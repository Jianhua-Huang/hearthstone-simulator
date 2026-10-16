"""Actual return consumers, current hand weapons and suspended original effects."""
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.return_hand_cards import load_batch
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, CostSpec,
    EndTurn, Game, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, Damage,
    GainArmor, InvokeBehavior, RequestChoice, ReturnToHand)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import TargetMode, TargetSpec
from hs_sim.engine.return_followups import RandomReturnCapturedMinion, ReturnCapturedMinion
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.targets import canonical_digest


def registry(mode=None):
    r = build_registry(); meta = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
    r.register_card(CardDefinition('k12.hero', 'Hero', CardType.HERO, health=100, metadata=meta))
    for cid, attack, health in (('a', 3, 5), ('b', 2, 6)):
        r.register_card(CardDefinition('k12.'+cid, cid, CardType.MINION, cost=4,
            attack=attack, health=health, metadata=meta))
    r.register_behavior('k12.dr', lambda c: (GainArmor(c.player_id, 3),))
    r.register_card(CardDefinition('k12.dr', 'Deathrattle', CardType.MINION, cost=4,
        attack=3, health=5, deathrattle='k12.dr', metadata=meta))
    r.register_card(CardDefinition('k12.dormant', 'Dormant', CardType.MINION, health=4,
        dormant_turns=2, metadata=meta))
    r.register_behavior('k12.noop', lambda c: ())
    r.register_card(CardDefinition('k12.location', 'Location', CardType.LOCATION, cost=3,
        durability=2, on_use='k12.noop', metadata=meta))
    r.register_card(CardDefinition('k12.weapon', 'Replacement weapon', CardType.WEAPON,
        cost=3, attack=2, durability=3, metadata=meta))
    r.register_behavior('k12.fail', lambda c: (AddToHand(c.player_id, 'missing.k12'),))
    def target(c): return c.state.entities[c.target_id]
    def captured(c): return MinionReference.capture(target(c))
    scripts = {
        'steal': lambda c: (ChangeControl(c.target_id, c.player_id),),
        'give': lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        'double': lambda c: (ReturnCapturedMinion(captured(c), c.source_id,
                                on_success=(GainArmor(c.player_id, 5),)),
                             ReturnCapturedMinion(captured(c), c.source_id,
                                on_success=(GainArmor(c.player_id, 5),))),
        'rollback': lambda c: (ReturnCapturedMinion(captured(c), c.source_id),
                               InvokeBehavior('k12.fail', c.source_id, c.player_id)),
        'material': lambda c: (Buff(c.target_id, 2, 3, c.source_id), Damage(c.target_id, 2, c.source_id),
                               ReturnCapturedMinion(captured(c), c.source_id, cost=CostSpec(delta=-2))),
        'weapon_health': lambda c: (BuffStoredCard(CardReference.capture(next(c.state.entities[e]
             for e in c.state.players[c.player_id].hand if c.state.entities[e].kind == CardType.WEAPON)),
             0, 1, c.source_id),),
    }
    for name, body in scripts.items():
        r.register_behavior('k12.'+name, body)
        targeting = None if name == 'weapon_health' else TargetSpec(TargetMode.REQUIRED,
            kinds=(CardType.MINION,), zones=(Zone.BOARD,))
        r.register_card(CardDefinition('k12.'+name, name, CardType.SPELL, on_play='k12.'+name,
            targeting=targeting, metadata=meta))
    if mode is not None:
        def watch(c):
            if c.event.kind == 'card_committed':
                return (AddToHand(c.player_id, 'k12.a'),) if mode == 'full' and (
                    c.state.entities[c.event.source_id].card_id == 'EDR_523') else ()
            if c.event.kind == 'random_choice':
                if mode != 'random_wait': return ()
                return (RequestChoice(c.player_id, (
                    ChoiceOption('continue', 'Return the original random minion'),
                    ChoiceOption('shift', 'Original selection leaves', (ChangeControl(c.event.target_id, 3-c.player_id),)),
                    ChoiceOption('bad', 'Rollback', (InvokeBehavior('k12.fail', c.source_id, c.player_id),)),
                ), c.source_id),)
            if c.event.kind != 'card_returned': return ()
            returned = c.state.entities[c.event.target_id]
            if mode == 'move':
                return (MoveCard(CardReference.capture(returned), returned.controller, Zone.DECK, source_id=c.source_id),)
            if mode == 'shift_second':
                rest = next((e for e in c.state.players[2].board if c.state.entities[e].card_id == 'k12.b'), None)
                return () if rest is None else (ChangeControl(rest, 1),)
            if mode != 'wait': return ()
            return (RequestChoice(c.player_id, (
                ChoiceOption('continue', 'Continue after actual return'),
                ChoiceOption('bad', 'Rollback', (InvokeBehavior('k12.fail', c.source_id, c.player_id),)),
            ), c.source_id),)
        r.register_behavior('k12.watch', watch)
        r.register_card(CardDefinition('k12.watch', 'Observer', CardType.MINION, health=6,
            triggers=tuple(TriggerSpec(event, 'k12.watch') for event in ('card_committed', 'card_returned', 'random_choice')),
            metadata=meta))
    return r


class ReturnHandCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.r = registry()
    def game(self, hand=(), board=(), enemy=(), mode=None, weapon=None, enemy_hand=(), hand_cap=None):
        self.mode = mode
        return Game.from_scenario(Scenario((
            PlayerSetup('k12.hero', hand=hand, board=board, deck=('k12.a',)*6,
                        weapon_card_id=weapon, mana=30, max_mana=30, mana_cap=30, hand_cap=hand_cap),
            PlayerSetup('k12.hero', hand=enemy_hand, board=enemy, deck=('k12.a',)*6,
                        mana=30, max_mana=30, mana_cap=30)), seed=191), registry(mode) if mode else self.r)
    def eid(self, g, cid, p=1, zone=Zone.HAND):
        return next(e for e in getattr(g.state.players[p], zone.value) if g.state.entities[e].card_id == cid)
    def play(self, g, cid, target=None, p=1):
        eid = self.eid(g, cid, p); g.apply(PlayCard(p, eid, target_id=target)); return eid
    def portable(self, g):
        s = g.snapshot(); other = Game.from_snapshot(s, registry(self.mode))
        self.assertEqual(other.snapshot(), s); self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), registry(self.mode)).snapshot(), s); return other
    def finish(self, g, option='continue'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (option,)))
    def price(self, g, cid, p=1):
        return quote_cost(g.state, g.registry, g.state.entities[self.eid(g, cid, p)]).amount

    def test_five_complete_roots_and_real_spider_are_pinned(self):
        rows = load_batch()['cards']; self.assertEqual((len(rows), sum(x['recipe']['root'] for x in rows)), (6, 5))
        for row in rows:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
            self.assertEqual(self.r.card(row['record']['id']).cost, row['record']['cost'])
        spider = self.r.card('EDR_523t'); self.assertEqual((spider.attack, spider.health), (4, 4))
        self.assertIn(Keyword.STEALTH, spider.keywords)

    def test_matriarch_returns_all_active_enemy_minions_to_owners_in_original_order(self):
        g = self.game(('CATA_201',), enemy=('k12.a', 'k12.b', 'k12.dormant', 'k12.location'))
        original = g.state.players[2].board[:2]; self.play(g, 'CATA_201')
        self.assertEqual(g.state.players[2].hand, original)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[2].board], ['k12.dormant', 'k12.location'])
        self.assertEqual(len(g.state.death_history), 0); self.portable(g)

    def test_matriarch_respects_original_owner_after_enemy_control(self):
        g = self.game(('k12.give', 'CATA_201'), ('k12.a',), ('k12.b',))
        own = g.state.players[1].board[0]; self.play(g, 'k12.give', own); self.play(g, 'CATA_201')
        self.assertIn(own, g.state.players[1].hand)
        self.assertEqual(g.state.entities[own].owner, 1); self.assertEqual(g.state.entities[own].controller, 1)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[2].hand], ['k12.b']); self.portable(g)

    def test_matriarch_captured_tail_is_not_redirected_after_control_change(self):
        g = self.game(('CATA_201',), enemy=('k12.a', 'k12.watch', 'k12.b'), mode='shift_second')
        tail = self.eid(g, 'k12.b', 2, Zone.BOARD); self.play(g, 'CATA_201')
        self.assertIn(tail, g.state.players[1].board); self.assertNotIn(tail, g.state.players[2].hand)
        self.portable(g)

    def test_web_returns_same_physical_card_then_summons_full_stealth_spider(self):
        g = self.game(('EDR_523',), ('k12.a',)); target = g.state.players[1].board[0]
        self.play(g, 'EDR_523', target)
        self.assertEqual(g.state.players[1].hand, [target])
        spider = g.state.entities[g.state.players[1].board[0]]
        self.assertEqual((spider.card_id, spider.attack, spider.health), ('EDR_523t', 4, 4))
        self.assertIn(Keyword.STEALTH, spider.keywords); self.portable(g)

    def test_web_requires_friendly_actual_target_and_does_not_play_without_one(self):
        g = self.game(('EDR_523',), enemy=('k12.a',)); saved = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, 'EDR_523', g.state.players[2].board[0])
        self.assertEqual(g.snapshot(), saved)
        self.assertFalse(any(getattr(a, 'entity_id', None) == self.eid(g, 'EDR_523') for a in g.legal_actions()))

    def test_web_full_hand_failure_causes_normal_death_and_no_spider(self):
        g = self.game(('EDR_523', 'k12.a'), ('k12.dr', 'k12.watch'), mode='full', hand_cap=2)
        target = self.eid(g, 'k12.dr', zone=Zone.BOARD); self.play(g, 'EDR_523', target)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.death_history), 1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 3)
        self.assertFalse(any(g.state.entities[e].card_id == 'EDR_523t' for e in g.state.players[1].board)); self.portable(g)

    def test_web_success_is_preserved_when_returned_card_moves_before_summon(self):
        g = self.game(('EDR_523',), ('k12.a', 'k12.watch'), mode='move')
        target = self.eid(g, 'k12.a', zone=Zone.BOARD); self.play(g, 'EDR_523', target)
        self.assertIn(target, g.state.players[1].deck)
        self.assertEqual(sum(g.state.entities[e].card_id == 'EDR_523t' for e in g.state.players[1].board), 1)
        self.portable(g)

    def test_waiting_after_actual_return_restores_success_once_and_rolls_back_bad_choice(self):
        g = self.game(('EDR_523',), ('k12.a', 'k12.watch'), mode='wait')
        target = self.eid(g, 'k12.a', zone=Zone.BOARD); self.play(g, 'EDR_523', target)
        self.assertIn(target, g.state.players[1].hand); self.assertEqual(g.state.players[1].mana, 28)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.finish(g, 'bad')
        self.assertEqual(g.snapshot(), saved); other = self.portable(g)
        self.finish(g); self.finish(other); self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(sum(g.state.entities[e].card_id == 'EDR_523t' for e in g.state.players[1].board), 1)
        self.assertEqual(g.state.players[1].mana, 28); self.portable(g)

    def test_captured_duplicate_return_does_not_repeat_success_reward(self):
        g = self.game(('k12.double',), ('k12.a',)); self.play(g, 'k12.double', g.state.players[1].board[0])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 5); self.portable(g)

    def test_original_material_resets_before_successful_return_discount(self):
        g = self.game(('k12.material',), ('k12.a',)); target = g.state.players[1].board[0]
        self.play(g, 'k12.material', target); e = g.state.entities[target]
        self.assertEqual((e.attack, e.health, self.price(g, 'k12.a')), (3, 5, 2)); self.portable(g)

    def test_late_error_rolls_back_physical_return_and_all_material(self):
        g = self.game(('k12.rollback',), ('k12.a',)); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'k12.rollback', g.state.players[1].board[0])
        self.assertEqual(g.snapshot(), saved)

    def test_waggle_pick_replacement_returns_one_friendly_with_discount(self):
        g = self.game(('k12.weapon',), ('k12.a', 'k12.b'), weapon='CORE_DAL_720')
        self.play(g, 'k12.weapon'); choices = [e for e in g.events if e.kind == 'random_choice']
        self.assertEqual(len(choices), 1); selected = choices[0].target_id
        self.assertIn(selected, g.state.players[1].hand)
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[selected]).amount, 2)
        self.assertEqual(len(g.state.players[1].board), 1); self.portable(g)

    def test_waggle_pick_two_real_weapon_attacks_trigger_only_on_last_durability(self):
        g = self.game(board=('k12.a',), weapon='CORE_DAL_720')
        original = g.state.players[1].board[0]
        hero, enemy = g.state.players[1].hero_id, g.state.players[2].hero_id
        g.apply(Attack(1, hero, enemy)); self.assertEqual(len(g.state.players[1].board), 1)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); g.apply(Attack(1, hero, enemy))
        self.assertEqual(g.state.players[1].weapon_id, None)
        self.assertFalse(g.state.players[1].board); self.assertIn(original, g.state.players[1].hand)
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[original]).amount, 2); self.portable(g)

    def test_random_empty_pool_consumes_no_rng_and_skips_dormant_and_locations(self):
        g = self.game(('k12.weapon',), ('k12.dormant', 'k12.location'), weapon='CORE_DAL_720')
        rng = g.snapshot()['rng_state']; self.play(g, 'k12.weapon')
        self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertFalse(any(e.kind == 'random_choice' for e in g.events)); self.portable(g)

    def test_waggle_pick_uses_controller_hand_for_borrowed_friendly_minion(self):
        g = self.game(('k12.steal', 'k12.weapon'), enemy=('k12.a',), weapon='CORE_DAL_720')
        target = g.state.players[2].board[0]; self.play(g, 'k12.steal', target); self.play(g, 'k12.weapon')
        self.assertIn(target, g.state.players[1].hand)
        self.assertEqual((g.state.entities[target].owner, g.state.entities[target].controller), (2, 1))
        self.assertEqual(self.price(g, 'k12.a'), 2); self.portable(g)

    def test_random_waiting_keeps_original_selection_and_does_not_redraw_after_shift(self):
        g = self.game(('k12.weapon',), ('k12.a', 'k12.b', 'k12.watch'), mode='random_wait', weapon='CORE_DAL_720')
        self.play(g, 'k12.weapon'); saved = g.snapshot()
        selected = next(e.target_id for e in g.events if e.kind == 'random_choice')
        other = self.portable(g); self.finish(g, 'shift'); self.finish(other, 'shift')
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertIn(selected, g.state.players[2].board)
        self.assertFalse(g.state.players[1].hand); self.assertEqual(g.snapshot()['rng_state'], saved['rng_state'])
        self.assertEqual(sum(e.kind == 'random_choice' for e in g.events), 1); self.portable(g)

    def test_weaponsmith_buffs_minions_and_weapons_but_not_other_cards(self):
        g = self.game(('END_021', 'k12.a', 'CORE_DAL_720', 'EDR_523', 'k12.location'))
        self.play(g, 'END_021'); a = g.state.entities[self.eid(g, 'k12.a')]
        w = g.state.entities[self.eid(g, 'CORE_DAL_720')]
        self.assertEqual((a.attack, a.health, w.attack, w.durability), (5, 5, 6, 2))
        for cid in ('EDR_523', 'k12.location'): self.assertFalse(g.state.entities[self.eid(g, cid)].enchantments)
        self.play(g, 'CORE_DAL_720'); w = g.state.entities[g.state.players[1].weapon_id]
        self.assertEqual((w.attack, w.durability), (6, 2)); self.portable(g)

    def test_stored_weapon_health_change_is_rejected_and_whole_action_rolls_back(self):
        g = self.game(('k12.weapon_health', 'CORE_DAL_720')); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'k12.weapon_health')
        self.assertEqual(g.snapshot(), saved)

    def test_hourglass_buffs_only_own_hand_minions_on_own_turn_end(self):
        g = self.game(('TIME_100', 'k12.a', 'CORE_DAL_720'), enemy_hand=('k12.b',))
        self.play(g, 'TIME_100'); g.apply(EndTurn(1))
        own = g.state.entities[self.eid(g, 'k12.a')]; enemy = g.state.entities[self.eid(g, 'k12.b', 2)]
        self.assertEqual((own.attack, own.health, enemy.attack, enemy.health), (4, 6, 2, 6))
        self.assertEqual(g.state.entities[self.eid(g, 'CORE_DAL_720')].attack, 4)
        g.apply(EndTurn(2)); self.assertEqual(g.state.entities[self.eid(g, 'k12.a')].attack, 4); self.portable(g)

    def test_public_return_types_reject_duplicate_random_weight_and_bad_continuations(self):
        g = self.game(board=('k12.a',)); ref = MinionReference.capture(g.state.entities[g.state.players[1].board[0]])
        with self.assertRaises(ValueError): RandomReturnCapturedMinion((ref, ref))
        with self.assertRaises(ValueError): ReturnCapturedMinion(ref, on_success=('bad',))
        with self.assertRaises(ValueError): ReturnCapturedMinion(ref, to_owner=1)
        with self.assertRaises(ValueError): RandomReturnCapturedMinion([ref])

    def test_player_projection_hides_original_return_and_stored_material(self):
        g = self.game(('EDR_523',), ('k12.a', 'k12.watch'), mode='wait')
        self.play(g, 'EDR_523', self.eid(g, 'k12.a', zone=Zone.BOARD))
        for viewer in (1, 2):
            public = json.dumps(g.for_player(viewer).observe())+json.dumps(g.player_events(viewer))
            for field in ('on_success', 'zone_epoch', 'submitted_cost', 'payment_state', 'minion_reference'):
                self.assertNotIn('"'+field+'"', public)


if __name__ == '__main__': unittest.main()
