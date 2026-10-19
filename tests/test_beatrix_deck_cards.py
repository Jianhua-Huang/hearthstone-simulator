"""Original Beatrix selection, generated opening copies and ordinary runtime."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry as assembled_registry
from hs_sim.cards.beatrix_deck_cards import ROOT,BODY,load_batch,register_beatrix_deck_cards
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,
    PlayCard,PlayerSetup,Rarity,Scenario,SelectChoice)
from hs_sim.engine.construction import DeckPolicy,DeckSpec,DeckValidationError,MatchSetup,validate_deck
from hs_sim.engine.effects import ChoiceOption,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import OpeningHook
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.sideboards import (DeckCopySideboardProfile,DiscoverSideboard,
    SideboardSpec,validate_player)
from hs_sim.targets import canonical_digest

P='beatrix.test.';FILL=P+'filler';PICK='NEW1_023';SECOND=P+'second';LEGEND=P+'legend'
ALIAS=P+'alias';SPELL=P+'spell';THREE=P+'three';FOREIGN=P+'foreign';TOKEN=P+'token';HOOK=P+'hook'


@lru_cache(maxsize=1)
def full_registry():return assembled_registry()


@lru_cache(maxsize=None)
def registry(role,mode=None):
    assert role in ('writer','reader')
    r=build_registry();register_beatrix_deck_cards(r)
    meta=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,cost=1,attack=1,health=1,
        metadata=replace(meta,max_copies=30)))
    for cid,rarity,classes,collectible,cost,kind in (
        (SECOND,Rarity.COMMON,(CardClass.PALADIN,),True,2,CardType.MINION),
        (LEGEND,Rarity.LEGENDARY,(CardClass.NEUTRAL,),True,2,CardType.MINION),
        (SPELL,Rarity.COMMON,(CardClass.NEUTRAL,),True,2,CardType.SPELL),
        (THREE,Rarity.COMMON,(CardClass.NEUTRAL,),True,3,CardType.MINION),
        (FOREIGN,Rarity.COMMON,(CardClass.ROGUE,),True,2,CardType.MINION),
        (TOKEN,Rarity.COMMON,(CardClass.NEUTRAL,),False,2,CardType.MINION)):
        r.register_card(CardDefinition(cid,cid,kind,cost=cost,attack=2 if kind==CardType.MINION else 0,
            health=3 if kind==CardType.MINION else 0,metadata=replace(meta,rarity=rarity,classes=classes,collectible=collectible)))
    r.register_card(replace(r.card(PICK),id=ALIAS,name=ALIAS,
        metadata=replace(r.card(PICK).metadata,deck_identity=r.card(PICK).metadata.deck_identity or PICK)))
    r.register_behavior(HOOK,lambda c:(GainArmor(c.player_id,99),))
    r.register_card(CardDefinition(HOOK,HOOK,CardType.MINION,cost=2,attack=2,health=2,
        opening_hooks=(OpeningHook('before_deal',HOOK),),metadata=meta))
    def fail(c):raise ResolutionError('Beatrix deliberate failure')
    r.register_behavior(P+'fail',fail)
    r.register_behavior(P+'band',lambda c:(DiscoverSideboard(c.player_id,ROOT,c.source_id),))
    r.register_card(CardDefinition(P+'band',P+'band',CardType.SPELL,on_play=P+'band',metadata=meta))
    if mode is not None:
        original=r.behavior(BODY)
        def wrapped(c):
            work=tuple(original(c))
            choice=RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id)
            return (choice,*work)if mode=='before'else(*work,choice)
        r.register_behavior(P+'opening',wrapped)
        r._cards[ROOT]=replace(r.card(ROOT),opening_hooks=(OpeningHook('before_deal',P+'opening'),))
    r.validate();r.freeze();return r


def setup(pick=PICK,*,other_pick=None,first_player=1,seed=234397):
    def deck(selected):
        return DeckSpec('HERO_04','HERO_04bp',CardClass.PALADIN,
            (ROOT,)+(FILL,)*29 if selected is not None else(FILL,)*30,
            sideboards=(SideboardSpec(ROOT,(selected,)),)if selected is not None else())
    allowed=(ROOT,FILL,PICK,SECOND,LEGEND,ALIAS,SPELL,THREE,FOREIGN,TOKEN,HOOK,P+'band')
    return MatchSetup((deck(pick),deck(other_pick)),DeckPolicy(P+'policy',P+'target','experimental',allowed),
        'GAME_005',seed=seed,first_player=first_player)


class BeatrixDeckTests(unittest.TestCase):
    def game(self,pick=PICK,*,mode=None,other_pick=None,first_player=1):
        self.mode=mode
        return Game.from_decks(setup(pick,other_pick=other_pick,first_player=first_player),registry('writer',mode))
    def copies(self,g,cid=PICK,pid=1):
        return [e for e in g.state.entities.values()if e.card_id==cid and e.owner==pid]
    def choose(self,g,key=None):
        q=g.state.pending_choice
        selected=()if key is None and q.min_count==0 else(key or'ok',)
        g.apply(SelectChoice(q.player_id,q.id,selected))
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def portable(self,g):
        r=registry('reader'if g.registry is registry('writer',self.mode)else'writer',self.mode)
        self.assertIsNot(r,g.registry);s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,r)
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        for pid in (1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for field in ('match_setup','original_deck','original_entities','rng_state','resolution_frame','DeckCopySideboardProfile'):
                self.assertNotIn(field,wire)
        return other
    def test_a00_full_raw_two_faces_real_taunt_and_static_profile(self):
        d=load_batch();self.assertEqual(len(d['official_observations']),2)
        self.assertEqual(canonical_digest(d['cards'][0]['record']),d['cards'][0]['record_sha256'])
        r=registry('writer');self.assertEqual(r.card(ROOT),full_registry().card(ROOT))
        self.assertEqual(r.sideboards[ROOT],DeckCopySideboardProfile(ROOT))
        self.assertEqual((r.card(ROOT).cost,r.card(ROOT).attack,r.card(ROOT).health),(5,5,6))
        self.assertIn(Keyword.TAUNT,r.card(ROOT).keywords);self.assertIsNone(r.card(ROOT).battlecry)
    def test_a01_original_source_requires_exactly_one_valid_two_cost_selection(self):
        r=registry('writer');s=setup();base=s.decks[0]
        for cards in (None,(),(PICK,SECOND),(SPELL,),(THREE,),('missing.beatrix.selection',)):
            with self.subTest(cards=cards):
                deck=replace(base,sideboards=()if cards is None else(SideboardSpec(ROOT,cards),))
                report=validate_deck(deck,r,s.policy);self.assertFalse(report.valid)
                self.assertTrue(any(i.code=='deck_copy_selection'for i in report.issues))
        with self.assertRaises(DeckValidationError):Game.from_decks(replace(s,decks=(replace(base,sideboards=()),s.decks[1])),r)
    def test_a02_shared_class_collectibility_and_format_rules_still_validate_selection(self):
        r=registry('writer');s=setup()
        for pick in (FOREIGN,TOKEN):
            self.assertFalse(validate_deck(replace(s.decks[0],sideboards=(SideboardSpec(ROOT,(pick,)),)),r,s.policy).valid)
        self.assertFalse(validate_deck(s.decks[0],r,replace(s.policy,banned_card_ids=(PICK,))).valid)
        self.assertFalse(validate_deck(s.decks[0],r,replace(s.policy,allowed_card_ids=(ROOT,FILL))).valid)
    def test_a03_selection_uses_max_copy_allowance_for_common_legendary_and_alias(self):
        r=registry('writer')
        for pick,extra in ((PICK,PICK),(PICK,ALIAS),(LEGEND,LEGEND)):
            with self.subTest(pick=pick,extra=extra):
                s=setup(pick);self.assertTrue(validate_deck(s.decks[0],r,s.policy).valid)
                changed=replace(s.decks[0],cards=(ROOT,extra)+(FILL,)*28)
                self.assertFalse(validate_deck(changed,r,s.policy).valid)
    def test_a04_selection_does_not_change_original_policy_capacity(self):
        r=registry('writer');s=setup();d=s.decks[0]
        self.assertTrue(validate_deck(d,r,s.policy).valid)
        for cards in ((ROOT,)+(FILL,)*28,(ROOT,)+(FILL,)*39):
            self.assertFalse(validate_deck(replace(d,cards=cards),r,s.policy).valid)
    def test_b00_opening_creates_ten_independent_printed_cards_outside_original_facts(self):
        g=self.game();copies=self.copies(g);self.assertEqual(len(copies),10)
        p=g.state.players[1];self.assertEqual(len(p.original_deck),30);self.assertNotIn(PICK,p.original_deck)
        originals=set(g.state.opening.original_entities[0]);self.assertEqual(len(originals),30)
        self.assertTrue(originals.isdisjoint(e.id for e in copies));self.assertEqual(len(p.deck)+len(p.hand),40)
        base=g.registry.card(PICK)
        self.assertEqual(len({e.id for e in copies}),10)
        for e in copies:
            self.assertEqual((e.base_cost,e.attack,e.max_health),(base.cost,base.attack,base.health))
            self.assertEqual(e.keywords,set(base.keywords))
        self.assertEqual(sum(i==PICK for i in g._generation_context.starting_decks[0]),0)
        self.assertEqual(len(g.state.deck_shuffle_history),1);self.assertEqual(g.state.deck_shuffle_history[0].actor_id,1)
        self.portable(g)
    def test_b01_real_mulligans_keep_all_ten_physical_copies_and_original_deck(self):
        g=self.game();before={e.id for e in self.copies(g)}
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,tuple(o.id for o in q.options)))
        self.portable(g);self.finish(g)
        self.assertEqual({e.id for e in self.copies(g)},before);self.assertEqual(len(g.state.players[1].original_deck),30)
        self.assertEqual(g.state.opening.stage,'complete');self.portable(g)
    def test_b02_both_players_keep_independent_selections_with_opposite_first_player(self):
        g=self.game(other_pick=SECOND,first_player=2)
        self.assertEqual(len(self.copies(g,PICK,1)),10);self.assertEqual(len(self.copies(g,SECOND,2)),10)
        self.assertFalse(self.copies(g,SECOND,1));self.assertFalse(self.copies(g,PICK,2));self.portable(g)
        self.finish(g);self.portable(g)
    def test_b03_selected_legendary_generates_ten_without_widening_construction_limit(self):
        g=self.game(LEGEND);self.assertEqual(len(self.copies(g,LEGEND)),10);self.assertNotIn(LEGEND,g.state.players[1].original_deck)
        self.finish(g);self.portable(g)
    def test_b04_generated_selection_does_not_run_its_own_opening_hook(self):
        g=self.game(HOOK);self.assertEqual(len(self.copies(g,HOOK)),10)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.assertFalse([e for e in g.events if e.kind=='opening_effect'and dict(e.data).get('behavior_id')==HOOK])
        self.finish(g);self.portable(g)
    def test_c00_normal_runtime_commander_pays_five_and_does_not_generate_a_deck(self):
        self.mode=None;r=registry('writer')
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_04',hand=(ROOT,),deck=(FILL,)*8,mana=10,max_mana=10),
            PlayerSetup('HERO_04',deck=(FILL,)*8)),seed=234),r)
        eid=g.state.players[1].hand[0];g.apply(PlayCard(1,eid));e=g.state.entities[eid]
        self.assertEqual(g.state.players[1].mana,5);self.assertEqual((e.attack,e.health),(5,6))
        self.assertIn(Keyword.TAUNT,e.keywords);self.assertFalse(self.copies(g));self.portable(g)
    def test_c01_construction_selection_is_not_a_consumable_discovery_band(self):
        self.mode=None;r=registry('writer')
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_04',hand=(P+'band',)),PlayerSetup('HERO_04')),seed=234),r)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(PlayCard(1,g.state.players[1].hand[0]))
        self.assertEqual(g.snapshot(),before);self.portable(g)
    def test_d00_before_producer_wait_restores_selection_rng_and_only_one_ten_card_group(self):
        g=self.game(mode='before');self.assertFalse(self.copies(g));other=self.portable(g);before=other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),before);self.choose(other)
        self.assertEqual(len(self.copies(other)),10);self.finish(other);self.portable(other)
    def test_d01_after_producer_wait_keeps_complete_group_and_never_readds_on_resume(self):
        g=self.game(mode='after');self.assertEqual(len(self.copies(g)),10);other=self.portable(g);before=other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),before);self.choose(other);self.finish(other)
        self.assertEqual(len(self.copies(other)),10);self.portable(other)
    def test_d02_player_validation_rejects_consumed_or_changed_selection(self):
        g=self.game();player=deepcopy(g.state.players[1]);band=player.sideboards[0]
        player.sideboards=(replace(band,taken_slots=(0,)),)
        with self.assertRaises(ValueError):validate_player(player,g.registry)
        player.sideboards=(replace(band,cards=(THREE,)),)
        with self.assertRaises(ValueError):validate_player(player,g.registry)
    def test_e00_static_profile_is_closed_immutable_and_requires_exact_source_policy(self):
        for kw in ({'selected_cost':3},{'copies':9},{'copies':11},{'copies':10.0},{'version':'sideboard-v1'}):
            with self.assertRaises(ValueError):DeckCopySideboardProfile(ROOT,**kw)
        r=registry('writer')
        with self.assertRaises(ValueError):r.register_sideboard(DeckCopySideboardProfile(ROOT))


if __name__=='__main__':unittest.main()
