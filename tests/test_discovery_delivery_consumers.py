"""Native Vault Breaker and actual original delivery producers, no pool pruning."""
from dataclasses import replace
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import unittest

from hs_sim.cards.native_discovery_delivery_cards import CARD, load_batch, register_native_discovery_delivery_cards
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, PlayCard,
    PlayerSetup, Rarity, Registry, Scenario, SelectChoice, SnapshotError, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy, InvokeBehavior,
    RequestChoice, Silence)
from hs_sim.engine.model import (ChoicePurpose, CostSpec, LimitedTriggerSpec, SummonQuantitySpec,
    SummonStats, Keyword, RewindSpec)
from hs_sim.engine.pools import (DiscoverFromPool, DiscoveryGiftPool, GenerateFromPool,
    GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery)
from hs_sim.engine.discovery_delivery import COMPLETED, QUEUED, original_recipient, validate_boundary
from hs_sim.engine.dark_gifts import DARK_GIFTS, LIVING_NIGHTMARE_BEHAVIOR, living_nightmare
from hs_sim.engine.hand_choice_followups import DiscoverForPlayFollowup
from hs_sim.engine.stored_gift_discovery import DiscoverDeckDarkGift
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference, ChooseFromZone, MoveCard, ModifyStoredCost
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.serialization import canonical_hash

P = 'k174.'
HERO, A, B, C, DUPE = (P+x for x in ('hero','a','b','c','quantity'))
DISC, ALL, EACH, DECK, TEMP, GIFT, GIFT_COPY, REMAIN, HAND_COPY, BOARD, BOARD_COPY, STORED, MAP, MAP_TAKE, DEAD, AUTO, GEN, MENU, TAKE, COPY, TOP, DISCARD, BOOST, KILL, MUTE = (
    P+x for x in ('discover','all','each','deck','temporary','gift','gift-copy','remainder','hand-copy','board','board-copy','stored','map','map-take','dead','auto','generate','menu','take','copy','top','discard','boost','kill','mute'))
