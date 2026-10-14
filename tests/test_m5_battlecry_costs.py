"""Card ability conditions and payer-related cost auras; provisional R-118."""
import json
import unittest
from copy import deepcopy
from dataclasses import replace
import test_m5_battlecries as foundation
from hs_sim.engine import (Game, Scenario, PlayerSetup, Registry, CardDefinition, CardType,
    CardAbilityCondition, CostSpec, CostAuraSpec, CostScope, PaymentType, EndTurn, PlayCard,
    UseHeroPower, UseHandAction, HandActionSpec, CardClass, CardMetadata, Rarity, GenerationContext,
    ChooseBranch, ChooseOneSpec, Keyword, Zone, IllegalAction, ResolutionError, SnapshotError,
    MakeDormant, AwakenMinion, DestroyLocation, RewindSpec, SelectChoice, PoolCard, PoolDefinition, PoolMember,
    PoolOfferGroup, ChooseFromPools, GrantCounterPolicy, CounterPolicySpec, matches_ability,
    CardReference, CopyCard, MoveCard, UpgradeHandCard, BuffStoredCard, RandomBuffStoredMinion,
    PoolQuery, CreateTemporaryCard)
from hs_sim.engine.effects import (GainArmor, Damage, Destroy, Silence, Transform, ChangeControl,
    CopyMinion, ReturnToHand, ShuffleIntoDeck, Summon, GrantCostAura, AddCostModifier,
    ModifyCost, AddToHand, RequestChoice, ChoiceOption, InvokeBehavior, EquipWeapon)
from hs_sim.engine.costs import quote_generated_cost, quote_cost
from hs_sim.engine.sacrifice import MinionReference

CTX=GenerationContext('local-2026-09-23','experimental')


