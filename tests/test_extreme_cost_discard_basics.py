"""Current-price extrema reuse physical discard, quotes and continuations."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from dataclasses import fields
import json
from pathlib import Path
import random
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostAuraSpec, CostSpec,
    Game, Keyword, PaymentType, PlayCard, PlayerSetup, Rarity, Registry,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone,
    discarded_cards)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddCostModifier, ChoiceOption, InvokeBehavior,
    ModifyCost, RequestChoice)
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import DiscardMatching, DrawMatching, DestroyDeckMatching
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

PATH = Path(__file__).resolve().parents[1] / 'data/support/extreme-cost-discard-basics.json'
PIN = 'd288c10a149298082c211180ac4081a59c0b7aa10933dfee37d9263ead0bebb4'


def evidence():
    data = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != PIN:
        raise ValueError('Extrema discard evidence changed')
    for row in data['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Extrema discard raw row changed')
    return {row['id']: row['data'] for row in data['records']}


def registry():
    r = Registry('isolated-extreme-cost-discard-basics-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=60, metadata=metadata()))
    for cid, cost in (('zero', 0), ('low', 1), ('mid', 5), ('high', 9), ('same', 9), ('huge', 99)):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=cost, metadata=metadata()))
    r.register_card(CardDefinition('beast', 'Beast', CardType.MINION, cost=7,
        attack=1, health=5, metadata=metadata(tribes=('beast',))))
    r.register_card(CardDefinition('aura', 'Price probe', CardType.MINION, health=5,
        cost_auras=(CostAuraSpec(CostSpec(delta=-9, card_ids=('high',))),), metadata=metadata()))

    def match(c, selection, *, count=1, player=None, query=PoolQuery(), reveal=True):
        return DiscardMatching(c.player_id if player is None else player, query,
            count, selection, c.source_id, reveal)

    def physical(c, cid):
        return next(i for i in c.state.players[c.player_id].hand
                    if c.state.entities[i].card_id == cid)

    def fault(c):
        raise RuntimeError('Deliberate extrema discard fault')

    r.register_behavior('fault', fault)
    scripts = {
        'highest': lambda c: (match(c, 'highest_cost'),),
        'lowest': lambda c: (match(c, 'lowest_cost'),),
        'highest2': lambda c: (match(c, 'highest_cost', count=2),),
        'lowest2': lambda c: (match(c, 'lowest_cost', count=2),),
        'many': lambda c: (match(c, 'highest_cost', count=6),),
        'none': lambda c: (match(c, 'highest_cost', count=0),),
        'first': lambda c: (match(c, 'first'),),
        'random': lambda c: (match(c, 'random'),),
        'private': lambda c: (match(c, 'highest_cost', reveal=False),),
        'enemy': lambda c: (match(c, 'highest_cost', player=2),),
        'lower.high': lambda c: (ModifyCost(physical(c, 'high'), CostSpec(set_to=0), c.source_id),
                                match(c, 'highest_cost')),
        'raise.low': lambda c: (ModifyCost(physical(c, 'low'), CostSpec(set_to=20), c.source_id),
                               match(c, 'lowest_cost')),
        'clamp': lambda c: (ModifyCost(physical(c, 'high'), CostSpec(delta=-50), c.source_id),
                           match(c, 'lowest_cost')),
        'filter': lambda c: (ModifyCost(physical(c, 'high'), CostSpec(set_to=0), c.source_id),
                            ModifyCost(physical(c, 'mid'), CostSpec(set_to=30), c.source_id),
                            match(c, 'highest_cost', query=PoolQuery(min_cost=6))),
        'kinds': lambda c: (match(c, 'highest_cost', query=PoolQuery(kinds=(CardType.SPELL,))),),
        'modifier': lambda c: (AddCostModifier(c.player_id,
            CostSpec(set_to=0, card_ids=('high',)), uses_remaining=2, source_id=c.source_id),
            match(c, 'highest_cost')),
        'health': lambda c: (AddCostModifier(c.player_id,
            CostSpec(payment=PaymentType.HEALTH, card_ids=('high',)),
            uses_remaining=2, source_id=c.source_id), match(c, 'highest_cost')),
        'fault.highest': lambda c: (match(c, 'highest_cost'),
            InvokeBehavior('fault', c.source_id, c.player_id)),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata()))

    raw = evidence()
    for cid, selection, keyword, tribes in (
            ('BT_301', 'highest_cost', Keyword.RUSH, ('demon',)),
            ('TRL_551', 'lowest_cost', Keyword.TAUNT, ())):
        behavior = 'native.' + cid
        r.register_behavior(behavior, lambda c, selection=selection: (match(c, selection),))
        row = raw[cid]
        r.register_card(CardDefinition(cid, row['name'], CardType.MINION, cost=row['cost'],
            attack=row['attack'], health=row['health'], keywords=(keyword,), battlecry=behavior,
            metadata=metadata(CardClass.WARLOCK, rarity=Rarity.COMMON, tribes=tribes)))

    def wait(c, changed_card=None, amount=None):
        if c.event.player_id != c.player_id or len(discarded_cards(c.state, c.player_id)) != 1:
            return ()
        effects = () if changed_card is None else (
            ModifyCost(physical(c, changed_card), CostSpec(set_to=amount), c.source_id),)
        options = (ChoiceOption('ok', 'Continue'), ChoiceOption('fault', 'Fail',
            (InvokeBehavior('fault', c.source_id, c.player_id),)))
        return (*effects, RequestChoice(c.player_id, options, c.source_id))

    for cid, changed_card, amount in (
            ('wait', None, None), ('raise.remaining', 'low', 20), ('lower.remaining', 'high', 0)):
        behavior = 'watch.' + cid
        r.register_behavior(behavior, lambda c, cid=changed_card, amount=amount: wait(c, cid, amount))
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=5,
            triggers=(TriggerSpec('card_discarded', behavior),), metadata=metadata()))
    return r


class ExtremeCostDiscardTests(unittest.TestCase):
    def game(self, hand=('highest', 'low', 'mid', 'high'), *, board=(), enemy_hand=(), seed=54):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, mana=10, max_mana=10),
            PlayerSetup('hero', hand=enemy_hand, mana=10, max_mana=10),
        ), seed=seed), registry())

    def play(self, g, cid, player=1):
        eid = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(player, eid))
        return eid

    def rows(self, g, player=1):
        return discarded_cards(g.state, player)

    def ids(self, g, cid, player=1):
        return [i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid]

    def choose(self, g, name='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (name,)))

    def portable(self, g):
        s = json.loads(json.dumps(g.snapshot()))
        h = Game.from_snapshot(s, registry())
        self.assertEqual(h.snapshot(), s)
        self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), s)
        return h

    def test_complete_raw_pin_and_exact_two_native_definitions(self):
        raw = evidence()
        originals = {r['id']: r for r in json.loads(
            (PATH.parents[1] / 'extracted/cards.json').read_text(encoding='utf-8'))}
        r = registry()
        for cid, values in (('BT_301', (4, 5, 5, Keyword.RUSH, ('demon',))),
                            ('TRL_551', (3, 2, 6, Keyword.TAUNT, ()))):
            self.assertEqual(raw[cid], originals[cid])
            card = r.card(cid)
            self.assertEqual((card.cost, card.attack, card.health, card.keywords[0],
                              card.metadata.tribes), values)
            self.assertEqual((card.metadata.classes, card.metadata.rarity),
                             ((CardClass.WARLOCK,), Rarity.COMMON))
            self.assertEqual(card.battlecry, 'native.' + cid)
        self.assertNotIn('UNG_833', r.cards)

    def test_native_highest_discards_one_card_after_source_leaves_hand(self):
        g = self.game(('BT_301', 'low', 'high'))
        target = self.ids(g, 'high')[0]
        source = self.play(g, 'BT_301')
        self.assertEqual([r.entity_id for r in self.rows(g)], [target])
        self.assertEqual(self.rows(g)[0].source.entity_id, source)
        self.assertEqual(g.state.entities[source].zone, Zone.BOARD)
        self.assertEqual(g.state.players[1].mana, 6)
        self.portable(g)

    def test_native_lowest_discards_one_card_after_source_leaves_hand(self):
        g = self.game(('TRL_551', 'low', 'mid', 'high'))
        target = self.ids(g, 'low')[0]
        source = self.play(g, 'TRL_551')
        self.assertEqual([r.entity_id for r in self.rows(g)], [target])
        self.assertEqual(self.rows(g)[0].source.entity_id, source)
        self.assertEqual(g.state.players[1].mana, 7)
        self.portable(g)

    def test_current_local_reduction_changes_highest_candidate(self):
        g = self.game(('lower.high', 'high', 'mid'))
        self.play(g, 'lower.high')
        self.assertEqual([r.card_id for r in self.rows(g)], ['mid'])
        self.assertEqual(g.quote_cost(self.ids(g, 'high')[0]).amount, 0)

    def test_current_local_increase_changes_lowest_candidate(self):
        g = self.game(('raise.low', 'low', 'mid', 'high'))
        self.play(g, 'raise.low')
        self.assertEqual([r.card_id for r in self.rows(g)], ['mid'])
        self.assertEqual(g.quote_cost(self.ids(g, 'low')[0]).amount, 20)

    def test_cost_reduction_clamps_to_zero_before_comparison(self):
        g = self.game(('clamp', 'high', 'low'))
        self.play(g, 'clamp')
        self.assertEqual([r.card_id for r in self.rows(g)], ['high'])
        self.assertEqual(g.state.entities[self.rows(g)[0].entity_id].cost, 0)

    def test_printed_cost_filter_precedes_current_cost_extremum(self):
        g = self.game(('filter', 'high', 'mid'))
        self.play(g, 'filter')
        self.assertEqual([r.card_id for r in self.rows(g)], ['high'])
        self.assertEqual(g.quote_cost(self.ids(g, 'mid')[0]).amount, 30)

    def test_kind_filter_keeps_only_eligible_physical_cards(self):
        g = self.game(('kinds', 'low', 'beast'))
        self.play(g, 'kinds')
        self.assertEqual([r.card_id for r in self.rows(g)], ['low'])
        self.assertEqual(len(self.ids(g, 'beast')), 1)

    def test_current_live_cost_aura_changes_extremum(self):
        g = self.game(board=('aura',))
        self.assertEqual(g.quote_cost(self.ids(g, 'high')[0]).amount, 0)
        self.play(g, 'highest')
        self.assertEqual([r.card_id for r in self.rows(g)], ['mid'])
        self.assertEqual(len(g.state.players[1].board), 1)

    def test_player_modifier_quote_does_not_consume_uses(self):
        g = self.game(('modifier', 'high', 'mid'))
        self.play(g, 'modifier')
        self.assertEqual([r.card_id for r in self.rows(g)], ['mid'])
        self.assertEqual([m.uses_remaining for m in g.state.players[1].cost_modifiers], [2])
        self.assertEqual(g.state.players[1].mana, 10)
        self.assertEqual(len(g.state.cost_use_history), 1)
        self.portable(g)

    def test_numeric_comparison_ignores_payment_account_and_spends_nothing(self):
        g = self.game(('health', 'high', 'mid'))
        self.play(g, 'health')
        self.assertEqual([r.card_id for r in self.rows(g)], ['high'])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 60)
        self.assertEqual(g.state.players[1].mana, 10)
        self.assertEqual([m.uses_remaining for m in g.state.players[1].cost_modifiers], [2])

    def test_unaffordable_card_remains_highest_discard_candidate(self):
        g = self.game(('highest', 'huge', 'high'))
        self.play(g, 'highest')
        self.assertEqual([r.card_id for r in self.rows(g)], ['huge'])
        self.assertEqual(g.state.players[1].mana, 10)

    def test_highest_ties_use_one_choice_over_all_physical_duplicates(self):
        g = self.game(('highest', 'high', 'same', 'high', 'low'))
        ties = [i for i in g.state.players[1].hand if g.state.entities[i].cost == 9]
        rng = random.Random()
        rng.setstate(g._rng.getstate())
        expected = rng.choice(ties)
        self.play(g, 'highest')
        self.assertEqual([r.entity_id for r in self.rows(g)], [expected])
        self.assertEqual(g._rng.getstate(), rng.getstate())
        self.assertEqual(len(ties), 3)
        self.portable(g)

    def test_lowest_ties_preserve_hand_order_and_one_weight_per_physical_card(self):
        g = self.game(('lowest', 'low', 'high', 'low', 'low'))
        ties = self.ids(g, 'low')
        rng = random.Random()
        rng.setstate(g._rng.getstate())
        expected = rng.choice(ties)
        self.play(g, 'lowest')
        self.assertEqual(self.rows(g)[0].entity_id, expected)
        self.assertEqual(g._rng.getstate(), rng.getstate())

    def test_unique_highest_among_multiple_candidates_does_not_use_rng(self):
        g = self.game()
        before = g._rng.getstate()
        self.play(g, 'highest')
        self.assertEqual(g._rng.getstate(), before)
        self.assertEqual(self.rows(g)[0].card_id, 'high')

    def test_unique_lowest_among_multiple_candidates_does_not_use_rng(self):
        g = self.game(('lowest', 'mid', 'low', 'high'))
        before = g._rng.getstate()
        self.play(g, 'lowest')
        self.assertEqual(g._rng.getstate(), before)
        self.assertEqual(self.rows(g)[0].card_id, 'low')

    def test_single_candidate_extrema_do_not_use_rng(self):
        for cid in ('highest', 'lowest'):
            with self.subTest(selection=cid):
                g = self.game((cid, 'low'))
                before = g._rng.getstate()
                self.play(g, cid)
                self.assertEqual(g._rng.getstate(), before)
                self.assertEqual(len(self.rows(g)), 1)

    def test_empty_hand_extrema_do_not_use_rng_or_create_discard(self):
        for cid in ('highest', 'lowest'):
            with self.subTest(selection=cid):
                g = self.game((cid,))
                before = g._rng.getstate()
                self.play(g, cid)
                self.assertEqual(g._rng.getstate(), before)
                self.assertEqual(self.rows(g), ())

    def test_count_zero_keeps_all_candidates_and_rng(self):
        g = self.game(('none', 'low', 'high'))
        before = g._rng.getstate()
        self.play(g, 'none')
        self.assertEqual(self.rows(g), ())
        self.assertEqual(g._rng.getstate(), before)
        self.assertEqual(len(g.state.players[1].hand), 2)

    def test_original_random_singleton_still_performs_its_existing_choice(self):
        g = self.game(('random', 'low'))
        before = g._rng.getstate()
        rng = random.Random()
        rng.setstate(before)
        rng.choice(self.ids(g, 'low'))
        self.play(g, 'random')
        self.assertNotEqual(g._rng.getstate(), before)
        self.assertEqual(g._rng.getstate(), rng.getstate())

    def test_original_first_selection_still_uses_hand_order(self):
        g = self.game(('first', 'low', 'high'))
        before = g._rng.getstate()
        self.play(g, 'first')
        self.assertEqual(self.rows(g)[0].card_id, 'low')
        self.assertEqual(g._rng.getstate(), before)

    def test_original_count_loop_stops_when_current_hand_is_empty(self):
        g = self.game(('many', 'low', 'high'))
        self.play(g, 'many')
        self.assertEqual([r.card_id for r in self.rows(g)], ['high', 'low'])
        self.assertEqual(g.state.players[1].hand, [])

    def test_highest_count_loop_requotes_after_first_discard_reaction(self):
        g = self.game(('highest2', 'low', 'mid', 'high'), board=('raise.remaining',))
        self.play(g, 'highest2')
        self.assertEqual([r.card_id for r in self.rows(g)], ['high'])
        self.assertEqual(g.quote_cost(self.ids(g, 'low')[0]).amount, 20)
        self.assertIsNotNone(g.state.pending_choice)
        self.choose(g)
        self.assertEqual([r.card_id for r in self.rows(g)], ['high', 'low'])

    def test_lowest_count_loop_requotes_after_first_discard_reaction(self):
        g = self.game(('lowest2', 'low', 'mid', 'high'), board=('lower.remaining',))
        self.play(g, 'lowest2')
        self.assertEqual([r.card_id for r in self.rows(g)], ['low'])
        self.choose(g)
        self.assertEqual([r.card_id for r in self.rows(g)], ['low', 'high'])

    def test_waiting_count_continuation_restores_clones_and_replays(self):
        g = self.game(('highest2', 'high', 'same', 'mid'), board=('wait',))
        self.play(g, 'highest2')
        work = next(w for w in (*g._frame.prefix, *g._frame.continuation)
                    if type(w) is DiscardMatching and w.count == 1)
        self.assertEqual(work.selection, 'highest_cost')
        h = self.portable(g)
        self.choose(g)
        self.choose(h)
        self.assertEqual(g.snapshot(), h.snapshot())
        self.assertEqual(len(self.rows(g)), 2)
        self.portable(g)

    def test_failed_choice_rolls_back_waiting_frame_history_and_rng(self):
        g = self.game(('highest2', 'high', 'same', 'mid'), board=('wait',))
        self.play(g, 'highest2')
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)
        self.choose(g)
        self.assertEqual(len(self.rows(g)), 2)

    def test_late_action_failure_rolls_back_extremum_rng_and_discard(self):
        g = self.game(('fault.highest', 'high', 'same', 'mid'))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'fault.highest')
        self.assertEqual(g.snapshot(), before)

    def test_opponent_hand_selection_uses_affected_player_and_physical_source(self):
        g = self.game(('enemy', 'huge'), enemy_hand=('low', 'high'))
        target = self.ids(g, 'high', 2)[0]
        source = self.play(g, 'enemy')
        row = self.rows(g, 2)[0]
        self.assertEqual((row.entity_id, row.player_id, row.card.owner, row.card.controller),
                         (target, 2, 2, 2))
        self.assertEqual(row.source.entity_id, source)
        self.assertEqual(len(self.ids(g, 'huge')), 1)
        self.portable(g)

    def test_selection_is_not_an_extra_play_cast_draw_or_death(self):
        g = self.game()
        self.play(g, 'highest')
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual(len(g.state.cast_history), 1)
        self.assertEqual(g.state.draw_history, [])
        self.assertEqual(g.state.death_history, [])
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(sum(e.kind == 'card_discarded' for e in g.events), 1)

    def test_extrema_typed_codec_reuses_the_original_effect_shape(self):
        g = self.game()
        codec = FrameCodec(g.mechanics, g.registry)
        for selection in ('highest_cost', 'lowest_cost'):
            work = DiscardMatching(1, count=2, selection=selection)
            self.assertEqual(codec.decode(codec.encode(work)), work)
        self.assertEqual([f.name for f in fields(DiscardMatching)],
            ['player_id', 'query', 'count', 'selection', 'source_id', 'reveal'])
        bad = codec.encode(DiscardMatching(1, selection='highest_cost'))
        bad['fields']['selection'] = 'invented'
        with self.assertRaises(ValueError):
            codec.decode(bad)

    def test_unknown_selector_and_non_discard_extrema_are_rejected(self):
        for value in ('invented', 'Highest_cost', None, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                DiscardMatching(1, selection=value)
        for selection in ('highest_cost', 'lowest_cost'):
            with self.subTest(selection=selection):
                # Highest stored-DECK cost is now an explicit draw policy;
                # discard still compares a different, current held-card quote.
                if selection == 'highest_cost':
                    self.assertEqual(DrawMatching(1, PoolQuery(), 'skip', selection=selection).selection,selection)
                else:
                    with self.assertRaises(ValueError):
                        DrawMatching(1, PoolQuery(), 'skip', selection=selection)
                with self.assertRaises(ValueError):
                    DestroyDeckMatching(1, selection=selection)
        for values in ({'count': True}, {'count': -1}, {'reveal': 1}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                DiscardMatching(1, selection='highest_cost', **values)

    def test_current_schema_accepts_and_old_or_future_schemas_reject(self):
        g = self.game()
        self.assertEqual(g.snapshot()['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        for version in (1, 197, 217, True):
            s = g.snapshot()
            s['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(SnapshotError):
                Game.from_snapshot(s, registry())

    def test_player_views_do_not_expose_price_inputs_candidates_or_history(self):
        g = self.game()
        before = g.snapshot()
        for player in (1, 2):
            port = g.for_player(player)
            payload = json.dumps((port.observe(), port.legal_actions()))
            for key in ('discard_history', 'quote_input', 'consumable_ids',
                        'zone_epoch', 'hand_entry_id', 'resolution_frame'):
                self.assertNotIn(key, payload)
        self.assertEqual(g.snapshot(), before)
        self.play(g, 'highest')
        view = json.dumps(g.observe(2))
        self.assertIn('"card_id": "high"', view)
        self.assertNotIn('discard_history', view)

    def test_private_discard_does_not_reveal_selected_face_to_opponent(self):
        g = self.game(('private', 'high', 'low'))
        self.play(g, 'private')
        self.assertFalse(self.rows(g)[0].reveal)
        self.assertNotIn('"card_id": "high"', json.dumps(g.observe(2)))
        self.portable(g)
