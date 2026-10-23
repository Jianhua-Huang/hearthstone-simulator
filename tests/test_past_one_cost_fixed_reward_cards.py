from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_one_cost_fixed_reward_cards import (
    ACORN, BAT, BOLT, BOMBER, CHEF, CRAB, DEPENDENCIES, GUEST, LEAVES,
    PIRATE, RECRUIT, REVELER, SKELETON, SOLDIER, SQUIRREL, VALKYR, VRYKUL, WYRM, ZOMBIE, load_batch,
)
from hs_sim.engine import Attack, CardDefinition, CardType, Game, Keyword, PlayerSetup, Scenario, TargetSpec, TriggerSpec, Zone
from hs_sim.engine.effects import (
    ChoiceOption, Damage, Destroy, GrantKeyword, InvokeBehavior, RequestChoice,
    ReturnToHand, SetStats, Silence, TriggerDeathrattles,
)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.model import TargetMode, TribeChangeSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import ChangeMinionTribes
from tools import card_batch as batch


P = 'test.k461.'
KILL, SILENCE, MURLOCIZE, STRIP, SHIELD, TAKE, DR, LOW, NOOP, FAIL, WATCH, BOUNCER, POWER = (
    P + name for name in ('kill', 'silence', 'murlocize', 'strip', 'shield', 'take',
        'deathrattle', 'low', 'noop', 'fail', 'watch', 'bouncer', 'power'))
YETI, MURLOC, ALL, RAVEN, AXE, FLASHBACK = (
    'CORE_CS2_182', 'CORE_EX1_509', 'NX2_050', 'KAR_300', 'CS2_106', 'TIME_711')
CONTEXT = GenerationContext('k461-explicit-fixed-reward-leaves', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    from hs_sim.engine.effects import ChangeControl
    r = build_registry()
    r.register_pool(PoolDefinition('constructed.past.cards', 'eleven-explicit-leaves-v1',
        CONTEXT.target_id, CONTEXT.mode, tuple(PoolMember(cid) for cid in LEAVES), complete=True))

    def fail(c):
        raise ResolutionError('K461 deliberate late reward failure')

    def bounce_reward(c):
        ids = (i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id in (REVELER, CRAB))
        target = next(ids, None)
        return () if target is None else (ReturnToHand(target),)

    bodies = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        SILENCE: lambda c: (Silence(c.target_id),),
        MURLOCIZE: lambda c: (ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),
            TribeChangeSpec('set', ('murloc',)), c.source_id),),
        STRIP: lambda c: (ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),
            TribeChangeSpec('set', ()), c.source_id),),
        SHIELD: lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),),
        TAKE: lambda c: (ChangeControl(c.target_id, 2),),
        DR: lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        LOW: lambda c: tuple(SetStats(c.state.players[pid].hero_id, health=3, source_id=c.source_id) for pid in (1, 2)),
        NOOP: lambda c: (), FAIL: fail, BOUNCER: bounce_reward,
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        if cid != BOUNCER:
            r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
                targeting=TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,))
                    if cid in (KILL, SILENCE, MURLOCIZE, STRIP, SHIELD, TAKE, DR) else None))
    r.register_card(CardDefinition(BOUNCER, BOUNCER, CardType.MINION, attack=1, health=1, deathrattle=BOUNCER))
    r.register_card(CardDefinition(POWER, POWER, CardType.MINION, health=5, spell_damage=5))

    def watch(c):
        e = c.event
        target = c.state.entities.get(e.target_id)
        source = c.state.entities.get(e.source_id)
        named = target is not None and target.card_id in (SQUIRREL, RECRUIT, BOLT, VALKYR, BAT, PIRATE)
        reward = named and e.kind in ('card_added_to_hand', 'minion_summoned')
        damage = e.kind == 'damage_dealt' and source is not None and source.card_id in (ZOMBIE, SOLDIER, BOMBER)
        if mode == 'fail' and (reward or damage):
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        waiting = (mode == 'wait_hand' and named and e.kind == 'card_added_to_hand' or
            mode == 'wait_summon' and named and e.kind == 'minion_summoned' or
            mode == 'wait_death' and e.kind == 'minion_died' and target is not None and target.card_id == ACORN)
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),) if waiting else ()

    behavior = WATCH + '.' + mode
    r.register_behavior(behavior, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=40,
        triggers=tuple(TriggerSpec(event, behavior) for event in
            ('card_added_to_hand', 'minion_summoned', 'minion_died', 'damage_dealt')) if mode != 'normal' else ()))
    r.validate()
    return r


class PastOneCostFixedRewardTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), board=(), *, enemy_hand=(), enemy_board=(), weapon=None,
             enemy_weapon=None, active=1, mode='normal', mana=10):
        self.mode = mode
        marker = (WATCH,) if mode != 'normal' else ()
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=marker + board, weapon_card_id=weapon,
                hero_power_card_id='HERO_08bp', mana=mana, max_mana=mana),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board, weapon_card_id=enemy_weapon,
                hero_power_card_id='HERO_08bp', mana=10, max_mana=10)),
            active_player=active, seed=461, generation_context=CONTEXT), fixture(mode))

    def ids(self, g, player=1, zone='hand'):
        return tuple(g.state.entities[i].card_id for i in getattr(g.state.players[player], zone))

    def hero_health(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].health

    def test_seventeen_complete_rows_and_thirty_four_primary_faces_and_unchanged_dependencies(self):
        data = load_batch(); rows = {row['record']['id']: row['record'] for row in
            data['dependencies'] + data['existing_dependencies']}
        self.assertEqual((len(rows), len(data['official_observations'])), (17, 34))
        hashes = {}
        for o in data['official_observations']:
            if o['response_file'] not in hashes:
                hashes[o['response_file']] = batch.sha(Path(o['response_file']))
            self.assertEqual(hashes[o['response_file']], o['response_sha256'])
            batch.check_face(rows[o['card_id']], o['face'], o['locale'])
        for row in data['existing_dependencies']:
            self.assertEqual(batch.canonical(asdict(fixture().card(row['record']['id']))), row['definition_sha256'])
        for parent, child in ((ACORN, SQUIRREL), (SKELETON, PIRATE), (VRYKUL, VALKYR)):
            for o in data['official_observations']:
                if o['card_id'] == parent:
                    self.assertIn(rows[child]['dbf_id'], o['face']['childIds'])
        self.assertEqual((rows[BAT]['attack'], rows[BAT]['health'], rows[BAT]['name_en']), (2, 1, 'Thirsty Bat'))
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_eleven_real_hand_entries_pay_once_and_keep_native_stats(self):
        r = fixture()
        for cid in LEAVES:
            with self.subTest(card=cid):
                g = self.game((cid,)); eid = self.play(g, cid); e = g.state.entities[eid]
                self.assertEqual((e.attack, e.max_health, g.state.players[1].mana),
                    (r.card(cid).attack, r.card(cid).health, 9))
                self.assertEqual(len(g.state.play_history), 1)

    def test_crab_destroys_enemy_murloc_through_shield_without_damage_and_gains_two_two(self):
        g = self.game((SHIELD, CRAB), enemy_board=(MURLOC,)); target = self.entity(g, MURLOC, 2, 'board').id
        self.play(g, SHIELD, target); source = self.play(g, CRAB, target)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (3, 4))
        self.assertFalse(any(e.kind == 'damage_dealt' and e.target_id == target for e in g.events))

    def test_crab_accepts_friendly_all_tribes_minion(self):
        g = self.game((CRAB,), board=(ALL,)); target = self.entity(g, ALL, zone='board').id
        source = self.play(g, CRAB, target)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (3, 4))
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)

    def test_crab_matches_current_granted_tribe_and_rejects_removed_printed_tribe(self):
        g = self.game((MURLOCIZE, CRAB), enemy_board=(YETI,)); target = self.entity(g, YETI, 2, 'board').id
        self.play(g, MURLOCIZE, target); source = self.play(g, CRAB, target)
        self.assertEqual(g.state.entities[source].attack, 3)
        g = self.game((STRIP, CRAB), enemy_board=(MURLOC,)); target = self.entity(g, MURLOC, 2, 'board').id
        self.play(g, STRIP, target); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, CRAB, target)
        self.assertEqual(g.snapshot(), before)
        source = self.play(g, CRAB); self.assertEqual(g.state.entities[source].attack, 1)

    def test_crab_no_murloc_has_no_arrow_or_reward_and_illegal_targets_roll_back(self):
        g = self.game((CRAB,), enemy_board=(YETI,)); before = g.snapshot()
        for target in (self.entity(g, YETI, 2, 'board').id, g.state.players[2].hero_id):
            with self.assertRaises(IllegalAction): self.play(g, CRAB, target)
            self.assertEqual(g.snapshot(), before)
        source = self.play(g, CRAB)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (1, 2))

    def test_reveler_requires_friendly_victim_and_real_death_runs_before_buff(self):
        g = self.game((REVELER,), board=(ACORN,), enemy_board=(RAVEN,)); before = g.snapshot()
        for target in (None, self.entity(g, RAVEN, 2, 'board').id):
            with self.assertRaises(IllegalAction): self.play(g, REVELER, target)
            self.assertEqual(g.snapshot(), before)
        source = self.play(g, REVELER, self.entity(g, ACORN, zone='board').id)
        self.assertEqual(self.ids(g), (SQUIRREL, SQUIRREL))
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (3, 3))
        kinds = [e.kind for e in g.events]
        self.assertLess(kinds.index('card_added_to_hand'), kinds.index('stats_changed'))

    def test_reveler_without_other_friendly_minion_is_an_unbuffed_native_body(self):
        g = self.game((REVELER,)); source = self.play(g, REVELER)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (1, 1))
        self.assertFalse(g.state.death_history)

    def test_destroyed_victim_deathrattle_returning_original_beneficiary_prevents_reward(self):
        g = self.game((REVELER,), board=(BOUNCER,)); source = self.play(g, REVELER, self.entity(g, BOUNCER, zone='board').id)
        e = g.state.entities[source]
        self.assertEqual((e.zone, e.attack, e.health), (Zone.HAND, 1, 1))
        self.assertEqual(len(g.state.death_history), 1)
        self.portable(g)

    def test_wyrm_adds_original_arcane_bolt_and_both_manathirst_branches_really_cast(self):
        for mana, damage in ((7, 2), (8, 3)):
            with self.subTest(mana=mana):
                g = self.game((WYRM,), mana=mana); self.play(g, WYRM)
                self.assertEqual(self.ids(g), (BOLT,))
                self.play(g, BOLT, g.state.players[2].hero_id)
                self.assertEqual((self.hero_health(g, 2), g.state.players[1].mana), (30-damage, mana-2))

    def test_two_named_hand_rewards_have_physical_duplicates_and_independent_overflow(self):
        for root, token in ((ACORN, SQUIRREL), (CHEF, RECRUIT)):
            for fill, kept in ((0, 2), (9, 1), (10, 0)):
                with self.subTest(root=root, fill=fill):
                    g = self.game((NOOP,) * fill, board=(root,), enemy_hand=(KILL,), active=2)
                    target = self.entity(g, root, zone='board').id
                    self.play(g, KILL, target, 2)
                    children = [e for e in g.state.entities.values() if e.card_id == token]
                    self.assertEqual(len(children), 2); self.assertNotEqual(children[0].id, children[1].id)
                    self.assertEqual(sum(e.zone == Zone.HAND for e in children), kept)
                    self.assertTrue(all(e.owner == 1 and e.controller == 1 for e in children))
                    self.assertEqual(len(g.state.deathrattle_history), 1)

    def test_guest_natural_death_uses_original_board_slot_and_native_bat(self):
        g = self.game((KILL,), board=(YETI, GUEST, RAVEN)); source = self.entity(g, GUEST, zone='board').id
        self.play(g, KILL, source)
        self.assertEqual(self.ids(g, zone='board'), (YETI, BAT, RAVEN))
        bat = self.entity(g, BAT, zone='board')
        self.assertEqual((bat.attack, bat.health, bat.cost), (2, 1, 1))
        self.assertNotEqual(bat.id, source)

    def test_guest_active_deathrattle_summons_to_live_carrier_right_without_fake_death(self):
        g = self.game((DR,), board=(YETI, GUEST, RAVEN)); self.play(g, DR, self.entity(g, GUEST, zone='board').id)
        self.assertEqual(self.ids(g, zone='board'), (YETI, GUEST, BAT, RAVEN))
        self.assertFalse(g.state.death_history)

    def test_zombie_real_rush_attacks_minion_but_not_hero_on_entry(self):
        g = self.game((ZOMBIE,), enemy_board=(RAVEN,)); source = self.play(g, ZOMBIE); before = g.snapshot()
        with self.assertRaises(IllegalAction): g.apply(Attack(1, source, g.state.players[2].hero_id))
        self.assertEqual(g.snapshot(), before)
        g.apply(Attack(1, source, self.entity(g, RAVEN, 2, 'board').id))
        self.assertEqual(g.state.entities[source].health, 1)

    def test_zombie_current_controller_takes_four_nonspell_death_damage(self):
        g = self.game((TAKE, KILL), board=(ZOMBIE, POWER)); source = self.entity(g, ZOMBIE, zone='board').id
        self.play(g, TAKE, source); self.play(g, KILL, source)
        self.assertEqual((self.hero_health(g), self.hero_health(g, 2)), (30, 26))
        self.assertEqual(g.state.deathrattle_history[-1].capture.player_id, 2)

    def test_soldier_self_damage_is_two_and_native_shield_uses_original_combat(self):
        g = self.game((SOLDIER,), board=(POWER,)); source = self.play(g, SOLDIER)
        self.assertEqual(self.hero_health(g), 28); self.assertIn(Keyword.DIVINE_SHIELD, g.state.entities[source].keywords)
        g = self.game(board=(SOLDIER,), enemy_board=(RAVEN,), active=2)
        target = self.entity(g, SOLDIER, zone='board').id
        g.apply(Attack(2, self.entity(g, RAVEN, 2, 'board').id, target))
        self.assertEqual(g.state.entities[target].health, 1)
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[target].keywords)
        self.assertEqual(self.hero_health(g), 30)

    def test_bomber_hits_both_heroes_three_in_one_nonspell_batch(self):
        g = self.game((BOMBER,), board=(POWER,)); source = self.play(g, BOMBER)
        self.assertEqual((self.hero_health(g), self.hero_health(g, 2)), (27, 27))
        rows = [row.health_result for row in g.state.damage_history if row.health_result.source_id == source]
        self.assertEqual(len(rows), 2); self.assertEqual(rows[0].batch_id, rows[1].batch_id)
        self.assertTrue(all(row.damage_kind == 'minion_ability' for row in rows))

    def test_bomber_simultaneous_lethal_to_both_heroes_is_a_draw(self):
        g = self.game((LOW, BOMBER)); self.play(g, LOW); self.play(g, BOMBER)
        self.assertEqual((self.hero_health(g), self.hero_health(g, 2)), (0, 0))
        self.assertIsNone(g.state.winner)
        self.portable(g)

    def test_skeleton_own_hero_completed_attack_summons_one_native_undead_pirate(self):
        g = self.game(board=(SKELETON,), weapon=AXE)
        g.apply(Attack(1, g.state.players[1].hero_id, g.state.players[2].hero_id))
        self.assertEqual(self.ids(g, zone='board'), (SKELETON, PIRATE))
        child = self.entity(g, PIRATE, zone='board')
        self.assertEqual((child.attack, child.health, child.cost), (1, 1, 1))
        self.assertEqual(set(g.registry.card(PIRATE).metadata.tribes), {'undead', 'pirate'})
        self.assertEqual(len(g.state.character_attack_history), 1)

    def test_skeleton_other_minion_or_opponent_hero_attack_does_not_summon(self):
        g = self.game(board=(SKELETON, RAVEN))
        g.apply(Attack(1, self.entity(g, RAVEN, zone='board').id, g.state.players[2].hero_id))
        self.assertNotIn(PIRATE, self.ids(g, zone='board'))
        g = self.game(board=(SKELETON,), enemy_weapon=AXE, active=2)
        g.apply(Attack(2, g.state.players[2].hero_id, g.state.players[1].hero_id))
        self.assertEqual(self.ids(g, zone='board'), (SKELETON,))

    def test_skeleton_full_board_uses_normal_summon_capacity(self):
        g = self.game(board=(SKELETON,) + (RAVEN,) * 6, weapon=AXE)
        g.apply(Attack(1, g.state.players[1].hero_id, g.state.players[2].hero_id))
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertNotIn(PIRATE, self.ids(g, zone='board'))

    def test_vrykul_own_attack_gives_native_one_cost_valkyr_that_can_be_played(self):
        g = self.game(board=(VRYKUL,)); rng = g._rng.getstate()
        g.apply(Attack(1, self.entity(g, VRYKUL, zone='board').id, g.state.players[2].hero_id))
        self.assertEqual(self.ids(g), (VALKYR,)); self.assertEqual(g._rng.getstate(), rng)
        self.assertNotIn(VALKYR, str(g.for_player(2).observe()))
        source = self.play(g, VALKYR)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health, g.state.players[1].mana), (2, 3, 9))

    def test_vrykul_other_attacker_or_lethal_retaliation_has_no_reward(self):
        g = self.game(board=(VRYKUL, RAVEN)); g.apply(Attack(1, self.entity(g, RAVEN, zone='board').id, g.state.players[2].hero_id))
        self.assertFalse(g.state.players[1].hand)
        g = self.game(board=(VRYKUL,), enemy_board=(YETI,))
        g.apply(Attack(1, self.entity(g, VRYKUL, zone='board').id, self.entity(g, YETI, 2, 'board').id))
        self.assertFalse(g.state.players[1].hand); self.assertFalse(g.state.players[1].board)

    def test_vrykul_full_hand_burns_one_new_named_card(self):
        g = self.game((NOOP,) * 10, board=(VRYKUL,))
        g.apply(Attack(1, self.entity(g, VRYKUL, zone='board').id, g.state.players[2].hero_id))
        children = [e for e in g.state.entities.values() if e.card_id == VALKYR]
        self.assertEqual(len(children), 1); self.assertEqual(children[0].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand), 10)

    def test_silencing_both_attack_providers_removes_their_native_rewards(self):
        g = self.game((SILENCE, SILENCE), board=(SKELETON, VRYKUL), weapon=AXE)
        self.play(g, SILENCE, self.entity(g, SKELETON, zone='board').id)
        self.play(g, SILENCE, self.entity(g, VRYKUL, zone='board').id)
        g.apply(Attack(1, g.state.players[1].hero_id, g.state.players[2].hero_id))
        g.apply(Attack(1, self.entity(g, VRYKUL, zone='board').id, g.state.players[2].hero_id))
        self.assertFalse(g.state.players[1].hand); self.assertEqual(self.ids(g, zone='board'), (SKELETON, VRYKUL))

    def test_two_death_hand_grants_wait_restore_and_failed_choice_preserve_exact_delivery(self):
        g = self.game((KILL,), board=(ACORN,), mode='wait_hand')
        self.play(g, KILL, self.entity(g, ACORN, zone='board').id)
        self.assertIsNotNone(g.state.pending_choice); g = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before)
        self.choose(g); self.assertIsNotNone(g.state.pending_choice); self.choose(g)
        self.assertEqual(self.ids(g), (SQUIRREL, SQUIRREL))
        self.assertEqual(len(g.state.deathrattle_history), 1); self.assertTrue(g.state.deathrattle_history[0].completed)

    def test_destroy_reward_waits_for_real_victim_death_and_retains_original_paid_origin(self):
        g = self.game((REVELER,), board=(ACORN,), mode='wait_death')
        source = self.play(g, REVELER, self.entity(g, ACORN, zone='board').id)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(g.state.entities[source].attack, 1)
        g = self.portable(g); self.choose(g)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (3, 3))
        self.assertEqual(self.ids(g), (SQUIRREL, SQUIRREL)); self.assertEqual(g.state.players[1].mana, 9)

    def test_both_attack_reward_shapes_wait_restore_without_repeating_original_combat(self):
        for cid, mode in ((VRYKUL, 'wait_hand'), (SKELETON, 'wait_summon')):
            with self.subTest(card=cid):
                g = self.game(board=(cid,), weapon=AXE if cid == SKELETON else None, mode=mode)
                source = g.state.players[1].hero_id if cid == SKELETON else self.entity(g, cid, zone='board').id
                g.apply(Attack(1, source, g.state.players[2].hero_id))
                self.assertIsNotNone(g.state.pending_choice); g = self.portable(g); self.choose(g)
                self.assertEqual(len(g.state.character_attack_history), 1)
                self.assertEqual(self.hero_health(g, 2), 27 if cid == SKELETON else 29)
                expected = (VALKYR,) if cid == VRYKUL else (WATCH, SKELETON, PIRATE)
                self.assertEqual(self.ids(g) if cid == VRYKUL else self.ids(g, zone='board'), expected)

    def test_late_reward_and_self_damage_failures_restore_entire_real_action(self):
        for cid in (WYRM, SOLDIER, BOMBER):
            g = self.game((cid,), mode='fail'); before = g.snapshot()
            with self.assertRaises(ResolutionError): self.play(g, cid)
            self.assertEqual(g.snapshot(), before)
        g = self.game((KILL,), board=(CHEF,), mode='fail'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, KILL, self.entity(g, CHEF, zone='board').id)
        self.assertEqual(g.snapshot(), before)
        for cid in (VRYKUL, SKELETON):
            g = self.game(board=(cid,), weapon=AXE if cid == SKELETON else None, mode='fail'); before = g.snapshot()
            source = g.state.players[1].hero_id if cid == SKELETON else self.entity(g, cid, zone='board').id
            with self.assertRaises(ResolutionError): g.apply(Attack(1, source, g.state.players[2].hero_id))
            self.assertEqual(g.snapshot(), before)

    def test_real_flashback_has_all_explicit_leaves_and_ordinary_summons_do_not_run_battlecries(self):
        g = self.game((FLASHBACK,)); self.play(g, FLASHBACK)
        row, = g.state.pool_summon_history
        self.assertEqual({c.card_id for c in row.spec.basis.candidates}, set(LEAVES))
        self.assertEqual(len(g.state.players[1].board), 2); self.assertFalse(g.state.battlecry_history)
        self.assertFalse(g.state.players[1].hand); self.assertEqual((self.hero_health(g), self.hero_health(g, 2)), (30, 30))

    def test_batch_does_not_bind_a_production_past_or_standard_pool_or_expand_standard_roots(self):
        from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format
        r = build_registry(); self.assertNotIn('constructed.past.cards', r.pools); self.assertNotIn('constructed.cards', r.pools)
        self.assertFalse(set(DEPENDENCIES) & set(build_cn37_launch_candidate_format().root_card_ids))


if __name__ == '__main__':
    unittest.main()
