"""Native repeatable quests reuse the quest interpreter and physical slot.

Minimal diagnostic rewards isolate cycle semantics; they are not a complete
TLC_426 adapter or a statement of its current formal condition/reward policy.
"""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (AdvanceQuest, CardClass, CardDefinition, CardMetadata, CardType,
    DeckPolicy, DeckSpec, EndTurn, Game, IllegalAction, Keyword, MatchSetup, PlayCard,
    PlayerSetup, QuestSpec, QuestStageSpec, Rarity, Registry, RemoveQuest,
    ResetQuestProgress, ResolutionError, Scenario, SelectChoice, SnapshotError, Zone)
from hs_sim.engine.effects import ChoiceOption, DamageBatch, Damage, GainArmor, InvokeBehavior, RequestChoice, Summon
from hs_sim.engine.quests import FinishQuestStage
from hs_sim.engine.pools import (GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery,
    resolve_candidates)
from hs_sim.engine.replay import build_replay, replay


def registry():
    r = Registry('repeatable-quest-tests-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30, initial_hero_power='power',
        metadata=CardMetadata(False, (CardClass.PALADIN,), Rarity.FREE)))
    r.register_behavior('noop', lambda c: ())
    r.register_card(CardDefinition('power', 'Power', CardType.HERO_POWER, cost=2, on_use='noop',
        metadata=CardMetadata(False, (CardClass.PALADIN,), Rarity.FREE)))
    r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, cost=1, attack=1, health=1,
        metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, max_copies=30)))

    def progress(c):
        if c.event.player_id != c.player_id:
            return ()
        p = c.source.quest_progress
        return (AdvanceQuest(c.source_id, p.id, p.stage),)

    r.register_behavior('progress', progress)
    r.register_behavior('reward', lambda c: (GainArmor(c.player_id, 3),))
    r.register_behavior('choose', lambda c: (RequestChoice(c.player_id, (
        ChoiceOption('ok', 'Receive reward', (GainArmor(c.player_id, 3),)),
        ChoiceOption('fail', 'Fail reward', (InvokeBehavior('fail', c.source_id, c.player_id),))), c.source_id),))
    r.register_behavior('remove', lambda c: (RemoveQuest(c.source_id),))
    r.register_behavior('fail', lambda c: (Summon(c.player_id, 'missing'),))
    r.register_behavior('summon.reward', lambda c: (Summon(c.player_id, 'plain'),))
    for name, reward, goal, kind in (
            ('q', 'reward', 2, 'repeatable_quest'), ('one', 'reward', 1, 'repeatable_quest'),
            ('waiting', 'choose', 1, 'repeatable_quest'), ('removed', 'remove', 1, 'repeatable_quest'),
            ('failed', 'fail', 1, 'repeatable_quest'), ('spawn', 'summon.reward', 1, 'repeatable_quest'),
            ('ordinary', 'reward', 1, 'quest'), ('side', 'reward', 1, 'sidequest')):
        keyword = Keyword.SIDEQUEST if kind == 'sidequest' else Keyword.QUEST
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=1, keywords=(keyword,),
            quest=QuestSpec(kind, (QuestStageSpec(name, goal, ('minion_summoned',), 'progress', reward),)),
            metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.LEGENDARY)))
    for n in (1, 2, 5):
        name = 'wave' + str(n)
        r.register_behavior(name, lambda c, n=n: tuple(Summon(c.player_id, 'plain') for _ in range(n)))
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))
    r.register_behavior('clear', lambda c: (DamageBatch(tuple(Damage(i, 2) for i in c.state.players[c.player_id].board)),))
    r.register_card(CardDefinition('clear', 'clear', CardType.SPELL, on_play='clear'))

    def stale(c):
        q = c.state.entities[c.state.players[c.player_id].quests[0]]
        p = q.quest_progress
        return (AdvanceQuest(q.id, p.id, 0, 9), AdvanceQuest(q.id, p.id, 0),
                ResetQuestProgress(q.id, p.id, 0), FinishQuestStage(q.id, p.id, 0))

    r.register_behavior('stale', stale)
    r.register_card(CardDefinition('stale', 'stale', CardType.SPELL, on_play='stale'))
    for key in ('a', 'b'):
        def distinct(c, key=key):
            q = c.state.entities[c.state.players[c.player_id].quests[0]]
            return (AdvanceQuest(q.id, q.quest_progress.id, 0, key=key),)
        r.register_behavior(key, distinct)
        r.register_card(CardDefinition(key, key, CardType.SPELL, on_play=key))
    return r


