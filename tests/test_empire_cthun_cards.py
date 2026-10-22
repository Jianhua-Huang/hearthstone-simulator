"""Real C'Thun activations and external producers through the shared interpreter."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.empire_cthun_cards import (GOD, DEACON, SPAWN, RUMBLER, RITUAL, LASH,
    LESSON, SKILLS, FANATIC, FAMILY, ROOTS, load_batch, register_empire_cthun_cards)
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec, UseMinionAbility)
from hs_sim.engine.ability_families import completed_ids
from hs_sim.engine.battlecry_sources import RepeatBattlecry
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, InvokeBehavior,
    RefreshMana, RequestChoice, ReturnToHand, Silence, GrantKeyword)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.health_loss import LoseHealth
from hs_sim.engine.model import DamageKind, SpellSchool
from hs_sim.engine.pools import GenerationContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.rituals import completed_rituals
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from tools.card_batch import canonical

P = 'fixture.empire_cthun.'
FILL, BIG, ELUSIVE, SHIELD, STEALTH, BOOST, WOUND, SHADOW, ARCANE, BOUNCE, CONTROL, COPY, QUIET, AUTO, MANA, WATCH, HISTORY = (
    P+x for x in ('fill', 'big', 'elusive', 'shield', 'stealth', 'boost', 'wound', 'shadow',
                  'arcane', 'bounce', 'control', 'copy', 'silence', 'auto', 'mana', 'watch', 'history'))


@lru_cache(maxsize=None)
def fixture(mode=None, role='writer'):
    assert role in ('writer', 'reader')
    r = build_registry(); register_empire_cthun_cards(r)
    for cid, attack, health, keywords in ((FILL, 2, 10, ()), (BIG, 0, 60, ()),
            (ELUSIVE, 0, 60, (Keyword.ELUSIVE,)), (SHIELD, 0, 60, (Keyword.DIVINE_SHIELD,)),
            (STEALTH, 0, 60, (Keyword.STEALTH,))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=attack, health=health, keywords=keywords))
    r.register_card(CardDefinition(BOOST, BOOST, CardType.MINION, health=8, spell_damage=12))
    bodies = {WOUND: lambda c: (LoseHealth(c.state.players[c.player_id].hero_id, 12, c.source_id),),
        SHADOW: lambda c: (), ARCANE: lambda c: (),
        MANA: lambda c: (RefreshMana(c.player_id, 10),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        CONTROL: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id, mode='current'),),
        QUIET: lambda c: (Silence(c.target_id),),
        AUTO: lambda c: (CastSpell(c.player_id, LESSON, c.source_id, choices='player'),)}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            requires_target=cid in (BOUNCE, CONTROL, COPY, QUIET),
            spell_school=SpellSchool.SHADOW if cid == SHADOW else SpellSchool.ARCANE if cid == ARCANE else None))
    def historical(c):
        original=next(r for r in c.state.battlecry_history if r.card_id==RUMBLER and r.completed)
        return (RepeatBattlecry(c.player_id,c.source_id,original.id,choices='player'),)
    r.register_behavior(HISTORY,historical)
    r.register_card(CardDefinition(HISTORY,HISTORY,CardType.MINION,health=10,battlecry=HISTORY))
    def fail(c): raise ResolutionError('Deliberate family reaction failure')
    r.register_behavior(P+'fail', fail)
    if mode:
        def watch(c):
            if not any(not row.completed for row in c.state.ability_trigger_history): return ()
            if mode == 'fail': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
            return (RequestChoice(3-c.player_id, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
                ChoiceOption('take','Take original source',(ChangeControl(c.state.ability_trigger_history[-1].request.source.entity_id,2),)),
                ChoiceOption('life','Grant Lifesteal',(GrantKeyword(c.state.ability_trigger_history[-1].request.source.entity_id,Keyword.LIFESTEAL,c.source_id),))), c.source_id),)
        r.register_behavior(WATCH, watch)
        r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20,
            triggers=(TriggerSpec('damage_dealt', WATCH),)))
    return r


class EmpireCthunTests(unittest.TestCase):
    def game(self, board=(), hand=(), enemy=(BIG,), deck=(), mode=None, other_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', board=board, hand=hand, deck=deck or (FILL,)*12, max_mana=10, mana=10),
            PlayerSetup('HERO_01', board=enemy, hand=other_hand, deck=(FILL,)*12, max_mana=10, mana=10)), seed=173,
            generation_context=GenerationContext('fixture.cthun','experimental',starting_decks=(deck,(FILL,)*12))
                if deck else None), fixture(mode))

    def play(self, g, cid, target=None, player=1):
        entity = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)
        return g.apply(PlayCard(player, entity, target))

    def use(self, g, skill, index=0, target=None, player=1):
        source = [i for i in g.state.players[player].board if g.state.entities[i].card_id == GOD][index]
        return g.apply(UseMinionAbility(player, source, SKILLS[skill], target))

    def choose(self, g, option):
        pending = g.state.pending_choice
        return g.apply(SelectChoice(pending.player_id, pending.id, (str(option),)))

    def next_turn(self, g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def enemy(self, g): return g.state.players[2].board[0]

    def restore(self, g, mode=None):
        other = Game.from_snapshot(json.loads(json.dumps(g.snapshot())), fixture(mode, 'reader'))
        self.assertEqual(other.state_hash(), g.state_hash())
        self.assertEqual(g.clone().state_hash(), g.state_hash())
        self.assertEqual(replay(build_replay(g), fixture(mode, 'reader')).state_hash(), g.state_hash())
        return other

    def fanatics(self, g):
        return [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == FANATIC]

    def test_complete_fixed_records_and_cn_conflicts_are_not_relabelled_verified(self):
        data = load_batch(); self.assertEqual(tuple(data['roots']), ROOTS)
        self.assertEqual(len(data['records']), 12); self.assertEqual(len(data['complete_primary_observations']), 24)
        self.assertFalse(data['all_primary_faces_verified']); self.assertFalse(data['cn_calibrated'])
        for row in data['records'].values(): self.assertEqual(canonical(row['record']), row['record_sha256'])
        profile = fixture().ability_family_profiles[FAMILY]
        self.assertEqual(profile.keywords, ((), (), (Keyword.LIFESTEAL,), ()))
        for cid in SKILLS: self.assertTrue(fixture().card(cid).choice_only)

    def test_real_ten_mana_play_and_free_ability_do_not_pay_descriptor_cost_or_cast(self):
        g = self.game(hand=(GOD,)); self.play(g, GOD); self.assertEqual(g.state.players[1].mana, 0)
        self.use(g, 3)
        self.assertEqual([(e.attack, e.max_health) for e in self.fanatics(g)], [(2, 3), (2, 3)])
        self.assertTrue(all(Keyword.TAUNT in e.keywords for e in self.fanatics(g)))
        self.assertEqual(len(g.state.cast_history), 0); self.restore(g)

    def test_wrath_uses_seven_shared_unit_packets_without_spell_damage(self):
        g = self.game(board=(GOD, BOOST)); self.use(g, 0)
        results = [r.health_result for r in g.state.damage_history if r.health_result.ability_trigger_id == 1]
        self.assertEqual(len(results), 7); self.assertEqual(sum(r.damage_dealt for r in results), 7)
        self.assertTrue(all(r.damage_kind == DamageKind.MINION_ABILITY.value and r.spell_bonus == 0 for r in results))
        self.assertTrue(g.state.ability_trigger_history[0].completed); self.restore(g)

    def test_domain_samples_two_distinct_other_friendly_minions(self):
        g = self.game(board=(GOD, FILL, FILL, FILL)); self.use(g, 1)
        units = [g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual((units[0].attack, units[0].max_health), (12, 12))
        self.assertEqual(sorted((e.attack, e.max_health) for e in units[1:]), [(2, 10), (4, 13), (4, 13)])
        self.restore(g)

    def test_gaze_has_local_lifesteal_and_never_grants_it_to_the_source(self):
        g = self.game(board=(GOD,), hand=(WOUND,)); self.play(g, WOUND)
        before = len(g.state.cast_history); self.use(g, 2, target=self.enemy(g))
        hero = g.state.entities[g.state.players[1].hero_id]
        self.assertEqual(hero.health, 23); self.assertEqual(g.state.entities[self.enemy(g)].health, 55)
        source = g.state.entities[g.state.players[1].board[0]]; self.assertNotIn(Keyword.LIFESTEAL, source.keywords)
        self.use(g, 0); self.assertEqual(g.state.entities[hero.id].health, 23)
        self.assertEqual(len(g.state.cast_history), before); self.restore(g)

    def test_gaze_shield_produces_no_restoration(self):
        g = self.game(board=(GOD,), hand=(WOUND,), enemy=(SHIELD,)); self.play(g, WOUND)
        self.use(g, 2, target=self.enemy(g))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 18)
        self.assertFalse(g.state.healing_history); self.restore(g)

    def test_gaze_is_a_minion_ability_and_can_target_elusive(self):
        g = self.game(board=(GOD,), enemy=(ELUSIVE,)); self.use(g, 2, target=self.enemy(g))
        self.assertEqual(g.state.entities[self.enemy(g)].health, 55); self.restore(g)

    def test_native_target_legality_and_action_failure_roll_back(self):
        g = self.game(board=(GOD,), enemy=(STEALTH,)); before = g.state_hash()
        with self.assertRaises(IllegalAction): self.use(g, 2, target=self.enemy(g))
        self.assertEqual(g.state_hash(), before); self.assertFalse(g.state.ability_trigger_history)

    def test_real_rumbler_paid_battlecry_does_not_consume_a_native_god_action(self):
        g = self.game(board=(GOD,), hand=(RUMBLER,)); self.play(g, RUMBLER)
        self.assertEqual(g.state.players[1].mana, 4); self.assertEqual(len(g.state.pending_choice.options), 4)
        self.choose(g, SKILLS[3]); self.assertEqual(len(self.fanatics(g)), 2)
        god = g.state.entities[g.state.players[1].board[0]]
        self.assertFalse(god.old_god_free_used); self.assertEqual(god.attacks_this_turn, 0)
        row = g.state.ability_trigger_history[0]
        self.assertFalse(row.request.native); self.assertEqual(row.request.source.card_id, RUMBLER)
        self.restore(g)

    def test_external_domain_excludes_the_actual_minion_producer(self):
        g = self.game(board=(FILL, FILL), hand=(RUMBLER,)); self.play(g, RUMBLER); self.choose(g, SKILLS[1])
        units = [g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual([(e.attack, e.max_health) for e in units], [(4, 13), (4, 13), (6, 7)])

    def test_spawn_reads_original_deck_even_after_cthun_was_drawn(self):
        g = self.game(hand=(SPAWN,), deck=(GOD, FILL, FILL))
        self.next_turn(g); self.play(g, SPAWN); self.choose(g, SKILLS[3])
        self.assertEqual(len(self.fanatics(g)), 2); self.restore(g)

    def test_spawn_does_not_treat_cthun_in_initial_hand_as_original_deck_membership(self):
        g = self.game(hand=(SPAWN, GOD)); self.play(g, SPAWN)
        self.assertIsNone(g.state.pending_choice); self.assertFalse(g.state.ability_trigger_history)

    def test_two_held_shadow_casts_unlock_the_deacon(self):
        g = self.game(hand=(DEACON, SHADOW, ARCANE, SHADOW))
        self.play(g, SHADOW); self.play(g, ARCANE); self.play(g, SHADOW); self.play(g, DEACON)
        self.choose(g, SKILLS[3]); self.assertEqual(len(self.fanatics(g)), 2); self.restore(g)

    def test_deacon_without_two_held_shadow_casts_has_no_skill_choice(self):
        g = self.game(hand=(DEACON, SHADOW, ARCANE)); self.play(g, SHADOW); self.play(g, ARCANE); self.play(g, DEACON)
        self.assertIsNone(g.state.pending_choice); self.assertFalse(g.state.ability_trigger_history)

    def test_ritual_counts_two_owner_starts_and_uses_the_original_spell_source(self):
        g = self.game(hand=(RITUAL,)); self.play(g, RITUAL)
        self.assertEqual(g.state.players[1].mana, 9); self.next_turn(g)
        self.assertIsNone(g.state.pending_choice); self.next_turn(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(completed_rituals(g.state,1)),1); self.restore(g)
        self.choose(g, SKILLS[3]); self.assertEqual(len(self.fanatics(g)), 2)
        row = g.state.ability_trigger_history[0]
        self.assertEqual(row.request.source.card_id, RITUAL); self.assertEqual(row.request.source.kind, CardType.SPELL)
        self.assertEqual(len(g.state.cast_history), 1); self.restore(g)

    def test_lesson_selects_two_distinct_skills_and_gaze_is_not_a_spell_cast(self):
        g = self.game(board=(BOOST,), hand=(WOUND, LESSON)); self.play(g, WOUND); self.play(g, LESSON)
        self.assertEqual(g.state.players[1].mana, 4); self.restore(g)
        self.choose(g, SKILLS[2]); self.restore(g); self.choose(g, self.enemy(g))
        self.assertNotIn(SKILLS[2], [o.id for o in g.state.pending_choice.options]); self.restore(g)
        self.choose(g, SKILLS[3]); self.assertEqual(len(self.fanatics(g)), 2)
        result = next(r.health_result for r in g.state.damage_history if r.health_result.ability_trigger_id)
        self.assertEqual((result.damage_dealt, result.spell_bonus, result.damage_kind), (5, 0, DamageKind.EFFECT.value))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 23)
        self.assertEqual(len(g.state.cast_history), 2); self.restore(g)

    def test_empty_external_gaze_completes_without_inventing_a_target(self):
        g = self.game(hand=(RUMBLER,), enemy=()); self.play(g, RUMBLER); self.choose(g, SKILLS[2])
        self.assertIsNone(g.state.pending_choice); self.assertTrue(g.state.ability_trigger_history[0].completed)
        self.assertFalse(g.state.damage_history); self.restore(g)

    def test_full_board_servants_keep_the_original_empty_delivery(self):
        g = self.game(board=(GOD,)+(FILL,)*6); self.use(g, 3)
        self.assertFalse(self.fanatics(g)); self.assertEqual(len(g.state.players[1].board), 7)
        self.assertTrue(g.state.ability_trigger_history[0].completed); self.restore(g)

    def test_four_completed_external_members_triple_only_native_cthun_skills(self):
        g = self.game(board=(GOD,), hand=(LESSON, LESSON))
        self.play(g, LESSON); self.choose(g, SKILLS[0]); self.choose(g, SKILLS[1]); self.next_turn(g)
        self.play(g, LESSON); self.choose(g, SKILLS[2]); self.choose(g, self.enemy(g)); self.choose(g, SKILLS[3])
        self.assertEqual(completed_ids(g.state, g.registry.ability_family_profiles[FAMILY], 1), SKILLS)
        self.use(g, 2, target=self.enemy(g)); self.assertEqual(g.state.ability_trigger_history[-1].multiplier, 3)
        result = g.state.damage_history[-1].health_result; self.assertEqual(result.damage_dealt, 15)
        self.restore(g)

    def test_fourth_native_skill_uses_its_prior_completed_set_and_new_cthun_is_triple(self):
        g = self.game(board=(GOD, GOD))
        self.use(g, 0); self.use(g, 1); self.next_turn(g)
        self.use(g, 2, target=self.enemy(g)); self.use(g, 3)
        self.assertEqual([r.multiplier for r in g.state.ability_trigger_history], [1, 1, 1, 1])
        self.use(g, 2, index=1, target=self.enemy(g)); self.assertEqual(g.state.ability_trigger_history[-1].multiplier, 3)
        self.restore(g)

    def test_weapon_real_attacks_reduce_cthun_and_last_durability_still_triggers(self):
        g = self.game(hand=(LASH, GOD)); self.play(g, LASH)
        hero = g.state.players[1].hero_id; enemy = g.state.players[2].hero_id
        g.apply(Attack(1, hero, enemy)); self.choose(g, SKILLS[1])
        entity = next(g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id == GOD)
        self.assertEqual(quote_unselected_cost(g.state, g.registry, entity).amount, 9)
        self.next_turn(g); g.apply(Attack(1, hero, enemy)); self.choose(g, SKILLS[1])
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(quote_unselected_cost(g.state, g.registry, g.state.entities[entity.id]).amount, 8)
        self.assertEqual([r.request.source.card_id for r in g.state.ability_trigger_history], [LASH, LASH]); self.restore(g)

    def test_automatic_lesson_reuses_real_choices_and_one_actual_spell_cast(self):
        g = self.game(hand=(AUTO,)); self.play(g, AUTO); self.choose(g, SKILLS[1]); self.choose(g, SKILLS[3])
        self.assertEqual(len(g.state.cast_history), 2)
        self.assertEqual([r.request.source.card_id for r in g.state.ability_trigger_history], [LESSON, LESSON])
        self.restore(g)

    def test_native_gaze_waiting_reaction_preserves_local_lifesteal_and_completion(self):
        g = self.game(board=(GOD, WATCH), hand=(WOUND,), mode='wait'); self.play(g, WOUND)
        self.use(g, 2, target=self.enemy(g)); self.assertFalse(g.state.ability_trigger_history[0].completed)
        restored = self.restore(g, 'wait')
        for branch in (g, restored): self.choose(branch, 'ok')
        self.assertEqual(g.state_hash(), restored.state_hash()); self.assertTrue(g.state.ability_trigger_history[0].completed)
        self.restore(g, 'wait')

    def test_each_wrath_packet_can_resume_without_repeating_rng_or_invocation(self):
        g = self.game(board=(GOD, WATCH), mode='wait'); self.use(g, 0); other = self.restore(g, 'wait')
        for branch in (g, other):
            count = 0
            while branch.state.pending_choice:
                self.choose(branch, 'ok'); count += 1; self.assertLessEqual(count, 7)
            self.assertEqual(count, 7); self.assertEqual(len(branch.state.ability_trigger_history), 1)
        self.assertEqual(g.state_hash(), other.state_hash()); self.restore(g, 'wait')

    def test_failed_native_body_rolls_back_free_action_history_and_rng(self):
        g = self.game(board=(GOD, WATCH), mode='fail'); before = g.state_hash()
        with self.assertRaises(ResolutionError): self.use(g, 0)
        self.assertEqual(g.state_hash(), before); self.assertFalse(g.state.ability_trigger_history)

    def test_failed_choice_rolls_back_only_that_selection(self):
        g = self.game(board=(WATCH,), hand=(RUMBLER,), mode='fail'); self.play(g, RUMBLER); before = g.state_hash()
        with self.assertRaises(ResolutionError): self.choose(g, SKILLS[0])
        self.assertEqual(g.state_hash(), before); self.assertIsNotNone(g.state.pending_choice)
        self.choose(g, SKILLS[3]); self.assertEqual(len(self.fanatics(g)), 2)

    def test_tampered_completed_set_multiplier_and_lost_history_are_rejected(self):
        g = self.game(board=(GOD,)); self.use(g, 3)
        for mode in ('multiplier', 'completed', 'prior', 'lost'):
            value = deepcopy(g.snapshot()); rows = value['state']['ability_trigger_history']
            if mode == 'multiplier': rows[0]['multiplier'] = 3
            elif mode == 'completed': rows[0]['completed'] = False
            elif mode == 'prior': rows[0]['prior_completed'] = list(SKILLS)
            else: rows.clear()
            self.rehash(value)
            with self.subTest(mode=mode), self.assertRaisesRegex(SnapshotError, 'skill|Skill'):
                Game.from_snapshot(value, fixture(role='reader'))

    def test_private_acceptance_proofs_and_hidden_hands_never_enter_player_views(self):
        g = self.game(board=(GOD,), other_hand=(LESSON,)); self.use(g, 3)
        for pid in (1, 2):
            visible = json.dumps(g.observe(pid), ensure_ascii=False)
            self.assertNotIn('ability_trigger_history', visible); self.assertNotIn('prior_completed', visible)
            self.assertNotIn('family_ability_accepted', visible); self.assertNotIn('source_keywords', visible)
        self.restore(g)

    def rehash(self, value):
        value['events_hash'] = canonical_hash(value['events'])
        value['state_hash'] = canonical_hash({k: v for k, v in value.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})

    def complete_external_set(self, g):
        self.play(g, LESSON); self.choose(g, SKILLS[0]); self.choose(g, SKILLS[1]); self.next_turn(g)
        self.play(g, LESSON); self.choose(g, SKILLS[2]); self.choose(g, self.enemy(g)); self.choose(g, SKILLS[3])

    def test_remaining_triple_bodies_scale_numbers_without_tripling_target_or_summon_counts(self):
        for skill in (0, 1, 3):
            with self.subTest(skill=skill):
                g = self.game(board=(GOD, FILL, FILL), hand=(LESSON, LESSON))
                self.complete_external_set(g)
                before = {i: (g.state.entities[i].attack, g.state.entities[i].max_health)
                          for i in g.state.players[1].board}
                old_damage = len(g.state.damage_history); self.use(g, skill)
                self.assertEqual(g.state.ability_trigger_history[-1].multiplier, 3)
                if skill == 0:
                    results = [r.health_result for r in g.state.damage_history[old_damage:]]
                    self.assertEqual(len(results), 21); self.assertEqual(sum(r.damage_dealt for r in results), 21)
                elif skill == 1:
                    deltas = [(g.state.entities[i].attack-a, g.state.entities[i].max_health-h)
                              for i, (a, h) in before.items()]
                    self.assertEqual(deltas.count((6, 9)), 2)
                    self.assertEqual(sum(a for a, h in deltas), 12)
                else:
                    new = [g.state.entities[i] for i in g.state.players[1].board if i not in before]
                    self.assertEqual([(e.card_id, e.attack, e.max_health) for e in new], [(FANATIC, 6, 9)]*2)
                self.restore(g)

    def test_weapon_gaze_keeps_weapon_credit_and_local_lifesteal(self):
        g = self.game(hand=(WOUND, LASH)); self.play(g, WOUND); self.play(g, LASH)
        hero = g.state.players[1].hero_id
        g.apply(Attack(1, hero, g.state.players[2].hero_id)); self.choose(g, SKILLS[2]); self.choose(g, self.enemy(g))
        row = g.state.ability_trigger_history[0]
        self.assertEqual(row.request.source.kind, CardType.WEAPON)
        result = next(r.health_result for r in g.state.damage_history if r.health_result.ability_trigger_id)
        self.assertEqual((result.source_card_id, result.damage_kind, result.damage_dealt), (LASH, DamageKind.EFFECT.value, 5))
        self.assertEqual(g.state.entities[hero].health, 23)
        self.assertNotIn(Keyword.LIFESTEAL, g.state.entities[g.state.players[1].weapon_id].keywords)
        self.restore(g)

    def test_control_change_during_wrath_keeps_the_original_actor_and_source_material(self):
        g = self.game(board=(GOD, WATCH), mode='wait'); self.use(g, 0)
        self.choose(g, 'take'); other = self.restore(g, 'wait')
        for branch in (g, other):
            while branch.state.pending_choice: self.choose(branch, 'ok')
            results = [r.health_result for r in branch.state.damage_history if r.health_result.ability_trigger_id]
            self.assertEqual(len(results), 7); self.assertTrue(all(r.source_controller == 1 for r in results))
        self.assertEqual(g.state_hash(), other.state_hash()); self.restore(g, 'wait')

    def test_completed_set_belongs_to_the_player_and_survives_source_control_changes(self):
        g = self.game(board=(GOD,), hand=(LESSON, LESSON, CONTROL))
        self.complete_external_set(g)
        source = g.state.players[1].board[0]; self.play(g, CONTROL, source); g.apply(EndTurn(1))
        target = next(i for i in g.state.players[1].board if g.state.entities[i].card_id == FANATIC)
        self.use(g, 2, target=target, player=2)
        row = g.state.ability_trigger_history[-1]
        self.assertEqual((row.request.player_id, row.multiplier, row.prior_completed), (2, 1, ()))
        self.assertEqual(completed_ids(g.state, g.registry.ability_family_profiles[FAMILY], 1), SKILLS)
        self.restore(g)

    def test_all_private_witnesses_cannot_be_erased_while_real_native_or_external_actions_remain(self):
        for native in (True, False):
            g = self.game(board=(GOD,) if native else (), hand=() if native else (RUMBLER,))
            if native: self.use(g, 1)
            else: self.play(g, RUMBLER); self.choose(g, SKILLS[1])
            value = deepcopy(g.snapshot()); value['state']['ability_trigger_history'].clear()
            for event in value['events']:
                if event['kind'] in ('family_ability_accepted', 'family_ability_completed', 'family_ability_selected'):
                    event['kind'] = 'fixture.removed_private_witness'; event['data'] = {}
            self.rehash(value)
            with self.subTest(native=native), self.assertRaisesRegex(SnapshotError, 'Native|native|Family|family'):
                Game.from_snapshot(value, fixture(role='reader'))

    def test_historical_rumbler_body_keeps_the_actual_foreign_minion_source(self):
        g=self.game(hand=(WOUND,RUMBLER,HISTORY));self.play(g,WOUND);self.play(g,RUMBLER)
        self.choose(g,SKILLS[1]);self.play(g,HISTORY);self.choose(g,SKILLS[2]);self.choose(g,self.enemy(g))
        row=g.state.ability_trigger_history[-1]
        self.assertEqual(row.request.source.card_id,HISTORY)
        original=next(r for r in g.state.battlecry_history if r.id==row.request.battlecry_id)
        self.assertEqual(original.payload.card_id,RUMBLER)
        result=next(r.health_result for r in g.state.damage_history if r.health_result.ability_trigger_id)
        self.assertEqual((result.source_card_id,result.damage_dealt),(HISTORY,5))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,23);self.restore(g)

    def test_wrath_keeps_normal_per_packet_physical_keyword_reading(self):
        g=self.game(board=(GOD,WATCH),hand=(WOUND,),mode='wait');self.play(g,WOUND);self.use(g,0)
        self.choose(g,'life');other=self.restore(g,'wait')
        for branch in (g,other):
            while branch.state.pending_choice:self.choose(branch,'ok')
            self.assertEqual(branch.state.entities[branch.state.players[1].hero_id].health,24)
            self.assertEqual(len(branch.state.healing_history),6)
        self.assertEqual(g.state_hash(),other.state_hash());self.restore(g,'wait')
