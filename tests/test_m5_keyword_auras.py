"""Continuous keyword provenance, combat limits and Azshara integration."""
import json
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, GrantKeywordAura,
    Herald, IllegalAction, Keyword, KeywordAuraSpec, PlayCard, PlayerSetup, ResolutionError,
    Scenario, SelectChoice, SnapshotError, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    DamageBatch, Destroy, Freeze, GainArmor, GrantKeyword, ModifyWeapon, ReplaceHero,
    RequestChoice, ReturnToHand, Silence, Summon, Transform, Unfreeze)
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.model import AbilityInstance, AuraSpec, CardClass, CardMetadata
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay


WIND = KeywordAuraSpec(Keyword.WINDFURY)


class KeywordAuraTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.r.register_card(CardDefinition('hero', 'fixture hero', CardType.HERO, attack=2, health=30,
            metadata=CardMetadata(False, (CardClass.DEMON_HUNTER,), None)))
        self.minion('plain', attack=2, health=5)
        self.minion('aura', attack=2, health=5, keyword_auras=(WIND,))
        self.minion('sleep', health=5, dormant_turns=None, keyword_auras=(WIND,))
        self.r.register_behavior('noop', lambda c: [])
        self.r.register_card(CardDefinition('site', 'site', CardType.LOCATION, durability=2, on_use='noop'))
        self.r.register_card(CardDefinition('wind_weapon', 'weapon', CardType.WEAPON, attack=2, durability=3,
            keywords=(Keyword.WINDFURY,)))
        self.r.register_card(CardDefinition('plain_weapon', 'weapon', CardType.WEAPON, attack=2, durability=3))
        for name, fn in (
            ('silence', lambda c: [Silence(c.target_id)]),
            ('kill', lambda c: [Destroy(c.target_id)]),
            ('bounce', lambda c: [ReturnToHand(c.target_id)]),
            ('transform', lambda c: [Transform(c.target_id, 'plain')]),
            ('steal', lambda c: [ChangeControl(c.target_id, 2)]),
            ('copy', lambda c: [CopyMinion(c.target_id, 1)]),
            ('copy_base', lambda c: [CopyMinion(c.target_id, 1, mode='base')]),
            ('sleep', lambda c: [MakeDormant(c.target_id, None)]),
            ('wake', lambda c: [AwakenMinion(c.target_id)]),
            ('grant', lambda c: [GrantKeywordAura(c.target_id, WIND, c.source_id)]),
            ('grant_turn', lambda c: [GrantKeywordAura(c.target_id, WIND, c.source_id, c.state.turn)]),
            ('native', lambda c: [GrantKeyword(c.target_id, Keyword.WINDFURY)]),
            ('freeze', lambda c: [Freeze(c.target_id)]),
            ('unfreeze', lambda c: [Unfreeze(c.target_id)]),
        ):
            # Avoid fixture ID collision between a dormant minion and its spell.
            self.spell('do_'+name, fn, requires_target=True)
        self.spell('replace', lambda c: [ReplaceHero(1, 'hero')])
        self.spell('summon', lambda c: [Summon(1, 'aura')])

    def minion(self, name, **kw):
        self.r.register_card(CardDefinition(name, name, CardType.MINION, **kw))
    def spell(self, name, fn, **kw):
        self.r.register_behavior(name, fn)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, **kw))
    def game(self, board=('aura',), hand=(), enemy=(), enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', board=board, hand=hand, deck=('plain',)*8, max_mana=10, mana=10),
            PlayerSetup('HERO_01', board=enemy, hand=enemy_hand, deck=('plain',)*8, max_mana=10, mana=10)
        ), seed=149), self.r)
    def play(self, g, name, target=None):
        p = g.state.active_player
        i = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == name)
        g.apply(PlayCard(p, i, target)); return i
    def hero(self, g, p=1):
        return g.state.entities[g.state.players[p].hero_id]
    def board(self, g, p=1):
        return [g.state.entities[i] for i in g.state.players[p].board]
    def attack(self, g, target=None):
        g.apply(Attack(1, self.hero(g).id, target or self.hero(g, 2).id))
    def has_wind(self, g, expected=True, p=1):
        self.assertEqual(Keyword.WINDFURY in self.hero(g, p).keywords, expected)
    def check(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot, self.r).snapshot(), snapshot)
        self.assertEqual(g.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), snapshot)

    def test_hero_aura_is_derived_and_controller_local(self):
        g = self.game()
        self.has_wind(g); self.has_wind(g, False, 2)
        self.assertFalse(any(a.kind == 'keyword' for a in self.hero(g).abilities))
        self.assertNotIn(Keyword.WINDFURY, self.board(g)[0].keywords)
        self.assertEqual(self.hero(g).aura_keywords, {Keyword.WINDFURY}); self.check(g)

    def test_real_body_summons_limbs_and_hero_attacks_twice(self):
        g = self.game(board=(), hand=('CATA_151',))
        self.play(g, 'CATA_151')
        self.assertEqual([e.card_id for e in self.board(g)], ['CATA_151t', 'CATA_151', 'CATA_151t1'])
        self.assertEqual(self.hero(g).attack, 4)
        self.attack(g); self.attack(g)
        self.assertEqual(self.hero(g, 2).health, 22)
        with self.assertRaises(IllegalAction): self.attack(g)
        self.check(g)

    def test_herald_scales_limbs_but_never_attack_quota(self):
        self.spell('herald4', lambda c: [GainArmor(2, 20), *([Herald(1)]*4)])
        g = self.game(board=(), hand=('herald4', 'CATA_151'))
        self.play(g, 'herald4'); self.play(g, 'CATA_151')
        self.assertEqual(self.hero(g).attack, 16)  # Four soldiers + two empowered limbs.
        self.attack(g); self.attack(g)
        with self.assertRaises(IllegalAction): self.attack(g)
        self.check(g)

    def test_silence_body_does_not_remove_limb_attack_buff(self):
        g = self.game(board=(), hand=('CATA_151', 'do_silence'))
        body = self.play(g, 'CATA_151'); self.play(g, 'do_silence', body)
        self.has_wind(g, False); self.assertEqual(self.hero(g).attack, 4); self.check(g)

    def test_full_board_body_still_supplies_aura(self):
        g = self.game(board=('plain',)*6, hand=('CATA_151',))
        self.play(g, 'CATA_151')
        self.assertEqual(len(self.board(g)), 7); self.assertEqual(self.hero(g).attack, 2)
        self.has_wind(g); self.check(g)

    def test_damage_to_source_does_not_disable_aura(self):
        self.spell('hit', lambda c: [Damage(c.target_id, 4)], requires_target=True)
        g = self.game(hand=('hit',)); self.play(g, 'hit', self.board(g)[0].id)
        self.assertEqual(self.board(g)[0].health, 1); self.has_wind(g); self.check(g)

    def test_source_removal_lifecycles(self):
        for spell in ('do_kill', 'do_silence', 'do_bounce', 'do_transform', 'do_sleep'):
            with self.subTest(spell=spell):
                g = self.game(hand=(spell,)); self.play(g, spell, self.board(g)[0].id)
                self.has_wind(g, False); self.check(g)

    def test_control_transfer_retargets_hero(self):
        g = self.game(hand=('do_steal',)); self.play(g, 'do_steal', self.board(g)[0].id)
        self.has_wind(g, False); self.has_wind(g, True, 2); self.check(g)

    def test_dormant_source_awakes_and_restores_aura(self):
        self.spell('awaken', lambda c: [AwakenMinion(c.state.players[1].board[0])])
        g = self.game(board=('sleep',), hand=('awaken',))
        self.has_wind(g, False); self.play(g, 'awaken')
        self.has_wind(g); self.check(g)

    def test_multiple_sources_union_and_last_removal(self):
        g = self.game(board=('aura', 'aura'), hand=('do_silence', 'do_kill'))
        first, second = self.board(g)
        self.play(g, 'do_silence', first.id); self.has_wind(g)
        self.attack(g); self.attack(g)
        self.play(g, 'do_kill', second.id); self.has_wind(g, False)
        self.assertEqual(self.hero(g).attacks_this_turn, 2); self.check(g)

    def test_gaining_wind_after_first_attack_opens_one_more(self):
        g = self.game(board=(), hand=('summon',))
        self.attack(g); self.play(g, 'summon'); self.attack(g)
        with self.assertRaises(IllegalAction): self.attack(g)
        self.check(g)

    def test_losing_and_regaining_wind_never_resets_attack_count(self):
        g = self.game(hand=('do_silence', 'summon', 'do_silence', 'summon'))
        self.attack(g); self.play(g, 'do_silence', self.board(g)[0].id)
        with self.assertRaises(IllegalAction): self.attack(g)
        self.play(g, 'summon'); self.attack(g)
        self.play(g, 'do_silence', self.board(g)[1].id); self.play(g, 'summon')
        with self.assertRaises(IllegalAction): self.attack(g)
        self.check(g)

    def test_weapon_and_aura_windfury_do_not_multiply(self):
        g = self.game(hand=('wind_weapon', 'do_silence'))
        self.play(g, 'wind_weapon'); self.attack(g); self.attack(g)
        self.play(g, 'do_silence', self.board(g)[0].id); self.has_wind(g)
        with self.assertRaises(IllegalAction): self.attack(g)
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].durability, 1); self.check(g)

    def test_weapon_break_leaves_aura_and_other_hero_attack(self):
        self.spell('wear', lambda c: [ModifyWeapon(c.state.players[1].weapon_id, durability=-2)])
        g = self.game(hand=('wind_weapon', 'wear'))
        self.play(g, 'wind_weapon'); self.play(g, 'wear'); self.attack(g)
        self.assertIsNone(g.state.players[1].weapon_id); self.has_wind(g)
        self.assertEqual(self.hero(g).attack, 2); self.attack(g); self.check(g)

    def test_plain_weapon_replacement_keeps_aura_and_attack_usage(self):
        g = self.game(hand=('wind_weapon', 'plain_weapon', 'do_silence'))
        self.play(g, 'wind_weapon'); self.attack(g); self.play(g, 'plain_weapon')
        self.has_wind(g); self.play(g, 'do_silence', self.board(g)[0].id)
        self.has_wind(g, False)
        with self.assertRaises(IllegalAction): self.attack(g)
        self.check(g)

    def test_granted_intrinsic_wind_survives_source_removal(self):
        g = self.game(hand=('do_native', 'do_silence'))
        self.play(g, 'do_native', self.hero(g).id); self.play(g, 'do_silence', self.board(g)[0].id)
        self.has_wind(g); self.assertFalse(self.hero(g).aura_keywords); self.check(g)

    def test_freeze_blocks_windfury_and_unfreeze_keeps_usage(self):
        g = self.game(hand=('do_freeze', 'do_unfreeze'))
        self.attack(g); self.play(g, 'do_freeze', self.hero(g).id)
        with self.assertRaises(IllegalAction): self.attack(g)
        self.play(g, 'do_unfreeze', self.hero(g).id); self.attack(g)
        with self.assertRaises(IllegalAction): self.attack(g)
        self.check(g)

    def test_turn_boundary_expires_attack_bonus_but_not_aura(self):
        g = self.game(board=(), hand=('CATA_151',)); self.play(g, 'CATA_151')
        self.attack(g); self.attack(g); g.apply(EndTurn(1))
        self.has_wind(g); self.assertEqual(self.hero(g).attack, 2)
        g.apply(EndTurn(2)); self.attack(g); self.attack(g); self.check(g)

    def test_hero_replacement_retargets_without_copying_cache(self):
        g = self.game(hand=('replace', 'do_silence'))
        old = self.hero(g).id; self.attack(g); self.play(g, 'replace')
        self.assertNotEqual(old, self.hero(g).id); self.has_wind(g)
        self.assertFalse(g.state.entities[old].aura_keywords)
        self.attack(g); self.play(g, 'do_silence', self.board(g)[0].id)
        self.has_wind(g, False); self.assertEqual(self.hero(g).attacks_this_turn, 2); self.check(g)

    def test_real_hero_card_receives_existing_aura(self):
        g = self.game(hand=('CATA_190h',)); self.play(g, 'CATA_190h')
        self.has_wind(g); self.assertIsNotNone(g.state.pending_choice); self.check(g)

    def test_dynamic_grant_expiry(self):
        g = self.game(board=('plain',), hand=('do_grant_turn',))
        self.play(g, 'do_grant_turn', self.board(g)[0].id); self.has_wind(g)
        g.apply(EndTurn(1)); self.has_wind(g, False); self.check(g)

    def test_dynamic_grant_survives_silenced_source_until_silenced_again(self):
        g = self.game(hand=('do_silence', 'do_grant', 'do_silence'))
        i = self.board(g)[0].id
        self.play(g, 'do_silence', i); self.play(g, 'do_grant', i); self.has_wind(g)
        self.play(g, 'do_silence', i); self.has_wind(g, False); self.check(g)

    def test_source_copy_owns_independent_aura_instance(self):
        g = self.game(hand=('do_copy', 'do_kill'))
        i = self.board(g)[0].id; self.play(g, 'do_copy', i)
        abilities = [next(a for a in e.abilities if a.kind == 'keyword_aura').id for e in self.board(g)]
        self.assertEqual(len(set(abilities)), 2)
        self.play(g, 'do_kill', i); self.has_wind(g); self.check(g)

    def test_base_copy_restores_silenced_printed_aura(self):
        g = self.game(hand=('do_silence', 'do_copy_base'))
        i = self.board(g)[0].id; self.play(g, 'do_silence', i); self.play(g, 'do_copy_base', i)
        self.has_wind(g); self.check(g)

    def test_copy_beneficiary_does_not_capture_external_keyword(self):
        self.minion('minion_aura', health=5, keyword_auras=(KeywordAuraSpec(Keyword.WINDFURY, 'friendly_minions'),))
        g = self.game(board=('minion_aura', 'plain'), hand=('do_copy', 'do_kill'))
        source, target = self.board(g)
        self.play(g, 'do_copy', target.id); self.play(g, 'do_kill', source.id)
        self.assertTrue(all(Keyword.WINDFURY not in e.keywords for e in self.board(g))); self.check(g)

    def test_beneficiary_silence_does_not_remove_external_keyword(self):
        self.minion('minion_aura', health=5, keyword_auras=(KeywordAuraSpec(Keyword.WINDFURY, 'friendly_minions'),))
        g = self.game(board=('minion_aura', 'plain'), hand=('do_silence',))
        self.play(g, 'do_silence', self.board(g)[1].id)
        self.assertIn(Keyword.WINDFURY, self.board(g)[1].keywords); self.check(g)

    def test_physical_adjacent_scope_does_not_skip_location_or_dormant(self):
        self.minion('neighbor', health=5, keyword_auras=(KeywordAuraSpec(Keyword.WINDFURY, 'friendly_minions', adjacent_only=True),))
        g = self.game(board=('plain', 'site', 'neighbor', 'sleep', 'plain'))
        self.assertTrue(all(Keyword.WINDFURY not in e.keywords for e in self.board(g)))
        self.check(g)

    def test_adjacent_retargets_after_position_changes(self):
        self.minion('neighbor', health=5, keyword_auras=(KeywordAuraSpec(Keyword.WINDFURY, 'friendly_minions', adjacent_only=True),))
        g = self.game(board=('plain', 'neighbor', 'plain', 'plain'), hand=('do_kill',))
        left, source, right, far = self.board(g)
        self.assertNotIn(Keyword.WINDFURY, far.keywords)
        self.play(g, 'do_kill', right.id)
        self.assertIn(Keyword.WINDFURY, g.state.entities[far.id].keywords); self.check(g)

    def test_include_self_and_intrinsic_flags_union(self):
        self.minion('self_aura', health=5, keywords=(Keyword.TAUNT,),
            keyword_auras=(KeywordAuraSpec(Keyword.WINDFURY, 'friendly_minions', include_self=True),))
        g = self.game(board=('self_aura', 'plain'))
        self.assertEqual(self.board(g)[0].keywords, {Keyword.TAUNT, Keyword.WINDFURY}); self.check(g)

    def test_continuous_taunt_participates_in_attack_targeting(self):
        self.minion('taunt_aura', health=5, keyword_auras=(KeywordAuraSpec(Keyword.TAUNT, 'friendly_minions'),))
        g = self.game(board=(), enemy=('taunt_aura', 'plain'))
        with self.assertRaises(IllegalAction): self.attack(g)
        with self.assertRaises(IllegalAction): self.attack(g, self.board(g, 2)[0].id)
        self.attack(g, self.board(g, 2)[1].id); self.check(g)

    def test_continuous_charge_allows_new_minion_to_attack_hero(self):
        self.minion('charge_aura', health=5, keyword_auras=(KeywordAuraSpec(Keyword.CHARGE, 'friendly_minions'),))
        self.spell('recruit', lambda c: [Summon(1, 'plain')])
        g = self.game(board=('charge_aura',), hand=('recruit',))
        self.play(g, 'recruit'); g.apply(Attack(1, self.board(g)[1].id, self.hero(g, 2).id))
        self.assertEqual(self.hero(g, 2).health, 28); self.check(g)

    def test_continuous_rush_restricts_new_minion_to_minion_target(self):
        self.minion('rush_aura', health=5, keyword_auras=(KeywordAuraSpec(Keyword.RUSH, 'friendly_minions'),))
        self.spell('recruit', lambda c: [Summon(1, 'plain')])
        g = self.game(board=('rush_aura',), hand=('recruit',), enemy=('plain',))
        self.play(g, 'recruit'); recruit = self.board(g)[1].id
        with self.assertRaises(IllegalAction): g.apply(Attack(1, recruit, self.hero(g, 2).id))
        g.apply(Attack(1, recruit, self.board(g, 2)[0].id)); self.check(g)

    def test_continuous_lifesteal_heals_from_hero_combat(self):
        self.minion('leech_aura', health=5, keyword_auras=(KeywordAuraSpec(Keyword.LIFESTEAL),))
        self.spell('hurt', lambda c: [Damage(c.state.players[1].hero_id, 5)])
        g = self.game(board=('leech_aura',), hand=('hurt',))
        self.play(g, 'hurt'); self.attack(g)
        self.assertEqual(self.hero(g).health, 27); self.check(g)

    def test_continuous_poisonous_kills_combat_minion(self):
        self.minion('poison_aura', health=5, keyword_auras=(KeywordAuraSpec(Keyword.POISONOUS),))
        g = self.game(board=('poison_aura',), enemy=('plain',))
        self.attack(g, self.board(g, 2)[0].id)
        self.assertEqual(self.board(g, 2), []); self.check(g)

    def test_continuous_immune_blocks_damage_until_source_removed(self):
        self.minion('immune_aura', health=5, keyword_auras=(KeywordAuraSpec(Keyword.IMMUNE),))
        self.spell('hurt', lambda c: [Damage(c.state.players[1].hero_id, 5)])
        g = self.game(board=('immune_aura',), hand=('hurt', 'do_silence', 'hurt'))
        self.play(g, 'hurt'); self.assertEqual(self.hero(g).health, 30)
        self.play(g, 'do_silence', self.board(g)[0].id); self.play(g, 'hurt')
        self.assertEqual(self.hero(g).health, 25); self.check(g)

    def test_continuous_elusive_blocks_spell_target_but_not_attack(self):
        self.minion('elusive_aura', health=5, keyword_auras=(KeywordAuraSpec(Keyword.ELUSIVE),))
        g = self.game(board=(), enemy=('elusive_aura',), hand=('CS2_029',))
        with self.assertRaises(IllegalAction): self.play(g, 'CS2_029', self.hero(g, 2).id)
        self.attack(g); self.assertEqual(self.hero(g, 2).health, 28); self.check(g)

    def test_source_and_beneficiary_death_record_keeps_final_aura(self):
        self.minion('minion_aura', health=5, keyword_auras=(KeywordAuraSpec(Keyword.WINDFURY, 'friendly_minions'),))
        self.spell('batch', lambda c: [DamageBatch(tuple(Damage(i, 9) for i in c.state.players[1].board))])
        g = self.game(board=('minion_aura', 'plain'), hand=('batch',))
        self.play(g, 'batch')
        record = next(d for d in g.state.death_history if d.card_id == 'plain')
        self.assertIn(Keyword.WINDFURY, record.keywords)
        self.assertFalse(any(e.aura_keywords for e in g.state.entities.values())); self.check(g)

    def test_silenced_current_copy_stays_silenced(self):
        g = self.game(hand=('do_silence', 'do_copy'))
        i = self.board(g)[0].id; self.play(g, 'do_silence', i); self.play(g, 'do_copy', i)
        self.has_wind(g, False); self.check(g)

    def test_bounce_and_replay_resets_dynamic_aura(self):
        g = self.game(board=('plain',), hand=('do_grant', 'do_bounce'))
        i = self.board(g)[0].id
        self.play(g, 'do_grant', i); self.play(g, 'do_bounce', i); self.play(g, 'plain')
        self.has_wind(g, False); self.check(g)

    def test_pending_choice_roundtrip_preserves_typed_aura_effect(self):
        self.spell('choose', lambda c: [RequestChoice(1, (ChoiceOption('wind', 'Windfury',
            (GrantKeywordAura(c.state.players[1].board[0], WIND, c.source_id),)),))])
        g = self.game(board=('plain',), hand=('choose',)); self.play(g, 'choose'); self.check(g)
        restored = Game.from_snapshot(g.snapshot(), self.r)
        for match in (g, restored):
            match.apply(SelectChoice(1, match.state.pending_choice.id, ('wind',)))
            self.has_wind(match); self.check(match)
        self.assertEqual(g.snapshot(), restored.snapshot())

    def test_snapshot_rejects_tampered_derived_cache(self):
        g = self.game()
        for field, value in (('aura_keywords', []), ('keywords', []), ('aura_keywords', ['taunt'])):
            with self.subTest(field=field, value=value):
                s = g.snapshot(); s['state']['entities'][str(self.hero(g).id)][field] = value
                with self.assertRaises(SnapshotError): Game.from_snapshot(s, self.r)

    def test_snapshot_rejects_malformed_aura_spec(self):
        g = self.game()
        for field, value in (('keyword', 'reborn'), ('target', 'enemy_hero'), ('include_self', 1)):
            with self.subTest(field=field):
                s = g.snapshot(); row = s['state']['entities'][str(self.board(g)[0].id)]
                next(a for a in row['abilities'] if a['kind'] == 'keyword_aura')['keyword_aura'][field] = value
                with self.assertRaises(SnapshotError): Game.from_snapshot(s, self.r)

    def test_snapshot_rejects_old_schema(self):
        g = self.game(); s = g.snapshot(); s['schema_version'] = 38
        with self.assertRaises(SnapshotError): Game.from_snapshot(s, self.r)

    def test_grant_bad_source_rolls_back_entire_action(self):
        self.spell('bad', lambda c: [Damage(c.state.players[2].hero_id, 1),
            GrantKeywordAura(c.state.players[1].board[0], WIND, 999999)])
        g = self.game(board=('plain',), hand=('bad',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'bad')
        self.assertEqual(g.snapshot(), before)

    def test_unsupported_consumable_and_special_keywords_rejected(self):
        for keyword in (Keyword.DIVINE_SHIELD, Keyword.STEALTH, Keyword.REBORN, Keyword.TITAN,
                        Keyword.SPELLBURST, Keyword.HERALD, 'windfury'):
            with self.subTest(keyword=keyword), self.assertRaises(ValueError): KeywordAuraSpec(keyword)

    def test_invalid_definition_and_ability_combinations_rejected(self):
        for kw in ({'target': 'enemy_hero'}, {'include_self': True}, {'adjacent_only': True},
                   {'target': 'friendly_minions', 'include_self': True, 'adjacent_only': True}):
            with self.subTest(kw=kw), self.assertRaises(ValueError): KeywordAuraSpec(Keyword.WINDFURY, **kw)
        with self.assertRaises(ValueError):
            self.r.register_card(CardDefinition('bad', 'bad', CardType.SPELL, keyword_auras=(WIND,)))
        with self.assertRaises(ValueError): AbilityInstance(1, 'keyword_aura')
        with self.assertRaises(ValueError): AbilityInstance(1, 'spell_damage', spell_damage=1, keyword_aura=WIND)

    def test_player_api_observes_aura_and_removes_second_attack(self):
        g = self.game(hand=('do_silence',)); self.attack(g)
        port = g.for_player(1); listing = port.legal_actions()
        hero_ref = next(p for p in listing['observation']['players'] if p['id'] == 1)['hero']['ref']
        self.assertTrue(any(a['type'] == 'attack' and a['attacker'] == hero_ref for a in listing['actions']))
        self.play(g, 'do_silence', self.board(g)[0].id)
        self.assertFalse(any(a['type'] == 'attack' and a['attacker'] == hero_ref for a in port.legal_actions()['actions']))
        self.assertNotIn('aura_keywords', json.dumps(g.observe(2)))
        self.check(g)


if __name__ == '__main__': unittest.main()
