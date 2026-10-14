"""Native selected entry-strength acceptance, combinations, and portable boundaries."""
from copy import deepcopy
from dataclasses import replace
import json,unittest
from hs_sim.engine import (AuraSpec,CardClass,CardMetadata,CardDefinition,CardType,Game,Keyword,PlayerSetup,Rarity,RewindSpec,Scenario,
    SnapshotError,SummonByCard,SummonCause,SummonEntryMaterial,SummonStats,TriggerSpec,Zone,Herald)
from hs_sim.engine.effects import ChoiceOption,CopyMinion,Damage,Destroy,EquipWeapon,RandomDamage,RequestChoice
from hs_sim.engine.pools import GenerateFromPool,DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.summon_sources import CopyStoredMinion
from hs_sim.engine.zones import CardReference
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
import test_v165_resurrection_summons as base

CONTEXT=GenerationContext('v166-target','experimental')

def registry():
    r=base.registry()
    r.register_card(CardDefinition('es_aura','Scaling printed aura',CardType.MINION,attack=1,health=1,herald_scaling=True,auras=(AuraSpec(attack=1),)))
    r.register_card(CardDefinition('es_pool_soldier','Pool entry scaling',CardType.MINION,attack=1,health=1,herald_scaling=True,
        metadata=CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON)))
    r.register_pool_card(PoolCard.from_definition(r.card('es_pool_soldier')))
    r.register_pool(PoolDefinition('es_pool','v1','v166-target','experimental',(PoolMember('es_pool_soldier'),)))
    def summon(c,player=1,stats=None,card='rr_soldier',selection='first',capacity='selection_requires_space'):
        return SummonByCard(player,(SummonEntryMaterial(card,stats),),SummonCause.capture(c),selection=selection,capacity=capacity)
    def stored(c,mode):
        ref=CardReference.capture(next(c.state.entities[i]for i in c.state.players[1].hand if c.state.entities[i].card_id=='rr_soldier'))
        return CopyStoredMinion(ref,1,mode=mode,cause=SummonCause.capture(c))
    def watch(c):
        roots=c.state.card_summon_history
        if len(roots)!=1 or len(roots[0].deliveries)!=1 or roots[0].deliveries[0].entity is None or c.event.target_id!=roots[0].deliveries[0].entity.entity_id:return[]
        root=roots[0]
        if root.request.materials[root.selected].card_id not in('rr_soldier','es_aura','es_pool_soldier'):return[]
        return[*(Destroy(i,c.source_id)for i in c.state.players[1].board if c.state.entities[i].card_id=='source' or
                c.state.entities[i].card_id=='rr_soldier'and i!=c.event.target_id),
            Herald(root.request.player_id,c.source_id),Herald(root.request.player_id,c.source_id),
            RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Failure',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),EquipWeapon(1,'body')))),c.source_id)]
    r.register_behavior('es_watch',watch)
    r.register_card(CardDefinition('es_watch','Change counter after first body',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','es_watch'),)))
    def before_pick(c):
        if not c.state.discovery_summon_history or c.state.card_summon_history or sum(x.player_id==1 for x in c.state.herald_history)!=2:return[]
        return[Herald(1,c.source_id),Herald(1,c.source_id)]
    r.register_behavior('es_before_pick',before_pick)
    r.register_card(CardDefinition('es_before_pick','Change counter in original choice reaction',CardType.MINION,health=5,
        triggers=(TriggerSpec('choice_selected','es_before_pick'),)))
    def nested(c):
        roots=c.state.card_summon_history
        if len(roots)!=1 or len(roots[0].deliveries)!=1 or roots[0].deliveries[0].entity is None or c.event.target_id!=roots[0].deliveries[0].entity.entity_id:return[]
        return[*(Destroy(i,c.source_id)for i in c.state.players[1].board if c.state.entities[i].card_id=='source'or
                c.state.entities[i].card_id=='rr_soldier'and i!=c.event.target_id),
            Herald(1,c.source_id),Herald(1,c.source_id),CastSpell(1,'es_plain',c.source_id,choices='player')]
    r.register_behavior('es_nested',nested)
    r.register_card(CardDefinition('es_nested','Nested later entry',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','es_nested'),)))
    r.register_behavior('es_fatal',lambda c:[]if not c.state.card_summon_history else[Damage(c.state.players[2].hero_id,100,c.source_id)])
    r.register_card(CardDefinition('es_fatal','Terminate accepted entry',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','es_fatal'),)))
    query=PoolQuery(kinds=(CardType.MINION,))
    def discover(c,delivery):
        return DiscoverFromPool(1,'es_pool',query,count=1,source_id=c.source_id,discoveries=2,destination='board',delivery=delivery,cause=SummonCause.capture(c))
    bodies={
        'es_plain':lambda c:[summon(c)],'es_twice':lambda c:[summon(c),summon(c)],
        'es_enemy':lambda c:[summon(c,2)],'es_stats':lambda c:[summon(c,stats=SummonStats(9,2))],
        'es_random':lambda c:[summon(c,selection='random')],
        'es_force_full':lambda c:[GenerateFromPool(1,'es_pool',query,count=1,source_id=c.source_id,destination='board',cause=SummonCause.capture(c))],
        'es_body':lambda c:[summon(c,card='body')],'es_aura_summon':lambda c:[summon(c,card='es_aura')],
        'es_board_base':lambda c:[CopyMinion(c.target_id,1,mode='base',cause=SummonCause.capture(c))],
        'es_board_current':lambda c:[CopyMinion(c.target_id,1,mode='current',cause=SummonCause.capture(c))],
        'es_stored_base':lambda c:[stored(c,'base')],'es_stored_current':lambda c:[stored(c,'current')],
        'es_batch':lambda c:[GenerateFromPool(1,'es_pool',query,count=2,source_id=c.source_id,destination='board',cause=SummonCause.capture(c))],
        'es_each':lambda c:[discover(c,'after_each')],'es_all':lambda c:[discover(c,'after_all')],
        'es_herald_enemy':lambda c:[Herald(2,c.source_id),Herald(2,c.source_id)],
        'es_kill':lambda c:[Destroy(c.target_id,c.source_id)],
        'es_retry':lambda c:[summon(c,selection='random')],
    }
    for name,fn in bodies.items():
        r.register_behavior(name,fn);r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,
            requires_target=name in('es_board_base','es_board_current','es_kill'),
            keywords=(Keyword.REWIND,)if name=='es_retry'else(),rewind=RewindSpec(1)if name=='es_retry'else None))
    return r

class EntryStrengthTests(unittest.TestCase):
    blob=base.ResurrectionQuantityTests.blob;play=base.ResurrectionQuantityTests.play;choose=base.ResurrectionQuantityTests.choose
    rng=base.ResurrectionQuantityTests.rng;bodies=base.ResurrectionQuantityTests.bodies
    def game(self,hand=(),board=(),enemy=()):
        g=Game.from_scenario(Scenario((PlayerSetup('rr_mage',hand=hand,board=board,deck=('body',)*5,mana=10,max_mana=10),
            PlayerSetup('rr_mage',board=enemy,deck=('body',)*5)),seed=166,generation_context=CONTEXT),registry())
        self.blob(g,'initial');return g
    def ready(self,name,board=('source','es_watch'),extra=()):
        g=self.game(('rr_herald_twice',name)+extra,board);self.play(g,'rr_herald_twice');return g
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));self.blob(s,'portable')
        self.assertEqual(Game.from_snapshot(deepcopy(s),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for key in('entry_strength','AcceptedEntryStrength','card_summon_history','rng_before','rng_after'):
                self.assertNotIn('"'+key+'"',public)
        return s
    def reject(self,s,name):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
        self.blob(s,name)
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())
    def finish_watch(self,g):
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g,'ok');self.portable(g)
    def pick(self,g):
        p=g.state.pending_choice;self.choose(g,p.options[0].id)

    def test_plain_first_reaction_does_not_change_accepted_extra_strength(self):
        g=self.ready('es_plain');self.play(g,'es_plain');root=g.state.card_summon_history[0]
        self.assertEqual((root.entry_strength.count,len(root.entry_strength.history),root.plan.total),(2,2,2))
        self.assertEqual(len(g.state.herald_history),4);self.finish_watch(g)
        self.assertEqual([e.herald_rank for e in self.bodies(g)],[1,1])

    def test_next_original_entry_accepts_new_counter_and_quantity(self):
        g=self.ready('es_twice');self.play(g,'es_twice');self.finish_watch(g)
        self.assertEqual([(x.entry_strength.count,x.plan.total)for x in g.state.card_summon_history],[(2,2),(4,1)])
        self.assertEqual([e.herald_rank for e in self.bodies(g)],[2])

    def test_board_base_copy_rebuilds_at_accepted_recipient_rank(self):
        g=self.ready('es_board_base',('rr_soldier','source','es_watch'));old=next(i for i in g.state.players[1].board if g.state.entities[i].card_id=='rr_soldier')
        self.assertEqual(g.state.entities[old].herald_rank,0);self.play(g,'es_board_base',old);self.finish_watch(g)
        self.assertEqual(g.state.card_summon_history[0].entry_strength.profile,'board_copy_base_herald')
        self.assertEqual([e.herald_rank for e in self.bodies(g)],[1,1])

    def test_stored_base_copy_freezes_rank_without_moving_original(self):
        g=self.ready('es_stored_base',extra=('rr_soldier',));old=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id=='rr_soldier')
        self.play(g,'es_stored_base');self.finish_watch(g);self.assertEqual(g.state.entities[old].zone,Zone.HAND)
        self.assertEqual(g.state.card_summon_history[0].entry_strength.profile,'stored_copy_base_herald')
        self.assertEqual([e.herald_rank for e in self.bodies(g)],[1,1])

    def test_current_board_copy_retains_source_rank_and_has_no_new_fact(self):
        g=self.ready('es_board_current',('rr_soldier','source','es_watch'));old=next(i for i in g.state.players[1].board if g.state.entities[i].card_id=='rr_soldier')
        self.play(g,'es_board_current',old);self.finish_watch(g)
        self.assertIsNone(g.state.card_summon_history[0].entry_strength);self.assertEqual([e.herald_rank for e in self.bodies(g)],[0,0])

    def test_uninitialized_stored_current_uses_its_existing_material_basis(self):
        g=self.ready('es_stored_current',extra=('rr_soldier',));self.play(g,'es_stored_current');self.finish_watch(g)
        root=g.state.card_summon_history[0];self.assertIsNone(root.entry_strength);self.assertEqual(root.request.materials[0].entry_herald_count,2)
        self.assertEqual([e.herald_rank for e in self.bodies(g)],[1,1])

    def test_death_material_keeps_its_independent_counter_basis(self):
        g=self.game(('es_kill','rr_herald_twice','dx_direct'),('rr_soldier','source','es_watch'))
        old=next(i for i in g.state.players[1].board if g.state.entities[i].card_id=='rr_soldier')
        self.play(g,'es_kill',old);self.play(g,'rr_herald_twice');self.play(g,'dx_direct');self.finish_watch(g)
        root=g.state.card_summon_history[0];self.assertIsNone(root.entry_strength);self.assertEqual(root.request.materials[0].entry_herald_count,2)
        self.assertEqual([e.herald_rank for e in self.bodies(g)],[1,1])

    def test_recipient_counter_is_distinct_from_cause_player(self):
        g=self.game(('es_herald_enemy','es_enemy'),('source','es_watch'));self.play(g,'es_herald_enemy');self.play(g,'es_enemy');self.finish_watch(g)
        root=g.state.card_summon_history[0];self.assertEqual((root.request.cause.player_id,root.entry_strength.player_id,root.entry_strength.count),(1,2,2))
        self.assertEqual([(e.owner,e.controller,e.herald_rank)for e in self.bodies(g)],[(2,2,1)]*2)

    def test_pool_batch_keeps_original_materials_but_each_entry_has_own_strength(self):
        g=self.ready('es_batch');self.play(g,'es_batch');self.finish_watch(g)
        self.assertEqual([x.entry_strength.count for x in g.state.card_summon_history],[2,4])
        self.assertEqual([x.request.materials[0].card_id for x in g.state.card_summon_history],['es_pool_soldier']*2)

    def test_after_each_discovery_freezes_strength_only_at_entry(self):
        g=self.ready('es_each');self.play(g,'es_each');self.assertFalse(g.state.card_summon_history);self.portable(g)
        self.pick(g);self.portable(g);self.choose(g,'ok');self.assertEqual(len(g.state.card_summon_history),1)
        self.portable(g);self.pick(g);self.portable(g);self.assertEqual([x.entry_strength.count for x in g.state.card_summon_history],[2,4])

    def test_after_all_discovery_first_finishes_before_next_strength_capture(self):
        g=self.ready('es_all');self.play(g,'es_all');self.pick(g);self.assertFalse(g.state.card_summon_history);self.portable(g)
        self.pick(g);self.finish_watch(g);self.assertEqual([x.entry_strength.count for x in g.state.card_summon_history],[2,4])

    def test_original_discovery_choice_reactions_update_counter_before_entry_acceptance(self):
        g=self.ready('es_each',('source','es_before_pick'));self.play(g,'es_each')
        self.assertFalse(g.state.card_summon_history);self.portable(g);self.pick(g)
        root=g.state.card_summon_history[0];self.assertEqual((root.entry_strength.count,len(root.entry_strength.history)),(4,4))
        self.assertEqual([e.herald_rank for e in self.bodies(g)],[2]);self.assertEqual([x.outcome for x in root.deliveries],['delivered','board_full'])
        self.portable(g);self.pick(g);self.portable(g)

    def test_random_choice_draws_once_then_extras_keep_accepted_basis(self):
        g=self.ready('es_random');local=self.rng(g);self.play(g,'es_random');root=g.state.card_summon_history[0]
        local.randrange(1);self.assertEqual(root.rng_after,local.getstate());self.finish_watch(g)
        self.assertEqual([e.herald_rank for e in self.bodies(g)],[1,1])

    def test_stats_override_after_strength_initialization_for_every_body(self):
        g=self.ready('es_stats');self.play(g,'es_stats');self.finish_watch(g)
        self.assertEqual([(e.attack,e.max_health,e.herald_rank)for e in self.bodies(g)],[(9,2,1)]*2)

    def test_printed_aura_scales_once_using_original_counter(self):
        g=self.ready('es_aura_summon');self.play(g,'es_aura_summon');self.finish_watch(g)
        self.assertEqual([[a.attack for a in e.abilities if a.kind=='aura']for e in self.bodies(g)],[[2],[2]])

    def test_non_scaling_selected_material_has_no_entry_strength(self):
        g=self.ready('es_body',('source',));self.play(g,'es_body');self.assertIsNone(g.state.card_summon_history[0].entry_strength);self.portable(g)

    def test_skipped_full_selection_has_no_fact_and_consumes_no_rng(self):
        g=self.game(('es_random',),('source',)+('body',)*6);before=g.snapshot()['rng_state'];self.play(g,'es_random')
        root=g.state.card_summon_history[0];self.assertEqual((root.selected,root.entry_strength,root.status),(None,None,'skipped'))
        self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)

    def test_forced_full_selection_keeps_fact_and_failed_delivery_prefix(self):
        g=self.game(('es_force_full',),('source',)+('body',)*6);self.play(g,'es_force_full');root=g.state.card_summon_history[0]
        self.assertEqual((root.entry_strength.count,root.status,len(root.deliveries)),(0,'completed',2))
        self.assertEqual([x.outcome for x in root.deliveries],['board_full']*2);self.portable(g)

    def test_terminal_preserves_accepted_fact_without_extra_delivery(self):
        g=self.ready('es_plain',('source','es_fatal'));self.play(g,'es_plain');root=g.state.card_summon_history[0]
        self.assertEqual((root.entry_strength.count,root.status,len(root.deliveries)),(2,'interrupted',1));self.portable(g)

    def test_rng_after_acceptance_failure_rolls_back_original_choice(self):
        g=self.ready('es_plain');self.play(g,'es_plain');before=g.snapshot()
        with self.assertRaises(Exception):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g,'ok');self.portable(g)

    def test_nested_root_uses_new_counter_outer_extra_preserves_old(self):
        g=self.ready('es_plain',('source','es_nested'));self.play(g,'es_plain');self.portable(g)
        self.assertEqual([x.entry_strength.count for x in g.state.card_summon_history],[2,4])
        self.assertEqual([e.herald_rank for e in self.bodies(g,0)],[1,1])

    def test_true_retry_retires_old_strength_and_recomputes_current_basis(self):
        g=self.ready('es_retry',('source',));self.play(g,'es_retry');old=g.state.card_summon_history[0]
        self.portable(g);self.choose(g,'retry');self.portable(g);new=g.state.card_summon_history[0]
        self.assertGreater(new.id,old.id);self.assertEqual(new.entry_strength.history,old.entry_strength.history)

    def test_rehashed_fact_counter_history_identity_and_selection_edits_reject(self):
        g=self.ready('es_plain');self.play(g,'es_plain');s=self.portable(g)
        for name in('count','history','player','profile','index','card','allocator','missing'):
            bad=deepcopy(s);fact=bad['state']['card_summon_history'][0]['entry_strength']
            if name=='count':fact['count']+=1
            elif name=='history':fact['history'].pop()
            elif name=='player':fact['player_id']=2
            elif name=='profile':fact['profile']='stored_copy_base_herald'
            elif name=='index':fact['material_index']=1
            elif name=='card':fact['card_id']='body'
            elif name=='allocator':fact['next_attachment_id']+=1
            else:bad['state']['card_summon_history'][0]['entry_strength']=None
            self.reject(bad,name)

    def test_closed_original_private_receipts_reject_strength_rewrites(self):
        g=self.ready('es_plain',('source',));self.play(g,'es_plain');s=self.portable(g);bad=deepcopy(s)
        event=next(x for x in bad['events']if x['kind']=='card_summon_finished');data=event['data']
        # Snapshot events encode their data as a JSON object.
        root=json.loads(data['root']);root['entry_strength']['count']+=1;data['root']=json.dumps(root)
        self.reject(bad,'closed-count')
