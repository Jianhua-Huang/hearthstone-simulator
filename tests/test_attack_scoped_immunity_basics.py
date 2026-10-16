"""One attack scope, two native carriers, and the original combat lifecycle."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, CardClass, CardDefinition, CardType, EndTurn,
    Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity, Registry,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone,
    health_result)
from hs_sim.engine.combat import is_immune
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion,
    Damage, Destroy, EquipWeapon, ForceAttack, InvokeBehavior, RequestChoice,
    ReturnToHand, Silence, Transform)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.targeting import accepts_target
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT = Path(__file__).resolve().parents[1]
PIN = '341aa3cb0ee568cbcda1d9c1d18b8d978903d750c43a746175820e987a03387e'
BOW = 'DS1_188'
BIRD = 'VAC_410t'
FLAG = Keyword.IMMUNE_WHILE_ATTACKING


def evidence():
    value = json.loads((ROOT/'data/support/attack-scoped-immunity-basics.json').read_bytes())
    if canonical_digest(value) != PIN:
        raise ValueError('Attack immunity requires the complete native evidence pin')
    return value


def registry():
    r = Registry('attack-scoped-immunity-basics-v1')
    raw = {c['id']:c for c in evidence()['records']}
    r.register_card(CardDefinition('ai.hero', 'Hero', CardType.HERO, health=30,
        metadata=metadata(CardClass.HUNTER, collectible=False)))
    for cid, attack, health in (('ai.body', 6, 20), ('ai.plain', 1, 6), ('ai.hidden', 1, 1)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=attack,
            health=health, metadata=metadata()))
    r.register_card(CardDefinition('ai.weapon', 'Plain weapon', CardType.WEAPON,
        attack=2, durability=2, metadata=metadata()))
    r.register_card(CardDefinition(BOW, raw[BOW]['name'], CardType.WEAPON,
        cost=raw[BOW]['cost'], attack=raw[BOW]['attack'], durability=raw[BOW]['health'],
        keywords=(FLAG,), metadata=metadata(CardClass.HUNTER, rarity=Rarity.EPIC)))
    r.register_card(CardDefinition(BIRD, raw[BIRD]['name'], CardType.MINION,
        cost=raw[BIRD]['cost'], attack=raw[BIRD]['attack'], health=raw[BIRD]['health'],
        keywords=(FLAG,), metadata=metadata(CardClass.HUNTER, collectible=False,
            rarity=None, tribes=('beast',))))

    def fail(c): raise ResolutionError('Deliberate attack choice failure')
    r.register_behavior('ai.cb.fail', fail)

    def waiting(c):
        actor = c.state.entities[c.event.source_id]
        weapon = c.state.players[actor.controller].weapon_id
        remove = Destroy(weapon) if weapon is not None else Silence(actor.id)
        return RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue attack', (Damage(actor.id, 1, c.source_id),)),
            ChoiceOption('bad', 'Remove protection and fail', (remove,
                Damage(actor.id, 1, c.source_id), InvokeBehavior('ai.cb.fail', c.source_id, c.player_id))),
        ), c.source_id)

    def reenter(c):
        actor = c.state.entities[c.event.source_id]
        return (ReturnToHand(actor.id), SummonFromZone(actor.controller, zone=Zone.HAND,
            selection='first', source_id=c.source_id), Damage(actor.id, 1, c.source_id),
            RequestChoice(c.player_id, (ChoiceOption('ok', 'Finish old declaration', ()),), c.source_id))

    watchers = {
        'pre': ('attack_declared', lambda c: (Damage(c.event.source_id, 2, c.source_id),)),
        'wait': ('attack_declared', lambda c: (Damage(c.event.source_id, 2, c.source_id), waiting(c))),
        'after': ('attack_finished', lambda c: (Damage(c.event.source_id, 2, c.source_id),)),
        'remove': ('attack_declared', lambda c: (
            Destroy(c.state.players[c.state.entities[c.event.source_id].controller].weapon_id),
            Damage(c.event.source_id, 2, c.source_id))),
        'replace': ('attack_declared', lambda c: (
            EquipWeapon(c.state.entities[c.event.source_id].controller, 'ai.weapon'),
            Damage(c.event.source_id, 2, c.source_id))),
        'silence': ('attack_declared', lambda c: (Silence(c.event.source_id), Damage(c.event.source_id, 1, c.source_id))),
        'bounce': ('attack_declared', lambda c: (ReturnToHand(c.event.source_id),)),
        'reenter': ('attack_declared', reenter),
    }
    for key, (event, body) in watchers.items():
        bid = 'ai.cb.watch.'+key
        r.register_behavior(bid, body)
        r.register_card(CardDefinition('ai.watch.'+key, key, CardType.MINION,
            health=20, triggers=(TriggerSpec(event, bid),), metadata=metadata()))
    operations = {
        'ping': lambda c: (Damage(c.target_id, 2, c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'transform': lambda c: (Transform(c.target_id, 'ai.plain'),),
        'copy': lambda c: (CopyMinion(c.target_id, c.player_id),),
        'transfer': lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        'force': lambda c: (ForceAttack(next(i for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id == BIRD), c.target_id),),
    }
    for key, body in operations.items():
        cid = 'ai.op.'+key
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            requires_target=True, metadata=metadata()))
    return r


class AttackScopedImmunityBasicsTests(unittest.TestCase):
    def game(self, *, hand=(), board=(), enemy=('ai.body',), enemy_hand=(),
             weapon=BOW, active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('ai.hero', hand=hand, board=board, deck=('ai.hidden',),
                weapon_card_id=weapon, mana=10, max_mana=10),
            PlayerSetup('ai.hero', hand=enemy_hand, board=enemy, deck=('ai.hidden',),
                mana=10, max_mana=10),
        ), seed=718, active_player=active), registry())

    def hero(self, g, p=1): return g.state.entities[g.state.players[p].hero_id]
    def entity(self, g, cid='ai.body', p=2):
        return next(g.state.entities[i] for i in g.state.players[p].board if g.state.entities[i].card_id == cid)
    def attack(self, g, actor=None, target=None):
        p = g.state.active_player
        g.apply(Attack(p, actor if actor is not None else self.hero(g, p).id,
            target if target is not None else self.entity(g).id))
    def play(self, g, cid, target=None):
        p = g.state.active_player
        source = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(p, source, target))
        return source
    def choose(self, g, key='ok'):
        choice = g.state.pending_choice
        g.apply(SelectChoice(choice.player_id, choice.id, (key,)))
    def results(self, g): return [health_result(e) for e in g.events if e.kind == 'health_resolved']
    def check(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, registry()).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)

    def test_complete_raw_pin_native_carriers_and_evidence_only_sources(self):
        packet = evidence()
        self.assertEqual(packet['executable_representatives'], [BOW, BIRD])
        all_raw = {c['id']:c for c in json.loads((ROOT/'data/extracted/cards.json').read_bytes())}
        for row in packet['records']: self.assertEqual(row, all_raw[row['id']])
        r = registry()
        self.assertEqual((r.card(BOW).attack, r.card(BOW).durability, r.card(BOW).cost), (5, 2, 7))
        self.assertEqual((r.card(BIRD).attack, r.card(BIRD).health, r.card(BIRD).metadata.tribes), (3, 3, ('beast',)))
        self.assertEqual(r.card(BIRD).keywords, (FLAG,))
        self.assertFalse(packet['CN_calibrated'])

    def test_native_weapon_equips_through_paid_hand_and_normal_hero_attack(self):
        g = self.game(hand=(BOW,), weapon=None)
        source = self.play(g, BOW)
        self.assertEqual((g.state.players[1].weapon_id, g.state.players[1].mana), (source, 3))
        self.attack(g)
        self.assertEqual((self.hero(g).health, self.entity(g).health, g.state.entities[source].durability), (30, 15, 1))
        self.assertEqual(self.hero(g).attacks_this_turn, 1)
        self.assertFalse(is_immune(g.state, self.hero(g)))
        self.check(g)

    def test_weapon_does_not_protect_ordinary_damage_before_or_after_attack(self):
        g = self.game(hand=('ai.op.ping', 'ai.op.ping'))
        self.play(g, 'ai.op.ping', self.hero(g).id)
        self.attack(g)
        self.play(g, 'ai.op.ping', self.hero(g).id)
        self.assertEqual(self.hero(g).health, 26)
        self.assertEqual([r.prevention for r in self.results(g)], [None, None, 'immune', None])
        self.check(g)

    def test_equipped_weapon_does_not_protect_passive_opponent_turn_hero(self):
        g = self.game()
        weapon = g.state.players[1].weapon_id
        g.apply(EndTurn(1))
        self.attack(g, actor=self.entity(g).id, target=self.hero(g, 1).id)
        self.assertEqual((self.hero(g, 1).health, g.state.entities[weapon].durability), (24, 2))
        self.assertNotIn(FLAG, self.hero(g, 1).keywords)
        self.check(g)

    def test_minion_only_attacking_role_is_immune_not_native_defender(self):
        g = self.game(board=(BIRD,), enemy=(BIRD,), weapon=None)
        actor = self.entity(g, BIRD, 1).id
        target = self.entity(g, BIRD, 2).id
        self.attack(g, actor, target)
        self.assertEqual((g.state.entities[actor].health, g.state.entities[target].zone), (3, Zone.GRAVEYARD))
        self.assertEqual([(r.damage_dealt, r.prevention) for r in self.results(g)], [(3, None), (0, 'immune')])
        self.assertFalse(is_immune(g.state, g.state.entities[actor]))
        self.check(g)

    def test_native_minion_can_be_attacked_and_killed_outside_its_own_attack(self):
        g = self.game(board=(BIRD,), weapon=None, active=2)
        target = self.entity(g, BIRD, 1).id
        self.assertIn(Attack(2, self.entity(g).id, target), g.legal_actions())
        self.attack(g, self.entity(g).id, target)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.check(g)

    def test_existing_forced_minion_attack_has_same_scope_without_spending_voluntary_count(self):
        g = self.game(hand=('ai.op.force',), board=(BIRD,), weapon=None)
        actor = self.entity(g, BIRD, 1).id
        self.play(g, 'ai.op.force', self.entity(g).id)
        self.assertEqual((g.state.entities[actor].health, g.state.entities[actor].attacks_this_turn), (3, 0))
        self.assertEqual(self.entity(g).health, 17)
        self.check(g)

    def test_declared_attack_reaction_damage_is_prevented_for_both_native_carriers(self):
        for minion in (False, True):
            with self.subTest(minion=minion):
                g = self.game(board=(BIRD,) if minion else (),
                    enemy=('ai.body', 'ai.watch.pre'), weapon=None if minion else BOW)
                actor = self.entity(g, BIRD, 1).id if minion else self.hero(g).id
                self.attack(g, actor)
                self.assertEqual(g.state.entities[actor].health, 3 if minion else 30)
                self.assertEqual([r.prevention for r in self.results(g)], ['immune', None, 'immune'])
                self.check(g)

    def test_attack_finished_reaction_is_outside_the_protected_scope(self):
        g = self.game(board=('ai.watch.after',))
        self.attack(g)
        self.assertEqual(self.hero(g).health, 28)
        self.assertEqual([r.prevention for r in self.results(g)], [None, 'immune', None])
        self.assertEqual(g.state.action_windows, [])
        self.check(g)

    def test_last_durability_protects_exchange_then_weapon_leaves_once(self):
        g = self.game()
        weapon = g.state.players[1].weapon_id
        self.attack(g)
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.attack(g)
        self.assertEqual(self.hero(g).health, 30)
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(g.state.entities[weapon].zone, Zone.GRAVEYARD)
        self.assertFalse(is_immune(g.state, self.hero(g)))
        self.check(g)

    def test_current_weapon_destroyed_in_declaration_removes_protection_before_damage(self):
        g = self.game(enemy=('ai.body', 'ai.watch.remove'))
        self.attack(g)
        self.assertEqual((self.hero(g).health, self.entity(g).health), (22, 20))
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertFalse(any(r.prevention == 'immune' for r in self.results(g)))
        self.check(g)

    def test_current_replacement_weapon_is_used_without_old_native_protection(self):
        g = self.game(enemy=('ai.body', 'ai.watch.replace'))
        self.attack(g)
        weapon = g.state.entities[g.state.players[1].weapon_id]
        self.assertEqual((self.hero(g).health, self.entity(g).health, weapon.card_id, weapon.durability), (22, 18, 'ai.weapon', 1))
        self.check(g)

    def test_silence_during_declaration_removes_minion_trait_before_quote(self):
        g = self.game(board=(BIRD,), enemy=('ai.body', 'ai.watch.silence'), weapon=None)
        actor = self.entity(g, BIRD, 1).id
        self.attack(g, actor)
        self.assertEqual(g.state.entities[actor].zone, Zone.GRAVEYARD)
        self.assertNotIn(FLAG, g.state.entities[actor].keywords)
        self.assertFalse(any(r.prevention == 'immune' for r in self.results(g)))
        self.check(g)

    def test_copy_preserves_native_trait_as_independent_physical_carrier(self):
        g = self.game(hand=('ai.op.copy',), board=(BIRD,), weapon=None)
        original = self.entity(g, BIRD, 1).id
        self.play(g, 'ai.op.copy', original)
        copy = next(i for i in g.state.players[1].board if i != original)
        self.assertIn(FLAG, g.state.entities[copy].keywords)
        self.assertNotEqual(g.state.entities[copy].board_presence_id, g.state.entities[original].board_presence_id)
        self.assertFalse(is_immune(g.state, g.state.entities[copy]))
        self.check(g)

    def test_control_transfer_and_transform_use_existing_trait_lifecycle(self):
        g = self.game(hand=('ai.op.transfer',), board=(BIRD,), weapon=None)
        source = self.entity(g, BIRD, 1).id
        self.play(g, 'ai.op.transfer', source)
        self.assertEqual(g.state.entities[source].controller, 2)
        self.assertIn(FLAG, g.state.entities[source].keywords)
        self.assertFalse(is_immune(g.state, g.state.entities[source]))
        self.check(g)
        g = self.game(hand=('ai.op.transform',), board=(BIRD,), weapon=None)
        source = self.entity(g, BIRD, 1).id
        self.play(g, 'ai.op.transform', source)
        self.assertNotIn(FLAG, g.state.entities[source].keywords)
        self.check(g)

    def test_leaving_board_cancels_original_attack_and_never_grants_hand_immunity(self):
        g = self.game(board=(BIRD,), enemy=('ai.body', 'ai.watch.bounce'), weapon=None)
        actor = self.entity(g, BIRD, 1).id
        self.attack(g, actor)
        self.assertEqual(g.state.entities[actor].zone, Zone.HAND)
        self.assertFalse(is_immune(g.state, g.state.entities[actor]))
        self.assertEqual(self.results(g), [])
        self.assertEqual(self.entity(g).health, 20)
        self.check(g)

    def test_same_entity_reentering_board_cannot_borrow_old_attack_scope_or_exchange(self):
        g = self.game(board=(BIRD,), enemy=('ai.body', 'ai.watch.reenter'), weapon=None)
        actor = self.entity(g, BIRD, 1).id
        old_presence = g.state.entities[actor].board_presence_id
        self.attack(g, actor)
        self.assertEqual(g.state.entities[actor].zone, Zone.BOARD)
        self.assertNotEqual(g.state.entities[actor].board_presence_id, old_presence)
        self.assertEqual(g.state.action_windows[-1].attack_source_presence.presence_id, old_presence)
        self.assertFalse(is_immune(g.state, g.state.entities[actor]))
        self.assertEqual(g.state.entities[actor].health, 2)
        self.check(g)
        restored = Game.from_snapshot(g.snapshot(), registry())
        for game in (g, restored): self.choose(game)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(self.entity(g).health, 20)
        self.assertTrue(any(e.kind == 'attack_cancelled' and dict(e.data)['reason'] ==
            'attacker_left_original_board_residence' for e in g.events))
        self.check(g)

    def test_waiting_scope_save_clone_and_independent_replay_for_both_carriers(self):
        for minion in (False, True):
            with self.subTest(minion=minion):
                g = self.game(board=(BIRD,) if minion else (), enemy=('ai.body', 'ai.watch.wait'),
                    weapon=None if minion else BOW)
                actor = self.entity(g, BIRD, 1).id if minion else self.hero(g).id
                self.attack(g, actor)
                self.assertTrue(is_immune(g.state, g.state.entities[actor]))
                self.check(g)
                restored, cloned = Game.from_snapshot(g.snapshot(), registry()), g.clone()
                for game in (g, restored, cloned): self.choose(game)
                self.assertEqual(g.snapshot(), restored.snapshot())
                self.assertEqual(g.snapshot(), cloned.snapshot())
                self.assertEqual(g.state.entities[actor].health, 3 if minion else 30)
                self.assertFalse(is_immune(g.state, g.state.entities[actor]))
                self.check(g)

    def test_failed_choice_restores_original_scope_trait_payment_and_damage_prefix(self):
        for minion in (False, True):
            with self.subTest(minion=minion):
                g = self.game(board=(BIRD,) if minion else (), enemy=('ai.body', 'ai.watch.wait'),
                    weapon=None if minion else BOW)
                actor = self.entity(g, BIRD, 1).id if minion else self.hero(g).id
                self.attack(g, actor)
                saved = g.snapshot()
                with self.assertRaises(ResolutionError): self.choose(g, 'bad')
                self.assertEqual(g.snapshot(), saved)
                self.assertTrue(is_immune(g.state, g.state.entities[actor]))
                self.choose(g)
                self.check(g)

    def test_active_attacker_is_unselectable_to_enemy_but_automatic_effect_can_address_it(self):
        g = self.game(enemy=('ai.body', 'ai.watch.wait'), enemy_hand=('ai.op.ping',))
        actor = self.hero(g).id
        self.attack(g)
        source = g.state.entities[g.state.players[2].hand[0]]
        self.assertFalse(accepts_target(g.state, g.registry, source, g.registry.card(source.card_id), actor))
        self.assertTrue(accepts_target(g.state, g.registry, source, g.registry.card(source.card_id), actor, automatic=True))
        self.choose(g)
        self.assertTrue(accepts_target(g.state, g.registry, source, g.registry.card(source.card_id), actor))

    def test_immunity_does_not_allow_a_second_attack_or_change_original_action_payment(self):
        g = self.game()
        self.attack(g)
        before = g.snapshot()
        with self.assertRaises(IllegalAction): self.attack(g)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(self.hero(g).attacks_this_turn, 1)

    def test_internal_window_and_original_presence_are_not_exposed_to_player(self):
        g = self.game(board=(BIRD,), enemy=('ai.body', 'ai.watch.wait'), enemy_hand=('ai.hidden',), weapon=None)
        self.attack(g, self.entity(g, BIRD, 1).id)
        self.assertNotIn('ai.hidden', json.dumps(g.for_player(1).observe(), ensure_ascii=False))
        for player in (1,2):
            text = json.dumps(g.for_player(player).observe(), ensure_ascii=False)
            for key in ('attack_source_presence', 'BoardPresenceReference', 'resolution_frame', 'rng_state'):
                self.assertNotIn(key, text)

    def test_rehashed_minion_window_rejects_missing_foreign_future_or_unknown_presence(self):
        g = self.game(board=(BIRD,), enemy=('ai.body', 'ai.watch.wait'), weapon=None)
        self.attack(g, self.entity(g, BIRD, 1).id)
        for change in ('null', 'foreign', 'future', 'boolean', 'unknown'):
            with self.subTest(change=change):
                saved = g.snapshot()
                row = saved['state']['action_windows'][-1]
                if change == 'null': row['attack_source_presence'] = None
                elif change == 'foreign': row['attack_source_presence']['entity_id'] = self.entity(g).id
                elif change == 'future': row['attack_source_presence']['presence_id'] = saved['state']['next_order']
                elif change == 'boolean': row['attack_source_presence']['presence_id'] = True
                else: row['attack_source_presence']['unknown'] = 1
                saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
                    if k not in ('schema_version','events','events_hash','state_hash')})
                with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry())

    def test_previous_schema_requires_its_original_engine(self):
        saved = self.game().snapshot()
        saved['schema_version'] = 222
        with self.assertRaisesRegex(SnapshotError, f'schemas 1 through {SNAPSHOT_SCHEMA_VERSION-1}'):
            Game.from_snapshot(saved, registry())


if __name__ == '__main__': unittest.main()
