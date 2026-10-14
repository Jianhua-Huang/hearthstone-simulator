"""Paid cost history across real DR, power and end-turn parent windows.

Only default actions and public effects produce these windows. Adversarial
states first pass compact invariants, then must fail their still-live proof.
These synthetic tests do not establish official timing or CAST coverage.
"""
import copy
import json
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, CostSpec, EndTurn,
    EndTurnSpec, Game, PlayCard, PlayerSetup, Registry, RepeatCostFilter,
    RepeatMatchSpec, RecipientMetadataFilter, Scenario, SelectChoice,
    SnapshotError, SpellRepeatSpec, SpellSchool, TriggerSpec, UseHeroPower)
from hs_sim.engine.effects import (AddCostModifier, ChoiceOption, GainArmor,
    RequestChoice, TriggerDeathrattles)
from hs_sim.engine.end_turns import TriggerEndTurnEffects
from hs_sim.engine.hero_powers import TriggerHeroPower
from hs_sim.engine.model import EndTurnRequest, EndTurnSelector, validate_invariants
from hs_sim.engine.payment_projection import validate_cost_source_history
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import PlayFromHand
from hs_sim.engine.serialization import canonical_hash, state_from_dict
from hs_sim.engine.spell_modifiers import AddSpellRepeatModifier, RemoveSpellRepeatModifier
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.spell_acceptance import FinishSpellAcceptance, _bind_foreign_windows


PROFILE = 'repeat.cost.accepted_hand'
FINISH = {'deathrattle': 'FinishDeathrattleBatch',
    'hero_power': 'FinishHeroPower', 'end_turn': 'FinishEndTurnBatch'}


def ask(context, *effects, prompt='Continue'):
    return RequestChoice(context.player_id,
        (ChoiceOption('ok', 'Continue', tuple(effects)),),
        source_id=context.source_id, prompt=prompt)


