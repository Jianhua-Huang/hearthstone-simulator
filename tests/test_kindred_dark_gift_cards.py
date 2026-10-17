"""One real Raptor discovery keeps accepted Kindred cost through native Rewind."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import random
import re
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.kindred_dark_gift_cards import RAPTOR, IDENTITY, QUERY, POOL_ID, PREFIX, load_batch
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game, PlayCard, PlayerSetup, Scenario, SelectChoice
from hs_sim.engine.dark_gift_generation import DiscoverDarkGift
from hs_sim.engine.dark_gifts import DARK_GIFTS
from hs_sim.engine.effects import AddToHand, ChoiceOption, InvokeBehavior, RequestChoice, Summon
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import ChoicePurpose, CostSpec, Keyword, LimitedTriggerSpec, Rarity
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.targets import canonical_digest

P = 'k121.test.'
BEAST = 'BAR_024'
MUKLA = 'CORE_EX1_014'
TIGER = 'CORE_EX1_028'
YETI = 'CORE_CS2_182'
DRAGON = 'EX1_563'
CHALLENGER = 'TLC_251'
UNKNOWN = P + 'unknown_beast'
MEMBERS = (BEAST, MUKLA, TIGER, YETI, DRAGON, RAPTOR)
CTX = GenerationContext('k121-explicit-experiment', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())


@lru_cache(None)
def registry(members=MEMBERS, mode=None, pool=True):
    r = build_registry()
    for cid in members:
        if cid == IDENTITY:
            raw = load_batch()['evidence_only'][0]['record']
            r.register_pool_card(PoolCard(cid, CardType.MINION, 3, metadata_from_record(raw),
                keywords=(Keyword.REWIND,), battlecry=True))
        elif cid == UNKNOWN:
            r.register_pool_card(PoolCard(cid, CardType.MINION, 3,
                CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=('beast',), factions=(), subtypes=())))
        elif cid not in r.pool_cards:
            r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:
        r.register_pool(PoolDefinition(POOL_ID, 'k121-complete-explicit-fixture', CTX.target_id, CTX.mode,
            tuple(PoolMember(cid) for cid in members), complete=True))
    def fail(c):
        raise ResolutionError('K121 deliberate acquisition failure')
    def before(c):
        return (RequestChoice(c.player_id, (ChoiceOption('gift', 'Discover with source reduction', (
            DiscoverDarkGift(c.player_id, POOL_ID, QUERY, c.source_id,
                             cost=CostSpec(delta=-1, card_types=(CardType.MINION,))),)),), c.source_id),)
    for name, body in (('fail', fail), ('before', before), ('natural', lambda c: (Summon(c.player_id, RAPTOR),))):
        r.register_behavior(P + name, body)
        r.register_card(CardDefinition(P + name, name, CardType.SPELL, on_play=P + name, metadata=META))
    if mode:
        def eligible(c):
            return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id == RAPTOR
        def watch(c):
            if mode == 'fill':
                return (AddToHand(1, YETI, c.source_id),)
            if mode == 'fail':
                return (InvokeBehavior(P + 'fail', c.source_id, 1),)
            return (RequestChoice(1, (ChoiceOption('ok', 'Continue', ()),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(P + 'fail', c.source_id, 1),))), c.source_id),)
        r.register_trigger_condition(P + 'eligible', eligible)
        r.register_behavior(P + 'watch', watch)
        r.register_card(CardDefinition(P + 'watch', 'Original reward observer', CardType.MINION, health=6, metadata=META,
            limited_triggers=(LimitedTriggerSpec('choice_selected' if mode == 'fill' else 'card_created',
                P + 'watch', condition_id=P + 'eligible'),)))
    r.validate()
    return r


class KindredDarkGiftTests(unittest.TestCase):
    def setUp(self):
        self.configs = {}

    def game(self, hand=(RAPTOR,), board=(), members=MEMBERS, mode=None, pool=True, context=CTX, seed=121):
        config = (members, mode, pool)
        if mode:
            board = (*board, P + 'watch')
        g = Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(YETI,) * 8, mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_08', deck=(YETI,) * 8, mana=40, max_mana=40, mana_cap=40),
        ), seed=seed, generation_context=context), registry(*config))
        self.configs[g.registry.fingerprint()] = config
        return g

    def play(self, g, cid=RAPTOR):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid, position=len(g.state.players[1].board) if g.registry.card(cid).kind == CardType.MINION else None))
        return eid

    def cycle(self, g):
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))

    def qualified(self, **kw):
        hand = kw.pop('hand', (BEAST, RAPTOR))
        g = self.game(hand=hand, **kw)
        self.play(g, BEAST)
        self.cycle(g)
        return g

    def options(self, g):
        return g._frame.options

    def spec(self, g):
        return self.options(g)[0].effects[0].batch.spec

    def choose(self, g, key=None, gift=None):
        q = g.state.pending_choice
        option = next(o for o in self.options(g) if o.effects[0].selection.gift.id == gift) if gift else None
        if key is None:
            key = option.id if option else q.options[0].id
        g.apply(SelectChoice(q.player_id, q.id, (key,)))
        return option

    def created(self, g, source):
        return [g.state.entities[e.target_id] for e in g.events if e.kind == 'card_created' and e.source_id == source]

    def portable(self, g):
        config = self.configs[g.registry.fingerprint()]
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(*config))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(*config)).snapshot(), saved)
        for seat in (1, 2):
            wire = json.dumps(g.for_player(seat).observe()) + json.dumps(g.for_player(seat).legal_actions()) + json.dumps(g.player_events(seat))
            for field in ('KindredActivation', 'kindred_history', 'gift_pool', 'resolution_frame', 'rng_state', 'rewind_session'):
                self.assertNotIn('"' + field + '"', wire)
        return other

    def nodes(self, value, suffix):
        if isinstance(value, dict):
            if value.get('type', '').endswith('.' + suffix):
                yield value['fields']
            for item in value.values():
                yield from self.nodes(item, suffix)
        elif isinstance(value, list):
            for item in value:
                yield from self.nodes(item, suffix)

    def reject(self, g, saved):
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as caught:
            Game.from_snapshot(saved, registry(*self.configs[g.registry.fingerprint()]))
        self.assertNotIn('digest mismatch', str(caught.exception))

    def test_complete_current_legacy_and_ten_gift_rows_two_faces_exact_rewind_and_identity(self):
        data = load_batch()
        r = registry()
        self.assertEqual(len(data['cards'] + data['evidence_only'] + data['existing_gift_sources']), 12)
        self.assertEqual(data['gift_recipes_sha256'], canonical_digest([asdict(g) for g in DARK_GIFTS]))
        for row in data['cards'] + data['evidence_only'] + data['existing_gift_sources']:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        raw = data['cards'][0]['record']
        self.assertEqual(r.card(RAPTOR).metadata, replace(metadata_from_record(raw), deck_identity=IDENTITY))
        self.assertEqual(raw['tags']['858'], data['evidence_only'][0]['record']['dbf_id'])
        c = r.card(RAPTOR)
        self.assertEqual((c.cost, c.attack, c.health, c.keywords), (3, 4, 2, (Keyword.REWIND,)))
        self.assertIsNotNone(c.rewind)
        profile = r.kindred_profiles[RAPTOR]
        self.assertEqual((profile.wrapper, profile.prepare, profile.active), (PREFIX + 'wrapper', PREFIX + 'prepare', None))
        norm = lambda s: re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]', '', s)
        for o in data['official_observations']['observations']:
            en = o['locale'] == 'en_US'
            self.assertEqual(o['face']['name'], raw['name_en' if en else 'name'])
            self.assertEqual(norm(o['face']['text']), norm(raw['text_en' if en else 'text']))
        self.assertNotIn(IDENTITY, r.cards)
        self.assertFalse(data['formal_pool_complete'])
        self.assertFalse(data['cn_calibrated'])

    def test_no_previous_beast_still_discovers_once_without_source_discount_then_keeps_rewind(self):
        g = self.game()
        source = self.play(g)
        self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.POOL_DISCOVERY)
        self.assertIsNone(self.spec(g).cost)
        self.assertEqual({o.card_id for o in self.options(g)}, {BEAST, MUKLA, TIGER})
        self.choose(g)
        self.assertEqual(len(self.created(g, source)), 1)
        self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.REWIND)
        self.choose(g, 'keep')
        self.assertFalse(g.state.kindred_history[-1].condition.matched)
        self.assertEqual(g.state.kindred_history[-1].plan, ('prepare',))
        self.assertEqual(g.state.players[1].mana, 37)
        self.portable(g)

    def test_previous_owner_beast_freezes_one_reduction_in_one_original_discovery(self):
        g = self.qualified()
        before = g.state.players[1].mana
        source = self.play(g)
        self.assertEqual(self.spec(g).cost, CostSpec(delta=-1, card_types=(CardType.MINION,)))
        option = self.options(g)[0]
        expected = option.preview
        self.choose(g)
        e, = self.created(g, source)
        self.assertEqual((e.cost, e.attack, e.max_health), (expected.cost, expected.attack, expected.max_health))
        self.choose(g, 'keep')
        self.assertTrue(g.state.kindred_history[-1].condition.matched)
        self.assertEqual(g.state.kindred_history[-1].plan, ('prepare',))
        self.assertEqual(g.state.players[1].mana, before - 3)
        self.portable(g)

    def test_playing_beast_in_same_owner_turn_does_not_qualify_previous_turn(self):
        g = self.game(hand=(BEAST, RAPTOR))
        self.play(g, BEAST)
        self.play(g)
        self.assertIsNone(self.spec(g).cost)
        self.assertFalse(g.state.kindred_history[-1].condition.matched)

    def test_next_kindred_max_two_modifies_same_selected_result_and_consumes_once(self):
        g = self.qualified(hand=(BEAST, CHALLENGER, RAPTOR))
        self.play(g, CHALLENGER)
        self.assertEqual(len(g.state.players[1].player_effects), 1)
        source = self.play(g)
        self.assertEqual(self.spec(g).cost.delta, -2)
        self.assertFalse(g.state.players[1].player_effects)
        self.assertEqual((g.state.kindred_history[-1].repetitions, g.state.kindred_history[-1].plan), (2, ('prepare',)))
        self.choose(g)
        self.assertEqual(len(self.created(g, source)), 1)
        self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.REWIND)
        self.choose(g, 'keep')
        self.portable(g)

    def test_failed_kindred_consumes_original_next_source_but_does_not_add_discount_or_discovery(self):
        g = self.game(hand=(CHALLENGER, RAPTOR))
        self.play(g, CHALLENGER)
        source = self.play(g)
        self.assertIsNone(self.spec(g).cost)
        self.assertEqual(g.state.kindred_history[-1].repetitions, 2)
        self.assertFalse(g.state.players[1].player_effects)
        self.choose(g)
        self.assertEqual(len(self.created(g, source)), 1)
        self.choose(g, 'keep')
        self.portable(g)

    def test_real_battlecry_repeat_reaccepts_after_consumed_kindred_sources_without_repayment(self):
        g = self.qualified(hand=(BEAST, CHALLENGER, RAPTOR), board=('TIME_064',))
        self.play(g, CHALLENGER)
        self.assertEqual(len(g.state.players[1].player_effects), 2)
        before = g.state.players[1].mana
        source = self.play(g)
        self.assertEqual(self.spec(g).cost.delta, -2)
        self.choose(g)
        self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.POOL_DISCOVERY)
        self.assertEqual(self.spec(g).cost.delta, -1)
        self.choose(g)
        self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.REWIND)
        self.choose(g, 'keep')
        rows = [row for row in g.state.kindred_history if row.card_id == RAPTOR]
        self.assertEqual([row.repetitions for row in rows], [2, 1])
        self.assertEqual(len(self.created(g, source)), 2)
        self.assertEqual(g.state.players[1].mana, before - 3)
        self.portable(g)

    def test_gift_reduction_and_kindred_source_reduction_share_preview_and_zero_floor(self):
        g = self.qualified(members=(MUKLA,), seed=22)
        source = self.play(g)
        option = self.options(g)[0]
        gift = option.effects[0].selection.gift
        self.assertEqual(gift.id, 'EDR_100t2')
        self.assertEqual(option.preview.cost, max(0, 3 + gift.cost_delta - 1))
        self.choose(g)
        e, = self.created(g, source)
        self.assertEqual(e.cost, option.preview.cost)
        self.assertEqual(e.cost, 0)
        self.assertEqual(e.enchantments[-1].source_id, source)
        self.choose(g, 'keep')
        self.portable(g)

    def test_first_pair_wait_restore_independent_registry_replay_and_keep_are_exact(self):
        g = self.qualified()
        source = self.play(g)
        other = self.portable(g)
        fresh = Game.from_snapshot(g.snapshot(), registry.__wrapped__(*self.configs[g.registry.fingerprint()]))
        self.assertEqual(fresh.snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), registry.__wrapped__(*self.configs[g.registry.fingerprint()])).snapshot(), g.snapshot())
        rng = g._rng.getstate()
        for game in (g, other, fresh):
            self.choose(game)
            self.assertEqual(game.state.pending_choice.purpose, ChoicePurpose.REWIND)
            self.assertEqual(len(self.created(game, source)), 1)
            self.choose(game, 'keep')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.snapshot(), fresh.snapshot())
        self.assertEqual(g._rng.getstate(), rng)

    def test_retry_removes_first_gift_and_kindred_result_then_repeats_with_one_original_payment(self):
        g = self.qualified(hand=(BEAST, CHALLENGER, RAPTOR))
        self.play(g, CHALLENGER)
        before = g.state.players[1].mana
        source = self.play(g)
        self.choose(g)
        old, = self.created(g, source)
        self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.REWIND)
        self.portable(g)
        self.choose(g, 'retry')
        self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.POOL_DISCOVERY)
        self.assertEqual(self.spec(g).cost.delta, -2)
        self.assertNotIn(old.id, g.state.players[1].hand + g.state.players[1].deck)
        self.choose(g)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].mana, before - 3)
        self.assertEqual(len([x for x in g.state.battlecry_history if x.card_id == RAPTOR]), 1)
        self.assertEqual(len([x for x in g.state.kindred_history if x.card_id == RAPTOR]), 1)
        self.assertFalse(g.state.players[1].player_effects)
        self.portable(g)

    def test_acquisition_wait_bad_resume_rolls_back_only_resume_and_keeps_accepted_reduction(self):
        g = self.qualified(mode='wait')
        source = self.play(g)
        cost = self.spec(g).cost
        self.choose(g)
        self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.EFFECT)
        other = self.portable(g)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K121 deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game, 'ok')
            self.choose(game, 'keep')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(cost.delta, -1)
        self.assertEqual(len(self.created(g, source)), 1)

    def test_post_selection_failure_restores_committed_offer_payment_and_rng(self):
        g = self.qualified(mode='fail')
        self.play(g)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K121 deliberate'):
            self.choose(g)
        self.assertEqual(g.snapshot(), saved)
        self.portable(g)

    def test_full_hand_result_has_source_reduction_even_when_burned(self):
        g = self.qualified(hand=(BEAST, RAPTOR) + (YETI,) * 8, mode='fill')
        source = self.play(g)
        option = next(o for o in self.options(g) if o.effects[0].selection.gift.destination == 'hand')
        g.apply(SelectChoice(1, g.state.pending_choice.id, (option.id,)))
        e, = self.created(g, source)
        self.assertEqual(e.zone.value, 'graveyard')
        self.assertEqual(e.cost, option.preview.cost)
        self.choose(g, 'keep')
        self.portable(g)

    def test_sweet_dreams_deck_top_receives_same_source_cost_and_original_material(self):
        g = self.qualified(members=(MUKLA,), seed=11)
        source = self.play(g)
        option = self.options(g)[0]
        gift = option.effects[0].selection.gift
        self.assertEqual(gift.id, 'EDR_100t8')
        self.choose(g)
        e, = self.created(g, source)
        self.assertEqual(e.cost, max(0, 3 + gift.cost_delta - 1))
        self.assertEqual(e.zone.value, 'deck')
        self.assertEqual(g.state.players[1].deck[0], e.id)
        self.choose(g, 'keep')
        self.portable(g)

    def test_source_and_explicit_legacy_edition_are_excluded_before_unknown_execution(self):
        g = self.game(members=(RAPTOR, IDENTITY, BEAST))
        self.play(g)
        self.assertEqual({o.card_id for o in self.options(g)}, {BEAST})
        self.choose(g)
        self.choose(g, 'keep')
        self.portable(g)

    def test_natural_summon_has_no_battlecry_kindred_or_rewind_request(self):
        g = self.game(hand=(P + 'natural',), pool=False, context=None)
        self.play(g, P + 'natural')
        self.assertIsNone(g.state.pending_choice)
        self.assertFalse(g.state.kindred_history)
        self.assertFalse(g.state.battlecry_history)
        self.portable(g)

    def test_unknown_complete_candidate_and_missing_pool_context_fail_before_rng_and_payment(self):
        for case in ('unknown', 'context', 'pool'):
            g = self.qualified(members=(*MEMBERS, UNKNOWN) if case == 'unknown' else MEMBERS,
                context=None if case == 'context' else CTX, pool=case != 'pool')
            saved = g.snapshot()
            with patch.object(random.Random, 'randrange', side_effect=AssertionError('Unvalidated Beast sampled')) as rng:
                with self.assertRaises(ResolutionError):
                    self.play(g)
                rng.assert_not_called()
            self.assertEqual(g.snapshot(), saved)

    def test_empty_beast_pool_preserves_paid_rewind_and_is_rng_neutral(self):
        g = self.game(members=(YETI,))
        rng = g._rng.getstate()
        self.play(g)
        self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.REWIND)
        self.assertEqual(g._rng.getstate(), rng)
        self.choose(g, 'keep')
        self.portable(g)

    def test_finite_negative_minion_cost_only_and_saved_nested_cost_is_strict(self):
        good = DiscoverDarkGift(1, POOL_ID, QUERY, 1, CostSpec(delta=-1, card_types=(CardType.MINION,)))
        for cost in ({'delta': -1}, CostSpec(delta=0, card_types=(CardType.MINION,)), CostSpec(set_to=1),
                     CostSpec(delta=1), CostSpec(delta=-1), CostSpec(delta=-1, minimum=1, card_types=(CardType.MINION,))):
            with self.subTest(cost=cost), self.assertRaises(ValueError):
                replace(good, cost=cost)
        g = self.game(hand=(P + 'before',))
        self.play(g, P + 'before')
        self.portable(g)
        for field, value in (('delta', 0), ('set_to', 1)):
            saved = deepcopy(g.snapshot())
            request = next(self.nodes(saved['resolution_frame'], 'DiscoverDarkGift'))
            request['cost']['fields'][field] = value
            self.reject(g, saved)
        saved = deepcopy(g.snapshot())
        del next(self.nodes(saved['resolution_frame'], 'DiscoverDarkGift'))['cost']
        self.reject(g, saved)
        saved = g.snapshot()
        saved['schema_version'] = 330
        self.assertEqual(SNAPSHOT_SCHEMA_VERSION, 331)
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, registry())


if __name__ == '__main__':
    unittest.main()
