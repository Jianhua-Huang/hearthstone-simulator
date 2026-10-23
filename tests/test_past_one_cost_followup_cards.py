"""Real historical leaves reuse native entry, death, hand, healing and cost paths."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.past_one_cost_followup_cards import (
    BATCH_PATH, BOMB, CHOW, DECKHAND, DEPENDENCIES, FLYBOOTER, GUITARIST,
    KNIGHT, LEAVES, LEECH, MISSILES, MURMY, PIRATE, PROTECTOR, SPELLWING, SPY,
    VENDOR, load_batch, register_past_one_cost_followup_cards,
)
from hs_sim.engine import (
    Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction, Keyword,
    PlayCard, PlayerSetup, Registry, Scenario, SelectChoice, TargetSpec, TriggerSpec, UseHeroPower, Zone,
)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (
    ChoiceOption, Damage, DamageBatch, Destroy, EquipWeapon, InvokeBehavior, RequestChoice,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind, TargetMode
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face


P = 'k454.'
KILL, HURT, BOTH, EQUIP, FAIL, WATCH, WEAPON, ZERO = (
    P + key for key in ('kill', 'hurt', 'both', 'equip', 'fail', 'watch', 'weapon', 'zero'))
RAVEN, YETI, THALNOS, FLASHBACK = 'KAR_300', 'CORE_CS2_182', 'CORE_EX1_012', 'TIME_711'
CONTEXT = GenerationContext('k454-explicit-twelve-leaf-experiment', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry()
    r.register_pool(PoolDefinition('constructed.past.cards', 'explicit-twelve-leaves-v1',
        CONTEXT.target_id, CONTEXT.mode, tuple(PoolMember(cid) for cid in LEAVES), complete=True))
    r.register_card(CardDefinition(WEAPON, 'Diagnostic weapon', CardType.WEAPON,
        cost=2, attack=2, durability=2))
    r.register_card(CardDefinition(ZERO, 'Diagnostic zero weapon', CardType.WEAPON,
        cost=0, attack=1, durability=1))
    def fail(c):
        raise ResolutionError('K454 deliberate acquisition failure')
    bodies = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        HURT: lambda c: (Damage(c.target_id, 3, c.source_id, DamageKind.EFFECT),),
        BOTH: lambda c: (DamageBatch(tuple(Damage(c.state.players[p].hero_id, 6,
            c.source_id, DamageKind.EFFECT) for p in (1, 2))),),
        EQUIP: lambda c: (EquipWeapon(c.player_id, WEAPON),),
        FAIL: fail,
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            targeting=TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,))
                if cid in (KILL, HURT) else None))
    def watch(c):
        if c.event.player_id != c.player_id or c.state.entities[c.event.target_id].card_id not in (PIRATE, MISSILES):
            return ()
        if mode == 'fail':
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
    watch_behavior = WATCH + '.' + mode
    r.register_behavior(watch_behavior, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=40,
        triggers=(TriggerSpec('card_added_to_hand', watch_behavior),) if mode != 'normal' else ()))
    r.validate()
    return r


class PastOneCostFollowupTests(unittest.TestCase):
    def game(self, hand=(), board=(), *, enemy_hand=(), enemy_board=(), mode='normal', active=1):
        self.mode = mode
        marker = () if mode == 'normal' else (WATCH,)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=marker + board,
                hero_power_card_id='HERO_08bp', mana=10, max_mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board,
                hero_power_card_id='HERO_08bp', mana=10, max_mana=10)),
            active_player=active, seed=454, generation_context=CONTEXT), fixture(mode))

    def play(self, g, cid, target=None, player=1):
        eid = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(player, eid, target))
        return eid

    def choose(self, g, key='continue'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        reader = fixture(self.mode, 'independent-reader')
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(saved, reader).snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for player in (1, 2):
            view = json.dumps(g.for_player(player).observe())
            for private in ('rng_state', 'submitted_cost', 'hand_entry_id', 'resolution_frame'):
                self.assertNotIn(private, view)

    def test_fourteen_full_source_rows_twenty_eight_primary_faces_and_retained_spell(self):
        data = load_batch()
        self.assertEqual((len(data['dependencies']), len(data['existing_dependencies'])), (13, 1))
        self.assertEqual(len(data['official_observations']), 28)
        rows = {i['record']['id']: i['record'] for i in data['dependencies'] + data['existing_dependencies']}
        for observation in data['official_observations']:
            cid = observation['card_id']
            check_face(rows[cid], observation['face'], observation['locale'],
                numeric_normalizations=data['numeric_normalizations'].get(cid))
        old = data['existing_dependencies'][0]
        self.assertEqual(canonical_digest(asdict(fixture().card(MISSILES))), old['definition_sha256'])
        self.assertFalse(data['formal_pool_complete'])
        self.assertFalse(data['cn_calibrated'])

    def test_five_printed_bodies_pay_once_and_keep_original_stats_and_keywords(self):
        cases = ((SPY, 3, 1, {Keyword.STEALTH}), (LEECH, 2, 1, {Keyword.LIFESTEAL}),
            (PROTECTOR, 1, 1, {Keyword.TAUNT, Keyword.DIVINE_SHIELD}),
            (KNIGHT, 1, 1, {Keyword.LIFESTEAL}), (MURMY, 1, 1, {Keyword.REBORN}))
        for cid, attack, health, keywords in cases:
            with self.subTest(card=cid):
                g = self.game((cid,)); eid = self.play(g, cid); entity = g.state.entities[eid]
                self.assertEqual((entity.attack, entity.health, g.state.players[1].mana), (attack, health, 9))
                self.assertTrue(keywords <= entity.keywords)
                self.assertEqual(len(g.state.battlecry_history), 0)

    def test_protector_taunt_and_shield_use_original_combat_rules(self):
        g = self.game(board=(PROTECTOR,), enemy_board=(YETI,), active=2)
        attacker, target = g.state.players[2].board[0], g.state.players[1].board[0]
        saved = g.snapshot()
        with self.assertRaises(IllegalAction):
            g.apply(Attack(2, attacker, g.state.players[1].hero_id))
        self.assertEqual(g.snapshot(), saved)
        g.apply(Attack(2, attacker, target))
        self.assertEqual(g.state.entities[target].health, 1)
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[target].keywords)

    def test_both_lifesteal_sources_heal_actual_damage_even_when_the_attacker_dies(self):
        for cid, amount in ((LEECH, 2), (KNIGHT, 1)):
            with self.subTest(card=cid):
                g = self.game((BOTH,), board=(cid,), enemy_board=(YETI,))
                self.play(g, BOTH)
                hero = g.state.players[1].hero_id
                g.apply(Attack(1, g.state.players[1].board[0], g.state.players[2].board[0]))
                self.assertEqual(g.state.entities[hero].health, 24 + amount)
                self.assertFalse(g.state.players[1].board)

    def test_murmy_reborn_creates_one_new_one_health_body_without_reborn(self):
        g = self.game((MURMY, KILL)); original = self.play(g, MURMY)
        self.play(g, KILL, original)
        self.assertEqual(len(g.state.players[1].board), 1)
        eid = g.state.players[1].board[0]
        self.assertNotEqual(eid, original)
        self.assertEqual((g.state.entities[eid].card_id, g.state.entities[eid].health), (MURMY, 1))
        self.assertNotIn(Keyword.REBORN, g.state.entities[eid].keywords)
        self.portable(g)

    def test_spy_stealth_blocks_enemy_targeting_and_expires_after_its_attack(self):
        g = self.game(board=(SPY,), active=2); eid = g.state.players[1].board[0]
        saved = g.snapshot()
        with self.assertRaises(IllegalAction):
            g.apply(UseHeroPower(2, g.state.players[2].hero_power_id, target_id=eid))
        self.assertEqual(g.snapshot(), saved)
        g.apply(EndTurn(2)); g.apply(Attack(1, eid, g.state.players[2].hero_id))
        self.assertNotIn(Keyword.STEALTH, g.state.entities[eid].keywords)

    def test_bomb_death_deals_two_to_enemy_hero_without_spell_damage(self):
        g = self.game((KILL,), board=(BOMB, THALNOS)); eid = g.state.players[1].board[0]
        self.play(g, KILL, eid)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28)
        self.assertEqual(len(g.state.deathrattle_history), 1)

    def test_chow_death_heals_enemy_hero_five_and_not_its_owner(self):
        g = self.game((BOTH, KILL), board=(CHOW,)); self.play(g, BOTH)
        self.play(g, KILL, g.state.players[1].board[0])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 24)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 29)

    def test_guitarist_modifies_current_weapon_durability_and_empty_slot_skips(self):
        g = self.game((EQUIP, GUITARIST)); self.play(g, EQUIP)
        weapon = g.state.players[1].weapon_id
        self.play(g, GUITARIST)
        self.assertEqual(g.state.players[1].weapon_id, weapon)
        self.assertEqual(g.state.entities[weapon].durability, 3)
        self.assertEqual(g.state.entities[weapon].attack, 2)
        g = self.game((GUITARIST,)); before = g._rng.getstate(); self.play(g, GUITARIST)
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(g._rng.getstate(), before)

    def test_flybooter_creates_two_physical_named_pirates_and_overflow_is_independent(self):
        for extra, count in (((), 2), ((RAVEN,) * 9, 1)):
            with self.subTest(hand=len(extra)):
                g = self.game((FLYBOOTER,) + extra); self.play(g, FLYBOOTER)
                children = [e for e in g.state.entities.values() if e.card_id == PIRATE]
                self.assertEqual(len(children), 2)
                self.assertEqual(sum(e.zone == Zone.HAND for e in children), count)
                self.assertTrue(all((e.attack, e.health, e.cost) == (1, 1, 1) for e in children))

    def test_spellwing_gives_retained_missiles_which_can_really_be_cast(self):
        g = self.game((KILL,), board=(SPELLWING,))
        self.play(g, KILL, g.state.players[1].board[0])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [MISSILES])
        self.play(g, MISSILES)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)
        self.portable(g)

    def test_opponent_killing_spellwing_with_full_owner_hand_burns_only_owners_spell(self):
        g = self.game((RAVEN,) * 10, board=(SPELLWING,), enemy_hand=(KILL,), active=2)
        self.play(g, KILL, g.state.players[1].board[0], player=2)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertFalse(g.state.players[2].hand)
        copies = [e for e in g.state.entities.values() if e.card_id == MISSILES]
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].zone, Zone.GRAVEYARD)

    def test_vendor_heals_all_friendly_characters_two_without_healing_enemies(self):
        g = self.game((BOTH, HURT, VENDOR), board=(YETI,), enemy_board=(YETI,))
        self.play(g, BOTH); ally = g.state.players[1].board[0]; self.play(g, HURT, ally)
        self.play(g, VENDOR)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 26)
        self.assertEqual(g.state.entities[ally].health, 4)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 24)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health, 5)

    def test_next_weapon_discount_ignores_minions_persists_turns_and_is_used_once(self):
        g = self.game((DECKHAND, SPY, WEAPON, WEAPON)); self.play(g, DECKHAND); self.play(g, SPY)
        weapon = g.state.players[1].hand[0]
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[weapon]).amount, 1)
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[weapon]).amount, 1)
        self.play(g, WEAPON)
        other = g.state.players[1].hand[0]
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[other]).amount, 2)

    def test_zero_cost_weapon_still_consumes_next_weapon_discount(self):
        g = self.game((DECKHAND, ZERO, WEAPON)); self.play(g, DECKHAND); self.play(g, ZERO)
        other = g.state.players[1].hand[0]
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[other]).amount, 2)

    def test_two_grants_wait_restore_replay_and_failed_choice_do_not_duplicate_delivery(self):
        g = self.game((FLYBOOTER,), mode='wait'); self.play(g, FLYBOOTER)
        self.assertIsNotNone(g.state.pending_choice); self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g); self.assertIsNotNone(g.state.pending_choice); self.portable(g); self.choose(g)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [PIRATE, PIRATE])
        self.assertTrue(g.state.battlecry_history[-1].completed)

    def test_actual_deathrattle_wait_restores_original_death_and_one_named_grant(self):
        g = self.game((KILL,), board=(SPELLWING,), mode='wait')
        target = next(i for i in g.state.players[1].board if g.state.entities[i].card_id == SPELLWING)
        self.play(g, KILL, target); self.assertIsNotNone(g.state.pending_choice); self.portable(g)
        self.choose(g)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [MISSILES])
        self.assertEqual(len(g.state.deathrattle_history), 1)
        self.assertTrue(g.state.deathrattle_history[0].completed)

    def test_late_acquisition_failure_rolls_back_payment_new_entities_and_entire_play(self):
        g = self.game((FLYBOOTER,), mode='fail'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, FLYBOOTER)
        self.assertEqual(g.snapshot(), saved)

    def test_real_flashback_uses_all_twelve_explicit_fixture_members_without_battlecries(self):
        g = self.game(('GAME_005', FLASHBACK)); self.play(g, 'GAME_005'); self.play(g, FLASHBACK)
        batch, = g.state.pool_summon_history
        self.assertEqual({m.card_id for m in batch.spec.basis.candidates}, set(LEAVES))
        self.assertEqual(len(g.state.players[1].board), 2)
        self.assertFalse(g.state.players[1].hand)
        for eid in g.state.players[1].board:
            entity = g.state.entities[eid]
            self.assertEqual(entity.attack, g.registry.card(entity.card_id).attack + 1)
        self.portable(g)

    def test_leaves_do_not_become_standard_roots_or_a_fabricated_production_past_pool(self):
        f = build_cn37_launch_candidate_format()
        self.assertFalse(set(DEPENDENCIES) & set(f.root_card_ids))
        for domain in ('constructed.past.cards', 'constructed.past.spells'):
            with self.assertRaises(UnsupportedDefinitionError): f.registry.pool(domain, f.context)

    def test_changed_package_or_existing_spell_fails_before_partial_registration(self):
        data = load_batch()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.json'; data['dependencies'][0]['record']['health'] += 1
            path.write_text(json.dumps(data), encoding='utf-8')
            with patch('hs_sim.cards.past_one_cost_followup_cards.BATCH_PATH', path), self.assertRaises(TargetValidationError):
                load_batch()
        r = Registry('k454-dependency-guard')
        r.register_card(replace(fixture().card(MISSILES), cost=2))
        with self.assertRaises(TargetValidationError): register_past_one_cost_followup_cards(r)
        self.assertEqual(set(r.cards), {MISSILES})


if __name__ == '__main__':
    unittest.main()
