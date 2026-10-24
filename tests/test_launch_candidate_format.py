"""Complete launch inventory, isolated deck bans and explicit unsupported roots."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hs_sim.candidate_format import build_cn37_candidate_format
from hs_sim.cards import build_registry
from hs_sim.engine import (
    CardClass, CardDefinition, CardType, DeckSpec, Game, Keyword, PlayCard,
    PlayerSetup, Rarity, Scenario, SelectChoice, SnapshotError,
)
from hs_sim.engine.construction import DeckValidationError, validate_deck
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.pools import PoolQuery, resolve_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.launch_candidate_format import (
    BATCH_PATH, OBSERVED_BANS, build_cn37_launch_candidate_format, load_batch,
    register_launch_pool_metadata,
)
from hs_sim.targets import TargetValidationError, canonical_digest


NEW = 'BE_193'
UNKNOWN = ('BE_588',)


def fillers(fmt, count):
    cards, used = [], Counter()
    for cid in fmt.root_card_ids:
        if cid == NEW or cid not in fmt.registry.cards:
            continue
        card = fmt.registry.card(cid)
        if (card.kind != CardType.MINION or card.metadata.classes != (CardClass.NEUTRAL,) or
                card.metadata.rarity == Rarity.LEGENDARY or card != CardDefinition(card.id, card.name,
                    card.kind, cost=card.cost, attack=card.attack, health=card.health,
                    keywords=card.keywords, metadata=card.metadata)):
            continue
        identity = card.metadata.deck_identity or cid
        while used[identity] < (card.metadata.max_copies or 2) and len(cards) < count:
            cards.append(cid)
            used[identity] += 1
        if len(cards) == count:
            return tuple(cards)
    raise AssertionError('Missing plain neutral source fillers')


def deck(fmt, cards=None):
    return DeckSpec('HERO_08', fmt.registry.card('HERO_08').initial_hero_power, CardClass.MAGE,
        fillers(fmt, 30) if cards is None else cards)


class LaunchCandidateFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fmt = build_cn37_launch_candidate_format()
        cls.reader = build_cn37_launch_candidate_format()
        cls.previous = build_cn37_candidate_format()

    def portable(self, game):
        saved = json.loads(json.dumps(game.snapshot()))
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(deepcopy(saved), self.reader.registry).snapshot(), saved)
        self.assertEqual(replay(build_replay(game), self.reader.registry).snapshot(), saved)
        return saved

    def scenario(self, hand):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, mana=10, max_mana=10),
            PlayerSetup('HERO_08')), seed=453, generation_context=self.fmt.context), self.fmt.registry)

    def test_full_roots_minions_and_missing_definitions_have_distinct_meanings(self):
        f = self.fmt
        self.assertEqual(len(f.root_card_ids), 1322)
        self.assertEqual(f.unimplemented_root_card_ids, UNKNOWN)
        self.assertEqual(tuple(m.card_id for m in f.registry.pool('constructed.cards', f.context).members),
            f.root_card_ids)
        minions = f.registry.pool('constructed.minions', f.context)
        self.assertEqual(len(minions.members), 811)
        self.assertTrue(all(f.registry.pool_card(m.card_id).kind == CardType.MINION for m in minions.members))
        self.assertEqual({m.weight for m in minions.members}, {1})
        for cid in UNKNOWN:
            self.assertIn(cid, f.policy.allowed_card_ids)
            self.assertIn(cid, f.registry.pool_cards)
            self.assertNotIn(cid, f.registry.cards)

    def test_historical_prelaunch_domain_and_default_definitions_stay_exact(self):
        original = build_registry()
        self.assertEqual(self.fmt.registry.cards, original.cards)
        self.assertEqual(len(self.previous.root_card_ids), 1188)
        self.assertNotIn(NEW, self.previous.root_card_ids)
        self.assertEqual(self.previous.effective_until, '2026-10-21T01:00:00+08:00')
        self.assertFalse(self.previous.policy.banned_card_ids)
        self.assertNotEqual(self.fmt.target_id, self.previous.target_id)
        self.assertTrue(all(self.fmt.registry.pool_card(cid) == value for cid, value in original.pool_cards.items()))

    def test_real_thirty_card_opening_includes_new_root_and_complete_original_decks(self):
        f = self.fmt
        cards = (NEW, NEW, *fillers(f, 28))
        own, other = deck(f, cards), deck(f)
        self.assertTrue(validate_deck(own, f.registry, f.policy).valid)
        game = f.new_game((own, other), seed=453, first_player=1)
        self.assertEqual(game.state.players[1].original_deck, cards)
        self.assertIsNotNone(game.state.pending_choice)
        self.portable(game)
        while game.state.pending_choice is not None:
            q = game.state.pending_choice
            game.apply(SelectChoice(q.player_id, q.id, ()))
        self.assertEqual(game.snapshot()['generation_context']['starting_decks'],
            [list(cards), list(other.cards)])
        self.portable(game)

    def test_real_new_minion_can_be_paid_and_played_in_launch_context(self):
        game = self.scenario((NEW,))
        source = game.state.players[1].hand[0]
        game.apply(PlayCard(1, source))
        self.assertIn(source, game.state.players[1].board)
        self.assertEqual(game.state.players[1].mana, 9)
        self.assertIn(Keyword.POISONOUS, game.state.entities[source].keywords)
        self.assertEqual(game.state.play_history[-1].card_id, NEW)
        self.portable(game)

    def test_observed_deck_bans_reject_actual_known_roots_without_certifying_CN(self):
        f = self.fmt
        self.assertEqual(f.policy.banned_card_ids, OBSERVED_BANS)
        self.assertFalse(f.cn_bans_verified)
        self.assertFalse(f.formal_pool_complete)
        self.assertFalse(f.policy.pool_complete)
        with self.assertRaises(TargetValidationError):
            f.require_formal()
        for cid in OBSERVED_BANS:
            with self.subTest(card=cid):
                report = validate_deck(deck(f, (cid, *fillers(f, 29))), f.registry, f.policy)
                self.assertIn('format_legality', {i.code for i in report.issues})
                self.assertNotIn('unsupported_definition', {i.code for i in report.issues})

    def test_missing_roots_are_rejected_when_actually_requested_by_a_deck(self):
        f = self.fmt
        for cid in UNKNOWN:
            with self.subTest(card=cid):
                own = deck(f, (cid, *fillers(f, 29)))
                report = validate_deck(own, f.registry, f.policy)
                self.assertIn('unsupported_definition', {i.code for i in report.issues})
                with self.assertRaises(DeckValidationError):
                    f.new_game((own, deck(f)), seed=453, first_player=1)

    def test_implemented_translator_is_a_real_legal_root_and_uses_paid_battlecry(self):
        cid = 'BE_327'; f = self.fmt
        self.assertIn(cid, f.root_card_ids)
        self.assertNotIn(cid, f.unimplemented_root_card_ids)
        self.assertTrue(validate_deck(deck(f, (cid, *fillers(f, 29))), f.registry, f.policy).valid)
        game = self.scenario((cid,)); source = game.state.players[1].hand[0]
        game.apply(PlayCard(1, source))
        self.assertIn(source, game.state.players[1].board)
        self.assertEqual(game.state.players[1].mana, 6)
        self.assertEqual(game.state.play_history[-1].card_id, cid)
        self.assertEqual(len([event for event in game.events if event.source_id == source and
            dict(event.data).get('producer') == 'effect_branch']), 1)

    def test_deck_bans_do_not_silently_remove_random_inventory_members(self):
        f = self.fmt
        domain = {m.card_id for m in f.registry.pool('constructed.cards', f.context).members}
        self.assertTrue(set(OBSERVED_BANS) <= domain)
        for cid, cost in (('DINO_402', 8), ('TIME_030', 5)):
            query = PoolQuery(kinds=(CardType.SPELL,), min_cost=cost, max_cost=cost, class_mode='any')
            candidates = resolve_candidates(f.registry, f.context, 'constructed.cards', query)
            self.assertIn(cid, {m.card_id for m in candidates})
        quests = resolve_candidates(f.registry, f.context, 'constructed.cards',
            PoolQuery(kinds=(CardType.SPELL,), class_mode='any'))
        self.assertNotIn('TLC_817', {m.card_id for m in quests})  # Original quest rule remains independent.

    def test_unknown_qualifying_source_is_not_filtered_or_chosen_away(self):
        f = self.fmt
        with self.assertRaises(UnsupportedDefinitionError):
            resolve_candidates(f.registry, f.context, 'constructed.cards',
                PoolQuery(kinds=(CardType.MINION,), min_cost=1, max_cost=1, class_mode='any'))
        game = self.scenario(('CORE_EX1_189',))
        source = game.state.players[1].hand[0]
        before = game.snapshot()
        with self.assertRaises(ResolutionError) as caught:
            game.apply(PlayCard(1, source))
        self.assertIsInstance(caught.exception.__cause__, UnsupportedDefinitionError)
        self.assertEqual(game.snapshot(), before)

    def test_real_decoded_body_queries_the_whole_launch_deathrattle_domain(self):
        game = self.scenario(('BE_327t',))
        source = game.state.players[1].hand[0]
        game.apply(PlayCard(1, source))
        children = [game.state.entities[i] for i in game.state.players[1].board if i != source]
        self.assertEqual(len(children), 2)
        self.assertTrue(all(self.fmt.registry.pool_card(e.card_id).cost == 2 and
            self.fmt.registry.pool_card(e.card_id).deathrattle for e in children))
        self.portable(game)

    def test_zero_fields_and_missing_XML_keyword_flags_have_complete_dual_primary_faces(self):
        data = load_batch()
        self.assertEqual([i['record']['id'] for i in data['zero_cost_evidence']], ['BE_071'])
        self.assertEqual([i['record']['id'] for i in data['zero_attack_evidence']], ['BE_196', 'BE_207'])
        self.assertEqual(data['printed_keyword_overrides'], {'BE_171': ['taunt'], 'BE_702': ['combo']})
        for item in data['zero_cost_evidence'] + data['zero_attack_evidence'] + data['keyword_override_evidence']:
            self.assertEqual(canonical_digest(item['record']), item['record_sha256'])
            self.assertEqual({o['locale'] for o in item['official_observations']}, {'zh_CN', 'en_US'})
            self.assertTrue(all(o['face']['id'] == item['record']['dbf_id'] for o in item['official_observations']))
        self.assertIn(Keyword.TAUNT, self.fmt.registry.pool_card('BE_171').keywords)
        self.assertIn(Keyword.COMBO, self.fmt.registry.pool_card('BE_702').keywords)
        self.assertIn(Keyword.OLD_GOD, self.fmt.registry.pool_card('BE_009').keywords)

    def test_all_new_metadata_is_validated_before_any_pending_row_is_installed(self):
        registry = build_registry()
        data = load_batch()
        cid = next(item['record']['id'] for item in reversed(data['additional_cards'])
            if item['record']['id'] in registry.pool_cards)
        registry._pool_cards[cid] = replace(registry.pool_card(cid), cost=registry.pool_card(cid).cost + 1)
        before = dict(registry.pool_cards)
        with self.assertRaises(TargetValidationError):
            register_launch_pool_metadata(registry)
        self.assertEqual(dict(registry.pool_cards), before)
        self.assertIn('BE_327', registry.pool_cards)
        self.assertNotIn('BE_588', registry.pool_cards)

    def test_changed_frozen_phase_or_source_is_rejected_before_registry_work(self):
        data = load_batch()
        for key, value in (('region', 'EU'), ('patch', '37.2'), ('source_sha256', '0' * 64),
                ('client_version', '37.0.1'), ('expansion_launched_at', '2026-10-20T00:00:00Z')):
            bad = deepcopy(data)
            bad[key] = value
            with self.subTest(field=key), patch('hs_sim.launch_candidate_format.load_batch', return_value=bad), \
                    patch('hs_sim.launch_candidate_format.build_registry', side_effect=AssertionError('Registry work')):
                with self.assertRaises(TargetValidationError):
                    build_cn37_launch_candidate_format()

    def test_tampered_catalog_evidence_or_complete_claim_cannot_reuse_binding(self):
        original = load_batch()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.json'
            for kind in ('missing_root', 'ban', 'CN_claim', 'numeric_face'):
                bad = deepcopy(original)
                if kind == 'missing_root': bad['candidate_root_ids'].remove('BE_327')
                elif kind == 'ban': bad['experimental_deck_bans'] = []
                elif kind == 'CN_claim': bad['cn_bans_verified'] = True
                else: bad['zero_attack_evidence'][0]['official_observations'][0]['face']['attack'] = 1
                path.write_text(json.dumps(bad), encoding='utf-8')
                with self.subTest(kind=kind), patch('hs_sim.launch_candidate_format.BATCH_PATH', path), \
                        self.assertRaises(TargetValidationError):
                    load_batch()

    def test_restore_cannot_mix_prelaunch_and_launch_registry_identities(self):
        game = self.scenario((NEW,))
        saved = self.portable(game)
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, self.previous.registry)
        self.assertEqual(self.fmt.target_id, self.reader.target_id)
        self.assertIsNone(self.fmt.effective_until)
        self.assertEqual(self.fmt.effective_from, load_batch()['ban_observed_at'])

    def test_launch_builder_uses_no_outputs_or_network_at_runtime(self):
        original = Path.read_text
        outputs = Path(__file__).resolve().parents[1] / 'outputs'
        def checked(path, *args, **kwargs):
            self.assertFalse(path.resolve().is_relative_to(outputs))
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', checked), \
                patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected network')):
            other = build_cn37_launch_candidate_format()
        self.assertEqual(other.registry.fingerprint(), self.fmt.registry.fingerprint())


if __name__ == '__main__':
    unittest.main()
