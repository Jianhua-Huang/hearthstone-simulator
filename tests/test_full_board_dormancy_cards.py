"""Actual Ash Worm and native full-board dormancy over original awaken requests."""
from copy import deepcopy
from dataclasses import replace
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.full_board_dormancy_cards import load_batch
from hs_sim.engine import Attack,CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Ruleset,Scenario,SelectChoice,SnapshotError,Zone
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import AddToHand,ChangeControl,ChoiceOption,CopyMinion,Destroy,GainArmor,InvokeBehavior,RequestChoice,Silence,Summon,Transform
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.targets import canonical_digest

ASH='MEND_040';YETI='CORE_CS2_182';LOCATION='CORE_REV_990'


def registry():
    r=build_registry()
    def choose(c):return(RequestChoice(c.player_id,(ChoiceOption('ok','Keep', (GainArmor(c.player_id,1),)),ChoiceOption('bad','Rollback',(InvokeBehavior('k61.fail',c.source_id,c.player_id),))),source_id=c.source_id),)
    bodies=dict(empty=lambda c:(),summon=lambda c:(Summon(c.player_id,YETI,c.source_id),),kill=lambda c:(Destroy(c.target_id,c.source_id),),
        silence=lambda c:(Silence(c.target_id),),sleep=lambda c:(MakeDormant(c.target_id,None,c.source_id),),
        steal=lambda c:(ChangeControl(c.target_id,c.player_id),),
        copy=lambda c:(CopyMinion(c.state.players[c.player_id].board[0],c.player_id,allow_dormant=True),),
        change=lambda c:(Transform(c.state.players[c.player_id].board[0],YETI),),
        choose=choose,fail=lambda c:(AddToHand(c.player_id,'k61.missing',c.source_id),),
        late_fail=lambda c:(Summon(c.player_id,YETI,c.source_id),InvokeBehavior('k61.fail',c.source_id,c.player_id)))
    for key,body in bodies.items():r.register_behavior('k61.'+key,body)
    for key in ('summon','kill','silence','sleep','steal','copy','change','late_fail'):
        r.register_card(CardDefinition('k61.'+key,key,CardType.SPELL,on_play='k61.'+key,requires_target=key in ('kill','silence','sleep','steal')))
    r.register_card(CardDefinition('k61.choose','Choice-only lifecycle fixture',CardType.MINION,health=2,battlecry='k61.choose'))
    return r


class FullBoardDormancyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,board=(ASH,),hand=(),enemy=(),rules=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_06',board=board,hand=hand,deck=(YETI,)*8,mana=20,max_mana=20,mana_cap=20),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=20,max_mana=20,mana_cap=20)),seed=1061),self.r,ruleset=rules)
    def source(self,g):
        s=g.state;return next(s.entities[i]for i in s.players[1].board if s.entities[i].card_id==ASH)
    def play(self,g,cid,target=None):
        s=g.state;eid=next(i for i in s.players[1].hand if s.entities[i].card_id==cid);g.apply(PlayCard(1,eid,target));return eid
    def portable(self,g):
        s=g.snapshot();self.assertEqual(Game.from_snapshot(s,registry()).snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
    def wakes(self,g):return sum(e.kind=='minion_awakened'for e in g.events)
    def test_complete_actual_source_and_six_six_face(self):
        row=load_batch()['cards'][0];c=self.r.card(ASH);self.assertEqual(canonical_digest(row['record']),row['record_sha256']);self.assertEqual((c.cost,c.attack,c.health),(1,6,6));self.assertTrue(c.dormant_board_full);self.assertIsNone(c.dormant_turns)
    def test_default_representative_fingerprint_remains_exact(self):
        self.assertEqual(representative().fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')
    def test_underfull_board_starts_indefinitely_dormant(self):
        g=self.game();self.assertIsNone(self.source(g).dormancy.remaining_turns);self.assertEqual(self.wakes(g),0);self.portable(g)
    def test_elapsed_turns_do_not_count_down_this_condition(self):
        g=self.game()
        for p in (1,2,1,2):g.apply(EndTurn(p))
        self.assertIsNotNone(self.source(g).dormancy);self.assertEqual(self.wakes(g),0)
    def test_play_as_seventh_resident_awakes_once(self):
        g=self.game(board=(YETI,)*6,hand=(ASH,));eid=self.play(g,ASH);self.assertIsNone(g.state.entities[eid].dormancy);self.assertEqual(self.wakes(g),1);self.portable(g)
    def test_playing_as_sixth_resident_does_not_awake(self):
        g=self.game(board=(YETI,)*5,hand=(ASH,));eid=self.play(g,ASH);self.assertIsNotNone(g.state.entities[eid].dormancy)
    def test_subsequent_paid_minion_fills_board(self):
        g=self.game(board=(ASH,)+(YETI,)*5,hand=(YETI,));self.play(g,YETI);self.assertIsNone(self.source(g).dormancy);self.assertEqual(self.wakes(g),1)
    def test_effect_summon_fills_board(self):
        g=self.game(board=(ASH,)+(YETI,)*5,hand=('k61.summon',));self.play(g,'k61.summon');self.assertIsNone(self.source(g).dormancy);self.portable(g)
    def test_actual_location_occupies_seventh_slot(self):
        g=self.game(board=(ASH,)+(YETI,)*5,hand=(LOCATION,));self.play(g,LOCATION);self.assertIsNone(self.source(g).dormancy);self.assertEqual(self.wakes(g),1);self.portable(g)
    def test_initial_scenario_full_board_uses_same_awakening(self):
        g=self.game(board=(ASH,)+(YETI,)*6);self.assertIsNone(self.source(g).dormancy);self.assertEqual(self.wakes(g),1);self.portable(g)
    def test_full_initial_board_including_location_normalizes(self):
        g=self.game(board=(ASH,LOCATION)+(YETI,)*5);self.assertIsNone(self.source(g).dormancy);self.portable(g)
    def test_other_dormant_residents_count_as_occupied(self):
        g=self.game(board=(ASH,'CORE_BT_156')+(YETI,)*5);self.assertIsNone(self.source(g).dormancy);s=g.state;other=next(s.entities[i]for i in s.players[1].board if s.entities[i].card_id=='CORE_BT_156');self.assertIsNotNone(other.dormancy)
    def test_full_opponent_board_does_not_wake_friendly_source(self):
        g=self.game(board=(ASH,)+(YETI,)*4,enemy=(YETI,)*7);self.assertIsNotNone(self.source(g).dormancy)
    def test_receiving_controlled_minion_counts_as_a_new_occupied_slot(self):
        g=self.game(board=(ASH,)+(YETI,)*5,hand=('k61.steal',),enemy=(YETI,));eid=g.state.players[2].board[0];self.play(g,'k61.steal',eid);self.assertIsNone(self.source(g).dormancy);self.portable(g)
    def test_configured_capacity_is_not_hardcoded_to_seven(self):
        g=self.game(board=(ASH,YETI),hand=(YETI,),rules=Ruleset(max_board=3));self.assertIsNotNone(self.source(g).dormancy);self.play(g,YETI);self.assertIsNone(self.source(g).dormancy);self.portable(g)
    def test_configured_larger_capacity_keeps_seven_underfull(self):
        g=self.game(board=(ASH,)+(YETI,)*6,rules=Ruleset(max_board=8));self.assertIsNotNone(self.source(g).dormancy)
    def test_multiple_worms_awake_once_each(self):
        g=self.game(board=(ASH,ASH)+(YETI,)*4,hand=(YETI,));self.play(g,YETI);s=g.state;self.assertTrue(all(s.entities[i].dormancy is None for i in s.players[1].board));self.assertEqual(self.wakes(g),2);self.portable(g)
    def test_copied_dormant_worms_keep_independent_native_condition(self):
        g=self.game(board=(ASH,)+(YETI,)*4,hand=('k61.copy',YETI));self.play(g,'k61.copy');self.assertEqual(self.wakes(g),0);self.play(g,YETI);self.assertEqual(self.wakes(g),2);self.portable(g)
    def test_awakening_is_not_a_second_summon_or_play(self):
        g=self.game(board=(ASH,)+(YETI,)*5,hand=(YETI,));self.play(g,YETI);self.assertEqual(len(g.state.successful_summon_history),1);self.assertEqual(len(g.state.play_history),1)
    def test_awakening_does_not_grant_immediate_attack(self):
        g=self.game(board=(ASH,)+(YETI,)*5,hand=(YETI,));self.play(g,YETI)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,self.source(g).id,g.state.players[2].hero_id))
        g.apply(EndTurn(1));g.apply(EndTurn(2));g.apply(Attack(1,self.source(g).id,g.state.players[2].hero_id));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,24);self.portable(g)
    def test_ordinary_silence_removes_printed_rewake_condition(self):
        g=self.game(board=(ASH,)+(YETI,)*6,hand=('k61.silence','k61.sleep'));eid=self.source(g).id;self.play(g,'k61.silence',eid);self.play(g,'k61.sleep',eid);self.assertIsNotNone(self.source(g).dormancy);self.assertEqual(self.wakes(g),1);self.portable(g)
    def test_new_dormancy_instance_can_awake_again_when_condition_remains(self):
        g=self.game(board=(ASH,)+(YETI,)*6,hand=('k61.sleep',));eid=self.source(g).id;self.play(g,'k61.sleep',eid);self.assertIsNone(self.source(g).dormancy);self.assertEqual(self.wakes(g),2);self.portable(g)
    def test_transform_away_removes_the_native_condition(self):
        g=self.game(board=(ASH,)+(YETI,)*6,hand=('k61.change','k61.sleep'));eid=self.source(g).id;self.play(g,'k61.change');self.assertEqual(g.state.entities[eid].card_id,YETI);self.play(g,'k61.sleep',eid);self.assertIsNotNone(g.state.entities[eid].dormancy);self.assertEqual(self.wakes(g),1)
    def test_choice_after_filling_restores_awakened_state_and_resumes(self):
        g=self.game(board=(ASH,)+(YETI,)*5,hand=('k61.choose',));self.play(g,'k61.choose');self.assertIsNotNone(g.state.pending_choice);self.assertIsNone(self.source(g).dormancy);self.portable(g);q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)));self.portable(g)
    def test_failed_choice_keeps_exact_waiting_state(self):
        g=self.game(board=(ASH,)+(YETI,)*5,hand=('k61.choose',));self.play(g,'k61.choose');before=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(q.player_id,q.id,('bad',)))
        self.assertEqual(g.snapshot(),before)
    def test_later_failure_rolls_back_summon_and_awakening(self):
        g=self.game(board=(ASH,)+(YETI,)*5,hand=('k61.late_fail',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k61.late_fail')
        self.assertEqual(g.snapshot(),before)
    def test_player_queries_do_not_wake_or_change_rng(self):
        g=self.game(board=(ASH,)+(YETI,)*5);before=g.snapshot()
        for p in (1,2):g.for_player(p).observe();g.for_player(p).legal_actions()
        self.assertEqual(g.snapshot(),before)
    def test_non_native_or_mutated_wake_ability_is_rejected(self):
        g=self.game();before=g.snapshot();eid=self.source(g).id
        for change in [dict(origin='granted'),dict(consumed=True),dict(remove_on_silence=False),dict(behavior_id='k61.empty')]:
            with self.subTest(change=change):
                bad=deepcopy(before);row=bad['state']['entities'][str(eid)];ability=next(a for a in row['abilities']if a['kind']=='board_full_awaken');ability.update(change)
                with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
    def test_invalid_definition_shapes_fail_without_registration(self):
        for kwargs in [dict(dormant_turns=2),dict(permanent_dormancy=True),dict(dormant_board_full=1)]:
            with self.subTest(kwargs=kwargs):
                r=build_registry()
                with self.assertRaises(ValueError):r.register_card(replace(r.card(ASH),id='k61.invalid',**kwargs))


if __name__=='__main__':unittest.main()
