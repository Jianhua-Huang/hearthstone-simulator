"""Real conditions and effects remain independent in assembled card faces."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import assemble_conditional_native_followups as cards
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID as ASSEMBLE_POOL
from hs_sim.engine import (
    Attack, CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    Keyword, PlayCard, PlayerSetup, Registry, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone,
)
from hs_sim.engine.assemble_faces import (
    AssembleRecipe, AssembleSuffix, CONDITION_PREFIX, conditional_parts,
    inner_condition_behavior_id, printed_face,
)
from hs_sim.engine.assemble_offers import ResolveAssemble
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (
    AddCostModifier, ChoiceOption, Damage, Destroy, Heal, InvokeBehavior, RequestChoice,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CostSpec, DamageKind, HealingKind, TribeChangeSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference, DiscardCard, ModifyStoredCost
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_draw_armor_heal_fragments import fixture as base_fixture, COIN, DECK, KILL, META, UNIT

ANSHE, GORILLA, CRYSTAL, SWORD_KEEPER, SURVIVOR, STORY_KEEPER, DRYAD = cards.SOURCES
LOOT, BEETLE, UNCONDITIONAL = 'CORE_EX1_096', 'CORE_LOOT_413', 'CORE_GIL_622'
TAELAN, CURATOR = 'CS3_024', 'CORE_KAR_061'
DRAGON, SHADOW, BIG, ARCANE = 'EDR_451', 'BE_724', 'CORE_CS2_032', 'CORE_CS2_023'
MECHS = ('CORE_GVG_044', 'CORE_GVG_085', 'CORE_GVG_076')
P = 'k417.'
HURT, HEAL, TAX, TO_DRAGON, TO_BEAST, WATCH_BC, FAIL, UNKNOWN_TYPE, UNKNOWN_MECH = (
    P + name for name in ('hurt', 'heal', 'tax', 'to_dragon', 'to_beast', 'watch_bc', 'fail',
                         'unknown_type', 'unknown_mech'))
CTX = GenerationContext('k417-native-conditions', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    registry = base_fixture.__wrapped__('no_pool', role)
    registry._version += '.k417.' + mode
    bodies = {
        HURT: lambda c: (Damage(c.target_id, 2, c.source_id, DamageKind.SPELL),),
        HEAL: lambda c: (Heal(c.target_id, 2, c.source_id, HealingKind.SPELL),),
        TAX: lambda c: (AddCostModifier(c.player_id,
            CostSpec(delta=2, card_types=(CardType.SPELL,)), uses_remaining=1, source_id=c.source_id),),
    }
    for cid, tribe in ((TO_DRAGON, 'dragon'), (TO_BEAST, 'beast')):
        bodies[cid] = lambda c, tribe=tribe: (ChangeMinionTribes(
            CardReference.capture(c.state.entities[c.target_id]),
            TribeChangeSpec('set', (tribe,)), c.source_id),)
    for cid, body in bodies.items():
        registry.register_behavior(cid, body)
        target = (TargetSpec(zones=(Zone.HAND,), kinds=(CardType.MINION,), relation='friendly')
            if cid in (TO_DRAGON, TO_BEAST) else None if cid == TAX else TargetSpec())
        registry.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            targeting=target, metadata=META))

    def fail(c):
        raise ResolutionError('deliberate conditional-native observer fault')

    def watch(c):
        if c.event.player_id != c.player_id or c.event.source_id is None:
            return ()
        current_id = c.state.entities[c.event.source_id].card_id
        if not current_id.startswith('assemble:') and current_id not in cards.SOURCES:
            return ()
        dragon = next(c.state.entities[eid] for eid in c.state.players[c.player_id].hand
            if c.state.entities[eid].card_id == DRAGON)
        options = [
            ChoiceOption('keep', 'Keep Dragon'),
            ChoiceOption('lose', 'Discard Dragon', (DiscardCard(CardReference.capture(dragon), c.source_id),)),
            ChoiceOption('kill', 'Remove carrier', (Destroy(c.event.source_id, c.source_id),)),
            ChoiceOption('hurt', 'Damage hero', (Damage(c.state.players[c.player_id].hero_id,
                2, c.source_id, DamageKind.EFFECT),)),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),)),
        ]
        big = next((c.state.entities[eid] for eid in c.state.players[c.player_id].hand
            if c.state.entities[eid].card_id == BIG), None)
        if big is not None:
            options.append(ChoiceOption('discount', 'Discount held spell', (ModifyStoredCost(
                CardReference.capture(big), CostSpec(set_to=4), c.source_id),)))
        outer = registry.card(current_id).battlecry
        if outer is not None and outer.startswith(CONDITION_PREFIX):
            row, _, _, _ = conditional_parts(registry, outer)
            if row['condition_id'] in registry.assemble_inner_conditions:
                data = dict(c.event.data)
                accepted = data['battlecry_id']
                wrong = accepted+1 if accepted == 1 else accepted-1
                options.append(ChoiceOption('wrong', 'Wrong accepted identity', (InvokeBehavior(
                    inner_condition_behavior_id(row['condition_id'], row['behavior_id'], wrong),
                    c.event.source_id, c.player_id, play_id=data['play_id']),)))
        return (RequestChoice(c.player_id, tuple(options), c.source_id),)

    registry.register_behavior(FAIL, fail)
    registry.register_behavior(WATCH_BC, watch)
    registry.register_card(CardDefinition(WATCH_BC, WATCH_BC, CardType.MINION, health=10,
        metadata=META, triggers=(TriggerSpec('battlecry_started', WATCH_BC),)))
    registry.register_card(CardDefinition(UNKNOWN_TYPE, UNKNOWN_TYPE, CardType.MINION, health=4,
        metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=None)))
    if mode != 'no_pool':
        members = tuple(PoolMember(cid) for cid in MECHS)
        if mode == 'unknown_mech':
            registry.register_pool_card(replace(registry.pool_card(MECHS[0]), card_id=UNKNOWN_MECH))
            members += (PoolMember(UNKNOWN_MECH),)
        registry.register_pool(PoolDefinition('constructed.cards', 'k417-three-real-neutral-mechs',
            CTX.target_id, CTX.mode, members, complete=True))
    # Native entry verification uses an explicit test domain, not a formal pool.
    registry.register_pool(PoolDefinition(ASSEMBLE_POOL, 'k417-real-low-primary-high-donors',
        CTX.target_id, CTX.mode, (PoolMember(CRYSTAL), PoolMember(TAELAN), PoolMember(CURATOR)),
        complete=True))
    registry.validate()
    return registry


class AssembleConditionalNativeFollowupTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), mode='normal', seed=417):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_09', hero_power_card_id='HERO_09bp', hand=hand, board=board,
                deck=DECK + (COIN,) * 10, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', board=enemy,
                deck=(COIN,) * 20, mana=30, max_mana=30, mana_cap=30)),
            seed=seed, generation_context=CTX), fixture(mode))

    def play(self, game, cid, target=None):
        player = game.state.active_player
        source = next(eid for eid in game.state.players[player].hand if game.state.entities[eid].card_id == cid)
        game.apply(PlayCard(player, source, target))
        return source

    def hero(self, game, player=1):
        return game.state.entities[game.state.players[player].hero_id]

    def drawn(self, game, player=1):
        return [row for row in game.state.draw_history if row.player_id == player]

    def choose(self, game, option='keep'):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def portable(self, game, mode='normal'):
        reader = fixture(mode, 'reader')
        self.assertIsNot(reader, game.registry)
        saved = json.loads(json.dumps(game.snapshot()))
        restored = Game.from_snapshot(saved, reader)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(game), reader).snapshot(), saved)
        for pid in (1, 2):
            visible = json.dumps(game.for_player(pid).observe()) + json.dumps(game.player_events(pid))
            for field in ('rng_state', 'behavior_id', 'condition_id', 'source_allocation'):
                self.assertNotIn('"' + field + '"', visible)
        return restored

    def test_a_eight_complete_records_sixteen_faces_and_full_original_native_bridges(self):
        data = cards.load_batch()
        registry = fixture()
        rows = {row['record']['id']: row for row in data['existing_dependencies']}
        self.assertEqual(tuple(rows), cards.SOURCES + (cards.SWORD,))
        self.assertEqual(len(data['official_observations']), 16)
        for obs in data['official_observations']:
            check_face(rows[obs['card_id']]['record'], obs['face'], obs['locale'])
            self.assertEqual(sha(Path(obs['response_file'])), obs['response_sha256'])
        for cid in cards.SOURCES:
            original = registry.card(cid)
            template = registry.assemble_templates[cid]
            full = printed_face(original, template.prefix, template.suffix, cid)
            self.assertEqual(replace(full, battlecry=template.original_battlecry_id), original)
            self.assertEqual(canonical_digest(asdict(original)), rows[cid]['definition_sha256'])
            self.assertEqual(template.original_battlecry_id, original.battlecry)
            self.assertEqual(template.prefix.keywords, original.keywords)
        self.assertEqual(canonical_digest(asdict(cards.QUERIES[cards.GORILLA])), data['mech_discovery_query_sha256'])

    def test_b_each_real_condition_stays_with_borrowed_prefix_and_does_not_apply_its_old_effect(self):
        for donor in cards.SOURCES:
            for enabled in (False, True):
                with self.subTest(donor=donor, enabled=enabled):
                    cid = AssembleRecipe(LOOT, donor, 'top').card_id
                    held = (() if not enabled else (SHADOW,) if donor == CRYSTAL else
                        (DRAGON,) if donor in (SWORD_KEEPER, STORY_KEEPER) else (BIG,) if donor == DRYAD else ())
                    history = donor in (ANSHE, SURVIVOR) and enabled
                    hand = (cid,) + held + ((HURT, HEAL) if history else ())
                    board = (MECHS[0],) if donor == GORILLA and enabled else ()
                    game = self.game(hand, board=board, mode='no_pool')
                    if history:
                        self.play(game, HURT, self.hero(game).id)
                        self.play(game, HEAL, self.hero(game).id)
                    source = self.play(game, cid)
                    self.assertEqual(len(self.drawn(game)), int(enabled))
                    self.assertEqual((game.state.entities[source].attack, game.state.entities[source].health),
                        (game.registry.card(LOOT).attack, game.registry.card(LOOT).health))
                    self.assertIsNone(game.state.pending_choice)
                    self.assertIsNone(game.state.players[1].weapon_id)
                    for keyword in game.registry.card(donor).keywords:
                        self.assertIn(keyword, game.state.entities[source].keywords)

    def test_c_each_distinct_borrowed_effect_runs_without_its_original_condition(self):
        seen = set()
        for donor, _, body in cards.RECIPES:
            if body in seen:
                continue
            seen.add(body)
            with self.subTest(donor=donor):
                cid = AssembleRecipe(UNCONDITIONAL, donor, 'bottom').card_id
                game = self.game((cid,))
                source = self.play(game, cid)
                entity = game.state.entities[source]
                base = game.registry.card(UNCONDITIONAL)
                if body in ('buff_three', 'buff_one'):
                    amount = 3 if body == 'buff_three' else 1
                    self.assertEqual((entity.attack, entity.health), (base.attack+amount, base.health+amount))
                elif body == 'discover_mech':
                    choice = game.state.pending_choice
                    self.assertEqual({option.card_id for option in choice.options}, set(MECHS))
                    selected = choice.options[0]
                    self.choose(game, selected.id)
                    self.assertEqual(game.state.entities[game.state.players[1].hand[-1]].card_id, selected.card_id)
                elif body == 'equip_sword':
                    weapon = game.state.entities[game.state.players[1].weapon_id]
                    self.assertEqual((weapon.card_id, weapon.attack, weapon.durability), (cards.SWORD, 2, 2))
                    game.apply(Attack(1, self.hero(game).id, self.hero(game, 2).id))
                    self.assertEqual((self.hero(game, 2).health, game.state.entities[weapon.id].durability), (28, 1))
                else:
                    expected = ((Keyword.TAUNT, Keyword.DIVINE_SHIELD) if body == 'taunt_shield'
                        else (Keyword.DIVINE_SHIELD, Keyword.LIFESTEAL))
                    self.assertTrue(all(keyword in entity.keywords for keyword in expected))

    def test_d_other_mech_excludes_the_carrier_and_opponent_and_false_gate_needs_no_domain(self):
        cid = AssembleRecipe(GORILLA, LOOT, 'bottom').card_id
        game = self.game((cid,), enemy=(MECHS[0],), mode='no_pool')
        self.play(game, cid)
        self.assertEqual(len(self.drawn(game)), 0)
        self.assertIsNone(game.state.pending_choice)
        self.assertEqual(len(game.state.battlecry_history), 1)

    def test_e_held_dragon_uses_current_hand_tribes_in_both_directions(self):
        cid = AssembleRecipe(LOOT, SWORD_KEEPER, 'top').card_id
        for action, held, expected in ((TO_DRAGON, UNIT, 1), (TO_BEAST, DRAGON, 0)):
            game = self.game((action, cid, held))
            target = next(eid for eid in game.state.players[1].hand if game.state.entities[eid].card_id == held)
            self.play(game, action, target)
            self.play(game, cid)
            self.assertEqual(len(self.drawn(game)), expected)

    def test_f_current_spell_cost_quote_does_not_consume_the_next_spell_modifier(self):
        cid = AssembleRecipe(LOOT, DRYAD, 'top').card_id
        game = self.game((TAX, cid, ARCANE))
        self.play(game, TAX)
        held = next(game.state.entities[eid] for eid in game.state.players[1].hand
            if game.state.entities[eid].card_id == ARCANE)
        self.assertEqual(game.registry.card(ARCANE).cost, 3)
        self.assertEqual(quote_unselected_cost(game.state, game.registry, held).amount, 5)
        self.play(game, cid)
        self.assertEqual(len(self.drawn(game)), 1)
        self.assertEqual(quote_unselected_cost(game.state, game.registry, held).amount, 5)
        before = game.state.players[1].mana
        self.play(game, ARCANE)
        self.assertEqual(game.state.players[1].mana, before-5)
        self.assertEqual(len(self.drawn(game)), 3)

    def test_g_actual_healing_history_excludes_overheal_and_expires_on_the_next_turn(self):
        cid = AssembleRecipe(LOOT, ANSHE, 'top').card_id
        game = self.game((HEAL, cid, HURT, HEAL, cid, cid))
        self.play(game, HEAL, self.hero(game).id)
        self.play(game, cid)
        self.assertEqual(len(self.drawn(game)), 0)
        self.play(game, HURT, self.hero(game).id)
        self.play(game, HEAL, self.hero(game).id)
        self.play(game, cid)
        self.assertEqual((self.hero(game).health, len(self.drawn(game))), (30, 1))
        game.apply(EndTurn(1))
        game.apply(EndTurn(2))
        self.play(game, cid)
        self.assertEqual(len(self.drawn(game)), 2)  # Includes the ordinary start draw only.

    def test_h_unknown_required_held_type_is_not_silently_a_false_condition(self):
        cid = AssembleRecipe(LOOT, STORY_KEEPER, 'top').card_id
        game = self.game((cid, UNKNOWN_TYPE))
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, cid)
        self.assertEqual(game.snapshot(), before)

    def test_i_captured_condition_waiting_preserves_native_view_and_accepted_battlecry_after_death(self):
        cid = AssembleRecipe(LOOT, STORY_KEEPER, 'top').card_id
        for option, draws in (('keep', 1), ('lose', 1), ('kill', 1)):
            game = self.game((cid, DRAGON), board=(WATCH_BC,))
            source = self.play(game, cid)
            self.assertIsNotNone(game.state.pending_choice)
            if option == 'keep':
                restored = self.portable(game)
                before = game.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'conditional-native observer fault'):
                    self.choose(game, 'fail')
                self.assertEqual(game.snapshot(), before)
                self.choose(restored, option)
            self.choose(game, option)
            self.assertEqual(len(self.drawn(game)), draws)
            self.assertEqual(len(game.state.battlecry_history), 1)
            if option == 'keep':
                self.assertEqual(game.snapshot(), restored.snapshot())
            elif option == 'kill':
                self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)

    def test_j_real_mismatch_entry_keeps_the_actual_conditional_prefix(self):
        for enabled in (False, True):
            game = self.game((MISMATCH,) + ((SHADOW,) if enabled else ()))
            self.play(game, MISMATCH)
            offer = next(effect.offer for option in game._frame.options for effect in option.effects
                if isinstance(effect, ResolveAssemble))
            self.assertEqual(offer.primary_card_id, CRYSTAL)
            cid = AssembleRecipe(CRYSTAL, TAELAN, 'bottom').card_id
            option = next(option for option in game.state.pending_choice.options if option.card_id == cid)
            self.choose(game, option.id)
            before = game.state.players[1].mana
            self.play(game, cid)
            self.assertEqual(game.state.players[1].mana, before-game.registry.card(CRYSTAL).cost)
            self.assertEqual(len(self.drawn(game)), int(enabled))
            self.assertEqual(game.state.card_discovery_history, [])
            if enabled:
                self.portable(game)

    def test_k_death_suffix_discovery_and_equipment_do_not_require_a_live_carrier_or_original_condition(self):
        for donor in (GORILLA, SWORD_KEEPER):
            cid = AssembleRecipe(LOOT, donor, 'bottom').card_id
            game = self.game((cid, KILL))
            source = self.play(game, cid)
            self.play(game, KILL, source)
            self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)
            if donor == GORILLA:
                selected = game.state.pending_choice.options[0]
                self.choose(game, selected.id)
                self.assertEqual(game.state.entities[game.state.players[1].hand[-1]].card_id, selected.card_id)
            else:
                self.assertEqual(game.state.entities[game.state.players[1].weapon_id].card_id, cards.SWORD)

    def test_l_missing_domain_and_unknown_qualified_mech_roll_back_the_whole_unconditional_entry(self):
        cid = AssembleRecipe(UNCONDITIONAL, GORILLA, 'bottom').card_id
        for mode in ('no_pool', 'unknown_mech'):
            game = self.game((cid,), mode=mode)
            before = game.snapshot()
            with self.assertRaises(ResolutionError):
                self.play(game, cid)
            self.assertEqual(game.snapshot(), before)

    def test_m_dead_self_buff_and_keyword_effects_do_not_resurrect_or_mutate_another_minion(self):
        for donor in (ANSHE, DRYAD):
            cid = AssembleRecipe(LOOT, donor, 'bottom').card_id
            game = self.game((cid, KILL), board=(UNIT,))
            friend, = game.state.players[1].board
            source = self.play(game, cid)
            self.play(game, KILL, source)
            self.assertEqual(game.state.players[1].board, [friend])
            self.assertEqual((game.state.entities[friend].attack, game.state.entities[friend].health), (0, 20))
            self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)

    def test_n_full_sword_or_query_drift_rejects_before_registering_any_new_symbols(self):
        for mutation in ('sword', 'query'):
            registry = fixture.__wrapped__()
            before = (set(registry.assemble_templates), set(registry._behaviors), set(registry._trigger_conditions))
            if mutation == 'sword':
                registry._cards[cards.SWORD] = replace(registry.card(cards.SWORD), durability=3)
                with self.assertRaises(TargetValidationError):
                    cards.register_assemble_conditional_native_followups(registry)
            else:
                changed = replace(cards.QUERIES[cards.GORILLA], min_cost=2)
                with patch.dict(cards.QUERIES, {cards.GORILLA: changed}):
                    with self.assertRaises(TargetValidationError):
                        cards.register_assemble_conditional_native_followups(registry)
            self.assertEqual((set(registry.assemble_templates), set(registry._behaviors),
                set(registry._trigger_conditions)), before)

    def test_o_original_and_assembled_conditions_keep_their_different_native_windows(self):
        cases = ((STORY_KEEPER, 'lose', True), (SURVIVOR, 'hurt', True), (DRYAD, 'discount', False))
        for donor, choice, enabled in cases:
            with self.subTest(donor=donor):
                extra = (DRAGON, BIG) if donor == DRYAD else (DRAGON,)
                native = self.game((donor,) + extra, board=(WATCH_BC,))
                source = self.play(native, donor)
                self.choose(native, choice)
                entity = native.state.entities[source]
                if donor == SURVIVOR:
                    self.assertEqual((entity.attack, entity.health),
                        (native.registry.card(donor).attack+3, native.registry.card(donor).health+3))
                else:
                    self.assertEqual(Keyword.DIVINE_SHIELD in entity.keywords, enabled)
                cid = AssembleRecipe(LOOT, donor, 'top').card_id
                derived = self.game((cid,) + extra, board=(WATCH_BC,))
                self.play(derived, cid)
                self.choose(derived, choice)
                self.assertEqual(len(self.drawn(derived)), int(enabled))

    def test_p_inner_window_discovery_wait_restores_replays_and_keeps_exact_acceptance(self):
        cid = AssembleRecipe(SURVIVOR, GORILLA, 'bottom').card_id
        game = self.game((cid, DRAGON), board=(WATCH_BC,))
        self.play(game, cid)
        before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'conditional-native observer fault'):
            self.choose(game, 'fail')
        self.assertEqual(game.snapshot(), before)
        self.choose(game, 'hurt')
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual({option.card_id for option in game.state.pending_choice.options}, set(MECHS))
        restored = self.portable(game)
        selected = game.state.pending_choice.options[0].id
        for branch in (game, restored):
            self.choose(branch, selected)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual(len(game.state.battlecry_history), 1)

    def test_q_repeated_inner_windows_reject_another_activation_before_each_real_resume(self):
        cid = AssembleRecipe(LOOT, SURVIVOR, 'top').card_id
        game = self.game((cid, DRAGON), board=(WATCH_BC, 'LOE_077'))
        self.play(game, cid)
        for count in (0, 1):
            self.assertEqual(len(self.drawn(game)), count)
            before = game.snapshot()
            with self.assertRaises(ResolutionError):
                self.choose(game, 'wrong')
            self.assertEqual(game.snapshot(), before)
            self.choose(game, 'hurt')
        self.assertIsNone(game.state.pending_choice)
        self.assertEqual(len(self.drawn(game)), 2)
        self.assertEqual([record.id for record in game.state.battlecry_history], [1, 2])
        self.assertTrue(all(record.completed for record in game.state.battlecry_history))

    def test_r_inner_window_is_fingerprinted_and_unused_or_recursive_declarations_are_rejected(self):
        expected = {cards.PREFIX + key for key in ('hero_damaged_turn', 'held_big_spell')}
        self.assertEqual(fixture().assemble_inner_conditions, frozenset(expected))
        with self.assertRaises(AttributeError):
            fixture().assemble_inner_conditions.add('mutable')
        other = fixture.__wrapped__()
        other._assemble_inner_conditions.clear()
        self.assertNotEqual(other.fingerprint(), fixture().fingerprint())
        game = self.game()
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(game.snapshot(), other)
        small = Registry('k417-unused-inner-profile')
        small.register_trigger_condition(P + 'condition', lambda c: True)
        small.register_assemble_inner_condition(P + 'condition')
        with self.assertRaises(ValueError):
            small.register_assemble_inner_condition(P + 'condition')
        with self.assertRaises(ValueError):
            small.validate()
        donor = fixture().assemble_templates[SURVIVOR]
        helper = inner_condition_behavior_id(donor.prefix.condition_id, donor.suffix.behavior_id, 1)
        with self.assertRaises(ValueError):
            AssembleSuffix(helper, ('battlecry',))


if __name__ == '__main__':
    unittest.main()
