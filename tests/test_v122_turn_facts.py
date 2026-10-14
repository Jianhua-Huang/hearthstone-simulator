"""Bounded public current-turn facts candidate, not real-card CN calibration."""
from copy import deepcopy
import json
import unittest

from tests import test_v119_attack_policies as attack_fixtures
from tests.test_v119_attack_policies import Unhandled
from tests.test_m5_owner_turn_history import registry as opening_registry, metadata
from hs_sim.engine import (Attack, AttackPolicyCondition, AttackPolicySpec, CardClass,
    CardDefinition, CardType, CastSpell, CastWhenDrawnSpec, CurrentTurnFactQuery,
    DeckPolicy, DeckSpec, EndTurn, Game, GrantAttackPolicy, IllegalAction, Keyword,
    MatchSetup, OpeningHook, PlayCard, PlayerSetup, RecastSpell, ResolutionError,
    Scenario, SelectChoice, SnapshotError, SpellRepeatSpec, TargetSpec, TriggerSpec,
    current_turn_fact_count)
from hs_sim.engine.combat import attack_error
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, Draw, Freeze,
    GrantKeyword, ModifyWeapon, ReplaceHero, RequestChoice, Summon)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.serialization import canonical_hash

ORIGINS = ('hand', 'repeat', 'effect', 'draw', 'history')

def spell_query(phase='payload_accepted', origins=ORIGINS, window='owner_turn'):
    return CurrentTurnFactQuery('spell_cast', phase, window, origins)

def hero_query(window='owner_turn'):
    return CurrentTurnFactQuery('hero_attack', 'declared', window)

def condition(query, comparison='lt', value=1):
    return AttackPolicyCondition('current_turn_fact_count', comparison, value, turn_fact=query)

