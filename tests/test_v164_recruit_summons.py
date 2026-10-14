"""Native physical first movement, sequential re-query, and immutable extras."""
from copy import deepcopy
from dataclasses import dataclass
import json,unittest
from random import Random
from hs_sim.engine import (CardDefinition,CardType,Game,Keyword,PlayerSetup,PoolQuery,RewindSpec,Scenario,
    SnapshotError,SummonCause,SummonFromZone,SummonStats,SummonStoredCard,TriggerSpec,Zone,Herald)
from hs_sim.engine.effects import Buff,ChoiceOption,Destroy,Effect,EquipWeapon,GainArmor,RandomDamage,RequestChoice,Transform
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.zones import AddToDeck,CardReference,MoveCard
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.model import CardClass,CardMetadata
from hs_sim.engine.summon_sources import CopyStoredMinion
from hs_sim.engine.recruit_summons import ContinueRecruit,start
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
import test_v163_copy_materials as base


@dataclass(frozen=True)
class PauseSelectedRecruit(Effect):
    """Test extension exposes the existing select/entry gap; no default claim."""
    spec:SummonFromZone


def mechanics():
    m=default_mechanics()
    def pause(r,effect):
        work=start(r,effect.spec);parent=r.state.recruit_summon_history[-1];ref=parent.rounds[-1].selected
        return(RequestChoice(1,(ChoiceOption('move','Move selected source',(MoveCard(ref,1,Zone.HAND),)),
            ChoiceOption('stay','Keep selected source',())),effect.spec.source_id),*work)
    m.register(PauseSelectedRecruit,pause);return m


