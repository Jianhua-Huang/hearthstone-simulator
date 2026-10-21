"""Real automatic producer entry points, full groups and retained residences."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard, PlayerSetup,
    Registry, Scenario, SelectChoice, SnapshotError, TargetSpec)
from hs_sim.engine.automatic_spell_groups import (ACCEPTED, AutomaticSpellGroupProof,
    AutomaticSpellTargets, validate_finish, validate_proof)
from hs_sim.engine.automatic_targets import AutomaticTargetPreference, PreferredMinionTarget
from hs_sim.engine.effects import (ChoiceOption, Damage, DamageBatch, Draw, InvokeBehavior,
    RequestChoice, ReturnToHand, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (BoardPresenceReference, CardClass, CardMetadata,
    CastWhenDrawnSpec, DamageKind, Rarity, RepeatCostFilter, RepeatMatchSpec, SpellRepeatSpec, Zone)
from hs_sim.engine.pools import (GenerationContext, PoolCard, PoolDefinition, PoolMember)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell, CastStoredSpell, FinishSpellCast
from hs_sim.engine.spell_history import CastFromPool, RecastFromHistory, RecastSpell, SpellHistoryQuery
from hs_sim.engine.spell_target_groups import SpellTargetGroupProfile, target_ids
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.zones import CardReference

P='k358.'
HERO,GROUP,PLAIN,DRIVER,NATIVE,MATERIAL=(P+x for x in ('hero','group','plain','driver','native','material'))
CONTEXT=GenerationContext(P+'target','experimental')


@lru_cache(maxsize=None)
def registry(route='generated', mode='plain', domain='enemy', native=False):
    r=Registry(P+route+'.'+mode+'.'+domain+'.'+str(native))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30))
    r.register_card(CardDefinition(PLAIN,PLAIN,CardType.MINION,attack=2,health=10))
    r.register_card(CardDefinition(MATERIAL,MATERIAL,CardType.MINION,attack=1,health=12))
    r.register_behavior(P+'fail',lambda c:(_ for _ in ()).throw(ResolutionError('K358 deliberate failure')))
    def body(c):
        work=(DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.SPELL)for i in target_ids(c))),)
        if mode=='fail':return (*work,InvokeBehavior(P+'fail',c.source_id,c.player_id))
        if mode=='wait':return (*work,RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',
                effects=(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),source_id=c.source_id))
        return work
    r.register_behavior(P+'body',body)
    target=TargetSpec(relation='any'if domain=='any'else'enemy',
        **({'zones':(Zone.BOARD,),'kinds':(CardType.MINION,)}if domain=='minions'else{}))
    r.register_card(CardDefinition(GROUP,GROUP,CardType.SPELL,cost=1,on_play=P+'body',targeting=target,
        metadata=CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON),
        keywords=(Keyword.CASTS_WHEN_DRAWN,)if route=='draw'else(),
        cast_when_drawn=CastWhenDrawnSpec(replacement=False,choices='player')if route=='draw'else None))
    r.register_spell_target_group_profile(SpellTargetGroupProfile(GROUP,'automatic-group-v1'))
    r.register_card(CardDefinition(NATIVE,NATIVE,CardType.MINION,health=7,
        spell_repeats=(SpellRepeatSpec(2,class_mode='any',match=RepeatMatchSpec(
            recipient_cost=RepeatCostFilter('cast_quote',minimum=1,maximum=1))),)))
    r.register_pool_card(PoolCard.from_definition(r.card(GROUP)))
    r.register_pool(PoolDefinition(P+'pool','v1',CONTEXT.target_id,CONTEXT.mode,(PoolMember(GROUP),)))
    def launch(c):
        enemy=c.state.players[3-c.player_id]
        ids=(enemy.hero_id,*enemy.board)[:2]
        kwargs={'choices':'player'}
        if route=='preferred':kwargs['target_preference']=PreferredMinionTarget(BoardPresenceReference.capture(c.state,c.source_id))
        if route=='enemy_preferred':kwargs['target_preference']=AutomaticTargetPreference.ENEMY_IF_AVAILABLE
        if route in ('explicit','bad_explicit','scalar'):
            ids=(ids[0],c.state.players[c.player_id].hero_id)if route=='bad_explicit'else ids
            kwargs.update(target_id=ids[0],targeting='explicit')
            if route!='scalar':kwargs['target_ids']=ids
        if route=='stored':
            card=next(e for e in c.state.entities.values()if e.card_id==GROUP and e.zone==Zone.HAND)
            return(CastStoredSpell(CardReference.capture(card),c.player_id,c.source_id,**kwargs),)
        if route=='deck':
            from hs_sim.engine.deck_spell_casts import CastRandomDeckSpell
            return(CastRandomDeckSpell(c.player_id,1,c.source_id),)
        if route=='draw':return(Draw(c.player_id,1,c.source_id),)
        if route=='pool':return(CastFromPool(c.player_id,P+'pool',source_id=c.source_id,choices='player'),)
        if route.startswith('history'):
            original=next(x for x in c.state.cast_history if x.card_id==GROUP)
            if route=='history_batch':return(RecastFromHistory(c.player_id,
                SpellHistoryQuery(origins=('hand',)),source_id=c.source_id,targeting='original',choices='player'),)
            retained=route!='history_random'
            work=(RecastSpell(c.player_id,original.id,c.source_id,
                targeting='original'if retained else'random',choices='player'),)
            if route=='history_bounce':return(ReturnToHand(enemy.board[0]),*work)
            if route=='history_transform':return(Transform(enemy.board[0],MATERIAL),*work)
            return work
        if route=='whole':return(ReplayWholeCards(c.player_id,c.source_id,
            WholeCardHistoryQuery(c.player_id,len(c.state.play_history),kinds=(CardType.SPELL,)),choices='player'),)
        return(CastSpell(c.player_id,GROUP,c.source_id,**kwargs),)
    r.register_behavior(P+'launch',launch)
    r.register_card(CardDefinition(DRIVER,DRIVER,CardType.MINION,health=7,on_play=P+'launch'))
    r.freeze();return r


class AutomaticSpellGroupTests(unittest.TestCase):
    def game(self, route='generated', mode='plain', domain='enemy', native=False, *, enemy=(PLAIN,PLAIN), seat=1, cross=False):
        self.config=(route,mode,domain,native)
        first=PlayerSetup(HERO,hand=(GROUP,DRIVER)if route.startswith('history')or route=='whole'else(DRIVER,),
            board=(NATIVE,)if native else(),deck=(GROUP,)if route in('deck','draw')else(),mana=10,max_mana=10)
        second=PlayerSetup(HERO,hand=(GROUP,)if cross else(),board=enemy,mana=10,max_mana=10)
        if route=='stored'and not cross:first=replace(first,hand=(GROUP,DRIVER))
        players=(first,second)if seat==1 else(second,first)
        return Game.from_scenario(Scenario(players,active_player=seat,seed=358,generation_context=CONTEXT),registry(*self.config))

    def play(self,g,card=DRIVER,seat=1):
        source=next(i for i in g.state.players[seat].hand if g.state.entities[i].card_id==card)
        targets=(g.state.players[3-seat].hero_id,g.state.players[3-seat].board[0])if card==GROUP else()
        g.apply(PlayCard(seat,source,targets[0]if targets else None,target_ids=targets));return source

    def settle(self,g):
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))

    def restore(self,g,*,replay_too=True):
        saved=json.loads(json.dumps(g.snapshot()))
        independent=registry.__wrapped__(*self.config)
        copies=(g.clone(),Game.from_snapshot(saved,independent))
        if replay_too:copies=(*copies,replay(build_replay(g),independent))
        for copy in copies:self.assertEqual(copy.snapshot(),saved)
        return Game.from_snapshot(saved,independent)

    def value(self,g):return g.state.cast_history[-1].spell_target_receipt

    def proof(self,g):return next(w.group_target_proof for w in (*g._frame.prefix,*g._frame.continuation)
        if type(w)is FinishSpellCast and w.group_target_proof is not None)

    def rehash(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
        s['events_hash']=canonical_hash(s['events']);return s

    def test_generated_group_uses_complete_shared_pool_two_distinct_draws_and_one_cast(self):
        g=self.game();before=g._rng.getstate();rng=Random();rng.setstate(before)
        ids=sorted((g.state.players[2].hero_id,*g.state.players[2].board));first=rng.choice(ids);ids.remove(first);second=rng.choice(ids)
        source=self.play(g);value=self.value(g)
        self.assertEqual(tuple(x.entity_id for x in value.targets),(first,second));self.assertEqual(g._rng.getstate(),rng.getstate())
        self.assertEqual(len(g.state.cast_history),1);self.assertEqual(g.state.cast_history[0].caster_id,source)
        self.assertEqual(g.state.players[1].mana,10);self.assertIsNone(g.state.cast_history[0].spell_target_group)
        self.assertEqual(value.source.zone,Zone.GRAVEYARD);self.assertFalse(any(e.kind=='spell_targeted'for e in g.events));self.restore(g)

    def test_explicit_vector_has_no_rng_and_rejects_illegal_second_arrow_without_partial_payload(self):
        for route in('explicit','bad_explicit'):
            g=self.game(route);before=g._rng.getstate();enemy=g.state.players[2];self.play(g);row=g.state.cast_history[-1]
            self.assertEqual(g._rng.getstate(),before)
            self.assertEqual(row.failure,'invalid_target'if route=='bad_explicit'else None)
            self.assertEqual(g.state.entities[enemy.hero_id].health,30 if route=='bad_explicit'else 28)
            self.restore(g)

    def test_scalar_cannot_silently_omit_the_second_automatic_arrow(self):
        g=self.game('scalar');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'scalar target'):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_cross_owner_stored_spell_uses_actual_executor_and_keeps_original_entity(self):
        g=self.game('stored',cross=True);original=next(e for e in g.state.entities.values()if e.card_id==GROUP)
        self.play(g);row=g.state.cast_history[-1]
        self.assertEqual((row.source_id,row.from_zone,row.player_id),(original.id,Zone.HAND,1))
        self.assertEqual((self.value(g).source.owner,self.value(g).source.controller),(2,1))
        self.assertTrue(all(x.controller==2 for x in self.value(g).targets));self.restore(g)

    def test_real_deck_cast_and_draw_cast_keep_the_physical_source_and_correct_history(self):
        for route in('deck','draw'):
            g=self.game(route);eid=g.state.players[1].deck[0];self.play(g);row=g.state.cast_history[-1]
            self.assertEqual(row.source_id,eid);self.assertEqual(row.origin,'draw'if route=='draw'else'effect')
            self.assertEqual(len(g.state.draw_history),int(route=='draw'));self.restore(g)

    def test_empty_group_fails_without_rng_and_partial_group_keeps_empty_position(self):
        for count in(0,1):
            g=self.game(domain='minions',enemy=(PLAIN,)*count);before=g._rng.getstate();self.play(g);value=self.value(g)
            self.assertEqual(len(value.targets),2);self.assertIsNone(value.targets[-1])
            self.assertEqual(value.failure,None if count else'no_target')
            if not count:self.assertEqual(g._rng.getstate(),before)
            self.assertEqual(value.selections[-1].rng_before,value.selections[-1].rng_after);self.restore(g)

    def test_preferred_original_minion_is_used_only_once_then_other_arrow_uses_remaining_domain(self):
        g=self.game('preferred',domain='any');before=g._rng.getstate();source=self.play(g);value=self.value(g)
        self.assertEqual(value.targets[0].entity_id,source)
        self.assertEqual(value.selections[0].rng_before,value.selections[0].rng_after)
        self.assertNotEqual(value.targets[1].entity_id,source)
        rng=Random();rng.setstate(before);self.assertEqual(value.targets[1].entity_id,rng.choice(value.selections[1].partition.selection_ids))
        self.assertEqual(g._rng.getstate(),rng.getstate());self.restore(g)

    def test_enemy_preference_recomputes_remaining_preferred_partition_without_duplicates(self):
        g=self.game('enemy_preferred',domain='any');self.play(g);value=self.value(g)
        self.assertTrue(all(x.controller==2 for x in value.targets));self.assertEqual(len({x.entity_id for x in value.targets}),2)
        self.restore(g)

    def test_history_original_and_batch_retain_both_targets_without_rng(self):
        for route in('history','history_batch'):
            g=self.game(route);self.play(g,GROUP);original=g.state.cast_history[0].spell_target_receipt;before=g._rng.getstate()
            self.play(g);value=self.value(g)
            self.assertEqual(tuple(x.entity_id for x in value.targets),tuple(x.entity_id for x in original.targets))
            self.assertEqual(value.retained_cast_id,1);self.assertEqual(g._rng.getstate(),before)
            self.assertEqual(g.state.cast_history[-1].origin,'history');self.restore(g)

    def test_history_random_accepts_a_fresh_complete_group_instead_of_copying_original(self):
        g=self.game('history_random');self.play(g,GROUP);before=g._rng.getstate();self.play(g);value=self.value(g)
        self.assertEqual(value.targeting,'random');self.assertIsNone(value.retained_cast_id)
        self.assertEqual(value.selections[0].rng_before,before);self.assertEqual(len(value.selections),2);self.restore(g)

    def test_retained_history_drops_departed_residence_and_accepts_current_transformed_material(self):
        for route in('history_bounce','history_transform'):
            g=self.game(route);self.play(g,GROUP);self.play(g);value=self.value(g)
            if route=='history_bounce':self.assertIsNone(value.targets[1])
            else:self.assertEqual(value.targets[1].card_id,MATERIAL)
            self.assertIsNotNone(value.targets[0]);self.restore(g)

    def test_native_repetition_reuses_full_accepted_group_without_a_second_random_window(self):
        g=self.game(native=True);self.play(g);parent,child=g.state.cast_history
        self.assertEqual([parent.origin,child.origin],['effect','native_repeat'])
        self.assertEqual(child.spell_target_receipt,parent.spell_target_receipt)
        self.assertEqual(g._rng.getstate(),parent.spell_target_receipt.selections[-1].rng_after)
        self.assertEqual(sum(e.kind==ACCEPTED for e in g.events),1);self.restore(g)

    def test_pool_generation_and_whole_card_replay_use_the_shared_complete_group(self):
        for route in('pool','whole'):
            g=self.game(route)
            if route=='whole':self.play(g,GROUP)
            self.play(g);value=self.value(g)
            self.assertIsInstance(value,AutomaticSpellTargets);self.assertEqual(len(value.targets),2);self.restore(g)

    def test_waiting_generated_draw_history_and_whole_recover_complete_original_proof(self):
        for route in('generated','draw','history','whole'):
            g=self.game(route,mode='wait')
            if route in('history','whole'):self.play(g,GROUP);self.settle(g)
            self.play(g);self.assertIsNotNone(g.state.pending_choice)
            self.assertIsInstance(self.proof(g),AutomaticSpellGroupProof)
            g=self.restore(g);self.settle(g);self.assertTrue(g.state.cast_history[-1].completed);self.restore(g,replay_too=False)

    def test_failed_choice_and_payload_restore_group_allocation_rng_and_payment(self):
        g=self.game(mode='fail');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):self.play(g)
        self.assertEqual(g.snapshot(),before)
        g=self.game(mode='wait');self.play(g);before=g.snapshot();q=g.state.pending_choice
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):g.apply(SelectChoice(q.player_id,q.id,('fail',)))
        self.assertEqual(g.snapshot(),before)

    def test_rehashed_missing_or_changed_actual_group_private_fact_is_rejected(self):
        g=self.game();self.play(g);saved=g.snapshot()
        for mode in('missing_receipt','missing_event','changed_fact'):
            bad=deepcopy(saved)
            if mode=='missing_receipt':bad['state']['cast_history'][-1]['spell_target_receipt']=None
            elif mode=='missing_event':bad['events']=[x for x in bad['events']if x['kind']!=ACCEPTED]
            else:next(x for x in bad['events']if x['kind']==ACCEPTED)['data']['cast_id']=999
            with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(bad),registry(*self.config))

    def test_pending_finish_rejects_different_original_window_and_complete_domain_crop(self):
        g=self.game('explicit',mode='wait');self.play(g);proof=self.proof(g);value=proof.receipt
        candidates=value.plan.candidates[:-1];refs=tuple(x for x in value.plan.board_presences if x.entity_id in {f.entity_id for f in candidates})
        cropped=replace(value,plan=replace(value.plan,candidates=candidates,board_presences=refs))
        with self.assertRaisesRegex(ValueError,'complete original'):validate_proof(replace(proof,receipt=cropped),registry(*self.config))
        wrong=deepcopy(proof.before_state);wrong.action_number+=1
        with self.assertRaises(ValueError):validate_proof(replace(proof,before_state=wrong),registry(*self.config))

    def test_second_seat_and_private_candidate_proofs_do_not_leak_to_player_views(self):
        g=self.game(mode='wait',seat=2);self.play(g,seat=2)
        self.assertEqual(self.value(g).player_id,2)
        for pid in(1,2):
            view=json.dumps(g.for_player(pid).observe(),ensure_ascii=False)
            for private in(ACCEPTED,'rng_before','plan','cast_history','group_target_proof'):
                self.assertNotIn(private,view)
        self.restore(g)

    def test_pending_original_proof_cannot_rewrite_earlier_physical_cast_prefix(self):
        g=self.game('history',mode='wait');self.play(g,GROUP);self.settle(g);self.play(g)
        proof=self.proof(g);before=deepcopy(proof.before_state)
        before.cast_history[0]=replace(before.cast_history[0],recorded_event=before.cast_history[0].recorded_event+1)
        changed=replace(proof,before_state=before)
        # The target calculation alone still agrees; the original prefix must
        # also be tied to the actual earlier accepted physical CAST.
        validate_proof(changed,registry(*self.config))
        with self.assertRaisesRegex(ValueError,'earlier CAST'):
            validate_finish(changed,g.state.cast_history[-1],registry(*self.config),g.state)

    def test_waiting_native_repetitions_keep_one_group_across_both_payloads(self):
        g=self.game(mode='wait',native=True);self.play(g);value=self.value(g)
        g=self.restore(g);q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.cast_history[-1].origin,'native_repeat')
        self.assertEqual(self.value(g),value);g=self.restore(g);self.settle(g)
        self.assertEqual(g._rng.getstate(),value.selections[-1].rng_after);self.restore(g,replay_too=False)

    def test_explicit_group_requests_reject_duplicate_boolean_and_mismatched_primary_input(self):
        for primary,ids in((1,(1,1)),(1,(1,True)),(2,(1,2))):
            with self.assertRaises(ValueError):CastSpell(1,GROUP,target_id=primary,targeting='explicit',target_ids=ids)
