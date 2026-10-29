"""Complete faction inventories through the real paid source and hand delivery."""
from dataclasses import asdict
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin, event_player
from hs_sim.cards import champions_of_azeroth as native
from hs_sim.engine import Game, PlayerSetup, ResolutionError, Scenario
from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import AddToHand, ChoiceOption, InvokeBehavior, RandomDamage, RequestChoice
from hs_sim.engine.model import CardDefinition, CardType, TriggerSpec, Zone
from hs_sim.engine.pools import PoolCard, PoolQuery, resolve_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.local_pool_format import ROOT, build_cn37_local_pool_format, load_bindings
from hs_sim.targets import TargetValidationError, canonical_digest

CARD = native.CARD
UNIT = 'CORE_CS2_182'
PREFIX = 'k657.'
FAIL = PREFIX + 'deliberate_failure'


@lru_cache(maxsize=None)
def fixture(role='writer'):
    """One registry per reader role; all finite reaction fixtures share it."""
    f = build_cn37_local_pool_format()
    r = f.registry

    def fail(c):
        raise ValueError('K657 deliberate failure after random physical delivery')

    r.register_behavior(FAIL, fail)
    for kind in ('wait', 'fail', 'fill'):
        key = PREFIX + kind

        def watch(c, kind=kind):
            e = c.event
            source = c.state.entities.get(e.source_id)
            if source is None or source.card_id not in (CARD, 'TIME_861'):
                return ()
            pid = event_player(c)
            if kind == 'fill':
                if e.kind != 'spell_cast_started' or source.card_id != CARD:
                    return ()
                return tuple(AddToHand(pid, UNIT, c.source_id)
                    for _ in range(10 - len(c.state.players[pid].hand)))
            if e.kind != 'card_added_to_hand':
                return ()
            if kind == 'fail':
                return (InvokeBehavior(FAIL, c.source_id, pid),)
            return (RequestChoice(pid, (ChoiceOption('continue', 'Continue'),
                ChoiceOption('fail', 'Fail after random work', (
                    RandomDamage((c.state.players[3-pid].hero_id,), 1, c.source_id),
                    InvokeBehavior(FAIL, c.source_id, pid)))), c.source_id,
                prompt='K657 original physical delivery'),)

        r.register_behavior(key, watch)
        r.register_card(CardDefinition(key, key, CardType.MINION, health=30,
            triggers=tuple(TriggerSpec(event, key) for event in
                ('card_added_to_hand', 'spell_cast_started'))))
    return f


class ChampionsOfAzerothTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(lambda mode, role: fixture(role).registry)

    def game(self, *, seed=74, player=1, watch=None, hand=(CARD,)):
        f = fixture()
        own = PlayerSetup('HERO_08', hand=hand, deck=(UNIT,) * 6,
            mana=60, max_mana=60, mana_cap=60)
        other = PlayerSetup('HERO_08', board=(PREFIX + watch,) if watch else (),
            deck=(UNIT,) * 6)
        return Game.from_scenario(Scenario((own, other) if player == 1 else (other, own),
            active_player=player, seed=seed, generation_context=f.context), f.registry)

    def test_complete_sixteen_raw_faces_and_twenty_two_primary_observations_keep_native_pins(self):
        d = native.load_batch()
        self.assertEqual(len(d['cards'] + d['dependencies'] + d['existing_dependencies']), 16)
        self.assertEqual(len(d['official_observations']), 22)
        r = fixture().registry
        native.validate_native(r, d)
        self.assertEqual(r.pool_card('LOE_077'), PoolCard.from_definition(r.card('LOE_077')))
        for row in d['existing_dependencies']:
            self.assertEqual(canonical_digest(asdict(r.card(row['record']['id']))), row['definition_sha256'])
        for cid in native.CHOICES:
            self.assertTrue(r.card(cid).choice_only)
            self.assertNotIn(cid, r.pool_cards)
        self.assertFalse(d['formal_pool_complete'] or d['cn_calibrated'])

    def test_two_full_faction_lists_keep_original_order_roles_and_unit_weights(self):
        f = fixture()
        for d in native.load_batch()['domains']:
            p = f.registry.pool(d['pool_id'], f.context)
            self.assertEqual([m.card_id for m in p.members], d['member_ids'])
            self.assertTrue(p.complete)
            self.assertFalse(p.excluded_card_ids)
            rows = resolve_candidates(f.registry, f.context, p.id, native.QUERY,
                source_card_id=CARD, exclude_source_by_rule=True)
            self.assertEqual([m.card_id for m in rows], d['actual_ids'])
            self.assertTrue(all(m.weight == 1 for m in (*p.members, *rows)))

    def test_real_paid_parent_alliance_choice_two_distinct_discounted_brann_instances(self):
        g = self.game()
        self.play(g, CARD)
        self.assertEqual(g.state.players[1].mana, 56)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options], list(native.CHOICES))
        self.choose(g, native.CHOICES[0])
        ids = tuple(g.state.players[1].hand)
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual([g.state.entities[i].card_id for i in ids], ['LOE_077'] * 2)
        self.assertEqual([local_cost(g.state.entities[i])[0] for i in ids], [1, 1])
        self.play(g, 'LOE_077')
        self.play(g, 'LOE_077')
        self.assertEqual(g.state.players[1].mana, 54)
        self.assertEqual(len(g.state.play_history), 3)

    def test_real_horde_choice_uses_its_full_domain_and_native_cairne_is_playable(self):
        g = self.game(seed=13)
        self.play(g, CARD)
        self.choose(g, native.CHOICES[1])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], ['EX1_110'] * 2)
        self.play(g, 'EX1_110')
        self.assertEqual(g.state.players[1].mana, 52)
        self.assertEqual(self.entity(g, 'EX1_110', zone='board').max_health, 5)

    def test_parent_choice_restores_before_sampling_and_replays_the_same_complete_branch(self):
        g = self.game()
        self.play(g, CARD)
        restored = self.portable(g)
        for x in (g, restored):
            self.choose(x, native.CHOICES[1])
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.portable(g)

    def test_first_delivery_exposes_discount_before_reaction_and_restores_remaining_generation(self):
        g = self.game(watch='wait')
        self.play(g, CARD)
        self.choose(g, native.CHOICES[0])
        self.assertEqual(len(g.state.players[1].hand), 1)
        self.assertEqual(local_cost(self.entity(g, 'LOE_077'))[0], 1)
        restored = self.portable(g)
        for _ in range(2):
            self.choose(g)
            self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len(g.state.players[1].hand), 2)

    def test_full_hand_burns_both_original_selections_without_reselection(self):
        g = self.game(seed=13, watch='fill')
        self.play(g, CARD)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.choose(g, native.CHOICES[1])
        generated = [e for e in g.state.entities.values() if e.card_id == 'EX1_110']
        self.assertEqual(len(generated), 2)
        self.assertTrue(all(e.zone == Zone.GRAVEYARD for e in generated))
        self.assertEqual(g.state.players[1].mana, 56)

    def test_failure_after_actual_random_generation_restores_original_choice_and_rng(self):
        g = self.game(watch='fail')
        self.play(g, CARD)
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, native.CHOICES[0])
        self.assertEqual(g.snapshot(), before)

    def test_second_seat_private_choices_cards_and_inventory_stay_out_of_opponent_events(self):
        g = self.game(player=2)
        self.play(g, CARD, player=2)
        view = json.dumps(g.for_player(1).observe()) + json.dumps(g.player_events(1))
        for cid in native.CHOICES:
            self.assertNotIn(cid, view)
        self.choose(g, native.CHOICES[0])
        view = json.dumps(g.for_player(1).observe()) + json.dumps(g.player_events(1))
        for key in ('LOE_077', 'member_ids', 'native_pins', 'rng_state', 'constructed.champions_of_azeroth'):
            self.assertNotIn(key, view)
        self.assertEqual(g.state.players[2].mana, 56)
        self.portable(g)

    def test_unknown_source_or_query_and_missing_native_member_are_rejected(self):
        f = fixture()
        pool = native.load_batch()['domains'][0]['pool_id']
        with self.assertRaises(UnsupportedDefinitionError):
            resolve_candidates(f.registry, f.context, pool, native.QUERY,
                source_card_id='CS2_029', exclude_source_by_rule=True)
        with self.assertRaises(UnsupportedDefinitionError):
            resolve_candidates(f.registry, f.context, pool, PoolQuery(kinds=(CardType.MINION,)),
                source_card_id=CARD, exclude_source_by_rule=True)
        with patch.dict(f.registry._cards):
            f.registry._cards.pop('LOE_077')
            with self.assertRaises((UnsupportedDefinitionError, TargetValidationError)):
                native.validate_native(f.registry, native.load_batch())

    def test_manifest_preserves_every_v14_predecessor_declaration_and_labels_local_policies(self):
        d = load_bindings()
        old = json.loads((ROOT / d['previous_manifest']['path']).read_text(encoding='utf-8'))
        self.assertEqual(canonical_digest(old), d['previous_manifest']['canonical_sha256'])
        for key, value in old.items():
            if key not in ('policy_id', 'accepted_on', 'previous_manifest'):
                self.assertEqual(d[key], value, key)
        self.assertEqual(d['champions_binding']['member_count'], 10)
        self.assertEqual(d['toki_mage_binding']['mage_neutral_member_count'], 181)
        self.assertFalse(d['formal_pool_complete'])
