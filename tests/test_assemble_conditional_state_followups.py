"""Actual held gifts, owned Auras, paid-cost receipts and original attack targets."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import assemble_conditional_state_followups as cards
from hs_sim.cards.native_assemble_entry_cards import FETCHER, POOL_ID as ASSEMBLE_POOL
from hs_sim.cards.native_paladin_aura_cards import RESISTANCE, SPEC
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe, condition_behavior_id
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.dark_gifts import GrantDarkGift, public_gifts
from hs_sim.engine.effects import (AddCostModifier, ChoiceOption, Damage, Destroy, GainArmor,
    InvokeBehavior, RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CostSpec, DamageKind, PlayerEffectSpec
from hs_sim.engine.player_effects import RemovePlayerEffect
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import CardReference, DiscardCard, ModifyStoredCost
from tools.card_batch import check_face, sha
from hs_sim.targets import canonical_digest
from test_assemble_draw_armor_heal_fragments import (
    fixture as base_fixture, META, COIN, BEAST, UNIT, KILL,
)

MATRIARCH, TURTLE, TIMEWAYS, SABER = cards.SOURCES
LOOT, CURATOR, FLY, GOLEM, TAELAN = 'CORE_EX1_096', 'CORE_KAR_061', 'CORE_UNG_809', 'BE_861', 'CS3_024'
PREFIXES = {'deathrattle': LOOT, 'end_turn': 'BE_152', 'start_turn': 'CORE_NEW1_021'}
P = 'k420.'
GIFT, SET3, DISCOUNT, TAX, TRIGGER, HURT, LEGACY, WATCH, FAIL, REENTER, BONUS = (
    P + key for key in ('gift', 'set3', 'discount', 'tax', 'trigger', 'hurt', 'legacy',
        'watch', 'fail', 'reenter', 'bonus'))
CTX = GenerationContext('k420-actual-conditional-state-fixture', 'experimental')
DECK = (BEAST, BEAST) + (COIN,) * 18


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    registry = base_fixture.__wrapped__('no_pool', role)
    registry._version += '.k420.' + mode

    def held_unit(c):
        return next(c.state.entities[eid] for eid in c.state.players[c.player_id].hand
            if c.state.entities[eid].card_id == UNIT)

    def set_three(c):
        return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[eid]), CostSpec(set_to=3), c.source_id)
            for eid in c.state.players[c.player_id].hand if c.state.entities[eid].card_id.startswith('assemble:'))

    def reenter(c):
        entity = c.state.entities[c.target_id]
        return (SummonStoredCard(CardReference.capture(entity), entity.controller),)

    def fail(c):
        raise ResolutionError('K420 deliberate original-window continuation failure')

    scripts = {
        GIFT: lambda c: (GrantDarkGift(CardReference.capture(held_unit(c)), 'EDR_100t3', c.source_id),),
        SET3: set_three,
        DISCOUNT: lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-2, card_types=(CardType.MINION,)),
            uses_remaining=1, source_id=c.source_id),),
        TAX: lambda c: (AddCostModifier(c.player_id, CostSpec(delta=2, card_types=(CardType.MINION,)),
            uses_remaining=1, source_id=c.source_id),),
        TRIGGER: lambda c: (TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]), c.source_id),),
        HURT: lambda c: (Damage(c.state.players[c.player_id].hero_id, 4, c.source_id, DamageKind.EFFECT),),
    }
    for cid, body in scripts.items():
        registry.register_behavior(cid, body)
        registry.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)) if cid == TRIGGER else None))
    registry.register_behavior(REENTER, reenter)
    registry.register_behavior(FAIL, fail)
    registry.register_card(CardDefinition(BONUS, BONUS, CardType.MINION, health=20, spell_damage=10, metadata=META))
    registry.register_player_effect(PlayerEffectSpec(LEGACY, LEGACY, kind='objective', duration=3, tick_event='turn_ended'))
    registry.register_card(CardDefinition(LEGACY, LEGACY, CardType.SPELL, ongoing_effect_id=LEGACY, metadata=META))

    def watch(c):
        source = c.state.entities.get(c.event.source_id)
        if source is None or not source.card_id.startswith('assemble:'):
            return ()
        options = [ChoiceOption('keep', 'Continue'),
            ChoiceOption('kill', 'Kill source', (Destroy(source.id, c.source_id),)),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1), InvokeBehavior(FAIL, c.source_id, c.player_id)))]
        if mode == 'attack_wait':
            target = c.state.entities[c.event.target_id]
            options.append(ChoiceOption('stale', 'Reenter original defender', (
                ReturnToHand(target.id), InvokeBehavior(REENTER, c.source_id, c.player_id, target.id)),
                card_id=target.card_id, entity_id=target.id))
        else:
            unit = next((c.state.entities[eid] for eid in c.state.players[c.player_id].hand
                if c.state.entities[eid].card_id == UNIT), None)
            if unit is not None:
                options.append(ChoiceOption('drop_gift', 'Discard held gifted minion',
                    (DiscardCard(CardReference.capture(unit), c.source_id),)))
            aura = next((effect for effect in c.state.players[c.player_id].player_effects if effect.spec_id == SPEC), None)
            if aura is not None:
                options.append(ChoiceOption('drop_aura', 'Retire owned Aura', (RemovePlayerEffect(c.player_id, aura.id),)))
        return (RequestChoice(c.player_id, tuple(options), c.source_id),)

    registry.register_behavior(WATCH, watch)
    registry.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=30, metadata=META,
        triggers=(TriggerSpec('attack_declared' if mode == 'attack_wait' else 'battlecry_started', WATCH),)))
    registry.register_pool(PoolDefinition(ASSEMBLE_POOL, 'k420-four-cost-primary-two-valid-five-cost-donors',
        CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in (GOLEM, MATRIARCH, TAELAN)), complete=True))
    registry.validate()
    return registry


class AssembleConditionalStateFollowupTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), mode='normal', enemy_hand=(), hero='HERO_08'):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, deck=DECK, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(COIN,) * 18,
                mana=30, max_mana=30, mana_cap=30)), seed=420, generation_context=CTX), fixture(mode))

    def entity(self, game, cid, player=1):
        return next(game.state.entities[eid] for eid in game.state.players[player].hand
            if game.state.entities[eid].card_id == cid)

    def hero(self, game, player=1):
        return game.state.entities[game.state.players[player].hero_id]

    def play(self, game, cid, target=None):
        player = game.state.active_player
        source = self.entity(game, cid, player).id
        game.apply(PlayCard(player, source, target))
        return source

    def choose(self, game, key):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (key,)))

    def own_draws(self, game):
        return [record for record in game.state.draw_history if record.player_id == 1]

    def broodlings(self, game):
        return [game.state.entities[eid] for eid in game.state.players[1].board
            if game.state.entities[eid].card_id == cards.BROODLING]

    def portable(self, game, mode):
        reader = fixture(mode, 'reader')
        self.assertIsNot(reader, game.registry)
        saved = json.loads(json.dumps(game.snapshot()))
        restored = Game.from_snapshot(saved, reader)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(game), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(game.for_player(player).observe()) + json.dumps(game.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'condition_id', 'candidate_card_ids', 'board_residence'):
                self.assertNotIn('"' + key + '"', public)
        return restored

    def test_a_five_full_records_ten_primary_faces_originals_and_exact_condition_bridges(self):
        data = cards.load_batch()
        registry = build_registry()
        rows = {row['record']['id']: row for row in data['existing_dependencies']}
        self.assertEqual(tuple(rows), cards.SOURCES + (cards.BROODLING,))
        self.assertEqual(len(data['official_observations']), 10)
        seen = set()
        for observation in data['official_observations']:
            cid = observation['card_id']
            check_face(rows[cid]['record'], observation['face'], observation['locale'],
                data['display_normalizations'].get(cid),
                numeric_normalizations=data['numeric_normalizations'].get(cid))
            path = Path(observation['response_file'])
            self.assertEqual(sha(path), observation['response_sha256'])
            response = json.loads(path.read_text(encoding='utf-8-sig'))
            self.assertEqual([face for face in response['cards'] if face['id'] == rows[cid]['record']['dbf_id']],
                [observation['face']])
            seen.add((cid, observation['locale']))
        self.assertEqual(seen, {(cid, locale) for cid in rows for locale in ('zh_CN', 'en_US')})
        for cid, row in rows.items():
            self.assertEqual(canonical_digest(asdict(registry.card(cid))), row['definition_sha256'])
        for cid in cards.SOURCES:
            template = registry.assemble_templates[cid]
            recipe = AssembleRecipe(cid, cid, 'top').card_id
            derived = asdict(registry.card(recipe))
            self.assertEqual(derived['battlecry'], condition_behavior_id(template.prefix.condition_id,
                template.suffix.behavior_id))
            derived.update(id=cid, battlecry=template.original_battlecry_id)
            self.assertEqual(derived, asdict(registry.card(cid)))

    def test_b_both_gift_prefixes_keep_actual_held_gift_condition_without_the_original_rewards(self):
        for donor in (MATRIARCH, TURTLE):
            for gifted in (False, True):
                with self.subTest(donor=donor, gifted=gifted):
                    cid = AssembleRecipe(LOOT, donor, 'top').card_id
                    game = self.game((cid, UNIT, GIFT) if gifted else (cid, TAELAN))
                    if gifted:
                        self.play(game, GIFT)
                        self.assertTrue(public_gifts(self.entity(game, UNIT)))
                    self.play(game, cid)
                    self.assertEqual(len(self.own_draws(game)), int(gifted))
                    self.assertFalse(self.broodlings(game))
                    self.assertEqual((self.hero(game).attack, self.hero(game).armor), (0, 0))

    def test_c_aura_prefix_uses_actual_owned_aura_not_legacy_objective_or_opponent_aura(self):
        cid = AssembleRecipe(LOOT, TIMEWAYS, 'top').card_id
        for mode in ('own', 'legacy', 'opponent'):
            with self.subTest(mode=mode):
                game = self.game((cid, LEGACY if mode == 'legacy' else RESISTANCE), enemy_hand=(RESISTANCE,))
                if mode == 'opponent':
                    game.apply(EndTurn(1)); self.play(game, RESISTANCE); game.apply(EndTurn(2))
                else:
                    self.play(game, LEGACY if mode == 'legacy' else RESISTANCE)
                before = len(self.own_draws(game))
                self.play(game, cid)
                self.assertEqual(len(self.own_draws(game)) - before, int(mode == 'own'))
                self.assertEqual(self.hero(game, 2).health, 30)

    def test_d_paid_receipt_survives_one_use_discount_or_tax_consumption(self):
        for primary, modifier, paid, current, draws in ((CURATOR, DISCOUNT, 3, 5, 1), (LOOT, TAX, 4, 2, 0)):
            with self.subTest(primary=primary):
                cid = AssembleRecipe(primary, SABER, 'top').card_id
                game = self.game((cid, modifier))
                self.play(game, modifier)
                before = game.state.players[1].mana
                source = self.play(game, cid)
                self.assertEqual(game.state.players[1].mana, before - paid)
                self.assertEqual(game.state.play_history[-1].cost, paid)
                self.assertEqual(quote_unselected_cost(game.state, game.registry, game.state.entities[source]).amount, current)
                self.assertEqual(len(self.own_draws(game)), draws)
                self.assertFalse(game.state.character_attack_history)

    def test_e_indirect_condition_has_no_parent_spell_price_and_uses_current_cost_without_payment(self):
        cid = AssembleRecipe(CURATOR, SABER, 'top').card_id
        game = self.game((TRIGGER,), (cid,))
        source = game.state.players[1].board[0]
        self.play(game, TRIGGER, source)
        self.assertFalse(self.own_draws(game))
        self.assertEqual(game.state.players[1].mana, 30)
        game = self.game((cid, SET3, TRIGGER))
        self.play(game, SET3); source = self.play(game, cid)
        self.assertEqual(len(self.own_draws(game)), 1)
        self.assertEqual(quote_unselected_cost(game.state, game.registry, game.state.entities[source]).amount, 3)
        before = game.state.players[1].mana
        self.play(game, TRIGGER, source)
        self.assertEqual(game.state.players[1].mana, before)
        self.assertEqual(len(self.own_draws(game)), 2)
        self.assertEqual(len(game.state.battlecry_history), 2)

    def test_f_all_four_borrowed_effects_execute_without_old_conditions_or_generation_pool(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                cid = AssembleRecipe(CURATOR, donor, 'bottom').card_id
                game = self.game((cid,), (BONUS,), (UNIT, UNIT, UNIT))
                source = self.play(game, cid)
                self.assertEqual(game.state.players[1].mana, 25)
                if donor == MATRIARCH:
                    born = self.broodlings(game)
                    self.assertEqual(len({e.id for e in born}), 2)
                    self.assertTrue(all((e.attack, e.health, set(e.keywords)) == (4, 4, {Keyword.TAUNT}) for e in born))
                elif donor == TURTLE:
                    self.assertEqual((self.hero(game).attack, self.hero(game).armor), (3, 6))
                    game.apply(EndTurn(1))
                    self.assertEqual((self.hero(game).attack, self.hero(game).armor), (0, 6))
                elif donor == TIMEWAYS:
                    self.assertEqual(self.hero(game, 2).health, 27)
                    self.assertEqual([game.state.entities[eid].health for eid in game.state.players[2].board], [17] * 3)
                    self.assertEqual(self.hero(game).health, 30)
                else:
                    attacks = game.state.character_attack_history
                    self.assertEqual(len({record.delivery.target_id for record in attacks}), 2)
                    self.assertEqual(sorted(game.state.entities[eid].health for eid in game.state.players[2].board), [16, 16, 20])
                    self.assertTrue(all(record.terminal.status == 'completed' for record in attacks))
                self.assertEqual(game.state.entities[source].card_id, cid)

    def test_g_all_four_suffixes_keep_dead_end_start_contexts_and_physical_attack_requirements(self):
        for donor in cards.SOURCES:
            for timing, primary in PREFIXES.items():
                with self.subTest(donor=donor, timing=timing):
                    cid = AssembleRecipe(primary, donor, 'bottom').card_id
                    game = self.game((cid, KILL), enemy=(UNIT, UNIT))
                    source = self.play(game, cid)
                    if timing == 'deathrattle':
                        self.play(game, KILL, source)
                    elif timing == 'end_turn':
                        game.apply(EndTurn(1))
                    else:
                        game.apply(EndTurn(1)); game.apply(EndTurn(2))
                    self.assertIsNone(game.state.pending_choice)
                    if donor == MATRIARCH:
                        self.assertEqual(len(self.broodlings(game)), 2)
                    elif donor == TURTLE:
                        self.assertEqual((self.hero(game).attack, self.hero(game).armor),
                            (0 if timing == 'end_turn' else 3, 6))
                    elif donor == TIMEWAYS:
                        self.assertEqual(self.hero(game, 2).health, 27)
                        self.assertEqual([game.state.entities[eid].health for eid in game.state.players[2].board], [17, 17])
                    else:
                        attack = game.registry.card(primary).attack if timing != 'deathrattle' else 0
                        self.assertEqual([game.state.entities[eid].health for eid in game.state.players[2].board], [20-attack] * 2)
                    if timing == 'deathrattle':
                        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)

    def test_h_original_sampled_attack_targets_wait_reentry_failure_restore_replay_and_one_payment(self):
        cid = AssembleRecipe(CURATOR, SABER, 'bottom').card_id
        game = self.game((cid,), (WATCH, BONUS), (UNIT, UNIT), mode='attack_wait')
        source = self.play(game, cid)
        first = next(option.entity_id for option in game.state.pending_choice.options if option.id == 'stale')
        second = next(eid for eid in game.state.players[2].board if eid != first)
        reader = self.portable(game, 'attack_wait')
        saved = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate original-window continuation failure'):
            self.choose(game, 'bad')
        self.assertEqual(game.snapshot(), saved)
        for running in (game, reader):
            self.choose(running, 'stale')
            while running.state.pending_choice is not None:
                self.choose(running, 'keep')
            self.assertEqual(running.state.entities[first].health, 20)
            self.assertEqual(running.state.entities[second].health, 16)
            self.assertEqual([record.terminal.status for record in running.state.character_attack_history], ['cancelled', 'completed'])
            self.assertEqual(running.state.players[1].mana, 25)
            self.assertTrue(running.state.battlecry_history[0].completed)
            self.assertEqual(running.state.entities[source].zone, Zone.BOARD)
        self.assertEqual(game.snapshot(), reader.snapshot())
        self.portable(game, 'attack_wait')

    def test_i_captured_conditions_remain_accepted_after_held_gift_or_owned_aura_is_removed(self):
        for donor, setup, option in ((MATRIARCH, GIFT, 'drop_gift'), (TIMEWAYS, RESISTANCE, 'drop_aura')):
            with self.subTest(donor=donor):
                cid = AssembleRecipe(LOOT, donor, 'top').card_id
                game = self.game((cid, setup, UNIT), (WATCH,), mode='bc_wait')
                self.play(game, setup); self.play(game, cid)
                self.assertFalse(self.own_draws(game))
                self.choose(game, option)
                self.assertEqual(len(self.own_draws(game)), 1)
                if donor == MATRIARCH:
                    self.assertFalse(any(public_gifts(game.state.entities[eid]) for eid in game.state.players[1].hand))
                else:
                    self.assertFalse(any(game.registry.player_effect(effect.spec_id).kind == 'aura'
                        for effect in game.state.players[1].player_effects))

    def test_j_accepted_conditional_draw_survives_source_death_without_old_deathrattle(self):
        cid = AssembleRecipe(LOOT, MATRIARCH, 'top').card_id
        game = self.game((cid, UNIT, GIFT), (WATCH,), mode='bc_wait')
        self.play(game, GIFT); source = self.play(game, cid)
        self.choose(game, 'kill')
        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(len(self.own_draws(game)), 1)
        self.assertFalse(self.broodlings(game))

    def test_k_actual_fetcher_keeps_valid_class_cost_pool_and_both_conditional_source_halves(self):
        for half in ('top', 'bottom'):
            with self.subTest(half=half):
                hand = (FETCHER, KILL, HURT, UNIT, GIFT)
                game = self.game(hand, hero='HERO_11')
                self.play(game, GIFT); self.play(game, HURT); self.play(game, FETCHER)
                cid = AssembleRecipe(GOLEM, MATRIARCH, half).card_id
                self.choose(game, next(option.id for option in game.state.pending_choice.options if option.card_id == cid))
                before = game.state.players[1].mana
                source = self.play(game, cid)
                self.assertEqual(game.state.players[1].mana, before-4)
                if half == 'top':
                    self.assertEqual(self.hero(game).health, 29)
                    self.assertFalse(self.broodlings(game))
                else:
                    self.assertFalse(self.broodlings(game))
                    self.play(game, KILL, source)
                    self.assertEqual(len(self.broodlings(game)), 2)
                self.assertTrue(all(record.completed for record in game.state.battlecry_history))

    def test_l_original_source_child_or_selected_callback_drift_rejects_before_partial_registration(self):
        for mode in ('source', 'child', 'selected'):
            with self.subTest(mode=mode):
                with patch.object(cards, 'register_assemble_conditional_state_followups', lambda r: None):
                    registry = build_registry()
                if mode in ('source', 'child'):
                    cid = MATRIARCH if mode == 'source' else cards.BROODLING
                    registry._cards[cid] = replace(registry.card(cid), name=registry.card(cid).name + ' changed')
                else:
                    registry._behaviors.pop('cards.native_forced_attack.selected')
                before = registry.fingerprint()
                with self.assertRaises(ValueError):
                    cards.register_assemble_conditional_state_followups(registry)
                self.assertEqual(registry.fingerprint(), before)


if __name__ == '__main__':
    unittest.main()
