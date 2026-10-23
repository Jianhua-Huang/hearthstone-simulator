from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.health_cards import SCHOOLS
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.past_one_cost_spell_consumer_cards import (
    BOOK, BURGLAR, COUNT_FIELD, CRYSTALSMITH, FROG, FROSTBREAKER, HERALD,
    LEAVES, PLUNDERER, THIEF, TRACKER, WINNER, load_batch,
)
from hs_sim.engine import (
    CardDefinition, CardType, CastSpell, EndTurn, Game, IllegalAction, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError, SpellSchool, TargetSpec, TriggerSpec, UseHeroPower, Zone,
)
from hs_sim.engine.effects import ChoiceOption, Damage, InvokeBehavior, RequestChoice, ReturnToHand, Silence
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.actions import action_from_dict
from hs_sim.engine.paid_body_retries import receipt_from_dict
from hs_sim.engine.model import CostSpec, DamageKind, TargetMode
from hs_sim.engine.player_target_inputs import canonical, capture, decode, validate_full_state
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from tools import card_batch as batch


P = 'test.k460.'
NOOP, ONE, TWO, SHADOW, FROST, AUTO, DISCOUNT, BOUNCE, FAIL, WATCH = (
    P+s for s in ('noop', 'one', 'two', 'shadow', 'frost', 'auto', 'discount', 'bounce', 'fail', 'watch'))
FIRE, ICE, SECRET, SECRET2, BOLT, WARLOCK, YETI, RAVEN, FLASHBACK = (
    'CORE_CS2_029', 'CORE_CS2_024', 'CORE_EX1_287', 'CORE_EX1_289', 'CORE_EX1_238',
    'CORE_CS2_065', 'CORE_CS2_182', 'KAR_300', 'TIME_711')
UNKNOWN = P+'unknown-mage'
UNKNOWN_OVERLOAD = 'AT_051'
POOL_CARDS = (FIRE, ICE, SECRET, SECRET2, BOLT, WARLOCK, YETI)
CONTEXT = GenerationContext('k460-explicit-spell-consumers', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry()
    missing = replace(r.card(FIRE), id=UNKNOWN, name=UNKNOWN,
        metadata=replace(r.card(FIRE).metadata, deck_identity=UNKNOWN))
    r.register_pool_card(PoolCard.from_definition(missing))
    raw = next(x['record'] for x in load_batch()['evidence_only'] if x['record']['id'] == UNKNOWN_OVERLOAD)
    if UNKNOWN_OVERLOAD not in r.pool_cards:
        r.register_pool_card(PoolCard(UNKNOWN_OVERLOAD, CardType.SPELL, raw['cost'],
            metadata_from_record(raw), SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL'))))
    members = () if mode == 'empty' else POOL_CARDS + (
        (UNKNOWN,) if mode == 'unknown' else (UNKNOWN_OVERLOAD,) if mode == 'unknown_overload' else ())
    if mode != 'unbound':
        r.register_pool(PoolDefinition('constructed.cards', 'explicit-spells-v1', CONTEXT.target_id,
            CONTEXT.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    r.register_pool(PoolDefinition('constructed.past.cards', 'explicit-spell-consumer-leaves-v1',
        CONTEXT.target_id, CONTEXT.mode, tuple(PoolMember(cid) for cid in LEAVES), complete=True))

    def fail(c):
        raise ResolutionError('K460 original late failure')

    def discount(c):
        target = next(c.state.entities[i] for i in c.state.players[c.player_id].deck
            if c.state.entities[i].card_id == TWO)
        return (ModifyStoredCost(CardReference.capture(target), CostSpec(set_to=1), c.source_id),)

    bodies = {NOOP: lambda c: (), ONE: lambda c: (), TWO: lambda c: (),
        SHADOW: lambda c: (), FROST: lambda c: (),
        AUTO: lambda c: (CastSpell(c.player_id, NOOP, c.source_id, targeting='explicit'),),
        DISCOUNT: discount, BOUNCE: lambda c: (ReturnToHand(c.target_id),), FAIL: fail}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            cost=1 if cid == ONE else 2 if cid == TWO else 0,
            spell_school=SpellSchool.SHADOW if cid == SHADOW else SpellSchool.FROST if cid == FROST else None,
            targeting=TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,)) if cid == BOUNCE else None))

    def watch(c):
        original = c.state.entities.get(c.event.source_id)
        source = None if original is None else original.card_id
        added = c.event.kind == 'card_added_to_hand' and source in (BOOK, BURGLAR, WINNER, THIEF, FROG)
        combo = c.event.kind == 'combo_started' and source == THIEF
        herald = c.event.kind == 'battlecry_started' and source == HERALD
        damage = c.event.kind == 'damage_dealt' and source in (HERALD, PLUNDERER)
        if mode == 'fail' and (added or combo or damage):
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        if not (mode == 'wait_combo' and combo or mode == 'wait_herald' and herald or mode == 'wait_hand' and added):
            return ()
        options = (ChoiceOption('continue', 'Continue'), ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),)))
        if herald:
            options += (ChoiceOption('silence', 'Silence accepted source', (Silence(c.event.source_id),)),)
        return (RequestChoice(c.player_id, options, c.source_id),)

    behavior = WATCH+'.'+mode
    r.register_behavior(behavior, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=40,
        triggers=tuple(TriggerSpec(e, behavior) for e in
            ('card_added_to_hand', 'combo_started', 'battlecry_started', 'damage_dealt'))
            if mode.startswith('wait_') or mode == 'fail' else ()))
    r.validate()
    return r


class PastOneCostSpellConsumerTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), board=(), *, deck=(), enemy_hand=(), enemy_board=(), enemy_deck=(), active=1, mode='normal'):
        self.mode = mode
        marker = (WATCH,) if mode.startswith('wait_') or mode == 'fail' else ()
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=marker+board, deck=deck,
            mana=10, max_mana=10, hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board, deck=enemy_deck,
                mana=10, max_mana=10, hero_power_card_id='HERO_08bp')),
            active_player=active, seed=460, generation_context=CONTEXT), fixture(mode))

    def pick(self, g):
        choice = g.state.pending_choice
        g.apply(SelectChoice(choice.player_id, choice.id, (choice.options[0].id,)))

    def count(self, g, player=1):
        return g.observe(player)['players'][player-1][COUNT_FIELD]

    def test_ten_complete_faces_and_full_ninety_eight_printed_overload_facts(self):
        d = load_batch(); self.assertEqual((len(d['dependencies']), len(d['official_observations']), len(d['evidence_only'])), (10, 20, 98))
        rows = {x['record']['id']: x['record'] for x in d['dependencies']}; hashes = {}
        for o in d['official_observations']:
            if o['response_file'] not in hashes: hashes[o['response_file']] = batch.sha(Path(o['response_file']))
            self.assertEqual(hashes[o['response_file']], o['response_sha256'])
            batch.check_face(rows[o['card_id']], o['face'], o['locale'])
        source = batch.read(Path(__file__).resolve().parents[1]/d['source']['path'])
        self.assertEqual(batch.sha(Path(__file__).resolve().parents[1]/d['source']['path']), d['source']['sha256'])
        self.assertEqual([x['id'] for x in source if type(x['tags'].get('OVERLOAD')) is int and x['tags']['OVERLOAD'] > 0], d['printed_overload_ids'])
        self.assertNotIn(FROG, d['printed_overload_ids'])

    def test_ten_native_hand_entries_pay_one_without_invented_battlecries_for_combos(self):
        for cid in LEAVES:
            g = self.game((cid,)); source = self.play(g, cid)
            self.assertEqual(g.state.players[1].mana, 9); self.assertIn(source, g.state.players[1].board)
            if g.state.pending_choice is not None: self.pick(g)
            if cid in (THIEF, PLUNDERER):
                self.assertFalse(g.state.combo_history); self.assertIsNone(g.registry.card(cid).battlecry)

    def test_book_generates_fixed_mage_spell_and_burglar_excludes_current_class_and_neutral(self):
        g = self.game((BOOK, BURGLAR)); self.play(g, BOOK); self.play(g, BURGLAR)
        cards = [g.state.entities[i].card_id for i in g.state.players[1].hand]
        self.assertIn(cards[0], (FIRE, ICE, SECRET, SECRET2)); self.assertIn(cards[1], (BOLT, WARLOCK))

    def test_winner_discovers_current_hero_secrets_and_preserves_private_offer(self):
        g = self.game((WINNER,)); self.play(g, WINNER)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {SECRET, SECRET2})
        self.assertNotIn(SECRET, json.dumps(g.for_player(2).observe()))
        g = self.portable(g); self.pick(g); self.assertEqual(len(g.state.players[1].hand), 1)

    def test_frog_intersects_printed_overload_identity_with_host_domain_without_paying_overload(self):
        g = self.game((FROG,)); self.play(g, FROG)
        self.assertEqual(self.entity(g, BOLT).card_id, BOLT)
        self.assertEqual(g.state.players[1].overload_owed, 0)

    def test_matching_unknown_mage_and_overload_candidates_fail_before_sampling_and_roll_back(self):
        for mode, card in (('unknown', BOOK), ('unknown_overload', FROG)):
            g = self.game((card,), mode=mode); before = g.snapshot()
            with self.assertRaises(ResolutionError): self.play(g, card)
            self.assertEqual(g.snapshot(), before)

    def test_empty_random_domain_does_not_consume_rng_and_unbound_domain_does_not_fall_back(self):
        g = self.game((BOOK,), mode='empty'); rng = g._rng.getstate(); self.play(g, BOOK)
        self.assertFalse(g.state.players[1].hand); self.assertEqual(g._rng.getstate(), rng)
        h = self.game((BOOK,), mode='unbound'); before = h.snapshot()
        with self.assertRaises(ResolutionError): self.play(h, BOOK)
        self.assertEqual(h.snapshot(), before)

    def test_book_hand_delivery_wait_restores_without_second_generation(self):
        g = self.game((BOOK,), mode='wait_hand'); self.play(g, BOOK)
        self.assertIsNotNone(g.state.pending_choice); rng = g._rng.getstate(); g = self.portable(g); self.choose(g)
        self.assertEqual(len(g.state.players[1].hand), 1); self.assertEqual(g._rng.getstate(), rng)

    def test_thief_first_card_does_not_discover_but_native_combo_does(self):
        g = self.game((THIEF,)); self.play(g, THIEF); self.assertIsNone(g.state.pending_choice)
        h = self.game((NOOP, THIEF)); self.play(h, NOOP); self.play(h, THIEF)
        self.assertTrue(h.state.combo_history); self.assertFalse(h.state.battlecry_history)
        self.assertTrue({o.card_id for o in h.state.pending_choice.options} <= {FIRE, ICE, SECRET, SECRET2})
        self.pick(h); self.assertEqual(len(h.state.players[1].hand), 1)

    def test_thief_combo_start_wait_then_discovery_each_restore_with_original_activation(self):
        g = self.game((NOOP, THIEF), mode='wait_combo'); self.play(g, NOOP); self.play(g, THIEF)
        self.assertEqual(g.state.pending_choice.options[0].id, 'continue')
        g = self.portable(g); self.choose(g); self.assertIsNotNone(g.state.pending_choice)
        self.pick(g); self.assertEqual(len(g.state.combo_history), 1); self.assertTrue(g.state.combo_history[0].completed)

    def test_tracker_draws_original_physical_one_cost_spell_and_leaves_others_ordered(self):
        g = self.game((TRACKER,), deck=(YETI, TWO, ONE, RAVEN)); original = self.entity(g, ONE, zone='deck').id
        self.play(g, TRACKER); self.assertIn(original, g.state.players[1].hand)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck], [YETI, TWO, RAVEN])

    def test_tracker_uses_current_stored_cost_and_retains_the_drawn_modification(self):
        g = self.game((DISCOUNT, TRACKER), deck=(TWO,)); original = self.entity(g, TWO, zone='deck').id
        self.play(g, DISCOUNT); self.play(g, TRACKER); self.assertIn(original, g.state.players[1].hand)
        self.assertEqual(quote_unselected_cost(g.state, g.registry, g.state.entities[original]).amount, 1)

    def test_tracker_no_matching_spell_does_not_draw_minion_or_cause_fatigue(self):
        for deck in ((), (YETI, TWO)):
            g = self.game((TRACKER,), deck=deck); hero = g.state.players[1].hero_id
            self.play(g, TRACKER); self.assertEqual(g.state.entities[hero].health, 30)
            self.assertEqual(len(g.state.players[1].deck), len(deck))

    def test_crystalsmith_checks_own_current_hand_shadow_spell(self):
        for held, expected in (((SHADOW,), (2, 3)), ((FROST,), (1, 2)), ((), (1, 2))):
            g = self.game((CRYSTALSMITH,)+held); source = self.play(g, CRYSTALSMITH)
            self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health), expected)
        h = self.game((CRYSTALSMITH,), enemy_hand=(SHADOW,)); source = self.play(h, CRYSTALSMITH)
        self.assertEqual(h.state.entities[source].attack, 1)

    def test_frostbreaker_counts_physical_frost_spells_not_unique_faces_or_opponent_hand(self):
        g = self.game((FROSTBREAKER, FROST, FROST, SHADOW), enemy_hand=(FROST,))
        source = self.play(g, FROSTBREAKER); self.assertEqual(g.state.entities[source].attack, 3)
        self.assertEqual(g.state.entities[source].max_health, 2)

    def test_herald_has_no_target_before_two_real_spell_plays_then_deals_two(self):
        g = self.game((HERALD,)); source = self.play(g, HERALD)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)
        h = self.game((NOOP, NOOP, HERALD)); self.play(h, NOOP); self.play(h, NOOP)
        before = h.snapshot()
        with self.assertRaises(IllegalAction): self.play(h, HERALD)
        self.assertEqual(h.snapshot(), before)
        self.play(h, HERALD, h.state.players[2].hero_id)
        self.assertEqual(h.state.entities[h.state.players[2].hero_id].health, 28)

    def test_herald_count_is_at_least_two_and_automatic_cast_is_not_another_hand_play(self):
        g = self.game((NOOP, NOOP, NOOP, HERALD))
        for _ in range(3): self.play(g, NOOP)
        self.play(g, HERALD, g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28)
        h = self.game((AUTO, HERALD)); self.play(h, AUTO); self.assertEqual(self.count(h), 1)
        self.play(h, HERALD); self.assertEqual(h.state.entities[h.state.players[2].hero_id].health, 30)

    def test_countered_spell_is_still_a_real_hand_play_for_herald(self):
        g = self.game((NOOP, NOOP, HERALD), enemy_hand=(SECRET,), active=2)
        self.play(g, SECRET, player=2); g.apply(EndTurn(2)); self.play(g, NOOP); self.play(g, NOOP)
        self.assertEqual(self.count(g), 2); self.play(g, HERALD, g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28)

    def test_spell_count_projection_is_own_only_and_clears_on_turn_transition(self):
        g = self.game((NOOP, RAVEN)); self.play(g, NOOP); self.play(g, RAVEN)
        self.assertEqual(self.count(g), 1); self.assertNotIn(COUNT_FIELD, g.observe(2)['players'][0])
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id, g.state.players[2].hero_id))
        self.assertEqual(self.count(g), 1); g.apply(EndTurn(1)); self.assertEqual(self.count(g), 0)

    def test_spell_count_input_rejects_missing_bool_negative_overbound_and_other_viewer(self):
        g = self.game((HERALD,)); source = g._state.entities[g._state.players[1].hand[0]]
        proof = capture(g, g._state, source)
        mutations = [lambda v:v['players'][0].pop(COUNT_FIELD), lambda v:v['players'][1].update({COUNT_FIELD:0})]
        mutations += [lambda v, x=x:v['players'][0].update({COUNT_FIELD:x}) for x in (None, True, -1, 1, '0')]
        for mutate in mutations:
            value = json.loads(proof.observation_json); mutate(value)
            with self.assertRaises(ValueError): decode(replace(proof, observation_json=canonical(value)))

    def test_within_bound_forged_spell_count_cannot_replace_complete_payment_projection(self):
        g = self.game((NOOP, RAVEN, HERALD)); self.play(g, NOOP); self.play(g, RAVEN)
        source = g._state.entities[g._state.players[1].hand[0]]; proof = capture(g, g._state, source)
        for count in (0, 2):
            value = json.loads(proof.observation_json); value['players'][0][COUNT_FIELD] = count
            changed = replace(proof, observation_json=canonical(value)); decode(changed)
            with self.assertRaises(ValueError): validate_full_state(g._state, g.registry, source, changed)

    def test_rehashed_closed_receipt_rejects_forged_original_spell_count(self):
        from test_player_target_inputs import registry as paid_registry, command
        r = paid_registry(); r.register_card(CardDefinition(P+'prior_spell', P+'prior_spell', CardType.SPELL))
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=(P+'prior_spell', 'unit'), board=('tiny', 'big'), mana=6, max_mana=6),
            PlayerSetup('hero', board=('tiny', 'big'))), seed=460), r)
        g.apply(PlayCard(1, g.state.players[1].hand[0]))
        self.assertTrue(g.for_player(1).submit(command(g))['accepted'])
        self.assertEqual(Game.from_snapshot(g.snapshot(), r).snapshot(), g.snapshot())
        valid = g.snapshot()['state']['play_history'][-1]['body_targets']
        self.assertEqual(valid['action']['target_ids'], [])
        for invalid in (None, False, {}, ''):
            broken = deepcopy(valid); broken['action']['target_ids'] = invalid
            with self.assertRaises(ValueError): receipt_from_dict(broken)
        saved = deepcopy(g.snapshot()); receipt = saved['state']['play_history'][-1]['body_targets']; proof = receipt['origin']['observation']
        value = json.loads(proof['observation_json']); value['players'][0][COUNT_FIELD] = 0; proof['observation_json'] = canonical(value)
        receipt['origin_hash'] = canonical_hash(receipt['origin'])
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as caught: Game.from_snapshot(saved, r)
        self.assertNotIn('digest mismatch', str(caught.exception))

    def test_internal_empty_arrow_sentinel_does_not_relax_public_command_arrays(self):
        with self.assertRaises(ValueError):
            action_from_dict({'type':'play_card', 'player_id':1, 'entity_id':1, 'target_ids':[]})
        action = action_from_dict({'type':'play_card', 'player_id':1, 'entity_id':1, 'target_id':7, 'target_ids':[7, 3]})
        self.assertEqual(action.target_ids, (7, 3))

    def test_herald_accepted_body_survives_silence_and_waiting_restore(self):
        g = self.game((NOOP, NOOP, HERALD), mode='wait_herald'); self.play(g, NOOP); self.play(g, NOOP)
        self.play(g, HERALD, g.state.players[2].hero_id); self.assertIsNotNone(g.state.pending_choice)
        g = self.portable(g); self.choose(g, 'silence')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28)

    def test_plunderer_first_play_has_no_combo_or_required_arrow(self):
        g = self.game((PLUNDERER,), enemy_board=(YETI,)); self.play(g, PLUNDERER)
        self.assertFalse(g.state.combo_history); self.assertEqual(self.entity(g, YETI, player=2, zone='board').health, 5)

    def test_plunderer_counts_original_other_plays_when_same_entity_is_replayed(self):
        g = self.game((NOOP, PLUNDERER, BOUNCE), enemy_board=(YETI,)); self.play(g, NOOP)
        target = self.entity(g, YETI, player=2, zone='board').id
        source = self.play(g, PLUNDERER, target); self.play(g, BOUNCE, source); self.play(g, PLUNDERER, target)
        self.assertEqual(g.state.entities[target].health, 1)
        self.assertEqual([e.amount for e in g.events if e.kind == 'damage_dealt' and e.source_id == source], [1, 3])
        self.assertEqual(len(g.state.combo_history), 2)

    def test_generation_damage_and_combo_late_failures_restore_whole_action(self):
        for card in (BOOK, THIEF, HERALD, PLUNDERER):
            g = self.game((NOOP, NOOP, card), enemy_board=(YETI,), mode='fail')
            self.play(g, NOOP); self.play(g, NOOP); before = g.snapshot()
            target = g.state.players[2].hero_id if card == HERALD else self.entity(g, YETI, player=2, zone='board').id if card == PLUNDERER else None
            with self.assertRaisesRegex(ResolutionError, 'K460 original late failure'): self.play(g, card, target)
            self.assertEqual(g.snapshot(), before)

    def test_discovery_delivery_failure_restores_the_waiting_selection(self):
        g = self.game((WINNER,), mode='fail'); self.play(g, WINNER); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K460 original late failure'): self.pick(g)
        self.assertEqual(g.snapshot(), before)

    def test_real_flashback_uses_normal_summons_without_combo_or_battlecry(self):
        g = self.game((FLASHBACK,)); self.play(g, FLASHBACK)
        self.assertEqual(len(g.state.players[1].board), 2); self.assertFalse(g.state.battlecry_history)
        self.assertFalse(g.state.combo_history); self.assertFalse(g.state.players[1].hand)

    def test_batch_does_not_bind_a_production_past_or_standard_pool(self):
        r = build_registry(); self.assertNotIn('constructed.past.cards', r.pools); self.assertNotIn('constructed.cards', r.pools)


if __name__ == '__main__':
    unittest.main()
