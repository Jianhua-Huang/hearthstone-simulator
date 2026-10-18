"""Real Jumpscare and original per-slot gifts through one semantic shuffle."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_gift_remainder_cards import CARD,BODY,QUERY,load_batch,register_native_gift_remainder_cards
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,Game,PlayCard,PlayerSetup,
    Rarity,Registry,RewindSpec,Keyword,Scenario,SelectChoice,Zone)
from hs_sim.engine.dark_gifts import DARK_GIFTS,public_gifts
from hs_sim.engine.pools import (DiscoverFromPool,DiscoveryGiftPool,GenerationContext,PoolCard,PoolDefinition,PoolMember)
from hs_sim.engine.effects import AddToHand,ChoiceOption,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.errors import ResolutionError,SnapshotError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.costs import local_cost
from hs_sim.engine.zones import CardReference,MoveCard
from hs_sim.engine.discovery_offers import offer_for_result
from hs_sim.engine.serialization import canonical_hash

P='k178.'
HERO,FILL,DISC,RETRY,DRAW=(P+x for x in('hero','filler','discover','retry','draw'))
MEMBERS=tuple(P+x for x in('a','b','c'))
CTX=GenerationContext('k178-gifts','experimental')
GIFTS={g.id:g for g in DARK_GIFTS}

@lru_cache(maxsize=60)
def registry(role='writer',gift='full',mode='normal',stone=False):
    r=Registry('k178-'+gift+'-'+mode)
    register_native_gift_remainder_cards(r)
    if stone:
        from hs_sim.cards.native_origin_stone_cards import register_native_origin_stone_cards
        register_native_origin_stone_cards(r)
    r.register_behavior(P+'bc',lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,
        metadata=CardMetadata(False,(CardClass.MAGE,),Rarity.NONE,tribes=())))
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,attack=1,health=3))
    for cid,cost,tribes,cls in ((MEMBERS[0],5,('demon',),CardClass.NEUTRAL),
            (MEMBERS[1],7,('demon',),CardClass.NEUTRAL),(MEMBERS[2],9,('demon',),CardClass.MAGE),
            (P+'low',4,('demon',),CardClass.NEUTRAL),(P+'beast',6,('beast',),CardClass.NEUTRAL),
            (P+'other',6,('demon',),CardClass.WARRIOR),(P+'unknown',5,('demon',),CardClass.NEUTRAL)):
        d=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=4,health=5,battlecry=P+'bc',
            metadata=CardMetadata(True,(cls,),Rarity.COMMON,tribes=tribes))
        if not cid.endswith('unknown'):r.register_card(d)
        r.register_pool_card(PoolCard.from_definition(d))
    members=(MEMBERS[:1]if mode=='one'else MEMBERS[:2]if mode=='two'else()if mode=='empty'else MEMBERS)
    members+=tuple(P+x for x in('low','beast','other'))
    if mode=='unknown':members+=(P+'unknown',)
    r.register_pool(PoolDefinition('constructed.cards','k178',CTX.target_id,CTX.mode,
        tuple(PoolMember(x)for x in members),complete=True))
    chosen=DARK_GIFTS if gift=='full'else(tuple([GIFTS[gift]]+
        [g for g in DARK_GIFTS if g.id!=gift and g.id in('EDR_100t1','EDR_100t3','EDR_100t13')][:2]))
    pool=DiscoveryGiftPool(P+'gifts','v1',CTX.target_id,CTX.mode,chosen,complete=True)
    r.register_behavior(P+'discover',lambda c:(DiscoverFromPool(c.player_id,'constructed.cards',QUERY,
        source_id=c.source_id,gift_pool=pool,shuffle_unselected_into_deck=True),))
    r.register_card(CardDefinition(DISC,DISC,CardType.SPELL,cost=2,on_play=P+'discover'))
    r.register_card(CardDefinition(RETRY,RETRY,CardType.SPELL,cost=2,on_play=P+'discover',
        keywords=(Keyword.REWIND,),rewind=RewindSpec()))
    def draw(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id in MEMBERS)
        return(MoveCard(CardReference.capture(e),c.player_id,Zone.HAND,draw=True,source_id=c.source_id),)
    r.register_behavior(DRAW,draw);r.register_card(CardDefinition(DRAW,DRAW,CardType.SPELL,on_play=DRAW))
    def fail(c):raise ResolutionError('k178 original insertion failure')
    r.register_behavior(P+'fail',fail)
    for action,event in (('wait_hand','card_added_to_hand'),('wait_deck','card_added_to_deck'),
            ('fail_deck','card_added_to_deck'),('fill','choice_selected')):
        def condition(c,action=action):
            return c.event.player_id==c.player_id and(c.event.source_id is not None and
                c.state.entities[c.event.source_id].card_id in(CARD,DISC,RETRY)if action=='fill'else
                c.event.target_id is not None and c.state.entities[c.event.target_id].card_id in MEMBERS)
        r.register_trigger_condition(P+action,condition)
        def watch(c,action=action):
            if action=='fill':return(AddToHand(c.player_id,FILL,c.source_id),)
            if action=='fail_deck':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),)
        r.register_behavior(P+action,watch)
        r.register_card(CardDefinition(P+action,P+action,CardType.MINION,health=4,
            limited_triggers=(LimitedTriggerSpec(event,P+action,condition_id=P+action),)))
    r.validate();r.freeze();return r

def game(gift='full',mode='normal',hand=(CARD,),board=(),context=CTX,stone=False):
    return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=(FILL,)*3,
        mana=40,max_mana=40,mana_cap=40),PlayerSetup(HERO,deck=(FILL,)*3)),seed=178,
        generation_context=context),registry('writer',gift,mode,stone))

def play(g,cid=CARD):
    e=next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
    g.apply(PlayCard(1,e.id,position=len(g.state.players[1].board)if e.kind==CardType.MINION else None))
    return e.id

def select(g,key):
    q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

def pick_gift(g,gift):
    offer=g._frame.original_discovery_offer
    o=next(o for o in offer.options if o.effects[0].selection.gift.id==gift)
    select(g,o.id);return o.card_id

class NativeGiftRemainderTests(unittest.TestCase):
    def portable(self,g,gift='full',mode='normal',stone=False):
        saved=g.snapshot();reader=registry('reader',gift,mode,stone);self.assertIsNot(reader,g.registry)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)),reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        for pid in(1,2):
            visible=json.dumps(g.observe(pid))+json.dumps(g.player_events(pid))+json.dumps(g.for_player(pid).legal_actions())
            for key in('receipt','original_offer','offered_gifts','resolution_frame','rng_state'):
                self.assertNotIn('"'+key+'"',visible)

    def check_material(self,e,cid,gift):
        self.assertEqual(e.card_id,cid);d=GIFTS[gift]
        self.assertEqual((e.attack,e.max_health),(max(0,4+d.grant.attack),5+d.grant.health))
        self.assertEqual(local_cost(e)[0],max(0,{'k178.a':5,'k178.b':7,'k178.c':9}[cid]+d.cost_delta))
        self.assertEqual([x['id']for x in public_gifts(e)],[gift])

    def test_01_native_complete_actual_paired_menu_and_single_semantic_shuffle(self):
        g=game();source=play(g);self.assertEqual(set(o.card_id for o in g.state.pending_choice.options),set(MEMBERS))
        original=g._frame.original_discovery_offer;self.portable(g)
        selected=original.options[0];select(g,selected.id);self.assertEqual(g.state.players[1].mana,38)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.card_discovery_history),1)
        self.assertEqual([x.declared_count for x in g.state.deck_shuffle_history],[2])
        inserted=[e.target_id for e in g.events if e.kind=='card_added_to_deck'and e.source_id==source
            and dict(e.data).get('deck_insertion',(None,))[0]=='random']
        other=[o for o in original.options if o.id!=selected.id]
        self.assertEqual(len(inserted),2)
        for eid,o in zip(inserted,other):self.check_material(g.state.entities[eid],o.card_id,o.effects[0].selection.gift.id)
        self.portable(g)

    def test_02_all_ten_real_gifts_keep_selected_and_each_unselected_original_material(self):
        for gift in GIFTS:
            with self.subTest(gift=gift):
                g=game(gift,hand=(DISC,));play(g,DISC);original=g._frame.original_discovery_offer
                cid=pick_gift(g,gift);self.assertIsNone(g.state.pending_choice)
                e=next(e for e in g.state.entities.values()if e.card_id==cid)
                self.check_material(e,cid,gift);self.assertEqual(e.zone,Zone.DECK if gift=='EDR_100t8'else Zone.HAND)
                for o in original.options:
                    actual=next(e for e in g.state.entities.values()if e.card_id==o.card_id)
                    self.check_material(actual,o.card_id,o.effects[0].selection.gift.id)
                self.portable(g,gift)

    def test_03_original_hand_acquisition_wait_survives_independent_restore(self):
        gift='EDR_100t2';g=game(gift,hand=(DISC,),board=(P+'wait_hand',));play(g,DISC);pick_gift(g,gift)
        self.assertIsNotNone(g.state.pending_choice);self.assertFalse(g.state.deck_shuffle_history)
        self.portable(g,gift);select(g,'ok');self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.deck_shuffle_history[0].declared_count,2);self.portable(g,gift)

    def test_04_sweet_dreams_deck_delivery_wait_is_before_remainder_shuffle(self):
        gift='EDR_100t8';g=game(gift,hand=(DISC,),board=(P+'wait_deck',));play(g,DISC);pick_gift(g,gift)
        self.assertIsNotNone(g.state.pending_choice);self.assertFalse(g.state.deck_shuffle_history)
        self.portable(g,gift);select(g,'ok');self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.deck_shuffle_history[0].declared_count,2);self.portable(g,gift)

    def test_05_whole_remainder_installs_before_its_first_deck_reaction(self):
        gift='EDR_100t2';g=game(gift,hand=(DISC,),board=(P+'wait_deck',));play(g,DISC);pick_gift(g,gift)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.deck_shuffle_history[0].declared_count,2)
        self.portable(g,gift);select(g,'ok');self.assertIsNone(g.state.pending_choice);self.portable(g,gift)

    def test_06_full_hand_burns_only_chosen_hand_card_and_keeps_gifted_remainder(self):
        gift='EDR_100t2';g=game(gift,hand=(DISC,)+(FILL,)*9,board=(P+'fill',));play(g,DISC);cid=pick_gift(g,gift)
        e=next(e for e in g.state.entities.values()if e.card_id==cid);self.assertEqual(e.zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.deck_shuffle_history[0].declared_count,2);self.portable(g,gift)

    def test_07_insertion_failure_rolls_back_to_exact_original_paired_menu(self):
        gift='EDR_100t2';g=game(gift,hand=(DISC,),board=(P+'fail_deck',));play(g,DISC);before=g.snapshot()
        with self.assertRaises(ResolutionError):pick_gift(g,gift)
        self.assertEqual(g.snapshot(),before);self.portable(g,gift)

    def test_08_empty_and_short_complete_pools_do_not_invent_extra_cards_or_shuffle(self):
        for mode,n in(('empty',0),('one',0),('two',1)):
            g=game(mode=mode);play(g)
            if mode!='empty':select(g,g.state.pending_choice.options[0].id)
            self.assertEqual(len(g.state.card_discovery_history),0 if mode=='empty'else 1)
            self.assertEqual([x.declared_count for x in g.state.deck_shuffle_history],[n]if n else[])
            self.portable(g,mode=mode)

    def test_09_unknown_eligible_definition_and_missing_context_are_explicit_atomic_errors(self):
        for mode,ctx in(('unknown',CTX),('normal',None)):
            g=game(mode=mode,context=ctx);before=g.snapshot()
            with self.assertRaises(ResolutionError):play(g)
            self.assertEqual(g.snapshot(),before)

    def test_10_gifted_shuffled_card_keeps_ability_and_price_when_physically_drawn(self):
        gift='EDR_100t2';g=game(gift,hand=(DISC,DRAW));play(g,DISC);offer=g._frame.original_discovery_offer
        chosen=next(o for o in offer.options if o.effects[0].selection.gift.id!=gift);select(g,chosen.id)
        drawn=g.state.entities[next(i for i in g.state.players[1].deck if g.state.entities[i].card_id in MEMBERS)]
        cid=drawn.card_id;bound=next(o.effects[0].selection.gift.id for o in offer.options if o.card_id==cid)
        play(g,DRAW);self.assertEqual(g.state.entities[drawn.id].zone,Zone.HAND);self.check_material(g.state.entities[drawn.id],cid,bound)
        self.portable(g,gift)

    def test_11_actual_retry_keeps_only_final_original_gifted_shuffle(self):
        gift='EDR_100t2';g=game(gift,hand=(RETRY,));play(g,RETRY);pick_gift(g,gift);self.portable(g,gift)
        select(g,'retry');self.assertFalse(g.state.deck_shuffle_history);pick_gift(g,gift)
        self.assertEqual(g.state.players[1].mana,38);self.assertEqual(len(g.state.deck_shuffle_history),1);self.portable(g,gift)

    def test_12_native_full_source_and_previous_schema_are_explicit(self):
        from tools.card_batch import check_face
        d=load_batch();raw=d['cards'][0]['record']
        for o in d['official_observations']:check_face(raw,o['face'],o['locale'])
        g=game();s=g.snapshot();s['schema_version']=381
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry('reader'))

    def test_13_actual_stone_plays_original_gifted_others_after_one_original_shuffle(self):
        from hs_sim.cards.native_origin_stone_cards import REWARD
        g=game(hand=(REWARD,CARD),stone=True);weapon=play(g,REWARD);source=play(g)
        offer=g._frame.original_discovery_offer;selected=offer.options[0];select(g,selected.id)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.entities[weapon].durability,7)
        self.assertEqual(g.state.players[1].mana,35);self.assertEqual(len(g.state.play_history),2)
        self.assertEqual([x.declared_count for x in g.state.deck_shuffle_history],[2])
        self.assertEqual(len(g.state.card_discovery_history),1)
        children=g.state.whole_card_replay_ledger.children
        self.assertEqual([c.card_id for c in children],[o.card_id for o in offer.options if o.id!=selected.id])
        for child in children:
            self.assertIsNone(child.failure)
            o=next(o for o in offer.options if o.card_id==child.card_id)
            self.check_material(g.state.entities[child.physical.source.entity_id],o.card_id,o.effects[0].selection.gift.id)
        self.portable(g,stone=True)

    def test_14_gift_remainder_wrapper_rejects_unproved_or_losing_shapes(self):
        from hs_sim.engine.dark_gift_generation import DiscoverDarkGift
        good=DiscoverDarkGift(1,'constructed.cards',QUERY,1,shuffle_unselected_into_deck=True)
        for changes in(dict(shuffle_unselected_into_deck=1),dict(gift_copy_to_hand=True),
                dict(query=replace(QUERY,min_cost=4)),dict(query=replace(QUERY,class_mode='any'))):
            with self.assertRaises(ValueError):replace(good,**changes)

if __name__=='__main__':unittest.main()
