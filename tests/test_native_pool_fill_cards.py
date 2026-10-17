"""Real ruleset capacity, original fill receipts and two native Battlecries."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json
import random
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_pool_fill_cards import CHAMPION,MUROZOND,POOL_ID,load_batch
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,
    Game,Keyword,PlayCard,PlayerSetup,Ruleset,Scenario,SelectChoice,SnapshotError)
from hs_sim.engine.effects import (Buff,ChoiceOption,Damage,Destroy,InvokeBehavior,RequestChoice,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec,RewindSpec,TargetSpec,Zone
from hs_sim.engine.pools import (FillBoardFromPool,GenerationContext,PoolCard,PoolDefinition,
    PoolMember,PoolQuery,matches_metadata,SPECIAL_GENERATION_KEYWORDS)
from hs_sim.engine.pool_summons import PoolFillCapacity
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.targets import canonical_digest

TEST='k139.';ONE=TEST+'one';DRAGON=TEST+'dragon';ALL=TEST+'all';YETI='CORE_CS2_182'
CONTEXT=GenerationContext('k139-complete-explicit-test-pool','experimental')
MEMBERS=(ONE,DRAGON,ALL)
ONE_QUERY=PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=1,max_cost=1)
DRAGON_QUERY=PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('dragon',))


def registry(mode=None,members=MEMBERS):
    r=build_registry()
    for cid,cost,tribes in((ONE,1,()),(DRAGON,2,('dragon',)),(ALL,3,('all',))):
        c=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=3,
            metadata=CardMetadata(True,(CardClass.NEUTRAL,),None,tribes=tribes))
        r.register_card(c);r.register_pool_card(PoolCard.from_definition(c))
    r.register_pool(PoolDefinition(POOL_ID,'k139-native-fill-v1',CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(cid)for cid in members),complete=True))
    def fail(c):raise ResolutionError('K139 deliberate continuation failure')
    def retry(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CHAMPION)
        return (TriggerBattlecry(MinionReference.capture(e),c.source_id),)
    def defer(c):
        effect=FillBoardFromPool(2,POOL_ID,ONE_QUERY,c.source_id,SummonCause.capture(c))
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Fill after waiting',(effect,)),),c.source_id),)
    bodies=dict(noop=lambda c:(),fail=fail,
        wound=lambda c:(Damage(c.state.players[1].hero_id,7,c.source_id),),
        enhance=lambda c:(Buff(c.state.players[1].hero_id,health=10,source_id=c.source_id),),
        rewind=retry,defer=defer)
    for name,body in bodies.items():
        r.register_behavior(TEST+name,body)
        if name in('fail','noop'):continue
        if name=='defer':
            card=CardDefinition(TEST+name,name,CardType.MINION,health=2,battlecry=TEST+name)
        else:
            kwargs=dict(keywords=(Keyword.REWIND,),rewind=RewindSpec())if name=='rewind'else{}
            card=CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,**kwargs)
        r.register_card(card)
    r.register_card(CardDefinition(TEST+'dormant','Physical sleeping occupant',CardType.MINION,
        attack=1,health=3,dormant_turns=2))
    r.register_card(CardDefinition(TEST+'location','Physical location occupant',CardType.LOCATION,
        durability=3,on_use=TEST+'noop'))
    if mode:
        def eligible(c):
            e=c.event
            if mode=='healing':return e.source_id is not None and c.state.entities[e.source_id].card_id==MUROZOND
            expected=(CHAMPION,MUROZOND)if mode=='before'else(ONE,DRAGON,ALL)
            return e.target_id is not None and c.state.entities[e.target_id].card_id in expected
        def watch(c):
            if mode=='direct_fail':return (InvokeBehavior(TEST+'fail',c.source_id,c.player_id),)
            options=[ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(
                InvokeBehavior(TEST+'fail',c.source_id,c.player_id),))]
            if mode!='healing':
                options.extend((ChoiceOption('occupy','Occupy another original free slot',(Summon(2,YETI),)),
                    ChoiceOption('remove','Remove this arrived minion',(Destroy(c.event.target_id,c.source_id),))))
                source=next((i for i in c.state.players[1].board if c.state.entities[i].card_id in(CHAMPION,MUROZOND)),None)
                if source is not None:options.append(ChoiceOption('source','Remove original cause',(Destroy(source,c.source_id),)))
            return (RequestChoice(c.player_id,tuple(options),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        event='health_resolved'if mode=='healing'else'minion_summoned'
        r.register_card(CardDefinition(TEST+'watch','Ordinary fill reaction witness',CardType.MINION,health=20,
            limited_triggers=(LimitedTriggerSpec(event,TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r


@lru_cache(maxsize=None)
def shared(mode,members):return registry(mode,members)


class NativePoolFillTests(unittest.TestCase):
    def game(self,hand=(CHAMPION,),board=(),enemy=(),mode=None,members=MEMBERS,limit=7):
        self.config=(mode,members)
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*12,
            mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*12,
            mana=50,max_mana=50,mana_cap=50)),seed=139,generation_context=CONTEXT),shared(*self.config),Ruleset(max_board=limit))
    def eid(self,g,cid,p=1,zone='board'):
        return next(i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid=CHAMPION):
        i=self.eid(g,cid,zone='hand');g.apply(PlayCard(1,i,position=len(g.state.players[1].board)
            if g.state.entities[i].kind==CardType.MINION else None));return i
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config))
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s);return other
    def root(self,g):return g.state.pool_summon_history[-1]
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as e:Game.from_snapshot(s,shared(*self.config))
        self.assertNotIn('digest mismatch',str(e.exception))

    def test_complete_native_faces_and_all_metadata_without_inferred_dragon_type(self):
        d=load_batch();r=shared(None,MEMBERS);self.assertEqual(len(d['official_observations']),4)
        for row in d['cards']:
            raw=row['record'];c=r.card(raw['id']);self.assertEqual(canonical_digest(raw),row['record_sha256'])
            self.assertEqual((c.cost,c.attack,c.health),(raw['cost'],raw['attack'],raw['health']))
            self.assertEqual(c.metadata,metadata_from_record(raw))
        self.assertEqual(r.card(CHAMPION).keywords,(Keyword.RUSH,));self.assertEqual(r.card(MUROZOND).metadata.tribes,())
        self.assertFalse(d['formal_pool_complete']or d['cn_calibrated'])

    def test_real_champion_fills_actual_two_seven_or_eight_capacity_and_pays_once(self):
        for limit in(2,7,8):
            with self.subTest(limit=limit):
                g=self.game(limit=limit);source=self.play(g);root=self.root(g);cap=root.spec.fill_capacity
                self.assertEqual((cap.player_id,cap.limit,cap.occupants,root.spec.count),(2,limit,(),limit))
                self.assertEqual(len(g.state.players[2].board),limit);self.assertEqual(g.state.players[1].mana,42)
                self.assertEqual(root.spec.cause.source.entity_id,source);self.assertEqual(root.spec.cause.player_id,1)
                self.assertTrue(all(g.state.entities[i].card_id==ONE for i in g.state.players[2].board))

    def test_existing_dormant_and_location_occupants_both_reduce_real_free_slots(self):
        g=self.game(enemy=(TEST+'dormant',TEST+'location',YETI),limit=8);old=tuple(g.state.players[2].board);self.play(g)
        root=self.root(g);self.assertEqual(root.spec.count,5);self.assertEqual(tuple(a.entity_id for a in root.spec.fill_capacity.occupants),old)
        self.assertEqual(g.state.players[2].board[:3],list(old));self.assertEqual(len(g.state.players[2].board),8)
        self.assertFalse(g.state.entities[old[0]].active)

    def test_full_destination_records_zero_root_without_consuming_rng(self):
        g=self.game(enemy=(YETI,)*7);rng=g._rng.getstate();self.play(g);root=self.root(g)
        self.assertEqual((root.spec.count,root.selected,root.entry_root_ids,root.status),(0,(),(),'completed'))
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(len(root.spec.fill_capacity.occupants),7)

    def test_empty_qualified_pool_records_empty_selection_without_inventing_minions(self):
        g=self.game(members=(DRAGON,));rng=g._rng.getstate();self.play(g);root=self.root(g)
        self.assertEqual((root.spec.count,root.selected,root.status),(7,(),'completed'))
        self.assertEqual(g._rng.getstate(),rng);self.assertFalse(g.state.players[2].board)

    def test_capacity_is_captured_at_execution_after_real_entry_reaction(self):
        g=self.game(mode='before');self.play(g);self.assertFalse(g.state.pool_summon_history)
        self.choose(g,'occupy');root=self.root(g)
        self.assertEqual((len(root.spec.fill_capacity.occupants),root.spec.count),(1,6))
        self.assertEqual(len(g.state.players[2].board),7)

    def test_original_draws_wait_restore_replay_and_failed_resume_never_redraw(self):
        g=self.game(mode='arrive',limit=8);self.play(g);root=self.root(g);draw=root.selected;rng=root.rng_after
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.root(g).selected,draw)
        self.assertEqual(self.root(g).rng_after,rng);self.assertEqual(len(g.state.players[2].board),8)

    def test_later_slot_changes_do_not_resize_original_accepted_attempts(self):
        for decision,expected in(('occupy',7),('remove',6)):
            with self.subTest(decision=decision):
                g=self.game(mode='arrive');self.play(g);self.choose(g,decision);root=self.root(g)
                self.assertEqual((root.spec.count,len(root.selected),len(root.entry_root_ids)),(7,7,7))
                self.assertEqual(len(g.state.players[2].board),expected)

    def test_accepted_fill_survives_source_leaving_and_direct_failure_rolls_back_payment(self):
        g=self.game(mode='arrive');source=self.play(g);self.choose(g,'source')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.players[2].board),7)
        g=self.game(mode='direct_fail');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.play(g)
        self.assertEqual(g.snapshot(),saved)

    def test_champion_native_rush_can_use_actual_new_enemy_minion(self):
        g=self.game();source=self.play(g);enemy=g.state.players[2].board[0]
        g.apply(Attack(1,source,enemy));self.assertEqual(g.state.entities[enemy].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[source].attacks_this_turn,1)

    def test_murozond_full_dragon_query_includes_all_type_and_excludes_non_dragons(self):
        g=self.game((MUROZOND,));source=self.play(g,MUROZOND);root=self.root(g)
        self.assertEqual({m.card_id for m in root.spec.basis.candidates},{DRAGON,ALL})
        self.assertEqual((root.spec.basis.player_id,root.spec.fill_capacity.remaining,root.spec.count),(1,6,6))
        self.assertEqual(g.state.players[1].board[0],source);self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(g.state.turn_schedule.skip_counts,(1,0));self.assertEqual(g.state.players[1].mana,41)

    def test_murozond_fresh_full_heal_uses_actual_maximum_then_skips_one_real_next_slot(self):
        from hs_sim.engine.health_outcomes import health_result
        g=self.game((TEST+'enhance',TEST+'wound',MUROZOND));self.play(g,TEST+'enhance');self.play(g,TEST+'wound')
        hero=g.state.players[1].hero_id;self.assertEqual((g.state.entities[hero].health,g.state.entities[hero].max_health),(33,40))
        source=self.play(g,MUROZOND);result=next(v for e in g.events if(v:=health_result(e))is not None and v.source_id==source)
        self.assertEqual((result.base_amount,result.healed,result.overheal),(40,7,33));self.assertEqual(g.state.entities[hero].health,40)
        g.apply(EndTurn(1));self.assertEqual(g.state.active_player,2);g.apply(EndTurn(2))
        self.assertEqual(g.state.active_player,2);self.assertEqual(g.state.turn_schedule.skip_counts,(0,0))
        self.assertEqual(sum(e.kind=='turn_skipped'and e.player_id==1 for e in g.events),1)

    def test_full_own_board_still_heals_and_schedules_skip_without_rng(self):
        g=self.game((TEST+'wound',MUROZOND),board=(YETI,)*6);self.play(g,TEST+'wound');rng=g._rng.getstate()
        self.play(g,MUROZOND);root=self.root(g)
        self.assertEqual((root.spec.count,root.selected),(0,()));self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30);self.assertEqual(g.state.turn_schedule.skip_counts,(1,0))

    def test_heal_wait_restore_and_bad_resume_does_not_duplicate_fill_or_skip(self):
        g=self.game((TEST+'wound',MUROZOND),mode='healing');self.play(g,TEST+'wound');self.play(g,MUROZOND)
        self.assertEqual(g.state.turn_schedule.skip_counts,(0,0));other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.turn_schedule.skip_counts,(1,0))
        self.assertEqual(len(g.state.pool_summon_history),1)

    def test_unknown_eligible_content_fails_before_rng_even_with_full_destination(self):
        r=shared(None,MEMBERS)
        unknown=next(c.card_id for c in r.pool_cards.values()if c.card_id not in r.cards and
            not SPECIAL_GENERATION_KEYWORDS.intersection(c.keywords)and matches_metadata(ONE_QUERY,
                card_id=c.card_id,kind=c.kind,cost=c.cost,meta=c.metadata,spell_school=c.spell_school,keywords=c.keywords))
        for enemy in((),(YETI,)*7):
            with self.subTest(full=bool(enemy)):
                g=self.game(enemy=enemy,members=(ONE,unknown));saved=g.snapshot();calls=[];original=random.Random.randrange
                def spy(rng,*a,**kw):calls.append(a);return original(rng,*a,**kw)
                with patch.object(random.Random,'randrange',autospec=True,side_effect=spy):
                    with self.assertRaises(ResolutionError):self.play(g)
                self.assertFalse(calls);self.assertEqual(g.snapshot(),saved)

    def test_fill_count_cannot_be_shrunk_and_limit_must_equal_actual_rules(self):
        g=self.game(enemy=(YETI,),mode='arrive');self.play(g);spec=self.root(g).spec;cap=spec.fill_capacity
        with self.assertRaisesRegex(ValueError,'free-slot'):replace(spec,count=spec.count-1)
        with self.assertRaisesRegex(ValueError,'actual ruleset'):replace(cap,limit=8).validate_in_state(g.state,g.registry,limit=7)
        with self.assertRaises(ValueError):replace(cap,occupants=cap.occupants*2)
        with self.assertRaises(ValueError):replace(cap,player_id=1)

    def test_rehashed_capacity_count_source_and_missing_field_are_rejected(self):
        g=self.game(enemy=(YETI,),mode='arrive');self.play(g)
        for mutation in('count','limit','duplicate','recipient','future','missing'):
            with self.subTest(mutation=mutation):
                s=deepcopy(g.snapshot());spec=s['state']['pool_summon_history'][0]['spec'];cap=spec['fill_capacity']
                if mutation=='count':spec['count']-=1
                elif mutation=='limit':cap['limit']+=1
                elif mutation=='duplicate':cap['occupants']*=2
                elif mutation=='recipient':cap['player_id']=1
                elif mutation=='future':cap['occupants'][0]['next_entity_id']=999999
                else:spec.pop('fill_capacity')
                self.reject(s)

    def test_queued_fill_request_restores_before_acceptance_and_rejects_wrong_cause(self):
        g=self.game((TEST+'defer',));self.play(g,TEST+'defer');self.assertFalse(g.state.pool_summon_history)
        other=self.portable(g)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.players[2].board),7)
        cap=self.root(g).spec.fill_capacity;self.assertEqual(cap.limit,7)
        with self.assertRaises(ValueError):FillBoardFromPool(2,POOL_ID,ONE_QUERY,1,self.root(g).spec.cause)

    def test_native_rewind_restores_original_occupancy_and_keeps_only_final_fill(self):
        g=self.game((TEST+'rewind',),board=(CHAMPION,),enemy=(YETI,));self.play(g,TEST+'rewind');self.portable(g)
        self.choose(g,'retry');root=self.root(g)
        self.assertEqual(len(g.state.pool_summon_history),1);self.assertEqual(root.spec.count,6)
        self.assertEqual(len(root.spec.fill_capacity.occupants),1);self.assertEqual(len(g.state.players[2].board),7)
        self.portable(g)

    def test_player_projection_does_not_expose_fill_capacity_or_draw_materials(self):
        g=self.game(mode='arrive');self.play(g)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('fill_capacity','occupants','pool_summon_history','pool_basis','rng_before','rng_after','resolution_frame'):
                self.assertNotIn('"'+key+'"',public)

    def test_actual_old_schema_requires_original_engine_and_existing_definitions_stay_identical(self):
        g=self.game();s=g.snapshot();s['schema_version']=345
        with self.assertRaisesRegex(SnapshotError,f'schemas 1 through {SNAPSHOT_SCHEMA_VERSION-1}'):Game.from_snapshot(s,shared(*self.config))
        with patch('hs_sim.cards.native_pool_fill_cards.register_native_pool_fill_cards',lambda r:None):before=build_registry()
        after=build_registry();self.assertEqual(set(after.cards)-set(before.cards),{CHAMPION,MUROZOND})
        for cid,c in before.cards.items():self.assertEqual(asdict(c),asdict(after.card(cid)))
        self.assertEqual(dict(before.pool_cards),dict(after.pool_cards));self.assertEqual(dict(before.pools),dict(after.pools))
        self.assertEqual(dict(before.generation_families),dict(after.generation_families))


if __name__=='__main__':unittest.main()

