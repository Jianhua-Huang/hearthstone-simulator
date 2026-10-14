"""Actual corpse units in the shared cost stage; necessary RLK_744 only."""
from copy import deepcopy
from dataclasses import asdict, dataclass, FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CostQuoteFact,
    CostSpec, EndTurn, Game, IntrinsicCostStageFact, PlayerCorpseSpendCostFact,
    PlayerCorpseSpendCostSpec, PlayerSummonCountCostSpec, PlayerSetup, PlayCard, Rarity, ResolutionError, Runes,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, PaymentType, spent_corpses)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input, capture_quote_fact, capture_generated_quote_fact
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Destroy,
    Effect, GainArmor, GainResource, InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand,
    Silence, SpendResource, Transform)
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact,
    validate_intrinsic_history_prefix, validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.player_corpse_spend_costs import validate_definition, validate_prefix
from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import _intrinsic_stage_from_dict, canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.targets import canonical_digest
import test_corpse_spend_history_basics as debits
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE = 'RLK_744'
SUPPORT = Path(__file__).resolve().parents[1]/'data/support/player-corpse-spend-cost-basics.json'
PIN = 'c81544e818e5590d43b8c91952963017f5d87e7c7f7e523fba7b17f2a15eebe2'


def evidence():
    packet = json.loads(SUPPORT.read_bytes())
    if canonical_digest(packet) != PIN or len(packet['records']) != 1:
        raise ValueError('Complete corpse-spend price evidence changed')
    row = packet['records'][0]
    if row['id'] != NATIVE or canonical_digest(row['data']) != row['data_sha256']:
        raise ValueError('Complete original corpse-spend price row changed')
    return row['data']


@dataclass(frozen=True)
class SavedQuote(Effect):
    value: CostQuoteFact

    def __post_init__(self):
        if type(self.value) is not CostQuoteFact:
            raise ValueError('Expected one complete original physical quote')
        self.value.__post_init__()


def mechanics():
    def saved(r, work):
        validate_intrinsic_history_prefix(work.value.intrinsic, r.state, r.registry)
        return (GainArmor(r.state.players[work.value.quote_input.player_id].hero_id,
            work.value.intrinsic.player_corpses.quantity),)
    return default_mechanics('b72-corpse-price-typed-test').register(SavedQuote, saved)


def registry():
    r = debits.registry()
    raw = evidence()
    r.register_card(CardDefinition(NATIVE, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], player_corpse_spend_cost=PlayerCorpseSpendCostSpec(),
        metadata=CardMetadata(True, (CardClass.DEATH_KNIGHT,), Rarity.EPIC,
            runes=Runes(unholy=1), tribes=('undead',))))

    def held(c):
        return next(c.state.entities[e] for e in c.state.players[c.player_id].hand
            if c.state.entities[e].card_id == NATIVE)

    def body(c):
        return next(e for e in c.state.players[c.player_id].board if c.state.entities[e].card_id == NATIVE)

    scripts = {
        'native.acquire': lambda c: (AddToHand(c.player_id, NATIVE),),
        'native.copy': lambda c: (CopyCard(CardReference.capture(held(c)), 3-c.player_id, mode='base'),),
        'native.silence': lambda c: (Silence(body(c)),),
        'native.bounce': lambda c: (ReturnToHand(body(c)),),
        'native.destroy': lambda c: (Destroy(body(c), c.source_id),),
        'native.transform': lambda c: (TransformCapturedMinion(CardReference.capture(held(c)), 'card.1'),),
        'native.to.face': lambda c: (TransformCapturedMinion(CardReference.capture(next(c.state.entities[e]
            for e in c.state.players[c.player_id].hand if c.state.entities[e].card_id == 'card.1')), NATIVE),),
        'native.refund': lambda c: (SpendResource(c.player_id, debits.Resource.CORPSES, 2),
            GainResource(c.player_id, debits.Resource.CORPSES, 4)),
        'native.large': lambda c: (SpendResource(c.player_id, debits.Resource.CORPSES, 12),),
        'native.local': lambda c: (ModifyCost(held(c).id, CostSpec(set_to=6)),),
        'native.external': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-2, card_ids=(NATIVE,))),),
        'native.currency': lambda c: (AddCostModifier(c.player_id,
            CostSpec(payment=PaymentType.CORPSES, card_ids=(NATIVE,))),),
    }
    for name, fn in scripts.items():
        r.register_behavior(name, fn)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))

    def pause(c):
        if c.state.entities[c.event.source_id].card_id != NATIVE:
            return ()
        quote = c.state.play_history[-1].submitted_cost.quote
        return (RequestChoice(c.player_id, (
            ChoiceOption('more', 'New debit for a future quote', (SpendResource(c.player_id, debits.Resource.CORPSES, 2),
                AddToHand(c.player_id, NATIVE), SavedQuote(quote))),
            ChoiceOption('fault', 'Rollback to the original paid boundary', (InvokeBehavior('debit.fault', c.source_id, c.player_id),)),
        ), c.source_id),)
    r.register_behavior('native.pause', pause)
    for name, event in (('native.committed.watch', 'card_committed'), ('native.completed.watch', 'card_played')):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=3,
            triggers=(TriggerSpec(event, 'native.pause'),)))
    r.register_behavior('native.late.fail', lambda c: (AddToHand(c.player_id, 'unknown.native.price'),)
        if c.state.entities[c.event.source_id].card_id == NATIVE else ())
    r.register_card(CardDefinition('native.fail.watch', 'Original failure listener', CardType.MINION,
        health=3, triggers=(TriggerSpec('card_played', 'native.late.fail'),)))
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({key:value for key,value in saved.items()
        if key not in ('schema_version','events','events_hash','state_hash')})
    return saved


