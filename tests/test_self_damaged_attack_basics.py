"""One real Amani adapter; independent continuous attack and its own lifecycle."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, AuraSpec, CardDefinition, CardType, EndTurn, Game,
    GrantStatRelation, Keyword, PlayCard, PlayerSetup, Registry, ResolutionError,
    Scenario, SelectChoice, SnapshotError, StatReference, StatRelationLayer,
    StatRelationOperand, StatRelationSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption,
    CopyMinion, Damage, DamageBatch, Destroy, GainArmor, GrantKeyword, Heal,
    InvokeBehavior, RequestChoice, ReturnToHand, SetStats, Silence, Summon, Transform)
from hs_sim.engine.model import AbilityInstance
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

AMANI = 'EX1_393'
PATH = Path(__file__).resolve().parents[1] / 'data/support/self-damaged-attack-basics.json'
PIN = '80ad786d0038478f6c388bc0b034f8f829b6a38a00fab9df7474445785b313a0'
REL = StatRelationSpec(operand=StatRelationOperand.SELF_DAMAGED,
    layer=StatRelationLayer.CONDITIONAL_ATTACK, amount=3)

def evidence():
    support = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support) != PIN: raise ValueError('Self-damaged complete evidence changed')
    for row in support['records']:
        if canonical_digest(row['data']) != row['data_sha256']: raise ValueError('Self-damaged raw changed')
    return support['records'][0]['data']

def registry():
    r = Registry('isolated-self-damaged-attack-basics-v1'); raw = evidence()
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=80, metadata=metadata()))
    r.register_card(CardDefinition(AMANI, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], stat_relations=(REL,), metadata=metadata()))
    r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, attack=1, health=15, metadata=metadata()))
    r.register_card(CardDefinition('aura', 'Health support', CardType.MINION, health=5,
        auras=(AuraSpec(0, health=2),), metadata=metadata()))
    def quote(c): return (GainArmor(c.player_id, c.state.entities[c.target_id].attack),)
    def waiting(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('hurt', 'Injure once', (Damage(c.target_id, 1, c.source_id),)),
            ChoiceOption('fault', 'Fault after injury', (Damage(c.target_id, 1, c.source_id),
                InvokeBehavior('late-fault', source_id=c.source_id, player_id=c.player_id))),
        ), c.source_id),)
    def declared(c):
        if c.event.player_id != c.player_id: return ()
        return (RequestChoice(c.player_id, (ChoiceOption('hurt', 'Injure attacker',
            (Damage(c.event.source_id, 1, c.source_id),)),), c.source_id),)
    r.register_behavior('quote', quote); r.register_behavior('declared', declared)
    r.register_behavior('late-fault', lambda c: (AddToHand(c.player_id, 'missing.self-damaged'),))
    r.register_card(CardDefinition('watcher', 'Attack observer', CardType.MINION, health=5,
        triggers=(TriggerSpec('attack_declared', 'declared'),), metadata=metadata()))
    scripts = {
        'hurt0': lambda c: (Damage(c.target_id, 0, c.source_id),),
        'hurt': lambda c: (Damage(c.target_id, 1, c.source_id),),
        'hurt2': lambda c: (Damage(c.target_id, 2, c.source_id),),
        'heal': lambda c: (Heal(c.target_id, 1, c.source_id),),
        'full': lambda c: (Heal(c.target_id, 30, c.source_id),),
        'shield': lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),),
        'atk': lambda c: (Buff(c.target_id, attack=5, source_id=c.source_id),),
        'setatk': lambda c: (SetStats(c.target_id, attack=1, source_id=c.source_id),),
        'negatk': lambda c: (Buff(c.target_id, attack=-5, source_id=c.source_id),),
        'zeroatk': lambda c: (SetStats(c.target_id, attack=0, source_id=c.source_id),),
        'hp': lambda c: (Buff(c.target_id, health=2, source_id=c.source_id),),
        'sethp': lambda c: (SetStats(c.target_id, health=4, source_id=c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'copy': lambda c: (CopyMinion(c.target_id, 2),),
        'copybase': lambda c: (CopyMinion(c.target_id, 2, mode='base'),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'away': lambda c: (Transform(c.target_id, 'plain'),),
        'into': lambda c: (Transform(c.target_id, AMANI),),
        'control': lambda c: (ChangeControl(c.target_id, 2),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'summon': lambda c: (Summon(c.player_id, AMANI),),
        'wait': waiting,
        'fault': lambda c: (Damage(c.target_id, 1, c.source_id), AddToHand(c.player_id, 'missing.self-damaged')),
        'batch': lambda c: (DamageBatch((Damage(c.target_id, 1, c.source_id, on_result='quote'),
            Damage(c.target_id, 1, c.source_id, on_result='quote'))),),
    }
    for name, body in scripts.items():
        r.register_behavior(name, body)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name,
            requires_target=True, metadata=metadata()))
    return r

class SelfDamagedAttackBasicsTests(unittest.TestCase):
    def game(self, hand=(), board=(AMANI,), enemy=('plain',), enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, mana=10, max_mana=10),
            PlayerSetup('hero', hand=enemy_hand, board=enemy, mana=10, max_mana=10),
        ), seed=32), registry())

    def actor(self, g): return g.state.players[1].board[0]
    def cast(self, g, name, target=None):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, eid, self.actor(g) if target is None else target))
    def choose(self, g, name):
        p = g.state.pending_choice
        return g.apply(SelectChoice(p.player_id, p.id, (name,)))
    def rows(self, g, eid):
        return tuple(a for a in g.state.entities[eid].abilities if a.kind == 'stat_relation')
    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(snap, registry())
        self.assertEqual(restored.snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), snap)
        return restored
    def reject(self, snap):
        snap['state_hash'] = canonical_hash({k:v for k,v in snap.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(snap, registry())

    def test_full_raw_pin_and_single_necessary_real_definition(self):
        raw = evidence(); self.assertEqual(raw['id'], AMANI)
        self.assertEqual((raw['cost'], raw['attack'], raw['health']), (2, 2, 3))
        self.assertEqual(raw['text_en'], 'Has +3 Attack while damaged.')
        self.assertEqual(registry().card(AMANI).stat_relations, (REL,))
        self.assertEqual([r['id'] for r in json.loads(PATH.read_text(encoding='utf-8'))['records']], [AMANI])

    def test_closed_exact_typed_positive_declaration(self):
        self.assertEqual(StatRelationSpec().amount, 0)
        for kwargs in ({'amount': True}, {'amount': 3.0}, {'amount': 0}, {'amount': -1},
                {'layer': StatRelationLayer.FINAL_ATTACK}, {'operand': 'self_damaged'},
                {'target': StatReference.HEALTH}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): replace(REL, **kwargs)
        with self.assertRaises(ValueError): StatRelationSpec(amount=3)
        with self.assertRaises(FrozenInstanceError): REL.amount = 4

    def test_existing_ordinary_carrier_and_duplicate_guards_are_reused(self):
        from hs_sim.engine.stat_relations import validate_definition
        ordinary = registry().card(AMANI)
        for card in (replace(ordinary, stat_relations=(REL, REL)),
                replace(ordinary, stat_relations=(dict(amount=3),)),
                replace(ordinary, kind=CardType.HERO),
                replace(ordinary, keywords=(Keyword.MAGNETIC,), magnetic_tribes=('MECH',))):
            with self.subTest(card=card), self.assertRaises(ValueError): validate_definition(card)

    def test_new_optional_grants_remain_explicitly_unsupported(self):
        with self.assertRaises(ValueError): GrantStatRelation(1, REL)
        with self.assertRaises(ValueError): AbilityInstance(1, 'stat_relation', stat_relation=REL)
        self.assertIsNotNone(GrantStatRelation(1, StatRelationSpec()))

    def test_damage_activates_without_mutating_numeric_attachments(self):
        g = self.game(('hurt',)); eid = self.actor(g)
        self.assertEqual(g.state.entities[eid].attack, 2)
        before = self.rows(g, eid); self.cast(g, 'hurt')
        e = g.state.entities[eid]
        self.assertEqual((e.attack, e.health, e.damage, e.attack_bonus), (5, 2, 1, 0))
        self.assertEqual(self.rows(g, eid), before); self.assertEqual(e.enchantments, [])
        self.portable(g)

    def test_repeated_damage_does_not_stack(self):
        g = self.game(('hurt', 'hurt')); self.cast(g, 'hurt'); self.cast(g, 'hurt')
        e = g.state.entities[self.actor(g)]
        self.assertEqual((e.attack, e.health, e.damage), (5, 1, 2))
        self.assertEqual(len(self.rows(g, e.id)), 1); self.portable(g)

    def test_partial_heal_keeps_condition(self):
        g = self.game(('hurt2', 'heal')); self.cast(g, 'hurt2'); self.cast(g, 'heal')
        e = g.state.entities[self.actor(g)]
        self.assertEqual((e.attack, e.health, e.damage), (5, 2, 1)); self.portable(g)

    def test_full_heal_removes_condition_and_next_injury_reactivates(self):
        g = self.game(('hurt', 'full', 'hurt'))
        self.cast(g, 'hurt'); self.cast(g, 'full')
        self.assertEqual(g.state.entities[self.actor(g)].attack, 2)
        self.cast(g, 'hurt'); self.assertEqual(g.state.entities[self.actor(g)].attack, 5)
        self.portable(g)

    def test_zero_damage_and_overheal_do_not_activate(self):
        g = self.game(('hurt0', 'full')); self.cast(g, 'hurt0'); self.cast(g, 'full')
        e = g.state.entities[self.actor(g)]
        self.assertEqual((e.attack, e.damage), (2, 0)); self.portable(g)

    def test_prevented_damage_does_not_activate(self):
        g = self.game(('shield', 'hurt', 'hurt')); self.cast(g, 'shield'); self.cast(g, 'hurt')
        self.assertEqual(g.state.entities[self.actor(g)].attack, 2)
        self.cast(g, 'hurt'); self.assertEqual(g.state.entities[self.actor(g)].attack, 5)
        self.portable(g)

    def test_manual_play_installs_printed_condition_once(self):
        g = self.game((AMANI, 'hurt'), board=())
        eid = g.state.players[1].hand[0]; g.apply(PlayCard(1, eid))
        self.assertEqual((g.state.entities[eid].attack, len(self.rows(g, eid))), (2, 1))
        self.cast(g, 'hurt', eid); self.assertEqual(g.state.entities[eid].attack, 5); self.portable(g)

    def test_summon_installs_printed_condition_once(self):
        g = self.game(('summon', 'hurt'), board=('plain',)); self.cast(g, 'summon')
        eid = g.state.players[1].board[-1]
        self.assertEqual((g.state.entities[eid].attack, len(self.rows(g, eid))), (2, 1))
        self.cast(g, 'hurt', eid); self.assertEqual(g.state.entities[eid].attack, 5); self.portable(g)

    def test_combat_injury_does_not_rewrite_prepared_attacker_packet(self):
        g = self.game(); eid = self.actor(g); enemy = g.state.players[2].board[0]
        g.apply(Attack(1, eid, enemy))
        self.assertEqual((g.state.entities[enemy].damage, g.state.entities[eid].damage,
            g.state.entities[eid].attack), (2, 1, 5)); self.portable(g)

    def test_combat_injury_does_not_rewrite_prepared_retaliation(self):
        g = self.game(board=('plain',), enemy=(AMANI,))
        attacker = self.actor(g); target = g.state.players[2].board[0]
        g.apply(Attack(1, attacker, target))
        self.assertEqual((g.state.entities[attacker].damage, g.state.entities[target].damage,
            g.state.entities[target].attack), (2, 1, 5)); self.portable(g)

    def test_declared_wait_uses_new_delivery_attack_and_original_retaliation(self):
        g = self.game(board=(AMANI, 'watcher')); eid = self.actor(g); enemy = g.state.players[2].board[0]
        g.apply(Attack(1, eid, enemy)); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[eid].attack, 2)
        restored = self.portable(g); clone = g.clone()
        for branch in (g, restored, clone):
            self.choose(branch, 'hurt')
            self.assertEqual((branch.state.entities[enemy].damage, branch.state.entities[eid].damage,
                branch.state.entities[eid].attack), (5, 2, 5)); self.portable(branch)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(g.snapshot(), clone.snapshot())

    def test_batch_callbacks_see_settled_condition_without_extra_attachment(self):
        g = self.game(('batch',)); self.cast(g, 'batch')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 10)
        self.assertEqual((g.state.entities[self.actor(g)].attack, len(self.rows(g, self.actor(g)))), (5, 1))
        self.portable(g)

    def test_lethal_damage_freezes_conditional_attack_without_self_health_equation(self):
        g = self.game(('hurt', 'hurt2')); eid = self.actor(g)
        self.cast(g, 'hurt'); self.cast(g, 'hurt2', eid)
        row = g.state.death_history[-1]
        self.assertEqual((row.entity_id, row.attack, row.damage, row.max_health), (eid, 5, 3, 3))
        self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD); self.portable(g)

    def test_silence_removes_condition_without_healing(self):
        g = self.game(('hurt', 'silence')); eid = self.actor(g)
        self.cast(g, 'hurt'); self.cast(g, 'silence')
        self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].damage), (2, 1))
        self.assertEqual(self.rows(g, eid), ()); self.portable(g)

    def test_current_copy_keeps_damage_attachment_identity_and_original_provenance(self):
        g = self.game(('hurt', 'copy')); eid = self.actor(g)
        self.cast(g, 'hurt'); self.cast(g, 'copy'); copied = g.state.players[2].board[-1]
        self.assertEqual((g.state.entities[copied].attack, g.state.entities[copied].damage), (5, 1))
        self.assertNotEqual(self.rows(g, eid)[0].id, self.rows(g, copied)[0].id)
        self.assertEqual(self.rows(g, copied)[0].source_id, eid)
        self.assertEqual(self.rows(g, copied)[0].origin, 'printed'); self.portable(g)

    def test_base_copy_starts_healthy_with_native_condition(self):
        g = self.game(('hurt', 'copybase')); self.cast(g, 'hurt'); self.cast(g, 'copybase')
        eid = g.state.players[2].board[-1]
        self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].damage,
            len(self.rows(g, eid))), (2, 0, 1)); self.portable(g)

    def test_current_silenced_copy_remains_silenced(self):
        g = self.game(('hurt', 'silence', 'copy')); self.cast(g, 'hurt'); self.cast(g, 'silence'); self.cast(g, 'copy')
        eid = g.state.players[2].board[-1]
        self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].damage), (2, 1))
        self.assertEqual(self.rows(g, eid), ()); self.portable(g)

    def test_bounce_resets_damage_and_reinstalls_only_native_condition(self):
        g = self.game(('hurt', 'bounce')); eid = self.actor(g); self.cast(g, 'hurt'); self.cast(g, 'bounce')
        self.assertEqual((g.state.entities[eid].zone, g.state.entities[eid].attack,
            g.state.entities[eid].damage, len(self.rows(g, eid))), (Zone.HAND, 2, 0, 1))
        g.apply(PlayCard(1, eid)); self.assertEqual(g.state.entities[eid].attack, 2); self.portable(g)

    def test_transform_away_removes_old_condition(self):
        g = self.game(('hurt', 'away')); eid = self.actor(g); self.cast(g, 'hurt'); self.cast(g, 'away')
        self.assertEqual((g.state.entities[eid].card_id, g.state.entities[eid].attack), ('plain', 1))
        self.assertEqual(self.rows(g, eid), ()); self.portable(g)

    def test_transform_into_installs_healthy_native_condition(self):
        g = self.game(('into', 'hurt'), board=('plain',)); eid = self.actor(g)
        self.cast(g, 'into'); self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].damage), (2, 0))
        self.cast(g, 'hurt'); self.assertEqual(g.state.entities[eid].attack, 5); self.portable(g)

    def test_control_change_preserves_self_condition(self):
        g = self.game(('hurt', 'control')); eid = self.actor(g); before = self.rows(g, eid)
        self.cast(g, 'hurt'); self.cast(g, 'control')
        self.assertEqual((g.state.entities[eid].controller, g.state.entities[eid].attack,
            g.state.entities[eid].damage), (2, 5, 1))
        self.assertEqual(self.rows(g, eid), before); self.portable(g)

    def test_set_max_health_clears_damage_and_switches_without_heal_event(self):
        g = self.game(('hurt', 'sethp')); self.cast(g, 'hurt'); result = self.cast(g, 'sethp')
        e = g.state.entities[self.actor(g)]
        self.assertEqual((e.attack, e.health, e.max_health, e.damage), (2, 4, 4, 0))
        self.assertFalse(any(event.kind == 'healed' for event in result.events)); self.portable(g)

    def test_health_buff_preserves_damage_and_condition(self):
        g = self.game(('hurt', 'hp')); self.cast(g, 'hurt'); self.cast(g, 'hp')
        e = g.state.entities[self.actor(g)]
        self.assertEqual((e.attack, e.health, e.max_health, e.damage), (5, 4, 5, 1)); self.portable(g)

    def test_health_aura_removal_uses_existing_clamp_and_switches_to_healthy(self):
        g = self.game(('hurt', 'kill'), board=(AMANI, 'aura'))
        eid, aura = g.state.players[1].board; self.cast(g, 'hurt'); self.cast(g, 'kill', aura)
        e = g.state.entities[eid]
        self.assertEqual((e.attack, e.health, e.max_health, e.damage), (2, 3, 3, 0)); self.portable(g)

    def test_numeric_attack_layers_precede_condition_and_zero_floor(self):
        g = self.game(('hurt', 'atk', 'setatk', 'negatk', 'zeroatk', 'full'))
        self.cast(g, 'hurt'); self.cast(g, 'atk'); self.assertEqual(g.state.entities[self.actor(g)].attack, 10)
        self.cast(g, 'setatk'); self.assertEqual(g.state.entities[self.actor(g)].attack, 4)
        self.cast(g, 'negatk'); self.assertEqual(g.state.entities[self.actor(g)].attack, 0)
        self.cast(g, 'zeroatk'); self.assertEqual(g.state.entities[self.actor(g)].attack, 3)
        self.cast(g, 'full'); self.assertEqual(g.state.entities[self.actor(g)].attack, 0); self.portable(g)

    def test_public_current_attack_and_queries_are_pure_without_private_formula(self):
        g = self.game(('hurt',), enemy_hand=(AMANI,)); self.cast(g, 'hurt'); before = g.snapshot()
        for _ in range(3):
            self.assertEqual(g.state.entities[self.actor(g)].attack, 5)
            self.assertEqual(g.observe(1)['players'][0]['board'][0]['attack'], 5)
            public = json.dumps(g.observe(1)) + json.dumps(g.observe(2))
            public += json.dumps(g.for_player(1).legal_actions())
            for word in ('stat_relation', 'stat_relations', 'self_damaged', 'conditional_attack', 'resolution_frame', 'next_attachment_id'):
                self.assertNotIn('"'+word+'"', public)
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_waiting_choice_restore_and_replay_keep_same_condition(self):
        g = self.game(('wait',)); self.cast(g, 'wait'); self.assertIsNotNone(g.state.pending_choice)
        restored = self.portable(g); clone = g.clone()
        for branch in (g, restored, clone):
            self.choose(branch, 'hurt'); self.assertEqual(branch.state.entities[self.actor(branch)].attack, 5)
            self.portable(branch)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(g.snapshot(), clone.snapshot())

    def test_failed_immediate_effect_rolls_back_damage_and_condition(self):
        g = self.game(('fault',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.cast(g, 'fault')
        self.assertEqual(g.snapshot(), before); self.assertEqual(g.state.entities[self.actor(g)].attack, 2)
        self.portable(g)

    def test_failed_waiting_choice_rolls_back_to_original_waiting_boundary(self):
        g = self.game(('wait',)); self.cast(g, 'wait'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before); self.assertEqual(g.state.entities[self.actor(g)].attack, 2)
        self.choose(g, 'hurt'); self.assertEqual(g.state.entities[self.actor(g)].attack, 5); self.portable(g)

    def test_rehashed_wire_requires_exact_complete_typed_native_spec(self):
        g = self.game(('hurt',)); self.cast(g, 'hurt'); snap = g.snapshot(); eid = self.actor(g)
        for field, value in (('amount', True), ('amount', 3.0), ('amount', 4), ('amount', 0),
                ('layer', 'final_attack'), ('target', 'health'), ('operand', 'unregistered_condition')):
            bad = deepcopy(snap); ability = next(a for a in bad['state']['entities'][str(eid)]['abilities'] if a['kind']=='stat_relation')
            ability['stat_relation'][field] = value
            with self.subTest(field=field, value=value): self.reject(bad)
        bad = deepcopy(snap); ability = next(a for a in bad['state']['entities'][str(eid)]['abilities'] if a['kind']=='stat_relation')
        del ability['stat_relation']['amount']; self.reject(bad)
        bad = deepcopy(snap); ability = next(a for a in bad['state']['entities'][str(eid)]['abilities'] if a['kind']=='stat_relation')
        ability['origin'] = 'granted'; self.reject(bad); self.portable(g)

    def test_schema_and_strict_previous_versions(self):
        g = self.game(); snap = g.snapshot()
        self.assertEqual(snap['schema_version'], 266)
        self.assertEqual(snap['mechanics_version']['version'], CORE_EFFECTS_VERSION)
        for version in (1, 178, 179, True, 180.0, 217):
            bad = deepcopy(snap); bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())
        self.portable(g)

if __name__ == '__main__': unittest.main()
