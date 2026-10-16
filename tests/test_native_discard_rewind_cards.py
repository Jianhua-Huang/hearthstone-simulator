"""Real TIME_008 and strict committed discard inventory across native Rewind."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.native_discard_rewind_cards import DOOMSPEAKER, load_batch
from hs_sim.engine import CardDefinition, CardType, Game, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError
from hs_sim.engine.discard_history import discarded_cards, validate_boundary
from hs_sim.engine.effects import AddToHand, ChoiceOption, GainArmor, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import ChoicePurpose
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, DiscardCard

YETI='CORE_CS2_182'; FIRE='CORE_CS2_029'
BEFORE=Path(__file__).resolve().parent/'fixtures/native-discard-rewind-core378'


def registry():
    r=build_registry()
    r.register_behavior('k87.armor',lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition('k87.payload','Discard armor fixture',CardType.MINION,health=1,on_discard='k87.armor'))
    r.register_behavior('k87.fail',lambda c:(AddToHand(c.player_id,'unknown.k87'),))
    r.register_behavior('k87.wait',lambda c:(RequestChoice(c.player_id,(
        ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
        ChoiceOption('bad','Fail',(InvokeBehavior('k87.fail',c.source_id,c.player_id),)),
    ),source_id=c.source_id),))
    r.register_card(CardDefinition('k87.wait','Waiting discard fixture',CardType.MINION,health=1,on_discard='k87.wait'))
    r.register_behavior('k87.fail_retry',lambda c:(InvokeBehavior('k87.fail',c.source_id,c.player_id),)
        if c.state.action_number>1 else(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition('k87.fail_retry','Retry failure fixture',CardType.MINION,health=1,on_discard='k87.fail_retry'))
    r.register_behavior('k87.prior',lambda c:(DiscardCard(CardReference.capture(next(c.state.entities[i]
        for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==YETI)),c.source_id),))
    r.register_card(CardDefinition('k87.prior','Earlier discard fixture',CardType.SPELL,on_play='k87.prior'))
    return r


class NativeDiscardRewindTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()

    def game(self,hand=(DOOMSPEAKER,YETI,FIRE),enemy=(YETI,FIRE)):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=enemy,mana=10,max_mana=10),
        ),seed=31),self.r)

    def play(self,g,cid=DOOMSPEAKER):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,position=0 if self.r.card(cid).kind==CardType.MINION else None));return eid

    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())
            for key in('discard_history','rng_state','hand_entry_id','source_allocation','rewind_session'):
                self.assertNotIn(key,public)
        return other

    def test_complete_real_source_and_native_rewind_declaration(self):
        row,=load_batch()['cards'];card=self.r.card(DOOMSPEAKER)
        self.assertEqual((row['record']['dbf_id'],card.cost,card.attack,card.health),(119545,3,3,3))
        self.assertIsNotNone(card.rewind);self.assertIsNotNone(card.battlecry)

    def test_first_play_keep_has_two_physical_discards_and_one_payment(self):
        g=self.game();source=self.play(g)
        self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.REWIND)
        self.assertEqual([row.player_id for row in g.state.discard_history],[1,2])
        self.assertTrue(all(row.source_id==source for row in g.state.discard_history))
        self.choose(g,'keep');self.assertEqual(g.state.players[1].mana,7);self.portable(g)

    def test_retry_retains_diagnostic_events_but_only_final_committed_rows(self):
        g=self.game();source=self.play(g);old=tuple(row.event_sequence for row in g.state.discard_history)
        self.portable(g);self.choose(g,'retry')
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len(g.state.discard_history),2)
        self.assertEqual(sum(e.kind=='card_discarded'for e in g.events),4)
        self.assertTrue(set(old).isdisjoint(row.event_sequence for row in g.state.discard_history))
        self.assertEqual(g.state.players[1].mana,7)
        self.assertEqual(g.state.players[1].board,[source])
        self.assertEqual(len(discarded_cards(g.state,1)),1);self.assertEqual(len(discarded_cards(g.state,2)),1)
        self.portable(g)

    def test_committed_prefix_before_checkpoint_survives_retry(self):
        g=self.game((DOOMSPEAKER,'k87.prior',YETI,FIRE));self.play(g,'k87.prior')
        prefix=g.state.discard_history[0];self.play(g);self.choose(g,'retry')
        self.assertEqual(g.state.discard_history[0],prefix)
        self.assertEqual(len(g.state.discard_history),3)
        self.assertEqual(sum(e.kind=='card_discarded'for e in g.events),5)
        self.portable(g)

    def test_empty_hands_do_not_invent_discard_rows_or_use_randomness(self):
        g=self.game((DOOMSPEAKER,),());before=g.snapshot()['rng_state'];self.play(g);self.choose(g,'retry')
        self.assertEqual(g.state.discard_history,[]);self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertEqual(sum(e.kind=='card_discarded'for e in g.events),0)
        self.portable(g)

    def test_one_empty_hand_has_one_final_discard_after_retry(self):
        g=self.game((DOOMSPEAKER,),(YETI,));self.play(g);self.choose(g,'retry')
        self.assertEqual([x.player_id for x in g.state.discard_history],[2])
        self.assertEqual(sum(e.kind=='card_discarded'for e in g.events),2)

    def test_own_discard_bodies_are_reexecuted_with_one_final_reward(self):
        g=self.game((DOOMSPEAKER,'k87.payload'),('k87.payload',));self.play(g);self.choose(g,'retry')
        self.assertEqual([g.state.entities[g.state.players[p].hero_id].armor for p in(1,2)],[1,1])
        self.assertEqual(len(g.state.discard_history),2);self.portable(g)

    def test_nested_discard_waits_restore_both_players_before_and_after_retry(self):
        g=self.game((DOOMSPEAKER,'k87.wait'),('k87.wait',));self.play(g)
        self.assertEqual(g.state.pending_choice.player_id,1);self.portable(g)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        self.choose(g,'ok');self.assertEqual(g.state.pending_choice.player_id,2);self.portable(g)
        self.choose(g,'ok');self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.REWIND)
        self.choose(g,'retry');self.assertEqual(g.state.pending_choice.player_id,1)
        other=self.portable(g)
        for key in('ok','ok'):
            self.choose(g,key);self.choose(other,key)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertIsNone(g.state.pending_choice)
        self.portable(g)

    def test_late_retry_failure_rolls_back_to_original_valid_wait_and_rng(self):
        g=self.game((DOOMSPEAKER,'k87.fail_retry'),(YETI,));self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'retry')
        self.assertEqual(g.snapshot(),before)
        self.choose(g,'keep');self.portable(g)

    def test_missing_committed_row_is_still_rejected_after_rehash(self):
        g=self.game();self.play(g);self.choose(g,'retry');saved=deepcopy(g.snapshot())
        saved['state']['discard_history'].pop();saved['state']['next_discard_id']-=1
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())

    def test_unmarked_diagnostic_discard_cannot_be_ignored(self):
        g=self.game();self.play(g);self.choose(g,'keep')
        event=next(e for e in g.events if e.kind=='card_discarded')
        extra=replace(event,sequence=len(g.events)+1)
        fake=SimpleNamespace(_state=g._state,registry=g.registry,_events=[*g.events,extra])
        with self.assertRaisesRegex(ValueError,'complete committed event inventory'):validate_boundary(fake)

    def test_committed_event_must_still_match_exact_original_card(self):
        g=self.game();self.play(g);self.choose(g,'retry');row=g.state.discard_history[-1]
        events=list(g.events);events[row.event_sequence-1]=replace(events[row.event_sequence-1],target_id=g.state.players[1].hero_id)
        fake=SimpleNamespace(_state=g._state,registry=g.registry,_events=events)
        with self.assertRaisesRegex(ValueError,'actual original event'):validate_boundary(fake)

    def test_actual_old_core378_snapshots_rejected_with_same_schema303(self):
        for name,factory in(('default-core378',defaults),('constructed-v97',build_registry)):
            saved=json.loads((BEFORE/(name+'-snapshot.json')).read_text(encoding='utf-8-sig'))
            self.assertEqual(saved['schema_version'],303)
            reason = 'Mechanics version mismatch' if name == 'default-core378' else 'Registry version/fingerprint mismatch'
            with self.assertRaisesRegex(SnapshotError,reason):Game.from_snapshot(saved,factory())
