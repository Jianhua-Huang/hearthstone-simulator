"""The complete declared local inventories through the actual Victor entry."""
from dataclasses import asdict, replace
from collections import Counter
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture, P, FILLER
from hs_sim.cards.nefarian_community_pools import load_batch, SOURCE_TARGET
from hs_sim.cards.nefarian_crafting_card import CARD, TEMPLATE, DRAGONS, UNDEAD
from hs_sim.engine import Game, EndTurn, Keyword, PlayerSetup, Scenario, SelectChoice
from hs_sim.engine.crafted_faces import CraftedMinionRecipe
from hs_sim.engine.crafted_offers import CraftMinion, ResolveCraft, candidates
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.pools import GenerationContext, sample_candidates
from hs_sim.engine.native_conditions import validate_carrier as validate_condition
from hs_sim.engine.stat_relations import validate_carrier as validate_stat_relation
from tools import card_batch as batch


def recipe(first, second):
    return CraftedMinionRecipe(TEMPLATE, first, second).card_id


class NefarianCommunityHostTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(lambda mode, role: fixture(mode, role).registry)

    def game(self, hand, board=(), enemy=(), seed=1):
        fmt = fixture()
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_03', hand=tuple(hand), board=tuple(board), deck=(FILLER,)*8,
                max_mana=10, mana=10),
            PlayerSetup('HERO_08', board=tuple(enemy), deck=(FILLER,)*8)), seed=seed,
            generation_context=fmt.context), fmt.registry)

    def seed(self, first, second):
        fmt = fixture(); spec = CraftMinion(1, TEMPLATE, DRAGONS, UNDEAD, 1, max_total_cost=10)
        a = candidates(fmt.registry, fmt.context, spec)
        b = candidates(fmt.registry, fmt.context, spec, first)
        for seed in range(10000):
            rng = Random(seed)
            if first in sample_candidates(rng, a, 3, replacement=False):
                if second in sample_candidates(rng, b, 3, replacement=False):
                    return seed
        self.fail('No seed covers the original complete two-stage inventories')

    def pick(self, game, cid):
        choice = game.state.pending_choice
        option = next(o for o in game._frame.options if any(
            type(e) is ResolveCraft and e.card_id == cid for e in o.effects))
        game.apply(SelectChoice(choice.player_id, choice.id, (option.id,)))

    def create(self, first, second, extra=(), board=(), enemy=(), portable=False):
        game = self.game((CARD, *extra), board, enemy, self.seed(first, second))
        self.play(game, CARD)
        self.assertEqual(game.state.players[1].mana, 6)
        if portable: self.portable(game)
        self.pick(game, first)
        if portable: self.portable(game)
        self.pick(game, second)
        cid = recipe(first, second)
        self.assertEqual(self.entity(game, cid).card_id, cid)
        return game, cid

    def test_original_19_and_20_entries_preserved_with_explicit_role_conflict(self):
        data = load_batch(); fmt = fixture(); r = fmt.registry
        self.assertEqual(len(data['native_part_ids']), 38)
        self.assertEqual([len(x['members']) for x in data['roles']], [19, 20])
        self.assertEqual(data['roles'][1]['excluded_card_ids'], ['CATA_898'])
        self.assertEqual(r.card('CATA_898').metadata.tribes, ('dragon',))
        for role in data['roles']:
            source = r.pool(role['pool_id'], GenerationContext(SOURCE_TARGET, 'experimental'))
            current = r.pool(role['pool_id'], fmt.context)
            self.assertFalse(source.complete); self.assertTrue(current.complete)
            self.assertEqual(source.members, current.members)
            self.assertEqual(source.excluded_card_ids, current.excluded_card_ids)
            for row in data['cards']:
                c = r.card(row['record']['id'])
                self.assertEqual(batch.canonical(asdict(c)), row['reviewed_native_definition_sha256'])
                self.assertIn(c.id, r.crafted_minion_parts)
        spec = CraftMinion(1, TEMPLATE, DRAGONS, UNDEAD, 1, max_total_cost=10)
        self.assertEqual(len(candidates(r, fmt.context, spec)), 19)
        second = candidates(r, fmt.context, spec, 'END_022')
        self.assertEqual(len(second), 19)
        self.assertNotIn('CATA_898', [m.card_id for m in second])
        self.assertFalse(data['official_completeness_verified'])

    def test_all_affordable_declared_role_pairs_resolve_without_dropping_effects(self):
        fmt = fixture(); r = fmt.registry; data = load_batch(); count = 0
        for a in data['roles'][0]['members']:
            for b in data['roles'][1]['members']:
                if b['card_id'] in data['roles'][1]['excluded_card_ids']: continue
                first, second = r.card(a['card_id']), r.card(b['card_id'])
                if first.cost+second.cost > 10: continue
                face = r.card(recipe(first.id, second.id)); count += 1
                self.assertEqual((face.cost, face.attack, face.health),
                    (first.cost+second.cost, first.attack+second.attack, first.health+second.health))
                for field in ('triggers', 'cost_auras', 'keyword_auras', 'stat_relations', 'intrinsic_costs'):
                    self.assertEqual(getattr(face, field), getattr(first, field)+getattr(second, field))
                self.assertEqual(face.minion_death_cost, first.minion_death_cost or second.minion_death_cost)
        self.assertGreater(count, 250)

    def test_every_donor_installs_its_native_bodies_on_the_physical_composite(self):
        data = load_batch(); r = fixture().registry
        dragons = {m['card_id'] for m in data['roles'][0]['members']}
        for cid in data['native_part_ids']:
            first, second = (cid, 'ICC_913') if cid in dragons else ('END_022', cid)
            composed = recipe(first, second)
            game = self.game((), board=(composed,))
            entity = game.state.entities[game.state.players[1].board[0]]
            self.assertEqual(entity.components, (first, second))
            expected = Counter(body for part in (first, second) for body in
                (r.card(part).on_play, r.card(part).battlecry, r.card(part).deathrattle, r.card(part).combo) if body)
            actual = Counter(a.behavior_id for a in entity.abilities if a.kind in ('on_play', 'battlecry', 'deathrattle', 'combo'))
            self.assertEqual(actual, expected, cid)

    def test_actual_volcanic_ghoul_inherits_both_prices_and_each_choice_restores(self):
        game, cid = self.create('BRM_025', 'ICC_700',
            (P+'sweep', P+'hurt_hero', P+'heal_hero'), board=(P+'unit',), enemy=(P+'unit',), portable=True)
        self.assertEqual(quote_cost(game.state, game.registry, self.entity(game, cid)).amount, 9)
        self.play(game, P+'sweep')
        self.assertEqual(quote_cost(game.state, game.registry, self.entity(game, cid)).amount, 7)
        self.play(game, P+'hurt_hero'); self.play(game, P+'heal_hero')
        self.assertEqual(quote_cost(game.state, game.registry, self.entity(game, cid)).amount, 0)
        self.play(game, cid); self.assertEqual(game.state.play_history[-1].cost, 0)
        self.portable(game)

    def test_actual_wounded_provider_keeps_separate_condition_and_attack_relation(self):
        game, cid = self.create('END_022', 'ULD_185',
            ('TIME_045', P+'hurt', 'CORE_DS1_185', 'CORE_CS2_117', 'CORE_DS1_185'))
        ident = self.play(game, cid)
        self.assertEqual(game.state.entities[ident].attack, 2)
        self.play(game, P+'hurt', ident)
        self.assertEqual(game.state.entities[ident].attack, 4)
        hero = game.state.players[2].hero_id
        self.play(game, 'CORE_DS1_185', hero)
        self.assertEqual(game.state.entities[hero].health, 26)
        self.portable(game)
        self.play(game, 'CORE_CS2_117', ident)
        self.assertEqual(game.state.entities[ident].attack, 2)
        self.play(game, 'CORE_DS1_185', hero)
        self.assertEqual(game.state.entities[hero].health, 24)
        self.portable(game)

    def test_actual_on_play_overload_and_both_spell_damage_donors(self):
        game, cid = self.create('DRG_211', 'ICC_913')
        self.assertEqual(game.state.players[1].overload_owed, 0)
        ident = self.play(game, cid)
        self.assertEqual(game.state.players[1].overload_owed, 2)
        entity = game.state.entities[ident]
        self.assertIn(Keyword.DIVINE_SHIELD, entity.keywords)
        self.assertEqual(sum(a.spell_damage for a in entity.abilities if a.kind=='spell_damage'), 3)
        self.portable(game)

    def test_actual_native_deathrattle_and_reborn_keep_the_ordered_recipe(self):
        game, cid = self.create('BOT_066', 'JAM_007', ('TIME_045', P+'kill'))
        game.apply(EndTurn(1)); game.apply(EndTurn(2))
        ident = self.play(game, cid); self.play(game, P+'kill', ident)
        token = self.entity(game, 'BOT_066t', zone='board')
        reborn = self.entity(game, cid, zone='board')
        self.assertEqual((token.attack, token.health), (7, 7))
        self.assertEqual(reborn.components, ('BOT_066', 'JAM_007'))
        self.assertEqual(reborn.health, 1)
        self.assertIn(Keyword.DIVINE_SHIELD, reborn.keywords)
        self.assertNotIn(Keyword.REBORN, reborn.keywords)
        self.portable(game)

    def test_actual_floor_and_targeted_battlecry_use_same_new_carrier(self):
        game, cid = self.create('TTN_924', 'RLK_958', (P+'noop',), board=('RLK_503',))
        ally = self.entity(game, 'RLK_503', zone='board')
        self.play(game, cid, ally.id)
        self.assertEqual(game.state.entities[ally.id].attack, 3)
        self.assertEqual(quote_cost(game.state, game.registry, self.entity(game, P+'noop')).amount, 2)
        self.play(game, P+'noop'); self.assertEqual(game.state.play_history[-1].cost, 2)
        self.portable(game)

    def test_actual_native_turn_draw_suppression_is_donated(self):
        game, cid = self.create('TIME_856', 'TIME_617', ('TIME_045',))
        self.play(game, cid)
        own = tuple(game.state.players[1].deck); enemy = tuple(game.state.players[2].deck)
        game.apply(EndTurn(1)); self.assertEqual(len(game.state.players[2].deck), len(enemy)-1)
        game.apply(EndTurn(2)); self.assertEqual(tuple(game.state.players[1].deck), own)
        self.portable(game)

    def test_conditional_material_cannot_be_stripped_duplicated_or_given_foreign_parts(self):
        cid = recipe('END_022', 'ULD_185'); game = self.game((), board=(cid,))
        entity = game.state.entities[game.state.players[1].board[0]]; abilities = tuple(entity.abilities)
        bad = tuple(replace(a, native_condition=None) if a.native_condition else a for a in abilities)
        with self.assertRaises(ValueError):
            validate_condition(game.registry, cid, entity.kind, bad, entity.components)
        relation = next(a for a in abilities if a.kind=='stat_relation')
        with self.assertRaises(ValueError):
            validate_stat_relation(game.registry, cid, entity.kind,
                (*abilities, replace(relation, id=99999)), entity.components)
        with self.assertRaises(ValueError):
            validate_condition(game.registry, cid, entity.kind, abilities, ('END_022', 'ICC_913'))
        with self.assertRaises(ValueError):
            validate_stat_relation(game.registry, cid, entity.kind, abilities, ())


if __name__ == '__main__':
    unittest.main()
