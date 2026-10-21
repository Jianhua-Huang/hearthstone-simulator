"""Flame Shock through actual paid/automatic CASTs, damage and Overload."""
from functools import lru_cache
import json
from types import SimpleNamespace
import unittest

from hs_sim.cards import build_registry as assembled
from hs_sim.cards.flame_shock_card import CARD, BODY, load_batch, register_flame_shock_card
from hs_sim.engine import (CardDefinition, CardType, CounterSpell, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, SetSecret)
from hs_sim.engine.effects import (ChoiceOption, Damage, Draw, InvokeBehavior,
    RequestChoice, ReturnToHand, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import (CardClass, Rarity, RepeatCostFilter,
    RepeatMatchSpec, SecretSpec, SpellRepeatSpec, TriggerSpec, Zone)
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell, CastStoredSpell
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face

P='fixture.flame_shock.'
FILL,SMALL,PROTECTED,IMMUNE,BONUS,REPEAT,NATIVE,DRIVER,WATCH,SECRET,MATERIAL=(P+x for x in
    ('fill','small','protected','immune','bonus','repeat','native','driver','watch','secret','material'))


@lru_cache(maxsize=None)
def fixture(route='auto', mode=None, role='writer'):
    if role not in ('writer','reader'):raise ValueError('Explicit independent registry role required')
    r=build_registry();register_flame_shock_card(r)
    for cid,health,keywords in((FILL,10,()),(SMALL,2,()),
            (PROTECTED,10,(Keyword.STEALTH,Keyword.ELUSIVE)),(IMMUNE,10,(Keyword.IMMUNE,)),(MATERIAL,9,())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=2,health=health,keywords=keywords))
    r.register_card(CardDefinition(BONUS,BONUS,CardType.MINION,health=7,spell_damage=1))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=7,
        spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
    r.register_card(CardDefinition(NATIVE,NATIVE,CardType.MINION,health=7,
        spell_repeats=(SpellRepeatSpec(2,class_mode='any',match=RepeatMatchSpec(
            recipient_cost=RepeatCostFilter('cast_quote',minimum=1,maximum=1))),)))
    def fail(c):raise ResolutionError('Flame Shock deliberate failure')
    r.register_behavior(P+'fail',fail)
    def launch(c):
        enemy=c.state.players[3-c.player_id]
        if route=='wound':return(Damage(enemy.hero_id,28,c.source_id),)
        if route=='draw':return(Draw(c.player_id,1,c.source_id),)
        if route.startswith('history'):
            original=next(x for x in c.state.cast_history if x.card_id==CARD)
            return(RecastSpell(c.player_id,original.id,c.source_id,
                targeting='random'if route=='history_random'else'original'),)
        if route in('stored','deck'):
            zone=Zone.HAND if route=='stored'else Zone.DECK
            entity=next(e for e in c.state.entities.values()if e.card_id==CARD and e.zone==zone)
            return(CastStoredSpell(CardReference.capture(entity),c.player_id,c.source_id),)
        if route=='explicit_bad':return(CastSpell(c.player_id,CARD,c.source_id,enemy.hero_id,
            targeting='explicit',target_ids=(enemy.hero_id,c.state.players[c.player_id].hero_id)),)
        return(CastSpell(c.player_id,CARD,c.source_id),)
    r.register_behavior(P+'launch',launch)
    r.register_card(CardDefinition(DRIVER,DRIVER,CardType.MINION,health=10,on_play=P+'launch'))
    r.register_behavior(P+'arm',lambda c:(SetSecret(3-c.player_id,SECRET),))
    r.register_card(CardDefinition(P+'arm',P+'arm',CardType.SPELL,on_play=P+'arm'))
    r.register_secret_condition(P+'counter_condition',lambda c:c.window is not None and
        c.window.kind=='spell'and c.window.player_id!=c.player_id and not c.window.countered)
    r.register_behavior(P+'counter',lambda c:(CounterSpell(c.window.id),))
    r.register_card(CardDefinition(SECRET,SECRET,CardType.SPELL,keywords=(Keyword.SECRET,),
        secret=SecretSpec(SECRET,('card_committed',),P+'counter_condition',P+'counter')))
    if mode:
        if mode not in('arrow','overload','late_fail','bounce','transform'):raise ValueError('Explicit observation mode required')
        event='spell_targeted'if mode=='arrow'else'spell_cast_started'if mode in('bounce','transform')else'overload_added'
        def condition(c):
            if mode in('overload','late_fail'):return c.event.player_id!=c.player_id
            return(c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==CARD and
                (mode!='arrow'or dict(c.event.data).get('spell_target_index')==1))
        def react(c):
            if not condition(c):return ()
            if mode=='late_fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode in('bounce','transform'):
                cast=next(x for x in reversed(c.state.cast_history)if x.source_id==c.event.source_id)
                facts=cast.spell_target_receipt.targets
                return tuple(ReturnToHand(x.entity_id)if mode=='bounce'else Transform(x.entity_id,MATERIAL)
                    for x in facts if x is not None and x.kind==CardType.MINION)
            return(RequestChoice(c.player_id,(
                ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',effects=(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),
                source_id=c.source_id),)
        r.register_behavior(P+'react',react)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,
            triggers=(TriggerSpec(event,P+'react'),)))
    return r


