"""Cross-class Herald entries, persistent class selection and unbound policy."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
                           Game, GenerationContext, Herald, IllegalAction,
                           PlayCard, PlayerSetup, Registry, ResolutionError, Scenario,
                           SelectChoice, SnapshotError, herald_count)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Destroy, DestroyBatch,
    GainArmor, ReplaceHero, RequestChoice, Summon, Transform)
from hs_sim.engine.herald import HERALD_CLASSES, request_from_context, soldier_card
from hs_sim.engine.player_api import PlayerPort
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.runtime import RuntimeMode
from hs_sim.engine.serialization import canonical_hash


def changing_source(context):
    request = request_from_context(context)
    return (RequestChoice(context.player_id, (ChoiceOption('continue', 'Continue',
        (Transform(context.source_id, 'fixture-plain'),)),), context.source_id), request)


def make_registry():
    registry = build_registry()
    for cls in HERALD_CLASSES:
        registry.register_card(CardDefinition(
            'fixture-hero-' + cls.value, cls.value, CardType.HERO, health=30,
            metadata=CardMetadata(False, (cls,), None)))
    registry.register_card(CardDefinition('fixture-plain', 'Plain', CardType.MINION,
                                         attack=1, health=3))
    scripts = (
        ('generic', lambda c: (Herald(c.player_id, c.source_id),), CardClass.NEUTRAL),
        ('warrior', lambda c: (Herald(c.player_id, c.source_id),), CardClass.WARRIOR),
        ('shaman', lambda c: (Herald(c.player_id, c.source_id),), CardClass.SHAMAN),
        ('no-effect-rest', lambda c: (Herald(c.player_id, c.source_id), GainArmor(1, 2)), CardClass.NEUTRAL),
        ('mage-form', lambda c: (ReplaceHero(1, 'HERO_08'),), CardClass.NEUTRAL),
        ('warrior-form', lambda c: (ReplaceHero(1, 'HERO_01'),), CardClass.NEUTRAL),
        ('opponent-mage', lambda c: (ReplaceHero(2, 'HERO_08'),), CardClass.NEUTRAL),
        ('bad', lambda c: (Herald(1, c.source_id), Summon(1, 'missing')), CardClass.WARRIOR),
        ('kill', lambda c: (Destroy(c.target_id),), CardClass.NEUTRAL),
        ('sweep', lambda c: (DestroyBatch(tuple(i for p in c.state.players.values()
            for i in p.board)),), CardClass.NEUTRAL),
        ('steal', lambda c: (ChangeControl(c.target_id, 2),), CardClass.NEUTRAL),
    )
    for name, callback, cls in scripts:
        registry.register_behavior('fixture.' + name, callback)
        registry.register_card(CardDefinition('fixture-' + name, name, CardType.SPELL,
            on_play='fixture.' + name, requires_target=name in ('kill', 'steal'),
            metadata=CardMetadata(False, (cls,), None)))
    registry.register_behavior('fixture.changing', changing_source)
    registry.register_card(CardDefinition('fixture-changing', 'Changing source',
        CardType.MINION, attack=1, health=3, battlecry='fixture.changing',
        metadata=CardMetadata(False, (CardClass.SHAMAN,), None)))
    return registry


class CrossClassHeraldTests(unittest.TestCase):
    def setUp(self):
        self.registry = make_registry()

    def game(self, hand, hero='HERO_09', enemy='HERO_08', board=(), mode=RuntimeMode.DEBUG):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, mana=10, max_mana=10),
            PlayerSetup(enemy, mana=10, max_mana=10),
        ), seed=43, generation_context=GenerationContext(
            'local-2026-09-23', 'experimental')), self.registry, mode=mode)

    def play(self, game, card_id, target=None):
        entity_id = next(i for i in game.state.players[1].hand
                         if game.state.entities[i].card_id == card_id)
        game.apply(PlayCard(1, entity_id, target))
        return entity_id

    def test_real_generic_envoy_uses_warrior_opponent(self):
        game = self.game(('CATA_722',), enemy='HERO_01')
        self.play(game, 'CATA_722')
        self.assertEqual(game.state.herald_history[-1].soldier_card_id, 'CATA_580t')

    def test_real_single_class_weapon_precedes_shaman_opponent(self):
        game = self.game(('CATA_580',), enemy='fixture-hero-shaman')
        self.play(game, 'CATA_580')
        self.assertEqual(game.state.herald_history[-1].soldier_card_id, 'CATA_580t')

    def test_real_generic_envoy_is_noop_when_both_players_are_unbound(self):
        game = self.game(('CATA_722',))
        source = self.play(game, 'CATA_722')
        self.assertEqual(game.state.players[1].board, [source])
        self.assertEqual(herald_count(game.state, 1), 0)

    def portable(self, game):
        snapshot = json.loads(json.dumps(game.snapshot()))
        independent = make_registry()
        self.assertEqual(Game.from_snapshot(snapshot, independent).snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), independent).snapshot(), snapshot)

    def test_generic_source_resolves_every_implemented_opponent_class(self):
        for cls in sorted(HERALD_CLASSES):
            with self.subTest(cls=cls):
                game = self.game(('CATA_722',), enemy='fixture-hero-' + cls.value)
                self.play(game, 'CATA_722')
                record = game.state.herald_history[-1]
                self.assertEqual(record.herald_class, cls)
                self.assertEqual(record.hero_class, CardClass.PRIEST)
                self.assertEqual(record.soldier_card_id, soldier_card(self.registry, cls))

    def test_own_starting_binding_precedes_source_and_opponent(self):
        game = self.game(('CATA_530',), hero='HERO_01', enemy='fixture-hero-shaman')
        self.play(game, 'CATA_530')
        self.assertEqual(game.state.herald_history[-1].herald_class, CardClass.WARRIOR)

    def test_real_single_class_fel_spell_uses_its_class_with_nonherald_opponent(self):
        game = self.game(('CATA_530',))
        self.play(game, 'CATA_530')
        self.assertEqual(game.state.herald_history[-1].herald_class, CardClass.DEMON_HUNTER)
        self.assertEqual(game.state.herald_history[-1].soldier_card_id, 'CATA_525t')

    def test_starting_binding_survives_hero_replacement_before_first_herald(self):
        game = self.game(('fixture-mage-form', 'fixture-shaman'), hero='HERO_01')
        self.play(game, 'fixture-mage-form')
        self.play(game, 'fixture-shaman')
        self.assertEqual(game.state.herald_history[-1].herald_class, CardClass.WARRIOR)
        self.portable(game)

    def test_first_source_binding_is_retained_for_later_different_sources(self):
        game = self.game(('fixture-warrior', 'fixture-shaman', 'fixture-generic'))
        for card in ('fixture-warrior', 'fixture-shaman', 'fixture-generic'):
            self.play(game, card)
        self.assertEqual([r.herald_class for r in game.state.herald_history],
                         [CardClass.WARRIOR] * 3)
        self.assertEqual([r.rank for r in game.state.herald_history], [0, 0, 1])
        self.portable(game)

    def test_new_own_herald_class_can_bind_if_no_prior_binding_exists(self):
        game = self.game(('fixture-warrior-form', 'fixture-shaman'))
        self.play(game, 'fixture-warrior-form')
        self.play(game, 'fixture-shaman')
        self.assertEqual(game.state.herald_history[-1].herald_class, CardClass.WARRIOR)

    def test_opponent_existing_binding_survives_their_current_nonherald_class(self):
        game = self.game(('fixture-opponent-mage', 'fixture-generic'), enemy='HERO_01')
        self.play(game, 'fixture-opponent-mage')
        self.play(game, 'fixture-generic')
        self.assertEqual(game.state.herald_history[-1].herald_class, CardClass.WARRIOR)

    def test_unbound_noop_keeps_rng_ids_counter_and_executes_remaining_body(self):
        for mode in (RuntimeMode.DEBUG, RuntimeMode.RELEASE):
            with self.subTest(mode=mode):
                game = self.game(('fixture-no-effect-rest',), mode=mode)
                rng = game._rng.getstate()
                next_id = game.state.next_entity_id
                self.play(game, 'fixture-no-effect-rest')
                self.assertEqual(game.state.herald_history, [])
                self.assertEqual(game._rng.getstate(), rng)
                self.assertEqual(game.state.next_entity_id, next_id)
                self.assertIsNone(game.state.players[1].herald_class)
                hero = game.state.entities[game.state.players[1].hero_id]
                self.assertEqual(hero.armor, 2)
                self.portable(game)

    def test_noop_does_not_advance_the_first_later_resolvable_herald(self):
        game = self.game(('fixture-generic', 'fixture-warrior'))
        self.play(game, 'fixture-generic')
        self.play(game, 'fixture-warrior')
        record = game.state.herald_history[-1]
        self.assertEqual((record.count_before, record.rank), (0, 0))
        self.assertEqual(herald_count(game.state, 1), 1)

    def test_full_board_still_binds_and_counts_without_a_soldier(self):
        game = self.game(('fixture-generic',), enemy='HERO_01',
                         board=('fixture-plain',) * 7)
        self.play(game, 'fixture-generic')
        record = game.state.herald_history[-1]
        self.assertIsNone(record.soldier_id)
        self.assertEqual(game.state.players[1].herald_class, CardClass.WARRIOR)
        self.assertEqual(herald_count(game.state, 1), 1)
        self.portable(game)

    def test_missing_selected_soldier_adapter_still_raises_and_rolls_back(self):
        self.registry = Registry('missing-herald-soldier')
        for cid, cls in (('HERO_09', CardClass.PRIEST), ('HERO_01', CardClass.WARRIOR)):
            self.registry.register_card(CardDefinition(cid, cid, CardType.HERO,
                health=30, metadata=CardMetadata(False, (cls,), None)))
        self.registry.register_behavior('missing-soldier',
            lambda c: (Herald(c.player_id, c.source_id),))
        self.registry.register_card(CardDefinition('fixture-generic', 'Herald',
            CardType.SPELL, on_play='missing-soldier'))
        game = self.game(('fixture-generic',), enemy='HERO_01')
        before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Herald Soldier'):
            self.play(game, 'fixture-generic')
        self.assertEqual(game.snapshot(), before)

    def test_failure_after_binding_rolls_back_class_soldier_and_counter(self):
        game = self.game(('fixture-bad',))
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, 'fixture-bad')
        self.assertEqual(game.snapshot(), before)

    def test_real_deathrattle_resolves_its_source_class_after_source_dies(self):
        game = self.game(('CATA_158', 'fixture-kill'), enemy='fixture-hero-shaman')
        source = self.play(game, 'CATA_158')
        self.play(game, 'fixture-kill', source)
        self.assertEqual(game.state.herald_history[-1].herald_class, CardClass.ROGUE)
        self.portable(game)

    def test_transferred_deathrattle_binds_actual_death_controller(self):
        game = self.game(('CATA_158', 'fixture-steal', 'fixture-sweep'))
        source = self.play(game, 'CATA_158')
        self.play(game, 'fixture-steal', source)
        self.play(game, 'fixture-sweep')
        record = game.state.herald_history[-1]
        self.assertEqual((record.player_id, record.herald_class),
                         (2, CardClass.ROGUE))
        self.assertIsNone(game.state.players[1].herald_class)

    def test_waiting_original_source_face_survives_transform_and_independent_restore(self):
        game = self.game(('fixture-changing',))
        self.play(game, 'fixture-changing')
        pending = game.snapshot()
        restored = Game.from_snapshot(pending, make_registry())
        choice = game.state.pending_choice
        with self.assertRaises(IllegalAction):
            game.apply(SelectChoice(1, choice.id, ('wrong',)))
        self.assertEqual(game.snapshot(), pending)
        action = SelectChoice(1, choice.id, ('continue',))
        game.apply(action)
        restored.apply(action)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual(game.state.herald_history[-1].herald_class, CardClass.SHAMAN)
        self.portable(game)

    def test_player_port_can_use_cross_class_herald_without_private_binding_fields(self):
        game = self.game(('CATA_722',), enemy='HERO_01', mode=RuntimeMode.RELEASE)
        port = PlayerPort(game, 1)
        view = port.legal_actions()
        action = next(a for a in view['actions'] if a['type'] == 'play_card')
        reply = port.submit({'revision': view['revision'], 'action': action})
        self.assertTrue(reply['accepted'], reply['error'])
        for viewer in (1, 2):
            public = json.dumps(game.observe(viewer))
            self.assertNotIn('"herald_class"', public)
            self.assertNotIn('"herald_history"', public)

    def test_rehashed_snapshot_rejects_invalid_missing_or_inconsistent_binding(self):
        game = self.game(('fixture-warrior',))
        self.play(game, 'fixture-warrior')
        for mode in ('invalid', 'missing', 'different', 'drop-history', 'record'):
            with self.subTest(mode=mode):
                snapshot = json.loads(json.dumps(game.snapshot()))
                player = snapshot['state']['players']['1']
                if mode == 'invalid': player['herald_class'] = 'mage'
                elif mode == 'missing': del player['herald_class']
                elif mode == 'different': player['herald_class'] = 'shaman'
                elif mode == 'drop-history': snapshot['state']['herald_history'] = []
                else: snapshot['state']['herald_history'][0]['herald_class'] = 'rogue'
                snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
                    if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
                with self.assertRaises(SnapshotError):
                    Game.from_snapshot(snapshot, self.registry)


if __name__ == '__main__':
    unittest.main()
