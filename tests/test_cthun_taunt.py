"""Real Geomancer growth and its own ordinary lifecycle, no combination family."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, GrowCthun, Keyword, PlayCard, PlayerSetup, Rarity,
    ResolutionError, Scenario, SelectChoice, SnapshotError, Zone, cthun_ritual_stats)
from hs_sim.engine.cthun import ritual_taunt
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, CopyMinion,
    Destroy, RequestChoice, ReturnToHand, ShuffleIntoDeck, Silence, Summon, Transform)
from hs_sim.engine.model import AbilityInstance, CthunRitualStamp
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest
from test_cthun_basics import CTHUN, REPRINT, registry as numeric_registry


GEOMANCER = 'OG_284'
PIN = '4196c82cebe88ce4fd30c981d96d12adac20a704411cb5866720c4f5b257d0f4'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/cthun-taunt.json'


def evidence():
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(data) != PIN:
        raise ValueError('Complete Geomancer raw evidence changed')
    for r in data['records']:
        if r['id'] != r['data']['id'] or canonical_digest(r['data']) != r['data_sha256']:
            raise ValueError('Complete original Geomancer record changed')
    return {r['id']: r['data'] for r in data['records']}


def registry(extras=(), *, missing=False, no_profile=False):
    r = numeric_registry(extras, missing, no_profile)
    row = evidence()[GEOMANCER]
    r.register_behavior('cthun.geomancer', lambda c:
        (GrowCthun(c.player_id, 1, 1, c.source_id, taunt=True),))
    r.register_card(CardDefinition(GEOMANCER, row['name'], CardType.MINION,
        cost=row['cost'], attack=row['attack'], health=row['health'],
        keywords=(Keyword.TAUNT,), battlecry='cthun.geomancer',
        metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON)))
    return r


class CthunTauntTests(unittest.TestCase):
    def setUp(self):
        self.extras = []

    def script(self, cid, fn):
        self.extras.append((cid, fn))

    def game(self, hand=(GEOMANCER,), board=(), deck=(), enemy_board=(), enemy_hand=(), **options):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=deck, mana=10, max_mana=10),
            PlayerSetup('hero', board=enemy_board, hand=enemy_hand, mana=10, max_mana=10)), seed=43),
            registry(self.extras, **options))

    def play(self, g, cid, pid=1):
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid, eid))
        return eid

    def body(self, g, zone=Zone.BOARD, pid=1, cid=CTHUN):
        return next(e for e in g.state.entities.values()
                    if e.controller == pid and e.zone == zone and e.card_id == cid)

    def check(self, g):
        restored = Game.from_snapshot(g.snapshot(), registry(self.extras))
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual(g.clone().snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), registry(self.extras)).snapshot(), g.snapshot())
        for pid in (1, 2):
            self.assertEqual(restored.observe(pid), g.observe(pid))

    def rejected(self, g, mutate):
        s = g.snapshot()
        mutate(s)
        s['events_hash'] = canonical_hash(s['events'])
        s['state_hash'] = canonical_hash({k: v for k, v in s.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(s, registry(self.extras))

    def test_complete_real_geomancer_and_enchantment_evidence(self):
        raw = evidence(); r = registry()
        self.assertEqual(set(raw), {GEOMANCER, 'OG_284e'})
        d = r.card(GEOMANCER)
        self.assertEqual((d.cost, d.attack, d.health), (2, 1, 4))
        self.assertEqual(d.keywords, (Keyword.TAUNT,))
        self.assertIn('+1/+1', raw[GEOMANCER]['text_en'])
        self.assertNotIn('OG_284e', r.cards)

    def test_absent_ritual_records_taunt_and_later_creation_receives_it(self):
        g = self.game(hand=(GEOMANCER, 'create')); before = g.snapshot()['rng_state']
        self.play(g, GEOMANCER)
        self.assertEqual(cthun_ritual_stats(g.state, g.registry, 1), (7, 7))
        self.assertTrue(ritual_taunt(g.state, 1))
        self.assertFalse(any(e.card_id == CTHUN for e in g.state.entities.values()))
        self.assertEqual(g.snapshot()['rng_state'], before)
        self.play(g, 'create'); e = self.body(g, Zone.HAND)
        self.assertEqual((e.attack, e.health), (7, 7)); self.assertIn(Keyword.TAUNT, e.keywords)
        self.check(g)

    def test_existing_hand_deck_board_and_reprint_receive_same_grant(self):
        g = self.game(hand=(GEOMANCER, CTHUN), deck=(CTHUN,), board=(CTHUN, REPRINT), enemy_board=(CTHUN,))
        self.play(g, GEOMANCER)
        bodies = [e for e in g.state.entities.values() if e.controller == 1 and e.card_id in (CTHUN, REPRINT)]
        self.assertEqual(len(bodies), 4)
        self.assertTrue(all((e.attack, e.health) == (7, 7) and Keyword.TAUNT in e.keywords for e in bodies))
        self.assertNotIn(Keyword.TAUNT, self.body(g, pid=2).keywords); self.check(g)

    def test_numeric_growth_does_not_grant_or_regrant_taunt(self):
        g = self.game(hand=('grow',), board=(CTHUN,)); self.play(g, 'grow')
        self.assertFalse(ritual_taunt(g.state, 1))
        self.assertNotIn(Keyword.TAUNT, self.body(g).keywords); self.check(g)

    def test_taunt_only_growth_is_a_real_nonzero_contribution(self):
        self.script('flag', lambda c: (GrowCthun(1, 0, 0, c.source_id, taunt=True),))
        g = self.game(hand=('flag',), board=(CTHUN,)); self.play(g, 'flag')
        e = self.body(g); self.assertEqual((e.attack, e.health, e.enchantments), (6, 6, []))
        self.assertIn(Keyword.TAUNT, e.keywords); self.assertEqual(len(g.state.cthun_history), 1); self.check(g)

    def test_zero_growth_stays_noop_and_taunt_flag_requires_exact_bool(self):
        for invalid in (0, 1, None, 'taunt', Keyword.TAUNT):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                GrowCthun(1, 0, 0, taunt=invalid)
        self.script('zero', lambda c: (GrowCthun(1, 0, 0, c.source_id),))
        g = self.game(hand=('zero',)); self.play(g, 'zero')
        self.assertEqual(g.state.cthun_history, []); self.assertFalse(ritual_taunt(g.state, 1)); self.check(g)

    def test_repeated_geomancer_grants_do_not_duplicate_on_reset(self):
        self.script('bounce', lambda c: (ReturnToHand(c.state.players[1].board[0]),))
        g = self.game(hand=(GEOMANCER, GEOMANCER, 'bounce'), board=(CTHUN,))
        self.play(g, GEOMANCER); self.play(g, GEOMANCER)
        self.assertEqual(len([a for a in self.body(g).abilities if a.cthun_ritual]), 2)
        self.play(g, 'bounce'); e = self.body(g, Zone.HAND)
        self.assertEqual((e.attack, e.health), (8, 8))
        self.assertEqual(len([a for a in e.abilities if a.cthun_ritual]), 2); self.check(g)

    def test_permanent_taunt_survives_silence_and_later_numeric_growth(self):
        self.script('silence', lambda c: (Silence(c.state.players[1].board[0]),))
        g = self.game(hand=(GEOMANCER, 'silence', 'grow'), board=(CTHUN,))
        self.play(g, GEOMANCER); self.play(g, 'silence'); self.play(g, 'grow')
        e = self.body(g); self.assertTrue(e.silenced); self.assertIn(Keyword.TAUNT, e.keywords)
        self.assertEqual((e.attack, e.health), (9, 9)); self.check(g)

    def test_geomancer_printed_taunt_is_ordinary_removable_keyword(self):
        self.script('silence', lambda c: (Silence(c.state.players[1].board[-1]),))
        g = self.game(hand=(GEOMANCER, 'silence'), board=(CTHUN,))
        self.play(g, GEOMANCER); self.play(g, 'silence')
        self.assertNotIn(Keyword.TAUNT, self.body(g, cid=GEOMANCER).keywords)
        self.assertIn(Keyword.TAUNT, self.body(g).keywords); self.check(g)

    def test_bounce_and_play_preserve_taunt_and_do_not_grow_again(self):
        self.script('bounce', lambda c: (ReturnToHand(c.state.players[1].board[0]),))
        g = self.game(hand=(GEOMANCER, 'bounce'), board=(CTHUN,))
        self.play(g, GEOMANCER); self.play(g, 'bounce')
        self.assertIn(Keyword.TAUNT, self.body(g, Zone.HAND).keywords)
        self.play(g, CTHUN); self.assertEqual(self.body(g).attack, 7)
        self.assertIn(Keyword.TAUNT, self.body(g).keywords); self.check(g)

    def test_stored_reset_keeps_one_taunt_contribution(self):
        self.script('move', lambda c: (MoveCard(CardReference.capture(c.state.entities[c.state.players[1].hand[-1]]),
            1, Zone.DECK, reset=True),))
        g = self.game(hand=(GEOMANCER, 'move', CTHUN)); self.play(g, GEOMANCER); self.play(g, 'move')
        e = self.body(g, Zone.DECK); self.assertIn(Keyword.TAUNT, e.keywords)
        self.assertEqual(len([a for a in e.abilities if a.cthun_ritual]), 1); self.check(g)

    def test_shuffling_and_drawing_preserve_growth_and_keyword(self):
        self.script('shuffle', lambda c: (ShuffleIntoDeck(c.state.players[1].board[0]),))
        g = self.game(hand=(GEOMANCER, 'shuffle'), board=(CTHUN,))
        self.play(g, GEOMANCER); self.play(g, 'shuffle')
        self.assertIn(Keyword.TAUNT, self.body(g, Zone.DECK).keywords)
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        e = self.body(g, Zone.HAND); self.assertEqual((e.attack, e.health), (7, 7))
        self.assertIn(Keyword.TAUNT, e.keywords); self.check(g)

    def test_current_board_copy_retains_original_taunt_once(self):
        self.script('copy', lambda c: (CopyMinion(c.state.players[1].board[0], 1,
            mode='current', cause=SummonCause.capture(c)),))
        g = self.game(hand=(GEOMANCER, 'copy'), board=(CTHUN,)); self.play(g, GEOMANCER); self.play(g, 'copy')
        bodies = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == CTHUN]
        self.assertEqual(len(bodies), 2)
        self.assertTrue(all(e.attack == 7 and Keyword.TAUNT in e.keywords for e in bodies)); self.check(g)

    def test_current_stored_copy_retains_other_players_local_taunt(self):
        self.script('copy', lambda c: (CopyCard(CardReference.capture(c.state.entities[c.state.players[2].hand[-1]]),
            1, mode='current'),))
        g = self.game(hand=('copy',), enemy_hand=(GEOMANCER, CTHUN))
        g.apply(EndTurn(1)); self.play(g, GEOMANCER, 2); g.apply(EndTurn(2)); self.play(g, 'copy')
        self.assertFalse(ritual_taunt(g.state, 1)); self.assertIn(Keyword.TAUNT, self.body(g, Zone.HAND).keywords)
        self.check(g)

    def test_base_copy_uses_receiver_taunt_and_does_not_borrow_source_bank(self):
        self.script('copy', lambda c: (CopyCard(CardReference.capture(c.state.entities[c.state.players[2].hand[-1]]),
            1, mode='base'),))
        g = self.game(hand=('copy',), enemy_hand=(GEOMANCER, CTHUN))
        g.apply(EndTurn(1)); self.play(g, GEOMANCER, 2); g.apply(EndTurn(2)); self.play(g, 'copy')
        self.assertNotIn(Keyword.TAUNT, self.body(g, Zone.HAND).keywords); self.assertEqual(self.body(g, Zone.HAND).attack, 6)
        self.assertIn(Keyword.TAUNT, self.body(g, Zone.HAND, 2).keywords); self.check(g)

    def test_base_copy_gains_receiver_ritual_taunt(self):
        self.script('copy', lambda c: (CopyCard(CardReference.capture(c.state.entities[c.state.players[2].hand[-1]]),
            1, mode='base'),))
        g = self.game(hand=(GEOMANCER, 'copy'), enemy_hand=(CTHUN,))
        self.play(g, GEOMANCER); self.play(g, 'copy')
        self.assertIn(Keyword.TAUNT, self.body(g, Zone.HAND).keywords); self.assertEqual(self.body(g, Zone.HAND).attack, 7)
        self.assertNotIn(Keyword.TAUNT, self.body(g, Zone.HAND, 2).keywords); self.check(g)

    def test_control_transfer_keeps_local_taunt_without_changing_receiver_bank(self):
        self.script('steal', lambda c: (ChangeControl(c.state.players[2].board[0], 1),))
        g = self.game(hand=('steal',), enemy_hand=(GEOMANCER,), enemy_board=(CTHUN,))
        g.apply(EndTurn(1)); self.play(g, GEOMANCER, 2); g.apply(EndTurn(2)); self.play(g, 'steal')
        self.assertFalse(ritual_taunt(g.state, 1)); self.assertIn(Keyword.TAUNT, self.body(g).keywords); self.check(g)

    def test_transform_into_cthun_skips_old_taunt_then_accepts_new_grant(self):
        self.script('transform', lambda c: (Transform(c.state.players[1].board[0], CTHUN),))
        g = self.game(hand=(GEOMANCER, 'transform', GEOMANCER), board=('plain',))
        self.play(g, GEOMANCER); self.play(g, 'transform')
        self.assertEqual(self.body(g).attack, 6); self.assertNotIn(Keyword.TAUNT, self.body(g).keywords)
        self.play(g, GEOMANCER); self.assertEqual(self.body(g).attack, 7)
        self.assertIn(Keyword.TAUNT, self.body(g).keywords); self.check(g)

    def test_transformed_body_catches_up_both_channels_only_on_reset(self):
        self.script('transform', lambda c: (Transform(c.state.players[1].board[0], CTHUN),))
        self.script('bounce', lambda c: (ReturnToHand(c.state.players[1].board[0]),))
        g = self.game(hand=(GEOMANCER, 'transform', 'bounce'), board=('plain',))
        self.play(g, GEOMANCER); self.play(g, 'transform'); self.play(g, 'bounce')
        e = self.body(g, Zone.HAND); self.assertEqual(e.attack, 7)
        self.assertIn(Keyword.TAUNT, e.keywords); self.check(g)

    def test_transform_out_clears_permanent_taunt(self):
        self.script('transform', lambda c: (Transform(c.state.players[1].board[0], 'plain'),))
        g = self.game(hand=(GEOMANCER, 'transform'), board=(CTHUN,))
        self.play(g, GEOMANCER); self.play(g, 'transform')
        e = self.body(g, cid='plain'); self.assertNotIn(Keyword.TAUNT, e.keywords)
        self.assertFalse(any(a.cthun_ritual for a in e.abilities)); self.check(g)

    def test_dead_record_is_fixed_and_new_resurrection_uses_current_ritual(self):
        self.script('kill', lambda c: (Destroy(c.state.players[1].board[0]),))
        self.script('resurrect', lambda c: (ResurrectMinion(1, c.state.death_history[0].id,
            source_id=c.source_id, cause=SummonCause.capture(c)),))
        g = self.game(hand=('kill', GEOMANCER, 'resurrect'), board=(CTHUN,))
        self.play(g, 'kill'); death = g.state.death_history[0]
        self.play(g, GEOMANCER); self.play(g, 'resurrect')
        self.assertEqual(death.attack, 6); self.assertIn(Keyword.TAUNT, self.body(g).keywords)
        self.assertEqual(self.body(g).attack, 7); self.check(g)

    def test_choice_waiting_restores_without_reapplying_accepted_taunt(self):
        self.script('wait', lambda c: (GrowCthun(1, 1, 1, c.source_id, taunt=True),
            RequestChoice(1, (ChoiceOption('ok', 'Continue', (GrowCthun(1, 2, 0, c.source_id),)),), c.source_id)))
        g = self.game(hand=('wait',), board=(CTHUN,)); self.play(g, 'wait')
        self.assertIn(Keyword.TAUNT, self.body(g).keywords); self.check(g)
        restored = Game.from_snapshot(g.snapshot(), registry(self.extras))
        action = SelectChoice(1, g.state.pending_choice.id, ('ok',))
        g.apply(action); restored.apply(action)
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual((self.body(g).attack, self.body(g).health), (9, 7))
        self.assertEqual(len([a for a in self.body(g).abilities if a.cthun_ritual]), 1); self.check(g)

    def test_failure_tail_rolls_back_taunt_numeric_history_payment_and_events(self):
        self.script('bad', lambda c: (GrowCthun(1, 1, 1, c.source_id, taunt=True), AddToHand(1, 'unknown')))
        g = self.game(hand=('bad',), board=(CTHUN,)); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'bad')
        self.assertEqual(g.snapshot(), before)

    def test_missing_profile_or_unknown_body_adapter_remains_explicit_error(self):
        g = self.game(no_profile=True); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, GEOMANCER)
        self.assertEqual(g.snapshot(), before)
        g = self.game(hand=(GEOMANCER, 'create'), missing=True); self.play(g, GEOMANCER); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'create')
        self.assertEqual(g.snapshot(), before)

    def test_private_taunt_history_is_not_exposed_to_player_views_or_logs(self):
        g = self.game(hand=(GEOMANCER, CTHUN)); self.play(g, GEOMANCER)
        self.assertIn(Keyword.TAUNT, self.body(g, Zone.HAND).keywords)
        for pid in (1, 2):
            text = json.dumps(g.observe(pid)) + json.dumps(g.player_events(pid))
            for private in ('cthun_history', 'cthun_ritual_grown', 'growth_id', 'first_id', 'last_id'):
                self.assertNotIn(private, text)
        self.check(g)

    def test_taunt_stamp_cannot_be_used_for_arbitrary_keyword_or_other_state(self):
        stamp = CthunRitualStamp(1, 1, 1, registry().cthun_profile.version)
        a = AbilityInstance(1, 'keyword', keyword=Keyword.TAUNT, remove_on_silence=False, cthun_ritual=stamp)
        for fields in ({'keyword': Keyword.RUSH}, {'remove_on_silence': True}, {'source_id': 1},
                       {'consumed': True}, {'expires_turn': 1}, {'origin': 'printed'}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                replace(a, **fields)

    def test_rehashed_taunt_record_and_receipt_changes_are_rejected(self):
        g = self.game(board=(CTHUN,)); self.play(g, GEOMANCER)
        self.rejected(g, lambda s: s['state']['cthun_history'][0].update(taunt=False))
        self.rejected(g, lambda s: next(e for e in s['events'] if e['kind'] == 'cthun_ritual_grown')['data'].update(taunt=False))
        self.rejected(g, lambda s: s['state']['cthun_history'][0].pop('taunt'))

    def test_rehashed_permanent_taunt_requires_original_taunt_scope(self):
        g = self.game(hand=(GEOMANCER, 'grow'), board=(CTHUN,)); self.play(g, GEOMANCER); self.play(g, 'grow')
        eid = str(self.body(g).id)
        self.rejected(g, lambda s: next(a for a in s['state']['entities'][eid]['abilities']
            if a['cthun_ritual'])['cthun_ritual'].update(first_id=2, last_id=2))

    def test_frozen_copy_taunt_provenance_cannot_point_to_numeric_only_row(self):
        self.script('copy', lambda c: (CopyMinion(c.state.players[1].board[0], 1,
            mode='current', cause=SummonCause.capture(c)),))
        g = self.game(hand=(GEOMANCER, 'grow', 'copy'), board=(CTHUN,))
        self.play(g, GEOMANCER); self.play(g, 'grow'); self.play(g, 'copy')
        self.rejected(g, lambda s: next(a for a in s['state']['card_summon_history'][0]
            ['request']['materials'][0]['local']['abilities'] if a['cthun_ritual'])
            ['cthun_ritual'].update(first_id=2, last_id=2))

    def test_reset_into_another_players_deck_uses_receivers_taunt_bank(self):
        self.script('shuffle', lambda c: (ShuffleIntoDeck(c.state.players[2].board[0], player_id=1),))
        g = self.game(hand=('shuffle',), enemy_hand=(GEOMANCER,), enemy_board=(CTHUN,))
        g.apply(EndTurn(1)); self.play(g, GEOMANCER, 2); g.apply(EndTurn(2)); self.play(g, 'shuffle')
        e = self.body(g, Zone.DECK); self.assertEqual(e.attack, 6)
        self.assertNotIn(Keyword.TAUNT, e.keywords); self.assertTrue(ritual_taunt(g.state, 2)); self.check(g)

    def test_rehashed_duplicate_taunt_contribution_is_rejected(self):
        g = self.game(board=(CTHUN,)); self.play(g, GEOMANCER)
        def duplicate(s):
            abilities = s['state']['entities'][str(self.body(g).id)]['abilities']
            row = deepcopy(next(a for a in abilities if a['cthun_ritual']))
            row['id'] = s['state']['next_attachment_id']
            s['state']['next_attachment_id'] += 1
            abilities.append(row)
        self.rejected(g, duplicate)


if __name__ == '__main__':
    unittest.main()