class PlayerCorpseSpendCostTests(unittest.TestCase):
    def game(self, hand=(NATIVE,), *, corpses=20, enemy_corpses=20, enemy_hand=(), board=(), typed=False):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, corpses=corpses, board=board, deck=('card.1',)*3, mana=10, max_mana=10),
            PlayerSetup('warrior.hero', hand=enemy_hand, corpses=enemy_corpses, deck=('card.1',)*3, mana=10, max_mana=10)), seed=72),
            registry(), mechanics=mechanics() if typed else None)

    def source(self, g, cid=NATIVE, player=1):
        return next(g.state.entities[e] for e in g.state.players[player].hand if g.state.entities[e].card_id == cid)

    def play(self, g, cid=NATIVE):
        player=g.state.active_player;source=self.source(g, cid, player)
        g.apply(PlayCard(player, source.id));return source.id

    def fact(self, g, player=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, player=player)))

    def price(self, g, player=1):
        return self.fact(g, player).amount

    def five(self, extra=(), *, board=(), corpses=20, typed=False):
        g=self.game((NATIVE,'debit.fixed','debit.cap',*extra),board=board,corpses=corpses,typed=typed)
        self.play(g,'debit.fixed');self.play(g,'debit.cap');return g

    def check(self, g, *, typed=False):
        saved=json.loads(json.dumps(g.snapshot()))
        restored=Game.from_snapshot(saved,registry(),mechanics=mechanics() if typed else None)
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(),mechanics=mechanics() if typed else None).snapshot(),saved)
        return restored

    def typed(self, g, stage):
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(stage)),stage)
        self.assertEqual(_intrinsic_stage_from_dict(json.loads(json.dumps(asdict(stage)))),stage)

    def test_one_complete_original_native_raw_pin_and_printed9_8_8_undead_unholy(self):
        raw=evidence();card=registry().card(NATIVE)
        self.assertEqual((raw['dbf_id'],card.cost,card.attack,card.health),(82072,9,8,8))
        self.assertEqual((card.metadata.classes,card.metadata.rarity,card.metadata.runes,card.metadata.tribes),
            ((CardClass.DEATH_KNIGHT,),Rarity.EPIC,Runes(unholy=1),('undead',)))
        self.assertEqual((card.on_play,card.battlecry,card.deathrattle,card.keywords),(None,None,None,()))

    def test_initial_resource_bank_does_not_fabricate_spent_units(self):
        g=self.game(corpses=99);f=self.fact(g).intrinsic.player_corpses
        self.assertEqual((self.price(g),f.quantity,f.records),(9,0,()))

    def test_fixed_capped_currency_and_zero_share_complete_original_quantity(self):
        g=self.game((NATIVE,'debit.fixed','debit.cap','debit.skip','debit.gain','debit.mode','debit.paid','debit.fixed.zero'),corpses=5)
        for cid in ('debit.fixed','debit.cap','debit.skip','debit.gain','debit.mode','debit.paid','debit.fixed.zero'):self.play(g,cid)
        f=self.fact(g).intrinsic.player_corpses
        self.assertEqual((f.quantity,self.price(g),f.corpse_spend_history_length),(8,1,4))
        self.assertEqual([row.amount for row in f.records],[2,3,3,0])
        self.assertEqual([row.origin for row in f.records],['fixed','capped','payment','fixed'])
        self.assertEqual(g.state.resource_operations,[]);self.check(g);self.typed(g,self.fact(g).intrinsic)

    def test_capped_actual_units_are_not_requested_cap_or_operation_count(self):
        g=self.game((NATIVE,'debit.cap'),corpses=1);self.play(g,'debit.cap')
        self.assertEqual((self.price(g),self.fact(g).intrinsic.player_corpses.quantity),(8,1))

    def test_refund_does_not_erase_original_successful_consumption(self):
        g=self.game((NATIVE,'native.refund'),corpses=10);self.play(g,'native.refund')
        self.assertEqual((g.state.players[1].resources[debits.Resource.CORPSES],self.price(g)),(12,7))

    def test_skipped_zero_gain_and_failed_root_do_not_reduce_by_request_or_balance(self):
        g=self.game((NATIVE,'debit.skip','debit.fixed.zero','debit.gain','debit.fault'),corpses=0)
        for cid in ('debit.skip','debit.fixed.zero','debit.gain'):self.play(g,cid)
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'debit.fault')
        self.assertEqual(g.snapshot(),saved);self.assertEqual((self.price(g),spent_corpses(g.state,1)),(9,0))
        self.assertEqual(self.fact(g).intrinsic.player_corpses.corpse_spend_history_length,1)

    def test_actual_payers_have_independent_units_with_unselected_rows_retained(self):
        g=self.game((NATIVE,'debit.fixed'),enemy_hand=(NATIVE,'debit.cap'))
        self.play(g,'debit.fixed');g.apply(EndTurn(1));self.play(g,'debit.cap')
        first=self.fact(g,1).intrinsic.player_corpses;second=self.fact(g,2).intrinsic.player_corpses
        self.assertEqual((self.price(g,1),self.price(g,2)),(7,6))
        self.assertEqual(first.records,second.records);self.assertEqual(len(first.records),2)

    def test_acquisition_after_spending_uses_all_previous_actual_units(self):
        g=self.game(('debit.fixed','native.acquire'));self.play(g,'debit.fixed');self.play(g,'native.acquire')
        self.assertEqual(self.price(g),7);self.check(g)

    def test_actual_turn_handoff_does_not_reset_all_game_units(self):
        g=self.game((NATIVE,'debit.fixed'));self.play(g,'debit.fixed');g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual((self.price(g),self.fact(g).intrinsic.player_corpses.records[0].turn),(7,1));self.check(g)

    def test_quantity_remains_complete_even_after_floor_reaches_zero(self):
        g=self.game((NATIVE,'native.large'),corpses=20);self.play(g,'native.large')
        f=self.fact(g).intrinsic.player_corpses
        self.assertEqual((self.price(g),f.quantity,len(f.records)),(0,12,1));self.typed(g,self.fact(g).intrinsic)

    def test_quote_is_pure_detached_and_matches_current_generated_operand(self):
        g=self.five();saved=g.snapshot();physical=self.fact(g)
        generated=capture_generated_quote_fact(g.state,g.registry,1,NATIVE)
        self.assertEqual(physical.intrinsic.player_corpses,generated.intrinsic.player_corpses)
        self.assertEqual((physical.amount,generated.amount),(4,4));validate_generated_quote_fact(g.registry,generated)
        self.assertEqual(g.snapshot(),saved);self.typed(g,physical.intrinsic)

    def test_generated_initial_and_minimum_apply_after_original_intrinsic_quantity(self):
        g=self.five()
        f=capture_generated_quote_fact(g.state,g.registry,1,NATIVE,cost=CostSpec(set_to=6),minimum_cost=7)
        self.assertEqual((f.intrinsic.amount,f.local_amount,f.amount),(4,6,7));validate_generated_quote_fact(g.registry,f)

    def test_original_local_then_external_cost_layers_follow_quantity(self):
        g=self.five(('native.local','native.external'));self.play(g,'native.local');self.play(g,'native.external')
        f=self.fact(g);self.assertEqual((f.intrinsic.amount,f.local_amount,f.amount),(4,6,4))
        self.play(g);self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(4,6));self.check(g)

    def test_original_player_command_pays_once_and_plays_real8_8(self):
        g=self.five();port=g.for_player(1);dto=port.legal_actions()
        row=next(row for row in g.observe(1)['players'][0]['hand'] if row['card_id']==NATIVE)
        action=next(action for action in dto['actions'] if action.get('card')==row['ref'])
        self.assertTrue(port.submit({'revision':dto['revision'],'action':action})['accepted'])
        e=g.state.entities[g.state.players[1].board[0]]
        self.assertEqual((e.attack,e.health,g.state.play_history[-1].cost,g.state.players[1].mana),(8,8,4,6))
        self.assertEqual(spent_corpses(g.state,1),5);self.check(g)

    def test_original_corpse_payment_prices_before_its_own_debit_and_freezes_once(self):
        g=self.five(('native.currency',NATIVE),corpses=9);self.play(g,'native.currency');self.play(g)
        record=g.state.play_history[-1];f=record.submitted_cost.quote.intrinsic.player_corpses
        self.assertEqual((record.cost,record.payment,f.quantity,spent_corpses(g.state,1)),(4,PaymentType.CORPSES,5,9))
        self.assertEqual((g.state.players[1].resources[debits.Resource.CORPSES],self.price(g)),(0,0))
        self.assertEqual([row.amount for row in f.records],[2,3]);self.check(g)

    def test_ordinary_copy_to_other_player_recomputes_recipient_quantity(self):
        g=self.five(('native.copy',));self.play(g,'native.copy')
        self.assertEqual((self.price(g,1),self.price(g,2)),(4,9));self.check(g)

    def test_transform_from_plain_face_uses_preserved_player_history(self):
        g=self.game(('card.1','debit.fixed','native.to.face'));self.play(g,'debit.fixed');self.play(g,'native.to.face')
        self.assertEqual(self.price(g),7);self.check(g)

    def test_transform_to_plain_face_removes_formula_without_erasing_history(self):
        g=self.five(('native.transform',));source=self.source(g).id;self.play(g,'native.transform')
        self.assertEqual((g.state.entities[source].card_id,g.quote_cost(source).amount,spent_corpses(g.state,1)),('card.1',1,5))
        self.check(g)

    def test_silence_then_bounce_restores_printed_face_with_same_global_history(self):
        g=self.game((NATIVE,'debit.fixed','native.silence','native.bounce'));self.play(g,'debit.fixed');self.play(g)
        self.play(g,'native.silence');self.play(g,'native.bounce')
        self.assertEqual((self.source(g).base_cost,self.price(g),spent_corpses(g.state,1)),(9,7,2));self.check(g)

    def test_death_corpse_gain_is_not_consumption_and_does_not_reprice(self):
        g=self.five((NATIVE,'native.destroy'));self.play(g);before=spent_corpses(g.state,1);self.play(g,'native.destroy')
        self.assertEqual((spent_corpses(g.state,1),self.price(g)),(before,4));self.check(g)

    def waiting(self, watcher, completed):
        g=self.five(board=(watcher,),typed=True);self.play(g)
        record=g.state.play_history[-1];old=record.submitted_cost.quote.intrinsic
        self.assertEqual((record.cost,record.completed,old.player_corpses.quantity),(4,completed,5))
        restored=self.check(g,typed=True);clone=g.clone();self.typed(g,old)
        action=SelectChoice(1,g.state.pending_choice.id,('more',));g.apply(action)
        for other in (restored,clone):other.apply(action);self.assertEqual(other.snapshot(),g.snapshot())
        self.assertEqual((self.price(g),g.state.play_history[-1].cost,g.state.players[1].mana),(2,4,6))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,5)
        validate_intrinsic_history_prefix(old,g.state,g.registry);self.assertEqual(old.player_corpses.quantity,5)
        self.check(g,typed=True)

    def test_committed_window_waiting_restores_original_payment_and_future_price(self):
        self.waiting('native.committed.watch',False)

    def test_completed_window_waiting_restores_original_payment_and_future_price(self):
        self.waiting('native.completed.watch',True)

    def test_failed_selection_restores_saved_original_price_history_and_choice(self):
        g=self.five(board=('native.completed.watch',),typed=True);self.play(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,g.state.pending_choice.id,('fault',)))
        self.assertEqual(g.snapshot(),saved);self.check(g,typed=True)

    def test_late_listener_failure_rolls_back_payment_and_native_entry(self):
        g=self.five(board=('native.fail.watch',));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),saved);self.assertEqual(self.price(g),4)

    def test_compact_original_prefix_allows_later_debits_without_repricing_old_quote(self):
        g=self.five(('debit.fixed',));old=self.fact(g).intrinsic;self.play(g,'debit.fixed')
        validate_prefix(old.player_corpses,g.state,g.registry);validate_intrinsic_history_prefix(old,g.state,g.registry)
        self.assertEqual((old.amount,self.price(g)),(4,2))
        with self.assertRaises(ValueError):validate_intrinsic_origin(old,g.state,g.registry)

    def test_equal_quantity_altered_unselected_payer_prefix_is_rejected(self):
        g=self.game((NATIVE,'debit.fixed'),enemy_hand=('debit.fixed',));self.play(g,'debit.fixed')
        g.apply(EndTurn(1));self.play(g,'debit.fixed');old=self.fact(g,1).intrinsic
        rows=old.player_corpses.records
        altered=replace(rows[1],balance_before=rows[1].balance_before+1,balance_after=rows[1].balance_after+1)
        changed=replace(old,player_corpses=replace(old.player_corpses,records=(rows[0],altered)))
        self.assertEqual(changed.amount,old.amount)
        with self.assertRaises(ValueError):validate_intrinsic_history_prefix(changed,g.state,g.registry)

    def test_frozen_operand_rejects_malformed_history_clock_quantity_and_bounds(self):
        g=self.five();f=self.fact(g).intrinsic.player_corpses
        with self.assertRaises(FrozenInstanceError):f.quantity=0
        for changes in (dict(player_id=True),dict(quantity=True),dict(quantity=2),dict(turn=0),dict(action=0),
                dict(records=list(f.records)),dict(corpse_spend_history_length=1),dict(records=tuple(reversed(f.records))),
                dict(next_resource_operation_id=1),dict(next_entity_id=f.records[1].source_id),dict(after=9)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(f,**changes)

    def test_finite_declarations_reject_unknown_types_shapes_and_multiple_formulas(self):
        for profile in ('unknown','cost.player-corpse-spent-turn-v1',None,True):
            with self.subTest(profile=profile),self.assertRaises(ValueError):PlayerCorpseSpendCostSpec(profile)
        card=registry().card(NATIVE)
        for changes in (dict(player_corpse_spend_cost=True),dict(kind=CardType.SPELL),dict(choice_only=True),
                dict(player_summon_count_cost=PlayerSummonCountCostSpec())):
            with self.subTest(changes=changes),self.assertRaises(ValueError):validate_definition(replace(card,**changes))

    def test_physical_source_cannot_borrow_future_allocation_even_with_same_price(self):
        g=self.game(('debit.fixed','debit.cap','native.acquire'))
        for cid in ('debit.fixed','debit.cap','native.acquire'):self.play(g,cid)
        full=self.fact(g);source=self.source(g)
        f=replace(full.intrinsic.player_corpses,next_entity_id=source.id)
        with self.assertRaises(ValueError):replace(full,intrinsic=replace(full.intrinsic,player_corpses=f))

    def test_typed_and_dictionary_stage_require_explicit_null_leaf(self):
        g=self.game(('debit.fixed',));source=self.source(g,'debit.fixed')
        stage=capture_quote_fact(g.state,g.registry,capture_cost_input(source)).intrinsic
        self.assertIsNone(stage.player_corpses)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);wire=codec.encode(stage)
        del wire['fields']['player_corpses']
        with self.assertRaises(ValueError):codec.decode(wire)
        raw=json.loads(json.dumps(asdict(stage)));del raw['player_corpses']
        with self.assertRaises(ValueError):_intrinsic_stage_from_dict(raw)

    def test_rehashed_paid_wire_rejects_missing_extra_shortened_and_rewritten_cost_operand(self):
        g=self.five();self.play(g);saved=g.snapshot()
        for mode in ('missing','extra','quantity','length','drop','balance','operation','source','clock'):
            bad=deepcopy(saved);stage=bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic'];f=stage['player_corpses']
            if mode=='missing':del stage['player_corpses']
            elif mode=='extra':f['invented']=1
            elif mode=='quantity':f['quantity']=True
            elif mode=='length':f['corpse_spend_history_length']-=1
            elif mode=='drop':f['records'].pop()
            elif mode=='balance':f['records'][0]['balance_before']+=1;f['records'][0]['balance_after']+=1
            elif mode=='operation':f['records'][1]['operation_id']=999
            elif mode=='source':f['records'][1]['source_card_id']='unknown.original.debit'
            else:f['action']+=1
            with self.subTest(mode=mode),self.assertRaises(SnapshotError) as error:Game.from_snapshot(rehash(bad),registry())
            self.assertNotIn('digest mismatch',str(error.exception).lower())

    def test_typed_record_field_loss_and_same_quantity_source_forgery_are_rejected(self):
        g=self.five();stage=self.fact(g).intrinsic;codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        wire=codec.encode(stage);row=wire['fields']['player_corpses']['fields']['records']['tuple'][1]
        del row['fields']['source_card_id']
        with self.assertRaises(ValueError):codec.decode(wire)
        changed_row=replace(stage.player_corpses.records[1],source_card_id='unknown.original.debit')
        changed=replace(stage,player_corpses=replace(stage.player_corpses,records=(stage.player_corpses.records[0],changed_row)))
        with self.assertRaises(ValueError):validate_intrinsic_stage_fact(g.registry,changed)

    def test_player_prices_are_visible_but_original_debit_inventory_is_private(self):
        g=self.five();before=g.snapshot()
        own=next(row for row in g.observe(1)['players'][0]['hand'] if row['card_id']==NATIVE)
        self.assertEqual(own['cost'],{'amount':4,'payment':'mana'})
        for player in (1,2):
            text=json.dumps(g.observe(player))+json.dumps(g.player_events(player))+json.dumps(g.for_player(player).legal_actions())
            for field in ('player_corpses','corpse_spend_history','corpse_spend_history_length','balance_before','submitted_cost'):
                self.assertNotIn('"'+field+'"',text)
        self.assertNotIn(NATIVE,json.dumps(g.observe(2)));self.assertEqual(g.snapshot(),before)

    def test_schema210_new_leaf_and_old_current_hosts_are_rejected(self):
        g=self.five();saved=g.snapshot()
        self.assertEqual((saved['schema_version'],g.ruleset.id,g.mechanics.version),(266,'prototype-v302',CORE_EFFECTS_VERSION))
        for version in (1,209,217,True,216.0):
            bad=deepcopy(saved);bad['schema_version']=version
            with self.subTest(version=version),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())
        self.check(g)


if __name__=='__main__':unittest.main()
