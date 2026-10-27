"""Real past Mage entries over original draws, death results and native summons."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import past_mage_summon_draw_chains as native
from hs_sim.engine import CardClass,CardDefinition,CardType,EndTurn,Game,PlayerSetup,ResolutionError,Scenario,TriggerSpec
from hs_sim.engine.costs import quote_cost,quote_generated_cost
from hs_sim.engine.effects import ChoiceOption,Damage,Destroy,InvokeBehavior,RequestChoice,Summon
from hs_sim.engine.model import CardMetadata,DamageKind,Keyword,Rarity,SpellSchool,TargetSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

BREATH,MANUFACTURE,SEAFLOOR,EXPERIMENT,FINALE,STITCH,DEATHBORNE,TSUNAMI,DRINK=native.LEAVES
FIREWORKS,DRINK2,DRINK1=native.TOKENS
WATER,SKELETON=native.EXISTING
P='k605.'
NOOP,FIRE,FROST,MECH,OTHERMECH,ALL,PLAIN,SMALL,BIG,POWER,EL,TWO,THREE,FOUR,KILL,CONJURE,WAIT_DRAW,WAIT_SUMMON,WAIT_SPLIT,DOOM,ADD_DECK,DROP_POWER,OTHER_KILL=(
    P+s for s in('noop','fire','frost','mech','othermech','all','plain','small','big','power','elemental','two','three','four','kill','conjure',
    'wait_draw','wait_summon','wait_split','doom','add_deck','drop_power','other_kill'))
META=CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


def context(mode='normal'):return GenerationContext(P+'complete-diagnostic-'+mode,'experimental')


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=build_registry();r.register_behavior(NOOP,lambda c:())
    def fault(c):raise ResolutionError('K605 deliberate saved-branch failure')
    r.register_behavior(P+'fault',fault)
    def wait(c):return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
        ChoiceOption('fault','Fail',(InvokeBehavior(P+'fault',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(P+'wait',wait)
    r.register_behavior(KILL,lambda c:(Destroy(c.target_id,c.source_id),))
    r.register_behavior(CONJURE,lambda c:(Summon(c.player_id,EL),))
    for cid,school in((NOOP,None),(FIRE,SpellSchool.FIRE),(FROST,SpellSchool.FROST)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=0 if cid==NOOP else 4,on_play=NOOP,spell_school=school,metadata=META))
    r.register_card(CardDefinition(KILL,KILL,CardType.SPELL,on_play=KILL,targeting=TargetSpec(),metadata=META))
    r.register_card(CardDefinition(CONJURE,CONJURE,CardType.SPELL,on_play=CONJURE,metadata=META))
    for cid,cost,health,tribes,power in((MECH,2,5,('mech',),0),(OTHERMECH,4,5,('mech',),0),(ALL,4,5,('all',),0),
            (PLAIN,4,8,(),0),(SMALL,2,2,(),0),(BIG,1,20,(),0),(POWER,1,1,(),1),(EL,0,1,('elemental',),0),
            (TWO,2,5,(),0),(THREE,3,5,(),0),(FOUR,4,5,(),0),(DOOM,3,3,(),0)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=health,spell_damage=power,
            metadata=replace(META,tribes=tribes),deathrattle=P+'wait' if cid==DOOM else None))
    def watch(c):
        event=c.event;source=c.state.entities.get(event.source_id);target=c.state.entities.get(event.target_id);who=c.source.card_id
        if who==WAIT_DRAW and event.kind=='card_drawn' and source is not None and source.card_id in(MANUFACTURE,SEAFLOOR):return wait(c)
        if who==ADD_DECK and event.kind=='card_drawn' and source is not None and source.card_id==MANUFACTURE:
            if len(c.state.players[c.player_id].hand)==1:return(AddToDeck(c.player_id,PLAIN,'bottom',c.source_id),)
        if who==WAIT_SUMMON and event.kind=='minion_summoned' and target is not None and target.card_id in(WATER,SKELETON,FIREWORKS):return wait(c)
        if who==DROP_POWER and event.kind=='minion_summoned' and target is not None and target.card_id==THREE:
            return tuple(Destroy(i,c.source_id) for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==POWER)
        if who==WAIT_SPLIT and event.kind=='damage_dealt' and source is not None and source.card_id==DRINK and target is not None and target.health==19:return wait(c)
        if who==OTHER_KILL and event.kind=='damage_dealt' and source is not None and source.card_id in(STITCH,DEATHBORNE):
            if target is not None and target.controller!=c.player_id and target.health>0:return(Destroy(target.id,c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    for cid,event in((WAIT_DRAW,'card_drawn'),(ADD_DECK,'card_drawn'),(WAIT_SUMMON,'minion_summoned'),
            (DROP_POWER,'minion_summoned'),(WAIT_SPLIT,'damage_dealt'),(OTHER_KILL,'damage_dealt')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=30,metadata=META,triggers=(TriggerSpec(event,P+'watch'),)))
    members=[TWO,THREE,FOUR]
    for cid in members:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if mode=='unknown':
        unknown=P+'unknown_three';r.register_pool_card(PoolCard(unknown,CardType.MINION,3,META));members.append(unknown)
    r.register_pool(PoolDefinition(native.POOL,P+'complete-v1',context(mode).target_id,'experimental',tuple(PoolMember(i)for i in members),complete=True))
    r.validate();return r


class PastMageSummonDrawChainTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'

    def game(self,hand=(),*,deck=(NOOP,)*6,board=(),enemy_board=(),player=1,mode='normal'):
        self.mode=mode
        setups=tuple(PlayerSetup('HERO_08',hand=hand if p==player else(),deck=deck if p==player else(NOOP,)*6,
            board=board if p==player else enemy_board,mana=30,max_mana=30,mana_cap=30)for p in(1,2))
        return Game.from_scenario(Scenario(setups,active_player=player,seed=605,generation_context=context(mode)),registry(mode))

    def paid(self,g,cid,target=None,player=1):
        e=self.entity(g,cid,player);cost=quote_cost(g.state,g.registry,e).amount;mana=g.state.players[player].mana
        source=self.play(g,cid,target,player);self.assertEqual(g.state.players[player].mana,mana-cost)
        self.assertEqual((g.state.play_history[-1].card_id,g.state.play_history[-1].cost),(cid,cost));return source

    def cost(self,g,cid,p=1):return quote_cost(g.state,g.registry,self.entity(g,cid,p)).amount

    def board_ids(self,g,cid,p=1):return [i for i in g.state.players[p].board if g.state.entities[i].card_id==cid]

    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]

    def test_full_fifteen_source_rows_thirty_primary_faces_real_roles_and_unimplemented_evidence(self):
        data=native.load_batch();rows={r['record']['id']:r for key in('dependencies','existing_dependencies','evidence_only')for r in data[key]}
        self.assertEqual((len(rows),len(data['official_observations'])),(15,30))
        for obs in data['official_observations']:batch.check_face(rows[obs['card_id']]['record'],obs['face'],obs['locale'])
        self.assertEqual((len(data['dependencies']),len(data['existing_dependencies']),len(data['evidence_only'])),(12,2,1))
        self.assertEqual((registry().card(FIREWORKS).cost,registry().card(FIREWORKS).attack,registry().card(FIREWORKS).health),(8,8,8))
        self.assertTrue(all(not registry().card(i).metadata.collectible for i in native.TOKENS))
        self.assertTrue(registry().card(SKELETON).metadata.collectible);self.assertNotIn('WW_377',registry().cards)
        self.assertEqual(native.COLLECTIBLE_ROOTS,())
        for row in data['existing_dependencies']:
            cid=row['record']['id'];self.assertEqual(batch.canonical(asdict(registry().card(cid))),row['definition_sha256'])

    def test_dragons_breath_counts_both_sides_actual_deaths_this_turn_and_real_payment_both_seats(self):
        for p in(1,2):
            g=self.game((KILL,KILL,BREATH),board=(SMALL,),enemy_board=(SMALL,),player=p)
            self.paid(g,KILL,g.state.players[p].board[0],p);self.paid(g,KILL,g.state.players[3-p].board[0],p)
            self.assertEqual(self.cost(g,BREATH,p),3);self.assertEqual(quote_generated_cost(g.state,g.registry,p,BREATH).amount,3)
            self.paid(g,BREATH,g.state.players[3-p].hero_id,p);self.assertEqual(self.hero(g,3-p).health,26)

    def test_dragons_breath_current_turn_price_resets_on_next_owner_turn(self):
        g=self.game((KILL,BREATH),enemy_board=(SMALL,));self.paid(g,KILL,g.state.players[2].board[0]);self.assertEqual(self.cost(g,BREATH),4)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(self.cost(g,BREATH),5);self.portable(g)

    def test_manufacturing_draws_three_original_cards_and_freezes_initial_no_minion_condition(self):
        g=self.game((MANUFACTURE,),deck=(FIRE,FROST,FIRE),board=(ADD_DECK,));self.paid(g,MANUFACTURE)
        self.assertEqual([quote_cost(g.state,g.registry,g.state.entities[i]).amount for i in g.state.players[1].hand],[1,1,1])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[PLAIN])
        g=self.game((MANUFACTURE,),deck=(MECH,FIRE,FROST));self.paid(g,MANUFACTURE)
        self.assertEqual((self.cost(g,MECH),self.cost(g,FIRE),self.cost(g,FROST)),(2,4,4))

    def test_manufacturing_wait_restore_keeps_whole_original_group_reward_and_failure_rollback(self):
        g=self.game((MANUFACTURE,),deck=(FIRE,FIRE,FIRE),board=(WAIT_DRAW,));self.paid(g,MANUFACTURE)
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for obj in(g,other):
            while obj.state.pending_choice is not None:self.choose(obj)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual([quote_cost(g.state,g.registry,g.state.entities[i]).amount for i in g.state.players[1].hand],[1,1,1])

    def test_manufacturing_empty_deck_uses_three_ordinary_fatigue_draws(self):
        g=self.game((MANUFACTURE,),deck=());self.paid(g,MANUFACTURE);self.assertEqual(self.hero(g).health,24)

    def test_seafloor_draws_actual_mech_then_reduces_all_current_held_mechs_including_all_tribes(self):
        g=self.game((SEAFLOOR,OTHERMECH,ALL,PLAIN),deck=(MECH,FIRE));self.paid(g,SEAFLOOR)
        self.assertEqual((self.cost(g,MECH),self.cost(g,OTHERMECH),self.cost(g,ALL),self.cost(g,PLAIN)),(1,3,3,4))
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[FIRE])

    def test_seafloor_empty_match_still_reduces_held_mechs_without_fatigue_or_rng(self):
        g=self.game((SEAFLOOR,MECH),deck=());rng=g.snapshot()['rng_state'];self.paid(g,SEAFLOOR)
        self.assertEqual(self.cost(g,MECH),1);self.assertEqual(self.hero(g).health,30);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_seafloor_wait_restores_before_late_whole_hand_cost_reward(self):
        g=self.game((SEAFLOOR,OTHERMECH),deck=(MECH,),board=(WAIT_DRAW,));self.paid(g,SEAFLOOR)
        self.assertEqual(self.cost(g,OTHERMECH),4);other=self.portable(g)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual((self.cost(g,MECH),self.cost(g,OTHERMECH)),(1,3))

    def test_unexpected_results_two_named_cost_queries_and_original_spell_damage_cost_is_frozen(self):
        g=self.game((EXPERIMENT,),board=(POWER,DROP_POWER));self.paid(g,EXPERIMENT)
        self.assertEqual(len(self.board_ids(g,THREE)),2);self.assertFalse(self.board_ids(g,POWER));self.assertFalse(self.board_ids(g,TWO))
        g=self.game((EXPERIMENT,));self.paid(g,EXPERIMENT);self.assertEqual(len(self.board_ids(g,TWO)),2)

    def test_unexpected_results_full_board_and_unknown_eligible_member_roll_back(self):
        g=self.game((EXPERIMENT,),board=(PLAIN,)*7);rng=g.snapshot()['rng_state'];self.paid(g,EXPERIMENT)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g.snapshot()['rng_state'],rng)
        g=self.game((EXPERIMENT,),board=(POWER,),mode='unknown');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'[Uu]nsupported|[Mm]issing|executable'):self.play(g,EXPERIMENT)
        self.assertEqual(g.snapshot(),saved)

    def test_grand_finale_base_one_and_actual_previous_owner_elemental_plays_exclude_direct_summons(self):
        g=self.game((FINALE,));self.paid(g,FINALE);self.assertEqual(len(self.board_ids(g,FIREWORKS)),1)
        for p in(1,2):
            g=self.game((EL,EL,CONJURE,FINALE),player=p);self.paid(g,EL,player=p);self.paid(g,EL,player=p);self.paid(g,CONJURE,player=p)
            g.apply(EndTurn(p));g.apply(EndTurn(3-p));self.paid(g,FINALE,player=p)
            self.assertEqual(len(self.board_ids(g,FIREWORKS,p)),3)

    def test_grand_finale_latest_empty_owner_interval_replaces_older_elemental_turn(self):
        g=self.game((EL,FINALE));self.paid(g,EL);g.apply(EndTurn(1));g.apply(EndTurn(2));g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.paid(g,FINALE);self.assertEqual(len(self.board_ids(g,FIREWORKS)),1)

    def test_cross_stitch_real_kill_summons_original_water_elemental_and_nonlethal_has_no_reward(self):
        g=self.game((STITCH,),enemy_board=(SMALL,));self.paid(g,STITCH,g.state.players[2].board[0])
        self.assertEqual(len(self.board_ids(g,WATER)),1);water=g.state.entities[self.board_ids(g,WATER)[0]];self.assertEqual((water.attack,water.health),(3,6))
        g=self.game((STITCH,),enemy_board=(BIG,));self.paid(g,STITCH,g.state.players[2].board[0]);self.assertFalse(self.board_ids(g,WATER))

    def test_cross_stitch_reaction_destroy_does_not_forge_damage_kill_and_full_board_blocks_only_reward(self):
        g=self.game((STITCH,),board=(OTHER_KILL,),enemy_board=(BIG,));target=g.state.players[2].board[0];self.paid(g,STITCH,target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertFalse(self.board_ids(g,WATER))
        g=self.game((STITCH,),board=(PLAIN,)*7,enemy_board=(SMALL,));self.paid(g,STITCH,g.state.players[2].board[0]);self.assertEqual(len(g.state.players[1].board),7)

    def test_cross_stitch_death_wait_restores_exact_original_result_and_summon_cast_attribution(self):
        g=self.game((STITCH,),enemy_board=(DOOM,));self.paid(g,STITCH,g.state.players[2].board[0]);self.assertFalse(self.board_ids(g,WATER))
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(len(self.board_ids(g,WATER)),1)

    def test_deathborne_batch_counts_both_sides_original_killed_minions_without_damaging_new_skeletons(self):
        g=self.game((DEATHBORNE,),board=(SMALL,),enemy_board=(SMALL,SMALL));self.paid(g,DEATHBORNE)
        self.assertEqual(len(self.board_ids(g,SKELETON)),3);self.assertTrue(all(g.state.entities[i].health==2 for i in self.board_ids(g,SKELETON)))
        self.assertFalse(g.state.players[2].board)

    def test_deathborne_unrelated_reaction_kill_and_empty_board_do_not_create_skeletons(self):
        g=self.game((DEATHBORNE,),board=(OTHER_KILL,),enemy_board=(BIG,));self.paid(g,DEATHBORNE);self.assertFalse(self.board_ids(g,SKELETON))
        g=self.game((DEATHBORNE,));self.paid(g,DEATHBORNE);self.assertFalse(g.state.players[1].board)

    def test_deathborne_original_spell_damage_provider_dying_does_not_shrink_later_packets(self):
        g=self.game((DEATHBORNE,),board=(POWER,),enemy_board=(DOOM,DOOM));self.paid(g,DEATHBORNE)
        while g.state.pending_choice is not None:self.choose(g)
        self.assertEqual(len(self.board_ids(g,SKELETON)),3)

    def test_tsunami_summons_three_original_waters_each_forced_attacks_and_freezes_enemy_hero(self):
        for p in(1,2):
            g=self.game((TSUNAMI,),player=p);self.paid(g,TSUNAMI,player=p)
            self.assertEqual(len(self.board_ids(g,WATER,p)),3);self.assertEqual(self.hero(g,3-p).health,21);self.assertTrue(self.hero(g,3-p).frozen)
            self.assertTrue(all(g.state.entities[i].attacks_this_turn==0 for i in self.board_ids(g,WATER,p)))
            self.assertCountEqual([e.source_id for e in g.events if e.kind=='attack_declared'],self.board_ids(g,WATER,p))

    def test_tsunami_full_board_cannot_attack_with_existing_water_or_consume_randomness(self):
        g=self.game((TSUNAMI,),board=(WATER,)+(PLAIN,)*6);rng=g.snapshot()['rng_state'];self.paid(g,TSUNAMI)
        self.assertEqual(self.hero(g,2).health,30);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_tsunami_original_named_followup_waits_restore_rollback_and_sequential_attacks(self):
        g=self.game((TSUNAMI,),board=(WAIT_SUMMON,));self.paid(g,TSUNAMI);self.assertEqual(self.hero(g,2).health,30)
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for obj in(g,other):
            self.choose(obj);self.assertEqual(self.hero(obj,2).health,27)
            while obj.state.pending_choice is not None:self.choose(obj)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.hero(g,2).health,21)

    def test_three_drinks_real_successor_identities_independent_payments_and_one_spell_bonus_per_split(self):
        g=self.game((DRINK,),board=(POWER,),enemy_board=(BIG,));target=g.state.players[2].board[0]
        for cid in(DRINK,DRINK2,DRINK1):self.paid(g,cid)
        self.assertEqual(g.state.entities[target].health,11);self.assertFalse(g.state.players[1].hand);self.assertEqual(g.state.players[1].mana,27)
        self.assertEqual([p.card_id for p in g.state.play_history],[DRINK,DRINK2,DRINK1])

    def test_drinks_empty_enemy_minion_pool_still_gives_successor_without_rng_or_hero_damage(self):
        g=self.game((DRINK,));rng=g.snapshot()['rng_state']
        for cid in(DRINK,DRINK2,DRINK1):self.paid(g,cid)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(self.hero(g,2).health,30);self.assertFalse(g.state.players[1].hand)

    def test_drink_packet_wait_keeps_undelivered_successor_and_original_budget_restore_replay(self):
        g=self.game((DRINK,),board=(WAIT_SPLIT,),enemy_board=(BIG,));target=g.state.players[2].board[0];self.paid(g,DRINK)
        self.assertIsNotNone(g.state.pending_choice);self.assertFalse(g.state.players[1].hand);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(g.state.entities[target].health,18);self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id,DRINK2)

    def test_bad_last_dependency_rejects_before_any_partial_cards_or_behaviors(self):
        data=deepcopy(native.load_batch());data['dependencies'][-1]['record']['collectible']=True
        r=batch.registration_prefix(build_registry,'hs_sim.cards.past_mage_summon_draw_chains.register_past_mage_summon_draw_chains',native.register_past_mage_summon_draw_chains)
        before=(dict(r.cards),dict(r.pool_cards),dict(r._behaviors))
        with patch.object(native,'load_batch',return_value=data):
            with self.assertRaises(TargetValidationError):native.register_past_mage_summon_draw_chains(r)
        self.assertEqual((r.cards,r.pool_cards,r._behaviors),before)


if __name__=='__main__':unittest.main()
