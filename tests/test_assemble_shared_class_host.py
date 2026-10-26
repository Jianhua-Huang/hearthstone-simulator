"""The full declared shared pool through its actual twelve producers."""
from dataclasses import asdict, replace
from random import Random
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture, P, FILLER
from hs_sim.cards import build_registry
from hs_sim.cards.assemble_shared_class_pool import load_batch, register_assemble_shared_class_pool
from hs_sim.engine import CardClass, Game, PlayerSetup, Scenario, SelectChoice
from hs_sim.engine.assemble_faces import AssembleRecipe, PREFIX, text_source, prefix_timings
from hs_sim.engine.assemble_offers import Assemble, candidates, ResolveAssemble
from hs_sim.engine.pools import PoolQuery, sample_candidates
from hs_sim.engine.registry import RuleContext
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

SOURCES = ('BE_571', 'BE_262', 'BE_851', 'BE_553', 'BE_257', 'BE_229',
    'BE_045', 'BE_702', 'BE_114', 'BE_087', 'BE_740', 'BE_044')
HEROES = dict(death_knight='HERO_11', demon_hunter='HERO_10', druid='HERO_06',
    hunter='HERO_05', mage='HERO_08', paladin='HERO_04', priest='HERO_09',
    rogue='HERO_03', shaman='HERO_02', warlock='HERO_07', warrior='HERO_01', neutral='HERO_08')


class AssembleSharedClassHostTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(lambda mode, role: fixture(mode, role).registry)

    def game(self, source, extra=(), seed=1):
        fmt = fixture(); card = fmt.registry.card(source)
        hero = HEROES[card.metadata.classes[0].value]
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=(source, *extra), deck=(FILLER,)*8, max_mana=10, mana=10),
            PlayerSetup('HERO_08', deck=(FILLER,)*8)), seed=seed,
            generation_context=fmt.context), fmt.registry)

    def offer(self, game):
        return game._frame.options[0].effects[0].offer

    def choose_option(self, game, option=None):
        choice = game.state.pending_choice
        selected = option or game._frame.options[0]
        game.apply(SelectChoice(choice.player_id, choice.id, (selected.id,)))

    def test_all_class_panels_and_214_original_identities_are_bound_without_widget_inference(self):
        data = load_batch(); fmt = fixture(); r = fmt.registry
        self.assertEqual([g['declared_count'] for g in data['classes']],
            [16, 23, 15, 18, 14, 17, 14, 7, 10, 12, 15, 57])
        self.assertEqual(sum(len(g['member_ids']) for g in data['classes']), 218)
        self.assertEqual(len(data['member_ids']), 214)
        pool = r.pool('constructed.assemble', fmt.context)
        self.assertTrue(pool.complete)
        self.assertEqual(tuple(m.card_id for m in pool.members), tuple(data['member_ids']))
        self.assertEqual({m.weight for m in pool.members}, {1})
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])
        for row in data['cards']:
            card = r.card(row['record']['id'])
            self.assertEqual(batch.canonical(asdict(card)), row['reviewed_native_definition_sha256'])
        self.assertIn('JAIL_376', data['member_ids'])
        self.assertIn('TLC_EVENT_402', data['member_ids'])

    def test_all_twelve_paid_native_sources_offer_and_deliver_from_full_pool(self):
        inventory = set(load_batch()['member_ids'])
        for source in SOURCES:
            with self.subTest(source=source):
                game = self.game(source, (P+'noop',) if source=='BE_702' else ())
                if source=='BE_702': self.play(game, P+'noop')
                self.play(game, source)
                self.assertEqual(game.state.players[1].mana, 10-game.registry.card(source).cost)
                offer = self.offer(game); r = game.registry; primary = r.card(offer.primary_card_id)
                self.assertTrue(set(offer.primary_candidates) <= inventory)
                self.assertTrue(set(offer.secondary_candidates) <= inventory)
                if source=='BE_044': self.assertEqual(primary.cost, 4)
                if source=='BE_262': self.assertEqual(primary.cost, 1)
                if source=='BE_851': self.assertTrue(set(primary.metadata.tribes) & {'beast', 'all'})
                if source=='BE_553': self.assertTrue(set(primary.metadata.tribes) & {'mech', 'all'})
                if source=='BE_257': self.assertIn(CardClass.MAGE, primary.metadata.classes)
                if source=='BE_229': self.assertIn('end_turn', prefix_timings(text_source(r, primary.id, primary=True).prefix))
                if source=='BE_571': self.assertIn('deathrattle', prefix_timings(text_source(r, primary.id, primary=True).prefix))
                if source=='BE_045':
                    self.assertLessEqual(primary.cost, 3)
                    self.assertTrue(all(r.card(c).cost>=5 for c in offer.secondary_candidates))
                if source=='BE_702':
                    self.assertNotIn(CardClass.ROGUE, primary.metadata.classes)
                    self.assertNotIn(CardClass.NEUTRAL, primary.metadata.classes)
                    self.assertTrue(all(any(c in r.card(cid).metadata.classes for c in (CardClass.ROGUE, CardClass.NEUTRAL))
                        for cid in offer.secondary_candidates))
                option = game._frame.options[0]
                expected = option.card_id
                self.choose_option(game, option)
                created = self.entity(game, expected)
                self.assertTrue(created.card_id.startswith(PREFIX))
                self.assertEqual(r.card(created.card_id).cost, primary.cost)
                if source=='BE_553': self.assertIn('BE_553t', [game.state.entities[i].card_id for i in game.state.players[1].hand])

    def test_full_pool_choice_restores_and_generated_pyromancer_draw_body_is_playable(self):
        fmt = fixture(); r = fmt.registry; primary = 'CORE_NEW1_020'; donor = 'CORE_EX1_007'
        probe_game = self.game('BE_114')
        source = self.entity(probe_game, 'BE_114').id
        spec = Assemble(1, 'constructed.assemble', source)
        first = candidates(r, fmt.context, probe_game.state, spec)
        second = candidates(r, fmt.context, probe_game.state, spec, primary)
        selected_seed = None
        for seed in range(20000):
            rng = Random(seed)
            if sample_candidates(rng, first, 1, replacement=False)==(primary,):
                if donor in sample_candidates(rng, second, 2, replacement=False):
                    selected_seed = seed; break
        self.assertIsNotNone(selected_seed)
        game = self.game('BE_114', (P+'noop',), selected_seed)
        self.play(game, 'BE_114'); self.assertEqual(self.offer(game).primary_card_id, primary)
        self.portable(game)
        for player in (1, 2):
            view = json.dumps(game.for_player(player).observe())
            for field in ('primary_candidates', 'secondary_candidates', 'rng_before', 'rng_after'):
                self.assertNotIn('"'+field+'"', view)
        cid = AssembleRecipe(primary, donor, 'bottom').card_id
        option = next(o for o in game._frame.options if o.card_id==cid)
        self.choose_option(game, option)
        self.assertEqual(self.entity(game, cid).cost, 0)
        self.play(game, cid)
        deck = len(game.state.players[1].deck)
        self.play(game, P+'noop')
        self.assertEqual(len(game.state.players[1].deck), deck-1)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 30)
        self.portable(game)

    def test_changed_native_definition_is_rejected_before_pool_registration(self):
        r = batch.registration_prefix(build_registry,
            'hs_sim.cards.assemble_shared_class_pool.register_assemble_shared_class_pool',
            register_assemble_shared_class_pool)
        original = r.card('CORE_EX1_007')
        r._cards[original.id] = replace(original, health=original.health+1)
        before = tuple(r.pools)
        with self.assertRaises(TargetValidationError): register_assemble_shared_class_pool(r)
        self.assertEqual(tuple(r.pools), before)

    def test_source_operands_do_not_borrow_another_minions_death_record(self):
        fmt = fixture(); r = fmt.registry
        cid = AssembleRecipe('CORE_NEW1_020', 'BE_859', 'bottom').card_id
        game = Game.from_scenario(Scenario((
            PlayerSetup('HERO_06', board=(FILLER, cid, FILLER), hand=(P+'kill',),
                deck=(FILLER,)*8, max_mana=10, mana=10),
            PlayerSetup('HERO_08', board=('BOT_066t',), deck=(FILLER,)*8)),
            generation_context=fmt.context), r)
        source = game.state.players[1].board[1]
        victim = game.state.players[2].board[0]
        self.play(game, P+'kill', victim)
        death = game.state.death_history[-1]
        self.assertNotEqual(death.attack, game.state.entities[source].attack)
        context = RuleContext(game.state, source, 1, death=death)
        for donor in ('BE_859', 'FIR_953', 'TLC_479'):
            body = r.behavior(text_source(r, donor).suffix.behavior_id)
            self.assertEqual(body(context), body(replace(context, death=None)), donor)
        self.portable(game)


if __name__ == '__main__':
    unittest.main()
