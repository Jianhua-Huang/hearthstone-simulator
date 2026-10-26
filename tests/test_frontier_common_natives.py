"""Known Frontier dependencies, their ordinary payments and actual generated entry."""
from dataclasses import replace
from functools import lru_cache
from random import Random
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture as base_fixture, P, FILLER
from hs_sim.cards.frontier_common_natives import ROOTS, TOKENS, CHOICES, KUN_BOTH, ALIASES, load_batch
from hs_sim.cards.past_summon_prices import PAST_TEN
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, ResolutionError, Scenario, TriggerSpec, UseHeroPower)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import AddToHand, ChoiceOption, Damage, DamageBatch, InvokeBehavior, RequestChoice
from hs_sim.engine.pools import (GenerationContext, PoolDefinition, PoolMember, resolve_candidates, sample_candidates)
from tools import card_batch as batch

S='k554.'
WATCH=S+'watch'
DRAGON='CORE_LOOT_137'
CTX=GenerationContext('k554-thirteen-native-frontier-test','experimental')


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    fmt=base_fixture.__wrapped__('normal',role);r=fmt.registry
    for name in ('constructed.cards','constructed.minions'):
        r.register_pool(replace(r.pool(name,fmt.context),target_id=CTX.target_id,mode=CTX.mode))
    r.register_pool(PoolDefinition('constructed.past.cards','thirteen-native-frontier-test-v1',
        CTX.target_id,CTX.mode,tuple(PoolMember(cid)for cid in ROOTS),complete=True))
    def fail(c):raise ResolutionError('k554 intentional late failure')
    def wait(c):
        return RequestChoice(c.player_id,(
            ChoiceOption('continue','Continue',()),
            ChoiceOption('fault','Fail',(InvokeBehavior(S+'fail',c.source_id,c.player_id),))),c.source_id)
    def observe(c):
        source=c.state.entities.get(c.event.source_id)
        if (mode=='deck_wait' and c.event.kind=='card_destroyed_in_deck' and
                source is not None and source.card_id=='CORE_MAW_034'):
            return (wait(c),)
        roots=c.state.card_summon_history
        if (mode=='dragon_wait' and c.event.kind=='minion_summoned' and roots and
                roots[-1].request.cause.source.card_id=='OG_317' and
                c.state.entities[c.event.target_id].card_id==DRAGON):
            return (AddToHand(c.player_id,DRAGON,c.source_id),wait(c))
        return ()
    def blast(c):
        return (DamageBatch(tuple(Damage(i,3,c.source_id)for p in c.state.players.values()for i in p.board)),)
    for name,body in (('fail',fail),('blast',blast)):
        r.register_behavior(S+name,body)
        r.register_card(CardDefinition(S+name,name,CardType.SPELL,on_play=S+name))
    r.register_behavior(S+'observe',observe)
    r.register_card(CardDefinition(WATCH,'Native effect observer',CardType.MINION,health=30,
        triggers=tuple(TriggerSpec(event,S+'observe')for event in ('card_destroyed_in_deck','minion_summoned'))))
    r.validate();return replace(fmt,context=CTX)


class FrontierCommonNativeTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role).registry)

    def game(self,hand,*,board=(),deck=(),enemy=(),enemy_hand=(),mode='normal',seed=1,power=None):
        self.mode=mode;fmt=fixture(mode)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06',hand=hand,board=board,deck=deck,max_mana=10,mana=10,hero_power_card_id=power),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,max_mana=10,mana=10)),
            seed=seed,generation_context=CTX),fmt.registry)

    def price(self,game,cid):return quote_unselected_cost(game.state,game.registry,self.entity(game,cid)).amount

    def branch(self,game,key):
        entity=self.entity(game,'CFM_308').id
        game.apply(PlayCard(1,entity,branch_id=key));return entity

    def pick(self,game,cid):
        self.choose(game,next(o.id for o in game.state.pending_choice.options if o.card_id==cid))

    def test_full_twenty_original_rows_thirty_primary_faces_and_real_core_associations(self):
        data=load_batch();source={r['id']:r for r in batch.read(data['source'])}
        self.assertEqual(batch.sha(data['source']),data['source_sha256'])
        rows={x['record']['id']:x['record']for key in ('cards','dependencies','choices','evidence_only')for x in data[key]}
        self.assertEqual(len(rows),20)
        for cid,raw in rows.items():self.assertEqual(raw,source[cid])
        for observation in data['official_faces']:
            batch.check_face(rows[observation['card_id']],observation['face'],observation['locale'])
        r=fixture().registry
        for core,original in ALIASES.items():self.assertEqual(r.card(core).metadata.deck_identity,original)
        for cid in ROOTS+TOKENS:
            raw=rows[cid];card=r.card(cid)
            self.assertEqual((card.cost,card.attack,card.health),(raw['cost'],raw['attack'],raw['health']))
        self.assertTrue(all(r.card(cid).choice_only and cid not in r.pool_cards for cid in CHOICES))
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_frost_giant_counts_two_actual_personal_power_uses_and_pays_reduced_eight(self):
        game=self.game(('AT_120',),power='HERO_06bp');self.assertEqual(self.price(game,'AT_120'),10)
        game.apply(UseHeroPower(1,game.state.players[1].hero_power_id))
        self.assertEqual(self.price(game,'AT_120'),9)
        game.apply(EndTurn(1));game.apply(EndTurn(2))
        game.apply(UseHeroPower(1,game.state.players[1].hero_power_id))
        self.assertEqual(self.price(game,'AT_120'),8)
        self.play(game,'AT_120');self.assertEqual(game.state.players[1].mana,0)
        self.assertEqual(game.state.play_history[-1].cost,8);self.portable(game)

    def test_sea_giant_counts_both_boards_before_its_own_entry(self):
        game=self.game(('CORE_EX1_586',),board=(FILLER,FILLER),enemy=(FILLER,)*3)
        self.assertEqual(self.price(game,'CORE_EX1_586'),5);self.play(game,'CORE_EX1_586')
        self.assertEqual(game.state.players[1].mana,5)
        self.assertEqual(game.state.play_history[-1].cost,5)

    def test_gnoll_counts_other_hand_cards_and_keeps_real_rush(self):
        game=self.game(('SW_062',P+'noop',FILLER));self.assertEqual(self.price(game,'SW_062'),8)
        self.play(game,P+'noop');self.assertEqual(self.price(game,'SW_062'),9)
        body=self.play(game,'SW_062');self.assertEqual(game.state.players[1].mana,1)
        self.assertIn(Keyword.RUSH,game.state.entities[body].keywords)

    def test_moon_colossus_shield_and_reborn_use_native_fresh_body_and_end_after_second_death(self):
        game=self.game(('ULD_721',P+'hurt',P+'kill',P+'kill'))
        original=self.play(game,'ULD_721');self.play(game,P+'hurt',original)
        self.assertEqual(game.state.entities[original].health,10)
        self.assertNotIn(Keyword.DIVINE_SHIELD,game.state.entities[original].keywords)
        self.play(game,P+'kill',original);body=self.entity(game,'ULD_721',zone='board')
        self.assertNotEqual(body.id,original);self.assertEqual((body.attack,body.health),(10,1))
        self.assertIn(Keyword.DIVINE_SHIELD,body.keywords)
        self.play(game,P+'kill',body.id);self.assertFalse(game.state.players[1].board);self.portable(game)

    def test_tyrantus_is_elusive_but_ordinary_untargeted_damage_still_applies(self):
        game=self.game(('UNG_852',S+'blast'),enemy_hand=('CORE_CS2_029',))
        body=self.play(game,'UNG_852');self.assertIn(Keyword.TAUNT,game.state.entities[body].keywords)
        self.play(game,S+'blast');self.assertEqual(game.state.entities[body].health,11)
        game.apply(EndTurn(1));saved=game.snapshot()
        with self.assertRaises(IllegalAction):self.play(game,'CORE_CS2_029',body,player=2)
        self.assertEqual(game.snapshot(),saved)

    def test_named_colossus_and_gravewing_deaths_summon_exact_real_tokens_at_original_slot(self):
        for cid,token,stats,keyword in (('BT_155','BT_155t',(7,7),Keyword.TAUNT),
                ('CORE_REV_375','REV_375t',(8,8),Keyword.RUSH)):
            with self.subTest(card=cid):
                game=self.game((P+'kill',),board=(FILLER,cid,FILLER))
                source=self.entity(game,cid,zone='board').id
                self.play(game,P+'kill',source);body=self.entity(game,token,zone='board')
                self.assertEqual((body.attack,body.health),stats);self.assertIn(keyword,body.keywords)
                self.assertEqual(game.state.players[1].board.index(body.id),1)
                self.assertEqual(game.state.card_summon_history[-1].request.cause.source.entity_id,source)
        self.portable(game)

    def test_elekk_native_death_damages_all_enemies_by_three_without_spell_damage_bonus(self):
        game=self.game(('ETC_086',P+'kill'),board=('CORE_EX1_012',),enemy=('CORE_REV_990',FILLER,FILLER))
        location=self.entity(game,'CORE_REV_990',player=2,zone='board');durability=location.durability
        source=self.play(game,'ETC_086');self.play(game,P+'kill',source)
        self.assertEqual([game.state.entities[i].health for i in game.state.players[2].board
            if game.state.entities[i].kind==CardType.MINION],[2,2])
        self.assertEqual(game.state.entities[location.id].durability,durability)
        self.assertEqual(self.entity(game,'CORE_EX1_012',zone='board').health,1)

    def test_kun_branches_and_real_fandral_combined_refresh_actual_owned_crystals(self):
        for key,board,mana,armor in (('CFM_308a',(),0,10),('CFM_308b',(),10,0),
                (KUN_BOTH,('CORE_OG_044',),10,10)):
            with self.subTest(branch=key):
                game=self.game(('CFM_308',),board=board);self.branch(game,key)
                self.assertEqual(game.state.players[1].mana,mana)
                self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor,armor)
                self.assertEqual(len(game.state.play_history),1)
        self.portable(game)

    def test_jailer_destroys_original_deck_and_grants_only_its_own_removable_immunity(self):
        game=self.game(('CORE_MAW_034',S+'blast',P+'quiet',S+'blast'),board=(FILLER,),deck=('SW_062','AT_120'))
        original=set(game.state.players[1].deck);source=self.play(game,'CORE_MAW_034')
        self.assertFalse(game.state.players[1].deck)
        events=[e for e in game.events if e.kind=='card_destroyed_in_deck']
        self.assertEqual({e.target_id for e in events},original)
        self.assertTrue(all(dict(e.data)['reveal']is False for e in events))
        body=game.state.entities[source];health=body.health
        self.assertIn(Keyword.IMMUNE,body.keywords);self.assertNotIn(Keyword.IMMUNE,self.entity(game,FILLER,zone='board').keywords)
        self.assertNotIn('SW_062',json.dumps(game.for_player(2).observe()))
        self.play(game,S+'blast');self.assertEqual(game.state.entities[source].health,health)
        self.play(game,P+'quiet',source);self.assertNotIn(Keyword.IMMUNE,game.state.entities[source].keywords)
        self.play(game,S+'blast');self.assertEqual(game.state.entities[source].health,health-3);self.portable(game)

    def test_jailer_wait_sees_entire_deck_removed_before_immunity_and_restores_original_tail(self):
        game=self.game(('CORE_MAW_034',),board=(WATCH,),deck=('SW_062','AT_120'),mode='deck_wait')
        source=self.play(game,'CORE_MAW_034');self.assertFalse(game.state.players[1].deck)
        self.assertNotIn(Keyword.IMMUNE,game.state.entities[source].keywords)
        restored=self.portable(game);saved=restored.snapshot()
        with self.assertRaises(ResolutionError):self.choose(restored,'fault')
        self.assertEqual(restored.snapshot(),saved)
        for current in (game,restored):
            while current.state.pending_choice is not None:self.choose(current)
        self.assertEqual(restored.snapshot(),game.snapshot())
        self.assertIn(Keyword.IMMUNE,game.state.entities[source].keywords);self.portable(game)

    def test_dragonlord_recruits_original_current_dragons_and_leaves_non_dragons_in_hand(self):
        game=self.game(('OG_317',P+'kill',DRAGON,'DEEP_006',FILLER))
        original={game.state.entities[i].card_id:i for i in game.state.players[1].hand}
        source=self.play(game,'OG_317');self.play(game,P+'kill',source)
        self.assertEqual(game.state.players[1].board,[original[DRAGON],original['DEEP_006']])
        self.assertEqual(game.state.players[1].hand,[original[FILLER]])
        self.assertTrue(all(x.request.cause.source.entity_id==source for x in game.state.card_summon_history))
        self.assertFalse(game.state.draw_history);self.portable(game)

    def test_dragonlord_original_hand_group_wait_does_not_add_newly_acquired_dragon(self):
        game=self.game(('OG_317',P+'kill',DRAGON,'DEEP_006'),board=(WATCH,),mode='dragon_wait')
        source=self.play(game,'OG_317');self.play(game,P+'kill',source)
        self.assertEqual(len(game.state.players[1].hand),2)
        restored=self.portable(game);saved=restored.snapshot()
        with self.assertRaises(ResolutionError):self.choose(restored,'fault')
        self.assertEqual(restored.snapshot(),saved)
        self.choose(restored);self.choose(game);self.assertEqual(restored.snapshot(),game.snapshot())
        self.assertEqual([game.state.entities[i].card_id for i in game.state.players[1].hand],[DRAGON])
        self.assertEqual([game.state.entities[i].card_id for i in game.state.players[1].board],[WATCH,DRAGON,'DEEP_006'])
        self.portable(game)

    def test_all_thirteen_are_really_discovered_by_frontier_and_played_with_one_cost(self):
        r=fixture().registry
        rows=resolve_candidates(r,CTX,'constructed.past.cards',PAST_TEN,
            current_class=r.card('CFM_308').metadata.classes[0],source_card_id='GDB_857',player_id=1)
        self.assertEqual({x.card_id for x in rows},set(ROOTS))
        for cid in ROOTS:
            with self.subTest(card=cid):
                seed=next(n for n in range(100)if cid in sample_candidates(Random(n),rows,3,replacement=False))
                game=self.game(('GDB_857',),seed=seed);self.play(game,'GDB_857');self.pick(game,cid)
                self.assertEqual(self.price(game,cid),1)
                source=self.branch(game,'CFM_308a')if cid=='CFM_308'else self.play(game,cid)
                self.assertEqual(game.state.players[1].mana,2)
                self.assertEqual(game.state.entities[source].card_id,cid)
                self.assertEqual(game.state.play_history[-1].cost,1)
        self.portable(game)


if __name__=='__main__':unittest.main()
