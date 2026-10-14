"""Current-turn original physical draws and one necessary ordinary Spell."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import unittest

import test_player_draw_count_cost_basics as foundation
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardType, CostSpec, EndTurn, Game,
    IllegalAction, IntrinsicCostSpec, PlayerDrawCountCostSpec, PlayerSetup, PlayCard, Rarity,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec)
from hs_sim.engine.costs import capture_cost_input, capture_generated_quote_fact, capture_quote_fact
from hs_sim.engine.effects import (AddCostModifier, AddToHand, Buff, ChoiceOption, Draw,
    InvokeBehavior, ModifyCost, RequestChoice)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact, validate_intrinsic_history_prefix,
    validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.player_draw_count_costs import validate_definition
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, setup

MOMENTUM = 'TTN_841'
PROFILE = 'cost.player-physical-draw-count-turn-v1'
SUPPORT = Path(__file__).resolve().parents[1]/'data/support/player-draw-turn-spell-cost-basics.json'
PIN = 'e3a8f09699ffd497480c9821e67752aef378338e65b6d9dc2f5e6dfa4fb768c1'


def evidence():
    value = json.loads(SUPPORT.read_text(encoding='utf-8'))
    if canonical_digest(value) != PIN: raise ValueError('Current-turn draw Spell evidence changed')
    row, = value['records']
    if row['id'] != MOMENTUM or canonical_digest(row['data']) != row['data_sha256']:
        raise ValueError('Current-turn draw Spell complete raw changed')
    return row['data']


def registry():
    r = foundation.registry()
    raw = evidence()
    r.register_behavior('t.momentum', lambda c: (Buff(c.state.players[c.player_id].hero_id,
        4, 0, c.source_id, expires_turn=c.state.turn),))
    r.register_card(CardDefinition(MOMENTUM, raw['name'], CardType.SPELL, cost=raw['cost'],
        metadata=metadata(CardClass.DEMON_HUNTER, rarity=Rarity.RARE), on_play='t.momentum',
        player_draw_count_cost=PlayerDrawCountCostSpec(PROFILE)))
    # Synthetic probes exercise only the same real finite input or existing effects.
    r.register_card(CardDefinition('t.turn.minion', 'Current-turn input type probe', CardType.MINION,
        cost=5, attack=1, health=1, player_draw_count_cost=PlayerDrawCountCostSpec(PROFILE)))
    def held(c):
        return next(c.state.entities[eid] for eid in c.state.players[c.player_id].hand
            if c.state.entities[eid].card_id == MOMENTUM)
    bodies = {
        't.acquire':lambda c:(AddToHand(c.player_id,MOMENTUM),),
        't.six':lambda c:(Draw(c.player_id,6,c.source_id),),
        't.local':lambda c:(ModifyCost(held(c).id,CostSpec(set_to=4)),),
        't.external':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-2,card_ids=(MOMENTUM,))),),
        't.copy.enemy':lambda c:(CopyCard(CardReference.capture(held(c)),3-c.player_id,mode='base'),),
    }
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    def pause(c):
        return (RequestChoice(c.player_id,(
            ChoiceOption('continue','Continue original completed Spell',
                (Draw(c.player_id,source_id=c.source_id),AddToHand(c.player_id,MOMENTUM))),
            ChoiceOption('fault','Delayed original rollback',
                (InvokeBehavior('d.fail',c.source_id,c.player_id),)),
        ),c.source_id),)
    r.register_behavior('t.paid.wait',lambda c:pause(c)
        if c.state.entities[c.event.source_id].card_id == MOMENTUM else ())
    r.register_card(CardDefinition('t.paid.watch','Completed payment probe',CardType.MINION,health=5,
        triggers=(TriggerSpec('card_played','t.paid.wait'),)))
    r.register_behavior('t.paid.fail',lambda c:(AddToHand(c.player_id,'unknown.draw.turn.price'),)
        if c.state.entities[c.event.source_id].card_id == MOMENTUM else ())
    r.register_card(CardDefinition('t.fail.watch','Late root rollback probe',CardType.MINION,health=5,
        triggers=(TriggerSpec('card_played','t.paid.fail'),)))
    r.register_behavior('t.counter',lambda c:(CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id != c.player_id and c.state.entities[c.event.source_id].card_id == MOMENTUM else ())
    r.register_card(CardDefinition('t.counter.watch','Existing Spell counter probe',CardType.MINION,health=5,
        triggers=(TriggerSpec('card_committed','t.counter'),)))
    return r


class PlayerDrawTurnSpellCostTests(unittest.TestCase):
    choose = foundation.PlayerDrawCountCostTests.choose
    typed = foundation.PlayerDrawCountCostTests.typed

    def game(self,hand=(MOMENTUM,),*,board=(),enemy_board=(),enemy_hand=(),
            deck=('card.1',)*12,enemy_deck=('card.2',)*5,mana=10):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero',hand=hand,board=board,deck=deck,mana=mana,max_mana=10),
            PlayerSetup('warrior.hero',hand=enemy_hand,board=enemy_board,deck=enemy_deck,
                mana=10,max_mana=10)),seed=41),registry())

    def source(self,g,cid=MOMENTUM,player=1):
        return next(g.state.entities[eid] for eid in g.state.players[player].hand
            if g.state.entities[eid].card_id == cid)

    def play(self,g,cid=MOMENTUM):
        player=g.state.active_player
        g.apply(PlayCard(player,self.source(g,cid,player).id))

    def fact(self,g,cid=MOMENTUM,player=1):
        return capture_quote_fact(g.state,g.registry,capture_cost_input(self.source(g,cid,player)))

    def price(self,g,player=1): return self.fact(g,player=player).amount

    def two(self,extras=(),**kwargs):
        g=self.game((MOMENTUM,'d.two',*extras),**kwargs)
        self.play(g,'d.two')
        return g

    def hero(self,g,player=1): return g.state.entities[g.state.players[player].hero_id]

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for player in (1,2): self.assertEqual(other.observe(player),g.observe(player))
        return saved

    def test_complete_native_five_cost_rare_demon_hunter_raw_and_only_original_buff_body(self):
        raw=evidence()
        rows=json.loads((SUPPORT.parents[1]/'extracted/cards.json').read_bytes())
        self.assertEqual(raw,next(row for row in rows if row['id']==MOMENTUM))
        d=registry().card(MOMENTUM)
        self.assertEqual((d.cost,d.kind,d.metadata.classes,d.metadata.rarity),
            (5,CardType.SPELL,(CardClass.DEMON_HUNTER,),Rarity.RARE))
        self.assertIsNone(d.battlecry)
        self.assertIsNone(d.spell_school)
        self.assertEqual(d.player_draw_count_cost,PlayerDrawCountCostSpec(PROFILE))

    def test_two_finite_profiles_and_ordinary_types_still_reject_unreviewed_formulas(self):
        self.assertEqual(PlayerDrawCountCostSpec().profile_id,'cost.player-physical-draw-count-v1')
        d=registry().card(MOMENTUM); validate_definition(d)
        validate_definition(registry().card('t.turn.minion'))
        for profile in (True,None,'cost.player-physical-draw-count-all-players-v1'):
            with self.subTest(profile=profile),self.assertRaises(ValueError): PlayerDrawCountCostSpec(profile)
        for change in (dict(kind=CardType.WEAPON,durability=1),dict(choice_only=True),
                dict(intrinsic_costs=(IntrinsicCostSpec(delta=-1),)),dict(player_draw_count_cost='formula')):
            with self.subTest(change=change),self.assertRaises(ValueError):validate_definition(replace(d,**change))

    def test_empty_history_keeps_five_and_complete_empty_current_turn_fact(self):
        g=self.game(); f=self.fact(g).intrinsic.player_draws
        self.assertEqual((self.price(g),f.spec.profile_id,f.turn,f.records,f.selected_ids,f.quantity),
            (5,PROFILE,1,(),(),0))
        self.typed(g,self.fact(g).intrinsic); self.portable(g)

    def test_two_original_physical_draws_discount_by_two_without_changing_base(self):
        g=self.two(); f=self.fact(g).intrinsic.player_draws
        self.assertEqual((self.price(g),f.selected_ids,f.quantity,self.source(g).base_cost),(3,(1,2),2,5))
        self.portable(g)

    def test_current_turn_draws_before_acquisition_are_retained(self):
        g=self.game(('d.two','t.acquire')); self.play(g,'d.two'); self.play(g,'t.acquire')
        self.assertEqual((self.price(g),len(g.state.draw_history)),(3,2)); self.portable(g)

    def test_global_turn_filter_keeps_old_and_opponent_rows_and_counts_actual_payer(self):
        g=self.game((MOMENTUM,'d.one'),enemy_hand=('d.enemy',)); self.play(g,'d.one')
        old=self.fact(g).intrinsic
        g.apply(EndTurn(1)); self.assertEqual(self.price(g),5)
        self.play(g,'d.enemy'); f=self.fact(g).intrinsic.player_draws
        self.assertEqual((f.turn,f.selected_ids,f.quantity,self.price(g)),(2,(3,4),2,3))
        self.assertEqual(tuple(row.player_id for row in f.records),(1,2,1,1))
        g.apply(EndTurn(2)); f=self.fact(g).intrinsic.player_draws
        self.assertEqual((f.turn,f.selected_ids,len(f.records),self.price(g)),(3,(5,),5,4))
        validate_intrinsic_history_prefix(old,g.state,g.registry)
        self.assertEqual((old.amount,old.player_draws.quantity),(4,1)); self.portable(g)

    def test_current_turn_minion_uses_same_original_filtered_quantity(self):
        g=self.game(('t.turn.minion','d.two')); self.play(g,'d.two')
        self.assertEqual(self.fact(g,'t.turn.minion').amount,3)
        g.apply(EndTurn(1)); self.assertEqual(self.fact(g,'t.turn.minion').amount,5)
        self.portable(g)

    def test_fatigue_rows_do_not_reduce_price_but_remain_in_full_prefix(self):
        g=self.game((MOMENTUM,'d.one','d.one','d.one'),deck=('card.1',))
        for _ in range(3): self.play(g,'d.one')
        f=self.fact(g).intrinsic.player_draws
        self.assertEqual((self.price(g),f.quantity,tuple(row.outcome for row in f.records)),
            (4,1,('hand','fatigue','fatigue'))); self.portable(g)

    def test_burned_actual_draw_is_counted_using_original_acceptance(self):
        g=self.game((MOMENTUM,'d.two',*('card.1',)*8)); self.play(g,'d.two')
        f=self.fact(g).intrinsic.player_draws
        self.assertEqual((self.price(g),f.quantity,tuple(row.outcome for row in f.records)),
            (3,2,('hand','burned'))); self.portable(g)

    def test_cast_when_drawn_and_its_replacement_are_original_two_draws(self):
        g=self.game((MOMENTUM,'d.one'),deck=('d.auto','card.1')); self.play(g,'d.one')
        f=self.fact(g).intrinsic.player_draws
        self.assertEqual((self.price(g),f.quantity,f.selected_ids),(3,2,(1,2)))
        self.assertEqual(f.records[0].replacement_id,2); self.portable(g)

    def test_ordinary_draw_wait_restores_and_old_filtered_quote_stays_frozen(self):
        g=self.two(board=('d.draw.watch',)); old=self.fact(g).intrinsic
        self.assertEqual((old.amount,old.player_draws.records[0].phase),(4,'drawing'))
        saved=self.portable(g); other=Game.from_snapshot(saved,registry()); self.typed(g,old)
        self.choose(g); self.choose(other); self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(self.price(g),3)
        validate_intrinsic_history_prefix(old,g.state,g.registry); self.portable(g)

    def test_pending_automatic_draw_links_can_complete_under_the_same_current_turn_fact(self):
        g=self.game((MOMENTUM,'d.one'),deck=('d.auto','card.1'),board=('d.draw.watch',))
        self.play(g,'d.one'); old=self.fact(g).intrinsic
        self.assertEqual((old.amount,old.player_draws.records[0].phase,old.player_draws.records[0].cast_id),
            (4,'pending_cast',None))
        self.portable(g); self.choose(g)
        self.assertEqual(self.price(g),3)
        validate_intrinsic_history_prefix(old,g.state,g.registry); self.portable(g)

    def test_native_pays_three_once_and_uses_original_temporary_hero_attack_buff(self):
        g=self.two(); self.play(g); record=g.state.play_history[-1]
        self.assertEqual((record.cost,g.state.players[1].mana,self.hero(g).attack),(3,7,4))
        self.assertEqual((record.submitted_cost.quote.intrinsic.player_draws.quantity,
            record.submitted_cost.quote.intrinsic.player_draws.spec.profile_id),(2,PROFILE))
        self.assertEqual(tuple(e.expires_turn for e in self.hero(g).enchantments),(1,))
        self.portable(g)

    def test_native_hero_attack_uses_existing_attack_action_and_damage(self):
        g=self.two(); self.play(g)
        g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id))
        self.assertEqual((self.hero(g,2).health,self.hero(g).attacks_this_turn),(26,1)); self.portable(g)

    def test_native_attack_expires_and_new_turn_price_resets_while_old_payment_is_valid(self):
        g=self.two(); self.play(g); old=g.state.play_history[-1].submitted_cost.quote.intrinsic
        g.apply(EndTurn(1))
        self.assertEqual(self.hero(g).attack,0)
        self.assertEqual(capture_generated_quote_fact(g.state,g.registry,1,MOMENTUM).amount,5)
        validate_intrinsic_history_prefix(old,g.state,g.registry)
        g.apply(EndTurn(2))
        self.assertEqual(capture_generated_quote_fact(g.state,g.registry,1,MOMENTUM).amount,4)
        self.assertEqual(old.amount,3); self.portable(g)

    def test_six_physical_draws_floor_price_zero_before_original_generated_minimum(self):
        g=self.game((MOMENTUM,'t.six')); self.play(g,'t.six')
        generated=capture_generated_quote_fact(g.state,g.registry,1,MOMENTUM,minimum_cost=2)
        self.assertEqual((self.price(g),generated.intrinsic.amount,generated.amount),(0,0,2))
        validate_generated_quote_fact(g.registry,generated)
        self.play(g); self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(0,10))
        self.portable(g)

    def test_physical_generated_and_player_display_use_the_identical_current_turn_fact(self):
        g=self.two(); f=self.fact(g)
        generated=capture_generated_quote_fact(g.state,g.registry,1,MOMENTUM)
        self.assertEqual((f.intrinsic,f.amount),(generated.intrinsic,generated.amount))
        row=next(c for c in g.observe(1)['players'][0]['hand'] if c['card_id']==MOMENTUM)
        self.assertEqual(row['cost']['amount'],3); self.typed(g,f.intrinsic)

    def test_player_command_pays_the_visible_price_and_applies_native_body(self):
        g=self.two(); port=g.for_player(1); dto=port.legal_actions()
        row=next(c for c in g.observe(1)['players'][0]['hand'] if c['card_id']==MOMENTUM)
        action=next(a for a in dto['actions'] if a.get('card')==row['ref'])
        self.assertTrue(port.submit({'revision':dto['revision'],'action':action})['accepted'])
        self.assertEqual((g.state.play_history[-1].cost,self.hero(g).attack),(3,4)); self.portable(g)

    def test_original_local_and_external_cost_layers_override_after_filtered_intrinsic(self):
        g=self.two(('t.local','t.external')); self.play(g,'t.local'); self.play(g,'t.external')
        f=self.fact(g); self.assertEqual((f.intrinsic.amount,f.local_amount,f.amount),(3,4,2))
        self.play(g); self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(2,8))
        self.portable(g)

    def test_insufficient_mana_rolls_back_without_native_attack_or_a_new_draw(self):
        g=self.two(mana=2); before=g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g)
        self.assertEqual(g.snapshot(),before); self.assertEqual(self.hero(g).attack,0)

    def test_existing_counter_keeps_frozen_payment_and_skips_hero_attack(self):
        g=self.two(enemy_board=('t.counter.watch',)); self.play(g); record=g.state.play_history[-1]
        self.assertEqual((record.countered,record.cost,g.state.players[1].mana,self.hero(g).attack),(True,3,7,0))
        self.assertEqual(record.submitted_cost.quote.intrinsic.player_draws.quantity,2); self.portable(g)

    def test_completed_native_choice_later_draw_changes_new_quote_without_repricing_old_root(self):
        g=self.two(board=('t.paid.watch',)); self.play(g)
        old=g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.assertTrue(g.state.play_history[-1].completed); self.assertIsNotNone(g.state.pending_choice)
        saved=self.portable(g); other=Game.from_snapshot(saved,registry())
        self.choose(g); self.choose(other); self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual((self.price(g),g.state.play_history[-1].cost,g.state.players[1].mana,self.hero(g).attack),(2,3,7,4))
        validate_intrinsic_history_prefix(old,g.state,g.registry); self.portable(g)

    def test_delayed_choice_error_restores_original_payment_buff_and_draw_prefix(self):
        g=self.two(board=('t.paid.watch',)); self.play(g); before=self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
        self.assertEqual((g.state.play_history[-1].cost,self.hero(g).attack),(3,4))

    def test_late_native_body_error_rolls_back_whole_payment_and_original_buff(self):
        g=self.two(board=('t.fail.watch',)); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g)
        self.assertEqual(g.snapshot(),before); self.assertEqual(self.hero(g).attack,0)

    def test_printed_copy_uses_new_payer_original_draws_and_hero(self):
        g=self.two(('t.copy.enemy',)); self.play(g,'t.copy.enemy')
        self.assertEqual((self.price(g),self.price(g,2),self.source(g,player=2).base_cost),(3,5,5))
        g.apply(EndTurn(1)); self.assertEqual(self.price(g,2),4); self.play(g)
        self.assertEqual((self.hero(g).attack,self.hero(g,2).attack,g.state.play_history[-1].cost),(0,4,4))
        self.portable(g)

    def test_fact_checks_original_turn_payer_profile_and_excluded_previous_rows(self):
        g=self.two(); old=self.fact(g).intrinsic
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); stage=self.fact(g).intrinsic; f=stage.player_draws
        self.assertEqual((f.selected_ids,f.quantity),((4,),1))
        for change in (dict(selected_ids=(1,2,4),quantity=3,after=2),dict(turn=2),dict(quantity=True),
                dict(records=f.records[1:],draw_history_length=len(f.records)-1)):
            with self.subTest(change=change),self.assertRaises(ValueError): replace(f,**change)
        with self.assertRaises(ValueError):
            validate_intrinsic_stage_fact(g.registry,replace(stage,player_draws=replace(f,
                spec=PlayerDrawCountCostSpec(),selected_ids=(1,2,4),quantity=3,after=2),amount=2))
        validate_intrinsic_history_prefix(old,g.state,g.registry); validate_intrinsic_origin(stage,g.state,g.registry)
        self.typed(g,stage); self.portable(g)

    def test_rehashed_paid_wire_cannot_change_profile_turn_selection_or_complete_prefix(self):
        g=self.two(); g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g); saved=self.portable(g)
        for mode in ('profile','turn','selection','excluded','none'):
            bad=deepcopy(saved); stage=bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']
            f=stage['player_draws']
            if mode=='profile': f['spec']['profile_id']='cost.player-physical-draw-count-v1'
            elif mode=='turn': f['turn']=2
            elif mode=='selection': f['selected_ids']=[1,2,4]
            elif mode=='excluded': f['records']=f['records'][1:]
            else: stage['player_draws']=None
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):
                Game.from_snapshot(foundation.rehash(bad),registry())

    def test_opening_deal_and_mulligan_do_not_count_but_original_start_draw_does(self):
        r=registry(); g=Game.from_decks(setup(r),r)
        self.assertEqual(capture_generated_quote_fact(g.state,r,1,MOMENTUM).amount,5)
        while g.state.pending_choice is not None:
            q=g.state.pending_choice; g.apply(SelectChoice(q.player_id,q.id,()))
        self.assertEqual(capture_generated_quote_fact(g.state,r,1,MOMENTUM).amount,4); self.portable(g)

    def test_quotes_and_player_views_are_pure_and_keep_complete_draw_fact_private(self):
        g=self.two(); before=g.snapshot()
        for _ in range(2):
            self.assertEqual(self.price(g),3)
            capture_generated_quote_fact(g.state,g.registry,1,MOMENTUM)
            for player in (1,2):
                text=json.dumps(g.observe(player))
                for hidden in ('player_draws','draw_history','selected_ids','submitted_cost','draw_history_length'):
                    self.assertNotIn(hidden,text)
        self.assertEqual(g.snapshot(),before)


if __name__=='__main__': unittest.main()
