"""Two new cross-package boundaries, without importing old TestCase fixtures."""
from copy import deepcopy
import json
import unittest

from tests import test_v129_mechanism_combinations as fixtures
from hs_sim.engine import (Attack, BuffStoredCard, CardDefinition, CardType, EndTurn, Game,
    GrantPrintedAttackPermit, Keyword, MakeHandCardTemporary, PlayCard, PlayerSetup,
    PrintedAttackPolicyDeclaration, Scenario, SelectChoice, SnapshotError,
    UpgradeHandCard, Zone, capture_printed_attack_permit)
from hs_sim.engine.attack_policies import current_policies
from hs_sim.engine.effects import Buff, ChoiceOption, CopyMinion, Damage, Draw, RequestChoice
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, MoveCard


def registry():
    r=fixtures.registry()
    r.register_card(CardDefinition('stored_actor','stored_actor',CardType.MINION,attack=2,health=6,
        keywords=(Keyword.CHARGE,),attack_policies=(fixtures.BAN,)))

    def handref(c):
        return CardReference.capture(next(c.state.entities[i] for i in c.state.players[1].hand
                                         if c.state.entities[i].card_id=='stored_actor'))

    def request(c,entity_id):
        return capture_printed_attack_permit(c.state,r,entity_id,
            PrintedAttackPolicyDeclaration(c.state.entities[entity_id].card_id,0))

    def prepare(c):
        ref=handref(c)
        return [MakeHandCardTemporary(ref,1,source_id=c.source_id), BuffStoredCard(ref,1,2),
                UpgradeHandCard(ref,'grown_actor')]

    def actor_body(c):
        return [GrantPrintedAttackPermit(request(c,c.source_id)), Damage(c.source_id,2,c.source_id),
                Buff(c.source_id,health=-3,source_id=c.source_id),
                RequestChoice(1,(ChoiceOption('copy','Copy',(CopyMinion(c.source_id,1),)),),source_id=c.source_id)]

    def hybrid(c):
        ref=handref(c); actor=c.state.players[1].board[0]; req=request(c,actor)
        # One real physical card departs and returns before the old reference
        # is offered; the board request is still the same accepted residence.
        return [MoveCard(ref,1,Zone.DECK,position='top'),Draw(1),RequestChoice(1,
                (ChoiceOption('good','Good',(MakeHandCardTemporary(ref,1),
                 GrantPrintedAttackPermit(req),Buff(actor,health=-2))),),source_id=c.source_id)]

    r.register_behavior('actor_body',actor_body)
    r.register_card(CardDefinition('grown_actor','grown_actor',CardType.MINION,attack=3,health=8,
        keywords=(Keyword.CHARGE,),attack_policies=(fixtures.BAN,),on_play='actor_body'))
    for name,body in (('prepare',prepare),('hybrid',hybrid)):
        r.register_behavior(name,body)
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name))
    return r


class TemporaryCombinationTests(unittest.TestCase):
    def game(self,hand,board=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*5,mana=10,max_mana=10),
            PlayerSetup('hero',board=('plain',),deck=('plain',)*5,mana=10,max_mana=10)),seed=135),registry())

    def find(self,g,name):
        return next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)

    def cast(self,g,name): g.apply(PlayCard(1,self.find(g,name)))

    def portable(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        restored=Game.from_snapshot(snap,registry())
        self.assertEqual(restored.snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),snap)
        return restored

    def test_stored_temporary_upgrade_play_signed_layer_copy_and_both_expiry_clocks(self):
        g=self.game(('prepare','stored_actor')); actor=self.find(g,'stored_actor')
        self.cast(g,'prepare')
        self.assertEqual(g.state.entities[actor].card_id,'grown_actor')
        self.assertEqual(g.state.entities[actor].hand_lifetime.expires_turn,1)
        self.assertEqual((g.state.entities[actor].attack,g.state.entities[actor].health),(4,10))
        self.portable(g); g.apply(PlayCard(1,actor))
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((g.state.entities[actor].max_health,g.state.entities[actor].damage), (7,2))
        self.assertEqual(g.state.entities[actor].hand_lifetime.expires_turn,1)
        restored=self.portable(g); cloned=g.clone()
        for branch in (g,restored,cloned):
            choice=branch.state.pending_choice
            branch.apply(SelectChoice(1,choice.id,('copy',)))
            child=branch.state.players[1].board[-1]
            self.assertNotEqual(child,actor)
            for ident in (actor,child):
                entity=branch.state.entities[ident]
                self.assertEqual((entity.max_health,entity.damage,entity.health),(7,2,5))
                self.assertEqual(current_policies(branch.state,entity,branch.registry),())
                self.assertTrue(any(isinstance(a,Attack) and a.attacker_id==ident for a in branch.legal_actions()))
            self.portable(branch); branch.apply(EndTurn(1))
            self.assertIn(actor,branch.state.players[1].board); self.assertIn(child,branch.state.players[1].board)
            self.assertIsNone(branch.state.entities[actor].hand_lifetime)
            for ident in (actor,child):
                entity=branch.state.entities[ident]
                self.assertFalse(any(a.kind=='printed_attack_permit' for a in entity.abilities))
                self.assertEqual(current_policies(branch.state,entity,branch.registry),(fixtures.BAN,))
            self.assertFalse(any(e.kind=='card_expired' and e.target_id in (actor,child) for e in branch.events))
            self.portable(branch)
        self.assertEqual(g.snapshot(),restored.snapshot()); self.assertEqual(g.snapshot(),cloned.snapshot())

    def test_hybrid_choice_keeps_stale_hand_reference_and_valid_board_permit_separate(self):
        g=self.game(('hybrid','stored_actor'),board=('actor',)); stored=self.find(g,'stored_actor')
        actor=g.state.players[1].board[0]; self.cast(g,'hybrid'); original=g.snapshot()
        restored=self.portable(g)
        def rows(value,suffix):
            if isinstance(value,dict):
                if value.get('type','').endswith(suffix): yield value
                for child in value.values(): yield from rows(child,suffix)
            elif isinstance(value,list):
                for child in value: yield from rows(child,suffix)
        for suffix,change in (
            ('.PrintedAttackPermitRequest',lambda row:row['fields'].update(expires_owner_turn_id=99999)),
            ('.MakeHandCardTemporary',lambda row:row['fields']['card']['fields'].update(zone_epoch=99999)),
        ):
            bad=deepcopy(original); found=list(rows(bad['resolution_frame'],suffix)); self.assertTrue(found)
            for row in found: change(row)
            bad['state_hash']=canonical_hash({k:v for k,v in bad.items()
                if k not in ('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())
        for branch in (g,restored):
            choice=branch.state.pending_choice
            branch.apply(SelectChoice(1,choice.id,('good',)))
            self.assertIn(stored,branch.state.players[1].hand)
            self.assertIsNone(branch.state.entities[stored].hand_lifetime)
            self.assertEqual(current_policies(branch.state,branch.state.entities[actor],branch.registry),())
            self.assertEqual(branch.state.entities[actor].health,10)
            self.assertTrue(any(e.kind=='zone_target_skipped' and e.target_id==stored for e in branch.events))
            self.portable(branch)
        self.assertEqual(g.snapshot(),restored.snapshot())
