"""Actual capacity, one frozen generated batch and native local Health prices."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import random
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.native_pool_hand_fill_cards import OBLIVION, POOL_ID, UNDEAD, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, IllegalAction, PaymentType, PlayCard, PlayerSetup, Rarity, Ruleset,
    Scenario, SelectChoice, SnapshotError, Zone)
from hs_sim.engine.effects import AddToHand, ChoiceOption, CostSpec, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError, ResolutionLimitExceeded
from hs_sim.engine.hand_capacity import SetHandCapacity
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import (FillHandFromPool, GenerateFromPool, GenerationContext,
    PoolCard, PoolDefinition, PoolMember, PoolQuery)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, MoveCard

P = 'k144.'
UND, ALL, BEAST, FILLER, UNKNOWN = (P+n for n in ('undead', 'all', 'beast', 'filler', 'unknown'))
CONTEXT = GenerationContext('k144-complete-explicit-pool', 'experimental')
MEMBERS = (UND, ALL, BEAST)


def registry(mode=None, members=MEMBERS):
    r = build_registry()
    for cid, tribes, collectible in ((UND, ('undead',), True), (ALL, ('all',), True),
            (BEAST, ('beast',), True), (FILLER, (), False)):
        c = CardDefinition(cid, cid, CardType.MINION, cost=2, attack=2, health=3,
            metadata=CardMetadata(collectible, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=tribes))
        r.register_card(c); r.register_pool_card(PoolCard.from_definition(c))
    r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 2,
        CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=('undead',)),
        battlecry=False, deathrattle=False, choose_one=False))
    r.register_pool(PoolDefinition(POOL_ID, 'k144-explicit-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid, 3 if cid == UND else 1) for cid in members), complete=True))

    def request(c):
        return FillHandFromPool(GenerateFromPool(c.player_id, POOL_ID, UNDEAD,
            source_id=c.source_id))

    def defer(c):
        fill = request(c)
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Fill', (fill,)),
            ChoiceOption('small', 'Change capacity then fill', (SetHandCapacity(c.player_id, 1), fill))), c.source_id),)

    def fail(c):
        raise ResolutionError('K144 deliberate acquisition failure')

    bodies = {'full': lambda c: (SetHandCapacity(c.player_id, 1),
        AddToHand(c.player_id, FILLER, c.source_id), request(c)), 'defer': defer, 'fail': fail}
    for name, body in bodies.items():
        r.register_behavior(P+name, body)
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name))
    if mode:
        def eligible(c):
            source = c.state.entities.get(c.event.source_id)
            return source is not None and source.card_id == OBLIVION and c.event.player_id == c.player_id

        def watch(c):
            if mode == 'fail':
                return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
            ref = CardReference.capture(c.state.entities[c.event.target_id])
            return (RequestChoice(c.player_id, (
                ChoiceOption('ok', 'Continue'),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
                ChoiceOption('expand', 'Expand capacity', (SetHandCapacity(c.player_id, 7),)),
                ChoiceOption('shrink', 'Shrink capacity', (SetHandCapacity(c.player_id, 1),)),
                ChoiceOption('remove', 'Move original generated card',
                    (MoveCard(ref, c.player_id, Zone.DECK, position='bottom', source_id=c.source_id),)),
            ), c.source_id),)
        r.register_behavior(P+'watch', watch)
        r.register_trigger_condition(P+'eligible', eligible)
        r.register_card(CardDefinition(P+'watch', 'One actual acquisition', CardType.WEAPON,
            durability=4, limited_triggers=(LimitedTriggerSpec('card_created', P+'watch', P+'eligible'),)))
    r.validate()
    return r


@lru_cache(maxsize=None)
def shared_registry(mode, members):
    return registry(mode, members)


def wires(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from wires(child)
    elif isinstance(value, list):
        for child in value:
            yield from wires(child)


class NativePoolHandFillTests(unittest.TestCase):
    def game(self, hand=(OBLIVION,), *, limit=4, cap=None, mode=None, members=MEMBERS, actor=1):
        self.config = mode, members
        own = PlayerSetup('HERO_08', hand=hand, deck=(FILLER,)*8, mana=8, max_mana=10,
            hand_cap=cap, weapon_card_id=P+'watch' if mode else None)
        other = PlayerSetup('HERO_08', hand=(FILLER,), deck=(FILLER,)*8, mana=8, max_mana=10)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own),
            active_player=actor, seed=144, generation_context=CONTEXT),
            shared_registry(*self.config), Ruleset(max_hand=limit))

    def first(self, g, cid, actor=1):
        return next(i for i in g.state.players[actor].hand if g.state.entities[i].card_id == cid)

    def play(self, g, cid=OBLIVION, actor=1):
        source = self.first(g, cid, actor)
        g.apply(PlayCard(actor, source))
        return source

    def choose(self, g, option='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (option,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(*self.config))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(*self.config)).snapshot(), saved)
        for actor in (1, 2):
            public = json.dumps(g.for_player(actor).observe())+json.dumps(g.player_events(actor))
            for key in ('rng_state', 'resolution_frame', 'pool_id', 'request', 'source_json'):
                self.assertNotIn('"'+key+'"', public)
        return other

    def test_complete_original_source_two_primary_faces_and_real_eight_cost_spell(self):
        from tools.card_batch import check_face
        d = load_batch(); raw = d['cards'][0]['record']
        self.assertEqual(len(d['official_observations']), 2)
        for o in d['official_observations']:
            check_face(raw, o['face'], o['locale'])
        card = shared_registry(None, MEMBERS).card(OBLIVION)
        self.assertEqual((card.kind, card.cost, card.spell_school), (CardType.SPELL, 8, None))
        self.assertFalse(d['formal_pool_complete'] or d['cn_calibrated'])

    def test_actual_rules_capacity_paid_spell_and_complete_weighted_undead_all_query(self):
        g = self.game(); calls = []
        original = random.Random.randrange
        def spy(rng, *args, **kwargs):
            calls.append(args)
            return original(rng, *args, **kwargs)
        with patch.object(random.Random, 'randrange', spy):
            source = self.play(g)
        self.assertEqual(calls, [(4,)]*4)
        self.assertEqual(len(g.state.players[1].hand), 4)
        self.assertEqual(g.state.players[1].mana, 0)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertTrue(all(g.state.entities[i].card_id in (UND, ALL) for i in g.state.players[1].hand))
        self.assertEqual(len(g.state.players[2].hand), 1)
        self.portable(g)

    def test_player_override_and_already_held_cards_determine_actual_free_slots(self):
        for capacity in (2, 7):
            with self.subTest(capacity=capacity):
                g = self.game((OBLIVION, FILLER), cap=capacity)
                held = self.first(g, FILLER)
                source = self.play(g)
                self.assertEqual(len(g.state.players[1].hand), capacity)
                self.assertIn(held, g.state.players[1].hand)
                self.assertEqual(g.quote_cost(held).payment, PaymentType.MANA)
                self.assertEqual(sum(e.kind == 'card_created' and e.source_id == source for e in g.events), capacity-1)
                self.assertEqual(g.state.players[2].hand_cap, None)

    def test_only_new_physical_cards_pay_health_and_native_payment_works_without_mana(self):
        g = self.game((OBLIVION, UND), members=(UND,))
        old = self.first(g, UND)
        self.play(g)
        new = next(i for i in g.state.players[1].hand if i != old)
        self.assertEqual((g.quote_cost(old).payment, g.quote_cost(new).payment),
            (PaymentType.MANA, PaymentType.HEALTH))
        saved = g.snapshot()
        with self.assertRaises(IllegalAction):
            g.apply(PlayCard(1, old, position=0))
        self.assertEqual(g.snapshot(), saved)
        before = g.state.entities[g.state.players[1].hero_id].health
        g.apply(PlayCard(1, new, position=0))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, before-2)
        self.assertEqual(g.state.players[1].mana, 0)
        self.assertEqual(g.state.play_history[-1].payment, PaymentType.HEALTH)
        self.portable(g)

    def test_local_health_price_expires_at_original_turn_end(self):
        g = self.game(members=(UND,))
        self.play(g); eid = g.state.players[1].hand[0]
        self.assertEqual(g.quote_cost(eid).payment, PaymentType.HEALTH)
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(g.quote_cost(eid).payment, PaymentType.MANA)
        before = g.state.entities[g.state.players[1].hero_id].health
        g.apply(PlayCard(1, eid, position=0))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, before)
        self.assertEqual(g.state.players[1].mana, 8)

    def test_empty_pool_and_already_full_hand_consume_no_rng(self):
        for hand, members in (((OBLIVION,), (BEAST,)), ((P+'full',), MEMBERS)):
            with self.subTest(hand=hand):
                g = self.game(hand, members=members)
                rng = g.snapshot()['rng_state']
                self.play(g, hand[0])
                self.assertEqual(g.snapshot()['rng_state'], rng)
                self.assertEqual(len(g.state.players[1].hand), 0 if hand[0] == OBLIVION else 1)

    def test_unknown_eligible_content_rejects_before_rng_even_when_hand_is_full(self):
        for cid in (OBLIVION, P+'full'):
            with self.subTest(cid=cid):
                g = self.game((cid,), members=(UND, UNKNOWN)); saved = g.snapshot(); calls = []
                def spy(*args, **kwargs):
                    calls.append(args)
                    raise AssertionError('Unknown candidate reached RNG')
                with patch.object(random.Random, 'randrange', spy), self.assertRaises(ResolutionError):
                    self.play(g, cid)
                self.assertFalse(calls)
                self.assertEqual(g.snapshot(), saved)

    def test_actual_delivery_wait_restores_and_keeps_original_count_after_capacity_or_zone_changes(self):
        for option, held, burned in (('expand', 3, 0), ('shrink', 1, 2), ('remove', 2, 0)):
            with self.subTest(option=option):
                g = self.game(limit=3, mode='wait')
                source = self.play(g)
                self.assertEqual(len(g.state.players[1].hand), 1)
                self.portable(g); saved = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'deliberate'):
                    self.choose(g, 'bad')
                self.assertEqual(g.snapshot(), saved)
                self.choose(g, option)
                self.assertEqual(len(g.state.players[1].hand), held)
                self.assertEqual(sum(e.kind == 'card_created' and e.source_id == source for e in g.events), 3)
                self.assertEqual(sum(e.kind == 'card_burned' and e.source_id == source for e in g.events), burned)
                self.assertIsNone(g.state.pending_choice)
                self.portable(g)

    def test_new_typed_request_waits_and_captures_capacity_only_when_executed(self):
        g = self.game((P+'defer',))
        self.play(g, P+'defer'); self.portable(g)
        self.assertFalse(g.state.players[1].hand)
        self.choose(g, 'small')
        self.assertEqual(len(g.state.players[1].hand), 1)
        self.portable(g)

    def test_hand_fill_request_rejects_other_delivery_recipes_and_caller_quantities(self):
        q = GenerateFromPool(1, POOL_ID, UNDEAD, source_id=1)
        FillHandFromPool(q)
        for changes in (dict(count=2), dict(source_id=None), dict(destination='board'),
                dict(replacement=False), dict(query=PoolQuery(kinds=(CardType.SPELL,), collectible=True))):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                FillHandFromPool(replace(q, **changes))
        with self.assertRaises(ValueError):
            FillHandFromPool('untyped')

    def test_rehashed_typed_request_count_and_old_schema_are_rejected(self):
        g = self.game((P+'defer',)); self.play(g, P+'defer')
        saved = deepcopy(g.snapshot())
        changed = 0
        for row in wires(saved['resolution_frame']):
            if row.get('type', '').endswith('.FillHandFromPool'):
                row['fields']['request']['fields']['count'] = 2; changed += 1
        self.assertGreater(changed, 0)
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises((SnapshotError, ValueError)):
            Game.from_snapshot(saved, registry(*self.config))
        saved = g.snapshot(); saved['schema_version'] = 349
        with self.assertRaises((SnapshotError, ValueError)):
            Game.from_snapshot(saved, registry(*self.config))

    def test_acquisition_exception_rolls_back_actual_payment_rng_and_all_new_cards(self):
        g = self.game(mode='fail'); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.play(g)
        self.assertEqual(g.snapshot(), saved)

    def test_actual_other_player_receives_its_own_local_prices_and_capacity(self):
        g = self.game(actor=2, cap=6)
        source = self.play(g, actor=2)
        self.assertEqual((len(g.state.players[1].hand), len(g.state.players[2].hand)), (1, 6))
        self.assertTrue(all(g.quote_cost(i).payment == PaymentType.HEALTH for i in g.state.players[2].hand))
        self.assertTrue(all(e.player_id == 2 for e in g.events if e.kind == 'card_created' and e.source_id == source))
        self.portable(g)

    def test_large_effective_capacity_still_obeys_existing_resolution_budget(self):
        g = self.game(cap=1001); saved = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            self.play(g)
        self.assertEqual(g.snapshot(), saved)


if __name__ == '__main__':
    unittest.main()
