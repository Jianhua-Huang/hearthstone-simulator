"""Actual public actions covering own-turn history and immutable submitted faces."""
from copy import deepcopy
from dataclasses import dataclass, replace
import json
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, DeckPolicy,
    DeckSpec, EndTurn, Game, IllegalAction, Keyword, MatchSetup, OpeningHook, PlayCard,
    PlayedTypeQuery, PlayerSetup, Rarity, Registry, ResolutionError, Ruleset, Scenario,
    SelectChoice, SnapshotError, SpellSchool, UseHeroPower, query_previous_owner_turn)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChangeControl, ChoiceOption, Damage,
    Destroy, Effect, GainArmor, GainTemporaryMana, RequestChoice, ReturnToHand, Silence,
    Summon, Transform)
from hs_sim.engine.interrupts import CounterSpell, CounterMinion
from hs_sim.engine.model import CostSpec, EndTurnRequest, EndTurnSelector, EndTurnSpec, RewindSpec, TriggerSpec
from hs_sim.engine.owner_turns import query_for_definition, share_tribes
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import PlayFromHand, default_mechanics
from hs_sim.engine.serialization import canonical_hash


def metadata(tribes=(), *, card_class=CardClass.NEUTRAL, collectible=True):
    return CardMetadata(collectible, (card_class,), Rarity.COMMON, tribes=tribes)


def registry():
    r = Registry('h1-isolated-synthetic-fixtures-v1')
    r.register_behavior('power', lambda c: [GainArmor(c.player_id, 1)])
    for pid, cls in ((1, CardClass.MAGE), (2, CardClass.WARRIOR)):
        r.register_card(CardDefinition(f'power{pid}', f'power{pid}', CardType.HERO_POWER,
            on_use='power', metadata=metadata(card_class=cls, collectible=False)))
        r.register_card(CardDefinition(f'hero{pid}', f'hero{pid}', CardType.HERO, health=30,
            initial_hero_power=f'power{pid}', metadata=metadata(card_class=cls, collectible=False)))
    for name, tribes in (('dragon', ('dragon',)), ('beast', ('beast',)), ('all', ('all',)),
                         ('empty', ()), ('unknown', None)):
        r.register_card(CardDefinition(name, name, CardType.MINION, attack=1, health=5,
            metadata=metadata(tribes)))
    r.register_card(CardDefinition('missing-meta', 'missing-meta', CardType.MINION, health=5))
    r.register_card(CardDefinition('retainer', 'retainer', CardType.MINION, health=5,
        metadata=metadata(), retain_rewind_outcomes=True))
    r.register_behavior('nothing', lambda c: [])
    for name, school in (('arcane', SpellSchool.ARCANE), ('frost', SpellSchool.FROST), ('unschooled', None)):
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play='nothing',
            spell_school=school, metadata=metadata()))
    r.register_behavior('coin', lambda c: [GainTemporaryMana(c.player_id, 1)])
    r.register_card(CardDefinition('coin', 'coin', CardType.SPELL, on_play='coin',
        metadata=metadata(collectible=False)))
    r.register_behavior('choice', lambda c: [RequestChoice(c.player_id,
        (ChoiceOption('ok', 'ok', (GainArmor(c.player_id, 1),)),), source_id=c.source_id)])
    r.register_card(CardDefinition('choice', 'choice', CardType.SPELL, on_play='choice',
        spell_school=SpellSchool.ARCANE, metadata=metadata()))
    r.register_behavior('failure', lambda c: (_ for _ in ()).throw(ValueError('intentional H1 rollback')))
    r.register_card(CardDefinition('failure', 'failure', CardType.SPELL, on_play='failure', metadata=metadata()))
    r.register_behavior('terminal', lambda c: [Damage(c.state.players[3-c.player_id].hero_id, 50)])
    r.register_card(CardDefinition('terminal', 'terminal', CardType.SPELL, on_play='terminal',
        spell_school=SpellSchool.ARCANE, metadata=metadata()))
    r.register_behavior('rewind', lambda c: [GainArmor(c.player_id, c.rewind_attempt+1)])
    r.register_card(CardDefinition('rewind', 'rewind', CardType.SPELL, cost=2, on_play='rewind',
        spell_school=SpellSchool.ARCANE, metadata=metadata(), rewind=RewindSpec(1), keywords=(Keyword.REWIND,)))
    r.register_behavior('end-choice', lambda c: [RequestChoice(c.player_id,
        (ChoiceOption('ok', 'ok', (GainArmor(c.player_id, 1),)),), source_id=c.source_id)])
    r.register_card(CardDefinition('end-watcher', 'end-watcher', CardType.MINION, health=8,
        metadata=metadata(), triggers=(TriggerSpec('turn_ended', 'end-choice', EndTurnSpec()),)))
    r.register_behavior('counter-spell', lambda c: [CounterSpell(dict(c.event.data)['window_id'])]
        if c.play is not None and c.play.kind == CardType.SPELL else [])
    r.register_behavior('counter-minion', lambda c: [CounterMinion(dict(c.event.data)['window_id'])]
        if c.play is not None and c.play.kind == CardType.MINION else [])
    for name in ('counter-spell', 'counter-minion'):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=8, metadata=metadata(),
            triggers=(TriggerSpec('card_committed', name),)))
    return r


