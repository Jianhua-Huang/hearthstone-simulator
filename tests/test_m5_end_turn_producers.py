"""R-147 structural carrier pools and one-draw end-turn producers."""
import json
import random
import unittest
from copy import deepcopy
from dataclasses import replace

import test_m5_end_turn_activations as activation_fixtures
from hs_sim.engine import (AddPlayerEffect, CardClass, CardDefinition, CardType,
    EndTurn, EndTurnSpec, Game, LimitedTriggerSpec, PlayCard, PlayerEffectSpec,
    PlayerSetup, RemovePlayerEffect, ResolutionError,
    ResolutionLimitExceeded, Ruleset, Scenario, SelectChoice, SnapshotError,
    TriggerSpec, Zone)
from hs_sim.engine.effects import (ChangeControl, Damage, Destroy,
    GainArmor, GrantTrigger, RandomDamage, Silence,
    Transform, TriggerDeathrattles)
from hs_sim.engine.end_turn_producers import (TriggerRandomEndTurnEffects,
    end_turn_carriers, validate_selection)
from hs_sim.engine.end_turns import TriggerEndTurnEffects
from hs_sim.engine.model import (CardMetadata, EndTurnCandidateProfile,
    EndTurnProducerRequest, EndTurnRepeatSpec, EndTurnSelection, EndTurnSelector,
    Keyword, Rarity, validate_end_turn_rng)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import (CARD_LIMITATIONS, EXPECTED_CARD_HASHES,
    build_registry)
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest, load_baseline


ALL = activation_fixtures.CARRIERS
MAUL_HASH = '43df6f13cb9f2d5cc6c02d39906c1c93e44df959f484bbc872b8314a4163f2e9'


def request(players=(1,), carriers=('minion',), *, entities=(), effects=(),
            mode='owner', candidate='end_turn.candidates', activation='end_turn.effect'):
    return EndTurnProducerRequest(EndTurnSelector(mode, players, carriers, entities, effects),
        candidate, activation)


def fixture_registry():
    r = activation_fixtures.fixture_registry()
    for profile in (
            EndTurnCandidateProfile('any', presence='any'),
            EndTurnCandidateProfile('lacks', presence='lacks_body'),
            EndTurnCandidateProfile('current', basis='current', consumed='include'),
            EndTurnCandidateProfile('current.unconsumed', basis='current'),
            EndTurnCandidateProfile('printed', basis='printed', consumed='include'),
            EndTurnCandidateProfile('printed.lacks', presence='lacks_body',
                basis='printed', consumed='include'),
            EndTurnCandidateProfile('dormant.include', dormant='include'),
            EndTurnCandidateProfile('dormant.only', dormant='only'),
            EndTurnCandidateProfile('not.live', live_only=False)):
        r.register_end_turn_candidate_profile(profile)
    r.register_behavior('producer', lambda c: [TriggerRandomEndTurnEffects(
        c.player_id, request(), c.source_id)])
    r.register_card(CardDefinition('producer', 'producer', CardType.SPELL, on_play='producer'))
    r.register_behavior('producer.hero', lambda c: [TriggerRandomEndTurnEffects(c.player_id, request())])
    r.register_card(CardDefinition('producer.hero', 'producer.hero', CardType.SPELL,
        on_play='producer.hero'))
    r.register_card(CardDefinition('many', 'many', CardType.MINION, health=8,
        triggers=tuple(TriggerSpec('turn_ended', 'armor', EndTurnSpec()) for _ in range(3))))
    r.register_card(CardDefinition('finite.one', 'finite.one', CardType.MINION, health=8,
        limited_triggers=(LimitedTriggerSpec('turn_ended', 'armor', uses=1,
            end_turn=EndTurnSpec()),)))
    r.register_card(CardDefinition('finite.wait', 'finite.wait', CardType.MINION, health=8,
        limited_triggers=(LimitedTriggerSpec('turn_ended', 'waiting', uses=2,
            end_turn=EndTurnSpec()),)))
    return r


