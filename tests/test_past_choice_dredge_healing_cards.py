from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.native_healing_conversion_cards import CARD as SANCTUM, PROGRAM as TURN_PROGRAM, register_native_healing_conversion_cards
from hs_sim.cards.past_choice_dredge_healing_cards import (
    BOTH, CHOICE_ONLY, DEPENDENCIES, DISCOVER_CHOICE, DRAW_CHOICE, KVALDIR, LEAVES,
    OPTION_RECORDS, PIPER, PROGRAM, REEF, SHARK, SHARK_CHOICE, SURVEYOR, TURTLE,
    TURTLE_CHOICE, load_batch, register_past_choice_dredge_healing_cards,
)
from hs_sim.engine import Attack, CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard, PlayerSetup, Registry, Scenario, TriggerSpec, UseHeroPower, UseLocation, Zone
from hs_sim.engine.effects import (
    AddToHand, ChangeControl, ChoiceOption, Damage, Destroy, Heal, HealBatch, InvokeBehavior,
    ModifyCost, RequestChoice, Silence,
)
from hs_sim.engine.errors import IllegalAction, ResolutionError, SnapshotError
from hs_sim.engine.model import CardClass, CardMetadata, CostSpec, DamageKind, HealingKind, PlayerEffectSpec, TargetMode, TargetSpec
from hs_sim.engine.next_healing_conversion import KIND, UNTIL_USED_KIND
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, ModifyStoredCost, MoveCard
from tools import card_batch as batch


P = 'test.k467.'
HERO, ENEMY, BEAST, MECH, OTHER, ALL, OFFCLASS, UNCOLLECTIBLE, UNKNOWN = (
    P+s for s in ('hero', 'enemy', 'beast', 'mech', 'other', 'all', 'offclass', 'uncollectible', 'unknown'))
NOOP, HEAL, TWICE, GROUP, EMPTY, ZERO, KILL, SILENCE, TAKE, WRONG, FAIL, WATCH, POWER, SUMMON = (
    P+s for s in ('noop', 'heal', 'twice', 'group', 'empty', 'zero', 'kill', 'silence', 'take', 'wrong', 'fail', 'watch', 'power', 'summon'))
FANDRAL, BRANN = 'OG_044', 'LOE_077'
REPRICE, LIFE = P+'reprice', P+'life'
CONTEXT = GenerationContext('k467-explicit-ordinary-and-past', 'experimental')


