"""Reload's real payment, original quote pairs and repeated discovery obligations."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.reload_card import CARD,load_batch,register_reload_card
from hs_sim.cards.holy_soldier_cards import MARCH,register_holy_soldier_cards
from hs_sim.engine import (CardDefinition,CardType,Game,PlayCard,PlayerSetup,Scenario,
    SelectChoice,SnapshotError,TriggerSpec)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_generated_quote_fact
from hs_sim.engine.discovery import ContinuePoolDiscovery
from hs_sim.engine.discovery_discounts import ACCEPTED,FINISHED,validate_boundary
from hs_sim.engine.effects import (AddCostModifier,ChoiceOption,GainArmor,InvokeBehavior,RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardClass,CardMetadata,ChoicePurpose,CostSpec,Rarity,SpellRepeatSpec)
from hs_sim.engine.pools import (DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from tools.card_batch import canonical,check_face

P='fixture.reload.'
A,B,HIGH,ZERO,ONE,PAL,FILL,HERO,HERO_P,OTHER,NEUTRAL,MINION,AUTO,COUNTER,REPEAT,WATCH,UNKNOWN=(P+x for x in
    ('three','five','ten','zero','one','paladin_six','fill','hero','hero_paladin','other','neutral',
     'minion','auto','counter','repeat','watch','unknown'))
TARGET='reload-fixture-v1'
QUERY=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current',include_neutral=False)


@lru_cache(maxsize=None)
def fixture(pool='sequence',mode=None,role='writer'):
    assert role in ('writer','reader')
    r=build_registry();register_reload_card(r);register_holy_soldier_cards(r)
    for cid,cls in ((HERO,CardClass.MAGE),(HERO_P,CardClass.PALADIN)):
        r.register_card(CardDefinition(cid,cid,CardType.HERO,health=30,metadata=CardMetadata(False,(cls,),None)))
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,health=10))
    for cid,n,cls in ((A,3,CardClass.MAGE),(B,5,CardClass.MAGE),(HIGH,10,CardClass.MAGE),
            (ZERO,0,CardClass.MAGE),(ONE,1,CardClass.MAGE),(PAL,6,CardClass.PALADIN),
            (OTHER,3,CardClass.PRIEST),(NEUTRAL,3,CardClass.NEUTRAL),(MINION,3,CardClass.MAGE)):
        meta=CardMetadata(True,(cls,),Rarity.COMMON)
        if cid!=MINION:r.register_behavior(cid,lambda c:(GainArmor(c.player_id,1),))
        card=CardDefinition(cid,cid,CardType.MINION if cid==MINION else CardType.SPELL,cost=n,
            health=3 if cid==MINION else 0,on_play=None if cid==MINION else cid,metadata=meta)
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    def fail(c):raise ResolutionError('Reload deliberate failure')
    r.register_behavior(P+'fail',fail)
    for cid,body in ((AUTO,lambda c:(CastSpell(c.player_id,CARD,c.source_id,choices='player'),)),
            (COUNTER,lambda c:(SetSecret(3-c.player_id,'EX1_287'),))):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=12,
        spell_repeats=(SpellRepeatSpec(2,'any'),)))
    if mode:
        def watch(c):
            if mode=='discount':
                if len(c.state.card_discovery_history)!=1:return ()
                return (AddCostModifier(c.player_id,CostSpec(delta=-1),source_id=c.source_id,uses_remaining=1),)
            if mode=='selection_wait':
                if dict(c.event.data).get('purpose')!=ChoicePurpose.POOL_DISCOVERY.value:return ()
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return (RequestChoice(3-c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=12,
            triggers=(TriggerSpec('choice_selected' if mode=='selection_wait' else 'card_added_to_hand',WATCH),)))
    members={'sequence':(A,B),'expensive':(HIGH,),'exact':(A,B),'zero':(ZERO,A,B),
        'one':(ONE,),'empty':(),'filter':(A,OTHER,NEUTRAL,MINION),'march':(MARCH,PAL),
        'unknown':(A,UNKNOWN)}[pool]
    if pool=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,1,CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON)))
    r.register_pool(PoolDefinition('constructed.cards','reload-fixture-pool-v1',TARGET,'experimental',
        tuple(PoolMember(cid) for cid in members),complete=True))
    return r


class ReloadTests(unittest.TestCase):
    def game(self,pool='sequence',mode=None,*,hand=(CARD,),board=(),seat=1,mana=10):
        self.pool,self.mode,self.seat=pool,mode,seat
        own=PlayerSetup(HERO_P if pool=='march' else HERO,hand=hand,board=board+((WATCH,) if mode else ()),
            deck=(FILL,)*8,mana=mana,max_mana=max(10,mana),mana_cap=max(10,mana))
        other=PlayerSetup('HERO_01',deck=(FILL,)*8,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other) if seat==1 else (other,own),active_player=seat,seed=375,
            generation_context=GenerationContext(TARGET,'experimental')),fixture(pool,mode))
    def play(self,g,cid=CARD):
        eid=next(i for i in g.state.players[self.seat].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(self.seat,eid));return eid
    def choose(self,g,cid):
        q=g.state.pending_choice;key=next(o.id for o in q.options if o.card_id==cid)
        g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def settle_reactions(self,g):
        while g.state.pending_choice and g.state.pending_choice.purpose!=ChoicePurpose.POOL_DISCOVERY:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
    def steps(self,g):
        codec=FrameCodec(g.mechanics,g.registry)
        return [codec.decode(json.loads(dict(e.data)['batch'])).selections[-1].discount_step
            for e in g.events if e.kind==ACCEPTED]
    def created(self,g,cid):
        return [e for e in g.state.entities.values() if e.card_id==cid and e.origin_entity_id is None and
            e.id not in [p.source_id for p in g.state.play_history]]
    def hand(self,g):return [g.state.entities[i] for i in g.state.players[self.seat].hand]
    def price(self,g,cid):return g.quote_cost(next(e.id for e in self.hand(g) if e.card_id==cid)).amount
    def restore(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=fixture(self.pool,self.mode,'reader')
        for other in (g.clone(),Game.from_snapshot(s,r),replay(build_replay(g),r)):
            self.assertTrue(other.snapshot()==s,'Original discount quotes, selections and owed continuation must restore')
        return Game.from_snapshot(s,r)
    def reject(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error:Game.from_snapshot(s,fixture(self.pool,self.mode,'reader'))
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_complete_root_and_two_primary_faces_keep_actual_hunter_arcane_spell(self):
        d=load_batch();raw=d['cards'][0]['record'];self.assertEqual(canonical(raw),d['cards'][0]['record_sha256'])
        self.assertEqual(len(d['official_observations']),2)
        for o in d['official_observations']:check_face(raw,o['face'],o['locale'])
        card=fixture().card(CARD);self.assertEqual(card.cost,8);self.assertEqual(card.metadata.classes,(CardClass.HUNTER,))
        self.assertFalse(d['cn_calibrated'])

    def test_actual_eight_mana_payment_and_three_then_five_spend_exact_budget(self):
        g=self.game();self.play(g);self.assertEqual(g.state.players[1].mana,2)
        self.choose(g,A);self.assertEqual(self.price(g,A),0);self.choose(g,B)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.price(g,B),0)
        self.assertEqual([(s.budget,s.before.amount,s.after.amount,s.remaining) for s in self.steps(g)],[(8,3,0,5),(5,5,0,0)])
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(len(g.state.card_discovery_history),2)
        self.restore(g)

    def test_more_expensive_spell_consumes_whole_budget_and_keeps_ordinary_remaining_cost(self):
        g=self.game('expensive');self.play(g);self.choose(g,HIGH)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.price(g,HIGH),2)
        self.assertEqual(self.steps(g)[0].remaining,0)

    def test_one_cost_spells_produce_eight_independent_discoveries_and_no_extra_payments(self):
        g=self.game('one');self.play(g)
        for _ in range(8):self.choose(g,ONE)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(self.hand(g)),8)
        self.assertEqual([s.budget for s in self.steps(g)],list(range(8,0,-1)))
        self.assertEqual(g.state.players[1].mana,2);self.assertEqual(len({e.id for e in self.hand(g)}),8)

    def test_zero_cost_choice_keeps_budget_and_is_not_pruned_or_forced_to_spend(self):
        g=self.game('zero');self.play(g);before=g.state.next_entity_id
        self.choose(g,ZERO);self.assertEqual(g.state.next_entity_id,before+1)
        self.assertEqual((self.steps(g)[0].budget,self.steps(g)[0].remaining),(8,8))
        self.assertIn(ZERO,[o.card_id for o in g.state.pending_choice.options]);self.choose(g,A);self.choose(g,B)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.card_discovery_history),3)

    def test_current_class_spell_domain_excludes_other_class_neutral_and_minions(self):
        g=self.game('filter');self.play(g)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],[A])
        self.choose(g,A);self.choose(g,A);self.choose(g,A)
        self.assertEqual([s.budget for s in self.steps(g)],[8,5,2]);self.assertEqual(self.price(g,A),0)

    def test_empty_domain_does_not_sample_allocate_or_leave_a_choice(self):
        g=self.game('empty');rng=g._rng.getstate();before=g.state.next_entity_id;self.play(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(g.state.next_entity_id,before);self.assertFalse(self.steps(g))
        self.assertEqual([dict(e.data)['reason'] for e in g.events if e.kind==FINISHED],['empty'])
        self.restore(g)

    def test_unknown_eligible_spell_errors_without_pruning_or_consuming_rng(self):
        g=self.game('unknown');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'unknown'):self.play(g)
        self.assertTrue(g.snapshot()==before)

    def test_full_hand_burn_still_commits_selected_quote_and_owed_remaining_budget(self):
        g=self.game(hand=(CARD,)+(FILL,)*9);self.play(g);self.choose(g,A);self.choose(g,B)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(self.hand(g)),10)
        self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),1)
        self.assertEqual([s.remaining for s in self.steps(g)],[5,0])

    def test_generated_quote_pair_is_pure_and_does_not_consume_external_one_use_modifier(self):
        g=self.game(mode='discount');self.play(g);self.choose(g,A);self.choose(g,B)
        self.assertEqual([s.remaining for s in self.steps(g)],[5,1]);self.choose(g,A)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.players[1].cost_modifiers),1)
        self.assertEqual(g.state.players[1].cost_modifiers[0].uses_remaining,1)
        step=self.steps(g)[1];self.assertEqual((step.before.amount,step.after.amount),(4,0))
        self.assertEqual(step.before.quote_input.base_cost,5)
        self.assertEqual(self.steps(g)[-1].after.amount,1)

    def test_real_remaining_mana_spell_uses_captured_generation_numbers_and_ordinary_delivery(self):
        g=self.game('march',mana=12);self.play(g);self.choose(g,MARCH)
        step=self.steps(g)[0];self.assertEqual((step.before.quote_input.mana_numbers,step.before.amount,step.remaining),(4,4,4))
        self.assertEqual(self.price(g,MARCH),0);self.choose(g,PAL);self.assertEqual(self.price(g,PAL),2)
        self.assertIsNone(g.state.pending_choice);self.restore(g)

    def test_hypothetical_native_quote_is_pure_and_unregistered_spell_cannot_borrow_mana_basis(self):
        g=self.game('march',mana=12);before=g.snapshot();fact=capture_generated_quote_fact(g.state,g.registry,1,MARCH)
        self.assertEqual(fact.amount,12);self.assertEqual(fact.quote_input.mana_numbers,12);self.assertTrue(g.snapshot()==before)
        with self.assertRaises(ValueError):replace(fact.quote_input,card_id=PAL,base_cost=6,mana_numbers=12)

    def test_actual_repeated_hand_cast_has_two_independent_initial_budgets_one_payment(self):
        g=self.game('expensive',board=(REPEAT,));self.play(g);self.choose(g,HIGH);self.choose(g,HIGH)
        self.assertIsNone(g.state.pending_choice);self.assertEqual([s.budget for s in self.steps(g)],[8,8])
        self.assertEqual(len([c for c in g.state.cast_history if c.card_id==CARD]),2)
        self.assertEqual((len(g.state.play_history),g.state.players[1].mana),(1,2))

    def test_effect_cast_runs_same_discovery_budget_without_hand_payment(self):
        g=self.game(hand=(AUTO,));self.play(g,AUTO);self.choose(g,A);self.choose(g,B)
        self.assertEqual(g.state.players[1].mana,10)
        self.assertEqual([c.origin for c in g.state.cast_history if c.card_id==CARD],['effect'])

    def test_countered_source_pays_but_never_offers_or_accepts_discount_quotes(self):
        g=self.game(hand=(COUNTER,CARD));self.play(g,COUNTER);rng=g._rng.getstate();self.play(g)
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(g.state.players[1].mana,2)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(self.steps(g));self.assertEqual(g._rng.getstate(),rng)

    def test_first_second_and_acquisition_waits_restore_original_discount_and_continue_once(self):
        g=self.game(mode='wait');self.play(g);g=self.restore(g);self.choose(g,A)
        self.assertEqual(g.state.pending_choice.player_id,2);g=self.restore(g);self.settle_reactions(g)
        g=self.restore(g);self.choose(g,B);g=self.restore(g);self.settle_reactions(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.card_discovery_history),2)

    def test_failed_selection_rolls_back_to_original_offer_and_failed_reaction_choice_preserves_delivery(self):
        g=self.game(mode='fail');self.play(g);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):self.choose(g,A)
        self.assertTrue(g.snapshot()==before)
        g=self.game(mode='wait');self.play(g);self.choose(g,A);before=g.snapshot();q=g.state.pending_choice
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):g.apply(SelectChoice(q.player_id,q.id,('fail',)))
        self.assertTrue(g.snapshot()==before);self.assertEqual(len(self.steps(g)),1)

    def test_choice_selection_reaction_wait_precedes_one_actual_quote_acceptance(self):
        g=self.game(mode='selection_wait');self.play(g);self.choose(g,A)
        self.assertEqual(len(self.steps(g)),0);g=self.restore(g);self.settle_reactions(g)
        self.assertEqual(len(self.steps(g)),1);self.choose(g,B)
        self.assertEqual(len(self.steps(g)),1);g=self.restore(g);self.settle_reactions(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(self.steps(g)),2)

    def test_second_seat_keeps_owner_and_private_quote_budget_and_original_offer_hidden(self):
        g=self.game(mode='wait',seat=2);self.play(g);self.choose(g,A)
        self.assertEqual(self.steps(g)[0].before.quote_input.player_id,2)
        for pid in (1,2):
            text=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for key in (ACCEPTED,FINISHED,'discount_step','mana_numbers','before_budget','resolution_frame','rng_state'):
                self.assertNotIn(key,text)

    def test_accepted_quote_witness_cannot_be_dropped_or_changed_after_rehash(self):
        for pool,cid in (('sequence',A),('expensive',HIGH)):
            g=self.game(pool);self.play(g);self.choose(g,cid);s=g.snapshot()
            for change in ('kind','budget','all'):
                bad=deepcopy(s);e=next(e for e in bad['events'] if e['kind']==ACCEPTED)
                if change=='kind':e['kind']='unused_event'
                elif change=='all':
                    for item in bad['events']:
                        if item['kind'] in (ACCEPTED,FINISHED):item['kind']='unused_event'
                else:
                    data=dict(e['data']);data['after_budget']+=1;e['data']=list(data.items())
                self.reject(bad)

    def test_owed_acquisition_continuation_cannot_be_clipped_or_duplicated(self):
        g=self.game(mode='wait');self.play(g);self.choose(g,A)
        work=next(w for w in (*g._frame.prefix,*g._frame.continuation) if type(w) is ContinuePoolDiscovery)
        for duplicate in (False,True):
            clone=g.clone();frame=clone._frame
            if duplicate:clone._frame=replace(frame,continuation=(*frame.continuation,work))
            else:clone._frame=replace(frame,prefix=tuple(w for w in frame.prefix if type(w) is not ContinuePoolDiscovery),
                continuation=tuple(w for w in frame.continuation if type(w) is not ContinuePoolDiscovery))
            with self.assertRaises(ValueError):validate_boundary(clone)

    def test_only_source_bound_plain_current_class_spell_discount_discoveries_can_repeat(self):
        valid=dict(player_id=1,pool_id='constructed.cards',query=QUERY,source_id=1,cost=CostSpec(delta=-8),excess_discount=True)
        DiscoverFromPool(**valid)
        for change in ({'source_id':None},{'cost':None},{'cost':CostSpec(set_to=0)},
                {'discoveries':2},{'replacement':False},{'count':2},{'destination':'deck'},
                {'query':PoolQuery(kinds=(CardType.MINION,),collectible=True)},
                {'excess_discount':1}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):DiscoverFromPool(**dict(valid,**change))
