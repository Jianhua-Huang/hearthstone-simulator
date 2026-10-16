"""Printed Deathrattle qualification preserves historical active-at-death policy."""
import json
from types import SimpleNamespace
import unittest
from hs_sim.engine import CardDefinition,CardType,Game,PlayCard,PlayerSetup,Scenario,SnapshotError
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import GrantDeathrattle,Silence,Transform
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.resurrection_summons import primary_resurrected_body
from hs_sim.engine.summon_sources import DeathQuery,death_candidates
from test_death_followup_cards import registry as base_registry

NATIVE='TLC_621';HIGH='EDR_572';PLAIN='CORE_CS2_182'


def registry():
    r=base_registry();r.register_behavior('p38.noop',lambda c:())
    bodies={'silence':lambda c:(Silence(c.target_id),),
        'grant':lambda c:(GrantDeathrattle(c.target_id,'p38.noop',c.source_id),),
        'plain':lambda c:(Transform(c.target_id,PLAIN),),'native':lambda c:(Transform(c.target_id,NATIVE),)}
    for key,body in bodies.items():
        r.register_behavior('p38.'+key,body);r.register_card(CardDefinition('p38.'+key,key,CardType.SPELL,on_play='p38.'+key,requires_target=True))
    return r


class PrintedDeathQueryTests(unittest.TestCase):
    def game(self,hand,board):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08')),seed=385),registry())
    def play(self,g,cid,target):
        eid=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid);g.apply(PlayCard(1,eid,target))
    def candidates(self,g,**kw):return[d.card_id for d in death_candidates(g.state,g.registry,1,DeathQuery(**kw))]

    def test_printed_silenced_native_and_active_granted_plain_remain_distinct(self):
        g=self.game(('p38.silence','p38.grant','k21.kill','k21.kill'),(NATIVE,PLAIN));native,plain=g.state.players[1].board
        self.play(g,'p38.silence',native);self.play(g,'p38.grant',plain)
        self.play(g,'k21.kill',native);self.play(g,'k21.kill',plain)
        self.assertEqual(self.candidates(g,has_deathrattle=True,deathrattle_basis='printed'),[NATIVE])
        self.assertEqual(self.candidates(g,has_deathrattle=True),[PLAIN])
        self.assertEqual(self.candidates(g,has_deathrattle=False,deathrattle_basis='printed'),[PLAIN])
        self.assertEqual(self.candidates(g,has_deathrattle=False),[NATIVE])

    def test_printed_qualification_uses_identity_at_death_after_transformation(self):
        g=self.game(('p38.plain','p38.native','k21.kill','k21.kill'),(NATIVE,PLAIN));first,second=g.state.players[1].board
        self.play(g,'p38.plain',first);self.play(g,'p38.native',second)
        self.play(g,'k21.kill',first);self.play(g,'k21.kill',second)
        self.assertEqual(self.candidates(g,has_deathrattle=True,deathrattle_basis='printed'),[NATIVE])
        self.assertEqual(g.state.death_history[1].entity_id,second)

    def test_existing_printed_cost_bounds_and_controller_filters_still_apply(self):
        g=self.game(('k21.control','k21.kill','k21.kill'),(NATIVE,HIGH));low,high=g.state.players[1].board
        self.play(g,'k21.control',low);self.play(g,'k21.kill',low);self.play(g,'k21.kill',high)
        self.assertEqual(self.candidates(g,cards=PoolQuery(max_cost=4),has_deathrattle=True,deathrattle_basis='printed'),[])
        self.assertEqual(self.candidates(g,side='enemy',cards=PoolQuery(max_cost=4),has_deathrattle=True,deathrattle_basis='printed'),[NATIVE])
        self.assertEqual(self.candidates(g,cards=PoolQuery(min_cost=5),has_deathrattle=True,deathrattle_basis='printed'),[HIGH])

    def test_strict_basis_and_codec_require_complete_saved_query(self):
        for value in(None,True,0,'current','both'):
            with self.assertRaises(ValueError):DeathQuery(deathrattle_basis=value)
        codec=FrameCodec(default_mechanics(),registry());query=DeathQuery(has_deathrattle=True,deathrattle_basis='printed')
        encoded=codec.encode(query);self.assertEqual(codec.decode(json.loads(json.dumps(encoded))),query)
        del encoded['fields']['deathrattle_basis']
        with self.assertRaises(ValueError):codec.decode(encoded)

    def test_previous_schema_is_rejected_for_changed_query_layout(self):
        g=self.game((),());saved=g.snapshot();self.assertEqual(saved['schema_version'],274);saved['schema_version']=273
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())

    def test_primary_body_lookup_requires_actual_original_resurrection(self):
        g=self.game((),());context=SimpleNamespace(state=g.state,target_id=g.state.players[1].hero_id,death=None)
        with self.assertRaises(ResolutionError):primary_resurrected_body(context)