CONTEXT = GenerationContext('k174-native-delivery', 'experimental')
META = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=('dragon',))
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True)
POOL = P+'pool'
PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@lru_cache(maxsize=None)
def registry(mode='plain', role='writer', pin=PIN):
    if role not in ('writer','reader') or pin != PIN: raise ValueError('Immutable independent fixture key required')
    r = Registry('k174-native-'+mode)
    register_native_discovery_delivery_cards(r)
    r.register_behavior(P+'noop', lambda c: ())
    for cid in (A,B,C):
        d = CardDefinition(cid,cid,CardType.MINION,cost=4,attack=4,health=5,battlecry=P+'noop',
            dormant_turns=2 if mode=='dormant' and cid==A else 0,
            metadata=replace(META,rarity=Rarity.LEGENDARY) if mode=='remainder' else META)
        r.register_card(d); r.register_pool_card(PoolCard.from_definition(d))
    r.register_card(CardDefinition(DUPE,DUPE,CardType.MINION,health=5,summon_quantities=(SummonQuantitySpec(2),)))
    r.register_pool(PoolDefinition(POOL,'v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(i) for i in (A,B,C)),complete=True))
    gifts=DiscoveryGiftPool(P+'gifts','v1',CONTEXT.target_id,CONTEXT.mode,
        tuple(g for g in DARK_GIFTS if g.id in ('EDR_100t','EDR_100t3','EDR_100t8')),complete=True)
    def discover(c,**kw): return DiscoverFromPool(c.player_id,POOL,QUERY,source_id=c.source_id,**kw)
    def zone(c,operation,owner=None,zone=Zone.DECK):
        return ChooseFromZone(c.player_id,c.player_id if owner is None else owner,zone,operation=operation,
            distinct='entity',source_id=c.source_id,discovery=True)
    def dead(c):
        rows=[d for d in c.state.death_history if d.controller==c.player_id and d.card_id in (A,B,C)]
        options=tuple(ChoiceOption(str(d.id),d.card_id,(ResurrectMinion(c.player_id,d.id,source_id=c.source_id,cause=SummonCause.capture(c)),),card_id=d.card_id)for d in rows)
        return (RequestChoice(c.player_id,options,c.source_id,purpose=ChoicePurpose.CARD_DISCOVERY),) if options else ()
    bodies={
        DISC:lambda c:(discover(c),), ALL:lambda c:(discover(c,discoveries=2,delivery='after_all'),),
        EACH:lambda c:(discover(c,discoveries=2),), DECK:lambda c:(discover(c,destination='deck',position='top'),),
        TEMP:lambda c:(discover(c,temporary_until_turn=c.state.turn),),
        GIFT:lambda c:(discover(c,gift_pool=gifts),), GIFT_COPY:lambda c:(discover(c,gift_pool=gifts,gift_copy_to_hand=True),),
        REMAIN:lambda c:(DiscoverFromPool(c.player_id,POOL,replace(QUERY,rarities=(Rarity.LEGENDARY,)),source_id=c.source_id,shuffle_unselected_into_deck=True),),
        HAND_COPY:lambda c:(discover(c,summon_copy_stats=SummonStats(2,3),cause=SummonCause.capture(c)),),
        BOARD:lambda c:(discover(c,destination='board',cause=SummonCause.capture(c)),),
        BOARD_COPY:lambda c:(discover(c,destination='board',cause=SummonCause.capture(c),copy_selected_to_hand=True),),
        STORED:lambda c:(DiscoverDeckDarkGift(c.player_id,c.source_id),),
        MAP:lambda c:(DiscoverForPlayFollowup(discover(c)),), MAP_TAKE:lambda c:(DiscoverForPlayFollowup(zone(c,'take')),),
        DEAD:dead, AUTO:lambda c:(CastSpell(c.player_id,DISC,c.source_id),),
        GEN:lambda c:(GenerateFromPool(c.player_id,POOL,QUERY,source_id=c.source_id),),
        MENU:lambda c:(RequestChoice(c.player_id,(ChoiceOption('a','a',(AddToHand(c.player_id,A,c.source_id),),card_id=A),),c.source_id),),
        TAKE:lambda c:(zone(c,'take'),), COPY:lambda c:(zone(c,'copy_current'),),
        TOP:lambda c:(zone(c,'top',3-c.player_id),), DISCARD:lambda c:(zone(c,'discard',3-c.player_id,Zone.HAND),),
        BOOST:lambda c:(ModifyStoredCost(CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]]),CostSpec(delta=-1),c.source_id),),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        MUTE:lambda c:(Silence(c.target_id),),
    }
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        from hs_sim.engine.model import TargetSpec
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=TargetSpec() if cid in(KILL,MUTE) else None))
    hero_extra={}
    if mode in ('duplicate','acquire','completed','fail_acquire','fill_before'):
        event=COMPLETED if mode=='completed' else 'choice_selected' if mode=='fill_before' else 'card_added_to_hand'
        r.register_trigger_condition(P+'condition',lambda c:c.event.player_id==c.player_id and
            c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==DISC)
        def fail(c): raise ResolutionError('Deliberate original delivery failure')
        r.register_behavior(P+'fail',fail)
        def reenter(c):return (MoveCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,Zone.HAND,source_id=c.source_id),)
        r.register_behavior(P+'reenter',reenter)
        def watch(c):
            if mode in('duplicate','fill_before'):return (AddToHand(c.player_id,A,c.source_id),)
            if mode=='fail_acquire':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            target=c.state.entities[c.event.target_id]
            source=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD)
            return (RequestChoice(c.player_id,(
                ChoiceOption('ok','Continue'),
                ChoiceOption('leave','Original leaves and returns',(MoveCard(CardReference.capture(target),c.player_id,Zone.DECK,source_id=c.source_id),InvokeBehavior(P+'reenter',c.source_id,c.player_id,target.id))),
                ChoiceOption('kill','Destroy original Breaker',(Destroy(source,c.source_id),)),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(P+'watch',watch)
        hero_extra['limited_triggers']=(LimitedTriggerSpec(event,P+'watch',condition_id=P+'condition'),)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,metadata=replace(META,collectible=False,classes=(CardClass.MAGE,)),**hero_extra))
    r.validate(); r.freeze(); return r


def game(hand=(DISC,),*,mode='plain',pid=1,board=(CARD,),other_hand=(),deck=(A,B,C)):
    setup=tuple(PlayerSetup(HERO,hand=hand if p==pid else other_hand,board=board if p==pid else (),deck=deck,
        mana=60,max_mana=60,mana_cap=60)for p in(1,2))
    return Game.from_scenario(Scenario(setup,active_player=pid,seed=174,generation_context=CONTEXT),registry(mode))


def first(g,cid,zone='hand',pid=None):
    pid=g.state.active_player if pid is None else pid
    return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)


