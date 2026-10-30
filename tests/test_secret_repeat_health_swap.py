"""Finite native Secret repeat and atomic captured Health exchange contracts."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.engine import EndTurn,Game,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.effects import (Buff,ChoiceOption,Damage,Destroy,GainArmor,InvokeBehavior,
    RandomDamage,RequestChoice,ReturnToHand,Silence,Summon)
from hs_sim.engine.health_swaps import SwapCapturedMinionHealth
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.secret_repeats import NativeSecretRepeatProfile
from hs_sim.engine.serialization import canonical_hash

P='public.secret_pair.';MULT=P+'mult';A=P+'a';B=P+'b';TOKEN=P+'token';SECRET=P+'secret';SPELL=P+'spell'
SWAP=P+'swap';WAIT=P+'wait';HIT=P+'hit';HUSH=P+'hush';FAIL=P+'fail';OBSERVER=P+'observer'


@lru_cache(None)
def fixture(mode='plain',role='writer'):
    r=opening_registry();meta=metadata(collectible=False)
    for cid,health in((MULT,5),(A,2),(B,7),(TOKEN,1)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=3 if cid==B else 2,health=health,metadata=meta))
    r.register_native_secret_repeat_profile(NativeSecretRepeatProfile(MULT))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('Public pair/Secret deliberate rollback')))
    def pending(c):return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
        RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    def secret(c):
        if mode=='counter':return(CounterSpell(c.window.id),)
        if mode=='fresh':return(GainArmor(c.player_id,len(c.state.players[c.player_id].board)),Summon(c.player_id,TOKEN))
        effects=(GainArmor(c.player_id,1),)
        if mode=='waiting':return effects+pending(c)
        if mode=='retire':return effects+tuple(Destroy(i,c.source_id)for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id==MULT)
        return effects
    bid=P+'secret_body.'+mode;r.register_behavior(bid,secret)
    condition=bid+'.condition';r.register_secret_condition(condition,lambda c:c.window is not None and c.window.kind=='spell'if mode=='counter'else True)
    r.register_card(CardDefinition(SECRET,SECRET,CardType.SPELL,metadata=meta,keywords=(Keyword.SECRET,),secret=SecretSpec(SECRET,
        ('card_committed',)if mode=='counter'else('turn_ended',),condition,bid,turn='opponent'if mode=='counter'else'owner')))
    r.register_behavior(SPELL,lambda c:(GainArmor(c.player_id,9),))
    r.register_card(CardDefinition(SPELL,SPELL,CardType.SPELL,cost=1,on_play=SPELL,metadata=meta))
    def pair(c):
        first=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==A)
        second=c.state.entities[c.target_id]
        return SwapCapturedMinionHealth(MinionReference.capture(first),MinionReference.capture(second),c.source_id)
    def swap(c):return(pair(c),)
    def wait(c):
        effect=pair(c)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Exchange',(effect,)),
            ChoiceOption('move','Move second first',(ReturnToHand(c.target_id),effect)),
            ChoiceOption('grow','Grow then exchange',(Buff(c.target_id,0,3,c.source_id),effect)),
            ChoiceOption('fault','Exchange and fail',(effect,InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    for cid,body in((SWAP,swap),(WAIT,wait),(HIT,lambda c:(Damage(c.target_id,3,c.source_id),)),(HUSH,lambda c:(Silence(c.target_id),))):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=meta,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    def observe(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=SWAP:return()
        values=[e.health for e in c.state.entities.values()if e.zone==Zone.BOARD and e.card_id in(A,B)]
        return(GainArmor(c.player_id,sum(values)),)
    r.register_behavior(OBSERVER,observe);r.register_card(CardDefinition(OBSERVER,OBSERVER,CardType.MINION,health=5,
        metadata=meta,triggers=(TriggerSpec('stats_changed',OBSERVER),)))
    r.validate();return r


def wires(value,kind):
    if isinstance(value,dict):
        if value.get('type','').endswith('.'+kind):yield value
        for child in value.values():yield from wires(child,kind)
    elif isinstance(value,list):
        for child in value:yield from wires(child,kind)


def rehash(saved):
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
    return saved


class SecretRepeatHealthSwapTests(CardBatchTestMixin,unittest.TestCase):
    mode='plain'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role))

    def game(self,hand=(),*,board=(),enemy=(),mode='plain',enemy_hand=()):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=(A,)*5,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',hand=enemy_hand,board=enemy,deck=(A,)*5,mana=10,max_mana=10)),seed=699),fixture(mode,'writer'))
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)

    def test_secret_without_source_runs_once_and_reveals_once(self):
        g=self.game((SECRET,));self.play(g,SECRET);g.apply(EndTurn(1));self.assertEqual(self.hero(g).armor,1)
        self.assertEqual(sum(e.kind=='secret_revealed'for e in g.events),1)

    def test_native_source_two_executions_with_one_consumption_and_reveal(self):
        g=self.game((SECRET,),board=(MULT,));self.play(g,SECRET);g.apply(EndTurn(1));self.assertEqual(self.hero(g).armor,2)
        self.assertEqual(sum(e.kind=='secret_revealed'for e in g.events),1);self.assertEqual(g.state.players[1].secrets,[]);self.portable(g)

    def test_multiple_twice_sources_keep_two_body_maximum(self):
        g=self.game((SECRET,),board=(MULT,MULT));self.play(g,SECRET);g.apply(EndTurn(1));self.assertEqual(self.hero(g).armor,2)

    def test_enemy_or_silenced_native_source_does_not_contribute(self):
        g=self.game((SECRET,),enemy=(MULT,));self.play(g,SECRET);g.apply(EndTurn(1));self.assertEqual(self.hero(g).armor,1)
        g=self.game((HUSH,SECRET),board=(MULT,));self.play(g,HUSH,self.unit(g,MULT).id);self.play(g,SECRET)
        g.apply(EndTurn(1));self.assertEqual(self.hero(g).armor,1)

    def test_extra_secret_body_requeries_new_board_after_first_body(self):
        g=self.game((SECRET,),board=(MULT,),mode='fresh');self.play(g,SECRET);g.apply(EndTurn(1))
        self.assertEqual(self.hero(g).armor,3);self.assertEqual(len(g.state.players[1].board),3);self.portable(g)

    def test_accepted_extra_survives_source_retirement_during_first_body(self):
        g=self.game((SECRET,),board=(MULT,),mode='retire');self.play(g,SECRET);g.apply(EndTurn(1))
        self.assertEqual(self.hero(g).armor,2);self.assertEqual(g.state.players[1].board,[]);self.portable(g)

    def test_secret_wait_roundtrip_clone_replay_and_atomic_fault_keep_extra_once(self):
        g=self.game((SECRET,),board=(MULT,),mode='waiting');self.play(g,SECRET);g.apply(EndTurn(1))
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.finish(g);self.assertEqual(self.hero(g).armor,2);self.portable(g)

    def test_extra_counter_body_uses_original_window_without_duplicate_reveal(self):
        g=self.game((SECRET,),board=(MULT,),enemy_hand=(SPELL,),mode='counter');self.play(g,SECRET);g.apply(EndTurn(1))
        self.play(g,SPELL,player=2);self.assertEqual(self.hero(g,2).armor,0)
        self.assertEqual(sum(e.kind=='secret_revealed'for e in g.events),1);self.portable(g)

    def test_rehashed_future_secret_source_or_changed_event_is_rejected(self):
        g=self.game((SECRET,),board=(MULT,),mode='waiting');self.play(g,SECRET);g.apply(EndTurn(1));saved=g.snapshot()
        altered=deepcopy(saved);effect=next(wires(altered,'RepeatSecretBody'));ref=next(wires(effect,'MinionReference'))
        ref['fields']['zone_epoch']+=100
        with self.assertRaises((ValueError,SnapshotError)):Game.from_snapshot(rehash(altered),fixture('waiting','reader'))
        altered=deepcopy(saved);effect=next(wires(altered,'RepeatSecretBody'));effect['fields']['secret_card_id']=A
        with self.assertRaises((ValueError,SnapshotError)):Game.from_snapshot(rehash(altered),fixture('waiting','reader'))

    def test_profile_is_typed_immutable_fingerprinted_and_requires_real_minion(self):
        r=fixture('plain');self.assertEqual(r.native_secret_repeat_profiles[MULT].executions,2)
        with self.assertRaises(ValueError):NativeSecretRepeatProfile(MULT,3)
        with self.assertRaises(ValueError):NativeSecretRepeatProfile(MULT,True)
        with self.assertRaises(TypeError):r.native_secret_repeat_profiles[MULT]=NativeSecretRepeatProfile(MULT)

    def test_health_exchange_swaps_remaining_health_without_attack_owner_or_identity_change(self):
        g=self.game((HIT,SWAP),board=(A,),enemy=(B,));a=self.unit(g,A).id;b=self.unit(g,B,2).id
        self.play(g,HIT,b);self.assertEqual((g.state.entities[b].health,g.state.entities[b].max_health),(4,7))
        self.play(g,SWAP,b)
        self.assertEqual((g.state.entities[a].health,g.state.entities[a].max_health,g.state.entities[a].attack),(4,4,2))
        self.assertEqual((g.state.entities[b].health,g.state.entities[b].max_health,g.state.entities[b].attack),(2,2,3))
        self.assertEqual((g.state.entities[a].controller,g.state.entities[b].controller),(1,2));self.portable(g)

    def test_both_health_mutations_precede_either_stats_notification(self):
        g=self.game((SWAP,),board=(A,OBSERVER),enemy=(B,));self.play(g,SWAP,self.unit(g,B,2).id)
        self.assertEqual(self.hero(g).armor,18)

    def test_health_wait_uses_execution_values_and_restores_new_typed_request(self):
        g=self.game((WAIT,),board=(A,),enemy=(B,));self.play(g,WAIT,self.unit(g,B,2).id);g=self.portable(g);self.choose(g,'grow')
        self.assertEqual((self.unit(g,A).health,self.unit(g,B,2).health),(10,2));self.portable(g)

    def test_stale_pair_member_skips_whole_exchange(self):
        g=self.game((WAIT,),board=(A,),enemy=(B,));b=self.unit(g,B,2).id;self.play(g,WAIT,b);g=self.portable(g);self.choose(g,'move')
        self.assertEqual(self.unit(g,A).health,2);self.assertEqual(g.state.entities[b].zone,Zone.HAND)

    def test_health_pair_failure_rolls_back_both_attachments_events_and_original_wait(self):
        g=self.game((WAIT,),board=(A,),enemy=(B,));self.play(g,WAIT,self.unit(g,B,2).id);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual((self.unit(g,A).health,self.unit(g,B,2).health),(7,2))

    def test_health_pair_rejects_self_unknown_and_future_references(self):
        g=self.game((WAIT,),board=(A,),enemy=(B,));ref=MinionReference.capture(self.unit(g,A))
        with self.assertRaises(ValueError):SwapCapturedMinionHealth(ref,ref)
        self.play(g,WAIT,self.unit(g,B,2).id);saved=g.snapshot();effect=next(wires(saved,'SwapCapturedMinionHealth'))
        ref=next(wires(effect,'MinionReference'));ref['fields']['entered_order']=g.state.next_order+100
        with self.assertRaises((ValueError,SnapshotError)):Game.from_snapshot(rehash(saved),fixture('plain','reader'))


if __name__=='__main__':unittest.main()
