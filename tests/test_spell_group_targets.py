"""Actual joint target draws and resumable individual spell arrow windows."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
from types import SimpleNamespace
import unittest

import test_paid_spell_target_groups as base
from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError, TriggerSpec)
from hs_sim.engine.effects import (ChoiceOption, Destroy, GrantKeyword, InvokeBehavior,
    RandomDamage, RequestChoice, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import RedirectSpellTarget, SummonSpellTarget
from hs_sim.engine.model import Zone
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_group_targets import (FinishSpellGroupTargets, SettleSpellGroupArrow,
    SpellGroupArrow, validate_proof)
from hs_sim.engine.spell_group_targets import validate_boundary as validate_actual_groups

P = 'k357.'
WATCH = lambda role: P+role+'.watch'
MATERIAL = P+'current_material'


@lru_cache(maxsize=None)
def extension(role):
    def configure(r):
        r.register_card(CardDefinition(MATERIAL, MATERIAL, CardType.MINION, attack=6, health=9))
        event = 'card_committed' if role in ('one', 'empty', 'material') else 'spell_targeted'
        def reaction(c):
            window = next((x for x in c.state.action_windows if x.id == dict(c.event.data).get('window_id')), None)
            if window is None: return ()
            if role == 'scalar':
                if window.spell_target_index is not None: return ()
            elif role in ('one','empty','material'):
                if c.state.entities[c.event.source_id].card_id != base.SPELL: return ()
            else:
                wanted = 1 if role == 'wait1' else 0
                if window.spell_target_index != wanted: return ()
            enemy = c.state.players[3-window.player_id]
            if role in ('one','empty'):
                selected = enemy.board if role == 'empty' else enemy.board[1:]
                return (GrantKeyword(enemy.hero_id, Keyword.IMMUNE, c.source_id),
                    *(GrantKeyword(i, Keyword.ELUSIVE, c.source_id) for i in selected))
            if role == 'material': return (Transform(enemy.board[0], MATERIAL),)
            if role == 'drop':
                return tuple(Destroy(i) for i in c.state.players[c.player_id].board
                    if c.state.entities[i].card_id == 'CORE_CFM_670')
            if role == 'spawn':
                return (SummonSpellTarget(window.id, window.player_id, base.PLAIN),)
            if role == 'fail': return (InvokeBehavior(base.P+'fail', c.source_id, c.player_id),)
            prefix = ()
            if role == 'redirect': prefix = (RedirectSpellTarget(window.id, c.source_id),)
            if role == 'random':
                prefix = (RandomDamage((c.state.players[c.player_id].hero_id,), 1, c.source_id),)
            return (*prefix, RequestChoice(c.player_id, (
                ChoiceOption('ok','Continue'),
                ChoiceOption('fail','Fail', effects=(InvokeBehavior(base.P+'fail',c.source_id,c.player_id),))), c.source_id))
        r.register_behavior(P+role+'.reaction', reaction)
        r.register_card(CardDefinition(WATCH(role), WATCH(role), CardType.MINION, health=8,
            triggers=(TriggerSpec(event, P+role+'.reaction'),)))
    return configure


@lru_cache(maxsize=None)
def registry(role='none'):
    return base.fixture.__wrapped__('plain', 'reject', None if role=='none' else extension(role))


class ActualSpellGroupTargetTests(unittest.TestCase):
    source = base.PaidSpellTargetGroupTests.source
    action = base.PaidSpellTargetGroupTests.action
    play = base.PaidSpellTargetGroupTests.play

    def game(self, role='none', *, native=True, seat=1):
        self.role = role
        own = (() if not native else ('CORE_CFM_670',)) + (() if role=='none' else (WATCH(role),))
        players = [PlayerSetup(base.P+'hero', hand=(base.SPELL,base.P+'single',base.P+'arm'),
                              board=own, mana=10, max_mana=10),
                   PlayerSetup(base.P+'hero', board=(base.PLAIN,base.PLAIN), mana=10,max_mana=10)]
        if seat==2: players.reverse()
        return Game.from_scenario(Scenario(tuple(players),active_player=seat,seed=357),registry(role))

    def receipt(self,g):return g.state.play_history[-1].spell_target_receipt

    def choose(self,g,key='ok'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))

    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)

    def restore(self,g):
        saved=json.loads(json.dumps(g.snapshot()));reader=registry.__wrapped__(self.role)
        for other in (g.clone(),Game.from_snapshot(saved,reader),replay(build_replay(g),reader)):
            self.assertEqual(other.snapshot(),saved)
        return Game.from_snapshot(saved,reader)

    def rehash(self,value):
        value['events_hash']=canonical_hash(value['events'])
        value['state_hash']=canonical_hash({k:v for k,v in value.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        return value

    def tail(self,g):
        return next(x for x in (*g._frame.prefix,*g._frame.continuation) if type(x)is FinishSpellGroupTargets)

    def test_native_group_draws_from_complete_shared_pool_without_replacement_once(self):
        g=self.game();before=g._rng.getstate();rng=Random();rng.setstate(before)
        candidates=sorted((g.state.players[2].hero_id,*g.state.players[2].board));first=rng.choice(candidates)
        candidates.remove(first);second=rng.choice(candidates);action=self.play(g);value=self.receipt(g)
        self.assertEqual(tuple(x.entity_id for x in value.targets),(first,second))
        self.assertEqual(value.original.target_ids,action.target_ids)
        self.assertEqual(len(value.native_selections),2)
        self.assertEqual(value.native_selections[0].rng_before,before)
        self.assertEqual(value.native_selections[1].rng_after,rng.getstate())
        self.assertEqual(g._rng.getstate(),rng.getstate());self.restore(g)

    def test_ordinary_actual_source_and_targets_are_separate_from_original_hand_plan(self):
        g=self.game(native=False);before=g._rng.getstate();action=self.play(g);value=self.receipt(g)
        self.assertEqual(value.source.zone,Zone.GRAVEYARD)
        self.assertEqual(value.original.plan.source.zone,Zone.HAND)
        self.assertEqual(tuple(x.entity_id for x in value.targets),action.target_ids)
        self.assertFalse(value.native_selections);self.assertEqual(g._rng.getstate(),before)

    def test_one_live_native_candidate_preserves_two_original_positions_and_empty_second_sample(self):
        g=self.game('one');action=self.play(g);value=self.receipt(g)
        self.assertEqual(len(value.original.target_ids),2);self.assertEqual(value.original.target_ids,action.target_ids)
        self.assertIsNotNone(value.targets[0]);self.assertIsNone(value.targets[1])
        self.assertEqual(value.native_selections[1].failure,'no_target')
        self.assertEqual(value.native_selections[1].rng_before,value.native_selections[1].rng_after)
        self.assertTrue(g.state.cast_history[0].payload_started);self.restore(g)

    def test_empty_native_domain_preserves_original_input_payment_and_two_empty_proofs_without_rng(self):
        g=self.game('empty');before=g._rng.getstate();action=self.play(g);value=self.receipt(g)
        self.assertEqual(value.targets,(None,None));self.assertEqual(value.original.target_ids,action.target_ids)
        self.assertEqual(g.state.players[1].mana,9);self.assertEqual(g.state.cast_history[0].failure,'no_target')
        self.assertFalse(g.state.cast_history[0].payload_started);self.assertEqual(g._rng.getstate(),before)
        self.assertFalse(any(e.kind=='spell_targeted'for e in g.events));self.restore(g)

    def test_native_source_dies_after_first_arrow_but_second_keeps_joint_original_draw(self):
        g=self.game('drop');self.play(g);value=self.receipt(g)
        self.assertFalse(any(g.state.entities[i].card_id=='CORE_CFM_670'for i in g.state.players[1].board))
        self.assertEqual(tuple(x.entity_id for x in value.targets),tuple(x.target_id for x in value.native_selections))
        self.assertEqual(g._rng.getstate(),value.native_selections[-1].rng_after);self.restore(g)

    def test_redirection_uses_active_arrow_and_keeps_original_and_native_selections(self):
        g=self.game('redirect');action=self.play(g);value=self.receipt(g)
        watcher=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==WATCH('redirect'))
        self.assertEqual(value.targets[0].entity_id,watcher)
        self.assertEqual(value.original.target_ids,action.target_ids)
        self.assertNotEqual(value.native_selections[0].target_id,watcher)
        self.assertEqual(value.redirects[0].index,0)
        g=self.restore(g);self.finish(g);self.assertEqual(g.state.entities[watcher].health,6);self.restore(g)

    def test_summoned_redirect_target_uses_new_actual_entity_without_redrawing_other_arrow(self):
        g=self.game('spawn');self.play(g);value=self.receipt(g)
        self.assertGreaterEqual(value.targets[0].entity_id,value.source.next_entity_id)
        self.assertEqual(value.targets[1].entity_id,value.native_selections[1].target_id)
        self.assertEqual(value.redirects[0].target,value.targets[0])
        self.assertEqual(g.state.entities[value.targets[0].entity_id].health,6);self.restore(g)

    def test_first_arrow_true_wait_keeps_full_native_draws_and_one_exact_settlement_continuation(self):
        g=self.game('wait0');self.play(g);value=self.receipt(g)
        self.assertEqual(value.phase,0);self.assertEqual(g.state.action_windows[-1].spell_target_index,0)
        self.assertEqual(len(self.tail(g).proof.phase_states),1)
        self.assertEqual(len(self.tail(g).proof.settlement_states),0)
        expected=value.native_selections;g=self.restore(g);self.finish(g)
        self.assertEqual(self.receipt(g).native_selections,expected);self.assertTrue(self.receipt(g).closed);self.restore(g)

    def test_second_arrow_true_wait_preserves_first_settled_slot_and_original_full_proof(self):
        g=self.game('wait1');self.play(g);value=self.receipt(g);first=value.targets[0]
        self.assertEqual(value.phase,1);self.assertEqual(g.state.action_windows[-1].spell_target_index,1)
        self.assertEqual(len(self.tail(g).proof.settlement_states),1)
        g=self.restore(g);self.finish(g);self.assertEqual(self.receipt(g).targets[0],first);self.restore(g)

    def test_failed_choice_rolls_back_to_original_arrow_rng_and_receipt(self):
        g=self.game('redirect');self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.finish(g);self.restore(g)

    def test_later_reaction_rng_is_allowed_without_reselecting_joint_targets(self):
        g=self.game('random');self.play(g);value=self.receipt(g)
        self.assertFalse(g._rng.getstate()==value.native_selections[-1].rng_after, 'Later random reaction must consume its own draw')
        expected=value.native_selections;g=self.restore(g);self.finish(g)
        self.assertEqual(self.receipt(g).native_selections,expected);self.restore(g)

    def test_current_transformed_material_is_captured_without_printed_face_restriction(self):
        g=self.game('material',native=False);action=self.play(g);value=self.receipt(g)
        self.assertEqual(value.original.targets[1].card_id,base.PLAIN)
        self.assertEqual(value.targets[1].card_id,MATERIAL)
        self.assertEqual(value.targets[1].entity_id,action.target_ids[1])
        self.assertEqual(g.state.entities[action.target_ids[1]].health,7);self.restore(g)

    def test_target_reaction_error_restores_entire_original_payment_rng_and_group(self):
        g=self.game('fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_pending_proof_recomputes_complete_original_native_domain(self):
        g=self.game('wait0');self.play(g);proof=self.tail(g).proof;before=deepcopy(proof.before_state)
        target=before.players[2].board[-1];before.entities[target].keywords.add(Keyword.STEALTH)
        with self.assertRaises(ValueError):validate_proof(replace(proof,before_state=before),g.registry,g.mechanics)

    def test_pending_proof_cannot_drop_an_arrow_phase_or_change_its_original_submission(self):
        g=self.game('wait1');self.play(g);proof=self.tail(g).proof
        with self.assertRaises(ValueError):replace(proof,phase_states=())
        before=deepcopy(proof.before_state);window=before.action_windows[-1]
        before.action_windows[-1]=replace(window,target_id=proof.initial.original.target_ids[1])
        with self.assertRaises(ValueError):validate_proof(replace(proof,before_state=before),g.registry,g.mechanics)

    def test_closed_actual_group_cannot_be_deleted_or_reordered_with_recomputed_snapshot_hashes(self):
        g=self.game();self.play(g);saved=g.snapshot()
        for edit in ('missing','reverse'):
            bad=deepcopy(saved)
            for row in (bad['state']['play_history'][0],bad['state']['cast_history'][0]):
                if edit=='missing':row['spell_target_receipt']=None
                else:row['spell_target_receipt']['targets'].reverse()
            with self.subTest(edit=edit),self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(bad),registry(self.role))

    def test_active_arrow_index_cannot_jump_ahead_of_original_settlement_cursor(self):
        g=self.game('wait0');self.play(g);bad=g.snapshot();bad['state']['action_windows'][-1]['spell_target_index']=1
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(bad),registry(self.role))

    def test_scalar_spell_cannot_borrow_the_new_arrow_index_field(self):
        g=self.game('scalar',native=False);target=g.state.players[2].hero_id
        g.apply(PlayCard(1,self.source(g,base.P+'single'),target));self.assertIsNotNone(g.state.pending_choice)
        bad=g.snapshot();bad['state']['action_windows'][-1]['spell_target_index']=0
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(bad),registry(self.role))

    def test_second_seat_native_group_keeps_original_caster_and_actual_opponent(self):
        g=self.game(seat=2);action=self.play(g,seat=2);value=self.receipt(g)
        self.assertEqual(value.player_id,2);self.assertEqual(value.original.target_ids,action.target_ids)
        self.assertTrue(all(x.controller==1 for x in value.targets));self.restore(g)

    def test_actual_proofs_and_samples_remain_private_to_both_player_views(self):
        g=self.game('wait0');self.play(g)
        for seat in (1,2):
            data=json.dumps({'view':g.observe(seat),'events':g.player_events(seat)})
            for hidden in ('SpellGroupTargetProof','native_selections','rng_before','phase_states','definition_digest'):
                self.assertNotIn(hidden,data)

    def test_closed_settlement_cannot_keep_a_substituted_publication_event(self):
        g=self.game();self.play(g)
        events=[replace(e,kind='k357.substituted_private_event') if e.kind=='spell_targeted' and
            dict(e.data).get('spell_target_index')==0 else e for e in g._events]
        proxy=SimpleNamespace(_state=g._state,registry=g.registry,mechanics=g.mechanics,_events=events,_frame=g._frame)
        with self.assertRaises(ValueError):validate_actual_groups(proxy)

    def test_pending_proof_cannot_borrow_an_unpublished_event_with_matching_shape(self):
        g=self.game('wait0');self.play(g);tail=self.tail(g);publication=tail.proof.publications[0]
        forged=replace(publication,sequence=publication.sequence+100000)
        changed=replace(tail,proof=replace(tail.proof,publications=(forged,)))
        frame=replace(g._frame,prefix=tuple(changed if x is tail else x for x in g._frame.prefix),
            continuation=tuple(changed if x is tail else x for x in g._frame.continuation))
        proxy=SimpleNamespace(_state=g._state,registry=g.registry,mechanics=g.mechanics,_events=g._events,_frame=frame)
        with self.assertRaises(ValueError):validate_actual_groups(proxy)


if __name__=='__main__':unittest.main()
