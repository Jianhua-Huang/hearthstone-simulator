"""Actual next-use costs, scoped numeric bonuses and full CAST-school prices."""
from dataclasses import replace
from copy import deepcopy
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry, past_arcane_next_values as native
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, CastSpell,
    EndTurn, Game, IllegalAction, Keyword, PlayerSetup, ResolutionError, Ruleset, Scenario, SpellSchool,
    TriggerSpec, Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import ChoiceOption, Destroy, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionLimitExceeded
from hs_sim.engine.model import PlayerSpellCountCostSpec
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P='k592.'
UNIT,TANK,SMALL,SHIELD,NAGA,POWER,NATURE_POWER,HUGE_POWER,WATCH,DORMANT,LOCATION=(
    P+x for x in('unit','tank','small','shield','naga','power','nature_power','huge_power','watch','dormant','location'))
FIRE,FROST,HOLY,AUTO,AUTO_BAD,AUTO_ENEMY,NOOP,OLD_PRICE,FAULT=(
    P+x for x in('fire','frost','holy','auto','auto_bad','auto_enemy','noop','old_price','fault'))
DRAW='CS2_023';WISDOM='TTN_085';GIFTS='TSC_948';PORTAL='RLK_819';CRAM='SCH_353'


@lru_cache(None)
def host(mode='normal',role='writer'):
    f=build_cn37_local_pool_format();r=f.registry
    def fail(c):raise ResolutionError('K592 deliberate continuation failure')
    def options(c):
        result=(ChoiceOption('continue','Continue'),
            ChoiceOption('fault','Fail',(InvokeBehavior(FAULT,c.source_id,c.player_id),)),
            ChoiceOption('new_school','Accept a later Holy cast',(CastSpell(c.player_id,HOLY,c.source_id),)))
        power=next((i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==POWER),None)
        return result+((ChoiceOption('remove_power','Remove original provider',(Destroy(power,c.source_id),)),)if power else ())
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id)
        if e.kind=='damage_dealt' and mode=='damage-wait' and source is not None and source.card_id in('AV_212','TOY_800'):
            return(RequestChoice(c.player_id,options(c),c.source_id),)
        if e.player_id!=c.player_id:return ()
        if e.kind=='card_drawn' and mode=='draw-wait' and source is not None and source.card_id in(CRAM,WISDOM):
            if len(c.state.draw_history)==1:return(RequestChoice(c.player_id,options(c),c.source_id),)
        if e.kind=='minion_summoned' and mode=='portal-wait' and c.state.entities[e.target_id].card_id==native.LYNX:
            bodies=[v.id for v in c.state.entities.values()if v.card_id==native.LYNX and v.controller==c.player_id]
            if e.target_id==min(bodies):return(RequestChoice(c.player_id,options(c),c.source_id),)
        if e.kind=='card_committed' and mode=='naga-wait' and source is not None and source.card_id==NAGA:
            return(RequestChoice(c.player_id,options(c),c.source_id),)
        return ()
    r.register_behavior(FAULT,fail);r.register_behavior(WATCH,watch)
    for cid,cost,attack,health in((UNIT,5,2,6),(TANK,8,2,40),(SMALL,1,1,2)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health))
    r.register_card(CardDefinition(SHIELD,SHIELD,CardType.MINION,attack=1,health=2,keywords=(Keyword.DIVINE_SHIELD,)))
    r.register_card(CardDefinition(NAGA,NAGA,CardType.MINION,cost=3,attack=2,health=4,
        metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('naga',))))
    for cid,amount,schools in((POWER,1,()),(NATURE_POWER,2,(SpellSchool.NATURE,)),(HUGE_POWER,100,())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=5,spell_damage=amount,spell_damage_schools=schools))
    r.register_card(CardDefinition(DORMANT,DORMANT,CardType.MINION,health=5,dormant_turns=2))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,durability=3,on_use=FAULT))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,triggers=tuple(
        TriggerSpec(k,WATCH)for k in('card_drawn','minion_summoned','damage_dealt','card_committed'))))
    scripts={FIRE:lambda c:(),FROST:lambda c:(),HOLY:lambda c:(),NOOP:lambda c:(),OLD_PRICE:lambda c:(),
        AUTO:lambda c:(CastSpell(c.player_id,FIRE,c.source_id),),
        AUTO_BAD:lambda c:(CastSpell(c.player_id,'AT_004',c.source_id),),
        AUTO_ENEMY:lambda c:(CastSpell(3-c.player_id,HOLY,c.source_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=5 if cid==OLD_PRICE else 0,
            on_play=cid,spell_school={FIRE:SpellSchool.FIRE,FROST:SpellSchool.FROST,HOLY:SpellSchool.HOLY}.get(cid),
            player_spell_count_cost=PlayerSpellCountCostSpec('cost.player-distinct-spell-school-count-v1')if cid==OLD_PRICE else None))
    r.validate();return f


class PastArcaneNextValueTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:host(mode,role).registry)

    def game(self,hand=(),*,own=(),enemy=(),other_hand=(),deck=None,mode='normal',player=1,active=None,seed=19,
             mana=60,max_mana=60,rules=None):
        self.mode=mode;f=host(mode)
        if mode in('draw-wait','portal-wait','damage-wait','naga-wait'):own=(WATCH,*own)
        players=tuple(PlayerSetup('HERO_08',hand=hand if p==player else other_hand,board=own if p==player else enemy,
            deck=((UNIT,)*12 if deck is None else deck)if p==player else(UNIT,)*12,
            mana=mana,max_mana=max_mana,mana_cap=60)for p in(1,2))
        return Game.from_scenario(Scenario(players,active_player=player if active is None else active,seed=seed,generation_context=f.context),f.registry,rules)

    def price(self,g,cid,player=1):return quote_unselected_cost(g.state,g.registry,self.entity(g,cid,player)).amount
    def paid(self,g,cid,target=None,player=1):
        expected=self.price(g,cid,player);index=len(g.state.play_history);eid=self.play(g,cid,target,player)
        self.assertEqual((g.state.play_history[index].card_id,g.state.play_history[index].cost),(cid,expected));return eid
    def results(self,g,cid):return[v.health_result for v in g.state.damage_history if v.health_result.source_card_id==cid]

    def test_complete_ten_roots_real_lynx_and_twenty_two_primary_faces(self):
        d=native.load_batch();self.assertEqual((len(d['collectible_leaf_ids']),len(d['dependencies']),len(d['official_observations'])),(10,11,22))
        rows={v['record']['id']:v['record']for v in d['dependencies']}
        for face in d['official_observations']:batch.check_face(rows[face['card_id']],face['face'],face['locale'])
        parents=[v for v in d['official_observations']if v['card_id']==PORTAL]
        self.assertTrue(all(rows[native.LYNX]['dbf_id']in v['face']['childIds']for v in parents))
        self.assertEqual(native.COLLECTIBLE_ROOTS,());self.assertFalse(d['source_scope_bound'])

    def test_arcane_blast_doubles_only_actual_arcane_spell_bonus_and_requires_minion_in_both_seats(self):
        for p in(1,2):
            g=self.game(('AT_004',),own=(POWER,NATURE_POWER),enemy=(TANK,),player=p);saved=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,'AT_004',g.state.players[3-p].hero_id,p)
            self.assertEqual(g.snapshot(),saved);self.paid(g,'AT_004',g.state.players[3-p].board[0],p)
            row=self.results(g,'AT_004')[0];self.assertEqual((row.base_amount,row.modified_amount),(2,4))
        self.portable(g)

    def test_siphon_exact_enemy_lethal_reduces_only_current_original_hand_spells(self):
        g=self.game(('AV_212',DRAW,UNIT),enemy=(SMALL,));self.paid(g,'AV_212',g.state.players[2].board[0])
        self.assertEqual(self.price(g,DRAW),2);self.assertEqual(self.price(g,UNIT),5)
        self.paid(g,DRAW);self.assertEqual(g.state.play_history[-1].cost,2);self.portable(g)

    def test_siphon_overkill_prevention_nonlethal_and_friendly_lethal_have_no_honorable_reward(self):
        for target,power,friend in((SMALL,(POWER,),False),(SHIELD,(),False),(TANK,(),False),(SMALL,(),True)):
            g=self.game(('AV_212',DRAW),own=power+((target,)if friend else()),enemy=()if friend else(target,))
            self.paid(g,'AV_212',g.state.players[1 if friend else 2].board[-1]);self.assertEqual(self.price(g,DRAW),3)

    def test_siphon_health_wait_restores_original_honorable_result_and_failed_choice(self):
        g=self.game(('AV_212',DRAW),enemy=(SMALL,),mode='damage-wait');self.paid(g,'AV_212',g.state.players[2].board[0])
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);self.choose(other);self.assertEqual(self.price(other,DRAW),2);self.portable(other)

    def test_lunar_eclipse_preserves_next_spell_discount_through_minion_play_then_consumes_once(self):
        for p in(1,2):
            g=self.game(('DMF_057',UNIT,DRAW,DRAW),enemy=(TANK,),player=p);self.paid(g,'DMF_057',g.state.players[3-p].board[0],p)
            self.assertEqual(self.price(g,DRAW,p),1);self.paid(g,UNIT,player=p);self.assertEqual(self.price(g,DRAW,p),1)
            self.paid(g,DRAW,player=p);self.assertEqual(g.state.play_history[-1].cost,1);self.assertEqual(self.price(g,DRAW,p),3)
        self.portable(g)

    def test_lunar_eclipse_discount_expires_at_original_turn_end(self):
        g=self.game(('DMF_057',DRAW),enemy=(TANK,));self.paid(g,'DMF_057',g.state.players[2].board[0])
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(self.price(g,DRAW),3)

    def test_phial_uses_captured_damage_for_next_any_card_and_consumes_once(self):
        g=self.game(('TOY_800',UNIT,DRAW),own=(POWER,));self.paid(g,'TOY_800',g.state.players[2].hero_id)
        self.assertEqual(self.results(g,'TOY_800')[0].damage_dealt,3);self.assertEqual(self.price(g,UNIT),2)
        self.paid(g,UNIT);self.assertEqual(self.price(g,DRAW),3);self.portable(g)

    def test_phial_prevention_grants_no_discount_and_unspent_discount_expires(self):
        g=self.game(('TOY_800',UNIT),enemy=(SHIELD,));self.paid(g,'TOY_800',g.state.players[2].board[0]);self.assertEqual(self.price(g,UNIT),5)
        g=self.game(('TOY_800',UNIT));self.paid(g,'TOY_800',g.state.players[2].hero_id);self.assertEqual(self.price(g,UNIT),3)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(self.price(g,UNIT),5)

    def test_phial_health_wait_keeps_original_damage_quote_and_real_discount_after_restore(self):
        g=self.game(('TOY_800',UNIT),mode='damage-wait');self.paid(g,'TOY_800',g.state.players[2].hero_id)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);self.choose(other)
        self.assertEqual(self.price(other,UNIT),3);self.paid(other,UNIT);self.portable(other)

    def test_celestial_shot_applies_bonus_to_next_cast_across_turns_without_boosting_itself(self):
        g=self.game(('YOG_082','AT_004'),enemy=(TANK,));self.paid(g,'YOG_082',g.state.players[2].hero_id)
        self.assertEqual(self.results(g,'YOG_082')[0].modified_amount,3)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.paid(g,'AT_004',g.state.players[2].board[0])
        self.assertEqual(self.results(g,'AT_004')[0].modified_amount,6)
        self.assertFalse(any(e.spec_id==native.NEXT_DAMAGE for e in g.state.players[1].player_effects));self.portable(g)

    def test_celestial_scoped_bonus_scales_cram_draw_and_is_consumed_by_nondamage_spell(self):
        g=self.game(('YOG_082',CRAM));self.paid(g,'YOG_082',g.state.players[2].hero_id);self.paid(g,CRAM)
        self.assertEqual(len(g.state.draw_history),3)
        g=self.game(('YOG_082',DRAW,'AT_004'),enemy=(TANK,));self.paid(g,'YOG_082',g.state.players[2].hero_id);self.paid(g,DRAW)
        self.paid(g,'AT_004',g.state.players[2].board[0]);self.assertEqual(self.results(g,'AT_004')[0].modified_amount,2)

    def test_cram_draw_count_is_frozen_before_first_draw_reaction_removes_provider(self):
        g=self.game((CRAM,),own=(POWER,),mode='draw-wait');self.paid(g,CRAM)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);self.choose(other,'remove_power')
        self.assertEqual(len(other.state.draw_history),2);self.assertFalse(any(other.state.entities[i].card_id==POWER for i in other.state.players[1].board));self.portable(other)

    def test_cram_uses_ordinary_burn_and_fatigue_for_its_original_draw_count(self):
        g=self.game((CRAM,)+(UNIT,)*9,own=(POWER,));self.paid(g,CRAM)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(g.state.draw_history),2)
        self.assertEqual([row.outcome for row in g.state.draw_history],['hand','burned'])
        g=self.game((CRAM,),own=(POWER,),deck=());self.paid(g,CRAM);self.assertEqual(g.state.players[1].fatigue,2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27)

    def test_portal_creates_real_four_four_rush_lynxes_and_actual_minion_attack(self):
        g=self.game((PORTAL,),own=(POWER,),enemy=(TANK,));self.paid(g,PORTAL)
        bodies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==native.LYNX]
        self.assertEqual(len(bodies),2);self.assertTrue(all((e.attack,e.health)==(4,4)and Keyword.RUSH in e.keywords for e in bodies))
        saved=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,bodies[0].id,g.state.players[2].hero_id))
        self.assertEqual(g.snapshot(),saved);g.apply(Attack(1,bodies[0].id,g.state.players[2].board[0]))
        self.assertEqual(self.entity(g,TANK,2,'board').health,36);self.portable(g)

    def test_portal_wait_keeps_original_count_after_provider_removal_and_bad_choice_rolls_back(self):
        g=self.game((PORTAL,),own=(POWER,),mode='portal-wait');self.paid(g,PORTAL)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);self.choose(other,'remove_power')
        self.assertEqual(sum(other.state.entities[i].card_id==native.LYNX for i in other.state.players[1].board),2);self.portable(other)

    def test_portal_lazy_expansion_uses_actual_resolution_budget_and_rolls_back(self):
        g=self.game((PORTAL,),own=(HUGE_POWER,),rules=Ruleset(max_resolution_steps=80));saved=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g,PORTAL)
        self.assertEqual(g.snapshot(),saved)

    def test_ricochet_selects_three_distinct_enemies_then_one_simultaneous_spell_damage_batch(self):
        g=self.game(('RLK_818',),own=(POWER,),enemy=(UNIT,UNIT,UNIT,UNIT));probe=Random();probe.setstate(g._rng.getstate())
        candidates=tuple(sorted((g.state.players[2].hero_id,*g.state.players[2].board)));expected=probe.sample(candidates,3)
        self.paid(g,'RLK_818');rows=self.results(g,'RLK_818')
        self.assertEqual([v.target_id for v in rows],expected);self.assertEqual(len({v.batch_id for v in rows}),1)
        self.assertEqual([v.modified_amount for v in rows],[2]*3);self.assertEqual(g._rng.getstate(),probe.getstate());self.portable(g)

    def test_ricochet_small_pool_does_not_repeat_same_target_or_target_inactive_slots(self):
        g=self.game(('RLK_818',),enemy=(DORMANT,LOCATION));self.paid(g,'RLK_818')
        rows=self.results(g,'RLK_818');self.assertEqual([v.target_id for v in rows],[g.state.players[2].hero_id])

    def test_gifts_requires_actual_naga_play_while_original_card_is_held_in_both_seats(self):
        for p in(1,2):
            g=self.game((GIFTS,NAGA),player=p);self.paid(g,NAGA,player=p);self.paid(g,GIFTS,player=p)
            self.assertEqual(len(g.state.draw_history),2)
        self.portable(g)

    def test_gifts_naga_play_before_acquisition_does_not_qualify_later_drawn_card(self):
        g=self.game((NAGA,DRAW),deck=(GIFTS,UNIT,UNIT,UNIT));self.paid(g,NAGA);self.paid(g,DRAW)
        before=len(g.state.draw_history);self.paid(g,GIFTS);self.assertEqual(len(g.state.draw_history)-before,1)

    def test_held_naga_wait_restores_original_witness_and_failed_choice_before_gifts_cast(self):
        g=self.game((GIFTS,NAGA),mode='naga-wait');self.paid(g,NAGA)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);self.choose(other);self.paid(other,GIFTS)
        self.assertEqual(len(other.state.draw_history),2);self.portable(other)

    def test_wisdom_counts_all_cast_schools_without_changing_old_hand_root_profile(self):
        for p in(1,2):
            g=self.game((WISDOM,OLD_PRICE,AUTO,FROST,FIRE,NOOP,AUTO_ENEMY),player=p)
            self.paid(g,AUTO,player=p);self.assertEqual((self.price(g,WISDOM,p),self.price(g,OLD_PRICE,p)),(4,5))
            self.paid(g,FROST,player=p);self.assertEqual((self.price(g,WISDOM,p),self.price(g,OLD_PRICE,p)),(3,4))
            self.paid(g,FIRE,player=p);self.paid(g,NOOP,player=p);self.paid(g,AUTO_ENEMY,player=p)
            self.assertEqual((self.price(g,WISDOM,p),self.price(g,OLD_PRICE,p)),(3,3))
        self.portable(g)

    def test_wisdom_excludes_countered_hand_spells_and_failed_automatic_target_attempts(self):
        g=self.game((WISDOM,FIRE),other_hand=('EX1_287',),active=2);self.paid(g,'EX1_287',player=2);g.apply(EndTurn(2))
        self.paid(g,FIRE);self.assertEqual(self.price(g,WISDOM),5)
        g=self.game((WISDOM,AUTO_BAD));self.paid(g,AUTO_BAD)
        self.assertEqual(g.state.cast_history[-1].failure,'no_target');self.assertEqual(self.price(g,WISDOM),5)

    def test_wisdom_wait_restores_original_paid_prefix_while_later_cast_adds_another_school(self):
        g=self.game((WISDOM,WISDOM,FROST),mode='draw-wait');self.paid(g,FROST);self.assertEqual(self.price(g,WISDOM),4)
        self.paid(g,WISDOM);self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);self.choose(other,'new_school')
        row=next(v for v in other.state.play_history if v.card_id==WISDOM)
        self.assertEqual(row.cost,4);self.assertTrue(row.completed);self.assertEqual(self.price(other,WISDOM),2);self.portable(other)

    def test_source_cost_validation_and_direct_prefix_still_reject_missing_real_cast_receipt(self):
        from hs_sim.engine.player_spell_count_costs import validate_prefix
        from hs_sim.engine.spell_casts import validate_history
        g=self.game((WISDOM,FIRE));self.paid(g,FIRE);self.paid(g,WISDOM)
        original=next(v for v in g.state.cast_history if v.card_id==WISDOM)
        self.assertIsNotNone(original.source_cost);fact=original.source_cost.intrinsic.player_spells
        bad=deepcopy(g.state);bad.cast_history[original.id-1]=replace(original,source_cost=None)
        with self.assertRaisesRegex(ValueError,'source-cost'):validate_history(bad,g.registry)
        with self.assertRaisesRegex(ValueError,'source-cost'):validate_prefix(fact,bad,g.registry)

    def test_complete84_source_stays_closed_and_keeps_every_current_batch_identity(self):
        data=native.load_batch();ref=batch.read(data['reference_document']);r=host().registry
        self.assertEqual(len(ref['candidate_ids']),84);self.assertTrue(set(native.LEAVES)<=set(ref['candidate_ids'])&set(r.cards))
        g=self.game(('TIME_857',));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'TIME_857')
        self.assertEqual(g.snapshot(),saved)

    def test_last_bad_lynx_metadata_rejects_before_partial_cards_conditions_or_player_programs(self):
        r=batch.registration_prefix(build_registry,'hs_sim.cards.past_arcane_next_values.register_past_arcane_next_values',native.register_past_arcane_next_values)
        r.register_pool_card(replace(host().registry.pool_card(native.LYNX),cost=99))
        before=(dict(r.cards),dict(r._behaviors),dict(r._trigger_conditions),dict(r.player_effects))
        with self.assertRaises(TargetValidationError):native.register_past_arcane_next_values(r)
        self.assertEqual((dict(r.cards),dict(r._behaviors),dict(r._trigger_conditions),dict(r.player_effects)),before)

    def test_private_held_witness_and_personal_cost_prefix_are_not_opponent_information(self):
        g=self.game((GIFTS,NAGA,WISDOM,FIRE));self.paid(g,NAGA);self.paid(g,FIRE)
        public=json.dumps(g.observe(2))+json.dumps(g.player_events(2))
        for key in(GIFTS,WISDOM,'progress_completions','player_spell_count_fact','resolution_frame','source_sha256'):
            self.assertNotIn(key,public)
        self.portable(g)
