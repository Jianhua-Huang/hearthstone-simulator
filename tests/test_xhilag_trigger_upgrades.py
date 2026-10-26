"""Xhilag's actual four Stalks retain ordinary physical +1 damage modifiers."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.xhilag_trigger_upgrades import CARD, PARTS, PROFILE, BODY, load_batch, register_xhilag_trigger_upgrades
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Enchantment, Game, PlayerSetup, ResolutionError, Scenario, SnapshotError, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Destroy,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon)
from hs_sim.engine.native_trigger_values import PREFIX, amount, marker_id
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k582.'
HERO, UNIT, WATCH = (P+x for x in ('hero', 'unit', 'watch'))
KILL, QUIET, COPY, BASE, HAND, ENEMY_HAND, BOUNCE, GIVE, SUMMON, TOUGH = (
    P+x for x in ('kill', 'silence', 'copy', 'base', 'hand', 'enemy-hand', 'bounce', 'give', 'summon', 'tough'))
SOURCE = 'CATA_EVENT_000'
CONTEXT = GenerationContext(P+'one-original-native-fixture', 'experimental')
META = CardMetadata(False, (CardClass.HUNTER,), None)


def value(r, e): return amount(r, e, 'cards.simple_followup_p75.stalk', 2)


@lru_cache(None)
def host(mode='normal', role='writer'):
    r = build_cn37_local_pool_format().registry
    r.register_pool(PoolDefinition('constructed.past.cards', P+'explicit-single-body:'+mode,
        CONTEXT.target_id, CONTEXT.mode, (PoolMember(CARD),), complete=True))
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=200, metadata=META))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=1, health=20, metadata=META))
    def fail(c): raise ResolutionError('K582 deliberate late upgrade failure')
    def redeploy(c):
        e = next(e for e in c.state.entities.values() if e.controller == c.player_id and e.zone == Zone.HAND and e.card_id == PARTS[-1])
        return (SummonStoredCard(CardReference.capture(e), c.player_id),)
    def watch(c):
        if c.event.kind != 'native_trigger_upgraded' or c.event.player_id != c.player_id: return ()
        total = sum(marker_id(e) == PROFILE for i in c.state.players[c.player_id].board
            for e in c.state.entities[i].enchantments)
        if mode == 'failure' and total == 3: return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        if mode == 'waiting' and total == 1:
            future = next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == PARTS[-1])
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'continue', ()),
                ChoiceOption('bad', 'fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
                ChoiceOption('move', 'return and replay original later target',
                    (ReturnToHand(future), InvokeBehavior(P+'redeploy', c.source_id, c.player_id))),
            ), c.source_id),)
        return ()
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'watch', watch); r.register_behavior(P+'redeploy', redeploy)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('native_trigger_upgraded', P+'watch'),)))
    scripts = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        QUIET: lambda c: (Silence(c.target_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id),),
        BASE: lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        HAND: lambda c: (CopyCard(MinionReference.capture(c.state.entities[c.target_id]), c.player_id, mode='current', source_id=c.source_id),),
        ENEMY_HAND: lambda c: (CopyCard(MinionReference.capture(c.state.entities[c.target_id]), 3-c.player_id, mode='current', source_id=c.source_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        GIVE: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        SUMMON: lambda c: (Summon(c.player_id, PARTS[0]),),
        TOUGH: lambda c: (Buff(c.target_id, health=20, source_id=c.source_id),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        spec = None if cid == SUMMON else TargetSpec(TargetMode.REQUIRED, zones=(Zone.BOARD,), kinds=(CardType.MINION,))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, targeting=spec, metadata=META))
    r.validate(); return r


def fixture(mode='normal', role='writer'): return host(mode, role)


class XhilagTriggerUpgradeTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)
    mode = 'normal'

    def game(self, hand=(), *, player=1, own=(), enemy=(), mode='normal'):
        self.mode = mode
        if mode != 'normal': own = (WATCH, *own)
        players = tuple(PlayerSetup(HERO, hero_power_card_id='HERO_05bp',
            hand=(SOURCE, *hand) if p == player else (), board=own if p == player else enemy,
            deck=(UNIT,)*12, mana=40, max_mana=40, mana_cap=40) for p in (1, 2))
        return Game.from_scenario(Scenario(players, active_player=player, seed=582,
            generation_context=CONTEXT), host(mode))

    def reward(self, g, player=1):
        self.play(g, SOURCE, player=player); return self.play(g, CARD, player=player)

    def stalks(self, g, player=1):
        return [g.state.entities[i] for i in g.state.players[player].board if g.state.entities[i].card_id in PARTS]

    def grow(self, g, player=1):
        g.apply(EndTurn(player)); rng = g._rng.getstate(); g.apply(EndTurn(3-player))
        self.assertEqual(g._rng.getstate(), rng)

    def damage_on_end(self, g, player=1):
        hero = g.state.players[3-player].hero_id; before = g.state.entities[hero].health
        g.apply(EndTurn(player)); return before-g.state.entities[hero].health

    def test_original_full_source_four_old_bodies_enchantment_and_bilingual_main_face(self):
        data = load_batch(); raw, = data['cards']
        for face in data['official_observations']: batch.check_face(raw['record'], face['face'], face['locale'])
        self.assertEqual(data['evidence_only'][0]['record']['type'], 'ENCHANTMENT')
        self.assertEqual(tuple(row['record']['id'] for row in data['existing_dependencies']), PARTS)
        self.assertEqual((data['initial_value'], data['increment']), (2, 1))
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_real_paid_parent_and_native_seven_mana_body_make_all_four_in_exact_positions(self):
        g = self.game(); self.reward(g)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],
            [SOURCE, PARTS[0], PARTS[1], CARD, PARTS[2], PARTS[3]])
        self.assertEqual(g.state.players[1].mana, 27)
        self.assertEqual([value(g.registry, e) for e in self.stalks(g)], [2]*4)
        self.assertEqual(self.damage_on_end(g), 8)

    def test_both_actors_only_actual_owner_starts_add_four_units_without_rng_and_real_damage_grows(self):
        for player in (1, 2):
            g = self.game(player=player); self.reward(g, player); self.grow(g, player)
            self.assertEqual([value(g.registry, e) for e in self.stalks(g, player)], [3]*4)
            self.assertEqual(self.damage_on_end(g, player), 12)
            g.apply(EndTurn(3-player)); self.assertEqual([value(g.registry, e) for e in self.stalks(g, player)], [4]*4)
            self.assertEqual(self.damage_on_end(g, player), 16)

    def test_parent_death_stops_future_upgrades_but_does_not_revoke_existing_stalk_modifiers(self):
        g = self.game((KILL,)); parent = self.reward(g); self.grow(g); self.play(g, KILL, parent)
        self.assertEqual(self.damage_on_end(g), 12); g.apply(EndTurn(2))
        self.assertEqual([value(g.registry, e) for e in self.stalks(g)], [3]*4)

    def test_existing_unrelated_friendly_stalk_counts_and_enemy_stalk_does_not_gain_our_upgrade(self):
        g = self.game((TOUGH, TOUGH), own=(PARTS[0],), enemy=(PARTS[1],))
        existing, enemy = self.stalks(g)[0].id, self.stalks(g, 2)[0].id
        self.play(g, TOUGH, existing); self.play(g, TOUGH, enemy); self.reward(g)
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(value(g.registry, g.state.entities[existing]), 3)
        self.assertGreaterEqual(len(self.stalks(g)), 4)
        self.assertTrue(all(value(g.registry, e) == 3 for e in self.stalks(g)))
        self.assertEqual([value(g.registry, e) for e in self.stalks(g, 2)], [2])

    def test_future_new_stalk_starts_at_printed_two_and_only_later_receives_its_own_upgrade(self):
        g = self.game((KILL, SUMMON)); self.reward(g); self.grow(g)
        self.play(g, KILL, self.stalks(g)[0].id); self.play(g, SUMMON)
        self.assertEqual(sorted(value(g.registry, e) for e in self.stalks(g)), [2, 3, 3, 3])
        self.assertEqual(self.damage_on_end(g), 11); g.apply(EndTurn(2))
        self.assertEqual(sorted(value(g.registry, e) for e in self.stalks(g)), [3, 4, 4, 4])

    def test_two_actual_parent_copies_each_add_one_unit_to_current_stalks(self):
        g = self.game((COPY,)); parent = self.reward(g); self.play(g, COPY, parent); self.grow(g)
        self.assertEqual(len(self.stalks(g)), 4)
        self.assertEqual([value(g.registry, e) for e in self.stalks(g)], [4]*4)
        self.assertEqual(self.damage_on_end(g), 16)

    def test_silenced_parent_stops_growth_and_silenced_stalk_never_restores_its_body(self):
        g = self.game((QUIET,)); parent = self.reward(g); self.play(g, QUIET, parent); self.grow(g)
        self.assertEqual([value(g.registry, e) for e in self.stalks(g)], [2]*4)
        h = self.game((QUIET,)); self.reward(h); self.grow(h); self.play(h, QUIET, self.stalks(h)[0].id)
        self.assertEqual(self.damage_on_end(h), 9); h.apply(EndTurn(2))
        self.assertEqual(self.damage_on_end(h), 12)

    def test_current_and_base_board_copies_preserve_or_reset_actual_end_turn_damage(self):
        for script, expected in ((COPY, 15), (BASE, 14)):
            g = self.game((script,)); self.reward(g); self.grow(g)
            self.play(g, script, self.stalks(g)[0].id)
            self.assertEqual(self.damage_on_end(g), expected)

    def test_actual_current_hand_copy_replays_number_and_return_to_hand_resets_it(self):
        g = self.game((HAND,)); self.reward(g); self.grow(g); self.play(g, HAND, self.stalks(g)[0].id)
        self.play(g, PARTS[0]); self.assertEqual(self.damage_on_end(g), 15)
        h = self.game((BOUNCE,)); self.reward(h); self.grow(h); self.play(h, BOUNCE, self.stalks(h)[0].id)
        self.play(h, PARTS[0]); self.assertEqual(self.damage_on_end(h), 11)

    def test_control_change_preserves_existing_number_and_uses_new_controller_targets(self):
        g = self.game((GIVE, TOUGH)); self.reward(g); self.grow(g); eid = self.stalks(g)[0].id
        self.play(g, TOUGH, eid)
        self.play(g, GIVE, eid); self.assertEqual(value(g.registry, g.state.entities[eid]), 3)
        self.damage_on_end(g); before = len(g.events); g.apply(EndTurn(2))
        hits = [e for e in g.events[before:] if e.kind == 'damage_dealt' and e.source_id == eid]
        self.assertEqual([(e.player_id, e.amount) for e in hits], [(1, 3)])

    def test_real_upgrade_wait_restores_clone_replay_and_rollback_then_all_remaining_original_targets(self):
        g = self.game(mode='waiting'); self.reward(g); self.grow(g)
        self.assertIsNotNone(g.state.pending_choice); before = g.snapshot(); restored = self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g, 'ok'); self.choose(restored, 'ok'); self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual([value(g.registry, e) for e in self.stalks(g)], [3]*4)

    def test_waiting_reentry_of_same_future_target_does_not_borrow_its_old_upgrade(self):
        g = self.game(mode='waiting'); self.reward(g); self.grow(g); self.choose(g, 'move')
        self.assertEqual(sorted(value(g.registry, e) for e in self.stalks(g)), [2, 3, 3, 3])

    def test_late_third_upgrade_failure_rolls_back_whole_opponent_end_and_owner_start(self):
        g = self.game(mode='failure'); self.reward(g); g.apply(EndTurn(1)); before = g.snapshot()
        with self.assertRaises(ResolutionError): g.apply(EndTurn(2))
        self.assertEqual(g.snapshot(), before)

    def test_visible_damage_for_both_board_viewers_and_own_hand_hides_enemy_hand_numbers_and_internal_markers(self):
        g = self.game((ENEMY_HAND,)); self.reward(g); self.grow(g); self.play(g, ENEMY_HAND, self.stalks(g)[0].id)
        for viewer in (1, 2):
            observed = g.observe(viewer); self.assertEqual(observed['version'], 'player-view-v119')
            own = observed['players'][0]
            self.assertEqual([e['end_turn_damage'] for e in own['board'] if e.get('card_id') in PARTS], [3]*4)
            text = json.dumps(observed)
            for key in (PREFIX, PROFILE, 'attachment_id', 'rng_state', 'resolution_frame'): self.assertNotIn(key, text)
        hidden = g.observe(1)['players'][1]['hand']
        self.assertFalse(any('end_turn_damage' in e for e in hidden))
        own = g.observe(2)['players'][1]['hand']
        self.assertEqual([e['end_turn_damage'] for e in own if e.get('card_id') in PARTS], [3])

    def test_marker_shape_unknown_profile_and_foreign_recipient_are_rejected_after_rehash(self):
        with self.assertRaises(ValueError): Enchantment(1, source_id=1, label=PREFIX+PROFILE, attack=1)
        with self.assertRaises(ValueError): Enchantment(1, label=PREFIX+PROFILE)
        g = self.game(); self.reward(g); self.grow(g); saved = g.snapshot()
        stalk = self.stalks(g)[0].id
        bad = deepcopy(saved); bad['state']['entities'][str(stalk)]['enchantments'][0]['label'] = PREFIX+'unknown'
        bad['state_hash'] = canonical_hash({k:v for k,v in bad.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaisesRegex(SnapshotError, '[Nn]ative trigger'):
            Game.from_snapshot(bad, fixture('normal', 'independent-reader'))
        bad = deepcopy(saved); parent = next(i for i in g.state.players[1].board if g.state.entities[i].card_id == CARD)
        bad['state']['entities'][str(parent)]['enchantments'] = bad['state']['entities'][str(stalk)]['enchantments']
        bad['state']['entities'][str(stalk)]['enchantments'] = []
        bad['state_hash'] = canonical_hash({k:v for k,v in bad.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaisesRegex(SnapshotError, '[Nn]ative trigger'):
            Game.from_snapshot(bad, fixture('normal', 'independent-reader'))

    def test_profile_overlap_and_late_old_stalk_change_do_not_create_partial_new_registration(self):
        r = build_registry(); p = r.trigger_value_profiles[PROFILE]
        with self.assertRaises(ValueError): r.register_trigger_value_profile(replace(p, id='overlapping'))
        del r._cards[CARD]; del r._pool_cards[CARD]; del r._behaviors[BODY]; del r._trigger_value_profiles[PROFILE]
        r._cards[PARTS[-1]] = replace(r.card(PARTS[-1]), attack=2)
        before = (dict(r.cards), dict(r.pool_cards), dict(r._behaviors), dict(r.trigger_value_profiles))
        with self.assertRaises(TargetValidationError): register_xhilag_trigger_upgrades(r)
        self.assertEqual((dict(r.cards), dict(r.pool_cards), dict(r._behaviors), dict(r.trigger_value_profiles)), before)


if __name__ == '__main__': unittest.main()
