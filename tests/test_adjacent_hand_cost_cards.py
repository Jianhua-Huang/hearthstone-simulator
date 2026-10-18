"""Native Sabotage hand positions share ordinary quotes, payments and persistence."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.adjacent_hand_cost_cards import AURA, CARD, SABOTAGE, load_batch, register_adjacent_hand_cost_cards
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CastStoredSpell,
    Game, IllegalAction, PlayCard, PlayerSetup, Registry, ResolutionError, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.costs import quote_accepted_hand, quote_cost, quote_generated_cost
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (ChoiceOption, GrantCostAura, InvokeBehavior, ModifyCost,
    RequestChoice, Summon)
from hs_sim.engine.model import CostAuraSpec, CostSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard, DiscardCard, MoveCard, ReorderZone

P = 'k216.'
HERO, SPELL, MINION, WEAPON, LOCATION, HERO_CARD, WATCH, REDUCER = (
    P+x for x in ('hero', 'spell', 'minion', 'weapon', 'location', 'hero-card', 'watch', 'reducer'))
CMD = P+'cmd.'
META = CardMetadata(False, (CardClass.HUNTER,), None, tribes=())


@lru_cache(None)
def registry(mode=None):
    r = Registry(P+'host'); register_adjacent_hand_cost_cards(r)
    r.register_behavior(P+'empty', lambda c: ())
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('Deliberate Sabotage rollback')))
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=80, metadata=META))
    r.register_card(CardDefinition(SPELL, SPELL, CardType.SPELL, cost=2, on_play=P+'empty', metadata=META))
    r.register_card(CardDefinition(MINION, MINION, CardType.MINION, cost=3, attack=2, health=5, metadata=META))
    r.register_card(CardDefinition(WEAPON, WEAPON, CardType.WEAPON, cost=3, attack=2, durability=2, metadata=META))
    r.register_card(CardDefinition(LOCATION, LOCATION, CardType.LOCATION, cost=3, durability=2,
        on_use=P+'empty', metadata=META))
    r.register_card(CardDefinition(P+'power', 'Power', CardType.HERO_POWER, cost=2, on_use=P+'empty', metadata=META))
    r.register_card(CardDefinition(HERO_CARD, HERO_CARD, CardType.HERO, cost=3, health=60,
        hero_card=True, initial_hero_power=P+'power', metadata=META))
    r.register_card(CardDefinition(REDUCER, REDUCER, CardType.MINION, health=10, metadata=META,
        cost_auras=(CostAuraSpec(CostSpec(delta=-1)),)))
    def native(c, zone=Zone.HAND):
        return CardReference.capture(next(c.state.entities[i]
            for i in getattr(c.state.players[c.player_id], zone.value)
            if c.state.entities[i].card_id == SABOTAGE))
    def left(c):
        hand = tuple(c.state.players[c.player_id].hand); source = native(c).entity_id
        return (ReorderZone(c.player_id, Zone.HAND, (source,)+tuple(i for i in hand if i != source)),)
    scripts = {
        'left': left,
        'discard': lambda c: (DiscardCard(native(c), c.source_id),),
        'transfer': lambda c: (MoveCard(native(c), 3-c.player_id, Zone.HAND, source_id=c.source_id),),
        'deck': lambda c: (MoveCard(native(c), c.player_id, Zone.DECK, source_id=c.source_id),),
        'hand': lambda c: (MoveCard(native(c, Zone.DECK), c.player_id, Zone.HAND, source_id=c.source_id),),
        'transform': lambda c: (TransformStoredCard(native(c), SPELL, c.source_id),),
        'copy_current': lambda c: (CopyCard(native(c), c.player_id, mode='current', source_id=c.source_id),),
        'copy_base': lambda c: (CopyCard(native(c), c.player_id, mode='base', source_id=c.source_id),),
        'auto': lambda c: (CastStoredSpell(native(c), c.player_id, c.source_id),),
        'discount': lambda c: tuple(ModifyCost(i, CostSpec(set_to=1), c.source_id)
            for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == SPELL),
        'summon': lambda c: (Summon(c.player_id, CARD),),
    }
    for name, body in scripts.items():
        r.register_behavior(P+name, body)
        r.register_card(CardDefinition(CMD+name, name, CardType.SPELL, on_play=P+name, metadata=META))
    def watch(c):
        if mode != 'wait' or c.event.player_id != c.player_id: return ()
        original = c.state.entities[c.event.source_id]
        if original.card_id not in (SPELL, MINION): return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue'),
            ChoiceOption('discard', 'Discard source', (DiscardCard(native(c), c.source_id),)),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
    r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('card_committed', P+'watch'),)))
    r.validate(); return r


class AdjacentHandCostTests(unittest.TestCase):
    def game(self, hand=(), enemy_hand=(), board=(), owner=1, mode=None, mana=30, deck=(SPELL,)*4):
        self.owner, self.mode = owner, mode
        own = PlayerSetup(HERO, hand=hand, board=board, deck=deck, mana=mana, max_mana=30, mana_cap=30)
        other = PlayerSetup(HERO, hand=enemy_hand, deck=(SPELL,)*4, mana=30, max_mana=30, mana_cap=30)
        return Game.from_scenario(Scenario((own, other) if owner == 1 else (other, own),
            active_player=owner, seed=216), registry(mode))
    def ids(self, g, cid, player=None, zone='hand'):
        return tuple(i for i in getattr(g.state.players[self.owner if player is None else player], zone)
            if g.state.entities[i].card_id == cid)
    def prices(self, g, player=None):
        return tuple(quote_cost(g.state, g.registry, g.state.entities[i]).amount
            for i in g.state.players[self.owner if player is None else player].hand)
    def play(self, g, cid, index=0):
        eid = self.ids(g, cid)[index]; g.apply(PlayCard(self.owner, eid)); return eid
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); r = registry.__wrapped__(self.mode)
        restored = Game.from_snapshot(deepcopy(saved), r)
        self.assertEqual(restored.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe())
            for key in ('hand_adjacent', 'hand_entry_id', 'rng_state', 'submitted_cost'):
                self.assertNotIn(key, public)
        return restored
    def rehash(self, data):
        data['events_hash'] = canonical_hash(data['events'])
        data['state_hash'] = canonical_hash({k: v for k, v in data.items()
            if k not in ('schema_version', 'state_hash', 'events', 'events_hash')})
        return data

    def test_full_raws_four_primary_faces_and_named_child_identity(self):
        from hs_sim.cards import build_registry
        r = build_registry(); data = load_batch()
        self.assertEqual((r.card(CARD).cost, r.card(CARD).attack, r.card(CARD).health), (4, 4, 4))
        self.assertEqual(r.card(SABOTAGE).cost, 2); self.assertFalse(r.card(SABOTAGE).metadata.collectible)
        self.assertEqual(r.card(SABOTAGE).cost_auras, (AURA,)); self.assertNotIn('CATA_186te', r.cards)
        self.assertEqual(len(data['official_observations']), 4)
        for row in data['official_observations']:
            if row['card_id'] == CARD: self.assertEqual(row['face']['childIds'], [123782])
            else: self.assertEqual(row['face']['parentId'], 123783)

    def test_real_four_mana_battlecry_gives_opponent_one_current_two_cost_provider(self):
        for owner in (1, 2):
            g = self.game((CARD,), enemy_hand=(SPELL,), owner=owner); self.play(g, CARD)
            self.assertEqual(g.state.players[owner].mana, 26)
            self.assertEqual(self.prices(g, 3-owner), (3, 2))
            self.assertFalse(self.ids(g, SABOTAGE)); self.assertEqual(len(self.ids(g, SABOTAGE, 3-owner)), 1)
            self.portable(g)

    def test_full_opponent_hand_burns_named_child_without_active_hand_aura(self):
        g = self.game((CARD,), enemy_hand=(SPELL,)*10); self.play(g, CARD)
        self.assertEqual(self.prices(g, 2), (2,)*10)
        self.assertFalse(self.ids(g, SABOTAGE, 2))
        child = next(e for e in g.state.entities.values() if e.card_id == SABOTAGE)
        self.assertEqual(child.zone, Zone.GRAVEYARD); self.portable(g)

    def test_current_left_middle_and_right_slots_affect_only_physical_neighbors(self):
        for hand, prices in (((SABOTAGE, SPELL, MINION), (2, 3, 3)),
                ((SPELL, SABOTAGE, MINION), (3, 2, 4)), ((SPELL, MINION, SABOTAGE), (2, 4, 2))):
            g = self.game(hand); before = g.snapshot()
            self.assertEqual(self.prices(g), prices); self.assertEqual(g.snapshot(), before)
            self.assertEqual(quote_generated_cost(g.state, g.registry, 1, SPELL).amount, 2)
        self.portable(g)

    def test_adjacent_sources_tax_each_other_and_two_original_sources_stack_on_middle(self):
        g = self.game((SABOTAGE, SPELL, SABOTAGE)); self.assertEqual(self.prices(g), (2, 4, 2))
        g = self.game((SABOTAGE, SABOTAGE, SPELL)); self.assertEqual(self.prices(g), (3, 3, 3))
        self.portable(g)

    def test_all_five_ordinary_hand_card_types_receive_current_position_cost(self):
        for cid in (SPELL, MINION, WEAPON, LOCATION, HERO_CARD):
            g = self.game((SABOTAGE, cid)); self.assertEqual(self.prices(g)[1], g.registry.card(cid).cost+1)
        self.portable(g)

    def test_paid_spell_uses_original_hand_quote_and_reprices_remaining_hand_after_departure(self):
        g = self.game((SABOTAGE, SPELL, MINION)); old_mana = g.state.players[1].mana
        source = self.play(g, SPELL)
        self.assertEqual(g.state.players[1].mana, old_mana-3)
        self.assertEqual((g.state.play_history[-1].source_id, g.state.play_history[-1].cost), (source, 3))
        self.assertEqual(self.prices(g), (2, 4))
        self.assertEqual(quote_accepted_hand(g.state, g.registry, g.state.play_history[-1]).amount, 2)
        self.portable(g)

    def test_paid_minion_uses_same_current_quote_and_ordinary_entry_receipt(self):
        g = self.game((SPELL, SABOTAGE, MINION)); source = self.play(g, MINION)
        self.assertEqual(g.state.players[1].mana, 26); self.assertEqual(g.state.entities[source].zone, Zone.BOARD)
        self.assertEqual(g.state.play_history[-1].cost, 4); self.assertEqual(self.prices(g), (3, 2))
        self.portable(g)

    def test_sabotage_can_be_paid_to_remove_aura_and_has_no_spell_payload(self):
        g = self.game((SPELL, SABOTAGE, MINION)); source = self.play(g, SABOTAGE)
        self.assertEqual(g.state.players[1].mana, 28); self.assertEqual(self.prices(g), (2, 3))
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.cast_history), 1); self.assertTrue(g.state.cast_history[0].completed)
        self.portable(g)

    def test_ordinary_discard_removes_current_provider_without_permanent_neighbor_enchantments(self):
        g = self.game((CMD+'discard', SPELL, SABOTAGE, MINION)); self.play(g, CMD+'discard')
        self.assertEqual(self.prices(g), (2, 3)); self.assertEqual(len(g.state.discard_history), 1)
        self.assertTrue(all(not g.state.entities[i].enchantments for i in g.state.players[1].hand)); self.portable(g)

    def test_current_physical_hand_reordering_moves_aura_without_creating_attachments(self):
        g = self.game((CMD+'left', SPELL, SABOTAGE, MINION)); source = self.ids(g, SABOTAGE)[0]
        marker = tuple(g.state.entities[source].abilities); self.play(g, CMD+'left')
        self.assertEqual(self.prices(g), (2, 3, 3))
        self.assertEqual(tuple(g.state.entities[source].abilities), marker); self.portable(g)

    def test_deck_provider_is_inactive_then_reentry_uses_new_actual_neighbors(self):
        g = self.game((CMD+'deck', SPELL, SABOTAGE, CMD+'hand')); original = self.ids(g, SABOTAGE)[0]
        self.play(g, CMD+'deck'); self.assertEqual(self.prices(g), (2, 0))
        self.assertEqual(g.state.entities[original].zone, Zone.DECK)
        self.play(g, CMD+'hand'); self.assertEqual(self.ids(g, SABOTAGE), (original,))
        self.assertEqual(self.prices(g), (3, 2)); self.portable(g)

    def test_transfer_reprices_new_owner_actual_hand_only(self):
        g = self.game((CMD+'transfer', SPELL, SABOTAGE), enemy_hand=(MINION,)); source = self.ids(g, SABOTAGE)[0]
        self.play(g, CMD+'transfer'); self.assertEqual(self.prices(g), (2,))
        self.assertEqual(self.ids(g, SABOTAGE, 2), (source,)); self.assertEqual(self.prices(g, 2), (4, 2))
        self.portable(g)

    def test_current_and_base_copies_are_independent_new_position_sources(self):
        for mode in ('current', 'base'):
            g = self.game((CMD+'copy_'+mode, SABOTAGE, SPELL)); original = self.ids(g, SABOTAGE)[0]
            self.play(g, CMD+'copy_'+mode); new, = set(self.ids(g, SABOTAGE))-{original}
            self.assertEqual(self.prices(g), (2, 4, 2))
            self.assertTrue(all(a.source_id == new for a in g.state.entities[new].abilities if a.kind == 'cost_aura'))
            self.portable(g)

    def test_transforming_original_hand_source_removes_native_aura(self):
        g = self.game((CMD+'transform', SPELL, SABOTAGE, MINION)); source = self.ids(g, SABOTAGE)[0]
        self.play(g, CMD+'transform'); self.assertEqual(g.state.entities[source].card_id, SPELL)
        self.assertEqual(self.prices(g), (2, 2, 3)); self.portable(g)

    def test_local_set_board_reduction_and_generated_cost_still_share_external_order(self):
        g = self.game((CMD+'discount', SABOTAGE, SPELL), board=(REDUCER,)); self.play(g, CMD+'discount')
        target = self.ids(g, SPELL)[0]
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[target]).amount, 1)
        self.assertEqual(quote_generated_cost(g.state, g.registry, 1, SPELL).amount, 1)
        g = self.game((REDUCER, SABOTAGE, SPELL)); self.assertEqual(self.prices(g), (1, 2, 3))
        self.portable(g)

    def test_spell_and_minion_paid_waits_keep_original_price_after_provider_discard(self):
        for cid in (SPELL, MINION):
            g = self.game((SABOTAGE, cid), board=(WATCH,), mode='wait'); self.play(g, cid)
            self.assertIsNotNone(g.state.pending_choice); paid = g.state.play_history[-1].cost
            self.assertEqual(paid, g.registry.card(cid).cost+1)
            g = self.portable(g); saved = g.snapshot()
            with self.assertRaises(ResolutionError): self.choose(g, 'fail')
            self.assertEqual(g.snapshot(), saved); self.choose(g, 'discard')
            self.assertFalse(self.ids(g, SABOTAGE)); self.assertEqual(g.state.players[1].mana, 30-paid)
            self.assertTrue(g.state.play_history[-1].completed); self.portable(g)

    def test_automatic_original_hand_spell_removal_does_not_fabricate_payment(self):
        g = self.game((CMD+'auto', SPELL, SABOTAGE, MINION)); self.play(g, CMD+'auto')
        self.assertEqual(self.prices(g), (2, 3)); self.assertEqual(g.state.players[1].mana, 30)
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual(g.state.cast_history[-1].card_id, SABOTAGE); self.portable(g)

    def test_insufficient_actual_adjacent_price_is_not_a_legal_action_and_rolls_back(self):
        g = self.game((SABOTAGE, MINION), mana=3); source = self.ids(g, MINION)[0]; saved = g.snapshot()
        self.assertFalse(any(isinstance(a, PlayCard) and a.entity_id == source for a in g.legal_actions()))
        with self.assertRaises(IllegalAction): self.play(g, MINION)
        self.assertEqual(g.snapshot(), saved); self.portable(g)

    def test_typed_scope_native_spell_declaration_and_unsupported_grants_are_strict(self):
        for change in ({'hand_adjacent': 1}, {'relation': 'enemy'}, {'first_per_turn': True},
                {'cost': CostSpec(delta=2)}, {'cost': CostSpec(delta=-1)},
                {'cost': CostSpec(delta=1, card_types=(CardType.SPELL,))}):
            with self.assertRaises(ValueError): replace(AURA, **change)
        with self.assertRaises(ValueError): GrantCostAura(1, AURA)
        r = Registry(P+'invalid')
        with self.assertRaises(ValueError):
            r.register_card(CardDefinition(P+'invalid-source', 'Invalid', CardType.MINION,
                health=3, metadata=META, cost_auras=(AURA,)))

    def test_rehashed_snapshot_rejects_native_scope_rewrite_and_old_schema(self):
        g = self.game((SABOTAGE, SPELL)); source = self.ids(g, SABOTAGE)[0]
        saved = g.snapshot(); row = saved['state']['entities'][str(source)]
        next(a for a in row['abilities'] if a['kind'] == 'cost_aura')['cost_aura']['hand_adjacent'] = False
        with self.assertRaises(SnapshotError) as error: Game.from_snapshot(self.rehash(saved), registry())
        self.assertNotIn('digest mismatch', str(error.exception))
        self.assertGreaterEqual(SNAPSHOT_SCHEMA_VERSION, 410)
        saved = g.snapshot(); saved['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry())

    def test_plain_summon_does_not_give_opponent_a_sabotage(self):
        g = self.game((CMD+'summon',), enemy_hand=(SPELL,)); self.play(g, CMD+'summon')
        self.assertEqual(len(self.ids(g, CARD, zone='board')), 1)
        self.assertFalse(self.ids(g, SABOTAGE, 2)); self.assertEqual(self.prices(g, 2), (2,)); self.portable(g)
