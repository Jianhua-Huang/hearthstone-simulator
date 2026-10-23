"""Finley's original skill offers, selection delivery and shared slot lifecycle."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
from random import Random
from pathlib import Path
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards.past_basic_hero_power_discovery_card import (
    CARD, POWERS, load_batch, register_past_basic_hero_power_discovery_card)
from hs_sim.cards.native_origin_stone_cards import REWARD as STONE
from hs_sim.cards.native_past_entry_grant_cards import FLASHBACK, POOL_ID
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, IllegalAction, Keyword, PlayerSetup, Registry, Scenario, SelectChoice, UseHeroPower, Zone)
from hs_sim.engine.effects import (ChoiceOption, Destroy, InvokeBehavior, ReplaceHeroPower,
    RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.hero_power_discovery import (DiscoverHeroPower, HeroPowerDiscoveryOffer,
    HeroPowerDiscoveryProfile, InstallDiscoveredHeroPower, candidates, options_for,
    power_class, validate_offer_data)
from hs_sim.engine.hero_powers import AddHeroPower
from hs_sim.engine.model import TargetMode, TargetSpec, TriggerSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember, sample_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial

P = 'k471.'
NOOP, SUMMON, ADD, FAIL, WATCH, KILL, SILENCE, BOUNCE, UNKNOWN, NEUTRAL, MULTI = (
    P+s for s in ('noop', 'summon', 'add', 'fail', 'watch', 'kill', 'silence', 'bounce', 'unknown', 'neutral', 'multi'))
CONTEXT = GenerationContext('k471-explicit-finite-past', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry()
    r._version = 'k471-skill-fixture-'+mode
    def fail(c):
        raise ResolutionError('K471 deliberate original discovery reaction failure')
    scripts = {
        NOOP: lambda c: (), FAIL: fail,
        SUMMON: lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(CARD),), SummonCause.capture(c)),),
        ADD: lambda c: (AddHeroPower(c.player_id, 'HERO_05bp', c.source_id),),
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        SILENCE: lambda c: (Silence(c.target_id),), BOUNCE: lambda c: (ReturnToHand(c.target_id),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,))
                if cid in (KILL, SILENCE, BOUNCE) else None))
    for cid, meta in ((UNKNOWN, None), (NEUTRAL, META),
            (MULTI, replace(META, classes=(CardClass.MAGE, CardClass.WARRIOR)))):
        r.register_card(CardDefinition(cid, cid, CardType.HERO_POWER, cost=2, on_use=NOOP, metadata=meta))
    def watch(c):
        e = c.event
        if mode == 'source_leaves' and e.kind == 'choice_requested':
            return (Destroy(e.source_id, c.source_id),
                ReplaceHeroPower(c.player_id, 'HERO_01bp', source_id=c.source_id))
        if mode == 'fail' and e.kind == 'hero_power_replaced':
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        if mode == 'completion_fail' and e.kind == 'card_discovered':
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        if mode == 'replace_wait' and e.kind == 'hero_power_replaced':
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
        return ()
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=10, metadata=META,
        triggers=tuple(TriggerSpec(event, WATCH) for event in ('choice_requested', 'hero_power_replaced', 'card_discovered'))))
    r.register_pool(PoolDefinition(POOL_ID, 'k471-only-finley', CONTEXT.target_id, CONTEXT.mode,
        (PoolMember(CARD),), complete=True))
    r.validate()
    return r


def seed_for(card_id, current='HERO_08bp'):
    r = fixture(); excluded = power_class(r, current) if current else None
    rows = tuple(PoolMember(cid) for cid in sorted(POWERS) if power_class(r, cid) != excluded)
    return next(seed for seed in range(1000)
        if card_id in sample_candidates(Random(seed), rows, 3, replacement=False))


class PastBasicHeroPowerDiscoveryTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), *, power='HERO_08bp', mode='normal', board=(), weapon=None, seed=471, enemy_hand=()):
        self.mode = mode
        if mode != 'normal': board = (*board, WATCH)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hero_power_card_id=power, hand=hand, board=board,
                weapon_card_id=weapon, deck=(NOOP,)*8, mana=20, max_mana=20, mana_cap=20),
            PlayerSetup('HERO_04', hero_power_card_id='HERO_04bp', hand=enemy_hand,
                deck=(NOOP,)*8, mana=20, max_mana=20, mana_cap=20)), seed=seed,
            generation_context=CONTEXT), fixture(mode))

    def power(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_power_id]

    def use(self, g, player=1, target=None):
        g.apply(UseHeroPower(player, self.power(g, player).id, target))

    def offer(self, g):
        return g._frame.options[0].effects[0].offer

    def pick(self, g, cid=None):
        cid = cid or g.state.pending_choice.options[0].id
        self.choose(g, cid)
        return cid

    def test_twelve_complete_rows_two_full_parent_faces_and_eleven_exact_children(self):
        data = load_batch(); raw = data['dependencies'][0]['record']
        self.assertEqual(len(data['existing_dependencies']), 11)
        self.assertEqual(len(data['official_observations']), 2)
        self.assertEqual(batch.sha(data['source']['path']), data['source']['sha256'])
        dbfs = [row['record']['dbf_id'] for row in data['existing_dependencies']]
        for o in data['official_observations']:
            self.assertEqual(batch.sha(o['response_file']), o['response_sha256'])
            batch.check_face(raw, o['face'], o['locale'])
            self.assertEqual(o['face']['childIds'], dbfs)
        for cid in POWERS:
            self.assertEqual(batch.canonical(asdict(fixture().card(cid))), data['existing_power_definition_pins'][cid])
        self.assertFalse(data['child_primary_faces_observed']); self.assertFalse(data['cn_calibrated'])

    def test_real_hand_entry_pays_once_and_offers_three_distinct_eligible_skills(self):
        g = self.game((CARD,)); old = self.power(g).id; source = self.play(g, CARD)
        offer = self.offer(g)
        self.assertEqual(g.state.players[1].mana, 19); self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual(self.power(g).id, old)
        self.assertEqual(offer.request.source_id, source)
        self.assertEqual(len(offer.eligible), 10); self.assertEqual(len(set(offer.offered)), 3)
        self.assertNotIn('HERO_08bp', offer.eligible)
        self.assertEqual(tuple(o.card_id for o in g.state.pending_choice.options), offer.offered)

    def test_captured_current_skill_class_decides_exclusion_instead_of_hero_class(self):
        g = self.game((CARD,), power='HERO_01bp'); self.play(g, CARD); offer = self.offer(g)
        self.assertNotIn('HERO_01bp', offer.eligible); self.assertIn('HERO_08bp', offer.eligible)
        self.assertEqual(g.state.players[1].hero_class, CardClass.MAGE)

    def test_upgraded_skill_excludes_its_printed_class_basic_skill(self):
        g = self.game((CARD,), power='HERO_01bp2'); self.play(g, CARD)
        self.assertNotIn('HERO_01bp', self.offer(g).eligible)
        self.assertEqual(len(self.offer(g).eligible), 10)

    def test_known_special_priest_skill_excludes_priest_without_changing_hero_class(self):
        g = self.game((CARD,), power='EDR_449p'); self.play(g, CARD)
        self.assertNotIn('HERO_09bp', self.offer(g).eligible)
        self.assertIn('HERO_08bp', self.offer(g).eligible)

    def test_demon_hunter_and_death_knight_are_actual_family_members(self):
        g = self.game((CARD,)); self.play(g, CARD)
        self.assertTrue({'HERO_10bp', 'HERO_11bp'} <= set(self.offer(g).eligible))

    def test_empty_primary_slot_keeps_all_eleven_choices_eligible(self):
        g = self.game((CARD,), power=None); self.play(g, CARD)
        self.assertEqual(set(self.offer(g).eligible), set(POWERS))
        chosen = self.pick(g); self.assertEqual(self.power(g).card_id, chosen)

    def test_known_neutral_skill_does_not_exclude_a_playable_class(self):
        g = self.game((CARD,), power=NEUTRAL); self.play(g, CARD)
        self.assertEqual(set(self.offer(g).eligible), set(POWERS))

    def test_unknown_current_skill_class_fails_explicitly_and_rolls_back_before_rng(self):
        g = self.game((CARD,), power=UNKNOWN); before = g.snapshot()
        with self.assertRaises((ResolutionError, UnsupportedDefinitionError)):
            self.play(g, CARD)
        self.assertEqual(g.snapshot(), before)

    def test_multiclass_current_skill_is_not_silently_guessed(self):
        g = self.game((CARD,), power=MULTI); before = g.snapshot()
        with self.assertRaises((ResolutionError, UnsupportedDefinitionError)):
            self.play(g, CARD)
        self.assertEqual(g.snapshot(), before)

    def test_missing_eligible_definition_fails_before_any_sampling_or_payment_commit(self):
        g = self.game((CARD,)); before = g.snapshot(); original = g.registry.card
        def lookup(cid):
            if cid == 'HERO_10bp': raise UnsupportedDefinitionError('K471 missing eligible skill')
            return original(cid)
        with patch.object(g.registry, 'card', side_effect=lookup):
            with self.assertRaises((ResolutionError, UnsupportedDefinitionError)):
                self.play(g, CARD)
        self.assertEqual(g.snapshot(), before)

    def test_exact_uniform_draw_is_replayed_locally_and_preserved_in_every_branch(self):
        g = self.game((CARD,)); self.play(g, CARD); offer = self.offer(g)
        local = Random(); local.setstate(offer.rng_before)
        expected = sample_candidates(local, tuple(PoolMember(cid) for cid in offer.eligible), 3, replacement=False)
        self.assertEqual((expected, local.getstate()), (offer.offered, offer.rng_after))
        self.assertEqual(g._rng.getstate(), offer.rng_after)
        for option in g._frame.options:
            self.assertEqual(option.effects[0].offer, offer)

    def test_selection_installs_a_fresh_skill_without_hand_delivery_or_second_payment(self):
        g = self.game((CARD,)); old = self.power(g).id; self.play(g, CARD); rng = g.snapshot()['rng_state']
        chosen = self.pick(g)
        self.assertEqual((self.power(g).card_id, g.state.players[1].mana), (chosen, 19))
        self.assertNotEqual(self.power(g).id, old); self.assertEqual(g.state.entities[old].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.players[1].hand, [])
        self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertFalse(any(e.kind == 'card_added_to_hand' for e in g.events))

    def test_generic_card_discovery_cannot_claim_a_skill_without_original_native_recipe(self):
        from hs_sim.engine.card_discoveries import validate_offered_faces
        from hs_sim.engine.model import ChoiceResult
        g = self.game((CARD,)); self.play(g, CARD); choice = g.state.pending_choice
        result = ChoiceResult(choice, (choice.options[0].id,))
        with self.assertRaisesRegex(ValueError, 'typed original skill menu'):
            validate_offered_faces(result, g.registry)

    def test_discovery_completion_identifies_the_actual_installed_skill_allocation(self):
        from hs_sim.engine.discovery_delivery import original_recipient
        g = self.game((CARD,)); self.play(g, CARD); self.pick(g)
        event = next(e for e in g.events if e.kind == 'card_discovered')
        fact = original_recipient(g.state, event)
        self.assertEqual((fact.entity_id, fact.card_id, fact.kind, fact.zone, fact.controller),
            (self.power(g).id, self.power(g).card_id, CardType.HERO_POWER, Zone.HERO_POWER, 1))

    def test_new_mage_skill_can_be_used_immediately_with_original_targeting_and_cost(self):
        g = self.game((CARD,), power='HERO_01bp', seed=seed_for('HERO_08bp', 'HERO_01bp'))
        self.play(g, CARD); self.pick(g, 'HERO_08bp'); self.use(g, target=g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 29)
        self.assertEqual(g.state.players[1].mana, 17)

    def test_new_demon_claws_keeps_its_one_mana_cost_and_original_hero_buff(self):
        g = self.game((CARD,), seed=seed_for('HERO_10bp')); self.play(g, CARD); self.pick(g, 'HERO_10bp'); self.use(g)
        self.assertEqual(g.state.players[1].mana, 18)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack, 1)

    def test_new_death_knight_skill_uses_the_existing_charging_ghoul_lifecycle(self):
        g = self.game((CARD,), seed=seed_for('HERO_11bp')); self.play(g, CARD); self.pick(g, 'HERO_11bp'); self.use(g)
        ghoul = g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual((ghoul.attack, ghoul.health), (1, 1)); self.assertIn(Keyword.CHARGE, ghoul.keywords)
        identity = ghoul.id; g.apply(EndTurn(1)); self.assertEqual(g.state.entities[identity].zone, Zone.GRAVEYARD)

    def test_used_old_skill_does_not_spend_new_physical_skill_use(self):
        g = self.game((CARD,), seed=seed_for('HERO_01bp')); self.use(g, target=g.state.players[2].hero_id)
        self.play(g, CARD); self.pick(g, 'HERO_01bp'); self.use(g)
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn, 2)
        self.assertEqual(self.power(g).uses_this_turn, 1)

    def test_primary_replacement_keeps_additional_skill_identity(self):
        g = self.game((ADD, CARD)); self.play(g, ADD); extra = tuple(g.state.players[1].additional_hero_power_ids)
        self.play(g, CARD); self.pick(g)
        self.assertEqual(tuple(g.state.players[1].additional_hero_power_ids), extra)
        self.assertEqual(g.state.entities[extra[0]].card_id, 'HERO_05bp')

    def test_skill_installation_needs_no_hand_capacity(self):
        g = self.game((CARD,)+(NOOP,)*9); self.play(g, CARD); self.pick(g)
        self.assertEqual(len(g.state.players[1].hand), 9)
        self.assertEqual(len(g.state.card_discovery_history), 1)

    def test_full_board_does_not_block_installing_a_nonsummoning_skill(self):
        g = self.game((CARD,), board=('CS2_101t',)*6, power='HERO_01bp',
            seed=seed_for('HERO_08bp', 'HERO_01bp'))
        self.play(g, CARD); self.pick(g, 'HERO_08bp'); self.use(g, target=g.state.players[2].hero_id)
        self.assertEqual(len(g.state.players[1].board), 7)

    def test_full_board_still_blocks_the_original_summoning_skill_before_payment(self):
        g = self.game((CARD,), board=('CS2_101t',)*6, seed=seed_for('HERO_11bp'))
        self.play(g, CARD); self.pick(g, 'HERO_11bp'); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_bad_or_empty_selection_keeps_the_same_paid_waiting_boundary(self):
        g = self.game((CARD,)); self.play(g, CARD); before = g.snapshot(); choice = g.state.pending_choice
        for selected in ((), ('not-offered',)):
            with self.assertRaises(IllegalAction): g.apply(SelectChoice(1, choice.id, selected))
            self.assertEqual(g.snapshot(), before)

    def test_choice_restore_clone_and_replay_keep_exact_offers_and_resume_the_same_skill(self):
        g = self.game((CARD,)); self.play(g, CARD); expected = self.offer(g).offered
        g = self.portable(g); self.assertEqual(self.offer(g).offered, expected)
        self.pick(g, expected[-1]); self.assertEqual(self.power(g).card_id, expected[-1])
        self.portable(g)

    def test_wait_after_installation_keeps_original_recipient_and_continues_discovery_once(self):
        g = self.game((CARD,), mode='replace_wait'); self.play(g, CARD); chosen = self.pick(g)
        self.assertIsNotNone(g.state.pending_choice); installed = self.power(g).id
        g = self.portable(g); self.choose(g)
        self.assertEqual((self.power(g).id, self.power(g).card_id), (installed, chosen))
        self.assertEqual(sum(e.kind == 'card_discovered' for e in g.events), 1)

    def test_late_installation_failure_restores_original_paid_menu_and_rng(self):
        g = self.game((CARD,), mode='fail'); self.play(g, CARD); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g)
        self.assertEqual(g.snapshot(), before)

    def test_completion_failure_restores_selection_delivery_and_original_skill(self):
        g = self.game((CARD,), mode='completion_fail'); self.play(g, CARD); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g)
        self.assertEqual(g.snapshot(), before)

    def test_source_and_primary_can_change_after_offer_without_rematching_or_replacing_extra_slots(self):
        g = self.game((CARD,), mode='source_leaves'); source = self.play(g, CARD); expected = self.offer(g).offered
        chosen = self.pick(g, expected[-1])
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(self.power(g).card_id, chosen)
        self.assertEqual(g.state.card_discovery_history[-1].result.selected[0].card_id, chosen)

    def test_origin_stone_ignores_real_hero_power_discovery_without_wearing(self):
        g = self.game((CARD,), weapon=STONE); weapon = g.state.players[1].weapon_id
        self.play(g, CARD); chosen = self.pick(g)
        self.assertEqual(self.power(g).card_id, chosen)
        self.assertEqual(g.state.entities[weapon].durability, 8)
        self.assertEqual(g.state.players[1].weapon_id, weapon)

    def test_ordinary_summon_and_real_flashback_do_not_run_finley_battlecry(self):
        for hand in ((SUMMON,), (NOOP, FLASHBACK)):
            g = self.game(hand); old = self.power(g).id
            for cid in hand: self.play(g, cid)
            self.assertIsNone(g.state.pending_choice); self.assertEqual(self.power(g).id, old)
            self.assertEqual(len(g.state.card_discovery_history), 0)

    def test_source_silence_and_death_after_selection_do_not_revoke_new_skill(self):
        for cid in (SILENCE, KILL):
            g = self.game((CARD, cid)); source = self.play(g, CARD); self.pick(g); installed = self.power(g).id
            self.play(g, cid, source); self.assertEqual(self.power(g).id, installed); self.portable(g)

    def test_replaying_finley_uses_the_new_current_class_and_a_fresh_discovery(self):
        g = self.game((CARD, BOUNCE)); source = self.play(g, CARD); first = self.pick(g)
        self.play(g, BOUNCE, source); self.play(g, CARD)
        self.assertNotIn(first, self.offer(g).eligible)
        second = self.pick(g); self.assertEqual(self.power(g).card_id, second)
        self.assertEqual(len(g.state.card_discovery_history), 2)

    def test_opponent_play_uses_its_actual_primary_skill_and_choice_owner(self):
        g = self.game(enemy_hand=(CARD,)); original = self.power(g).id; g.apply(EndTurn(1))
        self.play(g, CARD, player=2)
        self.assertEqual(g.state.pending_choice.player_id, 2)
        self.assertNotIn('HERO_04bp', self.offer(g).eligible)
        chosen = self.pick(g); self.assertEqual(self.power(g, 2).card_id, chosen)
        self.assertEqual(self.power(g).id, original)

    def test_complete_offer_rejects_truncated_candidates_offers_and_rng(self):
        g = self.game((CARD,)); self.play(g, CARD); offer = self.offer(g)
        for changes in (dict(eligible=offer.eligible[:-1]), dict(offered=offer.offered[:-1]),
                dict(offered=offer.offered[::-1]), dict(rng_after=offer.rng_before)):
            try:
                forged = replace(offer, **changes)
            except ValueError:
                continue
            with self.assertRaises(ValueError): validate_offer_data(g.state, g.registry, forged)
        wrong = replace(offer, previous_power=None)
        with self.assertRaisesRegex(ValueError, 'complete original class exclusion'):
            validate_offer_data(g.state, g.registry, wrong)

    def test_profile_rejects_duplicate_class_unknown_member_and_non_power_faces(self):
        with self.assertRaises(ValueError): HeroPowerDiscoveryProfile(CARD, (POWERS[0], POWERS[0]))
        from hs_sim.engine.hero_power_discovery import validate_profile
        for powers in (('HERO_01bp', 'HERO_01bp2'), (CARD,), ('missing.k471.power',)):
            with self.assertRaises((ValueError, UnsupportedDefinitionError)):
                validate_profile(fixture(), HeroPowerDiscoveryProfile(CARD, powers))

    def test_empty_known_eligible_family_is_an_rng_free_noop(self):
        source = P+'single-family-source'; r = Registry('k471-generic-single-class-family')
        for cid in ('HERO_08', 'HERO_08bp'):
            card = fixture().card(cid)
            if card.on_use: r.register_behavior(card.on_use, fixture().behavior(card.on_use))
            r.register_card(card)
        r.register_behavior(source, lambda c: (DiscoverHeroPower(c.player_id, c.source_id, source),))
        r.register_card(CardDefinition(source, source, CardType.MINION, cost=1, health=1,
            battlecry=source, metadata=META))
        r.register_hero_power_discovery_profile(HeroPowerDiscoveryProfile(source, ('HERO_08bp',)))
        g = Game.from_scenario(Scenario((PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp',
            hand=(source,), mana=5, max_mana=5), PlayerSetup('HERO_08')), seed=471), r)
        before = g._rng.getstate(); old = self.power(g).id; self.play(g, source)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g._rng.getstate(), before)
        self.assertEqual(self.power(g).id, old); self.assertEqual(g.state.players[1].mana, 4)
        self.assertEqual(len(g.state.card_discovery_history), 0)

    def test_saved_schema_and_player_views_do_not_expose_private_offer_proofs(self):
        import json
        g = self.game((CARD,)); self.play(g, CARD)
        own = json.dumps(g.for_player(1).observe()); other = json.dumps(g.for_player(2).observe())
        for key in ('eligible', 'rng_before', 'rng_after', 'previous_power', 'profile_power_ids'):
            self.assertNotIn('"'+key+'"', own); self.assertNotIn('"'+key+'"', other)
        bad = deepcopy(g.snapshot()); bad['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, fixture('normal', 'independent-reader'))