def play(g,cid,target=None):
    e=first(g,cid);g.apply(PlayCard(g.state.active_player,e.id,target_id=target,position=len(g.state.players[g.state.active_player].board)if e.kind==CardType.MINION else None));return e.id


def choose(g,cid=None,key=None):
    q=g.state.pending_choice;o=next(o for o in q.options if (key is None or o.id==key)and(cid is None or o.card_id==cid))
    g.apply(SelectChoice(q.player_id,q.id,(o.id,)));return o.card_id


def completions(g):return [e for e in g.events if e.kind==COMPLETED]


def portable(test,g,mode='plain'):
    reader=registry(mode,'reader');test.assertIsNot(reader,g.registry);saved=json.loads(json.dumps(g.snapshot()))
    test.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved);test.assertEqual(g.clone().snapshot(),saved)
    test.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
    return saved


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
    return saved


class DiscoveryDeliveryConsumerTests(unittest.TestCase):
    def test_a0_native_full_source_and_default_entry_have_real_three_two_four(self):
        from tools.card_batch import check_face
        d=load_batch();row=d['cards'][0]['record']
        for o in d['official_observations']:check_face(row,o['face'],o['locale'])
        self.assertEqual((len(d['cards']),len(d['official_observations'])),(1,2))
        g=game((CARD,),board=());eid=play(g,CARD);e=g.state.entities[eid]
        self.assertEqual((e.cost,e.attack,e.health,g.state.players[1].mana),(3,2,4,57))

    def test_a1_same_face_acquisition_copy_never_takes_the_original_discount(self):
        g=game(mode='duplicate');play(g,DISC);choose(g,A)
        cards=[g.state.entities[i]for i in g.state.players[1].hand]
        self.assertEqual([e.cost for e in cards],[3,4]);self.assertEqual([e.card_id for e in cards],[A,A])
        event,=completions(g);self.assertEqual(original_recipient(g.state,event).entity_id,cards[0].id)
        portable(self,g,'duplicate')

    def test_a2_two_same_faces_after_all_keep_original_receipts_and_separate_costs(self):
        g=game((ALL,));play(g,ALL);choose(g,A);self.assertEqual(g.state.players[1].hand,[]);portable(self,g)
        choose(g,A);self.assertEqual([g.state.entities[i].cost for i in g.state.players[1].hand],[3,3])
        self.assertEqual(len(completions(g)),2);self.assertEqual(len({dict(e.data)['choice_id']for e in completions(g)}),2)

    def test_a3_after_each_second_actor_and_automatic_spell_have_real_own_discoveries(self):
        for source,pid in((EACH,2),(AUTO,1)):
            g=game((source,),pid=pid);play(g,source)
            while g.state.pending_choice:choose(g,A)
            self.assertTrue(all(g.state.entities[i].cost==3 for i in g.state.players[pid].hand))
            self.assertTrue(all(e.player_id==pid for e in completions(g)))
        portable(self,g)

    def test_a4_independent_sources_stack_silence_retires_and_opponent_is_not_the_discoverer(self):
        g=game(board=(CARD,CARD));play(g,DISC);choose(g,A)
        self.assertEqual(first(g,A).cost,2)
        g=game((MUTE,DISC));play(g,MUTE,first(g,CARD,'board').id);play(g,DISC);choose(g,A)
        self.assertEqual(first(g,A).cost,4)
        g=Game.from_scenario(Scenario((PlayerSetup(HERO,board=(CARD,),deck=(A,B,C)),
            PlayerSetup(HERO,hand=(DISC,),deck=(A,B,C))),active_player=2,seed=174,generation_context=CONTEXT),registry())
        play(g,DISC);choose(g,A);self.assertEqual(first(g,A).cost,4);portable(self,g)

    def test_b0_deck_and_temporary_generated_cards_use_original_fact_and_creation_cost(self):
        for source in(DECK,TEMP):
            g=game((source,));play(g,source);choose(g,A);event,=completions(g);fact=original_recipient(g.state,event)
            self.assertEqual(g.state.entities[fact.entity_id].cost,3)
            self.assertEqual(fact.zone,Zone.DECK if source==DECK else Zone.HAND)
            portable(self,g)

    def test_b1_sweet_gift_primary_deck_reduction_does_not_create_a_second_discovery_for_copy(self):
        g=game((GIFT_COPY,));play(g,GIFT_COPY)
        q=g.state.pending_choice;opt=next(o for o in q.options if '甜美梦境' in o.label);choose(g,key=opt.id)
        event,=completions(g);fact=original_recipient(g.state,event)
        self.assertEqual(fact.zone,Zone.DECK);self.assertEqual(g.state.entities[fact.entity_id].cost,opt.preview.cost-1)
        copy=first(g,opt.card_id);self.assertEqual(copy.cost,opt.preview.cost);self.assertNotEqual(copy.id,fact.entity_id)
        portable(self,g)

    def test_b2_hand_plus_summoned_copy_has_one_discovery_and_one_original_hand_discount(self):
        g=game((HAND_COPY,));play(g,HAND_COPY);choose(g,A)
        event,=completions(g);fact=original_recipient(g.state,event)
        self.assertEqual((fact.zone,g.state.entities[fact.entity_id].cost),(Zone.HAND,3))
        body=first(g,A,'board');self.assertEqual((body.attack,body.health),(2,3));self.assertNotEqual(body.id,fact.entity_id)
        portable(self,g)

    def test_b3_remainder_shuffle_keeps_the_actual_selected_recipient(self):
        g=game((REMAIN,),mode='remainder');play(g,REMAIN);choose(g,A)
        event,=completions(g);fact=original_recipient(g.state,event)
        self.assertEqual((fact.zone,g.state.entities[fact.entity_id].cost),(Zone.HAND,3))
        self.assertEqual(len(g.state.players[1].deck),5)
        portable(self,g,'remainder')

    def test_b4_original_overflow_keeps_burned_recipient_and_never_discounts_an_existing_same_face(self):
        g=game((DISC,)+(A,)*9,mode='fill_before');play(g,DISC);choose(g,A)
        event,=completions(g);fact=original_recipient(g.state,event)
        self.assertEqual((fact.zone,g.state.entities[fact.entity_id].cost),(Zone.GRAVEYARD,4))
        self.assertEqual(len(g.state.players[1].hand),10)
        self.assertTrue(all(g.state.entities[i].cost==4 for i in g.state.players[1].hand))
        portable(self,g,'fill_before')

    def test_c0_physical_take_copy_top_and_discard_retain_original_chooser_and_body(self):
        for source in(TAKE,COPY,TOP,DISCARD):
            g=game((source,),other_hand=(A,));original=first(g,A,'hand'if source==DISCARD else'deck',2 if source in(TOP,DISCARD) else 1).id
            play(g,source);choose(g,A);event,=completions(g);fact=original_recipient(g.state,event)
            self.assertEqual(event.player_id,1);self.assertEqual(fact.entity_id==original,source!=COPY)
            self.assertEqual(g.state.entities[fact.entity_id].cost,4 if source==DISCARD else 3)
            portable(self,g)

    def test_c1_current_physical_copy_keeps_original_cost_material_then_adds_its_own_reduction(self):
        g=game((BOOST,COPY));original=first(g,A,'deck').id;play(g,BOOST);play(g,COPY);choose(g,A)
        copy=first(g,A);self.assertEqual((g.state.entities[original].cost,copy.cost),(3,2));self.assertNotEqual(original,copy.id)

    def test_c2_stored_gift_moves_actual_selected_entity_and_uses_original_visible_material(self):
        g=game((STORED,));ids=set(g.state.players[1].deck);play(g,STORED);q=g.state.pending_choice;opt=q.options[0]
        choose(g,key=opt.id);event,=completions(g);fact=original_recipient(g.state,event)
        self.assertIn(fact.entity_id,ids);self.assertEqual(g.state.entities[fact.entity_id].cost,max(0,opt.preview.cost-1))
        portable(self,g)

    def test_d0_map_initial_discovery_discount_survives_play_but_reward_is_not_a_new_discovery(self):
        for source in(MAP,MAP_TAKE):
            g=game((source,));play(g,source);choose(g,A);self.assertEqual(first(g,A).cost,3)
            portable(self,g);play(g,A);self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.EFFECT)
            choose(g,B);self.assertEqual(len(completions(g)),1);self.assertEqual(first(g,B).cost,4)

    def test_d1_board_quantity_only_discounts_the_original_first_selected_body(self):
        g=game((BOARD,),board=(CARD,DUPE));play(g,BOARD);choose(g,A)
        bodies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==A]
        self.assertEqual([e.cost for e in bodies],[3,4]);event,=completions(g)
        self.assertEqual(original_recipient(g.state,event).entity_id,bodies[0].id);portable(self,g)

    def test_d2_board_copy_and_no_capacity_keep_one_discovery_and_primary_scope(self):
        for full in(False,True):
            g=game((BOARD_COPY,),board=(CARD,)+(A,)*6 if full else(CARD,));play(g,BOARD_COPY);choose(g,A)
            event,=completions(g);fact=original_recipient(g.state,event)
            self.assertEqual(first(g,A).cost,4)
            if full:self.assertIsNone(fact)
            else:self.assertEqual(g.state.entities[fact.entity_id].cost,3)
            portable(self,g)

    def test_d3_still_dormant_original_board_card_accepts_only_its_own_cost_attachment(self):
        g=game((BOARD,),mode='dormant');play(g,BOARD);choose(g,A);e=first(g,A,'board')
        self.assertFalse(e.active);self.assertIsNotNone(e.dormancy);self.assertEqual(e.cost,3);portable(self,g,'dormant')

    def test_d4_selected_death_resurrection_uses_returned_original_root_and_real_first_body(self):
        g=game((KILL,DEAD),board=(CARD,A));old=first(g,A,'board').id;play(g,KILL,old);play(g,DEAD);choose(g,A)
        event,=completions(g);fact=original_recipient(g.state,event)
        self.assertNotEqual(fact.entity_id,old);self.assertEqual((fact.zone,g.state.entities[fact.entity_id].cost),(Zone.BOARD,3))
        portable(self,g)

    def test_e0_acquisition_wait_restores_owed_completion_and_fail_rolls_back_before_cost(self):
        g=game(mode='acquire');play(g,DISC);choose(g,A)
        self.assertEqual(completions(g),[]);self.assertEqual(first(g,A).cost,4);saved=portable(self,g,'acquire')
        with self.assertRaises(ResolutionError):choose(g,key='fail')
        self.assertEqual(g.snapshot(),saved);choose(g,key='ok');self.assertEqual(first(g,A).cost,3)

    def test_e1_source_departing_before_notification_cancels_new_listener_capture(self):
        g=game(mode='acquire');play(g,DISC);choose(g,A);choose(g,key='kill')
        self.assertEqual(first(g,A).cost,4);self.assertEqual(len(completions(g)),1);portable(self,g,'acquire')

    def test_e2_already_captured_discount_survives_source_death_but_not_original_same_id_reentry(self):
        for key,expected in(('kill',3),('leave',4)):
            g=game(mode='completed');play(g,DISC);choose(g,A);self.assertIsNotNone(g.state.pending_choice)
            portable(self,g,'completed');choose(g,key=key);self.assertEqual(first(g,A).cost,expected)
            portable(self,g,'completed')

    def test_e3_acquisition_exception_restores_original_unselected_choice_and_rng(self):
        g=game(mode='fail_acquire');play(g,DISC);saved=g.snapshot()
        with self.assertRaises(ResolutionError):choose(g,A)
        self.assertEqual(g.snapshot(),saved);self.assertEqual(g.state.card_discovery_history,[])

    def test_f0_rehashed_missing_owed_completion_and_actual_recipient_cannot_restore(self):
        g=game(mode='acquire');play(g,DISC);choose(g,A);saved=json.loads(json.dumps(g.snapshot()))
        def rewrite(value):
            if isinstance(value,dict):
                if value.get('type')=='hs_sim.engine.discovery_delivery.FinishCardDiscovery':
                    value['fields']['completion']['fields']['recipient']['fields']['entity_id']=first(g,A,'deck').id
                else:
                    for child in value.values():rewrite(child)
            elif isinstance(value,list):
                for child in value:rewrite(child)
        rewrite(saved)
        with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(rehash(saved),registry('acquire','reader'))

    def test_f1_generation_generic_menu_and_player_information_do_not_invent_discoveries(self):
        for source in(GEN,MENU):
            g=game((source,));play(g,source)
            if g.state.pending_choice:choose(g,A)
            self.assertEqual(completions(g),[]);self.assertEqual(first(g,A).cost,4)
        g=game();play(g,DISC);choose(g,A)
        for pid in(1,2):
            visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for key in('receipt','source_allocation','resolution_frame','card_discovery_history','rng_state'):
                self.assertNotIn('"'+key+'"',visible)

    def test_f2_previous_snapshot_schema_rejects_without_migrating_original_work(self):
        g=game();saved=g.snapshot();saved['schema_version']=377
        with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(saved,g.registry)


if __name__=='__main__':unittest.main()
