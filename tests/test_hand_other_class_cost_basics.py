"""One Vendetta and finite current-own-hand class condition in original pricing."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import unittest
from hs_sim.engine import (CardClass,CardDefinition,CardType,CostSpec,Game,HandOtherClassMatch,
    IllegalAction,IntrinsicCostSpec,PlayCard,PlayerSetup,Registry,ResolutionError,Scenario,
    SelectChoice,SnapshotError,TargetSpec,TriggerSpec,Zone,capture_hand_other_class,hand_has_other_class)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input,capture_quote_fact,capture_generated_quote_fact
from hs_sim.engine.effects import (AddCostModifier,AddToHand,ChoiceOption,Damage,InvokeBehavior,
    ModifyCost,ReplaceHero,RequestChoice)
from hs_sim.engine.hand_conditions import validate_hand_other_class_match
from hs_sim.engine.intrinsic_costs import validate_intrinsic_origin,validate_intrinsic_history_prefix
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash,_intrinsic_stage_from_dict
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

CARD='DAL_716'
PIN='855bb763b2bd204a579fb5515efe409a0a6a5852c437db3dabed7578f2724c84'
SPEC=IntrinsicCostSpec(set_to=0,condition='hand_other_class',history_profile_id='hand.current-other-class-v1')


def evidence():
    data=json.loads((Path(__file__).resolve().parents[1]/'data/support/hand-other-class-cost-basics.json').read_bytes())
    if canonical_digest(data)!=PIN:raise ValueError('Complete hand class evidence changed')
    for row in data['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Raw hand class card changed')
    return data


def registry():
    r=Registry('isolated-current-hand-other-class-price-v1')
    for name,clazz in (('hero.rogue',CardClass.ROGUE),('hero.mage',CardClass.MAGE),('hero.neutral',CardClass.NEUTRAL)):
        r.register_card(CardDefinition(name,name,CardType.HERO,health=80,metadata=metadata(clazz,tribes=())))
    r.register_behavior('power',lambda c:())
    r.register_card(CardDefinition('power','Power',CardType.HERO_POWER,on_use='power',metadata=metadata(tribes=())))
    r.register_card(CardDefinition('hero.keep','Keep current class',CardType.HERO,health=80,
        hero_card=True,initial_hero_power='power',keep_hero_class=True,metadata=metadata(tribes=())))
    for cid,classes in (('rogue',(CardClass.ROGUE,)),('mage',(CardClass.MAGE,)),('neutral',(CardClass.NEUTRAL,)),
            ('dual-own',(CardClass.ROGUE,CardClass.MAGE)),('dual-foreign',(CardClass.MAGE,CardClass.PRIEST))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=10,
            metadata=replace(metadata(classes[0],tribes=()),classes=classes)))
    r.register_card(CardDefinition('unknown','Unknown class',CardType.MINION,health=5))
    raw=evidence()['records'][0]['data'];r.register_behavior('vendetta',lambda c:(Damage(c.target_id,4,c.source_id),))
    r.register_card(CardDefinition(CARD,raw['name'],CardType.SPELL,cost=raw['cost'],on_play='vendetta',
        targeting=TargetSpec(kinds=(CardType.MINION,)),intrinsic_costs=(SPEC,),metadata=metadata_from_record(raw)))
    def source(c,cid):return next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==cid)
    def lose(c):return MoveCard(CardReference.capture(source(c,'mage')),c.player_id,Zone.DECK,source_id=c.source_id)
    scripts={
        'gain':lambda c:(AddToHand(c.player_id,'mage'),),
        'lose':lambda c:(lose(c),),
        'hero':lambda c:(ReplaceHero(c.player_id,'hero.mage'),),
        'keep':lambda c:(ReplaceHero(c.player_id,'hero.keep'),),
        'local':lambda c:(ModifyCost(source(c,CARD).id,CostSpec(delta=2),c.source_id),),
        'tax':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=1,card_ids=(CARD,))),),
        'copy':lambda c:(CopyCard(CardReference.capture(source(c,CARD)),c.player_id,Zone.HAND),),
        'transfer':lambda c:(MoveCard(CardReference.capture(source(c,CARD)),2,Zone.HAND,source_id=c.source_id),),
    }
    for name,body in scripts.items():
        r.register_behavior(name,body);r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,metadata=metadata(CardClass.ROGUE,tribes=())))
    def wait(c):
        if c.event.kind=='card_committed' and (c.play is None or c.play.card_id!=CARD):return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('lose','Lose foreign hand card',(lose(c),)),
            ChoiceOption('hero','Change current class',(ReplaceHero(c.player_id,'hero.mage'),)),
            ChoiceOption('fault','Lose then fail',(lose(c),InvokeBehavior('late-fault',c.source_id,c.player_id))),
        ),c.source_id),)
    r.register_behavior('wait',wait)
    r.register_behavior('late-fault',lambda c:(AddToHand(c.player_id,'unknown.hand-class'),))
    r.register_card(CardDefinition('watch','Original paid window',CardType.MINION,health=5,
        triggers=(TriggerSpec('card_committed','wait'),),metadata=metadata(tribes=())))
    return r


class HandOtherClassCostBasicsTests(unittest.TestCase):
    def game(self,hand=(CARD,),*,hero='hero.rogue',enemy_hero='hero.rogue',enemy_hand=(),board=(),mana=10):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=('rogue',)*4,mana=mana,max_mana=10),
            PlayerSetup(enemy_hero,hand=enemy_hand,board=('neutral',),deck=('rogue',)*4,mana=10,max_mana=10),
        ),seed=47),registry())
    def source(self,g,p=1):return next(g.state.entities[i] for i in g.state.players[p].hand if g.state.entities[i].card_id==CARD)
    def fact(self,g,p=1):return capture_quote_fact(g.state,g.registry,capture_cost_input(self.source(g,p)))
    def condition(self,g,p=1):return self.fact(g,p).intrinsic.condition_facts[0]
    def cast(self,g,name=CARD,p=1):
        eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(p,eid,g.state.players[2].board[0] if name==CARD else None))
    def choose(self,g,name):q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(name,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));restored=Game.from_snapshot(saved,registry())
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return restored
    def reject(self,saved):
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())

    def test_full_raw_and_only_necessary_vendetta(self):
        raw=evidence();card=registry().card(CARD)
        self.assertEqual(raw['new_real_card_adapters'],[CARD]);self.assertEqual((card.cost,card.intrinsic_costs,card.metadata.classes),(4,(SPEC,),(CardClass.ROGUE,)))

    def test_strict_finite_price_spec_and_original_inventory(self):
        for changes in ({'set_to':None},{'delta':-1},{'minimum':1},{'mana_crystals':1},{'card_count':1},{'history_profile_id':'owner-turn.latest-closed-v1'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(SPEC,**changes)
        g=self.game((CARD,'mage'));condition=self.condition(g)
        for changes in ({'player_id':True},{'hero_class':CardClass.NEUTRAL},{'hero_class':'rogue'},{'rows':list(condition.rows)},{'rows':(condition.rows[0],)*2}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(condition,**changes)

    def test_current_class_neutral_dual_and_duplicate_physical_rows(self):
        for other,amount in (((),4),(('rogue',),4),(('neutral',),4),(('mage',),0),(('dual-own',),4),(('dual-foreign',),0),(('mage','mage'),0)):
            with self.subTest(other=other):
                g=self.game((CARD,*other));fact=self.fact(g);self.assertEqual(fact.amount,amount)
                self.assertEqual([row.entity_id for row in fact.intrinsic.condition_facts[0].rows],g.state.players[1].hand)
                self.portable(g)

    def test_priced_card_counts_when_it_is_itself_foreign_in_physical_hand(self):
        g=self.game(hero='hero.mage');self.assertEqual(self.fact(g).amount,0)
        self.assertTrue(self.condition(g).rows[0].matched);self.cast(g);self.assertEqual(g.state.players[1].mana,10);self.portable(g)

    def test_generated_preview_does_not_insert_virtual_foreign_card_in_hand(self):
        g=self.game(hand=(),hero='hero.mage');before=g.snapshot()
        self.assertEqual(capture_generated_quote_fact(g.state,g.registry,1,CARD).amount,4)
        self.assertEqual(g.snapshot(),before)

    def test_unknown_own_metadata_even_after_true_match_is_not_ignored(self):
        g=self.game((CARD,'mage','unknown'))
        with self.assertRaisesRegex(ValueError,'Unknown candidate metadata'):self.fact(g)
        g=self.game(hero='hero.neutral')
        with self.assertRaisesRegex(ValueError,'playable hero class'):self.fact(g)

    def test_opponent_unknown_hand_is_not_inspected_or_counted(self):
        g=self.game(enemy_hand=('mage','unknown'));self.assertEqual(self.fact(g).amount,4)
        self.assertFalse(hand_has_other_class(g.state,g.registry,1));self.portable(g)

    def test_gain_and_loss_reprice_without_permanent_discount_attachment(self):
        g=self.game((CARD,'gain','lose'));self.assertEqual(self.fact(g).amount,4)
        self.cast(g,'gain');self.assertEqual(self.fact(g).amount,0);self.cast(g,'lose');self.assertEqual(self.fact(g).amount,4)
        self.assertFalse(self.source(g).enchantments);self.portable(g)

    def test_current_hero_class_changes_and_keep_class_policy_are_reused(self):
        for name,amount,clazz in (('hero',0,CardClass.MAGE),('keep',4,CardClass.ROGUE)):
            with self.subTest(name=name):
                g=self.game((CARD,name));self.cast(g,name);self.assertEqual(self.fact(g).amount,amount)
                self.assertEqual(g.state.players[1].hero_class,clazz);self.portable(g)

    def test_intrinsic_assignment_precedes_original_local_and_external_layers(self):
        g=self.game((CARD,'mage','local','tax'));self.cast(g,'local');self.cast(g,'tax')
        self.assertEqual(self.fact(g).amount,3);self.cast(g);self.assertEqual(g.state.players[1].mana,7);self.portable(g)

    def test_real_payer_pays_once_and_native_damage_stays_four(self):
        for other,price in (((),4),(('mage',),0)):
            with self.subTest(other=other):
                g=self.game((CARD,*other));self.cast(g)
                self.assertEqual(g.state.players[1].mana,10-price);self.assertEqual(g.state.entities[g.state.players[2].board[0]].damage,4)
                self.assertEqual(len(g.state.cost_use_history),1);self.assertEqual(g.state.cost_use_history[0].amount,price);self.portable(g)

    def test_insufficient_mana_and_wrong_target_preserve_full_transaction(self):
        g=self.game(mana=0);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.cast(g)
        self.assertEqual(g.snapshot(),before)
        g=self.game((CARD,'mage'));before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,self.source(g).id,g.state.players[2].hero_id))
        self.assertEqual(g.snapshot(),before)

    def test_copy_and_transfer_recompute_actual_payer_hand_class(self):
        g=self.game((CARD,'mage','copy'));self.cast(g,'copy')
        self.assertEqual(sum(g.state.entities[i].card_id==CARD for i in g.state.players[1].hand),2)
        self.assertEqual(self.fact(g).amount,0);self.portable(g)
        g=self.game((CARD,'mage','transfer'));self.cast(g,'transfer');self.assertEqual(self.fact(g,2).amount,4);self.portable(g)

    def test_waiting_payment_later_hand_loss_keeps_original_accepted_price(self):
        g=self.game((CARD,'mage'),board=('watch',));self.cast(g);self.assertIsNotNone(g.state.pending_choice)
        original=g.state.play_history[-1].submitted_cost.quote.intrinsic;self.assertTrue(original.condition_facts[0].matched)
        restored=self.portable(g)
        for branch in (g,restored):
            self.choose(branch,'lose');self.assertEqual(branch.state.players[1].mana,10)
            self.assertEqual(branch.state.entities[branch.state.players[2].board[0]].damage,4)
            validate_intrinsic_history_prefix(original,branch.state,branch.registry);self.portable(branch)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_waiting_payment_later_hero_class_does_not_reprice_original_match(self):
        g=self.game((CARD,'mage'),board=('watch',));self.cast(g)
        original=g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.choose(g,'hero');self.assertEqual(g.state.players[1].hero_class,CardClass.MAGE)
        self.assertEqual(original.condition_facts[0].hero_class,CardClass.ROGUE)
        validate_intrinsic_history_prefix(original,g.state,g.registry);self.portable(g)

    def test_choice_failure_preserves_original_quote_and_hand(self):
        g=self.game((CARD,'mage'),board=('watch',));self.cast(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_original_window_and_standalone_frame_reject_changed_row_truth(self):
        g=self.game((CARD,'mage','neutral'));fact=self.fact(g);condition=fact.intrinsic.condition_facts[0]
        validate_intrinsic_origin(fact.intrinsic,g.state,g.registry)
        forged=replace(condition,rows=(replace(condition.rows[0],matched=True),*condition.rows[1:]))
        with self.assertRaises(ValueError):validate_hand_other_class_match(forged,g.registry)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(condition)),condition)
        with self.assertRaises(ValueError):codec.encode(forged)
        cropped=replace(condition,rows=condition.rows[:-1])
        with self.assertRaises(ValueError):validate_intrinsic_origin(replace(fact.intrinsic,condition_facts=(cropped,)),g.state,g.registry)

    def test_json_stage_and_original_context_keep_complete_private_inventory(self):
        g=self.game((CARD,'mage','neutral','lose'));source=self.source(g);context=RuleContext(g.state,source.id,1)
        fact=self.fact(g);wire=json.loads(json.dumps(asdict(fact.intrinsic)))
        self.assertEqual(_intrinsic_stage_from_dict(wire),fact.intrinsic)
        self.cast(g,'lose');self.assertEqual(self.fact(g).amount,4)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);restored=codec.decode(codec.encode(context))
        self.assertTrue(capture_hand_other_class(restored.state,g.registry,1).matched)
        missing=deepcopy(wire);del missing['condition_facts'][0]['hero_class']
        with self.assertRaises(ValueError):_intrinsic_stage_from_dict(missing)

    def test_rehashed_paid_receipt_rejects_changed_class_truth_future_and_cropped_hand(self):
        g=self.game((CARD,'mage','neutral'));self.cast(g);saved=g.snapshot()
        for mode in ('truth','class','future','crop','duplicate'):
            with self.subTest(mode=mode):
                bad=deepcopy(saved);condition=bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['condition_facts'][0]
                if mode=='truth':condition['rows'][0]['matched']=True
                elif mode=='class':condition['hero_class']='mage'
                elif mode=='future':condition['rows'][0]['entity_id']=condition['next_entity_id']
                elif mode=='crop':condition['rows'].pop()
                else:condition['rows'].append(deepcopy(condition['rows'][0]))
                self.reject(bad)

    def test_query_and_player_interfaces_are_pure_and_hide_condition_rows(self):
        g=self.game((CARD,'mage'));before=g.snapshot()
        self.assertTrue(hand_has_other_class(g.state,g.registry,1))
        self.assertEqual(self.condition(g),capture_hand_other_class(g.state,g.registry,1))
        for p in (1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.for_player(p).legal_actions())
            for key in ('condition_facts','current-other-class','HandOtherClassRow','next_entity_id','resolution_frame'):
                self.assertNotIn('"'+key+'"',public)
        self.assertEqual(g.snapshot(),before)
