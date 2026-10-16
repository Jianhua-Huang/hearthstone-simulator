"""All-game actual overloaded crystals and one finite Snowfury price."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (BoardMinionCostSpec, CardClass, CardDefinition, CardType, CostSpec, DamageKind,
    EndTurn, Game, HandCountCostSpec, HeroMissingHealthCostSpec, IllegalAction, InteractableSpec,
    MinionDeathCostSpec, OverloadRecord, PlayerOverloadCostSpec, PlayerSetup, PlayCard,
    PlayerSpellCountCostSpec, PlayerHeroPowerCountCostSpec, PlayerSpellManaCostSpec,
    Rarity, ResolutionError, Scenario, SelectChoice, SnapshotError, SpellSchool, TargetSpec,
    TriggerSpec, overloaded_crystals)
from hs_sim.engine.costs import (capture_cost_input, capture_generated_quote_fact, capture_quote_fact, quote_cost)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChangeManaCrystals, ChoiceOption, CopyMinion,
    Damage, GainArmor, GainTemporaryMana, InvokeBehavior, ModifyCost, Overload, RefreshMana,
    RequestChoice, ReturnToHand, SetManaCap, Silence, UnlockOverload)
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact, validate_intrinsic_history_prefix,
    validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.overload_history import validate_state
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import Resolution
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

GIANT, BOLT = 'ICC_090', 'EX1_238'
PATH = Path(__file__).resolve().parents[1] / 'data/support/player-overload-cost-basics.json'
PIN = 'fec42fdcb534241f1595ac609ee409f0180c5837ed2ad6ff5c07714ec2bad369'

def evidence():
    support = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support) != PIN: raise ValueError('Overload cost full evidence changed')
    for row in support['records']:
        if canonical_digest(row['data']) != row['data_sha256']: raise ValueError('Overload raw changed')
    return {row['id']: row['data'] for row in support['records']}

def registry():
    r = opening_registry(); raw = evidence()[GIANT]
    r.register_card(CardDefinition(GIANT, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], metadata=metadata(CardClass.SHAMAN, rarity=Rarity.EPIC, tribes=('ELEMENTAL',)),
        player_overload_cost=PlayerOverloadCostSpec()))
    bolt = evidence()[BOLT]
    r.register_behavior('over.bolt', lambda c: (Overload(c.player_id, 1), Damage(c.target_id, 3, c.source_id, DamageKind.SPELL)))
    r.register_card(CardDefinition(BOLT, bolt['name'], CardType.SPELL, cost=bolt['cost'], spell_school=SpellSchool.NATURE,
        metadata=metadata(CardClass.SHAMAN, rarity=Rarity.COMMON), targeting=TargetSpec(), on_play='over.bolt'))
    for cid, amount, player in (('over.zero', 0, None), ('over.one', 1, None), ('over.two', 2, None),
            ('over.three', 3, None), ('over.many', 20, None), ('over.enemy', 3, 2)):
        r.register_behavior(cid, lambda c, n=amount, p=player: (Overload(c.player_id if p is None else p, n),))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    def held(c):
        return next(eid for eid in c.state.players[c.player_id].hand if c.state.entities[eid].card_id == GIANT)
    def first(c):
        return next(eid for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id == GIANT)
    scripts = {
        'over.acquire': lambda c: (AddToHand(c.player_id, GIANT),),
        'over.unlock': lambda c: (UnlockOverload(c.player_id),),
        'over.unlock.keep': lambda c: (UnlockOverload(c.player_id, False),),
        'over.other': lambda c: (GainTemporaryMana(c.player_id, 2), RefreshMana(c.player_id, 3),
            ChangeManaCrystals(c.player_id, -1), SetManaCap(c.player_id, 12)),
        'over.local': lambda c: (ModifyCost(held(c), CostSpec(delta=-3)),),
        'over.external': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-2, card_ids=(GIANT,))),),
        'over.copy': lambda c: (CopyMinion(first(c), c.player_id, mode='base'),),
        'over.silence': lambda c: (Silence(first(c)),),
        'over.bounce': lambda c: (ReturnToHand(first(c)),),
        'over.fail': lambda c: (Overload(c.player_id, 3), AddToHand(c.player_id, 'unknown.overload.price')),
        'over.pause': lambda c: (Overload(c.player_id, 2), RequestChoice(c.player_id, (
            ChoiceOption('continue', 'More actual overload', (Overload(c.player_id, 3),)),
            ChoiceOption('fault', 'Delayed error', (InvokeBehavior('over.fail', c.source_id, c.player_id),)),
        ), c.source_id)),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body); r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    r.register_behavior('over.counter', lambda c: (CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id != c.player_id else ())
    r.register_card(CardDefinition('over.counter', 'Physical spell counter', CardType.MINION, health=4,
        triggers=(TriggerSpec('card_committed', 'over.counter'),)))
    r.register_behavior('over.observe', lambda c: (GainArmor(c.state.players[c.player_id].hero_id,
        1 + overloaded_crystals(c.state, c.player_id)),))
    r.register_card(CardDefinition('over.observe', 'Observe original resource windows', CardType.MINION, health=4,
        triggers=(TriggerSpec('mana_changed', 'over.observe'), TriggerSpec('overload_added', 'over.observe'))))
    def paid_pause(c):
        if c.state.entities[c.event.source_id].card_id != GIANT: return ()
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Finish paid minion',
            (Overload(c.player_id, 3), AddToHand(c.player_id, GIANT))),), c.source_id),)
    r.register_behavior('over.paid.pause', paid_pause)
    r.register_card(CardDefinition('over.paid.watch', 'Paid minion completion observer', CardType.MINION, health=4,
        triggers=(TriggerSpec('card_played', 'over.paid.pause'),)))
    return r

def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({key: value for key, value in saved.items()
        if key not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved

class PlayerOverloadCostTests(unittest.TestCase):
    def game(self, hand=(GIANT,), *, enemy_hand=(), board=(), enemy_board=(), owed=0, locked=0, mana=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, deck=('card.1',)*4, mana=10-locked if mana is None else mana,
                max_mana=10, overload_owed=owed, overload_locked=locked),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy_board, deck=('card.1',)*4, mana=10, max_mana=10)),
            seed=21), registry())
    def source(self, g, cid=GIANT, player=1):
        return next(g.state.entities[eid] for eid in g.state.players[player].hand if g.state.entities[eid].card_id == cid)
    def fact(self, g, cid=GIANT, player=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, cid, player)))
    def price(self, g, player=1): return self.fact(g, player=player).amount
    def play(self, g, cid, target=None):
        eid = self.source(g, cid, g.state.active_player).id
        g.apply(PlayCard(g.state.active_player, eid, target)); return eid
    def choose(self, g, option='continue'):
        c = g.state.pending_choice; g.apply(SelectChoice(c.player_id, c.id, (option,)))
    def two(self, *, extras=(), board=()):
        g = self.game((GIANT, 'over.two', *extras), board=board)
        self.play(g, 'over.two'); return g
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry())
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for player in (1, 2): self.assertEqual(other.observe(player), g.observe(player))
        return saved

    def test_full_raw_records_are_pinned_and_only_necessary_faces_are_adapted(self):
        raw = evidence(); catalog = {v['id']: v for v in json.loads((PATH.parents[1] / 'extracted/cards.json').read_bytes())}
        self.assertEqual(set(raw), {GIANT, 'CORE_ICC_090', BOLT})
        for cid, row in raw.items(): self.assertEqual(row, catalog[cid])
        r = registry(); giant = r.card(GIANT)
        self.assertEqual((giant.cost, giant.attack, giant.health, giant.metadata.classes, giant.metadata.tribes),
            (11, 8, 8, (CardClass.SHAMAN,), ('ELEMENTAL',)))
        self.assertEqual((r.card(BOLT).cost, r.card(BOLT).spell_school), (1, SpellSchool.NATURE))

    def test_only_one_real_finite_ordinary_minion_quantity_is_registered(self):
        with self.assertRaises(ValueError): PlayerOverloadCostSpec('invented.formula')
        for extra in (dict(kind=CardType.SPELL), dict(interactable=InteractableSpec('over.two')),
                dict(board_minion_cost=BoardMinionCostSpec()), dict(hand_count_cost=HandCountCostSpec()),
                dict(hero_missing_health_cost=HeroMissingHealthCostSpec()), dict(player_spell_count_cost=PlayerSpellCountCostSpec()),
                dict(player_hero_power_count_cost=PlayerHeroPowerCountCostSpec()), dict(player_spell_mana_cost=PlayerSpellManaCostSpec()),
                dict(minion_death_cost=MinionDeathCostSpec())):
            values = dict(id='bad.overload', name='Bad declaration', kind=CardType.MINION, health=1,
                player_overload_cost=PlayerOverloadCostSpec()); values.update(extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError): registry().register_card(CardDefinition(**values))

    def test_empty_game_keeps_printed_price_and_original_empty_cursor(self):
        g = self.game(); f = self.fact(g).intrinsic.player_overload
        self.assertEqual((self.price(g), f.records, f.quantity, f.next_overload_id, g.state.next_overload_id), (11, (), 0, 1, 1))
        self.portable(g)

    def test_starting_owed_and_locked_crystals_do_not_create_historical_overload(self):
        g = self.game(owed=7, locked=4)
        self.assertEqual((overloaded_crystals(g.state, 1), self.price(g), g.state.overload_history), (0, 11, []))
        self.portable(g)

    def test_prior_pending_balance_is_not_added_again(self):
        g = self.game((GIANT, 'over.two'), owed=8); self.play(g, 'over.two')
        row, = g.state.overload_history
        self.assertEqual((row.amount, row.pending_before, row.pending_after, self.price(g)), (2, 8, 10, 9))
        self.portable(g)

    def test_two_and_three_actual_increments_count_five_crystals_not_two_cards(self):
        g = self.two(extras=('over.three',)); self.play(g, 'over.three')
        self.assertEqual(([r.amount for r in g.state.overload_history], overloaded_crystals(g.state, 1), self.price(g)), ([2, 3], 5, 6))
        self.portable(g)

    def test_two_same_face_physical_bolts_each_add_one_actual_increment(self):
        g = self.game((GIANT, BOLT, BOLT)); target = g.state.players[2].hero_id
        self.play(g, BOLT, target); self.play(g, BOLT, target)
        self.assertEqual((len(g.state.overload_history), overloaded_crystals(g.state, 1), self.price(g)), (2, 2, 9))
        self.assertNotEqual(g.state.overload_history[0].event_sequence, g.state.overload_history[1].event_sequence)
        self.portable(g)

    def test_actual_affected_player_excludes_opponent_quantity(self):
        g = self.game((GIANT, 'over.two', 'over.enemy'), enemy_hand=(GIANT,))
        self.play(g, 'over.two'); self.play(g, 'over.enemy')
        self.assertEqual((self.price(g), self.price(g, 2)), (9, 8))
        self.assertEqual([r.player_id for r in g.state.overload_history], [1, 2]); self.portable(g)

    def test_overload_before_giant_acquisition_is_retained(self):
        g = self.game(('over.two', 'over.acquire')); self.play(g, 'over.two'); self.play(g, 'over.acquire')
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_overload.quantity), (9, 2)); self.portable(g)

    def test_actual_turn_locking_keeps_the_same_all_game_quantity(self):
        g = self.two(); records = tuple(g.state.overload_history)
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual((g.state.players[1].overload_owed, g.state.players[1].overload_locked, self.price(g)), (0, 2, 9))
        self.assertEqual(tuple(g.state.overload_history), records); self.portable(g)

    def test_unlocking_all_pending_and_locked_does_not_erase_quantity(self):
        g = self.two(extras=('over.unlock',)); self.play(g, 'over.unlock')
        self.assertEqual((g.state.players[1].overload_owed, g.state.players[1].overload_locked, self.price(g)), (0, 0, 9))
        self.portable(g)

    def test_unlock_without_pending_clear_keeps_account_and_history(self):
        g = self.game((GIANT, 'over.two', 'over.unlock.keep'), locked=3); self.play(g, 'over.two'); self.play(g, 'over.unlock.keep')
        self.assertEqual((g.state.players[1].overload_owed, g.state.players[1].overload_locked, self.price(g)), (2, 0, 9))
        self.portable(g)

    def test_zero_overload_has_mana_event_but_no_positive_history_root(self):
        g = self.game((GIANT, 'over.zero')); self.play(g, 'over.zero')
        self.assertEqual((g.state.overload_history, g.state.next_overload_id, self.price(g)), ([], 1, 11))
        self.assertEqual(len([e for e in g.events if e.kind == 'mana_changed']), 1)
        self.assertFalse(any(e.kind == 'overload_added' for e in g.events)); self.portable(g)

    def test_other_mana_operations_do_not_change_original_overload_quantity(self):
        g = self.two(extras=('over.other',)); history = tuple(g.state.overload_history); self.play(g, 'over.other')
        self.assertEqual((tuple(g.state.overload_history), self.price(g)), (history, 9)); self.portable(g)

    def test_actual_lightning_bolt_spends_mana_and_records_only_its_overload(self):
        g = self.game((GIANT, BOLT)); self.play(g, BOLT, g.state.players[2].hero_id)
        self.assertEqual((g.state.players[1].mana, g.state.entities[g.state.players[2].hero_id].health, self.price(g)), (9, 27, 10))
        self.assertEqual([health_result(e).damage_kind for e in g.events if health_result(e) is not None], [DamageKind.SPELL.value])
        row, = g.state.overload_history; self.assertEqual(row.amount, 1); self.portable(g)

    def test_countered_bolt_has_a_paid_play_but_no_executed_overload(self):
        g = self.game((GIANT, BOLT), enemy_board=('over.counter',)); self.play(g, BOLT, g.state.players[2].hero_id)
        self.assertEqual((g.state.players[1].mana, g.state.overload_history, self.price(g)), (9, [], 11)); self.portable(g)

    def test_large_actual_increment_is_not_capped_to_mana_capacity_and_price_floors_zero(self):
        g = self.game((GIANT, 'over.many')); self.play(g, 'over.many')
        self.assertEqual((g.state.players[1].overload_owed, overloaded_crystals(g.state, 1), self.price(g)), (20, 20, 0))
        self.play(g, GIANT); self.assertEqual(g.state.play_history[-1].cost, 0); self.portable(g)

    def test_public_quantity_and_all_quotes_are_pure_and_require_real_player(self):
        g = self.two(); before = g.snapshot()
        for _ in range(3):
            self.assertEqual(overloaded_crystals(g.state, 1), 2)
            self.assertEqual(quote_cost(g.state, g.registry, self.source(g)).amount, 9)
        for bad in (True, 0, 3, '1'):
            with self.assertRaises(ValueError): overloaded_crystals(g.state, bad)
        generated = capture_generated_quote_fact(g.state, g.registry, 1, GIANT)
        self.assertEqual(generated.amount, 9); validate_generated_quote_fact(g.registry, generated)
        self.assertEqual(g.snapshot(), before)

    def test_original_mana_and_overload_captures_have_distinct_publication_windows(self):
        g = self.two(board=('over.observe',))
        self.assertEqual([e.amount for e in g.events if e.kind == 'armor_gained'], [1, 3])
        row, = g.state.overload_history
        self.assertLess(row.mana_event_sequence, row.event_sequence); self.portable(g)

    def test_overload_choice_restores_original_increment_and_resumes_new_one(self):
        g = self.game((GIANT, 'over.pause')); self.play(g, 'over.pause')
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(self.price(g), 9); self.portable(g)
        self.choose(g); self.assertEqual((self.price(g), [r.amount for r in g.state.overload_history]), (6, [2, 3])); self.portable(g)

    def test_exception_after_increment_rolls_back_accounts_history_events_and_rng(self):
        g = self.game((GIANT, 'over.fail')); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'over.fail')
        self.assertEqual(g.snapshot(), before)

    def test_delayed_error_preserves_previous_committed_overload_choice(self):
        g = self.game((GIANT, 'over.pause')); self.play(g, 'over.pause'); before = self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)

    def test_local_external_and_generated_layers_follow_original_crystal_quantity(self):
        g = self.two(extras=('over.local', 'over.external')); self.play(g, 'over.local'); self.play(g, 'over.external')
        f = self.fact(g); self.assertEqual((f.intrinsic.amount, f.local_amount, f.amount), (9, 6, 4))
        generated = capture_generated_quote_fact(g.state, g.registry, 1, GIANT, cost=CostSpec(delta=-3))
        self.assertEqual(generated.amount, 4); self.portable(g)

    def test_player_price_legal_submission_and_payment_use_original_same_quantity(self):
        g = self.two(); port = g.for_player(1); dto = port.legal_actions()
        card = next(v for v in g.observe(1)['players'][0]['hand'] if v['card_id'] == GIANT)
        action = next(v for v in dto['actions'] if v.get('card') == card['ref'])
        self.assertEqual(card['cost']['amount'], 9)
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (9, 1)); self.portable(g)

    def test_insufficient_giant_payment_preserves_complete_original_state(self):
        g = self.game(); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, GIANT)
        self.assertEqual(g.snapshot(), before)

    def test_printed_copy_silence_and_bounce_requery_same_player_history(self):
        g = self.two(extras=('over.copy', 'over.silence', 'over.bounce')); self.play(g, GIANT)
        self.play(g, 'over.copy'); self.play(g, 'over.silence'); self.play(g, 'over.bounce')
        self.assertEqual((self.price(g), overloaded_crystals(g.state, 1)), (9, 2)); self.portable(g)

    def test_paid_giant_choice_and_later_overload_keep_original_paid_amount(self):
        g = self.two(board=('over.paid.watch',)); self.play(g, GIANT); self.portable(g)
        original = g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.assertEqual((g.state.play_history[-1].cost, original.player_overload.quantity), (9, 2))
        self.choose(g); self.assertEqual((self.price(g), g.state.play_history[1].cost), (6, 9))
        validate_intrinsic_history_prefix(original, g.state, g.registry); self.portable(g)

    def test_old_paid_prefix_restores_after_real_turn_handoff(self):
        g = self.two(); self.play(g, GIANT); original = g.state.play_history[-1].submitted_cost.quote.intrinsic
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        validate_intrinsic_history_prefix(original, g.state, g.registry)
        self.assertEqual(overloaded_crystals(g.state, 1), 2); self.portable(g)

    def test_records_are_strict_immutable_positive_amounts_with_ordered_events(self):
        row, = self.two().state.overload_history
        with self.assertRaises(FrozenInstanceError): row.amount = 3
        for changes in (dict(amount=0), dict(amount=True), dict(player_id=True), dict(pending_before=-1),
                dict(pending_after=5), dict(event_sequence=row.mana_event_sequence), dict(mana_event_sequence=0)):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(row, **changes)

    def test_original_state_cursor_clock_owner_and_exact_types_are_required(self):
        g = self.two(); state = g.state
        for changes in ('cursor', 'future_action', 'future_turn', 'future_owner', 'type'):
            bad = deepcopy(state); row = bad.overload_history[0]
            if changes == 'cursor': bad.next_overload_id += 1
            elif changes == 'future_action': bad.overload_history[0] = replace(row, action=state.action_number+1)
            elif changes == 'future_turn': bad.overload_history[0] = replace(row, turn=state.turn+1)
            elif changes == 'future_owner': bad.overload_history[0] = replace(row, owner_turn_id=2)
            else: bad.overload_history[0] = dict(amount=2)
            with self.subTest(changes=changes), self.assertRaises(ValueError): validate_state(bad)

    def test_rehashed_state_cannot_drop_complete_original_increment_inventory(self):
        g = self.two(); bad = self.portable(g); bad['state']['overload_history'] = []; bad['state']['next_overload_id'] = 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())

    def test_rehashed_state_cannot_borrow_wrong_mana_event_or_change_actual_amount(self):
        g = self.two(extras=('over.other',)); self.play(g, 'over.other'); saved = self.portable(g)
        other = next(e.sequence for e in g.events if e.kind == 'mana_changed' and dict(e.data)['operation'] != 'Overload')
        for mode in ('mana', 'event', 'amount'):
            bad = deepcopy(saved); row = bad['state']['overload_history'][0]
            if mode == 'mana': row['mana_event_sequence'] = other
            elif mode == 'event': row['event_sequence'] = other
            else: row['amount'] = 3; row['pending_after'] = row['pending_before']+3
            with self.subTest(mode=mode), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())

    def test_rehashed_original_increment_event_cannot_disagree_with_ledger(self):
        g = self.two(); saved = self.portable(g)
        for mode in ('drop', 'amount', 'player', 'pending', 'mana_operation', 'mana_owed',
                'player_bool', 'mana_player_bool', 'pending_before_bool', 'pending_before_float', 'pending_after_float'):
            bad = deepcopy(saved); row = bad['state']['overload_history'][0]
            event = bad['events'][row['event_sequence']-1]; mana = bad['events'][row['mana_event_sequence']-1]
            if mode == 'drop': event['kind'] = 'not.overload'
            elif mode == 'amount': event['amount'] += 1
            elif mode == 'player': event['player_id'] = 2
            elif mode == 'pending': event['data']['pending_before'] += 1
            elif mode == 'mana_operation': mana['data']['operation'] = 'RefreshMana'
            elif mode == 'mana_owed': mana['data']['owed'] += 1
            elif mode == 'player_bool': event['player_id'] = True
            elif mode == 'mana_player_bool': mana['player_id'] = True
            elif mode == 'pending_before_bool': event['data']['pending_before'] = False
            elif mode == 'pending_before_float': event['data']['pending_before'] = 0.0
            else: event['data']['pending_after'] = 2.0
            with self.subTest(mode=mode), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())

    def test_overload_publication_requires_actual_original_mana_operation(self):
        g = self.game(); before = g.snapshot(); resolution = Resolution(g)
        with self.assertRaises(ResolutionError): resolution.emit('overload_added', player_id=1, amount=2, pending_before=0, pending_after=2)
        with self.assertRaises(ResolutionError): resolution.emit('unrelated', _overload_commit=True)
        self.assertEqual(g.snapshot(), before)

    def test_full_origin_and_physical_allocator_reject_later_overload_source(self):
        g = self.two(extras=('over.three',)); f = self.fact(g); stage = f.intrinsic
        validate_intrinsic_origin(stage, g.state, g.registry)
        with self.assertRaises(ValueError): replace(f, quote_input=replace(f.quote_input, source_id=stage.player_overload.next_entity_id))
        self.play(g, 'over.three'); validate_intrinsic_history_prefix(stage, g.state, g.registry)
        with self.assertRaises(ValueError): validate_intrinsic_origin(stage, g.state, g.registry)

    def test_frozen_prefix_cannot_borrow_different_original_pending_values(self):
        g = self.two(); stage = self.fact(g).intrinsic; f = stage.player_overload; row, = f.records
        changed = replace(stage, player_overload=replace(f, records=(replace(row, pending_before=5, pending_after=7),)))
        validate_intrinsic_stage_fact(g.registry, changed)
        with self.assertRaises(ValueError): validate_intrinsic_history_prefix(changed, g.state, g.registry)

    def test_frozen_fact_requires_complete_cursor_allocation_amount_and_original_window(self):
        g = self.two(); stage = self.fact(g).intrinsic; f = stage.player_overload
        for values in (dict(records=()), dict(records=list(f.records)), dict(quantity=3), dict(after=8),
                dict(overload_history_length=2), dict(next_overload_id=3), dict(next_entity_id=True)):
            with self.subTest(values=values), self.assertRaises(ValueError): replace(f, **values)
        with self.assertRaises(ValueError): replace(stage, player_overload=replace(f, player_id=2, quantity=0, after=11))
        with self.assertRaises(ValueError): replace(stage, player_overload=replace(f, action=f.action+1))

    def test_rehashed_paid_wire_cannot_drop_or_rewrite_complete_overload_fact(self):
        g = self.two(); self.play(g, GIANT); saved = self.portable(g)
        for mode in ('quantity', 'field', 'fact', 'extra', 'records', 'cursor', 'event', 'owner', 'boolean'):
            bad = deepcopy(saved); stage = bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']; f = stage['player_overload']
            if mode == 'quantity': f['quantity'] += 1
            elif mode == 'field': del stage['player_overload']
            elif mode == 'fact': stage['player_overload'] = None
            elif mode == 'extra': f['invented'] = 1
            elif mode == 'records': f['records'] = []
            elif mode == 'cursor': f['next_overload_id'] += 1
            elif mode == 'event': f['records'][0]['event_sequence'] += 1
            elif mode == 'owner': f['records'][0]['owner_turn_id'] = 0
            else: f['records'][0]['amount'] = True
            with self.subTest(mode=mode), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())

    def test_player_price_keeps_internal_ledger_and_opponent_hand_private(self):
        g = self.two(); own = g.observe(1)
        self.assertEqual(own['players'][0]['hand'][0]['cost']['amount'], 9)
        for player in (1, 2):
            text = json.dumps(g.observe(player))
            for private in ('overload_history', 'next_overload_id', 'player_overload', 'submitted_cost', 'payment_state', 'pending_before'):
                self.assertNotIn(private, text)
        saved = self.portable(g)
        self.assertEqual(len(saved['state']['overload_history']), 1)

    def test_detached_state_and_restored_lists_cannot_mutate_live_history(self):
        g = self.two(); state = g.state; state.overload_history.clear(); saved = self.portable(g)
        self.assertEqual(overloaded_crystals(g.state, 1), 2)
        other = Game.from_snapshot(saved, registry()); saved['state']['overload_history'].clear()
        self.assertEqual(overloaded_crystals(other.state, 1), 2)

    def test_default_none_and_current_protocol_require_explicit_saved_history_and_leaf(self):
        g = self.game(('card.1',)); self.assertIsNone(self.fact(g, 'card.1').intrinsic.player_overload)
        self.play(g, 'card.1'); saved = self.portable(g)
        self.assertEqual((g.ruleset.id, g.mechanics.version, saved['schema_version']), ('prototype-v302', CORE_EFFECTS_VERSION, SNAPSHOT_SCHEMA_VERSION))
        for mode in ('schema', 'history', 'allocator', 'leaf'):
            bad = deepcopy(saved)
            if mode == 'schema': bad['schema_version'] = 177
            elif mode == 'history': del bad['state']['overload_history']
            elif mode == 'allocator': del bad['state']['next_overload_id']
            else: del bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['player_overload']
            with self.subTest(mode=mode), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())

if __name__ == '__main__': unittest.main()
