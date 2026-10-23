"""Real Scout copies actual Discover material through ordinary writers."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards.past_discovery_copy_card import SCOUT, BEHAVIOR, load_batch, register_past_discovery_copy_card
from hs_sim.cards.native_discovery_delivery_cards import CARD as VAULT, register_native_discovery_delivery_cards
from hs_sim.cards.kindred_dark_gift_cards import RAPTOR, POOL_ID
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CostSpec,
    EndTurn, Game, PlayerSetup, Rarity, Scenario, TriggerSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.crafted_faces import CraftedMinionBlueprint, CraftedMinionRecipe
from hs_sim.engine.dark_gifts import DARK_GIFTS, public_gifts
from hs_sim.engine.dark_gift_generation import DiscoverDarkGift
from hs_sim.engine.discovered_card_copies import CopyDiscoveredCard
from hs_sim.engine.discovery_delivery import COMPLETED
from hs_sim.engine.effects import AddToHand, ChoiceOption, Destroy, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import ChoicePurpose, SummonQuantitySpec
from hs_sim.engine.pools import (DiscoverFromPool, DiscoveryGiftPool, GenerateFromPool,
    GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.engine.zones import CardReference, ChooseFromZone, DiscardCard, ModifyStoredCost, MoveCard

P = 'k477.'
A, B, C, WATCH, DOUBLE, TEMPLATE = (P+x for x in ('a', 'b', 'c', 'watch', 'double', 'template'))
DISC, DISCOUNT, BOARD, SELF, DECK, GIFT, NO_RECIP, COPY, TAKE, DISCARD, TEMP, GEN, MENU, AUTO, BOOST, KILL, DEAD, FAIL, BACK = (
    P+x for x in ('discover', 'discount', 'board', 'self', 'deck', 'gift', 'no-recipient',
        'copy', 'take', 'discard', 'temp', 'generate', 'menu', 'auto', 'boost', 'kill', 'dead', 'fail', 'back'))
SELF_POOL = P+'self-pool'
CONTEXT = GenerationContext('k477-finite-material-only', 'experimental')
META = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=('beast',), factions=(), subtypes=())
COMPOSED = CraftedMinionRecipe(TEMPLATE, A, B).card_id


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry() if mode in ('full', 'skill', 'burn_gift', 'stale_gift') else defaults()
    if SCOUT not in r.cards: register_past_discovery_copy_card(r)
    if VAULT not in r.cards: register_native_discovery_delivery_cards(r)
    r._version = 'k477-'+mode
    for cid in (A, B, C):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=4, attack=4, health=5, metadata=META))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_card(CardDefinition(TEMPLATE, TEMPLATE, CardType.MINION, attack=1, health=1,
        metadata=replace(META, collectible=False)))
    for cid in (A, B): r.register_crafted_minion_part(cid)
    r.register_crafted_minion_blueprint(CraftedMinionBlueprint(TEMPLATE, 'beast', 'beast'))
    r.register_card(CardDefinition(DOUBLE, DOUBLE, CardType.MINION, health=5,
        metadata=replace(META, collectible=False), summon_quantities=(SummonQuantitySpec(2),)))
    r.register_pool(PoolDefinition(POOL_ID, 'k477-three-explicit-beasts', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid) for cid in (A, B, C)), complete=True))
    r.register_pool(PoolDefinition(SELF_POOL, 'k477-only-real-scout', CONTEXT.target_id,
        CONTEXT.mode, (PoolMember(SCOUT),), complete=True))
    gift_pool = DiscoveryGiftPool(P+'gifts', 'v1', CONTEXT.target_id, CONTEXT.mode,
        tuple(g for g in DARK_GIFTS if g.id in ('EDR_100t', 'EDR_100t3', 'EDR_100t8')), complete=True)
    def discover(c, **kw): return DiscoverFromPool(c.player_id, POOL_ID, source_id=c.source_id, **kw)
    def zone(c, operation, place=Zone.DECK):
        return ChooseFromZone(c.player_id, 3-c.player_id, place, operation=operation,
            distinct='entity', source_id=c.source_id, discovery=True)
    def fail(c): raise ResolutionError('K477 deliberate copy publication failure')
    r.register_behavior(FAIL, fail)
    def back(c):
        ref = CardReference.capture(c.state.entities[c.target_id])
        return (ModifyStoredCost(ref, CostSpec(set_to=0), c.source_id),
            MoveCard(ref, c.player_id, Zone.HAND, source_id=c.source_id))
    r.register_behavior(BACK, back)
    def resurrect(c):
        row = next(d for d in reversed(c.state.death_history) if d.card_id == SCOUT)
        return (RequestChoice(c.player_id, (ChoiceOption('revive', 'Revive',
            (ResurrectMinion(c.player_id, row.id, source_id=c.source_id, cause=SummonCause.capture(c)),),
            card_id=SCOUT),), c.source_id, purpose=ChoicePurpose.CARD_DISCOVERY),)
    scripts = {
        DISC: lambda c: (discover(c),),
        DISCOUNT: lambda c: (discover(c, cost=CostSpec(delta=-1)),),
        BOARD: lambda c: (discover(c, destination='board', cause=SummonCause.capture(c)),),
        SELF: lambda c: (DiscoverFromPool(c.player_id, SELF_POOL, source_id=c.source_id,
            destination='board', cause=SummonCause.capture(c)),),
        DECK: lambda c: (discover(c, destination='deck', position='top', cost=CostSpec(delta=-1)),),
        GIFT: lambda c: (discover(c, gift_pool=gift_pool, cost=CostSpec(delta=-1)),),
        NO_RECIP: lambda c: (RequestChoice(c.player_id, (ChoiceOption('a', 'A', card_id=A),),
            c.source_id, purpose=ChoicePurpose.CARD_DISCOVERY),),
        COPY: lambda c: (zone(c, 'copy_current'),),
        TAKE: lambda c: (zone(c, 'take'),),
        DISCARD: lambda c: (zone(c, 'discard', Zone.HAND),),
        TEMP: lambda c: (discover(c, query=PoolQuery(kinds=(CardType.MINION,), collectible=True),
            temporary_until_turn=c.state.turn),),
        GEN: lambda c: (GenerateFromPool(c.player_id, POOL_ID, source_id=c.source_id),),
        MENU: lambda c: (RequestChoice(c.player_id, (ChoiceOption('a', 'A',
            (AddToHand(c.player_id, A, c.source_id),), card_id=A),), c.source_id),),
        AUTO: lambda c: (CastSpell(c.player_id, DISC, c.source_id),),
        BOOST: lambda c: (BuffStoredCard(CardReference.capture(c.state.entities[
            c.state.players[2].deck[0]]), 3, 2, c.source_id, cost=CostSpec(set_to=0)),),
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        DEAD: resurrect,
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            requires_target=cid == KILL, metadata=replace(META, collectible=False, tribes=())))
    def watch(c):
        e = c.event; original_source = c.state.entities.get(e.source_id)
        is_original = original_source is not None and original_source.card_id in (DISC, DISCOUNT, GIFT, TEMP)
        if mode in ('burn_free', 'burn_gift'):
            if e.kind == 'choice_selected' and is_original:
                return (AddToHand(c.player_id, B, c.source_id),)
            if e.kind == 'card_burned' and is_original:
                old = c.state.entities[c.state.players[c.player_id].hand[0]]
                return (DiscardCard(CardReference.capture(old), c.source_id),)
        if mode == 'forge' and e.kind == COMPLETED:
            return (CopyDiscoveredCard(c.player_id, c.source_id, e),)
        if e.kind == 'card_added_to_hand' and original_source is not None and original_source.card_id == SCOUT:
            if mode == 'late_fail': return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
            if mode == 'copy_wait':
                return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
                    ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
        if mode in ('entry_reentry', 'stale_gift') and e.kind == 'card_added_to_hand' and is_original:
            ref = CardReference.capture(c.state.entities[e.target_id])
            return (MoveCard(ref, c.player_id, Zone.DECK, position='top', source_id=c.source_id),
                InvokeBehavior(BACK, c.source_id, c.player_id, ref.entity_id))
        if mode == 'completion_wait' and e.kind == COMPLETED and is_original:
            ref = CardReference.capture(c.state.entities[e.target_id])
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
                ChoiceOption('zero', 'Reduce original', (ModifyStoredCost(ref, CostSpec(set_to=0), c.source_id),))), c.source_id),)
        if mode == 'entry_wait' and e.kind == 'card_added_to_hand' and is_original:
            scout = next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == SCOUT)
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
                ChoiceOption('kill', 'Remove source', (Destroy(scout, c.source_id),))), c.source_id),)
        return ()
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=5,
        metadata=replace(META, collectible=False, tribes=()), triggers=tuple(TriggerSpec(e, WATCH) for e in
            ('card_added_to_hand', 'card_burned', 'choice_selected', COMPLETED))))
    r.validate(); return r


class PastDiscoveryCopyTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(DISC,), *, board=(SCOUT,), enemy=(), deck=(A, B, C),
             enemy_deck=(A, B, C), enemy_hand=(), mode='normal'):
        self.mode = mode
        if mode not in ('normal', 'full', 'skill'): board = (WATCH, *board)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
            hero_power_card_id='HERO_08bp', mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=enemy_deck,
            hero_power_card_id='HERO_08bp', mana=30, max_mana=30, mana_cap=30)),
            seed=477, generation_context=CONTEXT), fixture(mode))

    def pick(self, g, cid=A):
        self.choose(g, next(o.id for o in g.state.pending_choice.options if o.card_id == cid))

    def copies(self, g):
        return [g.state.entities[e.target_id] for e in g.events if e.kind == 'card_created'
            and e.source_id is not None and g.state.entities[e.source_id].card_id == SCOUT]

    def gift(self, g, gid='EDR_100t8'):
        option = next(o for o in g._frame.options if o.effects[0].selection.gift.id == gid)
        self.choose(g, option.id); return option.card_id

    def test_complete_original_record_primary_faces_and_native_trigger(self):
        data = load_batch(); raw = data['dependencies'][0]['record']
        self.assertEqual((len(data['dependencies']), len(data['official_observations'])), (1, 2))
        for face in data['official_observations']:
            self.assertEqual(batch.sha(face['response_file']), face['response_sha256'])
            batch.check_face(raw, face['face'], face['locale'])
        c = fixture().card(SCOUT)
        self.assertEqual((c.cost, c.attack, c.health, c.metadata.tribes), (1, 1, 2, ('draenei',)))
        self.assertEqual(c.triggers, (TriggerSpec(COMPLETED, BEHAVIOR),))
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_real_scout_play_then_discover_copies_exact_original_and_pays_only_card_cost(self):
        g = self.game((SCOUT, DISC), board=()); source = self.play(g, SCOUT); self.play(g, DISC); self.pick(g)
        self.assertEqual((g.state.players[1].mana, len(self.copies(g))), (29, 1))
        original = g.state.card_discovery_history[0].result.selected[0].card_id
        self.assertEqual((self.copies(g)[0].card_id, self.copies(g)[0].zone), (original, Zone.HAND))
        self.assertEqual(len(g.state.card_discovery_history[0].trigger_sources), 1)
        self.assertEqual(g.state.card_discovery_history[0].trigger_sources[0].source.entity_id, source)

    def test_generated_hand_result_keeps_discovery_discount_on_copy(self):
        g = self.game((DISCOUNT,)); self.play(g, DISCOUNT); self.pick(g)
        self.assertEqual([g.state.entities[i].cost for i in g.state.players[1].hand], [3, 3])
        copy = self.copies(g)[0]; self.assertNotEqual(copy.id, copy.origin_entity_id)
        self.assertEqual(g.state.entities[copy.origin_entity_id].card_id, A)

    def test_native_raptor_kindred_dark_gift_and_copy_share_actual_reduction(self):
        g = self.game(('BAR_024', RAPTOR), mode='full'); self.play(g, 'BAR_024')
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); source = self.play(g, RAPTOR)
        option = g._frame.options[0]
        self.assertEqual(option.effects[0].batch.spec.cost.delta, -1)
        self.choose(g, option.id)
        original = next(g.state.entities[e.target_id] for e in g.events
            if e.kind == 'card_created' and e.source_id == source)
        copy = self.copies(g)[0]
        self.assertEqual((copy.card_id, copy.cost, copy.attack, copy.max_health),
            (original.card_id, original.cost, original.attack, original.max_health))
        self.assertEqual(public_gifts(copy), public_gifts(original))
        self.assertEqual(original.cost, max(0, g.registry.card(original.card_id).cost
            + option.effects[0].selection.gift.cost_delta - 1))
        self.assertTrue(public_gifts(copy)); self.assertNotEqual(copy.id, original.id)
        self.assertEqual(len([e for e in g.events if e.kind == 'dark_gift_granted']), 1)
        self.assertEqual(g.state.kindred_history[-1].condition.matched, True)
        self.choose(g, 'keep'); self.portable(g)

    def test_native_raptor_retry_removes_old_copy_and_preserves_one_payment(self):
        g = self.game(('BAR_024', RAPTOR), mode='full'); self.play(g, 'BAR_024')
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); before = g.state.players[1].mana
        self.play(g, RAPTOR); self.choose(g, g.state.pending_choice.options[0].id)
        old = self.copies(g)[0].id; self.choose(g, 'retry')
        self.choose(g, g.state.pending_choice.options[0].id)
        self.assertNotIn(old, g.state.players[1].hand)
        self.assertEqual(g.state.players[1].mana, before-3); self.portable(g)

    def test_deck_top_gift_retains_full_gift_and_discount_in_hand_copy(self):
        g = self.game((GIFT,), mode='full'); self.play(g, GIFT); cid = self.gift(g)
        original = g.state.entities[g.state.players[1].deck[0]]; copy = self.copies(g)[0]
        self.assertEqual((original.card_id, copy.card_id), (cid, cid))
        self.assertEqual((copy.cost, copy.attack, copy.max_health), (original.cost, original.attack, original.max_health))
        self.assertEqual(public_gifts(copy), public_gifts(original)); self.assertFalse(g.state.draw_history)

    def test_current_opponent_deck_copy_preserves_local_stats_and_price(self):
        g = self.game((BOOST, COPY)); original = g.state.players[2].deck[0]
        self.play(g, BOOST); self.play(g, COPY); self.pick(g)
        cards = [g.state.entities[i] for i in g.state.players[1].hand]
        self.assertEqual([(c.attack, c.max_health, c.cost) for c in cards], [(7, 7, 0), (7, 7, 0)])
        self.assertIn(original, g.state.players[2].deck); self.assertEqual(len({c.id for c in cards}), 2)

    def test_taken_original_card_keeps_original_owner_and_current_material(self):
        g = self.game((BOOST, TAKE)); original = g.state.players[2].deck[0]
        self.play(g, BOOST); self.play(g, TAKE); self.pick(g)
        copy = self.copies(g)[0]
        self.assertIn(original, g.state.players[1].hand)
        self.assertEqual((g.state.entities[original].owner, copy.owner, copy.copy_origin.owner), (2, 1, 2))
        self.assertEqual((copy.attack, copy.max_health, copy.cost), (7, 7, 0))

    def test_composed_physical_card_copy_keeps_exact_ordered_recipe(self):
        g = self.game((COPY,), enemy_deck=(COMPOSED,)); self.play(g, COPY); self.pick(g, COMPOSED)
        copy = self.copies(g)[0]
        self.assertEqual((copy.card_id, copy.components, copy.attack, copy.max_health), (COMPOSED, (A, B), 8, 10))
        self.portable(g)

    def test_original_deck_delivery_remains_in_deck_while_copy_enters_hand(self):
        g = self.game((DECK,)); self.play(g, DECK); self.pick(g)
        original = g.state.entities[g.state.players[1].deck[0]]; copy = self.copies(g)[0]
        self.assertEqual((original.card_id, original.cost, copy.card_id, copy.cost), (A, 3, A, 3))
        self.assertNotEqual(original.id, copy.id); self.assertFalse(g.state.draw_history)

    def test_selection_only_discovery_copies_complete_printed_definition(self):
        g = self.game((NO_RECIP,)); self.play(g, NO_RECIP); self.choose(g, 'a')
        self.assertEqual([(c.card_id, c.attack, c.max_health) for c in self.copies(g)], [(A, 4, 5)])
        self.assertIsNone(self.copies(g)[0].origin_entity_id)

    def test_new_scout_discovered_and_summoned_does_not_copy_itself(self):
        g = self.game((SELF,), board=()); self.play(g, SELF); self.pick(g, SCOUT)
        self.assertFalse(self.copies(g)); self.assertEqual(len(g.state.players[1].board), 1)

    def test_quantity_two_new_scouts_do_not_copy_their_own_discovery(self):
        g = self.game((SELF,), board=(DOUBLE,)); self.play(g, SELF); self.pick(g, SCOUT)
        self.assertEqual(sum(g.state.entities[i].card_id == SCOUT for i in g.state.players[1].board), 2)
        self.assertFalse(self.copies(g))

    def test_one_old_scout_copies_once_despite_two_new_summoned_scouts(self):
        g = self.game((SELF,), board=(SCOUT, DOUBLE)); self.play(g, SELF); self.pick(g, SCOUT)
        self.assertEqual([c.card_id for c in self.copies(g)], [SCOUT])

    def test_two_old_physical_sources_copy_once_each(self):
        g = self.game(board=(SCOUT, SCOUT)); self.play(g, DISC); self.pick(g)
        self.assertEqual(len(self.copies(g)), 2); self.assertEqual(len({c.id for c in self.copies(g)}), 2)

    def test_resurrected_scout_does_not_get_its_own_copy(self):
        g = self.game((KILL, DEAD)); old = g.state.players[1].board[0]
        self.play(g, KILL, old); self.play(g, DEAD); self.choose(g, 'revive')
        self.assertFalse(self.copies(g))

    def test_board_result_uses_original_base_copy_and_keeps_board_entity(self):
        g = self.game((BOARD,)); self.play(g, BOARD); self.pick(g)
        copy = self.copies(g)[0]; original = g.state.entities[copy.origin_entity_id]
        self.assertEqual((original.zone, copy.zone, copy.card_id, copy.attack, copy.max_health),
            (Zone.BOARD, Zone.HAND, A, 4, 5))

    def test_earlier_real_vault_discount_is_visible_to_later_scout_copy(self):
        g = self.game(board=(VAULT, SCOUT)); self.play(g, DISC); self.pick(g)
        self.assertEqual([g.state.entities[i].cost for i in g.state.players[1].hand], [3, 3])

    def test_later_real_vault_discount_does_not_retroactively_change_copy(self):
        g = self.game(board=(SCOUT, VAULT)); self.play(g, DISC); self.pick(g)
        copy = self.copies(g)[0]; original = g.state.entities[copy.origin_entity_id]
        self.assertEqual((original.cost, copy.cost), (3, 4))

    def test_waiting_earlier_observer_updates_current_same_recipient_before_copy(self):
        g = self.game(mode='completion_wait'); self.play(g, DISC); self.pick(g)
        self.assertIsNotNone(g.state.pending_choice); self.assertFalse(self.copies(g))
        restored = self.portable(g); self.choose(g, 'zero'); self.choose(restored, 'zero')
        self.assertEqual(restored.snapshot(), g.snapshot()); self.assertEqual(self.copies(g)[0].cost, 0)

    def test_stale_reentered_recipient_uses_original_recipe_not_new_residency(self):
        g = self.game((DISCOUNT,), mode='entry_reentry'); self.play(g, DISCOUNT); self.pick(g)
        copy = self.copies(g)[0]; original = g.state.entities[copy.origin_entity_id]
        self.assertEqual((original.cost, copy.cost), (0, 3)); self.portable(g)

    def test_full_hand_copy_uses_ordinary_burn_and_no_extra_discovery(self):
        g = self.game((DISC,)+(B,)*9); self.play(g, DISC); self.pick(g)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertEqual(self.copies(g)[0].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.card_discovery_history), 1)

    def test_burned_original_reconstructs_discount_after_earlier_burn_reaction_frees_slot(self):
        g = self.game((DISCOUNT,)+(A,)*9, mode='burn_free'); self.play(g, DISCOUNT); self.pick(g)
        copy = self.copies(g)[0]; original = g.state.entities[copy.origin_entity_id]
        self.assertEqual((original.zone, copy.zone, copy.cost), (Zone.GRAVEYARD, Zone.HAND, 3))
        self.portable(g)

    def test_current_copy_keeps_original_temporary_deadline_without_restart(self):
        g = self.game((TEMP,)); self.play(g, TEMP); self.pick(g)
        copy = self.copies(g)[0]; original = g.state.entities[copy.origin_entity_id]
        self.assertIsNotNone(original.hand_lifetime)
        self.assertEqual(copy.hand_lifetime, original.hand_lifetime)
        g.apply(EndTurn(1))
        self.assertEqual((g.state.entities[original.id].zone, g.state.entities[copy.id].zone),
            (Zone.GRAVEYARD, Zone.GRAVEYARD))

    def test_burned_temporary_result_recovers_same_original_deadline(self):
        g = self.game((TEMP,)+(A,)*9, mode='burn_free'); self.play(g, TEMP); self.pick(g)
        copy = self.copies(g)[0]; original = g.state.entities[copy.origin_entity_id]
        self.assertEqual((original.zone, copy.zone), (Zone.GRAVEYARD, Zone.HAND))
        self.assertIsNotNone(original.hand_lifetime)
        self.assertEqual(copy.hand_lifetime, original.hand_lifetime)
        self.portable(g); g.apply(EndTurn(1)); self.assertEqual(g.state.entities[copy.id].zone, Zone.GRAVEYARD)

    def test_burned_gift_copy_keeps_full_grant_without_another_original_grant_event(self):
        g = self.game((GIFT,)+(A,)*9, mode='burn_gift'); self.play(g, GIFT); self.gift(g, 'EDR_100t')
        copy = self.copies(g)[0]; original = g.state.entities[copy.origin_entity_id]
        self.assertEqual((original.zone, copy.zone, copy.cost), (Zone.GRAVEYARD, Zone.HAND, 3))
        self.assertEqual(public_gifts(copy), public_gifts(original))
        self.assertTrue(public_gifts(copy))
        hand_source = g.state.hand_entries[copy.hand_entry_id-1].source_id
        self.assertEqual(g.state.entities[hand_source].card_id, SCOUT)
        grants = [e for e in g.events if e.kind == 'dark_gift_granted']
        self.assertEqual([e.target_id for e in grants], [original.id]); self.portable(g)

    def test_stale_gift_recipient_rebuilds_original_grant_without_regrant_credit(self):
        g = self.game((GIFT,), mode='stale_gift'); self.play(g, GIFT); self.gift(g, 'EDR_100t')
        copy = self.copies(g)[0]; original = g.state.entities[copy.origin_entity_id]
        self.assertEqual((original.cost, copy.cost), (0, 3))
        self.assertEqual(public_gifts(copy), public_gifts(original))
        self.assertEqual([e.target_id for e in g.events if e.kind == 'dark_gift_granted'], [original.id])
        self.portable(g)

    def test_generate_and_effect_menu_do_not_create_discovery_copies(self):
        g = self.game((GEN, MENU)); self.play(g, GEN); self.play(g, MENU); self.choose(g, 'a')
        self.assertFalse(self.copies(g)); self.assertFalse(g.state.card_discovery_history)

    def test_automatic_spell_discovery_uses_same_copy_path(self):
        g = self.game((AUTO,)); self.play(g, AUTO)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(len(self.copies(g)), 1)

    def test_source_removed_before_completion_does_not_capture_copy(self):
        g = self.game(mode='entry_wait'); self.play(g, DISC); self.pick(g); self.choose(g, 'kill')
        self.assertFalse(self.copies(g))

    def test_wait_after_copy_restores_without_duplicate_creation(self):
        g = self.game(mode='copy_wait'); self.play(g, DISC); self.pick(g); self.assertEqual(len(self.copies(g)), 1)
        restored = self.portable(g); self.choose(g); self.choose(restored)
        self.assertEqual(restored.snapshot(), g.snapshot()); self.assertEqual(len(self.copies(g)), 1)

    def test_late_failure_rolls_back_original_delivery_and_copy(self):
        g = self.game(mode='late_fail'); self.play(g, DISC); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g)
        self.assertEqual(g.snapshot(), before)

    def test_unqualified_observer_cannot_inject_copy_effect(self):
        g = self.game(mode='forge'); self.play(g, DISC); before = g.snapshot()
        with self.assertRaises((ValueError, ResolutionError)): self.pick(g)
        self.assertEqual(g.snapshot(), before)

    def test_hero_power_discovery_is_explicit_unsupported_and_keeps_paid_menu(self):
        g = self.game(('LOE_076',), mode='skill'); self.play(g, 'LOE_076'); before = g.snapshot()
        with self.assertRaises(ResolutionError) as raised: self.choose(g, g.state.pending_choice.options[0].id)
        self.assertIsInstance(raised.exception.__cause__, UnsupportedDefinitionError)
        self.assertEqual(g.snapshot(), before)

    def test_player_observations_do_not_expose_private_copy_recipe(self):
        g = self.game(); self.play(g, DISC); self.pick(g)
        for player in (1, 2):
            visible = json.dumps(g.for_player(player).observe())
            for key in ('CopyDiscoveredCard', 'original_offer', 'trigger_sources', 'next_attachment_id'):
                self.assertNotIn('"'+key+'"', visible)
        self.portable(g)

    def test_old_snapshot_schema_is_rejected(self):
        g = self.game(); saved = g.snapshot(); saved['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, fixture())
