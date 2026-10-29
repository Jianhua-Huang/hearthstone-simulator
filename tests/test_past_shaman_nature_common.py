"""Actual entries for thirteen shared Shaman effects; no partial source pool."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from test_past_hunter_nature_leaves import fixture as leaf_fixture,CTX,A,B,DORMANT,POWER,SHIELD
from hs_sim.cards import past_shaman_nature_common as native
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import Buff,ChoiceOption,Damage,InvokeBehavior,RandomDamage,RequestChoice,Silence,Summon
from hs_sim.engine.model import CardDefinition,CardType,Keyword,TargetSpec,TriggerSpec,Zone
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError,canonical_digest
from opening_fixtures import metadata

P='k670.'
TOTEM,ALL,HURT,HURTHERO,HUSH,WATCH,FAIL,SPAWN,TOKEN=(P+x for x in('totem','all','hurt','hurt-hero','hush','watch','fail','spawn','token'))
WIND,HEAL,ROCK,WRATH,SHOCK,STORM,CRACK,WAVE,SURGE,QUAKE,LIGHT,STRIKE,TOTEMS=native.ROOTS


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=leaf_fixture('k670-'+role);native.register_past_shaman_nature_common(r)
    for cid,tribes,hp in((TOTEM,('totem',),8),(ALL,('all',),8),(TOKEN,(),8)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=1,health=hp,metadata=metadata(tribes=tribes)))
    r.register_behavior(SPAWN,lambda c:(Summon(c.player_id,TOKEN),))
    r.register_card(CardDefinition(SPAWN,SPAWN,CardType.MINION,attack=1,health=1,deathrattle=SPAWN,metadata=metadata(tribes=())))
    for cid,body in((HURT,lambda c:(Damage(c.target_id,2,c.source_id),)),(HUSH,lambda c:(Silence(c.target_id),))):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),metadata=metadata(collectible=False)))
    r.register_behavior(HURTHERO,lambda c:(Damage(c.state.players[c.player_id].hero_id,20,c.source_id),))
    r.register_card(CardDefinition(HURTHERO,HURTHERO,CardType.SPELL,on_play=HURTHERO,metadata=metadata(collectible=False)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K670 deliberate rollback')))
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=QUAKE:return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,triggers=(TriggerSpec('damage_dealt',WATCH),),metadata=metadata(collectible=False)))
    r.validate();return r


class ShamanNatureCommonTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(),watch=False):
        self.mode='small';board=board+((WATCH,)if watch else())
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=('card.1',)*16,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',board=enemy,deck=('card.2',)*16,mana=10,max_mana=10)),seed=670,generation_context=CTX),fixture())

    def hero(self,g,player=1):return g.state.entities[g.state.players[player].hero_id]

    def ids(self,g,player=1):return[g.state.entities[eid].card_id for eid in g.state.players[player].board]

    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))

    def finish(self,g):
        count=0
        while g.state.pending_choice is not None:
            self.choose(g);count+=1;self.assertLess(count,12)

    def test_complete_thirteen_original_faces_and_zero_cost_primary_normalizations(self):
        d=native.load_batch();r=fixture()
        self.assertEqual(len(d['cards']),13);self.assertEqual(len(d['official_observations']),28)
        self.assertEqual(len(d['original_shaman_member_ids']),71);self.assertFalse(d['complete_shaman_source_bound'])
        for row in d['cards']:
            cid=row['record']['id'];self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(r.pool_card(cid))),row['pool_card_sha256'])
        self.assertEqual((r.card(HEAL).cost,r.card(TOTEMS).cost),(0,0))
        with patch.object(native,'BATCH_HASH',''):
            with self.assertRaises(TargetValidationError):native.load_batch()

    def test_each_original_spell_has_an_actual_paid_hand_entry(self):
        for cid in native.ROOTS:
            with self.subTest(card=cid):
                g=self.game((cid,),board=(A,TOTEM),enemy=(B,));card=g.registry.card(cid)
                target=self.hero(g).id if cid==ROCK else self.entity(g,A,zone='board').id if cid in(WIND,HEAL)else self.entity(g,B,2,'board').id if cid in native.TARGETED else None
                self.play(g,cid,target);self.assertEqual(g.state.players[1].mana,10-card.cost)
                self.assertEqual([row.card_id for row in g.state.cast_history],[cid])
                self.assertEqual(sum(row.amount for row in g.state.overload_history),native.OVERLOAD.get(cid,0))

    def test_windfury_grant_uses_normal_two_attacks_and_no_third_attack(self):
        g=self.game((WIND,),board=(A,),enemy=(B,));own=self.entity(g,A,zone='board').id;enemy=self.entity(g,B,2,'board').id
        self.play(g,WIND,own);self.cycle(g)
        g.apply(Attack(1,own,enemy));g.apply(Attack(1,own,enemy));saved=deepcopy(g.snapshot())
        with self.assertRaises(IllegalAction):g.apply(Attack(1,own,enemy))
        self.assertEqual(g.snapshot(),saved);self.assertEqual(g.state.entities[enemy].health,26);self.portable(g)

    def test_ancestral_healing_restores_full_original_minion_and_grants_taunt_for_zero(self):
        g=self.game((HURT,HEAL),board=(A,));target=self.entity(g,A,zone='board').id
        self.play(g,HURT,target);self.assertEqual(g.state.entities[target].health,6);self.play(g,HEAL,target)
        self.assertEqual(g.state.entities[target].health,8);self.assertIn(Keyword.TAUNT,g.state.entities[target].keywords)
        self.assertEqual(g.state.players[1].mana,10);self.portable(g)

    def test_rockbiter_friendly_hero_and_minion_gain_attack_only_until_current_end(self):
        for hero in(False,True):
            with self.subTest(hero=hero):
                g=self.game((ROCK,),board=(A,));target=self.hero(g).id if hero else self.entity(g,A,zone='board').id
                old=g.state.entities[target].attack;self.play(g,ROCK,target);self.assertEqual(g.state.entities[target].attack,old+3)
                g.apply(EndTurn(1));self.assertEqual(g.state.entities[target].attack,old)

    def test_wrong_hero_and_enemy_targets_fail_before_payment_or_side_effects(self):
        for cid in(WIND,HEAL,SHOCK,CRACK,SURGE,STRIKE,ROCK):
            with self.subTest(card=cid):
                g=self.game((cid,),enemy=(B,));saved=deepcopy(g.snapshot())
                target=self.entity(g,B,2,'board').id if cid==ROCK else self.hero(g).id
                with self.assertRaises(IllegalAction):self.play(g,cid,target)
                self.assertEqual(g.snapshot(),saved)

    def test_three_real_overload_cards_lock_three_next_turn_crystals(self):
        g=self.game((WRATH,STORM,CRACK),board=(A,),enemy=(B,))
        self.play(g,WRATH);self.play(g,STORM);self.play(g,CRACK,self.entity(g,B,2,'board').id)
        self.assertEqual([row.amount for row in g.state.overload_history],[1,1,1]);self.assertEqual(g.state.players[1].mana,4)
        self.cycle(g);self.assertEqual(g.state.players[1].mana,7);self.portable(g)

    def test_storm_wrath_buff_excludes_dormant_and_enemy_group(self):
        g=self.game((WRATH,),board=(A,DORMANT),enemy=(B,));self.play(g,WRATH)
        self.assertEqual((self.entity(g,A,zone='board').attack,self.entity(g,A,zone='board').health),(3,9))
        self.assertEqual((self.entity(g,DORMANT,zone='board').attack,self.entity(g,DORMANT,zone='board').health),(2,8))
        self.assertEqual((self.entity(g,B,2,'board').attack,self.entity(g,B,2,'board').health),(2,30))

    def test_earth_shock_silences_shield_before_original_captured_damage(self):
        g=self.game((SHOCK,),enemy=(SHIELD,));target=self.entity(g,SHIELD,2,'board').id;self.play(g,SHOCK,target)
        self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[target].keywords);self.assertEqual(g.state.entities[target].health,3)
        self.assertTrue(g.state.entities[target].silenced)

    def test_lightning_storm_only_damages_active_enemies_and_applies_spell_bonus_once(self):
        g=self.game((STORM,),board=(POWER,A),enemy=(B,DORMANT));self.play(g,STORM)
        self.assertEqual(self.entity(g,B,2,'board').health,25);self.assertEqual(self.entity(g,A,zone='board').health,8)
        self.assertEqual(self.entity(g,DORMANT,2,'board').health,8)

    def test_tidal_surge_printed_lifesteal_uses_actual_spell_damage_to_heal(self):
        g=self.game((HURTHERO,SURGE),board=(POWER,),enemy=(B,));self.play(g,HURTHERO)
        self.play(g,SURGE,self.entity(g,B,2,'board').id)
        self.assertEqual((self.entity(g,B,2,'board').health,self.hero(g).health),(23,17));self.portable(g)

    def test_tidal_wave_hits_both_minion_sides_and_heals_from_ordinary_damage(self):
        g=self.game((HURTHERO,WAVE),board=(A,),enemy=(B,DORMANT));self.play(g,HURTHERO);self.play(g,WAVE)
        self.assertEqual((self.entity(g,A,zone='board').health,self.entity(g,B,2,'board').health),(5,27))
        self.assertEqual(self.hero(g).health,16);self.assertEqual(self.hero(g,2).health,30);self.portable(g)

    def test_earthquake_second_fresh_batch_hits_deathrattle_newborn(self):
        g=self.game((QUAKE,),enemy=(SPAWN,));self.play(g,QUAKE)
        self.assertEqual(self.ids(g,2),[TOKEN]);self.assertEqual(self.entity(g,TOKEN,2,'board').health,6)
        self.assertEqual(g.state.players[1].mana,3);self.assertEqual(len(g.state.cast_history),1);self.portable(g)

    def test_earthquake_each_batch_has_one_current_spell_bonus_before_provider_death(self):
        g=self.game((QUAKE,),board=(POWER,),enemy=(B,));self.play(g,QUAKE)
        self.assertEqual(self.ids(g),[]);self.assertEqual(self.entity(g,B,2,'board').health,19)

    def test_earthquake_waiting_recovery_and_failed_choice_do_not_repeat_payment(self):
        g=self.game((QUAKE,),enemy=(SPAWN,),watch=True);self.play(g,QUAKE)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.finish(g)
        self.assertEqual(self.entity(g,TOKEN,2,'board').health,6);self.assertEqual(g.state.players[1].mana,3);self.portable(g)

    def test_bioluminescence_grants_stack_and_silence_removes_only_that_carrier(self):
        g=self.game((LIGHT,LIGHT,STORM,HUSH),board=(A,TOTEM),enemy=(B,));self.play(g,LIGHT);self.play(g,LIGHT)
        self.play(g,HUSH,self.entity(g,A,zone='board').id)
        self.assertEqual(sum(a.spell_damage for a in self.entity(g,A,zone='board').abilities if a.kind=='spell_damage'and not a.consumed),0)
        self.assertEqual(sum(a.spell_damage for a in self.entity(g,TOTEM,zone='board').abilities if a.kind=='spell_damage'and not a.consumed),2)
        self.cycle(g);self.play(g,STORM);self.assertEqual(self.entity(g,B,2,'board').health,25);self.portable(g)

    def test_totemic_surge_matches_current_totem_and_all_tribes_but_not_other_or_enemy(self):
        g=self.game((TOTEMS,),board=(TOTEM,ALL,A,DORMANT),enemy=(TOTEM,));self.play(g,TOTEMS)
        self.assertEqual((self.entity(g,TOTEM,zone='board').attack,self.entity(g,ALL,zone='board').attack),(3,3))
        self.assertEqual(self.entity(g,A,zone='board').attack,2);self.assertEqual(self.entity(g,TOTEM,2,'board').attack,1)
        self.assertEqual(g.state.players[1].mana,10)

    def test_stormstrike_damage_and_hero_attack_share_one_payment_and_expiry(self):
        g=self.game((STRIKE,),enemy=(B,));self.play(g,STRIKE,self.entity(g,B,2,'board').id)
        self.assertEqual(self.entity(g,B,2,'board').health,27);self.assertEqual(self.hero(g).attack,3)
        self.assertEqual(g.state.players[1].mana,7);g.apply(EndTurn(1));self.assertEqual(self.hero(g).attack,0)

    def test_empty_area_or_grant_groups_consume_no_rng(self):
        for cid in(WRATH,STORM,WAVE,QUAKE,LIGHT,TOTEMS):
            with self.subTest(card=cid):
                g=self.game((cid,));rng=g.snapshot()['rng_state'];self.play(g,cid)
                self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_real_standard_host_uses_actual_shaman_spell_payment_overload_and_expiry(self):
        self.mode='host';h=host();deck=('CORE_EX1_169',)*15
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_02',hand=(ROCK,STRIKE,STORM),deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=('LOOT_077t','LOOT_077t'),deck=deck,mana=10,max_mana=10)),seed=670,generation_context=h.context),h.registry)
        self.play(g,ROCK,self.hero(g).id);self.play(g,STRIKE,g.state.players[2].board[0]);self.play(g,STORM)
        self.assertEqual(self.ids(g,2),[]);self.assertEqual((self.hero(g).attack,g.state.players[1].mana),(6,2))
        self.assertEqual([row.amount for row in g.state.overload_history],[1]);self.cycle(g)
        self.assertEqual(self.hero(g).attack,0);self.assertEqual(g.state.players[1].mana,9);self.portable(g)
