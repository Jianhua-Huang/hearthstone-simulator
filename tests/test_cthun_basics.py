"""Classic numeric ritual foundation, with only two necessary real cultists."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    CthunProfile, EndTurn, Game, GrowCthun, PlayCard, PlayerSetup, Rarity,
    Registry, ResolutionError, Scenario, SelectChoice, SnapshotError, Zone,
    cthun_attack_at_least, cthun_ritual_stats)
from hs_sim.engine.cthun import VERSION
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption,
    CopyMinion, Destroy, RequestChoice, ReturnToHand, SetStats, ShuffleIntoDeck,
    Silence, SplitDamage, Summon, Transform)
from hs_sim.engine.model import DamageKind, EndTurnSpec, TriggerSpec
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.player_target_inputs import capture, decode, canonical
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest


CTHUN, REPRINT, BECKONER, ELDER = 'OG_280', 'WON_135', 'OG_281', 'OG_286'
PIN = '45482a1bcba2085b3f18dcbb7bf8ae19836bb168a3c897fa61029805c7420946'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/cthun-basics.json'


def evidence():
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(data) != PIN:
        raise ValueError('Complete Cthun raw evidence changed')
    for row in data['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original complete Cthun record changed')
    return {r['id']: r['data'] for r in data['records']}


def registry(extras=(), missing=False, no_profile=False):
    r = Registry('cthun-basics-' + VERSION)
    if not no_profile:
        r.register_cthun_profile(CthunProfile(VERSION, (CTHUN, REPRINT)))
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=300,
        metadata=CardMetadata(False, (CardClass.MAGE,), None)))
    r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, attack=2, health=4))
    raw = evidence()
    r.register_behavior('cthun.beckoner', lambda c: (GrowCthun(c.player_id, 2, 2, c.source_id),))
    r.register_behavior('cthun.elder', lambda c: (GrowCthun(c.player_id, 1, 1, c.source_id),))
    r.register_behavior('cthun.body', lambda c: (SplitDamage(3-c.player_id,
        min(100, c.state.entities[c.source_id].attack), source_id=c.source_id, kind=DamageKind.EFFECT),))
    for cid in (CTHUN, REPRINT, BECKONER, ELDER):
        if missing and cid in (CTHUN, REPRINT):
            continue
        row = raw[cid]
        if cid in (CTHUN, REPRINT):
            fields = {'battlecry': 'cthun.body'}
        elif cid == BECKONER:
            fields = {'battlecry': 'cthun.beckoner'}
        else:
            fields = {'triggers': (TriggerSpec('turn_ended', 'cthun.elder', EndTurnSpec()),)}
        r.register_card(CardDefinition(cid, row['name'], CardType.MINION,
            cost=row['cost'], attack=row['attack'], health=row['health'],
            metadata=CardMetadata(True, (CardClass.NEUTRAL,),
                Rarity.LEGENDARY if cid in (CTHUN, REPRINT) else Rarity.COMMON), **fields))
    probes = {
        'grow': lambda c: (GrowCthun(c.player_id, 2, 2, c.source_id),),
        'grow_enemy': lambda c: (GrowCthun(2, 3, 1, c.source_id),),
        'create': lambda c: (AddToHand(c.player_id, CTHUN, c.source_id),),
        'summon': lambda c: (Summon(c.player_id, CTHUN),),
    }
    probes.update(dict(extras))
    for cid, fn in probes.items():
        r.register_behavior(cid, lambda c, fn=fn: fn(c))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    return r


class CthunBasicsTests(unittest.TestCase):
    def setUp(self):
        self.extras = []

    def script(self, cid, fn):
        self.extras.append((cid, fn))

    def game(self, hand=('grow',), board=(), deck=(), enemy_board=(), enemy_hand=(), missing=False, no_profile=False):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=deck, mana=10, max_mana=10),
            PlayerSetup('hero', hand=enemy_hand, board=enemy_board, mana=10, max_mana=10)), seed=13),
            registry(self.extras, missing, no_profile))

    def play(self, g, cid, pid=1):
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid, eid)); return eid

    def body(self, g, zone=Zone.BOARD, pid=1, cid=CTHUN):
        return next(e for e in g.state.entities.values() if e.controller == pid and e.zone == zone and e.card_id == cid)

    def stats(self, g, pid=1):
        return cthun_ritual_stats(g.state, g.registry, pid)

    def check(self, g):
        restored = Game.from_snapshot(g.snapshot(), registry(self.extras))
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual(g.clone().snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), registry(self.extras)).snapshot(), g.snapshot())
        for pid in (1, 2):
            self.assertEqual(restored.observe(pid), g.observe(pid))

    def rejected(self, g, mutate):
        s = g.snapshot(); mutate(s)
        s['events_hash'] = canonical_hash(s['events'])
        s['state_hash'] = canonical_hash({k: v for k, v in s.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(s, registry(self.extras))

    def test_frozen_raw_and_two_real_cultists_only(self):
        raw, r = evidence(), registry()
        self.assertEqual(len(raw), 12)
        self.assertEqual((r.card(CTHUN).cost, r.card(CTHUN).attack, r.card(CTHUN).health), (8, 6, 6))
        self.assertEqual(r.card(REPRINT).cost, 8)
        self.assertEqual((r.card(BECKONER).attack, r.card(BECKONER).health), (2, 3))
        self.assertNotIn('OG_279', r.cards)
        self.assertNotIn('OG_284', r.cards)
        self.assertNotIn('DMF_254', r.cards)

    def test_growth_without_any_cthun(self):
        g = self.game(); before = g.snapshot()['rng_state']; self.play(g, 'grow')
        self.assertEqual(self.stats(g), (8, 8))
        self.assertFalse(any(e.card_id == CTHUN for e in g.state.entities.values()))
        self.assertEqual(g.snapshot()['rng_state'], before); self.check(g)

    def test_new_hand_body_receives_accumulated_growth_once(self):
        g = self.game(hand=('grow', 'grow', 'create')); self.play(g, 'grow'); self.play(g, 'grow'); self.play(g, 'create')
        e = self.body(g, Zone.HAND); self.assertEqual((e.attack, e.max_health), (10, 10))
        self.assertEqual(len(e.enchantments), 1); self.check(g)

    def test_new_summon_receives_accumulated_growth(self):
        g = self.game(hand=('grow', 'summon')); self.play(g, 'grow'); self.play(g, 'summon')
        e = self.body(g); self.assertEqual((e.attack, e.health), (8, 8)); self.check(g)

    def test_hand_deck_board_and_reprint_grow_together(self):
        g = self.game(hand=('grow', CTHUN), deck=(CTHUN,), board=(CTHUN, REPRINT))
        self.play(g, 'grow')
        bodies = [e for e in g.state.entities.values() if e.card_id in (CTHUN, REPRINT)]
        self.assertEqual([(e.attack, e.health) for e in bodies], [(8, 8)] * 4); self.check(g)

    def test_two_player_banks_are_independent(self):
        g = self.game(hand=('grow', 'grow_enemy'), board=(CTHUN,), enemy_board=(CTHUN,))
        self.play(g, 'grow'); self.play(g, 'grow_enemy')
        self.assertEqual(self.stats(g), (8, 8)); self.assertEqual(self.stats(g, 2), (9, 7))
        self.assertEqual((self.body(g, pid=2).attack, self.body(g, pid=2).health), (9, 7)); self.check(g)

    def test_real_beckoner_battlecry_works_without_cthun(self):
        g = self.game(hand=(BECKONER,)); self.play(g, BECKONER)
        self.assertEqual(self.stats(g), (8, 8)); self.assertEqual(len(g.state.cthun_history), 1); self.check(g)

    def test_real_elder_only_grows_on_its_controller_end(self):
        g = self.game(hand=(), board=(ELDER,))
        g.apply(EndTurn(1)); self.assertEqual(self.stats(g), (7, 7))
        g.apply(EndTurn(2)); self.assertEqual(self.stats(g), (7, 7)); self.check(g)

    def test_silence_preserves_ritual_and_removes_ordinary_buff(self):
        self.script('ordinary', lambda c: (Buff(c.state.players[1].board[0], 3, 4),))
        self.script('silence', lambda c: (Silence(c.state.players[1].board[0]),))
        g = self.game(hand=('grow', 'ordinary', 'silence', 'grow'), board=(CTHUN,))
        for cid in ('grow', 'ordinary', 'silence'):
            self.play(g, cid)
        e = self.body(g); self.assertEqual((e.attack, e.health), (8, 8)); self.assertTrue(e.silenced)
        self.play(g, 'grow'); self.assertEqual(self.body(g).attack, 10); self.check(g)

    def test_future_growth_adds_delta_after_stat_set(self):
        self.script('set', lambda c: (SetStats(c.state.players[1].board[0], 1, 1),))
        g = self.game(hand=('grow', 'grow', 'set', 'grow'), board=(CTHUN,))
        for cid in ('grow', 'grow', 'set', 'grow'):
            self.play(g, cid)
        self.assertEqual((self.body(g).attack, self.body(g).health), (3, 3))
        self.assertEqual(self.stats(g), (12, 12)); self.check(g)

    def test_physical_ordinary_buff_does_not_raise_ritual_bank(self):
        self.script('ordinary', lambda c: (Buff(c.state.players[1].board[0], 5, 1),))
        g = self.game(hand=('ordinary',), board=(CTHUN,)); self.play(g, 'ordinary')
        self.assertEqual(self.stats(g), (6, 6)); self.assertEqual(self.body(g).attack, 11)
        self.assertTrue(cthun_attack_at_least(g.state, g.registry, 1)); self.check(g)

    def test_threshold_can_succeed_without_physical_body(self):
        g = self.game(hand=('grow', 'grow')); self.play(g, 'grow'); self.play(g, 'grow')
        self.assertTrue(cthun_attack_at_least(g.state, g.registry, 1))
        self.assertFalse(cthun_attack_at_least(g.state, g.registry, 1, 11))

    def test_opponent_physical_attack_does_not_satisfy_threshold(self):
        self.script('ordinary', lambda c: (Buff(c.state.players[2].board[0], 5, 1),))
        g = self.game(hand=('ordinary',), enemy_board=(CTHUN,)); self.play(g, 'ordinary')
        self.assertFalse(cthun_attack_at_least(g.state, g.registry, 1))

    def test_transform_into_cthun_does_not_receive_past_growth(self):
        self.script('transform', lambda c: (Transform(c.state.players[1].board[0], CTHUN),))
        g = self.game(hand=('grow', 'transform', 'grow'), board=('plain',))
        self.play(g, 'grow'); self.play(g, 'transform'); self.assertEqual(self.body(g).attack, 6)
        self.play(g, 'grow'); self.assertEqual(self.body(g).attack, 8); self.check(g)

    def test_transform_out_of_cthun_clears_ritual_material(self):
        self.script('transform', lambda c: (Transform(c.state.players[1].board[0], 'plain'),))
        g = self.game(hand=('grow', 'transform', 'grow'), board=(CTHUN,))
        for cid in ('grow', 'transform', 'grow'):
            self.play(g, cid)
        e = g.state.entities[g.state.players[1].board[0]]
        self.assertEqual((e.attack, e.health, e.enchantments), (2, 4, [])); self.check(g)

    def test_return_to_hand_keeps_permanent_growth_without_doubling(self):
        self.script('bounce', lambda c: (ReturnToHand(c.state.players[1].board[0]),))
        g = self.game(hand=('grow', 'bounce'), board=(CTHUN,)); self.play(g, 'grow'); self.play(g, 'bounce')
        e = self.body(g, Zone.HAND); self.assertEqual((e.attack, e.health), (8, 8))
        self.play(g, CTHUN); self.assertEqual(self.body(g).attack, 8); self.check(g)

    def test_shuffle_and_draw_keep_same_permanent_growth(self):
        self.script('shuffle', lambda c: (ShuffleIntoDeck(c.state.players[1].board[0]),))
        g = self.game(hand=('grow', 'shuffle', 'grow'), board=(CTHUN,))
        self.play(g, 'grow'); self.play(g, 'shuffle'); self.play(g, 'grow')
        self.assertEqual(self.body(g, Zone.DECK).attack, 10)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.assertEqual(self.body(g, Zone.HAND).attack, 10); self.check(g)

    def test_reset_stored_card_keeps_ritual(self):
        self.script('move', lambda c: (MoveCard(CardReference.capture(c.state.entities[c.state.players[1].hand[-1]]),
            1, Zone.DECK, reset=True),))
        g = self.game(hand=('grow', 'move', CTHUN)); self.play(g, 'grow'); self.play(g, 'move')
        self.assertEqual(self.body(g, Zone.DECK).attack, 8); self.check(g)

    def test_base_copy_uses_receiver_bank(self):
        self.script('copy', lambda c: (CopyCard(CardReference.capture(c.state.entities[c.state.players[2].hand[-1]]),
            1, mode='base'),))
        g = self.game(hand=('grow', 'grow_enemy', 'copy'), enemy_hand=(CTHUN,))
        for cid in ('grow', 'grow_enemy', 'copy'):
            self.play(g, cid)
        self.assertEqual(self.body(g, Zone.HAND).attack, 8)
        self.assertEqual(self.body(g, Zone.HAND, 2).attack, 9); self.check(g)

    def test_current_copy_keeps_frozen_increment_and_no_double_bank(self):
        self.script('copy', lambda c: (CopyMinion(c.state.players[1].board[0], 1, mode='current',
            cause=SummonCause.capture(c)),))
        g = self.game(hand=('grow', 'copy'), board=(CTHUN,)); self.play(g, 'grow'); self.play(g, 'copy')
        self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board], [8, 8])
        self.assertEqual(len(g.state.cthun_history), 1); self.check(g)

    def test_control_change_retains_physical_stats_and_only_new_delta(self):
        self.script('steal', lambda c: (ChangeControl(c.state.players[2].board[0], 1),))
        g = self.game(hand=('grow_enemy', 'steal', 'grow'), enemy_board=(CTHUN,))
        for cid in ('grow_enemy', 'steal', 'grow'):
            self.play(g, cid)
        self.assertEqual((self.body(g).attack, self.body(g).health), (11, 9)); self.check(g)

    def test_death_does_not_stop_bank_or_mutate_old_dead_body(self):
        self.script('kill', lambda c: (Destroy(c.state.players[1].board[0]),))
        g = self.game(hand=('grow', 'kill', 'grow'), board=(CTHUN,))
        eid = self.body(g).id
        for cid in ('grow', 'kill', 'grow'):
            self.play(g, cid)
        self.assertEqual(self.stats(g), (10, 10)); self.assertEqual(g.state.entities[eid].attack, 8)
        self.assertEqual(g.state.death_history[0].attack, 8); self.check(g)

    def test_resurrection_new_body_receives_current_bank(self):
        self.script('kill', lambda c: (Destroy(c.state.players[1].board[0]),))
        self.script('revive', lambda c: (ResurrectMinion(1, c.state.death_history[0].id,
            source_id=c.source_id, cause=SummonCause.capture(c)),))
        g = self.game(hand=('grow', 'kill', 'grow', 'revive'), board=(CTHUN,))
        for cid in ('grow', 'kill', 'grow', 'revive'):
            self.play(g, cid)
        self.assertEqual(self.body(g).attack, 10); self.assertEqual(len(g.state.cthun_history), 2); self.check(g)

    def test_real_cthun_battlecry_reads_actual_attack_not_bank(self):
        self.script('sethand', lambda c: (BuffStoredCard(
            CardReference.capture(c.state.entities[c.state.players[1].hand[-1]]), attack=2),))
        g = self.game(hand=('sethand', CTHUN)); self.play(g, 'sethand'); self.play(g, CTHUN)
        hits = [e for e in g.events if e.kind == 'random_choice' and e.source_id == self.body(g).id]
        self.assertEqual(len(hits), 8); self.assertEqual(self.stats(g), (6, 6))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].damage, 8); self.check(g)

    def test_transformed_body_catches_up_on_hand_reset_without_duplicate_rows(self):
        self.script('transform', lambda c: (Transform(c.state.players[1].board[0], CTHUN),))
        self.script('bounce', lambda c: (ReturnToHand(c.state.players[1].board[0]),))
        g = self.game(hand=('grow', 'transform', 'grow', 'bounce'), board=('plain',))
        for cid in ('grow', 'transform', 'grow', 'bounce'):
            self.play(g, cid)
        self.assertEqual(self.body(g, Zone.HAND).attack, 10); self.check(g)

    def test_reset_into_other_player_deck_uses_recipient_ritual(self):
        self.script('shuffle', lambda c: (ShuffleIntoDeck(c.state.players[2].board[0], player_id=1),))
        g = self.game(hand=('grow', 'grow_enemy', 'shuffle'), enemy_board=(CTHUN,))
        for cid in ('grow', 'grow_enemy', 'shuffle'):
            self.play(g, cid)
        self.assertEqual((self.body(g, Zone.DECK).attack, self.body(g, Zone.DECK).health), (8, 8)); self.check(g)

    def test_frozen_copy_material_cannot_rewrite_original_permanent_delta(self):
        self.script('copy', lambda c: (CopyMinion(c.state.players[1].board[0], 1,
            mode='current', cause=SummonCause.capture(c)),))
        g = self.game(hand=('grow', 'copy'), board=(CTHUN,)); self.play(g, 'grow'); self.play(g, 'copy')
        self.rejected(g, lambda s: s['state']['card_summon_history'][0]['request']['materials'][0]
            ['local']['enchantments'][0].update(attack=9))

    def test_real_cthun_caps_native_missiles_at_one_hundred(self):
        self.script('large', lambda c: (GrowCthun(1, 150, 0, c.source_id),))
        g = self.game(hand=('large', CTHUN)); self.play(g, 'large'); self.play(g, CTHUN)
        self.assertEqual(self.body(g).attack, 156)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].damage, 100); self.check(g)

    def test_waiting_growth_restores_clone_and_replay_with_remaining_tail(self):
        self.script('wait', lambda c: (GrowCthun(1, 2, 2, c.source_id),
            RequestChoice(1, (ChoiceOption('ok', 'Continue', (GrowCthun(1, 1, 1, c.source_id),)),), c.source_id),
            GrowCthun(1, 3, 0, c.source_id)))
        g = self.game(hand=('wait',)); self.play(g, 'wait')
        self.assertEqual(self.stats(g), (8, 8)); self.check(g)
        restored = Game.from_snapshot(g.snapshot(), registry(self.extras))
        choice = g.state.pending_choice; action = SelectChoice(1, choice.id, ('ok',))
        g.apply(action); restored.apply(action)
        self.assertEqual(self.stats(g), (12, 9)); self.assertEqual(restored.snapshot(), g.snapshot()); self.check(g)

    def test_invalid_tail_rolls_back_growth_stats_events_rng_and_payment(self):
        self.script('bad', lambda c: (GrowCthun(1, 2, 2, c.source_id), AddToHand(1, 'unknown')))
        g = self.game(hand=('bad',), board=(CTHUN,)); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'bad')
        self.assertEqual(g.snapshot(), before)

    def test_owner_view_is_numeric_and_enemy_has_no_bank_or_private_receipt(self):
        g = self.game(); self.play(g, 'grow')
        for pid in (1, 2):
            view = g.observe(pid)
            self.assertEqual(view['players'][pid-1]['cthun_ritual'],
                {'attack': 8, 'health': 8} if pid == 1 else {'attack': 6, 'health': 6})
            self.assertNotIn('cthun_ritual', view['players'][2-pid])
            rendered = json.dumps(view)
            self.assertNotIn('cthun_ritual_grown', rendered); self.assertNotIn('cthun_history', rendered)
            self.assertNotIn('growth_id', rendered)

    def test_player_target_dto_accepts_only_owner_numeric_bank(self):
        g = self.game(hand=('grow', CTHUN)); self.play(g, 'grow')
        state = g._state; source = state.entities[self.body(g, Zone.HAND).id]
        proof = capture(g, state, source); value = decode(proof)
        self.assertEqual(value['players'][0]['cthun_ritual'], {'attack': 8, 'health': 8})
        value['players'][1]['cthun_ritual'] = {'attack': 8, 'health': 8}
        with self.assertRaises(ValueError):
            decode(replace(proof, observation_json=canonical(value)))

    def test_snapshot_rejects_old_future_schema_and_bool(self):
        g = self.game(); self.assertEqual(g.snapshot()['schema_version'], 265)
        for version in (1, 154, 155, 156, 157, 158, 159, 160, 161, 162, 217, True):
            s = g.snapshot(); s['schema_version'] = version
            with self.assertRaises(SnapshotError):
                Game.from_snapshot(s, registry())

    def test_rehashed_snapshot_cannot_change_growth_without_receipt(self):
        g = self.game(); self.play(g, 'grow')
        self.rejected(g, lambda s: s['state']['cthun_history'][0].update(attack=9))

    def test_rehashed_snapshot_cannot_drop_growth_receipt(self):
        g = self.game(); self.play(g, 'grow')
        self.rejected(g, lambda s: s['events'].__setitem__(slice(None),
            [e for e in s['events'] if e['kind'] != 'cthun_ritual_grown']))

    def test_rehashed_snapshot_cannot_change_physical_growth_stamp(self):
        g = self.game(board=(CTHUN,)); self.play(g, 'grow'); eid = str(self.body(g).id)
        self.rejected(g, lambda s: s['state']['entities'][eid]['enchantments'][0].update(attack=7))

    def test_rehashed_snapshot_cannot_make_ritual_removable(self):
        g = self.game(board=(CTHUN,)); self.play(g, 'grow'); eid = str(self.body(g).id)
        self.rejected(g, lambda s: s['state']['entities'][eid]['enchantments'][0].update(remove_on_silence=True))

    def test_registry_profile_is_frozen_and_fingerprinted(self):
        r = registry(); before = r.fingerprint(); r.freeze()
        with self.assertRaises(ValueError):
            r.register_cthun_profile(CthunProfile('other', (CTHUN,)))
        other = registry(); other._cthun_profile = CthunProfile('other', (CTHUN, REPRINT))
        self.assertNotEqual(other.fingerprint(), before)

    def test_unknown_body_adapter_remains_error_after_absent_growth(self):
        g = self.game(hand=('grow', 'create'), missing=True); self.play(g, 'grow'); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'create')
        self.assertEqual(g.snapshot(), before)

    def test_missing_profile_rejects_growth_instead_of_noop(self):
        g = self.game(no_profile=True); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'grow')
        self.assertEqual(g.snapshot(), before)

    def test_exact_argument_types_and_zero_growth(self):
        for args in ((True, 1, 1), (1, True, 1), (1, 1, -1), (3, 1, 1)):
            with self.assertRaises(ValueError):
                GrowCthun(*args)
        self.script('zero', lambda c: (GrowCthun(1, 0, 0, c.source_id),))
        g = self.game(hand=('zero',)); self.play(g, 'zero')
        self.assertEqual(self.stats(g), (6, 6)); self.assertEqual(g.state.cthun_history, [])


if __name__ == '__main__':
    unittest.main()
