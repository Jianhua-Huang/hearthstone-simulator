"""A completed empty Deathrattle must still settle an owed native refill."""
from functools import lru_cache
import json
import unittest

from hs_sim.engine import (AppendageSpec,Attack,CardDefinition,CardType,EndTurn,Game,Keyword,
    PlayCard,PlayerSetup,Registry,Scenario,SelectChoice,SnapshotError)
from hs_sim.engine.colossal_reserves import ColossalReserveProfile,source
from hs_sim.engine.effects import (ChoiceOption,Damage,Destroy,InvokeBehavior,
    RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash

P='fixture.refill-boundary.'
BODY,LIMB,FILL,KILL=(P+s for s in ('body','limb','fill','kill'))


@lru_cache(maxsize=None)
def registry(mode,role):
    assert mode in ('empty','wait','kill-body','terminal','summon')
    assert role in ('writer','reader')
    r=Registry('refill-boundary-v1:'+mode)
    r.register_card(CardDefinition('hero','hero',CardType.HERO,health=30))
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,attack=2,health=8))
    r.register_card(CardDefinition(BODY,BODY,CardType.MINION,attack=2,health=12,
        keywords=(Keyword.COLOSSAL,),colossal=(AppendageSpec(LIMB),)*5))
    r.register_colossal_reserve_profile(ColossalReserveProfile(BODY))
    def fail(c):raise ResolutionError('Deliberate refill-boundary failure')
    r.register_behavior(P+'fail',fail)
    def death(c):
        if mode=='wait':return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Finish empty Deathrattle'),
            ChoiceOption('bad','Rollback',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        if mode=='terminal':return (Damage(c.state.players[3-c.player_id].hero_id,100,c.source_id),)
        if mode=='kill-body':return tuple(Destroy(i,c.source_id)for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id==BODY)
        if mode=='summon':
            from hs_sim.engine.effects import Summon
            return (Summon(c.player_id,FILL),)
        return ()
    r.register_behavior(P+'death',death)
    r.register_card(CardDefinition(LIMB,LIMB,CardType.MINION,attack=1,health=1,deathrattle=P+'death'))
    r.register_behavior(KILL,lambda c:(Destroy(c.target_id,c.source_id),))
    r.register_card(CardDefinition(KILL,KILL,CardType.SPELL,on_play=KILL,requires_target=True))
    return r


class ColossalRefillBoundaryTests(unittest.TestCase):
    def game(self,mode='empty',runtime='release'):
        self.mode=mode
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=(BODY,KILL,KILL),board=(FILL,)*3,
            mana=10,max_mana=10),PlayerSetup('hero',board=(FILL,)*2)),seed=376),registry(mode,'writer'),mode=runtime)
        self.play(g,BODY)
        self.assertEqual((len(g.state.players[1].board),self.remaining(g)),(7,2))
        g.apply(EndTurn(1))
        return g
    def ids(self,g,cid):return [i for i in g.state.players[1].board if g.state.entities[i].card_id==cid]
    def play(self,g,cid,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target));return eid
    def remaining(self,g):return source(g.state.entities[self.ids(g,BODY)[0]]).colossal_remaining
    def kill_limb(self,g):
        attacker=next(i for i in g.state.players[2].board if not g.state.entities[i].attacks_this_turn)
        g.apply(Attack(2,attacker,self.ids(g,LIMB)[0]))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=registry(self.mode,'reader')
        self.assertIsNot(r,g.registry)
        self.assertEqual(Game.from_snapshot(s,r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        return s
    def test_empty_deathrattle_settles_before_stable_boundary_in_both_modes(self):
        for runtime in ('release','debug'):
            with self.subTest(runtime=runtime):
                g=self.game(runtime=runtime);old=self.ids(g,LIMB)[0]
                self.kill_limb(g)
                self.assertEqual((len(g.state.players[1].board),self.remaining(g)),(7,1))
                self.assertNotIn(old,self.ids(g,LIMB));self.assertTrue(g.state.deathrattle_history[-1].completed)
                self.portable(g)
    def test_waiting_last_deathrattle_resumes_once_and_bad_choice_rolls_back(self):
        g=self.game('wait');self.kill_limb(g);before=self.portable(g)
        q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,q.id,('bad',)))
        self.assertEqual(g.snapshot(),before)
        g.apply(SelectChoice(1,q.id,('ok',)))
        self.assertEqual((len(g.state.players[1].board),self.remaining(g)),(7,1));self.portable(g)
    def test_two_separate_empty_deaths_spend_each_owed_reserve_exactly_once(self):
        g=self.game()
        for expected in (1,0):
            self.kill_limb(g)
            self.assertEqual((len(g.state.players[1].board),self.remaining(g)),(7,expected))
        self.portable(g)
    def test_deathrattle_fills_slot_before_refill_can_spend_it(self):
        g=self.game('summon');self.kill_limb(g)
        self.assertEqual((len(g.state.players[1].board),self.remaining(g)),(7,2));self.portable(g)
    def test_deathrattle_killing_body_or_ending_game_cancels_refill(self):
        for mode in ('kill-body','terminal'):
            with self.subTest(mode=mode):
                g=self.game(mode);self.kill_limb(g)
                if mode=='kill-body':self.assertFalse(self.ids(g,BODY))
                else:self.assertEqual(g.state.status,'finished')
                self.assertEqual(len(self.ids(g,LIMB)),2);self.portable(g)
    def test_restore_still_rejects_a_dropped_owed_waiting_refill(self):
        g=self.game('wait');self.kill_limb(g);s=self.portable(g)
        # Drop the continuation and pretend its accepted Deathrattle completed.
        s['resolution_frame']=None;s['state']['pending_choice']=None
        for row in s['state']['deathrattle_history']:row['completed']=True
        s['events_hash']=canonical_hash(s['events'])
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in
            ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry(self.mode,'reader'))
