"""Permanent portal lifecycle reuses common inactive gates and end-turn bodies."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (AdvanceDormancy, Attack, AwakenMinion, CardClass,
    CardDefinition, CardMetadata, CardType, EndTurn, EndTurnSpec, Game, IllegalAction,
    PlayCard, PlayerSetup, Registry, ResolutionError, Scenario, SelectChoice,
    SnapshotError, SpellSchool, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (ChoiceOption, Damage, Destroy, InvokeBehavior, RequestChoice,
    ReturnToHand, Silence, Summon)
from hs_sim.engine.model import DormancyState
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1]
PIN='25008d079966bbe5c0a849927577c673e1981c288c34d6a50ddb4a07fae97e19'
SPELL='UNG_829t1';PORTAL='UNG_829t2';IMP='UNG_829t3';CROC='CS2_120'


def evidence():
    p=json.loads((ROOT/'data/support/permanent-board-carriers-basics.json').read_bytes())
    if canonical_digest(p)!=PIN:raise ValueError('Permanent carrier full raw changed')
    return p


def registry(pause=False,permanent=True):
    r=Registry('permanent-board-carriers-independent-v1')
    raw={x['id']:x for x in evidence()['records']}
    r.register_card(CardDefinition('pc.hero','Diagnostic Warlock',CardType.HERO,health=30,
        metadata=CardMetadata(False,(CardClass.WARLOCK,),None)))
    for name in (CROC,IMP):
        x=raw[name];r.register_card(CardDefinition(name,x['name'],CardType.MINION,
            cost=x['cost'],attack=x['attack'],health=x['health'],metadata=metadata_from_record(x)))
    r.register_behavior('pc.open',lambda c:(Summon(c.player_id,PORTAL),))
    x=raw[SPELL];r.register_card(CardDefinition(SPELL,x['name'],CardType.SPELL,
        cost=x['cost'],spell_school=SpellSchool.SHADOW,on_play='pc.open',metadata=metadata_from_record(x)))
    r.register_behavior('pc.imps',lambda c:(Summon(c.player_id,IMP),Summon(c.player_id,IMP)))
    x=raw[PORTAL];r.register_card(CardDefinition(PORTAL,x['name'],CardType.MINION,
        cost=x['cost'],health=x['health'],metadata=metadata_from_record(x),
        dormant_turns=None,permanent_dormancy=permanent,
        dormant_triggers=(TriggerSpec('turn_ended','pc.imps',EndTurnSpec()),)))
    def carrier(c):return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==PORTAL)
    bodies={
        'wake':lambda c:(AwakenMinion(carrier(c),c.source_id),),
        'advance':lambda c:(AdvanceDormancy(carrier(c),999,c.source_id),),
        'touch':lambda c:(Damage(carrier(c),99),Destroy(carrier(c)),Silence(carrier(c)),ReturnToHand(carrier(c))),
        'fail':lambda c:(Summon(c.player_id,PORTAL),Summon(c.player_id,'pc.unknown')),
    }
    for name,fn in bodies.items():
        r.register_behavior('pc.'+name,fn)
        r.register_card(CardDefinition('pc.'+name,name,CardType.SPELL,on_play='pc.'+name))
    r.register_behavior('pc.target',lambda c:(Damage(c.target_id,1),))
    r.register_card(CardDefinition('pc.target','Diagnostic ordinary target',CardType.SPELL,
        on_play='pc.target',targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    if pause:
        def fail_choice(c):raise ResolutionError('Diagnostic selected callback failure')
        r.register_behavior('pc.fail_choice',fail_choice)
        def pause_after_first(c):
            if c.event.player_id!=c.player_id or sum(c.state.entities[i].card_id==IMP for i in c.state.players[c.player_id].board)!=1:return ()
            return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                ChoiceOption('fail','Diagnostic failure',effects=(InvokeBehavior('pc.fail_choice',c.source_id,c.player_id),))),source_id=c.source_id),)
        r.register_behavior('pc.pause',pause_after_first)
        r.register_card(CardDefinition('pc.observer','Diagnostic pause observer',CardType.MINION,
            health=3,triggers=(TriggerSpec('minion_summoned','pc.pause'),)))
    return r


class PermanentBoardCarrierTests(unittest.TestCase):
    def game(self,board=(),hand=(),enemy=(),pause=False):
        return Game.from_scenario(Scenario((
            PlayerSetup('pc.hero',board=board,hand=hand,deck=(CROC,)*20,max_mana=10,mana=10),
            PlayerSetup('pc.hero',board=enemy,hand=(SPELL,),deck=(CROC,)*20,max_mana=10,mana=10)),seed=31),registry(pause))

    def play(self,g,name,target=None):
        i=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(1,i,target))

    def portal(self,g):
        return next(g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id==PORTAL)

    def imps(self,g):
        return [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id==IMP]

    def check(self,g,pause=False):
        s=g.snapshot();self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry(pause)).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry(pause)).snapshot(),s)

    def test_real_raw_is_pinned_and_other_portal_bodies_are_not_bulk_adapted(self):
        p=evidence();self.assertEqual(len(p['records']),7)
        raw={x['id']:x for x in p['records']}
        self.assertEqual(raw[PORTAL]['tags']['UNTOUCHABLE'],1)
        self.assertIn('permanent',raw[SPELL]['text_en'])
        self.assertEqual((raw[IMP]['attack'],raw[IMP]['health']),(3,2))
        self.assertFalse(p['formal_pool_verified']);self.assertFalse(p['CN_calibrated'])
        self.assertTrue(set(p['unadapted_permanent_carriers']).isdisjoint(registry().cards))

    def test_reward_pays_once_and_opens_a_permanent_carrier(self):
        g=self.game(hand=(SPELL,));rng=g.snapshot()['rng_state']
        self.play(g,SPELL);p=self.portal(g)
        self.assertEqual(g.state.players[1].mana,5)
        self.assertFalse(p.active);self.assertTrue(p.dormancy.permanent)
        self.assertIsNone(p.dormancy.remaining_turns)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(len(self.imps(g)),0)
        self.check(g)

    def test_own_end_turn_body_runs_and_opponent_turn_does_not(self):
        g=self.game(hand=(SPELL,));self.play(g,SPELL);before=self.portal(g).dormancy
        g.apply(EndTurn(1));self.assertEqual([(i.attack,i.health) for i in self.imps(g)],[(3,2),(3,2)])
        g.apply(EndTurn(2));self.assertEqual(len(self.imps(g)),2)
        self.assertEqual(self.portal(g).dormancy,before)
        self.check(g)

    def test_multiple_rounds_keep_same_identity_lifecycle_and_slot(self):
        g=self.game(board=(PORTAL,));before=self.portal(g);rng=g.snapshot()['rng_state']
        for count in (2,4,6):
            g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(len(self.imps(g)),count)
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(len(self.imps(g)),6);self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual((self.portal(g).id,self.portal(g).dormancy),(before.id,before.dormancy))
        self.assertEqual(g.snapshot()['rng_state'],rng);self.check(g)

    def test_one_free_slot_summons_only_one_and_full_board_keeps_carrier(self):
        g=self.game(board=(PORTAL,)+(CROC,)*5);before=self.portal(g)
        g.apply(EndTurn(1));self.assertEqual(len(self.imps(g)),1)
        self.assertEqual(len(g.state.players[1].board),7)
        g.apply(EndTurn(2));g.apply(EndTurn(1));self.assertEqual(len(self.imps(g)),1)
        self.assertEqual(self.portal(g),before);self.check(g)

    def test_carrier_cannot_attack_or_be_an_ordinary_action_target(self):
        g=self.game(board=(PORTAL,),hand=('pc.target',),enemy=(CROC,));p=self.portal(g)
        for action in (Attack(1,p.id,g.state.players[2].hero_id),
                       Attack(1,g.state.players[1].hero_id,p.id),
                       PlayCard(1,g.state.players[1].hand[0],p.id)):
            before=g.snapshot()
            with self.assertRaises(IllegalAction):g.apply(action)
            self.assertEqual(g.snapshot(),before)
        self.assertFalse(any(getattr(a,'target_id',None)==p.id or getattr(a,'attacker_id',None)==p.id for a in g.legal_actions()))

    def test_existing_damage_destroy_silence_and_return_gates_ignore_carrier(self):
        g=self.game(board=(PORTAL,),hand=('pc.touch',));before=self.portal(g)
        self.play(g,'pc.touch');self.assertEqual(self.portal(g),before)
        self.assertFalse(any(e.kind=='minion_died' and e.source_id==before.id for e in g.events))
        self.check(g)

    def test_explicit_awaken_and_countdown_advance_cannot_release_carrier(self):
        g=self.game(board=(PORTAL,),hand=('pc.wake','pc.advance'));before=self.portal(g)
        self.play(g,'pc.wake');self.play(g,'pc.advance')
        self.assertEqual(self.portal(g),before)
        self.assertFalse(any(e.kind in ('minion_awakened','dormancy_progressed') for e in g.events))
        self.check(g)

    def test_rehashed_snapshot_cannot_remove_or_change_native_permanence(self):
        g=self.game(board=(PORTAL,CROC));p=self.portal(g)
        for value in (None,replace(p.dormancy,permanent=False),
                      replace(p.dormancy,permanent=False,remaining_turns=2)):
            s=g.snapshot();s['state']['entities'][str(p.id)]['dormancy']=None if value is None else dict(value.__dict__)
            s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())
        s=g.snapshot();i=g.state.players[1].board[1]
        s['state']['entities'][str(i)]['dormancy']=dict(p.dormancy.__dict__,id=g.state.next_attachment_id-1)
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_native_and_instance_permanence_require_strict_valid_types(self):
        original=registry().card(PORTAL)
        for field in ({'permanent_dormancy':1},{'permanent_dormancy':None},
                      {'dormant_turns':2},{'dormant_turns':0},{'kind':CardType.SPELL},
                      {'on_awaken':'pc.imps'}):
            with self.subTest(field=field),self.assertRaises(ValueError):Registry('invalid').register_card(replace(original,**field))
        for value in (1,None,'yes'):
            with self.assertRaises(ValueError):DormancyState(1,None,1,value)
        with self.assertRaises(ValueError):DormancyState(1,2,1,True)
        self.assertFalse(DormancyState(1,None,1).permanent)

    def test_pause_between_imps_restores_replays_and_rolls_back_failed_choice(self):
        g=self.game(board=('pc.observer',),hand=(SPELL,),pause=True);self.play(g,SPELL)
        g.apply(EndTurn(1));self.assertEqual(len(self.imps(g)),1);self.assertIsNotNone(g.state.pending_choice)
        before=g.snapshot();self.check(g,True)
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,g.state.pending_choice.id,('fail',)))
        self.assertEqual(g.snapshot(),before)
        restored=Game.from_snapshot(before,registry(True));cloned=g.clone()
        action=SelectChoice(1,g.state.pending_choice.id,('continue',))
        for branch in (g,restored,cloned):branch.apply(action)
        self.assertEqual(len(self.imps(g)),2);self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.active_player,2)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.snapshot(),cloned.snapshot())
        self.assertTrue(self.portal(g).dormancy.permanent);self.check(g,True)

    def test_failure_after_carrier_creation_rolls_back_payment_board_and_history(self):
        g=self.game(hand=('pc.fail',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'pc.fail')
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_both_players_see_carrier_without_internal_lifecycle_or_hidden_cards(self):
        g=self.game(board=(PORTAL,),hand=('pc.wake',));p=self.portal(g)
        for seat in (1,2):
            view=g.observe(seat);row=view['players'][0]['board'][0]
            self.assertEqual(row['card_id'],PORTAL);self.assertEqual(row['dormancy'],{'remaining_turns':None})
            self.assertNotIn('permanent',row['dormancy']);self.assertNotIn('started_turn',row['dormancy'])
            hidden=json.dumps(view['players'][1 if seat==1 else 0],ensure_ascii=False)
            self.assertNotIn(SPELL if seat==1 else 'pc.wake',hidden)
            public=json.dumps(g.for_player(seat).events(),ensure_ascii=False)
            self.assertNotIn('pc.wake',public)
        self.assertTrue(p.dormancy.permanent);self.check(g)

    def test_permanent_policy_participates_in_registry_identity(self):
        self.assertNotEqual(registry().fingerprint(),registry(permanent=False).fingerprint())
