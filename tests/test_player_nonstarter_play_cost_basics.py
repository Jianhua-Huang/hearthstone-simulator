"""Original physical starting decks and the necessary Mana Giant price profile."""
from copy import deepcopy
from dataclasses import asdict, dataclass, FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CastSpell, CostQuoteFact, CostSpec, DeckSpec,
    EndTurn, Game, IllegalAction, MatchSetup, OpeningHook, PaymentType, PlayerPlayedClassCostSpec,
    PlayerSetup, PlayCard, Rarity, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec,
    UseHeroPower, Zone, played_outside_starting_deck, starting_deck_identity)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input, capture_generated_quote_fact, capture_quote_fact
from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChangeManaCrystals, ChoiceOption,
    Effect, GainArmor, InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand, Silence, Summon)
from hs_sim.engine.intrinsic_costs import (validate_intrinsic_history_prefix, validate_intrinsic_origin,
    validate_intrinsic_stage_fact, validate_definition_intrinsics)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import _intrinsic_stage_from_dict, canonical_hash
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE = 'DRG_109'
PROFILE = 'cost.player-played-outside-starting-deck-v1'
SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/player-nonstarter-play-cost-basics.json'
PIN = 'b79085b1e2a0a88adfc73b0d19f317c3e5e4532ecddd7e10cb0a193bbdb6e47f'
BASE = tuple(f'origin.{i}' for i in range(29)) + ('origin.boot',)


def evidence():
    packet = json.loads(SUPPORT.read_bytes())
    if canonical_digest(packet) != PIN or len(packet['records']) != 1:
        raise ValueError('Complete nonstarter price evidence changed')
    row = packet['records'][0]
    if row['id'] != NATIVE or canonical_digest(row['data']) != row['data_sha256']:
        raise ValueError('Original Mana Giant row changed')
    return row['data']


@dataclass(frozen=True)
class SavedQuote(Effect):
    value: CostQuoteFact

    def __post_init__(self):
        if type(self.value) is not CostQuoteFact:
            raise ValueError('Expected one complete original quote')
        self.value.__post_init__()


def mechanics():
    def saved(r, work):
        validate_intrinsic_history_prefix(work.value.intrinsic, r.state, r.registry)
        return (GainArmor(r.state.players[work.value.quote_input.player_id].hero_id,
            work.value.intrinsic.player_played_class.quantity),)
    return default_mechanics('b73-nonstarter-price-typed-test').register(SavedQuote, saved)


