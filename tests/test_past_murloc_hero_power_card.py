"""Real Vilefin entry, physical power installation and its ordinary Murloc."""
from dataclasses import asdict, replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards.native_past_entry_grant_cards import FLASHBACK, POOL_ID, register_native_past_entry_grant_cards
from hs_sim.cards.past_murloc_hero_power_card import (
    CARD, TOKEN, POWER, DEPENDENCIES, EVIDENCE_ONLY, load_batch, register_past_murloc_hero_power_card)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    IllegalAction, PlayerSetup, Registry, Scenario, UseHeroPower, Zone)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Destroy, InvokeBehavior,
    RefreshHeroPower, ReplaceHeroPower, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hero_powers import AddHeroPower
from hs_sim.engine.model import TargetMode, TargetSpec, TriggerSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.representative import build_registry as baseline_registry
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial

P = 'k470.'
NOOP, KILL, SILENCE, STEAL, BOUNCE, SUMMON, REFRESH, ADD, REPLACE, WATCH, FAIL, EMPTY = (
    P+s for s in ('noop', 'kill', 'silence', 'steal', 'bounce', 'summon', 'refresh', 'add', 'replace', 'watch', 'fail', 'empty'))
CONTEXT = GenerationContext('k470-finite-historical-skill-entry', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())


@lru_cache(None)
def complete_registry():
    return build_registry()


@lru_cache(None)
def baseline():
    return baseline_registry()


def fixture(mode='normal', role='writer'):
    r = Registry('k470-'+mode)
    register_past_murloc_hero_power_card(r)
    register_native_past_entry_grant_cards(r)
    for cid in ('HERO_04', 'HERO_08', 'HERO_04bp', 'HERO_08bp', 'CS2_101t'):
        card = baseline().card(cid)
        if card.on_use:
            r.register_behavior(card.on_use, baseline().behavior(card.on_use))
        r.register_card(card)
    r.register_card(CardDefinition(EMPTY, EMPTY, CardType.HERO, health=30,
        metadata=replace(META, classes=(CardClass.MAGE,))))
    def fail(c):
        raise ResolutionError('K470 deliberate late power reaction failure')
    scripts = {
        NOOP: lambda c: (), KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        SILENCE: lambda c: (Silence(c.target_id),), STEAL: lambda c: (ChangeControl(c.target_id, 2),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        SUMMON: lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(CARD),), SummonCause.capture(c)),),
        REFRESH: lambda c: (RefreshHeroPower(c.player_id),),
        ADD: lambda c: (AddHeroPower(c.player_id, 'HERO_08bp', c.source_id),),
        REPLACE: lambda c: (ReplaceHeroPower(c.player_id, 'HERO_04bp', source_id=c.source_id),),
        FAIL: fail,
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,))
                if cid in (KILL, SILENCE, STEAL, BOUNCE) else None))
    def watch(c):
        e = c.event
        replacement = e.kind == 'hero_power_replaced' and c.state.entities[e.target_id].card_id == POWER
        token = e.kind == 'minion_summoned' and c.state.entities[e.target_id].card_id == TOKEN
        if replacement and mode == 'fail' or token and mode == 'token_fail':
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        if replacement and mode == 'replace_wait' or token and mode == 'token_wait':
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
        return ()
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=8, metadata=META,
        triggers=(TriggerSpec('hero_power_replaced', WATCH), TriggerSpec('minion_summoned', WATCH))))
    r.register_pool(PoolDefinition(POOL_ID, 'k470-only-vilefin', CONTEXT.target_id, CONTEXT.mode,
        (PoolMember(CARD),), complete=True))
    r.validate()
    return r


class PastMurlocHeroPowerTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), board=(), *, mode='normal', hero='HERO_08', enemy_hand=()):
        self.mode = mode
        if mode != 'normal':
            board = (*board, WATCH)
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, deck=(NOOP,)*8, mana=20, max_mana=20, mana_cap=20,
                hero_power_card_id=None if hero == EMPTY else 'HERO_04bp' if hero == 'HERO_04' else 'HERO_08bp'),
            PlayerSetup('HERO_04', hand=enemy_hand, deck=(NOOP,)*8, mana=20, max_mana=20, mana_cap=20,
                hero_power_card_id='HERO_04bp')),
            seed=470, generation_context=CONTEXT), fixture(mode))

    def power(self, game, player=1):
        return game.state.entities[game.state.players[player].hero_power_id]

    def use(self, game, player=1, target=None):
        game.apply(UseHeroPower(player, self.power(game, player).id, target))

    def test_complete_three_execution_rows_four_review_rows_and_ten_full_primary_faces(self):
        data = load_batch()
        self.assertEqual(tuple(x['record']['id'] for x in data['dependencies']), DEPENDENCIES)
        self.assertEqual(tuple(x['record']['id'] for x in data['evidence_only']), EVIDENCE_ONLY)
        rows = {x['record']['id']: x['record'] for x in data['dependencies']+data['evidence_only']}
        self.assertEqual(len(data['official_observations']), 10)
        hashes = {}
        for observation in data['official_observations']:
            path = observation['response_file']
            if path not in hashes:
                hashes[path] = batch.sha(path)
            self.assertEqual(hashes[path], observation['response_sha256'])
            batch.check_face(rows[observation['card_id']], observation['face'], observation['locale'])
            if observation['card_id'] == CARD:
                self.assertEqual(observation['face']['childIds'], [39154, 38822])
        self.assertEqual(batch.sha(data['source']['path']), data['source']['sha256'])
        self.assertFalse(data['child_primary_faces_observed'])
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_constructed_registers_exact_three_faces_and_no_evidence_only_adapters(self):
        r = complete_registry(); small = fixture()
        for cid in DEPENDENCIES:
            self.assertEqual(asdict(r.card(cid)), asdict(small.card(cid)))
            self.assertEqual(r.pool_card(cid), small.pool_card(cid))
        for cid in EVIDENCE_ONLY:
            self.assertNotIn(cid, small.cards)
        self.assertEqual((r.card(CARD).attack, r.card(CARD).health, r.card(CARD).cost), (1, 3, 1))

    def test_paid_battlecry_replaces_only_own_primary_slot_once(self):
        g = self.game((CARD,)); old = self.power(g).id; other = self.power(g, 2).id
        source = self.play(g, CARD)
        self.assertEqual((self.power(g).card_id, g.state.players[1].mana), (POWER, 19))
        self.assertEqual(g.state.entities[old].zone, Zone.GRAVEYARD)
        self.assertEqual(self.power(g, 2).id, other)
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual(sum(e.kind == 'hero_power_replaced' for e in g.events), 1)
        self.assertEqual(g.state.entities[source].health, 3)

    def test_new_power_pays_two_and_summons_the_exact_one_one_murloc(self):
        g = self.game((CARD,)); self.play(g, CARD); self.use(g)
        token = self.entity(g, TOKEN, zone='board')
        self.assertEqual((token.attack, token.health, g.state.players[1].mana), (1, 1, 17))
        self.assertEqual(g.registry.card(TOKEN).metadata.tribes, ('murloc',))
        self.assertEqual(token.keywords, set())
        self.assertEqual((self.power(g).uses_this_turn, len(g.state.hero_power_history)), (1, 1))
        self.assertEqual(g.state.hero_power_history[-1].card_id, POWER)
        self.assertNotIn('CS2_101t', [g.state.entities[i].card_id for i in g.state.players[1].board])

    def test_skill_install_and_fixed_summon_do_not_consume_rng(self):
        g = self.game((CARD,)); before = g.snapshot()['rng_state']
        self.play(g, CARD); self.use(g)
        self.assertEqual(g.snapshot()['rng_state'], before)

    def test_second_activation_is_rejected_without_payment_or_state_change(self):
        g = self.game((CARD,)); self.play(g, CARD); self.use(g); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_replacement_after_old_skill_use_has_fresh_local_use_but_keeps_player_history(self):
        g = self.game((CARD,)); old = self.power(g).id
        self.use(g, target=g.state.players[2].hero_id); self.play(g, CARD); self.use(g)
        self.assertNotEqual(self.power(g).id, old)
        self.assertEqual([x.card_id for x in g.state.hero_power_history], ['HERO_08bp', POWER])
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn, 2)
        self.assertEqual(self.power(g).uses_this_turn, 1)

    def test_same_printed_skill_replacement_is_a_fresh_physical_installation(self):
        g = self.game((CARD, CARD)); self.play(g, CARD); self.use(g); old = self.power(g).id
        self.play(g, CARD)
        self.assertEqual(self.power(g).card_id, POWER); self.assertNotEqual(self.power(g).id, old)
        self.assertEqual(g.state.entities[old].zone, Zone.GRAVEYARD)
        self.assertEqual(self.power(g).uses_this_turn, 0); self.use(g)
        self.assertEqual(sum(g.state.entities[i].card_id == TOKEN for i in g.state.players[1].board), 2)

    def test_full_board_blocks_the_skill_before_payment_and_usage(self):
        g = self.game((CARD,), board=(TOKEN,)*6); self.play(g, CARD); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_summoned_inquisitor_does_not_run_battlecry(self):
        g = self.game((SUMMON,)); old = self.power(g).id; self.play(g, SUMMON)
        self.assertEqual(self.power(g).id, old)
        self.assertEqual(self.entity(g, CARD, zone='board').health, 3)
        self.assertFalse(any(e.kind == 'hero_power_replaced' for e in g.events))

    def test_real_flashback_summons_two_inquisitors_without_replacing_the_skill(self):
        g = self.game((NOOP, FLASHBACK)); old = self.power(g).id
        self.play(g, NOOP); self.play(g, FLASHBACK)
        bodies = [g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual([(e.card_id, e.attack, e.health) for e in bodies], [(CARD, 2, 3)]*2)
        self.assertEqual(self.power(g).id, old)
        self.assertFalse(any(e.kind == 'hero_power_replaced' for e in g.events))

    def test_source_silence_death_or_control_change_does_not_revoke_installed_skill(self):
        for change in (SILENCE, KILL, STEAL):
            with self.subTest(change=change):
                g = self.game((CARD, change)); source = self.play(g, CARD); installed = self.power(g).id
                self.play(g, change, source)
                self.assertEqual(self.power(g).id, installed); self.use(g)
                self.assertEqual(self.entity(g, TOKEN, zone='board').controller, 1)

    def test_bounce_and_replay_replaces_the_installed_skill_again(self):
        g = self.game((CARD, BOUNCE)); source = self.play(g, CARD); old = self.power(g).id
        self.play(g, BOUNCE, source); self.play(g, CARD)
        self.assertNotEqual(self.power(g).id, old)
        self.assertEqual(self.power(g).card_id, POWER)

    def test_existing_additional_power_identity_and_uses_are_preserved(self):
        g = self.game((ADD, CARD)); self.play(g, ADD)
        extra = tuple(g.state.players[1].additional_hero_power_ids)
        self.play(g, CARD)
        self.assertEqual(tuple(g.state.players[1].additional_hero_power_ids), extra)
        self.assertEqual(g.state.entities[extra[0]].card_id, 'HERO_08bp')
        self.assertEqual(g.state.entities[extra[0]].uses_this_turn, 0)

    def test_installation_into_an_empty_primary_slot_uses_the_original_installer(self):
        g = self.game((CARD,), hero=EMPTY); self.assertIsNone(g.state.players[1].hero_power_id)
        self.play(g, CARD); self.assertEqual(self.power(g).card_id, POWER); self.use(g)
        self.assertEqual(self.entity(g, TOKEN, zone='board').health, 1)

    def test_installed_skill_is_still_usable_on_following_owner_turn(self):
        g = self.game((CARD,)); self.play(g, CARD); self.use(g)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.use(g)
        self.assertEqual(sum(g.state.entities[i].card_id == TOKEN for i in g.state.players[1].board), 2)

    def test_enemy_hand_play_installs_the_power_for_its_actual_controller(self):
        g = self.game(enemy_hand=(CARD,)); old = self.power(g).id; g.apply(EndTurn(1))
        self.play(g, CARD, player=2); self.use(g, player=2)
        self.assertEqual(self.power(g).id, old)
        self.assertEqual(self.entity(g, TOKEN, 2, 'board').controller, 2)

    def test_replacement_wait_restores_new_and_retired_skill_identities(self):
        g = self.game((CARD,), mode='replace_wait'); old = self.power(g).id; self.play(g, CARD)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[old].zone, Zone.GRAVEYARD)
        installed = self.power(g).id; g = self.portable(g); self.choose(g); self.use(g)
        self.assertEqual(self.power(g).id, installed)
        self.assertEqual(self.entity(g, TOKEN, zone='board').attack, 1)

    def test_token_summon_wait_resumes_original_skill_payload_without_second_payment(self):
        g = self.game((CARD,), mode='token_wait'); self.play(g, CARD); self.use(g)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(g.state.players[1].mana, 17)
        g = self.portable(g); self.choose(g)
        self.assertEqual(g.state.players[1].mana, 17)
        self.assertTrue(g.state.hero_power_history[-1].completed)
        self.assertEqual(sum(g.state.entities[i].card_id == TOKEN for i in g.state.players[1].board), 1)

    def test_failed_replacement_restores_old_skill_hand_payment_and_events(self):
        g = self.game((CARD,), mode='fail'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, CARD)
        self.assertEqual(g.snapshot(), before)

    def test_failed_token_reaction_restores_skill_payment_usage_and_board(self):
        g = self.game((CARD,), mode='token_fail'); self.play(g, CARD); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_waiting_failure_returns_to_the_exact_accepted_choice_boundary(self):
        g = self.game((CARD,), mode='replace_wait'); self.play(g, CARD); g = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before); self.choose(g); self.use(g)

    def test_later_independent_replacement_retires_murloc_skill_and_uses_normal_recruit(self):
        g = self.game((CARD, REPLACE)); self.play(g, CARD); old = self.power(g).id; self.play(g, REPLACE)
        self.assertEqual(g.state.entities[old].zone, Zone.GRAVEYARD)
        self.use(g)
        self.assertEqual(self.entity(g, 'CS2_101t', zone='board').health, 1)
        self.assertFalse(any(g.state.entities[i].card_id == TOKEN for i in g.state.players[1].board))
