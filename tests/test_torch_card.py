"""Torch's actual damage, retained value and original physical spell delivery."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry as assembled_registry
from hs_sim.cards.torch_card import ROOT, load_batch, register_torch_card
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction, Keyword,
    PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, GrantKeyword, InvokeBehavior,
    RandomDamage, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CostSpec, DamageKind, SpellRemainderDamageValue
from hs_sim.engine.native_spell_values import bound_value, public_value
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastStoredSpell
from hs_sim.engine.spent_spells import ReturnSpentSpell
from hs_sim.engine.stored_spell_damage import GrantStoredSpellDamage
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.zones import CardReference, CopyCard, ModifyStoredCost

P = 'torch.test.'
WOUND, SHIELD, COPY, BASE, DISCOUNT, BONUS, AUTO, FIRST, LAST, WATCH, BIG, HUGE = (
    P+x for x in ('wound', 'shield', 'copy', 'base', 'discount', 'bonus', 'auto', 'first', 'last', 'watch', 'big', 'huge'))
FILL = 'CS2_182'


@lru_cache(maxsize=None)
def registry(role, mode=None):
    assert role in ('writer', 'reader')
    r = build_registry(); register_torch_card(r); meta = replace(r.card(FILL).metadata, deck_identity=None)
    r.register_card(CardDefinition(BIG, BIG, CardType.MINION, attack=2, health=9, metadata=meta))
    r.register_card(CardDefinition(HUGE, HUGE, CardType.MINION, attack=2, health=12, metadata=meta))
    bodies = {
        WOUND: lambda c: (Damage(c.target_id, 1, c.source_id, DamageKind.EFFECT),),
        SHIELD: lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),),
        COPY: lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id,
            mode='current', source_id=c.source_id),),
        BASE: lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id,
            mode='base', source_id=c.source_id),),
        DISCOUNT: lambda c: (ModifyStoredCost(CardReference.capture(c.state.entities[c.target_id]),
            CostSpec(set_to=0), source_id=c.source_id),),
        BONUS: lambda c: (GrantStoredSpellDamage(CardReference.capture(c.state.entities[c.target_id]), 2, c.source_id),),
        AUTO: lambda c: (CastStoredSpell(CardReference.capture(c.state.entities[c.target_id]), c.player_id,
            c.source_id, target_id=next(i for i in c.state.players[3-c.player_id].board
                if c.state.entities[i].damage > 0), targeting='explicit'),),
    }
    def history(c, first):
        roots = tuple(p.id for p in c.state.play_history if p.id < c.play.id and p.card_id == ROOT)
        selected = roots[0] if first else roots[-1]
        query = WholeCardHistoryQuery(c.player_id, c.play.id, kinds=(CardType.SPELL,),
            exclude_play_ids=tuple(p.id for p in c.state.play_history if p.id < c.play.id and p.id != selected))
        return (ReplayWholeCards(c.player_id, c.source_id, query),)
    bodies[FIRST] = lambda c: history(c, True)
    bodies[LAST] = lambda c: history(c, False)
    for name, body in bodies.items():
        r.register_behavior(name, body)
        extra = {} if name in (FIRST, LAST) else {'targeting': TargetSpec(
            zones=(Zone.BOARD,) if name in (WOUND, SHIELD) else (Zone.HAND,),
            kinds=(CardType.MINION,) if name in (WOUND, SHIELD) else (CardType.SPELL,),
            relation='any' if name in (WOUND, SHIELD) else 'friendly')}
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=meta, **extra))
    def fail(c): raise ResolutionError('Torch deliberate rollback')
    r.register_behavior(P+'fail', fail)
    if mode:
        event = {'damage': 'damage_dealt', 'return': 'card_returned', 'death': 'minion_died',
                 'fill': 'spell_cast_started', 'counter': 'card_committed', 'prevent': 'spell_cast_started'}[mode]
        def watch(c):
            e = c.event; source = c.state.entities.get(e.source_id)
            if source is None or source.card_id != (FILL if mode == 'death' else ROOT): return ()
            if mode == 'fill': return (AddToHand(c.player_id, FILL, c.source_id), AddToHand(c.player_id, FILL, c.source_id))
            if mode == 'counter': return (CounterSpell(dict(e.data)['window_id']),)
            if mode == 'prevent': return (GrantKeyword(e.target_id, Keyword.IMMUNE, c.source_id),)
            options = [ChoiceOption('ok', 'Continue', ()), ChoiceOption('fail', 'Fail', (
                RandomDamage((c.state.players[2].hero_id,), 1, c.source_id), InvokeBehavior(P+'fail', c.source_id, c.player_id)))]
            if mode == 'damage':
                fact = SourceAllocationFact.capture(c.state, source)
                options.append(ChoiceOption('claim', 'Earlier original return', (ReturnSpentSpell(fact, c.player_id),)))
            return (RequestChoice(c.player_id, tuple(options), c.source_id),)
        r.register_behavior(WATCH, watch)
        r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=9,
            triggers=(TriggerSpec(event, WATCH),), metadata=meta))
    r.validate(); r.freeze(); return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class TorchTests(unittest.TestCase):
    def game(self, *, mode=None, hand=(ROOT, WOUND), board=(), enemy=(FILL, FILL, FILL), enemy_hand=()):
        self.mode = mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board+((WATCH,) if mode else ()),
                deck=(FILL,)*12, mana=10, max_mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy,
                deck=(FILL,)*12, mana=10, max_mana=10)), seed=241585), registry('writer', mode))
    def play(self, g, cid=ROOT, target=None, *, eid=None):
        pid = g.state.active_player
        eid = eid or next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        return g.apply(PlayCard(pid, eid, target))
    def wound(self, g, eid, count=1):
        for _ in range(count): self.play(g, WOUND, eid)
    def torch(self, g, pid=1):
        return next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == ROOT)
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; return g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g):
        r = registry('reader' if g.registry is registry('writer', self.mode) else 'writer', self.mode)
        s = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(s, r)
        for candidate in (other, g.clone(), replay(build_replay(g), r)): self.assertEqual(candidate.snapshot(), s)
        for pid in (1, 2):
            wire = json.dumps(g.for_player(pid).observe()) + json.dumps(g.for_player(pid).legal_actions()) + json.dumps(g.player_events(pid))
            for private in ('SpellRemainderDamageValue', 'spell_base_value', 'native_spell_value', 'resolution_frame', 'rng_state'):
                self.assertNotIn(private, wire)
        return other
    def test_a00_complete_primary_faces_and_printed_eight_fire_spell(self):
        from tools.card_batch import check_face
        data = load_batch(); raw = data['cards'][0]['record']; self.assertEqual(len(data['official_observations']), 2)
        for item in data['official_observations']:
            check_face(raw, item['face'], item['locale'], data['display_normalizations'][ROOT])
        self.assertEqual(registry('writer').card(ROOT), assembled_registry().card(ROOT))
        self.assertEqual(registry('writer').spell_value_profiles[ROOT].initial_amount, 8)
    def test_b00_only_damaged_minions_are_legal_and_initial_default_is_player_supported(self):
        g = self.game(); source = self.torch(g); target = g.state.players[2].board[0]
        self.assertFalse(g.legal_targets(source)); self.wound(g, target)
        self.assertEqual(g.legal_targets(source), (target,))
        listing = g.for_player(1).legal_actions(); self.assertIsNotNone(listing['actions'])
        before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, target=g.state.players[2].board[1])
        self.assertEqual(g.snapshot(), before)
    def test_b01_actual_eight_damage_returns_same_physical_spell_with_four_remaining(self):
        g = self.game(); source = self.torch(g); target = g.state.players[2].board[0]
        entry = g.state.entities[source].hand_entry_id; self.wound(g, target)
        result = self.play(g, target=target); self.assertEqual(self.torch(g), source)
        self.assertEqual(public_value(g.state.entities[source]), 4)
        self.assertNotEqual(g.state.entities[source].hand_entry_id, entry); self.assertEqual(g.state.players[1].mana, 9)
        self.assertEqual(g.state.hand_entries[g.state.entities[source].hand_entry_id-1].source_id, source)
        self.assertEqual([e.amount for e in result.events if e.kind == 'damage_dealt'], [8])
        self.assertEqual(sum(e.card_id == ROOT for e in g.state.entities.values()), 1); self.portable(g)
    def test_b02_equal_damage_and_nonlethal_damage_do_not_return(self):
        for cid, hp in ((BIG, 0), (HUGE, 3)):
            with self.subTest(cid=cid):
                g = self.game(enemy=(cid,)); source = self.torch(g); target = g.state.players[2].board[0]
                self.wound(g, target); self.play(g, target=target)
                self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
                self.assertEqual(g.state.entities[target].health, hp); self.portable(g)
    def test_c00_reused_spell_spends_only_remaining_four(self):
        g = self.game(hand=(ROOT, WOUND, WOUND)); first, second, _ = g.state.players[2].board
        source = self.torch(g); self.wound(g, first); self.play(g, target=first); self.wound(g, second)
        result = self.play(g, target=second)
        self.assertEqual([e.amount for e in result.events if e.kind == 'damage_dealt'], [4])
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD); self.assertEqual(g.state.players[1].mana, 8)
        self.portable(g)
    def test_c01_spell_damage_counts_in_remainder_and_applies_again_on_next_cast(self):
        g = self.game(hand=(ROOT, WOUND, WOUND), board=('EX1_012',)); source = self.torch(g)
        first, second, _ = g.state.players[2].board; self.wound(g, first); self.play(g, target=first)
        self.assertEqual(public_value(g.state.entities[source]), 5); self.wound(g, second)
        result = self.play(g, target=second)
        self.assertEqual([e.amount for e in result.events if e.kind == 'damage_dealt'], [6])
        self.assertEqual(public_value(g.state.entities[source]), 2); self.portable(g)
    def test_c02_original_local_spell_bonus_is_consumed_into_excess_then_reset_on_return(self):
        g = self.game(hand=(ROOT, WOUND, BONUS)); source = self.torch(g); target = g.state.players[2].board[0]
        self.play(g, BONUS, source); self.wound(g, target); self.play(g, target=target)
        self.assertEqual(public_value(g.state.entities[source]), 6)
        self.assertFalse(any(a.kind == 'spell_damage' for a in g.state.entities[source].abilities)); self.portable(g)
    def test_c03_divine_shield_and_post_acceptance_immunity_have_no_excess(self):
        for mode in (None, 'prevent'):
            with self.subTest(mode=mode):
                g = self.game(mode=mode, hand=(ROOT, WOUND, SHIELD)); source = self.torch(g); target = g.state.players[2].board[0]
                self.wound(g, target)
                if mode is None: self.play(g, SHIELD, target)
                self.play(g, target=target); self.assertEqual(g.state.entities[target].health, 4)
                self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD); self.assertIsNone(bound_value(g.state.entities[source]))
                self.portable(g)
    def test_d00_counter_spends_once_without_damage_or_return(self):
        g = self.game(mode='counter'); source = self.torch(g); target = g.state.players[2].board[0]
        self.wound(g, target); result = self.play(g, target=target)
        self.assertFalse(any(e.kind == 'damage_dealt' for e in result.events)); self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.players[1].mana, 9); self.portable(g)
    def test_d01_full_hand_burns_original_return_with_retained_value_without_new_card(self):
        g = self.game(mode='fill', hand=(ROOT, WOUND)+(FILL,)*8); source = self.torch(g)
        target = g.state.players[2].board[0]; self.wound(g, target)
        self.play(g, target=target)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertEqual(public_value(g.state.entities[source]), 4)
        self.assertEqual(sum(e.card_id == ROOT for e in g.state.entities.values()), 1)
        self.portable(g)
    def test_d02_return_resets_old_discount_and_keeps_only_new_native_remainder(self):
        g = self.game(hand=(ROOT, WOUND, DISCOUNT)); source = self.torch(g); target = g.state.players[2].board[0]
        self.play(g, DISCOUNT, source); self.wound(g, target); self.play(g, target=target)
        self.assertEqual(g.state.players[1].mana, 10); self.assertEqual(public_value(g.state.entities[source]), 4)
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[source]).amount, 1); self.portable(g)
    def test_e00_damage_wait_restores_before_same_original_return(self):
        g = self.game(mode='damage'); source = self.torch(g); target = g.state.players[2].board[0]
        self.wound(g, target); self.play(g, target=target); self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        g = self.portable(g); self.choose(g); self.assertEqual(self.torch(g), source)
        self.assertEqual(public_value(g.state.entities[source]), 4); self.portable(g)
    def test_e01_return_notification_wait_has_value_before_original_cast_finishes(self):
        g = self.game(mode='return'); source = self.torch(g); target = g.state.players[2].board[0]
        self.wound(g, target); self.play(g, target=target); self.assertEqual(public_value(g.state.entities[source]), 4)
        g = self.portable(g); self.choose(g); self.assertTrue(g.state.cast_history[-1].completed); self.portable(g)
    def test_e02_death_wait_keeps_same_original_spent_allocation(self):
        g = self.game(mode='death'); source = self.torch(g); target = g.state.players[2].board[0]
        self.wound(g, target); self.play(g, target=target); self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        g = self.portable(g); self.choose(g); self.assertEqual(self.torch(g), source); self.portable(g)
    def test_e03_failed_wait_rolls_back_damage_return_value_rng_and_private_state(self):
        for mode in ('damage', 'return'):
            with self.subTest(mode=mode):
                g = self.game(mode=mode); target = g.state.players[2].board[0]; self.wound(g, target); self.play(g, target=target)
                saved = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'deliberate rollback'): self.choose(g, 'fail')
                self.assertEqual(g.snapshot(), saved); self.portable(g)
    def test_e04_old_grave_allocation_cannot_modify_an_earlier_returned_same_spell(self):
        g = self.game(mode='damage'); source = self.torch(g); target = g.state.players[2].board[0]
        self.wound(g, target); self.play(g, target=target); self.choose(g, 'claim')
        self.assertEqual(self.torch(g), source); self.assertIsNone(bound_value(g.state.entities[source]))
        self.assertEqual(sum(e.card_id == ROOT for e in g.state.entities.values()), 1); self.portable(g)
    def test_f00_current_copy_preserves_remainder_and_base_copy_uses_initial_default(self):
        g = self.game(hand=(ROOT, WOUND, COPY, BASE)); source = self.torch(g); target = g.state.players[2].board[0]
        self.wound(g, target); self.play(g, target=target); self.play(g, COPY, source); self.play(g, BASE, source)
        values = [public_value(g.state.entities[i]) for i in g.state.players[1].hand if g.state.entities[i].card_id == ROOT]
        self.assertEqual(values, [4, 4, None]); self.portable(g)
    def test_f01_automatic_stored_cast_returns_original_without_manual_payment(self):
        g = self.game(hand=(ROOT, WOUND, AUTO)); source = self.torch(g); target = g.state.players[2].board[0]
        self.wound(g, target); self.play(g, AUTO, source)
        self.assertEqual(self.torch(g), source); self.assertEqual(public_value(g.state.entities[source]), 4)
        self.assertEqual(g.state.players[1].mana, 10); self.portable(g)
    def test_f02_original_initial_play_history_keeps_eight_after_the_physical_card_changed(self):
        g = self.game(hand=(ROOT, WOUND, WOUND, FIRST)); first, second, _ = g.state.players[2].board
        self.wound(g, first); self.play(g, target=first); self.wound(g, second); self.play(g, FIRST)
        roots = [i for i in g.state.players[1].hand if g.state.entities[i].card_id == ROOT]
        self.assertEqual(len(roots), 2); self.assertEqual([public_value(g.state.entities[i]) for i in roots], [4, 4])
        self.portable(g)
    def test_f03_original_remainder_play_history_keeps_four_after_later_return_changed_it(self):
        g = self.game(hand=(ROOT, WOUND, WOUND, WOUND, WOUND, WOUND, LAST)); first, second, third = g.state.players[2].board
        self.wound(g, first); self.play(g, target=first); self.wound(g, second, 2); self.play(g, target=second)
        self.assertEqual(public_value(g.state.entities[self.torch(g)]), 1)
        self.wound(g, third, 2); self.play(g, LAST)
        roots = [i for i in g.state.players[1].hand if g.state.entities[i].card_id == ROOT]
        self.assertEqual(len(roots), 2); self.assertEqual([public_value(g.state.entities[i]) for i in roots], [1, 1])
        self.portable(g)
    def test_f04_second_caster_returns_to_its_actual_hand(self):
        g = self.game(board=(FILL,), enemy_hand=(ROOT, WOUND)); target = g.state.players[1].board[0]
        g.apply(EndTurn(1)); self.wound(g, target); source = self.torch(g, 2); self.play(g, target=target)
        self.assertEqual(self.torch(g, 2), source); self.assertEqual(public_value(g.state.entities[source]), 4); self.portable(g)
    def test_g00_rehashed_wrong_amount_source_records_missing_fields_and_old_schema_reject(self):
        g = self.game(); source = self.torch(g); target = g.state.players[2].board[0]; self.wound(g, target); self.play(g, target=target)
        original = g.snapshot()
        def value(saved):
            return next(a['spell_base_value'] for a in saved['state']['entities'][str(source)]['abilities'] if a['kind'] == 'spell_base_value')
        for field, data in (('amount', 5), ('cast_id', 99999), ('damage_id', 1)):
            with self.subTest(field=field):
                bad = deepcopy(original); value(bad)[field] = data
                with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), g.registry)
        bad = deepcopy(original); del value(bad)['damage_id']
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), g.registry)
        bad = deepcopy(original); bad['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, g.registry)
    def test_g01_pending_return_requires_actual_positive_damage_and_matching_active_cast(self):
        g = self.game(mode='damage'); source = self.torch(g); target = g.state.players[2].board[0]
        self.wound(g, target); self.play(g, target=target)
        cast = g.state.cast_history[-1]; damage_id = g.state.damage_history[-1].id
        fact = SourceAllocationFact.capture(g.state, g.state.entities[source])
        value = SpellRemainderDamageValue(ROOT, 4, cast.id, damage_id)
        ReturnSpentSpell(fact, 1, value).validate_in_state(g.state, g.registry)
        with self.assertRaises(ValueError): ReturnSpentSpell(fact, 1, replace(value, amount=5)).validate_in_state(g.state, g.registry)
        self.portable(g)


if __name__ == '__main__': unittest.main()
