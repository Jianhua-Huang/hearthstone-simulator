"""Native Yogg with the real Tendril dependency and small behavioral fixtures."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json, unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry as full_registry
from hs_sim.cards import simple_followup_p68_cards as tendrils, yogg_unleashed as native
from hs_sim.engine import (EndTurn, Game, IllegalAction, PlayerSetup, ResolutionError,
    Scenario, UseMinionAbility)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy, Freeze,
    GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.forced_attack_sequences import ForceEachMinionAttack, ForcePlayerMinionsAttackEachOther
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import (BoardPresenceReference, CardClass, CardDefinition, CardMetadata,
    CardType, Keyword, LimitedTriggerSpec, Rarity, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, resolve_candidates
from hs_sim.engine.representative import build_registry
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError, canonical_digest
from tools import card_batch as batch

P = 'k617.'
UNIT, DORMANT, BORN, WATCH, CASTWATCH, COUNTER, ARMOR1, ARMOR2, NOOP, FORCE, ALL, FROST, COPY, FAIL, UNKNOWN = (
    P + name for name in ('unit', 'dormant', 'born', 'watch', 'castwatch', 'counter', 'armor1', 'armor2',
                         'noop', 'force', 'all', 'frost', 'copy', 'failure', 'unknown'))
META = CardMetadata(True, (CardClass.PRIEST,), Rarity.COMMON)


def context():
    return GenerationContext(P + 'complete', 'experimental')


@lru_cache(None)
def donor():
    return full_registry()


@lru_cache(None)
def registry(mode='normal', role='writer'):
    r = build_registry(); original = donor()
    # Copy complete immutable declarations and the actual native body, never a
    # whiteboard stand-in. Its ordinary progression program is needed by CAST.
    card = original.card(native.TENDRIL)
    r.register_card(card); r.register_pool_card(original.pool_card(native.TENDRIL))
    r.register_behavior(card.battlecry, original.behavior(card.battlecry))
    r.register_player_effect(original.player_effect(tendrils.PREFIX + 'tendril_progress'))
    native.register_yogg_unleashed(r)
    for cid in (ARMOR1, ARMOR2):
        r.register_behavior(cid, lambda c: (GainArmor(c.player_id, 3),))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=1 if cid == ARMOR1 else 2,
            on_play=cid, metadata=META))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_behavior(NOOP, lambda c: ())
    r.register_card(CardDefinition(NOOP, NOOP, CardType.SPELL, cost=1, on_play=NOOP))
    for cid in (UNIT, BORN):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=50))
    r.register_card(CardDefinition(DORMANT, DORMANT, CardType.MINION, attack=2, health=50, dormant_turns=2))
    r.register_behavior(FORCE, lambda c: (ForcePlayerMinionsAttackEachOther(3 - c.player_id),))
    r.register_behavior(ALL, lambda c: (ForceEachMinionAttack(),))
    r.register_behavior(FROST, lambda c: tuple(Freeze(i) for i in c.state.players[3 - c.player_id].board))
    r.register_behavior(COPY, lambda c: (CopyMinion(c.target_id, c.player_id),))
    for cid in (FORCE, ALL, FROST, COPY):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=1, on_play=cid,
            targeting=TargetSpec() if cid == COPY else None))
    def fail(c):
        raise ResolutionError('K617 deliberate resume failure')
    r.register_behavior(FAIL, fail)
    def watch(c):
        event = c.event
        others = [i for i in c.state.players[3 - c.player_id].board if i not in (event.source_id, event.target_id)]
        options = [ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),)),
            ChoiceOption('add', 'A new enemy defender', (Summon(3 - c.player_id, BORN, c.source_id),))]
        if others:
            options.append(ChoiceOption('steal', 'Remove remaining attacker from enemy side', (ChangeControl(others[0], c.player_id),)))
        return (RequestChoice(c.player_id, tuple(options), c.source_id),)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=50,
        limited_triggers=(LimitedTriggerSpec('attack_declared', WATCH),)))
    def cast_watch(c):
        cast = next(row for row in c.state.cast_history if row.id == dict(c.event.data)['cast_id'])
        if cast.caster_id is None or c.state.entities[cast.caster_id].card_id != native.YOGG:
            return ()
        source = cast.caster_id
        if mode == 'wait_cast':
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
        return {'death': (Destroy(source, c.source_id),), 'control': (ChangeControl(source, 3 - c.player_id),),
            'silence': (Silence(source),), 'transform': (Transform(source, UNIT),)}.get(mode, ())
    r.register_behavior(CASTWATCH, cast_watch)
    r.register_card(CardDefinition(CASTWATCH, CASTWATCH, CardType.WEAPON, attack=1, durability=2,
        limited_triggers=(LimitedTriggerSpec('spell_cast_started', CASTWATCH),)))
    def counter(c):
        return (CounterSpell(dict(c.event.data)['window_id']),) if c.state.entities[c.event.source_id].card_id == ARMOR1 else ()
    r.register_behavior(COUNTER, counter)
    r.register_card(CardDefinition(COUNTER, COUNTER, CardType.MINION, health=50,
        triggers=(TriggerSpec('card_committed', COUNTER),)))
    members = (ARMOR1, ARMOR2)
    if mode == 'counter': members = (ARMOR1,)
    if mode == 'unknown':
        r.register_pool_card(PoolCard(UNKNOWN, CardType.SPELL, 1, META)); members = (UNKNOWN,)
    r.register_pool(PoolDefinition(native.POOL, P + 'spells-v1', context().target_id, 'experimental',
        tuple(PoolMember(cid) for cid in members), complete=True))
    r.validate()
    return r


class YoggUnleashedTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(registry)
    mode = 'normal'

    def game(self, hand=(), *, board=(native.YOGG,), enemy_board=(UNIT,), mode='normal', player=1, hand_cap=10, seed=617):
        self.mode = mode
        setup = tuple(PlayerSetup('HERO_08', hand=hand if p == player else (), board=board if p == player else enemy_board,
            deck=(NOOP,) * 12, mana=30, max_mana=30, mana_cap=30, hand_cap=hand_cap,
            weapon_card_id=CASTWATCH if p == player and mode in ('wait_cast', 'death', 'control', 'silence', 'transform') else None)
            for p in (1, 2))
        return Game.from_scenario(Scenario(setup, active_player=player, seed=seed, generation_context=context()), registry(mode))

    def source(self, g, player=1):
        return self.entity(g, native.YOGG, player, 'board')

    def use(self, g, skill, target=None, *, source=None, player=1):
        sid = self.source(g, player).id if source is None else source
        mana = g.state.players[player].mana; g.apply(UseMinionAbility(player, sid, skill, target))
        self.assertEqual(g.state.players[player].mana, mana)
        return sid

    def casts(self, g, source):
        return [c for c in g.state.cast_history if c.caster_id == source and c.origin == 'effect']

    def attacks(self, g):
        return [e for e in g.events if e.kind == 'attack_declared' and dict(e.data).get('forced')]

    def test_six_full_rows_eight_primary_faces_and_exact_existing_tendril_are_preserved(self):
        d = native.load_batch()
        self.assertEqual(sum(len(d[k]) for k in ('cards', 'dependencies', 'existing_dependencies', 'evidence_only')), 6)
        self.assertEqual(len(d['official_observations']), 8); r = registry()
        self.assertEqual(canonical_digest(asdict(r.card(native.TENDRIL))), d['existing_dependencies'][0]['definition_sha256'])
        self.assertEqual(r.card(native.TENDRIL), donor().card(native.TENDRIL))
        for cid in native.ROOTS + native.SKILLS:
            self.assertEqual(r.card(cid), donor().card(cid))
        for cid in native.SKILLS:
            self.assertTrue(r.card(cid).choice_only); self.assertNotIn(cid, r.pool_cards)
        self.assertNotIn('YOG_516e', r.cards)
        self.assertLess(len(r.cards), 400)

    def test_both_seats_pay_nine_take_control_then_cast_two_foreign_class_spells_for_free(self):
        for player in (1, 2):
            with self.subTest(player=player):
                g = self.game((native.YOGG,), board=(), player=player)
                sid = self.play(g, native.YOGG, player=player); target = g.state.players[3 - player].board[0]
                self.assertEqual(g.state.players[player].mana, 21); self.use(g, native.SKILLS[0], target, player=player)
                self.assertEqual(g.state.entities[target].controller, player)
                self.assertEqual(len(self.casts(g, sid)), 2)
                self.assertTrue(all(c.completed and c.play_id is None and c.player_id == player for c in self.casts(g, sid)))
                self.assertEqual(g.state.entities[g.state.players[player].hero_id].armor, 6)
                self.assertEqual(len(g.state.play_history), 1)
        self.portable(g)

    def test_control_requires_a_legal_enemy_minion_and_cannot_target_hero_friendly_or_dormant(self):
        g = self.game(board=(native.YOGG, UNIT), enemy_board=(DORMANT,)); sid = self.source(g).id
        for target in (None, g.state.players[1].board[-1], g.state.players[2].hero_id, g.state.players[2].board[0]):
            before = g.snapshot()
            with self.assertRaises(IllegalAction): g.apply(UseMinionAbility(1, sid, native.SKILLS[0], target))
            self.assertEqual(g.snapshot(), before)

    def test_enemy_side_original_roster_attacks_once_without_hitting_friendly_minions_or_heroes(self):
        g = self.game(board=(native.YOGG, UNIT), enemy_board=(UNIT,) * 3)
        enemies = set(g.state.players[2].board); sid = self.use(g, native.SKILLS[1]); attacks = self.attacks(g)
        self.assertEqual(len(attacks), 3); self.assertEqual({e.source_id for e in attacks}, enemies)
        self.assertTrue(all(e.target_id in enemies and e.target_id != e.source_id for e in attacks))
        self.assertEqual(sum(g.state.entities[i].health for i in enemies), 144)
        self.assertEqual([g.state.entities[i].health for i in g.state.players[1].board], [5, 50])
        self.assertEqual(len(self.casts(g, sid)), 2); self.portable(g)

    def test_public_one_side_empty_or_single_roster_needs_no_rng(self):
        for enemy in ((), (UNIT,)):
            g = self.game((FORCE,), board=(), enemy_board=enemy); rng = g._rng.getstate(); self.play(g, FORCE)
            self.assertFalse(self.attacks(g)); self.assertEqual(g._rng.getstate(), rng)

    def test_legacy_both_board_effect_keeps_all_original_attackers_and_original_shape(self):
        g = self.game((ALL,), board=(UNIT,) * 2, enemy_board=(UNIT,) * 2)
        original = set(g.state.players[1].board + g.state.players[2].board); self.play(g, ALL)
        self.assertEqual(len(self.attacks(g)), 4); self.assertEqual({e.source_id for e in self.attacks(g)}, original)
        self.assertEqual(asdict(ForceEachMinionAttack()), {'remaining': None})

    def test_forced_frozen_enemies_do_not_spend_normal_attack_budget(self):
        g = self.game((FROST,), enemy_board=(UNIT,) * 2); self.play(g, FROST); ids = tuple(g.state.players[2].board)
        self.use(g, native.SKILLS[1]); self.assertEqual(len(self.attacks(g)), 2)
        self.assertTrue(all(g.state.entities[i].frozen and g.state.entities[i].attacks_this_turn == 0 for i in ids))

    def test_original_combat_wait_restores_without_redraw_and_failed_resume_is_atomic(self):
        g = self.game(board=(native.YOGG, WATCH), enemy_board=(UNIT,) * 3); sid = self.use(g, native.SKILLS[1])
        self.assertIsNotNone(g.state.pending_choice); self.assertFalse(self.casts(g, sid)); g = self.portable(g); saved = g.snapshot()
        for player in (1, 2):
            view = json.dumps(g.for_player(player).observe())
            for private in ('ForcePlayerMinionsAttackEachOther', 'presence_id', 'rng_state', 'resolution_frame'):
                self.assertNotIn(private, view)
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved); self.choose(g)
        self.assertEqual(len(self.attacks(g)), 3); self.assertEqual(len(self.casts(g, sid)), 2); self.portable(g)

    def test_newly_summoned_enemy_can_defend_but_is_not_added_to_original_attacker_roster(self):
        g = self.game(board=(native.YOGG, WATCH), enemy_board=(UNIT,) * 3, seed=618); original = set(g.state.players[2].board)
        self.use(g, native.SKILLS[1]); self.choose(g, 'add'); born = self.entity(g, BORN, 2, 'board')
        self.assertEqual({e.source_id for e in self.attacks(g)}, original)
        self.assertIn(born.id, {e.target_id for e in self.attacks(g)})
        self.assertNotIn(born.id, {e.source_id for e in self.attacks(g)})

    def test_remaining_original_attacker_that_changes_sides_is_skipped(self):
        g = self.game(board=(native.YOGG, WATCH), enemy_board=(UNIT,) * 3); original = set(g.state.players[2].board)
        self.use(g, native.SKILLS[1]); self.choose(g, 'steal'); moved = original - set(g.state.players[2].board)
        self.assertEqual(len(moved), 1); self.assertEqual({e.source_id for e in self.attacks(g)}, original - moved)

    def test_fill_uses_actual_capacity_and_generated_real_tendrils_continue_the_existing_progression(self):
        for cap in (10, 12):
            g = self.game((NOOP,) * 2, hand_cap=cap); sid = self.use(g, native.SKILLS[2])
            cards = [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id == native.TENDRIL]
            self.assertEqual(len(cards), cap - 2); self.assertEqual(len(self.casts(g, sid)), 2)
            self.assertTrue(all((e.base_cost, e.attack, e.health) == (1, 1, 1) for e in cards))
            first = self.play(g, native.TENDRIL); second = self.play(g, native.TENDRIL)
            self.assertEqual([self.casts(g, first)[0].card_id, self.casts(g, second)[0].card_id], [ARMOR1, ARMOR2])
            self.assertEqual(sum(e.spec_id == tendrils.PREFIX + 'tendril_progress' for e in g.state.players[1].player_effects), 2)

    def test_full_hand_adds_nothing_but_still_accepts_two_automatic_spells(self):
        g = self.game((NOOP,) * 10); sid = self.use(g, native.SKILLS[2])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [NOOP] * 10)
        self.assertEqual(len(self.casts(g, sid)), 2)

    def test_two_automatic_casts_use_cast_windows_without_manual_play_commit_or_mana_payment(self):
        g = self.game((ARMOR1,), board=(native.YOGG, COUNTER), enemy_board=(), mode='counter')
        self.play(g, ARMOR1); self.assertEqual(g.state.cast_history[0].failure, 'countered')
        sid = self.use(g, native.SKILLS[1])
        self.assertEqual(len(self.casts(g, sid)), 2); self.assertTrue(all(c.completed and c.failure is None for c in self.casts(g, sid)))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 6)
        self.assertEqual(len([e for e in g.events if e.kind == 'card_committed']), 1)

    def test_accepted_cast_pair_survives_source_death_silence_transform_and_control_change(self):
        for mode in ('death', 'silence', 'transform', 'control'):
            g = self.game(enemy_board=(), mode=mode); sid = self.use(g, native.SKILLS[1])
            self.assertEqual(len(self.casts(g, sid)), 2); self.assertTrue(all(c.player_id == 1 and c.completed for c in self.casts(g, sid)))
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 6)
            self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor, 0)
        self.portable(g)

    def test_first_automatic_cast_wait_retains_player_and_remaining_second_cast(self):
        g = self.game(enemy_board=(), mode='wait_cast'); sid = self.use(g, native.SKILLS[1]); g = self.portable(g)
        self.assertEqual(len(self.casts(g, sid)), 1); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved); self.choose(g)
        self.assertEqual(len(self.casts(g, sid)), 2); self.portable(g)

    def test_unknown_eligible_spell_rolls_back_skill_usage_tendrils_rng_and_allocation(self):
        g = self.game(mode='unknown'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.use(g, native.SKILLS[2])
        self.assertEqual(g.snapshot(), saved)

    def test_another_titan_does_not_trigger_yogg_and_current_yogg_copy_has_only_its_own_after_body(self):
        g = self.game((COPY,), board=(native.YOGG, 'TTN_903'))
        eonar = self.entity(g, 'TTN_903', 1, 'board'); g.apply(UseMinionAbility(1, eonar.id, 'TTN_903t'))
        self.assertFalse(g.state.cast_history); sid = self.source(g).id; self.play(g, COPY, sid)
        copied = [i for i in g.state.players[1].board if i != sid and g.state.entities[i].card_id == native.YOGG][0]
        self.use(g, native.SKILLS[2], source=copied)
        self.assertEqual(len(self.casts(g, copied)), 2); self.assertFalse(self.casts(g, sid))

    def test_public_queue_inputs_refuse_invalid_players_duplicate_and_future_residences(self):
        g = self.game(); ref = BoardPresenceReference.capture(g.state, g.state.players[2].board[0])
        for player in (0, 3, True):
            with self.assertRaises(ValueError): ForcePlayerMinionsAttackEachOther(player)
        with self.assertRaises(ValueError): ForcePlayerMinionsAttackEachOther(2, (ref, ref))
        with self.assertRaises(ValueError): ForcePlayerMinionsAttackEachOther(2, (replace(ref, presence_id=g.state.next_order),)).validate_in_state(g.state)
        with self.assertRaises(ValueError): ForcePlayerMinionsAttackEachOther(2, (BoardPresenceReference(999999, 1),)).validate_in_state(g.state)

    def test_complete_host_keeps_entire_spell_domain_and_executes_all_native_entries(self):
        fmt = build_cn37_local_pool_format(); candidates = resolve_candidates(fmt.registry, fmt.context,
            native.POOL, native.QUERY, current_class=CardClass.WARRIOR, source_card_id=native.YOGG, player_id=1)
        self.assertGreater(len(candidates), 100); self.assertTrue(all(c.card_id in fmt.registry.cards for c in candidates))
        for skill in native.SKILLS:
            g = Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=(native.YOGG,), mana=10, max_mana=10),
                PlayerSetup('HERO_08', board=('CORE_EX1_162',) * 2)), seed=617, generation_context=fmt.context), fmt.registry)
            sid = self.play(g, native.YOGG); target = g.state.players[2].board[0] if skill == native.SKILLS[0] else None
            g.apply(UseMinionAbility(1, sid, skill, target))
            self.assertEqual(len([e for e in g.events if e.kind == 'minion_ability_used' and e.source_id == sid]), 1)
            if g.state.status == 'playing': self.assertEqual(len(self.casts(g, sid)), 2)
            self.assertEqual(Game.from_snapshot(g.snapshot(), fmt.registry).snapshot(), g.snapshot())

    def test_bad_last_face_and_changed_existing_dependency_cannot_half_register(self):
        for mode in ('descriptor', 'dependency'):
            r = batch.registration_prefix(full_registry, 'hs_sim.cards.yogg_unleashed.register_yogg_unleashed', lambda r: None)
            data = deepcopy(native.load_batch()); before = r.fingerprint()
            if mode == 'descriptor': data['dependencies'][-1]['record']['type'] = 'MINION'
            else: data['existing_dependencies'][0]['definition_sha256'] = '0' * 64
            with patch.object(native, 'load_batch', lambda: data), self.assertRaises(TargetValidationError): native.register_yogg_unleashed(r)
            self.assertEqual(r.fingerprint(), before)


if __name__ == '__main__':
    unittest.main()
