"""Armor consumers use player identities across seats and hero replacement."""
from dataclasses import replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, DeckSpec,
    Game, PlayCard, PlayerSetup, ResolutionError, Scenario, TriggerSpec)
from hs_sim.engine.effects import AddToHand, Draw, GainArmor, ReplaceHero
from hs_sim.engine.replay import build_replay, replay
from hs_sim.local_pool_format import build_cn37_local_pool_format

P='armor.recipient.test.';SMALL=P+'small';LARGE=P+'large';SWAP=P+'swap';DRAW=P+'draw';WATCH=P+'watch'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
ROOT=Path(__file__).resolve().parents[1]


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=build_registry()
    r.register_behavior(P+'cry',lambda c:(GainArmor(c.player_id,40),))
    r.register_card(CardDefinition(SMALL,SMALL,CardType.MINION,cost=2,attack=1,health=4,battlecry=P+'cry',metadata=META))
    r.register_card(CardDefinition(LARGE,LARGE,CardType.MINION,cost=5,attack=1,health=6,metadata=META))
    r.register_behavior(SWAP,lambda c:(ReplaceHero(c.player_id,'HERO_01'),))
    r.register_behavior(DRAW,lambda c:(Draw(c.player_id,1,c.source_id),))
    for cid in (SWAP,DRAW):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META))
    def watch(c):
        if mode=='fault'and c.event.player_id==c.player_id and c.state.entities[c.event.target_id].card_id==SMALL:
            return(AddToHand(c.player_id,'missing.after.recruit.armor'),)
        return()
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=5,metadata=META,
        triggers=(TriggerSpec('minion_summoned',WATCH),)))
    return r


class RecruitArmorRecipientTests(unittest.TestCase):
    def game(self,card,player=2,*,deck=(SMALL,LARGE),board=(),mode='normal'):
        own=PlayerSetup('HERO_08',hand=(SWAP,card),board=board,deck=deck,mana=10,max_mana=10)
        other=PlayerSetup('HERO_08',deck=(LARGE,)*9,mana=10,max_mana=10)
        self.mode=mode
        g=Game.from_scenario(Scenario((own,other)if player==1 else(other,own),active_player=player,seed=83),
            registry(mode),mode='debug')
        self.play(g,SWAP,player)
        self.assertNotIn(g.state.players[player].hero_id,(1,2))
        return g

    def play(self,g,cid,player=2,target=None):
        source=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(player,source,target));return source

    def armor(self,g,player):return g.state.entities[g.state.players[player].hero_id].armor

    def portable(self,g):
        saved=g.snapshot();r=registry(self.mode,'independent-reader')
        self.assertEqual(Game.from_snapshot(saved,r).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),r).snapshot(),saved)

    def test_oak_both_seats_after_replacement_gains_armor_and_recruits_original(self):
        for player in (1,2):
            with self.subTest(player=player):
                g=self.game('CORE_LOOT_309',player);original=g.state.players[player].deck[0]
                self.play(g,'CORE_LOOT_309',player)
                self.assertEqual(self.armor(g,player),6);self.assertEqual(self.armor(g,3-player),0)
                self.assertEqual(g.state.players[player].board,[original])
                self.assertEqual(g.state.play_history[-1].cost,4)
        self.portable(g)

    def test_equipment_both_seats_gains_own_armor_and_shuffles_five_tokens(self):
        for player in (1,2):
            with self.subTest(player=player):
                g=self.game('JAIL_386',player)
                self.play(g,'JAIL_386',player)
                self.assertEqual(self.armor(g,player),2);self.assertEqual(self.armor(g,3-player),0)
                tokens=[i for i in g.state.players[player].deck if g.state.entities[i].card_id=='JAIL_386t']
                self.assertEqual(len(tokens),5)
                self.assertTrue(all(g.state.entities[i].controller==player for i in tokens))

    def test_draw_cast_token_both_seats_gains_own_armor_and_replaces_draw(self):
        for player in (1,2):
            with self.subTest(player=player):
                g=self.game(DRAW,player,deck=('JAIL_386t',SMALL))
                self.play(g,DRAW,player)
                self.assertEqual(self.armor(g,player),2);self.assertEqual(self.armor(g,3-player),0)
                self.assertEqual([g.state.entities[i].card_id for i in g.state.players[player].hand],[SMALL])
                casts=[c for c in g.state.cast_history if c.card_id=='JAIL_386t']
                self.assertEqual(len(casts),1);self.assertTrue(casts[0].completed)
        self.portable(g)

    def test_whelp_both_seats_damages_target_and_gains_armor(self):
        for player in (1,2):
            with self.subTest(player=player):
                g=self.game('TLC_600',player)
                target=g.state.players[3-player].hero_id
                self.play(g,'TLC_600',player,target)
                self.assertEqual(g.state.entities[target].damage,5)
                self.assertEqual(self.armor(g,player),5);self.assertEqual(self.armor(g,3-player),0)
        self.portable(g)

    def test_oak_empty_or_full_board_still_gains_armor_without_random_draw(self):
        for deck,board in (((),()),((SMALL,), (SMALL,)*7)):
            with self.subTest(empty=not deck):
                g=self.game('CORE_LOOT_309',deck=deck,board=board);rng=g._rng.getstate()
                self.play(g,'CORE_LOOT_309')
                self.assertEqual(self.armor(g,2),6);self.assertEqual(g._rng.getstate(),rng)

    def test_late_recruit_failure_rolls_back_armor_mana_physical_deck_and_rng(self):
        g=self.game('CORE_LOOT_309',board=(WATCH,),mode='fault');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'CORE_LOOT_309')
        self.assertEqual(g.snapshot(),before)

    def test_original_oak_failure_game_reaches_and_accepts_step71(self):
        from web_ui.autoplay_checks import facts
        base=ROOT/'outputs/mixed-deck-audit-20261103';doc=json.loads((base/'decks/discard_choose.json').read_text('utf-8'))
        f=build_cn37_local_pool_format();pool=f.registry.pool('constructed.minions',f.context)
        for name in ('representative.attack-cost-minions','representative.legendary-dragons'):
            f.registry.register_pool(replace(pool,id=name,version='ui-standard-match-full-minions-v1:'+pool.version))
        specs=tuple(DeckSpec(v['hero_card_id'],v['hero_power_card_id'],CardClass(v['card_class']),tuple(v['cards']))for v in doc['decks'].values())
        g=Game.from_decks(f.match_setup(specs,seed=doc['fixed_seed_pairs'][0],first_player=1),f.registry)
        rows=[json.loads(s)for s in(base/'discard_choose/run/private/A-1-steps.jsonl').read_text('utf-8').splitlines()]
        def normalize(v):
            v=json.loads(json.dumps(v))
            for e in v['entities'].values():e['keywords']=sorted(e['keywords'])
            return v
        count=0
        for row in rows:
            self.assertEqual(normalize(facts(g)),normalize(row['before']),f"before step{row['step']}")
            player=row['actor'];port=g.for_player(player);before=self.armor(g,player)
            reply=port.submit({'revision':port.legal_actions()['revision'],'action':row['action']})
            self.assertTrue(reply['accepted'],f"step{row['step']}: {reply.get('error')}")
            if row['step']==71:
                self.assertEqual(count,71);self.assertEqual(player,2)
                self.assertEqual(self.armor(g,player),before+6)
                saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,f.registry).snapshot(),saved)
                return
            self.assertEqual(normalize(facts(g)),normalize(row['after']),f"after step{row['step']}")
            count+=1
        self.fail('Original failed step71 is missing')
