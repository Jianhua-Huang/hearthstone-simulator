"""Original actual healing facts and one isolated Crystal Stag consumer."""
from copy import deepcopy
from dataclasses import dataclass, FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, DeckSpec, EndTurn, Game,
    HealingKind, HealingRecord, HealthFlow, HealthLayer, HealthOp, HealthRule, IllegalAction,
    Keyword, MatchSetup, PlayCard, PlayerSetup, Rarity, ResolutionError, RewindSpec, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, Zone, health_result, healing_records,
    hero_was_healed, restored_health)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, DamageBatch, Destroy, Effect, GainArmor, Heal, HealBatch, InvokeBehavior, RequestChoice,
    ReturnToHand, Transform)
from hs_sim.engine.healing_history import validate_state
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE = 'DAL_799'
SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/actual-healing-history-basics.json'
PIN = 'd3be3c81bd60a9d6650fc755dda526eb23baf8798b066f0178d103c59cafbd0f'


def evidence():
    packet = json.loads(SUPPORT.read_bytes())
    if canonical_digest(packet) != PIN or len(packet['records']) != 1:
        raise ValueError('Complete original healing evidence changed')
    row = packet['records'][0]
    if row['id'] != NATIVE or canonical_digest(row['data']) != row['data_sha256']:
        raise ValueError('Original Crystal Stag row changed')
    return row['data']


@dataclass(frozen=True)
class SavedHealing(Effect):
    row: HealingRecord

    def __post_init__(self):
        if type(self.row) is not HealingRecord: raise ValueError('Expected complete original healing row')
        self.row.__post_init__()


def mechanics():
    return default_mechanics('b74-healing-typed-test').register(SavedHealing,
        lambda r, work: (GainArmor(work.row.health_result.source_controller, work.row.health_result.healed),))


