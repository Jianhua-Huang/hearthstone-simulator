"""Real Maloriak, original discard material and ordinary quantity delivery."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_discard_summon_cards import CARD, BODY, load_batch, register_native_discard_summon_cards
from hs_sim.engine import (CardClass, CardDefinition, CardType, EndTurn, Game, Keyword, LaunchStarship,
    PlayCard, PlayerSetup, Registry, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.copy_materials import CopyEntryMaterial, validate_scope
from hs_sim.engine.discard_summons import capture
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Destroy, Draw, InvokeBehavior,
    RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import AppendageSpec, CostSpec, SummonQuantitySpec
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, validate_request
from hs_sim.engine.temporary_cards import MakeHandCardTemporary
from hs_sim.engine.zones import CardReference, CopyCard, DiscardCard, DiscardMatching, MoveCard

P = 'k182.'
HERO, MINION, SPELL, OWN, QUANTITY, WAIT, GROW, LEAVE, AFTER, PART, SHIP, COLOSSAL, LIMB, MAGNETIC, DORMANT = (
    P+x for x in ('hero', 'minion', 'blank', 'own', 'quantity', 'wait', 'grow', 'leave', 'after',
                  'part', 'ship', 'colossal', 'limb', 'magnetic', 'dormant'))


@lru_cache(maxsize=8)
def registry(role='writer'):
    r = Registry('k182-discard-summon-v1')
    register_native_discard_summon_cards(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=150))
    r.register_card(CardDefinition(SPELL, SPELL, CardType.SPELL))
    r.register_behavior(P+'bc', lambda c: (AddToHand(c.player_id, SPELL, c.source_id),))
    r.register_card(CardDefinition(MINION, MINION, CardType.MINION, cost=2, attack=2, health=5,
                                  battlecry=P+'bc', keywords=(Keyword.TAUNT,)))
    r.register_behavior(P+'own', lambda c: (AddToHand(c.player_id, SPELL, c.source_id),))
    r.register_card(CardDefinition(OWN, OWN, CardType.MINION, cost=2, attack=3, health=4, on_discard=P+'own'))
    r.register_card(CardDefinition(QUANTITY, QUANTITY, CardType.MINION, health=8,
                                  summon_quantities=(SummonQuantitySpec(),)))
    r.register_card(CardDefinition(PART, PART, CardType.MINION, attack=3, health=4,
                                  keywords=(Keyword.STARSHIP_PIECE, Keyword.TAUNT)))
    r.register_card(CardDefinition(SHIP, SHIP, CardType.MINION, cost=5, starship_for=(CardClass.NEUTRAL,)))
    r.register_card(CardDefinition(LIMB, LIMB, CardType.MINION, attack=1, health=2))
    r.register_card(CardDefinition(COLOSSAL, COLOSSAL, CardType.MINION, cost=4, attack=4, health=7,
                                  keywords=(Keyword.COLOSSAL,), colossal=(AppendageSpec(LIMB),)))
    r.register_card(CardDefinition(MAGNETIC, MAGNETIC, CardType.MINION, cost=2, attack=2, health=3,
                                  keywords=(Keyword.MAGNETIC,), magnetic_tribes=('mech',)))
    r.register_card(CardDefinition(DORMANT, DORMANT, CardType.MINION, cost=2, attack=3, health=6, dormant_turns=2))

    def ref(c, player=None):
        pid = c.player_id if player is None else player
        return CardReference.capture(next(c.state.entities[i] for i in c.state.players[pid].hand
                                         if c.state.entities[i].kind == CardType.MINION))
    def bad(c):
        raise ResolutionError('k182 deliberate original discard reaction failure')
    r.register_behavior(P+'bad', bad)
    scripts = {
        'discard': lambda c: (DiscardCard(ref(c), c.source_id),),
        'enemy': lambda c: (DiscardCard(ref(c, 3-c.player_id), c.source_id),),
        'blank_discard': lambda c: (DiscardCard(CardReference.capture(next(c.state.entities[i] for i in
            c.state.players[c.player_id].hand if c.state.entities[i].card_id == SPELL)), c.source_id),),
        'twice': lambda c: (DiscardMatching(c.player_id, query=PoolQuery(kinds=(CardType.MINION,)), count=2,
                                          selection='first', source_id=c.source_id),),
        'stale': lambda c: (DiscardCard(ref(c), c.source_id), DiscardCard(ref(c), c.source_id)),
        'buff': lambda c: (BuffStoredCard(ref(c), 3, 4, cost=CostSpec(delta=-1), source_id=c.source_id),),
        'temporary': lambda c: (MakeHandCardTemporary(ref(c), c.state.turn, source_id=c.source_id),),
        'move': lambda c: (MoveCard(ref(c), c.player_id, Zone.DECK, source_id=c.source_id),),
        'draw': lambda c: (Draw(c.player_id, 2, source_id=c.source_id),),
        'fault': lambda c: (DiscardCard(ref(c), c.source_id), InvokeBehavior(P+'bad', c.source_id, c.player_id)),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'silence': lambda c: (Silence(c.target_id),),
    }
    for key, body in scripts.items():
        r.register_behavior(P+key, body)
        r.register_card(CardDefinition(P+key, P+key, CardType.SPELL, on_play=P+key,
                                      requires_target=key in ('kill', 'bounce', 'silence')))

    def own_event(c):
        return c.event.player_id == c.player_id
    def wait(c):
        if not own_event(c): return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue'),
            ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'bad', c.source_id, c.player_id),)),
            ChoiceOption('remove', 'Remove source', tuple(Destroy(i, c.source_id) for i in
                c.state.players[c.player_id].board if c.state.entities[i].card_id == CARD)),
        ), c.source_id),)
    def grow(c):
        if not own_event(c): return ()
        row = next(x for x in c.state.discard_history if x.event_sequence == c.event.sequence)
        return (BuffStoredCard(row, 10, 10, source_id=row.entity_id),)
    def leave(c):
        if not own_event(c): return ()
        row = next(x for x in c.state.discard_history if x.event_sequence == c.event.sequence)
        return (ReturnToHand(row.entity_id, discard=row),)
    def after(c):
        source = c.state.entities[c.event.target_id]
        if source.origin_entity_id is None: return ()
        row = next(x for x in c.state.discard_history if x.entity_id == source.origin_entity_id)
        # Only the first actual copy suspends; the next body must keep the original recipe.
        if sum(x.origin_entity_id == row.entity_id for x in c.state.entities.values()) != 1: return ()
        return (BuffStoredCard(row, 20, 20, source_id=row.entity_id), RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue'),
            ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'bad', c.source_id, c.player_id),)),
        ), c.source_id))
    for cid, event, body in ((WAIT, 'card_discarded', wait), (GROW, 'card_discarded', grow),
                             (LEAVE, 'card_discarded', leave), (AFTER, 'minion_summoned', after)):
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=8, triggers=(TriggerSpec(event, cid),)))
    r.validate()
    return r


class NativeDiscardSummonCardTests(unittest.TestCase):
    def game(self, hand=('discard', MINION), board=(CARD,), enemy=(), enemy_hand=(), deck=(), active=1):
        def names(values): return tuple(P+x if x in ('discard', 'enemy', 'blank_discard', 'twice', 'stale',
            'buff', 'temporary', 'move', 'draw', 'fault', 'kill', 'bounce', 'silence') else x for x in values)
        return Game.from_scenario(Scenario((PlayerSetup(HERO, hand=names(hand), board=board, deck=deck,
            mana=40, max_mana=40, mana_cap=40), PlayerSetup(HERO, hand=names(enemy_hand), board=enemy,
            mana=40, max_mana=40, mana_cap=40)), active_player=active, seed=182), registry())
    def eid(self, g, cid, player=1, zone='hand'):
        return next(i for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)
    def play(self, g, cid, target=None):
        if not cid.startswith(P) and cid != CARD: cid = P+cid
        pid = g.state.active_player; eid = self.eid(g, cid, pid)
        g.apply(PlayCard(pid, eid, target, position=len(g.state.players[pid].board)
                         if g.state.entities[eid].kind == CardType.MINION else None))
        return eid
    def copies(self, g, original=None):
        return [e for e in g.state.entities.values() if e.origin_entity_id is not None and
                (original is None or e.origin_entity_id == original) and e.zone == Zone.BOARD]
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); h = Game.from_snapshot(saved, registry('reader'))
        self.assertEqual(h.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry('replay')).snapshot(), saved)
        return h

    def test_raw_face_actual_paid_entry_and_dragon_metadata(self):
        raw = load_batch()['cards'][0]['record']; card = registry().card(CARD)
        self.assertEqual((raw['cost'], card.cost, card.attack, card.health), (7, 7, 7, 7))
        self.assertEqual(card.metadata.classes, (CardClass.WARLOCK,))
        self.assertIn('dragon', card.metadata.tribes)
        g = self.game((CARD,), board=()); self.play(g, CARD)
        self.assertEqual(g.state.players[1].mana, 33)
        self.assertFalse(g.state.discard_history); self.assertFalse(g.state.card_summon_history)

    def test_successful_own_minion_discard_creates_independent_current_copy_without_battlecry(self):
        g = self.game(); original = self.eid(g, MINION); self.play(g, 'discard')
        copy, = self.copies(g, original)
        self.assertEqual((copy.card_id, copy.attack, copy.health, copy.owner, copy.controller), (MINION, 2, 5, 1, 1))
        self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD)
        self.assertFalse(g.state.players[1].hand)
        self.assertEqual(len(g.state.discard_history), 1)
        self.assertEqual(len(g.state.successful_summon_history), 1)
        self.portable(g)

    def test_current_hand_growth_cost_and_independent_attachments(self):
        g = self.game(('buff', 'discard', MINION)); original = self.eid(g, MINION)
        self.play(g, 'buff'); self.play(g, 'discard'); copy, = self.copies(g, original)
        self.assertEqual((copy.attack, copy.health, copy.cost), (5, 9, 1))
        a = {x.id for x in copy.enchantments}; b = {x.id for x in g.state.entities[original].enchantments}
        self.assertTrue(a); self.assertTrue(a.isdisjoint(b)); self.assertIn(Keyword.TAUNT, copy.keywords)
        self.portable(g)

    def test_spell_discard_opponent_discard_move_and_burn_do_not_trigger(self):
        g = self.game(('blank_discard', SPELL)); self.play(g, 'blank_discard'); self.assertFalse(self.copies(g))
        g = self.game(('enemy',), enemy_hand=(MINION,)); self.play(g, 'enemy'); self.assertFalse(self.copies(g))
        g = self.game(('move', MINION)); self.play(g, 'move'); self.assertFalse(g.state.discard_history)
        g = self.game(('draw',)+(SPELL,)*9, deck=(MINION, MINION)); self.play(g, 'draw')
        self.assertTrue(any(e.kind == 'card_burned' for e in g.events))
        self.assertFalse(g.state.discard_history); self.assertFalse(self.copies(g))

    def test_opponent_caused_own_discard_still_uses_original_discard_player(self):
        g = self.game((MINION,), enemy_hand=('enemy',), active=2); original = self.eid(g, MINION)
        self.play(g, 'enemy'); copy, = self.copies(g, original)
        self.assertEqual((copy.owner, copy.controller), (1, 1)); self.portable(g)

    def test_temporary_hand_lease_does_not_destroy_new_board_copy(self):
        g = self.game(('temporary', 'discard', MINION)); original = self.eid(g, MINION)
        self.play(g, 'temporary'); self.play(g, 'discard'); copy, = self.copies(g, original)
        self.assertIsNone(copy.hand_lifetime)
        g.apply(EndTurn(1)); self.assertEqual(g.state.entities[copy.id].zone, Zone.BOARD); self.portable(g)

    def test_each_successful_physical_discard_gets_one_original_root_and_stale_request_skips(self):
        g = self.game(('twice', MINION, OWN)); self.play(g, 'twice')
        self.assertEqual(len(g.state.discard_history), 2); self.assertEqual(len(self.copies(g)), 2)
        self.assertEqual(len(g.state.card_summon_history), 2); self.assertEqual(len(g.state.players[1].hand), 1)
        self.portable(g)
        g = self.game(('stale', MINION)); self.play(g, 'stale')
        self.assertEqual(len(g.state.discard_history), 1); self.assertEqual(len(self.copies(g)), 1)

    def test_full_board_preserves_real_discard_and_consumes_no_randomness(self):
        g = self.game(board=(CARD,)+(MINION,)*6); rng = deepcopy(g.snapshot()['rng_state'])
        self.play(g, 'discard'); self.assertFalse(self.copies(g)); self.assertEqual(len(g.state.discard_history), 1)
        self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertTrue(any(e.kind == 'summon_failed' for e in g.events)); self.portable(g)

    def test_ordinary_quantity_copies_frozen_material_and_respects_remaining_space(self):
        for fillers, expected in ((0, 2), (4, 1)):
            with self.subTest(fillers=fillers):
                g = self.game(board=(CARD, QUANTITY)+(MINION,)*fillers); self.play(g, 'discard')
                self.assertEqual(len(self.copies(g)), expected)
                self.assertEqual(g.state.card_summon_history[-1].plan.total, 2); self.portable(g)

    def test_two_sources_have_distinct_acceptance_clocks_and_same_original_material(self):
        g = self.game(('buff', 'discard', MINION), board=(CARD, CARD)); self.play(g, 'buff'); self.play(g, 'discard')
        self.assertEqual([(e.attack, e.health) for e in self.copies(g)], [(5, 9), (5, 9)])
        roots = g.state.card_summon_history
        self.assertEqual(roots[0].request.materials[0].local, roots[1].request.materials[0].local)
        self.assertGreater(roots[1].plan.next_attachment_id, roots[0].plan.next_attachment_id); self.portable(g)

    def test_earlier_listener_growth_does_not_change_original_material(self):
        g = self.game(board=(GROW, CARD)); original = self.eid(g, MINION); self.play(g, 'discard')
        self.assertEqual(g.state.entities[original].attack, 12)
        self.assertEqual(self.copies(g, original)[0].attack, 2); self.portable(g)

    def test_earlier_listener_return_does_not_cancel_or_recapture_original_copy(self):
        g = self.game(board=(LEAVE, CARD)); original = self.eid(g, MINION); self.play(g, 'discard')
        self.assertEqual(g.state.entities[original].zone, Zone.HAND)
        self.assertEqual(len(self.copies(g, original)), 1); self.portable(g)

    def test_wait_before_body_restores_original_event_even_after_source_removed(self):
        g = self.game(board=(WAIT, CARD)); self.play(g, 'discard'); self.assertFalse(self.copies(g))
        h = self.portable(g); self.choose(g, 'remove'); self.choose(h, 'remove')
        self.assertEqual(g.snapshot(), h.snapshot()); self.assertEqual(len(self.copies(g)), 1); self.portable(g)

    def test_wait_between_quantity_deliveries_retains_original_recipe(self):
        g = self.game(('buff', 'discard', MINION), board=(CARD, QUANTITY, AFTER))
        original = self.eid(g, MINION); self.play(g, 'buff'); self.play(g, 'discard')
        self.assertIsNotNone(g.state.pending_choice); h = self.portable(g)
        self.assertEqual(g.state.entities[original].attack, 25)
        self.choose(g); self.choose(h); self.assertEqual(h.snapshot(), g.snapshot())
        self.assertEqual([(e.attack, e.health) for e in self.copies(g)], [(5, 9), (5, 9)]); self.portable(g)

    def test_choice_failure_rolls_back_pending_original_delivery(self):
        g = self.game(board=(CARD, QUANTITY, AFTER)); self.play(g, 'discard'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved); self.choose(g)
        self.assertEqual(len(self.copies(g)), 2); self.portable(g)

    def test_late_failure_rolls_back_discard_entities_quantities_and_history(self):
        g = self.game(('fault', MINION)); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'fault')
        self.assertEqual(g.snapshot(), saved); self.assertFalse(g.state.discard_history)

    def test_silence_removes_future_listener_and_native_copy_rebinds_self_source(self):
        g = self.game(('silence', 'discard', MINION)); self.play(g, 'silence', self.eid(g, CARD, zone='board'))
        self.play(g, 'discard'); self.assertFalse(self.copies(g))
        g = self.game(('discard', CARD)); original = self.eid(g, CARD); self.play(g, 'discard')
        copy, = self.copies(g, original)
        self.assertTrue(any(a.behavior_id == BODY and a.source_id == copy.id for a in copy.abilities))
        self.assertEqual(len(g.state.discard_history), 1); self.portable(g)

    def test_native_on_discard_is_independent_and_not_replayed_by_copy(self):
        g = self.game(('discard', OWN)); self.play(g, 'discard')
        self.assertEqual(len(g.state.players[1].hand), 1)
        self.assertEqual(len(self.copies(g)), 1); self.portable(g)

    def test_colossal_copy_uses_normal_appendages_and_native_summon_history(self):
        g = self.game(('discard', COLOSSAL)); original = self.eid(g, COLOSSAL); self.play(g, 'discard')
        self.assertEqual(len(self.copies(g, original)), 1)
        self.assertEqual(len([i for i in g.state.players[1].board if g.state.entities[i].card_id == LIMB]), 1)
        self.assertEqual(len(g.state.colossal_history), 1); self.portable(g)

    def test_magnetic_piece_and_printed_dormancy_use_their_normal_summon_entry(self):
        for cid in (MAGNETIC, PART, DORMANT):
            with self.subTest(cid=cid):
                g = self.game(('discard', cid)); self.play(g, 'discard'); copy, = self.copies(g)
                self.assertEqual(copy.card_id, cid)
                if cid == DORMANT: self.assertIsNotNone(copy.dormancy)
                else: self.assertIn(Keyword.MAGNETIC if cid == MAGNETIC else Keyword.STARSHIP_PIECE, copy.keywords)
                self.portable(g)

    def test_actual_launched_bounced_ship_copies_complete_original_components(self):
        from hs_sim.engine.starships import construction
        g = self.game(('kill', 'bounce', 'discard'), board=(CARD, PART))
        self.play(g, 'kill', self.eid(g, PART, zone='board')); ship = construction(g.state, 1)
        g.apply(LaunchStarship(1, ship.id)); self.play(g, 'bounce', ship.id); self.play(g, 'discard')
        copy, = self.copies(g, ship.id)
        self.assertEqual(copy.components, (PART,)); self.assertEqual((copy.attack, copy.health), (3, 4))
        self.assertIn(Keyword.TAUNT, copy.keywords); self.portable(g)

    def test_private_materials_do_not_escape_player_projection(self):
        g = self.game(board=(WAIT, CARD)); self.play(g, 'discard')
        for pid in (1, 2):
            visible = json.dumps(g.observe(pid), ensure_ascii=False)
            for token in ('CopyEntryMaterial', 'copy_materials', 'discard_summon_copy', 'next_attachment_id', 'resolution_frame'):
                self.assertNotIn(token, visible)
        self.portable(g)

    def test_original_material_scope_recipient_future_and_old_hand_profile_rejections(self):
        g = self.game(); self.play(g, 'discard'); root = g.state.card_summon_history[0]
        material = root.request.materials[0]; self.assertEqual(material.profile, 'discard_summon_copy')
        validate_scope(g.state, registry(), material)
        for changed in (replace(root.request, player_id=2), replace(root.request, cause=replace(root.request.cause, action=root.request.cause.action+1))):
            with self.assertRaises(ValueError): validate_request(g.state, registry(), changed)
        with self.assertRaises(ValueError): validate_scope(g.state, registry(), replace(material, next_attachment_id=g.state.next_attachment_id+1))
        with self.assertRaises(ValueError): CopyCard(material, 1)
        old = replace(material, profile='discard_copy')
        with self.assertRaises(ValueError): validate_request(g.state, registry(), replace(root.request, materials=(old,)))
        with self.assertRaises(ValueError): replace(material, mode='base', local=None)
        with self.assertRaises(ValueError): capture(None, registry())

    def test_snapshot_rejects_old_schema_and_mutated_original_discard_material(self):
        g = self.game(board=(CARD, QUANTITY, AFTER)); self.play(g, 'discard')
        saved = g.snapshot(); old = deepcopy(saved); old['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError): Game.from_snapshot(old, registry('reader'))
        # Structural receipts are validated independently of the snapshot hash.
        root = g.state.card_summon_history[0]; material = root.request.materials[0]
        with self.assertRaises(ValueError):
            validate_scope(g.state, registry(), replace(material, discard=replace(material.discard, player_id=2)))


if __name__ == '__main__':
    unittest.main()
