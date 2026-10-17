"""Storage Scuffle's real price, original discovery facts and paid boundaries."""
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_discovery_cost_cards import CARD, BODY, CONDITION, HISTORY, load_batch, register_native_discovery_cost_cards
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game, IllegalAction,
    IntrinsicCostSpec, PaymentType, PlayCard, PlayerSetup, Rarity, Registry, Scenario,
    SelectChoice, SnapshotError, SpellSchool, Zone)
from hs_sim.engine.card_discoveries import (capture_turn_match, discovered_cards, validate_turn_match,
    validate_turn_prefix, record_from_dict)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input, capture_quote_fact, capture_generated_quote_fact
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Effect, GainArmor,
    InvokeBehavior, ModifyCost, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.intrinsic_costs import (validate_definition_intrinsics, validate_intrinsic_origin,
    validate_intrinsic_stage_fact, validate_intrinsic_history_prefix, validate_generated_quote_fact)
from hs_sim.engine.model import CardDiscoveredTurnMatch, CostQuoteFact, CostSpec, Keyword, RewindSpec, TriggerSpec
from hs_sim.engine.pools import (DiscoverFromPool, GenerateFromPool, GenerationContext, PoolCard,
    PoolDefinition, PoolMember, PoolQuery)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import canonical_hash, _intrinsic_stage_from_dict
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from tools.card_batch import check_face

P = 'k171.'
HERO, A, B, C, TARGET, POWER, WATCH = (P + n for n in ('hero', 'a', 'b', 'c', 'target', 'power', 'watch'))
DISC, GEN, MENU, FOREIGN, NOOP, ACQUIRE, COPY, TRANSFER, LAYERS, HEALTH, HOLD, AUTO, RETRY = (P + n for n in
    ('discover', 'generate', 'menu', 'foreign', 'noop', 'acquire', 'copy', 'transfer', 'layers', 'health', 'hold', 'auto', 'retry'))
POOL = 'constructed.cards'
CONTEXT = GenerationContext('k171-native-price-fixture', 'experimental')
META = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=2, max_cost=2)


@dataclass(frozen=True)
class SavedQuote(Effect):
    fact: CostQuoteFact

    def __post_init__(self):
        if type(self.fact) is not CostQuoteFact:
            raise ValueError('The fixture retains the complete original physical quote')
        self.fact.__post_init__()


def mechanics():
    def use_saved(r, effect):
        validate_intrinsic_history_prefix(effect.fact.intrinsic, r.state, r.registry)
        return (GainArmor(effect.fact.quote_input.player_id, effect.fact.amount),)
    return default_mechanics().register(SavedQuote, use_saved)


def native_entity(c):
    return next(c.state.entities[i] for i in c.state.players[c.player_id].hand
        if c.state.entities[i].card_id == CARD)


@lru_cache(maxsize=None)
def registry(role='writer'):
    if role not in ('writer', 'reader'):
        raise ValueError('Independent immutable fixture role required')
    r = Registry('k171-small-native-price')
    register_native_discovery_cost_cards(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=30,
        metadata=replace(META, collectible=False, classes=(CardClass.MAGE,))))
    for cid in (A, B, C):
        card = CardDefinition(cid, cid, CardType.MINION, cost=2, attack=1, health=2, metadata=META)
        r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    r.register_pool(PoolDefinition(POOL, 'v1', CONTEXT.target_id, CONTEXT.mode,
        tuple(PoolMember(cid) for cid in (A, B, C)), complete=True))
    r.register_card(CardDefinition(TARGET, TARGET, CardType.MINION, attack=1, health=12,
        metadata=replace(META, collectible=False)))
    r.register_card(CardDefinition(POWER, POWER, CardType.MINION, health=4, spell_damage=2,
        metadata=replace(META, collectible=False)))
    def discovery(c):
        return DiscoverFromPool(c.player_id, POOL, QUERY, source_id=c.source_id)
    def fail(c):
        raise ResolutionError('Fixture failure after original quote')
    r.register_behavior(P+'fail', fail)
    def hold(c):
        fact = capture_quote_fact(c.state, r, capture_cost_input(native_entity(c)))
        return (RequestChoice(c.player_id, (
            ChoiceOption('accept', 'Accept original quote', (SavedQuote(fact),)),
            ChoiceOption('discover', 'Discover before using saved quote', (discovery(c), SavedQuote(fact))),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
    scripts = {
        DISC: lambda c: (discovery(c),),
        GEN: lambda c: (GenerateFromPool(c.player_id, POOL, QUERY, source_id=c.source_id),),
        MENU: lambda c: (RequestChoice(c.player_id, (ChoiceOption('plain', 'Plain menu',
            (AddToHand(c.player_id, A, c.source_id),), card_id=A),), c.source_id),),
        FOREIGN: lambda c: (CastSpell(3-c.player_id, DISC, c.source_id),),
        NOOP: lambda c: (),
        ACQUIRE: lambda c: (AddToHand(c.player_id, CARD, c.source_id),),
        COPY: lambda c: (CopyCard(CardReference.capture(native_entity(c)), c.player_id, source_id=c.source_id),),
        TRANSFER: lambda c: (MoveCard(CardReference.capture(native_entity(c)), 3-c.player_id, Zone.HAND, source_id=c.source_id),),
        LAYERS: lambda c: (ModifyCost(native_entity(c).id, CostSpec(delta=-1), c.source_id),
            AddCostModifier(c.player_id, CostSpec(delta=2, card_ids=(CARD,)), source_id=c.source_id)),
        HEALTH: lambda c: (AddCostModifier(c.player_id, CostSpec(payment=PaymentType.HEALTH, card_ids=(CARD,)), source_id=c.source_id),),
        HOLD: hold,
        AUTO: lambda c: (CastSpell(c.player_id, CARD, c.source_id),),
    }
    for cid, fn in scripts.items():
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            metadata=replace(META, collectible=False)))
    r.register_card(CardDefinition(RETRY, RETRY, CardType.SPELL, on_play=DISC,
        rewind=RewindSpec(1), keywords=(Keyword.REWIND,), metadata=replace(META, collectible=False)))
    r.register_behavior(P+'paid', lambda c: (discovery(c),)
        if c.event.player_id == c.player_id and c.state.entities[c.event.source_id].card_id == CARD else ())
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=4,
        triggers=(TriggerSpec('card_committed', P+'paid'),), metadata=replace(META, collectible=False)))
    r.validate(); r.freeze()
    return r


