"""Real next-card consumers over complete current prices and genuine owner clocks."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.qualified_next_cards import load_batch,NO_HEAL
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,CostSpec,EndTurn,Game,
    HealingKind,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.costs import capture_cost_input,capture_quote_fact,quote_accepted_hand,quote_cost,quote_generated_cost
from hs_sim.engine.effects import (AddCostModifier,AddToHand,ChoiceOption,Damage,Destroy,GrantHealthRule,
    Heal,InvokeBehavior,ReplaceHero,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import PaymentType,TribeChangeSpec
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.repeat_matching import validate_cost_quote_fact
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.temporary_cards import CreateTemporaryCard,MakeHandCardTemporary
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from hs_sim.engine.zones import CardReference,CopyCard,ModifyStoredCost,MoveCard
from hs_sim.targets import canonical_digest

FOX='CORE_DMF_511';CAVE='TLC_450';TICH='CORE_CATA_001';MURL='CATA_180';CROC='TLC_250'
ROOTS=(FOX,CAVE,TICH,MURL,CROC)


def registry(mode=None):
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
    for name,cost,tribes in (('plain',3,()),('demon',6,('demon',)),('murloc',4,('murloc',)),('small',2,('murloc',)),('unknown',2,None)):
        r.register_card(CardDefinition('k25c.'+name,name,CardType.MINION,cost=cost,attack=2,health=5,metadata=replace(meta,tribes=tribes)))
    r.register_card(CardDefinition('k25c.hero','New hero',CardType.HERO,health=30,metadata=meta))
    r.register_card(CardDefinition('k25c.leech','Leech',CardType.MINION,attack=2,health=5,
        keywords=(Keyword.CHARGE,Keyword.LIFESTEAL),metadata=meta))
    def ref(c):return CardReference.capture(c.state.entities[c.target_id])
    scripts={
        'temp':lambda c:(MakeHandCardTemporary(ref(c),c.state.turn,source_id=c.source_id),),
        'temp_floor':lambda c:(MakeHandCardTemporary(ref(c),c.state.turn,minimum_cost=1,source_id=c.source_id),),
        'new_temp':lambda c:(CreateTemporaryCard(c.player_id,'k25c.plain',c.state.turn,source_id=c.source_id),),
        'discount':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-2,card_types=(CardType.MINION,)),source_id=c.source_id),),
        'tax':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=2,card_types=(CardType.MINION,)),source_id=c.source_id),),
        'demon':lambda c:(ChangeMinionTribes(ref(c),TribeChangeSpec('set',('demon',)),c.source_id),),
        'murloc':lambda c:(ChangeMinionTribes(ref(c),TribeChangeSpec('set',('murloc',)),c.source_id),),
        'plain':lambda c:(ChangeMinionTribes(ref(c),TribeChangeSpec('set',()),c.source_id),),
        'wound':lambda c:tuple(Damage(c.state.players[p].hero_id,10,c.source_id)for p in (1,2)),
        'heal':lambda c:(Heal(c.target_id,3,c.source_id,HealingKind.SPELL),),
        'replace':lambda c:(ReplaceHero(c.player_id,'k25c.hero'),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'extra_own':lambda c:(QueueTurns((c.player_id,),c.source_id),),
        'extra_enemy':lambda c:(QueueTurns((3-c.player_id,),c.source_id),),
        'skip_own':lambda c:(SkipTurns(c.player_id,1,c.source_id),),
    }
    for name,body in scripts.items():
        key='k25c.op.'+name;r.register_behavior(key,body)
        target=(TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,CardType.SPELL),relation='friendly')
            if name in ('temp','temp_floor','demon','murloc','plain')else TargetSpec()if name in ('heal','kill','silence','bounce')else None)
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,targeting=target,metadata=meta))
    r.register_behavior('k25c.fail',lambda c:(AddToHand(c.player_id,'missing.k25c'),))
    def wait(c):
        if mode=='paid_temp':
            play=next((p for p in reversed(c.state.play_history)if p.source_id==c.event.source_id),None)
            if play is None or play.submitted_cost is None or play.submitted_cost.quote.quote_input.hand_lifetime is None:return ()
        elif mode!='start'and c.event.source_id is not None and c.state.entities[c.event.source_id].card_id not in ROOTS:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(
            InvokeBehavior('k25c.fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior('k25c.wait',wait)
    if mode in ('install','commit','start','health_install','paid_temp'):
        event={'install':'cost_modifier_added','commit':'card_committed','start':'turn_started',
            'health_install':'ability_granted','paid_temp':'card_committed'}[mode]
        r.register_card(CardDefinition('k25c.watch','Observer',CardType.MINION,health=10,metadata=meta,
            triggers=(TriggerSpec(event,'k25c.wait'),)))
    r.register_behavior('k25c.start_heal',lambda c:(Heal(c.state.players[2].hero_id,3,c.source_id),))
    r.register_card(CardDefinition('k25c.healer','Start healer',CardType.MINION,health=5,metadata=meta,
        triggers=(TriggerSpec('turn_started','k25c.start_heal'),)))
    return r


class QualifiedNextCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,enemy_hand=(),board=(),enemy_board=(),mode=None,mana=40):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=('CORE_CS2_182',)*12,mana=mana,max_mana=mana,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy_board,deck=('CORE_CS2_182',)*12,mana=40,max_mana=40,mana_cap=40)),seed=401),registry(mode)if mode else self.r)
    def eid(self,g,cid,p=None,zone='hand'):
        p=p or g.state.active_player;return next(i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        i=self.eid(g,cid);g.apply(PlayCard(g.state.active_player,i,target_id=target));return i
    def quote(self,g,cid,p=1):
        s=g.state;return quote_cost(s,g.registry,s.entities[self.eid(g,cid,p)])
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def portable(self,g):
        s=g.snapshot();other=Game.from_snapshot(s,registry(self.mode));self.assertEqual(s,other.snapshot());self.assertEqual(s,g.clone().snapshot())
        self.assertEqual(s,replay(build_replay(g),registry(self.mode)).snapshot());return other
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def reject(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry(self.mode))

    def test_full_five_pinned_roots_and_live_hero_aura_not_body_immunity(self):
        rows=load_batch()['cards'];self.assertEqual(len(rows),5)
        for row in rows:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256']);c=self.r.card(raw['id'])
            self.assertEqual((c.cost,c.attack,c.health),(raw['cost'],raw['attack'],raw['health']));self.assertIsNotNone(c.battlecry)
        self.assertEqual(self.r.card(TICH).keyword_auras[0].keyword,Keyword.IMMUNE)
        self.assertNotIn(Keyword.IMMUNE,self.r.card(TICH).keywords)

    def test_fox_qualifies_structural_combo_not_the_next_ordinary_card(self):
        g=self.game((FOX,'CORE_EX1_131','CORE_EX1_008'));self.play(g,FOX)
        self.assertEqual(self.quote(g,'CORE_EX1_131').amount,0);self.assertEqual(self.quote(g,'CORE_EX1_008').amount,1)
        self.play(g,'CORE_EX1_008');self.assertEqual(self.quote(g,'CORE_EX1_131').amount,0)
        mana=g.state.players[1].mana;self.play(g,'CORE_EX1_131');self.assertEqual(g.state.players[1].mana,mana)
        self.assertFalse(g.state.players[1].cost_modifiers);self.portable(g)

    def test_fox_preview_is_pure_and_unused_discount_expires_this_turn(self):
        g=self.game((FOX,'CORE_EX1_131'));self.play(g,FOX);before=g.snapshot()
        for _ in range(3):self.assertEqual(self.quote(g,'CORE_EX1_131').amount,0)
        self.assertEqual(before,g.snapshot());self.end(g);self.assertEqual(self.quote(g,'CORE_EX1_131').amount,2);self.portable(g)

    def test_fox_frozen_quote_replays_full_current_combo_attachments(self):
        g=self.game((FOX,'CORE_EX1_131'));self.play(g,FOX);s=g.state;entity=s.entities[self.eid(g,'CORE_EX1_131')]
        fact=capture_quote_fact(s,g.registry,capture_cost_input(entity));validate_cost_quote_fact(g.registry,fact)
        stripped=replace(fact.quote_input,abilities=tuple(a for a in fact.quote_input.abilities if a.kind!='combo'))
        with self.assertRaises(ValueError):validate_cost_quote_fact(g.registry,replace(fact,quote_input=stripped))
        self.assertEqual(quote_generated_cost(s,g.registry,1,'CORE_EX1_131').amount,0)

    def test_temporary_discount_uses_physical_mark_and_not_equal_card_name(self):
        g=self.game((CAVE,'k25c.op.temp','k25c.plain','k25c.plain'));self.play(g,CAVE)
        same=[i for i in g.state.players[1].hand if g.state.entities[i].card_id=='k25c.plain'];self.play(g,'k25c.op.temp',same[1])
        s=g.state;self.assertEqual([quote_cost(s,g.registry,s.entities[i]).amount for i in same],[3,1])
        g.apply(PlayCard(1,same[0]));self.assertEqual(len(g.state.players[1].cost_modifiers),1)
        g.apply(PlayCard(1,same[1]));self.assertFalse(g.state.players[1].cost_modifiers);self.portable(g)

    def test_temporary_source_death_and_turns_do_not_expire_unused_next(self):
        g=self.game((CAVE,'k25c.op.kill','k25c.op.new_temp'));source=self.play(g,CAVE);self.play(g,'k25c.op.kill',source)
        self.end(g);self.end(g);self.play(g,'k25c.op.new_temp');self.assertEqual(self.quote(g,'k25c.plain').amount,1)
        self.play(g,'k25c.plain');self.assertFalse(g.state.players[1].cost_modifiers);self.portable(g)

    def test_temporary_floor_and_accepted_hand_receipt_survive_source_leaving_hand(self):
        g=self.game((CAVE,'k25c.op.temp_floor','k25c.op.wound'));self.play(g,CAVE);e=self.eid(g,'k25c.op.wound')
        self.play(g,'k25c.op.temp_floor',e);self.assertEqual(self.quote(g,'k25c.op.wound').amount,1)
        self.play(g,'k25c.op.wound');play=next(p for p in g.state.play_history if p.source_id==e)
        self.assertIsNotNone(play.submitted_cost.quote.quote_input.hand_lifetime)
        self.assertEqual(quote_accepted_hand(g.state,g.registry,play).amount,1)
        self.assertEqual(self.hero(g).health,20);self.portable(g)

    def test_temporary_hypothetical_fresh_face_is_not_a_temporary_hand_card(self):
        g=self.game((CAVE,'k25c.plain'));self.play(g,CAVE);s=g.state
        self.assertEqual(quote_generated_cost(s,g.registry,1,'k25c.plain').amount,3)
        self.assertEqual(self.quote(g,'k25c.plain').amount,3);self.portable(g)

    def test_tichondrius_zeroes_current_demon_and_leaves_other_minions_normal(self):
        g=self.game((TICH,'k25c.demon','k25c.plain'));source=self.play(g,TICH)
        self.assertIn(Keyword.IMMUNE,self.hero(g).keywords);self.assertNotIn(Keyword.IMMUNE,g.state.entities[source].keywords)
        self.assertEqual(self.quote(g,'k25c.demon').amount,0);self.assertEqual(self.quote(g,'k25c.plain').amount,3)
        self.play(g,'k25c.plain');self.assertEqual(self.quote(g,'k25c.demon').amount,0)
        mana=g.state.players[1].mana;self.play(g,'k25c.demon');self.assertEqual(g.state.players[1].mana,mana);self.portable(g)

    def test_tichondrius_current_tribe_change_affects_zero_and_consumption(self):
        g=self.game((TICH,'k25c.op.plain','k25c.op.demon','k25c.demon','k25c.plain'));self.play(g,TICH)
        self.play(g,'k25c.op.plain',self.eid(g,'k25c.demon'));self.assertEqual(self.quote(g,'k25c.demon').amount,6)
        self.play(g,'k25c.op.demon',self.eid(g,'k25c.plain'));self.assertEqual(self.quote(g,'k25c.plain').amount,0);self.portable(g)

    def test_tichondrius_silence_ends_aura_but_next_demon_retains_until_turn_end(self):
        g=self.game((TICH,'k25c.op.silence','k25c.demon'));source=self.play(g,TICH);self.play(g,'k25c.op.silence',source)
        self.assertNotIn(Keyword.IMMUNE,self.hero(g).keywords);self.assertEqual(self.quote(g,'k25c.demon').amount,0)
        self.end(g);self.assertEqual(self.quote(g,'k25c.demon').amount,6);self.portable(g)

    def test_murloc_qualifies_final_current_cost_including_later_reduction(self):
        g=self.game((MURL,'k25c.op.discount','k25c.murloc'));self.play(g,MURL)
        self.assertEqual(self.quote(g,'k25c.murloc').payment,PaymentType.MANA)
        self.play(g,'k25c.op.discount');q=self.quote(g,'k25c.murloc');self.assertEqual((q.amount,q.payment),(2,PaymentType.HEALTH))
        mana=g.state.players[1].mana;self.play(g,'k25c.murloc')
        self.assertEqual(g.state.players[1].mana,mana);self.assertEqual(self.hero(g).health,28)
        self.assertFalse(any(m.maximum_cost is not None for m in g.state.players[1].cost_modifiers));self.portable(g)

    def test_murloc_later_tax_excludes_small_card_without_spending_qualification(self):
        g=self.game((MURL,'k25c.op.tax','k25c.small'));self.play(g,MURL);self.play(g,'k25c.op.tax')
        q=self.quote(g,'k25c.small');self.assertEqual((q.amount,q.payment),(4,PaymentType.MANA));self.play(g,'k25c.small')
        self.assertTrue(any(m.maximum_cost==3 for m in g.state.players[1].cost_modifiers));self.assertEqual(self.hero(g).health,30);self.portable(g)

    def test_murloc_current_tribe_and_generated_full_price_use_original_shared_quote(self):
        g=self.game((MURL,'k25c.op.murloc','k25c.plain'));self.play(g,MURL)
        self.play(g,'k25c.op.murloc',self.eid(g,'k25c.plain'));self.assertEqual(self.quote(g,'k25c.plain').payment,PaymentType.HEALTH)
        q=quote_generated_cost(g.state,g.registry,1,'k25c.murloc',cost=CostSpec(delta=-2))
        self.assertEqual((q.amount,q.payment),(2,PaymentType.HEALTH));self.assertTrue(g.state.players[1].cost_modifiers)

    def test_murloc_zero_mana_still_has_public_health_paid_action(self):
        g=self.game((MURL,'k25c.small'),mana=2);self.play(g,MURL);self.assertEqual(g.state.players[1].mana,0)
        listing=g.for_player(1).legal_actions();self.assertIsNotNone(listing['actions']);self.play(g,'k25c.small')
        self.assertEqual((g.state.players[1].mana,self.hero(g).health),(0,28));self.portable(g)

    def test_health_payment_is_not_waived_by_real_tichondrius_immunity(self):
        g=self.game((TICH,MURL,'k25c.small'));self.play(g,TICH);self.play(g,MURL);self.assertIn(Keyword.IMMUNE,self.hero(g).keywords)
        self.play(g,'k25c.small');self.assertEqual(self.hero(g).health,28)
        self.assertFalse(any(e.kind=='damage_dealt'and e.target_id==self.hero(g).id for e in g.events));self.portable(g)

    def test_murloc_unknown_tribe_is_explicit_and_quote_is_pure(self):
        g=self.game((MURL,'k25c.unknown'));self.play(g,MURL);before=g.snapshot()
        with self.assertRaises(UnsupportedDefinitionError):self.quote(g,'k25c.unknown')
        self.assertEqual(before,g.snapshot())

    def test_croc_blocks_enemy_hero_healing_but_not_owner_or_minions(self):
        g=self.game((CROC,'k25c.op.wound','k25c.op.heal','k25c.op.heal'));self.play(g,CROC);self.play(g,'k25c.op.wound')
        self.play(g,'k25c.op.heal',self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,20)
        self.play(g,'k25c.op.heal',self.hero(g).id);self.assertEqual(self.hero(g).health,23);self.portable(g)

    def test_croc_source_death_does_not_end_prevention_and_enemy_hero_replacement_preserves_it(self):
        g=self.game((CROC,'k25c.op.kill','k25c.op.wound'),enemy_hand=('k25c.op.replace','k25c.op.heal'))
        source=self.play(g,CROC);self.play(g,'k25c.op.kill',source);self.play(g,'k25c.op.wound');self.end(g)
        self.play(g,'k25c.op.replace');self.play(g,'k25c.op.heal',self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,20);self.portable(g)

    def test_croc_next_owner_start_expires_before_start_healing_reactions(self):
        g=self.game((CROC,'k25c.op.wound'),enemy_board=('k25c.healer',));self.play(g,CROC);self.play(g,'k25c.op.wound')
        self.end(g);self.assertEqual(self.hero(g,2).health,20);self.end(g)
        self.assertEqual(self.hero(g,2).health,23);self.assertFalse(any(a.health_rule_expiry is not None for a in self.hero(g,2).abilities));self.portable(g)

    def test_croc_extra_enemy_turn_and_skipped_owner_slot_do_not_expire(self):
        g=self.game((CROC,'k25c.op.skip_own','k25c.op.wound'),enemy_hand=('k25c.op.heal','k25c.op.heal'))
        self.play(g,CROC);self.play(g,'k25c.op.skip_own');self.play(g,'k25c.op.wound');self.end(g)
        self.play(g,'k25c.op.heal',self.hero(g,2).id);self.end(g);self.assertEqual(g.state.active_player,2)
        self.play(g,'k25c.op.heal',self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,20);self.end(g)
        self.assertEqual(g.state.active_player,1);self.assertFalse(any(a.health_rule_expiry is not None for a in self.hero(g,2).abilities));self.portable(g)

    def test_croc_immediate_extra_own_turn_reaches_the_actual_deadline(self):
        g=self.game((CROC,'k25c.op.extra_own'));self.play(g,CROC);self.play(g,'k25c.op.extra_own');self.end(g)
        self.assertEqual(g.state.active_player,1);self.assertFalse(any(a.health_rule_expiry is not None for a in self.hero(g,2).abilities));self.portable(g)

    def test_croc_prevents_real_combat_lifesteal_using_shared_health_rules(self):
        g=self.game((CROC,'k25c.op.wound'),enemy_hand=('k25c.leech',));self.play(g,CROC);self.play(g,'k25c.op.wound');self.end(g)
        leech=self.play(g,'k25c.leech');g.apply(Attack(2,leech,self.hero(g).id))
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(18,20));self.assertTrue(any(e.kind=='lifesteal'for e in g.events));self.portable(g)

    def test_filtered_cost_install_waiting_restores_and_spends_only_once(self):
        for cid in (FOX,CAVE,TICH,MURL):
            g=self.game((cid,),board=('k25c.watch',),mode='install');self.play(g,cid);self.assertIsNotNone(g.state.pending_choice)
            saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.choose(g,'bad')
            self.assertEqual(saved,g.snapshot());other=self.portable(g);self.choose(g);self.choose(other)
            self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.players[1].cost_modifiers),1)

    def test_full_current_price_fact_rejects_tampered_lifetime_and_threshold(self):
        g=self.game((CAVE,'k25c.op.temp','k25c.plain'));self.play(g,CAVE);e=self.eid(g,'k25c.plain');self.play(g,'k25c.op.temp',e)
        s=g.state;fact=capture_quote_fact(s,g.registry,capture_cost_input(s.entities[e]));validate_cost_quote_fact(g.registry,fact)
        with self.assertRaises(ValueError):validate_cost_quote_fact(g.registry,replace(fact,quote_input=replace(fact.quote_input,hand_lifetime=None)))
        g=self.game((MURL,'k25c.small'));self.play(g,MURL);s=g.state;e=s.entities[self.eid(g,'k25c.small')]
        fact=capture_quote_fact(s,g.registry,capture_cost_input(e));validate_cost_quote_fact(g.registry,fact)
        wrong=tuple(replace(c,modifier=replace(c.modifier,maximum_cost=1))if c.modifier is not None and c.modifier.maximum_cost is not None else c for c in fact.contributions)
        with self.assertRaises(ValueError):validate_cost_quote_fact(g.registry,replace(fact,contributions=wrong))
        saved=g.snapshot()
        saved['state']['players']['1']['cost_modifiers'][0]['maximum_cost']=-1;self.reject(saved)

    def test_owner_health_deadline_snapshot_rejects_future_or_changed_owner_clock(self):
        g=self.game((CROC,));self.play(g,CROC);saved=g.snapshot();abilities=saved['state']['entities'][str(self.hero(g,2).id)]['abilities']
        row=next(a for a in abilities if a['health_rule_expiry']is not None);row['health_rule_expiry']['owner_turn_index']+=1;self.reject(saved)

    def test_previous269_layout_rejected_and_no_new_private_fact_in_player_dto(self):
        g=self.game((CROC,FOX));self.play(g,CROC);self.play(g,FOX);saved=g.snapshot();self.assertEqual(saved['schema_version'],SNAPSHOT_SCHEMA_VERSION)
        saved['schema_version']=269
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())
        for p in (1,2):
            wire=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for hidden in ('health_rule_expiry','submitted_cost','quote_input','resolution_frame'):self.assertNotIn(hidden,wire)

    def test_paid_temporary_spell_waiting_preserves_lifetime_payment_and_one_use(self):
        g=self.game((CAVE,'k25c.op.temp_floor','k25c.op.wound'),board=('k25c.watch',),mode='paid_temp')
        self.play(g,CAVE);self.play(g,'k25c.op.temp_floor',self.eid(g,'k25c.op.wound'));self.play(g,'k25c.op.wound')
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.hero(g).health,30)
        play=g.state.play_history[-1];self.assertIsNotNone(play.submitted_cost.quote.quote_input.hand_lifetime)
        self.assertFalse(g.state.players[1].cost_modifiers);saved=g.snapshot();mana=g.state.players[1].mana
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);other=self.portable(g);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual((self.hero(g).health,g.state.players[1].mana),(20,mana))

    def test_croc_grant_waiting_restores_single_original_owner_deadline(self):
        g=self.game((CROC,),board=('k25c.watch',),mode='health_install');self.play(g,CROC)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(sum(a.health_rule_expiry is not None for a in self.hero(g,2).abilities),1)
        self.end(g);self.end(g);self.assertFalse(any(a.health_rule_expiry is not None for a in self.hero(g,2).abilities));self.portable(g)
