"""Last original paid hand Cost reuses the existing physical-play price consumer."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, CostSpec, EndTurn, Game, IllegalAction,
    PaymentType, PlayCard, PlayerPlayedClassCostSpec, PlayerSetup, ResolutionError,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, UseHeroPower)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input, capture_generated_quote_fact, capture_quote_fact
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, InvokeBehavior,
    ModifyCost, RequestChoice, ReturnToHand)
from hs_sim.engine.intrinsic_costs import (validate_intrinsic_history_prefix,
    validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import _intrinsic_stage_from_dict
from hs_sim.targets import canonical_digest
import test_player_played_class_cost_basics as old

NATIVE='CATA_616';PROFILE='cost.player-last-played-cost-v1'
SUPPORT=Path(__file__).resolve().parents[1]/'data/support/last-played-cost-basics.json'
PIN='4a6170e9724712319450c72e25d80da6f32bc27940bfd0b2390bbdd859794f13'


def evidence():
    value=json.loads(SUPPORT.read_bytes())
    if canonical_digest(value)!=PIN:raise ValueError('Last-play Cost evidence changed')
    row=value['records'][0]
    if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Last-play Cost original raw changed')
    return row['data']


def registry(*,wait=False):
    r=old.registry();raw=evidence()
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.MINION,cost=raw['cost'],
        attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw),
        player_played_class_cost=PlayerPlayedClassCostSpec(card_class=None,profile_id=PROFILE)))
    for cid,cost,body in (('last.four',4,'class.noop'),('last.ten',10,'class.noop'),
                          ('last.wait',4,'class.wait')):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=body,metadata=old.metadata()))
    r.register_card(CardDefinition('last.two','Ordinary two-cost physical minion',CardType.MINION,
        cost=2,health=2,metadata=old.metadata()))
    r.register_behavior('last.acquire',lambda c:(AddToHand(c.player_id,NATIVE),))
    r.register_card(CardDefinition('last.acquire','Acquire after original commitment',CardType.SPELL,
        cost=4,on_play='last.acquire',metadata=old.metadata()))
    held=lambda c:next(e for e in c.state.players[c.player_id].hand if c.state.entities[e].card_id==NATIVE)
    def return_native(c):
        eid=next(e for e in c.state.players[c.player_id].board if c.state.entities[e].card_id==NATIVE)
        return (ReturnToHand(eid),)
    scripts={
        'last.reduce':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-3,card_ids=('last.four',))),),
        'last.health':lambda c:(AddCostModifier(c.player_id,CostSpec(payment=PaymentType.HEALTH,card_ids=('last.four',))),),
        'last.local':lambda c:(ModifyCost(held(c),CostSpec(set_to=6)),),
        'last.external':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-2,card_ids=(NATIVE,))),),
        'last.return':return_native,
    }
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,
            on_play=cid,metadata=old.metadata()))
    r.register_behavior('last.fail',lambda c:(AddToHand(c.player_id,'missing.last.play.cost'),))
    def pause(c):
        if c.state.entities[c.event.source_id].card_id!=NATIVE:return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('continue','Continue original paid root'),
            ChoiceOption('fault','Delayed failure',(InvokeBehavior('last.fail',c.source_id,c.player_id),)),
        ),c.source_id),)
    if wait:
        r.register_behavior('last.pause',pause)
        r.register_card(CardDefinition('last.watch','Original payment observer',CardType.MINION,health=3,
            triggers=(TriggerSpec('card_committed','last.pause'),),metadata=old.metadata()))
    return r


class LastPlayedCostTests(unittest.TestCase):
    def setUp(self):self.options={}

    def game(self,hand=(NATIVE,),*,enemy_hand=(),board=(),enemy_board=(),mana=10):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero',hand=hand,board=board,deck=('card.1',)*4,
                mana=mana,max_mana=10,hero_power_card_id='mage.power'),
            PlayerSetup('warrior.hero',hand=enemy_hand,board=enemy_board,deck=('card.1',)*4,
                mana=10,max_mana=10,hero_power_card_id='warrior.power')),seed=63),registry(**self.options))

    def source(self,g,cid=NATIVE,player=1):
        return next(g.state.entities[e] for e in g.state.players[player].hand if g.state.entities[e].card_id==cid)

    def fact(self,g,player=1,cid=NATIVE):
        return capture_quote_fact(g.state,g.registry,capture_cost_input(self.source(g,cid,player)))

    def play(self,g,cid=NATIVE):
        p=g.state.active_player;eid=self.source(g,cid,p).id;g.apply(PlayCard(p,eid));return eid

    def choose(self,g,option='continue'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option,)))

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));restored=Game.from_snapshot(saved,registry(**self.options))
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(**self.options)).snapshot(),saved)
        for p in (1,2):self.assertEqual(restored.observe(p),g.observe(p))
        return restored

    def four(self,**kwargs):
        g=self.game((NATIVE,'last.four',*kwargs.pop('extras',())),**kwargs);self.play(g,'last.four');return g

    def test_native_raw_and_empty_prefix_keep_nine_mana_eight_eight(self):
        raw=evidence();source=next(r for r in json.loads((SUPPORT.parents[1]/'extracted/cards.json').read_bytes()) if r['id']==NATIVE)
        self.assertEqual(raw,source);g=self.game();f=self.fact(g).intrinsic.player_played_class
        self.assertEqual((f.rows,f.selected_ids,f.quantity,f.after),((),(),0,9))
        self.play(g);eid=g.state.players[1].board[0]
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(8,8));self.portable(g)

    def test_last_root_cost_is_not_total_count_or_sum(self):
        g=self.game((NATIVE,'last.four','last.two'));self.play(g,'last.four');self.play(g,'last.two')
        f=self.fact(g).intrinsic.player_played_class
        self.assertEqual((f.selected_ids,f.quantity,f.after,len(f.rows)),((2,),2,7,2))
        self.assertEqual([r.accepted_cost for r in f.rows],[4,2]);self.portable(g)

    def test_zero_cost_last_play_replaces_previous_discount(self):
        g=self.four(extras=('pal.free',));self.assertEqual(self.fact(g).amount,5);self.play(g,'pal.free')
        self.assertEqual((self.fact(g).amount,self.fact(g).intrinsic.player_played_class.selected_ids),(9,(2,)))
        self.portable(g)

    def test_discounted_previous_card_uses_original_accepted_not_printed_cost(self):
        g=self.game((NATIVE,'last.reduce','last.four'));self.play(g,'last.reduce');self.play(g,'last.four')
        self.assertEqual((g.registry.card('last.four').cost,g.state.play_history[-1].cost,self.fact(g).amount),(4,1,8))
        self.portable(g)

    def test_alternative_payment_account_keeps_the_original_numeric_cost(self):
        g=self.game((NATIVE,'last.health','last.four'));self.play(g,'last.health');self.play(g,'last.four')
        self.assertEqual((g.state.play_history[-1].payment,self.fact(g).amount,g.state.players[1].mana),(PaymentType.HEALTH,5,10))
        self.portable(g)

    def test_actual_payer_and_previous_turn_do_not_use_opponents_latest_root(self):
        g=self.four(enemy_hand=(NATIVE,'pal.two'));g.apply(EndTurn(1));self.play(g,'pal.two')
        self.assertEqual((self.fact(g).amount,self.fact(g,2).amount),(5,7))
        g.apply(EndTurn(2));self.assertEqual(self.fact(g).amount,5);self.portable(g)

    def test_getting_the_native_after_original_commitment_reads_player_history(self):
        g=self.game(('last.acquire',));self.play(g,'last.acquire')
        self.assertEqual(self.fact(g).amount,5);self.assertEqual(self.source(g).abilities,[]);self.portable(g)

    def test_countered_and_waiting_accepted_roots_keep_original_cost(self):
        g=self.game((NATIVE,'last.four'),enemy_board=('class.counter',));self.play(g,'last.four')
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(self.fact(g).amount,5);self.portable(g)
        g=self.game((NATIVE,'last.wait'));self.play(g,'last.wait')
        self.assertFalse(g.state.play_history[-1].completed);self.assertEqual(self.fact(g).amount,5)
        restored=self.portable(g)
        for current in (g,restored):self.choose(current)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_hero_power_does_not_replace_last_hand_root(self):
        g=self.four();g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual((self.fact(g).amount,self.fact(g).intrinsic.player_played_class.selected_ids),(5,(1,)))
        self.portable(g)

    def test_ten_cost_root_reaches_zero_floor_with_one_original_payment(self):
        g=self.game((NATIVE,'last.ten'));self.play(g,'last.ten');self.assertEqual(self.fact(g).amount,0)
        self.play(g);self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(0,0));self.portable(g)

    def test_own_payment_freezes_previous_root_then_affects_next_native_price(self):
        g=self.four(extras=(NATIVE,));self.play(g)
        played=g.state.play_history[-1];self.assertEqual((played.cost,played.submitted_cost.quote.intrinsic.player_played_class.quantity),(5,4))
        self.assertEqual(self.fact(g).amount,4);self.assertEqual(g.state.players[1].mana,1);self.portable(g)

    def test_return_and_repeated_quote_do_not_reapply_to_previous_original_cost(self):
        g=self.four(extras=('last.return',));self.play(g);accepted=g.state.play_history[-1].cost
        self.play(g,'last.return');before=g.snapshot()
        for _ in range(3):self.assertEqual(self.fact(g).amount,9)
        self.assertEqual((accepted,g.state.play_history[1].cost),(5,5));self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_local_and_external_layers_follow_last_cost_intrinsic_stage(self):
        g=self.game((NATIVE,'last.local','last.external','last.four'))
        for cid in ('last.local','last.external','last.four'):self.play(g,cid)
        f=self.fact(g);self.assertEqual((f.intrinsic.amount,f.local_amount,f.amount),(5,6,4));self.play(g)
        self.assertEqual(g.state.play_history[-1].cost,4);self.portable(g)

    def test_generated_and_physical_quotes_are_pure_and_use_same_last_root(self):
        g=self.four();before=g.snapshot();f=self.fact(g)
        generated=capture_generated_quote_fact(g.state,g.registry,1,NATIVE)
        self.assertEqual((generated.amount,generated.intrinsic.player_played_class),(5,f.intrinsic.player_played_class))
        g.legal_actions();self.assertEqual(g.snapshot(),before)

    def test_insufficient_payment_leaves_cost_prefix_rng_and_hand_unchanged(self):
        g=self.four(mana=8);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_waiting_native_restore_and_replay_keep_old_price_after_later_play(self):
        self.options=dict(wait=True);g=self.four(extras=('pal.free',),board=('last.watch',));self.play(g)
        stage=g.state.play_history[-1].submitted_cost.quote.intrinsic;restored=self.portable(g)
        for current in (g,restored):
            self.choose(current);self.play(current,'pal.free')
            validate_intrinsic_history_prefix(stage,current.state,current.registry)
            self.assertEqual(capture_generated_quote_fact(current.state,current.registry,1,NATIVE).amount,9)
            self.assertEqual(current.state.play_history[1].cost,5)
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_delayed_failure_rolls_back_to_the_original_paid_boundary(self):
        self.options=dict(wait=True);g=self.four(board=('last.watch',));self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_self_consistent_wrong_original_cost_fails_actual_origin_and_prefix(self):
        g=self.four();stage=self.fact(g).intrinsic;f=stage.player_played_class
        changed=replace(f,rows=(replace(f.rows[0],accepted_cost=3),),quantity=3,after=6)
        forged=replace(stage,player_played_class=changed,amount=6)
        validate_intrinsic_stage_fact(g.registry,forged)
        with self.assertRaises(ValueError):validate_intrinsic_origin(forged,g.state,g.registry)
        with self.assertRaises(ValueError):validate_intrinsic_history_prefix(forged,g.state,g.registry)

    def test_complete_selection_cannot_borrow_an_earlier_root_with_same_cost(self):
        g=self.four(extras=('last.four',));self.play(g,'last.four');f=self.fact(g).intrinsic.player_played_class
        with self.assertRaises(ValueError):replace(f,selected_ids=(1,))
        with self.assertRaises(ValueError):replace(f,rows=f.rows[:-1])
        with self.assertRaises(ValueError):replace(f,rows=(replace(f.rows[0],accepted_cost=True),f.rows[1]))

    def test_json_and_typed_prefix_require_explicit_original_cost(self):
        g=self.four();stage=self.fact(g).intrinsic;codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(stage)),stage)
        raw=json.loads(json.dumps(asdict(stage)));self.assertEqual(_intrinsic_stage_from_dict(raw),stage)
        del raw['player_played_class']['rows'][0]['accepted_cost']
        with self.assertRaises(ValueError):_intrinsic_stage_from_dict(raw)
        row=codec.encode(stage.player_played_class.rows[0]);del row['fields']['accepted_cost']
        with self.assertRaises((ValueError,SnapshotError)):codec.decode(row)

    def test_rehashed_history_cannot_rewrite_original_cost_for_same_zero_price(self):
        g=self.game((NATIVE,'last.ten'));self.play(g,'last.ten');self.play(g);saved=g.snapshot();bad=deepcopy(saved)
        f=bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['player_played_class']
        f['rows'][0]['accepted_cost']=11;f['quantity']=11
        with self.assertRaises(SnapshotError):Game.from_snapshot(old.rehash(bad),registry())

    def test_player_price_does_not_leak_complete_prefix_or_opponent_hand(self):
        g=self.four(enemy_hand=(NATIVE,));view=g.observe(1)
        self.assertEqual(view['players'][0]['hand'][0]['cost']['amount'],5)
        self.assertIsNone(view['players'][1]['hand'][0]['card_id'])
        for key in ('accepted_cost','selected_ids','player_played_class','submitted_cost','play_history_length'):
            self.assertNotIn(key,json.dumps(view))
        self.portable(g)

    def test_profile_is_finite_unfiltered_and_ordinary_minion_only(self):
        for kwargs in ({'profile_id':PROFILE}, {'card_class':None,'profile_id':'all.last.sources'}):
            with self.assertRaises(ValueError):PlayerPlayedClassCostSpec(**kwargs)
        r=registry()
        with self.assertRaises(ValueError):r.register_card(replace(r.card(NATIVE),id='bad.last.spell',kind=CardType.SPELL,health=0))
