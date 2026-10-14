"""Native tribal reduction uses current physical operands in shared cost quotes."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, ChangeMinionTribes, CostAuraSpec,
    CostSpec, EndTurn, Game, IllegalAction, PlayCard, PlayerSetup, Rarity, Registry,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TribeChangeSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import (capture_cost_input, capture_generated_quote_fact,
    quote_input, quote_generated_cost, validate_cost_aura_carrier)
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChangeControl, ChoiceOption,
    CopyMinion, Destroy, GrantCostAura, InvokeBehavior, ModifyCost, RequestChoice,
    ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.intrinsic_costs import validate_generated_quote_fact
from hs_sim.engine.model import AbilityInstance, Keyword, PaymentType
from hs_sim.engine.registry import RuleContext, UnsupportedDefinitionError
from hs_sim.engine.repeat_matching import validate_cost_quote_fact
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

MECHWARPER='GVG_006'
PATH=Path(__file__).resolve().parents[1]/'data/support/tribal-cost-aura-basics.json'
PIN='fec55d51503a2709f22d404608b7fc9a24229f41b82aad2ae8244a2a343f90ef'
AURA=CostAuraSpec(CostSpec(delta=-1,card_types=(CardType.MINION,)),tribes_any=('mech',))

def evidence():
    support=json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support)!=PIN:raise ValueError('Tribal cost evidence changed')
    for row in support['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Raw card evidence changed')
    return support['records'][0]['data']

def registry():
    r=Registry('isolated-tribal-cost-aura-basics-v1');raw=evidence()
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata()))
    r.register_card(CardDefinition(MECHWARPER,raw['name'],CardType.MINION,cost=raw['cost'],
        attack=raw['attack'],health=raw['health'],cost_auras=(AURA,),
        metadata=metadata(tribes=('mech',),rarity=Rarity.COMMON)))
    for cid,tribes,cost in (('mech',('mech',),3),('plain',(),3),('dual',('mech','undead'),3),
        ('all',('all',),3),('unknown',None,3),('cheap',('mech',),1),('free',('mech',),0)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=2,health=5,metadata=metadata(tribes=tribes)))
    r.register_behavior('noop',lambda c:())
    r.register_card(CardDefinition('site','Site',CardType.LOCATION,cost=3,durability=2,on_use='noop',metadata=metadata(tribes=('mech',))))
    r.register_card(CardDefinition('weapon','Weapon',CardType.WEAPON,cost=3,attack=1,durability=2,metadata=metadata(tribes=('mech',))))
    r.register_card(CardDefinition('dormant','Dormant',CardType.MINION,cost=3,health=5,dormant_turns=None,metadata=metadata(tribes=('mech',))))
    def source(c):return next(i for i in c.state.players[1].board if c.state.entities[i].card_id==MECHWARPER)
    def held(c):return next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].kind==CardType.MINION)
    def wait(c):return (RequestChoice(1,(
        ChoiceOption('silence','Silence source',(Silence(source(c)),)),
        ChoiceOption('fault','Remove and fail',(Silence(source(c)),InvokeBehavior('late-fault',source_id=c.source_id,player_id=1))),
    ),c.source_id),)
    def fail(c):raise ValueError('Fixture late failure')
    r.register_behavior('wait-paid',wait);r.register_behavior('late-fault',fail)
    r.register_card(CardDefinition('waiting-mech','Waiting Mech',CardType.MINION,cost=3,health=5,
        battlecry='wait-paid',metadata=metadata(tribes=('mech',))))
    targeted={
        'silence':lambda c:(Silence(c.target_id),),
        'destroy':lambda c:(Destroy(c.target_id,c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'plain-face':lambda c:(Transform(c.target_id,'plain'),),
        'warper-face':lambda c:(Transform(c.target_id,MECHWARPER),),
        'steal':lambda c:(ChangeControl(c.target_id,2),),
        'copy':lambda c:(CopyMinion(c.target_id,1),),
        'base-copy':lambda c:(CopyMinion(c.target_id,1,mode='base'),),
        'sleep':lambda c:(MakeDormant(c.target_id,None),),
        'fault':lambda c:(Silence(c.target_id),InvokeBehavior('late-fault',source_id=c.source_id,player_id=1)),
        'grant-flat':lambda c:(GrantCostAura(c.target_id,CostAuraSpec(CostSpec(delta=-1)),c.source_id),),
    }
    scripts={
        'wait':wait,
        'wake':lambda c:(AwakenMinion(next(i for i in c.state.players[1].board if c.state.entities[i].dormancy is not None)),),
        'summon-warper':lambda c:(Summon(1,MECHWARPER),),
        'get-mech':lambda c:(AddToHand(1,'mech'),),
        'cost-zero':lambda c:(ModifyCost(held(c).id,CostSpec(set_to=0),c.source_id),),
        'cost-set':lambda c:(ModifyCost(held(c).id,CostSpec(set_to=5),c.source_id),),
        'cost-once':lambda c:(AddCostModifier(1,CostSpec(delta=-1,card_types=(CardType.MINION,)),uses_remaining=1,source_id=c.source_id),),
    }
    for name,operation,tribes in (('add-mech','add',('mech',)),('remove-mech','remove',('mech',)),
        ('set-mech','set',('mech',)),('set-plain','set',())):
        def work(c,operation=operation,tribes=tribes):
            return (ChangeMinionTribes(CardReference.capture(held(c)),TribeChangeSpec(operation,tribes),c.source_id),)
        scripts[name]=work
    for name,body in {**scripts,**targeted}.items():
        r.register_behavior(name,body)
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,requires_target=name in targeted,metadata=metadata()))
    return r

class TribalCostAuraBasicsTests(unittest.TestCase):
    def game(self,hand=('mech',),board=(MECHWARPER,),enemy=(),enemy_hand=('mech',),mana=10):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*4,mana=mana,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,board=enemy,deck=('plain',)*4,mana=10,max_mana=10),
        ),seed=39),registry())
    def source(self,g):return g.state.players[1].board[0]
    def held(self,g,cid='mech',p=1):return next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
    def cost(self,g,cid='mech',p=1):
        return g.quote_cost(self.held(g,cid,p)).amount if p==g.state.active_player else self.fact(g,cid,p).amount
    def fact(self,g,cid='mech',p=1):
        state=g.state;return quote_input(state,g.registry,capture_cost_input(state.entities[self.held(g,cid,p)]))
    def play(self,g,cid,target=None):
        p=g.state.active_player;eid=self.held(g,cid,p)
        g.apply(PlayCard(p,eid,target if g.registry.card(cid).requires_target else None));return eid
    def choose(self,g,key):c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def roundtrip(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,registry()).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),registry()).snapshot(),snap)
    def rehash(self,snap):
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')});return snap

    def test_complete_raw_native_pin_and_official_updated_stats(self):
        raw=evidence();self.assertEqual((raw['id'],raw['dbf_id'],raw['cost'],raw['attack'],raw['health']),(MECHWARPER,1940,4,4,4))
        self.assertEqual(raw['text_en'],'Your Mechs cost (1) less.')
        self.assertEqual((raw['tags']['CLASS'],raw['tags']['CARDRACE'],raw['tags']['RARITY']),(12,17,1))
        self.assertEqual(registry().card(MECHWARPER).cost_auras,(AURA,))

    def test_selector_is_immutable_typed_and_simple_friendly_reduction_only(self):
        self.assertEqual(CostAuraSpec(CostSpec()).tribes_any,())
        with self.assertRaises(FrozenInstanceError):AURA.tribes_any=()
        for tribes in (None,['mech'],('mech','mech'),(True,),('',)):
            with self.subTest(tribes=tribes),self.assertRaises((ValueError,TypeError)):replace(AURA,tribes_any=tribes)
        for kw in ({'relation':'enemy'},{'relation':'any'},{'cost':CostSpec(delta=-1)},
            {'cost':replace(AURA.cost,delta=0)},{'cost':replace(AURA.cost,set_to=2,delta=0)},
            {'cost':replace(AURA.cost,minimum=1)},{'cost':replace(AURA.cost,payment=PaymentType.HEALTH)},
            {'cost':replace(AURA.cost,card_ids=('mech',))}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):replace(AURA,**kw)

    def test_ordinary_native_definition_and_no_optional_grant_expansion(self):
        card=registry().card(MECHWARPER)
        for kw in ({'kind':CardType.WEAPON},{'keywords':(Keyword.MAGNETIC,)},
            {'keywords':(Keyword.STARSHIP_PIECE,)},{'cost_auras':(AURA,AURA)}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):Registry('bad').register_card(replace(card,**kw))
        with self.assertRaises(ValueError):GrantCostAura(3,AURA)
        with self.assertRaises(TypeError):CostSpec(tribes_any=('mech',))

    def test_only_friendly_current_mech_minions_match(self):
        g=self.game(hand=('mech','plain','dual','all','weapon','site'))
        self.assertEqual([self.cost(g,c) for c in ('mech','plain','dual','all','weapon','site')],[2,3,2,2,3,3])
        self.assertEqual(self.cost(g,p=2),3);self.assertEqual(g.state.entities[self.held(g)].cost,3)

    def test_hand_and_deck_sources_are_not_active(self):
        g=self.game(hand=(MECHWARPER,'mech'),board=());self.assertEqual(self.cost(g),3)
        self.assertEqual(quote_generated_cost(g.state,g.registry,1,'mech').amount,3)

    def test_played_source_prices_itself_before_it_enters(self):
        g=self.game(hand=(MECHWARPER,'mech'),board=());self.play(g,MECHWARPER)
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana,self.cost(g)),(4,6,2))
        self.roundtrip(g)

    def test_second_native_source_stacks_once_per_physical_carrier(self):
        g=self.game(hand=(MECHWARPER,'mech'));self.play(g,MECHWARPER)
        self.assertEqual((g.state.play_history[-1].cost,self.cost(g)),(3,1))
        q=self.fact(g);self.assertEqual(len(q.contributions),2)
        self.assertEqual(len(set(q.modifier_ids)),2);self.roundtrip(g)

    def test_zero_floor_and_discount_does_not_increase_free_cards(self):
        g=self.game(hand=('cheap','free'),board=(MECHWARPER,MECHWARPER))
        self.assertEqual((self.cost(g,'cheap'),self.cost(g,'free')),(0,0));self.play(g,'cheap')
        self.assertEqual(g.state.players[1].mana,10);self.assertEqual(g.state.play_history[-1].cost,0)

    def test_current_tribe_add_remove_reprices_without_local_cost_cache(self):
        g=self.game(hand=('plain','add-mech','remove-mech'));eid=self.held(g,'plain')
        self.assertEqual(self.cost(g,'plain'),3);self.play(g,'add-mech');self.assertEqual(self.cost(g,'plain'),2)
        self.assertEqual(g.registry.card('plain').metadata.tribes,());self.assertEqual(g.state.entities[eid].cost,3)
        self.play(g,'remove-mech');self.assertEqual(self.cost(g,'plain'),3);self.roundtrip(g)

    def test_all_tribe_exclusion_and_addback_are_not_redundant_weights(self):
        g=self.game(hand=('all','remove-mech','add-mech'));self.assertEqual(self.cost(g,'all'),2)
        self.play(g,'remove-mech');self.assertEqual(self.cost(g,'all'),3)
        self.play(g,'add-mech');self.assertEqual(self.cost(g,'all'),2);self.roundtrip(g)

    def test_explicit_set_can_resolve_unknown_current_identity(self):
        g=self.game(hand=('unknown','set-mech'))
        with self.assertRaises(UnsupportedDefinitionError):self.cost(g,'unknown')
        self.play(g,'set-mech');self.assertEqual(self.cost(g,'unknown'),2);self.roundtrip(g)

    def test_unknown_matching_minion_is_error_and_reads_are_pure(self):
        g=self.game(hand=('unknown',));before=g.snapshot()
        with self.assertRaises(UnsupportedDefinitionError):self.cost(g,'unknown')
        with self.assertRaises(UnsupportedDefinitionError):quote_generated_cost(g.state,g.registry,1,'unknown')
        self.assertEqual(g.snapshot(),before)

    def test_unknown_without_active_tribal_filter_does_not_require_metadata(self):
        g=self.game(hand=('unknown',),board=());self.assertEqual(self.cost(g,'unknown'),3)
        self.assertEqual(quote_generated_cost(g.state,g.registry,1,'unknown').amount,3)

    def test_generated_quote_uses_fresh_printed_face_not_same_named_held_changes(self):
        g=self.game(hand=('plain','add-mech'));self.play(g,'add-mech');before=g.snapshot()
        self.assertEqual(self.cost(g,'plain'),2)
        q=capture_generated_quote_fact(g.state,g.registry,1,'plain');self.assertEqual(q.amount,3)
        self.assertEqual(capture_generated_quote_fact(g.state,g.registry,1,'mech').amount,2)
        validate_generated_quote_fact(g.registry,q);self.assertEqual(g.snapshot(),before)

    def test_generated_addtohand_and_summoned_source_share_original_cost_path(self):
        g=self.game(hand=('get-mech','summon-warper'),board=());self.play(g,'get-mech')
        self.assertEqual(self.cost(g),3);self.play(g,'summon-warper');self.assertEqual(self.cost(g),2)
        self.play(g,'mech');self.assertEqual(g.state.players[1].mana,8);self.roundtrip(g)

    def test_original_local_set_then_external_discount_order(self):
        g=self.game(hand=('mech','cost-set'));self.play(g,'cost-set');self.assertEqual(self.cost(g),4)
        q=self.fact(g);self.assertEqual((q.local_amount,q.amount),(5,4))
        self.assertEqual([c.kind for c in q.contributions],['local_enchantment','cost_aura']);validate_cost_quote_fact(g.registry,q)
        self.play(g,'mech');self.assertEqual(g.state.players[1].mana,6);self.roundtrip(g)

    def test_local_zero_remains_zero_under_external_reduction(self):
        g=self.game(hand=('mech','cost-zero'));self.play(g,'cost-zero');self.assertEqual(self.cost(g),0)
        self.play(g,'mech');self.assertEqual(g.state.players[1].mana,10);self.roundtrip(g)

    def test_original_finite_player_modifier_consumes_only_on_payment(self):
        g=self.game(hand=('mech','cost-once'));self.play(g,'cost-once');before=g.snapshot()
        for _ in range(3):self.assertEqual(self.cost(g),1)
        self.assertEqual(g.snapshot(),before);self.play(g,'mech')
        self.assertEqual(g.state.players[1].mana,9);self.assertFalse(g.state.players[1].cost_modifiers)
        self.roundtrip(g)

    def test_actual_discounted_payment_receipt_matches_quote_once(self):
        g=self.game();q=self.fact(g);self.play(g,'mech');play=g.state.play_history[-1]
        self.assertEqual((play.cost,play.payment,g.state.players[1].mana),(2,PaymentType.MANA,8))
        self.assertEqual(play.submitted_cost.quote.quote_input,q.quote_input)
        self.assertEqual(play.submitted_cost.quote.contributions,q.contributions)
        self.assertEqual(len([e for e in g.events if e.kind=='mana_spent']),1);self.roundtrip(g)

    def test_insufficient_mana_rejection_keeps_transaction_and_information(self):
        g=self.game(mana=1);before=g.snapshot();views=[g.for_player(p).observe() for p in (1,2)]
        with self.assertRaises(IllegalAction):self.play(g,'mech')
        self.assertEqual(g.snapshot(),before);self.assertEqual([g.for_player(p).observe() for p in (1,2)],views)

    def test_source_silence_restores_current_cost_and_native_guard_history(self):
        g=self.game(hand=('mech','silence'));self.play(g,'silence',self.source(g))
        self.assertEqual(self.cost(g),3);self.roundtrip(g)

    def test_source_death_removes_price_and_preserves_complete_frozen_native_declaration(self):
        g=self.game(hand=('mech','destroy'));self.play(g,'destroy',self.source(g))
        self.assertEqual(self.cost(g),3);record=g.state.death_history[-1]
        self.assertEqual(next(a.cost_aura for a in record.abilities if a.kind=='cost_aura'),AURA);self.roundtrip(g)

    def test_source_bounce_and_reinstall_use_shared_printed_lifetime(self):
        g=self.game(hand=('mech','bounce'));src=self.source(g);self.play(g,'bounce',src)
        self.assertEqual(self.cost(g),3);self.play(g,MECHWARPER)
        self.assertEqual((self.cost(g),g.state.play_history[-1].cost),(2,4));self.roundtrip(g)

    def test_source_transform_removes_and_installs_current_native_aura(self):
        g=self.game(hand=('mech','plain-face','warper-face'));src=self.source(g)
        self.play(g,'plain-face',src);self.assertEqual(self.cost(g),3)
        self.play(g,'warper-face',src);self.assertEqual(self.cost(g),2);self.roundtrip(g)

    def test_current_controller_not_original_provenance_gets_reduction(self):
        g=self.game(hand=('mech','steal'));src=self.source(g);self.play(g,'steal',src)
        self.assertEqual((self.cost(g),self.cost(g,p=2)),(3,2))
        self.assertEqual(next(a.source_id for a in g.state.entities[src].abilities if a.kind=='cost_aura'),src)
        g.apply(EndTurn(1));self.play(g,'mech');self.assertEqual(g.state.play_history[-1].cost,2)
        self.assertEqual(g.state.players[2].mana,8);self.roundtrip(g)

    def test_source_dormancy_stops_contribution_and_wake_restores(self):
        g=self.game(hand=('mech','sleep','wake'));self.play(g,'sleep',self.source(g))
        self.assertEqual(self.cost(g),3);self.roundtrip(g);self.play(g,'wake');self.assertEqual(self.cost(g),2);self.roundtrip(g)

    def test_source_current_and_base_copies_use_shared_physical_provenance(self):
        for cid in ('copy','base-copy'):
            with self.subTest(cid=cid):
                g=self.game(hand=('mech',cid));self.play(g,cid,self.source(g));self.assertEqual(self.cost(g),1)
                self.assertEqual(len(self.fact(g).modifier_ids),2);self.roundtrip(g)

    def test_paid_pending_choice_keeps_original_price_after_source_removal(self):
        g=self.game(hand=('waiting-mech',));self.play(g,'waiting-mech');self.assertIsNotNone(g.state.pending_choice)
        saved=g.snapshot();paid=g.state.play_history[-1].submitted_cost;self.assertEqual(paid.quote.amount,2)
        for other in (g,Game.from_snapshot(saved,registry()),g.clone(),replay(build_replay(g),registry())):
            self.choose(other,'silence');self.assertEqual(other.state.players[1].mana,8)
            self.assertEqual(other.state.play_history[-1].submitted_cost,paid)
            validate_cost_quote_fact(other.registry,paid.quote)
        self.roundtrip(g)

    def test_current_tribe_operands_frozen_before_paid_hand_leaves(self):
        g=self.game(hand=('plain','add-mech'));self.play(g,'add-mech');q=self.fact(g,'plain');self.play(g,'plain')
        paid=g.state.play_history[-1].submitted_cost.quote
        self.assertEqual(paid.quote_input,q.quote_input);self.assertEqual(paid.contributions,q.contributions)
        self.assertEqual((paid.amount,len(paid.quote_input.enchantments)),(2,1));validate_cost_quote_fact(g.registry,paid)
        self.roundtrip(g)

    def test_immediate_effect_failure_rolls_back_source_and_quote(self):
        g=self.game(hand=('mech','fault'));before=g.snapshot()
        with self.assertRaises((ResolutionError,ValueError)):self.play(g,'fault',self.source(g))
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.cost(g),2)

    def test_pending_choice_failure_rolls_back_price_frame_and_both_views(self):
        g=self.game(hand=('waiting-mech',));self.play(g,'waiting-mech');before=g.snapshot()
        views=[g.for_player(p).observe() for p in (1,2)]
        with self.assertRaises((ResolutionError,ValueError)):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.assertEqual([g.for_player(p).observe() for p in (1,2)],views)
        self.choose(g,'silence');self.roundtrip(g)

    def test_public_cost_actions_are_pure_and_hide_internal_quote_operands(self):
        g=self.game();before=g.snapshot();own=g.for_player(1).observe()
        self.assertEqual(own['observation']['players'][0]['hand'][0]['cost']['amount'],2)
        self.assertTrue(any(isinstance(a,PlayCard) and a.entity_id==self.held(g) for a in g.legal_actions()))
        for p in (1,2):
            text=json.dumps(g.for_player(p).observe());
            for hidden in ('tribes_any','contributions','resolution_frame','registry_fingerprint','modifier_ids'):self.assertNotIn(hidden,text)
        self.assertEqual(g.snapshot(),before)

    def test_native_ability_provenance_and_exact_printed_selector_guards(self):
        g=self.game();a=next(a for a in g.state.entities[self.source(g)].abilities if a.kind=='cost_aura')
        for kw in ({'origin':'granted'},{'consumed':True},{'expires_turn':1},{'remove_on_silence':False},{'magnetic_id':1},{'source_id':None}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):replace(a,**kw)
        for spec in (replace(AURA,tribes_any=()),replace(AURA,tribes_any=('beast',)),replace(AURA,cost=replace(AURA.cost,delta=-2))):
            with self.subTest(spec=spec),self.assertRaises(ValueError):validate_cost_aura_carrier(g.registry,MECHWARPER,CardType.MINION,[replace(a,cost_aura=spec)])
        with self.assertRaises(ValueError):validate_cost_aura_carrier(g.registry,MECHWARPER,CardType.MINION,[a,replace(a,id=999)])
        with self.assertRaises(ValueError):validate_cost_aura_carrier(g.registry,'plain',CardType.MINION,[a])

    def test_compact_physical_fact_rechecks_its_original_current_tribe(self):
        g=self.game();q=self.fact(g);validate_cost_quote_fact(g.registry,q)
        value=replace(q.quote_input,card_id='plain')
        intrinsic=replace(q.intrinsic,card_id='plain')
        with self.assertRaises(ValueError):validate_cost_quote_fact(g.registry,replace(q,quote_input=value,intrinsic=intrinsic))

    def test_compact_generated_fact_rechecks_printed_tribe(self):
        g=self.game();q=capture_generated_quote_fact(g.state,g.registry,1,'mech');validate_generated_quote_fact(g.registry,q)
        value=replace(q.quote_input,card_id='plain');intrinsic=replace(q.intrinsic,card_id='plain')
        with self.assertRaises(ValueError):validate_generated_quote_fact(g.registry,replace(q,quote_input=value,intrinsic=intrinsic))

    def test_rehashed_wire_requires_full_selector_and_native_declaration(self):
        g=self.game();src=self.source(g)
        for value in (None,'mech',[True],['mech','mech'],[],['beast']):
            s=g.snapshot();a=next(a for a in s['state']['entities'][str(src)]['abilities'] if a['kind']=='cost_aura');a['cost_aura']['tribes_any']=value
            with self.subTest(value=value),self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry())
        s=g.snapshot();del next(a for a in s['state']['entities'][str(src)]['abilities'] if a['kind']=='cost_aura')['cost_aura']['tribes_any']
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry())

    def test_death_and_paid_original_domains_reject_stripped_native_selector(self):
        g=self.game(hand=('waiting-mech',));self.play(g,'waiting-mech');saved=g.snapshot()
        # Original full payment state is checked independently of today's board.
        frame=deepcopy(saved['resolution_frame']);changed=[]
        def strip(node):
            if isinstance(node,dict):
                if 'entities' in node and isinstance(node['entities'],dict):
                    for entity in node['entities'].values():
                        for ability in entity.get('abilities',[]):
                            if ability.get('kind')=='cost_aura' and ability['cost_aura']['tribes_any']:
                                ability['cost_aura']['tribes_any']=[];changed.append(True)
                for child in node.values():strip(child)
            elif isinstance(node,list):
                for child in node:strip(child)
        strip(frame);self.assertTrue(changed);saved['resolution_frame']=frame
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry())
        g2=self.game(hand=('mech','destroy'));self.play(g2,'destroy',self.source(g2));s=g2.snapshot()
        next(a for a in s['state']['death_history'][-1]['abilities'] if a['kind']=='cost_aura')['cost_aura']['tribes_any']=[]
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry())

    def test_captured_context_validates_its_own_source_catalog(self):
        g=self.game();codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);ctx=RuleContext(g.state,self.source(g),1)
        self.assertEqual(codec.decode(codec.encode(ctx)).state.entities[self.source(g)].abilities,ctx.state.entities[self.source(g)].abilities)
        state=deepcopy(g.state);src=state.entities[self.source(g)]
        src.abilities=[replace(a,cost_aura=replace(AURA,tribes_any=())) if a.kind=='cost_aura' else a for a in src.abilities]
        with self.assertRaises(ValueError):codec.decode(codec.encode(replace(ctx,state=state)))

    def test_existing_empty_aura_grant_preserves_original_scope(self):
        g=self.game(hand=('mech','plain','grant-flat'));self.play(g,'grant-flat',self.source(g))
        self.assertEqual((self.cost(g),self.cost(g,'plain')),(1,2));self.roundtrip(g)

    def test_schema_strictly_rejects_every_old_and_nonstrict_version(self):
        g=self.game();s=g.snapshot();self.assertEqual(s['schema_version'],266)
        self.assertEqual(s['ruleset']['id'],'prototype-v302');self.assertEqual(s['mechanics_version']['version'],CORE_EFFECTS_VERSION)
        for value in (*range(1,218),True,187.0,217):
            bad=deepcopy(s);bad['schema_version']=value
            with self.subTest(value=value),self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())

if __name__=='__main__':unittest.main()
