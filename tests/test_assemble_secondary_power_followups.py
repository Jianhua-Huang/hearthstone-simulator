"""Native first extra power through real Assemble offers; unresolved slots fail."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import assemble_secondary_power_followups as cards
from hs_sim.cards.constructed import build_registry
from hs_sim.cards.native_assemble_entry_cards import FETCHER, POOL_ID
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.effects import ChoiceOption, Damage, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.model import Resource
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha

SOURCE = cards.SOURCE
KISS, RUST, DRAKE, _, _, CAIRNE, CLEANER = cards.DEPENDENCIES
P = 'k450.'
N, KILL, WATCH, FAIL = (P + name for name in ('minion', 'kill', 'watch', 'fail'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
CTX = GenerationContext('k450-complete-experimental-original-power-domain', 'experimental')


def recipe(primary=SOURCE, secondary=None, half='bottom'):
    return AssembleRecipe(primary, secondary or primary, half).card_id


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    registry = build_registry()
    registry._version += '.k450.' + mode
    registry.register_card(CardDefinition(N, N, CardType.MINION, attack=1, health=20, metadata=META))
    registry.register_behavior(KILL, lambda c: (Damage(c.target_id, 99, c.source_id),))
    registry.register_card(CardDefinition(KILL, KILL, CardType.SPELL, on_play=KILL,
        targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)), metadata=META))

    def fail(context):
        raise ResolutionError('K450 deliberate failure after native power installation')

    registry.register_behavior(FAIL, fail)
    if mode in ('wait', 'fail'):
        registry.register_behavior(WATCH, lambda c: (RequestChoice(c.player_id,
            (ChoiceOption('go', 'Continue', ()),), c.source_id),))
        registry.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20,
            triggers=(TriggerSpec('hero_power_added', FAIL if mode == 'fail' else WATCH),), metadata=META))
    if mode == 'offer':
        registry.register_pool(PoolDefinition(POOL_ID, 'k450-three-complete-original-fragments',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in (SOURCE, CAIRNE, CLEANER)), complete=True))
    registry.validate()
    return registry


class AssembleSecondaryPowerTests(unittest.TestCase):
    def game(self, hand=(), board=(), *, enemy=(), corpses=9, mana=30,
             mode='normal', additional=(), enemy_weapon=False):
        if mode in ('wait', 'fail'):
            board += (WATCH,)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_11', hand=hand, board=board,
            deck=('GAME_005',) * 8, mana=mana, max_mana=mana, mana_cap=40, corpses=corpses,
            hero_power_card_id='HERO_11bp',
            additional_hero_power_card_ids=additional), PlayerSetup('HERO_08', board=enemy,
            deck=('GAME_005',) * 8, weapon_card_id='CS2_091' if enemy_weapon else None)),
            seed=6, generation_context=CTX), fixture(mode))

    def ids(self, game, cid, player=1, zone='board'):
        return [i for i in getattr(game.state.players[player], zone) if game.state.entities[i].card_id == cid]

    def play(self, game, cid, target=None):
        entity_id = self.ids(game, cid, zone='hand')[0]
        game.apply(PlayCard(1, entity_id, target))
        return entity_id

    def power(self, game):
        return next(game.state.entities[i] for i in game.state.players[1].additional_hero_power_ids
            if game.state.entities[i].card_id == KISS)

    def choose(self, game, option='go'):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def portable(self, game, mode='normal'):
        snapshot = json.loads(json.dumps(game.snapshot()))
        registry = fixture(mode, 'reader')
        self.assertIsNot(registry, game.registry)
        restored = Game.from_snapshot(snapshot, registry)
        self.assertEqual(restored.snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), snapshot)
        for player in (1, 2):
            visible = json.dumps(game.for_player(player).observe()) + json.dumps(game.player_events(player))
            for key in ('resolution_frame', 'rng_state', 'assemble_offer'):
                self.assertNotIn('"' + key + '"', visible)
        return restored

    def test_a_full_eight_original_rows_fourteen_faces_and_self_definition(self):
        data = cards.load_batch()
        registry = fixture()
        rows = {row['record']['id']: row for row in data['existing_dependencies']}
        self.assertEqual((len(rows), len(data['official_observations'])), (8, 14))
        for observation in data['official_observations']:
            self.assertEqual(sha(observation['response_file']), observation['response_sha256'])
            check_face(rows[observation['card_id']]['record'], observation['face'], observation['locale'])
        for cid, row in rows.items():
            self.assertEqual(canonical_digest(asdict(registry.card(cid))), row['definition_sha256'])
        generated = asdict(registry.card(recipe()))
        generated['id'] = SOURCE
        self.assertEqual(generated, asdict(registry.card(SOURCE)))
        self.assertEqual(recipe_options(registry, SOURCE, SOURCE), ())
        self.assertNotIn(KISS, {row['card_id'] for row in data['official_observations']})

    def test_b_native_and_self_recipe_keep_primary_and_install_one_identical_extra(self):
        for cid in (SOURCE, recipe()):
            game = self.game((cid,))
            primary = game.state.players[1].hero_power_id
            source = self.play(game, cid)
            player = game.state.players[1]
            self.assertEqual(player.hero_power_id, primary)
            self.assertEqual(len(player.hero_power_ids), 2)
            self.assertEqual(self.power(game).card_id, KISS)
            self.assertEqual(self.power(game).owner, 1)
            self.assertEqual(len(game.state.battlecry_history), 1)
            self.assertEqual(game.state.entities[source].attack, game.registry.card(SOURCE).attack)
        self.portable(game)

    def test_c_replacing_suffix_removes_entire_power_installation(self):
        cid = recipe(SOURCE, RUST)
        game = self.game((cid,), enemy_weapon=True)
        self.play(game, cid)
        self.assertEqual(len(game.state.players[1].hero_power_ids), 1)
        self.assertIsNone(game.state.players[2].weapon_id)
        self.assertFalse(any(event.kind == 'hero_power_added' for event in game.events))

    def test_d_borrowing_suffix_preserves_primary_stats_and_cost(self):
        cid = recipe(RUST, SOURCE)
        game = self.game((cid,), enemy_weapon=True)
        before = game.state.players[1].mana
        source = self.play(game, cid)
        entity = game.state.entities[source]
        original = game.registry.card(RUST)
        self.assertEqual((entity.attack, entity.max_health), (original.attack, original.health))
        self.assertEqual(before - game.state.players[1].mana, original.cost)
        self.assertIsNotNone(game.state.players[2].weapon_id)
        self.assertEqual(self.power(game).card_id, KISS)
        self.portable(game)

    def test_e_natural_death_prefix_grants_power_after_source_left_without_baine(self):
        cid = recipe(SOURCE, CAIRNE, 'top')
        game = self.game((cid, KILL))
        source = self.play(game, cid)
        self.assertEqual(len(game.state.players[1].hero_power_ids), 1)
        self.play(game, KILL, source)
        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(game.state.players[1].board, [])
        self.assertEqual(self.power(game).card_id, KISS)
        self.assertEqual(len(game.state.deathrattle_history), 1)
        self.portable(game)

    def test_f_original_corpse_payment_at_zero_mana_uses_physical_power_and_target(self):
        cid = recipe(RUST, SOURCE)
        game = self.game((cid,), enemy=(N,), corpses=3, mana=3)
        self.play(game, cid)
        target = self.ids(game, N, 2)[0]
        game.apply(UseHeroPower(1, self.power(game).id, target))
        self.assertEqual((game.state.players[1].mana, game.state.players[1].resources[Resource.CORPSES]), (0, 0))
        self.assertEqual(game.state.entities[target].attack, 4)
        self.assertEqual(game.state.hero_power_history[-1].source_id, self.power(game).id)
        self.portable(game)

    def test_g_insufficient_corpses_and_hero_target_preserve_state(self):
        for corpses, hero_target in ((2, False), (9, True)):
            game = self.game((recipe(),), board=(N,), corpses=corpses)
            self.play(game, recipe())
            target = game.state.players[2].hero_id if hero_target else self.ids(game, N)[0]
            before = game.snapshot()
            with self.assertRaises(IllegalAction):
                game.apply(UseHeroPower(1, self.power(game).id, target))
            self.assertEqual(game.snapshot(), before)

    def test_h_powers_retain_independent_native_use_counters(self):
        game = self.game((recipe(),), board=(N,))
        self.play(game, recipe())
        primary = game.state.players[1].hero_power_id
        extra = self.power(game).id
        game.apply(UseHeroPower(1, primary))
        game.apply(UseHeroPower(1, extra, self.ids(game, N)[0]))
        for power in (primary, extra):
            before = game.snapshot()
            with self.assertRaises(IllegalAction):
                game.apply(UseHeroPower(1, power, self.ids(game, N)[0] if power == extra else None))
            self.assertEqual(game.snapshot(), before)

    def test_i_duplicate_same_power_still_fails_explicitly_and_rolls_back(self):
        game = self.game((SOURCE, recipe(RUST, SOURCE)))
        self.play(game, SOURCE)
        before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'second-slot replacement/refresh') as caught:
            self.play(game, recipe(RUST, SOURCE))
        self.assertIsInstance(caught.exception.__cause__, UnsupportedDefinitionError)
        self.assertEqual(game.snapshot(), before)

    def test_j_different_existing_extra_slot_is_not_silently_replaced_or_duplicated(self):
        game = self.game((recipe(),), additional=('HERO_08bp',))
        before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'second-slot replacement/refresh'):
            self.play(game, recipe())
        self.assertEqual(game.snapshot(), before)

    def test_k_installed_power_survives_carrier_death_and_remains_usable(self):
        game = self.game((recipe(), KILL), board=(N,))
        source = self.play(game, recipe())
        power = self.power(game).id
        self.play(game, KILL, source)
        game.apply(UseHeroPower(1, power, self.ids(game, N)[0]))
        self.assertEqual(self.power(game).id, power)
        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)
        self.portable(game)

    def test_l_wait_after_actual_installation_restores_without_reinstalling(self):
        game = self.game((recipe(RUST, SOURCE),), mode='wait')
        self.play(game, recipe(RUST, SOURCE))
        self.assertIsNotNone(game.state.pending_choice)
        power = self.power(game).id
        restored = self.portable(game, 'wait')
        self.choose(game)
        self.choose(restored)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual(self.power(game).id, power)
        self.assertEqual(len([e for e in game.events if e.kind == 'hero_power_added']), 1)
        self.portable(game, 'wait')

    def test_m_late_observer_failure_reverts_play_payment_and_new_slot(self):
        game = self.game((recipe(),), mode='fail')
        before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K450 deliberate failure'):
            self.play(game, recipe())
        self.assertEqual(game.snapshot(), before)

    def test_n_real_four_cost_entry_offers_cairne_prefix_with_full_secondaries(self):
        cid = recipe(SOURCE, CAIRNE, 'top')
        game = self.game((FETCHER, KILL), mode='offer')
        self.play(game, FETCHER)
        choice = game.state.pending_choice
        self.assertIsNotNone(choice)
        self.assertIn(cid, [option.card_id for option in choice.options])
        restored = self.portable(game, 'offer')
        option = next(option.id for option in choice.options if option.card_id == cid)
        self.choose(game, option)
        self.choose(restored, option)
        self.assertEqual(game.snapshot(), restored.snapshot())
        source = self.play(game, cid)
        self.assertEqual(len(game.state.players[1].hero_power_ids), 1)
        self.play(game, KILL, source)
        self.assertEqual(self.power(game).card_id, KISS)
        self.portable(game, 'offer')

    def test_o_original_pin_and_registration_uniqueness_are_enforced(self):
        registry = fixture.__wrapped__()
        template = registry.assemble_templates[SOURCE]
        with self.assertRaises(TypeError):
            registry.assemble_templates[SOURCE] = template
        with self.assertRaises(ValueError):
            cards.register_assemble_secondary_power_followups(registry)
        registry.freeze()
        with self.assertRaises(ValueError):
            registry.register_assemble_template(template)
        changed = fixture.__wrapped__()
        changed._cards[SOURCE] = replace(changed.card(SOURCE), cost=99)
        with self.assertRaises(TargetValidationError):
            cards.register_assemble_secondary_power_followups(changed)
