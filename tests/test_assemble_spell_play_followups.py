"""Four actual spell subjects, original late bodies and captured physical shield."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import assemble_spell_play_followups as cards
from hs_sim.cards.native_assemble_entry_cards import FETCHER, CARETAKER, POOL_ID
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import (ChoiceOption, Destroy, GainArmor, InvokeBehavior,
    RequestChoice, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import Keyword, SpellSchool
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_card_play_followups import (
    fixture as base_fixture, META, CLASS_META, N, C, NZ, SP, SD, KILL, COIN,
    WAR, TAELAN, CURATOR, LOOT, END, START)

VETERAN, PYRO, COLD, THRESHER = cards.SOURCES
MEDIC = cards.MEDIC
COUNTER = 'CORE_EX1_287'
P = 'k423.'
HOLY, PRE, WATCH, FAIL = (P + key for key in ('holy', 'pre', 'watch', 'fail'))
CTX = GenerationContext('k423-reviewed-completed-spell-sources', 'experimental')
DECK = (COIN,) * 24


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = base_fixture.__wrapped__('normal', role)
    r._version += '.k423.' + mode
    r.register_behavior(HOLY, lambda c: ())
    r.register_card(CardDefinition(HOLY, HOLY, CardType.SPELL, on_play=HOLY,
        spell_school=SpellSchool.HOLY, metadata=CLASS_META))

    def fail(c):
        raise ResolutionError('K423 deliberate spell reaction failure')

    def pre(c):
        if c.event.player_id != c.player_id or c.state.entities[c.event.source_id].kind != CardType.SPELL:
            return ()
        source = c.state.players[c.player_id].board[1]
        if mode == 'late_pyro':
            return (Summon(c.player_id, N),)
        if mode == 'late_cold':
            return (Summon(3-c.player_id, N),)
        if mode == 'destroy':
            return (Destroy(source, c.source_id),)
        return (Transform(source, N),)

    def watch(c):
        if mode == 'wait_summon':
            if c.state.entities[c.event.target_id].card_id != MEDIC:
                return ()
        elif c.event.source_id is None or not c.state.entities[c.event.source_id].card_id.startswith('assemble:'):
            return ()
        return (RequestChoice(c.player_id, (ChoiceOption('go', 'Continue'),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1),
                InvokeBehavior(FAIL, c.source_id, c.player_id)))), c.source_id),)

    r.register_behavior(FAIL, fail)
    r.register_behavior(PRE, pre)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(PRE, PRE, CardType.MINION, health=20, metadata=CLASS_META,
        triggers=(TriggerSpec('card_played', PRE),)))
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=CLASS_META,
        triggers=(TriggerSpec('minion_summoned' if mode == 'wait_summon' else 'damage_dealt', WATCH),)))
    if mode.endswith('_pool'):
        primary = VETERAN if mode == 'veteran_pool' else THRESHER
        r.register_pool(PoolDefinition(POOL_ID, 'k423-real-four-fee-or-beast-source-domain',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in (primary, WAR, TAELAN)), complete=True))
    r.validate()
    return r


class AssembleSpellPlayFollowupTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), mode='normal'):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_04', hand=hand, board=board, deck=DECK, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=DECK,
                mana=30, max_mana=30, mana_cap=30)), seed=423, generation_context=CTX), fixture(mode))

    def play(self, game, cid, target=None):
        player = game.state.active_player
        source = next(eid for eid in game.state.players[player].hand if game.state.entities[eid].card_id == cid)
        game.apply(PlayCard(player, source, target))
        return source

    def pick(self, game, option):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def hits(self, game, source):
        return [e for e in game.events if e.kind == 'damage_dealt' and e.source_id == source]

    def medics(self, game):
        return [game.state.entities[eid] for eid in game.state.players[1].board
            if game.state.entities[eid].card_id == MEDIC]

    def portable(self, game, mode='normal'):
        saved = json.loads(json.dumps(game.snapshot()))
        reader = fixture(mode, 'reader')
        self.assertIsNot(reader, game.registry)
        restored = Game.from_snapshot(saved, reader)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(game), reader).snapshot(), saved)
        for pid in (1, 2):
            public = json.dumps(game.for_player(pid).observe()) + json.dumps(game.player_events(pid))
            for key in ('rng_state', 'resolution_frame', 'condition_id', 'original_inner_bodies', 'played_face'):
                self.assertNotIn('"' + key + '"', public)
        return restored

    def test_a_five_full_definitions_eight_root_faces_original_inner_dependencies_and_bridges(self):
        data = cards.load_batch(); r = fixture()
        rows = {row['record']['id']: row for row in data['existing_dependencies']}
        self.assertEqual(tuple(rows), cards.SOURCES + (MEDIC,))
        self.assertEqual(len(data['official_observations']), 8)
        for obs in data['official_observations']:
            self.assertEqual(sha(obs['response_file']), obs['response_sha256'])
            check_face(rows[obs['card_id']]['record'], obs['face'], obs['locale'])
        for cid, row in rows.items():
            self.assertEqual(canonical_digest(asdict(r.card(cid))), row['definition_sha256'])
        for cid in cards.SOURCES:
            template = r.assemble_templates[cid]; profile = r.assemble_reaction_sources[cid]
            self.assertEqual((profile.event, profile.original_behavior_id),
                ('card_played', r.card(cid).triggers[0].behavior_id))
            self.assertEqual(template.prefix.condition_id, profile.condition_id)
            self.assertEqual(template.suffix.allowed_timings,
                ('battlecry', 'deathrattle', 'end_turn', 'start_turn', 'card_played'))
            d = r.card(AssembleRecipe(cid, cid, 'bottom').card_id)
            self.assertEqual((d.cost, d.attack, d.health, d.metadata),
                (r.card(cid).cost, r.card(cid).attack, r.card(cid).health, r.card(cid).metadata))
        for behavior in data['original_inner_bodies'].values():
            self.assertTrue(callable(r.behavior(behavior)))

    def test_b_original_and_self_spell_sources_keep_school_counter_and_body_qualification(self):
        for original in cards.SOURCES:
            for cid in (original, AssembleRecipe(original, original, 'bottom').card_id):
                with self.subTest(original=original, cid=cid):
                    game = self.game((SP, HOLY), (cid,))
                    source = game.state.players[1].board[0]
                    self.play(game, SP)
                    if original == VETERAN:
                        self.assertFalse(self.medics(game))
                        self.play(game, HOLY)
                        medic, = self.medics(game)
                        self.assertEqual((medic.attack, medic.health), (2, 2))
                        self.assertIn(Keyword.LIFESTEAL, medic.keywords)
                    elif original == THRESHER:
                        self.assertIn(Keyword.DIVINE_SHIELD, game.state.entities[source].keywords)
                    else:
                        self.assertEqual([e.amount for e in self.hits(game, source)], [1])

    def test_c_real_countered_spell_does_not_trigger_any_of_the_four_assembled_sources(self):
        board = tuple(AssembleRecipe(cid, cid, 'bottom').card_id for cid in cards.SOURCES)
        game = self.game((HOLY,), board, enemy_hand=(COUNTER,))
        game.apply(EndTurn(1)); self.play(game, COUNTER); game.apply(EndTurn(2))
        rng = game.snapshot()['rng_state']
        self.play(game, HOLY)
        self.assertTrue(game.state.play_history[-1].countered)
        self.assertFalse(self.medics(game))
        self.assertFalse(any(e.kind == 'damage_dealt' for e in game.events))
        source = game.state.players[1].board[-1]
        self.assertNotIn(Keyword.DIVINE_SHIELD, game.state.entities[source].keywords)
        self.assertEqual(game.snapshot()['rng_state'], rng)

    def test_d_borrowed_spell_prefixes_draw_without_native_rewards_and_ignore_minions_or_opponent_spells(self):
        for original in cards.SOURCES:
            with self.subTest(original=original):
                cid = AssembleRecipe(original, WAR, 'bottom').card_id
                game = self.game((N, SP, HOLY), (cid,), enemy_hand=(SP,))
                self.play(game, N)
                self.assertFalse(game.state.draw_history)
                self.play(game, SP)
                self.assertEqual(len(game.state.draw_history), int(original != VETERAN))
                self.play(game, HOLY)
                expected = 1 if original == VETERAN else 2
                self.assertEqual(len(game.state.draw_history), expected)
                self.assertFalse(self.medics(game))
                self.assertFalse(any(e.kind == 'damage_dealt' for e in game.events))
                self.assertNotIn(Keyword.DIVINE_SHIELD, game.state.entities[game.state.players[1].board[0]].keywords)
                game.apply(EndTurn(1)); self.play(game, SP)
                self.assertEqual(len([row for row in game.state.draw_history if row.player_id == 1]), expected)

    def test_e_pyro_and_cold_keep_the_original_extra_current_board_window(self):
        for original, mode in ((PYRO, 'late_pyro'), (COLD, 'late_cold')):
            for cid in (original, AssembleRecipe(original, original, 'bottom').card_id):
                with self.subTest(original=original, cid=cid):
                    game = self.game((SP,), (PRE, cid), mode=mode)
                    source = game.state.players[1].board[1]
                    self.play(game, SP)
                    player = 1 if original == PYRO else 2
                    added = next(game.state.entities[eid] for eid in game.state.players[player].board
                        if game.state.entities[eid].card_id == N)
                    self.assertEqual(added.health, 11)
                    self.assertIn(added.id, [e.target_id for e in self.hits(game, source)])
                    if original == COLD:
                        self.assertEqual(len(self.hits(game, source)), 2)

    def test_f_shield_uses_original_physical_presence_after_earlier_transform_or_death(self):
        for mode in ('transform', 'destroy'):
            for cid in (THRESHER, AssembleRecipe(THRESHER, THRESHER, 'bottom').card_id):
                with self.subTest(mode=mode, cid=cid):
                    game = self.game((SP,), (PRE, cid), mode=mode)
                    source = game.state.players[1].board[1]
                    self.play(game, SP)
                    current = game.state.entities[source]
                    self.assertEqual(current.zone, Zone.BOARD if mode == 'transform' else Zone.GRAVEYARD)
                    self.assertNotIn(Keyword.DIVINE_SHIELD, current.keywords)

    def test_g_four_independent_bodies_at_battlecry_death_end_start_do_not_keep_the_spell_guard(self):
        for donor in cards.SOURCES:
            for timing, prefix in (('battlecry', CURATOR), ('deathrattle', LOOT),
                    ('end_turn', END), ('start_turn', START)):
                with self.subTest(donor=donor, timing=timing):
                    cid = AssembleRecipe(prefix, donor, 'bottom').card_id
                    game = self.game((cid, KILL), enemy=(C,))
                    source = self.play(game, cid)
                    if timing == 'deathrattle':
                        self.play(game, KILL, source)
                    elif timing == 'end_turn':
                        game.apply(EndTurn(1))
                    elif timing == 'start_turn':
                        game.apply(EndTurn(1)); game.apply(EndTurn(2))
                    if donor == VETERAN:
                        self.assertEqual(len(self.medics(game)), 1)
                    elif donor == THRESHER:
                        self.assertEqual(Keyword.DIVINE_SHIELD in game.state.entities[source].keywords,
                            timing != 'deathrattle')
                    elif donor == COLD:
                        self.assertEqual([e.amount for e in self.hits(game, source)], [1, 1])
                    else:
                        self.assertTrue(self.hits(game, source))
                        self.assertTrue(all(e.amount == 1 and dict(e.data)['damage_kind'] == 'minion_ability'
                            for e in self.hits(game, source)))

    def test_h_borrowed_random_body_ignores_spell_power_and_waiting_keeps_rng_choice_and_delivery(self):
        cid = AssembleRecipe(COLD, COLD, 'bottom').card_id
        game = self.game((SP,), (WATCH, cid, SD), (N, C), mode='wait_damage')
        source = game.state.players[1].board[1]
        self.play(game, SP)
        self.assertIsNotNone(game.state.pending_choice)
        rng = game.snapshot()['rng_state']; saved = game.snapshot()
        reader = self.portable(game, 'wait_damage')
        with self.assertRaisesRegex(ResolutionError, 'K423 deliberate'):
            self.pick(game, 'bad')
        self.assertEqual(game.snapshot(), saved)
        count = 0
        while game.state.pending_choice:
            self.pick(game, 'go'); self.pick(reader, 'go'); count += 1
            self.assertEqual(game.snapshot(), reader.snapshot())
            self.assertEqual(game.snapshot()['rng_state'], rng)
        self.assertEqual(count, 2)
        hits = self.hits(game, source)
        self.assertEqual([e.amount for e in hits], [1, 1])
        self.assertEqual(len({e.target_id for e in hits}), 2)
        self.portable(game, 'wait_damage')

    def test_i_real_four_cost_and_beast_assemble_offers_pay_for_source_and_run_new_prefix_only(self):
        for primary, entry, mode, spell in ((VETERAN, FETCHER, 'veteran_pool', HOLY),
                (THRESHER, CARETAKER, 'thresher_pool', SP)):
            with self.subTest(primary=primary):
                game = self.game((entry, spell), mode=mode)
                self.play(game, entry)
                cid = AssembleRecipe(primary, WAR, 'bottom').card_id
                choice = game.state.pending_choice
                option = next(o for o in choice.options if o.card_id == cid)
                self.pick(game, option.id)
                mana = game.state.players[1].mana
                source = self.play(game, cid)
                self.assertEqual(game.state.players[1].mana, mana-game.registry.card(primary).cost)
                self.assertFalse(game.state.draw_history)
                self.play(game, spell)
                self.assertEqual(len(game.state.draw_history), 1)
                self.assertFalse(self.medics(game))
                self.assertNotIn(Keyword.DIVINE_SHIELD, game.state.entities[source].keywords)

    def test_j_native_medic_summon_wait_uses_original_cause_and_portable_completed_play(self):
        cid = AssembleRecipe(VETERAN, VETERAN, 'bottom').card_id
        game = self.game((HOLY,), (WATCH, cid), mode='wait_summon')
        self.play(game, HOLY)
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(len(self.medics(game)), 1)
        self.assertTrue(game.state.play_history[-1].completed)
        reader = self.portable(game, 'wait_summon')
        self.pick(game, 'go'); self.pick(reader, 'go')
        self.assertEqual(game.snapshot(), reader.snapshot())
        self.assertEqual(len(self.medics(game)), 1)

    def test_k_source_or_medic_drift_and_missing_original_inner_body_fail_before_installation(self):
        with patch.object(cards, 'register_assemble_spell_play_followups', lambda r: None):
            registry = build_registry()
        for cid in cards.SOURCES + (MEDIC,):
            original = registry._cards[cid]
            registry._cards[cid] = replace(original, health=original.health+1)
            before = registry.fingerprint()
            with self.assertRaisesRegex(TargetValidationError, 'complete original source or Medic'):
                cards.register_assemble_spell_play_followups(registry)
            self.assertEqual(registry.fingerprint(), before)
            registry._cards[cid] = original
        for body in cards.load_batch()['original_inner_bodies'].values():
            original = registry._behaviors.pop(body)
            before = registry.fingerprint()
            with self.assertRaises(ValueError):
                cards.register_assemble_spell_play_followups(registry)
            self.assertEqual(registry.fingerprint(), before)
            registry._behaviors[body] = original
        self.assertFalse(any(cid in registry.assemble_templates for cid in cards.SOURCES))

    def test_l_spell_conditions_require_completed_same_physical_play_and_actual_original_event(self):
        cid = AssembleRecipe(THRESHER, WAR, 'bottom').card_id
        game = self.game((N,), (cid,)); source = game.state.players[1].board[0]
        self.play(game, N)
        event = next(e for e in game.events if e.kind == 'card_played')
        for name in ('spell_play', 'holy_spell_play', 'living_spell_play'):
            condition = game.registry.trigger_condition(cards.PREFIX + name)
            context = RuleContext(game.state, source, 1, event=event)
            self.assertFalse(condition(context))
            with self.assertRaisesRegex(ResolutionError, 'actual completed event'):
                condition(replace(context, event=None))
            with self.assertRaisesRegex(ResolutionError, 'completed original physical play'):
                condition(replace(context, event=replace(event, source_id=source)))
