"""Existing nondeath movement and explicit selection policies for board carriers."""
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, EndTurn, EndTurnSpec, Game,
    IllegalAction, MinionReference, PlayCard, PlayerSetup, RemoveFromGame,
    ResolutionError, Resource, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.effects import ChoiceOption, InvokeBehavior, RequestChoice, Summon
from hs_sim.engine.player_api import visible_entities
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest
from test_nondeath_removal import LIFE, registry as removal_registry

ROOT=Path(__file__).resolve().parents[1]
PIN='ed0dfce5d2bf01c27940c610e106f670577680caeb25219aae15d0732ab933b6'
PORTAL='UNG_829t2';IMP='UNG_829t3'


def evidence():
    p=json.loads((ROOT/'data/support/board-removal-scope-basics.json').read_bytes())
    if canonical_digest(p)!=PIN:raise ValueError('Removal scope full raw changed')
    return p


def registry():
    raw={x['id']:x for x in evidence()['records']}
    def operation(c,active=False):
        return RemoveFromGame(tuple(MinionReference.capture(c.state.entities[i])
            for i in c.state.players[2].board if c.state.entities[i].kind==CardType.MINION
            and (not active or c.state.entities[i].active)),c.source_id)
    def waiting(c):
        final=RequestChoice(1,(ChoiceOption('finish','Finish'),ChoiceOption('fail','Diagnostic failure',
            effects=(InvokeBehavior('scope.fail_choice',c.source_id,c.player_id),))),source_id=c.source_id)
        return (RequestChoice(1,(ChoiceOption('remove','Remove explicit physical batch',
            effects=(operation(c),final)),),source_id=c.source_id),)
    x=raw[PORTAL];portal=CardDefinition(PORTAL,x['name'],CardType.MINION,cost=x['cost'],health=x['health'],
        metadata=metadata_from_record(x),dormant_turns=None,permanent_dormancy=True,
        dormant_triggers=(TriggerSpec('turn_ended','scope.imps',EndTurnSpec()),))
    x=raw[IMP];imp=CardDefinition(IMP,x['name'],CardType.MINION,cost=x['cost'],attack=x['attack'],health=x['health'],
        metadata=metadata_from_record(x))
    r=removal_registry((('scope.all',lambda c:(operation(c),)),
        ('scope.active',lambda c:(operation(c,True),)),('scope.wait',waiting)),((portal,None),(imp,None)))
    r.register_behavior('scope.imps',lambda c:(Summon(c.player_id,IMP),Summon(c.player_id,IMP)))
    def fail_choice(c):raise ResolutionError('Diagnostic selected callback failure')
    r.register_behavior('scope.fail_choice',fail_choice)
    return r


class BoardRemovalScopeTests(unittest.TestCase):
    def game(self,source='scope.all',enemy=(PORTAL,'probe.dormant','probe.unit')):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero',hand=(source,),deck=('card.1',)*5,max_mana=10,mana=10),
            PlayerSetup('warrior.hero',board=enemy,deck=('card.1',)*5,max_mana=10,mana=10)),seed=53),registry())

    def play(self,g,target=None):return g.apply(PlayCard(1,g.state.players[1].hand[0],target))

    def portable(self,g):
        s=g.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(s)),registry())
        self.assertEqual(restored.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        return restored

    def test_current_raw_and_historical_update_do_not_install_old_reno_board_limit(self):
        p=evidence();raw={x['id']:x for x in p['records']};text=' '.join(raw['WW_0700']['text_en'].split())
        self.assertIn('remove all enemy minions',text);self.assertNotIn('limit',text)
        self.assertEqual(raw['WW_0700']['cost'],8)
        self.assertFalse(p['full_reno_adapted']);self.assertFalse(p['old_empty_board_policy_used'])
        self.assertNotIn('WW_0700',registry().cards);self.assertNotIn('TTN_960t2',registry().cards)
        self.assertFalse(p['CN_calibrated']);self.assertEqual(p['new_runtime_modules'],0)

    def test_existing_real_targeted_removal_cannot_target_permanent_carrier(self):
        g=self.game(LIFE,enemy=(PORTAL,));i=g.state.players[2].board[0];before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,i)
        self.assertEqual(g.snapshot(),before)
        self.assertFalse(any(a.target_id==i for a in g.legal_actions() if isinstance(a,PlayCard)))
        self.portable(g)

    def test_explicit_physical_batch_retires_permanent_lifecycle_without_death(self):
        g=self.game();before={i:g.state.entities[i] for i in g.state.players[2].board}
        handles=[row['ref'] for row in g.observe(1)['players'][1]['board']];rng=g.snapshot()['rng_state']
        self.play(g);self.assertEqual(g.state.players[2].board,[])
        self.assertEqual(g.state.players[2].setaside,list(before));self.assertFalse(g.state.death_history)
        self.assertFalse(g.state.players[2].graveyard);self.assertEqual(g.state.players[2].resources[Resource.CORPSES],0)
        for i,old in before.items():
            e=g.state.entities[i];self.assertEqual(e.zone,Zone.SETASIDE);self.assertIsNone(e.dormancy)
            self.assertIsNone(e.board_presence_id);self.assertEqual(e.zone_epoch,old.zone_epoch+1)
            self.assertEqual((e.owner,e.controller,e.card_id),(old.owner,old.controller,old.card_id))
        self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertFalse({'minion_died','minion_reborn','card_discarded'} & {e.kind for e in g.events})
        for seat in (1,2):
            self.assertTrue(set(handles).isdisjoint(visible_entities(g.observe(seat))))
            receipt=next(e for e in g.player_events(seat) if e['kind']=='cards_removed_from_game')
            self.assertEqual(receipt['amount'],3);self.assertEqual({x['card_id'] for x in receipt['removed_cards']},{PORTAL,'probe.dormant','probe.unit'})
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(g.state.players[2].board,[]);self.assertFalse(g.state.death_history)
        self.portable(g)

    def test_explicit_active_minion_scope_retains_permanent_timed_and_location_carriers(self):
        g=self.game('scope.active',enemy=(PORTAL,'probe.dormant','probe.unit','probe.location'))
        before=[g.state.entities[i] for i in g.state.players[2].board]
        self.play(g)
        self.assertEqual(g.state.players[2].board,[before[n].id for n in (0,1,3)])
        self.assertEqual(g.state.players[2].setaside,[before[2].id])
        self.assertEqual(g.state.entities[before[0].id].dormancy,before[0].dormancy)
        self.assertEqual(g.state.entities[before[1].id].dormancy,before[1].dormancy)
        self.assertFalse(g.state.death_history);self.portable(g)

    def test_captured_permanent_removal_and_retired_state_restore_between_choices(self):
        g=self.game('scope.wait');self.play(g)
        self.assertEqual(len(g.state.players[2].board),3);restored=self.portable(g);cloned=g.clone()
        action=SelectChoice(1,g.state.pending_choice.id,('remove',))
        for branch in (g,restored,cloned):branch.apply(action)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.snapshot(),cloned.snapshot())
        self.assertEqual(g.state.players[2].board,[]);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,g.state.pending_choice.id,('fail',)))
        self.assertEqual(g.snapshot(),before)
        action=SelectChoice(1,g.state.pending_choice.id,('finish',))
        for branch in (g,restored,cloned):branch.apply(action)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.snapshot(),cloned.snapshot())
        self.assertEqual(sum(e.kind=='cards_removed_from_game' for e in g.events),1)
        self.assertFalse(g.state.death_history);self.portable(g)
