import json
import unittest
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache

from hs_sim.cards import build_registry
from hs_sim.cards.hand_rank_death_neighbor_cards import BLASPHEMY, GUARD, load_batch
from hs_sim.engine import (CardDefinition, CardType, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddCostModifier, ChoiceOption, Damage, DamageBatch,
    Destroy, Draw, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform, TriggerDeathrattles)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.errors import IllegalAction
from hs_sim.engine.hand_cost_rank import HandCostRankProfile
from hs_sim.engine.model import BoardPresenceReference, CardClass, CardMetadata, CostSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell, CastStoredSpell
from hs_sim.engine.zones import CardReference, ModifyStoredCost

COIN, YETI, FLY = 'GAME_005', 'CORE_CS2_182', 'CORE_UNG_809'
P = 'fixture.hand_rank_neighbors.'
KILL, CLEAR, DISCOUNT, REDUCE, HIGH, AUTO, STORED, TRIGGER, SILENCE, SD, DORMANT, LOCATION, WATCH, MORPHER = (
    P+s for s in ('kill', 'clear', 'discount', 'reduce', 'high', 'auto', 'stored', 'trigger', 'silence',
                 'spell_damage', 'dormant', 'location', 'watch', 'morpher'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r = build_registry()
    target = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
    held = TargetSpec(zones=(Zone.HAND,), kinds=(CardType.SPELL,), relation='friendly')
    bodies = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        CLEAR: lambda c: (DamageBatch(tuple(Damage(i, 3, c.source_id) for i in c.state.players[c.player_id].board
            if c.state.entities[i].kind == CardType.MINION)),),
        DISCOUNT: lambda c: (AddCostModifier(c.player_id, CostSpec(set_to=1, card_types=(CardType.SPELL,)),
            uses_remaining=1, source_id=c.source_id),),
        REDUCE: lambda c: (ModifyStoredCost(CardReference.capture(c.state.entities[c.target_id]), CostSpec(delta=-3), c.source_id),),
        HIGH: lambda c: (),
        AUTO: lambda c: (CastSpell(c.player_id, BLASPHEMY, c.source_id, choices='player'),),
        STORED: lambda c: (CastStoredSpell(CardReference.capture(c.state.entities[c.target_id]), c.player_id, c.source_id, choices='player'),),
        TRIGGER: lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        SILENCE: lambda c: (Silence(c.target_id),),
        LOCATION: lambda c: (),
        MORPHER: lambda c: (Transform(c.state.players[c.player_id].board[0], FLY),),
        P+'resummon': lambda c: (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, position=2),),
    }
    for cid, body in bodies.items(): r.register_behavior(cid, body)
    for cid in (KILL, CLEAR, DISCOUNT, REDUCE, HIGH, AUTO, STORED, TRIGGER, SILENCE):
        r.register_card(CardDefinition(cid, 'Explicit ordinary preparation', CardType.SPELL,
            cost=8 if cid == HIGH else 0, metadata=META, on_play=cid,
            targeting=held if cid in (REDUCE, STORED) else target if cid in (KILL, TRIGGER, SILENCE) else None))
    r.register_card(CardDefinition(SD, 'Spell Damage observer', CardType.MINION, health=8, spell_damage=1, metadata=META))
    r.register_card(CardDefinition(DORMANT, 'Inactive neighboring residence', CardType.MINION,
        attack=3, health=3, dormant_turns=2, metadata=META))
    r.register_card(CardDefinition(LOCATION, 'Ordinary intervening location', CardType.LOCATION,
        durability=2, on_use=LOCATION, metadata=META))
    r.register_card(CardDefinition(MORPHER, 'Earlier death reaction', CardType.MINION,
        attack=1, health=1, deathrattle=MORPHER, metadata=META))
    if mode in ('wave_wait', 'death_wait'):
        def observe(c):
            if mode == 'wave_wait':
                if (c.event.source_id is None or c.state.entities[c.event.source_id].card_id != BLASPHEMY or
                        c.event.target_id != c.state.players[2].hero_id or c.state.entities[c.event.target_id].health != 28): return ()
                options = (ChoiceOption('continue', 'Continue'), ChoiceOption('draw', 'Draw a later high-cost card', (Draw(c.player_id, source_id=c.source_id),)))
            else:
                if c.event.source_id is None or c.state.entities[c.event.source_id].card_id != GUARD: return ()
                death = c.state.death_history[dict(c.event.data)['death_id']-1]
                right = death.adjacent_minions[-1].entity_id
                options = (ChoiceOption('continue', 'Continue'), ChoiceOption('remove', 'Remove the original right neighbor', (Destroy(right, c.source_id),)),
                    ChoiceOption('reenter', 'Return and summon the same physical card', (ReturnToHand(right), InvokeBehavior(P+'resummon', c.source_id, c.player_id, right))))
            return (RequestChoice(c.player_id, options, c.source_id),)
        r.register_behavior(WATCH, observe)
        r.register_card(CardDefinition(WATCH, 'Actual native boundary observer', CardType.MINION,
            health=20, metadata=META, triggers=(TriggerSpec('damage_dealt' if mode == 'wave_wait' else 'minion_died', WATCH),)))
    return r


