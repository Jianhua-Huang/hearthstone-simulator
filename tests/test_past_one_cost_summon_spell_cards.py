from functools import lru_cache
from pathlib import Path
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_one_cost_summon_spell_cards import (
    BANSHEE, BUBBLER, CHIRURGEON, CONJURER, DEALER, DISTRIBUTOR, HEALER,
    LEAVES, ORACLE, PIRANHA, RACER, SUNFURY, ZEALOT, load_batch,
)
from hs_sim.engine import Attack, CardDefinition, CardType, CastSpell, EndTurn, Game, IllegalAction, Keyword, PlayerSetup, Scenario, TargetSpec, TriggerSpec, Zone
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (
    ChangeControl, ChoiceOption, Damage, DamageBatch, Destroy, Freeze, GrantKeyword, InvokeBehavior,
    RequestChoice, ReturnToHand, Silence, Summon, TriggerDeathrattles,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec, DamageKind, SpellSchool, TargetMode, TribeChangeSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference
from opening_fixtures import metadata
from tools import card_batch as batch


P = 'test.k463.'
NOOP, FIRE, FROST, KILL, ZERO, ONE, TWO, FOUR, SHIELD, SILENCE, BOTH, TAKE, HAND_UNDEAD, BOARD_UNDEAD, ENHANCE, FROZEN, SUMMON_YETI, SUMMON_RACER, AUTO_MINION, AUTO_FIRE_MINION, WATCH, FAIL, REENTER, POWER, UNKNOWN, DORMANT = (
    P + x for x in ('noop', 'fire', 'frost', 'kill', 'zero', 'one', 'two', 'four', 'shield', 'silence', 'both',
        'take', 'hand_undead', 'board_undead', 'enhance', 'frozen', 'summon_yeti', 'summon_racer',
        'auto_minion', 'auto_fire_minion', 'watch', 'fail', 'reenter', 'power', 'unknown', 'dormant'))
YETI, RAVEN, ALL, ZOMBIE, PIRATE, COUNTER, FIREBALL, COIN, FLASHBACK = (
    'CORE_CS2_182', 'KAR_300', 'NX2_050', 'NX2_024', 'WON_351', 'CORE_EX1_287', 'CORE_CS2_029', 'GAME_005', 'TIME_711')
CONTEXT = GenerationContext('k463-explicit-summon-spell-leaves', 'experimental')
ACTIVE_DR = P + 'active_dr'


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry()
    r.register_pool(PoolDefinition('constructed.past.cards', 'twelve-explicit-summon-spell-v1',
        CONTEXT.target_id, CONTEXT.mode, tuple(PoolMember(cid) for cid in LEAVES), complete=True))

    def fail(c):
        raise ResolutionError('K463 deliberate late reaction failure')

    def hand_undead(c):
        target = next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == YETI)
        return (ChangeMinionTribes(CardReference.capture(target), TribeChangeSpec('set', ('undead',)), c.source_id),)

    def enhance(c):
        target = c.state.entities[c.state.players[2].deck[0]]
        return (BuffStoredCard(CardReference.capture(target), 2, 1, c.source_id, cost=CostSpec(set_to=1)),)

    def freeze(c):
        return tuple(Freeze(i, c.source_id) for i in (c.state.players[2].hero_id,
            *(i for i in c.state.players[2].board if c.state.entities[i].card_id == RAVEN)))

    bodies = {
        NOOP: lambda c: (), FIRE: lambda c: (), FROST: lambda c: (), KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        SHIELD: lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),),
        SILENCE: lambda c: (Silence(c.target_id),),
        BOTH: lambda c: (DamageBatch(tuple(Damage(c.state.players[p].hero_id, 6, c.source_id, DamageKind.EFFECT) for p in (1, 2))),),
        TAKE: lambda c: (ChangeControl(c.target_id, 2),), HAND_UNDEAD: hand_undead,
        BOARD_UNDEAD: lambda c: (ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),
            TribeChangeSpec('set', ('undead',)), c.source_id),),
        ENHANCE: enhance, FROZEN: freeze, SUMMON_YETI: lambda c: (Summon(c.player_id, YETI),),
        SUMMON_RACER: lambda c: (Summon(c.player_id, RACER), Freeze(c.state.players[2].hero_id, c.source_id)),
        AUTO_MINION: lambda c: (CastSpell(c.player_id, NOOP, c.source_id, targeting='explicit'),),
        AUTO_FIRE_MINION: lambda c: (CastSpell(c.player_id, FIRE, c.source_id, targeting='explicit'),),
        REENTER: lambda c: (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id),),
        FAIL: fail,
        ACTIVE_DR: lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
    }
    for cid, amount in ((ZERO, 0), (ONE, 1), (TWO, 2), (FOUR, 4)):
        bodies[cid] = lambda c, amount=amount: (Damage(c.target_id, amount, c.source_id, DamageKind.EFFECT),)
    targeted = (KILL, SHIELD, SILENCE, TAKE, BOARD_UNDEAD, ZERO, ONE, TWO, FOUR, ACTIVE_DR)
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        if cid == REENTER: continue
        if cid in (AUTO_MINION, AUTO_FIRE_MINION):
            r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=5, battlecry=cid, metadata=metadata(tribes=())))
        else:
            r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
                targeting=TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,)) if cid in targeted else None,
                spell_school=SpellSchool.FIRE if cid == FIRE else SpellSchool.FROST if cid in (FROST, FROZEN) else None))
    r.register_card(CardDefinition(POWER, POWER, CardType.MINION, health=5, spell_damage=5, metadata=metadata(tribes=())))
    r.register_card(CardDefinition(UNKNOWN, UNKNOWN, CardType.MINION, attack=1, health=5))
    r.register_card(CardDefinition(DORMANT, DORMANT, CardType.MINION, attack=1, health=5,
        dormant_turns=2, metadata=metadata(tribes=('undead',))))

    def watch(c):
        e = c.event
        if mode == 'reenter' and e.kind == 'minion_summoned' and c.state.entities[e.target_id].card_id == YETI:
            if sum(r.entity_id == e.target_id for r in c.state.successful_summon_history) == 1:
                return (ReturnToHand(e.target_id), InvokeBehavior(REENTER, c.source_id, c.player_id, e.target_id))
        if mode == 'reenter_bubbler' and e.kind == 'damage_dealt' and e.amount == 1 and c.state.entities[e.target_id].card_id == BUBBLER:
            return (ReturnToHand(e.target_id), InvokeBehavior(REENTER, c.source_id, c.player_id, e.target_id))
        source = c.state.entities.get(e.source_id)
        cid = None if source is None else source.card_id
        entry = e.kind == 'stats_changed' and cid in (DEALER, DISTRIBUTOR, CHIRURGEON, ZEALOT, PIRANHA)
        random = e.kind == 'random_choice' and cid == BANSHEE
        copy = e.kind == 'card_added_to_hand' and cid in (CONJURER, ORACLE)
        burst = e.kind == 'damage_dealt' and e.amount > 0 and cid in (RACER, SUNFURY)
        healing = e.kind == 'health_resolved' and cid == HEALER and c.health_result.flow == 'healing'
        if mode == 'fail' and (entry or random or copy or burst or healing):
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        waiting = (mode == 'wait_entry' and entry or mode == 'wait_random' and random or
            mode == 'wait_copy' and copy or mode == 'wait_burst' and burst)
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),) if waiting else ()

    behavior = WATCH + '.' + mode
    r.register_behavior(behavior, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.WEAPON, attack=0, durability=50,
        triggers=tuple(TriggerSpec(e, behavior) for e in ('minion_summoned', 'stats_changed', 'random_choice',
            'card_added_to_hand', 'damage_dealt', 'health_resolved')) if mode != 'normal' else ()))
    r.validate()
    return r


class PastOneCostSummonSpellTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), board=(), *, enemy_hand=(), enemy_board=(), enemy_deck=(), active=1, mode='normal'):
        self.mode = mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(NOOP,)*4,
                weapon_card_id=WATCH if mode != 'normal' else None, hero_power_card_id='HERO_08bp', mana=10, max_mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board, deck=enemy_deck,
                hero_power_card_id='HERO_08bp', mana=10, max_mana=10)),
            active_player=active, seed=463, generation_context=CONTEXT), fixture(mode))

    def ids(self, g, player=1, zone='hand'):
        return tuple(g.state.entities[i].card_id for i in getattr(g.state.players[player], zone))

    def health(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].health

    def test_twelve_complete_raw_records_and_twenty_four_cached_full_primary_faces(self):
        data = load_batch(); rows = {x['record']['id']: x['record'] for x in data['dependencies']}; hashes = {}
        self.assertEqual((len(rows), len(data['official_observations'])), (12, 24))
        for o in data['official_observations']:
            if o['response_file'] not in hashes: hashes[o['response_file']] = batch.sha(Path(o['response_file']))
            self.assertEqual(hashes[o['response_file']], o['response_sha256'])
            batch.check_face(rows[o['card_id']], o['face'], o['locale'])
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_all_twelve_native_hand_entries_pay_one_and_keep_their_full_bodies(self):
        for cid in LEAVES:
            with self.subTest(card=cid):
                g = self.game((cid,)); source = self.play(g, cid)
                self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health, g.state.players[1].mana),
                    (g.registry.card(cid).attack, g.registry.card(cid).health, 9))

    def test_native_undead_and_pirate_rewards_match_only_original_own_entries(self):
        for root, child in ((DEALER, ZOMBIE), (DISTRIBUTOR, PIRATE)):
            g = self.game((child, RAVEN), board=(root,)); target = self.play(g, child); self.play(g, RAVEN)
            self.assertEqual(g.state.entities[target].attack, g.registry.card(child).attack+1)
            self.assertEqual(self.entity(g, RAVEN, zone='board').attack, 2)
            self.assertEqual(self.entity(g, root, zone='board').attack, 1)
            g = self.game(board=(root,), enemy_hand=(child,), active=2); target = self.play(g, child, player=2)
            self.assertEqual(g.state.entities[target].attack, g.registry.card(child).attack)

    def test_chirurgeon_adds_health_to_own_original_minion_not_itself_or_opponent(self):
        g = self.game((YETI,), board=(CHIRURGEON,)); source = self.play(g, YETI)
        self.assertEqual((g.state.entities[source].health, g.state.entities[source].max_health), (6, 6))
        self.assertEqual(self.entity(g, CHIRURGEON, zone='board').health, 2)
        g = self.game(board=(CHIRURGEON,), enemy_hand=(YETI,), active=2); source = self.play(g, YETI, player=2)
        self.assertEqual(g.state.entities[source].health, 5)

    def test_tribal_reward_uses_granted_entry_tribes_and_all_tribes(self):
        g = self.game((HAND_UNDEAD, YETI), board=(DEALER,)); self.play(g, HAND_UNDEAD); source = self.play(g, YETI)
        self.assertEqual(g.state.entities[source].attack, 5)
        g = self.game((ALL,), board=(DEALER, DISTRIBUTOR)); source = self.play(g, ALL)
        self.assertEqual(g.state.entities[source].attack, g.registry.card(ALL).attack+2)

    def test_reward_does_not_double_apply_to_later_residence_of_same_summoned_entity(self):
        g = self.game((YETI,), board=(CHIRURGEON,), mode='reenter'); source = self.play(g, YETI)
        self.assertEqual(g.state.entities[source].health, 6)
        rows = [r for r in g.state.successful_summon_history if r.entity_id == source]
        self.assertEqual(len(rows), 2); self.assertNotEqual(rows[0].minion.entered_order, rows[1].minion.entered_order)
        self.portable(g)

    def test_unknown_original_current_tribes_fail_instead_of_silently_excluding_the_minion(self):
        g = self.game((UNKNOWN,), board=(DEALER,)); before = g.snapshot()
        with self.assertRaises(ResolutionError) as caught: self.play(g, UNKNOWN)
        self.assertIsInstance(caught.exception.__cause__, UnsupportedDefinitionError)
        self.assertEqual(g.snapshot(), before)

    def test_zealot_counts_real_other_own_entries_including_effect_summons(self):
        g = self.game((YETI, SUMMON_YETI), board=(ZEALOT,)); self.play(g, YETI); self.play(g, SUMMON_YETI)
        self.assertEqual(self.entity(g, ZEALOT, zone='board').attack, 4)
        g = self.game(board=(ZEALOT,), enemy_hand=(YETI,), active=2); self.play(g, YETI, player=2)
        self.assertEqual(self.entity(g, ZEALOT, zone='board').attack, 2)

    def test_piranhas_grow_only_other_original_piranhas_and_use_real_rush(self):
        g = self.game((PIRANHA, PIRANHA), enemy_board=(RAVEN,)); first = self.play(g, PIRANHA); before = g.snapshot()
        with self.assertRaises(IllegalAction): g.apply(Attack(1, first, g.state.players[2].hero_id))
        self.assertEqual(g.snapshot(), before); second = self.play(g, PIRANHA)
        self.assertEqual((g.state.entities[first].attack, g.state.entities[second].attack), (2, 1))
        target = self.entity(g, RAVEN, 2, 'board').id; g.apply(Attack(1, first, target))
        self.assertEqual(g.state.entities[first].zone, Zone.GRAVEYARD); self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)

    def test_healer_natural_death_restores_six_to_current_controllers_enemy_hero(self):
        for taken in (False, True):
            g = self.game((BOTH, HEALER, TAKE, KILL) if taken else (BOTH, HEALER, KILL)); self.play(g, BOTH)
            source = self.play(g, HEALER)
            if taken: self.play(g, TAKE, source)
            self.play(g, KILL, source)
            self.assertEqual((self.health(g), self.health(g, 2)), (30, 24) if taken else (24, 30))

    def test_healer_spellburst_silences_itself_and_removes_the_natural_death_reward(self):
        g = self.game((BOTH, KILL), board=(HEALER,)); self.play(g, BOTH)
        source = self.entity(g, HEALER, zone='board').id
        self.assertFalse(any(a.kind in ('deathrattle', 'limited_trigger') for a in g.state.entities[source].abilities))
        self.play(g, KILL, source); self.assertEqual((self.health(g), self.health(g, 2)), (24, 24))
        self.assertFalse(g.state.deathrattle_history)

    def test_original_countered_spell_still_uses_existing_spellburst_capture_policy(self):
        g = self.game((NOOP,), board=(HEALER,), enemy_hand=(COUNTER,), active=2)
        self.play(g, COUNTER, player=2); g.apply(EndTurn(2)); self.play(g, NOOP)
        self.assertTrue(g.state.play_history[-1].countered)
        self.assertFalse(any(a.kind == 'deathrattle' for a in self.entity(g, HEALER, zone='board').abilities))

    def test_opponent_spells_and_effect_cast_from_minion_do_not_consume_own_spellburst(self):
        g = self.game(board=(HEALER,), enemy_hand=(NOOP,), active=2); self.play(g, NOOP, player=2)
        self.assertIn(Keyword.SPELLBURST, self.entity(g, HEALER, zone='board').keywords)
        g = self.game((AUTO_MINION,), board=(HEALER,)); self.play(g, AUTO_MINION)
        self.assertIn(Keyword.SPELLBURST, self.entity(g, HEALER, zone='board').keywords)

    def test_racer_uses_final_frozen_enemies_and_deals_three_once_without_spell_bonus(self):
        g = self.game((FROZEN, NOOP), board=(RACER, POWER), enemy_board=(RAVEN, YETI)); source = self.entity(g, RACER, zone='board').id
        self.play(g, FROZEN); self.assertEqual(self.health(g, 2), 27)
        self.assertNotIn(RAVEN, self.ids(g, 2, 'board')); self.assertEqual(self.entity(g, YETI, 2, 'board').health, 5)
        self.assertNotIn(Keyword.SPELLBURST, g.state.entities[source].keywords)
        self.play(g, NOOP); self.assertEqual(self.health(g, 2), 27)

    def test_spellburst_created_during_original_spell_waits_for_a_later_hand_spell(self):
        g = self.game((SUMMON_RACER, NOOP)); self.play(g, SUMMON_RACER)
        self.assertEqual(self.health(g, 2), 30); self.assertIn(Keyword.SPELLBURST, self.entity(g, RACER, zone='board').keywords)
        self.play(g, NOOP); self.assertEqual(self.health(g, 2), 27)

    def test_sunfury_own_successful_fire_cast_hits_all_active_minions_once(self):
        g = self.game((FIRE, FROST), board=(SUNFURY, YETI, POWER), enemy_board=(YETI,))
        self.play(g, FIRE)
        self.assertEqual((self.entity(g, SUNFURY, zone='board').health, self.entity(g, YETI, zone='board').health,
            self.entity(g, YETI, 2, 'board').health), (2, 4, 4))
        rows = [r.health_result for r in g.state.damage_history if r.health_result.source_card_id == SUNFURY]
        self.assertEqual(len(rows), 4); self.assertEqual(len({r.batch_id for r in rows}), 1)
        self.play(g, FROST); self.assertEqual(self.entity(g, YETI, zone='board').health, 4)

    def test_sunfury_excludes_countered_fire_and_opponent_fire(self):
        g = self.game((FIRE,), board=(SUNFURY,), enemy_hand=(COUNTER,), active=2)
        self.play(g, COUNTER, player=2); g.apply(EndTurn(2)); self.play(g, FIRE)
        self.assertTrue(g.state.play_history[-1].countered); self.assertEqual(self.entity(g, SUNFURY, zone='board').health, 3)
        g = self.game(board=(SUNFURY,), enemy_hand=(FIRE,), active=2); self.play(g, FIRE, player=2)
        self.assertEqual(self.entity(g, SUNFURY, zone='board').health, 3)

    def test_sunfury_includes_real_successful_automatic_fire_cast(self):
        g = self.game((AUTO_FIRE_MINION,), board=(SUNFURY, YETI)); source = self.play(g, AUTO_FIRE_MINION)
        self.assertEqual((g.state.entities[source].health, self.entity(g, SUNFURY, zone='board').health,
            self.entity(g, YETI, zone='board').health), (4, 2, 4))

    def test_bubbler_uses_exact_settled_damage_and_has_one_natural_death(self):
        for spell, health in ((ZERO, 4), (ONE, None), (TWO, 2), (FOUR, None)):
            g = self.game((spell,), board=(BUBBLER,)); source = self.entity(g, BUBBLER, zone='board').id
            self.play(g, spell, source)
            if health is None:
                self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD); self.assertEqual(len(g.state.death_history), 1)
            else: self.assertEqual(g.state.entities[source].health, health); self.assertFalse(g.state.death_history)

    def test_bubbler_shield_prevents_the_exact_one_damage_condition(self):
        g = self.game((SHIELD, ONE), board=(BUBBLER,)); source = self.entity(g, BUBBLER, zone='board').id
        self.play(g, SHIELD, source); self.play(g, ONE, source)
        self.assertEqual(g.state.entities[source].health, 4); self.assertFalse(g.state.death_history)

    def test_bubbler_ignores_unrelated_zero_damage_notification_without_settled_payload(self):
        g = self.game((ZERO,), board=(BUBBLER,), enemy_board=(YETI,))
        self.play(g, ZERO, self.entity(g, YETI, 2, 'board').id)
        self.assertEqual(self.entity(g, BUBBLER, zone='board').health, 4)
        self.assertEqual(self.entity(g, YETI, 2, 'board').health, 5); self.assertFalse(g.state.death_history)

    def test_bubbler_original_one_damage_trigger_does_not_destroy_reentered_same_entity(self):
        g = self.game((ONE,), board=(BUBBLER,), mode='reenter_bubbler'); source = self.entity(g, BUBBLER, zone='board').id
        self.play(g, ONE, source)
        self.assertEqual((g.state.entities[source].zone, g.state.entities[source].health), (Zone.BOARD, 4))
        self.assertFalse(g.state.death_history); self.portable(g)

    def test_banshee_selects_one_physical_current_undead_including_all_tribes(self):
        g = self.game((KILL,), board=(BANSHEE, ZOMBIE, ZOMBIE, ALL, DORMANT), enemy_board=(ZOMBIE,))
        source = self.entity(g, BANSHEE, zone='board').id
        candidates = [i for i in g.state.players[1].board if g.state.entities[i].card_id in (ZOMBIE, ALL)]
        random = Random(); random.setstate(g._rng.getstate()); chosen = random.choice(candidates)
        prior = {i: (g.state.entities[i].attack, g.state.entities[i].health) for i in candidates}
        self.play(g, KILL, source)
        for i in candidates:
            a, h = prior[i]; self.assertEqual((g.state.entities[i].attack, g.state.entities[i].health), (a+2, h+1) if i == chosen else (a, h))
        self.assertEqual(g._rng.getstate(), random.getstate())
        self.assertEqual(self.entity(g, ZOMBIE, 2, 'board').attack, 2)

    def test_banshee_current_granted_tribe_matches_and_unknown_tribes_fail_atomically(self):
        g = self.game((BOARD_UNDEAD, KILL), board=(BANSHEE, RAVEN)); target = self.entity(g, RAVEN, zone='board').id
        self.play(g, BOARD_UNDEAD, target); self.play(g, KILL, self.entity(g, BANSHEE, zone='board').id)
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].health), (4, 3))
        g = self.game((KILL,), board=(BANSHEE, UNKNOWN)); before = g.snapshot()
        with self.assertRaises(ResolutionError) as caught: self.play(g, KILL, self.entity(g, BANSHEE, zone='board').id)
        self.assertIsInstance(caught.exception.__cause__, UnsupportedDefinitionError)
        self.assertEqual(g.snapshot(), before)

    def test_banshee_empty_eligible_board_does_not_consume_rng(self):
        g = self.game((KILL,), board=(BANSHEE, RAVEN)); random = g._rng.getstate()
        self.play(g, KILL, self.entity(g, BANSHEE, zone='board').id); self.assertEqual(g._rng.getstate(), random)
        self.assertEqual(self.entity(g, RAVEN, zone='board').attack, 2)

    def test_alive_active_banshee_deathrattle_can_buff_its_own_current_undead_body(self):
        g = self.game((ACTIVE_DR,), board=(BANSHEE,)); source = self.entity(g, BANSHEE, zone='board').id
        self.play(g, ACTIVE_DR, source)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (4, 2))
        self.assertFalse(g.state.death_history)

    def test_two_native_copy_entries_use_physical_enemy_deck_weights_without_removal(self):
        for cid in (CONJURER, ORACLE):
            g = self.game((CONJURER,) if cid == CONJURER else (KILL,), board=() if cid == CONJURER else (ORACLE,),
                enemy_deck=(YETI, YETI, COIN))
            original = tuple(g.state.players[2].deck); random = Random(); random.setstate(g._rng.getstate()); chosen = random.choice(original)
            self.play(g, CONJURER) if cid == CONJURER else self.play(g, KILL, self.entity(g, ORACLE, zone='board').id)
            self.assertEqual(tuple(g.state.players[2].deck), original); self.assertEqual(len(g.state.players[1].hand), 1)
            copied = g.state.entities[g.state.players[1].hand[0]]
            self.assertEqual(copied.card_id, g.state.entities[chosen].card_id); self.assertEqual(copied.origin_entity_id, chosen)
            self.assertNotEqual(copied.id, chosen); self.assertEqual(g._rng.getstate(), random.getstate())

    def test_enemy_deck_copy_preserves_current_material_and_cost_with_new_owner(self):
        g = self.game((ENHANCE, CONJURER), enemy_deck=(YETI,)); self.play(g, ENHANCE); original = g.state.players[2].deck[0]
        self.play(g, CONJURER); copied = self.entity(g, YETI)
        self.assertEqual((copied.attack, copied.health, copied.cost, copied.owner, copied.controller), (6, 6, 1, 1, 1))
        self.assertEqual(g.state.players[2].deck, [original]); self.portable(g)

    def test_copied_real_spell_can_be_paid_and_cast_from_new_hand(self):
        g = self.game((CONJURER,), enemy_deck=(FIREBALL,)); self.play(g, CONJURER); self.play(g, FIREBALL, g.state.players[2].hero_id)
        self.assertEqual((self.health(g, 2), g.state.players[1].mana), (24, 5))

    def test_empty_enemy_deck_copy_skips_without_rng_or_fatigue(self):
        for cid in (CONJURER, ORACLE):
            g = self.game((CONJURER,) if cid == CONJURER else (KILL,), board=() if cid == CONJURER else (ORACLE,)); random = g._rng.getstate()
            self.play(g, CONJURER) if cid == CONJURER else self.play(g, KILL, self.entity(g, ORACLE, zone='board').id)
            self.assertFalse(g.state.players[1].hand); self.assertEqual(g._rng.getstate(), random)
            self.assertEqual(g.state.players[1].fatigue, 0)

    def test_full_hand_oracle_copy_burns_new_copy_and_retains_original_enemy_deck(self):
        g = self.game((NOOP,)*10, board=(ORACLE,), enemy_hand=(KILL,), enemy_deck=(YETI,), active=2)
        original = tuple(g.state.players[2].deck); self.play(g, KILL, self.entity(g, ORACLE, zone='board').id, 2)
        copies = [e for e in g.state.entities.values() if e.card_id == YETI and e.owner == 1]
        self.assertEqual(len(copies), 1); self.assertEqual(copies[0].zone, Zone.GRAVEYARD)
        self.assertEqual(tuple(g.state.players[2].deck), original); self.assertEqual(len(g.state.players[1].hand), 10)

    def test_silenced_oracle_has_no_natural_copy(self):
        g = self.game((SILENCE, KILL), board=(ORACLE,), enemy_deck=(YETI,)); source = self.entity(g, ORACLE, zone='board').id
        self.play(g, SILENCE, source); random = g._rng.getstate(); self.play(g, KILL, source)
        self.assertFalse(g.state.players[1].hand); self.assertEqual(g._rng.getstate(), random)

    def test_entry_reward_wait_restores_original_recipient_and_failed_selection(self):
        g = self.game((YETI,), board=(CHIRURGEON,), mode='wait_entry'); source = self.play(g, YETI)
        self.assertIsNotNone(g.state.pending_choice); g = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before); self.choose(g)
        self.assertEqual((g.state.entities[source].health, g.state.players[1].mana), (6, 6))

    def test_random_death_reward_wait_restores_original_selection_without_redraw(self):
        g = self.game((KILL,), board=(BANSHEE, ZOMBIE, ALL), mode='wait_random')
        self.play(g, KILL, self.entity(g, BANSHEE, zone='board').id)
        self.assertIsNotNone(g.state.pending_choice); rng = g._rng.getstate(); g = self.portable(g); self.choose(g)
        self.assertEqual(g._rng.getstate(), rng)
        bonuses = [g.state.entities[i].attack-g.registry.card(g.state.entities[i].card_id).attack for i in g.state.players[1].board]
        self.assertEqual(sorted(bonuses), [0, 2])

    def test_private_copy_delivery_wait_restores_material_and_rng_without_another_copy(self):
        g = self.game((CONJURER,), enemy_deck=(YETI, RAVEN), mode='wait_copy'); self.play(g, CONJURER)
        self.assertIsNotNone(g.state.pending_choice); rng = g._rng.getstate(); g = self.portable(g); self.choose(g)
        self.assertEqual(g._rng.getstate(), rng); self.assertEqual(len(g.state.players[1].hand), 1)
        other_hand = g.observe(2)['players'][0]['hand']; self.assertEqual(len(other_hand), 1)
        self.assertIsNone(other_hand[0]['card_id'])

    def test_spellburst_damage_wait_restores_once_only_budget_and_simultaneous_batch(self):
        g = self.game((FROZEN,), board=(RACER,), enemy_board=(RAVEN,), mode='wait_burst'); self.play(g, FROZEN)
        self.assertIsNotNone(g.state.pending_choice); g = self.portable(g)
        waits = 0
        while g.state.pending_choice is not None:
            waits += 1; self.assertLessEqual(waits, 2); self.choose(g)
        self.assertEqual(self.health(g, 2), 27); self.assertNotIn(Keyword.SPELLBURST, self.entity(g, RACER, zone='board').keywords)
        self.assertFalse(g.state.players[2].board)

    def test_late_entry_random_copy_and_fire_failures_restore_whole_real_action(self):
        cases = (((CHIRURGEON,), YETI, (), ()), ((BANSHEE, ZOMBIE), KILL, (), ()),
            ((), CONJURER, (), (YETI,)), ((SUNFURY, YETI), FIRE, (), ()), ((RACER,), FROZEN, (RAVEN,), ()))
        for board, card, enemy_board, enemy_deck in cases:
            g = self.game((card,), board=board, enemy_board=enemy_board, enemy_deck=enemy_deck, mode='fail'); before = g.snapshot()
            target = self.entity(g, BANSHEE, zone='board').id if card == KILL else None
            with self.assertRaises(ResolutionError): self.play(g, card, target)
            self.assertEqual(g.snapshot(), before)

    def test_late_actual_healer_death_reaction_failure_restores_original_death_and_health(self):
        g = self.game((BOTH, HEALER, KILL), mode='fail'); self.play(g, BOTH); source = self.play(g, HEALER)
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, KILL, source)
        self.assertEqual(g.snapshot(), before)

    def test_actual_flashback_uses_complete_fixture_members_without_summoned_battlecries(self):
        g = self.game((FLASHBACK,)); self.play(g, FLASHBACK); row, = g.state.pool_summon_history
        self.assertEqual({x.card_id for x in row.spec.basis.candidates}, set(LEAVES))
        self.assertEqual(len(g.state.players[1].board), 2); self.assertFalse(g.state.battlecry_history)
        self.assertFalse(g.state.players[1].hand); self.assertEqual((self.health(g), self.health(g, 2)), (30, 30))

    def test_leaves_are_not_standard_roots_or_a_fabricated_production_generation_domain(self):
        from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format
        r = build_registry(); self.assertNotIn('constructed.past.cards', r.pools); self.assertNotIn('constructed.cards', r.pools)
        self.assertFalse(set(LEAVES) & set(build_cn37_launch_candidate_format().root_card_ids))


if __name__ == '__main__':
    unittest.main()
