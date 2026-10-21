"""Real-source prerequisites: frozen physical Attack and actual entry stats."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.card_creation import CreatedMinionStats
from hs_sim.engine.effects import (ChoiceOption, CopyMinion, Damage, Destroy, InvokeBehavior, RequestChoice, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass, CardMetadata, Rarity, SummonStats
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.recruit_summons import validate_record
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.successful_summons import ENTRY_STATS_KEY
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.zones import AddToDeck
from tools.card_batch import canonical, check_face, read

P='fixture.entryfacts.';OP=P+'op.'
ZERO,ONE,PLAIN,REBORN,WATCH=(P+x for x in ('zero','one','plain','reborn','watch'))
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
SUPPORT=Path(__file__).resolve().parents[1]/'data/support/zeoth-recruit-foundation-v1.json'


@lru_cache(maxsize=None)
def fixture(mode=None,role='writer'):
    if role not in('writer','reader'):raise ValueError('Independent registry role required')
    r=build_registry()
    for cid,attack,kw in((ZERO,0,()),(ONE,1,()),(PLAIN,9,()),(REBORN,2,(Keyword.REBORN,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=6,keywords=kw,metadata=META))
    def fail(c):raise ResolutionError('Entry facts deliberate failure')
    r.register_behavior(P+'fail',fail)
    def seed(c):return tuple(AddToDeck(c.player_id,cid,position='bottom',source_id=c.source_id,
        minion_stats=CreatedMinionStats(set_to=SummonStats(attack,7)))for cid,attack in((ZERO,1),(ONE,0)))
    def recruit(c,basis='current',attack=0):return(SummonFromZone(c.player_id,
        query=PoolQuery(attack_equals=attack),source_id=c.source_id,cause=SummonCause.capture(c),attack_basis=basis),)
    def source(c):return next(e for e in c.state.entities.values()if e.card_id==ONE and e.zone==Zone.BOARD)
    operations={
        'seed':seed,'current':lambda c:recruit(c),'printed':lambda c:recruit(c,'printed'),
        'empty':lambda c:recruit(c,attack=3),
        'zero_health':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(ZERO,SummonStats(0,0)),),SummonCause.capture(c)),),
        'reborn':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(REBORN),),SummonCause.capture(c)),),
        'kill_reborn':lambda c:(Destroy(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==REBORN),c.source_id),),
        'copy_damaged':lambda c:(Damage(source(c).id,2,c.source_id),
            CopyMinion(source(c).id,c.player_id,cause=SummonCause.capture(c))),
    }
    for name,body in operations.items():
        r.register_behavior(OP+name,body);r.register_card(CardDefinition(OP+name,name,CardType.SPELL,on_play=OP+name))
    if mode:
        def watch(c):
            e=c.state.entities[c.event.target_id]
            if e.card_id!=ONE:return()
            if mode=='kill':return(Destroy(e.id,c.source_id),)
            if mode=='transform':return(Transform(e.id,PLAIN),)
            if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return(RequestChoice(3-c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('fail','Fail',effects=(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),source_id=c.source_id),)
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,
            triggers=(TriggerSpec('minion_summoned',P+'watch'),)))
    return r


class PhysicalRecruitEntryFactTests(unittest.TestCase):
    def game(self,mode=None,*,ops=('seed','current'),board=(),seat=1):
        self.mode=mode;self.seat=seat
        if mode:board=(WATCH,*board)
        own=PlayerSetup('HERO_08',hand=tuple(OP+x for x in ops),board=board,mana=10,max_mana=10)
        other=PlayerSetup('HERO_01',mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,seed=365),fixture(mode))
    def op(self,g,name):
        pid=g.state.active_player;i=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==OP+name)
        g.apply(PlayCard(pid,i));return i
    def seed(self,g):self.op(g,'seed');return tuple(g.state.players[self.seat].deck)
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=fixture(self.mode,'reader')
        for other in(g.clone(),Game.from_snapshot(s,r),replay(build_replay(g),r)):
            self.assertTrue(other.snapshot()==s,'Original current-Attack basis and entry stats must restore')
        return Game.from_snapshot(s,r)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()
            if k not in('schema_version','events','events_hash','state_hash')});return s

    def test_real_zeoth_full_raw_two_primary_faces_without_executable_adapter_claim(self):
        d=read(SUPPORT);r=d['record'];self.assertEqual((r['id'],r['dbf_id']),('BE_790',130000))
        self.assertEqual(canonical(r),d['record_sha256']);self.assertFalse(d['executable_adapter'])
        for o in d['complete_primary_observations']:check_face(r,o['face'],o['locale'])

    def test_current_attack_recruits_modified_printed_one_and_preserves_original_physical_entity(self):
        g=self.game();zero,one=self.seed(g);self.op(g,'current');root=g.state.recruit_summon_history[-1]
        self.assertEqual(root.rounds[0].selected.entity_id,one);self.assertEqual(g.state.entities[one].zone,Zone.BOARD)
        self.assertEqual(g.state.entities[zero].zone,Zone.DECK);self.assertEqual(root.spec.attack_basis,'current')
        self.assertEqual([x.current_attack for x in root.rounds[0].basis.inventory],[1,0]);self.portable(g)

    def test_old_printed_default_does_not_switch_to_modified_deck_attack(self):
        g=self.game(ops=('seed','printed'));zero,one=self.seed(g);self.op(g,'printed');root=g.state.recruit_summon_history[-1]
        self.assertEqual(root.rounds[0].selected.entity_id,zero);self.assertEqual(root.spec.attack_basis,'printed')
        self.assertTrue(all(x.current_attack is None for x in root.rounds[0].basis.inventory));self.assertEqual(g.state.entities[one].zone,Zone.DECK)

    def test_no_current_match_keeps_complete_inventory_and_consumes_no_rng(self):
        g=self.game(ops=('seed','empty'));self.seed(g);before=g._rng.getstate();self.op(g,'empty')
        self.assertEqual(g._rng.getstate(),before);r=g.state.recruit_summon_history[-1]
        self.assertEqual(r.status,'exhausted');self.assertEqual(len(r.rounds[0].basis.inventory),2)

    def test_entry_fact_records_current_attack_remaining_and_maximum_health_at_original_publication(self):
        g=self.game();self.seed(g);self.op(g,'current');row=g.state.successful_summon_history[-1]
        self.assertEqual((row.entry_attack,row.entry_health,row.entry_max_health),(0,7,7))
        event=g.events[row.event_sequence-1];self.assertEqual(tuple(dict(event.data)[ENTRY_STATS_KEY]),(0,7,7));self.portable(g)

    def test_entry_fact_survives_immediate_entry_reaction_death_and_transform(self):
        for mode in('kill','transform'):
            with self.subTest(mode=mode):
                g=self.game(mode);self.seed(g);self.op(g,'current');row=g.state.successful_summon_history[-1]
                self.assertEqual((row.card_id,row.entry_attack,row.entry_health,row.entry_max_health),(ONE,0,7,7))
                self.assertEqual(g.state.entities[row.entity_id].zone,Zone.GRAVEYARD if mode=='kill'else Zone.BOARD)
                if mode=='transform':self.assertEqual(g.state.entities[row.entity_id].card_id,PLAIN)
                self.portable(g)

    def test_current_board_copy_entry_separates_remaining_from_maximum_health(self):
        g=self.game(ops=('seed','current','copy_damaged'));self.seed(g);self.op(g,'current');self.op(g,'copy_damaged')
        row=g.state.successful_summon_history[-1];self.assertEqual((row.entry_attack,row.entry_health,row.entry_max_health),(0,5,7))
        self.portable(g)

    def test_zero_health_entry_remains_real_success_before_normal_death(self):
        g=self.game(ops=('zero_health',));self.op(g,'zero_health');row=g.state.successful_summon_history[-1]
        self.assertEqual((row.entry_attack,row.entry_health,row.entry_max_health),(0,0,0));self.assertEqual(g.state.entities[row.entity_id].zone,Zone.GRAVEYARD)
        self.portable(g)

    def test_reborn_entry_has_actual_one_remaining_health_and_original_maximum(self):
        g=self.game(ops=('reborn','kill_reborn'));self.op(g,'reborn');self.op(g,'kill_reborn');row=g.state.successful_summon_history[-1]
        self.assertIsNotNone(row.reborn_death_id);self.assertEqual((row.entry_attack,row.entry_health,row.entry_max_health),(2,1,6));self.portable(g)

    def test_wait_restores_full_frozen_basis_and_entry_facts_then_finishes_identically(self):
        g=self.game('wait');self.seed(g);self.op(g,'current');other=self.portable(g);self.choose(g);self.choose(other)
        self.assertTrue(g.snapshot()==other.snapshot());self.portable(g)

    def test_late_entry_failure_and_failed_choice_restore_all_facts_rng_and_physical_zones(self):
        g=self.game('fail');self.seed(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.op(g,'current')
        self.assertTrue(g.snapshot()==before)
        g=self.game('wait');self.seed(g);self.op(g,'current');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertTrue(g.snapshot()==before);self.choose(g)

    def test_tampered_current_basis_or_candidate_attack_rejected_against_original_receipts(self):
        g=self.game();self.seed(g);self.op(g,'current');root=g.state.recruit_summon_history[-1];basis=root.rounds[0].basis
        with self.assertRaises(ValueError):replace(basis,attack_basis='printed').__post_init__()
        with self.assertRaises(ValueError):replace(basis.inventory[0],current_attack=True).__post_init__()
        bad=replace(basis,inventory=tuple(replace(x,current_attack=0)for x in basis.inventory))
        modified=replace(root,rounds=(replace(root.rounds[0],basis=bad),))
        with self.assertRaises(ValueError):validate_record(g.state,g.registry,modified)

    def test_rehashed_entry_fact_and_private_original_event_stats_cannot_diverge(self):
        g=self.game();self.seed(g);self.op(g,'current');s=deepcopy(g.snapshot())
        s['state']['successful_summon_history'][0]['entry_attack']=99
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),fixture())
        s=deepcopy(g.snapshot());s['state']['successful_summon_history'][0].pop('entry_health')
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),fixture())

    def test_private_deck_attack_and_entry_receipts_do_not_enter_either_player_projection(self):
        g=self.game('wait',seat=2);self.seed(g);self.op(g,'current');before=g.snapshot()
        for pid in(1,2):
            visible=json.dumps(g.for_player(pid).observe());g.for_player(pid).legal_actions()
            for key in(ENTRY_STATS_KEY,'entry_max_health','current_attack','recruit_summon_history'):
                self.assertNotIn('"'+key+'"',visible)
        self.assertTrue(g.snapshot()==before);self.choose(g);self.portable(g)

    def test_exact_current_attack_requires_cause_numeric_selector_and_closed_basis(self):
        for kwargs in(dict(attack_basis='unknown'),dict(attack_basis=True),dict(attack_basis='current'),
                dict(query=PoolQuery(attack_equals=0),attack_basis='current')):
            with self.assertRaises(ValueError):SummonFromZone(1,**kwargs)
        g=self.game();self.seed(g);self.op(g,'current');row=g.state.successful_summon_history[-1]
        with self.assertRaises(ValueError):replace(row,entry_health=True).__post_init__()
        with self.assertRaises(ValueError):replace(row,entry_health=row.entry_max_health+1).__post_init__()
        old=g.snapshot();old['schema_version']=518
        with self.assertRaises(SnapshotError):Game.from_snapshot(old,fixture())
