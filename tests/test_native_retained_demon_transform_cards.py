"""Actual Alara'shi hand roots, local numeric retention and native pool lifecycle."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_retained_demon_transform_cards import (
    ALARASHI, BATCH_HASH, DEMONS, POLICY, POOL_ID, load_batch,
    register_native_retained_demon_transform_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CostSpec,
    EndTurn, Game, Keyword, PlayCard, PlayerSetup, Rarity, Registry, Scenario, SelectChoice,
    SnapshotError, SummonStats, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, GainArmor, InvokeBehavior,
    RequestChoice, ReturnToHand, RevealHandCard)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostAuraSpec, LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.engine.stats import enchantment_stats
from hs_sim.engine.stored_pool_transforms import DRAW, TransformStoredFromPool, decode
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest

P='k187.'
HERO,A,B,C,SPELL,WEAPON,D1,D2,D3,OTHER,HIDDEN,UNKNOWN,AURA=(P+n for n in (
    'hero','a','b','c','spell','weapon','d1','d2','d3','other','hidden','unknown','aura'))
MEMBERS=(D1,D2,D3,OTHER,HIDDEN)
CTX=GenerationContext('k187-explicit-complete-demons','experimental')
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON)


@lru_cache(None)
def registry(members=MEMBERS,mode=None,pool=True):
    r=Registry('k187-original-numeric-hand-v1');register_native_retained_demon_transform_cards(r)
    r.register_behavior(P+'marker',lambda c:(GainArmor(c.player_id,99),))
    for cid,cost,attack,health in ((A,6,3,4),(B,8,0,2),(C,2,1,1)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health,
            metadata=META,keywords=(Keyword.RUSH,) if cid==A else ()))
    for cid,cost,cls in ((D1,1,CardClass.WARLOCK),(D2,9,CardClass.NEUTRAL),(D3,6,CardClass.MAGE),
                         (OTHER,3,CardClass.NEUTRAL),(HIDDEN,4,CardClass.NEUTRAL)):
        meta=CardMetadata(cid!=HIDDEN,(cls,),Rarity.COMMON,tribes=() if cid==OTHER else ('demon',))
        d=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=8,health=1,metadata=meta,
            keywords=(Keyword.DIVINE_SHIELD,),battlecry=P+'marker')
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    r.register_card(CardDefinition(SPELL,SPELL,CardType.SPELL,on_play=P+'marker'))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,cost=1,attack=1,durability=2))
    if UNKNOWN in members:
        r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,2,
            replace(META,tribes=('demon',)),battlecry=False,deathrattle=False,choose_one=False))
    if pool:
        r.register_pool(PoolDefinition(POOL_ID,'k187-explicit-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(cid,3 if cid==D2 else 1)for cid in members),complete=True))
    r.register_card(CardDefinition(AURA,AURA,CardType.MINION,attack=1,health=3,
        cost_auras=(CostAuraSpec(CostSpec(delta=-1,card_types=(CardType.MINION,))),)))
    def held(c,cid=A):return next(c.state.entities[i] for i in c.state.players[1].hand
        if c.state.entities[i].card_id==cid)
    def buff(c):
        return (BuffStoredCard(CardReference.capture(held(c)),2,3,c.source_id,cost=CostSpec(delta=-2)),)
    def fail(c):raise ResolutionError('K187 deliberate transformation reaction failure')
    def copy(c,base=False):
        target=next(c.state.entities[i] for i in c.state.players[1].hand
            if c.state.entities[i].card_id in (D1,D2,D3))
        return (CopyCard(CardReference.capture(target),1,Zone.HAND,
            mode='base' if base else 'current',source_id=c.source_id),)
    def bounce(c):
        target=next(i for i in c.state.players[1].board if c.state.entities[i].card_id in (D1,D2,D3))
        return (ReturnToHand(target),)
    def back(c):
        entity=c.state.entities[c.target_id]
        return (MoveCard(CardReference.capture(entity),1,Zone.HAND,source_id=c.source_id),)
    bodies={'buff':buff,'zero':lambda c:(BuffStoredCard(CardReference.capture(held(c,B)),
        source_id=c.source_id,cost=CostSpec(set_to=0)),),
        'reveal':lambda c:(RevealHandCard(held(c).id),),'fail':fail,'copy':copy,
        'base':lambda c:copy(c,True),'bounce':bounce,'back':back}
    for key,body in bodies.items():
        r.register_behavior(P+key,body)
        if key not in ('fail','back'):r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key))
    kwargs={}
    if mode:
        def eligible(c):
            source=c.state.entities.get(c.event.source_id)
            return source is not None and source.card_id==ALARASHI and c.event.player_id==c.player_id
        def observe(c):
            if mode=='inspect':
                e=c.state.entities[c.event.target_id]
                return (GainArmor(c.player_id,10 if (e.attack,e.health,e.cost)in((3,4,6),(0,2,8)) else 1),)
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode=='mutate':
                e=held(c,B)
                return (BuffStoredCard(CardReference.capture(e),10,10,c.source_id),AddToHand(1,C,c.source_id))
            if mode=='stale':
                e=held(c,B);ref=CardReference.capture(e)
                return (MoveCard(ref,1,Zone.DECK,source_id=c.source_id),
                    InvokeBehavior(P+'back',c.source_id,c.player_id,e.id))
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_trigger_condition(P+'eligible',eligible);r.register_behavior(P+'observe',observe)
        kwargs['limited_triggers']=(LimitedTriggerSpec('stored_card_transformed',P+'observe',
            condition_id=P+'eligible',uses=1),)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=100,
        metadata=CardMetadata(False,(CardClass.DEMON_HUNTER,),None),**kwargs))
    r.validate();return r


class NativeRetainedDemonTransformTests(unittest.TestCase):
    def game(self,members=MEMBERS,mode=None,pool=True,hand=(ALARASHI,A,B),board=()):
        self.config=members,mode,pool
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO,hand=hand,board=board,deck=(C,)*8,mana=20,max_mana=20,mana_cap=20),
            PlayerSetup(HERO,hand=(A,),deck=(C,)*8)),seed=187,generation_context=CTX),registry(*self.config))
    def play(self,g,cid=ALARASHI,player=1):
        source=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(player,source));return source
    def draws(self,g):return [decode(g,e)for e in g.events if e.kind==DRAW]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));reader=registry.__wrapped__(*self.config)
        self.assertIsNot(reader,g.registry)
        other=Game.from_snapshot(s,reader);self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),reader).snapshot(),s)
        return other
    def ids(self,g):return tuple(i for i in g.state.players[1].hand if g.state.entities[i].kind==CardType.MINION)

    def test_complete_source_dual_tribes_and_central_assembly(self):
        from hs_sim.cards.constructed import build_registry
        d=load_batch();card=build_registry().card(ALARASHI)
        self.assertEqual(canonical_digest(d),BATCH_HASH)
        self.assertEqual(d['policy'],POLICY);self.assertEqual(len(d['official_observations']),2)
        self.assertEqual((card.cost,card.attack,card.health,card.metadata.tribes),(5,5,5,('beast','demon')))
        self.assertEqual(card.metadata.classes,(CardClass.DEMON_HUNTER,))
        self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])

    def test_all_original_hand_minions_keep_numbers_identity_slot_and_hand_entry(self):
        g=self.game(hand=(ALARASHI,A,SPELL,B,WEAPON));before=g.state;ids=self.ids(g)[1:]
        expected={i:(before.entities[i].attack,before.entities[i].health,before.entities[i].cost)for i in ids}
        source=self.play(g)
        self.assertIn(source,g.state.players[1].board)
        for i in ids:
            e=g.state.entities[i];self.assertEqual((e.attack,e.health,e.cost),expected[i])
            self.assertEqual(e.zone_epoch,before.entities[i].zone_epoch+1)
            self.assertIn(e.card_id,(D1,D2,D3));self.assertNotIn(Keyword.RUSH,e.keywords)
        self.assertEqual([g.state.entities[i].kind for i in g.state.players[1].hand],
            [CardType.MINION,CardType.SPELL,CardType.MINION,CardType.WEAPON])
        self.assertEqual(g.state.players[2].hand,before.players[2].hand)
        self.assertEqual(g.state.hand_entries,before.hand_entries)
        self.portable(g)

    def test_local_buffs_cost_and_external_discount_are_not_counted_twice(self):
        g=self.game(members=(D1,),hand=(ALARASHI,A,P+'buff'),board=(AURA,))
        self.play(g,P+'buff');target=self.ids(g)[1]
        self.assertEqual(g.quote_cost(target).amount,3)
        self.play(g);e=g.state.entities[target]
        self.assertEqual((e.attack,e.health,local_cost(e)[0]),(5,7,4))
        self.assertEqual(g.quote_cost(target).amount,3)
        self.assertEqual(e.card_id,D1);self.assertIn(Keyword.DIVINE_SHIELD,e.keywords)
        self.assertNotIn(Keyword.RUSH,e.keywords);self.portable(g)

    def test_full_any_class_demon_pool_not_equal_cost_or_current_class(self):
        g=self.game();self.play(g)
        draws=self.draws(g);self.assertEqual(len(draws),2)
        for d in draws:
            self.assertEqual({c for c,w in d.candidates},{D1,D2,D3})
            self.assertEqual(dict(d.candidates)[D2],3)
            self.assertEqual(d.request.query,DEMONS)
        self.assertEqual(draws[0].rng_after,draws[1].rng_before)
        self.portable(g)

    def test_numeric_material_is_complete_at_first_transform_notification(self):
        g=self.game(mode='inspect');self.play(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,10)
        self.assertFalse(any(e.kind in ('card_created','card_added_to_hand','card_drawn')for e in g.events))
        self.portable(g)

    def test_original_frozen_numbers_and_inventory_ignore_later_buff_and_new_card(self):
        g=self.game(mode='mutate');original=self.ids(g)[1:];self.play(g)
        self.assertEqual((g.state.entities[original[1]].attack,g.state.entities[original[1]].health),(0,2))
        self.assertEqual(len(self.draws(g)),2)
        self.assertTrue(any(g.state.entities[i].card_id==C for i in g.state.players[1].hand))
        self.portable(g)

    def test_departed_and_reentered_original_target_stays_stale(self):
        g=self.game(mode='stale');second=self.ids(g)[2];self.play(g)
        self.assertEqual(g.state.entities[second].card_id,B)
        self.assertEqual(len(self.draws(g)),1);self.portable(g)

    def test_first_transform_wait_restores_remaining_original_numbers_and_draws_once(self):
        g=self.game(mode='wait');self.play(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(self.draws(g)),1);other=self.portable(g)
        for work in(g,other):
            q=work.state.pending_choice;work.apply(SelectChoice(1,q.id,('ok',)))
            self.assertIsNone(work.state.pending_choice);self.assertEqual(len(self.draws(work)),2)
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)

    def test_reaction_failure_rolls_back_hand_payment_source_board_and_rng(self):
        g=self.game(mode='fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_failed_wait_continuation_restores_original_pending_material(self):
        g=self.game(mode='wait');self.play(g);before=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,q.id,('bad',)))
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_unknown_qualified_demon_rolls_back_before_random_or_payment_commit(self):
        g=self.game(members=(D1,UNKNOWN));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_absent_formal_pool_is_explicit_and_not_registry_inference(self):
        g=self.game(pool=False);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_no_original_minion_does_not_require_unused_pool(self):
        g=self.game(pool=False,hand=(ALARASHI,SPELL,WEAPON));self.play(g)
        self.assertFalse(self.draws(g));self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_empty_eligible_pool_keeps_originals_and_has_empty_draw_without_rng(self):
        g=self.game(members=(OTHER,HIDDEN));ids=self.ids(g)[1:];before=g.snapshot()['rng_state'];self.play(g)
        self.assertEqual([g.state.entities[i].card_id for i in ids],[A,B])
        self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertTrue(all(not d.selected for d in self.draws(g)));self.portable(g)

    def test_current_copy_keeps_retained_numbers_base_copy_uses_new_printed_face(self):
        for kind in('copy','base'):
            with self.subTest(kind=kind):
                g=self.game(members=(D1,),hand=(ALARASHI,A,P+kind));self.play(g);self.play(g,P+kind)
                entities=[g.state.entities[i]for i in g.state.players[1].hand]
                self.assertEqual(len(entities),2)
                self.assertEqual((entities[1].attack,entities[1].health,entities[1].cost),
                    (3,4,6)if kind=='copy'else(8,1,1))
                self.portable(g)

    def test_play_uses_new_battlecry_and_bounce_resets_retained_numbers(self):
        g=self.game(members=(D1,),hand=(ALARASHI,A,P+'bounce'));self.play(g);target=self.ids(g)[0]
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        g.apply(PlayCard(1,target));self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,99)
        self.play(g,P+'bounce');e=g.state.entities[target]
        self.assertEqual((e.attack,e.health,e.cost),(8,1,1));self.portable(g)

    def test_revealed_original_is_concealed_and_numeric_draw_material_stays_private(self):
        g=self.game(members=(D1,),hand=(ALARASHI,A,P+'reveal'));self.play(g,P+'reveal')
        self.assertIn(A,json.dumps(g.observe(2)));self.play(g)
        enemy=json.dumps(g.observe(2));self.assertNotIn(D1,enemy)
        self.assertNotIn('retained_stats',enemy);self.assertNotIn(DRAW,json.dumps(g.player_events(2)))
        self.portable(g)

    def test_retained_request_rejects_partial_mixed_wrong_zone_and_scalar_shapes(self):
        g=self.game();ref=CardReference.capture(g.state.entities[self.ids(g)[1]])
        req=TransformStoredFromPool(ref,POOL_ID,DEMONS,g.state.players[1].hero_id,
            retained_stats=SummonStats(3,4),retained_cost=6)
        codec=FrameCodec(g.mechanics,g.registry);self.assertEqual(codec.decode(codec.encode(req)),req)
        for changes in({'retained_stats':None},{'retained_cost':None},{'retained_cost':True},
            {'retained_stats':SummonStats(attack=1)},{'source_id':None},
            {'target':replace(ref,zone=Zone.DECK)}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(req,**changes)

    def test_zero_attack_and_zero_retained_cost_are_exact_not_missing_values(self):
        g=self.game(members=(D1,),hand=(ALARASHI,B,P+'zero'));self.play(g,P+'zero');self.play(g)
        e=g.state.entities[self.ids(g)[0]]
        self.assertEqual((e.attack,e.health,e.cost),(0,2,0));self.portable(g)

    def test_old_snapshot_schema_is_rejected(self):
        g=self.game();self.play(g);s=g.snapshot();s['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,g.registry)


if __name__=='__main__':unittest.main()
