"""Real past Arcane entry points reuse full pools and physical copy/CAST tails."""
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry, past_arcane_secrets_copy_damage as native
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, CastSpell, EndTurn,
    Game, IllegalAction, Keyword, PlayerSetup, ResolutionError, Scenario, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (Buff, ChoiceOption, Damage, Destroy, InvokeBehavior, RequestChoice)
from hs_sim.engine.model import DamageKind
from hs_sim.engine.pools import resolve_candidates, sample_candidates
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P='k591.'
UNIT,SECOND,TANK,DRAGON,POWER,DORMANT,LOCATION,WATCH,FRAGILE=(
    P+x for x in ('unit','second','tank','dragon','power','dormant','location','watch','fragile'))
BUFF,WOUND,KILL,AUTO,NOOP,FAULT=(P+x for x in ('buff','wound','kill','auto','noop','fault'))
DRAW='CS2_023'


@lru_cache(None)
def host(mode='normal',role='writer'):
    f=build_cn37_local_pool_format();r=f.registry
    def fail(c):raise ResolutionError('K591 deliberate continuation failure')
    def options(c):
        return (ChoiceOption('continue','Continue'),
            ChoiceOption('fault','Fail',(InvokeBehavior(FAULT,c.source_id,c.player_id),)))
    def death(c):
        wait=(RequestChoice(c.player_id,options(c),c.source_id),)if mode=='star-wait'else ()
        return (*wait,SummonByCard(c.player_id,(SummonEntryMaterial(TANK),),SummonCause.capture(c)))
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id)
        if e.kind=='damage_dealt' and source is not None and source.card_id=='MIS_107':
            rows=[v for v in c.state.damage_history if v.health_result.source_card_id=='MIS_107']
            if mode=='split-wait' and len(rows)==1:return(RequestChoice(c.player_id,options(c),c.source_id),)
        if e.player_id!=c.player_id:return ()
        if e.kind=='minion_summoned' and mode=='portal-wait':
            roots=c.state.pool_summon_history
            if roots and roots[-1].spec.basis.source.card_id=='BT_003':
                return(RequestChoice(c.player_id,options(c),c.source_id),)
        if e.kind!='card_added_to_hand' or source is None or source.card_id not in ('GVG_005','SCH_352'):return ()
        copies=[v for v in c.state.entities.values()if v.controller==c.player_id and v.origin_entity_id is not None]
        if mode=='copy-fail' and len(copies)==2:return(InvokeBehavior(FAULT,c.source_id,c.player_id),)
        if mode!='copy-wait' or len(copies)!=1:return ()
        other=next(i for i in reversed(c.state.players[c.player_id].board)if i!=c.source_id)
        return(RequestChoice(c.player_id,options(c)+(ChoiceOption('remove','Remove last original',
            (Destroy(other,c.source_id),)),),c.source_id),)
    r.register_behavior(FAULT,fail);r.register_behavior(WATCH,watch);r.register_behavior(P+'death',death)
    for cid,cost,attack,health in ((UNIT,5,2,8),(SECOND,3,3,6),(TANK,8,2,50)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health))
    r.register_card(CardDefinition(DRAGON,DRAGON,CardType.MINION,cost=3,attack=2,health=5,
        metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('dragon',))))
    r.register_card(CardDefinition(POWER,POWER,CardType.MINION,health=5,spell_damage=1))
    r.register_card(CardDefinition(DORMANT,DORMANT,CardType.MINION,health=5,dormant_turns=2))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,durability=3,on_use=FAULT))
    r.register_card(CardDefinition(FRAGILE,FRAGILE,CardType.MINION,attack=1,health=1,deathrattle=P+'death'))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,triggers=tuple(
        TriggerSpec(k,WATCH)for k in('card_added_to_hand','minion_summoned','damage_dealt'))))
    scripts={BUFF:lambda c:(Buff(c.target_id,2,3,c.source_id),),
        WOUND:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        AUTO:lambda c:(CastSpell(c.player_id,NOOP,c.source_id),),NOOP:lambda c:()}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid in(BUFF,WOUND,KILL)else None))
    r.validate();return f


@lru_cache(None)
def portal_seed():
    f=host();rows=resolve_candidates(f.registry,f.context,native.POOL,native.FOURS,
        source_card_id='BT_003',exclude_source_by_rule=True)
    plain={v.card_id for v in rows if not f.registry.card(v.card_id).triggers and not f.registry.card(v.card_id).auras
        and not f.registry.card(v.card_id).colossal and not f.registry.card(v.card_id).dormant_turns}
    return next(seed for seed in range(10000)if sample_candidates(Random(seed),rows,1,replacement=True)[0]in plain)


class PastArcaneSecretCopyDamageTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:host(mode,role).registry)

    def game(self,hand=(),*,own=(),enemy=(),other_hand=(),deck=None,mode='normal',player=1,seed=17,hero='HERO_08'):
        self.mode=mode;f=host(mode)
        if mode in ('copy-wait','copy-fail','portal-wait','split-wait'):own=(WATCH,*own)
        players=tuple(PlayerSetup(hero if p==player else'HERO_08',hand=hand if p==player else other_hand,
            board=own if p==player else enemy,deck=((UNIT,)*12 if deck is None else deck)if p==player else(UNIT,)*12,
            mana=60,max_mana=60,mana_cap=60)for p in(1,2))
        return Game.from_scenario(Scenario(players,active_player=player,seed=seed,generation_context=f.context),f.registry)

    def paid(self,g,cid,target=None,player=1):
        index=len(g.state.play_history);eid=self.play(g,cid,target,player)
        row=g.state.play_history[index];self.assertEqual((row.card_id,row.cost),(cid,g.registry.card(cid).cost));return eid

    def arm(self,g,cid,player=1):
        eid=self.paid(g,cid,player=player);self.assertEqual(g.state.entities[eid].zone,Zone.SECRET)
        g.apply(EndTurn(player));return eid

    def results(self,g,cid):return[v.health_result for v in g.state.damage_history if v.health_result.source_card_id==cid]

    def test_complete_eleven_original_faces_and_two_full_existing_dependencies(self):
        data=native.load_batch();self.assertEqual((len(data['dependencies']),len(data['existing_dependencies']),len(data['official_observations'])),(11,2,26))
        rows={v['record']['id']:v['record']for v in data['dependencies']+data['existing_dependencies']}
        for face in data['official_observations']:batch.check_face(rows[face['card_id']],face['face'],face['locale'])
        self.assertEqual(native.COLLECTIBLE_ROOTS,());self.assertFalse(data['source_scope_bound'])
        self.assertEqual(host().registry.card('BAR_541').on_play,host().registry.card('CORE_BAR_541').on_play)

    def test_all_four_paid_secrets_keep_duplicate_prevention_and_hidden_identity(self):
        for cid in native.SECRETS:
            g=self.game((cid,cid));eid=self.paid(g,cid);saved=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,cid)
            self.assertEqual(g.snapshot(),saved);self.assertEqual(g.state.entities[eid].zone,Zone.SECRET)
            public=json.dumps(g.observe(2))+json.dumps(g.player_events(2));self.assertNotIn(cid,public)

    def test_portal_after_real_enemy_spell_uses_complete_weighted_four_cost_pool_in_both_seats(self):
        for p in(1,2):
            g=self.game(('BT_003',),other_hand=(DRAW,),seed=portal_seed(),player=p);source=self.arm(g,'BT_003',p)
            rows=resolve_candidates(g.registry,g._generation_context,native.POOL,native.FOURS,source_card_id='BT_003',player_id=p,exclude_source_by_rule=True)
            probe=Random();probe.setstate(g._rng.getstate());expected=sample_candidates(probe,rows,1,replacement=True)
            self.paid(g,DRAW,player=3-p);root=g.state.pool_summon_history[-1]
            self.assertEqual(root.selected,expected);self.assertEqual(g._rng.getstate(),probe.getstate())
            self.assertEqual(root.spec.basis.candidates,rows);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
            self.assertEqual([g.state.entities[i].card_id for i in g.state.players[p].board],list(expected))
        self.portable(g)

    def test_portal_accepts_real_automatic_cast_completion_once(self):
        g=self.game(('BT_003',),other_hand=(AUTO,),seed=portal_seed());source=self.arm(g,'BT_003')
        self.paid(g,AUTO,player=2);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.pool_summon_history),1)
        self.assertTrue(any(v.card_id==NOOP and v.origin!='hand'and v.completed for v in g.state.cast_history));self.portable(g)

    def test_portal_own_turn_countered_cast_and_full_board_do_not_reveal(self):
        g=self.game(('BT_003',DRAW));source=self.paid(g,'BT_003');self.paid(g,DRAW)
        self.assertEqual(g.state.entities[source].zone,Zone.SECRET)
        g=self.game(('EX1_287','BT_003'),other_hand=(DRAW,));self.paid(g,'EX1_287');source=self.arm(g,'BT_003')
        self.paid(g,DRAW,player=2);self.assertEqual(g.state.entities[source].zone,Zone.SECRET)
        g=self.game(('BT_003',),own=(UNIT,)*7,other_hand=(DRAW,));source=self.arm(g,'BT_003');rng=g._rng.getstate()
        self.paid(g,DRAW,player=2);self.assertEqual(g.state.entities[source].zone,Zone.SECRET)
        self.assertEqual(g._rng.getstate(),rng);self.assertFalse(g.state.pool_summon_history)

    def test_portal_summon_wait_restores_selected_batch_and_rolls_back_failed_branch(self):
        g=self.game(('BT_003',),other_hand=(DRAW,),mode='portal-wait',seed=portal_seed());source=self.arm(g,'BT_003')
        self.paid(g,DRAW,player=2);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);selected=other.state.pool_summon_history[-1].selected
        self.choose(other);self.assertEqual(other.state.pool_summon_history[-1].selected,selected);self.portable(other)

    def test_potion_of_polymorph_waits_for_real_enemy_minion_play_and_uses_native_sheep(self):
        g=self.game(('CFM_620',),other_hand=(UNIT,));source=self.arm(g,'CFM_620')
        target=self.paid(g,UNIT,player=2);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        e=g.state.entities[target];self.assertEqual((e.card_id,e.attack,e.health),('CS2_tk1',1,1));self.portable(g)

    def test_polymorph_potion_ignores_friendly_play_and_minion_spells(self):
        g=self.game(('CFM_620',UNIT),other_hand=(DRAW,));source=self.paid(g,'CFM_620');self.paid(g,UNIT)
        g.apply(EndTurn(1));self.paid(g,DRAW,player=2);self.assertEqual(g.state.entities[source].zone,Zone.SECRET)

    def test_duplicate_uses_original_first_friendly_death_and_printed_copies(self):
        for p in(1,2):
            g=self.game(('FP1_018',BUFF),own=(UNIT,),other_hand=(KILL,),player=p)
            target=g.state.players[p].board[0];self.paid(g,BUFF,target,p);source=self.arm(g,'FP1_018',p)
            self.paid(g,KILL,target,3-p);copies=[g.state.entities[i]for i in g.state.players[p].hand]
            self.assertEqual([e.card_id for e in copies],[UNIT,UNIT]);self.assertTrue(all((e.attack,e.max_health)==(2,8)for e in copies))
            self.assertTrue(all(e.origin_entity_id==target for e in copies));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.portable(g)

    def test_duplicate_remains_on_owner_turn_and_burns_both_copies_on_full_hand(self):
        g=self.game(('FP1_018',KILL),own=(UNIT,));source=self.paid(g,'FP1_018');self.paid(g,KILL,g.state.players[1].board[0])
        self.assertEqual(g.state.entities[source].zone,Zone.SECRET)
        g=self.game(('FP1_018',DRAW)+(UNIT,)*8,own=(UNIT,),other_hand=(KILL,));self.paid(g,'FP1_018');self.paid(g,DRAW)
        self.assertEqual(len(g.state.players[1].hand),10);g.apply(EndTurn(1));target=g.state.players[1].board[0]
        self.paid(g,KILL,target,2);copies=[e for e in g.state.entities.values()if e.origin_entity_id==target]
        self.assertEqual(len(copies),2);self.assertTrue(all(e.zone==Zone.GRAVEYARD for e in copies));self.portable(g)

    def test_splitting_image_copies_original_attacked_minion_before_combat_in_both_seats(self):
        for p in(1,2):
            g=self.game(('TRL_400',BUFF),own=(UNIT,),enemy=(SECOND,),player=p)
            target=g.state.players[p].board[0];self.paid(g,BUFF,target,p);source=self.arm(g,'TRL_400',p)
            g.apply(Attack(3-p,g.state.players[3-p].board[0],target))
            bodies=[g.state.entities[i]for i in g.state.players[p].board]
            self.assertEqual(len(bodies),2);self.assertEqual((bodies[0].attack,bodies[0].health),(4,8))
            self.assertEqual((bodies[1].attack,bodies[1].health),(4,11));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.portable(g)

    def test_splitting_image_requires_real_minion_target_and_available_board_slot(self):
        g=self.game(('TRL_400',),enemy=(SECOND,));source=self.arm(g,'TRL_400')
        g.apply(Attack(2,g.state.players[2].board[0],g.state.players[1].hero_id));self.assertEqual(g.state.entities[source].zone,Zone.SECRET)
        g=self.game(('TRL_400',),own=(UNIT,)*7,enemy=(SECOND,));source=self.arm(g,'TRL_400')
        g.apply(Attack(2,g.state.players[2].board[0],g.state.players[1].board[0]));self.assertEqual(g.state.entities[source].zone,Zone.SECRET)

    def test_original_runed_orb_alias_uses_spell_damage_and_actual_current_class_discovery(self):
        g=self.game(('BAR_541',),own=(POWER,),hero='HERO_03');target=g.state.players[2].hero_id;self.paid(g,'BAR_541',target)
        self.assertEqual(self.results(g,'BAR_541')[0].modified_amount,3)
        rows=resolve_candidates(g.registry,g._generation_context,native.POOL,native.SPELLS,current_class=g.state.players[1].hero_class,
            source_card_id='BAR_541',player_id=1,exclude_source_by_rule=True)
        self.assertEqual(len(g.state.pending_choice.options),3)
        self.assertTrue({v.card_id for v in g.state.pending_choice.options}<={v.card_id for v in rows})
        other=self.portable(g);self.choose(other,other.state.pending_choice.options[0].id);self.portable(other)

    def test_arcane_breath_requires_a_held_dragon_and_checks_before_its_damage(self):
        g=self.game(('DRG_106',),own=(DRAGON,),enemy=(UNIT,));self.paid(g,'DRG_106',g.state.players[2].board[0])
        self.assertIsNone(g.state.pending_choice)
        g=self.game(('DRG_106',DRAGON),own=(POWER,),enemy=(UNIT,));self.paid(g,'DRG_106',g.state.players[2].board[0])
        self.assertEqual(self.results(g,'DRG_106')[0].modified_amount,3);self.assertIsNotNone(g.state.pending_choice)
        self.choose(g,g.state.pending_choice.options[0].id);self.portable(g)

    def test_echo_and_illusion_copy_current_buffs_without_injury_then_apply_fixed_stats_and_cost(self):
        for cid in('GVG_005','SCH_352'):
            g=self.game((cid,BUFF,WOUND),own=(UNIT,SECOND,DORMANT,LOCATION));original=g.state.players[1].board[0]
            self.paid(g,BUFF,original);self.paid(g,WOUND,original);self.paid(g,cid)
            copies=[g.state.entities[i]for i in g.state.players[1].hand]
            self.assertEqual([e.card_id for e in copies],[UNIT,SECOND]);self.assertEqual(copies[0].damage,0)
            expected=(1,1,1)if cid=='SCH_352'else(4,11,5)
            self.assertEqual((copies[0].attack,copies[0].max_health,quote_unselected_cost(g.state,g.registry,copies[0]).amount),expected)
            self.assertEqual(copies[0].origin_entity_id,original);self.play(g,UNIT)
            self.assertEqual(g.state.play_history[-1].cost,expected[2])
        self.portable(g)

    def test_echo_copy_overflow_keeps_both_originals_and_records_burned_copy(self):
        g=self.game(('GVG_005',)+(DRAW,)*9,own=(UNIT,SECOND));original=tuple(g.state.players[1].board);self.paid(g,'GVG_005')
        copies=[e for e in g.state.entities.values()if e.origin_entity_id in original]
        self.assertEqual([e.zone for e in copies],[Zone.HAND,Zone.GRAVEYARD]);self.assertEqual(tuple(g.state.players[1].board),original)

    def test_copy_wait_restores_remaining_originals_and_does_not_rebind_departed_body(self):
        g=self.game(('GVG_005',),own=(UNIT,SECOND),mode='copy-wait');self.paid(g,'GVG_005')
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);self.choose(other,'remove')
        self.assertEqual([other.state.entities[i].card_id for i in other.state.players[1].hand],[WATCH,UNIT]);self.portable(other)

    def test_second_copy_failure_rolls_back_original_payment_allocations_and_notifications(self):
        g=self.game(('SCH_352',),own=(UNIT,),mode='copy-fail');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.play(g,'SCH_352')
        self.assertEqual(g.snapshot(),saved)

    def test_star_power_has_five_decreasing_printed_hits_and_current_spell_bonus_per_hit(self):
        for power,expected in(((),[5,4,3,2,1]),((POWER,),[6,5,4,3,2])):
            g=self.game(('JAM_002',),own=power,enemy=(TANK,));self.paid(g,'JAM_002')
            self.assertEqual([v.modified_amount for v in self.results(g,'JAM_002')],expected)
            self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,50-sum(expected))
        self.portable(g)

    def test_star_power_current_targets_follow_death_choice_without_new_cast_or_extra_payment(self):
        g=self.game(('JAM_002',),enemy=(FRAGILE,),mode='star-wait');self.paid(g,'JAM_002')
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);self.choose(other)
        self.assertEqual([v.modified_amount for v in self.results(other,'JAM_002')],[5,4,3,2,1])
        self.assertEqual(self.entity(other,TANK,2,'board').health,40)
        self.assertEqual(sum(v.card_id=='JAM_002'for v in other.state.cast_history),1);self.portable(other)

    def test_star_power_empty_active_target_pool_does_not_hit_hero_or_spend_rng(self):
        g=self.game(('JAM_002',),enemy=(DORMANT,LOCATION));rng=g._rng.getstate();self.paid(g,'JAM_002')
        self.assertEqual(g._rng.getstate(),rng);self.assertFalse(self.results(g,'JAM_002'))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)

    def test_malfunction_chooses_one_conditional_base_budget_and_adds_spell_damage_only_once(self):
        for deck,budget in(((UNIT,),4),((DRAW,),7),((),7)):
            g=self.game(('MIS_107',),own=(POWER,),enemy=(TANK,),deck=deck);self.paid(g,'MIS_107')
            roots=g.state.split_damage_history;self.assertEqual(len(roots),1);self.assertEqual(roots[0].quote.budget,budget)
            rows=self.results(g,'MIS_107');self.assertEqual(len(rows),budget);self.assertTrue(all(v.modified_amount==1 for v in rows))
            self.assertEqual(self.entity(g,TANK,2,'board').health,50-budget)
        self.portable(g)

    def test_malfunction_split_wait_restores_accepted_budget_rng_and_original_tail(self):
        g=self.game(('MIS_107',),enemy=(TANK,),deck=(),mode='split-wait');self.paid(g,'MIS_107')
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);self.choose(other)
        self.assertEqual(len(self.results(other,'MIS_107')),6);self.assertEqual(other.state.split_damage_history[0].quote.budget,6);self.portable(other)

    def test_sky_mother_grows_only_friendly_minions_in_original_hand_deck_and_active_board(self):
        for p in(1,2):
            g=self.game(('TOY_877',UNIT,DRAW),own=(UNIT,DORMANT,LOCATION),enemy=(SECOND,),deck=(SECOND,DRAW),player=p)
            old_hand=self.entity(g,UNIT,p).id;deck_id=g.state.players[p].deck[0];board_id=g.state.players[p].board[0]
            self.paid(g,'TOY_877',player=p)
            self.assertEqual((g.state.entities[old_hand].attack,g.state.entities[old_hand].max_health),(4,11))
            self.assertEqual((g.state.entities[deck_id].attack,g.state.entities[deck_id].max_health),(5,9))
            self.assertEqual((g.state.entities[board_id].attack,g.state.entities[board_id].max_health),(4,11))
            self.assertEqual(self.entity(g,DORMANT,p,'board').max_health,5);self.assertEqual(self.entity(g,LOCATION,p,'board').durability,3)
            self.assertEqual(self.entity(g,SECOND,3-p,'board').max_health,6)
            self.paid(g,DRAW,player=p);self.play(g,SECOND,player=p)
            self.assertEqual((self.entity(g,SECOND,p,'board').attack,self.entity(g,SECOND,p,'board').max_health),(5,9))
        self.portable(g)

    def test_full84_raw_members_remain_and_unclosed_time857_scope_still_rejects_before_rng(self):
        data=native.load_batch();ref=batch.read(data['reference_document']);r=host().registry
        self.assertEqual(len(ref['candidate_ids']),84);self.assertTrue(set(native.LEAVES)<=set(ref['candidate_ids'])&set(r.cards))
        g=self.game(('TIME_857',));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'TIME_857')
        self.assertEqual(g.snapshot(),saved)

    def test_last_conflicting_metadata_rejects_before_any_partial_cards_conditions_or_behaviors(self):
        r=batch.registration_prefix(build_registry,'hs_sim.cards.past_arcane_secrets_copy_damage.register_past_arcane_secrets_copy_damage',
            native.register_past_arcane_secrets_copy_damage)
        bad=replace(host().registry.pool_card(native.LEAVES[-1]),cost=999);r.register_pool_card(bad)
        cards=set(r.cards);behaviors=set(r._behaviors);conditions=dict(r._secret_conditions)
        with self.assertRaises(TargetValidationError):native.register_past_arcane_secrets_copy_damage(r)
        self.assertEqual(set(r.cards),cards);self.assertEqual(set(r._behaviors),behaviors);self.assertEqual(r._secret_conditions,conditions)