class BattlecryCostTests(unittest.TestCase):
    card=foundation.BattlecryTests.card
    script=foundation.BattlecryTests.script
    watch=foundation.BattlecryTests.watch
    play=foundation.BattlecryTests.play
    choose=foundation.BattlecryTests.choose
    pause=foundation.BattlecryTests.pause
    armor=foundation.BattlecryTests.armor
    check=foundation.BattlecryTests.check
    reject=foundation.BattlecryTests.reject
    nested=foundation.BattlecryTests.nested

    def setUp(self):
        self.r=Registry('battlecry-cost-tests-v1')
        self.r.register_card(CardDefinition('hero','hero',CardType.HERO,health=30))
        self.r.register_card(CardDefinition('body','body',CardType.MINION,health=5))
        self.r.register_behavior('armor',lambda c:[GainArmor(c.player_id,2)])
        self.r.register_card(CardDefinition('power','power',CardType.HERO_POWER,on_use='armor'))
        self.r.register_card(CardDefinition('cry','cry',CardType.MINION,cost=2,health=4,battlecry='armor',
            metadata=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON)))
        self.r.register_card(CardDefinition('plain','plain',CardType.MINION,cost=2,health=4,
            metadata=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON)))
        self.r.register_card(CardDefinition('generic','generic',CardType.MINION,cost=2,health=4,on_play='armor'))
        self.script('spell',lambda c:[GainArmor(c.player_id,9)])
        self.aura('web')

    def spec(self,**kw):
        values=dict(delta=2,card_types=(CardType.MINION,),ability=CardAbilityCondition())
        values.update(kw);return CostSpec(**values)

    def aura(self,cid,relation='any',spec=None,kind=CardType.MINION,**kw):
        values=dict(cost=2)
        if kind==CardType.MINION:values['health']=4
        if kind==CardType.WEAPON:values.update(attack=1,durability=2)
        if kind==CardType.LOCATION:values.update(durability=2,on_use='armor')
        values.update(kw)
        self.r.register_card(CardDefinition(cid,cid,kind,cost_auras=(CostAuraSpec(spec or self.spec(),relation),),**values))

    def game(self,hand=('cry',),board=(),enemy=(),enemy_hand=('cry',),mana=10,**kw):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,deck=('body',)*5,
            max_mana=10,mana=mana,**kw),PlayerSetup('hero',hand=enemy_hand,board=enemy,deck=('body',)*5,
            max_mana=10,mana=10)),seed=78,generation_context=CTX),self.r)

    def hand_id(self,g,cid='cry',p=1):
        return next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)

    def quote(self,g,i):
        state=g.state
        return quote_cost(state,self.r,state.entities[i]).amount

    def cost(self,g,cid='cry',p=1):return self.quote(g,self.hand_id(g,cid,p))

    def test_both_players_pay_matching_increase(self):
        g=self.game(enemy=('web',));self.assertEqual((self.cost(g),self.cost(g,p=2)),(4,4))
        self.play(g);self.assertEqual((g.state.players[1].mana,self.armor(g)),(6,2))
        g.apply(EndTurn(1));g.apply(PlayCard(2,self.hand_id(g,p=2)))
        self.assertEqual((g.state.players[2].mana,self.armor(g,2)),(6,2));self.check(g)

    def test_friendly_relation_preserves_old_scope(self):
        self.aura('friend',relation='friendly');g=self.game(board=('friend',))
        self.assertEqual((self.cost(g),self.cost(g,p=2)),(4,2));self.check(g)

    def test_enemy_relation_follows_controller(self):
        self.aura('enemy',relation='enemy')
        self.script('take',lambda c:[ChangeControl(c.state.players[2].board[0],1)])
        g=self.game(hand=('take','cry'),enemy=('enemy',));self.assertEqual((self.cost(g),self.cost(g,p=2)),(4,2))
        self.play(g,'take');self.assertEqual((self.cost(g),self.cost(g,p=2)),(2,4));self.check(g)

    def test_opposing_sources_stack(self):
        g=self.game(board=('web',),enemy=('web',));self.assertEqual(self.cost(g),6)
        self.play(g);self.assertEqual(g.state.players[1].mana,4);self.check(g)

    def test_nonmatching_cards_and_aura_source_have_base_cost(self):
        g=self.game(hand=('plain','generic','spell','web','cry'),enemy=('web',))
        self.assertEqual([self.cost(g,c) for c in ('plain','generic','spell','web','cry')],[2,2,0,2,4]);self.check(g)

    def test_choose_one_is_not_battlecry(self):
        self.r.register_card(CardDefinition('choose','choose',CardType.MINION,cost=2,health=4,
            choose_one=ChooseOneSpec((ChooseBranch('a','A','armor'),ChooseBranch('b','B','armor')),ChooseBranch('both','Both','armor'))))
        g=self.game(hand=('choose',),enemy=('web',));self.assertEqual(self.cost(g,'choose'),2);self.play(g,'choose',branch='a');self.check(g)

    def test_explicit_negative_ability_filter(self):
        self.aura('negative',spec=self.spec(ability=CardAbilityCondition(present=False)))
        g=self.game(hand=('plain','cry'),enemy=('negative',));self.assertEqual((self.cost(g,'plain'),self.cost(g)),(4,2));self.check(g)

    def test_type_and_id_filters_intersect_ability(self):
        self.aura('named',spec=self.spec(card_ids=('cry',)))
        self.card('other');g=self.game(hand=('cry','other'),enemy=('named',))
        self.assertEqual((self.cost(g),self.cost(g,'other')),(4,2));self.check(g)

    def test_insufficient_mana_rejects_without_side_effects(self):
        g=self.game(enemy=('web',),mana=3);before=g.snapshot()
        self.assertFalse(any(isinstance(a,PlayCard) for a in g.legal_actions()))
        with self.assertRaises(IllegalAction):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_player_view_actions_and_payment_share_quote(self):
        g=self.game(enemy=('web',),mana=4);port=g.for_player(1);listing=port.legal_actions()
        self.assertEqual(listing['observation']['players'][0]['hand'][0]['cost']['amount'],4)
        self.assertEqual(g.quote_cost(self.hand_id(g)).amount,4)
        action=next(a for a in listing['actions'] if a['type']=='play_card')
        self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        self.assertEqual(g.state.players[1].mana,0);self.assertEqual(g.state.play_history[-1].cost,4);self.check(g)

    def test_source_leaving_during_commit_does_not_refund_payment(self):
        self.watch('remove','card_committed',lambda c:[Destroy(c.state.players[2].board[0])] if c.play.card_id=='cry' else [])
        g=self.game(board=('remove',),enemy=('web',));self.play(g)
        self.assertEqual(g.state.players[1].mana,6);self.check(g)

    def test_source_appearing_during_commit_does_not_reprice(self):
        self.watch('create','card_committed',lambda c:[Summon(2,'web')] if c.play.card_id=='cry' else [])
        g=self.game(board=('create',));self.play(g);self.assertEqual(g.state.players[1].mana,8);self.check(g)

    def test_own_aura_battlecry_does_not_tax_its_preentry_payment(self):
        self.aura('self',battlecry='armor');g=self.game(hand=('self','cry'));self.play(g,'self')
        self.assertEqual(g.state.players[1].mana,8);self.assertEqual(self.cost(g),4);self.check(g)

    def test_countered_minion_still_pays_aura_quote(self):
        self.script('arm',lambda c:[GrantCounterPolicy(MinionReference.capture(c.state.entities[c.state.players[2].board[0]]),CounterPolicySpec(CardType.MINION))])
        g=self.game(hand=('arm','cry'),enemy=('web',));self.play(g,'arm');self.play(g)
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(g.state.players[1].mana,6)
        self.assertEqual(self.armor(g),0);self.check(g)

    def mutation(self,effect):
        self.script('change',lambda c:[effect(c.state.players[2].board[0])])
        g=self.game(hand=('change','cry'),enemy=('web',));self.assertEqual(self.cost(g),4)
        self.play(g,'change');self.assertEqual(self.cost(g),2);self.check(g);return g

    def test_silence_removes_aura(self):self.mutation(Silence)
    def test_death_removes_aura(self):self.mutation(Destroy)
    def test_transform_removes_aura(self):self.mutation(lambda i:Transform(i,'plain'))
    def test_return_removes_aura(self):self.mutation(ReturnToHand)
    def test_shuffle_removes_aura(self):self.mutation(ShuffleIntoDeck)
    def test_dormancy_pauses_aura(self):self.mutation(lambda i:MakeDormant(i,None))

    def test_awaken_restores_aura(self):
        self.script('sleep',lambda c:[MakeDormant(c.state.players[2].board[0],None)])
        self.script('wake',lambda c:[AwakenMinion(c.state.players[2].board[0])])
        g=self.game(hand=('sleep','wake','cry'),enemy=('web',));self.play(g,'sleep');self.play(g,'wake')
        self.assertEqual(self.cost(g),4);self.check(g)

    def test_control_does_not_change_any_relation(self):
        self.script('take',lambda c:[ChangeControl(c.state.players[2].board[0],1)])
        g=self.game(hand=('take','cry'),enemy=('web',));self.play(g,'take')
        self.assertEqual((self.cost(g),self.cost(g,p=2)),(4,4));self.check(g)

    def test_current_copy_stacks_as_distinct_source(self):
        self.script('copy',lambda c:[CopyMinion(c.state.players[2].board[0],1)])
        g=self.game(hand=('copy','cry'),enemy=('web',));self.play(g,'copy')
        self.assertEqual((self.cost(g),self.cost(g,p=2)),(6,6));self.check(g)

    def test_granted_aura_expires_for_both_payers(self):
        self.script('grant',lambda c:[GrantCostAura(c.state.players[2].board[0],CostAuraSpec(self.spec(),'any'),c.source_id,c.state.turn)])
        g=self.game(hand=('grant','cry'),enemy=('body',));self.play(g,'grant')
        self.assertEqual(self.cost(g),4);g.apply(EndTurn(1));self.assertEqual(self.cost(g,p=2),2);self.check(g)

    def test_granted_aura_current_copy_keeps_and_base_copy_loses(self):
        self.script('grant',lambda c:[GrantCostAura(c.state.players[2].board[0],CostAuraSpec(self.spec(),'enemy'))])
        self.script('copy',lambda c:[CopyMinion(c.state.players[2].board[0],2),CopyMinion(c.state.players[2].board[0],2,mode='base')])
        g=self.game(hand=('grant','copy','cry'),enemy=('body',));self.play(g,'grant');self.play(g,'copy')
        self.assertEqual((self.cost(g),self.cost(g,p=2)),(6,2));self.check(g)

    def test_location_carrier_applies_and_stops_on_destruction(self):
        self.aura('location',kind=CardType.LOCATION)
        self.script('kill',lambda c:[DestroyLocation(c.state.players[2].board[0])])
        g=self.game(hand=('kill','cry'),enemy=('location',));self.assertEqual(self.cost(g),4)
        self.play(g,'kill');self.assertEqual(self.cost(g),2);self.check(g)

    def test_weapon_carrier_applies_to_enemy_and_stops(self):
        self.aura('weapon',kind=CardType.WEAPON)
        self.script('equip',lambda c:[EquipWeapon(2,'weapon')])
        self.script('kill',lambda c:[Destroy(c.state.players[2].weapon_id)])
        g=self.game(hand=('equip','kill','cry'));self.play(g,'equip');self.assertEqual(self.cost(g),4)
        self.play(g,'kill');self.assertEqual(self.cost(g),2);self.check(g)

    def test_ability_current_and_printed_differ_after_silence(self):
        self.script('silence',lambda c:[Silence(c.state.players[1].board[0])])
        g=self.game(hand=('silence',),board=('cry',),enemy=('web',));i=g.state.players[1].board[0]
        self.assertEqual(self.quote(g,i),4);self.play(g,'silence');entity=g.state.entities[i]
        self.assertEqual(self.quote(g,i),2)
        self.assertFalse(matches_ability(CardAbilityCondition(),self.r.card('cry'),entity))
        self.assertTrue(matches_ability(CardAbilityCondition(basis='printed'),self.r.card('cry'),entity));self.check(g)

    def test_printed_filter_survives_silenced_card_identity(self):
        self.aura('printed',spec=self.spec(ability=CardAbilityCondition(basis='printed')))
        self.script('silence',lambda c:[Silence(c.state.players[1].board[0])])
        g=self.game(hand=('silence',),board=('cry',),enemy=('printed',));i=g.state.players[1].board[0]
        self.play(g,'silence');self.assertEqual(self.quote(g,i),4);self.check(g)

    def test_dormant_card_still_has_structural_battlecry(self):
        self.script('sleep',lambda c:[MakeDormant(c.state.players[1].board[0],None)])
        g=self.game(hand=('sleep',),board=('cry',),enemy=('web',));i=g.state.players[1].board[0]
        self.play(g,'sleep');self.assertEqual(self.quote(g,i),4);self.check(g)

    def test_hand_upgrade_reprices_from_new_ability_identity(self):
        self.script('upgrade',lambda c:[UpgradeHandCard(CardReference.capture(c.state.entities[c.state.players[1].hand[0]]),'cry')])
        g=self.game(hand=('upgrade','plain'),enemy=('web',));self.assertEqual(self.cost(g,'plain'),2)
        self.play(g,'upgrade');self.assertEqual(self.cost(g),4);self.check(g)

    def test_finite_modifier_spends_only_matching_ability(self):
        self.script('grant',lambda c:[AddCostModifier(1,self.spec(delta=-1),uses_remaining=1)])
        g=self.game(hand=('grant','plain','cry'),enemy=('web',));self.play(g,'grant')
        self.assertEqual(self.cost(g),3);self.play(g,'plain');self.assertEqual(g.state.players[1].cost_modifiers[0].uses_remaining,1)
        self.play(g);self.assertFalse(g.state.players[1].cost_modifiers);self.assertEqual(g.state.players[1].mana,5);self.check(g)

    def test_local_modifier_checks_condition_once(self):
        self.script('modify',lambda c:[ModifyCost(c.state.players[1].hand[0],self.spec(delta=-1))])
        g=self.game(hand=('modify','cry'),enemy=('web',));self.play(g,'modify')
        self.assertEqual(self.cost(g),3);self.check(g)

    def test_local_modifier_skips_unmatched_card(self):
        self.script('modify',lambda c:[ModifyCost(c.state.players[1].hand[0],self.spec(delta=-1))])
        g=self.game(hand=('modify','plain'),enemy=('web',));self.play(g,'modify')
        self.assertEqual(self.cost(g,'plain'),2);self.assertFalse(g.state.entities[self.hand_id(g,'plain')].enchantments);self.check(g)

    def test_health_payment_and_cost_history_share_tax(self):
        self.script('health',lambda c:[AddCostModifier(1,self.spec(delta=0,payment=PaymentType.HEALTH),uses_remaining=1)])
        g=self.game(hand=('health','cry'),enemy=('web',));self.play(g,'health');self.play(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,26)
        self.assertEqual(g.state.players[1].mana,10);self.check(g)

    def test_local_set_then_aura_and_later_player_set_keep_order(self):
        self.script('set',lambda c:[ModifyCost(c.state.players[1].hand[-1],CostSpec(set_to=1)),
            AddCostModifier(1,self.spec(delta=0,set_to=0),uses_remaining=1)])
        g=self.game(hand=('set','cry'),enemy=('web',));self.play(g,'set');self.assertEqual(self.cost(g),0)
        self.play(g);self.assertEqual(g.state.players[1].mana,10);self.check(g)

    def test_hero_power_and_trade_fee_are_independent(self):
        self.r.register_card(CardDefinition('trade','trade',CardType.MINION,cost=2,health=4,battlecry='armor',
            hand_actions=(HandActionSpec('trade','trade',1),)))
        g=self.game(hand=('trade',),enemy=('web',),hero_power_card_id='power')
        self.assertEqual(self.cost(g,'trade'),4)
        g.apply(UseHandAction(1,self.hand_id(g,'trade'),'trade'));self.assertEqual(g.state.players[1].mana,9)
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.assertEqual(g.state.players[1].mana,9);self.check(g)

    def test_quote_generated_is_pure_and_matches_received_card(self):
        self.script('generate',lambda c:[AddToHand(1,'cry',cost=CostSpec(delta=-1))])
        g=self.game(hand=('generate',),enemy=('web',));before=g.snapshot()
        q=quote_generated_cost(g.state,self.r,1,'cry',cost=CostSpec(delta=-1))
        self.assertEqual(q.amount,3);self.assertEqual(g.snapshot(),before)
        self.play(g,'generate');self.assertEqual(self.cost(g),q.amount);self.check(g)

    def test_temporary_floor_after_relations_and_reductions(self):
        self.script('generate',lambda c:[AddCostModifier(1,self.spec(delta=-20)),
            CreateTemporaryCard(1,'cry',c.state.turn,minimum_cost=2)])
        g=self.game(hand=('generate',),enemy=('web',));self.play(g,'generate')
        self.assertEqual(self.cost(g),2);self.check(g)

    def pool(self):
        for cid in ('plain','cry'):self.r.register_pool_card(PoolCard.from_definition(self.r.card(cid)))
        self.r.register_pool(PoolDefinition('cost-pool','v1',CTX.target_id,CTX.mode,(PoolMember('plain'),PoolMember('cry'))))

    def test_affordable_pool_uses_enemy_aura_before_sampling(self):
        self.pool();self.script('offer',lambda c:[ChooseFromPools(1,(PoolOfferGroup('cost-pool',count=2),),affordable=True)])
        g=self.game(hand=('offer',),enemy=('web',),mana=3);self.play(g,'offer')
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],['plain']);self.check(g)

    def test_pool_preview_and_delivery_use_same_current_cost(self):
        self.pool();self.script('offer',lambda c:[ChooseFromPools(1,(PoolOfferGroup('cost-pool',count=2),))])
        g=self.game(hand=('offer',),enemy=('web',));self.play(g,'offer')
        options=g.state.pending_choice.options;chosen=next(o for o in options if o.card_id=='cry')
        self.assertEqual(chosen.preview.cost,4);self.check(g);self.choose(g,chosen.id)
        self.assertEqual(self.cost(g),4);self.check(g)

    def test_saved_offer_keeps_preview_but_later_cost_is_live(self):
        self.pool();self.script('offer',lambda c:[ChooseFromPools(1,(PoolOfferGroup('cost-pool',count=2),))])
        self.watch('remove','choice_selected',lambda c:[Destroy(c.state.players[2].board[0])])
        g=self.game(hand=('offer',),board=('remove',),enemy=('web',));self.play(g,'offer')
        chosen=next(o for o in g.state.pending_choice.options if o.card_id=='cry');self.assertEqual(chosen.preview.cost,4)
        saved=g.clone();self.choose(g,chosen.id);self.choose(saved,chosen.id)
        self.assertEqual(self.cost(g),2);self.assertEqual(g.snapshot(),saved.snapshot());self.check(g)

    def test_generated_cost_condition_mismatch_fails_before_creation(self):
        self.script('bad',lambda c:[AddToHand(1,'plain',cost=self.spec(delta=-1))])
        g=self.game(hand=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_stored_buff_uses_ability_condition(self):
        self.script('buff',lambda c:[BuffStoredCard(CardReference.capture(c.state.entities[c.state.players[1].hand[0]]),
            attack=1,cost=self.spec(delta=-1))])
        g=self.game(hand=('buff','cry'),enemy=('web',));self.play(g,'buff')
        self.assertEqual(self.cost(g),3);self.assertEqual(g.state.entities[self.hand_id(g)].attack,1);self.check(g)

    def test_random_stored_buff_rejects_mixed_ineligible_candidates_atomically(self):
        self.script('bad',lambda c:[RandomBuffStoredMinion(1,attack=1,cost=self.spec(delta=-1))])
        g=self.game(hand=('bad','plain','cry'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_enemy_hand_identity_does_not_leak_through_quotes(self):
        g=self.game(enemy=('web',),enemy_hand=('cry',));other=self.game(enemy=('web',),enemy_hand=('plain',))
        self.assertEqual(g.observe(1),other.observe(1));self.assertEqual(g.for_player(1).legal_actions(),other.for_player(1).legal_actions())
        self.assertNotIn('cost',g.observe(1)['players'][1]['hand'][0]);self.check(g)

    def test_quote_uses_current_cost_after_restore(self):
        g=self.game(enemy=('web',));snapshot=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(snapshot,self.r)
        self.assertEqual(self.cost(other),4);self.play(other);self.play(g);self.assertEqual(g.snapshot(),other.snapshot());self.check(g)

    def test_rewind_pays_original_aura_quote_once(self):
        self.card('rewind',lambda c:[GainArmor(1,c.rewind_attempt+1)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewind',),enemy=('web',));self.play(g,'rewind');self.check(g);self.choose(g,'retry')
        self.assertEqual((g.state.players[1].mana,self.armor(g)),(6,2));self.check(g)

    def test_choice_can_suspend_granted_aura_operation(self):
        self.script('grant',lambda c:[RequestChoice(1,(ChoiceOption('ok','OK',
            (GrantCostAura(c.state.players[2].board[0],CostAuraSpec(self.spec(),'enemy')),)),))])
        g=self.game(hand=('grant','cry'),enemy=('body',));self.play(g,'grant');self.check(g)
        other=g.clone();self.choose(g);self.choose(other);self.assertEqual(self.cost(g),4)
        self.assertEqual(g.snapshot(),other.snapshot());self.check(g)

    def test_invalid_conditions_and_relations_rejected(self):
        for values in ({'ability':'on_play'},{'present':1},{'basis':'automatic'}):
            with self.subTest(values=values),self.assertRaises(ValueError):CardAbilityCondition(**values)
        with self.assertRaises(ValueError):CostAuraSpec(self.spec(),'both')
        with self.assertRaises(ValueError):CostSpec(ability=True)
        with self.assertRaises(ValueError):GrantCostAura(1,self.spec())
        with self.assertRaises(ValueError):AddCostModifier(1,CostAuraSpec(self.spec(),'enemy'))
        with self.assertRaises(ValueError):AddCostModifier(1,CostSpec(ability=CardAbilityCondition()),scope=CostScope.STARSHIP_LAUNCH)

    def test_wrong_instance_identity_rejected(self):
        g=self.game();entity=g.state.entities[self.hand_id(g)]
        with self.assertRaises(ValueError):matches_ability(CardAbilityCondition(),self.r.card('plain'),entity)

    def test_corrupt_snapshot_relation_or_condition_rejected(self):
        g=self.game(enemy=('web',));i=g.state.players[2].board[0]
        s=g.snapshot();s['state']['entities'][str(i)]['abilities'][0]['cost_aura']['relation']='both';self.reject(s)
        s=g.snapshot();s['state']['entities'][str(i)]['abilities'][0]['cost_aura']['cost']['ability']['present']=1;self.reject(s)

    def test_corrupt_pending_aura_declaration_rejected(self):
        self.script('grant',lambda c:[RequestChoice(1,(ChoiceOption('ok','OK',(GrantCostAura(c.state.players[2].board[0],CostAuraSpec(self.spec(),'enemy')),)),))])
        g=self.game(hand=('grant',),enemy=('body',));self.play(g,'grant');s=g.snapshot()
        self.nested(s['resolution_frame'],'CostAuraSpec')['fields']['relation']='both';self.reject(s)

    def test_cross_player_noncommutative_order_uses_attachment_ids(self):
        self.aura('set',spec=self.spec(delta=0,set_to=1))
        g=self.game(board=('set',),enemy=('web',))
        self.assertEqual(self.cost(g),3)
        g=self.game(board=('web',),enemy=('set',))
        self.assertEqual(self.cost(g),1);self.check(g)

    def test_missing_condition_or_relation_does_not_default_on_restore(self):
        g=self.game(enemy=('web',));i=g.state.players[2].board[0]
        for field in ('relation','ability'):
            s=g.snapshot();a=s['state']['entities'][str(i)]['abilities'][0]['cost_aura']
            del (a if field=='relation' else a['cost'])[field]
            self.reject(s)

    def test_old_snapshot_schema_is_rejected(self):
        s=self.game().snapshot();s['schema_version']=76;self.reject(s)

    def test_real_weblord_combination_restores_and_replays(self):
        from examples.battlecry_cost_auras import run
        game,snapshot=run()
        self.assertIsNotNone(snapshot['state']['pending_choice'])
        self.assertEqual(len(game.state.battlecry_history),2)


if __name__=='__main__':unittest.main()
