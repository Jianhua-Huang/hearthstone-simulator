"""The real Glaciate declaration also works through auto cast and terminal flow."""
import json,unittest
import test_discovery_summon_freeze_cards as base
from hs_sim.engine import CardDefinition,CardType,Game,PlayCard,PlayerSetup,Scenario
from hs_sim.engine.effects import Damage
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell


def registry(terminal=False):
    r=base.registry(members=(base.NEUTRAL,))
    r.register_behavior(base.P+'auto',lambda c:(CastSpell(1,base.GLACIATE,c.source_id,choices='random'),))
    r.register_card(CardDefinition(base.P+'auto','Actual automatic spell fixture',CardType.SPELL,on_play=base.P+'auto',metadata=base.META))
    if terminal:
        r.register_behavior(base.P+'end',lambda c:(Damage(c.state.players[2].hero_id,30,c.source_id),))
        r.register_card(CardDefinition(base.P+'end','Actual Freeze end reaction',CardType.MINION,health=5,metadata=base.META,
            limited_triggers=(LimitedTriggerSpec('frozen',base.P+'end'),)))
    r.validate();return r


class DiscoveredFreezeExecutionTests(unittest.TestCase):
    def game(self,terminal=False):
        self.terminal=terminal
        return Game.from_scenario(Scenario((PlayerSetup('HERO_02',hand=(base.GLACIATE if terminal else base.P+'auto',),
            board=(base.P+'end',)if terminal else(),mana=10,max_mana=10,deck=(base.YETI,)*4),
            PlayerSetup('HERO_08',deck=(base.YETI,)*4)),seed=112,generation_context=base.CTX),registry(terminal))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));self.assertEqual(Game.from_snapshot(s,registry(self.terminal)).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.terminal)).snapshot(),s)

    def test_automatic_out_of_hand_glaciate_selects_summons_freezes_and_pays_no_generated_cost(self):
        g=self.game();g.apply(PlayCard(1,g.state.players[1].hand[0]));self.assertIsNone(g.state.pending_choice)
        bodies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==base.NEUTRAL]
        self.assertEqual(len(bodies),1);self.assertTrue(bodies[0].frozen);self.assertEqual(g.state.players[1].mana,10)
        root,=g.state.discovery_summon_history;self.assertEqual(root.freeze_acceptances,(0,));self.assertEqual(root.status,'completed')
        self.assertEqual(root.spec.cause.origin,'spell_cast');self.assertEqual(root.spec.cause.cast_card_id,base.GLACIATE);self.portable(g)

    def test_freeze_triggered_terminal_retains_original_acceptance_and_interrupts_parent(self):
        from hs_sim.engine import SelectChoice
        g=self.game(terminal=True);g.apply(PlayCard(1,g.state.players[1].hand[0]));q=g.state.pending_choice
        g.apply(SelectChoice(1,q.id,(q.options[0].id,)));self.assertNotEqual(g.state.status,'playing');self.assertIsNone(g.state.pending_choice)
        root,=g.state.discovery_summon_history;self.assertEqual(root.freeze_acceptances,(0,));self.assertEqual(root.status,'interrupted')
        self.assertEqual(g.state.card_summon_history[0].status,'completed');self.portable(g)


if __name__=='__main__':unittest.main()
