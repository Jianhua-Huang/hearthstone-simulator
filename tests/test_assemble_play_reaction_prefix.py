"""Real completed-play subjects, captured reactions and unchanged native bodies."""
from dataclasses import asdict, replace, FrozenInstanceError
from functools import lru_cache
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import assemble_play_reaction_prefix as cards
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import (AssemblePrefix, AssembleRecipe, AssembleSuffix,
    AssembleTemplate, compatible)
from hs_sim.engine.assemble_reactions import AssembleReactionSource, REACTION_PREFIX, reaction_behavior_id
from hs_sim.engine.effects import (ChoiceOption, Destroy, GainArmor, InvokeBehavior, RequestChoice,
    Silence, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import Event
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_draw_armor_heal_fragments import fixture as base_fixture, META, COIN, BEAST, DRAGON, UNIT, KILL, MUTE, STEAL

WYRM, WARBAND = cards.SOURCES
TAELAN, CURATOR, LOOT, END, START = cards.TAELAN, 'CORE_KAR_061', 'CORE_EX1_096', 'BE_152', 'CORE_NEW1_021'
DRAW_SOURCE = AssembleRecipe(WYRM, WARBAND, 'bottom').card_id
HP_SOURCE = AssembleRecipe(WARBAND, WYRM, 'bottom').card_id
P = 'k421.'
PRE, WATCH, FAIL, NATURAL, CALL, PLAIN = (P + key for key in ('pre', 'watch', 'fail', 'natural', 'call', 'plain'))
CONTEXT = GenerationContext('k421-reviewed-play-reaction-sources', 'experimental')
DECK = (BEAST, DRAGON) + (COIN,) * 22


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    registry = base_fixture.__wrapped__('no_pool', role)
    registry._version += '.k421.' + mode
    registry.register_card(CardDefinition(PLAIN, PLAIN, CardType.MINION, attack=1, health=10, metadata=META))
    registry.register_behavior(NATURAL, lambda c: (Summon(c.player_id, PLAIN),))
    registry.register_card(CardDefinition(NATURAL, NATURAL, CardType.SPELL, on_play=NATURAL, metadata=META))

    def fail(c):
        raise ResolutionError('K421 deliberate captured reaction failure')

    def pre(c):
        if c.event.source_id is None or c.state.entities[c.event.source_id].card_id != PLAIN:
            return ()
        candidates = [eid for eid in c.state.players[c.player_id].board if eid != c.source_id and
            (c.state.entities[eid].card_id.startswith('assemble:') or c.state.entities[eid].card_id == WARBAND)]
        if not candidates:
            return ()
        source = candidates[0]
        change = (Destroy(source, c.source_id),) if mode == 'destroy' else (Transform(source, UNIT),)
        if mode == 'wait_transform':
            return (RequestChoice(c.player_id, (ChoiceOption('change', 'Transform accepted source', change),
                ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1), InvokeBehavior(FAIL, c.source_id, c.player_id)))), c.source_id),)
        return change

    def watch(c):
        if c.event.player_id != c.player_id:
            return ()
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1), InvokeBehavior(FAIL, c.source_id, c.player_id)))), c.source_id),)

    registry.register_behavior(FAIL, fail)
    registry.register_behavior(PRE, pre)
    registry.register_behavior(WATCH, watch)
    registry.register_card(CardDefinition(PRE, PRE, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('card_played', PRE),)))
    registry.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('card_drawn', WATCH),)))
    gate = reaction_behavior_id('card_played', cards.PREFIX + 'other_minion_play', cards.PREFIX + 'draw')
    registry.register_behavior(CALL, lambda c: (InvokeBehavior(gate, c.target_id, c.player_id),))
    registry.register_card(CardDefinition(CALL, CALL, CardType.SPELL, on_play=CALL, metadata=META,
        targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    members = (WYRM, WARBAND, CURATOR if mode == 'unsupported' else TAELAN)
    registry.register_pool(PoolDefinition(POOL_ID, 'k421-real-low-primary-two-five-cost-donors',
        CONTEXT.target_id, CONTEXT.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode == 'nonbool':
        registry._trigger_conditions[cards.PREFIX + 'other_minion_play'] = lambda c: 1
    registry.validate()
    return registry


class AssemblePlayReactionPrefixTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), mode='normal', hero='HERO_08'):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, deck=DECK, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(COIN,) * 24,
                mana=30, max_mana=30, mana_cap=30)), seed=421, generation_context=CONTEXT), fixture(mode))

    def play(self, game, cid, target=None):
        player = game.state.active_player
        source = next(eid for eid in game.state.players[player].hand if game.state.entities[eid].card_id == cid)
        game.apply(PlayCard(player, source, target))
        return source

    def choose(self, game, option):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def draws(self, game, player=1):
        return [row for row in game.state.draw_history if row.player_id == player]

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
            for key in ('rng_state', 'resolution_frame', 'condition_id', 'original_behavior_id', 'assemble_reaction_sources'):
                self.assertNotIn('"' + key + '"', public)
        return restored

    def test_a_three_complete_sources_six_faces_native_bridges_and_exact_single_context_amendment(self):
        data = cards.load_batch()
        registry = build_registry()
        rows = {row['record']['id']: row for row in data['existing_dependencies']}
        self.assertEqual(tuple(rows), cards.SOURCES + (TAELAN,))
        self.assertEqual(len(data['official_observations']), 6)
        for observation in data['official_observations']:
            cid = observation['card_id']
            check_face(rows[cid]['record'], observation['face'], observation['locale'])
            path = Path(observation['response_file'])
            self.assertEqual(sha(path), observation['response_sha256'])
            response = json.loads(path.read_text(encoding='utf-8-sig'))
            self.assertEqual([face for face in response['cards'] if face['id'] == rows[cid]['record']['dbf_id']], [observation['face']])
        for cid, row in rows.items():
            self.assertEqual(canonical_digest(asdict(registry.card(cid))), row['definition_sha256'])
        for cid in cards.SOURCES:
            template = registry.assemble_templates[cid]
            profile = registry.assemble_reaction_sources[cid]
            derived = asdict(registry.card(AssembleRecipe(cid, cid, 'top').card_id))
            self.assertEqual(derived['triggers'][0]['behavior_id'], reaction_behavior_id(
                'card_played', template.prefix.condition_id, template.suffix.behavior_id))
            derived.update(id=cid, triggers=asdict(registry.card(cid))['triggers'])
            self.assertEqual(derived, asdict(registry.card(cid)))
            self.assertEqual(profile.original_behavior_id, registry.card(cid).triggers[0].behavior_id)
        amendment = data['amendments'][0]
        old = amendment['old_template']
        current = json.loads(json.dumps(asdict(registry.assemble_templates[TAELAN])))
        self.assertEqual(current['suffix']['allowed_timings'], old['suffix']['allowed_timings'] + ['card_played'])
        current['suffix']['allowed_timings'] = old['suffix']['allowed_timings']
        self.assertEqual(current, old)

    def test_b_original_and_self_recipes_exclude_self_spells_and_summons_but_accept_real_other_minions(self):
        for donor in cards.SOURCES:
            for cid in (donor, AssembleRecipe(donor, donor, 'top').card_id):
                with self.subTest(donor=donor, cid=cid):
                    game = self.game((cid, COIN, NATURAL, PLAIN))
                    source = self.play(game, cid)
                    base = game.registry.card(cid).health
                    self.assertFalse(self.draws(game))
                    self.assertEqual(game.state.entities[source].health, base)
                    self.play(game, COIN); self.play(game, NATURAL)
                    self.assertFalse(self.draws(game))
                    self.assertEqual(game.state.entities[source].health, base)
                    self.play(game, PLAIN)
                    self.assertEqual(len(self.draws(game)), int(donor == WARBAND))
                    self.assertEqual(game.state.entities[source].health, base + int(donor == WYRM))
                    self.assertFalse(game.state.battlecry_history)

    def test_c_borrowed_prefix_draws_without_old_self_health_and_each_physical_receiver_keeps_its_owner(self):
        game = self.game((PLAIN,), (DRAW_SOURCE, DRAW_SOURCE), enemy=(DRAW_SOURCE,), enemy_hand=(PLAIN,))
        ids = tuple(game.state.players[1].board)
        before_hp = [game.state.entities[eid].health for eid in ids]
        self.play(game, PLAIN)
        self.assertEqual(len(self.draws(game)), 2)
        self.assertEqual([game.state.entities[eid].health for eid in ids], before_hp)
        game.apply(EndTurn(1))
        before1, before2 = len(self.draws(game)), len(self.draws(game, 2))
        self.play(game, PLAIN)
        self.assertEqual(len(self.draws(game)), before1)
        self.assertEqual(len(self.draws(game, 2)), before2 + 1)

    def test_d_borrowed_unconditional_bodies_keep_battlecry_death_end_and_owner_start_without_play_guard(self):
        for donor in cards.SOURCES:
            for timing, prefix in (('battlecry', CURATOR), ('deathrattle', LOOT), ('end_turn', END), ('start_turn', START)):
                with self.subTest(donor=donor, timing=timing):
                    cid = AssembleRecipe(prefix, donor, 'bottom').card_id
                    game = self.game((cid, KILL))
                    source = self.play(game, cid)
                    initial_max = game.registry.card(prefix).health
                    if timing == 'deathrattle':
                        self.play(game, KILL, source)
                    elif timing == 'end_turn':
                        game.apply(EndTurn(1))
                    elif timing == 'start_turn':
                        game.apply(EndTurn(1)); game.apply(EndTurn(2))
                    automatic = int(timing == 'start_turn')
                    self.assertEqual(len(self.draws(game)), automatic + int(donor == WARBAND))
                    if donor == WYRM:
                        self.assertEqual(game.state.entities[source].max_health,
                            initial_max + int(timing != 'deathrattle'))
                    if timing == 'deathrattle':
                        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)

    def test_e_captured_reaction_keeps_original_native_view_after_earlier_transform_or_death(self):
        for mode in ('transform', 'destroy'):
            for cid in (WARBAND, DRAW_SOURCE):
                with self.subTest(mode=mode, cid=cid):
                    game = self.game((PLAIN,), (PRE, cid), mode=mode)
                    source = game.state.players[1].board[1]
                    self.play(game, PLAIN)
                    self.assertEqual(len(self.draws(game)), 1)
                    if mode == 'transform':
                        self.assertEqual(game.state.entities[source].card_id, UNIT)
                    else:
                        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)

    def test_f_captured_source_wait_failure_transform_independent_restore_clone_replay_and_visibility(self):
        game = self.game((PLAIN,), (PRE, DRAW_SOURCE), mode='wait_transform')
        source = game.state.players[1].board[1]
        self.play(game, PLAIN)
        self.assertIsNotNone(game.state.pending_choice)
        self.assertFalse(self.draws(game))
        reader = self.portable(game, 'wait_transform')
        saved = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate captured reaction failure'):
            self.choose(game, 'bad')
        self.assertEqual(game.snapshot(), saved)
        for running in (game, reader):
            self.choose(running, 'change')
            self.assertEqual(running.state.entities[source].card_id, UNIT)
            self.assertEqual(len(self.draws(running)), 1)
            self.assertIsNone(running.state.pending_choice)
        self.assertEqual(game.snapshot(), reader.snapshot())
        self.portable(game, 'wait_transform')

    def test_g_silence_and_control_changes_affect_later_acceptance_without_rewriting_existing_draws(self):
        game = self.game((PLAIN, MUTE, PLAIN), (DRAW_SOURCE,))
        source = game.state.players[1].board[0]
        self.play(game, PLAIN); self.assertEqual(len(self.draws(game)), 1)
        self.play(game, MUTE, source); self.play(game, PLAIN)
        self.assertEqual(len(self.draws(game)), 1)
        game = self.game((STEAL, PLAIN), enemy=(DRAW_SOURCE,))
        source = game.state.players[2].board[0]
        self.play(game, STEAL, source); self.play(game, PLAIN)
        self.assertEqual(len(self.draws(game)), 1)
        self.assertEqual(game.state.entities[source].controller, 1)

    def test_h_actual_mismatch_entry_keeps_two_real_five_cost_donors_and_reactive_draw(self):
        game = self.game((MISMATCH, PLAIN), hero='HERO_09')
        self.play(game, MISMATCH)
        choice = game.state.pending_choice
        self.choose(game, next(option.id for option in choice.options if option.card_id == DRAW_SOURCE))
        before = game.state.players[1].mana
        source = self.play(game, DRAW_SOURCE)
        self.assertEqual(game.state.players[1].mana, before-1)
        self.assertFalse(self.draws(game))
        self.play(game, PLAIN)
        self.assertEqual(len(self.draws(game)), 1)
        self.assertEqual(game.state.entities[source].health, 1)

    def test_i_unreviewed_reaction_context_is_explicit_error_and_does_not_trim_actual_offer(self):
        registry = build_registry()
        with self.assertRaisesRegex(ValueError, 'explicitly unimplemented'):
            registry.card(AssembleRecipe(WYRM, CURATOR, 'bottom').card_id)
        game = self.game((MISMATCH,), mode='unsupported', hero='HERO_09')
        saved = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'explicitly unimplemented'):
            self.play(game, MISMATCH)
        self.assertEqual(game.snapshot(), saved)

    def test_j_profile_guard_cannot_be_called_without_real_event_or_with_another_source_or_play(self):
        game = self.game((PLAIN, CALL), (DRAW_SOURCE,))
        source = game.state.players[1].board[0]
        self.play(game, PLAIN)
        saved = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'original captured event'):
            self.play(game, CALL, source)
        self.assertEqual(game.snapshot(), saved)
        event = next(event for event in game.events if event.kind == 'card_played' and event.source_id != source)
        gate = game.registry.card(DRAW_SOURCE).triggers[0].behavior_id
        context = RuleContext(game.state, source, 1, event=replace(event, source_id=source))
        with self.assertRaisesRegex(ResolutionError, 'completed physical play'):
            game.registry.behavior(gate)(context)
        plain = next(eid for eid in game.state.players[1].board if game.state.entities[eid].card_id == PLAIN)
        with self.assertRaisesRegex(ResolutionError, 'immutable assembled source'):
            game.registry.behavior(gate)(replace(context, source_id=plain, event=event))

    def test_k_reaction_declarations_are_fingerprinted_immutable_and_canonical_not_recursive(self):
        registry = build_registry()
        profile = registry.assemble_reaction_sources[WYRM]
        with self.assertRaises(TypeError):
            registry.assemble_reaction_sources[WYRM] = profile
        with self.assertRaises(FrozenInstanceError):
            profile.event = 'turn_ended'
        with self.assertRaises(ValueError):
            registry.register_assemble_reaction_source(profile)
        missing = build_registry(); missing._assemble_reaction_sources.pop(WYRM)
        with self.assertRaises(ValueError):
            missing.validate()
        with self.assertRaises(ValueError):
            AssemblePrefix('card_played')
        gate = reaction_behavior_id('card_played', cards.PREFIX+'other_minion_play', cards.PREFIX+'draw')
        with self.assertRaises(ValueError):
            reaction_behavior_id('card_played', cards.PREFIX+'other_minion_play', gate)
        with self.assertRaises(ValueError):
            AssembleSuffix(gate, ('card_played',))
        with self.assertRaises(ValueError):
            registry.behavior(REACTION_PREFIX + 'bad')
        game = self.game()
        with self.assertRaises(ValueError):
            game.registry.register_assemble_reaction_source(profile)

    def test_l_wrong_native_bridge_or_non_boolean_predicate_rejects_without_a_partial_success(self):
        # The later attack adapter amends this predecessor's exact draw template.
        # Omit that dependent installer only while testing predecessor failure.
        with patch.object(cards, 'register_assemble_play_reaction_prefix', lambda r: None), patch(
                'hs_sim.cards.assemble_attack_finished_followups.register_assemble_attack_finished_followups', lambda r: None), patch(
                'hs_sim.cards.assemble_attack_declared_followups.register_assemble_attack_declared_followups', lambda r: None):
            registry = build_registry()
        registry.register_trigger_condition(P+'test_cond', lambda c: True)
        before = registry.fingerprint()
        with self.assertRaises(ValueError):
            registry.register_assemble_reaction_source(AssembleReactionSource(WYRM, 'card_played',
                registry.card(WARBAND).triggers[0].behavior_id, P+'test_cond'))
        self.assertEqual(registry.fingerprint(), before)
        game = self.game((PLAIN,), (DRAW_SOURCE,), mode='nonbool')
        saved = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'explicit boolean'):
            self.play(game, PLAIN)
        self.assertEqual(game.snapshot(), saved)

    def test_m_previous_exact_core_stamp_is_rejected_without_defaulting_new_reaction_rules(self):
        game = self.game((PLAIN,), (DRAW_SOURCE,))
        saved = json.loads(json.dumps(game.snapshot()))
        saved['mechanics_version']['version'] = 'core-effects-v664'
        saved['state_hash'] = canonical_hash({key:value for key,value in saved.items()
            if key not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(ValueError):
            Game.from_snapshot(saved, fixture('normal', 'reader'))


if __name__ == '__main__':
    unittest.main()
