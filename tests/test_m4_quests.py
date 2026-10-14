"""Quest area, progression, rewards, opening, information and recovery contracts."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (AdvanceQuest, CardClass, CardDefinition, CardMetadata, CardType,
    DeckPolicy, DeckSpec, EndTurn, Game, IllegalAction, Keyword, MatchSetup, PlayCard,
    PlayerSetup, QuestSpec, QuestStageSpec, Rarity, RemoveQuest, ResetQuestProgress,
    ResolutionError, Ruleset, Scenario, SelectChoice, SnapshotError, UseHeroPower, Zone)
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, DamageBatch,
    Destroy, EquipWeapon, GainArmor, GrantKeyword, RequestChoice, SetStats, Summon)
from hs_sim.engine.pools import PoolCard, PoolDefinition, PoolMember, PoolQuery, resolve_candidates
from hs_sim.engine.representative import build_registry, quest_increment
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class QuestTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, attack=1, health=1, metadata=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,max_copies=30)))
        for n in (1, 4, 5, 6, 7, 20):
            self.spell(f'wave{n}', lambda c, n=n: [Summon(c.player_id, 'plain') for _ in range(n)])
            self.spell(f'attack{n}', lambda c, n=n: [Buff(c.state.players[c.player_id].hero_id, attack=n,
                source_id=c.source_id, expires_turn=c.state.turn)])
        self.spell('clear', lambda c: [DamageBatch(tuple(Damage(i, 10) for i in c.state.players[c.player_id].board))])
        self.r.register_behavior('increment', quest_increment)
        self.r.register_behavior('reward', lambda c: [GainArmor(c.player_id, 3)])

    def spell(self, name, callback):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))

    def quest(self, name='quest', kind='quest', goal=2, reward='reward', progress='increment', events=('minion_summoned',)):
        cards = (name,) if kind != 'questline' else (name, name+'.2', name+'.3')
        for card in cards[1:]:
            self.r.register_card(CardDefinition(card, card, CardType.SPELL, choice_only=True))
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, keywords=(Keyword(kind),),
            quest=QuestSpec(kind, tuple(QuestStageSpec(card, goal, events, progress, reward) for card in cards)),
            metadata=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.LEGENDARY if kind != "sidequest" else Rarity.COMMON)))

    def game(self, hand=(), enemy_hand=(), board=(), rules=None, weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01', hand=hand, board=board, deck=('plain',)*15, mana=10, max_mana=10, weapon_card_id=weapon),
            PlayerSetup('HERO_08', hand=enemy_hand, deck=('plain',)*15, mana=10, max_mana=10)), seed=91), self.r, ruleset=rules)

    def play(self, g, card):
        player = g.state.active_player
        entity = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == card)
        return g.apply(PlayCard(player, entity))

    def active(self, g, player=1, index=0):
        return g.state.entities[g.state.players[player].quests[index]]

    def cycle(self, g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def check(self, g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())), self.r).snapshot(), g.snapshot())
        self.assertEqual(g.clone().snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), g.snapshot())

    def test_quest_is_physical_spell_in_independent_area(self):
        g=self.game(hand=('ULD_155',), board=('plain',)*7); q=g.state.players[1].hand[0]
        self.play(g,'ULD_155'); self.assertEqual(g.state.entities[q].zone,Zone.QUEST)
        self.assertEqual(len(g.state.players[1].board),7); self.assertEqual(g.state.players[1].mana,9)
        self.assertFalse(g.state.death_history); self.check(g)

    def test_counts_only_after_play_not_hand_or_previous_summons(self):
        g=self.game(hand=('wave1','ULD_155','wave1')); self.play(g,'wave1'); self.play(g,'ULD_155')
        self.assertEqual(self.active(g).quest_progress.value,0); self.play(g,'wave1')
        self.assertEqual(self.active(g).quest_progress.value,1)

    def test_enemy_summons_do_not_progress_own_quest(self):
        g=self.game(hand=('ULD_155',),enemy_hand=('wave5',)); self.play(g,'ULD_155');g.apply(EndTurn(1));self.play(g,'wave5')
        self.assertEqual(self.active(g).quest_progress.value,0)

    def test_sidequest_reward_buffs_current_minions_and_removes_slot(self):
        g=self.game(hand=('DRG_008','wave5')); self.play(g,'DRG_008');self.play(g,'wave5')
        self.assertFalse(g.state.players[1].quests)
        self.assertTrue(all(g.state.entities[i].attack==2 and g.state.entities[i].health==2 for i in g.state.players[1].board));self.check(g)

    def test_vault_twenty_summons_replaces_power(self):
        g=self.game(hand=('ULD_155','wave7','clear','wave7','clear','wave6'))
        for card in ('ULD_155','wave7','clear','wave7','clear','wave6'):self.play(g,card)
        self.assertFalse(g.state.players[1].quests)
        power=g.state.entities[g.state.players[1].hero_power_id];self.assertEqual(power.card_id,'ULD_155p')
        g.apply(UseHeroPower(1,power.id));self.assertTrue(all(g.state.entities[i].attack==3 for i in g.state.players[1].board));self.check(g)

    def test_park_all_three_stages_and_guff_battlecry(self):
        g=self.game(hand=('SW_428','attack4','attack5','attack6'))
        for card in ('SW_428','attack4','attack5','attack6'):self.play(g,card)
        self.assertFalse(g.state.players[1].quests);self.play(g,'SW_428t4')
        hero=g.state.entities[g.state.players[1].hero_id];self.assertEqual((hero.attack,hero.armor),(23,18))
        self.cycle(g);self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack,0);self.check(g)

    def test_large_gain_does_not_overflow_into_next_stage(self):
        g=self.game(hand=('SW_428','attack20'));self.play(g,'SW_428');self.play(g,'attack20')
        q=self.active(g).quest_progress;self.assertEqual((q.stage,q.value),(1,0));self.check(g)

    def test_weapon_turn_activation_is_not_new_attack_gain(self):
        g=self.game(hand=('SW_428',),weapon='CS2_106');self.play(g,'SW_428');self.cycle(g)
        self.assertEqual(self.active(g).quest_progress.value,0)

    def test_weapon_equip_positive_difference_progresses(self):
        self.spell('equip',lambda c:[EquipWeapon(c.player_id,'CS2_106')])
        g=self.game(hand=('SW_428','equip'));self.play(g,'SW_428');self.play(g,'equip')
        self.assertEqual(self.active(g).quest_progress.value,3)

    def test_set_attack_counts_positive_change_only(self):
        self.spell('set',lambda c:[SetStats(c.state.players[1].hero_id,attack=2)])
        g=self.game(hand=('SW_428','set','set'));self.play(g,'SW_428');self.play(g,'set');self.play(g,'set')
        self.assertEqual(self.active(g).quest_progress.value,2)

    def test_duplicate_quest_rejected_without_payment(self):
        g=self.game(hand=('ULD_155','ULD_155'));self.play(g,'ULD_155');before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'ULD_155')
        self.assertEqual(g.snapshot(),before)

    def test_different_main_quests_are_mutually_exclusive(self):
        g=self.game(hand=('ULD_155','SW_428'));self.play(g,'ULD_155')
        with self.assertRaises(IllegalAction):self.play(g,'SW_428')

    def test_main_and_sidequest_coexist(self):
        g=self.game(hand=('ULD_155','DRG_008','wave5'))
        for card in ('ULD_155','DRG_008','wave5'):self.play(g,card)
        self.assertEqual(self.active(g).card_id,'ULD_155');self.assertEqual(self.active(g).quest_progress.value,5)

    def test_duplicate_sidequest_rejected(self):
        g=self.game(hand=('DRG_008','DRG_008'));self.play(g,'DRG_008')
        with self.assertRaises(IllegalAction):self.play(g,'DRG_008')

    def test_completed_quest_can_be_played_again_with_new_instance(self):
        self.quest(goal=1);g=self.game(hand=('quest','wave1','quest'));self.play(g,'quest');old=self.active(g).quest_progress.id
        self.play(g,'wave1');self.play(g,'quest');self.assertGreater(self.active(g).quest_progress.id,old)
        self.assertEqual(self.active(g).quest_progress.value,0)

    def test_configured_quest_capacity_enforced(self):
        self.quest('side','sidequest');g=self.game(hand=('ULD_155','side'),rules=Ruleset(max_quests=1));self.play(g,'ULD_155')
        with self.assertRaises(IllegalAction):self.play(g,'side')

    def test_failed_summons_do_not_progress(self):
        g=self.game(hand=('ULD_155','wave7'),board=('plain',)*6);self.play(g,'ULD_155');self.play(g,'wave7')
        self.assertEqual(self.active(g).quest_progress.value,1)

    def test_distinct_keys_do_not_double_count(self):
        def unique(c):
            q=c.source.quest_progress
            return [AdvanceQuest(c.source_id,q.id,q.stage,key=c.state.entities[c.event.source_id].card_id)]
        self.r.register_behavior('unique',unique);self.quest(goal=2,progress='unique')
        g=self.game(hand=('quest','wave5'));self.play(g,'quest');self.play(g,'wave5')
        self.assertEqual((self.active(g).quest_progress.value,self.active(g).quest_progress.keys),(1,('plain',)));self.check(g)

    def test_explicit_turn_reset_clears_progress_and_keys(self):
        def progress(c):
            q=c.source.quest_progress
            if c.event.kind=='turn_ended':return [ResetQuestProgress(c.source_id,q.id,q.stage)]
            return quest_increment(c)
        self.r.register_behavior('per_turn',progress);self.quest(goal=3,progress='per_turn',events=('minion_summoned','turn_ended'))
        g=self.game(hand=('quest','wave1'));self.play(g,'quest');self.play(g,'wave1');g.apply(EndTurn(1))
        self.assertEqual(self.active(g).quest_progress.value,0);self.check(g)

    def test_queued_previous_stage_events_are_discarded(self):
        self.quest(kind='questline',goal=1)
        # A single handler emits two matching events before any progression runs.
        from hs_sim.engine.effects import Effect
        from hs_sim.engine.resolver import default_mechanics
        from dataclasses import dataclass
        @dataclass(frozen=True)
        class Burst(Effect):pass
        mechanics=default_mechanics()
        def emit(r,e):
            r.emit('ping',player_id=1);r.emit('ping',player_id=1)
        mechanics.register(Burst,emit)
        self.spell('burst',lambda c:[Burst()])
        # Separate definition selects ping, leaving the original definition unused.
        self.quest('line','questline',1,events=('ping',))
        g=Game.from_scenario(Scenario((PlayerSetup('test.hero',hand=('line','burst')),PlayerSetup('test.hero'))),self.r,mechanics=mechanics)
        self.play(g,'line');self.play(g,'burst');self.assertEqual((self.active(g).quest_progress.stage,self.active(g).quest_progress.value),(1,0))

    def test_reward_choice_can_save_restore_and_resume_next_stage(self):
        self.r.register_behavior('choose',lambda c:[RequestChoice(c.player_id,(ChoiceOption('yes','Armor',(GainArmor(c.player_id,4),)),),c.source_id)])
        self.quest(kind='questline',goal=1,reward='choose');g=self.game(hand=('quest','wave1'));self.play(g,'quest');self.play(g,'wave1')
        self.assertTrue(self.active(g).quest_progress.completing);self.check(g)
        saved=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,saved):
            choice=match.state.pending_choice;match.apply(SelectChoice(1,choice.id,('yes',)))
            self.assertEqual(self.active(match).quest_progress.stage,1)
        self.assertEqual(g.snapshot(),saved.snapshot());self.check(g)

    def test_reward_generated_event_does_not_feed_next_stage(self):
        self.r.register_behavior('summon_reward',lambda c:[Summon(c.player_id,'plain')])
        self.quest(kind='questline',goal=1,reward='summon_reward');g=self.game(hand=('quest','wave1'));self.play(g,'quest');self.play(g,'wave1')
        self.assertEqual((self.active(g).quest_progress.stage,self.active(g).quest_progress.value),(1,0))

    def test_reward_failure_rolls_back_triggering_action_and_progress(self):
        self.r.register_behavior('fail',lambda c:[Summon(c.player_id,'missing')]);self.quest(goal=1,reward='fail')
        g=self.game(hand=('quest','wave1'));self.play(g,'quest');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'wave1')
        self.assertEqual(g.snapshot(),before)

    def test_removal_invalidates_queued_progress(self):
        def remove_and_increment(c):
            return [RemoveQuest(c.source_id),*quest_increment(c)]
        self.r.register_behavior('remove',remove_and_increment);self.quest(goal=1,progress='remove')
        g=self.game(hand=('quest','wave1'));self.play(g,'quest');self.play(g,'wave1')
        self.assertFalse(g.state.players[1].quests);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.check(g)

    def test_public_progress_and_stage_descriptor_visible_to_both(self):
        g=self.game(hand=('SW_428','attack4'));self.play(g,'SW_428');self.play(g,'attack4')
        for viewer in (1,2):
            q=g.observe(viewer)['players'][0]['quests'][0]['quest']
            self.assertEqual((q['stage_card_id'],q['stage'],q['progress']),('SW_428t',2,0))
            self.assertNotIn('instance_id',json.dumps(g.observe(viewer)))
            completed=[e for e in g.player_events(viewer) if e['kind']=='quest_stage_completed']
            self.assertEqual(completed[0]['quest']['stage_card_id'],'SW_428')
        self.check(g)

    def test_player_command_rejects_second_main_quest_and_enumeration_agrees(self):
        g=self.game(hand=('ULD_155','SW_428'));port=g.for_player(1);listing=port.legal_actions()
        cards={e['card_id']:e['ref'] for e in listing['observation']['players'][0]['hand']}
        self.assertTrue(port.submit({'revision':listing['revision'],'action':{'type':'play_card','card':cards['ULD_155']}})['accepted'])
        listing=port.legal_actions();self.assertFalse(any(a.get('card')==cards['SW_428'] for a in listing['actions']))
        self.assertFalse(port.submit({'revision':listing['revision'],'action':{'type':'play_card','card':cards['SW_428']}})['accepted'])

    def test_stage_descriptors_cannot_be_physical_cards(self):
        with self.assertRaises(ValueError):self.game(hand=('SW_428t',))

    def test_invalid_definition_and_unknown_reward_rejected(self):
        with self.assertRaises(ValueError):QuestSpec('questline',())
        with self.assertRaises(ValueError):QuestStageSpec('q',True,('ping',),'a','b')
        self.quest(reward='missing')
        with self.assertRaises(ValueError):self.r.validate()

    def test_snapshot_rejects_corrupted_progress(self):
        g=self.game(hand=('SW_428',));self.play(g,'SW_428')
        for field,value in (('stage',3),('value',5),('value',True),('id',0),('completing',True),('keys',['same','same'])):
            row=g.snapshot();row['state']['entities'][str(self.active(g).id)]['quest_progress'][field]=value
            row['state_hash']=canonical_hash({k:v for k,v in row.items() if k not in ('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError):Game.from_snapshot(row,self.r)

    def opening(self, cards, seed=13, first=1):
        decks=(DeckSpec('HERO_01','HERO_01bp',CardClass.WARRIOR,cards),
               DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,('plain',)*30))
        policy=DeckPolicy('quest-opening','test','experimental',tuple(self.r.cards))
        return Game.from_decks(MatchSetup(decks,policy,'GAME_005',seed,first),self.r)

    def test_quest_guaranteed_for_both_first_and_second_player(self):
        self.quest()
        for first in (1,2):
            for seed in (1,17,31):
                g=self.opening(('plain',)*29+('quest',),seed,first)
                self.assertIn('quest',[g.state.entities[i].card_id for i in g.state.players[1].hand])
                self.assertFalse(g.state.players[1].quests)
        self.check(g)

    def test_questline_guaranteed_and_sidequest_not_guaranteed(self):
        self.quest('line','questline');self.quest('side','sidequest')
        g=self.opening(('plain',)*28+('line','side'))
        hand=[g.state.entities[i].card_id for i in g.state.players[1].hand]
        self.assertIn('line',hand);self.assertNotIn('side',hand)

    def test_guaranteed_quest_mulliganed_away_is_not_forced_back(self):
        self.quest();g=self.opening(('plain',)*29+('quest',))
        choice=g.state.pending_choice
        selected=next(o.id for o in choice.options if o.card_id=='quest')
        g.apply(SelectChoice(1,choice.id,(selected,)));choice=g.state.pending_choice
        g.apply(SelectChoice(2,choice.id,()))
        self.assertNotIn('quest',[g.state.entities[i].card_id for i in g.state.players[1].hand])
        self.assertIn('quest',[g.state.entities[i].card_id for i in g.state.players[1].deck]);self.check(g)

    def test_multiple_different_guaranteed_quests_keep_hand_size(self):
        self.quest('q1');self.quest('q2');g=self.opening(('plain',)*28+('q1','q2'))
        hand=[g.state.entities[i].card_id for i in g.state.players[1].hand]
        self.assertEqual(len(hand),3);self.assertTrue({'q1','q2'}<=set(hand));self.check(g)

    def test_generation_excludes_unimplemented_quest_metadata_but_not_sidequest(self):
        from hs_sim.engine.pools import GenerationContext
        self.r.register_pool_card(PoolCard('unknownquest',CardType.SPELL,1,
            CardMetadata(True,(CardClass.NEUTRAL,),Rarity.LEGENDARY),keywords=(Keyword.QUEST,)))
        self.r.register_pool_card(PoolCard.from_definition(self.r.card('DRG_008')))
        self.r.register_pool(PoolDefinition('qpool','v1','test','experimental',
            (PoolMember('unknownquest'),PoolMember('DRG_008'))))
        candidates=resolve_candidates(self.r,GenerationContext('test','experimental'),'qpool',PoolQuery(class_mode='any'))
        self.assertEqual([c.card_id for c in candidates],['DRG_008'])

    def test_completed_reward_card_burns_when_hand_is_full(self):
        # Fill after committing the final progress spell, before the gain resolves.
        self.spell('fill_gain',lambda c:[*[AddToHand(1,'plain') for _ in range(10)],
                                         Buff(c.state.players[1].hero_id,attack=6)])
        g=self.game(hand=('SW_428','attack4','attack5','fill_gain'))
        for card in ('SW_428','attack4','attack5','fill_gain'):self.play(g,card)
        self.assertFalse(g.state.players[1].quests)
        self.assertFalse(any(g.state.entities[i].card_id=='SW_428t4' for i in g.state.players[1].hand))
        self.assertTrue(any(g.state.entities[i].card_id=='SW_428t4' for i in g.state.players[1].graveyard));self.check(g)

    def test_progress_effect_rejects_boolean_negative_and_bad_key_amount(self):
        for args in ((1,1,0,True),(1,1,0,-1),(1,1,0,2,'key'),(1,1,-1,1)):
            with self.assertRaises(ValueError):AdvanceQuest(*args)

    def test_quest_spell_does_not_count_its_own_play(self):
        self.quest(goal=2,events=('card_played',));g=self.game(hand=('quest','wave1'))
        self.play(g,'quest');self.assertEqual(self.active(g).quest_progress.value,0)
        self.play(g,'wave1');self.assertEqual(self.active(g).quest_progress.value,1)

    def test_reward_events_can_progress_other_active_quest(self):
        self.r.register_behavior('spawn',lambda c:[Summon(1,'plain')])
        self.quest('side','sidequest',goal=1,reward='spawn')
        g=self.game(hand=('ULD_155','side','wave1'))
        for card in ('ULD_155','side','wave1'):self.play(g,card)
        self.assertEqual(self.active(g).quest_progress.value,2);self.check(g)

    def test_public_log_rejects_corrupted_stage_goal(self):
        g=self.game(hand=('SW_428',));self.play(g,'SW_428');row=g.snapshot()
        for knowledge in row['information']['players'].values():
            for event in knowledge['events']:
                if event['kind']=='quest_started':event['quest']['goal']=False
        row['state_hash']=canonical_hash({k:v for k,v in row.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(row,self.r)

    def test_hidden_enemy_cards_do_not_change_quest_legality(self):
        a=self.game(hand=('SW_428',),enemy_hand=('plain',));b=self.game(hand=('SW_428',),enemy_hand=('DRG_008',))
        self.assertEqual(a.for_player(1).legal_actions(),b.for_player(1).legal_actions())

    def test_real_questline_example_uses_player_commands_restores_and_replays(self):
        from examples.complete_questline import run
        game,snapshot=run()
        self.assertEqual(snapshot['schema_version'],266)
        self.assertEqual(len(game.history),47)
        self.assertFalse(game.state.players[1].quests)

    def test_bare_quest_keyword_grant_is_rejected(self):
        self.spell('bare',lambda c:[GrantKeyword(c.state.players[1].board[0],Keyword.QUEST)])
        g=self.game(hand=('bare',),board=('plain',))
        with self.assertRaises(ResolutionError):self.play(g,'bare')


if __name__=='__main__':unittest.main()
