"""Actual production Mayor source, lifecycle and finite native target domains."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
from pathlib import Path
from random import Random
from types import SimpleNamespace
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (Attack, CardDefinition, CardType, Game, Keyword, PlayCard, PlayerSetup,
    Scenario, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import ChoiceOption, CopyMinion, RequestChoice, Silence
from hs_sim.engine.native_random_targets import (NativeTargetSelection, attack_partition,
    current_sources, manual_partition, sample)
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face
from hs_sim.cards.noggenfogger_card import load_batch

CARD='CORE_CFM_670'
P='fixture.noggen.domain.';FIRE=P+'fire';SAP=P+'sap';UNIT=P+'unit';STEALTH=P+'stealth';ELUSIVE=P+'elusive';IMMUNE=P+'immune';TAUNT=P+'taunt';WATCH=P+'watch'


@lru_cache(maxsize=None)
def fixture():
    r=build_registry()
    # Consumer fixtures use the production definition/declaration; only their
    # witnesses and target bodies below are private test helpers.
    assert CARD in r.cards and CARD in r.random_target_cards
    for cid,keywords in((UNIT,()),(STEALTH,(Keyword.STEALTH,)),(ELUSIVE,(Keyword.ELUSIVE,)),(IMMUNE,(Keyword.IMMUNE,)),(TAUNT,(Keyword.TAUNT,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=2,health=10,keywords=keywords))
    r.register_behavior(P+'noop',lambda c:())
    for cid,target in((FIRE,TargetSpec()),(SAP,TargetSpec(kinds=(CardType.MINION,),relation='enemy'))):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=P+'noop',targeting=target))
    r.register_behavior(P+'silence',lambda c:(Silence(c.target_id),))
    r.register_card(CardDefinition(P+'silence','Silence',CardType.SPELL,on_play=P+'silence',
        targeting=TargetSpec(kinds=(CardType.MINION,))))
    r.register_behavior(P+'copy',lambda c:(CopyMinion(c.target_id,c.player_id,cause=SummonCause.capture(c)),))
    r.register_card(CardDefinition(P+'copy','Copy',CardType.SPELL,on_play=P+'copy',
        targeting=TargetSpec(kinds=(CardType.MINION,),relation='friendly')))
    # Lifecycle tests use explicit trusted no-arrow fixture operations. Actual
    # targeted spells now correctly invoke the native random replacement.
    def original_source(c):return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD)
    r.register_behavior(P+'copy_source',lambda c:(CopyMinion(original_source(c),c.player_id,cause=SummonCause.capture(c)),))
    r.register_card(CardDefinition(P+'copy_source','Copy native source fixture',CardType.SPELL,on_play=P+'copy_source'))
    r.register_behavior(P+'silence_source',lambda c:(Silence(original_source(c)),))
    r.register_card(CardDefinition(P+'silence_source','Silence native source fixture',CardType.SPELL,on_play=P+'silence_source'))
    r.register_behavior(P+'wait',lambda c:(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,triggers=(TriggerSpec('attack_declared',P+'wait'),)))
    r.validate();return r


class NativeRandomTargetDomainTests(unittest.TestCase):
    def game(self,board=(CARD,UNIT),enemy=(UNIT,STEALTH,ELUSIVE,IMMUNE),hand=(FIRE,SAP,P+'silence',P+'copy')):
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_03',hand=hand,board=board,mana=10,max_mana=10),
            PlayerSetup('HERO_03',board=enemy,mana=10,max_mana=10)),seed=311),fixture())
        return g,SimpleNamespace(state=g._state,registry=g.registry,game=g)
    def entity(self,g,cid,player=1,zone='hand'):
        return next(g._state.entities[i]for i in getattr(g._state.players[player],zone)if g._state.entities[i].card_id==cid)
    def test_complete_actual_card_sources_and_production_declaration_match_full_printed_face(self):
        data=load_batch();row=data['cards'][0]
        self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        for observation in data['official_observations']:check_face(row['record'],observation['face'],observation['locale'])
        registry=build_registry();raw=row['record'];card=registry.card(CARD)
        self.assertEqual(card,CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],
            attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw)))
        self.assertEqual(registry.random_target_cards,frozenset((CARD,)))
        self.assertEqual(canonical_digest(asdict(card.metadata)),canonical_digest(row['metadata']))
        from hs_sim.engine.pools import PoolCard
        self.assertEqual(registry.pool_cards[CARD],PoolCard.from_definition(card))
    def test_manual_spell_domain_keeps_all_declared_selectable_restrictions(self):
        g,r=self.game();source=self.entity(g,FIRE);target=self.entity(g,UNIT,2,'board')
        p=manual_partition(r,source,r.registry.card(FIRE),target.id)
        blocked={self.entity(g,cid,2,'board').id for cid in(STEALTH,ELUSIVE,IMMUNE)}
        self.assertTrue(p.applied);self.assertFalse(blocked & set(p.target_ids))
        self.assertIn(g._state.players[1].hero_id,p.target_ids)
        self.assertIn(g._state.players[2].hero_id,p.target_ids)
        self.assertIn(target.id,p.target_ids)
    def test_actual_paid_mayor_and_frostbolt_use_unmodified_production_registry_restore_and_replay(self):
        from hs_sim.engine.continuations import FrameCodec
        from hs_sim.engine.native_target_acceptance import ACCEPTED
        from hs_sim.engine.replay import build_replay,replay
        registry=build_registry()
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(CARD,'CS2_024'),board=('CS2_182',),
            mana=30,max_mana=30,mana_cap=30),PlayerSetup('HERO_03',board=('CS2_182',))),seed=311),registry)
        source=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==CARD)
        rng=g.snapshot()['rng_state'];g.apply(PlayCard(1,source))
        self.assertEqual(g.state.players[1].mana,21);self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertEqual(tuple(x.source.entity_id for x in current_sources(g.state,registry)),(source,))
        self.assertFalse(g.state.battlecry_history)
        spell=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id=='CS2_024')
        original=g.state.players[2].hero_id;health={i:e.health for i,e in g.state.entities.items()}
        g.apply(PlayCard(1,spell,original))
        event=next(e for e in g.events if e.kind==ACCEPTED)
        selection=FrameCodec(g.mechanics,registry).decode(json.loads(dict(event.data)['selection']))
        self.assertTrue(selection.partition.applied);self.assertNotEqual(selection.rng_before,selection.rng_after)
        self.assertEqual(g.state.play_history[-1].target_id,original)
        self.assertEqual(g.state.cast_history[-1].target_id,selection.target_id)
        self.assertEqual(g.state.entities[selection.target_id].health,health[selection.target_id]-3)
        self.assertEqual(g.state.players[1].mana,19)
        saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,build_registry()).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),build_registry()).snapshot(),saved)
    def test_enemy_minion_contract_does_not_expand_to_friendly_or_heroes(self):
        g,r=self.game();source=self.entity(g,SAP);target=self.entity(g,UNIT,2,'board')
        p=manual_partition(r,source,r.registry.card(SAP),target.id)
        self.assertEqual(p.target_ids,(target.id,))
        self.assertEqual(sample(Random(9),p).target_id,target.id)
    def test_partition_is_pure_and_sampling_uses_only_explicit_rng_operand(self):
        g,r=self.game();source=self.entity(g,FIRE);target=self.entity(g,UNIT,2,'board');before=g.snapshot()
        p=manual_partition(r,source,r.registry.card(FIRE),target.id);rng=Random(311)
        a=sample(rng,p);b=sample(Random(311),p)
        self.assertEqual(a,b);self.assertEqual(g.snapshot(),before)
        self.assertNotEqual(a.rng_before,a.rng_after)
    def test_no_source_preserves_submitted_target_without_random_draw(self):
        g,r=self.game(board=(UNIT,));source=self.entity(g,FIRE);target=self.entity(g,UNIT,2,'board')
        p=manual_partition(r,source,r.registry.card(FIRE),target.id)
        self.assertFalse(p.applied);self.assertEqual(p.candidates,())
        s=sample(Random(311),p);self.assertEqual(s.target_id,target.id);self.assertEqual(s.rng_before,s.rng_after)
    def test_optional_untargeted_activation_is_not_given_an_invented_target(self):
        g,r=self.game();source=self.entity(g,FIRE)
        p=manual_partition(r,source,r.registry.card(FIRE),None)
        s=sample(Random(311),p);self.assertIsNone(s.target_id);self.assertFalse(p.applied)
        self.assertEqual(s.rng_before,s.rng_after)
    def test_current_owner_is_explicit_separate_from_source_physical_controller(self):
        g,r=self.game();source=self.entity(g,SAP);target=self.entity(g,UNIT,1,'board')
        p=manual_partition(r,source,r.registry.card(SAP),target.id,player_id=2,origin='battlecry')
        self.assertIn(target.id,p.target_ids)
        self.assertTrue(all(x.controller==1 for x in p.candidates))
        self.assertEqual(p.source.controller,1);self.assertEqual(p.player_id,2)
    def test_both_controllers_are_global_sources_with_unique_attachment_identity(self):
        g,r=self.game(enemy=(CARD,UNIT));rows=current_sources(r.state,r.registry)
        self.assertEqual(len(rows),2);self.assertEqual({x.source.controller for x in rows},{1,2})
        ids=[i for row in rows for i in row.ability_ids];self.assertEqual(len(ids),len(set(ids)))
    def test_silence_removes_policy_and_current_copy_preserves_native_source(self):
        g,r=self.game(enemy=(UNIT,),hand=(P+'copy_source',P+'silence_source'));source=self.entity(g,P+'copy_source');original=self.entity(g,CARD,1,'board')
        g.apply(PlayCard(1,source.id));r.state=g._state
        self.assertEqual(len(current_sources(r.state,r.registry)),2)
        source=self.entity(g,P+'silence_source');g.apply(PlayCard(1,source.id));r.state=g._state
        rows=current_sources(r.state,r.registry);self.assertEqual(len(rows),1)
        self.assertNotEqual(rows[0].source.entity_id,original.id)
        s=json.loads(json.dumps(g.snapshot()));restored=Game.from_snapshot(s,fixture.__wrapped__())
        self.assertEqual(restored.snapshot(),s)
    def test_proposed_attack_domain_ignores_taunt_stealth_and_voluntary_constraints(self):
        g,r=self.game(board=(CARD,UNIT,WATCH),enemy=(TAUNT,STEALTH,UNIT),hand=())
        attacker=self.entity(g,UNIT,1,'board');defender=self.entity(g,TAUNT,2,'board')
        g.apply(Attack(1,attacker.id,defender.id));self.assertIsNotNone(g.state.pending_choice)
        r.state=g._state;window=g._state.action_windows[-1];p=attack_partition(r,window)
        self.assertTrue(p.applied)
        self.assertIn(self.entity(g,STEALTH,2,'board').id,p.target_ids)
        self.assertIn(g._state.players[2].hero_id,p.target_ids)
        self.assertFalse(any(x.controller==1 for x in p.candidates))
        self.assertEqual({x.entity_id for x in p.candidates},set(g._state.players[2].board+[g._state.players[2].hero_id]))
    def test_stale_proposed_attack_and_forged_rng_receipts_are_rejected(self):
        g,r=self.game();source=self.entity(g,FIRE);target=self.entity(g,UNIT,2,'board')
        p=manual_partition(r,source,r.registry.card(FIRE),target.id);s=sample(Random(311),p)
        with self.assertRaises(ValueError):replace(s,rng_after=s.rng_before)
        with self.assertRaises(ValueError):replace(p,candidates=tuple(reversed(p.candidates)))
        with self.assertRaises(ValueError):attack_partition(r,None)


if __name__=='__main__':unittest.main()
