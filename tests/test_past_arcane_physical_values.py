"""Real Arcane consumers keep physical costs, original results and use windows."""
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry, past_arcane_physical_values as native
from hs_sim.engine import (CardClass, CardDefinition, CardType, CastSpell, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, ResolutionError, Scenario, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddToHand, ChangeManaCrystals, ChoiceOption, Destroy, GainArmor,
    InvokeBehavior, RequestChoice)
from hs_sim.engine.model import CastWhenDrawnSpec, CostSpec
from hs_sim.engine.pools import PoolCard, PoolQuery, resolve_candidates, sample_candidates
from hs_sim.engine.spell_casts import CastStoredSpell
from hs_sim.engine.zones import CardReference, ModifyStoredCost, MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P='k593.'
UNIT,SMALL,TANK,EXACT,SHIELD,IMMUNE,POWER,DORMANT,LOCATION=(P+x for x in
    ('unit','small','tank','exact','shield','immune','power','dormant','location'))
COPY_WATCH,DAMAGE_WATCH,DRAW_WATCH,HAND_WATCH,MISSILE_WATCH,FAIL_SUMMON,FAIL_COPY=(P+x for x in
    ('copy_watch','damage_watch','draw_watch','hand_watch','missile_watch','fail_summon','fail_copy'))
FAULT,PREP_DECK,PREP_HAND,SPARK,FIRE,DRAWN,AUTO_SPARK,AUTO_BIND,AUTO_STARGAZING=(P+x for x in
    ('fault','prep_deck','prep_hand','spark','fire','drawn','auto_spark','auto_bind','auto_stargazing'))
SPELLS={n:P+'spell'+str(n)for n in(6,7,8,9,10)}
WATCHES=(COPY_WATCH,DAMAGE_WATCH,DRAW_WATCH,HAND_WATCH,MISSILE_WATCH,FAIL_SUMMON,FAIL_COPY)


