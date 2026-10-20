"""Actual targeted locations and two genuine non-Battlecry target bodies."""
from functools import lru_cache
import json
import unittest

from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,
    ResolutionError,Scenario,SelectChoice,SnapshotError,TriggerSpec,UseHandAction,
    UseLocation,UseMinionAbility,Zone)
from hs_sim.engine.effects import AddToHand,ChoiceOption,Destroy,RequestChoice
from hs_sim.engine.locations import ModifyLocation
from hs_sim.engine.native_active_targets import ACCEPTED,FINISHED
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from test_native_random_target_domains import fixture as domain_fixture,CARD,UNIT

P='fixture.native.active.';WATCH=P+'watch';LOC='CORE_REV_990';SUN='WW_434';MAT='TLC_825';BEAST='BAR_024'


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r=domain_fixture.__wrapped__()
    def watch(c):
        if mode=='fail':raise ResolutionError('Native active target observer failure')
        if mode=='wait':return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),)
        if mode=='clear'and c.state.entities[c.event.source_id].card_id==MAT:
            return tuple(Destroy(i,c.source_id)for i in c.state.players[2].board)
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,
        triggers=(TriggerSpec('card_committed'if mode=='clear'else'health_resolved',P+'watch'),)))
    def last(c):
        eid=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==LOC)
        return(ModifyLocation(eid,1-c.state.entities[eid].durability,c.source_id),)
    for name,body in(('make',lambda c:(AddToHand(c.player_id,SUN,c.source_id),)),('last',last)):
        r.register_behavior(P+name,body);r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('events','events_hash','state_hash')})
    return s


