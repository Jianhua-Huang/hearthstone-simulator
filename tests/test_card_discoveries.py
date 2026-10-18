"""Actual discovery facts share existing manual/automatic choice execution."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_discovered_turn_cards import CARD, POOL, register_native_discovered_turn_cards
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    PlayCard, PlayerSetup, Rarity, Registry, Scenario, SelectChoice, SnapshotError, Zone)
from hs_sim.engine.card_discoveries import discovered_cards, discovered_this_turn, PUBLICATION
from hs_sim.engine.effects import AddToHand, ChoiceOption, GainArmor, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_choice_followups import DiscoverForPlayFollowup
from hs_sim.engine.model import ChoiceItem, ChoicePurpose, PendingChoice, TriggerSpec, Keyword, RewindSpec
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromPool, GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import ChooseFromZone

P = 'k170.'
HERO, A, B, C, FOUR, FOREIGN, MISSING, WATCH = (P + x for x in
    ('hero', 'a', 'b', 'c', 'four', 'foreign', 'missing', 'watch'))
DISC, GEN, DECK, COPY, TOP, FALSE, MENU, AUTO, BOARD, MAP, BAD, TWICE, BURN, EMPTY = (P + x for x in
    ('discover', 'generate', 'deck', 'copy', 'top', 'false', 'menu', 'auto', 'board', 'map', 'bad', 'twice', 'burn', 'empty'))
RETRY = P + 'retry'
CONTEXT = GenerationContext('k170-fact-fixture', 'experimental')
META = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())
TWOS = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=2, max_cost=2)


@lru_cache(maxsize=None)
def registry(mode='all', role='writer'):
    if role not in ('writer', 'reader'):
        raise ValueError('Independent immutable fixture registries required')
    r = Registry('discovery-facts-' + mode)
    register_native_discovered_turn_cards(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=30,
        metadata=replace(META, collectible=False, classes=(CardClass.MAGE,))))
    for cid in (A, B, C, FOUR, FOREIGN):
        card = CardDefinition(cid, cid, CardType.MINION, cost=4 if cid in (FOUR, FOREIGN) else 2,
            attack=1, health=3, metadata=replace(META, classes=(CardClass.WARRIOR,) if cid == FOREIGN else (CardClass.NEUTRAL,)))
        r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    members = (A, B, C) if mode == 'no_four' else (A, B, C, FOREIGN) if mode == 'foreign_four' else (A, B, C, FOUR, FOREIGN)
    if mode == 'unadapted':
        r.register_pool_card(PoolCard(MISSING, CardType.MINION, 4, META, attack=1))
        members += (MISSING,)
    r.register_pool(PoolDefinition(POOL, 'v1', CONTEXT.target_id, CONTEXT.mode,
        tuple(PoolMember(cid) for cid in members), complete=True))
    def discover(c, **extra):
        return DiscoverFromPool(c.player_id, POOL, TWOS, source_id=c.source_id, **extra)
    def menu(c, *, bad=False):
        return RequestChoice(c.player_id, tuple(ChoiceOption(cid, cid,
            (AddToHand(c.player_id, cid, c.source_id),),
            card_id=cid) for cid in (A, B)), c.source_id,
            purpose=ChoicePurpose.CARD_DISCOVERY if bad else ChoicePurpose.EFFECT,
            on_select=P+'fail' if bad else None)
    bodies = {
        DISC: lambda c: (discover(c),),
        GEN: lambda c: (GenerateFromPool(c.player_id, POOL, TWOS, source_id=c.source_id),),
        DECK: lambda c: (ChooseFromZone(c.player_id, c.player_id, Zone.DECK, operation='take', distinct='entity', source_id=c.source_id, discovery=True),),
        COPY: lambda c: (ChooseFromZone(c.player_id, c.player_id, Zone.DECK, operation='copy_current', source_id=c.source_id, discovery=True),),
        TOP: lambda c: (ChooseFromZone(c.player_id, 3-c.player_id, Zone.DECK, operation='top', distinct='entity', source_id=c.source_id, discovery=True),),
        FALSE: lambda c: (ChooseFromZone(c.player_id, c.player_id, Zone.DECK, operation='take', distinct='entity', source_id=c.source_id),),
        MENU: lambda c: (menu(c),),
        AUTO: lambda c: (CastSpell(c.player_id, DISC, c.source_id),),
        BOARD: lambda c: (discover(c, destination='board', cause=SummonCause.capture(c)),),
        MAP: lambda c: (DiscoverForPlayFollowup(discover(c)),),
        BAD: lambda c: (menu(c, bad=True),),
        TWICE: lambda c: (discover(c, discoveries=2, delivery='after_all'),),
        BURN: lambda c: (*(AddToHand(c.player_id, A, c.source_id) for _ in range(9)), discover(c)),
        EMPTY: lambda c: (DiscoverFromPool(c.player_id, POOL, PoolQuery(min_cost=99), source_id=c.source_id),),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=replace(META, collectible=False)))
    r.register_card(CardDefinition(RETRY, RETRY, CardType.SPELL, on_play=DISC,
        rewind=RewindSpec(1), keywords=(Keyword.REWIND,), metadata=replace(META, collectible=False)))
    def fail(c):
        raise ResolutionError('Fixture failure after genuine selection')
    r.register_behavior(P+'fail', fail)
    r.register_behavior(P+'watch', lambda c: (GainArmor(c.player_id, 1),)
        if c.event.player_id == c.player_id and discovered_this_turn(c.state, c.player_id) else ())
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=3,
        triggers=(TriggerSpec('card_added_to_hand', P+'watch'),), metadata=replace(META, collectible=False)))
    r.validate(); r.freeze()
    return r


def game(hand=(DISC,), *, pid=1, mode='all', board=(), deck=(A, B, C), other_hand=()):
    setup = tuple(PlayerSetup(HERO, hand=hand if p == pid else other_hand, deck=deck,
        board=board if p == pid else (), mana=30, max_mana=30, mana_cap=30) for p in (1, 2))
    return Game.from_scenario(Scenario(setup, active_player=pid, seed=170, generation_context=CONTEXT), registry(mode))


def play(g, cid, *, pid=None, entity_id=None):
    pid = g.state.active_player if pid is None else pid
    e = g.state.entities[entity_id] if entity_id is not None else next(g.state.entities[i]
        for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
    g.apply(PlayCard(pid, e.id, position=len(g.state.players[pid].board) if e.kind == CardType.MINION else None))
    return e.id


def choose(g, cid=None):
    q = g.state.pending_choice
    option = next(o for o in q.options if cid is None or o.card_id == cid)
    g.apply(SelectChoice(q.player_id, q.id, (option.id,)))
    return option.card_id


def portable(test, g, mode='all'):
    reader = registry(mode, 'reader')
    if g.registry is reader:
        reader = registry(mode, 'writer')
    test.assertIsNot(g.registry, reader)
    saved = json.loads(json.dumps(g.snapshot()))
    other = Game.from_snapshot(saved, reader)
    test.assertEqual(other.snapshot(), saved)
    test.assertEqual(g.clone().snapshot(), saved)
    test.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
    return other


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class CardDiscoveryTests(unittest.TestCase):
    def test_card_intent_requires_exactly_one_card_and_explicit_zone_boolean(self):
        for purpose in (ChoicePurpose.CARD_DISCOVERY, ChoicePurpose.POOL_DISCOVERY):
            for options, minimum, maximum in (((ChoiceItem('a', 'a'),), 1, 1),
                    ((ChoiceItem('a', 'a', A),), 0, 1)):
                with self.assertRaises(ValueError):
                    PendingChoice(1, 1, None, 'pick', options, minimum, maximum, purpose)
        with self.assertRaises(ValueError):
            ChooseFromZone(1, 1, Zone.DECK, discovery=1)

    def test_pending_selection_is_not_yet_discovered_and_result_keeps_full_offer(self):
        g = game(); play(g, DISC)
        original = g.state.pending_choice
        self.assertFalse(discovered_this_turn(g.state, 1)); portable(self, g)
        choose(g, B)
        row, = discovered_cards(g.state, 1)
        self.assertEqual(row.result.choice, original)
        self.assertEqual(row.result.selected[0].card_id, B)
        self.assertEqual(row.owner_turn_id, g.state.owner_turn_history[-1].id)
        self.assertTrue(discovered_this_turn(g.state, 1)); portable(self, g)

    def test_generate_generic_card_menu_and_unmarked_physical_choice_are_not_discover(self):
        for source in (GEN, MENU, FALSE):
            with self.subTest(source=source):
                g = game((source,)); play(g, source)
                if g.state.pending_choice is not None: choose(g)
                self.assertFalse(discovered_this_turn(g.state, 1))
                self.assertEqual(g.state.card_discovery_history, [])
                self.assertFalse(any(e.kind == PUBLICATION for e in g.events))

    def test_physical_take_copy_and_enemy_deck_top_count_for_chooser_without_new_hand_requirement(self):
        for source in (DECK, COPY, TOP):
            with self.subTest(source=source):
                g = game((source,)); play(g, source)
                self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.CARD_DISCOVERY)
                before = tuple(g.state.players[1].hand); choose(g)
                self.assertTrue(discovered_this_turn(g.state, 1))
                self.assertFalse(discovered_this_turn(g.state, 2))
                if source == TOP: self.assertEqual(tuple(g.state.players[1].hand), before)
                portable(self, g)

    def test_automatic_cast_commits_original_full_result_without_pending_choice(self):
        g = game((AUTO,)); play(g, AUTO)
        self.assertIsNone(g.state.pending_choice)
        row, = discovered_cards(g.state, 1)
        self.assertEqual(row.result.choice.purpose, ChoicePurpose.POOL_DISCOVERY)
        self.assertEqual(g.events[row.selection_event - 1].kind, 'spell_choice_automatic')
        self.assertEqual(len(row.result.choice.options), 3)
        portable(self, g)

    def test_two_actual_selections_survive_second_waiting_with_distinct_receipts(self):
        g = game((TWICE,)); play(g, TWICE); choose(g)
        self.assertEqual(len(discovered_cards(g.state, 1)), 1)
        self.assertIsNotNone(g.state.pending_choice); g = portable(self, g)
        choose(g)
        rows = discovered_cards(g.state, 1)
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0].result.choice.id, rows[1].result.choice.id)
        portable(self, g)

    def test_map_initial_is_discovery_remaining_pick_is_ordinary_choice(self):
        g = game((MAP,)); play(g, MAP); choose(g, A)
        self.assertEqual(len(discovered_cards(g.state, 1)), 1)
        play(g, A)
        self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.EFFECT)
        g = portable(self, g); choose(g)
        self.assertEqual(len(discovered_cards(g.state, 1)), 1)
        portable(self, g)

    def test_board_discovery_counts_and_full_hand_burn_counts_without_recipient_claim(self):
        for source in (BOARD, BURN):
            with self.subTest(source=source):
                g = game((source, CARD)); play(g, source); choose(g)
                self.assertTrue(discovered_this_turn(g.state, 1))
                if source == BOARD: self.assertEqual(len(g.state.players[1].board), 1)
                else: self.assertTrue(any(e.kind == 'card_burned' for e in g.events))
                portable(self, g)

    def test_selection_fact_visible_to_original_acquisition_reaction_without_new_effect_checkpoint(self):
        g = game(board=(WATCH,)); play(g, DISC); choose(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 1)
        row, = discovered_cards(g.state, 1)
        acquisition = next(e for e in g.events if e.kind == 'card_added_to_hand')
        self.assertLess(row.publication_event, acquisition.sequence)

    def test_empty_discovery_has_no_fact_and_consumes_no_rng(self):
        g = game((EMPTY,)); before = g.snapshot()['rng_state']; play(g, EMPTY)
        self.assertIsNone(g.state.pending_choice)
        self.assertFalse(discovered_this_turn(g.state, 1))
        self.assertEqual(g.snapshot()['rng_state'], before)

    def test_failure_after_selection_rolls_back_receipt_events_rng_and_original_waiting(self):
        g = game((BAD,)); play(g, BAD); before = g.snapshot()
        with self.assertRaises(ResolutionError): choose(g)
        self.assertEqual(g.snapshot(), before)
        self.assertFalse(discovered_this_turn(g.state, 1)); portable(self, g)

    def test_rewind_restores_facts_and_retires_attempt_publications_before_new_selection(self):
        g = game((RETRY,)); play(g, RETRY); choose(g, A)
        self.assertEqual(len(discovered_cards(g.state, 1)), 1)
        first = discovered_cards(g.state, 1)[0].result.choice.id
        self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.REWIND)
        g = portable(self, g)
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, ('retry',)))
        self.assertEqual(discovered_cards(g.state, 1), ())
        self.assertFalse(discovered_this_turn(g.state, 1)); g = portable(self, g)
        choose(g, B)
        row, = discovered_cards(g.state, 1)
        self.assertGreater(row.result.choice.id, first)
        self.assertEqual(row.result.selected[0].card_id, B)
        self.assertEqual(sum(e.kind == PUBLICATION for e in g.events), 2)
        portable(self, g)

    def test_same_turn_for_second_player_and_next_global_turn_are_separate(self):
        g = game((DISC,), pid=2); play(g, DISC); choose(g)
        self.assertTrue(discovered_this_turn(g.state, 2))
        self.assertFalse(discovered_this_turn(g.state, 1))
        g.apply(EndTurn(2))
        self.assertFalse(discovered_this_turn(g.state, 2))
        self.assertEqual(len(discovered_cards(g.state, 2)), 1)
        portable(self, g)

    def test_rehashed_record_turn_choice_result_and_missing_receipt_are_rejected(self):
        g = game(); play(g, DISC); choose(g)
        original = g.snapshot()
        def mutate_turn(s): s['state']['card_discovery_history'][0]['turn'] += 1
        def mutate_result(s): s['state']['card_discovery_history'][0]['result']['selected_ids'] = ['not-offered']
        def remove_record(s): s['state']['card_discovery_history'] = []
        def mutate_choice(s): s['state']['card_discovery_history'][0]['result']['choice']['purpose'] = 'effect'
        for mutate in (mutate_turn, mutate_result, remove_record, mutate_choice):
            saved = deepcopy(original); mutate(saved)
            with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(saved), registry('all', 'reader'))

    def test_receipts_and_original_hidden_offers_never_enter_player_projection(self):
        g = game(); play(g, DISC)
        self.assertEqual(g.observe(2)['pending_choice'], {'player_id': 1})
        self.assertEqual(g.observe(1)['pending_choice']['purpose'], 'pool_discovery')
        choose(g)
        for pid in (1, 2):
            text = json.dumps((g.observe(pid), g.player_events(pid)))
            for private in ('card_discovery_history', PUBLICATION, 'publication_event', 'receipt_hash'):
                self.assertNotIn(private, text)
        portable(self, g)
