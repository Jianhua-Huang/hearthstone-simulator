"""Real complete quantity-cost cards through the shared paid-hand interpreter."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.quantity_cost_cards import load_batch
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, CostSpec,
    EndTurn, Game, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input, capture_generated_quote_fact, capture_quote_fact, quote_cost
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Damage, Destroy,
    GrantHealthRule, GrantKeyword, InvokeBehavior, ModifyCost, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.intrinsic_costs import validate_intrinsic_history_prefix, validate_intrinsic_origin
from hs_sim.engine.model import DamageKind, HealthFlow, HealthOp, HealthRule
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import _intrinsic_stage_from_dict, canonical_hash
from hs_sim.targets import canonical_digest

ROOTS = ('TIME_047', 'JAIL_204', 'CATA_452', 'CATA_568', 'TIME_715', 'JAIL_514')


def registry(wait=False):
    r = build_registry()
    meta = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
    r.register_card(CardDefinition('k11.hero', 'Fixture hero', CardType.HERO, attack=2, health=100, metadata=meta))
    r.register_card(CardDefinition('k11.plain', 'Fixture minion', CardType.MINION, attack=2, health=20, metadata=meta))
    r.register_card(CardDefinition('k11.wind', 'Attacker', CardType.MINION, attack=1, health=20,
        keywords=(Keyword.CHARGE, Keyword.WINDFURY), metadata=meta))
    r.register_card(CardDefinition('k11.dormant', 'Dormant', CardType.MINION, health=20, dormant_turns=2, metadata=meta))
    r.register_card(CardDefinition('k11.converter', 'Conversion source', CardType.MINION, health=20,
        health_rules=(HealthRule(HealthFlow.DAMAGE, HealthOp.CONVERT),), metadata=meta))
    r.register_behavior('k11.noop', lambda c: ())
    r.register_card(CardDefinition('k11.location', 'Location', CardType.LOCATION, cost=2, durability=2,
        on_use='k11.noop', metadata=meta))
    def hero(c, p=None): return c.state.players[p or 3-c.player_id].hero_id
    scripts = {
        'one': lambda c: (Damage(hero(c), 1, c.source_id, DamageKind.SPELL),),
        'six': lambda c: (Damage(hero(c), 6, c.source_id, DamageKind.SPELL),),
        'two_packets': lambda c: (Damage(hero(c), 1, c.source_id, DamageKind.SPELL), Damage(hero(c), 1, c.source_id, DamageKind.SPELL)),
        'zero': lambda c: (Damage(hero(c), 0, c.source_id, DamageKind.SPELL),),
        'self': lambda c: (Damage(hero(c, c.player_id), 2, c.source_id, DamageKind.SPELL),),
        'immune': lambda c: (GrantKeyword(hero(c), Keyword.IMMUNE, c.source_id),),
        'convert': lambda c: (Damage(hero(c), 3, c.source_id, DamageKind.SPELL),),
        'clear': lambda c: tuple(Destroy(e, c.source_id) for p in (1, 2) for e in c.state.players[p].board
                                if c.state.entities[e].kind == CardType.MINION),
        'local': lambda c: (ModifyCost(next(e for e in c.state.players[c.player_id].hand
                                         if c.state.entities[e].card_id == 'TIME_047'), CostSpec(set_to=3), c.source_id),),
        'external': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-1, card_ids=('TIME_047',)), source_id=c.source_id),),
        'fail': lambda c: (AddToHand(c.player_id, 'missing.k11.choice'),),
    }
    for name, body in scripts.items():
        r.register_behavior('k11.'+name, body)
        r.register_card(CardDefinition('k11.'+name, name, CardType.SPELL, on_play='k11.'+name, metadata=meta))
    if wait:
        def pause(c):
            cid = c.state.entities[c.event.source_id].card_id
            if cid not in ROOTS: return ()
            return (RequestChoice(c.player_id, (
                ChoiceOption('continue', 'Later damage and card',
                    (Damage(hero(c), 1, c.source_id), AddToHand(c.player_id, cid))),
                ChoiceOption('bad', 'Rollback', (InvokeBehavior('k11.fail', c.source_id, c.player_id),)),
            ), c.source_id),)
        r.register_behavior('k11.pause', pause)
        r.register_card(CardDefinition('k11.watch', 'Observer', CardType.MINION, health=20,
            triggers=(TriggerSpec('card_committed', 'k11.pause'),), metadata=meta))
    return r


class QuantityCostCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.r = registry()
    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), armor=0, wait=False, deck=None):
        self.wait = wait
        return Game.from_scenario(Scenario((
            PlayerSetup('k11.hero', hand=hand, board=board, deck=deck if deck is not None else ('k11.plain',)*8,
                        mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('k11.hero', hand=enemy_hand, board=enemy, armor=armor,
                        deck=('k11.plain',)*8, mana=30, max_mana=30, mana_cap=30)), seed=181),
            registry(True) if wait else self.r)
    def eid(self, g, cid, p=1):
        return next(e for e in g.state.players[p].hand if g.state.entities[e].card_id == cid)
    def play(self, g, cid, p=1):
        eid = self.eid(g, cid, p); g.apply(PlayCard(p, eid)); return eid
    def quote(self, g, cid, p=1): return quote_cost(g.state, g.registry, g.state.entities[self.eid(g, cid, p)])
    def fact(self, g, cid, p=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(g.state.entities[self.eid(g, cid, p)]))
    def portable(self, g):
        s = g.snapshot(); other = Game.from_snapshot(s, registry(self.wait))
        self.assertEqual(other.snapshot(), s); self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), registry(self.wait)).snapshot(), s)
        return other
    def typed(self, g, fact):
        codec = FrameCodec(g.mechanics, g.registry)
        self.assertEqual(codec.decode(codec.encode(fact)), fact)
        self.assertEqual(_intrinsic_stage_from_dict(json.loads(json.dumps(asdict(fact.intrinsic)))), fact.intrinsic)
        validate_intrinsic_origin(fact.intrinsic, g.state, g.registry)
    def reject(self, saved):
        saved['events_hash'] = canonical_hash(saved['events'])
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry(self.wait))

    def test_six_complete_roots_and_actual_dragon_dependency_are_pinned(self):
        rows = load_batch()['cards']; self.assertEqual(len(rows), 7)
        self.assertEqual(sum(row['recipe']['root'] for row in rows), 6)
        for row in rows:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
            self.assertEqual(self.r.card(row['record']['id']).cost, row['record']['cost'])
        dragon = self.r.card('CATA_452t')
        self.assertEqual((dragon.attack, dragon.health, dragon.metadata.tribes), (6, 6, ('dragon',)))

    def test_coyote_counts_positive_packets_not_damage_units(self):
        g = self.game(('TIME_047', 'k11.six', 'k11.two_packets', 'k11.self'))
        self.play(g, 'k11.six'); self.assertEqual(self.quote(g, 'TIME_047').amount, 4)
        self.play(g, 'k11.two_packets'); self.play(g, 'k11.self')
        f = self.fact(g, 'TIME_047'); self.assertEqual(f.intrinsic.hero_damage_taken.quantity, 3)
        self.assertEqual(f.amount, 2); self.typed(g, f); self.play(g, 'TIME_047')
        self.assertEqual(g.state.play_history[-1].cost, 2); self.portable(g)

    def test_armor_only_damage_is_one_packet_and_zero_and_immunity_do_not_count(self):
        g = self.game(('TIME_047', 'k11.one', 'k11.zero', 'k11.immune', 'k11.six'), armor=10)
        self.play(g, 'k11.one'); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 100)
        self.assertEqual(self.quote(g, 'TIME_047').amount, 4)
        self.play(g, 'k11.zero'); self.play(g, 'k11.immune'); self.play(g, 'k11.six')
        self.assertEqual(self.quote(g, 'TIME_047').amount, 4); self.portable(g)

    def test_converted_damage_has_no_actual_received_damage_credit(self):
        g = self.game(('TIME_047', 'k11.convert'), board=('k11.converter',))
        self.play(g, 'k11.convert')
        self.assertEqual(self.quote(g, 'TIME_047').amount, 5)
        self.assertEqual(len(g.state.damage_history), 1)
        self.assertEqual(g.state.damage_history[0].health_result.damage_dealt, 0)
        self.assertEqual(g.state.damage_history[0].health_result.flow, HealthFlow.HEALING.value)
        self.portable(g)

    def test_enemy_hero_self_damage_counts_independently_of_source_player(self):
        g = self.game(('TIME_047',), enemy_hand=('k11.self',))
        g.apply(EndTurn(1)); self.play(g, 'k11.self', 2)
        self.assertEqual(self.quote(g, 'TIME_047').amount, 4)
        self.assertEqual(capture_generated_quote_fact(g.state, g.registry, 1, 'TIME_047').amount, 4)
        g.apply(EndTurn(2)); self.assertEqual(self.quote(g, 'TIME_047').amount, 5); self.portable(g)

    def test_second_seat_uses_actual_enemy_hero_and_current_global_turn(self):
        g = self.game(enemy_hand=('TIME_047', 'k11.two_packets'))
        g.apply(EndTurn(1)); self.play(g, 'k11.two_packets', 2)
        self.assertEqual(self.quote(g, 'TIME_047', 2).amount, 3)
        self.play(g, 'TIME_047', 2); self.assertEqual(g.state.play_history[-1].cost, 3); self.portable(g)

    def test_original_damage_prefix_stays_bound_and_later_damage_is_allowed(self):
        g = self.game(('TIME_047', 'k11.one', 'k11.two_packets'))
        self.play(g, 'k11.one'); old = self.fact(g, 'TIME_047').intrinsic
        self.play(g, 'k11.two_packets'); validate_intrinsic_history_prefix(old, g.state, g.registry)
        self.assertEqual(old.hero_damage_taken.quantity, 1)
        self.assertEqual(self.fact(g, 'TIME_047').intrinsic.hero_damage_taken.quantity, 3)
        with self.assertRaises(ValueError): validate_intrinsic_origin(old, g.state, g.registry)
        self.portable(g)

    def test_local_assignment_and_external_discount_follow_original_packet_stage(self):
        g = self.game(('TIME_047', 'k11.two_packets', 'k11.local', 'k11.external'))
        for cid in ('k11.two_packets', 'k11.local', 'k11.external'): self.play(g, cid)
        f = self.fact(g, 'TIME_047'); self.assertEqual((f.intrinsic.amount, f.local_amount, f.amount), (3, 3, 2))
        before = g.snapshot(); self.assertEqual(self.quote(g, 'TIME_047').amount, 2)
        self.assertEqual(g.snapshot(), before); self.play(g, 'TIME_047'); self.portable(g)

    def test_no_minions_ignores_locations_but_includes_both_sides_and_dormancy(self):
        for own, enemy, expected in (((), (), 2), (('k11.location',), ('k11.location',), 2),
                (('k11.plain',), (), 5), ((), ('k11.plain',), 5), ((), ('k11.dormant',), 5)):
            with self.subTest(own=own, enemy=enemy):
                g = self.game(('JAIL_204',), own, enemy)
                self.assertEqual(self.quote(g, 'JAIL_204').amount, expected)
                self.typed(g, self.fact(g, 'JAIL_204')); self.play(g, 'JAIL_204')
                self.assertEqual(g.state.play_history[-1].cost, expected); self.portable(g)

    def test_no_minions_requotes_after_real_removal_and_after_its_own_entry(self):
        g = self.game(('JAIL_204', 'JAIL_204', 'k11.clear'), enemy=('k11.plain',))
        self.assertEqual(self.quote(g, 'JAIL_204').amount, 5); self.play(g, 'k11.clear')
        self.assertEqual(self.quote(g, 'JAIL_204').amount, 2); self.play(g, 'JAIL_204')
        self.assertEqual(self.quote(g, 'JAIL_204').amount, 5); self.portable(g)

    def test_enemy_board_spell_draws_two_and_excludes_own_board_and_locations(self):
        g = self.game(('TIME_715',), ('k11.plain',), ('k11.plain', 'k11.dormant', 'k11.location'))
        f = self.fact(g, 'TIME_715'); self.assertEqual((f.amount, f.intrinsic.board_minions.quantity), (3, 2))
        self.typed(g, f); self.play(g, 'TIME_715')
        self.assertEqual(len(g.state.players[1].hand), 2); self.assertEqual(g.state.play_history[-1].cost, 3)
        self.assertEqual(len(g.state.draw_history), 2); self.portable(g)

    def test_own_all_hand_counts_physical_self_and_one_virtual_subject(self):
        g = self.game(('JAIL_514', 'JAIL_514', 'k11.plain'))
        f = self.fact(g, 'JAIL_514'); self.assertEqual((f.amount, f.intrinsic.hand_cards.quantity), (7, 3))
        self.typed(g, f)
        virtual = capture_generated_quote_fact(g.state, g.registry, 1, 'JAIL_514')
        self.assertEqual((virtual.amount, virtual.intrinsic.hand_cards.quantity), (6, 4))
        self.play(g, 'JAIL_514'); self.assertEqual(g.state.play_history[-1].cost, 7)
        self.assertEqual(len(g.state.players[1].hand), 5); self.assertEqual(len(g.state.draw_history), 3)
        self.portable(g)

    def test_only_secret_monitoring_costs_nine_then_draws_three(self):
        g = self.game(('JAIL_514',)); self.assertEqual(self.quote(g, 'JAIL_514').amount, 9)
        self.play(g, 'JAIL_514'); self.assertEqual(len(g.state.players[1].hand), 3); self.portable(g)

    def test_spell_damage_full_card_summons_real_six_six_dragon(self):
        g = self.game(('CATA_452', 'k11.six'))
        self.play(g, 'k11.six'); self.assertEqual(self.quote(g, 'CATA_452').amount, 4)
        self.play(g, 'CATA_452'); e = g.state.entities[g.state.players[1].board[0]]
        self.assertEqual((e.card_id, e.attack, e.health), ('CATA_452t', 6, 6))
        self.assertEqual(g.state.play_history[-1].cost, 4); self.portable(g)

    def test_character_attack_full_card_uses_two_original_attacks_and_draws_two(self):
        g = self.game(('CATA_568',), ('k11.wind',))
        e = g.state.players[1].board[0]; hero = g.state.players[2].hero_id
        g.apply(Attack(1, e, hero)); g.apply(Attack(1, e, hero))
        self.assertEqual(self.quote(g, 'CATA_568').amount, 7); self.play(g, 'CATA_568')
        self.assertEqual(len(g.state.players[1].hand), 2); self.assertEqual(g.state.play_history[-1].cost, 7)
        self.portable(g)

    def test_paid_waiting_restore_later_changes_and_failed_choice_preserve_one_payment(self):
        for cid in ('TIME_047', 'JAIL_204', 'TIME_715', 'JAIL_514'):
            with self.subTest(card=cid):
                g = self.game((cid,), ('k11.watch',), wait=True)
                cost = self.quote(g, cid).amount; self.play(g, cid)
                s = g.snapshot(); q = g.state.pending_choice
                with self.assertRaises(ResolutionError): g.apply(SelectChoice(1, q.id, ('bad',)))
                self.assertEqual(g.snapshot(), s); other = self.portable(g)
                action = SelectChoice(1, q.id, ('continue',)); g.apply(action); other.apply(action)
                self.assertEqual(g.snapshot(), other.snapshot())
                self.assertEqual(g.state.players[1].mana, 30-cost)
                self.assertEqual(g.state.play_history[0].cost, cost); self.portable(g)

    def test_rehashed_payment_damage_quantity_and_board_match_forgery_are_rejected(self):
        g = self.game(('TIME_047', 'k11.one'), ('k11.watch',), wait=True)
        self.play(g, 'k11.one'); self.play(g, 'TIME_047'); s = g.snapshot()
        s['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['hero_damage_taken']['quantity'] = 0
        self.reject(s)
        g = self.game(('JAIL_204',)); self.play(g, 'JAIL_204'); s = g.snapshot()
        s['state']['play_history'][0]['submitted_cost']['quote']['intrinsic']['condition_facts'][0]['matched'] = False
        self.reject(s)

    def test_player_views_do_not_expose_original_hands_boards_or_packet_proof(self):
        g = self.game(('JAIL_514', 'TIME_047', 'k11.one')); self.play(g, 'k11.one'); self.play(g, 'JAIL_514')
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(g.player_events(player))
            for field in ('condition_facts', 'hero_damage_taken', 'payment_state', 'submitted_cost', 'hands'):
                self.assertNotIn('"'+field+'"', public)


if __name__ == '__main__': unittest.main()