class NativeActiveTargetTests(unittest.TestCase):
    def game(self,*,mode='normal',board=(CARD,UNIT,LOC),enemy=(UNIT,),hand=(),seed=314):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_03',board=board,hand=hand,deck=(UNIT,)*16,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_03',board=enemy,deck=(UNIT,)*16,mana=40,max_mana=40,mana_cap=40)),seed=seed),fixture(mode))
    def entity(self,g,cid,player=1,zone='board'):
        return next(i for i in getattr(g.state.players[player],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):g.apply(PlayCard(1,self.entity(g,cid,1,'hand'),target))
    def use(self,g,cid=LOC,target=None):
        g.apply(UseLocation(1,self.entity(g,cid),target or self.entity(g,UNIT,2)))
    def selections(self,g):
        codec=FrameCodec(g.mechanics,g.registry)
        return[codec.decode(json.loads(dict(e.data)['selection']))for e in g.events if e.kind==ACCEPTED]
    def portable(self,g,mode='normal'):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,fixture.__wrapped__(mode))
        self.assertEqual(s,other.snapshot());self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),fixture.__wrapped__(mode)).snapshot(),s)
        return other
    def prepare_kindred(self,g):
        self.play(g,BEAST);g.apply(EndTurn(1));g.apply(EndTurn(2))
    def test_real_depths_uses_selected_minion_and_one_durability_cooldown(self):
        g=self.game();source=self.entity(g,LOC);original=self.entity(g,UNIT,2)
        before={i:(e.attack,e.damage)for i,e in g.state.entities.items()}
        durability=g.state.entities[source].durability;self.use(g,target=original);selection=self.selections(g)[-1]
        chosen=g.state.entities[selection.target_id]
        self.assertEqual(selection.partition.origin,'location');self.assertEqual(selection.partition.submitted_target_id,original)
        self.assertEqual(chosen.attack,before[chosen.id][0]+2);self.assertEqual(chosen.damage,before[chosen.id][1]+1)
        self.assertEqual(g.state.entities[source].durability,durability-1)
        self.assertEqual(g.state.entities[source].location_cooldown,2);self.assertEqual(g.state.entities[source].uses_this_turn,1)
        self.assertEqual(sum(e.kind==FINISHED for e in g.events),1);self.portable(g)
    def test_real_hand_buff_location_preserves_hand_minion_domain(self):
        g=self.game(board=(CARD,'CATA_477'),hand=(UNIT,UNIT,'CS2_029'))
        minions=[i for i in g.state.players[1].hand if g.state.entities[i].kind==CardType.MINION]
        before={i:(g.state.entities[i].attack,g.state.entities[i].health)for i in minions}
        self.use(g,'CATA_477',minions[0]);s=self.selections(g)[-1]
        self.assertEqual(set(s.partition.target_ids),set(minions));self.assertEqual(g.state.entities[s.target_id].zone,Zone.HAND)
        self.assertEqual((g.state.entities[s.target_id].attack,g.state.entities[s.target_id].health),(before[s.target_id][0]+2,before[s.target_id][1]+2))
        self.portable(g)
    def test_real_prison_location_discards_actual_selected_hand_card_across_types(self):
        g=self.game(board=(CARD,'JAIL_887'),hand=(UNIT,'CS2_029','CS2_106','CATA_477'))
        original=self.entity(g,UNIT,1,'hand');hand=set(g.state.players[1].hand)
        self.use(g,'JAIL_887',original);s=self.selections(g)[-1]
        self.assertEqual(set(s.partition.target_ids),hand)
        self.assertEqual(g.state.discard_history[-1].card_id,g.state.entities[s.target_id].card_id)
        self.assertNotIn(s.target_id,g.state.players[1].hand);self.portable(g)
    def test_last_durability_keeps_original_body_after_location_death(self):
        g=self.game(hand=(P+'last',));source=self.entity(g,LOC);self.play(g,P+'last');self.use(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        selected=self.selections(g)[-1].target_id
        self.assertTrue(any(e.kind=='damage_dealt'and e.source_id==source and e.target_id==selected for e in g.events));self.portable(g)
    def test_no_source_keeps_manual_location_target_and_rng(self):
        g=self.game(board=(UNIT,LOC));rng=g.snapshot()['rng_state'];original=self.entity(g,UNIT,2);self.use(g)
        self.assertEqual(self.selections(g),[]);self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertEqual(g.state.entities[original].damage,1);self.portable(g)
    def test_real_quickdraw_on_play_preserves_original_paid_submission_and_actual_damage(self):
        g=self.game(board=(CARD,UNIT),hand=(P+'make',));self.play(g,P+'make');original=self.entity(g,UNIT,2)
        self.play(g,SUN,original);s=self.selections(g)[-1];play=g.state.play_history[-1]
        self.assertTrue(play.quickdraw);self.assertEqual(play.target_id,original)
        self.assertEqual(s.partition.origin,'on_play');self.assertEqual(s.partition.submitted_target_id,original)
        self.assertTrue(any(e.kind=='damage_dealt'and e.source_id==play.source_id and e.target_id==s.target_id and e.amount==6 for e in g.events))
        self.portable(g)
    def test_inactive_quickdraw_and_kindred_do_not_create_targets_or_rng(self):
        for card in(SUN,MAT):
            g=self.game(board=(CARD,UNIT),hand=(card,));rng=g.snapshot()['rng_state'];self.play(g,card)
            self.assertEqual(self.selections(g),[]);self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)
    def test_real_kindred_on_play_uses_native_enemy_minion_target_without_changing_paid_root(self):
        g=self.game(board=(CARD,),hand=(BEAST,MAT),enemy=(UNIT,UNIT),seed=0);self.prepare_kindred(g)
        original=self.entity(g,UNIT,2);self.play(g,MAT,original);s=self.selections(g)[-1];play=g.state.play_history[-1]
        self.assertEqual(play.target_id,original);self.assertEqual(set(s.partition.target_ids),set(g.state.players[2].board))
        self.assertTrue(any(e.kind=='damage_dealt'and e.source_id==play.source_id and e.target_id==s.target_id and e.amount==5 for e in g.events));self.portable(g)
    def test_empty_kindred_target_still_accepts_actual_wrapper_and_history(self):
        g=self.game(mode='clear',board=(CARD,WATCH),hand=(BEAST,MAT));self.prepare_kindred(g)
        original=self.entity(g,UNIT,2);self.play(g,MAT,original);s=self.selections(g)[-1]
        self.assertEqual(s.failure,'no_target');self.assertEqual(s.rng_before,s.rng_after)
        self.assertTrue(g.state.kindred_history);self.assertEqual(g.state.play_history[-1].target_id,original)
        self.portable(g,'clear')
    def test_location_health_choice_restores_original_acceptance_before_resuming(self):
        g=self.game(mode='wait',board=(CARD,UNIT,LOC,WATCH));self.use(g)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,'wait')
        for current in(g,other):
            q=current.state.pending_choice;current.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(sum(e.kind==ACCEPTED for e in g.events),1)
    def test_real_quickdraw_and_kindred_waits_restore_their_original_on_play_proof(self):
        for card in(SUN,MAT):
            with self.subTest(card=card):
                g=self.game(mode='wait',board=(CARD,WATCH),hand=(P+'make',)if card==SUN else(BEAST,MAT))
                if card==SUN:self.play(g,P+'make')
                else:self.prepare_kindred(g)
                self.play(g,card,self.entity(g,UNIT,2));self.assertIsNotNone(g.state.pending_choice)
                other=self.portable(g,'wait')
                for current in(g,other):
                    for _ in range(4):
                        q=current.state.pending_choice
                        if q is None:break
                        current.apply(SelectChoice(q.player_id,q.id,('ok',)))
                    self.assertIsNone(current.state.pending_choice)
                self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(sum(e.kind==ACCEPTED for e in g.events),1)
    def test_failure_rolls_back_location_usage_and_native_rng(self):
        g=self.game(mode='fail',board=(CARD,UNIT,LOC,WATCH));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.use(g)
        self.assertEqual(g.snapshot(),before)
    def test_existing_untargeted_titan_and_trade_do_not_acquire_native_targets(self):
        g=self.game(board=(CARD,'TTN_903'),hand=(SUN,));rng=g.snapshot()['rng_state']
        g.apply(UseMinionAbility(1,self.entity(g,'TTN_903'),'TTN_903t2'))
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(self.selections(g),[])
        g.apply(UseHandAction(1,self.entity(g,SUN,1,'hand'),'trade'));self.assertEqual(self.selections(g),[]);self.portable(g)
    def test_waiting_proof_rejects_cropped_candidates_and_missing_finish(self):
        g=self.game(mode='wait',board=(CARD,UNIT,LOC,WATCH));self.use(g)
        for mode in('crop','finish'):
            s=json.loads(json.dumps(g.snapshot()))
            if mode=='crop':
                event=next(e for e in s['events']if e['kind']==ACCEPTED);data=dict(event['data'])
                encoded=json.loads(data['selection'])
                def crop(value):
                    if isinstance(value,dict):
                        if 'candidates'in value and isinstance(value['candidates'],dict):
                            child=value['candidates'];items=child.get('tuple')
                            if isinstance(items,list)and items:child['tuple']=items[:-1];return True
                        return any(crop(x)for x in value.values())
                    if isinstance(value,list):return any(crop(x)for x in value)
                    return False
                self.assertTrue(crop(encoded));data['selection']=json.dumps(encoded);event['data']=sorted(data.items())
            else:
                def prune(value):
                    if isinstance(value,dict):
                        for key,child in list(value.items()):
                            if isinstance(child,list):value[key]=[x for x in child if not(isinstance(x,dict)and str(x.get('type','')).endswith('.FinishNativeActiveTarget'))]
                            prune(value[key])
                    elif isinstance(value,list):
                        for child in value:prune(child)
                prune(s['resolution_frame'])
            with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(rehash(s),fixture.__wrapped__('wait'))
    def test_player_views_hide_private_native_material(self):
        g=self.game();self.use(g)
        for player in(1,2):
            text=json.dumps(g.observe(player))
            for hidden in(ACCEPTED,FINISHED,'before_state','rng_before','behavior_ids','acceptance_id'):
                self.assertNotIn(hidden,text)


if __name__=='__main__':unittest.main()
