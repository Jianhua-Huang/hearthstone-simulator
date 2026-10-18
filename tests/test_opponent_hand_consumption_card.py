"""Iso'rath's real hand disruption, dormancy and original-player delivery."""
from collections import Counter
from copy import deepcopy
from functools import lru_cache
import json
import unittest

import test_stored_native_source_cards as f
from hs_sim.cards.opponent_hand_consumption_card import CARD, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
                           Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.dormancy import AwakenMinion
from hs_sim.engine.effects import AddToHand, ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P = 'k202.'
WATCH = P+'watch'


@lru_cache(None)
def registry(mode=None):
    r = f.registry.__wrapped__(None)
    def original(c):
        return next(c.state.entities[i] for i in c.state.players[c.player_id].board
                    if c.state.entities[i].card_id == CARD)
    def boost(c):
        card = c.state.entities[c.state.players[3-c.player_id].hand[0]]
        return (BuffStoredCard(CardReference.capture(card), 4, 5, c.source_id, cost=CostSpec(delta=-1)),)
    scripts = dict(awake=lambda c: (AwakenMinion(original(c).id, c.source_id),),
                   boost=boost,
                   fill=lambda c: tuple(AddToHand(3-c.player_id, f.A, c.source_id) for _ in range(10)))
    for name, body in scripts.items():
        r.register_behavior(P+name, body)
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name))
    def watch(c):
        source = c.state.entities.get(c.event.source_id)
        if source is None or source.card_id != CARD:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue'),
            ChoiceOption('bad', 'Rollback', (InvokeBehavior(f.P+'fail', c.source_id, c.player_id),))),
            c.source_id),)
    r.register_behavior(P+'watch', watch)
    event = {'dormant':'minion_dormant','return':'card_created','grant':'ability_granted'}.get(mode)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=50,
        triggers=() if event is None else (TriggerSpec(event, P+'watch'),)))
    r.validate()
    return r


