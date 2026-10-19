"""Real permanent draw replacement, physical discovery and original destruction."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from test_infinite_cost_card import registry as helper_registry, P
from hs_sim.cards.commander_geddon_card import CARD, PROGRAM, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import AddToHand, ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardPreview, ChoicePurpose, CostSpec
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.turn_start_draws import TurnDrawReplacementProfile
from hs_sim.engine.zones import CardReference, ChooseFromZone
from hs_sim.targets import canonical_digest

G='geddon.test.'
PLAIN='CORE_CS2_182'
DECK=(PLAIN,'CORE_CS2_029','CORE_CS2_024','CATA_472','CORE_REV_990')


@lru_cache(None)
def registry(mode=None):
    # Reuse the already checked ordinary kill/copy/control/draw fixtures.
    r=helper_registry.__wrapped__()
    def fail(c):raise ResolutionError('Geddon deliberate failure')
    r.register_behavior(G+'fail',fail)
    r.register_behavior(G+'fill',lambda c:(AddToHand(c.player_id,P+'draw',c.source_id),)*2)
    def boost(c):
        entity=c.state.entities[c.state.players[c.player_id].deck[0]]
        return (BuffStoredCard(CardReference.capture(entity),3,5,c.source_id,cost=CostSpec(delta=-1)),)
    r.register_behavior(G+'boost',boost)
    for name in ('fill','boost'):
        r.register_card(CardDefinition(G+name,name,CardType.SPELL,cost=1,on_play=G+name))
    if mode:
        def watch(c):
            if c.event.player_id!=c.player_id:return ()
            if mode=='fail_move':return (InvokeBehavior(G+'fail',c.source_id,c.player_id),)
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),)
        r.register_behavior(G+'watch',watch)
        r.register_card(CardDefinition(G+'watch','Observer',CardType.MINION,health=20,
            triggers=(TriggerSpec('card_destroyed_in_deck' if mode=='wait_destroy' else 'card_moved_to_hand',G+'watch'),)))
    r.validate();return r


class CommanderGeddonTests(unittest.TestCase):
    def game(self,hand=(CARD,),deck=DECK,*,other_deck=(),board=(),mode=None,seat=1):
        own=PlayerSetup('HERO_08',hand=hand,deck=deck,board=(*((G+'watch',) if mode else ()),*board),
            mana=50,max_mana=50,mana_cap=50)
        other=PlayerSetup('HERO_08',deck=other_deck,mana=50,max_mana=50,mana_cap=50)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,seed=282),registry(mode))

    def eid(self,g,cid):
        return next(i for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id==cid)

    def play(self,g,cid,*,target=None):
        eid=self.eid(g,cid);seat=g.state.active_player;kind=g.registry.card(cid).kind
        g.apply(PlayCard(seat,eid,target_id=target,position=len(g.state.players[seat].board)if kind==CardType.MINION else None))
        return eid

    def next_owner(self,g):
        seat=g.state.active_player;g.apply(EndTurn(seat))
        self.assertIsNone(g.state.pending_choice)
        g.apply(EndTurn(3-seat))

    def select(self,g,index=0):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(q.options[index].id,)))

    def offers(self,g):
        return g._frame.options[0].effects[0].offered

    def portable(self,g,mode=None):
        saved=json.loads(json.dumps(g.snapshot()))
        other=Game.from_snapshot(saved,registry.__wrapped__(mode))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry.__wrapped__(mode)).snapshot(),saved)
        return other

    def test_a01_full_primary_sources_native_body_and_signed_independent_program(self):
        data=load_batch()
        for row in (*data['cards'],*data['evidence_only']):self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(len(data['official_observations']),2)
        card=registry().card(CARD)
        self.assertEqual((card.cost,card.attack,card.health),(7,7,7))
        self.assertEqual(card.metadata.tribes,('elemental',))
        self.assertEqual(registry().turn_draw_replacement_profiles[PROGRAM].spec_id,PROGRAM)

    def test_a02_real_battlecry_pays_once_and_installs_without_immediate_draw_or_discovery(self):
        g=self.game();deck=list(g.state.players[1].deck);source=self.play(g,CARD)
        self.assertEqual(g.state.players[1].mana,43)
        self.assertEqual(g.state.players[1].deck,deck)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual([(p.spec_id,p.source_id)for p in g.state.players[1].player_effects],[(PROGRAM,source)])
        self.assertFalse(g.state.card_discovery_history)

    def test_a03_normal_owner_turn_draw_offers_three_original_deck_entities(self):
        g=self.game();self.play(g,CARD);original=set(g.state.players[1].deck);self.next_owner(g)
        choice=g.state.pending_choice
        self.assertEqual((choice.player_id,choice.purpose,len(choice.options)),(1,ChoicePurpose.CARD_DISCOVERY,3))
        offered=self.offers(g)
        self.assertEqual(len({o.card.entity_id for o in offered}),3)
        self.assertTrue({o.card.entity_id for o in offered}<=original)
        self.assertEqual(set(g.state.players[1].deck),original)

    def test_a04_original_selected_delivery_cost_and_other_two_destructions_share_existing_receipts(self):
        g=self.game();self.play(g,CARD);before=list(g.state.players[1].deck);self.next_owner(g)
        offers=self.offers(g);selected=offers[0];others={o.card.entity_id for o in offers[1:]}
        maximum=g.state.next_entity_id;rng=g._rng.getstate();self.select(g)
        entity=g.state.entities[selected.card.entity_id]
        self.assertEqual(entity.zone,Zone.HAND)
        self.assertEqual(entity.cost,max(0,selected.face.cost-3))
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in others))
        self.assertEqual(g.state.players[1].deck,[i for i in before if i not in others|{entity.id}])
        self.assertEqual(g.state.next_entity_id,maximum)
        self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(len(g.state.card_discovery_history),1)
        self.assertFalse(any(r.player_id==1 for r in g.state.draw_history))
        self.assertFalse(g.state.death_history or g.state.discard_history)

    def test_a05_current_stored_stats_and_prior_discount_are_preserved_and_previewed(self):
        g=self.game(hand=(G+'boost',CARD),deck=(PLAIN,));original=g.state.players[1].deck[0]
        self.play(g,G+'boost');self.play(g,CARD);self.next_owner(g)
        face=g.state.pending_choice.options[0].preview
        self.assertEqual((face.cost,face.attack,face.max_health),(3,7,10))
        self.select(g);entity=g.state.entities[original]
        self.assertEqual((entity.cost,entity.attack,entity.max_health),(0,7,10))

    def test_a06_source_death_silence_bounce_and_control_change_do_not_remove_the_program(self):
        for operation in ('kill','silence','bounce','steal'):
            g=self.game(hand=(CARD,P+operation));source=self.play(g,CARD)
            self.play(g,P+operation,target=source);self.next_owner(g)
            self.assertEqual(len(g.state.pending_choice.options),3)
            self.assertEqual(len(g.state.players[1].player_effects),1)

    def test_a07_two_real_installations_keep_instances_but_replace_one_scheduled_draw_once(self):
        g=self.game(hand=(CARD,CARD));first=self.play(g,CARD);second=self.play(g,CARD)
        self.assertNotEqual(first,second)
        self.assertEqual(len(g.state.players[1].player_effects),2)
        self.next_owner(g);self.assertEqual(g.state.pending_choice.source_id,second)
        self.select(g);self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len(g.state.card_discovery_history),1)

    def test_a08_true_repeated_battlecry_does_not_create_two_sequential_turn_discovers(self):
        g=self.game(board=(P+'double',));self.play(g,CARD)
        self.assertEqual(len(g.state.players[1].player_effects),2)
        self.next_owner(g);self.select(g)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len(g.state.card_discovery_history),1)

    def test_a09_extra_draw_after_installation_remains_an_actual_draw(self):
        g=self.game(hand=(CARD,P+'draw'));self.play(g,CARD)
        first=g.state.players[1].deck[0];self.play(g,P+'draw')
        self.assertIn(first,g.state.players[1].hand)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len([r for r in g.state.draw_history if r.player_id==1]),1)
        self.assertFalse(g.state.card_discovery_history)

    def test_a10_empty_deck_keeps_ordinary_fatigue_and_does_not_sample(self):
        g=self.game(deck=());self.play(g,CARD);rng=g._rng.getstate()
        self.next_owner(g);self.assertIsNone(g.state.pending_choice)
        hero=g.state.players[1].hero_id;self.assertEqual(g.state.entities[hero].health,29)
        self.next_owner(g);self.assertEqual(g.state.entities[hero].health,27)
        self.assertEqual(g._rng.getstate(),rng)
        self.assertFalse(g.state.card_discovery_history)

    def test_a11_one_and_two_cards_offer_only_existing_physical_cards(self):
        for count in (1,2):
            g=self.game(deck=DECK[:count]);self.play(g,CARD);self.next_owner(g)
            self.assertEqual(len(g.state.pending_choice.options),count)
            offered=self.offers(g);self.select(g)
            self.assertEqual(g.state.players[1].deck,[])
            self.assertEqual(sum(g.state.entities[o.card.entity_id].zone==Zone.GRAVEYARD for o in offered),count-1)

    def test_a12_duplicate_faces_remain_separate_physical_offers(self):
        g=self.game(deck=(PLAIN,PLAIN,PLAIN));self.play(g,CARD);self.next_owner(g)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],[PLAIN]*3)
        self.assertEqual(len({o.card.entity_id for o in self.offers(g)}),3)
        self.select(g);self.assertEqual(len(g.state.players[1].hand),1)

    def test_a13_full_hand_burns_selected_original_and_still_destroys_other_offers(self):
        g=self.game(hand=(CARD,G+'fill',*([P+'draw']*8)));self.play(g,CARD);self.play(g,G+'fill')
        self.assertEqual(len(g.state.players[1].hand),10)
        self.next_owner(g);offered=self.offers(g);self.select(g)
        self.assertEqual(len(g.state.players[1].hand),10)
        self.assertTrue(all(g.state.entities[o.card.entity_id].zone==Zone.GRAVEYARD for o in offered))
        self.assertEqual(sum(e.kind=='card_burned' and e.target_id==offered[0].card.entity_id for e in g.events),1)

    def test_a14_all_five_playable_types_use_original_delivery_and_normal_cost_floor(self):
        for cid in (PLAIN,'CORE_CS2_029','CATA_472','CORE_REV_990','SC_400'):
            g=self.game(deck=(cid,));original=g.state.players[1].deck[0];cost=g.state.entities[original].cost
            self.play(g,CARD);self.next_owner(g);self.select(g)
            self.assertEqual((g.state.entities[original].zone,g.state.entities[original].cost),(Zone.HAND,max(0,cost-3)))

    def test_a15_opponent_natural_draw_is_not_replaced(self):
        g=self.game(other_deck=(PLAIN,));self.play(g,CARD);original=g.state.players[2].deck[0]
        g.apply(EndTurn(1));self.assertIsNone(g.state.pending_choice)
        self.assertIn(original,g.state.players[2].hand)
        self.assertFalse(g.state.card_discovery_history)

    def test_a16_pending_menu_recovers_clones_and_replays_without_resampling(self):
        g=self.game();self.play(g,CARD);self.next_owner(g);other=self.portable(g)
        self.select(g);self.select(other);self.assertEqual(other.snapshot(),g.snapshot());self.portable(g)

    def test_a17_selected_move_wait_keeps_discount_and_original_remaining_destructions(self):
        g=self.game(mode='wait_move');self.play(g,CARD);self.next_owner(g);offered=self.offers(g)
        self.select(g);self.assertEqual(g.state.entities[offered[0].card.entity_id].zone,Zone.HAND)
        self.assertTrue(all(g.state.entities[o.card.entity_id].zone==Zone.DECK for o in offered[1:]))
        self.portable(g,'wait_move');self.select(g)
        self.assertTrue(all(g.state.entities[o.card.entity_id].zone==Zone.GRAVEYARD for o in offered[1:]))

    def test_a18_destruction_batch_moves_all_unchosen_before_first_waiting_notice(self):
        g=self.game(mode='wait_destroy');self.play(g,CARD);self.next_owner(g);offered=self.offers(g)
        self.select(g)
        self.assertTrue(all(g.state.entities[o.card.entity_id].zone==Zone.GRAVEYARD for o in offered[1:]))
        self.portable(g,'wait_destroy')
        while g.state.pending_choice is not None:self.select(g)
        self.portable(g,'wait_destroy')

    def test_a19_failed_selected_move_rolls_back_to_exact_original_discovery_menu(self):
        g=self.game(mode='fail_move');self.play(g,CARD);self.next_owner(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g)
        self.assertEqual(g.snapshot(),saved)

    def test_a20_menu_and_selected_hand_identity_remain_private_to_the_owner(self):
        g=self.game();self.play(g,CARD);self.next_owner(g);selected=g.state.pending_choice.options[0].card_id
        before=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        for option in g.state.pending_choice.options:self.assertNotIn(option.card_id,before)
        self.select(g);after=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        self.assertNotIn(selected,after)

    def test_a21_second_player_uses_own_original_deck_and_permanent_program(self):
        g=self.game(seat=2);self.play(g,CARD);self.next_owner(g)
        self.assertEqual(g.state.pending_choice.player_id,2)
        offered=self.offers(g);self.assertTrue(all(o.card.player_id==2 for o in offered))
        self.select(g);self.assertEqual(g.state.entities[offered[0].card.entity_id].controller,2)

    def test_a22_existing_native_normal_draw_suppression_takes_priority(self):
        g=self.game(board=('TIME_617',));self.play(g,CARD);deck=g.state.players[1].deck[:];self.next_owner(g)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].deck,deck)

    def test_a23_rehashed_consistent_fake_previews_are_rejected_against_original_deck_material(self):
        g=self.game();self.play(g,CARD);self.next_owner(g);saved=deepcopy(g.snapshot())
        def corrupt(value):
            if isinstance(value,dict):
                if set(value)=={'cost','attack','health','max_health','durability','keywords'}:value['cost']+=100
                for child in value.values():corrupt(child)
            elif isinstance(value,list):
                for child in value:corrupt(child)
        corrupt(saved)
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry.__wrapped__())

    def test_a24_profile_and_enriched_zone_request_are_strict_and_do_not_accept_fake_combinations(self):
        r=registry.__wrapped__()
        with self.assertRaises(ValueError):r.register_turn_draw_replacement_profile(TurnDrawReplacementProfile(PROGRAM,'unknown'))
        with self.assertRaises(TypeError):r.turn_draw_replacement_profiles[PROGRAM]=None
        for kwargs in ({'operation':'copy_base','cost':CostSpec(delta=-3)},
                {'operation':'take','distinct':'entity','destroy_unchosen':True}):
            with self.assertRaises(ValueError):ChooseFromZone(1,1,Zone.DECK,**kwargs)

    def test_a25_original_offered_material_does_not_absorb_the_selected_only_discount(self):
        from hs_sim.engine.discovery_offers import ACCEPTED, decode_offer, offer_for_result
        from hs_sim.engine.offered_card_execution import copy_mode
        g=self.game(hand=(G+'boost',CARD),deck=(PLAIN,PLAIN,PLAIN))
        self.play(g,G+'boost');source=self.play(g,CARD);self.next_owner(g)
        event=next(e for e in reversed(g.events)if e.kind==ACCEPTED)
        original=decode_offer(g,dict(event.data)['original_offer'])
        for option,material in zip(original.options,original.materials):
            self.assertEqual(material.route,'physical')
            entity=g.state.entities[material.physical.origin.entity_id]
            self.assertEqual(material.physical.local.enchantments,tuple(entity.enchantments))
            self.assertEqual(copy_mode(g.state,option),'current')
            self.assertFalse(any(e.source_id==source for e in material.physical.local.enchantments))
        self.select(g)
        row,=g.state.card_discovery_history
        self.assertEqual(offer_for_result(g,row.result),original)


if __name__=='__main__':
    unittest.main()
