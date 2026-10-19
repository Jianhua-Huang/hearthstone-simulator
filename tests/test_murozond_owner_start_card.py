"""Real paid Murozond, removable original-caster start grants and existing infinity."""
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.murozond_owner_start_card import CARD, PREFIX, INFINITE_ATTACK_VALUE, load_batch
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage, Destroy,
    InvokeBehavior, RequestChoice, ReturnToHand, SetStats, Silence, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.dormancy import MakeDormant, AwakenMinion
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.turn_scheduling import QueueTurns, SkipTurns
from hs_sim.targets import canonical_digest

P = 'murozond.start.test.'
FILL, OTHER = P + 'fill', P + 'other'
BUFF, QUIET, BOUNCE, KILL, CHANGE, CURRENT, BASE, STEAL, EXTRA, SKIP, WEAKEN = (
    P + x for x in ('buff', 'quiet', 'bounce', 'kill', 'change', 'current', 'base', 'steal', 'extra', 'skip', 'weaken'))
WATCH_START, WATCH_USED, FAIL_STATS = (P + x for x in ('watch_start', 'watch_used', 'fail_stats'))
SLEEP, WAKE = P + 'sleep', P + 'wake'


@lru_cache(maxsize=None)
def registry(role):
    assert role in ('writer', 'reader')
    r = build_registry()
    def source(c):
        return next(c.state.entities[i] for pid in (1, 2) for i in c.state.players[pid].board
            if c.state.entities[i].card_id == CARD)
    def buff(c):
        e = source(c)
        return (Buff(e.id, 5, 2, c.source_id), Damage(e.id, 3, c.source_id))
    scripts = {
        FILL: lambda c: (), BUFF: buff, QUIET: lambda c: (Silence(source(c).id),),
        BOUNCE: lambda c: (ReturnToHand(source(c).id),), KILL: lambda c: (Destroy(source(c).id, c.source_id),),
        CHANGE: lambda c: (Transform(source(c).id, OTHER),),
        CURRENT: lambda c: (CopyMinion(source(c).id, c.player_id),),
        BASE: lambda c: (CopyMinion(source(c).id, c.player_id, mode='base'),),
        STEAL: lambda c: (ChangeControl(source(c).id, c.player_id),),
        EXTRA: lambda c: (QueueTurns((c.player_id,), c.source_id),),
        SKIP: lambda c: (SkipTurns(c.player_id, 1, c.source_id),),
        WEAKEN: lambda c: (SetStats(source(c).id, attack=4, source_id=c.source_id),),
        SLEEP: lambda c: (MakeDormant(source(c).id, None, c.source_id),),
        WAKE: lambda c: (AwakenMinion(source(c).id, c.source_id),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body); r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    r.register_card(CardDefinition(OTHER, OTHER, CardType.MINION, attack=2, health=4))
    def fail(c):
        raise ResolutionError('Deliberate Murozond reaction failure')
    r.register_behavior(P + 'fail', fail)
    def options(c):
        return RequestChoice(1, (ChoiceOption('ok', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P + 'fail', c.source_id, c.player_id),))), c.source_id)
    def watch(c, mode):
        if mode == 'start':
            if c.event.player_id != 1: return ()
            bodies = [c.state.entities[i] for i in c.state.players[1].board
                if c.state.entities[i].card_id == CARD]
            if not bodies or not any(a.kind == 'limited_trigger' and not a.consumed for a in bodies[0].abilities): return ()
        else:
            e = c.state.entities.get(c.event.source_id if mode == 'used' else c.event.target_id)
            if e is None or e.card_id != CARD: return ()
            if mode == 'stats':
                if e.attack != INFINITE_ATTACK_VALUE: return ()
                return (InvokeBehavior(P + 'fail', c.source_id, c.player_id),)
        return (options(c),)
    for cid, mode, event in ((WATCH_START, 'start', 'turn_started'),
            (WATCH_USED, 'used', 'limited_trigger_used'), (FAIL_STATS, 'stats', 'stats_changed')):
        r.register_behavior(cid, lambda c, mode=mode: watch(c, mode))
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=5, triggers=(TriggerSpec(event, cid),)))
    r.validate(); r.freeze(); return r


