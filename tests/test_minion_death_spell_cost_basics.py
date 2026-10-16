"""Real ordinary Spell consumer of the existing finite minion death price."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

import test_minion_death_cost_basics as foundation
from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, EndTurn, Game,
    IllegalAction, IntrinsicCostSpec, MinionDeathCostSpec, PlayerSetup, PlayCard, Rarity,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec)
from hs_sim.engine.costs import capture_cost_input, capture_generated_quote_fact, capture_quote_fact
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Destroy, Draw,
    InvokeBehavior, ModifyCost, RequestChoice)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact, validate_intrinsic_history_prefix,
    validate_intrinsic_origin)
from hs_sim.engine.minion_death_costs import validate_definition
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

VIGIL = 'BRM_001'
PROFILE = 'cost.minion-deaths-both-turn-v1'
SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/minion-death-spell-cost-basics.json'
PIN = '04f29c137bd187647bc6d4f68c2041e4f5dfd93e8be37e0b334fb917efa8f8b7'


def evidence():
    support = json.loads(SUPPORT.read_text(encoding='utf-8'))
    if canonical_digest(support) != PIN:
        raise ValueError('Death Spell evidence changed')
    row, = support['records']
    if row['id'] != VIGIL or canonical_digest(row['data']) != row['data_sha256']:
        raise ValueError('Death Spell raw changed')
    return row['data']


def registry():
    r = foundation.registry()
    raw = evidence()
    r.register_behavior('s.vigil', lambda c: (Draw(c.player_id, 2),))
    r.register_card(CardDefinition(VIGIL, raw['name'], CardType.SPELL, cost=raw['cost'],
        metadata=metadata(CardClass.PALADIN, rarity=Rarity.COMMON), on_play='s.vigil',
        minion_death_cost=MinionDeathCostSpec(PROFILE)))
    r.register_behavior('s.acquire', lambda c: (AddToHand(c.player_id, VIGIL),))
    r.register_card(CardDefinition('s.acquire', 'Late acquisition probe', CardType.SPELL, on_play='s.acquire'))
    def held(c):
        return next(eid for eid in c.state.players[c.player_id].hand if c.state.entities[eid].card_id == VIGIL)
    r.register_behavior('s.local', lambda c: (ModifyCost(held(c), CostSpec(set_to=4)),))
    r.register_card(CardDefinition('s.local', 'Original local layer probe', CardType.SPELL, on_play='s.local'))
    r.register_behavior('s.external', lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-2, card_ids=(VIGIL,))),))
    r.register_card(CardDefinition('s.external', 'Original external layer probe', CardType.SPELL, on_play='s.external'))

    def pause(c):
        target = next((eid for eid in c.state.players[c.player_id].board
            if c.state.entities[eid].card_id == 'death.victim'), None)
        extra = () if target is None else (Destroy(target, c.source_id),)
        return (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Continue original root', (*extra, AddToHand(c.player_id, VIGIL))),
            ChoiceOption('fault', 'Delayed rollback probe', (InvokeBehavior('death.fail', c.source_id, c.player_id),)),
        ), c.source_id),)

    r.register_behavior('s.draw.pause', lambda c: pause(c)
        if c.event.player_id == c.player_id and len(c.state.draw_history) == 1 else ())
    r.register_card(CardDefinition('s.draw.watch', 'First ordinary draw capture probe', CardType.MINION,
        health=5, triggers=(TriggerSpec('card_drawn', 's.draw.pause'),)))
    r.register_behavior('s.paid.pause', lambda c: pause(c)
        if c.state.entities[c.event.source_id].card_id == VIGIL else ())
    r.register_card(CardDefinition('s.paid.watch', 'Original completed Spell window probe', CardType.MINION,
        health=5, triggers=(TriggerSpec('card_played', 's.paid.pause'),)))
    r.register_behavior('s.draw.fail', lambda c: (AddToHand(c.player_id, 'unknown.death.spell.price'),))
    r.register_card(CardDefinition('s.draw.fail.watch', 'Draw rollback probe', CardType.MINION,
        health=5, triggers=(TriggerSpec('card_drawn', 's.draw.fail'),)))
    r.register_behavior('s.counter', lambda c: (CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id != c.player_id and c.state.entities[c.event.source_id].card_id == VIGIL else ())
    r.register_card(CardDefinition('s.counter.watch', 'Original Spell counter probe', CardType.MINION,
        health=5, triggers=(TriggerSpec('card_committed', 's.counter'),)))
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
        if k not in ('schema_version','events','events_hash','state_hash')})
    return saved


class MinionDeathSpellCostTests(unittest.TestCase):
    play = foundation.MinionDeathCostTests.play
    choose = foundation.MinionDeathCostTests.choose
    victim = foundation.MinionDeathCostTests.victim

    def game(self, hand=(VIGIL,), *, board=(), enemy_board=(), enemy_hand=(),
             deck=('card.1','card.2','card.3','card.4'), mana=10, weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, deck=deck, mana=mana, max_mana=10,
                weapon_card_id=weapon),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy_board, deck=('card.1',)*4,
                mana=10, max_mana=10)), seed=23), registry())

    def source(self, g, cid=VIGIL, player=1):
        return next(g.state.entities[eid] for eid in g.state.players[player].hand if g.state.entities[eid].card_id == cid)

    def fact(self, g, cid=VIGIL, player=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g,cid,player)))

    def price(self, g, player=1):
        return self.fact(g,player=player).amount

    def two(self, extras=(), *, board=(), enemy_board=(), victims=2):
        g = self.game((VIGIL,'death.kill','death.kill',*extras),
            board=('death.victim',)*victims+board, enemy_board=enemy_board)
        self.play(g,'death.kill',self.victim(g)); self.play(g,'death.kill',self.victim(g))
        return g

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for player in (1,2): self.assertEqual(other.observe(player),g.observe(player))
        return saved

    def test_single_complete_raw_is_pinned_and_native_body_is_only_original_draw_two(self):
        raw=evidence()
        original=json.loads((SUPPORT.parents[1]/'extracted/cards.json').read_bytes())
        self.assertEqual(raw,next(row for row in original if row['id']==VIGIL))
        d=registry().card(VIGIL)
        self.assertEqual((d.kind,d.cost,d.metadata.classes,d.metadata.rarity),
            (CardType.SPELL,5,(CardClass.PALADIN,),Rarity.COMMON))
        self.assertEqual(d.minion_death_cost,MinionDeathCostSpec(PROFILE))
        self.assertIsNone(d.battlecry)
        self.assertEqual(d.intrinsic_costs,())

    def test_only_ordinary_minion_or_spell_uses_this_existing_finite_input(self):
        d=registry().card(VIGIL)
        validate_definition(d)
        for changed in (replace(d,kind=CardType.WEAPON,attack=1,durability=2),
                replace(d,choice_only=True),replace(d,intrinsic_costs=(IntrinsicCostSpec(delta=-1),))):
            with self.subTest(changed=changed),self.assertRaises(ValueError): validate_definition(changed)

    def test_initial_native_price_five_pays_once_and_draws_two_real_cards(self):
        g=self.game(); self.assertEqual(self.price(g),5)
        self.play(g,VIGIL)
        self.assertEqual((g.state.players[1].mana,g.state.play_history[-1].cost,len(g.state.draw_history)),(5,5,2))
        self.assertEqual(len(g.state.cast_history),1)
        self.assertEqual(g.state.play_history[-1].submitted_cost.quote.intrinsic.minion_deaths.quantity,0)
        self.portable(g)

    def test_both_sides_same_turn_deaths_discount_the_actual_spell(self):
        g=self.game((VIGIL,'death.area'),board=('death.victim',),enemy_board=('death.victim',)*2)
        self.play(g,'death.area'); f=self.fact(g).intrinsic.minion_deaths
        self.assertEqual((f.quantity,f.selected_ids,self.price(g)),(3,(1,2,3),2))
        self.play(g,VIGIL)
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana,len(g.state.draw_history)),(2,8,2))
        self.portable(g)

    def test_same_face_deaths_count_distinct_occurrences(self):
        g=self.two(); self.assertEqual((self.price(g),self.fact(g).intrinsic.minion_deaths.quantity),(3,2))
        self.assertEqual(len({row.card_id for row in g.state.death_history}),1)

    def test_actual_deaths_before_acquisition_are_available(self):
        g=self.game(('death.area','s.acquire'),board=('death.victim',),enemy_board=('death.victim',)*2)
        self.play(g,'death.area'); self.play(g,'s.acquire')
        self.assertEqual(self.price(g),2); self.portable(g)

    def test_current_turn_resets_new_quotes_and_keeps_old_complete_prefix(self):
        g=self.two(); original=self.fact(g).intrinsic
        validate_intrinsic_origin(original,g.state,g.registry)
        g.apply(EndTurn(1)); self.assertEqual(self.price(g),5)
        g.apply(EndTurn(2)); self.assertEqual(self.price(g),5)
        validate_intrinsic_history_prefix(original,g.state,g.registry)
        self.assertEqual((original.amount,original.minion_deaths.quantity),(3,2))
        self.portable(g)

    def test_physical_generated_and_player_prices_use_identical_existing_stage(self):
        g=self.two(); physical=self.fact(g)
        generated=capture_generated_quote_fact(g.state,g.registry,1,VIGIL)
        self.assertEqual((physical.intrinsic,physical.amount),(generated.intrinsic,generated.amount))
        validate_generated_quote_fact(g.registry,generated)
        self.assertEqual(g.observe(1)['players'][0]['hand'][0]['cost']['amount'],3)

    def test_quantity_beyond_printed_cost_floors_zero_and_still_draws_two(self):
        g=self.game((VIGIL,'death.area'),board=('death.victim',)*3,enemy_board=('death.victim',)*3)
        self.play(g,'death.area'); self.assertEqual(self.price(g),0)
        generated=capture_generated_quote_fact(g.state,g.registry,1,VIGIL,minimum_cost=2)
        self.assertEqual((generated.intrinsic.amount,generated.amount),(0,2))
        self.play(g,VIGIL)
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana,len(g.state.draw_history)),(0,10,2))
        self.portable(g)

    def test_original_local_and_external_cost_layers_follow_the_same_quantity(self):
        g=self.two(('s.local','s.external')); self.play(g,'s.local'); self.play(g,'s.external')
        f=self.fact(g); self.assertEqual((f.intrinsic.amount,f.local_amount,f.amount),(3,4,2))
        generated=capture_generated_quote_fact(g.state,g.registry,1,VIGIL,cost=CostSpec(set_to=4))
        self.assertEqual(generated.amount,2)
        self.play(g,VIGIL); self.assertEqual(g.state.play_history[-1].cost,2); self.portable(g)

    def test_player_native_command_pays_the_visible_price_and_draws(self):
        g=self.two(); port=g.for_player(1); dto=port.legal_actions()
        card=next(v for v in g.observe(1)['players'][0]['hand'] if v['card_id']==VIGIL)
        action=next(v for v in dto['actions'] if v.get('card')==card['ref'])
        self.assertTrue(port.submit({'revision':dto['revision'],'action':action})['accepted'])
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana,len(g.state.draw_history)),(3,7,2))
        self.portable(g)

    def test_insufficient_payment_does_not_draw_or_commit_anything(self):
        g=self.game(mana=4); before=g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g,VIGIL)
        self.assertEqual(g.snapshot(),before)

    def test_weapon_destruction_is_kept_in_full_prefix_but_does_not_discount(self):
        g=self.game((VIGIL,'death.destroy.weapon'),weapon='death.weapon')
        self.play(g,'death.destroy.weapon'); f=self.fact(g).intrinsic.minion_deaths
        self.assertEqual((len(f.records),f.quantity,self.price(g)),(1,0,5)); self.portable(g)

    def test_original_complete_death_batch_is_visible_during_first_listener_choice(self):
        g=self.game((VIGIL,'death.area'),board=('death.victim','death.batch.watch'),enemy_board=('death.victim',)*2)
        self.play(g,'death.area'); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((self.price(g),self.fact(g).intrinsic.minion_deaths.quantity),(2,3))
        self.portable(g); self.choose(g); self.assertEqual(self.price(g),2); self.portable(g)

    def test_original_spell_counter_keeps_paid_quote_and_skips_native_draw_body(self):
        g=self.two(enemy_board=('s.counter.watch',)); self.play(g,VIGIL)
        record=g.state.play_history[-1]
        self.assertEqual((record.countered,record.cost,g.state.players[1].mana,len(g.state.draw_history)),(True,3,7,0))
        self.assertEqual(record.submitted_cost.quote.intrinsic.minion_deaths.quantity,2)
        self.portable(g)

    def test_first_draw_choice_restores_then_later_death_does_not_reprice_paid_root(self):
        g=self.two(board=('s.draw.watch',),victims=3); self.play(g,VIGIL)
        self.assertEqual(len(g.state.draw_history),1); self.assertIsNotNone(g.state.pending_choice)
        saved=self.portable(g); other=Game.from_snapshot(saved,registry())
        original=g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.choose(g); self.choose(other); self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual((len(g.state.draw_history),len(g.state.death_history),self.price(g),g.state.play_history[-1].cost),(2,3,2,3))
        validate_intrinsic_history_prefix(original,g.state,g.registry); self.portable(g)

    def test_delayed_error_restores_first_draw_choice_and_original_paid_price(self):
        g=self.two(board=('s.draw.watch',),victims=3); self.play(g,VIGIL); before=self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
        self.assertEqual(g.state.play_history[-1].cost,3)

    def test_completed_spell_can_wait_and_preserve_its_original_quantity(self):
        g=self.two(board=('s.paid.watch',),victims=3); self.play(g,VIGIL)
        self.assertTrue(g.state.play_history[-1].completed); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(g.state.draw_history),2); self.portable(g)
        original=g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.choose(g)
        self.assertEqual((self.price(g),g.state.play_history[-1].cost),(2,3))
        validate_intrinsic_history_prefix(original,g.state,g.registry); self.portable(g)

    def test_failure_during_draw_rolls_back_payment_cast_draw_and_events(self):
        g=self.two(board=('s.draw.fail.watch',)); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,VIGIL)
        self.assertEqual(g.snapshot(),before)

    def test_empty_deck_uses_original_fatigue_without_inventing_minion_deaths(self):
        g=self.game(deck=()); self.play(g,VIGIL)
        self.assertEqual((g.state.play_history[-1].cost,len(g.state.death_history),len(g.state.draw_history)),(5,0,2))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27)
        self.portable(g)

    def test_rehashed_paid_spell_requires_the_existing_full_death_fact_and_subject(self):
        g=self.two(); self.play(g,VIGIL); saved=self.portable(g)
        for mode in ('quantity','field','none','records','selection','kind'):
            bad=deepcopy(saved); stage=bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']
            f=stage['minion_deaths']
            if mode=='quantity': f['quantity']+=1
            elif mode=='field': del stage['minion_deaths']
            elif mode=='none': stage['minion_deaths']=None
            elif mode=='records': f['records']=[]
            elif mode=='selection': f['selected_ids']=[]
            else: stage['kind']='minion'
            with self.subTest(mode=mode),self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad),registry())

    def test_quotes_and_views_are_pure_and_do_not_expose_private_death_or_payment_facts(self):
        g=self.two(); before=g.snapshot()
        for _ in range(2):
            self.assertEqual(self.price(g),3)
            capture_generated_quote_fact(g.state,g.registry,1,VIGIL)
            for player in (1,2):
                text=json.dumps(g.observe(player))
                for private in ('death_history','minion_deaths','selected_ids','submitted_cost','payment_state'):
                    self.assertNotIn(private,text)
        self.assertEqual(g.snapshot(),before)

    def test_rule_semantics_advance_while_the_strict_snapshot_layout_stays_201(self):
        g=self.two(); self.play(g,VIGIL); saved=self.portable(g)
        self.assertEqual((g.ruleset.id,g.mechanics.version,saved['schema_version']),('prototype-v302',CORE_EFFECTS_VERSION,SNAPSHOT_SCHEMA_VERSION))
        bad=deepcopy(saved); bad['ruleset']['id']='prototype-v213'
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad),registry())


if __name__=='__main__': unittest.main()
