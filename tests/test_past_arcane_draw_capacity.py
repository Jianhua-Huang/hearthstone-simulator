"""Real Arcane consumers retain physical draws, actual capacity and full pools."""
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry, past_arcane_draw_capacity as native
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction, Keyword,
    PlayerSetup, ResolutionError, Ruleset, Scenario, TriggerSpec, Zone)
from hs_sim.engine.board_conditions import IfBoardFull
from hs_sim.engine.costs import local_cost, quote_unselected_cost
from hs_sim.engine.effects import ChoiceOption, Destroy, InvokeBehavior, RequestChoice
from hs_sim.engine.physical_draw_groups import DrawGroupReward
from hs_sim.engine.pools import resolve_candidates, sample_candidates
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import AddToDeck, CardReference, MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k590.'
UNIT, SECOND, WATCH, FAULT, MAKE, POWER, DORMANT, LOCATION, FRAGILE = (
    P+x for x in ('unit','second','watch','fault','make','power','dormant','location','fragile'))
SHOT, DRAW, SECRET = 'DS1_185','CS2_023','EX1_287'


@lru_cache(None)
def host(mode='normal',role='writer'):
    f=build_cn37_local_pool_format();r=f.registry
    def fail(c):raise ResolutionError('K590 deliberate late failure')
    def back(c):return (MoveCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,Zone.HAND,source_id=c.source_id),)
    def watch(c):
        e=c.event
        if e.player_id!=c.player_id:return ()
        source=c.state.entities.get(e.source_id)
        if e.kind!='minion_summoned' and (source is None or source.card_id not in native.LEAVES):return ()
        if e.kind=='card_drawn':
            if mode=='draw-fail' and len(c.state.draw_history)==2:return (InvokeBehavior(FAULT,c.source_id,c.player_id),)
            if mode=='reenter' and len(c.state.draw_history)==2:
                first=next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==UNIT)
                return (MoveCard(CardReference.capture(first),c.player_id,Zone.DECK,source_id=c.source_id),
                    InvokeBehavior(P+'back',c.source_id,c.player_id,target_id=first.id))
            waiting=mode=='draw-wait' and len(c.state.draw_history)==1
        elif e.kind=='minion_summoned' and c.state.entities[e.target_id].card_id==native.PULSAR:
            if mode=='summon-fail':return (InvokeBehavior(FAULT,c.source_id,c.player_id),)
            ids=[e.id for e in c.state.entities.values() if e.controller==c.player_id and e.card_id==native.PULSAR]
            waiting=mode=='summon-wait' and e.target_id==min(ids)
        elif e.kind=='card_added_to_hand':
            if mode=='gen-fail' and len(c.state.players[c.player_id].hand)>=2:
                return (InvokeBehavior(FAULT,c.source_id,c.player_id),)
            waiting=False
        else:return ()
        if not waiting:return ()
        options=(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(InvokeBehavior(FAULT,c.source_id,c.player_id),)))
        if mode=='summon-wait':options+= (ChoiceOption('remove','Remove first Pulsar',(Destroy(e.target_id,c.source_id),)),)
        return (RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(FAULT,fail);r.register_behavior(P+'back',back);r.register_behavior(WATCH,watch)
    r.register_behavior(MAKE,lambda c:(AddToDeck(c.player_id,UNIT,'bottom',c.source_id),))
    r.register_behavior(P+'death',lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(SECOND),),SummonCause.capture(c)),))
    for cid,cost,attack,health in ((UNIT,5,2,6),(SECOND,3,3,4)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,
        triggers=tuple(TriggerSpec(k,WATCH)for k in('card_drawn','minion_summoned','card_added_to_hand'))))
    r.register_card(CardDefinition(MAKE,MAKE,CardType.SPELL,on_play=MAKE))
    r.register_card(CardDefinition(POWER,POWER,CardType.MINION,health=5,spell_damage=1))
    r.register_card(CardDefinition(DORMANT,DORMANT,CardType.MINION,health=5,dormant_turns=2))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,durability=3,on_use=FAULT))
    r.register_card(CardDefinition(FRAGILE,FRAGILE,CardType.MINION,attack=1,health=1,deathrattle=P+'death'))
    r.validate();return f