class EndTurnProducerTests(unittest.TestCase):
    def setUp(self):
        self.r = fixture_registry()

    def game(self, board=('end',), enemy=(), hand=('producer',), *,
             power='power', weapon=None, rules=None, seed=147):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', board=board, hand=hand, deck=('plain',) * 20,
                mana=10, max_mana=10, hero_power_card_id=power, weapon_card_id=weapon),
            PlayerSetup('hero', board=enemy, deck=('plain',) * 20,
                mana=10, max_mana=10, hero_power_card_id='power')), seed=seed), self.r,
            ruleset=rules)

    def script(self, name, callback):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))

    def minion(self, name, callback, **kwargs):
        self.r.register_behavior(name, callback)
        kwargs.setdefault('health', 8)
        kwargs.setdefault('triggers', (TriggerSpec('turn_ended', name, EndTurnSpec()),))
        self.r.register_card(CardDefinition(name, name, CardType.MINION, **kwargs))

    def play(self, game, card='producer', *, position=None):
        player = game.state.active_player
        entity = next(i for i in game.state.players[player].hand
            if game.state.entities[i].card_id == card)
        game.apply(PlayCard(player, entity, position=position))
        return entity

    def choose(self, game):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, ('one',)))

    def armor(self, game, owner=1):
        return game.state.entities[game.state.players[owner].hero_id].armor

    def body(self, game, index=0, owner=1):
        return game.state.entities[game.state.players[owner].board[index]]

    def batch(self, game):
        return game.state.end_turn_batches[-1]

    def pool(self, game, candidate='end_turn.candidates', selector=None):
        return end_turn_carriers(game.state, self.r,
            selector or EndTurnSelector('owner', (1,), ('minion',)), candidate)

    def selection(self, game):
        return self.batch(game).activation.selection

    def check(self, game, *, fresh=False):
        registry = fixture_registry() if fresh else self.r
        snapshot = json.loads(json.dumps(game.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot, registry).snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), snapshot)

    def named(self, value, name):
        found = []
        if isinstance(value, dict):
            if str(value.get('type', '')).endswith('.' + name):
                found.append(value)
            for child in value.values():
                found.extend(self.named(child, name))
        elif isinstance(value, list):
            for child in value:
                found.extend(self.named(child, name))
        return found

    def queue(self, snapshot):
        return snapshot['resolution_frame']['fields']['continuation']['tuple']

    def rehash(self, snapshot):
        snapshot['events_hash'] = canonical_hash(snapshot['events'])
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        return snapshot

    def reject(self, snapshot):
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(self.rehash(snapshot), self.r)
        self.assertNotIn('digest mismatch', str(error.exception))
        return str(error.exception)

    def waiting(self, *, extra=False, unselected=False):
        board = ('double', 'waiting') if extra else ('waiting',)
        if unselected:
            board += ('never',)
        game = self.game(board=board)
        self.play(game)
        self.assertIsNotNone(game.state.pending_choice)
        if extra:
            self.choose(game)
            self.assertIsNotNone(game.state.pending_choice)
        return game

    def install(self, game, name='persistent'):
        return self.play(game, name)

    def test_default_candidate_profile_is_explicit_structural_policy(self):
        self.assertEqual(self.r.end_turn_candidate_profile('end_turn.candidates'),
            EndTurnCandidateProfile('end_turn.candidates'))

    def test_candidate_profile_enums_and_boolean_are_strict(self):
        for field, value in (('presence', 'ready'), ('basis', 'text'),
                ('dormant', 'all'), ('consumed', True), ('live_only', 1), ('id', '')):
            with self.subTest(field=field), self.assertRaises(ValueError):
                EndTurnCandidateProfile(**dict({'id': 'bad'}, **{field: value}))

    def test_active_profile_cannot_include_consumed_abilities(self):
        with self.assertRaises(ValueError):
            EndTurnCandidateProfile('bad', consumed='include')

    def test_printed_profile_must_ignore_consumption(self):
        with self.assertRaises(ValueError):
            EndTurnCandidateProfile('bad', basis='printed')
        self.assertEqual(EndTurnCandidateProfile('ok', basis='printed', consumed='include').basis,
            'printed')

    def test_registry_profiles_are_registered_readonly_and_fingerprinted(self):
        before = self.r.fingerprint()
        self.r.register_end_turn_candidate_profile(EndTurnCandidateProfile('new'))
        self.assertNotEqual(before, self.r.fingerprint())
        with self.assertRaises((TypeError, AttributeError)):
            self.r.end_turn_candidate_profiles['new'] = EndTurnCandidateProfile('other')
        with self.assertRaises((ValueError, ResolutionError)):
            self.r.register_end_turn_candidate_profile(EndTurnCandidateProfile('new'))

    def test_unknown_candidate_and_activation_profiles_roll_back_without_draw(self):
        for field in ('candidate', 'activation'):
            with self.subTest(field=field):
                self.r = fixture_registry()
                name = 'bad.' + field
                self.script(name, lambda c, f=field: [TriggerRandomEndTurnEffects(1,
                    request(**{f: 'unknown'}), c.source_id)])
                game = self.game(hand=(name,))
                before = game.snapshot()
                with self.assertRaises(ResolutionError):
                    self.play(game, name)
                self.assertEqual(game.snapshot(), before)

    def test_producer_request_and_effect_require_typed_inputs(self):
        for callback in (
                lambda: EndTurnProducerRequest(None),
                lambda: EndTurnProducerRequest(request().selector, ''),
                lambda: TriggerRandomEndTurnEffects(True, request()),
                lambda: TriggerRandomEndTurnEffects(1, activation_fixtures.request()),
                lambda: TriggerRandomEndTurnEffects(1, request(), source_id=0),
                lambda: TriggerRandomEndTurnEffects(1, request(), cause='turn_ended')):
            with self.subTest(callback=callback), self.assertRaises(ValueError):
                callback()

    def test_rng_witness_requires_v3_strict_words_and_index(self):
        value = random.Random(17).getstate()
        validate_end_turn_rng(value)
        for bad in (list(value), (True, value[1], None), (2, value[1], None),
                (3, value[1][:-1], None), (3, (True,) + value[1][1:], None),
                (3, value[1][:-1] + (625,), None),
                (3, (2 ** 32,) + value[1][1:], None)):
            with self.subTest(bad=str(bad)[:35]), self.assertRaises(ValueError):
                validate_end_turn_rng(bad)

    def test_rng_gaussian_cache_requires_finite_float(self):
        value = random.Random(17).getstate()
        validate_end_turn_rng((3, value[1], 0.25))
        for cache in (True, 0, float('inf'), float('nan')):
            with self.subTest(cache=cache), self.assertRaises(ValueError):
                validate_end_turn_rng((3, value[1], cache))

    def test_query_is_pure_and_never_runs_body_conditions(self):
        game = self.game(board=('bad_condition', 'never', 'end'))
        before = game.snapshot()
        self.assertEqual([c.card_id for c in self.pool(game)], ['bad_condition', 'never', 'end'])
        self.assertEqual(game.snapshot(), before)

    def test_presence_any_has_and_lacks_distinguish_unclassified_listener(self):
        game = self.game(board=('end', 'raw', 'plain', 'double'))
        self.assertEqual([c.card_id for c in self.pool(game)], ['end'])
        self.assertEqual([c.card_id for c in self.pool(game, 'lacks')], ['raw', 'plain', 'double'])
        self.assertEqual(len(self.pool(game, 'any')), 4)

    def test_finite_false_condition_still_has_candidate_weight(self):
        game = self.game(board=('finite_never', 'never'))
        self.assertEqual([c.card_id for c in self.pool(game)], ['finite_never', 'never'])

    def test_one_carrier_with_three_bodies_gets_one_pool_slot(self):
        game = self.game(board=('many', 'end'))
        self.assertEqual(len(self.pool(game)), 2)
        self.assertEqual(len({c.key for c in self.pool(game)}), 2)

    def test_owner_and_carrier_filters_intersect_in_stable_listener_order(self):
        game = self.game(board=('end', 'location'), enemy=('end',), power='end_power', weapon='weapon')
        rows = self.pool(game, selector=EndTurnSelector('owner', (2, 1), ALL))
        self.assertEqual([c.player_id for c in rows], [1, 1, 1, 1, 2])
        self.assertEqual({c.kind for c in rows}, {'minion', 'location', 'weapon', 'hero_power'})
        only = self.pool(game, selector=EndTurnSelector('owner', (2,), ('minion',)))
        self.assertEqual([c.source_id for c in only], [self.body(game, owner=2).id])

    def test_selected_ids_do_not_override_owner_or_kind_scope(self):
        game = self.game(board=('end', 'location'), enemy=('end',))
        ids = (self.body(game, owner=2).id, self.body(game, index=1).id, self.body(game).id)
        rows = self.pool(game, selector=EndTurnSelector('selected', (1,), ('minion',), ids))
        self.assertEqual([c.source_id for c in rows], [self.body(game).id])

    def test_selected_empty_ids_do_not_default_to_owner_pool(self):
        self.assertEqual(self.pool(self.game(), selector=EndTurnSelector('selected', (1,), ALL)), ())

    def test_selected_unknown_entity_and_instance_ids_are_explicit_errors(self):
        game = self.game()
        for selector in (EndTurnSelector('selected', (1,), ALL, (99999,)),
                EndTurnSelector('selected', (1,), ALL, player_effect_ids=(99999,))):
            with self.subTest(selector=selector), self.assertRaises(ResolutionError):
                self.pool(game, selector=selector)

    def test_hand_and_deck_entities_are_not_candidates_even_selected(self):
        game = self.game(board=(), hand=('end', 'producer'))
        ids = tuple(game.state.players[1].hand + game.state.players[1].deck)
        self.assertEqual(self.pool(game, 'any', EndTurnSelector('selected', (1,), ALL, ids)), ())

    def test_dormant_policies_are_independent_of_presence_basis(self):
        game = self.game(board=('dormant', 'end'))
        self.assertEqual([c.card_id for c in self.pool(game)], ['end'])
        self.assertEqual([c.card_id for c in self.pool(game, 'dormant.include')], ['dormant', 'end'])
        self.assertEqual([c.card_id for c in self.pool(game, 'dormant.only')], ['dormant'])

    def test_live_filter_detects_doomed_and_zero_health_without_mutating_state(self):
        game = self.game()
        for doomed, damage in ((True, 0), (False, 8)):
            state = game.state
            entity = state.entities[state.players[1].board[0]]
            entity.doomed, entity.damage = doomed, damage
            selector = request().selector
            self.assertEqual(end_turn_carriers(state, self.r, selector), ())
            self.assertEqual(len(end_turn_carriers(state, self.r, selector, 'not.live')), 1)
        self.assertEqual(len(self.pool(game)), 1)

    def test_live_filter_checks_weapon_and_location_durability_but_not_hp_health(self):
        game = self.game(board=('location',), power='end_power', weapon='weapon')
        state = game.state
        state.entities[state.players[1].weapon_id].durability = 0
        state.entities[state.players[1].board[0]].durability = 0
        selector = EndTurnSelector('owner', (1,), ALL)
        self.assertEqual([c.kind for c in end_turn_carriers(state, self.r, selector)], ['hero_power'])
        self.assertEqual(len(end_turn_carriers(state, self.r, selector, 'not.live')), 3)

    def test_silenced_printed_body_remains_printed_but_not_current_or_active(self):
        self.script('silence', lambda c: [Silence(c.state.players[1].board[0])])
        game = self.game(hand=('silence',))
        self.play(game, 'silence')
        self.assertEqual(self.pool(game), ())
        self.assertEqual(self.pool(game, 'current'), ())
        self.assertEqual([c.card_id for c in self.pool(game, 'printed')], ['end'])

    def test_granted_body_is_current_and_active_without_becoming_printed(self):
        self.script('grant', lambda c: [GrantTrigger(c.state.players[1].board[0],
            'turn_ended', 'armor', c.source_id, end_turn=EndTurnSpec())])
        game = self.game(board=('plain',), hand=('grant',))
        self.play(game, 'grant')
        self.assertEqual(len(self.pool(game)), 1)
        self.assertEqual(len(self.pool(game, 'current')), 1)
        self.assertEqual(self.pool(game, 'printed'), ())

    def test_transform_uses_new_physical_printed_identity(self):
        self.script('transform', lambda c: [Transform(c.state.players[1].board[0], 'plain')])
        game = self.game(hand=('transform',))
        old_id = self.body(game).id
        self.play(game, 'transform')
        self.assertEqual(self.body(game).id, old_id)
        self.assertEqual(self.pool(game, 'printed'), ())
        self.assertEqual([c.card_id for c in self.pool(game, 'printed.lacks')], ['plain'])

    def test_exhausted_finite_body_remains_current_include_and_printed(self):
        game = self.game(board=('finite.one',))
        self.play(game)
        self.assertEqual(self.pool(game), ())
        self.assertEqual(self.pool(game, 'current.unconsumed'), ())
        self.assertEqual([c.card_id for c in self.pool(game, 'current')], ['finite.one'])
        self.assertEqual(len(self.pool(game, 'printed')), 1)

    def test_magnetic_classification_belongs_to_host_current_not_component_printed(self):
        metadata = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('mech',))
        self.minion('part', lambda c: [GainArmor(1, 1)], keywords=(Keyword.MAGNETIC,),
            magnetic_tribes=('mech',), metadata=metadata)
        self.r.register_card(CardDefinition('host', 'host', CardType.MINION, health=8, metadata=metadata))
        game = self.game(board=('host',), hand=('part',))
        self.play(game, 'part', position=0)
        self.assertEqual([c.card_id for c in self.pool(game)], ['host'])
        self.assertEqual(self.pool(game, 'printed'), ())

    def test_player_effect_instances_with_same_source_have_independent_weights(self):
        self.script('install', lambda c: [AddPlayerEffect(1, 'persistent', c.state.players[1].board[0]),
            AddPlayerEffect(1, 'persistent', c.state.players[1].board[0])])
        game = self.game(hand=('install',))
        self.play(game, 'install')
        rows = self.pool(game, selector=EndTurnSelector('owner', (1,), ALL))
        self.assertEqual([c.kind for c in rows], ['minion', 'player_effect', 'player_effect'])
        self.assertEqual(len({c.key for c in rows}), 3)
        self.assertEqual(len({c.source_id for c in rows}), 1)

    def test_selected_player_instance_does_not_select_its_physical_source(self):
        game = self.game(hand=('persistent',))
        self.install(game)
        instance = game.state.players[1].player_effects[0]
        rows = self.pool(game, selector=EndTurnSelector('selected', (1,), ALL,
            player_effect_ids=(instance.id,)))
        self.assertEqual([c.key for c in rows], [('player_effect', instance.id)])

    def test_player_presence_is_same_for_active_current_and_printed(self):
        game = self.game(hand=('persistent',))
        self.install(game)
        selector = EndTurnSelector('owner', (1,), ('player_effect',))
        pools = [self.pool(game, p, selector) for p in ('end_turn.candidates', 'current', 'printed')]
        self.assertEqual(pools[0], pools[1])
        self.assertEqual(pools[1], pools[2])
        self.assertEqual(self.pool(game, 'dormant.only', selector), ())

    def test_player_carrier_survives_source_death_transform_and_control_change(self):
        for operation in ('death', 'transform', 'control'):
            with self.subTest(operation=operation):
                self.r = fixture_registry()
                name = 'install.' + operation
                def callback(c, op=operation):
                    source = c.state.players[1].board[0]
                    change = Destroy(source) if op == 'death' else Transform(source, 'plain')
                    if op == 'control':
                        change = ChangeControl(source, 2)
                    return [AddPlayerEffect(1, 'persistent', source), change]
                self.script(name, callback)
                game = self.game(hand=(name,))
                self.play(game, name)
                rows = self.pool(game, selector=EndTurnSelector('owner', (1,), ('player_effect',)))
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0].player_id, rows[0].card_id), (1, 'end'))
                self.check(game)

    def test_removed_player_instance_leaves_candidate_pool(self):
        self.script('remove', lambda c: [RemovePlayerEffect(1, c.state.players[1].player_effects[0].id)])
        game = self.game(hand=('persistent', 'remove'))
        self.install(game)
        self.play(game, 'remove')
        self.assertEqual(self.pool(game, selector=EndTurnSelector('owner', (1,), ('player_effect',))), ())

    def test_singleton_pool_still_consumes_exactly_one_choice(self):
        game = self.game()
        before = game._rng.getstate()
        candidates = self.pool(game)
        probe = random.Random(); probe.setstate(before)
        expected = probe.choice(candidates)
        self.play(game)
        selection = self.selection(game)
        self.assertEqual((selection.selected, selection.rng_before, selection.rng_after),
            (expected, before, probe.getstate()))
        self.assertNotEqual(before, selection.rng_after)
        self.assertEqual(self.armor(game), 1)
        self.check(game, fresh=True)

    def test_many_bodies_on_selected_carrier_all_execute_without_resampling(self):
        game = self.game(board=('many', 'double'))
        self.play(game)
        self.assertEqual(len(self.selection(game).candidates), 1)
        self.assertEqual(len(self.batch(game).subjects), 3)
        self.assertEqual(self.batch(game).total, 6)
        self.assertEqual(self.armor(game), 6)
        self.check(game, fresh=True)

    def test_false_condition_carrier_draws_but_creates_zero_subjects(self):
        game = self.game(board=('never',))
        self.play(game)
        selection = self.selection(game)
        self.assertEqual(selection.selected.card_id, 'never')
        self.assertNotEqual(selection.rng_before, selection.rng_after)
        self.assertEqual(self.batch(game).subjects, ())
        self.assertTrue(self.batch(game).completed)
        self.check(game, fresh=True)

    def test_truly_empty_pool_preserves_rng_and_records_empty_selection(self):
        game = self.game(board=('raw', 'plain', 'double'))
        before = game._rng.getstate()
        self.play(game)
        selection = self.selection(game)
        self.assertEqual((selection.candidates, selection.selected), ((), None))
        self.assertEqual((selection.rng_before, selection.rng_after, game._rng.getstate()),
            (before, before, before))
        self.assertEqual(self.armor(game), 0)
        self.check(game, fresh=True)

    def test_nonbool_body_condition_rolls_back_draw_and_action(self):
        game = self.game(board=('bad_condition',))
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game)
        self.assertEqual(game.snapshot(), before)

    def test_default_issuer_is_player_hero_with_legal_entry_zero(self):
        game = self.game(hand=('producer.hero',))
        original_hero = game.state.entities[game.state.players[1].hero_id]
        self.play(game, 'producer.hero')
        activation = self.batch(game).activation
        self.assertEqual(activation.issuer_id, game.state.players[1].hero_id)
        self.assertEqual(activation.issuer_entered_order, original_hero.entered_order)
        self.check(game, fresh=True)

    def test_generic_random_producer_executes_each_of_five_carrier_types(self):
        for kind in ALL:
            with self.subTest(kind=kind):
                self.r = fixture_registry()
                name = 'only.' + kind
                self.script(name, lambda c, k=kind: [TriggerRandomEndTurnEffects(1,
                    request(carriers=(k,)), c.source_id)])
                game = self.game(board=('end', 'location'), power='end_power', weapon='weapon',
                    hand=('persistent', name))
                self.install(game)
                self.play(game, name)
                self.assertEqual(self.selection(game).selected.kind, kind)
                self.assertEqual(self.armor(game), 1)
                self.check(game)

    def test_qualification_does_not_apply_turn_scope_and_activation_profile_does(self):
        for profile, total in (('end_turn.effect', 1), ('effect.respect', 0)):
            with self.subTest(profile=profile):
                self.r = fixture_registry()
                self.r.register_behavior('cause.source', lambda c, p=profile:
                    [TriggerRandomEndTurnEffects(1, request(activation=p), c.source_id, c.event)]
                    if c.event.amount == 7 else [])
                self.r.register_card(CardDefinition('cause.source', 'cause.source', CardType.MINION,
                    health=8, triggers=(TriggerSpec('armor_gained', 'cause.source'),)))
                self.script('cause', lambda c: [GainArmor(1, 7)])
                game = self.game(board=('cause.source', 'opponent'), hand=('cause',))
                self.play(game, 'cause')
                self.assertEqual(len(self.selection(game).candidates), 1)
                self.assertEqual(self.batch(game).total, total)
                self.check(game)

    def test_player_source_clock_does_not_tick_for_random_activation(self):
        self.script('pe.producer', lambda c: [TriggerRandomEndTurnEffects(1,
            request(carriers=('player_effect',)), c.source_id)])
        game = self.game(hand=('clock', 'pe.producer'))
        self.install(game, 'clock')
        self.play(game, 'pe.producer')
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 3)
        self.assertEqual((game.state.turn, game.state.active_player), (1, 1))
        self.assertFalse(any(e.kind in ('turn_ended', 'turn_started', 'player_effect_ticked')
            for e in game.events))
        self.check(game)

    def test_query_and_acceptance_share_handler_without_post_draw_checkpoint(self):
        self.minion('self.kill', lambda c: [Destroy(c.source_id), GainArmor(1, 1)])
        game = self.game(board=('self.kill', 'double'))
        self.play(game)
        self.assertEqual(self.selection(game).selected.source_id,
            self.batch(game).subjects[0].source_id)
        self.assertEqual(self.batch(game).total, 2)
        self.assertEqual(self.armor(game), 2)
        self.assertEqual(game.state.entities[self.selection(game).selected.source_id].zone, Zone.GRAVEYARD)
        self.check(game)

    def test_handler_queries_latest_state_after_previous_effect_and_reactions(self):
        self.script('latest', lambda c: [Silence(c.state.players[1].board[0]),
            TriggerRandomEndTurnEffects(1, request(), c.source_id)])
        game = self.game(board=('many', 'end'), hand=('latest',))
        self.play(game, 'latest')
        self.assertEqual([c.card_id for c in self.selection(game).candidates], ['end'])
        self.assertEqual(self.armor(game), 1)
        self.check(game)

    def test_extra_body_reads_new_state_while_selection_stays_frozen(self):
        game = self.game(board=('double', 'fresh'))
        self.play(game)
        self.assertEqual(self.armor(game), 3)
        self.assertEqual(len(self.selection(game).candidates), 1)
        self.check(game, fresh=True)

    def test_finite_guard_consumes_once_per_selected_root_not_per_extra(self):
        game = self.game(board=('double', 'finite'))
        self.play(game)
        ability = next(a for a in self.body(game, 1).abilities if a.kind == 'limited_trigger')
        self.assertEqual(ability.uses_remaining, 1)
        used = [e for e in game.events if e.kind == 'limited_trigger_used']
        self.assertEqual(len(used), 1)
        self.assertEqual(self.armor(game), 2)
        self.check(game, fresh=True)

    def test_nested_finite_roots_draw_and_consume_independently_at_choice(self):
        self.r.register_behavior('nested', lambda c: [TriggerRandomEndTurnEffects(1,
            request(mode='selected', entities=(c.source_id,)), c.source_id)]
            if c.end_turn.subject.ability.uses_remaining == 2 else self.r.behavior('waiting')(c))
        self.r.register_card(CardDefinition('nested', 'nested', CardType.MINION, health=8,
            limited_triggers=(LimitedTriggerSpec('turn_ended', 'nested', uses=2,
                end_turn=EndTurnSpec()),)))
        game = self.game(board=('nested',))
        self.play(game)
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(len(game.state.end_turn_batches), 2)
        self.assertEqual(len([e for e in game.events if e.kind == 'limited_trigger_used']), 2)
        self.assertEqual(game.state.end_turn_batches[1].activation.parent_id, 1)
        self.check(game)
        self.choose(game)
        self.assertTrue(all(b.completed for b in game.state.end_turn_batches))
        self.check(game)

    def test_active_deathrattle_times_create_distinct_draws_and_inner_repeat_plans(self):
        self.r.register_behavior('dr.producer', lambda c: [TriggerRandomEndTurnEffects(1,
            request(), c.source_id)])
        self.r.register_card(CardDefinition('dr.source', 'dr.source', CardType.MINION, health=8,
            deathrattle='dr.producer'))
        self.script('twice', lambda c: [TriggerDeathrattles(c.state.players[1].board[0], c.source_id, times=2)])
        game = self.game(board=('dr.source', 'double', 'end'), hand=('twice',))
        self.play(game, 'twice')
        batches = game.state.end_turn_batches
        self.assertEqual([b.total for b in batches], [2, 2])
        self.assertEqual(batches[0].activation.selection.rng_after,
            batches[1].activation.selection.rng_before)
        self.assertEqual(self.armor(game), 4)
        self.assertFalse(any(e.kind == 'died' for e in game.events))
        self.check(game)

    def test_consumer_randomness_can_advance_rng_after_the_selection_receipt(self):
        self.minion('random.body', lambda c: [RandomDamage((c.state.players[2].hero_id,), 1, c.source_id)])
        game = self.game(board=('random.body',))
        self.play(game)
        self.assertNotEqual(game._rng.getstate(), self.selection(game).rng_after)
        self.check(game)

    def test_gaussian_cache_round_trips_in_selection_frame_and_replay_origin(self):
        snapshot = self.game(board=('waiting',)).snapshot()
        snapshot['rng_state'][-1] = 0.25
        game = Game.from_snapshot(self.rehash(snapshot), self.r)
        self.play(game)
        self.assertEqual(self.selection(game).rng_before[-1], 0.25)
        from hs_sim.engine.continuations import FrameCodec
        FrameCodec(game.mechanics, game.registry).check_runtime(game._frame)
        self.check(game, fresh=True)
        self.choose(game)
        self.check(game, fresh=True)

    def test_last_extra_choice_preserves_complete_pool_and_original_plan(self):
        game = self.waiting(extra=True)
        self.assertEqual(self.batch(game).total, 2)
        self.assertEqual([r.completed for r in game.state.end_turn_history], [True, False])
        self.assertEqual(len(self.selection(game).candidates), 1)
        self.check(game, fresh=True)
        self.choose(game)
        self.assertEqual(self.armor(game), 2)
        self.check(game, fresh=True)

    def test_terminal_consumer_interrupts_extra_positions_without_natural_clock(self):
        self.minion('lethal', lambda c: [Damage(c.state.players[2].hero_id, 30)])
        game = self.game(board=('double', 'lethal'))
        self.play(game)
        self.assertTrue(self.batch(game).interrupted)
        self.assertEqual([r.execution_order for r in game.state.end_turn_history], [1, None])
        self.assertEqual((game.state.turn, game.state.active_player), (1, 1))
        self.check(game)

    def test_repeat_budget_error_rolls_back_the_random_draw(self):
        self.r.register_card(CardDefinition('huge', 'huge', CardType.MINION, health=8,
            end_turn_repeats=(EndTurnRepeatSpec(1000),)))
        game = self.game(board=('huge', 'end'), rules=Ruleset(max_resolution_steps=50))
        before = game.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            self.play(game)
        self.assertEqual(game.snapshot(), before)

    def test_extra_body_failure_rolls_back_receipt_history_events_and_rng(self):
        def callback(c):
            if c.end_turn.repeat_index:
                raise ValueError('synthetic producer extra failure')
            return [GainArmor(1, 1)]
        self.minion('failure', callback)
        game = self.game(board=('double', 'failure'))
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game)
        self.assertEqual(game.snapshot(), before)

    def test_player_observation_hides_pool_rng_request_and_full_proof(self):
        game = self.waiting(extra=True)
        for viewer in (1, 2):
            text = json.dumps((game.observe(viewer), game.player_events(viewer),
                game.for_player(viewer).legal_actions()))
            for key in ('selection', 'candidates', 'rng_before', 'rng_after',
                    'candidate_profile_id', 'activation_profile_id', 'end_turn_batches',
                    'end_turn_history', 'guard_event', 'end_turn_guard_id', 'resolution_frame'):
                self.assertNotIn('"' + key + '"', text)
        self.assertFalse(any(e.kind in ('random_choice', 'random_choice_skipped') for e in game.events))

    def test_empty_pool_receipt_survives_later_caller_choice(self):
        self.script('empty.then.wait', lambda c: [TriggerRandomEndTurnEffects(1, request(), c.source_id),
            *self.r.behavior('waiting')(c)])
        game = self.game(board=('plain',), hand=('empty.then.wait',))
        self.play(game, 'empty.then.wait')
        self.assertTrue(self.batch(game).completed)
        self.assertIsNone(self.selection(game).selected)
        self.check(game)
        self.choose(game)
        self.check(game)

    def test_selection_constructor_rejects_duplicate_carrier_and_out_of_pool_pick(self):
        game = self.game(board=('end', 'end'))
        candidates = self.pool(game)
        rng = game._rng.getstate()
        for rows, selected in (((candidates[0],) * 2, candidates[0]),
                ((candidates[0],), candidates[1]), (candidates, None)):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                EndTurnSelection(request(), rows, selected, rng, rng)

    def test_rehashed_missing_or_extra_selection_wire_fields_are_rejected(self):
        game = self.waiting()
        for field in ('selection', 'rng_before', 'unexpected'):
            snapshot = game.snapshot()
            activation = snapshot['state']['end_turn_batches'][0]['activation']
            if field == 'selection':
                del activation[field]
            elif field == 'rng_before':
                del activation['selection'][field]
            else:
                activation['selection'][field] = 1
            with self.subTest(field=field):
                self.reject(snapshot)

    def test_rehashed_frame_selection_missing_field_is_not_defaulted(self):
        snapshot = self.waiting().snapshot()
        value = self.named(snapshot['resolution_frame'], 'EndTurnSelection')[0]
        del value['fields']['rng_after']
        self.reject(snapshot)

    def test_rehashed_selection_unknown_profiles_are_rejected(self):
        game = self.waiting()
        for field in ('candidate_profile_id', 'activation_profile_id'):
            snapshot = game.snapshot()
            snapshot['state']['end_turn_batches'][0]['activation']['selection']['request'][field] = 'unknown'
            with self.subTest(field=field):
                self.reject(snapshot)

    def test_rehashed_selection_selected_none_or_outside_pool_is_rejected(self):
        game = self.waiting()
        for selected in (None, {'kind': 'minion', 'source_id': 9999, 'player_id': 1,
                'card_id': 'waiting', 'entered_order': 1, 'zone_epoch': 0, 'player_effect': None}):
            snapshot = game.snapshot()
            snapshot['state']['end_turn_batches'][0]['activation']['selection']['selected'] = selected
            with self.subTest(selected=selected):
                self.reject(snapshot)

    def test_rehashed_duplicate_or_reordered_pool_is_rejected(self):
        game = self.game(board=('waiting', 'waiting'))
        self.play(game)
        for duplicate in (False, True):
            snapshot = game.snapshot()
            pool = snapshot['state']['end_turn_batches'][0]['activation']['selection']['candidates']
            pool[:] = [pool[0], pool[0]] if duplicate else list(reversed(pool))
            with self.subTest(duplicate=duplicate):
                self.reject(snapshot)

    def test_rehashed_pool_carrier_owner_kind_card_epoch_and_order_are_rejected(self):
        game = self.waiting()
        for field, value in (('player_id', 2), ('kind', 'weapon'), ('card_id', 'plain'),
                ('zone_epoch', 999), ('entered_order', 999), ('source_id', True)):
            snapshot = game.snapshot()
            snapshot['state']['end_turn_batches'][0]['activation']['selection']['candidates'][0][field] = value
            with self.subTest(field=field):
                self.reject(snapshot)

    def test_rehashed_rng_before_or_after_cannot_claim_a_different_draw(self):
        game = self.waiting()
        for field in ('rng_before', 'rng_after'):
            snapshot = game.snapshot()
            selection = snapshot['state']['end_turn_batches'][0]['activation']['selection']
            selection[field] = list(random.Random(999).getstate())
            with self.subTest(field=field):
                self.reject(snapshot)

    def test_rehashed_rng_wire_rejects_bool_word_bad_index_and_integer_cache(self):
        game = self.waiting()
        for mode in ('bool', 'index', 'cache'):
            snapshot = game.snapshot()
            rng = snapshot['state']['end_turn_batches'][0]['activation']['selection']['rng_before']
            if mode == 'bool':
                rng[1][0] = True
            elif mode == 'index':
                rng[1][-1] = 625
            else:
                rng[2] = 1
            with self.subTest(mode=mode):
                self.reject(snapshot)

    def test_rehashed_resolved_activation_request_cannot_change_selected_carrier(self):
        snapshot = self.waiting().snapshot()
        activation = snapshot['state']['end_turn_batches'][0]['activation']
        activation['request']['selector']['entity_ids'] = []
        self.reject(snapshot)

    def test_rehashed_selection_null_cannot_disagree_with_original_finish_proof(self):
        snapshot = self.waiting().snapshot()
        snapshot['state']['end_turn_batches'][0]['activation']['selection'] = None
        self.reject(snapshot)

    def test_rehashed_last_extra_cannot_remove_finish_batch_proof(self):
        snapshot = self.waiting(extra=True).snapshot()
        queue = self.queue(snapshot)
        queue[:] = [w for w in queue if not str(w.get('type', '')).endswith('.FinishEndTurnBatch')]
        self.reject(snapshot)

    def test_rehashed_last_extra_cannot_shrink_plan_and_history_together(self):
        snapshot = self.waiting(extra=True).snapshot()
        snapshot['state']['end_turn_batches'][0]['plans'][0]['repetitions'] = 1
        snapshot['state']['end_turn_history'][:] = snapshot['state']['end_turn_history'][:1]
        self.reject(snapshot)

    def test_rehashed_player_carrier_requires_full_independent_instance_identity(self):
        self.script('pe.wait', lambda c: [TriggerRandomEndTurnEffects(1,
            request(carriers=('player_effect',)), c.source_id), *self.r.behavior('waiting')(c)])
        game = self.game(hand=('persistent', 'pe.wait'))
        self.install(game)
        self.play(game, 'pe.wait')
        for mode in ('missing', 'id', 'source'):
            snapshot = game.snapshot()
            candidate = snapshot['state']['end_turn_batches'][0]['activation']['selection']['candidates'][0]
            if mode == 'missing':
                candidate['player_effect'] = None
            elif mode == 'id':
                candidate['player_effect']['id'] = 99999
            else:
                candidate['source_id'] = game.state.players[1].hero_id
            with self.subTest(mode=mode):
                self.reject(snapshot)

    def test_old_schema_98_cannot_omit_selection_witness(self):
        snapshot = self.waiting().snapshot()
        snapshot['schema_version'] = 98
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(snapshot, self.r)

    def real_game(self, board=('BOT_107',), enemy=(), hand=('fixture.break',),
                  weapon='CATA_472'):
        self.r = build_registry()
        self.r.register_behavior('fixture.break', lambda c: [Destroy(c.state.players[1].weapon_id,
            c.source_id)])
        self.r.register_card(CardDefinition('fixture.break', 'fixture.break', CardType.SPELL,
            on_play='fixture.break'))
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_04', board=board, hand=hand, weapon_card_id=weapon,
                deck=('CS2_182',) * 20, mana=10, max_mana=10),
            PlayerSetup('HERO_08', board=enemy, deck=('CS2_182',) * 20,
                mana=10, max_mana=10)), seed=147), self.r)

    def test_real_maul_metadata_and_independent_full_raw_pin(self):
        self.r = build_registry()
        card = self.r.card('CATA_472')
        self.assertEqual((card.kind, card.cost, card.attack, card.durability), (CardType.WEAPON, 2, 2, 2))
        self.assertEqual((card.metadata.classes, card.metadata.rarity, card.metadata.collectible),
            ((CardClass.PALADIN,), Rarity.COMMON, True))
        self.assertEqual(EXPECTED_CARD_HASHES['CATA_472'], MAUL_HASH)
        raw = next(c['data'] for c in load_baseline().support['cards'] if c['id'] == 'CATA_472')
        self.assertEqual(canonical_digest(raw), MAUL_HASH)
        self.assertEqual(raw['dbf_id'], 123106)
        self.assertIn('CN', CARD_LIMITATIONS['CATA_472'])

    def test_real_maul_profile_selects_only_friendly_active_minions(self):
        game = self.real_game(board=('BOT_107', 'ICC_901'), enemy=('BOT_107',))
        self.play(game, 'fixture.break')
        selection = self.selection(game)
        self.assertEqual(selection.request.candidate_profile_id, 'CATA_472.end_turn_candidates')
        self.assertEqual(selection.request.selector.carrier_kinds, ('minion',))
        self.assertEqual([(c.card_id, c.player_id) for c in selection.candidates], [('BOT_107', 1)])
        self.assertEqual(self.batch(game).total, 2)
        self.check(game)

    def test_real_maul_empty_board_break_preserves_rng_and_weapon_issuer(self):
        game = self.real_game(board=())
        weapon = game.state.players[1].weapon_id
        before = game._rng.getstate()
        self.play(game, 'fixture.break')
        self.assertEqual(self.selection(game).candidates, ())
        self.assertEqual(game._rng.getstate(), before)
        self.assertEqual(self.batch(game).activation.issuer_id, weapon)
        self.assertEqual(game.state.entities[weapon].zone, Zone.GRAVEYARD)
        self.check(game)

    def test_real_maul_bot_payload_has_one_damage_batch_without_natural_events(self):
        game = self.real_game(enemy=('CS2_182',))
        self.play(game, 'fixture.break')
        self.assertEqual(len(self.batch(game).subjects), 1)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].damage, 1)
        self.assertEqual(self.body(game, owner=2).damage, 1)
        self.assertFalse(any(e.kind in ('turn_ended', 'turn_started') for e in game.events))
        self.check(game)

    def test_real_maul_icc_and_cata_repeats_use_max_not_product_and_do_not_tick(self):
        game = self.real_game(board=('BOT_107', 'ICC_901'), hand=('CATA_480', 'fixture.break'))
        self.play(game, 'CATA_480')
        self.play(game, 'fixture.break')
        self.assertEqual(self.batch(game).total, 2)
        self.assertEqual(len(self.batch(game).plans[0].contributors), 2)
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 3)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].damage, 2)
        self.check(game)

    def test_real_maul_on_opponent_turn_uses_weapon_owner_not_active_player(self):
        self.r = build_registry()
        self.r.register_behavior('enemy.break', lambda c: [Destroy(c.state.players[1].weapon_id, c.source_id)])
        self.r.register_card(CardDefinition('enemy.break', 'enemy.break', CardType.SPELL, on_play='enemy.break'))
        # Build a new scenario after registering the explicit enemy action.
        game = Game.from_scenario(Scenario((
            PlayerSetup('HERO_04', board=('BOT_107',), weapon_card_id='CATA_472', deck=('CS2_182',) * 10),
            PlayerSetup('HERO_08', hand=('enemy.break',), deck=('CS2_182',) * 10,
                mana=10, max_mana=10)), seed=147), self.r)
        game.apply(EndTurn(1))
        before = game.state.entities[game.state.players[2].hero_id].damage
        self.play(game, 'enemy.break')
        self.assertEqual(self.batch(game).activation.issuer_player_id, 1)
        self.assertEqual([c.player_id for c in self.selection(game).candidates], [1])
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].damage, before + 1)
        self.check(game)

    def test_rehashed_random_mode_missing_or_boolean_is_rejected(self):
        game = self.waiting()
        for missing in (False, True):
            snapshot = game.snapshot()
            activation = snapshot['state']['end_turn_batches'][0]['activation']
            if missing:
                del activation['producer_mode']
            else:
                activation['producer_mode'] = True
            with self.subTest(missing=missing):
                self.reject(snapshot)

    def test_rehashed_all_selection_copies_null_cannot_preserve_random_mode(self):
        snapshot = self.waiting(extra=True).snapshot()
        def clear(value):
            if isinstance(value, dict):
                if value.get('producer_mode') == 'random_one':
                    value['selection'] = None
                if str(value.get('type', '')).endswith('.EndTurnActivation'):
                    if value['fields']['producer_mode'] == 'random_one':
                        value['fields']['selection'] = None
                for child in value.values():
                    clear(child)
            elif isinstance(value, list):
                for child in value:
                    clear(child)
        clear(snapshot)
        self.reject(snapshot)

    def test_random_phase_uses_real_start_cause_without_creating_another_boundary(self):
        self.r.register_behavior('phase.producer', lambda c: [TriggerRandomEndTurnEffects(1,
            request(activation='end_turn.phase'), c.source_id, c.event)]
            if c.event.player_id == 1 else [])
        self.r.register_card(CardDefinition('phase.producer', 'phase.producer', CardType.MINION,
            health=8, triggers=(TriggerSpec('turn_started', 'phase.producer'),)))
        game = self.game(board=('phase.producer', 'end'), hand=())
        game.apply(EndTurn(1))
        game.apply(EndTurn(2))
        self.assertEqual(self.batch(game).activation.kind, 'phase')
        self.assertEqual(self.batch(game).event.kind, 'turn_started')
        self.assertEqual(self.selection(game).request.activation_profile_id, 'end_turn.phase')
        self.assertEqual(len([e for e in game.events if e.kind == 'turn_started']), 2)
        self.assertEqual(len([e for e in game.events if e.kind == 'turn_ended']), 2)
        self.check(game)

    def test_tail_ordinary_random_root_settles_before_outer_natural_proof_and_clock(self):
        self.r.register_behavior('tail', lambda c: [TriggerRandomEndTurnEffects(1,
            request(mode='selected', entities=(c.state.players[1].board[1],)), c.source_id),
            *self.r.behavior('waiting')(c)] if c.event.player_id == 1 else [])
        self.r.register_card(CardDefinition('tail', 'tail', CardType.MINION, health=8,
            triggers=(TriggerSpec('turn_ended', 'tail'),)))
        game = self.game(board=('double', 'end', 'tail'), hand=())
        game.apply(EndTurn(1))
        self.assertIsNotNone(game.state.pending_choice)
        natural, active = game.state.end_turn_batches
        self.assertFalse(natural.completed)
        self.assertTrue(active.completed)
        self.assertEqual((active.activation.parent_id, active.activation.parent_batch_id), (None, natural.id))
        self.assertEqual((game.state.turn, game.state.active_player), (1, 1))
        self.check(game)
        snapshot = game.snapshot()
        self.queue(snapshot)[:] = [w for w in self.queue(snapshot)
            if not str(w.get('type', '')).endswith('.FinishEndTurnBatch')]
        self.reject(snapshot)
        self.choose(game)
        self.assertEqual((game.state.turn, game.state.active_player), (2, 2))
        self.assertEqual(len([e for e in game.events if e.kind == 'turn_started']), 1)
        self.check(game)

    def test_selected_player_instance_removed_by_first_body_keeps_extra_and_proof(self):
        self.r.register_behavior('remove.wait', lambda c: [RemovePlayerEffect(1, c.player_effect.id),
            *self.r.behavior('waiting')(c)])
        self.r.register_player_effect(PlayerEffectSpec('remove.wait', 'persistent',
            triggers=(TriggerSpec('turn_ended', 'remove.wait', EndTurnSpec()),)))
        self.script('install.wait', lambda c: [AddPlayerEffect(1, 'remove.wait', c.source_id)])
        self.script('pe.random', lambda c: [TriggerRandomEndTurnEffects(1,
            request(carriers=('player_effect',)), c.source_id)])
        game = self.game(board=('double',), hand=('install.wait', 'pe.random'))
        self.play(game, 'install.wait')
        self.play(game, 'pe.random')
        self.assertEqual(game.state.players[1].player_effects, [])
        self.assertEqual(self.batch(game).total, 2)
        self.check(game)
        self.choose(game)
        self.assertIsNotNone(game.state.pending_choice)
        self.check(game)
        self.choose(game)
        self.assertEqual(self.armor(game), 2)
        self.check(game)

    def test_last_extra_coordinated_pool_shrink_with_valid_one_draw_still_fails_acceptance(self):
        game = self.game(board=('double', 'waiting', 'waiting'))
        self.play(game)
        self.choose(game)
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(len(self.selection(game).candidates), 2)
        self.check(game, fresh=True)
        snapshot = game.snapshot()
        selection = self.selection(game)
        probe = random.Random(); probe.setstate(selection.rng_before)
        self.assertEqual(probe.choice((selection.selected,)), selection.selected)
        shrunk = EndTurnSelection(selection.request, (selection.selected,), selection.selected,
            selection.rng_before, probe.getstate())
        validate_selection(game.state, self.r,
            replace(self.batch(game).activation, selection=shrunk))
        after = json.loads(json.dumps(probe.getstate()))
        def shrink(value):
            if isinstance(value, dict):
                if ({'request', 'candidates', 'selected', 'rng_before', 'rng_after'} <= value.keys()
                        and type(value['rng_before']) is list):
                    value['candidates'] = [deepcopy(value['selected'])]
                    value['rng_after'] = deepcopy(after)
                if str(value.get('type', '')).endswith('.EndTurnSelection'):
                    fields = value['fields']
                    fields['candidates'] = {'tuple': [deepcopy(fields['selected'])]}
                    fields['rng_after'] = {'end_turn_rng': deepcopy(after)}
                for child in value.values():
                    shrink(child)
            elif isinstance(value, list):
                for child in value:
                    shrink(child)
        shrink(snapshot)
        self.assertIn('complete candidate window', self.reject(snapshot))


if __name__ == '__main__':
    unittest.main()
