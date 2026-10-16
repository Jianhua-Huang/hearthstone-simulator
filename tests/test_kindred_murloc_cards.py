"""Real Kindred bodies, complete tokens, expiry, physical draws and continuations."""
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.kindred_murloc_cards import load_batch, ROOTS, KINDRED
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, Keyword,
    PlayCard, PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption,
    Destroy, GainArmor, InvokeBehavior, RequestChoice, Silence, Summon)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

FIREGILL = 'DINO_404'; YESTERLOC = 'TIME_428'; SKIPPER = 'TLC_427'
THIEF = 'TLC_429'; DRAKE = 'TLC_243'; QUEEN = 'TLC_903'; BOOK = 'TLC_226'
ROCK = 'WW_001t'; TOKEN = 'TLC_429t'; YETI = 'CORE_CS2_182'; PRIMER = 'TLC_223'


def registry():
    r = build_registry()

    def choice(c, kind):
        e = c.state.entities.get(c.event.target_id)
        if e is None or (kind == 'token' and e.card_id != TOKEN) or (
                kind == 'draw' and c.event.source_id is None):
            return ()
        if kind == 'draw' and c.state.entities[c.event.source_id].card_id != BOOK:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', (GainArmor(c.state.players[c.player_id].hero_id, 1),)),
            ChoiceOption('bad', 'Fail', (InvokeBehavior('k63.fail', c.source_id, c.player_id),)),
        ), source_id=c.source_id),)

    def buff_hand(c):
        book = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id == BOOK)
        return (BuffStoredCard(CardReference.capture(book), 2, 3, c.source_id),)

    bodies = {
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'give': lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        'books_die': lambda c: tuple(Destroy(i, c.source_id)
            for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == BOOK),
        'buff_hand': buff_hand,
        'fail': lambda c: (AddToHand(c.player_id, 'k63.missing', c.source_id),),
    }
    for cid in ROOTS:
        if cid != YESTERLOC:
            bodies['summon_' + cid] = lambda c, cid=cid: (Summon(c.player_id, cid),)
    for name, body in bodies.items():
        r.register_behavior('k63.' + name, body)
        if name != 'fail':
            r.register_card(CardDefinition('k63.' + name, name, CardType.SPELL,
                on_play='k63.' + name, requires_target=name in ('kill', 'silence', 'give')))
    for kind, event in [('token', 'minion_summoned'), ('draw', 'card_drawn')]:
        r.register_behavior('k63.choice_' + kind, lambda c, kind=kind: choice(c, kind))
        r.register_card(CardDefinition('k63.choice_' + kind, kind, CardType.MINION,
            health=4, triggers=(TriggerSpec(event, 'k63.choice_' + kind),)))
    r.register_behavior('k63.fail_draw', lambda c: bodies['fail'](c)
        if c.event.source_id is not None and c.state.entities[c.event.source_id].card_id == BOOK else ())
    r.register_card(CardDefinition('k63.fail_draw', 'Late failure', CardType.MINION,
        health=4, triggers=(TriggerSpec('card_drawn', 'k63.fail_draw'),)))
    return r


class KindredMurlocCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = registry()

    def game(self, hand=(), board=(), deck=(YETI,)*12, enemy=(), enemy_hand=(), seed=1063):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
                mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(YETI,)*12,
                mana=30, max_mana=30, mana_cap=30)), seed=seed), self.r)

    def entity(self, g, cid, p=1, zone='board'):
        s = g.state
        return next(s.entities[i] for i in getattr(s.players[p], zone) if s.entities[i].card_id == cid)

    def play(self, g, cid, target=None, p=1):
        eid = self.entity(g, cid, p, 'hand').id
        g.apply(PlayCard(p, eid, target))
        return eid

    def cycle(self, g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def prime(self, g, cid=FIREGILL):
        self.play(g, cid); self.cycle(g)

    def portable(self, g):
        s = g.snapshot()
        self.assertEqual(Game.from_snapshot(s, registry()).snapshot(), s)
        self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), s)

    def test_complete_seven_roots_and_two_real_dependencies(self):
        data = load_batch()
        self.assertEqual(tuple(x['record']['id'] for x in data['cards']), ROOTS)
        self.assertEqual([x['record']['id'] for x in data['dependencies']], [ROCK, TOKEN])
        for row in data['cards'] + data['dependencies'] + data['source_evidence_only']:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        self.assertEqual((self.r.card(ROCK).kind, self.r.card(ROCK).cost), (CardType.SPELL, 1))
        self.assertEqual((self.r.card(TOKEN).attack, self.r.card(TOKEN).health), (1, 1))
        self.assertEqual(self.r.card(TOKEN).keywords, (Keyword.RUSH,))

    def test_default_representative_fingerprint_remains_unchanged(self):
        self.assertEqual(representative().fingerprint(),
            'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')

    def test_kindred_play_bodies_are_not_battlecries(self):
        for cid in KINDRED:
            self.assertIsNotNone(self.r.card(cid).on_play)
            self.assertIsNone(self.r.card(cid).battlecry)
        self.assertIsNotNone(self.r.card(SKIPPER).battlecry)

    def test_first_turn_kindred_does_not_activate(self):
        for cid in KINDRED:
            with self.subTest(card=cid):
                g = self.game((cid,), board=(YETI,))
                eid = self.play(g, cid)
                self.assertEqual(len(g.state.players[1].board), 2)
                self.assertNotIn(Keyword.IMMUNE, g.state.entities[eid].keywords)
                self.assertNotIn(Keyword.RUSH, self.entity(g, YETI).keywords)
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack, 0)

    def test_current_turn_murloc_is_not_previous_own_turn(self):
        g = self.game((SKIPPER, FIREGILL), board=(YETI,))
        self.play(g, SKIPPER); self.play(g, FIREGILL)
        self.assertNotIn(Keyword.RUSH, self.entity(g, YETI).keywords)

    def test_firegill_grants_other_friendly_minions_rush(self):
        g = self.game((SKIPPER, FIREGILL), board=(YETI,), enemy=(YETI,))
        self.prime(g, SKIPPER); eid = self.play(g, FIREGILL)
        self.assertIn(Keyword.RUSH, self.entity(g, YETI).keywords)
        self.assertIn(Keyword.RUSH, self.entity(g, SKIPPER).keywords)
        self.assertNotIn(Keyword.RUSH, g.state.entities[eid].keywords)
        self.assertNotIn(Keyword.RUSH, self.entity(g, YETI, 2).keywords)
        self.portable(g)

    def test_firegill_skips_dormant_minions_and_locations(self):
        g = self.game((SKIPPER, FIREGILL), board=(YETI, 'MEND_040', 'CORE_REV_990'))
        self.prime(g, SKIPPER); self.play(g, FIREGILL)
        self.assertIn(Keyword.RUSH, self.entity(g, YETI).keywords)
        self.assertNotIn(Keyword.RUSH, self.entity(g, 'MEND_040').keywords)
        self.assertNotIn(Keyword.RUSH, self.entity(g, 'CORE_REV_990').keywords)

    def test_firegill_granted_rush_survives_source_silence(self):
        g = self.game((SKIPPER, FIREGILL, 'k63.silence'), board=(YETI,))
        self.prime(g, SKIPPER); eid = self.play(g, FIREGILL)
        self.play(g, 'k63.silence', eid)
        self.assertIn(Keyword.RUSH, self.entity(g, YETI).keywords)

    def test_all_tribe_primer_can_activate_firegill(self):
        g = self.game(('DINO_435', FIREGILL), board=(YETI,))
        self.prime(g, 'DINO_435'); self.play(g, FIREGILL)
        self.assertIn(Keyword.RUSH, self.entity(g, YETI).keywords)

    def test_empty_latest_own_turn_replaces_older_murloc_match(self):
        g = self.game((SKIPPER, FIREGILL), board=(YETI,))
        self.prime(g, SKIPPER); self.cycle(g); self.play(g, FIREGILL)
        self.assertNotIn(Keyword.RUSH, self.entity(g, YETI).keywords)

    def test_opponents_murloc_does_not_activate_own_kindred(self):
        g = self.game((FIREGILL,), board=(YETI,), enemy_hand=(SKIPPER,))
        g.apply(EndTurn(1)); self.play(g, SKIPPER, p=2); g.apply(EndTurn(2))
        self.play(g, FIREGILL)
        self.assertNotIn(Keyword.RUSH, self.entity(g, YETI).keywords)

    def test_effect_summons_do_not_execute_kindred_or_battlecry(self):
        for cid in (*sorted(KINDRED), SKIPPER):
            with self.subTest(card=cid):
                primer = SKIPPER if cid in (FIREGILL, THIEF, SKIPPER) else PRIMER
                g = self.game((primer, 'k63.summon_' + cid), board=(YETI,))
                self.prime(g, primer)
                before_hand = len(g.state.players[1].hand)
                self.play(g, 'k63.summon_' + cid)
                self.assertEqual(len(g.state.players[1].board), 3)
                self.assertEqual(len(g.state.players[1].hand), before_hand-1)
                self.assertNotIn(Keyword.IMMUNE, self.entity(g, cid).keywords)
                self.assertNotIn(Keyword.RUSH, self.entity(g, YETI).keywords)
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack, 0)

    def test_yesterloc_buffs_only_other_own_minions_at_own_end(self):
        g = self.game(board=(YESTERLOC, YETI), enemy=(YETI,))
        g.apply(EndTurn(1))
        self.assertEqual(self.entity(g, YETI).max_health, 6)
        self.assertEqual(self.entity(g, YESTERLOC).max_health, 1)
        self.assertEqual(self.entity(g, YETI, 2).max_health, 5)
        g.apply(EndTurn(2)); self.assertEqual(self.entity(g, YETI).max_health, 6)
        self.portable(g)

    def test_yesterloc_two_physical_sources_buff_each_other(self):
        g = self.game(board=(YESTERLOC, YESTERLOC, YETI))
        g.apply(EndTurn(1)); s = g.state
        self.assertEqual([s.entities[i].max_health for i in s.players[1].board], [2, 2, 7])

    def test_yesterloc_silence_removes_end_body(self):
        g = self.game(('k63.silence',), board=(YESTERLOC, YETI))
        self.play(g, 'k63.silence', self.entity(g, YESTERLOC).id); g.apply(EndTurn(1))
        self.assertEqual(self.entity(g, YETI).max_health, 5)

    def test_yesterloc_follows_current_controller_end(self):
        g = self.game(('k63.give',), board=(YESTERLOC, YETI), enemy=(YETI,))
        self.play(g, 'k63.give', self.entity(g, YESTERLOC).id); g.apply(EndTurn(1))
        self.assertEqual(self.entity(g, YETI).max_health, 5)
        g.apply(EndTurn(2)); self.assertEqual(self.entity(g, YETI, 2).max_health, 6)
        self.portable(g)

    def test_real_repeat_source_repeats_end_body(self):
        g = self.game(board=('TIME_064', YESTERLOC, YETI))
        g.apply(EndTurn(1)); self.assertEqual(self.entity(g, YETI).max_health, 7)

    def test_rockskipper_gives_original_rock_and_pays_actual_cost(self):
        g = self.game((SKIPPER,)); before = g.state.players[1].mana
        self.play(g, SKIPPER); self.assertEqual(g.state.players[1].mana, before-2)
        self.assertEqual(self.entity(g, ROCK, zone='hand').base_cost, 1)
        self.play(g, ROCK, g.state.players[2].hero_id)
        self.assertEqual(g.state.players[1].mana, before-3)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)
        self.portable(g)

    def test_rock_uses_spell_damage_and_can_target_friendly_characters(self):
        g = self.game((ROCK,), board=('CORE_EX1_012',))
        self.play(g, ROCK, g.state.players[1].hero_id)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 26)

    def test_rock_requires_target_and_invalid_submission_rolls_back(self):
        g = self.game((ROCK,)); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, ROCK)
        self.assertEqual(g.snapshot(), before)

    def test_repeated_rockskipper_respects_hand_capacity(self):
        g = self.game((SKIPPER,) + (YETI,)*9, board=('TIME_064',))
        self.play(g, SKIPPER)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertEqual(sum(e.card_id == ROCK for e in g.state.entities.values()), 2)
        self.assertEqual(sum(g.state.entities[i].card_id == ROCK for i in g.state.players[1].hand), 1)

    def test_thief_summons_two_real_one_one_rush_murlocs(self):
        g = self.game((SKIPPER, THIEF), enemy=(YETI,))
        self.prime(g, SKIPPER); self.play(g, THIEF)
        tokens = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == TOKEN]
        self.assertEqual([(e.attack, e.health, e.keywords) for e in tokens], [(1, 1, {Keyword.RUSH})]*2)
        with self.assertRaises(IllegalAction): g.apply(Attack(1, tokens[0].id, g.state.players[2].hero_id))
        g.apply(Attack(1, tokens[0].id, self.entity(g, YETI, 2).id))
        self.assertEqual(g.state.entities[tokens[0].id].zone, Zone.GRAVEYARD)
        self.portable(g)

    def test_thief_respects_one_remaining_board_slot(self):
        g = self.game((SKIPPER, THIEF), board=(YETI,)*4)
        self.prime(g, SKIPPER); self.play(g, THIEF)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual(sum(g.state.entities[i].card_id == TOKEN for i in g.state.players[1].board), 1)

    def test_battlecry_repeat_source_does_not_repeat_kindred(self):
        g = self.game((SKIPPER, THIEF), board=('TIME_064',))
        self.prime(g, SKIPPER); self.play(g, THIEF)
        self.assertEqual(sum(g.state.entities[i].card_id == TOKEN for i in g.state.players[1].board), 2)

    def test_stormdrake_immune_expires_at_end_of_current_turn(self):
        g = self.game((PRIMER, DRAKE, ROCK), enemy_hand=(ROCK,))
        self.prime(g, PRIMER); eid = self.play(g, DRAKE)
        self.assertIn(Keyword.IMMUNE, g.state.entities[eid].keywords)
        self.play(g, ROCK, eid); self.assertEqual(g.state.entities[eid].health, 8)
        g.apply(EndTurn(1)); self.assertNotIn(Keyword.IMMUNE, g.state.entities[eid].keywords)
        self.play(g, ROCK, eid, p=2); self.assertEqual(g.state.entities[eid].health, 5)
        self.portable(g)

    def test_stormdrake_retains_rush_windfury_and_immune_combat(self):
        g = self.game((PRIMER, DRAKE), enemy=(YETI, YETI))
        self.prime(g, PRIMER); eid = self.play(g, DRAKE)
        with self.assertRaises(IllegalAction): g.apply(Attack(1, eid, g.state.players[2].hero_id))
        for _ in range(2): g.apply(Attack(1, eid, self.entity(g, YETI, 2).id))
        self.assertEqual(g.state.entities[eid].health, 8)
        self.assertIn(Keyword.WINDFURY, g.state.entities[eid].keywords)
        with self.assertRaises(IllegalAction): g.apply(Attack(1, eid, g.state.players[2].hero_id))

    def test_queen_grants_hero_attack_only_for_current_turn(self):
        g = self.game((PRIMER, QUEEN)); self.prime(g, PRIMER); self.play(g, QUEEN)
        hero = g.state.players[1].hero_id
        self.assertEqual(g.state.entities[hero].attack, 5)
        g.apply(Attack(1, hero, g.state.players[2].hero_id)); g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[hero].attack, 0)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 25)
        self.portable(g)

    def test_queen_kindred_is_not_doubled_by_battlecry_repeat(self):
        g = self.game((PRIMER, QUEEN), board=('TIME_064',))
        self.prime(g, PRIMER); self.play(g, QUEEN)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack, 5)

    def test_bookkeeper_copies_current_hand_buff_and_deathrattle(self):
        g = self.game((PRIMER, BOOK, 'k63.buff_hand'))
        self.prime(g, PRIMER); self.play(g, 'k63.buff_hand'); self.play(g, BOOK)
        books = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == BOOK]
        self.assertEqual([(e.attack, e.health) for e in books], [(4, 5), (4, 5)])
        self.assertTrue(all(any(a.kind == 'deathrattle' for a in e.abilities) for e in books))
        self.portable(g)

    def test_bookkeeper_original_and_copy_each_draw_one_physical_spell(self):
        g = self.game((PRIMER, BOOK, 'k63.books_die'), deck=(YETI, ROCK, ROCK, YETI))
        self.prime(g, PRIMER); self.play(g, BOOK); self.play(g, 'k63.books_die')
        self.assertEqual(sum(g.state.entities[i].card_id == ROCK for i in g.state.players[1].hand), 2)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck], [YETI])
        self.portable(g)

    def test_bookkeeper_empty_spell_pool_skips_without_fatigue(self):
        g = self.game((BOOK, 'k63.kill'), deck=()); eid = self.play(g, BOOK)
        before = g.state.entities[g.state.players[1].hero_id].health
        self.play(g, 'k63.kill', eid)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, before)
        self.assertFalse(g.state.draw_history)

    def test_bookkeeper_silence_removes_draw_deathrattle(self):
        g = self.game((BOOK, 'k63.kill', 'k63.silence'), deck=(ROCK,))
        eid = self.play(g, BOOK); self.play(g, 'k63.silence', eid); self.play(g, 'k63.kill', eid)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck], [ROCK])

    def test_each_token_waiting_checkpoint_restores_and_resumes(self):
        g = self.game((SKIPPER, THIEF), board=('k63.choice_token',))
        self.prime(g, SKIPPER); self.play(g, THIEF); waits = 0
        while g.state.pending_choice is not None:
            waits += 1; self.portable(g)
            before = g.snapshot(); choice = g.state.pending_choice
            with self.assertRaises(ResolutionError): g.apply(SelectChoice(1, choice.id, ('bad',)))
            self.assertEqual(g.snapshot(), before)
            g.apply(SelectChoice(1, choice.id, ('ok',)))
        self.assertEqual(waits, 2)
        self.assertEqual(sum(g.state.entities[i].card_id == TOKEN for i in g.state.players[1].board), 2)
        self.portable(g)

    def test_physical_deathrattle_draw_can_pause_and_restore(self):
        g = self.game((BOOK, 'k63.kill'), board=('k63.choice_draw',), deck=(ROCK,))
        eid = self.play(g, BOOK); self.play(g, 'k63.kill', eid)
        self.assertIsNotNone(g.state.pending_choice); self.portable(g)
        g.apply(SelectChoice(1, g.state.pending_choice.id, ('ok',))); self.portable(g)
        self.assertEqual(self.entity(g, ROCK, zone='hand').zone, Zone.HAND)

    def test_late_draw_failure_rolls_back_death_physical_draw_and_rng(self):
        g = self.game((BOOK, 'k63.kill'), board=('k63.fail_draw',), deck=(ROCK, ROCK))
        eid = self.play(g, BOOK); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'k63.kill', eid)
        self.assertEqual(g.snapshot(), before)

    def test_player_queries_preserve_state_and_hide_enemy_generated_rock(self):
        g = self.game((SKIPPER,), enemy_hand=(BOOK,)); self.play(g, SKIPPER); before = g.snapshot()
        for p in (1, 2):
            g.for_player(p).observe(); g.for_player(p).legal_actions()
        self.assertEqual(g.snapshot(), before)
        enemy_view = g.observe(2)
        hidden_hand = next(p['hand'] for p in enemy_view['players'] if p['id'] == 1)
        self.assertTrue(hidden_hand)
        self.assertTrue(all(set(row) == {'ref', 'card_id'} and row['card_id'] is None
            for row in hidden_hand))


if __name__ == '__main__':
    unittest.main()
