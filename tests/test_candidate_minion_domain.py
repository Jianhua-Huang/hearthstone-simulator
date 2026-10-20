"""Actual candidate consumers share the source-defined ordinary minion domain."""
from random import Random
import unittest

from hs_sim.candidate_format import build_cn37_candidate_format
from hs_sim.cards.candidate_generation_catalog import load_batch
from hs_sim.cards.kazakus_potion_cards import TEMPLATE, PARTS
from hs_sim.cards.medivh_fabled_cards import KARAZHAN, QUERY
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec, UseLocation)
from hs_sim.engine.composed_spells import ComposedSpellRecipe
from hs_sim.engine.effects import ChoiceOption, RequestChoice
from hs_sim.engine.pools import GenerationContext, PoolQuery, resolve_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sham_trials import ShamTrialRecipe
from hs_sim.targets import TargetValidationError

POOL = 'constructed.minions'
WATCH = 'fixture.candidate_minion_domain.watch'
TRIAL = 'CAP_405'


def waiting_format():
    fmt = build_cn37_candidate_format()
    def observe(c):
        if c.event.kind != 'minion_summoned': return ()
        target = c.state.entities[c.event.target_id]
        if fmt.registry.card(target.card_id).cost != 8: return ()
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),), c.source_id),)
    # An explicit observer supplies a wait; it never joins either source pool.
    fmt.registry.register_behavior(WATCH, observe)
    fmt.registry.register_card(CardDefinition(WATCH, 'Explicit waiting observer', CardType.MINION,
        health=20, triggers=(TriggerSpec('minion_summoned', WATCH),)))
    fmt.registry.validate()
    return fmt


class CandidateMinionDomainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fmt = build_cn37_candidate_format()
        cls.reader = build_cn37_candidate_format()

    def game(self, hand=(), board=(), *, fmt=None, seed=322):
        fmt = fmt or self.fmt
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_09', hand=hand, board=board, deck=('CORE_EX1_189',)*3,
                mana=10, max_mana=10),
            PlayerSetup('HERO_07', deck=('CORE_EX1_189',)*3, mana=10, max_mana=10)),
            seed=seed, generation_context=fmt.context), fmt.registry)

    def portable(self, game, reader=None):
        saved = game.snapshot(); registry = (reader or self.reader).registry
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(saved, registry).snapshot(), saved)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), saved)

    def play(self, game, cid):
        eid = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == cid)
        game.apply(PlayCard(1, eid))

    def choose(self, game, cid):
        q = game.state.pending_choice
        game.apply(SelectChoice(q.player_id, q.id, (cid,)))

    def test_minion_inventory_is_the_exact_source_projection_with_equal_query_results(self):
        fmt = self.fmt
        expected = tuple(r['record']['id'] for r in load_batch()['cards'] if r['record']['type'] == 'MINION')
        pool = fmt.registry.pool(POOL, fmt.context)
        self.assertEqual(len(expected), 729)
        self.assertEqual(tuple(m.card_id for m in pool.members), expected)
        self.assertEqual({m.weight for m in pool.members}, {1})
        self.assertTrue(pool.complete)
        for query in (PoolQuery(kinds=(CardType.MINION,), collectible=True), QUERY,
                PoolQuery(kinds=(CardType.MINION,), collectible=True, tribes_any=('demon',)),
                PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=3, max_cost=3)):
            with self.subTest(query=query):
                self.assertEqual(resolve_candidates(fmt.registry, fmt.context, POOL, query),
                    resolve_candidates(fmt.registry, fmt.context, 'constructed.cards', query))

    def test_actual_karazhan_use_resolves_original_two_eight_cost_requests(self):
        game = self.game(board=(KARAZHAN,))
        source = game.state.players[1].board[0]
        game.apply(UseLocation(1, source))
        roots = game.state.card_summon_history
        self.assertEqual(len(roots), 2)
        self.assertTrue(all(r.request.pool_basis.pool_id == POOL for r in roots))
        self.assertTrue(all(r.request.pool_basis.query == QUERY for r in roots))
        chosen = [r.request.materials[r.selected].card_id for r in roots if r.selected is not None]
        self.assertEqual(len(chosen), 2)
        self.assertTrue(all(self.fmt.registry.card(cid).cost == 8 for cid in chosen))
        self.assertEqual(game.state.entities[source].durability, 1)
        self.assertEqual(len(game.state.cast_history), 0)
        self.portable(game)

    def test_actual_aya_potion_generates_a_demon_through_one_paid_cast(self):
        cid = ComposedSpellRecipe(TEMPLATE, PARTS[6], PARTS[8]).card_id
        game = self.game((cid,)); self.play(game, cid)
        self.assertEqual(len(game.state.players[1].hand), 1)
        created = game.state.entities[game.state.players[1].hand[0]]
        self.assertIn(created.card_id, self.fmt.root_card_ids)
        self.assertIn('demon', self.fmt.registry.card(created.card_id).metadata.tribes)
        self.assertEqual((game.state.players[1].mana, len(game.state.cast_history)), (9, 1))
        self.portable(game)

    def test_actual_godfather_crafting_and_paid_trial_summon_three_cost_minions(self):
        fmt = self.fmt; profile = fmt.registry._sham_trial_profiles[TRIAL]
        first, second = 'CAP_405t6', 'CAP_405t8'
        for seed in range(1000):
            rng = Random(seed)
            if first in rng.sample(profile.component_ids, 3) and second in rng.sample(
                    tuple(c for c in profile.component_ids if c != first), 3): break
        else: self.fail('No seed for the original full-domain manufacture')
        game = self.game((TRIAL,), seed=seed); self.play(game, TRIAL)
        self.choose(game, first); self.choose(game, second)
        tier = next(t for t in profile.tiers if fmt.registry.card(t.template_card_id).cost == 7)
        self.choose(game, tier.choice_card_id)
        parts = sorted((first, second), key=profile.component_ids.index)
        recipe = ShamTrialRecipe(tier.template_card_id, *parts).card_id
        self.assertIn(recipe, [game.state.entities[i].card_id for i in game.state.players[1].hand])
        game.apply(EndTurn(1)); game.apply(EndTurn(2)); self.play(game, recipe)
        batch, = game.state.pool_summon_history
        self.assertEqual((batch.spec.basis.pool_id, len(batch.selected), batch.status), (POOL, 3, 'completed'))
        self.assertTrue(all(fmt.registry.card(cid).cost == 3 for cid in batch.selected))
        self.assertEqual((game.state.players[1].mana, len(game.state.cast_history)), (3, 1))
        self.portable(game)

    def test_karazhan_waits_restore_and_replay_original_second_request(self):
        fmt, reader = waiting_format(), waiting_format()
        game = self.game(board=(KARAZHAN, WATCH), fmt=fmt)
        source = game.state.players[1].board[0]; game.apply(UseLocation(1, source))
        waits = 0
        while game.state.pending_choice is not None:
            waits += 1; self.assertLessEqual(waits, 2)
            self.portable(game, reader)
            game = Game.from_snapshot(game.snapshot(), reader.registry)
            self.choose(game, 'continue')
        self.assertEqual(waits, 2)
        self.assertEqual(len(game.state.card_summon_history), 2)
        self.assertEqual(game.state.entities[source].durability, 1)
        self.portable(game, reader)

    def test_unknown_eligible_minion_remains_a_member_and_explicitly_fails(self):
        fmt = build_cn37_candidate_format()
        cid = resolve_candidates(fmt.registry, fmt.context, 'constructed.cards', QUERY)[0].card_id
        fmt.registry._cards.pop(cid)  # Explicit incomplete-implementation fixture.
        self.assertIn(cid, tuple(m.card_id for m in fmt.registry.pool(POOL, fmt.context).members))
        with self.assertRaises(UnsupportedDefinitionError):
            resolve_candidates(fmt.registry, fmt.context, POOL, QUERY)

    def test_minion_binding_does_not_fabricate_pack_past_or_formal_domains(self):
        fmt = self.fmt
        self.assertFalse(fmt.formal_pool_complete); self.assertFalse(fmt.policy.pool_complete)
        with self.assertRaises(TargetValidationError): fmt.require_formal()
        for pool in ('constructed.standard_pack', 'constructed.past.cards', 'constructed.past.spells'):
            with self.subTest(pool=pool), self.assertRaises(UnsupportedDefinitionError):
                fmt.registry.pool(pool, fmt.context)
        for mode in ('standard', 'wild'):
            with self.subTest(mode=mode), self.assertRaises(UnsupportedDefinitionError):
                fmt.registry.pool(POOL, GenerationContext(fmt.target_id, mode))


if __name__ == '__main__': unittest.main()
