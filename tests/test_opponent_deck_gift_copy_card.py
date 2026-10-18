"""Nightmare Fuel copies accepted opponent material with an atomic Combo gift."""
from dataclasses import asdict
from functools import lru_cache
from types import SimpleNamespace
import json,random,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.opponent_deck_gift_copy_card import CARD,load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,
    PlayerSetup,PlayCard,Rarity,Scenario,SelectChoice,Zone)
from hs_sim.engine.effects import ChoiceOption,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.model import CardPreview,ChoicePurpose,CostSpec,LimitedTriggerSpec
from hs_sim.engine.dark_gifts import DARK_GIFTS,public_gifts
from hs_sim.engine.discovery import sample_eligible_gifts
from hs_sim.engine.stored_gift_discovery import eligible_face
from hs_sim.engine.hand_capacity import SetHandCapacity
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.zones import CardReference,ModifyStoredCost,MoveCard
from hs_sim.engine.opponent_deck_gift_copy import DeckCopyOffer,DiscoverOpponentDeckCopy,CopyOpponentDeckOffer
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest

P='nightmare.fuel.test.';A,B,C,FILL,PREP=(P+x for x in ('a','b','c','fill','prep'))
CAP=P+'cap';BUFF=P+'buff';WATCH=P+'watch';STONE='TLC_460t'


@lru_cache(maxsize=None)
def gift_seed(gift_id):
    face=eligible_face(CardPreview(4,3,5,5,0,()),True)
    for seed in range(1000):
        rng=random.Random(seed);rng.sample((0,),1);rng.choice((0,))
        picked=sample_eligible_gifts(SimpleNamespace(game=SimpleNamespace(_rng=rng)),DARK_GIFTS,(face,))[0]
        if picked.id==gift_id:return seed
    raise AssertionError('No native seed for the requested real gift')


