"""Real Knockback and committed shuffle facts across native Rewind boundaries."""
from copy import deepcopy
from dataclasses import asdict,replace
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_shuffle_damage_cards import KNOCKBACK,load_batch
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.deck_shuffles import capture_cost,shuffled,validate_boundary
from hs_sim.engine.effects import AddToHand,ChoiceOption,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import RewindSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck,ShuffleDeck
from hs_sim.targets import canonical_digest

PREFIX='k135.';YETI='CORE_CS2_182';TRACKER='TLC_520'


def registry():
    r=build_registry()
    def batch(c,count=3,owner=None):
        owner=c.player_id if owner is None else owner
        return shuffled(c,(AddToDeck(owner,YETI,source_id=c.source_id)for _ in range(count)),player_id=owner)
    def fail(c):raise ResolutionError('K135 deliberate retry failure')
    def wait(c):
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue'),
            ChoiceOption('bad','Fail',(InvokeBehavior(PREFIX+'fail',c.source_id,c.player_id),)),
        ),c.source_id),)
    def paid_wait(c):
        if c.state.entities[c.event.source_id].card_id!=KNOCKBACK:return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Shuffle after payment',batch(c,1)),
            ChoiceOption('bad','Roll back insertion',(*batch(c,1),InvokeBehavior(PREFIX+'fail',c.source_id,c.player_id))),
        ),c.source_id),)
    bodies=dict(batch=batch,foreign=lambda c:batch(c,1,3-c.player_id),
        into_one=lambda c:batch(c,1,1),unknown=lambda c:(AddToDeck(c.player_id,YETI,source_id=c.source_id),),
        top=lambda c:(AddToDeck(c.player_id,YETI,'top',c.source_id),),
        bottom=lambda c:(AddToDeck(c.player_id,YETI,'bottom',c.source_id),),
        reorder=lambda c:(ShuffleDeck(c.player_id),),acquire=lambda c:(AddToHand(c.player_id,KNOCKBACK,c.source_id),),
        rewind_empty=lambda c:()if c.rewind_attempt else batch(c,2),
        rewind_again=lambda c:batch(c,2),
        rewind_fail=lambda c:(*batch(c,1),InvokeBehavior(PREFIX+'fail',c.source_id,c.player_id))if c.rewind_attempt else batch(c,1),
        rewind_wait=lambda c:(*batch(c,1),*wait(c)),fail=fail,paid_wait=paid_wait)
    for name,body in bodies.items():
        r.register_behavior(PREFIX+name,body)
        if name in('fail','paid_wait'):continue
        rewind=name.startswith('rewind_')
        r.register_card(CardDefinition(PREFIX+name,name,CardType.SPELL,cost=2 if rewind else 0,
            on_play=PREFIX+name,keywords=(Keyword.REWIND,)if rewind else(),rewind=RewindSpec()if rewind else None))
    r.register_card(CardDefinition(PREFIX+'body','Large target',CardType.MINION,attack=1,health=30))
    r.register_card(CardDefinition(PREFIX+'watch','Original paid window',CardType.MINION,health=30,
        triggers=(TriggerSpec('card_committed',PREFIX+'paid_wait'),)))
    r.validate();return r


class NativeShuffleDamageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy_hand=(),enemy=(PREFIX+'body',)):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,
            mana=40,max_mana=40,mana_cap=40,hand_cap=30),PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,
            mana=40,max_mana=40,mana_cap=40,hand_cap=30)),seed=135),self.r)
    def eid(self,g,cid,p=1,zone='hand'):
        return next(i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def target(self,g,p=2):return self.eid(g,PREFIX+'body',p,'board')
    def play(self,g,cid,p=1,target=None):
        eid=self.eid(g,cid,p);g.apply(PlayCard(p,eid,target,position=len(g.state.players[p].board)
            if g.state.entities[eid].kind==CardType.MINION else None));return eid
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return other
    def fake(self,g,events):return SimpleNamespace(_state=g._state,registry=g.registry,_events=events)
    def rehash(self,saved):
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        return saved
    def damage(self,g):return g.state.damage_history[-1].health_result

    def test_complete_original_source_primary_faces_and_native_minion_target(self):
        d=load_batch();row,=d['cards'];raw=row['record'];card=self.r.card(KNOCKBACK)
        self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(card.metadata,metadata_from_record(raw))
        self.assertEqual((card.cost,card.kind,card.spell_school),(1,CardType.SPELL,None))
        self.assertEqual((card.targeting.zones,card.targeting.kinds,card.targeting.relation),((Zone.BOARD,),(CardType.MINION,),'any'))
        self.assertEqual({o['locale']for o in d['official_observations']},{'en_US','zh_CN'})
        self.assertTrue(all(o['face']['id']==raw['dbf_id']for o in d['official_observations']))
        self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])

    def test_real_spell_base_damage_payment_spell_bonus_and_friendly_targets(self):
        for board,target_side,expected in(((),2,1),(('CORE_EX1_012',),2,2),((PREFIX+'body',),1,1)):
            with self.subTest(board=board):
                g=self.game((KNOCKBACK,),board);target=self.target(g,target_side);self.play(g,KNOCKBACK,target=target)
                self.assertEqual(g.state.entities[target].health,30-expected);self.assertEqual(g.state.players[1].mana,39)
                self.assertEqual(self.damage(g).base_amount,1)

    def test_hero_target_is_illegal_and_does_not_pay(self):
        g=self.game((KNOCKBACK,));saved=g.snapshot()
        with self.assertRaises(ValueError):self.play(g,KNOCKBACK,target=g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(),saved)

    def test_multi_card_batch_counts_once_and_separate_operations_stack(self):
        g=self.game((PREFIX+'batch',PREFIX+'batch',KNOCKBACK));self.play(g,PREFIX+'batch');self.play(g,PREFIX+'batch')
        self.assertEqual([r.declared_count for r in g.state.deck_shuffle_history],[3,3]);self.play(g,KNOCKBACK,target=self.target(g))
        self.assertEqual((capture_cost(g.state,1).quantity,self.damage(g).base_amount),(2,3))

    def test_actual_ten_raptors_are_one_credit_shared_with_existing_tracker(self):
        g=self.game(('TLC_826',KNOCKBACK,TRACKER));self.play(g,'TLC_826');self.play(g,KNOCKBACK,target=self.target(g))
        self.assertEqual(self.damage(g).base_amount,2)
        from hs_sim.engine.costs import quote_unselected_cost
        self.assertEqual(quote_unselected_cost(g.state,g.registry,g.state.entities[self.eid(g,TRACKER)]).amount,5)

    def test_original_actor_and_recipient_both_must_be_the_spell_player(self):
        g=self.game((PREFIX+'foreign',KNOCKBACK),enemy_hand=(PREFIX+'into_one',))
        self.play(g,PREFIX+'foreign');g.apply(EndTurn(1));self.play(g,PREFIX+'into_one',p=2);g.apply(EndTurn(2))
        self.assertEqual([(r.actor_id,r.player_id)for r in g.state.deck_shuffle_history],[(1,2),(2,1)])
        self.play(g,KNOCKBACK,target=self.target(g));self.assertEqual(self.damage(g).base_amount,1)

    def test_top_bottom_and_reorder_are_not_semantic_shuffles(self):
        g=self.game(tuple(PREFIX+x for x in('top','bottom','reorder'))+(KNOCKBACK,))
        for x in('top','bottom','reorder'):self.play(g,PREFIX+x)
        self.play(g,KNOCKBACK,target=self.target(g));self.assertEqual(self.damage(g).base_amount,1)
        self.assertFalse(g.state.deck_shuffle_history)

    def test_history_before_acquiring_the_spell_is_still_counted(self):
        g=self.game((PREFIX+'batch',PREFIX+'acquire'));self.play(g,PREFIX+'batch');self.play(g,PREFIX+'acquire')
        self.play(g,KNOCKBACK,target=self.target(g));self.assertEqual(self.damage(g).base_amount,2)

    def test_unknown_issuer_remains_explicitly_unsupported_and_atomic(self):
        g=self.game((PREFIX+'unknown',KNOCKBACK));self.play(g,PREFIX+'unknown');saved=g.snapshot()
        with self.assertRaisesRegex((ResolutionError,ValueError),'original issuer'):self.play(g,KNOCKBACK,target=self.target(g))
        self.assertEqual(g.snapshot(),saved)

    def test_keep_preserves_original_shuffle_while_retry_removes_only_attempted_credit(self):
        for decision,expected in(('keep',2),('retry',1)):
            with self.subTest(decision=decision):
                g=self.game((PREFIX+'batch',PREFIX+'rewind_empty',KNOCKBACK));self.play(g,PREFIX+'batch')
                prefix=g.state.deck_shuffle_history[0];self.play(g,PREFIX+'rewind_empty');rng=g._rng.getstate()
                other=self.portable(g)if decision=='retry'else None
                self.choose(g,decision);self.assertEqual(capture_cost(g.state,1).quantity,expected)
                self.assertEqual(g.state.deck_shuffle_history[0],prefix);self.assertEqual(g.state.players[1].mana,38)
                if other is not None:
                    self.choose(other,decision);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng)
                    self.assertEqual(sum(e.kind=='card_added_to_deck'for e in g.events),5)
                self.play(g,KNOCKBACK,target=self.target(g));self.assertEqual(self.damage(g).base_amount,1+expected)

    def test_retry_new_operation_reuses_restored_id_with_a_new_original_witness(self):
        g=self.game((PREFIX+'batch',PREFIX+'rewind_again',KNOCKBACK));self.play(g,PREFIX+'batch');prefix=g.state.deck_shuffle_history[0]
        self.play(g,PREFIX+'rewind_again');old=g.state.deck_shuffle_history[-1];self.choose(g,'retry')
        rows=g.state.deck_shuffle_history;self.assertEqual(rows[0],prefix);self.assertEqual(rows[-1].id,old.id)
        self.assertGreater(rows[-1].event_sequence,old.event_sequence);self.assertNotEqual(rows[-1].first_card.entity_id,old.first_card.entity_id)
        self.assertEqual(sum(e.kind=='card_added_to_deck'for e in g.events),7)
        self.play(g,KNOCKBACK,target=self.target(g));self.assertEqual(self.damage(g).base_amount,3);self.portable(g)

    def test_nested_wait_before_and_after_retry_restores_the_original_shuffle_proof(self):
        g=self.game((PREFIX+'rewind_wait',));self.play(g,PREFIX+'rewind_wait');self.portable(g)
        saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'ok');self.choose(g,'retry');other=self.portable(g)
        for x in(g,other):self.choose(x,'ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(capture_cost(g.state,1).quantity,1)
        self.assertEqual(g.state.players[1].mana,38)

    def test_retry_failure_restores_original_wait_facts_events_and_rng(self):
        g=self.game((PREFIX+'rewind_fail',));self.play(g,PREFIX+'rewind_fail');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'retry')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'keep');self.assertEqual(capture_cost(g.state,1).quantity,1)

    def test_spell_reads_actual_history_after_payment_wait_and_failed_insertion_rolls_back(self):
        g=self.game((KNOCKBACK,),board=(PREFIX+'watch',));self.play(g,KNOCKBACK,target=self.target(g));other=self.portable(g)
        self.assertEqual(g.state.players[1].mana,39);self.assertFalse(g.state.damage_history);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for x in(g,other):self.choose(x,'ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.damage(g).base_amount,2)
        self.assertEqual(g.state.players[1].mana,39)

    def test_rehashed_missing_or_rewritten_current_operation_is_rejected_after_retry(self):
        g=self.game((PREFIX+'rewind_again',));self.play(g,PREFIX+'rewind_again');self.choose(g,'retry')
        for mutation in('missing','issuer','witness'):
            with self.subTest(mutation=mutation):
                saved=deepcopy(g.snapshot());rows=saved['state']['deck_shuffle_history']
                if mutation=='missing':rows.clear()
                elif mutation=='issuer':rows[0]['actor_id']=2
                else:rows[0]['event_sequence']+=1
                with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),self.r)

    def test_without_a_real_reset_retired_insertions_cannot_be_silently_ignored(self):
        g=self.game((PREFIX+'rewind_again',));self.play(g,PREFIX+'rewind_again');self.choose(g,'retry')
        events=[e for e in g.events if e.kind!='timeline_rewound']
        with self.assertRaises(ValueError):validate_boundary(self.fake(g,events))
        events=list(g.events);index=next(i for i,e in enumerate(events)if e.kind=='timeline_rewound')
        e=events[index];events[index]=replace(e,data=tuple((k,e.sequence if k=='event_start'else v)for k,v in e.data))
        with self.assertRaisesRegex(ValueError,'future event cursor'):validate_boundary(self.fake(g,events))

    def test_current_witness_still_requires_original_target_and_member_issuer(self):
        g=self.game((PREFIX+'rewind_again',));self.play(g,PREFIX+'rewind_again');self.choose(g,'retry')
        row=g.state.deck_shuffle_history[0];events=list(g.events);event=events[row.event_sequence-1]
        events[row.event_sequence-1]=replace(event,target_id=g.state.players[1].hero_id)
        with self.assertRaisesRegex(ValueError,'first insertion'):validate_boundary(self.fake(g,events))
        events=list(g.events);data=dict(event.data);marker=list(data['deck_insertion']);marker[2]=2;data['deck_insertion']=tuple(marker)
        events[row.event_sequence-1]=replace(event,data=tuple(data.items()))
        with self.assertRaisesRegex(ValueError,'issuer or batch'):validate_boundary(self.fake(g,events))

    def test_player_views_do_not_expose_timeline_proofs_or_private_state(self):
        g=self.game((PREFIX+'rewind_again',KNOCKBACK));self.play(g,PREFIX+'rewind_again')
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('deck_shuffle_history','deck_insertion','first_card','rng_state','resolution_frame','rewind_session'):
                self.assertNotIn('"'+key+'"',public)

    def test_previous_mechanics_identity_needs_its_original_engine(self):
        g=self.game();saved=g.snapshot();saved['mechanics_version']='core-effects-v424'
        with self.assertRaisesRegex(SnapshotError,'Mechanics version mismatch'):Game.from_snapshot(saved,self.r)

    def test_old_complete_definitions_and_all_pool_metadata_remain_intact(self):
        with patch('hs_sim.cards.native_shuffle_damage_cards.register_native_shuffle_damage_cards',lambda r:None):before=build_registry()
        after=build_registry();self.assertEqual(set(after.cards)-set(before.cards),{KNOCKBACK})
        for cid,c in before.cards.items():self.assertEqual(asdict(c),asdict(after.card(cid)))
        self.assertEqual(dict(before.pool_cards),dict(after.pool_cards))
        self.assertEqual(dict(before.generation_families),dict(after.generation_families));self.assertEqual(dict(before.pools),dict(after.pools))


if __name__=='__main__':unittest.main()
