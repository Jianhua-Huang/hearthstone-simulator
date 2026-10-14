"""Player policies own accepted roots, independently of payload repetitions."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (AddChooseBothModifier, RemoveChooseBothModifier, CardDefinition,
    CardType, CastSpell, CastWhenDrawnSpec, ChooseBranch, ChooseOneSpec, EndTurn, Game,
    GrantChooseBoth, IllegalAction, Keyword, PlayCard, PlayerSetup, Registry, RewindSpec,
    Scenario, SelectChoice, SpellRepeatSpec, TriggerHeroPower, TriggerSpec, UseHeroPower,
    RecastSpell, CastStoredSpell, CounterSpell, CounterMinion, TargetSpec, Zone)
from hs_sim.engine.effects import (ChoiceOption, Damage, Draw, GainArmor, RandomDamage,
    RequestChoice, ReturnToHand, Silence, Summon, Transform, ChangeControl, Destroy)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.generated_combo_repeats import PROFILES
from hs_sim.engine.zones import CardReference
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION


def registry(mode='normal', policies=None, profile=PROFILES[0]):
    policies = policies if policies is not None else (AddChooseBothModifier(1, uses=1),)
    r = Registry('player-choose-both-' + mode + '-' + profile + '-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
    r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, health=8))
    r.register_card(CardDefinition('both_source', 'Both source', CardType.MINION, health=8, choose_both=True))
    r.register_card(CardDefinition('repeat', 'Repeat', CardType.MINION, health=8,
        spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
    r.register_card(CardDefinition('retainer', 'Retainer', CardType.MINION, health=8, retain_rewind_outcomes=True))
    def grant(c):
        source = c.state.players[1].board[0] if mode in ('board_source', 'silence', 'transform', 'control', 'bounce', 'destroy') else c.source_id
        return tuple(replace(p, source_id=source) for p in policies)
    r.register_behavior('grant', grant)
    r.register_card(CardDefinition('policy', 'Policy', CardType.SPELL, on_play='grant'))
    def body(c, amount):
        work = [GainArmor(c.player_id, amount)]
        if mode == 'nested_wait' and c.cast is not None and c.cast.origin == 'effect' and len(c.state.choose_policy_receipts) == 1:
            work.append(CastSpell(c.player_id, 'spell', c.source_id, choices='player'))
        if mode in ('wait', 'nested_wait'): work.append(RequestChoice(c.player_id, (ChoiceOption('go', 'Go'),), c.source_id))
        if mode == 'fail': work.extend((RandomDamage(tuple(c.state.players[2].board), 1), Summon(c.player_id, 'unknown.choose.result')))
        if mode == 'terminal': work.append(Damage(c.state.players[2].hero_id, 90))
        if mode == 'grant_during_body': work.append(AddChooseBothModifier(c.player_id, c.source_id, uses=1))
        return tuple(work)
    for name, amount in (('left', 2), ('right', 4), ('both', 7)):
        r.register_behavior(name, lambda c, n=amount: body(c, n))
    r.register_behavior('extra', lambda c: (GainArmor(c.player_id, 1),))
    both_target = TargetSpec(kinds=(CardType.MINION,), zones=(Zone.BOARD,), relation='enemy') if mode == 'no_target' else None
    spec = ChooseOneSpec((ChooseBranch('left', 'Left', 'left'), ChooseBranch('right', 'Right', 'right')),
                         ChooseBranch('both', 'Both', 'both', both_target))
    for name, kind in (('spell', CardType.SPELL), ('minion', CardType.MINION), ('power', CardType.HERO_POWER)):
        r.register_card(CardDefinition(name, name, kind, cost=1, health=8 if kind == CardType.MINION else 0,
            choose_one=spec))
    r.register_card(CardDefinition('draw_spell', 'Draw spell', CardType.SPELL, choose_one=spec,
        cast_when_drawn=CastWhenDrawnSpec(), keywords=(Keyword.CASTS_WHEN_DRAWN,)))
    r.register_card(CardDefinition('rewind_spell', 'Rewind spell', CardType.SPELL, cost=1,
        choose_one=spec, keywords=(Keyword.REWIND,), rewind=RewindSpec()))
    r.register_behavior('auto', lambda c: (CastSpell(c.player_id, 'spell', c.source_id, choices='player',
        branch_id='left' if mode == 'auto_conflict' else None),))
    r.register_card(CardDefinition('auto', 'Auto', CardType.SPELL, on_play='auto'))
    r.register_behavior('trigger', lambda c: (TriggerHeroPower(c.player_id, c.source_id, choices='player'),))
    r.register_card(CardDefinition('trigger', 'Trigger', CardType.SPELL, on_play='trigger'))
    r.register_behavior('draw', lambda c: (Draw(c.player_id, 1, c.source_id),))
    r.register_card(CardDefinition('draw', 'Draw', CardType.SPELL, on_play='draw'))
    r.register_behavior('stored', lambda c: (CastStoredSpell(CardReference.capture(c.state.entities[next(
        i for i in c.state.players[1].hand if c.state.entities[i].card_id == 'spell')]), c.player_id, c.source_id, choices='player'),))
    r.register_card(CardDefinition('stored', 'Stored', CardType.SPELL, on_play='stored'))
    r.register_behavior('recast', lambda c: (RecastSpell(c.player_id, next(row.id for row in reversed(c.state.cast_history)
        if row.card_id == 'spell' and row.completed and row.failure is None), c.source_id, choices='player'),))
    r.register_card(CardDefinition('recast', 'Recast', CardType.SPELL, on_play='recast'))
    def mutate(c):
        target = c.state.players[1].board[0]
        if mode == 'silence': return (Silence(target),)
        if mode == 'transform': return (Transform(target, 'plain'),)
        if mode == 'control': return (ChangeControl(target, 2),)
        if mode == 'bounce': return (ReturnToHand(target),)
        if mode == 'remove': return (RemoveChooseBothModifier(1, c.state.players[1].choose_both_modifiers[0].id),)
        return (Destroy(target),)
    r.register_behavior('mutate', mutate)
    r.register_card(CardDefinition('mutate', 'Mutate', CardType.SPELL, on_play='mutate'))
    def counter(c):
        source = c.state.entities[c.event.source_id]
        if source.card_id not in ('spell', 'minion'): return ()
        identity = dict(c.event.data)['window_id']
        return (CounterSpell(identity) if source.kind == CardType.SPELL else CounterMinion(identity),)
    r.register_behavior('counter', counter)
    r.register_card(CardDefinition('counter', 'Counter', CardType.MINION, health=8,
        triggers=(TriggerSpec('card_committed', 'counter'),)))
    def event_wait(c):
        if c.state.entities[c.event.source_id].card_id not in ('spell', 'minion'): return ()
        return (RequestChoice(c.player_id, (ChoiceOption('go', 'Go'),), c.source_id),)
    r.register_behavior('event_wait', event_wait)
    r.register_card(CardDefinition('watch', 'Watch', CardType.MINION, health=8,
        triggers=(TriggerSpec('card_committed' if mode == 'commit_wait' else 'card_played', 'event_wait'),)))
    def expiry_regrant(c):
        if c.state.entities[c.state.players[1].hero_id].armor: return ()
        return (GainArmor(1, 1), AddChooseBothModifier(1, c.source_id, expires_turn=c.state.turn))
    r.register_behavior('expiry_regrant', expiry_regrant)
    r.register_card(CardDefinition('expiry_watch', 'Expiry watch', CardType.MINION, health=8,
        triggers=(TriggerSpec('choose_both_modifier_expired', 'expiry_regrant'),)))
    r.register_behavior('generate', lambda c: (
        *(Destroy(i) for i in c.state.players[1].board if c.state.entities[i].card_id == 'minion'),
        *((Summon(1, 'plain'),) * 7 if mode == 'full' else ()),
        ReplayWholeCards(c.player_id, c.source_id,
            WholeCardHistoryQuery(c.player_id, len(c.state.play_history) + 1, kinds=(CardType.MINION,)),
            physical_profile=profile, choices='player')))
    r.register_card(CardDefinition('generate', 'Generate', CardType.SPELL, on_play='generate'))
    return r


def game(mode='normal', policies=None, profile=PROFILES[0], hand=('policy', 'spell', 'minion', 'spell'), board=(), deck=('plain',) * 8, enemy=('plain',)):
    return Game.from_scenario(Scenario((
        PlayerSetup('hero', hero_power_card_id='power', hand=hand, board=board, deck=deck, mana=10, max_mana=10),
        PlayerSetup('hero', hero_power_card_id='power', board=enemy, hand=('spell',), deck=('plain',) * 8, mana=10, max_mana=10)),
        seed=76), registry(mode, policies, profile))


def play(g, card, branch=None, player=1):
    source = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == card)
    g.apply(PlayCard(player, source, branch_id=branch))
    return source


class PlayerChooseBothTests(unittest.TestCase):
    def armor(self, g): return g.state.entities[g.state.players[1].hero_id].armor
    def check(self, g, mode='normal', policies=None, profile=PROFILES[0]):
        saved = json.loads(json.dumps(g.snapshot()))
        independent = registry(mode, policies, profile)
        restored = Game.from_snapshot(saved, independent)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(mode, policies, profile)).snapshot(), saved)
        for player in (1, 2): self.assertEqual(g.observe(player), restored.observe(player))
    def choose_all(self, g):
        count = 0
        while g.state.pending_choice is not None:
            choice = g.state.pending_choice
            g.apply(SelectChoice(choice.player_id, choice.id, ('go',)))
            count += 1
        return count
    def test_queries_do_not_consume_and_one_paid_root_consumes_once(self):
        g = game(); play(g, 'policy')
        saved = g.snapshot()
        for _ in range(3):
            actions = g.legal_actions()
            self.assertEqual({a.branch_id for a in actions if type(a) is PlayCard}, {'both'})
            g.legal_targets(g.state.players[1].hand[0], branch_id='both')
            g.for_player(1).legal_actions()
        self.assertEqual(g.snapshot(), saved)
        play(g, 'spell', 'both')
        self.assertEqual((self.armor(g), len(g.state.choose_policy_receipts)), (7, 1))
        self.assertEqual(g.state.players[1].choose_both_modifiers, [])
        play(g, 'minion', 'left')
        self.assertEqual(self.armor(g), 9)
        self.check(g)
    def test_persistent_policy_survives_two_paid_roots(self):
        policies = (AddChooseBothModifier(1),)
        g = game(policies=policies); play(g, 'policy')
        play(g, 'spell', 'both'); play(g, 'minion', 'both')
        self.assertEqual(self.armor(g), 14)
        self.assertEqual(len(g.state.choose_policy_receipts), 2)
        self.assertIsNone(g.state.players[1].choose_both_modifiers[0].uses_remaining)
        self.check(g, policies=policies)
    def test_automatic_cast_accepts_separate_qualified_root(self):
        policies = (AddChooseBothModifier(1, uses=1, kinds=(CardType.SPELL,), origins=('cast_effect',)),)
        g = game(policies=policies, hand=('policy', 'auto', 'spell')); play(g, 'policy')
        play(g, 'auto')
        self.assertEqual(self.armor(g), 7)
        self.assertEqual(g.state.cast_history[-1].branch_id, 'both')
        self.assertEqual(g.state.choose_policy_receipts[0].root_kind, 'cast')
        play(g, 'spell', 'left'); self.check(g, policies=policies)
    def test_power_scope_does_not_borrow_hand_policy(self):
        g = game(); play(g, 'policy')
        power = g.state.players[1].hero_power_id
        g.apply(UseHeroPower(1, power, branch_id='left'))
        self.assertEqual(g.state.players[1].choose_both_modifiers[0].uses_remaining, 1)
        play(g, 'spell', 'both'); self.check(g)
    def test_generated_physical_root_has_its_own_acceptance(self):
        policies = (AddChooseBothModifier(1, uses=1, kinds=(CardType.MINION,), origins=('physical',)),)
        for profile in PROFILES:
            with self.subTest(profile=profile):
                g = game(policies=policies, profile=profile, hand=('minion', 'policy', 'generate'))
                play(g, 'minion', 'left'); play(g, 'policy'); play(g, 'generate')
                self.assertEqual(self.armor(g), 9)
                receipt = g.state.choose_policy_receipts[0]
                self.assertEqual((receipt.root_kind, receipt.profile_id), ('physical', profile))
                self.check(g, policies=policies, profile=profile)
    def test_all_matching_finite_policies_consume_independently_alongside_board_and_persistent_sources(self):
        policies = (AddChooseBothModifier(1, uses=2), AddChooseBothModifier(1, uses=1), AddChooseBothModifier(1))
        g = game(policies=policies, board=('both_source',)); play(g, 'policy')
        play(g, 'spell', 'both')
        self.assertEqual([m.uses_remaining for m in g.state.players[1].choose_both_modifiers], [1, None])
        self.assertEqual(len(g.state.choose_policy_receipts[0].modifier_ids), 3)
        self.assertEqual(len(g.state.choose_policy_receipts[0].board_source_ids), 1)
        play(g, 'minion', 'both')
        self.assertEqual([m.uses_remaining for m in g.state.players[1].choose_both_modifiers], [None])
        self.assertEqual(sum(e.kind == 'choose_both_modifier_used' for e in g.events), 3)
        self.check(g, policies=policies)
    def test_kind_filter_leaves_unmatched_policy_for_later_root(self):
        policies = (AddChooseBothModifier(1, uses=1, kinds=(CardType.SPELL,)),)
        g = game(policies=policies); play(g, 'policy'); play(g, 'minion', 'left')
        self.assertEqual(g.state.players[1].choose_both_modifiers[0].uses_remaining, 1)
        self.assertEqual(g.state.choose_policy_receipts, [])
        play(g, 'spell', 'both'); self.check(g, policies=policies)
    def test_opponent_policy_and_clock_are_owned_by_that_player(self):
        policies = (AddChooseBothModifier(2, uses=1),)
        g = game(policies=policies); play(g, 'policy'); play(g, 'spell', 'left')
        self.assertEqual(g.state.players[2].choose_both_modifiers[0].uses_remaining, 1)
        g.apply(EndTurn(1)); play(g, 'spell', 'both', player=2)
        self.assertEqual(g.state.choose_policy_receipts[0].player_id, 2)
        self.assertEqual(g.state.players[2].choose_both_modifiers, [])
        self.check(g, policies=policies)
    def test_expiry_removes_all_policies_at_global_boundary(self):
        policies = (AddChooseBothModifier(1, uses=2, expires_turn=1), AddChooseBothModifier(2, expires_turn=1))
        g = game(policies=policies); play(g, 'policy'); play(g, 'spell', 'both'); g.apply(EndTurn(1))
        self.assertEqual([p.choose_both_modifiers for p in g.state.players.values()], [[], []])
        self.assertEqual(sum(e.kind == 'choose_both_modifier_expired' for e in g.events), 2)
        self.check(g, policies=policies)
    def test_player_policy_survives_source_lifecycle_changes(self):
        policies = (AddChooseBothModifier(1, uses=1),)
        for mode in ('silence', 'transform', 'control', 'bounce', 'destroy'):
            with self.subTest(mode=mode):
                # This fixture binds the public policy to the board carrier.
                g = game(mode, policies, board=('both_source',), hand=('policy', 'mutate', 'spell'))
                play(g, 'policy'); source = g.state.players[1].choose_both_modifiers[0].source_id
                play(g, 'mutate'); play(g, 'spell', 'both')
                self.assertEqual(self.armor(g), 7)
                self.assertEqual(g.state.choose_policy_receipts[0].original_modifiers[0].source_id, source)
                self.check(g, mode, policies)
    def test_invalid_manual_branch_is_atomic(self):
        g = game(); play(g, 'policy'); saved = g.snapshot()
        for branch in (None, 'left', 'right', 'unknown'):
            with self.subTest(branch=branch), self.assertRaises(IllegalAction): play(g, 'spell', branch)
            self.assertEqual(g.snapshot(), saved)
    def test_automatic_explicit_conflict_rolls_back_outer_payment_and_policy(self):
        policies = (AddChooseBothModifier(1, uses=1, kinds=(CardType.SPELL,), origins=('cast_effect',)),)
        g = game('auto_conflict', policies, hand=('policy', 'auto')); play(g, 'policy'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): play(g, 'auto')
        self.assertEqual(g.snapshot(), saved)
    def test_failed_automatic_target_is_a_consumed_branch_attempt(self):
        policies = (AddChooseBothModifier(1, uses=1, kinds=(CardType.SPELL,), origins=('cast_effect',)),)
        g = game('no_target', policies, hand=('policy', 'auto'), enemy=()); play(g, 'policy'); play(g, 'auto')
        self.assertEqual((g.state.cast_history[-1].branch_id, g.state.cast_history[-1].failure), ('both', 'no_target'))
        self.assertEqual(g.state.players[1].choose_both_modifiers, [])
        self.assertIsNotNone(g.state.choose_policy_receipts[0].closed_action)
        self.check(g, 'no_target', policies)
    def test_draw_and_history_casts_have_fresh_matching_windows(self):
        policies = (AddChooseBothModifier(1, uses=2, kinds=(CardType.SPELL,), origins=('cast_draw', 'cast_history')),)
        g = game(policies=policies, hand=('policy', 'spell', 'recast', 'draw'), deck=('draw_spell', 'plain', 'plain'))
        play(g, 'spell', 'left'); play(g, 'policy'); play(g, 'recast'); play(g, 'draw')
        self.assertEqual([r.origin for r in g.state.choose_policy_receipts], ['cast_history', 'cast_draw'])
        self.assertEqual(self.armor(g), 16)
        self.assertEqual(g.state.players[1].choose_both_modifiers, [])
        self.check(g, policies=policies)
    def test_stored_spell_is_effect_root_without_inventing_paid_hand_play(self):
        policies = (AddChooseBothModifier(1, uses=1, kinds=(CardType.SPELL,), origins=('cast_effect',)),)
        g = game(policies=policies, hand=('policy', 'stored', 'spell')); play(g, 'policy'); play(g, 'stored')
        self.assertEqual([p.card_id for p in g.state.play_history], ['policy', 'stored'])
        self.assertEqual(g.state.cast_history[-1].branch_id, 'both')
        self.assertEqual(g.state.players[1].choose_both_modifiers, [])
        self.check(g, policies=policies)
    def test_manual_and_triggered_powers_consume_independently_when_explicitly_qualified(self):
        policies = (AddChooseBothModifier(1, uses=2, kinds=(CardType.HERO_POWER,), origins=('power_manual', 'power_effect')),)
        g = game(policies=policies, hand=('policy', 'trigger')); play(g, 'policy')
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id, branch_id='both')); play(g, 'trigger')
        self.assertEqual(self.armor(g), 14)
        self.assertEqual([r.origin for r in g.state.choose_policy_receipts], ['power_manual', 'power_effect'])
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn, 1)
        self.check(g, policies=policies)
    def test_repeat_payloads_do_not_consume_again(self):
        policies = (AddChooseBothModifier(1, uses=2),)
        g = game(policies=policies, board=('repeat',)); play(g, 'policy'); play(g, 'spell', 'both')
        self.assertEqual(self.armor(g), 14)
        self.assertEqual(len(g.state.choose_policy_receipts), 1)
        self.assertEqual(g.state.players[1].choose_both_modifiers[0].uses_remaining, 1)
        self.assertEqual([c.branch_id for c in g.state.cast_history if c.card_id == 'spell'], ['both', 'both'])
        self.check(g, policies=policies)
    def test_waiting_paid_and_automatic_roots_restore_original_policy(self):
        cases = ((('policy', 'spell'), (AddChooseBothModifier(1, uses=2),), 'spell'),
                 (('policy', 'auto'), (AddChooseBothModifier(1, uses=2, kinds=(CardType.SPELL,), origins=('cast_effect',)),), 'auto'))
        for hand, policies, card in cases:
            with self.subTest(card=card):
                g = game('wait', policies, hand=hand); play(g, 'policy'); play(g, card, 'both' if card == 'spell' else None)
                self.assertEqual(g.state.players[1].choose_both_modifiers[0].uses_remaining, 1)
                self.assertIsNone(g.state.choose_policy_receipts[0].closed_action)
                self.check(g, 'wait', policies)
                self.assertEqual(self.choose_all(g), 1)
                self.assertEqual(g.state.players[1].choose_both_modifiers[0].uses_remaining, 1)
                self.check(g, 'wait', policies)
    def test_each_generated_profile_restores_policy_during_actual_wait(self):
        policies = (AddChooseBothModifier(1, uses=2, kinds=(CardType.MINION,), origins=('physical',)),)
        for profile in PROFILES:
            with self.subTest(profile=profile):
                g = game('wait', policies, profile, hand=('minion', 'policy', 'generate'))
                play(g, 'minion', 'left'); self.choose_all(g); play(g, 'policy'); play(g, 'generate')
                self.assertEqual(g.state.players[1].choose_both_modifiers[0].uses_remaining, 1)
                self.check(g, 'wait', policies, profile)
                self.assertEqual(self.choose_all(g), 1)
                self.check(g, 'wait', policies, profile)
    def test_countered_paid_root_keeps_one_consumption_without_payload(self):
        for card in ('spell', 'minion'):
            with self.subTest(card=card):
                g = game(hand=('policy', card), board=('counter',)); play(g, 'policy'); play(g, card, 'both')
                self.assertEqual(self.armor(g), 0)
                self.assertTrue(g.state.play_history[-1].countered)
                self.assertEqual(g.state.players[1].choose_both_modifiers, [])
                self.check(g)
    def test_failed_generated_install_still_owns_its_branch_attempt(self):
        policies = (AddChooseBothModifier(1, uses=1, kinds=(CardType.MINION,), origins=('physical',)),)
        g = game('full', policies, hand=('minion', 'policy', 'generate'))
        play(g, 'minion', 'left'); play(g, 'policy'); play(g, 'generate')
        self.assertEqual(g.state.players[1].choose_both_modifiers, [])
        self.assertIsNotNone(g.state.choose_policy_receipts[0].closed_action)
        self.assertEqual(self.armor(g), 2)
        self.check(g, 'full', policies)
    def test_exception_rolls_back_rng_payment_and_consumption(self):
        g = game('fail', hand=('policy', 'spell')); play(g, 'policy'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): play(g, 'spell', 'both')
        self.assertEqual(g.snapshot(), saved)
    def test_terminal_interrupt_preserves_consumption_and_original_receipt(self):
        g = game('terminal', hand=('policy', 'spell')); play(g, 'policy'); play(g, 'spell', 'both')
        self.assertEqual(g.state.status, 'finished')
        self.assertTrue(g.state.choose_policy_receipts[0].interrupted)
        self.assertEqual(g.state.players[1].choose_both_modifiers, [])
        self.check(g, 'terminal')
    def test_public_views_show_policy_but_no_source_id_or_original_proof(self):
        g = game('wait', hand=('policy', 'spell')); play(g, 'policy')
        for viewer in (1, 2):
            item = g.observe(viewer)['players'][0]['choose_both_modifiers'][0]
            self.assertEqual(set(item), {'kinds', 'origins', 'uses_remaining', 'expires_turn'})
            self.assertEqual(item['uses_remaining'], 1)
        play(g, 'spell', 'both')
        forbidden = {'choose_policy_receipts', 'modifier_ids', 'source_card_id', 'before_state', 'original_modifiers', 'original_board_json', 'rng_state'}
        def scan(value):
            if type(value) is dict:
                self.assertFalse(set(value) & forbidden)
                for child in value.values(): scan(child)
            elif type(value) is list:
                for child in value: scan(child)
        for viewer in (1, 2):
            scan(g.for_player(viewer).observe()); scan(g.for_player(viewer).events())
    def reject(self, saved, mode='wait', policies=None, profile=PROFILES[0]):
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as result:
            Game.from_snapshot(saved, registry(mode, policies, profile))
        self.assertNotIn('digest mismatch', str(result.exception))
    def test_rehashed_receipt_tampering_rejects_owner_root_branch_and_uses(self):
        policies = (AddChooseBothModifier(1, uses=2),)
        g = game('wait', policies, hand=('policy', 'spell')); play(g, 'policy'); play(g, 'spell', 'both')
        for field, value in (('root_id', 1), ('player_id', 2), ('branch_id', 'left'), ('modifier_ids', []), ('closed_action', g.state.action_number)):
            with self.subTest(field=field):
                saved = g.snapshot(); saved['state']['choose_policy_receipts'][0][field] = value
                self.reject(saved, policies=policies)
        saved = g.snapshot(); saved['state']['players']['1']['choose_both_modifiers'][0]['uses_remaining'] = 2
        self.reject(saved, policies=policies)
    def test_waiting_queue_cannot_drop_or_duplicate_policy_completion(self):
        g = game('wait', hand=('policy', 'spell')); play(g, 'policy'); play(g, 'spell', 'both')
        for duplicate in (False, True):
            saved = g.snapshot()
            work = saved['resolution_frame']['fields']['continuation']['tuple']
            index = next(i for i, row in enumerate(work) if row.get('type', '').endswith('FinishChoosePolicy'))
            if duplicate: work.append(deepcopy(work[index]))
            else: del work[index]
            self.reject(saved)
    def test_invalid_policy_declarations_and_expired_grants_fail_explicitly(self):
        for kwargs in ({'uses': 0}, {'uses': True}, {'kinds': ()}, {'origins': ('unknown',)},
                       {'origins': ('power_manual',)}, {'kinds': (CardType.WEAPON,)}, {'origins': ('hand', 'hand')}, {'player_id': 3}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): AddChooseBothModifier(**({'player_id': 1} | kwargs))
        policies = (AddChooseBothModifier(1, expires_turn=1),)
        g = game(policies=policies, hand=('policy',)); g.apply(EndTurn(1)); g.apply(EndTurn(2)); saved = g.snapshot()
        with self.assertRaises(ResolutionError): play(g, 'policy')
        self.assertEqual(g.snapshot(), saved)
    def test_previous_schema_and_host_labels_are_rejected(self):
        g = game(); saved = g.snapshot()
        self.assertEqual((saved['schema_version'], g.ruleset.id, saved['mechanics_version']['version']),
                         (266, 'prototype-v302', CORE_EFFECTS_VERSION))
        self.assertEqual(g.observe(1)['version'], 'player-view-v85')
        saved['schema_version'] = 139; self.reject(saved, mode='normal')
        saved = g.snapshot(); saved['ruleset']['id'] = 'prototype-v144'; self.reject(saved, mode='normal')
        saved = g.snapshot(); saved['mechanics_version']['version'] = 'core-effects-v144'; self.reject(saved, mode='normal')
    def test_rewind_retry_reaccepts_from_restored_policy_without_double_consumption(self):
        policies = (AddChooseBothModifier(1, uses=2),)
        g = game(policies=policies, hand=('policy', 'rewind_spell')); play(g, 'policy'); play(g, 'rewind_spell', 'both')
        self.assertEqual(g.state.players[1].choose_both_modifiers[0].uses_remaining, 1)
        self.check(g, policies=policies)
        choice = g.state.pending_choice; g.apply(SelectChoice(1, choice.id, ('retry',)))
        self.assertEqual(g.state.players[1].choose_both_modifiers[0].uses_remaining, 1)
        self.assertEqual((self.armor(g), len(g.state.choose_policy_receipts)), (7, 1))
        self.check(g, policies=policies)
    def test_retained_outcomes_keep_one_policy_use_for_all_results(self):
        policies = (AddChooseBothModifier(1, uses=2),)
        g = game(policies=policies, hand=('policy', 'rewind_spell'), board=('retainer',))
        play(g, 'policy'); play(g, 'rewind_spell', 'both')
        self.assertEqual((self.armor(g), len(g.state.choose_policy_receipts)), (14, 1))
        self.assertEqual(g.state.players[1].choose_both_modifiers[0].uses_remaining, 1)
        self.assertIsNone(g.state.pending_choice)
        self.check(g, policies=policies)
    def test_policy_created_by_first_body_affects_new_root_but_not_existing_repeat(self):
        g = game('grant_during_body', policies=(), hand=('spell', 'minion'), board=('repeat',))
        play(g, 'spell', 'left')
        self.assertEqual(self.armor(g), 4)
        self.assertEqual(len(g.state.players[1].choose_both_modifiers), 2)
        self.assertEqual(g.state.choose_policy_receipts, [])
        play(g, 'minion', 'both')
        self.assertEqual(g.state.choose_policy_receipts[0].modifier_ids,
                         tuple(m.id for m in g.state.choose_policy_receipts[0].original_modifiers))
        # The newly accepted minion's own combined body grants a new policy.
        self.assertEqual(len(g.state.players[1].choose_both_modifiers), 1)
        self.check(g, 'grant_during_body', policies=())
    def test_commit_and_completion_reactions_wait_after_original_consumption(self):
        for mode in ('commit_wait', 'after_wait'):
            with self.subTest(mode=mode):
                g = game(mode, hand=('policy', 'spell'), board=('watch',)); play(g, 'policy'); play(g, 'spell', 'both')
                self.assertEqual(g.state.players[1].choose_both_modifiers, [])
                self.assertIsNone(g.state.choose_policy_receipts[0].closed_action)
                self.check(g, mode)
                self.choose_all(g); self.assertEqual(self.armor(g), 7); self.check(g, mode)
    def test_removal_of_policy_before_next_root_restores_ordinary_branches(self):
        g = game('remove', hand=('policy', 'mutate', 'spell'), board=('plain',)); play(g, 'policy'); play(g, 'mutate')
        play(g, 'spell', 'left')
        self.assertEqual((self.armor(g), g.state.choose_policy_receipts), (2, []))
        self.check(g, 'remove')
    def test_nested_automatic_roots_consume_separately_and_close_inner_first(self):
        policies = (AddChooseBothModifier(1, uses=2, kinds=(CardType.SPELL,), origins=('cast_effect',)),)
        g = game('nested_wait', policies, hand=('policy', 'auto')); play(g, 'policy'); play(g, 'auto')
        self.assertEqual(g.state.players[1].choose_both_modifiers, [])
        self.assertEqual(len(g.state.choose_policy_receipts), 2)
        self.check(g, 'nested_wait', policies)
        self.assertEqual(self.choose_all(g), 2)
        self.assertEqual(self.armor(g), 14)
        self.assertLessEqual(g.state.choose_policy_receipts[1].closed_action, g.state.choose_policy_receipts[0].closed_action)
        self.check(g, 'nested_wait', policies)
    def test_policy_completion_cannot_precede_retained_root_work_or_hide_in_choice(self):
        g = game('wait', hand=('policy', 'spell')); play(g, 'policy'); play(g, 'spell', 'both')
        saved = g.snapshot(); work = saved['resolution_frame']['fields']['continuation']['tuple']
        index = next(i for i, row in enumerate(work) if row.get('type', '').endswith('FinishChoosePolicy'))
        work.insert(0, work.pop(index)); self.reject(saved)
        saved = g.snapshot(); work = saved['resolution_frame']['fields']['continuation']['tuple']
        control = next(row for row in work if row.get('type', '').endswith('FinishChoosePolicy'))
        saved['resolution_frame']['fields']['options']['tuple'][0]['fields']['effects']['tuple'].append(deepcopy(control))
        self.reject(saved)
    def test_expiry_reaction_new_same_turn_policy_is_settled_before_turn_advances(self):
        policies = (AddChooseBothModifier(1, expires_turn=1),)
        g = game(policies=policies, hand=('policy',), board=('expiry_watch',)); play(g, 'policy'); g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].choose_both_modifiers, [])
        self.assertEqual(sum(e.kind == 'choose_both_modifier_expired' for e in g.events), 2)
        self.assertEqual((g.state.turn, self.armor(g)), (2, 1))
        self.check(g, policies=policies)
