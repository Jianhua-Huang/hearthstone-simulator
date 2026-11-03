"""Real source adapters, exact RNG policies and interrupted batch receipts."""
from copy import deepcopy
from dataclasses import replace
import json,unittest
from random import Random

from hs_sim.engine import CardDefinition,CardMetadata,CardClass,CardType,Rarity,Game,PlayerSetup,Scenario,PlayCard,TriggerSpec,SummonCause,SnapshotError
from hs_sim.engine.effects import Buff,ChoiceOption,Damage,Destroy,EquipWeapon,GainArmor,RandomDamage,RequestChoice,ReplaceHero,Transform
from hs_sim.engine.pools import (GenerateFromPool,SummonFromCandidates,SummonFromPool,DiscoverFromPool,
    GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery)
from hs_sim.engine.pool_summons import FinishPoolSummonBatch
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
import test_v160_summon_quantities as base

CONTEXT=GenerationContext('v161-target','experimental')


def registry():
    r=base.registry()
    for name,attack in (('red',1),('green',2),('blue',3),('ared',1)):
        r.register_card(CardDefinition(name,name,CardType.MINION,health=4,attack=attack,metadata=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON)))
        r.register_pool_card(PoolCard.from_definition(r.card(name),identity='red-family'if name in ('red','ared')else None))
    r.register_pool(PoolDefinition('weighted','v1','v161-target','experimental',(PoolMember('red',1),PoolMember('green',4),PoolMember('blue',2))))
    r.register_pool(PoolDefinition('aliases','v1','v161-target','experimental',(PoolMember('red',1),PoolMember('ared',1),PoolMember('green',4),PoolMember('blue',2))))
    r.register_pool(PoolDefinition('empty','v1','v161-target','experimental',()))
    for name,kind in (('mage_card',CardType.MINION),('rogue_card',CardType.MINION),('mage_hero',CardType.HERO),('rogue_hero',CardType.HERO)):
        hero_class=CardClass.MAGE if name.startswith('mage')else CardClass.ROGUE
        r.register_card(CardDefinition(name,name,kind,health=30 if kind==CardType.HERO else 4,attack=1,
            metadata=CardMetadata(kind==CardType.MINION,(hero_class,),Rarity.COMMON)))
        if kind==CardType.MINION:r.register_pool_card(PoolCard.from_definition(r.card(name)))
    r.register_pool(PoolDefinition('classes','v1','v161-target','experimental',(PoolMember('mage_card'),PoolMember('rogue_card'))))
    # A fully declared eligible metadata row without execution must not disappear.
    unknown=PoolCard('unknown',CardType.MINION,0,CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON))
    r.register_pool_card(unknown)
    r.register_pool(PoolDefinition('unknown','v1','v161-target','experimental',(PoolMember('unknown'),PoolMember('red'))))
    query=PoolQuery(kinds=(CardType.MINION,),collectible=True)
    def pool(c,pool_id='weighted',empty='skip',player=None):
        return SummonFromPool(c.player_id if player is None else player,pool_id,query,c.source_id,empty=empty,cause=SummonCause.capture(c))
    def batch(c,count=3,replacement=True,pool_id='weighted'):
        return GenerateFromPool(c.player_id,pool_id,query,count,c.source_id,replacement,'board',cause=SummonCause.capture(c))
    def watch(c):
        roots=c.state.card_summon_history
        if not roots or roots[-1].request.producer_link is None or roots[-1].request.producer_link.index!=0:return []
        if not roots[-1].deliveries or roots[-1].deliveries[-1].index!=0:return []
        sources=[i for i in c.state.players[1].board if c.state.entities[i].card_id=='source']
        return [*(Destroy(i,c.source_id)for i in sources),Buff(c.event.target_id,attack=20,source_id=c.source_id),
            RequestChoice(c.player_id,(ChoiceOption('bad','Failure',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),EquipWeapon(1,'red'))),
                ChoiceOption('ok','Continue',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),GainArmor(1,1)))),c.source_id)]
    r.register_behavior('pool_watch',watch)
    r.register_card(CardDefinition('pool_watcher','Original batch first entry',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','pool_watch'),)))
    def nested(c):
        if len(c.state.pool_summon_history)!=1:return []
        return [CastSpell(1,'batch',c.source_id,choices='player')]
    r.register_behavior('nested_batch',nested)
    r.register_card(CardDefinition('nested_watcher','Nested producer',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','nested_batch'),)))
    def class_watch(c):
        if not c.state.card_summon_history or c.state.players[1].hero_class!=CardClass.MAGE:return []
        return [ReplaceHero(1,'rogue_hero'),RequestChoice(1,(ChoiceOption('ok','Continue',()),),c.source_id)]
    r.register_behavior('class_watch',class_watch)
    r.register_card(CardDefinition('class_watcher','Change class at entry',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','class_watch'),)))
    def caller_body(c):
        return [SummonFromPool(1,'self',replace(query,exclude_source=True),c.source_id,cause=SummonCause.capture(c))]
    r.register_behavior('caller_body',caller_body)
    r.register_card(CardDefinition('caller','Caller',CardType.MINION,cost=1,health=4,attack=1,battlecry='caller_body',
        metadata=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON)))
    r.register_pool_card(PoolCard.from_definition(r.card('caller')))
    r.register_pool(PoolDefinition('self','v1','v161-target','experimental',(PoolMember('caller'),PoolMember('red'))))
    def morph(c):
        callers=[i for i in c.state.players[1].board if c.state.entities[i].card_id=='caller']
        if not callers or not c.state.card_summon_history:return []
        return [Transform(callers[0],'green'),RequestChoice(1,(ChoiceOption('ok','Continue',()),),c.source_id)]
    r.register_behavior('morph',morph)
    r.register_card(CardDefinition('morph_watcher','Change source at entry',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','morph'),)))
    body={
        'finite':lambda c:[SummonFromCandidates(c.player_id,('red','green','blue'),c.source_id,SummonCause.capture(c))],
        'pool':lambda c:[pool(c)],'pool_empty':lambda c:[pool(c,'empty')],
        'pool_error':lambda c:[pool(c,'empty','error')],'alias_pool':lambda c:[pool(c,'aliases')],
        'pool_enemy':lambda c:[pool(c,player=2)],'pool_unknown':lambda c:[pool(c,'unknown')],
        'finite_unknown':lambda c:[SummonFromCandidates(1,('red','unknown'),c.source_id,SummonCause.capture(c))],
        'batch':lambda c:[batch(c)],'batch_nr':lambda c:[batch(c,5,False)],'batch_empty':lambda c:[batch(c,pool_id='empty')],
        'board_discovery':lambda c:[DiscoverFromPool(1,'weighted',query,source_id=c.source_id,destination='board')],
        'waiting_pool':lambda c:[RequestChoice(1,(ChoiceOption('ok','Pool',(pool(c),)),),c.source_id)],
        'waiting_batch':lambda c:[RequestChoice(1,(ChoiceOption('ok','Batch',(batch(c),)),),c.source_id)],
        'pool_injection':lambda c:[RequestChoice(1,(ChoiceOption('bad','Injected',(FinishPoolSummonBatch(1),)),),c.source_id)],
        'pool_retry':lambda c:[batch(c)],
        'class_batch':lambda c:[GenerateFromPool(1,'classes',replace(query,class_mode='current',include_neutral=False),3,c.source_id,destination='board',cause=SummonCause.capture(c))],
    }
    from hs_sim.engine import Keyword,RewindSpec
    for name,fn in body.items():
        r.register_behavior(name,fn);r.register_card(CardDefinition(name,name,CardType.SPELL,cost=1,on_play=name,
            keywords=(Keyword.REWIND,)if name=='pool_retry'else(),rewind=RewindSpec(1)if name=='pool_retry'else None))
    return r


def independent_draw(rng,rows,count,replacement=True):
    remaining=list(rows);out=[]
    for _ in range(count if replacement else min(count,len(remaining))):
        if not remaining:break
        ticket=rng.randrange(sum(w for _,w in remaining))
        for index,(name,weight)in enumerate(remaining):
            if ticket<weight:
                out.append(name)
                if not replacement:remaining.pop(index)
                break
            ticket-=weight
    return tuple(out)


class PoolSummonTests(unittest.TestCase):
    blob=base.SummonQuantityTests.blob
    play=base.SummonQuantityTests.play
    choose=base.SummonQuantityTests.choose
    def game(self,hand=(),board=(),enemy=(),hero='hero'):
        g=Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,mana=10,max_mana=10,deck=('red',)*5),
            PlayerSetup('hero',board=enemy,deck=('blue',)*5)),seed=161,generation_context=CONTEXT),registry())
        self.blob(g,'initial');return g
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));self.blob(s,'portable')
        self.assertEqual(Game.from_snapshot(deepcopy(s),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        for p in (1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for name in ('pool_summon_history','pool_summon_accepted','pool_summon_finished','card_summon_accepted','card_summon_finished','rng_before','rng_after','PoolSummonBasis'):
                self.assertNotIn('"'+name+'"',public)
        return s
    def reject(self,s,name):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
        self.blob(s,name)
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())
    def rng(self,g):
        snap=g.snapshot()['rng_state'];local=Random();local.setstate((snap[0],tuple(snap[1]),snap[2]));return local

    def test_finite_adapter_preserves_one_uniform_draw_and_duplicates_result(self):
        g=self.game(('finite',),('source',));rng=self.rng(g);expected=rng.choice(('red','green','blue'))
        self.play(g,'finite');root=g.state.card_summon_history[-1]
        self.assertEqual([d.entity.card_id for d in root.deliveries],[expected]*2);self.assertEqual(root.rng_after,rng.getstate());self.portable(g)
    def test_pool_adapter_preserves_original_weighted_integer_ticket(self):
        g=self.game(('pool',),('source',));rng=self.rng(g);expected=independent_draw(rng,(('blue',2),('green',4),('red',1)),1)
        self.play(g,'pool');root=g.state.card_summon_history[-1]
        self.assertEqual(root.request.weights,(2,4,1));self.assertEqual([d.entity.card_id for d in root.deliveries],[expected[0]]*2)
        self.assertEqual(root.rng_after,rng.getstate());self.portable(g)
    def test_alias_deduplication_preserves_canonical_identity_and_weight(self):
        g=self.game(('alias_pool',),('source',));rng=self.rng(g);expected=independent_draw(rng,(('ared',1),('blue',2),('green',4)),1)
        self.play(g,'alias_pool');root=g.state.card_summon_history[-1]
        self.assertEqual([m.card_id for m in root.request.materials],['ared','blue','green'])
        self.assertEqual(root.deliveries[0].entity.card_id,expected[0]);self.portable(g)
    def test_full_finite_and_pool_skip_rng_but_keep_complete_inventory(self):
        for name in ('finite','pool'):
            with self.subTest(name=name):
                g=self.game((name,),('source',)+('red',)*6);before=g.snapshot()['rng_state'];self.play(g,name)
                root=g.state.card_summon_history[-1];self.assertEqual((root.selected,root.status),(None,'skipped'))
                self.assertEqual(len(root.request.materials),3);self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)
    def test_empty_pool_skip_and_error_are_distinct_and_rng_neutral(self):
        g=self.game(('pool_empty',),('source',));before=g.snapshot()['rng_state'];self.play(g,'pool_empty')
        root=g.state.card_summon_history[-1];self.assertEqual((root.request.materials,root.selected,root.status),((),None,'skipped'))
        self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)
        h=self.game(('pool_error',),('source',));s=h.snapshot()
        with self.assertRaisesRegex(Exception,'Empty summon pool'):self.play(h,'pool_error')
        self.assertEqual(h.snapshot(),s)
    def test_batch_draws_all_original_results_before_independent_quantity_entries(self):
        g=self.game(('batch',),('source',));rng=self.rng(g);expected=independent_draw(rng,(('blue',2),('green',4),('red',1)),3)
        self.play(g,'batch');batch=g.state.pool_summon_history[-1]
        self.assertEqual((batch.selected,batch.rng_after,batch.status),(expected,rng.getstate(),'completed'))
        self.assertEqual([r.plan.total for r in g.state.card_summon_history],[2,2,2])
        self.assertEqual([r.request.materials[0].card_id for r in g.state.card_summon_history],list(expected));self.portable(g)
    def test_initial_full_batch_still_consumes_all_original_draws_and_records_failures(self):
        g=self.game(('batch',),('source',)+('red',)*6);rng=self.rng(g);expected=independent_draw(rng,(('blue',2),('green',4),('red',1)),3)
        self.play(g,'batch');batch=g.state.pool_summon_history[-1]
        self.assertEqual((batch.selected,batch.rng_after),(expected,rng.getstate()))
        self.assertTrue(all(r.selected==0 and [d.outcome for d in r.deliveries]==['board_full','board_full']for r in g.state.card_summon_history));self.portable(g)
    def test_batch_without_replacement_keeps_original_three_distinct_items(self):
        g=self.game(('batch_nr',),('source',));rng=self.rng(g);expected=independent_draw(rng,(('blue',2),('green',4),('red',1)),5,False)
        self.play(g,'batch_nr');batch=g.state.pool_summon_history[-1]
        self.assertEqual((batch.selected,batch.rng_after),(expected,rng.getstate()));self.assertEqual(len(set(batch.selected)),3);self.portable(g)
    def test_empty_batch_has_complete_zero_entry_receipt_without_rng(self):
        g=self.game(('batch_empty',),('source',));before=g.snapshot()['rng_state'];self.play(g,'batch_empty')
        batch=g.state.pool_summon_history[-1];self.assertEqual((batch.selected,batch.entry_root_ids,batch.status),((),(),'completed'))
        self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)
    def test_first_true_wait_changes_source_and_rng_without_redrawing_batch(self):
        g=self.game(('batch',),('source','pool_watcher'));self.play(g,'batch');s=self.portable(g)
        selected=g.state.pool_summon_history[-1].selected;before=g.state.card_summon_history[-1].rng_after
        with self.assertRaises(Exception):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),s);self.choose(g,'ok')
        self.assertEqual(g.state.pool_summon_history[-1].selected,selected)
        self.assertEqual([r.plan.total for r in g.state.card_summon_history],[2,1,1])
        first=g.state.card_summon_history[0];self.assertGreater(g.state.entities[first.deliveries[0].entity.entity_id].attack,20)
        self.assertLess(g.state.entities[first.deliveries[1].entity.entity_id].attack,4)
        self.assertNotEqual(g.state.card_summon_history[1].rng_before,before);self.portable(g)
    def test_causing_player_is_separate_from_pool_recipient(self):
        g=self.game(('pool_enemy',),('source',));self.play(g,'pool_enemy');root=g.state.card_summon_history[-1]
        self.assertEqual((root.request.cause.player_id,root.request.pool_basis.player_id,root.plan.total),(1,2,2));self.portable(g)
    def test_unknown_candidates_reject_without_pruning_even_on_full_board(self):
        for name in ('finite_unknown','pool_unknown'):
            with self.subTest(name=name):
                g=self.game((name,),('source',)+('red',)*6);s=g.snapshot()
                with self.assertRaises(Exception):self.play(g,name)
                self.assertEqual(g.snapshot(),s)
    def test_saved_public_pool_and_batch_requests_restore_before_execution(self):
        for name in ('waiting_pool','waiting_batch'):
            with self.subTest(name=name):
                g=self.game((name,),('source',));self.play(g,name);self.portable(g);self.choose(g,'ok');self.portable(g)
    def test_board_discovery_and_injected_control_reject_explicitly(self):
        for name,pattern in (('board_discovery','Unattributed summon'),('pool_injection','inject pool summon control')):
            with self.subTest(name=name):
                g=self.game((name,),('source',))
                if name=='pool_injection':g.runtime_mode='debug'
                s=g.snapshot()
                with self.assertRaisesRegex(Exception,pattern):self.play(g,name)
                self.assertEqual(g.snapshot(),s)
    def test_current_and_outer_receipts_reject_weight_draw_link_and_queue_edits(self):
        g=self.game(('batch',),('source','pool_watcher'));self.play(g,'batch');s=self.portable(g)
        for name in ('weight','selected','RNG','index','crop-roots','crop-next','crop-finish'):
            with self.subTest(name=name):
                bad=deepcopy(s);batch=bad['state']['pool_summon_history'][0]
                if name=='weight':batch['spec']['basis']['candidates'][0]['weight']=3
                elif name=='selected':batch['selected'][0]='unknown'
                elif name=='RNG':batch['rng_after'][1][2]^=1
                elif name=='index':bad['state']['card_summon_history'][0]['request']['producer_link']['index']=1
                elif name=='crop-roots':batch['entry_root_ids']=[]
                else:
                    tail=bad['resolution_frame']['fields']['continuation']['tuple']
                    kind='StartPoolSummonEntry'if name=='crop-next'else 'FinishPoolSummonBatch'
                    index=next(i for i,w in enumerate(tail)if w.get('type','').endswith('.'+kind));tail.pop(index)
                self.reject(bad,name)
    def test_true_retry_removes_old_batch_and_children_but_keeps_monotonic_ids(self):
        g=self.game(('pool_retry',),('source',));self.play(g,'pool_retry');self.portable(g)
        old=g.state.pool_summon_history[-1];ids=old.entry_root_ids;self.choose(g,'retry')
        self.assertEqual(len(g.state.pool_summon_history),1);self.assertGreater(g.state.pool_summon_history[-1].id,old.id)
        self.assertGreater(min(g.state.pool_summon_history[-1].entry_root_ids),max(ids));self.assertIsNone(g.state.pending_choice);self.portable(g)
    def test_terminal_interrupts_one_actual_entry_prefix_and_the_original_batch(self):
        g=self.game(('batch',),('source','fatal_watcher'));self.play(g,'batch')
        batch=g.state.pool_summon_history[-1];self.assertEqual((batch.status,len(batch.entry_root_ids)),('interrupted',1))
        self.assertEqual(g.state.card_summon_history[-1].status,'interrupted');self.portable(g)
    def test_nested_batch_has_its_own_draw_and_entry_identities(self):
        g=self.game(('batch',),('source','nested_watcher'));self.play(g,'batch')
        batches=g.state.pool_summon_history;self.assertEqual(len(batches),2)
        self.assertTrue(all(r.status=='completed'for r in batches))
        self.assertFalse(set(batches[0].entry_root_ids)&set(batches[1].entry_root_ids));self.portable(g)
    def test_original_class_basis_survives_hero_class_change_before_later_entries(self):
        g=self.game(('class_batch',),('source','class_watcher'),hero='mage_hero');self.play(g,'class_batch');s=self.portable(g)
        self.assertEqual(g.state.players[1].hero_class,CardClass.ROGUE)
        batch=g.state.pool_summon_history[0];self.assertEqual((batch.spec.basis.hero_class,batch.selected),(CardClass.MAGE,('mage_card',)*3))
        bad=deepcopy(s);bad['state']['pool_summon_history'][0]['spec']['basis']['hero_class']=CardClass.ROGUE.value;self.reject(bad,'change-original-class')
        self.choose(g,'ok');self.assertTrue(all(r.request.materials[0].card_id=='mage_card'for r in g.state.card_summon_history));self.portable(g)
    def test_original_excluded_query_source_survives_transformation(self):
        g=self.game(('caller',),('source','morph_watcher'));self.play(g,'caller');s=self.portable(g)
        root=g.state.card_summon_history[-1];basis=root.request.pool_basis
        self.assertEqual((basis.source.card_id,[m.card_id for m in basis.candidates]),('caller',['red']))
        self.assertEqual(g.state.entities[basis.source.entity_id].card_id,'green')
        bad=deepcopy(s);bad['state']['card_summon_history'][0]['request']['pool_basis']['source']['card_id']='green';self.reject(bad,'borrow-current-query-source')
        self.choose(g,'ok');self.assertEqual([d.entity.card_id for d in g.state.card_summon_history[0].deliveries],['red','red']);self.portable(g)
    def test_saved_public_producer_cause_and_query_source_use_their_own_scope(self):
        for name in ('waiting_pool','waiting_batch'):
            with self.subTest(name=name):
                g=self.game((name,),('source',));self.play(g,name);s=self.portable(g)
                for field in ('cast_id','source_id'):
                    bad=deepcopy(s);request=bad['resolution_frame']['fields']['options']['tuple'][0]['fields']['effects']['tuple'][0]['fields']
                    if field=='cast_id':request['cause']['fields']['cast_id']=999999
                    else:request['source_id']=999999
                    self.reject(bad,'future-queued-'+field)