class MurozondOwnerStartTests(unittest.TestCase):
    def game(self, hand=(CARD,), *, board=(), enemy_hand=(), active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(FILL,) * 24, mana=10, max_mana=10,
                hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', hand=enemy_hand, deck=(FILL,) * 24, mana=10, max_mana=10,
                hero_power_card_id='HERO_08bp')), seed=261, active_player=active), registry('writer'))
    def play(self, g, cid=CARD):
        pid = g.state.active_player
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid, eid)); return eid
    def end(self, g): g.apply(EndTurn(g.state.active_player))
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def grants(self, g, eid):
        return [a for a in g.state.entities[eid].abilities if a.kind == 'limited_trigger'
            and a.limited_trigger.behavior_id == PREFIX + 'set_attack']
    def portable(self, g):
        s = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(s, registry('reader'))
        self.assertEqual(other.snapshot(), s); self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), registry('reader')).snapshot(), s); return other

    def test_a00_complete_original_body_dragon_and_explicit_shared_numeric_policy(self):
        d = load_batch(); c = registry('writer').card(CARD)
        self.assertEqual((c.cost, c.attack, c.health), (9, 8, 8)); self.assertEqual(c.metadata.tribes, ('dragon',))
        self.assertEqual(c.metadata.rarity.value, 'legendary'); self.assertEqual(len(d['official_observations']), 2)
        self.assertEqual(d['policy']['infinite_attack_value'], (1 << 31) - 1)
        self.assertNotIn('TIME_024e', registry('writer').cards); self.assertFalse(c.triggers)

    def test_a01_actual_paid_battlecry_only_sets_attack_at_next_caster_start(self):
        g = self.game(); eid = self.play(g); original = self.grants(g, eid)[0]
        self.assertEqual(g.state.players[1].mana, 1); self.assertEqual(g.state.entities[eid].attack, 8)
        self.end(g); self.assertEqual(g.state.entities[eid].attack, 8); self.assertEqual(self.grants(g, eid)[0], original)
        self.end(g); self.assertEqual(g.state.entities[eid].attack, INFINITE_ATTACK_VALUE)
        a = self.grants(g, eid)[0]; self.assertEqual((a.id, a.uses_remaining, a.consumed), (original.id, 0, True))
        self.assertEqual(len(g.state.play_history), 1)

    def test_a02_real_combat_uses_set_attack_and_defeats_opposing_hero(self):
        g = self.game(); eid = self.play(g); self.end(g); self.end(g)
        g.apply(Attack(1, eid, g.state.players[2].hero_id)); self.assertEqual(g.state.winner, 1)

    def test_a03_attack_setting_does_not_heal_or_replace_health_buffs(self):
        g = self.game((CARD, BUFF)); eid = self.play(g); self.play(g, BUFF)
        self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].health), (13, 7))
        self.end(g); self.end(g)
        self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].health, g.state.entities[eid].damage),
            (INFINITE_ATTACK_VALUE, 7, 3))

    def test_b00_current_copy_before_start_keeps_independent_pending_grant(self):
        g = self.game((CARD, CURRENT)); source = self.play(g); self.play(g, CURRENT)
        copies = list(g.state.players[1].board); self.assertEqual(len(copies), 2)
        self.assertNotEqual(self.grants(g, copies[0])[0].id, self.grants(g, copies[1])[0].id)
        other = self.portable(g)
        for item in (g, other): self.end(item); self.end(item)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertTrue(all(g.state.entities[i].attack == INFINITE_ATTACK_VALUE for i in copies))

    def test_b01_base_copy_does_not_invent_a_battlecry_or_pending_effect(self):
        g = self.game((CARD, BASE)); eid = self.play(g); self.play(g, BASE); copy = g.state.players[1].board[-1]
        self.assertFalse(self.grants(g, copy)); self.end(g); self.end(g)
        self.assertEqual(g.state.entities[eid].attack, INFINITE_ATTACK_VALUE); self.assertEqual(g.state.entities[copy].attack, 8)

    def test_b02_silence_and_death_remove_the_unconsumed_start_grant(self):
        for operation in (QUIET, KILL):
            with self.subTest(operation=operation):
                g = self.game((CARD, operation)); eid = self.play(g); self.play(g, operation); self.end(g); self.end(g)
                self.assertFalse(any(e.kind == 'stats_changed' and e.target_id == eid for e in g.events))

    def test_b03_return_resets_old_grant_and_actual_replay_installs_fresh_one(self):
        g = self.game((CARD, BOUNCE)); eid = self.play(g); old = self.grants(g, eid)[0].id; self.play(g, BOUNCE)
        self.assertFalse(self.grants(g, eid)); self.end(g); self.end(g); self.assertEqual(g.state.entities[eid].attack, 8)
        self.assertEqual(self.play(g), eid); self.assertNotEqual(self.grants(g, eid)[0].id, old)
        self.end(g); self.end(g); self.assertEqual(g.state.entities[eid].attack, INFINITE_ATTACK_VALUE)

    def test_b04_official_transform_fix_prevents_same_entity_new_face_receiving_infinity(self):
        g = self.game((CARD, CHANGE)); eid = self.play(g); self.play(g, CHANGE); self.end(g); self.end(g)
        self.assertEqual((g.state.entities[eid].card_id, g.state.entities[eid].attack), (OTHER, 2))
        self.assertFalse(self.grants(g, eid))

    def test_b05_control_change_preserves_original_caster_condition_local_policy(self):
        g = self.game(enemy_hand=(STEAL,)); eid = self.play(g); self.end(g); self.play(g, STEAL)
        self.assertEqual(g.state.entities[eid].controller, 2); self.end(g)
        self.assertEqual((g.state.active_player, g.state.entities[eid].attack), (1, INFINITE_ATTACK_VALUE))

    def test_b06_extra_actual_start_and_skipped_slot_use_existing_turn_scheduling(self):
        g = self.game((CARD, EXTRA)); eid = self.play(g); self.play(g, EXTRA); self.end(g)
        self.assertEqual((g.state.active_player, g.state.entities[eid].attack), (1, INFINITE_ATTACK_VALUE))
        g = self.game((CARD, SKIP)); eid = self.play(g); self.play(g, SKIP); self.end(g); self.end(g)
        self.assertEqual((g.state.active_player, g.state.entities[eid].attack), (2, 8))
        self.end(g); self.assertEqual(g.state.entities[eid].attack, INFINITE_ATTACK_VALUE)

    def test_b07_second_actor_on_first_global_turn_uses_its_own_next_start(self):
        g = self.game((), enemy_hand=(CARD,), active=2); eid = self.play(g); self.end(g)
        self.assertEqual(g.state.entities[eid].attack, 8); self.end(g)
        self.assertEqual((g.state.active_player, g.state.entities[eid].attack), (2, INFINITE_ATTACK_VALUE))

    def test_c00_real_deios_repeated_battlecry_installs_separate_once_grants_with_one_payment(self):
        g = self.game(board=('TIME_064',)); eid = self.play(g)
        self.assertEqual(len(self.grants(g, eid)), 2); self.assertEqual(g.state.players[1].mana, 1)
        self.end(g); self.end(g); self.assertTrue(all(a.consumed for a in self.grants(g, eid)))
        self.assertEqual(len([e for e in g.events if e.kind == 'stats_changed' and e.target_id == eid]), 2)

    def test_c01_existing_board_body_without_battlecry_has_no_delayed_grant(self):
        g = self.game((), board=(CARD,)); eid = g.state.players[1].board[0]; self.end(g); self.end(g)
        self.assertEqual(g.state.entities[eid].attack, 8); self.assertFalse(self.grants(g, eid))

    def test_c02_consumed_effect_does_not_reapply_after_later_set_or_current_copy(self):
        g = self.game((CARD, WEAKEN, CURRENT)); eid = self.play(g); self.end(g); self.end(g)
        self.play(g, WEAKEN); self.play(g, CURRENT); self.end(g); self.end(g)
        self.assertTrue(all(g.state.entities[i].attack == 4 for i in g.state.players[1].board))
        self.assertFalse(any(not a.consumed for i in g.state.players[1].board for a in self.grants(g, i)))

    def test_d00_active_original_grant_restores_clones_replays_and_fires_identically(self):
        g = self.game(); eid = self.play(g); other = self.portable(g)
        for item in (g, other): self.end(item); self.end(item)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(g.state.entities[eid].attack, INFINITE_ATTACK_VALUE)

    def test_d01_consumed_trigger_wait_keeps_once_budget_and_failed_choice_rolls_back(self):
        g = self.game(board=(WATCH_USED,)); eid = self.play(g); self.end(g); self.end(g)
        self.assertEqual((g.state.entities[eid].attack, self.grants(g, eid)[0].consumed), (8, True))
        other = self.portable(g); snap = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Deliberate Murozond reaction failure'): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), snap); self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(g.state.entities[eid].attack, INFINITE_ATTACK_VALUE)

    def test_d02_stat_reaction_failure_restores_entire_turn_attachment_and_health(self):
        g = self.game(board=(FAIL_STATS,)); self.play(g); self.end(g); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Deliberate Murozond reaction failure'): self.end(g)
        self.assertEqual(g.snapshot(), before)

    def test_d03_wait_before_consumption_preserves_captured_source_and_player_privacy(self):
        g = self.game(board=(WATCH_START,)); eid = self.play(g); self.end(g); self.end(g)
        self.assertFalse(self.grants(g, eid)[0].consumed); other = self.portable(g)
        for pid in (1, 2):
            wire = json.dumps(g.for_player(pid).observe()) + json.dumps(g.player_events(pid))
            for key in ('"ability_id"', '"source_id"', '"recipient"', '"condition_id"', '"continuation"'):
                self.assertNotIn(key, wire)
        self.choose(g); self.choose(other); self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.entities[eid].attack, INFINITE_ATTACK_VALUE)

    def test_e00_unknown_saved_callback_is_rejected_after_canonical_rehash(self):
        g = self.game(); eid = self.play(g); snap = g.snapshot()
        ability = next(x for x in snap['state']['entities'][str(eid)]['abilities'] if x['kind'] == 'limited_trigger')
        ability['limited_trigger']['condition_id'] = PREFIX + 'unknown'
        keys = ('ruleset', 'registry_fingerprint', 'mechanics_version', 'state', 'rng_state',
            'resolution_frame', 'rewind_session', 'match_setup', 'generation_context', 'information')
        snap['state_hash'] = canonical_digest({k: snap[k] for k in keys})
        with self.assertRaises(ValueError): Game.from_snapshot(snap, registry('reader'))

    def test_e01_dormant_at_intended_start_cannot_awaken_and_fire_on_a_later_start(self):
        g = self.game((CARD, SLEEP, WAKE)); eid = self.play(g); self.play(g, SLEEP)
        self.end(g); self.end(g); self.assertEqual(g.state.entities[eid].attack, 8)
        self.play(g, WAKE); self.end(g); self.assertFalse(self.grants(g, eid)); self.end(g)
        self.assertEqual(g.state.entities[eid].attack, 8)

    def test_e02_saved_deadline_cannot_shift_to_a_later_owner_start_after_rehash(self):
        g = self.game(); eid = self.play(g); snap = g.snapshot()
        ability = next(x for x in snap['state']['entities'][str(eid)]['abilities'] if x['kind'] == 'limited_trigger')
        ability['limited_trigger_deadline']['owner_turn_index'] += 1
        keys = ('ruleset', 'registry_fingerprint', 'mechanics_version', 'state', 'rng_state',
            'resolution_frame', 'rewind_session', 'match_setup', 'generation_context', 'information')
        snap['state_hash'] = canonical_digest({k: snap[k] for k in keys})
        with self.assertRaises(ValueError): Game.from_snapshot(snap, registry('reader'))

    def test_e03_frozen_death_material_cannot_shift_its_original_start_deadline(self):
        g = self.game((CARD, KILL)); self.play(g); self.play(g, KILL); self.portable(g); snap = g.snapshot()
        ability = next(x for x in snap['state']['death_history'][-1]['abilities'] if x['kind'] == 'limited_trigger')
        ability['limited_trigger_deadline']['owner_turn_index'] += 1
        keys = ('ruleset', 'registry_fingerprint', 'mechanics_version', 'state', 'rng_state',
            'resolution_frame', 'rewind_session', 'match_setup', 'generation_context', 'information')
        snap['state_hash'] = canonical_digest({k: snap[k] for k in keys})
        with self.assertRaises(ValueError): Game.from_snapshot(snap, registry('reader'))


if __name__ == '__main__': unittest.main()
