"""Actual creation/movement outputs bind physical cards across acquisition work."""
from dataclasses import dataclass
from functools import lru_cache
import json
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, PlayCard,
    PlayerSetup, Rarity, Registry, Scenario, SelectChoice, Zone)
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.costs import capture_cost_input, capture_quote_fact
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Effect, InvokeBehavior, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CostSpec, TriggerSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.zones import (AddToDeck, CardReference, CopyCard, MoveCard, ModifyStoredCost,
    create_deck_card, copy_physical_card, move_physical_card, reference_entity)

P = 'k172.'
HERO, TOKEN, WATCH = (P+n for n in ('hero', 'token', 'watch'))
MODES = ('create', 'move', 'copy', 'burn', 'stale', 'same_hand', 'plain_deck', 'plain_move', 'draw', 'bad')
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())


@dataclass(frozen=True)
class AcceptResult(Effect):
    player_id: int
    source_id: int
    entity_id: int | None
    zone: Zone | None
    card: CardReference | None

    def __post_init__(self):
        if self.player_id not in (1, 2): raise ValueError('Actual delivery actor required')
        if (self.entity_id is None) != (self.zone is None): raise ValueError('Absent result has no physical identity')
        if self.card is not None:
            self.card.__post_init__()
            if (self.card.entity_id, self.card.zone) != (self.entity_id, self.zone):
                raise ValueError('Bound result changed its original physical body')
        elif self.zone not in (None, Zone.GRAVEYARD): raise ValueError('A live output requires its reference')


@dataclass(frozen=True)
class BindMaterialization(Effect):
    operation: AddToDeck | MoveCard | CopyCard

    def __post_init__(self):
        if type(self.operation) not in (AddToDeck, MoveCard, CopyCard): raise ValueError('Finite original materialization required')
        self.operation.__post_init__()


def mechanics():
    def bind(r, effect):
        op = effect.operation
        helper = create_deck_card if type(op) is AddToDeck else copy_physical_card if type(op) is CopyCard else move_physical_card
        entity = helper(r, op)
        if entity is not None and r.state.entities[entity.id] is not entity:
            raise ValueError('Materialization returned a synthetic entity')
        ref = None if entity is None or entity.zone == Zone.GRAVEYARD else CardReference.capture(entity)
        result = AcceptResult(op.player_id, op.source_id, None if entity is None else entity.id,
            None if entity is None else entity.zone, ref)
        return (RequestChoice(op.player_id, (ChoiceOption('accept', 'Use original output', (result,)),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', op.source_id, op.player_id),))), op.source_id),)
    def accept(r, effect):
        return (ModifyStoredCost(effect.card, CostSpec(delta=-1), effect.source_id),) if effect.card is not None else ()
    return default_mechanics().register(BindMaterialization, bind).register(AcceptResult, accept)


@lru_cache(maxsize=None)
def registry(role='writer'):
    if role not in ('writer', 'reader'): raise ValueError('Independent immutable registry role')
    r = Registry('k172-original-materialization')
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=30, metadata=replace_meta(CardClass.MAGE)))
    r.register_card(CardDefinition(TOKEN, TOKEN, CardType.MINION, cost=4, attack=2, health=3, metadata=META))
    def fail(c): raise ResolutionError('Fixture result failure')
    r.register_behavior(P+'fail', fail)
    for mode in MODES:
        def body(c, mode=mode):
            if mode in ('create', 'plain_deck', 'bad'):
                op = AddToDeck(c.player_id, HERO if mode == 'bad' else TOKEN, 'random', c.source_id,
                    cost=CostSpec(delta=-1), minion_grant=CreatedMinionGrant(attack=1, health=2) if mode != 'bad' else None)
                return (op,) if mode == 'plain_deck' else (BindMaterialization(op),)
            zone = Zone.HAND if mode == 'same_hand' else Zone.DECK
            ids = c.state.players[c.player_id].hand if zone == Zone.HAND else c.state.players[c.player_id].deck
            original = next(c.state.entities[i] for i in reversed(ids) if c.state.entities[i].card_id == TOKEN)
            ref = CardReference.capture(original)
            if mode == 'copy':
                return (ModifyStoredCost(ref, CostSpec(delta=-1), c.source_id),
                    BindMaterialization(CopyCard(ref, c.player_id, source_id=c.source_id)),)
            op = MoveCard(ref, c.player_id, Zone.HAND, draw=mode == 'draw', source_id=c.source_id)
            if mode in ('plain_move', 'draw'): return (op,)
            if mode == 'burn': return (AddToHand(c.player_id, TOKEN, c.source_id), BindMaterialization(op))
            if mode == 'stale':
                return (op, BindMaterialization(MoveCard(ref, c.player_id, Zone.DECK, position='top', source_id=c.source_id)))
            return (BindMaterialization(op),)
        r.register_behavior(P+mode, body)
        r.register_card(CardDefinition(P+mode, mode, CardType.SPELL, on_play=P+mode, metadata=META))
    def duplicate(c):
        if (c.event.player_id == c.player_id and c.event.source_id is not None and
                c.state.entities[c.event.source_id].card_id in tuple(P+x for x in MODES)):
            return (AddToDeck(c.player_id, TOKEN, 'top', c.source_id),)
        return ()
    r.register_behavior(P+'duplicate', duplicate)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=3, metadata=META,
        triggers=(TriggerSpec('card_added_to_deck', P+'duplicate'), TriggerSpec('card_added_to_hand', P+'duplicate'))))
    r.validate(); r.freeze(); return r


