"""Real native sources bind host context and retain existing paired discovery."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import random
import re
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_dark_gift_generation_cards import TORMENTOR, ENDMAW, ROOTS, QUERIES, POOL_ID, load_batch
from hs_sim.engine import CardClass, CardDefinition, CardMetadata, CardType, Game, PlayCard, PlayerSetup, Scenario, SelectChoice
from hs_sim.engine.dark_gift_generation import DiscoverDarkGift
from hs_sim.engine.dark_gifts import DARK_GIFTS, DARK_GIFT_VERSION, dark_gift_pool
from hs_sim.engine.effects import AddToHand, ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import BattlecryRepeatSpec, LimitedTriggerSpec, Rarity, Zone
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery, resolve_candidates
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.targets import canonical_digest

P = 'k120.test.'
LEGEND = 'EX1_563'
SECOND = 'TIME_064'
MAGE = 'RLK_541'
DRUID = 'OG_044'
WARRIOR = 'DEEP_020'
ONE = 'JAIL_460'
SQUIRE = 'CORE_EX1_008'
WARLOCK = 'CORE_CS2_065'
YETI = 'CORE_CS2_182'
UNKNOWN = P + 'unknown_legend'
UNKNOWN_ONE = P + 'unknown_one'
MEMBERS = (LEGEND, SECOND, MAGE, DRUID, WARRIOR, ONE, SQUIRE, WARLOCK, YETI)
CTX = GenerationContext('k120-host-a', 'experimental')
CTX_B = GenerationContext('k120-host-b', 'standard')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())


@lru_cache(None)
def registry(members=MEMBERS, mode=None, pool=True, context=CTX):
    r = build_registry()
    for cid in members:
        if cid in r.cards and cid not in r.pool_cards:
            r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    for cid, cost, rarity in ((UNKNOWN, 9, Rarity.LEGENDARY), (UNKNOWN_ONE, 1, Rarity.COMMON)):
        if cid in members:
            r.register_pool_card(PoolCard(cid, CardType.MINION, cost,
                CardMetadata(True, (CardClass.MAGE,), rarity, tribes=(), factions=(), subtypes=())))
    if pool:
        r.register_pool(PoolDefinition(POOL_ID, 'k120-explicit-complete-fixture', context.target_id, context.mode,
            tuple(PoolMember(cid) for cid in members), complete=True))
    def fail(c):
        raise ResolutionError('K120 deliberate post-choice failure')
    def before(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('discover', 'Native gift discovery', (DiscoverDarkGift(c.player_id, POOL_ID, QUERIES[TORMENTOR], c.source_id),)),
            ChoiceOption('skip', 'Skip', ()),), c.source_id),)
    def invalid(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('good', 'Good', ()),
            ChoiceOption('bad', 'Unknown source', (DiscoverDarkGift(c.player_id, POOL_ID, QUERIES[TORMENTOR], 999999),)),), c.source_id),)
    for name, body in (('fail', fail), ('before', before), ('invalid', invalid)):
        r.register_behavior(P + name, body)
        r.register_card(CardDefinition(P + name, name, CardType.SPELL, on_play=P + name, metadata=META))
    r.register_card(CardDefinition(P + 'twice', 'Existing repeat policy', CardType.MINION, health=6, metadata=META,
        battlecry_repeats=(BattlecryRepeatSpec(),)))
    if mode:
        def eligible(c):
            return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in ROOTS
        def watch(c):
            if mode == 'fill':
                return (AddToHand(c.player_id, YETI, c.source_id),)
            return (InvokeBehavior(P + 'fail', c.source_id, c.player_id),)
        r.register_trigger_condition(P + 'eligible', eligible)
        r.register_behavior(P + 'watch', watch)
        r.register_card(CardDefinition(P + 'watch', 'Choice delivery observer', CardType.MINION, health=6, metadata=META,
            limited_triggers=(LimitedTriggerSpec('choice_selected' if mode == 'fill' else 'card_created',
                P + 'watch', condition_id=P + 'eligible'),)))
    r.validate()
    return r


class NativeDarkGiftGenerationTests(unittest.TestCase):
    def game(self, hand=(TORMENTOR,), board=(), members=MEMBERS, mode=None, pool=True, context=CTX,
             supplied_context=True, hero='HERO_08', seed=120):
        config = (members, mode, pool, context)
        if mode:
            board = (*board, P + 'watch')
        g = Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, deck=(YETI,) * 4, mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_08', hand=(YETI,), deck=(YETI,) * 4),
        ), seed=seed, generation_context=context if supplied_context else None), registry(*config))
        self.configs[g.registry.fingerprint()] = config
        return g

    def setUp(self):
        self.configs = {}

    def play(self, g, cid=TORMENTOR):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid, position=len(g.state.players[1].board) if g.registry.card(cid).kind == CardType.MINION else None))
        return eid

    def options(self, g):
        return g._frame.options

    def spec(self, g):
        return self.options(g)[0].effects[0].batch.spec

    def pick(self, g, destination=None):
        return next(o for o in self.options(g) if destination is None or o.effects[0].selection.gift.destination == destination)

    def choose(self, g, option=None):
        option = self.pick(g) if option is None else option
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (option.id,)))
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
        self.configs[other.registry.fingerprint()] = config
        for seat in (1, 2):
            wire = json.dumps(g.for_player(seat).observe()) + json.dumps(g.for_player(seat).legal_actions()) + json.dumps(g.player_events(seat))
            for field in ('DiscoveryGiftPool', 'gift_pool', 'offered_gifts', 'resolution_frame', 'rng_state', 'DiscoverDarkGift'):
                self.assertNotIn('"' + field + '"', wire)
            self.assertNotIn('entities', g.for_player(seat).observe()['observation'])
        return other

    def candidates(self, g, cid, hero_class=CardClass.MAGE):
        return resolve_candidates(g.registry, g._generation_context, POOL_ID, QUERIES[cid],
            source_card_id=cid, current_class=hero_class, exclude_source_by_rule=True, player_id=1)

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

    def test_full_two_root_ten_existing_gift_rows_four_faces_and_real_dualclass_metadata(self):
        data = load_batch()
        r = registry()
        self.assertEqual(len(data['cards'] + data['existing_gift_sources']), 12)
        self.assertEqual(data['gift_recipes_sha256'], canonical_digest([asdict(g) for g in DARK_GIFTS]))
        for row in data['cards'] + data['existing_gift_sources']:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        norm = lambda s: re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]', '', s)
        raws = {x['record']['id']: x['record'] for x in data['cards']}
        self.assertEqual(len(data['official_observations']['observations']), 4)
        for o in data['official_observations']['observations']:
            raw = raws[o['card_id']]
            cn = o['locale'] == 'zh_CN'
            self.assertEqual(o['face']['name'], raw['name' if cn else 'name_en'])
            self.assertEqual(norm(o['face']['text']), norm(raw['text' if cn else 'text_en']))
        for cid in ROOTS:
            self.assertEqual(r.card(cid).metadata, metadata_from_record(raws[cid]))
        self.assertEqual(r.card(TORMENTOR).metadata.tribes, ('demon',))
        self.assertEqual(r.card(ENDMAW).metadata.classes, (CardClass.HUNTER, CardClass.PALADIN))
        self.assertEqual(r.card(ENDMAW).metadata.tribes, ('beast',))
        self.assertFalse(data['cn_calibrated'])
        self.assertFalse(data['formal_pool_complete'])

    def test_tormentor_native_battlecry_filters_legendary_current_hero_and_neutral(self):
        g = self.game()
        self.assertEqual({m.card_id for m in self.candidates(g, TORMENTOR)}, {LEGEND, SECOND, MAGE})
        source = self.play(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {LEGEND, SECOND, MAGE})
        self.assertEqual((self.spec(g).source_id, g.state.players[1].mana), (source, 36))
        self.assertEqual((len(g.state.battlecry_history), len(g.state.play_history), len(g.state.cast_history)), (1, 1, 0))
        self.choose(g)
        self.assertEqual(len(self.created(g, source)), 1)
        self.portable(g)

    def test_endmaw_native_battlecry_uses_printed_one_cost_minions(self):
        g = self.game(hand=(ENDMAW,))
        source = self.play(g, ENDMAW)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {ONE, SQUIRE})
        self.assertEqual((self.spec(g).query.min_cost, self.spec(g).query.max_cost), (1, 1))
        self.assertEqual(g.state.players[1].mana, 37)
        self.choose(g)
        self.assertEqual(len(self.created(g, source)), 1)
        self.portable(g)

    def test_current_hero_scope_is_not_source_printed_dualclass_scope(self):
        g = self.game(hand=(ENDMAW,), hero='HERO_07')
        self.play(g, ENDMAW)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {ONE, SQUIRE, WARLOCK})
        self.assertEqual(self.spec(g).query.class_mode, 'current')
        self.portable(g)

    def test_native_entry_binds_each_actual_host_target_and_mode_with_full_unchanged_inventory(self):
        for ctx in (CTX, CTX_B):
            g = self.game(context=ctx)
            self.play(g)
            pool = self.spec(g).gift_pool
            self.assertEqual(pool, dark_gift_pool(ctx.target_id, ctx.mode))
            self.assertEqual(pool.members, DARK_GIFTS)
            self.assertEqual(pool.version, DARK_GIFT_VERSION)
            self.assertTrue(pool.complete)
            self.portable(g)

    def test_three_offers_have_distinct_eligible_original_gifts_and_selected_preview_matches_delivery(self):
        g = self.game()
        source = self.play(g)
        options = self.options(g)
        gifts = [o.effects[0].selection.gift for o in options]
        self.assertEqual(len({x.id for x in gifts}), 3)
        self.assertTrue(all(gift.eligible(g.registry.card(o.card_id)) for o, gift in zip(options, gifts)))
        option = self.pick(g)
        gift = option.effects[0].selection.gift
        self.choose(g, option)
        entity, = self.created(g, source)
        self.assertEqual((entity.card_id, entity.cost, entity.attack, entity.max_health),
            (option.card_id, option.preview.cost, option.preview.attack, option.preview.max_health))
        self.assertTrue(any(e.label == 'created_minion_grant:' + gift.id and e.source_id == source for e in entity.enchantments))
        self.assertEqual(entity.zone, Zone.HAND if gift.destination == 'hand' else Zone.DECK)
        self.portable(g)

    def test_selected_pair_restores_without_new_rng_payment_or_duplicate_creation(self):
        g = self.game()
        source = self.play(g)
        other = self.portable(g)
        fresh = Game.from_snapshot(g.snapshot(), registry.__wrapped__(*self.configs[g.registry.fingerprint()]))
        self.assertEqual(fresh.snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), registry.__wrapped__(*self.configs[g.registry.fingerprint()])).snapshot(), g.snapshot())
        rng = g._rng.getstate()
        selected = self.pick(g)
        for game in (g, other, fresh):
            self.choose(game, selected)
            self.assertEqual(len(self.created(game, source)), 1)
            self.assertEqual(game.state.players[1].mana, 36)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.snapshot(), fresh.snapshot())
        self.assertEqual(g._rng.getstate(), rng)
        self.portable(g)

    def test_old_same_name_hand_card_does_not_get_created_gift(self):
        g = self.game(hand=(TORMENTOR, LEGEND), members=(LEGEND,))
        old = g.state.players[1].hand[1]
        source = self.play(g)
        self.choose(g)
        new, = self.created(g, source)
        self.assertNotEqual(old, new.id)
        self.assertFalse(g.state.entities[old].enchantments)
        self.assertEqual((g.state.entities[old].attack, g.state.entities[old].max_health), (4, 12))
        self.portable(g)

    def test_complete_choice_delivery_failure_rolls_back_selected_gift_rng_and_allocation(self):
        g = self.game(mode='fail')
        self.play(g)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K120 deliberate'):
            self.choose(g, self.pick(g, 'hand'))
        self.assertEqual(g.snapshot(), saved)
        self.portable(g)

    def test_hand_overflow_burns_actual_complete_gifted_entity(self):
        g = self.game(hand=(TORMENTOR,) + (YETI,) * 9, mode='fill')
        source = self.play(g)
        option = self.pick(g, 'hand')
        self.choose(g, option)
        new, = self.created(g, source)
        self.assertEqual(new.zone, Zone.GRAVEYARD)
        self.assertEqual((new.cost, new.attack, new.max_health), (option.preview.cost, option.preview.attack, option.preview.max_health))
        self.assertEqual(len([e for e in g.events if e.kind == 'card_burned']), 1)
        self.portable(g)

    def test_two_real_battlecry_executions_use_two_offers_and_one_original_payment(self):
        g = self.game(board=(P + 'twice',))
        source = self.play(g)
        first_id = g.state.pending_choice.id
        self.choose(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertNotEqual(g.state.pending_choice.id, first_id)
        self.assertEqual(len(self.created(g, source)), 1)
        self.portable(g)
        self.choose(g)
        self.assertEqual((len(self.created(g, source)), len(g.state.battlecry_history), len(g.state.play_history)), (2, 2, 1))
        self.assertEqual(g.state.players[1].mana, 36)
        self.portable(g)

    def test_unknown_matching_candidate_is_not_cropped_before_minion_or_gift_rng(self):
        for cid, unknown in ((TORMENTOR, UNKNOWN), (ENDMAW, UNKNOWN_ONE)):
            g = self.game(hand=(cid,), members=(*MEMBERS, unknown))
            saved = g.snapshot()
            with patch.object(random.Random, 'randrange', side_effect=AssertionError('Unknown minion sampled')) as samples:
                with patch.object(random.Random, 'choice', side_effect=AssertionError('Gift selected before full validation')) as gifts:
                    with self.assertRaises(ResolutionError):
                        self.play(g, cid)
                    samples.assert_not_called()
                    gifts.assert_not_called()
            self.assertEqual(g.snapshot(), saved)

    def test_missing_host_context_or_matching_pool_rolls_back_paid_native_minion(self):
        for cid in ROOTS:
            for case in ('context', 'pool'):
                g = self.game(hand=(cid,), pool=case != 'pool', supplied_context=case != 'context')
                saved = g.snapshot()
                with self.assertRaises(ResolutionError):
                    self.play(g, cid)
                self.assertEqual(g.snapshot(), saved)

    def test_empty_pool_keeps_original_play_and_is_rng_neutral(self):
        for cid in ROOTS:
            g = self.game(hand=(cid,), members=(YETI,))
            rng = g._rng.getstate()
            source = self.play(g, cid)
            self.assertIsNone(g.state.pending_choice)
            self.assertFalse(self.created(g, source))
            self.assertEqual(g._rng.getstate(), rng)
            self.assertEqual(g.state.entities[source].zone, Zone.BOARD)
            self.portable(g)

    def test_wait_before_binding_restores_typed_request_then_uses_original_host_context(self):
        g = self.game(hand=(P + 'before',), context=CTX_B)
        self.play(g, P + 'before')
        self.assertTrue(list(self.nodes(g.snapshot()['resolution_frame'], 'DiscoverDarkGift')))
        other = self.portable(g)
        for game in (g, other):
            q = game.state.pending_choice
            game.apply(SelectChoice(q.player_id, q.id, ('discover',)))
            self.assertEqual(self.spec(game).gift_pool.generation_target, CTX_B.target_id)
            self.assertEqual(self.spec(game).gift_pool.mode, CTX_B.mode)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.portable(g)

    def test_malformed_or_future_source_nested_request_is_rejected_without_rehash_shortcut(self):
        g = self.game(hand=(P + 'before',))
        self.play(g, P + 'before')
        for field, value in (('source_id', 999999), ('source_id', True), ('unexpected', 1)):
            saved = deepcopy(g.snapshot())
            next(self.nodes(saved['resolution_frame'], 'DiscoverDarkGift'))[field] = value
            self.reject(g, saved)
        saved = deepcopy(g.snapshot())
        del next(self.nodes(saved['resolution_frame'], 'DiscoverDarkGift'))['query']
        self.reject(g, saved)
        h = self.game(hand=(P + 'invalid',))
        saved = h.snapshot()
        with self.assertRaises(ValueError):
            self.play(h, P + 'invalid')
        self.assertEqual(h.snapshot(), saved)

    def test_finite_native_declaration_and_new_effect_leave_existing_payload_and_schema_shapes(self):
        good = DiscoverDarkGift(1, POOL_ID, QUERIES[TORMENTOR], 1)
        for change in ({'source_id': None}, {'source_id': True}, {'player_id': 3}, {'pool_id': ''},
                       {'query': {}}, {'query': PoolQuery(kinds=(CardType.SPELL,), collectible=True)},
                       {'query': replace(QUERIES[TORMENTOR], collectible=None)}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(good, **change)
        with self.assertRaises(TypeError):
            DiscoverDarkGift(1, POOL_ID, QUERIES[TORMENTOR], 1, destination='board')
        g = self.game()
        self.assertEqual(g.snapshot()['schema_version'], 330)
        self.assertEqual(SNAPSHOT_SCHEMA_VERSION, 330)
        self.assertIn('hs_sim.engine.dark_gift_generation.DiscoverDarkGift', g.mechanics.signature['effect_types'])

    def test_player_boundary_hides_private_pairing_from_opponent_and_internal_inventory_from_both(self):
        g = self.game()
        source = self.play(g)
        self.assertEqual(g.observe(2)['pending_choice'], {'player_id': 1})
        public = g.for_player(2).observe()
        for label in (gift.label for gift in DARK_GIFTS):
            self.assertNotIn(label, json.dumps(public, ensure_ascii=False))
        self.portable(g)
        self.choose(g)
        new, = self.created(g, source)
        self.assertNotIn(new.card_id, json.dumps(g.for_player(2).observe()))
        self.portable(g)


if __name__ == '__main__':
    unittest.main()