class TurnFactTests(unittest.TestCase):
    def setUp(self):
        self.f = attack_fixtures.AttackPolicyTests(methodName='runTest'); self.f.setUp()

    def count(self, game, query=None, player=1):
        return current_turn_fact_count(game.state, player, query or spell_query())

    def actor(self, name='fact_actor', query=None, **fields):
        self.f.r.register_card(CardDefinition(name, name, CardType.MINION, attack=1, health=30,
            keywords=(Keyword.CHARGE,), attack_policies=(AttackPolicySpec('cannot_attack',
            conditions=(condition(query or spell_query()),)),), **fields))

    def choose(self, game):
        choice = game.state.pending_choice
        return game.apply(SelectChoice(choice.player_id, choice.id, (choice.options[0].id,)))

    def reject_rehashed(self, game, snapshot):
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(snapshot, self.f.r)

    def test_prior_cast_counts_before_minion_entry_without_extra_cast_for_minion(self):
        f = self.f; self.actor()
        g = f.game(board=(), hand=('armor', 'fact_actor'), enemy=())
        self.assertEqual(self.count(g), 0)
        f.cast(g, 'armor'); f.cast(g, 'fact_actor')
        self.assertEqual(self.count(g), 1)
        self.assertTrue(f.attacks(g))
        self.assertEqual(len(g.state.play_history), 2)
        f.check(g)

    def test_manual_countered_attempt_is_not_payload_or_successful_completion(self):
        f = self.f
        f.r.register_behavior('counter', lambda c: [CounterSpell(dict(c.event.data)['window_id'])]
            if c.play is not None and c.play.kind == CardType.SPELL else [])
        f.r.register_card(CardDefinition('counter', 'counter', CardType.MINION, health=30,
                                         triggers=(TriggerSpec('card_committed', 'counter'),)))
        g = f.game(hand=('armor',), enemy=('counter',))
        f.cast(g, 'armor')
        self.assertEqual([self.count(g, spell_query(phase)) for phase in ('attempt', 'payload_accepted', 'completed')], [1, 0, 0])
        self.assertEqual(g.state.cast_history[0].failure, 'countered')
        self.assertEqual(g.state.cast_history[0].owner_turn_id, 1)
        f.check(g)

    def test_automatic_no_target_attempt_is_not_payload_or_completion(self):
        f = self.f
        f.r.register_behavior('minion_only', lambda c: [Damage(c.target_id, 1)])
        f.r.register_card(CardDefinition('minion_only', 'minion_only', CardType.SPELL, on_play='minion_only',
                                         targeting=TargetSpec(kinds=(CardType.MINION,))))
        f.spell('driver', lambda c: [CastSpell(1, 'minion_only', c.source_id)])
        g = f.game(hand=('driver',), enemy=())
        f.cast(g, 'driver')
        self.assertEqual([self.count(g, spell_query(p, ('effect',))) for p in ('attempt', 'payload_accepted', 'completed')], [1, 0, 0])
        self.assertEqual(g.state.cast_history[-1].failure, 'no_target')
        f.check(g)

    def test_automatic_two_waits_distinguish_attempt_acceptance_and_completion(self):
        f = self.f; self.actor(query=spell_query(origins=('effect',)))
        f.r.register_behavior('start_pause', lambda c: [RequestChoice(1,
            (ChoiceOption('continue', 'Continue'),), source_id=c.source_id)])
        f.r.register_card(CardDefinition('start_listener', 'start_listener', CardType.MINION, health=30,
                                         triggers=(TriggerSpec('spell_cast_started', 'start_pause'),)))
        queued = AttackPolicySpec('cannot_attack_heroes', conditions=(condition(spell_query('completed', ('effect',)), 'ge'),))
        f.spell('chooser', lambda c: [RequestChoice(1, (ChoiceOption('finish', 'Finish',
            (GrantAttackPolicy(c.state.players[1].board[0], queued),)),), source_id=c.source_id)])
        f.spell('driver', lambda c: [CastSpell(1, 'chooser', c.source_id, choices='player')])
        g = f.game(board=('fact_actor', 'start_listener'), hand=('driver',), enemy=())
        actor = f.unit(g).id
        f.cast(g, 'driver')
        queries = [spell_query(p, ('effect',)) for p in ('attempt', 'payload_accepted', 'completed')]
        self.assertEqual([self.count(g, q) for q in queries], [1, 0, 0])
        self.assertEqual(attack_error(g.state, actor, f.hero(g), 1, registry=f.r), 'Current policy prevents attacking')
        f.check(g); self.choose(g)
        self.assertEqual([self.count(g, q) for q in queries], [1, 1, 0])
        self.assertIsNone(attack_error(g.state, actor, f.hero(g), 1, registry=f.r))
        listing = json.dumps(g.for_player(1).legal_actions())
        self.assertNotIn('turn_fact', listing); self.assertNotIn('owner_turn_id', listing)
        restored = Game.from_snapshot(json.loads(json.dumps(g.snapshot())), f.r)
        f.check(g)
        choice = g.state.pending_choice
        action = SelectChoice(1, choice.id, (choice.options[0].id,))
        g.apply(action); restored.apply(action)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual([self.count(g, q) for q in queries], [1, 1, 1])
        self.assertEqual(attack_error(g.state, actor, f.hero(g), 1, registry=f.r), 'Current policy prevents attacking heroes')
        f.check(g)

    def test_manual_payload_wait_is_accepted_before_it_is_completed(self):
        f = self.f; self.actor()
        f.spell('wait', lambda c: [RequestChoice(1, (ChoiceOption('ok', 'OK'),), source_id=c.source_id)])
        g = f.game(board=('fact_actor',), hand=('wait',), enemy=())
        f.cast(g, 'wait')
        self.assertEqual([self.count(g, spell_query(p)) for p in ('attempt', 'payload_accepted', 'completed')], [1, 1, 0])
        f.check(g); self.choose(g)
        self.assertEqual(self.count(g, spell_query('completed')), 1)
        f.check(g)

    def test_all_five_origins_are_independent_real_facts_and_explicitly_filterable(self):
        f = self.f
        f.r.register_card(CardDefinition('repeat_source', 'repeat_source', CardType.MINION, health=30,
                                         spell_repeats=(SpellRepeatSpec(2, class_mode='any'),)))
        f.r.register_behavior('draw_auto', lambda c: [])
        f.r.register_card(CardDefinition('draw_auto', 'draw_auto', CardType.SPELL, on_play='draw_auto',
            keywords=(Keyword.CASTS_WHEN_DRAWN,), cast_when_drawn=CastWhenDrawnSpec()))
        f.spell('driver', lambda c: [CastSpell(1, 'armor', c.source_id), Draw(1), RecastSpell(1, 2, c.source_id)])
        g = Game.from_scenario(Scenario((
            PlayerSetup('hero', board=('repeat_source',), hand=('driver',), deck=('draw_auto',)+('plain',)*10, mana=10, max_mana=10),
            PlayerSetup('hero', deck=('plain',)*10, mana=10, max_mana=10)), seed=41), f.r)
        f.cast(g, 'driver')
        self.assertEqual([self.count(g, spell_query('completed', (origin,))) for origin in ORIGINS], [1, 1, 2, 1, 2])
        self.assertEqual(self.count(g), 7)
        self.assertTrue(all(c.owner_turn_id == 1 for c in g.state.cast_history))
        self.assertEqual(len(g.state.play_history), 1)
        f.check(g)

    def test_nonactive_caster_current_turn_does_not_become_its_own_turn(self):
        f = self.f
        f.spell('other_cast', lambda c: [CastSpell(2, 'armor', c.source_id)])
        g = f.game(hand=('other_cast',), enemy=())
        f.cast(g, 'other_cast')
        self.assertEqual(self.count(g, spell_query(window='current_turn'), 2), 1)
        self.assertEqual(self.count(g, spell_query(window='owner_turn'), 2), 0)
        record = g.state.cast_history[-1]
        self.assertEqual((record.player_id, record.owner_turn_id), (2, 1))
        g.apply(EndTurn(1))
        self.assertEqual(self.count(g, spell_query(window='owner_turn'), 2), 0)
        f.check(g)

    def test_actual_handoff_does_not_reuse_previous_owner_cast_facts(self):
        f = self.f; self.actor()
        g = f.game(board=('fact_actor',), hand=('armor',), enemy=())
        f.cast(g, 'armor'); self.assertTrue(f.attacks(g))
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(g.state.owner_turn_history[-1].id, 3)
        self.assertEqual(self.count(g), 0)
        self.assertFalse(f.attacks(g))
        f.check(g)

    def test_hero_declaration_survives_actual_freeze_cancellation(self):
        f = self.f; self.actor(query=hero_query())
        f.r.register_behavior('cancel_hero', lambda c: [Freeze(c.event.source_id)]
            if c.state.entities[c.event.source_id].kind == CardType.HERO else [])
        f.r.register_card(CardDefinition('freeze_listener', 'freeze_listener', CardType.MINION, health=30,
                                         triggers=(TriggerSpec('attack_declared', 'cancel_hero'),)))
        g = f.game(board=('fact_actor',), weapon='weapon', enemy=('freeze_listener',))
        self.assertFalse(f.attacks(g, f.unit(g).id))
        result = f.attack(g, source=f.hero(g, 1))
        self.assertTrue(any(e.kind == 'attack_cancelled' for e in result.events))
        self.assertFalse(any(e.kind == 'attack_finished' for e in result.events))
        self.assertEqual(self.count(g, hero_query()), 1)
        self.assertTrue(f.attacks(g, f.unit(g).id))
        f.check(g)

    def test_zero_damage_hero_exchange_is_completed_without_fabricating_history(self):
        f = self.f
        f.r.register_behavior('zero_hero', lambda c: [ModifyWeapon(c.state.players[1].weapon_id, attack=-1)])
        f.r.register_card(CardDefinition('zero_listener', 'zero_listener', CardType.MINION, health=30,
                                         triggers=(TriggerSpec('attack_declared', 'zero_hero'),)))
        g = f.game(weapon='weapon', enemy=('zero_listener',))
        result = f.attack(g, source=f.hero(g, 1))
        self.assertTrue(any(e.kind == 'attack_finished' for e in result.events))
        self.assertEqual(g.state.entities[f.hero(g)].damage, 0)
        self.assertEqual(self.count(g, hero_query()), 1)
        with self.assertRaises(ValueError): CurrentTurnFactQuery('hero_attack', 'completed', 'owner_turn')
        f.check(g)

    def test_hero_replacement_weapon_change_and_handoff_preserve_then_clear_declarations(self):
        f = self.f
        f.r.register_card(CardDefinition('hero_form', 'hero_form', CardType.HERO, health=100))
        f.spell('replace', lambda c: [ReplaceHero(1, 'hero_form')])
        g = f.game(weapon='megaweapon', hand=('replace', 'equip'), enemy=())
        f.attack(g, source=f.hero(g, 1)); f.attack(g, source=f.hero(g, 1))
        original = f.hero(g, 1)
        f.cast(g, 'replace'); f.cast(g, 'equip')
        self.assertNotEqual(f.hero(g, 1), original)
        self.assertEqual(self.count(g, hero_query()), 2)
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(self.count(g, hero_query()), 0)
        f.check(g)

    def test_current_copy_transfer_and_silence_use_current_controller_facts(self):
        f = self.f; self.actor()
        f.spell('give', lambda c: [ChangeControl(c.target_id, 2)], True)
        g = f.game(board=('fact_actor',), hand=('armor', 'copy', 'give', 'silence'), enemy=())
        f.cast(g, 'armor'); f.cast(g, 'copy', f.unit(g).id)
        copied = f.unit(g, 1).id
        self.assertTrue(f.attacks(g, copied))
        f.cast(g, 'give', copied)
        self.assertEqual(attack_error(g.state, copied, f.hero(g, 1), 2, registry=f.r), 'Current policy prevents attacking')
        f.cast(g, 'silence', copied)
        # Silence also removes Charge; normal entry sleep remains this turn.
        self.assertEqual(attack_error(g.state, copied, f.hero(g, 1), 2, registry=f.r), 'New minion cannot attack this target')
        g.apply(EndTurn(1))
        self.assertIsNone(attack_error(g.state, copied, f.hero(g, 1), 2, registry=f.r))
        f.check(g)

    def test_freeze_deadline_reads_turn_condition_without_consuming_attacks(self):
        f = self.f; self.actor()
        g = f.game(board=('fact_actor',), hand=('freeze',), enemy=())
        # The freeze spell is accepted before freezing, so this actor has an opportunity.
        f.cast(g, 'freeze', f.unit(g).id)
        self.assertEqual(f.unit(g).frozen_until_owner_turn, 1)
        self.assertEqual(f.unit(g).attacks_this_turn, 0)
        f.check(g)

    def test_unknown_later_effect_rolls_back_cast_and_query_attachment(self):
        f = self.f
        f.spell('fail', lambda c: [GrantAttackPolicy(c.target_id,
            AttackPolicySpec('cannot_attack', conditions=(condition(spell_query()),))), Unhandled()], True)
        g = f.game(board=('plain',), hand=('fail',), enemy=())
        before = g.snapshot()
        with self.assertRaises(ResolutionError): f.cast(g, 'fail', f.unit(g).id)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(self.count(g), 0)

    def test_pre_first_and_actual_first_cast_same_action_have_distinct_interval_identity(self):
        f = self.f; r = opening_registry(); f.r = r
        r.register_behavior('actual_cast', lambda c: [CastSpell(1, 'arcane', c.source_id)])
        r.register_card(CardDefinition('start_cast', 'start_cast', CardType.MINION, health=5,
            metadata=metadata(), triggers=(TriggerSpec('turn_started', 'actual_cast'),)))
        r.register_behavior('opening_cast', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('go', 'Go', (CastSpell(c.player_id, 'arcane', c.source_id), Summon(c.player_id, 'start_cast'))),),
            source_id=c.source_id)])
        r.register_card(CardDefinition('hook', 'hook', CardType.MINION, health=5, metadata=metadata(),
            opening_hooks=(OpeningHook('after_mulligan', 'opening_cast'),)))
        policy = DeckPolicy('turn-facts-opening', 'synthetic-turn-facts-opening', 'experimental', tuple(r.cards), deck_size=8, max_copies=8)
        decks = (DeckSpec('hero1', 'power1', CardClass.MAGE, ('hook',)+('empty',)*7),
                 DeckSpec('hero2', 'power2', CardClass.WARRIOR, ('empty',)*8))
        g = Game.from_decks(MatchSetup(decks, policy, 'coin', first_player=1), r)
        for _ in range(2):
            c = g.state.pending_choice; g.apply(SelectChoice(c.player_id, c.id, ()))
        self.assertEqual(self.count(g), 0)
        f.check(g); self.choose(g)
        pre, actual = g.state.cast_history
        interval = g.state.owner_turn_history[0]
        self.assertEqual((pre.turn, pre.action), (actual.turn, actual.action))
        self.assertEqual((pre.owner_turn_id, actual.owner_turn_id), (None, 1))
        self.assertLess(pre.recorded_event, interval.start_event)
        self.assertGreaterEqual(actual.recorded_event, interval.start_event)
        self.assertEqual(self.count(g), 1)
        f.check(g)
        for index, wrong in ((0, 1), (1, None)):
            tampered = deepcopy(g.snapshot()); tampered['state']['cast_history'][index]['owner_turn_id'] = wrong
            self.reject_rehashed(g, tampered)

    def test_unknown_profiles_misplaced_queries_and_forged_intervals_rejected(self):
        for build in (
            lambda: CurrentTurnFactQuery('unknown', 'declared', 'owner_turn'),
            lambda: CurrentTurnFactQuery('spell_cast', 'unknown', 'owner_turn', ORIGINS),
            lambda: CurrentTurnFactQuery('spell_cast', 'completed', 'previous_owner_turn', ORIGINS),
            lambda: CurrentTurnFactQuery('spell_cast', 'completed', 'owner_turn'),
            lambda: CurrentTurnFactQuery('spell_cast', 'completed', 'owner_turn', ('hand', 'hand')),
            lambda: CurrentTurnFactQuery('hero_attack', 'declared', 'owner_turn', ('hand',)),
            lambda: AttackPolicyCondition('current_turn_fact_count', 'eq', 1),
            lambda: AttackPolicyCondition('attack', 'eq', 1, turn_fact=hero_query()),
        ):
            with self.assertRaises(ValueError): build()
        f = self.f; self.actor()
        g = f.game(board=('fact_actor',), hand=('armor',), enemy=())
        f.cast(g, 'armor')
        for field, wrong in (('owner_turn_id', None), ('owner_turn_id', 99), ('recorded_event', -1), ('recorded_event', 10**9)):
            tampered = deepcopy(g.snapshot()); tampered['state']['cast_history'][0][field] = wrong
            self.reject_rehashed(g, tampered)
        tampered = deepcopy(g.snapshot())
        policy = next(a for a in tampered['state']['entities'][str(f.unit(g).id)]['abilities'] if a['kind'] == 'attack_policy')
        policy['attack_policy']['conditions'][0]['turn_fact']['phase'] = 'unknown'
        self.reject_rehashed(g, tampered)

    def test_terminal_interrupted_payload_keeps_acceptance_without_completion(self):
        f = self.f
        f.spell('terminal', lambda c: [Damage(c.state.players[2].hero_id, 1000)])
        g = f.game(hand=('terminal',), enemy=())
        f.cast(g, 'terminal')
        self.assertEqual(g.state.status, 'finished')
        self.assertEqual([self.count(g, spell_query(p)) for p in ('attempt', 'payload_accepted', 'completed')], [1, 1, 0])
        self.assertTrue(g.state.cast_history[0].interrupted)
        f.check(g)

    def test_query_is_pure_and_player_legality_does_not_export_history(self):
        f = self.f; self.actor()
        g = f.game(board=('fact_actor',), hand=('armor',), enemy=())
        f.cast(g, 'armor'); before = g.snapshot()
        for _ in range(3): self.assertEqual(self.count(g), 1)
        self.assertEqual(g.snapshot(), before)
        listing = g.for_player(1).legal_actions()
        self.assertNotIn('cast_history', json.dumps(listing)); self.assertNotIn('turn_fact', json.dumps(listing))
        action = next(a for a in listing['actions'] if a['type'] == 'attack')
        result = g.for_player(1).submit({'revision': listing['revision'], 'action': action})
        self.assertTrue(result['accepted'])
        f.check(g)
