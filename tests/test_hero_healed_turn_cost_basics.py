"""One finite hero-healed intrinsic bool over the original healing/price pipeline."""
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import unittest
from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, DeckSpec, EndTurn, Game,
    HealthFlow, HealthOp, HealthRule, IntrinsicCostSpec, Keyword, MatchSetup, PaymentType, PlayCard,
    PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input, capture_quote_fact, capture_generated_quote_fact
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption,
    Damage, Effect, GainArmor, Heal, InvokeBehavior, ModifyCost, RequestChoice,
    ReturnToHand, Silence, Summon)
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.intrinsic_costs import (validate_definition_intrinsics, validate_intrinsic_origin,
    validate_intrinsic_stage_fact, validate_intrinsic_history_prefix, validate_generated_quote_fact)
from hs_sim.engine.model import HeroHealedTurnMatch, IntrinsicCostStageFact, PreviousOwnerTurnMatch
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import canonical_hash, _intrinsic_stage_from_dict
from hs_sim.targets import canonical_digest
from opening_fixtures import policy, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE='ICC_700'; CONDITION='hero_healed_this_turn'; HISTORY='healing.hero-this-turn-v1'
SUPPORT=Path(__file__).resolve().parents[1]/'data/support/hero-healed-turn-cost-basics.json'
PIN='a64b0f73e25bbc7907573abdbc0bbbc0b28679298c85768ea198edcebc88c164'
def evidence():
    packet=json.loads(SUPPORT.read_bytes())
    if canonical_digest(packet)!=PIN: raise ValueError('Complete hero-healed condition evidence changed')
    if len(packet['records'])!=2: raise ValueError('Lost original/Core evidence')
    for row in packet['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Original full row changed')
    return {row['id']:row['data'] for row in packet['records']}
def spec(**kw):return IntrinsicCostSpec(set_to=0,condition=CONDITION,history_profile_id=HISTORY,**kw)
def native():
    raw=evidence()[NATIVE]
    return CardDefinition(NATIVE,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),intrinsic_costs=(spec(),))
@dataclass(frozen=True)
class SavedStage(Effect):
    stage: IntrinsicCostStageFact
    def __post_init__(self):
        if type(self.stage)is not IntrinsicCostStageFact:raise ValueError('Expected complete original price stage')
        self.stage.__post_init__()
def mechanics():
    def resume(r,work):
        validate_intrinsic_history_prefix(work.stage,r.state,r.registry)
        return (GainArmor(work.stage.player_id,int(work.stage.condition_facts[0].matched)),)
    return default_mechanics('b75-healed-price-typed-test').register(SavedStage,resume)