def build_registry():
    registry = Registry('fee-foreign-windows-public-v1')
    registry.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
    registry.register_behavior('armor', lambda c: [GainArmor(c.player_id, 1)])
    registry.register_behavior('wait', lambda c: [ask(c, GainArmor(c.player_id, 1))])

    def setup(context):
        return [AddCostModifier(context.player_id,
            CostSpec(delta=-1, card_types=(CardType.SPELL,),
                card_ids=('child.first', 'child.second')),
            uses_remaining=2, source_id=context.source_id),
            AddSpellRepeatModifier(context.player_id, SpellRepeatSpec(2, 'any',
                RepeatMatchSpec(recipient_metadata=RecipientMetadataFilter(
                    spell_schools=(SpellSchool.FIRE,)))), source_id=context.source_id)]

    def parent(context):
        children = [next(i for i in context.state.players[context.player_id].hand
            if context.state.entities[i].card_id == card_id)
            for card_id in ('child.first', 'child.second')]
        # These are two distinct subsequent external SelectChoice actions.
        # A complete parent stays alive after both child's paid roots close.
        foreign_id = context.state.players[context.player_id].spell_modifiers[0].id
        return [ask(context, RemoveSpellRepeatModifier(context.player_id, foreign_id),
                    PlayFromHand(PlayCard(context.player_id, children[0])),
                    prompt='First paid child'),
            ask(context, PlayFromHand(PlayCard(context.player_id, children[1])),
                    prompt='Second paid child'),
            ask(context, GainArmor(context.player_id, 1), prompt='Parent tail')]

    registry.register_behavior('setup', setup)
    registry.register_behavior('parent', parent)
    registry.register_card(CardDefinition('setup', 'Setup', CardType.SPELL, on_play='setup'))
    for card_id in ('child.first', 'child.second'):
        registry.register_card(CardDefinition(card_id, card_id, CardType.SPELL,
            cost=2, on_play='armor', spell_school=SpellSchool.ARCANE))
    registry.register_card(CardDefinition('dr.parent', 'DR parent', CardType.MINION,
        attack=1, health=1, deathrattle='parent'))
    registry.register_card(CardDefinition('defender', 'Defender', CardType.MINION,
        attack=2, health=3))
    registry.register_card(CardDefinition('power.parent', 'Power parent', CardType.HERO_POWER,
        cost=1, on_use='parent'))
    registry.register_card(CardDefinition('end.parent', 'End parent', CardType.MINION,
        health=4, triggers=(TriggerSpec('turn_ended', 'parent', EndTurnSpec()),)))
    registry.register_card(CardDefinition('plain', 'Plain', CardType.MINION, health=4))

    # Demand both accepted-hand facts while remaining false on the Arcane root.
    false_match = RepeatMatchSpec(
        recipient_metadata=RecipientMetadataFilter(spell_schools=(SpellSchool.FIRE,)),
        recipient_cost=RepeatCostFilter('window_quote', maximum=10, quote_profile_id=PROFILE))
    false_spec = SpellRepeatSpec(2, 'any', false_match)
    registry.register_behavior('fee.setup', lambda c: [AddSpellRepeatModifier(
        c.player_id, false_spec, source_id=c.source_id)])
    registry.register_card(CardDefinition('fee.setup', 'Fee setup', CardType.SPELL,
        on_play='fee.setup'))
    registry.register_card(CardDefinition('fee.donor', 'False fee donor', CardType.MINION,
        health=4, spell_repeats=(false_spec,)))
    registry.register_card(CardDefinition('dr.child', 'DR child', CardType.MINION,
        health=4, deathrattle='wait'))
    registry.register_card(CardDefinition('power.child', 'Power child', CardType.HERO_POWER,
        cost=1, on_use='wait'))
    registry.register_card(CardDefinition('end.child', 'End child', CardType.MINION,
        health=4, triggers=(TriggerSpec('turn_ended', 'wait', EndTurnSpec()),)))

    for family in FINISH:
        def payload(context, selected=family):
            if selected == 'deathrattle':
                target = next(i for i in context.state.players[context.player_id].board
                    if context.state.entities[i].card_id == 'dr.child')
                effect = TriggerDeathrattles(target, context.source_id)
            elif selected == 'hero_power':
                effect = TriggerHeroPower(context.player_id, context.source_id,
                    targeting='explicit', choices='player')
            else:
                target = next(i for i in context.state.players[context.player_id].board
                    if context.state.entities[i].card_id == 'end.child')
                request = EndTurnRequest(EndTurnSelector('selected',
                    (context.player_id,), ('minion',), (target,)))
                effect = TriggerEndTurnEffects(context.player_id, request, context.source_id)
            return [ask(context, effect, prompt='Open later typed child'),
                ask(context, GainArmor(context.player_id, 1), prompt='Fee parent tail')]
        behavior = 'fee.parent.' + family
        registry.register_behavior(behavior, payload)
        registry.register_card(CardDefinition(behavior, behavior, CardType.SPELL,
            cost=2, on_play=behavior, spell_school=SpellSchool.ARCANE))
    return registry


