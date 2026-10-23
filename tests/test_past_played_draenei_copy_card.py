"""Actual Vigilant battlecry with immutable original minion material."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards.past_played_draenei_copy_card import (
    VIGILANT, BEHAVIOR, load_batch, register_past_played_draenei_copy_card)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    CostSpec, EndTurn, Game, PlayerSetup, Scenario, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy,
    InvokeBehavior, RequestChoice, ReturnToHand, Transform)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.crafted_faces import CraftedMinionBlueprint, CraftedMinionRecipe
from hs_sim.engine.played_minion_copies import PlayedMinionCopyMaterial
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, CopyCard

P = 'k475.'
D1, D2, OTHER, ALL, TEMPLATE, WATCH = (P+s for s in ('d1', 'd2', 'other', 'all', 'template', 'watch'))
SUMMON, BUFF, KILL, MORPH, BOUNCE, FILL, FAIL, BAD = (
    P+s for s in ('summon', 'buff', 'kill', 'morph', 'bounce', 'fill', 'fail', 'bad'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())
COMPOSED = CraftedMinionRecipe(TEMPLATE, D1, OTHER).card_id


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry() if mode == 'full' else defaults()
    if mode != 'full': register_past_played_draenei_copy_card(r)
    r._version = 'k475-'+mode
    for cid, tribes, cost, attack, health in (
            (D1, ('draenei',), 2, 2, 3), (D2, ('draenei',), 3, 3, 4),
            (OTHER, ('beast',), 1, 1, 2), (ALL, ('all',), 1, 1, 1),
            (TEMPLATE, ('draenei', 'beast'), 1, 1, 1)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=attack,
            health=health, metadata=replace(META, tribes=tribes)))
    for cid in (D1, OTHER): r.register_crafted_minion_part(cid)
    r.register_crafted_minion_blueprint(CraftedMinionBlueprint(TEMPLATE, 'draenei', 'beast'))
    def fail(c): raise ResolutionError('K475 intentional late copy failure')
    def buff(c):
        target = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id == D1)
        return (BuffStoredCard(CardReference.capture(target), 5, 7, c.source_id, cost=CostSpec(set_to=0)),)
    def original(c):
        return next(p.minion_copy_material for p in c.state.play_history if p.card_id == D1)
    scripts = {
        SUMMON: lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(D2),), SummonCause.capture(c)),),
        BUFF: buff,
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        MORPH: lambda c: (Transform(c.target_id, OTHER),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        FILL: lambda c: tuple(AddToHand(c.player_id, OTHER, c.source_id)
            for _ in range(10-len(c.state.players[c.player_id].hand))),
        FAIL: fail,
        BAD: lambda c: (CopyCard(replace(original(c), play_id=999), c.player_id, mode='base', source_id=c.source_id),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            requires_target=cid in (KILL, MORPH, BOUNCE), metadata=META))
    def watch(c):
        e = c.event
        source = c.state.entities.get(e.source_id)
        if source is None or source.card_id != VIGILANT: return ()
        if mode == 'full_hand' and e.kind == 'battlecry_started':
            return (InvokeBehavior(FILL, c.source_id, c.player_id),)
        if mode == 'late_fail' and e.kind == 'card_added_to_hand':
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        wanted = 'card_added_to_hand' if mode == 'copy_wait' else 'battlecry_started'
        if mode not in ('start_wait', 'copy_wait') or e.kind != wanted: return ()
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=9, metadata=META,
        triggers=(TriggerSpec('battlecry_started', WATCH), TriggerSpec('card_added_to_hand', WATCH))))
    r.validate(); return r


def rehash(value):
    value['events_hash'] = canonical_hash(value['events'])
    value['state_hash'] = canonical_hash({k:v for k,v in value.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return value


class PlayedDraeneiCopyTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), *, board=(), enemy_hand=(), mode='normal'):
        self.mode = mode
        if mode not in ('normal', 'full'): board = (*board, WATCH)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(OTHER,)*6,
                mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_08', hand=enemy_hand, deck=(OTHER,)*6,
                mana=30, max_mana=30, mana_cap=30)), seed=475), fixture(mode))

    def copies(self, g, source):
        return [g.state.entities[e.target_id] for e in g.events
            if e.kind == 'card_created' and e.source_id == source and 'copied_from' in dict(e.data)]

    def test_complete_original_row_two_primary_faces_and_native_non_draenei_definition(self):
        data = load_batch(); raw = data['dependencies'][0]['record']
        self.assertEqual((len(data['dependencies']), len(data['official_observations'])), (1, 2))
        for face in data['official_observations']:
            self.assertEqual(batch.sha(face['response_file']), face['response_sha256'])
            batch.check_face(raw, face['face'], face['locale'])
        c = fixture().card(VIGILANT)
        self.assertEqual((c.cost, c.attack, c.health, c.battlecry, c.metadata.tribes), (1, 1, 2, BEHAVIOR, ()))
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_actual_full_registry_uses_real_velen_and_native_battlecry(self):
        g = self.game(('EX1_350', VIGILANT), mode='full'); old = self.play(g, 'EX1_350')
        source = self.play(g, VIGILANT); result = self.copies(g, source)
        self.assertEqual([(c.card_id, c.origin_entity_id) for c in result], [('EX1_350', old)])
        self.assertEqual(g.state.players[1].mana, 22)

    def test_real_entry_copies_last_draenei_pays_once_and_consumes_no_rng(self):
        g = self.game((D1, VIGILANT)); old = self.play(g, D1); rng = g._rng.getstate()
        source = self.play(g, VIGILANT); result = self.copies(g, source)
        self.assertEqual([(c.card_id, c.zone, c.origin_entity_id) for c in result], [(D1, Zone.HAND, old)])
        self.assertEqual((g.state.players[1].mana, len(g.state.play_history)), (27, 2))
        self.assertNotEqual(result[0].id, old); self.assertEqual(g._rng.getstate(), rng)

    def test_no_qualifying_play_has_no_copy(self):
        g = self.game((VIGILANT,), board=(D1,)); source = self.play(g, VIGILANT)
        self.assertFalse(self.copies(g, source)); self.assertFalse(g.state.players[1].hand)

    def test_later_summon_does_not_replace_original_play(self):
        g = self.game((D1, SUMMON, VIGILANT)); old = self.play(g, D1); self.play(g, SUMMON)
        source = self.play(g, VIGILANT); self.assertEqual(self.copies(g, source)[0].origin_entity_id, old)
        self.assertEqual([p.card_id for p in g.state.play_history], [D1, SUMMON, VIGILANT])

    def test_last_matching_play_survives_other_nonmatching_plays(self):
        g = self.game((D1, D2, OTHER, VIGILANT)); self.play(g, D1); old = self.play(g, D2); self.play(g, OTHER)
        source = self.play(g, VIGILANT); self.assertEqual(self.copies(g, source)[0].origin_entity_id, old)

    def test_enemy_play_does_not_replace_friendly_history(self):
        g = self.game((D1, VIGILANT), enemy_hand=(D2,)); old = self.play(g, D1)
        g.apply(EndTurn(1)); self.play(g, D2, player=2); g.apply(EndTurn(2))
        source = self.play(g, VIGILANT); self.assertEqual(self.copies(g, source)[0].origin_entity_id, old)

    def test_original_all_type_face_qualifies_for_draenei_history(self):
        g = self.game((ALL, VIGILANT)); old = self.play(g, ALL); source = self.play(g, VIGILANT)
        self.assertEqual([(x.card_id, x.origin_entity_id) for x in self.copies(g, source)], [(ALL, old)])

    def test_original_recipe_survives_later_transformation(self):
        g = self.game((D1, MORPH, VIGILANT)); old = self.play(g, D1); self.play(g, MORPH, old)
        source = self.play(g, VIGILANT); self.assertEqual(g.state.entities[old].card_id, OTHER)
        self.assertEqual([(c.card_id, c.attack, c.max_health) for c in self.copies(g, source)], [(D1, 2, 3)])
        self.portable(g)

    def test_original_recipe_survives_source_death(self):
        g = self.game((D1, KILL, VIGILANT)); old = self.play(g, D1); self.play(g, KILL, old)
        source = self.play(g, VIGILANT); self.assertEqual(g.state.entities[old].zone, Zone.GRAVEYARD)
        self.assertEqual(self.copies(g, source)[0].card_id, D1)

    def test_original_hand_buffs_and_discount_do_not_become_printed_copy(self):
        g = self.game((BUFF, D1, VIGILANT)); self.play(g, BUFF); old = self.play(g, D1)
        self.assertEqual((g.state.entities[old].attack, g.state.entities[old].max_health), (7, 10))
        source = self.play(g, VIGILANT); result = self.copies(g, source)[0]
        self.assertEqual((result.attack, result.max_health, result.base_cost), (2, 3, 2))
        self.assertFalse(result.enchantments)

    def test_composed_draenei_preserves_original_ordered_recipe_after_transformation(self):
        g = self.game((COMPOSED, MORPH, VIGILANT)); old = self.play(g, COMPOSED)
        material = g.state.play_history[0].minion_copy_material
        self.assertEqual(material.components, (D1, OTHER)); self.play(g, MORPH, old)
        source = self.play(g, VIGILANT); result = self.copies(g, source)[0]
        self.assertEqual((result.card_id, result.components, result.attack, result.max_health), (COMPOSED, (D1, OTHER), 3, 5))
        self.portable(g)

    def test_replayed_same_physical_minion_uses_latest_submission_and_original_owner(self):
        g = self.game((D1, BOUNCE, VIGILANT)); old = self.play(g, D1); self.play(g, BOUNCE, old)
        self.play(g, D1); source = self.play(g, VIGILANT)
        rows = [p for p in g.state.play_history if p.card_id == D1]
        self.assertEqual([p.source_id for p in rows], [old, old])
        self.assertGreater(rows[1].minion_copy_material.source.zone_epoch, rows[0].minion_copy_material.source.zone_epoch)
        self.assertEqual(self.copies(g, source)[0].copy_origin.entity_id, old)

    def test_real_brann_repeats_native_copy_with_one_payment(self):
        g = self.game((D1, VIGILANT), board=('LOE_077',)); self.play(g, D1)
        source = self.play(g, VIGILANT); self.assertEqual(len(self.copies(g, source)), 2)
        self.assertEqual(g.state.players[1].mana, 27)
        self.assertEqual(len({c.id for c in self.copies(g, source)}), 2)

    def test_full_hand_uses_ordinary_created_copy_burn(self):
        g = self.game((D1, VIGILANT), mode='full_hand'); self.play(g, D1); source = self.play(g, VIGILANT)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertEqual(self.copies(g, source)[0].zone, Zone.GRAVEYARD)
        self.assertTrue(any(e.kind == 'card_burned' and e.source_id == source for e in g.events))

    def test_wait_before_body_restores_original_history_and_continues_copy(self):
        g = self.game((D1, VIGILANT), mode='start_wait'); self.play(g, D1); source = self.play(g, VIGILANT)
        self.assertIsNotNone(g.state.pending_choice); self.assertFalse(self.copies(g, source))
        restored = self.portable(g); self.choose(g); self.choose(restored)
        self.assertEqual(restored.snapshot(), g.snapshot()); self.assertEqual(len(self.copies(g, source)), 1)

    def test_wait_after_copy_restores_typed_material_and_never_copies_twice(self):
        g = self.game((D1, VIGILANT), mode='copy_wait'); self.play(g, D1); source = self.play(g, VIGILANT)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(len(self.copies(g, source)), 1)
        restored = self.portable(g); self.choose(g); self.choose(restored)
        self.assertEqual(restored.snapshot(), g.snapshot()); self.assertEqual(len(self.copies(g, source)), 1)

    def test_late_failure_rolls_back_payment_history_entities_and_rng(self):
        g = self.game((D1, VIGILANT), mode='late_fail'); self.play(g, D1); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, VIGILANT)
        self.assertEqual(g.snapshot(), before)

    def test_waiting_failure_rolls_back_to_the_original_waiting_choice(self):
        g = self.game((D1, VIGILANT), mode='copy_wait'); self.play(g, D1); self.play(g, VIGILANT)
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before); self.choose(g)

    def test_fabricated_played_copy_material_is_rejected_transactionally(self):
        g = self.game((D1, BAD)); self.play(g, D1); before = g.snapshot()
        with self.assertRaises((ResolutionError, ValueError)): self.play(g, BAD)
        self.assertEqual(g.snapshot(), before)

    def test_current_copy_mode_is_rejected_for_original_played_base_material(self):
        g = self.game((D1,)); self.play(g, D1); material = g.state.play_history[0].minion_copy_material
        self.assertIs(type(material), PlayedMinionCopyMaterial)
        with self.assertRaises(ValueError): CopyCard(material, 1)

    def test_snapshot_rejects_lost_foreign_or_invalid_original_copy_material(self):
        g = self.game((D1,)); self.play(g, D1); saved = g.snapshot()
        for field, value in (('play_id', 999), ('components', [OTHER]), ('jade_size', 5), ('turn', 999)):
            with self.subTest(field=field):
                bad = deepcopy(saved); bad['state']['play_history'][0]['minion_copy_material'][field] = value
                with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), fixture())
        bad = deepcopy(saved); bad['state']['play_history'][0]['minion_copy_material'] = None
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), fixture())

    def test_player_views_do_not_expose_private_original_material(self):
        g = self.game((D1, VIGILANT)); self.play(g, D1); self.play(g, VIGILANT)
        for player in (1, 2):
            view = json.dumps(g.for_player(player).observe())
            self.assertNotIn('"minion_copy_material"', view)
            self.assertNotIn('"next_entity_id"', view)
        self.portable(g)

    def test_old_snapshot_schema_is_explicitly_rejected(self):
        g = self.game(); old = g.snapshot(); old['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError): Game.from_snapshot(old, fixture())
