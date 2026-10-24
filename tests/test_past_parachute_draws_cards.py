"""Physical Parachutes share ordinary shuffle, draw/CAST and charged summon paths."""
from functools import lru_cache
import json
import unittest
from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.past_parachute_draws_cards import (PATCHES, PARACHUTE, PIRATE, load_batch,
    register_past_parachute_draws_cards)
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, Keyword,
    PlayerSetup, Registry, Scenario, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy, Draw, InvokeBehavior, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BattlecryRepeatSpec, TargetSpec
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from tools import card_batch as batch

P = 'k497.'
HERO, POWER, A, WATCH, DOUBLE = (P+x for x in ('hero', 'power', 'plain', 'watch', 'double'))


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = Registry(P+mode)
    register_past_parachute_draws_cards(r)
    r.register_behavior(P+'draw', lambda c: (Draw(c.player_id, source_id=c.source_id),))
    r.register_card(CardDefinition(HERO, 'Hero', CardType.HERO, health=30, initial_hero_power=POWER))
    r.register_card(CardDefinition(POWER, 'Draw power', CardType.HERO_POWER, on_use=P+'draw'))
    r.register_card(CardDefinition(A, 'Plain', CardType.MINION, attack=1, health=8))
    r.register_card(CardDefinition(DOUBLE, 'Repeat', CardType.MINION, health=8,
        battlecry_repeats=(BattlecryRepeatSpec(2),)))
    r.register_card(CardDefinition(P+'draw', 'Draw', CardType.SPELL, on_play=P+'draw'))
    def explode(c):
        raise ResolutionError('k497 deliberate reaction failure')
    r.register_behavior(P+'explode', explode)
    scripts = {
        'two': lambda c: (Draw(c.player_id, 2, c.source_id),),
        'generate': lambda c: (AddToHand(c.player_id, PARACHUTE, c.source_id),),
        'auto': lambda c: (CastSpell(c.player_id, PARACHUTE, c.source_id),),
        'summon': lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(PATCHES),), SummonCause.capture(c)),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
    }
    for name, body in scripts.items():
        r.register_behavior(P+name, body)
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)) if name == 'kill' else None))
    def observe(c):
        event = c.event
        if event.kind == 'card_added_to_deck':
            source = c.state.entities.get(event.source_id)
            relevant = source is not None and source.card_id == PATCHES
            prefix = 'shuffle'
        elif event.kind == 'card_drawn':
            target = c.state.entities.get(event.target_id)
            relevant = target is not None and target.card_id == PARACHUTE
            prefix = 'draw'
        else:
            target = c.state.entities.get(event.target_id)
            relevant = target is not None and target.card_id == PIRATE
            prefix = 'summon'
        if not relevant:
            return ()
        if prefix == 'shuffle':
            # One representative publication tests this shared batch window;
            # all six physical insertions are still asserted below.
            first = min(i for i in c.state.players[event.player_id].deck
                if c.state.entities[i].card_id == PARACHUTE)
            if event.target_id != first:
                return ()
        if mode == prefix+'_fail':
            return (InvokeBehavior(P+'explode', c.source_id, c.player_id),)
        if mode != prefix+'_wait':
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Continue', ()),
            ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'explode', c.source_id, c.player_id),)),
        ), source_id=c.source_id),)
    r.register_behavior(P+'observe', observe)
    r.register_card(CardDefinition(WATCH, 'Observer', CardType.MINION, health=8, triggers=tuple(
        TriggerSpec(event, P+'observe') for event in ('card_added_to_deck', 'card_drawn', 'minion_summoned'))))
    r.validate()
    return r


class PastParachuteDrawTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), *, board=(), deck=(A,)*8, enemy_hand=(), mode='normal', power=False):
        self.mode = mode
        return Game.from_scenario(Scenario((PlayerSetup(HERO, hand=tuple(hand), board=tuple(board),
            deck=tuple(deck), mana=10, max_mana=10, hero_power_card_id=POWER if power else None), PlayerSetup(HERO, hand=tuple(enemy_hand),
            deck=(A,)*8, mana=10, max_mana=10)), seed=497), fixture(mode))

    def cards(self, g, cid, zone='deck', player=1):
        return [g.state.entities[i] for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid]

    def finish(self, g):
        while g.state.pending_choice is not None:
            self.choose(g)

    def test_three_complete_original_rows_six_full_primary_faces_and_real_tribes(self):
        d = load_batch(); self.assertEqual(len(d['dependencies']), 3); self.assertEqual(len(d['official_observations']), 6)
        rows = {x['record']['id']:x['record'] for x in d['dependencies']}
        for o in d['official_observations']:
            self.assertEqual(batch.sha(o['response_file']), o['response_sha256'])
            batch.check_face(rows[o['card_id']], o['face'], o['locale'])
        self.assertEqual(fixture().card(PATCHES).metadata.tribes, ('demon', 'pirate'))
        self.assertEqual(fixture().card(PIRATE).metadata.tribes, ('pirate',))
        self.assertNotIn(Keyword.CHARGE, fixture().card(PATCHES).keywords)
        self.assertEqual(fixture().card(PARACHUTE).attack, 0)

    def test_actual_constructed_registration_adds_all_three_complete_definitions(self):
        from hs_sim.cards import build_registry
        r = batch.registration_prefix(build_registry,
            'hs_sim.cards.past_parachute_draws_cards.register_past_parachute_draws_cards',
            register_past_parachute_draws_cards, after=True)
        self.assertEqual(len(r.cards), 2700)
        for cid in (PATCHES, PARACHUTE, PIRATE): self.assertEqual(r.card(cid), fixture().card(cid))

    def test_paid_battlecry_shuffles_six_distinct_physical_cards_in_one_semantic_operation(self):
        g = self.game((PATCHES,)); source = self.play(g, PATCHES); tokens = self.cards(g, PARACHUTE)
        self.assertEqual(len(tokens), 6); self.assertEqual(len({e.id for e in tokens}), 6)
        self.assertEqual(len(g.state.players[1].deck), 14); self.assertEqual(g.state.players[1].mana, 9)
        row, = g.state.deck_shuffle_history
        self.assertEqual((row.actor_id, row.player_id, row.declared_count, row.source.entity_id), (1, 1, 6, source))
        self.assertFalse(g.state.cast_history); self.assertFalse(g.state.draw_history); self.portable(g)

    def test_repeated_actual_battlecry_makes_two_independent_six_card_operations(self):
        g = self.game((PATCHES,), board=(DOUBLE,)); self.play(g, PATCHES)
        self.assertEqual(len(self.cards(g, PARACHUTE)), 12)
        self.assertEqual([x.declared_count for x in g.state.deck_shuffle_history], [6, 6])

    def test_ordinary_effect_summon_does_not_run_battlecry(self):
        g = self.game((P+'summon',)); self.play(g, P+'summon')
        self.assertEqual(len(self.cards(g, PATCHES, 'board')), 1)
        self.assertFalse(self.cards(g, PARACHUTE)); self.assertFalse(g.state.deck_shuffle_history)

    def test_real_other_seat_is_the_recipient_and_semantic_actor(self):
        g = self.game(enemy_hand=(PATCHES,)); g.apply(EndTurn(1)); source = self.play(g, PATCHES, player=2)
        self.assertEqual(len(self.cards(g, PARACHUTE, player=2)), 6); self.assertFalse(self.cards(g, PARACHUTE))
        row, = g.state.deck_shuffle_history
        self.assertEqual((row.actor_id, row.player_id, row.source.entity_id), (2, 2, source))

    def test_physical_draw_casts_original_spell_then_draws_replacement_without_hand_play(self):
        g = self.game((P+'draw',), deck=(PARACHUTE, A)); original = g.state.players[1].deck[0]
        self.play(g, P+'draw')
        self.assertEqual(len(self.cards(g, PIRATE, 'board')), 1); self.assertEqual(len(self.cards(g, A, 'hand')), 1)
        token = next(c for c in g.state.cast_history if c.card_id == PARACHUTE)
        self.assertEqual((token.source_id, token.origin, token.from_zone), (original, 'draw', Zone.DECK))
        self.assertEqual([d.outcome for d in g.state.draw_history], ['cast', 'hand'])
        self.assertEqual(len(g.state.play_history), 1); self.assertEqual(g.state.players[1].mana, 10); self.portable(g)

    def test_consecutive_parachutes_follow_one_replacement_chain(self):
        g = self.game((P+'draw',), deck=(PARACHUTE, PARACHUTE, A)); self.play(g, P+'draw')
        self.assertEqual(len(self.cards(g, PIRATE, 'board')), 2)
        self.assertEqual([d.outcome for d in g.state.draw_history], ['cast', 'cast', 'hand'])
        self.assertTrue(all(d.completed for d in g.state.draw_history)); self.assertEqual(len(self.cards(g, A, 'hand')), 1)

    def test_printed_charge_can_attack_enemy_hero_in_the_same_turn(self):
        g = self.game((P+'draw',), deck=(PARACHUTE, A)); self.play(g, P+'draw')
        pirate, = self.cards(g, PIRATE, 'board'); enemy = g.state.players[2].hero_id
        self.assertIn(Keyword.CHARGE, pirate.keywords); g.apply(Attack(1, pirate.id, enemy))
        self.assertEqual(g.state.entities[enemy].health, 29)

    def test_full_board_still_completes_cast_and_replacement_without_fake_pirate(self):
        g = self.game((P+'draw',), board=(A,)*7, deck=(PARACHUTE, A)); self.play(g, P+'draw')
        self.assertFalse(self.cards(g, PIRATE, 'board')); self.assertEqual(len(self.cards(g, A, 'hand')), 1)
        self.assertEqual([d.outcome for d in g.state.draw_history], ['cast', 'hand'])

    def test_full_hand_burns_parachute_without_cast_or_replacement(self):
        g = self.game((A,)*10, deck=(PARACHUTE, A), power=True)
        power = next(e.id for e in g.state.entities.values()
            if e.card_id == POWER and e.controller == 1 and e.zone == Zone.HERO_POWER)
        g.apply(UseHeroPower(1, power))
        self.assertEqual([d.outcome for d in g.state.draw_history], ['burned'])
        self.assertFalse(g.state.cast_history); self.assertFalse(self.cards(g, PIRATE, 'board'))
        self.assertEqual(len(g.state.players[1].deck), 1)

    def test_manual_parachute_play_summons_once_without_draw_or_replacement(self):
        g = self.game((PARACHUTE,)); self.play(g, PARACHUTE)
        self.assertEqual(len(self.cards(g, PIRATE, 'board')), 1); self.assertFalse(g.state.draw_history)
        self.assertEqual(g.state.players[1].mana, 9); self.assertEqual(len(g.state.players[1].deck), 8)
        self.assertEqual(g.state.cast_history[-1].origin, 'hand')

    def test_generated_hand_card_waits_for_actual_play_instead_of_casting(self):
        g = self.game((P+'generate',)); self.play(g, P+'generate')
        self.assertEqual(len(self.cards(g, PARACHUTE, 'hand')), 1)
        self.assertFalse(self.cards(g, PIRATE, 'board')); self.assertFalse(g.state.draw_history)

    def test_automatic_cast_uses_ordinary_spell_cause_without_replacement(self):
        g = self.game((P+'auto',)); self.play(g, P+'auto')
        self.assertEqual(len(self.cards(g, PIRATE, 'board')), 1); self.assertFalse(g.state.draw_history)
        self.assertEqual([c.origin for c in g.state.cast_history], ['hand', 'effect'])
        self.assertEqual(len(g.state.players[1].deck), 8)

    def test_printed_one_one_is_independent_of_shuffle_source_survival(self):
        g = self.game((PATCHES, P+'kill')); source = self.play(g, PATCHES); self.play(g, P+'kill', source)
        self.assertEqual(len(self.cards(g, PARACHUTE)), 6)
        self.assertTrue(all((e.card_id, e.kind) == (PARACHUTE, CardType.SPELL) for e in self.cards(g, PARACHUTE)))

    def test_shuffle_wait_preserves_all_original_insertions_and_rng(self):
        g = self.game((PATCHES,), board=(WATCH,), mode='shuffle_wait'); self.play(g, PATCHES)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(len(self.cards(g, PARACHUTE)), 6)
        restored = self.portable(g); self.finish(g); self.finish(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(len(g.state.deck_shuffle_history), 1)

    def test_draw_notification_wait_restores_original_physical_cast_and_replacement(self):
        g = self.game((P+'draw',), board=(WATCH,), deck=(PARACHUTE, A), mode='draw_wait')
        self.play(g, P+'draw'); self.assertIsNotNone(g.state.pending_choice); restored = self.portable(g)
        self.finish(g); self.finish(restored); self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(len(self.cards(g, PIRATE, 'board')), 1)

    def test_summon_wait_keeps_remaining_draw_chain_and_same_original_spell(self):
        g = self.game((P+'draw',), board=(WATCH,), deck=(PARACHUTE, A), mode='summon_wait')
        self.play(g, P+'draw'); self.assertIsNotNone(g.state.pending_choice); self.portable(g)
        self.finish(g); self.assertEqual([d.outcome for d in g.state.draw_history], ['cast', 'hand']); self.portable(g)

    def test_failing_shuffle_reaction_rolls_back_all_six_cards_and_rng(self):
        g = self.game((PATCHES,), board=(WATCH,), mode='shuffle_fail'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, PATCHES)
        self.assertEqual(g.snapshot(), before)

    def test_failing_summon_reaction_rolls_back_actual_draw_cast_and_deck(self):
        g = self.game((P+'draw',), board=(WATCH,), deck=(PARACHUTE, A), mode='summon_fail'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, P+'draw')
        self.assertEqual(g.snapshot(), before)

    def test_failed_wait_choice_keeps_accepted_shuffle_for_a_valid_resume(self):
        g = self.game((PATCHES,), board=(WATCH,), mode='shuffle_wait'); self.play(g, PATCHES); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before); self.finish(g); self.portable(g)

    def test_no_full_state_or_hidden_deck_order_leaks_into_player_views(self):
        g = self.game((PATCHES,)); self.play(g, PATCHES)
        for player in (1, 2):
            dto = json.dumps(g.for_player(player).observe())
            for name in ('rng_state', 'deck_shuffle_history', 'declared_count', 'next_entity_id'):
                self.assertNotIn('"'+name+'"', dto)


if __name__ == '__main__':
    unittest.main()
