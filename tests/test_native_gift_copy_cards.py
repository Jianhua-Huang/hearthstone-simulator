"""Selected enriched recipes create two fresh results through existing delivery."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import random
import re
import unittest
from unittest.mock import patch

from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.native_gift_copy_cards import STALKER, QUERY, POOL_ID, COPY_POLICY, load_batch
from hs_sim.engine import CardClass, CardDefinition, CardMetadata, CardType, Game, PlayCard, PlayerSetup, Scenario, SelectChoice
from hs_sim.engine.dark_gift_generation import DiscoverDarkGift
from hs_sim.engine.dark_gifts import DARK_GIFTS, dark_gift_pool
from hs_sim.engine.effects import AddToHand, ChoiceOption, Destroy, InvokeBehavior, RequestChoice, Summon
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.hand_choice_followups import DiscoverForPlayFollowup
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import BattlecryRepeatSpec, CostSpec, LimitedTriggerSpec, Rarity, Zone
from hs_sim.engine.pools import DiscoverFromPool, GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P = 'k125.test.'
DEMON, VOID, FOREIGN, YETI = 'EDR_102', 'CORE_CS2_065', 'EDR_456', 'CORE_CS2_182'
UNKNOWN = P + 'unknown_demon'
MEMBERS = (DEMON, VOID, FOREIGN, YETI)
CTX = GenerationContext('k125-host', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())
SEEDS = {'EDR_100t6': 0, 'EDR_100t9': 1, 'EDR_100t1': 2, 'EDR_100t3': 4, 'EDR_100t5': 5,
         'EDR_100t7': 6, 'EDR_100t13': 7, 'EDR_100t8': 11, 'EDR_100t': 15, 'EDR_100t2': 22}


@lru_cache(None)
def registry(members=MEMBERS, mode=None, pool=True):
    r = build_registry()
    if UNKNOWN in members:
        r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 5,
            CardMetadata(True, (CardClass.WARLOCK,), Rarity.COMMON, tribes=('demon',), factions=(), subtypes=()),
            battlecry=False, deathrattle=False, choose_one=False))
    if pool:
        r.register_pool(PoolDefinition(POOL_ID, 'k125-complete-explicit-fixture', CTX.target_id, CTX.mode,
            tuple(PoolMember(cid) for cid in members), complete=True))
    r.register_behavior(P + 'fail', lambda c: (_ for _ in ()).throw(ResolutionError('K125 deliberate copy failure')))
    r.register_behavior(P + 'summon', lambda c: (Summon(1, STALKER),))
    r.register_behavior(P + 'before', lambda c: (RequestChoice(1, (
        ChoiceOption('get', 'Native selected copy', (DiscoverDarkGift(1, POOL_ID, QUERY, c.source_id, gift_copy_to_hand=True),)),
        ChoiceOption('skip', 'Skip', ())), c.source_id),))
    for name in ('fail', 'summon', 'before'):
        r.register_card(CardDefinition(P + name, name, CardType.SPELL, on_play=P + name, metadata=META))
    r.register_card(CardDefinition(P + 'twice', 'Original repeat policy', CardType.MINION, health=8, metadata=META,
        battlecry_repeats=(BattlecryRepeatSpec(),)))
    if mode:
        def eligible(c):
            return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id == STALKER
        def watch(c):
            if mode == 'fill':
                return (AddToHand(1, YETI, c.source_id),)
            count = sum(any(e.source_id == c.event.source_id and e.label.startswith('created_minion_grant:')
                            for e in entity.enchantments) for entity in c.state.entities.values())
            if mode == 'fail_second':
                return (InvokeBehavior(P + 'fail', c.source_id, 1),) if count == 2 else ()
            if count != 1:
                return ()
            if mode == 'kill_first':
                return (Destroy(c.event.source_id, c.source_id),)
            if mode == 'buff_first':
                return (BuffStoredCard(CardReference.capture(c.state.entities[c.event.target_id]), 2, 3, c.source_id),)
            return (RequestChoice(1, (ChoiceOption('ok', 'Continue', ()),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(P + 'fail', c.source_id, 1),))), c.source_id),)
        r.register_behavior(P + 'watch', watch)
        r.register_trigger_condition(P + 'eligible', eligible)
        r.register_card(CardDefinition(P + 'watch', 'Actual acquisition observer', CardType.MINION, health=8, metadata=META,
            limited_triggers=(LimitedTriggerSpec('choice_selected' if mode == 'fill' else 'card_created', P + 'watch',
                condition_id=P + 'eligible', uses=2 if mode == 'fail_second' else 1),)))
    r.validate()
    return r


class NativeGiftCopyTests(unittest.TestCase):
    def game(self, members=MEMBERS, mode=None, pool=True, context=CTX, seed=22, hand=(STALKER,), board=()):
        self.config = (members, mode, pool)
        if mode:
            board = (*board, P + 'watch')
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_07', hand=hand, board=board, deck=(YETI,) * 4, mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_08', deck=(YETI,) * 4),
        ), seed=seed, generation_context=context), registry(*self.config))

    def play(self, g, cid=STALKER):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid, position=len(g.state.players[1].board) if g.registry.card(cid).kind == CardType.MINION else None))
        return eid

    def choose(self, g, key=None):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (q.options[0].id if key is None else key,)))

    def results(self, g, source):
        return [g.state.entities[e.target_id] for e in g.events if e.kind == 'card_created' and e.source_id == source]

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry.__wrapped__(*self.config))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry.__wrapped__(*self.config)).snapshot(), saved)
        for player in (1, 2):
            wire = json.dumps(g.for_player(player).observe()) + json.dumps(g.for_player(player).legal_actions()) + json.dumps(g.player_events(player))
            for key in ('resolution_frame', 'rng_state', 'gift_copy_to_hand', 'gift_pool', 'offered_gifts', 'behavior_id'):
                self.assertNotIn('"' + key + '"', wire)
        return other

    def test_complete_source_gifts_faces_dual_tribes_and_explicit_copy_policy(self):
        data = load_batch()
        self.assertEqual(len(data['cards'] + data['existing_gift_sources']), 11)
        self.assertEqual(data['copy_policy'], COPY_POLICY)
        self.assertFalse(data['cn_calibrated'])
        self.assertFalse(data['formal_pool_complete'])
        norm = lambda s: re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]', '', s)
        raw = data['cards'][0]['record']
        for row in data['cards'] + data['existing_gift_sources']:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        for o in data['official_observations']['observations']:
            cn = o['locale'] == 'zh_CN'
            self.assertEqual(o['face']['name'], raw['name' if cn else 'name_en'])
            self.assertEqual(norm(o['face']['text']), norm(raw['text' if cn else 'text_en']))
        c = registry().card(STALKER)
        self.assertEqual((c.cost, c.attack, c.health, c.metadata.classes), (4, 4, 3, (CardClass.WARLOCK,)))
        self.assertEqual(c.metadata.tribes, ('beast', 'elemental'))
        self.assertFalse(c.keywords)

    def test_single_definition_old_complete_metadata_and_default_identity_are_preserved(self):
        with patch('hs_sim.cards.native_gift_copy_cards.register_native_gift_copy_cards', lambda r: None):
            before = build_registry()
        after = build_registry()
        self.assertEqual(set(after.cards) - set(before.cards), {STALKER})
        self.assertTrue(all(asdict(before.card(cid)) == asdict(after.card(cid)) for cid in before.cards))
        self.assertEqual(dict(after.pool_cards), dict(before.pool_cards))
        self.assertEqual(dict(after.pools), dict(before.pools))
        self.assertEqual(dict(after.generation_families), dict(before.generation_families))
        from hs_sim.engine.representative import build_registry as default
        self.assertEqual(default().fingerprint(), DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_one_native_battlecry_choice_filters_current_demons_and_pays_once(self):
        g = self.game()
        self.play(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {DEMON, VOID})
        spec = g._frame.options[0].effects[0].batch.spec
        self.assertTrue(spec.gift_copy_to_hand)
        self.assertEqual(spec.query, QUERY)
        self.assertEqual(len(spec.gift_pool.members), 10)
        self.assertEqual(g.state.players[1].mana, 36)
        self.assertEqual(len(g.state.battlecry_history), 1)
        self.portable(g)

    def test_all_ten_real_gifts_preserve_same_enriched_material_but_create_independent_entities(self):
        self.assertEqual(set(SEEDS), {g.id for g in DARK_GIFTS})
        for gift_id, seed in SEEDS.items():
            with self.subTest(gift=gift_id):
                g = self.game(members=(DEMON,), seed=seed)
                source = self.play(g)
                option = g._frame.options[0]
                gift = option.effects[0].selection.gift
                self.assertEqual(gift.id, gift_id)
                self.choose(g)
                original, copy = self.results(g, source)
                self.assertNotEqual(original.id, copy.id)
                expected = (DEMON, option.preview.cost, option.preview.attack, option.preview.max_health)
                for entity in (original, copy):
                    self.assertEqual((entity.card_id, entity.cost, entity.attack, entity.max_health), expected)
                    self.assertTrue(any(e.label == 'created_minion_grant:' + gift_id for e in entity.enchantments))
                self.assertEqual(original.zone, Zone.DECK if gift.destination == 'deck_top' else Zone.HAND)
                self.assertEqual(copy.zone, Zone.HAND)
                self.assertFalse({a.id for a in original.abilities}.intersection(a.id for a in copy.abilities))
                self.assertEqual(len(g.state.battlecry_history), 1)
                self.assertEqual(sum(e.kind == 'pool_discovery_picked' for e in g.events), 1)

    def test_original_offer_restores_then_creates_two_without_resampling_or_repayment(self):
        g = self.game(members=(DEMON,))
        source = self.play(g)
        other = self.portable(g)
        rng = g._rng.getstate()
        with patch.object(random.Random, 'randrange', side_effect=AssertionError('Copy resampled original candidate')):
            self.choose(g)
            self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g._rng.getstate(), rng)
        self.assertEqual(len(self.results(g, source)), 2)
        self.assertEqual(g.state.players[1].mana, 36)
        self.portable(g)

    def test_first_acquisition_wait_preserves_exact_pending_copy_and_bad_resume_rolls_back(self):
        g = self.game(members=(DEMON,), mode='wait')
        source = self.play(g)
        self.choose(g)
        self.assertEqual(len(self.results(g, source)), 1)
        saved = g.snapshot()
        other = self.portable(g)
        with self.assertRaises(ResolutionError):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game, 'ok')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(self.results(g, source)), 2)
        self.portable(g)

    def test_copy_uses_selected_recipe_before_first_only_acquisition_buff(self):
        g = self.game(members=(DEMON,), mode='buff_first')
        source = self.play(g)
        preview = g._frame.options[0].preview
        self.choose(g)
        original, copy = self.results(g, source)
        self.assertEqual((original.attack, original.max_health), (preview.attack + 2, preview.max_health + 3))
        self.assertEqual((copy.attack, copy.max_health), (preview.attack, preview.max_health))
        self.portable(g)

    def test_source_dying_after_original_does_not_cancel_already_accepted_copy(self):
        g = self.game(members=(DEMON,), mode='kill_first')
        source = self.play(g)
        self.choose(g)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(len(self.results(g, source)), 2)
        self.portable(g)

    def test_second_creation_failure_rolls_back_both_results_to_original_committed_offer(self):
        g = self.game(members=(DEMON,), mode='fail_second')
        self.play(g)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K125 deliberate'):
            self.choose(g)
        self.assertEqual(g.snapshot(), saved)

    def test_one_free_hand_slot_delivers_original_then_burns_complete_copy(self):
        g = self.game(members=(DEMON,), hand=(STALKER,) + (YETI,) * 9)
        source = self.play(g)
        self.choose(g)
        original, copy = self.results(g, source)
        self.assertEqual((original.zone, copy.zone), (Zone.HAND, Zone.GRAVEYARD))
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertEqual(copy.cost, original.cost)
        self.portable(g)

    def test_actual_full_hand_burns_both_without_losing_gift_recipe(self):
        g = self.game(members=(DEMON,), mode='fill', hand=(STALKER,) + (YETI,) * 9)
        source = self.play(g)
        preview = g._frame.options[0].preview
        self.choose(g)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertEqual(len(self.results(g, source)), 2)
        for entity in self.results(g, source):
            self.assertEqual(entity.zone, Zone.GRAVEYARD)
            self.assertEqual((entity.cost, entity.attack, entity.max_health), (preview.cost, preview.attack, preview.max_health))

    def test_sweet_dreams_original_is_deck_top_and_copy_is_hand_with_same_enriched_stats(self):
        g = self.game(members=(DEMON,), seed=SEEDS['EDR_100t8'])
        source = self.play(g)
        self.assertEqual(g._frame.options[0].effects[0].selection.gift.id, 'EDR_100t8')
        self.choose(g)
        original, copy = self.results(g, source)
        self.assertEqual(g.state.players[1].deck[0], original.id)
        self.assertEqual(copy.zone, Zone.HAND)
        self.assertEqual((original.cost, copy.cost), (4, 4))
        self.assertEqual((original.attack, original.max_health, copy.attack, copy.max_health), (9, 9, 9, 9))
        self.portable(g)

    def test_older_same_name_hand_entity_is_never_used_as_copy_source(self):
        g = self.game(members=(DEMON,), hand=(STALKER, DEMON))
        older = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == DEMON)
        before = asdict(g.state.entities[older])
        source = self.play(g)
        self.choose(g)
        self.assertEqual(asdict(g.state.entities[older]), before)
        self.assertNotIn(older, {e.id for e in self.results(g, source)})

    def test_original_battlecry_repeat_has_two_choices_four_results_and_one_payment(self):
        g = self.game(members=(DEMON,), board=(P + 'twice',))
        source = self.play(g)
        self.choose(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.choose(g)
        self.assertEqual(len(self.results(g, source)), 4)
        self.assertEqual(len(g.state.battlecry_history), 2)
        self.assertEqual(g.state.players[1].mana, 36)
        self.portable(g)

    def test_natural_summon_does_not_run_native_battlecry_or_require_generated_pool(self):
        g = self.game(pool=False, context=None, hand=(P + 'summon',))
        self.play(g, P + 'summon')
        self.assertFalse(g.state.battlecry_history)
        self.assertIsNone(g.state.pending_choice)

    def test_empty_unknown_and_missing_context_have_the_original_explicit_boundaries(self):
        g = self.game(members=(YETI,))
        rng = g._rng.getstate()
        source = self.play(g)
        self.assertFalse(self.results(g, source))
        self.assertEqual(g._rng.getstate(), rng)
        self.assertEqual(g.state.players[1].mana, 36)
        for config in ({'members': (DEMON, UNKNOWN)}, {'pool': False}, {'context': None}):
            with self.subTest(config=config):
                g = self.game(**config)
                saved = g.snapshot()
                with patch.object(random.Random, 'randrange', side_effect=AssertionError('RNG before validation')):
                    with self.assertRaises(ResolutionError):
                        self.play(g)
                self.assertEqual(g.snapshot(), saved)

    def test_finite_copy_flag_rejects_unrelated_discovery_shapes_and_wrappers(self):
        native = DiscoverDarkGift(1, POOL_ID, QUERY, 1, gift_copy_to_hand=True)
        for changes in ({'gift_copy_to_hand': 1}, {'gift_copy_to_hand': None},
                        {'cost': CostSpec(delta=-1, card_types=(CardType.MINION,))}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(native, **changes)
        spec = DiscoverFromPool(1, POOL_ID, QUERY, source_id=1, gift_pool=dark_gift_pool(CTX.target_id, CTX.mode), gift_copy_to_hand=True)
        for changes in ({'gift_pool': None}, {'source_id': None}, {'temporary_until_turn': 1}, {'cost': CostSpec(delta=-1)},
                        {'discoveries': 2}, {'destination': 'board'}, {'gift_copy_to_hand': 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(spec, **changes)
        with self.assertRaises(ValueError):
            DiscoverForPlayFollowup(spec)

    def test_saved_nested_native_request_requires_explicit_boolean_flag_and_current_schema(self):
        g = self.game(members=(DEMON,), hand=(P + 'before',))
        self.play(g, P + 'before')
        self.portable(g)
        def nodes(node):
            if isinstance(node, dict):
                if node.get('type', '').endswith('.DiscoverDarkGift'):
                    yield node['fields']
                for v in node.values():
                    yield from nodes(v)
            elif isinstance(node, list):
                for v in node:
                    yield from nodes(v)
        for value in (1, None, 'true'):
            saved = deepcopy(g.snapshot())
            next(nodes(saved))['gift_copy_to_hand'] = value
            saved['state_hash'] = canonical_hash({k: v for k, v in saved.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
            with self.assertRaises(SnapshotError):
                Game.from_snapshot(saved, registry(*self.config))
        saved = g.snapshot()
        saved['schema_version'] = SNAPSHOT_SCHEMA_VERSION - 1
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, registry(*self.config))


if __name__ == '__main__':
    unittest.main()
