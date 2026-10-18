"""Actual Petrified Ogre, captured dormant self-growth and ordinary lifecycle."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_dormant_growth_cards import CARD, BODY, load_batch, register_native_dormant_growth_cards
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction,
    LimitedTriggerSpec, PlayCard, PlayerSetup, Registry, Scenario, SelectChoice, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.dormancy import AwakenMinion, GrowDormantMinion, MakeDormant
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference
from hs_sim.engine.turn_scheduling import QueueTurns, SkipTurns

P = 'k179.'
HERO, FILL = P + 'hero', P + 'filler'


def ogre(c):
    return next(c.state.entities[i] for i in c.state.players[c.player_id].board
                if c.state.entities[i].card_id == CARD)


def growth(e):
    return GrowDormantMinion(MinionReference.capture(e), e.dormancy.id, 2, 2)


@lru_cache(maxsize=2)
def registry(role='writer'):
    r = Registry('k179-dormant-growth')
    register_native_dormant_growth_cards(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=80))
    r.register_card(CardDefinition(FILL, FILL, CardType.MINION, attack=1, health=4))

    def external(c):
        e = ogre(c)
        return (Buff(e.id, 9, 9, c.source_id),
                BuffCapturedMinion(MinionReference.capture(e), 9, 9, c.source_id))

    def wait_grow(c):
        e = ogre(c)
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),), c.source_id), growth(e))

    def stale(c, mode):
        e = ogre(c)
        old = growth(e)
        wake = AwakenMinion(e.id, c.source_id)
        if mode == 'active':
            return (wake, old)
        if mode == 'resleep':
            return (wake, MakeDormant(e.id, None, c.source_id), old)
        if mode == 'transform':
            return (wake, Transform(e.id, FILL), Transform(e.id, CARD), old)
        if mode == 'control':
            return (wake, ChangeControl(e.id, 3-c.player_id), MakeDormant(e.id, None, c.source_id), old)
        if mode == 'leave':
            return (wake, ReturnToHand(e.id), old)
        raise AssertionError('Unknown fixture')

    scripts = dict(
        external=external, wait_grow=wait_grow,
        wake=lambda c: (AwakenMinion(ogre(c).id, c.source_id),),
        sleep=lambda c: (MakeDormant(ogre(c).id, None, c.source_id),),
        silence=lambda c: (Silence(ogre(c).id),),
        damage=lambda c: (Damage(ogre(c).id, 2, c.source_id),),
        bounce=lambda c: (ReturnToHand(ogre(c).id),),
        transform=lambda c: (Transform(ogre(c).id, CARD),),
        copy=lambda c: (CopyMinion(ogre(c).id, c.player_id, allow_dormant=True),),
        base=lambda c: (CopyMinion(ogre(c).id, c.player_id, mode='base', allow_dormant=True),),
        extra=lambda c: (QueueTurns((c.player_id,), c.source_id),),
        skip=lambda c: (SkipTurns(c.player_id, source_id=c.source_id),))
    for mode in ('active', 'resleep', 'transform', 'control', 'leave'):
        scripts['stale_' + mode] = lambda c, mode=mode: stale(c, mode)
    for name, handler in scripts.items():
        r.register_behavior(P + name, handler)
        r.register_card(CardDefinition(P + name, P + name, CardType.SPELL, on_play=P + name))

    def fail(c):
        raise ResolutionError('k179 actual reaction failure')

    r.register_behavior(P + 'fail', fail)
    for name, event in (('wait_start', 'turn_started'), ('wait_growth', 'stats_changed'),
                        ('wait_awake', 'minion_awakened'), ('fail_growth', 'stats_changed'),
                        ('fail_awake', 'minion_awakened')):
        def condition(c, name=name):
            if name == 'wait_start':
                return c.event.player_id == c.player_id
            target = c.state.entities.get(c.event.target_id)
            return target is not None and target.card_id == CARD and target.controller == c.player_id

        def watch(c, name=name):
            if name.startswith('fail_'):
                return (InvokeBehavior(P + 'fail', c.source_id, c.player_id),)
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),), c.source_id),)

        r.register_trigger_condition(P + name, condition)
        r.register_behavior(P + name, watch)
        r.register_card(CardDefinition(P + name, P + name, CardType.MINION, attack=1, health=4,
            limited_triggers=(LimitedTriggerSpec(event, P + name, condition_id=P + name),)))
    r.validate()
    r.freeze()
    return r


def game(seed=1, board=(CARD,), hand=(), enemy=()):
    return Game.from_scenario(Scenario((
        PlayerSetup(HERO, board=board, hand=hand, deck=(FILL,)*20, mana=40, max_mana=40, mana_cap=40),
        PlayerSetup(HERO, board=enemy, deck=(FILL,)*20, mana=40, max_mana=40, mana_cap=40)), seed=seed), registry())


def unit(g, player=1):
    return next(g.state.entities[i] for i in g.state.players[player].board
                if g.state.entities[i].card_id == CARD)


def play(g, cid):
    p = g.state.active_player
    e = next(g.state.entities[i] for i in g.state.players[p].hand if g.state.entities[i].card_id == cid)
    g.apply(PlayCard(p, e.id, position=len(g.state.players[p].board) if e.kind == CardType.MINION else None))
    return e.id


def cycle(g):
    g.apply(EndTurn(1))
    g.apply(EndTurn(2))


def select(g):
    q = g.state.pending_choice
    g.apply(SelectChoice(q.player_id, q.id, ('ok',)))


class NativeDormantGrowthTests(unittest.TestCase):
    def portable(self, g):
        saved = g.snapshot()
        reader = registry('reader')
        self.assertIsNot(reader, g.registry)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)), reader).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for pid in (1, 2):
            visible = json.dumps(g.observe(pid)) + json.dumps(g.player_events(pid)) + json.dumps(g.for_player(pid).legal_actions())
            for key in ('dormancy_id', 'reference', 'rng_state', 'resolution_frame', 'source_guard'):
                self.assertNotIn('"' + key + '"', visible)

    def test_01_complete_raw_and_strict_bilingual_faces(self):
        from tools.card_batch import check_face
        batch = load_batch()
        raw = batch['cards'][0]['record']
        for face in batch['official_observations']:
            check_face(raw, face['face'], face['locale'])
        d = registry().card(CARD)
        self.assertEqual((d.cost, d.attack, d.health, d.dormant_turns), (3, 5, 5, None))
        self.assertFalse(d.permanent_dormancy)
        self.assertIsNone(d.battlecry)
        self.assertEqual([(t.event, t.behavior_id) for t in d.dormant_triggers], [('turn_started', BODY)])

    def test_02_actual_paid_play_starts_original_body_indefinitely_dormant(self):
        g = game(board=(), hand=(CARD,))
        original = g.state.players[1].hand[0]
        self.assertIsNone(g.state.entities[original].dormancy)
        self.assertEqual(play(g, CARD), original)
        e = unit(g)
        self.assertEqual((e.id, e.attack, e.max_health, g.state.players[1].mana), (original, 5, 5, 37))
        self.assertIsNone(e.dormancy.remaining_turns)
        self.assertIsNone(g.state.pending_choice)
        self.assertFalse(any(x.kind == 'choice_skipped' for x in g.events))
        self.portable(g)

    def test_03_opponent_start_does_not_roll_owner_start_grows_same_self(self):
        g = game()
        e = unit(g)
        before = (e.id, e.zone_epoch, e.entered_order, e.dormancy.id)
        rng = g.snapshot()['rng_state']
        g.apply(EndTurn(1))
        self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertEqual(unit(g).attack, 5)
        g.apply(EndTurn(2))
        e = unit(g)
        self.assertEqual((e.id, e.zone_epoch, e.entered_order, e.dormancy.id), before)
        self.assertEqual((e.attack, e.health, e.max_health), (7, 7, 7))
        self.assertEqual([(a.attack, a.health, a.source_id) for a in e.enchantments], [(2, 2, e.id)])
        self.assertNotEqual(g.snapshot()['rng_state'], rng)
        self.assertFalse(g.state.card_discovery_history)
        self.assertIsNone(g.state.pending_choice)
        self.portable(g)

    def test_04_repeated_owner_growth_uses_ordinary_ordered_attachments(self):
        g = game()
        cycle(g)
        cycle(g)
        e = unit(g)
        self.assertEqual((e.attack, e.health, e.max_health), (9, 9, 9))
        self.assertEqual(len(e.enchantments), 2)
        self.assertEqual(len({a.id for a in e.enchantments}), 2)
        self.assertIsNotNone(e.dormancy)
        self.portable(g)

    def test_05_wake_alternative_has_no_growth_and_stops_later_rolls(self):
        g = game(seed=0)
        e = unit(g)
        original = e.id
        cycle(g)
        self.assertIsNone(unit(g).dormancy)
        self.assertEqual((unit(g).id, unit(g).attack, unit(g).health), (original, 5, 5))
        self.assertFalse(unit(g).enchantments)
        self.assertEqual(sum(x.kind == 'minion_awakened' for x in g.events), 1)
        self.assertFalse(any(x.kind in ('minion_summoned', 'card_played', 'stats_changed') for x in g.events))
        with self.assertRaises(IllegalAction):
            g.apply(Attack(1, original, g.state.players[2].hero_id))
        rng = g.snapshot()['rng_state']
        cycle(g)
        self.assertEqual(g.snapshot()['rng_state'], rng)
        self.portable(g)

    def test_06_awaken_after_growth_keeps_stats_and_accumulated_damage(self):
        g = game(hand=(P+'wake', P+'damage', P+'sleep'))
        cycle(g)
        play(g, P+'wake')
        play(g, P+'damage')
        play(g, P+'sleep')
        cycle(g)
        self.assertEqual((unit(g).attack, unit(g).max_health, unit(g).health, unit(g).damage), (9, 9, 7, 2))
        self.portable(g)

    def test_07_external_ordinary_buffs_still_skip_dormant_targets(self):
        g = game(hand=(P+'external',))
        play(g, P+'external')
        self.assertEqual((unit(g).attack, unit(g).health), (5, 5))
        self.assertFalse(unit(g).enchantments)
        self.assertEqual(sum(x.kind == 'effect_skipped' for x in g.events), 2)

    def test_08_original_capture_cannot_grow_awake_or_replaced_dormancy(self):
        for mode in ('active', 'resleep'):
            with self.subTest(mode=mode):
                g = game(hand=(P+'stale_'+mode,))
                old = unit(g).dormancy.id
                play(g, P+'stale_'+mode)
                self.assertEqual(unit(g).attack, 5)
                self.assertFalse(unit(g).enchantments)
                if mode == 'resleep':
                    self.assertNotEqual(unit(g).dormancy.id, old)
                self.assertTrue(any(x.kind == 'effect_skipped' and dict(x.data)['effect'] == 'GrowDormantMinion' for x in g.events))
                self.portable(g)

    def test_09_original_capture_cannot_follow_transform_control_or_leave(self):
        for mode in ('transform', 'control', 'leave'):
            with self.subTest(mode=mode):
                g = game(hand=(P+'stale_'+mode,))
                eid = unit(g).id
                play(g, P+'stale_'+mode)
                e = g.state.entities[eid]
                self.assertEqual(e.attack, 5)
                self.assertFalse(e.enchantments)
                self.assertTrue(any(x.kind == 'effect_skipped' and dict(x.data)['effect'] == 'GrowDormantMinion' for x in g.events))
                if mode == 'leave':
                    self.assertEqual(e.zone, Zone.HAND)
                    play(g, CARD)
                    self.assertEqual((unit(g).attack, unit(g).health), (5, 5))
                self.portable(g)

    def test_10_current_dormant_copy_preserves_growth_with_independent_identity(self):
        g = game(hand=(P+'copy',))
        cycle(g)
        original = unit(g)
        play(g, P+'copy')
        copies = [g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual([(e.attack, e.health) for e in copies], [(7, 7), (7, 7)])
        self.assertNotEqual(copies[0].dormancy.id, copies[1].dormancy.id)
        self.assertNotEqual(copies[0].enchantments[0].id, copies[1].enchantments[0].id)
        self.assertEqual(copies[1].origin_entity_id, original.id)
        self.portable(g)

    def test_11_awake_current_copy_and_base_copy_follow_existing_printed_lifecycle(self):
        g = game(hand=(P+'wake', P+'copy', P+'base'))
        cycle(g)
        play(g, P+'wake')
        play(g, P+'copy')
        play(g, P+'base')
        copies = [g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual([e.attack for e in copies], [7, 7, 5])
        self.assertEqual([e.dormancy is not None for e in copies], [False, False, True])
        self.portable(g)

    def test_12_bounce_and_printed_transform_restart_fresh_five_five(self):
        for mode in ('bounce', 'transform'):
            with self.subTest(mode=mode):
                g = game(hand=(P+'wake', P+mode))
                cycle(g)
                old = unit(g).dormancy.id
                play(g, P+'wake')
                play(g, P+mode)
                if mode == 'bounce':
                    play(g, CARD)
                e = unit(g)
                self.assertEqual((e.attack, e.health), (5, 5))
                self.assertFalse(e.enchantments)
                self.assertNotEqual(e.dormancy.id, old)
                self.portable(g)

    def test_13_silence_removes_growth_and_native_dormant_trigger(self):
        g = game(hand=(P+'wake', P+'silence', P+'sleep'))
        cycle(g)
        play(g, P+'wake')
        play(g, P+'silence')
        play(g, P+'sleep')
        rng = g.snapshot()['rng_state']
        cycle(g)
        self.assertEqual((unit(g).attack, unit(g).health), (5, 5))
        self.assertIsNotNone(unit(g).dormancy)
        self.assertEqual(g.snapshot()['rng_state'], rng)
        self.portable(g)

    def test_14_extra_actual_owner_start_rolls_and_opponent_start_does_not(self):
        g = game(hand=(P+'extra',))
        play(g, P+'extra')
        g.apply(EndTurn(1))
        self.assertEqual(g.state.active_player, 1)
        self.assertEqual(unit(g).attack, 7)
        g.apply(EndTurn(1))
        self.assertEqual(g.state.active_player, 2)
        self.assertEqual(unit(g).attack, 7)
        g.apply(EndTurn(2))
        self.assertEqual(unit(g).attack, 9)
        self.portable(g)

    def test_15_skipped_owner_slot_does_not_roll_or_grant_growth(self):
        g = game(hand=(P+'skip',))
        play(g, P+'skip')
        g.apply(EndTurn(1))
        rng = g.snapshot()['rng_state']
        g.apply(EndTurn(2))
        self.assertEqual(g.state.active_player, 2)
        self.assertEqual(unit(g).attack, 5)
        self.assertEqual(g.snapshot()['rng_state'], rng)
        g.apply(EndTurn(2))
        self.assertEqual(unit(g).attack, 7)
        self.portable(g)

    def test_16_new_effect_pending_in_real_choice_is_portable_then_runs_once(self):
        g = game(hand=(P+'wait_grow',))
        play(g, P+'wait_grow')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(unit(g).attack, 5)
        self.assertIn('GrowDormantMinion', json.dumps(g.snapshot()))
        self.portable(g)
        saved = g.snapshot()
        reader = Game.from_snapshot(saved, registry('reader'))
        select(g)
        select(reader)
        self.assertEqual(g.snapshot(), reader.snapshot())
        self.assertEqual(unit(g).attack, 7)
        self.assertEqual(len(unit(g).enchantments), 1)
        self.portable(g)

    def test_17_real_turn_choice_can_suspend_before_native_coin_flip(self):
        g = game(board=(P+'wait_start', CARD))
        cycle(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(unit(g).attack, 5)
        self.portable(g)
        reader = Game.from_snapshot(g.snapshot(), registry('reader'))
        select(g)
        select(reader)
        self.assertEqual(g.snapshot(), reader.snapshot())
        self.assertEqual(unit(g).attack, 7)
        self.portable(g)

    def test_18_native_growth_and_wake_reactions_suspend_after_single_outcome(self):
        for seed, watcher in ((1, 'wait_growth'), (0, 'wait_awake')):
            with self.subTest(watcher=watcher):
                g = game(seed=seed, board=(CARD, P+watcher))
                cycle(g)
                self.assertIsNotNone(g.state.pending_choice)
                self.assertEqual(unit(g).attack, 7 if seed == 1 else 5)
                self.portable(g)
                reader = Game.from_snapshot(g.snapshot(), registry('reader'))
                select(g)
                select(reader)
                self.assertEqual(g.snapshot(), reader.snapshot())
                self.assertEqual(len(unit(g).enchantments), 1 if seed == 1 else 0)
                self.portable(g)

    def test_19_reaction_failure_rolls_back_original_turn_stats_dormancy_and_rng(self):
        for seed, watcher in ((1, 'fail_growth'), (0, 'fail_awake')):
            with self.subTest(watcher=watcher):
                g = game(seed=seed, board=(CARD, P+watcher))
                g.apply(EndTurn(1))
                saved = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'actual reaction failure'):
                    g.apply(EndTurn(2))
                self.assertEqual(g.snapshot(), saved)
                self.portable(g)

    def test_20_finite_positive_self_growth_codec_and_previous_schema_rejection(self):
        g = game()
        good = growth(unit(g))
        codec = FrameCodec(default_mechanics(), registry())
        self.assertEqual(codec.decode(codec.encode(good)), good)
        for kw in (dict(attack=-1), dict(health=True), dict(attack=0, health=0),
                   dict(dormancy_id=0), dict(reference=unit(g).id)):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                replace(good, **kw)
        saved = g.snapshot()
        saved['schema_version'] = 382
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, registry('reader'))
