"""Real discovery halves, late delivery views and independent owner-turn promises."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import assemble_discovery_prefix_followups as cards
from hs_sim.cards.native_assemble_entry_cards import FLESH, POOL_ID as ASSEMBLE_POOL
from hs_sim.cards.simple_followup_p63_cards import PROMISE
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe, before_behavior_id
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import AddToHand, ChoiceOption, Destroy, GainArmor, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_draw_armor_heal_fragments import fixture as base_fixture, COIN, KILL, MUTE, META

WHELP, REAVER = cards.SOURCES
FLY, LOOT, END, START = 'CORE_UNG_809', 'CORE_EX1_096', 'BE_152', 'CORE_NEW1_021'
FEL, FOREIGN_FEL, ZERO, FIRE, FIVE = 'CORE_BT_035', 'CORE_SW_088', 'TLC_451', 'CORE_CS2_023', 'CS3_024'
BRANN = 'LOE_077'
P = 'k418.'
WATCH, FAIL, UNKNOWN = (P + key for key in ('watch', 'fail', 'unknown_five_fel'))
CTX = GenerationContext('k418-actual-native-discovery-halves', 'experimental')
MEMBERS = (FIVE, FEL, FOREIGN_FEL, ZERO, FIRE)


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    registry = base_fixture.__wrapped__('no_pool', role)
    registry._version += '.k418.' + mode

    def fail(c):
        raise ResolutionError('K418 deliberate late continuation failure')

    def watch(c):
        source = c.state.entities.get(c.event.source_id)
        recipient = c.state.entities.get(c.event.target_id)
        own_event = (recipient is not None and recipient.controller == c.player_id
            if mode == 'fail_cost' else c.event.player_id == c.player_id)
        if (not own_event or source is None or
                source.card_id not in cards.SOURCES and not source.card_id.startswith('assemble:')):
            return ()
        if mode == 'fill':
            return (AddToHand(c.player_id, COIN, c.source_id),)
        if mode == 'fail_cost':
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue after source death', (
                Destroy(c.event.source_id, c.source_id), AddToHand(c.player_id, FEL, c.source_id))),
            ChoiceOption('bad', 'Fail continuation', (GainArmor(c.player_id, 1),
                InvokeBehavior(FAIL, c.source_id, c.player_id)))), c.source_id),)

    registry.register_behavior(FAIL, fail)
    registry.register_behavior(WATCH, watch)
    event = 'choice_selected' if mode == 'fill' else 'cost_modified' if mode == 'fail_cost' else 'card_created'
    registry.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=10, metadata=META,
        triggers=(TriggerSpec(event, WATCH),)))
    if mode != 'no_pool':
        members = (FIRE, COIN) if mode == 'empty' else MEMBERS
        if mode == 'unknown':
            registry.register_pool_card(replace(registry.pool_card(FEL), card_id=UNKNOWN, cost=5))
            members += (UNKNOWN,)
        registry.register_pool(PoolDefinition(cards.POOL_ID, 'k418-explicit-discovery-domain',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    registry.register_pool(PoolDefinition(ASSEMBLE_POOL, 'k418-four-reviewed-real-sources',
        CTX.target_id, CTX.mode,
        tuple(PoolMember(cid) for cid in (REAVER, WHELP, LOOT, 'CORE_GIL_622')), complete=True))
    registry.validate()
    return registry


class AssembleDiscoveryPrefixFollowupTests(unittest.TestCase):
    def game(self, hand=(), board=(), mode='normal', enemy_hand=(), hero='HERO_10'):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, deck=(COIN,) * 18,
                mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_08', hand=enemy_hand, deck=(COIN,) * 18,
                mana=30, max_mana=30, mana_cap=30)), seed=418, generation_context=CTX), fixture(mode))

    def entity(self, game, cid, player=1):
        return next(game.state.entities[eid] for eid in game.state.players[player].hand
            if game.state.entities[eid].card_id == cid)

    def play(self, game, cid, target=None):
        player = game.state.active_player
        source = self.entity(game, cid, player).id
        game.apply(PlayCard(player, source, target))
        return source

    def choose(self, game, cid=None, key=None):
        choice = game.state.pending_choice
        selected = key if key is not None else next(option.id for option in choice.options
            if cid is None or option.card_id == cid)
        game.apply(SelectChoice(choice.player_id, choice.id, (selected,)))

    def portable(self, game, mode='normal'):
        reader = fixture(mode, 'reader')
        self.assertIsNot(reader, game.registry)
        saved = json.loads(json.dumps(game.snapshot()))
        restored = Game.from_snapshot(saved, reader)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(game), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(game.for_player(player).observe()) + json.dumps(game.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'pool_id', 'before_behavior_id', 'candidate_card_ids'):
                self.assertNotIn('"' + key + '"', public)
        return restored

    def test_a_two_complete_sources_four_faces_queries_profiles_and_exact_native_bridges(self):
        data = cards.load_batch()
        registry = build_registry()
        self.assertEqual(len(data['existing_dependencies']), 2)
        self.assertEqual(len(data['official_observations']), 4)
        rows = {row['record']['id']: row for row in data['existing_dependencies']}
        for observation in data['official_observations']:
            cid = observation['card_id']
            check_face(rows[cid]['record'], observation['face'], observation['locale'],
                data['display_normalizations'].get(cid))
            path = Path(observation['response_file'])
            self.assertEqual(sha(path), observation['response_sha256'])
            response = json.loads(path.read_text(encoding='utf-8-sig'))
            self.assertEqual([face for face in response['cards'] if face['id'] == rows[cid]['record']['dbf_id']],
                [observation['face']])
        for cid, row in rows.items():
            self.assertEqual(canonical_digest(asdict(registry.card(cid))), row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(cards.QUERIES[cid])), data['queries_sha256'][cid])
            template = registry.assemble_templates[cid]
            self.assertEqual(template.original_battlecry_id, registry.card(cid).battlecry)
            self.assertIsNotNone(template.prefix.before_behavior_id)
            recipe = AssembleRecipe(cid, cid, 'top').card_id
            derived = asdict(registry.card(recipe))
            self.assertEqual(derived['battlecry'], before_behavior_id(
                template.prefix.before_behavior_id, template.suffix.behavior_id))
            derived.update(id=cid, battlecry=template.original_battlecry_id)
            self.assertEqual(derived, asdict(registry.card(cid)))
        self.assertEqual(canonical_digest(asdict(registry.player_effect(PROMISE))),
            data['next_turn_player_effect_sha256'])
        self.assertFalse(any(data['experimental_policy'].values()))

    def test_b_each_borrowed_prefix_discovers_then_runs_new_suffix_without_its_old_reward(self):
        for donor, expected, selected in ((WHELP, {FIVE}, FIVE), (REAVER, {FEL}, FEL)):
            with self.subTest(donor=donor):
                cid = AssembleRecipe(LOOT, donor, 'top').card_id
                game = self.game((cid, FEL))
                old = self.entity(game, FEL).id
                mana = game.state.players[1].mana
                self.play(game, cid)
                self.assertEqual({option.card_id for option in game.state.pending_choice.options}, expected)
                self.assertFalse(game.state.draw_history)
                self.assertFalse(game.state.players[1].player_effects)
                self.choose(game, selected)
                self.assertEqual([row.card_id for row in game.state.draw_history], [COIN])
                self.assertEqual(game.quote_cost(old).amount, 2)
                self.assertFalse(game.state.players[1].player_effects)
                self.assertEqual(game.state.players[1].mana, mana - 2)
                self.assertEqual(len(game.state.battlecry_history), 1)
                self.assertTrue(game.state.battlecry_history[0].completed)

    def test_c_each_borrowed_reward_works_without_discovery_or_a_generation_domain(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                cid = AssembleRecipe(FLY, donor, 'bottom').card_id
                game = self.game((cid, FEL, FOREIGN_FEL, ZERO, FIRE), mode='no_pool', enemy_hand=(FEL,))
                ids = [self.entity(game, card).id for card in (FEL, FOREIGN_FEL, ZERO, FIRE)]
                enemy = self.entity(game, FEL, 2).id
                rng = game._rng.getstate()
                source = self.play(game, cid)
                self.assertIsNone(game.state.pending_choice)
                self.assertFalse(game.state.draw_history)
                self.assertEqual(game._rng.getstate(), rng)
                self.assertEqual([game.quote_cost(eid).amount for eid in ids],
                    [1, 3, 0, 3] if donor == REAVER else [2, 4, 0, 3])
                self.assertEqual(quote_unselected_cost(game.state, game.registry, game.state.entities[enemy]).amount, 2)
                effects = game.state.players[1].player_effects
                self.assertEqual(len(effects), 1 if donor == WHELP else 0)
                if effects:
                    self.assertEqual((effects[0].spec_id, effects[0].source_id, effects[0].source_card_id),
                        (PROMISE, source, cid))

    def test_d_self_recipes_preserve_the_actual_original_discovery_and_reward(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                cid = AssembleRecipe(donor, donor, 'top').card_id
                game = self.game((cid, FEL, FOREIGN_FEL))
                old = self.entity(game, FEL).id
                foreign = self.entity(game, FOREIGN_FEL).id
                self.play(game, cid)
                self.assertFalse(game.state.players[1].player_effects)
                self.assertEqual(game.quote_cost(old).amount, 2)
                self.choose(game, FIVE if donor == WHELP else FEL)
                self.assertEqual(len(game.state.players[1].player_effects), int(donor == WHELP))
                self.assertEqual([game.quote_cost(eid).amount for eid in (old, foreign)],
                    [2, 4] if donor == WHELP else [1, 3])
                if donor == REAVER:
                    self.assertEqual(game.quote_cost(self.entity(game, FEL).id).amount, 1)
                    self.assertEqual(sum(game.state.entities[eid].card_id == FEL
                        for eid in game.state.players[1].hand), 2)

    def test_e_delivery_reaction_wait_death_fresh_hand_failed_resume_restore_and_replay(self):
        cid = AssembleRecipe(REAVER, REAVER, 'top').card_id
        game = self.game((cid, FEL), (WATCH,), mode='wait')
        original = self.entity(game, FEL).id
        source = self.play(game, cid)
        saved = game.snapshot()
        with self.assertRaises(IllegalAction):
            self.choose(game, key='not-an-option')
        self.assertEqual(game.snapshot(), saved)
        self.choose(game, FEL)
        self.assertEqual({option.id for option in game.state.pending_choice.options}, {'ok', 'bad'})
        self.assertEqual(game.quote_cost(original).amount, 2)
        reader = self.portable(game, 'wait')
        saved = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate late continuation failure'):
            self.choose(game, key='bad')
        self.assertEqual(game.snapshot(), saved)
        for running in (game, reader):
            self.choose(running, key='ok')
            self.assertIsNone(running.state.pending_choice)
            self.assertEqual(running.state.entities[source].zone, Zone.GRAVEYARD)
            fel = [eid for eid in running.state.players[1].hand if running.state.entities[eid].card_id == FEL]
            self.assertEqual(len(fel), 3)
            self.assertEqual([running.quote_cost(eid).amount for eid in fel], [1, 1, 1])
            self.assertEqual(running.state.players[1].mana, 26)
            self.assertTrue(running.state.battlecry_history[0].completed)
        self.assertEqual(game.snapshot(), reader.snapshot())
        self.portable(game, 'wait')

    def test_f_two_mana_promises_survive_silence_death_and_only_pay_next_owner_turn_once(self):
        cid = AssembleRecipe(FLY, WHELP, 'bottom').card_id
        game = self.game((cid, cid, MUTE, KILL), mode='no_pool')
        sources = [self.play(game, cid), self.play(game, cid)]
        effects = game.state.players[1].player_effects
        self.assertEqual(len({effect.id for effect in effects}), 2)
        self.assertEqual({effect.source_id for effect in effects}, set(sources))
        self.play(game, MUTE, sources[0])
        self.play(game, KILL, sources[1])
        reader = self.portable(game, 'no_pool')
        for running in (game, reader):
            running.apply(EndTurn(1))
            self.assertEqual(running.state.players[1].temporary_mana, 0)
            self.assertEqual(len(running.state.players[1].player_effects), 2)
            running.apply(EndTurn(2))
            self.assertEqual(running.state.players[1].temporary_mana, 2)
            self.assertFalse(running.state.players[1].player_effects)
            running.apply(EndTurn(1))
            self.assertEqual(running.state.players[1].temporary_mana, 0)
            running.apply(EndTurn(2))
            self.assertEqual(running.state.players[1].temporary_mana, 0)
        self.assertEqual(game.snapshot(), reader.snapshot())

    def test_g_both_rewards_work_in_the_four_declared_native_contexts_without_discovery(self):
        for donor in cards.SOURCES:
            for prefix in (FLY, LOOT, END, START):
                with self.subTest(donor=donor, prefix=prefix):
                    cid = AssembleRecipe(prefix, donor, 'bottom').card_id
                    game = self.game((cid, FEL, KILL), mode='no_pool')
                    old = self.entity(game, FEL).id
                    source = self.play(game, cid)
                    if prefix == LOOT:
                        self.play(game, KILL, source)
                    elif prefix == END:
                        game.apply(EndTurn(1))
                    elif prefix == START:
                        game.apply(EndTurn(1))
                        self.assertFalse(game.state.players[1].player_effects)
                        self.assertEqual(quote_unselected_cost(game.state, game.registry, game.state.entities[old]).amount, 2)
                        game.apply(EndTurn(2))
                    self.assertIsNone(game.state.pending_choice)
                    if donor == WHELP:
                        effect = game.state.players[1].player_effects[-1]
                        self.assertEqual((effect.source_id, effect.source_card_id), (source, cid))
                        self.assertEqual(game.state.players[1].temporary_mana, 0)
                    else:
                        self.assertEqual(quote_unselected_cost(game.state, game.registry, game.state.entities[old]).amount, 1)

    def test_h_real_flesh_shaper_offers_both_new_prefixes_and_keeps_paid_activation(self):
        for donor, selected, hero in ((WHELP, FIVE, 'HERO_02'), (REAVER, FEL, 'HERO_10')):
            with self.subTest(donor=donor):
                game = self.game((FLESH, FEL), hero=hero)
                self.play(game, FLESH)
                cid = AssembleRecipe(LOOT, donor, 'top').card_id
                self.choose(game, cid)
                mana = game.state.players[1].mana
                self.play(game, cid)
                self.choose(game, selected)
                self.assertEqual(game.state.players[1].mana, mana - 2)
                self.assertFalse(game.state.players[1].player_effects)
                self.assertEqual(game.quote_cost(self.entity(game, FEL).id).amount, 2)
                self.assertEqual([row.card_id for row in game.state.draw_history], [COIN])
                self.assertTrue(all(row.completed for row in game.state.battlecry_history))

    def test_i_missing_domain_or_unknown_eligible_card_rejects_before_rng_and_payment(self):
        for mode in ('no_pool', 'unknown'):
            for donor in cards.SOURCES:
                with self.subTest(mode=mode, donor=donor):
                    cid = AssembleRecipe(LOOT, donor, 'top').card_id
                    game = self.game((cid,), mode=mode)
                    saved = game.snapshot()
                    with self.assertRaises((ResolutionError, ValueError)):
                        self.play(game, cid)
                    self.assertEqual(game.snapshot(), saved)

    def test_j_empty_discovery_still_executes_borrowed_suffix_without_rng(self):
        for donor in cards.SOURCES:
            cid = AssembleRecipe(LOOT, donor, 'top').card_id
            game = self.game((cid,), mode='empty')
            rng = game._rng.getstate()
            self.play(game, cid)
            self.assertIsNone(game.state.pending_choice)
            self.assertEqual([row.card_id for row in game.state.draw_history], [COIN])
            self.assertEqual(game._rng.getstate(), rng)

    def test_k_full_hand_burn_does_not_prevent_the_remaining_current_hand_discount(self):
        cid = AssembleRecipe(REAVER, REAVER, 'top').card_id
        game = self.game((cid, FEL) + (COIN,) * 8, (WATCH,), mode='fill')
        old = self.entity(game, FEL).id
        self.play(game, cid)
        self.choose(game, FEL)
        self.assertIsNone(game.state.pending_choice)
        self.assertEqual(len(game.state.players[1].hand), 10)
        self.assertEqual(sum(game.state.entities[eid].card_id == FEL for eid in game.state.players[1].hand), 1)
        self.assertEqual(game.quote_cost(old).amount, 1)
        self.assertTrue(game.state.battlecry_history[0].completed)

    def test_l_failed_late_discount_restores_delivery_and_previously_modified_cards(self):
        cid = AssembleRecipe(REAVER, REAVER, 'top').card_id
        game = self.game((cid, FEL, FOREIGN_FEL), (WATCH,), mode='fail_cost')
        old = self.entity(game, FEL).id
        foreign = self.entity(game, FOREIGN_FEL).id
        self.play(game, cid)
        saved = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate late continuation failure'):
            self.choose(game, FEL)
        self.assertEqual(game.snapshot(), saved)
        self.assertEqual([game.quote_cost(eid).amount for eid in (old, foreign)], [2, 4])

    def test_m_repeated_discovery_reads_each_new_hand_and_pays_only_once(self):
        cid = AssembleRecipe(REAVER, REAVER, 'top').card_id
        game = self.game((cid, FEL), (BRANN,))
        self.play(game, cid)
        first = game.state.pending_choice.id
        self.choose(game, FEL)
        self.assertNotEqual(game.state.pending_choice.id, first)
        self.choose(game, FEL)
        costs = [game.quote_cost(eid).amount for eid in game.state.players[1].hand
            if game.state.entities[eid].card_id == FEL]
        self.assertEqual(costs, [0, 0, 1])
        self.assertEqual(game.state.players[1].mana, 26)
        self.assertEqual(len({row.id for row in game.state.battlecry_history}), 2)
        self.assertTrue(all(row.completed for row in game.state.battlecry_history))

    def test_n_changed_full_source_query_or_promise_rejects_before_partial_registration(self):
        for mode in ('card', 'query', 'promise'):
            with self.subTest(mode=mode):
                with patch.object(cards, 'register_assemble_discovery_prefix_followups', lambda r: None):
                    registry = build_registry()
                if mode == 'card':
                    registry._cards[WHELP] = replace(registry.card(WHELP), attack=registry.card(WHELP).attack + 1)
                    registry._pool_cards[WHELP] = replace(registry.pool_card(WHELP), attack=registry.card(WHELP).attack)
                if mode == 'promise':
                    registry._player_effects[PROMISE] = replace(registry.player_effect(PROMISE), card_id=REAVER)
                before = registry.fingerprint()
                queries = dict(cards.QUERIES)
                if mode == 'query':
                    queries[WHELP] = replace(queries[WHELP], min_cost=4)
                with patch.object(cards, 'QUERIES', queries), self.assertRaises(TargetValidationError):
                    cards.register_assemble_discovery_prefix_followups(registry)
                self.assertEqual(registry.fingerprint(), before)


if __name__ == '__main__':
    unittest.main()
