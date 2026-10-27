"""Original discovery choices, independently owed copies and real Arcane sources."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry, past_arcane_discovery_profiles as native
from hs_sim.engine import (CardClass, CardDefinition, CardType, CastSpell, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, ResolutionError, Scenario, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.discovery_summons import (StartDiscoverySummonEntry, entry_picks, validate_child, validate_queue)
from hs_sim.engine.effects import (ChoiceOption, Destroy, GainArmor, InvokeBehavior, RequestChoice)
from hs_sim.engine.model import ChoicePurpose, SummonQuantitySpec
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, resolve_candidates, sample_candidates
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.summon_quantities import GrantSummonQuantity
from hs_sim.engine.spell_history import DiscoverSpellHistory
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P='k594.'
UNIT,POWER,COPY_WATCH,BOON_WATCH,ACQUIRE_WATCH,BEAM_WATCH,SHIFT_WATCH,FAIL_ENTRY,FAIL_ACQUIRE=(P+x for x in
    ('unit','power','copy_watch','boon_watch','acquire_watch','beam_watch','shift_watch','fail_entry','fail_acquire'))
SPARK,FROST,AUTO_SPARK,AUTO_LIGHT,FAULT=(P+x for x in('spark','frost','auto_spark','auto_light','fault'))
FONT,CREATION,LIGHT,REWIND,NEBULA,SCROLL=native.LEAVES
WATCHES=(COPY_WATCH,BOON_WATCH,ACQUIRE_WATCH,BEAM_WATCH,SHIFT_WATCH,FAIL_ENTRY,FAIL_ACQUIRE)


@lru_cache(None)
def host(role='writer'):
    f=build_cn37_local_pool_format();r=f.registry
    def fail(c):raise ResolutionError('K594 deliberate continuation failure')
    def options(c,root=None):
        result=(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',
            (InvokeBehavior(FAULT,c.source_id,c.player_id),)))
        if root is not None:
            result+=(ChoiceOption('double_later','Install a later quantity source',
                (GrantSummonQuantity(c.source_id,SummonQuantitySpec(2),c.source_id),)),)
            if c.event.target_id is not None:result+=(ChoiceOption('remove_first','Remove original first body',
                (Destroy(c.event.target_id,c.source_id),)),)
        if c.source.card_id==BEAM_WATCH:
            result+=(ChoiceOption('nested','Accept a later Lightshow',(CastSpell(c.player_id,LIGHT,c.source_id),)),)
        return result
    def watch(c):
        e=c.event;owner=c.source.card_id;source=c.state.entities.get(e.source_id)
        if owner==BEAM_WATCH and e.kind=='damage_dealt' and source is not None and source.card_id==LIGHT:
            rows=[v for v in c.state.cast_history if v.player_id==c.player_id and v.card_id==LIGHT and v.payload_started]
            damage=[v for v in c.state.damage_history if v.health_result.source_card_id==LIGHT]
            if len(rows)==1 and len(damage)==1:return(RequestChoice(c.player_id,options(c),c.source_id),)
        if owner==SHIFT_WATCH and e.kind=='stored_card_transformed' and e.player_id==c.player_id:
            return(RequestChoice(c.player_id,options(c),c.source_id),)
        if e.player_id!=c.player_id:return ()
        if e.kind=='minion_summoned' and c.state.card_summon_history:
            child=c.state.card_summon_history[-1];link=child.request.producer_link
            if not c.state.discovery_summon_history:return ()
            root=next((v for v in c.state.discovery_summon_history if link is not None and v.id==getattr(link,'producer_id',None)),None)
            if root is None:return ()
            if owner==FAIL_ENTRY:return(InvokeBehavior(FAULT,c.source_id,c.player_id),)
            if owner==BOON_WATCH and root.spec.cause.source.card_id==NEBULA:
                target=c.state.entities[e.target_id]
                if not {Keyword.TAUNT,Keyword.ELUSIVE}<=set(target.keywords):raise ResolutionError('Original entry boons were not installed before reactions')
                return(GainArmor(c.player_id,1),)
            if owner==COPY_WATCH and root.spec.cause.source.card_id==CREATION and len(root.entry_root_ids)==1:
                return(RequestChoice(c.player_id,options(c,root),c.source_id),)
        if e.kind=='card_added_to_hand' and source is not None and source.card_id==FONT:
            if owner==FAIL_ACQUIRE:return(InvokeBehavior(FAULT,c.source_id,c.player_id),)
            if owner==ACQUIRE_WATCH:
                made=[v for v in c.state.entities.values()if v.controller==c.player_id and v.kind==CardType.MINION and
                    r.card(v.card_id).metadata is not None and CardClass.MAGE in (r.card(v.card_id).metadata.classes or ())]
                if len(made)==1:return(RequestChoice(c.player_id,options(c),c.source_id),)
        return ()
    r.register_behavior(FAULT,fail);r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,cost=1,attack=1,health=20))
    r.register_card(CardDefinition(POWER,POWER,CardType.MINION,health=20,spell_damage=1))
    for cid in WATCHES:r.register_card(CardDefinition(cid,cid,CardType.MINION,health=30,triggers=tuple(
        TriggerSpec(k,P+'watch')for k in('minion_summoned','card_added_to_hand','damage_dealt','stored_card_transformed'))))
    bodies={SPARK:lambda c:(GainArmor(c.player_id,1),),FROST:lambda c:(GainArmor(c.player_id,2),),
        AUTO_SPARK:lambda c:(CastSpell(c.player_id,SPARK,c.source_id),),
        AUTO_LIGHT:lambda c:(CastSpell(c.player_id,LIGHT,c.source_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,
            on_play=cid,spell_school=SpellSchool.FIRE if cid==SPARK else SpellSchool.FROST if cid==FROST else None))
    r.validate();return f


def plain(registry,cid):
    c=registry.card(cid)
    return not(c.triggers or c.auras or c.colossal or c.dormant_turns or c.summon_quantities)


@lru_cache(None)
def board_seed(card):
    f=host();q=native.SIXES if card==CREATION else native.EIGHTS
    rows=resolve_candidates(f.registry,f.context,native.POOL,q,current_class=CardClass.MAGE,
        source_card_id=card,player_id=1)
    for seed in range(1000):
        probe=Random(seed);menus=[sample_candidates(probe,rows,3,replacement=False)for _ in range(1 if card==CREATION else 2)]
        if all(any(plain(f.registry,i)for i in menu)for menu in menus):return seed
    raise AssertionError('Complete real pool has no suitable deterministic representative offer')


class PastArcaneDiscoveryProfileTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:host(role).registry)

    def game(self,hand=(),*,own=(),enemy=(),deck=None,other_hand=(),player=1,active=None,seed=19,hero='HERO_08'):
        f=host();setups=tuple(PlayerSetup(hero if p==player else 'HERO_08',hand=hand if p==player else other_hand,
            board=own if p==player else enemy,deck=((UNIT,)*10 if deck is None else deck)if p==player else(UNIT,)*10,
            mana=60,max_mana=60,mana_cap=60)for p in(1,2))
        return Game.from_scenario(Scenario(setups,active_player=player if active is None else active,
            seed=seed,generation_context=f.context),f.registry)

    def paid(self,g,cid,player=1):
        e=self.entity(g,cid,player);cost=quote_unselected_cost(g.state,g.registry,e).amount;n=len(g.state.play_history)
        g.apply(PlayCard(player,e.id));self.assertEqual((g.state.play_history[n].card_id,g.state.play_history[n].cost),(cid,cost));return e.id
    def pick(self,g):
        choice=g.state.pending_choice;self.assertIsNotNone(choice)
        option=next(o for o in choice.options if plain(g.registry,o.card_id))
        self.choose(g,option.id);return option.card_id
    def health(self,g):return[v.health_result for v in g.state.damage_history if v.health_result.source_card_id==LIGHT]
    def frame_queue(self,g):return(*g._frame.prefix,*g._frame.continuation)

    def test_complete_six_original_rows_twelve_primary_faces_and_scroll_evidence(self):
        d=native.load_batch();self.assertEqual((len(d['dependencies']),len(d['evidence_only']),len(d['official_observations'])),(6,1,12))
        rows={v['record']['id']:v['record']for v in d['dependencies']}
        for v in d['official_observations']:batch.check_face(rows[v['card_id']],v['face'],v['locale'],
            d['display_normalizations'].get(v['card_id']),numeric_normalizations=d['numeric_normalizations'].get(v['card_id']))
        self.assertIsNone(rows[SCROLL]['cost']);self.assertFalse(host().registry.card(SCROLL).manual_playable)
        self.assertEqual(native.COLLECTIBLE_ROOTS,())

    def test_font_with_deck_minion_is_one_genuine_fixed_mage_discovery_in_both_seats(self):
        for p in(1,2):
            g=self.game((FONT,),deck=(UNIT,),player=p);self.paid(g,FONT,p)
            self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.POOL_DISCOVERY)
            self.assertTrue(all(CardClass.MAGE in g.registry.card(o.card_id).metadata.classes for o in g.state.pending_choice.options))
            selected=g.state.pending_choice.options[0].card_id;self.choose(g,g.state.pending_choice.options[0].id)
            self.assertEqual([g.state.entities[i].card_id for i in g.state.players[p].hand],[selected])
            self.assertEqual(len(g.state.card_discovery_history),1)

    def test_font_no_minions_uses_one_full_pool_sample_without_choice_or_discovery_fact(self):
        g=self.game((FONT,),deck=(SPARK,));rows=resolve_candidates(g.registry,host().context,native.POOL,
            native.MAGE_MINIONS,source_card_id=FONT,player_id=1)
        probe=Random();probe.setstate(g._rng.getstate());expected=sample_candidates(probe,rows,3,replacement=False)
        self.paid(g,FONT);self.assertIsNone(g.state.pending_choice)
        self.assertEqual(tuple(g.state.entities[i].card_id for i in g.state.players[1].hand),expected)
        self.assertEqual(g._rng.getstate(),probe.getstate());self.assertFalse(g.state.card_discovery_history)

    def test_font_uses_mage_minions_even_when_the_actual_caster_is_a_rogue(self):
        g=self.game((FONT,),hero='HERO_03',deck=(SPARK,));self.paid(g,FONT)
        self.assertEqual(g.state.players[1].hero_class,CardClass.ROGUE)
        self.assertTrue(all(CardClass.MAGE in g.registry.card(g.state.entities[i].card_id).metadata.classes
            for i in g.state.players[1].hand))

    def test_font_alternative_keeps_full_sample_when_only_one_hand_slot_remains(self):
        g=self.game((FONT,)+(UNIT,)*9,deck=());allocated=g.state.next_entity_id;self.paid(g,FONT)
        made=[e for e in g.state.entities.values()if e.id>=allocated and e.controller==1 and e.kind==CardType.MINION]
        self.assertEqual((len(made),sum(e.zone==Zone.HAND for e in made)),(3,1));self.assertFalse(g.state.card_discovery_history)

    def test_font_alternative_acquisition_wait_restores_remaining_original_sample_and_bad_choice(self):
        g=self.game((FONT,),own=(ACQUIRE_WATCH,),deck=());self.paid(g,FONT);self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);self.choose(other);self.assertEqual(len(other.state.players[1].hand),3)
        self.assertFalse(other.state.card_discovery_history);self.portable(other)

    def test_font_late_acquisition_failure_rolls_back_original_payment_full_sample_and_rng(self):
        g=self.game((FONT,),own=(FAIL_ACQUIRE,),deck=());saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.paid(g,FONT)
        self.assertEqual(g.snapshot(),saved)

    def test_creation_one_actual_choice_has_two_independent_original_summon_roots_in_both_seats(self):
        for p in(1,2):
            g=self.game((CREATION,),player=p,seed=board_seed(CREATION));self.paid(g,CREATION,p)
            cid=self.pick(g);root=g.state.discovery_summon_history[-1]
            self.assertEqual((len(root.offers),len(root.entry_root_ids),root.status),(1,2,'completed'))
            self.assertEqual(len(g.state.card_discovery_history),1)
            self.assertEqual([g.state.entities[i].card_id for i in g.state.players[p].board],[cid,cid])
            self.assertEqual([v.request.producer_link.index for v in g.state.card_summon_history],[0,1])

    def test_creation_keeps_one_choice_even_on_full_board_and_records_two_failed_entries(self):
        g=self.game((CREATION,),own=(UNIT,)*7,seed=board_seed(CREATION));rng=g._rng.getstate();self.paid(g,CREATION)
        self.assertNotEqual(g._rng.getstate(),rng);self.pick(g);root=g.state.discovery_summon_history[-1]
        self.assertEqual(len(root.entry_root_ids),2);self.assertEqual(len(g.state.players[1].board),7)
        self.assertTrue(all(v.deliveries[0].outcome=='board_full'for v in g.state.card_summon_history))

    def test_creation_wait_keeps_second_copy_after_first_body_is_removed(self):
        g=self.game((CREATION,),own=(COPY_WATCH,),seed=board_seed(CREATION));self.paid(g,CREATION);cid=self.pick(g)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);self.choose(other,'remove_first')
        self.assertEqual(sum(other.state.entities[i].card_id==cid for i in other.state.players[1].board),1)
        self.assertEqual(len(other.state.discovery_summon_history[-1].entry_root_ids),2);self.portable(other)

    def test_creation_second_copy_accepts_later_live_quantity_without_changing_first_plan(self):
        g=self.game((CREATION,),own=(COPY_WATCH,),seed=board_seed(CREATION));self.paid(g,CREATION);cid=self.pick(g)
        self.choose(g,'double_later');self.assertEqual([v.plan.total for v in g.state.card_summon_history],[1,2])
        self.assertEqual(sum(g.state.entities[i].card_id==cid for i in g.state.players[1].board),3)
        self.assertEqual(len(g.state.card_discovery_history),1);self.portable(g)

    def test_creation_pending_tail_cannot_drop_second_original_entry(self):
        g=self.game((CREATION,),own=(COPY_WATCH,),seed=board_seed(CREATION));self.paid(g,CREATION);self.pick(g)
        queue=self.frame_queue(g);self.assertTrue(any(type(w)is StartDiscoverySummonEntry for w in queue))
        stripped=tuple(w for w in queue if type(w)is not StartDiscoverySummonEntry)
        with self.assertRaises(ValueError):validate_queue(g.state,g.registry,stripped)

    def test_creation_real_entry_failure_rolls_back_selected_choice_and_leaves_original_offers(self):
        g=self.game((CREATION,),own=(FAIL_ENTRY,),seed=board_seed(CREATION));self.paid(g,CREATION);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.pick(g)
        self.assertEqual(g.snapshot(),saved)

    def test_nebula_two_real_discoveries_have_taunt_and_elusive_before_entry_reactions(self):
        g=self.game((NEBULA,),own=(BOON_WATCH,),seed=board_seed(NEBULA));self.paid(g,NEBULA)
        first=self.pick(g);self.assertIsNotNone(g.state.pending_choice);second=self.pick(g)
        root=g.state.discovery_summon_history[-1];self.assertEqual((len(root.offers),len(root.entry_root_ids)),(2,2))
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board if g.state.entities[i].card_id!=BOON_WATCH],[first,second])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
        self.assertEqual(len(g.state.card_discovery_history),2)

    def test_nebula_second_offer_restore_keeps_first_boons_and_original_pending_query(self):
        g=self.game((NEBULA,),seed=board_seed(NEBULA));self.paid(g,NEBULA);first=self.pick(g);other=self.portable(g)
        self.assertTrue({Keyword.TAUNT,Keyword.ELUSIVE}<=set(self.entity(other,first,1,'board').keywords))
        self.pick(other);self.portable(other)

    def test_nebula_child_cannot_discard_original_preentry_keyword_pair(self):
        g=self.game((NEBULA,),seed=board_seed(NEBULA));self.paid(g,NEBULA);self.pick(g)
        root=g.state.discovery_summon_history[-1];child=g.state.card_summon_history[-1]
        material=replace(child.request.materials[0],keywords=(Keyword.TAUNT,))
        forged=replace(child,request=replace(child.request,materials=(material,)))
        with self.assertRaises(ValueError):validate_child(root,0,forged)

    def test_finite_board_profiles_reject_unrequested_combinations_and_invalid_copy_counts(self):
        g=self.game((CREATION,),seed=board_seed(CREATION));self.paid(g,CREATION);spec=g.state.discovery_summon_history[-1].spec
        for fields in({'summon_copies':True},{'summon_copies':0},{'summon_copies':3},{'discoveries':2},
                {'entry_keywords':(Keyword.TAUNT,Keyword.ELUSIVE)},{'freeze_summoned':True},
                {'delivery':'after_all'},{'copy_selected_to_hand':True},{'keep_all_corpse_cost':2},
                {'entry_keywords':('taunt','elusive')},{'entry_keywords':(Keyword.RUSH,)},{'source_id':None}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):replace(spec,**fields)

    def test_lightshow_freezes_two_then_three_beams_from_real_accepted_own_casts(self):
        g=self.game((LIGHT,LIGHT));first=self.paid(g,LIGHT);second=self.paid(g,LIGHT)
        self.assertEqual(sum(v.source_id==first for v in self.health(g)),2)
        self.assertEqual(sum(v.source_id==second for v in self.health(g)),3)
        self.assertEqual(g.state.players[1].mana,54)

    def test_lightshow_automatic_cast_counts_and_each_beam_gets_normal_spell_damage(self):
        g=self.game((AUTO_LIGHT,LIGHT),own=(POWER,));self.paid(g,AUTO_LIGHT);self.paid(g,LIGHT)
        self.assertEqual(len(self.health(g)),5);self.assertTrue(all(v.damage_dealt==3 for v in self.health(g)))
        self.assertEqual(sum(v.card_id==LIGHT for v in g.state.cast_history),2)

    def test_lightshow_countered_and_opponent_casts_do_not_add_beams(self):
        g=self.game((LIGHT,LIGHT),other_hand=('CORE_EX1_287',),active=2)
        self.paid(g,'CORE_EX1_287',2);g.apply(EndTurn(2));self.paid(g,LIGHT);self.paid(g,LIGHT)
        self.assertEqual(len(self.health(g)),2)
        g=self.game((LIGHT,),other_hand=(LIGHT,),active=2);self.paid(g,LIGHT,2);g.apply(EndTurn(2));source=self.paid(g,LIGHT)
        self.assertEqual(sum(v.source_id==source for v in self.health(g)),2)

    def test_lightshow_wait_keeps_original_beam_count_when_later_nested_cast_is_accepted(self):
        g=self.game((LIGHT,),own=(BEAM_WATCH,));source=self.paid(g,LIGHT);other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);self.choose(other,'nested')
        self.assertEqual(sum(v.source_id==source for v in self.health(other)),2)
        self.assertEqual(len(self.health(other)),5);self.portable(other)

    def test_rewind_is_a_genuine_history_discovery_of_other_completed_own_spell_faces(self):
        g=self.game((SPARK,SPARK,FROST,REWIND));self.paid(g,SPARK);self.paid(g,SPARK);self.paid(g,FROST);self.paid(g,REWIND)
        choice=g.state.pending_choice;self.assertEqual(choice.purpose,ChoicePurpose.CARD_DISCOVERY)
        self.assertEqual({o.card_id for o in choice.options},{SPARK,FROST});self.assertEqual(len(choice.options),2)
        cid=choice.options[0].card_id;self.choose(g,choice.options[0].id)
        self.assertEqual(self.entity(g,cid).card_id,cid);self.assertEqual(len(g.state.card_discovery_history),1)

    def test_rewind_includes_automatic_cast_and_excludes_empty_history_without_rng(self):
        g=self.game((AUTO_SPARK,REWIND));self.paid(g,AUTO_SPARK);self.paid(g,REWIND)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{SPARK,AUTO_SPARK})
        g=self.game((REWIND,));rng=g._rng.getstate();self.paid(g,REWIND)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g._rng.getstate(),rng);self.assertFalse(g.state.card_discovery_history)

    def test_rewind_wait_restores_original_faces_and_delivers_one_original_choice(self):
        g=self.game((SPARK,REWIND));self.paid(g,SPARK);self.paid(g,REWIND);other=self.portable(g)
        self.choose(other,other.state.pending_choice.options[0].id);self.assertEqual(self.entity(other,SPARK).card_id,SPARK)
        self.assertEqual(len(other.state.card_discovery_history),1);self.portable(other)

    def test_history_discovery_intent_is_explicit_and_rejects_unsourced_or_inherited_delivery(self):
        self.assertFalse(DiscoverSpellHistory(1).discovery)
        for fields in({'discovery':1},{'discovery':True},{'discovery':True,'source_id':1,'branch_policy':'inherit'}):
            with self.assertRaises(ValueError):DiscoverSpellHistory(1,**fields)

    def test_original_shifting_scroll_cannot_be_manually_played_even_with_printed_zero(self):
        g=self.game((SCROLL,));saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.paid(g,SCROLL)
        self.assertEqual(g.snapshot(),saved)

    def test_scroll_native_source_keeps_same_physical_identity_across_two_owner_turns(self):
        g=self.game((SCROLL,));source=self.entity(g,SCROLL).id
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[source].card_id,SCROLL)
        g.apply(EndTurn(2));first=g.state.entities[source]
        self.assertNotEqual(first.card_id,SCROLL);self.assertEqual(first.controller,1)
        ability=next(a for a in first.abilities if a.kind=='defining_hand_source')
        self.assertEqual(ability.defining_card_id,SCROLL);old_id=ability.id
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(next(a.id for a in g.state.entities[source].abilities if a.kind=='defining_hand_source'),old_id)
        self.assertEqual(len([e for e in g.events if e.kind=='stored_card_transformed'and e.target_id==source]),2)

    def test_scroll_transformation_wait_restores_original_native_source_and_failed_choice(self):
        g=self.game((SCROLL,),own=(SHIFT_WATCH,));g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=other.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),saved);self.choose(other);self.portable(other)

    def test_scroll_original_source_selects_a_mage_spell_for_a_rogue_owner(self):
        g=self.game((SCROLL,),hero='HERO_03');source=self.entity(g,SCROLL).id
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertIn(CardClass.MAGE,g.registry.card(g.state.entities[source].card_id).metadata.classes)

    def test_last_bad_scroll_metadata_is_rejected_before_partial_registration(self):
        r=batch.registration_prefix(build_registry,'hs_sim.cards.past_arcane_discovery_profiles.register_past_arcane_discovery_profiles',
            native.register_past_arcane_discovery_profiles)
        r.register_pool_card(replace(host().registry.pool_card(SCROLL),cost=9));before=r.fingerprint()
        with self.assertRaisesRegex(TargetValidationError,SCROLL):native.register_past_arcane_discovery_profiles(r)
        self.assertEqual(r.fingerprint(),before)

    def test_new_wires_private_producer_state_and_original_full_source_remain_explicit(self):
        g=self.game((CREATION,),seed=board_seed(CREATION));self.paid(g,CREATION)
        self.assertEqual(g.snapshot()['schema_version'],SNAPSHOT_SCHEMA_VERSION);self.assertGreaterEqual(SNAPSHOT_SCHEMA_VERSION,601)
        public=json.dumps(g.for_player(2).observe())
        for key in('summon_copies','entry_keywords','discovery_summon_history','rng_state','resolution_frame','source_sha256'):
            self.assertNotIn('"'+key+'"',public)
        ref=batch.read(native.ROOT/'data/cards/past-arcane-local-reference-v1.json')
        self.assertEqual(len(ref['candidate_ids']),84);self.assertTrue(set(native.LEAVES)<=set(ref['candidate_ids']))
        self.assertFalse(any(v.source_card_id=='TIME_857'for v in host().registry.generation_scopes.values()))
