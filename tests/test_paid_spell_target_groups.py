"""Real paid two-arrow commands and original cast binding, without a card adapter."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CounterSpell,
    DamageKind, Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Registry, Scenario,
    SecretSpec, SelectChoice, SetSecret, SnapshotError, SpellRepeatSpec, TargetSpec, TriggerSpec)
from hs_sim.engine.actions import action_from_dict, action_to_dict
from hs_sim.engine.effects import (ChoiceOption, Damage, DamageBatch, InvokeBehavior,
    RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import RedirectSpellTarget
from hs_sim.engine.model import Zone
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell, CastStoredSpell
from hs_sim.engine.spell_cost_proof import validate_hand_cost_proof
from hs_sim.engine.spell_acceptance import FinishSpellAcceptance
from hs_sim.engine.spell_target_groups import SpellTargetGroupProfile, target_ids
from hs_sim.engine.zones import CardReference

P = 'k356.'
SPELL, PLAIN, ELUSIVE, REPEAT, WATCH, SECRET = (P+x for x in ('spell', 'plain', 'elusive', 'repeat', 'watch', 'secret'))
META = CardMetadata(False, (CardClass.MAGE,), None, tribes=())


@lru_cache(maxsize=None)
def fixture(mode='plain', shortfall='reject'):
    r = Registry(P+mode+'.'+shortfall)
    r.register_card(CardDefinition(P+'hero', 'Hero', CardType.HERO, health=30))
    for cid, keywords in ((PLAIN, ()), (ELUSIVE, (Keyword.ELUSIVE,))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=3, health=8, keywords=keywords))
    r.register_card(CardDefinition(REPEAT, REPEAT, CardType.MINION, health=6,
        spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
    def fail(c):
        raise ResolutionError('K356 deliberate failure')
    r.register_behavior(P+'fail', fail)
    def body(c):
        hits = tuple(Damage(i, 2, c.source_id, DamageKind.SPELL) for i in target_ids(c))
        result = (DamageBatch(hits),)
        if mode == 'fail':
            return (*result, InvokeBehavior(P+'fail', c.source_id, c.player_id))
        if mode == 'wait':
            return (*result, RequestChoice(c.player_id, (
                ChoiceOption('ok', 'Continue'),
                ChoiceOption('fail', 'Deliberate failure', effects=(InvokeBehavior(P+'fail', c.source_id, c.player_id),))),
                source_id=c.source_id))
        return result
    r.register_behavior(P+'body', body)
    r.register_card(CardDefinition(SPELL, SPELL, CardType.SPELL, cost=1, metadata=META,
        on_play=P+'body', targeting=TargetSpec(relation='enemy')))
    r.register_spell_target_group_profile(SpellTargetGroupProfile(SPELL, 'paid-original-group-v1', shortfall=shortfall))
    scripts = {
        'auto': lambda c: (CastSpell(c.player_id, SPELL, c.source_id),),
        'stored': lambda c: (CastStoredSpell(CardReference.capture(next(c.state.entities[i]
            for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == SPELL)), c.player_id, c.source_id),),
        'arm': lambda c: (SetSecret(3-c.player_id, SECRET),),
        'single': lambda c: (Damage(c.target_id, 1, c.source_id, DamageKind.SPELL),),
    }
    for name, fn in scripts.items():
        cid=P+name; r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(relation='enemy') if name == 'single' else None))
    r.register_secret_condition(P+'counter_condition', lambda c: c.window is not None and
        c.window.kind == 'spell' and c.window.player_id != c.player_id and not c.window.countered)
    r.register_behavior(P+'counter', lambda c: (CounterSpell(c.window.id),))
    r.register_card(CardDefinition(SECRET, SECRET, CardType.SPELL, keywords=(Keyword.SECRET,),
        secret=SecretSpec(SECRET, ('card_committed',), P+'counter_condition', P+'counter'), metadata=META))
    if mode in ('redirect', 'bounce'):
        def reaction(c):
            if mode == 'redirect':
                return (RedirectSpellTarget(dict(c.event.data)['window_id'], c.state.players[2].hero_id),)
            board = c.state.players[2].board
            return (ReturnToHand(board[-1]),) if board else ()
        r.register_behavior(P+'reaction', reaction)
        r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=5,
            triggers=(TriggerSpec('spell_targeted', P+'reaction'),)))
    from hs_sim.cards.noggenfogger_card import register_noggenfogger_card
    register_noggenfogger_card(r)
    r.freeze()
    return r


class PaidSpellTargetGroupTests(unittest.TestCase):
    def game(self, mode='plain', *, shortfall='reject', board=(), enemy=(PLAIN,), seat=1, hidden=()):
        self.config = (mode, shortfall)
        players = [PlayerSetup(P+'hero', hand=(SPELL, P+'arm', P+'auto', P+'stored', P+'single'),
                              board=board, mana=10, max_mana=10),
                   PlayerSetup(P+'hero', hand=hidden, board=enemy, mana=10, max_mana=10)]
        if seat == 2:
            players.reverse()
        return Game.from_scenario(Scenario(tuple(players), active_player=seat, seed=356), fixture(*self.config))

    def source(self, g, cid=SPELL, seat=1):
        return next(i for i in g.state.players[seat].hand if g.state.entities[i].card_id == cid)

    def action(self, g, targets=None, seat=1):
        if targets is None:
            enemy=g.state.players[3-seat];targets=(enemy.hero_id, enemy.board[0])
        return PlayCard(seat, self.source(g, seat=seat), targets[0], target_ids=targets)

    def play(self, g, targets=None, seat=1):
        action=self.action(g, targets, seat);g.apply(action);return action

    def restore(self, g):
        saved=json.loads(json.dumps(g.snapshot()))
        for copy in (g.clone(), Game.from_snapshot(saved, fixture(*self.config)), replay(build_replay(g), fixture(*self.config))):
            self.assertEqual(copy.snapshot(), saved)
        return Game.from_snapshot(saved, fixture(*self.config))

    def rehash(self, saved):
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        saved['events_hash']=canonical_hash(saved['events'])
        return saved

    def test_real_paid_input_keeps_two_arrows_one_payment_one_cast_and_one_damage_batch(self):
        g=self.game();action=self.play(g)
        self.assertEqual(g.state.players[1].mana, 9)
        self.assertEqual((len(g.state.play_history), len(g.state.cast_history)), (1, 1))
        play=g.state.play_history[0];cast=g.state.cast_history[0]
        self.assertEqual(play.spell_target_group.target_ids, action.target_ids)
        self.assertEqual(cast.spell_target_group, play.spell_target_group)
        self.assertEqual(play.spell_target_group.plan.source.zone, Zone.HAND)
        self.assertEqual([g.state.entities[i].health for i in action.target_ids], [28, 6])
        self.assertEqual(tuple(e.target_id for e in g.events if e.kind=='spell_targeted'), action.target_ids)
        self.assertEqual(sum(e.kind=='spell_target_group_submitted' for e in g.events), 1)
        self.restore(g)

    def test_legal_actions_enumerate_each_complete_ordered_pair_and_never_scalar_fallback(self):
        g=self.game(enemy=(PLAIN, PLAIN));source=self.source(g)
        actions=[a for a in g.legal_actions() if type(a) is PlayCard and a.entity_id==source]
        self.assertEqual(len(actions), 6)
        self.assertEqual(len({a.target_ids for a in actions}), 6)
        self.assertTrue(all(len(a.target_ids)==2 and a.target_id==a.target_ids[0] for a in actions))

    def test_scalar_and_invalid_second_target_reject_before_payment(self):
        g=self.game(enemy=(PLAIN, ELUSIVE));before=g.snapshot();enemy=g.state.players[2]
        actions=(PlayCard(1,self.source(g),enemy.hero_id),
                 self.action(g,(enemy.hero_id,g.state.players[1].hero_id)),
                 self.action(g,(enemy.hero_id,enemy.board[-1])))
        for action in actions:
            with self.subTest(action=action), self.assertRaises(IllegalAction):g.apply(action)
            self.assertEqual(g.snapshot(),before)

    def test_unavailable_second_target_has_no_legal_exact_pair(self):
        g=self.game(enemy=());source=self.source(g);hero=g.state.players[2].hero_id
        self.assertFalse(any(type(a)is PlayCard and a.entity_id==source for a in g.legal_actions()))
        with self.assertRaises(IllegalAction):g.apply(self.action(g,(hero,)))

    def test_available_shortfall_policy_is_explicit_and_still_requires_maximum_when_available(self):
        g=self.game(shortfall='available',enemy=());hero=g.state.players[2].hero_id
        self.play(g,(hero,));self.assertEqual(g.state.entities[hero].health,28)
        g=self.game(shortfall='available');hero=g.state.players[2].hero_id
        with self.assertRaises(IllegalAction):g.apply(self.action(g,(hero,)))

    def test_classic_single_target_codec_and_play_remain_unchanged(self):
        g=self.game();target=g.state.players[2].hero_id
        action=PlayCard(1,self.source(g,P+'single'),target)
        self.assertNotIn('target_ids',action_to_dict(action))
        self.assertEqual(action_from_dict(action_to_dict(action)),action)
        g.apply(action)
        self.assertIsNone(g.state.play_history[0].spell_target_group)
        self.assertIsNone(g.state.cast_history[0].spell_target_group)
        self.assertEqual(g.state.entities[target].health,29)

    def test_group_on_undeclared_single_target_spell_is_not_accepted(self):
        g=self.game();pair=self.action(g).target_ids
        bad=PlayCard(1,self.source(g,P+'single'),pair[0],target_ids=pair)
        with self.assertRaises(IllegalAction):g.apply(bad)

    def test_full_group_json_codec_rejects_ambiguous_first_duplicate_empty_and_boolean_inputs(self):
        g=self.game();action=self.action(g);raw=action_to_dict(action)
        self.assertEqual(action_from_dict(raw),action)
        for change in ({'target_id':action.target_ids[1]}, {'target_ids':[]},
                       {'target_ids':[action.target_id,action.target_id]}, {'target_ids':[True,action.target_ids[1]]}):
            with self.subTest(change=change),self.assertRaises(ValueError):action_from_dict({**raw,**change})

    def test_player_commands_project_both_targets_as_visible_refs_and_submit_whole_vector(self):
        g=self.game();port=g.for_player(1);legal=port.legal_actions();self.assertIsNone(legal['error'])
        raw=next(a for a in legal['actions'] if a['type']=='play_card' and 'targets'in a)
        self.assertTrue(all(type(x)is str for x in raw['targets']))
        self.assertEqual(raw['target'],raw['targets'][0])
        result=port.submit({'revision':legal['revision'],'action':raw});self.assertTrue(result['accepted'],result)
        self.assertEqual(len(g.state.play_history[0].spell_target_group.target_ids),2)
        self.restore(g)

    def test_player_hidden_or_numeric_target_refs_and_inconsistent_first_ref_reject(self):
        g=self.game(hidden=(PLAIN,));port=g.for_player(1);legal=port.legal_actions()
        raw=next(a for a in legal['actions'] if a['type']=='play_card' and 'targets'in a);before=g.snapshot()
        for targets in ([raw['targets'][0],17],[raw['targets'][0],'unavailable'],list(reversed(raw['targets']))):
            result=port.submit({'revision':legal['revision'],'action':{**raw,'targets':targets}})
            self.assertFalse(result['accepted']);self.assertEqual(g.snapshot(),before)

    def test_private_submission_candidates_and_allocator_facts_do_not_enter_player_dtos(self):
        g=self.game();self.play(g)
        for seat in (1,2):
            data=json.dumps({'view':g.observe(seat),'events':g.player_events(seat)})
            for key in ('spell_target_group_submitted','definition_digest','next_entity_id','candidates'):
                self.assertNotIn(key,data)

    def test_second_seat_keeps_original_payer_and_opponent_group(self):
        g=self.game(seat=2);action=self.play(g,seat=2)
        self.assertEqual(g.state.players[2].mana,9)
        self.assertEqual(g.state.cast_history[0].spell_target_group.target_ids,action.target_ids)
        self.restore(g)

    def test_repeated_manual_casts_keep_entire_group_and_pay_only_once(self):
        g=self.game(board=(REPEAT,));action=self.play(g)
        self.assertEqual(g.state.players[1].mana,9)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(len(g.state.cast_history),2)
        self.assertTrue(all(c.spell_target_group.target_ids==action.target_ids for c in g.state.cast_history))
        self.assertEqual([g.state.entities[i].health for i in action.target_ids],[26,4])
        self.restore(g)

    def test_counter_keeps_original_group_without_target_publication_or_payload(self):
        g=self.game();g.apply(PlayCard(1,self.source(g,P+'arm')));action=self.play(g)
        cast=g.state.cast_history[-1]
        self.assertEqual(cast.failure,'countered');self.assertEqual(cast.spell_target_group.target_ids,action.target_ids)
        self.assertEqual([g.state.entities[i].health for i in action.target_ids],[30,8])
        self.assertFalse(any(e.kind=='spell_targeted'and e.source_id==action.entity_id for e in g.events))
        self.restore(g)

    def test_waiting_json_clone_replay_and_failed_choice_preserve_original_group_and_paid_cost_proof(self):
        g=self.game('wait');self.play(g);self.assertIsNotNone(g.state.pending_choice)
        g=self.restore(g);before=g.snapshot();choice=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,choice.id,('fail',)))
        self.assertEqual(g.snapshot(),before)
        g.apply(SelectChoice(1,choice.id,('ok',)));self.assertEqual(g.state.players[1].mana,9)
        self.assertTrue(g.state.cast_history[0].completed);self.restore(g)

    def test_whole_action_failure_restores_payment_group_fact_and_all_damage(self):
        g=self.game('fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_closed_group_cannot_be_deleted_or_crop_candidates_even_with_recomputed_hashes(self):
        g=self.game(enemy=(PLAIN,PLAIN));self.play(g);saved=g.snapshot()
        for change in ('missing','crop'):
            bad=deepcopy(saved)
            for row in (bad['state']['play_history'][0],bad['state']['cast_history'][0]):
                if change=='missing':row['spell_target_group']=None
                else:row['spell_target_group']['plan']['candidates'].pop()
            with self.subTest(change=change),self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(bad),fixture(*self.config))

    def test_complete_pending_payment_proof_recomputes_second_arrow_and_entire_original_inventory(self):
        g=self.game('wait',enemy=(PLAIN,PLAIN));self.play(g)
        tail=next(x for x in (*g._frame.prefix,*g._frame.continuation)if type(x)is FinishSpellAcceptance)
        proof=tail.cost_proof;group=proof.prepared_play.spell_target_group
        # Remove the unselected candidate so the vector still fits its forged plan.
        spare=next(x for x in group.plan.candidates if x.entity_id not in group.target_ids)
        bad_group=replace(group,plan=replace(group.plan,candidates=tuple(x for x in group.plan.candidates if x!=spare)))
        bad=replace(proof,prepared_play=replace(proof.prepared_play,spell_target_group=bad_group))
        with self.assertRaises(ValueError):validate_hand_cost_proof(bad,g.registry)

    def test_returned_target_is_not_damaged_in_hand_and_no_replacement_is_invented(self):
        g=self.game('bounce',board=(WATCH,));action=self.play(g)
        returned=action.target_ids[1]
        self.assertIn(returned,g.state.players[2].hand)
        self.assertEqual(g.state.entities[returned].health,8)
        self.assertEqual(g.state.entities[action.target_ids[0]].health,28)
        self.assertEqual(g.state.cast_history[0].spell_target_group.target_ids,action.target_ids)
        self.restore(g)

    def test_unimplemented_native_replacement_and_redirect_fail_without_partial_payment(self):
        for mode, board in (('plain',('CORE_CFM_670',)),('redirect',(WATCH,))):
            g=self.game(mode,board=board);before=g.snapshot()
            with self.subTest(mode=mode),self.assertRaisesRegex(ResolutionError,'not implemented'):self.play(g)
            self.assertEqual(g.snapshot(),before)

    def test_automatic_and_stored_consumers_fail_explicitly_instead_of_losing_second_target(self):
        for mode in ('auto','stored'):
            g=self.game();before=g.snapshot()
            with self.subTest(mode=mode),self.assertRaisesRegex(ResolutionError,'not implemented'):
                g.apply(PlayCard(1,self.source(g,P+mode)))
            self.assertEqual(g.snapshot(),before)

    def test_new_schema_requires_group_slots_and_rejects_old_schema(self):
        g=self.game();self.play(g);saved=g.snapshot()
        for change in ('old','missing_play','missing_cast'):
            bad=deepcopy(saved)
            if change=='old':bad['schema_version']-=1
            elif change=='missing_play':del bad['state']['play_history'][0]['spell_target_group']
            else:del bad['state']['cast_history'][0]['spell_target_group']
            with self.subTest(change=change),self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(bad),fixture(*self.config))


if __name__=='__main__':unittest.main()
