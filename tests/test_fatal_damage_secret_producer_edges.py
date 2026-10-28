"""Ice Block must also handle actual fatigue and ordinary end-turn damage."""
from functools import lru_cache
import unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards.damage_fragility_ice_block import BLOCK,register_damage_fragility_ice_block
from hs_sim.engine import EndTurn,Game,PlayerSetup,Scenario
from hs_sim.engine.effects import Damage,Draw
from hs_sim.engine.health_loss import SetHeroHealth
from hs_sim.engine.model import CardDefinition,CardType,Keyword,TriggerSpec

P='k633.producer.';LOW=P+'low';MILL=P+'mill';END=P+'end';FILL='card.1'


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();register_damage_fragility_ice_block(r)
    r.register_behavior(LOW,lambda c:(SetHeroHealth(c.state.players[c.player_id].hero_id,5,c.source_id),))
    r.register_behavior(MILL,lambda c:(Draw(3-c.player_id,6,c.source_id),))
    r.register_behavior(END,lambda c:(Damage(c.state.players[3-c.player_id].hero_id,99,c.source_id),)
        if c.event.player_id==c.player_id else ())
    for cid in (LOW,MILL):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata(tribes=())))
    r.register_card(CardDefinition(END,END,CardType.MINION,health=10,triggers=(TriggerSpec('turn_ended',END),),metadata=metadata(tribes=())))
    r.validate();r.freeze();return r


class FatalDamageProducerTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,*,fatigue=False):
        g=Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=(LOW,BLOCK),deck=() if fatigue else (FILL,)*3,mana=20,max_mana=20,mana_cap=20),
            PlayerSetup('warrior.hero',hand=(MILL,) if fatigue else (),board=() if fatigue else (END,),deck=(FILL,)*3,mana=20,max_mana=20,mana_cap=20))),registry())
        self.play(g,LOW);self.play(g,BLOCK);g.apply(EndTurn(1));return g
    def test_actual_enemy_forced_draw_fatigue_prevents_first_fatal_and_later_damage(self):
        g=self.game(fatigue=True);self.play(g,MILL,player=2)
        hero=g.state.entities[g.state.players[1].hero_id]
        self.assertEqual(hero.health,2);self.assertFalse(g.state.players[1].secrets);self.assertIn(Keyword.IMMUNE,hero.keywords)
        self.portable(g)
    def test_actual_opponent_end_turn_lethal_does_not_leak_immunity_into_next_turn(self):
        g=self.game();g.apply(EndTurn(2));hero=g.state.entities[g.state.players[1].hero_id]
        self.assertEqual(hero.health,5);self.assertFalse(g.state.players[1].secrets);self.assertNotIn(Keyword.IMMUNE,hero.keywords)
        self.assertEqual(g.state.active_player,1);self.portable(g)


if __name__=='__main__':unittest.main()