class FlameShockTests(unittest.TestCase):
    def game(self, route='auto', mode=None, *, hand=(CARD,DRIVER), board=(), enemy=(FILL,), seat=1, cross=False):
        self.config=(route,mode);self.seat=seat
        if mode:enemy=(*enemy,WATCH)
        own=PlayerSetup('HERO_08',hand=hand,board=board,deck=(CARD,)if route in('deck','draw')else(FILL,)*8,mana=10,max_mana=10)
        other=PlayerSetup('HERO_01',hand=(CARD,)if cross else(DRIVER,),board=enemy,deck=(FILL,)*8,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,seed=359),fixture(*self.config))

    def play(self,g,cid=CARD,targets=None,seat=None):
        pid=g.state.active_player if seat is None else seat
        source=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        if cid==CARD:
            enemy=g.state.players[3-pid]
            targets=(enemy.hero_id,enemy.board[0])if targets is None else targets
            g.apply(PlayCard(pid,source,targets[0],target_ids=targets))
        else:g.apply(PlayCard(pid,source))
        return source

    def casts(self,g):return[x for x in g.state.cast_history if x.card_id==CARD]

    def settle(self,g):
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))

    def restore(self,g,*,replay_too=True):
        saved=json.loads(json.dumps(g.snapshot()));r=fixture(*self.config,'reader')
        copies=(g.clone(),Game.from_snapshot(saved,r))
        if replay_too:copies=(*copies,replay(build_replay(g),r))
        for other in copies:self.assertTrue(other.snapshot()==saved,'Full state/events/proof must restore exactly')
        return Game.from_snapshot(saved,r)

    def test_complete_original_and_two_primary_faces_metadata_and_unknown_tags_preserved(self):
        data=load_batch();row=data['cards'][0];raw=row['record']
        self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(raw['dbf_id'],130974)
        self.assertEqual({x['locale']for x in data['official_observations']},{'zh_CN','en_US'})
        for obs in data['official_observations']:check_face(raw,obs['face'],obs['locale'])
        card=fixture().card(CARD)
        self.assertEqual((card.cost,card.spell_school.value,card.metadata.classes,card.metadata.rarity),
            (1,'fire',(CardClass.SHAMAN,),Rarity.RARE))
        self.assertEqual(set(data['uninterpreted_source_tag_ids']),{1724,2731});self.assertFalse(data['cn_calibrated'])

    def test_paid_cast_hits_two_different_enemies_in_one_batch_and_adds_one_overload(self):
        g=self.game();enemy=g.state.players[2];ids=(enemy.hero_id,enemy.board[0]);source=self.play(g)
        self.assertEqual([g.state.entities[i].health for i in ids],[28,8])
        self.assertEqual((g.state.players[1].mana,g.state.players[1].overload_owed),(9,1))
        self.assertEqual((len(self.casts(g)),len(g.state.overload_history)),(1,1))
        results=[health_result(e)for e in g.events if e.kind=='health_resolved'and e.source_id==source]
        self.assertEqual(len(results),2);self.assertEqual(results[0].batch_id,results[1].batch_id);self.restore(g)

    def test_two_selected_minions_die_from_one_health_batch(self):
        g=self.game(enemy=(SMALL,SMALL));ids=tuple(g.state.players[2].board);source=self.play(g,targets=ids)
        self.assertFalse(g.state.players[2].board);self.assertEqual(g.state.players[1].overload_owed,1)
        results=[health_result(e)for e in g.events if e.kind=='health_resolved'and e.source_id==source]
        self.assertEqual(len({x.batch_id for x in results}),1);self.assertEqual(len(g.state.death_history),2)

    def test_full_ordered_pair_commands_reject_duplicate_and_friendly_target_before_payment(self):
        g=self.game(enemy=(FILL,FILL));source=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==CARD)
        legal=[a for a in g.legal_actions()if type(a)is PlayCard and a.entity_id==source]
        self.assertEqual(len(legal),6);before=g.snapshot();enemy=g.state.players[2].hero_id
        with self.assertRaises(ValueError):PlayCard(1,source,enemy,target_ids=(enemy,enemy))
        with self.assertRaises(IllegalAction):
            g.apply(PlayCard(1,source,enemy,target_ids=(enemy,g.state.players[1].hero_id)))
        self.assertTrue(g.snapshot()==before)

    def test_local_exact_two_manual_policy_and_partial_automatic_group_are_recorded_separately(self):
        g=self.game(enemy=());source=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==CARD)
        self.assertFalse(any(type(a)is PlayCard and a.entity_id==source for a in g.legal_actions()))
        self.play(g,DRIVER);row=self.casts(g)[0]
        self.assertEqual(len(row.spell_target_receipt.targets),2);self.assertIsNone(row.spell_target_receipt.targets[1])
        self.assertEqual(g.state.players[1].overload_owed,1);self.restore(g)

    def test_automatic_protection_policy_does_not_become_manual_target_permission(self):
        g=self.game(enemy=(PROTECTED,));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g)
        self.assertTrue(g.snapshot()==before);self.play(g,DRIVER)
        target=g.state.players[2].board[0];self.assertEqual(g.state.entities[target].health,8)
        self.assertEqual(g.state.players[1].overload_owed,1)

    def test_immune_auto_target_still_prevents_damage_and_spell_damage_applies_per_live_arrow(self):
        g=self.game(enemy=(IMMUNE,));self.play(g,DRIVER)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,10)
        self.assertEqual(g.state.players[1].overload_owed,1)
        g=self.game(board=(BONUS,));self.play(g)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,7)
        self.assertEqual(g.state.players[1].overload_owed,1)

    def test_manual_repeat_is_two_physical_casts_two_overloads_and_one_payment(self):
        g=self.game(board=(REPEAT,));self.play(g)
        self.assertEqual([x.origin for x in self.casts(g)],['hand','repeat'])
        self.assertEqual((g.state.players[1].mana,g.state.players[1].overload_owed),(9,2))
        self.assertEqual(len(g.state.overload_history),2);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,26)
        self.restore(g)

    def test_overload_uses_existing_next_own_turn_lock(self):
        g=self.game();self.play(g);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual((g.state.players[1].overload_owed,g.state.players[1].overload_locked,g.state.players[1].mana),(0,1,9))
        self.restore(g)

    def test_countered_attempt_keeps_original_pair_and_payment_without_damage_or_overload(self):
        g=self.game(hand=(P+'arm',CARD,DRIVER));self.play(g,P+'arm');self.play(g);row=self.casts(g)[0]
        self.assertEqual(row.failure,'countered');self.assertEqual(len(row.spell_target_group.target_ids),2)
        self.assertIsNone(row.spell_target_receipt);self.assertEqual(g.state.players[1].overload_owed,0)
        self.assertEqual(g.state.players[1].mana,9);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30);self.restore(g)

    def test_historical_original_can_inherit_complete_countered_hand_submission(self):
        g=self.game('history',hand=(P+'arm',CARD,DRIVER));self.play(g,P+'arm');self.play(g);original=self.casts(g)[0]
        before=g._rng.getstate();self.play(g,DRIVER);child=self.casts(g)[-1]
        self.assertEqual(child.spell_target_receipt.submitted_ids,original.spell_target_group.target_ids)
        self.assertEqual(child.recast_id,original.id);self.assertEqual(g._rng.getstate(),before)
        self.assertEqual(g.state.players[1].overload_owed,1);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28);self.restore(g)

    def test_history_original_keeps_both_targets_and_random_accepts_a_new_group(self):
        for route in('history','history_random'):
            g=self.game(route,enemy=(FILL,FILL));self.play(g);before=g._rng.getstate();self.play(g,DRIVER)
            row=self.casts(g)[-1];value=row.spell_target_receipt
            self.assertEqual(value.targeting,'random'if route=='history_random'else'original')
            if route=='history':self.assertEqual(g._rng.getstate(),before)
            else:self.assertEqual(value.selections[0].rng_before,before)
            self.assertEqual(g.state.players[1].overload_owed,2);self.restore(g)

    def test_opponent_history_original_does_not_turn_old_friendly_targets_into_new_enemies(self):
        g=self.game('history');self.play(g);g.apply(EndTurn(1));before=g._rng.getstate();self.play(g,DRIVER)
        row=self.casts(g)[-1];self.assertEqual((row.player_id,row.failure),(2,'no_target'))
        self.assertEqual(row.spell_target_receipt.targets,(None,None));self.assertEqual(g._rng.getstate(),before)
        self.assertEqual(g.state.players[2].overload_owed,0);self.restore(g)

    def test_native_repeat_of_history_retains_the_full_group_and_each_completed_payload_overloads_once(self):
        g=self.game('history',board=(NATIVE,));self.play(g);before=g._rng.getstate();self.play(g,DRIVER)
        rows=self.casts(g);self.assertEqual([x.origin for x in rows],['hand','repeat','history','native_repeat'])
        self.assertEqual(rows[-1].spell_target_receipt,rows[-2].spell_target_receipt)
        self.assertEqual(g._rng.getstate(),before);self.assertEqual(g.state.players[1].overload_owed,4);self.restore(g)

    def test_generated_and_foreign_stored_casts_keep_actual_source_and_one_overload(self):
        for route in('auto','stored'):
            g=self.game(route,hand=(DRIVER,),cross=route=='stored');source=self.play(g,DRIVER);row=self.casts(g)[0]
            self.assertEqual(row.caster_id,source);self.assertEqual(row.origin,'effect')
            self.assertEqual(row.from_zone,Zone.HAND if route=='stored'else None)
            if route=='stored':self.assertEqual(row.spell_target_receipt.source.owner,2)
            self.assertEqual((g.state.players[1].mana,g.state.players[1].overload_owed),(10,1));self.restore(g)

    def test_physical_deck_cast_is_not_a_draw_and_ordinary_draw_does_not_cast_this_card(self):
        for route in('deck','draw'):
            g=self.game(route,hand=(DRIVER,));original=g.state.players[1].deck[0];self.play(g,DRIVER)
            self.assertEqual(len(self.casts(g)),int(route=='deck'))
            self.assertEqual(g.state.players[1].overload_owed,int(route=='deck'))
            self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD if route=='deck'else Zone.HAND)
            self.assertEqual(len(g.state.draw_history),int(route=='draw'));self.restore(g)

    def test_explicit_illegal_second_arrow_has_no_partial_damage_or_overload(self):
        g=self.game('explicit_bad');self.play(g,DRIVER);row=self.casts(g)[0]
        self.assertEqual(row.failure,'invalid_target');self.assertEqual(g.state.players[1].overload_owed,0)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)

    def test_second_arrow_wait_restores_original_payment_before_damage_and_overload(self):
        g=self.game(mode='arrow');self.play(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((g.state.players[1].mana,g.state.players[1].overload_owed),(9,0))
        g=self.restore(g);self.settle(g);self.assertEqual(g.state.players[1].overload_owed,1);self.restore(g,replay_too=False)

    def test_wait_after_overload_preserves_damage_pending_mana_and_original_cast_completion(self):
        for route in('auto','history'):
            g=self.game(route,mode='overload')
            if route=='history':self.play(g);self.settle(g)
            self.play(g,DRIVER);self.assertIsNotNone(g.state.pending_choice)
            self.assertEqual(g.state.pending_choice.player_id,2);self.assertFalse(self.casts(g)[-1].completed)
            g=self.restore(g);self.settle(g);self.assertTrue(self.casts(g)[-1].completed)

    def test_late_error_and_failed_opponent_choice_roll_back_damage_overload_rng_and_original_action(self):
        g=self.game(mode='late_fail');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):self.play(g)
        self.assertTrue(g.snapshot()==before,'Late failure must restore all original damage/payment/overload')
        g=self.game(mode='overload');self.play(g);before=g.snapshot();q=g.state.pending_choice
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):g.apply(SelectChoice(q.player_id,q.id,('fail',)))
        self.assertTrue(g.snapshot()==before,'Failed reaction choice must retain exact waiting state')

    def test_accepted_residence_uses_current_transformed_material_and_does_not_damage_returned_hand_card(self):
        for mode in('bounce','transform'):
            g=self.game(mode=mode);target=g.state.players[2].board[0];self.play(g)
            entity=g.state.entities[target]
            if mode=='bounce':self.assertEqual((entity.zone,entity.health),(Zone.HAND,10))
            else:self.assertEqual((entity.card_id,entity.health),(MATERIAL,7))
            self.assertEqual(g.state.players[1].overload_owed,1);self.restore(g)

    def test_lethal_health_batch_uses_existing_terminal_cutoff_before_later_overload(self):
        g=self.game('wound');self.play(g,DRIVER);self.play(g)
        self.assertEqual(g.state.status,'finished');self.assertTrue(self.casts(g)[0].interrupted)
        self.assertEqual(g.state.players[1].overload_owed,0)

    def test_second_seat_and_opponent_wait_keep_all_private_group_proofs_out_of_player_ports(self):
        g=self.game(mode='overload',seat=2);self.play(g)
        self.assertEqual((self.casts(g)[0].player_id,g.state.players[2].overload_owed),(2,1))
        for pid in(1,2):
            view=json.dumps(g.for_player(pid).observe(),ensure_ascii=False)
            for private in('spell_target_group_accepted','automatic_spell_target_group_accepted','rng_before','cast_history'):
                self.assertNotIn(private,view)
        self.restore(g)

    def test_body_requires_actual_cast_and_does_not_fabricate_scalar_targets(self):
        g=self.game();ctx=SimpleNamespace(cast=None)
        with self.assertRaises(ValueError):fixture().behavior(BODY)(ctx)

    def test_assembled_card_pool_and_profile_match_the_reviewed_leaf(self):
        r=assembled();leaf=fixture();self.assertEqual(r.card(CARD),leaf.card(CARD))
        self.assertEqual(r.pool_card(CARD),leaf.pool_card(CARD))
        self.assertEqual(r.spell_target_group_profiles[CARD],leaf.spell_target_group_profiles[CARD])
