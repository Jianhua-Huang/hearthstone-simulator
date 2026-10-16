"""R-150: necessary Vexallus integration under the paid hand-spell profile.

Synthetic cards expose a late acceptance window and a last-extra choice only.
They are local fixtures, never new representative rows or automatic-cast rules.
"""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from hs_sim.targets import TargetValidationError, canonical_digest, load_baseline
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, GenerationContext, PlayCard, PlayerSetup, Rarity, Scenario,
    SelectChoice, SnapshotError, SpellRepeatSpec, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion,
    GainArmor, RequestChoice, ReturnToHand, Silence, Summon)
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import RecipientMetadataFilter, RepeatMatchSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import (CARD_LIMITATIONS, EXPECTED_CARD_HASHES,
    build_registry)
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_modifiers import AddSpellRepeatModifier
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION


ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'RLK_541'
ARCANE = 'RLK_843'
PIN = '1dffa975913600e7435fd0172399c7686a044f403284dcf6013e07511cf5add1'
OLD_ROWS_PIN = 'e265456d67990d964e01181b70a8bb184121a8cec272bebb8988895812977324'
CONTEXT = GenerationContext('local-2026-09-23', 'experimental')


def arcane_spec(casts=2):
    return SpellRepeatSpec(casts, 'any', RepeatMatchSpec(
        RecipientMetadataFilter(spell_schools=(SpellSchool.ARCANE,))))


def representative_fixture_registry():
    """A fresh real registry plus the same small, explicit synthetic overlay."""
    registry = build_registry()

    def spell(card, behavior, *, school=None, cost=0, target=False):
        registry.register_behavior(card, behavior)
        registry.register_card(CardDefinition(card, card, CardType.SPELL,
            cost=cost, on_play=card, requires_target=target, spell_school=school,
            metadata=CardMetadata(False, (CardClass.MAGE,), None)))

    spell('fixture.policy', lambda c: [AddSpellRepeatModifier(
        c.player_id, arcane_spec(3), c.source_id, uses=2)])
    spell('fixture.take', lambda c: [ChangeControl(c.target_id, c.player_id)], target=True)
    for mode in ('current', 'base'):
        spell('fixture.copy.' + mode, lambda c, mode=mode: [CopyMinion(
            c.target_id, c.player_id, mode=mode)], target=True)

    def last_extra(c):
        if c.cast.iteration == 1:
            carrier = c.play.spell_payload.contributors[0].carrier_id
            return [ReturnToHand(carrier), GainArmor(c.player_id, 1)]
        return [RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue',
            (GainArmor(c.player_id, 1),)),), source_id=c.source_id)]

    spell('fixture.last_extra', last_extra, school=SpellSchool.ARCANE, cost=1)

    def committed(c, add):
        if c.event.source_id is None or c.state.entities[c.event.source_id].card_id != ARCANE:
            return []
        if add:
            return [Summon(c.player_id, SOURCE)]
        return [Silence(i) for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id == SOURCE]

    for card, add in (('fixture.commit.add', True), ('fixture.commit.silence', False)):
        registry.register_behavior(card, lambda c, add=add: committed(c, add))
        registry.register_card(CardDefinition(card, card, CardType.MINION,
            health=4, triggers=(TriggerSpec('card_committed', card),)))

    def bounce_target(c):
        target = c.state.entities.get(c.event.target_id)
        return [ReturnToHand(target.id)] if target is not None and target.card_id == 'CS2_182' else []

    registry.register_behavior('fixture.target.return', bounce_target)
    registry.register_card(CardDefinition('fixture.target.return', 'fixture.target.return',
        CardType.MINION, health=4,
        triggers=(TriggerSpec('damage_dealt', 'fixture.target.return'),)))
    return registry


class SpellMatchRepresentativeTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry()
        self.factory = build_registry

    def use_fixtures(self):
        self.factory = representative_fixture_registry
        self.registry = self.factory()

    def game(self, *, hand=(), board=(SOURCE,), enemy=(), enemy_hand=(),
             hero='HERO_08', max_mana=10, mana=None):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, board=board, hand=hand, deck=('CS2_182',) * 8,
                max_mana=max_mana, mana=max_mana if mana is None else mana),
            PlayerSetup('HERO_01', board=enemy, hand=enemy_hand,
                deck=('CS2_182',) * 8, max_mana=10, mana=10)),
            seed=150, generation_context=CONTEXT), self.registry)

    def play(self, game, card, target=None):
        owner = game.state.active_player
        entity = next(i for i in game.state.players[owner].hand
            if game.state.entities[i].card_id == card)
        game.apply(PlayCard(owner, entity, target))
        return entity

    def hero(self, game, owner=2):
        return game.state.entities[game.state.players[owner].hero_id]

    def subject(self, game):
        return next(p for p in reversed(game.state.play_history) if p.kind == CardType.SPELL)

    def casts(self, game, play=None):
        return [c for c in game.state.cast_history if c.play_id == (play or self.subject(game)).id]

    def sources(self, game, owner=1):
        return [game.state.entities[i] for i in game.state.players[owner].board
            if game.state.entities[i].card_id == SOURCE]

    def portable(self, game):
        snapshot = json.loads(json.dumps(game.snapshot()))
        restored = Game.from_snapshot(snapshot, self.factory())
        self.assertEqual(restored.snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), self.factory()).snapshot(), snapshot)
        return restored

    def assert_one_hand_root(self, game, play, source_id):
        for kind in ('card_committed', 'card_played'):
            self.assertEqual(len([e for e in game.events
                if e.kind == kind and e.source_id == source_id]), 1)
        self.assertTrue(play.completed)
        self.assertTrue(play.spell_acceptance_closed)

    def waiting_game(self, *, enemy_hand=()):
        self.use_fixtures()
        game = self.game(hand=('fixture.last_extra', ARCANE), enemy_hand=enemy_hand)
        carrier = self.sources(game)[0].id
        self.play(game, 'fixture.last_extra')
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(game.state.entities[carrier].zone, Zone.HAND)
        self.assertFalse(self.sources(game))
        self.assertEqual(self.hero(game, 1).armor, 1)
        return game, carrier

    def test_complete_raw_pin_and_printed_adapter_match_the_independent_pre_audit(self):
        raw = next(r for r in json.loads((ROOT / 'data/extracted/cards.json').read_text(
            encoding='utf-8')) if r['id'] == SOURCE)
        audit = json.loads((ROOT / 'outputs/v109-rlk541-pre-audit.json').read_text(encoding='utf-8'))
        saved = next(r['raw'] for r in audit['catalog'] if r['card_id'] == SOURCE)
        row = next(r for r in load_baseline().support['cards'] if r['id'] == SOURCE)
        self.assertEqual(raw, saved)
        self.assertEqual(row['data'], raw)
        self.assertEqual((canonical_digest(raw), row['data_sha256'], EXPECTED_CARD_HASHES[SOURCE]),
            (PIN,) * 3)
        card = self.registry.card(SOURCE)
        self.assertEqual((card.kind, card.cost, card.attack, card.health),
            (CardType.MINION, 5, 3, 5))
        self.assertEqual((card.metadata.classes, card.metadata.rarity,
            card.metadata.collectible, card.metadata.tribes),
            ((CardClass.MAGE,), Rarity.LEGENDARY, True, ('elemental',)))
        self.assertEqual(card.spell_repeats, (arcane_spec(),))
        self.assertEqual((card.on_play, card.battlecry, card.deathrattle, card.triggers, card.auras),
            (None, None, None, (), ()))
        self.assertIn('R-150', CARD_LIMITATIONS[SOURCE])
        self.assertIn('R-149', CARD_LIMITATIONS[SOURCE])

    def test_recomputed_tampered_new_raw_digest_does_not_bypass_the_adapter_pin(self):
        baseline = load_baseline()
        row = next(r for r in baseline.support['cards'] if r['id'] == SOURCE)
        row['data']['health'] = 6
        row['data_sha256'] = canonical_digest(row['data'])
        with patch('hs_sim.engine.representative.load_baseline', return_value=baseline):
            with self.assertRaises(TargetValidationError):
                build_registry()

    def test_only_one_partial_representative_row_is_added_without_runtime_versions_changing(self):
        support = load_baseline().support
        old = [r for r in support['cards'] if r['id'] != SOURCE]
        self.assertEqual((len(old), canonical_digest(old)), (304, OLD_ROWS_PIN))
        self.assertEqual((self.registry.version, len(self.registry.cards), len(EXPECTED_CARD_HASHES)),
            ('representative-m5-v65', 311, 305))
        self.assertEqual(sum(c.choice_only for c in self.registry.cards.values()), 14)
        row = next(r for r in support['cards'] if r['id'] == SOURCE)
        self.assertEqual((row['implementation'], row['stage'], row['mode_legality']),
            ('partial', 'M5', {'standard': None, 'wild': None}))
        self.assertEqual(row['reachable_cards'], [])
        game = self.game()
        self.assertEqual((game.ruleset.id, game.mechanics.version, game.snapshot()['schema_version']),
            ('prototype-v302', CORE_EFFECTS_VERSION, SNAPSHOT_SCHEMA_VERSION))
        self.assertEqual(game.observe(1)['version'], 'player-view-v86')
        self.assertEqual(game.for_player(1).observe()['version'], 'player-actions-v12')
        self.assertEqual(build_replay(game)['schema_version'], 1)

    def test_real_paid_source_and_same_class_bolt_repeat_with_frozen_manathirst(self):
        for maximum, amount in ((7, 2), (10, 3)):
            with self.subTest(maximum=maximum):
                game = self.game(board=(), hand=(SOURCE, ARCANE), max_mana=maximum)
                carrier = self.play(game, SOURCE)
                ability = active_abilities(game.state.entities[carrier], 'spell_repeat')[0]
                self.assertEqual((ability.origin, ability.source_id, ability.spell_repeat),
                    ('printed', carrier, arcane_spec()))
                source = self.play(game, ARCANE, self.hero(game).id)
                play = self.subject(game)
                self.assertEqual(self.hero(game).health, 30 - 2 * amount)
                self.assertEqual(game.state.players[1].mana, maximum - 6)
                self.assertEqual(len(game.state.play_history), 2)
                self.assertEqual([(c.iteration, c.manathirst, c.target_id) for c in self.casts(game)],
                    [(1, maximum >= 8, self.hero(game).id), (2, maximum >= 8, self.hero(game).id)])
                self.assertEqual([(s.carrier_id, s.ability) for s in play.spell_payload.contributors],
                    [(carrier, ability)])
                self.assertEqual(play.spell_payload.casts, 2)
                self.assert_one_hand_root(game, play, source)
                self.portable(game)
        game = self.game(hand=(ARCANE,), mana=1)
        self.play(game, ARCANE, self.hero(game).id)
        self.assertEqual((game.state.players[1].mana, self.hero(game).health), (0, 24))
        self.assertTrue(all(c.manathirst for c in self.casts(game)))

    def test_real_fire_frost_and_schoolless_coin_remain_single_casts(self):
        for card, damage, cost, school in (
                ('CS2_029', 6, 4, SpellSchool.FIRE),
                ('CS2_024', 3, 2, SpellSchool.FROST),
                ('GAME_005', 0, 0, None)):
            with self.subTest(card=card):
                game = self.game(hand=(card,), mana=5)
                source = self.play(game, card, self.hero(game).id if damage else None)
                play = self.subject(game)
                self.assertEqual(self.registry.card(card).spell_school, school)
                self.assertEqual(self.hero(game).health, 30 - damage)
                self.assertEqual(game.state.players[1].mana, 6 if card == 'GAME_005' else 5 - cost)
                self.assertEqual(game.state.players[1].temporary_mana, int(card == 'GAME_005'))
                self.assertEqual(self.hero(game).frozen, card == 'CS2_024')
                self.assertEqual((len(self.casts(game)), play.spell_payload.casts,
                    play.spell_payload.contributors), (1, 1, ()))
                self.assertFalse(game.state.spell_repeats)
                self.assert_one_hand_root(game, play, source)
                self.portable(game)

    def test_duplicate_real_sources_and_sinestra_keep_full_ids_but_merge_max(self):
        for hero, expected_count in (('HERO_08', 2), ('HERO_01', 3)):
            with self.subTest(hero=hero):
                game = self.game(hand=(ARCANE,), board=(SOURCE, SOURCE, 'CATA_154'), hero=hero)
                expected = [(i, active_abilities(game.state.entities[i], 'spell_repeat')[0])
                    for i in game.state.players[1].board[:expected_count]]
                self.play(game, ARCANE, self.hero(game).id)
                contributors = self.subject(game).spell_payload.contributors
                self.assertEqual([(s.carrier_id, s.ability) for s in contributors], expected)
                self.assertEqual(len({s.ability.id for s in contributors}), expected_count)
                self.assertEqual((self.subject(game).spell_payload.casts,
                    len(self.casts(game)), self.hero(game).health), (2, 2, 24))
                self.portable(game)

    def test_higher_player_policy_keeps_both_lower_real_sources_and_spends_one_use(self):
        self.use_fixtures()
        game = self.game(hand=('fixture.policy', ARCANE), board=(SOURCE, SOURCE))
        self.play(game, 'fixture.policy')
        self.play(game, ARCANE, self.hero(game).id)
        play = self.subject(game)
        self.assertEqual((play.spell_payload.casts, len(self.casts(game)), self.hero(game).health),
            (3, 3, 21))
        self.assertEqual([s.ability.spell_repeat.casts for s in play.spell_payload.contributors], [2, 2])
        self.assertEqual([s.carrier_id for s in play.spell_payload.contributors],
            [e.id for e in self.sources(game)])
        self.assertEqual(play.spell_submission.modifiers[0].uses_remaining, 2)
        self.assertEqual(game.state.players[1].spell_modifiers[0].uses_remaining, 1)
        self.assertEqual(game.state.players[1].mana, 9)
        self.portable(game)

    def test_real_counterspell_pays_once_and_denies_payload_after_submission_consumption(self):
        self.use_fixtures()
        game = self.game(hand=('fixture.policy', ARCANE), enemy_hand=('EX1_287',))
        self.play(game, 'fixture.policy')
        game.apply(EndTurn(1))
        self.play(game, 'EX1_287')
        game.apply(EndTurn(2))
        source = self.play(game, ARCANE, self.hero(game).id)
        play = self.subject(game)
        self.assertTrue(play.countered)
        self.assertIsNone(play.spell_payload)
        self.assertEqual(game.state.players[1].spell_modifiers[0].uses_remaining, 1)
        self.assertEqual((game.state.players[1].mana, self.hero(game).health), (9, 30))
        self.assertEqual([(c.failure, c.payload_started, c.completed) for c in self.casts(game)],
            [('countered', False, True)])
        self.assertFalse(any(r.play_id == play.id for r in game.state.spell_repeats))
        self.assert_one_hand_root(game, play, source)
        self.portable(game)

    def test_real_bolt_keeps_dead_target_and_does_not_redirect_second_cast(self):
        game = self.game(hand=(ARCANE,), enemy=('CS2_179', 'CS2_182'))
        target, survivor = game.state.players[2].board
        before = game.state.entities[survivor].health
        self.play(game, ARCANE, target)
        self.assertEqual([c.target_id for c in self.casts(game)], [target, target])
        self.assertEqual(game.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual(game.state.entities[survivor].health, before)
        self.assertEqual(self.hero(game).health, 30)
        self.assertEqual([d.entity_id for d in game.state.death_history], [target])
        self.assertEqual(len(self.casts(game)), 2)
        self.portable(game)
        # Death is deferred by the double-cast root. A separate public reaction
        # puts a surviving real target out of play before the second payload.
        self.use_fixtures()
        game = self.game(hand=(ARCANE,), enemy=('CS2_182', 'fixture.target.return'))
        target, survivor = game.state.players[2].board
        self.play(game, ARCANE, target)
        self.assertEqual([c.target_id for c in self.casts(game)], [target, target])
        self.assertEqual(game.state.entities[target].zone, Zone.HAND)
        self.assertEqual(game.state.entities[survivor].health, 4)
        self.assertEqual(self.hero(game).health, 30)
        skipped = [e for e in game.events if e.kind == 'effect_skipped' and e.target_id == target]
        self.assertEqual([dict(e.data) for e in skipped],
            [{'effect': 'Damage', 'reason': 'target_not_in_play'}])
        self.assertTrue(all(c.completed and c.failure is None for c in self.casts(game)))
        self.portable(game)

    def test_source_dies_in_accepted_bolt_root_then_next_real_root_rechecks(self):
        game = self.game(hand=('CS2_024', ARCANE, ARCANE))
        carrier = self.sources(game)[0].id
        self.play(game, 'CS2_024', carrier)
        self.assertEqual(game.state.entities[carrier].health, 2)
        self.play(game, ARCANE, carrier)
        accepted = self.subject(game)
        self.assertEqual(accepted.spell_payload.casts, 2)
        self.assertEqual([c.target_id for c in self.casts(game, accepted)], [carrier, carrier])
        self.assertEqual(game.state.entities[carrier].zone, Zone.GRAVEYARD)
        self.play(game, ARCANE, self.hero(game).id)
        self.assertEqual((len(self.casts(game)), self.subject(game).spell_payload.contributors,
            self.hero(game).health), (1, (), 27))
        self.portable(game)

    def test_silence_and_copy_modes_preserve_the_real_printed_school_declaration(self):
        self.use_fixtures()
        for mode, count in (('current', 1), ('base', 2)):
            with self.subTest(mode=mode):
                game = self.game(hand=('EX1_332', 'fixture.copy.' + mode, ARCANE))
                carrier = self.sources(game)[0].id
                self.play(game, 'EX1_332', carrier)
                self.assertFalse(active_abilities(game.state.entities[carrier], 'spell_repeat'))
                self.play(game, 'fixture.copy.' + mode, carrier)
                copy_id = game.state.players[1].board[-1]
                self.assertNotEqual(carrier, copy_id)
                self.play(game, ARCANE, self.hero(game).id)
                contributors = self.subject(game).spell_payload.contributors
                self.assertEqual(self.hero(game).health, 30 - 3 * count)
                self.assertEqual(self.subject(game).spell_payload.casts, count)
                self.assertEqual([s.carrier_id for s in contributors], [copy_id] if mode == 'base' else [])
                if mode == 'base':
                    self.assertEqual(contributors[0].ability.spell_repeat, arcane_spec())
                self.portable(game)

    def test_enemy_source_and_same_physical_transfer_follow_the_new_controller(self):
        self.use_fixtures()
        game = self.game(board=(), enemy=(SOURCE,),
            hand=(ARCANE, 'fixture.take', ARCANE), enemy_hand=(ARCANE,))
        carrier = self.sources(game, 2)[0].id
        self.play(game, ARCANE, self.hero(game).id)
        self.assertEqual(self.subject(game).spell_payload.casts, 1)
        self.play(game, 'fixture.take', carrier)
        self.play(game, ARCANE, self.hero(game).id)
        self.assertEqual((self.subject(game).spell_payload.casts,
            self.subject(game).spell_payload.contributors[0].carrier_id), (2, carrier))
        game.apply(EndTurn(1))
        self.play(game, ARCANE, self.hero(game, 1).id)
        self.assertEqual((self.subject(game).spell_payload.casts,
            self.subject(game).spell_payload.contributors, self.hero(game, 1).health), (1, (), 27))
        self.portable(game)

    def test_real_source_added_or_silenced_at_commit_uses_the_late_window(self):
        self.use_fixtures()
        for operation, count in (('add', 2), ('silence', 1)):
            with self.subTest(operation=operation):
                board = ('fixture.commit.add',) if operation == 'add' else (SOURCE, 'fixture.commit.silence')
                game = self.game(hand=(ARCANE,), board=board)
                self.play(game, ARCANE, self.hero(game).id)
                play = self.subject(game)
                self.assertEqual((play.spell_payload.casts, len(self.casts(game)),
                    self.hero(game).health), (count, count, 30 - 3 * count))
                self.assertEqual(len(play.spell_payload.contributors), count - 1)
                if operation == 'add':
                    self.assertEqual(play.spell_payload.contributors[0].carrier_id, self.sources(game)[0].id)
                self.portable(game)

    def test_last_extra_wait_restores_real_source_proof_after_bounce_and_rejects_scope_rewrite(self):
        game, carrier = self.waiting_game()
        play = self.subject(game)
        self.assertEqual((play.spell_payload.casts,
            play.spell_payload.contributors[0].carrier_id), (2, carrier))
        self.assertEqual([(c.iteration, c.completed) for c in self.casts(game)], [(1, True), (2, False)])
        restored = self.portable(game)
        corrupted = copy.deepcopy(game.snapshot())
        original = corrupted['state']['play_history'][-1]
        original['spell_payload']['contributors'][0]['ability']['spell_repeat']['match'][
            'recipient_metadata']['spell_schools'] = ['fire']
        corrupted['state_hash'] = canonical_hash({k: v for k, v in corrupted.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(corrupted, self.factory())
        self.assertNotIn('digest mismatch', str(error.exception))
        choice = game.state.pending_choice
        action = SelectChoice(choice.player_id, choice.id, ('ok',))
        game.apply(action)
        restored.apply(action)
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.assertEqual(self.hero(game, 1).armor, 2)
        self.assertTrue(self.subject(game).spell_acceptance_closed)
        self.play(game, ARCANE, self.hero(game).id)
        self.assertEqual((self.subject(game).spell_payload.casts, self.hero(game).health), (1, 27))
        self.portable(game)

    def test_player_views_and_choice_commands_hide_real_source_acceptance_internals(self):
        game, _ = self.waiting_game(enemy_hand=('CS2_029',))
        owner, opponent = game.observe(1), game.observe(2)
        self.assertEqual(opponent['pending_choice'], {'player_id': 1})
        enemy = next(p for p in owner['players'] if p['id'] == 2)
        self.assertTrue(all(c['card_id'] is None for c in enemy['hand']))
        # Board aura declarations are not exposed by the current entity DTO.
        visible_source = next(c for p in owner['players'] if p['id'] == 1
            for c in p['hand'] if c['card_id'] == SOURCE)
        self.assertEqual((visible_source['attack'], visible_source['health']), (3, 5))
        forbidden = {'source_id', 'entity_id', 'carrier_id', 'attachment_id', 'abilities',
            'spell_repeat', 'spell_repeats', 'spell_submission', 'spell_payload',
            'spell_acceptance_closed', 'spell_acceptances', 'resolution_frame',
            'registry_fingerprint', 'rng_state', 'play_history', 'contributors'}

        def inspect(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for item in value.values():
                    inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)

        inspect([owner, opponent, game.player_events(1), game.player_events(2)])
        before = game.snapshot()
        visible_source['attack'] = 999
        self.assertEqual(game.snapshot(), before)
        port = game.for_player(1)
        available = port.legal_actions()
        self.assertEqual(available['version'], 'player-actions-v12')
        self.assertIsNone(available['error'])
        inspect(available)
        result = port.submit({'revision': available['revision'], 'action': available['actions'][0]})
        self.assertTrue(result['accepted'])
        inspect(result)
        self.assertEqual(self.hero(game, 1).armor, 2)
        self.portable(game)


if __name__ == '__main__':
    unittest.main()
