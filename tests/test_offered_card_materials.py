"""Real menus freeze physical material before selection and acquisition."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game,
    PlayCard, PlayerSetup, Registry, Scenario, SelectChoice, SnapshotError, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.discovery_offers import (ACCEPTED, decode_offer, encode_offer,
    offer_for_result, unselected_materials)
from hs_sim.engine.offered_card_materials import OfferedCardMaterial, capture
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import ChooseFromZone
import test_discovery_delivery_consumers as t

PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
P = 'offered-material.'
HERO, POWER, DISC = (P + x for x in ('hero', 'power', 'discover'))
FACES = tuple(P + x for x in ('minion', 'spell', 'weapon', 'location', 'hero-card'))


@lru_cache(maxsize=None)
def registry(role, pin):
    if role not in ('writer', 'reader') or pin != PIN:
        raise ValueError('Independent immutable material fixture key required')
    r = Registry('k176-original-offered-material')
    r.register_behavior(P + 'noop', lambda c: ())
    r.register_behavior(DISC, lambda c: (ChooseFromZone(c.player_id, c.player_id,
        Zone.DECK, operation='copy_current', distinct='entity', source_id=c.source_id,
        discovery=True),))
    r.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, on_use=P + 'noop'))
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=30,
        metadata=CardMetadata(False, (CardClass.MAGE,), None, tribes=())))
    r.register_card(CardDefinition(DISC, DISC, CardType.SPELL, on_play=DISC))
    for cid, kind in zip(FACES, (CardType.MINION, CardType.SPELL, CardType.WEAPON, CardType.LOCATION, CardType.HERO)):
        kw = dict(cost=7, metadata=CardMetadata(False, (CardClass.MAGE,), None, tribes=()))
        if kind == CardType.MINION: kw.update(attack=3, health=8)
        if kind == CardType.SPELL: kw['on_play'] = P + 'noop'
        if kind == CardType.WEAPON: kw.update(attack=4, durability=5)
        if kind == CardType.LOCATION: kw.update(durability=3, on_use=P + 'noop')
        if kind == CardType.HERO: kw.update(health=30, hero_card=True, initial_hero_power=POWER, on_play=P + 'noop')
        r.register_card(CardDefinition(cid, cid, kind, **kw))
    r.validate(); r.freeze()
    return r


def actual_offer(g):
    event = next(e for e in reversed(g.events) if e.kind == ACCEPTED)
    return decode_offer(g, dict(event.data)['original_offer'])


class OfferedCardMaterialTests(unittest.TestCase):
    def test_current_deck_copy_freezes_original_local_price_before_selected_only_discount(self):
        g = t.game((t.BOOST, t.COPY)); t.play(g, t.BOOST)
        original = t.first(g, t.A, 'deck'); t.play(g, t.COPY)
        offered = actual_offer(g); material = next(m for m in offered.materials if m.card_id == t.A)
        self.assertEqual(material.route, 'physical')
        self.assertEqual(material.physical.origin.entity_id, original.id)
        self.assertEqual(material.physical.local.enchantments, tuple(original.enchantments))
        t.portable(self, g); t.choose(g, t.A)
        row, = g.state.card_discovery_history
        self.assertEqual(offer_for_result(g, row.result), offered)
        self.assertEqual(len(unselected_materials(g, row.result)), 2)
        recipient = t.first(g, t.A)
        self.assertNotEqual(recipient.id, original.id)
        self.assertGreater(len(recipient.enchantments), len(material.physical.local.enchantments))
        self.assertEqual(g.state.entities[original.id].enchantments, original.enchantments)
        t.portable(self, g)

    def test_duplicate_same_faces_preserve_distinct_entities_and_distinct_local_material(self):
        g = t.game((t.BOOST, t.COPY), deck=(t.A, t.A, t.B)); t.play(g, t.BOOST); t.play(g, t.COPY)
        offer = actual_offer(g); twins = [m for m in offer.materials if m.card_id == t.A]
        self.assertEqual(len(twins), 2)
        self.assertEqual(len({m.physical.origin.entity_id for m in twins}), 2)
        self.assertEqual(sorted(len(m.physical.local.enchantments) for m in twins), [0, 1])
        t.choose(g, key=twins[0].option_id)
        row, = g.state.card_discovery_history
        self.assertEqual(len(unselected_materials(g, row.result)), 2)
        self.assertIn(twins[1], unselected_materials(g, row.result)); t.portable(self, g)

    def test_original_stored_dark_gift_keeps_unmodified_physical_material_and_separate_pairings(self):
        g = t.game((t.STORED,)); original = {i: deepcopy(g.state.entities[i]) for i in g.state.players[1].deck}
        t.play(g, t.STORED); offer = actual_offer(g)
        for option, material in zip(offer.options, offer.materials):
            physical = material.physical; entity = original[physical.origin.entity_id]
            self.assertEqual((material.option_id, material.card_id), (option.id, option.card_id))
            self.assertEqual(physical.local.abilities, tuple(entity.abilities))
            self.assertEqual(physical.local.enchantments, tuple(entity.enchantments))
            self.assertEqual(len(option.effects[0].offered), 3)
        t.portable(self, g); t.choose(g, t.A)
        row, = g.state.card_discovery_history
        self.assertEqual(offer_for_result(g, row.result), offer); t.portable(self, g)

    def test_map_initial_physical_material_survives_later_ordinary_reward_choice(self):
        g = t.game((t.MAP_TAKE,)); t.play(g, t.MAP_TAKE); offer = actual_offer(g)
        self.assertTrue(all(m.route == 'physical' for m in offer.materials))
        t.choose(g, t.A); row, = g.state.card_discovery_history
        self.assertEqual(offer_for_result(g, row.result), offer)
        t.play(g, t.A)
        self.assertIsNone(g._frame.original_discovery_offer)
        t.portable(self, g); t.choose(g, t.B)
        self.assertEqual(offer_for_result(g, row.result), offer)

    def test_resurrection_preserves_exact_original_death_instead_of_current_corpse(self):
        g = t.game((t.KILL, t.DEAD), board=(t.CARD, t.A)); source = t.first(g, t.A, 'board').id
        t.play(g, t.KILL, source); death, = g.state.death_history
        t.play(g, t.DEAD); offer = actual_offer(g); material, = offer.materials
        self.assertEqual(material.route, 'death'); self.assertEqual(material.death, death)
        self.assertIsNone(material.physical); t.portable(self, g)
        t.choose(g, t.A); self.assertNotEqual(t.first(g, t.A, 'board').id, source)
        row, = g.state.card_discovery_history
        self.assertEqual(offer_for_result(g, row.result).materials, (material,)); t.portable(self, g)

    def test_enemy_hand_discard_material_keeps_original_owner_and_chooser_separate(self):
        g = t.game((t.DISCARD,), other_hand=(t.A, t.B)); t.play(g, t.DISCARD); offer = actual_offer(g)
        self.assertEqual(offer.choice.player_id, 1)
        self.assertTrue(all(m.physical.origin.owner == 2 and m.physical.origin.zone == Zone.HAND for m in offer.materials))
        t.choose(g, t.A); row, = g.state.card_discovery_history
        self.assertEqual(offer_for_result(g, row.result), offer); t.portable(self, g)

    def test_all_five_hand_card_types_keep_full_material_through_real_deck_discovery(self):
        for cid in FACES:
            with self.subTest(cid=cid):
                setups = (PlayerSetup(HERO, hand=(DISC,), deck=(cid,), mana=20, max_mana=20, mana_cap=20,
                    hero_power_card_id=POWER), PlayerSetup(HERO, hero_power_card_id=POWER))
                g = Game.from_scenario(Scenario(setups), registry('writer', PIN))
                source = g.state.players[1].hand[0]; original = g.state.entities[g.state.players[1].deck[0]]
                g.apply(PlayCard(1, source)); offer = actual_offer(g); material, = offer.materials
                self.assertEqual(material.physical.origin.kind, original.kind)
                self.assertEqual(material.physical.durability, original.durability)
                reader = registry('reader', PIN); saved = g.snapshot()
                self.assertIsNot(reader, g.registry)
                self.assertEqual(Game.from_snapshot(saved, reader).snapshot(), saved)
                choice = g.state.pending_choice; g.apply(SelectChoice(1, choice.id, (choice.options[0].id,)))
                self.assertEqual(replay(build_replay(g), reader).snapshot(), g.snapshot())
                self.assertEqual(g.clone().snapshot(), g.snapshot())
                row, = g.state.card_discovery_history
                self.assertEqual(offer_for_result(g, row.result).materials, (material,))

    def test_capture_is_pure_and_does_not_allocate_sample_or_execute_original_producers(self):
        for source in (t.COPY, t.TAKE, t.TOP, t.GIFT, t.TEMP, t.BOARD):
            g = t.game((source,)); t.play(g, source); saved = g.snapshot(); offer = actual_offer(g)
            probe = SimpleNamespace(state=g.state, registry=g.registry)
            self.assertEqual(tuple(capture(probe, o) for o in offer.options), offer.materials)
            self.assertEqual(g.snapshot(), saved)

    def test_full_original_automatic_choice_uses_frozen_offer_without_pending_frame(self):
        g = t.game((t.AUTO,), pid=2); t.play(g, t.AUTO)
        self.assertIsNone(g._frame); row, = g.state.card_discovery_history
        offer = offer_for_result(g, row.result)
        self.assertEqual(len(offer.materials), 3)
        self.assertTrue(all(m.route == 'printed' for m in offer.materials)); t.portable(self, g)

    def test_acquisition_failure_rolls_back_to_exact_original_material(self):
        g = t.game(mode='fail_acquire'); t.play(g, t.DISC); saved = g.snapshot(); offer = actual_offer(g)
        from hs_sim.engine.errors import ResolutionError
        with self.assertRaises(ResolutionError): t.choose(g, t.A)
        self.assertEqual(g.snapshot(), saved); self.assertEqual(g._frame.original_discovery_offer, offer)
        t.portable(self, g, 'fail_acquire')

    def test_rehashed_waiting_material_cannot_replace_the_real_original_request_window(self):
        g = t.game((t.COPY,)); t.play(g, t.COPY); offer = actual_offer(g); item = offer.materials[0]
        forged = replace(item, physical=replace(item.physical,
            local=replace(item.physical.local, base_attack=item.physical.local.base_attack + 9)))
        changed = replace(offer, materials=(forged, *offer.materials[1:]))
        old_raw, new_raw = encode_offer(g, offer), encode_offer(g, changed)
        codec = FrameCodec(g.mechanics, g.registry)
        old_value, new_value = codec.encode(offer), codec.encode(changed)
        saved = deepcopy(g.snapshot()); count = 0
        def rewrite(value):
            nonlocal count
            if value == old_value:
                count += 1
                return deepcopy(new_value)
            if isinstance(value, dict):
                return {k: new_raw if k == 'original_offer' and v == old_raw else rewrite(v) for k, v in value.items()}
            if isinstance(value, list): return [rewrite(v) for v in value]
            return value
        saved = rewrite(saved); self.assertEqual(count, 1)
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, t.registry('plain', 'reader'))
        # Also bypass outer JSON hashes: matching publication plus a matching
        # live frame still cannot replace the real paid request-window state.
        from hs_sim.engine.discovery_offers import validate_boundary
        g._events = [replace(e, data=tuple((key, new_raw if key == 'original_offer' else value)
            for key, value in e.data)) if e.kind == ACCEPTED else e for e in g._events]
        g._frame = replace(g._frame, original_discovery_offer=changed)
        with self.assertRaisesRegex(ValueError, 'actual original physical material'):
            validate_boundary(g, g._events)

    def test_material_cannot_cross_slots_or_leak_in_either_player_interface(self):
        g = t.game((t.COPY,)); t.play(g, t.COPY); offer = actual_offer(g)
        with self.assertRaises(ValueError): replace(offer, materials=offer.materials[:-1])
        with self.assertRaises(ValueError): replace(offer, materials=tuple(reversed(offer.materials)))
        for pid in (1, 2):
            visible = json.dumps(g.for_player(pid).observe()) + json.dumps(g.for_player(pid).legal_actions()) + json.dumps(g.player_events(pid))
            for field in ('original_discovery_offer', 'materials', 'physical', 'next_attachment_id', 'original_offer'):
                self.assertNotIn('"' + field + '"', visible)
        saved = g.snapshot(); saved['schema_version'] = 379
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, t.registry('plain', 'reader'))


if __name__ == '__main__': unittest.main()
