from functools import lru_cache
from pathlib import Path
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.past_one_cost_qualified_price_cards import (
    ATTENDANT, CLERIC, COLLECTOR, DEPENDENCIES, FLOWRIDER, KNIGHT, LEAVES,
    OUTSIDER, PRIEST, SCARAB, SUBJUGATOR, VIRTUOSO, WISDOM, load_batch,
)
from hs_sim.engine import Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction, Keyword, PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone
from hs_sim.engine.effects import (
    AddToHand, ChangeControl, ChoiceOption, Damage, Destroy, Heal, InvokeBehavior,
    Overload, RequestChoice, Silence, UnlockOverload,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass, CostSpec, DamageKind, TargetMode
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.engine.costs import quote_cost
from tools import card_batch as batch


P = 'test.k464.'
NOOP, KILL, SILENCE, OWE, CLEAR, HURT_SELF, HURT_OTHER, HEAL_SELF, HEAL_OTHER, TAKE, TAKE_BACK, DISCOUNT_DECK, FAIL, WATCH = (
    P+s for s in ('noop', 'kill', 'silence', 'owe', 'clear', 'hurt_self', 'hurt_other', 'heal_self', 'heal_other',
        'take', 'take_back', 'discount_deck', 'fail', 'watch'))
YETI, RAVEN, ORACLE, FROST, TIDE, SIGHT, RUNNER, PLUNDERER, AXE, DRAGON, FLASHBACK, UNKNOWN_ONE, UNKNOWN_TWO = (
    'CORE_CS2_182', 'KAR_300', 'UNG_032', 'CORE_CS2_024', 'CORE_EX1_506', 'CORE_BT_491', 'CORE_BT_480',
    'DMF_519', 'CS2_106', 'WON_065', 'TIME_711', 'BAR_031', 'AT_003')
CONTEXT = GenerationContext('k464-explicit-qualified-prices', 'experimental')
MEMBERS = (RAVEN, ORACLE, FROST, TIDE, SIGHT, WISDOM, AXE)


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry()
    r.register_pool(PoolDefinition('constructed.past.cards', 'ten-qualified-leaves-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid) for cid in LEAVES), complete=True))
    members = MEMBERS
    if mode in ('unknown_one', 'unknown_two'):
        raw = {row['id']: row for row in batch.read(Path(__file__).resolve().parents[1]/load_batch()['source']['path'])}
        cid = UNKNOWN_ONE if mode == 'unknown_one' else UNKNOWN_TWO
        assert cid not in r.cards
        row = raw[cid]
        r.register_pool_card(PoolCard(cid, CardType.MINION, row['cost'], metadata=metadata_from_record(row)))
        members += (cid,)
    if mode != 'unbound':
        r.register_pool(PoolDefinition('constructed.cards', 'finite-qualified-host-v1', CONTEXT.target_id,
            CONTEXT.mode, tuple(PoolMember(cid) for cid in (() if mode == 'empty' else members)), complete=True))

    def fail(c):
        raise ResolutionError('K464 deliberate late consumer failure')

    def discount_deck(c):
        target = c.state.entities[c.state.players[c.player_id].deck[0]]
        return (ModifyStoredCost(CardReference.capture(target), CostSpec(delta=-1), c.source_id),)

    bodies = {
        NOOP: lambda c: (), KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        SILENCE: lambda c: (Silence(c.target_id),), OWE: lambda c: (Overload(c.player_id, 1),),
        CLEAR: lambda c: (UnlockOverload(c.player_id),),
        HURT_SELF: lambda c: (Damage(c.state.players[c.player_id].hero_id, 3, c.source_id, DamageKind.EFFECT),),
        HURT_OTHER: lambda c: (Damage(c.state.players[3-c.player_id].hero_id, 3, c.source_id, DamageKind.EFFECT),),
        HEAL_SELF: lambda c: (Heal(c.state.players[c.player_id].hero_id, 5, c.source_id),),
        HEAL_OTHER: lambda c: (Heal(c.state.players[3-c.player_id].hero_id, 5, c.source_id),),
        TAKE: lambda c: (ChangeControl(c.target_id, 2),), TAKE_BACK: lambda c: (ChangeControl(c.target_id, 1),),
        DISCOUNT_DECK: discount_deck, FAIL: fail,
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            targeting=TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,)) if cid in (KILL, SILENCE, TAKE, TAKE_BACK) else None))

    def watch(c):
        e = c.event; source = c.state.entities.get(e.source_id); cid = None if source is None else source.card_id
        price = e.kind == 'cost_modifier_added' and cid in (ATTENDANT, COLLECTOR, OUTSIDER)
        reward = (e.kind == 'card_added_to_hand' and cid in (SCARAB, YETI) or
            e.kind == 'minion_summoned' and e.player_id == 2 or
            e.kind == 'stats_changed' and cid in (WISDOM, SUBJUGATOR) or
            e.kind == 'damage_dealt' and cid == PLUNDERER)
        if mode == 'fail' and reward: return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        if mode == 'wait_price' and price or mode == 'wait_reward' and reward:
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
        return ()

    behavior = WATCH + '.' + mode; r.register_behavior(behavior, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.WEAPON, attack=0, durability=50,
        triggers=tuple(TriggerSpec(e, behavior) for e in ('cost_modifier_added', 'card_added_to_hand',
            'minion_summoned', 'stats_changed', 'damage_dealt')) if mode.startswith('wait') or mode == 'fail' else ()))
    r.validate(); return r


class PastOneCostQualifiedPriceTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), board=(), *, deck=(NOOP,)*6, enemy_hand=(), enemy_board=(),
             enemy_deck=(NOOP,)*6, active=1, mode='normal', owed=0, locked=0):
        self.mode = mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=deck, overload_owed=owed,
                overload_locked=locked, weapon_card_id=WATCH if mode.startswith('wait') or mode == 'fail' else None,
                hero_power_card_id='HERO_08bp', mana=10-locked, max_mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board, deck=enemy_deck,
                hero_power_card_id='HERO_08bp', mana=10, max_mana=10)),
            active_player=active, seed=464, generation_context=CONTEXT), fixture(mode))

    def ids(self, g, player=1, zone='hand'):
        return tuple(g.state.entities[i].card_id for i in getattr(g.state.players[player], zone))

    def price(self, g, cid, player=1):
        return quote_cost(g.state, g.registry, self.entity(g, cid, player)).amount

    def pick(self, g, index=0):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (q.options[index].id,)))

    def test_twenty_two_complete_rows_and_twenty_two_faces_with_complete_libram_family_facts(self):
        d = load_batch(); rows = {x['record']['id']: x['record'] for x in d['dependencies']+d['evidence_only']}; hashes = {}
        self.assertEqual((len(rows), len(d['official_observations']), len(d['dependencies'])), (22, 22, 11))
        for o in d['official_observations']:
            if o['response_file'] not in hashes: hashes[o['response_file']] = batch.sha(Path(o['response_file']))
            self.assertEqual(hashes[o['response_file']], o['response_sha256']); batch.check_face(rows[o['card_id']], o['face'], o['locale'])
        path = Path(__file__).resolve().parents[1]/d['source']['path']; self.assertEqual(batch.sha(path), d['source']['sha256'])
        native = [r['id'] for r in batch.read(path) if type(r['tags'].get('LIBRAM')) is int and r['tags']['LIBRAM'] > 0]
        self.assertEqual(native, d['printed_libram_ids']); self.assertIn('YOP_011', native); self.assertIn('YOP_011t', native)
        self.assertFalse(d['formal_pool_complete']); self.assertFalse(d['cn_calibrated'])

    def test_ten_native_minion_entries_pay_once_and_keep_original_stats(self):
        for cid in LEAVES:
            with self.subTest(card=cid):
                g = self.game((cid,)); source = self.play(g, cid)
                self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health, g.state.players[1].mana),
                    (g.registry.card(cid).attack, g.registry.card(cid).health, 9))
                if g.state.pending_choice: self.pick(g)

    def test_three_discovery_conditions_false_keep_physical_deck_and_rng(self):
        for cid in (FLOWRIDER, CLERIC, PRIEST):
            g = self.game((cid,), deck=(FROST, TIDE)); original = tuple(g.state.players[1].deck); rng = g._rng.getstate()
            self.play(g, cid); self.assertIsNone(g.state.pending_choice)
            self.assertEqual(tuple(g.state.players[1].deck), original); self.assertEqual(g._rng.getstate(), rng)

    def test_flowrider_owed_or_locked_accounts_enable_original_deck_spell_discovery(self):
        for owed, locked in ((1, 0), (0, 1), (2, 3)):
            g = self.game((FLOWRIDER,), deck=(FROST, TIDE), owed=owed, locked=locked); original = g.state.players[1].deck[0]
            self.play(g, FLOWRIDER); self.assertEqual([o.card_id for o in g.state.pending_choice.options], [FROST]); self.pick(g)
            self.assertEqual(g.state.players[1].hand, [original]); self.assertFalse(g.state.draw_history)

    def test_cleric_uses_actual_restoration_by_player_even_to_opponent_and_not_overheal(self):
        g = self.game((HEAL_SELF, CLERIC), deck=(FROST,)); self.play(g, HEAL_SELF); self.play(g, CLERIC)
        self.assertIsNone(g.state.pending_choice)
        g = self.game((HURT_OTHER, HEAL_OTHER, CLERIC), deck=(FROST,)); self.play(g, HURT_OTHER); self.play(g, HEAL_OTHER); self.play(g, CLERIC)
        self.assertIsNotNone(g.state.pending_choice); self.pick(g); self.assertEqual(self.ids(g), (FROST,))

    def test_priest_held_current_dragon_and_all_tribes_enable_discovery(self):
        for dragon in (DRAGON, 'NX2_050'):
            g = self.game((PRIEST, dragon), deck=(FROST,)); self.play(g, PRIEST)
            self.assertIsNotNone(g.state.pending_choice); self.pick(g); self.assertEqual(self.ids(g), (dragon, FROST))

    def test_physical_deck_discovery_keeps_duplicates_and_current_cost_without_drawing(self):
        g = self.game((DISCOUNT_DECK, FLOWRIDER), deck=(FROST, FROST, TIDE), owed=1)
        selected = g.state.players[1].deck[0]; self.play(g, DISCOUNT_DECK); self.play(g, FLOWRIDER)
        offered = g.state.pending_choice.options; self.assertEqual(len(offered), 2)
        selected_id = next(o.id for o in g._frame.options if o.effects[0].card.entity_id == selected)
        index = next(i for i, o in enumerate(offered) if o.id == selected_id)
        self.pick(g, index); self.assertEqual(g.state.players[1].hand, [selected])
        self.assertEqual(g.state.entities[selected].cost, 1); self.assertFalse(g.state.draw_history)

    def test_deck_discovery_wait_restores_private_options_and_original_physical_take(self):
        g = self.game((FLOWRIDER,), deck=(FROST, WISDOM, TIDE), owed=1); self.play(g, FLOWRIDER)
        self.assertIsNotNone(g.state.pending_choice); offered = tuple(o.id for o in g.state.pending_choice.options)
        self.assertNotIn('zone-', str(g.for_player(2).observe())); g = self.portable(g)
        self.assertEqual(tuple(o.id for o in g.state.pending_choice.options), offered); self.pick(g)
        self.assertEqual(len(g.state.players[1].hand), 1); self.assertEqual(len(g.state.players[1].deck), 2)

    def test_true_deck_condition_empty_spell_candidates_skips_without_rng_or_fatigue(self):
        g = self.game((FLOWRIDER,), deck=(TIDE,), owed=1); rng = g._rng.getstate(); self.play(g, FLOWRIDER)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g._rng.getstate(), rng); self.assertEqual(g.state.players[1].fatigue, 0)

    def test_knight_summons_one_opposing_one_cost_minion_without_its_battlecry(self):
        g = self.game((KNIGHT,)); source = self.play(g, KNIGHT)
        self.assertEqual(len(g.state.players[2].board), 1); child = g.state.entities[g.state.players[2].board[0]]
        self.assertIn(child.card_id, (RAVEN, ORACLE)); self.assertEqual((child.owner, child.controller), (2, 2))
        self.assertEqual(child.attack, g.registry.card(child.card_id).attack)
        self.assertEqual([r.source_id for r in g.state.battlecry_history], [source])

    def test_knight_opposing_full_board_has_no_extra_body(self):
        g = self.game((KNIGHT,), enemy_board=(RAVEN,)*7); self.play(g, KNIGHT)
        self.assertEqual(len(g.state.players[2].board), 7)

    def test_scarab_discovers_current_class_or_neutral_two_cost_cards(self):
        g = self.game((SCARAB,)); self.play(g, SCARAB)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {FROST, TIDE})
        self.pick(g); self.assertEqual(len(g.state.players[1].hand), 1)

    def test_matching_unknown_candidates_and_unbound_domains_do_not_fall_back(self):
        for cid, mode in ((KNIGHT, 'unknown_one'), (SCARAB, 'unknown_two'), (KNIGHT, 'unbound'), (SCARAB, 'unbound')):
            g = self.game((cid,), mode=mode); before = g.snapshot()
            with self.assertRaises((ResolutionError, UnsupportedDefinitionError)): self.play(g, cid)
            self.assertEqual(g.snapshot(), before)

    def test_complete_empty_ordinary_pool_skips_without_rng(self):
        for cid in (KNIGHT, SCARAB):
            g = self.game((cid,), mode='empty'); rng = g._rng.getstate(); self.play(g, cid)
            self.assertEqual(g._rng.getstate(), rng); self.assertIsNone(g.state.pending_choice)

    def test_wisdom_really_pays_two_buffs_and_returns_through_original_minion_death(self):
        g = self.game((WISDOM, KILL), board=(YETI,)); source = self.entity(g, YETI, zone='board').id
        self.play(g, WISDOM, source); self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health, g.state.players[1].mana), (5, 6, 8))
        self.play(g, KILL, source); self.assertEqual(self.ids(g), (WISDOM,)); self.assertEqual(self.price(g, WISDOM), 2)

    def test_attendant_stacks_real_zero_cost_libram_payment_and_natural_return(self):
        g = self.game((ATTENDANT, ATTENDANT, WISDOM, KILL), board=(YETI,))
        self.play(g, ATTENDANT); self.play(g, ATTENDANT); self.assertEqual(self.price(g, WISDOM), 0)
        target = self.entity(g, YETI, zone='board').id; self.play(g, WISDOM, target)
        self.assertEqual(g.state.players[1].mana, 8); self.play(g, KILL, target)
        self.assertEqual(self.ids(g), (WISDOM,)); self.assertEqual(self.price(g, WISDOM), 0); self.portable(g)

    def test_libram_whitelist_includes_weapons_and_does_not_discount_other_spells_or_weapons(self):
        g = self.game((ATTENDANT, FROST, AXE)); self.play(g, ATTENDANT)
        modifier = g.state.players[1].cost_modifiers[-1]
        self.assertEqual(set(modifier.spec.card_ids), set(load_batch()['printed_libram_ids']))
        self.assertIn(CardType.WEAPON, modifier.spec.card_types); self.assertIsNone(modifier.uses_remaining); self.assertIsNone(modifier.expires_turn)
        self.assertEqual((self.price(g, FROST), self.price(g, AXE)), (2, 2))

    def test_libram_discount_persists_after_attendant_death_and_across_turns(self):
        g = self.game((ATTENDANT, KILL, WISDOM)); source = self.play(g, ATTENDANT); self.play(g, KILL, source)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.assertEqual(self.price(g, WISDOM), 1)

    def test_wisdom_grants_are_independent_and_silence_removes_them(self):
        g = self.game((WISDOM, WISDOM, KILL), board=(YETI,)); target = self.entity(g, YETI, zone='board').id
        self.play(g, WISDOM, target); self.play(g, WISDOM, target); self.play(g, KILL, target)
        self.assertEqual(self.ids(g), (WISDOM, WISDOM))
        g = self.game((WISDOM, SILENCE, KILL), board=(YETI,)); target = self.entity(g, YETI, zone='board').id
        self.play(g, WISDOM, target); self.play(g, SILENCE, target); self.play(g, KILL, target)
        self.assertFalse(g.state.players[1].hand)

    def test_wisdom_return_belongs_to_current_minion_controller_and_its_own_cost_account(self):
        g = self.game((ATTENDANT, WISDOM, KILL), enemy_board=(YETI,)); self.play(g, ATTENDANT)
        target = self.entity(g, YETI, 2, 'board').id; self.play(g, WISDOM, target); self.play(g, KILL, target)
        self.assertEqual(self.ids(g, 2), (WISDOM,)); self.assertEqual(self.price(g, WISDOM, 2), 2)

    def test_next_combo_is_consumed_by_real_combo_card_and_not_other_cards(self):
        g = self.game((COLLECTOR, RAVEN, PLUNDERER), enemy_board=(YETI,)); self.play(g, COLLECTOR); self.play(g, RAVEN)
        self.assertEqual(g.state.players[1].cost_modifiers[-1].uses_remaining, 1)
        self.assertEqual(self.price(g, PLUNDERER), 0); before = g.state.players[1].mana
        self.play(g, PLUNDERER, self.entity(g, YETI, 2, 'board').id)
        self.assertEqual(g.state.players[1].mana, before); self.assertFalse(g.state.players[1].cost_modifiers)

    def test_next_combo_persists_to_next_turn_and_matches_printed_card_without_activation(self):
        g = self.game((COLLECTOR, PLUNDERER)); self.play(g, COLLECTOR); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        before = g.state.players[1].mana; self.play(g, PLUNDERER)
        self.assertEqual(g.state.players[1].mana, before); self.assertFalse(g.state.combo_history)
        self.assertFalse(g.state.players[1].cost_modifiers)

    def test_outsider_accepts_original_hand_edge_and_middle_does_not_grant_price(self):
        g = self.game((NOOP, OUTSIDER, NOOP)); source = self.play(g, OUTSIDER)
        self.assertFalse(g.state.players[1].cost_modifiers); self.assertIn(Keyword.RUSH, g.state.entities[source].keywords)
        g = self.game((OUTSIDER, NOOP)); self.play(g, OUTSIDER)
        self.assertEqual(g.state.players[1].cost_modifiers[-1].uses_remaining, 1)

    def test_outcast_discount_is_printed_identity_not_future_hand_position(self):
        g = self.game((OUTSIDER, NOOP, RUNNER, NOOP)); self.play(g, OUTSIDER); before = g.state.players[1].mana
        self.play(g, RUNNER); self.assertEqual(g.state.players[1].mana, before)
        self.assertFalse(g.state.play_history[-1].outcast); self.assertFalse(g.state.draw_history)
        self.assertFalse(g.state.players[1].cost_modifiers)

    def test_outsider_chained_zero_cost_plays_consume_old_and_install_new_account_once(self):
        g = self.game((OUTSIDER, OUTSIDER, OUTSIDER))
        for _ in range(3): self.play(g, OUTSIDER)
        self.assertEqual(g.state.players[1].mana, 9)
        self.assertEqual([m.uses_remaining for m in g.state.players[1].cost_modifiers], [1])
        rows = [r for r in g.state.cost_use_history if r.origin == 'payment' and r.source_card_id == OUTSIDER]
        self.assertEqual([r.amount for r in rows], [1, 0, 0])
        self.assertEqual([len(r.consumable_ids) for r in rows], [0, 1, 1])
        consumed = [i for r in rows for i in r.consumable_ids]
        self.assertEqual(len(consumed), len(set(consumed)))
        self.assertNotIn(g.state.players[1].cost_modifiers[0].id, consumed)

    def test_real_outcast_spell_receives_discount_and_executes_original_draw(self):
        g = self.game((OUTSIDER, SIGHT)); self.play(g, OUTSIDER); self.play(g, SIGHT)
        self.assertEqual(g.state.players[1].mana, 8); self.assertEqual(len(g.state.players[1].hand), 2)
        self.assertEqual(len(g.state.draw_history), 2)

    def test_subjugator_enemy_arrow_and_original_owner_start_expiry_survive_source_death(self):
        g = self.game((SUBJUGATOR, KILL), board=(RAVEN,), enemy_board=(YETI,)); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, SUBJUGATOR, self.entity(g, RAVEN, zone='board').id)
        self.assertEqual(g.snapshot(), before); target = self.entity(g, YETI, 2, 'board').id
        source = self.play(g, SUBJUGATOR, target); self.assertEqual(g.state.entities[target].attack, 2); self.play(g, KILL, source)
        g.apply(EndTurn(1)); self.assertEqual(g.state.entities[target].attack, 2)
        g = self.portable(g); g.apply(EndTurn(2)); self.assertEqual(g.state.entities[target].attack, 4)

    def test_subjugator_no_legal_minion_is_plain_native_body(self):
        g = self.game((SUBJUGATOR,)); self.play(g, SUBJUGATOR); self.assertEqual(len(g.state.players[1].board), 1)

    def test_virtuoso_own_turn_immunity_then_opponent_damage_uses_existing_health_pipeline(self):
        g = self.game((HURT_SELF,), board=(VIRTUOSO,), enemy_hand=(HURT_OTHER,))
        self.play(g, HURT_SELF); self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 30)
        g.apply(EndTurn(1)); self.play(g, HURT_OTHER, player=2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 27)

    def test_virtuoso_silence_and_control_transfer_follow_current_native_source(self):
        g = self.game((SILENCE, HURT_SELF), board=(VIRTUOSO,)); self.play(g, SILENCE, self.entity(g, VIRTUOSO, zone='board').id)
        self.play(g, HURT_SELF); self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 27)
        g = self.game((TAKE,), board=(VIRTUOSO,)); self.play(g, TAKE, self.entity(g, VIRTUOSO, zone='board').id)
        self.assertNotIn(Keyword.IMMUNE, g.state.entities[g.state.players[1].hero_id].keywords)
        g.apply(EndTurn(1)); self.assertIn(Keyword.IMMUNE, g.state.entities[g.state.players[2].hero_id].keywords)

    def test_original_price_grant_wait_restores_consumption_and_replay(self):
        g = self.game((COLLECTOR, PLUNDERER), enemy_board=(YETI,), mode='wait_price'); self.play(g, COLLECTOR)
        self.assertIsNotNone(g.state.pending_choice); g = self.portable(g); self.choose(g)
        self.assertEqual(self.price(g, PLUNDERER), 0)
        self.play(g, PLUNDERER, self.entity(g, YETI, 2, 'board').id)
        self.assertFalse(g.state.players[1].cost_modifiers)

    def test_wisdom_buff_wait_restores_unfinished_grant_and_one_natural_return(self):
        g = self.game((WISDOM, KILL), board=(YETI,), mode='wait_reward'); target = self.entity(g, YETI, zone='board').id
        self.play(g, WISDOM, target); self.assertIsNotNone(g.state.pending_choice); g = self.portable(g); self.choose(g)
        self.play(g, KILL, target)
        while g.state.pending_choice is not None: self.choose(g)
        self.assertEqual(self.ids(g), (WISDOM,))

    def test_late_combo_damage_failure_restores_zero_cost_consumption_and_payment(self):
        g = self.game((COLLECTOR, PLUNDERER), enemy_board=(YETI,), mode='fail')
        self.play(g, COLLECTOR); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, PLUNDERER, self.entity(g, YETI, 2, 'board').id)
        self.assertEqual(g.snapshot(), before)

    def test_late_generation_and_temporary_buff_failures_restore_whole_action(self):
        for cid in (KNIGHT, SUBJUGATOR, WISDOM):
            g = self.game((cid,), board=(YETI,) if cid == WISDOM else (), enemy_board=(YETI,), mode='fail')
            target = self.entity(g, YETI, zone='board').id if cid == WISDOM else self.entity(g, YETI, 2, 'board').id if cid == SUBJUGATOR else None
            before = g.snapshot()
            with self.assertRaises(ResolutionError): self.play(g, cid, target)
            self.assertEqual(g.snapshot(), before)

    def test_actual_flashback_has_all_ten_members_and_does_not_run_summoned_battlecries(self):
        g = self.game((FLASHBACK,)); self.play(g, FLASHBACK); row, = g.state.pool_summon_history
        self.assertEqual({x.card_id for x in row.spec.basis.candidates}, set(LEAVES))
        self.assertEqual(len(g.state.players[1].board), 2); self.assertFalse(g.state.battlecry_history)
        self.assertFalse(g.state.players[1].hand)

    def test_experimental_domains_are_not_production_bindings_or_new_standard_roots(self):
        from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format
        r = build_registry(); self.assertNotIn('constructed.cards', r.pools); self.assertNotIn('constructed.past.cards', r.pools)
        self.assertFalse(set(DEPENDENCIES) & set(build_cn37_launch_candidate_format().root_card_ids))


if __name__ == '__main__':
    unittest.main()