class HandRankDeathNeighborTests(unittest.TestCase):
    readers = {}

    def game(self, hand=(), board=(), enemy=(YETI,), mode='normal'):
        if mode in ('wave_wait', 'death_wait'): board = (WATCH,)+board
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', hand=hand,
            board=board, deck=(HIGH,)+(COIN,)*9, mana=10, max_mana=10),
            PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', board=enemy, deck=(COIN,)*10,
                mana=10, max_mana=10)), seed=0), fixture(mode))

    def play(self, g, cid, target=None, position=None):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid, target_id=target, position=position)); return eid

    def proceed(self, g, option='continue'):
        c = g.state.pending_choice; g.apply(SelectChoice(c.player_id, c.id, (option,)))

    def portable(self, g, mode='normal'):
        if mode not in self.readers: self.readers[mode] = fixture.__wrapped__(mode)
        r = self.readers[mode]; saved = g.snapshot()
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)), r).snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        for p in (1, 2):
            view = json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in ('hand_cost_rank', 'adjacent_minions', '_death_neighbors', 'rng_state', 'play_history'):
                self.assertNotIn('"'+key+'"', view)

    def reject(self, g, edit):
        saved = deepcopy(g.snapshot()); edit(saved)
        payload = g._hash_payload(); payload['state'] = saved['state']; saved['state_hash'] = canonical_hash(payload)
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, fixture())

    def test_real_highest_hand_quote_including_ties_is_frozen_before_payment(self):
        for other, damage in (((), 4), ((YETI,), 4), ((HIGH,), 2)):
            with self.subTest(other=other):
                g = self.game((BLASPHEMY,)+other); self.play(g, BLASPHEMY)
                self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30-damage)
                rank = g.state.play_history[0].hand_cost_rank
                self.assertEqual(rank.highest, damage == 4); self.assertEqual(len(rank.quotes), 1+len(other))
                self.assertEqual(g.state.cast_history[0].hand_cost_rank, rank)

    def test_guard_natural_death_preserves_both_original_neighbor_residences(self):
        g = self.game((KILL,), (YETI, GUARD, YETI, YETI)); board = tuple(g.state.players[1].board)
        self.play(g, KILL, board[1]); record = next(d for d in g.state.death_history if d.card_id == GUARD)
        self.assertEqual(tuple(x.entity_id for x in record.adjacent_minions), (board[0], board[2]))
        self.assertEqual([g.state.entities[i].attack for i in (board[0], board[2], board[3])], [6, 6, 4])
        self.portable(g)

    def test_complete_two_roots_and_four_primary_faces(self):
        data = load_batch(); self.assertEqual(len(data['cards']), 2); self.assertEqual(len(data['official_observations']), 4)
        r = fixture(); self.assertEqual(r.card(GUARD).battlecry, r.card(GUARD).deathrattle)
        self.assertEqual((r.card(BLASPHEMY).cost, r.card(GUARD).cost), (4, 5))
        self.assertEqual(set(r.hand_cost_rank_profiles), {BLASPHEMY})

    def test_highest_uses_actual_local_cost_instead_of_printed_cost(self):
        g = self.game((REDUCE, BLASPHEMY, YETI)); source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == BLASPHEMY)
        self.play(g, REDUCE, source); self.play(g, BLASPHEMY)
        rank = g.state.play_history[-1].hand_cost_rank; self.assertEqual(rank.source_quote.amount, 1)
        self.assertFalse(rank.highest); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28)

    def test_one_use_external_cost_is_compared_before_its_consumption(self):
        g = self.game((DISCOUNT, BLASPHEMY, HIGH)); self.play(g, DISCOUNT); self.play(g, BLASPHEMY)
        rank = g.state.play_history[-1].hand_cost_rank
        self.assertEqual([q.amount for q in rank.quotes], [1, 1]); self.assertTrue(rank.highest)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 26)
        self.assertEqual(g.state.players[1].mana, 9); self.portable(g)

    def test_full_hand_quotes_include_actual_intrinsic_death_zero_price(self):
        g = self.game((KILL, BLASPHEMY, 'BE_877'), (FLY,))
        self.play(g, KILL, g.state.players[1].board[0]); self.play(g, BLASPHEMY)
        rank = g.state.play_history[-1].hand_cost_rank
        self.assertEqual([(q.quote_input.card_id, q.amount) for q in rank.quotes], [(BLASPHEMY, 4), ('BE_877', 0)])
        self.assertTrue(rank.highest); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 26)
        self.portable(g)

    def test_each_damage_wave_uses_current_enemies_and_ordinary_spell_damage(self):
        g = self.game((BLASPHEMY,), (SD,)); enemy = g.state.players[2].board[0]
        self.play(g, BLASPHEMY)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 24)
        self.assertEqual(g.state.entities[enemy].zone, Zone.GRAVEYARD)

    def test_later_draw_and_wait_restore_do_not_recompute_accepted_wave_count(self):
        g = self.game((BLASPHEMY,), mode='wave_wait'); self.play(g, BLASPHEMY)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28)
        self.portable(g, 'wave_wait'); saved = g.snapshot(); c = g.state.pending_choice
        with self.assertRaises(IllegalAction): g.apply(SelectChoice(c.player_id, c.id, ('bad',)))
        self.assertEqual(g.snapshot(), saved); self.proceed(g, 'draw')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 26)
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id, HIGH); self.portable(g, 'wave_wait')

    def test_automatic_stored_cast_captures_actual_hand_without_fabricated_play(self):
        g = self.game((STORED, BLASPHEMY, YETI)); source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == BLASPHEMY)
        self.play(g, STORED, source)
        self.assertEqual([p.card_id for p in g.state.play_history], [STORED])
        self.assertTrue(g.state.cast_history[-1].hand_cost_rank.highest)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 26); self.portable(g)

    def test_generated_outside_hand_uses_explicit_unheld_policy(self):
        g = self.game((AUTO, BLASPHEMY)); self.play(g, AUTO)
        rank = g.state.cast_history[-1].hand_cost_rank
        self.assertFalse(rank.source_held); self.assertFalse(rank.highest)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28); self.portable(g)

    def test_hand_rank_rejects_missing_foreign_reordered_and_inconsistent_original_facts(self):
        g = self.game((YETI, BLASPHEMY)); self.play(g, BLASPHEMY)
        rank = g.state.play_history[0].hand_cost_rank
        with self.assertRaises(ValueError): replace(rank, source_zone=Zone.GRAVEYARD)
        with self.assertRaises(ValueError): replace(rank, quotes=rank.quotes+rank.quotes[:1])
        with self.assertRaises(ValueError): replace(rank, turn=rank.turn+1)
        self.reject(g, lambda s: s['state']['play_history'][0].update(hand_cost_rank=None))
        def reverse(s):
            for key in ('play_history', 'cast_history'): s['state'][key][0]['hand_cost_rank']['quotes'].reverse()
        self.reject(g, reverse)

    def test_hand_rank_profile_is_unique_and_rejects_nonspell_sources(self):
        r = build_registry()
        with self.assertRaises(ValueError): r.register_hand_cost_rank_profile(HandCostRankProfile(BLASPHEMY))
        with self.assertRaises(ValueError): r.register_hand_cost_rank_profile(HandCostRankProfile(GUARD))
        with self.assertRaises(ValueError): HandCostRankProfile(BLASPHEMY, 'unknown')

    def test_guard_battlecry_uses_real_inserted_slot_and_excludes_itself(self):
        g = self.game((GUARD,), (YETI, YETI)); guard = self.play(g, GUARD, position=1)
        self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board], [6, 3, 6])
        self.assertEqual(g.state.entities[guard].health, 3)

    def test_guard_edge_battlecry_does_not_expand_to_further_minions(self):
        g = self.game((GUARD,), (YETI, YETI)); self.play(g, GUARD, position=0)
        self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board], [3, 6, 4])

    def test_guard_simultaneous_left_death_does_not_shift_buff_to_further_survivor(self):
        g = self.game((CLEAR,), (FLY, GUARD, YETI, YETI)); board = tuple(g.state.players[1].board)
        self.play(g, CLEAR)
        self.assertEqual([(g.state.entities[i].attack, g.state.entities[i].health) for i in board[2:]], [(6, 4), (4, 2)])
        self.assertEqual(len({d.batch for d in g.state.death_history}), 1); self.portable(g)

    def test_guard_location_or_dormant_neighbor_does_not_expose_further_minion(self):
        for intervening in (LOCATION, DORMANT):
            with self.subTest(intervening=intervening):
                g = self.game((KILL,), (YETI, intervening, GUARD, YETI)); board = tuple(g.state.players[1].board)
                self.play(g, KILL, board[2]); self.assertEqual(g.state.entities[board[0]].attack, 4)
                self.assertEqual(g.state.entities[board[3]].attack, 6)
                if intervening == DORMANT: self.assertEqual(g.state.entities[board[1]].attack, 3)

    def test_guard_triggered_live_deathrattle_uses_current_adjacent_residences(self):
        g = self.game((TRIGGER,), (YETI, GUARD, YETI)); board = tuple(g.state.players[1].board)
        self.play(g, TRIGGER, board[1]); self.assertEqual([g.state.entities[i].attack for i in board], [6, 3, 6])
        self.assertFalse(g.state.death_history); self.portable(g)

    def test_guard_earlier_death_transform_preserves_continuous_neighbor_identity(self):
        g = self.game((CLEAR,), (MORPHER, GUARD, YETI, YETI)); board = tuple(g.state.players[1].board)
        self.play(g, CLEAR)
        self.assertEqual((g.state.entities[board[2]].card_id, g.state.entities[board[2]].attack, g.state.entities[board[2]].health), (FLY, 3, 4))
        self.assertEqual(g.state.entities[board[3]].attack, 4)

    def test_guard_wait_restore_keeps_originals_and_does_not_replace_removed_neighbor(self):
        g = self.game((KILL,), (YETI, GUARD, YETI, YETI), mode='death_wait')
        board = tuple(g.state.players[1].board); self.play(g, KILL, board[2])
        self.assertIsNotNone(g.state.pending_choice); self.portable(g, 'death_wait'); self.proceed(g, 'remove')
        self.assertEqual(g.state.entities[board[1]].attack, 6)
        self.assertEqual(g.state.entities[board[3]].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[board[4]].attack, 4); self.portable(g, 'death_wait')

    def test_silence_removes_guard_deathrattle_but_keeps_original_death_facts(self):
        g = self.game((SILENCE, KILL), (YETI, GUARD, YETI)); board = tuple(g.state.players[1].board)
        self.play(g, SILENCE, board[1]); self.play(g, KILL, board[1])
        self.assertEqual([g.state.entities[i].attack for i in (board[0], board[2])], [4, 4])
        self.assertEqual(len(g.state.death_history[-1].adjacent_minions), 2)

    def test_guard_original_neighbor_leaving_and_reentering_is_not_buffed(self):
        g = self.game((KILL,), (YETI, GUARD, YETI, YETI), mode='death_wait')
        board = tuple(g.state.players[1].board); right = board[3]
        old_presence = g.state.entities[right].board_presence_id
        self.play(g, KILL, board[2]); self.proceed(g, 'reenter')
        self.assertEqual(g.state.entities[right].zone, Zone.BOARD)
        self.assertNotEqual(g.state.entities[right].board_presence_id, old_presence)
        self.assertEqual(g.state.entities[right].attack, 4)
        self.assertEqual(g.state.entities[board[1]].attack, 6)
        self.assertEqual(g.state.entities[board[4]].attack, 4); self.portable(g, 'death_wait')

    def test_original_death_neighbors_reject_self_duplicates_future_and_trimmed_receipts(self):
        g = self.game((KILL,), (YETI, GUARD, YETI)); board = tuple(g.state.players[1].board); self.play(g, KILL, board[1])
        record = g.state.death_history[-1]
        with self.assertRaises(ValueError): replace(record, adjacent_minions=(record.adjacent_minions[0],)*2)
        with self.assertRaises(ValueError): replace(record, adjacent_minions=(BoardPresenceReference(record.entity_id, 1),))
        self.reject(g, lambda s: s['state']['death_history'][-1].update(adjacent_minions=[]))
        self.reject(g, lambda s: s['state']['death_history'][-1]['adjacent_minions'][0].update(presence_id=g.state.next_order))


if __name__ == '__main__': unittest.main()
