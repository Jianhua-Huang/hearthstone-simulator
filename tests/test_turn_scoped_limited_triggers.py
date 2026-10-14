"""Native once-per-actual-turn budgets belong to physical finite attachments."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,Keyword,LimitedTriggerSpec,
    PlayCard,PlayerSetup,ResolutionError,Scenario,SelectChoice,SnapshotError)
from hs_sim.engine.effects import ChoiceOption,GainArmor,InvokeBehavior,RequestChoice,Silence,Summon
from hs_sim.engine.representative import build_registry,metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.limited_triggers import CheckLimitedTrigger,candidate,check
from hs_sim.engine.resolver import Resolution
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1]
PIN='30ae5d8059b14ebe83b66410269ca1cf13d436b7a2fc624aaf7e1b26cc351895'

def evidence():
    p=json.loads((ROOT/'data/support/turn-scoped-limited-trigger-basics.json').read_bytes())
    if canonical_digest(p)!=PIN:raise ValueError('Native finite turn evidence changed')
    return p

def ability(e):return next(a for a in e.abilities if a.kind=='limited_trigger')

def registry(mode='direct'):
    r=build_registry();x=evidence()['records'][0]
    r.register_trigger_condition('tt.own',lambda c:c.event.player_id==c.player_id and c.event.amount>0)
    def fail(c):raise ResolutionError('Diagnostic turn-budget failure')
    r.register_behavior('tt.fail',fail)
    def body(c):
        summon=Summon(c.player_id,'TOY_651')
        if mode=='wait':return (RequestChoice(c.player_id,(
            ChoiceOption('summon','Summon',(summon,)),
            ChoiceOption('fail','Fail',(summon,InvokeBehavior('tt.fail',c.source_id,c.player_id)))),c.source_id),)
        if mode=='fail':return (summon,InvokeBehavior('tt.fail',c.source_id,c.player_id))
        return (summon,)
    r.register_behavior('tt.native.'+mode,body)
    r.register_card(CardDefinition('TOY_651',x['name'],CardType.MINION,cost=x['cost'],attack=x['attack'],health=x['health'],
        metadata=metadata_from_record(x),limited_triggers=(LimitedTriggerSpec('armor_gained','tt.native.'+mode,condition_id='tt.own',reset='turn'),)))
    for name,fn in (('armor',lambda c:(GainArmor(c.player_id,1),)),
                    ('other_armor',lambda c:(GainArmor(1,1),)),
                    ('silence',lambda c:(Silence(c.target_id),))):
        r.register_behavior('tt.'+name,fn);r.register_card(CardDefinition('tt.'+name,'Diagnostic '+name,CardType.SPELL,
            on_play='tt.'+name,requires_target=name=='silence'))
    r.register_behavior('tt.instance',lambda c:(GainArmor(c.player_id,2),))
    r.register_card(CardDefinition('tt.once','Diagnostic instance budget',CardType.MINION,health=4,
        limited_triggers=(LimitedTriggerSpec('card_played','tt.instance'),)))
    return r

def rehash(s):
    keys=('ruleset','registry_fingerprint','mechanics_version','state','rng_state','resolution_frame',
        'rewind_session','match_setup','generation_context','information')
    s['state_hash']=canonical_hash({k:s[k] for k in keys});return s

class TurnScopedLimitedTriggerTests(unittest.TestCase):
    def game(self,board=('TOY_651',),mode='direct',enemy_board=()):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01',board=board,hand=('tt.armor',)*5+('tt.silence',),
            deck=('CS2_182',)*12,max_mana=10,mana=10),PlayerSetup('HERO_08',board=enemy_board,
            hand=('tt.other_armor',)*4,deck=('CS2_182',)*12,max_mana=10,mana=10)),seed=127),registry(mode))
    def play(self,g,name,target=None):
        p=g.state.active_player;i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(p,i,target))
    def portable(self,g):
        s=g.snapshot();self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry(self.mode)).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),s);return s

    def test_native_raw_and_budget_declaration_are_pinned(self):
        x=evidence()['records'][0];self.assertEqual(x['id'],'TOY_651');self.assertIn('once per turn',x['text_en'])
        self.assertEqual(registry().card('TOY_651').limited_triggers[0].reset,'turn')

    def test_each_existing_physical_source_spends_once_and_new_summon_has_its_own_budget(self):
        g=self.game();original=g.state.players[1].board[0];aid=ability(g.state.entities[original]).id
        self.play(g,'tt.armor');self.assertEqual(len(g.state.players[1].board),2)
        self.assertEqual((ability(g.state.entities[original]).uses_remaining,ability(g.state.entities[original]).trigger_turn),(0,1))
        self.play(g,'tt.armor');self.assertEqual(len(g.state.players[1].board),3)
        self.assertEqual(ability(g.state.entities[original]).id,aid)
        self.assertEqual(sum(e.kind=='limited_trigger_used' and e.source_id==original for e in g.events),1);self.portable(g)

    def test_two_native_carriers_have_independent_budgets_in_the_same_event(self):
        g=self.game(board=('TOY_651','TOY_651'));originals=g.state.players[1].board
        self.play(g,'tt.armor');self.assertEqual(len(g.state.players[1].board),4)
        self.assertEqual([ability(g.state.entities[i]).uses_remaining for i in originals],[0,0]);self.portable(g)

    def test_opponent_actual_turn_refreshes_both_sides_and_allows_owner_armor_reaction(self):
        g=self.game();eid=g.state.players[1].board[0];aid=ability(g.state.entities[eid]).id
        self.play(g,'tt.armor');g.apply(EndTurn(1));self.assertEqual(g.state.turn,2)
        self.assertEqual((ability(g.state.entities[eid]).uses_remaining,ability(g.state.entities[eid]).trigger_turn),(1,2))
        self.play(g,'tt.other_armor');self.assertEqual(len(g.state.players[1].board),4)
        self.assertEqual((ability(g.state.entities[eid]).id,ability(g.state.entities[eid]).uses_remaining),(aid,0));self.portable(g)

    def test_next_owner_turn_refreshes_the_same_attachment_again(self):
        g=self.game();eid=g.state.players[1].board[0];self.play(g,'tt.armor');g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual((g.state.turn,ability(g.state.entities[eid]).trigger_turn,ability(g.state.entities[eid]).uses_remaining),(3,3,1))
        self.play(g,'tt.armor');self.assertEqual(ability(g.state.entities[eid]).uses_remaining,0);self.portable(g)

    def test_previous_turn_guard_cannot_spend_the_refreshed_budget(self):
        g=self.game();eid=g.state.players[1].board[0];self.play(g,'tt.armor')
        event=next(e for e in g.events if e.kind=='armor_gained')
        captured=candidate(g.state.entities[eid],ability(g.state.entities[eid]));g.apply(EndTurn(1));s=g.snapshot()
        check(Resolution(g),CheckLimitedTrigger(captured,event,budget_turn=1))
        self.assertEqual(g.snapshot(),s);self.assertEqual(ability(g.state.entities[eid]).uses_remaining,1)

    def test_instance_global_finite_trigger_is_not_refreshed(self):
        g=self.game(board=('tt.once',));eid=g.state.players[1].board[0];self.play(g,'tt.armor')
        self.assertEqual(ability(g.state.entities[eid]).uses_remaining,0);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual((ability(g.state.entities[eid]).uses_remaining,ability(g.state.entities[eid]).trigger_turn),(0,None));self.portable(g)

    def test_consumption_precedes_choice_and_waiting_restores_and_replays(self):
        g=self.game(mode='wait');eid=g.state.players[1].board[0];self.play(g,'tt.armor')
        self.assertEqual(ability(g.state.entities[eid]).uses_remaining,0);s=self.portable(g);choice=g.state.pending_choice
        restored=Game.from_snapshot(s,registry(self.mode));g.apply(SelectChoice(1,choice.id,('summon',)))
        restored.apply(SelectChoice(1,choice.id,('summon',)));self.assertEqual(restored.snapshot(),g.snapshot());self.portable(g)

    def test_failed_direct_body_or_choice_rolls_back_the_appropriate_budget(self):
        g=self.game(mode='fail');s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Diagnostic turn-budget failure'):self.play(g,'tt.armor')
        self.assertEqual(g.snapshot(),s)
        g=self.game(mode='wait');self.play(g,'tt.armor');s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Diagnostic turn-budget failure'):
            g.apply(SelectChoice(1,g.state.pending_choice.id,('fail',)))
        self.assertEqual(g.snapshot(),s)

    def test_silenced_source_does_not_regain_a_printed_trigger_on_turn_start(self):
        g=self.game();eid=g.state.players[1].board[0];self.play(g,'tt.silence',eid);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertFalse(any(a.kind=='limited_trigger' for a in g.state.entities[eid].abilities));self.play(g,'tt.armor')
        self.assertEqual(g.state.players[1].board,[eid]);self.portable(g)

    def test_current_budget_turn_tampering_rejects_after_rehashing(self):
        g=self.game();eid=g.state.players[1].board[0];g.apply(EndTurn(1));s=g.snapshot()
        for value in (1,3,True,None):
            with self.subTest(value=value):
                altered=deepcopy(s);a=next(a for a in altered['state']['entities'][str(eid)]['abilities'] if a['kind']=='limited_trigger')
                a['trigger_turn']=value
                with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(altered),registry())

    def test_keyword_instance_semantics_and_reset_scope_are_strict(self):
        for spec in (LimitedTriggerSpec.spellburst('tt.instance'),LimitedTriggerSpec.frenzy('tt.instance')):
            with self.assertRaises(ValueError):replace(spec,reset='turn')
        with self.assertRaises(ValueError):LimitedTriggerSpec('armor_gained','tt.instance',reset=True)
        g=self.game();wire=g.snapshot();wire['schema_version']=233
        with self.assertRaisesRegex(SnapshotError,'Unsupported snapshot schema'):Game.from_snapshot(wire,registry())

    def test_internal_budget_clock_does_not_enter_player_interfaces(self):
        g=self.game();self.play(g,'tt.armor')
        for p in (1,2):
            text=json.dumps([g.for_player(p).observe(),g.for_player(p).events()])
            self.assertNotIn('trigger_turn',text);self.assertNotIn('budget_turn',text)

if __name__=='__main__':unittest.main()
