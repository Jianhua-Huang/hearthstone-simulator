"""Original printed-class card plays, using one isolated Lightray adapter."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (BoardMinionCostSpec, CardClass, CardDefinition, CardMetadata, CardType, CastSpell, CostSpec,
    EndTurn, Game, HandCountCostSpec, HeroMissingHealthCostSpec, IllegalAction, InteractableSpec, Keyword,
    MinionDeathCostSpec, PaymentType, PlayerHeroPowerCountCostSpec, PlayerOverloadCostSpec,
    PlayerPlayedClassCostSpec, PlayerSetup, PlayerSpellCountCostSpec, PlayerSpellManaCostSpec, PlayCard,
    Rarity, ResolutionError, Scenario, SelectChoice, SnapshotError, SpellSchool, TriggerSpec, UseHeroPower, played_cards)
from hs_sim.engine.costs import capture_cost_input, capture_generated_quote_fact, capture_quote_fact
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, CopyMinion,
    GainArmor, InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.intrinsic_costs import (validate_intrinsic_stage_fact, validate_intrinsic_origin,
    validate_intrinsic_history_prefix)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.play_history import matches_played_class
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

LIGHT = 'TID_077'
PATH = Path(__file__).resolve().parents[1] / 'data/support/player-played-class-cost-basics.json'
PIN = '2d6fe2d3ff81d7e03baa5e78fce566ca3390e84f118f92de4cb2e387f7aa8dbb'

def evidence():
    support = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support) != PIN: raise ValueError('Played-class complete evidence changed')
    for row in support['records']:
        if canonical_digest(row['data']) != row['data_sha256']: raise ValueError('Played-class raw changed')
    return support['records'][0]['data']

def registry():
    r = opening_registry(); raw = evidence()
    r.register_card(CardDefinition(LIGHT, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], keywords=(Keyword.TAUNT,),
        metadata=metadata(CardClass.PALADIN, tribes=('elemental',)), player_played_class_cost=PlayerPlayedClassCostSpec()))
    r.register_behavior('class.noop', lambda c: ())
    r.register_behavior('class.wait', lambda c: (RequestChoice(c.player_id, (
        ChoiceOption('continue', 'Finish original play', ()),), c.source_id),))
    for cid, card_class, cost, body in (('pal.two', CardClass.PALADIN, 2, 'class.noop'),
            ('pal.free', CardClass.PALADIN, 0, 'class.noop'), ('mage.free', CardClass.MAGE, 0, 'class.noop'),
            ('pal.wait', CardClass.PALADIN, 0, 'class.wait')):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=cost, on_play=body, metadata=metadata(card_class)))
    r.register_card(CardDefinition('class.dual', 'Two printed classes', CardType.SPELL, on_play='class.noop',
        metadata=CardMetadata(True, (CardClass.MAGE, CardClass.PALADIN), Rarity.COMMON)))
    for cid, kind in (('pal.minion', CardType.MINION), ('pal.weapon', CardType.WEAPON), ('pal.location', CardType.LOCATION)):
        r.register_card(CardDefinition(cid, cid, kind, health=2 if kind == CardType.MINION else 0,
            durability=2 if kind != CardType.MINION else 0, attack=1 if kind != CardType.LOCATION else 0,
            on_use='class.noop' if kind == CardType.LOCATION else None, metadata=metadata(CardClass.PALADIN)))
    for cid, card_class in (('pal.hero', CardClass.PALADIN), ('neutral.hero', CardClass.NEUTRAL)):
        r.register_card(CardDefinition(cid, cid, CardType.HERO, health=30, hero_card=True,
            initial_hero_power='mage.power', metadata=metadata(card_class)))
    def held(c): return next(eid for eid in c.state.players[c.player_id].hand if c.state.entities[eid].card_id == LIGHT)
    def first(c): return next(eid for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id == LIGHT)
    def paladin(c): return next(eid for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id == 'pal.minion')
    scripts = {
        'class.acquire': lambda c: (AddToHand(c.player_id, LIGHT),),
        'class.auto': lambda c: (CastSpell(c.player_id, 'pal.free', c.source_id),),
        'class.summon': lambda c: (Summon(c.player_id, 'pal.minion'),),
        'class.local': lambda c: (ModifyCost(held(c), CostSpec(delta=-3)),),
        'class.external': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-2, card_ids=(LIGHT,))),),
        'class.health': lambda c: (AddCostModifier(c.player_id, CostSpec(payment=PaymentType.HEALTH, card_ids=('pal.two',))),),
        'class.copy': lambda c: (CopyMinion(first(c), c.player_id, mode='base'),),
        'class.silence': lambda c: (Silence(first(c)),),
        'class.bounce': lambda c: (ReturnToHand(first(c)),),
        'class.transform': lambda c: (Transform(paladin(c), 'card.1'),),
        'class.return.pal': lambda c: (ReturnToHand(paladin(c)),),
        'class.fail': lambda c: (AddToHand(c.player_id, 'unknown.played.class'),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body); r.register_card(CardDefinition(cid, cid, CardType.SPELL,
            on_play=cid, metadata=metadata()))
    r.register_behavior('class.counter', lambda c: (CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id != c.player_id else ())
    r.register_card(CardDefinition('class.counter', 'Counter a committed spell', CardType.MINION, health=3,
        triggers=(TriggerSpec('card_committed', 'class.counter'),), metadata=metadata()))
    r.register_behavior('class.observe', lambda c: (GainArmor(c.state.players[c.player_id].hero_id,
        sum(matches_played_class(p.played_face, CardClass.PALADIN) for p in played_cards(c.state, c.player_id))),))
    r.register_card(CardDefinition('class.observe', 'Observe original commitment', CardType.MINION, health=3,
        triggers=(TriggerSpec('card_committed', 'class.observe'),), metadata=metadata()))
    def paid_wait(c):
        if c.state.entities[c.event.source_id].card_id != LIGHT: return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Finish paid minion', (AddToHand(c.player_id, LIGHT),)),
            ChoiceOption('fault', 'Fail after suspension', (InvokeBehavior('class.fail', c.source_id, c.player_id),)),
        ), c.source_id),)
    r.register_behavior('class.paid.wait', paid_wait)
    r.register_card(CardDefinition('class.watch', 'Paid completion observer', CardType.MINION, health=3,
        triggers=(TriggerSpec('card_played', 'class.paid.wait'),), metadata=metadata()))
    return r

def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({key: value for key, value in saved.items()
        if key not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved

class PlayerPlayedClassCostTests(unittest.TestCase):
    def game(self, hand=(LIGHT,), *, enemy_hand=(), board=(), enemy_board=(), mana=10, power=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, deck=('card.1',)*3, mana=mana, max_mana=10, hero_power_card_id=power),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy_board, deck=('card.1',)*3, mana=10, max_mana=10)), seed=22), registry())
    def source(self, g, cid=LIGHT, player=1):
        return next(g.state.entities[eid] for eid in g.state.players[player].hand if g.state.entities[eid].card_id == cid)
    def fact(self, g, player=1, cid=LIGHT):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, cid, player)))
    def price(self, g, player=1): return self.fact(g, player).amount
    def play(self, g, cid):
        eid = self.source(g, cid, g.state.active_player).id; g.apply(PlayCard(g.state.active_player, eid)); return eid
    def choose(self, g, option='continue'):
        c = g.state.pending_choice; g.apply(SelectChoice(c.player_id, c.id, (option,)))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); restored = Game.from_snapshot(saved, registry())
        self.assertEqual(restored.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for player in (1, 2): self.assertEqual(restored.observe(player), g.observe(player))
        return saved
    def one(self, *, extras=(), board=()):
        g = self.game((LIGHT, 'pal.free', *extras), board=board); self.play(g, 'pal.free'); return g

    def test_complete_single_raw_and_adapter_are_pinned(self):
        raw = evidence(); card = registry().card(LIGHT)
        self.assertEqual((raw['id'], raw['cost'], raw['attack'], raw['health'], raw['tags']['CLASS']), (LIGHT, 9, 5, 5, 5))
        self.assertEqual(raw['text_en'], "<b>Taunt</b>\nCosts (1) less for each Paladin card you've played this game.")
        self.assertEqual((card.cost, card.attack, card.health, card.keywords), (9, 5, 5, (Keyword.TAUNT,)))

    def test_finite_declared_class_and_only_one_quantity_are_required(self):
        card = registry().card(LIGHT)
        for spec in (dict(card_class='PALADIN'), dict(card_class=True), dict(card_class=CardClass.NEUTRAL), dict(profile_id='unknown')):
            with self.subTest(spec=spec), self.assertRaises(ValueError): PlayerPlayedClassCostSpec(**spec)
        for values in (dict(kind=CardType.SPELL), dict(interactable=InteractableSpec('class.noop')),
                dict(board_minion_cost=BoardMinionCostSpec()), dict(hand_count_cost=HandCountCostSpec()),
                dict(hero_missing_health_cost=HeroMissingHealthCostSpec()), dict(player_spell_count_cost=PlayerSpellCountCostSpec()),
                dict(player_hero_power_count_cost=PlayerHeroPowerCountCostSpec()), dict(player_spell_mana_cost=PlayerSpellManaCostSpec()),
                dict(minion_death_cost=MinionDeathCostSpec()), dict(player_overload_cost=PlayerOverloadCostSpec())):
            r = opening_registry()
            with self.subTest(values=values), self.assertRaises(ValueError): r.register_card(replace(card, id='class.invalid', **values))

    def test_empty_history_keeps_full_price_and_zero_selection(self):
        g = self.game(); f = self.fact(g).intrinsic.player_played_class
        self.assertEqual((f.rows, f.selected_ids, f.quantity, self.price(g)), ((), (), 0, 9))

    def test_own_paladin_plays_exclude_neutral_and_other_classes(self):
        g = self.one(extras=('coin', 'mage.free')); self.play(g, 'coin'); self.play(g, 'mage.free')
        f = self.fact(g).intrinsic.player_played_class
        self.assertEqual((len(f.rows), f.selected_ids, f.quantity, self.price(g)), (3, (1,), 1, 8))

    def test_all_original_hand_card_types_count_once(self):
        g = self.game((LIGHT, 'pal.free', 'pal.minion', 'pal.weapon', 'pal.location', 'pal.hero'))
        for cid in ('pal.free', 'pal.minion', 'pal.weapon', 'pal.location', 'pal.hero'): self.play(g, cid)
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_played_class.selected_ids), (4, (1, 2, 3, 4, 5)))
        self.portable(g)

    def test_printed_dual_class_card_contributes_one_physical_play(self):
        g = self.game((LIGHT, 'class.dual')); self.play(g, 'class.dual')
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_played_class.quantity), (8, 1))

    def test_current_hero_class_does_not_reclassify_original_plays(self):
        g = self.game((LIGHT, 'mage.free', 'pal.hero', 'neutral.hero')); self.play(g, 'mage.free'); self.play(g, 'pal.hero')
        self.assertEqual(self.price(g), 8); self.play(g, 'neutral.hero'); self.assertEqual(self.price(g), 8)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].card_id, 'neutral.hero')

    def test_two_same_face_physical_plays_each_count(self):
        g = self.game((LIGHT, 'pal.free', 'pal.free')); self.play(g, 'pal.free'); self.play(g, 'pal.free')
        f = self.fact(g).intrinsic.player_played_class
        self.assertEqual((f.selected_ids, self.price(g)), ((1, 2), 7)); self.assertNotEqual(f.rows[0].face.source_id, f.rows[1].face.source_id)

    def test_same_physical_minion_returned_and_replayed_counts_again(self):
        g = self.game((LIGHT, 'pal.minion', 'class.return.pal')); original = self.play(g, 'pal.minion')
        self.play(g, 'class.return.pal'); self.assertEqual(self.play(g, 'pal.minion'), original)
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_played_class.selected_ids), (7, (1, 3)))

    def test_acquisition_after_play_reuses_earlier_history(self):
        g = self.game(('pal.free', 'class.acquire')); self.play(g, 'pal.free'); self.play(g, 'class.acquire')
        self.assertEqual(self.price(g), 8)

    def test_actual_payer_histories_are_independent_across_turns(self):
        g = self.game((LIGHT, 'pal.free'), enemy_hand=(LIGHT, 'pal.free')); self.play(g, 'pal.free')
        self.assertEqual((self.price(g), self.price(g, 2)), (8, 9)); g.apply(EndTurn(1)); self.play(g, 'pal.free')
        self.assertEqual((self.price(g), self.price(g, 2)), (8, 8)); g.apply(EndTurn(2)); self.assertEqual(self.price(g), 8)

    def test_automatic_cast_summon_and_hero_power_are_not_hand_plays(self):
        g = self.game((LIGHT, 'class.auto', 'class.summon'), power='mage.power')
        self.play(g, 'class.auto'); self.play(g, 'class.summon'); g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        self.assertEqual((self.price(g), len(g.state.play_history)), (9, 2)); self.assertEqual(len(g.state.cast_history), 3)

    def test_countered_paid_paladin_card_remains_an_original_play(self):
        g = self.game((LIGHT, 'pal.two'), enemy_board=('class.counter',)); self.play(g, 'pal.two')
        self.assertTrue(g.state.play_history[0].countered); self.assertEqual((self.price(g), g.state.players[1].mana), (8, 8))
        self.portable(g)

    def test_committed_card_is_visible_before_its_completion(self):
        g = self.game((LIGHT, 'pal.wait'), board=('class.observe',)); self.play(g, 'pal.wait')
        self.assertIsNotNone(g.state.pending_choice); self.assertFalse(g.state.play_history[0].completed)
        self.assertEqual((self.price(g), g.state.entities[g.state.players[1].hero_id].armor), (8, 1))
        self.portable(g); self.choose(g); self.assertEqual(self.price(g), 8)

    def test_alternative_resource_payment_still_counts_a_card(self):
        g = self.game((LIGHT, 'class.health', 'pal.two')); self.play(g, 'class.health'); self.play(g, 'pal.two')
        self.assertEqual((self.price(g), g.state.players[1].mana, g.state.entities[g.state.players[1].hero_id].health), (8, 10, 28))

    def test_zero_cost_original_cards_and_zero_floor(self):
        g = self.game((LIGHT, *('pal.free',)*9))
        for _ in range(9): self.play(g, 'pal.free')
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_played_class.quantity), (0, 9))
        self.play(g, LIGHT); self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (0, 10))

    def test_new_source_is_excluded_from_its_own_payment_then_counts_for_next(self):
        g = self.game((LIGHT, LIGHT)); self.play(g, LIGHT)
        paid = g.state.play_history[0].submitted_cost.quote.intrinsic.player_played_class
        self.assertEqual((paid.quantity, paid.rows, g.state.play_history[0].cost, self.price(g)), (0, (), 9, 8))

    def test_original_class_survives_current_entity_transformation(self):
        g = self.game((LIGHT, 'pal.minion', 'class.transform')); eid = self.play(g, 'pal.minion'); self.play(g, 'class.transform')
        self.assertEqual((g.state.entities[eid].card_id, self.price(g)), ('card.1', 8))
        self.assertTrue(matches_played_class(g.state.play_history[0].played_face, CardClass.PALADIN, registry=g.registry))

    def test_public_class_filter_is_pure_and_requires_pinned_known_class(self):
        g = self.one(extras=('mage.free',)); self.play(g, 'mage.free'); saved = g.snapshot()
        self.assertEqual([p.id for p in played_cards(g.state, 1, registry=g.registry, card_class=CardClass.PALADIN)], [1])
        self.assertEqual([p.id for p in played_cards(g.state, 1, registry=g.registry, card_class=CardClass.MAGE)], [2])
        for args in (dict(card_class=CardClass.PALADIN), dict(registry=g.registry, card_class='PALADIN'), dict(registry=g.registry, card_class=CardClass.NEUTRAL)):
            with self.subTest(args=args), self.assertRaises(ValueError): played_cards(g.state, 1, **args)
        self.assertEqual(g.snapshot(), saved)

    def test_unknown_original_metadata_cannot_be_skipped_as_non_candidate(self):
        g = self.one(); f = self.fact(g).intrinsic.player_played_class; row = f.rows[0]
        with self.assertRaises(ValueError): replace(f, rows=(replace(row, face=replace(row.face, metadata=None)),))

    def test_pure_physical_generated_and_player_prices_share_original_quantity(self):
        g = self.one(); saved = g.snapshot(); physical = self.fact(g)
        generated = capture_generated_quote_fact(g.state, g.registry, 1, LIGHT)
        self.assertEqual((physical.amount, generated.amount), (8, 8)); self.assertEqual(physical.intrinsic, generated.intrinsic)
        card = next(c for c in g.observe(1)['players'][0]['hand'] if c['card_id'] == LIGHT)
        self.assertEqual(card['cost']['amount'], 8); self.assertEqual(g.snapshot(), saved)

    def test_local_external_layers_and_payment_use_same_class_price(self):
        g = self.one(extras=('class.local', 'class.external')); self.play(g, 'class.local'); self.play(g, 'class.external')
        f = self.fact(g); self.assertEqual((f.intrinsic.amount, f.local_amount, f.amount), (8, 5, 3))
        self.play(g, LIGHT); self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (3, 7)); self.portable(g)

    def test_player_legal_action_pays_the_displayed_class_price(self):
        g = self.one(); port = g.for_player(1); dto = port.legal_actions()
        card = next(c for c in g.observe(1)['players'][0]['hand'] if c['card_id'] == LIGHT)
        action = next(a for a in dto['actions'] if a.get('card') == card['ref'])
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (8, 2))

    def test_insufficient_payment_and_failed_play_preserve_history(self):
        g = self.game((LIGHT, 'class.fail'), mana=1); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, LIGHT)
        self.assertEqual(g.snapshot(), before)
        with self.assertRaises(ResolutionError): self.play(g, 'class.fail')
        self.assertEqual(g.snapshot(), before)

    def test_paid_choice_restore_later_play_preserves_old_amount(self):
        g = self.game((LIGHT, 'pal.free'), board=('class.watch',)); self.play(g, LIGHT); self.portable(g)
        original = g.state.play_history[0].submitted_cost.quote.intrinsic
        self.assertEqual(original.player_played_class.quantity, 0)
        self.choose(g); self.play(g, 'pal.free'); self.assertEqual((self.price(g), g.state.play_history[0].cost), (7, 9))
        validate_intrinsic_history_prefix(original, g.state, g.registry); self.portable(g)

    def test_exception_after_paid_choice_rolls_back_all_original_play_history(self):
        g = self.game((LIGHT,), board=('class.watch',)); self.play(g, LIGHT); self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)

    def test_printed_copy_silence_and_bounce_requery_player_history(self):
        g = self.game((LIGHT, 'class.copy', 'class.silence', 'class.bounce')); self.play(g, LIGHT)
        self.play(g, 'class.copy'); self.play(g, 'class.silence'); self.play(g, 'class.bounce')
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_played_class.quantity), (8, 1)); self.portable(g)

    def test_original_prefix_survives_actual_turn_handoff(self):
        g = self.one(); self.play(g, LIGHT); original = g.state.play_history[-1].submitted_cost.quote.intrinsic
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); validate_intrinsic_history_prefix(original, g.state, g.registry); self.portable(g)

    def test_rows_are_immutable_and_facts_require_exact_complete_window(self):
        g = self.one(); stage = self.fact(g).intrinsic; f = stage.player_played_class; row = f.rows[0]
        with self.assertRaises(FrozenInstanceError): row.turn = 2
        for changes in (dict(quantity=True), dict(selected_ids=(True,)), dict(selected_ids=()), dict(rows=()), dict(rows=list(f.rows)),
                dict(play_history_length=2), dict(next_entity_id=row.face.source_id), dict(turn=2), dict(action=f.action+1)):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(stage, player_played_class=replace(f, **changes))
        with self.assertRaises(ValueError): replace(self.fact(g), quote_input=replace(self.fact(g).quote_input, source_id=f.next_entity_id))

    def test_pinned_complete_face_cannot_be_reclassified_even_if_quantity_matches(self):
        g = self.one(); stage = self.fact(g).intrinsic; f = stage.player_played_class
        wrong = replace(f.rows[0], face=replace(f.rows[0].face, metadata=metadata(CardClass.PALADIN, collectible=False)))
        changed = replace(stage, player_played_class=replace(f, rows=(wrong,)))
        with self.assertRaises(ValueError): validate_intrinsic_stage_fact(g.registry, changed)
        with self.assertRaises(ValueError): validate_intrinsic_history_prefix(changed, g.state, g.registry)

    def test_full_origin_rejects_later_roots_while_old_prefix_remains_valid(self):
        g = self.one(extras=('pal.free',)); stage = self.fact(g).intrinsic; validate_intrinsic_origin(stage, g.state, g.registry)
        self.play(g, 'pal.free'); validate_intrinsic_history_prefix(stage, g.state, g.registry)
        with self.assertRaises(ValueError): validate_intrinsic_origin(stage, g.state, g.registry)

    def test_rehashed_paid_wire_cannot_drop_or_rewrite_original_class_facts(self):
        g = self.one(); self.play(g, LIGHT); saved = self.portable(g)
        for mode in ('leaf', 'extra', 'rows', 'selected', 'quantity', 'class', 'source', 'owner', 'metadata', 'action', 'bool'):
            bad = deepcopy(saved); stage = bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']; f = stage['player_played_class']
            if mode == 'leaf': del stage['player_played_class']
            elif mode == 'extra': f['invented'] = 1
            elif mode == 'rows': f['rows'] = []
            elif mode == 'selected': f['selected_ids'] = []
            elif mode == 'quantity': f['quantity'] = 2
            elif mode == 'class': f['spec']['card_class'] = 'MAGE'
            elif mode == 'source': f['rows'][0]['face']['source_id'] += 1
            elif mode == 'owner': f['rows'][0]['face']['owner_turn_id'] += 1
            elif mode == 'metadata': f['rows'][0]['face']['metadata']['collectible'] = False
            elif mode == 'action': f['rows'][0]['action'] += 1
            else: f['rows'][0]['face']['player_id'] = True
            with self.subTest(mode=mode), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())

    def test_player_views_keep_internal_price_prefix_and_enemy_hand_private(self):
        g = self.game((LIGHT, 'pal.free'), enemy_hand=('pal.two',)); self.play(g, 'pal.free')
        for player in (1, 2):
            text = json.dumps(g.observe(player))
            for private in ('player_played_class', 'selected_ids', 'submitted_cost', 'payment_state'): self.assertNotIn(private, text)
        self.assertNotIn('pal.two', json.dumps(g.observe(1))); self.portable(g)

    def test_current_wire_has_explicit_default_leaf_and_rejects_previous_schema(self):
        g = self.game(('card.1',)); self.assertIsNone(self.fact(g, cid='card.1').intrinsic.player_played_class)
        self.play(g, 'card.1'); saved = self.portable(g)
        self.assertEqual((g.ruleset.id, g.mechanics.version, saved['schema_version']), ('prototype-v302', CORE_EFFECTS_VERSION, 265))
        for mode in ('schema', 'leaf'):
            bad = deepcopy(saved)
            if mode == 'schema': bad['schema_version'] = 178
            else: del bad['state']['play_history'][0]['submitted_cost']['quote']['intrinsic']['player_played_class']
            with self.subTest(mode=mode), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())

if __name__ == '__main__': unittest.main()
