"""Two real area quests through ordinary actions, capacities and reactions."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.fill_board_hand_quest_cards import BOARD, HAND, REWARDS, ROOTS, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard,
    PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, DestroyBatch,
    InvokeBehavior, RandomDamage, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_capacity import SetHandCapacity
from hs_sim.engine.model import (QUEST_FULL_BOARD_TURNS, QUEST_FULL_THEN_EMPTY_HAND,
    QuestStageSpec)
from hs_sim.engine.quests import RemoveQuest
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, DiscardCard, FillHandWithCard, MoveCard
from hs_sim.targets import canonical_digest

P = 'area_quest.test.'
ZERO, FILL, EMPTY, RESTART, SUMMON, OTHER, CLEAR, PARTIAL, THREE, SHRINK, MOVE, TRANSFER, TAKE, LOCATION, DORMANT = (
    P+x for x in ('zero', 'fill', 'empty', 'restart', 'summon', 'other', 'clear', 'partial',
                 'three', 'shrink', 'move', 'transfer', 'take', 'location', 'dormant'))
WAIT, REWARD_WAIT, EARLY_BOARD, EARLY_HAND = (P+x for x in ('wait', 'reward_wait', 'early_board', 'early_hand'))
MINION = 'CS2_182'


def discard(c):
    return tuple(DiscardCard(CardReference.capture(c.state.entities[i]), c.source_id)
                 for i in c.state.players[c.player_id].hand)


@lru_cache(maxsize=None)
def registry(role):
    assert role in ('writer', 'reader')
    r = build_registry(); meta = replace(r.card(MINION).metadata, deck_identity=None)
    def summon(c, owner):
        request = SummonByCard(owner, (SummonEntryMaterial(MINION),), SummonCause.capture(c))
        return (request,)*7
    def move_hand(c, owner, destination):
        return tuple(MoveCard(CardReference.capture(c.state.entities[i]), owner, destination,
            source_id=c.source_id) for i in c.state.players[c.player_id].hand)
    bodies = {
        ZERO: lambda c: (), FILL: lambda c: (FillHandWithCard(c.player_id, ZERO, c.source_id),),
        EMPTY: discard,
        RESTART: lambda c: (*discard(c), AddToHand(c.player_id, FILL, c.source_id), AddToHand(c.player_id, EMPTY, c.source_id)),
        SUMMON: lambda c: summon(c, c.player_id), OTHER: lambda c: summon(c, 3-c.player_id),
        CLEAR: lambda c: (DestroyBatch(tuple(c.state.players[c.player_id].board), c.source_id),),
        PARTIAL: lambda c: tuple(AddToHand(c.player_id, ZERO, c.source_id) for _ in range(8)),
        THREE: lambda c: tuple(AddToHand(c.player_id, ZERO, c.source_id) for _ in range(3)),
        SHRINK: lambda c: (SetHandCapacity(c.player_id, 2),),
        MOVE: lambda c: move_hand(c, c.player_id, Zone.DECK),
        TRANSFER: lambda c: move_hand(c, 3-c.player_id, Zone.HAND),
        TAKE: lambda c: tuple(MoveCard(CardReference.capture(c.state.entities[i]), c.player_id,
            Zone.HAND, source_id=c.source_id) for i in c.state.players[3-c.player_id].hand),
    }
    for name, body in bodies.items():
        r.register_behavior(name, body)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=meta))
    r.register_card(CardDefinition(LOCATION, LOCATION, CardType.LOCATION, durability=2, on_use=ZERO, metadata=meta))
    r.register_card(CardDefinition(DORMANT, DORMANT, CardType.MINION, health=2, dormant_turns=9, metadata=meta))
    def fail(c): raise ResolutionError('Area quest deliberate rollback')
    r.register_behavior(P+'fail', fail)
    for mode in (WAIT, REWARD_WAIT, EARLY_BOARD, EARLY_HAND):
        def watch(c, mode=mode):
            if mode == EARLY_BOARD:
                ids = tuple(c.state.players[c.player_id].board)
                return (DestroyBatch(ids, c.source_id),) if len(ids) == 7 else ()
            if mode == EARLY_HAND:
                return discard(c) if len(c.state.players[c.player_id].hand) == 10 else ()
            source = c.state.entities.get(c.event.source_id)
            if mode == WAIT:
                if (source is None or source.card_id != HAND or source.quest_progress is None
                        or source.quest_progress.value != 1): return ()
                extra = (ChoiceOption('empty', 'Empty hand', discard(c)),
                    ChoiceOption('remove', 'Remove quest and empty hand', (RemoveQuest(source.id), *discard(c))))
            else:
                target = c.state.entities.get(c.event.target_id)
                if target is None or target.card_id not in REWARDS: return ()
                extra = ()
            return (RequestChoice(c.player_id, (
                ChoiceOption('ok', 'Continue', ()),
                ChoiceOption('fail', 'Fail', (RandomDamage((c.state.players[2].hero_id,), 1, c.source_id),
                    InvokeBehavior(P+'fail', c.source_id, c.player_id))), *extra), c.source_id),)
        r.register_behavior(mode, watch)
        event = {WAIT: 'quest_progressed', REWARD_WAIT: 'card_added_to_hand',
                 EARLY_BOARD: 'minion_summoned', EARLY_HAND: 'card_created'}[mode]
        r.register_card(CardDefinition(mode, mode, CardType.MINION, health=3,
            triggers=(TriggerSpec(event, mode),), metadata=meta))
    r.validate(); r.freeze(); return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class FillAreaQuestTests(unittest.TestCase):
    def game(self, hand, *, board=(), other_hand=(), other_board=(), hand_cap=None, ruleset=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06', hand=hand, board=board, deck=(ZERO,)*14,
                mana=30, max_mana=10, temporary_mana=20, hand_cap=hand_cap),
            PlayerSetup('HERO_05', hand=other_hand, board=other_board, deck=(ZERO,)*14,
                mana=30, max_mana=10, temporary_mana=20)), seed=244239), registry('writer'), ruleset)
    def source(self, g, cid):
        return next(i for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id == cid)
    def play(self, g, cid): return g.apply(PlayCard(g.state.active_player, self.source(g, cid)))
    def quest(self, g, pid=1): return g.state.entities[g.state.players[pid].quests[0]]
    def progress(self, g, pid=1): return self.quest(g, pid).quest_progress.value
    def cycle(self, g):
        g.apply(EndTurn(g.state.active_player)); g.apply(EndTurn(g.state.active_player))
    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        return g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def reward_count(self, g, cid, pid=1):
        return sum(e.card_id == cid and e.controller == pid for e in g.state.entities.values())
    def portable(self, g):
        r = registry('reader' if g.registry is registry('writer') else 'writer')
        saved = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(saved, r)
        for candidate in (other, g.clone(), replay(build_replay(g), r)):
            self.assertEqual(candidate.snapshot(), saved)
        for pid in (1, 2):
            wire = json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for secret in ('resolution_frame', 'rng_state', 'completed_before', 'owner_turn:'):
                self.assertNotIn(secret, wire)
        return other

    def test_a00_five_complete_rows_eight_primary_faces_and_existing_reward_pins(self):
        from tools.card_batch import check_face
        d = load_batch(); rows=d['cards']+d['existing_dependencies']+d['evidence_only']
        self.assertEqual(len(rows), 5)
        by_dbf={x['record']['dbf_id']:x['record'] for x in rows}
        for item in d['official_observations']:
            check_face(by_dbf[item['face']['id']], item['face'], item['locale'])
        for row in d['existing_dependencies']:
            self.assertEqual(canonical_digest(asdict(registry('writer').card(row['record']['id']))), row['definition_sha256'])
        self.assertEqual([registry('writer').card(cid).quest.stages[0].goal for cid in ROOTS], [3, 2])

    def test_a01_state_subscriptions_are_finite_and_do_not_mix_named_events(self):
        for goal, events in ((2, ('state:unknown',)), (2, (QUEST_FULL_THEN_EMPTY_HAND, 'card_played')),
                             (3, (QUEST_FULL_THEN_EMPTY_HAND,))):
            with self.assertRaises(ValueError): QuestStageSpec(HAND, goal, events, 'progress', 'reward')
        QuestStageSpec(BOARD, 3, (QUEST_FULL_BOARD_TURNS,), 'progress', 'reward')

    def test_b00_full_board_at_activation_and_three_real_owner_intervals_reward_once(self):
        g=self.game((BOARD,), board=(MINION,)*7); self.play(g, BOARD)
        self.assertEqual(self.progress(g), 1); self.cycle(g); self.assertEqual(self.progress(g), 2)
        self.cycle(g); self.assertFalse(g.state.players[1].quests)
        self.assertEqual(self.reward_count(g, REWARDS[0]), 1); self.portable(g)

    def test_b01_repeated_fill_and_notifications_in_same_owner_turn_only_count_once(self):
        g=self.game((BOARD, SUMMON, CLEAR, SUMMON, ZERO)); self.play(g, BOARD)
        self.play(g, SUMMON); self.assertEqual(self.progress(g), 1)
        self.play(g, CLEAR); self.play(g, SUMMON); self.play(g, ZERO)
        self.assertEqual(self.progress(g), 1)
        self.assertEqual(len(self.quest(g).quest_progress.keys), 1); self.portable(g)

    def test_b02_opponent_turn_fill_waits_for_actual_owner_start(self):
        g=self.game((BOARD,), other_hand=(OTHER,)); self.play(g, BOARD); g.apply(EndTurn(1))
        self.play(g, OTHER); self.assertEqual(self.progress(g), 0)
        g.apply(EndTurn(2)); self.assertEqual(self.progress(g), 1); self.portable(g)

    def test_b03_locations_and_dormant_occupants_use_actual_board_space(self):
        g=self.game((BOARD,), board=(MINION,)*4+(DORMANT, LOCATION, LOCATION))
        self.play(g, BOARD); self.assertEqual(self.progress(g), 1); self.portable(g)

    def test_b04_actual_ruleset_board_capacity_is_not_hardcoded_seven(self):
        g=self.game((BOARD,), board=(MINION,)*3, ruleset=Ruleset(max_board=3))
        self.play(g, BOARD); self.assertEqual(self.progress(g), 1); self.portable(g)

    def test_b05_accepted_full_board_survives_earlier_clear_reaction(self):
        g=self.game((BOARD, SUMMON), board=(EARLY_BOARD,)); self.play(g, BOARD); self.play(g, SUMMON)
        self.assertLess(len(g.state.players[1].board), 7); self.assertEqual(self.progress(g), 1); self.portable(g)

    def test_c00_full_then_discard_empty_rewards_exact_existing_tick_and_tock(self):
        g=self.game((HAND, FILL, EMPTY)); self.play(g, HAND); self.play(g, FILL)
        self.assertEqual((len(g.state.players[1].hand), self.progress(g)), (10, 1))
        self.play(g, EMPTY); self.assertFalse(g.state.players[1].quests)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [REWARDS[1]])
        self.portable(g)

    def test_c01_empty_before_full_does_not_reverse_or_complete_the_order(self):
        g=self.game((HAND, RESTART)); self.play(g, HAND); self.play(g, RESTART)
        self.assertEqual(self.progress(g), 0)
        self.play(g, FILL); self.assertEqual(self.progress(g), 1)
        self.play(g, EMPTY); self.assertEqual(self.reward_count(g, REWARDS[1]), 1); self.portable(g)

    def test_c02_expanded_hand_requires_twelve_not_default_ten(self):
        g=self.game((HAND, PARTIAL, THREE, EMPTY), hand_cap=12); self.play(g, HAND); self.play(g, PARTIAL)
        self.assertEqual((len(g.state.players[1].hand), self.progress(g)), (10, 0))
        self.play(g, THREE); self.assertEqual((len(g.state.players[1].hand), self.progress(g)), (12, 1))
        self.play(g, EMPTY); self.assertEqual(self.reward_count(g, REWARDS[1]), 1); self.portable(g)

    def test_c03_capacity_change_itself_can_accept_full_state(self):
        g=self.game((HAND, SHRINK, ZERO, ZERO)); self.play(g, HAND); self.play(g, SHRINK)
        self.assertEqual((g.state.players[1].hand_cap, len(g.state.players[1].hand), self.progress(g)), (2, 2, 1))
        self.play(g, ZERO); self.play(g, ZERO)
        self.assertEqual(self.reward_count(g, REWARDS[1]), 1); self.portable(g)

    def test_c04_actual_ruleset_default_hand_capacity_is_respected(self):
        g=self.game((HAND, FILL, EMPTY), ruleset=Ruleset(max_hand=3)); self.play(g, HAND); self.play(g, FILL)
        self.assertEqual((len(g.state.players[1].hand), self.progress(g)), (3, 1))
        self.play(g, EMPTY); self.assertEqual(self.reward_count(g, REWARDS[1]), 1); self.portable(g)

    def test_c05_hand_to_deck_movement_can_empty_without_discard_or_playing_every_card(self):
        g=self.game((HAND, FILL, MOVE)); self.play(g, HAND); self.play(g, FILL); self.play(g, MOVE)
        self.assertEqual(self.reward_count(g, REWARDS[1]), 1); self.assertFalse(g.state.players[1].quests)
        self.portable(g)

    def test_c06_physical_hand_transfers_can_fill_then_empty_original_owner_hand(self):
        g=self.game((HAND, TAKE, TRANSFER), other_hand=(ZERO,)*9)
        self.play(g, HAND); self.play(g, TAKE); self.assertEqual(self.progress(g), 1)
        self.play(g, TRANSFER); self.assertEqual(self.reward_count(g, REWARDS[1]), 1)
        self.assertEqual(len(g.state.players[2].hand), 9); self.portable(g)

    def test_c07_full_fact_is_kept_when_earlier_notification_reaction_empties_hand(self):
        g=self.game((HAND, FILL), board=(EARLY_HAND,)); self.play(g, HAND); self.play(g, FILL)
        self.assertEqual(self.reward_count(g, REWARDS[1]), 1); self.assertFalse(g.state.players[1].quests)
        self.portable(g)

    def test_d00_progress_choice_restores_and_emptying_from_choice_completes_once(self):
        g=self.game((HAND, FILL), board=(WAIT,)); self.play(g, HAND); self.play(g, FILL)
        self.assertEqual(self.progress(g), 1); g=self.portable(g); self.choose(g, 'empty')
        self.assertEqual(self.reward_count(g, REWARDS[1]), 1); self.portable(g)

    def test_d01_reward_notification_wait_keeps_completing_slot_until_finish(self):
        g=self.game((HAND, FILL, EMPTY), board=(REWARD_WAIT,)); self.play(g, HAND); self.play(g, FILL)
        self.play(g, EMPTY); self.assertIsNotNone(g.state.pending_choice)
        self.assertTrue(self.quest(g).quest_progress.completing); g=self.portable(g); self.choose(g)
        self.assertFalse(g.state.players[1].quests); self.assertEqual(self.reward_count(g, REWARDS[1]), 1); self.portable(g)

    def test_d02_failed_progress_choice_rolls_back_rng_facts_and_original_pending_state(self):
        g=self.game((HAND, FILL), board=(WAIT,)); self.play(g, HAND); self.play(g, FILL); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before); self.choose(g, 'empty'); self.portable(g)

    def test_d03_removed_quest_does_not_earn_reward_from_old_pending_progress(self):
        g=self.game((HAND, FILL), board=(WAIT,)); self.play(g, HAND); self.play(g, FILL)
        self.choose(g, 'remove'); self.assertFalse(g.state.players[1].quests)
        self.assertEqual(self.reward_count(g, REWARDS[1]), 0); self.portable(g)

    def test_e00_second_player_uses_own_hand_and_real_owner_intervals(self):
        g=self.game((), other_hand=(HAND, FILL, EMPTY)); g.apply(EndTurn(1))
        self.play(g, HAND); self.play(g, FILL); self.assertEqual(self.progress(g, 2), 1)
        self.play(g, EMPTY); self.assertEqual(self.reward_count(g, REWARDS[1], 2), 1); self.portable(g)
        g=self.game((), other_hand=(BOARD,), other_board=(MINION,)*7); g.apply(EndTurn(1))
        self.play(g, BOARD); self.assertEqual(self.progress(g, 2), 1)
        self.cycle(g); self.cycle(g); self.assertEqual(self.reward_count(g, REWARDS[0], 2), 1); self.portable(g)

    def test_e01_previous_mechanics_cannot_restore_new_subscription_snapshots(self):
        g=self.game((HAND,)); saved=g.snapshot(); saved['mechanics_version']['version']='core-effects-v526'
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(saved), registry('reader'))


if __name__ == '__main__': unittest.main()