@dataclass(frozen=True)
class FakeTurnStarted(Effect):
    pass


class OwnerTurnActionTests(unittest.TestCase):
    def setUp(self):
        self.r = registry()

    def game(self, hand=(), enemy_hand=(), board=(), enemy_board=(), *, active=1, rules=None, mechanics=None, power=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero1', hand=hand, board=board, deck=('empty',)*12, max_mana=10, mana=10, hero_power_card_id=power),
            PlayerSetup('hero2', hand=enemy_hand, board=enemy_board, deck=('empty',)*12, max_mana=10, mana=10)),
            active_player=active, seed=4104), self.r, ruleset=rules, mechanics=mechanics)

    def play(self, game, card, player=None, *, target=None):
        player = game.state.active_player if player is None else player
        source = next(i for i in game.state.players[player].hand if game.state.entities[i].card_id == card)
        kind = self.r.card(card).kind
        game.apply(PlayCard(player, source, target, len(game.state.players[player].board)
                           if kind in (CardType.MINION, CardType.LOCATION) else None))
        return source

    def end(self, game):
        game.apply(EndTurn(game.state.active_player))

    def choose(self, game, option='ok'):
        pending = game.state.pending_choice
        game.apply(SelectChoice(pending.player_id, pending.id, (option,)))

    def query(self, game, player=1, tribe='dragon'):
        return query_previous_owner_turn(game.state, player, PlayedTypeQuery(CardType.MINION, (tribe,)))

    def school(self, game, school=SpellSchool.ARCANE, player=1):
        return query_previous_owner_turn(game.state, player, PlayedTypeQuery(CardType.SPELL, spell_school=school))

    def fresh_registry(self):
        r = registry()
        for name, behavior in self.r._behaviors.items():
            if name not in r._behaviors:
                r.register_behavior(name, behavior)
        for name, definition in self.r.cards.items():
            if name not in r.cards:
                r.register_card(definition)
        self.assertIsNot(r, self.r)
        return r

    def portable(self, game):
        snapshot = json.loads(json.dumps(game.snapshot(), ensure_ascii=False))
        self.assertEqual(Game.from_snapshot(snapshot, self.fresh_registry(), mechanics=game.mechanics).snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), self.fresh_registry(), mechanics=game.mechanics).snapshot(), snapshot)
        return snapshot

    def reject_rehashed(self, snapshot):
        snapshot['state_hash'] = canonical_hash({k:v for k,v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as raised:
            Game.from_snapshot(snapshot, self.fresh_registry())
        self.assertNotIn('digest mismatch', str(raised.exception))

    def script(self, name, behavior, **kwargs):
        self.r.register_behavior(name, behavior)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name,
            metadata=metadata(), **kwargs))

    def test_scenario_is_conceptual_first_interval_for_either_owner(self):
        for active in (1, 2):
            with self.subTest(active=active):
                g = self.game(active=active)
                row, = g.state.owner_turn_history
                self.assertEqual((row.id, row.player_id, row.owner_index, row.turn, row.origin), (1, active, 1, 1, 'scenario'))
                self.assertFalse(row.closed)
                self.assertFalse(any(e.kind == 'turn_started' for e in g.events))
                self.assertFalse(self.query(g, active).matched)
                self.portable(g)

    def test_first_committed_face_is_frozen_before_any_payload(self):
        g = self.game(('choice',))
        source = self.play(g, 'choice')
        play, = g.state.play_history
        self.assertFalse(play.completed)
        self.assertEqual((play.played_face.play_id, play.played_face.owner_turn_id,
                          play.played_face.source_id, play.played_face.spell_school), (1, 1, source, SpellSchool.ARCANE))
        self.portable(g)
        self.choose(g)
        self.assertEqual(g.state.play_history[0].played_face, play.played_face)

    def test_actual_end_closes_then_starts_owner_sequence(self):
        g = self.game(('dragon',))
        self.play(g, 'dragon'); self.end(g); self.end(g)
        rows = g.state.owner_turn_history
        self.assertEqual([(r.player_id, r.owner_index, r.previous_id, r.closed) for r in rows],
                         [(1, 1, None, True), (2, 1, None, True), (1, 2, 1, False)])
        self.assertEqual(rows[0].closed_action, rows[1].start_action)
        self.assertEqual(rows[0].closed_event, rows[1].start_event)
        self.assertTrue(self.query(g).matched)
        self.portable(g)

    def test_nonactive_player_uses_its_recent_closed_actual_interval(self):
        g = self.game(('dragon',), ('beast',))
        self.play(g, 'dragon'); self.end(g); self.play(g, 'beast'); self.end(g)
        match = self.query(g, 2, 'beast')
        self.assertEqual(match.owner_turn.turn, 2)
        self.assertTrue(match.matched)
        self.assertFalse(self.query(g, 2, 'dragon').matched)

    def test_current_own_plays_do_not_match_until_actual_interval_closed(self):
        g = self.game(('dragon', 'beast'))
        self.play(g, 'dragon')
        self.assertFalse(self.query(g).matched)
        self.end(g); self.end(g); self.play(g, 'beast')
        self.assertTrue(self.query(g).matched)
        self.assertFalse(self.query(g, tribe='beast').matched)
        self.end(g)
        self.assertTrue(self.query(g, tribe='beast').matched)
        self.assertFalse(self.query(g).matched)

    def test_both_players_history_are_distinct(self):
        g = self.game(('dragon',), ('beast',))
        self.play(g, 'dragon'); self.end(g); self.play(g, 'beast'); self.end(g)
        self.assertTrue(self.query(g, 1, 'dragon').matched)
        self.assertFalse(self.query(g, 1, 'beast').matched)
        self.assertTrue(self.query(g, 2, 'beast').matched)

    def test_complete_ordered_rows_include_false_faces(self):
        g = self.game(('beast', 'dragon', 'empty'))
        for card in ('beast', 'dragon', 'empty'): self.play(g, card)
        self.end(g)
        match = self.query(g)
        self.assertEqual([(r.face.card_id, r.matched) for r in match.rows],
                         [('beast', False), ('dragon', True), ('empty', False)])
        self.assertTrue(match.matched)

    def test_later_unknown_candidate_is_not_hidden_by_earlier_true(self):
        g = self.game(('dragon', 'unknown'))
        self.play(g, 'dragon'); self.play(g, 'unknown'); self.end(g)
        with self.assertRaisesRegex(ValueError, 'known Minion tribes'): self.query(g)

    def test_missing_metadata_is_unknown_not_known_empty(self):
        g = self.game(('missing-meta',))
        self.play(g, 'missing-meta'); self.end(g)
        self.assertIsNone(g.state.play_history[0].played_face.metadata)
        with self.assertRaisesRegex(ValueError, 'known Minion tribes'): self.query(g)

    def test_known_empty_never_matches_all_on_either_side(self):
        for hand, query in ((('all',), ()), (('empty',), ('all',))):
            with self.subTest(hand=hand):
                g = self.game(hand); self.play(g, hand[0]); self.end(g)
                value = query_previous_owner_turn(g.state, 1, PlayedTypeQuery(CardType.MINION, query))
                self.assertFalse(value.matched)

    def test_all_is_symmetric_against_nonempty_explicit_tribes(self):
        for hand, tribe in ((('all',), 'dragon'), (('dragon',), 'all')):
            with self.subTest(hand=hand):
                g = self.game(hand); self.play(g, hand[0]); self.end(g)
                self.assertTrue(self.query(g, tribe=tribe).matched)

    def test_unknown_subject_is_explicitly_rejected_even_without_history(self):
        g = self.game()
        with self.assertRaisesRegex(ValueError, 'subject.*unknown'):
            query_previous_owner_turn(g.state, 1, PlayedTypeQuery(CardType.MINION))

    def test_exact_school_and_unschooled_none_are_distinct(self):
        g = self.game(('arcane', 'frost', 'unschooled'))
        for card in ('arcane', 'frost', 'unschooled'): self.play(g, card)
        self.end(g)
        match = self.school(g)
        self.assertEqual([r.matched for r in match.rows], [True, False, False])
        self.assertFalse(self.school(g, None).matched)

    def test_school_query_does_not_require_irrelevant_minion_tribes(self):
        g = self.game(('unknown', 'arcane'))
        self.play(g, 'unknown'); self.play(g, 'arcane'); self.end(g)
        self.assertTrue(self.school(g).matched)

    def test_countered_spell_counts_submitted_face_without_payload(self):
        g = self.game(('arcane',), enemy_board=('counter-spell',))
        self.play(g, 'arcane')
        self.assertTrue(g.state.play_history[0].countered)
        self.assertFalse(g.state.cast_history[0].payload_started)
        self.end(g); self.assertTrue(self.school(g).matched); self.portable(g)

    def test_countered_minion_counts_submitted_face_without_summon(self):
        g = self.game(('dragon',), enemy_board=('counter-minion',))
        source = self.play(g, 'dragon')
        self.assertTrue(g.state.play_history[0].countered)
        self.assertNotIn(source, g.state.players[1].board)
        self.end(g); self.assertTrue(self.query(g).matched); self.portable(g)

    def test_failed_play_rolls_back_face_turn_events_and_rng(self):
        g = self.game(('failure',))
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'failure')
        self.assertEqual(g.snapshot(), before)
        self.assertFalse(g.state.play_history)

    def test_illegal_full_board_submission_never_creates_face(self):
        g = self.game(('dragon',), board=('empty',)*7)
        before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, 'dragon')
        self.assertEqual(g.snapshot(), before)

    def test_terminal_interruption_keeps_current_interval_open(self):
        g = self.game(('terminal',))
        self.play(g, 'terminal')
        self.assertEqual(g.state.status, 'finished')
        self.assertTrue(g.state.play_history[0].interrupted)
        self.assertFalse(g.state.owner_turn_history[-1].closed)
        self.assertFalse(self.school(g).matched)
        self.portable(g)

    def test_natural_configured_draw_closes_without_fabricating_next_turn(self):
        g = self.game(('dragon',), rules=Ruleset(draw_after_turn=1))
        self.play(g, 'dragon'); self.end(g)
        self.assertEqual(g.state.status, 'draw')
        self.assertEqual(len(g.state.owner_turn_history), 1)
        self.assertTrue(g.state.owner_turn_history[0].closed)
        self.assertTrue(self.query(g).matched); self.portable(g)

    def test_end_trigger_waiting_keeps_old_closed_interval_until_handoff(self):
        g = self.game(('dragon', 'beast'), board=('end-watcher',))
        self.play(g, 'dragon'); self.end(g)
        self.assertEqual(g.state.turn, 1)
        self.assertFalse(g.state.owner_turn_history[0].closed)
        self.assertIsNone(self.query(g).owner_turn)
        self.portable(g); self.choose(g); self.end(g); self.play(g, 'beast'); self.end(g)
        self.assertEqual(g.state.turn, 3)
        self.assertTrue(self.query(g).matched)
        self.assertFalse(self.query(g, tribe='beast').matched)
        self.portable(g); self.choose(g)
        self.assertEqual(g.state.turn, 4)
        self.assertTrue(self.query(g, tribe='beast').matched)

    def test_later_acquired_subject_sees_global_own_history(self):
        self.script('acquire', lambda c: [AddToHand(c.player_id, 'dragon')])
        g = self.game(('dragon', 'acquire'))
        self.play(g, 'dragon'); self.end(g); self.end(g); self.play(g, 'acquire')
        added = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == 'dragon')
        entry = next(e for e in g.state.hand_entries if e.id == g.state.entities[added].hand_entry_id)
        self.assertEqual(entry.turn, 3)
        self.assertTrue(query_previous_owner_turn(g.state, 1, query_for_definition(self.r.card('dragon'))).matched)

    def test_transform_and_control_changes_do_not_rewrite_submitted_face(self):
        self.script('change', lambda c: [Transform(c.target_id, 'beast'), ChangeControl(c.target_id, 2)], requires_target=True)
        g = self.game(('dragon', 'change'))
        source = self.play(g, 'dragon'); self.play(g, 'change', target=source); self.end(g)
        self.assertEqual(g.state.entities[source].card_id, 'beast')
        self.assertEqual(g.state.entities[source].controller, 2)
        self.assertTrue(self.query(g).matched)
        self.assertFalse(self.query(g, 2, 'dragon').matched)
        self.portable(g)

    def test_return_and_replay_same_physical_card_creates_distinct_face(self):
        self.script('return', lambda c: [ReturnToHand(c.target_id)], requires_target=True)
        g = self.game(('dragon', 'return'))
        source = self.play(g, 'dragon'); self.play(g, 'return', target=source)
        self.end(g); self.end(g); self.play(g, 'dragon')
        faces = [p.played_face for p in g.state.play_history if p.card_id == 'dragon']
        self.assertEqual([f.source_id for f in faces], [source, source])
        self.assertEqual([f.owner_turn_id for f in faces], [1, 3])
        self.portable(g)

    def test_summons_and_effect_casts_do_not_create_hand_faces(self):
        from hs_sim.engine.spell_casts import CastSpell
        self.script('other-sources', lambda c: [Summon(1, 'dragon'), CastSpell(1, 'arcane')])
        g = self.game(('other-sources',))
        self.play(g, 'other-sources'); self.end(g)
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual([c.origin for c in g.state.cast_history], ['hand', 'effect'])
        self.assertFalse(self.query(g).matched)
        self.assertFalse(self.school(g).matched)

    def test_true_rewind_restores_original_interval_and_single_face(self):
        g = self.game(('rewind',))
        interval = g.state.owner_turn_history[0]
        self.play(g, 'rewind'); self.portable(g)
        self.choose(g, 'retry')
        self.assertEqual(g.state.owner_turn_history, [interval])
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual(g.state.play_history[0].played_face.owner_turn_id, 1)
        self.assertEqual(g.state.action_number, 2)
        self.assertTrue(any(e.kind == 'timeline_rewound' for e in g.events))
        self.portable(g)

    def test_retained_multiple_bodies_keep_one_payment_and_one_face(self):
        g = self.game(('rewind',), board=('retainer',))
        self.play(g, 'rewind')
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].mana, 8)
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual(len(g.state.owner_turn_history), 1)
        self.assertEqual(g.state.rewind_outcomes[0].completed, 2)
        self.portable(g)

    def test_pure_queries_preserve_complete_state_events_rng_and_allocators(self):
        g = self.game(('beast', 'dragon'))
        self.play(g, 'beast'); self.play(g, 'dragon'); self.end(g)
        before = g.snapshot()
        for _ in range(4):
            self.query(g); self.query(g, 2); self.school(g)
        self.assertEqual(g.snapshot(), before)

    def test_internal_offturn_paid_root_binds_actual_interval_without_owner_fabrication(self):
        self.r.register_behavior('offturn', lambda c: [PlayFromHand(PlayCard(2,
            c.state.players[2].hand[0], position=len(c.state.players[2].board)))])
        self.r.register_card(CardDefinition('offturn-power', 'offturn-power', CardType.HERO_POWER,
            on_use='offturn', metadata=metadata(card_class=CardClass.MAGE, collectible=False)))
        g = self.game(enemy_hand=('dragon',), power='offturn-power')
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        face, = [p.played_face for p in g.state.play_history]
        self.assertEqual((face.player_id, face.owner_turn_id), (2, 1))
        self.assertEqual(g.state.owner_turn_history[0].player_id, 1)
        self.end(g)
        self.assertIsNone(self.query(g, 2).owner_turn)
        self.assertFalse(self.query(g, 1).matched)
        self.portable(g)

    def test_player_projection_never_exports_omniscient_history_or_face(self):
        g = self.game(('choice',), ('frost',))
        self.play(g, 'choice')
        for player in (1, 2):
            text = json.dumps(g.observe(player), ensure_ascii=False)
            for forbidden in ('owner_turn_history', 'played_face', 'owner_turn_id', 'closed_event', 'start_action'):
                self.assertNotIn(forbidden, text)
        self.portable(g)

    def test_strict_wire_rejects_missing_frozen_face_or_unknown_field(self):
        g = self.game(('dragon',)); self.play(g, 'dragon')
        for mutation in ('missing', 'extra', 'bool-id', 'bad-kind'):
            with self.subTest(mutation=mutation):
                s = g.snapshot(); face = s['state']['play_history'][0]['played_face']
                if mutation == 'missing': del s['state']['play_history'][0]['played_face']
                elif mutation == 'extra': face['extra'] = 0
                elif mutation == 'bool-id': face['owner_turn_id'] = True
                else: face['kind'] = 'spell'
                self.reject_rehashed(s)

    def test_strict_owner_wire_rejects_invalid_predecessor_and_open_prefix(self):
        g = self.game(); self.end(g); self.end(g)
        for mutation in ('predecessor', 'ordinal', 'open-prefix', 'cursor'):
            with self.subTest(mutation=mutation):
                s = g.snapshot(); rows = s['state']['owner_turn_history']
                if mutation == 'predecessor': rows[-1]['previous_id'] = 2
                elif mutation == 'ordinal': rows[-1]['owner_index'] = 1
                elif mutation == 'open-prefix': rows[0]['closed_action'] = rows[0]['closed_event'] = None
                else: rows[-1]['start_event'] = len(g.events)+1
                self.reject_rehashed(s)

    def test_active_original_spell_proof_rejects_rehashed_closed_interval_rewrite(self):
        g = self.game(('dragon', 'choice'))
        self.play(g, 'dragon'); self.end(g); self.end(g); self.play(g, 'choice')
        s = g.snapshot(); before = s['state']['owner_turn_history'][0]['closed_event']
        self.assertGreater(before, s['state']['owner_turn_history'][0]['start_event'])
        s['state']['owner_turn_history'][0]['closed_event'] -= 1
        self.reject_rehashed(s)

    def test_end_expiry_reaction_waiting_precedes_actual_interval_closure(self):
        self.script('install-expiry', lambda c: [AddCostModifier(1, CostSpec(delta=-1), expires_turn=c.state.turn)])
        self.r.register_behavior('expiry-choice', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('ok', 'ok', (GainArmor(c.player_id, 1),)),), source_id=c.source_id)])
        self.r.register_card(CardDefinition('expiry-watcher', 'expiry-watcher', CardType.MINION,
            health=5, metadata=metadata(), triggers=(TriggerSpec('cost_modifiers_expired', 'expiry-choice'),)))
        g = self.game(('install-expiry',), board=('expiry-watcher',))
        self.play(g, 'install-expiry'); self.end(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.turn, 1)
        self.assertFalse(g.state.owner_turn_history[0].closed)
        self.assertEqual(g.state.players[1].cost_modifiers, [])
        self.portable(g); self.choose(g)
        self.assertTrue(g.state.owner_turn_history[0].closed)
        expired = next(e for e in g.events if e.kind == 'cost_modifiers_expired')
        self.assertGreaterEqual(g.state.owner_turn_history[0].closed_event, expired.sequence)

    def test_active_end_effect_does_not_close_or_start_a_real_interval(self):
        from hs_sim.engine.end_turns import TriggerEndTurnEffects
        self.script('extra-end', lambda c: [TriggerEndTurnEffects(1,
            EndTurnRequest(EndTurnSelector('owner', (1,), ('minion',))), c.source_id)])
        g = self.game(('extra-end',), board=('end-watcher',))
        before = g.state.owner_turn_history
        self.play(g, 'extra-end'); self.portable(g)
        self.assertEqual(g.state.owner_turn_history, before)
        self.choose(g)
        self.assertEqual(g.state.owner_turn_history, before)
        self.assertEqual(g.state.turn, 1)

    def test_battlecry_waiting_binds_original_history_prefix(self):
        self.r.register_card(CardDefinition('choice-minion', 'choice-minion', CardType.MINION,
            health=5, metadata=metadata(('dragon',)), battlecry='choice'))
        g = self.game(('dragon', 'choice-minion'))
        self.play(g, 'dragon'); self.end(g); self.end(g); self.play(g, 'choice-minion')
        self.assertFalse(g.state.play_history[-1].completed)
        self.portable(g)
        s = g.snapshot(); s['state']['owner_turn_history'][0]['closed_event'] -= 1
        self.reject_rehashed(s)
        self.choose(g); self.portable(g)

    def test_hero_power_waiting_binds_original_history_prefix(self):
        self.r.register_card(CardDefinition('choice-power', 'choice-power', CardType.HERO_POWER,
            on_use='choice', metadata=metadata(card_class=CardClass.MAGE, collectible=False)))
        g = self.game(('dragon',), power='choice-power')
        self.play(g, 'dragon'); self.end(g); self.end(g)
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id)); self.portable(g)
        s = g.snapshot(); s['state']['owner_turn_history'][0]['closed_event'] -= 1
        self.reject_rehashed(s)
        self.choose(g); self.portable(g)

    def test_deathrattle_waiting_binds_original_history_prefix(self):
        self.r.register_card(CardDefinition('choice-death', 'choice-death', CardType.MINION,
            health=5, metadata=metadata(), deathrattle='choice'))
        self.r.register_behavior('destroy-death', lambda c: [Destroy(next(i for i in c.state.players[1].board
            if c.state.entities[i].card_id == 'choice-death'))])
        self.r.register_card(CardDefinition('destroy-power', 'destroy-power', CardType.HERO_POWER,
            on_use='destroy-death', metadata=metadata(card_class=CardClass.MAGE, collectible=False)))
        g = self.game(('dragon',), board=('choice-death',), power='destroy-power')
        self.play(g, 'dragon'); self.end(g); self.end(g)
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id)); self.portable(g)
        self.assertEqual(len(g.state.deathrattle_history), 1)
        s = g.snapshot(); s['state']['owner_turn_history'][0]['closed_event'] -= 1
        self.reject_rehashed(s)
        self.choose(g); self.portable(g)

    def test_terminal_midturn_cannot_be_forged_into_a_closed_interval(self):
        g = self.game(('terminal',)); self.play(g, 'terminal')
        s = g.snapshot(); row = s['state']['owner_turn_history'][-1]
        row['closed_action'], row['closed_event'] = g.state.action_number, len(g.events)
        self.reject_rehashed(s)

    def test_presentation_turn_started_event_cannot_create_an_actual_interval(self):
        mechanics = default_mechanics('h1-isolated-fake-event-test-v1')
        mechanics.register(FakeTurnStarted, lambda r, e: r.emit('turn_started', player_id=2, turn=99) and [])
        self.script('fake-start', lambda c: [FakeTurnStarted()])
        g = self.game(('fake-start',), mechanics=mechanics)
        before = g.state.owner_turn_history
        self.play(g, 'fake-start')
        self.assertTrue(any(e.kind == 'turn_started' and dict(e.data).get('turn') == 99 for e in g.events))
        self.assertEqual(g.state.owner_turn_history, before)
        self.assertEqual((g.state.turn, g.state.active_player), (1, 1))
        self.portable(g)

    def register_forms(self):
        for remaining in (1, 0):
            self.r.register_card(CardDefinition(f'form{remaining}', f'form{remaining}', CardType.MINION,
                cost=2, attack=1, health=5, on_play='rewind', metadata=metadata(('dragon',)),
                rewind=RewindSpec(1, 'form0') if remaining else None,
                keywords=(Keyword.REWIND,) if remaining else ()))

    def test_true_rewind_face_chain_keeps_actual_final_submission_face(self):
        self.register_forms()
        g = self.game(('form1',)); self.play(g, 'form1'); self.portable(g)
        self.choose(g, 'retry')
        play, = g.state.play_history
        self.assertEqual((play.card_id, play.played_face.card_id, play.played_face.owner_turn_id), ('form0', 'form0', 1))
        self.assertEqual(len(g.state.owner_turn_history), 1)
        self.portable(g)

    def test_retained_face_chain_preserves_original_single_submitted_face(self):
        self.register_forms()
        g = self.game(('form1',), board=('retainer',)); self.play(g, 'form1')
        play, = g.state.play_history
        self.assertEqual((play.card_id, play.played_face.card_id, play.played_face.owner_turn_id), ('form1', 'form1', 1))
        self.assertEqual(g.state.rewind_outcomes[0].completed, 2)
        self.assertEqual(g.state.players[1].mana, 8)
        self.portable(g)