@lru_cache(maxsize=None)
def registry(mode,role):
    assert role in ('writer','reader')
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON)
    r.register_behavior(P+'noop',lambda c:())
    for cid,cost,attack,health,extra in ((A,4,3,5,dict(battlecry=P+'noop')),(B,2,1,3,dict(keywords=(Keyword.TAUNT,))),
            (C,5,0,8,{}),(FILL,0,1,2,{})):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health,metadata=meta,**extra))
    r.register_behavior(PREP,lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition(PREP,PREP,CardType.SPELL,on_play=PREP,metadata=meta))
    r.register_behavior(CAP,lambda c:(SetHandCapacity(1,1),))
    def original(c):
        return CardReference.capture(next(c.state.entities[i]for i in c.state.players[2].deck if c.state.entities[i].card_id==A))
    r.register_behavior(BUFF,lambda c:(BuffStoredCard(original(c),attack=2,health=3,source_id=c.source_id),
        ModifyStoredCost(original(c),CostSpec(delta=-1),c.source_id)))
    for cid in (CAP,BUFF):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=meta))
    if mode:
        def fail(c):raise ResolutionError('Nightmare Fuel deliberate acquisition failure')
        r.register_behavior(P+'fail',fail)
        def eligible(c):return c.event.source_id in c.state.entities and c.state.entities[c.event.source_id].card_id==CARD
        def watch(c):
            if mode=='alter':return (BuffStoredCard(original(c),attack=9,source_id=c.source_id),)
            if mode=='depart':return (MoveCard(original(c),2,Zone.HAND,source_id=c.source_id),)
            entity=c.state.entities[c.event.target_id]
            if not public_gifts(entity):raise ResolutionError('Copy acquisition observed an incomplete gift')
            return (RequestChoice(1,(ChoiceOption('ok','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(P+'watch',watch);r.register_trigger_condition(P+'eligible',eligible)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=meta,
            limited_triggers=(LimitedTriggerSpec('choice_selected'if mode in ('alter','depart')else'card_created',P+'watch',condition_id=P+'eligible'),)))
    r.validate();r.freeze();return r


class OpponentDeckGiftCopyTests(unittest.TestCase):
    def game(self,enemy=(A,B,C),hand=(CARD,),mode=None,seed=225528,stone=False,enemy_hand=()):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=(WATCH,)if mode else(),weapon_card_id=STONE if stone else None,
            deck=(FILL,)*8,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',hand=enemy_hand,deck=enemy,
            mana=50,max_mana=50,mana_cap=50)),seed=seed),registry(mode,'writer'))
    def play(self,g,cid=CARD,pid=1):
        eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid));return eid
    def choose(self,g,index=0):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(q.options[index].id,)))
    def portable(self,g):
        r=registry(self.mode,'reader');self.assertIsNot(r,g.registry)
        self.assertEqual(r.fingerprint(),g.registry.fingerprint());s=json.loads(json.dumps(g.snapshot()))
        other=Game.from_snapshot(s,r);self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        for pid in (1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in ('resolution_frame','rng_state','source_allocation','CopyLocalState','DeckCopyOffer'):
                self.assertNotIn(key,public)
        return other
    def test_a00_no_combo_copies_original_material_without_changing_opponent_deck(self):
        g=self.game();deck=list(g.state.players[2].deck);before={i:asdict(g.state.entities[i])for i in deck};self.play(g)
        self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.CARD_DISCOVERY)
        effect=g._frame.options[0].effects[0];source=effect.offered[effect.index].material.origin
        self.assertFalse(effect.request.gift);self.portable(g);self.choose(g)
        copied=g.state.entities[g.state.players[1].hand[-1]]
        self.assertEqual((copied.card_id,copied.origin_entity_id),(source.card_id,source.entity_id));self.assertNotIn(copied.id,deck)
        self.assertEqual(g.state.players[2].deck,deck);self.assertEqual({i:asdict(g.state.entities[i])for i in deck},before)
        self.assertFalse(public_gifts(copied));self.assertEqual(g.state.players[1].mana,49);self.portable(g)
    def test_a01_actual_combo_pairs_three_distinct_gifts_and_copy_matches_preview(self):
        g=self.game(hand=(PREP,CARD));self.play(g,PREP);self.play(g)
        effect=g._frame.options[0].effects[0];self.assertTrue(effect.request.gift)
        self.assertEqual(len({o.gift_id for o in effect.offered}),3);expected=g.state.pending_choice.options[0].preview
        self.portable(g);self.choose(g)
        copies=[e for e in g.state.entities.values()if e.controller==1 and e.origin_entity_id in g.state.players[2].deck]
        self.assertEqual(len(copies),1);copy=copies[0]
        self.assertTrue(public_gifts(copy));self.assertEqual((copy.cost,copy.attack,copy.health),(expected.cost,expected.attack,expected.health))
        self.assertEqual(len(g.state.card_discovery_history),1);self.portable(g)
    def test_a02_complete_real_source_native_combo_marker_and_no_external_minion_pool(self):
        d=load_batch();row,=d['cards'];r=registry(None,'writer')
        self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual((r.card(CARD).cost,r.card(CARD).kind),(1,CardType.SPELL));self.assertIn(Keyword.COMBO,r.card(CARD).keywords)
        self.assertEqual(len(d['official_observations']),2);self.assertFalse(d['policy']['formal_pool_complete']);self.assertFalse(d['policy']['cn_calibrated'])
    def test_a03_distinct_faces_ignore_spells_and_duplicates_do_not_multiply_offers(self):
        g=self.game(enemy=(A,A,B,C,PREP));self.play(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{A,B,C})
        effect=g._frame.options[0].effects[0];self.assertEqual(len({o.material.origin.entity_id for o in effect.offered}),3)
        self.choose(g);self.assertEqual(len(g.state.players[2].deck),5)
    def test_b00_native_short_claws_copy_reduces_current_attack_and_cost_without_touching_original(self):
        g=self.game(enemy=(A,),hand=(PREP,CARD),seed=gift_seed('EDR_100t2'));old=g.state.players[2].deck[0]
        self.play(g,PREP);self.play(g);self.choose(g);copy=g.state.entities[g.state.players[1].hand[-1]]
        self.assertEqual((copy.cost,copy.attack,copy.health),(2,1,5));self.assertEqual(public_gifts(copy)[0]['id'],'EDR_100t2')
        self.assertEqual((g.state.entities[old].cost,g.state.entities[old].attack,g.state.entities[old].health),(4,3,5))
    def test_b01_native_sweet_dreams_creates_copy_on_own_deck_top_without_moving_opponent(self):
        g=self.game(enemy=(A,),hand=(PREP,CARD),seed=gift_seed('EDR_100t8'));old=g.state.players[2].deck[0]
        self.play(g,PREP);self.play(g);self.choose(g);copy=g.state.entities[g.state.players[1].deck[0]]
        self.assertEqual((copy.card_id,copy.attack,copy.health),(A,7,10));self.assertNotEqual(copy.id,old)
        self.assertEqual(g.state.players[2].deck,[old]);self.assertFalse(g.state.players[1].hand);self.portable(g)
    def test_b02_gift_is_complete_before_first_created_observer_and_failed_resume_is_atomic(self):
        g=self.game(enemy=(A,),hand=(PREP,CARD),mode='created',seed=gift_seed('EDR_100t2'))
        self.play(g,PREP);self.play(g);self.choose(g);copy=g.state.entities[g.state.players[1].hand[-1]]
        self.assertEqual((copy.cost,copy.attack,copy.health),(2,1,5));other=self.portable(g);saved=g.snapshot()
        q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,q.id,('fail',)))
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot())
    def test_c00_original_material_is_frozen_before_later_deck_buff_reaction(self):
        g=self.game(enemy=(A,),mode='alter');old=g.state.players[2].deck[0];self.play(g);self.choose(g)
        copy=g.state.entities[g.state.players[1].hand[-1]]
        self.assertEqual((copy.attack,copy.health),(3,5));self.assertEqual(g.state.entities[old].attack,12)
    def test_c01_original_departure_does_not_rebind_accepted_copy_to_later_source(self):
        g=self.game(enemy=(A,),mode='depart');old=g.state.players[2].deck[0];self.play(g);self.choose(g)
        self.assertFalse(g.state.players[2].deck);self.assertIn(old,g.state.players[2].hand)
        copy=g.state.entities[g.state.players[1].hand[-1]];self.assertEqual((copy.card_id,copy.origin_entity_id),(A,old))
    def test_c02_existing_opponent_deck_buffs_are_copied_and_opponent_play_does_not_enable_own_combo(self):
        g=self.game(enemy=(FILL,A),enemy_hand=(BUFF,));g.apply(EndTurn(1));self.play(g,BUFF,2);g.apply(EndTurn(2))
        self.play(g);self.assertFalse(g._frame.options[0].effects[0].request.gift);self.choose(g)
        copy=g.state.entities[g.state.players[1].hand[-1]];self.assertEqual((copy.cost,copy.attack,copy.health),(3,5,8))
    def test_c03_real_primal_stone_plays_unselected_current_material_with_its_original_gifts(self):
        g=self.game(hand=(PREP,CARD),stone=True);wid=g.state.players[1].weapon_id;dur=g.state.entities[wid].durability
        self.play(g,PREP);self.play(g);offered={o.card_id for o in g.state.pending_choice.options};selected=g.state.pending_choice.options[0].card_id
        self.choose(g);board=[g.state.entities[i]for i in g.state.players[1].board]
        self.assertTrue(offered-{selected}<={e.card_id for e in board})
        self.assertTrue(all(any(e.card_id==cid and public_gifts(e)for e in board)for cid in offered-{selected}))
        self.assertEqual(g.state.entities[wid].durability,dur-1);self.assertEqual(len(g.state.card_discovery_history),1)
        self.assertEqual(g.state.players[1].mana,49);self.portable(g)
    def test_d00_empty_minion_deck_has_no_choice_discovery_or_rng(self):
        g=self.game(enemy=(PREP,));rng=g._rng.getstate();self.play(g)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.card_discovery_history)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].mana,49)
    def test_d01_full_hand_burn_keeps_original_gifted_copy_and_never_buffs_existing_hand(self):
        g=self.game(enemy=(A,),hand=(CAP,CARD,FILL),seed=gift_seed('EDR_100t2'));self.play(g,CAP);self.play(g);self.choose(g)
        copies=[e for e in g.state.entities.values()if e.controller==1 and e.origin_entity_id in g.state.players[2].deck]
        self.assertEqual(len(copies),1);copy=copies[0];self.assertEqual((copy.zone,copy.cost,copy.attack),(Zone.GRAVEYARD,2,1))
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id,FILL);self.assertEqual(len(g.state.card_discovery_history),1);self.portable(g)
    def test_d02_offer_material_and_combo_flag_are_strict(self):
        for value in (0,1,None,'combo'):
            with self.assertRaises(ValueError):DiscoverOpponentDeckCopy(1,1,value)
        g=self.game(enemy=(C,));self.play(g);effect=g._frame.options[0].effects[0];material=effect.offered[0].material
        with self.assertRaises(ValueError):DeckCopyOffer(material,'EDR_100t2')
        with self.assertRaises(ValueError):CopyOpponentDeckOffer(DiscoverOpponentDeckCopy(2,effect.source_id),effect.offered,0)
    def test_d03_opponent_cannot_read_private_offers_materials_or_gift_bindings(self):
        g=self.game(hand=(PREP,CARD));self.play(g,PREP);self.play(g)
        public=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        for key in ('DeckCopyOffer','CopyLocalState','source_allocation','gift_id','request','offered'):
            self.assertNotIn('"'+key+'"',public)
