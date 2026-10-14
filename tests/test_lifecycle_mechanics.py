"""M1 public-API tests for the documented prototype-v2 lifecycle contract.

These scenarios are synthetic interaction tests, not evidence of official
Hearthstone timing.  Every state change goes through Scenario -> Game.apply.
"""

import unittest

from hs_sim.engine.actions import Attack, EndTurn, PlayCard
from hs_sim.engine.effects import (
    Buff, ChangeControl, CopyMinion, Damage, DamageBatch, Destroy,
    GainArmor, GrantAura, GrantDeathrattle, GrantKeyword, GrantTrigger,
    RemoveEnchantment, ReturnToHand, ShuffleIntoDeck, Silence, Summon, Transform,
)
from hs_sim.engine.errors import IllegalAction, ResolutionError, SnapshotError
from hs_sim.engine.game import Game, PlayerSetup, Scenario
from hs_sim.engine.model import AuraSpec, CardDefinition, CardType, Keyword, TriggerSpec, Zone
from hs_sim.engine.registry import Registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class LifecycleMechanicsTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry("lifecycle-tests-v2")
        self.registry.register_card(CardDefinition("hero", "Hero", CardType.HERO, health=30))
        for card_id, attack, health, keywords in (
            ("plain", 2, 4, ()),
            ("token", 1, 1, ()),
            ("reborn", 2, 3, (Keyword.REBORN,)),
            ("shield_reborn", 2, 3, (Keyword.DIVINE_SHIELD, Keyword.REBORN)),
            ("shield", 2, 4, (Keyword.DIVINE_SHIELD,)),
            ("charge", 2, 4, (Keyword.CHARGE,)),
        ):
            self.registry.register_card(CardDefinition(card_id, card_id, CardType.MINION,
                                                       attack=attack, health=health, keywords=keywords))
        self.registry.register_card(CardDefinition("aura", "Aura", CardType.MINION,
                                                   attack=1, health=3, auras=(AuraSpec(1),)))
        self.registry.register_behavior("armor2", lambda ctx: (GainArmor(ctx.player_id, 2),))
        self.registry.register_behavior("armor3", lambda ctx: (GainArmor(ctx.player_id, 3),))
        self.registry.register_behavior("hatch", lambda ctx: (Summon(ctx.player_id, "token"),))
        self.registry.register_card(CardDefinition("egg", "Egg", CardType.MINION,
                                                   health=2, deathrattle="hatch"))
        self.registry.register_card(CardDefinition("reborn_egg", "Reborn egg", CardType.MINION,
                                                   health=2, deathrattle="hatch",
                                                   keywords=(Keyword.REBORN,)))
        self.spell("kill", lambda ctx: (Destroy(ctx.target_id),), targeted=True)
        self.spell("silence", lambda ctx: (Silence(ctx.target_id),), targeted=True)
        self.spell("ping", lambda ctx: (Damage(ctx.target_id, 1, ctx.source_id),), targeted=True)

    def spell(self, card_id, behavior, *, targeted=False):
        self.registry.register_behavior(card_id, behavior)
        self.registry.register_card(CardDefinition(card_id, card_id, CardType.SPELL,
                                                   on_play=card_id, requires_target=targeted))

    def game(self, *, hand=(), board=(), deck=(), opponent_hand=(), opponent_board=(),
             opponent_deck=(), seed=19):
        return Game.from_scenario(Scenario((
            PlayerSetup("hero", hand=hand, board=board, deck=deck, mana=10, max_mana=10),
            PlayerSetup("hero", hand=opponent_hand, board=opponent_board,
                        deck=opponent_deck, mana=10, max_mana=10),
        ), seed=seed), self.registry)

    def play(self, game, card_id, target_id=None, *, player_id=1, position=None):
        state = game.state
        entity_id = next(i for i in state.players[player_id].hand if state.entities[i].card_id == card_id)
        return game.apply(PlayCard(player_id, entity_id, target_id, position))

    @staticmethod
    def armor(game, player_id=1):
        state = game.state
        return state.entities[state.players[player_id].hero_id].armor

    def test_stacked_enchantments_keep_distinct_identity_and_provenance(self):
        self.spell("boost", lambda ctx: (Buff(ctx.target_id, 2, 3, source_id=ctx.source_id),),
                   targeted=True)
        game = self.game(hand=("boost", "boost"), board=("plain",))
        target = game.state.players[1].board[0]
        sources = tuple(game.state.players[1].hand)
        self.play(game, "boost", target)
        self.play(game, "boost", target)
        entity = game.state.entities[target]
        self.assertEqual((entity.attack, entity.max_health, entity.health), (6, 10, 10))
        self.assertEqual(len(entity.enchantments), 2)
        self.assertEqual([item.source_id for item in entity.enchantments], list(sources))
        self.assertEqual(len({item.id for item in entity.enchantments}), 2)

    def test_expiry_runs_after_end_turn_reactions_and_clamps_current_health(self):
        self.registry.register_behavior("observe_attack", lambda ctx: (GainArmor(ctx.player_id, ctx.source.attack),))
        self.registry.register_card(CardDefinition("observer", "Observer", CardType.MINION,
                                                   attack=2, health=4,
                                                   triggers=(TriggerSpec("turn_ended", "observe_attack"),)))
        self.spell("temporary", lambda ctx: (Buff(ctx.target_id, 3, 4, source_id=ctx.source_id,
                                                   expires_turn=ctx.state.turn),), targeted=True)
        game = self.game(hand=("temporary", "ping"), board=("observer",))
        target = game.state.players[1].board[0]
        self.play(game, "temporary", target)
        self.play(game, "ping", target)
        self.assertEqual(game.state.entities[target].health, 7)
        game.apply(EndTurn(1))
        entity = game.state.entities[target]
        self.assertEqual(self.armor(game), 5)
        self.assertEqual((entity.attack, entity.max_health, entity.health), (2, 4, 4))
        self.assertEqual(entity.enchantments, [])

    def test_temporary_granted_keyword_enables_attack_and_expires(self):
        self.spell("haste", lambda ctx: (GrantKeyword(ctx.target_id, Keyword.WINDFURY,
                                                     source_id=ctx.source_id, expires_turn=ctx.state.turn),),
                   targeted=True)
        game = self.game(hand=("haste",), board=("plain",))
        state = game.state
        target, enemy = state.players[1].board[0], state.players[2].hero_id
        self.play(game, "haste", target)
        game.apply(Attack(1, target, enemy))
        game.apply(Attack(1, target, enemy))
        with self.assertRaises(IllegalAction):
            game.apply(Attack(1, target, enemy))
        game.apply(EndTurn(1))
        self.assertNotIn(Keyword.WINDFURY, game.state.entities[target].keywords)

    def test_remove_one_enchantment_does_not_remove_another(self):
        self.spell("boost", lambda ctx: (Buff(ctx.target_id, 2, 1),), targeted=True)
        self.spell("remove_first", lambda ctx: (
            RemoveEnchantment(ctx.target_id, ctx.state.entities[ctx.target_id].enchantments[0].id),),
            targeted=True)
        game = self.game(hand=("boost", "boost", "remove_first"), board=("plain",))
        target = game.state.players[1].board[0]
        self.play(game, "boost", target)
        self.play(game, "boost", target)
        surviving_id = game.state.entities[target].enchantments[1].id
        self.play(game, "remove_first", target)
        entity = game.state.entities[target]
        self.assertEqual((entity.attack, entity.max_health), (4, 5))
        self.assertEqual([item.id for item in entity.enchantments], [surviving_id])

    def test_silence_removes_printed_and_granted_abilities_and_buffs(self):
        self.spell("enhance", lambda ctx: (Buff(ctx.target_id, 3, 4),
                                            GrantKeyword(ctx.target_id, Keyword.TAUNT),
                                            GrantDeathrattle(ctx.target_id, "armor2")), targeted=True)
        game = self.game(hand=("enhance", "silence", "kill"), board=("shield_reborn",))
        target = game.state.players[1].board[0]
        self.play(game, "enhance", target)
        self.play(game, "silence", target)
        entity = game.state.entities[target]
        self.assertTrue(entity.silenced)
        self.assertEqual((entity.attack, entity.max_health), (2, 3))
        self.assertEqual(entity.keywords, set())
        self.assertEqual(entity.enchantments, [])
        self.play(game, "kill", target)
        self.assertEqual(game.state.players[1].board, [])
        self.assertEqual(self.armor(game), 0)

    def test_silence_health_removal_preserves_remaining_health_below_base_max(self):
        self.spell("grow", lambda ctx: (Buff(ctx.target_id, health=4), Damage(ctx.target_id, 6)),
                   targeted=True)
        game = self.game(hand=("grow", "silence"), board=("plain",))
        target = game.state.players[1].board[0]
        self.play(game, "grow", target)
        self.assertEqual(game.state.entities[target].health, 2)
        self.play(game, "silence", target)
        entity = game.state.entities[target]
        self.assertEqual((entity.max_health, entity.health, entity.damage), (4, 2, 2))

    def test_silenced_recipient_still_receives_external_attack_aura(self):
        game = self.game(hand=("silence",), board=("aura", "plain"))
        source, target = game.state.players[1].board
        self.play(game, "silence", target)
        self.assertEqual(game.state.entities[target].attack, 3)
        self.assertEqual(game.state.entities[source].attack, 1)

    def test_multiple_granted_deathrattles_each_execute_once_in_acquisition_order(self):
        self.spell("grant", lambda ctx: (GrantDeathrattle(ctx.target_id, "armor2", source_id=ctx.source_id),
                                          GrantDeathrattle(ctx.target_id, "armor3", source_id=ctx.source_id)),
                   targeted=True)
        game = self.game(hand=("grant", "kill"), board=("plain",))
        target = game.state.players[1].board[0]
        self.play(game, "grant", target)
        result = self.play(game, "kill", target)
        self.assertEqual(self.armor(game), 5)
        self.assertEqual([e.amount for e in result.events if e.kind == "armor_gained"], [2, 3])

    def test_granted_trigger_is_active_then_removed_by_silence(self):
        self.spell("grant", lambda ctx: (GrantTrigger(ctx.target_id, "damage_dealt", "armor2"),),
                   targeted=True)
        game = self.game(hand=("grant", "ping", "silence", "ping"), board=("plain",))
        target = game.state.players[1].board[0]
        enemy = game.state.players[2].hero_id
        self.play(game, "grant", target)
        self.play(game, "ping", enemy)
        self.assertEqual(self.armor(game), 2)
        self.play(game, "silence", target)
        self.play(game, "ping", enemy)
        self.assertEqual(self.armor(game), 2)

    def test_granted_aura_is_derived_and_stops_when_its_source_is_silenced(self):
        self.spell("grant", lambda ctx: (GrantAura(ctx.target_id, 3, source_id=ctx.source_id),),
                   targeted=True)
        game = self.game(hand=("grant", "ping", "silence"), board=("plain", "plain"))
        source, recipient = game.state.players[1].board
        self.play(game, "grant", source)
        self.assertEqual(game.state.entities[recipient].attack, 5)
        self.assertEqual(game.state.entities[source].attack, 2)
        self.play(game, "ping", game.state.players[2].hero_id)
        self.assertEqual(game.state.entities[recipient].attack, 5)
        self.play(game, "silence", source)
        self.assertEqual(game.state.entities[recipient].attack, 2)

    def test_temporary_granted_aura_and_trigger_expire_at_owner_turn_boundary(self):
        self.spell("grant", lambda ctx: (
            GrantAura(ctx.target_id, 2, include_self=True, expires_turn=ctx.state.turn),
            GrantTrigger(ctx.target_id, "turn_ended", "armor3", expires_turn=ctx.state.turn),
        ), targeted=True)
        game = self.game(hand=("grant",), board=("plain",),
                         deck=("plain",), opponent_deck=("plain",))
        target = game.state.players[1].board[0]
        self.play(game, "grant", target)
        self.assertEqual(game.state.entities[target].attack, 4)
        game.apply(EndTurn(1))
        self.assertEqual(self.armor(game), 3)
        self.assertEqual(game.state.entities[target].attack, 2)
        game.apply(EndTurn(2))
        self.assertEqual(self.armor(game), 3)

    def test_reborn_creates_new_identity_with_one_health_without_extra_enchantments(self):
        self.spell("enhance", lambda ctx: (Buff(ctx.target_id, 5, 5),
                                            GrantKeyword(ctx.target_id, Keyword.REBORN),
                                            GrantDeathrattle(ctx.target_id, "armor2")), targeted=True)
        game = self.game(hand=("enhance", "kill"), board=("reborn",))
        original = game.state.players[1].board[0]
        self.play(game, "enhance", original)
        self.play(game, "kill", original)
        state = game.state
        replacement = state.players[1].board[0]
        entity = state.entities[replacement]
        self.assertNotEqual(original, replacement)
        self.assertEqual(state.entities[original].zone, Zone.GRAVEYARD)
        self.assertEqual(entity.origin_entity_id, original)
        self.assertEqual((entity.attack, entity.max_health, entity.health), (2, 3, 1))
        self.assertEqual(entity.enchantments, [])
        self.assertNotIn(Keyword.REBORN, entity.keywords)
        old_reborn_instances = [a for a in state.entities[original].abilities if a.keyword == Keyword.REBORN]
        self.assertEqual(len(old_reborn_instances), 2)
        self.assertTrue(all(a.consumed for a in old_reborn_instances))
        self.assertEqual(self.armor(game), 2)
        self.assertFalse(any(a.kind == "deathrattle" for a in entity.abilities))

    def test_reborn_restores_printed_shield_but_cannot_reborn_twice(self):
        game = self.game(hand=("ping", "kill", "ping", "kill"), board=("shield_reborn",))
        original = game.state.players[1].board[0]
        self.play(game, "ping", original)
        self.assertNotIn(Keyword.DIVINE_SHIELD, game.state.entities[original].keywords)
        self.play(game, "kill", original)
        replacement = game.state.players[1].board[0]
        self.assertIn(Keyword.DIVINE_SHIELD, game.state.entities[replacement].keywords)
        self.assertNotIn(Keyword.REBORN, game.state.entities[replacement].keywords)
        self.play(game, "ping", replacement)
        self.assertEqual(game.state.entities[replacement].health, 1)
        self.play(game, "kill", replacement)
        self.assertEqual(game.state.players[1].board, [])
        self.assertEqual(len(game.state.death_history), 2)

    def test_deathrattle_fills_last_board_slot_before_reborn_attempt(self):
        game = self.game(hand=("kill",), board=("reborn_egg",) + ("plain",) * 6)
        original = game.state.players[1].board[0]
        self.play(game, "kill", original)
        state = game.state
        self.assertEqual(len(state.players[1].board), 7)
        self.assertEqual(sum(state.entities[i].card_id == "token" for i in state.players[1].board), 1)
        self.assertFalse(any(state.entities[i].card_id == "reborn_egg" for i in state.players[1].board))
        self.assertEqual(len(state.death_history), 1)

    def test_all_deathrattles_in_a_batch_run_before_reborn_summons(self):
        self.spell("wipe", lambda ctx: (DamageBatch(tuple(Damage(i, 2) for i in ctx.state.players[1].board)),))
        game = self.game(hand=("wipe",), board=("reborn_egg", "reborn_egg"))
        original = tuple(game.state.players[1].board)
        result = self.play(game, "wipe")
        state = game.state
        summons = [state.entities[e.target_id].card_id for e in result.events
                   if e.kind == "minion_summoned"]
        self.assertEqual(summons, ["token", "token", "reborn_egg", "reborn_egg"])
        self.assertEqual({record.entity_id for record in state.death_history}, set(original))
        self.assertEqual(len({record.batch for record in state.death_history}), 1)

    def test_silence_suppresses_reborn_even_when_card_definition_has_it(self):
        game = self.game(hand=("silence", "kill"), board=("reborn",))
        original = game.state.players[1].board[0]
        self.play(game, "silence", original)
        self.play(game, "kill", original)
        self.assertEqual(game.state.players[1].board, [])
        self.assertNotIn(Keyword.REBORN, game.state.death_history[-1].keywords)

    def test_death_record_preserves_derived_stats_before_aura_sources_leave(self):
        self.spell("enhance", lambda ctx: (Buff(ctx.target_id, 2, 3, source_id=ctx.source_id),), targeted=True)
        self.spell("wipe", lambda ctx: (DamageBatch(tuple(Damage(i, 20) for i in ctx.state.players[1].board)),))
        game = self.game(hand=("enhance", "wipe"), board=("aura", "plain"))
        source, target = game.state.players[1].board
        self.play(game, "enhance", target)
        self.play(game, "wipe")
        state = game.state
        record = next(item for item in state.death_history if item.entity_id == target)
        self.assertEqual((record.attack, record.max_health, record.damage, record.position), (5, 7, 20, 1))
        self.assertEqual((record.base_attack, record.base_health), (2, 4))
        self.assertEqual(len(record.enchantments), 1)
        self.assertEqual(record.controller, 1)
        self.assertEqual(record.batch, next(item.batch for item in state.death_history if item.entity_id == source))
        self.assertEqual(state.entities[target].aura_attack, 0)
        self.assertEqual(record.attack, 5)

    def test_return_to_hand_keeps_identity_and_resets_damage_buffs_and_consumption(self):
        self.spell("enhance", lambda ctx: (Buff(ctx.target_id, 3, 2),
                                            GrantKeyword(ctx.target_id, Keyword.TAUNT)), targeted=True)
        self.spell("bounce", lambda ctx: (ReturnToHand(ctx.target_id),), targeted=True)
        game = self.game(hand=("enhance", "ping", "ping", "bounce"), board=("shield",))
        target = game.state.players[1].board[0]
        self.play(game, "enhance", target)
        self.play(game, "ping", target)
        self.play(game, "ping", target)
        self.play(game, "bounce", target)
        entity = game.state.entities[target]
        self.assertEqual(entity.zone, Zone.HAND)
        self.assertIn(target, game.state.players[1].hand)
        self.assertEqual((entity.attack, entity.max_health, entity.damage), (2, 4, 0))
        self.assertEqual(entity.keywords, {Keyword.DIVINE_SHIELD})
        self.assertEqual(entity.enchantments, [])
        self.assertEqual(game.state.death_history, [])

    def test_full_hand_return_uses_deathrattle_and_death_record(self):
        self.spell("bounce", lambda ctx: (ReturnToHand(ctx.target_id),), targeted=True)
        game = self.game(hand=("bounce",), opponent_hand=("plain",) * 10, opponent_board=("egg",))
        target = game.state.players[2].board[0]
        self.play(game, "bounce", target)
        state = game.state
        self.assertEqual(state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual([state.entities[i].card_id for i in state.players[2].board], ['token'])
        self.assertEqual(len(state.players[2].hand), 10)
        self.assertEqual([d.entity_id for d in state.death_history], [target])
        self.assertEqual(state.death_history[0].cause.kind, 'destroy')

    def test_transform_keeps_identity_position_and_attack_history_but_resets_definition(self):
        self.spell("transform", lambda ctx: (Transform(ctx.target_id, "shield"),), targeted=True)
        game = self.game(hand=("transform",), board=("plain", "charge", "plain"))
        before = game.state
        target = before.players[1].board[1]
        game.apply(Attack(1, target, before.players[2].hero_id))
        summoned_turn = game.state.entities[target].summoned_turn
        self.play(game, "transform", target)
        state = game.state
        entity = state.entities[target]
        self.assertEqual(state.players[1].board[1], target)
        self.assertEqual((entity.card_id, entity.attack, entity.max_health, entity.damage), ("shield", 2, 4, 0))
        self.assertEqual(entity.keywords, {Keyword.DIVINE_SHIELD})
        self.assertEqual((entity.attacks_this_turn, entity.summoned_turn), (1, summoned_turn))
        with self.assertRaises(IllegalAction):
            game.apply(Attack(1, target, before.players[2].hero_id))

    def test_copy_current_clones_damage_dynamic_abilities_and_consumption_with_new_ids(self):
        self.spell("enhance", lambda ctx: (Buff(ctx.target_id, 3, 2),
                                            GrantDeathrattle(ctx.target_id, "armor2")), targeted=True)
        self.spell("copy", lambda ctx: (CopyMinion(ctx.target_id, ctx.player_id, mode="current"),), targeted=True)
        game = self.game(hand=("enhance", "ping", "ping", "copy"), board=("shield",))
        target = game.state.players[1].board[0]
        self.play(game, "enhance", target)
        self.play(game, "ping", target)
        self.play(game, "ping", target)
        self.play(game, "copy", target)
        state = game.state
        source, copy_id = state.players[1].board
        original, duplicate = state.entities[source], state.entities[copy_id]
        self.assertNotEqual(source, copy_id)
        self.assertEqual((duplicate.attack, duplicate.max_health, duplicate.damage), (5, 6, 1))
        self.assertNotIn(Keyword.DIVINE_SHIELD, duplicate.keywords)
        self.assertTrue(any(a.kind == "deathrattle" and a.behavior_id == "armor2" for a in duplicate.abilities))
        original_ids = {item.id for item in (*original.abilities, *original.enchantments)}
        duplicate_ids = {item.id for item in (*duplicate.abilities, *duplicate.enchantments)}
        self.assertTrue(original_ids.isdisjoint(duplicate_ids))

    def test_copy_base_uses_printed_stats_and_restores_consumed_printed_keywords(self):
        self.spell("enhance", lambda ctx: (Buff(ctx.target_id, 3, 2),
                                            GrantKeyword(ctx.target_id, Keyword.TAUNT)), targeted=True)
        self.spell("copy", lambda ctx: (CopyMinion(ctx.target_id, ctx.player_id, mode="base"),), targeted=True)
        game = self.game(hand=("enhance", "ping", "copy"), board=("shield",))
        target = game.state.players[1].board[0]
        self.play(game, "enhance", target)
        self.play(game, "ping", target)
        self.play(game, "copy", target)
        state = game.state
        duplicate = state.entities[state.players[1].board[-1]]
        self.assertEqual((duplicate.attack, duplicate.max_health, duplicate.damage), (2, 4, 0))
        self.assertEqual(duplicate.keywords, {Keyword.DIVINE_SHIELD})
        self.assertEqual(duplicate.enchantments, [])

    def test_control_transfer_preserves_owner_and_buffs_but_applies_summoning_limit(self):
        self.spell("take", lambda ctx: (ChangeControl(ctx.target_id, ctx.player_id),), targeted=True)
        self.spell("enhance", lambda ctx: (Buff(ctx.target_id, 3, 2),), targeted=True)
        game = self.game(hand=("enhance", "take"), board=("token",), opponent_board=("plain",))
        before = game.state
        target = before.players[2].board[0]
        old_order = before.entities[target].entered_order
        self.play(game, "enhance", target)
        self.play(game, "take", target)
        state = game.state
        entity = state.entities[target]
        self.assertEqual((entity.owner, entity.controller), (2, 1))
        self.assertEqual(state.players[1].board[-1], target)
        self.assertEqual(state.players[2].board, [])
        self.assertEqual((entity.attack, entity.max_health), (5, 6))
        self.assertGreater(entity.entered_order, old_order)
        with self.assertRaises(IllegalAction):
            game.apply(Attack(1, target, state.players[2].hero_id))

    def test_shuffle_resets_entity_and_replays_rng_and_dynamic_history(self):
        self.spell("enhance", lambda ctx: (Buff(ctx.target_id, 3, 2),
                                            GrantKeyword(ctx.target_id, Keyword.TAUNT)), targeted=True)
        self.spell("shuffle", lambda ctx: (ShuffleIntoDeck(ctx.target_id, ctx.player_id),), targeted=True)
        game = self.game(hand=("enhance", "ping", "shuffle", "kill"), board=("plain", "reborn"),
                         deck=("token", "shield", "charge", "plain"))
        target, reborn = game.state.players[1].board
        self.play(game, "enhance", target)
        self.play(game, "ping", target)
        self.play(game, "kill", reborn)
        fork = game.clone()
        self.play(game, "shuffle", target)
        self.play(fork, "shuffle", target)
        self.assertEqual(game.state_hash(), fork.state_hash())
        entity = game.state.entities[target]
        self.assertEqual(entity.zone, Zone.DECK)
        self.assertEqual((entity.attack, entity.max_health, entity.damage), (2, 4, 0))
        self.assertEqual(entity.keywords, set())
        self.assertEqual(entity.enchantments, [])
        restored = Game.from_snapshot(game.snapshot(), self.registry)
        self.assertEqual(restored.state_hash(), game.state_hash())
        reconstructed = replay(build_replay(game), self.registry)
        self.assertEqual(reconstructed.state_hash(), game.state_hash())
        self.assertEqual(reconstructed.events, game.events)
        self.assertEqual(len(reconstructed.state.death_history), 1)

    def test_failed_lifecycle_chain_rolls_back_deaths_attachments_and_random_state(self):
        self.spell("fail", lambda ctx: (
            Buff(ctx.target_id, 3, 2),
            Destroy(ctx.state.players[1].board[1]),
            ShuffleIntoDeck(ctx.target_id, ctx.player_id),
            Summon(ctx.player_id, "not-registered"),
        ), targeted=True)
        game = self.game(hand=("fail",), board=("plain", "reborn"), deck=("token", "shield"))
        target = game.state.players[1].board[0]
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, "fail", target)
        self.assertEqual(game.snapshot(), before)
        self.assertEqual(game.history, [])

    def test_expiry_observers_see_removed_auras_and_expired_triggers_cannot_react(self):
        self.registry.register_behavior("observe_expiry", lambda ctx: (GainArmor(ctx.player_id, ctx.source.attack),))
        self.registry.register_card(CardDefinition("expiry_observer", "Expiry observer", CardType.MINION,
                                                   attack=2, health=4,
                                                   triggers=(TriggerSpec("attachments_expired", "observe_expiry"),)))
        self.spell("grant", lambda ctx: (
            GrantAura(ctx.state.players[1].board[0], 4, expires_turn=ctx.state.turn),
            GrantTrigger(ctx.state.players[1].board[2], "attachments_expired", "armor3",
                         expires_turn=ctx.state.turn),
        ))
        game = self.game(hand=("grant",), board=("plain", "expiry_observer", "plain"),
                         deck=("plain",), opponent_deck=("plain",))
        self.play(game, "grant")
        observer = game.state.players[1].board[1]
        self.assertEqual(game.state.entities[observer].attack, 6)
        result = game.apply(EndTurn(1))
        self.assertEqual(sum(e.kind == "attachments_expired" for e in result.events), 2)
        self.assertEqual([e.amount for e in result.events if e.kind == "armor_gained"], [2, 2])
        self.assertEqual(self.armor(game), 4)

    def test_new_turn_control_transfer_does_not_inherit_previous_turn_attack_count(self):
        self.spell("take", lambda ctx: (ChangeControl(ctx.target_id, ctx.player_id),), targeted=True)
        game = self.game(board=("charge",), opponent_hand=("take",),
                         deck=("plain",), opponent_deck=("plain",))
        initial = game.state
        target = initial.players[1].board[0]
        game.apply(Attack(1, target, initial.players[2].hero_id))
        self.assertEqual(game.state.entities[target].attacks_this_turn, 1)
        game.apply(EndTurn(1))
        self.play(game, "take", target, player_id=2)
        self.assertEqual(game.state.entities[target].attacks_this_turn, 0)
        game.apply(Attack(2, target, initial.players[1].hero_id))
        self.assertEqual(game.state.entities[initial.players[1].hero_id].health, 28)

    def test_control_transfer_within_same_turn_preserves_spent_attacks(self):
        self.spell("transfer_twice", lambda ctx: (ChangeControl(ctx.target_id, 2), ChangeControl(ctx.target_id, 1)),
                   targeted=True)
        game = self.game(hand=("transfer_twice",), board=("charge",))
        initial = game.state
        target, defender = initial.players[1].board[0], initial.players[2].hero_id
        game.apply(Attack(1, target, defender))
        self.play(game, "transfer_twice", target)
        self.assertEqual(game.state.entities[target].controller, 1)
        self.assertEqual(game.state.entities[target].attacks_this_turn, 1)
        with self.assertRaises(IllegalAction):
            game.apply(Attack(1, target, defender))

    def test_rehashed_snapshot_rejects_expired_enchantment_or_ability_at_boundary(self):
        self.spell("grant", lambda ctx: (Buff(ctx.target_id, 2, expires_turn=ctx.state.turn + 2),
                                          GrantKeyword(ctx.target_id, Keyword.TAUNT,
                                                       expires_turn=ctx.state.turn + 2)), targeted=True)
        game = self.game(hand=("grant",), board=("plain",), opponent_deck=("plain",))
        target = game.state.players[1].board[0]
        self.play(game, "grant", target)
        game.apply(EndTurn(1))
        for field in ("enchantments", "abilities"):
            with self.subTest(field=field):
                snapshot = game.snapshot()
                snapshot["state"]["entities"][str(target)][field][0]["expires_turn"] = 1
                snapshot["state_hash"] = canonical_hash({key: snapshot[key] for key in (
                    "ruleset", "registry_fingerprint", "mechanics_version", "state", "rng_state", "resolution_frame", "match_setup", "generation_context", "information",
                )})
                with self.assertRaisesRegex(SnapshotError, "Expired attachment"):
                    Game.from_snapshot(snapshot, self.registry)

    def test_return_and_shuffle_observers_see_departed_aura_already_removed(self):
        self.registry.register_behavior("observe_departure", lambda ctx: (GainArmor(ctx.player_id, ctx.source.attack),))
        self.registry.register_card(CardDefinition("departure_observer", "Departure observer", CardType.MINION,
                                                   attack=2, health=4, triggers=(
                                                       TriggerSpec("card_returned", "observe_departure"),
                                                       TriggerSpec("card_shuffled", "observe_departure"),
                                                   )))
        self.spell("bounce", lambda ctx: (ReturnToHand(ctx.target_id),), targeted=True)
        self.spell("shuffle", lambda ctx: (ShuffleIntoDeck(ctx.target_id),), targeted=True)
        for spell in ("bounce", "shuffle"):
            with self.subTest(effect=spell):
                game = self.game(hand=(spell,), board=("aura", "departure_observer"))
                source, observer = game.state.players[1].board
                self.assertEqual(game.state.entities[observer].attack, 3)
                self.play(game, spell, source)
                self.assertEqual(game.state.entities[observer].attack, 2)
                self.assertEqual(self.armor(game), 2)

    def test_attack_cancels_when_control_transfer_makes_combatants_friendly(self):
        self.registry.register_behavior("take_attacker", lambda ctx: (
            ChangeControl(ctx.event.source_id, 2),
        ))
        self.registry.register_behavior("take_defender", lambda ctx: (
            ChangeControl(ctx.event.target_id, 1),
        ))
        for card_id, behavior in (("attacker_thief", "take_attacker"),
                                  ("defender_thief", "take_defender")):
            self.registry.register_card(CardDefinition(card_id, card_id, CardType.MINION,
                                                       health=5,
                                                       triggers=(TriggerSpec("attack_declared", behavior),)))
        for observer in ("attacker_thief", "defender_thief"):
            with self.subTest(transferred_by=observer):
                game = self.game(board=("charge",), opponent_board=("plain", observer))
                state = game.state
                attacker, defender = state.players[1].board[0], state.players[2].board[0]
                result = game.apply(Attack(1, attacker, defender))
                after = game.state
                self.assertEqual(after.entities[attacker].controller, after.entities[defender].controller)
                self.assertEqual(after.entities[attacker].attacks_this_turn, 1)
                self.assertEqual(after.entities[attacker].health, 4)
                self.assertEqual(after.entities[defender].health, 4)
                self.assertFalse(any(event.kind == "damage_dealt" for event in result.events))
                cancelled = [event for event in result.events if event.kind == "attack_cancelled"]
                self.assertEqual(len(cancelled), 1)
                self.assertEqual(dict(cancelled[0].data)["reason"], "combatants_became_friendly")


if __name__ == "__main__":
    unittest.main()
