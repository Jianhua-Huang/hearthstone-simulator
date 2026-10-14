"""Native immutable deaths, two original draw policies and per-body followups."""
from copy import deepcopy
from dataclasses import dataclass
import json,unittest
from random import Random
from hs_sim.engine import CardDefinition,CardType,Game,Keyword,PlayerSetup,PoolQuery,RewindSpec,Scenario,SnapshotError,SummonCause,SummonStats,TriggerSpec,Zone,Herald
from hs_sim.engine.effects import Buff,ChoiceOption,Damage,Destroy,Effect,EquipWeapon,Freeze,GainArmor,GrantKeyword,RandomDamage,RequestChoice,Silence,Transform
from hs_sim.engine.summon_sources import DeathQuery,Resurrect,ResurrectMinion
from hs_sim.engine.resurrection_summons import ContinueDeathResurrection,ContinueQuantityResurrection,ResurrectionEntryMaterial,continue_batch,start
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
import test_v164_recruit_summons as base


@dataclass(frozen=True)
class PauseDeathEntry(Effect):
    spec:Resurrect


def mechanics():
    m=base.mechanics()
    def pause(r,e):
        work=start(r,e.spec);producer=r.state.resurrection_summon_history[-1]
        entry=continue_batch(r,work[0])
        return(RequestChoice(1,(ChoiceOption('ok','Enter selected death',()),),e.spec.source_id),*entry)
    m.register(PauseDeathEntry,pause);return m