@lru_cache(None)
def complete_registry():
    return build_registry()


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = Registry('k467-' + mode)
    register_past_choice_dredge_healing_cards(r)
    register_native_healing_conversion_cards(r)
    for cid in (FANDRAL, BRANN):
        r.register_card(complete_registry().card(cid))
    r.register_card(CardDefinition(LIFE, LIFE, CardType.MINION, attack=2, health=12,
        keywords=(Keyword.LIFESTEAL, Keyword.CHARGE)))
    for cid, card_class in ((HERO, CardClass.DRUID), (ENEMY, CardClass.MAGE)):
        r.register_card(CardDefinition(cid, cid, CardType.HERO, health=80,
            metadata=CardMetadata(False, (card_class,), None)))
    for cid, tribes, card_class, collectible in (
            (BEAST, ('beast',), CardClass.DRUID, True), (MECH, ('mech',), CardClass.NEUTRAL, True),
            (OTHER, (), CardClass.NEUTRAL, True), (ALL, ('all',), CardClass.NEUTRAL, True),
            (OFFCLASS, ('beast',), CardClass.MAGE, True), (UNCOLLECTIBLE, ('beast',), CardClass.DRUID, False)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1, attack=2, health=12,
            metadata=CardMetadata(collectible, (card_class,), None, tribes=tribes)))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if mode != 'missing':
        members = () if mode == 'empty_pool' else (BEAST, ALL, OFFCLASS, OTHER, UNCOLLECTIBLE)
        if mode == 'unknown':
            r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 1,
                CardMetadata(True, (CardClass.DRUID,), None, tribes=('beast',))))
            members += (UNKNOWN,)
        r.register_pool(PoolDefinition('constructed.cards', 'k467-finite-full-domain', CONTEXT.target_id,
            CONTEXT.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    r.register_pool(PoolDefinition('constructed.past.cards', 'k467-four-historical-leaves', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid) for cid in LEAVES), complete=True))
    def hero(c):
        return c.state.players[c.player_id].hero_id
    def fail(c):
        raise ResolutionError('K467 deliberate late reaction failure')
    scripts = {
        NOOP: lambda c: (), HEAL: lambda c: (Heal(hero(c), 3, c.source_id, HealingKind.SPELL),),
        TWICE: lambda c: (Heal(hero(c), 3, c.source_id, HealingKind.SPELL), Heal(hero(c), 3, c.source_id, HealingKind.SPELL)),
        GROUP: lambda c: (HealBatch(tuple(Heal(c.state.players[p].hero_id, 3, c.source_id, HealingKind.SPELL) for p in (1, 2))),),
        EMPTY: lambda c: (HealBatch(()),), ZERO: lambda c: (Heal(hero(c), 0, c.source_id, HealingKind.SPELL),),
        KILL: lambda c: (Destroy(c.target_id, c.source_id),), SILENCE: lambda c: (Silence(c.target_id),),
        TAKE: lambda c: (ChangeControl(c.target_id, 2),),
        WRONG: lambda c: (AddPlayerEffect(c.player_id, PROGRAM, c.source_id),), FAIL: fail,
        SUMMON: lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(REEF),), SummonCause.capture(c)),),
        REPRICE: lambda c: tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]), CostSpec(delta=2), c.source_id)
            for i in c.state.players[c.player_id].deck),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            targeting=TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,)) if cid in (KILL, SILENCE, TAKE) else None))
    r.register_behavior(POWER, lambda c: (Heal(hero(c), 2, c.source_id, HealingKind.HERO_POWER),))
    r.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, cost=2, on_use=POWER))
    def watch(c):
        e = c.event
        if mode == 'full_hand' and e.kind == 'card_dredged':
            return (AddToHand(c.player_id, NOOP, c.source_id),)
        if (mode == 'fail' and e.kind in ('card_drawn', 'health_resolved', 'transformed') or
                mode == 'health_fail' and e.kind == 'health_resolved'):
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        waiting = mode == 'health_wait' and e.kind == 'player_effect_removed' or mode == 'transform_wait' and e.kind == 'transformed'
        options = (ChoiceOption('continue', 'Continue'), ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),)))
        if mode == 'dredge_wait' and e.kind == 'card_dredged':
            target = c.state.entities[e.target_id]
            options += (ChoiceOption('move', 'Move original card', (MoveCard(CardReference.capture(target), c.player_id, Zone.HAND, source_id=c.source_id),)),)
            waiting = True
        return (RequestChoice(c.player_id, options, c.source_id),) if waiting else ()
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.WEAPON, durability=50,
        triggers=tuple(TriggerSpec(e, WATCH) for e in ('card_drawn', 'health_resolved', 'transformed', 'card_dredged', 'player_effect_removed'))))
    r.validate()
    return r


class PastChoiceDredgeHealingTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), board=(), deck=(NOOP,)*8, *, mode='normal', enemy_hand=(), enemy_board=(), enemy_deck=(NOOP,)*8, hand_cap=None):
        self.mode = mode
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO, hand=hand, board=board, deck=deck, mana=10, max_mana=10,
                hero_power_card_id=POWER, weapon_card_id=WATCH if mode in ('fail', 'health_wait', 'transform_wait', 'dredge_wait', 'full_hand', 'health_fail') else None, hand_cap=hand_cap),
            PlayerSetup(ENEMY, hand=enemy_hand, board=enemy_board, deck=enemy_deck, mana=10, max_mana=10, hero_power_card_id=POWER)),
            seed=467, generation_context=CONTEXT), fixture(mode))

    def hp(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].health

    def programs(self, g, player=1):
        return [x for x in g.state.players[player].player_effects if x.spec_id == PROGRAM]

    def branch(self, g, cid, key):
        eid = self.entity(g, cid).id
        g.apply(PlayCard(1, eid, branch_id=key))
        return eid

    def dredged_option(self, g, entity_id):
        return next(o.id for o in g._frame.options if o.effects[0].card.entity_id == entity_id)

    def test_complete_eleven_client_rows_sixteen_primary_faces_and_explicit_missing_subfaces(self):
        d = load_batch(); rows = {x['record']['id']: x['record'] for x in d['dependencies']+d['evidence_only']}
        self.assertEqual((len(rows), len(d['official_observations'])), (11, 16))
        self.assertEqual(set(d['official_face_unavailable_ids']), {BOTH, DRAW_CHOICE, DISCOVER_CHOICE})
        hashes = {}
        for o in d['official_observations']:
            if o['response_file'] not in hashes:
                hashes[o['response_file']] = batch.sha(Path(o['response_file']))
            self.assertEqual(hashes[o['response_file']], o['response_sha256'])
            batch.check_face(rows[o['card_id']], o['face'], o['locale'])
        self.assertEqual(batch.sha(Path(d['source']['path'])), d['source']['sha256'])
        self.assertFalse(d['cn_calibrated']); self.assertFalse(d['formal_pool_complete'])

    def test_four_historical_roots_nine_definitions_and_nonphysical_option_records(self):
        r = fixture()
        self.assertTrue(all(c in r.cards for c in DEPENDENCIES))
        self.assertTrue(all(c not in r.cards for c in OPTION_RECORDS))
        self.assertTrue(all(r.card(c).choice_only and c not in r.pool_cards for c in CHOICE_ONLY))
        self.assertEqual(r.player_effect(PROGRAM).kind, UNTIL_USED_KIND)
        self.assertTrue(all(c in complete_registry().cards for c in DEPENDENCIES))

    def test_real_reef_both_manual_branches_transform_original_identity_and_pay_once(self):
        for branch, form, attack, health, keyword in ((SHARK_CHOICE, SHARK, 3, 1, Keyword.RUSH), (TURTLE_CHOICE, TURTLE, 1, 3, Keyword.TAUNT)):
            g = self.game((REEF,)); eid = self.branch(g, REEF, branch); e = g.state.entities[eid]
            self.assertEqual((e.card_id, e.attack, e.health), (form, attack, health))
            self.assertIn(keyword, e.keywords); self.assertEqual(g.state.players[1].mana, 9)
            self.assertEqual(len(g.state.play_history), 1)

    def test_real_fandral_accepts_exact_client_combined_form(self):
        g = self.game((REEF,), board=(FANDRAL,)); eid = self.branch(g, REEF, REEF+':combined'); e = g.state.entities[eid]
        self.assertEqual((e.card_id, e.attack, e.health), (BOTH, 3, 3))
        self.assertTrue({Keyword.RUSH, Keyword.TAUNT} <= set(e.keywords))

    def test_reef_illegal_branch_preserves_payment_rng_and_entity(self):
        g = self.game((REEF,)); snap = g.snapshot()
        with self.assertRaises(IllegalAction): self.branch(g, REEF, REEF+':combined')
        self.assertEqual(g.snapshot(), snap)

    def test_reef_ordinary_summon_keeps_unselected_native_one_one(self):
        g = self.game((SUMMON,)); self.play(g, SUMMON); e = self.entity(g, REEF, zone='board')
        self.assertEqual((e.attack, e.health, e.card_id), (1, 1, REEF))

    def test_reef_transform_wait_restores_original_form_and_finishes_once(self):
        g = self.game((REEF,), mode='transform_wait'); eid = self.branch(g, REEF, SHARK_CHOICE)
        self.assertIsNotNone(g.state.pending_choice); g = self.portable(g); self.choose(g)
        self.assertEqual(g.state.entities[eid].card_id, SHARK); self.assertEqual(len(g.state.play_history), 1)

    def test_reef_late_transform_failure_rolls_back_whole_real_play(self):
        g = self.game((REEF,), mode='fail'); snap = g.snapshot()
        with self.assertRaises(ResolutionError): self.branch(g, REEF, TURTLE_CHOICE)
        self.assertEqual(g.snapshot(), snap)

    def test_piper_draws_original_beast_or_all_entity_with_current_cost(self):
        for cid in (BEAST, ALL):
            g = self.game((PIPER, REPRICE), deck=(OTHER, cid)); original = self.entity(g, cid, zone='deck').id
            self.play(g, REPRICE)
            self.branch(g, PIPER, DRAW_CHOICE)
            self.assertIn(original, g.state.players[1].hand); self.assertEqual(len(g.state.draw_history), 1)
            self.assertEqual(g.state.entities[original].cost, 3)
            self.assertEqual(g.state.players[1].deck, [self.entity(g, OTHER, zone='deck').id])

    def test_piper_no_matching_card_and_empty_deck_skip_without_fatigue_or_rng(self):
        for deck in ((), (OTHER,)):
            g = self.game((PIPER,), deck=deck); rng = g.snapshot()['rng_state']
            self.branch(g, PIPER, DRAW_CHOICE)
            self.assertEqual(g.snapshot()['rng_state'], rng); self.assertFalse(g.state.draw_history)
            self.assertEqual(self.hp(g), 80)

    def test_piper_discovery_uses_full_current_class_and_neutral_beasts(self):
        g = self.game((PIPER,)); self.branch(g, PIPER, DISCOVER_CHOICE)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {BEAST, ALL})
        g = self.portable(g); key = g.state.pending_choice.options[0].id; self.choose(g, key)
        self.assertEqual(len(g.state.players[1].hand), 1); self.assertFalse(g.state.draw_history)

    def test_piper_actual_fandral_draw_and_discovery_are_separate_ordered_effects(self):
        g = self.game((PIPER,), board=(FANDRAL,), deck=(BEAST,)); original = self.entity(g, BEAST, zone='deck').id
        self.branch(g, PIPER, PIPER+':combined')
        self.assertEqual(g.state.players[1].hand, [original]); self.assertIsNotNone(g.state.pending_choice)
        self.choose(g, g.state.pending_choice.options[0].id)
        self.assertEqual((len(g.state.players[1].hand), len(g.state.draw_history)), (2, 1))

    def test_piper_missing_domain_and_unknown_eligible_member_fail_without_cropping(self):
        for mode in ('missing', 'unknown'):
            g = self.game((PIPER,), mode=mode); snap = g.snapshot()
            with self.assertRaises(ResolutionError): self.branch(g, PIPER, DISCOVER_CHOICE)
            self.assertEqual(g.snapshot(), snap)

    def test_piper_complete_empty_domain_finishes_without_wait_or_randomness(self):
        g = self.game((PIPER,), mode='empty_pool'); rng = g.snapshot()['rng_state']
        self.branch(g, PIPER, DISCOVER_CHOICE)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g.snapshot()['rng_state'], rng)

    def test_surveyor_bottom_three_selects_and_draws_exact_duplicate_mech(self):
        g = self.game((SURVEYOR,), deck=(OTHER, MECH, BEAST, MECH)); original = g.state.players[1].deck[-1]
        self.play(g, SURVEYOR)
        self.assertEqual({o.effects[0].card.entity_id for o in g._frame.options}, set(g.state.players[1].deck[-3:]))
        g = self.portable(g); self.choose(g, self.dredged_option(g, original))
        self.assertEqual(g.state.players[1].hand, [original]); self.assertEqual(len(g.state.draw_history), 1)
        self.assertNotEqual(original, self.entity(g, MECH, zone='deck').id)

    def test_surveyor_non_mech_only_reorders_and_empty_deck_has_no_fatigue(self):
        g = self.game((SURVEYOR,), deck=(MECH, OTHER)); original = self.entity(g, OTHER, zone='deck').id
        self.play(g, SURVEYOR); self.choose(g, self.dredged_option(g, original))
        self.assertEqual(g.state.players[1].deck[0], original); self.assertFalse(g.state.draw_history)
        g = self.game((SURVEYOR,), deck=()); rng = g.snapshot()['rng_state']; self.play(g, SURVEYOR)
        self.assertEqual((self.hp(g), g.state.pending_choice), (80, None)); self.assertEqual(g.snapshot()['rng_state'], rng)

    def test_surveyor_keeps_selected_mechs_original_current_cost(self):
        g = self.game((SURVEYOR, REPRICE), deck=(MECH,)); original = self.entity(g, MECH, zone='deck').id
        self.play(g, REPRICE); self.play(g, SURVEYOR); self.choose(g, self.dredged_option(g, original))
        self.assertEqual((g.state.players[1].hand, g.state.entities[original].cost), ([original], 3))

    def test_surveyor_all_tribes_is_mech_and_full_hand_burns_original_selected_card(self):
        g = self.game((SURVEYOR,), deck=(ALL,), hand_cap=1, mode='full_hand'); original = self.entity(g, ALL, zone='deck').id
        self.play(g, SURVEYOR); self.choose(g, self.dredged_option(g, original))
        self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.players[1].hand, [self.entity(g, NOOP).id]); self.assertEqual(len(g.state.draw_history), 1)

    def test_surveyor_original_draw_continuation_survives_wait_and_does_not_borrow_next_card(self):
        g = self.game((SURVEYOR,), deck=(OTHER, MECH), mode='dredge_wait'); original = self.entity(g, MECH, zone='deck').id
        self.play(g, SURVEYOR); self.choose(g, self.dredged_option(g, original)); self.assertIsNotNone(g.state.pending_choice)
        g = self.portable(g); self.choose(g, 'move')
        self.assertEqual(g.state.players[1].hand, [original]); self.assertFalse(g.state.draw_history)
        self.assertEqual(g.state.entities[g.state.players[1].deck[0]].card_id, OTHER)

    def test_surveyor_late_draw_failure_restores_original_dredge_choice_and_rng(self):
        g = self.game((SURVEYOR,), deck=(MECH,), mode='fail'); original = self.entity(g, MECH, zone='deck').id
        self.play(g, SURVEYOR); key = self.dredged_option(g, original); snap = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, key)
        self.assertEqual(g.snapshot(), snap)

    def test_actual_brann_gives_two_independent_dredge_menus_and_one_root_payment(self):
        g = self.game((SURVEYOR,), board=(BRANN,), deck=(MECH, MECH)); self.play(g, SURVEYOR)
        for _ in range(2):
            self.assertIsNotNone(g.state.pending_choice); self.choose(g, g.state.pending_choice.options[0].id)
        self.assertEqual((len(g.state.players[1].hand), len(g.state.draw_history), len(g.state.play_history)), (2, 2, 1))
        self.assertEqual(g.state.players[1].mana, 9)

    def test_kvaldir_real_battlecry_pays_once_and_converts_only_next_whole_effect(self):
        g = self.game((KVALDIR, TWICE)); self.play(g, KVALDIR); self.play(g, TWICE)
        self.assertEqual(self.hp(g), 80); self.assertFalse(self.programs(g)); self.assertEqual(g.state.players[1].mana, 9)

    def test_kvaldir_unconsumed_program_survives_multiple_owner_and_opponent_turns(self):
        g = self.game((KVALDIR, HEAL)); self.play(g, KVALDIR)
        for _ in range(4): g.apply(EndTurn(g.state.active_player))
        self.assertEqual(len(self.programs(g)), 1); g = self.portable(g); self.play(g, HEAL)
        self.assertEqual(self.hp(g), 77); self.assertFalse(self.programs(g))

    def test_kvaldir_death_silence_and_transfer_do_not_reassign_player_program(self):
        for action in (KILL, SILENCE, TAKE):
            g = self.game((KVALDIR, action, HEAL)); source = self.play(g, KVALDIR); self.play(g, action, source)
            self.assertEqual(len(self.programs(g)), 1); self.assertFalse(self.programs(g, 2))
            self.play(g, HEAL); self.assertEqual(self.hp(g), 77)

    def test_kvaldir_opponent_healing_does_not_consume_original_players_budget(self):
        g = self.game((KVALDIR, HEAL), enemy_hand=(HEAL,)); self.play(g, KVALDIR); g.apply(EndTurn(1))
        self.play(g, HEAL, player=2); self.assertEqual(self.hp(g, 2), 80); self.assertEqual(len(self.programs(g)), 1)
        g.apply(EndTurn(2)); self.play(g, HEAL); self.assertEqual(self.hp(g), 77)

    def test_kvaldir_cross_turn_whole_two_target_healing_consumes_once(self):
        g = self.game((KVALDIR, GROUP)); self.play(g, KVALDIR); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.play(g, GROUP); self.assertEqual((self.hp(g), self.hp(g, 2)), (77, 77)); self.assertFalse(self.programs(g))

    def test_kvaldir_stacked_battlecries_and_current_turn_program_consume_together_once(self):
        g = self.game((KVALDIR, HEAL), board=(BRANN, SANCTUM)); self.play(g, KVALDIR)
        g.apply(UseLocation(1, self.entity(g, SANCTUM, zone='board').id))
        self.assertEqual(len(self.programs(g)), 2); self.play(g, HEAL)
        self.assertEqual(self.hp(g), 77); self.assertFalse(g.state.players[1].player_effects)

    def test_only_old_turn_limited_program_expires_while_kvaldir_remains(self):
        g = self.game((KVALDIR, HEAL), board=(SANCTUM,)); self.play(g, KVALDIR)
        g.apply(UseLocation(1, self.entity(g, SANCTUM, zone='board').id)); g.apply(EndTurn(1))
        self.assertEqual([e.spec_id for e in g.state.players[1].player_effects], [PROGRAM])
        g.apply(EndTurn(2)); self.play(g, HEAL); self.assertEqual(self.hp(g), 77)

    def test_cross_turn_actual_hero_power_consumes_kvaldir_once(self):
        g = self.game((KVALDIR,)); self.play(g, KVALDIR); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_ids[0]))
        self.assertEqual(self.hp(g), 78); self.assertFalse(self.programs(g))

    def test_cross_turn_actual_lifesteal_restoration_converts_once_without_recursion(self):
        g = self.game((KVALDIR,), board=(LIFE,), enemy_board=(MECH,)); self.play(g, KVALDIR)
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        g.apply(Attack(1, self.entity(g, LIFE, zone='board').id, self.entity(g, MECH, 2, 'board').id))
        self.assertEqual(self.hp(g), 78); self.assertFalse(self.programs(g))
        self.assertEqual(self.entity(g, MECH, 2, 'board').health, 10)

    def test_empty_healing_preserves_budget_and_valid_zero_heal_consumes_it(self):
        g = self.game((KVALDIR, EMPTY, ZERO)); self.play(g, KVALDIR); self.play(g, EMPTY)
        self.assertEqual(len(self.programs(g)), 1); self.play(g, ZERO)
        self.assertFalse(self.programs(g)); self.assertEqual(self.hp(g), 80)

    def test_cross_turn_atomic_health_wait_sees_full_committed_batch_and_restores(self):
        g = self.game((KVALDIR, GROUP), mode='health_wait'); self.play(g, KVALDIR)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g, GROUP)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual((self.hp(g), self.hp(g, 2)), (77, 77))
        self.assertFalse(self.programs(g)); g = self.portable(g); self.choose(g)
        self.assertEqual((self.hp(g), self.hp(g, 2)), (77, 77))

    def test_cross_turn_late_health_failure_rolls_back_original_budget_and_payment(self):
        g = self.game((KVALDIR, HEAL), mode='health_fail'); self.play(g, KVALDIR); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        snap = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, HEAL)
        self.assertEqual(g.snapshot(), snap)

    def test_finite_new_kind_rejects_extra_powers_and_wrong_original_source(self):
        for kw in (dict(spell_damage=1), dict(duration=1), dict(triggers=(TriggerSpec('turn_started', NOOP),)), dict(next_turn_end=True)):
            with self.assertRaises(ValueError): PlayerEffectSpec(P+'bad', KVALDIR, kind=UNTIL_USED_KIND, **kw)
        g = self.game((WRONG,)); snap = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, WRONG)
        self.assertEqual(g.snapshot(), snap)

    def test_current_old_schema_is_explicitly_rejected_and_no_new_state_fields_leak(self):
        g = self.game((KVALDIR,)); self.play(g, KVALDIR); snap = g.snapshot(); old = deepcopy(snap); old['schema_version'] = 549
        with self.assertRaises(SnapshotError): Game.from_snapshot(old, fixture())
        self.assertEqual(g.snapshot(), snap); g = self.portable(g)
        for player in (1, 2):
            visible = json.dumps(g.for_player(player).observe()) + json.dumps(g.player_events(player))
            for key in ('source_allocation', 'health_rule', 'resolution_frame', 'rng_state'):
                self.assertNotIn('"'+key+'"', visible)


if __name__ == '__main__':
    unittest.main()
