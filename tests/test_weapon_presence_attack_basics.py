"""One real Buccaneer and the existing numeric layer with current equipment."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, Rarity, Registry, ResolutionError, Scenario,
    SelectChoice, SnapshotError, StatReference, StatRelationLayer, StatRelationOperand,
    StatRelationSpec, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, CopyMinion,
    Destroy, EquipWeapon, GainArmor, InvokeBehavior, ModifyWeapon, RequestChoice,
    ReturnToHand, SetStats, Silence, Summon, SwapStats, Transform)
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.stat_relations import GrantStatRelation, conditional_attack
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

BUCCANEER = 'CFM_325'
PATH = Path(__file__).resolve().parents[1] / 'data/support/weapon-presence-attack-basics.json'
PIN = '4b31bff8448b2b17fd07773f1e3709edd6d1a1494971bf9ac22c0c1fd506ea7d'
REL = StatRelationSpec(operand=StatRelationOperand.CONTROLLER_HAS_WEAPON,
    layer=StatRelationLayer.CONDITIONAL_ATTACK, amount=2)

def evidence():
    support = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support) != PIN: raise ValueError('Complete weapon-presence Attack evidence changed')
    for row in support['records']:
        if canonical_digest(row['data']) != row['data_sha256']: raise ValueError('Raw card evidence changed')
    return support['records'][0]['data']

def registry():
    r = Registry('isolated-weapon-presence-attack-basics-v1'); raw = evidence()
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=80, metadata=metadata()))
    r.register_card(CardDefinition(BUCCANEER, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], stat_relations=(REL,),
        metadata=metadata(tribes=('pirate',), rarity=Rarity.RARE)))
    r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, attack=1, health=15, metadata=metadata()))
    for cid, attack, durability in (('axe', 3, 2), ('last', 4, 1), ('zero', 0, 2)):
        r.register_card(CardDefinition(cid, cid, CardType.WEAPON, attack=attack,
            durability=durability, metadata=metadata()))

    def quote(c):
        return (GainArmor(c.player_id, c.state.entities[c.state.players[c.player_id].board[0]].attack),)

    def waiting(c):
        wid = c.state.players[c.player_id].weapon_id
        return (RequestChoice(c.player_id, (
            ChoiceOption('lose', 'Lose weapon', (Destroy(wid, c.source_id),)),
            ChoiceOption('replace', 'Replace with zero Attack weapon', (EquipWeapon(c.player_id, 'zero'),)),
            ChoiceOption('fault', 'Lose then fail', (Destroy(wid, c.source_id),
                InvokeBehavior('late-fault', source_id=c.source_id, player_id=c.player_id))),
        ), c.source_id),)

    def declared(c):
        p = c.state.players[c.player_id]
        if c.event.player_id != c.player_id or c.event.source_id != p.board[0] or p.weapon_id is None:
            return ()
        return waiting(c)

    r.register_behavior('quote', quote); r.register_behavior('declared', declared)
    r.register_behavior('late-fault', lambda c: (AddToHand(c.player_id, 'missing.weapon-attack'),))
    r.register_card(CardDefinition('observer', 'Observe equipment state', CardType.MINION, health=5,
        triggers=tuple(TriggerSpec(event, 'quote') for event in ('weapon_equipped', 'weapon_changed', 'weapon_destroyed')),
        metadata=metadata()))
    r.register_card(CardDefinition('watcher', 'Existing attack window', CardType.MINION, health=5,
        triggers=(TriggerSpec('attack_declared', 'declared'),), metadata=metadata()))
    scripts = {
        'equip': lambda c: (EquipWeapon(c.player_id, 'axe'),),
        'equip-zero': lambda c: (EquipWeapon(c.player_id, 'zero'),),
        'equip-last': lambda c: (EquipWeapon(c.player_id, 'last'),),
        'lose': lambda c: (Destroy(c.state.players[c.player_id].weapon_id, c.source_id),),
        'zero-attack': lambda c: (ModifyWeapon(c.state.players[c.player_id].weapon_id, attack=-3, source_id=c.source_id),),
        'break': lambda c: (ModifyWeapon(c.state.players[c.player_id].weapon_id, durability=-2, source_id=c.source_id),),
        'summon': lambda c: (Summon(c.player_id, BUCCANEER),),
        'sleep': lambda c: (MakeDormant(c.state.players[c.player_id].board[0], None, c.source_id),),
        'awake': lambda c: (AwakenMinion(c.state.players[c.player_id].board[0], c.source_id),),
        'wait': waiting,
        'fault': lambda c: (Destroy(c.state.players[c.player_id].weapon_id, c.source_id),
            AddToHand(c.player_id, 'missing.weapon-attack')),
    }
    targeted = {
        'buff': lambda c: (Buff(c.target_id, attack=5, source_id=c.source_id),),
        'set': lambda c: (SetStats(c.target_id, attack=1, source_id=c.source_id),),
        'zero-self': lambda c: (SetStats(c.target_id, attack=0, source_id=c.source_id),),
        'negative': lambda c: (Buff(c.target_id, attack=-2, source_id=c.source_id),),
        'swap': lambda c: (SwapStats(c.target_id, c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'copy': lambda c: (CopyMinion(c.target_id, 2),),
        'copybase': lambda c: (CopyMinion(c.target_id, 2, mode='base'),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'away': lambda c: (Transform(c.target_id, 'plain'),),
        'into': lambda c: (Transform(c.target_id, BUCCANEER),),
        'control': lambda c: (ChangeControl(c.target_id, 2),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
    }
    for name, body in {**scripts, **targeted}.items():
        r.register_behavior(name, body)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name,
            requires_target=name in targeted, metadata=metadata()))
    return r

class WeaponPresenceAttackBasicsTests(unittest.TestCase):
    def game(self, hand=(), board=(BUCCANEER,), enemy=('plain',), enemy_hand=(), weapon='axe', enemy_weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, weapon_card_id=weapon, mana=10, max_mana=10),
            PlayerSetup('hero', hand=enemy_hand, board=enemy, weapon_card_id=enemy_weapon, mana=10, max_mana=10),
        ), seed=32), registry())
    def actor(self, g): return g.state.players[1].board[0]
    def hero(self, g, player=1): return g.state.entities[g.state.players[player].hero_id]
    def cast(self, g, name, target=None):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        card = g.registry.card(name)
        return g.apply(PlayCard(1, eid, (self.actor(g) if target is None else target) if card.requires_target else None))
    def play(self, g):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == BUCCANEER)
        g.apply(PlayCard(1, eid)); return eid
    def choose(self, g, name):
        p = g.state.pending_choice; return g.apply(SelectChoice(p.player_id, p.id, (name,)))
    def rows(self, g, eid): return tuple(a for a in g.state.entities[eid].abilities if a.kind == 'stat_relation')
    def value(self, g, attack=3, amount=2, eid=None):
        e = g.state.entities[self.actor(g) if eid is None else eid]
        self.assertEqual((e.attack, e.conditional_attack), (attack, amount))
    def attack(self, g): return g.apply(Attack(1, self.actor(g), self.hero(g, 2).id))
    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot())); restored = Game.from_snapshot(snap, registry())
        self.assertEqual(restored.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), snap); return restored
    def reject(self, snap):
        snap['state_hash'] = canonical_hash({k: v for k, v in snap.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(snap, registry())

    def test_complete_raw_pin_and_only_necessary_native_representative(self):
        raw = evidence(); card = registry().card(BUCCANEER)
        self.assertEqual((raw['id'], raw['cost'], raw['attack'], raw['health']), (BUCCANEER, 1, 1, 2))
        self.assertEqual(raw['text_en'], 'Has +2 Attack while you have a weapon equipped.')
        self.assertEqual((card.stat_relations, card.auras, card.metadata.tribes, card.metadata.rarity),
            ((REL,), (), ('pirate',), Rarity.RARE))

    def test_closed_strict_declaration_and_existing_relation_defaults(self):
        self.assertEqual(StatRelationSpec().amount, 0)
        StatRelationSpec(operand=StatRelationOperand.SELF_DAMAGED,
            layer=StatRelationLayer.CONDITIONAL_ATTACK, amount=3).__post_init__()
        for changes in ({'amount': True}, {'amount': 2.0}, {'amount': 0}, {'amount': -2},
                {'operand': 'controller_has_weapon'}, {'layer': StatRelationLayer.FINAL_ATTACK},
                {'target': StatReference.HEALTH}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(REL, **changes)
        with self.assertRaises(FrozenInstanceError): REL.amount = 4

    def test_ordinary_carrier_and_duplicate_definition_guards(self):
        for changes in ({'kind': CardType.WEAPON}, {'keywords': frozenset({Keyword.MAGNETIC})},
                {'keywords': frozenset({Keyword.STARSHIP_PIECE})}, {'stat_relations': (REL, REL)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                Registry('invalid-weapon-attack-fixture').register_card(replace(registry().card(BUCCANEER), **changes))

    def test_new_grants_and_non_native_lifecycle_are_rejected(self):
        with self.assertRaises(ValueError): GrantStatRelation(1, REL, 1)
        g = self.game(); row = self.rows(g, self.actor(g))[0]
        for changes in ({'origin': 'granted'}, {'source_id': None}, {'consumed': True},
                {'expires_turn': 1}, {'remove_on_silence': False}, {'magnetic_id': 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(row, **changes)

    def test_no_weapon_uses_unmodified_own_attack(self):
        g = self.game(weapon=None); self.value(g, 1, 0); self.portable(g)

    def test_weapon_adds_only_derived_self_contribution(self):
        g = self.game(); e = g.state.entities[self.actor(g)]; self.value(g)
        self.assertEqual((e.base_attack, e.attack_bonus, e.aura_attack, e.damage, e.enchantments), (1, 0, 0, 0, []))
        self.assertEqual(len(self.rows(g, e.id)), 1); self.assertEqual(self.hero(g).attack, 3); self.portable(g)

    def test_zero_attack_weapon_still_satisfies_presence(self):
        g = self.game(weapon='zero'); self.value(g); self.assertEqual(self.hero(g).attack, 0); self.portable(g)

    def test_modifying_weapon_attack_does_not_switch_presence(self):
        g = self.game(('zero-attack',)); self.cast(g, 'zero-attack'); self.value(g)
        self.assertEqual(self.hero(g).attack, 0); self.portable(g)

    def test_late_equip_switches_current_numeric_condition(self):
        g = self.game(('equip',), weapon=None); self.value(g, 1, 0)
        self.cast(g, 'equip'); self.value(g); self.portable(g)

    def test_destroy_weapon_revokes_without_permanent_stack(self):
        g = self.game(('lose', 'equip', 'lose', 'equip'))
        for i in range(2):
            self.cast(g, 'lose'); self.value(g, 1, 0)
            self.cast(g, 'equip'); self.value(g)
        self.assertEqual(len(self.rows(g, self.actor(g))), 1); self.portable(g)

    def test_zero_durability_revokes_immediately(self):
        g = self.game(('break',)); self.cast(g, 'break'); self.value(g, 1, 0)
        self.assertIsNone(g.state.players[1].weapon_id); self.portable(g)

    def test_actual_last_weapon_wear_revokes_source_contribution(self):
        g = self.game(weapon='last'); g.apply(Attack(1, self.hero(g).id, self.hero(g, 2).id))
        self.value(g, 1, 0); self.assertEqual(self.hero(g, 2).damage, 4)
        self.assertEqual(g.state.entities[self.actor(g)].attacks_this_turn, 0); self.portable(g)

    def test_replacement_keeps_presence_and_freezes_old_weapon(self):
        g = self.game(('equip-zero',)); old = g.state.players[1].weapon_id
        self.cast(g, 'equip-zero'); self.value(g)
        self.assertEqual(next(d for d in g.state.death_history if d.entity_id == old).attack, 3)
        self.assertNotEqual(old, g.state.players[1].weapon_id); self.portable(g)

    def test_enemy_equipment_does_not_contribute(self):
        g = self.game(weapon=None, enemy_weapon='axe'); self.value(g, 1, 0); self.portable(g)

    def test_offturn_preserves_self_condition_and_original_hero_policy(self):
        g = self.game(); eid = self.actor(g); g.apply(EndTurn(1)); self.value(g, eid=eid)
        self.assertEqual(self.hero(g).attack, 0); self.portable(g)

    def test_independent_physical_carriers_do_not_share_numeric_state(self):
        g = self.game(('silence',), board=(BUCCANEER, BUCCANEER)); other = g.state.players[1].board[1]
        self.cast(g, 'silence'); self.value(g, 1, 0); self.value(g, eid=other); self.portable(g)

    def test_manual_play_and_summon_use_native_condition_without_charge(self):
        for name in (BUCCANEER, 'summon'):
            with self.subTest(name=name):
                g = self.game((name,), board=()); self.play(g) if name == BUCCANEER else self.cast(g, 'summon')
                self.value(g); self.assertNotIn(Keyword.CHARGE, g.state.entities[self.actor(g)].keywords)
                with self.assertRaises(IllegalAction): self.attack(g)
                self.portable(g)

    def test_changes_do_not_refund_consumed_attack(self):
        g = self.game(('lose', 'equip')); self.attack(g)
        self.cast(g, 'lose'); self.cast(g, 'equip'); self.value(g)
        self.assertEqual(g.state.entities[self.actor(g)].attacks_this_turn, 1)
        with self.assertRaises(IllegalAction): self.attack(g)
        self.portable(g)

    def test_real_combat_and_later_loss_keep_completed_damage(self):
        g = self.game(('lose',)); target = g.state.players[2].board[0]
        g.apply(Attack(1, self.actor(g), target)); self.assertEqual(g.state.entities[target].damage, 3)
        self.cast(g, 'lose'); self.value(g, 1, 0)
        self.assertEqual(g.state.entities[target].damage, 3); self.portable(g)

    def test_numeric_set_and_buff_use_existing_conditional_layer(self):
        g = self.game(('buff', 'set', 'lose')); self.cast(g, 'buff'); self.value(g, 8)
        self.cast(g, 'set'); self.value(g); self.cast(g, 'lose'); self.value(g, 1, 0); self.portable(g)

    def test_negative_ordinary_attack_applies_zero_floor_after_condition(self):
        g = self.game(('negative', 'lose')); self.cast(g, 'negative'); self.value(g, 1)
        self.cast(g, 'lose'); self.value(g, 0, 0); self.portable(g)

    def test_zero_base_attack_plus_weapon_condition_remains_attackable(self):
        g = self.game(('zero-self', 'lose')); self.cast(g, 'zero-self'); self.value(g, 2); self.attack(g)
        self.cast(g, 'lose'); self.value(g, 0, 0); self.assertEqual(self.hero(g, 2).damage, 2); self.portable(g)

    def test_swap_preserves_continuous_bonus_after_original_numeric_swap(self):
        g = self.game(('swap', 'lose')); self.cast(g, 'swap'); self.value(g, 4)
        self.assertEqual(g.state.entities[self.actor(g)].max_health, 3)
        self.cast(g, 'lose'); self.value(g, 2, 0); self.portable(g)

    def test_silence_clears_native_contribution_and_cache(self):
        g = self.game(('silence',)); self.cast(g, 'silence'); self.value(g, 1, 0)
        self.assertEqual(self.rows(g, self.actor(g)), ()); self.portable(g)

    def test_current_copy_reads_destination_equipment_and_preserves_provenance(self):
        for weapon, expected in ((None, 1), ('zero', 3)):
            with self.subTest(weapon=weapon):
                g = self.game(('copy',), enemy_weapon=weapon); source = self.actor(g); self.cast(g, 'copy')
                dest = g.state.players[2].board[-1]; self.value(g, expected, expected-1, dest)
                self.assertEqual(self.rows(g, dest)[0].source_id, source)
                self.assertNotEqual(self.rows(g, dest)[0].id, self.rows(g, source)[0].id); self.portable(g)

    def test_base_copy_reinstalls_native_profile_using_destination_weapon(self):
        g = self.game(('silence', 'copybase'), enemy_weapon='zero'); self.cast(g, 'silence'); self.cast(g, 'copybase')
        dest = g.state.players[2].board[-1]; self.value(g, eid=dest); self.assertEqual(len(self.rows(g, dest)), 1); self.portable(g)

    def test_silenced_current_copy_stays_without_native_condition(self):
        g = self.game(('silence', 'copy'), enemy_weapon='zero'); self.cast(g, 'silence'); self.cast(g, 'copy')
        dest = g.state.players[2].board[-1]; self.value(g, 1, 0, dest); self.assertEqual(self.rows(g, dest), ()); self.portable(g)

    def test_bounce_resets_and_manual_replay_recomputes_current_equipment(self):
        g = self.game(('bounce', 'lose')); source = self.actor(g); self.cast(g, 'bounce')
        self.value(g, eid=source); self.cast(g, 'lose'); self.value(g, 1, 0, source)
        g.apply(PlayCard(1, source)); self.value(g, 1, 0); self.portable(g)

    def test_transform_away_and_into_recompute_native_condition(self):
        g = self.game(('away', 'into')); self.cast(g, 'away'); self.value(g, 1, 0)
        self.cast(g, 'into'); self.value(g); self.portable(g)

    def test_control_change_uses_current_controller_weapon(self):
        for weapon, expected in ((None, 1), ('zero', 3)):
            with self.subTest(weapon=weapon):
                g = self.game(('control',), enemy_weapon=weapon); source = self.actor(g); self.cast(g, 'control')
                self.value(g, expected, expected-1, source); self.assertEqual(g.state.entities[source].controller, 2); self.portable(g)

    def test_dormancy_and_weapon_loss_are_observed_on_awake(self):
        g = self.game(('sleep', 'lose', 'awake')); self.cast(g, 'sleep'); self.value(g, 1, 0)
        self.cast(g, 'lose'); self.cast(g, 'awake'); self.value(g, 1, 0); self.portable(g)

    def test_source_death_freezes_last_attack_and_native_relation(self):
        g = self.game(('kill',)); source = self.actor(g); self.cast(g, 'kill')
        row = next(d for d in g.state.death_history if d.entity_id == source)
        self.assertEqual((row.attack, row.abilities[0].stat_relation), (3, REL)); self.portable(g)

    def test_equipment_event_contexts_freeze_updated_own_attack(self):
        g = self.game(('equip', 'lose'), board=(BUCCANEER, 'observer'), weapon=None)
        self.cast(g, 'equip'); self.assertEqual(self.hero(g).armor, 3)
        self.cast(g, 'lose'); self.assertEqual(self.hero(g).armor, 4); self.portable(g)

    def test_declared_wait_reads_current_attack_before_preparing_damage(self):
        g = self.game(board=(BUCCANEER, 'watcher')); source = self.actor(g); self.attack(g)
        self.assertIsNotNone(g.state.pending_choice); restored = self.portable(g); clone = g.clone()
        for branch in (g, restored, clone):
            self.choose(branch, 'lose'); self.value(branch, 1, 0)
            self.assertEqual((self.hero(branch, 2).damage, branch.state.entities[source].attacks_this_turn), (1, 1))
            self.portable(branch)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(g.snapshot(), clone.snapshot())

    def test_pending_choice_restore_and_replay_keep_original_condition(self):
        g = self.game(('wait',)); self.cast(g, 'wait'); restored = self.portable(g)
        self.choose(g, 'replace'); self.choose(restored, 'replace'); self.value(g)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_immediate_and_waiting_failures_roll_back_numeric_cache(self):
        g = self.game(('fault',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.cast(g, 'fault')
        self.assertEqual(g.snapshot(), before); self.portable(g)
        g = self.game(('wait',)); self.cast(g, 'wait'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_queries_and_player_interface_are_pure_and_hide_formula(self):
        g = self.game(enemy_hand=(BUCCANEER,)); before = g.snapshot()
        for _ in range(3):
            self.assertEqual(conditional_attack(g.state, g.state.entities[self.actor(g)]), 2)
            self.value(g); public = json.dumps(g.observe(1)) + json.dumps(g.observe(2)) + json.dumps(g.for_player(1).legal_actions())
            for key in ('conditional_attack', 'controller_has_weapon', 'stat_relation', 'resolution_frame'):
                self.assertNotIn('"'+key+'"', public)
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_original_captured_state_rejects_stale_numeric_cache(self):
        g = self.game(('lose',)); source = self.actor(g); context = RuleContext(g.state, source, 1)
        self.cast(g, 'lose'); codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        saved = codec.encode(context); restored = codec.decode(saved)
        self.assertEqual(restored.state.entities[source].conditional_attack, 2)
        for value in (0, 1, 3, True, 2.0, None):
            bad = deepcopy(saved); bad['fields']['state']['state']['entities'][str(source)]['conditional_attack'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): codec.decode(bad)
        old = deepcopy(context.state); old.entities[source].conditional_attack = 0
        with self.assertRaises(ValueError): codec.encode(RuleContext(old, source, 1))
        self.portable(g)

    def test_rehashed_wire_rejects_missing_stale_and_forged_cache(self):
        g = self.game(); snap = g.snapshot(); source = self.actor(g)
        for value in (0, 1, 3, True, 2.0, -1, None, '2'):
            bad = deepcopy(snap); bad['state']['entities'][str(source)]['conditional_attack'] = value
            with self.subTest(value=value): self.reject(bad)
        bad = deepcopy(snap); del bad['state']['entities'][str(source)]['conditional_attack']; self.reject(bad)
        plain = g.state.players[2].board[0]; bad = deepcopy(snap)
        bad['state']['entities'][str(plain)]['conditional_attack'] = 2; self.reject(bad)

    def test_rehashed_wire_rejects_changed_native_scope_and_duplicate_instance(self):
        g = self.game(); snap = g.snapshot(); source = self.actor(g)
        for field, value in (('operand', 'self_damaged'), ('amount', 3), ('layer', 'final_attack')):
            bad = deepcopy(snap); bad['state']['entities'][str(source)]['abilities'][0]['stat_relation'][field] = value
            with self.subTest(field=field): self.reject(bad)
        bad = deepcopy(snap); row = deepcopy(bad['state']['entities'][str(source)]['abilities'][0])
        row['id'] = bad['state']['next_attachment_id']; bad['state']['next_attachment_id'] += 1
        bad['state']['entities'][str(source)]['abilities'].append(row); self.reject(bad)

    def test_schema_and_protocol_reject_all_old_or_nonstrict_versions(self):
        g = self.game(); snap = g.snapshot(); self.assertEqual(snap['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(snap['ruleset']['id'], 'prototype-v302')
        self.assertEqual(snap['mechanics_version']['version'], CORE_EFFECTS_VERSION)
        for value in (*range(1, 218), True, 184.0, 217):
            bad = deepcopy(snap); bad['schema_version'] = value
            with self.subTest(value=value), self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())
        self.portable(g)
