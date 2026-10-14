"""Draft native contracts for independent logical summon producers.

This source is staged without imports or execution until the corrected complete
regression has an actual successful terminal. Its local policies are not CN facts.
"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from random import Random
import json
import os
import unittest

from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Herald, Keyword,
    PlayerSetup, RewindSpec, Scenario, SelectChoice, SnapshotError, SummonCause,
    TriggerSpec, UseHeroPower)
from hs_sim.engine.effects import (ChoiceOption, Destroy, EquipWeapon, GainArmor,
    RandomDamage, RequestChoice, ReplaceHero)
from hs_sim.engine.model import CardClass, PlayerEffectSpec, ProducerQuantitySpec, SummonProducerProfile
from hs_sim.engine.player_effects import AddPlayerEffect, RemovePlayerEffect
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
import test_v161_pool_summons as base


CONTEXT = base.CONTEXT
ROWS = (('blue', 2), ('green', 4), ('red', 1))


def registry():
    r = base.registry()
    profiles = (
        SummonProducerProfile('pq-default', 'companion'),
        SummonProducerProfile('pq-other', 'other-unit'),
        SummonProducerProfile('pq-card-only', 'companion', source_origins=('card_effect',)),
        SummonProducerProfile('pq-minion-only', 'companion', source_types=(CardType.MINION,)),
        SummonProducerProfile('pq-zero', 'companion', zero_base_eligible=True),
        SummonProducerProfile('pq-unsupported', 'companion', mode='choice_board'),
    )
    for profile in profiles:
        r.register_summon_producer_profile(profile)
    r.register_card(CardDefinition('pq-display', 'Public ongoing effect', CardType.SPELL))
    for spec in (
        PlayerEffectSpec('pq-one', 'pq-display', producer_quantities=(ProducerQuantitySpec('companion'),)),
        PlayerEffectSpec('pq-multi', 'pq-display', producer_quantities=(
            ProducerQuantitySpec('companion'), ProducerQuantitySpec('companion', 2),
            ProducerQuantitySpec('other-unit', 3))),
        PlayerEffectSpec('pq-other-effect', 'pq-display', producer_quantities=(ProducerQuantitySpec('other-unit'),)),
        PlayerEffectSpec('pq-plain', 'pq-display'),
        PlayerEffectSpec('pq-none', 'pq-display', producer_quantities=(ProducerQuantitySpec('companion', 0),)),
        PlayerEffectSpec('pq-timed', 'pq-display', kind='objective', duration=1,
            tick_event='turn_started', producer_quantities=(ProducerQuantitySpec('companion'),)),
        PlayerEffectSpec('pq-large', 'pq-display', producer_quantities=(ProducerQuantitySpec('companion', 1000000),)),
    ):
        r.register_player_effect(spec)
    query = PoolQuery(kinds=(CardType.MINION,), collectible=True)

    def batch(c, count=1, profile='pq-default', pool='weighted', replacement=True, player=None):
        return GenerateFromPool(c.player_id if player is None else player, pool, query,
            count=count, source_id=c.source_id, replacement=replacement, destination='board',
            cause=SummonCause.capture(c), producer_profile_id=profile)

    def grant(c, spec='pq-one', player=None):
        return AddPlayerEffect(c.player_id if player is None else player, spec, c.source_id)

    def first_child(c):
        roots = c.state.card_summon_history
        if not roots:
            return False
        root = roots[-1]
        link = root.request.producer_link
        return (link is not None and link.index == 0 and len(roots) == 1 and
            len(root.deliveries) == 1 and root.deliveries[0].entity is not None and
            root.deliveries[0].entity.entity_id == c.event.target_id)

    def wait(c, change=False):
        if not first_child(c):
            return []
        mutations = []
        if change:
            mutations = [RemovePlayerEffect(1, e.id) for e in c.state.players[1].player_effects]
            mutations.append(grant(c, 'pq-multi'))
        return [*mutations, RequestChoice(1, (
            ChoiceOption('bad', 'Invalid after RNG', (
                RandomDamage((c.state.players[2].hero_id,), 1, c.source_id), EquipWeapon(1, 'red'))),
            ChoiceOption('ok', 'Continue', (
                RandomDamage((c.state.players[2].hero_id,), 1, c.source_id), GainArmor(1, 1))),
            ), c.source_id)]

    def nested(c):
        if not first_child(c):
            return []
        return [grant(c), CastSpell(1, 'pq-batch', c.source_id, choices='player')]

    def strength(c):
        if not first_child(c):
            return []
        sources = [i for i in c.state.players[1].board if c.state.entities[i].card_id == 'source']
        return [*(Destroy(i, c.source_id) for i in sources), Herald(1, c.source_id),
            Herald(1, c.source_id), RequestChoice(1, (ChoiceOption('ok', 'Continue', ()),), c.source_id)]

    r.register_behavior('pq-granter-body', lambda c: [grant(c)])
    r.register_card(CardDefinition('pq-granter', 'Install whole-game amount', CardType.MINION,
        attack=1, health=5, battlecry='pq-granter-body'))
    r.register_behavior('pq-caller-body', lambda c: [batch(c, profile='pq-card-only')])
    r.register_card(CardDefinition('pq-caller', 'Physical card-origin producer', CardType.MINION,
        attack=1, health=5, battlecry='pq-caller-body'))
    for name, callback in (
        ('pq-watch', lambda c: wait(c)),
        ('pq-change-watch', lambda c: wait(c, True)),
        ('pq-nested', nested),
        ('pq-strength-watch', strength),
    ):
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.MINION, health=5,
            triggers=(TriggerSpec('minion_summoned', name),)))
    r.register_card(CardDefinition('pq-mage-soldier', 'Synthetic Mage Soldier', CardType.MINION,
        attack=1, health=1, herald_scaling=True, herald_soldier_for=CardClass.MAGE))
    r.register_card(CardDefinition('pq-scaling', 'Deferred scaling', CardType.MINION,
        attack=1, health=1, herald_scaling=True, metadata=r.card('red').metadata))
    r.register_pool_card(PoolCard.from_definition(r.card('pq-scaling')))
    r.register_pool(PoolDefinition('pq-scaling-pool', 'v1', CONTEXT.target_id,
        CONTEXT.mode, (PoolMember('pq-scaling'),)))
    r.register_behavior('pq-power-body', lambda c: [batch(c)])
    r.register_card(CardDefinition('pq-power', 'Unqualified power', CardType.HERO_POWER,
        on_use='pq-power-body'))
    bodies = {
        'pq-grant': lambda c: [grant(c)],
        'pq-grant-multi': lambda c: [grant(c, 'pq-multi')],
        'pq-grant-other': lambda c: [grant(c, 'pq-other-effect')],
        'pq-grant-plain': lambda c: [grant(c, 'pq-plain')],
        'pq-grant-none': lambda c: [grant(c, 'pq-none')],
        'pq-grant-timed': lambda c: [grant(c, 'pq-timed')],
        'pq-grant-large': lambda c: [grant(c, 'pq-large')],
        'pq-grant-enemy': lambda c: [grant(c, 'pq-multi', 2)],
        'pq-remove': lambda c: [RemovePlayerEffect(1, c.state.players[1].player_effects[0].id)],
        'pq-replace': lambda c: [ReplaceHero(1, 'rogue_hero')],
        'pq-batch': lambda c: [batch(c)],
        'pq-many': lambda c: [batch(c, count=3)],
        'pq-nr': lambda c: [batch(c, count=3, replacement=False)],
        'pq-empty': lambda c: [batch(c, pool='empty')],
        'pq-unknown-pool': lambda c: [batch(c, pool='unknown')],
        'pq-zero-default': lambda c: [batch(c, count=0)],
        'pq-zero-eligible': lambda c: [batch(c, count=0, profile='pq-zero')],
        'pq-other-batch': lambda c: [batch(c, profile='pq-other')],
        'pq-card-origin': lambda c: [batch(c, profile='pq-card-only')],
        'pq-minion-kind': lambda c: [batch(c, profile='pq-minion-only')],
        'pq-enemy': lambda c: [batch(c, player=2)],
        'pq-auto': lambda c: [CastSpell(1, 'pq-batch', c.source_id, choices='player')],
        'pq-unknown-profile': lambda c: [batch(c, profile='unknown-profile')],
        'pq-unsupported-mode': lambda c: [batch(c, profile='pq-unsupported')],
        'pq-wait-before': lambda c: [RequestChoice(1, (
            ChoiceOption('ok', 'Batch', (batch(c),)),), c.source_id)],
        'pq-retry': lambda c: [batch(c)],
        'pq-invalid-after': lambda c: [batch(c), EquipWeapon(1, 'red')],
        'pq-scale': lambda c: [batch(c, count=2, pool='pq-scaling-pool')],
        'pq-herald': lambda c: [Herald(1, c.source_id), Herald(1, c.source_id)],
    }
    for name, callback in bodies.items():
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL,
            cost=2 if name in ('pq-batch', 'pq-retry') else 0, on_play=name,
            keywords=(Keyword.REWIND,) if name == 'pq-retry' else (),
            rewind=RewindSpec(1) if name == 'pq-retry' else None))
    return r


class ProducerAmountTests(unittest.TestCase):
    play = base.PoolSummonTests.play
    choose = base.PoolSummonTests.choose
    rng = base.PoolSummonTests.rng

    def blob(self, value, label):
        output = os.environ.get('V169_INPUT_DIR')
        if not output:
            return
        root = Path(output) / self._testMethodName
        root.mkdir(parents=True, exist_ok=True)
        self.counter = getattr(self, 'counter', 0) + 1
        payload = value.snapshot() if hasattr(value, 'snapshot') else value
        (root / f'{self.counter:03d}-{label}.json').write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def game(self, hand=(), board=(), enemy=(), power=None, hero='hero'):
        g = Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, mana=10, max_mana=10,
                deck=('red',) * 10, hero_power_card_id=power),
            PlayerSetup('hero', board=enemy, mana=10, max_mana=10, deck=('blue',) * 10)),
            seed=169, generation_context=CONTEXT), registry())
        self.blob(g, 'initial')
        return g

    def portable(self, g):
        s = json.loads(json.dumps(g.snapshot()))
        self.blob(s, 'portable')
        self.assertEqual(Game.from_snapshot(deepcopy(s), registry()).snapshot(), s)
        self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), s)
        for player in (1, 2):
            public = json.dumps(g.observe(player)) + json.dumps(g.player_events(player))
            public += json.dumps(g.for_player(player).legal_actions())
            for key in ('producer_amount', 'AcceptedProducerAmount', 'ProducerAmountDecision',
                    'producer_quantities', 'pool_summon_history', 'card_summon_history',
                    'pool_summon_accepted', 'pool_summon_finished', 'rng_before', 'rng_after'):
                self.assertNotIn('"' + key + '"', public)
        return s

    def reject(self, s, label):
        s['events_hash'] = canonical_hash(s['events'])
        s['state_hash'] = canonical_hash({k: v for k, v in s.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        self.blob(s, label)
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(s, registry())

    def grant(self, g, name='pq-grant'):
        self.play(g, name)
        return tuple(g.state.players[1].player_effects)

    def last(self, g):
        return g.state.pool_summon_history[-1]

    def test_additive_instances_preserve_base_and_independent_weighted_draws(self):
        g = self.game(('pq-grant', 'pq-grant', 'pq-batch'))
        self.grant(g)
        inventory = self.grant(g)
        rng = self.rng(g)
        expected = base.independent_draw(rng, ROWS, 3)
        self.play(g, 'pq-batch')
        root = self.last(g)
        amount = root.producer_amount
        self.assertEqual((root.spec.count, amount.base_count, amount.total), (1, 1, 3))
        self.assertEqual((root.selected, root.rng_after), (expected, rng.getstate()))
        self.assertEqual(amount.inventory, inventory)
        self.assertEqual([d.additional for d in amount.decisions], [1, 1])
        self.assertEqual(len({d.instance.id for d in amount.decisions}), 2)
        self.assertEqual([x.request.materials[0].card_id for x in g.state.card_summon_history], list(expected))
        self.assertEqual(g.state.players[1].mana, 8)
        self.portable(g)

    def test_complete_inventory_includes_nonproducer_and_other_unit_decisions(self):
        g = self.game(('pq-grant-plain', 'pq-grant-multi', 'pq-grant-none', 'pq-batch'))
        for name in ('pq-grant-plain', 'pq-grant-multi', 'pq-grant-none'):
            self.grant(g, name)
        original = tuple(g.state.players[1].player_effects)
        self.play(g, 'pq-batch')
        amount = self.last(g).producer_amount
        self.assertEqual(amount.inventory, original)
        self.assertEqual([d.spec_index for d in amount.decisions], [0, 1, 2, 0])
        self.assertEqual([d.reason for d in amount.decisions], ['qualified', 'qualified', 'other_unit', 'qualified'])
        self.assertEqual([d.additional for d in amount.decisions], [1, 2, 0, 0])
        self.assertEqual(amount.total, 4)
        self.portable(g)

    def test_logical_unit_does_not_infer_selected_card_face_or_tribe(self):
        g = self.game(('pq-grant-other', 'pq-batch', 'pq-other-batch'))
        self.grant(g, 'pq-grant-other')
        self.play(g, 'pq-batch')
        first = self.last(g)
        self.assertEqual((first.producer_amount.total, first.producer_amount.decisions[0].reason), (1, 'other_unit'))
        self.play(g, 'pq-other-batch')
        second = self.last(g)
        self.assertEqual(second.producer_amount.total, 2)
        self.assertEqual(first.spec.basis.candidates, second.spec.basis.candidates)
        self.assertEqual({x.card_id for x in second.spec.basis.candidates}, {'red', 'green', 'blue'})
        self.portable(g)

    def test_granting_minion_lifecycle_does_not_remove_player_owned_addition(self):
        for operation in ('kill', 'silence', 'transform', 'steal', 'bounce'):
            with self.subTest(operation=operation):
                g = self.game(('pq-granter', operation, 'pq-batch'))
                self.play(g, 'pq-granter')
                original = g.state.players[1].player_effects[0]
                self.play(g, operation, original.source_id)
                self.play(g, 'pq-batch')
                self.assertEqual(self.last(g).producer_amount.inventory, (original,))
                self.assertEqual(self.last(g).producer_amount.total, 2)
                self.assertFalse(g.state.players[2].player_effects)
                self.portable(g)

    def test_hero_replacement_and_duplicate_removal_keep_correct_instances(self):
        g = self.game(('pq-grant', 'pq-grant', 'pq-replace', 'pq-remove', 'pq-batch'))
        self.grant(g)
        original = self.grant(g)
        self.play(g, 'pq-replace')
        self.play(g, 'pq-remove')
        self.assertEqual(tuple(g.state.players[1].player_effects), original[1:])
        self.play(g, 'pq-batch')
        self.assertEqual(self.last(g).producer_amount.inventory, original[1:])
        self.assertEqual(self.last(g).producer_amount.total, 2)
        self.portable(g)

    def test_original_cause_player_is_separate_from_delivery_recipient(self):
        g = self.game(('pq-grant', 'pq-grant-enemy', 'pq-enemy'))
        actor_inventory = self.grant(g)
        self.play(g, 'pq-grant-enemy')
        self.play(g, 'pq-enemy')
        root = self.last(g)
        self.assertEqual((root.spec.cause.player_id, root.spec.basis.player_id), (1, 2))
        self.assertEqual(root.producer_amount.inventory, actor_inventory)
        self.assertEqual((root.producer_amount.recipient_id, root.producer_amount.total), (2, 2))
        self.assertEqual(len(g.state.players[2].board), 2)
        self.assertEqual(len(g.state.players[1].board), 0)
        self.portable(g)

    def test_original_origin_and_source_type_qualification_are_explicit(self):
        for name, reason in (('pq-card-origin', 'source_origin'), ('pq-minion-kind', 'source_kind')):
            with self.subTest(name=name):
                g = self.game(('pq-grant', name))
                self.grant(g)
                self.play(g, name)
                amount = self.last(g).producer_amount
                self.assertEqual((amount.total, amount.decisions[0].reason), (1, reason))
                self.portable(g)
        g = self.game(('pq-grant', 'pq-caller'))
        self.grant(g)
        self.play(g, 'pq-caller')
        amount = self.last(g).producer_amount
        self.assertEqual((amount.cause.origin, amount.source_kind, amount.total), ('card_effect', CardType.MINION, 2))
        self.portable(g)

    def test_hero_power_origin_does_not_borrow_spell_card_qualification(self):
        g = self.game(('pq-grant',), power='pq-power')
        self.grant(g)
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        amount = self.last(g).producer_amount
        self.assertEqual((amount.cause.origin, amount.total, amount.decisions[0].reason), ('hero_power', 1, 'source_origin'))
        self.portable(g)

    def test_automatic_cast_uses_cast_card_type_instead_of_scheduling_entity(self):
        g = self.game(('pq-grant', 'pq-batch'), ('pq-nested',))
        self.grant(g)
        self.play(g, 'pq-batch')
        outer, inner = g.state.pool_summon_history
        self.assertEqual([x.producer_amount.total for x in (outer, inner)], [2, 3])
        self.assertEqual(inner.spec.cause.origin, 'spell_cast')
        self.assertEqual(inner.spec.cause.source.card_id, 'pq-batch')
        cast = next(c for c in g.state.cast_history if c.id == inner.spec.cause.cast_id)
        self.assertEqual(cast.source_id, inner.spec.cause.source.entity_id)
        self.assertEqual(g.state.entities[cast.caster_id].card_id, 'pq-nested')
        self.assertNotEqual(cast.source_id, cast.caster_id)
        self.assertEqual(inner.spec.cause.cast_card_id, 'pq-batch')
        self.assertEqual(inner.producer_amount.source_kind, CardType.SPELL)
        self.assertTrue(set(outer.entry_root_ids).isdisjoint(inner.entry_root_ids))
        self.portable(g)

    def test_owner_turn_expiry_preserves_original_accepted_inventory(self):
        g = self.game(('pq-grant-timed', 'pq-batch', 'pq-batch'))
        self.grant(g, 'pq-grant-timed')
        self.play(g, 'pq-batch')
        first = self.last(g)
        g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].player_effects[0].remaining_turns, 1)
        g.apply(EndTurn(2))
        self.assertFalse(g.state.players[1].player_effects)
        self.assertEqual(first.producer_amount.inventory[0].remaining_turns, 1)
        self.play(g, 'pq-batch')
        self.assertEqual([x.producer_amount.total for x in g.state.pool_summon_history], [2, 1])
        self.portable(g)

    def test_extra_independent_items_each_receive_existing_entry_quantity(self):
        g = self.game(('pq-grant', 'pq-batch'), ('source',))
        self.grant(g)
        rng = self.rng(g)
        expected = base.independent_draw(rng, ROWS, 2)
        self.play(g, 'pq-batch')
        self.assertEqual(self.last(g).selected, expected)
        self.assertEqual([x.plan.total for x in g.state.card_summon_history], [2, 2])
        self.assertEqual([[d.entity.card_id for d in x.deliveries] for x in g.state.card_summon_history],
            [[card, card] for card in expected])
        self.portable(g)

    def test_first_wait_removes_live_addition_without_changing_accepted_amount(self):
        g = self.game(('pq-grant', 'pq-batch', 'pq-batch'), ('pq-change-watch',))
        original = self.grant(g)
        self.play(g, 'pq-batch')
        self.assertIsNotNone(g.state.pending_choice)
        first = self.last(g)
        self.assertEqual(first.producer_amount.inventory, original)
        self.assertEqual(first.producer_amount.total, 2)
        self.assertEqual(g.state.players[1].player_effects[0].spec_id, 'pq-multi')
        saved = self.portable(g)
        with self.assertRaises(Exception):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g, 'ok')
        self.assertEqual(self.last(g).selected, first.selected)
        self.assertEqual(self.last(g).producer_amount, first.producer_amount)
        self.play(g, 'pq-batch')
        self.assertEqual([x.producer_amount.total for x in g.state.pool_summon_history], [2, 4])
        self.portable(g)

    def test_later_child_recaptures_quantity_without_redrawing_batch(self):
        g = self.game(('pq-grant', 'pq-many'), ('source', 'pool_watcher'))
        self.grant(g)
        self.play(g, 'pq-many')
        selected = self.last(g).selected
        self.assertEqual(self.last(g).producer_amount.total, 4)
        self.assertIsNotNone(g.state.pending_choice)
        self.portable(g)
        self.choose(g, 'ok')
        self.assertEqual(self.last(g).selected, selected)
        self.assertEqual([x.plan.total for x in g.state.card_summon_history], [2, 1, 1, 1])
        self.portable(g)

    def test_later_child_entry_strength_recaptures_its_own_window(self):
        g = self.game(('pq-grant', 'pq-herald', 'pq-scale'),
            ('source', 'pq-strength-watch'), hero='mage_hero')
        self.grant(g)
        self.play(g, 'pq-herald')
        self.play(g, 'pq-scale')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.last(g).producer_amount.total, 3)
        self.portable(g)
        self.choose(g, 'ok')
        children = g.state.card_summon_history
        self.assertEqual([(x.entry_strength.count, x.plan.total) for x in children], [(2, 2), (4, 1), (4, 1)])
        self.assertEqual(self.last(g).selected, ('pq-scaling',) * 3)
        self.portable(g)

    def test_full_board_keeps_all_independent_draws_and_failed_attempts(self):
        g = self.game(('pq-grant', 'pq-batch'), ('red',) * 7)
        self.grant(g)
        rng = self.rng(g)
        expected = base.independent_draw(rng, ROWS, 2)
        self.play(g, 'pq-batch')
        self.assertEqual((self.last(g).selected, self.last(g).rng_after), (expected, rng.getstate()))
        self.assertEqual([[d.outcome for d in x.deliveries] for x in g.state.card_summon_history],
            [['board_full'], ['board_full']])
        self.portable(g)

    def test_empty_pool_and_without_replacement_preserve_original_policies(self):
        for name in ('pq-empty', 'pq-nr'):
            with self.subTest(name=name):
                g = self.game(('pq-grant-multi', name))
                self.grant(g, 'pq-grant-multi')
                before = g.snapshot()['rng_state']
                rng = self.rng(g)
                count = 1 if name == 'pq-empty' else 3
                expected = () if name == 'pq-empty' else base.independent_draw(rng, ROWS, 6, False)
                self.play(g, name)
                root = self.last(g)
                self.assertEqual((root.spec.count, root.producer_amount.total), (count, count + 3))
                self.assertEqual(root.selected, expected)
                if name == 'pq-empty':
                    self.assertEqual(g.snapshot()['rng_state'], before)
                else:
                    self.assertEqual((len(set(root.selected)), root.rng_after), (3, rng.getstate()))
                self.portable(g)

    def test_zero_base_qualification_is_declared_and_rng_neutral_when_ineligible(self):
        for name, total, reason in (('pq-zero-default', 0, 'zero_base'), ('pq-zero-eligible', 1, 'qualified')):
            with self.subTest(name=name):
                g = self.game(('pq-grant', name))
                self.grant(g)
                before = g.snapshot()['rng_state']
                self.play(g, name)
                root = self.last(g)
                self.assertEqual((root.spec.count, root.producer_amount.total), (0, total))
                self.assertEqual(root.producer_amount.decisions[0].reason, reason)
                self.assertEqual(len(root.selected), total)
                if total == 0:
                    self.assertEqual(g.snapshot()['rng_state'], before)
                for invalid in (-1, True, 0.5):
                    with self.assertRaises(ValueError):
                        GenerateFromPool(1, 'weighted', count=invalid, destination='board',
                            cause=root.spec.cause, producer_profile_id='pq-zero')
                for kwargs in ({'count': 0}, {'count': 0, 'destination': 'board'}):
                    with self.assertRaises(ValueError):
                        GenerateFromPool(1, 'weighted', **kwargs)
                self.portable(g)

    def test_unknown_profile_mode_pool_and_derived_budget_reject_atomically(self):
        for grant, operation in (('pq-grant', 'pq-unknown-profile'), ('pq-grant', 'pq-unsupported-mode'),
                ('pq-grant', 'pq-unknown-pool'), ('pq-grant-large', 'pq-batch')):
            with self.subTest(operation=operation, grant=grant):
                g = self.game((grant, operation))
                self.grant(g, grant)
                before = g.snapshot()
                with self.assertRaises(Exception):
                    self.play(g, operation)
                self.assertEqual(g.snapshot(), before)

    def test_waiting_public_request_restores_before_amount_acceptance(self):
        g = self.game(('pq-grant', 'pq-wait-before'))
        self.grant(g)
        self.play(g, 'pq-wait-before')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(g.state.pool_summon_history)
        self.portable(g)
        self.choose(g, 'ok')
        self.assertEqual(self.last(g).producer_amount.total, 2)
        self.portable(g)

    def test_true_retry_retains_original_proof_and_monotonic_new_roots(self):
        g = self.game(('pq-grant', 'pq-retry'))
        self.grant(g)
        self.play(g, 'pq-retry')
        self.assertIsNotNone(g.state.pending_choice)
        old = self.last(g)
        self.portable(g)
        self.choose(g, 'retry')
        self.assertEqual(len(g.state.pool_summon_history), 1)
        new = self.last(g)
        self.assertGreater(new.id, old.id)
        self.assertGreater(min(new.entry_root_ids), max(old.entry_root_ids))
        self.assertEqual(new.producer_amount.total, old.producer_amount.total)
        self.assertEqual(new.producer_amount.inventory, old.producer_amount.inventory)
        self.assertIsNone(g.state.pending_choice)
        self.portable(g)

    def test_terminal_prefix_and_rng_exception_preserve_transaction_contract(self):
        g = self.game(('pq-grant', 'pq-batch'), ('fatal_watcher',))
        self.grant(g)
        self.play(g, 'pq-batch')
        root = self.last(g)
        self.assertEqual((root.producer_amount.total, len(root.selected), len(root.entry_root_ids)), (2, 2, 1))
        self.assertEqual(root.status, 'interrupted')
        self.portable(g)
        h = self.game(('pq-grant', 'pq-invalid-after'))
        self.grant(h)
        before = h.snapshot()
        with self.assertRaises(Exception):
            self.play(h, 'pq-invalid-after')
        self.assertEqual(h.snapshot(), before)

    def test_legacy_unprofiled_batches_do_not_infer_logical_identity(self):
        g = self.game(('pq-grant', 'batch'))
        self.grant(g)
        rng = self.rng(g)
        expected = base.independent_draw(rng, ROWS, 3)
        self.play(g, 'batch')
        root = self.last(g)
        self.assertIsNone(root.spec.producer_profile_id)
        self.assertIsNone(root.producer_amount)
        self.assertEqual((root.selected, root.rng_after), (expected, rng.getstate()))
        self.portable(g)

    def test_rehashed_amount_decision_rng_selection_and_queue_tampering_rejects(self):
        g = self.game(('pq-grant', 'pq-batch'), ('pq-watch',))
        self.grant(g)
        self.play(g, 'pq-batch')
        saved = self.portable(g)
        for case in ('base', 'total', 'profile', 'unit', 'inventory', 'source', 'future-counter', 'index',
                'decision', 'selected', 'rng', 'lost-proof', 'crop-next', 'crop-finish'):
            with self.subTest(case=case):
                bad = deepcopy(saved)
                root = bad['state']['pool_summon_history'][0]
                amount = root['producer_amount']
                if case == 'base':
                    amount['base_count'] += 1
                elif case == 'total':
                    amount['total'] += 1
                elif case == 'profile':
                    amount['profile']['id'] = 'pq-other'
                elif case == 'unit':
                    amount['profile']['unit_id'] = 'other-unit'
                elif case == 'inventory':
                    amount['inventory'] = []
                elif case == 'source':
                    amount['decisions'][0]['instance']['source_id'] = amount['next_entity_id']
                elif case == 'future-counter':
                    amount['next_order'] = bad['state']['next_order'] + 1
                elif case == 'index':
                    amount['decisions'][0]['spec_index'] = 1
                elif case == 'decision':
                    amount['decisions'] = []
                elif case == 'selected':
                    root['selected'] = root['selected'][:-1]
                elif case == 'rng':
                    root['rng_after'][1][2] ^= 1
                elif case == 'lost-proof':
                    root['producer_amount'] = None
                else:
                    tail = bad['resolution_frame']['fields']['continuation']['tuple']
                    kind = 'StartPoolSummonEntry' if case == 'crop-next' else 'FinishPoolSummonBatch'
                    tail.pop(next(i for i, item in enumerate(tail) if item.get('type', '').endswith('.' + kind)))
                self.reject(bad, case)

    def test_strict_declarations_and_registry_fingerprint_bind_profile(self):
        for declaration in (lambda: ProducerQuantitySpec('companion', True),
                lambda: SummonProducerProfile('bad', 'companion', source_types=(CardType.SPELL, CardType.SPELL)),
                lambda: PlayerEffectSpec('bad', 'pq-display', producer_quantities=[])):
            with self.assertRaises(ValueError):
                declaration()
        r = registry()
        before = r.fingerprint()
        r.register_summon_producer_profile(SummonProducerProfile('new-profile', 'companion'))
        self.assertNotEqual(r.fingerprint(), before)
        with self.assertRaises(ValueError):
            r.register_summon_producer_profile(SummonProducerProfile('new-profile', 'companion'))
        r.freeze()
        with self.assertRaises(Exception):
            r.register_summon_producer_profile(SummonProducerProfile('frozen-new', 'companion'))
        other = base.registry()
        other.register_player_effect(PlayerEffectSpec('unknown-unit', 'red',
            producer_quantities=(ProducerQuantitySpec('missing-unit'),)))
        with self.assertRaises(Exception):
            other.freeze()


if __name__ == '__main__':
    unittest.main()

