"""Original deck spells, captured local prices and ordinary random transforms."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import lunacy_card as native
from hs_sim.engine import Game,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.costs import local_cost,quote_cost
from hs_sim.engine.effects import ChoiceOption,Draw,GainArmor,InvokeBehavior,RandomDamage,RequestChoice
from hs_sim.engine.model import CardClass,CardDefinition,CardType,CostSpec,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spent_spells import ReturnSpentSpell
from hs_sim.engine.stored_pool_transforms import DRAW as TRANSFORM_DRAW,TransformStoredFromPool,candidates
from hs_sim.engine.zones import AddToDeck,CardReference,ModifyStoredCost,MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format

CARD=native.CARD;P='k651.'
A,B,Z,SEVEN,NINE,TWELVE,T3,T4,T4B,T5,T10,WATCH,DISCOUNT,DRAW,FAIL,UNKNOWN=(P+s for s in
    ('one','two','zero','seven','nine','twelve','spell3','spell4','other4','spell5','spell10','watch','discount','draw','fail','unknown'))
CTX=GenerationContext('k651-original-deck-spells','experimental')


def prompt(c):
    return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
        RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),
        source_id=c.source_id,prompt='Original Lunacy transformation reaction')


@lru_cache(maxsize=None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_lunacy_card(r)
    for cid,cost,hero in ((A,1,CardClass.MAGE),(B,2,CardClass.MAGE),(Z,0,CardClass.MAGE),(SEVEN,7,CardClass.MAGE),
            (NINE,9,CardClass.MAGE),(TWELVE,12,CardClass.MAGE),(T3,3,CardClass.WARLOCK),
            (T4,4,CardClass.SHAMAN),(T4B,4,CardClass.WARRIOR),(T5,5,CardClass.PRIEST),(T10,10,CardClass.DRUID)):
        r.register_behavior(cid,lambda c:(GainArmor(c.player_id,1),));card=CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,metadata=metadata(hero))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    members=(PoolMember(T3),PoolMember(T4,2),PoolMember(T4B,5),PoolMember(T5),PoolMember(T10))
    if mode=='empty':members=(PoolMember(T10),)
    if mode=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,5,metadata(CardClass.MAGE)));members=(*members,PoolMember(UNKNOWN))
    r.register_pool(PoolDefinition('constructed.cards','k651-native-tier-domain',CTX.target_id,CTX.mode,members,complete=True))
    def fail(c):raise ValueError('K651 deliberate failure')
    r.register_behavior(FAIL,fail)
    def discount(c):
        return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(delta=-1),c.source_id)
            for i in c.state.players[c.player_id].deck if c.state.entities[i].kind==CardType.SPELL)
    for cid,body in ((DISCOUNT,discount),(DRAW,lambda c:(Draw(c.player_id,1,c.source_id),))):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata()))
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=CARD:return ()
        if mode=='wait':return (prompt(c),)
        if mode=='fail':return (InvokeBehavior(FAIL,c.source_id,c.player_id),)
        if mode=='add':return (AddToDeck(c.player_id,A,position='bottom',source_id=c.source_id),)
        if mode=='return_source'and source.zone==Zone.GRAVEYARD:
            return (ReturnSpentSpell(SourceAllocationFact.capture(c.state,source),c.player_id),)
        later=next((c.state.entities[i]for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id==B),None)
        if later is not None:
            ref=CardReference.capture(later)
            if mode=='discount_later':return (ModifyStoredCost(ref,CostSpec(set_to=0),c.source_id),)
            if mode=='cycle_later':return (MoveCard(ref,c.player_id,Zone.HAND,source_id=c.source_id),
                MoveCard(replace(ref,zone=Zone.HAND,zone_epoch=ref.zone_epoch+1),c.player_id,Zone.DECK,position='bottom',source_id=c.source_id))
        return ()
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=metadata(),
        triggers=(TriggerSpec('stored_card_transformed',WATCH),)))
    return r


@lru_cache(maxsize=1)
def host():return build_cn37_local_pool_format()


class LunacyTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)

    def game(self,*,mode='normal',hand=(CARD,),deck=(A,B,'card.1'),watch=False,actor=1):
        self.mode=mode
        own=PlayerSetup('mage.hero',hand=hand,deck=deck,board=(WATCH,)if watch else(),mana=30,max_mana=30,mana_cap=30)
        other=PlayerSetup('mage.hero',deck=('card.40',)*8,mana=30,max_mana=30,mana_cap=30)
        return Game.from_scenario(Scenario((own,other)if actor==1 else(other,own),active_player=actor,seed=651,generation_context=CTX),registry(mode))

    def draws(self,g):return [e for e in g.events if e.kind==TRANSFORM_DRAW]
    def cost(self,g,eid):return local_cost(g.state.entities[eid])[0]

    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')});return s

    def test_complete_legendary_spell_enchant_evidence_and_two_primary_faces(self):
        data=native.load_batch();self.assertEqual((registry().card(CARD).cost,registry().card(CARD).kind),(2,CardType.SPELL))
        self.assertEqual(len(data['official_observations']),2);self.assertEqual(data['evidence_only'][0]['record']['id'],CARD+'e')
        self.assertFalse(data['new_standard_roots']or data['formal_pool_complete']or data['cn_calibrated'])

    def test_transforms_original_own_deck_spells_in_place_and_keeps_hand_and_minion(self):
        g=self.game(hand=(CARD,A));old=tuple(g.state.players[1].deck);held=self.entity(g,A).id;source=self.play(g,CARD)
        self.assertEqual(tuple(g.state.players[1].deck),old);self.assertIn(g.state.entities[old[0]].card_id,(T4,T4B))
        self.assertEqual(g.state.entities[old[1]].card_id,T5);self.assertEqual(g.state.entities[old[2]].card_id,'card.1')
        self.assertEqual(g.state.entities[held].card_id,A);self.assertEqual([self.cost(g,i)for i in old[:2]],[1,2])
        self.assertEqual(g.state.players[1].mana,28);self.assertTrue(all(e.source_id==source for e in self.draws(g)));self.portable(g)

    def test_discounted_current_deck_prices_determine_both_tier_and_retained_value(self):
        g=self.game(hand=(CARD,DISCOUNT));old=tuple(g.state.players[1].deck);self.play(g,DISCOUNT);self.play(g,CARD)
        self.assertEqual(g.state.entities[old[0]].card_id,T3);self.assertIn(g.state.entities[old[1]].card_id,(T4,T4B))
        self.assertEqual([self.cost(g,i)for i in old[:2]],[0,1])

    def test_high_costs_map_to_ten_but_keep_each_original_local_cost(self):
        g=self.game(deck=(SEVEN,NINE,TWELVE));old=tuple(g.state.players[1].deck);self.play(g,CARD)
        self.assertEqual([g.state.entities[i].card_id for i in old],[T10]*3);self.assertEqual([self.cost(g,i)for i in old],[7,9,12])

    def test_zero_cost_uses_three_tier_without_creating_mana_cost(self):
        g=self.game(deck=(Z,));old=g.state.players[1].deck[0];self.play(g,CARD)
        self.assertEqual((g.state.entities[old].card_id,self.cost(g,old)),(T3,0))

    def test_full_ordered_tier_candidates_and_original_integer_weights_are_preserved(self):
        g=self.game(deck=(A,));self.play(g,CARD);draw=dict(self.draws(g)[0].data)['draw']
        from hs_sim.engine.continuations import FrameCodec
        receipt=FrameCodec(g.mechanics,g.registry).decode(draw)
        self.assertEqual(receipt.candidates,((T4B,5),(T4,2))if T4B<T4 else((T4,2),(T4B,5)))
        self.assertEqual(receipt.request.retained_cost,1)

    def test_duplicate_original_faces_keep_independent_physical_targets(self):
        g=self.game(deck=(A,A));old=tuple(g.state.players[1].deck);before=g.state.next_entity_id;self.play(g,CARD)
        self.assertEqual(tuple(g.state.players[1].deck),old);self.assertNotEqual(*old);self.assertEqual(g.state.next_entity_id,before)
        self.assertEqual([e.target_id for e in self.draws(g)],list(old))

    def test_no_original_spell_is_noop_without_rng(self):
        g=self.game(deck=('card.1',));before=g._rng.getstate();self.play(g,CARD)
        self.assertFalse(self.draws(g));self.assertEqual(g._rng.getstate(),before)

    def test_actually_empty_tier_keeps_original_and_does_not_consume_rng(self):
        g=self.game(mode='empty',deck=(A,));old=g.state.players[1].deck[0];before=g._rng.getstate();self.play(g,CARD)
        self.assertEqual(g.state.entities[old].card_id,A);self.assertEqual(g._rng.getstate(),before)
        self.assertEqual(len(self.draws(g)),1)

    def test_unknown_later_eligible_member_is_not_pruned_and_rolls_back_whole_action(self):
        g=self.game(mode='unknown');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CARD)
        self.assertEqual(g.snapshot(),before)

    def test_drawn_transformed_card_preserves_retained_cost_in_real_hand_quote(self):
        g=self.game(hand=(CARD,DRAW));old=g.state.players[1].deck[0];self.play(g,CARD);self.play(g,DRAW)
        self.assertEqual(g.state.entities[old].zone,Zone.HAND);self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[old]).amount,1);self.portable(g)

    def test_later_inserted_spells_do_not_join_original_transform_inventory(self):
        g=self.game(mode='add',watch=True);self.play(g,CARD)
        self.assertEqual(len(self.draws(g)),2);self.assertEqual(sum(g.state.entities[i].card_id==A for i in g.state.players[1].deck),2)

    def test_later_price_change_does_not_reprice_frozen_original_request(self):
        g=self.game(mode='discount_later',watch=True);old=g.state.players[1].deck[1];self.play(g,CARD)
        self.assertEqual((g.state.entities[old].card_id,self.cost(g,old)),(T5,2));self.portable(g)

    def test_departed_then_reentered_target_does_not_borrow_old_residence(self):
        g=self.game(mode='cycle_later',watch=True);old=g.state.players[1].deck[1];self.play(g,CARD)
        self.assertEqual(g.state.entities[old].card_id,B);self.assertEqual(len(self.draws(g)),1);self.portable(g)

    def test_original_source_return_does_not_cancel_remaining_accepted_requests(self):
        g=self.game(mode='return_source',watch=True);source=self.play(g,CARD)
        self.assertEqual(g.state.entities[source].zone,Zone.HAND);self.assertEqual(len(self.draws(g)),2);self.portable(g)

    def test_each_transformation_wait_restores_original_remaining_targets_and_prices(self):
        g=self.game(mode='wait',watch=True);self.play(g,CARD);self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g);self.assertEqual(len(self.draws(g)),2);self.portable(g)

    def test_reaction_fault_rolls_back_payment_original_entities_and_rng(self):
        g=self.game(mode='fail',watch=True);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CARD)
        self.assertEqual(g.snapshot(),before)

    def test_wait_choice_failure_preserves_original_wait_and_rng(self):
        g=self.game(mode='wait',watch=True);self.play(g,CARD);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before)

    def test_new_deck_retention_rejects_missing_tier_and_original_minion(self):
        g=self.game();source=self.entity(g,CARD).id;ref=CardReference.capture(g.state.entities[g.state.players[1].deck[-1]])
        with self.assertRaises(ValueError):TransformStoredFromPool(ref,'constructed.cards',PoolQuery(kinds=(CardType.SPELL,),collectible=True),source,retained_cost=1)
        request=TransformStoredFromPool(ref,'constructed.cards',PoolQuery(kinds=(CardType.SPELL,),collectible=True,min_cost=4,max_cost=4),source,retained_cost=1)
        with self.assertRaises(ResolutionError):candidates(g.registry,g.state,CTX,request,None,CARD)

    def test_rehashed_private_draw_cannot_replace_the_original_cost_tier(self):
        g=self.game();self.play(g,CARD);saved=json.loads(json.dumps(g.snapshot()));changed=0
        def edit(value):
            nonlocal changed
            if isinstance(value,dict):
                if value.get('type','').endswith('.PoolQuery')and value['fields'].get('min_cost')==4:
                    value['fields']['min_cost']=5;value['fields']['max_cost']=5;changed+=1
                for v in value.values():edit(v)
            elif isinstance(value,list):
                for v in value:edit(v)
        edit(saved);self.assertTrue(changed)
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry('normal','reader'))

    def test_second_player_only_transforms_its_own_physical_deck(self):
        g=self.game(actor=2);old=tuple(g.state.players[2].deck);self.play(g,CARD,player=2)
        self.assertEqual(tuple(g.state.players[2].deck),old);self.assertTrue(all(e.player_id==2 for e in self.draws(g)))

    def test_opponent_information_hides_deck_results_complete_weights_and_rng(self):
        g=self.game();self.play(g,CARD);view=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        for key in (T4,T4B,T5,'StoredPoolTransformDraw','retained_cost','rng_before','rng_state'):self.assertNotIn(key,view)

    def test_real_standard_host_transforms_original_spells_and_keeps_their_prices(self):
        f=host();g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(CARD,),deck=('AV_283','AV_290','CORE_CS2_182'),mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*8)),seed=651,generation_context=f.context),f.registry)
        old=tuple(g.state.players[1].deck);self.play(g,CARD);self.assertEqual(tuple(g.state.players[1].deck),old)
        self.assertEqual([self.cost(g,i)for i in old[:2]],[9,10]);self.assertTrue(all(g.registry.card(g.state.entities[i].card_id).cost==10 for i in old[:2]))
        self.assertEqual(g.state.entities[old[2]].card_id,'CORE_CS2_182')


if __name__=='__main__':unittest.main()
