"""Native six-card draw groups retain physical identity across real reactions."""
from dataclasses import replace
import json
from random import Random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.physical_draw_cards import load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CastWhenDrawnSpec,
    DeckPolicy, DeckSpec, EndTurn, Game, Keyword, MatchSetup, OpeningHook, PlayCard,
    PlayerSetup, Rarity, Scenario, SelectChoice, SnapshotError, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (AddToHand, ChangeManaCrystals, ChoiceOption, Draw, GainArmor,
    InvokeBehavior, RequestChoice, Summon)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.model import CostSpec
from hs_sim.engine.physical_draw_groups import (CapturePhysicalDrawGroup, ContinuePhysicalDrawGroup,
    DrawGroupArrival, DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup, validate_material)
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, ModifyStoredCost, MoveCard
from hs_sim.targets import canonical_digest

ROOT='MEND_043';FORWARD='TIME_770';BRIBE='JAIL_206';FLIGHT='TLC_222';HYBRID='TLC_236';ARMS='EDR_251'
ROOTS=(ROOT,FORWARD,BRIBE,FLIGHT,HYBRID,ARMS)
ONE='k44.one';TWO='k44.two';THREE='k44.three';FOUR='k44.four';PLAIN='k44.plain';FIRE='k44.fire';NATURE='k44.nature'


def registry():
    r=build_registry();meta=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    for cid,cost,tribes in ((ONE,1,('beast',)),(TWO,2,('elemental',)),(THREE,3,('dragon',)),
        (FOUR,4,('undead',)),(PLAIN,6,()),('k44.dual',3,('beast','dragon')),('k44.all',2,('all',)),('k44.unknown',1,None)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=cost,health=cost+1,metadata=replace(meta,tribes=tribes)))
    r.register_behavior('k44.noop',lambda c:())
    for cid,school in ((FIRE,SpellSchool.FIRE),(NATURE,SpellSchool.NATURE)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,metadata=meta,on_play='k44.noop',spell_school=school))
    r.register_card(CardDefinition('k44.portal','Replacement portal',CardType.SPELL,metadata=meta,
        keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec(),on_play='k44.noop'))
    r.register_behavior('k44.fail',lambda c:(AddToHand(c.player_id,'unknown.k44'),))
    r.register_behavior('k44.draw',lambda c:(Draw(c.player_id,1,c.source_id),))
    r.register_behavior('k44.direct',lambda c:(Summon(c.player_id,ONE),))
    def reprice(c):
        ref=next(CardReference.capture(c.state.entities[i])for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id==TWO)
        return (ModifyStoredCost(ref,CostSpec(delta=-1),c.source_id),)
    r.register_behavior('k44.reprice',reprice)
    for cid in ('draw','direct','reprice'):
        r.register_card(CardDefinition('k44.'+cid,cid,CardType.SPELL,metadata=meta,on_play='k44.'+cid))
    def watch(c,mode):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id not in ROOTS:return ()
        if c.state.entities[c.state.players[c.player_id].hero_id].armor:return ()
        ref=CardReference.capture(c.state.entities[c.event.target_id])
        tail=(MoveCard(ref,c.player_id,Zone.DECK,'top',source_id=c.source_id),Draw(c.player_id,1,c.source_id))if mode=='cycle'else ()
        if mode=='extra':tail=(Draw(c.player_id,1,c.source_id),)
        if mode=='fill':tail=tuple(AddToHand(c.player_id,PLAIN,c.source_id)for _ in range(10))
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),*tail)),
            ChoiceOption('bad','Fail',(InvokeBehavior('k44.fail',c.source_id,c.player_id),))),c.source_id),)
    for mode in ('wait','cycle','extra','fill'):
        r.register_behavior('k44.watch.'+mode,lambda c,mode=mode:watch(c,mode))
        r.register_card(CardDefinition('k44.watch.'+mode,mode,CardType.MINION,health=8,metadata=meta,
            triggers=(TriggerSpec('card_drawn','k44.watch.'+mode),)))
    r.register_behavior('k44.fill_commit',lambda c:(AddToHand(c.player_id,PLAIN,c.source_id),)
        if c.state.entities[c.event.source_id].card_id==FLIGHT else ())
    r.register_card(CardDefinition('k44.fill_commit','Pre-draw fill',CardType.MINION,health=8,metadata=meta,
        triggers=(TriggerSpec('card_committed','k44.fill_commit'),)))
    def boot(c):
        return (ChangeManaCrystals(c.player_id,10,filled=True),AddToHand(c.player_id,ARMS,c.source_id),
            AddToHand(c.player_id,'k44.copy',c.source_id),AddToHand(c.player_id,'k44.transform',c.source_id),
            AddToHand(c.player_id,'k44.foreign',c.source_id),AddToDeck(c.player_id,FIRE,'bottom',c.source_id))
    r.register_behavior('k44.boot',boot)
    r.register_card(CardDefinition('k44.boot','Opening source fixture',CardType.MINION,health=1,metadata=meta,
        opening_hooks=(OpeningHook('after_mulligan','k44.boot'),)))
    def original(c,p=1):
        ids=set(c.state.opening.original_entities[p-1])
        return next(c.state.entities[i]for i in c.state.players[p].deck if i in ids and c.state.entities[i].card_id==FIRE)
    r.register_behavior('k44.copy',lambda c:(CopyCard(CardReference.capture(original(c)),1,Zone.DECK,source_id=c.source_id),))
    r.register_behavior('k44.transform',lambda c:(TransformStoredCard(CardReference.capture(original(c)),FIRE,c.source_id),))
    r.register_behavior('k44.foreign',lambda c:(MoveCard(CardReference.capture(original(c,2)),1,Zone.DECK,source_id=c.source_id),))
    for cid in ('copy','transform','foreign'):
        r.register_card(CardDefinition('k44.'+cid,cid,CardType.SPELL,on_play='k44.'+cid,metadata=meta))
    r.register_behavior('k44.bad_source',lambda c:(DrawPhysicalGroup(c.player_id,999999,(DrawGroupSlot(),)),))
    r.register_card(CardDefinition('k44.bad_source','bad source',CardType.SPELL,on_play='k44.bad_source',metadata=meta))
    return r


class PhysicalDrawCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand,*,deck=(ONE,TWO,THREE,FOUR),board=(),enemy_hand=(),enemy_deck=(PLAIN,)*8):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,board=board,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,deck=enemy_deck,mana=40,max_mana=40,mana_cap=40)),seed=944),self.r)
    def eid(self,g,cid,p=1,zone='hand'):
        s=g.state;return next(i for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def play(self,g,cid,p=1):
        s=g.state;eid=self.eid(g,cid,p);position=len(s.players[p].board)if s.entities[eid].kind==CardType.MINION else None
        g.apply(PlayCard(p,eid,position=position));return eid
    def choose(self,g,key=None):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key or c.options[0].id,)))
    def hand(self,g,p=1):
        s=g.state;return [s.entities[i]for i in s.players[p].hand]
    def armor(self,g):
        s=g.state;return s.entities[s.players[1].hero_id].armor
    def price(self,g,eid):
        s=g.state;return quote_unselected_cost(s,g.registry,s.entities[eid]).amount
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return other
    def match(self):
        cards=('k44.boot',)+(FIRE,)*11
        policy=DeckPolicy('k44.original','k44.fixed-test','experimental',('k44.boot',FIRE),deck_size=12,max_copies=12)
        g=Game.from_decks(MatchSetup(tuple(DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,cards)for _ in (1,2)),
            policy,'GAME_005',seed=944,first_player=1),self.r)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        return g

    def test_complete_six_faces_and_schools(self):
        data=load_batch();self.assertEqual({row['record']['id']for row in data['cards']},set(ROOTS))
        for row in data['cards']:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            self.assertEqual(self.r.card(raw['id']).cost,raw['cost'])
        self.assertEqual(self.r.card(HYBRID).spell_school,SpellSchool.NATURE)
        self.assertEqual(self.r.card(FLIGHT).spell_school,SpellSchool.FIRE)

    def test_heartroot_first_owner_interval_draws_twice_and_gains_six(self):
        g=self.game((ROOT,));ids=g.state.players[1].deck[:2];self.play(g,ROOT)
        self.assertEqual(g.state.players[1].hand,ids);self.assertEqual(self.armor(g),6)
        self.assertEqual([x.outcome for x in g.state.draw_history],['hand','hand'])

    def test_heartroot_previous_owner_minion_limits_to_one_pair(self):
        g=self.game((ROOT,ONE));self.play(g,ONE);g.apply(EndTurn(1));g.apply(EndTurn(2));n=len(g.state.draw_history)
        self.play(g,ROOT);self.assertEqual(len(g.state.draw_history)-n,1);self.assertEqual(self.armor(g),3)

    def test_heartroot_same_turn_and_direct_summon_do_not_replace_previous_history(self):
        for cid in (ONE,'k44.direct'):
            g=self.game((ROOT,cid));self.play(g,cid);self.play(g,ROOT);self.assertEqual(self.armor(g),6)

    def test_heartroot_latest_empty_owner_interval_replaces_older_minion(self):
        g=self.game((ROOT,ONE),deck=(PLAIN,)*8);self.play(g,ONE)
        for p in (1,2,1,2):g.apply(EndTurn(p))
        n=len(g.state.draw_history);self.play(g,ROOT);self.assertEqual(len(g.state.draw_history)-n,2)
        self.assertEqual(self.armor(g),6)

    def test_heartroot_draw_wait_restore_freezes_number_of_pairs(self):
        g=self.game((ROOT,),board=('k44.watch.wait',));self.play(g,ROOT);saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for h in (g,other):self.choose(h,'ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.armor(g),7)
        self.assertEqual(len(g.state.draw_history),2)

    def test_heartroot_fatigue_follows_actual_draw_then_armor_order(self):
        g=self.game((ROOT,),deck=());self.play(g,ROOT);s=g.state
        self.assertEqual(len(s.draw_history),2);self.assertEqual(self.armor(g),4)
        self.assertEqual(s.entities[s.players[1].hero_id].health,29)

    def test_forward_top_order_no_rng_and_only_one_original_discount(self):
        g=self.game((FORWARD,PLAIN),deck=(FOUR,THREE,TWO));before=g._rng.getstate();ids=g.state.players[1].deck[:2]
        self.play(g,FORWARD);q=g.state.pending_choice
        self.assertEqual([o.entity_id for o in q.options],ids);self.assertEqual(g._rng.getstate(),before)
        self.assertEqual([self.price(g,i)for i in ids],[4,3]);self.choose(g,q.options[1].id)
        self.assertEqual([self.price(g,i)for i in ids],[4,1]);self.assertEqual(self.price(g,self.eid(g,PLAIN)),6)
        self.portable(g)

    def test_forward_duplicate_faces_are_two_physical_options(self):
        g=self.game((FORWARD,),deck=(FOUR,FOUR));self.play(g,FORWARD);q=g.state.pending_choice
        self.assertEqual(len({o.entity_id for o in q.options}),2);self.assertEqual(len({o.id for o in q.options}),2)
        self.choose(g);self.assertEqual(sorted(self.price(g,e.id)for e in self.hand(g)),[2,4])

    def test_forward_empty_fatigues_twice_and_partial_draw_offers_once(self):
        g=self.game((FORWARD,),deck=());self.play(g,FORWARD);self.assertIsNone(g.state.pending_choice)
        self.assertEqual([d.outcome for d in g.state.draw_history],['fatigue','fatigue'])
        g=self.game((FORWARD,),deck=(ONE,));self.play(g,FORWARD);self.assertEqual(len(g.state.pending_choice.options),1)
        self.choose(g);self.assertEqual(self.price(g,self.eid(g,ONE)),0)

    def test_forward_burned_second_is_not_a_choice_and_existing_hand_is_not_added(self):
        g=self.game((FORWARD,)+(PLAIN,)*9,deck=(FOUR,THREE));self.play(g,FORWARD)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],[FOUR])
        self.assertEqual([d.outcome for d in g.state.draw_history],['hand','burned']);self.choose(g)

    def test_forward_extra_trigger_draw_is_not_in_original_group(self):
        g=self.game((FORWARD,),deck=(FOUR,THREE,TWO),board=('k44.watch.extra',));self.play(g,FORWARD)
        self.choose(g,'ok');self.assertEqual([o.card_id for o in g.state.pending_choice.options],[FOUR,TWO])
        self.choose(g);self.assertEqual(self.price(g,self.eid(g,THREE)),3)

    def test_forward_departed_and_redrawn_first_residency_is_not_rebound(self):
        g=self.game((FORWARD,),deck=(FOUR,THREE),board=('k44.watch.cycle',));self.play(g,FORWARD)
        other=self.portable(g)
        for h in (g,other):
            self.choose(h,'ok');self.assertEqual([o.card_id for o in h.state.pending_choice.options],[THREE]);self.choose(h)
            self.assertEqual(self.price(h,self.eid(h,FOUR)),4)
        self.assertEqual(g.snapshot(),other.snapshot())

    def test_forward_replacement_chain_offers_actual_leaf_hand_card(self):
        g=self.game((FORWARD,),deck=('k44.portal',FOUR,THREE));self.play(g,FORWARD)
        self.assertEqual([d.outcome for d in g.state.draw_history],['cast','hand','hand'])
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],[FOUR,THREE]);other=self.portable(g)
        for h in (g,other):self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot())

    def test_choice_wait_restore_invalid_option_and_full_replay(self):
        g=self.game((FORWARD,),deck=(FOUR,THREE));self.play(g,FORWARD);saved=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(IllegalAction):g.apply(SelectChoice(1,q.id,('not-in-group',)))
        self.assertEqual(g.snapshot(),saved);other=self.portable(g)
        for h in (g,other):self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot())

    def test_bribe_gives_original_physical_card_retains_owner_and_local_modifiers(self):
        g=self.game((BRIBE,'k44.reprice'),deck=(TWO,THREE,FOUR));self.play(g,'k44.reprice');ids=g.state.players[1].deck[:]
        self.play(g,BRIBE);q=g.state.pending_choice;self.assertEqual([o.entity_id for o in q.options],ids)
        self.choose(g);s=g.state;e=s.entities[ids[0]]
        self.assertEqual((e.owner,e.controller,e.zone),(1,2,Zone.HAND));self.assertEqual(self.price(g,e.id),1)
        self.assertEqual(len(s.draw_history),3);self.assertFalse(s.discard_history);self.portable(g)

    def test_bribe_full_opponent_hand_burns_original_without_discard_or_death(self):
        g=self.game((BRIBE,),deck=(FOUR,THREE,TWO),enemy_hand=(PLAIN,)*10);self.play(g,BRIBE)
        selected=g.state.pending_choice.options[0].entity_id;self.choose(g);s=g.state
        self.assertEqual(s.entities[selected].zone,Zone.GRAVEYARD);self.assertEqual(s.entities[selected].controller,2)
        self.assertFalse(s.discard_history);self.assertFalse(s.death_history);self.assertEqual(len(s.players[2].hand),10)

    def test_bribe_drawing_player_overflow_only_offers_successful_originals(self):
        g=self.game((BRIBE,)+(PLAIN,)*9,deck=(FOUR,THREE,TWO));self.play(g,BRIBE)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],[FOUR]);self.choose(g)
        self.assertEqual(len(g.state.players[1].hand),9)

    def test_flight_distinct_current_types_skip_typeless_and_buff_after_group(self):
        g=self.game((FLIGHT,),deck=(ONE,ONE,TWO,PLAIN,FIRE));self.play(g,FLIGHT);s=g.state
        self.assertEqual({e.card_id for e in self.hand(g)},{ONE,TWO})
        self.assertTrue(all(e.attack==e.base_attack+1 and e.max_health==e.base_health+1 for e in self.hand(g)))
        self.assertEqual(len(s.draw_history),2);self.assertEqual(s.players[1].fatigue,0);self.portable(g)

    def test_flight_overlap_dual_and_all_are_not_different_types(self):
        for deck in ((ONE,'k44.dual'),(ONE,'k44.all'),('k44.all','k44.all')):
            g=self.game((FLIGHT,),deck=deck);self.play(g,FLIGHT);self.assertEqual(len(g.state.draw_history),1)
            self.assertEqual(len(self.hand(g)),1)

    def test_flight_complete_unknown_tribes_fail_before_random_or_mutation(self):
        g=self.game((FLIGHT,),deck=(ONE,'k44.unknown'));before=g.snapshot();rng=g._rng.getstate()
        with self.assertRaises(ResolutionError)as caught:self.play(g,FLIGHT)
        self.assertIsInstance(caught.exception.__cause__,UnsupportedDefinitionError)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g._rng.getstate(),rng)

    def test_flight_reaction_fills_hand_and_second_draw_burns_without_buff(self):
        g=self.game((FLIGHT,)+(PLAIN,)*9,deck=(ONE,ONE,TWO),board=('k44.watch.fill',));self.play(g,FLIGHT)
        self.choose(g,'ok');draws=g.state.draw_history
        self.assertEqual(len(draws),2);self.assertNotEqual(draws[0].card_id,draws[1].card_id)
        self.assertEqual(draws[1].outcome,'burned')

    def test_flight_burned_first_still_removes_its_tribe_for_second_slot(self):
        g=self.game((FLIGHT,)+(PLAIN,)*9,deck=(ONE,ONE,TWO),board=('k44.fill_commit',));self.play(g,FLIGHT)
        draws=g.state.draw_history;self.assertEqual([d.outcome for d in draws],['burned','burned'])
        self.assertNotEqual(draws[0].card_id,draws[1].card_id);self.assertEqual(len(g.state.players[1].hand),10)

    def test_flight_does_not_apply_reward_between_original_draws(self):
        g=self.game((FLIGHT,),deck=(ONE,TWO),board=('k44.watch.wait',));self.play(g,FLIGHT)
        self.assertEqual([(e.attack,e.max_health)for e in self.hand(g)],[(g.registry.card(g.state.draw_history[0].card_id).attack,g.registry.card(g.state.draw_history[0].card_id).health)])
        other=self.portable(g)
        for h in (g,other):self.choose(h,'ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertTrue(all(e.attack==e.base_attack+1 for e in self.hand(g)))

    def test_hybrid_cost_order_and_missing_tier_do_not_fatigue(self):
        g=self.game((HYBRID,),deck=(FOUR,THREE,TWO,ONE,ONE));self.play(g,HYBRID)
        self.assertEqual([e.card_id for e in self.hand(g)],[ONE,TWO,THREE,FOUR])
        self.assertEqual([self.price(g,e.id)for e in self.hand(g)],[1,2,3,4])
        g=self.game((HYBRID,),deck=(ONE,THREE));self.play(g,HYBRID)
        self.assertEqual([e.card_id for e in self.hand(g)],[ONE,THREE]);self.assertEqual(g.state.players[1].fatigue,0)

    def test_hybrid_current_local_deck_cost_not_printed_cost_selects_tier(self):
        g=self.game((HYBRID,'k44.reprice'),deck=(TWO,THREE));self.play(g,'k44.reprice');self.play(g,HYBRID)
        self.assertEqual([e.card_id for e in self.hand(g)],[TWO,THREE]);self.assertEqual(len(g.state.draw_history),2)

    def test_hybrid_kindred_prior_nature_applies_to_all_four_originals(self):
        g=self.game((HYBRID,NATURE),deck=(ONE,TWO,THREE,FOUR,PLAIN,PLAIN));self.play(g,NATURE)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,HYBRID)
        selected=[e for e in self.hand(g)if e.card_id in (ONE,TWO,THREE,FOUR)]
        drawn={d.entity_id for d in g.state.draw_history if d.source_id is not None and g.state.entities[d.source_id].card_id==HYBRID}
        self.assertTrue(drawn);self.assertTrue(all(self.price(g,e.id)==g.registry.card(e.card_id).cost-1 for e in selected if e.id in drawn));self.portable(g)

    def test_hybrid_same_turn_nature_does_not_enable_kindred(self):
        g=self.game((HYBRID,NATURE));self.play(g,NATURE);self.play(g,HYBRID)
        self.assertEqual([self.price(g,e.id)for e in self.hand(g)],[1,2,3,4])

    def test_armaments_requires_actual_opening_and_rolls_back_unknown_scenario(self):
        g=self.game((ARMS,),deck=(FIRE,NATURE));before=g.snapshot()
        with self.assertRaises(ResolutionError)as caught:self.play(g,ARMS)
        self.assertIsInstance(caught.exception.__cause__,UnsupportedDefinitionError)
        self.assertEqual(g.snapshot(),before)

    def test_armaments_real_opening_same_named_original_and_created_are_different(self):
        g=self.match();original=set(g.state.opening.original_entities[0]);source=self.play(g,ARMS);rows=[d for d in g.state.draw_history if d.source_id==source]
        self.assertEqual(len(rows),2);self.assertIn(rows[0].entity_id,original);self.assertNotIn(rows[1].entity_id,original)
        self.assertEqual(rows[0].card_id,rows[1].card_id);self.portable(g)

    def test_armaments_copy_and_explicit_face_replacement_are_outside(self):
        g=self.match();self.play(g,'k44.copy');self.play(g,'k44.transform');source=self.play(g,ARMS);s=g.state
        rows=[d for d in s.draw_history if d.source_id==source];self.assertEqual(len(rows),2)
        self.assertFalse(s.entities[rows[0].entity_id].face_replaced)
        self.assertTrue(s.entities[rows[1].entity_id].face_replaced or rows[1].entity_id not in s.opening.original_entities[0])

    def test_armaments_foreign_starting_entity_is_outside_my_deck(self):
        g=self.match();self.play(g,'k44.foreign');source=self.play(g,ARMS);s=g.state;rows=[d for d in s.draw_history if d.source_id==source]
        self.assertEqual(len(rows),2);self.assertNotIn(rows[1].entity_id,s.opening.original_entities[0])

    def test_group_structural_contracts_reject_invalid_slots_rewards_and_missing_arrival(self):
        for make in (lambda:DrawGroupSlot(current_cost=1),lambda:DrawGroupSlot(PoolQuery(),different_tribes=True),
            lambda:DrawGroupReward('none',1),lambda:DrawGroupReward('cost_one',0),
            lambda:ContinuePhysicalDrawGroup(1,1,(DrawGroupSlot(),),index=1),
            lambda:DrawGroupArrival(0,None,CardReference(1,1,Zone.HAND,ONE,0))):
            with self.assertRaises(ValueError):make()

    def test_group_codec_rejects_wrong_source_and_future_hand_reference(self):
        g=self.game((FORWARD,),deck=(FOUR,THREE),board=('k44.watch.wait',));source=self.play(g,FORWARD);s=g.state
        capture=CapturePhysicalDrawGroup(1,source,(DrawGroupSlot(),)*2,draw_id=s.draw_history[0].id,hand_cursor=len(s.hand_entries)-1)
        codec=FrameCodec(default_mechanics(),g.registry,origin_state=s)
        self.assertEqual(codec.decode(codec.encode(capture)),capture)
        with self.assertRaises(ValueError):codec.encode(replace(capture,source_id=s.players[2].hero_id))
        with self.assertRaises(ValueError):codec.encode(replace(capture,hand_cursor=len(s.hand_entries)+1))
        bad=self.game(('k44.bad_source',));before=bad.snapshot()
        with self.assertRaises(ValueError):self.play(bad,'k44.bad_source')
        self.assertEqual(bad.snapshot(),before)

    def test_group_frame_rejects_changed_original_completed_reference(self):
        g=self.game((FORWARD,),deck=(FOUR,THREE));source=self.play(g,FORWARD);s=g.state;record=s.draw_history[0]
        ref=CardReference.capture(s.entities[record.entity_id]);cursor=next(i for i,e in enumerate(s.hand_entries)if e.entity_id==ref.entity_id and e.reason=='draw')
        row=DrawGroupArrival(0,record.id,ref,hand_cursor=cursor)
        request=ContinuePhysicalDrawGroup(1,source,(DrawGroupSlot(),)*2,DrawGroupReward('cost_one',2),1,(row,))
        validate_material(s,g.registry,request,completed=True)
        wrong=replace(row,hand=replace(ref,zone_epoch=ref.zone_epoch+1))
        with self.assertRaises(ValueError):validate_material(s,g.registry,replace(request,arrivals=(wrong,)))

    def test_draw_wait_failure_rolls_back_and_native_group_survives_json(self):
        g=self.game((FORWARD,),deck=(FOUR,THREE),board=('k44.watch.wait',));self.play(g,FORWARD);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);other=self.portable(g)
        for h in (g,other):self.choose(h,'ok');self.choose(h)
        self.assertEqual(g.snapshot(),other.snapshot())

    def test_opponent_cannot_observe_private_draw_group_options_or_materials(self):
        g=self.game((FORWARD,),deck=(FOUR,THREE));self.play(g,FORWARD)
        own=g.for_player(1).observe();other=g.for_player(2).observe();text=json.dumps(other,ensure_ascii=False)
        self.assertNotIn(FOUR,text);self.assertNotIn(THREE,text)
        for key in ('hand_cursor','DrawGroupArrival','draw_id','zone_epoch','starting_deck','reward'):
            self.assertNotIn(key,text)
        self.assertIn(FOUR,json.dumps(own,ensure_ascii=False))
        self.assertEqual(g.for_player(2).legal_actions()['actions'],[{'type':'concede'}])

    def test_previous_core_snapshot_is_rejected(self):
        from pathlib import Path
        from hs_sim.engine.representative import build_registry as representative
        path=Path(__file__).resolve().parents[1]/'tests/fixtures/history/card-integration-20261014/k44-before/default-snapshot-core344-schema275.json'
        with self.assertRaises(SnapshotError):Game.from_snapshot(json.loads(path.read_text(encoding='utf-8')),representative())


if __name__=='__main__':unittest.main()