def replace_meta(cls):
    from dataclasses import replace
    return replace(META, classes=(cls,))


def game(mode, *, pid=1, watch=False):
    hand = (P+mode, TOKEN) if mode == 'same_hand' else (P+mode,)
    setup = tuple(PlayerSetup(HERO, hand=hand if p == pid else (), deck=(TOKEN, TOKEN),
        board=(WATCH,) if p == pid and watch else (), hand_cap=1 if mode == 'burn' else None,
        mana=10, max_mana=10) for p in (1, 2))
    return Game.from_scenario(Scenario(setup, active_player=pid, seed=172), registry(), mechanics=mechanics())


def play(g, mode):
    pid = g.state.active_player
    eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == P+mode)
    g.apply(PlayCard(pid, eid))


def result(g): return g._frame.options[0].effects[0]


def choose(g, option='accept'):
    q = g.state.pending_choice
    g.apply(SelectChoice(q.player_id, q.id, (option,)))


def amount(g, entity): return capture_quote_fact(g.state, g.registry, capture_cost_input(entity)).amount


def portable(test, g):
    reader = registry('reader') if g.registry is not registry('reader') else registry('writer')
    test.assertIsNot(reader, g.registry)
    saved = json.loads(json.dumps(g.snapshot()))
    other = Game.from_snapshot(saved, reader, mechanics=mechanics())
    test.assertEqual(other.snapshot(), saved)
    test.assertEqual(g.clone().snapshot(), saved)
    test.assertEqual(replay(build_replay(g), reader, mechanics=mechanics()).snapshot(), saved)
    return other


