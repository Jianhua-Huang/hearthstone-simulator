"""Actual original Fireball, Archer, SI:7 and Fireblast under native targeting."""
from dataclasses import asdict
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,ResolutionError,
    Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,UseHeroPower,Zone)
from hs_sim.engine.effects import ChoiceOption,Destroy,InvokeBehavior,RequestChoice,ReturnToHand
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.native_target_acceptance import ACCEPTED,FINISHED,FinishNativeTarget
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from test_native_random_target_domains import fixture as domain_fixture,CARD,UNIT

P='fixture.native.accept.';WATCH=P+'watch';FIRE='CS2_029';ARCHER='CS2_189';SI7='EX1_134';POWER='HERO_08bp'


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r=domain_fixture.__wrapped__()
    def watch(c):
        if mode=='fail':raise ResolutionError('Native target body observer failure')
        if mode=='wait':return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),)
        return ()
    r.register_behavior(P+mode+'.watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,
        triggers=(TriggerSpec('health_resolved',P+mode+'.watch'),)))
    def clear(c):
        if c.state.entities[c.event.source_id].card_id!='EX1_581':return ()
        return tuple(Destroy(i,c.source_id)for i in c.state.players[2].board)
    r.register_behavior(P+'clear',clear)
    r.register_card(CardDefinition(P+'clear','Target removal observer',CardType.MINION,health=20,
        triggers=(TriggerSpec('card_committed',P+'clear'),)))
    r.register_target_rule(P+'own_player_predicate',lambda c:c.target is not None and
        c.target['controller']==c.player_id,visibility='player')
    r.register_behavior(P+'noop',lambda c:())
    r.register_card(CardDefinition(P+'player_predicate','Player predicate fixture',CardType.SPELL,
        on_play=P+'noop',targeting=TargetSpec(kinds=(CardType.MINION,)),target_rule=P+'own_player_predicate'))
    def blink(c):
        if c.state.entities[c.event.source_id].card_id not in('TIME_435','TLC_452t35'):return ()
        play=next(p for p in reversed(c.state.play_history)if p.source_id==c.event.source_id)
        return(ReturnToHand(play.target_id),InvokeBehavior(P+'resummon',c.source_id,c.player_id,play.target_id))
    def resummon(c):
        target=c.state.entities[c.target_id]
        return(SummonStoredCard(CardReference.capture(target),target.controller,cause=SummonCause.capture(c)),)
    r.register_behavior(P+'blink',blink);r.register_behavior(P+'resummon',resummon)
    r.register_card(CardDefinition(P+'blink','Original target lifecycle observer',CardType.MINION,health=20,
        triggers=(TriggerSpec('card_committed',P+'blink'),)))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
    return s


