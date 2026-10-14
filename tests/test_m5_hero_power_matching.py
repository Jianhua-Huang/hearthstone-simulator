"""B2-04 source-only Hero Power matching through real activation roots.

Synthetic contracts are not CN calibration. Empty/multiple on_use fixtures use
an explicitly registered test dispatcher; the native example uses default effects.
"""
import copy
import json
import unittest
from dataclasses import dataclass, replace
from unittest.mock import patch

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, EndTurnSpec, Game, HeroPowerReference, IllegalAction, Keyword,
    LimitedTriggerSpec, PlayCard, PlayerEffectSpec, PlayerSetup, Registry, ResolutionError,
    ResolutionLimitExceeded, RewindSpec, Ruleset, Scenario, SelectChoice,
    SnapshotError, SpellRepeatSpec, TriggerHeroPower, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, Effect, GainArmor, InvokeBehavior, RandomDamage, ReplaceHeroPower,
    RequestChoice, ReturnToHand, Silence, Summon, Transform, TriggerDeathrattles,
    RefreshHeroPower, SetHeroPowerUses)
from hs_sim.engine.hero_power_repeats import (GrantHeroPowerRepeatAura,
    capture_plan, validate_plan)
from hs_sim.engine.hero_powers import (AddHeroPower, FinishHeroPower,
    RemoveHeroPower, hero_power_references)
from hs_sim.engine.lifecycle import attachment_id
from hs_sim.engine.model import (AbilityInstance, BattlecryRepeatSpec,
    ComboRepeatSpec, DeathrattleRepeatSpec, EndTurnRequest, EndTurnSelector,
    HeroPowerRepeatMatchSpec, HeroPowerRepeatPlan, HeroPowerRepeatSpec,
    DamageKind, HealthFlow, HealthOp, HealthRule, RepeatSourceEligibility, RepeatWitnessProfile)
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.end_turns import TriggerEndTurnEffects
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import EndTurnPhase, PlayFromHand, default_mechanics
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.player_effects import AddPlayerEffect, RemovePlayerEffect, TickPlayerEffect


def metadata(tribes=()):
    return CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=tribes)


def condition(tribes=('beast',), *, another=True, profile='repeat.witness.controlled'):
    return RepeatSourceEligibility(profile, tribes_any=tribes, exclude_carrier=another)


def spec(count=2, eligibility=None):
    return HeroPowerRepeatSpec(count, match=None if eligibility is None else
        HeroPowerRepeatMatchSpec(source_eligibility=eligibility))


def ask(c, *effects):
    return RequestChoice(c.player_id, (ChoiceOption('ok', 'Resolve', tuple(effects)),),
        source_id=c.source_id)


def fixture_registry():
    r = Registry('hero-power-matching-public-fixtures-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30,
        metadata=metadata()))
    r.register_behavior('armor', lambda c: [GainArmor(c.player_id, 1)])
    r.register_behavior('wait', lambda c: [ask(c, GainArmor(c.player_id, 1))])
    r.register_behavior('noop', lambda c: [])
    for name, body in (('power', 'armor'), ('waiting', 'wait'), ('noop.power', 'noop')):
        r.register_card(CardDefinition(name, name, CardType.HERO_POWER, cost=2, on_use=body))
    for name, tribes in (('plain', ()), ('beast', ('beast',)), ('dragon', ('dragon',)),
            ('multi', ('beast', 'dragon')), ('all', ('all',)), ('unknown.tribes', None)):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=6,
            metadata=metadata(tribes)))
    r.register_card(CardDefinition('unknown.metadata', 'Unknown', CardType.MINION, health=6))
    r.register_card(CardDefinition('retainer', 'Retainer', CardType.MINION, health=6,
        retain_rewind_outcomes=True, metadata=metadata()))
    for name, count, eligibility in (('two', 2, None), ('three', 3, None),
            ('conditional.two', 2, condition()), ('conditional.three', 3, condition()),
            ('false.source', 5, condition(('dragon',)))):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=6,
            hero_power_repeats=(spec(count, eligibility),), metadata=metadata()))
    return r


@dataclass(frozen=True)
class InstallTestPowerPayloads(Effect):
    """Explicit custom dispatcher extension, not a default gameplay mechanic."""
    target_id: int
    behaviors: tuple[str, ...]
    clear_existing: bool = False
    consumed_indices: tuple[int, ...] = ()
    expires_turn: int | None = None


def install_test_power_payloads(r, effect):
    power = r.state.entities[effect.target_id]
    if effect.clear_existing:
        power.abilities = [a for a in power.abilities if a.kind != 'on_use']
    for index, behavior in enumerate(effect.behaviors):
        r.registry.behavior(behavior)
        power.abilities.append(AbilityInstance(attachment_id(r.state), 'on_use',
            behavior_id=behavior, consumed=index in effect.consumed_indices,
            expires_turn=effect.expires_turn))


