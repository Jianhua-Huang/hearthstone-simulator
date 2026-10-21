"""Efflorescence uses the real draw window and an explicitly all-CAST property."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards import build_registry as assembled
from hs_sim.cards.efflorescence_card import CARD, BODY, load_batch, register_efflorescence_card
from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError)
from hs_sim.engine.card_spell_repeats import (CardCastRepeatProof, GrantCardSpellRepeat,
    validate_automatic_proof)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, GainArmor, InvokeBehavior,
    RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardClass, CardMetadata, CastWhenDrawnSpec, Rarity,
    RepeatCostFilter, RepeatMatchSpec, SpellRepeatSpec, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.one_cost_casts import RepeatAutomaticSpell, validate_plan
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.spell_casts import CastSpell, CastStoredSpell
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face

P='fixture.efflorescence.'
NATURE,FIRE,DRAWN,FILL,DRIVER,NATIVE,REPEAT,WATCH=(P+x for x in
    ('nature','fire','drawn','fill','driver','native','repeat','watch'))
META=CardMetadata(False,(CardClass.DRUID,),Rarity.COMMON)


@lru_cache(maxsize=None)
def fixture(route='stored', mode=None, role='writer'):
    if role not in('writer','reader'):raise ValueError('Explicit independent registry role required')
    r=build_registry();register_efflorescence_card(r)
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,attack=1,health=10))
    def fail(c):raise ResolutionError('Efflorescence deliberate failure')
    r.register_behavior(P+'fail',fail)
    def nature(c):
        work=(GainArmor(c.player_id,2),)
        if mode=='wait':return(*work,RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',effects=(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),
            source_id=c.source_id))
        if mode=='fail':return(*work,InvokeBehavior(P+'fail',c.source_id,c.player_id))
        return work
    r.register_behavior(P+'nature',nature);r.register_behavior(P+'fire',lambda c:(GainArmor(c.player_id,1),))
    for cid,school,body in((NATURE,SpellSchool.NATURE,P+'nature'),(DRAWN,SpellSchool.NATURE,P+'nature'),
            (FIRE,SpellSchool.FIRE,P+'fire')):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=body,spell_school=school,metadata=META,
            keywords=(Keyword.CASTS_WHEN_DRAWN,)if cid==DRAWN else(),
            cast_when_drawn=CastWhenDrawnSpec(replacement=False,choices='player')if cid==DRAWN else None))
    r.register_card(CardDefinition(NATIVE,NATIVE,CardType.MINION,health=8,
        spell_repeats=(SpellRepeatSpec(2,class_mode='any',match=RepeatMatchSpec(
            recipient_cost=RepeatCostFilter('cast_quote',minimum=1,maximum=1))),)))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=8,
        spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
    def launch(c):
        if route in('auto','full'):
            return(*((AddToHand(c.player_id,FILL,c.source_id),)if route=='full'else()),CastSpell(c.player_id,CARD,c.source_id))
        target=next(c.state.entities[i]for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id==NATURE)
        ref=CardReference.capture(target)
        if route=='legacy':return(GrantCardSpellRepeat(ref,source_id=c.source_id),
            CastStoredSpell(ref,c.player_id,c.source_id,choices='player'))
        if route in('copy_current','copy_base'):
            return(CopyCard(ref,c.player_id,Zone.HAND,mode='current'if route=='copy_current'else'base',source_id=c.source_id),)
        if route=='reset':return(MoveCard(ref,c.player_id,Zone.DECK,reset=True,source_id=c.source_id),)
        return(CastStoredSpell(ref,c.player_id,c.source_id,choices='player'),)
    r.register_behavior(P+'launch',launch)
    r.register_card(CardDefinition(DRIVER,DRIVER,CardType.MINION,health=8,on_play=P+'launch'))
    if mode=='entry_fail':
        def watch(c):
            if c.event.target_id is not None and c.state.entities[c.event.target_id].card_id==NATURE:
                return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return()
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=8,
            triggers=(TriggerSpec('card_drawn',P+'watch'),)))
    return r


class EfflorescenceTests(unittest.TestCase):
    def game(self,route='stored',mode=None,*,deck=(NATURE,),hand=(CARD,DRIVER),board=(),seat=1):
        self.config=(route,mode);self.seat=seat
        if mode=='entry_fail':board=(*board,WATCH)
        own=PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=10,max_mana=10)
        other=PlayerSetup('HERO_01',deck=(FILL,)*6,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,seed=360),fixture(*self.config))

    def play(self,g,cid=CARD):
        pid=g.state.active_player
        eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid));return eid

    def settle(self,g):
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))

    def casts(self,g,cid=NATURE):return[x for x in g.state.cast_history if x.card_id==cid]

    def property(self,g,eid):return[a for a in g.state.entities[eid].abilities if a.kind in('card_spell_repeat','card_cast_repeat')]

    def restore(self,g,*,replay_too=True):
        saved=json.loads(json.dumps(g.snapshot()));r=fixture(*self.config,'reader')
        copies=(g.clone(),Game.from_snapshot(saved,r))
        if replay_too:copies=(*copies,replay(build_replay(g),r))
        for other in copies:self.assertTrue(other.snapshot()==saved,'Original complete draw/attachment/CAST/proof must restore exactly')
        return Game.from_snapshot(saved,r)

    def pending(self,g):return next(w for w in(*g._frame.prefix,*g._frame.continuation)if type(w)is RepeatAutomaticSpell)

    def test_full_original_two_primary_faces_druid_nature_metadata_and_assembled_definition(self):
        data=load_batch();row=data['cards'][0];raw=row['record']
        self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(raw['dbf_id'],131177)
        self.assertEqual({x['locale']for x in data['official_observations']},{'zh_CN','en_US'})
        for obs in data['official_observations']:check_face(raw,obs['face'],obs['locale'])
        r=assembled();card=r.card(CARD)
        self.assertEqual((card.cost,card.spell_school,card.metadata.classes),(2,SpellSchool.NATURE,(CardClass.DRUID,)))
        self.assertEqual(card,fixture().card(CARD));self.assertEqual(r.pool_card(CARD),fixture().pool_card(CARD))

    def test_real_paid_draw_keeps_original_carrier_source_and_installs_one_nature_property(self):
        g=self.game();target=g.state.players[1].deck[0];source=self.play(g);draw=g.state.draw_history[0]
        self.assertEqual((draw.entity_id,draw.source_id,draw.outcome),(target,source,'hand'))
        grants=self.property(g,target);self.assertEqual(len(grants),1)
        self.assertEqual((grants[0].kind,grants[0].spell_repeat.casts,grants[0].source_id),('card_cast_repeat',2,source))
        self.assertEqual(g.state.players[1].mana,8);self.restore(g)

    def test_draw_query_excludes_same_face_and_minions_but_keeps_full_physical_spell_weights(self):
        g=self.game(deck=(CARD,FILL,NATURE,FIRE,NATURE));before=g._rng.getstate();rng=Random();rng.setstate(before)
        ids=[i for i in g.state.players[1].deck if g.state.entities[i].card_id in(NATURE,FIRE)]
        expected=rng.choice(ids);self.play(g)
        self.assertEqual(g.state.draw_history[0].entity_id,expected);self.assertEqual(g._rng.getstate(),rng.getstate())
        for i in ids:
            self.assertEqual(bool(self.property(g,i)),i==expected and g.state.entities[i].card_id==NATURE)

    def test_non_nature_spell_draw_has_no_repeat_property_and_casts_normally_once(self):
        g=self.game(deck=(FIRE,));self.play(g);eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==FIRE)
        self.assertFalse(self.property(g,eid));self.play(g,FIRE)
        self.assertEqual(len(self.casts(g,FIRE)),1);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)

    def test_no_other_spell_has_no_draw_fatigue_or_rng_but_pays_original_two_mana(self):
        for deck in((),(CARD,CARD,FILL)):
            g=self.game(deck=deck);before=g._rng.getstate();self.play(g)
            self.assertFalse(g.state.draw_history);self.assertEqual(g._rng.getstate(),before)
            self.assertEqual(g.state.players[1].mana,8);self.restore(g,replay_too=False)

    def test_drawn_nature_paid_use_has_two_actual_casts_one_payment_and_no_extra_hand_play(self):
        g=self.game();self.play(g);self.play(g,NATURE)
        self.assertEqual([x.origin for x in self.casts(g)],['hand','repeat'])
        self.assertEqual((g.state.players[1].mana,len(g.state.play_history)),(7,2))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4);self.restore(g)

    def test_stored_automatic_cast_uses_new_scope_without_fabricating_a_hand_play(self):
        g=self.game();self.play(g);self.play(g,DRIVER);rows=self.casts(g)
        self.assertEqual([x.origin for x in rows],['effect','native_repeat'])
        self.assertEqual(rows[0].source_id,rows[1].source_id);self.assertEqual(len(g.state.play_history),2)
        self.assertEqual(g.state.players[1].mana,8);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4);self.restore(g)

    def test_cast_when_drawn_is_enchanted_before_original_cast_and_has_one_draw_record(self):
        g=self.game(deck=(DRAWN,));target=g.state.players[1].deck[0];self.play(g);rows=self.casts(g,DRAWN)
        self.assertEqual([x.origin for x in rows],['draw','native_repeat'])
        self.assertEqual({x.source_id for x in rows},{target});self.assertEqual(len(g.state.draw_history),1)
        self.assertEqual(g.state.draw_history[0].cast_id,rows[0].id)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4);self.restore(g)

    def test_existing_one_cost_native_and_specific_card_contributions_share_max_two_not_four(self):
        g=self.game(deck=(DRAWN,),board=(NATIVE,));self.play(g)
        self.assertEqual(len(self.casts(g,DRAWN)),2);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4)
        self.restore(g)

    def test_existing_hand_repeat_and_card_property_share_two_on_paid_use(self):
        g=self.game(deck=(NATURE,NATURE),board=(REPEAT,));self.play(g)
        # The original aura repeats Efflorescence itself and draws two distinct
        # carriers; each later hand cast still owns only max-two executions.
        self.assertEqual(len(g.state.draw_history),2);self.play(g,NATURE)
        self.assertEqual(len(self.casts(g)),2);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4)

    def test_legacy_hand_only_grants_do_not_start_new_automatic_repetition(self):
        g=self.game('legacy',deck=(),hand=(DRIVER,NATURE));self.play(g,DRIVER)
        self.assertEqual([x.origin for x in self.casts(g)],['effect'])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.restore(g)

    def test_generated_efflorescence_uses_actual_automatic_source_and_physical_draw(self):
        g=self.game('auto',hand=(DRIVER,));self.play(g,DRIVER)
        row=self.casts(g,CARD)[0];draw=g.state.draw_history[0]
        self.assertEqual((row.origin,draw.source_id),('effect',row.source_id))
        self.assertEqual(self.property(g,draw.entity_id)[0].source_id,row.source_id);self.assertEqual(g.state.players[1].mana,10)

    def test_full_hand_burn_still_records_original_draw_without_casting_the_burned_spell(self):
        g=self.game('full',deck=(DRAWN,),hand=(DRIVER,)+(FILL,)*9);target=g.state.players[1].deck[0]
        self.play(g,DRIVER);draw=g.state.draw_history[0]
        self.assertEqual((draw.entity_id,draw.outcome),(target,'burned'));self.assertFalse(self.casts(g,DRAWN))
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(len(self.property(g,target)),1);self.restore(g)

    def test_current_copy_gets_independent_property_and_base_copy_does_not(self):
        for route in('copy_current','copy_base'):
            g=self.game(route);self.play(g);original=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==NATURE)
            self.play(g,DRIVER);copies=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==NATURE and i!=original]
            self.assertEqual(len(copies),1);grants=self.property(g,copies[0])
            self.assertEqual(bool(grants),route=='copy_current')
            if grants:self.assertNotEqual(grants[0].id,self.property(g,original)[0].id)
            self.restore(g,replay_too=False)

    def test_explicit_reset_removes_the_new_property(self):
        g=self.game('reset');self.play(g);target=g.state.draw_history[0].entity_id;self.play(g,DRIVER)
        self.assertEqual(g.state.entities[target].zone,Zone.DECK);self.assertFalse(self.property(g,target));self.restore(g)

    def test_waiting_drawn_cast_and_its_second_payload_restore_one_accepted_complete_source_plan(self):
        g=self.game(mode='wait',deck=(DRAWN,));self.play(g);work=self.pending(g)
        self.assertIsInstance(work.card_proof,CardCastRepeatProof)
        g=self.restore(g);q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(self.casts(g,DRAWN)[-1].origin,'native_repeat');self.assertIsNotNone(g.state.pending_choice)
        g=self.restore(g);self.settle(g);self.assertEqual(len(g.state.draw_history),1);self.restore(g,replay_too=False)

    def test_original_property_and_provider_set_cannot_be_trimmed_in_pending_proof(self):
        g=self.game(mode='wait',deck=(DRAWN,));self.play(g);proof=self.pending(g).card_proof
        bad=deepcopy(proof.before_state);bad.entities[proof.plan.source.entity_id].abilities=[]
        with self.assertRaisesRegex(ValueError,'complete original'):
            validate_automatic_proof(replace(proof,before_state=bad),fixture(*self.config))

    def test_late_draw_error_rolls_back_original_payment_selection_grant_draw_and_rng(self):
        g=self.game(mode='entry_fail');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):self.play(g)
        self.assertTrue(g.snapshot()==before,'Failed original draw notification must roll back all material')

    def test_failed_choice_and_payload_keep_original_card_grant_and_cast_source_state_atomic(self):
        g=self.game(mode='fail',deck=(DRAWN,));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):self.play(g)
        self.assertTrue(g.snapshot()==before)
        g=self.game(mode='wait',deck=(DRAWN,));self.play(g);before=g.snapshot();q=g.state.pending_choice
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):g.apply(SelectChoice(q.player_id,q.id,('fail',)))
        self.assertTrue(g.snapshot()==before)

    def test_second_seat_keeps_actual_player_and_private_original_grant_proofs_hidden(self):
        g=self.game(mode='wait',deck=(DRAWN,),seat=2);self.play(g)
        self.assertEqual(self.casts(g,DRAWN)[0].player_id,2)
        for pid in(1,2):
            view=json.dumps(g.for_player(pid).observe(),ensure_ascii=False)
            for private in('card_proof','attachment_limit','cast_history','before_state','native_spell_repeat_accepted'):
                self.assertNotIn(private,view)
        self.restore(g)

    def test_pending_source_proof_cannot_borrow_another_zone_or_automatic_condition_clock(self):
        g=self.game(mode='wait',deck=(DRAWN,));self.play(g);work=self.pending(g);proof=work.card_proof
        before=deepcopy(proof.before_state);source=before.entities[proof.plan.source.entity_id];source.zone=Zone.HAND
        plan=replace(proof.plan,source=SourceAllocationFact.capture(before,source))
        changed=replace(work,plan=plan,card_proof=replace(proof,before_state=before,plan=plan))
        validate_automatic_proof(changed.card_proof,fixture(*self.config))
        with self.assertRaisesRegex(ValueError,'source zone'):validate_plan(g.state,fixture(*self.config),changed)
        state=deepcopy(g.state);parent=state.cast_history[work.cast_id-1]
        state.cast_history[work.cast_id-1]=replace(parent,manathirst=not parent.manathirst)
        with self.assertRaisesRegex(ValueError,'condition clocks'):validate_plan(state,fixture(*self.config),work)

    def test_pending_card_repeat_requires_the_full_original_proof_not_only_its_compact_receipt(self):
        g=self.game(mode='wait',deck=(DRAWN,));self.play(g);work=self.pending(g)
        with self.assertRaisesRegex(ValueError,'complete source proof'):
            validate_plan(g.state,fixture(*self.config),replace(work,card_proof=None))
