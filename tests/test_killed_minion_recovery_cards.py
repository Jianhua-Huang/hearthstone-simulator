"""Native physical kill ownership, all-minion attacks and attributed revival."""
from copy import deepcopy
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.killed_minion_recovery_cards import FROSTMOURNE, URSOC, load_batch
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, EquippedWeaponReference,
    Game, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.dark_gifts import GrantDarkGift
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, Destroy, GainArmor, GrantKeyword, InvokeBehavior, ModifyWeapon, RequestChoice,
    ReturnToHand, Silence, Summon, Transform, TransferWeapon, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.source_kills import KillSourceReference, killed_minion_deaths
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P = 'k200.'
A, B, BIG, POISON, SHIELD, SPAWN, WATCH = (P + s for s in (
    'a', 'b', 'big', 'poison', 'shield', 'spawn', 'watch'))
SENTENCE, THORNS = 'JAIL_940', 'EDR_491'


def registry(mode=None):
    r = build_registry()
    for cid, attack, health, keywords in ((A, 1, 2, ()), (B, 1, 3, ()),
            (BIG, 0, 7, ()), (POISON, 1, 9, (Keyword.POISONOUS,)),
            (SHIELD, 0, 2, (Keyword.DIVINE_SHIELD,))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=attack,
                                       health=health, keywords=keywords))
    r.register_behavior(P + 'spawn', lambda c: (Summon(c.player_id, A),))
    r.register_card(CardDefinition(SPAWN, 'New target source', CardType.MINION,
        attack=0, health=1, deathrattle=P + 'spawn'))
    r.register_behavior(P + 'fail', lambda c: (AddToHand(c.player_id, P + 'unknown', c.source_id),))
    def notify(c):
        if mode == 'attack_wait':
            source = c.state.entities.get(c.event.source_id)
            if source is None or source.card_id != URSOC:
                return ()
        elif mode == 'revive_wait':
            if not any(row.entity_id == c.event.target_id for row in c.state.resurrection_history):
                return ()
        else:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', (GainArmor(c.player_id, 1),)),
            ChoiceOption('bad', 'Fail', (InvokeBehavior(P + 'fail', c.source_id, c.player_id),))),
            source_id=c.source_id),)
    r.register_behavior(P + 'notify', notify)
    triggers = () if mode is None else (TriggerSpec(
        'attack_declared' if mode == 'attack_wait' else 'minion_summoned', P + 'notify'),)
    r.register_card(CardDefinition(WATCH, 'Waiting observer', CardType.MINION,
        attack=0, health=50, triggers=triggers))
    def weapon(c):
        return c.state.entities[c.state.players[c.player_id].weapon_id]
    def take(c):
        enemy = c.state.entities[c.state.players[3 - c.player_id].weapon_id]
        return (TransferWeapon(EquippedWeaponReference.capture(enemy), c.player_id, c.source_id),)
    def gift(c):
        target = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
                      if c.state.entities[i].card_id == URSOC)
        return (GrantDarkGift(CardReference.capture(target), 'EDR_100t5', c.source_id),)
    scripts = dict(
        kill=lambda c: (Destroy(c.target_id, c.source_id),),
        spell=lambda c: (Damage(c.target_id, 20, c.source_id),),
        buff=lambda c: (Buff(c.target_id, attack=3, health=2, source_id=c.source_id),),
        bounce=lambda c: (ReturnToHand(c.target_id),),
        silence=lambda c: (Silence(c.target_id),),
        copy=lambda c: (CopyMinion(c.target_id, c.player_id),),
        change=lambda c: (Transform(c.target_id, A),),
        restore=lambda c: (Transform(c.target_id, URSOC),),
        control=lambda c: (ChangeControl(c.target_id, c.player_id),),
        trigger=lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        break_weapon=lambda c: (Destroy(weapon(c).id, c.source_id),),
        one_charge=lambda c: (ModifyWeapon(weapon(c).id, durability=-2, source_id=c.source_id),),
        poison_weapon=lambda c: (GrantKeyword(weapon(c).id, Keyword.POISONOUS, c.source_id),),
        summon=lambda c: (Summon(c.player_id, URSOC),),
        take=take, gift=gift)
    targeted = {'kill', 'spell', 'buff', 'bounce', 'silence', 'copy', 'change', 'restore', 'control', 'trigger'}
    for name, body in scripts.items():
        r.register_behavior(P + name, body)
        r.register_card(CardDefinition(P + name, name, CardType.SPELL,
            on_play=P + name, requires_target=name in targeted))
    r.validate()
    return r


class KilledMinionRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registries = {mode: registry(mode) for mode in (None, 'attack_wait', 'revive_wait')}

    def game(self, hand=(), board=(), enemy=(A,), weapon=FROSTMOURNE,
             actor=1, enemy_hand=(), mode=None, seed=200):
        own = PlayerSetup('HERO_08', hand=hand, board=board, weapon_card_id=weapon,
            deck=(A,) * 12, mana=80, max_mana=80, mana_cap=80)
        other = PlayerSetup('HERO_08', hand=enemy_hand, board=enemy,
            deck=(A,) * 12, mana=80, max_mana=80, mana_cap=80)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own),
            active_player=actor, seed=seed), self.registries[mode])

    def entity(self, g, cid, zone='board', player=None):
        player = g.state.active_player if player is None else player
        return next(i for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None):
        eid = self.entity(g, cid, 'hand')
        g.apply(PlayCard(g.state.active_player, eid, target))
        return eid

    def attack(self, g, target, attacker=None):
        actor = g.state.active_player
        g.apply(Attack(actor, attacker or g.state.players[actor].hero_id, target))

    def count(self, g, cid, player=None):
        player = g.state.active_player if player is None else player
        return sum(g.state.entities[i].card_id == cid for i in g.state.players[player].board)

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g, mode=None):
        s = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(deepcopy(s), registry(mode)).snapshot(), s)
        self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), registry(mode)).snapshot(), s)

    def test_two_complete_native_sources_and_four_primary_faces(self):
        data = load_batch()
        self.assertEqual([row['record']['id'] for row in data['cards']], [FROSTMOURNE, URSOC])
        self.assertEqual(len(data['official_observations']), 4)
        for row in data['cards']:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        self.assertEqual((self.registries[None].card(FROSTMOURNE).cost,
            self.registries[None].card(FROSTMOURNE).attack,
            self.registries[None].card(FROSTMOURNE).durability), (6, 4, 3))

    def test_real_weapon_play_pays_six_and_installs_original_entity(self):
        g = self.game((FROSTMOURNE,), enemy=(), weapon=None)
        before = g.state.players[1].mana
        eid = self.play(g, FROSTMOURNE)
        self.assertEqual(g.state.players[1].weapon_id, eid)
        self.assertEqual(g.state.players[1].mana, before - 6)
        self.assertEqual(g.state.entities[eid].durability, 3)

    def test_empty_weapon_death_has_no_revival_or_rng_draw(self):
        g = self.game((P + 'break_weapon',), enemy=())
        before = g.snapshot()['rng_state']
        self.play(g, P + 'break_weapon')
        self.assertEqual(g.state.resurrection_history, [])
        self.assertEqual(g.snapshot()['rng_state'], before)

    def test_weapon_revives_its_actual_victim_as_new_printed_body(self):
        g = self.game((P + 'buff', P + 'break_weapon'))
        victim = self.entity(g, A, player=2)
        self.play(g, P + 'buff', victim)
        self.attack(g, victim)
        self.play(g, P + 'break_weapon')
        new = self.entity(g, A)
        self.assertNotEqual(new, victim)
        self.assertEqual((g.state.entities[new].attack, g.state.entities[new].health), (1, 2))
        self.assertEqual(g.state.resurrection_history[-1].death_id, 1)

    def test_weapon_does_not_take_credit_for_spell_kills_while_equipped(self):
        g = self.game((P + 'spell', P + 'break_weapon'))
        self.play(g, P + 'spell', self.entity(g, A, player=2))
        self.play(g, P + 'break_weapon')
        self.assertEqual(self.count(g, A), 0)

    def test_nonlethal_weapon_hit_is_not_a_kill(self):
        g = self.game((P + 'break_weapon',), enemy=(BIG,))
        self.attack(g, self.entity(g, BIG, player=2))
        self.play(g, P + 'break_weapon')
        self.assertEqual(self.count(g, BIG), 0)
        self.assertEqual(self.count(g, BIG, 2), 1)

    def test_divine_shield_prevention_does_not_add_a_victim(self):
        g = self.game((P + 'break_weapon',), enemy=(SHIELD,))
        self.attack(g, self.entity(g, SHIELD, player=2))
        self.play(g, P + 'break_weapon')
        self.assertEqual(self.count(g, SHIELD), 0)

    def test_poison_weapon_uses_original_combat_attribution(self):
        g = self.game((P + 'poison_weapon', P + 'break_weapon'), enemy=(BIG,))
        self.play(g, P + 'poison_weapon')
        self.attack(g, self.entity(g, BIG, player=2))
        self.assertEqual(g.state.death_history[0].cause.kind, 'poison')
        self.play(g, P + 'break_weapon')
        self.assertEqual(self.count(g, BIG), 1)

    def test_last_charge_includes_the_victim_of_that_exchange(self):
        g = self.game((P + 'one_charge',))
        self.play(g, P + 'one_charge')
        self.attack(g, self.entity(g, A, player=2))
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(self.count(g, A), 1)

    def test_three_real_hero_attacks_revive_three_occurrences(self):
        g = self.game(enemy=(A, A, B))
        for index in range(3):
            self.attack(g, g.state.players[2].board[0])
            if index < 2:
                g.apply(EndTurn(1))
                g.apply(EndTurn(2))
        self.assertEqual((self.count(g, A), self.count(g, B)), (2, 1))
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(len(g.state.resurrection_history), 3)

    def test_replacement_replays_old_weapon_only_and_new_weapon_starts_empty(self):
        g = self.game((FROSTMOURNE, P + 'break_weapon'))
        self.attack(g, self.entity(g, A, player=2))
        old = g.state.players[1].weapon_id
        new = self.play(g, FROSTMOURNE)
        self.assertNotEqual(old, new)
        self.assertEqual(self.count(g, A), 1)
        self.play(g, P + 'break_weapon')
        self.assertEqual(self.count(g, A), 1)

    def test_weapon_transfer_preserves_previous_owner_victims(self):
        g = self.game(enemy_hand=(P + 'take', P + 'break_weapon'))
        old = g.state.players[1].weapon_id
        self.attack(g, self.entity(g, A, player=2))
        g.apply(EndTurn(1))
        self.play(g, P + 'take')
        self.assertEqual(g.state.players[2].weapon_id, old)
        self.play(g, P + 'break_weapon')
        self.assertEqual(self.count(g, A, 2), 1)
        self.assertEqual(self.count(g, A, 1), 0)
        self.portable(g)

    def test_second_seat_weapon_credits_and_revives_for_second_seat(self):
        g = self.game((P + 'break_weapon',), actor=2)
        self.attack(g, self.entity(g, A, player=1))
        self.play(g, P + 'break_weapon')
        self.assertEqual(self.count(g, A, 2), 1)
        self.assertEqual(self.count(g, A, 1), 0)

    def test_full_board_uses_existing_resurrection_capacity(self):
        g = self.game((P + 'break_weapon',), (B,) * 7)
        self.attack(g, self.entity(g, A, player=2))
        self.play(g, P + 'break_weapon')
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual(self.count(g, A), 0)

    def test_ursoc_attacks_friendly_and_enemy_minions_once(self):
        g = self.game((URSOC,), (A,), (B,), weapon=None)
        source = self.play(g, URSOC)
        self.assertEqual(self.count(g, A), 0)
        self.assertEqual(self.count(g, B, 2), 0)
        rows = [row for row in g.state.character_attack_history if row.declaration.source_id == source]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.declaration.forced for row in rows))
        self.assertEqual(g.state.entities[source].attacks_this_turn, 0)

    def test_ursoc_death_revives_both_sides_actual_victims(self):
        g = self.game((URSOC, P + 'kill'), (A,), (B,), weapon=None)
        source = self.play(g, URSOC)
        self.play(g, P + 'kill', source)
        self.assertEqual((self.count(g, A), self.count(g, B)), (1, 1))
        self.assertEqual(g.state.players[2].board, [])
        self.assertEqual(len(g.state.resurrection_history), 2)

    def test_ursoc_no_other_minion_has_no_attack_or_rng_draw(self):
        g = self.game((URSOC,), enemy=(), weapon=None)
        before = g.snapshot()['rng_state']
        self.play(g, URSOC)
        self.assertEqual(g.snapshot()['rng_state'], before)
        self.assertEqual(g.state.character_attack_history, [])

    def test_ursoc_does_not_repeat_a_nonlethal_target(self):
        g = self.game((URSOC, P + 'kill'), enemy=(BIG,), weapon=None)
        source = self.play(g, URSOC)
        self.assertEqual(g.state.entities[self.entity(g, BIG, player=2)].health, 1)
        self.assertEqual(len(g.state.character_attack_history), 1)
        self.play(g, P + 'kill', source)
        self.assertEqual(self.count(g, BIG), 0)

    def test_ursoc_stops_when_original_attacker_dies(self):
        g = self.game((URSOC,), enemy=(POISON, A, B), weapon=None)
        source = self.play(g, URSOC)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        rows = [row for row in g.state.character_attack_history if row.declaration.source_id == source]
        self.assertLessEqual(len(rows), 3)
        self.assertEqual(self.count(g, POISON, 2), 1)
        victims = [d for d in g.state.death_history if d.cause.source_id == source]
        revived = [row for row in g.state.resurrection_history if row.source_id == source]
        self.assertEqual(len(revived), len(victims))

    def test_newly_entered_deathrattle_minion_is_another_remaining_target(self):
        g = self.game((URSOC,), enemy=(SPAWN,), weapon=None)
        source = self.play(g, URSOC)
        self.assertEqual(len(g.state.character_attack_history), 2)
        self.assertEqual(g.state.players[2].board, [])
        self.assertEqual(len([d for d in g.state.death_history if d.cause.source_id == source]), 2)

    def test_direct_summon_skips_battlecry_but_later_normal_attack_is_remembered(self):
        g = self.game((P + 'summon', P + 'kill'), weapon=None)
        self.play(g, P + 'summon')
        self.assertEqual(g.state.character_attack_history, [])
        source = self.entity(g, URSOC)
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.attack(g, self.entity(g, A, player=2), source)
        self.play(g, P + 'kill', source)
        self.assertEqual(self.count(g, A), 1)

    def test_control_change_keeps_same_instance_kills_and_changes_recipient(self):
        g = self.game(board=(URSOC,), weapon=None,
            enemy_hand=(P + 'control', P + 'kill'))
        source = self.entity(g, URSOC)
        self.attack(g, self.entity(g, A, player=2), source)
        g.apply(EndTurn(1))
        self.play(g, P + 'control', source)
        self.play(g, P + 'kill', source)
        self.assertEqual(self.count(g, A, 2), 1)
        self.assertEqual(self.count(g, A, 1), 0)

    def test_bounce_and_replay_do_not_borrow_previous_incarnation_kills(self):
        g = self.game((P + 'bounce', P + 'kill'), (URSOC,), weapon=None)
        source = self.entity(g, URSOC)
        self.attack(g, self.entity(g, A, player=2), source)
        self.play(g, P + 'bounce', source)
        self.assertEqual(self.play(g, URSOC), source)
        self.play(g, P + 'kill', source)
        self.assertEqual(self.count(g, A), 0)

    def test_transform_and_rebuild_do_not_restore_old_incarnation_kills(self):
        g = self.game((P + 'change', P + 'restore', P + 'kill'), (URSOC,), weapon=None)
        source = self.entity(g, URSOC)
        self.attack(g, self.entity(g, A, player=2), source)
        self.play(g, P + 'change', source)
        self.play(g, P + 'restore', source)
        self.play(g, P + 'kill', source)
        self.assertEqual(self.count(g, A), 0)

    def test_current_copy_is_an_independent_physical_kill_source(self):
        g = self.game((P + 'copy', P + 'kill', P + 'kill'), (URSOC,), weapon=None)
        source = self.entity(g, URSOC)
        self.attack(g, self.entity(g, A, player=2), source)
        self.play(g, P + 'copy', source)
        clone = next(i for i in g.state.players[1].board if i != source)
        self.play(g, P + 'kill', clone)
        self.assertEqual(self.count(g, A), 0)
        self.play(g, P + 'kill', source)
        self.assertEqual(self.count(g, A), 1)

    def test_active_deathrattle_reuses_current_source_kills(self):
        g = self.game((P + 'trigger',), (URSOC,), weapon=None)
        source = self.entity(g, URSOC)
        self.attack(g, self.entity(g, A, player=2), source)
        self.play(g, P + 'trigger', source)
        self.assertEqual(self.count(g, A), 1)
        self.assertEqual(g.state.entities[source].zone, Zone.BOARD)

    def test_historical_trigger_uses_original_dead_ursoc_parameters(self):
        g = self.game((P + 'kill', SENTENCE), (URSOC,), weapon=None)
        source = self.entity(g, URSOC)
        self.attack(g, self.entity(g, A, player=2), source)
        self.play(g, P + 'kill', source)
        self.assertEqual(self.count(g, A), 1)
        self.play(g, SENTENCE)
        self.assertEqual(self.count(g, A), 2)
        self.portable(g)

    def test_original_inherited_native_parameters_do_not_rebind_to_receiver(self):
        g = self.game((P + 'kill', THORNS, P + 'kill'), (URSOC,), weapon=None)
        source = self.entity(g, URSOC)
        self.attack(g, self.entity(g, A, player=2), source)
        self.play(g, P + 'kill', source)
        receiver = self.play(g, THORNS)
        self.play(g, P + 'kill', receiver)
        self.assertEqual(self.count(g, A), 2)

    def test_real_living_nightmare_copy_is_two_two_before_ursoc_attacks(self):
        g = self.game((P + 'gift', URSOC), enemy=(), weapon=None)
        self.play(g, P + 'gift')
        source = self.play(g, URSOC)
        copied = next(d for d in g.state.death_history if d.card_id == URSOC and d.entity_id != source)
        self.assertEqual((copied.attack, copied.max_health), (2, 2))
        self.assertEqual(g.state.entities[source].health, 12)

    def test_attack_choice_restores_and_failed_choice_does_not_lose_remaining_targets(self):
        g = self.game((URSOC,), (WATCH,), (A,), weapon=None, mode='attack_wait')
        self.play(g, URSOC)
        self.assertIsNotNone(g.state.pending_choice)
        self.portable(g, 'attack_wait')
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        choices = 0
        while g.state.pending_choice:
            self.choose(g)
            choices += 1
            self.assertLessEqual(choices, 2)
        self.assertEqual(choices, 2)
        self.assertEqual(self.count(g, A, 2), 0)

    def test_revival_choice_restores_without_reselecting_or_repaying(self):
        g = self.game((P + 'break_weapon',), (WATCH,), mode='revive_wait')
        self.attack(g, self.entity(g, A, player=2))
        self.play(g, P + 'break_weapon')
        self.assertIsNotNone(g.state.pending_choice)
        mana = g.state.players[1].mana
        self.portable(g, 'revive_wait')
        self.choose(g)
        self.assertEqual(g.state.players[1].mana, mana)
        self.assertEqual(self.count(g, A), 1)

    def test_pure_kill_query_preserves_state_rng_and_death_order(self):
        g = self.game(enemy=(A,))
        self.attack(g, self.entity(g, A, player=2))
        weapon = g.state.entities[g.state.players[1].weapon_id]
        ref = KillSourceReference(weapon.id, weapon.card_id, weapon.kind, weapon.zone_epoch)
        before = g.snapshot()
        rows = killed_minion_deaths(g.state, g.registry, ref, events=g.events)
        self.assertEqual([d.id for d in rows], [1])
        self.assertEqual(g.snapshot(), before)

    def test_player_projection_has_no_kill_source_receipts(self):
        g = self.game((P + 'break_weapon',))
        self.attack(g, self.entity(g, A, player=2))
        self.play(g, P + 'break_weapon')
        for player in (1, 2):
            view = json.dumps(g.for_player(player).observe(), ensure_ascii=False)
            self.assertNotIn('killed_minions_selected', view)
            self.assertNotIn('original_source', view)
            g.for_player(player).legal_actions()


if __name__ == '__main__':
    unittest.main()
