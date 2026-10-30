"""Actual Teron destruction, immutable native groups and ordinary relative-stat resurrection."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json, unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_destroyed_group_memory as native
from hs_sim.engine import Game, PlayerSetup, ResolutionError, Scenario
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.destroyed_group_memory import (DestroyForDeathrattleGroup, ResummonDestroyedGroups,
    RESUMMON_GRANT, validate_group)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage, Destroy, GainArmor,
    InvokeBehavior, RandomDamage, RequestChoice, ReturnToHand, Silence, Transform, TriggerDeathrattles)
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import (AuraSpec, BattlecryRepeatSpec, CardDefinition, CardType, DeathrattleMemory,
    DeathrattleRepeatSpec, Keyword, NativeDeathrattleSpec, RewindSpec, SummonQuantitySpec, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.registry import Registry, UnsupportedDefinitionError
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import deathrattle_memory_from_dict
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.local_pool_format import build_cn37_local_pool_format

TERON = native.TERON; P = 'k710.'
A, B, EGG, TOKEN, REBORN, SLEEP, SHIELD, IMMUNE, KILLER, AURA, BC_REPEAT, DR_REPEAT, QUANTITY = (
    P+x for x in ('a', 'b', 'egg', 'token', 'reborn', 'sleep', 'shield', 'immune', 'killer', 'aura', 'bc_repeat', 'dr_repeat', 'quantity'))
KILL, BOOST, WOUND, HUSH, RETURN, CONTROL, FORM, COPY, BASE, EARLY, BC, RETRY, ADD_DR, ADD_Q, FILL, INVALID = (
    P+x for x in ('kill', 'boost', 'wound', 'hush', 'return', 'control', 'form', 'copy', 'base', 'early', 'bc', 'retry', 'add_dr', 'add_q', 'fill', 'invalid'))
WATCH_DEATH, WATCH_ENTRY, FAIL = P+'watch_death', P+'watch_entry', P+'fail'
UNITS = (A, B, EGG, TOKEN, REBORN, SLEEP, SHIELD, IMMUNE, KILLER, AURA, BC_REPEAT, DR_REPEAT, QUANTITY)
SPELLS = (KILL, BOOST, WOUND, HUSH, RETURN, CONTROL, FORM, COPY, BASE, EARLY, BC, RETRY, ADD_DR, ADD_Q, FILL, INVALID)
HELPERS = (*UNITS, *SPELLS, WATCH_DEATH, WATCH_ENTRY)
ENTRIES = {cid: SummonEntryMaterial(cid) for cid in (TOKEN, DR_REPEAT, QUANTITY, B)}


@lru_cache(None)
def host(role='writer'):
    h = build_cn37_local_pool_format(); r = h.registry; meta = metadata(collectible=False)
    def summon(c, cid):
        return (SummonByCard(c.player_id, (ENTRIES[cid],), SummonCause.capture(c)),)
    r.register_behavior(P+'armor', lambda c: (GainArmor(c.player_id, 3),))
    r.register_behavior(P+'spawn', lambda c: summon(c, TOKEN))
    def kill_carrier(c):
        candidates = [eid for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id == TERON]
        return (Destroy(candidates[0], c.source_id),) if candidates else ()
    r.register_behavior(P+'kill_carrier', kill_carrier)
    for cid, attack, hp, extra in ((A, 2, 3, dict(battlecry=P+'armor')), (B, 1, 1, {}),
            (TOKEN, 1, 1, {}), (EGG, 0, 1, dict(deathrattle=P+'spawn')),
            (REBORN, 2, 3, dict(keywords=(Keyword.REBORN,))), (SLEEP, 2, 3, dict(dormant_turns=2)),
            (SHIELD, 1, 2, dict(keywords=(Keyword.DIVINE_SHIELD,))), (IMMUNE, 1, 2, dict(keywords=(Keyword.IMMUNE,))),
            (KILLER, 0, 1, dict(deathrattle=P+'kill_carrier')), (AURA, 0, 1, dict(auras=(AuraSpec(health=2),))),
            (BC_REPEAT, 0, 3, dict(battlecry_repeats=(BattlecryRepeatSpec(2),))),
            (DR_REPEAT, 0, 3, dict(deathrattle_repeats=(DeathrattleRepeatSpec(2),))),
            (QUANTITY, 0, 3, dict(summon_quantities=(SummonQuantitySpec(),)))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=attack, health=hp, metadata=meta, **extra))
    r.register_behavior(FAIL, lambda c: (_ for _ in ()).throw(ResolutionError('K710 intentional original-group failure')))
    def waiting(c):
        entity = c.state.entities.get(c.event.target_id)
        if entity is None: return ()
        if c.event.kind == 'minion_died':
            if entity.card_id != A: return ()
            carriers = [e for e in c.state.entities.values() if e.card_id == TERON and e.zone == Zone.BOARD]
            if carriers and not any(a.deathrattle_memory is not None and a.deathrattle_memory.destroyed_groups
                    for a in active_abilities(carriers[0], 'deathrattle')):
                raise ResolutionError('Original death was published before complete Teron native group memory')
        else:
            row = next((x for x in c.state.resurrection_history if x.entity_id == entity.id), None)
            if row is None: return ()
            printed = r.card(entity.card_id)
            if (entity.attack, entity.max_health) != (printed.attack+1, printed.health+1):
                raise ResolutionError('Original resurrection was notified before its relative +1/+1 grant')
        options = (ChoiceOption('continue', 'Continue'), ChoiceOption('fault', 'Fail after RNG',
            (RandomDamage((c.state.players[2].hero_id,), 1, c.source_id), InvokeBehavior(FAIL, c.source_id, c.player_id))))
        if c.event.kind == 'minion_summoned':
            carrier = c.state.entities.get(row.source_id)
            if carrier is not None and carrier.zone == Zone.BOARD:
                options += (ChoiceOption('control', 'Control original carrier', (ChangeControl(carrier.id, 3-carrier.controller),)),)
        return (RequestChoice(c.player_id, options, c.source_id),)
    r.register_behavior(P+'wait', waiting)
    for cid, event in ((WATCH_DEATH, 'minion_died'), (WATCH_ENTRY, 'minion_summoned')):
        r.register_card(CardDefinition(cid, cid, CardType.WEAPON, durability=20, metadata=meta,
            triggers=(TriggerSpec(event, P+'wait'),)))
    def trigger_battlecry(c):
        return (TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]), c.source_id),)
    bodies = {KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        BOOST: lambda c: (Buff(c.target_id, 5, 5, c.source_id), Damage(c.target_id, 1, c.source_id)),
        WOUND: lambda c: (Damage(c.target_id, 5, c.source_id),), HUSH: lambda c: (Silence(c.target_id),),
        RETURN: lambda c: (ReturnToHand(c.target_id),), CONTROL: lambda c: (ChangeControl(c.target_id, 2),),
        FORM: lambda c: (Transform(c.target_id, B),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id),),
        BASE: lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        EARLY: lambda c: (TriggerDeathrattles(c.target_id, c.source_id),), BC: trigger_battlecry, RETRY: trigger_battlecry,
        ADD_DR: lambda c: summon(c, DR_REPEAT), ADD_Q: lambda c: summon(c, QUANTITY),
        FILL: lambda c: tuple(SummonByCard(c.player_id, (ENTRIES[B],), SummonCause.capture(c)) for _ in range(6)),
        INVALID: lambda c: (ResummonDestroyedGroups(99999),)}
    targeted = {KILL, BOOST, WOUND, HUSH, RETURN, CONTROL, FORM, COPY, BASE, EARLY, BC, RETRY}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=meta,
            targeting=TargetSpec(kinds=(CardType.MINION,)) if cid in targeted else None,
            keywords=(Keyword.REWIND,) if cid == RETRY else (), rewind=RewindSpec(1) if cid == RETRY else None))
    r.validate(); return h


@lru_cache(None)
def fixture(role='writer'):
    full = host(role).registry; r = Registry('k710-original-destroyed-group-memory-v1')
    for bid, body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX): r.register_behavior(bid, body)
    for cid in ('HERO_08', 'HERO_08bp', *HELPERS): r.register_card(full.card(cid))
    native.register_past_destroyed_group_memory(r); r.validate(); return r


class PastDestroyedGroupMemoryTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'small'
    registry_factory = staticmethod(lambda mode, role: host(role).registry if mode == 'host' else fixture(role))

    def game(self, hand=(TERON, KILL), *, board=(), enemy=(), watch=None, real_host=False):
        self.mode = 'host' if real_host else 'small'
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board, deck=(B,)*8,
            mana=30, max_mana=30, mana_cap=30, weapon_card_id=watch, hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', board=enemy, deck=(B,)*8, mana=30, max_mana=30, mana_cap=30,
            hero_power_card_id='HERO_08bp')), seed=710, generation_context=host().context if real_host else None),
            self.registry_factory(self.mode, 'writer'))

    def unit(self, g, cid, player=1): return self.entity(g, cid, player, 'board')
    def copies(self, g, cid, player=1):
        return [g.state.entities[eid] for eid in g.state.players[player].board if g.state.entities[eid].card_id == cid]
    def memory(self, g, eid):
        return next(a.deathrattle_memory for a in active_abilities(g.state.entities[eid], 'deathrattle')
            if a.deathrattle_memory is not None and a.deathrattle_memory.spec == native.SPEC)
    def kill(self, g, eid): self.play(g, KILL, eid)
    def finish(self, g):
        count = 0
        while g.state.pending_choice is not None:
            count += 1; self.assertLess(count, 40); self.choose(g)

    def test_complete_raw_face_two_enchantment_roles_and_full_past_reference(self):
        d = native.load_batch(); card = fixture().card(TERON)
        self.assertEqual((card.cost, card.attack, card.health), (3, 3, 4))
        self.assertEqual(len(d['original_candidate_ids']), 732)
        self.assertEqual(len(d['official_observations']), 4)
        self.assertEqual([x['record']['type'] for x in d['evidence_only'][:2]], ['ENCHANTMENT', 'ENCHANTMENT'])
        self.assertFalse(any(cid in fixture().cards for cid in native.EVIDENCE))

    def test_actual_paid_battlecry_stores_complete_ordered_original_friendly_group(self):
        g = self.game(board=(A, B), enemy=(A,)); victims = list(g.state.players[1].board)
        eid = self.play(g, TERON); memory = self.memory(g, eid); group, = memory.destroyed_groups
        self.assertEqual([x.entity_id for x in group.victims], victims)
        self.assertEqual([d.entity_id for d in g.state.death_history], victims)
        self.assertEqual(len(self.copies(g, A, 2)), 1)
        self.assertEqual(g.state.players[1].mana, 27)
        self.assertEqual(len(g.state.battlecry_history), 1)
        validate_group(g.state, g.registry, group); self.portable(g)

    def test_resummon_base_body_plus_one_without_old_buffs_damage_or_battlecry(self):
        g = self.game((TERON, BOOST, KILL), board=(A,)); victim = self.unit(g, A).id
        self.play(g, BOOST, victim); eid = self.play(g, TERON); self.kill(g, eid)
        unit = self.unit(g, A)
        self.assertEqual((unit.attack, unit.max_health, unit.damage), (3, 4, 0))
        self.assertEqual(unit.origin_entity_id, victim)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)
        self.assertEqual(g.state.resurrection_history[-1].death_id, next(d.id for d in g.state.death_history if d.entity_id == victim))
        self.portable(g)

    def test_original_group_does_not_absorb_victim_deathrattle_spawn(self):
        g = self.game(board=(EGG, A)); eid = self.play(g, TERON)
        self.assertEqual(len(self.copies(g, TOKEN)), 1)
        self.kill(g, eid)
        self.assertEqual(len(self.copies(g, TOKEN)), 1)
        self.assertEqual(len(self.copies(g, EGG)), 1)
        self.assertEqual([r.death_id for r in g.state.resurrection_history], [1, 2])

    def test_reborn_created_body_is_not_an_extra_original_group_member(self):
        g = self.game(board=(REBORN,)); original = self.unit(g, REBORN).id
        eid = self.play(g, TERON); reborn = self.unit(g, REBORN)
        self.assertNotEqual(reborn.id, original); self.assertEqual(reborn.health, 1)
        self.kill(g, eid); bodies = self.copies(g, REBORN)
        self.assertEqual(len(bodies), 2)
        restored = next(x for x in bodies if x.id != reborn.id)
        self.assertEqual((restored.attack, restored.max_health), (3, 4))
        self.assertIn(Keyword.REBORN, restored.keywords)

    def test_dormant_minion_is_not_destroyed_or_remembered(self):
        g = self.game(board=(SLEEP, A)); asleep = self.unit(g, SLEEP).id
        eid = self.play(g, TERON)
        self.assertEqual([v.card_id for v in self.memory(g, eid).destroyed_groups[0].victims], [A])
        self.kill(g, eid); self.assertEqual(g.state.entities[asleep].zone, Zone.BOARD)
        self.assertEqual(len(g.state.resurrection_history), 1)

    def test_area_destruction_reuses_shield_and_immunity_rules(self):
        g = self.game(board=(SHIELD, IMMUNE)); eid = self.play(g, TERON)
        self.assertEqual([d.card_id for d in g.state.death_history], [SHIELD, IMMUNE])
        self.kill(g, eid)
        self.assertEqual(len(g.state.resurrection_history), 2)
        self.assertIn(Keyword.DIVINE_SHIELD, self.unit(g, SHIELD).keywords)

    def test_victim_deathrattle_kills_carrier_after_memory_was_installed(self):
        g = self.game(board=(KILLER, A)); eid = self.play(g, TERON)
        self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD)
        self.assertEqual([g.state.entities[r.entity_id].card_id for r in g.state.resurrection_history], [KILLER, A])
        self.portable(g)

    def test_aura_loss_uses_original_health_removal_policy_and_keeps_group(self):
        g = self.game((WOUND, BC, KILL), board=(TERON, AURA, A)); eid = self.unit(g, TERON).id
        self.play(g, WOUND, eid); self.assertEqual(g.state.entities[eid].health, 1)
        self.play(g, BC, eid)
        self.assertEqual((g.state.entities[eid].zone, g.state.entities[eid].health), (Zone.BOARD, 1))
        self.assertEqual([v.card_id for v in self.memory(g, eid).destroyed_groups[0].victims], [AURA, A])
        self.kill(g, eid)
        self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD)
        self.assertEqual([g.state.entities[r.entity_id].card_id for r in g.state.resurrection_history], [AURA, A])
        self.portable(g)

    def test_known_empty_memory_and_empty_actual_group_are_not_unknown_effects(self):
        g = self.game(); rng = g.snapshot()['rng_state']; eid = self.play(g, TERON)
        self.assertEqual(len(self.memory(g, eid).destroyed_groups), 1)
        self.assertEqual(self.memory(g, eid).destroyed_groups[0].victims, ())
        self.kill(g, eid); self.assertEqual(g.state.resurrection_history, [])
        self.assertEqual(g.snapshot()['rng_state'], rng)

    def test_current_copy_preserves_group_with_independent_attachment_and_both_can_resummon(self):
        g = self.game((TERON, COPY, KILL, KILL), board=(A,)); eid = self.play(g, TERON)
        original = self.memory(g, eid); self.play(g, COPY, eid)
        copied = next(x for x in self.copies(g, TERON) if x.id != eid)
        self.assertEqual(self.memory(g, copied.id), original)
        self.assertNotEqual(active_abilities(copied, 'deathrattle')[0].id, active_abilities(g.state.entities[eid], 'deathrattle')[0].id)
        self.kill(g, copied.id); self.kill(g, eid)
        self.assertEqual(len(self.copies(g, A)), 2); self.portable(g)

    def test_base_copy_has_known_empty_native_group_memory(self):
        g = self.game((TERON, BASE, KILL), board=(A,)); eid = self.play(g, TERON)
        self.play(g, BASE, eid); copied = next(x for x in self.copies(g, TERON) if x.id != eid)
        self.assertEqual(self.memory(g, copied.id).destroyed_groups, ())
        self.kill(g, copied.id); self.assertEqual(self.copies(g, A), [])

    def test_return_reset_and_real_replay_remember_only_the_new_group(self):
        g = self.game((TERON, RETURN, B, KILL), board=(A,)); eid = self.play(g, TERON)
        self.play(g, RETURN, eid); self.play(g, B); self.play(g, TERON)
        self.assertEqual([v.card_id for group in self.memory(g, eid).destroyed_groups for v in group.victims], [B])
        self.kill(g, eid); self.assertEqual(self.copies(g, A), []); self.assertEqual(len(self.copies(g, B)), 1)

    def test_silence_removes_original_memory_deathrattle(self):
        g = self.game((TERON, HUSH, KILL), board=(A,)); eid = self.play(g, TERON)
        self.play(g, HUSH, eid); self.kill(g, eid)
        self.assertEqual(g.state.resurrection_history, [])

    def test_transform_retires_original_native_memory(self):
        g = self.game((TERON, FORM, KILL), board=(A,)); eid = self.play(g, TERON)
        self.play(g, FORM, eid); self.kill(g, eid)
        self.assertEqual(g.state.resurrection_history, [])

    def test_changed_controller_receives_original_group_not_current_friendly_death_history(self):
        g = self.game((TERON, CONTROL, KILL), board=(A,), enemy=(B,)); eid = self.play(g, TERON)
        self.play(g, CONTROL, eid); self.kill(g, eid)
        self.assertEqual(self.copies(g, A), []); self.assertEqual(len(self.copies(g, A, 2)), 1)
        self.assertEqual((self.unit(g, A, 2).attack, self.unit(g, A, 2).max_health), (3, 4))
        self.portable(g)

    def test_early_trigger_and_natural_death_use_same_original_unconsumed_group(self):
        g = self.game((TERON, EARLY, KILL), board=(A,)); eid = self.play(g, TERON)
        self.play(g, EARLY, eid); self.assertEqual(g.state.entities[eid].zone, Zone.BOARD)
        self.kill(g, eid); self.assertEqual(len(self.copies(g, A)), 2)
        self.assertEqual(len({r.death_id for r in g.state.resurrection_history}), 1)

    def test_actual_battlecry_repeat_appends_new_group_after_first_deathrattle_spawn(self):
        g = self.game(board=(BC_REPEAT, EGG)); eid = self.play(g, TERON)
        groups = self.memory(g, eid).destroyed_groups
        self.assertEqual([[v.card_id for v in group.victims] for group in groups], [[BC_REPEAT, EGG], [TOKEN]])
        self.assertEqual(len(g.state.battlecry_history), 2)
        self.assertEqual(g.state.players[1].mana, 27)
        self.kill(g, eid); self.assertEqual(len(g.state.resurrection_history), 3); self.portable(g)

    def test_actual_deathrattle_repeat_uses_frozen_original_group_twice(self):
        g = self.game((TERON, ADD_DR, KILL), board=(A,)); eid = self.play(g, TERON)
        self.play(g, ADD_DR); self.kill(g, eid)
        self.assertEqual(len(self.copies(g, A)), 2)
        self.assertEqual(len(g.state.deathrattle_history), 2)

    def test_summon_quantity_extra_bodies_all_receive_grant_before_notification(self):
        g = self.game((TERON, ADD_Q, KILL), board=(A,), watch=WATCH_ENTRY); eid = self.play(g, TERON)
        self.play(g, ADD_Q); self.kill(g, eid); self.finish(g)
        self.assertEqual([(e.attack, e.max_health) for e in self.copies(g, A)], [(3, 4), (3, 4)])
        ids = [e.enchantments[-1].id for e in self.copies(g, A)]; self.assertEqual(len(set(ids)), 2)
        self.portable(g)

    def test_capacity_failure_keeps_ordered_original_selection_without_replacing_members(self):
        g = self.game((TERON, FILL, KILL), board=(A, B)); eid = self.play(g, TERON)
        self.play(g, FILL); self.assertEqual(len(g.state.players[1].board), 7)
        self.kill(g, eid); self.assertEqual(len(g.state.resurrection_history), 1)
        self.assertEqual(g.state.entities[g.state.resurrection_history[0].entity_id].card_id, A)
        self.assertTrue(any(e.kind == 'resurrection_failed' for e in g.events))

    def test_original_victim_death_wait_already_has_complete_memory(self):
        g = self.game(board=(A, B), watch=WATCH_DEATH); eid = self.play(g, TERON)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(self.memory(g, eid).destroyed_groups[0].victims), 2)
        self.portable(g); self.finish(g); self.kill(g, eid); self.finish(g)
        self.assertEqual(len(g.state.resurrection_history), 2)

    def test_resurrection_wait_restore_clone_replay_and_remaining_original_entries(self):
        g = self.game(board=(A, B), watch=WATCH_ENTRY); eid = self.play(g, TERON); self.kill(g, eid)
        self.assertIsNotNone(g.state.pending_choice); self.portable(g); self.finish(g)
        self.assertEqual([g.state.entities[r.entity_id].card_id for r in g.state.resurrection_history], [A, B])
        self.portable(g)

    def test_failed_choice_preserves_original_group_health_rng_and_paid_prefix(self):
        g = self.game(board=(A, B), watch=WATCH_ENTRY); eid = self.play(g, TERON); self.kill(g, eid)
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before); self.finish(g)

    def test_control_change_during_early_resummon_does_not_retarget_accepted_recipient(self):
        g = self.game((TERON, EARLY), board=(A, B), watch=WATCH_ENTRY); eid = self.play(g, TERON)
        self.play(g, EARLY, eid); self.choose(g, 'control'); self.portable(g); self.finish(g)
        self.assertEqual(g.state.entities[eid].controller, 2)
        self.assertEqual([r.player_id for r in g.state.resurrection_history], [1, 1])
        self.assertEqual(len(self.copies(g, B)), 1)

    def test_native_group_roundtrip_rejects_wrong_source_unpaired_causes_and_other_payloads(self):
        g = self.game(board=(A, B)); eid = self.play(g, TERON); memory = self.memory(g, eid); group, = memory.destroyed_groups
        self.assertEqual(deathrattle_memory_from_dict(json.loads(json.dumps(asdict(memory)))), memory)
        for patch in (dict(victims=group.victims[:-1]), dict(causes=group.causes[:-1]),
                dict(source=replace(group.source, controller=2)), dict(first_death_id=0)):
            with self.subTest(patch=patch), self.assertRaises(ValueError): replace(group, **patch)
        for patch in (dict(growth_steps=1), dict(draws=(object(),)), dict(spec=NativeDeathrattleSpec('draw_link'))):
            with self.subTest(patch=patch), self.assertRaises(ValueError): replace(memory, **patch)
        for player in (1, 2):
            view = json.dumps(g.for_player(player).observe())
            for key in ('destroyed_groups', 'first_death_id', 'causes', 'battlecry'):
                if key != 'battlecry': self.assertNotIn('"'+key+'"', view)

    def test_queued_resurrection_grant_cannot_change_original_source_or_mix_other_recipes(self):
        g = self.game(board=(A, B), watch=WATCH_ENTRY); eid = self.play(g, TERON); self.kill(g, eid)
        work = next(x for x in g._frame.continuation if type(x) is ResurrectMinion)
        self.assertEqual(work.entry_grant, RESUMMON_GRANT)
        for patch in (dict(source_id=g.state.players[1].hero_id), dict(cause=None),
                dict(entry_grant=CreatedMinionGrant(attack=2, health=1)), dict(on_summon=FAIL)):
            with self.subTest(patch=patch), self.assertRaises(ValueError): replace(work, **patch)
        self.finish(g)

    def test_completed_or_unknown_actual_deathrattle_requests_are_rejected_atomically(self):
        g = self.game((TERON, KILL, INVALID), board=(A,)); eid = self.play(g, TERON); self.kill(g, eid)
        with self.assertRaises(ValueError): ResummonDestroyedGroups(g.state.deathrattle_history[0].capture.id).validate_in_state(g.state, g.registry)
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, INVALID)
        self.assertEqual(g.snapshot(), before)

    def test_true_retry_replaces_actual_group_and_retired_copy_material_remains_consistent(self):
        g = self.game((RETRY,), board=(TERON, A, B)); eid = self.unit(g, TERON).id
        self.play(g, RETRY, eid); self.assertIsNotNone(g.state.pending_choice); self.portable(g)
        first = self.memory(g, eid).destroyed_groups[0]
        self.choose(g, 'retry'); current = self.memory(g, eid).destroyed_groups
        self.assertEqual(len(current), 1)
        self.assertGreater(current[0].battlecry.action, first.battlecry.action)
        self.assertEqual([v.card_id for v in current[0].victims], [A, B]); self.portable(g)

    def test_actual_standard_host_entry_resurrection_and_private_group_projection(self):
        g = self.game(board=(A, B), real_host=True); eid = self.play(g, TERON); self.kill(g, eid)
        self.assertEqual([(self.unit(g, cid).attack, self.unit(g, cid).max_health) for cid in (A, B)], [(3, 4), (2, 2)])
        self.assertFalse('MIS_701' in g.registry.cards); self.portable(g)


if __name__ == '__main__': unittest.main()
