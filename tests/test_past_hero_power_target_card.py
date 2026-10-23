"""Real Sharpshooter entry, live permissions and accepted skill targets."""
from dataclasses import asdict, replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards.past_hero_power_target_card import CARD, POWERS, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayerSetup, Scenario, UseHeroPower, Zone)
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy,
    InvokeBehavior, ReplaceHeroPower, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.hero_power_targets import (MARKER, HeroPowerMinionTargetProfile,
    validate_carrier, validate_profile)
from hs_sim.engine.hero_powers import AddHeroPower, TriggerHeroPower
from hs_sim.engine.model import AbilityInstance, TargetSpec, TriggerSpec

P = 'k473.'
UNIT, STEALTH, ELUSIVE, IMMUNE, LOCATION, WATCH, FAIL = (
    P+s for s in ('unit', 'stealth', 'elusive', 'immune', 'location', 'watch', 'fail'))
KILL, MUTE, BOUNCE, TAKE, MORPH, SLEEP, COPY, BASE_COPY, WAKE, MAGE, HUNTER, UPGRADE, EXTRA, AUTO = (
    P+s for s in ('kill', 'mute', 'bounce', 'take', 'morph', 'sleep', 'copy', 'basecopy',
                 'wake', 'mage', 'hunter', 'upgrade', 'extra', 'auto'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry(); r._version = 'k473-'+mode
    targeted = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),), MUTE: lambda c: (Silence(c.target_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),), TAKE: lambda c: (ChangeControl(c.target_id, 2),),
        MORPH: lambda c: (Transform(c.target_id, UNIT),), SLEEP: lambda c: (MakeDormant(c.target_id, None),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id),),
        BASE_COPY: lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        AUTO: lambda c: (TriggerHeroPower(c.player_id, c.source_id, targeting='explicit', target_id=c.target_id),),
    }
    scripts = {**targeted,
        WAKE: lambda c: (AwakenMinion(c.state.players[c.player_id].board[0], c.source_id),),
        MAGE: lambda c: (ReplaceHeroPower(c.player_id, 'HERO_08bp', source_id=c.source_id),),
        HUNTER: lambda c: (ReplaceHeroPower(c.player_id, POWERS[0], source_id=c.source_id),),
        UPGRADE: lambda c: (ReplaceHeroPower(c.player_id, POWERS[1], source_id=c.source_id),),
        EXTRA: lambda c: (AddHeroPower(c.player_id, POWERS[0], c.source_id),),
    }
    def fail(c): raise ResolutionError('K473 deliberate late skill target failure')
    scripts[FAIL] = fail
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)) if cid in targeted else None))
    for cid, keywords in ((UNIT, ()), (STEALTH, (Keyword.STEALTH,)),
            (ELUSIVE, (Keyword.ELUSIVE,)), (IMMUNE, (Keyword.IMMUNE,))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=2, health=8,
            keywords=keywords, metadata=META))
    r.register_behavior(LOCATION, lambda c: ())
    r.register_card(CardDefinition(LOCATION, LOCATION, CardType.LOCATION,
        durability=3, on_use=LOCATION, metadata=META))
    def watch(c):
        if c.event.kind == 'hero_power_started':
            sources = tuple(i for i in c.state.players[c.player_id].board
                if c.state.entities[i].card_id == CARD)
            effects = tuple(Destroy(i, c.source_id) for i in sources) if mode in (
                'start_remove', 'start_wait', 'start_swap') else ()
            if mode == 'start_swap':
                effects += (ReplaceHeroPower(c.player_id, 'HERO_08bp', source_id=c.source_id),)
            if mode == 'start_fail': return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
            if mode == 'start_wait':
                effects += (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
                    ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
            return effects
        if mode == 'damage_wait' and c.event.kind == 'damage_dealt':
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),), c.source_id),)
        return ()
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=8, metadata=META,
        triggers=(TriggerSpec('hero_power_started', WATCH), TriggerSpec('damage_dealt', WATCH))))
    r.validate(); return r


class PastHeroPowerTargetTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), *, board=(), enemy=(UNIT,), power=POWERS[0], mode='normal',
             hero='HERO_05', mana=20, opponent_hand=(), seed=473):
        self.mode = mode
        if mode != 'normal': board = (*board, WATCH)
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, deck=(UNIT,)*5, hero_power_card_id=power,
                mana=mana, max_mana=20, mana_cap=20),
            PlayerSetup('HERO_05', hand=opponent_hand, board=enemy, deck=(UNIT,)*5,
                hero_power_card_id=POWERS[0], mana=20, max_mana=20, mana_cap=20)), seed=seed), fixture(mode))

    def power(self, g, player=1): return g.state.players[player].hero_power_id
    def use(self, g, target=None, player=1, power=None):
        g.apply(UseHeroPower(player, power or self.power(g, player), target))
    def actions(self, g): return tuple(a for a in g.legal_actions() if isinstance(a, UseHeroPower))
    def reject(self, g, target=None):
        before = g.snapshot()
        with self.assertRaises(IllegalAction): self.use(g, target)
        self.assertEqual(g.snapshot(), before)

    def test_complete_three_original_rows_two_primary_faces_and_both_unchanged_skills(self):
        data = load_batch(); row = data['dependencies'][0]['record']
        self.assertEqual((row['id'], len(data['existing_dependencies']), len(data['official_observations'])), (CARD, 2, 2))
        for face in data['official_observations']:
            self.assertEqual(batch.sha(face['response_file']), face['response_sha256'])
            batch.check_face(row, face['face'], face['locale'])
        for cid, pin in data['existing_power_definition_pins'].items():
            self.assertEqual(batch.canonical(asdict(fixture().card(cid))), pin)
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_both_skills_without_a_source_keep_original_untargeted_damage_and_target_rejection(self):
        for cid, amount in zip(POWERS, (2, 3)):
            g = self.game(power=cid); self.assertEqual(g.legal_targets(self.power(g)), ())
            self.reject(g, g.state.players[2].board[0]); self.use(g)
            self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30-amount)

    def test_real_entry_pays_one_and_adds_one_removable_permission_without_replacing_skill(self):
        g = self.game((CARD,)); power = self.power(g); source = self.play(g, CARD)
        self.assertEqual(g.state.players[1].mana, 19); self.assertEqual(self.power(g), power)
        self.assertEqual(sum(a.kind == MARKER for a in g.state.entities[source].abilities), 1)
        self.assertFalse(g.state.battlecry_history); self.assertFalse(g.state.hero_power_history)
        self.assertEqual({a.target_id for a in self.actions(g)}, set(g.legal_targets(power)))

    def test_real_skill_selects_enemy_minion_and_keeps_original_payment_usage_and_damage_kind(self):
        g = self.game((CARD,)); self.play(g, CARD); target = g.state.players[2].board[0]
        self.use(g, target)
        self.assertEqual((g.state.entities[target].health, g.state.players[1].mana), (6, 17))
        row = g.state.hero_power_history[-1]
        self.assertEqual((row.target_id, row.card_id, row.cost, row.completed), (target, POWERS[0], 2, True))
        self.assertEqual(g.state.entities[self.power(g)].uses_this_turn, 1)

    def test_friendly_minions_and_the_permission_source_are_real_selectable_targets(self):
        for self_target in (False, True):
            g = self.game(board=(CARD, UNIT)); target = g.state.players[1].board[0 if self_target else 1]
            health = g.state.entities[target].health; self.use(g, target)
            self.assertEqual(g.state.entities[target].health, health-2)

    def test_enemy_hero_remains_selectable_but_own_hero_is_never_added(self):
        g = self.game(board=(CARD,)); own = g.state.players[1].hero_id; enemy = g.state.players[2].hero_id
        self.assertNotIn(own, g.legal_targets(self.power(g))); self.reject(g, own)
        self.assertIn(enemy, g.legal_targets(self.power(g))); self.use(g, enemy)
        self.assertEqual(g.state.entities[enemy].health, 28)

    def test_live_permission_requires_an_actual_arrow_and_does_not_default_missing_input(self):
        g = self.game(board=(CARD,)); self.assertNotIn(None, {a.target_id for a in self.actions(g)})
        self.reject(g)

    def test_opponent_source_does_not_enable_my_skill(self):
        g = self.game(enemy=(CARD, UNIT)); self.assertFalse(g.legal_targets(self.power(g)))
        self.use(g); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28)

    def test_two_sources_do_not_duplicate_skill_damage(self):
        g = self.game(board=(CARD, CARD)); target = g.state.players[2].board[0]
        self.use(g, target); self.assertEqual(g.state.entities[target].health, 6)

    def test_silence_removes_live_permission_and_restores_untargeted_shot(self):
        g = self.game((MUTE,), board=(CARD,)); self.play(g, MUTE, g.state.players[1].board[0])
        self.assertFalse(g.legal_targets(self.power(g))); self.use(g)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28)

    def test_last_source_death_removes_permission_but_another_source_keeps_it(self):
        for count in (1, 2):
            g = self.game((KILL,), board=(CARD,)*count); self.play(g, KILL, g.state.players[1].board[0])
            self.assertEqual(bool(g.legal_targets(self.power(g))), count == 2)

    def test_bounce_deactivates_and_real_replay_reinstalls_one_native_permission(self):
        g = self.game((BOUNCE,), board=(CARD,)); source = g.state.players[1].board[0]
        self.play(g, BOUNCE, source); self.assertFalse(g.legal_targets(self.power(g)))
        self.play(g, CARD); self.assertTrue(g.legal_targets(self.power(g)))
        self.assertEqual(sum(a.kind == MARKER for a in g.state.entities[source].abilities), 1)

    def test_control_transfer_moves_live_permission_to_actual_new_controller(self):
        g = self.game((TAKE,), board=(CARD,)); self.play(g, TAKE, g.state.players[1].board[0])
        self.assertFalse(g.legal_targets(self.power(g))); g.apply(EndTurn(1))
        target = g.state.players[2].board[0]; self.assertIn(target, g.legal_targets(self.power(g, 2)))
        self.use(g, target, 2); self.assertEqual(g.state.entities[target].health, 6)

    def test_transformation_removes_native_permission(self):
        g = self.game((MORPH,), board=(CARD,)); self.play(g, MORPH, g.state.players[1].board[0])
        self.assertFalse(g.legal_targets(self.power(g))); self.use(g)

    def test_dormancy_suspends_and_awakening_restores_same_native_permission(self):
        g = self.game((SLEEP, WAKE), board=(CARD,)); source = g.state.players[1].board[0]
        self.play(g, SLEEP, source); self.assertFalse(g.legal_targets(self.power(g)))
        self.play(g, WAKE); self.assertTrue(g.legal_targets(self.power(g)))

    def test_current_copy_preserves_permission_and_silenced_current_copy_does_not_restore_it(self):
        for muted in (False, True):
            g = self.game((COPY, MUTE), board=(CARD,)); source = g.state.players[1].board[0]
            if muted: self.play(g, MUTE, source)
            self.play(g, COPY, source); self.assertEqual(bool(g.legal_targets(self.power(g))), not muted)

    def test_base_copy_of_silenced_source_installs_fresh_printed_permission(self):
        g = self.game((BASE_COPY, MUTE), board=(CARD,)); source = g.state.players[1].board[0]
        self.play(g, MUTE, source); self.play(g, BASE_COPY, source)
        self.assertTrue(g.legal_targets(self.power(g)))

    def test_shared_manual_protection_excludes_enemy_stealth_and_all_elusive(self):
        g = self.game(board=(CARD, STEALTH, ELUSIVE), enemy=(UNIT, STEALTH, ELUSIVE, IMMUNE))
        own, enemy = g.state.players[1].board, g.state.players[2].board
        targets = g.legal_targets(self.power(g))
        self.assertIn(own[1], targets); self.assertNotIn(own[2], targets)
        self.assertIn(enemy[0], targets)
        for eid in enemy[1:]: self.assertNotIn(eid, targets)
        self.reject(g, enemy[1]); self.reject(g, enemy[2]); self.reject(g, enemy[3])

    def test_location_is_not_a_minion_target_and_full_board_does_not_block_skill(self):
        g = self.game(board=(CARD,)+(UNIT,)*6, enemy=(LOCATION, UNIT))
        self.assertNotIn(g.state.players[2].board[0], g.legal_targets(self.power(g)))
        self.use(g, g.state.players[2].board[1])

    def test_target_query_does_not_grant_mana_or_usage_permission(self):
        g = self.game(board=(CARD,), mana=0); self.assertTrue(g.legal_targets(self.power(g)))
        self.assertFalse(self.actions(g)); self.reject(g, g.state.players[2].board[0])

    def test_printed_skill_identity_controls_permission_independently_of_hero_class(self):
        g = self.game(board=(CARD,), hero='HERO_01'); self.use(g, g.state.players[2].board[0])
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health, 6)

    def test_other_skill_keeps_its_own_target_domain_and_normal_damage(self):
        g = self.game(board=(CARD,), power='HERO_08bp'); target = g.state.players[1].hero_id
        self.assertIn(target, g.legal_targets(self.power(g))); self.use(g, target)
        self.assertEqual(g.state.entities[target].health, 29)

    def test_switching_away_and_back_recomputes_live_permission_without_power_attachments(self):
        g = self.game((MAGE, HUNTER), board=(CARD,)); self.play(g, MAGE)
        self.assertIn(g.state.players[1].hero_id, g.legal_targets(self.power(g)))
        self.play(g, HUNTER); self.assertNotIn(g.state.players[1].hero_id, g.legal_targets(self.power(g)))
        self.use(g, g.state.players[2].board[0])

    def test_upgraded_ballista_uses_same_permission_and_real_three_damage(self):
        g = self.game((UPGRADE,), board=(CARD,)); self.play(g, UPGRADE); target = g.state.players[2].board[0]
        self.use(g, target); self.assertEqual(g.state.entities[target].health, 5)

    def test_additional_installed_skill_gets_permission_without_rewriting_primary(self):
        g = self.game((EXTRA,), board=(CARD,), power='HERO_08bp'); primary = self.power(g)
        self.play(g, EXTRA); extra = g.state.players[1].additional_hero_power_ids[0]
        self.assertEqual(primary, self.power(g)); self.assertNotIn(g.state.players[1].hero_id, g.legal_targets(extra))
        self.use(g, g.state.players[2].board[0], power=extra)

    def test_automatic_activation_uses_same_live_domain_without_manual_skill_payment_or_use(self):
        g = self.game((AUTO,), board=(CARD,)); target = g.state.players[2].board[0]
        self.play(g, AUTO, target); row = g.state.hero_power_history[-1]
        self.assertEqual((row.target_id, row.origin, row.completed, g.state.players[1].mana), (target, 'effect', True, 20))
        self.assertEqual(g.state.entities[self.power(g)].uses_this_turn, 0)

    def test_automatic_explicit_minion_without_live_permission_fails_without_damage(self):
        g = self.game((AUTO,)); target = g.state.players[2].board[0]; self.play(g, AUTO, target)
        self.assertEqual(g.state.hero_power_history[-1].failure, 'invalid_target')
        self.assertEqual(g.state.entities[target].health, 8)

    def test_native_random_target_acceptance_uses_full_expanded_domain_and_original_input(self):
        g = self.game(board=(CARD, 'CORE_CFM_670')); target = g.state.players[2].board[0]
        domain = g.legal_targets(self.power(g)); self.use(g, target)
        row = g.state.hero_power_history[-1]; selected = row.native_target
        self.assertIsNotNone(selected)
        self.assertEqual(selected.partition.target_ids, domain)
        self.assertEqual(selected.partition.submitted_target_id, target)
        self.assertEqual(row.target_id, selected.target_id)
        self.assertNotIn(g.state.players[1].hero_id, domain)

    def test_start_reaction_removing_source_keeps_the_accepted_minion_not_fallback_hero(self):
        g = self.game(board=(CARD,), mode='start_remove'); target = g.state.players[2].board[0]
        self.use(g, target); self.assertEqual(g.state.entities[target].health, 6)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)

    def test_real_repeat_keeps_original_target_after_permission_source_dies(self):
        g = self.game(board=(CARD, 'TOY_528'), mode='start_remove'); target = g.state.players[2].board[0]
        self.use(g, target); self.assertEqual(g.state.entities[target].health, 4)
        self.assertEqual(g.state.players[1].mana, 18)

    def test_start_reaction_replacing_skill_keeps_original_accepted_source_and_damage(self):
        g = self.game(board=(CARD,), mode='start_swap'); original = self.power(g); target = g.state.players[2].board[0]
        self.use(g, target); self.assertNotEqual(original, self.power(g))
        self.assertEqual((g.state.hero_power_history[-1].source_id, g.state.entities[target].health), (original, 6))

    def test_start_wait_restores_original_permission_acceptance_after_source_removal(self):
        g = self.game(board=(CARD,), mode='start_wait'); target = g.state.players[2].board[0]
        self.use(g, target); other = self.portable(g)
        self.assertEqual(g.state.entities[target].health, 8)
        self.choose(g); self.choose(other); self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.entities[target].health, 6)

    def test_completed_damage_wait_restores_and_resumes_without_second_skill_damage(self):
        g = self.game(board=(CARD,), mode='damage_wait'); target = g.state.players[2].board[0]
        self.use(g, target); other = self.portable(g); self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(g.state.entities[target].health, 6)

    def test_late_start_failure_rolls_back_payment_use_target_and_source_changes(self):
        g = self.game(board=(CARD,), mode='start_fail'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.use(g, g.state.players[2].board[0])
        self.assertEqual(g.snapshot(), before)

    def test_failed_waiting_choice_keeps_original_paid_target_boundary(self):
        g = self.game(board=(CARD,), mode='start_wait'); self.use(g, g.state.players[2].board[0]); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before); self.choose(g)

    def test_real_next_skill_damage_program_uses_same_selected_minion_health_path(self):
        g = self.game(('TRL_390',), board=(CARD,)); self.play(g, 'TRL_390'); target = g.state.players[2].board[0]
        self.use(g, target); self.assertEqual(g.state.entities[target].health, 4)

    def test_profile_and_native_marker_cannot_borrow_targeted_skills_or_arbitrary_carriers(self):
        r = fixture()
        for powers in ((), ('HERO_08bp',), (POWERS[0], POWERS[0])):
            with self.assertRaises(ValueError): validate_profile(r, HeroPowerMinionTargetProfile(CARD, powers))
        marker = AbilityInstance(1, MARKER, source_id=1, origin='printed')
        with self.assertRaises(ValueError): validate_carrier(r, UNIT, CardType.MINION, (marker,))
        with self.assertRaises(ValueError): validate_carrier(r, CARD, CardType.MINION, (marker, marker))
        for changed in (dict(origin='granted'), dict(remove_on_silence=False), dict(magnetic_id=1), dict(expires_turn=1)):
            with self.assertRaises(ValueError): replace(marker, **changed)

    def test_player_views_and_current_snapshot_keep_native_marker_private_and_reject_old_schema(self):
        g = self.game(board=(CARD,)); saved = g.snapshot(); saved['schema_version'] -= 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, fixture())
        for player in (1, 2):
            text = str(g.for_player(player).observe())
            self.assertNotIn('hero_power_target_profiles', text); self.assertNotIn('"'+MARKER+'"', text)


if __name__ == '__main__': unittest.main()
