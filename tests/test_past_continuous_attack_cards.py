from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_continuous_attack_cards import HERO_ATTACK, IMP_COUNT, LEAVES, LIBRARIAN, PUPPET, load_batch, register_past_continuous_attack_cards
from hs_sim.engine import Attack, AuraSpec, CardDefinition, CardType, EndTurn, Game, Keyword, PlayerSetup, Registry, Scenario, TriggerSpec, Zone
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import Buff, ChangeControl, ChoiceOption, CopyMinion, Damage, Destroy, EquipWeapon, GainArmor, InvokeBehavior, ModifyWeapon, RequestChoice, ReturnToHand, SetStats, Silence, Transform
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import CardClass, CardMetadata, StatRelationLayer as Layer, StatRelationOperand as Operand, StatRelationSpec, StatReference, TargetMode, TargetSpec, TribeChangeSpec, validate_invariants
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.stat_relations import GrantStatRelation
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.tribes import ChangeMinionTribes
from tools import card_batch as batch


P = 'test.k469.'
HERO, ENEMY, PLAIN, ALL, FAKE_IMP, DEMON, UNKNOWN, WEAPON, SHORT, ARMOR_WEAPON, SMITH, WATCH = (
    P+s for s in ('hero', 'enemy', 'plain', 'all', 'fake_imp', 'demon', 'unknown', 'weapon', 'short', 'armor_weapon', 'smith', 'watch'))
NOOP, HERO3, HERO1, OTHER2, TEMP3, EQUIP, BREAK, ARMOR5, KILL, HIT, TAKE, SILENCE, TO_IMP, TO_PLAIN, DORMANT, TRIBES, SUMMON, COPY, RETURN, BUFF2, SET1, MODIFY, FAIL = (
    P+s for s in ('noop', 'hero3', 'hero1', 'other2', 'temp3', 'equip', 'break', 'armor5', 'kill', 'hit', 'take', 'silence', 'to_imp', 'to_plain', 'dormant', 'tribes', 'summon', 'copy', 'return', 'buff2', 'set1', 'modify', 'fail'))
IMP = 'UNG_829t3'
CONTEXT = GenerationContext('k469-explicit-native-attack', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())


