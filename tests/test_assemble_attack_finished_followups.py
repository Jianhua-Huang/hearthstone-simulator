"""Real attack subjects, original Hound continuation and independent bodies."""
from dataclasses import asdict, replace, FrozenInstanceError
from functools import lru_cache
import hashlib
import json
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import assemble_attack_finished_followups as cards
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe, AssembleSuffix
from hs_sim.engine.assemble_reactions import (AssembleReactionContinuation, LATE_REACTION_PREFIX,
    late_reaction_behavior_id, reaction_behavior_id)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, Destroy, GainArmor,
    InvokeBehavior, RequestChoice, ReturnToHand, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import ChoiceItem, ChoiceResult, Keyword, PendingChoice
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.registry import RuleContext, UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_spell_play_followups import fixture as base_fixture
from test_assemble_card_play_followups import META, N, SP, SD, KILL, MUTE, COIN, WAR, CURATOR, LOOT, END, START

SUPPLIER, FIEND, WRATH, REHGAR, HOOK, HOUND, RIDER, TUNNELER = cards.SOURCES
P = 'k424.'
DUMMY, LETHAL, PRE, WATCH, FAIL, BOOST = (P + name for name in ('dummy', 'lethal', 'pre', 'watch', 'fail', 'boost'))
AXE = 'CS2_106'
CTX = GenerationContext('k424-reviewed-attack-sources', 'experimental')
DECK = (COIN,) * 24
HOUND_DRAW = AssembleRecipe(HOUND, SUPPLIER, 'bottom').card_id


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = base_fixture.__wrapped__('normal', role)
    r._version += '.k424.' + mode
    for cid, attack in ((DUMMY, 1), (LETHAL, 20)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=attack, health=40, metadata=META))

    def fail(c):
        raise ResolutionError('K424 deliberate attack reaction failure')

    def pre(c):
        if c.event.source_id != c.state.players[1].board[1]:
            return ()
        source = c.event.source_id
        if mode == 'return':
            return (ReturnToHand(source), SummonFromZone(1, zone=Zone.HAND,
                selection='first', source_id=c.source_id, cause=SummonCause.capture(c)))
        if mode == 'destroy':
            return (Destroy(source, c.source_id),)
        if mode == 'control':
            return (ChangeControl(source, 2),)
        if mode == 'transform':
            return (Transform(source, N),)
        effects = (Buff(source, attack=2, source_id=c.source_id),)
        if mode == 'wait_buff':
            return (RequestChoice(1, (ChoiceOption('change', 'Buff accepted attacker', effects),
                ChoiceOption('bad', 'Fail', (GainArmor(1, 1), InvokeBehavior(FAIL, c.source_id, 1)))), c.source_id),)
        return effects

    def watch(c):
        if c.event.player_id != c.player_id:
            return ()
        return (RequestChoice(c.player_id, (ChoiceOption('go', 'Continue'),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1),
                InvokeBehavior(FAIL, c.source_id, c.player_id)))), c.source_id),)

    r.register_behavior(FAIL, fail)
    r.register_behavior(BOOST, lambda c: (Buff(c.target_id, attack=3, source_id=c.source_id),))
    r.register_card(CardDefinition(BOOST, BOOST, CardType.MINION, health=10, metadata=META,
        battlecry=BOOST, targeting=r.card(KILL).targeting))
    r.register_behavior(PRE, pre)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(PRE, PRE, CardType.MINION, health=40, metadata=META,
        triggers=(TriggerSpec('attack_finished', PRE),)))
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=40, metadata=META,
        triggers=(TriggerSpec('card_drawn', WATCH),)))
    if mode in ('pool', 'unsupported'):
        members = (FIEND, WRATH, WAR if mode == 'pool' else CURATOR)
        r.register_pool(PoolDefinition(POOL_ID, 'k424-real-low-primary-two-five-plus-donors',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    r.validate()
    return r


class AssembleAttackFinishedTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), mode='normal', active=1, weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_10', hand=hand, board=board, deck=DECK, weapon_card_id=weapon,
                mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=DECK, weapon_card_id=weapon,
                mana=40, max_mana=40, mana_cap=40)), active_player=active, seed=424,
                generation_context=CTX), fixture(mode))

    def eid(self, game, cid, player=1, zone='board'):
        return next(eid for eid in getattr(game.state.players[player], zone) if game.state.entities[eid].card_id == cid)

    def play(self, game, cid, target=None):
        player = game.state.active_player; source = self.eid(game, cid, player, 'hand')
        game.apply(PlayCard(player, source, target)); return source

    def attack(self, game, cid, target=None):
        player = game.state.active_player
        source = game.state.players[player].hero_id if cid == 'hero' else self.eid(game, cid, player)
        game.apply(Attack(player, source, target or game.state.players[3-player].hero_id))
        return source

    def pick(self, game, key):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (key,)))

    def draws(self, game, player=1):
        return [row for row in game.state.draw_history if row.player_id == player]

    def hits(self, game, source):
        return [e for e in game.events if e.kind == 'damage_dealt' and e.source_id == source
            and dict(e.data)['damage_kind'] == 'minion_ability']

    def portable(self, game, mode='normal'):
        saved = json.loads(json.dumps(game.snapshot())); reader = fixture(mode, 'reader')
        self.assertIsNot(reader, game.registry)
        restored = Game.from_snapshot(saved, reader)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(game), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(game.for_player(player).observe()) + json.dumps(game.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'condition_id', 'accepted_card_id', 'late_condition_id', 'material_sha256'):
                self.assertNotIn('"'+key+'"', public)
            self.assertNotIn(LATE_REACTION_PREFIX, public)
        return restored

    def test_a_ten_full_records_twenty_faces_eight_bridges_and_exact_draw_amendment(self):
        data = cards.load_batch()
        # Verify this stage's exact amendment before the later reviewed extension.
        with patch('hs_sim.cards.assemble_attack_declared_followups.register_assemble_attack_declared_followups', lambda r: None):
            r = build_registry()
        rows = {row['record']['id']: row for row in data['existing_dependencies']}
        self.assertEqual(tuple(rows), cards.SOURCES+(cards.BOLT, WAR))
        self.assertEqual(len(data['official_observations']), 20)
        for obs in data['official_observations']:
            self.assertEqual(sha(obs['response_file']), obs['response_sha256'])
            check_face(rows[obs['card_id']]['record'], obs['face'], obs['locale'])
        for cid, row in rows.items():
            self.assertEqual(canonical_digest(asdict(r.card(cid))), row['definition_sha256'])
        for cid in cards.SOURCES:
            original = r.card(cid); template = r.assemble_templates[cid]
            self.assertEqual(r.assemble_reaction_sources[cid].original_behavior_id, original.triggers[0].behavior_id)
            self.assertEqual(template.prefix.timing, 'attack_finished')
            derived = r.card(AssembleRecipe(cid, cid, 'bottom').card_id)
            self.assertEqual((derived.cost, derived.attack, derived.health, derived.keywords, derived.metadata),
                (original.cost, original.attack, original.health, original.keywords, original.metadata))
        amendment = data['amendments'][0]
        current = json.loads(json.dumps(asdict(r.assemble_templates[WAR])))
        old = amendment['old_template']
        self.assertEqual(current['suffix']['allowed_timings'], old['suffix']['allowed_timings']+['attack_finished'])
        current['suffix']['allowed_timings'] = old['suffix']['allowed_timings']
        self.assertEqual(current, old)

    def test_b_original_and_self_hero_attack_sources_keep_attack_buff_armor_and_draw(self):
        for original in (FIEND, HOOK, RIDER):
            for cid in (original, AssembleRecipe(original, original, 'bottom').card_id):
                with self.subTest(original=original, cid=cid):
                    game = self.game(board=(cid,), weapon=AXE)
                    source = self.eid(game, cid); self.attack(game, 'hero')
                    self.assertEqual(len(self.draws(game)), int(original != FIEND))
                    self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 4 if original == HOOK else 0)
                    self.assertEqual(game.state.entities[source].attack,
                        game.registry.card(original).attack+int(original == FIEND))

    def test_c_original_and_self_attacking_sources_keep_stealth_draw_bolt_and_hero_damage(self):
        for original in (SUPPLIER, REHGAR, TUNNELER):
            for cid in (original, AssembleRecipe(original, original, 'bottom').card_id):
                with self.subTest(original=original, cid=cid):
                    game = self.game(board=(cid,)); source = self.attack(game, cid)
                    self.assertEqual(len(self.draws(game)), int(original == SUPPLIER))
                    bolts = [e for e in game.state.players[1].hand if game.state.entities[e].card_id == cards.BOLT]
                    self.assertEqual(len(bolts), int(original == REHGAR))
                    self.assertEqual([e.amount for e in self.hits(game, source)], [2] if original == TUNNELER else [])
                    self.assertNotIn(Keyword.STEALTH, game.state.entities[source].keywords)

    def test_d_wrathspike_defending_surviving_or_lethal_keeps_native_all_enemy_ping(self):
        for cid in (WRATH, AssembleRecipe(WRATH, WRATH, 'bottom').card_id):
            for attacker in (DUMMY, LETHAL):
                with self.subTest(cid=cid, attacker=attacker):
                    game = self.game(board=(cid,), enemy=(attacker,), active=2)
                    source = self.eid(game, cid)
                    self.attack(game, attacker, source)
                    self.assertEqual([e.amount for e in self.hits(game, source)], [1, 1])
                    self.assertEqual(game.state.entities[source].zone,
                        Zone.GRAVEYARD if attacker == LETHAL else Zone.BOARD)

    def test_e_rehgar_uses_captured_actual_adjacent_receiver_not_any_friendly_attacker(self):
        cid = AssembleRecipe(REHGAR, SUPPLIER, 'bottom').card_id
        for board, attacker, expected in (((N, cid, DUMMY), N, 1),
                ((N, DUMMY, cid), N, 0), ((N, cid, DUMMY), DUMMY, 1)):
            game = self.game(board=board)
            self.attack(game, attacker)
            self.assertEqual(len(self.draws(game)), expected)
        game = self.game(board=(cid,), weapon=AXE); self.attack(game, 'hero')
        self.assertFalse(self.draws(game))

    def test_f_hero_only_prefixes_ignore_minion_and_opponent_attacks(self):
        for original in (FIEND, HOOK, RIDER):
            cid = AssembleRecipe(original, SUPPLIER, 'bottom').card_id
            game = self.game(board=(cid, N), weapon=AXE)
            self.attack(game, N); self.assertFalse(self.draws(game))
            game.apply(EndTurn(1)); self.attack(game, 'hero')
            self.assertFalse(self.draws(game))

    def test_g_original_and_self_hound_keep_real_surviving_minion_attack_budget(self):
        for cid in (HOUND, AssembleRecipe(HOUND, HOUND, 'bottom').card_id):
            game = self.game(board=(cid, SD), enemy=(DUMMY,))
            self.attack(game, cid, self.eid(game, DUMMY, 2))
            self.assertEqual(game.state.split_damage_history[-1].request.amount, 5)
            self.assertEqual(sum(e.amount for e in self.hits(game, self.eid(game, cid))), 5)
            game = self.game(board=(cid,), enemy=(LETHAL,))
            self.attack(game, cid, self.eid(game, LETHAL, 2))
            self.assertFalse(game.state.split_damage_history)
            game = self.game(board=(cid,)); self.attack(game, cid)
            self.assertFalse(game.state.split_damage_history)

    def test_h_hound_survival_prefix_applies_to_borrowed_draw_after_original_presence_returns_or_changes_owner(self):
        for mode in ('destroy', 'return', 'control'):
            with self.subTest(mode=mode):
                game = self.game(board=(PRE, HOUND_DRAW), enemy=(DUMMY,), mode=mode)
                source = self.eid(game, HOUND_DRAW)
                original = game.state.entities[source].board_presence_id
                self.attack(game, HOUND_DRAW, self.eid(game, DUMMY, 2))
                self.assertFalse(self.draws(game))
                if mode == 'return':
                    self.assertEqual(game.state.entities[source].zone, Zone.BOARD)
                    self.assertNotEqual(game.state.entities[source].board_presence_id, original)

    def test_i_original_and_self_hound_late_view_reads_new_attack_and_surviving_transformed_face(self):
        for mode, expected in (('buff', 7), ('transform', 1)):
            for cid in (HOUND, AssembleRecipe(HOUND, HOUND, 'bottom').card_id):
                with self.subTest(mode=mode, cid=cid):
                    game = self.game(board=(PRE, cid), enemy=(DUMMY,), mode=mode)
                    self.attack(game, cid, self.eid(game, DUMMY, 2))
                    self.assertEqual(game.state.split_damage_history[-1].request.amount, expected)

    def test_j_hound_early_wait_then_late_survival_independent_restore_failure_and_native_split(self):
        cid = AssembleRecipe(HOUND, HOUND, 'bottom').card_id
        game = self.game(board=(PRE, cid), enemy=(DUMMY,), mode='wait_buff')
        self.attack(game, cid, self.eid(game, DUMMY, 2))
        self.assertIsNotNone(game.state.pending_choice)
        self.assertFalse(game.state.split_damage_history)
        saved = game.snapshot(); reader = self.portable(game, 'wait_buff')
        with self.assertRaisesRegex(ResolutionError, 'K424 deliberate'):
            self.pick(game, 'bad')
        self.assertEqual(game.snapshot(), saved)
        self.pick(game, 'change'); self.pick(reader, 'change')
        self.assertEqual(game.snapshot(), reader.snapshot())
        self.assertEqual(game.state.split_damage_history[-1].request.amount, 7)
        self.portable(game, 'wait_buff')

    def test_k_already_accepted_late_draw_wait_does_not_recheck_or_duplicate_after_resume(self):
        game = self.game(board=(WATCH, HOUND_DRAW), enemy=(DUMMY,))
        self.attack(game, HOUND_DRAW, self.eid(game, DUMMY, 2))
        self.assertEqual(len(self.draws(game)), 1)
        saved = game.snapshot(); rng = saved['rng_state']; reader = self.portable(game)
        with self.assertRaisesRegex(ResolutionError, 'K424 deliberate'):
            self.pick(game, 'bad')
        self.assertEqual(game.snapshot(), saved)
        self.pick(game, 'go'); self.pick(reader, 'go')
        self.assertEqual(game.snapshot(), reader.snapshot())
        self.assertEqual(len(self.draws(game)), 1)
        self.assertEqual(game.snapshot()['rng_state'], rng)

    def test_l_seven_independent_bodies_execute_without_any_original_attack_at_battlecry(self):
        for donor in (SUPPLIER, FIEND, WRATH, REHGAR, HOOK, HOUND, TUNNELER):
            with self.subTest(donor=donor):
                cid = AssembleRecipe(CURATOR, donor, 'bottom').card_id
                game = self.game((cid,), enemy=(DUMMY,)); source = self.play(game, cid)
                self.assertFalse(game.state.character_attack_history)
                if donor in (SUPPLIER, HOOK):
                    self.assertEqual(len(self.draws(game)), 1)
                    self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 4 if donor == HOOK else 0)
                elif donor == FIEND:
                    self.assertEqual(game.state.entities[source].attack, game.registry.card(CURATOR).attack+1)
                elif donor == REHGAR:
                    self.assertEqual(len([e for e in game.state.players[1].hand if game.state.entities[e].card_id == cards.BOLT]), 1)
                elif donor == HOUND:
                    self.assertEqual(game.state.split_damage_history[-1].request.amount, game.registry.card(CURATOR).attack)
                else:
                    self.assertEqual([e.amount for e in self.hits(game, source)], [1, 1] if donor == WRATH else [2])

    def test_m_hound_death_body_uses_actual_last_known_attack_without_old_survival_guard(self):
        cid = AssembleRecipe(LOOT, HOUND, 'bottom').card_id
        game = self.game((BOOST, KILL), (cid,)); source = self.eid(game, cid)
        # The accepted before-removal death fact, not the reset graveyard face.
        self.assertEqual(game.state.entities[source].attack, game.registry.card(LOOT).attack)
        self.play(game, BOOST, source)
        accepted_attack = game.state.entities[source].attack
        self.assertEqual(accepted_attack, game.registry.card(LOOT).attack+3)
        self.play(game, KILL, source)
        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(game.state.split_damage_history[-1].request.amount, game.state.death_history[-1].attack)
        self.assertEqual(game.state.split_damage_history[-1].request.amount, accepted_attack)

    def test_n_shared_end_start_and_dead_source_armor_draw_keep_native_delivery(self):
        for prefix, timing in ((END, 'end'), (START, 'start'), (LOOT, 'death')):
            cid = AssembleRecipe(prefix, HOOK, 'bottom').card_id
            game = self.game((cid, KILL)); source = self.play(game, cid)
            if timing == 'end':
                game.apply(EndTurn(1))
            elif timing == 'start':
                game.apply(EndTurn(1)); game.apply(EndTurn(2))
            else:
                self.play(game, KILL, source)
            self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 4)
            self.assertEqual(len(self.draws(game)), 2 if timing == 'start' else 1)

    def test_o_real_mismatch_offer_uses_low_primary_five_cost_donors_and_hero_attack_draw(self):
        cid = AssembleRecipe(FIEND, WAR, 'bottom').card_id
        game = self.game((MISMATCH,), mode='pool', weapon=AXE)
        self.play(game, MISMATCH)
        choice = game.state.pending_choice
        self.pick(game, next(o.id for o in choice.options if o.card_id == cid))
        mana = game.state.players[1].mana; source = self.play(game, cid)
        self.assertEqual(game.state.players[1].mana, mana-1)
        self.attack(game, 'hero')
        self.assertEqual(len(self.draws(game)), 1)
        self.assertEqual(game.state.entities[source].attack, 1)

    def test_p_unreviewed_eligible_attack_suffix_refuses_whole_offer_and_rolls_back_payment_rng(self):
        game = self.game((MISMATCH,), mode='unsupported'); saved = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'explicitly unimplemented'):
            self.play(game, MISMATCH)
        self.assertEqual(game.snapshot(), saved)

    def test_q_late_profiles_are_immutable_bound_fingerprinted_unique_and_not_recursive_bodies(self):
        r = build_registry(); spec = r.assemble_reaction_continuations[cards.PREFIX+'self_attacks_minion']
        self.assertEqual(spec.card_id, HOUND)
        with self.assertRaises(FrozenInstanceError):
            spec.capture = 'other'
        with self.assertRaises(TypeError):
            r.assemble_reaction_continuations[spec.condition_id] = spec
        with self.assertRaises(ValueError):
            r.register_assemble_reaction_continuation(spec)
        before = r.fingerprint(); r._assemble_reaction_continuations.clear()
        self.assertNotEqual(r.fingerprint(), before)
        with self.assertRaises(ValueError):
            r.register_assemble_reaction_continuation(replace(spec, card_id=FIEND))
        r.register_assemble_reaction_continuation(spec)
        late = late_reaction_behavior_id('attack_finished', spec.condition_id, cards.PREFIX+'draw', '0'*64)
        with self.assertRaises(ValueError):
            AssembleSuffix(late, ('attack_finished',))
        for bad in (late+'=', LATE_REACTION_PREFIX+'!', late.replace('reaction_late:', 'reaction_late:x')):
            with self.assertRaises(ValueError):
                r.behavior(bad)
        r.freeze()
        with self.assertRaisesRegex(ValueError, 'registry is frozen'):
            r.register_assemble_reaction_continuation(spec)

    def test_r_late_gate_refuses_missing_choice_forged_attacker_or_other_accepted_body(self):
        game = self.game(board=(HOUND_DRAW,), enemy=(DUMMY,))
        source = self.eid(game, HOUND_DRAW); self.attack(game, HOUND_DRAW, self.eid(game, DUMMY, 2))
        row = game.state.character_attack_history[-1]
        condition = cards.PREFIX+'self_attacks_minion'
        material = dict(kind='assemble.attack-source.v1', source_id=source, player_id=1,
            accepted_card_id=HOUND_DRAW, attack_window_id=row.declaration.id,
            event_sequence=row.terminal.event_cursor+1, reference=asdict(row.declaration.attack_source_presence))
        digest = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        late = late_reaction_behavior_id('attack_finished', condition, cards.PREFIX+'draw', digest)
        material['gate_id'] = late
        def context(value):
            option = ChoiceItem(json.dumps(value, sort_keys=True, separators=(',', ':')), 'Original attack')
            choice = PendingChoice(500, 1, source, 'Original attack', (option,), 0, 0)
            return RuleContext(game.state, source, 1, choice=ChoiceResult(choice, ()))
        call = game.registry.behavior(late)
        self.assertTrue(call(context(material)))
        with self.assertRaises(ResolutionError):
            call(RuleContext(game.state, source, 1))
        for key, value in (('source_id', source+1), ('attack_window_id', 999), ('player_id', True),
                ('event_sequence', material['event_sequence']+1), ('gate_id', late+'x'),
                ('accepted_card_id', AssembleRecipe(FIEND, SUPPLIER, 'bottom').card_id)):
            with self.subTest(key=key):
                with self.assertRaises(ResolutionError):
                    call(context(dict(material, **{key:value})))

    def test_s_guard_requires_actual_completed_attack_and_prior_core665_is_rejected(self):
        cid = AssembleRecipe(FIEND, SUPPLIER, 'bottom').card_id
        game = self.game(board=(cid,), weapon=AXE); source = self.eid(game, cid)
        condition = game.registry.trigger_condition(cards.PREFIX+'own_hero_attack')
        with self.assertRaisesRegex(ResolutionError, 'actual completed attack event'):
            condition(RuleContext(game.state, source, 1))
        self.attack(game, 'hero')
        event = next(e for e in game.events if e.kind == 'attack_finished')
        with self.assertRaises(ResolutionError):
            condition(RuleContext(game.state, source, 1, event=replace(event, target_id=source)))
        saved = json.loads(json.dumps(game.snapshot()));saved['mechanics_version']['version'] = 'core-effects-v665'
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(ValueError):
            Game.from_snapshot(saved, fixture('normal', 'reader'))

    def test_t_complete_source_or_reviewed_draw_pin_drift_fails_before_partial_registration(self):
        with patch.object(cards, 'register_assemble_attack_finished_followups', lambda r: None), patch(
                'hs_sim.cards.assemble_attack_declared_followups.register_assemble_attack_declared_followups', lambda r: None):
            r = build_registry()
        original_fingerprint = r.fingerprint()
        def registrations():
            return {name:dict(getattr(r, name)) for name in ('_cards', '_pool_cards', '_assemble_templates',
                '_assemble_reaction_sources', '_assemble_reaction_continuations', '_trigger_conditions', '_behaviors')}
        for cid in cards.SOURCES+(cards.BOLT,):
            old = r._cards[cid]; pool = r._pool_cards[cid]
            r._cards[cid] = replace(old, cost=old.cost+1)
            r._pool_cards[cid] = replace(pool, cost=pool.cost+1)
            before = registrations()
            with self.assertRaisesRegex(TargetValidationError, 'complete original source'):
                cards.register_assemble_attack_finished_followups(r)
            self.assertEqual(registrations(), before);r._cards[cid] = old;r._pool_cards[cid] = pool
        template = r._assemble_templates[WAR]
        r._assemble_templates[WAR] = replace(template, suffix=replace(template.suffix,
            allowed_timings=template.suffix.allowed_timings+('attack_finished',)))
        before = registrations()
        with self.assertRaisesRegex(TargetValidationError, 'exact reviewed original draw template'):
            cards.register_assemble_attack_finished_followups(r)
        self.assertEqual(registrations(), before)
        r._assemble_templates[WAR] = template
        self.assertEqual(r.fingerprint(), original_fingerprint)

    def test_u_another_valid_attack_by_same_carrier_cannot_replace_the_accepted_continuation_material(self):
        game = self.game(board=(HOUND_DRAW,), enemy=(DUMMY,))
        source = self.eid(game, HOUND_DRAW)
        self.attack(game, HOUND_DRAW, self.eid(game, DUMMY, 2))
        first = game.state.character_attack_history[-1]
        game.apply(EndTurn(1));game.apply(EndTurn(2))
        self.attack(game, HOUND_DRAW, self.eid(game, DUMMY, 2))
        second = game.state.character_attack_history[-1]
        self.assertNotEqual(first.declaration.id, second.declaration.id)
        self.assertEqual(first.declaration.attack_source_presence, second.declaration.attack_source_presence)
        def material(row):
            return dict(kind='assemble.attack-source.v1', source_id=source, player_id=1,
                accepted_card_id=HOUND_DRAW, attack_window_id=row.declaration.id,
                event_sequence=row.terminal.event_cursor+1, reference=asdict(row.declaration.attack_source_presence))
        one, two = material(first), material(second)
        def identity(value):
            digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            return late_reaction_behavior_id('attack_finished', cards.PREFIX+'self_attacks_minion', cards.PREFIX+'draw', digest)
        first_id, second_id = identity(one), identity(two)
        self.assertNotEqual(first_id, second_id)
        def context(value, gate):
            encoded = json.dumps(dict(value, gate_id=gate), sort_keys=True, separators=(',', ':'))
            choice = PendingChoice(501, 1, source, 'Original attack', (ChoiceItem(encoded, 'Original attack'),), 0, 0)
            return RuleContext(game.state, source, 1, choice=ChoiceResult(choice, ()))
        first_body = game.registry.behavior(first_id)
        self.assertTrue(first_body(context(one, first_id)))
        with self.assertRaisesRegex(ResolutionError, 'exact original attack material'):
            first_body(context(two, first_id))
        with self.assertRaises(ResolutionError):
            first_body(context(two, second_id))
        self.assertTrue(game.registry.behavior(second_id)(context(two, second_id)))
