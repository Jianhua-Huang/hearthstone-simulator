"""Expanded source identities and their actual generated effect bodies."""
from dataclasses import asdict, replace
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture, P, FILLER
from hs_sim.cards import build_registry
from hs_sim.cards.assemble_extended_reference_pool import load_batch, register_assemble_extended_reference_pool
from hs_sim.cards.assemble_huckster_reprint import load_batch as huckster_batch
from hs_sim.engine import CardClass, Game, PlayerSetup, Scenario, SelectChoice, Zone
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.assemble_offers import Assemble, candidates
from hs_sim.engine.pools import GenerationContext, sample_candidates
from hs_sim.cards.shadowcrafter_card import QUERY
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch


class AssembleExtendedReferenceTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(lambda mode, role: fixture(mode, role).registry)

    def game(self, hand, *, hero='HERO_03', seed=1):
        fmt = fixture()
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, deck=(FILLER,)*8, max_mana=10, mana=10),
            PlayerSetup('HERO_08', deck=(FILLER,)*8)), seed=seed,
            generation_context=fmt.context), fmt.registry)

    def test_all_259_identities_preserve_class_duplicates_raw_faces_and_explicit_restriction(self):
        data = load_batch(); fmt = fixture(); r = fmt.registry
        original = {row['id']: row for row in batch.read(data['source'])}
        self.assertEqual(batch.sha(data['source']), data['source_sha256'])
        self.assertEqual(sum(g['declared_count'] for g in data['classes']), 264)
        self.assertEqual(len(data['identity_observations']), 264)
        self.assertEqual(len(data['member_ids']), 259)
        self.assertEqual({x['card_id'] for x in data['identity_observations']}, set(data['member_ids']))
        self.assertEqual(sum(x['fragment_kind']=='projection' for x in data['cards']), 19)
        self.assertEqual([x['record']['id'] for x in data['cards'] if x['fragment_kind']=='local_restricted'], ['BE_790'])
        pool = r.pool('constructed.assemble', fmt.context)
        self.assertTrue(pool.complete)
        self.assertEqual([m.card_id for m in pool.members], data['member_ids'])
        self.assertEqual({m.weight for m in pool.members}, {1})
        source = r.pool('constructed.assemble', GenerationContext(data['source_target'], 'experimental'))
        self.assertFalse(source.complete)
        for row in data['cards']:
            self.assertEqual(row['record'], original[row['record']['id']])
            self.assertEqual(batch.canonical(asdict(r.card(row['record']['id']))), row['reviewed_native_definition_sha256'])
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_caverns_reprint_uses_its_own_physical_id_and_primary_verified_deck_identity(self):
        r = fixture().registry; data = huckster_batch()
        self.assertEqual(len(data['official_faces']), 4)
        original = r.card('OG_330'); card = r.card('WON_317')
        self.assertEqual(card.id, 'WON_317')
        self.assertEqual(card.metadata.deck_identity, 'OG_330')
        self.assertEqual(replace(card, id=original.id), original)
        before = asdict(r.assemble_templates['OG_330'])
        after = asdict(r.assemble_templates['WON_317'])
        self.assertTrue(set(before['suffix']['allowed_timings']) <= set(after['suffix']['allowed_timings']))
        after['card_id'] = before['card_id']
        after['suffix']['allowed_timings'] = before['suffix']['allowed_timings']
        self.assertEqual(after, before)

    def test_paid_reprint_death_generates_an_opponent_class_card_without_drawing(self):
        game = self.game(('WON_317', P+'kill'))
        source = self.play(game, 'WON_317'); self.assertEqual(game.state.players[1].mana, 8)
        self.play(game, P+'kill', source)
        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(len(game.state.players[1].hand), 1)
        created = game.state.entities[game.state.players[1].hand[0]]
        self.assertIn(CardClass.MAGE, game.registry.card(created.card_id).metadata.classes)
        self.assertEqual(len(game.state.players[1].deck), 8)
        self.assertFalse(game.state.draw_history)

    def assembled_game(self, primary, donor, half, *, hero):
        probe = self.game((P+'noop', 'BE_702', P+'hurt'), hero=hero)
        spec = Assemble(1, 'constructed.assemble', self.entity(probe, 'BE_702').id, primary_query=QUERY)
        first = candidates(probe.registry, probe._generation_context, probe.state, spec)
        second = candidates(probe.registry, probe._generation_context, probe.state, spec, primary)
        seed = None
        for n in range(30000):
            rng = Random(n)
            if sample_candidates(rng, first, 1, replacement=False)==(primary,) and donor in sample_candidates(rng, second, 2, replacement=False):
                seed = n; break
        self.assertIsNotNone(seed)
        game = self.game((P+'noop', 'BE_702', P+'hurt'), hero=hero, seed=seed)
        self.play(game, P+'noop'); self.play(game, 'BE_702')
        offer = game._frame.options[0].effects[0].offer
        self.assertEqual(offer.primary_card_id, primary)
        self.assertIn(donor, offer.secondary_card_ids)
        self.assertNotIn('BE_790', offer.primary_candidates)
        self.assertNotIn('BE_790', offer.secondary_candidates)
        self.assertEqual(game.state.players[1].mana, 8)
        cid = AssembleRecipe(primary, donor, half).card_id
        option = next(o for o in game._frame.options if o.card_id==cid)
        return game, cid, option.id

    def test_real_combo_offers_reprint_suffix_and_uses_it_as_a_battlecry(self):
        game, cid, option = self.assembled_game('CORE_EX1_319', 'WON_317', 'bottom', hero='HERO_03')
        self.portable(game)
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (option,)))
        self.play(game, cid)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 30)
        self.assertEqual(len(game.state.players[1].deck), 8)
        generated = [game.state.entities[i] for i in game.state.players[1].hand if game.state.entities[i].card_id!=P+'hurt']
        self.assertEqual(len(generated), 1)
        self.assertIn(CardClass.MAGE, game.registry.card(generated[0].card_id).metadata.classes)
        self.portable(game)

    def test_foreign_class_combo_can_use_reprint_as_primary_and_react_without_its_original_death(self):
        game, cid, option = self.assembled_game('WON_317', 'CORE_EX1_007', 'top', hero='HERO_02')
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (option,)))
        source = self.play(game, cid)
        self.assertEqual(game.state.players[1].hand, [self.entity(game, P+'hurt').id])
        self.play(game, P+'hurt', source)
        self.assertEqual(len(game.state.players[1].hand), 1)
        created = game.state.entities[game.state.players[1].hand[0]]
        self.assertIn(CardClass.MAGE, game.registry.card(created.card_id).metadata.classes)
        self.assertEqual(len(game.state.players[1].deck), 8)
        self.assertFalse(game.state.draw_history)
        self.assertEqual(game.state.entities[source].zone, Zone.BOARD)
        self.portable(game)

    def test_changed_alias_or_removed_restriction_is_rejected_before_inventory_registration(self):
        for cid in ('WON_317', 'BE_790'):
            with self.subTest(card=cid):
                r = batch.registration_prefix(build_registry,
                    'hs_sim.cards.assemble_extended_reference_pool.register_assemble_extended_reference_pool',
                    register_assemble_extended_reference_pool)
                before = tuple(r.pools)
                if cid=='WON_317': r._cards[cid] = replace(r.card(cid), health=4)
                else: del r._assemble_local_restrictions[cid]
                with self.assertRaises(TargetValidationError): register_assemble_extended_reference_pool(r)
                self.assertEqual(tuple(r.pools), before)


if __name__ == '__main__':
    unittest.main()
