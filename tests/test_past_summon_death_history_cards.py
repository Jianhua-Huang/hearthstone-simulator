"""Real entry points and shared history/lifecycle boundaries for three leaves."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards.past_summon_death_history_cards import (
    AUTOMATON, SPEAKER, SLEEPER, load_batch, register_past_summon_death_history_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, Keyword, PlayerSetup, Scenario, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant, deaths_since_installation
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Destroy,
    DestroyBatch, GrantKeyword, InvokeBehavior, RequestChoice, ReturnToHand, SetStats,
    Silence, Summon, SwapStats, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec, StatRelationOperand, StatRelationSpec
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.successful_summons import other_self_summon_count, successful_reborns

P='k485.'
FODDER, REBORN, RETAINED, SUMMONER, WATCH=(P+x for x in('fodder','reborn-body','retained','summoner','watch'))
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=defaults();register_past_summon_death_history_cards(r);r._version=P+mode
    r.register_card(CardDefinition(FODDER,FODDER,CardType.MINION,attack=1,health=1,metadata=META))
    r.register_card(CardDefinition(REBORN,REBORN,CardType.MINION,attack=2,health=4,
        keywords=(Keyword.REBORN,),metadata=META))
    r.register_card(CardDefinition(RETAINED,RETAINED,CardType.MINION,attack=3,health=4,
        keywords=(Keyword.REBORN,),reborn_policy='full_health_enchantments',metadata=META))
    r.register_behavior(SUMMONER,lambda c:(Summon(c.player_id,SLEEPER),))
    r.register_card(CardDefinition(SUMMONER,SUMMONER,CardType.MINION,health=1,deathrattle=SUMMONER,metadata=META))
    def fail(c):raise ResolutionError('K485 deliberate late failure')
    r.register_behavior(P+'fail',fail)
    def last(c,other=False):
        pid=3-c.player_id if other else c.player_id
        target=next(i for i in reversed(c.state.players[pid].board)if c.state.entities[i].card_id==FODDER)
        return(Destroy(target,c.source_id),)
    r.register_behavior(P+'last-own',last)
    r.register_behavior(P+'last-enemy',lambda c:last(c,True))
    targeted={'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'buff':lambda c:(Buff(c.target_id,2,3,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'give':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'morph':lambda c:(Transform(c.target_id,AUTOMATON),),
        'set':lambda c:(SetStats(c.target_id,1,1,c.source_id),),
        'swap':lambda c:(SwapStats(c.target_id,c.source_id),),
        'reborn':lambda c:(GrantKeyword(c.target_id,Keyword.REBORN,c.source_id),),
        'sleep':lambda c:(MakeDormant(c.target_id,None,c.source_id),),
        'wake':lambda c:(AwakenMinion(c.target_id,c.source_id),)}
    def batch_death(c):
        return(DestroyBatch(tuple(i for p in c.state.players.values()for i in p.board
            if c.state.entities[i].active and c.state.entities[i].kind==CardType.MINION),c.source_id),)
    scripts=dict(targeted,**{'one-own':lambda c:(Summon(c.player_id,FODDER),
            InvokeBehavior(P+'last-own',c.source_id,c.player_id)),
        'one-enemy':lambda c:(Summon(3-c.player_id,FODDER),InvokeBehavior(P+'last-enemy',c.source_id,c.player_id)),
        'batch':batch_death,'spawn-auto':lambda c:(Summon(c.player_id,AUTOMATON),)})
    for key,body in scripts.items():
        r.register_behavior(P+key,body)
        r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,metadata=META,
            targeting=TargetSpec()if key in targeted else None))
    def eligible(c):
        if mode=='reborn_wait':return c.event.target_id!=c.source_id
        if mode=='death_wait':return len(c.state.death_history)>=7
        if mode=='wake_fail':return c.state.entities[c.event.target_id].card_id==SLEEPER
        if mode=='copy_fail':return dict(c.event.data).get('copied_from')is not None
        return (c.state.entities[c.event.target_id].card_id==AUTOMATON and
            sum(x.card_id==AUTOMATON for x in c.state.successful_summon_history)>=2)
    def watch(c):
        if mode in('wake_fail','copy_fail','second_fail'):return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        target=c.event.target_id
        options=(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',
            (InvokeBehavior(P+'fail',c.source_id,c.player_id),)))
        if mode=='reborn_wait':options=(*options,
            ChoiceOption('buff','Buff',(Buff(target,2,3,c.source_id),)),
            ChoiceOption('bounce','Bounce',(ReturnToHand(target),)))
        return(RequestChoice(c.player_id,options,c.source_id),)
    event=('minion_reborn'if mode=='reborn_wait'else'minion_died'if mode=='death_wait'
        else'minion_awakened'if mode=='wake_fail'else'minion_summoned')
    r.register_trigger_condition(P+'eligible',eligible);r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=9,metadata=META,
        limited_triggers=(LimitedTriggerSpec(event,WATCH,condition_id=P+'eligible'),)))
    r.validate();return r


def rehash(value):
    value['events_hash']=canonical_hash(value['events'])
    value['state_hash']=canonical_hash({k:v for k,v in value.items()if k not in
        ('schema_version','events','events_hash','state_hash')})
    return value


class PastSummonDeathHistoryTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)

    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),mode='normal'):
        self.mode=mode
        if mode!='normal':board=(WATCH,*board)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,
            deck=(FODDER,)*12,mana=40,max_mana=40,mana_cap=40),PlayerSetup('HERO_08',board=enemy,
            hand=enemy_hand,deck=(FODDER,)*12,mana=40,max_mana=40,mana_cap=40)),seed=485),fixture(mode),
            ruleset=Ruleset(max_hand=40))

    def stats(self,g,eid,attack,health,remaining=None):
        e=g.state.entities[eid];self.assertEqual((e.attack,e.max_health),(attack,health))
        if remaining is not None:self.assertEqual(e.health,remaining)

    def deaths(self,g,n,other=False):
        for _ in range(n):self.play(g,P+('one-enemy'if other else'one-own'))

    def hand_deaths(self,n,other=False):return(P+('one-enemy'if other else'one-own'),)*n

    def progress(self,g,source):
        state=g.state
        return deaths_since_installation(state,fixture(self.mode),state.entities[source])

    def test_complete_three_rows_six_faces_and_real_metadata(self):
        d=load_batch();self.assertEqual((len(d['dependencies']),len(d['official_observations'])),(3,6))
        rows={x['record']['id']:x['record']for x in d['dependencies']}
        for face in d['official_observations']:
            self.assertEqual(batch.sha(face['response_file']),face['response_sha256'])
            batch.check_face(rows[face['card_id']],face['face'],face['locale'])
        r=build_registry();self.assertTrue(all(cid in r.cards for cid in rows))
        self.assertEqual(r.card(SPEAKER).metadata.runes.unholy,1)
        self.assertEqual(r.card(AUTOMATON).metadata.tribes,('mech',));self.assertFalse(d['cn_calibrated'])

    def test_sleep_counts_both_players_only_after_original_installation(self):
        g=self.game((SLEEPER,*self.hand_deaths(3),*self.hand_deaths(4,True)))
        source=self.play(g,SLEEPER);birth=g.state.entities[source].board_presence_id
        self.deaths(g,3);self.deaths(g,3,True);self.assertIsNotNone(g.state.entities[source].dormancy)
        self.deaths(g,1,True);self.assertIsNone(g.state.entities[source].dormancy)
        self.assertEqual(g.state.entities[source].board_presence_id,birth)
        self.assertEqual(sum(e.kind=='minion_awakened'for e in g.events),1);self.stats(g,source,3,5)

    def test_preexisting_deaths_do_not_advance_new_dormancy(self):
        g=self.game((*self.hand_deaths(7),SLEEPER,*self.hand_deaths(7)))
        self.deaths(g,7);source=self.play(g,SLEEPER)
        self.assertEqual(self.progress(g,source),0)
        self.deaths(g,6);self.assertIsNotNone(g.state.entities[source].dormancy)
        self.deaths(g,1);self.assertIsNone(g.state.entities[source].dormancy)

    def test_simultaneous_seven_minion_deaths_awaken_once(self):
        g=self.game((P+'batch',),board=(SLEEPER,*(FODDER,)*6),enemy=(FODDER,))
        source=self.entity(g,SLEEPER,zone='board').id;self.play(g,P+'batch')
        self.assertEqual(len(g.state.death_history),7);self.assertEqual(len({d.batch for d in g.state.death_history}),1)
        self.assertIsNone(g.state.entities[source].dormancy)
        self.assertEqual(sum(e.kind=='minion_awakened'for e in g.events),1)

    def test_deathrattle_created_sleeper_excludes_its_producers_death(self):
        g=self.game((P+'kill',*self.hand_deaths(7)),board=(SUMMONER,))
        self.play(g,P+'kill',self.entity(g,SUMMONER,zone='board').id)
        source=self.entity(g,SLEEPER,zone='board').id
        self.assertEqual(g.state.entities[source].dormancy.first_death_id,g.state.next_death_id)
        self.assertEqual(self.progress(g,source),0)
        self.deaths(g,7);self.assertIsNone(g.state.entities[source].dormancy)

    def test_new_dormancy_on_same_physical_source_starts_a_new_boundary(self):
        g=self.game((SLEEPER,*self.hand_deaths(7),P+'sleep',*self.hand_deaths(7)))
        source=self.play(g,SLEEPER);original=g.state.entities[source].dormancy.id
        self.deaths(g,7);self.play(g,P+'sleep',source)
        self.assertNotEqual(g.state.entities[source].dormancy.id,original)
        self.assertEqual(self.progress(g,source),0)
        self.deaths(g,6);self.assertIsNotNone(g.state.entities[source].dormancy)
        self.deaths(g,1);self.assertIsNone(g.state.entities[source].dormancy)

    def test_two_physical_dormant_sources_keep_distinct_installation_boundaries(self):
        g=self.game((SLEEPER,*self.hand_deaths(3),SLEEPER,*self.hand_deaths(7)))
        first=self.play(g,SLEEPER);self.deaths(g,3);second=self.play(g,SLEEPER);self.deaths(g,4)
        self.assertIsNone(g.state.entities[first].dormancy);self.assertIsNotNone(g.state.entities[second].dormancy)
        self.deaths(g,3);self.assertIsNone(g.state.entities[second].dormancy)

    def test_indefinite_sleep_does_not_count_turn_starts(self):
        g=self.game((SLEEPER,));source=self.play(g,SLEEPER)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertIsNotNone(g.state.entities[source].dormancy)

    def test_seventh_death_wait_restores_then_awakes_without_recount(self):
        g=self.game((SLEEPER,*self.hand_deaths(7)),mode='death_wait');source=self.play(g,SLEEPER)
        self.deaths(g,7);self.assertIsNotNone(g.state.pending_choice);self.assertIsNotNone(g.state.entities[source].dormancy)
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertIsNone(g.state.entities[source].dormancy)

    def test_late_awaken_failure_rolls_back_seventh_death_and_original_instance(self):
        g=self.game((SLEEPER,*self.hand_deaths(7)),mode='wake_fail');self.play(g,SLEEPER);self.deaths(g,6)
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.deaths(g,1)
        self.assertEqual(g.snapshot(),saved)

    def test_boolean_and_future_dormancy_death_cursor_are_rejected(self):
        g=self.game((SLEEPER,));source=self.play(g,SLEEPER)
        for value in(True,g.state.next_death_id+1):
            bad=deepcopy(g.snapshot());bad['state']['entities'][str(source)]['dormancy']['first_death_id']=value
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('normal','reader'))

    def test_each_actual_automaton_entry_updates_all_existing_sources(self):
        g=self.game((AUTOMATON,)*3);ids=[]
        for size in range(1,4):
            ids.append(self.play(g,AUTOMATON))
            for eid in ids:self.stats(g,eid,size,size+1)
        self.assertEqual([(x.entry_attack,x.entry_max_health)for x in g.state.successful_summon_history],[(1,2),(2,3),(3,4)])

    def test_current_copy_preserves_local_buff_but_recomputes_one_history_contribution(self):
        g=self.game((AUTOMATON,P+'buff',P+'copy'));source=self.play(g,AUTOMATON)
        self.play(g,P+'buff',source);self.play(g,P+'copy',source)
        ids=[i for i in g.state.players[1].board if g.state.entities[i].card_id==AUTOMATON]
        self.assertEqual(len(ids),2)
        for eid in ids:self.stats(g,eid,4,6)
        self.portable(g)

    def test_reborn_adds_actual_summon_then_uses_original_one_health_policy(self):
        g=self.game((AUTOMATON,AUTOMATON,P+'reborn',P+'kill'))
        source=self.play(g,AUTOMATON);other=self.play(g,AUTOMATON)
        self.play(g,P+'reborn',source);self.play(g,P+'kill',source)
        row=successful_reborns(g.state,1)[0];self.stats(g,row.entity_id,3,4,1);self.stats(g,other,3,4)
        self.assertEqual(len(g.state.successful_summon_history),3)

    def test_same_entity_reentry_counts_past_occurrence_but_excludes_current_one(self):
        g=self.game((AUTOMATON,AUTOMATON,P+'bounce'));source=self.play(g,AUTOMATON);other=self.play(g,AUTOMATON)
        self.play(g,P+'bounce',source);self.assertEqual(self.play(g,AUTOMATON),source)
        self.stats(g,source,3,4);self.stats(g,other,3,4)
        state=g.state;self.assertEqual(other_self_summon_count(state,state.entities[source]),2)

    def test_silence_removes_native_contribution_and_later_growth(self):
        g=self.game((AUTOMATON,AUTOMATON,P+'silence',AUTOMATON))
        source=self.play(g,AUTOMATON);other=self.play(g,AUTOMATON);self.play(g,P+'silence',source)
        self.stats(g,source,1,2);self.play(g,AUTOMATON);self.stats(g,source,1,2);self.stats(g,other,3,4)

    def test_set_stats_keeps_continuous_contribution_outside_local_modifier(self):
        g=self.game((AUTOMATON,AUTOMATON,P+'set'));source=self.play(g,AUTOMATON);self.play(g,AUTOMATON)
        self.play(g,P+'set',source);self.stats(g,source,2,2)

    def test_swap_reads_visible_attributes_then_continuous_contribution_remains(self):
        g=self.game((AUTOMATON,AUTOMATON,P+'swap'));source=self.play(g,AUTOMATON);self.play(g,AUTOMATON)
        self.play(g,P+'swap',source);self.stats(g,source,4,3)

    def test_control_change_uses_new_controller_without_rewriting_original_summons(self):
        g=self.game((AUTOMATON,AUTOMATON,P+'give'));source=self.play(g,AUTOMATON);other=self.play(g,AUTOMATON)
        self.play(g,P+'give',source);self.stats(g,source,1,2);self.stats(g,other,2,3)
        self.assertTrue(all(x.player_id==1 for x in g.state.successful_summon_history))

    def test_transform_into_automaton_reads_other_history_without_new_summon(self):
        g=self.game((AUTOMATON,AUTOMATON,P+'morph'),board=(FODDER,))
        self.play(g,AUTOMATON);self.play(g,AUTOMATON);target=self.entity(g,FODDER,zone='board').id
        self.play(g,P+'morph',target);self.stats(g,target,3,4);self.assertEqual(len(g.state.successful_summon_history),2)

    def test_first_entry_listener_sees_complete_new_history_and_attributes(self):
        g=self.game((AUTOMATON,AUTOMATON),mode='summon_wait');first=self.play(g,AUTOMATON);second=self.play(g,AUTOMATON)
        self.stats(g,first,2,3);self.stats(g,second,2,3);other=self.portable(g)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())

    def test_failed_entry_action_restores_history_and_existing_native_attributes(self):
        g=self.game((AUTOMATON,AUTOMATON),mode='second_fail');self.play(g,AUTOMATON);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,AUTOMATON)
        self.assertEqual(g.snapshot(),saved)

    def test_failed_full_board_summon_does_not_increase_native_count(self):
        g=self.game((P+'spawn-auto',),board=(AUTOMATON,*(FODDER,)*6));source=self.entity(g,AUTOMATON,zone='board').id
        self.play(g,P+'spawn-auto');self.stats(g,source,1,2);self.assertFalse(g.state.successful_summon_history)

    def test_death_speaker_copies_actual_reborn_material_without_reborn_classification(self):
        g=self.game((P+'kill',),board=(SPEAKER,REBORN));self.play(g,P+'kill',self.entity(g,REBORN,zone='board').id)
        ids=[i for i in g.state.players[1].board if g.state.entities[i].card_id==REBORN]
        self.assertEqual(len(ids),2);self.assertEqual(len(successful_reborns(g.state,1)),1)
        for eid in ids:self.stats(g,eid,2,4,1);self.assertNotIn(Keyword.REBORN,g.state.entities[eid].keywords)

    def test_enemy_reborn_and_original_creators_own_reborn_are_excluded(self):
        g=self.game((P+'kill',),board=(SPEAKER,),enemy=(REBORN,));self.play(g,P+'kill',self.entity(g,REBORN,2,'board').id)
        self.assertEqual(len(g.state.players[1].board),1)
        g=self.game((P+'reborn',P+'kill'),board=(SPEAKER,));source=self.entity(g,SPEAKER,zone='board').id
        self.play(g,P+'reborn',source);self.play(g,P+'kill',source);self.assertEqual(len(g.state.players[1].board),1)

    def test_silenced_or_dead_observer_does_not_watch_later_reborn(self):
        for operation in('silence','kill'):
            with self.subTest(operation=operation):
                g=self.game((P+operation,P+'kill'),board=(SPEAKER,REBORN))
                self.play(g,P+operation,self.entity(g,SPEAKER,zone='board').id)
                self.play(g,P+'kill',self.entity(g,REBORN,zone='board').id)
                self.assertEqual(sum(g.state.entities[i].card_id==REBORN for i in g.state.players[1].board),1)

    def test_two_independent_speakers_each_copy_once_and_full_board_is_normal_failure(self):
        g=self.game((P+'kill',),board=(SPEAKER,SPEAKER,REBORN));self.play(g,P+'kill',self.entity(g,REBORN,zone='board').id)
        self.assertEqual(sum(g.state.entities[i].card_id==REBORN for i in g.state.players[1].board),3)
        g=self.game((P+'kill',),board=(SPEAKER,*(FODDER,)*5,REBORN));self.play(g,P+'kill',self.entity(g,REBORN,zone='board').id)
        self.assertEqual(sum(g.state.entities[i].card_id==REBORN for i in g.state.players[1].board),1)

    def test_full_health_retained_reborn_copy_does_not_force_one_health(self):
        g=self.game((P+'buff',P+'kill'),board=(SPEAKER,RETAINED));source=self.entity(g,RETAINED,zone='board').id
        self.play(g,P+'buff',source);self.play(g,P+'kill',source)
        ids=[i for i in g.state.players[1].board if g.state.entities[i].card_id==RETAINED]
        self.assertEqual(len(ids),2)
        for eid in ids:self.stats(g,eid,5,7,7)

    def test_reborn_wait_uses_current_original_material_and_stale_reference_skips(self):
        for option in('buff','bounce'):
            with self.subTest(option=option):
                g=self.game((P+'kill',),board=(SPEAKER,REBORN),mode='reborn_wait')
                self.play(g,P+'kill',self.entity(g,REBORN,zone='board').id);other=self.portable(g)
                self.choose(g,option);self.choose(other,option);self.assertEqual(g.snapshot(),other.snapshot())
                ids=[i for i in g.state.players[1].board if g.state.entities[i].card_id==REBORN]
                self.assertEqual(len(ids),2 if option=='buff'else 0)
                if option=='buff':
                    for eid in ids:self.stats(g,eid,4,7,4)

    def test_copy_reaction_failure_rolls_back_original_death_reborn_and_copy(self):
        g=self.game((P+'kill',),board=(SPEAKER,REBORN),mode='copy_fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'kill',self.entity(g,REBORN,zone='board').id)
        self.assertEqual(g.snapshot(),saved)

    def test_native_relation_is_finite_and_private_cursors_stay_host_only(self):
        with self.assertRaises(ValueError):StatRelationSpec(operand=StatRelationOperand.CONTROLLER_OTHER_SELF_SUMMON_COUNT,amount=2)
        self.assertEqual(defaults().fingerprint(),'b2167d3328df10bb4336983812adfd12220d2644b7bcc86b517f5e335028eb4a')
        g=self.game((SLEEPER,AUTOMATON));self.play(g,SLEEPER);self.play(g,AUTOMATON)
        for pid in(1,2):
            text=json.dumps(g.observe(pid))+json.dumps(g.player_events(pid))
            for private in('"first_death_id"','"successful_summon_history"','"stat_relations"'):self.assertNotIn(private,text)
