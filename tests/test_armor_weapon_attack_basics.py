"""A native armor-derived weapon, using the existing equipment and armor paths."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, AttackPolicySpec, CardDefinition, CardType, EndTurn,
    EquippedWeaponReference, Game, IllegalAction, PlayCard, PlayerSetup, Registry,
    ResolutionError, Scenario, SelectChoice, SnapshotError, StatRelationLayer,
    StatRelationOperand, StatRelationSpec, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, EquipWeapon,
    GainArmor, InvokeBehavior, LoseArmor, ModifyWeapon, ReplaceHero, RequestChoice,
    TransferWeapon)
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.stat_relations import GrantStatRelation, conditional_attack
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

CARD = 'LOOT_044'
PIN = '7d6d2a3e58d1f0f34785bca61c982d24116d4c2912fc20cb08cd66ef18c93e34'
REL = StatRelationSpec(operand=StatRelationOperand.CONTROLLER_ARMOR)


def evidence():
    data = json.loads((Path(__file__).resolve().parents[1] /
        'data/support/armor-weapon-attack-basics.json').read_bytes())
    if canonical_digest(data) != PIN: raise ValueError('Complete armor weapon evidence changed')
    for row in data['records']:
        if canonical_digest(row['data']) != row['data_sha256']: raise ValueError('Raw card changed')
    return data


def registry():
    r = Registry('isolated-armor-weapon-attack-v1')
    for cid in ('hero', 'replacement'):
        r.register_card(CardDefinition(cid, cid, CardType.HERO, health=80, metadata=metadata()))
    r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, attack=2, health=30, metadata=metadata()))
    r.register_card(CardDefinition('axe', 'Axe', CardType.WEAPON, attack=3, durability=2, metadata=metadata()))
    raw = evidence()['records'][0]['data']
    r.register_card(CardDefinition(CARD, raw['name'], CardType.WEAPON, cost=raw['cost'],
        attack=0, durability=raw['health'], stat_relations=(REL,),
        attack_policies=(AttackPolicySpec(mode='cannot_attack_heroes'),), metadata=metadata_from_record(raw)))

    def wid(c): return c.state.players[c.player_id].weapon_id
    def choice(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('gain', 'Gain armor', (GainArmor(c.player_id, 4),)),
            ChoiceOption('lose', 'Lose armor', (LoseArmor(c.player_id, None, c.source_id),)),
            ChoiceOption('fault', 'Gain then fail', (GainArmor(c.player_id, 4),
                InvokeBehavior('fault-body', c.source_id, c.player_id))),
        ), c.source_id),)
    scripts = {
        'gain': lambda c: (GainArmor(c.player_id, 4),),
        'lose': lambda c: (LoseArmor(c.player_id, 2, c.source_id),),
        'clear': lambda c: (LoseArmor(c.player_id, None, c.source_id),),
        'damage': lambda c: (Damage(c.state.players[c.player_id].hero_id, 2, c.source_id),),
        'buff': lambda c: (ModifyWeapon(wid(c), attack=5, source_id=c.source_id),),
        'break': lambda c: (ModifyWeapon(wid(c), durability=-2, source_id=c.source_id),),
        'destroy': lambda c: (Destroy(wid(c), c.source_id),),
        'equip': lambda c: (EquipWeapon(c.player_id, CARD),),
        'replace': lambda c: (EquipWeapon(c.player_id, 'axe'),),
        'replace-hero': lambda c: (ReplaceHero(c.player_id, 'replacement', armor=2),),
        'take': lambda c: (TransferWeapon(EquippedWeaponReference.capture(
            c.state.entities[c.state.players[3-c.player_id].weapon_id]), c.player_id, c.source_id),),
        'wait': choice,
        'fault': lambda c: (GainArmor(c.player_id, 4), InvokeBehavior('fault-body', c.source_id, c.player_id)),
    }
    for name, body in scripts.items():
        r.register_behavior(name, body)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=metadata()))
    r.register_behavior('fault-body', lambda c: (AddToHand(c.player_id, 'unknown.armor-weapon'),))
    r.register_behavior('declared-choice', lambda c: choice(c) if c.event.source_id == c.state.players[c.player_id].hero_id else ())
    r.register_card(CardDefinition('watcher', 'Attack listener', CardType.MINION, health=5,
        triggers=(TriggerSpec('attack_declared', 'declared-choice'),), metadata=metadata()))
    # The observer stores the already-normalized value in an unrelated hero's
    # armor, so it cannot change the operand it is observing.
    def observe(c):
        if c.event.player_id != c.player_id: return ()
        weapon = c.state.entities[c.state.players[c.player_id].weapon_id]
        hero = c.state.entities[c.state.players[c.player_id].hero_id]
        if weapon.attack != hero.attack: raise ValueError('Stale hero weapon contribution')
        return (GainArmor(3-c.player_id, weapon.attack),)
    r.register_behavior('armor-observe', observe)
    r.register_card(CardDefinition('observer', 'Armor listener', CardType.MINION, health=5,
        triggers=(TriggerSpec('armor_gained', 'armor-observe'),), metadata=metadata()))
    return r


class ArmorWeaponAttackBasicsTests(unittest.TestCase):
    def game(self, hand=(), *, armor=3, enemy_armor=9, weapon=CARD, enemy_weapon=None, board=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', deck=('plain',), hand=hand, board=board, armor=armor, weapon_card_id=weapon, mana=10, max_mana=10),
            PlayerSetup('hero', deck=('plain',), board=('plain',), armor=enemy_armor, weapon_card_id=enemy_weapon, mana=10, max_mana=10),
        ), seed=27), registry())
    def hero(self, g, player=1): return g.state.entities[g.state.players[player].hero_id]
    def weapon(self, g, player=1): return g.state.entities[g.state.players[player].weapon_id]
    def cast(self, g, name):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, eid))
    def choose(self, g, name):
        p = g.state.pending_choice; return g.apply(SelectChoice(p.player_id, p.id, (name,)))
    def values(self, g, expected, player=1):
        self.assertEqual(self.weapon(g, player).attack, expected)
        self.assertEqual(self.weapon(g, player).conditional_attack, expected)
        self.assertEqual(self.hero(g, player).weapon_attack, expected if g.state.active_player == player else 0)
    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot())); restored = Game.from_snapshot(snap, registry())
        self.assertEqual(restored.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), snap)
        return restored
    def reject(self, snap):
        snap['state_hash'] = canonical_hash({k:v for k,v in snap.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(snap, registry())

    def test_full_raw_pin_and_one_native_adapter(self):
        data = evidence(); card = registry().card(CARD)
        self.assertEqual(data['new_real_card_adapters'], [CARD])
        self.assertEqual([r['id'] for r in data['records']], [CARD, 'CORE_LOOT_044'])
        self.assertEqual((card.cost, card.attack, card.durability, card.stat_relations), (2, 0, 2, (REL,)))
        self.assertEqual(card.metadata.classes, ('warrior',))

    def test_closed_native_weapon_spec_and_grant_rejection(self):
        for kwargs in ({'amount': 1}, {'amount': True}, {'layer': StatRelationLayer.CONDITIONAL_ATTACK},
                {'card_count': 1}, {'comparison': 'eq'}, {'operand': 'controller_armor'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): replace(REL, **kwargs)
        with self.assertRaises(ValueError): GrantStatRelation(1, REL, 1)
        with self.assertRaises(ValueError):
            Registry('bad').register_card(CardDefinition('bad', 'Bad', CardType.MINION, health=2, stat_relations=(REL,), metadata=metadata()))
        with self.assertRaises(ValueError):
            Registry('mixed').register_card(CardDefinition('bad', 'Bad', CardType.WEAPON, durability=2,
                stat_relations=(REL, StatRelationSpec()), metadata=metadata()))

    def test_initial_zero_and_large_armor_are_derived(self):
        for armor in (0, 3, 101):
            with self.subTest(armor=armor):
                g = self.game(armor=armor); self.values(g, armor); self.portable(g)

    def test_gain_loss_and_damage_update_without_accumulating(self):
        g = self.game(('gain', 'lose', 'damage', 'clear'))
        for name, amount in (('gain', 7), ('lose', 5), ('damage', 3), ('clear', 0)):
            self.cast(g, name); self.values(g, amount)
            self.assertEqual(self.weapon(g).base_attack, 0)
        self.portable(g)

    def test_existing_attack_hero_restriction_and_zero_attack_legality(self):
        g = self.game(); snap = g.snapshot()
        with self.assertRaises(IllegalAction): g.apply(Attack(1, self.hero(g).id, self.hero(g, 2).id))
        self.assertEqual(g.snapshot(), snap)
        zero = self.game(armor=0)
        with self.assertRaises(IllegalAction): zero.apply(Attack(1, self.hero(zero).id, zero.state.players[2].board[0]))

    def test_combat_uses_prepared_attack_then_armor_loss_and_original_wear(self):
        g = self.game(); target = g.state.players[2].board[0]
        g.apply(Attack(1, self.hero(g).id, target))
        self.assertEqual(g.state.entities[target].damage, 3)
        self.values(g, 1)
        self.assertEqual((self.weapon(g).durability, self.hero(g).attacks_this_turn), (1, 1))
        self.portable(g)

    def test_current_controller_and_inactive_turn_weapon_views(self):
        g = self.game(enemy_weapon=CARD); self.values(g, 3); self.values(g, 9, 2)
        g.apply(EndTurn(1)); self.values(g, 3); self.values(g, 9, 2); self.portable(g)

    def test_physical_transfer_recomputes_new_controller_armor(self):
        g = self.game(('take',), weapon=None, enemy_weapon=CARD)
        old = self.weapon(g, 2).id; self.cast(g, 'take')
        self.assertEqual(self.weapon(g).id, old); self.values(g, 3)
        self.assertIsNone(g.state.players[2].weapon_id)
        self.portable(g)

    def test_hero_replacement_reads_current_hero_armor(self):
        g = self.game(('replace-hero',)); self.cast(g, 'replace-hero')
        self.assertEqual(self.hero(g).card_id, 'replacement'); self.values(g, 5); self.portable(g)

    def test_final_layer_retains_ordinary_modification_without_accumulation(self):
        g = self.game(('buff', 'gain')); self.cast(g, 'buff')
        self.assertEqual(self.weapon(g).attack_bonus, 5); self.values(g, 3)
        self.cast(g, 'gain'); self.values(g, 7); self.portable(g)

    def test_play_and_equip_share_native_relation_and_original_payment(self):
        for card in (CARD, 'equip'):
            with self.subTest(card=card):
                g = self.game((card,), weapon=None); self.cast(g, card); self.values(g, 3)
                self.assertEqual(g.state.players[1].mana, 8 if card == CARD else 10)
                self.portable(g)

    def test_destroy_and_break_freeze_attack_and_clear_hero_contribution(self):
        for name in ('destroy', 'break'):
            with self.subTest(name=name):
                g = self.game((name, 'gain')); old = self.weapon(g).id; self.cast(g, name)
                self.assertIsNone(g.state.players[1].weapon_id)
                self.assertEqual(self.hero(g).weapon_attack, 0)
                record = next(r for r in g.state.death_history if r.entity_id == old)
                self.assertEqual(record.attack, 3); self.cast(g, 'gain')
                self.assertEqual(record.attack, 3); self.assertEqual(self.hero(g).weapon_attack, 0)
                self.portable(g)

    def test_replacement_removes_weapon_restriction_and_old_contribution(self):
        g = self.game(('replace',)); self.cast(g, 'replace')
        g.apply(Attack(1, self.hero(g).id, self.hero(g, 2).id))
        self.assertEqual(self.hero(g, 2).armor, 6); self.portable(g)

    def test_armor_event_context_sees_both_updated_weapon_and_hero(self):
        g = self.game(('gain',), board=('observer',)); self.cast(g, 'gain')
        self.values(g, 7); self.assertEqual(self.hero(g, 2).armor, 16); self.portable(g)

    def test_declared_wait_restore_reprices_only_unprepared_combat(self):
        g = self.game(board=('watcher',)); target = g.state.players[2].board[0]
        g.apply(Attack(1, self.hero(g).id, target)); self.assertIsNotNone(g.state.pending_choice)
        restored = self.portable(g)
        for branch in (g, restored):
            self.choose(branch, 'gain'); self.assertEqual(branch.state.entities[target].damage, 7)
            self.values(branch, 5); self.assertEqual(self.weapon(branch).durability, 1)
            self.portable(branch)
        self.assertEqual(restored.snapshot(), g.snapshot())

    def test_immediate_and_waiting_failure_restore_armor_and_derived_views(self):
        g = self.game(('fault',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.cast(g, 'fault')
        self.assertEqual(g.snapshot(), before)
        g = self.game(('wait',)); self.cast(g, 'wait'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_original_context_checks_its_own_armor_and_cache(self):
        g = self.game(('gain',)); wid = self.weapon(g).id
        context = RuleContext(g.state, wid, 1); self.cast(g, 'gain')
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        restored = codec.decode(codec.encode(context)); self.assertEqual(restored.state.entities[wid].attack, 3)
        bad = deepcopy(context.state); bad.entities[wid].conditional_attack = 7
        with self.assertRaises(ValueError): codec.encode(RuleContext(bad, wid, 1))

    def test_rehashed_snapshot_rejects_stale_cache_and_forged_native_relation(self):
        g = self.game(); snap = g.snapshot(); wid = str(self.weapon(g).id)
        # State entity keys are wire integers represented by JSON strings.
        for field, value in (('conditional_attack', 4), ('conditional_attack', True), ('weapon_attack', 1)):
            bad = deepcopy(snap); entities = bad['state']['entities']
            target = entities[wid] if isinstance(entities, dict) else next(r for r in entities if r['id'] == self.weapon(g).id)
            target[field] = value; self.reject(bad)
        bad = deepcopy(snap); entities = bad['state']['entities']
        target = entities[wid] if isinstance(entities, dict) else next(r for r in entities if r['id'] == self.weapon(g).id)
        relation = next(a for a in target['abilities'] if a['kind'] == 'stat_relation')
        relation['origin'] = 'granted'; self.reject(bad)
        bad = deepcopy(snap); target = bad['state']['entities'][wid]
        relation = next(a for a in target['abilities'] if a['kind'] == 'stat_relation')
        extra = deepcopy(relation); extra['id'] = bad['state']['next_attachment_id']
        bad['state']['next_attachment_id'] += 1; target['abilities'].append(extra); self.reject(bad)
        bad = deepcopy(snap); del bad['state']['entities'][wid]['conditional_attack']; self.reject(bad)

    def test_queries_and_player_interfaces_hide_formula_and_are_pure(self):
        g = self.game(); before = g.snapshot()
        self.assertEqual(conditional_attack(g.state, self.weapon(g)), 3)
        payload = json.dumps(g.observe(1), ensure_ascii=False) + json.dumps(g.observe(2)) + json.dumps(g.for_player(1).legal_actions())
        for key in ('controller_armor', 'stat_relation', 'conditional_attack', 'resolution_frame'):
            self.assertNotIn(key, payload)
        self.assertEqual(g.snapshot(), before)
