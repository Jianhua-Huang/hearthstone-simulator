"""Real Horror payments reuse live-source and board-capacity corpse gates."""
import unittest

from hs_sim.engine import (CardDefinition,CardType,EndTurn,EndTurnSpec,Game,Keyword,
    PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec,Zone)
from hs_sim.engine.effects import ChoiceOption,RequestChoice,ReturnToHand
from hs_sim.engine.model import Resource
from hs_sim.engine.replay import build_replay,replay
from test_constructed_zone_cards import registry as original_registry

HORROR='CORE_RLK_745';SMALL='k06.small';WATCH='horror-test.watch'


def registry(mode='plain'):
    r=original_registry()
    if mode!='plain':
        def watch(c):
            if mode=='return':
                targets=[i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==HORROR]
                return(ReturnToHand(targets[0]),)if targets else()
            if c.event.player_id!=c.player_id:return()
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),source_id=c.source_id),)
        r.register_behavior(WATCH,watch)
        event='turn_ended'if mode=='return'else'resource_spent'
        trigger=TriggerSpec(event,WATCH,EndTurnSpec('controller'))if mode=='return'else TriggerSpec(event,WATCH)
        r.register_card(CardDefinition(WATCH,'Explicit Horror observer '+mode,CardType.MINION,health=5,triggers=(trigger,)))
    return r


class MalignantHorrorCorpseGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.base=registry()

    def game(self,board=(HORROR,),*,corpses=4,hand=(),mode='plain',active=1):
        return Game.from_scenario(Scenario((PlayerSetup('test.hero',board=board,hand=hand,
            deck=(SMALL,)*4,mana=30,max_mana=30,mana_cap=30,corpses=corpses),
            PlayerSetup('test.hero',deck=(SMALL,)*4)),active_player=active,seed=319),
            self.base if mode=='plain'else registry(mode))

    def horrors(self,g):return[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==HORROR]
    def bank(self,g):return g.state.players[1].resources[Resource.CORPSES]
    def portable(self,g,mode='plain'):
        saved=g.snapshot()
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(Game.from_snapshot(saved,registry(mode)).snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved)

    def test_full_board_does_not_spend_corpses_without_a_copy_slot(self):
        g=self.game((HORROR,)+(SMALL,)*6);g.apply(EndTurn(1))
        self.assertEqual(self.bank(g),4);self.assertEqual(len(self.horrors(g)),1)
        self.assertFalse(g.state.corpse_spend_history);self.portable(g)

    def test_two_originals_recheck_last_slot_before_second_payment(self):
        g=self.game((HORROR,HORROR)+(SMALL,)*4,corpses=8);g.apply(EndTurn(1))
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(len(self.horrors(g)),3)
        self.assertEqual(self.bank(g),4);self.assertEqual([r.amount for r in g.state.corpse_spend_history],[4])
        self.portable(g)

    def test_actual_reborn_body_copy_does_not_restore_consumed_reborn(self):
        g=self.game(hand=('k06.kill',));original=self.horrors(g)[0].id
        kill=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id=='k06.kill')
        g.apply(PlayCard(1,kill,original));parent=self.horrors(g)[0]
        self.assertNotEqual(parent.id,original);self.assertNotIn(Keyword.REBORN,parent.keywords)
        g.apply(EndTurn(1));bodies=self.horrors(g)
        self.assertEqual(len(bodies),2);self.assertEqual([b.health for b in bodies],[1,1])
        self.assertTrue(all(Keyword.REBORN not in b.keywords for b in bodies));self.portable(g)

    def test_captured_end_source_returned_before_body_does_not_spend(self):
        g=self.game((WATCH,HORROR),mode='return');original=self.horrors(g)[0].id
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[original].zone,Zone.HAND)
        self.assertEqual(self.bank(g),4);self.assertFalse(self.horrors(g));self.portable(g,'return')

    def test_payment_observer_wait_restores_and_delivers_only_one_copy(self):
        g=self.game((HORROR,WATCH),mode='wait');g.apply(EndTurn(1))
        self.assertEqual(self.bank(g),0);self.assertEqual(len(self.horrors(g)),1)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g,'wait')
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(len(self.horrors(g)),2);self.assertEqual(self.bank(g),0)
        self.assertEqual([r.amount for r in g.state.corpse_spend_history],[4]);self.portable(g,'wait')

    def test_opponent_end_never_spends_own_horror_corpses(self):
        g=self.game(active=2);g.apply(EndTurn(2))
        self.assertEqual(self.bank(g),4);self.assertEqual(len(self.horrors(g)),1)
        self.assertFalse(g.state.corpse_spend_history);self.portable(g)


if __name__=='__main__':unittest.main()
