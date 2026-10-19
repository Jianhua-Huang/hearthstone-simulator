"""Real private hand offers, original native memory and source-independent rewards."""
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.private_hand_inspection_cards import AUGUR, HOLMES, PROGRAM, COIN, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.effects import (ChoiceOption, ChangeControl, Destroy, GainArmor, InvokeBehavior,
    RequestChoice, ReturnToHand, Silence, Transform, CopyMinion)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.hand_inspection import InspectHandCards
from hs_sim.engine.model import DeathrattleMemory, HandInvestigation, NativeDeathrattleSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, CopyCard, DrawMatching, MoveCard
from hs_sim.engine.effects import Draw
from hs_sim.targets import canonical_digest

P = 'private.hand.test.'
A, B, C, X, Y = (P + x for x in ('a', 'b', 'c', 'name_a', 'name_b'))
MINION = P + 'minion'
KILL, QUIET, STEAL, BOUNCE, CHANGE, CHANGE_TARGET, CYCLE, COPY, FAIL_SELECT, WATCH = (
    P + x for x in ('kill', 'quiet', 'steal', 'bounce', 'change', 'change_target', 'cycle', 'copy', 'fail_select', 'watch'))


@lru_cache(maxsize=None)
def registry(role):
    assert role in ('writer', 'reader')
    r = build_registry()
    def source(c):
        return next(c.state.entities[i] for pid in (1, 2) for i in c.state.players[pid].board
            if c.state.entities[i].card_id in (AUGUR, HOLMES))
    def selected(c):
        e = source(c)
        ability = next(a for a in e.abilities if a.deathrattle_memory is not None)
        entry = c.state.hand_entries[ability.deathrattle_memory.hand_entry_ids[0] - 1]
        return c.state.entities[entry.entity_id]
    def fail(c):
        raise ValueError('Deliberate private selection failure')
    r.register_behavior(P + 'fail', fail)
    def cycle(c):
        e = selected(c)
        return (MoveCard(CardReference.capture(e), e.controller, Zone.DECK, position='top', source_id=c.source_id),
            Draw(e.controller, 1, c.source_id))
    scripts = {
        KILL: lambda c: (Destroy(source(c).id, c.source_id),),
        QUIET: lambda c: (Silence(source(c).id),),
        STEAL: lambda c: (ChangeControl(source(c).id, 2),),
        BOUNCE: lambda c: (ReturnToHand(source(c).id),),
        CHANGE: lambda c: (Transform(source(c).id, MINION),),
        CHANGE_TARGET: lambda c: (TransformStoredCard(CardReference.capture(selected(c)), C, source_id=c.source_id),),
        CYCLE: cycle,
        COPY: lambda c: (CopyMinion(source(c).id, c.player_id),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    for cid, name in ((A, A), (B, B), (C, C), (X, 'Same printed name'), (Y, 'Same printed name')):
        r.register_behavior(cid, lambda c: (GainArmor(c.player_id, 1),))
        r.register_card(CardDefinition(cid, name, CardType.SPELL, on_play=cid))
    r.register_card(CardDefinition(MINION, MINION, CardType.MINION, attack=1, health=2))
    r.register_behavior(FAIL_SELECT, lambda c: (InvokeBehavior(P + 'fail', c.source_id, c.player_id),)
        if c.event.player_id == 1 else ())
    r.register_card(CardDefinition(FAIL_SELECT, FAIL_SELECT, CardType.MINION, health=4,
        triggers=(TriggerSpec('choice_selected', FAIL_SELECT),)))
    r.register_behavior(WATCH, lambda c: (RequestChoice(1, (ChoiceOption('ok', 'Continue'),), c.source_id),)
        if c.event.player_id == 2 else ())
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=4,
        triggers=(TriggerSpec('card_discarded', WATCH),)))
    r.validate(); r.freeze()
    return r