class MaterializationResultTests(unittest.TestCase):
    def test_created_deck_result_keeps_original_stats_cost_and_identity_after_same_face_reaction(self):
        g = game('create', watch=True); play(g, 'create'); bound = result(g)
        original = g.state.entities[bound.entity_id]
        self.assertEqual((original.zone, original.attack, original.health, amount(g, original)), (Zone.DECK, 3, 5, 3))
        self.assertEqual(len(g.state.players[1].deck), 4)
        self.assertNotEqual(bound.entity_id, g.state.players[1].deck[0])
        g = portable(self, g); choose(g)
        self.assertEqual(amount(g, g.state.entities[bound.entity_id]), 2)
        self.assertEqual(sorted(amount(g, g.state.entities[i]) for i in g.state.players[1].deck), [2, 4, 4, 4])
        portable(self, g)

    def test_physical_move_returns_same_entity_new_residence_without_creating_a_copy(self):
        g = game('move'); before = g.state.entities[g.state.players[1].deck[-1]]
        old_ref = CardReference.capture(before); count = len(g.state.entities)
        play(g, 'move'); bound = result(g)
        self.assertEqual((bound.entity_id, bound.zone, bound.card.zone_epoch), (before.id, Zone.HAND, old_ref.zone_epoch+1))
        self.assertEqual(len(g.state.entities), count)
        self.assertEqual(len(g.state.hand_entries), 2)
        g = portable(self, g); choose(g)
        self.assertEqual(amount(g, g.state.entities[before.id]), 3)

    def test_existing_copy_result_is_fresh_and_keeps_current_material_without_changing_original(self):
        g = game('copy', watch=True); original = g.state.players[1].deck[-1]
        play(g, 'copy'); bound = result(g)
        self.assertNotEqual(bound.entity_id, original)
        self.assertEqual(g.state.entities[bound.entity_id].origin_entity_id, original)
        self.assertEqual((amount(g, g.state.entities[original]), amount(g, g.state.entities[bound.entity_id])), (3, 3))
        choose(g)
        self.assertEqual((amount(g, g.state.entities[original]), amount(g, g.state.entities[bound.entity_id])), (3, 2))
        portable(self, g)

    def test_overflow_returns_actual_burned_body_without_fabricating_hand_recipient(self):
        g = game('burn'); original = g.state.players[1].deck[-1]
        play(g, 'burn'); bound = result(g)
        self.assertEqual((bound.entity_id, bound.zone, bound.card), (original, Zone.GRAVEYARD, None))
        self.assertTrue(any(e.kind == 'card_burned' and e.target_id == original for e in g.events))
        g = portable(self, g); choose(g)
        self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD)

    def test_stale_reference_and_already_held_card_return_no_movement_result(self):
        for mode in ('stale', 'same_hand'):
            with self.subTest(mode=mode):
                g = game(mode); play(g, mode); bound = result(g)
                self.assertEqual((bound.entity_id, bound.zone, bound.card), (None, None, None))
                g = portable(self, g); choose(g)
                self.assertEqual([amount(g, g.state.entities[i]) for i in g.state.players[1].hand], [4])

    def test_registered_deck_move_and_draw_handlers_keep_interpreter_work_and_original_draw_history(self):
        for mode in ('plain_deck', 'plain_move', 'draw'):
            with self.subTest(mode=mode):
                g = game(mode); original = g.state.players[1].deck[-1]; play(g, mode)
                self.assertIsNone(g.state.pending_choice)
                if mode == 'draw':
                    self.assertEqual(g.state.draw_history[-1].entity_id, original)
                    self.assertTrue(g.state.draw_history[-1].completed)
                if mode != 'plain_deck': self.assertEqual(g.state.players[1].hand, [original])
                portable(self, g)

    def test_failed_bound_selection_preserves_original_result_events_rng_and_pending_boundary(self):
        g = game('create', watch=True); play(g, 'create'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved); portable(self, g)

    def test_unsupported_deck_face_rolls_back_before_creation_and_rng(self):
        g = game('bad'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): play(g, 'bad')
        self.assertEqual(g.snapshot(), saved)

    def test_other_actor_and_private_output_are_preserved_without_player_reference_leaks(self):
        g = game('move', pid=2); play(g, 'move'); bound = result(g)
        self.assertEqual((bound.player_id, bound.card.player_id), (2, 2))
        for pid in (1, 2):
            visible = json.dumps((g.observe(pid), g.player_events(pid)))
            for hidden in ('AcceptResult', 'BindMaterialization', 'zone_epoch', 'entity_id'):
                self.assertNotIn(hidden, visible)
        portable(self, g)
