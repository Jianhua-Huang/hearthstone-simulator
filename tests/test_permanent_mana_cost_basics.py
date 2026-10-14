"""Permanent Mana-Crystal conditions use the original quote and payment window."""
from dataclasses import asdict,replace
import json
from pathlib import Path
import unittest
from copy import deepcopy
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,CostSpec,Game,
    IntrinsicCostSpec,PlayerSetup,PlayCard,Registry,ResolutionError,Scenario,SelectChoice,TriggerSpec,TargetSpec,SnapshotError)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input,capture_quote_fact,capture_generated_quote_fact
from hs_sim.engine.effects import (AddCostModifier,ChangeManaCrystals,ChoiceOption,Damage,
    GainTemporaryMana,InvokeBehavior,RequestChoice)
from hs_sim.engine.intrinsic_costs import validate_intrinsic_origin,validate_intrinsic_history_prefix
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import _intrinsic_stage_from_dict
from hs_sim.targets import canonical_digest

NATIVE='BT_134'
PIN='08a81c636d591309f59a4f5a8e904aae1e877b5683b6bc14c318c7bfc2fe2b79'
SUPPORT=Path(__file__).resolve().parents[1]/'data/support/mana-threshold-cost-basics.json'

def specification():
    return IntrinsicCostSpec(set_to=0,condition='permanent_mana_at_least',
        history_profile_id='mana.permanent-crystals-v1',mana_crystals=7)

def registry():
    support=json.loads(SUPPORT.read_bytes())
    if canonical_digest(support)!=PIN:raise ValueError('Permanent mana raw evidence changed')
    raw=support['records'][0]['data']
    if canonical_digest(raw)!=support['records'][0]['data_sha256']:raise ValueError('Native raw changed')
    r=Registry('permanent-mana-price-basics-v1')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=30,
        metadata=CardMetadata(False,(CardClass.DRUID,),None)))
    r.register_card(CardDefinition('body','Body',CardType.MINION,attack=1,health=12))
    r.register_behavior('beam',lambda c:(Damage(c.target_id,3,c.source_id),))
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.SPELL,cost=raw['cost'],on_play='beam',
        targeting=TargetSpec(kinds=(CardType.MINION,)),intrinsic_costs=(specification(),)))
    for name,fn in (
        ('temporary',lambda c:(GainTemporaryMana(c.player_id,4),)),
        ('up',lambda c:(ChangeManaCrystals(c.player_id,1,True),)),
        ('down',lambda c:(ChangeManaCrystals(c.player_id,-2),)),
        ('tax',lambda c:(AddCostModifier(c.player_id,CostSpec(delta=1,card_ids=(NATIVE,))),))):
        r.register_behavior(name,fn);r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name))
    def wait(c):
        if c.state.entities[c.event.source_id].card_id!=NATIVE:return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('up','Up',(ChangeManaCrystals(c.player_id,1,True),)),
            ChoiceOption('down','Down',(ChangeManaCrystals(c.player_id,-2),)),
            ChoiceOption('fail','Fail',(InvokeBehavior('fail',c.source_id,c.player_id),)),
        ),c.source_id),)
    r.register_behavior('wait',wait)
    r.register_behavior('fail',lambda c:(_ for _ in ()).throw(ValueError('Mana choice fixture failure')))
    r.register_card(CardDefinition('watch','Watch',CardType.MINION,health=2,
        triggers=(TriggerSpec('card_committed','wait'),)))
    return r