class PrivateHandTests(unittest.TestCase):
    def game(self, hand=(AUGUR, KILL), *, enemy_hand=(A, B, C, X, Y), board=(), active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(A,) * 20, mana=10, max_mana=10,
                hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', hand=enemy_hand, deck=(B,) * 20, mana=10, max_mana=10,
                hero_power_card_id='HERO_08bp')), seed=259, active_player=active), registry('writer'))
    def play(self, g, cid=AUGUR):
        pid = g.state.active_player
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid, eid)); return eid
    def choose(self, g, cid=None):
        q = g.state.pending_choice
        option = next((o for o in q.options if o.card_id == cid), q.options[0])
        eid = option.entity_id
        g.apply(SelectChoice(q.player_id, q.id, (option.id,)))
        return eid
    def portable(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(snapshot, registry('reader'))
        self.assertEqual(other.snapshot(), snapshot)
        self.assertEqual(g.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(g), registry('reader')).snapshot(), snapshot)
        return other
    def count_coins(self, g, pid=1):
        return sum(g.state.entities[i].card_id == COIN for i in g.state.players[pid].hand)
    def program(self, g):
        return [e for e in g.state.players[1].player_effects if e.spec_id == PROGRAM]
    def rehash(self, snapshot):
        keys = ('ruleset', 'registry_fingerprint', 'mechanics_version', 'state', 'rng_state',
            'resolution_frame', 'rewind_session', 'match_setup', 'generation_context', 'information')
        snapshot['state_hash'] = canonical_digest({k: snapshot[k] for k in keys})

    def test_a00_full_two_roots_coin_dependency_and_three_nonexecutable_enchantments(self):
        d = load_batch()
        self.assertEqual(len(d['cards']), 2)
        self.assertEqual(len(d['official_observations']), 4)
        self.assertEqual(tuple(x['record']['id'] for x in d['evidence_only']), ('JAIL_303e', 'JAIL_851e', 'JAIL_851e1'))
        self.assertEqual(registry('writer').card(HOLMES).metadata.tribes, ('murloc',))

    def test_a01_three_and_four_offers_are_private_physical_choices_with_real_payment(self):
        for card, count in ((AUGUR, 3), (HOLMES, 4)):
            with self.subTest(card=card):
                g = self.game((card,)); self.play(g, card)
                self.assertEqual(g.state.players[1].mana, 6)
                q = g.state.pending_choice; self.assertEqual(len(q.options), count)
                self.assertEqual(len({o.id for o in q.options}), count)
                self.assertIsNone(g.for_player(2).observe()['observation']['pending_choice'].get('options'))
                own = g.for_player(1).observe()['observation']
                self.assertEqual(len(own['pending_choice']['options']), count)
                self.assertEqual(sum(x['card_id'] is not None for x in own['players'][1]['hand']), count)

    def test_a02_small_and_duplicate_hands_keep_every_physical_card_weight(self):
        for card in (AUGUR, HOLMES):
            g = self.game((card,), enemy_hand=(A, A)); self.play(g, card)
            q = g.state.pending_choice
            self.assertEqual(len(q.options), 2)
            self.assertEqual(len({o.id for o in q.options}), 2)
            self.assertEqual([o.card_id for o in q.options], [A, A])
            self.choose(g)

    def test_a03_empty_enemy_hand_is_playable_and_rng_neutral(self):
        for card in (AUGUR, HOLMES):
            g = self.game((card,), enemy_hand=()); rng = g._rng.getstate()
            self.play(g, card)
            self.assertEqual(g._rng.getstate(), rng)
            self.assertIsNone(g.state.pending_choice)
            self.assertFalse(self.program(g))

    def test_b00_augur_discards_the_original_selected_card_via_actual_discard_history(self):
        g = self.game(); self.play(g); selected = self.choose(g)
        self.assertFalse(g.state.discard_history)
        other = self.portable(g)
        for game in (g, other): self.play(game, KILL)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.entities[selected].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.discard_history), 1)
        self.assertEqual(g.state.discard_history[0].card.entity_id, selected)

    def test_b01_selected_hand_transform_keeps_the_original_acquisition_link(self):
        g = self.game((AUGUR, CHANGE_TARGET, KILL)); self.play(g); selected = self.choose(g)
        self.play(g, CHANGE_TARGET); self.play(g, KILL)
        self.assertEqual(g.state.discard_history[-1].card.card_id, C)
        self.assertEqual(g.state.discard_history[-1].card.entity_id, selected)

    def test_b02_selected_card_leaves_and_returns_as_a_new_entry_is_not_rebound(self):
        g = self.game((AUGUR, CYCLE, KILL)); self.play(g); selected = self.choose(g)
        self.play(g, CYCLE); self.play(g, KILL)
        self.assertIn(selected, g.state.players[2].hand)
        self.assertFalse(g.state.discard_history)

    def test_b03_silence_return_or_transform_removes_the_old_native_memory(self):
        for operation in (QUIET, BOUNCE, CHANGE):
            with self.subTest(operation=operation):
                g = self.game((AUGUR, operation)); source = self.play(g); selected = self.choose(g)
                self.play(g, operation)
                self.assertIn(selected, g.state.players[2].hand)
                self.assertFalse(any(a.deathrattle_memory and a.deathrattle_memory.hand_entry_ids
                    for a in g.state.entities[source].abilities))

    def test_b04_source_control_change_does_not_retarget_a_different_opponents_hand(self):
        g = self.game((AUGUR, STEAL, KILL)); self.play(g); selected = self.choose(g)
        self.play(g, STEAL); self.play(g, KILL)
        self.assertEqual(g.state.entities[selected].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.discard_history[-1].player_id, 2)

    def test_b05_real_repeated_battlecry_remembers_each_original_selection(self):
        g = self.game(board=('TIME_064',)); self.play(g)
        first = self.choose(g)
        self.assertIsNotNone(g.state.pending_choice)
        q = g.state.pending_choice
        option = next(o for o in q.options if o.entity_id != first)
        second = option.entity_id; g.apply(SelectChoice(q.player_id, q.id, (option.id,)))
        self.play(g, KILL)
        self.assertEqual({x.card.entity_id for x in g.state.discard_history}, {first, second})

    def test_b06_discard_reaction_wait_restores_the_original_accepted_deathrattle(self):
        g = self.game(board=(WATCH,)); self.play(g); self.choose(g); self.play(g, KILL)
        self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g)
        for game in (g, other):
            q = game.state.pending_choice; game.apply(SelectChoice(q.player_id, q.id, ('ok',)))
        self.assertEqual(g.snapshot(), other.snapshot())

    def test_c00_holmes_next_opponent_play_of_the_name_pays_once_and_survives_source_death(self):
        g = self.game((HOLMES, KILL), enemy_hand=(X, Y)); self.play(g, HOLMES)
        self.choose(g, X); self.play(g, KILL); self.assertEqual(len(self.program(g)), 1)
        other = self.portable(g)
        for game in (g, other):
            game.apply(EndTurn(1)); self.play(game, Y); self.play(game, X)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.count_coins(g), 3)
        self.assertFalse(self.program(g))

    def test_c01_own_turn_matching_name_does_not_reward_and_unmatched_next_turn_expires(self):
        g = self.game((HOLMES, Y), enemy_hand=(X, A)); self.play(g, HOLMES); self.choose(g, X)
        self.play(g, Y); self.assertEqual(self.count_coins(g), 0)
        g.apply(EndTurn(1)); self.play(g, A); g.apply(EndTurn(2))
        self.assertFalse(self.program(g)); self.assertEqual(self.count_coins(g), 0)
        g.apply(EndTurn(1)); self.play(g, X); self.assertEqual(self.count_coins(g), 0)

    def test_c02_selected_physical_card_is_not_required_for_a_same_name_copy(self):
        g = self.game((HOLMES,), enemy_hand=(X, Y)); self.play(g, HOLMES); self.choose(g, X)
        selected = next(i for i in g.state.players[2].hand if g.state.entities[i].card_id == X)
        g.apply(EndTurn(1)); self.play(g, Y)
        self.assertIn(selected, g.state.players[2].hand)
        self.assertEqual(self.count_coins(g), 3)

    def test_c03_silencing_or_transforming_holmes_does_not_cancel_the_independent_program(self):
        for operation in (QUIET, CHANGE, BOUNCE):
            with self.subTest(operation=operation):
                g = self.game((HOLMES, operation), enemy_hand=(X,)); self.play(g, HOLMES); self.choose(g)
                self.play(g, operation); g.apply(EndTurn(1)); self.play(g, X)
                self.assertEqual(self.count_coins(g), 3)

    def test_c04_reward_respects_actual_hand_capacity_and_burns_excess_coins(self):
        g = self.game((HOLMES,) + (A,) * 8, enemy_hand=(X,)); self.play(g, HOLMES); self.choose(g)
        g.apply(EndTurn(1)); self.play(g, X)
        self.assertEqual(self.count_coins(g), 2)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertTrue(any(e.kind == 'card_burned' and e.player_id == 1 for e in g.events))

    def test_c05_repeated_investigations_are_independent_and_each_rewards_three_coins(self):
        g = self.game((HOLMES,), enemy_hand=(X,), board=('TIME_064',)); self.play(g, HOLMES)
        self.choose(g); self.choose(g)
        self.assertEqual(len(self.program(g)), 2)
        g.apply(EndTurn(1)); self.play(g, X)
        self.assertEqual(self.count_coins(g), 6)
        self.assertFalse(self.program(g))

    def test_d00_pending_secret_choice_recovers_clones_replays_and_finishes_once(self):
        for card in (AUGUR, HOLMES):
            with self.subTest(card=card):
                g = self.game((card,)); self.play(g, card); other = self.portable(g)
                for game in (g, other): self.choose(game)
                self.assertEqual(g.snapshot(), other.snapshot())

    def test_d01_failed_selection_reaction_rolls_back_to_the_same_private_offer(self):
        g = self.game(board=(FAIL_SELECT,)); self.play(g); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'private selection failure'): self.choose(g)
        self.assertEqual(g.snapshot(), before)

    def test_d02_private_original_ids_and_investigated_name_do_not_enter_opponent_views(self):
        g = self.game((HOLMES,), enemy_hand=(X, Y)); self.play(g, HOLMES); self.choose(g, X)
        for pid in (1, 2):
            wire = json.dumps(g.for_player(pid).observe()) + json.dumps(g.player_events(pid))
            for key in ('"investigation"', '"hand_entry_id"', '"owner_turn_index"', '"hand_entry_ids"', '"context"'):
                self.assertNotIn(key, wire)

    def test_d03_original_hand_memory_and_investigation_tampering_rejects_after_rehash(self):
        g = self.game(); source = self.play(g); self.choose(g); snap = g.snapshot()
        abilities = snap['state']['entities'][str(source)]['abilities']
        next(a for a in abilities if a['deathrattle_memory'] is not None)['deathrattle_memory']['hand_entry_ids'] = [999999]
        self.rehash(snap)
        with self.assertRaisesRegex(ValueError, 'acquisition'):
            Game.from_snapshot(snap, registry('reader'))
        g = self.game((HOLMES,)); self.play(g, HOLMES); self.choose(g); snap = g.snapshot()
        snap['state']['players']['1']['player_effects'][0]['investigation']['opponent_id'] = 1
        self.rehash(snap)
        with self.assertRaisesRegex(ValueError, 'opponent'):
            Game.from_snapshot(snap, registry('reader'))

    def test_e00_strict_requests_memory_profiles_and_private_material_types(self):
        for args in ((1, 1, 3, 1, 'body'), (1, 2, True, 1, 'body'), (1, 2, 3, None, 'body')):
            with self.assertRaises(ValueError): InspectHandCards(*args)
        with self.assertRaises(ValueError): InspectHandCards(1, 2, 3, 1, 'body', '[]')
        with self.assertRaises(ValueError): HandInvestigation(A, 1, True, 1)
        with self.assertRaises(ValueError): DeathrattleMemory(NativeDeathrattleSpec('draw_link'), hand_entry_ids=(1,))

    def test_b07_current_copy_keeps_independent_native_memory_without_discarding_twice(self):
        g = self.game((AUGUR, COPY, KILL, KILL)); self.play(g); selected = self.choose(g)
        self.play(g, COPY)
        sources = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == AUGUR]
        self.assertEqual(len(sources), 2)
        memories = [next(a.deathrattle_memory for a in e.abilities if a.deathrattle_memory is not None) for e in sources]
        self.assertEqual(memories[0].hand_entry_ids, memories[1].hand_entry_ids)
        self.play(g, KILL); self.play(g, KILL)
        self.assertEqual(len(g.state.discard_history), 1)
        self.assertEqual(g.state.discard_history[0].card.entity_id, selected)


if __name__ == '__main__':
    unittest.main()
