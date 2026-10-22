"""Real Neutral/Combo play predicates and borrowed one-use cost/random bodies."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import assemble_card_play_followups as cards
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import FETCHER, POOL_ID
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (ChoiceOption, Destroy, GainArmor, InvokeBehavior,
    RequestChoice, Silence, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass, Keyword
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_draw_armor_heal_fragments import fixture as base_fixture, META, COIN

GENERAL, PATROL = cards.SOURCES
WAR, TAELAN, CURATOR, LOOT, END, START = (
    'BE_701', 'CS3_024', 'CORE_KAR_061', 'CORE_EX1_096', 'BE_152', 'CORE_NEW1_021')
SI7 = 'CORE_EX1_134'
P = 'k422.'
N, C, NZ, SP, UNKNOWN, DUAL, MORPH_N, MORPH_C, NATURAL, KEYWORD, SD, KILL, MUTE, PRE, FAIL, WATCH = (
    P + name for name in ('neutral', 'class', 'neutral_spell', 'class_spell', 'unknown', 'dual',
        'morph_neutral', 'morph_class', 'summon', 'combo_keyword', 'spell_damage', 'kill',
        'silence', 'pre', 'fail', 'watch'))
CLASS_META = replace(META, classes=(CardClass.MAGE,))
CTX = GenerationContext('k422-reviewed-card-play-sources', 'experimental')
DECK = (COIN,) * 24
GENERAL_DRAW = AssembleRecipe(GENERAL, WAR, 'bottom').card_id
PATROL_DRAW = AssembleRecipe(PATROL, WAR, 'bottom').card_id
NEUTRAL_DAMAGE = AssembleRecipe(GENERAL, PATROL, 'bottom').card_id


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = base_fixture.__wrapped__('no_pool', role)
    r._version += '.k422.' + mode
    for cid, meta in ((N, META), (C, CLASS_META), (UNKNOWN, None),
            (DUAL, replace(META, classes=(CardClass.MAGE, CardClass.ROGUE)))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=12, metadata=meta))
    for cid, meta, destination in ((MORPH_N, META, C), (MORPH_C, CLASS_META, N)):
        r.register_behavior(cid, lambda c, destination=destination: (Transform(c.source_id, destination),))
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=12, battlecry=cid, metadata=meta))
    r.register_behavior(P + 'noop', lambda c: ())
    for cid, cost, meta in ((NZ, 0, META), (SP, 4, CLASS_META)):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=cost, on_play=P + 'noop', metadata=meta))
    r.register_behavior(NATURAL, lambda c: (Summon(c.player_id, N),))
    r.register_card(CardDefinition(NATURAL, NATURAL, CardType.SPELL, on_play=NATURAL, metadata=CLASS_META))
    r.register_card(CardDefinition(KEYWORD, KEYWORD, CardType.MINION, attack=1, health=12,
        keywords=(Keyword.COMBO,), metadata=CLASS_META))
    r.register_card(CardDefinition(SD, SD, CardType.MINION, health=12, spell_damage=9, metadata=CLASS_META))
    target = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
    for cid, body in ((KILL, lambda c: (Destroy(c.target_id, c.source_id),)),
            (MUTE, lambda c: (Silence(c.target_id),))):
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=12,
            battlecry=cid, targeting=target, metadata=CLASS_META))

    def fail(c):
        raise ResolutionError('K422 deliberate reaction transaction failure')

    def pre(c):
        if c.event.source_id is None or c.state.entities[c.event.source_id].card_id != N:
            return ()
        source = next(eid for eid in c.state.players[c.player_id].board
            if c.state.entities[eid].card_id == NEUTRAL_DAMAGE)
        return (RequestChoice(c.player_id, (
            ChoiceOption('change', 'Transform accepted source', (Transform(source, C),)),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1),
                InvokeBehavior(FAIL, c.source_id, c.player_id)))), c.source_id),)

    r.register_behavior(FAIL, fail)
    r.register_behavior(PRE, pre)
    r.register_card(CardDefinition(PRE, PRE, CardType.MINION, health=20, metadata=CLASS_META,
        triggers=(TriggerSpec('card_played', PRE),)))
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=CLASS_META,
        triggers=(TriggerSpec('damage_dealt', FAIL),)))
    if mode.endswith('_pool'):
        primary = GENERAL if mode == 'general_pool' else PATROL
        r.register_pool(PoolDefinition(POOL_ID, 'k422-real-primary-two-higher-cost-donors',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in (primary, WAR, TAELAN)), complete=True))
    r.validate()
    return r


class AssembleCardPlayFollowupTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), mode='normal', hero='HERO_03'):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, deck=DECK, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=DECK,
                mana=30, max_mana=30, mana_cap=30)), seed=422, generation_context=CTX), fixture(mode))

    def play(self, game, cid, target=None):
        player = game.state.active_player
        source = next(eid for eid in game.state.players[player].hand if game.state.entities[eid].card_id == cid)
        game.apply(PlayCard(player, source, target))
        return source

    def pick(self, game, option):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def price(self, game, cid=SP, player=1):
        state = game.state
        entity = next(state.entities[eid] for eid in state.players[player].hand if state.entities[eid].card_id == cid)
        return quote_unselected_cost(state, game.registry, entity).amount

    def hits(self, game, source):
        return [event for event in game.events if event.kind == 'damage_dealt' and event.source_id == source]

    def portable(self, game, mode='normal'):
        reader = fixture(mode, 'reader')
        self.assertIsNot(reader, game.registry)
        saved = json.loads(json.dumps(game.snapshot()))
        restored = Game.from_snapshot(saved, reader)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(game), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(game.for_player(player).observe()) + json.dumps(game.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'condition_id', 'original_behavior_id', 'played_face'):
                self.assertNotIn('"' + key + '"', public)
        return restored

    def test_a_complete_sources_four_faces_original_callbacks_and_two_exact_bridges(self):
        data = cards.load_batch()
        registry = fixture()
        rows = {row['record']['id']: row for row in data['existing_dependencies']}
        self.assertEqual(tuple(rows), cards.SOURCES)
        self.assertEqual(len(data['official_observations']), 4)
        for obs in data['official_observations']:
            self.assertEqual(sha(obs['response_file']), obs['response_sha256'])
            check_face(rows[obs['card_id']]['record'], obs['face'], obs['locale'])
        for cid, row in rows.items():
            original = registry.card(cid)
            self.assertEqual(canonical_digest(asdict(original)), row['definition_sha256'])
            template = registry.assemble_templates[cid]
            bridge = registry.assemble_reaction_sources[cid]
            self.assertEqual(original.triggers[0].behavior_id, bridge.original_behavior_id)
            self.assertEqual((template.prefix.timing, template.prefix.condition_id),
                (bridge.event, bridge.condition_id))
            self.assertEqual(bridge.event, 'card_played')
            self.assertEqual(template.suffix.allowed_timings,
                ('battlecry', 'deathrattle', 'end_turn', 'start_turn', 'card_played'))
            assembled = registry.card(AssembleRecipe(cid, cid, 'bottom').card_id)
            for field in ('cost', 'attack', 'health', 'metadata'):
                self.assertEqual(getattr(original, field), getattr(assembled, field))
            self.assertIsNone(assembled.battlecry)
            self.assertEqual(len(assembled.triggers), 1)

    def test_b_general_self_neutral_minion_and_zero_cost_neutral_spell_keep_one_use_consumption(self):
        for cid in (GENERAL, AssembleRecipe(GENERAL, GENERAL, 'bottom').card_id):
            with self.subTest(cid=cid):
                game = self.game((cid, N, NZ, SP))
                source = self.play(game, cid)
                self.assertEqual(self.price(game), 3)
                self.play(game, N)
                self.assertEqual(self.price(game), 2)
                old = {m.id for m in game.state.players[1].cost_modifiers}
                self.play(game, NZ)
                self.assertEqual(self.price(game), 3)
                modifiers = game.state.players[1].cost_modifiers
                self.assertEqual(len(modifiers), 1)
                self.assertNotIn(modifiers[0].id, old)
                self.assertEqual((modifiers[0].source_id, modifiers[0].uses_remaining,
                    modifiers[0].expires_turn), (source, 1, game.state.turn))
                mana = game.state.players[1].mana
                self.play(game, SP)
                self.assertEqual(game.state.players[1].mana, mana-3)
                self.assertFalse(game.state.players[1].cost_modifiers)

    def test_c_neutral_predicate_keeps_original_played_face_and_unknown_own_classes_fail_atomically(self):
        cid = AssembleRecipe(GENERAL, GENERAL, 'bottom').card_id
        game = self.game((MORPH_N, MORPH_C, DUAL, UNKNOWN, SP), (cid,))
        changed = self.play(game, MORPH_N)
        self.assertEqual(game.state.entities[changed].card_id, C)
        self.assertEqual(self.price(game), 3)
        changed = self.play(game, MORPH_C)
        self.assertEqual(game.state.entities[changed].card_id, N)
        self.play(game, DUAL)
        self.assertEqual(self.price(game), 3)
        saved = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'known original printed classes'):
            self.play(game, UNKNOWN)
        self.assertEqual(game.snapshot(), saved)

    def test_d_original_and_self_patrol_count_first_combo_declaration_keyword_and_activated_damage(self):
        for cid in (PATROL, AssembleRecipe(PATROL, PATROL, 'bottom').card_id):
            with self.subTest(cid=cid):
                game = self.game((SI7,), (cid,))
                source = game.state.players[1].board[0]
                self.play(game, SI7)
                self.assertEqual(game.state.play_history[-1].prior_turn_plays, 0)
                self.assertEqual([e.amount for e in self.hits(game, source)], [3])
                self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 27)
        cid = AssembleRecipe(PATROL, PATROL, 'bottom').card_id
        game = self.game((KEYWORD,), (cid,))
        self.play(game, KEYWORD)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 27)
        game = self.game((NZ, SI7), (cid,))
        self.play(game, NZ)
        hero = game.state.players[2].hero_id
        self.play(game, SI7, hero)
        self.assertEqual(game.state.entities[hero].health, 24)
        self.assertEqual(game.state.play_history[-1].prior_turn_plays, 1)

    def test_e_borrowed_prefixes_draw_without_old_discount_or_damage_and_ignore_opponents_and_summons(self):
        game = self.game((GENERAL_DRAW, C, NATURAL, N), enemy_hand=(N,))
        self.play(game, GENERAL_DRAW)
        self.assertEqual(len(game.state.draw_history), 1)
        self.play(game, C); self.play(game, NATURAL)
        self.assertEqual(len(game.state.draw_history), 1)
        self.play(game, N)
        self.assertEqual(len(game.state.draw_history), 2)
        self.assertFalse(game.state.players[1].cost_modifiers)
        game.apply(EndTurn(1)); self.play(game, N)
        self.assertEqual(len([r for r in game.state.draw_history if r.player_id == 1]), 2)
        game = self.game((SI7, NZ), (PATROL_DRAW,), enemy_hand=(SI7,))
        self.play(game, SI7)
        self.assertEqual(len(game.state.draw_history), 1)
        self.assertFalse(self.hits(game, game.state.players[1].board[0]))
        self.play(game, NZ)
        self.assertEqual(len(game.state.draw_history), 1)
        game.apply(EndTurn(1)); self.play(game, SI7)
        self.assertEqual(len([r for r in game.state.draw_history if r.player_id == 1]), 1)

    def test_f_independent_bodies_work_at_battlecry_natural_death_owner_end_and_owner_start(self):
        for donor in cards.SOURCES:
            for timing, prefix in (('battlecry', CURATOR), ('deathrattle', LOOT),
                    ('end_turn', END), ('start_turn', START)):
                with self.subTest(donor=donor, timing=timing):
                    cid = AssembleRecipe(prefix, donor, 'bottom').card_id
                    game = self.game((cid, KILL, SP))
                    source = self.play(game, cid)
                    if timing == 'deathrattle':
                        self.play(game, KILL, source)
                    elif timing == 'end_turn':
                        game.apply(EndTurn(1))
                    elif timing == 'start_turn':
                        game.apply(EndTurn(1)); game.apply(EndTurn(2))
                    if donor == GENERAL:
                        added = [e for e in game.events if e.kind == 'cost_modifier_added' and e.source_id == source]
                        self.assertEqual(len(added), 1)
                        self.assertEqual(self.price(game), 4 if timing == 'end_turn' else 3)
                    else:
                        self.assertEqual([e.amount for e in self.hits(game, source)], [3])
                    if timing == 'deathrattle':
                        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)

    def test_g_installed_spell_program_survives_source_silence_or_death_then_expires_at_actual_turn(self):
        cid = AssembleRecipe(CURATOR, GENERAL, 'bottom').card_id
        for removal in (MUTE, KILL):
            with self.subTest(removal=removal):
                game = self.game((cid, removal, SP))
                source = self.play(game, cid)
                self.play(game, removal, source)
                self.assertEqual(self.price(game), 3)
                self.assertEqual(game.state.players[1].cost_modifiers[0].source_id, source)
                game.apply(EndTurn(1))
                self.assertEqual(self.price(game), 4)
                self.assertFalse(game.state.players[1].cost_modifiers)

    def test_h_random_body_uses_enemy_characters_not_spell_power_and_failure_rolls_back_payment_and_rng(self):
        cid = AssembleRecipe(CURATOR, PATROL, 'bottom').card_id
        game = self.game((cid,), (SD,), (N, C))
        enemies = (*game.state.players[2].board, game.state.players[2].hero_id)
        before = sum(game.state.entities[eid].health for eid in enemies)
        rng = game.snapshot()['rng_state']
        source = self.play(game, cid)
        self.assertEqual(before-sum(game.state.entities[eid].health for eid in enemies), 3)
        self.assertNotEqual(game.snapshot()['rng_state'], rng)
        hits = self.hits(game, source)
        self.assertEqual(len(hits), 1)
        self.assertIn(hits[0].target_id, enemies)
        self.assertEqual(dict(hits[0].data)['damage_kind'], 'minion_ability')
        game = self.game((cid,), (WATCH, SD), (N, C))
        saved = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K422 deliberate'):
            self.play(game, cid)
        self.assertEqual(game.snapshot(), saved)

    def test_i_both_native_assemble_entries_use_real_cost_and_class_domains_then_execute_new_guards(self):
        for primary, entry, mode, hero, assembled in (
                (GENERAL, MISMATCH, 'general_pool', 'HERO_09', GENERAL_DRAW),
                (PATROL, FETCHER, 'combo_pool', 'HERO_03', PATROL_DRAW)):
            with self.subTest(primary=primary):
                game = self.game((entry, SI7), mode=mode, hero=hero)
                self.play(game, entry)
                choice = game.state.pending_choice
                self.assertIsNotNone(choice)
                chosen = next(option for option in choice.options if option.card_id == assembled)
                self.pick(game, chosen.id)
                mana = game.state.players[1].mana
                self.play(game, assembled)
                self.assertEqual(game.state.players[1].mana, mana-game.registry.card(primary).cost)
                self.assertEqual(len(game.state.draw_history), int(primary == GENERAL))
                game.apply(EndTurn(1)); game.apply(EndTurn(2))
                self.play(game, SI7)
                self.assertEqual(game.state.play_history[-1].prior_turn_plays, 0)
                self.assertEqual(len([r for r in game.state.draw_history if r.player_id == 1]), 2)
                self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 30)

    def test_j_captured_neutral_reaction_survives_wait_transform_and_independent_resume_replay(self):
        game = self.game((N,), (PRE, NEUTRAL_DAMAGE), (C,))
        source = game.state.players[1].board[1]
        self.play(game, N)
        self.assertIsNotNone(game.state.pending_choice)
        self.assertFalse(self.hits(game, source))
        saved = game.snapshot()
        reader = self.portable(game)
        with self.assertRaisesRegex(ResolutionError, 'K422 deliberate'):
            self.pick(game, 'bad')
        self.assertEqual(game.snapshot(), saved)
        self.pick(game, 'change'); self.pick(reader, 'change')
        self.assertEqual(game.snapshot(), reader.snapshot())
        self.assertEqual(game.state.entities[source].card_id, C)
        self.assertEqual([e.amount for e in self.hits(game, source)], [3])
        self.portable(game)

    def test_k_both_guards_require_exact_completed_original_physical_play_and_native_event(self):
        for primary in cards.SOURCES:
            with self.subTest(primary=primary):
                cid = AssembleRecipe(primary, WAR, 'bottom').card_id
                game = self.game((C,), (cid,))
                source = game.state.players[1].board[0]
                self.play(game, C)
                event = next(e for e in game.events if e.kind == 'card_played')
                condition = game.registry.trigger_condition(game.registry.assemble_templates[primary].prefix.condition_id)
                context = RuleContext(game.state, source, 1, event=event)
                self.assertFalse(condition(context))
                with self.assertRaisesRegex(ResolutionError, 'actual completed event'):
                    condition(replace(context, event=None))
                with self.assertRaisesRegex(ResolutionError, 'completed physical play'):
                    condition(replace(context, event=replace(event, source_id=source)))
                state = game.state
                state.play_history[-1] = replace(state.play_history[-1], completed=False, paid_hand_close=None)
                with self.assertRaisesRegex(ResolutionError, 'completed physical play'):
                    condition(replace(context, state=state))

    def test_l_complete_source_pin_drift_or_corrupt_batch_reject_before_installing_any_new_fragment(self):
        with patch.object(cards, 'register_assemble_card_play_followups', lambda r: None):
            registry = build_registry()
        for cid in cards.SOURCES:
            original = registry._cards[cid]
            registry._cards[cid] = replace(original, health=original.health+1)
            before = registry.fingerprint()
            with self.assertRaisesRegex(TargetValidationError, 'complete original source'):
                cards.register_assemble_card_play_followups(registry)
            self.assertEqual(registry.fingerprint(), before)
            self.assertFalse(any(key in registry.assemble_templates for key in cards.SOURCES))
            registry._cards[cid] = original
        with patch.object(cards, 'BATCH_HASH', '0'*64):
            with self.assertRaisesRegex(TargetValidationError, 'complete reviewed original sources'):
                cards.load_batch()
