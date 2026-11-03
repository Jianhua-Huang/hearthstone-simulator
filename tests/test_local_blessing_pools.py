"""Native Imbued powers use complete local Standard domains, not demo samples."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.engine import (CardClass,CardDefinition,CardType,Game,PlayerSetup,
    PoolQuery,Scenario,SelectChoice,UseHeroPower)
from hs_sim.engine.costs import local_cost
from hs_sim.engine.pools import resolve_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import BRONZE_POOL_ID,WIND_POOL_ID
from hs_sim.local_pool_format import build_cn37_local_pool_format

THREE='fixture.blessing.three';FORTY_NINE='fixture.blessing.forty-nine'


@lru_cache(maxsize=2)
def local(role):
    assert role in ('writer','reader')
    f=build_cn37_local_pool_format()
    for cid,cost in ((THREE,3),(FORTY_NINE,49)):
        f.registry.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=5))
    return f


class LocalBlessingPoolTests(unittest.TestCase):
    def game(self,hero,power,player=1,body=None):
        f=local('writer');context=replace(f.context,starting_decks=((),()))
        owner=PlayerSetup(hero,hero_power_card_id=power,board=()if body is None else(body,),
            mana=10,max_mana=10)
        enemy=PlayerSetup('HERO_08')
        return Game.from_scenario(Scenario((owner,enemy)if player==1 else(enemy,owner),
            active_player=player,seed=937,generation_context=context),f.registry,mode='release')
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=local('reader').registry
        self.assertIsNot(r,g.registry)
        other=Game.from_snapshot(s,r);self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        for p in (1,2):
            text=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())
            for field in ('rng_state','generation_context','resolution_frame','rewind_session'):
                self.assertNotIn('"'+field+'"',text)
        return other
    def test_both_aliases_preserve_every_standard_minion_weight_and_exclusion(self):
        f=local('writer');ordinary=f.registry.pool('constructed.minions',f.context)
        for pid in (BRONZE_POOL_ID,WIND_POOL_ID):
            pool=f.registry.pool(pid,f.context)
            self.assertEqual((pool.members,pool.excluded_card_ids,pool.complete),
                (ordinary.members,ordinary.excluded_card_ids,ordinary.complete))
            self.assertGreater(len(pool.members),500)
            self.assertEqual((pool.target_id,pool.mode),(f.context.target_id,f.context.mode))
    def test_bronze_native_activation_and_rewind_keep_work_from_either_seat(self):
        for player in (1,2):
            with self.subTest(player=player):
                g=self.game('HERO_03','END_000p',player);s=g.state
                g.apply(UseHeroPower(player,s.players[player].hero_power_id))
                generated=g.state.entities[g.state.players[player].hand[-1]]
                d=g.registry.card(generated.card_id)
                self.assertEqual(d.kind,CardType.MINION)
                self.assertNotIn(CardClass.ROGUE,d.metadata.classes)
                self.assertNotIn(CardClass.NEUTRAL,d.metadata.classes)
                self.assertEqual(local_cost(generated)[0],max(0,d.cost-1))
                waiting=self.portable(g);q=g.state.pending_choice
                g.apply(SelectChoice(player,q.id,('keep',)))
                waiting.apply(SelectChoice(player,q.id,('keep',)))
                self.assertEqual(waiting.snapshot(),g.snapshot())
                self.assertEqual((g.state.players[player].mana,len(g.state.hero_power_history)),(9,1))
                self.portable(g)
    def test_bronze_class_query_has_the_same_complete_candidates_as_ordinary_pool(self):
        f=local('writer');q=PoolQuery(kinds=(CardType.MINION,),collectible=True,
            class_mode='other',include_neutral=False)
        a=resolve_candidates(f.registry,replace(f.context,starting_decks=((),())),BRONZE_POOL_ID,q,
            current_class=CardClass.ROGUE,source_card_id='END_000p',player_id=1)
        b=resolve_candidates(f.registry,replace(f.context,starting_decks=((),())),'constructed.minions',q,
            current_class=CardClass.ROGUE,source_card_id='END_000p',player_id=1)
        self.assertEqual(a,b);self.assertGreater(len(a),200)
    def test_wind_transforms_original_body_at_printed_cost_plus_strength(self):
        for player in (1,2):
            with self.subTest(player=player):
                g=self.game('HERO_02','EDR_448p',player,THREE);s=g.state
                target=s.players[player].board[0];power=s.players[player].hero_power_id
                g.apply(UseHeroPower(player,power,target))
                entity=g.state.entities[target]
                self.assertEqual(g.registry.card(entity.card_id).cost,4)
                self.assertIn(target,g.state.players[player].board)
                self.assertFalse(g.state.cast_history);self.assertFalse(g.state.play_history)
                self.assertEqual(g.state.players[player].mana,8);self.portable(g)
    def test_wind_empty_tier_skips_without_rng_or_cheaper_substitution(self):
        g=self.game('HERO_02','EDR_448p',body=FORTY_NINE);s=g.state
        rng=g.snapshot()['rng_state'];target=s.players[1].board[0]
        g.apply(UseHeroPower(1,s.players[1].hero_power_id,target))
        self.assertEqual(g.state.entities[target].card_id,FORTY_NINE)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)
