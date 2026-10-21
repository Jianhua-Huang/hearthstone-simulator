"""Actual Ironborn death rewards use original turn and continuous residence."""
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards import build_registry as assembled
from hs_sim.cards.frontline_ironborn_card import CARD, load_batch, register_frontline_ironborn_card
from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.bonus_effects import BONUS_EFFECTS, GrantRandomBonusEffects, bonus_candidates
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, Destroy, DestroyBatch,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform, GrantKeyword)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference, CardClass, Rarity
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.sacrifice import BuffCapturedMinion, GrantCapturedKeyword
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face

P='fixture.ironborn.'
FILL,MATERIAL,WATCH=(P+x for x in ('fill','material','watch'))


@lru_cache(maxsize=None)
def fixture(mode=None, role='writer'):
    if role not in ('writer','reader'):raise ValueError('Independent registry role required')
    r=build_registry();register_frontline_ironborn_card(r)
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,attack=1,health=10))
    r.register_card(CardDefinition(MATERIAL,MATERIAL,CardType.MINION,attack=4,health=6,keywords=(Keyword.TAUNT,)))
    def fail(c):raise ResolutionError('Ironborn deliberate failure')
    r.register_behavior(P+'fail',fail)
    def source(c):return next(e for e in c.state.entities.values()if e.card_id==CARD and e.zone==Zone.BOARD)
    scripts={
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'enemy':lambda c:(DestroyBatch(tuple(c.state.players[3-c.player_id].board),c.source_id),),
        'both':lambda c:(DestroyBatch(tuple(i for p in (1,2)for i in c.state.players[p].board),c.source_id),),
        'silence':lambda c:(Silence(source(c).id),),
        'ping':lambda c:(Damage(c.target_id,2,c.source_id),),
        'steal':lambda c:(ChangeControl(c.target_id,c.player_id),),
        'give':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'saturate':lambda c:tuple(GrantKeyword(source(c).id,k,c.source_id)for k in BONUS_EFFECTS),
        'kill_fail':lambda c:(Destroy(c.target_id,c.source_id),InvokeBehavior(P+'fail',c.source_id,c.player_id)),
    }
    for name,body in scripts.items():
        key=P+name;r.register_behavior(key,body)
        r.register_card(CardDefinition(key,key,CardType.SPELL,on_play=key,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
                if name in ('kill','ping','steal','give','kill_fail')else None))
    if mode:
        def watch(c):
            if c.event is None:return()
            if mode=='before_transform':
                if c.event.player_id==c.player_id:return()
                return(Transform(source(c).id,MATERIAL),)
            eid=c.event.target_id
            if eid is None or c.state.entities[eid].card_id!=CARD:return()
            if mode=='wait':
                return(RequestChoice(3-c.player_id,(
                    ChoiceOption('ok','Continue'),
                    ChoiceOption('bounce','Return and summon',effects=(ReturnToHand(eid),
                        SummonFromZone(c.player_id,zone=Zone.HAND,query=PoolQuery(card_ids=(CARD,)),selection='first'))),
                    ChoiceOption('fail','Fail',effects=(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),
                    source_id=c.source_id),)
            if mode=='bounce':return(ReturnToHand(eid),SummonFromZone(c.player_id,zone=Zone.HAND,
                query=PoolQuery(card_ids=(CARD,)),selection='first'))
            if mode=='transform':return(Transform(eid,MATERIAL),)
            if mode=='control':return(ChangeControl(eid,3-c.player_id),)
            if mode=='silence':return(Silence(eid),)
            if mode=='destroy':return(Destroy(eid,c.source_id),)
            if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return()
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,
            triggers=(TriggerSpec('minion_died'if mode=='before_transform'else'stats_changed',P+'watch'),)))
    return r


