"""Actual Orb recasts one original spell per printed cost in ascending order."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import past_arcane_cost_history as native
from hs_sim.engine import (CardDefinition, CardType, CastSpell, EndTurn, Game, PlayCard,
    PlayerSetup, ResolutionError, Scenario, TriggerSpec)
from hs_sim.engine.automatic_targets import AutomaticTargetPreference
from hs_sim.engine.cost_history_recasts import validate_progress
from hs_sim.engine.effects import (ChoiceOption, Damage, GainArmor, InvokeBehavior, RequestChoice)
from hs_sim.engine.model import DamageKind, TargetSpec
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_history import (ContinueHistoryCasts, DiscoverSpellHistory, RecastFromHistory,
    SpellHistoryQuery, historical_groups, spell_history_candidates)
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.engine.model import CostSpec
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

CARD = native.CARD
P = 'k600.'
ZERO, ONE, OTHER, TWO, THREE, HIGH, HIT, FRIENDLY, AUTO, AUTO_ONE, WAIT, FAULT, FAIL, PRICE = (
    P+x for x in ('zero','one','other','two','three','high','hit','friendly','auto','auto_one','wait','fault','fail','price'))


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r = build_registry();native.register_past_arcane_cost_history(r)
    def failed(c):raise ResolutionError('K600 deliberate original recast failure')
    def faulty(c):
        if c.cast is not None and c.cast.origin == 'history':return (InvokeBehavior(FAULT,c.source_id,c.player_id),)
        return (GainArmor(c.player_id,4),)
    def price(c):
        entity = next((c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == HIGH),None)
        return () if entity is None else (ModifyStoredCost(CardReference.capture(entity),CostSpec(set_to=0),c.source_id),)
    def watch(c):
        if c.event.player_id != c.player_id:return ()
        current = c.state.cast_history[-1]
        if current.origin != 'history' or current.caster_id is None or c.state.entities[current.caster_id].card_id != CARD:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('add','Cast a new three-cost spell',(CastSpell(c.player_id,THREE,c.source_id),)),
            ChoiceOption('fault','Fail',(InvokeBehavior(FAULT,c.source_id,c.player_id),))),c.source_id),)
    bodies = {ZERO:lambda c:(GainArmor(c.player_id,1),),ONE:lambda c:(GainArmor(c.player_id,2),),
        OTHER:lambda c:(GainArmor(c.player_id,3),),TWO:lambda c:(GainArmor(c.player_id,5),),
        THREE:lambda c:(GainArmor(c.player_id,7),),HIGH:lambda c:(GainArmor(c.player_id,11),),
        HIT:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),),
        FRIENDLY:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        AUTO:lambda c:(CastSpell(c.player_id,CARD,c.source_id),),AUTO_ONE:lambda c:(CastSpell(c.player_id,ONE,c.source_id),),
        FAULT:failed,FAIL:faulty,PRICE:price}
    prices = {ZERO:0,ONE:1,OTHER:1,TWO:2,THREE:3,HIGH:12,HIT:2,FRIENDLY:3,AUTO:0,AUTO_ONE:0,FAULT:0,FAIL:1,PRICE:0}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        fields = {'targeting':TargetSpec(relation='friendly'if cid == FRIENDLY else'any')}if cid in (HIT,FRIENDLY)else{}
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=prices[cid],on_play=cid,**fields))
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WAIT,WAIT,CardType.MINION,health=20,triggers=(TriggerSpec('armor_gained',P+'watch'),)))
    r.validate();return r


def spec(player,source):
    return RecastFromHistory(player,native.QUERY,distinct='cost',selection='cost_ascending',source_id=source,
        target_preference=AutomaticTargetPreference.ENEMY_IF_AVAILABLE)


class PastArcaneCostHistoryTests(CardBatchTestMixin,unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(registry)

    def game(self,hand=(),*,player=1,board=()):
        players = tuple(PlayerSetup('HERO_08',hand=hand if p == player else (),deck=(ZERO,)*6,
            board=board if p == player else (),mana=20,max_mana=20,mana_cap=20)for p in (1,2))
        return Game.from_scenario(Scenario(players,active_player=player,seed=600),registry())

    def children(self,g,source):return tuple(c for c in g.state.cast_history if c.origin == 'history'and c.caster_id == source)

    def pending(self,g):
        values=tuple(w for w in (*g._frame.prefix,*g._frame.continuation)if type(w)is ContinueHistoryCasts)
        self.assertEqual(len(values),1);return values[0]

    def test_complete_original_row_two_primary_faces_and_no_new_standard_root(self):
        data = native.load_batch();self.assertEqual((len(data['dependencies']),len(data['official_observations'])),(1,2))
        for obs in data['official_observations']:batch.check_face(data['dependencies'][0]['record'],obs['face'],obs['locale'])
        self.assertEqual((registry().card(CARD).cost,native.COLLECTIBLE_ROOTS),(10,()))

    def test_actual_ten_cost_orb_both_actors_recasts_in_printed_cost_order(self):
        for player in (1,2):
            g = self.game((TWO,ZERO,ONE,CARD),player=player)
            for cid in (TWO,ZERO,ONE):self.play(g,cid,player=player)
            mana = g.state.players[player].mana;source = self.play(g,CARD,player=player)
            self.assertEqual(g.state.players[player].mana,mana-10)
            self.assertEqual([c.card_id for c in self.children(g,source)],[ZERO,ONE,TWO])
            self.assertEqual(len(g.state.play_history),4);self.assertTrue(all(c.completed for c in self.children(g,source)));self.portable(g)

    def test_group_uses_printed_cost_after_zero_price_and_includes_cost_above_ten(self):
        g = self.game((PRICE,HIGH,ZERO,AUTO));self.play(g,PRICE);self.play(g,HIGH);self.play(g,ZERO)
        original = next(c for c in g.state.cast_history if c.card_id == HIGH)
        self.assertEqual(next(p.cost for p in g.state.play_history if p.card_id == HIGH),0)
        self.play(g,AUTO);orb = next(c for c in reversed(g.state.cast_history)if c.card_id == CARD)
        children = self.children(g,orb.source_id);self.assertEqual([g.registry.card(c.card_id).cost for c in children],[0,12])
        self.assertEqual(children[-1].recast_id,original.id);self.portable(g)

    def test_duplicate_casts_keep_one_physical_weight_each_inside_same_cost(self):
        g = self.game((ONE,ONE,ONE,OTHER,CARD))
        for cid in (ONE,ONE,ONE,OTHER):self.play(g,cid)
        rows = tuple(g.state.cast_history);probe = Random();probe.setstate(g._rng.getstate());selected = probe.choice(rows)
        source = self.play(g,CARD);child, = self.children(g,source)
        self.assertEqual(child.recast_id,selected.id);self.assertEqual(g._rng.getstate(),probe.getstate());self.portable(g)

    def test_recasts_choose_current_enemy_target_instead_of_original_friendly_target(self):
        for player in (1,2):
            g = self.game((HIT,CARD),player=player);own = g.state.players[player].hero_id;enemy = g.state.players[3-player].hero_id
            self.play(g,HIT,target=own,player=player);source = self.play(g,CARD,player=player)
            child, = self.children(g,source);self.assertEqual(child.target_id,enemy)
            self.assertEqual((g.state.entities[own].health,g.state.entities[enemy].health),(28,28));self.portable(g)

    def test_enemy_preference_falls_back_to_current_legal_friendly_targets(self):
        g = self.game((FRIENDLY,CARD));own = g.state.players[1].hero_id
        self.play(g,FRIENDLY,target=own);source = self.play(g,CARD);child, = self.children(g,source)
        self.assertEqual(child.target_id,own);self.assertEqual(g.state.entities[own].health,28);self.portable(g)

    def test_empty_history_has_no_recast_or_rng_draw(self):
        g = self.game((CARD,));rng = g._rng.getstate();source = self.play(g,CARD)
        self.assertFalse(self.children(g,source));self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_prior_orb_and_pending_original_orb_are_excluded_without_recursion(self):
        g = self.game((ONE,CARD,AUTO));self.play(g,ONE);first = self.play(g,CARD);self.play(g,AUTO)
        self.assertEqual(len(self.children(g,first)),1)
        self.assertFalse(any(c.card_id == CARD and c.origin == 'history'for c in g.state.cast_history));self.portable(g)

    def test_opponent_history_does_not_join_own_groups(self):
        g = self.game((ONE,CARD));self.play(g,ONE);g.apply(EndTurn(1));self.play(g,ZERO,player=2);g.apply(EndTurn(2))
        source = self.play(g,CARD);self.assertEqual([c.card_id for c in self.children(g,source)],[ONE]);self.portable(g)

    def test_automatic_cast_origins_and_earlier_recasts_join_original_frozen_history(self):
        g = self.game((AUTO_ONE,CARD));self.play(g,AUTO_ONE)
        source = self.play(g,CARD);children = self.children(g,source)
        self.assertEqual([g.registry.card(c.card_id).cost for c in children],[0,1])
        self.assertEqual(children[-1].card_id,ONE);self.portable(g)

    def test_wait_preserves_original_groups_child_root_and_bad_resume_rollback(self):
        g = self.game((ONE,TWO,CARD),board=(WAIT,));self.play(g,ONE);self.play(g,TWO);source = self.play(g,CARD)
        for remaining in (1,0):
            pending = self.pending(g);self.assertEqual(pending.remaining,remaining)
            validate_progress(g.state,g.registry,pending,allow_pending=True)
            other = self.portable(g);before = other.snapshot()
            with self.assertRaises(ResolutionError):self.choose(other,'fault')
            self.assertEqual(other.snapshot(),before);self.choose(other);g = other
        self.assertIsNone(g.state.pending_choice);self.assertEqual([c.card_id for c in self.children(g,source)],[ONE,TWO]);self.portable(g)

    def test_new_nested_spell_during_recast_cannot_enter_later_cost_groups(self):
        g = self.game((ONE,TWO,CARD),board=(WAIT,));self.play(g,ONE);self.play(g,TWO);source = self.play(g,CARD)
        original = self.pending(g).initial_cast_ids;self.choose(g,'add')
        self.assertEqual(self.pending(g).initial_cast_ids,original);self.assertTrue(any(c.card_id == THREE for c in g.state.cast_history))
        self.choose(g);self.assertEqual([c.card_id for c in self.children(g,source)],[ONE,TWO]);self.portable(g)

    def test_original_group_progress_cannot_clip_candidates_skip_cost_or_borrow_root(self):
        g = self.game((ONE,OTHER,TWO,CARD),board=(WAIT,))
        for cid in (ONE,OTHER,TWO):self.play(g,cid)
        self.play(g,CARD);pending = self.pending(g)
        for changes in ({'initial_cast_ids':pending.initial_cast_ids[1:]},{'cast_ids':()},
                {'remaining':0},{'remaining':2},{'before_id':pending.before_id+100}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                changed = replace(pending,**changes);validate_progress(g.state,g.registry,changed,allow_pending=True)
        self.portable(g)

    def test_actual_history_failure_rolls_back_payment_new_entities_and_rng(self):
        g = self.game((FAIL,CARD));self.play(g,FAIL);before = g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CARD)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_finite_cost_mode_rejects_unrelated_selection_count_and_target_policies(self):
        request = spec(1,3)
        for changes in ({'selection':'random'},{'count':1},{'replacement':True},{'targeting':'original'},
                {'choices':'player'},{'branch_policy':'inherit'},{'target_preference':None},
                {'query':replace(native.QUERY,side='enemy')},{'query':SpellHistoryQuery()},
                {'source_id':None},{'distinct':'identity'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(request,**changes)
        with self.assertRaises(ValueError):DiscoverSpellHistory(1,distinct='cost')
        with self.assertRaises(ValueError):ContinueHistoryCasts(request,(1,),1,2)

    def test_private_candidates_groups_rng_and_previous_schema_are_not_player_contracts(self):
        g = self.game((ONE,TWO,CARD),board=(WAIT,));self.play(g,ONE);self.play(g,TWO);self.play(g,CARD);self.portable(g)
        for player in (1,2):
            view = json.dumps(g.for_player(player).observe())
            for key in ('cast_ids','initial_cast_ids','before_id','resolution_frame','rng_state','target_selection'):
                self.assertNotIn('"'+key+'"',view)
        old = g.snapshot();old['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(ValueError):Game.from_snapshot(old,registry())

    def test_bad_original_metadata_rejects_before_partial_registration(self):
        r = build_registry();data = deepcopy(native.load_batch());data['dependencies'][0]['record']['cost'] = 9
        before = (dict(r.cards),dict(r.pool_cards),dict(r._behaviors))
        with patch.object(native,'load_batch',return_value=data),self.assertRaises(TargetValidationError):native.register_past_arcane_cost_history(r)
        self.assertEqual((r.cards,r.pool_cards,r._behaviors),before)
