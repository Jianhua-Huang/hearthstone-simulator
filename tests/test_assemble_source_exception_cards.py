"""Real donor-floor/Mage entries and the distinct owner-end hand clock."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_source_exception_cards import MAGE_FRAGMENT, MISMATCH, ROOTS, THAW, load_batch
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_assemble_entry_cards import POOL_ID
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import recipe_from_id
from hs_sim.engine.assemble_offers import Assemble
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import ChoiceOption, Draw, InvokeBehavior, RandomDamage, RequestChoice, ReturnToHand
from hs_sim.engine.model import CardClass, CardMetadata, CostSpec, Enchantment
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard, ModifyStoredCost, MoveCard
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face
import test_native_assemble_entry_cards as previous

COIN, FLY, HOARDER, BEAR, FREYA, CAIRNE, STEAM = (
    'GAME_005', 'CORE_UNG_809', 'CORE_EX1_096', 'BE_855', 'BE_856', 'CORE_EX1_110', 'CORE_REV_946')
MEMBERS = (FLY, HOARDER, BEAR, FREYA, CAIRNE, STEAM, MAGE_FRAGMENT)
FLOOR_POOL = (FLY, FREYA, CAIRNE, STEAM)
CTX = GenerationContext('k331-explicit-reviewed-fixture', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
P = 'fixture.assemble_source_exceptions.'
RAISE, COPY, STASH, RETURN, WATCH, FAIL = (P+x for x in ('raise', 'copy', 'stash', 'return', 'watch', 'fail'))


def stamps(entity): return [a for a in entity.enchantments if a.hand_turn_discount]


@lru_cache(maxsize=None)
def fixture(members=MEMBERS, mode='normal'):
    registry = build_registry()
    def ref(c): return CardReference.capture(c.state.entities[c.target_id])
    def fail(c): raise ResolutionError('Intentional original choice rollback')
    bodies = {
        RAISE: lambda c: (ModifyStoredCost(ref(c), CostSpec(delta=4), c.source_id),),
        COPY: lambda c: tuple(CopyCard(ref(c), c.player_id, mode=mode, source_id=c.source_id) for mode in ('current', 'base')),
        STASH: lambda c: (MoveCard(ref(c), c.player_id, Zone.DECK, 'top', source_id=c.source_id),),
        RETURN: lambda c: (ReturnToHand(c.target_id),), FAIL: fail,
    }
    for cid, body in bodies.items():
        registry.register_behavior(cid, body)
        if cid == FAIL: continue
        registry.register_card(CardDefinition(cid, 'Explicit physical operation', CardType.SPELL, metadata=META,
            on_play=cid, targeting=TargetSpec(zones=(Zone.BOARD if cid == RETURN else Zone.HAND,),
                kinds=(CardType.MINION,), relation='friendly')))
    registry.register_pool(PoolDefinition(POOL_ID, 'explicit-reviewed-v1', CTX.target_id,
        CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode != 'normal':
        def observe(c):
            source = c.state.entities.get(c.event.source_id)
            entity = c.state.entities.get(c.event.target_id)
            if (source is None or source.card_id != THAW or entity is None or
                    entity.controller != c.player_id or not entity.card_id.startswith('assemble:')): return ()
            own = stamps(entity)
            if len(own) != 1 or own[0].hand_discount_boundary != 'turn_ended':
                raise ResolutionError('Original creation lost its owner-end grant')
            if mode == 'created':
                if own[0].hand_discount_turn is not None: raise ResolutionError('Creation borrowed a prior end')
            elif c.state.turn != 1: return ()
            options = (ChoiceOption('continue', 'Continue original work'),
                ChoiceOption('fail', 'Rollback this selection', (
                    RandomDamage(tuple(c.state.players[p].hero_id for p in (1, 2)), 1, c.source_id),
                    InvokeBehavior(FAIL, c.source_id, c.player_id))))
            return (RequestChoice(c.player_id, options, c.source_id),)
        registry.register_behavior(WATCH, observe)
        registry.register_card(CardDefinition(WATCH, 'Original grant observer', CardType.MINION,
            health=20, metadata=META, triggers=(TriggerSpec('card_created' if mode == 'created' else 'cost_modified', WATCH),)))
    return registry


class AssembleSourceExceptionTests(unittest.TestCase):
    readers = {}
    play = previous.NativeAssembleEntryTests.play
    choose = previous.NativeAssembleEntryTests.choose
    offer = previous.NativeAssembleEntryTests.offer

    def game(self, hand=(THAW,), members=MEMBERS, mode='normal', hero=None):
        hero = hero or ('HERO_08' if THAW in hand else 'HERO_06')
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hero_power_card_id=hero+'bp', hand=hand, board=(WATCH,) if mode != 'normal' else (),
                deck=(COIN,)*12, mana=10, max_mana=10),
            PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', deck=(COIN,)*12, mana=10, max_mana=10)),
            seed=0, generation_context=CTX), fixture(members, mode))

    def received(self, game):
        return next(game.state.entities[i] for i in game.state.players[1].hand
            if game.state.entities[i].card_id.startswith('assemble:'))

    def price(self, game, entity=None):
        state = game.state
        current = state.entities[entity.id] if entity is not None else self.received(game)
        return quote_unselected_cost(state, game.registry, current).amount

    def thaw(self, game): self.play(game, THAW); return self.choose(game, FLY, 'top')

    def continue_choice(self, game, key='continue'):
        choice = game.state.pending_choice; game.apply(SelectChoice(choice.player_id, choice.id, (key,)))

    def portable(self, game, members=MEMBERS, mode='normal'):
        key = members, mode
        if key not in self.readers: self.readers[key] = fixture.__wrapped__(*key)
        registry = self.readers[key]; saved = game.snapshot()
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)), registry).snapshot(), saved)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), saved)
        for seat in (1, 2):
            public = json.dumps(game.for_player(seat).observe())+json.dumps(game.player_events(seat))
            for hidden in ('"hand_discount_boundary"', '"hand_discount_turn"', '"primary_candidates"', '"rng_state"'):
                self.assertNotIn(hidden, public)
        return Game.from_snapshot(saved, registry)

    def test_two_full_roots_one_whole_fragment_and_six_bilingual_faces(self):
        data = load_batch(); registry = fixture()
        rows = {r['record']['id']: r['record'] for r in data['cards']+data['existing_dependencies']}
        self.assertEqual(tuple(r['record']['id'] for r in data['cards']), ROOTS)
        for cid in ROOTS:
            self.assertEqual(asdict(registry.card(cid).metadata), asdict(metadata_from_record(rows[cid])))
        self.assertEqual(canonical_digest(asdict(registry.card(MAGE_FRAGMENT))), data['existing_dependencies'][0]['definition_sha256'])
        self.assertEqual(len(data['official_observations']), 6)
        for obs in data['official_observations']: check_face(rows[obs['card_id']], obs['face'], obs['locale'])

    def test_new_declarations_are_typed_source_bound_and_do_not_accept_other_class_mode(self):
        base = Assemble(1, POOL_ID, 1)
        for kwargs in (dict(secondary_min_cost=True), dict(secondary_min_cost=-1), dict(secondary_min_cost='5'),
                dict(source_id=None, secondary_min_cost=5), dict(primary_query=PoolQuery(class_mode='other')),
                dict(source_id=None, primary_query=PoolQuery(class_mode='specified', classes=(CardClass.MAGE,))),
                dict(minion_grant=CreatedMinionGrant(special='hand_turn_discount'))):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): replace(base, **kwargs)
        value = replace(base, minion_grant=CreatedMinionGrant(special='hand_turn_end_discount'))
        self.assertEqual(value.minion_grant.special, 'hand_turn_end_discount')

    def test_boundary_is_an_independent_validated_periodic_attachment_field(self):
        stamp = Enchantment(1, source_id=1, label='hand_turn_discount', hand_turn_discount=True,
            hand_discount_boundary='turn_ended')
        self.assertEqual(stamp.hand_discount_boundary, 'turn_ended')
        for kwargs in (dict(hand_discount_boundary='after'), dict(hand_turn_discount=False), dict(attack=1)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): replace(stamp, **kwargs)
        with self.assertRaises(ValueError): Enchantment(1, hand_discount_boundary='turn_ended')

    def test_mismatch_uses_all_high_donors_without_the_ordinary_plus_two_ceiling(self):
        game = self.game(hand=(MISMATCH,), members=FLOOR_POOL); source = self.play(game, MISMATCH); offer = self.offer(game)
        self.assertEqual(game.state.players[1].mana, 5)
        self.assertEqual((game.state.entities[source].attack, game.state.entities[source].health), (4, 6))
        self.assertIn(Keyword.TAUNT, game.state.entities[source].keywords)
        self.assertEqual(offer.primary_card_id, FLY); self.assertEqual(offer.spec.secondary_min_cost, 5)
        self.assertEqual(set(offer.secondary_candidates), {FREYA, CAIRNE, STEAM})
        self.assertTrue(all(game.registry.card(cid).cost > game.registry.card(FLY).cost+2 for cid in offer.secondary_card_ids))
        cid = self.choose(game); self.assertEqual(game.registry.card(cid).cost, 1)

    def test_mismatch_real_selected_low_card_payment_does_not_charge_donor_cost(self):
        game = self.game(hand=(MISMATCH,)); self.play(game, MISMATCH)
        option = next(o for o in game.state.pending_choice.options if recipe_from_id(o.card_id).secondary_card_id != STEAM)
        game.apply(SelectChoice(1, game.state.pending_choice.id, (option.id,)))
        cost = game.registry.card(option.card_id).cost
        self.assertLessEqual(cost, 3); self.play(game, option.card_id)
        self.assertEqual(game.state.players[1].mana, 5-cost)

    def test_absolute_floor_pending_choice_restores_same_offer_and_rng(self):
        game = self.game(hand=(MISMATCH,), members=FLOOR_POOL); self.play(game, MISMATCH)
        restored = self.portable(game, FLOOR_POOL); rng = game.snapshot()['rng_state']
        self.choose(game); self.choose(restored)
        self.assertEqual(game.snapshot(), restored.snapshot()); self.assertEqual(game.snapshot()['rng_state'], rng)

    def test_unknown_eligible_high_donor_rolls_back_source_board_mana_and_rng(self):
        game = self.game(hand=(MISMATCH,), members=(*FLOOR_POOL, 'BE_999')); saved = game.snapshot()
        with self.assertRaises(ResolutionError): self.play(game, MISMATCH)
        self.assertEqual(game.snapshot(), saved)

    def test_thaw_only_mage_primary_but_neutral_donors_are_eligible(self):
        game = self.game(); self.play(game, THAW); offer = self.offer(game)
        self.assertEqual(offer.primary_candidates, (MAGE_FRAGMENT,))
        self.assertEqual(set(offer.secondary_card_ids), {FLY, HOARDER})
        self.assertEqual(offer.spec.primary_query.class_mode, 'specified')
        self.assertFalse(offer.spec.primary_query.include_neutral)
        self.assertEqual(game.state.players[1].mana, 8)

    def test_foreign_hero_keeps_explicit_mage_primary_and_ordinary_current_hero_donor_policy(self):
        # The donor policy is explicitly experimental and pending CN calibration.
        game = self.game(hero='HERO_06'); self.play(game, THAW); offer = self.offer(game)
        self.assertEqual(offer.primary_candidates, (MAGE_FRAGMENT,))
        self.assertEqual(set(offer.secondary_candidates), {FLY, HOARDER, BEAR})

    def test_thaw_end_grant_survives_original_assembly_choice_restore(self):
        game = self.game(); self.play(game, THAW); restored = self.portable(game)
        self.choose(game, FLY, 'top'); self.choose(restored, FLY, 'top')
        self.assertEqual(game.snapshot(), restored.snapshot())
        stamp = stamps(self.received(game))[0]
        self.assertEqual(stamp.hand_discount_boundary, 'turn_ended'); self.assertIsNone(stamp.hand_discount_turn)

    def test_only_actual_owner_ends_discount_and_later_ends_continue_after_zero_floor(self):
        game = self.game(hand=(THAW, RAISE)); self.thaw(game); self.assertEqual(self.price(game), 1)
        game.apply(EndTurn(1)); self.assertEqual(self.price(game), 0)
        game.apply(EndTurn(2)); self.assertEqual(self.price(game), 0)
        self.play(game, RAISE, self.received(game).id); self.assertEqual(self.price(game), 4)
        game.apply(EndTurn(1)); self.assertEqual(self.price(game), 3)

    def test_first_creation_observer_sees_owner_end_stamp_before_any_tick(self):
        game = self.game(mode='created'); self.thaw(game)
        self.assertEqual(self.price(game), 1); restored = self.portable(game, mode='created')
        for value in (game, restored): self.continue_choice(value)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual(len(stamps(self.received(game))), 1)
        game.apply(EndTurn(1)); self.assertEqual(self.price(game), 0)

    def test_owner_end_tick_wait_preserves_completed_price_and_resumes_once(self):
        game = self.game(hand=(THAW, RAISE), mode='tick'); self.thaw(game)
        self.play(game, RAISE, self.received(game).id); game.apply(EndTurn(1))
        self.assertEqual(game.state.active_player, 1); self.assertEqual(self.price(game), 4)
        saved = game.snapshot(); restored = self.portable(game, mode='tick')
        with self.assertRaises(ResolutionError): self.continue_choice(game, 'fail')
        self.assertEqual(game.snapshot(), saved)
        for value in (game, restored): self.continue_choice(value)
        self.assertEqual(game.snapshot(), restored.snapshot()); self.assertEqual(self.price(game), 4)
        self.assertEqual(game.state.active_player, 2)

    def test_current_copy_keeps_independent_end_grant_while_base_copy_keeps_only_recipe(self):
        game = self.game(hand=(THAW, COPY)); cid = self.thaw(game); self.play(game, COPY, self.received(game).id)
        copies = [game.state.entities[i] for i in game.state.players[1].hand if game.state.entities[i].card_id == cid]
        self.assertEqual([len(stamps(e)) for e in copies], [1, 1, 0])
        self.assertNotEqual(stamps(copies[0])[0].id, stamps(copies[1])[0].id)
        game.apply(EndTurn(1)); self.assertEqual([self.price(game, e) for e in copies], [0, 0, 1])

    def test_deck_pause_and_natural_reentry_do_not_borrow_an_owner_start(self):
        game = self.game(hand=(THAW, STASH)); self.thaw(game); eid = self.received(game).id
        self.play(game, STASH, eid); game.apply(EndTurn(1)); game.apply(EndTurn(2))
        entity = self.received(game); self.assertEqual(entity.id, eid); self.assertEqual(self.price(game), 1)
        game.apply(EndTurn(1)); self.assertEqual(self.price(game), 0)

    def test_paid_play_and_return_reset_local_end_grant_but_preserve_new_printed_face(self):
        game = self.game(hand=(THAW, RETURN)); cid = self.thaw(game)
        game.apply(EndTurn(1)); game.apply(EndTurn(2)); eid = self.play(game, cid)
        self.play(game, RETURN, eid)
        self.assertEqual(game.state.entities[eid].card_id, cid); self.assertFalse(stamps(game.state.entities[eid]))
        self.assertEqual(self.price(game), 1); game.apply(EndTurn(1)); self.assertEqual(self.price(game), 1)

    def test_rehashed_unknown_boundary_and_future_clock_or_old_schema_are_rejected(self):
        game = self.game(); self.thaw(game); saved = game.snapshot(); entity = self.received(game)
        for key, value in (('hand_discount_boundary', 'after'), ('hand_discount_turn', 1000)):
            bad = deepcopy(saved)
            row = bad['state']['entities'][str(entity.id)]
            stamp = next(e for e in row['enchantments'] if e['hand_turn_discount']); stamp[key] = value
            bad['state_hash'] = canonical_hash({k:v for k,v in bad.items()
                if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
            with self.subTest(key=key), self.assertRaises(SnapshotError): Game.from_snapshot(bad, fixture())
        with self.assertRaises(SnapshotError): Game.from_snapshot({**saved, 'schema_version': 500}, fixture())


if __name__ == '__main__': unittest.main()
