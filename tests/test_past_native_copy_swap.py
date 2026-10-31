"""Actual five-card entries, original materials, physical swaps and portable waits."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json, unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_native_copy_swap as native
from hs_sim.engine import EndTurn, Game, IllegalAction, PlayerSetup, ResolutionError, Scenario
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, CopyMinion, Damage, Destroy, Draw,
    GainArmor, InvokeBehavior, RandomDamage, RequestChoice, ReturnToHand, Silence, Transform, TriggerDeathrattles)
from hs_sim.engine.model import (CardDefinition, CardType, CostSpec, DeathrattleRepeatSpec, SummonQuantitySpec,
    TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import GenerationContext, PoolCard
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.cross_zone import BuffStoredCard
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.native_copy_consumers import TransformHeldPlayedMinion
from hs_sim.local_pool_format import build_cn37_local_pool_format

CARIA, MORRIGAN, FLOOP, ZEREK, SATH = native.ROOTS
P = 'k723.'
A, B, SLEEP, KILLER, DRAWER, DUP, SHIFT, DR_REPEAT, QUANTITY = (
    P+x for x in ('a','b','sleep','killer','drawer','duplicate','shift','dr_repeat','quantity'))
KILL, HUSH, BOOST, WOUND, BOUNCE, EARLY, COPY, AREA, SUMMON, HAND_BUFF, DECK_BUFF, ZERO = (
    P+x for x in ('kill','hush','boost','wound','bounce','early','copy','area','summon','hand_buff','deck_buff','zero'))
WATCH, FILL, FAIL, REENTER = (P+x for x in ('watch','fill','fail','reenter'))
CTX = GenerationContext(P+'original-copy-fixture','experimental')


def native_source(entity):
    return next((a for a in entity.abilities if a.kind == 'defining_hand_source'), None)


@lru_cache(None)
def fixture(role='writer', host=False):
    h = build_cn37_local_pool_format() if host else None
    r = h.registry if h else defaults()
    if not host: native.register_past_native_copy_swap(r)
    meta = metadata(collectible=False, tribes=())
    r.register_behavior(A, lambda c: (Buff(c.source_id,2,3,c.source_id), GainArmor(c.player_id,3)))
    r.register_behavior(KILLER, lambda c: (Destroy(c.target_id,c.source_id),))
    r.register_behavior(DRAWER, lambda c: (Draw(c.player_id,1,c.source_id),))
    def duplicate(c):
        source = next((c.state.entities[i] for i in c.state.players[c.player_id].hand
            if native_source(c.state.entities[i]) is not None), None)
        return () if source is None else (CopyCard(CapturedCardCopyMaterial.capture(c.state,source),c.player_id,source_id=c.source_id),)
    r.register_behavior(DUP, duplicate)
    r.register_behavior(SHIFT, lambda c: (Transform(c.source_id,B),))
    for cid, atk, hp, fields in (
            (A,2,6,dict(battlecry=A,metadata=metadata(collectible=False,tribes=('DEMON',)))),
            (B,5,7,{}),(SLEEP,2,4,dict(dormant_turns=2)),
            (KILLER,0,4,dict(battlecry=KILLER,targeting=TargetSpec())),
            (DRAWER,1,2,dict(battlecry=DRAWER)), (DUP,1,3,dict(battlecry=DUP)),
            (SHIFT,1,4,dict(battlecry=SHIFT)),
            (DR_REPEAT,0,20,dict(deathrattle_repeats=(DeathrattleRepeatSpec(2),))),
            (QUANTITY,0,20,dict(summon_quantities=(SummonQuantitySpec(),)))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=0 if cid == KILLER else 1,
            attack=atk,health=hp,**dict({'metadata':meta},**fields)))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    def stored_buff(c, zone):
        source = next(c.state.entities[i] for i in getattr(c.state.players[c.player_id],zone)
            if (native_source(c.state.entities[i]) is not None if zone == 'hand' else c.state.entities[i].kind == CardType.MINION))
        return (BuffStoredCard(CardReference.capture(source),6,7,c.source_id,cost=CostSpec(set_to=1)),)
    bodies = {
        KILL:lambda c:(Destroy(c.target_id,c.source_id),), HUSH:lambda c:(Silence(c.target_id),),
        BOOST:lambda c:(Buff(c.target_id,3,4,c.source_id),), WOUND:lambda c:(Damage(c.target_id,1,c.source_id),),
        BOUNCE:lambda c:(ReturnToHand(c.target_id),), EARLY:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        COPY:lambda c:(CopyMinion(c.target_id,c.player_id,cause=SummonCause.capture(c)),),
        AREA:lambda c:tuple(Damage(i,1,c.source_id) for i in c.state.players[c.player_id].board),
        SUMMON:lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(B),),SummonCause.capture(c)),),
        HAND_BUFF:lambda c:stored_buff(c,'hand'), DECK_BUFF:lambda c:stored_buff(c,'deck'),
        ZERO:lambda c:(GainArmor(c.player_id,1),)}
    targeted = {KILL,HUSH,BOOST,WOUND,BOUNCE,EARLY,COPY}
    for cid, body in bodies.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=meta,
            **({'targeting':TargetSpec()} if cid in targeted else {})))
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ResolutionError('K723 deliberate rollback')))
    r.register_behavior(REENTER,lambda c:(SummonStoredCard(CardReference.capture(c.source),c.player_id,cause=SummonCause.capture(c)),))
    def wait(c):
        e = c.event; target = c.state.entities.get(e.target_id); source = c.state.entities.get(e.source_id)
        qualifies = (e.kind == 'transformed' and dict(e.data).get('old_card_id') == CARIA or
            e.kind == 'stored_card_transformed' and target is not None and native_source(target) is not None or
            e.kind == 'minion_died' and target is not None and target.card_id == ZEREK or
            e.kind == 'minion_summoned' and any(row.capture.card_id == MORRIGAN and row.execution_order is not None
                and not row.completed for row in c.state.deathrattle_history) or
            e.kind == 'card_created' and source is not None and source.card_id == SATH and target is not None and target.zone == Zone.HAND)
        if not qualifies: return ()
        options = (ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fault',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))))
        if e.kind == 'card_created' and source is not None and source.card_id == SATH:
            original_id = dict(e.data)['copied_from']
            options += (ChoiceOption('mutate','Mutate and reenter original',(Buff(original_id,20,20,c.source_id),
                ReturnToHand(original_id),InvokeBehavior(REENTER,original_id,c.player_id))),
                ChoiceOption('remove','Remove original source',(Destroy(source.id,c.source_id),)))
        return (RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(WATCH,wait)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.WEAPON,attack=0,durability=10,metadata=meta,
        triggers=tuple(TriggerSpec(e,WATCH) for e in ('transformed','stored_card_transformed','minion_died','minion_summoned','card_created'))))
    r.register_behavior(FILL,lambda c:(AddToHand(c.player_id,ZERO,c.source_id),)
        if c.state.entities[c.event.source_id].card_id == SATH else ())
    r.register_card(CardDefinition(FILL,FILL,CardType.WEAPON,attack=0,durability=10,metadata=meta,
        triggers=(TriggerSpec('card_committed',FILL),)))
    r.validate()
    return r, h.context if h else CTX


class NativeCopySwapTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory = staticmethod(lambda mode,role:fixture(role,mode == 'host')[0])
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=None,watch=False,host=False,fill=False):
        self.mode = 'host' if host else 'small'; r, context = fixture('writer',host)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,
            deck=(B,)*12 if deck is None else deck,mana=40,max_mana=40,mana_cap=40,armor=500,
            weapon_card_id=WATCH if watch else FILL if fill else None),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(B,)*12,mana=40,max_mana=40,mana_cap=40,armor=500)),
            seed=723,generation_context=context),r)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def all_units(self,g,cid,p=1):return [g.state.entities[i] for i in g.state.players[p].board if g.state.entities[i].card_id == cid]
    def finish(self,g):
        count = 0
        while g.state.pending_choice is not None:
            count += 1; self.assertLess(count,35); self.choose(g)
    def fault(self,g):
        before = g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
    def rehash(self,s):
        from hs_sim.engine.serialization import canonical_hash
        s['state_hash'] = canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})

    def test_complete_rows_primary_faces_and_original_scope(self):
        d = native.load_batch(); self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(len(d['official_observations']),12); self.assertFalse(d['complete_past_source_bound'])
        self.assertFalse(d['membership_uses_executable_coverage']); self.assertNotIn('MIS_701',fixture()[0].cards)
        for cid in native.ROOTS:self.assertEqual(fixture()[0].card(cid),fixture('independent-reader')[0].card(cid))

    def test_all_five_execute_from_actual_current_host_entries(self):
        g=self.game((CARIA,),deck=(A,),host=True); sid=self.play(g,CARIA);self.assertEqual(g.state.entities[sid].card_id,A)
        g=self.game((KILL,),board=(MORRIGAN,),deck=(B,),host=True);sid=self.unit(g,MORRIGAN).id;self.play(g,KILL,sid);self.assertEqual(g.state.entities[sid].zone,Zone.DECK)
        g=self.game((FLOOP,B),host=True);sid=self.entity(g,FLOOP).id;self.play(g,B);self.assertEqual(g.state.entities[sid].card_id,B)
        g=self.game((BOOST,KILLER),board=(ZEREK,),host=True);sid=self.unit(g,ZEREK).id;self.play(g,BOOST,sid);self.play(g,KILLER,sid);self.assertEqual(len(self.all_units(g,ZEREK)),1)
        g=self.game((SATH,),board=(B,),host=True);sid=self.unit(g,B).id;self.play(g,SATH,sid);self.assertEqual(len(self.all_units(g,B)),2)
        self.assertEqual(len([e for e in g.state.entities.values() if e.origin_entity_id == sid]),3)

    def test_Caria_current_deck_Demon_original_stays_and_no_copied_Battlecry(self):
        g=self.game((DECK_BUFF,CARIA),deck=(ZERO,A,ZERO));old=self.entity(g,A,zone='deck').id
        self.play(g,DECK_BUFF);sid=self.play(g,CARIA);source=g.state.entities[sid]
        self.assertEqual((source.card_id,source.attack,source.health),(A,6,6))
        self.assertEqual(g.state.entities[old].zone,Zone.DECK);self.assertEqual(g.state.players[1].deck[1],old)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,500)
        self.assertEqual(len(g.state.play_history),2);self.assertEqual(len(g.state.battlecry_history),1)

    def test_Caria_no_Demon_is_known_empty_without_RNG(self):
        g=self.game((CARIA,),deck=(B,ZERO));before=g.snapshot()['rng_state'];sid=self.play(g,CARIA)
        self.assertEqual(g.state.entities[sid].card_id,CARIA);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_Caria_six_six_is_removable_and_original_body_can_be_silenced(self):
        g=self.game((CARIA,HUSH),deck=(A,));sid=self.play(g,CARIA);self.play(g,HUSH,sid)
        self.assertEqual((g.state.entities[sid].attack,g.state.entities[sid].health),(2,6))

    def test_Caria_transform_wait_independent_restore_replay_and_rollback(self):
        g=self.game((CARIA,),deck=(A,),watch=True);sid=self.play(g,CARIA)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.finish(g)
        self.assertEqual((g.state.entities[sid].card_id,g.state.entities[sid].attack),(A,6))

    def test_Morrigan_physical_swap_replaces_exact_deck_slot_and_keeps_identity(self):
        g=self.game((KILL,),board=(MORRIGAN,),deck=(ZERO,B,ZERO));sid=self.unit(g,MORRIGAN).id;chosen=self.entity(g,B,zone='deck').id
        original=list(g.state.players[1].deck);self.play(g,KILL,sid)
        self.assertEqual(g.state.players[1].deck,[original[0],sid,original[2]])
        self.assertEqual(g.state.players[1].board,[chosen]);self.assertEqual(len(g.state.death_history),1)
        self.assertEqual(sum(e.card_id==MORRIGAN for e in g.state.entities.values()),1)

    def test_Morrigan_early_swap_at_full_board_and_full_deck_has_no_false_death(self):
        g=self.game((EARLY,),board=(B,B,B,MORRIGAN,B,B,B),deck=(ZERO,)*49+(A,)+(ZERO,)*49)
        sid=self.unit(g,MORRIGAN).id;chosen=self.entity(g,A,zone='deck').id;self.play(g,EARLY,sid)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g.state.players[1].board[3],chosen)
        self.assertEqual(g.state.players[1].deck[49],sid);self.assertEqual(len(g.state.players[1].deck),99)
        self.assertEqual(len(g.state.death_history),0);self.assertEqual(g.state.entities[sid].zone,Zone.DECK)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,500)

    def test_Morrigan_empty_minion_deck_keeps_source_and_RNG(self):
        g=self.game((EARLY,),board=(MORRIGAN,),deck=(ZERO,ZERO));sid=self.unit(g,MORRIGAN).id;before=g.snapshot()['rng_state']
        self.play(g,EARLY,sid);self.assertEqual(g.state.entities[sid].zone,Zone.BOARD);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_Morrigan_each_actual_repeat_selects_without_duplicating_outgoing_original(self):
        g=self.game((KILL,),board=(DR_REPEAT,MORRIGAN),deck=(B,B));sid=self.unit(g,MORRIGAN).id;self.play(g,KILL,sid)
        self.assertEqual(len(g.state.players[1].board),3);self.assertEqual(len(g.state.card_summon_history),2)
        self.assertEqual(sum(e.card_id==MORRIGAN for e in g.state.entities.values()),1)
        self.assertEqual(len(g.state.death_history),1)

    def test_Morrigan_recruit_quantity_extras_copy_chosen_material_and_swap_once(self):
        g=self.game((EARLY,),board=(QUANTITY,MORRIGAN),deck=(B,));sid=self.unit(g,MORRIGAN).id;chosen=self.entity(g,B,zone='deck').id
        self.play(g,EARLY,sid);self.assertEqual(len(self.all_units(g,B)),2);self.assertIn(chosen,g.state.players[1].board)
        self.assertEqual(g.state.players[1].deck,[sid]);self.assertEqual(len(g.state.death_history),0)

    def test_Morrigan_swap_wait_has_both_writes_before_notification_and_portability(self):
        g=self.game((EARLY,),board=(MORRIGAN,),deck=(B,),watch=True);sid=self.unit(g,MORRIGAN).id;self.play(g,EARLY,sid)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.players[1].deck,[sid])
        self.fault(g);g=self.portable(g);self.finish(g);self.assertEqual(len(self.all_units(g,B)),1)

    def test_Floop_original_binding_hand_entry_and_removable_three_four_four_cost(self):
        g=self.game((FLOOP,B));old=self.entity(g,FLOOP);sid=old.id;binding=native_source(old).id
        self.play(g,B);body=g.state.entities[sid]
        self.assertEqual((body.card_id,body.attack,body.health),(B,3,4));self.assertEqual(native_source(body).id,binding)
        self.assertEqual(body.hand_entry_id,old.hand_entry_id)
        self.assertEqual(g.registry.card(body.card_id).cost,1)
        from hs_sim.engine.costs import quote_unselected_cost
        self.assertEqual(quote_unselected_cost(g.state,g.registry,body).amount,4)

    def test_Floop_does_not_see_own_draw_during_that_Battlecry(self):
        g=self.game((DRAWER,),deck=(FLOOP,));self.play(g,DRAWER)
        self.assertEqual(self.entity(g,FLOOP).card_id,FLOOP);self.assertEqual(g.state.play_history[-1].native_hand_candidates,())

    def test_Floop_new_current_hand_copy_does_not_see_creating_Battlecry(self):
        g=self.game((FLOOP,B,DUP,A));original=self.entity(g,FLOOP).id;self.play(g,B);self.play(g,DUP)
        held=[g.state.entities[i] for i in g.state.players[1].hand if native_source(g.state.entities[i]) is not None]
        self.assertEqual(len(held),2);self.assertEqual(g.state.entities[original].card_id,DUP)
        copied=next(e for e in held if e.id!=original);self.assertEqual(copied.card_id,B);self.assertEqual(native_source(copied).progress_keys,())
        g=self.portable(g);self.play(g,A)
        self.assertEqual([g.state.entities[e.id].card_id for e in held],[A,A])

    def test_Floop_resets_old_hand_buffs_and_discount_at_next_successful_play(self):
        g=self.game((FLOOP,B,HAND_BUFF,A));sid=self.entity(g,FLOOP).id;self.play(g,B);self.play(g,HAND_BUFF)
        self.assertEqual((g.state.entities[sid].attack,g.state.entities[sid].health),(9,11))
        self.play(g,A);body=g.state.entities[sid];self.assertEqual((body.card_id,body.attack,body.health),(A,3,4))
        from hs_sim.engine.costs import quote_unselected_cost
        self.assertEqual(quote_unselected_cost(g.state,g.registry,body).amount,4)

    def test_Floop_uses_original_played_face_after_self_transform_and_excludes_summons(self):
        g=self.game((FLOOP,SUMMON,SHIFT));sid=self.entity(g,FLOOP).id;self.play(g,SUMMON)
        self.assertEqual(g.state.entities[sid].card_id,FLOOP);played=self.play(g,SHIFT)
        self.assertEqual(g.state.entities[played].card_id,B);self.assertEqual(g.state.entities[sid].card_id,SHIFT)

    def test_Floop_played_copy_executes_real_Battlecry_then_retires_native_source(self):
        g=self.game((FLOOP,A,HUSH,BOUNCE));sid=self.entity(g,FLOOP).id;self.play(g,A)
        self.play(g,A);self.assertEqual(g.state.entities[sid].zone,Zone.BOARD);self.assertIsNone(native_source(g.state.entities[sid]))
        self.assertEqual((g.state.entities[sid].attack,g.state.entities[sid].health),(5,7))
        self.play(g,HUSH,sid);self.assertEqual((g.state.entities[sid].attack,g.state.entities[sid].health),(2,6))
        self.play(g,BOUNCE,sid);self.assertIsNone(native_source(g.state.entities[sid]))

    def test_Floop_wait_recovery_and_rehashed_missing_original_candidate_is_rejected(self):
        g=self.game((FLOOP,B),watch=True);sid=self.entity(g,FLOOP).id;self.play(g,B)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g)
        bad=deepcopy(g.snapshot());bad['state']['play_history'][-1]['native_hand_candidates']=[];self.rehash(bad)
        with self.assertRaises(ValueError):Game.from_snapshot(bad,fixture('independent-reader')[0])
        self.finish(g);self.assertEqual(g.state.entities[sid].card_id,B)

    def test_Zerek_actual_own_arrow_resummons_one_fresh_printed_body_and_resets_activation(self):
        g=self.game((BOOST,BOOST,KILLER,KILLER),board=(ZEREK,));sid=self.unit(g,ZEREK).id
        self.play(g,BOOST,sid);self.play(g,BOOST,sid);self.play(g,KILLER,sid)
        fresh=self.unit(g,ZEREK);self.assertNotEqual(fresh.id,sid);self.assertEqual((fresh.attack,fresh.health),(5,5))
        self.assertFalse(next(a.deathrattle_memory for a in fresh.abilities if a.kind=='deathrattle').targeted_spells)
        self.play(g,KILLER,fresh.id);self.assertEqual(self.all_units(g,ZEREK),[])

    def test_Zerek_area_spell_without_arrow_and_opponent_arrow_do_not_activate(self):
        g=self.game((AREA,KILLER),board=(ZEREK,));sid=self.unit(g,ZEREK).id;self.play(g,AREA);self.play(g,KILLER,sid)
        self.assertEqual(self.all_units(g,ZEREK),[])
        g=self.game(board=(ZEREK,),enemy_hand=(BOOST,KILLER));sid=self.unit(g,ZEREK).id;g.apply(EndTurn(1))
        self.play(g,BOOST,sid,player=2);self.play(g,KILLER,sid,player=2);self.assertEqual(self.all_units(g,ZEREK),[])

    def test_Zerek_early_actual_Deathrattle_does_not_consume_activation_or_forge_death(self):
        g=self.game((BOOST,EARLY,EARLY),board=(ZEREK,));sid=self.unit(g,ZEREK).id
        self.play(g,BOOST,sid);self.play(g,EARLY,sid);self.play(g,EARLY,sid)
        self.assertEqual(len(self.all_units(g,ZEREK)),3);self.assertEqual(len(g.state.death_history),0)
        self.assertTrue(next(a.deathrattle_memory for a in g.state.entities[sid].abilities if a.kind=='deathrattle').targeted_spells)

    def test_Zerek_current_copy_retains_original_activation_and_silence_retires_it(self):
        g=self.game((COPY,HUSH,KILLER,KILLER),board=(ZEREK,));sid=self.unit(g,ZEREK).id;self.play(g,COPY,sid)
        copied=next(e for e in self.all_units(g,ZEREK) if e.id!=sid);self.play(g,HUSH,sid);self.play(g,KILLER,sid)
        self.play(g,KILLER,copied.id);self.assertEqual(len(self.all_units(g,ZEREK)),1)

    def test_Zerek_death_wait_original_memory_survives_restore_and_replay(self):
        g=self.game((BOOST,KILLER),board=(ZEREK,),watch=True);sid=self.unit(g,ZEREK).id
        self.play(g,BOOST,sid);self.play(g,KILLER,sid);self.assertIsNotNone(g.state.pending_choice)
        self.fault(g);g=self.portable(g);self.finish(g);self.assertEqual(len(self.all_units(g,ZEREK)),1)

    def test_Sath_base_stored_copies_and_current_board_follow_zone_direction(self):
        g=self.game((BOOST,WOUND,SATH),board=(B,));sid=self.unit(g,B).id;self.play(g,BOOST,sid);self.play(g,WOUND,sid);self.play(g,SATH,sid)
        copies=[e for e in g.state.entities.values() if e.origin_entity_id==sid]
        self.assertEqual({e.zone for e in copies},{Zone.HAND,Zone.DECK,Zone.BOARD})
        for e in copies:self.assertEqual((e.attack,e.health),(8,10)if e.zone==Zone.BOARD else(5,7))
        self.assertEqual(g.state.entities[sid].health,10)

    def test_Sath_frozen_material_survives_original_mutation_and_same_entity_reentry(self):
        g=self.game((BOOST,SATH),board=(B,),watch=True);sid=self.unit(g,B).id;self.play(g,BOOST,sid);self.play(g,SATH,sid)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.choose(g,'mutate');self.finish(g)
        copies=[e for e in g.state.entities.values() if e.origin_entity_id==sid]
        self.assertEqual(len(copies),3)
        self.assertTrue(all((e.attack,e.health)==((8,11)if e.zone==Zone.BOARD else(5,7)) for e in copies))
        self.assertEqual((g.state.entities[sid].attack,g.state.entities[sid].health),(5,7))

    def test_Sath_original_source_death_does_not_erase_remaining_copies(self):
        g=self.game((SATH,),board=(B,),watch=True);sid=self.unit(g,B).id;source=self.play(g,SATH,sid)
        g=self.portable(g);self.choose(g,'remove');self.finish(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(len([e for e in g.state.entities.values() if e.origin_entity_id==sid]),3)

    def test_Sath_each_zone_capacity_is_independent(self):
        g=self.game((SATH,)+(ZERO,)*9,board=(B,),deck=(ZERO,)*99,fill=True);sid=self.unit(g,B).id;self.play(g,SATH,sid)
        copies=[e for e in g.state.entities.values() if e.origin_entity_id==sid]
        self.assertEqual({e.zone for e in copies},{Zone.GRAVEYARD,Zone.BOARD});self.assertEqual(len(g.state.players[1].deck),99)
        g=self.game((SATH,),board=(B,)*6);sid=self.unit(g,B).id;self.play(g,SATH,sid)
        self.assertEqual({e.zone for e in g.state.entities.values() if e.origin_entity_id==sid},{Zone.HAND,Zone.DECK})

    def test_Sath_wrong_friendly_target_is_atomic_and_private_material_stays_hidden(self):
        g=self.game((SATH,),board=(B,),enemy=(A,),watch=True);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,SATH,self.unit(g,A,2).id)
        self.assertEqual(g.snapshot(),before);self.play(g,SATH,self.unit(g,B).id)
        for player in (1,2):
            view=json.dumps(g.for_player(player).observe())
            for key in ('native_hand_candidates','deck_ids','targeted_spells','source_ability_id'):
                self.assertNotIn('"'+key+'"',view)
        g=self.portable(g);self.finish(g)


if __name__ == '__main__':unittest.main()
