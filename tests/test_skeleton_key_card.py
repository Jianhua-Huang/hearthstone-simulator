"""Real Skeleton Key refreshes: one paid spell, ordinary damage and one discovery."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import random
import unittest

from hs_sim.cards import build_registry as assembled_registry
from hs_sim.cards.skeleton_key_card import ROOT, CONTROL, load_batch, register_skeleton_key_card
from hs_sim.cards.native_discovery_cost_cards import CARD as DISCOUNT, register_native_discovery_cost_cards
from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.card_discoveries import (capture_turn_match, discovered_cards,
    discovered_this_turn, require_original_result)
from hs_sim.engine.discovery_offers import unselected_materials, unselected_options
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, GainArmor, GrantKeyword,
    Heal, InvokeBehavior, RandomDamage, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CostSpec, SpellSchool
from hs_sim.engine.pools import DiscoverFromPool, GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastStoredSpell
from hs_sim.engine.zones import CardReference

P = 'key.test.'
SPELLS = ('CS2_029', 'CS2_024', 'RLK_843', 'REV_601')
FILL = 'CS2_182'
POOL = 'constructed.cards'
TARGET = P+'target'


def risk_seed(hit):
    for seed in range(100):
        rng = random.Random(seed)
        for size in (4, 3, 2): rng.randrange(size)
        if (rng.randrange(5) == 0) == hit: return seed
    raise AssertionError('No deterministic risk seed')


@lru_cache(maxsize=None)
def registry(role, mode=None, pool_mode=None):
    assert role in ('writer', 'reader')
    r = build_registry()
    register_skeleton_key_card(r)
    register_native_discovery_cost_cards(r)
    meta = replace(r.card(FILL).metadata, deck_identity=None)
    def fail(c): raise ResolutionError('Key deliberate rollback')
    r.register_behavior(P+'fail', fail)
    def setup(c):
        hero = c.state.players[c.player_id].hero_id
        if mode == 'armor': return (GainArmor(c.player_id, 3),)
        if mode == 'immune': return (GrantKeyword(hero, Keyword.IMMUNE, c.source_id),)
        if mode == 'lethal': return (Damage(hero, 26, c.source_id),)
        return ()
    r.register_behavior(P+'setup', setup)
    r.register_card(CardDefinition(P+'setup', P+'setup', CardType.SPELL, on_play=P+'setup', metadata=meta))
    r.register_behavior(P+'cast', lambda c: (CastStoredSpell(
        CardReference.capture(c.state.entities[c.target_id]), c.player_id, c.source_id,
        targeting='explicit'),))
    from hs_sim.engine import TargetSpec
    r.register_card(CardDefinition(P+'cast', P+'cast', CardType.SPELL, on_play=P+'cast',
        targeting=TargetSpec(zones=(Zone.HAND,), kinds=(CardType.SPELL,), relation='friendly'), metadata=meta))
    if mode in ('selection', 'damage', 'created', 'counter', 'fill'):
        def watch(c):
            e = c.event
            if mode in ('counter', 'fill'):
                source = c.state.entities.get(e.source_id)
                if source is None or source.card_id != ROOT: return ()
                return (CounterSpell(dict(e.data)['window_id']),) if mode == 'counter' else (AddToHand(1, FILL, c.source_id),)
            if mode == 'selection':
                if tuple(dict(e.data).get('option_ids', ())) != ('refresh',): return ()
            elif mode == 'damage':
                if e.target_id != c.state.players[1].hero_id: return ()
            elif mode == 'created':
                target = c.state.entities.get(e.target_id)
                if target is None or target.card_id not in SPELLS: return ()
            return (RequestChoice(c.player_id, (
                ChoiceOption('ok', 'Continue', ()),
                ChoiceOption('heal', 'Heal', (Heal(c.state.players[1].hero_id, 5, c.source_id),)),
                ChoiceOption('fail', 'Fail', (RandomDamage((c.state.players[2].hero_id,), 1, c.source_id),
                    InvokeBehavior(P+'fail', c.source_id, c.player_id)))), c.source_id),)
        event = {'selection': 'choice_selected', 'damage': 'damage_dealt', 'created': 'card_created',
                 'counter': 'card_committed', 'fill': 'card_committed'}[mode]
        r.register_behavior(P+'watch', watch)
        r.register_card(CardDefinition(P+'watch', P+'watch', CardType.MINION, health=8,
            triggers=(TriggerSpec(event, P+'watch'),), metadata=meta))
    members = []
    selected = () if pool_mode == 'empty' else SPELLS[:1] if pool_mode == 'short' else SPELLS
    for cid in (*selected, FILL):
        if cid not in r.pool_cards: r.register_pool_card(PoolCard.from_definition(r.card(cid)))
        members.append(PoolMember(cid))
    if pool_mode == 'unknown':
        raw = replace(r.card(SPELLS[0]), id=P+'unknown', name=P+'unknown',
            metadata=replace(r.card(SPELLS[0]).metadata, deck_identity=None))
        r.register_pool_card(PoolCard.from_definition(raw)); members.append(PoolMember(raw.id))
    r.register_pool(PoolDefinition(POOL, P+'v1', TARGET, 'experimental', tuple(members), complete=True))
    r.validate(); r.freeze(); return r


class SkeletonKeyTests(unittest.TestCase):
    def game(self, *, mode=None, pool_mode=None, seed=None, hand=(ROOT,), board=()):
        self.mode, self.pool_mode = mode, pool_mode
        if mode in ('selection', 'damage', 'created', 'counter', 'fill'): board += (P+'watch',)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(FILL,)*10, mana=10, max_mana=10),
            PlayerSetup('HERO_08', deck=(FILL,)*10, mana=10, max_mana=10)),
            seed=risk_seed(False) if seed is None else seed,
            generation_context=GenerationContext(TARGET, 'experimental')),
            registry('writer', mode, pool_mode))
    def play(self, g, cid=ROOT, target=None):
        pid = g.state.active_player
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        return g.apply(PlayCard(pid, eid, target))
    def choose(self, g, key):
        q = g.state.pending_choice
        return g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def pick(self, g): return self.choose(g, g.state.pending_choice.options[0].id)
    def portable(self, g):
        writer = registry('writer', self.mode, self.pool_mode)
        r = registry('reader' if g.registry is writer else 'writer', self.mode, self.pool_mode)
        s = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(s, r)
        for candidate in (other, g.clone(), replay(build_replay(g), r)):
            self.assertEqual(candidate.snapshot(), s)
        for pid in (1, 2):
            wire = json.dumps(g.for_player(pid).observe()) + json.dumps(g.for_player(pid).legal_actions()) + json.dumps(g.player_events(pid))
            for private in ('control_roll', 'original_offer', 'rng_state', 'resolution_frame', 'RefreshPoolDiscovery'):
                self.assertNotIn(private, wire)
        return other
    def hp(self, g): return g.state.entities[g.state.players[1].hero_id].health
    def test_a00_complete_source_four_primary_faces_and_choice_only_control(self):
        from tools.card_batch import check_face
        data = load_batch(); rows = {x['record']['id']: x['record'] for k in ('cards', 'dependencies') for x in data[k]}
        self.assertEqual(len(data['official_observations']), 4)
        for item in data['official_observations']:
            check_face(rows[item['card_id']], item['face'], item['locale'],
                numeric_normalizations=data['numeric_normalizations'].get(item['card_id']))
        full = assembled_registry(); r = registry('writer')
        for cid in (ROOT, CONTROL): self.assertEqual(r.card(cid), full.card(cid))
        self.assertEqual((r.card(ROOT).cost, r.card(ROOT).spell_school), (1, SpellSchool.ARCANE))
        self.assertFalse(r.card(CONTROL).hand_playable); self.assertTrue(r.card(CONTROL).choice_only)
        self.assertNotIn(CONTROL, full.pool_cards); self.assertNotIn(ROOT+'e', full.cards)
    def test_b00_four_option_menu_only_three_actual_materials_and_one_payment(self):
        g = self.game(); self.play(g); q = g.state.pending_choice
        self.assertEqual(len(q.options), 4); self.assertEqual((q.options[-1].id, q.options[-1].card_id), ('refresh', CONTROL))
        self.assertEqual(len(g._frame.original_discovery_offer.materials), 3)
        self.assertTrue({o.card_id for o in q.options[:-1]} <= set(SPELLS))
        self.assertEqual(g.state.players[1].mana, 9); self.assertFalse(discovered_cards(g.state, 1))
        self.assertNotIn(CONTROL, json.dumps(g.for_player(2).observe()))
        self.portable(g)
    def test_b01_picking_spell_creates_once_counts_once_and_has_two_real_unselected(self):
        g = self.game(); self.play(g); cid = g.state.pending_choice.options[0].card_id
        result = self.pick(g); row = discovered_cards(g.state, 1)[0]
        self.assertFalse(row.is_control); self.assertEqual(len(g.state.players[1].hand), 1)
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id, cid)
        self.assertEqual(sum(e.kind == 'card_discovered' for e in result.events), 1)
        self.assertEqual(len(unselected_materials(g, row.result)), 2)
        self.assertEqual(len(unselected_options(g, row.result)), 2); self.portable(g)
    def test_c00_miss_refresh_is_not_discovery_and_uses_one_risk_then_new_sample(self):
        g = self.game(); self.play(g)
        rng = random.Random(); rng.setstate(g._rng.getstate()); roll = rng.randrange(5)
        for size in (4, 3, 2): rng.randrange(size)
        old_choice = g.state.pending_choice.id; result = self.choose(g, 'refresh')
        self.assertNotEqual(roll, 0); self.assertEqual(g._rng.getstate(), rng.getstate())
        self.assertEqual(self.hp(g), 30); self.assertEqual(g.state.players[1].mana, 9)
        self.assertEqual(g.state.card_discovery_history[0].control_roll, roll)
        self.assertFalse(discovered_this_turn(g.state, 1)); self.assertFalse(capture_turn_match(g.state, 1).matched)
        self.assertGreater(g.state.pending_choice.id, old_choice)
        self.assertFalse(any(e.kind == 'card_discovered' for e in result.events)); self.portable(g)
    def test_c01_hit_takes_exact_five_without_spell_damage_bonus(self):
        g = self.game(seed=risk_seed(True), board=('EX1_012',)); self.play(g); result = self.choose(g, 'refresh')
        self.assertEqual(g.state.card_discovery_history[0].control_roll, 0)
        self.assertEqual(self.hp(g), 25)
        self.assertEqual([e.amount for e in result.events if e.kind == 'damage_dealt'], [5]); self.portable(g)
    def test_c02_repeated_refresh_keeps_single_spell_payment_and_only_final_discovery(self):
        g = self.game(); self.play(g)
        for _ in range(3): self.choose(g, 'refresh')
        self.assertFalse(discovered_cards(g.state, 1)); self.assertFalse(g.state.players[1].hand)
        self.pick(g); self.assertEqual(len(g.state.card_discovery_history), 4)
        self.assertEqual(len(discovered_cards(g.state, 1)), 1); self.assertEqual(g.state.players[1].mana, 9)
        self.assertTrue(capture_turn_match(g.state, 1).matched)
        self.assertEqual(sum(x.card_id == ROOT for x in g.state.cast_history), 1); self.portable(g)
    def test_d00_armor_and_immunity_use_ordinary_health_pipeline(self):
        for mode, hp in (('armor', 28), ('immune', 30)):
            with self.subTest(mode=mode):
                g = self.game(mode=mode, seed=risk_seed(True), hand=(P+'setup', ROOT))
                self.play(g, P+'setup'); self.play(g); self.choose(g, 'refresh')
                self.assertEqual(self.hp(g), hp); self.assertIsNotNone(g.state.pending_choice); self.portable(g)
    def test_d01_lethal_risk_stops_without_refresh_menu_or_fake_discovery(self):
        g = self.game(mode='lethal', seed=risk_seed(True), hand=(P+'setup', ROOT))
        self.play(g, P+'setup'); self.play(g); self.choose(g, 'refresh')
        self.assertNotEqual(g.state.status, 'playing'); self.assertIsNone(g.state.pending_choice)
        self.assertFalse(discovered_cards(g.state, 1)); self.assertFalse(g.state.players[1].hand); self.portable(g)
    def test_e00_selection_wait_accepts_risk_once_before_reactions_and_restores(self):
        g = self.game(mode='selection', seed=risk_seed(True)); self.play(g); self.choose(g, 'refresh')
        self.assertEqual(self.hp(g), 30); self.assertEqual(g.state.card_discovery_history[0].control_roll, 0)
        saved_rng = g._rng.getstate(); g = self.portable(g); self.assertEqual(g._rng.getstate(), saved_rng)
        self.choose(g, 'ok'); self.assertEqual(self.hp(g), 25); self.assertEqual(len(g.state.card_discovery_history), 1)
        self.assertEqual(g.state.pending_choice.options[-1].id, 'refresh'); self.portable(g)
    def test_e01_damage_wait_restore_finishes_original_damage_before_refresh(self):
        g = self.game(mode='damage', seed=risk_seed(True)); self.play(g); self.choose(g, 'refresh')
        self.assertEqual(self.hp(g), 25); g = self.portable(g)
        self.choose(g, 'heal'); self.assertEqual(self.hp(g), 30)
        self.assertEqual(g.state.pending_choice.options[-1].id, 'refresh'); self.portable(g)
    def test_e02_reaction_failure_restores_original_accepted_roll_rng_and_wait(self):
        g = self.game(mode='selection', seed=risk_seed(True)); self.play(g); self.choose(g, 'refresh')
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate rollback'): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before); self.portable(g)
        self.choose(g, 'ok'); self.assertEqual(self.hp(g), 25)
    def test_e03_card_created_wait_is_genuine_discovery_and_never_materializes_control(self):
        g = self.game(mode='created'); self.play(g); self.choose(g, 'refresh'); self.pick(g)
        self.assertEqual(len(discovered_cards(g.state, 1)), 1); g = self.portable(g)
        self.choose(g, 'ok'); self.assertFalse(any(e.card_id == CONTROL for e in g.state.entities.values()))
        self.assertIsNone(g.state.pending_choice); self.portable(g)
    def test_f00_unknown_eligible_spell_fails_before_sampling_and_rolls_back_payment(self):
        g = self.game(pool_mode='unknown'); before = g.snapshot()
        with self.assertRaises(ResolutionError) as caught: self.play(g)
        self.assertIn(P+'unknown', str(caught.exception)); self.assertEqual(g.snapshot(), before); self.portable(g)
    def test_f01_empty_pool_has_no_refresh_no_fact_and_no_rng(self):
        g = self.game(pool_mode='empty'); before = g._rng.getstate(); self.play(g)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g._rng.getstate(), before)
        self.assertFalse(g.state.card_discovery_history); self.portable(g)
    def test_f02_short_pool_keeps_one_actual_spell_and_one_control(self):
        g = self.game(pool_mode='short'); self.play(g)
        self.assertEqual(len(g.state.pending_choice.options), 2); self.pick(g)
        row = discovered_cards(g.state, 1)[0]; self.assertEqual(unselected_materials(g, row.result), ())
        self.portable(g)
    def test_f03_countered_spell_spends_once_without_menu_or_risk(self):
        g = self.game(mode='counter'); before = g._rng.getstate(); self.play(g)
        self.assertIsNone(g.state.pending_choice); self.assertFalse(g.state.card_discovery_history)
        self.assertEqual(g.state.players[1].mana, 9); self.assertEqual(g._rng.getstate(), before); self.portable(g)
    def test_f04_full_hand_burn_is_still_one_genuine_discovery(self):
        g = self.game(mode='fill', hand=(ROOT,)+(FILL,)*9); self.play(g); self.pick(g)
        row = discovered_cards(g.state, 1)[0]; cid = row.result.selected[0].card_id
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertTrue(any(e.card_id == cid and e.zone == Zone.GRAVEYARD for e in g.state.entities.values()))
        self.portable(g)
    def test_g00_automatic_original_cast_preserves_control_receipts_and_portability(self):
        g = self.game(hand=(ROOT, P+'cast')); root = g.state.players[1].hand[0]
        self.play(g, P+'cast', root)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(len(discovered_cards(g.state, 1)), 1)
        self.assertEqual(g.state.players[1].mana, 10); self.portable(g)
    def test_g01_refresh_cannot_be_a_card_producer_or_original_unselected_execution(self):
        from hs_sim.engine.offered_card_selection import capture
        g = self.game(); self.play(g); self.choose(g, 'refresh'); row = g.state.card_discovery_history[0]
        with self.assertRaises(ValueError): require_original_result(g.state, row.result)
        self.assertEqual(require_original_result(g.state, row.result, control=True), row)
        with self.assertRaises(ValueError): capture(g.state, g.registry, row.id, g._rng.getstate())
        with self.assertRaises(ValueError): unselected_materials(g, row.result)
    def test_g02_real_discovery_after_refresh_has_exactly_three_executable_card_slots(self):
        from hs_sim.engine.offered_card_selection import capture, validate_origin
        g = self.game(); self.play(g); self.choose(g, 'refresh'); self.pick(g)
        row = discovered_cards(g.state, 1)[0]
        selection = capture(g.state, g.registry, row.id, g._rng.getstate())
        validate_origin(selection, g.state, g.registry)
        self.assertEqual(len(selection.rows), 3); self.assertEqual(len(selection.selected_ids), 2)
        self.assertNotIn(CONTROL, [slot.card_id for slot in selection.rows]); self.portable(g)
    def test_g03_real_storage_scuffle_discount_remains_off_until_actual_spell_selection(self):
        from hs_sim.engine.costs import quote_cost
        g = self.game(hand=(ROOT, DISCOUNT)); eid = g.state.players[1].hand[1]
        printed = g.registry.card(DISCOUNT).cost
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[eid]).amount, printed)
        self.play(g); self.choose(g, 'refresh')
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[eid]).amount, printed)
        self.pick(g); self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[eid]).amount, 0)
        self.portable(g)
    def test_h00_finite_refresh_declaration_rejects_unrelated_recipe_shapes(self):
        spec = DiscoverFromPool(1, POOL, PoolQuery(kinds=(CardType.SPELL,), collectible=True),
            source_id=1, refresh_card_id=CONTROL)
        for change in ({'source_id': None}, {'count': 2}, {'discoveries': 2}, {'destination': 'deck_top'},
                       {'query': PoolQuery(kinds=(CardType.MINION,), collectible=True)},
                       {'paired_choose_one': True}, {'cost': CostSpec(set_to=0)}):
            with self.subTest(change=change), self.assertRaises(ValueError): replace(spec, **change)
    def test_h01_rehashed_roll_control_classification_and_old_schema_are_rejected(self):
        g = self.game(mode='selection'); self.play(g); self.choose(g, 'refresh')
        original = g.snapshot()
        for field, value in (('control_roll', 5), ('control_roll', None)):
            with self.subTest(field=field, value=value):
                bad = deepcopy(original); bad['state']['card_discovery_history'][0][field] = value
                bad['events_hash'] = canonical_hash(bad['events'])
                bad['state_hash'] = canonical_hash({k: v for k, v in bad.items()
                    if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
                with self.assertRaises(SnapshotError): Game.from_snapshot(bad, g.registry)
        bad = deepcopy(original); bad['schema_version'] = SNAPSHOT_SCHEMA_VERSION - 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, g.registry)


if __name__ == '__main__': unittest.main()
