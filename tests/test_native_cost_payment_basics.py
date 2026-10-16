"""Printed payment currency uses the existing quote, accounts and lifecycle."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, CostSpec,
    DiscoverFromPool, Game, GenerationContext, IllegalAction, Keyword, PaymentType, PlayCard,
    PlayerSetup, PoolCard, PoolDefinition, PoolMember, PoolQuery, Registry, ResolutionError,
    Resource, Scenario, SelectChoice, SnapshotError, SpellSchool, TargetSpec, TriggerSpec,
    UseHeroPower, Zone)
from hs_sim.engine.costs import capture_generated_quote_fact, capture_cost_input, quote_input, quote_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Draw, GainArmor, GrantKeyword,
    ModifyCost, RefreshMana, RemoveEnchantment, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.intrinsic_costs import validate_generated_quote_fact
from hs_sim.engine.model import SpellCostFacts
from hs_sim.engine.repeat_matching import validate_cost_quote_fact, validate_spell_cost_facts
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1]
PIN='e1fec77979d6bed86a09d160184f1bb76f4b9bceaea6202824be2a86623ed4ab'
HEALTH='TIME_612';CORPSES='TLC_436';STOCK='RLK_042';CROC='CS2_120'
CONTEXT=GenerationContext('native-cost-payment-foundation','experimental')


def evidence():
    p=json.loads((ROOT/'data/support/native-cost-payment-basics.json').read_bytes())
    if canonical_digest(p)!=PIN:raise ValueError('Native payment full raw changed')
    return p


def native_payment(raw):
    if 'CARD_ALTERNATE_COST' not in raw['tags']:return PaymentType.MANA
    value=raw['tags']['CARD_ALTERNATE_COST']
    if type(value) is not int or value not in (1,3):raise ValueError('Unknown printed payment tag')
    return {1:PaymentType.HEALTH,3:PaymentType.CORPSES}[value]


def registry(corpse_payment=PaymentType.CORPSES):
    r=Registry('native-cost-payment-independent-v1');raw={x['id']:x for x in evidence()['records']}
    r.register_card(CardDefinition('np.hero','Diagnostic Death Knight',CardType.HERO,health=30,
        metadata=CardMetadata(False,(CardClass.DEATH_KNIGHT,),None)))
    x=raw[CROC];r.register_card(CardDefinition(CROC,x['name'],CardType.MINION,
        cost=x['cost'],attack=x['attack'],health=x['health'],metadata=metadata_from_record(x)))
    x=raw[CORPSES];r.register_card(CardDefinition(CORPSES,x['name'],CardType.MINION,
        cost=x['cost'],attack=x['attack'],health=x['health'],keywords=(Keyword.RUSH,Keyword.LIFESTEAL),
        metadata=replace(metadata_from_record(x),tribes=('beast','undead')),cost_payment=corpse_payment))
    r.register_behavior('np.horn',lambda c:(RefreshMana(c.player_id,2),))
    x=raw[STOCK];horn=CardDefinition(STOCK,x['name'],CardType.SPELL,
        cost=x['tags'].get('COST',0),on_play='np.horn',spell_school=SpellSchool.FROST,metadata=metadata_from_record(x))
    r.register_card(horn);r.register_pool_card(PoolCard.from_definition(horn))
    r.register_pool(PoolDefinition('np.discovery','restricted-one-spell-v1',CONTEXT.target_id,CONTEXT.mode,(PoolMember(STOCK),)))
    r.register_behavior('np.discover',lambda c:(DiscoverFromPool(c.player_id,'np.discovery',
        PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current',exclude_source=True),source_id=c.source_id),))
    x=raw[HEALTH];r.register_card(CardDefinition(HEALTH,x['name'],CardType.SPELL,
        cost=x['cost'],cost_payment=native_payment(x),spell_school=SpellSchool.SHADOW,
        metadata=metadata_from_record(x),on_play='np.discover'))
    r.register_behavior('np.power.body',lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition('np.power','Diagnostic corpse power',CardType.HERO_POWER,
        cost=3,cost_payment=PaymentType.CORPSES,on_use='np.power.body'))
    def first(c):return CardReference.capture(c.state.entities[next(i for i in c.state.players[c.player_id].hand
        if c.state.entities[i].card_id==CORPSES)])
    hand_target=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,))
    bodies={
        'create':lambda c:(AddToHand(c.player_id,CORPSES,c.source_id),),
        'deck':lambda c:(AddToDeck(c.player_id,CORPSES,'top',c.source_id),),
        'draw':lambda c:(Draw(c.player_id),),
        'copy':lambda c:(CopyCard(first(c),c.player_id,source_id=c.source_id),),
        'basecopy':lambda c:(CopyCard(first(c),c.player_id,mode='base',source_id=c.source_id),),
        'override':lambda c:(ModifyCost(c.target_id,CostSpec(set_to=0,payment=PaymentType.MANA),c.source_id),),
        'reduce':lambda c:(ModifyCost(c.target_id,CostSpec(delta=-2),c.source_id),),
        'free':lambda c:(ModifyCost(c.target_id,CostSpec(set_to=0),c.source_id),),
        'remove':lambda c:(RemoveEnchantment(c.target_id,c.state.entities[c.target_id].enchantments[0].id),),
        'silence':lambda c:(Silence(c.target_id),),'bounce':lambda c:(ReturnToHand(c.target_id),),
        'transform':lambda c:(Transform(c.target_id,CROC),),
        'hurt':lambda c:(Damage(c.state.players[c.player_id].hero_id,5),),
        'low':lambda c:(Damage(c.state.players[c.player_id].hero_id,27),),
        'protect':lambda c:(GrantKeyword(c.state.players[c.player_id].hero_id,Keyword.IMMUNE),
            GrantKeyword(c.state.players[c.player_id].hero_id,Keyword.DIVINE_SHIELD)),
        'waitcreate':lambda c:(RequestChoice(c.player_id,(ChoiceOption('create','Create',
            (AddToHand(c.player_id,CORPSES,c.source_id),)),),c.source_id),),
    }
    for key,fn in bodies.items():
        r.register_behavior('np.script.'+key,fn)
        kw={'targeting':hand_target} if key in ('override','reduce','free','remove') else {'requires_target':True} if key in ('silence','bounce','transform') else {}
        r.register_card(CardDefinition('np.'+key,key+' diagnostic',CardType.SPELL,on_play='np.script.'+key,**kw))
    r.register_behavior('np.wait.body',lambda c:(RequestChoice(c.player_id,(ChoiceOption('continue','Continue',()),),c.source_id),))
    r.register_card(CardDefinition('np.wait','Payment observer',CardType.MINION,health=3,
        triggers=(TriggerSpec('health_spent','np.wait.body'),)))
    def fail(c):raise ResolutionError('Deliberate native payment rollback')
    r.register_behavior('np.fail.body',fail)
    r.register_card(CardDefinition('np.fail','Failure observer',CardType.MINION,health=3,
        triggers=(TriggerSpec('corpses_spent','np.fail.body'),TriggerSpec('health_spent','np.fail.body'))))
    def inspect(c):
        e=c.state.entities[c.event.target_id]
        if e.card_id!=CORPSES:return ()
        q=quote_cost(c.state,r,e)
        return (GainArmor(c.player_id,q.amount if q.payment==PaymentType.CORPSES else 100),)
    r.register_behavior('np.inspect.body',inspect)
    r.register_card(CardDefinition('np.inspect','Creation observer',CardType.MINION,health=3,
        triggers=(TriggerSpec('card_created','np.inspect.body'),TriggerSpec('card_added_to_hand','np.inspect.body'))))
    return r


class NativeCostPaymentTests(unittest.TestCase):
    def game(self,hand=(CORPSES,),board=(),enemy_board=(),corpses=5,mana=0,armor=0,power=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('np.hero',hand=hand,board=board,deck=(CROC,)*5,corpses=corpses,max_mana=10,mana=mana,armor=armor,hero_power_card_id=power),
            PlayerSetup('np.hero',board=enemy_board,deck=(CROC,)*5)),seed=118,generation_context=CONTEXT),registry())
    def card(self,g,cid=CORPSES):return next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
    def play(self,g,cid=CORPSES,target=None):
        eid=self.card(g,cid);g.apply(PlayCard(1,eid,target));return eid
    def choose(self,g,option=None):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(q.options[0].id if option is None else option,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        for other in (Game.from_snapshot(s,registry()),g.clone(),replay(build_replay(g),registry())):self.assertEqual(other.snapshot(),s)
        return s
    def quote(self,g,eid):
        q=g.quote_cost(eid);return q.amount,q.payment

    def test_full_raw_has_two_constructed_sources_and_keeps_noncollectible_power(self):
        p=evidence();self.assertEqual(len(p['records']),5);self.assertEqual(set(p['all_local_alternate_cost_sources']),{'JAIL_446hp',HEALTH,CORPSES})
        self.assertEqual(p['unadapted_noncollectible_source'],['JAIL_446hp']);self.assertFalse(p['all_alternate_sources_implemented'])
        self.assertFalse(p['formal_pool_verified']);self.assertFalse(p['CN_calibrated'])
        for value in (99,None,True):
            with self.assertRaises(ValueError):native_payment({'tags':{'CARD_ALTERNATE_COST':value}})

    def test_corpse_minion_is_playable_with_zero_mana_and_pays_once(self):
        g=self.game();eid=self.card(g);self.assertEqual(self.quote(g,eid),(5,PaymentType.CORPSES))
        self.assertTrue(any(isinstance(a,PlayCard) and a.entity_id==eid for a in g.legal_actions()));self.play(g)
        self.assertEqual((g.state.players[1].mana,g.state.players[1].resources[Resource.CORPSES]),(0,0))
        self.assertEqual([(e.amount,e.source_id) for e in g.events if e.kind=='corpses_spent'],[(5,eid)])
        self.assertEqual(g.state.play_history[-1].payment,PaymentType.CORPSES);self.portable(g)

    def test_corpse_balance_cannot_be_replaced_by_available_mana(self):
        g=self.game(corpses=4,mana=10);s=g.snapshot()
        with self.assertRaisesRegex(IllegalAction,'corpses'):self.play(g)
        self.assertEqual(g.snapshot(),s)

    def test_native_corpse_payment_registers_actual_units_in_existing_history(self):
        g=self.game();eid=self.play(g);rows=g.state.corpse_spend_history
        self.assertEqual(len(rows),1);self.assertEqual((rows[0].amount,rows[0].source_id),(5,eid));self.portable(g)

    def test_reanimated_pterrordax_retains_real_rush_and_lifesteal_body(self):
        g=self.game(hand=('np.hurt',CORPSES),enemy_board=(CROC,));self.play(g,'np.hurt');eid=self.play(g)
        enemy=g.state.players[2].board[0]
        with self.assertRaises(IllegalAction):g.apply(Attack(1,eid,g.state.players[2].hero_id))
        g.apply(Attack(1,eid,enemy));self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,29)
        self.assertEqual(g.state.entities[eid].health,1);self.portable(g)

    def test_blood_draw_pays_health_before_actual_spell_discovery(self):
        g=self.game(hand=(HEALTH,));eid=self.card(g,HEALTH);self.assertEqual(self.quote(g,eid),(3,PaymentType.HEALTH));self.play(g,HEALTH)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27);self.assertEqual(g.state.players[1].mana,0)
        self.assertEqual([(e.amount,e.source_id) for e in g.events if e.kind=='health_spent'],[(3,eid)])
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],[STOCK]);self.portable(g)
        self.choose(g);self.assertEqual(self.quote(g,self.card(g,STOCK)),(0,PaymentType.MANA))
        self.play(g,STOCK);self.assertEqual(g.state.players[1].mana,2);self.portable(g)

    def test_native_health_payment_preserves_existing_armor_shield_and_immunity_policy(self):
        g=self.game(hand=('np.protect',HEALTH),armor=2);self.play(g,'np.protect');start=len(g.events);self.play(g,HEALTH)
        hero=g.state.entities[g.state.players[1].hero_id];self.assertEqual((hero.health,hero.armor),(29,0))
        self.assertIn(Keyword.DIVINE_SHIELD,hero.keywords);self.assertIn(Keyword.IMMUNE,hero.keywords)
        self.assertFalse(any(e.kind=='damage' for e in g.events[start:]));self.choose(g);self.portable(g)

    def test_native_health_cannot_pay_last_effective_health(self):
        g=self.game(hand=('np.low',HEALTH));self.play(g,'np.low');s=g.snapshot()
        with self.assertRaisesRegex(IllegalAction,'health'):self.play(g,HEALTH)
        self.assertEqual(g.snapshot(),s)

    def test_creation_observers_see_native_currency_without_a_removable_attachment(self):
        g=self.game(hand=('np.create',),board=('np.inspect',));self.play(g,'np.create');eid=self.card(g)
        self.assertEqual(self.quote(g,eid),(5,PaymentType.CORPSES));self.assertEqual(g.state.entities[eid].enchantments,[])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,10);self.portable(g)

    def test_native_currency_is_available_on_direct_deck_creation_and_draw(self):
        g=self.game(hand=('np.deck','np.draw'));self.play(g,'np.deck');eid=g.state.players[1].deck[0]
        q=quote_cost(g.state,g.registry,g.state.entities[eid]);self.assertEqual((q.amount,q.payment),(5,PaymentType.CORPSES));self.play(g,'np.draw')
        self.assertEqual(self.card(g),eid);self.assertEqual(self.quote(g,eid),(5,PaymentType.CORPSES));self.portable(g)

    def test_numeric_cost_reduction_keeps_the_printed_account(self):
        g=self.game(hand=('np.reduce',CORPSES),corpses=3);eid=self.card(g);self.play(g,'np.reduce',eid)
        self.assertEqual(self.quote(g,eid),(3,PaymentType.CORPSES));self.play(g)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0);self.portable(g)

    def test_explicit_payment_override_removal_returns_to_printed_currency(self):
        g=self.game(hand=('np.override','np.remove',CORPSES));eid=self.card(g);self.play(g,'np.override',eid)
        self.assertEqual(self.quote(g,eid),(0,PaymentType.MANA));self.play(g,'np.remove',eid)
        self.assertEqual(self.quote(g,eid),(5,PaymentType.CORPSES));self.portable(g)

    def test_current_copy_keeps_override_and_base_copy_recovers_native_currency(self):
        g=self.game(hand=('np.override','np.copy','np.basecopy',CORPSES));eid=self.card(g);self.play(g,'np.override',eid)
        self.play(g,'np.copy');current=g.state.players[1].hand[-1];self.assertNotEqual(current,eid)
        self.assertEqual(self.quote(g,current),(0,PaymentType.MANA));self.play(g,'np.basecopy');base=g.state.players[1].hand[-1]
        self.assertEqual(self.quote(g,base),(5,PaymentType.CORPSES));self.assertEqual(g.state.entities[base].enchantments,[]);self.portable(g)

    def test_silence_and_return_keep_native_currency_and_clear_removable_cost(self):
        g=self.game(hand=('np.override',CORPSES,'np.silence','np.bounce'));eid=self.card(g);self.play(g,'np.override',eid)
        self.play(g);self.play(g,'np.silence',eid)
        q=quote_cost(g.state,g.registry,g.state.entities[eid]);self.assertEqual((q.amount,q.payment),(5,PaymentType.CORPSES));self.play(g,'np.bounce',eid)
        self.assertEqual(g.state.entities[eid].zone,Zone.HAND);self.assertEqual(self.quote(g,eid),(5,PaymentType.CORPSES));self.portable(g)

    def test_transform_uses_the_new_printed_face_payment(self):
        g=self.game(hand=(CORPSES,'np.transform'));eid=self.play(g);self.play(g,'np.transform',eid)
        q=quote_cost(g.state,g.registry,g.state.entities[eid]);self.assertEqual((q.amount,q.payment),(2,PaymentType.MANA));self.portable(g)

    def test_zero_native_corpse_cost_does_not_consume_printed_five_units(self):
        g=self.game(hand=('np.free',CORPSES),corpses=0);eid=self.card(g);self.play(g,'np.free',eid);self.play(g)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0)
        self.assertEqual([e.amount for e in g.events if e.kind=='corpses_spent'],[0]);self.portable(g)

    def test_generated_and_physical_quotes_share_native_base_and_local_override(self):
        g=self.game();eid=self.card(g);fact=capture_generated_quote_fact(g.state,g.registry,1,CORPSES)
        self.assertEqual((fact.amount,fact.payment),self.quote(g,eid));validate_generated_quote_fact(g.registry,fact)
        modified=capture_generated_quote_fact(g.state,g.registry,1,CORPSES,cost=CostSpec(set_to=2,payment=PaymentType.MANA))
        self.assertEqual((modified.amount,modified.payment),(2,PaymentType.MANA));validate_generated_quote_fact(g.registry,modified)

    def test_frozen_physical_and_generated_facts_reject_a_forged_base_account(self):
        g=self.game();value=capture_cost_input(g.state.entities[self.card(g)]);fact=quote_input(g.state,g.registry,value)
        validate_cost_quote_fact(g.registry,fact)
        with self.assertRaises(ValueError):validate_cost_quote_fact(g.registry,replace(fact,local_payment=PaymentType.MANA,payment=PaymentType.MANA))
        generated=capture_generated_quote_fact(g.state,g.registry,1,CORPSES)
        with self.assertRaises(ValueError):validate_generated_quote_fact(g.registry,replace(generated,local_payment=PaymentType.MANA,payment=PaymentType.MANA))

    def test_actual_health_spell_receipt_validates_the_native_local_cost_facts(self):
        g=self.game(hand=(HEALTH,));self.play(g,HEALTH);q=g.state.play_history[-1].submitted_cost.quote
        facts=SpellCostFacts(3,q.quote_input,q.local_amount,q.local_payment,q.intrinsic)
        validate_spell_cost_facts(g.registry,facts)
        with self.assertRaises(ValueError):validate_spell_cost_facts(g.registry,replace(facts,local_payment=PaymentType.MANA))

    def test_payment_observer_waiting_restores_original_native_receipt_and_pays_once(self):
        g=self.game(hand=(HEALTH,),board=('np.wait',));self.play(g,HEALTH);saved=self.portable(g)
        self.choose(g);self.assertEqual(g.state.pending_choice.options[0].card_id,STOCK);self.choose(g)
        other=Game.from_snapshot(saved,registry());self.choose(other);self.choose(other);self.assertEqual(other.snapshot(),g.snapshot())
        self.assertEqual(len([e for e in g.events if e.kind=='health_spent']),1);self.portable(g)

    def test_waiting_creation_branch_restores_printed_currency_through_registry(self):
        g=self.game(hand=('np.waitcreate',));self.play(g,'np.waitcreate');self.portable(g);self.choose(g)
        self.assertEqual(self.quote(g,self.card(g)),(5,PaymentType.CORPSES));self.portable(g)

    def test_failed_payment_observers_roll_back_both_existing_accounts_and_receipts(self):
        for cid in (HEALTH,CORPSES):
            g=self.game(hand=(cid,),board=('np.fail',));s=g.snapshot()
            with self.assertRaisesRegex(ResolutionError,'native payment rollback'):self.play(g,cid)
            self.assertEqual(g.snapshot(),s)

    def test_native_power_uses_the_same_quote_and_corpse_account(self):
        g=self.game(hand=(),corpses=3,power='np.power');eid=g.state.players[1].hero_power_id
        self.assertEqual(self.quote(g,eid),(3,PaymentType.CORPSES));g.apply(UseHeroPower(1,eid))
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0);self.assertEqual(g.state.players[1].mana,0);self.portable(g)

    def test_player_view_shows_own_actual_currency_and_hides_opponent_price(self):
        a=self.game();b=self.game(hand=(CROC,));own=a.for_player(1).observe()['observation']['players'][0]['hand'][0]
        self.assertEqual(own['cost'],{'amount':5,'payment':'corpses'})
        self.assertEqual(a.for_player(2).observe(),b.for_player(2).observe());self.assertEqual(a.for_player(2).events(),b.for_player(2).events())
        for seat in (1,2):
            wire=json.dumps((a.for_player(seat).observe(),a.for_player(seat).legal_actions(),a.for_player(seat).events()))
            for private in ('cost_payment','CostQuoteFact','submitted_cost','resolution_frame'):self.assertNotIn(private,wire)

    def test_native_payment_is_pinned_and_old_schemas_are_rejected(self):
        g=self.game();s=g.snapshot();self.assertEqual(s['schema_version'],SNAPSHOT_SCHEMA_VERSION)
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry(PaymentType.MANA))
        s['schema_version']=229
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_strict_declaration_rejects_unknown_currency_and_nonpayable_carriers(self):
        for payment in ('health',None,True,1):
            with self.assertRaises(ValueError):Registry('invalid-native-currency').register_card(CardDefinition('bad','bad',CardType.SPELL,cost_payment=payment))
        for kwargs in ({'kind':CardType.HERO,'health':30},{'kind':CardType.SPELL,'choice_only':True},
                {'kind':CardType.HERO_POWER,'passive_hero_power':True}):
            with self.assertRaises(ValueError):Registry('invalid-native-currency').register_card(CardDefinition('bad','bad',cost_payment=PaymentType.HEALTH,**kwargs))

