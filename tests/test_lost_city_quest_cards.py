"""Real quest turns and complete reward split; native Time Warp/Crystal Core."""
from dataclasses import asdict
from functools import lru_cache
import json,unittest

from hs_sim.cards import build_registry
from hs_sim.cards.lost_city_quest_cards import (BASE_PROGRAM,CORE,CONTEXT,POOL,REWARD,REWARDS,
    ROOT,WARP,WARP_USED,load_batch)
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,
    SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.actions import Concede
from hs_sim.engine.card_creation import CreatedMinionStats
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,Damage,InvokeBehavior,
    RequestChoice,ReturnToHand,Silence,Summon,Transform,CopyMinion,SetStats)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.fixed_reward_splits import ACCEPTED as SPLIT_ACCEPTED,SplitFixedRewards
from hs_sim.engine.minion_base_programs import ACCEPTED as BASE_ACCEPTED
from hs_sim.engine.model import BoardPresenceReference,SummonStats
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from hs_sim.engine.allocation_facts import SourceAllocationFact

P='lostcity.test.'
SMALL,LARGE,FILLER=P+'small',P+'large',P+'filler'


@lru_cache(None)
def registry(role='writer',mode='plain'):
    r=build_registry()
    def fail(c):raise ResolutionError('deliberate Lost City delivery failure')
    r.register_behavior(P+'fail',fail)
    bodies={
        'noop':lambda c:(),
        'buff':lambda c:(Buff(c.target_id,3,4,c.source_id),),
        'hurt':lambda c:(Damage(c.target_id,3,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'steal':lambda c:(ChangeControl(c.target_id,c.player_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'transform':lambda c:(Transform(c.target_id,LARGE),),
        'set':lambda c:(SetStats(c.target_id,1,1,c.source_id),),
        'copy':lambda c:(CopyMinion(BoardPresenceReference.capture(c.state,c.target_id),c.player_id,
            stats=SummonStats(1,1),cause=SummonCause.capture(c)),),
        'make':lambda c:(AddToHand(c.player_id,SMALL,c.source_id,
            minion_stats=CreatedMinionStats(set_to=SummonStats(1,1))),),
        'summon':lambda c:(Summon(c.player_id,SMALL),),
        'extra':lambda c:(QueueTurns((c.player_id,),c.source_id),),
        'skip':lambda c:(SkipTurns(3-c.player_id,1,c.source_id),),
    }
    targets={'buff','hurt','silence','steal','bounce','transform','copy','set'}
    for key,fn in bodies.items():
        r.register_behavior(P+key,fn)
        r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,requires_target=key in targets))
    for cid,a,h in((SMALL,1,2),(LARGE,8,9),(FILLER,2,3)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=a,health=h))
    r.register_card(CardDefinition(P+'hero','Scenario hero',CardType.HERO,health=300))
    if mode!='plain':
        def watch(c):
            relevant=(c.event.kind=='card_added_to_hand'and c.state.entities[c.event.target_id].card_id in REWARDS
                if mode.startswith('split')else c.event.kind=='player_effect_added'and dict(c.event.data)['effect_key']==BASE_PROGRAM
                if mode.startswith('core')else c.event.kind=='turns_scheduled')
            if not relevant:return ()
            if mode.endswith('fail'):return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',
                (InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(P+'watch','Delivery observer',CardType.MINION,health=20,
            triggers=(TriggerSpec('card_added_to_hand',P+'watch'),TriggerSpec('player_effect_added',P+'watch'),
                TriggerSpec('turns_scheduled',P+'watch'))))
    r.validate();r.freeze();return r


class LostCityTests(unittest.TestCase):
    def game(self,hand=(),*,board=(),deck=(),other_hand=(),other_board=(),mode='plain',seed=2911):
        self.mode=mode
        a=PlayerSetup(P+'hero',hand=hand,board=((*board,P+'watch')if mode!='plain'else board),deck=deck or(FILLER,)*30,
            mana=30,max_mana=30,mana_cap=30)
        b=PlayerSetup(P+'hero',hand=other_hand,board=other_board,deck=(FILLER,)*30,mana=30,max_mana=30,mana_cap=30)
        return Game.from_scenario(Scenario((a,b),seed=seed),registry('writer',mode))
    def play(self,g,cid,target=None):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        kind=g.registry.card(cid).kind
        g.apply(PlayCard(pid,eid,target,position=len(g.state.players[pid].board)if kind==CardType.MINION else None));return eid
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        snap=json.loads(json.dumps(g.snapshot()));r=registry('reader',self.mode)
        restored=Game.from_snapshot(snap,r);self.assertEqual(restored.snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),r).snapshot(),snap);return restored
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
    def stats(self,g,eid):
        e=g.state.entities[eid];return(e.attack,e.health,e.max_health)

    def test_a01_complete_sources_and_nine_actual_original_rewards_are_pinned(self):
        d=load_batch();r=registry();self.assertEqual(len(d['reward_origins']),9)
        self.assertEqual(tuple(x.card_id for x in r.pool(POOL,CONTEXT).members),REWARDS)
        self.assertTrue(all(r.card(cid).hand_playable for cid in REWARDS))
        self.assertEqual((r.card(ROOT).cost,r.card(ROOT).quest.stages[0].goal),(1,10))
        self.assertEqual((r.card(REWARD).cost,r.card(REWARD).attack,r.card(REWARD).health),(5,8,8))
        self.assertEqual(set(d['existing_definition_pins']),{x['record']['id']for x in d['existing_dependencies']})

    def test_a02_real_ten_subsequent_turns_complete_once_and_use_normal_reward_delivery(self):
        g=self.game((ROOT,));source=self.play(g,ROOT)
        self.assertEqual(g.state.entities[source].quest_progress.value,0)
        for i in range(1,11):
            g.apply(EndTurn(g.state.active_player))
            if i<10:self.assertEqual(g.state.entities[source].quest_progress.value,i)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(sum(g.state.entities[i].card_id==REWARD for i in g.state.players[1].hand),1)
        self.assertEqual(len(g.state.quest_hand_rewards),1);self.assertEqual(g.state.quest_hand_rewards[0].phase,'delivered')
        self.portable(g)

    def test_a03_real_full_hand_completion_waits_then_next_play_gets_actual_reward(self):
        g=self.game((ROOT,)+(FILLER,)*9);source=self.play(g,ROOT)
        for _ in range(10):g.apply(EndTurn(g.state.active_player))
        row,=g.state.quest_hand_rewards;self.assertEqual((row.phase,row.request.source.entity_id),('pending',source))
        self.assertEqual(len(g.state.players[1].hand),10)
        self.play(g,FILLER);self.assertEqual(g.state.quest_hand_rewards[0].phase,'delivered')
        self.assertEqual(sum(g.state.entities[i].card_id==REWARD for i in g.state.players[1].hand),1)

    def test_a04_extra_actual_turn_counts_and_skipped_slot_does_not(self):
        g=self.game((ROOT,P+'extra',P+'skip'));source=self.play(g,ROOT);self.play(g,P+'extra')
        g.apply(EndTurn(1));self.assertEqual((g.state.active_player,g.state.entities[source].quest_progress.value),(1,1))
        self.play(g,P+'skip');g.apply(EndTurn(1))
        self.assertEqual((g.state.active_player,g.state.entities[source].quest_progress.value),(1,2))

    def test_b01_real_paid_reward_distributes_two_distinct_hand_cards_and_all_other_seven(self):
        g=self.game((REWARD,));old_deck=set(g.state.players[1].deck);source=self.play(g,REWARD)
        event=next(e for e in g.events if e.kind==SPLIT_ACCEPTED);data=dict(event.data)
        self.assertEqual(g.state.players[1].mana,25);self.assertEqual(len(data['selected']),2)
        self.assertEqual(len(set(data['selected'])),2);self.assertEqual(set(data['selected'])|set(data['remainder']),set(REWARDS))
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],list(data['selected']))
        added=[g.state.entities[i].card_id for i in g.state.players[1].deck if i not in old_deck]
        self.assertCountEqual(added,data['remainder']);self.assertEqual(len(added),7)
        operations=[x for x in g.state.deck_shuffle_history if x.source and x.source.entity_id==source]
        self.assertEqual(len(operations),1);self.assertEqual(operations[0].declared_count,7)
        self.portable(g)

    def test_b02_naturally_summoned_reward_does_not_execute_battlecry(self):
        r=registry();self.mode='plain'
        g=Game.from_scenario(Scenario((PlayerSetup(P+'hero',board=(REWARD,)),PlayerSetup(P+'hero'))),r)
        self.assertFalse(any(e.kind==SPLIT_ACCEPTED for e in g.events));self.assertFalse(g.state.players[1].hand)

    def test_b03_full_hand_burn_does_not_move_selected_reward_into_deck_remainder(self):
        g=self.game((REWARD,)+(FILLER,)*9);self.play(g,REWARD)
        data=dict(next(e for e in g.events if e.kind==SPLIT_ACCEPTED).data)
        selected=tuple(data['selected']);self.assertTrue(any(g.state.entities[i].card_id==selected[1]for i in g.state.players[1].graveyard))
        generated_deck=[g.state.entities[i].card_id for i in g.state.players[1].deck if g.state.entities[i].card_id in REWARDS]
        self.assertCountEqual(generated_deck,data['remainder']);self.assertFalse(set(selected)&set(generated_deck))
        self.assertFalse(g.state.quest_hand_rewards)

    def test_b04_first_delivery_wait_preserves_original_split_and_bad_resume_rolls_back(self):
        g=self.game((REWARD,),mode='splitwait');self.play(g,REWARD);original=g.snapshot();restored=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),original)
        while g.state.pending_choice:self.choose(g)
        while restored.state.pending_choice:self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(sum(e.kind==SPLIT_ACCEPTED for e in g.events),1)

    def test_b05_direct_delivery_error_rolls_back_paid_source_partition_rng_and_all_cards(self):
        g=self.game((REWARD,),mode='splitfail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,REWARD)
        self.assertEqual(g.snapshot(),before)

    def test_b06_fully_rehashed_closed_candidate_crop_is_rejected(self):
        g=self.game((REWARD,));self.play(g,REWARD);snap=g.snapshot()
        event=next(e for e in snap['events']if e['kind']==SPLIT_ACCEPTED)
        event['data']['candidates']=event['data']['candidates'][:-1];self.rehash(snap)
        with self.assertRaises(SnapshotError):Game.from_snapshot(snap,registry())

    def test_c01_time_warp_schedules_one_real_extra_turn_and_survives_source_retirement(self):
        g=self.game((WARP,));source=self.play(g,WARP)
        self.assertEqual(g.state.players[1].mana,25);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.turn_schedule.pending,(1,));g.apply(EndTurn(1))
        self.assertEqual(g.state.active_player,1);g.apply(EndTurn(1));self.assertEqual(g.state.active_player,2)
        self.portable(g)

    def test_c02_two_physical_warps_share_one_game_limit_and_second_still_pays(self):
        g=self.game((WARP,WARP));a=self.play(g,WARP);b=self.play(g,WARP)
        self.assertNotEqual(a,b);self.assertEqual(g.state.players[1].mana,20)
        self.assertEqual(g.state.turn_schedule.pending,(1,));self.assertEqual(sum(e.kind=='turns_scheduled'for e in g.events),1)
        self.assertEqual(sum(x.spec_id==WARP_USED for x in g.state.players[1].player_effects),1)

    def test_c03_players_have_independent_once_game_limits(self):
        g=self.game((WARP,),other_hand=(WARP,));self.play(g,WARP);g.apply(EndTurn(1));g.apply(EndTurn(1))
        self.play(g,WARP);self.assertEqual(g.state.turn_schedule.pending,(2,))
        self.assertTrue(all(any(x.spec_id==WARP_USED for x in p.player_effects)for p in g.state.players.values()))

    def test_c04_wait_restore_and_failed_resume_preserve_original_once_marker_and_turn(self):
        g=self.game((WARP,),mode='warpwait');self.play(g,WARP);before=g.snapshot();restored=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());g.apply(EndTurn(1));self.assertEqual(g.state.active_player,1)

    def test_d01_core_changes_existing_hand_deck_board_and_clears_old_board_modifiers_damage(self):
        g=self.game((P+'buff',P+'hurt',CORE,SMALL),board=(SMALL,),deck=(LARGE,));eid=g.state.players[1].board[0]
        self.play(g,P+'buff',eid);self.play(g,P+'hurt',eid);self.assertEqual(self.stats(g,eid),(4,3,6))
        self.play(g,CORE);self.assertEqual(self.stats(g,eid),(5,5,5))
        for i in g.state.players[1].hand+g.state.players[1].deck:self.assertEqual(self.stats(g,i),(5,5,5))
        self.assertTrue(any(x.spec_id==BASE_PROGRAM for x in g.state.players[1].player_effects));self.portable(g)

    def test_d02_core_survives_silence_and_old_base_does_not_reapply_over_new_set(self):
        g=self.game((CORE,P+'buff',P+'silence',P+'set'),board=(SMALL,));eid=g.state.players[1].board[0]
        self.play(g,CORE);self.play(g,P+'buff',eid);self.assertEqual(self.stats(g,eid),(8,9,9))
        self.play(g,P+'silence',eid);self.assertEqual(self.stats(g,eid),(5,5,5))
        self.play(g,P+'set',eid);self.assertEqual(self.stats(g,eid),(1,1,1))

    def test_d03_transferred_minion_keeps_accepted_base_for_player_without_program(self):
        g=self.game((CORE,),board=(SMALL,),other_hand=(P+'steal',P+'silence'));eid=g.state.players[1].board[0]
        self.play(g,CORE);g.apply(EndTurn(1));self.play(g,P+'steal',eid);self.play(g,P+'silence',eid)
        self.assertEqual((g.state.entities[eid].controller,self.stats(g,eid)),(2,(5,5,5)))
        self.assertFalse(g.state.players[2].player_effects)

    def test_d04_controlled_transform_and_new_summon_use_bases_before_ordinary_notification(self):
        g=self.game((CORE,P+'transform',P+'summon'),board=(SMALL,));eid=g.state.players[1].board[0]
        self.play(g,CORE);self.play(g,P+'transform',eid);self.assertEqual(g.state.entities[eid].card_id,LARGE)
        self.assertEqual(self.stats(g,eid),(5,5,5));self.play(g,P+'summon')
        self.assertEqual(self.stats(g,g.state.players[1].board[-1]),(5,5,5))

    def test_d05_explicit_copy_and_creation_one_one_operands_override_program_base(self):
        g=self.game((CORE,P+'copy',P+'make'),board=(LARGE,));eid=g.state.players[1].board[0]
        self.play(g,CORE);self.play(g,P+'copy',eid);copy=g.state.players[1].board[-1]
        self.assertNotEqual(eid,copy);self.assertEqual(self.stats(g,copy),(1,1,1))
        self.play(g,P+'make');created=g.state.players[1].hand[-1];self.assertEqual(self.stats(g,created),(1,1,1))
        self.play(g,SMALL);self.assertEqual(self.stats(g,created),(1,1,1))

    def test_d06_bounce_preserves_original_base_but_discards_normal_buff(self):
        g=self.game((CORE,P+'buff',P+'bounce'),board=(SMALL,));eid=g.state.players[1].board[0]
        self.play(g,CORE);self.play(g,P+'buff',eid);self.play(g,P+'bounce',eid)
        self.assertEqual((g.state.entities[eid].zone,self.stats(g,eid)),(Zone.HAND,(5,5,5)))
        self.assertEqual(self.play(g,SMALL),eid);self.assertEqual(self.stats(g,eid),(5,5,5))

    def test_d07_core_observer_wait_restores_typed_base_and_bad_resume_rolls_back(self):
        g=self.game((CORE,),board=(SMALL,),mode='corewait');self.play(g,CORE);before=g.snapshot();restored=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_d08_direct_core_failure_rolls_back_program_original_stats_damage_and_payment(self):
        g=self.game((P+'hurt',CORE),board=(LARGE,),mode='corefail');eid=g.state.players[1].board[0]
        self.play(g,P+'hurt',eid);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CORE)
        self.assertEqual(g.snapshot(),before)

    def test_d09_fully_rehashed_missing_program_acceptance_and_changed_base_are_rejected(self):
        g=self.game((CORE,),board=(SMALL,));self.play(g,CORE)
        for change in('receipt','stats'):
            snap=g.snapshot()
            if change=='receipt':snap['events']=[e for e in snap['events']if e['kind']!=BASE_ACCEPTED]
            else:
                e=snap['state']['entities'][str(g.state.players[1].board[0])]
                next(x for x in e['enchantments']if x['minion_base_stats']is not None)['minion_base_stats']['attack']=4
            self.rehash(snap)
            with self.assertRaises(SnapshotError):Game.from_snapshot(snap,registry())

    def test_d10_one_time_board_reset_heals_damage_larger_than_new_base_without_false_death(self):
        g=self.game((P+'hurt',P+'hurt',CORE),board=(LARGE,));eid=g.state.players[1].board[0]
        self.play(g,P+'hurt',eid);self.play(g,P+'hurt',eid)
        self.assertEqual(self.stats(g,eid),(8,3,9));self.play(g,CORE)
        self.assertEqual((g.state.entities[eid].zone,self.stats(g,eid)),(Zone.BOARD,(5,5,5)))

    def test_e01_private_material_stays_out_of_views_and_terminal_does_not_deliver_new_work(self):
        g=self.game((REWARD,CORE));self.play(g,REWARD);self.play(g,CORE)
        for pid in(1,2):
            view=json.dumps(g.observe(pid),ensure_ascii=False,default=str)
            for private in(SPLIT_ACCEPTED,BASE_ACCEPTED,'rng_before','minion_base_stats'):
                self.assertNotIn(private,view)
        g.apply(Concede(1));self.assertEqual(g.state.status,'finished');self.portable(g)


if __name__=='__main__':unittest.main()
