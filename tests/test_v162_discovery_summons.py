"""Native attributed discovery timing, source lifecycle and saved boundaries."""
from copy import deepcopy
from dataclasses import replace
import json,unittest
from random import Random

from hs_sim.engine import CardDefinition,CardClass,CardMetadata,CardType,Game,Keyword,PlayerSetup,Rarity,RewindSpec,Scenario,SnapshotError,SummonCause,TriggerSpec
from hs_sim.engine.effects import ChoiceOption,Destroy,GainArmor,RequestChoice,Transform
from hs_sim.engine.pools import DiscoverFromPool,GenerateFromPool,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.summon_quantities import GrantSummonQuantity
from hs_sim.engine.model import ChoicePurpose,SummonQuantitySpec
from hs_sim.engine.discovery_summons import DiscoverySummonEntryLink,FinishDiscoverySummon
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
import test_v161_pool_summons as base

CONTEXT=base.CONTEXT

def registry():
    r=base.registry();query=PoolQuery(kinds=(CardType.MINION,),collectible=True)
    def discover(c,delivery='after_each',rounds=2,pool='weighted',count=3,replacement=True,query=query):
        return DiscoverFromPool(c.player_id,pool,query,count,c.source_id,discoveries=rounds,destination='board',
            delivery=delivery,replacement=replacement,cause=SummonCause.capture(c))
    bodies={
        'd_single':lambda c:[discover(c,rounds=1)],
        'd_each':lambda c:[discover(c)],'d_all':lambda c:[discover(c,'after_all')],
        'd_nr':lambda c:[discover(c,rounds=5,count=1,replacement=False,pool='aliases')],
        'd_empty':lambda c:[discover(c,pool='empty')],'d_zero':lambda c:[discover(c,rounds=0)],
        'd_unknown':lambda c:[discover(c,pool='unknown')],
        'd_zero_count':lambda c:[discover(c,count=0)],
        'd_enemy':lambda c:[replace(discover(c,rounds=1),player_id=2)],
        'd_mixed':lambda c:[GenerateFromPool(1,'weighted',query,source_id=c.source_id,destination='board',cause=SummonCause.capture(c)),discover(c,rounds=1)],
        'd_class_each':lambda c:[discover(c,pool='classes',query=replace(query,class_mode='current',include_neutral=False))],
        'd_class_all':lambda c:[discover(c,'after_all',pool='classes',query=replace(query,class_mode='current',include_neutral=False))],
        'd_legacy':lambda c:[DiscoverFromPool(1,'weighted',query,source_id=c.source_id,destination='board')],
        'd_hand':lambda c:[DiscoverFromPool(1,'weighted',query,source_id=c.source_id)],
        'd_retry':lambda c:[discover(c,rounds=1)],
        'd_auto':lambda c:[CastSpell(1,'d_single',c.source_id,choices='random')],
        'd_waiting':lambda c:[RequestChoice(1,(ChoiceOption('ok','Discover',(discover(c,rounds=1),)),),c.source_id)],
        'd_inject':lambda c:[RequestChoice(1,(ChoiceOption('bad','Injected',(FinishDiscoverySummon(1),)),),c.source_id)],
    }
    for name,body in bodies.items():
        r.register_behavior(name,body);r.register_card(CardDefinition(name,name,CardType.SPELL,cost=1,on_play=name,
            keywords=(Keyword.REWIND,)if name=='d_retry'else(),rewind=RewindSpec(1)if name=='d_retry'else None))
    def before_pick(c):
        if not c.state.discovery_summon_history or c.state.discovery_summon_history[-1].offers[-1].result is not None:return []
        sources=[i for i in c.state.players[1].board if c.state.entities[i].card_id=='source']
        return [*(Destroy(i,c.source_id)for i in sources),RequestChoice(1,(ChoiceOption('ok','Continue',()),),c.source_id)]if sources else []
    r.register_behavior('d_before_pick',before_pick)
    r.register_card(CardDefinition('d_choice_watcher','Choice reaction',CardType.MINION,health=5,
        triggers=(TriggerSpec('choice_selected','d_before_pick'),)))
    def nested(c):
        if len(c.state.discovery_summon_history)!=1:return []
        return [CastSpell(1,'d_single',c.source_id,choices='player')]
    r.register_behavior('d_nested',nested)
    r.register_card(CardDefinition('d_nested_watcher','Nested discovery',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','d_nested'),)))
    def gain(c):
        roots=c.state.card_summon_history
        if not roots or type(roots[-1].request.producer_link)is not DiscoverySummonEntryLink:return []
        if roots[-1].request.producer_link.index!=0 or roots[-1].deliveries[-1].index!=0:return []
        return [GrantSummonQuantity(c.source_id,SummonQuantitySpec(2),c.source_id)]
    r.register_behavior('d_gain',gain)
    r.register_card(CardDefinition('d_gain_watcher','New quantity source',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','d_gain'),)))
    def caller(c):
        return [discover(c,pool='dself',query=replace(query,exclude_source=True))]
    r.register_behavior('d_caller_body',caller)
    r.register_card(CardDefinition('d_caller','Mutable source',CardType.MINION,cost=1,health=4,attack=1,battlecry='d_caller_body',
        metadata=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON)))
    r.register_pool_card(PoolCard.from_definition(r.card('d_caller')))
    r.register_pool(PoolDefinition('dself','v1','v161-target','experimental',(PoolMember('d_caller'),PoolMember('green'))))
    def morph(c):
        callers=[i for i in c.state.players[1].board if c.state.entities[i].card_id=='d_caller']
        if not callers or not c.state.card_summon_history:return []
        return [Transform(callers[0],'green'),RequestChoice(1,(ChoiceOption('ok','Continue',()),),c.source_id)]
    r.register_behavior('d_morph',morph)
    r.register_card(CardDefinition('d_morph_watcher','Transform query source',CardType.MINION,health=5,triggers=(TriggerSpec('minion_summoned','d_morph'),)))
    return r


class DiscoverySummonTests(unittest.TestCase):
    blob=base.PoolSummonTests.blob
    play=base.PoolSummonTests.play
    choose=base.PoolSummonTests.choose
    rng=base.PoolSummonTests.rng
    def game(self,hand=(),board=(),hero='hero',enemy=()):
        g=Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,mana=10,max_mana=10,deck=('red',)*5),
            PlayerSetup('hero',board=enemy,deck=('blue',)*5)),seed=162,generation_context=CONTEXT),registry())
        self.blob(g,'initial');return g
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));self.blob(s,'portable')
        self.assertEqual(Game.from_snapshot(deepcopy(s),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        for p in (1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for key in ('discovery_summon_history','discovery_summon_accepted','discovery_summon_offered','discovery_summon_picked',
                'discovery_summon_finished','card_summon_history','rng_before','rng_after','DiscoverySummonRecord'):
                self.assertNotIn('"'+key+'"',public)
        return s
    def pick(self,g,card=None):
        choice=g.state.pending_choice;self.assertEqual(choice.purpose,ChoicePurpose.POOL_DISCOVERY)
        option=next(o for o in choice.options if card is None or o.card_id==card)
        self.choose(g,option.id);return option.card_id
    def reject(self,s,name):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
        self.blob(s,name)
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_offer_draws_once_and_selected_card_duplicates_without_new_rng(self):
        g=self.game(('d_single',),('source',));rng=self.rng(g)
        expected=base.independent_draw(rng,(('blue',2),('green',4),('red',1)),3,False)
        self.play(g,'d_single');self.portable(g)
        root=g.state.discovery_summon_history[-1];self.assertEqual(root.offers[0].offered,expected)
        self.assertEqual(root.offers[0].rng_after,rng.getstate());card=self.pick(g,expected[1])
        root=g.state.discovery_summon_history[-1];self.assertEqual(root.status,'completed')
        child=g.state.card_summon_history[-1];self.assertEqual([d.entity.card_id for d in child.deliveries],[card,card])
        self.assertEqual(child.rng_before,child.rng_after);self.assertEqual(child.rng_after,rng.getstate());self.portable(g)

    def test_after_each_current_extra_retains_plan_next_entry_recaptures(self):
        g=self.game(('d_each',),('source','pool_watcher'));self.play(g,'d_each');first=self.pick(g);s=self.portable(g)
        with self.assertRaises(Exception):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),s);self.choose(g,'ok');self.portable(g);self.pick(g)
        self.assertEqual([r.plan.total for r in g.state.card_summon_history],[2,1])
        root=g.state.card_summon_history[0]
        self.assertEqual([d.entity.card_id for d in root.deliveries],[first,first])
        self.assertGreater(g.state.entities[root.deliveries[0].entity.entity_id].attack,20)
        self.assertLess(g.state.entities[root.deliveries[1].entity.entity_id].attack,4);self.portable(g)

    def test_after_all_freezes_choices_before_independent_entry_acceptances(self):
        g=self.game(('d_all',),('source','pool_watcher'));self.play(g,'d_all');first=self.pick(g);self.portable(g)
        self.assertFalse(g.state.card_summon_history);second=self.pick(g);self.portable(g)
        self.choose(g,'ok')
        self.assertEqual([r.request.materials[0].card_id for r in g.state.card_summon_history],[first,second])
        self.assertEqual([r.plan.total for r in g.state.card_summon_history],[2,1]);self.portable(g)

    def test_choice_reactions_can_change_quantity_before_actual_entry(self):
        g=self.game(('d_single',),('source','d_choice_watcher'));self.play(g,'d_single');self.pick(g);self.portable(g)
        self.assertFalse(g.state.card_summon_history);self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.EFFECT)
        self.choose(g,'ok');self.assertEqual(g.state.card_summon_history[-1].plan.total,1);self.portable(g)

    def test_new_source_from_first_body_only_changes_next_original_entry(self):
        g=self.game(('d_each',),('d_gain_watcher',));self.play(g,'d_each');self.pick(g);self.portable(g);self.pick(g)
        self.assertEqual([r.plan.total for r in g.state.card_summon_history],[1,2]);self.portable(g)

    def test_full_board_keeps_offers_and_records_each_failed_attempt(self):
        g=self.game(('d_each',),('source',)+('red',)*6);self.play(g,'d_each');self.pick(g);self.portable(g);self.pick(g)
        self.assertTrue(all([d.outcome for d in r.deliveries]==['board_full','board_full']for r in g.state.card_summon_history))
        self.assertTrue(all(o.rng_before!=o.rng_after for o in g.state.discovery_summon_history[0].offers));self.portable(g)

    def test_nonreplacement_identity_exclusion_ends_with_complete_empty_offer(self):
        g=self.game(('d_nr',),('source',));self.play(g,'d_nr');cards=[]
        while g.state.pending_choice is not None:
            self.portable(g);cards.append(self.pick(g))
        root=g.state.discovery_summon_history[-1]
        self.assertEqual(len(cards),3);self.assertEqual(len(set(cards)),3)
        self.assertEqual((root.exhausted,root.status,len(root.offers)),(True,'completed',4))
        self.assertEqual(root.offers[-1].rng_before,root.offers[-1].rng_after);self.portable(g)

    def test_zero_rounds_and_empty_pool_are_rng_neutral_complete_producers(self):
        for name,offers in (('d_zero',0),('d_empty',1)):
            with self.subTest(name=name):
                g=self.game((name,),('source',));rng=g.snapshot()['rng_state'];self.play(g,name)
                root=g.state.discovery_summon_history[-1]
                self.assertEqual((root.status,len(root.offers),root.entry_root_ids),('completed',offers,()))
                self.assertEqual(g.snapshot()['rng_state'],rng);self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_unknown_complete_inventory_rejects_before_offer_rng(self):
        g=self.game(('d_unknown',),('source',));s=g.snapshot()
        with self.assertRaises(Exception):self.play(g,'d_unknown')
        self.assertEqual(g.snapshot(),s)

    def test_current_class_each_requeries_after_delivery_all_preserves_prior_picks(self):
        for name,expected in (('d_class_each',('mage_card','rogue_card')),('d_class_all',('mage_card','mage_card'))):
            with self.subTest(name=name):
                g=self.game((name,),('source','class_watcher'),hero='mage_hero');self.play(g,name)
                first=self.pick(g)
                if name=='d_class_each':self.choose(g,'ok')
                self.portable(g);second=self.pick(g)
                if name=='d_class_all':self.choose(g,'ok')
                self.assertEqual((first,second),expected);self.assertEqual(g.state.players[1].hero_class,CardClass.ROGUE)
                self.assertEqual([x.request.materials[0].card_id for x in g.state.card_summon_history],list(expected));self.portable(g)

    def test_source_face_query_updates_next_offer_without_rewriting_original_cause(self):
        g=self.game(('d_caller',),('source','d_morph_watcher'));self.play(g,'d_caller');self.pick(g,'green');self.portable(g);self.choose(g,'ok')
        root=g.state.discovery_summon_history[-1]
        self.assertEqual((root.spec.cause.source.card_id,root.offers[0].basis.source.card_id,root.offers[1].basis.source.card_id),('d_caller','d_caller','green'))
        self.pick(g,'d_caller');self.portable(g)

    def test_nested_discovery_has_disjoint_parent_and_child_identities(self):
        g=self.game(('d_single',),('source','d_nested_watcher'));self.play(g,'d_single');self.pick(g);self.portable(g)
        self.assertEqual(len(g.state.discovery_summon_history),2);self.pick(g)
        roots=g.state.discovery_summon_history;self.assertTrue(all(r.status=='completed'for r in roots))
        self.assertFalse(set(roots[0].entry_root_ids)&set(roots[1].entry_root_ids));self.portable(g)

    def test_automatic_choice_keeps_real_choice_result_and_replay(self):
        g=self.game(('d_auto',),('source',));self.play(g,'d_auto')
        root=g.state.discovery_summon_history[-1]
        self.assertEqual(root.status,'completed');self.assertIsNotNone(root.offers[0].result)
        self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_true_retry_retires_discovery_and_keeps_monotonic_allocators(self):
        g=self.game(('d_retry',),('source',));self.play(g,'d_retry');self.pick(g);self.portable(g)
        old=g.state.discovery_summon_history[-1];old_children=old.entry_root_ids;self.choose(g,'retry');self.portable(g)
        self.assertEqual(len(g.state.discovery_summon_history),1);self.assertGreater(g.state.discovery_summon_history[-1].id,old.id)
        self.pick(g);self.assertGreater(min(g.state.discovery_summon_history[-1].entry_root_ids),max(old_children));self.portable(g)

    def test_terminal_closes_actual_prefix_without_later_offers(self):
        g=self.game(('d_each',),('source','fatal_watcher'));self.play(g,'d_each');self.pick(g)
        root=g.state.discovery_summon_history[-1]
        self.assertEqual((root.status,len(root.entry_root_ids),len(root.offers)),('interrupted',1,1))
        self.assertEqual(g.state.card_summon_history[-1].status,'interrupted');self.portable(g)

    def test_legacy_board_and_control_injection_reject_hand_discovery_still_works(self):
        for name,pattern in (('d_legacy','Unattributed summon'),('d_inject','inject discovery delivery control')):
            g=self.game((name,),('source',));s=g.snapshot()
            with self.assertRaisesRegex(Exception,pattern):self.play(g,name)
            self.assertEqual(g.snapshot(),s)
        g=self.game(('d_hand',),('source',));self.play(g,'d_hand');self.pick(g);self.portable(g)
        self.assertFalse(g.state.discovery_summon_history);self.assertFalse(g.state.card_summon_history)

    def test_original_offer_basis_rng_choice_and_delivery_tail_reject_edits(self):
        g=self.game(('d_all',),('source','pool_watcher'));self.play(g,'d_all');s=self.portable(g)
        for name in ('weight','offered','rng','choice-id','cause'):
            with self.subTest(name=name):
                bad=deepcopy(s);root=bad['state']['discovery_summon_history'][0];offer=root['offers'][0]
                if name=='weight':offer['basis']['candidates'][0]['weight']+=1
                elif name=='offered':offer['offered'].reverse()
                elif name=='rng':offer['rng_after'][1][2]^=1
                elif name=='choice-id':offer['choice']['id']+=1
                else:root['spec']['cause']['cast_id']=999999
                self.reject(bad,name)
        self.pick(g);self.pick(g);s=self.portable(g)
        for name in ('child-index','crop-roots','crop-next','crop-finish'):
            with self.subTest(name=name):
                bad=deepcopy(s);root=bad['state']['discovery_summon_history'][0]
                if name=='child-index':bad['state']['card_summon_history'][0]['request']['producer_link']['index']=1
                elif name=='crop-roots':root['entry_root_ids']=[]
                else:
                    tail=bad['resolution_frame']['fields']['continuation']['tuple']
                    kind='StartDiscoverySummonEntry'if name=='crop-next'else 'FinishDiscoverySummon'
                    index=next(i for i,w in enumerate(tail)if w.get('type','').endswith('.'+kind));tail.pop(index)
                self.reject(bad,name)

    def test_queued_attributed_discovery_uses_original_cause_and_query_scope(self):
        g=self.game(('d_waiting',),('source',));self.play(g,'d_waiting');s=self.portable(g)
        for name in ('cast_id','source_id'):
            bad=deepcopy(s);spec=bad['resolution_frame']['fields']['options']['tuple'][0]['fields']['effects']['tuple'][0]['fields']
            if name=='cast_id':spec['cause']['fields']['cast_id']=999999
            else:spec['source_id']=999999
            self.reject(bad,'queued-'+name)
        self.choose(g,'ok');self.pick(g);self.portable(g)

    def test_zero_offer_count_remains_invalid_and_rolls_back_without_sampling(self):
        g=self.game(('d_zero_count',),('source',));before=g.snapshot()
        with self.assertRaisesRegex(Exception,'generation count must be an integer >= 1'):self.play(g,'d_zero_count')
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_recipient_choice_and_quantity_qualification_have_distinct_players(self):
        for own,enemy,total in ((('source',),(),2),((),('source',),1)):
            with self.subTest(total=total):
                g=self.game(('d_enemy',),own,enemy=enemy);self.play(g,'d_enemy');self.portable(g)
                self.assertEqual(g.state.pending_choice.player_id,2)
                self.assertEqual(g.observe(1)['pending_choice'],{'player_id':2})
                self.assertIn('options',g.observe(2)['pending_choice'])
                self.pick(g);child=g.state.card_summon_history[-1]
                self.assertEqual((child.request.cause.player_id,child.request.player_id,child.plan.total),(1,2,total));self.portable(g)

    def test_closed_receipts_and_cross_family_parent_links_remain_bound(self):
        g=self.game(('d_mixed',),('source',));self.play(g,'d_mixed');self.portable(g);self.pick(g);s=self.portable(g)
        self.assertEqual((g.state.pool_summon_history[0].id,g.state.discovery_summon_history[0].id),(1,1))
        bad=deepcopy(s);link=bad['state']['card_summon_history'][-1]['request']['producer_link']
        link['batch_id']=link.pop('producer_id');self.reject(bad,'borrow-other-family-parent')
        bad=deepcopy(s);event=next(e for e in bad['events']if e['kind']=='discovery_summon_bound')
        event['kind']='unregistered-private-marker';self.reject(bad,'remove-original-private-choice-binding')
