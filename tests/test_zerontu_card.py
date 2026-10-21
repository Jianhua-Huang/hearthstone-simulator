"""Real Zer'Ontu, exact physical recruit groups and ordinary original reward."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from hs_sim.cards.zerontu_card import CARD, load_batch, register_zerontu_card
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.card_creation import CreatedMinionStats
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, Destroy, GainArmor,
    InvokeBehavior, RequestChoice, ReturnToHand, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (AppendageSpec, BattlecryRepeatSpec, CardClass, CardMetadata, Rarity,
    SummonQuantitySpec, SummonStats)
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.recruit_stat_groups import ACCEPTED, SLOT, REWARD, FINISHED
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.zones import AddToDeck, CardReference
from tools.card_batch import canonical, check_face

P='fixture.zerontu.'
ZERO,ONE,TWO,AUX,DOUBLE,REPEAT,WATCH,SEED,SUMMON=(P+x for x in
    ('zero','one','two','aux','double','repeat','watch','seed','summon'))
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
COLOSSAL=P+'colossal'; DORMANT=P+'dormant'


@lru_cache(maxsize=None)
def fixture(mode=None,role='writer'):
    if role not in('writer','reader'):raise ValueError('Independent registry role required')
    r=build_registry();register_zerontu_card(r)
    r.register_behavior(P+'cry',lambda c:(GainArmor(c.player_id,100),))
    r.register_behavior(P+'death',lambda c:(GainArmor(c.player_id,2),))
    r.register_card(CardDefinition(COLOSSAL,COLOSSAL,CardType.MINION,attack=0,health=4,
        colossal=(AppendageSpec(AUX),),keywords=(Keyword.COLOSSAL,),metadata=META))
    r.register_card(CardDefinition(DORMANT,DORMANT,CardType.MINION,attack=0,health=4,dormant_turns=2,metadata=META))
    for cid,a,h,kw in((ZERO,0,4,{}),(ONE,1,5,dict(battlecry=P+'cry')),
            (TWO,2,6,dict(deathrattle=P+'death')),(AUX,9,20,{}),
            (DOUBLE,0,20,dict(summon_quantities=(SummonQuantitySpec(2,(CardType.MINION,)),))),
            (REPEAT,0,20,dict(battlecry_repeats=(BattlecryRepeatSpec(),)))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=6,attack=a,health=h,metadata=META,**kw))
    def fail(c):raise ResolutionError('Zerontu deliberate late failure')
    r.register_behavior(P+'fail',fail)
    r.register_behavior(P+'reenter',lambda c:(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id),))
    r.register_behavior(P+'seed',lambda c:tuple(AddToDeck(c.player_id,cid,position='bottom',source_id=c.source_id,
        minion_stats=CreatedMinionStats(set_to=SummonStats(a,7)))for cid,a in((ZERO,1),(ONE,0))))
    r.register_card(CardDefinition(SEED,SEED,CardType.SPELL,on_play=P+'seed'))
    r.register_behavior(P+'summon',lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(CARD),),SummonCause.capture(c)),))
    r.register_card(CardDefinition(SUMMON,SUMMON,CardType.SPELL,on_play=P+'summon'))
    r.register_behavior(P+'recruit',lambda c:(SummonFromZone(c.player_id,query=PoolQuery(attack_equals=0),
        source_id=c.source_id,cause=SummonCause.capture(c)),))
    r.register_card(CardDefinition(P+'recruit',P+'recruit',CardType.SPELL,on_play=P+'recruit'))
    if mode:
        def watch(c):
            target=c.state.entities[c.event.target_id]
            if mode=='wait_reward':
                if target.card_id!=CARD:return()
            elif target.card_id not in ((ZERO,ONE,TWO)if mode=='wait_each'else(ZERO,)):
                return()
            source=next(e for e in c.state.entities.values()if e.card_id==CARD and e.zone==Zone.BOARD)
            if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode=='kill':return(Destroy(target.id,c.source_id),)
            if mode=='transform':return(Transform(target.id,AUX),)
            if mode=='give':return(ChangeControl(target.id,2),)
            if mode=='buff':return(Buff(target.id,5,5,c.source_id),)
            if mode=='kill_source':return(Destroy(source.id,c.source_id),)
            if mode=='give_source':return(ChangeControl(source.id,2),)
            if mode=='transform_source':return(Transform(source.id,AUX),)
            if mode=='reenter_source':return(ReturnToHand(source.id),InvokeBehavior(P+'reenter',c.source_id,1,source.id))
            if mode=='nested':
                cause=next(row.spec.cause for row in reversed(c.state.recruit_summon_history)if row.spec.query.attack_equals==0)
                return(SummonFromZone(1,query=PoolQuery(attack_equals=9),source_id=cause.source.entity_id,
                    cause=cause,attack_basis='current'),)
            return(RequestChoice(2,(ChoiceOption('ok','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
            triggers=(TriggerSpec('stats_changed'if mode=='wait_reward'else'minion_summoned',P+'watch'),)))
    return r


class ZerontuCardTests(unittest.TestCase):
    def game(self,mode=None,*,deck=(ZERO,ONE,TWO),board=(),hand=(CARD,),seat=1):
        self.mode=mode;self.seat=seat
        own=PlayerSetup('HERO_09',hand=hand,deck=deck,board=((WATCH,)if mode else())+board,mana=10,max_mana=10)
        other=PlayerSetup('HERO_08',mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,seed=366),fixture(mode))
    def play(self,g,cid=CARD):
        i=next(i for i in g.state.players[self.seat].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(self.seat,i));return i
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def stat(self,g,source):
        e=g.state.entities[source];return e.attack,e.health,e.max_health
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=fixture(self.mode,'reader')
        for other in(g.clone(),Game.from_snapshot(s,r),replay(build_replay(g),r)):
            self.assertTrue(other.snapshot()==s,'Exact group, original entry facts and reward must round trip')
        return Game.from_snapshot(s,r)
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()
            if k not in('schema_version','events','events_hash','state_hash')});return s
    def reject(self,g,edit):
        s=deepcopy(g.snapshot());edit(s)
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),fixture(self.mode))

    def test_full_raw_two_primary_faces_and_real_priest_legendary_taunt(self):
        d=load_batch();raw=d['cards'][0]['record'];self.assertEqual(canonical(raw),d['cards'][0]['record_sha256'])
        self.assertEqual({o['locale']for o in d['official_observations']},{'zh_CN','en_US'})
        for o in d['official_observations']:check_face(raw,o['face'],o['locale'])
        c=fixture().card(CARD);self.assertEqual((c.cost,c.attack,c.health),(8,3,3));self.assertIn(Keyword.TAUNT,c.keywords)
        self.assertEqual((c.metadata.classes,c.metadata.rarity),((CardClass.PRIEST,),Rarity.LEGENDARY))

    def test_real_paid_battlecry_recruits_three_originals_then_gains_their_stats_once(self):
        g=self.game();ids=tuple(g.state.players[1].deck);source=self.play(g)
        self.assertEqual(self.stat(g,source),(6,18,18));self.assertEqual(g.state.players[1].mana,2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.assertTrue(all(g.state.entities[i].zone==Zone.BOARD for i in ids))
        self.assertEqual([e.kind for e in g.events if e.kind in(ACCEPTED,SLOT,REWARD,FINISHED)],
            [ACCEPTED,SLOT,SLOT,SLOT,REWARD,FINISHED]);self.portable(g)

    def test_query_order_is_zero_one_two_regardless_of_deck_order(self):
        g=self.game(deck=(TWO,ONE,ZERO));self.play(g)
        self.assertEqual([r.card_id for r in g.state.successful_summon_history if r.card_id in(ZERO,ONE,TWO)],[ZERO,ONE,TWO])

    def test_printed_one_modified_to_zero_uses_current_physical_deck_attack(self):
        g=self.game(deck=(TWO,),hand=(SEED,CARD));self.play(g,SEED);source=self.play(g)
        self.assertEqual(self.stat(g,source),(6,23,23))
        self.assertEqual([r.card_id for r in g.state.successful_summon_history if r.card_id in(ZERO,ONE,TWO)],[ONE,ZERO,TWO])

    def test_missing_zero_does_not_stop_one_and_two_or_add_phantom_stats(self):
        g=self.game(deck=(ONE,TWO));source=self.play(g);self.assertEqual(self.stat(g,source),(6,14,14));self.portable(g)

    def test_empty_deck_accepts_all_three_empty_slots_without_rng_or_buff(self):
        g=self.game(deck=());rng=g._rng.getstate();source=self.play(g)
        self.assertEqual(self.stat(g,source),(3,3,3));self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual([r.status for r in g.state.recruit_summon_history],['exhausted']*3);self.portable(g)

    def test_last_board_slot_only_delivers_zero_and_keeps_other_physical_cards(self):
        g=self.game(board=(AUX,)*5);ids=tuple(g.state.players[1].deck);source=self.play(g)
        self.assertEqual(self.stat(g,source),(3,7,7));self.assertEqual(tuple(g.state.players[1].deck),ids[1:]);self.portable(g)

    def test_full_after_source_keeps_all_hidden_candidates_and_rng(self):
        g=self.game(board=(AUX,)*6);ids=tuple(g.state.players[1].deck);rng=g._rng.getstate();source=self.play(g)
        self.assertEqual(self.stat(g,source),(3,3,3));self.assertEqual(tuple(g.state.players[1].deck),ids)
        self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_quantity_extras_are_real_main_deliveries_with_capacity_per_original_request(self):
        g=self.game(board=(DOUBLE,));source=self.play(g)
        self.assertEqual(self.stat(g,source),(7,27,27));self.assertEqual(len(g.state.players[1].board),7);self.portable(g)

    def test_nested_recruit_with_identical_cause_is_excluded_from_group_reward(self):
        g=self.game('nested',deck=(ZERO,ONE,TWO,AUX));source=self.play(g)
        self.assertEqual(self.stat(g,source),(6,18,18));self.assertEqual(len(g.state.recruit_summon_history),4)
        slots=[dict(e.data)['recruit_id']for e in g.events if e.kind==SLOT]
        self.assertEqual(slots,[1,3,4]);self.portable(g)

    def test_colossal_main_delivery_counts_but_its_separate_appendage_does_not(self):
        for board,expected in (((),(6,18,18)),((DOUBLE,),(4,16,16))):
            with self.subTest(board=board):
                g=self.game(deck=(COLOSSAL,ONE,TWO),board=board);source=self.play(g)
                self.assertEqual(self.stat(g,source),expected)
                self.assertTrue(any(g.state.entities[i].card_id==AUX for i in g.state.players[1].board));self.portable(g)

    def test_old_attributed_printed_recruit_also_uses_native_physical_colossal_entry(self):
        g=self.game(deck=(COLOSSAL,),hand=(P+'recruit',));original=g.state.players[1].deck[0];self.play(g,P+'recruit')
        self.assertEqual(g.state.entities[original].zone,Zone.BOARD)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[COLOSSAL,AUX])
        self.assertFalse(any(e.kind==ACCEPTED for e in g.events));self.portable(g)

    def test_dormant_actual_main_delivery_still_contributes_its_entry_stats(self):
        g=self.game(deck=(DORMANT,ONE,TWO));source=self.play(g)
        self.assertEqual(self.stat(g,source),(6,18,18));self.assertFalse(next(e for e in g.state.entities.values()
            if e.card_id==DORMANT and e.zone==Zone.BOARD).active);self.portable(g)

    def test_entry_death_or_transform_does_not_rewrite_original_entry_operands(self):
        for mode in('kill','transform','give','buff'):
            with self.subTest(mode=mode):
                g=self.game(mode);source=self.play(g);self.assertEqual(self.stat(g,source),(6,18,18));self.portable(g)

    def test_source_death_keeps_later_recruits_and_skips_stale_original_reward(self):
        g=self.game('kill_source');source=self.play(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(len([i for i in g.state.players[1].board if g.state.entities[i].card_id in(ZERO,ONE,TWO)]),3)
        self.portable(g)

    def test_source_transfer_rewards_original_residence_while_recruits_stay_with_original_actor(self):
        g=self.game('give_source');source=self.play(g);self.assertEqual(self.stat(g,source),(6,18,18))
        self.assertEqual(g.state.entities[source].controller,2)
        self.assertTrue(all(g.state.entities[r.selected.entity_id].controller==1 for root in g.state.recruit_summon_history
            for r in root.rounds if r.selected));self.portable(g)

    def test_source_transform_rewards_current_face_in_same_original_residence(self):
        g=self.game('transform_source');source=self.play(g);self.assertEqual(g.state.entities[source].card_id,AUX)
        self.assertEqual(self.stat(g,source),(12,35,35));self.portable(g)

    def test_source_leaves_and_reenters_same_entity_does_not_receive_old_reward(self):
        g=self.game('reenter_source');source=self.play(g);self.assertEqual(self.stat(g,source),(3,3,3));self.portable(g)

    def test_each_entry_wait_restores_exact_partial_group_before_any_final_gain(self):
        g=self.game('wait_each');source=self.play(g)
        for n in range(3):
            self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.stat(g,source),(3,3,3))
            other=self.portable(g);self.choose(g);self.choose(other);self.assertTrue(other.snapshot()==g.snapshot())
        self.assertEqual(self.stat(g,source),(6,18,18));self.portable(g)

    def test_reward_wait_keeps_one_already_applied_buff_and_exact_finish_obligation(self):
        g=self.game('wait_reward');source=self.play(g);self.assertEqual(self.stat(g,source),(6,18,18))
        other=self.portable(g);self.choose(g);self.choose(other);self.assertTrue(other.snapshot()==g.snapshot())
        self.assertEqual(sum(e.kind==REWARD for e in g.events),1);self.portable(g)

    def test_late_entry_failure_rolls_back_payment_rng_physical_zones_and_all_group_receipts(self):
        g=self.game('fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertTrue(g.snapshot()==before)

    def test_failed_entry_or_reward_choice_preserves_wait_and_never_pays_twice(self):
        for mode in('wait_each','wait_reward'):
            with self.subTest(mode=mode):
                g=self.game(mode);source=self.play(g);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.choose(g,'fail')
                self.assertTrue(g.snapshot()==before)
                while g.state.pending_choice:self.choose(g)
                self.assertEqual(g.state.players[1].mana,2);self.assertEqual(self.stat(g,source),(6,18,18))

    def test_effect_summon_does_not_run_battlecry_or_touch_deck(self):
        g=self.game(hand=(SUMMON,));ids=tuple(g.state.players[1].deck);self.play(g,SUMMON)
        self.assertEqual(tuple(g.state.players[1].deck),ids);self.assertFalse(any(e.kind==ACCEPTED for e in g.events));self.portable(g)

    def test_two_real_battlecry_executions_have_disjoint_groups_and_later_capacity(self):
        g=self.game(board=(REPEAT,),deck=(ZERO,ONE,TWO,ZERO,ONE,TWO));source=self.play(g)
        self.assertEqual(sum(e.kind==ACCEPTED for e in g.events),2)
        self.assertEqual(sum(e.kind==FINISHED for e in g.events),2);self.assertEqual(len(g.state.recruit_summon_history),6)
        self.assertEqual(self.stat(g,source),(7,27,27));self.portable(g)

    def test_closed_group_and_operands_survive_later_turn_and_replay(self):
        g=self.game();source=self.play(g);g.apply(EndTurn(1));self.assertEqual(self.stat(g,source),(6,18,18));self.portable(g)

    def test_rehashed_changed_slot_or_reward_is_rejected_in_closed_and_waiting_states(self):
        for mode,kind,key,value in((None,SLOT,'recruit_id',999),(None,REWARD,'health',999),
                ('wait_each',ACCEPTED,'first_recruit',999),('wait_reward',REWARD,'attack',999)):
            with self.subTest(mode=mode,kind=kind):
                g=self.game(mode);self.play(g)
                self.reject(g,lambda s:next(e for e in s['events']if e['kind']==kind)['data'].update({key:value}))

    def test_rehashed_cropped_actual_and_proof_continuation_is_still_rejected(self):
        for mode,suffix in(('wait_each','.ContinueRecruitStatGroup'),('wait_reward','.FinishRecruitStatGroup')):
            with self.subTest(mode=mode):
                g=self.game(mode);self.play(g)
                def edit(s):
                    removed=[]
                    def visit(value):
                        if isinstance(value,list):
                            for item in list(value):
                                if isinstance(item,dict)and str(item.get('type','')).endswith(suffix):
                                    value.remove(item);removed.append(item)
                                else:visit(item)
                        elif isinstance(value,dict):
                            for item in value.values():visit(item)
                    visit(s['resolution_frame']);self.assertEqual(len(removed),2)
                self.reject(g,edit)

    def test_rehashed_missing_group_acceptance_cannot_leave_linked_recruit_orphans(self):
        g=self.game();self.play(g)
        self.reject(g,lambda s:next(e for e in s['events']if e['kind']==ACCEPTED).update(kind='unknown_private_event'))

    def test_private_group_receipts_and_hidden_deck_basis_do_not_enter_either_player_dto(self):
        g=self.game('wait_each',seat=2);self.play(g);before=g.snapshot()
        for pid in(1,2):
            text=json.dumps(g.for_player(pid).observe());g.for_player(pid).legal_actions()
            for key in(ACCEPTED,SLOT,REWARD,FINISHED,'stat_group_id','entry_health','accepted_state'):
                self.assertNotIn(key,text)
        self.assertTrue(g.snapshot()==before)