def registry():
    r=opening_registry();r.register_card(native())
    hero=lambda c,p=None:c.state.players[c.player_id if p is None else p].hero_id
    hand=lambda c:next(c.state.entities[e] for e in c.state.players[c.player_id].hand if c.state.entities[e].card_id==NATIVE)
    body=lambda c:c.state.players[c.player_id].board[0]
    scripts={
        'hurt':lambda c:(Damage(hero(c),2,c.source_id),),
        'heal':lambda c:(Heal(hero(c),5,c.source_id),),
        'zero':lambda c:(Heal(hero(c),0,c.source_id),),
        'heal.unknown':lambda c:(Heal(hero(c),5),),
        'heal.other.source':lambda c:(Heal(hero(c),5,c.state.players[3-c.player_id].board[0]),),
        'hurt.other':lambda c:(Damage(hero(c,3-c.player_id),2,c.source_id),),
        'heal.other':lambda c:(Heal(hero(c,3-c.player_id),5,c.source_id),),
        'hurt.body':lambda c:(Damage(body(c),2,c.source_id),),
        'heal.body':lambda c:(Heal(body(c),5,c.source_id),),
        'acquire':lambda c:(AddToHand(c.player_id,NATIVE),),
        'copy':lambda c:(CopyCard(CardReference.capture(hand(c)),c.player_id),),
        'transfer':lambda c:(MoveCard(CardReference.capture(hand(c)),3-c.player_id,Zone.HAND),),
        'transform':lambda c:(TransformCapturedMinion(CardReference.capture(hand(c)),'card.1'),),
        'bounce':lambda c:(ReturnToHand(body(c)),),
        'silence':lambda c:(Silence(body(c)),),
        'layers':lambda c:(ModifyCost(hand(c).id,CostSpec(set_to=4)),AddCostModifier(c.player_id,CostSpec(delta=-1,card_ids=(NATIVE,)))),
        'health.pay':lambda c:(AddCostModifier(c.player_id,CostSpec(payment=PaymentType.HEALTH,card_ids=(NATIVE,))),),
        'fail':lambda c:(Heal(hero(c),5,c.source_id),AddToHand(c.player_id,'unknown.b75.card')),
        'enable.prevent':lambda c:(Summon(c.player_id,'prevent'),),
        'enable.convert':lambda c:(Summon(c.player_id,'convert'),),
        'damage.heals':lambda c:(Summon(c.player_id,'damage.convert'),Damage(hero(c),2,c.source_id)),
    }
    for cid,fn in scripts.items():
        r.register_behavior(cid,fn);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    for cid,flow,operation in (('prevent',HealthFlow.HEALING,HealthOp.PREVENT),('convert',HealthFlow.HEALING,HealthOp.CONVERT),('damage.convert',HealthFlow.DAMAGE,HealthOp.CONVERT)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=4,health_rules=(HealthRule(flow,operation,source_relation='friendly'),)))
    def wait(c):
        stage=capture_quote_fact(c.state,r,capture_cost_input(hand(c))).intrinsic
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Accept',(SavedStage(stage),)),
            ChoiceOption('fault','Failure',(InvokeBehavior('late.fault',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior('freeze',wait);r.register_card(CardDefinition('freeze','Freeze quote probe',CardType.SPELL,on_play='freeze'))
    r.register_behavior('late.fault',lambda c:(AddToHand(c.player_id,'unknown.b75.choice'),))
    def paid(c):
        if c.state.entities[c.event.source_id].card_id!=NATIVE:return ()
        return (Heal(hero(c),2,c.source_id),RequestChoice(c.player_id,(ChoiceOption('ok','Continue',()),
            ChoiceOption('fault','Failure',(InvokeBehavior('late.fault',c.source_id,c.player_id),))),c.source_id))
    r.register_behavior('paid.wait',paid)
    r.register_card(CardDefinition('watch','Original after-payment probe',CardType.MINION,health=4,triggers=(TriggerSpec('card_committed','paid.wait'),)))
    return r
def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
    return saved
class HeroHealedCostTests(unittest.TestCase):
    def game(self,hand=(NATIVE,),*,board=(),enemy=('card.1',),enemy_hand=(),typed=False):
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=('card.1',)*8,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',hand=enemy_hand,board=enemy,deck=('card.1',)*8,mana=10,max_mana=10)),seed=75),registry(),mechanics=mechanics() if typed else None)
    def play(self,g,cid):
        p=g.state.active_player;eid=next(e for e in g.state.players[p].hand if g.state.entities[e].card_id==cid)
        g.apply(PlayCard(p,eid));return eid
    def source(self,g,p=1):return next(g.state.entities[e] for e in g.state.players[p].hand if g.state.entities[e].card_id==NATIVE)
    def fact(self,g,p=1):return capture_quote_fact(g.state,g.registry,capture_cost_input(self.source(g,p)))
    def ready(self,extras=(),**kwargs):
        g=self.game(('hurt','heal',NATIVE,*extras),**kwargs);self.play(g,'hurt');self.play(g,'heal');return g
    def check(self,g,typed=False):
        saved=json.loads(json.dumps(g.snapshot()))
        for branch in (Game.from_snapshot(saved,registry(),mechanics=mechanics() if typed else None),g.clone(),replay(build_replay(g),registry(),mechanics=mechanics() if typed else None)):
            self.assertEqual(branch.snapshot(),saved)
        return saved
    def test_full_raw_pin_printed_native_and_core_evidence_only(self):
        raw=evidence()[NATIVE];card=native()
        self.assertEqual((raw['dbf_id'],raw['tags']['RARITY'],raw['tags']['CARDRACE'],card.cost,card.attack,card.health),(42783,3,11,3,3,3))
        self.assertEqual(card.metadata,metadata_from_record(raw));self.assertEqual(card.intrinsic_costs,(spec(),))
        self.assertEqual((card.battlecry,card.deathrattle,card.keywords),(None,None,()))
        self.assertNotIn('CORE_ICC_700',registry().cards)
    def test_native_real_thirty_slot_experimental_deck_and_mulligan(self):
        r=registry();own=tuple(f'card.{i}' for i in range(1,30))+(NATIVE,);enemy=tuple(f'card.{i}' for i in range(1,31))
        g=Game.from_decks(MatchSetup((DeckSpec('mage.hero','mage.power',CardClass.MAGE,own),DeckSpec('warrior.hero','warrior.power',CardClass.WARRIOR,enemy)),policy(r),'coin',75,1),r)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        self.assertEqual(tuple(map(len,g.state.opening.original_entities)),(30,30))
        self.assertEqual(capture_generated_quote_fact(g.state,r,1,NATIVE).amount,3)
    def test_initial_false_and_unhealed_native_pays_printed_three_once(self):
        g=self.game();self.assertEqual(self.fact(g).amount,3);self.play(g,NATIVE)
        root=g.state.play_history[-1];self.assertEqual((root.cost,g.state.players[1].mana),(3,7));self.check(g)
    def test_actual_hero_positive_makes_native_zero_and_full_three_three(self):
        g=self.ready();self.assertEqual(self.fact(g).amount,0);eid=self.play(g,NATIVE)
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana,g.state.entities[eid].attack,g.state.entities[eid].health),(0,10,3,3));self.check(g)
    def test_full_health_and_zero_requested_heals_remain_false(self):
        g=self.game(('heal','zero',NATIVE));self.play(g,'heal');self.play(g,'zero')
        condition=self.fact(g).intrinsic.condition_facts[0]
        self.assertEqual((condition.matched,len(condition.records),self.fact(g).amount),(False,2,3));self.check(g)
    def test_minion_healing_does_not_satisfy_hero_condition(self):
        g=self.game(('hurt.body','heal.body',NATIVE),board=('card.1',));self.play(g,'hurt.body');self.play(g,'heal.body')
        self.assertEqual(self.fact(g).amount,3);self.check(g)
    def test_other_target_hero_does_not_satisfy_payer_condition(self):
        g=self.game(('hurt.other','heal.other',NATIVE));self.play(g,'hurt.other');self.play(g,'heal.other')
        self.assertEqual((self.fact(g).amount,capture_generated_quote_fact(g.state,g.registry,2,NATIVE).amount),(3,0));self.check(g)
    def test_enemy_healer_still_satisfies_actual_target_player(self):
        g=self.game(('hurt','heal.other.source',NATIVE));self.play(g,'hurt');self.play(g,'heal.other.source')
        self.assertEqual(self.fact(g).amount,0);self.check(g)
    def test_unknown_source_positive_target_is_sufficient_without_guessing_healer(self):
        g=self.game(('hurt','heal.unknown',NATIVE));self.play(g,'hurt');self.play(g,'heal.unknown')
        self.assertEqual(self.fact(g).amount,0);self.check(g)
    def test_prevention_and_healing_to_damage_do_not_satisfy(self):
        for enable in ('enable.prevent','enable.convert'):
            g=self.game(('hurt',enable,'heal',NATIVE));self.play(g,'hurt');self.play(g,enable);self.play(g,'heal')
            self.assertEqual(self.fact(g).amount,3);self.check(g)
    def test_damage_to_actual_healing_satisfies_final_target_condition(self):
        g=self.game(('hurt','damage.heals',NATIVE));self.play(g,'hurt');self.play(g,'damage.heals')
        self.assertEqual(self.fact(g).amount,0);self.check(g)
    def test_later_acquisition_sees_prior_current_turn_healing(self):
        g=self.game(('hurt','heal','acquire'));self.play(g,'hurt');self.play(g,'heal');self.play(g,'acquire')
        self.assertEqual(self.fact(g).amount,0);self.play(g,NATIVE);self.check(g)
    def test_turn_rollover_retires_bool_but_retains_original_history_and_paid_price(self):
        g=self.ready((NATIVE,));self.play(g,NATIVE);stage=g.state.play_history[-1].submitted_cost.quote.intrinsic
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(self.fact(g).amount,3)
        validate_intrinsic_history_prefix(stage,g.state,g.registry);self.assertEqual(stage.amount,0);self.check(g)
    def test_frozen_complete_rows_include_false_other_and_zero_after_true(self):
        g=self.ready(('zero','hurt.other','heal.other'));self.play(g,'zero');self.play(g,'hurt.other');self.play(g,'heal.other')
        match=self.fact(g).intrinsic.condition_facts[0]
        self.assertEqual(match.records,tuple(g.state.healing_history));self.assertEqual(len(match.records),3)
        self.assertTrue(match.matched);self.assertEqual(match.next_healing_id,4)
    def test_physical_and_generated_queries_share_bool_and_remain_pure(self):
        g=self.ready();saved=g.snapshot()
        for _ in range(3):
            self.assertEqual((self.fact(g).amount,capture_generated_quote_fact(g.state,g.registry,1,NATIVE).amount),(0,0))
            validate_generated_quote_fact(g.registry,capture_generated_quote_fact(g.state,g.registry,2,NATIVE))
        self.assertEqual(g.snapshot(),saved)
    def test_original_local_and_external_cost_layers_follow_intrinsic(self):
        g=self.ready(('layers',));self.play(g,'layers');q=self.fact(g)
        self.assertEqual((q.intrinsic.amount,q.amount),(0,3));self.play(g,NATIVE)
        self.assertEqual(g.state.players[1].mana,7);self.check(g)
    def test_original_alternative_health_account_still_uses_once_accepted_amount(self):
        g=self.game(('health.pay',NATIVE));self.play(g,'health.pay');self.play(g,NATIVE)
        self.assertEqual((g.state.entities[g.state.players[1].hero_id].health,g.state.players[1].mana),(27,10));self.check(g)
    def test_native_copy_shares_condition_without_mutable_discount_cache(self):
        g=self.ready(('copy',));self.play(g,'copy')
        cards=[g.state.entities[e] for e in g.state.players[1].hand if g.state.entities[e].card_id==NATIVE]
        self.assertEqual(len(cards),2);self.assertTrue(all(capture_quote_fact(g.state,g.registry,capture_cost_input(e)).amount==0 for e in cards));self.check(g)
    def test_transferred_hand_native_requotes_for_actual_new_payer(self):
        g=self.ready(('transfer',));self.play(g,'transfer')
        self.assertEqual(self.fact(g,2).amount,3);self.check(g)
    def test_transformed_hand_native_uses_new_printed_face_not_old_bool(self):
        g=self.ready(('transform',));eid=self.source(g).id;self.play(g,'transform')
        self.assertEqual(capture_quote_fact(g.state,g.registry,capture_cost_input(g.state.entities[eid])).amount,1);self.check(g)
    def test_silence_and_bounce_use_original_native_definition_on_reentry(self):
        g=self.ready(('silence','bounce'));eid=self.play(g,NATIVE);self.play(g,'silence');self.play(g,'bounce')
        self.assertEqual((self.source(g).id,self.fact(g).amount),(eid,0));self.check(g)
    def test_after_payment_healing_and_wait_do_not_reprice_original_root(self):
        g=self.game(('hurt',NATIVE,NATIVE),board=('watch',));self.play(g,'hurt');self.play(g,NATIVE)
        stage=g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.assertEqual((stage.amount,self.fact(g).amount,g.state.players[1].mana),(3,0,7));self.check(g)
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(g.state.players[1].mana,7);validate_intrinsic_history_prefix(stage,g.state,g.registry);self.check(g)
    def test_after_payment_failed_choice_preserves_original_price_and_heal(self):
        g=self.game(('hurt',NATIVE),board=('watch',));self.play(g,'hurt');self.play(g,NATIVE);before=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(q.player_id,q.id,('fault',)))
        self.assertEqual(g.snapshot(),before)
    def test_typed_frozen_quote_waiting_restore_clone_replay_and_resume(self):
        g=self.ready(('freeze',),typed=True);self.play(g,'freeze');self.check(g,True)
        for other in (g.clone(),Game.from_snapshot(g.snapshot(),registry(),mechanics=mechanics()),replay(build_replay(g),registry(),mechanics=mechanics())):
            q=other.state.pending_choice;other.apply(SelectChoice(q.player_id,q.id,('ok',)))
            self.assertEqual(other.state.entities[other.state.players[1].hero_id].armor,1);self.check(other,True)
    def test_complete_fact_dictionary_and_typed_codec_roundtrip(self):
        g=self.ready();stage=self.fact(g).intrinsic;codec=FrameCodec(g.mechanics,g.registry)
        self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(stage)))),stage)
        self.assertEqual(_intrinsic_stage_from_dict(json.loads(json.dumps(asdict(stage)))),stage)
        validate_intrinsic_origin(stage,g.state,g.registry)
    def test_failed_action_rolls_back_new_healing_and_resulting_discount(self):
        g=self.game(('hurt','fail',NATIVE));self.play(g,'hurt');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'fail')
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.fact(g).amount,3)
    def test_original_window_rejects_omitted_false_tail_even_same_true_price(self):
        g=self.ready(('zero',));self.play(g,'zero');stage=self.fact(g).intrinsic;match=stage.condition_facts[0]
        short=replace(match,records=match.records[:-1],next_healing_id=match.next_healing_id-1)
        changed=replace(stage,condition_facts=(short,));validate_intrinsic_stage_fact(g.registry,changed)
        with self.assertRaises(ValueError):validate_intrinsic_origin(changed,g.state,g.registry)
    def test_paid_retained_prefix_rejects_same_price_false_tail_truncation(self):
        g=self.ready(('zero',));self.play(g,'zero');self.play(g,NATIVE)
        stage=g.state.play_history[-1].submitted_cost.quote.intrinsic;match=stage.condition_facts[0]
        changed=replace(stage,condition_facts=(replace(match,records=match.records[:-1],next_healing_id=match.next_healing_id-1),))
        with self.assertRaises(ValueError):validate_intrinsic_history_prefix(changed,g.state,g.registry)
    def test_strict_match_types_player_clock_cursor_row_and_aggregate(self):
        g=self.ready();match=self.fact(g).intrinsic.condition_facts[0]
        for kwargs in ({'player_id':True},{'turn':0},{'action':True},{'next_healing_id':True},{'matched':1},{'matched':False},{'records':list(match.records)}):
            with self.assertRaises(ValueError):replace(match,**kwargs)
        with self.assertRaises(ValueError):replace(self.fact(g).intrinsic,condition_facts=())
    def test_declarations_reject_unknown_profiles_foreign_kinds_and_mixed_conditions(self):
        for kwargs in ({'condition':'hero_was_healed'},{'history_profile_id':'owner-turn.latest-closed-v1'},{'condition':True}):
            with self.assertRaises(ValueError):replace(spec(),**kwargs)
        for card in (replace(native(),kind=CardType.SPELL),replace(native(),keywords=(Keyword.MAGNETIC,)),
                     replace(native(),intrinsic_costs=(spec(),IntrinsicCostSpec(delta=-1)))):
            with self.assertRaises(ValueError):validate_definition_intrinsics(card)
    def test_unknown_original_source_card_cannot_hide_behind_true_or_zero(self):
        g=self.ready(('zero',));self.play(g,'zero');stage=self.fact(g).intrinsic;match=stage.condition_facts[0]
        row=match.records[-1];payload=tuple((k,'unknown.b75.source' if k=='source_card_id' else v) for k,v in row.result)
        changed=replace(stage,condition_facts=(replace(match,records=match.records[:-1]+(replace(row,result=payload),)),))
        with self.assertRaises(ValueError):validate_intrinsic_stage_fact(g.registry,changed)
    def test_rehashed_paid_record_cannot_drop_complete_condition(self):
        g=self.ready();self.play(g,NATIVE);saved=self.check(g)
        saved['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['condition_facts']=[]
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry())
    def test_player_interface_shows_zero_submits_once_and_filters_private_history(self):
        g=self.ready();port=g.for_player(1);dto=port.legal_actions();row=next(r for r in g.observe(1)['players'][0]['hand'] if r['card_id']==NATIVE)
        action=next(a for a in dto['actions'] if a.get('card')==row['ref'])
        self.assertTrue(port.submit({'revision':dto['revision'],'action':action})['accepted']);self.assertEqual(g.state.players[1].mana,10)
        for p in (1,2):
            view=json.dumps((g.observe(p),g.for_player(p).legal_actions()))
            for private in ('HeroHealedTurnMatch','healing_history','condition_facts','history_profile_id'):self.assertNotIn(private,view)
        self.check(g)
    def test_current_protocol_and_old_schema_refusal(self):
        g=self.game();s=g.snapshot();self.assertEqual((s['schema_version'],g.ruleset.id,g.mechanics.version),(266,'prototype-v302',CORE_EFFECTS_VERSION))
        for value in (1,212,217,True,216.0):
            bad=deepcopy(s);bad['schema_version']=value
            with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
if __name__=='__main__':unittest.main()