@lru_cache(None)
def host(role='writer'):
    f=build_cn37_local_pool_format();r=f.registry
    def fail(c):raise ResolutionError('K593 deliberate continuation failure')
    def options(c):
        result=(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',
            (InvokeBehavior(FAULT,c.source_id,c.player_id),)),
            ChoiceOption('shrink_mana','Remove one crystal',(ChangeManaCrystals(c.player_id,-1),)))
        powers=[i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==POWER]
        if powers:result+= (ChoiceOption('remove_power','Remove original provider',(Destroy(powers[0],c.source_id),)),)
        cards=[c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].kind==CardType.MINION]
        if cards:result+=(ChoiceOption('move_last','Move last original hand minion',
            (MoveCard(CardReference.capture(cards[-1]),c.player_id,Zone.DECK,'bottom',source_id=c.source_id),)),)
        if c.event.kind=='transformed':
            result+=(ChoiceOption('remove_target','Remove current enemy',(Destroy(c.event.target_id,c.source_id),)),)
        return result
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id);owner=c.source.card_id
        if owner==DAMAGE_WATCH and e.kind=='damage_dealt' and source is not None and source.card_id in('DED_517','RLK_804','DEEP_003'):
            return(RequestChoice(c.player_id,options(c),c.source_id),)
        if owner==MISSILE_WATCH and e.kind=='transformed':
            target=c.state.entities[e.target_id]
            if target.controller!=c.player_id and r.card(target.card_id).cost==7:
                return(RequestChoice(c.player_id,options(c),c.source_id),)
        if e.player_id!=c.player_id:return ()
        if owner==FAIL_SUMMON and e.kind=='minion_summoned' and c.state.entities[e.target_id].card_id==native.GOO:
            return(InvokeBehavior(FAULT,c.source_id,c.player_id),)
        if e.kind=='card_added_to_hand' and source is not None and source.card_id in('AV_116','UNG_024'):
            copies=[v for v in c.state.entities.values()if v.controller==c.player_id and v.origin_entity_id is not None]
            if owner==FAIL_COPY and len(copies)==2:return(InvokeBehavior(FAULT,c.source_id,c.player_id),)
            if owner==COPY_WATCH and len(copies)==1:return(RequestChoice(c.player_id,options(c),c.source_id),)
        if owner==DRAW_WATCH and e.kind=='card_drawn' and source is not None and source.card_id=='WW_425':
            return(RequestChoice(c.player_id,options(c),c.source_id),)
        if owner==FAIL_COPY and e.kind=='card_drawn' and source is not None and source.card_id=='WW_425':
            return(InvokeBehavior(FAULT,c.source_id,c.player_id),)
        if owner==HAND_WATCH and e.kind=='stored_card_transformed' and source is not None and source.card_id=='TTN_485':
            hands=[i for i in c.state.players[c.player_id].hand if c.state.entities[i].kind==CardType.MINION]
            if hands and e.target_id==min(hands):return(RequestChoice(c.player_id,options(c),c.source_id),)
        return ()
    r.register_behavior(FAULT,fail);r.register_behavior(P+'watch',watch)
    for cid,cost,health,keywords in((UNIT,2,4,()),(SMALL,1,3,()),(TANK,8,40,()),(EXACT,4,8,()),
            (SHIELD,1,3,(Keyword.DIVINE_SHIELD,)),(IMMUNE,1,3,(Keyword.IMMUNE,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=health,keywords=keywords))
    r.register_card(CardDefinition(POWER,POWER,CardType.MINION,health=5,spell_damage=1))
    r.register_card(CardDefinition(DORMANT,DORMANT,CardType.MINION,health=5,dormant_turns=2))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,durability=3,on_use=FAULT))
    for cid in WATCHES:r.register_card(CardDefinition(cid,cid,CardType.MINION,health=30,triggers=tuple(
        TriggerSpec(k,P+'watch')for k in('card_added_to_hand','minion_summoned','damage_dealt','card_drawn',
            'stored_card_transformed','transformed'))))
    def prep_deck(c):
        cards=c.state.players[c.player_id].deck
        return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(set_to=6 if n==0 else 7),c.source_id)
            for n,i in enumerate(cards[:2]))
    def prep_hand(c):
        return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(delta=-1),c.source_id)
            for i in c.state.players[c.player_id].hand if c.state.entities[i].kind==CardType.MINION)
    def auto_spark(c):
        card=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==SPARK)
        return(CastStoredSpell(CardReference.capture(card),c.player_id,c.source_id,choices='player'),)
    scripts={PREP_DECK:prep_deck,PREP_HAND:prep_hand,SPARK:lambda c:(GainArmor(c.player_id,1),),
        FIRE:lambda c:(GainArmor(c.player_id,1),),DRAWN:lambda c:(GainArmor(c.player_id,1),),
        AUTO_SPARK:auto_spark,AUTO_BIND:lambda c:(CastSpell(c.player_id,SPARK,c.source_id),),
        AUTO_STARGAZING:lambda c:(AddToHand(c.player_id,UNIT,c.source_id),CastSpell(c.player_id,'WW_425',c.source_id))}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.MINION if cid==AUTO_BIND else CardType.SPELL,
            on_play=cid,**({'health':1}if cid==AUTO_BIND else{}),
            spell_school=SpellSchool.ARCANE if cid in(SPARK,DRAWN)else SpellSchool.FIRE if cid==FIRE else None,
            keywords=(Keyword.CASTS_WHEN_DRAWN,)if cid==DRAWN else(),
            cast_when_drawn=CastWhenDrawnSpec(replacement=False,choices='player')if cid==DRAWN else None))
    for cost,cid in SPELLS.items():
        r.register_behavior(cid,lambda c:(GainArmor(c.player_id,1),))
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid))
    r.validate();return f


class PastArcanePhysicalValueTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:host(role).registry)

    def game(self,hand=(),*,own=(),enemy=(),deck=None,other_hand=(),player=1,active=None,seed=19,mana=60,max_mana=60):
        f=host()
        setups=tuple(PlayerSetup('HERO_08',hand=hand if p==player else other_hand,board=own if p==player else enemy,
            deck=((UNIT,)*12 if deck is None else deck)if p==player else(UNIT,)*12,
            mana=mana,max_mana=max_mana,mana_cap=60)for p in(1,2))
        return Game.from_scenario(Scenario(setups,active_player=player if active is None else active,seed=seed,
            generation_context=f.context),f.registry)

    def paid(self,g,cid,target=None,player=1,branch=None):
        e=self.entity(g,cid,player);cost=quote_unselected_cost(g.state,g.registry,e).amount;n=len(g.state.play_history)
        g.apply(PlayCard(player,e.id,target,branch_id=branch))
        self.assertEqual((g.state.play_history[n].card_id,g.state.play_history[n].cost),(cid,cost));return e.id
    def copies(self,g,player=1):return[e for e in g.state.entities.values()if e.controller==player and e.copy_origin is not None]
    def results(self,g,cid):return[v.health_result for v in g.state.damage_history if v.health_result.source_card_id==cid]

    def test_complete_ten_original_spells_token_four_real_branches_and_explicit_primary_gap(self):
        d=native.load_batch();self.assertEqual((len(d['dependencies']),len(d['choice_only']),len(d['evidence_only']),len(d['official_observations'])),(11,4,3,26))
        rows={v['record']['id']:v['record']for v in d['dependencies']+d['choice_only']}
        for v in d['official_observations']:batch.check_face(rows[v['card_id']],v['face'],v['locale'])
        self.assertEqual(d['raw_only_choice_ids'],['NEW1_007a','NEW1_007b'])
        self.assertEqual((rows[native.GOO]['attack'],rows[native.GOO]['health'],rows[native.GOO]['cost']),(1,1,1))
        self.assertEqual(native.COLLECTIBLE_ROOTS,());self.assertFalse(d['source_scope_bound'])

    def test_arcane_brilliance_copies_each_real_deck_tier_and_keeps_originals_in_both_seats(self):
        for p in(1,2):
            g=self.game(('AV_116',),deck=tuple(SPELLS[n]for n in(7,8,9,10)),player=p)
            original=tuple(g.state.players[p].deck);self.paid(g,'AV_116',player=p)
            self.assertEqual(tuple(g.state.players[p].deck),original)
            self.assertEqual([e.origin_entity_id for e in self.copies(g,p)],list(original))
            self.assertEqual([e.card_id for e in self.copies(g,p)],[SPELLS[n]for n in(7,8,9,10)])
            self.assertEqual(g.state.players[p].mana,56)

    def test_current_cost_filter_keeps_physical_equal_faces_separate_from_printed_tiers(self):
        g=self.game(('AV_116',PREP_DECK),deck=(SPELLS[7],SPELLS[7],SPELLS[8],SPELLS[9],SPELLS[10]))
        original=tuple(g.state.players[1].deck);self.paid(g,PREP_DECK);self.paid(g,'AV_116')
        copies=self.copies(g);self.assertEqual([e.origin_entity_id for e in copies],list(original[1:]))
        self.assertEqual([quote_unselected_cost(g.state,g.registry,e).amount for e in copies],[7,8,9,10])
        self.assertNotIn(original[0],[e.origin_entity_id for e in copies])

    def test_empty_cost_tiers_skip_without_rng_and_one_hand_three_burned_copies_preserve_deck(self):
        g=self.game(('AV_116',),deck=(FIRE,));rng=g._rng.getstate();self.paid(g,'AV_116')
        self.assertEqual(g._rng.getstate(),rng);self.assertFalse(self.copies(g));self.assertEqual(len(g.state.draw_history),0)
        g=self.game(('AV_116',)+(UNIT,)*9,deck=tuple(SPELLS[n]for n in(7,8,9,10)));self.paid(g,'AV_116')
        self.assertEqual(len(self.copies(g)),4);self.assertEqual(sum(e.zone==Zone.HAND for e in self.copies(g)),1)
        self.assertEqual(len(g.state.players[1].deck),4)

    def test_copy_tier_wait_restores_original_copy_and_remaining_queries_after_bad_choice(self):
        g=self.game(('AV_116',),own=(COPY_WATCH,),deck=tuple(SPELLS[n]for n in(7,8,9,10)))
        self.paid(g,'AV_116');self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);self.choose(other);self.assertEqual(len(self.copies(other)),4);self.portable(other)

    def test_late_copy_acquisition_failure_rolls_back_all_copies_payment_and_rng(self):
        g=self.game(('AV_116',),own=(FAIL_COPY,),deck=tuple(SPELLS[n]for n in(7,8,9,10)));saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.paid(g,'AV_116')
        self.assertEqual(g.snapshot(),saved)

    def test_overflow_summons_real_goo_from_original_excess_including_spell_damage(self):
        for p in(1,2):
            g=self.game(('DED_517',),own=(POWER,),enemy=(SMALL,),player=p)
            self.paid(g,'DED_517',self.entity(g,SMALL,3-p,'board').id,p)
            goo=self.entity(g,native.GOO,p,'board');self.assertEqual((goo.attack,goo.health),(6,6))
            result=self.results(g,'DED_517')[0];self.assertEqual((result.damage_dealt,result.health_before),(9,3))
            self.assertEqual(g.state.card_summon_history[-1].request.cause.cast_id,g.state.cast_history[-1].id)

    def test_overflow_exact_nonlethal_shield_and_friendly_targets_do_not_fabricate_excess(self):
        for target in(EXACT,TANK,SHIELD):
            g=self.game(('DED_517',),enemy=(target,));self.paid(g,'DED_517',self.entity(g,target,2,'board').id)
            self.assertFalse([e for e in g.state.entities.values()if e.card_id==native.GOO])
        g=self.game(('DED_517',),own=(SMALL,));saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.paid(g,'DED_517',self.entity(g,SMALL,1,'board').id)
        self.assertEqual(g.snapshot(),saved)

    def test_health_wait_keeps_original_excess_after_provider_removal_and_failed_selection(self):
        g=self.game(('DED_517',),own=(DAMAGE_WATCH,POWER),enemy=(SMALL,))
        self.paid(g,'DED_517',self.entity(g,SMALL,2,'board').id);other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);self.choose(other,'remove_power')
        self.assertEqual(self.entity(other,native.GOO,1,'board').health,6);self.portable(other)

    def test_real_goo_entry_failure_rolls_back_original_damage_death_summon_and_payment(self):
        g=self.game(('DED_517',),own=(FAIL_SUMMON,),enemy=(SMALL,));saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.paid(g,'DED_517',self.entity(g,SMALL,2,'board').id)
        self.assertEqual(g.snapshot(),saved)

    def test_shimmer_shot_uses_full_actual_damage_cost_pool_and_original_cast_attribution(self):
        for p in(1,2):
            g=self.game(('DEEP_003',),own=(POWER,),enemy=(TANK,),player=p)
            q=PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=2,max_cost=2)
            rows=resolve_candidates(g.registry,host().context,native.POOL,q,source_card_id='DEEP_003',player_id=p)
            probe=Random();probe.setstate(g._rng.getstate());expected=sample_candidates(probe,rows,1,replacement=True)[0]
            self.paid(g,'DEEP_003',self.entity(g,TANK,3-p,'board').id,p)
            self.assertIn(expected,[g.state.entities[i].card_id for i in g.state.players[p].board])
            self.assertEqual(self.results(g,'DEEP_003')[0].damage_dealt,2)
            self.assertEqual(g.state.card_summon_history[-1].request.pool_basis.query,q)

    def test_shimmer_prevented_damage_queries_zero_tier_and_full_board_does_not_draw_rng(self):
        g=self.game(('DEEP_003',),enemy=(SHIELD,));self.paid(g,'DEEP_003',self.entity(g,SHIELD,2,'board').id)
        self.assertEqual(self.results(g,'DEEP_003')[0].damage_dealt,0)
        self.assertEqual(g.state.card_summon_history[-1].request.pool_basis.query.min_cost,0)
        g=self.game(('DEEP_003',),own=(UNIT,)*7,enemy=(TANK,));rng=g._rng.getstate()
        self.paid(g,'DEEP_003',self.entity(g,TANK,2,'board').id)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(len(g.state.players[1].board),7)

    def test_conjured_arrow_uses_maximum_mana_and_actual_result_with_spell_damage(self):
        for maximum,power,draws in((5,(),0),(6,(),2),(6,(POWER,),3)):
            g=self.game(('RLK_804',),own=power,enemy=(TANK,),mana=maximum,max_mana=maximum)
            self.paid(g,'RLK_804',self.entity(g,TANK,2,'board').id)
            self.assertEqual(len(g.state.draw_history),draws)
            self.assertEqual(g.state.players[1].mana,maximum-2)

    def test_manathirst_wait_keeps_original_acceptance_after_maximum_mana_changes(self):
        g=self.game(('RLK_804',),own=(DAMAGE_WATCH,),enemy=(TANK,),mana=6,max_mana=6)
        self.paid(g,'RLK_804',self.entity(g,TANK,2,'board').id);other=self.portable(g);self.choose(other,'shrink_mana')
        self.assertEqual(other.state.players[1].max_mana,5);self.assertEqual(len(other.state.draw_history),2);self.portable(other)

    def test_prevented_arrow_at_six_mana_does_not_draw_or_fatigue(self):
        g=self.game(('RLK_804',),enemy=(SHIELD,),deck=(),mana=6,max_mana=6)
        self.paid(g,'RLK_804',self.entity(g,SHIELD,2,'board').id)
        self.assertFalse(g.state.draw_history);self.assertEqual(g.state.players[1].fatigue,0)

    def test_original_starfall_branches_use_real_targeting_and_spell_damage(self):
        g=self.game(('NEW1_007',),own=(POWER,UNIT),enemy=(TANK,TANK));target=self.entity(g,UNIT,1,'board').id
        self.paid(g,'NEW1_007',target,branch='NEW1_007b');self.assertEqual(self.results(g,'NEW1_007')[0].damage_dealt,6)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        g=self.game(('NEW1_007',),own=(POWER,UNIT),enemy=(TANK,TANK))
        self.paid(g,'NEW1_007',branch='NEW1_007a');self.assertEqual([x.damage_dealt for x in self.results(g,'NEW1_007')],[3,3])
        self.assertEqual(self.entity(g,UNIT,1,'board').health,4)

    def test_phase_ray_damages_two_distinct_enemies_and_real_dormancy_counts_owner_turns(self):
        g=self.game(('GDB_851',),own=(POWER,),enemy=(TANK,)*3)
        self.paid(g,'GDB_851',branch='GDB_851a');rows=self.results(g,'GDB_851')
        self.assertEqual((len(rows),len({v.target_id for v in rows})),(2,2));self.assertEqual([v.damage_dealt for v in rows],[3,3])
        g=self.game(('GDB_851',),enemy=(TANK,));target=self.entity(g,TANK,2,'board').id
        self.paid(g,'GDB_851',target,branch='GDB_851b');self.assertFalse(g.state.entities[target].active)
        for p in(1,2):g.apply(EndTurn(p))
        self.assertFalse(g.state.entities[target].active);g.apply(EndTurn(1));self.assertTrue(g.state.entities[target].active)

    def test_bad_branch_targets_and_unprovided_combined_branch_reject_before_payment(self):
        for root,branch in(('GDB_851','GDB_851b'),('NEW1_007','NEW1_007b')):
            g=self.game((root,),own=(UNIT,));saved=g.snapshot()
            with self.assertRaises(IllegalAction):self.paid(g,root,branch=branch)
            self.assertEqual(g.snapshot(),saved)
            with self.assertRaises(IllegalAction):self.paid(g,root,self.entity(g,UNIT,1,'board').id,branch=root+':combined')
            self.assertEqual(g.snapshot(),saved)

    def test_real_fandral_combined_starfall_has_one_payment_and_both_original_payloads(self):
        g=self.game(('NEW1_007',),own=('CORE_OG_044',),enemy=(TANK,));target=self.entity(g,TANK,2,'board').id
        self.paid(g,'NEW1_007',target,branch='NEW1_007:combined')
        self.assertEqual([v.damage_dealt for v in self.results(g,'NEW1_007')],[5,2]);self.assertEqual(g.state.players[1].mana,55)
        self.assertEqual(len(g.state.cast_history),1)

    def test_devolving_missiles_reselect_current_enemy_and_current_lower_cost_each_time(self):
        g=self.game(('SCH_235',),enemy=(TANK,));target=self.entity(g,TANK,2,'board').id
        self.paid(g,'SCH_235');events=[e for e in g.events if e.kind=='transformed']
        self.assertEqual(len(events),3);self.assertTrue(all(e.target_id==target for e in events))
        self.assertEqual([g.registry.card(dict(e.data)['card_id']).cost for e in events],[7,6,5])
        self.assertEqual(g.registry.card(g.state.entities[target].card_id).cost,5);self.assertEqual(len(g.state.cast_history),1)

    def test_empty_random_transform_domain_skips_dormant_and_locations_without_rng(self):
        g=self.game(('SCH_235',),enemy=(DORMANT,LOCATION));rng=g._rng.getstate();self.paid(g,'SCH_235')
        self.assertEqual(g._rng.getstate(),rng);self.assertFalse([e for e in g.events if e.kind=='transformed'])

    def test_missile_wait_restores_first_transform_then_later_missiles_observe_removed_enemy(self):
        g=self.game(('SCH_235',),own=(MISSILE_WATCH,),enemy=(TANK,));self.paid(g,'SCH_235')
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);self.choose(other,'remove_target')
        self.assertEqual(len([e for e in other.events if e.kind=='transformed']),1);self.portable(other)

    def test_hand_alignment_uses_current_local_tier_and_retains_each_original_local_cost(self):
        g=self.game(('TTN_485',PREP_HAND,UNIT,SMALL,SPARK),own=(TANK,));self.paid(g,PREP_HAND)
        original=[self.entity(g,cid).id for cid in(UNIT,SMALL)];self.paid(g,'TTN_485')
        self.assertEqual([g.registry.card(g.state.entities[i].card_id).cost for i in original],[4,3])
        self.assertEqual([quote_unselected_cost(g.state,g.registry,g.state.entities[i]).amount for i in original],[1,0])
        self.assertEqual(self.entity(g,TANK,1,'board').card_id,TANK);self.assertEqual(self.entity(g,SPARK).card_id,SPARK)
        g.apply(next(a for a in g.legal_actions()if isinstance(a,PlayCard)and a.entity_id==original[0]))
        self.assertEqual(g.state.play_history[-1].cost,1)

    def test_hand_transform_wait_keeps_original_group_references_when_last_card_moves_away(self):
        g=self.game(('TTN_485',UNIT,SMALL),own=(HAND_WATCH,));last=self.entity(g,SMALL).id
        self.paid(g,'TTN_485');self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);self.choose(other,'move_last')
        self.assertEqual((other.state.entities[last].zone,other.state.entities[last].card_id),(Zone.DECK,SMALL));self.portable(other)

    def test_mana_bind_copies_original_opponent_face_at_zero_then_uses_real_zero_payment(self):
        for p in(1,2):
            g=self.game(('UNG_024',),other_hand=(SPELLS[7],),player=p);self.paid(g,'UNG_024',player=p)
            g.apply(EndTurn(p));source=self.paid(g,SPELLS[7],player=3-p)
            copied=self.copies(g,p);self.assertEqual((len(copied),copied[0].origin_entity_id,copied[0].card_id),(1,source,SPELLS[7]))
            self.assertEqual(quote_unselected_cost(g.state,g.registry,copied[0]).amount,0)
            g.apply(EndTurn(3-p));self.paid(g,SPELLS[7],player=p);self.assertEqual(g.state.play_history[-1].cost,0)
            self.assertFalse(g.state.players[p].secrets)

    def test_mana_bind_actual_automatic_cast_is_seen_once_and_owner_turn_is_ignored(self):
        g=self.game(('UNG_024',AUTO_BIND),other_hand=(AUTO_BIND,));self.paid(g,'UNG_024');self.paid(g,AUTO_BIND)
        self.assertEqual(len(g.state.players[1].secrets),1);g.apply(EndTurn(1));self.paid(g,AUTO_BIND,player=2)
        self.assertEqual(len(self.copies(g)),1);self.assertEqual(self.copies(g)[0].card_id,SPARK)
        self.assertFalse(g.state.players[1].secrets)

    def test_mana_bind_copy_wait_restores_actual_opponent_cast_before_original_payload(self):
        g=self.game(('UNG_024',),own=(COPY_WATCH,),other_hand=(SPELLS[7],));self.paid(g,'UNG_024');g.apply(EndTurn(1))
        self.paid(g,SPELLS[7],player=2);self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);self.choose(other)
        self.assertEqual(other.state.entities[other.state.players[2].hero_id].armor,1);self.assertEqual(len(self.copies(other)),1);self.portable(other)

    def test_stargazing_draws_only_different_arcane_physical_card_and_grants_original_residence(self):
        g=self.game(('WW_425',SPARK),deck=('WW_425',FIRE,UNIT,SPARK));original=self.entity(g,SPARK).id
        self.paid(g,'WW_425');draw=g.state.draw_history[-1];self.assertEqual(draw.card_id,SPARK)
        self.assertNotEqual(draw.entity_id,original)
        self.assertFalse([a for a in g.state.entities[original].abilities if a.kind=='card_spell_repeat'])
        grant=next(a for a in g.state.entities[draw.entity_id].abilities if a.kind=='card_spell_repeat')
        self.assertEqual((grant.spell_repeat.casts,grant.expires_turn),(2,g.state.turn))
        g.apply(PlayCard(1,original));g.apply(PlayCard(1,draw.entity_id))
        self.assertEqual(sum(v.source_id==original for v in g.state.cast_history),1)
        self.assertEqual(sum(v.source_id==draw.entity_id for v in g.state.cast_history),2)

    def test_stargazing_unspent_grant_expires_at_original_turn_end(self):
        g=self.game(('WW_425',),deck=(SPARK,UNIT));self.paid(g,'WW_425');drawn=g.state.draw_history[-1].entity_id
        g.apply(EndTurn(1));g.apply(EndTurn(2));g.apply(PlayCard(1,drawn))
        self.assertEqual(sum(v.source_id==drawn for v in g.state.cast_history),1)

    def test_stargazing_does_not_repeat_stored_automatic_or_cast_when_drawn_payloads(self):
        g=self.game(('WW_425',AUTO_SPARK),deck=(SPARK,));self.paid(g,'WW_425');source=g.state.draw_history[-1].entity_id
        self.paid(g,AUTO_SPARK);self.assertEqual(sum(v.source_id==source for v in g.state.cast_history),1)
        g=self.game(('WW_425',),deck=(DRAWN,));self.paid(g,'WW_425');draw=g.state.draw_history[-1]
        self.assertEqual(draw.outcome,'cast');self.assertEqual(sum(v.source_id==draw.entity_id for v in g.state.cast_history),1)

    def test_stargazing_full_hand_burn_and_empty_match_do_not_create_an_extra_hand_card(self):
        g=self.game((AUTO_STARGAZING,)+(UNIT,)*9,deck=(SPARK,));self.paid(g,AUTO_STARGAZING)
        self.assertEqual(g.state.draw_history[-1].outcome,'burned');self.assertFalse([e for e in g.state.entities.values()if e.card_id==SPARK and e.zone==Zone.HAND])
        g=self.game(('WW_425',),deck=('WW_425',FIRE,UNIT));rng=g._rng.getstate();self.paid(g,'WW_425')
        self.assertFalse(g.state.draw_history);self.assertEqual(g._rng.getstate(),rng)

    def test_stargazing_draw_wait_restores_original_grant_and_failed_choice_then_two_paid_casts(self):
        g=self.game(('WW_425',),own=(DRAW_WATCH,),deck=(SPARK,));self.paid(g,'WW_425');self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);self.choose(other);source=other.state.draw_history[-1].entity_id
        self.paid(other,SPARK);self.assertEqual(sum(v.source_id==source for v in other.state.cast_history),2);self.portable(other)

    def test_stargazing_late_draw_failure_rolls_back_payment_grant_physical_draw_and_rng(self):
        g=self.game(('WW_425',),own=(FAIL_COPY,),deck=(SPARK,));saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.paid(g,'WW_425')
        self.assertEqual(g.snapshot(),saved)

    def test_last_bad_token_metadata_rejects_before_partial_cards_behaviors_or_conditions(self):
        r=batch.registration_prefix(build_registry,'hs_sim.cards.past_arcane_physical_values.register_past_arcane_physical_values',
            native.register_past_arcane_physical_values)
        r.register_pool_card(replace(host().registry.pool_card(native.GOO),attack=2));before=r.fingerprint()
        with self.assertRaisesRegex(TargetValidationError,native.GOO):native.register_past_arcane_physical_values(r)
        self.assertEqual(r.fingerprint(),before)

    def test_complete_source_is_not_pruned_or_enabled_and_private_original_quotes_stay_hidden(self):
        f=host();ref=batch.read(native.ROOT/'data/cards/past-arcane-local-reference-v1.json')
        self.assertEqual(len(ref['candidate_ids']),84);self.assertTrue(set(native.LEAVES)<=set(ref['candidate_ids'])&set(f.registry.cards))
        self.assertFalse(any(v.source_card_id=='TIME_857'for v in f.registry.generation_scopes.values()))
        g=self.game(('AV_116','WW_425'),own=(COPY_WATCH,),deck=(SPELLS[7],SPARK));self.paid(g,'AV_116')
        text=json.dumps(g.for_player(2).observe())
        for key in('current_deck_copy_costs','card_spell_repeat','original_cost','rng_state','resolution_frame','source_sha256'):
            self.assertNotIn('"'+key+'"',text)
