"""Bashana's original per-Treant spell values and the ordinary battle/cast pipeline."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.carved_treant_cards import CARD,TREE,PROFILE,load_batch,register_carved_treant_cards
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,ChooseBranch,ChooseOneSpec,
    CostSpec,Game,IllegalAction,PlayCard,PlayerSetup,Rarity,Registry,Scenario,SelectChoice,SnapshotError,
    SpellSchool,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.carved_spells import CarvedSpellProfile,CastCarvedSpell,validate_spell
from hs_sim.engine.effects import (AddCostModifier,AddToHand,Buff,ChoiceOption,Damage,Draw,GainArmor,
    InvokeBehavior,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,CopyCard,MinionReference
from hs_sim.engine.battlecry_sources import TriggerBattlecry,RepeatBattlecry
from hs_sim.targets import canonical_digest

P='carved.test.'
HIT,GROW,DRAW,CHOICE,ONE,TEN=(P+x for x in ('hit4','grow4','draw4','choice4','one1','ten10'))
CTX=GenerationContext('carved-native-experiment','experimental')
OPS=tuple(P+x for x in ('copy','base','silence','bounce','discount','wrong','fail','trigger','echo'))


def registry(mode=None,pool=(HIT,),unknown=False):
    r=Registry('carved-treant-tests-v1.'+str((mode,pool,unknown)));register_carved_treant_cards(r)
    r.register_card(CardDefinition(P+'avatar','Hero',CardType.HERO,health=100,
        metadata=CardMetadata(False,(CardClass.WARRIOR,),Rarity.NONE)))
    r.register_card(CardDefinition(P+'plain','Plain',CardType.MINION,attack=1,health=20))
    for cid,body in ((HIT,lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),)),
            (GROW,lambda c:(Buff(c.target_id,2,2),)),(DRAW,lambda c:(Draw(c.player_id,1,c.source_id),)),
            (ONE,lambda c:(GainArmor(c.player_id,1),)),(TEN,lambda c:(GainArmor(c.player_id,10),)),
            (P+'fire',lambda c:())):
        r.register_behavior(cid,body)
        cost=1 if cid==ONE else 10 if cid==TEN else 4
        target=TargetSpec(relation='friendly',zones=(Zone.BOARD,),kinds=(CardType.MINION,)) if cid==GROW else TargetSpec() if cid==HIT else None
        d=CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,spell_school=SpellSchool.FIRE if cid==P+'fire' else SpellSchool.NATURE,
            targeting=target,metadata=CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON))
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    r.register_behavior(P+'choice_hit',lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),))
    r.register_behavior(P+'choice_armor',lambda c:(GainArmor(c.player_id,2),))
    r.register_behavior(P+'choice_both',lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),GainArmor(c.player_id,2)))
    choice=ChooseOneSpec((ChooseBranch('hit','Hit',P+'choice_hit',TargetSpec()),
        ChooseBranch('armor','Armor',P+'choice_armor')),ChooseBranch('both','Both',P+'choice_both',TargetSpec()))
    d=CardDefinition(CHOICE,CHOICE,CardType.SPELL,cost=4,spell_school=SpellSchool.NATURE,choose_one=choice,
        metadata=CardMetadata(True,(CardClass.DRUID,),Rarity.COMMON))
    r.register_card(d);r.register_pool_card(PoolCard.from_definition(r.card(CHOICE)))
    def fail(c):raise ResolutionError('Carved native deliberate failure')
    r.register_behavior(P+'fail',fail)
    bodies={
        'copy':lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id),),
        'base':lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,mode='base'),),
        'silence':lambda c:(Silence(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'discount':lambda c:(AddCostModifier(c.player_id,CostSpec(set_to=99,card_types=(CardType.SPELL,))),),
        'wrong':lambda c:(AddToHand(c.player_id,TREE,c.source_id,carved_spell_id=P+'fire'),),
        'trigger':lambda c:(TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]),source_id=c.source_id),),
        'fail':fail}
    for name,body in bodies.items():
        cid=P+name
        if cid!=P+'fail':r.register_behavior(cid,body)
        target=(TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly') if name in ('copy','base') else
            TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)) if name in ('silence','bounce','trigger') else None)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=target))
    def echo(c):
        original=next(b for b in reversed(c.state.battlecry_history) if b.completed and b.payload.card_id==TREE)
        return (RepeatBattlecry(c.player_id,c.source_id,original.id),)
    r.register_behavior(P+'echo',echo)
    r.register_card(CardDefinition(P+'echo','Native replay carrier',CardType.MINION,cost=1,health=4,battlecry=P+'echo'))
    def watch(c):
        if mode in ('cast_wait','silence_before'):
            if c.event.kind=='battlecry_started':
                rec=c.state.battlecry_history[dict(c.event.data)['battlecry_id']-1]
                if rec.payload.card_id!=TREE:return ()
                return (Silence(rec.source_id),)
            cast=c.state.cast_history[dict(c.event.data)['cast_id']-1]
            if cast.card_id not in (HIT,GROW,DRAW,CHOICE):return ()
        else:
            e=c.state.entities.get(c.event.target_id)
            if e is None or e.card_id!=TREE:return ()
            if mode=='fail_created':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode=='check_created':
                if not any(a.carved_spell_id for a in e.abilities):raise ResolutionError('Missing spell before first card-created notification')
                return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(P+'watch',watch)
    event='battlecry_started' if mode=='silence_before' else 'spell_cast_started' if mode=='cast_wait' else 'card_created'
    r.register_card(CardDefinition(P+'watch','Observer',CardType.MINION,health=50,triggers=(TriggerSpec(event,P+'watch'),)))
    members=(*pool,P+'fire')
    if unknown:
        r.register_pool_card(PoolCard(P+'unknown',CardType.SPELL,4,
            CardMetadata(True,(CardClass.DRUID,),Rarity.COMMON),spell_school=SpellSchool.NATURE));members=(*members,P+'unknown')
    r.register_pool(PoolDefinition(POOL_ID,'carved-native-pool-v1',CTX.target_id,CTX.mode,tuple(PoolMember(cid) for cid in members),complete=True))
    r.validate();return r


POOL_ID='constructed.cards'


class CarvedTreantTests(unittest.TestCase):
    def game(self,mode=None,pool=(HIT,),unknown=False,pid=1,cap=30,empty_board=False):
        self.mode,self.pool,self.unknown,self.pid=mode,pool,unknown,pid
        actor=PlayerSetup(P+'avatar',hand=(CARD,*OPS) if cap>1 else (CARD,),hand_cap=cap,
            deck=(P+'plain',)*8,board=(P+'watch',) if mode else (),mana=20,max_mana=20,mana_cap=20)
        other=PlayerSetup(P+'avatar',hand=OPS,hand_cap=30,deck=(P+'plain',)*8,
            board=() if empty_board else (P+'plain',),mana=20,max_mana=20,mana_cap=20)
        return Game.from_scenario(Scenario((actor,other) if pid==1 else (other,actor),active_player=pid,
            seed=41,generation_context=CTX),registry(mode,pool,unknown))

    def play(self,g,cid=CARD,target=None,eid=None):
        eid=eid or next(i for i in g.state.players[self.pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(self.pid,eid,target));return eid

    def trees(self,g):return [i for i in g.state.players[self.pid].hand if g.state.entities[i].card_id==TREE]
    def stored(self,g,eid):return next((a.carved_spell_id for a in g.state.entities[eid].abilities if a.kind=='battlecry'),None)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));r=registry(self.mode,self.pool,self.unknown)
        other=Game.from_snapshot(saved,r);self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry(self.mode,self.pool,self.unknown)).snapshot(),saved)
        for pid in (1,2):
            dto=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for name in ('carved_spell_id','resolution_frame','rng_state','_carved_spell_profiles'):
                self.assertNotIn('"'+name+'"',dto)
        return other

    def test_a00_complete_creator_treant_four_faces_and_43_nature_sources(self):
        d=load_batch();r=build_registry();self.assertEqual(len(d['official_observations']),4)
        self.assertEqual(len(d['existing_dependencies']),43)
        self.assertEqual((r.card(CARD).cost,r.card(CARD).attack,r.card(CARD).health),(7,4,4))
        self.assertEqual((r.card(TREE).cost,r.card(TREE).attack,r.card(TREE).health),(1,2,2))
        for row in (*d['cards'],*d['dependencies']):
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            self.assertEqual(r.card(row['record']['id']).metadata,metadata_from_record(row['record']))
        for row in d['existing_dependencies']:validate_spell(r,TREE,row['record']['id'])

    def test_a01_three_real_treants_receive_spell_before_acquisition_and_sum12(self):
        g=self.game(mode='check_created');self.play(g);ids=self.trees(g)
        self.assertEqual(len(ids),3);self.assertEqual([self.stored(g,i) for i in ids],[HIT]*3)
        self.assertEqual(sum(g.registry.pool_card(self.stored(g,i)).cost for i in ids),12)
        self.assertEqual(g.state.players[1].mana,13);self.assertFalse(g.state.cast_history)
        self.assertTrue(all(g.state.entities[i].base_cost==1 for i in ids))

    def test_a02_three_slot_budget_remains_exact_with_sparse_feasible_costs(self):
        g=self.game(pool=(ONE,HIT,TEN));self.play(g)
        costs=[g.registry.pool_card(self.stored(g,i)).cost for i in self.trees(g)]
        self.assertEqual(len(costs),3);self.assertEqual(sum(costs),12);self.assertIn(sorted(costs),([1,1,10],[4,4,4]))

    def test_a03_actual_minion_play_forwards_selected_target_and_casts_original_spell_without_payment(self):
        g=self.game();self.play(g);tree=self.trees(g)[0];target=g.state.players[2].hero_id
        before=g.state.players[1].mana;self.play(g,TREE,target,tree)
        cast,=g.state.cast_history
        self.assertEqual((cast.card_id,cast.player_id,cast.caster_id,cast.target_id,cast.origin),(HIT,1,tree,target,'effect'))
        self.assertEqual(g.state.players[1].mana,before-1);self.assertEqual(g.state.entities[target].health,97)
        self.assertEqual(g.state.battlecry_history[-1].payload.carved_spell_id,HIT);self.assertEqual(len(g.state.play_history),2)

    def test_a04_live_target_domain_and_friendly_relation_match_stored_spell(self):
        g=self.game(pool=(GROW,));source=self.play(g);tree=self.trees(g)[0];enemy=g.state.players[2].hero_id
        before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,TREE,enemy,tree)
        self.assertEqual(g.snapshot(),before);self.play(g,TREE,source,tree)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].max_health),(6,6))

    def test_a05_untargeted_spell_allows_untargeted_minion_and_uses_real_draw(self):
        g=self.game(pool=(DRAW,));self.play(g);tree=self.trees(g)[0];n=len(g.state.players[1].deck)
        self.play(g,TREE,eid=tree);self.assertEqual(len(g.state.players[1].deck),n-1)
        self.assertEqual(g.state.cast_history[-1].card_id,DRAW)

    def test_a06_choose_one_uses_original_cast_branch_and_drops_target_for_untargeted_branch(self):
        g=self.game(pool=(CHOICE,));self.play(g);target=g.state.players[2].hero_id
        for tree in tuple(self.trees(g)):self.play(g,TREE,target,tree)
        self.assertEqual(len(g.state.cast_history),3)
        for cast in g.state.cast_history:
            self.assertIsNone(cast.failure)
            self.assertEqual(cast.target_id,target if cast.branch_id=='hit' else None)
        self.portable(g)

    def test_a07_owner_sees_each_carved_spell_but_opponent_does_not_receive_held_values(self):
        g=self.game();self.play(g)
        self.assertIn(json.dumps(HIT),json.dumps(g.for_player(1).observe()))
        self.assertNotIn(json.dumps(HIT),json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2)))

    def test_a08_full_hand_uses_normal_per_card_overflow_and_does_not_reallocate(self):
        g=self.game(cap=1);self.play(g)
        self.assertEqual(len(self.trees(g)),1)
        burned=[e for e in g.state.entities.values() if e.card_id==TREE and e.zone==Zone.GRAVEYARD]
        self.assertEqual(len(burned),2);self.assertTrue(all(self.stored(g,e.id)==HIT for e in burned))
        self.assertNotIn(json.dumps(HIT),json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2)))

    def test_a09_unknown_eligible_nature_or_impossible_budget_rolls_back_before_creation(self):
        for args in ({'unknown':True},{'pool':(TEN,)}):
            with self.subTest(args=args):
                g=self.game(**args);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g)
                self.assertEqual(g.snapshot(),before)

    def test_a10_wrong_school_native_creation_rejects_without_allocating_a_treant(self):
        g=self.game();before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'wrong')
        self.assertEqual(g.snapshot(),before)

    def test_a11_each_creation_pause_restores_clone_replay_and_fixed_remaining_values(self):
        g=self.game(mode='create_wait');self.play(g);other=self.portable(g);count=0
        while g.state.pending_choice is not None:
            before=g.snapshot()
            with self.assertRaises(ResolutionError):self.choose(g,'bad')
            self.assertEqual(g.snapshot(),before)
            for match in (g,other):self.choose(match)
            self.assertEqual(g.snapshot(),other.snapshot());count+=1
        self.assertEqual(count,3);self.assertEqual(len(self.trees(g)),3);self.portable(g)

    def test_a12_actual_cast_pause_preserves_native_body_original_target_and_spell(self):
        g=self.game(mode='cast_wait');self.play(g);tree=self.trees(g)[0];target=g.state.players[2].hero_id
        self.play(g,TREE,target,tree);other=self.portable(g)
        for match in (g,other):self.choose(match)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[target].health,97)

    def test_a13_creation_reaction_failure_rolls_back_all_spells_cards_rng_and_payment(self):
        g=self.game(mode='fail_created');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_a14_current_copy_keeps_its_own_native_value_and_base_copy_is_explicit_empty(self):
        g=self.game();self.play(g);tree=self.trees(g)[0]
        self.play(g,P+'copy',tree);current=self.trees(g)[-1];self.assertEqual(self.stored(g,current),HIT)
        self.play(g,P+'base',tree);base=self.trees(g)[-1];self.assertIsNone(self.stored(g,base))
        n=len(g.state.cast_history);self.play(g,TREE,eid=base);self.assertEqual(len(g.state.cast_history),n)
        self.assertTrue(any(e.kind=='carved_spell_empty' for e in g.events))

    def test_a15_accepted_battlecry_keeps_frozen_spell_after_source_silence(self):
        g=self.game(mode='silence_before');self.play(g);tree=self.trees(g)[0];target=g.state.players[2].hero_id
        self.play(g,TREE,target,tree);self.assertEqual(g.state.cast_history[-1].card_id,HIT)
        self.assertTrue(g.state.entities[tree].silenced);self.assertIsNone(self.stored(g,tree))

    def test_a16_underlying_spell_hand_cost_does_not_charge_the_treant(self):
        g=self.game();self.play(g);tree=self.trees(g)[0];self.play(g,P+'discount');before=g.state.players[1].mana
        self.play(g,TREE,g.state.players[2].hero_id,tree);self.assertEqual(g.state.players[1].mana,before-1)

    def test_a17_second_seat_uses_its_own_native_spell_and_selected_target(self):
        g=self.game(pid=2);self.play(g);tree=self.trees(g)[0];target=g.state.players[1].hero_id
        self.play(g,TREE,target,tree);self.assertEqual(g.state.cast_history[-1].player_id,2)
        self.assertEqual(g.state.entities[target].health,97)

    def test_a18_rehashed_native_field_cannot_borrow_wrong_school_or_body(self):
        g=self.game();self.play(g);s=g.snapshot();tree=self.trees(g)[0]
        for value in (P+'fire','missing.carved'):
            altered=deepcopy(s)
            body=next(a for a in altered['state']['entities'][str(tree)]['abilities'] if a['kind']=='battlecry')
            body['carved_spell_id']=value
            altered['state_hash']=canonical_hash({k:v for k,v in altered.items() if k not in ('schema_version','events','events_hash','state_hash')})
            with self.subTest(value=value),self.assertRaises(SnapshotError):Game.from_snapshot(altered,registry())

    def test_a19_full_fixed_context_can_create_three_real_carved_values(self):
        from hs_sim.cards.candidate_generation_catalog import load_batch as catalog
        r=build_registry();all_roots=tuple(catalog()['candidate_root_ids'])
        r.register_pool(PoolDefinition(POOL_ID,'all-cn37-root-experiment-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(cid) for cid in all_roots),complete=False))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_06',hand=(CARD,),mana=10,max_mana=10),
            PlayerSetup('HERO_08')),generation_context=CTX,seed=41),r)
        g.apply(PlayCard(1,g.state.players[1].hand[0]));trees=[g.state.entities[i] for i in g.state.players[1].hand]
        values=[next(a.carved_spell_id for a in e.abilities if a.kind=='battlecry') for e in trees]
        self.assertEqual(len(values),3);self.assertEqual(sum(r.pool_card(cid).cost for cid in values),12)
        self.assertTrue(all(r.card(cid).spell_school==SpellSchool.NATURE for cid in values))

    def test_a20_actual_indirect_trigger_keeps_stored_spell_and_selects_a_target(self):
        g=self.game();self.play(g);tree=self.trees(g)[0]
        self.play(g,TREE,g.state.players[2].hero_id,tree);self.play(g,P+'trigger',tree)
        cast=g.state.cast_history[-1]
        self.assertEqual((cast.card_id,cast.caster_id),(HIT,tree));self.assertIsNotNone(cast.target_id)
        self.assertIsNone(cast.failure);self.portable(g)

    def test_a21_historical_replay_on_another_carrier_uses_original_spell_target_contract(self):
        g=self.game();self.play(g);tree=self.trees(g)[0]
        self.play(g,TREE,g.state.players[2].hero_id,tree);echo=self.play(g,P+'echo')
        cast=g.state.cast_history[-1]
        self.assertEqual((cast.card_id,cast.caster_id),(HIT,echo));self.assertIsNotNone(cast.target_id)
        self.assertIsNone(cast.failure);self.portable(g)

    def test_a22_carved_request_cannot_borrow_creator_unknown_or_completed_battlecry(self):
        g=self.game(mode='cast_wait');self.play(g);tree=self.trees(g)[0]
        self.play(g,TREE,g.state.players[2].hero_id,tree)
        own=g.state.battlecry_history[-1].id
        self.assertEqual(CastCarvedSpell(own).validate_in_state(g.state,g.registry).payload.carved_spell_id,HIT)
        for record_id in (1,own+100):
            with self.subTest(record_id=record_id),self.assertRaises(ValueError):
                CastCarvedSpell(record_id).validate_in_state(g.state,g.registry)
        self.choose(g)
        with self.assertRaises(ValueError):CastCarvedSpell(own).validate_in_state(g.state,g.registry)


if __name__=='__main__':unittest.main()
