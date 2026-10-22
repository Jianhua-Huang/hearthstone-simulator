"""Ten actual native end halves keep their original effects and physical targets."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import assemble_owner_end_followups as cards
from hs_sim.cards.native_assemble_entry_cards import NURTURER, POOL_ID as ASSEMBLE_POOL
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    PlayCard, PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import AddToHand, ChoiceOption, Damage, Destroy, GainArmor, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import DamageKind
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_draw_armor_heal_fragments import (
    fixture as base_fixture, META, COIN, KILL, MUTE, BEAST, DRAGON, UNIT,
)

SENTRY, PRIESTESS, BLACKWING, DRAKE, PIXIE, GNOME, HOURGLASS, STORY, KROG, STONE = cards.SOURCES
PREFIXES = {'battlecry': 'CORE_KAR_061', 'deathrattle': 'CORE_EX1_096',
    'end_turn': 'BE_152', 'start_turn': 'CORE_NEW1_021'}
FLY, HOLY, NATURE, REAL_DRAGON = 'CORE_UNG_809', 'CORE_CFM_604', 'CORE_EX1_259', 'EDR_451'
P = 'k419.'
HURT, BONUS, WATCH, FAIL, UNKNOWN_TYPE = (P + key for key in ('hurt', 'bonus', 'watch', 'fail', 'unknown_type'))
LEAVES = (HOLY, NATURE, REAL_DRAGON)
CTX = GenerationContext('k419-ten-owner-end-native-source-fixture', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    registry = base_fixture.__wrapped__('no_pool', role)
    registry._version += '.k419.' + mode
    registry.register_card(CardDefinition(BONUS, BONUS, CardType.MINION, health=20, spell_damage=10, metadata=META))

    def hurt(c):
        return (Damage(c.state.players[c.player_id].hero_id, 4, c.source_id, DamageKind.EFFECT),
            *(Damage(eid, 1, c.source_id, DamageKind.EFFECT) for eid in c.state.players[c.player_id].board[:2]))

    def fail(c):
        raise ResolutionError('K419 deliberate accepted damage continuation failure')

    def watch(c):
        if mode == 'full':
            source = c.state.entities.get(c.event.source_id)
            return (AddToHand(c.player_id, COIN, c.source_id),) if (source is not None and
                source.card_id.startswith('assemble:') and c.event.player_id == c.player_id) else ()
        hit = c.health_result
        if hit is None or not (hit.source_card_id or '').startswith('assemble:') or hit.damage_dealt <= 0:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue'),
            ChoiceOption('depart', 'Continue after source death', (Destroy(hit.source_id, c.source_id),)),
            ChoiceOption('bad', 'Fail continuation', (GainArmor(c.player_id, 1),
                InvokeBehavior(FAIL, c.source_id, c.player_id)))), c.source_id),)

    registry.register_behavior(HURT, hurt)
    registry.register_card(CardDefinition(HURT, HURT, CardType.SPELL, on_play=HURT, metadata=META))
    registry.register_behavior(FAIL, fail)
    registry.register_behavior(WATCH, watch)
    registry.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('battlecry_started' if mode == 'full' else 'health_resolved', WATCH),)))
    registry.register_card(CardDefinition(UNKNOWN_TYPE, UNKNOWN_TYPE, CardType.MINION, health=5,
        metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=None)))
    if mode != 'no_pool':
        members = (COIN,) if mode == 'empty' else LEAVES
        if mode == 'unknown':
            unknown = []
            for cid in LEAVES:
                key = P + 'unknown.' + cid
                registry.register_pool_card(replace(registry.pool_card(cid), card_id=key))
                unknown.append(key)
            members += tuple(unknown)
        registry.register_pool(PoolDefinition('constructed.cards', 'k419-complete-explicit-three-leaf-domain',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    registry.register_pool(PoolDefinition(ASSEMBLE_POOL, 'k419-one-cost-primary-two-native-end-donors',
        CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in (FLY, PIXIE, STORY)), complete=True))
    registry.validate()
    return registry


class AssembleOwnerEndFollowupTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), mode='normal', hero='HERO_08'):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, deck=(COIN,) * 18,
                mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_08', board=enemy, deck=(COIN,) * 18,
                mana=30, max_mana=30, mana_cap=30)), seed=419, generation_context=CTX), fixture(mode))

    def entity(self, game, cid, player=1):
        return next(game.state.entities[eid] for eid in game.state.players[player].hand
            if game.state.entities[eid].card_id == cid)

    def play(self, game, cid, target=None):
        player = game.state.active_player
        source = self.entity(game, cid, player).id
        game.apply(PlayCard(player, source, target))
        return source

    def choose(self, game, key):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (key,)))

    def own_draws(self, game):
        return [row for row in game.state.draw_history if row.player_id == 1]

    def damage_rows(self, game, cid):
        return [health_result(event) for event in game.events if event.kind == 'health_resolved'
            and health_result(event).source_card_id == cid]

    def created(self, game, source):
        return [game.state.entities[event.target_id] for event in game.events
            if event.kind == 'card_created' and event.source_id == source]

    def portable(self, game, mode):
        reader = fixture(mode, 'reader')
        self.assertIsNot(reader, game.registry)
        saved = json.loads(json.dumps(game.snapshot()))
        restored = Game.from_snapshot(saved, reader)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(game), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(game.for_player(player).observe()) + json.dumps(game.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'pool_id', 'candidate_card_ids', 'behavior_id'):
                self.assertNotIn('"' + key + '"', public)
        return restored

    def exercise(self, donor, timing):
        prefix = PREFIXES[timing]
        cid = AssembleRecipe(prefix, donor, 'bottom').card_id
        game = self.game((cid, HURT, KILL, BEAST), (BEAST, DRAGON, BONUS), (UNIT, UNIT))
        friends = tuple(game.state.players[1].board[:2])
        enemy = tuple(game.state.players[2].board)
        held = self.entity(game, BEAST).id
        self.play(game, HURT)
        mana = game.state.players[1].mana
        source = self.play(game, cid)
        if timing == 'deathrattle':
            self.play(game, KILL, source)
        elif timing == 'end_turn':
            game.apply(EndTurn(1))
        elif timing == 'start_turn':
            game.apply(EndTurn(1))
            game.apply(EndTurn(2))
        self.assertIsNone(game.state.pending_choice)
        if timing in ('battlecry', 'deathrattle'):
            self.assertEqual(game.state.players[1].mana, mana - game.registry.card(prefix).cost)
        rows = self.damage_rows(game, cid)
        expected_damage = 6 if donor == PRIESTESS else 10 if donor == BLACKWING else (
            game.registry.card(prefix).attack if donor == GNOME and timing != 'deathrattle' else 0)
        self.assertEqual(sum(row.damage_dealt for row in rows), expected_damage)
        self.assertTrue(all(row.source_id == source and row.spell_bonus == 0 for row in rows))
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 26)
        born = self.created(game, source)
        expected_leaf = {SENTRY: HOLY, PIXIE: NATURE, DRAKE: REAL_DRAGON}.get(donor)
        self.assertEqual([entity.card_id for entity in born], [expected_leaf] if expected_leaf else [])
        if born:
            self.assertEqual(born[0].zone, Zone.HAND)
            self.assertEqual(quote_unselected_cost(game.state, game.registry, born[0]).amount,
                max(0, game.registry.card(expected_leaf).cost - (3 if donor == SENTRY else 0)))
        hand_card = game.state.entities[held]
        self.assertEqual((hand_card.attack, hand_card.health, hand_card.max_health),
            (2, 6, 6) if donor == HOURGLASS else (1, 5, 5))
        others = [game.state.entities[eid] for eid in friends]
        if donor == STORY:
            self.assertEqual([(e.attack, e.health, e.max_health) for e in others], [(2, 5, 6)] * 2)
        elif donor == STONE:
            self.assertEqual(sorted((e.attack, e.health, e.max_health) for e in others), [(1, 4, 5), (3, 6, 7)])
        else:
            self.assertEqual([(e.attack, e.health, e.max_health) for e in others], [(1, 4, 5)] * 2)
        if donor == KROG:
            self.assertEqual([(game.state.entities[eid].attack, game.state.entities[eid].health,
                game.state.entities[eid].max_health) for eid in enemy], [(1, 1, 1)] * 2)
        if timing == 'deathrattle':
            self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)
        return game

    def test_a_ten_whole_sources_twenty_faces_original_clocks_keywords_and_all_reconstructions(self):
        data = cards.load_batch()
        registry = build_registry()
        rows = {row['record']['id']: row for row in data['existing_dependencies']}
        self.assertEqual(tuple(rows), cards.SOURCES)
        self.assertEqual(len(data['official_observations']), 20)
        seen = set()
        for observation in data['official_observations']:
            cid = observation['card_id']
            check_face(rows[cid]['record'], observation['face'], observation['locale'],
                data['display_normalizations'].get(cid),
                numeric_normalizations=data['numeric_normalizations'].get(cid))
            path = Path(observation['response_file'])
            self.assertEqual(sha(path), observation['response_sha256'])
            response = json.loads(path.read_text(encoding='utf-8-sig'))
            self.assertEqual([face for face in response['cards'] if face['id'] == rows[cid]['record']['dbf_id']],
                [observation['face']])
            seen.add((cid, observation['locale']))
        self.assertEqual(seen, {(cid, locale) for cid in cards.SOURCES for locale in ('zh_CN', 'en_US')})
        for cid, row in rows.items():
            definition = registry.card(cid)
            self.assertEqual(canonical_digest(asdict(definition)), row['definition_sha256'])
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
            template = registry.assemble_templates[cid]
            self.assertEqual(template.suffix.behavior_id, definition.triggers[0].behavior_id)
            self.assertEqual(template.prefix.end_turn, definition.triggers[0].end_turn)
            recipe = AssembleRecipe(cid, cid, 'top').card_id
            self.assertEqual(asdict(registry.card(recipe)), asdict(definition) | {'id': recipe})
        self.assertIsNone(rows[PIXIE]['record']['attack'])
        self.assertEqual(registry.card(PIXIE).attack, 0)

    def test_b_all_ten_borrowed_battlecries_execute_current_native_bodies_and_pay_once(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                self.exercise(donor, 'battlecry')

    def test_c_all_ten_borrowed_deathrattles_keep_real_dead_source_and_living_attack_guard(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                self.exercise(donor, 'deathrattle')

    def test_d_all_ten_borrowed_owner_end_bodies_use_the_actual_controller(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                self.exercise(donor, 'end_turn')

    def test_e_all_ten_borrowed_owner_start_bodies_wait_for_the_owner_start(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                self.exercise(donor, 'start_turn')

    def test_f_all_ten_borrowed_prefixes_keep_only_owner_clock_keywords_and_new_draw_body(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                cid = AssembleRecipe(PREFIXES['deathrattle'], donor, 'top').card_id
                game = self.game((cid,), mode='no_pool')
                source = self.play(game, cid)
                self.assertFalse(game.state.battlecry_history)
                self.assertFalse(self.own_draws(game))
                self.assertEqual(game.state.entities[source].keywords, set(game.registry.card(donor).keywords))
                game.apply(EndTurn(1))
                self.assertEqual(len(self.own_draws(game)), 1)
                game.apply(EndTurn(2))
                self.assertEqual(len(self.own_draws(game)), 2)

    def test_g_three_generators_missing_domain_or_unknown_eligible_leaf_roll_back_paid_entry(self):
        for mode in ('no_pool', 'unknown'):
            for donor in (SENTRY, DRAKE, PIXIE):
                with self.subTest(mode=mode, donor=donor):
                    cid = AssembleRecipe(PREFIXES['battlecry'], donor, 'bottom').card_id
                    game = self.game((cid,), mode=mode)
                    saved = game.snapshot()
                    with self.assertRaises((ResolutionError, ValueError)):
                        self.play(game, cid)
                    self.assertEqual(game.snapshot(), saved)

    def test_h_empty_generation_enemy_or_wounded_recipient_pools_do_not_consume_rng(self):
        for donor in (SENTRY, DRAKE, PIXIE, BLACKWING, KROG, STONE):
            with self.subTest(donor=donor):
                cid = AssembleRecipe(PREFIXES['battlecry'], donor, 'bottom').card_id
                game = self.game((cid,), mode='empty')
                rng = game._rng.getstate()
                self.play(game, cid)
                self.assertEqual(game._rng.getstate(), rng)
                self.assertIsNone(game.state.pending_choice)
                self.assertFalse(self.created(game, game.state.players[1].board[0]))

    def test_i_accepted_split_wait_failure_source_death_restore_clone_replay_and_visibility(self):
        cid = AssembleRecipe(PREFIXES['battlecry'], PRIESTESS, 'bottom').card_id
        game = self.game((cid,), (WATCH, BONUS), (UNIT, UNIT), mode='wait')
        source = self.play(game, cid)
        self.assertEqual(sum(row.damage_dealt for row in self.damage_rows(game, cid)), 1)
        reader = self.portable(game, 'wait')
        saved = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate accepted damage continuation failure'):
            self.choose(game, 'bad')
        self.assertEqual(game.snapshot(), saved)
        for running in (game, reader):
            self.choose(running, 'depart')
            while running.state.pending_choice is not None:
                self.choose(running, 'ok')
            self.assertEqual(running.state.entities[source].zone, Zone.GRAVEYARD)
            self.assertEqual(sum(row.damage_dealt for row in self.damage_rows(running, cid)), 6)
            self.assertEqual(running.state.players[1].mana, 25)
            self.assertTrue(running.state.battlecry_history[0].completed)
        self.assertEqual(game.snapshot(), reader.snapshot())
        self.portable(game, 'wait')

    def test_j_actual_nurturer_offers_real_new_prefix_and_body_with_valid_cost_class_domain(self):
        for half in ('top', 'bottom'):
            with self.subTest(half=half):
                game = self.game((NURTURER,), hero='HERO_06')
                self.play(game, NURTURER)
                cid = AssembleRecipe(FLY, PIXIE, half).card_id
                choice = game.state.pending_choice
                self.choose(game, next(option.id for option in choice.options if option.card_id == cid))
                mana = game.state.players[1].mana
                source = self.play(game, cid)
                self.assertEqual(game.state.players[1].mana, mana - 1)
                self.assertEqual([e.card_id for e in self.created(game, source)], [NATURE] if half == 'bottom' else [])
                game.apply(EndTurn(1))
                self.assertEqual([e.card_id for e in self.created(game, source)],
                    [NATURE] if half == 'bottom' else ['UNG_809t1'])

    def test_k_all_three_full_hand_creations_burn_without_trimming_query_or_reversing_payment(self):
        for donor, expected in ((SENTRY, HOLY), (DRAKE, REAL_DRAGON), (PIXIE, NATURE)):
            with self.subTest(donor=donor):
                cid = AssembleRecipe(PREFIXES['battlecry'], donor, 'bottom').card_id
                game = self.game((cid,) + (COIN,) * 9, (WATCH,), mode='full')
                source = self.play(game, cid)
                self.assertEqual(len(game.state.players[1].hand), 10)
                created = self.created(game, source)
                self.assertEqual([e.card_id for e in created], [expected])
                self.assertNotEqual(created[0].zone, Zone.HAND)
                self.assertEqual(game.state.players[1].mana, 25)

    def test_l_complete_card_query_or_missing_nested_behavior_rejects_before_partial_installation(self):
        for mode in ('card', 'query', 'nested'):
            with self.subTest(mode=mode):
                with patch.object(cards, 'register_assemble_owner_end_followups', lambda r: None):
                    registry = build_registry()
                if mode == 'card':
                    registry._cards[SENTRY] = replace(registry.card(SENTRY), name=registry.card(SENTRY).name + ' changed')
                elif mode == 'nested':
                    registry._behaviors.pop('cards.six_cost_native.gnome_now')
                before = registry.fingerprint()
                queries = dict(cards.QUERIES)
                if mode == 'query':
                    queries[PIXIE] = replace(queries[PIXIE], max_cost=1)
                with patch.object(cards, 'QUERIES', queries), self.assertRaises(ValueError):
                    cards.register_assemble_owner_end_followups(registry)
                self.assertEqual(registry.fingerprint(), before)

    def test_m_unknown_current_tribe_is_explicit_failure_not_a_smaller_successful_group(self):
        cid = AssembleRecipe(PREFIXES['battlecry'], STORY, 'bottom').card_id
        game = self.game((cid,), (UNKNOWN_TYPE,))
        saved = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'recipient facts are unknown'):
            self.play(game, cid)
        self.assertEqual(game.snapshot(), saved)


if __name__ == '__main__':
    unittest.main()
