"""Frozen logical player damage and taxes over an actual future owner interval."""
from copy import deepcopy
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.player_period_cards import load_batch,PREFIX
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,
    PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Damage,Destroy,GrantKeyword,
    InvokeBehavior,ReplaceHero,RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.player_effects import PlayerEffectDamage,RemovePlayerEffect
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash,player_effect_from_dict
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from hs_sim.targets import canonical_digest

MOG='CORE_RLK_706';NEO='CORE_SCH_713'


def registry(mode=None):
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
    r.register_card(CardDefinition('k25p.hero','New hero',CardType.HERO,health=30,metadata=meta))
    r.register_card(CardDefinition('k25p.sheep_face','New face',CardType.MINION,attack=1,health=1,metadata=meta))
    def root(c):return next(e for e in c.state.players[c.player_id].player_effects if e.spec_id==PREFIX+'mograine')
    def delayed(c):
        instance=root(c);hit=PlayerEffectDamage(c.player_id,instance,c.state.players[3-c.player_id].hero_id,3)
        return (RequestChoice(c.player_id,(ChoiceOption('hit','Continue',(hit,)),ChoiceOption('bad','Fail',(
            hit,InvokeBehavior('k25p.fail',c.source_id,c.player_id)))),c.source_id),)
    def retired(c):
        instance=root(c)
        return (RemovePlayerEffect(c.player_id,instance.id),RequestChoice(c.player_id,(ChoiceOption('hit','Continue',(
            PlayerEffectDamage(c.player_id,instance,c.state.players[3-c.player_id].hero_id,3),)),),c.source_id))
    operations={
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'sheep':lambda c:(Transform(c.target_id,'k25p.sheep_face'),),
        'take':lambda c:(ChangeControl(c.target_id,c.player_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'leech':lambda c:(GrantKeyword(c.target_id,Keyword.LIFESTEAL,c.source_id),),
        'wound':lambda c:(Damage(c.state.players[c.player_id].hero_id,10,c.source_id),),
        'replace':lambda c:(ReplaceHero(c.player_id,'k25p.hero',hero_power_card_id='HERO_08bp'),),
        'extra_own':lambda c:(QueueTurns((c.player_id,),c.source_id),),
        'extra_enemy':lambda c:(QueueTurns((3-c.player_id,),c.source_id),),
        'skip_enemy':lambda c:(SkipTurns(3-c.player_id,1,c.source_id),),
        'immune':lambda c:(GrantKeyword(c.state.players[3-c.player_id].hero_id,Keyword.IMMUNE,c.source_id),),
        'summon':lambda c:(Summon(c.player_id,MOG),),
        'delayed':delayed,'retired':retired,
    }
    from hs_sim.engine import TargetSpec
    r.register_behavior('k25p.fail',lambda c:(AddToHand(c.player_id,'missing.k25p'),))
    for name,fn in operations.items():
        r.register_behavior('k25p.'+name,fn)
        r.register_card(CardDefinition('k25p.'+name,name,CardType.SPELL,on_play='k25p.'+name,
            targeting=TargetSpec()if name in ('kill','silence','sheep','take','bounce','leech')else None,metadata=meta))
    def wait(c):
        if mode=='install'and (c.event.source_id is None or c.state.entities[c.event.source_id].card_id not in (MOG,NEO)):return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(
            InvokeBehavior('k25p.fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior('k25p.wait',wait)
    if mode is not None:
        event={'install':'player_effect_added','end':'turn_ended','tax':'cost_modifier_added'}[mode]
        r.register_card(CardDefinition('k25p.watch','Observer',CardType.MINION,health=10,metadata=meta,
            triggers=(TriggerSpec(event,'k25p.wait'),)))
    return r


class PlayerPeriodCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,enemy_hand=(),board=(),mode=None):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=('CORE_CS2_182',)*12,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,deck=('CORE_CS2_182',)*12,mana=40,max_mana=40,mana_cap=40)),seed=391),
            registry(mode)if mode else self.r)
    def eid(self,g,cid,p=None,zone='hand'):
        p=p or g.state.active_player;return next(e for e in getattr(g.state.players[p],zone)if g.state.entities[e].card_id==cid)
    def play(self,g,cid,target=None):
        p=g.state.active_player;i=self.eid(g,cid);g.apply(PlayCard(p,i,target_id=target));return i
    def hp(self,g,p=2):return g.state.entities[g.state.players[p].hero_id].health
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def quote(self,g,cid,p=2):
        s=g.state;return quote_cost(s,g.registry,s.entities[self.eid(g,cid,p)]).amount
    def portable(self,g):
        s=g.snapshot();other=Game.from_snapshot(s,registry(self.mode))
        self.assertEqual(s,other.snapshot());self.assertEqual(s,g.clone().snapshot())
        self.assertEqual(s,replay(build_replay(g),registry(self.mode)).snapshot());return other
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def hits(self,g):
        return [dict(health_result(e).payload())for e in g.events if e.kind=='health_resolved'and health_result(e).source_card_id==MOG]
    def reject(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry(self.mode))

    def test_two_pinned_complete_roots_and_original_metadata(self):
        rows=load_batch()['cards'];self.assertEqual(len(rows),2)
        for row in rows:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256']);c=self.r.card(raw['id'])
            self.assertEqual((c.cost,c.attack,c.health),(raw['cost'],raw['attack'],raw['health']))
        self.assertEqual(self.r.card(MOG).metadata.runes.blood,3)

    def test_mograine_own_end_only_multiple_turns_without_source(self):
        g=self.game((MOG,'k25p.kill'));source=self.play(g,MOG);self.play(g,'k25p.kill',source)
        self.end(g);self.assertEqual(self.hp(g),27);self.end(g);self.assertEqual(self.hp(g),27)
        self.end(g);self.assertEqual(self.hp(g),24);self.assertEqual(len(self.hits(g)),2);self.portable(g)

    def test_mograine_silence_and_transformed_source_keep_original_face_and_packet(self):
        g=self.game((MOG,'k25p.silence','k25p.sheep'));source=self.play(g,MOG)
        original=next(iter(g.state.players[1].player_effects)).source_allocation
        self.play(g,'k25p.silence',source);self.play(g,'k25p.sheep',source);self.end(g)
        hit=self.hits(g)[0];self.assertEqual((hit['source_id'],hit['source_controller'],hit['source_card_id']),(source,1,MOG))
        self.assertEqual(hit['source_zone_epoch'],dict(original)['zone_epoch']);self.assertEqual(self.hp(g),27);self.portable(g)

    def test_mograine_control_change_does_not_move_beneficiary_or_damage_source(self):
        g=self.game((MOG,),enemy_hand=('k25p.take',));source=self.play(g,MOG);self.end(g)
        self.play(g,'k25p.take',source);self.assertEqual(g.state.entities[source].controller,2)
        self.end(g);self.assertEqual((self.hp(g,1),self.hp(g)),(30,27));self.end(g)
        self.assertEqual(self.hp(g),24);self.assertTrue(all(h['source_controller']==1 for h in self.hits(g)));self.portable(g)

    def test_mograine_original_granted_lifesteal_is_not_a_logical_player_keyword(self):
        g=self.game((MOG,'k25p.leech','k25p.wound'));source=self.play(g,MOG)
        self.play(g,'k25p.leech',source);self.play(g,'k25p.wound');self.end(g)
        self.assertEqual((self.hp(g,1),self.hp(g)),(20,27));self.assertFalse(any(e.kind=='lifesteal'for e in g.events));self.portable(g)

    def test_mograine_independent_instances_stack_without_ongoing_area_limit(self):
        g=self.game((MOG,MOG));self.play(g,MOG);self.play(g,MOG);self.end(g)
        self.assertEqual(self.hp(g),24);self.assertEqual(len(g.state.players[1].player_effects),2);self.portable(g)

    def test_mograine_summon_without_battlecry_has_no_permanent_effect(self):
        g=self.game(('k25p.summon',));self.play(g,'k25p.summon');self.end(g)
        self.assertEqual(self.hp(g),30);self.assertFalse(g.state.players[1].player_effects)

    def test_mograine_bounce_and_new_battlecry_add_separate_instances(self):
        g=self.game((MOG,'k25p.bounce'));source=self.play(g,MOG);self.play(g,'k25p.bounce',source);self.play(g,MOG)
        instances=g.state.players[1].player_effects;self.assertEqual(len(instances),2)
        self.assertNotEqual(instances[0].source_allocation,instances[1].source_allocation);self.end(g)
        self.assertEqual(self.hp(g),24);self.portable(g)

    def test_mograine_uses_current_enemy_hero_after_both_replacements(self):
        g=self.game((MOG,'k25p.replace'),enemy_hand=('k25p.replace',));self.play(g,MOG);self.play(g,'k25p.replace');self.end(g)
        old=g.state.players[2].hero_id;self.play(g,'k25p.replace');self.assertNotEqual(g.state.players[2].hero_id,old)
        self.end(g);self.end(g);self.assertEqual(self.hp(g),24);self.portable(g)

    def test_mograine_real_extra_own_turn_has_another_ordinary_end(self):
        g=self.game((MOG,'k25p.extra_own'));self.play(g,MOG);self.play(g,'k25p.extra_own');self.end(g)
        self.assertEqual(g.state.active_player,1);self.assertEqual(self.hp(g),27);self.end(g)
        self.assertEqual(self.hp(g),24);self.portable(g)

    def test_mograine_shared_immunity_prevents_damage_without_changing_source(self):
        g=self.game((MOG,'k25p.immune'));self.play(g,MOG);self.play(g,'k25p.immune');self.end(g)
        self.assertEqual(self.hp(g),30);self.assertEqual(self.hits(g)[0]['prevention'],'immune');self.portable(g)

    def test_captured_logical_damage_request_itself_survives_choice_and_failure(self):
        g=self.game((MOG,'k25p.delayed'));self.play(g,MOG);self.play(g,'k25p.delayed');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(saved,g.snapshot());other=self.portable(g);self.choose(g,'hit');self.choose(other,'hit')
        self.assertEqual(self.hp(g),27);self.assertEqual(g.snapshot(),other.snapshot())

    def test_accepted_logical_damage_finishes_after_instance_removal(self):
        g=self.game((MOG,'k25p.retired'));self.play(g,MOG);self.play(g,'k25p.retired')
        self.assertFalse(g.state.players[1].player_effects);other=self.portable(g)
        self.choose(g,'hit');self.choose(other,'hit');self.assertEqual(self.hp(g),27);self.assertEqual(g.snapshot(),other.snapshot())

    def test_captured_end_trigger_waiting_restores_original_source_after_transform(self):
        g=self.game((MOG,'k25p.sheep'),board=('k25p.watch',),mode='end')
        source=self.play(g,MOG);self.play(g,'k25p.sheep',source);self.end(g);self.assertEqual(self.hp(g),30)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);self.choose(g);self.choose(other)
        self.assertEqual(self.hp(g),27);self.assertEqual(g.snapshot(),other.snapshot())

    def test_neophyte_pending_tax_targets_only_first_real_enemy_turn(self):
        g=self.game((NEO,),enemy_hand=('CORE_CS2_029','CORE_EX1_008'));self.play(g,NEO)
        self.assertEqual(self.quote(g,'CORE_CS2_029'),4);self.end(g)
        self.assertEqual(self.quote(g,'CORE_CS2_029'),5);self.assertEqual(self.quote(g,'CORE_EX1_008'),1)
        self.assertFalse(g.state.players[2].player_effects);self.end(g)
        self.assertEqual(self.quote(g,'CORE_CS2_029'),4);self.end(g);self.assertEqual(self.quote(g,'CORE_CS2_029'),4);self.portable(g)

    def test_neophyte_extra_own_turn_before_enemy_start_does_not_spend_pending(self):
        g=self.game((NEO,'k25p.extra_own'),enemy_hand=('CORE_CS2_029',));self.play(g,NEO);self.play(g,'k25p.extra_own');self.end(g)
        self.assertEqual(g.state.active_player,1);self.assertEqual(self.quote(g,'CORE_CS2_029'),4)
        self.assertEqual(len(g.state.players[2].player_effects),1);self.end(g)
        self.assertEqual(self.quote(g,'CORE_CS2_029'),5);self.portable(g)

    def test_neophyte_skipped_enemy_slot_keeps_pending_until_actual_start(self):
        g=self.game((NEO,'k25p.skip_enemy'),enemy_hand=('CORE_CS2_029',));self.play(g,NEO);self.play(g,'k25p.skip_enemy');self.end(g)
        self.assertEqual(g.state.active_player,1);self.assertEqual(self.quote(g,'CORE_CS2_029'),4)
        self.end(g);self.assertEqual(g.state.active_player,2);self.assertEqual(self.quote(g,'CORE_CS2_029'),5);self.portable(g)

    def test_neophyte_source_death_does_not_cancel_multiple_independent_taxes(self):
        g=self.game((NEO,NEO,'k25p.kill'),enemy_hand=('CORE_CS2_029',));source=self.play(g,NEO);self.play(g,NEO)
        self.play(g,'k25p.kill',source);self.end(g);self.assertEqual(self.quote(g,'CORE_CS2_029'),6)
        self.end(g);self.assertEqual(self.quote(g,'CORE_CS2_029'),4);self.portable(g)

    def test_neophyte_actual_spell_payment_consumes_mana_at_taxed_price(self):
        g=self.game((NEO,),enemy_hand=('CORE_CS2_029',));self.play(g,NEO);self.end(g)
        mana=g.state.players[2].mana;self.play(g,'CORE_CS2_029',g.state.players[1].hero_id)
        self.assertEqual(g.state.players[2].mana,mana-5);self.portable(g)

    def test_installation_waiting_does_not_duplicate_instances(self):
        for cid in (MOG,NEO):
            g=self.game((cid,),board=('k25p.watch',),mode='install');self.play(g,cid);other=self.portable(g)
            self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
            self.assertEqual(sum(len(p.player_effects)for p in g.state.players.values()),1)

    def test_neophyte_start_tax_waiting_restores_ongoing_turn_and_single_layer(self):
        g=self.game((NEO,),board=('k25p.watch',),enemy_hand=('CORE_CS2_029',),mode='tax')
        self.play(g,NEO);self.end(g);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.quote(g,'CORE_CS2_029'),5)
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);other=self.portable(g);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.players[2].cost_modifiers),1)
        self.assertFalse(g.state.players[2].player_effects)

    def test_source_capture_snapshot_rejects_wrong_owner_face_future_epoch(self):
        g=self.game((MOG,));self.play(g,MOG);saved=g.snapshot()
        for field,value in (('source_player_id',2),('source_card_id','CORE_CS2_182')):
            bad=deepcopy(saved);bad['state']['players']['1']['player_effects'][0][field]=value;self.reject(bad)
        bad=deepcopy(saved);fact=bad['state']['players']['1']['player_effects'][0]['source_allocation']
        next(r for r in fact if r[0]=='zone_epoch')[1]=9999;self.reject(bad)

    def test_logical_damage_cannot_borrow_other_player_or_missing_capture(self):
        g=self.game((MOG,));self.play(g,MOG);instance=g.state.players[1].player_effects[0]
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        with self.assertRaises(ValueError):codec.encode(PlayerEffectDamage(2,instance,g.state.players[1].hero_id,3))
        with self.assertRaises(ValueError):PlayerEffectDamage(1,replace(instance,source_allocation=None,source_player_id=None),g.state.players[2].hero_id,3)

    def test_previous_schema_268_rejected_and_current_json_decoder_preserves_capture(self):
        g=self.game((MOG,));self.play(g,MOG);s=g.snapshot();self.assertEqual(s['schema_version'],SNAPSHOT_SCHEMA_VERSION)
        raw=s['state']['players']['1']['player_effects'][0]
        self.assertEqual(player_effect_from_dict(raw),g.state.players[1].player_effects[0])
        s['schema_version']=268
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_public_effect_identity_and_costs_do_not_expose_private_source_fact(self):
        g=self.game((MOG,NEO),enemy_hand=('CORE_CS2_029',));self.play(g,MOG);self.play(g,NEO)
        for p in (1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for hidden in ('source_allocation','source_player_id','payment_state','resolution_frame'):
                self.assertNotIn(hidden,public)
        listing=g.for_player(1).legal_actions();self.assertIsNotNone(listing['actions']);self.portable(g)
