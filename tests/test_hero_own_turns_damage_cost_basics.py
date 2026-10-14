"""One original actual-damage price input; necessary TTN_462 only."""
from copy import deepcopy
from dataclasses import asdict, dataclass, FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostQuoteFact, CostSpec,
    DeckSpec, EndTurn, Game, HeroDamageTakenCostFact, HeroDamageTakenCostSpec,
    MatchSetup, PaymentType, PlayCard, PlayerCorpseSpendCostSpec, PlayerSetup, Rarity,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, UseHeroPower,
    hero_damage_taken)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input, capture_quote_fact, capture_generated_quote_fact
from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Damage,
    Effect, GainArmor, InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.hero_damage_taken_costs import validate_definition, validate_prefix
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact, validate_intrinsic_history_prefix,
    validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import _intrinsic_stage_from_dict, canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy
import test_actual_damage_history_basics as damage
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE='TTN_462'; SUPPORT=Path(__file__).resolve().parents[1]/'data/support/hero-own-turns-damage-cost-basics.json'
PIN='b662ab7addd3dc4b5c37b878bbbecf5f09c3542939fbd423a10ec00260c49e87'


def evidence():
    packet=json.loads(SUPPORT.read_bytes())
    if canonical_digest(packet)!=PIN or len(packet['records'])!=1:raise ValueError('Complete received-damage price evidence changed')
    row=packet['records'][0]
    if row['id']!=NATIVE or canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Complete original TTN_462 row changed')
    return row['data']


@dataclass(frozen=True)
class SavedQuote(Effect):
    value: CostQuoteFact
    def __post_init__(self):
        if type(self.value) is not CostQuoteFact:raise ValueError('Expected complete original physical quote')
        self.value.__post_init__()


def mechanics():
    def saved(r,work):
        validate_intrinsic_history_prefix(work.value.intrinsic,r.state,r.registry)
        f=work.value.intrinsic.hero_damage_taken
        return (GainArmor(f.player_id,f.quantity),)
    return default_mechanics('b77-received-damage-price-typed').register(SavedQuote,saved)


def registry():
    r=damage.registry();raw=evidence()
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        hero_damage_taken_cost=HeroDamageTakenCostSpec(),metadata=metadata_from_record(raw)))
    r.register_card(CardDefinition('warlock.power','Warlock fixture power',CardType.HERO_POWER,cost=2,on_use='power',
        metadata=metadata(CardClass.WARLOCK,collectible=False)))
    r.register_card(CardDefinition('warlock.hero','Warlock fixture hero',CardType.HERO,health=30,initial_hero_power='warlock.power',
        metadata=metadata(CardClass.WARLOCK,collectible=False)))
    hero=lambda c:c.state.players[c.player_id].hero_id
    held=lambda c:next(c.state.entities[e] for e in c.state.players[c.player_id].hand if c.state.entities[e].card_id==NATIVE)
    body=lambda c:next(e for e in c.state.players[c.player_id].board if c.state.entities[e].card_id==NATIVE)
    scripts={
        'native.acquire':lambda c:(AddToHand(c.player_id,NATIVE),),
        'native.large':lambda c:(Damage(hero(c),12,c.source_id),),
        'native.copy':lambda c:(CopyCard(CardReference.capture(held(c)),3-c.player_id,mode='base'),),
        'native.transform':lambda c:(TransformCapturedMinion(CardReference.capture(held(c)),'card.1'),),
        'native.to.face':lambda c:(TransformCapturedMinion(CardReference.capture(next(c.state.entities[e] for e in c.state.players[c.player_id].hand
            if c.state.entities[e].card_id=='card.1')),NATIVE),),
        'native.silence':lambda c:(Silence(body(c)),),
        'native.bounce':lambda c:(ReturnToHand(body(c)),),
        'native.local':lambda c:(ModifyCost(held(c).id,CostSpec(set_to=6)),),
        'native.external':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-2,card_ids=(NATIVE,))),),
        'native.currency':lambda c:(AddCostModifier(c.player_id,CostSpec(payment=PaymentType.HEALTH,card_ids=(NATIVE,))),),
    }
    for cid,fn in scripts.items():r.register_behavior(cid,fn);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    def pause(c):
        if c.state.entities[c.event.source_id].card_id!=NATIVE:return ()
        quote=c.state.play_history[-1].submitted_cost.quote
        return (RequestChoice(c.player_id,(
            ChoiceOption('more','Later damage for future prices',(Damage(hero(c),3,c.source_id),AddToHand(c.player_id,NATIVE),SavedQuote(quote))),
            ChoiceOption('fault','Original paid boundary failure',(InvokeBehavior('native.choice.fail',c.source_id,c.player_id),)),
        ),c.source_id),)
    r.register_behavior('native.pause',pause)
    r.register_behavior('native.choice.fail',lambda c:(AddToHand(c.player_id,'unknown.native.damage.price'),))
    for cid,event in (('native.committed.watch','card_committed'),('native.completed.watch','card_played')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=3,triggers=(TriggerSpec(event,'native.pause'),)))
    r.register_behavior('native.late.fail',lambda c:(AddToHand(c.player_id,'unknown.native.damage.price'),)
        if c.state.entities[c.event.source_id].card_id==NATIVE else ())
    r.register_card(CardDefinition('native.fail.watch','Original failure listener',CardType.MINION,health=3,
        triggers=(TriggerSpec('card_played','native.late.fail'),)))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
    return saved


