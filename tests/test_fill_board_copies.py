"""The new request delegates actual copies, caps and transactions to the kernel."""
import unittest

from hs_sim.engine import CardDefinition,CardType,Game,PlayCard,PlayerSetup,Registry,Ruleset,Scenario,SelectChoice
from hs_sim.engine.effects import Buff,ChoiceOption,FillBoardWithCopies,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import TargetSpec,Zone
from hs_sim.engine.replay import build_replay,replay


def registry():
    r=Registry('fill-current-copies-tests-v1')
    r.register_card(CardDefinition('fc.hero','Hero',CardType.HERO,health=30))
    r.register_card(CardDefinition('fc.minion','Minion',CardType.MINION,attack=2,health=3))
    r.register_card(CardDefinition('fc.dormant','Dormant',CardType.MINION,health=3,dormant_turns=2))
    def fail(c):raise ResolutionError('after copy allocation')
    r.register_behavior('fc.fail',fail)
    for name,handler in {
        'fill':lambda c:(FillBoardWithCopies(c.target_id,c.player_id),),
        'grow_fill':lambda c:(Buff(c.target_id,1,2,c.source_id),FillBoardWithCopies(c.target_id,c.player_id)),
        'late_fail':lambda c:(FillBoardWithCopies(c.target_id,c.player_id),InvokeBehavior('fc.fail',c.source_id,c.player_id)),
        'wait':lambda c:(RequestChoice(c.player_id,(ChoiceOption('fill','Fill',(
            FillBoardWithCopies(c.target_id,c.player_id),)),),c.source_id),),
        'skip_dormant':lambda c:(FillBoardWithCopies(c.state.players[1].board[0],c.player_id),),
    }.items():
        r.register_behavior('fc.'+name,handler)
        r.register_card(CardDefinition('fc.'+name,name,CardType.SPELL,on_play='fc.'+name,
            targeting=TargetSpec(kinds=(CardType.MINION,)) if name!='skip_dormant' else None))
    return r


class FillBoardCopyTests(unittest.TestCase):
    def game(self,cid='fc.fill',cap=4,board=('fc.minion',)):
        return Game.from_scenario(Scenario((PlayerSetup('fc.hero',hand=(cid,),board=board),
            PlayerSetup('fc.hero'),)),registry(),ruleset=Ruleset(max_board=cap))
    def play(self,g,target=True):
        g.apply(PlayCard(1,g.state.players[1].hand[0],g.state.players[1].board[0] if target else None))
    def portable(self,g):
        for other in (g.clone(),Game.from_snapshot(g.snapshot(),registry()),replay(build_replay(g),registry())):
            self.assertEqual(other.snapshot(),g.snapshot())

    def test_fills_configured_slots_with_new_current_entities(self):
        g=self.game('fc.grow_fill');self.play(g)
        ids=g.state.players[1].board;self.assertEqual(len(set(ids)),4)
        self.assertTrue(all((g.state.entities[i].attack,g.state.entities[i].health)==(3,5) for i in ids))
        self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_full_board_allocates_no_copy_and_does_not_change_rng(self):
        g=self.game(cap=1);before=g.snapshot();self.play(g)
        self.assertEqual(g.snapshot()['rng_state'],before['rng_state'])
        self.assertEqual(g.state.next_entity_id,before['state']['next_entity_id'])
        self.assertEqual(len(g.state.players[1].board),1)

    def test_dormant_target_is_not_a_copy_source(self):
        g=self.game('fc.skip_dormant',board=('fc.dormant',));self.play(g,False)
        self.assertEqual(len(g.state.players[1].board),1)

    def test_pending_instruction_restores_and_replays_before_successful_fill(self):
        g=self.game('fc.wait');self.play(g);self.portable(g)
        others=(g.clone(),Game.from_snapshot(g.snapshot(),registry()),replay(build_replay(g),registry()))
        for current in (g,*others):
            p=current.state.pending_choice;current.apply(SelectChoice(1,p.id,('fill',)))
            self.assertEqual(len(current.state.players[1].board),4)
        for current in others:self.assertEqual(current.snapshot(),g.snapshot())
        self.portable(g)

    def test_late_failure_reverts_entities_attachments_and_allocation_cursors(self):
        g=self.game('fc.late_fail');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'after copy allocation'):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_instruction_rejects_invalid_ids_and_players(self):
        for target,player in ((True,1),(0,1),(1,True),(1,3),(None,1)):
            with self.assertRaises(ValueError):FillBoardWithCopies(target,player)
