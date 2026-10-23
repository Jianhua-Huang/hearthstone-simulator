from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_one_cost_event_condition_cards import (
    BERSERKER, BUCCANEER, CORPSE, DECKHAND, LEAVES, SECRETKEEPER, SINGER, SKIPPER,
    SOLOIST, TAR, TEMPEST, TOXFIN, UNDERTAKER, WOLF, load_batch,
)
from hs_sim.engine import Attack, CardDefinition, CardType, CastSpell, EndTurn, Game, IllegalAction, Keyword, PlayerSetup, Scenario, TargetSpec, TriggerSpec, UseHeroPower, Zone
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (
    Buff, ChangeControl, ChoiceOption, Destroy, EquipWeapon, InvokeBehavior, ModifyWeapon, Overload,
    RequestChoice, ReturnToHand, SetStats, Silence, Summon, UnlockOverload,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CostSpec, EquippedWeaponReference, TargetMode, TribeChangeSpec
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from tools import card_batch as batch


P = 'test.k462.'
NOOP, KILL, SILENCE, EQUIP, WEAR, OVERLOAD, CLEAR, GROW, TAKE, BEAST, MURLOCIZE, STRIP, COST, LOW, SUMMON_DR, SUMMON_YETI, AUTO, FAIL, WATCH, REENTER, POWER, SELF_DESTRUCT = (
    P + s for s in ('noop', 'kill', 'silence', 'equip', 'wear', 'overload', 'clear', 'grow', 'take', 'beast',
        'murlocize', 'strip', 'cost', 'low', 'summon_dr', 'summon_yeti', 'auto', 'fail', 'watch', 'reenter', 'power', 'self_destruct'))
YETI, RAVEN, MURLOC, ALL, DR, SECRET, SECRET2, AXE, DORMANT, LOCATION, FLASHBACK = (
    'CORE_CS2_182', 'KAR_300', 'CORE_EX1_509', 'NX2_050', 'DAL_354', 'CORE_EX1_287', 'CORE_EX1_289',
    'CS2_106', 'BT_009', 'CORE_REV_990', 'TIME_711')
CONTEXT = GenerationContext('k462-explicit-event-condition-leaves', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry()
    r.register_pool(PoolDefinition('constructed.past.cards', 'thirteen-explicit-leaves-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid) for cid in LEAVES), complete=True))

    def tribes(c, values):
        return (ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),
            TribeChangeSpec('set', values), c.source_id),)

    def cost(c):
        target = next(c.state.entities[i] for i in c.state.players[c.player_id].deck
            if Keyword.SECRET in r.card(c.state.entities[i].card_id).keywords)
        return (ModifyStoredCost(CardReference.capture(target), CostSpec(set_to=0), c.source_id),)

    def fail(c):
        raise ResolutionError('K462 deliberate late listener failure')

    bodies = {
        NOOP: lambda c: (), KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        SILENCE: lambda c: (Silence(c.target_id),), EQUIP: lambda c: (EquipWeapon(c.player_id, AXE),),
        WEAR: lambda c: (ModifyWeapon(EquippedWeaponReference.capture(c.state.entities[c.state.players[c.player_id].weapon_id]),
            durability=-2, source_id=c.source_id),),
        OVERLOAD: lambda c: (Overload(c.player_id, 1),), CLEAR: lambda c: (UnlockOverload(c.player_id),),
        GROW: lambda c: (Buff(c.target_id, attack=3, source_id=c.source_id),),
        TAKE: lambda c: (ChangeControl(c.target_id, 2),), BEAST: lambda c: tribes(c, ('beast',)),
        MURLOCIZE: lambda c: tribes(c, ('murloc',)), STRIP: lambda c: tribes(c, ()), COST: cost,
        LOW: lambda c: tuple(SetStats(c.state.players[p].hero_id, health=2, source_id=c.source_id) for p in (1, 2)),
        SUMMON_DR: lambda c: (Summon(c.player_id, DR),), SUMMON_YETI: lambda c: (Summon(c.player_id, YETI),),
        AUTO: lambda c: (CastSpell(c.player_id, SECRET2, c.source_id, targeting='explicit'),), FAIL: fail,
        REENTER: lambda c: (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id),),
        SELF_DESTRUCT: lambda c: (Destroy(c.source_id, c.source_id),),
    }
    targeted = (KILL, SILENCE, GROW, TAKE, BEAST, MURLOCIZE, STRIP)
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        if cid not in (REENTER, SELF_DESTRUCT):
            r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
                targeting=TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,)) if cid in targeted else None))
    r.register_card(CardDefinition(POWER, POWER, CardType.MINION, health=5, spell_damage=5))
    r.register_card(CardDefinition(SELF_DESTRUCT, SELF_DESTRUCT, CardType.MINION, attack=1, health=1, battlecry=SELF_DESTRUCT))

    def watch(c):
        e = c.event
        if mode == 'reenter' and e.kind == 'card_played':
            row = play_record(c.state, dict(e.data)['play_id'])
            if row.player_id == c.player_id and row.card_id == YETI:
                return (ReturnToHand(row.source_id), InvokeBehavior(REENTER, c.source_id, c.player_id, row.source_id))
        if mode == 'silence_entry' and e.kind == 'minion_summoned' and c.state.entities[e.target_id].card_id == DR:
            return (Silence(e.target_id),)
        source = c.state.entities.get(e.source_id)
        cid = None if source is None else source.card_id
        reward = (e.kind == 'damage_dealt' and e.amount > 0 and cid in (BERSERKER, SKIPPER, CORPSE) or
            e.kind == 'stats_changed' and cid in (SECRETKEEPER, UNDERTAKER) or
            e.kind == 'card_drawn' and cid == SINGER or e.kind == 'card_added_to_hand' and cid == SOLOIST)
        if mode == 'fail' and reward: return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        if mode == 'wait' and reward:
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
        return ()

    behavior = WATCH + '.' + mode
    r.register_behavior(behavior, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.WEAPON, attack=0, durability=50,
        triggers=tuple(TriggerSpec(e, behavior) for e in ('card_played', 'minion_summoned', 'damage_dealt',
            'stats_changed', 'card_drawn', 'card_added_to_hand')) if mode != 'normal' else ()))
    r.validate()
    return r


class PastOneCostEventConditionTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), board=(), *, enemy_hand=(), enemy_board=(), deck=(), enemy_deck=(NOOP,)*4,
             weapon=None, active=1, mode='normal'):
        self.mode = mode
        assert mode == 'normal' or weapon is None
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
                weapon_card_id=WATCH if mode != 'normal' else weapon,
                hero_power_card_id='HERO_08bp', mana=10, max_mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board, deck=enemy_deck,
                hero_power_card_id='HERO_08bp', mana=10, max_mana=10)),
            active_player=active, seed=462, generation_context=CONTEXT), fixture(mode))

    def ids(self, g, player=1, zone='hand'):
        return tuple(g.state.entities[i].card_id for i in getattr(g.state.players[player], zone))

    def health(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].health

    def test_thirteen_complete_raw_records_twenty_six_primary_faces_and_explicit_zero(self):
        data = load_batch(); rows = {x['record']['id']: x['record'] for x in data['dependencies']}; hashes = {}
        self.assertEqual((len(rows), len(data['official_observations'])), (13, 26))
        for o in data['official_observations']:
            if o['response_file'] not in hashes: hashes[o['response_file']] = batch.sha(Path(o['response_file']))
            self.assertEqual(hashes[o['response_file']], o['response_sha256'])
            batch.check_face(rows[o['card_id']], o['face'], o['locale'], numeric_normalizations=data['numeric_normalizations'].get(o['card_id']))
        self.assertIsNone(rows[TAR]['attack']); self.assertNotIn('ATK', rows[TAR]['tags'])
        self.assertEqual(fixture().card(TAR).attack, 0)
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_all_thirteen_real_hand_entries_pay_once(self):
        for cid in LEAVES:
            with self.subTest(card=cid):
                g = self.game((cid,)); source = self.play(g, cid, g.state.players[2].hero_id if cid == CORPSE else None)
                self.assertEqual(g.state.players[1].mana, 9)
                self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health),
                    (g.registry.card(cid).attack, g.registry.card(cid).health))
                self.assertEqual(len(g.state.play_history), 1)

    def test_secretkeeper_counts_both_players_original_secret_plays_including_countered(self):
        g = self.game((SECRET,), board=(SECRETKEEPER,), enemy_hand=(SECRET2,)); source = self.entity(g, SECRETKEEPER, zone='board').id
        self.play(g, SECRET); self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (2, 3))
        g.apply(EndTurn(1)); self.play(g, SECRET2, player=2)
        self.assertTrue(g.state.play_history[-1].countered)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (3, 4))

    def test_secretkeeper_ignores_nonsecret_power_and_effect_cast_secret(self):
        g = self.game((NOOP, AUTO), board=(SECRETKEEPER,)); source = self.entity(g, SECRETKEEPER, zone='board').id
        self.play(g, NOOP); self.play(g, AUTO)
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id, target_id=g.state.players[2].hero_id))
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (1, 2))
        self.assertTrue(g.state.players[1].secrets)

    def test_undertaker_counts_actual_own_deathrattle_entries_not_other_minions(self):
        g = self.game((DR, RAVEN), board=(UNDERTAKER,)); source = self.entity(g, UNDERTAKER, zone='board').id
        self.play(g, DR); self.play(g, RAVEN)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (2, 3))

    def test_undertaker_accepts_ordinary_summon_and_excludes_enemy_entry(self):
        g = self.game((SUMMON_DR,), board=(UNDERTAKER,)); source = self.entity(g, UNDERTAKER, zone='board').id
        self.play(g, SUMMON_DR); self.assertEqual(g.state.entities[source].attack, 2)
        g = self.game(board=(UNDERTAKER,), enemy_hand=(DR,), active=2); self.play(g, DR, player=2)
        self.assertEqual(self.entity(g, UNDERTAKER, zone='board').attack, 1)

    def test_undertaker_uses_original_frozen_deathrattle_fact_after_prior_silence(self):
        g = self.game((DR,), board=(UNDERTAKER,), mode='silence_entry'); source = self.play(g, DR)
        self.assertFalse(any(a.kind == 'deathrattle' for a in g.state.entities[source].abilities))
        self.assertEqual(self.entity(g, UNDERTAKER, zone='board').attack, 2)

    def test_berserker_damages_only_original_own_paid_minion_by_one_without_spell_bonus(self):
        g = self.game((YETI,), board=(BERSERKER, POWER)); source = self.play(g, YETI)
        self.assertEqual(g.state.entities[source].health, 4)
        self.assertEqual(self.entity(g, BERSERKER, zone='board').health, 3)

    def test_berserker_ignores_ordinary_summon_enemy_play_and_its_own_entry(self):
        g = self.game((SUMMON_YETI,), board=(BERSERKER,)); self.play(g, SUMMON_YETI)
        self.assertEqual(self.entity(g, YETI, zone='board').health, 5)
        g = self.game(board=(BERSERKER,), enemy_hand=(YETI,), active=2); source = self.play(g, YETI, player=2)
        self.assertEqual(g.state.entities[source].health, 5)
        g = self.game((BERSERKER,)); source = self.play(g, BERSERKER); self.assertEqual(g.state.entities[source].health, 3)

    def test_berserker_does_not_damage_later_residence_of_same_played_entity(self):
        g = self.game((YETI,), board=(BERSERKER,), mode='reenter'); source = self.play(g, YETI)
        self.assertEqual(g.state.entities[source].health, 5)
        entries = [r for r in g.state.successful_summon_history if r.entity_id == source]
        self.assertEqual(len(entries), 2); self.assertNotEqual(entries[0].minion.entered_order, entries[1].minion.entered_order)
        self.portable(g)

    def test_skipper_one_simultaneous_nonspell_batch_hits_both_sides_but_not_dormant_or_location(self):
        g = self.game((RAVEN,), board=(SKIPPER, YETI, DORMANT, LOCATION), enemy_board=(YETI,))
        source = self.play(g, RAVEN)
        self.assertEqual(g.state.entities[source].health, 1)
        self.assertEqual(self.entity(g, SKIPPER, zone='board').health, 2)
        self.assertEqual(self.entity(g, YETI, zone='board').health, 4)
        self.assertEqual(self.entity(g, YETI, 2, 'board').health, 4)
        self.assertEqual(self.entity(g, DORMANT, zone='board').health, g.registry.card(DORMANT).health)
        rows = [r.health_result for r in g.state.damage_history if r.health_result.source_card_id == SKIPPER]
        self.assertEqual(len(rows), 4); self.assertEqual(len({r.batch_id for r in rows}), 1)

    def test_skipper_own_entry_and_ordinary_summon_are_not_paid_other_minions(self):
        g = self.game((SKIPPER, SUMMON_YETI)); source = self.play(g, SKIPPER); self.play(g, SUMMON_YETI)
        self.assertEqual(g.state.entities[source].health, 3); self.assertEqual(self.entity(g, YETI, zone='board').health, 5)

    def test_skipper_still_fires_when_played_minion_dies_during_its_battlecry(self):
        g = self.game((SELF_DESTRUCT,), board=(SKIPPER,), enemy_board=(YETI,)); self.play(g, SELF_DESTRUCT)
        self.assertEqual(self.entity(g, SKIPPER, zone='board').health, 2)
        self.assertEqual(self.entity(g, YETI, 2, 'board').health, 4)

    def test_singer_draws_original_physical_secret_despite_changed_current_cost(self):
        g = self.game((COST,), board=(SINGER,), deck=(NOOP, SECRET2, SECRET)); target = g.state.players[1].deck[1]
        self.play(g, COST); g.apply(EndTurn(1))
        self.assertEqual(self.ids(g), (SECRET2,)); self.assertEqual(g.state.players[1].hand[0], target)
        self.assertEqual(g.state.entities[target].cost, 0); self.assertEqual(self.ids(g, zone='deck'), (NOOP, SECRET))

    def test_singer_empty_matching_pool_does_not_fatigue_and_opponent_end_does_not_trigger(self):
        g = self.game(board=(SINGER,), deck=(NOOP, NOOP)); rng = g._rng.getstate()
        g.apply(EndTurn(1)); self.assertFalse(g.state.players[1].hand); self.assertEqual(g.state.players[1].fatigue, 0)
        g.apply(EndTurn(2)); self.assertEqual(self.ids(g), (NOOP,))
        self.assertEqual(g._rng.getstate(), rng)

    def test_singer_full_hand_burns_exactly_the_selected_physical_secret(self):
        g = self.game((NOOP,)*10, board=(SINGER,), deck=(SECRET, NOOP)); target = g.state.players[1].deck[0]
        g.apply(EndTurn(1)); self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand), 10); self.assertEqual(self.ids(g, zone='deck'), (NOOP,))

    def test_soloist_counts_dormant_other_minion_but_not_location(self):
        for board, copies in (((), 1), ((LOCATION,), 1), ((DORMANT,), 0), ((RAVEN,), 0)):
            g = self.game((SOLOIST,), board=board); self.play(g, SOLOIST)
            self.assertEqual(self.ids(g), (SOLOIST,)*copies)

    def test_soloist_named_copy_can_be_played_but_existing_original_prevents_another(self):
        g = self.game((SOLOIST,)); original = self.play(g, SOLOIST); second = self.play(g, SOLOIST)
        self.assertNotEqual(original, second); self.assertFalse(g.state.players[1].hand)
        self.assertEqual(g.state.players[1].mana, 8)

    def test_toxfin_current_friendly_murloc_rule_and_poisonous_combat_use_existing_engine(self):
        g = self.game((TOXFIN,), board=(MURLOC,), enemy_board=(YETI, MURLOC)); target = self.entity(g, MURLOC, zone='board').id
        before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, TOXFIN, self.entity(g, MURLOC, 2, 'board').id)
        self.assertEqual(g.snapshot(), before); self.play(g, TOXFIN, target)
        victim = self.entity(g, YETI, 2, 'board').id; g.apply(Attack(1, target, victim))
        self.assertEqual(g.state.entities[victim].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)

    def test_toxfin_accepts_granted_current_tribe_and_all_tribes_and_empty_has_no_arrow(self):
        for cid in (YETI, ALL):
            g = self.game((MURLOCIZE, TOXFIN) if cid == YETI else (TOXFIN,), board=(cid,)); target = self.entity(g, cid, zone='board').id
            if cid == YETI: self.play(g, MURLOCIZE, target)
            self.play(g, TOXFIN, target); self.assertIn(Keyword.POISONOUS, g.state.entities[target].keywords)
        g = self.game((TOXFIN,)); source = self.play(g, TOXFIN); self.assertNotIn(Keyword.POISONOUS, g.state.entities[source].keywords)

    def test_corpse_enemy_target_and_self_share_one_nonspell_damage_batch(self):
        g = self.game((CORPSE,), board=(POWER,), enemy_board=(YETI,)); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, CORPSE, g.state.players[1].hero_id)
        self.assertEqual(g.snapshot(), before); source = self.play(g, CORPSE, self.entity(g, YETI, 2, 'board').id)
        self.assertEqual((self.entity(g, YETI, 2, 'board').health, self.health(g)), (3, 28))
        rows = [r.health_result for r in g.state.damage_history if r.health_result.source_id == source]
        self.assertEqual(len(rows), 2); self.assertEqual(rows[0].batch_id, rows[1].batch_id)

    def test_corpse_simultaneous_lethal_hero_packets_are_a_draw(self):
        g = self.game((LOW, CORPSE)); self.play(g, LOW); self.play(g, CORPSE, g.state.players[2].hero_id)
        self.assertEqual((self.health(g), self.health(g, 2)), (0, 0)); self.assertIsNone(g.state.winner); self.portable(g)

    def test_tar_opponent_turn_bonus_preserves_ordinary_buff_and_tracks_controller(self):
        g = self.game((GROW,), board=(TAR,), deck=(NOOP, NOOP)); source = self.entity(g, TAR, zone='board').id
        self.play(g, GROW, source); self.assertEqual(g.state.entities[source].attack, 3)
        g.apply(EndTurn(1)); self.assertEqual(g.state.entities[source].attack, 5)
        g.apply(EndTurn(2)); self.assertEqual(g.state.entities[source].attack, 3)
        g = self.game((TAKE,), board=(TAR,)); source = self.entity(g, TAR, zone='board').id
        self.play(g, TAKE, source); self.assertEqual(g.state.entities[source].attack, 2)

    def test_buccaneer_weapon_presence_refreshes_after_equip_removal_and_silence(self):
        g = self.game((EQUIP, WEAR), board=(BUCCANEER,)); source = self.entity(g, BUCCANEER, zone='board').id
        self.assertEqual(g.state.entities[source].attack, 1); self.play(g, EQUIP); self.assertEqual(g.state.entities[source].attack, 3)
        self.play(g, WEAR); self.assertEqual(g.state.entities[source].attack, 1)
        g = self.game((SILENCE,), board=(BUCCANEER,), weapon=AXE); source = self.entity(g, BUCCANEER, zone='board').id
        self.play(g, SILENCE, source); self.assertEqual(g.state.entities[source].attack, 1)

    def test_deckhand_conditional_charge_changes_real_same_turn_hero_attack_permission(self):
        g = self.game((DECKHAND, EQUIP, WEAR)); source = self.play(g, DECKHAND); before = g.snapshot()
        with self.assertRaises(IllegalAction): g.apply(Attack(1, source, g.state.players[2].hero_id))
        self.assertEqual(g.snapshot(), before); self.play(g, EQUIP); self.assertIn(Keyword.CHARGE, g.state.entities[source].keywords)
        g.apply(Attack(1, source, g.state.players[2].hero_id)); self.assertEqual(self.health(g, 2), 28)
        self.play(g, WEAR); self.assertNotIn(Keyword.CHARGE, g.state.entities[source].keywords)

    def test_wolf_aura_uses_current_beasts_all_tribes_and_excludes_self_and_opponent(self):
        g = self.game((BEAST, STRIP), board=(WOLF, YETI, RAVEN, ALL), enemy_board=(RAVEN,))
        self.assertEqual(self.entity(g, WOLF, zone='board').attack, 1)
        self.assertEqual(self.entity(g, RAVEN, zone='board').attack, 3)
        self.assertEqual(self.entity(g, RAVEN, 2, 'board').attack, 2)
        self.assertEqual(self.entity(g, ALL, zone='board').attack, g.registry.card(ALL).attack+1)
        target = self.entity(g, YETI, zone='board').id; self.play(g, BEAST, target); self.assertEqual(g.state.entities[target].attack, 5)
        target = self.entity(g, RAVEN, zone='board').id; self.play(g, STRIP, target); self.assertEqual(g.state.entities[target].attack, 2)

    def test_two_wolf_sources_and_death_silence_remove_only_their_own_contribution(self):
        g = self.game((KILL, SILENCE), board=(WOLF, WOLF, RAVEN)); wolves = list(g.state.players[1].board[:2])
        self.assertEqual([g.state.entities[i].attack for i in wolves], [2, 2]); self.assertEqual(self.entity(g, RAVEN, zone='board').attack, 4)
        self.play(g, KILL, wolves[0]); self.assertEqual(self.entity(g, RAVEN, zone='board').attack, 3)
        self.play(g, SILENCE, wolves[1]); self.assertEqual(self.entity(g, RAVEN, zone='board').attack, 2)

    def test_real_tempest_tracks_original_overload_account_and_restores_with_native_relation(self):
        g = self.game((TEMPEST, OVERLOAD, CLEAR)); source = self.play(g, TEMPEST)
        self.assertEqual(g.state.entities[source].attack, 1); self.play(g, OVERLOAD)
        self.assertEqual(g.state.entities[source].attack, 2); g = self.portable(g); self.play(g, CLEAR)
        self.assertEqual(g.state.entities[source].attack, 1)

    def test_paid_berserker_reward_wait_restores_without_reapplying_damage_or_payment(self):
        g = self.game((YETI,), board=(BERSERKER,), mode='wait'); source = self.play(g, YETI)
        self.assertIsNotNone(g.state.pending_choice); g = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before); self.choose(g)
        self.assertEqual((g.state.entities[source].health, g.state.players[1].mana), (4, 6))

    def test_singer_end_wait_restores_original_draw_and_owner_turn(self):
        g = self.game(board=(SINGER,), deck=(SECRET,), mode='wait'); g.apply(EndTurn(1))
        self.assertIsNotNone(g.state.pending_choice); g = self.portable(g); self.choose(g)
        self.assertEqual(self.ids(g), (SECRET,)); self.assertEqual(g.state.active_player, 2)
        self.assertEqual(sum(r.player_id == 1 for r in g.state.draw_history), 1)

    def test_soloist_delivery_wait_restores_without_another_named_copy(self):
        g = self.game((SOLOIST,), mode='wait'); self.play(g, SOLOIST)
        self.assertIsNotNone(g.state.pending_choice); g = self.portable(g); self.choose(g)
        self.assertEqual(self.ids(g), (SOLOIST,)); self.assertEqual(g.state.players[1].mana, 9)

    def test_late_listener_damage_draw_and_delivery_failures_restore_entire_action(self):
        for board, card, target in (((BERSERKER,), YETI, None), ((SKIPPER,), YETI, None),
                                   ((), CORPSE, 'hero'), ((), SOLOIST, None)):
            g = self.game((card,), board=board, mode='fail'); before = g.snapshot()
            with self.assertRaises(ResolutionError): self.play(g, card, g.state.players[2].hero_id if target else None)
            self.assertEqual(g.snapshot(), before)
        g = self.game(board=(SINGER,), deck=(SECRET,), mode='fail'); before = g.snapshot()
        with self.assertRaises(ResolutionError): g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(), before)

    def test_real_flashback_has_all_explicit_members_and_runs_no_summoned_battlecries(self):
        g = self.game((FLASHBACK,)); self.play(g, FLASHBACK); row, = g.state.pool_summon_history
        self.assertEqual({x.card_id for x in row.spec.basis.candidates}, set(LEAVES))
        self.assertEqual(len(g.state.players[1].board), 2); self.assertFalse(g.state.battlecry_history)
        self.assertEqual((self.health(g), self.health(g, 2)), (30, 30)); self.assertFalse(g.state.players[1].hand)

    def test_leaves_do_not_bind_production_pools_or_become_standard_roots(self):
        from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format
        r = build_registry(); self.assertNotIn('constructed.past.cards', r.pools); self.assertNotIn('constructed.cards', r.pools)
        self.assertFalse(set(LEAVES) & set(build_cn37_launch_candidate_format().root_card_ids))


if __name__ == '__main__':
    unittest.main()
