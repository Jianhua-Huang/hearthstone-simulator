"""Actual Godfrey entry, complete original batches and ordinary death/choice recovery."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_minion_death_waves as native
from hs_sim.engine import Game, PlayCard, PlayerSetup, ResolutionError, Scenario
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, Destroy, GrantKeyword,
    InvokeBehavior, RandomDamage, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.errors import ResolutionLimitExceeded
from hs_sim.engine.minion_damage_waves import ContinueBattlecryDamageIfDeaths, RepeatBattlecryMinionDamage
from hs_sim.engine.model import BattlecryRepeatSpec, CardDefinition, CardType, DamageKind, Keyword, TriggerSpec, Zone
from hs_sim.engine.registry import Registry, UnsupportedDefinitionError
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.local_pool_format import build_cn37_local_pool_format

GODFREY = native.GODFREY
P = 'k709.'
SMALL, BIG, EGG, REBORN, SHIELD, IMMUNE, SLEEP, BONUS, REPEAT, KILLER = (
    P+x for x in ('small', 'big', 'egg', 'reborn', 'shield', 'immune', 'sleep', 'bonus', 'repeat', 'killer'))
WATCH, FAIL, INVALID, UNKNOWN = (P+x for x in ('watch', 'fail', 'invalid', 'unknown'))
LOOP, DOOM = P+'loop', P+'doom'
HELPERS = (SMALL, BIG, EGG, REBORN, SHIELD, IMMUNE, SLEEP, BONUS, REPEAT, KILLER, WATCH, INVALID, UNKNOWN, LOOP, DOOM)
SMALL_ENTRY, LOOP_ENTRY = SummonEntryMaterial(SMALL), SummonEntryMaterial(LOOP)


@lru_cache(None)
def host(role='writer'):
    h = build_cn37_local_pool_format()
    r = h.registry
    meta = metadata(collectible=False)
    r.register_behavior(P+'spawn', lambda c: (SummonByCard(c.player_id, (SMALL_ENTRY,), SummonCause.capture(c)),))
    r.register_behavior(P+'loop', lambda c: (SummonByCard(c.player_id, (LOOP_ENTRY,), SummonCause.capture(c)),))
    r.register_behavior(P+'doom', lambda c: (Damage(c.state.players[3-c.player_id].hero_id, 1000, c.source_id),))
    def kill_source(c):
        source = next(b.source_id for b in reversed(c.state.battlecry_history)
            if b.payload.behavior_id == native.PREFIX+GODFREY and not b.completed)
        return (Destroy(source, c.source_id), SummonByCard(c.player_id, (SMALL_ENTRY,), SummonCause.capture(c)))
    r.register_behavior(P+'kill_source', kill_source)
    for cid, hp, extra in ((SMALL, 1, {}), (BIG, 20, {}), (EGG, 1, dict(deathrattle=P+'spawn')),
            (REBORN, 1, dict(keywords=(Keyword.REBORN,))), (SHIELD, 1, dict(keywords=(Keyword.DIVINE_SHIELD,))),
            (IMMUNE, 20, dict(keywords=(Keyword.IMMUNE,))), (SLEEP, 20, dict(dormant_turns=2)),
            (BONUS, 30, dict(spell_damage=7)), (REPEAT, 30, dict(battlecry_repeats=(BattlecryRepeatSpec(2),))),
            (KILLER, 1, dict(deathrattle=P+'kill_source')), (LOOP, 1, dict(deathrattle=P+'loop')),
            (DOOM, 1, dict(deathrattle=P+'doom'))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=hp, metadata=meta, **extra))
    r.register_behavior(FAIL, lambda c: (_ for _ in ()).throw(ResolutionError('K709 intentional wave failure')))
    def waiting(c):
        source = c.state.entities.get(c.event.source_id)
        target = c.state.entities.get(c.event.target_id)
        if source is None or source.card_id != GODFREY or target is None or target.card_id != BIG:
            return ()
        others = [i for i in c.state.players[3-c.player_id].board if i != target.id]
        options = (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fault', 'Fail after RNG', (RandomDamage((c.state.players[2].hero_id,), 1, c.source_id),
                InvokeBehavior(FAIL, c.source_id, c.player_id))),
            ChoiceOption('return', 'Return source', (ReturnToHand(source.id),)),
            ChoiceOption('silence', 'Silence source', (Silence(source.id),)),
            ChoiceOption('control', 'Control source', (ChangeControl(source.id, 3-source.controller),)),
            ChoiceOption('transform', 'Transform source', (Transform(source.id, SMALL),)),
            ChoiceOption('poison', 'Poison source', (GrantKeyword(source.id, Keyword.POISONOUS, c.source_id),)))
        if others:
            options += (ChoiceOption('destroy_other', 'Destroy another minion', (Destroy(others[0], c.source_id),)),
                ChoiceOption('damage_other', 'Damage another minion', (Damage(others[0], 100, c.source_id),)))
        return (RequestChoice(c.player_id, options, c.source_id),)
    r.register_behavior(P+'wait', waiting)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.WEAPON, durability=20, metadata=meta,
        triggers=(TriggerSpec('damage_dealt', P+'wait'),)))
    for cid, body in ((INVALID, lambda c: (RepeatBattlecryMinionDamage(99999, 2),)),
            (UNKNOWN, lambda c: (InvokeBehavior(native.PREFIX+GODFREY, c.source_id, c.player_id),))):
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=meta))
    r.validate()
    return h


@lru_cache(None)
def fixture(role='writer'):
    full = host(role).registry
    r = Registry('k709-minion-original-death-waves-v1')
    for bid, body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):
            r.register_behavior(bid, body)
    for cid in ('HERO_08', 'HERO_08bp', *HELPERS):
        r.register_card(full.card(cid))
    native.register_past_minion_death_waves(r)
    r.validate()
    return r


class PastMinionDeathWaveTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'small'
    registry_factory = staticmethod(lambda mode, role: host(role).registry if mode == 'host' else fixture(role))

    def game(self, hand=(GODFREY,), *, board=(), enemy=(), watch=False, real_host=False, budget=1000):
        self.mode = 'host' if real_host else 'small'
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board,
            deck=(BIG,)*10, mana=30, max_mana=30, mana_cap=30, weapon_card_id=WATCH if watch else None,
            hero_power_card_id='HERO_08bp'), PlayerSetup('HERO_08', board=enemy, deck=(BIG,)*10,
            mana=30, max_mana=30, mana_cap=30, hero_power_card_id='HERO_08bp')), seed=709,
            generation_context=host().context if real_host else None), self.registry_factory(self.mode, 'writer'),
            ruleset=Ruleset(max_resolution_steps=budget))

    def unit(self, g, cid, player=1):
        return self.entity(g, cid, player, 'board')

    def rows(self, g):
        return [row.health_result for row in g.state.damage_history if row.health_result.source_id ==
            next(b.source_id for b in g.state.battlecry_history if b.payload.behavior_id == native.PREFIX+GODFREY)]

    def batches(self, g):
        return tuple(dict.fromkeys(row.batch_id for row in self.rows(g) if not row.from_lifesteal))

    def finish(self, g):
        count = 0
        while g.state.pending_choice is not None:
            count += 1
            self.assertLess(count, 20)
            self.choose(g)

    def pending(self, g):
        return next(w for w in g._frame.continuation if type(w) is ContinueBattlecryDamageIfDeaths)

    def test_complete_original_face_full_reference_and_source_roles(self):
        d = native.load_batch()
        self.assertEqual(len(d['original_candidate_ids']), 732)
        self.assertEqual(len(d['official_observations']), 4)
        self.assertEqual((fixture().card(GODFREY).cost, fixture().card(GODFREY).attack,
            fixture().card(GODFREY).health), (7, 4, 4))
        self.assertEqual(d['remaining_frontier_ids'], ['BT_126'])

    def test_actual_paid_battlecry_one_simultaneous_batch_both_sides_excludes_source(self):
        g = self.game(board=(BIG,), enemy=(BIG,))
        original = [self.unit(g, BIG).id, self.unit(g, BIG, 2).id]
        eid = self.play(g, GODFREY)
        self.assertEqual(g.state.entities[eid].health, 4)
        self.assertEqual([g.state.entities[i].health for i in original], [18, 18])
        self.assertEqual([row.original_target_id for row in self.rows(g)], original)
        self.assertEqual(len(self.batches(g)), 1)
        self.assertEqual(g.state.players[1].mana, 23)
        self.assertEqual(len(g.state.battlecry_history), 1)
        self.assertEqual(g.state.cast_history, [])
        self.portable(g)

    def test_nonlethal_first_wave_does_not_repeat_to_kill(self):
        g = self.game(enemy=(BIG,))
        self.play(g, GODFREY)
        self.assertEqual(self.unit(g, BIG, 2).health, 18)
        self.assertEqual(len(self.batches(g)), 1)

    def test_actual_death_repeats_once_then_stops_on_fresh_nonlethal_board(self):
        g = self.game(enemy=(SMALL, BIG))
        self.play(g, GODFREY)
        self.assertEqual(self.unit(g, BIG, 2).health, 16)
        self.assertEqual(len(self.batches(g)), 2)
        self.assertEqual(len(g.state.death_history), 1)

    def test_multiple_same_wave_deaths_trigger_one_next_wave(self):
        g = self.game(enemy=(SMALL, SMALL, BIG))
        self.play(g, GODFREY)
        self.assertEqual(self.unit(g, BIG, 2).health, 16)
        self.assertEqual(len(self.batches(g)), 2)

    def test_deathrattle_spawn_is_available_to_next_wave_and_can_trigger_another(self):
        g = self.game(enemy=(EGG, BIG))
        self.play(g, GODFREY)
        self.assertEqual([d.card_id for d in g.state.death_history], [EGG, SMALL])
        self.assertEqual(self.unit(g, BIG, 2).health, 14)
        self.assertEqual(len(self.batches(g)), 3)
        self.portable(g)

    def test_reborn_new_entity_is_hit_only_by_next_wave(self):
        g = self.game(enemy=(REBORN, BIG))
        original = self.unit(g, REBORN, 2).id
        self.play(g, GODFREY)
        dead = [d for d in g.state.death_history if d.card_id == REBORN]
        self.assertEqual(len(dead), 2)
        self.assertEqual(dead[0].entity_id, original)
        self.assertNotEqual(dead[1].entity_id, original)
        self.assertEqual(self.unit(g, BIG, 2).health, 14)

    def test_shield_consumption_and_death_are_distinct_waves(self):
        g = self.game(enemy=(SHIELD, SMALL, BIG))
        shield = self.unit(g, SHIELD, 2).id
        self.play(g, GODFREY)
        hits = [r for r in self.rows(g) if r.original_target_id == shield]
        self.assertEqual([r.damage_dealt for r in hits], [0, 2])
        self.assertEqual(len(self.batches(g)), 3)

    def test_immune_and_dormant_are_not_invented_deaths(self):
        g = self.game(enemy=(IMMUNE, SLEEP, SMALL))
        asleep = self.unit(g, SLEEP, 2).id
        self.play(g, GODFREY)
        self.assertEqual(self.unit(g, IMMUNE, 2).health, 20)
        self.assertEqual(self.unit(g, SLEEP, 2).health, 20)
        self.assertNotIn(asleep, [r.original_target_id for r in self.rows(g)])
        self.assertEqual(len(self.batches(g)), 2)

    def test_minion_ability_damage_never_uses_spell_bonus(self):
        g = self.game(board=(BONUS,), enemy=(SMALL, BIG))
        self.play(g, GODFREY)
        self.assertTrue(all((r.damage_kind, r.base_amount, r.spell_bonus) ==
            (DamageKind.MINION_ABILITY.value, 2, 0) for r in self.rows(g)))
        self.assertEqual(self.unit(g, BIG, 2).health, 16)

    def test_empty_other_group_completes_without_health_or_rng(self):
        g = self.game()
        rng = g.snapshot()['rng_state']
        self.play(g, GODFREY)
        self.assertEqual(g.state.damage_history, [])
        self.assertEqual(g.snapshot()['rng_state'], rng)
        self.portable(g)

    def test_actual_battlecry_repeat_repeats_whole_body_without_repaying(self):
        g = self.game(board=(REPEAT,), enemy=(SMALL, BIG))
        self.play(g, GODFREY)
        self.assertEqual(len(g.state.battlecry_history), 2)
        self.assertTrue(all(b.completed for b in g.state.battlecry_history))
        self.assertEqual(len(self.batches(g)), 3)
        self.assertEqual(self.unit(g, BIG, 2).health, 14)
        self.assertEqual(g.state.players[1].mana, 23)
        self.portable(g)

    def test_source_dies_to_original_deathrattle_and_accepted_body_still_repeats(self):
        g = self.game(enemy=(KILLER, BIG))
        eid = self.play(g, GODFREY)
        self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD)
        self.assertEqual(self.unit(g, BIG, 2).health, 14)
        self.assertEqual(len(self.batches(g)), 3)
        self.portable(g)

    def test_midwave_wait_preserves_original_batch_after_new_choice_action(self):
        g = self.game(enemy=(SMALL, BIG), watch=True)
        self.play(g, GODFREY)
        self.assertIsNotNone(g.state.pending_choice)
        request = self.pending(g)
        request.validate_in_state(g.state, g.registry)
        self.portable(g)
        self.finish(g)
        self.assertEqual(self.unit(g, BIG, 2).health, 16)
        self.assertEqual(len(self.batches(g)), 2)
        self.portable(g)

    def test_failed_choice_rng_and_damage_are_atomically_rolled_back(self):
        g = self.game(enemy=(SMALL, BIG), watch=True)
        self.play(g, GODFREY)
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)
        self.finish(g)
        self.portable(g)

    def test_unrelated_destruction_during_nonlethal_wave_does_not_repeat(self):
        g = self.game(enemy=(BIG, BIG), watch=True)
        self.play(g, GODFREY)
        self.choose(g, 'destroy_other')
        self.finish(g)
        self.assertEqual(len(g.state.death_history), 1)
        self.assertEqual(len(self.batches(g)), 1)

    def test_unrelated_reaction_damage_death_does_not_repeat(self):
        g = self.game(enemy=(BIG, BIG), watch=True)
        self.play(g, GODFREY)
        self.choose(g, 'damage_other')
        self.finish(g)
        self.assertEqual(len(g.state.death_history), 1)
        self.assertEqual(len(self.batches(g)), 1)

    def test_returned_source_remains_excluded_and_accepted_wave_continues(self):
        g = self.game(enemy=(SMALL, BIG), watch=True)
        eid = self.play(g, GODFREY)
        self.choose(g, 'return')
        self.finish(g)
        self.assertEqual(g.state.entities[eid].zone, Zone.HAND)
        self.assertEqual(self.unit(g, BIG, 2).health, 16)
        self.portable(g)

    def test_silenced_source_does_not_cancel_already_accepted_body(self):
        g = self.game(enemy=(SMALL, BIG), watch=True)
        self.play(g, GODFREY)
        self.choose(g, 'silence')
        self.finish(g)
        self.assertEqual(self.unit(g, BIG, 2).health, 16)
        self.portable(g)

    def test_control_changed_source_keeps_original_exclusion_and_new_damage_attribution(self):
        g = self.game(enemy=(SMALL, BIG), watch=True)
        eid = self.play(g, GODFREY)
        self.choose(g, 'control')
        self.finish(g)
        self.assertEqual(g.state.entities[eid].controller, 2)
        rows = self.rows(g)
        self.assertEqual([r.source_controller for r in rows if r.target_card_id == BIG], [1, 2])
        self.assertEqual(self.unit(g, BIG, 2).health, 16)
        self.portable(g)

    def test_transformed_same_physical_source_still_excluded(self):
        g = self.game(enemy=(SMALL, BIG), watch=True)
        eid = self.play(g, GODFREY)
        self.choose(g, 'transform')
        self.finish(g)
        self.assertEqual((g.state.entities[eid].card_id, g.state.entities[eid].health), (SMALL, 1))
        self.assertEqual(self.unit(g, BIG, 2).health, 16)
        self.portable(g)

    def test_poison_death_uses_original_wave_and_public_keyword_executor(self):
        g = self.game(enemy=(SMALL, BIG), watch=True)
        self.play(g, GODFREY)
        self.choose(g, 'poison')
        self.finish(g)
        death = next(d for d in g.state.death_history if d.card_id == BIG)
        self.assertEqual(death.cause.kind, 'poison')
        self.assertEqual(len(self.batches(g)), 2)
        self.portable(g)

    def test_original_batch_receipt_rejects_clipped_and_borrowed_results(self):
        g = self.game(board=(BIG,), enemy=(SMALL, BIG), watch=True)
        self.play(g, GODFREY)
        work = self.pending(g)
        for forged in (replace(work, victims=work.victims[:-1]), replace(work, batch_id=work.batch_id+1),
                replace(work, first_damage_id=work.first_damage_id+1),
                replace(work, request=replace(work.request, amount=3)),
                replace(work, source=replace(work.source, controller=2))):
            with self.subTest(forged=forged), self.assertRaises(ValueError):
                forged.validate_in_state(g.state, g.registry)
        self.portable(g)
        self.finish(g)
        with self.assertRaises(ValueError):
            work.validate_in_state(g.state, g.registry)

    def test_strict_finite_declarations_reject_boolean_zero_and_unknown_battlecry(self):
        for args in ((True, 2), (1, 0), (1, True), (0, 2)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                RepeatBattlecryMinionDamage(*args)
        g = self.game((INVALID,))
        before = g.snapshot()
        with self.assertRaises((ValueError, ResolutionError)):
            self.play(g, INVALID)
        self.assertEqual(g.snapshot(), before)

    def test_restored_pending_snapshot_rejects_substituted_original_wave(self):
        g = self.game(enemy=(SMALL, BIG), watch=True)
        self.play(g, GODFREY)
        def effects(value):
            if isinstance(value, dict):
                if value.get('type', '').endswith('.ContinueBattlecryDamageIfDeaths'):
                    yield value['fields']
                for child in value.values():
                    yield from effects(child)
            elif isinstance(value, list):
                for child in value:
                    yield from effects(child)
        for field in ('batch_id', 'first_damage_id', 'last_damage_id'):
            saved = deepcopy(g.snapshot())
            nodes = list(effects(saved['resolution_frame']))
            self.assertGreaterEqual(len(nodes), 1)
            for node in nodes:
                node[field] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                Game.from_snapshot(saved, self.registry_factory(self.mode, 'independent-reader'))

    def test_infinite_real_deathrattle_loop_exhausts_normal_budget_and_rolls_back(self):
        g = self.game(enemy=(LOOP,), budget=160)
        before = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            self.play(g, GODFREY)
        self.assertEqual(g.snapshot(), before)

    def test_hero_terminal_death_stops_accepted_waves(self):
        g = self.game(enemy=(DOOM, BIG))
        self.play(g, GODFREY)
        self.assertNotEqual(g.state.status, 'playing')
        self.assertEqual(g.state.winner, 2)
        self.assertEqual(len(self.batches(g)), 1)
        self.portable(g)

    def test_unbound_direct_behavior_is_explicit_unsupported_not_fake_cast(self):
        g = self.game((UNKNOWN,))
        before = g.snapshot()
        with self.assertRaises((UnsupportedDefinitionError, ResolutionError)):
            self.play(g, UNKNOWN)
        self.assertEqual(g.snapshot(), before)

    def test_actual_standard_host_entry_and_unfinished_source_inventory_preserved(self):
        g = self.game(enemy=(EGG, BIG), real_host=True)
        self.play(g, GODFREY)
        self.assertEqual(self.unit(g, BIG, 2).health, 14)
        self.assertFalse('MIS_701' in g.registry.cards)
        self.assertEqual(len(native.load_batch()['original_candidate_ids']), 732)
        self.portable(g)


if __name__ == '__main__':
    unittest.main()
