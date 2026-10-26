"""Connect the real Lokholar to the full host; reuse existing threshold tests."""
from dataclasses import replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture as base_fixture, P, FILLER
from hs_sim.cards.native_lokholar import CARD, PROFILE, load_batch
from hs_sim.cards.past_summon_prices import PAST_TEN
from hs_sim.engine import (Attack, Game, IllegalAction, Keyword, PlayerSetup, Scenario)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.model import HeroMissingHealthCostSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember, resolve_candidates
from tools import card_batch as batch

CTX=GenerationContext('k558-native-lokholar-test','experimental')


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    fmt=base_fixture.__wrapped__('normal',role);r=fmt.registry
    for name in ('constructed.cards','constructed.minions'):
        r.register_pool(replace(r.pool(name,fmt.context),target_id=CTX.target_id,mode=CTX.mode))
    r.register_pool(PoolDefinition('constructed.past.cards','one-native-lokholar-test-v1',CTX.target_id,CTX.mode,
        (PoolMember(CARD),),complete=True))
    r.validate();return replace(fmt,context=CTX)


class NativeLokholarTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role).registry)

    def game(self,hand,enemy=()):
        fmt=fixture()
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06',hand=hand,deck=(FILLER,)*6,max_mana=10,mana=10),
            PlayerSetup('HERO_08',board=enemy,deck=(FILLER,)*6)),seed=558,generation_context=CTX),fmt.registry)

    def test_complete_native_row_two_primary_faces_and_exact_existing_profile(self):
        data=load_batch();raw=data['cards'][0]['record']
        self.assertEqual(batch.sha(data['source']),data['source_sha256'])
        self.assertEqual(raw,next(r for r in batch.read(data['source'])if r['id']==CARD))
        for face in data['official_faces']:batch.check_face(raw,face['face'],face['locale'])
        card=fixture().registry.card(CARD)
        self.assertEqual((card.cost,card.attack,card.health),(10,8,8))
        self.assertEqual(card.hero_missing_health_cost,HeroMissingHealthCostSpec(PROFILE))
        self.assertEqual(card.keywords,(Keyword.RUSH,Keyword.WINDFURY));self.assertIsNone(card.battlecry)
        self.assertEqual(fixture().registry.pool_cards[CARD].card_id,CARD)
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_full_native_host_pays_five_at_fifteen_and_really_uses_rush_windfury(self):
        g=self.game((CARD,)+(P+'hurt_hero',)*3,enemy=(P+'unit',)*2)
        for _ in range(3):self.play(g,P+'hurt_hero')
        held=self.entity(g,CARD);self.assertEqual(quote_unselected_cost(g.state,g.registry,held).amount,5)
        source=self.play(g,CARD);self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(5,5))
        with self.assertRaises(IllegalAction):g.apply(Attack(1,source,g.state.players[2].hero_id))
        for target in tuple(g.state.players[2].board):g.apply(Attack(1,source,target))
        self.assertEqual((g.state.entities[source].health,g.state.entities[source].attacks_this_turn),(6,2))
        self.assertFalse(g.state.players[2].board);self.portable(g)

    def test_real_frontier_discovery_set_to_one_follows_intrinsic_at_high_and_low_health(self):
        r=fixture().registry;rows=resolve_candidates(r,CTX,'constructed.past.cards',PAST_TEN,
            current_class=r.card('CFM_308').metadata.classes[0],source_card_id='GDB_857',player_id=1)
        self.assertEqual([(x.card_id,x.weight)for x in rows],[(CARD,1)])
        for low in (False,True):
            with self.subTest(low=low):
                g=self.game(('GDB_857',)+(P+'hurt_hero',)*3 if low else ('GDB_857',))
                if low:
                    for _ in range(3):self.play(g,P+'hurt_hero')
                self.play(g,'GDB_857');self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id==CARD))
                held=self.entity(g,CARD);self.assertEqual(quote_unselected_cost(g.state,g.registry,held).amount,1)
                source=self.play(g,CARD);self.assertEqual((g.state.entities[source].card_id,g.state.play_history[-1].cost),(CARD,1))
        self.portable(g)


if __name__=='__main__':unittest.main()
