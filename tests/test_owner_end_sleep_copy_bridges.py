"""New nonempty attack clocks through existing current/base copy materials."""
import json
import unittest

import test_native_owner_end_sleep_cards as fixtures
from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,Game,PlayCard,
    PlayerSetup,Scenario,TargetSpec,UseLocation,Zone)
from hs_sim.engine.effects import CopyMinion
from hs_sim.engine.errors import IllegalAction
from hs_sim.engine.replay import build_replay,replay

COPY='k193.copy_current';BASE='k193.copy_base'


def registry():
    r=fixtures.registry.__wrapped__(None)
    for cid,mode,recipient in((COPY,'current',2),(BASE,'base',1)):
        r.register_behavior(cid,lambda c,m=mode,p=recipient:(CopyMinion(c.target_id,p,mode=m),))
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    r.validate();return r


class OwnerEndSleepCopyBridgeTests(unittest.TestCase):
    def setup_game(self,copy_card):
        g=Game.from_scenario(Scenario((
            PlayerSetup(fixtures.HERO,hand=(fixtures.CARD,copy_card),board=(fixtures.BODY,),
                deck=(fixtures.BODY,)*12,mana=80,max_mana=80,mana_cap=80),
            PlayerSetup(fixtures.HERO,deck=(fixtures.BODY,)*12,mana=80,max_mana=80,mana_cap=80)),seed=193),registry())
        target=g.state.players[1].board[0];loc=g.state.players[1].hand[0]
        g.apply(PlayCard(1,loc));g.apply(UseLocation(1,loc,target))
        source=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==copy_card)
        g.apply(PlayCard(1,source,target));return g,target

    def clocks(self,g,target):return[a.attack_policy_expiry for a in g.state.entities[target].abilities if a.attack_policy_expiry is not None]

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));reader=registry()
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)

    def test_current_copy_for_other_player_keeps_original_clock_through_expiry_and_replay(self):
        g,original=self.setup_game(COPY);clone=g.state.players[2].board[0]
        self.assertEqual(self.clocks(g,clone),self.clocks(g,original))
        self.assertEqual(self.clocks(g,clone)[0].player_id,1);self.portable(g)
        g.apply(EndTurn(1))
        with self.assertRaises(IllegalAction):g.apply(Attack(2,clone,original))
        g.apply(EndTurn(2));g.apply(EndTurn(1))
        self.assertFalse(self.clocks(g,clone));self.assertFalse(self.clocks(g,original));self.portable(g)
        g.apply(Attack(2,clone,original));self.portable(g)

    def test_base_copy_has_printed_health_and_no_inherited_attack_clock(self):
        g,original=self.setup_game(BASE)
        clone=next(i for i in g.state.players[1].board if i!=original and g.state.entities[i].card_id==fixtures.BODY)
        self.assertFalse(self.clocks(g,clone));self.assertEqual(g.state.entities[clone].max_health,12)
        self.assertTrue(self.clocks(g,original));self.portable(g)


if __name__=='__main__':unittest.main()