class PermanentManaCostTests(unittest.TestCase):
    def game(self,maximum=7,mana=None,hand=(NATIVE,),board=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,max_mana=maximum,mana=maximum if mana is None else mana),
            PlayerSetup('hero',board=('body',),max_mana=10,mana=10)),seed=91),registry())
    def source(self,g,name=NATIVE):
        return next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
    def play(self,g,name=NATIVE):
        return g.apply(PlayCard(1,self.source(g,name).id,g.state.players[2].board[0]if name==NATIVE else None))
    def fact(self,g):
        return capture_quote_fact(g.state,g.registry,capture_cost_input(self.source(g)))
    def check(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,registry()).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        return saved
    def test_native_threshold_is_a_cost_condition_not_a_new_card_face(self):
        g=self.game(6);self.assertEqual(self.fact(g).amount,3)
        g=self.game(7);self.assertEqual(self.fact(g).amount,0)
        self.assertEqual(self.source(g).card_id,NATIVE);self.check(g)
    def test_spent_available_mana_does_not_remove_permanent_crystals(self):
        g=self.game(7,mana=0);self.assertEqual(self.fact(g).amount,0)
        self.play(g);self.assertEqual(g.state.players[1].mana,0)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,9);self.check(g)
    def test_temporary_mana_does_not_satisfy_the_permanent_threshold(self):
        g=self.game(6,hand=(NATIVE,'temporary'));self.play(g,'temporary')
        self.assertEqual(g.state.players[1].max_mana,6);self.assertEqual(g.state.players[1].mana,10)
        self.assertEqual(self.fact(g).amount,3);self.check(g)
    def test_gaining_and_losing_permanent_crystals_reprices_without_attachments(self):
        g=self.game(6,hand=(NATIVE,'up','down'));self.play(g,'up')
        self.assertEqual(self.fact(g).amount,0);self.play(g,'down');self.assertEqual(self.fact(g).amount,3)
        self.assertFalse(self.source(g).enchantments);self.check(g)
    def test_external_cost_operation_still_follows_the_intrinsic_condition(self):
        g=self.game(7,hand=(NATIVE,'tax'));self.play(g,'tax')
        self.assertEqual((self.fact(g).intrinsic.amount,self.fact(g).amount),(0,1));self.play(g)
        self.assertEqual(g.state.play_history[-1].cost,1);self.check(g)
    def waiting(self,maximum,option,old_amount,new_amount):
        g=self.game(maximum,hand=(NATIVE,NATIVE),board=('watch',));self.play(g)
        record=g.state.play_history[-1];old=record.submitted_cost.quote.intrinsic
        self.assertEqual(record.cost,old_amount);saved=self.check(g)
        peers=(Game.from_snapshot(saved,registry()),g.clone(),replay(build_replay(g),registry()))
        choice=SelectChoice(1,g.state.pending_choice.id,(option,));g.apply(choice)
        for peer in peers:peer.apply(choice);self.assertEqual(peer.snapshot(),g.snapshot())
        self.assertEqual(g.state.play_history[-1].cost,old_amount)
        self.assertEqual(self.fact(g).amount,new_amount)
        validate_intrinsic_history_prefix(old,g.state,g.registry)
        with self.assertRaises(ValueError):validate_intrinsic_origin(old,g.state,g.registry)
        self.check(g)
    def test_original_false_quote_survives_later_threshold_gain(self):
        self.waiting(6,'up',3,0)
    def test_original_true_quote_survives_later_crystal_loss(self):
        self.waiting(7,'down',0,3)
    def test_failed_wait_selection_preserves_payment_and_original_resource_operand(self):
        g=self.game(7,board=('watch',));self.play(g);saved=self.check(g)
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,g.state.pending_choice.id,('fail',)))
        self.assertEqual(g.snapshot(),saved);self.check(g)
    def test_physical_generated_and_explicit_floor_quotes_are_pure(self):
        g=self.game(7);saved=g.snapshot();physical=self.fact(g)
        generated=capture_generated_quote_fact(g.state,g.registry,1,NATIVE)
        minimum=capture_generated_quote_fact(g.state,g.registry,1,NATIVE,minimum_cost=2)
        self.assertEqual((physical.amount,generated.amount,minimum.amount),(0,0,2))
        self.assertEqual(physical.intrinsic,generated.intrinsic)
        self.assertEqual(g.snapshot(),saved);self.check(g)
    def test_original_window_rejects_a_self_consistent_false_resource_operand(self):
        g=self.game(7);stage=self.fact(g).intrinsic;condition=stage.condition_facts[0]
        changed=replace(condition,maximum=8)
        with self.assertRaises(ValueError):
            validate_intrinsic_origin(replace(stage,condition_facts=(changed,)),g.state,g.registry)
    def test_stage_json_typed_codec_and_player_information_boundaries(self):
        g=self.game(7);stage=self.fact(g).intrinsic
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(stage)),stage)
        self.assertEqual(_intrinsic_stage_from_dict(json.loads(json.dumps(asdict(stage)))),stage)
        self.assertNotIn('condition_facts',json.dumps(g.observe(1))+json.dumps(g.observe(2)))
        self.check(g)
    def test_resource_threshold_and_original_operand_types_are_strict(self):
        for value in (True,-1,7.0,None):
            with self.assertRaises(ValueError):replace(specification(),mana_crystals=value)
        g=self.game(7);condition=self.fact(g).intrinsic.condition_facts[0]
        for value in (True,-1,7.0):
            with self.assertRaises(ValueError):replace(condition,maximum=value)
    def test_missing_original_operand_and_missing_spec_field_are_rejected(self):
        g=self.game(7);wire=json.loads(json.dumps(asdict(self.fact(g).intrinsic)))
        missing=deepcopy(wire);missing['condition_facts'][0].pop('maximum')
        with self.assertRaises(ValueError):_intrinsic_stage_from_dict(missing)
        missing=deepcopy(wire);missing['rules'][0].pop('mana_crystals')
        with self.assertRaises(ValueError):_intrinsic_stage_from_dict(missing)
    def test_new_wire_rejects_prior_schema_without_migrating_resource_facts(self):
        g=self.game(7);saved=g.snapshot();self.assertEqual(saved['schema_version'],266)
        for old in (*range(1, saved['schema_version']), saved['schema_version'] + 1, True):
            changed=deepcopy(saved);changed['schema_version']=old
            with self.assertRaises(SnapshotError):Game.from_snapshot(changed,registry())

if __name__=='__main__':unittest.main()
