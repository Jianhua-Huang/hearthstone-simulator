"""A real all-game character declaration price uses the original cost pipeline."""
from copy import deepcopy
from dataclasses import asdict,replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack,CardClass,CardDefinition,CardType,CostSpec,EndTurn,Game,
    IllegalAction,Keyword,PlayCard,PlayerSetup,Rarity,Registry,ResolutionError,Scenario,
    SelectChoice,SnapshotError,SpellSchool,TriggerSpec)
from hs_sim.engine import model
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input,capture_generated_quote_fact,capture_quote_fact
from hs_sim.engine.effects import (AddCostModifier,AddToHand,ChangeControl,ChoiceOption,Draw,
    ForceAttack,Freeze,InvokeBehavior,ModifyCost,RequestChoice,Transform)
from hs_sim.engine.intrinsic_costs import (validate_intrinsic_history_prefix,
    validate_intrinsic_origin,validate_intrinsic_stage_fact)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import _intrinsic_stage_from_dict,canonical_hash
from hs_sim.targets import canonical_digest

NATIVE='CATA_568'
SUPPORT=Path(__file__).resolve().parents[1]/'data/support/player-character-attack-cost-basics.json'
PIN='e949aae78bc5c3f013505d9821f82fa1e595edb1741479ed0a3180b7a8c012a8'


def evidence():
    value=json.loads(SUPPORT.read_bytes())
    if canonical_digest(value)!=PIN:raise ValueError('Character declaration price evidence changed')
    row=value['records'][0]
    if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Character declaration price complete raw changed')
    return row['data']


def registry(*,wait=False,freeze=False,attack_wait=False):
    r=Registry('character-declaration-price-basics-v1');raw=evidence()
    r.register_card(CardDefinition('hero','Fixture hero',CardType.HERO,attack=2,health=100))
    r.register_card(CardDefinition('plain','Fixture minion',CardType.MINION,attack=1,health=30,keywords=(Keyword.CHARGE,)))
    r.register_card(CardDefinition('wind','Fixture Windfury minion',CardType.MINION,attack=1,health=30,keywords=(Keyword.CHARGE,Keyword.WINDFURY)))
    r.register_card(CardDefinition('shield','Fixture shield',CardType.MINION,health=30,keywords=(Keyword.DIVINE_SHIELD,)))
    r.register_behavior('attackprice.native',lambda c:(Draw(c.player_id,2,source_id=c.source_id),))
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.SPELL,cost=raw['cost'],spell_school=SpellSchool.NATURE,
        on_play='attackprice.native',metadata=metadata_from_record(raw),
        player_character_attack_cost=model.PlayerCharacterAttackCostSpec()))
    held=lambda c:next(e for e in c.state.players[c.player_id].hand if c.state.entities[e].card_id==NATIVE)
    body=lambda c:c.state.players[c.player_id].board[0]
    scripts={
        'attackprice.force':lambda c:(ForceAttack(body(c),c.state.players[2].hero_id),),
        'attackprice.acquire':lambda c:(AddToHand(c.player_id,NATIVE),),
        'attackprice.control':lambda c:(ChangeControl(body(c),2),),
        'attackprice.transform':lambda c:(Transform(body(c),'wind'),),
        'attackprice.local':lambda c:(ModifyCost(held(c),CostSpec(set_to=6)),),
        'attackprice.external':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-2,card_ids=(NATIVE,))),),
    }
    for cid,handler in scripts.items():
        r.register_behavior(cid,handler);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    r.register_behavior('attackprice.fail',lambda c:(AddToHand(c.player_id,'missing.attack.price.fixture'),))
    def pause(c):
        if c.state.entities[c.event.source_id].card_id!=NATIVE:return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('continue','Continue original paid spell'),
            ChoiceOption('more','Later declaration affects future prices',
                (ForceAttack(body(c),c.state.players[2].hero_id),AddToHand(c.player_id,NATIVE))),
            ChoiceOption('fault','Delayed failure',(InvokeBehavior('attackprice.fail',c.source_id,c.player_id),)),
        ),c.source_id),)
    if wait:
        r.register_behavior('attackprice.pause',pause)
        r.register_card(CardDefinition('attackprice.watch','Payment observer',CardType.MINION,health=30,
            triggers=(TriggerSpec('card_committed','attackprice.pause'),)))
    if freeze:
        r.register_behavior('attackprice.freeze',lambda c:(Freeze(c.event.source_id),))
        r.register_card(CardDefinition('attackprice.freeze','Cancellation observer',CardType.MINION,health=30,
            triggers=(TriggerSpec('attack_declared','attackprice.freeze'),)))
    if attack_wait:
        r.register_behavior('attackprice.wait',lambda c:(RequestChoice(1,(ChoiceOption('continue','Finish original attack'),),c.source_id),))
        r.register_card(CardDefinition('attackprice.wait','Declaration observer',CardType.MINION,health=30,
            triggers=(TriggerSpec('attack_declared','attackprice.wait'),)))
    return r