class HeroPowerMatchingTests(unittest.TestCase):
    def setUp(self):
        self.r = fixture_registry()
        self.entries = []
        self.custom = False
        self.script('trigger', lambda c: [TriggerHeroPower(c.player_id, c.source_id,
            targeting='explicit', choices='player')])
        self.script('grant.false', lambda c: [GrantHeroPowerRepeatAura(
            c.state.players[c.player_id].board[0], spec(5, condition(('dragon',))), c.source_id)])

    def install(self, kind, *values):
        getattr(self.r, 'register_' + kind)(*values)
        self.entries.append((kind, values))

    def fresh(self):
        registry = fixture_registry()
        for kind, values in self.entries:
            getattr(registry, 'register_' + kind)(*values)
        self.assertEqual(registry.fingerprint(), self.r.fingerprint())
        return registry

    def mechanics(self):
        if not self.custom:
            return None
        mechanics = default_mechanics('hero-power-matching-custom-fixtures-v1')
        mechanics.register(InstallTestPowerPayloads, install_test_power_payloads)
        return mechanics

    def behavior(self, name, body):
        self.install('behavior', name, body)

    def power(self, name, body, **fields):
        self.behavior(name, body)
        fields.setdefault('cost', 2)
        self.install('card', CardDefinition(name, name, CardType.HERO_POWER,
            on_use=name, **fields))

    def minion(self, name, **fields):
        fields.setdefault('health', 6)
        fields.setdefault('metadata', metadata())
        self.install('card', CardDefinition(name, name, CardType.MINION, **fields))

    def source(self, name, declaration, **fields):
        self.minion(name, hero_power_repeats=(declaration,), **fields)

    def script(self, name, body, *, target=False, **fields):
        self.behavior(name, body)
        fields.setdefault('cost', 1)
        self.install('card', CardDefinition(name, name, CardType.SPELL,
            on_play=name, requires_target=target, metadata=metadata(), **fields))

    def watch(self, name, body, event, **fields):
        self.behavior(name, body)
        self.minion(name, triggers=(TriggerSpec(event, name),), **fields)

    def game(self, *, power='power', board=(), enemy=(), hand=(), extras=(), deck=('plain',) * 5,
             mana=10, rules=None, seed=114):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=deck,
                hero_power_card_id=power, additional_hero_power_card_ids=extras,
                mana=mana, max_mana=10),
            PlayerSetup('hero', hand=('plain',), board=enemy, deck=('plain',) * 5,
                hero_power_card_id='power', mana=10, max_mana=10)), seed=seed),
            self.r, rules, self.mechanics())

    def find(self, g, name, player=1, zone='board'):
        return next(i for i in getattr(g.state.players[player], zone)
            if g.state.entities[i].card_id == name)

    def play(self, g, name='trigger', target=None):
        entity_id = self.find(g, name, zone='hand')
        g.apply(PlayCard(1, entity_id, target))
        return entity_id

    def use(self, g, target=None, power_id=None):
        g.apply(UseHeroPower(1, power_id or g.state.players[1].hero_power_id, target))

    def choose(self, g, option='ok'):
        c = g.state.pending_choice
        g.apply(SelectChoice(c.player_id, c.id, (option,)))

    def finish(self, g):
        for _ in range(100):
            if g.state.pending_choice is None:
                return
            self.choose(g)
        self.fail('Fixture did not settle within 100 choices')

    def portable(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot, self.fresh(), self.mechanics()).snapshot(), snapshot)
        self.assertEqual(g.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(g), self.fresh(), self.mechanics()).snapshot(), snapshot)

    def armor(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].armor

    def roots(self, g):
        return g.state.hero_power_history

    def counts(self, g):
        return [p.repeat_plan.repetitions for p in self.roots(g)]

    def nodes(self, value, tail):
        result = []
        def walk(v):
            if isinstance(v, dict):
                if v.get('type', '').split('.')[-1] == tail:
                    result.append(v)
                for key, child in v.items():
                    if key == 'fields' and v.get('type') == 'hs_sim.engine.paid_hand_acceptance.PaidHandChoiceBoundaryProof':
                        for field, operand in child.items():
                            if field != 'work':
                                walk(operand)
                    else:
                        walk(child)
            elif isinstance(v, list):
                for x in v:
                    walk(x)
        walk(value)
        return result

    def edit_ability(self, value, ability_id, edit):
        changes = 0
        def walk(v):
            nonlocal changes
            if isinstance(v, dict):
                fields = v.get('fields') if v.get('type', '').split('.')[-1] == 'AbilityInstance' else v
                if (isinstance(fields, dict) and fields.get('id') == ability_id and
                        {'kind', 'origin', 'consumed', 'remove_on_silence'} <= fields.keys()):
                    edit(fields)
                    changes += 1
                for x in tuple(v.values()):
                    walk(x)
            elif isinstance(v, list):
                for x in v:
                    walk(x)
        walk(value)
        return changes

    def spec_fields(self, ability):
        value = ability['hero_power_repeat']
        return value.get('fields', value)

    def change_count(self, value, ability_id, count):
        changed = self.edit_ability(value, ability_id,
            lambda a: self.spec_fields(a).__setitem__('repetitions', count))
        self.assertGreater(changed, 0)

    def reject(self, snapshot):
        self.rehash(snapshot)
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(snapshot, self.fresh(), self.mechanics())
        self.assertNotIn('digest mismatch', str(error.exception))

    def rehash(self, snapshot):
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})

    def waiting(self, board=('conditional.two', 'beast'), **fields):
        g = self.game(power='waiting', board=board, **fields)
        self.use(g)
        return g

    def dynamic_false_waiting(self):
        g = self.game(power='waiting', board=('plain',), hand=('grant.false',))
        self.play(g, 'grant.false')
        carrier = self.find(g, 'plain')
        ability = next(a for a in g.state.entities[carrier].abilities if a.kind == 'hero_power_repeat')
        self.use(g)
        self.assertEqual(self.counts(g), [1])
        self.portable(g)
        return g, carrier, ability.id

    def test_manual_matching_pays_and_spends_one_use(self):
        g = self.game(board=('conditional.two', 'beast'))
        self.use(g)
        power = g.state.entities[g.state.players[1].hero_power_id]
        self.assertEqual((self.armor(g), g.state.players[1].mana, power.uses_this_turn,
            g.state.players[1].hero_power_uses_this_turn), (2, 8, 1, 1))
        self.assertEqual(self.counts(g), [2])
        self.assertEqual([e.kind for e in g.events if e.kind.startswith('hero_power')],
            ['hero_power_started', 'hero_power_used'])
        self.portable(g)

    def test_mana_spent_callback_keeps_old_view_but_reaction_cannot_shrink_plan(self):
        def payment(c):
            if c.event.source_id != c.state.players[1].hero_power_id:
                return []
            self.assertEqual(c.state.hero_power_history[-1].repeat_plan, HeroPowerRepeatPlan())
            return [Transform(c.state.players[1].board[1], 'plain')]
        self.watch('payment', payment, 'mana_spent')
        g = self.game(board=('conditional.two', 'beast', 'payment'))
        self.use(g)
        self.assertEqual((self.counts(g), self.armor(g)), ([2], 2))
        self.assertEqual(g.state.entities[g.state.players[1].board[1]].card_id, 'plain')
        self.portable(g)

    def test_primary_and_same_face_extra_have_distinct_paid_recipients(self):
        g = self.game(board=('conditional.two', 'beast'), extras=('power',))
        primary = g.state.players[1].hero_power_id
        extra = g.state.players[1].additional_hero_power_ids[0]
        self.use(g, power_id=extra)
        root = self.roots(g)[0]
        self.assertEqual((root.source_id, root.card_id, root.player_id), (extra, 'power', 1))
        self.assertEqual((g.state.entities[primary].uses_this_turn,
            g.state.entities[extra].uses_this_turn), (0, 1))
        self.assertEqual(self.armor(g), 2)
        self.portable(g)

    def test_effect_uses_explicit_extra_reference_without_power_cost_or_use(self):
        def trigger(c):
            power = c.state.entities[c.state.players[1].additional_hero_power_ids[0]]
            return [TriggerHeroPower(1, c.source_id, targeting='explicit', choices='player',
                power=HeroPowerReference.capture(power))]
        self.script('extra', trigger)
        g = self.game(board=('conditional.two', 'beast'), extras=('power',), hand=('extra',))
        activator = self.play(g, 'extra')
        root = self.roots(g)[0]
        self.assertEqual((root.source_id, root.activator_id, root.origin),
            (g.state.players[1].additional_hero_power_ids[0], activator, 'effect'))
        self.assertEqual((root.cost, root.payment, self.armor(g), g.state.players[1].mana),
            (None, None, 2, 9))
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn, 0)
        self.portable(g)

    def test_stale_reference_skips_without_root_or_source_query(self):
        def stale(c):
            reference = HeroPowerReference.capture(c.state.entities[c.state.players[1].hero_power_id])
            return [ReplaceHeroPower(1, 'power', source_id=c.source_id),
                TriggerHeroPower(1, c.source_id, power=reference)]
        self.script('stale', stale)
        g = self.game(board=('conditional.two', 'unknown.metadata'), hand=('stale',))
        self.play(g, 'stale')
        self.assertEqual(self.roots(g), [])
        self.assertTrue(any(e.kind == 'effect_skipped' for e in g.events))
        self.portable(g)

    def test_passive_failed_root_does_not_query_unknown_witness(self):
        self.install('card', CardDefinition('passive', 'Passive', CardType.HERO_POWER,
            passive_hero_power=True, triggers=(TriggerSpec('card_played', 'noop'),)))
        g = self.game(power='passive', board=('conditional.two', 'unknown.metadata'), hand=('trigger',))
        self.play(g)
        root = self.roots(g)[0]
        self.assertEqual((root.failure, root.completed, root.payloads, root.repeat_plan),
            ('passive', True, (), HeroPowerRepeatPlan()))
        self.assertEqual(g.state.hero_power_payload_history, [])
        self.portable(g)

    def test_failed_target_root_does_not_query_unknown_witness(self):
        self.power('targeted', lambda c: [Damage(c.target_id, 1)], requires_target=True)
        self.script('badtarget', lambda c: [TriggerHeroPower(1, c.source_id,
            target_id=c.source_id, targeting='explicit')])
        # Build a separate scenario after the registration, using an actual Spell activator.
        g = self.game(power='targeted', board=('conditional.two', 'unknown.metadata'), hand=('badtarget',))
        self.play(g, 'badtarget')
        self.assertEqual(self.roots(g)[0].failure, 'invalid_target')
        self.assertEqual(self.counts(g), [1])
        self.assertEqual(g.state.hero_power_payload_history, [])
        self.portable(g)

    def test_max_retains_every_matching_lower_and_higher_source(self):
        g = self.game(board=('conditional.three', 'conditional.two', 'beast'))
        self.use(g)
        plan = self.roots(g)[0].repeat_plan
        self.assertEqual((plan.repetitions, len(plan.contributors), self.armor(g)), (3, 2, 3))
        self.assertEqual([s.spec.repetitions for s in plan.contributors], [3, 2])
        self.portable(g)

    def test_all_false_and_no_source_both_have_explicit_unit_root(self):
        for board in (('conditional.two', 'plain'), ()):
            with self.subTest(board=board):
                g = self.game(board=board)
                self.use(g)
                self.assertEqual(self.roots(g)[0].repeat_plan, HeroPowerRepeatPlan())
                self.assertEqual((len(g.state.hero_power_payload_history), self.armor(g)), (1, 1))
                self.portable(g)

    def test_another_excludes_actual_carrier_but_same_face_copy_counts(self):
        self.source('beast.source', spec(2, condition()), metadata=metadata(('beast',)))
        for board, expected in ((('beast.source',), 1), (('beast.source', 'beast.source'), 2)):
            with self.subTest(board=board):
                g = self.game(board=board)
                self.use(g)
                self.assertEqual((self.counts(g), self.armor(g)), ([expected], expected))
                self.portable(g)

    def test_control_presence_can_include_repeat_carrier(self):
        self.source('self.witness', spec(2, condition(another=False)), metadata=metadata(('beast',)))
        g = self.game(board=('self.witness',))
        self.use(g)
        self.assertEqual((self.counts(g), self.armor(g)), ([2], 2))

    def test_another_does_not_exclude_donor_or_power_identity(self):
        self.script('grant.beast', lambda c: [GrantHeroPowerRepeatAura(
            c.state.players[1].board[0], spec(2, condition()), c.source_id)])
        g = self.game(board=('plain', 'beast'), hand=('grant.beast',))
        donor = self.play(g, 'grant.beast')
        carrier = self.find(g, 'plain')
        self.use(g)
        source = self.roots(g)[0].repeat_plan.contributors[0]
        self.assertEqual((source.carrier_id, source.ability.source_id), (carrier, donor))
        self.assertNotEqual(carrier, self.roots(g)[0].source_id)
        self.assertEqual(self.armor(g), 2)
        self.portable(g)

    def test_dormant_witness_profiles_have_distinct_actual_root_counts(self):
        for profile, expected in (('repeat.witness.controlled', 2), ('repeat.witness.active_live', 1)):
            with self.subTest(profile=profile):
                self.setUp()
                self.source('profile.source', spec(2, condition(profile=profile)))
                self.script('sleep', lambda c: [MakeDormant(c.state.players[1].board[1], 2)])
                g = self.game(board=('profile.source', 'beast'), hand=('sleep',))
                self.play(g, 'sleep')
                self.use(g)
                self.assertEqual((self.counts(g), self.armor(g)), ([expected], expected))
                self.portable(g)

    def test_dormant_repeat_carrier_is_ineligible_under_either_witness_profile(self):
        self.script('sleep.source', lambda c: [MakeDormant(c.state.players[1].board[0], 2)])
        g = self.game(board=('conditional.two', 'beast'), hand=('sleep.source',))
        self.play(g, 'sleep.source')
        self.use(g)
        self.assertEqual(self.counts(g), [1])

    def test_doomed_and_nonpositive_witness_use_declared_profile_during_real_deferral(self):
        for operation in (lambda i: Damage(i, 6), Destroy):
            for profile, expected in (('repeat.witness.controlled', 2), ('repeat.witness.active_live', 1)):
                with self.subTest(operation=operation, profile=profile):
                    self.setUp()
                    self.source('profile.source', spec(2, condition(profile=profile)))
                    self.minion('spell.repeat', spell_repeats=(SpellRepeatSpec(class_mode='any'),))
                    self.script('defer', lambda c: [operation(c.state.players[1].board[1]),
                        TriggerHeroPower(1, c.source_id, targeting='explicit')])
                    g = self.game(board=('profile.source', 'beast', 'spell.repeat'), hand=('defer',))
                    self.play(g, 'defer')
                    self.assertEqual((self.counts(g), self.armor(g)), ([expected, expected], 2 * expected))
                    self.assertEqual(len(g.state.death_history), 1)
                    self.portable(g)

    def test_unknown_metadata_after_first_matching_witness_rolls_back_public_action(self):
        g = self.game(board=('conditional.two', 'beast', 'unknown.metadata'))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_unknown_tribes_after_first_matching_witness_are_not_short_circuited(self):
        g = self.game(board=('conditional.two', 'beast', 'unknown.tribes'))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_empty_tribes_query_needs_no_unused_metadata(self):
        self.source('any.source', spec(2, condition(())))
        g = self.game(board=('any.source', 'unknown.metadata'))
        self.use(g)
        self.assertEqual((self.counts(g), self.armor(g)), ([2], 2))
        self.portable(g)

    def test_enemy_and_excluded_carrier_metadata_are_irrelevant(self):
        self.source('unknown.source', spec(2, condition()), metadata=None)
        g = self.game(board=('unknown.source', 'beast'), enemy=('unknown.metadata',))
        self.use(g)
        self.assertEqual(self.counts(g), [2])
        self.portable(g)

    def test_multi_all_and_or_tribes_match_current_face(self):
        for witness in ('multi', 'all', 'dragon'):
            with self.subTest(witness=witness):
                self.setUp()
                self.source('or.source', spec(2, condition(('beast', 'dragon'))))
                g = self.game(board=('or.source', witness))
                self.use(g)
                self.assertEqual(self.armor(g), 2)

    def test_started_true_to_false_keeps_root_and_later_root_recaptures(self):
        self.watch('flip', lambda c: [Transform(c.state.players[1].board[1], 'plain')],
            'hero_power_started')
        g = self.game(board=('conditional.two', 'beast', 'flip'), hand=('trigger',))
        self.use(g)
        self.play(g)
        self.assertEqual((self.counts(g), self.armor(g)), ([2, 1], 3))
        self.portable(g)

    def test_started_false_to_true_does_not_expand_old_root(self):
        self.watch('flip', lambda c: [Transform(c.state.players[1].board[1], 'beast')],
            'hero_power_started')
        g = self.game(board=('conditional.two', 'plain', 'flip'), hand=('trigger',))
        self.use(g)
        self.play(g)
        self.assertEqual((self.counts(g), self.armor(g)), ([1, 2], 3))
        self.portable(g)

    def test_additional_repeat_body_reads_current_world_without_rematching(self):
        def body(c):
            if c.power_payload.repeat_index == 1:
                return [Transform(c.state.players[1].board[1], 'plain'), GainArmor(1, 1)]
            return [GainArmor(1, 10 if c.state.entities[c.state.players[1].board[1]].card_id == 'plain' else 100)]
        self.power('read.latest', body)
        g = self.game(power='read.latest', board=('conditional.two', 'beast'))
        self.use(g)
        self.assertEqual((self.counts(g), self.armor(g)), ([2], 11))
        self.portable(g)

    def test_replace_selected_power_retains_old_payload_then_new_root_selects_new(self):
        self.watch('replace', lambda c: [ReplaceHeroPower(1, 'power', source_id=c.source_id)], 'hero_power_started')
        g = self.game(power='waiting', board=('conditional.two', 'beast', 'replace'), hand=('trigger',))
        old = g.state.players[1].hero_power_id
        self.use(g)
        self.portable(g)
        self.finish(g)
        self.play(g)
        self.assertEqual(self.counts(g), [2, 2])
        self.assertEqual([p.card_id for p in self.roots(g)], ['waiting', 'power'])
        self.assertNotEqual(self.roots(g)[1].source_id, old)
        self.assertEqual(self.armor(g), 4)
        self.portable(g)

    def test_removed_selected_power_does_not_cancel_accepted_body(self):
        self.watch('remove', lambda c: [RemoveHeroPower(1, source_id=c.source_id)], 'hero_power_started')
        g = self.game(power='waiting', board=('conditional.two', 'beast', 'remove'))
        self.use(g)
        self.assertIsNone(g.state.players[1].hero_power_id)
        self.portable(g)
        self.finish(g)
        self.assertEqual(self.armor(g), 2)
        self.portable(g)

    def test_source_control_change_retains_old_owner_then_new_owner_queries_it(self):
        self.power('take', lambda c: [ChangeControl(c.state.players[1].board[0], 2), GainArmor(1, 1)]
            if c.power_payload.repeat_index == 1 else [GainArmor(1, 1)])
        self.script('enemy.trigger', lambda c: [TriggerHeroPower(2, c.source_id, targeting='explicit')])
        g = self.game(power='take', board=('conditional.two', 'beast'), enemy=('beast',), hand=('enemy.trigger',))
        self.use(g)
        self.play(g, 'enemy.trigger')
        self.assertEqual([p.repeat_plan.repetitions for p in self.roots(g)], [2, 2])
        self.assertEqual([p.player_id for p in self.roots(g)], [1, 2])
        self.assertEqual((self.armor(g), self.armor(g, 2)), (2, 2))
        self.portable(g)

    def test_source_silence_bounce_transform_and_dormancy_keep_accepted_root(self):
        operations = (Silence, ReturnToHand, lambda i: Transform(i, 'plain'), lambda i: MakeDormant(i, 2))
        for operation in operations:
            with self.subTest(operation=operation):
                self.setUp()
                self.power('remove.source', lambda c: [operation(c.state.players[1].board[0]), GainArmor(1, 1)]
                    if c.power_payload.repeat_index == 1 else [GainArmor(1, 1)])
                g = self.game(power='remove.source', board=('conditional.two', 'beast'), hand=('trigger',))
                self.use(g)
                self.play(g)
                self.assertEqual((self.counts(g), self.armor(g)), ([2, 1], 3))
                self.portable(g)

    def test_copied_conditional_source_has_new_identity_without_multiplication(self):
        self.script('copy', lambda c: [CopyMinion(c.state.players[1].board[0], 1)])
        g = self.game(board=('conditional.two', 'beast'), hand=('copy',))
        self.play(g, 'copy')
        self.use(g)
        plan = self.roots(g)[0].repeat_plan
        self.assertEqual((self.armor(g), plan.repetitions, len(plan.contributors)), (2, 2, 2))
        self.assertEqual(len({s.ability.id for s in plan.contributors}), 2)
        self.portable(g)

    def test_nested_free_child_recaptures_after_witness_changed(self):
        self.power('nested', lambda c: [Transform(c.state.players[1].board[1], 'plain'),
            TriggerHeroPower(1, c.source_id, targeting='explicit', choices='player'), GainArmor(1, 1)]
            if c.power.origin == 'manual' and c.power_payload.repeat_index == 1 else [ask(c, GainArmor(1, 1))])
        g = self.game(power='nested', board=('conditional.two', 'beast'))
        self.use(g)
        self.assertEqual(self.counts(g), [2, 1])
        self.assertEqual([p.parent_id for p in self.roots(g)], [None, 1])
        self.portable(g)
        self.finish(g)
        self.assertEqual(self.armor(g), 3)
        self.assertEqual([r.execution_order for r in g.state.hero_power_payload_history], [1, 3, 2])
        self.portable(g)

    def test_ordinary_rewind_retry_rebuilds_root_without_extra_net_payment(self):
        self.power('rewind', lambda c: [Transform(c.state.players[1].board[1], 'plain'),
            GainArmor(1, c.rewind_attempt + 1)] if c.power_payload.repeat_index == 1 else
            [GainArmor(1, c.rewind_attempt + 1)], keywords=(Keyword.REWIND,), rewind=RewindSpec(1))
        g = self.game(power='rewind', board=('conditional.two', 'beast'))
        self.use(g)
        self.portable(g)
        self.choose(g, 'retry')
        self.assertEqual(self.counts(g), [2])
        self.assertEqual((len(g.state.hero_power_payload_history), self.armor(g), g.state.players[1].mana), (2, 4, 8))
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn, 1)
        self.portable(g)

    def test_retained_results_keep_plan_after_witness_and_source_disappear(self):
        self.power('retained', lambda c: [Silence(c.state.players[1].board[0]),
            Transform(c.state.players[1].board[1], 'plain'), GainArmor(1, 1)]
            if c.power_payload.repeat_index == 1 else [GainArmor(1, 1)],
            keywords=(Keyword.REWIND,), rewind=RewindSpec(1))
        g = self.game(power='retained', board=('conditional.two', 'beast', 'retainer'))
        self.use(g)
        self.assertEqual((self.counts(g), self.armor(g), g.state.players[1].mana), ([2], 4, 8))
        self.assertEqual([(r.capture.iteration, r.capture.repeat_index) for r in
            g.state.hero_power_payload_history], [(1, 1), (1, 2), (2, 1), (2, 2)])
        self.portable(g)

    def test_retained_result_first_views_refresh_without_recapturing_sources(self):
        self.power('retained.read', lambda c: [GainArmor(1,
            1 if c.state.entities[c.state.players[1].board[1]].card_id == 'beast' else 10),
            Transform(c.state.players[1].board[1], 'plain')],
            keywords=(Keyword.REWIND,), rewind=RewindSpec(1))
        g = self.game(power='retained.read', board=('conditional.two', 'beast', 'retainer'))
        self.use(g)
        self.assertEqual((self.counts(g), self.armor(g)), ([2], 31))
        self.assertEqual([b.plan.repetitions for b in g.state.hero_power_payload_batches], [2, 2])
        self.portable(g)

    def test_custom_empty_success_keeps_matching_root_and_no_payload_batch(self):
        self.custom = True
        self.script('empty', lambda c: [InstallTestPowerPayloads(c.state.players[1].hero_power_id, (), True)])
        g = self.game(board=('conditional.two', 'beast'), hand=('empty',))
        self.play(g, 'empty')
        self.use(g)
        self.assertEqual((self.counts(g), self.roots(g)[0].payloads, self.armor(g)), ([2], (), 0))
        self.assertEqual(g.state.hero_power_payload_batches, [])
        self.assertTrue(self.roots(g)[0].completed)
        self.portable(g)

    def test_custom_multiple_payloads_use_full_order_and_shared_first_view(self):
        self.custom = True
        self.behavior('A', lambda c: [Transform(c.state.players[1].board[1], 'plain'), GainArmor(1, 1)])
        self.behavior('B', lambda c: [GainArmor(1, 10 if
            c.state.entities[c.state.players[1].board[1]].card_id == 'beast' else 100)])
        self.script('multi.install', lambda c: [InstallTestPowerPayloads(c.state.players[1].hero_power_id, ('A', 'B'), True)])
        g = self.game(board=('conditional.two', 'beast'), hand=('multi.install',))
        self.play(g, 'multi.install')
        self.use(g)
        self.assertEqual(self.armor(g), 112)
        self.assertEqual([(r.capture.ability.behavior_id, r.capture.repeat_index) for r in
            g.state.hero_power_payload_history], [('A', 1), ('A', 2), ('B', 1), ('B', 2)])
        self.assertEqual(self.counts(g), [2])
        self.portable(g)

    def test_custom_duplicate_behavior_payloads_keep_distinct_ability_ids(self):
        self.custom = True
        self.script('duplicate', lambda c: [InstallTestPowerPayloads(c.state.players[1].hero_power_id,
            ('armor', 'armor'), True)])
        g = self.game(board=('conditional.two', 'beast'), hand=('duplicate',))
        self.play(g, 'duplicate')
        self.use(g)
        self.assertEqual((self.armor(g), len(self.roots(g)[0].payloads)), (4, 2))
        self.assertEqual(len({a.id for a in self.roots(g)[0].payloads}), 2)
        self.portable(g)

    def test_source_only_model_has_no_recipient_self_tribe_or_kind_arguments(self):
        for fields in ({'recipient_metadata': None}, {'scope': 'self'},
                {'kinds': (CardType.HERO_POWER,)}, {'origins': ('printed',)}):
            with self.subTest(fields=fields), self.assertRaises(TypeError):
                HeroPowerRepeatMatchSpec(**fields)
        self.assertEqual(spec(), HeroPowerRepeatSpec())
        self.assertEqual(HeroPowerRepeatMatchSpec().source_eligibility, None)

    def test_match_and_source_condition_models_reject_wrong_typed_values(self):
        for value in (False, {}, [], 'condition', 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                HeroPowerRepeatMatchSpec(value)
        for value in (False, {}, (), 'match'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                HeroPowerRepeatSpec(match=value)
        for value in (True, 0, -1, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                HeroPowerRepeatSpec(value)

    def test_unknown_profile_is_rejected_by_card_registration_before_any_root(self):
        with self.assertRaises(ValueError):
            self.source('unknown.profile', spec(2, condition(profile='missing.profile')))

    def test_capture_requires_real_registry_even_for_all_false_sources(self):
        g = self.game(board=('false.source',))
        with self.assertRaises(ValueError):
            capture_plan(g.state, None, 1)
        self.assertEqual(capture_plan(g.state, self.r, 1), HeroPowerRepeatPlan())

    def test_dynamic_unknown_profile_grant_rolls_back_paid_spell(self):
        self.script('bad.grant', lambda c: [GrantHeroPowerRepeatAura(c.state.players[1].board[0],
            spec(2, condition(profile='missing.profile')), c.source_id)])
        g = self.game(board=('plain',), hand=('bad.grant',))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'bad.grant')
        self.assertEqual(g.snapshot(), before)

    def test_unknown_profile_on_false_hand_deck_enemy_and_consumed_sources_is_rejected(self):
        for place in ('hand', 'deck', 'enemy', 'consumed', 'dormant'):
            with self.subTest(place=place):
                self.setUp()
                fields = {'hand': ('false.source',)} if place == 'hand' else {
                    'enemy': ('false.source',)} if place == 'enemy' else {
                    'deck': ('false.source',)} if place == 'deck' else {'board': ('false.source',)}
                if place == 'dormant':
                    self.script('sleep', lambda c: [MakeDormant(c.state.players[1].board[0], 2)])
                    fields['hand'] = ('sleep',)
                g = self.game(**fields)
                if place == 'consumed':
                    carrier = self.find(g, 'false.source')
                    g._state.entities[carrier].abilities = [replace(a, consumed=True)
                        if a.kind == 'hero_power_repeat' else a for a in g._state.entities[carrier].abilities]
                if place == 'dormant':
                    self.play(g, 'sleep')
                if place == 'consumed':
                    before = g.snapshot()
                    self.assertEqual(Game.from_snapshot(before, self.fresh()).snapshot(), before)
                    self.assertEqual(g.clone().snapshot(), before)
                else:
                    self.portable(g)
                snapshot = g.snapshot()
                changed = 0
                def edit(a):
                    nonlocal changed
                    m = self.spec_fields(a)['match']
                    m = m.get('fields', m)
                    q = m['source_eligibility']
                    q = q.get('fields', q)
                    q['profile_id'] = 'missing.profile'
                    changed += 1
                for entity in g.state.entities.values():
                    for a in entity.abilities:
                        if a.kind == 'hero_power_repeat':
                            self.edit_ability(snapshot['state'], a.id, edit)
                self.assertGreater(changed, 0)
                self.reject(snapshot)

    def test_false_nonminion_repeat_attachment_is_rejected_in_all_zone_invariants(self):
        g = self.game()
        source = g._state.entities[g.state.players[1].hero_power_id]
        identity = g._state.next_attachment_id
        g._state.next_attachment_id += 1
        source.abilities.append(AbilityInstance(identity, 'hero_power_repeat',
            hero_power_repeat=spec(2, condition(('dragon',)))))
        self.reject(g.snapshot())

    def test_frozen_nonminion_death_repeat_declaration_is_rejected_even_false(self):
        self.install('card', CardDefinition('weapon.rattle', 'Weapon', CardType.WEAPON,
            attack=1, durability=1, deathrattle='noop'))
        from hs_sim.engine.effects import EquipWeapon
        self.script('weapon', lambda c: [EquipWeapon(1, 'weapon.rattle')])
        self.script('replace.weapon', lambda c: [EquipWeapon(1, 'weapon.rattle')])
        g = self.game(hand=('weapon', 'replace.weapon'))
        self.play(g, 'weapon')
        self.play(g, 'replace.weapon')
        snapshot = g.snapshot()
        identity = snapshot['state']['next_attachment_id']
        snapshot['state']['next_attachment_id'] += 1
        template = self.game(board=('false.source',)).snapshot()['state']['entities']
        ability = next(a for e in template.values() for a in e['abilities'] if a['kind'] == 'hero_power_repeat')
        ability['id'] = identity
        ability['source_id'] = None
        ability['origin'] = 'granted'
        snapshot['state']['death_history'][0]['abilities'].append(ability)
        self.reject(snapshot)

    def test_wire_requires_explicit_match_field_and_exact_source_only_shape(self):
        g = self.waiting()
        for mutation in ('missing', 'recipient_metadata', 'scope', 'extra_condition'):
            with self.subTest(mutation=mutation):
                snapshot = g.snapshot()
                carrier = self.find(g, 'conditional.two')
                a = next(a for a in snapshot['state']['entities'][str(carrier)]['abilities']
                    if a['kind'] == 'hero_power_repeat')
                declaration = a['hero_power_repeat']
                if mutation == 'missing':
                    declaration.pop('match')
                elif mutation in ('recipient_metadata', 'scope'):
                    declaration['match'][mutation] = None if mutation == 'recipient_metadata' else 'self'
                else:
                    declaration['match']['source_eligibility']['surprise'] = True
                self.reject(snapshot)

    def test_wire_rejects_missing_source_eligibility_and_wrong_frozen_match_type(self):
        g = self.waiting()
        for mutation in ('missing', 'wrong_type'):
            with self.subTest(mutation=mutation):
                snapshot = g.snapshot()
                carrier = self.find(g, 'conditional.two')
                a = next(a for a in snapshot['state']['entities'][str(carrier)]['abilities']
                    if a['kind'] == 'hero_power_repeat')
                if mutation == 'missing':
                    a['hero_power_repeat']['match'].pop('source_eligibility')
                else:
                    marker = self.nodes(snapshot['resolution_frame'], 'FinishHeroPower')[0]
                    typed = self.nodes(marker, 'HeroPowerRepeatMatchSpec')
                    self.assertTrue(typed)
                    typed[0]['type'] = 'hs_sim.engine.model.DeathrattleRepeatMatchSpec'
                self.reject(snapshot)

    def test_previous_schema_is_rejected_without_implicit_match_defaults(self):
        g = self.waiting()
        snapshot = g.snapshot()
        snapshot['schema_version'] = 105
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(snapshot, self.fresh())

    def test_completed_contributor_full_source_identity_cannot_be_rewritten(self):
        g = self.game(board=('conditional.two', 'beast'))
        self.use(g)
        snapshot = g.snapshot()
        source = snapshot['state']['hero_power_history'][0]['repeat_plan']['contributors'][0]
        source['ability']['source_id'] = g.state.players[2].hero_id
        self.reject(snapshot)

    def test_completed_contributor_expiry_origin_and_consumption_static_identity(self):
        g = self.game(board=('conditional.two', 'beast'))
        self.use(g)
        for field, value in (('expires_turn', 1), ('origin', 'granted'), ('remove_on_silence', False)):
            with self.subTest(field=field):
                snapshot = g.snapshot()
                source = snapshot['state']['hero_power_history'][0]['repeat_plan']['contributors'][0]
                source['ability'][field] = value
                self.reject(snapshot)

    def test_completed_contributor_id_cannot_belong_to_other_global_family(self):
        self.minion('foreign', battlecry_repeats=(BattlecryRepeatSpec(kinds=(CardType.MINION,)),))
        g = self.game(board=('conditional.two', 'beast', 'foreign'))
        self.use(g)
        foreign = next(a for a in g.state.entities[self.find(g, 'foreign')].abilities
            if a.kind == 'battlecry_repeat')
        snapshot = g.snapshot()
        source = snapshot['state']['hero_power_history'][0]['repeat_plan']['contributors'][0]
        source['ability']['id'] = foreign.id
        self.reject(snapshot)

    def test_completed_history_does_not_requery_current_unknown_witness_metadata(self):
        self.script('unknown', lambda c: [Transform(c.state.players[1].board[1], 'unknown.metadata')])
        g = self.game(board=('conditional.two', 'beast'), hand=('unknown',))
        self.use(g)
        self.play(g, 'unknown')
        self.assertEqual(self.counts(g), [2])
        self.portable(g)

    def test_expired_granted_source_history_uses_original_acceptance_turn(self):
        self.script('grant.expiry', lambda c: [GrantHeroPowerRepeatAura(c.state.players[1].board[0],
            spec(2, condition()), c.source_id, expires_turn=1)])
        g = self.game(board=('plain', 'beast'), hand=('grant.expiry', 'trigger'))
        self.play(g, 'grant.expiry')
        self.use(g)
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.play(g)
        self.assertEqual(self.counts(g), [2, 1])
        self.portable(g)

    def test_false_surviving_declaration_changed_in_current_state_is_rejected(self):
        g, carrier, identity = self.dynamic_false_waiting()
        snapshot = g.snapshot()
        self.change_count(snapshot['state']['entities'][str(carrier)], identity, 4)
        self.reject(snapshot)

    def test_root_finish_false_declaration_binds_independent_original_window(self):
        g, carrier, identity = self.dynamic_false_waiting()
        snapshot = g.snapshot()
        marker = self.nodes(snapshot['resolution_frame'], 'FinishHeroPower')[0]
        self.change_count(marker['fields']['context'], identity, 4)
        self.reject(snapshot)
        self.finish(g)
        self.assertEqual(self.armor(g), 1)

    def test_false_source_cannot_be_erased_only_from_original_finish_view(self):
        g, carrier, identity = self.dynamic_false_waiting()
        snapshot = g.snapshot()
        marker = self.nodes(snapshot['resolution_frame'], 'FinishHeroPower')[0]
        erased = []
        def erase(v):
            if isinstance(v, dict):
                values = v.get('abilities')
                if isinstance(values, list):
                    before = len(values)
                    values[:] = [a for a in values if a.get('id') != identity]
                    erased.append(before - len(values))
                for x in v.values():
                    erase(x)
            elif isinstance(v, list):
                for x in v:
                    erase(x)
        erase(marker)
        self.assertGreater(sum(erased), 0)
        self.reject(snapshot)

    def test_false_consumed_source_cannot_be_revived_after_original_acceptance(self):
        g = self.game(power='waiting', board=('false.source',))
        carrier = self.find(g, 'false.source')
        identity = next(a.id for a in g.state.entities[carrier].abilities if a.kind == 'hero_power_repeat')
        g._state.entities[carrier].abilities = [replace(a, consumed=True) if a.id == identity else a
            for a in g._state.entities[carrier].abilities]
        g = Game.from_snapshot(g.snapshot(), self.fresh())
        self.use(g)
        snapshot = g.snapshot()
        self.assertGreater(self.edit_ability(snapshot['state']['entities'][str(carrier)], identity,
            lambda a: a.__setitem__('consumed', False)), 0)
        self.reject(snapshot)

    def test_false_old_global_id_cannot_switch_to_battlecry_family(self):
        g, carrier, identity = self.dynamic_false_waiting()
        snapshot = g.snapshot()
        a = next(a for a in snapshot['state']['entities'][str(carrier)]['abilities'] if a['id'] == identity)
        a['kind'] = 'battlecry_repeat'
        a['hero_power_repeat'] = None
        a['battlecry_repeat'] = dict(repetitions=2, kinds=['minion'], scope='friendly', match=None)
        self.reject(snapshot)

    def test_last_payload_root_finish_binds_false_source_after_no_invoke_remains(self):
        g, carrier, identity = self.dynamic_false_waiting()
        snapshot = g.snapshot()
        self.assertFalse(self.nodes(snapshot['resolution_frame'], 'InvokeHeroPowerPayload'))
        self.assertTrue(self.nodes(snapshot['resolution_frame'], 'FinishHeroPower'))
        marker = self.nodes(snapshot['resolution_frame'], 'FinishHeroPower')[0]
        self.change_count(marker['fields']['context'], identity, 4)
        self.reject(snapshot)
        self.finish(g)
        self.portable(g)

    def test_pending_start_root_finish_is_independent_of_unchanged_invoke(self):
        self.watch('start.wait', lambda c: [ask(c, GainArmor(1, 1))], 'hero_power_started')
        g = self.game(power='noop.power', board=('plain', 'start.wait'), hand=('grant.false',))
        self.play(g, 'grant.false')
        identity = next(a.id for a in g.state.entities[self.find(g, 'plain')].abilities
            if a.kind == 'hero_power_repeat')
        self.use(g)
        self.portable(g)
        snapshot = g.snapshot()
        invokes = copy.deepcopy(self.nodes(snapshot['resolution_frame'], 'InvokeHeroPowerPayload'))
        self.assertEqual(len(invokes), 1)
        marker = self.nodes(snapshot['resolution_frame'], 'FinishHeroPower')[0]
        self.change_count(marker['fields']['context'], identity, 4)
        self.assertEqual(self.nodes(snapshot['resolution_frame'], 'InvokeHeroPowerPayload'), invokes)
        self.reject(snapshot)
        self.finish(g)
        self.assertEqual(self.armor(g), 1)

    def removed_source_child(self):
        self.power('parent.child', lambda c: [TriggerHeroPower(1, c.source_id,
            targeting='explicit', choices='player'), GainArmor(1, 1)] if c.power.origin == 'manual'
            else [Silence(c.state.players[1].board[0]), ask(c, GainArmor(1, 1))])
        g = self.game(power='parent.child', board=('plain',), hand=('grant.false',))
        self.play(g, 'grant.false')
        carrier = self.find(g, 'plain')
        identity = next(a.id for a in g.state.entities[carrier].abilities if a.kind == 'hero_power_repeat')
        self.use(g)
        self.assertFalse(g.state.entities[carrier].abilities)
        self.portable(g)
        return g, identity

    def test_later_child_original_window_cannot_rewrite_false_source_now_removed(self):
        g, identity = self.removed_source_child()
        snapshot = g.snapshot()
        marker = next(m for m in self.nodes(snapshot['resolution_frame'], 'FinishHeroPower')
            if m['fields']['record_id'] == 2)
        self.change_count(marker['fields']['context'], identity, 4)
        self.reject(snapshot)
        self.finish(g)
        self.assertEqual(self.armor(g), 2)

    def test_early_parent_root_view_may_legitimately_lack_later_child(self):
        g, identity = self.removed_source_child()
        marker = next(w for w in (*g._frame.prefix, *g._frame.continuation)
            if type(w) is FinishHeroPower and w.record_id == 1)
        self.assertEqual(len(marker.context.state.hero_power_history), 1)
        self.assertEqual(len(self.roots(g)), 2)
        self.portable(g)
        self.finish(g)
        self.portable(g)

    def test_queued_invoke_false_original_declaration_cannot_change_independently(self):
        self.watch('start.wait', lambda c: [ask(c, GainArmor(1, 1))], 'hero_power_started')
        g = self.game(power='noop.power', board=('plain', 'start.wait'), hand=('grant.false',))
        self.play(g, 'grant.false')
        identity = next(a.id for a in g.state.entities[self.find(g, 'plain')].abilities
            if a.kind == 'hero_power_repeat')
        self.use(g)
        snapshot = g.snapshot()
        invoke = self.nodes(snapshot['resolution_frame'], 'InvokeHeroPowerPayload')[0]
        self.change_count(invoke['fields']['context'], identity, 4)
        self.reject(snapshot)

    def test_custom_empty_success_original_root_has_no_payload_witness_to_replace_finish(self):
        self.custom = True
        self.script('empty', lambda c: [InstallTestPowerPayloads(c.state.players[1].hero_power_id, (), True)])
        self.watch('start.wait', lambda c: [ask(c, GainArmor(1, 1))], 'hero_power_started')
        g = self.game(board=('plain', 'start.wait'), hand=('grant.false', 'empty'))
        self.play(g, 'grant.false')
        identity = next(a.id for a in g.state.entities[self.find(g, 'plain')].abilities
            if a.kind == 'hero_power_repeat')
        self.play(g, 'empty')
        self.use(g)
        self.assertFalse(g.state.hero_power_payload_batches)
        self.portable(g)
        snapshot = g.snapshot()
        marker = self.nodes(snapshot['resolution_frame'], 'FinishHeroPower')[0]
        self.change_count(marker['fields']['context'], identity, 4)
        self.reject(snapshot)
        self.finish(g)
        self.portable(g)

    def test_whole_queued_repeat_position_trim_keeps_independent_root_anchor(self):
        g = self.waiting(board=('conditional.three', 'beast'))
        snapshot = g.snapshot()
        original_finish = copy.deepcopy(self.nodes(snapshot['resolution_frame'], 'FinishHeroPower'))
        # Keep the original root proof intact while truncating all downstream facts.
        snapshot['state']['hero_power_payload_history'].pop()
        snapshot['state']['hero_power_payload_batches'][0]['plan']['repetitions'] = 2
        queue = snapshot['resolution_frame']['fields']['continuation']['tuple']
        queue[:] = [w for w in queue if not (w.get('type', '').endswith('.InvokeHeroPowerPayload') and
            w['fields']['context']['fields']['power_payload']['fields']['repeat_index'] == 3)]
        self.assertEqual(self.nodes(snapshot['resolution_frame'], 'FinishHeroPower'), original_finish)
        self.reject(snapshot)

    def test_root_marker_missing_or_duplicate_is_rejected_even_with_unit_plan(self):
        g, _, _ = self.dynamic_false_waiting()
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                snapshot = g.snapshot()
                queue = snapshot['resolution_frame']['fields']['continuation']['tuple']
                marker = self.nodes(snapshot['resolution_frame'], 'FinishHeroPower')[0]
                if duplicate:
                    queue.append(copy.deepcopy(marker))
                else:
                    queue.remove(marker)
                self.reject(snapshot)

    def test_completed_history_does_not_recapture_removed_or_transferred_source(self):
        self.script('remove', lambda c: [Silence(c.state.players[1].board[0]),
            ChangeControl(c.state.players[1].board[1], 2)])
        g = self.game(board=('conditional.two', 'beast'), hand=('remove',))
        self.use(g)
        self.play(g, 'remove')
        self.assertEqual(self.counts(g), [2])
        self.portable(g)

    def test_choice_rng_then_real_registered_failure_rolls_back_waiting_transaction(self):
        def fail(c):
            raise ValueError('registered failure after RNG')
        self.behavior('fail', fail)
        self.power('bad.choice', lambda c: [ask(c,
            RandomDamage((c.state.players[1].hero_id, c.state.players[2].hero_id), 1, c.source_id),
            InvokeBehavior('fail', c.source_id, c.player_id))])
        g = self.game(power='bad.choice',
            board=('conditional.two', 'beast'))
        self.use(g)
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual((g.state.players[1].mana, g.state.players[1].hero_power_uses_this_turn), (8, 1))
        self.portable(g)

    def test_initial_later_repeat_failure_rolls_back_payment_root_and_all_facts(self):
        def body(c):
            if c.power_payload.repeat_index == 2:
                raise ValueError('second actual payload failed')
            return [GainArmor(1, 1)]
        self.power('bad.second', body)
        g = self.game(power='bad.second', board=('conditional.two', 'beast'))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_matching_expansion_obeys_budget_but_false_huge_source_does_not_expand(self):
        self.source('huge', spec(100001, condition()))
        g = self.game(board=('huge', 'beast'))
        before = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            self.use(g)
        self.assertEqual(g.snapshot(), before)
        other = self.game(board=('huge', 'plain'))
        self.use(other)
        self.assertEqual((self.counts(other), self.armor(other)), ([1], 1))
        self.portable(other)

    def test_recursive_free_roots_share_budget_and_roll_back_outer_manual_action(self):
        self.power('recursive', lambda c: [TriggerHeroPower(1, c.source_id, targeting='explicit')])
        g = self.game(power='recursive', board=('conditional.two', 'beast'),
            rules=Ruleset(max_resolution_steps=35))
        before = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_fatal_started_reaction_preserves_plan_and_interrupts_unstarted_positions(self):
        self.watch('fatal', lambda c: [Damage(c.state.players[2].hero_id, 30)], 'hero_power_started')
        g = self.game(board=('conditional.three', 'beast', 'fatal'))
        self.use(g)
        self.assertEqual(self.counts(g), [3])
        self.assertTrue(self.roots(g)[0].interrupted)
        self.assertEqual([r.execution_order for r in g.state.hero_power_payload_history], [None] * 3)
        self.assertTrue(all(r.interrupted for r in g.state.hero_power_payload_history))
        self.portable(g)

    def test_fatal_extra_body_keeps_prior_completed_position(self):
        self.power('fatal.second', lambda c: [GainArmor(1, 1)] if c.power_payload.repeat_index == 1
            else [Damage(c.state.players[2].hero_id, 30)])
        g = self.game(power='fatal.second', board=('conditional.three', 'beast'))
        self.use(g)
        rows = g.state.hero_power_payload_history
        self.assertEqual([r.completed for r in rows], [True, False, False])
        self.assertEqual([r.interrupted for r in rows], [False, True, True])
        self.assertEqual(self.armor(g), 1)
        self.portable(g)

    def test_retained_fatal_started_reaction_has_proved_root_without_started_batch(self):
        self.power('retained', lambda c: [GainArmor(1, 1)],
            keywords=(Keyword.REWIND,), rewind=RewindSpec(1))
        self.watch('fatal', lambda c: [Damage(c.state.players[2].hero_id, 30)], 'hero_power_started')
        g = self.game(power='retained', board=('conditional.two', 'beast', 'retainer', 'fatal'))
        self.use(g)
        self.assertEqual(self.counts(g), [2])
        self.assertFalse(g.state.hero_power_payload_batches)
        self.assertFalse(g.state.hero_power_payload_history)
        self.assertTrue(self.roots(g)[0].interrupted)
        self.portable(g)

    def test_fatal_payment_reaction_executes_after_full_matching_acceptance(self):
        self.watch('fatal.payment', lambda c: [Damage(c.state.players[2].hero_id, 30)]
            if c.event.source_id == c.state.players[1].hero_power_id else [], 'mana_spent')
        g = self.game(board=('conditional.two', 'beast', 'fatal.payment'))
        self.use(g)
        self.assertEqual((self.counts(g), g.state.players[1].mana), ([2], 8))
        self.assertTrue(self.roots(g)[0].interrupted)
        self.portable(g)

    def test_player_observations_actions_events_are_detached_and_hide_private_match(self):
        g = self.waiting()
        forbidden = ('hero_power_history', 'hero_power_payload_history', 'contributors',
            'repeat_plan', 'source_eligibility', 'profile_id', 'resolution_frame', 'rng_state')
        for player in (1, 2):
            port = g.for_player(player)
            before = g.snapshot()
            view = port.observe()
            encoded = json.dumps((view, port.legal_actions(), port.events()), sort_keys=True)
            for field in forbidden:
                self.assertNotIn('"' + field + '"', encoded)
            view['observation']['players'][0]['hero']['armor'] = 999
            self.assertEqual(g.snapshot(), before)
        self.portable(g)

    def test_each_real_waiting_position_and_terminal_restores_with_fresh_registry(self):
        g = self.waiting(board=('conditional.three', 'beast'))
        positions = []
        while g.state.pending_choice is not None:
            self.portable(g)
            row = next(r for r in reversed(g.state.hero_power_payload_history)
                if r.execution_order is not None and not r.completed)
            positions.append(row.capture.repeat_index)
            self.choose(g)
        self.assertEqual(positions, [1, 2, 3])
        self.assertEqual(self.armor(g), 3)
        self.portable(g)

    def test_refresh_and_use_limits_remain_separate_from_matching_repeat_count(self):
        self.script('refresh', lambda c: [RefreshHeroPower(1), SetHeroPowerUses(1, 2)])
        g = self.game(board=('conditional.two', 'beast'), hand=('refresh',))
        self.use(g)
        with self.assertRaises(IllegalAction):
            self.use(g)
        self.play(g, 'refresh')
        self.use(g)
        self.assertEqual((self.counts(g), self.armor(g)), ([2, 2], 4))
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn, 2)
        self.portable(g)

    def foreign_child(self, family):
        field = {'battlecry': 'battlecry_repeats', 'combo': 'combo_repeats',
            'spell': 'spell_repeats', 'deathrattle': 'deathrattle_repeats'}[family]
        declaration = {'battlecry': BattlecryRepeatSpec(kinds=(CardType.MINION,)),
            'combo': ComboRepeatSpec(), 'spell': SpellRepeatSpec(class_mode='any'),
            'deathrattle': DeathrattleRepeatSpec()}[family]
        self.minion('dual', **{field: (declaration,)})
        def child(c):
            repeat = getattr(c, family).repeat_index if family != 'spell' else c.cast.iteration
            effects = [Silence(next(i for i in c.state.players[1].board
                if c.state.entities[i].card_id == 'dual'))] if repeat == 1 else []
            return [ask(c, *effects, GainArmor(1, 1))]
        self.behavior('foreign.body', child)
        if family == 'spell':
            self.script('foreign.child', child)
        else:
            fields = {family: 'foreign.body', 'cost': 1}
            if family == 'combo':
                fields['keywords'] = (Keyword.COMBO,)
            self.minion('foreign.child', **fields)
        def parent(c):
            if family == 'deathrattle':
                target = next(i for i in c.state.players[1].board
                    if c.state.entities[i].card_id == 'foreign.child')
                effect = TriggerDeathrattles(target, c.source_id)
            else:
                target = next(i for i in c.state.players[1].hand
                    if c.state.entities[i].card_id == 'foreign.child')
                effect = PlayFromHand(PlayCard(1, target))
            return [ask(c, effect, ask(c, GainArmor(1, 1)))]
        self.power('foreign.parent', parent)
        g = self.game(power='foreign.parent', board=('dual', 'foreign.child')
            if family == 'deathrattle' else ('dual',), hand=('grant.false',)
            if family == 'deathrattle' else ('grant.false', 'foreign.child'))
        self.play(g, 'grant.false')
        carrier = self.find(g, 'dual')
        identity = next(a.id for a in g.state.entities[carrier].abilities if a.kind == 'hero_power_repeat')
        foreign_id = next(a.id for a in g.state.entities[carrier].abilities if a.kind == family + '_repeat')
        self.use(g)
        self.choose(g)
        self.choose(g)
        self.assertFalse(g.state.entities[carrier].abilities)
        self.assertEqual(self.counts(g), [1])
        self.portable(g)
        return g, identity, foreign_id

    def test_four_later_foreign_original_windows_bind_false_source_after_live_removal(self):
        endings = {'battlecry': 'FinishBattlecryAcceptance', 'combo': 'FinishComboAcceptance',
            'spell': 'FinishSpellAcceptance', 'deathrattle': 'FinishDeathrattleBatch'}
        for family, ending in endings.items():
            with self.subTest(family=family):
                self.setUp()
                g, identity, _ = self.foreign_child(family)
                snapshot = g.snapshot()
                markers = self.nodes(snapshot['resolution_frame'], ending)
                self.assertTrue(markers)
                self.change_count(markers[-1], identity, 4)
                self.reject(snapshot)
                self.finish(g)
                self.assertEqual(self.armor(g), 3)
                self.portable(g)

    def test_four_completed_foreign_sources_cannot_reuse_removed_false_HP_id(self):
        for family in ('battlecry', 'combo', 'spell', 'deathrattle'):
            with self.subTest(family=family):
                self.setUp()
                g, identity, foreign_id = self.foreign_child(family)
                self.choose(g)
                endings = ('FinishBattlecryAcceptance', 'FinishComboAcceptance',
                    'FinishSpellAcceptance', 'FinishDeathrattleBatch')
                self.assertFalse(any(self.nodes(g.snapshot()['resolution_frame'], ending) for ending in endings))
                self.portable(g)
                snapshot = g.snapshot()
                changes = []
                def rewrite(value):
                    if isinstance(value, dict):
                        contributors = value.get('contributors')
                        if isinstance(contributors, list):
                            for index, item in enumerate(contributors):
                                if item == foreign_id:
                                    contributors[index] = identity
                                    changes.append(True)
                        if value.get('kind') == family + '_repeat' and value.get('id') == foreign_id:
                            value['id'] = identity
                            changes.append(True)
                        for item in value.values():
                            rewrite(item)
                    elif isinstance(value, list):
                        for item in value:
                            rewrite(item)
                rewrite(snapshot['state'])
                self.assertTrue(changes)
                self.reject(snapshot)
                self.finish(g)
                self.assertEqual(self.armor(g), 3)

    def end_guard_fixture(self, *, carrier_kind='minion', skip=False, natural=False):
        def first(c):
            dual = next(i for i in c.state.players[1].board if c.state.entities[i].card_id == 'dual')
            effects = [Silence(dual)]
            if skip:
                effects.append(Destroy(next(i for i in c.state.players[1].board
                    if c.state.entities[i].card_id == 'end.last')))
            return [ask(c, *effects, ask(c, GainArmor(1, 1)))]
        self.behavior('end.first', first)
        self.minion('dual')
        self.minion('end.first', triggers=(TriggerSpec('turn_ended', 'end.first', EndTurnSpec()),))
        if carrier_kind == 'hero_power':
            self.power('end.last', lambda c: [GainArmor(1, 1)],
                triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),))
        elif carrier_kind == 'limited':
            self.minion('end.last', limited_triggers=(LimitedTriggerSpec('turn_ended', 'armor',
                uses=2, end_turn=EndTurnSpec()),))
        else:
            self.minion('end.last', triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),))
        def parent(c):
            selected = tuple(i for i in c.state.players[1].board
                if c.state.entities[i].card_id.startswith('end.'))
            if carrier_kind == 'hero_power':
                selected += (c.state.players[1].additional_hero_power_ids[0],)
            request = EndTurnRequest(EndTurnSelector('selected', (1,),
                ('minion', 'hero_power') if carrier_kind == 'hero_power' else ('minion',), selected))
            effect = EndTurnPhase(1) if natural else TriggerEndTurnEffects(1, request, c.source_id)
            return [ask(c, effect, ask(c, GainArmor(1, 1)))]
        self.power('end.parent', parent)
        if carrier_kind == 'hero_power':
            self.script('add.end.last', lambda c: [AddHeroPower(1, 'end.last', c.source_id)])
        g = self.game(power='end.parent', board=('dual', 'end.first') if carrier_kind == 'hero_power'
            else ('dual', 'end.first', 'end.last'), hand=('grant.false', 'add.end.last')
            if carrier_kind == 'hero_power' else ('grant.false',))
        self.play(g, 'grant.false')
        if carrier_kind == 'hero_power':
            # Scenario-installed skills precede board listeners; a real later
            # installation leaves this guard pending behind the first body.
            self.play(g, 'add.end.last')
        carrier = self.find(g, 'dual')
        identity = next(a.id for a in g.state.entities[carrier].abilities if a.kind == 'hero_power_repeat')
        self.use(g)
        self.choose(g)
        self.choose(g)
        self.assertFalse(g.state.entities[carrier].abilities)
        self.portable(g)
        return g, identity

    def test_later_pending_EndTurn_guard_retains_complete_false_HP_identity(self):
        g, identity = self.end_guard_fixture()
        snapshot = g.snapshot()
        markers = self.nodes(snapshot['resolution_frame'], 'InvokeEndTurn')
        self.assertTrue(markers)
        self.change_count(markers[-1]['fields']['acceptance'], identity, 4)
        self.reject(snapshot)
        self.finish(g)
        self.assertEqual(self.armor(g), 3)
        self.portable(g)

    def test_later_EndTurn_guard_checks_original_false_source_before_legal_skip(self):
        g, identity = self.end_guard_fixture(carrier_kind='limited', skip=True)
        before = g.snapshot()
        from hs_sim.engine.hero_power_acceptance import validate_control_work
        from hs_sim.engine.end_turns import CheckActiveEndTurn
        called = []
        def corrupt(r, work):
            if type(work) is CheckActiveEndTurn and work.acceptance.source.card_id == 'end.last':
                saved = copy.deepcopy(work.acceptance.state)
                for entity in saved.entities.values():
                    entity.abilities = [replace(a, hero_power_repeat=replace(a.hero_power_repeat,
                        repetitions=4)) if a.id == identity else a for a in entity.abilities]
                context = replace(work.acceptance, state=saved)
                work = replace(work, context=context, acceptance=context)
                called.append(True)
            return validate_control_work(r, work)
        with patch('hs_sim.engine.hero_power_acceptance.validate_control_work', side_effect=corrupt):
            with self.assertRaises(ResolutionError):
                self.choose(g)
        self.assertTrue(called)
        self.assertEqual(g.snapshot(), before)
        self.finish(g)
        self.assertTrue(any(row.skipped for row in g.state.end_turn_history))
        self.portable(g)

    def test_later_finite_EndTurn_guard_binds_HP_false_source_before_it_is_erased(self):
        self.check_special_end_guard('limited')

    def test_later_installed_power_EndTurn_guard_binds_HP_false_source_before_it_is_erased(self):
        self.check_special_end_guard('hero_power')

    def check_special_end_guard(self, kind):
        g, identity = self.end_guard_fixture(carrier_kind=kind, natural=True)
        before = g.snapshot()
        from hs_sim.engine.hero_power_acceptance import validate_control_work
        from hs_sim.engine.limited_triggers import CheckLimitedTrigger
        from hs_sim.engine.hero_powers import CheckHeroPowerTrigger
        target = CheckLimitedTrigger if kind == 'limited' else CheckHeroPowerTrigger
        called = []
        def corrupt(r, work):
            if type(work) is target:
                c = work.end_turn_context if kind == 'limited' else work.context
                if c is not None and c.end_turn is not None and c.source.card_id == 'end.last':
                    saved = copy.deepcopy(c.state)
                    for entity in saved.entities.values():
                        entity.abilities = [replace(a, hero_power_repeat=replace(a.hero_power_repeat,
                            repetitions=4)) if a.id == identity else a for a in entity.abilities]
                    work = replace(work, **{'end_turn_context' if kind == 'limited' else 'context':
                        replace(c, state=saved)})
                    called.append(True)
            return validate_control_work(r, work)
        with patch('hs_sim.engine.hero_power_acceptance.validate_control_work', side_effect=corrupt):
            with self.assertRaises(ResolutionError):
                self.choose(g)
        self.assertTrue(called)
        self.assertEqual(g.snapshot(), before)
        self.finish(g)
        self.portable(g)

    def test_completed_foreign_player_DR_clock_cannot_increase_after_source_expiry(self):
        self.install('player_effect', PlayerEffectSpec('clock', 'plain', kind='objective', duration=3,
            tick_event='turn_ended', deathrattle_repeats=(DeathrattleRepeatSpec(),)))
        self.script('clock.add', lambda c: [AddPlayerEffect(1, 'clock', c.source_id)])
        self.minion('clock.child', deathrattle='armor')
        def parent(c):
            child = next(i for i in c.state.players[1].board if c.state.entities[i].card_id == 'clock.child')
            instance = c.state.players[1].player_effects[0]
            return [TriggerDeathrattles(child, c.source_id), TickPlayerEffect(1, instance.id, 3),
                TriggerDeathrattles(child, c.source_id), TickPlayerEffect(1, instance.id, 2),
                TriggerDeathrattles(child, c.source_id), TickPlayerEffect(1, instance.id, 1),
                ask(c, GainArmor(1, 1))]
        self.power('clock.parent', parent)
        g = self.game(power='clock.parent', board=('clock.child',), hand=('clock.add',))
        self.play(g, 'clock.add')
        self.use(g)
        self.assertFalse(g.state.players[1].player_effects)
        self.assertFalse(self.nodes(g.snapshot()['resolution_frame'], 'FinishDeathrattleBatch'))
        remaining = [b.payloads[0].plan.contributors[0].instance.remaining_turns
            for b in g.state.deathrattle_batches]
        self.assertEqual(remaining, [3, 2, 1])
        self.portable(g)
        snapshot = g.snapshot()
        later = snapshot['state']['deathrattle_batches'][2]['payloads'][0]['plan']['contributors'][0]
        later['instance']['remaining_turns'] = 3
        self.reject(snapshot)
        self.finish(g)
        self.assertEqual(self.armor(g), 7)
        self.portable(g)

    def test_false_HP_frozen_death_declaration_remains_bound_after_live_attachment_is_reset(self):
        self.power('death.parent', lambda c: [ask(c, Destroy(c.state.players[1].board[0]),
            ask(c, GainArmor(1, 1)))])
        g = self.game(power='death.parent', board=('plain',), hand=('grant.false',))
        self.play(g, 'grant.false')
        carrier = self.find(g, 'plain')
        identity = next(a.id for a in g.state.entities[carrier].abilities if a.kind == 'hero_power_repeat')
        self.use(g)
        self.choose(g)
        self.assertEqual(len(g.state.death_history), 1)
        self.assertEqual(self.counts(g), [1])
        snapshot = g.snapshot()
        snapshot['state']['entities'][str(carrier)]['abilities'] = []
        self.rehash(snapshot)
        restored = Game.from_snapshot(snapshot, self.fresh())
        self.assertEqual(restored.snapshot(), snapshot)
        self.assertEqual(g.state.death_history[0].abilities[-1].id, identity)
        self.change_count(snapshot['state']['death_history'][0], identity, 4)
        self.reject(snapshot)
        self.finish(g)
        self.portable(g)

    def test_false_HP_frozen_death_source_requires_minion_face_even_without_current_attachment(self):
        self.install('card', CardDefinition('weapon.face', 'Weapon', CardType.WEAPON,
            attack=1, durability=1, metadata=metadata()))
        self.power('death.parent', lambda c: [ask(c, Destroy(c.state.players[1].board[0]),
            ask(c, GainArmor(1, 1)))])
        g = self.game(power='death.parent', board=('plain',), hand=('grant.false',))
        self.play(g, 'grant.false')
        carrier = self.find(g, 'plain')
        self.use(g)
        self.choose(g)
        self.portable(g)
        snapshot = g.snapshot()
        snapshot['state']['entities'][str(carrier)]['abilities'] = []
        snapshot['state']['death_history'][0]['card_id'] = 'weapon.face'
        self.reject(snapshot)

    def test_inactive_starship_witness_requires_registered_presence_profile(self):
        self.install('repeat_witness_profile', RepeatWitnessProfile('test.building', include_starship_building=True))
        self.minion('ship', health=0, metadata=metadata(('beast',)), starship_for=(CardClass.NEUTRAL,))
        self.minion('piece', keywords=(Keyword.STARSHIP_PIECE,))
        self.source('building.source', spec(2, condition(profile='test.building')))
        self.script('kill.piece', lambda c: [Destroy(c.state.players[1].board[1])])
        for source, expected in (('conditional.two', 1), ('building.source', 2)):
            with self.subTest(source=source):
                g = self.game(board=(source, 'piece'), hand=('kill.piece',))
                self.play(g, 'kill.piece')
                self.assertTrue(any(g.state.entities[i].starship_building for i in g.state.players[1].board))
                self.use(g)
                self.assertEqual((self.counts(g), self.armor(g)), ([expected], expected))
                self.portable(g)

    def test_board_location_is_not_a_minion_witness_and_does_not_demand_metadata(self):
        self.install('card', CardDefinition('location', 'Location', CardType.LOCATION,
            durability=2, on_use='noop'))
        g = self.game(board=('conditional.two', 'location'))
        self.use(g)
        self.assertEqual((self.counts(g), self.armor(g)), ([1], 1))
        self.portable(g)

    def test_late_retained_invoke_uses_its_batch_window_after_an_accepted_child_root(self):
        def parent(c):
            if c.rewind_attempt == 0 and c.power_payload.repeat_index == 1:
                extra = hero_power_references(c.state, 1, scope='additional')[0]
                return [TriggerHeroPower(1, c.source_id, targeting='explicit', choices='player', power=extra),
                    GainArmor(1, 1)]
            if c.rewind_attempt == 1 and c.power_payload.repeat_index == 1:
                return [Silence(c.state.players[1].board[0]), ask(c, GainArmor(1, 1))]
            return [GainArmor(1, 1)]
        self.power('retained.parent', parent, keywords=(Keyword.REWIND,), rewind=RewindSpec(1))
        g = self.game(power='retained.parent', extras=('power',),
            board=('plain', 'conditional.two', 'beast', 'retainer'), hand=('grant.false',))
        self.play(g, 'grant.false')
        carrier = self.find(g, 'plain')
        identity = next(a.id for a in g.state.entities[carrier].abilities if a.kind == 'hero_power_repeat')
        self.use(g)
        self.assertEqual(self.counts(g), [2, 2])
        self.assertTrue(self.roots(g)[1].completed)
        self.assertFalse(g.state.entities[carrier].abilities)
        snapshot = g.snapshot()
        invoke = self.nodes(snapshot['resolution_frame'], 'InvokeHeroPowerPayload')[-1]
        capture = invoke['fields']['context']['fields']['power_payload']['fields']
        child_batch = next(b for b in g.state.hero_power_payload_batches if b.power_id == 2)
        self.assertEqual((capture['power_id'], capture['iteration'], capture['repeat_index']), (1, 2, 2))
        self.assertGreater(capture['batch_id'], child_batch.id)
        self.portable(g)
        self.change_count(invoke['fields']['context'], identity, 4)
        self.reject(snapshot)
        self.finish(g)
        self.assertEqual(self.armor(g), 6)
        self.portable(g)

    def test_root_closing_rejects_whole_completed_batch_deletion_after_last_invoke(self):
        g, _, _ = self.dynamic_false_waiting()
        before = g.snapshot()
        from hs_sim.engine.hero_power_acceptance import validate_queue
        called = []
        def corrupt(state, registry, queue, maximum, **keywords):
            if keywords.get('closing') is not None:
                self.assertFalse(any(type(w).__name__ == 'InvokeHeroPowerPayload' for w in queue))
                state.hero_power_payload_batches.clear()
                state.hero_power_payload_history.clear()
                called.append(True)
            return validate_queue(state, registry, queue, maximum, **keywords)
        with patch('hs_sim.engine.hero_power_acceptance.validate_queue', side_effect=corrupt):
            with self.assertRaises(ResolutionError):
                self.choose(g)
        self.assertTrue(called)
        self.assertEqual(g.snapshot(), before)
        self.finish(g)
        self.assertEqual(self.armor(g), 1)
        self.portable(g)

    def test_retained_root_closing_cannot_downgrade_to_ordinary_after_all_results(self):
        self.power('retained', lambda c: [ask(c, GainArmor(1, 1))],
            keywords=(Keyword.REWIND,), rewind=RewindSpec(1))
        g = self.game(power='retained', board=('conditional.two', 'beast', 'retainer'))
        self.use(g)
        for _ in range(3):
            self.portable(g)
            self.choose(g)
        before = g.snapshot()
        from hs_sim.engine.hero_power_acceptance import validate_queue
        called = []
        def corrupt(state, registry, queue, maximum, **keywords):
            if keywords.get('closing') is not None:
                state.rewind_outcomes.clear()
                state.hero_power_payload_history = [replace(row, capture=replace(row.capture,
                    outcome_id=None, iteration=1)) for row in state.hero_power_payload_history[:2]]
                state.hero_power_payload_batches = [replace(state.hero_power_payload_batches[0],
                    outcome_id=None, iteration=1)]
                called.append(True)
            return validate_queue(state, registry, queue, maximum, **keywords)
        with patch('hs_sim.engine.hero_power_acceptance.validate_queue', side_effect=corrupt):
            with self.assertRaises(ResolutionError):
                self.choose(g)
        self.assertTrue(called)
        self.assertEqual(g.snapshot(), before)
        self.finish(g)
        self.assertEqual(self.armor(g), 4)
        self.portable(g)

    def test_terminal_guard_rejects_ordinary_batch_removal_before_queue_drop(self):
        self.power('fatal', lambda c: [ask(c, Damage(c.state.players[2].hero_id, 30))])
        g = self.game(power='fatal', board=('conditional.two', 'beast'))
        self.use(g)
        before = g.snapshot()
        from hs_sim.engine.hero_power_acceptance import validate_terminal_queue
        called = []
        def corrupt(r, queue):
            r.state.hero_power_payload_batches.clear()
            r.state.hero_power_payload_history.clear()
            called.append(True)
            return validate_terminal_queue(r, queue)
        with patch('hs_sim.engine.hero_power_acceptance.validate_terminal_queue', side_effect=corrupt):
            with self.assertRaises(ResolutionError):
                self.choose(g)
        self.assertTrue(called)
        self.assertEqual(g.snapshot(), before)
        self.choose(g)
        self.assertEqual(g.state.status, 'finished')
        self.assertEqual(self.counts(g), [2])
        self.portable(g)

    def test_terminal_guard_rejects_retained_identity_removal_before_any_batch(self):
        self.power('retained', lambda c: [GainArmor(1, 1)],
            keywords=(Keyword.REWIND,), rewind=RewindSpec(1))
        self.watch('fatal', lambda c: [ask(c, Damage(c.state.players[2].hero_id, 30))], 'hero_power_started')
        g = self.game(power='retained', board=('conditional.two', 'beast', 'retainer', 'fatal'))
        self.use(g)
        self.assertFalse(g.state.hero_power_payload_batches)
        self.assertEqual(len(g.state.rewind_outcomes), 1)
        self.portable(g)
        before = g.snapshot()
        from hs_sim.engine.hero_power_acceptance import validate_terminal_queue
        called = []
        def corrupt(r, queue):
            r.state.rewind_outcomes.clear()
            called.append(True)
            return validate_terminal_queue(r, queue)
        with patch('hs_sim.engine.hero_power_acceptance.validate_terminal_queue', side_effect=corrupt):
            with self.assertRaises(ResolutionError):
                self.choose(g)
        self.assertTrue(called)
        self.assertEqual(g.snapshot(), before)
        self.choose(g)
        self.assertTrue(self.roots(g)[0].interrupted)
        self.assertEqual(self.armor(g), 0)
        self.portable(g)

    def test_false_removed_HP_id_cannot_reappear_as_other_global_attachment_family(self):
        for family in ('enchantment', 'dormancy', 'player_effects'):
            with self.subTest(family=family):
                self.setUp()
                if family == 'player_effects':
                    self.install('player_effect', PlayerEffectSpec('other.effect', 'plain'))
                def parent(c):
                    player = c.state.players[1]
                    after = Buff(player.board[1], health=1, source_id=c.source_id) if family == 'enchantment' else (
                        MakeDormant(player.board[1], 2) if family == 'dormancy' else
                        AddPlayerEffect(1, 'other.effect', c.source_id))
                    return [ask(c, Silence(player.board[0]), after, ask(c, GainArmor(1, 1)))]
                self.power('global.parent', parent)
                g = self.game(power='global.parent', board=('plain', 'beast'), hand=('grant.false',))
                self.play(g, 'grant.false')
                carrier = self.find(g, 'plain')
                identity = next(a.id for a in g.state.entities[carrier].abilities if a.kind == 'hero_power_repeat')
                self.use(g)
                self.choose(g)
                self.assertFalse(g.state.entities[carrier].abilities)
                self.portable(g)
                snapshot = g.snapshot()
                if family == 'player_effects':
                    foreign = snapshot['state']['players']['1']['player_effects'][0]
                else:
                    entity = snapshot['state']['entities'][str(self.find(g, 'beast'))]
                    foreign = entity['enchantments'][0] if family == 'enchantment' else entity['dormancy']
                self.assertGreater(foreign['id'], identity)
                foreign['id'] = identity
                self.reject(snapshot)
                self.finish(g)
                self.portable(g)

    def test_numeric_power_damage_and_inspire_remain_separate_from_matching_count(self):
        from hs_sim.engine.inspire import is_inspire
        def inspire(c):
            self.assertTrue(is_inspire(c.state, c.event, c.player_id))
            return [GainArmor(1, 10)]
        self.watch('inspire', inspire, 'hero_power_used')
        self.minion('numeric', health_rules=(HealthRule(HealthFlow.DAMAGE, HealthOp.SCALE, amount=2,
            source_relation='friendly', damage_kinds=(DamageKind.HERO_POWER,)),))
        self.power('ping', lambda c: [Damage(c.state.players[2].hero_id, 1, c.source_id, DamageKind.HERO_POWER)])
        g = self.game(power='ping', board=('conditional.two', 'beast', 'numeric', 'inspire'), hand=('trigger',))
        self.use(g)
        self.play(g)
        self.assertEqual((self.counts(g), self.armor(g), g.state.entities[g.state.players[2].hero_id].health),
            ([2, 2], 10, 22))
        self.assertEqual((sum(e.kind == 'hero_power_used' for e in g.events),
            sum(e.kind == 'hero_power_triggered' for e in g.events),
            g.state.players[1].hero_power_uses_this_turn), (1, 1, 1))
        self.portable(g)

    def test_custom_payload_consumption_and_expiry_filter_actual_body_set_before_matching_root(self):
        self.custom = True
        self.script('custom.filtered', lambda c: [InstallTestPowerPayloads(
            c.state.players[1].hero_power_id, ('armor', 'armor'), True, (0,), 1)])
        g = self.game(board=('conditional.two', 'beast'), hand=('custom.filtered',))
        self.play(g, 'custom.filtered')
        self.use(g)
        self.assertEqual((len(self.roots(g)[0].payloads), self.counts(g), self.armor(g)), (1, [2], 2))
        self.portable(g)
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.use(g)
        self.assertEqual((len(self.roots(g)[1].payloads), self.counts(g), self.armor(g)), (0, [2, 2], 2))
        self.assertTrue(self.roots(g)[1].completed)
        self.portable(g)

    def test_fresh_registry_fingerprint_change_is_rejected_with_matching_waiting_proof(self):
        g = self.waiting()
        different = self.fresh()
        different.register_repeat_witness_profile(RepeatWitnessProfile('unrelated.extra'))
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(g.snapshot(), different)

    def test_default_native_example_has_three_independent_roots_and_five_waits(self):
        from examples.hero_power_matching import run
        game, waiting, summary = run()
        self.assertEqual((len(waiting), summary['accepted_counts'], summary['contributor_counts']),
            (5, [3, 1, 1], [2, 0, 0]))
        self.assertEqual((summary['armor'], summary['final_mana'], summary['manual_uses']), (5, 6, 1))
        self.assertTrue(summary['default_mechanics_only'])
        self.assertEqual(summary['state_hash'], game.state_hash())
