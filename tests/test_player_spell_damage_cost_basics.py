"""One native current-turn actual spell-damage price through public pipelines."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, CostSpec, EndTurn, Game, IllegalAction,
    PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError,
    SpellSchool, TriggerSpec, UseHeroPower)
from hs_sim.engine import model
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input, capture_generated_quote_fact, capture_quote_fact
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Damage,
    InvokeBehavior, ModifyCost, RequestChoice, Summon)
from hs_sim.engine.intrinsic_costs import (validate_intrinsic_history_prefix,
    validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import _intrinsic_stage_from_dict
from hs_sim.targets import canonical_digest
import test_actual_damage_history_basics as damage

NATIVE='CATA_452';TOKEN='CATA_452t'
SUPPORT=Path(__file__).resolve().parents[1]/'data/support/player-spell-damage-cost-basics.json'
PIN='daed86e1d99ca0641d776dbd484f34be32e75c26be81abc2c2a821e92be7535a'


def evidence():
    value=json.loads(SUPPORT.read_bytes())
    if canonical_digest(value)!=PIN:raise ValueError('Spell damage price complete evidence changed')
    for row in value['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Spell damage price original raw changed')
    return {row['id']:row['data'] for row in value['records']}


def registry(*,wait=False):
    r=damage.registry();rows=evidence();raw=rows[NATIVE];token=rows[TOKEN]
    r.register_card(CardDefinition(TOKEN,token['name'],CardType.MINION,cost=token['cost'],
        attack=token['attack'],health=token['health'],metadata=metadata_from_record(token)))
    r.register_behavior('spellprice.native',lambda c:(Summon(c.player_id,TOKEN),))
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.SPELL,cost=raw['cost'],
        spell_school=SpellSchool.ARCANE,on_play='spellprice.native',metadata=metadata_from_record(raw),
        player_spell_damage_cost=model.PlayerSpellDamageCostSpec()))
    hero=lambda c:c.state.players[c.player_id].hero_id
    held=lambda c:next(e for e in c.state.players[c.player_id].hand if c.state.entities[e].card_id==NATIVE)
    scripts={
        'spellprice.acquire':lambda c:(AddToHand(c.player_id,NATIVE),),
        'spellprice.large':lambda c:(Damage(hero(c),12,c.source_id),),
        'spellprice.local':lambda c:(ModifyCost(held(c),CostSpec(set_to=6)),),
        'spellprice.external':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-2,card_ids=(NATIVE,))),),
    }
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    r.register_behavior('spellprice.fail',lambda c:(AddToHand(c.player_id,'missing.spell.damage.price'),))
    def pause(c):
        if c.state.entities[c.event.source_id].card_id!=NATIVE:return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('continue','Complete original payment'),
            ChoiceOption('more','Later damage affects future prices',
                (Damage(hero(c),3,c.event.source_id),AddToHand(c.player_id,NATIVE))),
            ChoiceOption('fault','Delayed failure',(InvokeBehavior('spellprice.fail',c.source_id,c.player_id),)),
        ),c.source_id),)
    if wait:
        r.register_behavior('spellprice.pause',pause)
        r.register_card(CardDefinition('spellprice.watch','Payment waiting fixture',CardType.MINION,
            health=3,triggers=(TriggerSpec('card_committed','spellprice.pause'),)))
    return r


class PlayerSpellDamageCostTests(unittest.TestCase):
    def setUp(self):self.options={}

    def game(self,hand=(NATIVE,),*,enemy_hand=(),board=('plain',),enemy=('plain',),mana=10,armor=0):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero',hand=hand,board=board,deck=('card.1',)*5,armor=armor,
                mana=mana,max_mana=10,hero_power_card_id='mage.power'),
            PlayerSetup('warrior.hero',hand=enemy_hand,board=enemy,deck=('card.1',)*5,
                mana=10,max_mana=10,hero_power_card_id='warrior.power')),seed=62),registry(**self.options))

    def source(self,g,cid=NATIVE,player=1):
        return next(g.state.entities[e] for e in g.state.players[player].hand if g.state.entities[e].card_id==cid)

    def fact(self,g,player=1):
        return capture_quote_fact(g.state,g.registry,capture_cost_input(self.source(g,player=player)))

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

    def five(self,**kwargs):
        g=self.game((NATIVE,'hurt',*kwargs.pop('extras',())),**kwargs);self.play(g,'hurt');return g

    def test_native_full_raw_and_complete_dragon_summon_adapter(self):
        rows=evidence();raw={r['id']:r for r in json.loads((SUPPORT.parents[1]/'extracted/cards.json').read_bytes())}
        self.assertEqual(rows,{cid:raw[cid] for cid in (NATIVE,TOKEN)})
        g=self.game();self.play(g)
        summoned=next(g.state.entities[e] for e in g.state.players[1].board if g.state.entities[e].card_id==TOKEN)
        self.assertEqual((summoned.attack,summoned.health,summoned.base_cost),(6,6,6))
        self.assertEqual(g.state.play_history[-1].cost,10);self.portable(g)

    def test_armor_absorption_uses_actual_units_not_net_health(self):
        g=self.five(armor=3);f=self.fact(g).intrinsic.player_spell_damage
        self.assertEqual((f.quantity,f.before,f.after,len(f.rows)),(5,10,5,1))
        self.assertEqual(f.rows[0].record.health_result.health_lost,2);self.portable(g)

    def test_batch_counts_all_targets_not_number_of_spells(self):
        g=self.game((NATIVE,'batch'));self.play(g,'batch');f=self.fact(g).intrinsic.player_spell_damage
        self.assertEqual((f.quantity,f.after,len(f.rows)),(10,0,3));self.play(g);self.portable(g)

    def test_damage_before_acquisition_is_available_without_held_progress(self):
        g=self.game(('hurt','spellprice.acquire'));self.play(g,'hurt');self.play(g,'spellprice.acquire')
        self.assertEqual(self.fact(g).amount,5);self.portable(g)

    def test_payer_excludes_opponent_minion_and_hero_power_sources(self):
        g=self.game((NATIVE,'hurt','body.source'),enemy_hand=(NATIVE,'hurt'))
        self.play(g,'hurt');self.play(g,'body.source');g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual(self.fact(g).amount,5)
        g.apply(EndTurn(1));self.play(g,'hurt')
        self.assertEqual((self.fact(g).amount,self.fact(g,2).amount),(10,5));self.portable(g)

    def test_new_global_turn_resets_discount_without_erasing_history(self):
        g=self.five();old=self.fact(g).intrinsic;g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual((self.fact(g).amount,len(g.state.damage_history)),(10,1))
        validate_intrinsic_history_prefix(old,g.state,g.registry);self.portable(g)

    def test_zero_immune_and_shield_results_do_not_discount(self):
        for hand,board in ((('zero',),('plain',)),(('body.hit',),('immune',)),(('body.hit',),('shield',))):
            with self.subTest(board=board):
                g=self.game((NATIVE,*hand),board=board);self.play(g,hand[0])
                self.assertEqual((self.fact(g).amount,len(self.fact(g).intrinsic.player_spell_damage.rows)),(10,1))
                self.portable(g)

    def test_converted_flows_use_final_actual_damage_quantity(self):
        g=self.game((NATIVE,'hurt','enable','two'))
        for cid in ('hurt','enable','two'):self.play(g,cid)
        self.assertEqual(self.fact(g).amount,5);self.portable(g)
        g=self.game((NATIVE,'heal'),board=('plain','heal.to.damage'));self.play(g,'heal')
        self.assertEqual(self.fact(g).amount,5);self.portable(g)

    def test_positive_unknown_source_rejects_even_at_zero_floor(self):
        g=self.game(('spellprice.large','unknown'));self.play(g,'spellprice.large');self.play(g,'unknown')
        with self.assertRaises(UnsupportedDefinitionError):capture_generated_quote_fact(g.state,g.registry,1,NATIVE)
        self.assertEqual(g.state.damage_history[0].health_result.damage_dealt,12)

    def test_previous_turn_unknown_credit_does_not_block_current_zero_operand(self):
        g=self.game(('unknown',));self.play(g,'unknown');g.apply(EndTurn(1))
        self.assertEqual(capture_generated_quote_fact(g.state,g.registry,1,NATIVE).amount,10)
        self.portable(g)

    def test_generated_and_physical_quotes_are_pure_and_share_complete_operand(self):
        g=self.five();before=g.snapshot();f=self.fact(g)
        generated=capture_generated_quote_fact(g.state,g.registry,1,NATIVE)
        self.assertEqual((generated.amount,generated.intrinsic.player_spell_damage),(5,f.intrinsic.player_spell_damage))
        g.legal_actions();self.assertEqual(g.snapshot(),before)

    def test_local_external_and_minimum_layers_follow_intrinsic_price(self):
        g=self.five(extras=('spellprice.local','spellprice.external'))
        self.play(g,'spellprice.local');self.play(g,'spellprice.external')
        f=self.fact(g);self.assertEqual((f.intrinsic.amount,f.local_amount,f.amount),(5,6,4))
        floor=capture_quote_fact(g.state,g.registry,capture_cost_input(self.source(g),minimum_cost=7))
        self.assertEqual(floor.amount,7);self.play(g);self.assertEqual(g.state.players[1].mana,6);self.portable(g)

    def test_insufficient_payment_rolls_back_all_operands(self):
        g=self.five(mana=4);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_waiting_payment_preserves_original_price_after_later_damage(self):
        self.options=dict(wait=True);g=self.five(board=('plain','spellprice.watch'))
        self.play(g);stage=g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.assertEqual((stage.player_spell_damage.quantity,g.state.players[1].mana),(5,5))
        restored=self.portable(g)
        for current in (g,restored):
            self.choose(current,'more');validate_intrinsic_history_prefix(stage,current.state,current.registry)
            self.assertEqual((self.fact(current).amount,current.state.play_history[-1].cost,current.state.players[1].mana),(2,5,5))
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_delayed_choice_failure_restores_the_paid_boundary(self):
        self.options=dict(wait=True);g=self.five(board=('plain','spellprice.watch'));self.play(g)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_original_window_rejects_self_consistent_forged_source_kind(self):
        g=self.game((NATIVE,'body.source'));self.play(g,'body.source');stage=self.fact(g).intrinsic
        f=stage.player_spell_damage;row=replace(f.rows[0],source_kind=CardType.SPELL)
        forged=replace(stage,player_spell_damage=replace(f,rows=(row,),quantity=2,after=8),amount=8)
        with self.assertRaises(ValueError):validate_intrinsic_stage_fact(g.registry,forged)
        with self.assertRaises(ValueError):validate_intrinsic_origin(forged,g.state,g.registry)

    def test_complete_prefix_rejects_missing_reordered_or_wrong_quantity(self):
        g=self.game((NATIVE,'batch'));self.play(g,'batch');f=self.fact(g).intrinsic.player_spell_damage
        for changes in ({'rows':f.rows[:-1]},{'rows':tuple(reversed(f.rows))},{'quantity':9,'after':1}):
            with self.subTest(changes=tuple(changes)),self.assertRaises(ValueError):replace(f,**changes)

    def test_json_and_typed_fact_require_exact_new_leaf_and_typed_source_kind(self):
        g=self.five();stage=self.fact(g).intrinsic
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state,origin_events=g.events)
        self.assertEqual(codec.decode(codec.encode(stage)),stage)
        raw=json.loads(json.dumps(asdict(stage)));self.assertEqual(_intrinsic_stage_from_dict(raw),stage)
        del raw['player_spell_damage']
        with self.assertRaises(ValueError):_intrinsic_stage_from_dict(raw)
        wire=codec.encode(stage);del wire['fields']['player_spell_damage']
        with self.assertRaises((ValueError,SnapshotError)):codec.decode(wire)

    def test_saved_rehashed_cost_rejects_borrowed_original_card_kind(self):
        g=self.five();self.play(g);saved=g.snapshot();bad=deepcopy(saved)
        f=bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['player_spell_damage']
        f['rows'][0]['source_kind']=CardType.HERO_POWER.value
        with self.assertRaises(SnapshotError):Game.from_snapshot(damage.rehash(bad),registry())

    def test_player_prices_do_not_leak_complete_damage_or_opponent_hand(self):
        g=self.five(enemy_hand=(NATIVE,));view=g.observe(1)
        self.assertEqual(view['players'][0]['hand'][0]['cost']['amount'],5)
        self.assertIsNone(view['players'][1]['hand'][0]['card_id'])
        for key in ('player_spell_damage','damage_history','source_kind','submitted_cost','next_damage_id'):
            self.assertNotIn(key,json.dumps(view))
        self.portable(g)

    def test_finite_spell_carrier_rejects_other_formulas_and_wrong_policy(self):
        r=registry();native=r.card(NATIVE)
        for changes in ({'kind':CardType.MINION,'health':1},
                        {'intrinsic_costs':(model.IntrinsicCostSpec(condition='permanent_mana_at_least',
                            history_profile_id='mana.permanent-crystals-v1',set_to=0,mana_crystals=7),)},
                        {'hero_damage_taken_cost':model.HeroDamageTakenCostSpec()}):
            with self.subTest(changes=tuple(changes)),self.assertRaises(ValueError):
                r.register_card(replace(native,id='bad.spell.damage',**changes))
        for profile in (True,None,'all.turns','all.kinds'):
            with self.subTest(profile=profile),self.assertRaises(ValueError):model.PlayerSpellDamageCostSpec(profile)
