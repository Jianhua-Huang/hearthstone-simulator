"""Four native sources and original physical delivery over existing creation."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_assemble_entry_cards import POOL_ID
from hs_sim.cards.native_assemble_followup_cards import (CHISEL, DEPENDENCIES, DEPTHS,
    GUARD, MECH_FRAGMENT, OVERDRIVE, PATCH, ROOTS, SCULPT, load_batch)
from hs_sim.engine import (Attack, CardDefinition, CardType, DeckPolicy, DeckSpec, EndTurn,
    Game, IllegalAction, Keyword, MatchSetup, OpeningHook, PlayCard, PlayerSetup,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_offers import Assemble
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChangeManaCrystals, ChoiceOption,
    RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.model import CardClass, CardMetadata, CostSpec, Rarity
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face
import test_native_assemble_entry_cards as previous

FOX, FREYA, CAIRNE = 'BE_859', 'BE_856', 'CORE_EX1_110'
COIN, RAVEN, FLY, HOARDER = 'GAME_005', 'KAR_300', 'CORE_UNG_809', 'CORE_EX1_096'
FOX_POOL, MECH_POOL, LOW_POOL = (FOX, FREYA, CAIRNE), (MECH_FRAGMENT, FREYA, CAIRNE), (FLY, HOARDER, 'BE_855')
CTX = GenerationContext('k330-explicit-reviewed-fixture', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
P = 'fixture.native_assemble_followups.'
RETURN, QUIET, GIVE, WATCH, BOOT = (P+x for x in ('return', 'silence', 'give', 'watch', 'boot'))


@lru_cache(maxsize=None)
def fixture(members=FOX_POOL, mode='normal'):
    registry = build_registry()
    bodies = {RETURN: lambda c: (ReturnToHand(c.target_id),), QUIET: lambda c: (Silence(c.target_id),),
        GIVE: lambda c: (ChangeControl(c.target_id, 3-c.player_id),)}
    for cid, body in bodies.items():
        registry.register_behavior(cid, body)
        registry.register_card(CardDefinition(cid, 'Explicit test operation', CardType.SPELL,
            metadata=META, on_play=cid, targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    registry.register_pool(PoolDefinition(POOL_ID, 'explicit-reviewed-v1', CTX.target_id,
        CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode == 'match':
        def boot(c):
            tail = (AddToHand(c.player_id, PATCH, c.source_id),) if c.player_id == 1 else (
                SummonByCard(c.player_id, (SummonEntryMaterial(RAVEN),), SummonCause.capture(c)),)
            return (ChangeManaCrystals(c.player_id, 10, filled=True), *tail)
        registry.register_behavior(BOOT, boot)
        registry.register_card(CardDefinition(BOOT, 'Real opening fixture', CardType.MINION, health=1,
            metadata=replace(META, collectible=True, rarity=Rarity.COMMON),
            opening_hooks=(OpeningHook('after_mulligan', BOOT),)))
    elif mode != 'normal':
        def observe(c):
            if mode == 'fill':
                if c.state.entities[c.event.source_id].card_id != SCULPT: return ()
                return (AddToHand(c.player_id, COIN, c.source_id),)
            entity = c.state.entities.get(c.event.target_id)
            if entity is None: return ()
            if mode == 'summon':
                if entity.card_id != GUARD or sum(c.state.entities[i].card_id == GUARD
                        for i in c.state.players[c.player_id].board) != 1: return ()
                label = 'First original guard has arrived'
            else:
                if not entity.card_id.startswith('assemble:'): return ()
                label = json.dumps(dict(entity=entity.id, attack=entity.attack, health=entity.health,
                    cost=quote_unselected_cost(c.state, registry, entity).amount))
            return (RequestChoice(c.player_id, (ChoiceOption('continue', label),), c.source_id),)
        registry.register_behavior(WATCH, observe)
        event = 'card_committed' if mode == 'fill' else 'minion_summoned' if mode == 'summon' else 'card_created'
        registry.register_card(CardDefinition(WATCH, 'Original event observer', CardType.MINION,
            health=12, metadata=META, triggers=(TriggerSpec(event, WATCH),)))
    return registry


class NativeAssembleFollowupTests(unittest.TestCase):
    readers = {}
    play = previous.NativeAssembleEntryTests.play
    choose = previous.NativeAssembleEntryTests.choose
    offer = previous.NativeAssembleEntryTests.offer
    coins = previous.NativeAssembleEntryTests.coins

    def game(self, hand=(SCULPT,), members=FOX_POOL, mode='normal', board=(), enemy=()):
        if mode != 'normal': board = (WATCH,)+board
        seed = 5 if members == LOW_POOL else 1 if CHISEL in hand else 0
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06', hero_power_card_id='HERO_06bp', hand=hand, board=board,
                deck=(COIN,)*12, max_mana=10, mana=10),
            PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', board=enemy,
                deck=(COIN,)*12, max_mana=10, mana=10)), seed=seed, generation_context=CTX), fixture(members, mode))

    def portable(self, game, members=FOX_POOL, mode='normal'):
        key = members, mode
        if key not in self.readers: self.readers[key] = fixture.__wrapped__(*key)
        registry = self.readers[key]; saved = game.snapshot()
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)), registry).snapshot(), saved)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), saved)
        for seat in (1, 2):
            public = json.dumps(game.for_player(seat).observe())+json.dumps(game.player_events(seat))
            for hidden in ('"primary_candidates"', '"rng_state"', '"rng_before"', '"minion_grant"'):
                self.assertNotIn(hidden, public)
        return Game.from_snapshot(saved, registry)

    def received(self, game):
        return next(game.state.entities[i] for i in game.state.players[1].hand
            if game.state.entities[i].card_id.startswith('assemble:'))

    def continue_choice(self, game):
        q = game.state.pending_choice; game.apply(SelectChoice(q.player_id, q.id, ('continue',)))

    def test_complete_four_roots_two_dependencies_and_fourteen_bilingual_faces(self):
        data = load_batch(); registry = fixture()
        rows = {r['record']['id']: r['record'] for r in data['cards']+data['dependencies']+data['existing_dependencies']}
        self.assertEqual(tuple(r['record']['id'] for r in data['cards']), ROOTS)
        self.assertEqual(tuple(r['record']['id'] for r in data['dependencies']), DEPENDENCIES)
        for cid in ROOTS+DEPENDENCIES:
            self.assertEqual(asdict(registry.card(cid).metadata), asdict(metadata_from_record(rows[cid])))
        self.assertEqual(canonical_digest(asdict(registry.card(MECH_FRAGMENT))), data['existing_dependencies'][0]['definition_sha256'])
        self.assertEqual(len(data['official_observations']), 14)
        for obs in data['official_observations']:
            check_face(rows[obs['card_id']], obs['face'], obs['locale'],
                numeric_normalizations=data['numeric_normalizations'].get(obs['card_id']))
        self.assertEqual((registry.card(GUARD).attack, registry.card(GUARD).health), (0, 3))
        self.assertEqual(registry.card(OVERDRIVE).cost, 0)

    def test_delivery_declarations_only_allow_needed_source_bound_numeric_grants(self):
        base = Assemble(1, POOL_ID, 1)
        self.assertEqual(replace(base, cost=CostSpec(delta=-2)).cost.delta, -2)
        self.assertEqual(replace(base, minion_grant=CreatedMinionGrant(2, 3)).minion_grant.health, 3)
        for kwargs in (dict(cost={'delta': -2}), dict(cost=CostSpec(delta=1)), dict(cost=CostSpec(set_to=0)),
                dict(source_id=None, cost=CostSpec(delta=-2)),
                dict(minion_grant=CreatedMinionGrant(-1, 1)),
                dict(minion_grant=CreatedMinionGrant(keywords=(Keyword.TAUNT,))),
                dict(cost=CostSpec(delta=-2), minion_grant=CreatedMinionGrant(2, 3))):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): replace(base, **kwargs)

    def test_depths_summons_two_distinct_original_guards_before_assembly(self):
        game = self.game(hand=(DEPTHS,)); self.play(game, DEPTHS)
        guards = [game.state.entities[i] for i in game.state.players[1].board]
        self.assertEqual([e.card_id for e in guards], [GUARD, GUARD])
        self.assertNotEqual(guards[0].id, guards[1].id)
        self.assertTrue(all(e.attack == 0 and e.health == 3 and Keyword.TAUNT in e.keywords for e in guards))
        self.assertEqual(game.state.players[1].mana, 8); self.assertIsNotNone(self.offer(game))

    def test_depths_capacity_does_not_cancel_subsequent_assembly(self):
        game = self.game(hand=(DEPTHS,), board=(RAVEN,)*6); self.play(game, DEPTHS)
        self.assertEqual(len(game.state.players[1].board), 7)
        self.assertEqual(sum(game.state.entities[i].card_id == GUARD for i in game.state.players[1].board), 1)
        self.choose(game); self.assertTrue(self.received(game).card_id.startswith('assemble:'))

    def test_depths_first_summon_wait_restores_original_second_request_and_payment(self):
        game = self.game(hand=(DEPTHS,), mode='summon'); self.play(game, DEPTHS)
        self.assertEqual(sum(game.state.entities[i].card_id == GUARD for i in game.state.players[1].board), 1)
        restored = self.portable(game, mode='summon')
        for value in (game, restored): self.continue_choice(value)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual(sum(game.state.entities[i].card_id == GUARD for i in game.state.players[1].board), 2)
        self.assertEqual(game.state.players[1].mana, 8); self.choose(game)

    def test_patch_constrains_only_primary_mech_and_gives_named_overdrive_after_selection(self):
        game = self.game(hand=(PATCH,), members=MECH_POOL); self.play(game, PATCH); offer = self.offer(game)
        self.assertEqual(offer.primary_card_id, MECH_FRAGMENT)
        self.assertEqual(offer.spec.primary_query.tribes_any, ('mech',))
        self.assertEqual(set(offer.secondary_card_ids), {FREYA, CAIRNE})
        self.assertEqual(game.state.players[1].hand, [])
        self.choose(game, CAIRNE, 'top')
        self.assertEqual([game.state.entities[i].card_id for i in game.state.players[1].hand], [self.received(game).card_id, OVERDRIVE])
        self.assertEqual(game.state.players[1].mana, 8)

    def test_patch_acquisition_wait_keeps_actual_original_recipe_then_named_reward(self):
        game = self.game(hand=(PATCH,), members=MECH_POOL, mode='created'); self.play(game, PATCH)
        self.choose(game, CAIRNE, 'top')
        self.assertFalse(any(game.state.entities[i].card_id == OVERDRIVE for i in game.state.players[1].hand))
        restored = self.portable(game, MECH_POOL, 'created')
        for value in (game, restored): self.continue_choice(value)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual(sum(game.state.entities[i].card_id == OVERDRIVE for i in game.state.players[1].hand), 1)

    def test_sculpt_reduction_is_on_selected_new_entity_and_real_payment(self):
        game = self.game(hand=(SCULPT, RAVEN)); raven = game.state.players[1].hand[1]
        self.play(game, SCULPT); self.assertEqual(self.offer(game).spec.cost, CostSpec(delta=-2))
        cid = self.choose(game, FREYA, 'top'); entity = self.received(game)
        self.assertEqual(game.registry.card(cid).cost, 4)
        self.assertEqual(quote_unselected_cost(game.state, game.registry, entity).amount, 2)
        self.assertEqual(quote_unselected_cost(game.state, game.registry, game.state.entities[raven]).amount, 1)
        self.play(game, cid); self.assertEqual(game.state.players[1].mana, 5)

    def test_sculpt_cost_has_zero_floor_and_does_not_change_printed_recipe(self):
        game = self.game(members=LOW_POOL); self.play(game, SCULPT); cid = self.choose(game, HOARDER, 'top')
        self.assertEqual(game.registry.card(cid).cost, 1)
        self.assertEqual(quote_unselected_cost(game.state, game.registry, self.received(game)).amount, 0)
        self.play(game, cid); self.assertEqual(game.state.players[1].mana, 7)

    def test_sculpt_creation_observer_sees_discount_and_wait_resumes_once(self):
        game = self.game(mode='created'); self.play(game, SCULPT); self.choose(game, FREYA, 'top')
        self.assertEqual(json.loads(game.state.pending_choice.options[0].label)['cost'], 2)
        restored = self.portable(game, mode='created')
        for value in (game, restored): self.continue_choice(value)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual(quote_unselected_cost(game.state, game.registry, self.received(game)).amount, 2)

    def test_sculpt_full_hand_burn_keeps_original_recipe_without_modifying_old_cards(self):
        game = self.game(hand=(SCULPT,)+(COIN,)*9, mode='fill'); self.play(game, SCULPT)
        self.assertEqual(len(game.state.players[1].hand), 10)
        cid = self.choose(game, FREYA, 'top')
        burned = [e for e in game.state.entities.values() if e.card_id == cid]
        self.assertEqual(len(burned), 1); self.assertEqual(burned[0].zone, Zone.GRAVEYARD)
        self.assertEqual(quote_unselected_cost(game.state, game.registry, burned[0]).amount, 2)
        self.assertEqual(len(game.state.players[1].hand), 10)

    def test_return_resets_local_discount_while_preserving_new_printed_recipe(self):
        game = self.game(hand=(SCULPT, RETURN)); self.play(game, SCULPT); cid = self.choose(game, FREYA, 'top')
        eid = self.play(game, cid); self.play(game, RETURN, eid)
        self.assertEqual(game.state.entities[eid].card_id, cid)
        self.assertEqual(quote_unselected_cost(game.state, game.registry, game.state.entities[eid]).amount, 4)

    def test_chisel_uses_original_taunt_then_grants_only_selected_entity_current_stats(self):
        game = self.game(hand=(CHISEL, RAVEN)); raven = game.state.players[1].hand[1]
        self.play(game, CHISEL); self.assertEqual(self.offer(game).primary_card_id, FOX)
        cid = self.choose(game, FREYA, 'top'); entity = self.received(game)
        self.assertNotIn(Keyword.TAUNT, game.registry.card(cid).keywords)
        self.assertEqual((game.registry.card(cid).attack, game.registry.card(cid).health), (2, 4))
        self.assertEqual((entity.attack, entity.health), (4, 7))
        self.assertEqual((game.state.entities[raven].attack, game.state.entities[raven].health), (2, 2))
        self.play(game, cid); self.assertEqual(self.coins(game), 4)

    def test_chisel_stat_grant_is_already_present_at_first_creation_notification(self):
        game = self.game(hand=(CHISEL,), mode='created'); self.play(game, CHISEL); self.choose(game, FREYA, 'top')
        proof = json.loads(game.state.pending_choice.options[0].label)
        self.assertEqual((proof['attack'], proof['health'], proof['cost']), (4, 7, 4))
        self.continue_choice(game); self.assertEqual(self.received(game).attack, 4)

    def test_pending_grants_restore_and_other_snapshot_schemas_are_rejected(self):
        game = self.game(); self.play(game, SCULPT); saved = game.snapshot()
        restored = self.portable(game)
        self.choose(game, FREYA, 'top'); self.choose(restored, FREYA, 'top')
        self.assertEqual(game.snapshot(), restored.snapshot())
        for version in (499, 501):
            with self.subTest(version=version), self.assertRaises(SnapshotError):
                Game.from_snapshot({**saved, 'schema_version': version}, fixture())

    def test_unknown_eligible_fragment_rolls_back_summons_mana_and_rng(self):
        game = self.game(hand=(DEPTHS,), members=(*FOX_POOL, 'BE_999')); saved = game.snapshot()
        with self.assertRaises(ResolutionError): self.play(game, DEPTHS)
        self.assertEqual(game.snapshot(), saved)

    def test_overdrive_real_rush_attack_and_natural_end_destruction(self):
        policy = DeckPolicy(P+'policy', CTX.target_id, CTX.mode, (BOOT, RAVEN), deck_size=12, max_copies=12)
        deck = (BOOT,)+(RAVEN,)*11
        setup = MatchSetup(tuple(DeckSpec('HERO_06', 'HERO_06bp', CardClass.DRUID, deck) for _ in (1, 2)),
            policy, COIN, seed=0, first_player=1)
        game = Game.from_decks(setup, fixture(MECH_POOL, 'match'))
        while game.state.pending_choice:
            choice = game.state.pending_choice; game.apply(SelectChoice(choice.player_id, choice.id, ()))
        self.play(game, PATCH)
        cid = self.choose(game, CAIRNE, 'top'); eid = self.play(game, cid); self.play(game, OVERDRIVE, eid)
        entity = game.state.entities[eid]
        self.assertEqual((entity.attack, entity.health), (7, 5)); self.assertIn(Keyword.RUSH, entity.keywords)
        with self.assertRaises(IllegalAction): game.apply(Attack(1, eid, game.state.players[2].hero_id))
        game.apply(Attack(1, eid, game.state.players[2].board[0]))
        game.apply(EndTurn(1)); self.assertEqual(game.state.entities[eid].zone, Zone.GRAVEYARD)
        self.portable(game, MECH_POOL, 'match')

    def test_overdrive_target_precheck_rejects_enemy_or_non_mech_without_payment(self):
        game = self.game(hand=(OVERDRIVE,), board=(RAVEN,), enemy=(MECH_FRAGMENT,)); saved = game.snapshot()
        for target in (game.state.players[1].board[0], game.state.players[2].board[0]):
            with self.subTest(target=target), self.assertRaises(IllegalAction): self.play(game, OVERDRIVE, target)
            self.assertEqual(game.snapshot(), saved)

    def test_overdrive_dies_at_this_end_even_after_control_changes(self):
        game = self.game(hand=(OVERDRIVE, GIVE), board=(MECH_FRAGMENT,)); eid = game.state.players[1].board[0]
        self.play(game, OVERDRIVE, eid); self.play(game, GIVE, eid)
        self.assertEqual(game.state.entities[eid].controller, 2)
        game.apply(EndTurn(1)); self.assertEqual(game.state.entities[eid].zone, Zone.GRAVEYARD)

    def test_silence_removes_overdrive_stats_rush_and_end_trigger(self):
        game = self.game(hand=(OVERDRIVE, QUIET), board=(MECH_FRAGMENT,)); eid = game.state.players[1].board[0]
        self.play(game, OVERDRIVE, eid); self.play(game, QUIET, eid); game.apply(EndTurn(1))
        entity = game.state.entities[eid]
        self.assertEqual(entity.zone, Zone.BOARD); self.assertEqual((entity.attack, entity.health), (5, 5))
        self.assertNotIn(Keyword.RUSH, entity.keywords)


if __name__ == '__main__': unittest.main()
