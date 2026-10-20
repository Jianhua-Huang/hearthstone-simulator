"""Five real entries over original play, draw and summon facts."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_consumer_followup_cards import (CARRIER, GENERAL, JUDGMENT, OMEN,
    PREFIX, ROOTS, SUMMONER, load_batch)
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    ResolutionError, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.copy_materials import CopyEntryMaterial
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import Buff, ChoiceOption, Destroy, Draw, RequestChoice, Transform
from hs_sim.engine.model import CardClass, CardMetadata, CastWhenDrawnSpec, CostSpec, Keyword, Rarity
from hs_sim.engine.physical_draw_groups import DrawGroupReward
from hs_sim.engine.pool_summons import validate_weighted_request
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, SummonFromPool
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.allocation_facts import SourceAllocationFact
from tools.card_batch import check_face

COIN, FIREBALL, MISSILES = 'GAME_005', 'CS2_029', 'EX1_277'
YETI, STEAM, KNIGHT, HOARDER, FLY = 'CORE_CS2_182', 'CORE_REV_946', 'AT_096', 'CORE_EX1_096', 'CORE_UNG_809'
SPELLS, MINIONS = (FIREBALL, MISSILES, OMEN), (STEAM, KNIGHT)
CTX = GenerationContext('k332-complete-explicit-fixture', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
P = 'fixture.native_consumer_followups.'
DRAW, BOOST, MORPH, CWD, WATCH, NOOP = (P+x for x in ('draw', 'boost', 'morph', 'drawcast', 'watch', 'noop'))


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    registry = build_registry()
    registry.register_behavior(NOOP, lambda c: ())
    registry.register_behavior(DRAW, lambda c: (Draw(c.player_id, source_id=c.source_id),))
    registry.register_card(CardDefinition(DRAW, 'Explicit ordinary draw', CardType.SPELL, metadata=META, on_play=DRAW))
    registry.register_behavior(BOOST, lambda c: (Buff(c.target_id, 2, 3, c.source_id),))
    registry.register_card(CardDefinition(BOOST, 'Explicit current-copy preparation', CardType.SPELL, metadata=META,
        on_play=BOOST, targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    registry.register_behavior(MORPH, lambda c: (Transform(c.source_id, SUMMONER),))
    registry.register_card(CardDefinition(MORPH, 'Original neutral submitted face', CardType.MINION, health=1,
        metadata=META, battlecry=MORPH))
    registry.register_card(CardDefinition(CWD, 'Explicit replacement draw cast', CardType.SPELL,
        metadata=META, on_play=NOOP, keywords=(Keyword.CASTS_WHEN_DRAWN,), cast_when_drawn=CastWhenDrawnSpec()))
    for domain, ids in (('constructed.cards', SPELLS), ('constructed.minions', MINIONS)):
        members = tuple(PoolMember(cid) for cid in ids)
        if mode == 'empty_minion' and domain == 'constructed.minions': members = ()
        if mode == 'unknown_spell' and domain == 'constructed.cards' or mode == 'unknown_minion' and domain == 'constructed.minions':
            cid = P+mode; kind = CardType.SPELL if mode == 'unknown_spell' else CardType.MINION
            registry.register_pool_card(PoolCard(cid, kind, 3 if kind == CardType.SPELL else 5,
                CardMetadata(True, (CardClass.MAGE,), Rarity.COMMON, tribes=()),
                battlecry=False, deathrattle=False, choose_one=False))
            members += (PoolMember(cid),)
        registry.register_pool(PoolDefinition(domain, 'explicit-known-v1', CTX.target_id, CTX.mode,
            members, complete=True))
    if mode in ('draw_wait', 'deck_wait', 'pool_wait', 'copy_wait'):
        def observe(c):
            entity = c.state.entities.get(c.event.target_id)
            if entity is None or entity.controller != c.player_id: return ()
            if mode == 'draw_wait':
                if entity.card_id != YETI or sum(r.source_id == c.event.source_id for r in c.state.draw_history) != 1: return ()
            elif mode == 'deck_wait':
                if entity.card_id not in SPELLS: return ()
            elif mode == 'pool_wait':
                if entity.card_id not in MINIONS: return ()
            elif entity.card_id != FLY: return ()
            target = entity.id if mode == 'pool_wait' else c.state.players[2].board[0] if mode == 'copy_wait' else None
            options = (ChoiceOption('continue', 'Continue original work'),)
            if target is not None: options += (ChoiceOption('remove', 'Remove original subject', (Destroy(target, c.source_id),)),)
            return (RequestChoice(c.player_id, options, c.source_id),)
        registry.register_behavior(WATCH, observe)
        event = 'card_drawn' if mode == 'draw_wait' else 'card_added_to_deck' if mode == 'deck_wait' else 'minion_summoned'
        registry.register_card(CardDefinition(WATCH, 'Actual boundary observer', CardType.MINION,
            health=20, metadata=META, triggers=(TriggerSpec(event, WATCH),)))
    return registry


class NativeConsumerFollowupTests(unittest.TestCase):
    readers = {}

    def game(self, hand=(), board=(), enemy=(), deck=(COIN,)*10, mode='normal'):
        if mode in ('draw_wait', 'deck_wait', 'pool_wait', 'copy_wait'): board = (WATCH,)+board
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', hand=hand, board=board,
                deck=deck, mana=10, max_mana=10),
            PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', hand=(HOARDER,), board=enemy,
                deck=(COIN,)*10, mana=10, max_mana=10)), seed=0, generation_context=CTX), fixture(mode))

    def play(self, game, cid, target=None, player=1):
        eid = next(i for i in game.state.players[player].hand if game.state.entities[i].card_id == cid)
        game.apply(PlayCard(player, eid, target_id=target)); return eid

    def pick(self, game, cid):
        choice = game.state.pending_choice; option = next(o for o in choice.options if o.card_id == cid)
        game.apply(SelectChoice(choice.player_id, choice.id, (option.id,)))

    def proceed(self, game, key='continue'):
        choice = game.state.pending_choice; game.apply(SelectChoice(choice.player_id, choice.id, (key,)))

    def price(self, game, eid):
        state = game.state; return quote_unselected_cost(state, game.registry, state.entities[eid]).amount

    def portable(self, game, mode='normal'):
        if mode not in self.readers: self.readers[mode] = fixture.__wrapped__(mode)
        registry = self.readers[mode]; saved = game.snapshot()
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)), registry).snapshot(), saved)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(game.for_player(player).observe())+json.dumps(game.player_events(player))
            for hidden in ('"pool_basis"', '"card_summon_history"', '"rng_state"', '"copy_local"'):
                self.assertNotIn(hidden, public)
        return Game.from_snapshot(saved, registry)

    def test_five_complete_rows_ten_bilingual_faces_metadata_and_explicit_zero(self):
        data = load_batch(); registry = fixture(); rows = {r['record']['id']:r['record'] for r in data['cards']}
        self.assertEqual(tuple(rows), ROOTS); self.assertEqual(len(data['official_observations']), 10)
        for cid, raw in rows.items(): self.assertEqual(asdict(registry.card(cid).metadata), asdict(metadata_from_record(raw)))
        for obs in data['official_observations']:
            check_face(rows[obs['card_id']], obs['face'], obs['locale'],
                numeric_normalizations=data['numeric_normalizations'].get(obs['card_id']))
        self.assertEqual(registry.card(SUMMONER).attack, 0)

    def test_general_counts_its_own_neutral_play_then_stacks_independent_one_use_discounts(self):
        game = self.game(hand=(GENERAL, HOARDER, FIREBALL)); self.play(game, GENERAL)
        spell = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == FIREBALL)
        self.assertEqual(self.price(game, spell), 3)
        self.play(game, HOARDER); self.assertEqual(self.price(game, spell), 2)
        self.play(game, FIREBALL, game.state.players[2].hero_id)
        self.assertEqual(game.state.players[1].mana, 3)

    def test_general_uses_original_neutral_face_even_after_the_used_minion_transforms(self):
        game = self.game(hand=(GENERAL, MORPH, FIREBALL)); self.play(game, GENERAL)
        changed = self.play(game, MORPH); self.assertEqual(game.state.entities[changed].card_id, SUMMONER)
        spell = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == FIREBALL)
        self.assertEqual(self.price(game, spell), 2)

    def test_general_zero_price_spell_consumes_old_program_and_neutral_coin_installs_new_one(self):
        game = self.game(hand=(GENERAL, COIN, FIREBALL)); self.play(game, GENERAL); self.play(game, COIN)
        spell = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == FIREBALL)
        self.assertEqual(self.price(game, spell), 3)
        self.play(game, FIREBALL, game.state.players[2].hero_id); self.assertEqual(game.state.players[1].mana, 5)

    def test_general_this_turn_expires_and_opponent_neutral_play_does_not_install_owner_discount(self):
        game = self.game(hand=(GENERAL, FIREBALL)); self.play(game, GENERAL); game.apply(EndTurn(1))
        self.play(game, HOARDER, player=2); game.apply(EndTurn(2))
        spell = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == FIREBALL)
        self.assertEqual(self.price(game, spell), 4)

    def test_carrier_discovers_to_original_top_with_discount_and_no_hand_delivery(self):
        game = self.game(hand=(CARRIER, DRAW)); self.play(game, CARRIER); rng = game.snapshot()['rng_state']
        self.pick(game, FIREBALL); top = game.state.players[1].deck[0]
        self.assertEqual(game.state.entities[top].card_id, FIREBALL); self.assertEqual(self.price(game, top), 2)
        self.assertEqual(game.snapshot()['rng_state'], rng)
        self.assertFalse(any(game.state.entities[i].card_id == FIREBALL for i in game.state.players[1].hand))
        self.play(game, DRAW); self.assertIn(top, game.state.players[1].hand); self.assertEqual(self.price(game, top), 2)

    def test_carrier_first_deck_acquisition_wait_retains_chosen_identity_and_floor(self):
        game = self.game(hand=(CARRIER,), mode='deck_wait'); self.play(game, CARRIER); self.pick(game, MISSILES)
        top = game.state.players[1].deck[0]; self.assertEqual(self.price(game, top), 0)
        restored = self.portable(game, 'deck_wait')
        for value in (game, restored): self.proceed(value)
        self.assertEqual(game.snapshot(), restored.snapshot()); self.assertEqual(game.state.players[1].deck[0], top)

    def test_carrier_unknown_eligible_spell_is_not_cropped_and_rolls_back_entry(self):
        game = self.game(hand=(CARRIER,), mode='unknown_spell'); saved = game.snapshot()
        with self.assertRaises(ResolutionError): self.play(game, CARRIER)
        self.assertEqual(game.snapshot(), saved)

    def test_judgment_three_actual_draws_set_only_drawn_minions_and_leave_costs_and_old_hand(self):
        game = self.game(hand=(JUDGMENT, GENERAL), deck=(YETI, FIREBALL, HOARDER)); old = game.state.players[1].hand[1]
        self.play(game, JUDGMENT)
        drawn = [game.state.entities[i] for i in game.state.players[1].hand if i != old]
        self.assertEqual([e.card_id for e in drawn], [YETI, FIREBALL, HOARDER])
        self.assertEqual([(e.attack, e.health) for e in drawn if e.kind == CardType.MINION], [(2,2),(2,2)])
        self.assertEqual((game.state.entities[old].attack, game.state.entities[old].health), (2,5))
        self.assertEqual(self.price(game, drawn[0].id), 4)
        self.play(game, YETI); self.assertEqual(game.state.players[1].mana, 3)

    def test_judgment_whole_group_reward_waits_for_three_draws_and_restores_prefix(self):
        game = self.game(hand=(JUDGMENT,), deck=(YETI, FIREBALL, HOARDER), mode='draw_wait'); self.play(game, JUDGMENT)
        eid = game.state.players[1].hand[0]
        self.assertEqual((game.state.entities[eid].attack, game.state.entities[eid].health), (4,5))
        self.assertEqual(len(game.state.draw_history), 1); restored = self.portable(game, 'draw_wait')
        for value in (game, restored): self.proceed(value)
        self.assertEqual(game.snapshot(), restored.snapshot()); self.assertEqual(len(game.state.draw_history), 3)
        self.assertEqual((game.state.entities[eid].attack, game.state.entities[eid].health), (2,2))

    def test_judgment_includes_its_actual_draw_cast_replacement_minion(self):
        game = self.game(hand=(JUDGMENT,), deck=(CWD, YETI, FIREBALL, HOARDER)); self.play(game, JUDGMENT)
        self.assertEqual(len(game.state.draw_history), 4)
        hand = [game.state.entities[i] for i in game.state.players[1].hand]
        self.assertEqual([e.card_id for e in hand], [YETI, FIREBALL, HOARDER])
        self.assertEqual((hand[0].attack, hand[0].health), (2,2))

    def test_judgment_partial_deck_fatigues_for_remaining_real_draws(self):
        game = self.game(hand=(JUDGMENT,), deck=(YETI,)); self.play(game, JUDGMENT)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 27)
        self.assertEqual(len(game.state.draw_history), 3)
        self.assertEqual(game.state.entities[game.state.players[1].hand[0]].health, 2)

    def test_judgment_full_hand_rewards_only_original_successful_hand_arrival(self):
        game = self.game(hand=(JUDGMENT,)+(COIN,)*9, deck=(YETI, YETI, YETI)); self.play(game, JUDGMENT)
        bodies = [e for e in game.state.entities.values() if e.card_id == YETI]
        held = [e for e in bodies if e.zone == Zone.HAND]
        self.assertEqual(len(held), 1); self.assertEqual((held[0].attack, held[0].health), (2,2))
        self.assertEqual(sum(e.zone == Zone.GRAVEYARD for e in bodies), 2)
        self.assertEqual(len(game.state.players[1].hand), 10)

    def test_summoner_copies_current_stats_attacks_original_without_running_battlecry(self):
        game = self.game(hand=(SUMMONER, BOOST), enemy=(FLY,)); self.play(game, SUMMONER)
        enemy = game.state.players[2].board[0]; self.play(game, BOOST, enemy); game.apply(EndTurn(1))
        clone = next(game.state.entities[i] for i in game.state.players[1].board if game.state.entities[i].card_id == FLY)
        self.assertNotEqual(clone.id, enemy); self.assertEqual((clone.attack, clone.health), (3,2))
        self.assertEqual(game.state.entities[enemy].health, 2); self.assertEqual(game.state.players[1].hand, [])

    def test_summoner_duplicate_faces_are_distinct_equal_physical_candidates(self):
        game = self.game(hand=(SUMMONER,), enemy=(FLY, FLY)); self.play(game, SUMMONER); game.apply(EndTurn(1))
        root = game.state.card_summon_history[-1]
        self.assertEqual([m.card_id for m in root.request.materials], [FLY, FLY])
        self.assertEqual(len({m.origin.entity_id for m in root.request.materials}), 2)
        self.assertIn(root.selected, (0,1))
        original = root.request.materials[root.selected].origin.entity_id
        self.assertEqual(game.state.entities[original].health, 1)
        self.assertEqual(sum(game.state.entities[i].damage == 0 for i in game.state.players[2].board), 1)

    def test_summoner_empty_enemy_and_full_board_do_not_consume_summon_rng(self):
        for board, enemy in (((SUMMONER,), ()), ((SUMMONER,)+(FLY,)*6, (FLY,))):
            with self.subTest(board=len(board), enemy=len(enemy)):
                game = self.game(board=board, enemy=enemy); rng = game.snapshot()['rng_state']; game.apply(EndTurn(1))
                self.assertEqual(game.snapshot()['rng_state'], rng)

    def test_summoner_actual_copy_wait_restores_original_enemy_and_native_combat(self):
        game = self.game(hand=(SUMMONER,), enemy=(FLY,), mode='copy_wait'); self.play(game, SUMMONER); game.apply(EndTurn(1))
        original = game.state.players[2].board[0]; self.assertEqual(game.state.entities[original].health, 2)
        restored = self.portable(game, 'copy_wait')
        for value in (game, restored): self.proceed(value)
        self.assertEqual(game.snapshot(), restored.snapshot()); self.assertEqual(game.state.entities[original].health, 1)

    def test_summoner_original_removed_during_copy_notifications_is_not_retargeted(self):
        game = self.game(hand=(SUMMONER,), enemy=(FLY,), mode='copy_wait'); self.play(game, SUMMONER); game.apply(EndTurn(1))
        self.proceed(game, 'remove')
        self.assertEqual(game.state.players[2].board, [])
        clone = next(game.state.entities[i] for i in game.state.players[1].board if game.state.entities[i].card_id == FLY)
        self.assertEqual(clone.health, 2)

    def test_random_copy_requests_reject_duplicate_physical_candidates_and_mixed_recipes(self):
        game = self.game(board=(SUMMONER,), enemy=(FLY,)); state = game.state
        source = state.entities[state.players[1].board[0]]; original = state.entities[state.players[2].board[0]]
        cause = SummonCause(SourceAllocationFact.capture(state, source), 1, state.turn, state.action_number)
        material = CopyEntryMaterial.capture(state, original, 'board_copy', 'current', registry=game.registry, player_id=1)
        for rows in ((material, material), (material, SummonEntryMaterial(YETI))):
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError): SummonByCard(1, rows, cause, selection='random')

    def test_omen_freezes_original_enemy_then_actual_random_five_cost_without_battlecry(self):
        game = self.game(hand=(OMEN,)); target = game.state.players[2].hero_id; self.play(game, OMEN, target)
        self.assertTrue(game.state.entities[target].frozen); body = game.state.entities[game.state.players[1].board[0]]
        self.assertIn(body.card_id, MINIONS); self.assertTrue(body.frozen); self.assertEqual(game.state.players[1].mana, 7)

    def test_omen_freeze_is_after_summon_notifications_and_waiting_restore_keeps_callback(self):
        game = self.game(hand=(OMEN,), mode='pool_wait'); self.play(game, OMEN, game.state.players[2].hero_id)
        body = next(i for i in game.state.players[1].board if game.state.entities[i].card_id in MINIONS)
        self.assertFalse(game.state.entities[body].frozen); restored = self.portable(game, 'pool_wait')
        for value in (game, restored): self.proceed(value)
        self.assertEqual(game.snapshot(), restored.snapshot()); self.assertTrue(game.state.entities[body].frozen)

    def test_omen_destroyed_summon_before_callback_is_not_replaced_or_frozen(self):
        game = self.game(hand=(OMEN,), mode='pool_wait'); self.play(game, OMEN, game.state.players[2].hero_id)
        self.proceed(game, 'remove'); self.assertEqual(len(game.state.players[1].board), 1)

    def test_omen_pool_callback_is_bound_to_complete_original_materials(self):
        game = self.game(hand=(OMEN,), mode='pool_wait'); self.play(game, OMEN, game.state.players[2].hero_id)
        request = game.state.card_summon_history[-1].request
        bad = replace(request, pool_basis=replace(request.pool_basis, on_summon=PREFIX+GENERAL))
        with self.assertRaises(ValueError): validate_weighted_request(game.state, game.registry, bad)

    def test_omen_empty_or_full_keeps_first_freeze_without_random_selection(self):
        for mode, board in (('empty_minion', ()), ('normal', (FLY,)*7)):
            with self.subTest(mode=mode):
                game = self.game(hand=(OMEN,), mode=mode, board=board); rng = game.snapshot()['rng_state']
                target = game.state.players[2].hero_id; self.play(game, OMEN, target)
                self.assertTrue(game.state.entities[target].frozen); self.assertEqual(game.snapshot()['rng_state'], rng)

    def test_omen_unknown_eligible_minion_rolls_back_the_prior_freeze_and_payment(self):
        game = self.game(hand=(OMEN,), mode='unknown_minion'); saved = game.snapshot()
        with self.assertRaises(ResolutionError): self.play(game, OMEN, game.state.players[2].hero_id)
        self.assertEqual(game.snapshot(), saved)

    def test_new_reward_and_pool_callback_require_their_finite_shapes(self):
        with self.assertRaises(ValueError): DrawGroupReward('set_drawn_minion_stats', 0)
        with self.assertRaises(ValueError): DrawGroupReward('set_drawn_minion_stats', 2, repetitions=2)
        with self.assertRaises(ValueError): SummonFromPool(1, 'constructed.minions', on_summon=PREFIX+'freeze_summoned')


if __name__ == '__main__': unittest.main()