def registry():
    r = opening_registry(); raw = evidence()
    r.register_behavior('heal.native', lambda c: (CopyMinion(c.source_id, c.player_id),)
        if restored_health(c.state, c.player_id) >= 5 else ())
    r.register_card(CardDefinition(NATIVE, raw['name'], CardType.MINION,
        cost=raw['cost'], attack=raw['attack'], health=raw['health'],
        keywords=(Keyword.RUSH,), battlecry='heal.native',
        metadata=metadata(CardClass.DRUID, rarity=Rarity.EPIC, tribes=('beast',))))
    r.register_card(CardDefinition('plain', 'Plain target', CardType.MINION, attack=1, health=10))
    r.register_card(CardDefinition('other', 'Other face', CardType.MINION, attack=2, health=10))
    r.register_card(CardDefinition('life', 'Original lifesteal source', CardType.MINION,
        attack=2, health=10, keywords=(Keyword.LIFESTEAL,)))
    hero = lambda c, p=None: c.state.players[c.player_id if p is None else p].hero_id
    body = lambda c, p=1, i=0: c.state.players[p].board[i]
    scripts = {
        'wound': lambda c: (Damage(hero(c), 2, c.source_id),),
        'wound.five': lambda c: (Damage(hero(c), 5, c.source_id),),
        'heal.five': lambda c: (Heal(hero(c), 5, c.source_id, HealingKind.SPELL),),
        'heal.four': lambda c: (Heal(hero(c), 4, c.source_id),),
        'heal.zero': lambda c: (Heal(hero(c), 0, c.source_id),),
        'heal.unknown': lambda c: (Heal(hero(c), 5),),
        'wound.batch': lambda c: (DamageBatch((Damage(hero(c), 2, c.source_id),
            Damage(hero(c, 2), 2, c.source_id), Damage(body(c), 2, c.source_id))),),
        'heal.batch': lambda c: (HealBatch((Heal(hero(c), 5, c.source_id),
            Heal(hero(c, 2), 5, c.source_id), Heal(body(c), 5, c.source_id), Heal(hero(c), 5, c.source_id))),),
        'heal.enemy': lambda c: (Heal(hero(c, 2), 5, c.source_id),),
        'heal.other.source': lambda c: (Heal(hero(c), 5, body(c, 2)),),
        'heal.from.body': lambda c: (Heal(hero(c), 5, body(c)),),
        'heal.body': lambda c: (Heal(body(c), 5, c.source_id),),
        'wound.body': lambda c: (Damage(body(c), 2, c.source_id),),
        'grow': lambda c: (Buff(hero(c), health=5),),
        'armor': lambda c: (GainArmor(c.player_id, 5),),
        'life.hit': lambda c: (Damage(hero(c, 2), 2, body(c)),),
        'transform.source': lambda c: (Transform(body(c), 'other'),),
        'transfer.source': lambda c: (ChangeControl(body(c), 2),),
        'destroy.source': lambda c: (Destroy(body(c, 2), c.source_id),),
        'transform.target': lambda c: (Transform(body(c), 'other'),),
        'transfer.target': lambda c: (ChangeControl(body(c), 2),),
        'bounce.target': lambda c: (ReturnToHand(body(c)),),
        'stale': lambda c: (ReturnToHand(body(c)), Heal(body(c), 5, c.source_id)),
        'acquire': lambda c: (AddToHand(c.player_id, NATIVE),),
        'fail': lambda c: (Heal(hero(c), 5, c.source_id), AddToHand(c.player_id, 'unknown.healing.card')),
        'wait': lambda c: (Heal(hero(c), 5, c.source_id, on_result='heal.wait'),),
    }
    for cid, fn in scripts.items():
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    r.register_behavior('heal.wait', lambda c: (RequestChoice(c.player_id, (
        ChoiceOption('accept', 'Accept', (SavedHealing(c.state.healing_history[-1]),)),
        ChoiceOption('fault', 'Failure probe', (InvokeBehavior('heal.choice.fail', c.source_id, c.player_id),)),
    ), c.source_id),))
    r.register_behavior('heal.choice.fail', lambda c: (AddToHand(c.player_id, 'unknown.healing.choice'),))
    r.register_behavior('retry.heal', lambda c: (Heal(hero(c), 5, c.source_id),))
    r.register_card(CardDefinition('retry.heal', 'Original healing retry', CardType.SPELL,
        on_play='retry.heal', keywords=(Keyword.REWIND,), rewind=RewindSpec()))
    r.register_behavior('heal.inspect', lambda c: () if (
        c.state.entities[c.event.source_id].card_id != 'heal.batch' or
        restored_health(c.state, 1) == 6 and len(healing_records(c.state)) == 4
    ) else (_ for _ in ()).throw(ResolutionError('First event missed complete actual healing batch')))
    r.register_card(CardDefinition('watch', 'First event capture probe', CardType.MINION,
        health=4, triggers=(TriggerSpec('healed', 'heal.inspect'),)))
    for cid, flow, op in (('prevent', HealthFlow.HEALING, HealthOp.PREVENT),
                         ('heal.to.damage', HealthFlow.HEALING, HealthOp.CONVERT),
                         ('damage.to.heal', HealthFlow.DAMAGE, HealthOp.CONVERT)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=4,
            health_rules=(HealthRule(flow, op, source_relation='friendly', layer=HealthLayer.SOURCE),)))
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class ActualHealingTests(unittest.TestCase):
    def game(self, hand=(), *, board=('plain',), enemy=('plain',), enemy_hand=(), typed=False):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, mana=10, max_mana=10, deck=('card.1',)*8),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy, mana=10, max_mana=10, deck=('card.1',)*8)),
            seed=74), registry(), mechanics=mechanics() if typed else None)

    def play(self, g, cid):
        p = g.state.active_player
        source = next(e for e in g.state.players[p].hand if g.state.entities[e].card_id == cid)
        g.apply(PlayCard(p, source)); return source

    def rows(self, g): return healing_records(g.state)
    def check(self, g, *, typed=False):
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, registry(), mechanics=mechanics() if typed else None).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(), mechanics=mechanics() if typed else None).snapshot(), saved)

    def reject(self, saved):
        with self.assertRaises(SnapshotError) as err: Game.from_snapshot(rehash(saved), registry())
        self.assertNotIn('digest mismatch', str(err.exception))

    def complete(self):
        g = self.game(('wound.batch', 'heal.batch')); self.play(g, 'wound.batch'); self.play(g, 'heal.batch')
        return g

    def test_complete_native_raw_pin_and_full_face(self):
        raw = evidence(); native = registry().card(NATIVE)
        self.assertEqual((raw['dbf_id'], raw['cost'], raw['attack'], raw['health'], raw['tags']['CARDRACE']), (53179, 5, 4, 4, 20))
        self.assertEqual((native.cost, native.attack, native.health, native.keywords), (5, 4, 4, (Keyword.RUSH,)))
        self.assertEqual((native.metadata.classes, native.metadata.rarity, native.metadata.tribes), ((CardClass.DRUID,), Rarity.EPIC, ('beast',)))
        self.assertIn('restored 5 Health', raw['text_en'])

    def test_native_real_thirty_slot_experimental_constructed_fixture(self):
        r = registry()
        r.register_behavior('druid.power', lambda c: ())
        r.register_card(CardDefinition('druid.power', 'Druid power fixture', CardType.HERO_POWER,
            on_use='druid.power', metadata=metadata(CardClass.DRUID, collectible=False)))
        r.register_card(CardDefinition('druid.hero', 'Druid hero fixture', CardType.HERO, health=30,
            initial_hero_power='druid.power', metadata=metadata(CardClass.DRUID, collectible=False)))
        own = tuple(f'card.{i}' for i in range(1, 30)) + (NATIVE,)
        enemy = tuple(f'card.{i}' for i in range(1, 31))
        g = Game.from_decks(MatchSetup((DeckSpec('druid.hero', 'druid.power', CardClass.DRUID, own),
            DeckSpec('warrior.hero', 'warrior.power', CardClass.WARRIOR, enemy)), policy(r), 'coin', 74, 1), r)
        while g.state.pending_choice:
            q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, ()))
        self.assertEqual(tuple(map(len, g.state.opening.original_entities)), (30, 30))
        self.assertEqual((self.rows(g), restored_health(g.state, 1)), ((), 0))

    def test_initial_health_and_ordinary_damage_do_not_invent_healing(self):
        g = self.game(('wound',)); self.assertEqual((self.rows(g), g.state.next_healing_id), ((), 1))
        self.play(g, 'wound'); self.assertEqual(self.rows(g), ()); self.check(g)

    def test_actual_units_not_requested_or_hero_change_count(self):
        g = self.complete(); results = [row.health_result for row in self.rows(g)]
        self.assertEqual([r.healed for r in results], [2, 2, 2, 0])
        self.assertEqual([r.overheal for r in results], [3, 3, 3, 5])
        self.assertEqual((sum(r.base_amount for r in results), restored_health(g.state, 1)), (20, 6))
        self.assertEqual(len([r for r in g.state.hero_health_change_history if r.health_after > r.health_before]), 2)
        self.check(g)

    def test_complete_original_packet_identity_payload_and_order(self):
        g = self.complete(); rows = self.rows(g)
        original = [health_result(e) for e in g.events if e.kind == 'health_resolved' and health_result(e).flow == HealthFlow.HEALING.value]
        self.assertEqual([r.result for r in rows], [r.payload() for r in original])
        self.assertEqual([r.id for r in rows], [1, 2, 3, 4])
        self.assertEqual([r.health_result.packet_index for r in rows], [1, 2, 3, 4])
        self.assertEqual(len({r.health_result.batch_id for r in rows}), 1)

    def test_full_health_and_zero_keep_rows_without_positive_units(self):
        g = self.game(('heal.five', 'heal.zero')); self.play(g, 'heal.five'); self.play(g, 'heal.zero')
        self.assertEqual([(r.health_result.healed, r.health_result.overheal) for r in self.rows(g)], [(0, 5), (0, 0)])
        self.assertFalse(hero_was_healed(g.state, 1, turn=1)); self.check(g)

    def test_prevention_keeps_complete_zero_original_result(self):
        g = self.game(('wound', 'heal.five'), board=('plain', 'prevent')); self.play(g, 'wound'); self.play(g, 'heal.five')
        r = self.rows(g)[0].health_result
        self.assertEqual((r.prevention, r.base_amount, r.modified_amount, r.healed, r.overheal), ('rule_prevention', 5, 0, 0, 0))
        self.assertEqual(restored_health(g.state, 1), 0); self.check(g)

    def test_healing_converted_to_damage_is_retained_but_not_credited(self):
        g = self.game(('heal.five',), board=('plain', 'heal.to.damage')); self.play(g, 'heal.five')
        r = self.rows(g)[0].health_result
        self.assertEqual((r.original_flow, r.flow, r.converted, r.healed, r.health_lost), ('healing', 'damage', True, 0, 5))
        self.assertEqual(restored_health(g.state, 1), 0); self.check(g)

    def test_damage_converted_to_healing_counts_actual_final_restoration(self):
        # Add the original conversion provider through an ordinary public Summon.
        from hs_sim.engine.effects import Summon
        r = registry(); r.register_behavior('enable', lambda c: (Summon(c.player_id, 'damage.to.heal'),))
        r.register_card(CardDefinition('enable', 'Enable original conversion', CardType.SPELL, on_play='enable'))
        g = Game.from_scenario(Scenario((PlayerSetup('mage.hero', hand=('wound.five', 'enable', 'wound'), mana=10, max_mana=10),
            PlayerSetup('warrior.hero'))), r)
        self.play(g, 'wound.five'); self.play(g, 'enable'); self.play(g, 'wound')
        result = self.rows(g)[0].health_result
        self.assertEqual((result.original_flow, result.flow, result.converted, result.healed), ('damage', 'healing', True, 2))
        self.assertEqual(restored_health(g.state, 1), 2)
        self.assertEqual(Game.from_snapshot(g.snapshot(), r).snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), r).snapshot(), g.snapshot())

    def test_intrinsic_lifesteal_records_actual_original_source_once(self):
        g = self.game(('wound.five', 'life.hit'), board=('life',)); self.play(g, 'wound.five'); self.play(g, 'life.hit')
        rows = self.rows(g)
        self.assertEqual((len(rows), rows[0].health_result.from_lifesteal, rows[0].health_result.healed), (1, True, 2))
        self.assertEqual((restored_health(g.state, 1), rows[0].health_result.source_id), (2, g.state.players[1].board[0]))
        self.check(g)

    def test_source_controller_and_target_controller_are_independent(self):
        g = self.game(('wound', 'heal.other.source')); self.play(g, 'wound'); self.play(g, 'heal.other.source')
        self.assertEqual((restored_health(g.state, 1), restored_health(g.state, 2)), (0, 2))
        self.assertTrue(hero_was_healed(g.state, 1, turn=1))
        self.assertEqual((self.rows(g)[0].health_result.source_controller, self.rows(g)[0].health_result.target_controller), (2, 1))
        self.check(g)

    def test_enemy_character_healing_uses_frozen_source_credit(self):
        g = self.complete()
        self.assertEqual(sum(r.health_result.healed for r in healing_records(g.state, source_player=1, target_player=2)), 2)
        self.assertTrue(hero_was_healed(g.state, 2, turn=1)); self.check(g)

    def test_successful_unknown_source_is_preserved_and_quantity_is_explicitly_unsupported(self):
        g = self.game(('wound', 'heal.unknown')); self.play(g, 'wound'); self.play(g, 'heal.unknown')
        self.assertEqual((len(self.rows(g)), self.rows(g)[0].health_result.source_id), (1, None))
        self.assertTrue(hero_was_healed(g.state, 1, turn=1))
        for p in (1, 2):
            with self.assertRaises(UnsupportedDefinitionError): restored_health(g.state, p)
        self.assertEqual(restored_health(g.state, 1, turn=2), 0); self.check(g)

    def test_zero_unknown_source_does_not_invent_player_credit(self):
        g = self.game(('heal.unknown',)); self.play(g, 'heal.unknown')
        self.assertEqual((len(self.rows(g)), restored_health(g.state, 1), restored_health(g.state, 2)), (1, 0, 0))
        self.check(g)

    def test_target_and_turn_filters_apply_before_unknown_source_credit(self):
        g = self.game(('wound', 'heal.unknown')); self.play(g, 'wound'); self.play(g, 'heal.unknown')
        self.assertEqual(healing_records(g.state, source_player=1, target_player=2), ())
        self.assertEqual(healing_records(g.state, source_player=1, before_id=1), ())
        self.assertEqual(healing_records(g.state, source_player=1, target_kind=CardType.MINION), ())

    def test_all_game_and_current_turn_queries_have_no_mutable_total(self):
        g = self.game(('wound', 'heal.five'), enemy_hand=('wound', 'heal.five'))
        self.play(g, 'wound'); self.play(g, 'heal.five'); g.apply(EndTurn(1))
        self.play(g, 'wound'); self.play(g, 'heal.five')
        self.assertEqual((restored_health(g.state, 1), restored_health(g.state, 1, turn=2), restored_health(g.state, 2, turn=2)), (2, 0, 2))
        self.assertFalse(hero_was_healed(g.state, 1, turn=2)); self.assertTrue(hero_was_healed(g.state, 2, turn=2)); self.check(g)

    def test_minion_healing_does_not_satisfy_hero_target_query(self):
        g = self.game(('wound.body', 'heal.body')); self.play(g, 'wound.body'); self.play(g, 'heal.body')
        self.assertEqual(restored_health(g.state, 1), 2)
        self.assertFalse(hero_was_healed(g.state, 1, turn=1)); self.check(g)

    def test_stat_growth_and_armor_are_not_restoration_packets(self):
        g = self.game(('grow', 'armor')); self.play(g, 'grow'); self.play(g, 'armor')
        self.assertEqual((self.rows(g), restored_health(g.state, 1)), ((), 0)); self.check(g)

    def test_stale_target_skips_without_inventing_result_or_occurrence(self):
        g = self.game(('wound.body', 'stale')); self.play(g, 'wound.body'); self.play(g, 'stale')
        self.assertEqual(self.rows(g), ())
        self.assertTrue(any(e.kind == 'effect_skipped' for e in g.events)); self.check(g)

    def test_whole_numeric_batch_is_visible_at_first_original_healed_capture(self):
        g = self.game(('wound.batch', 'heal.batch'), board=('plain', 'watch'))
        self.play(g, 'wound.batch'); self.play(g, 'heal.batch')
        self.assertEqual((len(self.rows(g)), restored_health(g.state, 1)), (4, 6)); self.check(g)

    def test_original_source_survives_transformation_transfer_and_death(self):
        g = self.game(('wound', 'heal.from.body', 'transform.source', 'transfer.source', 'destroy.source'))
        self.play(g, 'wound'); self.play(g, 'heal.from.body'); original = self.rows(g)[0]
        self.play(g, 'transform.source'); self.play(g, 'transfer.source'); self.play(g, 'destroy.source')
        self.assertEqual(self.rows(g), (original,)); self.assertEqual((restored_health(g.state, 1), restored_health(g.state, 2)), (2, 0))
        self.assertEqual(original.health_result.source_card_id, 'plain'); self.check(g)

    def test_original_target_survives_transformation_and_transfer(self):
        g = self.game(('wound.body', 'heal.body', 'transform.target', 'transfer.target'))
        self.play(g, 'wound.body'); self.play(g, 'heal.body'); original = self.rows(g)[0]
        self.play(g, 'transform.target'); self.play(g, 'transfer.target')
        self.assertEqual(healing_records(g.state, target_player=1, target_kind=CardType.MINION), (original,))
        self.assertEqual(healing_records(g.state, target_player=2), ()); self.check(g)

    def test_original_target_survives_zone_migration(self):
        g = self.game(('wound.body', 'heal.body', 'bounce.target'))
        self.play(g, 'wound.body'); self.play(g, 'heal.body'); original = self.rows(g)[0]; self.play(g, 'bounce.target')
        self.assertEqual((self.rows(g), g.state.entities[original.health_result.target_id].zone), ((original,), Zone.HAND)); self.check(g)

    def test_native_threshold_counts_actual_units_and_preserves_rush_face(self):
        for heal, expected in (('heal.four', 1), ('heal.five', 2)):
            with self.subTest(heal=heal):
                g = self.game(('wound.five', heal, NATIVE)); self.play(g, 'wound.five'); self.play(g, heal); self.play(g, NATIVE)
                native = [g.state.entities[e] for e in g.state.players[1].board if g.state.entities[e].card_id == NATIVE]
                self.assertEqual(len(native), expected)
                self.assertTrue(all((e.attack, e.health) == (4, 4) and Keyword.RUSH in e.keywords for e in native)); self.check(g)

    def test_native_sees_healing_before_later_acquisition_and_across_turns(self):
        g = self.game(('wound.five', 'heal.five', 'acquire')); self.play(g, 'wound.five'); self.play(g, 'heal.five')
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g, 'acquire'); self.play(g, NATIVE)
        self.assertEqual(len([e for e in g.state.players[1].board if g.state.entities[e].card_id == NATIVE]), 2); self.check(g)

    def test_native_copy_obeys_original_full_board_capacity(self):
        g = self.game(('wound.five', 'heal.five', NATIVE), board=('plain',)*6)
        self.play(g, 'wound.five'); self.play(g, 'heal.five'); self.play(g, NATIVE)
        self.assertEqual(len(g.state.players[1].board), 7); self.check(g)

    def test_transaction_failure_rolls_back_new_history_and_original_numbers(self):
        g = self.game(('wound', 'fail')); self.play(g, 'wound'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'fail')
        self.assertEqual(g.snapshot(), before)

    def test_typed_healing_record_waiting_restore_clone_and_replay(self):
        g = self.game(('wound', 'wait'), typed=True); self.play(g, 'wound'); self.play(g, 'wait')
        self.assertEqual((len(self.rows(g)), restored_health(g.state, 1)), (1, 2)); self.check(g, typed=True)
        for branch in (g.clone(), Game.from_snapshot(g.snapshot(), registry(), mechanics=mechanics()),
                       replay(build_replay(g), registry(), mechanics=mechanics())):
            q = branch.state.pending_choice; branch.apply(SelectChoice(q.player_id, q.id, ('accept',)))
            self.assertEqual((branch.state.entities[branch.state.players[1].hero_id].armor, len(self.rows(branch))), (2, 1))
            self.check(branch, typed=True)

    def test_waiting_choice_failure_preserves_committed_heal_exactly(self):
        g = self.game(('wound', 'wait'), typed=True); self.play(g, 'wound'); self.play(g, 'wait'); before = g.snapshot()
        q = g.state.pending_choice
        with self.assertRaises(ResolutionError): g.apply(SelectChoice(q.player_id, q.id, ('fault',)))
        self.assertEqual(g.snapshot(), before)

    def test_original_rewind_retires_attempt_history_and_reuses_logical_cursor(self):
        g = self.game(('wound.five', 'retry.heal')); self.play(g, 'wound.five'); self.play(g, 'retry.heal')
        self.assertEqual((len(self.rows(g)), restored_health(g.state, 1)), (1, 5)); self.check(g)
        first = self.rows(g)[0].health_result.batch_id; q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, ('retry',)))
        self.assertEqual((len(self.rows(g)), self.rows(g)[0].id, restored_health(g.state, 1), g.state.next_healing_id), (1, 1, 5, 2))
        self.assertGreater(self.rows(g)[0].health_result.batch_id, first); self.check(g)

    def test_frozen_record_and_typed_codec_preserve_complete_payload(self):
        g = self.complete(); row = self.rows(g)[0]; codec = FrameCodec(g.mechanics, g.registry)
        self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(row)))), row)
        with self.assertRaises(FrozenInstanceError): row.id = 9
        with self.assertRaises(ValueError): replace(row, id=True)
        with self.assertRaises(ValueError): replace(row, result=tuple(reversed(row.result)))

    def test_saved_cursor_order_and_numeric_types_are_strict(self):
        g = self.complete()
        for field, value in (('id', True), ('action', 2.0), ('action', 99999)):
            with self.subTest(field=field):
                saved = g.snapshot(); saved['state']['healing_history'][0][field] = value; self.reject(saved)
        for value in (1, True, 5.0):
            saved = g.snapshot(); saved['state']['next_healing_id'] = value; self.reject(saved)
        saved = g.snapshot(); saved['state']['healing_history'].reverse(); self.reject(saved)

    def test_saved_complete_original_result_rejects_missing_duplicate_and_noncanonical_fields(self):
        g = self.complete()
        for mode in ('missing', 'duplicate', 'reverse', 'amount', 'identity', 'turn', 'flow'):
            with self.subTest(mode=mode):
                saved = json.loads(json.dumps(g.snapshot())); result = saved['state']['healing_history'][0]['result']
                if mode == 'missing': result.pop()
                elif mode == 'duplicate': result.append(deepcopy(result[0]))
                elif mode == 'reverse': result.reverse()
                else:
                    name, value = {'amount': ('healed', True), 'identity': ('target_id', 99999),
                        'turn': ('turn', 99), 'flow': ('original_flow', 'unknown')}[mode]
                    next(row for row in result if row[0] == name)[1] = value
                self.reject(saved)

    def test_original_nested_floor_payload_is_frozen_and_strict_in_healing_record(self):
        from test_v146_health_floor import registry as floor_registry
        r = floor_registry()
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('heal',), mana=10, max_mana=10),
            PlayerSetup('hero', board=('convert_h', 'self'))), seed=74), r)
        source = g.state.players[1].hand[0]; target = g.state.players[2].board[-1]
        g.apply(PlayCard(1, source, target)); row = self.rows(g)[0]
        self.assertTrue(row.health_result.converted); self.assertIsNotNone(row.health_result.floor_plan)
        codec = FrameCodec(g.mechanics, r)
        self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(row)))), row)
        self.assertEqual(Game.from_snapshot(g.snapshot(), floor_registry()).snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), floor_registry()).snapshot(), g.snapshot())
        saved = json.loads(json.dumps(g.snapshot()))
        next(pair for pair in saved['state']['healing_history'][0]['result'] if pair[0] == 'floor_plan')[1].pop()
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(saved), floor_registry())

    def test_original_nested_split_link_is_frozen_and_strict_in_healing_record(self):
        from test_v155_whole_budget_split import expanded_registry
        r = expanded_registry()
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('hurt', 'convert_split'), mana=10, max_mana=10),
            PlayerSetup('hero')), seed=74), r)
        self.play(g, 'hurt'); self.play(g, 'convert_split'); rows = self.rows(g)
        self.assertEqual((len(rows), restored_health(g.state, 1)), (3, 3))
        self.assertEqual([row.health_result.split_packet.index for row in rows], [1, 2, 3])
        codec = FrameCodec(g.mechanics, r)
        self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(rows[-1])))), rows[-1])
        self.assertEqual(Game.from_snapshot(g.snapshot(), expanded_registry()).snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), expanded_registry()).snapshot(), g.snapshot())
        saved = json.loads(json.dumps(g.snapshot()))
        link = next(pair for pair in saved['state']['healing_history'][0]['result'] if pair[0] == 'split_packet')[1]
        next(pair for pair in link if pair[0] == 'index')[1] = True
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(saved), expanded_registry())

    def test_rehashed_omission_and_valid_but_changed_original_facts_are_rejected(self):
        g = self.complete(); saved = g.snapshot()
        saved['state']['healing_history'] = []; saved['state']['next_healing_id'] = 1; self.reject(saved)
        saved = json.loads(json.dumps(g.snapshot()))
        result = saved['state']['healing_history'][0]['result']
        next(row for row in result if row[0] == 'source_controller')[1] = 2
        self.reject(saved)

    def test_borrowed_unknown_card_and_future_physical_epoch_are_rejected(self):
        g = self.complete()
        for name, value in (('source_card_id', 'unknown.healing.source'), ('source_zone_epoch', 99999),
                            ('target_entered_order', g.state.next_order), ('original_target_id', 99999)):
            saved = json.loads(json.dumps(g.snapshot())); result = saved['state']['healing_history'][0]['result']
            next(row for row in result if row[0] == name)[1] = value; self.reject(saved)

    def test_schema_and_required_persistent_fields_are_strict(self):
        g = self.game(); saved = g.snapshot()
        self.assertEqual((g.ruleset.id, g.mechanics.version, saved['schema_version']), ('prototype-v302', CORE_EFFECTS_VERSION, 265))
        for value in (*range(1, 218), 217, True, 216.0):
            changed = deepcopy(saved); changed['schema_version'] = value
            with self.assertRaises(SnapshotError): Game.from_snapshot(changed, registry())
        for field in ('next_healing_id', 'healing_history'):
            changed = deepcopy(saved); del changed['state'][field]; self.reject(changed)

    def test_queries_are_strict_pure_and_private_for_both_players(self):
        g = self.complete(); before = g.snapshot()
        for _ in range(3):
            self.assertEqual(restored_health(g.state, 1), 6)
            for p in (1, 2):
                view = json.dumps(g.observe(p))
                for private in ('healing_history', 'next_healing_id', 'HealthResult', 'health_resolved'):
                    self.assertNotIn(private, view)
        self.assertEqual(g.snapshot(), before)
        for kwargs in ({'source_player': True}, {'target_player': 1.0}, {'target_kind': 'HERO'},
                       {'target_kind': CardType.SPELL}, {'turn': 0}, {'turn': True}, {'before_id': 1.0}):
            with self.assertRaises(ValueError): healing_records(g.state, **kwargs)
        for p in (None, True, 1.0, 0, 3):
            with self.assertRaises(ValueError): restored_health(g.state, p)
            with self.assertRaises(ValueError): hero_was_healed(g.state, p, turn=1)


if __name__ == '__main__': unittest.main()
