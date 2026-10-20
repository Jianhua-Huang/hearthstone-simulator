"""Real Prison activation/release with source-specific ordinary card execution."""
from dataclasses import asdict
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.zuramat_prison_cards import CARD, RELEASED, GUARD, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction, PlayCard,
    PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, UseLocation, Zone)
from hs_sim.engine.effects import ChoiceOption, CopyMinion, Destroy, GainArmor, RequestChoice, ReturnToHand
from hs_sim.engine.locations import RefreshLocation, DestroyLocation
from hs_sim.engine.prison_playback import ACCEPTED, MATERIAL
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard, DiscardCard
from hs_sim.engine.summon_quantities import SummonCause
from tools.card_batch import check_face
from hs_sim.targets import canonical_digest

P='fixture.prison.'; UNIT=P+'unit'; REWARD=P+'reward'; WEAPON=P+'weapon'; OTHER=P+'other'


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r=build_registry()
    r.register_behavior(P+'bc',lambda c:(GainArmor(c.player_id,50),))
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,attack=2,health=3,battlecry=P+'bc'))
    r.register_card(CardDefinition(OTHER,OTHER,CardType.MINION,attack=1,health=5))
    r.register_behavior(P+'reward',lambda c:(GainArmor(c.player_id,3),))
    r.register_card(CardDefinition(REWARD,REWARD,CardType.SPELL,cost=2,on_play=P+'reward'))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,attack=2,durability=3,battlecry=P+'bc'))
    target=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,CardType.LOCATION),relation='friendly')
    scripts={'kill':lambda c:((DestroyLocation(c.target_id,c.source_id) if
        c.state.entities[c.target_id].kind==CardType.LOCATION else Destroy(c.target_id,c.source_id)),),
        'refresh':lambda c:(RefreshLocation(c.target_id,c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'bodycopy':lambda c:(CopyMinion(c.target_id,c.player_id,cause=SummonCause.capture(c)),),
        'copy':lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,source_id=c.source_id),)}
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,targeting=target))
    r.register_behavior(P+'discard',lambda c:(DiscardCard(CardReference.capture(c.state.entities[c.target_id]),c.source_id),))
    r.register_card(CardDefinition(P+'discard','Other discard',CardType.SPELL,on_play=P+'discard',
        targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.SPELL,CardType.MINION),relation='friendly')))
    def watch(c):
        entity=c.state.entities[c.event.target_id]
        if entity.card_id!=UNIT:return ()
        if mode=='fail':raise ResolutionError('Prison summon observer failure')
        if mode=='wait':return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(P+'watch','Observer',CardType.MINION,health=20,
        triggers=(TriggerSpec('minion_summoned',P+'watch'),)))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
    return s


