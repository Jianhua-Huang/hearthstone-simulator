"""One real Smith, continuous current-weapon Attack and existing kernel paths."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, AuraSpec, CardDefinition, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Registry, ResolutionError, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, DamageBatch, Destroy, EquipWeapon, GainArmor, GrantAura, GrantKeyword, Heal,
    InvokeBehavior, ModifyWeapon, RequestChoice, ReturnToHand, SetStats, Silence, Summon, Transform)
from hs_sim.engine.equipment import total_hero_attack
from hs_sim.engine.model import AbilityInstance
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.stat_auras import weapon_bonuses
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

SMITH = 'CS2_221'
PATH = Path(__file__).resolve().parents[1] / 'data/support/self-damaged-weapon-aura-basics.json'
PIN = 'c3a29cb63a112723aed1c52182a6b343519c806060c7f75770559a5c7ee8f405'
REL = AuraSpec(attack=2, target='friendly_weapon', condition='self_damaged')


def evidence():
    support = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support) != PIN:
        raise ValueError('Complete damaged weapon aura evidence changed')
    for row in support['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Damaged weapon aura raw changed')
    return support['records'][0]['data']


def registry():
    r = Registry('isolated-self-damaged-weapon-aura-basics-v1')
    raw = evidence()
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=80, metadata=metadata()))
    r.register_card(CardDefinition(SMITH, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], auras=(REL,), metadata=metadata(tribes=('undead',))))
    r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, attack=1, health=15, metadata=metadata()))
    r.register_card(CardDefinition('health-aura', 'Existing health support', CardType.MINION, health=5,
        auras=(AuraSpec(0, health=2),), metadata=metadata()))
    # Original equipment fixtures; no additional real representative is needed.
    for cid, attack, durability in (('axe', 3, 2), ('last', 4, 1), ('zero', 0, 2)):
        r.register_card(CardDefinition(cid, cid, CardType.WEAPON, attack=attack,
            durability=durability, metadata=metadata()))

    def quote(c):
        p = c.state.players[c.player_id]
        amount = 0 if p.weapon_id is None else c.state.entities[p.weapon_id].attack
        return (GainArmor(c.player_id, amount),)

    def observed(c):
        if c.event.target_id != c.state.players[c.player_id].board[0]:
            return ()
        return quote(c)

    def waiting(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('hurt', 'Injure', (Damage(c.target_id, 1, c.source_id),)),
            ChoiceOption('fault', 'Injure then fail', (Damage(c.target_id, 1, c.source_id),
                InvokeBehavior('late-fault', source_id=c.source_id, player_id=c.player_id))),
        ), c.source_id),)

    def declared(c):
        p = c.state.players[c.player_id]
        if c.event.source_id != p.hero_id or c.event.player_id != c.player_id:
            return ()
        return (RequestChoice(c.player_id, (ChoiceOption('hurt', 'Injure Smith',
            (Damage(p.board[0], 1, c.source_id),)),), c.source_id),)

    r.register_behavior('quote', quote)
    r.register_behavior('observed', observed)
    r.register_behavior('declared', declared)
    r.register_behavior('late-fault', lambda c: (AddToHand(c.player_id, 'missing.weapon-aura'),))
    r.register_card(CardDefinition('observer', 'Observe saved health context', CardType.MINION, health=5,
        triggers=tuple(TriggerSpec(event, 'observed') for event in ('damage_dealt', 'healed', 'stats_changed')),
        metadata=metadata()))
    r.register_card(CardDefinition('watcher', 'Existing attack window', CardType.MINION, health=5,
        triggers=(TriggerSpec('attack_declared', 'declared'),), metadata=metadata()))
    scripts = {
        'hurt0': lambda c: (Damage(c.target_id, 0, c.source_id),),
        'hurt': lambda c: (Damage(c.target_id, 1, c.source_id),),
        'hurt2': lambda c: (Damage(c.target_id, 2, c.source_id),),
        'heal': lambda c: (Heal(c.target_id, 1, c.source_id),),
        'full': lambda c: (Heal(c.target_id, 30, c.source_id),),
        'shield': lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'copy': lambda c: (CopyMinion(c.target_id, 2),),
        'copybase': lambda c: (CopyMinion(c.target_id, 2, mode='base'),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'away': lambda c: (Transform(c.target_id, 'plain'),),
        'into': lambda c: (Transform(c.target_id, SMITH),),
        'control': lambda c: (ChangeControl(c.target_id, 2),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'hp': lambda c: (Buff(c.target_id, health=2, source_id=c.source_id),),
        'sethp': lambda c: (SetStats(c.target_id, health=4, source_id=c.source_id),),
        'quote-hurt': lambda c: (Damage(c.target_id, 1, c.source_id, on_result='quote'),),
        'quote-full': lambda c: (Heal(c.target_id, 30, c.source_id, on_result='quote'),),
        'batch': lambda c: (DamageBatch((Damage(c.target_id, 1, c.source_id, on_result='quote'),
            Damage(c.target_id, 1, c.source_id, on_result='quote'))),),
        'lethal': lambda c: (Damage(c.target_id, 30, c.source_id, on_result='quote'),),
        'wait': waiting,
        'fault': lambda c: (Damage(c.target_id, 1, c.source_id), AddToHand(c.player_id, 'missing.weapon-aura')),
    }
    untargeted = {
        'equip': lambda c: (EquipWeapon(c.player_id, 'axe'),),
        'equip-last': lambda c: (EquipWeapon(c.player_id, 'last'),),
        'w.plus': lambda c: (ModifyWeapon(c.state.players[c.player_id].weapon_id, attack=1, source_id=c.source_id),),
        'w.minus': lambda c: (ModifyWeapon(c.state.players[c.player_id].weapon_id, attack=-4, source_id=c.source_id),),
        'summon': lambda c: (Summon(c.player_id, SMITH),),
        'sleep': lambda c: (MakeDormant(c.state.players[c.player_id].board[0], None, c.source_id),),
        'awake': lambda c: (AwakenMinion(c.state.players[c.player_id].board[0], c.source_id),),
    }
    for name, body in {**scripts, **untargeted}.items():
        r.register_behavior(name, body)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name,
            requires_target=name not in untargeted, metadata=metadata()))
    return r


class SelfDamagedWeaponAuraBasicsTests(unittest.TestCase):
    def game(self, hand=(), board=(SMITH,), enemy=('plain',), weapon='axe', enemy_weapon=None, enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, weapon_card_id=weapon,
                deck=('plain',) * 5, mana=10, max_mana=10),
            PlayerSetup('hero', hand=enemy_hand, board=enemy, weapon_card_id=enemy_weapon,
                deck=('plain',) * 5, mana=10, max_mana=10),
        ), seed=34), registry())

    def actor(self, g):
        return g.state.players[1].board[0]

    def weapon(self, g, player=1):
        return g.state.entities[g.state.players[player].weapon_id]

    def hero(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id]

    def cast(self, g, name, target=None):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        card = g.registry.card(name)
        return g.apply(PlayCard(1, eid, (self.actor(g) if target is None else target) if card.requires_target else None))

    def choose(self, g, name):
        p = g.state.pending_choice
        return g.apply(SelectChoice(p.player_id, p.id, (name,)))

    def rows(self, g, eid):
        return tuple(a for a in g.state.entities[eid].abilities if a.kind == 'aura')

    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(snap, registry())
        self.assertEqual(restored.snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), snap)
        return restored

    def reject(self, snap):
        snap['state_hash'] = canonical_hash({k: v for k, v in snap.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(snap, registry())

    def test_complete_raw_pin_and_single_necessary_real_definition(self):
        raw = evidence()
        self.assertEqual((raw['id'], raw['cost'], raw['attack'], raw['health']), (SMITH, 5, 4, 6))
        self.assertEqual(raw['text_en'], 'Your weapon has +2 Attack while this is damaged.')
        self.assertEqual(raw['tags']['CARDRACE'], 11)
        card = registry().card(SMITH)
        self.assertEqual(card.auras, (REL,))
        self.assertEqual(card.metadata.tribes, ('undead',))

    def test_closed_typed_profile_and_old_default_shape(self):
        self.assertEqual(AuraSpec(-1, health=2).target, 'friendly_minions')
        for changes in ({'target': 'friendly_weapon', 'condition': 'always'}, {'target': 'self'},
                {'condition': True}, {'target': True}, {'condition': 'self_healthy'}, {'attack': True},
                {'attack': 2.0}, {'attack': 0}, {'attack': -1}, {'health': 1},
                {'include_self': True}, {'adjacent_only': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(REL, **changes)
        with self.assertRaises(FrozenInstanceError):
            REL.attack = 3

    def test_ordinary_printed_carriers_and_duplicate_guards(self):
        card = registry().card(SMITH)
        for changes in ({'kind': CardType.SPELL}, {'keywords': (Keyword.MAGNETIC,)},
                {'keywords': (Keyword.STARSHIP_PIECE,)}, {'auras': (REL, REL)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                Registry('invalid-weapon-aura').register_card(replace(card, **changes))

    def test_strict_native_instance_and_new_grants_unsupported(self):
        g = self.game(); a = self.rows(g, self.actor(g))[0]
        for changes in ({'origin': 'granted'}, {'source_id': None}, {'consumed': True},
                {'expires_turn': 1}, {'remove_on_silence': False}, {'magnetic_id': 1}, {'kind': 'keyword'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(a, **changes)
        with self.assertRaises(TypeError):
            GrantAura(1, attack=2, target='friendly_weapon', condition='self_damaged')
        GrantAura(1, attack=2).__post_init__()

    def test_healthy_source_keeps_weapon_and_minion_base_attack(self):
        g = self.game()
        self.assertEqual((self.weapon(g).attack, self.hero(g).attack, g.state.entities[self.actor(g)].attack), (3, 3, 4))
        self.assertEqual(self.rows(g, self.actor(g))[0].aura_spec, REL)
        self.portable(g)

    def test_injury_adds_derived_weapon_attack_without_permanent_attachment(self):
        g = self.game(('hurt',))
        old = self.weapon(g); self.cast(g, 'hurt')
        self.assertEqual((self.weapon(g).attack, self.hero(g).attack), (5, 5))
        self.assertEqual(self.weapon(g).enchantments, old.enchantments)
        self.assertEqual(self.weapon(g).base_attack, old.base_attack)
        self.assertEqual(self.weapon(g).aura_attack, 2)
        self.portable(g)

    def test_repeated_injury_is_not_a_permanent_stack(self):
        g = self.game(('hurt', 'hurt'))
        self.cast(g, 'hurt'); self.cast(g, 'hurt')
        self.assertEqual((self.weapon(g).attack, g.state.entities[self.actor(g)].damage), (5, 2))
        self.portable(g)

    def test_partial_heal_preserves_weapon_contribution(self):
        g = self.game(('hurt2', 'heal'))
        self.cast(g, 'hurt2'); self.cast(g, 'heal')
        self.assertEqual((self.weapon(g).attack, g.state.entities[self.actor(g)].damage), (5, 1))

    def test_full_heal_revokes_and_reinjury_restores(self):
        g = self.game(('hurt', 'full', 'hurt'))
        self.cast(g, 'hurt'); self.cast(g, 'full')
        self.assertEqual((self.weapon(g).attack, self.weapon(g).aura_attack), (3, 0))
        self.cast(g, 'hurt'); self.assertEqual(self.weapon(g).attack, 5); self.portable(g)

    def test_zero_prevented_damage_and_overheal_do_not_enable(self):
        g = self.game(('hurt0', 'full', 'shield', 'hurt'))
        for name in ('hurt0', 'full', 'shield', 'hurt'):
            self.cast(g, name); self.assertEqual(self.weapon(g).attack, 3)
        self.portable(g)

    def test_no_weapon_then_late_equip_reads_current_condition(self):
        g = self.game(('hurt', 'equip'), weapon=None)
        self.cast(g, 'hurt'); self.assertEqual(self.hero(g).attack, 0)
        self.cast(g, 'equip'); self.assertEqual((self.weapon(g).attack, self.hero(g).attack), (5, 5))
        self.portable(g)

    def test_replacement_freezes_old_weapon_and_targets_new_slot(self):
        g = self.game(('hurt', 'equip-last'))
        self.cast(g, 'hurt'); old_id = self.weapon(g).id; self.cast(g, 'equip-last')
        self.assertEqual(self.weapon(g).attack, 6)
        death = next(d for d in g.state.death_history if d.entity_id == old_id)
        self.assertEqual((death.attack, death.durability), (5, 2))
        self.assertEqual(g.state.entities[old_id].aura_attack, 0)
        self.portable(g)

    def test_two_physical_sources_add_once_and_remove_independently(self):
        g = self.game(('hurt', 'hurt', 'kill'), board=(SMITH, SMITH))
        first, second = g.state.players[1].board
        self.cast(g, 'hurt', first); self.cast(g, 'hurt', second)
        self.assertEqual(self.weapon(g).attack, 7)
        self.cast(g, 'kill', second); self.assertEqual(self.weapon(g).attack, 5); self.portable(g)

    def test_each_controller_receives_only_its_own_source_contribution(self):
        g = self.game(('hurt', 'hurt'), enemy=(SMITH,), enemy_weapon='axe')
        self.cast(g, 'hurt'); self.assertEqual((self.weapon(g).attack, self.weapon(g, 2).attack), (5, 3))
        self.cast(g, 'hurt', g.state.players[2].board[0])
        self.assertEqual((self.weapon(g).attack, self.weapon(g, 2).attack), (5, 5)); self.portable(g)

    def test_offturn_weapon_remains_buffed_but_hero_uses_original_turn_policy(self):
        g = self.game(('hurt',))
        self.cast(g, 'hurt'); g.apply(EndTurn(1))
        self.assertEqual((self.weapon(g).attack, self.hero(g).attack), (5, 0))
        self.assertEqual(total_hero_attack(g.state, g.state.players[1]), 5)
        g.apply(EndTurn(2)); self.assertEqual(self.hero(g).attack, 5); self.portable(g)

    def test_weapon_numeric_modifiers_precede_aura_and_zero_floor(self):
        g = self.game(('hurt', 'w.minus', 'full'))
        self.cast(g, 'hurt'); self.cast(g, 'w.minus')
        self.assertEqual((self.weapon(g).attack, self.hero(g).attack), (1, 1))
        self.cast(g, 'full'); self.assertEqual((self.weapon(g).attack, self.hero(g).attack), (0, 0))
        self.portable(g)

    def test_healing_preserves_real_permanent_weapon_modifier(self):
        g = self.game(('w.plus', 'hurt', 'full'))
        self.cast(g, 'w.plus'); self.cast(g, 'hurt'); self.assertEqual(self.weapon(g).attack, 6)
        self.cast(g, 'full'); self.assertEqual(self.weapon(g).attack, 4); self.portable(g)

    def test_minion_combat_injury_enables_weapon_without_rewriting_packet(self):
        g = self.game(); enemy = g.state.players[2].board[0]
        g.apply(Attack(1, self.actor(g), enemy))
        self.assertEqual((g.state.entities[enemy].damage, g.state.entities[self.actor(g)].damage), (4, 1))
        self.assertEqual((self.weapon(g).attack, self.weapon(g).durability), (5, 2))
        g.apply(Attack(1, self.hero(g).id, self.hero(g, 2).id))
        self.assertEqual((self.hero(g, 2).damage, self.weapon(g).durability), (5, 1)); self.portable(g)

    def test_actual_hero_attack_wear_and_frozen_broken_weapon(self):
        g = self.game(('hurt', 'equip'), weapon='last')
        self.cast(g, 'hurt'); old_id = self.weapon(g).id
        g.apply(Attack(1, self.hero(g).id, self.hero(g, 2).id))
        self.assertEqual(self.hero(g, 2).damage, 6)
        self.assertIsNone(g.state.players[1].weapon_id)
        death = next(d for d in g.state.death_history if d.entity_id == old_id)
        self.assertEqual((death.attack, death.durability), (6, 0))
        self.cast(g, 'equip'); self.assertEqual(self.weapon(g).attack, 5); self.portable(g)

    def test_declared_wait_rebuilds_delivery_with_current_weapon(self):
        g = self.game(board=(SMITH, 'watcher')); enemy = g.state.players[2].board[0]
        g.apply(Attack(1, self.hero(g).id, enemy)); self.assertIsNotNone(g.state.pending_choice)
        restored = self.portable(g); clone = g.clone()
        for branch in (g, restored, clone):
            self.choose(branch, 'hurt')
            self.assertEqual((branch.state.entities[enemy].damage, self.hero(branch).damage), (5, 1))
            self.assertEqual((self.weapon(branch).attack, self.weapon(branch).durability), (5, 1))
            self.assertEqual(self.hero(branch).attacks_this_turn, 1); self.portable(branch)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(g.snapshot(), clone.snapshot())

    def test_damage_and_healing_result_callbacks_read_current_weapon(self):
        g = self.game(('quote-hurt', 'quote-full'))
        self.cast(g, 'quote-hurt'); self.assertEqual(self.hero(g).armor, 5)
        self.cast(g, 'quote-full'); self.assertEqual(self.hero(g).armor, 8); self.portable(g)

    def test_saved_event_contexts_freeze_current_weapon_before_reactions(self):
        g = self.game(('hurt', 'full'), board=(SMITH, 'observer'))
        self.cast(g, 'hurt'); self.assertEqual(self.hero(g).armor, 5)
        self.cast(g, 'full'); self.assertEqual(self.hero(g).armor, 8); self.portable(g)

    def test_primary_batch_callbacks_see_final_condition_once(self):
        g = self.game(('batch',)); self.cast(g, 'batch')
        self.assertEqual((self.hero(g).armor, self.weapon(g).attack), (10, 5)); self.portable(g)

    def test_lethal_source_uses_original_last_source_checkpoint_then_removes(self):
        g = self.game(('lethal',)); source = self.actor(g); self.cast(g, 'lethal')
        self.assertEqual((self.hero(g).armor, self.weapon(g).attack), (5, 3))
        death = next(d for d in g.state.death_history if d.entity_id == source)
        self.assertEqual((death.attack, death.abilities[0].aura_spec), (4, REL)); self.portable(g)

    def test_silence_removes_contribution_without_healing(self):
        g = self.game(('hurt', 'silence')); self.cast(g, 'hurt'); self.cast(g, 'silence')
        self.assertEqual((self.weapon(g).attack, g.state.entities[self.actor(g)].damage), (3, 1))
        self.assertEqual(self.rows(g, self.actor(g)), ()); self.portable(g)

    def test_current_copy_uses_own_damage_current_controller_and_original_provenance(self):
        g = self.game(('hurt', 'copy', 'full'), enemy=(), enemy_weapon='axe')
        source = self.actor(g); self.cast(g, 'hurt'); original = self.rows(g, source)[0]; self.cast(g, 'copy')
        copied = g.state.players[2].board[0]; row = self.rows(g, copied)[0]
        self.assertEqual(row.source_id, source); self.assertNotEqual(row.id, original.id)
        self.assertEqual(self.weapon(g, 2).attack, 5)
        self.cast(g, 'full', source); self.assertEqual((self.weapon(g).attack, self.weapon(g, 2).attack), (3, 5))
        self.portable(g)

    def test_base_copy_is_healthy_and_not_bound_to_original_injury(self):
        g = self.game(('hurt', 'copybase'), enemy=(), enemy_weapon='axe')
        self.cast(g, 'hurt'); self.cast(g, 'copybase')
        self.assertEqual(self.weapon(g, 2).attack, 3); self.portable(g)

    def test_current_silenced_copy_remains_without_aura(self):
        g = self.game(('hurt', 'silence', 'copy'), enemy=(), enemy_weapon='axe')
        for name in ('hurt', 'silence', 'copy'): self.cast(g, name)
        self.assertEqual(self.weapon(g, 2).attack, 3)
        self.assertEqual(self.rows(g, g.state.players[2].board[0]), ()); self.portable(g)

    def test_bounce_resets_condition_and_manual_replay_starts_healthy(self):
        g = self.game(('hurt', 'bounce')); source = self.actor(g)
        self.cast(g, 'hurt'); self.cast(g, 'bounce'); self.assertEqual(self.weapon(g).attack, 3)
        g.apply(PlayCard(1, source)); self.assertEqual(self.weapon(g).attack, 3)
        self.assertEqual(self.rows(g, source)[0].aura_spec, REL); self.portable(g)

    def test_transform_away_clears_old_contribution(self):
        g = self.game(('hurt', 'away')); self.cast(g, 'hurt'); self.cast(g, 'away')
        self.assertEqual(self.weapon(g).attack, 3); self.portable(g)

    def test_transform_into_installs_healthy_native_condition(self):
        g = self.game(('into', 'hurt'), board=('plain',)); self.cast(g, 'into')
        self.assertEqual(self.weapon(g).attack, 3); self.cast(g, 'hurt')
        self.assertEqual(self.weapon(g).attack, 5); self.portable(g)

    def test_manual_play_and_summon_share_native_aura_installation(self):
        for mode in ('manual', 'summon'):
            with self.subTest(mode=mode):
                g = self.game((SMITH if mode == 'manual' else 'summon', 'hurt'), board=())
                if mode == 'manual': g.apply(PlayCard(1, g.state.players[1].hand[0]))
                else: self.cast(g, 'summon')
                self.assertEqual(self.weapon(g).attack, 3); self.cast(g, 'hurt')
                self.assertEqual(self.weapon(g).attack, 5); self.portable(g)

    def test_control_change_moves_contribution_to_current_controller_weapon(self):
        g = self.game(('hurt', 'control'), enemy=(), enemy_weapon='axe'); source = self.actor(g)
        self.cast(g, 'hurt'); original = self.rows(g, source); self.cast(g, 'control')
        self.assertEqual((self.weapon(g).attack, self.weapon(g, 2).attack), (3, 5))
        self.assertEqual(self.rows(g, source), original); self.portable(g)

    def test_dormancy_suppresses_and_awake_recomputes_preserved_damage(self):
        g = self.game(('hurt', 'sleep', 'awake')); self.cast(g, 'hurt'); self.cast(g, 'sleep')
        self.assertEqual(self.weapon(g).attack, 3); self.cast(g, 'awake')
        self.assertEqual(self.weapon(g).attack, 5); self.portable(g)

    def test_health_set_clears_condition_before_stats_event_context(self):
        g = self.game(('hurt', 'sethp'), board=(SMITH, 'observer'))
        self.cast(g, 'hurt'); self.cast(g, 'sethp')
        self.assertEqual((self.weapon(g).attack, self.hero(g).armor), (3, 8)); self.portable(g)

    def test_max_health_gain_preserves_actual_damage_condition(self):
        g = self.game(('hurt', 'hp')); self.cast(g, 'hurt'); self.cast(g, 'hp')
        self.assertEqual((self.weapon(g).attack, g.state.entities[self.actor(g)].damage), (5, 1)); self.portable(g)

    def test_health_aura_removal_clamp_revokes_without_heal_event(self):
        g = self.game(('hurt', 'kill'), board=(SMITH, 'health-aura')); self.cast(g, 'hurt')
        before = sum(e.kind == 'healed' for e in g.events)
        self.cast(g, 'kill', g.state.players[1].board[1])
        self.assertEqual((self.weapon(g).attack, g.state.entities[self.actor(g)].damage), (3, 0))
        self.assertEqual(sum(e.kind == 'healed' for e in g.events), before); self.portable(g)

    def test_pending_choice_restore_clone_and_replay_resume_same_contribution(self):
        g = self.game(('wait',)); self.cast(g, 'wait'); restored = self.portable(g)
        self.choose(g, 'hurt'); self.choose(restored, 'hurt')
        self.assertEqual(self.weapon(g).attack, 5); self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_immediate_failure_restores_weapon_source_damage_events_and_rng(self):
        g = self.game(('fault',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.cast(g, 'fault')
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_waiting_failure_rolls_back_to_original_accepted_boundary(self):
        g = self.game(('wait',)); self.cast(g, 'wait'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)
        with self.assertRaises(IllegalAction): self.choose(g, 'missing')
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_player_views_actions_and_pure_queries_hide_private_aura_formula(self):
        g = self.game(('hurt', 'full'), enemy_hand=(SMITH,)); self.cast(g, 'hurt')
        before = g.snapshot()
        for _ in range(3):
            self.assertEqual(weapon_bonuses(g.state), {self.weapon(g).id: 2})
            self.assertTrue(any(type(a) is Attack and a.attacker_id == self.hero(g).id for a in g.legal_actions()))
            public = json.dumps(g.observe(1)) + json.dumps(g.observe(2)) + json.dumps(g.for_player(1).legal_actions())
            for key in ('aura_target', 'aura_condition', 'self_damaged', 'resolution_frame', 'next_attachment_id'):
                self.assertNotIn('"' + key + '"', public)
        self.assertEqual(g.snapshot(), before); self.cast(g, 'full'); self.portable(g)

    def test_rehashed_wire_requires_complete_typed_native_scope_and_lifecycle(self):
        g = self.game(('hurt',)); self.cast(g, 'hurt'); snap = g.snapshot(); eid = self.actor(g)
        for field, value in (('aura_condition', True), ('aura_condition', 'always'),
                ('aura_target', 'friendly_minions'), ('attack', 1), ('origin', 'granted'),
                ('consumed', True), ('expires_turn', 1), ('magnetic_id', 1)):
            bad = deepcopy(snap); row = next(a for a in bad['state']['entities'][str(eid)]['abilities'] if a['kind'] == 'aura')
            row[field] = value
            with self.subTest(field=field, value=value): self.reject(bad)
        bad = deepcopy(snap); row = bad['state']['entities'][str(eid)]['abilities'][0]
        del row['aura_condition']; self.reject(bad)
        bad = deepcopy(snap); row = bad['state']['entities'][str(eid)]['abilities'][0]
        row['aura_target'], row['aura_condition'] = 'friendly_minions', 'always'; self.reject(bad)

    def test_rehashed_wire_rejects_native_duplicates_and_stale_weapon_hero_caches(self):
        g = self.game(('hurt',)); self.cast(g, 'hurt'); snap = g.snapshot(); eid = self.actor(g)
        bad = deepcopy(snap); row = deepcopy(bad['state']['entities'][str(eid)]['abilities'][0])
        row['id'] = bad['state']['next_attachment_id']; bad['state']['next_attachment_id'] += 1
        bad['state']['entities'][str(eid)]['abilities'].append(row); self.reject(bad)
        for entity, field, value in ((self.weapon(g).id, 'aura_attack', 0),
                (self.weapon(g).id, 'aura_attack', 4), (self.hero(g).id, 'weapon_attack', 3)):
            bad = deepcopy(snap); bad['state']['entities'][str(entity)][field] = value
            with self.subTest(entity=entity, field=field, value=value): self.reject(bad)

    def test_protocol_versions_reject_all_old_and_noninteger_schemas(self):
        g = self.game(); snap = g.snapshot()
        self.assertEqual(snap['schema_version'], 266)
        self.assertEqual(snap['mechanics_version']['version'], CORE_EFFECTS_VERSION)
        self.assertEqual(snap['ruleset']['id'], 'prototype-v302')
        for value in (*range(1, 218), True, 182.0, 217):
            bad = deepcopy(snap); bad['schema_version'] = value
            with self.subTest(value=value), self.assertRaises(SnapshotError):
                Game.from_snapshot(bad, registry())
        self.portable(g)
