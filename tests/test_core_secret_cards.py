"""Current Core secrets, exact identities and normal hidden-secret lifecycles."""
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.core_secret_cards import load_batch
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, CastSpell,
    EndTurn, Game, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, DamageBatch, InvokeBehavior,
    RequestChoice, Summon)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.model import DamageKind
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest

ALIASES = ('CORE_EX1_287', 'CORE_EX1_289', 'CORE_EX1_610', 'CORE_EX1_611')


def registry(wait=False):
    r = build_registry(); meta = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
    r.register_card(CardDefinition('k13.hero', 'Hero', CardType.HERO, health=100, metadata=meta))
    for cid, attack, health in (('a', 2, 5), ('small', 2, 2), ('b', 3, 6)):
        r.register_card(CardDefinition('k13.'+cid, cid, CardType.MINION, cost=3,
            attack=attack, health=health, keywords=(Keyword.CHARGE,), metadata=meta))
    scripts = {
        'nothing': lambda c: (),
        'hit': lambda c: (Damage(c.state.players[3-c.player_id].hero_id, 4, c.source_id, DamageKind.SPELL),),
        'clear_enemy': lambda c: (DamageBatch(tuple(Damage(e, 10, c.source_id, DamageKind.SPELL)
                                   for e in c.state.players[3-c.player_id].board)),),
        'fail': lambda c: (AddToHand(c.player_id, 'missing.k13'),),
    }
    for cid, body in scripts.items():
        r.register_behavior('k13.'+cid, body)
        r.register_card(CardDefinition('k13.'+cid, cid, CardType.SPELL, on_play='k13.'+cid, metadata=meta))
    r.register_behavior('k13.auto', lambda c: (CastSpell(c.player_id, 'k13.nothing', c.source_id),))
    r.register_card(CardDefinition('k13.auto', 'Minion effect caster', CardType.MINION,
        health=5, battlecry='k13.auto', metadata=meta))
    r.register_behavior('k13.summoner', lambda c: (Summon(c.player_id, 'k13.a'),))
    r.register_card(CardDefinition('k13.summoner', 'Ordinary summoner', CardType.MINION,
        health=5, battlecry='k13.summoner', metadata=meta))
    if wait:
        r.register_behavior('k13.pause', lambda c: (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Finish revealed secret'),
            ChoiceOption('bad', 'Rollback', (InvokeBehavior('k13.fail', c.source_id, c.player_id),)),
        ), c.source_id),))
        r.register_card(CardDefinition('k13.watch', 'Reveal observer', CardType.MINION, health=10,
            triggers=(TriggerSpec('secret_revealed', 'k13.pause'),), metadata=meta))
    return r


class CoreSecretCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.r = registry()
    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), wait=False):
        self.wait = wait
        return Game.from_scenario(Scenario((
            PlayerSetup('k13.hero', hand=hand, board=board, deck=('k13.nothing',)*6,
                        mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('k13.hero', hand=enemy_hand, board=enemy, deck=('k13.nothing',)*6,
                        mana=30, max_mana=30, mana_cap=30)), seed=211), registry(True) if wait else self.r)
    def eid(self, g, cid, p=1):
        return next(e for e in g.state.players[p].hand if g.state.entities[e].card_id == cid)
    def play(self, g, cid, p=1):
        eid = self.eid(g, cid, p); g.apply(PlayCard(p, eid)); return eid
    def turn_two(self, g): g.apply(EndTurn(1))
    def portable(self, g):
        saved = g.snapshot(); other = Game.from_snapshot(saved, registry(self.wait))
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(self.wait)).snapshot(), saved); return other
    def hero(self, g, p=1): return g.state.entities[g.state.players[p].hero_id]
    def attack(self, g, target=None):
        g.apply(Attack(2, g.state.players[2].board[0], target or g.state.players[1].hero_id))
    def finish(self, g, option='continue'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (option,)))

    def test_seven_complete_roots_rat_and_exact_existing_water_are_pinned(self):
        data = load_batch(); self.assertEqual((len(data['cards']), sum(x['recipe']['root'] for x in data['cards'])), (8, 7))
        for row in (*data['cards'], *data['reused_dependencies']):
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        for cid in ALIASES:
            self.assertEqual(self.r.card(cid).secret, self.r.card(cid[5:]).secret)
            self.assertEqual(self.r.card(cid).metadata.deck_identity, cid[5:])
        self.assertEqual((self.r.card('GIL_577t').attack, self.r.card('GIL_577t').health), (6, 6))
        self.assertEqual(self.r.card('CS2_033').metadata.tribes, ('elemental',))
        self.assertNotIn('CORE_LOOT_101', {row['record']['id'] for row in data['cards']})

    def test_all_four_aliases_deploy_paid_with_canonical_duplicate_prevention(self):
        for cid in ALIASES:
            with self.subTest(card=cid):
                g = self.game((cid, cid, cid[5:])); self.play(g, cid)
                self.assertEqual(len(g.state.players[1].secrets), 1)
                self.assertEqual(g.state.players[1].mana, 30-self.r.card(cid).cost)
                saved = g.snapshot()
                for duplicate in (cid, cid[5:]):
                    with self.assertRaises(IllegalAction): self.play(g, duplicate)
                    self.assertEqual(g.snapshot(), saved)
                self.portable(g)

    def test_current_counterspell_consumes_once_keeps_payment_and_suppresses_body(self):
        g = self.game(('CORE_EX1_287',), enemy_hand=('k13.hit', 'k13.hit'))
        self.play(g, 'CORE_EX1_287'); self.turn_two(g); self.play(g, 'k13.hit', 2)
        self.assertEqual(self.hero(g).health, 100)
        self.assertTrue(g.state.play_history[-1].countered); self.assertFalse(g.state.players[1].secrets)
        self.play(g, 'k13.hit', 2); self.assertEqual(self.hero(g).health, 96); self.portable(g)

    def test_current_barrier_adds_eight_before_actual_combat(self):
        g = self.game(('CORE_EX1_289',), enemy=('k13.a',))
        self.play(g, 'CORE_EX1_289'); self.turn_two(g); self.attack(g)
        self.assertEqual((self.hero(g).health, self.hero(g).armor), (100, 6)); self.portable(g)

    def test_current_explosive_trap_hits_all_enemies_and_cancels_dead_attacker(self):
        g = self.game(('CORE_EX1_610',), enemy=('k13.small', 'k13.b'))
        self.play(g, 'CORE_EX1_610'); self.turn_two(g); self.attack(g)
        self.assertEqual((self.hero(g).health, self.hero(g, 2).health), (100, 98))
        self.assertEqual(len(g.state.players[2].board), 1)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health, 4); self.portable(g)

    def test_current_freezing_trap_returns_actual_attacker_with_two_more_cost(self):
        g = self.game(('CORE_EX1_611',), enemy=('k13.a',))
        self.play(g, 'CORE_EX1_611'); self.turn_two(g); original = g.state.players[2].board[0]; self.attack(g)
        self.assertIn(original, g.state.players[2].hand)
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[original]).amount, 5)
        self.assertEqual(self.hero(g).health, 100); self.portable(g)

    def test_oasis_triggers_only_for_friendly_minion_attack_and_summons_real_water(self):
        g = self.game(('CORE_BAR_812',), ('k13.a',), ('k13.b',))
        self.play(g, 'CORE_BAR_812'); self.turn_two(g); target = g.state.players[1].board[0]
        self.attack(g, target)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].board], ['k13.a', 'CS2_033'])
        water = g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual((water.attack, water.health), (3, 6)); self.portable(g)

    def test_oasis_does_not_consume_for_hero_attack_or_a_full_owner_board(self):
        for full in (False, True):
            g = self.game(('CORE_BAR_812',), ('k13.a',)*7 if full else (), ('k13.b',))
            self.play(g, 'CORE_BAR_812'); self.turn_two(g)
            self.attack(g, g.state.players[1].board[0] if full else None)
            self.assertEqual(len(g.state.players[1].secrets), 1); self.portable(g)

    def test_summoned_water_freezes_after_real_damage_and_keeps_full_behavior(self):
        g = self.game(('CORE_BAR_812',), ('k13.b',), ('k13.a',))
        self.play(g, 'CORE_BAR_812'); self.turn_two(g); self.attack(g, g.state.players[1].board[0])
        g.apply(EndTurn(2)); water = next(e for e in g.state.players[1].board if g.state.entities[e].card_id == 'CS2_033')
        g.apply(Attack(1, water, g.state.players[2].hero_id))
        self.assertTrue(self.hero(g, 2).frozen); self.assertEqual(self.hero(g, 2).health, 97); self.portable(g)

    def test_rat_trap_counts_three_actual_hand_submissions_and_summons_six_six(self):
        g = self.game(('CORE_GIL_577',), enemy_hand=('k13.nothing',)*3)
        self.play(g, 'CORE_GIL_577'); self.turn_two(g)
        for _ in range(2): self.play(g, 'k13.nothing', 2)
        self.assertTrue(g.state.players[1].secrets); self.assertFalse(g.state.players[1].board)
        self.play(g, 'k13.nothing', 2); rat = g.state.entities[g.state.players[1].board[0]]
        self.assertEqual((rat.card_id, rat.attack, rat.health), ('GIL_577t', 6, 6)); self.portable(g)

    def test_rat_counts_countered_hand_play_but_not_automatic_cast_or_extra_summon(self):
        g = self.game(('CORE_EX1_287', 'CORE_GIL_577'), enemy_hand=('k13.nothing', 'k13.auto', 'k13.summoner'))
        self.play(g, 'CORE_EX1_287'); self.play(g, 'CORE_GIL_577'); self.turn_two(g)
        self.play(g, 'k13.nothing', 2); self.play(g, 'k13.auto', 2)
        self.assertFalse(g.state.players[1].board)
        self.play(g, 'k13.summoner', 2)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].board], ['GIL_577t']); self.portable(g)

    def test_rat_count_restarts_on_new_turn_and_full_board_can_trigger_after_later_space(self):
        g = self.game(('CORE_GIL_577',), ('k13.a',)*7, enemy_hand=('k13.nothing',)*3+('k13.clear_enemy',))
        self.play(g, 'CORE_GIL_577'); self.turn_two(g)
        for _ in range(3): self.play(g, 'k13.nothing', 2)
        self.assertTrue(g.state.players[1].secrets)
        self.play(g, 'k13.clear_enemy', 2)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].board], ['GIL_577t']); self.portable(g)
        g = self.game(('CORE_GIL_577',), enemy_hand=('k13.nothing',)*3)
        self.play(g, 'CORE_GIL_577'); self.turn_two(g)
        for _ in range(2): self.play(g, 'k13.nothing', 2)
        g.apply(EndTurn(2)); g.apply(EndTurn(1)); self.play(g, 'k13.nothing', 2)
        self.assertTrue(g.state.players[1].secrets); self.portable(g)

    def test_pressure_triggers_after_full_spell_body_and_uses_current_enemy_candidates(self):
        g = self.game(('CORE_ULD_152',), enemy=('k13.a', 'k13.b'), enemy_hand=('k13.hit',))
        self.play(g, 'CORE_ULD_152'); self.turn_two(g); self.play(g, 'k13.hit', 2)
        self.assertEqual(self.hero(g).health, 96); self.assertEqual(len(g.state.players[2].board), 1)
        self.assertEqual(sum(e.kind == 'random_choice' for e in g.events), 1)
        self.assertFalse(g.state.players[1].secrets); self.portable(g)

    def test_pressure_does_not_consume_for_automatic_minion_cast_or_countered_spell(self):
        g = self.game(('CORE_EX1_287', 'CORE_ULD_152'), enemy=('k13.a',), enemy_hand=('k13.auto', 'k13.hit'))
        self.play(g, 'CORE_EX1_287'); self.play(g, 'CORE_ULD_152'); self.turn_two(g)
        self.play(g, 'k13.auto', 2); self.assertEqual(len(g.state.players[1].secrets), 2)
        self.play(g, 'k13.hit', 2); self.assertEqual(len(g.state.players[1].secrets), 1)
        self.assertEqual(g.state.entities[g.state.players[1].secrets[0]].card_id, 'CORE_ULD_152'); self.portable(g)

    def test_pressure_empty_enemy_board_consumes_no_rng_and_keeps_secret(self):
        g = self.game(('CORE_ULD_152',), enemy_hand=('k13.nothing',))
        self.play(g, 'CORE_ULD_152'); self.turn_two(g); rng = g.snapshot()['rng_state']; self.play(g, 'k13.nothing', 2)
        self.assertEqual(g.snapshot()['rng_state'], rng); self.assertEqual(len(g.state.players[1].secrets), 1)
        self.portable(g)

    def test_reveal_waiting_restores_then_completes_each_new_body_once(self):
        for cid in ('CORE_BAR_812', 'CORE_GIL_577', 'CORE_ULD_152'):
            with self.subTest(card=cid):
                g = self.game((cid,), ('k13.a', 'k13.watch'), ('k13.b',), ('k13.nothing',)*3, wait=True)
                self.play(g, cid); self.turn_two(g)
                if cid == 'CORE_BAR_812': self.attack(g, g.state.players[1].board[0])
                else:
                    for _ in range(3 if cid == 'CORE_GIL_577' else 1): self.play(g, 'k13.nothing', 2)
                self.assertIsNotNone(g.state.pending_choice); self.assertFalse(g.state.players[1].secrets)
                saved = g.snapshot()
                with self.assertRaises(ResolutionError): self.finish(g, 'bad')
                self.assertEqual(g.snapshot(), saved); other = self.portable(g)
                self.finish(g); self.finish(other); self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_opponent_projection_of_unrevealed_same_class_core_secrets_is_identical(self):
        observations = []
        for cid in ('CORE_EX1_287', 'CORE_EX1_289'):
            g = self.game((cid,), enemy_hand=('k13.hit',)); self.play(g, cid)
            observations.append((g.for_player(2).observe(), g.for_player(2).legal_actions(), g.player_events(2)))
            self.assertNotIn(cid, json.dumps(observations[-1])); self.portable(g)
        self.assertEqual(observations[0], observations[1])


if __name__ == '__main__': unittest.main()
