from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_one_cost_passive_cards import (
    BLOOD_IMP, CHICKEN, CLERGY, CORSAIR, LEAVES, MASSAGER, NORTHSHIRE,
    SEEKER, SPACE_PIRATE, TIME_WYRM, TOTEM, WITCH_IMP, WYRM, load_batch,
)
from hs_sim.engine import (
    CardDefinition, CardType, EndTurn, Game, Keyword, PlayerSetup, Scenario,
    TargetSpec, TriggerSpec, UseHeroPower, Zone,
)
from hs_sim.engine.effects import (
    Buff, ChangeControl, ChoiceOption, CopyMinion, Damage, GrantKeyword, Heal,
    InvokeBehavior, ModifyWeapon, RequestChoice, ReturnToHand, Silence, TriggerDeathrattles,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind, EquippedWeaponReference, TargetMode
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from tools import card_batch as batch


P = 'test.k459.'
HIT, HEAL, BIG_HEAL, ZERO_HEAL, ZERO, KILL, GROW, ATTACK_BUFF, SILENCE, COPY, TAKE, DR, NOOP, SHIELD, WEAR, FAIL, WATCH = (
    P + s for s in ('hit', 'heal', 'big_heal', 'zero_heal', 'zero', 'kill', 'grow',
        'attack_buff', 'silence', 'copy', 'take', 'deathrattle', 'noop', 'shield', 'wear', 'fail', 'watch'))
YETI, RAVEN, AXE, DEATH_BITE, COUNTER, DORMANT, LOCATION, FLASHBACK = (
    'CORE_CS2_182', 'KAR_300', 'CS2_106', 'FP1_021', 'CORE_EX1_287',
    'BT_009', 'CORE_REV_990', 'TIME_711')
CONTEXT = GenerationContext('k459-explicit-passive-leaves', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry()
    r.register_pool(PoolDefinition('constructed.past.cards', 'explicit-twelve-passives-v1',
        CONTEXT.target_id, CONTEXT.mode, tuple(PoolMember(cid) for cid in LEAVES), complete=True))

    def fail(c):
        raise ResolutionError('K459 original late failure')

    bodies = {
        HIT: lambda c: (Damage(c.target_id, 1, c.source_id, DamageKind.SPELL),),
        KILL: lambda c: (Damage(c.target_id, 20, c.source_id, DamageKind.SPELL),),
        ZERO: lambda c: (Damage(c.target_id, 0, c.source_id, DamageKind.SPELL),),
        HEAL: lambda c: (Heal(c.target_id, 1, c.source_id),),
        BIG_HEAL: lambda c: (Heal(c.target_id, 2, c.source_id),),
        ZERO_HEAL: lambda c: (Heal(c.target_id, 0, c.source_id),),
        GROW: lambda c: (Buff(c.target_id, health=2, source_id=c.source_id),),
        ATTACK_BUFF: lambda c: (Buff(c.target_id, attack=3, source_id=c.source_id),),
        SILENCE: lambda c: (Silence(c.target_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id),),
        TAKE: lambda c: (ChangeControl(c.target_id, 2),),
        DR: lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        NOOP: lambda c: (),
        SHIELD: lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),),
        WEAR: lambda c: (ModifyWeapon(EquippedWeaponReference.capture(
            c.state.entities[c.state.players[2].weapon_id]), durability=-1, source_id=c.source_id),),
        FAIL: fail,
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        target = None if cid in (NOOP, WEAR, FAIL) else TargetSpec() if cid in (
            HIT, KILL, ZERO, HEAL, BIG_HEAL, ZERO_HEAL) else TargetSpec(
                TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, targeting=target))

    def watch(c):
        event = c.event
        origin = c.state.entities.get(event.source_id)
        source_card = None if origin is None else origin.card_id
        random_reward = event.kind == 'random_choice' and source_card in (BLOOD_IMP, WITCH_IMP)
        original_draw = event.kind == 'card_drawn' and source_card in (NORTHSHIRE, CLERGY)
        weapon_wear = event.kind == 'weapon_changed' and source_card == CORSAIR
        echo = event.kind == 'damage_dealt' and source_card == MASSAGER
        healing = event.kind == 'health_resolved' and c.health_result.flow == 'healing'
        if mode == 'fail' and (random_reward or original_draw or weapon_wear or echo):
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        waiting = (mode == 'wait_random' and random_reward or mode == 'wait_heal' and healing or
            mode == 'wait_draw' and original_draw or mode == 'wait_weapon' and weapon_wear)
        return (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),) if waiting else ()

    behavior = WATCH + '.' + mode
    r.register_behavior(behavior, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=40,
        triggers=tuple(TriggerSpec(event, behavior) for event in
            ('random_choice', 'card_drawn', 'weapon_changed', 'damage_dealt', 'health_resolved'))
            if mode != 'normal' else ()))
    r.validate()
    return r


class PastOneCostPassiveTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), board=(), *, enemy_hand=(), enemy_board=(), deck=(), enemy_deck=(),
             weapon=None, enemy_weapon=None, active=1, mode='normal'):
        self.mode = mode
        marker = (WATCH,) if mode != 'normal' else ()
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=marker+board, deck=deck, weapon_card_id=weapon,
                hero_power_card_id='HERO_08bp', mana=10, max_mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board, deck=enemy_deck,
                weapon_card_id=enemy_weapon, hero_power_card_id='HERO_08bp', mana=10, max_mana=10)),
            active_player=active, seed=459, generation_context=CONTEXT), fixture(mode))

    def cycle(self, g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def ids(self, g, player=1, zone='hand'):
        return tuple(g.state.entities[i].card_id for i in getattr(g.state.players[player], zone))

    def test_twelve_complete_raw_records_and_twenty_four_cached_primary_faces(self):
        data = load_batch()
        self.assertEqual((len(data['dependencies']), len(data['official_observations'])), (12, 24))
        rows = {x['record']['id']: x['record'] for x in data['dependencies']}; hashes = {}
        for o in data['official_observations']:
            path = o['response_file']
            if path not in hashes: hashes[path] = batch.sha(Path(path))
            self.assertEqual(hashes[path], o['response_sha256'])
            batch.check_face(rows[o['card_id']], o['face'], o['locale'],
                numeric_normalizations=data['numeric_normalizations'].get(o['card_id']))
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_twelve_real_hand_entries_pay_one_mana_and_preserve_printed_bodies(self):
        for cid in LEAVES:
            with self.subTest(card=cid):
                g = self.game((cid,)); source = self.play(g, cid); definition = g.registry.card(cid)
                self.assertEqual(g.state.players[1].mana, 9)
                self.assertEqual((g.state.entities[source].base_attack, g.state.entities[source].max_health),
                    (definition.attack, definition.health))

    def test_blood_imp_selects_one_other_friend_and_totem_grows_only_at_own_end(self):
        g = self.game(board=(BLOOD_IMP, YETI, YETI, TOTEM), deck=(RAVEN,), enemy_deck=(RAVEN,))
        source = self.entity(g, BLOOD_IMP, zone='board').id
        before = {i:g.state.entities[i].max_health for i in g.state.players[1].board}
        g.apply(EndTurn(1))
        deltas = [g.state.entities[i].max_health-before[i] for i in before if i != source]
        self.assertEqual(sum(deltas), 2); self.assertEqual(g.state.entities[source].max_health, 1)
        after = [g.state.entities[i].max_health for i in before]
        g.apply(EndTurn(2)); self.assertEqual([g.state.entities[i].max_health for i in before], after)

    def test_blood_imp_alone_has_no_reward_and_does_not_consume_rng(self):
        g = self.game(board=(BLOOD_IMP,)); rng = g._rng.getstate(); g.apply(EndTurn(1))
        self.assertEqual(g._rng.getstate(), rng)
        self.assertEqual(self.entity(g, BLOOD_IMP, zone='board').max_health, 1)

    def test_totem_health_gain_preserves_damage_and_is_removed_by_silence(self):
        g = self.game((HIT, SILENCE), board=(TOTEM,), deck=(RAVEN,), enemy_deck=(RAVEN,))
        source = self.entity(g, TOTEM, zone='board').id; self.play(g, HIT, source); self.cycle(g)
        self.assertEqual((g.state.entities[source].health, g.state.entities[source].max_health), (3, 4))
        self.play(g, SILENCE, source)
        self.assertEqual((g.state.entities[source].health, g.state.entities[source].max_health), (3, 3))

    def test_end_random_choice_wait_restores_selected_recipient_and_advances_turn_once(self):
        g = self.game(board=(BLOOD_IMP, YETI), mode='wait_random')
        before = {i:g.state.entities[i].max_health for i in g.state.players[1].board}
        g.apply(EndTurn(1)); self.assertIsNotNone(g.state.pending_choice)
        selected = next(e.target_id for e in reversed(g.events) if e.kind == 'random_choice')
        rng = g._rng.getstate(); g = self.portable(g); self.choose(g)
        self.assertEqual(g.state.entities[selected].max_health, before[selected]+1)
        self.assertEqual(sum(g.state.entities[i].max_health-before[i] for i in before), 1)
        self.assertEqual(g.state.active_player, 2); self.assertEqual(g._rng.getstate(), rng)

    def test_witch_imp_natural_death_rewards_a_friend_and_live_activation_can_reward_itself(self):
        g = self.game((KILL,), board=(WITCH_IMP, YETI), enemy_board=(YETI,))
        self.play(g, KILL, self.entity(g, WITCH_IMP, zone='board').id)
        self.assertEqual(self.entity(g, YETI, zone='board').max_health, 7)
        self.assertEqual(self.entity(g, YETI, player=2, zone='board').max_health, 5)
        h = self.game((DR,), board=(WITCH_IMP,)); source = self.entity(h, WITCH_IMP, zone='board').id
        self.play(h, DR, source); self.assertEqual(h.state.entities[source].max_health, 3)

    def test_witch_imp_empty_natural_death_preserves_rng(self):
        g = self.game((KILL,), board=(WITCH_IMP,)); rng = g._rng.getstate()
        self.play(g, KILL, self.entity(g, WITCH_IMP, zone='board').id)
        self.assertEqual(g._rng.getstate(), rng); self.assertFalse(g.state.players[1].board)

    def test_chicken_damaged_attack_is_continuous_and_stacks_with_ordinary_attack(self):
        g = self.game((GROW, ATTACK_BUFF, HIT, HEAL), board=(CHICKEN,))
        source = self.entity(g, CHICKEN, zone='board').id
        self.play(g, GROW, source); self.play(g, ATTACK_BUFF, source)
        self.assertEqual(g.state.entities[source].attack, 4)
        self.play(g, HIT, source); self.assertEqual(g.state.entities[source].attack, 9)
        self.play(g, HEAL, source); self.assertEqual(g.state.entities[source].attack, 4)

    def test_chicken_current_copy_and_transfer_keep_derived_condition_and_restore(self):
        g = self.game((GROW, HIT, COPY, TAKE, HEAL), board=(CHICKEN,))
        source = self.entity(g, CHICKEN, zone='board').id
        self.play(g, GROW, source); self.play(g, HIT, source); self.play(g, COPY, source)
        copy_id = next(i for i in g.state.players[1].board if i != source)
        self.assertEqual(g.state.entities[copy_id].attack, 6)
        self.play(g, TAKE, source); g = self.portable(g); self.play(g, HEAL, source)
        self.assertEqual(g.state.entities[source].attack, 1); self.assertEqual(g.state.entities[copy_id].attack, 6)

    def test_chicken_silence_removes_native_condition_and_caps_current_health(self):
        g = self.game((GROW, HIT, SILENCE), board=(CHICKEN,)); source = self.entity(g, CHICKEN, zone='board').id
        for cid in (GROW, HIT, SILENCE): self.play(g, cid, source)
        self.assertEqual((g.state.entities[source].zone, g.state.entities[source].health), (Zone.BOARD, 1))
        self.assertEqual(g.state.entities[source].attack, 1)

    def test_seeker_requires_six_other_minions_and_counts_a_dormant_one(self):
        for board, attack in (((YETI,)*5, 1), ((YETI,)*6, 5), ((YETI,)*5+(DORMANT,), 5)):
            g = self.game((SEEKER,), board=board); source = self.play(g, SEEKER)
            self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health), (attack, attack))

    def test_seeker_does_not_count_a_location_as_a_sixth_minion(self):
        g = self.game((SEEKER,), board=(YETI,)*5+(LOCATION,)); source = self.play(g, SEEKER)
        self.assertEqual(g.state.entities[source].attack, 1)

    def test_space_pirate_next_weapon_discount_survives_turn_and_consumes_only_once(self):
        g = self.game((KILL, NOOP, AXE, AXE), board=(SPACE_PIRATE,), deck=(RAVEN,), enemy_deck=(RAVEN,))
        self.play(g, KILL, self.entity(g, SPACE_PIRATE, zone='board').id); self.play(g, NOOP)
        self.cycle(g); g = self.portable(g); mana = g.state.players[1].mana
        self.play(g, AXE); self.assertEqual(g.state.players[1].mana, mana-1)
        self.play(g, AXE); self.assertEqual(g.state.players[1].mana, mana-3)

    def test_space_pirate_live_activation_installs_real_weapon_only_modifier(self):
        g = self.game((DR, RAVEN, AXE), board=(SPACE_PIRATE,))
        self.play(g, DR, self.entity(g, SPACE_PIRATE, zone='board').id)
        self.play(g, RAVEN); self.assertEqual(g.state.players[1].mana, 9)
        self.play(g, AXE); self.assertEqual(g.state.players[1].mana, 8)

    def test_northshire_draws_for_real_healing_of_either_sides_minion(self):
        g = self.game((HIT, HEAL, HIT, HEAL), board=(NORTHSHIRE, YETI), enemy_board=(YETI,), deck=(RAVEN, YETI))
        for player in (1, 2):
            target = self.entity(g, YETI, player=player, zone='board').id
            self.play(g, HIT, target); self.play(g, HEAL, target)
        self.assertEqual(self.ids(g), (RAVEN, YETI)); self.assertEqual(self.ids(g, zone='deck'), ())

    def test_northshire_ignores_full_health_zero_healing_damage_and_hero_healing(self):
        g = self.game((HEAL, ZERO_HEAL, HIT, HEAL), board=(NORTHSHIRE, YETI), deck=(RAVEN,))
        target = self.entity(g, YETI, zone='board').id
        self.play(g, HEAL, target); self.play(g, ZERO_HEAL, target)
        hero = g.state.players[1].hero_id; self.play(g, HIT, hero); self.play(g, HEAL, hero)
        self.assertEqual(self.ids(g, zone='deck'), (RAVEN,))

    def test_northshire_can_trigger_on_opponents_turn_and_opponents_healing(self):
        g = self.game(board=(NORTHSHIRE,), enemy_hand=(HIT, HEAL), enemy_board=(YETI,), deck=(RAVEN,), active=2)
        target = self.entity(g, YETI, player=2, zone='board').id
        self.play(g, HIT, target, player=2); self.play(g, HEAL, target, player=2)
        self.assertEqual(self.ids(g), (RAVEN,))

    def test_northshire_wait_uses_original_positive_heal_even_after_target_is_full(self):
        g = self.game((HIT, HEAL), board=(NORTHSHIRE, YETI), deck=(RAVEN,), mode='wait_heal')
        target = self.entity(g, YETI, zone='board').id
        self.play(g, HIT, target); self.play(g, HEAL, target); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[target].health, g.state.entities[target].max_health)
        g = self.portable(g); self.choose(g); self.assertEqual(self.ids(g), (RAVEN,))

    def test_clergy_overheal_at_full_health_draws_even_when_actual_heal_is_zero(self):
        g = self.game((HEAL,), board=(CLERGY,), deck=(RAVEN,)); self.play(g, HEAL, self.entity(g, CLERGY, zone='board').id)
        self.assertEqual(self.ids(g), (RAVEN,))

    def test_clergy_partial_and_exact_heals_do_not_count_as_overheal(self):
        g = self.game((HIT, HIT, HEAL, HEAL, HEAL), board=(CLERGY,), deck=(RAVEN,))
        target = self.entity(g, CLERGY, zone='board').id
        for cid in (HIT, HIT, HEAL, HEAL): self.play(g, cid, target)
        self.assertEqual(self.ids(g, zone='deck'), (RAVEN,))
        self.play(g, HEAL, target); self.assertEqual(self.ids(g), (RAVEN,))

    def test_clergy_only_own_overheal_and_nonzero_request_can_draw(self):
        g = self.game((ZERO_HEAL, HEAL, HIT, BIG_HEAL), board=(CLERGY, YETI), deck=(RAVEN,))
        source = self.entity(g, CLERGY, zone='board').id
        self.play(g, ZERO_HEAL, source); self.play(g, HEAL, self.entity(g, YETI, zone='board').id)
        self.assertEqual(self.ids(g, zone='deck'), (RAVEN,))
        self.play(g, HIT, source); self.play(g, BIG_HEAL, source)
        self.assertEqual(self.ids(g), (RAVEN,))

    def test_clergy_draw_wait_restores_one_private_physical_draw(self):
        g = self.game((HEAL,), board=(CLERGY,), deck=(RAVEN,), mode='wait_draw')
        self.play(g, HEAL, self.entity(g, CLERGY, zone='board').id); self.assertIsNotNone(g.state.pending_choice)
        g = self.portable(g); self.choose(g); self.assertEqual(self.ids(g), (RAVEN,))
        observer = g.for_player(2).observe()['observation']
        self.assertIsNone(observer['players'][0]['hand'][0]['card_id'])

    def test_clergy_empty_deck_uses_ordinary_fatigue(self):
        g = self.game((HEAL,), board=(CLERGY,)); hero = g.state.players[1].hero_id
        self.play(g, HEAL, self.entity(g, CLERGY, zone='board').id)
        self.assertEqual(g.state.entities[hero].health, 29)

    def test_both_mana_wyrm_editions_buff_for_own_successful_spells(self):
        g = self.game((NOOP, NOOP), board=(WYRM, TIME_WYRM))
        self.play(g, NOOP); self.play(g, NOOP)
        self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board], [3, 3])

    def test_mana_wyrms_ignore_opponents_spells_countered_casts_and_hero_powers(self):
        g = self.game((NOOP,), board=(WYRM, TIME_WYRM), enemy_hand=(NOOP, COUNTER), active=2)
        self.play(g, NOOP, player=2); self.play(g, COUNTER, player=2); g.apply(EndTurn(2))
        self.play(g, NOOP); g.apply(UseHeroPower(1, g.state.players[1].hero_power_id, g.state.players[2].hero_id))
        self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board], [1, 1])

    def test_mana_wyrm_silence_stops_new_spell_rewards(self):
        g = self.game((NOOP, SILENCE, NOOP), board=(WYRM,)); source = self.entity(g, WYRM, zone='board').id
        self.play(g, NOOP); self.play(g, SILENCE, source); self.play(g, NOOP)
        self.assertEqual(g.state.entities[source].attack, 1)

    def test_massager_echoes_original_positive_damage_including_a_lethal_hit(self):
        g = self.game((HIT, KILL), board=(MASSAGER,)); source = self.entity(g, MASSAGER, zone='board').id
        self.play(g, HIT, source); self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 29)
        self.play(g, KILL, source); self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 9)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)

    def test_massager_zero_shield_and_silence_do_not_echo(self):
        g = self.game((ZERO, SHIELD, HIT, SILENCE, HIT), board=(MASSAGER,))
        source = self.entity(g, MASSAGER, zone='board').id
        for cid in (ZERO, SHIELD, HIT, SILENCE, HIT): self.play(g, cid, source)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 30)

    def test_corsair_removes_one_durability_from_opponents_original_weapon_only(self):
        g = self.game((CORSAIR,), weapon=AXE, enemy_weapon=AXE)
        own, enemy = g.state.players[1].weapon_id, g.state.players[2].weapon_id; self.play(g, CORSAIR)
        self.assertEqual(g.state.entities[own].durability, 2); self.assertEqual(g.state.entities[enemy].durability, 1)

    def test_corsair_last_durability_runs_real_death_bite_deathrattle(self):
        g = self.game((WEAR, CORSAIR), enemy_weapon=DEATH_BITE, enemy_board=(YETI,))
        weapon = g.state.players[2].weapon_id; self.play(g, WEAR); source = self.play(g, CORSAIR)
        self.assertIsNone(g.state.players[2].weapon_id); self.assertEqual(g.state.entities[weapon].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[source].health, 1)
        self.assertEqual(self.entity(g, YETI, player=2, zone='board').health, 4)

    def test_corsair_weapon_change_wait_restores_without_second_durability_loss(self):
        g = self.game((CORSAIR,), enemy_weapon=AXE, mode='wait_weapon'); weapon = g.state.players[2].weapon_id
        self.play(g, CORSAIR); self.assertIsNotNone(g.state.pending_choice)
        g = self.portable(g); self.choose(g); self.assertEqual(g.state.entities[weapon].durability, 1)

    def test_late_failures_roll_back_real_heal_draw_damage_echo_and_weapon_wear(self):
        for hand, board, enemy_weapon, operation, target in (
                ((HEAL,), (CLERGY,), None, HEAL, CLERGY), ((HIT,), (MASSAGER,), None, HIT, MASSAGER),
                ((CORSAIR,), (), AXE, CORSAIR, None)):
            with self.subTest(operation=operation):
                g = self.game(hand, board=board, deck=(RAVEN,), enemy_weapon=enemy_weapon, mode='fail')
                before = g.snapshot(); target_id = None if target is None else self.entity(g, target, zone='board').id
                with self.assertRaisesRegex(ResolutionError, 'K459 original late failure'): self.play(g, operation, target_id)
                self.assertEqual(g.snapshot(), before)

    def test_end_random_failure_rolls_back_entire_turn_and_rng(self):
        g = self.game(board=(BLOOD_IMP, YETI), mode='fail'); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K459 original late failure'): g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(), before)

    def test_real_flashback_summons_native_passives_without_battlecry(self):
        g = self.game((FLASHBACK, RAVEN)); self.play(g, RAVEN); self.play(g, FLASHBACK)
        self.assertEqual(len(g.state.players[1].board), 3); self.assertFalse(g.state.battlecry_history)
        self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertTrue(all(g.state.entities[i].card_id in LEAVES for i in g.state.players[1].board[1:]))

    def test_production_past_domain_is_still_not_bound_from_this_small_batch(self):
        self.assertNotIn('constructed.past.cards', build_registry().pools)


if __name__ == '__main__':
    unittest.main()
