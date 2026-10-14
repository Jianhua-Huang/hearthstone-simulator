"""One real Deckhand and the existing Charge rules with current weapon state."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, GrantKeywordAura,
    IllegalAction, Keyword, KeywordAuraSpec, PlayCard, PlayerSetup, Registry, ResolutionError,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, CopyMinion, Destroy,
    EquipWeapon, GainArmor, GrantKeyword, InvokeBehavior, ModifyWeapon, RequestChoice,
    ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.equipment import equipped_weapon
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.keyword_auras import conditional_keywords
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

DECKHAND = 'CS2_146'
PATH = Path(__file__).resolve().parents[1] / 'data/support/weapon-presence-keyword-basics.json'
PIN = '6b2d66fccd88e3e8162642fc87e4ad4e0a241a7e54cb35fecd9166d3e0204902'
REL = KeywordAuraSpec(Keyword.CHARGE, 'self', condition='controller_has_weapon')


def evidence():
    support = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support) != PIN: raise ValueError('Complete weapon-presence evidence changed')
    for row in support['records']:
        if canonical_digest(row['data']) != row['data_sha256']: raise ValueError('Weapon-presence raw changed')
    return support['records'][0]['data']


def registry():
    r = Registry('isolated-weapon-presence-keyword-basics-v1'); raw = evidence()
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=80, metadata=metadata()))
    r.register_card(CardDefinition(DECKHAND, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], keyword_auras=(REL,), metadata=metadata(tribes=('pirate',))))
    r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, attack=1, health=15, metadata=metadata()))
    for cid, attack, durability in (('axe', 3, 2), ('last', 4, 1), ('zero', 0, 2)):
        r.register_card(CardDefinition(cid, cid, CardType.WEAPON, attack=attack,
            durability=durability, metadata=metadata()))

    def quote(c):
        e = c.state.entities[c.state.players[c.player_id].board[0]]
        return (GainArmor(c.player_id, 10 if Keyword.CHARGE in e.keywords else 1),)

    def waiting(c):
        wid = c.state.players[c.player_id].weapon_id
        return (RequestChoice(c.player_id, (
            ChoiceOption('lose', 'Lose weapon', (Destroy(wid, c.source_id),)),
            ChoiceOption('replace', 'Replace with zero Attack weapon', (EquipWeapon(c.player_id, 'zero'),)),
            ChoiceOption('fault', 'Lose then fail', (Destroy(wid, c.source_id),
                InvokeBehavior('late-fault', source_id=c.source_id, player_id=c.player_id))),
        ), c.source_id),)

    def declared(c):
        p = c.state.players[c.player_id]
        if c.event.player_id != c.player_id or c.event.source_id != p.board[0] or p.weapon_id is None:
            return ()
        return waiting(c)

    r.register_behavior('quote', quote); r.register_behavior('declared', declared)
    r.register_behavior('late-fault', lambda c: (AddToHand(c.player_id, 'missing.weapon-keyword'),))
    r.register_card(CardDefinition('observer', 'Observe equipment events', CardType.MINION, health=5,
        triggers=tuple(TriggerSpec(event, 'quote') for event in ('weapon_equipped', 'weapon_changed', 'weapon_destroyed')),
        metadata=metadata()))
    r.register_card(CardDefinition('watcher', 'Existing attack window', CardType.MINION, health=5,
        triggers=(TriggerSpec('attack_declared', 'declared'),), metadata=metadata()))
    r.register_card(CardDefinition('external', 'Existing external Charge', CardType.MINION, health=5,
        keyword_auras=(KeywordAuraSpec(Keyword.CHARGE, 'friendly_minions'),), metadata=metadata()))
    scripts = {
        'equip': lambda c: (EquipWeapon(c.player_id, 'axe'),),
        'equip-zero': lambda c: (EquipWeapon(c.player_id, 'zero'),),
        'equip-last': lambda c: (EquipWeapon(c.player_id, 'last'),),
        'lose': lambda c: (Destroy(c.state.players[c.player_id].weapon_id, c.source_id),),
        'zero-attack': lambda c: (ModifyWeapon(c.state.players[c.player_id].weapon_id, attack=-3, source_id=c.source_id),),
        'break': lambda c: (ModifyWeapon(c.state.players[c.player_id].weapon_id, durability=-2, source_id=c.source_id),),
        'summon': lambda c: (Summon(c.player_id, DECKHAND),),
        'summon-watcher': lambda c: (Summon(c.player_id, 'watcher'),),
        'sleep': lambda c: (MakeDormant(c.state.players[c.player_id].board[0], None, c.source_id),),
        'awake': lambda c: (AwakenMinion(c.state.players[c.player_id].board[0], c.source_id),),
        'wait': waiting,
        'fault': lambda c: (Destroy(c.state.players[c.player_id].weapon_id, c.source_id),
            AddToHand(c.player_id, 'missing.weapon-keyword')),
    }
    targeted = {
        'silence': lambda c: (Silence(c.target_id),),
        'copy': lambda c: (CopyMinion(c.target_id, 2),),
        'copybase': lambda c: (CopyMinion(c.target_id, 2, mode='base'),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'away': lambda c: (Transform(c.target_id, 'plain'),),
        'into': lambda c: (Transform(c.target_id, DECKHAND),),
        'control': lambda c: (ChangeControl(c.target_id, 2),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'permanent': lambda c: (GrantKeyword(c.target_id, Keyword.CHARGE, c.source_id),),
    }
    for name, body in {**scripts, **targeted}.items():
        r.register_behavior(name, body)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name,
            requires_target=name in targeted, metadata=metadata()))
    return r


class WeaponPresenceKeywordBasicsTests(unittest.TestCase):
    def game(self, hand=(), board=(DECKHAND,), enemy=('plain',), weapon='axe', enemy_weapon=None, enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, weapon_card_id=weapon,
                deck=('plain',) * 5, mana=10, max_mana=10),
            PlayerSetup('hero', hand=enemy_hand, board=enemy, weapon_card_id=enemy_weapon,
                deck=('plain',) * 5, mana=10, max_mana=10),
        ), seed=35), registry())

    def actor(self, g): return g.state.players[1].board[0]
    def hero(self, g, player=1): return g.state.entities[g.state.players[player].hero_id]
    def cast(self, g, name, target=None):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        card = g.registry.card(name)
        return g.apply(PlayCard(1, eid, (self.actor(g) if target is None else target) if card.requires_target else None))
    def play(self, g):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == DECKHAND)
        g.apply(PlayCard(1, eid)); return eid
    def choose(self, g, name):
        p = g.state.pending_choice; return g.apply(SelectChoice(p.player_id, p.id, (name,)))
    def rows(self, g, eid): return tuple(a for a in g.state.entities[eid].abilities if a.kind == 'keyword_aura')
    def charge(self, g, expected=True, eid=None):
        e = g.state.entities[self.actor(g) if eid is None else eid]
        self.assertEqual(Keyword.CHARGE in e.keywords, expected)
        self.assertEqual(e.conditional_keywords, {Keyword.CHARGE} if expected else set())
    def attack(self, g): return g.apply(Attack(1, self.actor(g), self.hero(g, 2).id))
    def can_attack(self, g, eid=None):
        return any(type(a) is Attack and a.attacker_id == (self.actor(g) if eid is None else eid) for a in g.legal_actions())
    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot())); restored = Game.from_snapshot(snap, registry())
        self.assertEqual(restored.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), snap); return restored
    def reject(self, snap):
        snap['state_hash'] = canonical_hash({k: v for k, v in snap.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(snap, registry())

    def test_complete_raw_pin_and_no_unconditional_printed_charge(self):
        raw = evidence(); card = registry().card(DECKHAND)
        self.assertEqual((raw['id'], raw['cost'], raw['attack'], raw['health']), (DECKHAND, 1, 2, 1))
        self.assertEqual(raw['text_en'], 'Has <b>Charge</b> while you have a weapon equipped.')
        self.assertIn({'tag': 'CHARGE', 'value': 1}, raw['reference_tags'])
        self.assertNotIn(Keyword.CHARGE, card.keywords); self.assertEqual(card.keyword_auras, (REL,))
        self.assertEqual(card.metadata.tribes, ('pirate',))

    def test_closed_profile_preserves_old_damaged_windfury_and_defaults(self):
        KeywordAuraSpec(Keyword.WINDFURY, 'self', condition='self_damaged').__post_init__()
        self.assertEqual(KeywordAuraSpec(Keyword.CHARGE, 'friendly_minions').condition, 'always')
        for changes in ({'condition': True}, {'condition': 'unknown'}, {'condition': 'always'},
                {'condition': 'self_damaged'}, {'keyword': Keyword.WINDFURY}, {'keyword': Keyword.TAUNT},
                {'target': 'friendly_minions'}, {'include_self': True}, {'adjacent_only': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(REL, **changes)
        with self.assertRaises(FrozenInstanceError): REL.condition = 'always'

    def test_native_ordinary_carriers_and_optional_grants_are_explicit(self):
        card = registry().card(DECKHAND)
        for changes in ({'kind': CardType.SPELL}, {'keywords': (Keyword.MAGNETIC,)},
                {'keywords': (Keyword.STARSHIP_PIECE,)}, {'keyword_auras': (REL, REL)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                Registry('invalid-weapon-keyword').register_card(replace(card, **changes))
        with self.assertRaises(ValueError): GrantKeywordAura(1, REL)
        g = self.game(); row = self.rows(g, self.actor(g))[0]
        for changes in ({'origin': 'granted'}, {'source_id': None}, {'consumed': True},
                {'expires_turn': 1}, {'remove_on_silence': False}, {'magnetic_id': 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(row, **changes)

    def test_weapon_presence_adds_only_a_derived_keyword_contribution(self):
        g = self.game(); self.charge(g)
        e = g.state.entities[self.actor(g)]
        self.assertEqual((e.attack, len(e.abilities), e.enchantments, e.aura_keywords), (2, 1, [], set()))
        self.assertEqual(self.rows(g, e.id)[0].keyword_aura, REL); self.portable(g)

    def test_no_weapon_has_no_charge_but_mature_minion_can_attack(self):
        g = self.game(weapon=None); self.charge(g, False); self.assertTrue(self.can_attack(g))
        self.attack(g); self.assertEqual(self.hero(g, 2).damage, 2); self.portable(g)

    def test_new_manual_play_without_weapon_keeps_summoning_sickness(self):
        g = self.game((DECKHAND,), board=(), weapon=None); self.play(g)
        self.charge(g, False); self.assertFalse(self.can_attack(g))
        before = g.snapshot()
        with self.assertRaises(IllegalAction): self.attack(g)
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_new_manual_play_with_weapon_uses_existing_charge_attack(self):
        g = self.game((DECKHAND,), board=()); self.play(g); self.charge(g)
        self.assertTrue(self.can_attack(g)); self.attack(g)
        self.assertEqual((self.hero(g, 2).damage, g.state.entities[self.actor(g)].attacks_this_turn), (2, 1))
        self.portable(g)

    def test_new_summon_uses_same_current_weapon_condition(self):
        for weapon in (None, 'axe'):
            with self.subTest(weapon=weapon):
                g = self.game(('summon',), board=(), weapon=weapon); self.cast(g, 'summon')
                self.charge(g, weapon is not None); self.assertEqual(self.can_attack(g), weapon is not None)
                self.portable(g)

    def test_late_equip_opens_first_attack_for_this_turn_new_minion(self):
        g = self.game((DECKHAND, 'equip'), board=(), weapon=None); self.play(g)
        self.assertFalse(self.can_attack(g)); self.cast(g, 'equip'); self.charge(g)
        self.assertTrue(self.can_attack(g)); self.attack(g); self.portable(g)

    def test_zero_attack_weapon_still_provides_charge(self):
        g = self.game((DECKHAND,), board=(), weapon='zero'); self.play(g); self.charge(g)
        self.assertEqual(self.hero(g).attack, 0); self.assertTrue(self.can_attack(g)); self.attack(g); self.portable(g)

    def test_modifying_weapon_attack_to_zero_does_not_remove_condition(self):
        g = self.game((DECKHAND, 'zero-attack'), board=()); self.play(g); self.cast(g, 'zero-attack')
        self.charge(g); self.assertEqual(self.hero(g).attack, 0); self.assertTrue(self.can_attack(g)); self.portable(g)

    def test_weapon_loss_revokes_new_minion_attack_before_it_is_spent(self):
        g = self.game((DECKHAND, 'lose'), board=()); self.play(g); self.cast(g, 'lose')
        self.charge(g, False); self.assertFalse(self.can_attack(g))
        self.assertEqual(g.state.entities[self.actor(g)].attacks_this_turn, 0); self.portable(g)

    def test_weapon_durability_zero_removes_condition_by_original_live_predicate(self):
        g = self.game((DECKHAND, 'break'), board=()); self.play(g); self.cast(g, 'break')
        self.assertIsNone(g.state.players[1].weapon_id); self.charge(g, False)
        self.assertFalse(self.can_attack(g)); self.portable(g)

    def test_last_hero_weapon_attack_revokes_charge_without_spending_minion_attack(self):
        g = self.game((DECKHAND,), board=(), weapon='last'); self.play(g)
        g.apply(Attack(1, self.hero(g).id, self.hero(g, 2).id))
        self.charge(g, False); self.assertFalse(self.can_attack(g))
        self.assertEqual(g.state.entities[self.actor(g)].attacks_this_turn, 0); self.portable(g)

    def test_weapon_replacement_preserves_condition_and_original_spent_attack(self):
        g = self.game((DECKHAND, 'equip-zero'), board=()); self.play(g); self.attack(g)
        self.cast(g, 'equip-zero'); self.charge(g); self.assertFalse(self.can_attack(g))
        self.assertEqual(g.state.entities[self.actor(g)].attacks_this_turn, 1); self.portable(g)

    def test_loss_and_reequip_never_refund_same_incarnation_attack(self):
        g = self.game((DECKHAND, 'lose', 'equip'), board=()); self.play(g); self.attack(g)
        self.cast(g, 'lose'); self.cast(g, 'equip'); self.charge(g)
        self.assertFalse(self.can_attack(g)); self.portable(g)

    def test_real_new_owner_turn_allows_mature_minion_without_charge(self):
        g = self.game((DECKHAND, 'lose'), board=()); self.play(g); self.cast(g, 'lose')
        self.assertFalse(self.can_attack(g)); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.charge(g, False); self.assertTrue(self.can_attack(g)); self.attack(g); self.portable(g)

    def test_weapon_owned_by_opponent_does_not_enable_source(self):
        g = self.game((DECKHAND,), board=(), weapon=None, enemy_weapon='axe'); self.play(g)
        self.charge(g, False); self.assertFalse(self.can_attack(g)); self.portable(g)

    def test_offturn_weapon_presence_is_independent_of_hero_attack_projection(self):
        g = self.game(); g.apply(EndTurn(1)); self.charge(g)
        self.assertEqual(self.hero(g).attack, 0); self.portable(g)

    def test_current_copy_reads_destination_equipment_and_preserves_provenance(self):
        for source_weapon, target_weapon in ((None, 'axe'), ('axe', None)):
            with self.subTest(source_weapon=source_weapon):
                g = self.game(('copy',), enemy=(), weapon=source_weapon, enemy_weapon=target_weapon)
                source = self.actor(g); original = self.rows(g, source)[0]; self.cast(g, 'copy')
                copied = g.state.players[2].board[0]; row = self.rows(g, copied)[0]
                self.assertEqual(row.source_id, source); self.assertNotEqual(row.id, original.id)
                self.charge(g, target_weapon is not None, copied); self.portable(g)

    def test_current_silenced_copy_does_not_reinstall_condition(self):
        g = self.game(('silence', 'copy'), enemy=(), enemy_weapon='axe')
        self.cast(g, 'silence'); self.cast(g, 'copy'); copied = g.state.players[2].board[0]
        self.charge(g, False, copied); self.assertEqual(self.rows(g, copied), ()); self.portable(g)

    def test_base_copy_reinstalls_native_condition_using_destination_weapon(self):
        g = self.game(('silence', 'copybase'), enemy=(), enemy_weapon='axe')
        self.cast(g, 'silence'); self.cast(g, 'copybase'); self.charge(g, True, g.state.players[2].board[0]); self.portable(g)

    def test_silence_clears_only_self_derived_cache(self):
        g = self.game(('silence',)); self.cast(g, 'silence'); self.charge(g, False)
        self.assertEqual(self.rows(g, self.actor(g)), ()); self.portable(g)

    def test_bounce_rebuilds_native_condition_on_return_and_replay(self):
        g = self.game(('bounce',)); source = self.actor(g); self.cast(g, 'bounce')
        self.charge(g, True, source); self.assertEqual(g.state.entities[source].zone, Zone.HAND)
        g.apply(PlayCard(1, source)); self.charge(g); self.assertTrue(self.can_attack(g)); self.portable(g)

    def test_transform_away_clears_self_cache_and_old_native_condition(self):
        g = self.game(('away',)); self.cast(g, 'away'); self.charge(g, False); self.portable(g)

    def test_transform_into_recomputes_condition_from_current_slot(self):
        g = self.game(('into',), board=('plain',)); self.cast(g, 'into'); self.charge(g)
        self.assertEqual(self.rows(g, self.actor(g))[0].keyword_aura, REL); self.portable(g)

    def test_control_change_uses_new_controller_slot_not_original_source(self):
        for target_weapon in (None, 'zero'):
            with self.subTest(target_weapon=target_weapon):
                g = self.game(('control',), enemy=(), enemy_weapon=target_weapon); source = self.actor(g)
                original = self.rows(g, source); self.cast(g, 'control')
                self.charge(g, target_weapon is not None, source); self.assertEqual(self.rows(g, source), original)
                self.portable(g)

    def test_dormancy_suppresses_condition_and_awake_recomputes_it(self):
        g = self.game(('sleep', 'awake')); self.cast(g, 'sleep'); self.charge(g, False)
        self.cast(g, 'awake'); self.charge(g); self.portable(g)

    def test_weapon_change_while_dormant_is_observed_on_awake(self):
        g = self.game(('sleep', 'lose', 'awake')); self.cast(g, 'sleep'); self.cast(g, 'lose'); self.cast(g, 'awake')
        self.charge(g, False); self.portable(g)

    def test_source_death_freezes_current_keyword_and_native_declaration(self):
        g = self.game(('kill',)); source = self.actor(g); self.cast(g, 'kill')
        death = next(d for d in g.state.death_history if d.entity_id == source)
        self.assertIn(Keyword.CHARGE, death.keywords); self.assertEqual(death.abilities[0].keyword_aura, REL); self.portable(g)

    def test_losing_condition_preserves_permanent_same_keyword(self):
        g = self.game((DECKHAND, 'permanent', 'lose'), board=()); self.play(g)
        self.cast(g, 'permanent'); self.cast(g, 'lose'); e = g.state.entities[self.actor(g)]
        self.assertEqual(e.conditional_keywords, set()); self.assertIn(Keyword.CHARGE, e.keywords)
        self.assertTrue(self.can_attack(g)); self.portable(g)

    def test_losing_condition_preserves_existing_external_same_keyword(self):
        g = self.game(('lose',), board=(DECKHAND, 'external')); self.cast(g, 'lose')
        e = g.state.entities[self.actor(g)]
        self.assertEqual(e.conditional_keywords, set()); self.assertIn(Keyword.CHARGE, e.aura_keywords)
        self.assertIn(Keyword.CHARGE, e.keywords); self.portable(g)

    def test_equipment_event_contexts_freeze_updated_self_keyword(self):
        g = self.game(('equip', 'lose'), board=(DECKHAND, 'observer'), weapon=None)
        self.cast(g, 'equip'); self.assertEqual(self.hero(g).armor, 10)
        self.cast(g, 'lose'); self.assertEqual(self.hero(g).armor, 11); self.portable(g)

    def test_hand_display_and_new_play_use_current_slot_without_permanent_charge(self):
        g = self.game((DECKHAND, 'lose'), board=()); source = g.state.players[1].hand[0]
        self.charge(g, True, source); self.cast(g, 'lose'); self.charge(g, False, source)
        self.play(g); self.charge(g, False); self.assertFalse(self.can_attack(g)); self.portable(g)

    def test_declared_wait_keeps_original_acceptance_after_condition_loss(self):
        g = self.game((DECKHAND, 'summon-watcher'), board=()); source = self.play(g); self.cast(g, 'summon-watcher')
        g.apply(Attack(1, source, self.hero(g, 2).id)); self.assertIsNotNone(g.state.pending_choice)
        restored = self.portable(g); clone = g.clone()
        for branch in (g, restored, clone):
            self.choose(branch, 'lose'); self.charge(branch, False)
            self.assertEqual((self.hero(branch, 2).damage, branch.state.entities[source].attacks_this_turn), (2, 1))
            self.portable(branch)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(g.snapshot(), clone.snapshot())

    def test_pending_choice_restore_clone_and_replay_keep_original_equipment(self):
        g = self.game(('wait',)); self.cast(g, 'wait'); restored = self.portable(g)
        self.choose(g, 'replace'); self.choose(restored, 'replace'); self.charge(g)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_immediate_failure_restores_equipment_keywords_events_and_rng(self):
        g = self.game(('fault',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.cast(g, 'fault')
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_waiting_failure_rolls_back_to_original_choice_boundary(self):
        g = self.game(('wait',)); self.cast(g, 'wait'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_pure_queries_and_player_views_hide_self_condition_cache(self):
        g = self.game((DECKHAND,), board=(), enemy_hand=(DECKHAND,)); self.play(g); before = g.snapshot()
        for _ in range(3):
            self.assertIsNotNone(equipped_weapon(g.state, g.state.players[1]))
            actual = conditional_keywords(g.state, g.state.entities[self.actor(g)])
            self.assertEqual(actual, {Keyword.CHARGE}); actual.clear(); self.charge(g)
            public = json.dumps(g.observe(1)) + json.dumps(g.observe(2)) + json.dumps(g.for_player(1).legal_actions())
            for key in ('conditional_keywords', 'controller_has_weapon', 'keyword_aura', 'resolution_frame', 'next_attachment_id'):
                self.assertNotIn('"'+key+'"', public)
            self.assertTrue(self.can_attack(g))
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_rehashed_wire_requires_complete_native_condition_and_lifecycle(self):
        g = self.game(); snap = g.snapshot(); source = self.actor(g)
        for field, value in (('condition', True), ('condition', 'always'), ('target', 'friendly_minions'),
                ('keyword', 'windfury'), ('adjacent_only', True)):
            bad = deepcopy(snap); row = bad['state']['entities'][str(source)]['abilities'][0]
            row['keyword_aura'][field] = value
            with self.subTest(field=field, value=value): self.reject(bad)
        bad = deepcopy(snap); row = bad['state']['entities'][str(source)]['abilities'][0]
        row['keyword_aura']['keyword'] = 'windfury'; row['keyword_aura']['condition'] = 'self_damaged'; self.reject(bad)
        bad = deepcopy(snap); del bad['state']['entities'][str(source)]['abilities'][0]['keyword_aura']['condition']; self.reject(bad)
        bad = deepcopy(snap); bad['state']['entities'][str(source)]['abilities'][0]['origin'] = 'granted'; self.reject(bad)

    def test_rehashed_wire_rejects_missing_stale_or_forged_derived_cache(self):
        g = self.game(); snap = g.snapshot(); source = self.actor(g)
        for value in ([], ['immune'], ['charge', 'charge'], True, ['unknown']):
            bad = deepcopy(snap); bad['state']['entities'][str(source)]['conditional_keywords'] = value
            with self.subTest(value=value): self.reject(bad)
        bad = deepcopy(snap); del bad['state']['entities'][str(source)]['conditional_keywords']; self.reject(bad)
        bad = deepcopy(snap); bad['state']['entities'][str(source)]['keywords'] = []; self.reject(bad)
        plain = g.state.players[2].board[0]; bad = deepcopy(snap)
        bad['state']['entities'][str(plain)]['conditional_keywords'] = ['charge']; self.reject(bad)

    def test_captured_frames_validate_cache_in_the_original_state_domain(self):
        g = self.game(('lose',)); source = self.actor(g)
        context = RuleContext(g.state, source, 1)
        self.cast(g, 'lose'); self.charge(g, False)
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        saved = codec.encode(context)
        restored = codec.decode(saved)
        self.assertEqual(restored.state.entities[source].conditional_keywords, {Keyword.CHARGE})
        self.assertIsNotNone(restored.state.players[1].weapon_id)
        for value in ([], ['immune']):
            bad = deepcopy(saved)
            bad['fields']['state']['state']['entities'][str(source)]['conditional_keywords'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): codec.decode(bad)
        original = deepcopy(context.state)
        original.entities[source].conditional_keywords.clear()
        with self.assertRaises(ValueError): codec.encode(RuleContext(original, source, 1))
        self.portable(g)

    def test_schema_protocol_and_all_old_versions(self):
        g = self.game(); snap = g.snapshot(); self.assertEqual(snap['schema_version'], 265)
        self.assertEqual(snap['ruleset']['id'], 'prototype-v302')
        self.assertEqual(snap['mechanics_version']['version'], CORE_EFFECTS_VERSION)
        for value in (*range(1, 218), True, 183.0, 217):
            bad = deepcopy(snap); bad['schema_version'] = value
            with self.subTest(value=value), self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())
        self.portable(g)
