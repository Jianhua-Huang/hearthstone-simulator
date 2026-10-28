"""Independent successful discard facts; no new real-card effect adapter."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, DiscardRecord, discarded_cards,
    EndTurn, Game, Keyword, PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice,
    SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy, Draw, GainArmor, InvokeBehavior,
    RequestChoice, Summon)
from hs_sim.engine.model import validate_invariants
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash, state_from_dict, state_to_dict
from hs_sim.engine.zones import (CardReference, ChooseFromZone, CopyCard, DiscardCard,
    DiscardMatching, MoveCard, DestroyDeckCard)
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

FIXTURE=Path(__file__).resolve().parents[1]/'data/support/discard-history-basics.json'
PIN='81fc0bf2cecab8068de1766b72f22d6309a62666e8de898d4a274f71ca6eb28c'


def first(c,player=None,cid='a'):
    player=player or c.player_id
    return CardReference.capture(next(c.state.entities[i]for i in c.state.players[player].hand if c.state.entities[i].card_id==cid))


def registry(scripts=(),watchers=()):
    r=opening_registry()
    for cid,kind,fields in (('a',CardType.MINION,{'attack':1,'health':5}),('upgraded',CardType.MINION,{'attack':2,'health':6}),
            ('b',CardType.SPELL,{}),('weapon',CardType.WEAPON,{'attack':1,'durability':2}),
            ('location',CardType.LOCATION,{'durability':2,'on_use':'nothing'})):
        r.register_card(CardDefinition(cid,cid,kind,cost=1,metadata=metadata(tribes=()),**fields))
    r.register_behavior('nothing',lambda c:())
    r.register_behavior('count',lambda c:(GainArmor(c.player_id,len(discarded_cards(c.state,c.player_id))),))
    defaults=(
        ('discard',lambda c:(DiscardCard(first(c),c.source_id),)),
        ('private',lambda c:(DiscardCard(first(c),c.source_id,False),)),
        ('enemy',lambda c:(DiscardCard(first(c,3-c.player_id),c.source_id),)),
        ('multi',lambda c:(DiscardMatching(c.player_id,PoolQuery(),3,'first',c.source_id),)),
        ('random',lambda c:(DiscardMatching(c.player_id,PoolQuery(),2,'random',c.source_id),)),
        ('chosen',lambda c:(ChooseFromZone(c.player_id,c.player_id,Zone.HAND,PoolQuery(),
            'discard',None,'entity',c.source_id),)),
        ('count',lambda c:(InvokeBehavior('count',c.source_id,c.player_id),)),
        ('add.a',lambda c:(AddToHand(c.player_id,'a'),)),
        ('draw',lambda c:(Draw(c.player_id,source_id=c.source_id),)))
    for name,callback in (*defaults,*scripts):
        if name!='count':r.register_behavior(name,callback)
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,metadata=metadata()))
    for name,callback in watchers:
        r.register_behavior(name,callback)
        r.register_card(CardDefinition(name,name,CardType.MINION,health=6,
            triggers=(TriggerSpec('card_discarded',name),),metadata=metadata(tribes=())))
    return r


def rehash(s):
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
    return s


class DiscardHistoryTests(unittest.TestCase):
    def setUp(self):self.scripts=[];self.watchers=[]
    def script(self,name,callback):self.scripts.append((name,callback))
    def game(self,hand=('discard','a'),enemy_hand=(),board=(),enemy_board=(),deck=('b',)*6):
        return Game.from_scenario(Scenario((PlayerSetup('warrior.hero',hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('mage.hero',hand=enemy_hand,board=enemy_board,deck=('b',)*6,mana=10,max_mana=10)),seed=37),
            registry(self.scripts,self.watchers))
    def play(self,g,cid,player=1):
        eid=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(player,eid));return eid
    def rows(self,g,player=1,**kw):return discarded_cards(g.state,player,**kw)
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));h=Game.from_snapshot(s,registry(self.scripts,self.watchers))
        self.assertEqual(h.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry(self.scripts,self.watchers)).snapshot(),s);return h
    def choose(self,g,index=0):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(q.options[index].id,)))

    def test_three_complete_real_requirements_preserved_without_fake_adapters(self):
        raw=json.loads(FIXTURE.read_text(encoding='utf-8'));self.assertEqual(canonical_digest(raw),PIN)
        originals={r['id']:r for r in json.loads((FIXTURE.parents[1]/'extracted/cards.json').read_text(encoding='utf-8'))}
        for row in raw['records']:
            self.assertEqual(canonical_digest(row['data']),row['data_sha256']);self.assertEqual(row['data'],originals[row['id']])
        self.assertEqual({r['id']for r in raw['records']},{'ICC_841','TRL_247','NX2_017'})
        self.assertNotIn('NX2_017',registry().cards)

    def test_original_physical_card_acquisition_cause_and_event_recorded_once(self):
        g=self.game();before=g.state;eid=before.players[1].hand[-1];source=self.play(g,'discard');row=self.rows(g)[0]
        self.assertIs(type(row),DiscardRecord);self.assertEqual((row.id,row.entity_id,row.card_id,row.kind,row.player_id),(1,eid,'a',CardType.MINION,1))
        self.assertEqual(row.hand_entry_id,before.entities[eid].hand_entry_id)
        self.assertEqual((row.card.zone,row.card.zone_epoch,row.card.owner),(Zone.HAND,before.entities[eid].zone_epoch,1))
        self.assertEqual((row.source_id,row.source.card_id,row.source.zone),(source,'discard',Zone.GRAVEYARD))
        event=g.events[row.event_sequence-1];self.assertEqual((event.kind,event.target_id,event.data),('card_discarded',eid,()))
        self.assertEqual(g.state.next_discard_id,2);self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.death_history,[]);self.portable(g)

    def test_minion_spell_weapon_and_location_are_original_kinds(self):
        self.script('all',lambda c:(DiscardMatching(c.player_id,count=4,selection='first',source_id=c.source_id),))
        g=self.game(('all','a','b','weapon','location'));self.play(g,'all')
        self.assertEqual([r.kind for r in self.rows(g)],[CardType.MINION,CardType.SPELL,CardType.WEAPON,CardType.LOCATION])
        self.assertEqual([r.card_id for r in self.rows(g,kind=CardType.SPELL)],['b']);self.portable(g)

    def test_original_owner_and_current_hand_controller_are_separate(self):
        self.script('transfer',lambda c:(MoveCard(first(c),2,Zone.HAND,source_id=c.source_id),))
        g=self.game(('transfer','a'),enemy_hand=('discard',));original=g.state.players[1].hand[-1];self.play(g,'transfer');g.apply(EndTurn(1));self.play(g,'discard',2)
        row=self.rows(g,2)[0];self.assertEqual((row.entity_id,row.player_id,row.card.owner),(original,2,1));self.assertEqual(self.rows(g),());self.portable(g)

    def test_no_source_is_a_supported_original_discard(self):
        self.script('bare',lambda c:(DiscardCard(first(c)),));g=self.game(('bare','a'));self.play(g,'bare')
        self.assertIsNone(self.rows(g)[0].source);self.portable(g)

    def test_current_card_face_captured_after_stored_upgrade(self):
        from hs_sim.engine.hand_upgrades import UpgradeHandCard
        self.script('upgrade',lambda c:(UpgradeHandCard(first(c),'upgraded'),))
        g=self.game(('upgrade','chosen','a'));self.play(g,'upgrade');self.play(g,'chosen');self.choose(g)
        row=self.rows(g)[0];self.assertEqual((row.card_id,row.kind),('upgraded',CardType.MINION));self.portable(g)

    def test_same_physical_entity_can_discard_again_only_after_new_acquisition(self):
        from hs_sim.engine.hand_upgrades import UpgradeHandCard
        self.script('upgrade',lambda c:(UpgradeHandCard(first(c),'upgraded'),))
        self.script('discard.upgraded',lambda c:(DiscardCard(first(c,cid='upgraded'),c.source_id),))
        # Use the existing physical hand/deck move path after returning the
        # discarded body through the original trusted zone handler seam.
        from hs_sim.engine.resolver import default_mechanics
        from hs_sim.engine.effects import Effect
        from dataclasses import dataclass
        @dataclass(frozen=True)
        class Retrieve(Effect):entity_id:int
        def retrieve(r,e):
            entity=r.state.entities[e.entity_id]
            r.move(entity,Zone.HAND)
            # This trusted fixture seam must complete the same acquisition
            # publication required of ordinary physical hand writers.
            from hs_sim.engine.hand_history import publish
            publish(r,entity.hand_entry_id)
        self.script('retrieve.physical',lambda c:(Retrieve(c.state.discard_history[0].entity_id),))
        r=registry(self.scripts);m=default_mechanics('discard-test-effects');m.register(Retrieve,retrieve)
        scenario=Scenario((PlayerSetup('warrior.hero',hand=('discard','retrieve.physical','upgrade','discard.upgraded','a'),mana=10,max_mana=10),PlayerSetup('mage.hero')),seed=37)
        g=Game.from_scenario(scenario,r,mechanics=m);self.play(g,'discard');self.play(g,'retrieve.physical');self.play(g,'upgrade');self.play(g,'discard.upgraded')
        a,b=self.rows(g);self.assertEqual(a.entity_id,b.entity_id);self.assertNotEqual(a.hand_entry_id,b.hand_entry_id)
        self.assertEqual((a.card_id,b.card_id),('a','upgraded'))
        self.assertGreater(b.card.zone_epoch,a.card.zone_epoch);self.assertEqual(len(self.rows(g)),2)
        self.assertEqual(g.clone().snapshot(),g.snapshot())

    def test_matching_discards_requery_after_reaction_and_append_actual_order(self):
        self.watchers.append(('replace',lambda c:(AddToHand(c.player_id,'a'),)if len(discarded_cards(c.state,c.player_id))==1 else ()))
        g=self.game(('multi','a','b'),board=('replace',));self.play(g,'multi')
        self.assertEqual([r.card_id for r in self.rows(g)],['a','b','a']);self.portable(g)

    def test_random_selection_preserves_original_rng_and_replay(self):
        g=self.game(('random','a','a','b'));before=g.snapshot()['rng_state'];self.play(g,'random')
        self.assertEqual(len(self.rows(g)),2);self.assertNotEqual(g.snapshot()['rng_state'],before);self.portable(g)

    def test_empty_matching_and_stale_reference_are_not_discard_attempts(self):
        self.script('empty',lambda c:(DiscardMatching(c.player_id,PoolQuery()),))
        self.script('stale',lambda c:(MoveCard(first(c),c.player_id,Zone.DECK),DiscardCard(first(c))))
        g=self.game(('empty',));before=g.snapshot()['rng_state'];self.play(g,'empty');self.assertEqual(self.rows(g),());self.assertEqual(g.snapshot()['rng_state'],before)
        g=self.game(('stale','a'));self.play(g,'stale');self.assertEqual(self.rows(g),());self.portable(g)

    def test_original_matching_source_and_each_success_has_one_event(self):
        g=self.game(('multi','a','b','a'));source=self.play(g,'multi')
        self.assertEqual([r.source_id for r in self.rows(g)],[source]*3)
        self.assertEqual(len([e for e in g.events if e.kind=='card_discarded']),3);self.portable(g)

    def test_history_precedes_original_listener_context_and_later_obtain(self):
        self.watchers.append(('observe',lambda c:(GainArmor(c.player_id,len(discarded_cards(c.state,c.player_id))),)))
        g=self.game(('discard','a','add.a','count'),board=('observe',));self.play(g,'discard')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        self.play(g,'add.a');self.play(g,'count');self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.portable(g)

    def test_choice_before_discard_restores_without_premature_fact(self):
        g=self.game(('chosen','a','b'));self.play(g,'chosen');self.assertEqual(self.rows(g),())
        h=self.portable(g);self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(len(self.rows(g)),1);self.portable(g)

    def test_discard_listener_wait_captures_current_record_and_resumes_once(self):
        self.watchers.append(('wait',lambda c:(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),
            GainArmor(c.player_id,len(discarded_cards(c.state,c.player_id))))))
        g=self.game(board=('wait',));self.play(g,'discard');self.assertEqual(len(self.rows(g)),1)
        h=self.portable(g);self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(len(self.rows(g)),1);self.portable(g)

    def test_discard_many_wait_resumes_original_remaining_iterations(self):
        self.watchers.append(('wait',lambda c:(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),)))
        g=self.game(('multi','a','b','a'),board=('wait',));self.play(g,'multi');h=self.portable(g)
        for expected in (1,2,3):
            self.assertEqual(len(self.rows(g)),expected);self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot())
        self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_separate_turns_and_players_have_ordered_pure_filters(self):
        g=self.game(('discard','a'),enemy_hand=('discard','a'));self.play(g,'discard');g.apply(EndTurn(1));self.play(g,'discard',2)
        self.assertEqual([r.turn for r in self.rows(g)],[1]);self.assertEqual([r.turn for r in self.rows(g,2)],[2])
        self.assertEqual(self.rows(g,2,turn=1),());self.assertEqual(len(self.rows(g,turn=1)),1)
        before=g.snapshot();self.rows(g);self.rows(g,2,kind=CardType.MINION);self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_private_reveal_policy_does_not_expose_history_or_hidden_card(self):
        g=self.game(('private','a'));eid=g.state.players[1].hand[-1];self.play(g,'private');row=self.rows(g)[0]
        self.assertFalse(row.reveal);self.assertEqual(row.entity_id,eid)
        before=g.snapshot();view=g.observe(2);payload=json.dumps(view)
        self.assertNotIn('discard_history',payload);self.assertNotIn('hand_entry_id',payload);self.assertNotIn('next_discard_id',payload)
        self.assertNotIn('"card_id": "a"',payload);g.for_player(2).legal_actions();self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_public_discard_identity_visible_but_internal_proof_is_private(self):
        g=self.game();self.play(g,'discard');view=json.dumps(g.observe(2))
        self.assertIn('"card_id": "a"',view);self.assertNotIn('discard_history',view);self.assertNotIn('event_sequence',view);self.portable(g)

    def test_burn_play_and_board_death_do_not_add_discard_occurrences(self):
        self.script('kill',lambda c:(Destroy(c.state.players[1].board[0],c.source_id),))
        g=self.game(('a','kill'),board=('a',));self.play(g,'a');self.play(g,'kill');self.assertEqual(self.rows(g),())
        self.script('burn',lambda c:(AddToHand(c.player_id,'a'),AddToHand(c.player_id,'a')))
        g=self.game(('burn',)+('b',)*9);self.play(g,'burn');self.assertEqual(self.rows(g),());self.assertTrue(any(e.kind=='card_burned'for e in g.events));self.portable(g)

    def test_deck_destruction_ordinary_move_and_copy_are_not_discards(self):
        self.script('move.copy',lambda c:(CopyCard(first(c),c.player_id),MoveCard(first(c),c.player_id,Zone.DECK),
            DestroyDeckCard(CardReference.capture(c.state.entities[c.state.players[1].deck[0]]))))
        g=self.game(('move.copy','a'));self.play(g,'move.copy');self.assertEqual(self.rows(g),());self.portable(g)

    def test_late_failure_rolls_back_occurrence_inventory_cursor_rng_and_visibility(self):
        self.script('fault',lambda c:(DiscardMatching(c.player_id,PoolQuery(),2,'random',c.source_id),AddToHand(c.player_id,'missing')))
        g=self.game(('fault','a','b'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_strict_query_and_record_types(self):
        g=self.game();self.play(g,'discard');row=self.rows(g)[0]
        for p in (True,1.0,0,3):
            with self.assertRaises(ValueError):discarded_cards(g.state,p)
        for kw in ({'kind':'minion'},{'turn':True},{'turn':1.0}):
            with self.assertRaises(ValueError):discarded_cards(g.state,1,**kw)
        for kw in ({'id':True},{'player_id':1.0},{'action':False},{'reveal':1},{'card':object()},{'source':object()}):
            with self.assertRaises(ValueError):replace(row,**kw)

    def test_state_codec_requires_complete_rows_fields_and_cursor(self):
        g=self.game();self.play(g,'discard');raw=state_to_dict(g.state);self.assertEqual(state_to_dict(state_from_dict(raw)),raw)
        for field in ('discard_history','next_discard_id'):
            s=json.loads(json.dumps(g.snapshot()));del s['state'][field]
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(s),registry())
        for field in ('card','source','hand_entry_id','reveal'):
            s=json.loads(json.dumps(g.snapshot()));del s['state']['discard_history'][0][field]
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(s),registry())

    def test_rehashed_drop_duplicate_wrong_cursor_or_foreign_event_rejected(self):
        g=self.game(('multi','a','b','a'));self.play(g,'multi')
        for mutation in ('drop','duplicate','cursor','event','player','epoch','kind','entry'):
            with self.subTest(mutation=mutation):
                s=json.loads(json.dumps(g.snapshot()));rows=s['state']['discard_history']
                if mutation=='drop':rows.pop();s['state']['next_discard_id']-=1
                elif mutation=='duplicate':rows[1]=rows[0].copy()
                elif mutation=='cursor':s['state']['next_discard_id']=True
                elif mutation=='event':rows[0]['event_sequence']+=1
                elif mutation=='player':rows[0]['player_id']=2
                elif mutation=='epoch':rows[0]['card']['zone_epoch']+=1
                elif mutation=='kind':rows[0]['card']['kind']='spell'
                else:rows[0]['hand_entry_id']=rows[1]['hand_entry_id']
                with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(s),registry())

    def test_plain_state_invariants_reject_corrupted_occurrence(self):
        g=self.game();self.play(g,'discard');s=g.state;s.discard_history[0]=replace(s.discard_history[0],turn=s.turn+1)
        with self.assertRaises(ValueError):validate_invariants(s,g.registry)

    def test_original_event_player_cannot_be_bool_equal_to_numeric_identity(self):
        g=self.game();self.play(g,'discard');s=json.loads(json.dumps(g.snapshot()));row=s['state']['discard_history'][0]
        s['events'][row['event_sequence']-1]['player_id']=True;s['events_hash']=canonical_hash(s['events'])
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_current_protocol_and_old_schema_are_explicit(self):
        g=self.game();s=g.snapshot();self.assertEqual(s['schema_version'],SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(g.ruleset.id,'prototype-v302');self.assertEqual(g.mechanics.signature['version'],CORE_EFFECTS_VERSION)
        s['schema_version']=192
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_unknown_card_definition_is_not_silently_counted_or_removed(self):
        g=self.game();self.play(g,'discard');s=json.loads(json.dumps(g.snapshot()));s['state']['discard_history'][0]['card']['card_id']='missing'
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(s),registry())