class HeroOwnTurnsDamageCostTests(unittest.TestCase):
    def game(self,hand=(NATIVE,),*,enemy_hand=(),board=(),enemy_board=('plain',),armor=0,enemy_armor=0,typed=False):
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,armor=armor,
            hero_power_card_id='mage.power',deck=('card.1',)*8,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',hand=enemy_hand,board=enemy_board,armor=enemy_armor,hero_power_card_id='warrior.power',
            deck=('card.1',)*8,mana=10,max_mana=10)),seed=77),registry(),mechanics=mechanics() if typed else None)
    def source(self,g,cid=NATIVE,player=1):
        return next(g.state.entities[e] for e in g.state.players[player].hand if g.state.entities[e].card_id==cid)
    def play(self,g,cid=NATIVE):
        p=g.state.active_player;g.apply(PlayCard(p,self.source(g,cid,p).id))
    def fact(self,g,player=1):return capture_quote_fact(g.state,g.registry,capture_cost_input(self.source(g,player=player)))
    def price(self,g,player=1):return self.fact(g,player).amount
    def five(self,extra=(),*,board=(),typed=False):
        g=self.game((NATIVE,'hurt')+extra,board=board,typed=typed);self.play(g,'hurt');return g
    def check(self,g,*,typed=False):
        saved=json.loads(json.dumps(g.snapshot()));restored=Game.from_snapshot(saved,registry(),mechanics=mechanics() if typed else None)
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(),mechanics=mechanics() if typed else None).snapshot(),saved);return restored
    def typed(self,g,stage):
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(stage)),stage)
        self.assertEqual(_intrinsic_stage_from_dict(json.loads(json.dumps(asdict(stage)))),stage)

    def test_complete_native_raw_pin_original_9_4_4_warlock_epic_without_guessed_race(self):
        raw=evidence();card=registry().card(NATIVE)
        self.assertEqual((card.cost,card.attack,card.health),(9,4,4));self.assertNotIn('CARDRACE',raw['tags'])
        self.assertEqual(card.metadata,metadata_from_record(raw))
        self.assertEqual((card.metadata.classes,card.metadata.rarity,card.metadata.tribes),((CardClass.WARLOCK,),Rarity.EPIC,()))
        self.assertEqual((card.battlecry,card.deathrattle,card.keywords),(None,None,()))
        self.assertIn('your turns this game',raw['text_en'])

    def test_real_thirty_slot_experimental_constructed_and_mulligan_fixture(self):
        r=registry();own=tuple(f'card.{i}' for i in range(1,30))+(NATIVE,)
        g=Game.from_decks(MatchSetup((DeckSpec('warlock.hero','warlock.power',CardClass.WARLOCK,own),
            DeckSpec('warrior.hero','warrior.power',CardClass.WARRIOR,tuple(f'card.{i}' for i in range(1,31)))),policy(r),'coin',77,1),r)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        f=capture_generated_quote_fact(g.state,r,1,NATIVE)
        self.assertEqual((tuple(map(len,g.state.opening.original_entities)),f.amount),((30,30),9))
        self.assertEqual(f.intrinsic.hero_damage_taken.records,())

    def test_initial_health_and_armor_do_not_fabricate_received_damage(self):
        g=self.game(armor=99);f=self.fact(g).intrinsic.hero_damage_taken
        self.assertEqual((f.quantity,f.records,f.next_damage_id,self.price(g)),(0,(),1,9))

    def test_armor_absorption_reduces_cost_by_actual_damage_not_lost_health(self):
        g=self.game((NATIVE,'hurt'),armor=3);self.play(g,'hurt');f=self.fact(g).intrinsic.hero_damage_taken
        self.assertEqual((f.quantity,f.records[0].health_result.health_lost,self.price(g)),(5,2,4));self.check(g)

    def test_ordinary_healing_does_not_erase_previous_actual_damage_units(self):
        g=self.five(('heal','armor','grow'))
        for cid in ('heal','armor','grow'):self.play(g,cid)
        self.assertEqual((self.price(g),self.fact(g).intrinsic.hero_damage_taken.quantity),(4,5));self.check(g)

    def test_complete_all_target_rows_preserve_unselected_packets(self):
        g=self.game((NATIVE,'batch'),board=('plain',),armor=3);self.play(g,'batch');f=self.fact(g).intrinsic.hero_damage_taken
        self.assertEqual((f.quantity,len(f.records),self.price(g)),(5,3,4))
        self.assertEqual([r.health_result.damage_dealt for r in f.records],[5,2,3]);self.typed(g,self.fact(g).intrinsic)

    def test_all_own_turns_accumulate_and_opponent_turn_damage_is_excluded(self):
        g=self.game((NATIVE,'batch','two'),board=('plain',),armor=3);self.play(g,'batch');g.apply(EndTurn(1))
        g.apply(UseHeroPower(2,g.state.players[2].hero_power_id));g.apply(EndTurn(2));self.play(g,'two')
        f=self.fact(g).intrinsic.hero_damage_taken
        self.assertEqual((hero_damage_taken(g.state,1),f.quantity,self.price(g)),(8,7,2))
        self.assertEqual(hero_damage_taken(g.state,1,own_turn_only=True,turn=3),2)
        self.assertEqual([r.health_result.turn for r in f.records],[1,1,1,2,3]);self.check(g)

    def test_other_player_source_and_unknown_source_still_count_target_hero_damage(self):
        for cid in ('other.source','unknown'):
            g=self.game((NATIVE,cid));self.play(g,cid)
            self.assertEqual(self.price(g),7 if cid=='other.source' else 4);self.check(g)

    def test_each_payer_uses_own_target_and_own_turn_with_all_original_rows(self):
        g=self.game((NATIVE,'hurt'),enemy_hand=(NATIVE,'two'));self.play(g,'hurt');g.apply(EndTurn(1));self.play(g,'two')
        a=self.fact(g,1).intrinsic.hero_damage_taken;b=self.fact(g,2).intrinsic.hero_damage_taken
        self.assertEqual((a.quantity,b.quantity,self.price(g,1),self.price(g,2)),(5,2,4,7))
        self.assertEqual(a.records,b.records);self.check(g)

    def test_zero_prevented_and_converted_rows_use_final_damage_only(self):
        for cid,board,expected in (('zero',(),0),('hurt',('prevent',),0),('heal',('heal.to.damage',),5)):
            g=self.game((NATIVE,cid),board=board);self.play(g,cid)
            f=self.fact(g).intrinsic.hero_damage_taken
            self.assertEqual((len(f.records),f.quantity,self.price(g)),(1,expected,9-expected));self.check(g)
        g=self.five(('enable','two'));self.play(g,'enable');self.play(g,'two')
        self.assertEqual((self.fact(g).intrinsic.hero_damage_taken.quantity,self.price(g)),(5,4));self.check(g)

    def test_known_fatigue_is_received_damage_on_own_turn_without_player_source(self):
        g=self.game((NATIVE,'fatigue'));self.play(g,'fatigue');f=self.fact(g).intrinsic.hero_damage_taken
        self.assertEqual((f.quantity,f.records[0].health_result.damage_kind,self.price(g)),(1,'fatigue',8));self.check(g)

    def test_acquisition_after_damage_uses_all_previous_own_turn_units(self):
        g=self.game(('hurt','native.acquire'));self.play(g,'hurt');self.play(g,'native.acquire')
        self.assertEqual((self.price(g),len(self.fact(g).intrinsic.hero_damage_taken.records)),(4,1));self.check(g)

    def test_floor_zero_retains_complete_quantity_and_packets(self):
        g=self.game((NATIVE,'native.large'));self.play(g,'native.large');f=self.fact(g).intrinsic.hero_damage_taken
        self.assertEqual((f.quantity,len(f.records),self.price(g)),(12,1,0));self.typed(g,self.fact(g).intrinsic)

    def test_physical_and_generated_quotes_are_equal_detached_and_pure(self):
        g=self.five();before=g.snapshot();a=self.fact(g);b=capture_generated_quote_fact(g.state,g.registry,1,NATIVE)
        self.assertEqual(a.intrinsic.hero_damage_taken,b.intrinsic.hero_damage_taken)
        self.assertEqual((a.amount,b.amount),(4,4));validate_generated_quote_fact(g.registry,b)
        self.assertEqual(g.snapshot(),before);self.typed(g,a.intrinsic)

    def test_generated_initial_cost_and_minimum_follow_intrinsic_quantity(self):
        g=self.five();f=capture_generated_quote_fact(g.state,g.registry,1,NATIVE,cost=CostSpec(set_to=6),minimum_cost=7)
        self.assertEqual((f.intrinsic.amount,f.local_amount,f.amount),(4,6,7));validate_generated_quote_fact(g.registry,f)

    def test_original_local_and_external_layers_follow_damage_quantity(self):
        g=self.five(('native.local','native.external'));self.play(g,'native.local');self.play(g,'native.external');f=self.fact(g)
        self.assertEqual((f.intrinsic.amount,f.local_amount,f.amount),(4,6,4));self.play(g)
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(4,6));self.check(g)

    def test_player_command_pays_once_and_plays_complete_native_four_four(self):
        g=self.five();port=g.for_player(1);dto=port.legal_actions()
        card=next(row for row in g.observe(1)['players'][0]['hand'] if row['card_id']==NATIVE)
        action=next(row for row in dto['actions'] if row.get('card')==card['ref'])
        self.assertTrue(port.submit({'revision':dto['revision'],'action':action})['accepted'])
        e=g.state.entities[g.state.players[1].board[0]]
        self.assertEqual((e.attack,e.health,g.state.play_history[-1].cost,g.state.players[1].mana),(4,4,4,6));self.check(g)

    def test_health_payment_is_not_actual_damage_and_does_not_reprice_original(self):
        g=self.five(('native.currency',NATIVE));self.play(g,'native.currency');self.play(g)
        record=g.state.play_history[-1];f=record.submitted_cost.quote.intrinsic.hero_damage_taken
        self.assertEqual((record.cost,record.payment,f.quantity,self.price(g)),(4,PaymentType.HEALTH,5,4))
        self.assertEqual(hero_damage_taken(g.state,1,own_turn_only=True),5);self.check(g)

    def test_ordinary_copy_to_other_payer_recomputes_recipient_damage_history(self):
        g=self.five(('native.copy',));self.play(g,'native.copy')
        self.assertEqual((self.price(g,1),self.price(g,2)),(4,9));self.check(g)

    def test_transform_to_and_from_native_face_preserves_global_history(self):
        g=self.game(('card.1','hurt','native.to.face','native.transform'));self.play(g,'hurt');self.play(g,'native.to.face')
        self.assertEqual(self.price(g),4);source=self.source(g).id;self.play(g,'native.transform')
        self.assertEqual(g.quote_cost(source).amount,1);self.assertEqual(hero_damage_taken(g.state,1,own_turn_only=True),5);self.check(g)

    def test_silence_then_bounce_restores_printed_cost_formula_with_global_history(self):
        g=self.five(('native.silence','native.bounce'));self.play(g);self.play(g,'native.silence');self.play(g,'native.bounce')
        self.assertEqual(self.price(g),4);self.check(g)

    def waiting(self,watcher,completed):
        g=self.five(board=(watcher,),typed=True);self.play(g);record=g.state.play_history[-1];old=record.submitted_cost.quote.intrinsic
        self.assertEqual((record.cost,record.completed,old.hero_damage_taken.quantity),(4,completed,5));restored=self.check(g,typed=True);clone=g.clone()
        action=SelectChoice(1,g.state.pending_choice.id,('more',));g.apply(action)
        for other in (restored,clone):other.apply(action);self.assertEqual(other.snapshot(),g.snapshot())
        self.assertEqual((self.price(g),g.state.play_history[-1].cost,g.state.players[1].mana),(1,4,6))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,5)
        validate_intrinsic_history_prefix(old,g.state,g.registry);self.assertEqual(old.hero_damage_taken.quantity,5);self.typed(g,old);self.check(g,typed=True)

    def test_committed_waiting_retains_price_and_accepts_later_actual_damage(self):self.waiting('native.committed.watch',False)
    def test_completed_waiting_retains_price_and_accepts_later_actual_damage(self):self.waiting('native.completed.watch',True)

    def test_second_player_waiting_continuation_uses_payer_not_hero_entity_id(self):
        g=self.game((),enemy_hand=(NATIVE,'two'),enemy_board=('native.completed.watch',),typed=True)
        g.apply(EndTurn(1));self.play(g,'two');self.play(g);old=g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.assertEqual((old.hero_damage_taken.player_id,old.hero_damage_taken.quantity,old.amount),(2,2,7))
        restored=self.check(g,typed=True);q=g.state.pending_choice;action=SelectChoice(2,q.id,('more',))
        g.apply(action);restored.apply(action);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual((self.price(g,2),g.state.players[2].mana),(4,3))
        self.assertEqual((g.state.entities[g.state.players[1].hero_id].armor,g.state.entities[g.state.players[2].hero_id].armor),(0,2))
        validate_intrinsic_history_prefix(old,g.state,g.registry);self.check(g,typed=True)

    def test_failed_choice_preserves_original_payment_prefix_and_pending_frame(self):
        g=self.five(board=('native.completed.watch',),typed=True);self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,g.state.pending_choice.id,('fault',)))
        self.assertEqual(g.snapshot(),before);self.check(g,typed=True)

    def test_transaction_failure_rolls_back_native_entry_payment_and_price(self):
        g=self.five(board=('native.fail.watch',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.price(g),4)

    def test_later_damage_advances_prefix_but_cannot_rewrite_old_accepted_quantity(self):
        g=self.five(('two',));old=self.fact(g).intrinsic;self.play(g,'two')
        validate_prefix(old.hero_damage_taken,g.state,g.registry);validate_intrinsic_history_prefix(old,g.state,g.registry)
        self.assertEqual((old.amount,self.price(g)),(4,2))
        with self.assertRaises(ValueError):validate_intrinsic_origin(old,g.state,g.registry)

    def test_full_unselected_original_prefix_identity_cannot_be_changed_with_equal_quantity(self):
        g=self.game((NATIVE,'batch'),board=('plain',));self.play(g,'batch');old=self.fact(g).intrinsic;f=old.hero_damage_taken
        row=f.records[1];pairs=tuple((key,2 if key=='source_controller' else value) for key,value in row.result)
        changed=replace(f,records=(f.records[0],replace(row,result=pairs),f.records[2]))
        self.assertEqual(changed.quantity,f.quantity)
        with self.assertRaises(ValueError):validate_prefix(changed,g.state,g.registry)

    def test_strict_operand_types_clocks_packet_order_and_physical_bounds(self):
        g=self.five();f=self.fact(g).intrinsic.hero_damage_taken
        for changes in ({'quantity':True},{'after':2},{'player_id':True},{'next_damage_id':1},{'records':list(f.records)},
                        {'turn':0},{'action':0},{'next_entity_id':f.records[0].health_result.source_id},{'next_order':1}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(f,**changes)
        with self.assertRaises(FrozenInstanceError):f.quantity=0
        with self.assertRaises(ValueError):HeroDamageTakenCostSpec('unreviewed.damage.profile')

    def test_finite_native_declaration_rejects_other_shapes_and_multiple_formulas(self):
        card=registry().card(NATIVE)
        for changes in ({'hero_damage_taken_cost':{}},{'kind':CardType.SPELL},{'choice_only':True},
                        {'player_corpse_spend_cost':PlayerCorpseSpendCostSpec()}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):validate_definition(replace(card,**changes))

    def test_physical_quote_source_cannot_borrow_future_allocator(self):
        g=self.game(('hurt','native.acquire'));self.play(g,'hurt');self.play(g,'native.acquire');full=self.fact(g)
        f=replace(full.intrinsic.hero_damage_taken,next_entity_id=self.source(g).id)
        with self.assertRaises(ValueError):replace(full,intrinsic=replace(full.intrinsic,hero_damage_taken=f))

    def test_typed_and_dictionary_stage_require_explicit_null_damage_leaf(self):
        g=self.game(('hurt',));stage=capture_quote_fact(g.state,g.registry,capture_cost_input(self.source(g,'hurt'))).intrinsic
        self.assertIsNone(stage.hero_damage_taken);codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);wire=codec.encode(stage)
        del wire['fields']['hero_damage_taken']
        with self.assertRaises(ValueError):codec.decode(wire)
        raw=json.loads(json.dumps(asdict(stage)));del raw['hero_damage_taken']
        with self.assertRaises(ValueError):_intrinsic_stage_from_dict(raw)

    def test_rehashed_paid_wire_rejects_missing_truncated_or_changed_damage_operand(self):
        g=self.five();self.play(g);saved=g.snapshot()
        for mode in ('missing','extra','quantity','cursor','drop','source','clock','reorder'):
            bad=deepcopy(saved);stage=bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic'];f=stage['hero_damage_taken']
            if mode=='missing':del stage['hero_damage_taken']
            elif mode=='extra':f['invented']=1
            elif mode=='quantity':f['quantity']=True
            elif mode=='cursor':f['next_damage_id']+=1
            elif mode=='drop':f['records'].pop()
            elif mode=='clock':f['action']+=1
            elif mode=='reorder':f['records'][0]['result'].reverse()
            else:next(pair for pair in f['records'][0]['result'] if pair[0]=='source_card_id')[1]='unknown.original.source'
            with self.subTest(mode=mode),self.assertRaises(SnapshotError) as err:Game.from_snapshot(rehash(bad),registry())
            self.assertNotIn('digest mismatch',str(err.exception).lower())

    def test_original_window_and_known_card_checks_reject_equal_price_forgery(self):
        g=self.five();stage=self.fact(g).intrinsic;row=stage.hero_damage_taken.records[0]
        pairs=tuple((key,'unknown.original.face' if key=='source_card_id' else value) for key,value in row.result)
        changed=replace(stage,hero_damage_taken=replace(stage.hero_damage_taken,records=(replace(row,result=pairs),)))
        with self.assertRaises(ValueError):validate_intrinsic_stage_fact(g.registry,changed)
        changed=replace(stage,hero_damage_taken=replace(stage.hero_damage_taken,next_entity_id=stage.hero_damage_taken.next_entity_id+1))
        with self.assertRaises(ValueError):validate_intrinsic_origin(changed,g.state,g.registry)

    def test_player_price_is_visible_but_complete_original_damage_inventory_is_private(self):
        g=self.five();before=g.snapshot();own=next(row for row in g.observe(1)['players'][0]['hand'] if row['card_id']==NATIVE)
        self.assertEqual(own['cost'],{'amount':4,'payment':'mana'})
        for p in (1,2):
            text=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for field in ('hero_damage_taken','damage_history','next_damage_id','source_controller','submitted_cost'):
                self.assertNotIn('"'+field+'"',text)
        self.assertNotIn(NATIVE,json.dumps(g.observe(2)));self.assertEqual(g.snapshot(),before)

    def test_new_schema_and_old_host_signatures_are_strict(self):
        g=self.five();saved=g.snapshot()
        self.assertEqual((saved['schema_version'],g.ruleset.id,g.mechanics.version),(266,'prototype-v302',CORE_EFFECTS_VERSION))
        for version in (1,214,217,True,216.0):
            bad=deepcopy(saved);bad['schema_version']=version
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())
        self.check(g)