class RepeatableQuestTests(unittest.TestCase):
    def game(self, hand=('q', 'wave2'), enemy=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, deck=('plain',) * 4, mana=10, max_mana=10),
            PlayerSetup('hero', hand=enemy, deck=('plain',) * 4, mana=10, max_mana=10)), seed=17), registry())

    def play(self, g, name):
        pid = g.state.active_player
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(pid, eid))

    def quest(self, g, pid=1):
        return g.state.entities[g.state.players[pid].quests[0]]

    def armor(self, g, pid=1):
        return g.state.entities[g.state.players[pid].hero_id].armor

    def check(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, registry()).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)

    def test_native_declaration_uses_quest_keyword_and_one_stage(self):
        r = registry(); q = r.card('q')
        self.assertTrue(q.quest.starts_in_hand)
        self.assertEqual(q.keywords, (Keyword.QUEST,))
        with self.assertRaises(ValueError):
            QuestSpec('repeatable_quest', (q.quest.stages[0], q.quest.stages[0]))
        with self.assertRaises(ValueError):
            r.register_card(replace(q, id='wrong', keywords=(Keyword.SIDEQUEST,)))

    def test_completion_retains_physical_slot_and_rotates_cycle_identity(self):
        g = self.game(); self.play(g, 'q'); before = self.quest(g)
        self.play(g, 'wave2'); after = self.quest(g)
        self.assertEqual((after.id, after.zone, after.zone_epoch), (before.id, Zone.QUEST, before.zone_epoch))
        self.assertGreater(after.quest_progress.id, before.quest_progress.id)
        self.assertEqual((after.quest_progress.stage, after.quest_progress.value, after.quest_progress.keys), (0, 0, ()))
        self.assertEqual((self.armor(g), g.state.players[1].mana), (3, 9))
        self.assertEqual(sum(row.card_id == 'q' for row in g.state.play_history), 1)
        self.check(g)

    def test_multiple_sequential_summons_can_finish_two_cycles_in_one_action(self):
        g = self.game(('q', 'wave5')); self.play(g, 'q'); self.play(g, 'wave5')
        self.assertEqual((self.armor(g), self.quest(g).quest_progress.value), (6, 1))
        self.assertEqual(sum(e.kind == 'quest_completed' for e in g.events), 2)
        self.assertEqual(len(g.state.players[1].quests), 1)
        self.check(g)

    def test_excess_and_old_cycle_commands_do_not_enter_new_cycle(self):
        g = self.game(('q', 'stale', 'wave1')); self.play(g, 'q'); self.play(g, 'stale')
        self.assertEqual((self.armor(g), self.quest(g).quest_progress.value), (3, 0))
        self.assertEqual(sum(e.kind == 'quest_completed' for e in g.events), 1)
        self.play(g, 'wave1'); self.assertEqual(self.quest(g).quest_progress.value, 1)
        self.check(g)

    def test_distinct_keys_reset_and_can_be_used_again_next_cycle(self):
        g = self.game(('q', 'a', 'a', 'b', 'a')); self.play(g, 'q')
        self.play(g, 'a'); self.play(g, 'a')
        self.assertEqual(self.quest(g).quest_progress.value, 1)
        self.play(g, 'b'); self.assertEqual(self.quest(g).quest_progress.keys, ())
        self.play(g, 'a'); self.assertEqual(self.quest(g).quest_progress.keys, ('a',))
        self.check(g)

    def test_reward_events_do_not_progress_not_yet_started_cycle(self):
        g = self.game(('spawn', 'wave1', 'wave1')); self.play(g, 'spawn'); self.play(g, 'wave1')
        self.assertEqual((len(g.state.players[1].board), self.quest(g).quest_progress.value), (2, 0))
        self.play(g, 'wave1'); self.assertEqual(len(g.state.players[1].board), 4)
        self.assertEqual(sum(e.kind == 'quest_completed' for e in g.events), 2)
        self.check(g)

    def test_reward_choice_keeps_completing_slot_then_restarts_once(self):
        g = self.game(('waiting', 'wave1', 'wave1')); self.play(g, 'waiting')
        instance = self.quest(g).quest_progress.id; self.play(g, 'wave1')
        self.assertTrue(self.quest(g).quest_progress.completing)
        self.assertEqual(self.quest(g).quest_progress.id, instance)
        self.check(g)
        choice = g.state.pending_choice; g.apply(SelectChoice(1, choice.id, ('ok',)))
        self.assertEqual((self.armor(g), self.quest(g).quest_progress.value), (3, 0))
        self.assertGreater(self.quest(g).quest_progress.id, instance)
        self.check(g)

    def test_bad_reward_selection_preserves_committed_waiting_boundary(self):
        g = self.game(('waiting', 'wave1')); self.play(g, 'waiting'); self.play(g, 'wave1')
        saved = g.snapshot(); choice = g.state.pending_choice
        with self.assertRaises(ResolutionError):
            g.apply(SelectChoice(1, choice.id, ('fail',)))
        self.assertEqual(g.snapshot(), saved)
        g.apply(SelectChoice(1, choice.id, ('ok',))); self.assertEqual(self.armor(g), 3)
        self.check(g)

    def test_failed_reward_rolls_back_completion_payment_and_board(self):
        g = self.game(('failed', 'wave1')); self.play(g, 'failed'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'wave1')
        self.assertEqual(g.snapshot(), saved)
        self.assertEqual(self.quest(g).quest_progress.value, 0)
        self.check(g)

    def test_removal_during_reward_prevents_cycle_restart(self):
        g = self.game(('removed', 'wave1')); self.play(g, 'removed'); eid = self.quest(g).id
        self.play(g, 'wave1')
        self.assertFalse(g.state.players[1].quests)
        self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD)
        self.assertIsNone(g.state.entities[eid].quest_progress)
        self.assertFalse(any(e.kind == 'quest_completed' for e in g.events))
        self.check(g)

    def test_active_cycle_still_blocks_duplicate_and_other_main_quest(self):
        g = self.game(('one', 'wave1', 'one', 'ordinary')); self.play(g, 'one'); self.play(g, 'wave1')
        for name in ('one', 'ordinary'):
            saved = g.snapshot()
            with self.assertRaises(IllegalAction): self.play(g, name)
            self.assertEqual(g.snapshot(), saved)
        self.check(g)

    def test_ordinary_and_side_quests_keep_their_final_retirement(self):
        for name in ('ordinary', 'side'):
            with self.subTest(kind=name):
                g = self.game((name, 'wave1')); self.play(g, name); self.play(g, 'wave1')
                self.assertFalse(g.state.players[1].quests)
                self.assertEqual(self.armor(g), 3)
                self.check(g)

    def test_enemy_summons_and_turn_changes_do_not_reset_or_progress(self):
        g = self.game(('q', 'wave1'), ('wave1',)); self.play(g, 'q'); self.play(g, 'wave1')
        p = self.quest(g).quest_progress; g.apply(EndTurn(1)); self.play(g, 'wave1'); g.apply(EndTurn(2))
        self.assertEqual(self.quest(g).quest_progress, p)
        self.check(g)

    def test_both_players_have_separate_cycle_instances_and_rewards(self):
        g = self.game(('one', 'wave1'), ('one', 'wave1')); self.play(g, 'one'); self.play(g, 'wave1')
        first = self.quest(g).quest_progress; g.apply(EndTurn(1)); self.play(g, 'one'); self.play(g, 'wave1')
        self.assertEqual((self.armor(g), self.armor(g, 2)), (3, 3))
        self.assertNotEqual(first.id, self.quest(g, 2).quest_progress.id)
        self.check(g)

    def test_public_cycle_progress_keeps_private_instance_keys_out(self):
        g = self.game(('q', 'a')); self.play(g, 'q'); self.play(g, 'a')
        for pid in (1, 2):
            view = g.observe(pid); events = g.player_events(pid)
            text = json.dumps((view, events))
            self.assertIn('repeatable_quest', text)
            self.assertNotIn('instance_id', text)
            self.assertNotIn('"keys"', text)
        self.check(g)

    def test_repeatable_quest_metadata_stays_excluded_from_random_generation(self):
        r = registry()
        for name in ('q', 'side'): r.register_pool_card(PoolCard.from_definition(r.card(name)))
        r.register_pool(PoolDefinition('pool', 'v1', 'test', 'experimental', (PoolMember('q'), PoolMember('side'))))
        rows = resolve_candidates(r, GenerationContext('test', 'experimental'), 'pool', PoolQuery(class_mode='any'))
        self.assertEqual([row.card_id for row in rows], ['side'])

    def test_repeatable_quest_is_guaranteed_in_normal_opening_and_can_be_mulliganed(self):
        r = registry(); cards = ('plain',) * 29 + ('q',)
        decks = (DeckSpec('hero', 'power', CardClass.PALADIN, cards),
                 DeckSpec('hero', 'power', CardClass.PALADIN, ('plain',) * 30))
        policy = DeckPolicy('repeatable-opening', 'test', 'experimental', tuple(r.cards))
        r.register_behavior('coin', lambda c: ())
        r.register_card(CardDefinition('coin', 'Coin', CardType.SPELL, on_play='coin'))
        g = Game.from_decks(MatchSetup(decks, policy, 'coin', 17, 1), r)
        self.assertIn('q', [g.state.entities[i].card_id for i in g.state.players[1].hand])
        self.assertEqual(len(g.state.players[1].hand), 3)
        choice = g.state.pending_choice; option = next(o.id for o in choice.options if o.card_id == 'q')
        g.apply(SelectChoice(1, choice.id, (option,))); choice = g.state.pending_choice
        g.apply(SelectChoice(2, choice.id, ()))
        self.assertNotIn('q', [g.state.entities[i].card_id for i in g.state.players[1].hand])
        self.assertIn('q', [g.state.entities[i].card_id for i in g.state.players[1].deck])

    def test_old_schema_is_rejected_after_repeatable_kind_extension(self):
        g = self.game(); snapshot = g.snapshot(); snapshot['schema_version'] -= 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(snapshot, registry())


if __name__ == '__main__':
    unittest.main()