class OpponentHandConsumptionTests(unittest.TestCase):
    def game(self, hand=(CARD,), enemy_hand=(f.A,f.B), board=(), actor=1, mode=None):
        self.mode = mode
        own = PlayerSetup('HERO_08', hand=hand, board=board, deck=(f.A,)*12,
                          mana=80, max_mana=80, mana_cap=80)
        other = PlayerSetup('HERO_08', hand=enemy_hand, deck=(f.B,)*12,
                            mana=80, max_mana=80, mana_cap=80)
        return Game.from_scenario(Scenario((own,other) if actor == 1 else (other,own),
            active_player=actor, seed=202), registry(mode))

    def eid(self, g, cid, zone='hand', player=None):
        p = g.state.active_player if player is None else player
        return next(i for i in getattr(g.state.players[p],zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None):
        eid = self.eid(g,cid)
        g.apply(PlayCard(g.state.active_player,eid,target))
        return eid

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        fresh = registry.__wrapped__(self.mode)
        self.assertEqual(Game.from_snapshot(deepcopy(snap),fresh).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),fresh).snapshot(),snap)

    def wake(self, g):
        for _ in range(4):
            g.apply(EndTurn(g.state.active_player))

    def hand(self, g, player):
        return Counter(g.state.entities[i].card_id for i in g.state.players[player].hand)

    def test_original_card_and_dormancy_evidence_are_complete(self):
        data = load_batch()
        self.assertEqual([x['record']['id'] for x in data['cards']],[CARD])
        self.assertEqual([x['record']['id'] for x in data['evidence_only']],['CATA_481e'])
        self.assertNotIn('CATA_481e',registry().cards)
        self.assertEqual(len(data['official_observations']),2)
        for row in data['cards']+data['evidence_only']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        c = registry().card(CARD)
        self.assertEqual((c.cost,c.attack,c.health),(5,5,3))

    def test_real_play_consumes_two_opponent_cards_and_pays_five(self):
        g = self.game(enemy_hand=(f.A,f.B,f.FIRE,f.FOUR))
        before = set(g.state.players[2].hand)
        source = self.play(g,CARD)
        rows = g.state.consumed_card_history
        self.assertEqual((g.state.players[1].mana,len(rows),len(g.state.players[2].hand)),(75,2,2))
        self.assertEqual([len(x.candidates) for x in rows],[4,3])
        self.assertEqual({x.card.origin.entity_id for x in rows},before-set(g.state.players[2].hand))
        self.assertEqual(g.state.entities[source].dormancy.remaining_turns,2)
        self.assertFalse(g.state.discard_history or g.state.death_history or g.state.draw_history)
        self.portable(g)

    def test_own_other_hand_cards_are_never_consumed(self):
        g = self.game((CARD,f.A,f.FIRE))
        own = {self.eid(g,f.A),self.eid(g,f.FIRE)}
        self.play(g,CARD)
        self.assertEqual(set(g.state.players[1].hand),own)

    def test_one_opponent_card_is_consumed_once(self):
        g = self.game(enemy_hand=(f.A,))
        self.play(g,CARD)
        self.assertEqual(len(g.state.consumed_card_history),1)
        self.assertFalse(g.state.players[2].hand)

    def test_empty_hand_still_goes_dormant_without_rng_draw(self):
        g = self.game(enemy_hand=())
        before = g.snapshot()['rng_state']
        source = self.play(g,CARD)
        self.assertFalse(g.state.consumed_card_history)
        self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertEqual(g.state.entities[source].dormancy.remaining_turns,2)

    def test_same_named_cards_remain_distinct_physical_targets(self):
        g = self.game(enemy_hand=(f.A,f.A))
        self.play(g,CARD)
        self.assertEqual(len({x.card.origin.entity_id for x in g.state.consumed_card_history}),2)

    def test_full_hand_card_types_are_not_filtered_to_minions(self):
        for kind in (CardType.MINION,CardType.SPELL,CardType.WEAPON,CardType.HERO,CardType.LOCATION):
            with self.subTest(kind=kind):
                cid = next(c.id for c in registry().cards.values() if c.kind == kind and c.hand_playable)
                g = self.game((CARD,P+'awake',f.P+'kill'),enemy_hand=(cid,))
                source = self.play(g,CARD)
                self.assertEqual(g.state.consumed_card_history[0].card.origin.card_id,cid)
                self.play(g,P+'awake'); self.play(g,f.P+'kill',source)
                self.assertEqual(self.hand(g,2),Counter({cid:1}))

    def test_dormancy_counts_owner_starts_and_does_not_create_summons(self):
        g = self.game()
        source = self.play(g,CARD)
        g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[source].dormancy.remaining_turns,2)
        g.apply(EndTurn(2))
        self.assertEqual(g.state.entities[source].dormancy.remaining_turns,1)
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertIsNone(g.state.entities[source].dormancy)
        self.assertFalse(g.state.consumed_card_history[0].card.origin.entity_id in g.state.players[2].hand)
        self.portable(g)

    def test_natural_death_returns_both_cards_to_original_player(self):
        g = self.game((CARD,P+'awake',f.P+'kill'))
        source = self.play(g,CARD)
        original = {x.card.origin.entity_id for x in g.state.consumed_card_history}
        self.play(g,P+'awake');self.play(g,f.P+'kill',source)
        self.assertEqual(self.hand(g,2),Counter({f.A:1,f.B:1}))
        self.assertTrue(all(g.state.entities[i].zone == Zone.SETASIDE for i in original))
        self.assertTrue(original.isdisjoint(g.state.players[2].hand))
        self.portable(g)

    def test_current_consumed_material_retains_stored_stats_and_cost(self):
        g = self.game((CARD,P+'boost',P+'awake',f.P+'kill'))
        self.play(g,P+'boost')
        source = self.play(g,CARD)
        self.play(g,P+'awake');self.play(g,f.P+'kill',source)
        card = g.state.entities[self.eid(g,f.A,player=2)]
        self.assertEqual((card.attack,card.max_health),(6,8))
        self.assertEqual(f.registry().card(f.A).cost,1)
        from hs_sim.engine.costs import quote_unselected_cost
        self.assertEqual(quote_unselected_cost(g.state,g.registry,card).amount,0)

    def test_source_transfer_does_not_change_original_return_player(self):
        g = self.game((CARD,P+'awake',f.P+'give',f.P+'kill'))
        source = self.play(g,CARD)
        self.play(g,P+'awake');self.play(g,f.P+'give',source)
        self.play(g,f.P+'kill',source)
        self.assertEqual(self.hand(g,2),Counter({f.A:1,f.B:1}))

    def test_second_seat_consumes_and_returns_first_seat_cards(self):
        g = self.game((CARD,P+'awake',f.P+'kill'),actor=2)
        source = self.play(g,CARD)
        self.assertFalse(g.state.players[1].hand)
        self.play(g,P+'awake');self.play(g,f.P+'kill',source)
        self.assertEqual(self.hand(g,1),Counter({f.A:1,f.B:1}))

    def test_silence_removes_return_payload(self):
        g = self.game((CARD,P+'awake',f.P+'silence',f.P+'kill'))
        source = self.play(g,CARD)
        self.play(g,P+'awake');self.play(g,f.P+'silence',source);self.play(g,f.P+'kill',source)
        self.assertFalse(g.state.players[2].hand)

    def test_bounce_loses_old_payload_without_giving_cards_back(self):
        g = self.game((CARD,P+'awake',f.P+'bounce'))
        source = self.play(g,CARD)
        self.play(g,P+'awake');self.play(g,f.P+'bounce',source)
        self.assertFalse(g.state.players[2].hand)
        self.assertFalse(any(a.consumed_card_id is not None for a in g.state.entities[source].abilities))
        self.play(g,CARD)
        self.assertEqual(len(g.state.consumed_card_history),2)

    def test_repeated_accepted_battlecry_uses_new_opponent_hand_pool(self):
        g = self.game(board=(f.BC2,),enemy_hand=(f.A,f.B,f.FIRE,f.FOUR))
        source = self.play(g,CARD)
        self.assertEqual(len(g.state.consumed_card_history),4)
        self.assertEqual([len(x.candidates) for x in g.state.consumed_card_history],[4,3,2,1])
        self.assertEqual(g.state.entities[source].dormancy.remaining_turns,2)

    def test_repeated_deathrattle_returns_current_material_twice(self):
        g = self.game((CARD,P+'awake',f.P+'kill'),board=(f.DR2,))
        source = self.play(g,CARD)
        self.play(g,P+'awake');self.play(g,f.P+'kill',source)
        self.assertEqual(self.hand(g,2),Counter({f.A:2,f.B:2}))
        self.assertEqual(len(g.state.consumed_card_history),2)

    def test_current_copy_preserves_return_payload(self):
        g = self.game((CARD,P+'awake',f.P+'copy',f.P+'kill',f.P+'kill'))
        source = self.play(g,CARD)
        self.play(g,P+'awake');self.play(g,f.P+'copy',source)
        other = next(i for i in g.state.players[1].board if i != source)
        self.play(g,f.P+'kill',source);self.play(g,f.P+'kill',other)
        self.assertEqual(self.hand(g,2),Counter({f.A:2,f.B:2}))
        self.portable(g)

    def test_actual_inheritance_preserves_original_return_player(self):
        g = self.game((CARD,P+'awake',f.P+'kill','EDR_491',f.P+'kill'))
        source = self.play(g,CARD)
        self.play(g,P+'awake');self.play(g,f.P+'kill',source)
        inheritor = self.play(g,'EDR_491')
        self.play(g,f.P+'kill',inheritor)
        self.assertEqual(self.hand(g,2),Counter({f.A:2,f.B:2}))
        self.portable(g)

    def test_historical_printed_body_does_not_return_additional_grants(self):
        g = self.game((CARD,P+'awake',f.P+'kill','JAIL_940'))
        source = self.play(g,CARD)
        self.play(g,P+'awake');self.play(g,f.P+'kill',source)
        self.play(g,'JAIL_940')
        self.assertEqual(self.hand(g,2),Counter({f.A:1,f.B:1}))

    def test_full_original_hand_uses_normal_burn_capacity(self):
        g = self.game((CARD,P+'fill',P+'awake',f.P+'kill'))
        source = self.play(g,CARD)
        self.play(g,P+'fill');self.play(g,P+'awake');self.play(g,f.P+'kill',source)
        self.assertEqual(len(g.state.players[2].hand),10)
        self.assertEqual(len([x for x in g.events if x.kind == 'card_burned']),2)
        self.assertEqual(len(g.state.death_history),1)
        self.portable(g)

    def test_dormancy_waiting_contains_both_consumptions_and_restores(self):
        g = self.game(board=(WATCH,),mode='dormant')
        source = self.play(g,CARD)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(g.state.consumed_card_history),2)
        self.assertEqual(g.state.entities[source].dormancy.remaining_turns,2)
        self.portable(g)
        self.choose(g)
        self.assertIsNone(g.state.pending_choice)

    def test_failed_dormancy_choice_restores_original_waiting(self):
        g = self.game(board=(WATCH,),mode='dormant')
        self.play(g,CARD)
        before = g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        self.choose(g)

    def test_each_return_waiting_restores_remaining_payloads_once(self):
        g = self.game((CARD,P+'awake',f.P+'kill'),board=(WATCH,),mode='return')
        source = self.play(g,CARD)
        self.play(g,P+'awake');self.play(g,f.P+'kill',source)
        for _ in range(2):
            self.assertIsNotNone(g.state.pending_choice)
            self.portable(g);self.choose(g)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(self.hand(g,2),Counter({f.A:1,f.B:1}))

    def test_consumption_receipts_are_not_exposed_to_players(self):
        g = self.game()
        self.play(g,CARD)
        for player in (1,2):
            visible = json.dumps(g.observe(player))+json.dumps(g.player_events(player))
            for key in ('consumed_card_history','consumed_card_id','candidates','rng_before','rng_after','card.origin'):
                self.assertNotIn('"'+key+'"',visible)