def rehash(value):
    value['events_hash']=canonical_hash(value['events'])
    value['state_hash']=canonical_hash({k:v for k,v in value.items() if k not in ('schema_version','events','events_hash','state_hash')})
    return value


class PlayerCharacterAttackCostTests(unittest.TestCase):
    def setUp(self):self.options={}
    def game(self,hand=(NATIVE,),*,board=('plain',),enemy=(),enemy_hand=(),mana=10):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*6,mana=mana,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,board=enemy,deck=('plain',)*6,mana=10,max_mana=10)),seed=65),registry(**self.options))
    def source(self,g,cid=NATIVE,p=1):return next(g.state.entities[e] for e in g.state.players[p].hand if g.state.entities[e].card_id==cid)
    def fact(self,g,p=1):return capture_quote_fact(g.state,g.registry,capture_cost_input(self.source(g,p=p)))
    def hit(self,g,p=1,*,hero=False,target=None):
        eid=g.state.players[p].hero_id if hero else g.state.players[p].board[0]
        g.apply(Attack(p,eid,target or g.state.players[3-p].hero_id))
    def play(self,g,cid=NATIVE):
        p=g.state.active_player;g.apply(PlayCard(p,self.source(g,cid,p).id))
    def choose(self,g,key='continue'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));restored=Game.from_snapshot(saved,registry(**self.options))
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(**self.options)).snapshot(),saved)
        for p in (1,2):self.assertEqual(restored.observe(p),g.observe(p))
        return restored
    def one(self,**kwargs):
        g=self.game(**kwargs);self.hit(g);return g

    def test_real_shaman_nature_rare_face_and_complete_draw_two_body(self):
        raw=evidence();source=next(r for r in json.loads((SUPPORT.parents[1]/'extracted/cards.json').read_bytes()) if r['id']==NATIVE)
        self.assertEqual(raw,source);g=self.game();d=g.registry.card(NATIVE)
        self.assertEqual((d.cost,d.spell_school,d.metadata.classes,d.metadata.rarity),(9,SpellSchool.NATURE,(CardClass.SHAMAN,),Rarity.RARE))
        self.play(g);self.assertEqual((len(g.state.players[1].hand),len(g.state.draw_history),g.state.play_history[-1].cost),(2,2,9));self.portable(g)

    def test_completed_hero_and_minion_declarations_each_reduce_once(self):
        g=self.one();self.hit(g,hero=True);f=self.fact(g).intrinsic.player_character_attacks
        self.assertEqual((f.quantity,f.before,f.after,len(f.records)),(2,9,7,2))
        self.assertTrue(all(r.delivery is None and r.combat is None and r.terminal is None for r in f.records))
        self.play(g);self.assertEqual(g.state.players[1].mana,3);self.portable(g)

    def test_each_windfury_attack_is_one_window_not_damage_packet(self):
        g=self.game(board=('wind',));self.hit(g);self.hit(g)
        self.assertEqual((self.fact(g).amount,len(self.fact(g).intrinsic.player_character_attacks.records)),(7,2));self.portable(g)

    def test_unchanged_original_payer_across_turns_excludes_opponent(self):
        g=self.one(enemy=('plain',),enemy_hand=(NATIVE,));g.apply(EndTurn(1));self.hit(g,2);g.apply(EndTurn(2));self.hit(g)
        self.assertEqual((self.fact(g).amount,self.fact(g,2).amount),(7,8));self.portable(g)

    def test_declarations_before_acquisition_are_not_held_progress(self):
        g=self.game(hand=('attackprice.acquire',));self.hit(g);self.play(g,'attackprice.acquire')
        self.assertEqual(self.fact(g).amount,8);self.portable(g)

    def test_forced_minion_window_counts_without_opportunity_consumption(self):
        g=self.game(hand=(NATIVE,'attackprice.force'));self.play(g,'attackprice.force')
        self.assertEqual((self.fact(g).amount,g.state.entities[g.state.players[1].board[0]].attacks_this_turn),(8,0));self.portable(g)

    def test_cancelled_after_declaration_keeps_explicit_internal_credit(self):
        self.options=dict(freeze=True);g=self.one(board=('plain','attackprice.freeze'))
        self.assertEqual(g.state.character_attack_history[0].terminal.status,'cancelled');self.assertEqual(self.fact(g).amount,8);self.portable(g)

    def test_shield_damage_prevention_does_not_turn_attack_units_into_damage_units(self):
        g=self.game(enemy=('shield',));self.hit(g,target=g.state.players[2].board[0])
        self.assertEqual(self.fact(g).amount,8);self.portable(g)

    def test_original_source_control_and_transform_do_not_rewrite_price_credit(self):
        g=self.one(hand=(NATIVE,'attackprice.control'));self.play(g,'attackprice.control');self.assertEqual(self.fact(g).amount,8);self.portable(g)
        g=self.one(hand=(NATIVE,'attackprice.transform'));self.play(g,'attackprice.transform');self.assertEqual(self.fact(g).amount,8);self.portable(g)

    def test_accepted_declaration_wait_can_finish_after_an_original_quote(self):
        self.options=dict(attack_wait=True);g=self.one(board=('plain','attackprice.wait'));stage=self.fact(g).intrinsic
        self.assertEqual(stage.amount,8);restored=self.portable(g)
        for current in (g,restored):
            self.choose(current);validate_intrinsic_history_prefix(stage,current.state,current.registry)
            self.assertEqual(self.fact(current).amount,8)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_waiting_payment_keeps_frozen_count_after_new_real_declaration(self):
        self.options=dict(wait=True);g=self.one(board=('plain','attackprice.watch'));self.play(g)
        stage=g.state.play_history[-1].submitted_cost.quote.intrinsic;restored=self.portable(g)
        for current in (g,restored):
            self.choose(current,'more');validate_intrinsic_history_prefix(stage,current.state,current.registry)
            self.assertEqual((self.fact(current).amount,current.state.play_history[-1].cost,current.state.players[1].mana),(7,8,2))
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_failed_choice_restores_original_payment_draws_and_attack_history(self):
        self.options=dict(wait=True);g=self.one(board=('plain','attackprice.watch'));self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_physical_and_generated_quotes_are_pure_and_share_full_declarations(self):
        g=self.one();before=g.snapshot();f=self.fact(g)
        generated=capture_generated_quote_fact(g.state,g.registry,1,NATIVE)
        self.assertEqual((generated.amount,generated.intrinsic.player_character_attacks),(8,f.intrinsic.player_character_attacks))
        g.legal_actions();self.assertEqual(g.snapshot(),before)

    def test_local_external_and_minimum_layers_keep_the_original_intrinsic_count(self):
        g=self.one(hand=(NATIVE,'attackprice.local','attackprice.external'));self.play(g,'attackprice.local');self.play(g,'attackprice.external')
        f=self.fact(g);self.assertEqual((f.intrinsic.amount,f.local_amount,f.amount),(8,6,4))
        minimum=capture_quote_fact(g.state,g.registry,capture_cost_input(self.source(g),minimum_cost=7));self.assertEqual(minimum.amount,7)
        self.play(g);self.assertEqual(g.state.play_history[-1].cost,4);self.portable(g)

    def test_insufficient_mana_rejects_without_changes_to_history_or_rng(self):
        g=self.one(mana=7);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_nine_real_windows_reach_zero_floor_with_one_native_payment(self):
        g=self.game(hand=(NATIVE,*('attackprice.force',)*9))
        for _ in range(9):self.play(g,'attackprice.force')
        self.assertEqual((self.fact(g).amount,self.fact(g).intrinsic.player_character_attacks.quantity),(0,9))
        self.play(g);self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(0,10));self.portable(g)

    def test_self_consistent_forged_original_player_rejects_actual_origin(self):
        g=self.one();stage=self.fact(g).intrinsic;f=stage.player_character_attacks
        row=replace(f.records[0],declaration=replace(f.records[0].declaration,player_id=2))
        forged=replace(stage,player_character_attacks=replace(f,records=(row,),quantity=0,after=9),amount=9)
        validate_intrinsic_stage_fact(g.registry,forged)
        with self.assertRaises(ValueError):validate_intrinsic_origin(forged,g.state,g.registry)
        with self.assertRaises(ValueError):validate_intrinsic_history_prefix(forged,g.state,g.registry)

    def test_declaration_prefix_rejects_later_phase_injection_wrong_count_and_future_window(self):
        g=self.one();f=self.fact(g).intrinsic.player_character_attacks;full=g.state.character_attack_history[0]
        for changes in ({'records':(full,)},{'quantity':2,'after':7},{'next_window_id':f.records[0].declaration.id}):
            with self.subTest(fields=tuple(changes)),self.assertRaises(ValueError):replace(f,**changes)

    def test_same_action_unselected_tail_cannot_be_cropped_with_the_same_quantity(self):
        r=registry()
        r.register_behavior('attackprice.both',lambda c:(
            ForceAttack(c.state.players[1].board[0],c.state.players[2].hero_id),
            ForceAttack(c.state.players[2].board[0],c.state.players[1].hero_id)))
        r.register_card(CardDefinition('attackprice.both','Both original declarations in one action',CardType.SPELL,on_play='attackprice.both'))
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=(NATIVE,'attackprice.both'),board=('plain',),mana=10,max_mana=10),
            PlayerSetup('hero',board=('plain',),mana=10,max_mana=10)),seed=65),r)
        self.play(g,'attackprice.both');stage=self.fact(g).intrinsic;f=stage.player_character_attacks
        self.assertEqual((f.quantity,len(f.records)),(1,2))
        self.assertEqual(f.records[0].declaration_action,f.records[1].declaration_action)
        forged=replace(stage,player_character_attacks=replace(f,records=f.records[:1]))
        validate_intrinsic_stage_fact(g.registry,forged)
        with self.assertRaises(ValueError):validate_intrinsic_history_prefix(forged,g.state,g.registry)

    def test_dictionary_and_typed_frames_require_the_new_private_leaf(self):
        g=self.one();stage=self.fact(g).intrinsic;codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(stage)),stage)
        raw=json.loads(json.dumps(asdict(stage)));self.assertEqual(_intrinsic_stage_from_dict(raw),stage)
        del raw['player_character_attacks']
        with self.assertRaises(ValueError):_intrinsic_stage_from_dict(raw)
        encoded=codec.encode(stage);del encoded['fields']['player_character_attacks']
        with self.assertRaises((ValueError,SnapshotError)):codec.decode(encoded)

    def test_rehashed_snapshot_cannot_trim_a_paid_declaration_prefix(self):
        g=self.one();self.play(g);bad=deepcopy(g.snapshot())
        f=bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['player_character_attacks']
        f['records']=[];f['quantity']=0;f['after']=9
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())

    def test_player_prices_keep_original_declarations_and_opponent_hand_private(self):
        g=self.one(enemy_hand=(NATIVE,));view=g.observe(1)
        self.assertEqual(view['players'][0]['hand'][0]['cost']['amount'],8);self.assertIsNone(view['players'][1]['hand'][0]['card_id'])
        for key in ('player_character_attacks','character_attack_history','declaration_event_cursor','next_window_id','submitted_cost'):
            self.assertNotIn(key,json.dumps(view))
        self.portable(g)

    def test_only_finite_ordinary_spell_policy_without_other_intrinsic_formula_is_allowed(self):
        for value in (True,None,'cost.character-completed-all-origins-v1'):
            with self.assertRaises(ValueError):model.PlayerCharacterAttackCostSpec(value)
        r=registry();d=r.card(NATIVE)
        for changes in ({'kind':CardType.MINION,'health':1},{'player_spell_damage_cost':model.PlayerSpellDamageCostSpec()}):
            with self.assertRaises(ValueError):r.register_card(replace(d,id='bad.attackprice',**changes))
