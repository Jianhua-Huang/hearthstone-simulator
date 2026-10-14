"""Unexecuted native tests for the ordered-group kernel source candidate."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from random import Random
import json
import os
import unittest

from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard,
    PlayerSetup, RewindSpec, Scenario, SelectChoice, SnapshotError, TriggerSpec,
    UseHeroPower)
from hs_sim.engine.effects import (ChoiceOption, Destroy, EquipWeapon, GainArmor,
    RandomDamage, RequestChoice)
from hs_sim.engine.model import SummonProducerProfile, SummonStats
from hs_sim.engine.ordered_group_batches import (FinishOrderedGroup, OrderedGroupRecord,
    SummonOrderedGroup, from_dict as group_from_dict, validate_closed_events,
    validate_record as validate_group_record)
from hs_sim.engine.ordered_summon_groups import (GroupSummonEntryLink,
    OrderedGroupMember, OrderedSummonGroupSpec)
from hs_sim.engine.player_effects import AddPlayerEffect, RemovePlayerEffect
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonCause, SummonEntryMaterial
import test_v169_producer_amounts as pending


MEMBERS = (OrderedGroupMember('first-red', SummonEntryMaterial('red'), extra_weight=1),
           OrderedGroupMember('middle-green', SummonEntryMaterial('green'), extra_weight=4),
           OrderedGroupMember('last-red', SummonEntryMaterial('red'), extra_weight=2))


def registry():
    r = pending.registry()
    for profile in (
        SummonProducerProfile('og-default', 'companion', mode='ordered_board_group'),
        SummonProducerProfile('og-card-only', 'companion', mode='ordered_board_group', source_origins=('card_effect',)),
        SummonProducerProfile('og-spell-only', 'companion', mode='ordered_board_group', source_types=(CardType.SPELL,)),
        SummonProducerProfile('og-zero', 'companion', mode='ordered_board_group', zero_base_eligible=True),
    ):
        r.register_summon_producer_profile(profile)

    def group(c, members=MEMBERS, profile='og-default', player=None, policy='weighted_occurrence_with_replacement'):
        return SummonOrderedGroup(OrderedSummonGroupSpec(c.player_id if player is None else player,
            SummonCause.capture(c), members, extra_policy=policy), profile)

    def first(c):
        children = c.state.card_summon_history
        if not children:
            return False
        child = children[-1]
        link = child.request.producer_link
        return (type(link) is GroupSummonEntryLink and link.index == 0 and
                len(c.state.ordered_group_history) == 1 and len(child.deliveries) == 1 and
                child.deliveries[0].entity is not None and
                child.deliveries[0].entity.entity_id == c.event.target_id)

    def wait(c, change=False):
        if not first(c):
            return []
        mutations = []
        if change:
            mutations = [RemovePlayerEffect(1, e.id) for e in c.state.players[1].player_effects]
            mutations += [AddPlayerEffect(1, 'pq-multi', c.source_id)]
            mutations += [Destroy(i, c.source_id) for i in c.state.players[1].board
                          if c.state.entities[i].card_id == 'source']
        return [*mutations, RequestChoice(1, (
            ChoiceOption('bad', 'Invalid after RNG', (
                RandomDamage((c.state.players[2].hero_id,), 1, c.source_id), EquipWeapon(1, 'red'))),
            ChoiceOption('ok', 'Continue', (GainArmor(1, 1),)),
        ), c.source_id)]

    def nested(c):
        if not first(c):
            return []
        return [CastSpell(1, 'og-single', c.source_id, choices='player')]

    def pool_to_group(c):
        if len(c.state.pool_summon_history) != 1 or c.state.ordered_group_history:
            return []
        children = c.state.card_summon_history
        if not children or not children[-1].deliveries or children[-1].deliveries[0].entity is None:
            return []
        if c.event.target_id != children[-1].deliveries[0].entity.entity_id:
            return []
        return [CastSpell(1, 'og-spell-group', c.source_id, choices='player')]

    def free_space(c):
        if not first(c):
            return []
        older = [i for i in c.state.players[1].board
                 if c.state.entities[i].card_id == 'red' and i != c.event.target_id]
        return [Destroy(older[0], c.source_id), *wait(c)]

    for name, callback in (('og-watch', lambda c: wait(c)), ('og-change-watch', lambda c: wait(c, True)),
                           ('og-nested', nested), ('og-pool-auto', pool_to_group),
                           ('og-free-space', free_space)):
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.MINION, health=5,
                                        triggers=(TriggerSpec('minion_summoned', name),)))
    recipe = (OrderedGroupMember('recipe', SummonEntryMaterial('red', SummonStats(7, 6),
              ('gift',), (Keyword.TAUNT,))),)
    positions = tuple(replace(m, position=i) for i, m in enumerate(MEMBERS))
    scaling = (OrderedGroupMember('scale-a', SummonEntryMaterial('pq-scaling')),
               OrderedGroupMember('scale-b', SummonEntryMaterial('pq-scaling')))
    bodies = {
        'og-group': lambda c: [group(c)],
        'og-single': lambda c: [group(c, MEMBERS[:1])],
        'og-plain': lambda c: [group(c, profile=None)],
        'og-position': lambda c: [group(c, positions, profile=None)],
        'og-recipe': lambda c: [group(c, recipe)],
        'og-enemy': lambda c: [group(c, player=2)],
        'og-card-filter': lambda c: [group(c, profile='og-card-only')],
        'og-spell-group': lambda c: [group(c, profile='og-spell-only')],
        'og-empty': lambda c: [group(c, (), profile=None, policy='none')],
        'og-unknown': lambda c: [group(c, (OrderedGroupMember('unknown', SummonEntryMaterial('unknown')),
            OrderedGroupMember('known', SummonEntryMaterial('red'))))],
        'og-bad-mode': lambda c: [group(c, profile='pq-default')],
        'og-no-extra-domain': lambda c: [group(c, (), profile='og-zero', policy='weighted_occurrence_with_replacement')],
        'og-disallow-extra': lambda c: [group(c, policy='none')],
        'og-fail-after': lambda c: [group(c), EquipWeapon(1, 'red')],
        'og-wait-before': lambda c: [RequestChoice(1, (ChoiceOption('ok', 'Accept group', (group(c),)),), c.source_id)],
        'og-inject': lambda c: [RequestChoice(1, (ChoiceOption('bad', 'Injected Finish', (FinishOrderedGroup(1),)),), c.source_id)],
        'og-retry': lambda c: [group(c)],
        'og-scale': lambda c: [group(c, scaling)],
    }
    for name, callback in bodies.items():
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name,
            keywords=(Keyword.REWIND,) if name == 'og-retry' else (),
            rewind=RewindSpec(1) if name == 'og-retry' else None))
    r.register_behavior('og-caller-body', lambda c: [group(c, profile='og-card-only')])
    r.register_card(CardDefinition('og-caller', 'Physical card cause', CardType.MINION,
                                    health=5, battlecry='og-caller-body'))
    r.register_behavior('og-power-body', lambda c: [group(c)])
    r.register_card(CardDefinition('og-power', 'Group power', CardType.HERO_POWER, on_use='og-power-body'))
    return r


class OrderedGroupKernelTests(unittest.TestCase):
    def blob(self, value, label):
        output = os.environ.get('V195_INPUT_DIR')
        if not output:
            return
        root = Path(output) / self._testMethodName
        root.mkdir(parents=True, exist_ok=True)
        self.counter = getattr(self, 'counter', 0) + 1
        payload = value.snapshot() if hasattr(value, 'snapshot') else value
        (root / f'{self.counter:03d}-{label}.json').write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def game(self, hand=(), board=(), enemy=(), hero='hero', power=None):
        g = Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, mana=10, max_mana=10,
                        deck=('red',) * 10, hero_power_card_id=power),
            PlayerSetup('hero', board=enemy, mana=10, max_mana=10, deck=('blue',) * 10)),
            seed=195, generation_context=pending.CONTEXT), registry())
        self.blob(g, 'initial')
        return g

    def play(self, g, name, target=None):
        self.blob(g, 'before-' + name)
        player = g.state.active_player
        card = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(player, card, target))

    def choose(self, g, key):
        self.blob(g, 'before-' + key)
        pending = g.state.pending_choice
        return g.apply(SelectChoice(pending.player_id, pending.id, (key,)))

    def resume(self, g, key):
        value = self.portable(g)
        recovered = (Game.from_snapshot(deepcopy(value), registry()), g.clone(),
                     replay(build_replay(g), registry()))
        self.choose(g, key)
        expected = g.snapshot()
        for other in recovered:
            self.choose(other, key)
            self.assertEqual(other.snapshot(), expected)

    def portable(self, g):
        value = json.loads(json.dumps(g.snapshot()))
        self.blob(value, 'portable')
        self.assertEqual(Game.from_snapshot(deepcopy(value), registry()).snapshot(), value)
        self.assertEqual(g.clone().snapshot(), value)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), value)
        for player in (1, 2):
            public = json.dumps(g.observe(player)) + json.dumps(g.player_events(player))
            public += json.dumps(g.for_player(player).legal_actions())
            for key in ('ordered_group_history', 'next_ordered_group_id', 'OrderedGroupRecord',
                        'OrderedGroupSelection', 'producer_amount', 'producer_quantities',
                        'ordered_group_accepted', 'ordered_group_finished', 'rng_before', 'rng_after'):
                self.assertNotIn(key, public)
        return value

    def reject(self, value, label):
        value['events_hash'] = canonical_hash(value['events'])
        value['state_hash'] = canonical_hash({k: v for k, v in value.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        self.blob(value, label)
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(value, registry())

    def root(self, g):
        return g.state.ordered_group_history[-1]

    def children(self, g, root=None):
        root = self.root(g) if root is None else root
        return [next(c for c in g.state.card_summon_history if c.id == i) for i in root.entry_root_ids]

    def test_original_heterogeneous_group_keeps_equal_face_occurrences_without_rng(self):
        g = self.game(('og-plain',))
        before = g._rng.getstate()
        self.play(g, 'og-plain')
        root = self.root(g)
        self.assertEqual([m.member_key for m in root.selection.occurrences], ['first-red', 'middle-green', 'last-red'])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], ['red', 'green', 'red'])
        self.assertEqual((root.selection.rng_before, root.selection.rng_after, g._rng.getstate()), (before, before, before))
        self.assertEqual(len(set(root.entry_root_ids)), 3)
        self.assertEqual(root.status, 'completed')
        self.portable(g)

    def test_extra_instances_add_to_whole_group_once_and_draw_physical_occurrences_independently(self):
        g = self.game(('pq-grant', 'pq-grant', 'og-group'))
        self.play(g, 'pq-grant'); self.play(g, 'pq-grant')
        inventory = tuple(g.state.players[1].player_effects)
        local = Random(); local.setstate(g._rng.getstate())
        tickets = [local.randrange(7) for _ in range(2)]
        expected = ['first-red' if t < 1 else 'middle-green' if t < 5 else 'last-red' for t in tickets]
        self.play(g, 'og-group'); root = self.root(g)
        self.assertEqual((root.producer_amount.base_count, root.producer_amount.total, root.producer_amount.family), (3, 5, 'ordered_group'))
        self.assertEqual(root.producer_amount.inventory, inventory)
        self.assertEqual([m.member_key for m in root.selection.occurrences[3:]], expected)
        self.assertEqual(root.selection.rng_after, local.getstate())
        self.assertEqual(len(root.entry_root_ids), 5)
        self.portable(g)

    def test_declared_original_positions_and_full_recipe_survive_actual_delivery(self):
        g = self.game(('og-position',), ('body',))
        self.play(g, 'og-position')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], ['red', 'green', 'red', 'body'])
        self.portable(g)
        h = self.game(('pq-grant', 'og-recipe', 'kill', 'kill'))
        self.play(h, 'pq-grant'); self.play(h, 'og-recipe')
        ids = [c.deliveries[0].entity.entity_id for c in self.children(h)]
        self.assertEqual(len(ids), 2)
        for i in ids:
            body = h.state.entities[i]
            self.assertEqual((body.attack, body.health), (7, 6))
            self.assertIn(Keyword.TAUNT, body.keywords)
            self.assertEqual(len([a for a in body.abilities if a.kind == 'deathrattle']), 1)
        for i in ids: self.play(h, 'kill', i)
        self.assertEqual(h.state.entities[h.state.players[1].hero_id].armor, 4)
        self.portable(h)

    def test_first_true_wait_preserves_amount_after_live_instance_and_source_changes(self):
        g = self.game(('pq-grant', 'og-group'), ('source', 'og-change-watch'))
        self.play(g, 'pq-grant'); inventory = tuple(g.state.players[1].player_effects)
        self.play(g, 'og-group')
        self.assertIsNotNone(g.state.pending_choice)
        accepted = self.root(g)
        self.assertEqual(accepted.producer_amount.inventory, inventory)
        self.assertEqual(accepted.producer_amount.total, 4)
        self.assertNotEqual(tuple(g.state.players[1].player_effects), inventory)
        self.resume(g, 'ok')
        self.assertEqual(self.root(g).selection, accepted.selection)
        self.assertEqual(self.root(g).producer_amount, accepted.producer_amount)
        self.assertEqual([c.plan.total for c in self.children(g)], [2, 1, 1, 1])
        self.portable(g)

    def test_extra_occurrences_each_accept_existing_child_quantity_without_recursive_expansion(self):
        g = self.game(('pq-grant', 'og-group'), ('source',))
        self.play(g, 'pq-grant'); self.play(g, 'og-group')
        root = self.root(g)
        self.assertEqual(root.producer_amount.total, 4)
        self.assertEqual([c.plan.total for c in self.children(g)], [2, 2, 2, 2])
        self.assertEqual(sum(len(c.deliveries) for c in self.children(g)), 8)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.portable(g)

    def test_later_child_strength_has_its_own_changed_window(self):
        g = self.game(('pq-grant', 'pq-herald', 'og-scale'), ('source', 'pq-strength-watch'), hero='mage_hero')
        self.play(g, 'pq-grant'); self.play(g, 'pq-herald'); self.play(g, 'og-scale')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.root(g).producer_amount.total, 3)
        self.resume(g, 'ok')
        self.assertEqual([(c.entry_strength.count, c.plan.total) for c in self.children(g)], [(2, 2), (4, 1), (4, 1)])
        self.portable(g)

    def test_cause_player_and_delivery_recipient_have_separate_inventories(self):
        g = self.game(('pq-grant', 'pq-grant-enemy', 'og-enemy'))
        self.play(g, 'pq-grant'); inventory = tuple(g.state.players[1].player_effects)
        self.play(g, 'pq-grant-enemy'); self.play(g, 'og-enemy')
        root = self.root(g)
        self.assertEqual((root.request.group.cause.player_id, root.request.group.player_id), (1, 2))
        self.assertEqual(root.producer_amount.inventory, inventory)
        self.assertEqual((root.producer_amount.recipient_id, root.producer_amount.total), (2, 4))
        self.assertEqual((len(g.state.players[1].board), len(g.state.players[2].board)), (0, 4))
        self.portable(g)

    def test_explicit_source_origin_filter_and_unqualified_power_remain_distinct(self):
        for card, expected in (('og-card-filter', 3), ('og-caller', 4)):
            g = self.game(('pq-grant', card)); self.play(g, 'pq-grant'); self.play(g, card)
            self.assertEqual(self.root(g).producer_amount.total, expected)
            self.portable(g)
        g = self.game(('pq-grant',), power='og-power')
        self.play(g, 'pq-grant'); g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        self.assertEqual((self.root(g).request.group.cause.origin, self.root(g).producer_amount.total), ('hero_power', 3))
        self.portable(g)

    def test_nested_group_and_mixed_pool_group_keep_disjoint_parent_child_namespaces(self):
        g = self.game(('og-group',), ('og-nested',))
        self.play(g, 'og-group')
        outer, inner = g.state.ordered_group_history
        self.assertTrue(set(outer.entry_root_ids).isdisjoint(inner.entry_root_ids))
        self.assertEqual((len(outer.entry_root_ids), len(inner.entry_root_ids)), (3, 1))
        self.portable(g)
        h = self.game(('pq-grant', 'pq-batch'), ('og-pool-auto',))
        self.play(h, 'pq-grant'); self.play(h, 'pq-batch')
        pool, group = h.state.pool_summon_history[0], self.root(h)
        self.assertEqual((pool.id, group.id), (1, 1))
        self.assertEqual((pool.producer_amount.family, group.producer_amount.family), ('pool', 'ordered_group'))
        self.assertTrue(set(pool.entry_root_ids).isdisjoint(group.entry_root_ids))
        self.assertEqual(group.producer_amount.source_kind, CardType.SPELL)
        self.assertEqual(group.request.group.cause.source.card_id, 'og-spell-group')
        cast = next(c for c in h.state.cast_history if c.id == group.request.group.cause.cast_id)
        self.assertEqual(cast.source_id, group.request.group.cause.source.entity_id)
        self.assertEqual(h.state.entities[cast.caster_id].card_id, 'og-pool-auto')
        self.assertNotEqual(cast.source_id, cast.caster_id)
        self.assertEqual(group.request.group.cause.cast_card_id, 'og-spell-group')
        self.portable(h)

    def test_full_board_retains_complete_selected_group_and_all_failed_attempts(self):
        g = self.game(('pq-grant', 'og-group'), ('red',) * 7)
        self.play(g, 'pq-grant'); self.play(g, 'og-group')
        root = self.root(g)
        self.assertEqual((len(root.selection.occurrences), len(root.entry_root_ids)), (4, 4))
        self.assertEqual([[d.outcome for d in c.deliveries] for c in self.children(g)], [['board_full']] * 4)
        self.assertEqual(root.status, 'completed')
        self.portable(g)

    def test_later_member_uses_space_freed_after_the_first_actual_delivery(self):
        g = self.game(('pq-grant', 'og-group'), ('og-free-space',) + ('red',) * 5)
        removed = next(i for i in g.state.players[1].board if g.state.entities[i].card_id == 'red')
        self.play(g, 'pq-grant'); self.play(g, 'og-group')
        self.assertIsNotNone(g.state.pending_choice)
        accepted = self.root(g)
        self.assertEqual((len(g.state.players[1].board), len(accepted.entry_root_ids)), (6, 1))
        self.assertNotIn(removed, g.state.players[1].board)
        self.resume(g, 'ok')
        self.assertEqual(self.root(g).selection, accepted.selection)
        self.assertEqual([[d.outcome for d in c.deliveries] for c in self.children(g)],
                         [['delivered'], ['delivered'], ['board_full'], ['board_full']])
        self.assertEqual((len(g.state.players[1].board), self.root(g).status), (7, 'completed'))
        self.portable(g)

    def test_empty_original_group_is_rng_neutral_and_unsupported_policies_roll_back(self):
        g = self.game(('og-empty',)); before = g._rng.getstate(); self.play(g, 'og-empty')
        self.assertEqual((self.root(g).selection.occurrences, self.root(g).entry_root_ids, self.root(g).status), ((), (), 'completed'))
        self.assertEqual(g._rng.getstate(), before); self.portable(g)
        for card in ('og-unknown', 'og-bad-mode', 'og-disallow-extra', 'og-no-extra-domain'):
            h = self.game(('pq-grant', card), ('red',) * 7)
            self.play(h, 'pq-grant'); saved = h.snapshot()
            with self.assertRaises(ValueError): self.play(h, card)
            self.assertEqual(h.snapshot(), saved)
            self.portable(h)

    def test_waiting_public_request_restores_before_any_group_root_is_accepted(self):
        g = self.game(('pq-grant', 'og-wait-before'))
        self.play(g, 'pq-grant'); self.play(g, 'og-wait-before')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.ordered_group_history, [])
        self.resume(g, 'ok')
        self.assertEqual(self.root(g).producer_amount.total, 4)
        self.portable(g)

    def test_actual_retry_keeps_monotonic_group_ids_and_retired_receipts(self):
        g = self.game(('pq-grant', 'og-retry'))
        self.play(g, 'pq-grant'); self.play(g, 'og-retry')
        old = self.root(g); self.assertIsNotNone(g.state.pending_choice)
        self.resume(g, 'retry')
        self.assertEqual(len(g.state.ordered_group_history), 1)
        new = self.root(g)
        self.assertGreater(new.id, old.id)
        self.assertGreater(min(new.entry_root_ids), max(old.entry_root_ids))
        self.assertEqual(new.producer_amount.inventory, old.producer_amount.inventory)
        self.assertIsNone(g.state.pending_choice)
        self.portable(g)

    def test_actual_retry_retired_close_cannot_erase_an_old_delivered_child(self):
        g = self.game(('pq-grant', 'og-retry'))
        self.play(g, 'pq-grant'); self.play(g, 'og-retry')
        old_id = self.root(g).id
        self.resume(g, 'retry'); saved = self.portable(g)
        bad = deepcopy(saved)
        event = next(e for e in bad['events'] if e['kind'] == 'ordered_group_finished'
                     and e['data']['group_id'] == old_id)
        retired = json.loads(event['data']['root'])
        retired['entry_root_ids'].pop()
        retired['status'] = 'interrupted'
        event['amount'] = len(retired['entry_root_ids'])
        event['data']['root'] = json.dumps(retired, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        self.reject(bad, 'crop-retired-actual-child')

    def test_terminal_interrupt_retains_actual_prefix_and_stops_later_group_entries(self):
        g = self.game(('pq-grant', 'og-group'), ('source', 'fatal_watcher'))
        self.play(g, 'pq-grant'); self.play(g, 'og-group')
        root = self.root(g)
        self.assertEqual((g.state.status, root.status, len(root.entry_root_ids)), ('finished', 'interrupted', 1))
        self.assertEqual((self.children(g)[0].status, len(self.children(g)[0].deliveries)), ('interrupted', 1))
        self.assertEqual(len(root.selection.occurrences), 4)
        self.portable(g)

    def test_rng_exception_budget_and_injected_control_preserve_atomic_state(self):
        for grant, card in (('pq-grant', 'og-fail-after'), ('pq-grant-large', 'og-group'), ('pq-grant', 'og-inject')):
            g = self.game((grant, card)); self.play(g, grant); before = g.snapshot()
            with self.assertRaises(ValueError): self.play(g, card)
            self.assertEqual(g.snapshot(), before)
            self.portable(g)
        h = self.game(('og-group',), ('og-watch',)); self.play(h, 'og-group')
        self.assertIsNotNone(h.state.pending_choice); before = self.portable(h)
        with self.assertRaises(ValueError): self.choose(h, 'bad')
        self.assertEqual(h.snapshot(), before)
        self.resume(h, 'ok'); self.portable(h)

    def test_rehashed_selection_amount_and_cross_family_link_changes_reject(self):
        g = self.game(('pq-grant', 'og-group'), ('og-watch',))
        self.play(g, 'pq-grant'); self.play(g, 'og-group'); saved = self.portable(g)
        for case in ('family', 'amount-inventory', 'original-member', 'selected-member', 'position', 'rng', 'group-link', 'pool-link'):
            bad = deepcopy(saved); root = bad['state']['ordered_group_history'][0]
            if case == 'family': root['producer_amount']['family'] = 'pool'
            elif case == 'amount-inventory': root['producer_amount']['inventory'] = []
            elif case == 'original-member': root['request']['group']['members'][0]['occurrence_key'] = 'forged'
            elif case == 'selected-member': root['selection']['occurrences'][0]['member_key'] = 'last-red'
            elif case == 'position': root['selection']['occurrences'][0]['position'] = 2
            elif case == 'rng': root['selection']['rng_after'][1][2] ^= 1
            else:
                child = next(c for c in bad['state']['card_summon_history'] if c['id'] == root['entry_root_ids'][0])
                child['request']['producer_link'] = ({'group_id': 2, 'index': 0} if case == 'group-link' else {'batch_id': 1, 'index': 0})
            self.reject(bad, case)

    def test_locally_coherent_extra_removal_is_rejected_by_original_accepted_event(self):
        g = self.game(('pq-grant', 'og-group'), ('og-watch',))
        self.play(g, 'pq-grant'); self.play(g, 'og-group'); saved = self.portable(g)
        bad = deepcopy(saved); root = bad['state']['ordered_group_history'][0]
        root['producer_amount']['inventory'] = []
        root['producer_amount']['decisions'] = []
        root['producer_amount']['total'] = 3
        root['selection']['additional'] = 0
        root['selection']['occurrences'] = root['selection']['occurrences'][:3]
        root['selection']['rng_after'] = deepcopy(root['selection']['rng_before'])
        forged = group_from_dict(OrderedGroupRecord, root)
        # The modified root is locally consistent; the original acceptance proves otherwise.
        validate_group_record(g.state, g.registry, forged)
        shadow = Game.from_snapshot(deepcopy(saved), registry())
        shadow._state.ordered_group_history[0] = forged
        with self.assertRaisesRegex(ValueError, 'original private event proof'):
            validate_closed_events(shadow)
        self.reject(bad, 'coherent-extra-removal')

    def test_rehashed_group_next_and_finish_queue_truncation_reject(self):
        g = self.game(('og-group',), ('og-watch',)); self.play(g, 'og-group'); saved = self.portable(g)
        for kind in ('StartOrderedGroupEntry', 'FinishOrderedGroup'):
            bad = deepcopy(saved); tail = bad['resolution_frame']['fields']['continuation']['tuple']
            tail.pop(next(i for i, w in enumerate(tail) if w.get('type', '').endswith('.' + kind)))
            self.reject(bad, 'crop-' + kind)
        bad = deepcopy(saved); tail = bad['resolution_frame']['fields']['continuation']['tuple']
        controls = [i for i, w in enumerate(tail) if any(w.get('type', '').endswith('.' + kind)
                    for kind in ('StartOrderedGroupEntry', 'FinishOrderedGroup'))]
        self.assertEqual(len(controls), 2)
        a, b = controls
        tail[a], tail[b] = tail[b], tail[a]
        self.reject(bad, 'reverse-next-finish')
        self.resume(g, 'ok'); closed = self.portable(g)
        bad = deepcopy(closed); bad['state']['ordered_group_history'][0]['entry_root_ids'].pop()
        self.reject(bad, 'crop-closed-child-prefix')


if __name__ == '__main__':
    unittest.main()