class NativeManualTargetAcceptanceTests(unittest.TestCase):
    def game(self,hand=(FIRE,ARCHER,SI7,'GAME_005'),mode='normal',board=None,enemy=(UNIT,),seed=313):
        board=(CARD,UNIT)if board is None else board
        if mode in('wait','fail'):board=(*board,WATCH)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,mana=10,max_mana=10,hero_power_card_id=POWER),
            PlayerSetup('HERO_03',board=enemy,mana=10,max_mana=10)),seed=seed),fixture(mode))
    def hand(self,g,cid,p=1):return next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
    def target(self,g):return g.state.players[2].board[0]
    def play(self,g,cid,target=None):
        eid=self.hand(g,cid);g.apply(PlayCard(1,eid,target));return eid
    def selections(self,g):
        codec=FrameCodec(g.mechanics,g.registry)
        return[(dict(e.data)['origin'],codec.decode(json.loads(dict(e.data)['selection'])))for e in g.events if e.kind==ACCEPTED]
    def portable(self,g,mode='normal'):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,fixture.__wrapped__(mode))
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),fixture.__wrapped__(mode)).snapshot(),s)
        return other
    def test_paid_real_fireball_keeps_submission_and_casts_at_native_target(self):
        g=self.game();original=self.target(g);eid=self.play(g,FIRE,original)
        origin,selection=self.selections(g)[0]
        self.assertEqual(origin,'manual_card');self.assertEqual(selection.partition.submitted_target_id,original)
        self.assertEqual(g.state.play_history[-1].target_id,original)
        self.assertEqual(g.state.cast_history[-1].target_id,selection.target_id)
        self.assertEqual(g.state.players[1].mana,6)
        self.assertTrue(any(e.kind=='damage_dealt'and e.source_id==eid and e.target_id==selection.target_id and e.amount==6 for e in g.events))
        self.assertEqual(sum(e.kind==FINISHED for e in g.events),1);self.portable(g)
    def test_real_archer_has_separate_original_play_and_actual_battlecry_target(self):
        g=self.game();original=self.target(g);eid=self.play(g,ARCHER,original)
        row=g.state.battlecry_history[-1];self.assertIsNotNone(row.native_target)
        self.assertEqual(g.state.play_history[-1].target_id,original)
        self.assertEqual(row.native_target.partition.submitted_target_id,original)
        self.assertEqual(row.target_id,row.native_target.target_id)
        self.assertTrue(any(e.kind=='damage_dealt'and e.source_id==eid and e.target_id==row.target_id for e in g.events))
        self.portable(g)
    def test_real_si7_combo_uses_original_paid_play_and_one_native_acceptance(self):
        g=self.game();self.play(g,'GAME_005');original=self.target(g);self.play(g,SI7,original)
        row=g.state.combo_history[-1];self.assertIsNotNone(row.native_target)
        self.assertEqual(row.native_target.partition.submitted_target_id,original)
        self.assertEqual(row.target_id,row.native_target.target_id)
        self.assertEqual(len([x for x in self.selections(g)if x[0]=='combo']),1)
        self.portable(g)
    def test_real_manual_fireblast_pays_original_cost_and_keeps_actual_target(self):
        g=self.game();original=self.target(g);power=g.state.players[1].hero_power_id
        g.apply(UseHeroPower(1,power,original));row=g.state.hero_power_history[-1]
        self.assertIsNotNone(row.native_target);self.assertEqual(row.native_target.partition.submitted_target_id,original)
        self.assertEqual(row.target_id,row.native_target.target_id);self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual(g.state.entities[power].uses_this_turn,1);self.portable(g)
    def test_real_deios_repeated_archer_accepts_two_fresh_domains_with_one_payment(self):
        g=self.game(board=(CARD,'TIME_064',UNIT));original=self.target(g);self.play(g,ARCHER,original)
        rows=g.state.battlecry_history
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r.native_target is not None for r in rows))
        self.assertEqual([r.repeat_index for r in rows],[1,2])
        self.assertEqual(g.state.players[1].mana,9)
        self.assertEqual(len([x for x in self.selections(g)if x[0]=='battlecry']),2)
        self.portable(g)
    def test_no_native_source_preserves_original_target_without_native_rng_or_receipts(self):
        g=self.game(board=(UNIT,));before=g._rng.getstate();original=self.target(g)
        self.play(g,FIRE,original)
        self.assertEqual(g.state.cast_history[-1].target_id,original);self.assertFalse(self.selections(g))
        self.assertEqual(g._rng.getstate(),before);self.portable(g)
    def test_missing_last_enemy_target_fizzles_real_assassinate_without_fake_counter(self):
        g=self.game(hand=('EX1_581',),board=(CARD,P+'clear'));original=self.target(g)
        self.play(g,'EX1_581',original)
        cast=g.state.cast_history[-1]
        self.assertEqual(cast.failure,'no_target');self.assertTrue(cast.completed);self.assertFalse(cast.payload_started)
        self.assertFalse(g.state.play_history[-1].countered);self.assertIsNone(cast.target_id)
        self.assertEqual(self.selections(g)[0][1].failure,'no_target');self.portable(g)
    def test_waiting_native_body_restores_full_proof_clone_and_replay(self):
        g=self.game(mode='wait');self.play(g,ARCHER,self.target(g))
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,'wait')
        for current in(g,other):
            q=current.state.pending_choice;current.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g,'wait')
    def test_actual_counterspell_prevents_native_target_sampling(self):
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(FIRE,),board=(CARD,UNIT),mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=('CORE_EX1_287',),board=(UNIT,),mana=10,max_mana=10)),
            active_player=2,seed=313),fixture())
        g.apply(PlayCard(2,self.hand(g,'CORE_EX1_287',2)));g.apply(EndTurn(2))
        before=g._rng.getstate();self.play(g,FIRE,self.target(g))
        self.assertEqual(g.state.cast_history[-1].failure,'countered')
        self.assertEqual(g._rng.getstate(),before);self.assertFalse(self.selections(g));self.portable(g)
    def test_sinestra_empty_domain_keeps_two_failed_casts_and_one_original_payment(self):
        g=self.game(hand=('EX1_581',),board=(CARD,'CATA_154',P+'clear'))
        self.play(g,'EX1_581',self.target(g));rows=g.state.cast_history
        self.assertEqual(len(rows),2);self.assertEqual([c.origin for c in rows],['hand','repeat'])
        self.assertTrue(all(c.failure=='no_target'and c.completed and not c.payload_started for c in rows))
        self.assertEqual(len(self.selections(g)),1);self.assertEqual(len(g.state.play_history),1)
        self.assertEqual(g.state.spell_repeats[-1].completed,2);self.portable(g)
    def test_real_deios_power_repeats_preserve_the_single_manual_use_acceptance(self):
        g=self.game(board=(CARD,'TIME_064',UNIT));power=g.state.players[1].hero_power_id
        g.apply(UseHeroPower(1,power,self.target(g)))
        row=g.state.hero_power_history[-1]
        self.assertEqual(len(g.state.hero_power_payload_history),2)
        self.assertEqual(len([x for x in self.selections(g)if x[0]=='hero_power']),1)
        self.assertEqual(g.state.players[1].mana,8)
        self.assertTrue(all(e.target_id==row.target_id for e in g.events if e.kind=='damage_dealt'))
        self.portable(g)
    def test_player_predicate_uses_original_player_dto_at_full_acceptance_window(self):
        g=self.game(hand=(P+'player_predicate',));own=g.state.players[1].board[-1]
        self.play(g,P+'player_predicate',own);selection=self.selections(g)[0][1]
        self.assertTrue(all(x.controller==1 for x in selection.partition.candidates))
        self.portable(g)
    def test_opponent_owned_native_source_changes_second_players_real_archer_target(self):
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',board=(CARD,UNIT),mana=10,max_mana=10),
            PlayerSetup('HERO_03',hand=(ARCHER,),board=(UNIT,),mana=10,max_mana=10)),active_player=2,seed=313),fixture())
        original=g.state.players[1].board[-1];g.apply(PlayCard(2,self.hand(g,ARCHER,2),original))
        row=g.state.battlecry_history[-1]
        self.assertEqual(row.player_id,2);self.assertEqual(row.native_target.partition.player_id,2)
        self.assertEqual(row.native_target.partition.carriers[0].source.controller,1)
        self.assertEqual(row.native_target.partition.submitted_target_id,original);self.portable(g)
    def test_spell_and_power_waits_restore_their_distinct_native_acceptance_windows(self):
        for action in('spell','power'):
            with self.subTest(action=action):
                g=self.game(mode='wait')
                if action=='spell':self.play(g,FIRE,self.target(g))
                else:g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,self.target(g)))
                self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,'wait')
                for current in(g,other):
                    q=current.state.pending_choice;current.apply(SelectChoice(q.player_id,q.id,('ok',)))
                self.assertEqual(g.snapshot(),other.snapshot())
                self.assertEqual(sum(e.kind==FINISHED for e in g.events),1)
    def test_hand_no_target_failure_cannot_be_forged_without_its_native_receipt(self):
        g=self.game(board=(UNIT,));self.play(g,FIRE,self.target(g))
        s=json.loads(json.dumps(g.snapshot()));row=s['state']['cast_history'][-1]
        row.update(target_id=None,target_origin=None,failure='no_target',payload_started=False)
        with self.assertRaises((SnapshotError,ValueError)):
            Game.from_snapshot(rehash(s),fixture.__wrapped__())
    def test_native_same_id_control_targets_use_newly_accepted_residence(self):
        for card in('TIME_435','TLC_452t35'):
            with self.subTest(card=card):
                g=self.game(hand=(card,),board=(CARD,P+'blink'),enemy=(ARCHER,))
                target=self.target(g);epoch=g.state.entities[target].zone_epoch
                self.play(g,card,target);row=g.state.battlecry_history[-1]
                self.assertEqual(row.target_id,target);self.assertIsNotNone(row.native_target)
                selected=next(x for x in row.native_target.partition.candidates if x.entity_id==target)
                self.assertGreater(selected.zone_epoch,epoch)
                self.assertIn(target,g.state.players[1].board);self.assertEqual(g.state.entities[target].owner,2)
                self.portable(g)
    def test_body_failure_rolls_back_payment_rng_native_receipts_and_actual_history(self):
        g=self.game(mode='fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,ARCHER,self.target(g))
        self.assertEqual(g.snapshot(),before)
    def test_private_source_candidate_and_full_before_state_are_not_player_visible(self):
        g=self.game();self.play(g,ARCHER,self.target(g))
        for player in(1,2):
            public=json.dumps(g.observe(player))
            for hidden in(ACCEPTED,FINISHED,'native_target','rng_before','before_state','definition_digest'):
                self.assertNotIn(hidden,public)
    def test_waiting_proof_cannot_crop_candidates_or_drop_finish_after_rehash(self):
        g=self.game(mode='wait');self.play(g,ARCHER,self.target(g))
        for mode in('receipt','finish'):
            s=json.loads(json.dumps(g.snapshot()))
            if mode=='receipt':
                row=s['state']['battlecry_history'][-1]['native_target']
                row['partition']['candidates']=row['partition']['candidates'][:-1]
            else:
                def prune(value):
                    if isinstance(value,dict):
                        for key,child in list(value.items()):
                            if isinstance(child,list):value[key]=[x for x in child if not(isinstance(x,dict)and str(x.get('type','')).endswith('.FinishNativeTarget'))]
                            prune(value[key])
                    elif isinstance(value,list):
                        for child in value:prune(child)
                prune(s['resolution_frame'])
            with self.assertRaises((SnapshotError,ValueError)):
                Game.from_snapshot(rehash(s),fixture.__wrapped__('wait'))


if __name__=='__main__':unittest.main()
