"""Same-owner-end temporary copied hand: original physical group and return."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass,CardDefinition,CardType,CostSpec,EndTurn,Game,PlayCard,PlayerSetup,
    Rarity,ResolutionError,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,Destroy,Draw,ModifyCost,RequestChoice,
    RevealHandCard,ReturnToHand,Silence)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.temporary_hands import ReplaceHandWithTemporaryCopy,ReturnTemporaryHand,validate_boundary
from hs_sim.engine.zones import AddToDeck,CardReference,MoveCard,ReorderZone
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

ILLUCIA='SCH_159'
FIXTURE=Path(__file__).resolve().parents[1]/'data/support/temporary-hand-basics.json'
PIN='606f92ef5057899af2ae0d09ed2fe9fe62be70a32194f564b5a0cb5ab68114ee'


def evidence():
    raw=json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw)!=PIN:raise ValueError('Complete temporary hand raw changed')
    row=raw['records'][0]
    if row['id']!=ILLUCIA or canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Original Illucia row changed')
    return row['data']


def registry(scripts=(), *,watch=None,fault=False):
    r=opening_registry();row=evidence()
    def illucia(c):
        work=(ReplaceHandWithTemporaryCopy(c.player_id,3-c.player_id,c.source_id),)
        return work+((AddToDeck(1,'card.1'),AddToHand(1,'missing.after.hand'))if fault else ())
    r.register_behavior('illucia',illucia)
    r.register_card(CardDefinition(ILLUCIA,row['name'],CardType.MINION,cost=row['cost'],attack=row['attack'],health=row['health'],
        battlecry='illucia',metadata=metadata(CardClass.PRIEST,rarity=Rarity.LEGENDARY,tribes=())))
    for name,callback in scripts:
        r.register_behavior(name,callback);r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,metadata=metadata()))
    if watch:
        name,event,card_id,callback=watch
        def filtered(c):
            if card_id is not None and(c.event.target_id is None or c.state.entities[c.event.target_id].card_id!=card_id):return ()
            return callback(c)
        r.register_behavior(name,filtered)
        r.register_card(CardDefinition(name,name,CardType.MINION,health=4,triggers=(TriggerSpec(event,name),),metadata=metadata()))
    return r


class TemporaryHandTests(unittest.TestCase):
    def setUp(self):self.scripts=[];self.options={}
    def script(self,name,callback):self.scripts.append((name,callback))
    def game(self,hand=(ILLUCIA,'card.1','card.2'), *,enemy_hand=('card.3','card.4'),board=(),enemy_board=(),deck=('card.9',)*5):
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,deck=deck,board=board,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',hand=enemy_hand,deck=('card.10',)*5,board=enemy_board,mana=10,max_mana=10)),seed=79),registry(self.scripts,**self.options))
    def play(self,g,cid=ILLUCIA):
        source=next(eid for eid in g.state.players[1].hand if g.state.entities[eid].card_id==cid)
        g.apply(PlayCard(1,source));return source
    def portable(self,g):
        snapshot=json.loads(json.dumps(g.snapshot()));restored=Game.from_snapshot(snapshot,registry(self.scripts,**self.options))
        self.assertEqual(restored.snapshot(),snapshot);self.assertEqual(g.clone().snapshot(),snapshot)
        self.assertEqual(replay(build_replay(g),registry(self.scripts,**self.options)).snapshot(),snapshot);return restored
    def cards(self,g,player=1):return [g.state.entities[eid].card_id for eid in g.state.players[player].hand]
    def choose(self,g):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
    def wait(self,c):return (RequestChoice(1,(ChoiceOption('ok','Continue'),),c.source_id),)
    def watch(self,event,card=None,callback=None):
        self.options['watch']=('watch',event,card,callback or self.wait)
    def invalid_boundary(self,g,change):
        bad=self.portable(g);change(bad)
        with self.assertRaises(ValueError):validate_boundary(bad)

    def test_real_illucia_saves_originals_copies_other_hand_and_returns_same_entities(self):
        g=self.game();held=tuple(g.state.players[1].hand[1:]);other=tuple(g.state.players[2].hand);rng=g._rng.getstate();source=self.play(g)
        root=g.state.temporary_hands[0];self.assertEqual(root.phase,'active');self.assertEqual(tuple(v.entity_id for v in root.originals),held)
        self.assertEqual(self.cards(g),['card.3','card.4']);self.assertEqual(tuple(g.state.players[2].hand),other)
        self.assertEqual(tuple(g.state.entities[eid].origin_entity_id for eid in g.state.players[1].hand),other)
        self.assertTrue(all(g.state.entities[eid].zone==Zone.SETASIDE for eid in held));self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(g.state.players[1].board,[source]);self.assertFalse(g.state.draw_history)
        self.portable(g);g.apply(EndTurn(1));self.assertEqual(tuple(g.state.players[1].hand),held)
        self.assertEqual(g.state.temporary_hands[0].phase,'completed');self.assertTrue(all(g.state.entities[eid].zone==Zone.SETASIDE for eid in root.introduced))
        self.portable(g)

    def test_complete_original_raw_and_current_own_hand_text(self):
        row=evidence();original=next(r for r in json.loads((FIXTURE.parents[1]/'extracted/cards.json').read_text(encoding='utf-8'))if r['id']==ILLUCIA)
        self.assertEqual(row,original);self.assertEqual((row['cost'],row['attack'],row['health']),(3,1,3))
        self.assertIn("copy of",row['text_en']);self.assertIn('end of turn',row['text_en'])

    def test_empty_other_hand_still_preserves_and_restores_originals(self):
        g=self.game(enemy_hand=());held=g.state.players[1].hand[1:];self.play(g)
        self.assertFalse(g.state.players[1].hand);self.assertFalse(g.state.temporary_hands[0].introduced)
        g.apply(EndTurn(1));self.assertEqual(g.state.players[1].hand,held);self.portable(g)

    def test_no_original_hand_restores_empty_group(self):
        g=self.game((ILLUCIA,));self.play(g);g.apply(EndTurn(1));self.assertFalse(g.state.players[1].hand)
        self.assertFalse(g.state.temporary_hands[0].returned);self.portable(g)

    def test_ten_other_cards_fit_after_original_hand_is_fully_saved(self):
        g=self.game((ILLUCIA,)+('card.1',)*9,enemy_hand=('card.3',)*10);held=g.state.players[1].hand[1:];self.play(g)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertFalse(any(e.kind=='card_burned'for e in g.events))
        g.apply(EndTurn(1));self.assertEqual(g.state.players[1].hand,held);self.portable(g)

    def test_identical_faces_remain_distinct_original_entities_and_copies(self):
        g=self.game((ILLUCIA,'card.1','card.1'),enemy_hand=('card.1','card.1'))
        held=g.state.players[1].hand[1:];other=list(g.state.players[2].hand);self.play(g)
        self.assertEqual(len(set(held+other+g.state.players[1].hand)),6);g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].hand,held);self.portable(g)

    def test_current_hand_order_is_saved_after_reordering(self):
        self.script('order',lambda c:(ReorderZone(1,Zone.HAND,tuple(reversed(c.state.players[1].hand))),))
        g=self.game(('order',ILLUCIA,'card.1','card.2'));self.play(g,'order')
        held=[eid for eid in g.state.players[1].hand if g.state.entities[eid].card_id!=ILLUCIA]
        self.play(g);g.apply(EndTurn(1));self.assertEqual(g.state.players[1].hand,held);self.portable(g)

    def test_local_original_and_current_source_cost_materials_survive(self):
        self.script('cost',lambda c:(ModifyCost(c.state.players[1].hand[-1],CostSpec(delta=-1)),
            ModifyCost(c.state.players[2].hand[0],CostSpec(delta=-1))))
        g=self.game(('cost',ILLUCIA,'card.1'));held=g.state.players[1].hand[-1];self.play(g,'cost');self.play(g)
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].cost,0)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[held].cost,0);self.portable(g)

    def test_played_replacement_minion_stays_on_board_and_does_not_return_to_hand(self):
        g=self.game();held=g.state.players[1].hand[1:];self.play(g);body=self.play(g,'card.3')
        g.apply(EndTurn(1));self.assertIn(body,g.state.players[1].board);self.assertEqual(g.state.players[1].hand,held);self.portable(g)

    def test_replacement_card_moved_to_deck_survives_hand_cleanup(self):
        self.script('move',lambda c:(MoveCard(CardReference.capture(c.state.entities[c.state.players[1].hand[-1]]),1,Zone.DECK),))
        g=self.game(enemy_hand=('move','card.3'));held=g.state.players[1].hand[1:];self.play(g)
        body=g.state.players[1].hand[-1];self.play(g,'move');g.apply(EndTurn(1))
        self.assertIn(body,g.state.players[1].deck);self.assertEqual(g.state.players[1].hand,held);self.portable(g)

    def test_newly_drawn_card_is_cleared_under_current_replace_whole_hand_policy(self):
        self.script('draw',lambda c:(Draw(1),));g=self.game(enemy_hand=('draw','card.3'))
        held=g.state.players[1].hand[1:];self.play(g);self.play(g,'draw');drawn=g.state.players[1].hand[-1]
        self.assertEqual(g.state.entities[drawn].card_id,'card.9');g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[drawn].zone,Zone.SETASIDE);self.assertEqual(g.state.players[1].hand,held);self.portable(g)

    def test_source_death_does_not_destroy_saved_original_group(self):
        self.script('kill',lambda c:(Destroy(next(eid for eid in c.state.players[1].board if c.state.entities[eid].card_id==ILLUCIA)),))
        g=self.game(enemy_hand=('kill',));held=g.state.players[1].hand[1:];source=self.play(g);self.play(g,'kill');g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(g.state.players[1].hand,held);self.portable(g)

    def test_source_silence_does_not_cancel_existing_temporary_group(self):
        self.script('silence',lambda c:(Silence(next(eid for eid in c.state.players[1].board if c.state.entities[eid].card_id==ILLUCIA)),))
        g=self.game(enemy_hand=('silence',));held=g.state.players[1].hand[1:];self.play(g);self.play(g,'silence');g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].hand,held);self.portable(g)

    def test_saved_and_cleared_cards_do_not_create_death_discard_or_draw(self):
        g=self.game(deck=());self.play(g);g.apply(EndTurn(1))
        self.assertFalse(g.state.death_history)
        self.assertFalse(any(e.kind in('card_discarded','card_destroyed_in_deck','cards_removed_from_game')for e in g.events))
        self.assertEqual(len(g.state.draw_history),1);self.assertEqual(g.state.draw_history[0].player_id,2)

    def test_return_creates_new_hand_acquisitions_for_original_physical_cards(self):
        g=self.game();held=g.state.players[1].hand[1:];old={eid:g.state.entities[eid].hand_entry_id for eid in held};self.play(g);g.apply(EndTurn(1))
        for eid in held:
            entity=g.state.entities[eid];record=g.state.hand_entries[entity.hand_entry_id-1]
            self.assertGreater(entity.hand_entry_id,old[eid]);self.assertEqual((record.from_zone,record.reason),(Zone.SETASIDE,'move'))
        self.portable(g)

    def test_same_mechanism_nested_replacements_restore_in_reverse_order(self):
        g=self.game((ILLUCIA,'card.1'),enemy_hand=(ILLUCIA,'card.3'));held=g.state.players[1].hand[1:]
        first=self.play(g);second=self.play(g);self.assertEqual(len(g.state.temporary_hands),2);g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].hand,held);self.assertEqual(g.state.players[1].board,[first,second])
        events=[e for e in g.events if e.kind=='temporary_hand_restored']
        self.assertEqual([dict(e.data)['hand_id']for e in events],[2,1]);self.portable(g)

    def test_copy_event_wait_restores_original_saved_group_and_final_copies_once(self):
        self.watch('card_added_to_hand','card.3');g=self.game(board=('watch',));self.play(g)
        self.assertIsNotNone(g.state.pending_choice);root=g.state.temporary_hands[0];self.assertEqual(len(root.introduced),2)
        restored=self.portable(g);self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        g.apply(EndTurn(1));restored.apply(EndTurn(1));self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_end_turn_wait_keeps_temporary_hand_until_after_end_subjects(self):
        self.watch('turn_ended');g=self.game(board=('watch',));self.play(g);copies=list(g.state.players[1].hand);g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].hand,copies);self.assertEqual(g.state.temporary_hands[0].phase,'active')
        restored=self.portable(g);self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_return_event_wait_commits_complete_original_group_before_reaction(self):
        self.watch('card_moved_to_hand','card.1');g=self.game(board=('watch',));held=g.state.players[1].hand[1:];self.play(g);g.apply(EndTurn(1))
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.players[1].hand,held)
        self.assertEqual(g.state.temporary_hands[0].phase,'completed');restored=self.portable(g)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_late_begin_failure_rolls_back_saved_group_new_copies_payment_and_rng(self):
        self.options['fault']=True;g=self.game();before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'missing.after.hand'):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_return_reaction_failure_rolls_back_entire_end_turn_and_hand_session(self):
        self.watch('card_moved_to_hand','card.1',lambda c:(AddToDeck(1,'card.1'),AddToHand(1,'missing.after.return')))
        g=self.game(board=('watch',));self.play(g);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'missing.after.return'):g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(),before)

    def test_terminal_game_keeps_saved_cards_private_and_marks_session_ended(self):
        self.script('lethal',lambda c:(Damage(c.state.players[2].hero_id,30,c.source_id),))
        g=self.game(enemy_hand=('lethal',));held=g.state.players[1].hand[1:];self.play(g);self.play(g,'lethal')
        self.assertEqual(g.state.status,'finished');self.assertEqual(g.state.temporary_hands[0].phase,'ended')
        self.assertTrue(all(g.state.entities[eid].zone==Zone.SETASIDE for eid in held));self.portable(g)

    def test_private_return_cannot_be_called_before_real_ending_boundary(self):
        self.script('early',lambda c:(ReturnTemporaryHand(1),));g=self.game(enemy_hand=('early',));self.play(g);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'genuine ending'):self.play(g,'early')
        self.assertEqual(g.snapshot(),before)

    def test_nonactive_player_temporary_copy_is_rejected_with_full_rollback(self):
        self.script('wrong',lambda c:(ReplaceHandWithTemporaryCopy(2,1,c.source_id),));g=self.game(('wrong',));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'active player'):self.play(g,'wrong')
        self.assertEqual(g.snapshot(),before)

    def test_invalid_requests_reject_bool_self_copy_and_unknown_source(self):
        for args in ((True,2,1),(1,1,1),(1,2,False),(3,1,1)):
            with self.subTest(args=args),self.assertRaises(ValueError):ReplaceHandWithTemporaryCopy(*args)
        self.script('missing',lambda c:(ReplaceHandWithTemporaryCopy(1,2,999999),));g=self.game(('missing',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'missing')
        self.assertEqual(g.snapshot(),before)

    def test_saved_group_cannot_reorder_original_acceptance(self):
        g=self.game();self.play(g)
        self.invalid_boundary(g,lambda bad:bad._state.temporary_hands.__setitem__(0,replace(bad._state.temporary_hands[0],originals=tuple(reversed(bad._state.temporary_hands[0].originals)))))

    def test_actual_copy_origin_and_original_acceptance_receipts_are_required(self):
        g=self.game();self.play(g)
        self.invalid_boundary(g,lambda bad:setattr(bad._state.entities[bad._state.temporary_hands[0].introduced[0]],'origin_entity_id',None))
        def lose_acceptance(bad):
            index=next(i for i,e in enumerate(bad._events)if e.kind=='temporary_hand_replaced')
            bad._events[index]=replace(bad._events[index],kind='missing.acceptance')
        self.invalid_boundary(g,lose_acceptance)

    def test_end_continuation_cannot_drop_original_expiry(self):
        self.watch('turn_ended');g=self.game(board=('watch',));self.play(g);g.apply(EndTurn(1))
        def cut(bad):
            from hs_sim.engine.resolver import ExpireTurn
            bad._frame=replace(bad._frame,prefix=tuple(v for v in bad._frame.prefix if type(v)is not ExpireTurn),
                continuation=tuple(v for v in bad._frame.continuation if type(v)is not ExpireTurn))
        self.invalid_boundary(g,cut)

    def test_actual_acceptance_cannot_lose_its_entire_private_history(self):
        g=self.game();self.play(g)
        self.invalid_boundary(g,lambda bad:bad._state.temporary_hands.clear())

    def test_snapshot_has_typed_history_and_rejects_old_schema_and_extra_fields(self):
        g=self.game();self.play(g);saved=g.snapshot();self.assertEqual((saved['schema_version'],g.ruleset.id,g.mechanics.version),(SNAPSHOT_SCHEMA_VERSION,'prototype-v302',CORE_EFFECTS_VERSION))
        for version in (1,162,163):
            bad=json.loads(json.dumps(saved));bad['schema_version']=version
            with self.subTest(version=version),self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
        bad=json.loads(json.dumps(saved));bad['state']['temporary_hands'][0]['extra']=1
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())

    def test_player_dtos_hide_original_storage_and_do_not_reveal_other_original_hand_ids(self):
        g=self.game();self.play(g);before=g.snapshot()
        own=json.dumps(g.observe(1));other=json.dumps(g.observe(2))
        self.assertIn('"card.3"',own);self.assertNotIn('"card.1"',own);self.assertNotIn('"card.1"',other)
        for view in (own,other):
            for name in('temporary_hands','SETASIDE','setaside','copied_from','originals','introduced','origin_entity_id'):self.assertNotIn(name,view)
        for p in (1,2):self.assertFalse(any(e['kind'].startswith('temporary_hand_')for e in g.player_events(p)))
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_returned_originals_are_hidden_from_other_player_and_reads_do_not_change_rng(self):
        g=self.game();self.play(g);g.apply(EndTurn(1));before=g.snapshot()
        self.assertIn('"card.1"',json.dumps(g.observe(1)));self.assertNotIn('"card.1"',json.dumps(g.observe(2)))
        for p in(1,2):g.observe(p);g.player_events(p)
        self.assertEqual(g.snapshot(),before);self.portable(g)


if __name__=='__main__':unittest.main()