class FrontlineIronbornTests(unittest.TestCase):
    def game(self,*,mode=None,hand=(),board=(CARD,),enemy=(FILL,),seat=1,active=None,enemy_hand=()):
        self.mode=mode;self.seat=seat
        if mode:board=(WATCH,*board)
        own=PlayerSetup('HERO_08',hand=hand,board=board,deck=(FILL,)*6,mana=10,max_mana=10)
        other=PlayerSetup('HERO_01',hand=enemy_hand,board=enemy,deck=(FILL,)*6,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),
            active_player=seat if active is None else active,seed=361),fixture(mode))

    def eid(self,g,cid=CARD,pid=None,zone='board'):
        return next(i for i in getattr(g.state.players[self.seat if pid is None else pid],zone)
            if g.state.entities[i].card_id==cid)

    def play(self,g,cid,target=None):
        pid=g.state.active_player;i=self.eid(g,cid,pid,'hand');g.apply(PlayCard(pid,i,target));return i

    def op(self,g,name,target=None):return self.play(g,P+name,target)
    def recipient(self,g):return g.state.entities[self.eid(g)]
    def enemy(self,g):return self.eid(g,FILL,3-self.seat)
    def keywords(self,g,eid):return g.state.entities[eid].keywords.intersection(BONUS_EFFECTS)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g,*,replay_too=True):
        saved=json.loads(json.dumps(g.snapshot()));r=fixture(self.mode,'reader')
        copies=(g.clone(),Game.from_snapshot(saved,r))
        if replay_too:copies=(*copies,replay(build_replay(g),r))
        for other in copies:self.assertTrue(other.snapshot()==saved,'Complete original residence/reward/RNG must restore')
        return Game.from_snapshot(saved,r)

    def test_complete_raw_primary_faces_and_original_neutral_epic_body(self):
        batch=load_batch();row=batch['cards'][0];raw=row['record']
        self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(raw['dbf_id'],131432)
        self.assertEqual({o['locale']for o in batch['official_observations']},{'zh_CN','en_US'})
        for obs in batch['official_observations']:check_face(raw,obs['face'],obs['locale'])
        self.assertEqual(raw['tags']['4548'],1)
        r=assembled();card=r.card(CARD)
        self.assertEqual((card.cost,card.attack,card.health,card.metadata.classes,card.metadata.rarity),
            (5,3,5,(CardClass.NEUTRAL,),Rarity.EPIC))
        self.assertEqual(card,fixture().card(CARD));self.assertEqual(r.pool_card(CARD),fixture().pool_card(CARD))

    def test_real_paid_minion_then_actual_enemy_death_gives_stats_and_one_original_pool_roll(self):
        g=self.game(hand=(CARD,P+'kill'),board=());i=self.play(g,CARD);self.assertEqual(g.state.players[1].mana,5)
        rng=Random();rng.setstate(g._rng.getstate());expected=rng.choice(bonus_candidates(g.state,g.state.entities[i]))
        self.op(g,'kill',self.enemy(g));e=g.state.entities[i]
        self.assertEqual((e.attack,e.max_health),(5,7));self.assertEqual(self.keywords(g,i),{expected})
        self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(g.state.death_history[-1].controller,2)
        self.portable(g)

    def test_friendly_death_does_not_reward_or_consume_rng(self):
        g=self.game(hand=(P+'kill',),board=(CARD,FILL));before=g._rng.getstate()
        self.op(g,'kill',self.eid(g,FILL));self.assertEqual((self.recipient(g).attack,self.recipient(g).max_health),(3,5))
        self.assertEqual(g._rng.getstate(),before)

    def test_enemy_death_on_opponents_turn_does_not_reward(self):
        g=self.game(active=2,enemy_hand=(P+'kill',));before=g._rng.getstate();self.op(g,'kill',self.enemy(g))
        self.assertEqual(self.recipient(g).attack,3);self.assertEqual(g._rng.getstate(),before)

    def test_stolen_original_friend_is_enemy_by_controller_at_actual_death(self):
        g=self.game(hand=(P+'give',P+'kill'),board=(CARD,FILL));victim=self.eid(g,FILL)
        self.op(g,'give',victim);self.op(g,'kill',victim)
        self.assertEqual((g.state.death_history[-1].owner,g.state.death_history[-1].controller),(1,2))
        self.assertEqual(self.recipient(g).attack,5)

    def test_stolen_original_enemy_is_friendly_by_controller_at_actual_death(self):
        g=self.game(hand=(P+'steal',P+'kill'));victim=self.enemy(g)
        self.op(g,'steal',victim);before=g._rng.getstate();self.op(g,'kill',victim)
        self.assertEqual(self.recipient(g).attack,3);self.assertEqual(g._rng.getstate(),before)

    def test_each_death_in_one_batch_has_independent_growth_and_new_missing_bonus_query(self):
        g=self.game(hand=(P+'enemy',),enemy=(FILL,)*3);i=self.eid(g);rng=Random();rng.setstate(g._rng.getstate())
        pool=list(bonus_candidates(g.state,g.state.entities[i]));expected=[]
        for _ in range(3):k=rng.choice(pool);pool.remove(k);expected.append(k)
        self.op(g,'enemy');self.assertEqual((g.state.entities[i].attack,g.state.entities[i].max_health),(9,11))
        self.assertEqual(self.keywords(g,i),set(expected));self.assertEqual(g._rng.getstate(),rng.getstate());self.portable(g)

    def test_two_physical_ironborn_sources_reward_independently(self):
        g=self.game(hand=(P+'kill',),board=(CARD,CARD));ids=tuple(g.state.players[1].board)
        self.op(g,'kill',self.enemy(g))
        self.assertEqual([(g.state.entities[i].attack,len(self.keywords(g,i)))for i in ids],[(5,1),(5,1)])
        grants=[next(a for a in g.state.entities[i].abilities if a.kind=='keyword')for i in ids]
        self.assertEqual([a.source_id for a in grants],list(ids));self.assertNotEqual(grants[0].id,grants[1].id)

    def test_source_dying_in_same_batch_never_receives_graveyard_reward(self):
        g=self.game(hand=(P+'both',));i=self.eid(g);before=g._rng.getstate();self.op(g,'both')
        self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[i].attack,3)
        self.assertEqual(g._rng.getstate(),before)

    def test_silenced_source_does_not_listen_to_next_death(self):
        g=self.game(hand=(P+'silence',P+'kill'));self.op(g,'silence');before=g._rng.getstate()
        self.op(g,'kill',self.enemy(g));self.assertEqual(self.recipient(g).attack,3);self.assertEqual(g._rng.getstate(),before)

    def test_existing_damage_is_preserved_by_health_increase(self):
        g=self.game(hand=(P+'ping',P+'kill'));i=self.eid(g);self.op(g,'ping',i);self.op(g,'kill',self.enemy(g))
        self.assertEqual((g.state.entities[i].attack,g.state.entities[i].max_health,g.state.entities[i].damage),(5,7,2))

    def test_full_bonus_pool_still_grows_stats_without_rng(self):
        g=self.game(hand=(P+'saturate',P+'kill'));i=self.eid(g);self.op(g,'saturate');before=g._rng.getstate()
        self.op(g,'kill',self.enemy(g));self.assertEqual((g.state.entities[i].attack,g.state.entities[i].max_health),(5,7))
        self.assertEqual(self.keywords(g,i),set(BONUS_EFFECTS));self.assertEqual(g._rng.getstate(),before)
        self.assertTrue(any(e.kind=='random_choice_skipped'and dict(e.data).get('reason')=='no_bonus_effects'for e in g.events))

    def test_transform_after_stats_keeps_residence_and_reads_current_printed_keywords(self):
        g=self.game(mode='transform',hand=(P+'kill',));i=self.eid(g);ref=BoardPresenceReference.capture(g.state,i)
        self.op(g,'kill',self.enemy(g));e=g.state.entities[i]
        self.assertEqual(e.card_id,MATERIAL);self.assertEqual((e.attack,e.max_health),(4,6))
        self.assertEqual(BoardPresenceReference.capture(g.state,i),ref);self.assertEqual(len(self.keywords(g,i)),2)
        self.assertIn(Keyword.TAUNT,self.keywords(g,i));self.portable(g)

    def test_transform_before_reward_preserves_original_accepted_residence_for_both_parts(self):
        g=self.game(mode='before_transform',hand=(P+'kill',));i=self.eid(g)
        self.op(g,'kill',self.enemy(g));e=g.state.entities[i]
        self.assertEqual((e.card_id,e.attack,e.max_health),(MATERIAL,6,8));self.assertEqual(len(self.keywords(g,i)),2)

    def test_control_change_between_parts_does_not_lose_original_recipient(self):
        g=self.game(mode='control',hand=(P+'kill',));i=self.eid(g);self.op(g,'kill',self.enemy(g))
        self.assertEqual((g.state.entities[i].controller,g.state.entities[i].attack),(2,5))
        self.assertEqual(len(self.keywords(g,i)),1);self.assertNotIn(Keyword.RUSH,self.keywords(g,i));self.portable(g)

    def test_silence_between_parts_removes_stats_but_accepted_bonus_still_finishes(self):
        g=self.game(mode='silence',hand=(P+'kill',));i=self.eid(g);self.op(g,'kill',self.enemy(g))
        self.assertEqual((g.state.entities[i].attack,g.state.entities[i].max_health),(3,5))
        self.assertEqual(len(self.keywords(g,i)),1)

    def test_return_and_resummon_same_entity_cannot_receive_old_bonus_or_consume_rng(self):
        g=self.game(mode='bounce',hand=(P+'kill',));i=self.eid(g);ref=BoardPresenceReference.capture(g.state,i);before=g._rng.getstate()
        self.op(g,'kill',self.enemy(g));e=g.state.entities[i]
        self.assertEqual((e.zone,e.attack,e.max_health),(Zone.BOARD,3,5));self.assertEqual(self.keywords(g,i),set())
        self.assertNotEqual(BoardPresenceReference.capture(g.state,i),ref);self.assertEqual(g._rng.getstate(),before);self.portable(g)

    def test_death_between_parts_stops_bonus_without_rng(self):
        g=self.game(mode='destroy',hand=(P+'kill',));i=self.eid(g);before=g._rng.getstate();self.op(g,'kill',self.enemy(g))
        self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD);self.assertEqual(self.keywords(g,i),set())
        self.assertEqual(g._rng.getstate(),before)

    def test_wait_after_stats_before_roll_restores_full_reward_and_finishes_identically(self):
        g=self.game(mode='wait',hand=(P+'kill',));i=self.eid(g);before=g._rng.getstate();self.op(g,'kill',self.enemy(g))
        self.assertEqual(g.state.pending_choice.player_id,2);self.assertEqual(g.state.entities[i].attack,5)
        self.assertEqual(g._rng.getstate(),before);other=self.portable(g);self.choose(g);self.choose(other)
        self.assertTrue(g.snapshot()==other.snapshot());self.assertEqual(len(self.keywords(g,i)),1);self.portable(g)

    def test_waiting_return_reentry_is_stale_after_independent_json_restore(self):
        g=self.game(mode='wait',hand=(P+'kill',));i=self.eid(g);self.op(g,'kill',self.enemy(g));before=g._rng.getstate()
        other=self.portable(g);self.choose(g,'bounce');self.choose(other,'bounce')
        self.assertTrue(g.snapshot()==other.snapshot());self.assertEqual(self.keywords(g,i),set())
        self.assertEqual(g._rng.getstate(),before);self.assertEqual(g.state.entities[i].attack,3)

    def test_late_failure_rolls_back_death_growth_keywords_rng_mana_and_history(self):
        g=self.game(hand=(P+'kill_fail',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.op(g,'kill_fail',self.enemy(g))
        self.assertTrue(g.snapshot()==before)

    def test_failed_pending_choice_preserves_whole_original_wait_then_can_continue(self):
        g=self.game(mode='wait',hand=(P+'kill',));self.op(g,'kill',self.enemy(g));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertTrue(g.snapshot()==before);self.choose(g);self.portable(g)

    def test_second_seat_owner_interval_and_private_pending_work_never_enter_player_view(self):
        g=self.game(mode='wait',seat=2,hand=(P+'kill',));i=self.eid(g);self.op(g,'kill',self.enemy(g))
        self.assertEqual(g.state.pending_choice.player_id,1);before=g.snapshot()
        for pid in (1,2):
            visible=json.dumps(g.for_player(pid).observe());g.for_player(pid).legal_actions()
            for key in ('presence_id','BoardPresenceReference','GrantRandomBonusEffects','rng_state','before_state'):
                self.assertNotIn(key,visible)
        self.assertTrue(g.snapshot()==before);self.choose(g);self.assertEqual(g.state.entities[i].attack,5);self.portable(g)

    def test_typed_reward_references_reject_mismatch_unknown_and_future_even_when_noop(self):
        g=self.game();i=self.eid(g);ref=BoardPresenceReference.capture(g.state,i)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        for effect in (GrantRandomBonusEffects(i,1,i,ref),BuffCapturedMinion(ref,2,2,i),
                GrantCapturedKeyword(ref,Keyword.TAUNT,i)):
            self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(effect)))),effect)
        with self.assertRaises(ValueError):GrantRandomBonusEffects(i+1,1,i,ref)
        for bad in (replace(ref,presence_id=g.state.next_order),replace(ref,entity_id=g.state.next_entity_id+1)):
            for effect in (GrantRandomBonusEffects(i,0,i,bad)if bad.entity_id==i else None,
                    BuffCapturedMinion(bad,2,2,i),GrantCapturedKeyword(bad,Keyword.TAUNT,i)):
                if effect is not None:
                    with self.assertRaises(ValueError):effect.validate_in_state(g.state)
                    with self.assertRaises(ValueError):codec.decode(codec.encode(effect))
