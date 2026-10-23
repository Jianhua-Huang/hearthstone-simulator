"""Actual personal skill programs, original activation budgets and health paths."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards.past_personal_hero_power_value_cards import (
    SPIRIT, FIRE_EATER, ARMOR_SPEC, DAMAGE_SPEC, load_batch)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    IllegalAction, PlayerSetup, Registry, Scenario, UseHeroPower, Zone)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, DamageBatch, Destroy,
    GainArmor, InvokeBehavior, RefreshHeroPower, ReplaceHero, ReplaceHeroPower, RequestChoice, Silence)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.hero_power_values import (ARMOR, NEXT_DAMAGE, GainHeroPowerArmor,
    HeroPowerValuePlan, HeroPowerValueProfile, armor_effect, validate_plan)
from hs_sim.engine.hero_powers import AddHeroPower, TriggerHeroPower
from hs_sim.engine.model import DamageKind, PlayerEffectSpec, TargetMode, TargetSpec, TriggerSpec
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION

P = 'k472.'
NOOP, KILL, SILENCE, TAKE, ARMOR_SPELL, DAMAGE_SPELL, REFRESH, REPLACE, HERO, EXTRA, AUTO, WATCH, FAIL, MULTI = (
    P+s for s in ('noop', 'kill', 'silence', 'take', 'armor', 'damage', 'refresh', 'replace', 'hero', 'extra', 'auto', 'watch', 'fail', 'multi'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry(); r._version = 'k472-'+mode
    def fail(c): raise ResolutionError('K472 deliberate late original value failure')
    scripts = {
        NOOP: lambda c: (), KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        SILENCE: lambda c: (Silence(c.target_id),), TAKE: lambda c: (ChangeControl(c.target_id, 2),),
        ARMOR_SPELL: lambda c: (GainArmor(c.player_id, 5),),
        DAMAGE_SPELL: lambda c: (Damage(c.state.players[2].hero_id, 1, c.source_id, DamageKind.SPELL),),
        REFRESH: lambda c: (RefreshHeroPower(c.player_id),),
        REPLACE: lambda c: (ReplaceHeroPower(c.player_id, 'HERO_01bp', source_id=c.source_id),),
        HERO: lambda c: (ReplaceHero(c.player_id, 'HERO_01', hero_power_card_id='HERO_01bp'),),
        EXTRA: lambda c: (AddHeroPower(c.player_id, 'HERO_08bp', c.source_id),),
        AUTO: lambda c: (TriggerHeroPower(c.player_id, c.source_id, targeting='explicit', target_id=c.state.players[2].hero_id),),
        FAIL: fail,
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,))
                if cid in (KILL, SILENCE, TAKE) else None))
    r.register_behavior(MULTI, lambda c: (DamageBatch((
        Damage(c.state.players[1].hero_id, 1, c.source_id, DamageKind.HERO_POWER),
        Damage(c.state.players[2].hero_id, 2, c.source_id, DamageKind.HERO_POWER))),))
    r.register_card(CardDefinition(MULTI, MULTI, CardType.HERO_POWER, cost=2, on_use=MULTI,
        metadata=replace(META, classes=(CardClass.MAGE,))))
    def watch(c):
        event = c.event
        if mode == 'start_kill' and event.kind == 'hero_power_started':
            ids = tuple(i for i in c.state.players[1].board if c.state.entities[i].card_id == SPIRIT)
            return tuple(Destroy(i, c.source_id) for i in ids)
        if mode == 'start_fail' and event.kind == 'hero_power_started' or mode == 'armor_fail' and event.kind == 'armor_gained':
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        if mode == 'start_wait' and event.kind == 'hero_power_started' or mode == 'damage_wait' and event.kind == 'damage_dealt':
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
        return ()
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=8, metadata=META,
        triggers=tuple(TriggerSpec(event, WATCH) for event in ('hero_power_started', 'armor_gained', 'damage_dealt'))))
    r.validate(); return r


class PersonalHeroPowerValueTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), *, power='HERO_06bp', mode='normal', board=()):
        self.mode = mode
        if mode != 'normal': board = (*board, WATCH)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hero_power_card_id=power, hand=hand, board=board,
                deck=(NOOP,)*12, mana=20, max_mana=20, mana_cap=20),
            PlayerSetup('HERO_01', hero_power_card_id='HERO_01bp', deck=(NOOP,)*12,
                mana=20, max_mana=20, mana_cap=20)), seed=472), fixture(mode))

    def power(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_power_id]

    def use(self, g, player=1, target=None, power_id=None):
        g.apply(UseHeroPower(player, self.power(g, player).id if power_id is None else power_id, target))

    def health(self, g, player=2):
        return g.state.entities[g.state.players[player].hero_id].health

    def armor(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].armor

    def effects(self, g, kind, player=1):
        return tuple(e for e in g.state.players[player].player_effects if g.registry.player_effect(e.spec_id).kind == kind)

    def test_complete_thirteen_rows_four_full_primary_faces_and_unchanged_basic_definitions(self):
        data = load_batch(); raws = {x['record']['id']: x['record'] for x in data['dependencies']}
        self.assertEqual((set(raws), len(data['existing_dependencies']), len(data['official_observations'])),
            ({SPIRIT, FIRE_EATER}, 11, 4))
        hashes = {}
        for o in data['official_observations']:
            if o['response_file'] not in hashes: hashes[o['response_file']] = batch.sha(o['response_file'])
            self.assertEqual(hashes[o['response_file']], o['response_sha256'])
            batch.check_face(raws[o['card_id']], o['face'], o['locale'])
        for cid, pin in data['existing_power_definition_pins'].items():
            self.assertEqual(batch.canonical(asdict(fixture().card(cid))), pin)
        self.assertFalse(data['cn_calibrated']); self.assertFalse(data['formal_pool_complete'])

    def test_spirit_real_battlecry_grants_one_player_program_without_immediate_armor(self):
        g = self.game((SPIRIT,)); self.play(g, SPIRIT)
        self.assertEqual((g.state.players[1].mana, self.armor(g), len(self.effects(g, ARMOR))), (19, 0, 1))
        self.use(g); self.assertEqual(self.armor(g), 2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack, 1)

    def test_spirit_real_deathrattle_adds_a_second_independent_permanent_program(self):
        g = self.game((SPIRIT, KILL)); source = self.play(g, SPIRIT); self.play(g, KILL, source)
        self.assertEqual(len(self.effects(g, ARMOR)), 2); self.use(g); self.assertEqual(self.armor(g), 3)

    def test_silencing_source_does_not_remove_battlecry_reward_but_removes_deathrattle(self):
        g = self.game((SPIRIT, SILENCE, KILL)); source = self.play(g, SPIRIT)
        self.play(g, SILENCE, source); self.play(g, KILL, source)
        self.assertEqual(len(self.effects(g, ARMOR)), 1); self.use(g); self.assertEqual(self.armor(g), 2)

    def test_ordinary_armor_spell_is_not_a_skill_armor_output(self):
        g = self.game((SPIRIT, ARMOR_SPELL)); self.play(g, SPIRIT); self.play(g, ARMOR_SPELL)
        self.assertEqual(self.armor(g), 5); self.use(g); self.assertEqual(self.armor(g), 7)

    def test_skill_without_armor_does_not_gain_an_invented_armor_packet(self):
        g = self.game((SPIRIT,), power='HERO_08bp'); self.play(g, SPIRIT)
        self.use(g, target=g.state.players[2].hero_id)
        self.assertEqual((self.armor(g), self.health(g)), (0, 29))

    def test_armor_program_survives_primary_skill_replacement_and_uses_new_skill_base(self):
        g = self.game((SPIRIT, REPLACE)); self.play(g, SPIRIT); self.play(g, REPLACE); self.use(g)
        self.assertEqual(self.armor(g), 3)

    def test_armor_program_survives_hero_replacement(self):
        g = self.game((SPIRIT, HERO)); self.play(g, SPIRIT); self.play(g, HERO); self.use(g)
        self.assertEqual(self.armor(g), 3); self.assertEqual(len(self.effects(g, ARMOR)), 1)

    def test_upgraded_warrior_and_druid_armor_outputs_use_the_same_public_amount_path(self):
        for power, expected in (('HERO_01bp2', 5), ('HERO_06bp2', 3)):
            g = self.game((SPIRIT,), power=power); self.play(g, SPIRIT); self.use(g)
            self.assertEqual(self.armor(g), expected)

    def test_permanent_armor_remains_on_following_owner_turns(self):
        g = self.game((SPIRIT,)); self.play(g, SPIRIT); self.use(g)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.use(g)
        self.assertEqual(self.armor(g), 4); self.assertEqual(len(self.effects(g, ARMOR)), 1)

    def test_stolen_spirit_death_rewards_current_death_controller(self):
        g = self.game((SPIRIT, TAKE, KILL)); source = self.play(g, SPIRIT)
        self.play(g, TAKE, source); self.play(g, KILL, source)
        self.assertEqual((len(self.effects(g, ARMOR)), len(self.effects(g, ARMOR, 2))), (1, 1))
        self.use(g); self.assertEqual(self.armor(g), 2)
        g.apply(EndTurn(1)); self.use(g, player=2); self.assertEqual(self.armor(g, 2), 3)

    def test_spirit_dying_at_start_updates_native_armor_before_its_output(self):
        g = self.game((SPIRIT,), mode='start_kill'); self.play(g, SPIRIT); self.use(g)
        self.assertEqual(self.armor(g), 3)

    def test_fire_eater_real_entry_does_not_damage_or_consume_before_skill_use(self):
        g = self.game((FIRE_EATER,), power='HERO_08bp'); self.play(g, FIRE_EATER)
        self.assertEqual((g.state.players[1].mana, self.health(g), len(self.effects(g, NEXT_DAMAGE))), (19, 30, 1))
        self.use(g, target=g.state.players[2].hero_id)
        self.assertEqual((self.health(g), len(self.effects(g, NEXT_DAMAGE))), (27, 0))
        self.assertEqual(len(g.state.hero_power_history[-1].value_plan.claimed), 1)

    def test_two_fire_eaters_stack_in_one_original_activation_and_consume_once(self):
        g = self.game((FIRE_EATER, FIRE_EATER), power='HERO_08bp')
        self.play(g, FIRE_EATER); self.play(g, FIRE_EATER); self.use(g, target=g.state.players[2].hero_id)
        self.assertEqual(self.health(g), 25)
        self.assertEqual(len(g.state.hero_power_history[-1].value_plan.claimed), 2)

    def test_claim_keeps_the_other_permanent_program_in_the_shared_player_account(self):
        g = self.game((SPIRIT, FIRE_EATER), power='HERO_01bp')
        self.play(g, SPIRIT); self.play(g, FIRE_EATER); self.use(g)
        self.assertEqual((self.armor(g), len(self.effects(g, ARMOR)), len(self.effects(g, NEXT_DAMAGE))), (3, 1, 0))
        plan = g.state.hero_power_history[-1].value_plan
        self.assertEqual((len(plan.before), len(plan.claimed)), (2, 1)); self.portable(g)

    def test_existing_native_repetition_keeps_one_original_next_activation_budget(self):
        g = self.game((FIRE_EATER,), power='HERO_08bp', board=('TOY_528',)); self.play(g, FIRE_EATER)
        self.use(g, target=g.state.players[2].hero_id)
        self.assertEqual(self.health(g), 24)
        self.assertEqual(len(g.state.hero_power_history[-1].value_plan.claimed), 1)
        self.portable(g)

    def test_later_same_turn_activation_does_not_reuse_claimed_damage(self):
        g = self.game((FIRE_EATER, REFRESH), power='HERO_08bp'); self.play(g, FIRE_EATER)
        self.use(g, target=g.state.players[2].hero_id); self.play(g, REFRESH); self.use(g, target=g.state.players[2].hero_id)
        self.assertEqual(self.health(g), 26); self.assertIsNone(g.state.hero_power_history[-1].value_plan)

    def test_next_nondamaging_skill_consumes_the_damage_program_without_inventing_damage(self):
        g = self.game((FIRE_EATER,), power='HERO_01bp'); self.play(g, FIRE_EATER); self.use(g)
        self.assertEqual((self.armor(g), self.health(g), len(self.effects(g, NEXT_DAMAGE))), (2, 30, 0))
        self.assertIsNotNone(g.state.hero_power_history[-1].value_plan)

    def test_unused_damage_expires_at_current_turn_end(self):
        g = self.game((FIRE_EATER,), power='HERO_08bp'); self.play(g, FIRE_EATER); g.apply(EndTurn(1))
        self.assertFalse(self.effects(g, NEXT_DAMAGE)); g.apply(EndTurn(2))
        self.use(g, target=g.state.players[2].hero_id); self.assertEqual(self.health(g), 29)

    def test_old_unused_program_cannot_be_reintroduced_after_turn_expiry(self):
        g = self.game((FIRE_EATER,), power='HERO_08bp'); self.play(g, FIRE_EATER)
        original = self.effects(g, NEXT_DAMAGE)[0]; g.apply(EndTurn(1))
        g._state.players[1].player_effects.append(original)
        with self.assertRaises(ValueError): g._assert_stable()

    def test_unrelated_spell_does_not_consume_or_receive_skill_damage(self):
        g = self.game((FIRE_EATER, DAMAGE_SPELL), power='HERO_08bp'); self.play(g, FIRE_EATER); self.play(g, DAMAGE_SPELL)
        self.assertEqual((self.health(g), len(self.effects(g, NEXT_DAMAGE))), (29, 1))
        self.use(g, target=g.state.players[2].hero_id); self.assertEqual(self.health(g), 26)

    def test_spell_damage_source_does_not_amplify_the_skill_bonus(self):
        g = self.game((FIRE_EATER,), power='HERO_08bp', board=('EX1_012',)); self.play(g, FIRE_EATER)
        self.use(g, target=g.state.players[2].hero_id); self.assertEqual(self.health(g), 27)

    def test_existing_healing_conversion_uses_genuine_hero_power_damage_pipeline(self):
        g = self.game((FIRE_EATER,), power='HERO_09bp', board=('EX1_591',)); self.play(g, FIRE_EATER)
        self.use(g, target=g.state.players[2].hero_id); self.assertEqual(self.health(g), 26)

    def test_one_original_budget_applies_to_every_packet_of_that_skill_activation(self):
        g = self.game((FIRE_EATER,), power=MULTI); self.play(g, FIRE_EATER); self.use(g)
        self.assertEqual((self.health(g, 1), self.health(g)), (27, 26))
        self.assertEqual(len(g.state.hero_power_history[-1].value_plan.claimed), 1)

    def test_damage_reward_survives_its_original_source_death(self):
        g = self.game((FIRE_EATER, KILL), power='HERO_08bp'); source = self.play(g, FIRE_EATER)
        self.play(g, KILL, source); self.use(g, target=g.state.players[2].hero_id); self.assertEqual(self.health(g), 27)

    def test_additional_active_skill_claims_the_same_players_next_activation_budget(self):
        g = self.game((EXTRA, FIRE_EATER)); self.play(g, EXTRA); self.play(g, FIRE_EATER)
        extra = g.state.players[1].additional_hero_power_ids[0]
        self.use(g, power_id=extra, target=g.state.players[2].hero_id)
        self.assertEqual(self.health(g), 27); self.assertEqual(g.state.hero_power_history[-1].source_id, extra)

    def test_automatic_actual_activation_claims_without_manual_payment_or_use_count(self):
        g = self.game((FIRE_EATER, AUTO), power='HERO_08bp'); self.play(g, FIRE_EATER); self.play(g, AUTO)
        self.assertEqual((self.health(g), self.power(g).uses_this_turn), (27, 0))
        self.assertEqual(g.state.hero_power_history[-1].origin, 'effect')

    def test_invalid_manual_target_does_not_consume_budget_or_pay(self):
        g = self.game((FIRE_EATER,), power='HERO_08bp'); self.play(g, FIRE_EATER); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_start_wait_saves_consumed_budget_and_resumes_original_damage_without_reclaim(self):
        g = self.game((FIRE_EATER,), power='HERO_08bp', mode='start_wait'); self.play(g, FIRE_EATER)
        self.use(g, target=g.state.players[2].hero_id)
        self.assertIsNotNone(g.state.pending_choice); self.assertFalse(self.effects(g, NEXT_DAMAGE))
        g = self.portable(g); self.choose(g); self.assertEqual(self.health(g), 27)

    def test_damage_wait_saves_original_budget_and_completed_health_packet(self):
        g = self.game((FIRE_EATER,), power='HERO_08bp', mode='damage_wait'); self.play(g, FIRE_EATER)
        self.use(g, target=g.state.players[2].hero_id); self.assertEqual(self.health(g), 27)
        g = self.portable(g); self.choose(g); self.assertEqual(self.health(g), 27)

    def test_start_failure_restores_the_exact_pending_budget_payment_and_root_history(self):
        g = self.game((FIRE_EATER,), power='HERO_08bp', mode='start_fail'); self.play(g, FIRE_EATER); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.use(g, target=g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(), before)

    def test_late_armor_failure_restores_skill_use_and_committed_armor_history(self):
        g = self.game((SPIRIT,), mode='armor_fail'); self.play(g, SPIRIT); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_waiting_failure_returns_to_original_paid_skill_boundary(self):
        g = self.game((FIRE_EATER,), power='HERO_08bp', mode='start_wait'); self.play(g, FIRE_EATER)
        self.use(g, target=g.state.players[2].hero_id); g = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before); self.choose(g); self.assertEqual(self.health(g), 27)

    def test_program_kinds_do_not_borrow_spell_damage_or_other_program_text(self):
        for kind in (ARMOR, NEXT_DAMAGE):
            with self.assertRaises(ValueError): PlayerEffectSpec('k472.invalid', SPIRIT, kind, spell_damage=1)
            with self.assertRaises(ValueError): PlayerEffectSpec('k472.invalid', SPIRIT, kind, duration=1, tick_event='turn_ended')
        with self.assertRaises(ValueError): HeroPowerValueProfile(ARMOR_SPEC, True)
        with self.assertRaises(ValueError): HeroPowerValueProfile(ARMOR_SPEC, 0)

    def test_pending_account_plan_rejects_partial_claims_and_foreign_player(self):
        g = self.game((FIRE_EATER, FIRE_EATER), power='HERO_08bp', mode='start_wait')
        self.play(g, FIRE_EATER); self.play(g, FIRE_EATER); self.use(g, target=g.state.players[2].hero_id)
        plan = g.state.hero_power_history[-1].value_plan
        with self.assertRaisesRegex(ValueError, 'omitted part'):
            validate_plan(g.state, g.registry, replace(plan, claimed=plan.claimed[:1]))
        with self.assertRaises(ValueError): replace(g.state.hero_power_history[-1], value_plan=replace(plan, player_id=2))

    def test_consumed_instances_cannot_be_reused_by_a_later_record(self):
        from hs_sim.engine.hero_power_values import validate_history
        g = self.game((FIRE_EATER, REFRESH), power='HERO_08bp'); self.play(g, FIRE_EATER)
        self.use(g, target=g.state.players[2].hero_id); self.play(g, REFRESH); self.use(g, target=g.state.players[2].hero_id)
        state = g.state; first = state.hero_power_history[0]
        state.hero_power_history[-1] = replace(state.hero_power_history[-1], value_plan=first.value_plan)
        with self.assertRaisesRegex(ValueError, 'reused'): validate_history(state, g.registry)

    def test_record_plan_roundtrips_and_old_schema_is_rejected(self):
        g = self.game((FIRE_EATER,), power='HERO_08bp'); self.play(g, FIRE_EATER); self.use(g, target=g.state.players[2].hero_id)
        g = self.portable(g); self.assertIsNotNone(g.state.hero_power_history[-1].value_plan)
        import json
        for player in (1, 2):
            view = json.dumps(g.for_player(player).observe())
            for key in ('value_plan', 'claimed', 'hero_power_value_profiles'):
                self.assertNotIn('"'+key+'"', view)
        old = deepcopy(g.snapshot()); old['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError): Game.from_snapshot(old, fixture('normal', 'independent-reader'))