def registry():
    r=base.registry()
    r.register_card(CardDefinition('dx_printed','Base resurrection face',CardType.MINION,cost=3,attack=1,health=5,
        keywords=(Keyword.REBORN,Keyword.TAUNT),deathrattle='gift'))
    def res(c,count=2,selection='first',distinct='death',query=DeathQuery(),player=1,follow=None,position=None):
        return Resurrect(player,count,query,distinct,selection,position,c.source_id,on_summon=follow,cause=SummonCause.capture(c))
    def direct(c,player=1,follow=None,stats=None):
        return ResurrectMinion(player,c.state.death_history[0].id,source_id=c.source_id,stats=stats,on_summon=follow,cause=SummonCause.capture(c))
    def kill(c):return[Destroy(i,c.source_id)for i in c.state.players[1].board if c.state.entities[i].card_id not in('dx_watch','dx_nested','dx_herald_watch','dx_fatal','dx_sourceface_watch','fatal_watcher')]
    def prepped(c):return[Buff(c.target_id,4,4,c.source_id),Freeze(c.target_id),Silence(c.target_id),GrantKeyword(c.target_id,Keyword.LIFESTEAL,c.source_id),Damage(c.target_id,1,c.source_id),Destroy(c.target_id,c.source_id)]
    def follow(c):return[BuffCapturedMinion(MinionReference.capture(c.state.entities[c.target_id]),1,1,c.source_id),GainArmor(c.player_id,1)]
    def waiting_follow(c):return[RequestChoice(c.player_id,(
        ChoiceOption('bad','Rollback',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),EquipWeapon(1,'body'))),
        ChoiceOption('ok','Enhance this body',tuple(follow(c)))),c.source_id)]
    r.register_behavior('dx_follow',follow);r.register_behavior('dx_wait_body',waiting_follow)
    def watch(c):
        roots=c.state.card_summon_history
        if not roots or type(roots[0].request.materials[0])is not ResurrectionEntryMaterial or len(roots[0].deliveries)!=1 or c.event.target_id!=roots[0].deliveries[0].entity.entity_id:return[]
        return[*(Destroy(i,c.source_id)for i in c.state.players[1].board if c.state.entities[i].card_id=='source'),
            Transform(c.event.target_id,'other'),RequestChoice(1,(ChoiceOption('ok','Continue',()),),c.source_id)]
    r.register_behavior('dx_watch',watch);r.register_card(CardDefinition('dx_watch','Change first resurrection',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','dx_watch'),)))
    def nested(c):
        roots=c.state.card_summon_history
        return[]if len(roots)!=1 or type(roots[0].request.materials[0])is not ResurrectionEntryMaterial else[CastSpell(1,'dx_direct',c.source_id,choices='player')]
    r.register_behavior('dx_nested',nested);r.register_card(CardDefinition('dx_nested','Nested resurrection',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','dx_nested'),)))
    def herald_watch(c):
        roots=c.state.card_summon_history
        if not roots or len(roots)!=1 or len(roots[0].deliveries)!=1 or c.event.target_id!=roots[0].deliveries[0].entity.entity_id:return[]
        return[*(Destroy(i,c.source_id)for i in c.state.players[1].board if c.state.entities[i].card_id=='source'),Herald(1,c.source_id),Herald(1,c.source_id),
            RequestChoice(1,(ChoiceOption('ok','Finish original strength',()),),c.source_id)]
    r.register_behavior('dx_herald_watch',herald_watch);r.register_card(CardDefinition('dx_herald_watch','Change Herald after resurrection',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','dx_herald_watch'),)))
    r.register_behavior('dx_fatal',lambda c:[]if not c.state.card_summon_history else[Damage(c.state.players[2].hero_id,100,c.source_id)])
    r.register_card(CardDefinition('dx_fatal','End actual resurrection',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','dx_fatal'),)))
    def sourceface_watch(c):
        roots=c.state.resurrection_summon_history;children=c.state.card_summon_history
        if not roots or len(roots)!=1 or not children or len(children[0].deliveries)!=1 or c.event.target_id!=children[0].deliveries[0].entity.entity_id:return[]
        return[Transform(roots[0].spec.source_id,'other'),RequestChoice(1,(ChoiceOption('ok','Continue frozen query',()),),c.source_id)]
    r.register_behavior('dx_sourceface_watch',sourceface_watch)
    r.register_card(CardDefinition('dx_sourceface_watch','Change original query source face',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','dx_sourceface_watch'),)))
    r.register_card(CardDefinition('dx_minion','Minion resurrection cause',CardType.MINION,health=5,on_play='dx_exclude'))
    bodies={
        'dx_kill':kill,'dx_prepped':prepped,'dx_direct':lambda c:[direct(c)],'dx_enemy':lambda c:[direct(c,2)],
        'dx_once':lambda c:[res(c,1)],'dx_twice':lambda c:[res(c)],'dx_random':lambda c:[res(c,1,'random')],
        'dx_card_random':lambda c:[res(c,2,'random','card')],'dx_followed':lambda c:[res(c,1,follow='dx_follow')],
        'dx_wait_follow':lambda c:[res(c,1,follow='dx_wait_body')],'dx_position':lambda c:[res(c,position=0)],
        'dx_zero':lambda c:[res(c,0)],'dx_wait':lambda c:[RequestChoice(1,(ChoiceOption('ok','Resurrect',(res(c),)),),c.source_id)],
        'dx_stats':lambda c:[direct(c,stats=SummonStats(9,2))],'dx_retry':lambda c:[res(c,1,'random',follow='dx_follow')],
        'dx_legacy':lambda c:[Resurrect(1)],'dx_inject':lambda c:[RequestChoice(1,(ChoiceOption('bad','Inject',(ContinueDeathResurrection(1),)),),c.source_id)],
        'dx_inject_follow':lambda c:[RequestChoice(1,(ChoiceOption('bad','Inject',(ContinueQuantityResurrection(1,0),)),),c.source_id)],
        'dx_pause':lambda c:[PauseDeathEntry(res(c))],
        'dx_highest':lambda c:[res(c,1,query=DeathQuery(cost_extreme='highest'))],
        'dx_kill_new':lambda c:[Destroy(c.target_id,c.source_id)],
        'dx_missing_follow':lambda c:[res(c,0,follow='missing')],
        'dx_batch_enemy':lambda c:[res(c,1,query=DeathQuery(side='enemy'),player=2)],
        'dx_exclude':lambda c:[res(c,query=DeathQuery(cards=PoolQuery(exclude_source=True)))],
    }
    for name,fn in bodies.items():
        r.register_behavior(name,fn);r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,requires_target=name in('dx_prepped','dx_kill_new'),
            keywords=(Keyword.REWIND,)if name=='dx_retry'else(),rewind=RewindSpec(1)if name=='dx_retry'else None))
    return r


class ResurrectionQuantityTests(unittest.TestCase):
    blob=base.RecruitSummonTests.blob;play=base.RecruitSummonTests.play;choose=base.RecruitSummonTests.choose
    def game(self,hand=(),board=(),enemy=(),hero='hero'):
        g=Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=('body',)*5,mana=10,max_mana=10),
            PlayerSetup('hero',board=enemy,deck=('body',)*5)),seed=165),registry(),mechanics=mechanics());self.blob(g,'initial');return g
    def ready(self,name,deaths=('body','other'),watchers=(),extra=()):
        g=self.game(('dx_kill','source',name)+extra,deaths+watchers);self.play(g,'dx_kill');self.play(g,'source');return g
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));self.blob(s,'portable')
        self.assertEqual(Game.from_snapshot(deepcopy(s),registry(),mechanics=mechanics()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(),mechanics=mechanics()).snapshot(),s)
        for player in(1,2):
            public=json.dumps(g.observe(player))+json.dumps(g.player_events(player))+json.dumps(g.for_player(player).legal_actions())
            for key in('resurrection_summon_history','resurrection_quantity_bodies','ResurrectionEntryMaterial','resurrection_batch_accepted','resurrection_batch_finished','resurrection_pick_accepted','resurrection_entry_bound','resurrection_delivery_bound','resurrection_followup_finished','rng_before','rng_after'):
                self.assertNotIn('"'+key+'"',public)
        return s
    def reject(self,s,label):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
        self.blob(s,label)
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry(),mechanics=mechanics())
    def bodies(self,g,index=-1):return[g.state.entities[d.entity.entity_id]for d in g.state.card_summon_history[index].deliveries if d.entity]
    def rng(self,g):
        s=g.snapshot()['rng_state'];r=Random();r.setstate((s[0],tuple(s[1]),s[2]));return r

    def test_direct_death_is_preserved_and_every_body_is_new(self):
        g=self.ready('dx_direct',('body',));death=g.state.death_history[0];original=g.state.entities[death.entity_id];self.play(g,'dx_direct')
        self.assertEqual(g.state.death_history[0],death);self.assertEqual(g.state.entities[original.id].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.resurrection_history),2);self.assertEqual([e.origin_entity_id for e in self.bodies(g)],[original.id]*2)
        self.assertEqual(len({e.id for e in self.bodies(g)}),2);self.portable(g)

    def test_base_reconstruction_discards_death_state_and_restores_printed_flags(self):
        g=self.game(('dx_prepped','source','dx_direct'),('dx_printed',));original=g.state.players[1].board[0];self.play(g,'dx_prepped',original)
        self.assertIn(Keyword.LIFESTEAL,g.state.death_history[0].keywords);self.play(g,'source');self.play(g,'dx_direct')
        for e in self.bodies(g):
            self.assertEqual((e.attack,e.health,e.damage,e.silenced,e.frozen),(1,5,0,False,False))
            self.assertIn(Keyword.REBORN,e.keywords);self.assertIn(Keyword.TAUNT,e.keywords);self.assertNotIn(Keyword.LIFESTEAL,e.keywords)
        ids=[a.id for e in self.bodies(g)for a in e.abilities];self.assertEqual(len(ids),len(set(ids)));self.portable(g)

    def test_cross_recipient_death_owner_is_not_inherited(self):
        g=self.ready('dx_enemy',('body',));self.play(g,'dx_enemy')
        self.assertEqual([(e.owner,e.controller)for e in self.bodies(g)],[(2,2)]*2);self.portable(g)

    def test_two_original_entries_each_capture_their_own_plan(self):
        g=self.ready('dx_twice');self.play(g,'dx_twice')
        self.assertEqual([x.plan.total for x in g.state.card_summon_history],[2,2]);self.assertEqual(len(g.state.resurrection_history),4)
        self.assertEqual([x.selected for x in g.state.resurrection_summon_history[0].picks],[1,2]);self.portable(g)

    def test_new_quantity_source_changes_next_original_entry_only(self):
        g=self.ready('dx_twice',('source','body'));self.play(g,'dx_twice')
        self.assertEqual([x.plan.total for x in g.state.card_summon_history],[2,8]);self.portable(g)

    def test_death_mode_draws_once_with_duplicate_card_records(self):
        g=self.ready('dx_random',('body','body','other'));rng=self.rng(g);expected=rng.choice([1,2,3]);self.play(g,'dx_random')
        pick=g.state.resurrection_summon_history[0].picks[0];self.assertEqual(pick.selected,expected)
        self.assertEqual(pick.rng_after,rng.getstate());self.assertEqual(self.rng(g).getstate(),rng.getstate());self.portable(g)

    def test_card_mode_draws_group_then_member_and_removes_whole_identity(self):
        g=self.ready('dx_card_random',('body','body','other'));rng=self.rng(g);groups=[[1,2],[3]];first=rng.choice(rng.choice(groups));remaining=[x for x in groups if first not in x];second=rng.choice(rng.choice(remaining))
        self.play(g,'dx_card_random');root=g.state.resurrection_summon_history[0]
        self.assertEqual([x.selected for x in root.picks],[first,second]);self.assertEqual(root.picks[-1].rng_after,rng.getstate());self.portable(g)

    def test_accepted_material_survives_first_transformation_and_source_death(self):
        g=self.ready('dx_followed',('body',),('dx_watch',));self.play(g,'dx_followed');self.portable(g);self.choose(g,'ok')
        self.assertEqual([(e.card_id,e.attack,e.health)for e in self.bodies(g)],[('other',3,7),('body',3,6)])
        self.assertEqual([x.status for x in g.state.resurrection_quantity_bodies],['skipped','attempted']);self.portable(g)

    def test_per_body_followup_targets_each_actual_body_and_original_death(self):
        g=self.ready('dx_followed',('body',));self.play(g,'dx_followed')
        self.assertEqual([(e.attack,e.health)for e in self.bodies(g)],[(3,6)]*2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
        self.assertEqual([x.status for x in g.state.resurrection_quantity_bodies],['attempted']*2);self.portable(g)

    def test_each_real_followup_choice_restores_and_bad_branch_rolls_back(self):
        g=self.ready('dx_wait_follow',('body',));self.play(g,'dx_wait_follow')
        for _ in range(2):
            s=self.portable(g)
            with self.assertRaises(Exception):self.choose(g,'bad')
            self.assertEqual(g.snapshot(),s);self.choose(g,'ok')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.portable(g)

    def test_full_batch_has_no_query_selection_or_rng(self):
        g=self.game(('dx_twice',),('source',)+('body',)*6);before=g.snapshot()['rng_state'];self.play(g,'dx_twice')
        root=g.state.resurrection_summon_history[0];self.assertEqual((root.status,root.basis,root.picks),('board_full',None,()))
        self.assertFalse(g.state.card_summon_history);self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)

    def test_direct_full_has_one_original_failure_and_no_success_record(self):
        g=self.game(('dx_kill_new','dx_direct','source'),('body',)+('other',)*6)
        self.play(g,'dx_kill_new',g.state.players[1].board[0]);self.play(g,'source');before=g.snapshot()['rng_state'];self.play(g,'dx_direct')
        self.assertEqual(len(g.state.resurrection_history),0);self.assertEqual(g.state.card_summon_history[0].status,'skipped')
        self.assertEqual(sum(e.kind=='resurrection_failed'for e in g.events),1);self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)

    def test_empty_and_zero_keep_original_no_rng_policies(self):
        for name,status in(('dx_twice','empty'),('dx_zero','completed')):
            g=self.game((name,),('source',));before=g.snapshot()['rng_state'];self.play(g,name)
            self.assertEqual(g.state.resurrection_summon_history[0].status,status);self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)

    def test_stats_override_every_actual_body_before_entry(self):
        g=self.ready('dx_stats',('body',));self.play(g,'dx_stats');self.assertEqual([(e.attack,e.health)for e in self.bodies(g)],[(9,2)]*2);self.portable(g)

    def test_positions_advance_per_original_iteration(self):
        g=self.ready('dx_position');self.play(g,'dx_position')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],['body','other','other','body','source']);self.portable(g)

    def test_pending_public_request_is_saved_before_batch_acceptance(self):
        g=self.ready('dx_wait');self.play(g,'dx_wait');self.portable(g);self.assertFalse(g.state.resurrection_summon_history)
        self.choose(g,'ok');self.assertEqual(g.state.resurrection_summon_history[0].status,'completed');self.portable(g)

    def test_selected_death_entry_waiting_has_complete_original_tail(self):
        g=self.ready('dx_pause');self.play(g,'dx_pause');self.portable(g)
        self.assertFalse(g.state.card_summon_history);self.assertIsNone(g.state.resurrection_summon_history[0].picks[0].entry_root_id)
        self.choose(g,'ok');self.assertEqual(len(g.state.resurrection_summon_history[0].picks),2);self.portable(g)

    def test_nested_cast_keeps_each_record_and_body_origin_disjoint(self):
        g=self.ready('dx_once',('body',),('dx_nested',));self.play(g,'dx_once')
        self.assertEqual(len(g.state.card_summon_history),2);self.assertEqual(len(g.state.resurrection_history),4)
        self.assertEqual(len({x.entity_id for x in g.state.resurrection_history}),4);self.portable(g)

    def test_true_retry_retires_original_records_but_keeps_monotonic_roots(self):
        g=self.ready('dx_retry',('body',));self.play(g,'dx_retry');self.portable(g)
        old_root=g.state.resurrection_summon_history[0].id;old_body=max(x.entity_id for x in g.state.resurrection_history)
        self.choose(g,'retry');self.assertGreater(g.state.resurrection_summon_history[0].id,old_root)
        self.assertGreater(min(x.entity_id for x in g.state.resurrection_history),old_body);self.portable(g)

    def test_terminal_cancels_owed_followup_and_extra_prefix(self):
        g=self.ready('dx_followed',('body',),('dx_fatal',));self.play(g,'dx_followed')
        self.assertEqual(g.state.card_summon_history[0].status,'interrupted');self.assertEqual(len(g.state.card_summon_history[0].deliveries),1)
        self.assertEqual(g.state.resurrection_quantity_bodies[0].status,'interrupted');self.portable(g)

    def test_rehashed_inventory_selection_rng_material_binding_and_tail_reject(self):
        g=self.ready('dx_followed',('body','other'),('dx_watch',));self.play(g,'dx_followed');s=self.portable(g)
        for name in('inventory','candidates','selected','rng','material','binding','followup','tail','link'):
            bad=deepcopy(s);root=bad['state']['resurrection_summon_history'][0];child=bad['state']['card_summon_history'][0]
            if name=='inventory':root['basis']['inventory'].pop()
            elif name=='candidates':root['candidates'].reverse()
            elif name=='selected':root['picks'][0]['selected']=2
            elif name=='rng':root['picks'][0]['rng_after'][1][-1]=(root['picks'][0]['rng_after'][1][-1]+1)%625
            elif name=='material':child['request']['materials'][0]['death']['base_attack']+=1
            elif name=='binding':bad['state']['resurrection_quantity_bodies'][0]['beneficiary']['card_id']='other'
            elif name=='followup':bad['state']['resurrection_quantity_bodies'][0]['status']='attempted'
            elif name=='tail':bad['resolution_frame']['fields']['continuation']['tuple']=[]
            else:child['request']['producer_link']={'recruit_id':1,'index':0}
            self.reject(bad,name)

    def test_legacy_quantity_and_choice_control_injections_roll_back(self):
        for name,pattern in(('dx_legacy','Unattributed summon'),('dx_inject','inject death resurrection control'),('dx_inject_follow','inject death resurrection control')):
            g=self.ready(name);before=g.snapshot()
            with self.assertRaisesRegex(Exception,pattern):self.play(g,name)
            self.assertEqual(g.snapshot(),before)
        g=self.game(('dx_kill','dx_legacy'),('body',));self.play(g,'dx_kill');self.play(g,'dx_legacy');self.assertFalse(g.state.resurrection_summon_history);self.portable(g)

    def test_highest_query_retains_complete_original_history(self):
        g=self.ready('dx_highest',('body','dx_printed'))
        # Printed Reborn creates a second real death candidate identity only in later death;
        # query still sees its original immutable first death.
        self.play(g,'dx_highest');root=g.state.resurrection_summon_history[0]
        self.assertEqual(len(root.basis.inventory),2);self.assertEqual([x.card_id for x in root.basis.inventory],['body','dx_printed'])
        self.assertEqual(root.candidates,(2,));self.portable(g)

    def test_new_deaths_from_first_reactions_do_not_join_original_batch(self):
        g=self.ready('dx_twice',('body','other'),('dx_watch',));self.play(g,'dx_twice');self.portable(g);self.choose(g,'ok')
        root=g.state.resurrection_summon_history[0]
        self.assertEqual(len(root.basis.inventory),2);self.assertEqual(root.candidates,(1,2))
        self.assertEqual([x.selected for x in root.picks],[1,2]);self.assertEqual(len(g.state.death_history),3)
        self.assertEqual([x.plan.total for x in g.state.card_summon_history],[2,1]);self.portable(g)

    def test_separate_requests_can_reuse_the_same_immutable_death(self):
        g=self.ready('dx_once',('body',),extra=('dx_once',));self.play(g,'dx_once');self.play(g,'dx_once')
        self.assertEqual([x.picks[0].selected for x in g.state.resurrection_summon_history],[1,1])
        self.assertEqual([x.death_id for x in g.state.resurrection_history],[1]*4);self.portable(g)

    def test_full_extra_attempt_has_no_successful_record_or_followup_binding(self):
        g=self.game(('dx_kill_new','dx_direct','source'),('body',)+('other',)*5)
        self.play(g,'dx_kill_new',g.state.players[1].board[0]);self.play(g,'source');self.play(g,'dx_direct')
        self.assertEqual([x.outcome for x in g.state.card_summon_history[0].deliveries],['delivered','board_full'])
        self.assertEqual((len(g.state.resurrection_history),len(g.state.resurrection_quantity_bodies)),(1,1));self.portable(g)

    def test_owed_body_followup_cannot_be_removed_from_rehashed_frame_and_proof(self):
        g=self.ready('dx_followed',('body',),('dx_watch',));self.play(g,'dx_followed');bad=deepcopy(self.portable(g));removed=[]
        def crop(value):
            if type(value)is dict:
                for x in value.values():crop(x)
            elif type(value)is list:
                for x in tuple(value):
                    if type(x)is dict and str(x.get('type','')).endswith('.ContinueQuantityResurrection'):value.remove(x);removed.append(x)
                    else:crop(x)
        crop(bad['resolution_frame']);self.assertGreaterEqual(len(removed),2);self.reject(bad,'cropped-all-owed-body-followups')

    def test_unbound_selected_death_or_cause_edits_reject_in_real_gap(self):
        g=self.ready('dx_pause');self.play(g,'dx_pause');s=self.portable(g)
        for name in('death','cause'):
            bad=deepcopy(s)
            def change(v):
                if type(v)is dict:
                    if str(v.get('type','')).endswith('.ResurrectMinion')and v['fields'].get('producer_link'):
                        if name=='death':v['fields']['death_id']=2
                        else:v['fields']['cause']['fields']['action']=bad['state']['action_number']+1
                        return True
                    return any(change(x)for x in v.values())
                if type(v)is list:return any(change(x)for x in v)
                return False
            self.assertTrue(change(bad['resolution_frame']));self.reject(bad,'unbound-'+name)

    def test_current_recipient_herald_strength_is_frozen_for_all_accepted_bodies(self):
        g=self.game(('dx_kill','rr_herald_twice','source','dx_direct'),('rr_soldier','dx_herald_watch'),hero='rr_mage')
        self.play(g,'dx_kill');original_rank=g.state.death_history[0].herald_rank
        self.play(g,'rr_herald_twice');self.play(g,'source');self.play(g,'dx_direct');self.portable(g)
        self.assertEqual(original_rank,0);self.assertEqual(len(g.state.herald_history),4)
        self.assertEqual(g.state.card_summon_history[0].request.materials[0].entry_herald_count,2)
        self.choose(g,'ok');self.assertEqual([(e.herald_rank,e.attack,e.health)for e in self.bodies(g)],[(1,2,2)]*2);self.portable(g)

    def test_unknown_required_followup_rejects_even_zero_request_before_rng(self):
        g=self.game(('dx_missing_follow',),('source',));before=g.snapshot()
        with self.assertRaises(Exception):self.play(g,'dx_missing_follow')
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_batch_query_recipient_and_quantity_cause_players_are_distinct(self):
        g=self.ready('dx_batch_enemy',('body',));self.play(g,'dx_batch_enemy')
        root=g.state.resurrection_summon_history[0]
        self.assertEqual((root.basis.player_id,root.spec.cause.player_id),(2,1))
        self.assertEqual(root.candidates,(1,));self.assertEqual([(e.owner,e.controller)for e in self.bodies(g)],[(2,2)]*2);self.portable(g)

    def test_original_excluded_source_face_survives_later_transformation(self):
        g=self.ready('dx_minion',('dx_minion','body','other'),('dx_sourceface_watch',));self.play(g,'dx_minion');self.portable(g)
        root=g.state.resurrection_summon_history[0];self.assertEqual(root.basis.source.card_id,'dx_minion')
        self.assertEqual(g.state.entities[root.spec.source_id].card_id,'other');self.choose(g,'ok')
        root=g.state.resurrection_summon_history[0];self.assertEqual(root.candidates,(2,3));self.assertEqual([x.selected for x in root.picks],[2,3]);self.portable(g)
