"""Fifteen real Mage spells share existing writers; verify actual entries by effect."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import past_mage_primitive_spells as native
from hs_sim.engine import (CardClass, CardDefinition, CardType, CastSpell, Game, IllegalAction, Keyword,
    PlayCard, PlayerSetup, ResolutionError, Scenario, TriggerSpec)
from hs_sim.engine.effects import (Buff, ChoiceOption, Destroy, Draw, GainArmor, GrantKeyword, InvokeBehavior, RequestChoice)
from hs_sim.engine.model import CardMetadata, Rarity, TargetSpec, Zone
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.representative import build_registry
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

LANCE, REPRINT, VOLCANIC, NOVA, ICE, BOLT, CANNON, CINDER, MASK, RESEARCH, SHATTER, BLAST, PUZZLE, BOX, MIRROR = native.LEAVES
P = 'k601.'
UNIT, BIG, SMALL, POWER, PLAIN, CHEAP, EXPENSIVE, BUFF, AUTO_CANNON, FAULT = (
    P+x for x in ('unit','big','small','power','plain','cheap','expensive','buff','auto_cannon','fault'))
SPLIT_WAIT, DRAW_WAIT, CAST_WAIT, ALTER_DECK = (P+x for x in ('split_wait','draw_wait','cast_wait','alter_deck'))
CTX = GenerationContext('k601-complete-explicit-diagnostic-pool','experimental')
META = CardMetadata(True,(CardClass.PALADIN,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r = build_registry();native.register_past_mage_primitive_spells(r)
    def fail(c):raise ResolutionError('K601 deliberate original continuation failure')
    def buff(c):return (Buff(c.target_id,2,3,c.source_id),GrantKeyword(c.target_id,Keyword.TAUNT,c.source_id))
    def watch(c):
        event = c.event;source = c.state.entities.get(event.source_id);cid = c.source.card_id
        options = (ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(InvokeBehavior(FAULT,c.source_id,c.player_id),)))
        if cid == SPLIT_WAIT and event.kind == 'damage_dealt' and source is not None and source.card_id in (CINDER,MASK):
            if len(c.state.damage_history) == 1:
                provider = next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == POWER)
                return (RequestChoice(c.player_id,options+(ChoiceOption('remove','Remove provider',(Destroy(provider.id,c.source_id),)),),c.source_id),)
        if cid == DRAW_WAIT and event.kind == 'card_drawn' and event.player_id == c.player_id and source is not None and source.card_id == BOLT:
            return (RequestChoice(c.player_id,options,c.source_id),)
        if event.kind == 'spell_cast_started' and source is not None and source.card_id in (CHEAP,EXPENSIVE):
            row = c.state.cast_history[-1];producer = c.state.entities.get(row.caster_id)
            if producer is None or producer.card_id not in (PUZZLE,BOX):return ()
            children = [x for x in c.state.cast_history if x.caster_id == row.caster_id]
            if len(children) == 1:
                if cid == CAST_WAIT:return (RequestChoice(c.player_id,options,c.source_id),)
                if cid == ALTER_DECK:return (AddToDeck(c.player_id,UNIT,'top',c.source_id),)
        return ()
    bodies = {FAULT:fail,PLAIN:lambda c:(),CHEAP:lambda c:(GainArmor(c.player_id,1),),
        EXPENSIVE:lambda c:(GainArmor(c.player_id,2),),BUFF:buff,AUTO_CANNON:lambda c:(CastSpell(c.player_id,CANNON,c.source_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,
            cost=1 if cid == CHEAP else 5 if cid == EXPENSIVE else 0,on_play=cid,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')if cid == BUFF else None,
            metadata=META if cid in (CHEAP,EXPENSIVE)else None))
    for cid in (CHEAP,EXPENSIVE):r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    for cid,attack,health,power in ((UNIT,2,8,0),(BIG,2,50,0),(SMALL,1,2,0),(POWER,1,2,2)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=health,spell_damage=power))
    r.register_behavior(P+'watch',watch)
    for cid in (SPLIT_WAIT,DRAW_WAIT,CAST_WAIT,ALTER_DECK):r.register_card(CardDefinition(cid,cid,CardType.MINION,health=20,
        triggers=tuple(TriggerSpec(event,P+'watch')for event in ('damage_dealt','card_drawn','spell_cast_started'))))
    members = (EXPENSIVE,)if mode == 'high'else(CHEAP,)if mode == 'low'else(CHEAP,EXPENSIVE)
    if mode == 'unknown':
        r.register_pool_card(PoolCard(P+'unknown',CardType.SPELL,1,META));members = (P+'unknown',EXPENSIVE)
    r.register_pool(PoolDefinition(native.POOL,P+'complete-domain-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in members),complete=True))
    r.validate();return r


class PastMagePrimitiveSpellTests(CardBatchTestMixin,unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(registry)

    def game(self,hand=(),*,deck=(),board=(),enemy_board=(),player=1,mode='normal'):
        self.mode = mode
        players = tuple(PlayerSetup('HERO_08',hand=hand if p == player else (),deck=deck if p == player else (PLAIN,)*5,
            board=board if p == player else enemy_board,mana=20,max_mana=20,mana_cap=20)for p in (1,2))
        return Game.from_scenario(Scenario(players,active_player=player,seed=601,generation_context=CTX),registry(mode))

    def paid(self,g,cid,target=None,player=1):
        mana = g.state.players[player].mana;source = self.play(g,cid,target=target,player=player)
        self.assertEqual(g.state.players[player].mana,mana-g.registry.card(cid).cost)
        self.assertEqual((g.state.play_history[-1].card_id,g.state.play_history[-1].cost),(cid,g.registry.card(cid).cost));return source

    def hero(self,g,p):return g.state.entities[g.state.players[p].hero_id]

    def children(self,g,source):return tuple(c for c in g.state.cast_history if c.caster_id == source)

    def test_fifteen_full_sources_thirty_primary_faces_and_original_school_cost_roles(self):
        data = native.load_batch();rows = {x['record']['id']:x for x in data['dependencies']}
        self.assertEqual((len(rows),len(data['official_observations'])),(15,30))
        for obs in data['official_observations']:batch.check_face(rows[obs['card_id']]['record'],obs['face'],obs['locale'])
        self.assertEqual(native.COLLECTIBLE_ROOTS,())
        for cid,row in rows.items():
            card = registry().card(cid);self.assertEqual(card.cost,row['record']['cost'])
            self.assertEqual(None if card.spell_school is None else card.spell_school.value,row['spell_school'])

    def test_both_lance_editions_have_real_minion_only_target_and_spell_damage_in_both_seats(self):
        for cid in (LANCE,REPRINT):
            for player in (1,2):
                g = self.game((cid,),board=(POWER,),enemy_board=(BIG,),player=player)
                target = g.state.players[3-player].board[0];before = g.snapshot()
                with self.assertRaises(IllegalAction):self.play(g,cid,target=g.state.players[3-player].hero_id,player=player)
                self.assertEqual(g.snapshot(),before);self.paid(g,cid,target,player)
                self.assertEqual(g.state.entities[target].health,23)
        self.portable(g)

    def test_volcanic_damage_batch_accepts_bonus_before_provider_dies(self):
        g = self.game((VOLCANIC,),board=(POWER,),enemy_board=(BIG,));provider = g.state.players[1].board[0]
        target = g.state.players[2].board[0];self.paid(g,VOLCANIC)
        self.assertNotIn(provider,g.state.players[1].board);self.assertEqual(g.state.entities[target].health,46)
        self.assertEqual((self.hero(g,1).health,self.hero(g,2).health),(30,30));self.portable(g)

    def test_nova_shatter_and_all_frozen_destruction_share_real_current_board_status(self):
        g = self.game((NOVA,SHATTER,ICE,BLAST),board=(BIG,),enemy_board=(BIG,BIG))
        own = g.state.players[1].board[0];first,second = g.state.players[2].board;self.paid(g,NOVA)
        self.assertFalse(g.state.entities[own].frozen);self.assertTrue(all(g.state.entities[i].frozen for i in (first,second)))
        g = self.portable(g);before = g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,SHATTER,target=own)
        self.assertEqual(g.snapshot(),before);self.paid(g,SHATTER,first);self.paid(g,ICE,own);self.paid(g,BLAST)
        self.assertFalse(g.state.players[1].board);self.assertFalse(g.state.players[2].board);self.portable(g)

    def test_ice_lance_freezes_first_then_damages_instead_without_another_freeze(self):
        g = self.game((ICE,ICE),board=(POWER,));enemy = g.state.players[2].hero_id
        self.paid(g,ICE,enemy);count = sum(e.kind == 'frozen'for e in g.events)
        self.assertTrue(g.state.entities[enemy].frozen);self.assertEqual(self.hero(g,2).health,30)
        self.paid(g,ICE,enemy);self.assertEqual(self.hero(g,2).health,24)
        self.assertEqual(sum(e.kind == 'frozen'for e in g.events),count);self.portable(g)

    def test_ice_bolt_lethal_frozen_target_still_draws_original_deck_card_in_both_seats(self):
        for player in (1,2):
            g = self.game((ICE,BOLT),deck=(PLAIN,),enemy_board=(SMALL,),player=player)
            target = g.state.players[3-player].board[0];original = g.state.players[player].deck[0]
            self.paid(g,ICE,target,player);source = self.paid(g,BOLT,target,player)
            self.assertNotIn(target,g.state.players[3-player].board);self.assertEqual(g.state.players[player].hand,[original])
            row, = g.state.draw_history;self.assertEqual(row.source_id,source);self.assertTrue(row.completed)
        self.portable(g)

    def test_ice_bolt_unfrozen_target_has_no_draw_or_fatigue(self):
        g = self.game((BOLT,),enemy_board=(BIG,));target = g.state.players[2].board[0];self.paid(g,BOLT,target)
        self.assertEqual(g.state.entities[target].health,48);self.assertFalse(g.state.draw_history);self.portable(g)

    def test_ice_bolt_draw_wait_restore_and_failed_resume_keep_actual_dead_target_reward(self):
        g = self.game((ICE,BOLT),deck=(PLAIN,),board=(DRAW_WAIT,),enemy_board=(SMALL,))
        target = g.state.players[2].board[0];self.paid(g,ICE,target);self.paid(g,BOLT,target)
        self.assertNotIn(target,g.state.players[2].board);other = self.portable(g);before = other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),before);self.choose(other);self.assertEqual(len(other.state.draw_history),1);self.portable(other)

    def test_flamecannon_public_minimum_gate_random_enemy_only_and_automatic_empty_handling(self):
        g = self.game((CANNON,));before = g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,CANNON)
        self.assertEqual(g.snapshot(),before)
        g = self.game((CANNON,),board=(BIG,),enemy_board=(BIG,));own = g.state.players[1].board[0];enemy = g.state.players[2].board[0]
        self.paid(g,CANNON);self.assertEqual((g.state.entities[own].health,g.state.entities[enemy].health),(50,46));self.portable(g)
        g = self.game((AUTO_CANNON,));self.play(g,AUTO_CANNON)
        self.assertFalse(g.state.damage_history);self.assertEqual((self.hero(g,1).health,self.hero(g,2).health),(30,30));self.portable(g)

    def test_cinderstorm_and_mask_use_one_whole_budget_bonus_not_one_bonus_per_packet(self):
        for cid,base in ((CINDER,5),(MASK,10)):
            g = self.game((cid,),board=(POWER,));self.paid(g,cid)
            self.assertEqual(self.hero(g,2).health,30-base-2);self.assertEqual(len(g.state.damage_history),base+2)
            self.assertEqual(len(g.state.split_damage_history),1)
        self.portable(g)

    def test_split_wait_removing_provider_preserves_original_remaining_budget_and_rng(self):
        g = self.game((MASK,),board=(POWER,SPLIT_WAIT));self.paid(g,MASK);self.assertEqual(len(g.state.damage_history),1)
        other = self.portable(g);before = other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),before);self.choose(other,'remove')
        self.assertEqual(self.hero(other,2).health,18);self.assertEqual(len(other.state.damage_history),12);self.portable(other)

    def test_research_project_uses_two_original_draws_for_each_actual_player(self):
        for player in (1,2):
            g = self.game((RESEARCH,),deck=(PLAIN,)*4,player=player)
            original = {p:tuple(g.state.players[p].deck[:2])for p in (1,2)};source = self.paid(g,RESEARCH,player=player)
            self.assertEqual([r.player_id for r in g.state.draw_history],[player,player,3-player,3-player])
            for p in (1,2):self.assertEqual(g.state.players[p].hand,list(original[p]))
            self.assertTrue(all(r.completed and r.source_id == source for r in g.state.draw_history))
        self.portable(g)

    def test_molten_reflection_has_friendly_target_and_copies_current_stats_abilities_with_new_identity(self):
        g = self.game((BUFF,MIRROR),board=(UNIT,),enemy_board=(UNIT,));original = g.state.players[1].board[0];enemy = g.state.players[2].board[0]
        self.play(g,BUFF,target=original);before = g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,MIRROR,target=enemy)
        self.assertEqual(g.snapshot(),before);source = self.paid(g,MIRROR,original);self.assertEqual(len(g.state.players[1].board),2)
        copy = g.state.entities[g.state.players[1].board[-1]];self.assertNotEqual(copy.id,original)
        self.assertEqual((copy.attack,copy.health),(4,11));self.assertIn(Keyword.TAUNT,copy.keywords)
        self.assertTrue(g.state.card_summon_history);self.portable(g)

    def test_molten_reflection_full_board_keeps_existing_summon_capacity_handling(self):
        g = self.game((MIRROR,),board=(UNIT,)*7);target = g.state.players[1].board[0]
        self.paid(g,MIRROR,target);self.assertEqual(len(g.state.players[1].board),7);self.portable(g)

    def test_both_real_boxes_keep_fixed_cast_counts_foreign_spell_pool_and_original_fees(self):
        for player in (1,2):
            g = self.game((PUZZLE,BOX),mode='high',player=player)
            first = self.paid(g,PUZZLE,player=player);second = self.paid(g,BOX,player=player)
            self.assertEqual((len(self.children(g,first)),len(self.children(g,second))),(10,5))
            self.assertTrue(all(c.card_id == EXPENSIVE for c in (*self.children(g,first),*self.children(g,second))))
            self.assertEqual((g.state.players[player].mana,self.hero(g,player).armor),(3,30))
        self.portable(g)

    def test_box_with_minion_deck_uses_low_cost_spells_but_no_minions_requires_at_least_five(self):
        g = self.game((BOX,),deck=(UNIT,),mode='low');source = self.paid(g,BOX)
        self.assertEqual([c.card_id for c in self.children(g,source)],[CHEAP]*5);self.assertEqual(self.hero(g,1).armor,5);self.portable(g)
        g = self.game((BOX,),mode='low');rng = g._rng.getstate();source = self.paid(g,BOX)
        self.assertFalse(self.children(g,source));self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_box_initial_high_cost_query_stays_frozen_after_first_spell_adds_a_minion_to_deck(self):
        g = self.game((BOX,),board=(ALTER_DECK,));source = self.paid(g,BOX)
        self.assertEqual([c.card_id for c in self.children(g,source)],[EXPENSIVE]*5)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[UNIT]);self.portable(g)

    def test_box_unknown_eligible_spell_fails_atomically_but_known_filter_can_exclude_it(self):
        g = self.game((BOX,),deck=(UNIT,),mode='unknown');before = g.snapshot()
        with self.assertRaises((ResolutionError,ValueError)):self.play(g,BOX)
        self.assertEqual(g.snapshot(),before)
        g = self.game((BOX,),mode='unknown');source = self.paid(g,BOX)
        self.assertEqual([c.card_id for c in self.children(g,source)],[EXPENSIVE]*5);self.portable(g)

    def test_box_first_automatic_cast_reaction_wait_restores_one_original_batch_and_failed_choice(self):
        g = self.game((PUZZLE,),board=(CAST_WAIT,),mode='high');source = self.paid(g,PUZZLE)
        self.assertEqual(len(self.children(g,source)),1);other = self.portable(g);before = other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),before);self.choose(other)
        self.assertEqual(len(self.children(other,source)),10);self.portable(other)

    def test_waiting_private_candidates_and_rng_do_not_enter_either_player_projection(self):
        g = self.game((PUZZLE,),board=(CAST_WAIT,),mode='high');self.paid(g,PUZZLE);self.portable(g)
        for p in (1,2):
            view = json.dumps(g.for_player(p).observe())
            for key in ('rng_state','resolution_frame','candidate_ids','source_epoch','initial_cast_ids'):
                self.assertNotIn('"'+key+'"',view)

    def test_last_bad_metadata_does_not_partially_register_any_card_rule_or_behavior(self):
        r = build_registry();data = deepcopy(native.load_batch());data['dependencies'][-1]['record']['type'] = 'MINION'
        before = r.fingerprint()
        with patch.object(native,'load_batch',return_value=data),self.assertRaises(TargetValidationError):native.register_past_mage_primitive_spells(r)
        self.assertEqual(r.fingerprint(),before)
