"""Real Fabled+ construction, native completion and complete physical price facts."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict,replace
import json
import unittest

from hs_sim.cards.simple_followup_p70_cards import register_simple_followup_p70_cards
from hs_sim.cards.timethief_rafaam_cards import load_batch,register_timethief_rafaam_cards
from hs_sim.engine import (CardClass,CardDefinition,CardType,DeckPolicy,DeckSpec,
    DeckValidationError,EndTurn,Game,Keyword,MatchSetup,PlayCard,PlayerSetup,
    Scenario,SelectChoice,SnapshotError,TriggerSpec,expand_fabled_cards,validate_deck)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (ChoiceOption,Destroy,GainArmor,RequestChoice,ReturnToHand,
    Summon,Transform)
from hs_sim.engine.model import PlayerPlayedClassCostSpec
from hs_sim.engine.rafaams import ROOT,MEMBERS,FAMILY,GIANT,SHEEP,PROFILE
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata,registry as opening_registry

TINY='TIME_005t1';GREEN='TIME_005t2';MURLOC='TIME_005t8';EXPLORER='TIME_005t3'
WARCHIEF='TIME_005t4';CALAMITOUS='TIME_005t6';MINDFLAYER='TIME_005t5';ARCHMAGE='TIME_005t9'
PLAIN='card.1';WATCH='rafaam-test.watch';BOUNCE='rafaam-test.bounce'
SWAP='rafaam-test.transform';SUMMON='rafaam-test.summon'


def fixture(mode='normal'):
    r=opening_registry();register_simple_followup_p70_cards(r);register_timethief_rafaam_cards(r)
    r.register_card(CardDefinition('warlock.power','Explicit power',CardType.HERO_POWER,cost=2,
        on_use='power',metadata=metadata(CardClass.WARLOCK,collectible=False)))
    r.register_card(CardDefinition('warlock.hero','Explicit hero',CardType.HERO,health=30,
        initial_hero_power='warlock.power',metadata=metadata(CardClass.WARLOCK,collectible=False)))
    def watch(c):
        if mode=='cleanup':
            if c.event.player_id!=c.player_id:return ()
            return tuple(Destroy(eid,c.source_id)for eid in c.state.players[c.player_id].board
                if c.state.entities[eid].card_id in FAMILY)
        if mode=='wait' and c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==GIANT:
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),source_id=c.source_id),)
        return ()
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,'Explicit observer',CardType.MINION,health=1000,
        triggers=(TriggerSpec('card_played',WATCH),),metadata=metadata(collectible=False)))
    r.register_behavior(BOUNCE,lambda c:tuple(ReturnToHand(eid)for eid in c.state.players[c.player_id].board
        if c.state.entities[eid].card_id==TINY))
    r.register_behavior(SWAP,lambda c:tuple(Transform(eid,SHEEP)for eid in c.state.players[c.player_id].board
        if c.state.entities[eid].card_id==TINY))
    r.register_behavior(SUMMON,lambda c:(Summon(c.player_id,TINY,c.source_id),))
    for cid in(BOUNCE,SWAP,SUMMON):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata()))
    r.validate();return r


class TimethiefRafaamTests(unittest.TestCase):
    def game(self,hand=(),*,mode='normal',board=(),enemy=(),enemy_hand=(),deck=(PLAIN,)*20,active=1):
        return Game.from_scenario(Scenario((PlayerSetup('warlock.hero',hand=hand,
            board=((WATCH,)if mode!='normal'else())+board,deck=deck,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('warlock.hero',hand=enemy_hand,board=enemy,deck=(PLAIN,)*20,
                mana=40,max_mana=40,mana_cap=40,armor=500)),active_player=active,seed=916),fixture(mode))
    def find(self,g,cid,*,pid=1,zone='hand'):
        return next(g.state.entities[eid]for eid in getattr(g.state.players[pid],zone)if g.state.entities[eid].card_id==cid)
    def play(self,g,cid,*,pid=1):
        eid=self.find(g,cid,pid=pid).id;g.apply(PlayCard(pid,eid));return eid
    def cost(self,g,cid=GIANT):
        return quote_unselected_cost(g.state,g.registry,self.find(g,cid)).amount
    def portable(self,g,mode='normal'):
        saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(Game.from_snapshot(saved,fixture(mode)).snapshot(),saved)
        self.assertEqual(replay(build_replay(g),fixture(mode)).snapshot(),saved)
    def full_deck(self,r):
        return expand_fabled_cards((ROOT,*(f'card.{n}'for n in range(1,31))),r)
    def setup(self,r,cards=None):
        cards=self.full_deck(r)if cards is None else cards
        decks=(DeckSpec('warlock.hero','warlock.power',CardClass.WARLOCK,cards),
            DeckSpec('mage.hero','mage.power',CardClass.MAGE,tuple(f'card.{n}'for n in range(1,31))))
        return MatchSetup(decks,DeckPolicy('rafaam-explicit-v1','rafaam-test-target','experimental',tuple(r.cards)),'coin',915,1)
    def reject(self,saved,mode='wait'):
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as error:Game.from_snapshot(saved,fixture(mode))
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_full_sources_reuse_nine_existing_definitions_without_replacement(self):
        r=opening_registry();register_simple_followup_p70_cards(r)
        before={cid:asdict(r.card(cid))for cid in FAMILY if cid in r.cards}
        register_timethief_rafaam_cards(r);r.validate();data=load_batch()
        self.assertEqual(len(before),9)
        for cid,value in before.items():self.assertEqual(asdict(r.card(cid)),value)
        self.assertEqual(len(data['official_observations']),22)
        self.assertEqual(set(data['rafaam_family_ids']),set(FAMILY))
        self.assertIn(SHEEP,FAMILY);self.assertNotIn(SHEEP,MEMBERS)
        self.assertFalse(data['cn_calibrated'])

    def test_original_forty_card_deck_has_ten_family_slots_and_thirty_other_cards(self):
        r=fixture();cards=self.full_deck(r);self.assertEqual(len(cards),40)
        self.assertEqual(cards[:10],(ROOT,*MEMBERS));self.assertNotIn(SHEEP,cards)
        self.assertEqual(Counter(cards)[ROOT],1)
        self.assertTrue(validate_deck(self.setup(r).decks[0],r,self.setup(r).policy).valid)
        g=Game.from_decks(self.setup(r),r)
        while g.state.pending_choice is not None:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        self.assertEqual(g.state.players[1].original_deck,cards)
        self.assertEqual(len(g.state.players[1].original_deck),40)
        self.portable(g)

    def test_missing_duplicate_companion_or_incorrect_capacity_rejects_before_match(self):
        r=fixture();good=self.full_deck(r)
        for cards in(good[:30],good+(PLAIN,)*9,tuple(PLAIN if c==GIANT else c for c in good),
            (ROOT,MEMBERS[0],MEMBERS[0],*good[3:])):
            with self.subTest(length=len(cards)):
                with self.assertRaises(DeckValidationError):Game.from_decks(self.setup(r,cards),r)

    def test_root_does_not_win_without_nine_original_distinct_paid_companions(self):
        g=self.game((ROOT,),board=MEMBERS[:6],enemy=(GIANT,ARCHMAGE,SHEEP));self.play(g,ROOT)
        self.assertEqual(g.state.status,'playing');self.assertEqual(g.state.winner,None)
        self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_repeating_one_companion_nine_times_does_not_replace_distinct_ones(self):
        g=self.game((TINY,)*9+(ROOT,),mode='cleanup')
        for _ in range(9):self.play(g,TINY)
        self.play(g,ROOT)
        self.assertEqual(len(g.state.play_history),10);self.assertEqual(g.state.status,'playing')
        self.portable(g,'cleanup')

    def test_all_nine_real_paid_companions_then_root_destroy_hero_through_shared_death(self):
        g=self.game((ROOT,*MEMBERS),mode='cleanup')
        for cid in MEMBERS:
            if self.cost(g,cid)>g.state.players[1].mana:
                g.apply(EndTurn(1));g.apply(EndTurn(2))
            self.play(g,cid)
            if g.state.pending_choice is not None:
                q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(q.options[0].id,)))
        if g.state.players[1].mana<10:g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.play(g,ROOT)
        self.assertEqual((g.state.status,g.state.winner),('finished',1))
        self.assertEqual({p.played_face.card_id for p in g.state.play_history},set((ROOT,*MEMBERS)))
        hero=g.state.entities[g.state.players[2].hero_id]
        self.assertEqual(hero.armor,500)
        self.assertTrue(any(e.kind=='destroyed'and e.target_id==hero.id for e in g.events))
        self.portable(g,'cleanup')

    def test_opponent_paid_faces_do_not_complete_owners_condition_or_price(self):
        g=self.game((ROOT,GIANT),enemy_hand=(TINY,),active=2);self.play(g,TINY,pid=2);g.apply(EndTurn(2))
        self.assertEqual(self.cost(g),8);self.play(g,ROOT)
        self.assertEqual(g.state.status,'playing');self.portable(g)

    def test_giant_counts_paid_duplicate_faces_and_tagged_sheep(self):
        g=self.game((TINY,TINY,SHEEP,GIANT),mode='cleanup')
        self.assertEqual(self.cost(g),8)
        for cid,price in((TINY,7),(TINY,6),(SHEEP,5)):
            self.play(g,cid);self.assertEqual(self.cost(g),price)
        source=self.play(g,GIANT)
        self.assertEqual(g.state.play_history[-1].cost,5)
        self.assertIn(Keyword.RUSH,g.state.entities[source].keywords)
        self.portable(g,'cleanup')

    def test_summoned_companions_and_ordinary_cards_do_not_reduce_giant(self):
        g=self.game((SUMMON,PLAIN,GIANT));self.play(g,SUMMON);self.play(g,PLAIN)
        self.assertEqual(self.cost(g),8);self.assertEqual(len(g.state.play_history),2)
        self.portable(g)

    def test_giant_uses_frozen_paid_identity_after_source_transform_and_reentry(self):
        g=self.game((TINY,SWAP,GIANT));source=self.play(g,TINY);self.play(g,SWAP)
        self.assertEqual(g.state.entities[source].card_id,SHEEP)
        self.assertEqual(g.state.play_history[0].played_face.card_id,TINY)
        self.assertEqual(self.cost(g),7);self.portable(g)
        g=self.game((TINY,BOUNCE,GIANT));self.play(g,TINY);self.play(g,BOUNCE);self.play(g,TINY)
        self.assertEqual(self.cost(g),6);self.portable(g)

    def test_giant_zero_floor_and_murloc_external_next_price_share_original_quote(self):
        g=self.game((TINY,)*8+(GIANT,),mode='cleanup')
        for _ in range(8):self.play(g,TINY)
        self.assertEqual(self.cost(g),0);self.play(g,GIANT)
        self.assertEqual(g.state.play_history[-1].cost,0);self.portable(g,'cleanup')
        g=self.game((TINY,MURLOC,GIANT));self.play(g,TINY);self.play(g,MURLOC)
        self.assertEqual(self.cost(g),3);self.play(g,GIANT)
        self.assertEqual(g.state.play_history[-1].cost,3)
        self.assertFalse(g.state.players[1].cost_modifiers);self.portable(g)

    def test_paid_giant_waiting_keeps_original_complete_class_price_fact(self):
        g=self.game((TINY,GIANT),mode='wait');self.play(g,TINY);self.play(g,GIANT)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g,'wait')
        fact=g.state.play_history[-1].submitted_cost.quote.intrinsic.player_played_class
        self.assertEqual((fact.quantity,fact.before,fact.after,fact.selected_ids),(1,8,7,(1,)))
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertTrue(g.state.play_history[-1].completed);self.portable(g,'wait')

    def test_rehashed_giant_price_selected_count_or_original_rows_cannot_be_cropped(self):
        g=self.game((TINY,GIANT),mode='wait');self.play(g,TINY);self.play(g,GIANT);saved=g.snapshot()
        def find(value):
            if isinstance(value,dict):
                spec=value.get('spec')
                if isinstance(spec,dict) and spec.get('profile_id')==PROFILE and 'selected_ids'in value:return value
                for child in value.values():
                    found=find(child)
                    if found is not None:return found
            elif isinstance(value,list):
                for child in value:
                    found=find(child)
                    if found is not None:return found
        self.assertIsNotNone(find(saved))
        for key,value in(('quantity',0),('selected_ids',[]),('rows',[])):
            bad=deepcopy(saved);find(bad)[key]=value;self.reject(bad)

    def test_finite_price_profile_rejects_wrong_class_or_unrelated_carrier(self):
        with self.assertRaises(ValueError):PlayerPlayedClassCostSpec(CardClass.WARLOCK,PROFILE)
        from hs_sim.engine.player_played_class_costs import validate_definition
        with self.assertRaises(ValueError):validate_definition(CardDefinition('fake.giant','Fake',CardType.MINION,
            attack=8,health=8,player_played_class_cost=PlayerPlayedClassCostSpec(None,PROFILE)))
        r=fixture();del r._fabled[ROOT]
        with self.assertRaises(ValueError):r.validate()

    def test_own_deck_explorer_now_discovers_original_parent_and_giant(self):
        g=self.game((EXPLORER,),deck=(ROOT,GIANT,PLAIN));originals=set(g.state.players[1].deck)
        self.play(g,EXPLORER);q=g.state.pending_choice
        self.assertEqual({o.card_id for o in q.options},{ROOT,GIANT});self.portable(g)
        answer=next(o.id for o in q.options if o.card_id==GIANT)
        g.apply(SelectChoice(q.player_id,q.id,(answer,)))
        self.assertIn(self.find(g,GIANT).id,originals);self.assertFalse(g.state.draw_history)
        self.assertEqual(self.cost(g),7);self.portable(g)

    def test_existing_green_and_murloc_include_new_parent_and_giant(self):
        g=self.game((GREEN,ROOT,GIANT));self.play(g,GREEN)
        self.assertEqual((self.find(g,ROOT).attack,self.find(g,ROOT).health),(12,12))
        self.assertEqual((self.find(g,GIANT).attack,self.find(g,GIANT).health),(10,10))
        self.assertEqual(self.find(g,GREEN,zone='board').attack,2);self.portable(g)
        g=self.game((MURLOC,ROOT,GIANT));self.play(g,MURLOC)
        self.assertEqual(self.cost(g,ROOT),7);self.assertEqual(self.cost(g),4)
        self.play(g,ROOT);self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertEqual(self.cost(g),6);self.portable(g)

    def test_existing_tiny_draws_parent_or_giant_as_original_physical_card(self):
        g=self.game((TINY,),deck=(ROOT,GIANT));original=set(g.state.players[1].deck);self.play(g,TINY)
        delivered=set(g.state.players[1].hand)
        self.assertEqual(len(delivered),1);self.assertTrue(delivered<=original)
        self.assertIn(g.state.entities[next(iter(delivered))].card_id,(ROOT,GIANT));self.portable(g)

    def test_existing_six_damage_and_archmage_spare_new_parent_and_giant(self):
        g=self.game((CALAMITOUS,),board=(ROOT,),enemy=(GIANT,PLAIN));self.play(g,CALAMITOUS)
        self.assertEqual(self.find(g,ROOT,zone='board').health,10)
        self.assertEqual(self.find(g,GIANT,pid=2,zone='board').health,8)
        self.assertFalse(any(g.state.entities[e].card_id==PLAIN for e in g.state.players[2].board));self.portable(g)
        g=self.game((ARCHMAGE,),board=(ROOT,PLAIN),enemy=(GIANT,PLAIN));self.play(g,ARCHMAGE)
        self.assertEqual(self.find(g,ROOT,zone='board').card_id,ROOT)
        self.assertEqual(self.find(g,GIANT,pid=2,zone='board').card_id,GIANT)
        self.assertTrue(any(g.state.entities[e].card_id==SHEEP for e in g.state.players[1].board));self.portable(g)

    def test_player_projection_does_not_expose_original_deck_or_full_price_prefix(self):
        g=self.game((TINY,GIANT),mode='wait');self.play(g,TINY);self.play(g,GIANT)
        for pid in(1,2):
            public=json.dumps((g.for_player(pid).observe(),g.for_player(pid).events()),ensure_ascii=False)
            for word in('play_history_length','selected_ids','starting_entities','original_deck','rng_state','quote_input'):
                self.assertNotIn(word,public)


if __name__=='__main__':unittest.main()
