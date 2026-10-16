"""Shared simultaneous board destruction and owner-directed random return."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION

import json
import unittest

from hs_sim.engine import CardDefinition, CardType, Game, PlayCard, PlayerSetup, Scenario, SelectChoice
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Destroy, DestroyBatch,
    Draw, RandomReturnToHand, RequestChoice, Summon)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import Zone
from hs_sim.engine.registry import Registry
from hs_sim.engine.replay import build_replay, replay


def registry():
    r=Registry('destruction-instructions-v1')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=30))
    r.register_card(CardDefinition('plain','Plain',CardType.MINION,attack=1,health=3))
    r.register_card(CardDefinition('dormant','Dormant',CardType.MINION,health=3,dormant_turns=2))
    r.register_behavior('location',lambda c:(Draw(c.player_id,0),))
    r.register_card(CardDefinition('location','Location',CardType.LOCATION,durability=2,on_use='location'))
    r.register_card(CardDefinition('weapon','Weapon',CardType.WEAPON,attack=1,durability=2))
    r.register_behavior('death',lambda c:(Summon(c.player_id,'plain'),))
    r.register_card(CardDefinition('death','Death',CardType.MINION,health=2,deathrattle='death'))
    def targets(c): return tuple(e for p in c.state.players.values() for e in p.board)
    r.register_behavior('batch',lambda c:(DestroyBatch(targets(c),c.source_id),))
    r.register_behavior('singles',lambda c:tuple(Destroy(e,c.source_id) for e in targets(c)))
    r.register_behavior('return',lambda c:(RandomReturnToHand(tuple(c.state.players[1].board),c.source_id),))
    r.register_behavior('transfer',lambda c:(ChangeControl(c.target_id,1),))
    r.register_behavior('fail',lambda c:(DestroyBatch(targets(c),c.source_id),Summon(1,'not-implemented')))
    r.register_behavior('wait',lambda c:(RequestChoice(1,(ChoiceOption('continue','Continue',()),),c.source_id),
        DestroyBatch(targets(c),c.source_id),RandomReturnToHand(tuple(c.state.players[2].board),c.source_id)))
    for name in ('batch','singles','return','transfer','fail','wait'):
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,requires_target=name=='transfer'))
    return r


class DestructionInstructionTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),*,enemy_hand=()):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,weapon_card_id='weapon'),
            PlayerSetup('hero',hand=enemy_hand,board=enemy)),seed=29),registry())

    def play(self,g,cid,target=None):
        eid=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid)
        g.apply(PlayCard(1,eid,target_id=target))

    def test_batch_has_one_death_wave_and_single_marks_have_distinct_waves(self):
        g=self.game(('batch',),('plain','plain'),('plain',))
        self.play(g,'batch')
        self.assertEqual(len(g.state.death_history),3)
        self.assertEqual(len({d.batch for d in g.state.death_history}),1)
        g=self.game(('singles',),('plain','plain'),('plain',))
        self.play(g,'singles')
        self.assertEqual(len({d.batch for d in g.state.death_history}),3)

    def test_locations_share_the_wave_dormant_and_weapons_are_preserved(self):
        g=self.game(('batch',),('location','plain','dormant'),('location','plain'))
        weapon=g.state.players[1].weapon_id
        self.play(g,'batch')
        self.assertEqual(len(g.state.death_history),4)
        self.assertEqual(len({d.batch for d in g.state.death_history}),1)
        self.assertEqual(g.state.players[1].weapon_id,weapon)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].board],['dormant'])

    def test_batch_deathrattles_spawn_after_all_original_victims_are_removed(self):
        g=self.game(('batch',),('death',),('death',))
        original=set(g.state.players[1].board+g.state.players[2].board)
        self.play(g,'batch')
        self.assertEqual({d.entity_id for d in g.state.death_history},original)
        self.assertEqual(len({d.batch for d in g.state.death_history}),1)
        self.assertTrue(all([g.state.entities[e].card_id for e in p.board]==['plain'] for p in g.state.players.values()))

    def test_random_return_uses_original_owner_after_control_transfer(self):
        g=self.game(('transfer','return'),enemy=('plain',))
        target=g.state.players[2].board[0]
        self.play(g,'transfer',target); self.play(g,'return')
        self.assertIn(target,g.state.players[2].hand)
        self.assertEqual(g.state.entities[target].controller,2)
        self.assertEqual(len(g.state.death_history),0)

    def test_full_owner_hand_uses_existing_return_failure_death_path(self):
        g=self.game(('transfer','return'),enemy=('death',),enemy_hand=('plain',)*10)
        target=g.state.players[2].board[0]
        self.play(g,'transfer',target); self.play(g,'return')
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual((g.state.death_history[0].owner,g.state.death_history[0].controller),(2,1))
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].board],['plain'])
        self.assertEqual(len(g.state.players[2].hand),10)

    def test_empty_random_pool_preserves_rng_and_seeded_return_replays(self):
        g=self.game(('return',))
        rng=g.snapshot()['rng_state']; self.play(g,'return')
        self.assertEqual(g.snapshot()['rng_state'],rng)
        g=self.game(('return',),('plain','plain'))
        self.play(g,'return')
        self.assertEqual(len(g.state.players[1].hand),1)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),g.snapshot())

    def test_queued_new_effects_restore_clone_replay_and_player_privacy(self):
        g=self.game(('wait',),('plain',),('plain',))
        self.play(g,'wait')
        saved=json.loads(json.dumps(g.snapshot()))
        restored=Game.from_snapshot(saved,registry())
        self.assertEqual(restored.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        self.assertEqual(g.for_player(2).legal_actions()['observation']['pending_choice'],{'player_id':1})
        g.apply(SelectChoice(1,g.state.pending_choice.id,('continue',)))
        restored.apply(SelectChoice(1,restored.state.pending_choice.id,('continue',)))
        self.assertEqual(restored.snapshot(),g.snapshot())
        self.assertEqual(len(g.state.death_history),2)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),g.snapshot())

    def test_late_failure_rolls_back_batch_deaths_events_and_rng(self):
        g=self.game(('fail',),('death',),('plain',))
        before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'fail')
        self.assertEqual(g.snapshot(),before)

    def test_unchanged_save_layout_still_rejects_old_mechanics_signature(self):
        g=self.game(); saved=g.snapshot()
        self.assertEqual(saved['schema_version'],SNAPSHOT_SCHEMA_VERSION)
        saved['mechanics_version']='core-effects-v306'
        with self.assertRaisesRegex(SnapshotError,'Mechanics version mismatch'):
            Game.from_snapshot(saved,registry())

    def test_instruction_inputs_reject_duplicates_booleans_and_mutable_vectors(self):
        for cls in (DestroyBatch,RandomReturnToHand):
            for value in ([1],(True,),(1,1),(0,)):
                with self.subTest(cls=cls,value=value),self.assertRaises(ValueError): cls(value)