def registry():
    r=base.registry()
    r.register_card(CardDefinition('rr_mage','Mage',CardType.HERO,health=30,metadata=CardMetadata(False,(CardClass.MAGE,),None)))
    r.register_card(CardDefinition('rr_soldier','Entry-scaled Soldier',CardType.MINION,attack=1,health=1,
        herald_scaling=True,herald_soldier_for=CardClass.MAGE))
    def recruit(c,count=2,selection='first',owner=None,zone=Zone.DECK,position=None,query=PoolQuery()):
        return SummonFromZone(1,count,owner,zone,query,selection,position,c.source_id,cause=SummonCause.capture(c))
    def ref(c,player=1,zone=Zone.DECK):return CardReference.capture(c.state.entities[getattr(c.state.players[player],zone.value)[0]])
    def direct(c,player=1,stats=None):return SummonStoredCard(ref(c,player),1,stats=stats,cause=SummonCause.capture(c))
    def prepare(c):return [BuffStoredCard(ref(c),3,2,c.source_id),direct(c,stats=SummonStats(9,2))]
    def stale(c):
        e=direct(c);return [MoveCard(e.card,1,Zone.HAND),e]
    def watch(c):
        if len(c.state.recruit_summon_history)!=1:return []
        parent=c.state.recruit_summon_history[0]
        if len(parent.rounds)!=1 or parent.rounds[0].entry_root_id is None:return []
        root=next(x for x in c.state.card_summon_history if x.id==parent.rounds[0].entry_root_id)
        if len(root.deliveries)!=1:return []
        sources=[i for i in c.state.players[1].board if c.state.entities[i].card_id=='source']
        return [*(Destroy(i,c.source_id)for i in sources),Transform(c.event.target_id,'other'),Buff(c.event.target_id,10,0,c.source_id),
            AddToDeck(1,'other',position='top'),RequestChoice(1,(
                ChoiceOption('bad','Rollback',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),EquipWeapon(1,'body'))),
                ChoiceOption('ok','Continue',())),c.source_id)]
    r.register_behavior('rr_watch',watch)
    r.register_card(CardDefinition('rr_watch','Change first body before extras',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','rr_watch'),)))
    r.register_behavior('rr_nested',lambda c:[]if len(c.state.recruit_summon_history)!=1 else[CastSpell(1,'rr_once',c.source_id,choices='player')])
    r.register_card(CardDefinition('rr_nested','Nested actual producer',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','rr_nested'),)))
    r.register_card(CardDefinition('rr_cry','Printed battlecry is not invoked',CardType.MINION,health=5,battlecry='gift'))
    def herald_watch(c):
        if len(c.state.card_summon_history)!=1:return []
        root=c.state.card_summon_history[0]
        if len(root.deliveries)!=1 or c.event.target_id!=root.deliveries[0].entity.entity_id:return []
        sources=[i for i in c.state.players[1].board if c.state.entities[i].card_id=='source']
        return [*(Destroy(i,c.source_id)for i in sources),Herald(1,c.source_id),Herald(1,c.source_id),
            RequestChoice(1,(ChoiceOption('ok','Finish accepted entry',()),),c.source_id)]
    r.register_behavior('rr_herald_watch',herald_watch)
    r.register_card(CardDefinition('rr_herald_watch','Change Herald after first body',CardType.MINION,health=5,
        triggers=(TriggerSpec('minion_summoned','rr_herald_watch'),)))
    bodies={
        'rr_twice':lambda c:[recruit(c)],'rr_once':lambda c:[recruit(c,1)],
        'rr_random':lambda c:[recruit(c,1,'random')],'rr_enemy':lambda c:[recruit(c,1,owner=2)],
        'rr_hand':lambda c:[recruit(c,1,zone=Zone.HAND,query=PoolQuery(kinds=(CardType.MINION,)))],
        'rr_position':lambda c:[recruit(c,position=0)],'rr_zero':lambda c:[recruit(c,0)],
        'rr_direct':lambda c:[direct(c)],'rr_direct_enemy':lambda c:[direct(c,2)],'rr_stats':prepare,
        'rr_stale':stale,'rr_wait':lambda c:[RequestChoice(1,(ChoiceOption('ok','Recruit',(recruit(c),)),),c.source_id)],
        'rr_inject':lambda c:[RequestChoice(1,(ChoiceOption('bad','Inject',(ContinueRecruit(1),)),),c.source_id)],
        'rr_retry':lambda c:[recruit(c)],'rr_legacy':lambda c:[SummonFromZone(1)],
        'rr_filtered':lambda c:[recruit(c,1,query=PoolQuery(max_cost=0,exclude_card_ids=('other',)))],
        'rr_pause':lambda c:[PauseSelectedRecruit(recruit(c))],
        'rr_herald_twice':lambda c:[Herald(1,c.source_id),Herald(1,c.source_id)],
        'rr_copy_soldier':lambda c:[CopyStoredMinion(ref(c,zone=Zone.HAND),1,cause=SummonCause.capture(c))],
        'rr_legacy_copy_soldier':lambda c:[CopyStoredMinion(ref(c,zone=Zone.HAND),1)],
    }
    for name,fn in bodies.items():
        r.register_behavior(name,fn);r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,
            keywords=(Keyword.REWIND,)if name=='rr_retry'else(),rewind=RewindSpec(1)if name=='rr_retry'else None))
    return r


class RecruitSummonTests(unittest.TestCase):
    blob=base.CopyMaterialTests.blob;play=base.CopyMaterialTests.play;choose=base.CopyMaterialTests.choose
    def game(self,hand=(),board=(),deck=('body','other'),enemy=(),enemy_deck=('other','body'),hero='hero'):
        g=Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('hero',board=enemy,deck=enemy_deck)),seed=164),registry(),mechanics=mechanics());self.blob(g,'initial');return g
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));self.blob(s,'portable')
        self.assertEqual(Game.from_snapshot(deepcopy(s),registry(),mechanics=mechanics()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(),mechanics=mechanics()).snapshot(),s)
        for player in(1,2):
            public=json.dumps(g.observe(player))+json.dumps(g.player_events(player))+json.dumps(g.for_player(player).legal_actions())
            for key in('recruit_summon_history','recruit_summon_accepted','recruit_summon_finished','recruit_selection_accepted','recruit_entry_bound','RecruitEntryMaterial','RecruitBasis','rng_before','rng_after'):
                self.assertNotIn('"'+key+'"',public)
        return s
    def reject(self,s,label):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
        self.blob(s,label)
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry(),mechanics=mechanics())
    def rng(self,g):
        s=g.snapshot()['rng_state'];r=Random();r.setstate((s[0],tuple(s[1]),s[2]));return r
    def bodies(self,g,index=-1):return[g.state.entities[d.entity.entity_id]for d in g.state.card_summon_history[index].deliveries if d.entity]

    def test_first_moves_original_extra_allocates_a_new_entity(self):
        g=self.game(('rr_once',),('source',));original=g.state.players[1].deck[0];next_id=g.state.next_entity_id
        self.play(g,'rr_once');root=g.state.card_summon_history[0]
        self.assertEqual((root.plan.total,root.deliveries[0].entity.entity_id),(2,original))
        self.assertGreaterEqual(root.deliveries[1].entity.entity_id,next_id)
        self.assertEqual([e.card_id for e in self.bodies(g)],['body','body']);self.assertNotIn(original,g.state.players[1].deck);self.portable(g)

    def test_cross_owner_first_keeps_owner_extra_is_recipient_owned(self):
        g=self.game(('rr_enemy',),('source',));original=g.state.players[2].deck[0];self.play(g,'rr_enemy')
        self.assertEqual([(e.owner,e.controller)for e in self.bodies(g)],[(2,1),(1,1)])
        self.assertEqual(g.state.card_summon_history[0].deliveries[0].entity.entity_id,original);self.portable(g)

    def test_direct_attributed_stored_movement_uses_same_first_extra_recipe(self):
        g=self.game(('rr_direct_enemy',),('source',));original=g.state.players[2].deck[0];self.play(g,'rr_direct_enemy')
        self.assertFalse(g.state.recruit_summon_history)
        self.assertEqual([(e.id,e.owner)for e in self.bodies(g)][:1],[(original,2)])
        self.assertEqual(self.bodies(g)[1].owner,1);self.portable(g)

    def test_two_original_selections_have_separate_entry_plans(self):
        g=self.game(('rr_twice',),('source',));ids=list(g.state.players[1].deck);self.play(g,'rr_twice')
        parent=g.state.recruit_summon_history[0];self.assertEqual((parent.status,len(parent.rounds)),('completed',2))
        self.assertEqual([x.selected.entity_id for x in parent.rounds],ids)
        self.assertEqual([x.plan.total for x in g.state.card_summon_history],[2,2]);self.assertFalse(g.state.players[1].deck);self.portable(g)

    def test_new_quantity_source_changes_later_original_root_only(self):
        g=self.game(('rr_twice',),('source',),deck=('source','body'));self.play(g,'rr_twice')
        self.assertEqual([x.plan.total for x in g.state.card_summon_history],[2,8])
        self.assertEqual([len(x.deliveries)for x in g.state.card_summon_history],[2,8]);self.portable(g)

    def test_random_is_one_uniform_physical_draw_and_no_extra_rng(self):
        g=self.game(('rr_random',),('source',),deck=('body','body','other'));rng=self.rng(g);expected=rng.choice(g.state.players[1].deck)
        self.play(g,'rr_random');round=g.state.recruit_summon_history[0].rounds[0]
        self.assertEqual(round.selected.entity_id,expected);self.assertEqual(len(round.candidates),3)
        self.assertEqual(round.rng_after,rng.getstate());self.assertEqual(self.rng(g).getstate(),rng.getstate());self.portable(g)

    def test_reactions_change_first_but_accepted_extras_keep_material(self):
        g=self.game(('rr_twice',),('source','rr_watch'));self.play(g,'rr_twice');s=self.portable(g)
        root=g.state.card_summon_history[0];self.assertEqual((root.plan.total,len(root.deliveries)),(2,1))
        with self.assertRaises(Exception):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),s);self.choose(g,'ok')
        self.assertEqual([(e.card_id,e.attack)for e in self.bodies(g,0)],[('other',13),('body',2)])
        self.assertEqual(g.state.card_summon_history[1].plan.total,1);self.portable(g)

    def test_next_requery_observes_injected_top_card_after_extras(self):
        g=self.game(('rr_twice',),('source','rr_watch'));self.play(g,'rr_twice');self.choose(g,'ok')
        parent=g.state.recruit_summon_history[0];self.assertEqual([x.selected.card_id for x in parent.rounds],['body','other'])
        self.assertEqual(len(parent.rounds[1].basis.inventory),2)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],['other']);self.portable(g)

    def test_full_before_query_keeps_hidden_zone_rng_and_no_child(self):
        g=self.game(('rr_random',),('source',)+('body',)*6);deck=list(g.state.players[1].deck);before=g.snapshot()['rng_state'];self.play(g,'rr_random')
        parent=g.state.recruit_summon_history[0];self.assertEqual((parent.status,parent.rounds[0].basis),('board_full',None))
        self.assertFalse(g.state.card_summon_history);self.assertEqual(g.state.players[1].deck,deck);self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)

    def test_direct_full_keeps_original_and_has_private_skipped_root(self):
        g=self.game(('rr_direct',),('source',)+('body',)*6);deck=list(g.state.players[1].deck);self.play(g,'rr_direct')
        root=g.state.card_summon_history[0];self.assertEqual((root.status,root.selected,root.deliveries),('skipped',None,()))
        self.assertEqual(g.state.players[1].deck,deck);self.assertFalse(any(e.kind=='summon_failed'for e in g.events));self.portable(g)

    def test_empty_and_zero_have_distinct_original_outcomes_without_rng(self):
        for name,status,rounds in(('rr_twice','exhausted',1),('rr_zero','completed',0)):
            g=self.game((name,),('source',),deck=());before=g.snapshot()['rng_state'];self.play(g,name)
            parent=g.state.recruit_summon_history[0];self.assertEqual((parent.status,len(parent.rounds)),(status,rounds))
            self.assertEqual(g.snapshot()['rng_state'],before);self.assertFalse(g.state.card_summon_history);self.portable(g)

    def test_early_capacity_exhaustion_stops_original_requery(self):
        g=self.game(('rr_twice',),('source',)+('body',)*5);original=g.state.players[1].deck[0];self.play(g,'rr_twice')
        parent=g.state.recruit_summon_history[0]
        self.assertEqual((parent.status,[x.outcome for x in parent.rounds]),('board_full',['selected','board_full']))
        self.assertEqual([d.outcome for d in g.state.card_summon_history[0].deliveries],['delivered','board_full'])
        self.assertEqual(g.state.card_summon_history[0].deliveries[0].entity.entity_id,original);self.portable(g)

    def test_position_cursor_is_per_original_selection_not_total_quantity(self):
        g=self.game(('rr_position',),('source',));self.play(g,'rr_position')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],['body','other','other','body','source']);self.portable(g)

    def test_hand_source_moves_original_without_payment_or_battlecry(self):
        g=self.game(('rr_hand','rr_cry'),('source',));original=g.state.players[1].hand[-1];self.play(g,'rr_hand')
        self.assertEqual(g.state.card_summon_history[0].deliveries[0].entity.entity_id,original)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.assertEqual((g.state.players[1].mana,len(g.state.play_history)),(10,1));self.portable(g)

    def test_stats_apply_before_both_entry_events_and_attachments_are_independent(self):
        g=self.game(('rr_stats',),('source',));original=g.state.players[1].deck[0];self.play(g,'rr_stats')
        self.assertEqual([(e.attack,e.health)for e in self.bodies(g)],[(9,2)]*2)
        ids=[a.id for e in self.bodies(g)for a in e.enchantments];self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(self.bodies(g)[0].id,original);self.portable(g)

    def test_stale_direct_reference_does_not_move_returned_source_or_make_root(self):
        g=self.game(('rr_stale',),('source',));original=g.state.players[1].deck[0];self.play(g,'rr_stale')
        self.assertEqual(g.state.entities[original].zone,Zone.HAND);self.assertFalse(g.state.card_summon_history)
        self.assertTrue(any(e.kind=='zone_target_skipped'for e in g.events));self.portable(g)

    def test_saved_public_choice_recruit_is_restored_before_acceptance(self):
        g=self.game(('rr_wait',),('source',));self.play(g,'rr_wait');self.portable(g);self.assertFalse(g.state.recruit_summon_history)
        self.choose(g,'ok');self.assertEqual(g.state.recruit_summon_history[0].status,'completed');self.portable(g)

    def test_nested_actual_cast_keeps_disjoint_producer_and_entry_identities(self):
        g=self.game(('rr_once',),('source','rr_nested'),deck=('body','other'));self.play(g,'rr_once')
        parents=g.state.recruit_summon_history;self.assertEqual([x.id for x in parents],[1,2])
        self.assertEqual([len(x.rounds)for x in parents],[1,1]);self.assertNotEqual(parents[0].spec.cause.cast_id,parents[1].spec.cause.cast_id);self.portable(g)

    def test_terminal_closes_actual_first_prefix_without_later_round(self):
        g=self.game(('rr_twice',),('source','fatal_watcher'));self.play(g,'rr_twice')
        parent=g.state.recruit_summon_history[0];child=g.state.card_summon_history[0]
        self.assertEqual((parent.status,len(parent.rounds),child.status,len(child.deliveries)),('interrupted',1,'interrupted',1));self.portable(g)

    def test_true_retry_preserves_physical_first_id_but_new_producer_and_extras(self):
        g=self.game(('rr_retry',),('source',));original=g.state.players[1].deck[0];self.play(g,'rr_retry');self.portable(g)
        old=g.state.recruit_summon_history[0];old_extra=g.state.card_summon_history[0].deliveries[1].entity.entity_id
        self.choose(g,'retry');self.portable(g);new=g.state.recruit_summon_history[0]
        self.assertGreater(new.id,old.id);self.assertGreater(new.rounds[0].entry_root_id,old.rounds[-1].entry_root_id)
        child=g.state.card_summon_history[0];self.assertEqual(child.deliveries[0].entity.entity_id,original);self.assertGreater(child.deliveries[1].entity.entity_id,old_extra)

    def test_complete_inventory_selection_material_and_owed_tail_edits_reject(self):
        g=self.game(('rr_twice',),('source','rr_watch'));self.play(g,'rr_twice');s=self.portable(g)
        for name in('inventory','candidates','selected','rng','physical','owner','material','tail','link'):
            bad=deepcopy(s);parent=bad['state']['recruit_summon_history'][0];round=parent['rounds'][0];child=bad['state']['card_summon_history'][0]
            if name=='inventory':round['basis']['inventory'].pop()
            elif name=='candidates':round['candidates'].reverse()
            elif name=='selected':round['selected']['entity_id']=round['candidates'][-1]['entity_id']
            elif name=='rng':round['rng_after'][1][-1]=(round['rng_after'][1][-1]+1)%625
            elif name=='physical':child['deliveries'][0]['entity']['entity_id']=child['request']['materials'][0]['copy']['origin']['next_entity_id']
            elif name=='owner':child['deliveries'][0]['entity']['owner']=2
            elif name=='material':child['request']['materials'][0]['copy']['local']['base_attack']+=1
            elif name=='tail':bad['resolution_frame']['fields']['continuation']['tuple']=[]
            else:child['request']['producer_link']={'batch_id':1,'index':0}
            self.reject(bad,name)

    def test_legacy_active_quantity_and_choice_control_injection_roll_back(self):
        for name,pattern in(('rr_legacy','Unattributed summon'),('rr_inject','inject physical recruit control')):
            g=self.game((name,),('source',));before=g.snapshot()
            with self.assertRaisesRegex(Exception,pattern):self.play(g,name)
            self.assertEqual(g.snapshot(),before)
        g=self.game(('rr_legacy',));self.play(g,'rr_legacy');self.assertFalse(g.state.recruit_summon_history);self.portable(g)

    def test_printed_filters_keep_complete_zone_inventory_and_all_original_refs(self):
        g=self.game(('rr_filtered',),('source',),deck=('other','body','rr_once'));self.play(g,'rr_filtered')
        round=g.state.recruit_summon_history[0].rounds[0]
        self.assertEqual(len(round.basis.inventory),3);self.assertEqual([x.card_id for x in round.candidates],['body']);self.portable(g)

    def test_selected_reference_can_depart_in_real_before_entry_choice(self):
        g=self.game(('rr_pause',),('source',));original=g.state.players[1].deck[0];self.play(g,'rr_pause');self.portable(g)
        self.assertFalse(g.state.card_summon_history);self.assertEqual(g.state.recruit_summon_history[0].rounds[0].entry_status,'unattempted')
        self.choose(g,'move');parent=g.state.recruit_summon_history[0]
        self.assertEqual([x.entry_status for x in parent.rounds],['stale','rooted']);self.assertEqual(parent.status,'completed')
        self.assertIsNone(parent.rounds[0].entry_root_id);self.assertEqual(g.state.entities[original].zone,Zone.HAND);self.portable(g)

    def test_unattempted_physical_entry_owed_work_cannot_be_cropped_or_borrowed(self):
        g=self.game(('rr_pause',),('source',));self.play(g,'rr_pause');s=self.portable(g)
        for name in('crop','source','cause'):
            bad=deepcopy(s)
            def change(v):
                if type(v)is dict:
                    if str(v.get('type','')).endswith('.SummonStoredCard')and v['fields'].get('producer_link'):
                        if name=='source':v['fields']['card']['fields']['entity_id']=bad['state']['next_entity_id']
                        elif name=='cause':v['fields']['cause']['fields']['action']=bad['state']['action_number']+1
                        return True
                    return any(change(x)for x in v.values())
                if type(v)is list:return any(change(x)for x in v)
                return False
            if name=='crop':bad['resolution_frame']['fields']['continuation']['tuple']=[]
            else:self.assertTrue(change(bad))
            self.reject(bad,name)

    def test_hand_dormancy_is_initialized_for_physical_first_and_each_extra(self):
        g=self.game(('rr_hand','cx_dormant'),('source',));original=g.state.players[1].hand[-1];self.play(g,'rr_hand')
        self.assertEqual(self.bodies(g)[0].id,original);self.assertTrue(all(e.dormancy is not None for e in self.bodies(g)));self.portable(g)

    def test_temporary_hand_first_and_extras_keep_original_lifetime(self):
        g=self.game(('cx_temporary','rr_hand'),('source',));self.play(g,'cx_temporary')
        original=next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id=='body')
        self.play(g,'rr_hand');self.assertEqual(self.bodies(g)[0].id,original.id)
        self.assertTrue(all(e.hand_lifetime==original.hand_lifetime for e in self.bodies(g)));self.portable(g)

    def test_uninitialized_stored_herald_rank_is_captured_for_original_and_extra(self):
        g=self.game(('rr_herald_twice','source','rr_hand','rr_soldier'),hero='rr_mage')
        original=g.state.players[1].hand[-1];self.assertIsNone(g.state.entities[original].herald_rank)
        self.play(g,'rr_herald_twice');self.play(g,'source');self.play(g,'rr_hand')
        root=g.state.card_summon_history[0]
        self.assertEqual(root.request.materials[0].copy.entry_herald_count,2)
        self.assertEqual([(e.herald_rank,e.attack,e.health)for e in self.bodies(g)],[(1,2,2)]*2)
        self.assertEqual(self.bodies(g)[0].id,original);self.portable(g)

    def test_later_herald_count_changes_but_accepted_extra_keeps_old_rank(self):
        g=self.game(('rr_herald_twice','source','rr_once'),('rr_herald_watch',),deck=('rr_soldier',),hero='rr_mage')
        self.play(g,'rr_herald_twice');self.play(g,'source');self.play(g,'rr_once');self.portable(g)
        root=g.state.card_summon_history[0]
        self.assertEqual((root.plan.total,len(root.deliveries),root.request.materials[0].copy.entry_herald_count),(2,1,2))
        self.assertEqual(len(g.state.herald_history),4)
        self.choose(g,'ok');self.assertEqual([(e.herald_rank,e.attack,e.health)for e in self.bodies(g)],[(1,2,2)]*2)
        self.assertFalse(any(g.state.entities[i].card_id=='source'for i in g.state.players[1].board));self.portable(g)

    def test_attributed_stored_current_copy_initializes_deferred_herald_strength(self):
        g=self.game(('rr_herald_twice','source','rr_copy_soldier','rr_soldier'),hero='rr_mage')
        original=g.state.players[1].hand[-1];self.play(g,'rr_herald_twice');self.play(g,'source');self.play(g,'rr_copy_soldier')
        self.assertEqual(g.state.card_summon_history[0].request.materials[0].entry_herald_count,2)
        self.assertEqual([(e.herald_rank,e.attack,e.health)for e in self.bodies(g)],[(1,2,2)]*2)
        self.assertIsNone(g.state.entities[original].herald_rank);self.assertEqual(g.state.entities[original].zone,Zone.HAND);self.portable(g)

    def test_legacy_stored_current_copy_initializes_deferred_herald_strength(self):
        g=self.game(('rr_herald_twice','rr_legacy_copy_soldier','rr_soldier'),hero='rr_mage')
        original=g.state.players[1].hand[-1];self.play(g,'rr_herald_twice');before=list(g.state.players[1].board)
        self.play(g,'rr_legacy_copy_soldier');created=[g.state.entities[i]for i in g.state.players[1].board if i not in before]
        self.assertEqual([(e.herald_rank,e.attack,e.health)for e in created],[(1,2,2)])
        self.assertIsNone(g.state.entities[original].herald_rank);self.assertFalse(g.state.card_summon_history);self.portable(g)

    def test_stored_entry_stats_override_frozen_herald_strength_before_reactions(self):
        g=self.game(('rr_herald_twice','source','rr_stats'),deck=('rr_soldier',),hero='rr_mage')
        self.play(g,'rr_herald_twice');self.play(g,'source');self.play(g,'rr_stats')
        self.assertEqual([(e.herald_rank,e.attack,e.health)for e in self.bodies(g)],[(1,9,2)]*2)
        self.assertEqual(g.state.card_summon_history[0].request.materials[0].copy.entry_herald_count,2);self.portable(g)

    def test_rehashed_accepted_deferred_strength_edits_are_rejected(self):
        g=self.game(('rr_herald_twice','source','rr_once'),('rr_herald_watch',),deck=('rr_soldier',),hero='rr_mage')
        self.play(g,'rr_herald_twice');self.play(g,'source');self.play(g,'rr_once');s=self.portable(g)
        for value in(None,4):
            bad=deepcopy(s);bad['state']['card_summon_history'][0]['request']['materials'][0]['copy']['entry_herald_count']=value
            self.reject(bad,'deferred-entry-count-'+str(value))