@lru_cache(None)
def complete_registry():
    return build_registry()


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = Registry('k469-'+mode)
    register_past_continuous_attack_cards(r)
    r.register_card(complete_registry().card(IMP))
    for cid, card_class in ((HERO, CardClass.DEMON_HUNTER), (ENEMY, CardClass.WARLOCK)):
        r.register_card(CardDefinition(cid, cid, CardType.HERO, health=60,
            metadata=CardMetadata(False, (card_class,), None, tribes=(), subtypes=())))
    for cid, tribes, meta in ((PLAIN, (), META), (ALL, ('all',), META), (FAKE_IMP, (), META), (DEMON, ('demon',), META), (UNKNOWN, (), None)):
        r.register_card(CardDefinition(cid, 'Imp' if cid == FAKE_IMP else cid, CardType.MINION, attack=1, health=8,
            metadata=None if meta is None else replace(meta, tribes=tribes)))
    for cid, attack, durability in ((WEAPON, 3, 3), (SHORT, 3, 1), (ARMOR_WEAPON, 0, 3)):
        r.register_card(CardDefinition(cid, cid, CardType.WEAPON, attack=attack, durability=durability, metadata=META,
            stat_relations=(StatRelationSpec(operand=Operand.CONTROLLER_ARMOR),) if cid == ARMOR_WEAPON else ()))
    r.register_card(CardDefinition(SMITH, SMITH, CardType.MINION, health=8, metadata=META,
        auras=(AuraSpec(attack=2, target='friendly_weapon', condition='self_damaged'),)))
    def hero(c, other=False):
        return c.state.players[3-c.player_id if other else c.player_id].hero_id
    def fail(c):
        raise ResolutionError('K469 deliberate late numeric reaction failure')
    scripts = {
        NOOP: lambda c: (), HERO3: lambda c: (Buff(hero(c), attack=3, source_id=c.source_id),),
        HERO1: lambda c: (Buff(hero(c), attack=1, source_id=c.source_id),),
        OTHER2: lambda c: (Buff(hero(c, True), attack=2, source_id=c.source_id),),
        TEMP3: lambda c: (Buff(hero(c), attack=3, source_id=c.source_id, expires_turn=c.state.turn),),
        EQUIP: lambda c: (EquipWeapon(c.player_id, WEAPON),),
        BREAK: lambda c: (ModifyWeapon(c.state.players[c.player_id].weapon_id, durability=-3, source_id=c.source_id),),
        MODIFY: lambda c: (ModifyWeapon(c.state.players[c.player_id].weapon_id, attack=2, source_id=c.source_id),),
        ARMOR5: lambda c: (GainArmor(c.player_id, 5),), KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        HIT: lambda c: (Damage(c.target_id, 1, c.source_id),),
        TAKE: lambda c: (ChangeControl(c.target_id, 2),), SILENCE: lambda c: (Silence(c.target_id),),
        TO_IMP: lambda c: (Transform(c.target_id, IMP),), TO_PLAIN: lambda c: (Transform(c.target_id, PLAIN),),
        DORMANT: lambda c: (MakeDormant(c.target_id, 1, c.source_id),),
        TRIBES: lambda c: (ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]), TribeChangeSpec('set', ('all',)), c.source_id),),
        SUMMON: lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(IMP),), SummonCause.capture(c)),),
        COPY: lambda c: (CopyMinion(c.target_id, 2, cause=SummonCause.capture(c)),),
        RETURN: lambda c: (ReturnToHand(c.target_id),),
        BUFF2: lambda c: (Buff(c.target_id, attack=2, source_id=c.source_id),),
        SET1: lambda c: (SetStats(c.target_id, attack=1, source_id=c.source_id),), FAIL: fail,
    }
    targets = {KILL, HIT, TAKE, SILENCE, TO_IMP, TO_PLAIN, DORMANT, TRIBES, COPY, RETURN, BUFF2, SET1}
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,)) if cid in targets else None))
    def watch(c):
        e = c.event
        if mode == 'fail' and e.kind == 'stats_changed':
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        waiting = (mode == 'health_wait' and e.kind == 'health_resolved' or
            mode == 'armor_wait' and e.kind == 'armor_gained' or
            mode == 'start_wait' and e.kind == 'turn_started')
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),) if waiting else ()
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=12, metadata=META,
        triggers=tuple(TriggerSpec(e, WATCH) for e in ('stats_changed', 'health_resolved', 'armor_gained', 'turn_started'))))
    r.register_pool(PoolDefinition('constructed.past.cards', 'k469-two-readers', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid) for cid in LEAVES), complete=True))
    r.validate()
    return r


class PastContinuousAttackTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), board=(), *, enemy_board=(), weapon=None, enemy_weapon=None, armor=0, mode='normal', deck=(NOOP,)*8):
        self.mode = mode
        if mode in ('health_wait', 'armor_wait', 'start_wait', 'fail'):
            board = (*board, WATCH)
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO, hand=hand, board=board, deck=deck, mana=10, max_mana=10, armor=armor, weapon_card_id=weapon),
            PlayerSetup(ENEMY, board=enemy_board, deck=(NOOP,)*8, mana=10, max_mana=10, weapon_card_id=enemy_weapon)),
            seed=469, generation_context=CONTEXT), fixture(mode))

    def atk(self, g, cid, player=1):
        return self.entity(g, cid, player, 'board').attack

    def hero_attack(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].attack

    def test_two_complete_rows_four_full_primary_faces_and_native_specs(self):
        d = load_batch(); rows = {x['record']['id']: x['record'] for x in d['dependencies']}; hashes = {}
        self.assertEqual((set(rows), len(d['official_observations'])), (set(LEAVES), 4))
        for o in d['official_observations']:
            if o['response_file'] not in hashes: hashes[o['response_file']] = batch.sha(Path(o['response_file']))
            self.assertEqual(hashes[o['response_file']], o['response_sha256']); batch.check_face(rows[o['card_id']], o['face'], o['locale'])
        self.assertEqual(batch.sha(Path(d['source']['path'])), d['source']['sha256'])
        self.assertEqual(complete_registry().card(PUPPET).stat_relations, (HERO_ATTACK,))
        self.assertEqual(complete_registry().card(LIBRARIAN).stat_relations, (IMP_COUNT,))
        self.assertFalse(d['cn_calibrated']); self.assertFalse(d['formal_pool_complete'])

    def test_both_real_hand_entries_pay_once_without_battlecry_or_parallel_counter(self):
        for cid, health in ((PUPPET, 2), (LIBRARIAN, 3)):
            g = self.game((cid,)); source = self.play(g, cid)
            self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health, g.state.players[1].mana), (1, health, 9))
            self.assertEqual(len(g.state.play_history), 1); self.assertIsNone(g.registry.card(cid).battlecry)

    def test_puppet_reads_current_hero_attack_without_accumulating_repeated_refreshes(self):
        g = self.game((HERO3, NOOP, NOOP, NOOP), board=(PUPPET,)); self.play(g, HERO3)
        for _ in range(3):
            self.assertEqual((self.hero_attack(g), self.atk(g, PUPPET)), (3, 4)); self.play(g, NOOP)
        self.assertEqual(self.atk(g, PUPPET), 4)

    def test_temporary_hero_attack_expires_and_does_not_leave_permanent_minion_buff(self):
        g = self.game((TEMP3,), board=(PUPPET,)); self.play(g, TEMP3); self.assertEqual(self.atk(g, PUPPET), 4)
        g.apply(EndTurn(1)); self.assertEqual(self.atk(g, PUPPET), 1)
        g.apply(EndTurn(2)); self.assertEqual(self.atk(g, PUPPET), 1)

    def test_weapon_attack_is_included_only_in_the_active_hero_view(self):
        g = self.game(board=(PUPPET,), weapon=WEAPON)
        self.assertEqual((self.hero_attack(g), self.atk(g, PUPPET)), (3, 4))
        g.apply(EndTurn(1)); self.assertEqual((self.hero_attack(g), self.atk(g, PUPPET)), (0, 1))
        g.apply(EndTurn(2)); self.assertEqual((self.hero_attack(g), self.atk(g, PUPPET)), (3, 4))

    def test_permanent_hero_bonus_remains_while_off_turn_weapon_is_inactive(self):
        g = self.game((HERO1,), board=(PUPPET,), weapon=WEAPON); self.play(g, HERO1)
        self.assertEqual(self.atk(g, PUPPET), 5); g.apply(EndTurn(1))
        self.assertEqual((self.hero_attack(g), self.atk(g, PUPPET)), (1, 2))

    def test_equipping_modifying_and_breaking_weapon_refresh_same_source(self):
        g = self.game((EQUIP, MODIFY, BREAK), board=(PUPPET,)); source = self.entity(g, PUPPET, zone='board').id
        for cid, expected in ((EQUIP, 4), (MODIFY, 6), (BREAK, 1)):
            self.play(g, cid); self.assertEqual(g.state.entities[source].attack, expected)

    def test_actual_hero_attack_and_final_weapon_wear_drop_puppet_bonus(self):
        g = self.game(board=(PUPPET,), enemy_board=(PLAIN,), weapon=SHORT)
        g.apply(Attack(1, g.state.players[1].hero_id, self.entity(g, PLAIN, 2, 'board').id))
        self.assertEqual(self.entity(g, PLAIN, 2, 'board').health, 5)
        self.assertEqual((g.state.players[1].weapon_id, self.hero_attack(g), self.atk(g, PUPPET)), (None, 0, 1))

    def test_conditional_weapon_is_evaluated_before_hero_and_puppet(self):
        g = self.game((ARMOR5,), board=(PUPPET,), weapon=ARMOR_WEAPON); self.play(g, ARMOR5)
        self.assertEqual((self.hero_attack(g), self.atk(g, PUPPET)), (5, 6))

    def test_weapon_aura_refresh_is_visible_in_original_health_wait_context(self):
        g = self.game((HIT,), board=(PUPPET, SMITH), weapon=WEAPON, mode='health_wait')
        self.play(g, HIT, self.entity(g, SMITH, zone='board').id)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((self.hero_attack(g), self.atk(g, PUPPET)), (5, 6))
        g = self.portable(g); self.choose(g); self.assertEqual(self.atk(g, PUPPET), 6)

    def test_conditional_weapon_armor_wait_restores_dependency_order(self):
        g = self.game((ARMOR5,), board=(PUPPET,), weapon=ARMOR_WEAPON, mode='armor_wait'); self.play(g, ARMOR5)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(self.atk(g, PUPPET), 6)
        g = self.portable(g); self.choose(g); self.assertEqual(self.atk(g, PUPPET), 6)

    def test_turn_start_wait_uses_new_active_equipment_before_any_observer(self):
        g = self.game(board=(PUPPET,), weapon=WEAPON, mode='start_wait'); g.apply(EndTurn(1))
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(self.atk(g, PUPPET), 1)
        g = self.portable(g); self.choose(g)
        g.apply(EndTurn(2)); self.assertEqual(self.atk(g, PUPPET), 4); self.choose(g)

    def test_control_transfer_follows_new_controllers_current_hero(self):
        g = self.game((HERO3, OTHER2, TAKE), board=(PUPPET,)); source = self.entity(g, PUPPET, zone='board').id
        self.play(g, HERO3); self.play(g, OTHER2); self.assertEqual(self.atk(g, PUPPET), 4)
        self.play(g, TAKE, source); self.assertEqual(self.atk(g, PUPPET, 2), 3)

    def test_silence_removes_native_relation_and_future_hero_buffs_do_not_rearm(self):
        g = self.game((HERO3, SILENCE, HERO3), board=(PUPPET,)); source = self.entity(g, PUPPET, zone='board').id
        self.play(g, HERO3); self.play(g, SILENCE, source); self.play(g, HERO3)
        self.assertEqual(self.atk(g, PUPPET), 1)

    def test_copy_preserves_local_bonus_but_recomputes_new_controller_relation(self):
        g = self.game((HERO3, BUFF2, COPY), board=(PUPPET,)); source = self.entity(g, PUPPET, zone='board').id
        self.play(g, HERO3); self.play(g, BUFF2, source); self.assertEqual(self.atk(g, PUPPET), 6)
        self.play(g, COPY, source); self.assertEqual(self.atk(g, PUPPET, 2), 3)

    def test_return_and_reentry_do_not_bake_dynamic_attack_into_base(self):
        g = self.game((HERO3, RETURN), board=(PUPPET,)); source = self.entity(g, PUPPET, zone='board').id
        self.play(g, HERO3); self.play(g, RETURN, source); self.assertEqual(g.state.entities[source].attack, 1)
        self.play(g, PUPPET); self.assertEqual(g.state.entities[source].attack, 4)

    def test_dormant_puppet_suspends_and_wakes_with_current_hero_attack(self):
        g = self.game((HERO3, DORMANT), board=(PUPPET,)); source = self.entity(g, PUPPET, zone='board').id
        self.play(g, HERO3); self.play(g, DORMANT, source); self.assertEqual(g.state.entities[source].attack, 1)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.assertEqual(self.atk(g, PUPPET), 4)

    def test_offboard_sources_remain_printed_under_explicit_internal_policy(self):
        g = self.game((HERO3, PUPPET, LIBRARIAN), board=(IMP,), deck=(PUPPET,)); self.play(g, HERO3)
        self.assertEqual(self.entity(g, PUPPET).attack, 1); self.assertEqual(self.entity(g, LIBRARIAN).attack, 1)
        self.assertEqual(self.entity(g, PUPPET, zone='deck').attack, 1)

    def test_librarian_counts_real_imp_not_names_demons_all_tribes_or_enemy_imps(self):
        g = self.game(board=(LIBRARIAN, IMP, ALL, FAKE_IMP, DEMON), enemy_board=(IMP,))
        self.assertEqual(self.atk(g, LIBRARIAN), 2)

    def test_imp_arrivals_and_deaths_change_attack_without_accumulation(self):
        g = self.game((SUMMON, SUMMON, KILL, NOOP), board=(LIBRARIAN,)); self.play(g, SUMMON); self.assertEqual(self.atk(g, LIBRARIAN), 2)
        self.play(g, SUMMON); self.assertEqual(self.atk(g, LIBRARIAN), 3)
        self.play(g, KILL, self.entity(g, IMP, zone='board').id); self.play(g, NOOP); self.assertEqual(self.atk(g, LIBRARIAN), 2)

    def test_current_printed_face_transform_replaces_imp_membership(self):
        g = self.game((TO_PLAIN, TO_IMP), board=(LIBRARIAN, IMP)); target = self.entity(g, IMP, zone='board').id
        self.play(g, TO_PLAIN, target); self.assertEqual(self.atk(g, LIBRARIAN), 1)
        self.play(g, TO_IMP, target); self.assertEqual(self.atk(g, LIBRARIAN), 2)

    def test_silencing_or_changing_ordinary_tribes_does_not_change_imp_subtype(self):
        g = self.game((SILENCE, TRIBES), board=(LIBRARIAN, IMP)); target = self.entity(g, IMP, zone='board').id
        self.play(g, SILENCE, target); self.play(g, TRIBES, target); self.assertEqual(self.atk(g, LIBRARIAN), 2)

    def test_imp_and_librarian_control_changes_use_each_current_board(self):
        g = self.game((TAKE, TAKE), board=(LIBRARIAN, IMP), enemy_board=(IMP,))
        self.play(g, TAKE, self.entity(g, IMP, zone='board').id); self.assertEqual(self.atk(g, LIBRARIAN), 1)
        self.play(g, TAKE, self.entity(g, LIBRARIAN, zone='board').id); self.assertEqual(self.atk(g, LIBRARIAN, 2), 3)

    def test_dormant_imp_policy_skips_then_recounts_on_wake(self):
        g = self.game((DORMANT,), board=(LIBRARIAN, IMP)); self.play(g, DORMANT, self.entity(g, IMP, zone='board').id)
        self.assertEqual(self.atk(g, LIBRARIAN), 1); g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.assertEqual(self.atk(g, LIBRARIAN), 2)

    def test_unknown_active_subtype_errors_and_restores_real_play_instead_of_whiteboard(self):
        g = self.game((LIBRARIAN,), board=(UNKNOWN,)); snap = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, LIBRARIAN)
        self.assertEqual(g.snapshot(), snap)

    def test_librarian_silence_removes_only_native_reader(self):
        g = self.game((SILENCE, SUMMON), board=(LIBRARIAN, IMP)); target = self.entity(g, LIBRARIAN, zone='board').id
        self.play(g, SILENCE, target); self.play(g, SUMMON); self.assertEqual(self.atk(g, LIBRARIAN), 1)

    def test_set_attack_keeps_independent_continuous_contribution(self):
        g = self.game((HERO3, BUFF2, SET1), board=(PUPPET,)); target = self.entity(g, PUPPET, zone='board').id
        self.play(g, HERO3); self.play(g, BUFF2, target); self.assertEqual(self.atk(g, PUPPET), 6)
        self.play(g, SET1, target); self.assertEqual(self.atk(g, PUPPET), 4)

    def test_late_numeric_failure_rolls_back_source_and_dependent_cache(self):
        g = self.game((HERO3,), board=(PUPPET,), mode='fail'); snap = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, HERO3)
        self.assertEqual(g.snapshot(), snap)

    def test_native_spec_rejects_extra_amount_health_target_grants_and_mixed_declarations(self):
        for spec in (HERO_ATTACK, IMP_COUNT):
            for changes in (dict(amount=2), dict(amount=0), dict(target=StatReference.HEALTH), dict(layer=Layer.FINAL_ATTACK), dict(count_tribe='imp')):
                with self.assertRaises(ValueError): replace(spec, **changes)
            with self.assertRaises(ValueError): GrantStatRelation(1, spec)
            r = Registry('k469-invalid')
            with self.assertRaises(ValueError): r.register_card(CardDefinition(P+'bad', P+'bad', CardType.WEAPON, durability=3, stat_relations=(spec,)))
            with self.assertRaises(ValueError): r.register_card(CardDefinition(P+'mixed', P+'mixed', CardType.MINION, health=3, stat_relations=(spec, StatRelationSpec())))

    def test_native_ability_and_numeric_cache_cannot_be_forged(self):
        g = self.game(board=(PUPPET,), weapon=WEAPON); source = self.entity(g, PUPPET, zone='board').id
        ability = next(x for x in g.state.entities[source].abilities if x.kind == 'stat_relation')
        for changes in (dict(origin='granted'), dict(consumed=True), dict(expires_turn=3), dict(source_id=None)):
            with self.assertRaises(ValueError): replace(ability, **changes)
        bad = g.state; bad.entities[source].conditional_attack += 1
        with self.assertRaises(ValueError): validate_invariants(bad, g.registry)

    def test_prior_schema_rejected_and_no_source_private_state_is_projected(self):
        g = self.game((HERO3,), board=(PUPPET, LIBRARIAN, IMP)); self.play(g, HERO3); g = self.portable(g)
        snap = g.snapshot(); old = deepcopy(snap); old['schema_version'] = 551
        with self.assertRaises(SnapshotError): Game.from_snapshot(old, fixture())
        self.assertEqual(g.snapshot(), snap)


if __name__ == '__main__':
    unittest.main()