def game(hand=(CARD,), *, pid=1, board=(), other_hand=()):
    setups = tuple(PlayerSetup(HERO, hand=hand if p == pid else other_hand, deck=(A, B, C, A, B, C),
        board=board if p == pid else (TARGET,), mana=30, max_mana=30, mana_cap=30) for p in (1, 2))
    return Game.from_scenario(Scenario(setups, active_player=pid, seed=171, generation_context=CONTEXT),
        registry(), mechanics=mechanics())


def source(g, pid=1):
    return next(g.state.entities[i] for i in g.state.players[pid].hand if g.state.entities[i].card_id == CARD)


def fact(g, pid=1):
    return capture_quote_fact(g.state, g.registry, capture_cost_input(source(g, pid)))


def play(g, cid, *, target=None, pid=None, entity=None):
    pid = g.state.active_player if pid is None else pid
    e = g.state.entities[entity] if entity is not None else next(g.state.entities[i]
        for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
    g.apply(PlayCard(pid, e.id, target_id=target,
        position=len(g.state.players[pid].board) if e.kind == CardType.MINION else None))
    return e.id


def choose(g, option=None):
    q = g.state.pending_choice
    selected = next(o for o in q.options if option is None or o.id == option or o.card_id == option)
    g.apply(SelectChoice(q.player_id, q.id, (selected.id,)))


def target(g, pid=1):
    return next(i for i in g.state.players[3-pid].board if g.state.entities[i].card_id == TARGET)


def portable(test, g):
    reader = registry('reader') if g.registry is not registry('reader') else registry('writer')
    test.assertIsNot(reader, g.registry)
    saved = json.loads(json.dumps(g.snapshot()))
    other = Game.from_snapshot(saved, reader, mechanics=mechanics())
    test.assertEqual(other.snapshot(), saved)
    test.assertEqual(g.clone().snapshot(), saved)
    test.assertEqual(replay(build_replay(g), reader, mechanics=mechanics()).snapshot(), saved)
    return other


def ready(*extra, pid=1, board=()):
    g = game((DISC, CARD, *extra), pid=pid, board=board)
    play(g, DISC); choose(g, A)
    return g


class DiscoveryTurnCostTests(unittest.TestCase):
    def test_full_real_source_two_primary_faces_and_complete_native_declaration(self):
        data = load_batch(); raw = data['cards'][0]['record']; card = registry().card(CARD)
        self.assertEqual((card.cost, card.spell_school, card.metadata.classes, card.on_play),
            (3, SpellSchool.ARCANE, (CardClass.MAGE,), BODY))
        self.assertEqual(len(data['official_observations']), 2)
        for o in data['official_observations']: check_face(raw, o['face'], o['locale'])
        self.assertEqual(card.intrinsic_costs, (IntrinsicCostSpec(set_to=0, condition=CONDITION, history_profile_id=HISTORY),))

    def test_finite_spec_rejects_wrong_profile_amount_kind_and_mixed_intrinsic_formula(self):
        for kwargs in (dict(set_to=1), dict(set_to=0, delta=-1), dict(set_to=0, minimum=1),
                dict(set_to=0, history_profile_id='invented')):
            with self.assertRaises(ValueError):
                IntrinsicCostSpec(**dict(dict(condition=CONDITION, history_profile_id=HISTORY), **kwargs))
        rule = registry().card(CARD).intrinsic_costs
        for make in (lambda: CardDefinition(P+'invalid', 'invalid', CardType.MINION, health=1, intrinsic_costs=rule),
                lambda: replace(registry().card(CARD), intrinsic_costs=rule*2)):
            with self.assertRaises(ValueError): validate_definition_intrinsics(make())

    def test_initial_false_pays_printed_three_and_deals_real_three_to_minion(self):
        g = game(); q = fact(g)
        self.assertEqual((q.amount, q.intrinsic.condition_facts[0].records, q.intrinsic.condition_facts[0].matched), (3, (), False))
        victim = target(g); play(g, CARD, target=victim)
        self.assertEqual((g.state.players[1].mana, g.state.entities[victim].health, g.state.play_history[-1].cost), (27, 9, 3))
        portable(self, g)

    def test_actual_discovery_changes_quote_and_real_payment_to_zero_without_consumption(self):
        g = ready(); q = fact(g); condition = q.intrinsic.condition_facts[0]
        self.assertIs(type(condition), CardDiscoveredTurnMatch)
        self.assertEqual((q.amount, condition.matched, condition.records), (0, True, tuple(g.state.card_discovery_history)))
        play(g, CARD, target=target(g))
        self.assertEqual((g.state.players[1].mana, g.state.play_history[-1].cost), (30, 0))
        self.assertEqual(len(discovered_cards(g.state, 1)), 1); portable(self, g)

    def test_pending_discovery_not_selected_has_false_price_and_recovery_preserves_it(self):
        g = game((DISC, CARD)); play(g, DISC)
        self.assertEqual(fact(g).amount, 3); g = portable(self, g)
        choose(g); self.assertEqual(fact(g).amount, 0)

    def test_generation_and_card_menu_do_not_satisfy_discovery_price(self):
        for before in (GEN, MENU):
            with self.subTest(before=before):
                g = game((before, CARD)); play(g, before)
                if g.state.pending_choice is not None: choose(g)
                self.assertEqual(fact(g).amount, 3)

    def test_other_actor_discovery_is_preserved_in_false_prefix_and_own_quote_is_zero(self):
        g = game((FOREIGN, CARD)); play(g, FOREIGN)
        own = fact(g); other = capture_generated_quote_fact(g.state, g.registry, 2, CARD)
        self.assertEqual((own.amount, len(own.intrinsic.condition_facts[0].records), other.amount), (3, 1, 0))
        self.assertEqual(own.intrinsic.condition_facts[0].records[0].result.choice.player_id, 2)
        portable(self, g)

    def test_second_player_and_next_global_turn_use_their_actual_quote_window(self):
        g = ready(pid=2); self.assertEqual(fact(g, 2).amount, 0)
        play(g, CARD, pid=2, target=target(g, 2)); portable(self, g)
        g = ready(NOOP); original = fact(g).intrinsic
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(fact(g).amount, 3)
        validate_intrinsic_history_prefix(original, g.state, g.registry)
        portable(self, g)

    def test_later_acquisition_copy_and_transfer_use_current_controller_facts(self):
        g = game((DISC, ACQUIRE, COPY, TRANSFER)); play(g, DISC); choose(g)
        play(g, ACQUIRE); play(g, COPY)
        originals = [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id == CARD]
        self.assertEqual(len(originals), 2)
        self.assertTrue(all(capture_quote_fact(g.state, g.registry, capture_cost_input(e)).amount == 0 for e in originals))
        play(g, TRANSFER)
        self.assertEqual(fact(g, 2).amount, 3); self.assertEqual(fact(g, 1).amount, 0)
        portable(self, g)

    def test_intrinsic_zero_preserves_original_local_then_external_cost_layers(self):
        g = game((LAYERS, DISC, CARD)); play(g, LAYERS)
        self.assertEqual(fact(g).amount, 4)
        play(g, DISC); choose(g)
        q = fact(g)
        self.assertEqual((q.intrinsic.amount, q.local_amount, q.amount), (0, 0, 2))
        generated = capture_generated_quote_fact(g.state, g.registry, 1, CARD, cost=CostSpec(set_to=4))
        self.assertEqual(generated.amount, 6)
        validate_generated_quote_fact(g.registry, generated)
        play(g, CARD, target=target(g)); self.assertEqual(g.state.players[1].mana, 28)
        portable(self, g)

    def test_zero_and_nonzero_health_payment_use_original_payment_account(self):
        for discovered in (False, True):
            with self.subTest(discovered=discovered):
                g = ready(HEALTH) if discovered else game((HEALTH, CARD))
                play(g, HEALTH); q = fact(g)
                self.assertEqual(q.payment, PaymentType.HEALTH)
                play(g, CARD, target=target(g))
                self.assertEqual(g.state.players[1].mana, 30)
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 30 if discovered else 27)
                portable(self, g)

    def test_paid_false_receipt_does_not_reprice_after_commit_trigger_discovers(self):
        g = game(board=(WATCH,)); victim = target(g); eid = play(g, CARD, target=victim)
        self.assertEqual(g.state.players[1].mana, 27)
        self.assertIsNotNone(g.state.pending_choice); g = portable(self, g)
        choose(g)
        row = next(p for p in g.state.play_history if p.source_id == eid)
        self.assertEqual((row.cost, g.state.players[1].mana, row.submitted_cost.quote.intrinsic.condition_facts[0].matched), (3, 27, False))
        self.assertTrue(capture_turn_match(g.state, 1).matched)
        self.assertEqual(g.state.entities[victim].health, 9); portable(self, g)

    def test_complete_quote_survives_nested_discovery_before_frozen_effect_continues(self):
        g = game((HOLD, CARD)); play(g, HOLD); g = portable(self, g)
        choose(g, 'discover'); self.assertEqual(fact(g).amount, 3); g = portable(self, g)
        choose(g)
        self.assertEqual(fact(g).amount, 0)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 3)
        portable(self, g)

    def test_full_prefix_and_original_stage_reject_changed_bool_actor_missing_row_and_selected_option(self):
        g = ready(NOOP); play(g, NOOP)
        stage = fact(g).intrinsic; match = stage.condition_facts[0]
        validate_intrinsic_origin(stage, g.state, g.registry)
        with self.assertRaises(ValueError): replace(match, matched=False)
        with self.assertRaises(ValueError): validate_turn_prefix(replace(match, records=(), matched=False), g.state, g.registry)
        with self.assertRaises(ValueError): replace(stage, condition_facts=(replace(match, player_id=2, matched=False),))
        bad = deepcopy(asdict(stage)); bad['condition_facts'][0]['records'][0]['result']['selected_ids'] = ['missing']
        with self.assertRaises(ValueError): _intrinsic_stage_from_dict(json.loads(json.dumps(bad)))
        old = stage
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        validate_intrinsic_history_prefix(old, g.state, g.registry)
        with self.assertRaises(ValueError): validate_intrinsic_origin(old, g.state, g.registry)

    def test_match_record_and_full_stage_roundtrip_use_shared_strict_typed_codec(self):
        g = ready(); stage = fact(g).intrinsic
        codec = FrameCodec(g.mechanics, g.registry)
        self.assertEqual(codec.decode(codec.encode(stage)), stage)
        self.assertEqual(_intrinsic_stage_from_dict(json.loads(json.dumps(asdict(stage)))), stage)
        match = stage.condition_facts[0]; validate_turn_match(match, g.registry)
        self.assertEqual(record_from_dict(json.loads(json.dumps(asdict(match.records[0])))), match.records[0])

    def test_rewind_restores_discovery_condition_before_retry_and_new_result_enables_it(self):
        g = game((RETRY, CARD)); play(g, RETRY); choose(g)
        self.assertEqual(fact(g).amount, 0); g = portable(self, g)
        choose(g, 'retry'); self.assertEqual(fact(g).amount, 3); g = portable(self, g)
        choose(g); self.assertEqual(fact(g).amount, 0); portable(self, g)

    def test_required_minion_target_and_spell_damage_are_independent_of_zero_price(self):
        g = ready(board=(POWER,)); before = g.snapshot()
        with self.assertRaises(IllegalAction): play(g, CARD, target=g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(), before)
        victim = target(g); play(g, CARD, target=victim)
        self.assertEqual((g.state.entities[victim].health, g.state.players[1].mana), (7, 30))

    def test_automatic_spell_has_real_damage_without_synthetic_hand_payment(self):
        g = ready(AUTO); victim = target(g); play(g, AUTO)
        self.assertEqual((g.state.entities[victim].health, g.state.players[1].mana), (9, 30))
        self.assertFalse(any(p.card_id == CARD for p in g.state.play_history))
        portable(self, g)

    def test_failed_choice_keeps_original_quote_waiting_and_every_private_field(self):
        g = ready(HOLD); play(g, HOLD); saved = g.snapshot()
        with self.assertRaises(ResolutionError): choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved); portable(self, g)

    def test_price_fact_and_offer_receipts_stay_out_of_player_information(self):
        g = ready(HOLD); play(g, HOLD)
        for pid in (1, 2):
            visible = json.dumps((g.observe(pid), g.player_events(pid)))
            for private in ('CardDiscoveredTurnMatch', 'condition_facts', 'selection_event', 'card_discovery_history'):
                self.assertNotIn(private, visible)
        portable(self, g)