class ConstructedOwnerTurnTests(unittest.TestCase):
    # These methods execute real opening/mulligan, independent of scenario tests.
    setUp = OwnerTurnActionTests.setUp
    query = OwnerTurnActionTests.query
    fresh_registry = OwnerTurnActionTests.fresh_registry
    portable = OwnerTurnActionTests.portable
    def constructed(self, first=1, hook=None):
        if hook is not None:
            self.r.register_behavior('opening-hook', hook)
            self.r.register_card(CardDefinition('hook', 'hook', CardType.MINION, health=5,
                metadata=metadata(), opening_hooks=(OpeningHook('before_deal', 'opening-hook'),)))
        cards = ('hook',)+('empty',)*7 if hook is not None else ('empty',)*8
        policy = DeckPolicy('h1-open', 'h1-test-only', 'experimental', tuple(self.r.cards), deck_size=8, max_copies=8)
        decks = tuple(DeckSpec(f'hero{p}', f'power{p}', cls, cards)
                      for p, cls in ((1, CardClass.MAGE), (2, CardClass.WARRIOR)))
        return Game.from_decks(MatchSetup(decks, policy, 'coin', first_player=first), self.r)

    def keep_mulligan(self, game):
        pending = game.state.pending_choice
        game.apply(SelectChoice(pending.player_id, pending.id, ()))

    def test_constructed_action_zero_and_mulligan_have_no_started_interval(self):
        g = self.constructed(first=2)
        self.assertEqual((g.state.action_number, g.state.active_player), (0, 2))
        self.assertEqual(g.state.owner_turn_history, [])
        self.assertFalse(self.query(g, 2).matched)
        self.portable(g); self.keep_mulligan(g)
        self.assertEqual(g.state.owner_turn_history, [])
        self.portable(g)

    def test_constructed_start_after_both_mulligans_records_actual_first_owner(self):
        g = self.constructed(first=2)
        self.keep_mulligan(g); self.keep_mulligan(g)
        row, = g.state.owner_turn_history
        self.assertEqual((row.player_id, row.turn, row.owner_index, row.origin, row.start_action), (2, 1, 1, 'actual', 2))
        self.assertFalse(row.closed)
        self.portable(g)

    def test_constructed_lethal_before_deal_never_creates_actual_interval(self):
        g = self.constructed(hook=lambda c: [Damage(c.state.players[2].hero_id, 50)])
        self.assertEqual(g.state.status, 'finished')
        self.assertEqual(g.state.owner_turn_history, [])
        self.assertFalse(any(e.kind == 'turn_started' for e in g.events))
        self.assertFalse(self.query(g).matched)
        self.portable(g)
