"""Generation eligibility must not depend on implementation coverage or secrets."""
from dataclasses import replace
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, Keyword,
    PlayCard, PlayerSetup, Rarity, Registry, ResolutionError, ResolutionLimitExceeded,
    Ruleset, Scenario, SelectChoice, SnapshotError, SpellSchool, TriggerSpec, UnsupportedDefinitionError)
from hs_sim.engine.construction import MatchSetup
from hs_sim.engine.effects import AddToHand, ChoiceOption, GainArmor, ReplaceHero, RequestChoice
from hs_sim.engine.pools import (DiscoverFromPool, GenerateFromPool, GenerationContext, PoolCard,
    PoolDefinition, PoolMember, PoolQuery, resolve_candidates, sample_candidates)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import canonical_hash


CONTEXT = GenerationContext('test-target', 'experimental')


def metadata(classes=(CardClass.NEUTRAL,), *, collectible=True, rarity=Rarity.COMMON, tribes=()):
    return CardMetadata(collectible, classes, rarity, tribes=tribes)


class GenerationPoolTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry('generation-tests-v1')
        for id, cls in (('hero', CardClass.MAGE), ('warrior', CardClass.WARRIOR)):
            self.registry.register_card(CardDefinition(id, id, CardType.HERO, health=30, metadata=metadata((cls,))))
        self.card('a', cost=3, tribes=('beast',), keywords=(Keyword.TAUNT,))
        self.card('b', cost=3, classes=(CardClass.MAGE,), kind=CardType.SPELL, school=SpellSchool.FIRE)
        self.card('c', cost=3, classes=(CardClass.WARRIOR,))
        self.card('d', cost=2, classes=(CardClass.MAGE, CardClass.ROGUE), rarity=Rarity.RARE)
        self.card('token', cost=3, collectible=False)

    def card(self, id, *, cost=1, classes=(CardClass.NEUTRAL,), kind=CardType.MINION,
             collectible=True, rarity=Rarity.COMMON, tribes=(), school=None, keywords=(),
             identity=None, executable=True):
        meta = metadata(classes, collectible=collectible, rarity=rarity, tribes=tribes)
        definition = CardDefinition(id, id, kind, cost=cost, health=2 if kind == CardType.MINION else 0,
                                    metadata=meta, spell_school=school, keywords=keywords)
        if executable:
            self.registry.register_card(definition)
        self.registry.register_pool_card(PoolCard.from_definition(definition, identity=identity))

    def pool(self, cards=('a', 'b', 'c', 'd', 'token'), *, context=CONTEXT, exclusions=(), version='v1', weights=None):
        self.registry.register_pool(PoolDefinition('pool', version, context.target_id, context.mode,
            tuple(PoolMember(i, (weights or {}).get(i, 1)) for i in cards), exclusions,
            complete=context.mode != 'experimental'))
        self.registry.validate()

    def candidates(self, query=PoolQuery(), **kwargs):
        return tuple(m.card_id for m in resolve_candidates(self.registry, CONTEXT, 'pool', query, **kwargs))

    def script(self, callback):
        self.registry.register_behavior('script', callback)
        self.registry.register_card(CardDefinition('script', 'script', CardType.SPELL, on_play='script'))

    def game(self, *, context=CONTEXT, seed=19, hand=('script',), rules=None, mechanics=None, board=()):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board, max_mana=10, mana=10),
            PlayerSetup('warrior')), seed=seed, generation_context=context), self.registry, rules, mechanics)

    def cast(self, game):
        return game.apply(PlayCard(1, game.state.players[1].hand[0]))

    def choose(self, game, index=0):
        choice = game.state.pending_choice
        return game.apply(SelectChoice(choice.player_id, choice.id, (choice.options[index].id,)))

    def assert_replay(self, game):
        self.assertEqual(replay(build_replay(game), self.registry).snapshot(), game.snapshot())

    def test_definition_validation_rejects_ambiguous_or_mutable_inputs(self):
        invalid = [lambda: GenerationContext('', 'wild'), lambda: GenerationContext('t', 'arena'),
            lambda: PoolMember('a', True), lambda: PoolMember('a', 0),
            lambda: PoolDefinition('p', 'v', 't', 'standard', ()),
            lambda: PoolDefinition('p', 'v', 't', 'experimental', [PoolMember('a')]),
            lambda: PoolDefinition('p', 'v', 't', 'experimental', (PoolMember('a'), PoolMember('a'))),
            lambda: PoolDefinition('p', 'v', 't', 'experimental', (), ('missing',)),
            lambda: PoolQuery(kinds=('spell',)), lambda: PoolQuery(min_cost=True),
            lambda: PoolQuery(min_cost=4, max_cost=3), lambda: PoolQuery(collectible=1),
            lambda: PoolQuery(class_mode='specified'), lambda: PoolQuery(classes=(CardClass.MAGE,)),
            lambda: PoolQuery(include_neutral=1), lambda: PoolQuery(exclude_source=1),
            lambda: PoolQuery(tribes_any=['beast']), lambda: GenerateFromPool(True, 'pool'),
            lambda: GenerateFromPool(1, 'pool', destination='graveyard'), lambda: DiscoverFromPool(1, 'pool', count=0)]
        for constructor in invalid:
            with self.subTest(constructor=constructor), self.assertRaises(ValueError):
                constructor()

    def test_missing_inventory_is_rejected_at_freeze(self):
        self.registry.register_pool(PoolDefinition('pool', 'v1', CONTEXT.target_id, CONTEXT.mode, (PoolMember('missing'),)))
        with self.assertRaisesRegex(UnsupportedDefinitionError, 'metadata'):
            self.registry.freeze()

    def test_known_definition_cannot_disagree_with_inventory(self):
        self.registry.register_pool_card(PoolCard('hero', CardType.MINION, 0, metadata()))
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.registry.freeze()

    def test_duplicate_registration_and_frozen_maps_are_rejected(self):
        self.pool()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.pool()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.registry.register_pool_card(self.registry.pool_card('a'))
        self.registry.freeze()
        with self.assertRaisesRegex(ValueError, 'frozen'):
            self.registry.register_pool_card(self.registry.pool_card('a'))
        with self.assertRaises(TypeError):
            self.registry.pools[('x', 'x', 'x')] = None
        with self.assertRaises(TypeError):
            self.registry.pool_cards['x'] = None

    def test_target_and_mode_have_no_fallback(self):
        self.pool(('a',))
        self.pool(('b',), context=GenerationContext('test-target', 'standard'))
        self.pool(('c',), context=GenerationContext('test-target', 'wild'))
        for mode, expected in (('experimental', 'a'), ('standard', 'b'), ('wild', 'c')):
            result = resolve_candidates(self.registry, GenerationContext('test-target', mode), 'pool', PoolQuery())
            self.assertEqual([m.card_id for m in result], [expected])
        with self.assertRaises(UnsupportedDefinitionError):
            resolve_candidates(self.registry, GenerationContext('other-target', 'wild'), 'pool', PoolQuery())

    def test_printed_cost_collectibility_kind_and_current_class_filter(self):
        self.pool()
        query = PoolQuery(min_cost=3, max_cost=3, collectible=True, class_mode='current')
        self.assertEqual(self.candidates(query, current_class=CardClass.MAGE), ('a', 'b'))
        self.assertEqual(self.candidates(replace(query, kinds=(CardType.SPELL,)), current_class=CardClass.MAGE), ('b',))
        self.assertEqual(self.candidates(replace(query, include_neutral=False), current_class=CardClass.MAGE), ('b',))

    def test_dual_classes_other_class_and_explicit_classes(self):
        self.pool()
        self.assertEqual(self.candidates(PoolQuery(class_mode='specified', classes=(CardClass.ROGUE,), include_neutral=False)), ('d',))
        self.assertEqual(self.candidates(PoolQuery(class_mode='current', include_neutral=False), current_class=CardClass.MAGE), ('b', 'd'))
        self.assertEqual(self.candidates(PoolQuery(class_mode='other', include_neutral=False), current_class=CardClass.MAGE), ('c',))
        for cls in (None, CardClass.NEUTRAL, 'mage'):
            with self.assertRaisesRegex(ValueError, 'current playable'):
                self.candidates(PoolQuery(class_mode='current'), current_class=cls)

    def test_school_tribe_keyword_and_rarity_filters(self):
        self.pool()
        self.assertEqual(self.candidates(PoolQuery(spell_schools=(SpellSchool.FIRE,))), ('b',))
        self.assertEqual(self.candidates(PoolQuery(tribes_any=('beast',), keywords_all=(Keyword.TAUNT,))), ('a',))
        self.assertEqual(self.candidates(PoolQuery(rarities=(Rarity.RARE,))), ('d',))

    def test_unknown_metadata_is_not_treated_as_negative_match(self):
        self.card('unknown', tribes=None, rarity=None)
        self.pool(('unknown',))
        for query in (PoolQuery(tribes_any=('beast',)), PoolQuery(rarities=(Rarity.RARE,))):
            with self.assertRaisesRegex(ValueError, 'Unknown candidate'):
                self.candidates(query)

    def test_eligible_unimplemented_candidate_causes_explicit_failure(self):
        self.card('missing', cost=3, executable=False)
        self.pool(('a', 'missing'))  # Inventory may precede execution support.
        with self.assertRaisesRegex(UnsupportedDefinitionError, 'missing'):
            self.candidates()
        self.assertEqual(self.candidates(PoolQuery(keywords_all=(Keyword.TAUNT,))), ('a',))

    def test_only_declared_exclusions_may_remove_unknown_implementations(self):
        self.card('missing', cost=3, executable=False)
        self.pool(('a', 'missing'), exclusions=('missing',))
        self.assertEqual(self.candidates(), ('a',))
        self.assertEqual(self.candidates(PoolQuery(exclude_card_ids=('a',))), ())

    def test_generation_aliases_are_deduplicated_without_inflating_weight(self):
        self.card('alias1', identity='same')
        self.card('alias2', identity='same')
        self.pool(('alias2', 'alias1', 'b'))
        self.assertEqual(self.candidates(), ('alias1', 'b'))
        self.assertEqual(self.candidates(PoolQuery(exclude_source=True), source_card_id='alias2'), ('b',))
        self.assertEqual(self.candidates(PoolQuery(exclude_card_ids=('alias2',))), ('b',))

    def test_unsupported_alias_cannot_hide_behind_an_implemented_printing(self):
        self.card('alias1', identity='same')
        self.card('alias2', identity='same', executable=False)
        self.pool(('alias1', 'alias2'))
        with self.assertRaisesRegex(UnsupportedDefinitionError, 'alias2'):
            self.candidates()

    def test_conflicting_aliases_or_weights_are_rejected(self):
        for conflict in ('cost', 'weight'):
            with self.subTest(conflict=conflict):
                self.setUp()
                self.card('alias1', identity='same')
                self.card('alias2', identity='same', cost=2 if conflict == 'cost' else 1)
                with self.assertRaisesRegex(ValueError, 'Conflicting generation aliases'):
                    self.pool(('alias1', 'alias2'), weights={'alias2': 2} if conflict == 'weight' else None)

    def test_integer_weight_intervals_and_without_replacement(self):
        class Tickets:
            def __init__(self, ticket): self.ticket = ticket
            def randrange(self, total):
                assert 0 <= self.ticket < total
                return self.ticket
        members = (PoolMember('a', 1), PoolMember('b', 3))
        self.assertEqual([sample_candidates(Tickets(i), members, 1, replacement=True)[0] for i in range(4)], ['a', 'b', 'b', 'b'])
        self.assertEqual(set(sample_candidates(random.Random(3), members, 9, replacement=False)), {'a', 'b'})

    def test_canonical_order_and_reproducible_sampling(self):
        self.pool(('d', 'c', 'b', 'a'))
        members = resolve_candidates(self.registry, CONTEXT, 'pool', PoolQuery())
        self.assertEqual([m.card_id for m in members], ['a', 'b', 'c', 'd'])
        self.assertEqual(sample_candidates(random.Random(8), members, 3, replacement=False),
                         sample_candidates(random.Random(8), members, 3, replacement=False))

    def test_discover_freezes_options_and_rng_across_restore_clone_replay(self):
        self.pool()
        self.script(lambda c: [DiscoverFromPool(1, 'pool', source_id=c.source_id)])
        g = self.game()
        self.cast(g)
        self.assertEqual(len({o.card_id for o in g.state.pending_choice.options}), 3)
        snapshot = g.snapshot()
        branches = [g.clone(), Game.from_snapshot(json.loads(json.dumps(snapshot)), self.registry)]
        self.assert_replay(g)
        for branch in branches:
            self.assertEqual(branch.snapshot(), snapshot)
            self.choose(branch)
            self.assertEqual(branch.snapshot()['rng_state'], snapshot['rng_state'])
        self.choose(g)
        self.assertEqual(g.snapshot(), branches[0].snapshot())
        self.assertEqual(g.snapshot(), branches[1].snapshot())
        self.assert_replay(g)

    def test_private_options_and_generated_hand_stay_out_of_opponent_dto(self):
        self.pool(('a', 'b', 'c'))
        self.script(lambda c: [DiscoverFromPool(1, 'pool')])
        g = self.game(); self.cast(g)
        self.assertEqual(g.observe(2)['pending_choice'], {'player_id': 1})
        port = g.for_player(1); legal = port.legal_actions()
        selected = legal['observation']['pending_choice']['options'][0]['card_id']
        result = port.submit({'revision': legal['revision'], 'action': legal['actions'][0]})
        self.assertTrue(result['accepted'])
        self.assertEqual(g.observe(1)['players'][0]['hand'][0]['card_id'], selected)
        self.assertIsNone(g.observe(2)['players'][0]['hand'][0]['card_id'])
        for event in g.player_events(2):
            self.assertNotIn('options', event)

    def test_empty_and_short_pools_do_not_require_three_candidates(self):
        for members in ((), ('a',), ('a', 'b')):
            with self.subTest(members=members):
                self.setUp(); self.pool(members)
                self.script(lambda c: [DiscoverFromPool(1, 'pool'), GainArmor(1, 2)])
                g = self.game(); before = g.snapshot()['rng_state']; self.cast(g)
                if members:
                    self.assertEqual(len(g.state.pending_choice.options), len(members))
                    self.choose(g)
                else:
                    self.assertIsNone(g.state.pending_choice)
                    self.assertEqual(g.snapshot()['rng_state'], before)
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2)

    def test_all_candidates_validated_before_rng_and_failure_rolls_back(self):
        self.card('missing', executable=False); self.pool(('a', 'missing'))
        self.script(lambda c: [GenerateFromPool(1, 'pool', count=1)])
        g = self.game(); before = g.snapshot()
        with patch('hs_sim.engine.pools.sample_candidates') as sampler:
            with self.assertRaisesRegex(ResolutionError, 'missing'):
                self.cast(g)
            sampler.assert_not_called()
        self.assertEqual(g.snapshot(), before); self.assertEqual(g.history, [])

    def test_unconfigured_or_wrong_context_fails_atomically(self):
        self.pool(); self.script(lambda c: [DiscoverFromPool(1, 'pool')])
        for context in (None, GenerationContext('test-target', 'wild'), GenerationContext('wrong', 'experimental')):
            with self.subTest(context=context):
                g = self.game(context=context); before = g.snapshot()
                with self.assertRaises(ResolutionError): self.cast(g)
                self.assertEqual(g.snapshot(), before)

    def test_generation_class_uses_replaced_current_hero(self):
        self.pool(('b', 'c'))
        self.script(lambda c: [ReplaceHero(1, 'warrior'), DiscoverFromPool(1, 'pool',
            PoolQuery(class_mode='current', include_neutral=False))])
        g = self.game(); self.cast(g)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options], ['c'])
        self.assert_replay(g)

    def test_generated_cards_have_new_independent_entities_and_can_repeat(self):
        self.pool(('a',)); self.script(lambda c: [GenerateFromPool(1, 'pool', count=2)])
        g = self.game(); self.cast(g)
        hand = g.state.players[1].hand
        self.assertEqual(len(set(hand)), 2)
        self.assertEqual([g.state.entities[i].card_id for i in hand], ['a', 'a'])
        self.assert_replay(g)

    def test_without_replacement_generation_stops_at_unique_population(self):
        self.pool(('a', 'b')); self.script(lambda c: [GenerateFromPool(1, 'pool', count=9, replacement=False)])
        g = self.game(); self.cast(g)
        self.assertEqual({g.state.entities[i].card_id for i in g.state.players[1].hand}, {'a', 'b'})

    def test_generation_to_board_uses_summon_and_full_board_contract(self):
        self.pool(('a',)); self.script(lambda c: [GenerateFromPool(1, 'pool', count=2, destination='board')])
        g = self.game(board=('c',) * 6); self.cast(g)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual(sum(e.kind == 'summon_failed' for e in g.events), 1)
        self.assert_replay(g)

    def test_incompatible_destination_checks_even_unsampled_candidates(self):
        self.pool(('a', 'b')); self.script(lambda c: [GenerateFromPool(1, 'pool', destination='board')])
        g = self.game(); before = g.snapshot()
        with patch('hs_sim.engine.pools.sample_candidates') as sampler:
            with self.assertRaisesRegex(ResolutionError, 'destination'): self.cast(g)
            sampler.assert_not_called()
        self.assertEqual(g.snapshot(), before)

    def test_discovered_card_burns_at_full_hand_using_existing_visibility(self):
        self.pool(('a',)); self.script(lambda c: [AddToHand(1, 'b'), DiscoverFromPool(1, 'pool')])
        g = self.game(hand=('script',) + ('b',) * 9); self.cast(g); self.choose(g)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertTrue(any(e.kind == 'card_burned' for e in g.events))
        self.assertTrue(any(e['kind'] == 'card_burned' for e in g.player_events(2)))

    def test_followup_pool_query_in_suspended_continuation_roundtrips(self):
        self.pool()
        self.script(lambda c: [RequestChoice(1, (ChoiceOption('go', 'Go'),)),
            DiscoverFromPool(1, 'pool', PoolQuery(class_mode='current', min_cost=3)),
            GenerateFromPool(2, 'pool', PoolQuery(tribes_any=('beast',)))])
        g = self.game(); self.cast(g)
        restored = Game.from_snapshot(json.loads(json.dumps(g.snapshot())), self.registry)
        for branch in (g, restored): self.choose(branch); self.choose(branch)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].hand], ['a'])
        self.assert_replay(g)

    def test_selected_branch_failure_keeps_committed_options_and_rng(self):
        self.pool(); self.script(lambda c: [DiscoverFromPool(1, 'pool')])
        from hs_sim.engine.discovery_delivery import MaterializeDiscoveredCard
        def fail(r, effect): raise ValueError('simulated add failure')
        mechanics = default_mechanics('generation-failing-v1'); mechanics.replace(MaterializeDiscoveredCard, fail)
        g = self.game(mechanics=mechanics); self.cast(g); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'simulated add failure'): self.choose(g)
        self.assertEqual(g.snapshot(), before)

    def test_oversized_choice_and_generation_are_bounded(self):
        for effect in (DiscoverFromPool(1, 'pool', count=33), GenerateFromPool(1, 'pool', count=1001)):
            with self.subTest(effect=effect):
                self.setUp(); self.pool(); self.script(lambda c: [effect])
                g = self.game(); before = g.snapshot()
                with self.assertRaises(ResolutionLimitExceeded): self.cast(g)
                self.assertEqual(g.snapshot(), before)

    def test_inventory_size_is_not_the_choice_option_limit(self):
        for n in range(45): self.card(f'large-{n}')
        self.pool(tuple(f'large-{n}' for n in range(45)))
        self.script(lambda c: [DiscoverFromPool(1, 'pool')])
        g = self.game(); self.cast(g)
        self.assertEqual(len(g.state.pending_choice.options), 3)
        self.assert_replay(g)

    def test_pool_version_membership_weight_and_metadata_change_fingerprint(self):
        self.pool(('a',))
        original = self.registry.fingerprint()
        for variation in ('version', 'members', 'weight', 'metadata'):
            with self.subTest(variation=variation):
                self.setUp()
                if variation == 'metadata': self.card('new-inventory-only', executable=False)
                self.pool(('a', 'b') if variation == 'members' else ('a',),
                          version='v2' if variation == 'version' else 'v1',
                          weights={'a': 2} if variation == 'weight' else None)
                self.assertNotEqual(self.registry.fingerprint(), original)

    def test_pool_change_rejects_pending_snapshot_restore(self):
        self.pool(('a',)); self.script(lambda c: [DiscoverFromPool(1, 'pool')])
        g = self.game(); self.cast(g); snapshot = g.snapshot()
        self.setUp(); self.pool(('b',)); self.script(lambda c: [DiscoverFromPool(1, 'pool')])
        with self.assertRaisesRegex(SnapshotError, 'fingerprint'): Game.from_snapshot(snapshot, self.registry)

    def test_scenario_context_roundtrip_strict_fields_and_old_schema_rejection(self):
        self.pool(); self.script(lambda c: [])
        scenario = Scenario((PlayerSetup('hero'), PlayerSetup('warrior')), generation_context=CONTEXT)
        self.assertEqual(Scenario.from_dict(json.loads(json.dumps(scenario.to_dict()))), scenario)
        row = scenario.to_dict(); row['players'] = list(row['players']); row['generation_context']['extra'] = 1
        with self.assertRaises(ValueError): Scenario.from_dict(row)
        g = self.game(); snapshot = g.snapshot(); snapshot['schema_version'] = 12
        with self.assertRaisesRegex(SnapshotError, 'schema version'): Game.from_snapshot(snapshot, self.registry)

    def test_constructed_generation_context_is_bound_to_legality_target_and_mode(self):
        from hs_sim.engine.representative import build_registry
        root = Path(__file__).resolve().parents[1]
        setup = MatchSetup.from_dict(json.loads((root / 'examples/matches/constructed.json').read_text('utf-8')))
        r = build_registry(); g = Game.from_decks(setup, r)
        snapshot = g.snapshot()
        self.assertEqual(snapshot['generation_context'], {'target_id': setup.policy.target_id, 'mode': setup.policy.mode,
            'starting_decks': [list(d.cards) for d in setup.decks]})
        snapshot['generation_context']['mode'] = 'wild'
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaisesRegex(SnapshotError, 'Generation context differs'): Game.from_snapshot(snapshot, r)

    def test_real_scarab_uses_explicit_sample_inventory_and_known_class(self):
        from hs_sim.engine.representative import (build_registry, GENERATION_SAMPLE_IDS,
            HERALD_POOL_IDS, DEATHWING_POOL_IDS, ATTACK_COST_POOL_IDS, REWIND_SAMPLE_IDS, REWIND_POOL_ID, CARD_LIMITATIONS,
            EXCAVATE_SHARED_SAMPLE_IDS, EXCAVATE_CLASS_REWARDS, EXCAVATE_TITAN_SAMPLE_IDS, EXCAVATE_EIGHT_SAMPLE_IDS, EXCAVATE_TRANSFORM_SAMPLE_IDS,
            BRONZE_SAMPLE_IDS, BRONZE_POOL_ID, WIND_SAMPLE_IDS, PORTAL_SAMPLE_IDS, MOON_SAMPLE_IDS, COMBO_POOL_ID)
        r = build_registry()
        combo_inventory = json.loads((Path(__file__).resolve().parents[1] /
            'data/support/combo-source-inventory.json').read_text(encoding='utf-8'))
        combo_members = set(combo_inventory['experimental_pool']['members'])
        from hs_sim.engine.card_spell_sources import POOL_ID as CARD_SPELL_POOL_ID
        card_spell_inventory = json.loads((Path(__file__).resolve().parents[1] /
            'data/support/card-spell-source-inventory.json').read_text(encoding='utf-8'))
        card_spell_members = set(card_spell_inventory['experimental_pool']['members'])
        from hs_sim.engine.dark_gift_cards import MINION_POOL_ID as DARK_GIFT_MINION_POOL_ID
        dark_gift_members = {member.card_id for member in r.pool(DARK_GIFT_MINION_POOL_ID,
            GenerationContext('local-2026-09-23', 'experimental')).members}
        g = Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=('LOE_029',), max_mana=10, mana=10),
            PlayerSetup('HERO_01')), generation_context=GenerationContext('local-2026-09-23', 'experimental')), r)
        self.cast(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {'EX1_019', 'CS2_117', 'CS2_122'})
        self.assertEqual(set(r.pool_cards), set(GENERATION_SAMPLE_IDS) | set(HERALD_POOL_IDS) |
                         set(DEATHWING_POOL_IDS) | set(ATTACK_COST_POOL_IDS) | set(REWIND_SAMPLE_IDS) |
                         set(EXCAVATE_SHARED_SAMPLE_IDS) | set(EXCAVATE_CLASS_REWARDS.values()) |
                         set(EXCAVATE_TITAN_SAMPLE_IDS) | set(EXCAVATE_EIGHT_SAMPLE_IDS) | set(EXCAVATE_TRANSFORM_SAMPLE_IDS) | set(BRONZE_SAMPLE_IDS) | set(WIND_SAMPLE_IDS) | set(PORTAL_SAMPLE_IDS) | set(MOON_SAMPLE_IDS) | combo_members | card_spell_members | dark_gift_members)
        self.assertEqual({m.card_id for m in r.pool(CARD_SPELL_POOL_ID,
            GenerationContext('local-2026-09-23','experimental')).members}, card_spell_members)
        self.assertEqual({m.card_id for m in r.pool(COMBO_POOL_ID,
            GenerationContext('local-2026-09-23','experimental')).members}, combo_members)
        self.assertEqual({m.card_id for m in r.pool(BRONZE_POOL_ID,
            GenerationContext('local-2026-09-23','experimental')).members},set(BRONZE_SAMPLE_IDS))
        self.assertEqual({m.card_id for m in r.pool(REWIND_POOL_ID,
            GenerationContext('local-2026-09-23','experimental')).members}, set(REWIND_SAMPLE_IDS))
        self.assertEqual({m.card_id for m in r.pool('representative.generation', GenerationContext('local-2026-09-23','experimental')).members}, set(GENERATION_SAMPLE_IDS))
        self.assertIn('experimental', CARD_LIMITATIONS['LOE_029'])
        self.choose(g)
        self.assertEqual(replay(build_replay(g), build_registry()).snapshot(), g.snapshot())

    def test_drawn_batch_survives_trigger_choices_without_redrawing(self):
        self.pool(('a', 'b', 'c'))
        self.registry.register_behavior('pause', lambda c: [RequestChoice(1, (ChoiceOption('go', 'Go'),))])
        self.registry.register_card(CardDefinition('observer', 'observer', CardType.MINION, health=2,
            triggers=(TriggerSpec('card_added_to_hand', 'pause'),)))
        self.script(lambda c: [GenerateFromPool(1, 'pool', count=2)])
        g = self.game(board=('observer',)); self.cast(g)
        self.assertEqual(len(g.state.players[1].hand), 1)
        first_rng = g.snapshot()['rng_state']
        restored = Game.from_snapshot(g.snapshot(), self.registry)
        for branch in (g, restored):
            self.choose(branch)
            self.assertEqual(len(branch.state.players[1].hand), 2)
            self.assertEqual(branch.snapshot()['rng_state'], first_rng)
            self.choose(branch)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assert_replay(g)

    def test_failure_after_random_draw_rolls_back_rng_and_new_entities(self):
        self.pool()
        self.script(lambda c: [GenerateFromPool(1, 'pool', count=2), AddToHand(1, 'unimplemented')])
        g = self.game(); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.cast(g)
        self.assertEqual(g.snapshot(), before); self.assertEqual(g.history, [])

    def test_source_exclusion_requires_source_and_unknown_hero_class_is_rejected(self):
        self.pool()
        self.script(lambda c: [DiscoverFromPool(1, 'pool', PoolQuery(exclude_source=True))])
        g = self.game(); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'excluded source'): self.cast(g)
        self.assertEqual(g.snapshot(), before)
        self.setUp(); self.pool()
        self.registry.register_card(CardDefinition('classless', 'classless', CardType.HERO, health=30))
        self.script(lambda c: [ReplaceHero(1, 'classless'), DiscoverFromPool(1, 'pool', PoolQuery(class_mode='current'))])
        g = self.game(); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'current playable'): self.cast(g)
        self.assertEqual(g.snapshot(), before)

    def test_noncollectible_generation_is_not_filtered_by_construction_rules(self):
        self.pool(('token',)); self.script(lambda c: [GenerateFromPool(1, 'pool')])
        g = self.game(); self.cast(g)
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id, 'token')
        self.assertEqual(self.candidates(PoolQuery(collectible=True)), ())

    def test_context_changes_digest_but_not_player_observation(self):
        self.pool(); self.script(lambda c: [])
        a = self.game(); b = self.game(context=GenerationContext('other', 'experimental'))
        self.assertNotEqual(a.state_hash(), b.state_hash())
        self.assertEqual(a.observe(1), b.observe(1))


if __name__ == '__main__':
    unittest.main()
