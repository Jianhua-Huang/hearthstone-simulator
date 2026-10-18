"""Real Leyline roots: one CAST, original numeric/effect quote, shared delivery."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import random
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_leyline_cards import (BURST, WALKER, CRYSTAL, NEEDLE, NEXUS,
    MAP, CAT, ROOTS, CHARGE, CHANNEL, ENHANCE, CHOICES, FAMILY, PREFIX, POOL,
    load_batch, register_native_leyline_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, Keyword, PlayCard, PlayerSetup, Rarity, Registry, Scenario, SelectChoice,
    TargetSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Damage,
    Destroy, EquipWeapon, RandomDamage, RequestChoice, Summon)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import (DamageKind, HealthFlow, HealthLayer, HealthOp,
    HealthRule, LimitedTriggerSpec, PlayerEffectSpec, SpellEffectModifierSpec, SpellSchool)
from hs_sim.engine.player_effects import AddPlayerEffect, spell_effect_values
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import canonical_digest

P = 'k190.'
HERO, FILL, TINY, THREE, PARENT, CHILD, POWER, SCALE = (P+n for n in (
    'hero', 'filler', 'tiny', 'three', 'parent', 'child', 'power', 'scale'))
SIX, SIX_OTHER, SEVEN, EIGHT, HIDDEN, SPELL, UNKNOWN = (P+n for n in (
    'six', 'other_six', 'seven', 'eight', 'hidden', 'spell', 'unknown'))
MEMBERS = (SIX, SIX_OTHER, SEVEN, EIGHT, HIDDEN, SPELL)
CTX = GenerationContext('k190-full-explicit-minions', 'experimental')
META = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON)


@lru_cache(maxsize=None)
def registry(mode=None, members=MEMBERS, pool=True):
    r = Registry('k190-actual-leylines-'+str(mode))
    register_native_leyline_cards(r)
    for cid, kind, fields in (
        (HERO, CardType.HERO, dict(health=100)), (FILL, CardType.MINION, dict(cost=10, attack=1, health=20)),
        (TINY, CardType.MINION, dict(health=2)), (THREE, CardType.MINION, dict(health=3)),
        (CHILD, CardType.MINION, dict(health=1)),
        (POWER, CardType.MINION, dict(health=20, spell_damage=5)),
        (SCALE, CardType.MINION, dict(health=20, health_rules=(HealthRule(HealthFlow.DAMAGE,
            HealthOp.SCALE, 2, layer=HealthLayer.SOURCE, source_relation='friendly'),))),
    ):
        r.register_card(CardDefinition(cid, cid, kind, **fields))
    r.register_behavior(P+'child', lambda c:(Summon(c.player_id, CHILD),))
    r.register_card(CardDefinition(PARENT, PARENT, CardType.MINION, health=2, deathrattle=P+'child'))
    for cid, cost, collectible, cls in ((SIX,6,True,CardClass.MAGE), (SIX_OTHER,6,True,CardClass.WARRIOR),
            (SEVEN,7,True,CardClass.NEUTRAL), (EIGHT,8,True,CardClass.NEUTRAL), (HIDDEN,6,False,CardClass.MAGE)):
        d = CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=2, health=20,
            metadata=replace(META, collectible=collectible, classes=(cls,)))
        r.register_card(d); r.register_pool_card(PoolCard.from_definition(d))
    r.register_card(CardDefinition(SPELL, SPELL, CardType.SPELL, cost=6, metadata=META))
    r.register_pool_card(PoolCard.from_definition(r.card(SPELL)))
    if UNKNOWN in members:
        r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 6, META,
            battlecry=False, deathrattle=False, choose_one=False))
    if pool:
        r.register_pool(PoolDefinition(POOL, 'k190-explicit-v1', CTX.target_id, CTX.mode,
            tuple(PoolMember(c, 3 if c == SIX_OTHER else 1) for c in members), complete=True))
    bodies = dict(kill=lambda c:(Destroy(c.target_id, c.source_id),),
        take=lambda c:(ChangeControl(c.target_id, 2),),
        enemy_cast=lambda c:(CastSpell(2, BURST, c.source_id),))
    for name, fn in bodies.items():
        r.register_behavior(P+name, fn)
        kwargs = dict(targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))) if name != 'enemy_cast' else {}
        r.register_card(CardDefinition(P+name, P+name, CardType.SPELL, on_play=P+name, **kwargs))
    if mode:
        event = 'health_resolved' if mode == 'damage' else 'card_drawn' if mode == 'draw' else 'minion_summoned'
        def eligible(c):
            if mode == 'damage':
                v = health_result(c.event)
                return v is not None and v.source_card_id == BURST and v.target_kind == 'minion'
            return (c.event.player_id == c.player_id and c.event.target_id is not None and
                c.state.entities[c.event.target_id].card_id in (FILL, SIX, SIX_OTHER, SEVEN, EIGHT))
        def watch(c):
            options = [ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Rollback random failure', (
                RandomDamage((c.state.players[2].hero_id,), 1, c.source_id), EquipWeapon(1, FILL))),
                ChoiceOption('rng', 'Consume ordinary reaction RNG', (
                    RandomDamage((c.state.players[2].hero_id,), 1, c.source_id),))]
            sources = {c.state.entities[i].card_id:i for i in c.state.players[1].board}
            if CAT in sources and NEEDLE in sources:
                options.append(ChoiceOption('upgrade', 'Install actual original source programs', (
                    AddPlayerEffect(1, PREFIX+CAT, sources[CAT]), AddPlayerEffect(1, PREFIX+NEEDLE, sources[NEEDLE]))))
            return (RequestChoice(c.player_id, tuple(options), c.source_id),)
        r.register_trigger_condition(P+'eligible', eligible); r.register_behavior(P+'watch', watch)
        r.register_card(CardDefinition(P+'watch', P+'watch', CardType.MINION, health=20,
            limited_triggers=(LimitedTriggerSpec(event, P+'watch', condition_id=P+'eligible'),)))
    r.validate(); return r


class NativeLeylineTests(unittest.TestCase):
    def game(self, hand=(BURST,), board=(), enemy=(), deck=(FILL,)*6,
            mode=None, members=MEMBERS, pool=True, enemy_hand=()):
        self.config = (mode, members, pool)
        if mode: board = (*board, P+'watch')
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO, hand=hand, board=board, deck=deck, mana=50, max_mana=50, mana_cap=50),
            PlayerSetup(HERO, hand=enemy_hand, board=enemy, deck=(FILL,)*6, mana=50, max_mana=50, mana_cap=50)),
            seed=190, generation_context=CTX), registry(*self.config))

    def play(self, g, cid=BURST, target=None, p=1):
        i = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(p, i, target)); return i

    def first(self, g, cid, zone='board', p=1):
        return next(i for i in getattr(g.state.players[p], zone) if g.state.entities[i].card_id == cid)

    def hero_health(self, g, p=2): return g.state.entities[g.state.players[p].hero_id].health
    def casts(self, g, cid): return [r for r in g.state.cast_history if r.card_id == cid]
    def choices(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def values(self, g):
        return [v for e in g.events if (v:=health_result(e)) is not None and v.source_card_id == BURST]
    def cost(self, g, cid): return g.quote_cost(self.first(g, cid, 'hand')).amount
    def portable(self, g):
        s = json.loads(json.dumps(g.snapshot())); reader = registry.__wrapped__(*self.config)
        self.assertIsNot(reader, g.registry)
        other = Game.from_snapshot(deepcopy(s), reader)
        self.assertEqual(other.snapshot(), s); self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), s); return other

    def test_complete_seven_roots_three_choice_only_upgrades_and_twenty_primary_faces(self):
        d = load_batch(); r = registry()
        self.assertEqual(len(d['official_observations']), 20)
        self.assertEqual(d['initial_primary_values'], {BURST:4, CRYSTAL:6, NEXUS:1})
        for item in d['cards']+d['dependencies']:
            raw = item['record']; self.assertEqual(canonical_digest(raw), item['record_sha256'])
            self.assertEqual(r.card(raw['id']).metadata, metadata_from_record(raw))
        self.assertTrue(all(r.card(c).choice_only and r.card(c).cost == 0 for c in CHOICES))
        self.assertTrue(all(r.card(c).spell_school == SpellSchool.ARCANE for c in FAMILY+(MAP,)))
        self.assertIn(Keyword.ELUSIVE, r.card(CAT).keywords)
        self.assertFalse(d['formal_pool_complete'] or d['cn_calibrated'])

    def test_burst_immune_four_budget_partitions_once_and_pays_once(self):
        g = self.game(board=(POWER,), enemy=(TINY,)); self.play(g)
        self.assertEqual(self.hero_health(g), 98)
        self.assertEqual(g.state.players[1].mana, 46)
        self.assertEqual(len(self.casts(g, BURST)), 1)
        self.assertEqual([v.spell_bonus for v in self.values(g)], [0, 0])
        self.assertEqual(sum(v.damage_dealt for v in self.values(g)), 4)

    def test_burst_empty_enemy_minions_never_hits_hero_or_consumes_rng(self):
        g = self.game(); before = g.snapshot()['rng_state']; self.play(g)
        self.assertEqual((self.hero_health(g), self.values(g)), (100, []))
        self.assertEqual(g.snapshot()['rng_state'], before)

    def test_extra_effects_requery_deathrattle_new_minion_with_one_cast(self):
        g = self.game((NEEDLE, BURST), enemy=(PARENT,)); self.play(g, NEEDLE); self.play(g)
        self.assertEqual(self.hero_health(g), 95)
        self.assertFalse(g.state.players[2].board)
        self.assertEqual(len(self.casts(g, BURST)), 1)
        self.assertEqual(len([e for e in g.events if e.kind == 'random_choice' and e.source_id == self.casts(g, BURST)[0].source_id]), 2)

    def test_power_and_effect_count_stack_independently(self):
        g = self.game((CAT, NEEDLE, BURST), enemy=(TINY, THREE)); self.play(g, CAT); self.play(g, NEEDLE); self.play(g)
        self.assertEqual(self.hero_health(g), 95)
        self.assertFalse(g.state.players[2].board)
        self.assertEqual(sum(v.damage_dealt for v in self.values(g)), 10)
        self.assertEqual(len(self.casts(g, BURST)), 1)

    def test_other_source_numeric_rule_still_scales_immune_whole_budget(self):
        g = self.game(board=(POWER, SCALE), enemy=(TINY,)); self.play(g)
        self.assertEqual(self.hero_health(g), 94)
        self.assertEqual(sum(v.damage_dealt for v in self.values(g)), 8)

    def test_nexus_primary_discount_and_extra_draws_use_actual_physical_arrivals(self):
        g = self.game((CAT, NEEDLE, NEXUS)); self.play(g, CAT); self.play(g, NEEDLE); self.play(g, NEXUS)
        hand = [g.state.entities[i] for i in g.state.players[1].hand]
        self.assertEqual([e.card_id for e in hand], [FILL, FILL])
        self.assertEqual([g.quote_cost(e.id).amount for e in hand], [8, 8])
        self.assertEqual(len(self.casts(g, NEXUS)), 1)

    def test_nexus_empty_deck_keeps_fatigue_and_no_fabricated_discount_target(self):
        g = self.game((NEXUS,), deck=()); self.play(g, NEXUS)
        self.assertEqual(self.hero_health(g, 1), 99)
        self.assertEqual(g.state.players[1].hand, [])

    def test_crystal_full_pool_keeps_both_classes_and_filters_wrong_kind_cost_and_noncollectible(self):
        g = self.game((CRYSTAL,)); self.play(g, CRYSTAL)
        cards = [g.state.entities[i].card_id for i in g.state.players[1].board]
        self.assertEqual(len(cards), 1); self.assertIn(cards[0], (SIX, SIX_OTHER))
        self.assertEqual(len(self.casts(g, CRYSTAL)), 1)
        self.assertEqual(g.state.players[1].mana, 45)

    def test_crystal_power_changes_tier_and_extra_effects_repeat_summon_not_cast(self):
        g = self.game((CAT, NEEDLE, CRYSTAL)); self.play(g, CAT); self.play(g, NEEDLE); self.play(g, CRYSTAL)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board].count(SEVEN), 2)
        self.assertEqual(len(self.casts(g, CRYSTAL)), 1)

    def test_qualifying_unknown_pool_member_rejects_before_rng_and_rolls_back_payment(self):
        g = self.game((CRYSTAL,), members=MEMBERS+(UNKNOWN,)); s = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, CRYSTAL)
        self.assertEqual(g.snapshot(), s)

    def test_empty_complete_tier_and_uninstalled_pool_do_not_crop_candidates(self):
        g = self.game((CRYSTAL,), members=(SEVEN,)); before = g.snapshot()['rng_state']; self.play(g, CRYSTAL)
        self.assertEqual(g.state.players[1].board, [])
        self.assertEqual(g.snapshot()['rng_state'], before)
        g = self.game((CRYSTAL,), pool=False); s = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, CRYSTAL)
        self.assertEqual(g.snapshot(), s)

    def test_full_board_crystal_keeps_original_selection_before_space_policy(self):
        g = self.game((CRYSTAL,), board=(FILL,)*7); before = g.snapshot()['rng_state']; self.play(g, CRYSTAL)
        self.assertEqual(len(g.state.players[1].board), 7)
        root, = g.state.pool_summon_history
        self.assertEqual((root.spec.count, len(root.selected), root.status), (1, 1, 'completed'))
        self.assertIn(root.selected[0], (SIX, SIX_OTHER))
        self.assertNotEqual(g.snapshot()['rng_state'], before)

    def test_walker_cost_is_permanent_family_only_and_death_gets_exact_real_member(self):
        g = self.game((WALKER, BURST, CRYSTAL, NEXUS, MAP, P+'kill')); source = self.play(g, WALKER)
        self.assertEqual([self.cost(g, c) for c in (BURST, CRYSTAL, NEXUS, MAP)], [3, 4, 1, 6])
        before = len(g.state.players[1].hand); self.play(g, P+'kill', source)
        self.assertEqual(len(g.state.players[1].hand), before)
        self.assertEqual(g.state.entities[g.state.players[1].hand[-1]].card_id in FAMILY, True)
        self.assertEqual(self.cost(g, BURST), 3)

    def test_stolen_walker_death_generates_for_actual_controller(self):
        g = self.game((P+'take', P+'kill'), board=(WALKER,)); source = self.first(g, WALKER)
        self.play(g, P+'take', source); self.play(g, P+'kill', source)
        self.assertEqual(g.state.players[1].hand, [])
        self.assertEqual(len(g.state.players[2].hand), 1)
        self.assertIn(g.state.entities[g.state.players[2].hand[0]].card_id, FAMILY)

    def test_map_gets_all_three_before_choice_and_charge_is_not_a_physical_cast(self):
        g = self.game((MAP,)); self.play(g, MAP)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [NEXUS, BURST, CRYSTAL])
        self.assertEqual([o.card_id for o in g.state.pending_choice.options], list(CHOICES))
        self.choices(g, 'charge')
        self.assertEqual(len(g.state.cast_history), 1)
        self.assertEqual(g.state.players[1].mana, 44)
        self.assertFalse(any(e.card_id in CHOICES for e in g.state.entities.values()))
        self.assertEqual(g.state.players[1].player_effects[0].source_card_id, MAP)

    def test_map_channel_reduces_all_real_leyline_prices_with_existing_zero_floor(self):
        g = self.game((MAP,)); self.play(g, MAP); self.choices(g, 'channel')
        self.assertEqual([self.cost(g, c) for c in (BURST, CRYSTAL, NEXUS)], [2, 3, 0])

    def test_map_enhance_changes_crystal_tier_to_eight(self):
        g = self.game((MAP,)); self.play(g, MAP); self.choices(g, 'enhance'); self.play(g, CRYSTAL)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], [EIGHT])

    def test_map_full_hand_burns_requested_cards_but_still_offers_upgrade(self):
        g = self.game((MAP,)+(FILL,)*9); self.play(g, MAP)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len([e for e in g.state.entities.values() if e.card_id in FAMILY and e.zone == Zone.GRAVEYARD]), 2)
        self.choices(g, 'enhance'); self.assertEqual(len(g.state.players[1].player_effects), 1)

    def test_map_wait_has_independent_restore_clone_replay_and_no_duplicate_gets(self):
        g = self.game((MAP,)); self.play(g, MAP); other = self.portable(g)
        for x in (g, other): self.choices(x, 'channel')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(g.state.players[1].hand), 3)

    def test_damage_wait_failure_rolls_back_and_original_quote_outlives_new_upgrades(self):
        g = self.game((BURST, BURST), board=(CAT, NEEDLE), enemy=(FILL,), mode='damage'); self.play(g)
        other = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choices(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        for x in (g, other): self.choices(x, 'upgrade')
        self.assertEqual(g.snapshot(), other.snapshot())
        enemy = self.first(g, FILL, p=2); self.assertEqual(g.state.entities[enemy].health, 16)
        self.play(g); self.assertEqual(g.state.entities[enemy].health, 6)
        self.assertEqual(len(self.casts(g, BURST)), 2)

    def test_draw_wait_preserves_actual_first_arrival_and_remaining_discount(self):
        g = self.game((NEEDLE, NEXUS), mode='draw'); self.play(g, NEEDLE); self.play(g, NEXUS)
        self.assertIsNotNone(g.state.pending_choice); first = g.state.players[1].hand[0]
        other = self.portable(g)
        for x in (g, other): self.choices(x)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.players[1].hand[0], first)
        self.assertEqual([g.quote_cost(i).amount for i in g.state.players[1].hand], [9, 9])

    def test_pool_summon_wait_resumes_without_resampling_first_or_duplicating_cast(self):
        g = self.game((NEEDLE, CRYSTAL), mode='summon'); self.play(g, NEEDLE); self.play(g, CRYSTAL)
        self.assertIsNotNone(g.state.pending_choice); original = tuple(g.state.players[1].board)
        other = self.portable(g)
        for x in (g, other): self.choices(x)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertTrue(all(i in g.state.players[1].board for i in original))
        self.assertEqual(len(self.casts(g, CRYSTAL)), 1)

    def test_extra_summon_effect_samples_only_after_previous_reaction_rng(self):
        g = self.game((NEEDLE, CRYSTAL), mode='summon'); self.play(g, NEEDLE); self.play(g, CRYSTAL)
        first, = g.state.pool_summon_history
        self.assertEqual((first.spec.count, len(first.selected)), (1, 1))
        probe = random.Random(); probe.setstate(g._rng.getstate()); probe.choice((g.state.players[2].hero_id,))
        expected_second_window = probe.getstate()
        self.choices(g, 'rng')
        first, second = g.state.pool_summon_history
        self.assertEqual(second.rng_before, expected_second_window)
        self.assertEqual((second.spec.count, len(second.selected)), (1, 1))
        self.assertEqual(len(self.casts(g, CRYSTAL)), 1)

    def test_out_of_turn_automatic_cast_uses_actual_casters_permanent_programs(self):
        g = self.game((P+'enemy_cast',), board=(TINY, THREE), enemy_hand=(NEEDLE,))
        g.apply(EndTurn(1)); self.play(g, NEEDLE, p=2); g.apply(EndTurn(2)); self.play(g, P+'enemy_cast')
        self.assertEqual(self.hero_health(g, 1), 97)
        self.assertFalse(g.state.players[1].board)
        self.assertEqual(self.casts(g, BURST)[0].player_id, 2)
        self.assertEqual(len(self.casts(g, BURST)), 1)

    def test_programs_survive_source_death_and_stack_from_repeated_real_sources(self):
        g = self.game((CAT, CAT, NEEDLE, P+'kill', BURST), enemy=(FILL,))
        self.play(g, CAT); self.play(g, CAT); source = self.play(g, NEEDLE); self.play(g, P+'kill', source); self.play(g)
        self.assertEqual(sum(v.damage_dealt for v in self.values(g)), 12)
        self.assertEqual(len(self.casts(g, BURST)), 1)

    def test_typed_modifier_guards_and_active_cast_requirement(self):
        for args in (((), 1, 0), (FAMILY, 1, 1), (FAMILY, 0, 2), (FAMILY, True, 0), (FAMILY, 0, 0)):
            with self.subTest(args=args), self.assertRaises(ValueError): SpellEffectModifierSpec(*args)
        with self.assertRaises(ValueError):
            PlayerEffectSpec('bad', CAT, kind='next_kindred', spell_effects=(SpellEffectModifierSpec(FAMILY, 1),))
        g = self.game()
        with self.assertRaises(ResolutionError): spell_effect_values(g.state, g.registry, None, 4)

    def test_choice_only_upgrade_cannot_be_materialized_as_a_spell_card(self):
        with self.assertRaises(ResolutionError): self.game((CHARGE,))

    def test_player_projection_has_no_internal_modifier_or_quote_fields(self):
        g = self.game((CAT, BURST)); self.play(g, CAT)
        for p in (1, 2):
            text = json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in ('spell_effects', 'additional_effects', 'value_add', 'resolution_frame'):
                self.assertNotIn('"'+key+'"', text)

    def test_current_assembly_adds_only_ten_defs_and_four_programs_and_rejects_old_schema(self):
        with patch('hs_sim.cards.native_leyline_cards.register_native_leyline_cards', lambda r:None): before = build_registry()
        after = build_registry(); self.assertEqual(set(after.cards)-set(before.cards), set(ROOTS+CHOICES))
        for c, d in before.cards.items(): self.assertEqual(asdict(d), asdict(after.card(c)))
        self.assertEqual(dict(before.pool_cards), dict(after.pool_cards))
        self.assertEqual(len(after.player_effects)-len(before.player_effects), 4)
        g = self.game(); s = g.snapshot(); s['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError): Game.from_snapshot(s, registry())


if __name__ == '__main__': unittest.main()
