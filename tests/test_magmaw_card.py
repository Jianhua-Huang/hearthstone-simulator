"""Actual finite Colossal source, capacity, life cycles and portable continuations."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.magmaw_card import CARD,LIMBS,load_batch
from hs_sim.engine import (AppendageSpec,CardDefinition,CardType,Game,IllegalAction,Keyword,
    EndTurn,PlayCard,PlayerSetup,ResolutionError,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Damage,DamageBatch,Destroy,
    InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.colossal_reserves import ColossalReserveProfile,RESET,SPENT,source
from hs_sim.engine.dormancy import MakeDormant,AwakenMinion
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from tools.card_batch import canonical,check_face

P='fixture.magmaw.';UNIT=P+'unit';WATCH=P+'watch'


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r=build_registry()
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,attack=1,health=5))
    def fail(c):raise ResolutionError('Magmaw fixture failure')
    r.register_behavior(P+'fail',fail)
    def clear(c):
        return (DamageBatch(tuple(Damage(i,1,c.source_id)for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id in LIMBS)),)
    scripts={'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'clear':clear,'wipe':lambda c:(DamageBatch(tuple(Damage(i,50,c.source_id)for i in c.state.players[c.player_id].board)),),
        'silence':lambda c:(Silence(c.target_id),),'bounce':lambda c:(ReturnToHand(c.target_id),),
        'steal':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'base':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        'transform':lambda c:(Transform(c.target_id,CARD),),'plain':lambda c:(Transform(c.target_id,UNIT),),
        'dormant':lambda c:(MakeDormant(c.target_id,2,c.source_id),),
        'wake':lambda c:tuple(AwakenMinion(i,c.source_id)for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD),
        'summon':lambda c:(Summon(c.player_id,CARD),),'latefail':lambda c:(Destroy(c.target_id,c.source_id),InvokeBehavior(P+'fail',c.source_id,c.player_id))}
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,
            requires_target=name not in ('clear','wipe','summon','wake'),target_rule='any_entity'))
    def watch(c):
        event=c.event
        if event.kind=='minion_summoned':
            e=c.state.entities[event.target_id]
            if e.card_id not in LIMBS:return ()
            if mode=='slaughter':return(Silence(e.id),Destroy(e.id,c.source_id))
            if mode=='terminal':return(Damage(c.state.players[1].hero_id,60,c.source_id),)
            records=[x for x in c.state.colossal_history if x.card_id==CARD]
            if mode!='wait_initial' or not records or records[-1].attempted!=1:return ()
        elif event.kind==SPENT:
            if mode not in ('wait_refill','fail_refill')or not c.state.colossal_history or not c.state.colossal_history[-1].completed:return ()
            if mode=='fail_refill':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        else:return ()
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',
            (InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=50,
        triggers=(TriggerSpec('minion_summoned',P+'watch'),TriggerSpec(SPENT,P+'watch'))))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
    return s


class MagmawTests(unittest.TestCase):
    def game(self,hand=(CARD,),board=(),mode='normal',active=1):
        r=fixture(mode);g=Game.from_scenario(Scenario((PlayerSetup('HERO_05',hand=hand if active==1 else (),board=board,
            deck=(UNIT,)*8,max_mana=10,mana=10),PlayerSetup('HERO_08',hand=hand if active==2 else (),
            board=()if mode=='normal'else(WATCH,),deck=(UNIT,)*8,max_mana=10,mana=10)),active_player=active,seed=41),r)
        return g
    def play(self,g,card,target=None,position=None):
        p=g.state.active_player;cid=card if card==CARD else P+card
        i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,i,target,position));return i
    def drain(self,g):
        count=0
        while g.state.pending_choice is not None:
            q=g.state.pending_choice
            self.assertEqual((q.min_count,q.max_count),(0,0))
            g.apply(SelectChoice(q.player_id,q.id,()));count+=1
            self.assertLess(count,110)
        return count
    def bodies(self,g,p=1):return [g.state.entities[i]for i in g.state.players[p].board]
    def limbs(self,g,p=1):return [e for e in self.bodies(g,p)if e.card_id in LIMBS]
    def remaining(self,g,i):return source(g.state.entities[i]).colossal_remaining
    def check(self,g,mode='normal'):
        self.assertEqual(g.clone().snapshot(),g.snapshot())
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())),fixture(mode)).snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),fixture(mode)).snapshot(),g.snapshot())

    def test_complete_sources_reuse_all_six_existing_limb_effects(self):
        d=load_batch();self.assertEqual(len(d['existing_dependencies']),6);self.assertFalse(d['dependencies'])
        self.assertEqual(len(d['official_observations']),14)
        r=fixture();self.assertEqual(len(r.card(CARD).colossal),99)
        self.assertEqual({r.card(i).deathrattle for i in LIMBS},{'cards.simple_followup_p50.body'})
        for row in d['cards']+d['existing_dependencies']+d['evidence_only']:
            self.assertEqual(canonical(row['record']),row['record_sha256'])

    def test_strict_bilingual_full_counter_faces_cannot_drop_a_rule_body(self):
        d=load_batch();row=d['cards'][0]['record'];decl={'@':'','{0}':''}
        for o in d['official_observations']:
            if o['card_id']!=CARD:continue
            check_face(row,o['face'],o['locale'],decl)
            bad=deepcopy(o['face']);bad['text']=bad['text'].split('<i>')[0].split(' <b>')[0]
            with self.assertRaises(ValueError):check_face(row,bad,o['locale'],decl)
            raw=deepcopy(row);raw['tags']['TAG_SCRIPT_DATA_NUM_1']=98
            with self.assertRaises(ValueError):check_face(raw,o['face'],o['locale'],decl)

    def test_real_paid_entry_fills_six_then_retains_93_without_failed_attempts(self):
        g=self.game();i=self.play(g,CARD)
        self.assertEqual(g.state.players[1].mana,3);self.assertEqual(len(self.limbs(g)),6)
        self.assertEqual([e.card_id for e in self.limbs(g)],list(LIMBS));self.assertEqual(self.remaining(g,i),93)
        self.assertFalse(any(e.kind=='summon_failed'for e in g.events))
        rec=g.state.colossal_history[0];self.assertTrue(rec.completed);self.assertEqual(rec.attempted,99)
        self.assertEqual(sum(x is not None for x in rec.limbs),6);self.check(g)

    def test_last_slot_preserves_all_99_then_unrelated_minion_death_refills(self):
        g=self.game(hand=(CARD,P+'kill'),board=(UNIT,)*6);i=self.play(g,CARD,position=2)
        self.assertEqual(self.remaining(g,i),99);self.assertFalse(self.limbs(g))
        victim=next(e.id for e in self.bodies(g)if e.card_id==UNIT);self.play(g,'kill',victim)
        self.assertEqual(self.remaining(g,i),98);self.assertEqual(len(self.limbs(g)),1);self.check(g)

    def test_dead_limb_replaced_after_its_original_random_buff_and_replay(self):
        g=self.game(hand=(CARD,P+'kill'));i=self.play(g,CARD);old=self.limbs(g)[0].id
        self.play(g,'kill',old);self.assertEqual(self.remaining(g,i),92);self.assertEqual(len(self.limbs(g)),6)
        self.assertEqual(self.drain(g),0);self.assertEqual(sum(e.attack for e in self.bodies(g)),16)
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.check(g)

    def test_simultaneous_six_deaths_refill_whole_board_and_spend_six(self):
        g=self.game(hand=(CARD,P+'clear'));i=self.play(g,CARD)
        self.play(g,'clear');self.assertEqual(self.remaining(g,i),87);self.assertEqual(len(self.limbs(g)),6)
        self.assertEqual(self.drain(g),0);self.assertEqual(len(g.state.death_history),6)
        self.assertEqual(g.state.entities[i].attack,14);self.check(g)

    def test_simultaneous_body_death_prevents_refills_but_limb_deathrattles_finish(self):
        g=self.game(hand=(CARD,P+'wipe'));i=self.play(g,CARD);self.play(g,'wipe');self.drain(g)
        self.assertFalse(self.bodies(g));self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)
        self.assertEqual(sum(e.kind==SPENT for e in g.events),6);self.check(g)

    def test_silenced_source_stops_refill_existing_limb_deathrattle_survives(self):
        g=self.game(hand=(CARD,P+'silence',P+'kill'));i=self.play(g,CARD);self.play(g,'silence',i)
        self.play(g,'kill',self.limbs(g)[0].id);self.drain(g)
        self.assertEqual(len(self.limbs(g)),5);self.assertIsNone(source(g.state.entities[i]));self.check(g)

    def test_bounce_replay_is_fresh_reserve_old_limbs_stay_independent(self):
        g=self.game(hand=(CARD,P+'bounce'));i=self.play(g,CARD);self.play(g,'bounce',i)
        self.assertEqual(len(self.limbs(g)),6);self.assertEqual(self.remaining(g,i),99)
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.play(g,CARD);self.assertEqual(self.remaining(g,i),99);self.assertEqual(len(self.limbs(g)),6);self.check(g)

    def test_control_change_uses_new_side_preserves_remaining_and_no_new_giant_entry(self):
        g=self.game(hand=(CARD,P+'steal'));i=self.play(g,CARD);self.play(g,'steal',i)
        self.assertEqual(g.state.entities[i].controller,2);self.assertEqual(len(self.limbs(g,1)),6)
        self.assertEqual(len(self.limbs(g,2)),6);self.assertEqual(self.remaining(g,i),87)
        self.assertEqual(len(g.state.colossal_history),1);self.check(g)

    def test_transform_away_stops_supply_and_existing_limbs_remain(self):
        g=self.game(hand=(CARD,P+'plain',P+'kill'));i=self.play(g,CARD);self.play(g,'plain',i)
        self.play(g,'kill',self.limbs(g)[0].id);self.drain(g)
        self.assertEqual(len(self.limbs(g)),5);self.assertIsNone(source(g.state.entities[i]));self.check(g)

    def test_native_transform_and_nonplay_summon_share_original_colossal_entry(self):
        for name,board in [('transform',(UNIT,)),('summon',())]:
            with self.subTest(name=name):
                g=self.game(hand=(P+name,),board=board);self.play(g,name,self.bodies(g)[0].id if board else None)
                i=next(e.id for e in self.bodies(g)if e.card_id==CARD)
                self.assertEqual(self.remaining(g,i),93);self.assertEqual(len(self.limbs(g)),6);self.check(g)

    def test_all_99_successful_appendages_exhaust_once_even_when_each_immediately_dies(self):
        g=self.game(mode='slaughter');i=self.play(g,CARD)
        self.assertEqual(self.remaining(g,i),0);self.assertEqual(len(g.state.death_history),99)
        self.assertEqual(sum(e.kind==SPENT for e in g.events),99);self.assertFalse(self.limbs(g))
        self.assertEqual(len(g.state.colossal_history),1);self.assertFalse(g.state.pending_choice);self.check(g,'slaughter')

    def test_initial_summon_wait_keeps_only_next_native_limb_and_independent_restore(self):
        g=self.game(mode='wait_initial');i=self.play(g,CARD);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.remaining(g,i),98);self.check(g,'wait_initial')
        q=g.state.pending_choice;before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(SelectChoice(q.player_id,q.id,('missing',)))
        self.assertEqual(g.snapshot(),before);g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(self.remaining(g,i),93);self.check(g,'wait_initial')

    def test_refill_wait_recovery_choice_failure_and_actual_debit_not_repeated(self):
        g=self.game(hand=(CARD,P+'kill'),mode='wait_refill');i=self.play(g,CARD)
        self.play(g,'kill',self.limbs(g)[0].id);self.assertEqual(self.remaining(g,i),92)
        self.check(g,'wait_refill');q=g.state.pending_choice;before=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(q.player_id,q.id,('bad',)))
        self.assertEqual(g.snapshot(),before);g.apply(SelectChoice(q.player_id,q.id,('ok',)));self.drain(g)
        self.assertEqual(self.remaining(g,i),92);self.check(g,'wait_refill')

    def test_failed_refill_reaction_rolls_back_entire_kill_and_allocation(self):
        g=self.game(hand=(CARD,P+'kill'),mode='fail_refill');self.play(g,CARD);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'kill',self.limbs(g)[0].id)
        self.assertEqual(g.snapshot(),before);self.check(g,'fail_refill')

    def test_later_effect_failure_rolls_back_native_refill_and_rng(self):
        g=self.game(hand=(CARD,P+'latefail'));self.play(g,CARD);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'latefail',self.limbs(g)[0].id)
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_silenced_current_copy_and_fresh_base_copy_share_existing_copy_lifecycle(self):
        # A real full opposing board prevents the ongoing source filling
        # before the Silence spell's body. Initial scenarios are not entries.
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_05',hand=(P+'silence',P+'copy',P+'base'),
            deck=(UNIT,)*8,max_mana=10,mana=10),PlayerSetup('HERO_08',board=(CARD,)+(UNIT,)*6,
            deck=(UNIT,)*8,max_mana=10,mana=10)),seed=41),fixture())
        i=g.state.players[2].board[0]
        self.play(g,'silence',i);self.play(g,'copy',i)
        self.assertFalse(self.limbs(g));self.assertTrue(all(e.silenced for e in self.bodies(g)))
        self.play(g,'base',i)
        native=[e for e in self.bodies(g)if e.card_id==CARD and source(e)is not None]
        self.assertEqual(len(native),1);self.assertEqual(self.remaining(g,native[0].id),94)
        self.assertEqual(len(self.limbs(g)),5);self.check(g)

    def test_actual_current_copy_opens_a_fresh_99_reserve_on_the_new_body(self):
        r=fixture();g=Game.from_scenario(Scenario((PlayerSetup('HERO_05',hand=(P+'copy',),deck=(UNIT,)*8,max_mana=10,mana=10),
            PlayerSetup('HERO_05',hand=(CARD,),deck=(UNIT,)*8,max_mana=10,mana=10)),active_player=2,seed=41),r)
        old=self.play(g,CARD);g.apply(EndTurn(2));self.play(g,'copy',old)
        new=next(e.id for e in self.bodies(g)if e.card_id==CARD)
        self.assertNotEqual(old,new);self.assertEqual(self.remaining(g,old),93);self.assertEqual(self.remaining(g,new),93)
        self.assertEqual(len(g.state.colossal_history),2);self.check(g)

    def test_dormancy_pauses_without_spending_and_wake_reuses_remaining_reserve(self):
        g=self.game(hand=(CARD,P+'dormant',P+'kill',P+'wake'));i=self.play(g,CARD)
        self.play(g,'dormant',i);self.play(g,'kill',self.limbs(g)[0].id)
        self.assertEqual(self.remaining(g,i),93);self.assertEqual(len(self.limbs(g)),5)
        self.play(g,'wake');self.assertEqual(self.remaining(g,i),92);self.assertEqual(len(self.limbs(g)),6);self.check(g)

    def test_pending_refill_cannot_be_cropped_or_change_its_original_counter(self):
        g=self.game(hand=(CARD,P+'clear'),mode='wait_refill');self.play(g,CARD);self.play(g,'clear')
        self.assertIsNotNone(g.state.pending_choice);s=g.snapshot()
        def visit(v,mode):
            if isinstance(v,dict):
                if v.get('type','').endswith('.RefillColossalAppendage')and mode=='counter':
                    v['fields']['remaining']+=1;return True
                if mode=='crop'and'tuple'in v:
                    for i,x in enumerate(v['tuple']):
                        if isinstance(x,dict)and x.get('type','').endswith('.RefillColossalAppendage'):
                            v['tuple'].pop(i);return True
                return any(visit(x,mode)for x in v.values())
            if isinstance(v,list):return any(visit(x,mode)for x in v)
            return False
        for mode in ('crop','counter'):
            bad=deepcopy(s);self.assertTrue(visit(bad,mode))
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('wait_refill'))
        self.check(g,'wait_refill')

    def test_terminal_initial_reaction_closes_entry_without_spending_remainder(self):
        g=self.game(mode='terminal');i=self.play(g,CARD)
        self.assertNotEqual(g.state.status,'playing');self.assertEqual(self.remaining(g,i),98)
        self.assertTrue(g.state.colossal_history[0].canceled);self.check(g,'terminal')

    def test_second_seat_paid_entry_has_own_reserve_and_original_owner(self):
        g=self.game(active=2);i=self.play(g,CARD)
        self.assertEqual(self.remaining(g,i),93);self.assertEqual(len(self.limbs(g,2)),6)
        self.assertTrue(all(e.owner==2 for e in self.limbs(g,2)));self.check(g)

    def test_rehashed_native_counter_debit_or_limb_identity_corruption_rejected(self):
        g=self.game();i=self.play(g,CARD);s=g.snapshot()
        for change in ('counter','debit','limb'):
            with self.subTest(change=change):
                bad=deepcopy(s)
                if change=='counter':
                    a=next(a for a in bad['state']['entities'][str(i)]['abilities']if a['kind']=='colossal_reserve');a['colossal_remaining']+=1
                else:
                    e=next(e for e in bad['events']if e['kind']==SPENT)
                    d=dict(e['data']);d['remaining'if change=='debit'else'limb_card_id']=99 if change=='debit'else UNIT;e['data']=d
                with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture())

    def test_remaining_public_on_board_but_hidden_opponent_hand_and_private_receipts(self):
        g=self.game();own=json.dumps(g.for_player(1).observe(),ensure_ascii=False);enemy=json.dumps(g.for_player(2).observe(),ensure_ascii=False)
        self.assertIn('colossal_remaining',own);self.assertNotIn('colossal_remaining',enemy)
        self.play(g,CARD)
        for p in (1,2):
            dto=json.dumps(g.for_player(p).observe(),ensure_ascii=False)
            self.assertIn('colossal_remaining',dto);self.assertNotIn(RESET,dto);self.assertNotIn(SPENT,dto)

    def test_registry_rejects_noncolossal_and_borrowed_native_reserve(self):
        r=fixture.__wrapped__()
        with self.assertRaises(ValueError):r.register_colossal_reserve_profile(ColossalReserveProfile(UNIT))
        g=self.game();s=g.snapshot();i=g.state.players[1].hand[0]
        native=next(a for a in s['state']['entities'][str(i)]['abilities']if a['kind']=='colossal_reserve');native['colossal_reserve_card_id']=UNIT
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(s),fixture())


if __name__=='__main__':unittest.main()