class PrisonTests(unittest.TestCase):
    def game(self,hand=(CARD,UNIT,P+'kill'),board=(),mode='normal',active=1):
        return Game.from_scenario(Scenario(tuple(PlayerSetup('HERO_03',hand=hand if p==active else (),
            deck=(OTHER,)*8,board=board if p==active else (),mana=10,max_mana=10)for p in(1,2)),
            active_player=active,seed=310),fixture(mode))
    def hand(self,g,cid,p=None):
        return next(i for i in g.state.players[p or g.state.active_player].hand if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.hand(g,cid);g.apply(PlayCard(g.state.active_player,eid,target));return eid
    def board(self,g,cid,p=None):
        return[i for i in g.state.players[p or g.state.active_player].board if g.state.entities[i].card_id==cid]
    def use(self,g,prison,cid):g.apply(UseLocation(g.state.active_player,prison,self.hand(g,cid)))
    def release(self,g,cid=UNIT):
        prison=self.play(g,CARD);self.use(g,prison,cid);self.play(g,P+'kill',prison)
        return prison,self.board(g,RELEASED)[0]
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def portable(self,g,mode='normal'):
        s=json.loads(json.dumps(g.snapshot()));r=fixture.__wrapped__(mode)
        other=Game.from_snapshot(s,r);self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),fixture.__wrapped__(mode)).snapshot(),s)
        return other
    def test_complete_sources_and_preserved_existing_guard(self):
        data=load_batch();r=fixture()
        for group in ('cards','dependencies','existing_dependencies','evidence_only'):
            for row in data[group]:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        for observation in data['official_observations']:
            row=next(x['record']for group in('cards','dependencies','existing_dependencies')for x in data[group]
                if x['record']['id']==observation['card_id'])
            check_face(row,observation['face'],observation['locale'])
        pin=data['existing_dependency_definition_pins'][GUARD]
        self.assertEqual(canonical_digest(asdict(r.card(GUARD))),pin['sha256'])
        self.assertNotIn(RELEASED+'e',r.cards)
    def test_real_location_payment_discard_reward_and_no_battlecry(self):
        g=self.game();prison,released=self.release(g)
        self.assertEqual(g.state.players[1].mana,5)
        self.assertEqual(g.state.entities[prison].zone,Zone.GRAVEYARD)
        self.assertEqual(len(self.board(g,GUARD)),1)
        self.assertEqual(g.state.discard_history[-1].source_id,prison)
        self.end(g)
        self.assertEqual(len(self.board(g,UNIT,1)),1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.assertEqual(g.state.entities[released].abilities[0].prison_playback.consumed_discard_ids,(1,))
        self.portable(g)
    def test_spell_uses_real_automatic_cast_without_hand_payment(self):
        g=self.game(hand=(CARD,REWARD,P+'kill'));self.release(g,REWARD)
        before=len(g.state.play_history);self.end(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,3)
        self.assertEqual(len(g.state.play_history),before)
        self.assertEqual(g.state.cast_history[-1].card_id,REWARD)
        self.assertEqual(g.state.cast_history[-1].origin,'effect')
        self.assertEqual(sum(e.kind==MATERIAL for e in g.events),1)
        self.portable(g)
    def test_printed_weapon_installation_omits_battlecry(self):
        g=self.game(hand=(CARD,WEAPON,P+'kill'));self.release(g,WEAPON);self.end(g)
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].card_id,WEAPON)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.portable(g)
    def test_printed_location_installation_has_no_activation(self):
        g=self.game(hand=(CARD,CARD,P+'kill'));self.release(g,CARD);self.end(g)
        fresh=self.board(g,CARD,1);self.assertEqual(len(fresh),1)
        self.assertEqual(g.state.entities[fresh[0]].durability,3)
        self.assertEqual(len(g.state.discard_history),1)
        self.portable(g)
    def test_last_use_discard_is_not_lost_after_location_death(self):
        g=self.game(hand=(CARD,UNIT,UNIT,REWARD,P+'refresh',P+'refresh'))
        prison=self.play(g,CARD);self.use(g,prison,UNIT)
        self.play(g,P+'refresh',prison);self.use(g,prison,UNIT)
        self.play(g,P+'refresh',prison);self.use(g,prison,REWARD)
        self.assertEqual(len(g.state.discard_history),3)
        self.assertEqual(len(self.board(g,RELEASED)),1)
        for _ in range(5):self.end(g)
        accepted=[json.loads(dict(e.data)['receipt'])for e in g.events if e.kind==ACCEPTED]
        self.assertEqual(accepted[0]['candidates'],[1,2,3])
        self.assertEqual(sorted(x['selected']for x in accepted),[1,2,3])
        self.portable(g)
    def test_unrelated_discard_and_other_prison_are_excluded(self):
        g=self.game(hand=(CARD,CARD,UNIT,REWARD,UNIT,P+'discard',P+'kill'))
        self.play(g,P+'discard',self.hand(g,UNIT))
        a=self.play(g,CARD);self.use(g,a,UNIT)
        b=self.play(g,CARD);self.use(g,b,REWARD)
        self.play(g,P+'kill',a);self.end(g)
        accepted=next(json.loads(dict(e.data)['receipt'])for e in g.events if e.kind==ACCEPTED)
        self.assertEqual(accepted['candidates'],[2]);self.assertEqual(len(self.board(g,UNIT,1)),1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.portable(g)
    def test_generated_zuramat_has_no_global_discard_memory(self):
        g=self.game(hand=(UNIT,P+'discard'),board=(RELEASED,))
        self.play(g,P+'discard',self.hand(g,UNIT));self.end(g)
        self.assertEqual(len(self.board(g,UNIT,1)),0)
        self.assertFalse(any(e.kind==ACCEPTED for e in g.events))
        self.portable(g)
    def test_printed_hero_uses_existing_hero_and_power_installation(self):
        hero='CORE_EX1_323'
        g=self.game(hand=(CARD,hero,P+'kill'));self.release(g,hero);self.end(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].card_id,hero)
        self.assertIsNotNone(g.state.players[1].hero_power_id)
        self.portable(g)
    def test_empty_memory_after_consumption_does_not_draw_rng_or_replay_again(self):
        g=self.game();self.release(g);self.end(g);self.end(g)
        before=g._rng.getstate();self.end(g)
        self.assertEqual(g._rng.getstate(),before)
        self.assertEqual(len(self.board(g,UNIT,1)),1)
        accepted=[json.loads(dict(e.data)['receipt'])for e in g.events if e.kind==ACCEPTED]
        self.assertEqual(accepted[-1]['candidates'],[]);self.assertIsNone(accepted[-1]['selected'])
        self.portable(g)
    def test_full_board_consumes_original_attempt_without_inventing_body(self):
        g=self.game(board=(OTHER,)*5);self.release(g);self.end(g)
        self.assertFalse(self.board(g,UNIT,1))
        accepted=next(json.loads(dict(e.data)['receipt'])for e in g.events if e.kind==ACCEPTED)
        self.assertEqual(accepted['after'],[1])
        self.portable(g)
    def test_waiting_actual_summon_preserves_original_finish_and_private_memory(self):
        g=self.game(board=(P+'watch',),mode='wait');self.release(g);self.end(g)
        self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g,'wait')
        for current in(g,other):
            q=current.state.pending_choice;current.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(g.snapshot(),other.snapshot())
        self.portable(g,'wait')
    def test_failure_after_accepted_random_play_rolls_back_entire_end_turn(self):
        g=self.game(board=(P+'watch',),mode='fail');self.release(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.end(g)
        self.assertEqual(g.snapshot(),before)
    def test_current_copy_preserves_remaining_but_consumes_independently(self):
        g=self.game(hand=(CARD,UNIT,REWARD,P+'refresh',P+'kill',P+'bodycopy'))
        prison=self.play(g,CARD);self.use(g,prison,UNIT)
        self.play(g,P+'refresh',prison);self.use(g,prison,REWARD);self.play(g,P+'kill',prison)
        self.end(g);self.end(g)
        original=self.board(g,RELEASED)[0]
        old=next(a.prison_playback for a in g.state.entities[original].abilities if a.prison_playback is not None)
        self.play(g,P+'bodycopy',original)
        bodies=self.board(g,RELEASED)
        self.assertEqual(len(bodies),2)
        for body in bodies:
            memory=next(a.prison_playback for a in g.state.entities[body].abilities if a.prison_playback is not None)
            self.assertEqual(memory,old)
        self.end(g)
        for body in bodies:
            memory=next(a.prison_playback for a in g.state.entities[body].abilities if a.prison_playback is not None)
            self.assertEqual(len(memory.consumed_discard_ids),2)
        self.portable(g)
    def test_bounced_replayed_zuramat_does_not_regain_old_prison_memory(self):
        g=self.game(hand=(CARD,UNIT,P+'kill',P+'bounce'));_,body=self.release(g)
        self.play(g,P+'bounce',body)
        self.assertTrue(all(a.prison_playback is None for a in g.state.entities[body].abilities))
        self.end(g);self.end(g);self.play(g,RELEASED);self.end(g)
        self.assertFalse(self.board(g,UNIT,1));self.portable(g)
    def test_rehashed_current_memory_rewind_and_candidate_cropping_are_rejected(self):
        g=self.game();_,body=self.release(g);self.end(g)
        for mutation in('binding','candidates','material'):
            s=json.loads(json.dumps(g.snapshot()))
            if mutation=='binding':
                entity=s['state']['entities'][str(body)]
                next(a for a in entity['abilities']if a['prison_playback']is not None)['prison_playback']['consumed_discard_ids']=[]
            elif mutation=='candidates':
                event=next(e for e in s['events']if e['kind']==ACCEPTED)
                data=dict(event['data']);receipt=json.loads(data['receipt']);receipt['candidates']=[]
                data['receipt']=json.dumps(receipt);event['data']=list(data.items())
            else:
                event=next(e for e in s['events']if e['kind']==ACCEPTED)
                s['events'].remove(event)
            with self.assertRaises((SnapshotError,ValueError)):
                Game.from_snapshot(rehash(s),fixture.__wrapped__())
    def test_player_actions_use_visible_hand_and_private_memory_never_leaks(self):
        g=self.game();prison=self.play(g,CARD)
        commands=g.for_player(1).legal_actions()
        self.assertIsNone(commands['error'])
        target=next(x['ref']for x in commands['observation']['players'][0]['hand']if x['card_id']==UNIT)
        command=next(a for a in commands['actions']if a['type']=='use_location'and a['target']==target)
        result=g.for_player(1).submit({'revision':commands['revision'],'action':command})
        self.assertTrue(result['accepted'])
        self.play(g,P+'kill',prison);self.end(g)
        for player in(1,2):
            observation=json.dumps(g.observe(player))
            for hidden in('prison_playback','consumed_discard_ids','prison_discard_material','rng_before','discard_frontier'):
                self.assertNotIn(hidden,observation)
    def test_second_player_has_independent_prison_and_actual_actor(self):
        g=self.game(active=2);self.release(g);self.end(g)
        self.assertEqual(len(self.board(g,UNIT,2)),1)
        event=next(e for e in g.events if e.kind==ACCEPTED)
        self.assertEqual(event.player_id,2);self.portable(g)


if __name__=='__main__':unittest.main()
