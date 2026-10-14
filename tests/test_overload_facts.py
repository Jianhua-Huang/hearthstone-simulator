"""Actual overload increments and Sapphire's independent hand progression."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, EndTurn, Game, HandProgressSpec,
    IllegalAction, PlayCard, PlayerSetup, Rarity, ResolutionError, Scenario, SelectChoice,
    SnapshotError, SpellSchool, SummonCause, TargetSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChangeManaCrystals, ChoiceOption, CopyMinion, Damage,
    GainTemporaryMana, Overload, RefreshMana, RequestChoice, SetManaCap, UnlockOverload)
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.information import Information
from hs_sim.engine.model import DamageKind
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import AddToDeck, CardReference, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry


BASE, MID, MAXIMUM, BOLT = 'LOOT_064', 'LOOT_064t1', 'LOOT_064t2', 'EX1_238'
PIN = '3eae258dcbfaadb114ea94663a2d480ec7e49a41309437519cc1855ed00c1696'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/overload-facts.json'


def evidence():
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(data) != PIN:
        raise ValueError('Complete Sapphire/Bolt evidence changed')
    for row in data['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Complete original card evidence changed')
    return {row['id']: row['data'] for row in data['records']}


def registry(scripts=(), *, bad_condition=False, choice_probe=False, fail_completion=False):
    r = opening_registry(); rows = evidence()
    condition = 'sapphire.overload.owner'
    r.register_trigger_condition(condition, (lambda c: 'invalid') if bad_condition else
        lambda c: c.event.player_id == c.player_id)
    for cid, count, following in ((MAXIMUM, 3, None), (MID, 2, MAXIMUM), (BASE, 1, MID)):
        r.register_behavior('sapphire.' + cid, lambda c, n=count:
            tuple(CopyMinion(c.target_id, c.player_id, cause=SummonCause.capture(c)) for _ in range(n)))
        spec = (HandProgressSpec('event', 3, following, event='overload_added', condition_id=condition,
            amount_basis='event_amount', upgrade_cost_policy='clear_local') if following else None)
        r.register_card(CardDefinition(cid, rows[cid]['name'], CardType.SPELL, cost=rows[cid]['cost'],
            on_play='sapphire.' + cid, hand_progress=spec, spell_school=SpellSchool.NATURE,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='friendly'),
            metadata=metadata(CardClass.SHAMAN, rarity=Rarity.RARE, collectible=cid == BASE)))
    # Match the existing representative's explicit resource/damage ordering.
    r.register_behavior('sapphire.bolt', lambda c:
        (Overload(c.player_id, 1), Damage(c.target_id, 3, c.source_id, DamageKind.SPELL)))
    r.register_card(CardDefinition(BOLT, rows[BOLT]['name'], CardType.SPELL, cost=rows[BOLT]['cost'],
        on_play='sapphire.bolt', targeting=TargetSpec(), spell_school=SpellSchool.NATURE,
        metadata=metadata(CardClass.SHAMAN, rarity=Rarity.COMMON)))
    r.register_card(CardDefinition('probe.unit', 'Resource test unit', CardType.MINION,
        attack=2, health=4, metadata=metadata()))
    if choice_probe or fail_completion:
        def completion(c):
            if fail_completion:
                raise ResolutionError('Deliberate resource completion failure')
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue', ()),), c.source_id),)
        r.register_behavior('probe.complete', completion)
        r.register_behavior('probe.noop', lambda c: ())
        r.register_card(CardDefinition('probe.counter', 'Overload fact probe', CardType.SPELL,
            on_play='probe.noop', hand_progress=HandProgressSpec('event', 3,
                on_complete='probe.complete', event='overload_added', condition_id=condition,
                amount_basis='event_amount'), metadata=metadata()))
    for name, callback, cost in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=cost, on_play=name, metadata=metadata()))
    return r


class OverloadFactTests(unittest.TestCase):
    def setUp(self):
        self.scripts = []; self.options = {}

    def script(self, name, callback, cost=0):
        self.scripts.append((name, callback, cost))

    def overload(self, name, amount, player=1):
        self.script(name, lambda c: (Overload(player, amount),))

    def game(self, hand=(BASE,), deck=(), enemy_hand=(), board=(), enemy_board=(), owed=0, locked=0):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, deck=deck, board=board, max_mana=10,
                mana=max(0, 10-locked), overload_owed=owed, overload_locked=locked),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy_board, deck=('card.1',)*8,
                max_mana=10, mana=10)), seed=64), registry(self.scripts, **self.options))

    def entity(self, g, card=BASE, player=1, zone=Zone.HAND):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone.value)
            if g.state.entities[i].card_id == card)

    def progress(self, g, card=BASE, player=1):
        return progress_ability(self.entity(g, card, player))

    def play(self, g, card, target=None):
        source = self.entity(g, card, g.state.active_player).id
        g.apply(PlayCard(g.state.active_player, source, target)); return source

    def events(self, g):
        return [e for e in g.events if e.kind == 'overload_added']

    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(snap, registry(self.scripts, **self.options))
        self.assertEqual(restored.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, **self.options)).snapshot(), snap)
        return restored

    def test_complete_raw_and_real_three_form_declarations(self):
        rows = evidence(); r = registry()
        self.assertEqual(set(rows), {BASE, MID, MAXIMUM, BOLT})
        for cid in (BASE, MID, MAXIMUM):
            d = r.card(cid)
            self.assertEqual((d.name, d.cost, d.kind, d.metadata.classes),
                (rows[cid]['name'], 7, CardType.SPELL, (CardClass.SHAMAN,)))
            self.assertEqual(d.spell_school, SpellSchool.NATURE)
        self.assertEqual(r.card(BASE).hand_progress.event_kind, 'overload_added')
        self.assertIsNone(r.card(MAXIMUM).hand_progress)

    def test_actual_pending_increment_is_not_available_mana_delta(self):
        self.overload('owed', 2); g = self.game(hand=('owed', BASE)); self.play(g, 'owed')
        event, = self.events(g)
        self.assertEqual((event.amount, event.player_id, dict(event.data)),
            (2, 1, dict(pending_before=0, pending_after=2)))
        mana = next(e for e in g.events if e.kind == 'mana_changed')
        self.assertEqual(mana.amount, 0); self.assertLess(mana.sequence, event.sequence)
        self.assertEqual((g.state.players[1].mana, self.progress(g).progress_value), (10, 2))
        self.portable(g)

    def test_prior_pending_balance_does_not_inflate_new_increment(self):
        self.overload('owed', 1); g = self.game(hand=('owed', BASE), owed=8); self.play(g, 'owed')
        event, = self.events(g); self.assertEqual((event.amount, dict(event.data)),
            (1, dict(pending_before=8, pending_after=9)))
        self.assertEqual(self.progress(g).progress_units, (1,)); self.portable(g)

    def test_scenario_pending_and_locked_amounts_are_not_new_facts(self):
        g = self.game(owed=7, locked=4)
        self.assertEqual(self.events(g), []); self.assertEqual(self.progress(g).progress_value, 0)
        self.portable(g)

    def test_three_units_from_two_events_upgrade_once(self):
        self.overload('two', 2); self.overload('one', 1)
        g = self.game(hand=('two', 'one', BASE)); self.play(g, 'two'); self.play(g, 'one')
        a = self.progress(g, MID); self.assertEqual((a.progress_value, a.progress_units), (0, (2, 1)))
        self.assertEqual([e.amount for e in self.events(g)], [2, 1]); self.portable(g)

    def test_large_increment_cannot_skip_tier_or_carry_excess(self):
        self.overload('many', 8); self.overload('one', 1)
        g = self.game(hand=('many', 'one', BASE)); self.play(g, 'many')
        self.assertEqual((self.progress(g, MID).progress_value, self.progress(g, MID).progress_units), (0, (3,)))
        self.play(g, 'one'); self.assertEqual(self.progress(g, MID).progress_value, 1); self.portable(g)

    def test_two_separate_large_events_upgrade_both_stages(self):
        self.overload('a', 6); self.overload('b', 6)
        g = self.game(hand=('a', 'b', BASE)); self.play(g, 'a'); self.play(g, 'b')
        a = self.progress(g, MAXIMUM)
        self.assertEqual((a.progress_completions, a.progress_units, a.consumed), (2, (3, 3), True))
        self.portable(g)

    def test_zero_overload_emits_no_new_increment_fact(self):
        self.overload('zero', 0); g = self.game(hand=('zero', BASE), owed=5); self.play(g, 'zero')
        self.assertEqual(self.events(g), []); self.assertEqual(self.progress(g).progress_keys, ())
        self.assertEqual(g.state.players[1].overload_owed, 5); self.portable(g)

    def test_only_affected_players_held_card_counts(self):
        self.overload('enemy', 2, 2); g = self.game(hand=('enemy', BASE), enemy_hand=(BASE,))
        self.play(g, 'enemy')
        self.assertEqual(self.progress(g).progress_value, 0); self.assertEqual(self.progress(g, player=2).progress_value, 2)
        self.portable(g)

    def test_two_physical_hand_cards_count_independently(self):
        self.overload('owed', 2); g = self.game(hand=('owed', BASE, BASE)); self.play(g, 'owed')
        a, b = [progress_ability(g.state.entities[i]) for i in g.state.players[1].hand]
        self.assertNotEqual(a.id, b.id); self.assertEqual((a.progress_units, b.progress_units), ((2,), (2,)))
        self.portable(g)

    def test_scheduled_locking_is_not_another_overload_increment(self):
        self.overload('owed', 2); g = self.game(hand=('owed', BASE), deck=('card.1',)*8)
        self.play(g, 'owed'); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual((g.state.players[1].overload_owed, g.state.players[1].overload_locked), (0, 2))
        self.assertEqual((len(self.events(g)), self.progress(g).progress_value), (1, 2)); self.portable(g)

    def test_unlocking_does_not_count_and_later_gain_uses_new_balance(self):
        self.script('unlock', lambda c: (UnlockOverload(1),)); self.overload('one', 1)
        g = self.game(hand=('unlock', 'one', BASE), owed=8, locked=3); self.play(g, 'unlock')
        self.assertEqual(self.events(g), []); self.play(g, 'one')
        self.assertEqual(dict(self.events(g)[0].data), dict(pending_before=0, pending_after=1))
        self.assertEqual(self.progress(g).progress_units, (1,)); self.portable(g)

    def test_other_mana_operations_do_not_create_overload_facts(self):
        self.script('mana', lambda c: (GainTemporaryMana(1, 2), RefreshMana(1, 1),
            ChangeManaCrystals(1, -1), SetManaCap(1, 12), UnlockOverload(1, False)))
        g = self.game(hand=('mana', BASE), owed=5); self.play(g, 'mana')
        self.assertEqual(self.events(g), []); self.assertEqual(self.progress(g).progress_value, 0)
        self.portable(g)

    def test_obtained_before_actual_increment_counts(self):
        self.script('gain', lambda c: (AddToHand(1, BASE), Overload(1, 2)))
        g = self.game(hand=('gain',)); self.play(g, 'gain')
        self.assertEqual(self.progress(g).progress_units, (2,)); self.portable(g)

    def test_obtained_after_increment_does_not_retroactively_count(self):
        self.script('gain', lambda c: (Overload(1, 2), AddToHand(1, BASE)))
        g = self.game(hand=('gain',)); self.play(g, 'gain')
        self.assertEqual(self.progress(g).progress_keys, ()); self.portable(g)

    def test_deck_card_does_not_listen(self):
        self.overload('owed', 3); g = self.game(hand=('owed',), deck=(BASE,)); self.play(g, 'owed')
        e = self.entity(g, zone=Zone.DECK)
        self.assertEqual((e.card_id, progress_ability(e).progress_units), (BASE, ())); self.portable(g)

    def test_nonreset_move_preserves_partial_progress_and_pauses_in_deck(self):
        self.overload('two', 2); self.overload('one', 1)
        def move(c, zone):
            entity = next(c.state.entities[i] for i in getattr(c.state.players[1], 'hand' if zone == Zone.DECK else 'deck')
                if c.state.entities[i].card_id == BASE)
            return (MoveCard(CardReference.capture(entity), 1, zone, position='bottom', reset=False),)
        self.script('out', lambda c: move(c, Zone.DECK)); self.script('back', lambda c: move(c, Zone.HAND))
        g = self.game(hand=('two', 'out', 'one', 'back', 'one', BASE))
        self.play(g, 'two'); self.play(g, 'out'); self.play(g, 'one'); self.play(g, 'back'); self.play(g, 'one')
        self.assertEqual(self.progress(g, MID).progress_units, (2, 1)); self.portable(g)

    def test_three_real_bolts_upgrade_then_mid_body_summons_two_copies(self):
        g = self.game(hand=(BOLT, BOLT, BOLT, BASE), board=('probe.unit',))
        for _ in range(3): self.play(g, BOLT, g.state.players[2].hero_id)
        self.assertEqual(self.progress(g, MID).progress_units, (1, 1, 1))
        self.assertEqual((g.state.players[1].overload_owed, g.state.players[1].mana), (3, 7))
        original = g.state.players[1].board[0]; self.play(g, MID, original)
        self.assertEqual(len(g.state.players[1].board), 3); self.assertEqual(g.state.players[1].mana, 0)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 21)
        self.assertEqual(len(set(g.state.players[1].board)), 3); self.portable(g)

    def test_printed_base_body_summons_one_copy(self):
        g = self.game(board=('probe.unit',)); self.play(g, BASE, g.state.players[1].board[0])
        self.assertEqual(len(g.state.players[1].board), 2); self.portable(g)

    def test_printed_maximum_body_summons_three_copies(self):
        g = self.game(hand=(MAXIMUM,), board=('probe.unit',)); self.play(g, MAXIMUM, g.state.players[1].board[0])
        self.assertEqual(len(g.state.players[1].board), 4); self.portable(g)

    def test_enemy_target_is_rejected_before_payment(self):
        g = self.game(board=('probe.unit',), enemy_board=('probe.unit',)); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, BASE, g.state.players[2].board[0])
        self.assertEqual(g.snapshot(), before)

    def test_resource_completion_wait_restores_without_counting_again(self):
        self.options['choice_probe'] = True; self.overload('owed', 3)
        g = self.game(hand=('owed', 'probe.counter')); self.play(g, 'owed'); restored = self.portable(g)
        for game in (g, restored):
            pending = game.state.pending_choice
            game.apply(SelectChoice(pending.player_id, pending.id, ('ok',)))
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual((len(self.events(g)), self.progress(g, 'probe.counter').progress_units), (1, (3,)))
        self.portable(g)

    def test_public_fact_exposes_amount_without_private_receipts(self):
        self.overload('owed', 2); g = self.game(hand=('owed', BASE)); self.play(g, 'owed')
        for player in (1, 2):
            event, = [e for e in g.player_events(player) if e['kind'] == 'overload_added']
            self.assertEqual((event['player_id'], event['amount'], event['source'], event['target']), (1, 2, None, None))
            for key in ('pending_before', 'pending_after', 'progress_units', 'progress_keys'):
                self.assertNotIn(key, event)
            self.assertEqual(g.observe(player)['version'], 'player-view-v84')
        self.assertFalse(any(e['kind'] in ('hand_progressed', 'hand_card_upgraded') for e in g.player_events(2)))
        self.portable(g)

    def test_invalid_public_fact_amount_or_player_is_rejected(self):
        self.overload('owed', 1); g = self.game(hand=('owed', BASE)); self.play(g, 'owed')
        for changes in (dict(amount=0), dict(amount=-1), dict(amount=True), dict(player_id=None)):
            info = deepcopy(g.snapshot()['information'])
            event = next(e for e in info['players']['1']['events'] if e['kind'] == 'overload_added')
            event.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError): Information.from_dict(info, g)

    def test_condition_failure_rolls_back_resource_mana_and_rng(self):
        self.options['bad_condition'] = True
        self.script('bad', lambda c: (AddToDeck(1, 'card.1'), Overload(1, 2)), cost=1)
        g = self.game(hand=('bad', BASE)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'bad')
        self.assertEqual(g.snapshot(), before)

    def test_completion_failure_rolls_back_actual_increment(self):
        self.options['fail_completion'] = True; self.overload('owed', 3)
        g = self.game(hand=('owed', 'probe.counter')); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'owed')
        self.assertEqual(g.snapshot(), before)

    def test_schema_rejects_old_future_and_boolean(self):
        g = self.game(); self.assertEqual(g.snapshot()['schema_version'], 265)
        for version in (1, 159, 160, 161, 162, 217, True):
            bad = g.snapshot(); bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())
