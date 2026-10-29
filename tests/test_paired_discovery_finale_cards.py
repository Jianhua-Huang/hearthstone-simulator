"""Two real discovery spells, original paired recipients and actual spent returns."""
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import paired_discovery_finale_cards as native
from hs_sim.engine import EndTurn,Game,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.discovery_delivery import original_recipient
from hs_sim.engine.effects import AddToHand,ChoiceOption,Draw,GainArmor,GainTemporaryMana,InvokeBehavior,RandomDamage,RequestChoice
from hs_sim.engine.model import CardClass,CardDefinition,CardType,CostSpec,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spent_spells import ReturnSpentSpell
from hs_sim.engine.zones import CardReference,ModifyStoredCost,MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format

PAIR,FINALE=native.LEAVES;P='k648.'
A,B,HIGH,OTHER,WATCH,FILL,RESCUE,AUTO,FAIL=(P+x for x in('one','three','five','rogue','watch','fill','rescue','auto','fail'))
CONTEXT=GenerationContext('k648-paired-discovery-fixture','experimental')


def prompt(c):
    return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
        RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),
        source_id=c.source_id,prompt='Original K648 reaction')


@lru_cache(maxsize=None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_paired_discovery_finale_cards(r)
    for cid,cost,hero in((A,1,CardClass.MAGE),(B,3,CardClass.MAGE),(HIGH,5,CardClass.MAGE),(OTHER,1,CardClass.ROGUE)):
        r.register_behavior(cid,lambda c:(GainArmor(c.player_id,1),));card=CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,metadata=metadata(hero))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    members=(A,)if mode=='single'else(HIGH,OTHER)if mode=='empty'else(A,B,HIGH,OTHER)
    r.register_pool(PoolDefinition('constructed.cards','k648-pool',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    def fail(c):raise ValueError('K648 deliberate failure')
    r.register_behavior(FAIL,fail)
    def rescue(c):
        target=next(e for e in c.state.entities.values()if e.card_id==FINALE and e.zone==Zone.GRAVEYARD)
        return (ReturnSpentSpell(SourceAllocationFact.capture(c.state,target),c.player_id),)
    for cid,body in((FILL,lambda c:tuple(AddToHand(c.player_id,A,c.source_id)for _ in range(10))),
            (RESCUE,rescue),(AUTO,lambda c:(CastSpell(c.player_id,FINALE,c.source_id),))):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata()))
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id)
        if e.kind=='mana_spent'and mode=='refund'and source is not None and source.card_id==FINALE:
            return (GainTemporaryMana(c.player_id,1),)
        if e.kind=='card_discovered'and source is not None and source.card_id==PAIR:
            fact=original_recipient(c.state,e)
            prior=[x for x in c.state.card_discovery_history if x.result.choice.source_id==source.id]
            if len(prior)==1 and fact is not None and fact.zone==Zone.HAND:
                ref=CardReference.capture(c.state.entities[fact.entity_id])
                if mode=='discount_first':return (ModifyStoredCost(ref,CostSpec(delta=-1),c.source_id),)
                if mode=='cycle_first':return (MoveCard(ref,c.player_id,Zone.DECK,position='top',source_id=c.source_id),Draw(c.player_id,1,c.source_id))
                if mode=='transform_first':return (TransformStoredCard(ref,HIGH,c.source_id),)
                if mode=='first_wait':return (prompt(c),)
        if e.kind=='cost_modified'and mode in('cost_wait','cost_fail')and source is not None and source.card_id==PAIR:
            return (prompt(c),)if mode=='cost_wait'else(InvokeBehavior(FAIL,c.source_id,c.player_id),)
        if e.kind=='card_returned'and source is not None and source.card_id==FINALE and mode=='return_wait':return (prompt(c),)
        return ()
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=metadata(tribes=()),
        triggers=tuple(TriggerSpec(e,WATCH)for e in('card_discovered','cost_modified','card_returned','mana_spent'))))
    return r


@lru_cache(maxsize=1)
def host():return build_cn37_local_pool_format()


def wires(value,name):
    result=[]
    if isinstance(value,dict):
        if value.get('type','').endswith('.'+name):result.append(value)
        for v in value.values():result.extend(wires(v,name))
    elif isinstance(value,list):
        for v in value:result.extend(wires(v,name))
    return result


class PairedDiscoveryFinaleTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)

    def game(self,*,mode='normal',hand=(PAIR,),mana=10,watch=False):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=(WATCH,)if watch else(),deck=(HIGH,)*6,mana=mana,max_mana=max(2,mana)),
            PlayerSetup('mage.hero',deck=(HIGH,)*6,mana=10,max_mana=10)),seed=648,generation_context=CONTEXT),registry(mode))

    def select(self,g,cid):
        q=g.state.pending_choice;option=next(o for o in q.options if o.card_id==cid);self.choose(g,option.id)

    def amount(self,g,eid):return quote_cost(g.state,g.registry,g.state.entities[eid]).amount

    def returns(self,g):return [e for p in g.state.players.values()for e in p.player_effects if e.spec_id==native.RETURN_ID]

    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')});return s

    def test_complete_two_roots_four_primary_faces_and_three_evidence_enchantments(self):
        d=native.load_batch();self.assertEqual([v['record']['id']for v in d['cards']],[PAIR,FINALE])
        self.assertEqual(len(d['official_observations']),4);self.assertEqual(len(d['evidence_only']),3)
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['new_standard_roots'])

    def test_first_delivered_before_second_menu_and_costs_swapped_on_actual_recipients(self):
        g=self.game();source=self.play(g,PAIR);self.select(g,A);first=self.entity(g,A).id
        self.assertEqual(self.amount(g,first),1);self.assertIsNotNone(g.state.pending_choice);self.select(g,B);second=self.entity(g,B).id
        self.assertEqual((self.amount(g,first),self.amount(g,second)),(3,1));self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual(len(g.state.card_discovery_history),2);self.assertTrue(all(v.result.choice.source_id==source for v in g.state.card_discovery_history));self.portable(g)

    def test_current_first_local_discount_is_frozen_before_swapping(self):
        g=self.game(mode='discount_first',watch=True);self.play(g,PAIR);self.select(g,A);first=self.entity(g,A).id
        self.assertEqual(self.amount(g,first),0);self.select(g,B);self.assertEqual((self.amount(g,first),self.amount(g,self.entity(g,B).id)),(3,0))

    def test_continuous_first_hand_transformation_uses_current_physical_quote(self):
        g=self.game(mode='transform_first',watch=True);self.play(g,PAIR);self.select(g,A);first=self.entity(g,HIGH).id
        self.assertEqual(self.amount(g,first),5);self.select(g,B);self.assertEqual((self.amount(g,first),self.amount(g,self.entity(g,B).id)),(3,5));self.portable(g)

    def test_reacquired_same_physical_card_is_not_borrowed_as_original_first_recipient(self):
        g=self.game(mode='cycle_first',watch=True);self.play(g,PAIR);self.select(g,A);first=self.entity(g,A).id
        self.select(g,B);self.assertEqual(self.amount(g,first),1);self.assertEqual(self.amount(g,self.entity(g,B).id),1);self.portable(g)

    def test_duplicate_selected_face_produces_two_distinct_original_cards(self):
        g=self.game(mode='single');self.play(g,PAIR);self.select(g,A);self.select(g,A)
        ids=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==A];self.assertEqual(len(ids),2);self.assertNotEqual(*ids)
        self.assertEqual([self.amount(g,i)for i in ids],[1,1])

    def test_empty_low_cost_domain_does_not_create_false_choices_or_fatigue(self):
        g=self.game(mode='empty');before=g._rng.getstate();self.play(g,PAIR)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.card_discovery_history);self.assertFalse(g.state.draw_history);self.assertEqual(g._rng.getstate(),before)

    def test_full_hand_second_burn_keeps_original_selected_pair_and_first_cost(self):
        g=self.game(hand=(PAIR,)+(A,)*9);self.play(g,PAIR);self.select(g,A);first=max(g.state.players[1].hand)
        self.select(g,B);self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(self.amount(g,first),3)
        self.assertTrue(any(e.card_id==B and e.zone==Zone.GRAVEYARD for e in g.state.entities.values()));self.portable(g)

    def test_each_menu_and_first_completion_wait_restores_original_pair_and_replays(self):
        g=self.game(mode='first_wait',watch=True);self.play(g,PAIR);g=self.portable(g);self.select(g,A)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g);g=self.portable(g);self.select(g,B)
        self.assertEqual((self.amount(g,self.entity(g,A).id),self.amount(g,self.entity(g,B).id)),(3,1));self.portable(g)

    def test_second_swap_notification_wait_has_original_quotes_and_complete_new_delivery(self):
        g=self.game(mode='cost_wait',watch=True);self.play(g,PAIR);self.select(g,A);self.select(g,B)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g)
        self.assertEqual((self.amount(g,self.entity(g,A).id),self.amount(g,self.entity(g,B).id)),(3,1));self.portable(g)

    def test_second_selection_failure_rolls_back_both_costs_creation_receipts_and_rng(self):
        g=self.game(mode='cost_fail',watch=True);self.play(g,PAIR);self.select(g,A);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g,B)
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.amount(g,self.entity(g,A).id),1)

    def test_rehashed_pending_swap_cannot_borrow_first_entry_or_quote(self):
        g=self.game(mode='cost_wait',watch=True);self.play(g,PAIR);self.select(g,A);self.select(g,B)
        for field,value in(('first_entry_id',1),('first_quote',None)):
            saved=json.loads(json.dumps(g.snapshot()));changed=0
            for event in saved['events']:
                for key in('work','receipt'):
                    wire=event['data'].get(key)
                    if type(wire)is not str or 'DeliverCostSwappedSpell'not in wire:continue
                    value_tree=json.loads(wire);nodes=wires(value_tree,'DeliverCostSwappedSpell')
                    for node in nodes:node['fields'][field]=value;changed+=1
                    event['data'][key]=json.dumps(value_tree)
            self.assertTrue(changed)
            with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry('cost_wait','independent-reader'))

    def test_finale_discovers_reduced_card_then_returns_same_original_spell_at_end(self):
        g=self.game(hand=(FINALE,),mana=2);source=self.play(g,FINALE)
        self.assertEqual(len(self.returns(g)),1);self.select(g,B)
        self.assertEqual(self.amount(g,self.entity(g,B).id),2);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[source].zone,Zone.HAND);self.assertEqual(self.amount(g,source),2);self.portable(g)

    def test_non_finale_only_discovers_and_discounts_without_returning_source(self):
        g=self.game(hand=(FINALE,),mana=3);source=self.play(g,FINALE);self.select(g,A)
        self.assertEqual(self.amount(g,self.entity(g,A).id),0);self.assertFalse(self.returns(g))
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)

    def test_accepted_finale_survives_later_payment_reaction_refund(self):
        g=self.game(mode='refund',hand=(FINALE,),mana=2,watch=True);source=self.play(g,FINALE)
        self.assertEqual(g.state.players[1].mana,1);self.select(g,A);g.apply(EndTurn(1));self.assertEqual(g.state.entities[source].zone,Zone.HAND)

    def test_original_return_full_hand_uses_shared_burn_instead_of_a_new_copy(self):
        g=self.game(hand=(FINALE,FILL),mana=2);source=self.play(g,FINALE);self.select(g,B);self.play(g,FILL)
        self.assertEqual(len(g.state.players[1].hand),10);g.apply(EndTurn(1));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertFalse(any(e.card_id==FINALE and e.id!=source for e in g.state.entities.values()));self.assertFalse(self.returns(g));self.portable(g)

    def test_earlier_actual_return_cancels_original_residence_without_retaking_hand_card(self):
        g=self.game(hand=(FINALE,RESCUE),mana=2);source=self.play(g,FINALE);self.select(g,B);self.play(g,RESCUE)
        self.assertEqual(g.state.entities[source].zone,Zone.HAND);entry=g.state.entities[source].hand_entry_id
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[source].hand_entry_id,entry);self.portable(g)

    def test_finale_menu_wait_and_end_return_notification_wait_restore_and_replay(self):
        g=self.game(mode='return_wait',hand=(FINALE,),mana=2,watch=True);source=self.play(g,FINALE);g=self.portable(g);self.select(g,B)
        g=self.portable(g);g.apply(EndTurn(1));self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g)
        self.assertEqual(g.state.entities[source].zone,Zone.HAND);self.portable(g)

    def test_return_notification_choice_failure_restores_original_end_boundary(self):
        g=self.game(mode='return_wait',hand=(FINALE,),mana=2,watch=True);self.play(g,FINALE);self.select(g,A);g.apply(EndTurn(1));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g)

    def test_rehashed_player_return_cannot_borrow_source_or_future_creation_or_drop_captured_allocation(self):
        g=self.game(hand=(FINALE,),mana=2);source=self.play(g,FINALE);self.select(g,A)
        self.assertEqual(self.returns(g)[0].source_id,source)
        for key,value in(('source_id',10**8),('created_turn',g.state.turn+1),('source_allocation',None)):
            saved=json.loads(json.dumps(g.snapshot()));saved['state']['players']['1']['player_effects'][0][key]=value
            with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry('normal','independent-reader'))

    def test_automatic_source_keeps_existing_non_finale_condition_policy(self):
        g=self.game(hand=(AUTO,),mana=0);self.play(g,AUTO)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.card_discovery_history),1)
        event=next(e for e in g.events if e.kind=='card_discovered');fact=original_recipient(g.state,event)
        self.assertIsNotNone(fact);self.assertEqual(fact.zone,Zone.HAND)
        self.assertFalse(self.returns(g))
        self.assertFalse(any(e.kind=='player_effect_added'and dict(e.data).get('effect_key')==native.RETURN_ID for e in g.events))
        self.assertEqual(self.amount(g,fact.entity_id),max(0,g.registry.card(fact.card_id).cost-1))

    def test_player_views_hide_pair_quotes_pending_source_and_private_end_receipts(self):
        for cid in(PAIR,FINALE):
            g=self.game(hand=(cid,),mana=2);self.play(g,cid)
            if cid==PAIR:self.select(g,A)
            for pid in(1,2):
                view=json.dumps(g.for_player(pid).observe())
                for value in('source_allocation','source_player_id','DeliverCostSwappedSpell','first_quote','second_quote','resolution_frame','rng_state'):
                    self.assertNotIn(value,view)

    def test_real_standard_host_both_new_discovery_sources_execute_ordinary_choices(self):
        f=host()
        for cid in(PAIR,FINALE):
            g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(cid,),mana=2,max_mana=2,deck=('CORE_CS2_182',)*4),
                PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*4)),seed=648,generation_context=f.context),f.registry)
            source=self.play(g,cid)
            while g.state.pending_choice:self.choose(g,g.state.pending_choice.options[0].id)
            self.assertEqual(len(g.state.card_discovery_history),2 if cid==PAIR else 1)
            if cid==FINALE:g.apply(EndTurn(1));self.assertEqual(g.state.entities[source].zone,Zone.HAND)


if __name__=='__main__':unittest.main()