def two_drop_seed():
    f=host();rows=resolve_candidates(f.registry,f.context,native.POOL,native.TWOS,
        source_card_id='GDB_883',exclude_source_by_rule=True)
    plain={m.card_id for m in rows if not f.registry.card(m.card_id).triggers and not f.registry.card(m.card_id).auras
        and not f.registry.card(m.card_id).colossal and not f.registry.card(m.card_id).dormant_turns}
    return next(n for n in range(10000)if set(sample_candidates(Random(n),rows,2,replacement=True))<=plain)


def evocation_seed(desired,count):
    f=host();rows=resolve_candidates(f.registry,f.context,native.POOL,native.MAGE_SPELLS,
        source_card_id='BT_006',exclude_source_by_rule=True)
    if desired not in {v.card_id for v in rows}:raise ValueError('Expected temporary followup is outside the actual pool')
    return next(n for n in range(10000)if desired in sample_candidates(Random(n),rows,count,replacement=True))


class PastArcaneDrawCapacityTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:host(mode,role).registry)

    def game(self,hand=(),*,deck=None,own=(),enemy=(),other_hand=(),mode='normal',player=1,
            rules=None,seed=3,mana=60,max_mana=60,hero='HERO_08'):
        self.mode=mode;f=host(mode)
        if mode in ('draw-wait','draw-fail','reenter','summon-wait','summon-fail','gen-fail'):own=(WATCH,*own)
        players=tuple(PlayerSetup(hero if p==player else 'HERO_08',hand=hand if p==player else other_hand,
            deck=((UNIT,)*12 if deck is None else deck)if p==player else(UNIT,)*12,
            board=own if p==player else enemy,mana=mana,max_mana=max_mana,mana_cap=60)for p in(1,2))
        return Game.from_scenario(Scenario(players,active_player=player,seed=seed,generation_context=f.context),f.registry,rules)

    def price(self,g,cid,player=1):return quote_unselected_cost(g.state,g.registry,self.entity(g,cid,player)).amount

    def test_complete_eleven_raw_roots_and_three_official_child_faces(self):
        d=native.load_batch();raw={v['record']['id']:v['record']for v in d['dependencies']}
        self.assertEqual(len(raw),14);self.assertEqual(len(d['official_observations']),28)
        for face in d['official_observations']:
            cid=face['card_id'];batch.check_face(raw[cid],face['face'],face['locale'],numeric_normalizations=d['numeric_normalizations'].get(cid))
            if cid in d['fixed_children']:
                self.assertIn(raw[d['fixed_children'][cid]]['dbf_id'],face['face']['childIds'])
        self.assertEqual(native.COLLECTIBLE_ROOTS,());self.assertFalse(d['source_scope_bound'])

    def test_two_filtered_rewards_and_board_condition_validate_their_exact_public_shape(self):
        for kind in ('cost_drawn_minions','cost_drawn_spells'):
            DrawGroupReward(kind,1)
            with self.assertRaises(ValueError):DrawGroupReward(kind,0)
            with self.assertRaises(ValueError):DrawGroupReward(kind,1,2)
        with self.assertRaises(ValueError):DrawGroupReward('cost_unknown',1)
        with self.assertRaises(ValueError):IfBoardFull(1,[])
        with self.assertRaises(ValueError):IfBoardFull(1,('fake-effect',))

    def test_both_deck_cost_spells_filter_original_cards_and_survive_real_draw_and_payment(self):
        for p in(1,2):
            g=self.game(('BOT_257','BT_002',DRAW),deck=(UNIT,SECOND,SHOT,SECRET),player=p)
            original=tuple(g.state.players[p].deck);self.play(g,'BOT_257',player=p)
            self.assertEqual([local_cost(g.state.entities[i])[0]for i in original],[1,1,1,3])
            self.play(g,'BT_002',player=p)
            self.assertEqual([local_cost(g.state.entities[i])[0]for i in original],[1,1,0,2])
            self.assertEqual(self.price(g,DRAW,p),3);self.play(g,DRAW,player=p);self.play(g,UNIT,player=p)
            self.assertEqual(g.state.play_history[-1].cost,1)
        self.portable(g)

    def test_deck_discount_is_not_a_global_modifier_for_later_insertions(self):
        g=self.game(('BOT_257',MAKE),deck=());self.play(g,'BOT_257');self.play(g,MAKE)
        e=g.state.entities[g.state.players[1].deck[0]];self.assertEqual((e.card_id,local_cost(e)[0]),(UNIT,5))

    def test_lunar_visions_reduces_only_original_drawn_minions_in_mixed_pairs(self):
        for deck in((UNIT,SHOT),(SHOT,UNIT)):
            g=self.game(('CFM_811',UNIT),deck=deck);old=self.entity(g,UNIT).id;original=tuple(g.state.players[1].deck)
            self.play(g,'CFM_811');self.assertEqual(g.state.players[1].deck,[])
            self.assertEqual(local_cost(g.state.entities[old])[0],5)
            self.assertEqual([local_cost(g.state.entities[i])[0]for i in original],[3 if g.state.entities[i].kind==CardType.MINION else 1 for i in original])
            self.assertTrue(set(original)<=set(g.state.players[1].hand))

    def test_lunar_visions_burned_arrival_does_not_reduce_other_same_id_hand_cards(self):
        g=self.game(('CFM_811',)+(UNIT,)*9,deck=(UNIT,UNIT));old=set(g.state.players[1].hand);self.play(g,'CFM_811')
        new=set(g.state.players[1].hand)-old;self.assertEqual(len(new),1)
        self.assertEqual(local_cost(g.state.entities[new.pop()])[0],3)
        self.assertTrue(all(local_cost(g.state.entities[i])[0]==5 for i in g.state.players[1].hand if i in old))
        self.assertEqual(len(g.state.draw_history),2)

    def test_revelation_draws_top_card_and_reduces_spells_only_with_real_fatigue(self):
        for cid,amount in((SHOT,0),(UNIT,5)):
            g=self.game(('GDB_852',SHOT),deck=(cid,));old=self.entity(g,SHOT).id;original=g.state.players[1].deck[0]
            self.play(g,'GDB_852');self.assertEqual(local_cost(g.state.entities[original])[0],amount)
            self.assertEqual(local_cost(g.state.entities[old])[0],1)
        g=self.game(('GDB_852',),deck=());self.play(g,'GDB_852')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,29)

    def test_ancient_mysteries_tutors_original_secret_sets_zero_and_real_counter_works(self):
        g=self.game(('ULD_726',SECRET),deck=(UNIT,SECRET,SECOND),other_hand=(DRAW,))
        original=g.state.players[1].deck[1];old=self.entity(g,SECRET).id;self.play(g,'ULD_726')
        self.assertIn(original,g.state.players[1].hand);self.assertEqual(local_cost(g.state.entities[original])[0],0)
        self.assertEqual(local_cost(g.state.entities[old])[0],3)
        from hs_sim.engine import PlayCard
        g.apply(PlayCard(1,original));self.assertEqual(g.state.play_history[-1].cost,0)
        g.apply(EndTurn(1));size=len(g.state.players[2].deck);self.play(g,DRAW,player=2)
        self.assertEqual(len(g.state.players[2].deck),size);self.assertEqual(g.state.cast_history[-1].failure,'countered')
        self.portable(g)

    def test_secret_matching_empty_is_explicit_existing_skip_policy_without_new_rng(self):
        for deck in((),(UNIT,SECOND)):
            g=self.game(('ULD_726',),deck=deck);rng=g._rng.getstate();self.play(g,'ULD_726')
            self.assertEqual(g._rng.getstate(),rng);self.assertEqual(len(g.state.players[1].deck),len(deck))
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)

    def test_typed_draw_waits_restore_original_arrivals_and_complete_reward_once(self):
        for cid,deck,target,price in(('CFM_811',(UNIT,SHOT),UNIT,3),('GDB_852',(SHOT,),SHOT,0)):
            self.mode='draw-wait';g=self.game((cid,),deck=deck,mode='draw-wait');self.play(g,cid)
            saved=g.snapshot();restored=self.portable(g)
            with self.assertRaises(ResolutionError):self.choose(g,'fault')
            self.assertEqual(g.snapshot(),saved)
            for current in(g,restored):self.choose(current)
            self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.price(g,target),price)
        self.portable(g)

    def test_first_arrival_same_id_reentry_during_second_draw_cannot_borrow_old_discount(self):
        g=self.game(('CFM_811',),deck=(UNIT,SHOT),mode='reenter');self.play(g,'CFM_811')
        self.assertEqual(self.price(g,UNIT),5);self.assertEqual(self.price(g,SHOT),1)

    def test_second_draw_failure_rolls_back_payment_physical_draws_rng_and_rewards(self):
        g=self.game(('CFM_811',),deck=(UNIT,SHOT),mode='draw-fail');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate late failure'):self.play(g,'CFM_811')
        self.assertEqual(g.snapshot(),saved)

    def test_cosmic_summons_three_then_uses_actual_capacity_in_both_seats(self):
        for p,count,cap in((1,0,7),(1,1,4),(2,6,7)):
            g=self.game(('GDB_882',),own=(UNIT,)*count,rules=Ruleset(max_board=cap),player=p);self.play(g,'GDB_882',player=p)
            ids=g.state.players[p].board;self.assertEqual(len(ids),min(cap,count+3));full=len(ids)==cap
            pulsars=[g.state.entities[i]for i in ids if g.state.entities[i].card_id==native.PULSAR]
            self.assertTrue(all((e.attack,e.max_health)==((3,4)if full else(2,3))for e in pulsars))
            self.assertTrue(all(Keyword.TAUNT in e.keywords for e in pulsars))
        self.portable(g)

    def test_cosmic_fullness_counts_dormant_and_location_slots_but_buffs_live_minions(self):
        g=self.game(('GDB_882',),own=(DORMANT,LOCATION,UNIT),rules=Ruleset(max_board=4));self.play(g,'GDB_882')
        self.assertEqual(len(g.state.players[1].board),4)
        self.assertEqual((self.entity(g,UNIT,zone='board').attack,self.entity(g,UNIT,zone='board').max_health),(3,7))
        self.assertEqual(self.entity(g,DORMANT,zone='board').max_health,5)
        self.assertEqual(self.entity(g,LOCATION,zone='board').durability,3)
        self.assertEqual(self.entity(g,native.PULSAR,zone='board').max_health,4)

    def test_cosmic_pending_condition_restores_and_checks_current_board_after_remaining_summons(self):
        for key,expected in(('continue',True),('remove',False)):
            g=self.game(('GDB_882',),own=(UNIT,),rules=Ruleset(max_board=5),mode='summon-wait');self.play(g,'GDB_882')
            self.assertIsNotNone(g.state.pending_choice)
            saved=g.snapshot();restored=self.portable(g)
            with self.assertRaises(ResolutionError):self.choose(g,'fault')
            self.assertEqual(g.snapshot(),saved)
            for current in(g,restored):self.choose(current,key)
            self.assertEqual(g.snapshot(),restored.snapshot())
            self.assertIsNone(g.state.pending_choice)
            self.assertEqual(self.entity(g,UNIT,zone='board').max_health,7 if expected else 6)
        self.portable(g)

    def test_cosmic_summon_reaction_failure_rolls_back_entire_cast_and_future_branch(self):
        g=self.game(('GDB_882',),mode='summon-fail');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate late failure'):self.play(g,'GDB_882')
        self.assertEqual(g.snapshot(),saved)

    def test_arcane_defenders_real_taunt_elusive_bodies_allow_untargeted_spell_damage(self):
        g=self.game(('RLK_544',),other_hand=(SHOT,'CS2_025'));self.play(g,'RLK_544')
        bodies=[g.state.entities[i]for i in g.state.players[1].board]
        self.assertEqual([e.card_id for e in bodies],[native.GOLEM]*2)
        self.assertTrue(all((e.attack,e.max_health)==(5,6) and {Keyword.TAUNT,Keyword.ELUSIVE}<=set(e.keywords)for e in bodies))
        g.apply(EndTurn(1));saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,SHOT,bodies[0].id,player=2)
        self.assertEqual(g.snapshot(),saved);self.play(g,'CS2_025',player=2)
        self.assertTrue(all(g.state.entities[e.id].health==5 for e in bodies));self.portable(g)

    def test_arcane_defenders_actual_board_capacity_never_spends_rng_or_creates_extra_bodies(self):
        g=self.game(('RLK_544',),own=(UNIT,)*6);rng=g._rng.getstate();self.play(g,'RLK_544')
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(sum(g.state.entities[i].card_id==native.GOLEM for i in g.state.players[1].board),1)

    def test_real_zero_cost_biscuit_refreshes_two_without_growing_crystals_in_both_seats(self):
        for p in(1,2):
            g=self.game(('YOP_019',),player=p,mana=5,max_mana=8);self.play(g,'YOP_019',player=p)
            self.assertEqual(self.price(g,native.BISCUIT,p),0);self.play(g,native.BISCUIT,player=p)
            self.assertEqual((g.state.players[p].mana,g.state.players[p].max_mana),(5,8))
            self.assertEqual(g.state.play_history[-1].cost,0)
        self.portable(g)

    def test_distress_uses_full_actual_two_drop_candidates_then_refreshes_mana(self):
        g=self.game(('GDB_883',),seed=two_drop_seed(),mana=10,max_mana=10);probe=Random();probe.setstate(g._rng.getstate())
        rows=resolve_candidates(g.registry,g._generation_context,native.POOL,native.TWOS,
            source_card_id='GDB_883',player_id=1,exclude_source_by_rule=True)
        expected=sample_candidates(probe,rows,2,replacement=True);self.play(g,'GDB_883')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],list(expected))
        self.assertEqual(g._rng.getstate(),probe.getstate());self.assertEqual(g.state.players[1].mana,8);self.portable(g)

    def test_distress_full_board_retains_complete_pool_draw_and_refreshes_mana_without_deliveries(self):
        g=self.game(('GDB_883',),own=(UNIT,)*7,mana=10,max_mana=10);board=tuple(g.state.players[1].board)
        probe=Random();probe.setstate(g._rng.getstate())
        rows=resolve_candidates(g.registry,g._generation_context,native.POOL,native.TWOS,
            source_card_id='GDB_883',player_id=1,exclude_source_by_rule=True)
        expected=sample_candidates(probe,rows,2,replacement=True);self.play(g,'GDB_883')
        root=g.state.pool_summon_history[-1]
        self.assertEqual((root.selected,root.rng_after,root.status),(expected,probe.getstate(),'completed'))
        self.assertEqual(g._rng.getstate(),probe.getstate());self.assertEqual(tuple(g.state.players[1].board),board)
        self.assertEqual(len(root.entry_root_ids),2)
        children=[v for v in g.state.card_summon_history if v.id in root.entry_root_ids]
        self.assertEqual(len(children),2);self.assertTrue(all(v.status=='completed' for v in children))
        self.assertTrue(all(d.outcome=='board_full' and d.entity is None for v in children for d in v.deliveries))
        self.assertEqual(sum(len(v.deliveries)for v in children),2)
        self.assertEqual(g.state.players[1].mana,8);self.portable(g)

    def test_evocation_fills_effective_hand_with_fixed_mage_spells_and_expires_only_new_cards(self):
        g=self.game(('BT_006',UNIT),rules=Ruleset(max_hand=6),hero='HERO_03');old=self.entity(g,UNIT).id
        self.play(g,'BT_006');created=set(g.state.players[1].hand)-{old};self.assertEqual(len(created),5)
        for i in created:self.assertIn('mage',[c.value for c in g.registry.card(g.state.entities[i].card_id).metadata.classes])
        g.apply(EndTurn(1));self.assertEqual(g.state.players[1].hand,[old]);self.portable(g)

    def test_temporary_generated_spell_can_be_used_and_its_normal_draws_do_not_expire(self):
        desired='CORE_CS2_023';g=self.game(('BT_006',UNIT),rules=Ruleset(max_hand=6),seed=evocation_seed(desired,5))
        self.play(g,'BT_006');self.play(g,desired);self.assertEqual(len(g.state.players[1].hand),6)
        g.apply(EndTurn(1));self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[UNIT,UNIT])
        self.portable(g)

    def test_evocation_second_generation_failure_restores_payment_rng_and_all_slots(self):
        g=self.game(('BT_006',),mode='gen-fail');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate late failure'):self.play(g,'BT_006')
        self.assertEqual(g.snapshot(),saved)

    def test_shooting_star_hits_only_original_target_and_adjacent_live_slots_in_one_batch(self):
        g=self.game(('BOT_453',),own=(POWER,),enemy=(UNIT,SECOND,UNIT));target=g.state.players[2].board[1]
        self.play(g,'BOT_453',target);rows=[v.health_result for v in g.state.damage_history if v.health_result.source_card_id=='BOT_453']
        self.assertEqual(len(rows),3);self.assertEqual(len({v.batch_id for v in rows}),1)
        self.assertEqual([v.modified_amount for v in rows],[2,2,2])
        g=self.game(('BOT_453',),enemy=(UNIT,DORMANT,SECOND));self.play(g,'BOT_453',g.state.players[2].board[0])
        self.assertEqual(self.entity(g,SECOND,2,'board').health,4)
        self.assertEqual(self.entity(g,DORMANT,2,'board').health,5)

    def test_shooting_star_does_not_damage_bodies_created_by_original_deaths(self):
        g=self.game(('BOT_453',),enemy=(FRAGILE,FRAGILE,FRAGILE));self.play(g,'BOT_453',g.state.players[2].board[1])
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[4,4,4]);self.portable(g)

    def test_full84_membership_stays_intact_and_production_source_remains_closed(self):
        ref=batch.read(native.load_batch()['reference_document']);r=host().registry
        self.assertEqual(len(ref['candidate_ids']),84);self.assertEqual(sum(cid in r.cards for cid in ref['candidate_ids']),35)
        g=self.game(('TIME_857',));saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Unreviewed generation scope'):self.play(g,'TIME_857')
        self.assertEqual(g.snapshot(),saved)

    def test_last_bad_token_metadata_rejects_before_partial_native_registration(self):
        r=build_registry()
        bad=replace(r.pool_card(native.BISCUIT),cost=1)
        for cid in native.DEPENDENCIES:r._cards.pop(cid);r._pool_cards.pop(cid)
        r.register_pool_card(bad);before=(dict(r.cards),dict(r.pool_cards),dict(r._behaviors))
        with self.assertRaises(TargetValidationError):native.register_past_arcane_draw_capacity(r)
        self.assertEqual((dict(r.cards),dict(r.pool_cards),dict(r._behaviors)),before)

    def test_private_generated_hand_and_internal_reward_material_are_not_opponent_information(self):
        g=self.game(('BT_006',),player=2,rules=Ruleset(max_hand=6));self.play(g,'BT_006',player=2)
        first=g.state.entities[g.state.players[2].hand[0]].card_id
        self.assertIn(first,json.dumps(g.observe(2)));self.assertNotIn(first,json.dumps(g.observe(1)))
        for p in(1,2):
            view=json.dumps(g.observe(p))
            for field in('on_full','draw_group','arrivals','rng_state','resolution_frame'):
                self.assertNotIn('"'+field+'"',view)


if __name__=='__main__':unittest.main()