def registry(extra=(), *, original_native=False, watch=None):
    r = opening_registry(); raw = evidence()
    r.register_behavior('origin.noop', lambda c: ())
    for cid in BASE[:-1]:
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=2, metadata=metadata()))
    r.register_card(CardDefinition(NATIVE, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], metadata=metadata(CardClass.MAGE,
            rarity=Rarity.EPIC, tribes=('elemental',)),
        player_played_class_cost=PlayerPlayedClassCostSpec(None, PROFILE)))
    for cid, kind in (('new.free', CardType.SPELL), ('new.minion', CardType.MINION),
                      ('new.weapon', CardType.WEAPON), ('new.location', CardType.LOCATION), ('new.hero', CardType.HERO)):
        r.register_card(CardDefinition(cid, cid, kind, attack=1 if kind in (CardType.MINION, CardType.WEAPON) else 0,
            health=30 if kind == CardType.HERO else 2 if kind == CardType.MINION else 0,
            durability=2 if kind in (CardType.WEAPON, CardType.LOCATION) else 0,
            on_play='origin.noop' if kind == CardType.SPELL else None,
            on_use='origin.noop' if kind == CardType.LOCATION else None,
            hero_card=kind == CardType.HERO, initial_hero_power='mage.power' if kind == CardType.HERO else None,
            metadata=metadata()))

    def hand(c, cid):
        return next(c.state.entities[e] for e in c.state.players[c.player_id].hand
                    if c.state.entities[e].card_id == cid)

    def body(c, cid=NATIVE):
        return next(e for e in c.state.players[c.player_id].board if c.state.entities[e].card_id == cid)

    def original(c):
        return next(c.state.entities[e] for e in c.state.players[c.player_id].hand
                    if e in c.state.opening.original_entities[c.player_id - 1] and c.state.entities[e].card_id != NATIVE)

    scripts = {
        'origin.create.same': lambda c: (AddToHand(c.player_id, original(c).card_id),),
        'origin.copy.same': lambda c: (CopyCard(CardReference.capture(original(c)), c.player_id),),
        'origin.shuffle.same': lambda c: (AddToDeck(c.player_id, original(c).card_id, 'top'),),
        'origin.draw.top': lambda c: (MoveCard(CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]]),
            c.player_id, Zone.HAND, draw=True),),
        'origin.transform': lambda c: (TransformCapturedMinion(CardReference.capture(original(c)), 'new.minion'),),
        'origin.steal': lambda c: (MoveCard(CardReference.capture(c.state.entities[next(e for e in c.state.players[3-c.player_id].hand
            if e in c.state.opening.original_entities[2-c.player_id])]), c.player_id, Zone.HAND),),
        'origin.native.copy.other': lambda c: (CopyCard(CardReference.capture(hand(c, NATIVE)), 3-c.player_id, mode='base'),),
        'origin.native.transform': lambda c: (TransformCapturedMinion(CardReference.capture(hand(c, NATIVE)), 'new.minion'),),
        'origin.native.silence': lambda c: (Silence(body(c)),),
        'origin.native.bounce': lambda c: (ReturnToHand(body(c)),),
        'origin.original.bounce': lambda c: (ReturnToHand(next(e for e in c.state.players[c.player_id].board
            if e in c.state.opening.original_entities[c.player_id-1])),),
        'origin.layers': lambda c: (ModifyCost(hand(c, NATIVE).id, CostSpec(set_to=6)),
            AddCostModifier(c.player_id, CostSpec(delta=-2, card_ids=(NATIVE,)))),
        'origin.health': lambda c: (AddCostModifier(c.player_id, CostSpec(payment=PaymentType.HEALTH, card_ids=(NATIVE,))),),
        'origin.acquire': lambda c: (AddToHand(c.player_id, NATIVE),),
        'origin.repeat': lambda c: (AddToHand(c.player_id, 'origin.repeat'),),
        'origin.auto': lambda c: (CastSpell(c.player_id, 'new.free', c.source_id), Summon(c.player_id, 'new.minion')),
        'origin.enable.counter': lambda c: (Summon(3-c.player_id, 'origin.counter'),),
        'origin.fail': lambda c: (AddToHand(c.player_id, 'unknown.nonstarter.body'),),
    }
    for cid, fn in scripts.items():
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata()))
    r.register_behavior('origin.counter', lambda c: (CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id != c.player_id else ())
    r.register_card(CardDefinition('origin.counter', 'Existing spell counter observer', CardType.MINION,
        health=3, triggers=(TriggerSpec('card_committed', 'origin.counter'),), metadata=metadata()))

    def bootstrap(c):
        work = [ChangeManaCrystals(c.player_id, 9, filled=True)]
        if c.player_id == 1:
            if original_native:
                source = next(c.state.entities[e] for e in c.state.opening.original_entities[0]
                              if c.state.entities[e].card_id == NATIVE)
                if source.zone == Zone.DECK:
                    work.append(MoveCard(CardReference.capture(source), 1, Zone.HAND))
            else:
                work.append(AddToHand(1, NATIVE))
            work.extend(AddToHand(1, cid) for cid in extra)
            if watch is not None:
                work.append(Summon(1, 'origin.watch'))
        return tuple(work)
    r.register_behavior('origin.bootstrap', bootstrap)
    r.register_card(CardDefinition('origin.boot', 'Original opening diagnostic', CardType.MINION, health=2,
        opening_hooks=(OpeningHook('after_mulligan', 'origin.bootstrap'),), metadata=metadata()))
    if watch is not None:
        def pause(c):
            if c.state.entities[c.event.source_id].card_id != NATIVE:
                return ()
            quote = c.state.play_history[-1].submitted_cost.quote
            return (RequestChoice(c.player_id, (
                ChoiceOption('continue', 'Retain original price and acquire future copy',
                    (AddToHand(c.player_id, NATIVE), SavedQuote(quote))),
                ChoiceOption('fault', 'Rollback to the original waiting boundary',
                    (InvokeBehavior('origin.fail', c.source_id, c.player_id),)),
            ), c.source_id),)
        r.register_behavior('origin.pause', pause)
        r.register_card(CardDefinition('origin.watch', 'Original paid boundary watcher', CardType.MINION,
            health=3, triggers=(TriggerSpec(watch, 'origin.pause'),), metadata=metadata()))
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({key: value for key, value in saved.items()
        if key not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class PlayerNonstarterPlayCostTests(unittest.TestCase):
    def game(self, extra=(), *, original_native=False, watch=None, finish=True):
        r = registry(extra, original_native=original_native, watch=watch)
        own = BASE if not original_native else BASE[:-2] + (NATIVE, BASE[-1])
        decks = (DeckSpec('mage.hero', 'mage.power', CardClass.MAGE, own),
                 DeckSpec('warrior.hero', 'warrior.power', CardClass.WARRIOR, BASE))
        g = Game.from_decks(MatchSetup(decks, policy(r), 'coin', 73, 1), r,
            mechanics=mechanics() if watch else None)
        if finish:
            while g.state.pending_choice is not None:
                q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, ()))
        return g

    def source(self, g, cid=NATIVE, player=1):
        return next(g.state.entities[e] for e in g.state.players[player].hand if g.state.entities[e].card_id == cid)

    def play(self, g, cid=NATIVE, *, eid=None):
        player = g.state.active_player
        source = self.source(g, cid, player).id if eid is None else eid
        g.apply(PlayCard(player, source)); return source

    def original(self, g, player=1):
        return next(g.state.entities[e] for e in g.state.players[player].hand
                    if e in g.state.opening.original_entities[player-1] and g.state.entities[e].card_id != NATIVE)

    def fact(self, g, player=1, cid=NATIVE):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, cid, player)))

    def price(self, g, player=1):
        return self.fact(g, player).amount

    def check(self, g, extra=(), *, original_native=False, watch=None):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, registry(extra, original_native=original_native, watch=watch),
            mechanics=mechanics() if watch else None)
        self.assertEqual(restored.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(extra, original_native=original_native, watch=watch),
            mechanics=mechanics() if watch else None).snapshot(), saved)
        return restored

    def choose(self, g, option='continue'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (option,)))

    def test_complete_native_raw_pin8_8_8_mage_epic_elemental(self):
        raw = evidence(); card = registry().card(NATIVE)
        self.assertEqual((raw['dbf_id'], card.cost, card.attack, card.health), (54909, 8, 8, 8))
        self.assertEqual((card.metadata.classes, card.metadata.rarity, card.metadata.tribes),
            ((CardClass.MAGE,), Rarity.EPIC, ('elemental',)))
        self.assertEqual((card.on_play, card.battlecry, card.deathrattle, card.keywords), (None, None, None, ()))

    def test_full30_slot_original_physical_inventory_is_read_only_and_survives_mulligan(self):
        g = self.game(finish=False); before = g.snapshot(); ids, cards = starting_deck_identity(g.state)
        self.assertEqual(tuple(map(len, ids)), (30, 30)); self.assertEqual(cards, (BASE, BASE))
        self.assertEqual(g.snapshot(), before)
        q = g.state.pending_choice; replaced = q.options[0].entity_id
        g.apply(SelectChoice(q.player_id, q.id, (str(replaced),)))
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, ()))
        self.assertEqual(starting_deck_identity(g.state), (ids, cards)); self.assertEqual(self.price(g), 8)
        self.check(g)

    def test_original_hand_play_does_not_reduce_and_complete_unselected_row_is_retained(self):
        g = self.game(); source = self.original(g); self.play(g, eid=source.id)
        fact = self.fact(g).intrinsic.player_played_class
        self.assertEqual((fact.quantity, fact.selected_ids, len(fact.rows), self.price(g)), (0, (), 1, 8))
        self.assertEqual(fact.rows[0].face.source_id, source.id); self.check(g)

    def test_generated_same_card_id_counts_while_original_name_is_in_starting_deck(self):
        extra = ('origin.create.same',); g = self.game(extra); original = self.original(g)
        self.play(g, extra[0]); copy = next(g.state.entities[e] for e in g.state.players[1].hand
            if g.state.entities[e].card_id == original.card_id and e not in g.state.opening.original_entities[0])
        self.play(g, eid=copy.id)
        self.assertEqual((copy.card_id in BASE, self.price(g)), (True, 6))
        self.assertEqual(tuple(r.id for r in played_outside_starting_deck(g.state, 1)), (1, 2)); self.check(g, extra)

    def test_existing_copy_operation_uses_new_allocation_not_copy_origin_entity(self):
        extra = ('origin.copy.same',); g = self.game(extra); source = self.original(g); self.play(g, extra[0])
        copy = next(g.state.entities[e] for e in g.state.players[1].hand if e not in g.state.opening.original_entities[0]
                    and g.state.entities[e].origin_entity_id == source.id)
        self.play(g, eid=copy.id); self.assertEqual(self.price(g), 6); self.check(g, extra)

    def test_generated_then_shuffled_and_drawn_same_face_remains_nonstarter(self):
        extra = ('origin.shuffle.same', 'origin.draw.top'); g = self.game(extra)
        self.play(g, extra[0]); generated = g.state.players[1].deck[0]
        self.assertNotIn(generated, g.state.opening.original_entities[0]); self.play(g, extra[1])
        self.play(g, eid=generated); self.assertEqual(self.price(g), 5); self.check(g, extra)

    def test_original_physical_card_transformed_to_other_face_keeps_original_membership(self):
        extra = ('origin.transform',); g = self.game(extra); original = self.original(g); self.play(g, extra[0])
        self.assertEqual(g.state.entities[original.id].card_id, 'new.minion')
        self.play(g, eid=original.id); self.assertEqual(self.price(g), 7); self.check(g, extra)

    def test_original_minion_bounce_and_replay_do_not_turn_it_into_generated_card(self):
        extra = ('origin.original.bounce',); g = self.game(extra); original = self.original(g)
        self.play(g, eid=original.id); self.play(g, extra[0]); self.play(g, eid=original.id)
        self.assertEqual((len(played_cards(g.state, 1)), self.price(g)), (3, 7)); self.check(g, extra)

    def test_other_players_original_physical_card_is_nonstarter_for_actual_payer(self):
        extra = ('origin.steal',); g = self.game(extra); source = self.original(g, 2); self.play(g, extra[0])
        self.assertEqual((g.state.entities[source.id].owner, g.state.entities[source.id].controller), (2, 1))
        self.play(g, eid=source.id); self.assertEqual(self.price(g), 6); self.check(g, extra)

    def test_old_plays_before_acquisition_and_real_turns_are_preserved(self):
        extra = ('new.free', 'origin.acquire'); g = self.game(extra); self.play(g, 'new.free')
        first = self.source(g).id; self.play(g, 'origin.acquire')
        new = next(e for e in g.state.players[1].hand if e != first and g.state.entities[e].card_id == NATIVE)
        self.assertEqual(g.quote_cost(new).amount, 6)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.assertEqual(self.price(g), 6); self.check(g, extra)

    def test_two_payers_keep_complete_other_player_rows_and_independent_quantities(self):
        extra = ('new.free', 'origin.native.copy.other'); g = self.game(extra)
        self.play(g, 'new.free'); self.play(g, 'origin.native.copy.other'); self.assertEqual(self.price(g), 6)
        g.apply(EndTurn(1)); self.assertEqual(self.price(g, 2), 8); self.play(g, 'coin')
        self.assertEqual((self.price(g, 1), self.price(g, 2)), (6, 7))
        f = self.fact(g, 1).intrinsic.player_played_class
        self.assertEqual((len(f.rows), f.selected_ids), (3, (1, 2))); self.check(g, extra)

    def test_all_five_paid_hand_types_count_and_hero_power_does_not(self):
        extra = ('new.free', 'new.minion', 'new.weapon', 'new.location', 'new.hero'); g = self.game(extra)
        for cid in extra: self.play(g, cid)
        self.assertEqual(self.price(g), 3)
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id)); self.assertEqual(self.price(g), 3); self.check(g, extra)

    def test_zero_price_does_not_truncate_original_quantity(self):
        extra = ('origin.repeat',); g = self.game(extra)
        for _ in range(10): self.play(g, 'origin.repeat')
        f = self.fact(g).intrinsic.player_played_class
        self.assertEqual((f.quantity, len(f.rows), self.price(g)), (10, 10, 0)); self.check(g, extra)

    def test_quotation_is_pure_and_generated_stage_uses_same_original_inventory(self):
        g = self.game(('new.free',)); self.play(g, 'new.free'); before = g.snapshot()
        ordinary = self.fact(g); generated = capture_generated_quote_fact(g.state, g.registry, 1, NATIVE)
        self.assertEqual(generated.intrinsic.player_played_class, ordinary.intrinsic.player_played_class)
        self.assertEqual((ordinary.amount, generated.amount), (7, 7)); self.assertEqual(g.snapshot(), before)

    def test_generated_cost_and_minimum_are_after_original_nonstarter_quantity(self):
        g = self.game(('new.free',)); self.play(g, 'new.free')
        quote = capture_generated_quote_fact(g.state, g.registry, 1, NATIVE, cost=CostSpec(set_to=5), minimum_cost=6)
        self.assertEqual((quote.intrinsic.player_played_class.after, quote.local_amount, quote.amount), (7, 5, 6))

    def test_existing_local_then_external_layers_and_once_payment(self):
        extra = ('origin.layers',); g = self.game(extra); self.play(g, extra[0])
        f = self.fact(g); self.assertEqual((f.intrinsic.amount, f.local_amount, f.amount), (7, 6, 4))
        self.play(g); record = g.state.play_history[-1]
        self.assertEqual((record.cost, record.mana_before-record.mana_after), (4, 4)); self.check(g, extra)

    def test_real_player_command_plays_native8_8_at_original_pre_self_count_price(self):
        extra = ('new.free',); g = self.game(extra); self.play(g, 'new.free')
        port = g.for_player(1); dto = port.legal_actions()
        ref = next(c['ref'] for c in g.observe(1)['players'][0]['hand'] if c['card_id'] == NATIVE)
        action = next(a for a in dto['actions'] if a.get('card') == ref)
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        source = next(g.state.entities[e] for e in g.state.players[1].board if g.state.entities[e].card_id == NATIVE)
        self.assertEqual((source.attack, source.health, g.state.players[1].mana), (8, 8, 3))
        self.assertEqual(g.state.play_history[-1].submitted_cost.quote.intrinsic.player_played_class.quantity, 1)
        self.assertEqual(len(played_outside_starting_deck(g.state, 1)), 2); self.check(g, extra)

    def test_original_native_itself_does_not_add_nonstarter_unit(self):
        g = self.game(original_native=True); source = self.source(g)
        self.assertIn(source.id, g.state.opening.original_entities[0]); self.play(g)
        self.assertEqual(len(played_outside_starting_deck(g.state, 1)), 0)
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (8, 2)); self.check(g, original_native=True)

    def test_alternative_health_payment_uses_same_original_unit_count(self):
        extra = ('origin.health',); g = self.game(extra); self.play(g, extra[0]); self.play(g)
        self.assertEqual((g.state.players[1].mana, g.state.entities[g.state.players[1].hero_id].health), (10, 23))
        self.assertEqual((len(played_outside_starting_deck(g.state, 1)), g.state.play_history[-1].payment), (2, PaymentType.HEALTH))
        self.check(g, extra)

    def test_failed_root_rolls_back_original_history_price_and_allocation(self):
        extra = ('origin.fail',); g = self.game(extra); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, extra[0])
        self.assertEqual(g.snapshot(), before); self.assertEqual(self.price(g), 8); self.check(g, extra)

    def test_generated_paid_countered_spell_is_one_committed_nonstarter_root(self):
        extra = ('origin.enable.counter', 'new.free'); g = self.game(extra)
        self.play(g, extra[0]); self.play(g, 'new.free')
        self.assertTrue(g.state.play_history[-1].countered)
        self.assertEqual((self.price(g), len(played_outside_starting_deck(g.state, 1))), (6, 2)); self.check(g, extra)

    def test_effect_cast_and_summon_are_not_additional_paid_hand_roots(self):
        extra = ('origin.auto',); g = self.game(extra); self.play(g, extra[0])
        self.assertEqual((len(g.state.play_history), len(g.state.cast_history), self.price(g)), (1, 2, 7)); self.check(g, extra)

    def test_committed_wait_keeps_original_cost_and_typed_inventory_after_resume(self):
        extra = ('new.free',); g = self.game(extra, watch='card_committed'); self.play(g, 'new.free'); self.play(g)
        self.assertIsNotNone(g.state.pending_choice); record = g.state.play_history[-1]
        self.assertEqual((record.cost, record.submitted_cost.quote.intrinsic.player_played_class.quantity), (7, 1))
        restored = self.check(g, extra, watch='card_committed')
        self.choose(g); self.choose(restored); self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual((self.price(g), g.state.entities[g.state.players[1].hero_id].armor), (6, 1))
        self.check(g, extra, watch='card_committed')

    def test_completed_wait_keeps_original_quote_after_self_count_changes(self):
        extra = ('new.free',); g = self.game(extra, watch='card_played'); self.play(g, 'new.free'); self.play(g)
        self.assertTrue(g.state.play_history[-1].completed); restored = self.check(g, extra, watch='card_played')
        self.choose(g); self.choose(restored); self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual((self.price(g), g.state.players[1].mana), (6, 3)); self.check(g, extra, watch='card_played')

    def test_waiting_choice_failure_preserves_original_paid_root_and_pending_choice(self):
        extra = ('new.free',); g = self.game(extra, watch='card_committed'); self.play(g, 'new.free'); self.play(g)
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before); self.check(g, extra, watch='card_committed')

    def test_native_silence_and_bounce_restore_face_with_whole_player_history(self):
        extra = ('origin.native.silence', 'origin.native.bounce'); g = self.game(extra); self.play(g)
        self.play(g, extra[0]); self.play(g, extra[1]); self.assertEqual(self.price(g), 5); self.check(g, extra)

    def test_transform_native_to_plain_face_removes_cost_formula_not_history(self):
        extra = ('origin.native.transform',); g = self.game(extra); source = self.source(g).id; self.play(g, extra[0])
        self.assertEqual((g.state.entities[source].card_id, g.quote_cost(source).amount), ('new.minion', 0))
        self.assertEqual(len(played_outside_starting_deck(g.state, 1)), 1); self.check(g, extra)

    def test_compact_prefix_allows_later_original_and_generated_plays_without_repricing(self):
        extra = ('new.free', 'origin.repeat'); g = self.game(extra); self.play(g, 'new.free'); old = self.fact(g).intrinsic
        self.play(g, eid=self.original(g).id); self.play(g, 'origin.repeat')
        validate_intrinsic_history_prefix(old, g.state, g.registry)
        self.assertEqual((old.amount, self.price(g)), (7, 6))
        with self.assertRaises(ValueError): validate_intrinsic_origin(old, g.state, g.registry)

    def test_equal_price_shortened_other_payer_original_inventory_is_rejected(self):
        g = self.game(); old = self.fact(g).intrinsic; f = old.player_played_class
        changed = replace(f, starting_entities=(f.starting_entities[0], f.starting_entities[1][:-1]),
            starting_cards=(f.starting_cards[0], f.starting_cards[1][:-1]))
        self.assertEqual(changed.quantity, f.quantity)
        with self.assertRaises(ValueError): validate_intrinsic_origin(replace(old, player_played_class=changed), g.state, g.registry)
        with self.assertRaises(ValueError): validate_intrinsic_history_prefix(replace(old, player_played_class=changed), g.state, g.registry)

    def test_original_inventory_type_allocation_order_and_cross_player_duplicates_are_strict(self):
        f = self.fact(self.game()).intrinsic.player_played_class
        with self.assertRaises(FrozenInstanceError): f.starting_entities = None
        for ids, cards in ((None, f.starting_cards), (list(f.starting_entities), f.starting_cards),
                ((f.starting_entities[0][::-1], f.starting_entities[1]), f.starting_cards),
                ((f.starting_entities[0], f.starting_entities[0]), f.starting_cards),
                ((f.starting_entities[0][:-1] + (f.next_entity_id,), f.starting_entities[1]), f.starting_cards),
                (f.starting_entities, (f.starting_cards[0][:-1], f.starting_cards[1]))):
            with self.subTest(ids=ids), self.assertRaises(ValueError): replace(f, starting_entities=ids, starting_cards=cards)

    def test_finite_profile_requires_explicit_none_class_and_rejects_other_shapes(self):
        for value in (CardClass.MAGE, CardClass.NEUTRAL, True, 'mage'):
            with self.subTest(value=value), self.assertRaises(ValueError): PlayerPlayedClassCostSpec(value, PROFILE)
        with self.assertRaises(ValueError): PlayerPlayedClassCostSpec(None, 'cost.nonstarter-turn-guessed')
        native = registry().card(NATIVE)
        for changes in (dict(kind=CardType.SPELL), dict(choice_only=True), dict(player_played_class_cost=True)):
            with self.subTest(changes=changes), self.assertRaises(ValueError): validate_definition_intrinsics(replace(native, **changes))

    def test_unknown_scenario_origin_does_not_guess_from_card_names_or_generation_context(self):
        r = registry(); g = Game.from_scenario(Scenario((PlayerSetup('mage.hero', hand=('new.free',)),
            PlayerSetup('warrior.hero')), seed=73), r)
        with self.assertRaises(UnsupportedDefinitionError): starting_deck_identity(g.state)
        with self.assertRaises(UnsupportedDefinitionError): played_outside_starting_deck(g.state, 1)
        with self.assertRaises(UnsupportedDefinitionError): capture_generated_quote_fact(g.state, g.registry, 1, NATIVE)
        self.assertEqual(len(g.state.play_history), 0)

    def test_queries_validate_player_and_before_bounds_and_do_not_mutate_state(self):
        g = self.game(('new.free',)); self.play(g, 'new.free'); before = g.snapshot()
        self.assertEqual(played_outside_starting_deck(g.state, 1, before_id=1), ())
        self.assertEqual(tuple(row.id for row in played_outside_starting_deck(g.state, 1, before_id=2)), (1,))
        for player, bound in ((True, None), (3, None), (1, True), (1, 0)):
            with self.subTest(player=player, bound=bound), self.assertRaises(ValueError):
                played_outside_starting_deck(g.state, player, before_id=bound)
        self.assertEqual(g.snapshot(), before)

    def test_dictionary_and_typed_quote_preserve_exact_nested_starting_pairs(self):
        g = self.game(('new.free',)); self.play(g, 'new.free'); stage = self.fact(g).intrinsic
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(stage)), stage)
        self.assertEqual(_intrinsic_stage_from_dict(json.loads(json.dumps(asdict(stage)))), stage)
        wire = codec.encode(stage); del wire['fields']['player_played_class']['fields']['starting_entities']
        with self.assertRaises(ValueError): codec.decode(wire)

    def test_old_class_and_turn_profiles_require_explicit_null_origin_operands(self):
        import test_player_played_class_cost_basics as old
        g = Game.from_scenario(Scenario((PlayerSetup('mage.hero', hand=(old.LIGHT,)),
            PlayerSetup('warrior.hero'))), old.registry())
        stage = capture_quote_fact(g.state, g.registry, capture_cost_input(g.state.entities[g.state.players[1].hand[0]])).intrinsic
        f = stage.player_played_class
        self.assertIsNone(f.starting_entities); self.assertIsNone(f.starting_cards)
        raw = json.loads(json.dumps(asdict(stage))); del raw['player_played_class']['starting_cards']
        with self.assertRaises(ValueError): _intrinsic_stage_from_dict(raw)
        with self.assertRaises(ValueError): replace(f, starting_entities=((), ()), starting_cards=((), ()))

    def test_rehashed_paid_wire_rejects_missing_shortened_reordered_or_forged_origin(self):
        extra = ('new.free',); g = self.game(extra); self.play(g, 'new.free'); self.play(g); saved = g.snapshot()
        for mode in ('missing', 'null', 'short', 'reverse', 'bool', 'unknown', 'selection', 'extra'):
            bad = deepcopy(saved); f = bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['player_played_class']
            if mode == 'missing': del f['starting_entities']
            elif mode == 'null': f['starting_cards'] = None
            elif mode == 'short': f['starting_entities'][1].pop(); f['starting_cards'][1].pop()
            elif mode == 'reverse': f['starting_entities'][0].reverse()
            elif mode == 'bool': f['starting_entities'][0][0] = True
            elif mode == 'unknown': f['starting_cards'][1][0] = 'unknown.original.starting.face'
            elif mode == 'selection': f['selected_ids'] = []
            else: f['invented'] = 1
            with self.subTest(mode=mode), self.assertRaises(SnapshotError) as error:
                Game.from_snapshot(rehash(bad), registry(extra))
            self.assertNotIn('digest mismatch', str(error.exception).lower())

    def test_player_final_price_visible_but_both_private_starting_decks_and_proof_are_hidden(self):
        extra = ('new.free',); g = self.game(extra); self.play(g, 'new.free'); before = g.snapshot()
        native = next(row for row in g.observe(1)['players'][0]['hand'] if row['card_id'] == NATIVE)
        self.assertEqual(native['cost'], {'amount': 7, 'payment': 'mana'})
        for player in (1, 2):
            text = json.dumps(g.observe(player)) + json.dumps(g.player_events(player)) + json.dumps(g.for_player(player).legal_actions())
            for field in ('starting_entities', 'starting_cards', 'original_entities', 'original_deck', 'submitted_cost', 'player_played_class'):
                self.assertNotIn('"' + field + '"', text)
        self.assertNotIn(NATIVE, json.dumps(g.observe(2))); self.assertEqual(g.snapshot(), before)

    def test_schema211_layout_and_old_current_rules_or_mechanics_are_rejected(self):
        g = self.game(); saved = g.snapshot()
        self.assertEqual((saved['schema_version'], g.ruleset.id, g.mechanics.version), (266, 'prototype-v302', CORE_EFFECTS_VERSION))
        for version in (1, 210, 217, True, 216.0):
            bad = deepcopy(saved); bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())
        for key, value in (('ruleset', 'prototype-v227'), ('mechanics', 'core-effects-v221')):
            bad = deepcopy(saved)
            if key == 'ruleset': bad['ruleset']['id'] = value
            else: bad['mechanics_version']['version'] = value
            with self.subTest(key=key), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())
        self.check(g)


if __name__ == '__main__':
    unittest.main()
