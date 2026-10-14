"""Existing immutable opening facts express an original-source type exclusion."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, ChoicePurpose, DeckCondition,
    DeckSpec, Game, MatchSetup, OpeningHook, PlayCard, PlayerSetup, ResolutionError,
    Scenario, SelectChoice, SnapshotError, UnknownDeckFacts, Zone, matches_deck_condition)
from hs_sim.engine.effects import (AddToHand, ChangeManaCrystals, ChoiceOption, GainArmor,
    InvokeBehavior, RequestChoice)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.registry import RuleContext, UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, DestroyDeckMatching
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry

ROOT = Path(__file__).resolve().parents[1]
PIN = '20a0a4326b48024f2afb793eb2e6c1fdad1242b4a35e40f376162da66b5be443'
SOURCE = 'original.source'


def evidence():
    data = json.loads((ROOT / 'data/support/starting-source-type-expression.json').read_bytes())
    if canonical_digest(data) != PIN:
        raise ValueError('Starting source-type evidence changed')
    row, = data['records']
    if canonical_digest(row['data']) != row['data_sha256']:
        raise ValueError('Complete starting source-type row changed')
    return data


def no_other_original_minions(registry, state, player_id, source_id):
    """Trusted expression using existing facts; not a new public kernel API."""
    if type(player_id) is not int or player_id not in (1, 2):
        raise ValueError('Expected a player')
    if state.opening is None:
        raise UnknownDeckFacts('Constructed starting facts are required')
    identities = state.opening.original_entities[player_id - 1]
    if type(source_id) is not int or source_id not in identities:
        raise UnknownDeckFacts('The source must be an original physical deck row')
    # Resolve the excluded row and the entire tail, even after a known mismatch.
    definitions = tuple(registry.card(cid) for cid in state.players[player_id].original_deck)
    source_index = identities.index(source_id)
    return not any(card.kind == CardType.MINION for index, card in enumerate(definitions)
                   if index != source_index)


def source_id(state, player):
    return state.opening.original_entities[player - 1][state.players[player].original_deck.index(SOURCE)]


def registry(mode='plain'):
    r = opening_registry()
    r.register_behavior('blank', lambda c: ())
    for index in range(1, 31):
        r.register_card(CardDefinition('original.spell.' + str(index), 'Spell', CardType.SPELL,
            on_play='blank', metadata=metadata()))
    r.register_card(CardDefinition('original.weapon', 'Weapon', CardType.WEAPON, attack=1,
        durability=2, metadata=metadata()))
    r.register_card(CardDefinition('original.location', 'Location', CardType.LOCATION, durability=2,
        on_use='blank', metadata=metadata()))
    r.register_card(CardDefinition('original.extra', 'Another minion', CardType.MINION, health=2, metadata=metadata()))
    r.register_card(CardDefinition('original.changed', 'Different current face', CardType.SPELL,
        on_play='blank', metadata=metadata()))
    def branch(c):
        matched = no_other_original_minions(r, c.state, c.player_id, c.source_id)
        return (GainArmor(c.player_id, 3 if matched else 1),)
    def pause(c):
        return RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue', ()),), c.source_id)
    def start(c):
        if mode == 'before':
            return (pause(c), InvokeBehavior('original.branch', c.source_id, c.player_id))
        if mode == 'selected':
            return (pause(c), *branch(c))
        return branch(c)
    r.register_behavior('original.branch', branch)
    r.register_behavior('original.start', start)
    r.register_behavior('original.prepare', lambda c: (
        ChangeManaCrystals(c.player_id, 9),
        *(AddToHand(c.player_id, cid) for cid in ('original.alter', 'original.clear', 'original.check', 'original.fault'))))
    r.register_card(CardDefinition(SOURCE, 'Original source fixture', CardType.MINION, health=1,
        metadata=metadata(), opening_hooks=(OpeningHook('before_deal', 'original.start'),
                                           OpeningHook('after_mulligan', 'original.prepare'))))
    def original_context(c):
        return InvokeBehavior('original.branch', source_id(c.state, c.player_id), c.player_id)
    r.register_behavior('original.alter', lambda c: (TransformStoredCard(
        CardReference.capture(c.state.entities[source_id(c.state, c.player_id)]), 'original.changed', c.source_id),))
    r.register_behavior('original.clear', lambda c: (DestroyDeckMatching(c.player_id, count=40, reveal=False),))
    r.register_behavior('original.check', lambda c: (original_context(c),))
    r.register_behavior('original.fault', lambda c: (original_context(c), InvokeBehavior('original.late-fault', c.source_id, c.player_id)))
    r.register_behavior('original.late-fault', lambda c: (AddToHand(c.player_id, 'unknown.original-source'),))
    for name in ('alter', 'clear', 'check', 'fault'):
        cid = 'original.' + name
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata()))
    return r


class StartingSourceTypeExpressionTests(unittest.TestCase):
    def match(self, extra=(), *, source_slot=0, mode='plain', finish=True):
        r = registry(mode)
        own = list(extra) + ['original.spell.' + str(i) for i in range(1, 30 - len(extra))]
        own.insert(source_slot, SOURCE)
        other = (SOURCE,) + tuple('original.spell.' + str(i) for i in range(1, 30))
        g = Game.from_decks(MatchSetup((
            DeckSpec('mage.hero', 'mage.power', CardClass.MAGE, tuple(own)),
            DeckSpec('warrior.hero', 'warrior.power', CardClass.WARRIOR, other)),
            policy(r), 'coin', 83, 1), r)
        return self.finish(g) if finish else g
    def finish(self, g):
        while g.state.pending_choice:
            q = g.state.pending_choice
            g.apply(SelectChoice(q.player_id, q.id, () if q.purpose == ChoicePurpose.MULLIGAN else ('ok',)))
        return g
    def query(self, g, player=1):
        return no_other_original_minions(g.registry, g.state, player, source_id(g.state, player))
    def armor(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].armor
    def play(self, g, name):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, eid))
    def portable(self, g, mode='plain'):
        saved = json.loads(json.dumps(g.snapshot()))
        h = Game.from_snapshot(saved, registry(mode))
        self.assertEqual(h.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(mode)).snapshot(), saved)
        return h

    def test_complete_real_need_and_no_real_mug_zee_adapter(self):
        packet = evidence()
        self.assertEqual(packet['records'][0]['id'], 'JAIL_800')
        self.assertEqual(packet['new_real_card_adapters'], [])
        self.assertEqual(packet['new_runtime_capabilities'], 0)
        self.assertNotIn('JAIL_800', registry().cards)

    def test_start_hook_resolves_all_original_types_and_excludes_its_source(self):
        for slot in (0, 15, 29):
            g = self.match(('original.weapon', 'original.location'), source_slot=slot)
            self.assertTrue(self.query(g)); self.assertEqual(self.armor(g), 3)
            self.assertEqual(self.armor(g, 2), 3); self.portable(g)

    def test_one_other_original_minion_is_false_and_opponent_facts_are_separate(self):
        g = self.match(('original.extra',))
        self.assertFalse(self.query(g)); self.assertEqual(self.armor(g), 1)
        self.assertTrue(self.query(g, 2)); self.assertEqual(self.armor(g, 2), 3); self.portable(g)

    def test_existing_original_no_spell_condition_is_independent(self):
        g = self.match()
        self.assertTrue(self.query(g))
        self.assertFalse(matches_deck_condition(g.state, g.registry, 1, DeckCondition('starting', 'no_spells')))
        self.assertEqual(self.armor(g), 3)

    def test_current_source_face_changes_do_not_replace_original_slot_or_card_facts(self):
        g = self.match(); eid = source_id(g.state, 1); original = g.state.players[1].original_deck
        self.play(g, 'original.alter')
        self.assertEqual(g.state.entities[eid].card_id, 'original.changed')
        self.assertEqual(g.state.players[1].original_deck, original)
        self.assertTrue(self.query(g)); self.play(g, 'original.check')
        self.assertEqual(self.armor(g), 6); self.portable(g)

    def test_clearing_current_deck_does_not_erase_an_original_other_minion(self):
        g = self.match(('original.extra',)); self.play(g, 'original.clear')
        self.assertEqual(g.state.players[1].deck, [])
        self.assertFalse(self.query(g)); self.play(g, 'original.check')
        self.assertEqual(self.armor(g), 2); self.portable(g)

    def test_unknown_tail_and_excluded_original_definition_are_not_short_circuited(self):
        g = self.match(('original.extra',)); state = g.state
        # Host diagnostics only; malformed facts are not a valid native opening.
        state.players[1].original_deck = state.players[1].original_deck[:-1] + ('unknown.original-tail',)
        with self.assertRaises(UnsupportedDefinitionError):
            no_other_original_minions(g.registry, state, 1, source_id(g.state, 1))
        state = g.state; original_id = source_id(state, 1)
        rows = list(state.players[1].original_deck); rows[0] = 'unknown.original-source'; state.players[1].original_deck = tuple(rows)
        with self.assertRaises(UnsupportedDefinitionError):
            no_other_original_minions(g.registry, state, 1, original_id)

    def test_scenario_and_foreign_or_generated_source_do_not_supply_original_proof(self):
        r = registry(); s = Game.from_scenario(Scenario((PlayerSetup('mage.hero', deck=(SOURCE,)),
            PlayerSetup('warrior.hero'))), r)
        with self.assertRaises(UnknownDeckFacts):
            no_other_original_minions(s.registry, s.state, 1, s.state.players[1].deck[0])
        g = self.match()
        for eid in (source_id(g.state, 2), g.state.players[1].hero_id,
                    self.entity_tool(g), True):
            with self.subTest(eid=eid), self.assertRaises(UnknownDeckFacts):
                no_other_original_minions(g.registry, g.state, 1, eid)

    def entity_tool(self, g):
        return next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == 'original.check')

    def test_before_and_selected_start_choices_restore_clone_and_replay(self):
        for mode in ('before', 'selected'):
            g = self.match(mode=mode, finish=False); h = self.portable(g, mode)
            self.assertNotEqual(g.state.pending_choice.purpose, ChoicePurpose.MULLIGAN)
            self.finish(g); self.finish(h); self.assertEqual(g.snapshot(), h.snapshot())
            self.assertEqual(self.armor(g), 3); self.portable(g, mode)

    def test_late_expression_error_rolls_back_existing_action_transaction(self):
        g = self.match(); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'original.fault')
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_query_is_pure_and_player_interfaces_do_not_export_original_decks(self):
        g = self.match(); before = g.snapshot()
        for _ in range(3):
            self.assertTrue(self.query(g)); self.assertTrue(self.query(g, 2))
        self.assertEqual(g.snapshot(), before)
        for player in (1, 2):
            public = json.dumps(g.observe(player)) + json.dumps(g.for_player(player).legal_actions())
            for key in ('original_deck', 'original_entities', 'resolution_frame'):
                self.assertNotIn('"' + key + '"', public)

    def test_saved_original_type_and_source_rows_remain_bound_to_match_setup(self):
        g = self.match(); saved = g.snapshot()
        for mutate in ('card', 'physical', 'swapped', 'generated'):
            bad = json.loads(json.dumps(saved))
            if mutate == 'card':
                bad['state']['players']['1']['original_deck'][1] = 'original.extra'
            elif mutate == 'physical':
                bad['state']['opening']['original_entities'][0][0] = bad['state']['players']['1']['hero_id']
            elif mutate == 'swapped':
                rows = bad['state']['opening']['original_entities'][0]
                rows[0], rows[1] = rows[1], rows[0]
            else:
                bad['state']['opening']['original_entities'][0][0] = self.entity_tool(g)
            bad['state_hash'] = canonical_hash({k: v for k, v in bad.items()
                if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
            with self.subTest(mutate=mutate), self.assertRaises(SnapshotError):
                Game.from_snapshot(bad, registry())

    def test_captured_context_source_rows_remain_bound_to_live_match_origin(self):
        g = self.match(); sid = source_id(g.state, 1)
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        encoded = codec.encode(RuleContext(g.state, sid, 1))
        for mutate in ('hero', 'swapped'):
            bad = json.loads(json.dumps(encoded))
            rows = bad['fields']['state']['state']['opening']['original_entities'][0]
            if mutate == 'hero':
                rows[0] = g.state.players[1].hero_id
            else:
                rows[0], rows[1] = rows[1], rows[0]
            with self.subTest(mutate=mutate), self.assertRaisesRegex(ValueError, 'Captured starting deck facts'):
                codec.decode(bad)

    def test_captured_context_keeps_original_rows_after_legitimate_current_face_change(self):
        g = self.match(); sid = source_id(g.state, 1)
        earlier = RuleContext(g.state, sid, 1)
        self.play(g, 'original.alter')
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        restored = codec.decode(codec.encode(earlier))
        self.assertEqual(restored.state.opening.original_entities, g.state.opening.original_entities)
        self.assertEqual(restored.source.card_id, SOURCE)
        self.assertEqual(g.state.entities[sid].card_id, 'original.changed')