class CostForeignWindowTests(unittest.TestCase):
    def game(self, *, board=(), enemy=(), hand=(), power=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', board=board, hand=hand, hero_power_card_id=power,
                deck=('plain',) * 5, mana=10, max_mana=10),
            PlayerSetup('hero', board=enemy, deck=('plain',) * 5,
                mana=10, max_mana=10)), seed=116), build_registry())

    def find(self, game, card_id, *, player=1, zone='hand'):
        return next(i for i in getattr(game.state.players[player], zone)
            if game.state.entities[i].card_id == card_id)

    def choose(self, game):
        choice = game.state.pending_choice
        self.assertIsNotNone(choice)
        game.apply(SelectChoice(choice.player_id, choice.id, ('ok',)))

    def nodes(self, value, name):
        result = []
        def walk(item):
            if isinstance(item, dict):
                if item.get('type', '').split('.')[-1] == name:
                    result.append(item)
                for key, child in item.items():
                    if key == 'fields' and item.get('type') == 'hs_sim.engine.paid_hand_acceptance.PaidHandChoiceBoundaryProof':
                        for field, operand in child.items():
                            if field != 'work':
                                walk(operand)
                    else:
                        walk(child)
            elif isinstance(item, list):
                for child in item:
                    walk(child)
        walk(value)
        return result

    def portable(self, game):
        snapshot = json.loads(json.dumps(game.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot, build_registry()).snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), build_registry()).snapshot(), snapshot)

    def reject(self, snapshot):
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(snapshot, build_registry())

    def parent_fixture(self, family):
        board = ('dr.parent',) if family == 'deathrattle' else (
            ('end.parent',) if family == 'end_turn' else ())
        game = self.game(board=board,
            enemy=('defender',) if family == 'deathrattle' else (),
            hand=('setup', 'child.first', 'child.second'),
            power='power.parent' if family == 'hero_power' else None)
        game.apply(PlayCard(1, self.find(game, 'setup')))
        modifier = game.state.players[1].cost_modifiers[0]
        self.assertEqual(modifier.uses_remaining, 2)
        if family == 'deathrattle':
            game.apply(Attack(1, self.find(game, 'dr.parent', zone='board'),
                self.find(game, 'defender', player=2, zone='board')))
        elif family == 'hero_power':
            game.apply(UseHeroPower(1, game.state.players[1].hero_power_id))
        else:
            game.apply(EndTurn(1))
        parent = self.nodes(game.snapshot()['resolution_frame'], FINISH[family])
        self.assertEqual(len(parent), 1)
        original = parent[0]['fields']['context']['fields']['state']['state']
        original_modifier = original['players']['1']['cost_modifiers'][0]
        self.assertEqual(original_modifier['uses_remaining'], 2)
        self.assertEqual(game.state.pending_choice.prompt, 'First paid child')
        self.portable(game)
        self.choose(game)
        self.assertEqual(game.state.players[1].cost_modifiers[0].uses_remaining, 1)
        self.assertEqual(game.state.pending_choice.prompt, 'Second paid child')
        self.portable(game)
        self.choose(game)
        self.assertFalse(game.state.players[1].cost_modifiers)
        self.assertFalse(game.state.players[1].spell_modifiers)
        self.assertEqual(game.state.pending_choice.prompt, 'Parent tail')
        self.assertEqual(len(self.nodes(game.snapshot()['resolution_frame'], FINISH[family])), 1)
        self.assertFalse(self.nodes(game.snapshot()['resolution_frame'], 'FinishSpellAcceptance'))
        children = [p for p in game.state.play_history if p.card_id.startswith('child.')]
        self.assertEqual([p.cost for p in children], [1, 1])
        self.assertTrue(all(p.completed and p.spell_acceptance_closed for p in children))
        self.assertNotEqual(children[0].action, children[1].action)
        uses = [r for r in game.state.cost_use_history if r.player_modifiers]
        self.assertEqual([r.player_modifiers[0].uses_remaining for r in uses], [2, 1])
        self.portable(game)
        return game, modifier.id, original

    def finish_parent(self, game, family):
        self.choose(game)
        self.assertIsNone(game.state.pending_choice)
        self.assertFalse(self.nodes(game.snapshot()['resolution_frame'], FINISH[family]))
        self.portable(game)

    def edit_modifier(self, value, identity, edit):
        changed = 0
        def walk(item):
            nonlocal changed
            if isinstance(item, dict):
                if (item.get('id') == identity and
                        {'spec', 'scope', 'uses_remaining', 'source_id', 'expires_turn'} <= item.keys()):
                    edit(item)
                    changed += 1
                for child in tuple(item.values()):
                    walk(child)
            elif isinstance(item, list):
                for child in item:
                    walk(child)
        walk(value)
        return changed

    def parent_clock_rejection(self, family, *, change_spec=False):
        game, identity, original = self.parent_fixture(family)
        snapshot = copy.deepcopy(game.snapshot())
        def alter(modifier):
            if change_spec:
                modifier['spec']['card_ids'] = []
            else:
                modifier['uses_remaining'] += 1
        self.assertGreaterEqual(self.edit_modifier(snapshot['state'], identity, alter), 4)
        # Complete quote facts, exact child ledger chains and resource accounting
        # remain compact-valid. The live parent supplies the missing old seed.
        current = state_from_dict(snapshot['state'])
        registry = build_registry()
        validate_invariants(current, registry)
        before = state_from_dict(original)
        with self.assertRaisesRegex(ValueError, 'Cost|cost'):
            validate_cost_source_history(before, current, registry)
        self.reject(snapshot)
        self.finish_parent(game, family)

    def test_natural_death_parent_paid_children_and_last_use_removal_are_portable(self):
        game, _, _ = self.parent_fixture('deathrattle')
        self.assertEqual(game.state.deathrattle_history[-1].capture.origin, 'death')
        self.finish_parent(game, 'deathrattle')

    def test_manual_power_parent_paid_children_and_last_use_removal_are_portable(self):
        game, _, _ = self.parent_fixture('hero_power')
        self.assertEqual(game.state.hero_power_history[-1].origin, 'manual')
        self.finish_parent(game, 'hero_power')

    def test_natural_end_parent_paid_children_and_last_use_removal_are_portable(self):
        game, _, _ = self.parent_fixture('end_turn')
        self.assertEqual(game.state.end_turn_batches[-1].activation.kind, 'natural')
        self.finish_parent(game, 'end_turn')

    def test_death_parent_rejects_gone_false_cost_source_clock_rewrite(self):
        self.parent_clock_rejection('deathrattle')

    def test_power_parent_rejects_gone_false_cost_source_clock_rewrite(self):
        self.parent_clock_rejection('hero_power')

    def test_end_parent_rejects_gone_false_cost_source_clock_rewrite(self):
        self.parent_clock_rejection('end_turn')

    def test_death_parent_rejects_gone_false_cost_source_complete_spec_rewrite(self):
        self.parent_clock_rejection('deathrattle', change_spec=True)

    def test_power_parent_rejects_gone_false_cost_source_complete_spec_rewrite(self):
        self.parent_clock_rejection('hero_power', change_spec=True)

    def test_end_parent_rejects_gone_false_cost_source_complete_spec_rewrite(self):
        self.parent_clock_rejection('end_turn', change_spec=True)

    def parent_family_rejection(self, family):
        game, identity, original = self.parent_fixture(family)
        borrowed = original['players']['1']['spell_modifiers'][0]['id']
        self.assertNotEqual(identity, borrowed)
        snapshot = copy.deepcopy(game.snapshot())
        self.assertGreaterEqual(self.edit_modifier(snapshot['state'], identity,
            lambda modifier: modifier.update(id=borrowed)), 4)
        changed_lists = 0
        def remap(item):
            nonlocal changed_lists
            if isinstance(item, dict):
                for key, value in item.items():
                    if key in ('modifier_ids', 'consumable_ids') and identity in value:
                        item[key] = [borrowed if i == identity else i for i in value]
                        changed_lists += 1
                    else:
                        remap(value)
            elif isinstance(item, list):
                for value in item:
                    remap(value)
        remap(snapshot['state'])
        self.assertGreaterEqual(changed_lists, 8)
        current, before = state_from_dict(snapshot['state']), state_from_dict(original)
        registry = build_registry()
        validate_invariants(current, registry)
        with self.assertRaisesRegex(ValueError, 'foreign attachment identity'):
            validate_cost_source_history(before, current, registry)
        self.reject(snapshot)
        self.finish_parent(game, family)

    def test_death_parent_rejects_later_cost_use_borrowing_gone_false_spell_policy_id(self):
        self.parent_family_rejection('deathrattle')

    def test_power_parent_rejects_later_cost_use_borrowing_gone_false_spell_policy_id(self):
        self.parent_family_rejection('hero_power')

    def test_end_parent_rejects_later_cost_use_borrowing_gone_false_spell_policy_id(self):
        self.parent_family_rejection('end_turn')

    def fee_parent_fixture(self, family):
        board = ('fee.donor',) + (('dr.child',) if family == 'deathrattle' else (
            ('end.child',) if family == 'end_turn' else ()))
        card_id = 'fee.parent.' + family
        game = self.game(board=board, hand=('fee.setup', card_id),
            power='power.child' if family == 'hero_power' else None)
        game.apply(PlayCard(1, self.find(game, 'fee.setup')))
        game.apply(PlayCard(1, self.find(game, card_id)))
        play = game.state.play_history[-1]
        self.assertIsNotNone(play.spell_submission.cost_facts)
        self.assertIsNotNone(play.spell_payload.cost_facts)
        self.assertEqual(play.spell_payload.casts, 1)
        self.assertFalse(play.spell_submission.modifiers)
        self.assertFalse(play.spell_payload.contributors)
        self.portable(game)
        self.choose(game)
        self.assertEqual(game.state.pending_choice.source_id,
            game.state.hero_power_history[-1].source_id if family == 'hero_power' else
            self.find(game, 'dr.child' if family == 'deathrattle' else 'end.child', zone='board'))
        self.assertEqual(len(self.nodes(game.snapshot()['resolution_frame'], FINISH[family])), 1)
        self.assertEqual(len(self.nodes(game.snapshot()['resolution_frame'], 'FinishSpellAcceptance')), 1)
        self.portable(game)
        return game, play.id

    def late_child_rejection(self, family):
        game, play_id = self.fee_parent_fixture(family)
        for phase in ('spell_submission', 'spell_payload'):
            with self.subTest(phase=phase):
                snapshot = copy.deepcopy(game.snapshot())
                marker = self.nodes(snapshot['resolution_frame'], FINISH[family])[0]
                # Select the actual complete later typed Finish original window;
                # neither an ordinary callback nor the older fee parent window.
                original = marker['fields']['context']['fields']['state']['state']
                parent = next(p for p in original['play_history'] if p['id'] == play_id)
                self.assertIsNotNone(parent['spell_submission'])
                self.assertIsNotNone(parent['spell_payload'])
                facts = parent[phase]['cost_facts']
                self.assertEqual(len(facts['window_quotes']), 1)
                facts['cost_input']['base_cost'] += 1
                facts['local_amount'] += 1
                facts['intrinsic']['base_cost'] += 1
                facts['intrinsic']['amount'] += 1
                for quote in facts['window_quotes']:
                    quote['quote_input']['base_cost'] += 1
                    quote['local_amount'] += 1
                    quote['amount'] += 1
                    quote['intrinsic']['base_cost'] += 1
                    quote['intrinsic']['amount'] += 1
                validate_invariants(state_from_dict(original), build_registry())
                # Decode the actual child proof independently: it remains a
                # well-typed, compact-valid accepted child. The still-live fee
                # parent must bind its accepted facts in this later original.
                registry = build_registry()
                child = FrameCodec(game.mechanics, registry).decode(marker)
                proofs = [work for work in (*game._frame.prefix, *game._frame.continuation)
                    if type(work) is FinishSpellAcceptance]
                self.assertEqual([proof.play_id for proof in proofs], [play_id])
                with self.assertRaisesRegex(ValueError,
                        'accepted receipt|durable root|existing full hand root'):
                    _bind_foreign_windows(registry, proofs, child)
                self.reject(snapshot)
        self.choose(game)
        self.assertEqual(game.state.pending_choice.prompt, 'Fee parent tail')
        self.portable(game)
        self.choose(game)
        self.assertIsNone(game.state.pending_choice)
        self.portable(game)

    def test_later_death_finish_original_binds_both_parent_fee_acceptance_facts(self):
        self.late_child_rejection('deathrattle')

    def test_later_power_finish_original_binds_both_parent_fee_acceptance_facts(self):
        self.late_child_rejection('hero_power')

    def test_later_end_finish_prebatch_original_binds_both_parent_fee_acceptance_facts(self):
        self.late_child_rejection('end_turn')


if __name__ == '__main__':
    unittest.main()
