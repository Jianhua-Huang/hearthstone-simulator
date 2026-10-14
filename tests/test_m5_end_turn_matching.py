"""B2-05 EndTurn source conditions and complete acceptance proof tests.

Fixtures use public actions and effects. Deliberate corruptions are adversarial inputs.
Internal tests do not certify official CN timing or complete card coverage.
"""
import copy
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, EndTurnSpec, Game, Keyword, LimitedTriggerSpec, PlayCard,
    PlayerEffectSpec, PlayerSetup, Registry, ResolutionError,
    ResolutionLimitExceeded, RewindSpec, Ruleset, Scenario, SelectChoice,
    SnapshotError, TriggerHeroPower, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, EquipWeapon, GainArmor, InvokeBehavior, RandomDamage, ReplaceHeroPower,
    RequestChoice, ReturnToHand, Silence, Summon, Transform, TriggerDeathrattles)
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.end_turn_repeats import GrantEndTurnRepeatAura, capture_plan
from hs_sim.engine.end_turns import TriggerEndTurnEffects, activated_end_turns
from hs_sim.engine.end_turn_producers import TriggerRandomEndTurnEffects
from hs_sim.engine.hero_powers import AddHeroPower, RemoveHeroPower, hero_power_references
from hs_sim.engine.model import (AbilityInstance, BattlecryRepeatSpec, ComboRepeatSpec,
    DeathrattleRepeatSpec, EndTurnRepeatMatchSpec, EndTurnRepeatPlan, EndTurnRepeatSpec,
    HeroPowerRepeatSpec, QuestSpec, QuestStageSpec, SecretSpec,
    EndTurnRequest, EndTurnSelector, EndTurnProducerRequest, RepeatSourceEligibility,
    RepeatWitnessProfile, SpellRepeatSpec, RecipientMetadataFilter, RepeatMatchSpec, SpellSchool)
from hs_sim.engine.player_effects import AddPlayerEffect, RemovePlayerEffect, TickPlayerEffect
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import PlayFromHand
from hs_sim.engine.serialization import canonical_hash


def matrix(group, *preaudit):
    """Static mapping metadata, never a success or execution annotation."""
    def decorate(method):
        method.design_group = group
        method.design_scenarios = preaudit
        return method
    return decorate


def metadata(tribes=()):
    return CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=tribes)


def condition(tribes=('beast',), *, another=True, profile='repeat.witness.controlled'):
    return RepeatSourceEligibility(profile, tribes_any=tribes, exclude_carrier=another)


def spec(count=2, scope='all', eligibility=None):
    return EndTurnRepeatSpec(count, scope, None if eligibility is None else
        EndTurnRepeatMatchSpec(source_eligibility=eligibility))


def request(players=(1,), carriers=('minion', 'weapon', 'location', 'hero_power', 'player_effect'),
            *, entities=(), effects=(), mode='owner', profile='end_turn.effect'):
    return EndTurnRequest(EndTurnSelector(mode, players, carriers, entities, effects), profile)


def ask(c, *effects):
    return RequestChoice(c.player_id, (ChoiceOption('ok', 'Resolve', tuple(effects)),),
        source_id=c.source_id)


def fixture_registry():
    r = Registry('end-turn-matching-public-fixtures-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30, metadata=metadata()))
    r.register_behavior('armor', lambda c: [GainArmor(c.player_id, 1)])
    r.register_behavior('noop', lambda c: [])
    r.register_behavior('wait', lambda c: [ask(c, GainArmor(c.player_id, 1))])
    r.register_behavior('expire', lambda c: [GainArmor(c.player_id, 99)])
    r.register_trigger_condition('never', lambda c: False)
    r.register_trigger_condition('not_bool', lambda c: 1)
    for name, tribes in (('plain', ()), ('beast', ('beast',)), ('dragon', ('dragon',)),
            ('multi', ('beast', 'dragon')), ('all', ('all',)), ('unknown.tribes', None)):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=6, metadata=metadata(tribes)))
    r.register_card(CardDefinition('unknown.metadata', 'Unknown', CardType.MINION, health=6))
    for name, behavior, turn_scope, body_condition in (
            ('end', 'armor', 'controller', 'always'), ('waiting', 'wait', 'controller', 'always'),
            ('never', 'armor', 'controller', 'never'), ('bad.condition', 'armor', 'controller', 'not_bool'),
            ('opponent', 'armor', 'opponent', 'always'), ('either', 'armor', 'either', 'always')):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=6, metadata=metadata(),
            triggers=(TriggerSpec('turn_ended', behavior, EndTurnSpec(turn_scope, body_condition)),)))
    for name, count, scope, eligibility in (
            ('two', 2, 'all', None), ('three', 3, 'all', None),
            ('conditional.two', 2, 'all', condition()), ('conditional.three', 3, 'all', condition()),
            ('conditional.minion', 2, 'minion', condition()),
            ('false.source', 5, 'all', condition(('dragon',)))):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=6, metadata=metadata(),
            end_turn_repeats=(spec(count, scope, eligibility),)))
    r.register_card(CardDefinition('finite', 'finite', CardType.MINION, health=6, metadata=metadata(),
        limited_triggers=(LimitedTriggerSpec('turn_ended', 'wait', uses=2, end_turn=EndTurnSpec()),)))
    r.register_card(CardDefinition('dormant', 'dormant', CardType.MINION, health=6,
        dormant_turns=2, dormant_triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),),
        metadata=metadata(('beast',))))
    r.register_card(CardDefinition('weapon', 'weapon', CardType.WEAPON, attack=1, durability=3,
        triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),)))
    r.register_card(CardDefinition('location', 'location', CardType.LOCATION, durability=2,
        on_use='noop', triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),)))
    r.register_card(CardDefinition('power', 'Power', CardType.HERO_POWER, cost=2, on_use='armor'))
    r.register_card(CardDefinition('end.power', 'End power', CardType.HERO_POWER,
        passive_hero_power=True, triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),)))
    r.register_card(CardDefinition('retainer', 'Retainer', CardType.MINION, health=6,
        retain_rewind_outcomes=True, metadata=metadata()))
    return r


class EndTurnMatchingTests(unittest.TestCase):
    def setUp(self):
        self.r = fixture_registry()
        self.entries = []
        self.script('invoke', lambda c: [TriggerEndTurnEffects(1, request(), c.source_id)])
        self.script('grant.false', lambda c: [GrantEndTurnRepeatAura(c.state.players[1].board[0],
            spec(5, eligibility=condition(('dragon',))), c.source_id)])

    def install(self, kind, *values):
        getattr(self.r, 'register_' + kind)(*values)
        self.entries.append((kind, values))

    def fresh(self):
        r = fixture_registry()
        for kind, values in self.entries:
            getattr(r, 'register_' + kind)(*values)
        self.assertEqual(r.fingerprint(), self.r.fingerprint())
        return r

    def behavior(self, name, callback):
        self.install('behavior', name, callback)

    def minion(self, name, **fields):
        fields.setdefault('health', 6)
        fields.setdefault('metadata', metadata())
        self.install('card', CardDefinition(name, name, CardType.MINION, **fields))

    def source(self, name, declaration, **fields):
        self.minion(name, end_turn_repeats=(declaration,), **fields)

    def body(self, name, callback, *, kind='ordinary', **fields):
        self.behavior(name, callback)
        if kind == 'limited':
            fields['limited_triggers'] = (LimitedTriggerSpec('turn_ended', name,
                uses=fields.pop('uses', 2), end_turn=EndTurnSpec()),)
        else:
            fields['triggers'] = (TriggerSpec('turn_ended', name, EndTurnSpec()),)
        self.minion(name, **fields)

    def raw(self, name, callback, event='turn_ended'):
        self.behavior(name, callback)
        self.minion(name, triggers=(TriggerSpec(event, name),))

    def script(self, name, callback, **fields):
        self.behavior(name, callback)
        fields.setdefault('cost', 1)
        self.install('card', CardDefinition(name, name, CardType.SPELL, on_play=name,
            metadata=metadata(), **fields))

    def power(self, name, callback, **fields):
        self.behavior(name, callback)
        fields.setdefault('cost', 2)
        self.install('card', CardDefinition(name, name, CardType.HERO_POWER, on_use=name, **fields))

    def player_spec(self, name, *, scope='all', duration=None, repeats=(2,), triggers=(), shared=False):
        self.install('player_effect', PlayerEffectSpec(name, 'plain',
            kind='persistent' if duration is None else 'objective', duration=duration,
            tick_event=None if duration is None else 'turn_ended',
            end_turn_repeats=tuple(spec(n, scope) for n in repeats), triggers=triggers,
            deathrattle_repeats=(DeathrattleRepeatSpec(),) if shared else ()))
        self.script('add.' + name, lambda c, n=name: [AddPlayerEffect(1, n,
            c.state.players[1].board[0] if c.state.players[1].board else c.source_id)])

    def game(self, *, board=(), enemy=(), hand=('invoke',), enemy_hand=(), power='power',
             weapon=None, rules=None, seed=115, deck=('plain',) * 20):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', board=board, hand=hand, deck=deck, mana=10, max_mana=10,
                hero_power_card_id=power, weapon_card_id=weapon),
            PlayerSetup('hero', board=enemy, hand=enemy_hand, deck=('plain',) * 20,
                mana=10, max_mana=10, hero_power_card_id='power')), seed=seed), self.r, ruleset=rules)

    def find(self, g, name, player=1, zone='board'):
        return next(i for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == name)

    def play(self, g, name='invoke'):
        owner = g.state.active_player
        entity = self.find(g, name, owner, 'hand')
        g.apply(PlayCard(owner, entity))
        return entity

    def end(self, g):
        g.apply(EndTurn(g.state.active_player))

    def choose(self, g, option='ok'):
        choice = g.state.pending_choice
        self.assertIsNotNone(choice)
        g.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def finish(self, g):
        for _ in range(100):
            if g.state.pending_choice is None:
                return
            self.portable(g)
            self.choose(g)
        self.fail('Fixture did not settle within 100 choices')

    def armor(self, g, owner=1):
        return g.state.entities[g.state.players[owner].hero_id].armor

    def counts(self, g, index=-1):
        return [p.repetitions for p in g.state.end_turn_batches[index].plans]

    def portable(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot, self.fresh()).snapshot(), snapshot)
        self.assertEqual(g.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(g), self.fresh()).snapshot(), snapshot)

    def nodes(self, value, name):
        result = []
        def visit(v):
            if isinstance(v, dict):
                if v.get('type', '').split('.')[-1] == name:
                    result.append(v)
                for key, child in v.items():
                    if key == 'fields' and v.get('type') == 'hs_sim.engine.paid_hand_acceptance.PaidHandChoiceBoundaryProof':
                        for field, operand in child.items():
                            if field != 'work':
                                visit(operand)
                    else:
                        visit(child)
            elif isinstance(v, list):
                for child in v:
                    visit(child)
        visit(value)
        return result

    def fields(self, value):
        return value.get('fields', value)

    def edit_ability(self, value, identity, edit):
        changed = []
        def visit(v):
            if isinstance(v, dict):
                fields = v.get('fields') if v.get('type', '').split('.')[-1] == 'AbilityInstance' else v
                if (isinstance(fields, dict) and fields.get('id') == identity and
                        {'kind', 'origin', 'consumed', 'remove_on_silence'} <= fields.keys()):
                    edit(fields)
                    changed.append(True)
                for child in tuple(v.values()):
                    visit(child)
            elif isinstance(v, list):
                for child in v:
                    visit(child)
        visit(value)
        return len(changed)

    def change_count(self, value, identity, count=4):
        changed = self.edit_ability(value, identity, lambda a:
            self.fields(a['end_turn_repeat']).__setitem__('repetitions', count))
        self.assertGreater(changed, 0)

    def rehash(self, snapshot):
        snapshot['events_hash'] = canonical_hash(snapshot['events'])
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})

    def reject(self, g, snapshot):
        before = g.snapshot()
        self.portable(g)
        self.rehash(snapshot)
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(snapshot, self.fresh())
        self.assertNotIn('digest mismatch', str(error.exception))
        self.assertEqual(g.snapshot(), before)

    def waiting(self, *, natural=False, board=('conditional.three', 'beast', 'waiting'), **fields):
        g = self.game(board=board, **fields)
        self.end(g) if natural else self.play(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.portable(g)
        return g

    def dynamic_false(self, *, body='waiting', natural=False, hand=()):
        g = self.game(board=('plain', body), hand=('grant.false', 'invoke', *hand))
        self.play(g, 'grant.false')
        carrier = self.find(g, 'plain')
        identity = next(a.id for a in g.state.entities[carrier].abilities if a.kind == 'end_turn_repeat')
        self.end(g) if natural else self.play(g)
        self.assertEqual(self.counts(g), [1])
        self.assertIsNotNone(g.state.pending_choice)
        self.portable(g)
        return g, carrier, identity

    def queue(self, snapshot):
        return snapshot['resolution_frame']['fields']['continuation']['tuple']

    @matrix('ET-V01', 'ETM-10', 'ETM-40')
    def test_match_model_strict_type_scope_and_boolean_rejection(self):
        self.assertEqual(spec().match, None)
        self.assertEqual(spec(eligibility=condition()).match.source_eligibility, condition())
        for constructor in (lambda: spec(True), lambda: spec(scope='self'),
                lambda: EndTurnRepeatMatchSpec({}), lambda: EndTurnRepeatSpec(match={}),
                lambda: EndTurnRepeatMatchSpec(source_eligibility=True)):
            with self.subTest(constructor=constructor):
                with self.assertRaises(ValueError):
                    constructor()

    @matrix('ET-V01', 'ETM-43')
    def test_source_only_contract_rejects_recipient_self_tribe_and_kind_fields(self):
        for fields in ({'recipient_metadata': None}, {'tribes_any': ('beast',)}, {'scope': 'self'}):
            with self.subTest(fields=fields):
                with self.assertRaises(TypeError):
                    EndTurnRepeatMatchSpec(**fields)
        with self.assertRaises(TypeError):
            EndTurnRepeatSpec(kinds=(CardType.MINION,))

    @matrix('ET-V01', 'ETM-12')
    def test_player_spec_rejects_physical_source_but_accepts_explicit_empty_match(self):
        legal = PlayerEffectSpec('legal', 'plain', end_turn_repeats=(
            EndTurnRepeatSpec(match=EndTurnRepeatMatchSpec()), spec(scope='minion')))
        self.install('player_effect', legal)
        with self.assertRaises(ValueError):
            PlayerEffectSpec('bad', 'plain', end_turn_repeats=(spec(eligibility=condition()),))

    @matrix('ET-V01', 'ETM-10', 'ETM-11')
    def test_registration_rejects_unknown_profile_and_nonminion_carrier(self):
        with self.assertRaises(ValueError):
            self.source('missing', spec(eligibility=condition(profile='missing.profile')))
        with self.assertRaises(ValueError):
            self.install('card', CardDefinition('bad.weapon', 'Bad', CardType.WEAPON,
                attack=1, durability=2, end_turn_repeats=(spec(eligibility=condition()),)))
        g = self.game(board=('conditional.two', 'beast', 'end'))
        self.play(g)
        self.assertEqual((self.counts(g), self.armor(g)), ([2], 2))
        self.portable(g)

    @matrix('ET-V01', 'ETM-10')
    def test_unknown_profile_dynamic_stale_grant_rolls_back_paid_action(self):
        self.script('bad.grant', lambda c: [GrantEndTurnRepeatAura(c.state.players[1].hero_id,
            spec(eligibility=condition(profile='missing.profile')), c.source_id)])
        self.script('legal.stale', lambda c: [GrantEndTurnRepeatAura(c.state.players[1].hero_id,
            spec(eligibility=condition()), c.source_id)])
        g = self.game(hand=('bad.grant', 'legal.stale'))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'bad.grant')
        self.assertEqual(g.snapshot(), before)
        self.play(g, 'legal.stale')
        self.assertFalse(g.state.end_turn_batches)
        self.portable(g)

    @matrix('ET-V01', 'ETM-10', 'ETM-11')
    def test_waiting_frame_unknown_profile_rejected_before_stale_effect_can_skip(self):
        self.script('stale.wait', lambda c: [ask(c, GrantEndTurnRepeatAura(c.state.players[1].hero_id,
            spec(eligibility=condition()), c.source_id))])
        g = self.game(hand=('stale.wait',))
        self.play(g, 'stale.wait')
        snapshot = g.snapshot()
        declaration = self.nodes(snapshot['resolution_frame'], 'RepeatSourceEligibility')[0]['fields']
        declaration['profile_id'] = 'missing.profile'
        self.reject(g, snapshot)
        self.finish(g)
        self.portable(g)

    @matrix('ET-V01', 'ETM-11')
    def test_unknown_profiles_on_false_all_zone_and_consumed_declarations(self):
        for place in ('hand', 'deck', 'enemy', 'dormant', 'consumed'):
            with self.subTest(place=place):
                self.setUp()
                self.script('sleep', lambda c: [MakeDormant(c.state.players[1].board[0], 2)])
                fields = {'hand': ('false.source',)} if place == 'hand' else {
                    'deck': ('false.source',)} if place == 'deck' else {
                    'enemy': ('false.source',)} if place == 'enemy' else {
                    'board': ('false.source',), 'hand': ('sleep',)}
                g = self.game(**fields)
                if place == 'dormant':
                    self.play(g, 'sleep')
                if place == 'consumed':
                    entity = g._state.entities[self.find(g, 'false.source')]
                    entity.abilities = [replace(a, consumed=True) if a.kind == 'end_turn_repeat' else a
                        for a in entity.abilities]
                snapshot = g.snapshot()
                identity = next(a.id for e in g.state.entities.values() for a in e.abilities
                    if a.kind == 'end_turn_repeat')
                def edit(a):
                    match = self.fields(self.fields(a['end_turn_repeat'])['match'])
                    self.fields(match['source_eligibility'])['profile_id'] = 'missing.profile'
                self.assertGreater(self.edit_ability(snapshot['state'], identity, edit), 0)
                # Consumed state is a compact invariant fixture; it is not replay-generated.
                if place == 'consumed':
                    self.rehash(snapshot)
                    with self.assertRaises(SnapshotError):
                        Game.from_snapshot(snapshot, self.fresh())
                else:
                    self.reject(g, snapshot)

    @matrix('ET-V01', 'ETM-11')
    def test_false_nonminion_attachment_and_frozen_weapon_declaration_rejected(self):
        self.install('card', CardDefinition('weapon.rattle', 'Weapon', CardType.WEAPON,
            attack=1, durability=1, deathrattle='noop'))
        self.script('equip', lambda c: [EquipWeapon(1, 'weapon.rattle')])
        g = self.game(hand=('equip', 'equip'))
        self.play(g, 'equip')
        self.play(g, 'equip')
        self.portable(g)
        template = self.game(board=('false.source',)).snapshot()['state']['entities']
        declaration = copy.deepcopy(next(a for e in template.values() for a in e['abilities']
            if a['kind'] == 'end_turn_repeat'))
        for destination in ('live.power', 'frozen.weapon'):
            with self.subTest(destination=destination):
                snapshot = g.snapshot()
                declaration['id'] = snapshot['state']['next_attachment_id']
                snapshot['state']['next_attachment_id'] += 1
                declaration['origin'] = 'granted'
                target = snapshot['state']['entities'][str(g.state.players[1].hero_power_id)]['abilities']
                if destination == 'frozen.weapon':
                    target = snapshot['state']['death_history'][0]['abilities']
                target.append(copy.deepcopy(declaration))
                self.reject(g, snapshot)

    @matrix('ET-V01', 'ETM-40')
    def test_private_wire_requires_match_and_exact_source_only_nested_fields(self):
        g = self.waiting()
        identity = next(a.id for a in g.state.entities[self.find(g, 'conditional.three')].abilities
            if a.kind == 'end_turn_repeat')
        for mutation in ('missing_match', 'missing_source', 'recipient', 'bool', 'unknown'):
            with self.subTest(mutation=mutation):
                snapshot = g.snapshot()
                def edit(a):
                    declaration = self.fields(a['end_turn_repeat'])
                    if mutation == 'missing_match':
                        declaration.pop('match')
                    elif mutation == 'missing_source':
                        self.fields(declaration['match']).pop('source_eligibility')
                    elif mutation == 'recipient':
                        self.fields(declaration['match'])['recipient_metadata'] = None
                    elif mutation == 'bool':
                        declaration['repetitions'] = True
                    else:
                        self.fields(self.fields(declaration['match'])['source_eligibility'])['extra'] = 1
                self.edit_ability(snapshot['state'], identity, edit)
                self.reject(g, snapshot)

    @matrix('ET-V01', 'ETM-40')
    def test_typed_match_family_substitution_and_previous_schema_rejected(self):
        g = self.waiting()
        snapshot = g.snapshot()
        nodes = self.nodes(snapshot['resolution_frame'], 'EndTurnRepeatMatchSpec')
        self.assertTrue(nodes)
        nodes[0]['type'] = 'hs_sim.engine.model.HeroPowerRepeatMatchSpec'
        self.reject(g, snapshot)
        snapshot = g.snapshot()
        snapshot['schema_version'] -= 1
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(snapshot, self.fresh())

    @matrix('ET-V02', 'ETM-01', 'ETM-02', 'ETM-03', 'ETM-17')
    def test_all_and_minion_scopes_intersect_conditions_for_five_subject_classes(self):
        for scope in ('all', 'minion'):
            with self.subTest(scope=scope):
                self.setUp()
                self.source('scoped', spec(scope=scope, eligibility=condition()))
                self.player_spec('body', repeats=(), triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),))
                g = self.game(board=('scoped', 'beast', 'end', 'location'), weapon='weapon',
                    power='end.power', hand=('add.body', 'invoke'))
                self.play(g, 'add.body')
                self.play(g)
                group = g.state.end_turn_batches[-1]
                expected = [2 if scope == 'all' or s.ability is not None and
                    self.r.card(s.card_id).kind == CardType.MINION else 1 for s in group.subjects]
                self.assertEqual(self.counts(g), expected)
                self.assertEqual(len(group.subjects), 5)
                self.assertEqual(self.armor(g), sum(expected))
                self.portable(g)

    @matrix('ET-V02', 'ETM-17', 'ETM-18')
    def test_effect_enemy_owner_uses_own_sources_not_requesting_player(self):
        self.script('enemy.invoke', lambda c: [TriggerEndTurnEffects(1,
            request(players=(2,), carriers=('minion',)), c.source_id)])
        g = self.game(board=('three',), enemy=('conditional.two', 'beast', 'end'), hand=('enemy.invoke',))
        self.play(g, 'enemy.invoke')
        self.assertEqual((self.counts(g), self.armor(g, 1), self.armor(g, 2)), ([2], 0, 2))
        self.assertEqual(g.state.end_turn_batches[-1].subjects[0].player_id, 2)
        self.portable(g)

    @matrix('ET-V02', 'ETM-18')
    def test_natural_body_scope_stays_separate_from_subject_source_owner(self):
        g = self.game(board=('conditional.two', 'beast', 'end', 'opponent', 'either'),
            enemy=('conditional.three', 'beast', 'end', 'opponent', 'either'))
        self.end(g)
        owner_counts = [(s.player_id, s.card_id, p.repetitions) for s, p in
            zip(g.state.end_turn_batches[-1].subjects, g.state.end_turn_batches[-1].plans)]
        self.assertEqual(owner_counts, [(1, 'end', 2), (1, 'either', 2), (2, 'opponent', 3), (2, 'either', 3)])
        self.assertEqual((self.armor(g, 1), self.armor(g, 2)), (4, 6))
        self.portable(g)

    @matrix('ET-V02', 'ETM-23')
    def test_phase_uses_real_start_event_and_condition_without_second_natural_clock(self):
        self.player_spec('clock', duration=3)
        self.raw('phase', lambda c: [TriggerEndTurnEffects(1,
            request(profile='end_turn.phase'), c.source_id, c.event)]
            if c.event.player_id == 1 else [], event='turn_started')
        g = self.game(board=('conditional.two', 'beast', 'end', 'phase'), hand=('add.clock',))
        self.play(g, 'add.clock')
        self.end(g)
        self.end(g)
        self.assertEqual(g.state.end_turn_batches[-1].activation.kind, 'phase')
        self.assertEqual(self.counts(g), [2])
        self.assertEqual(g.state.players[1].player_effects[0].remaining_turns, 2)
        self.assertEqual(len([e for e in g.events if e.kind == 'turn_ended']), 2)
        self.portable(g)

    @matrix('ET-V03', 'ETM-07')
    def test_another_excludes_actual_repeat_carrier_not_subject_or_same_face_copy(self):
        self.source('beast.source', spec(eligibility=condition()), metadata=metadata(('beast',)))
        for board, expected in ((('beast.source', 'end'), 1), (('beast.source', 'beast.source', 'end'), 2)):
            with self.subTest(board=board):
                g = self.game(board=board)
                self.play(g)
                self.assertEqual((self.counts(g), self.armor(g)), ([expected], expected))
                self.portable(g)

    @matrix('ET-V03', 'ETM-07')
    def test_control_presence_may_count_the_source_itself(self):
        self.source('presence', spec(eligibility=condition(another=False)), metadata=metadata(('beast',)))
        g = self.game(board=('presence', 'end'))
        self.play(g)
        self.assertEqual((self.counts(g), self.armor(g)), ([2], 2))
        self.portable(g)

    @matrix('ET-V03', 'ETM-09')
    def test_dormant_witness_and_dormant_source_have_distinct_policies(self):
        for profile, expected in (('repeat.witness.controlled', 2), ('repeat.witness.active_live', 1)):
            with self.subTest(profile=profile):
                self.setUp()
                self.source('profile.source', spec(eligibility=condition(profile=profile)))
                g = self.game(board=('profile.source', 'dormant', 'end'))
                self.play(g)
                self.assertEqual(self.counts(g), [expected, expected])
                self.portable(g)
        self.setUp()
        self.script('sleep', lambda c: [MakeDormant(c.state.players[1].board[0], 2)])
        g = self.game(board=('conditional.two', 'beast', 'end'), hand=('sleep', 'invoke'))
        self.play(g, 'sleep')
        self.play(g)
        self.assertEqual(self.counts(g), [1])
        self.portable(g)

    @matrix('ET-V03', 'ETM-09')
    def test_starship_building_witness_requires_explicit_presence_profile(self):
        self.install('repeat_witness_profile', RepeatWitnessProfile('building', include_starship_building=True))
        self.minion('ship', health=0, metadata=metadata(('beast',)), starship_for=(CardClass.NEUTRAL,))
        self.minion('piece', keywords=(Keyword.STARSHIP_PIECE,))
        self.source('building.source', spec(eligibility=condition(profile='building')))
        self.script('kill.piece', lambda c: [Destroy(c.state.players[1].board[1])])
        for source, expected in (('conditional.two', 1), ('building.source', 2)):
            with self.subTest(source=source):
                g = self.game(board=(source, 'piece', 'end'), hand=('kill.piece', 'invoke'))
                self.play(g, 'kill.piece')
                self.assertTrue(any(g.state.entities[i].starship_building for i in g.state.players[1].board))
                self.play(g)
                self.assertEqual(self.counts(g), [expected])
                self.portable(g)

    @matrix('ET-V03', 'ETM-09')
    def test_real_death_deferral_preserves_declared_doomed_and_health_witness_policy(self):
        for operation in (Destroy, lambda i: Damage(i, 6)):
            for profile, expected in (('repeat.witness.controlled', 2), ('repeat.witness.active_live', 1)):
                with self.subTest(operation=operation, profile=profile):
                    self.setUp()
                    self.source('profile.source', spec(eligibility=condition(profile=profile)))
                    self.minion('spell.repeat', spell_repeats=(SpellRepeatSpec(class_mode='any'),))
                    self.script('defer', lambda c, op=operation: [op(c.state.players[1].board[1]),
                        TriggerEndTurnEffects(1, request(), c.source_id)])
                    g = self.game(board=('profile.source', 'beast', 'spell.repeat', 'end'), hand=('defer',))
                    self.play(g, 'defer')
                    self.assertEqual([b.plans[0].repetitions for b in g.state.end_turn_batches], [expected, expected])
                    self.assertEqual(self.armor(g), 2 * expected)
                    self.portable(g)

    @matrix('ET-V03', 'ETM-08')
    def test_late_unknown_metadata_rejects_before_recipient_minion_scope_false(self):
        g = self.game(board=('conditional.minion', 'beast', 'unknown.metadata'),
            power='end.power')
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g)
        self.assertEqual(g.snapshot(), before)
        self.portable(g)

    @matrix('ET-V03', 'ETM-08')
    def test_late_unknown_tribes_rejects_after_first_known_matching_witness(self):
        g = self.game(board=('conditional.two', 'beast', 'unknown.tribes', 'end'))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g)
        self.assertEqual(g.snapshot(), before)
        self.portable(g)

    @matrix('ET-V03', 'ETM-08')
    def test_empty_tribes_and_irrelevant_enemy_or_location_need_no_metadata(self):
        self.source('any.source', spec(eligibility=condition(())))
        g = self.game(board=('any.source', 'unknown.metadata', 'location', 'end'), enemy=('unknown.metadata',))
        self.play(g)
        self.assertEqual(self.counts(g), [2, 2])
        self.portable(g)
        g = self.game(board=('conditional.two', 'location', 'end'), enemy=('unknown.metadata',))
        self.play(g)
        self.assertEqual(self.counts(g), [1, 1])
        self.portable(g)

    @matrix('ET-V03', 'ETM-04')
    def test_multi_all_and_or_queries_use_witness_current_face(self):
        self.source('or.source', spec(eligibility=condition(('beast', 'dragon'))))
        self.script('turn.dragon', lambda c: [Transform(c.state.players[1].board[1], 'dragon')])
        for witness in ('multi', 'all'):
            with self.subTest(witness=witness):
                g = self.game(board=('conditional.two', witness, 'end'))
                self.play(g)
                self.assertEqual(self.counts(g), [2])
                self.portable(g)
        g = self.game(board=('or.source', 'plain', 'end'), hand=('turn.dragon', 'invoke'))
        self.play(g, 'turn.dragon')
        self.play(g)
        self.assertEqual(self.counts(g), [2])
        self.portable(g)

    @matrix('ET-V04', 'ETM-14', 'ETM-15')
    def test_complete_max_keeps_lower_equal_and_same_carrier_independent_sources(self):
        self.minion('many.sources', end_turn_repeats=(spec(2, eligibility=condition()), spec(3)))
        g = self.game(board=('conditional.two', 'many.sources', 'three', 'beast', 'end'))
        self.play(g)
        plan = g.state.end_turn_batches[-1].plans[0]
        self.assertEqual((plan.repetitions, len(plan.contributors), self.armor(g)), (3, 4, 3))
        self.assertEqual([s.spec.repetitions for s in plan.contributors], [2, 2, 3, 3])
        self.assertEqual(len({s.key for s in plan.contributors}), 4)
        self.assertTrue(all(s.ability.end_turn_repeat == s.spec for s in plan.contributors))
        self.portable(g)

    @matrix('ET-V04', 'ETM-06', 'ETM-16')
    def test_body_condition_false_omits_subject_but_repeat_condition_false_keeps_body(self):
        g = self.game(board=('false.source', 'never', 'end'))
        self.play(g)
        self.assertEqual([s.card_id for s in g.state.end_turn_batches[-1].subjects], ['end'])
        self.assertEqual((self.counts(g), self.armor(g)), ([1], 1))
        self.portable(g)

    @matrix('ET-V04', 'ETM-16')
    def test_nonboolean_body_condition_rolls_back_natural_effect_and_random_roots(self):
        self.script('random', lambda c: [TriggerRandomEndTurnEffects(1,
            EndTurnProducerRequest(EndTurnSelector('owner', (1,), ('minion',))), c.source_id)])
        for route in ('natural', 'effect', 'random'):
            with self.subTest(route=route):
                g = self.game(board=('conditional.two', 'beast', 'bad.condition'), hand=('invoke', 'random'))
                before = g.snapshot()
                with self.assertRaises(ResolutionError):
                    self.end(g) if route == 'natural' else self.play(g, 'random' if route == 'random' else 'invoke')
                self.assertEqual(g.snapshot(), before)
                self.portable(g)

    @matrix('ET-V04', 'ETM-06', 'ETM-24')
    def test_source_false_to_true_changes_only_a_later_actual_group(self):
        self.body('summoner', lambda c: [Summon(1, 'beast'), GainArmor(1, 1)]
            if c.end_turn.repeat_index == 0 else [GainArmor(1, 1)])
        g = self.game(board=('conditional.two', 'summoner'), hand=('invoke', 'invoke'))
        self.play(g)
        self.assertEqual(self.counts(g), [1])
        self.play(g)
        self.assertEqual([b.plans[0].repetitions for b in g.state.end_turn_batches], [1, 2])
        self.assertEqual(self.armor(g), 3)
        self.portable(g)

    @matrix('ET-V05', 'ETM-05', 'ETM-19', 'ETM-24')
    def test_witness_removal_transform_or_transfer_keeps_extra_then_recaptures(self):
        for operation in (Destroy, lambda i: Transform(i, 'plain'), lambda i: ChangeControl(i, 2)):
            with self.subTest(operation=operation):
                self.setUp()
                self.body('changer', lambda c, op=operation: ([op(c.state.players[1].board[1])]
                    if c.end_turn.repeat_index == 0 and len(c.state.players[1].board) > 2 else []) +
                    [GainArmor(1, 1)])
                g = self.game(board=('conditional.two', 'beast', 'changer'), hand=('invoke', 'invoke'))
                self.play(g)
                self.assertEqual((self.counts(g), self.armor(g)), ([2], 2))
                self.play(g)
                self.assertEqual([b.plans[0].repetitions for b in g.state.end_turn_batches], [2, 1])
                self.portable(g)

    @matrix('ET-V05', 'ETM-19', 'ETM-24')
    def test_source_silence_bounce_transform_dormancy_keeps_accepted_max(self):
        for operation in (Silence, ReturnToHand, lambda i: Transform(i, 'plain'), lambda i: MakeDormant(i, 2)):
            with self.subTest(operation=operation):
                self.setUp()
                self.body('changer', lambda c, op=operation: ([op(c.state.players[1].board[0])]
                    if c.end_turn.repeat_index == 0 else []) + [GainArmor(1, 1)])
                g = self.game(board=('conditional.three', 'beast', 'changer'), hand=('invoke', 'invoke'))
                self.play(g)
                self.assertEqual((self.counts(g), self.armor(g)), ([3], 3))
                self.play(g)
                self.assertEqual(self.counts(g), [1])
                self.portable(g)

    @matrix('ET-V05', 'ETM-19')
    def test_copied_conditional_source_has_new_physical_identity_and_max_not_product(self):
        self.script('copy', lambda c: [CopyMinion(c.state.players[1].board[0], 1)])
        g = self.game(board=('conditional.two', 'beast', 'end'), hand=('copy', 'invoke'))
        self.play(g, 'copy')
        self.play(g)
        plan = g.state.end_turn_batches[-1].plans[0]
        self.assertEqual((plan.repetitions, len(plan.contributors)), (2, 2))
        self.assertEqual(len({s.carrier_id for s in plan.contributors}), 2)
        self.assertEqual(len({s.ability.id for s in plan.contributors}), 2)
        self.portable(g)

    @matrix('ET-V05', 'ETM-19')
    def test_transferred_source_old_owner_plan_stays_and_new_owner_recaptures(self):
        self.body('transfer', lambda c: [ChangeControl(c.state.players[1].board[0], 2), GainArmor(1, 1)]
            if c.end_turn.repeat_index == 0 else [GainArmor(1, 1)])
        self.script('enemy.invoke', lambda c: [TriggerEndTurnEffects(1,
            request(players=(2,), carriers=('minion',)), c.source_id)])
        g = self.game(board=('conditional.two', 'beast', 'transfer'), enemy=('beast', 'end'),
            hand=('invoke', 'enemy.invoke'))
        self.play(g)
        self.assertEqual(self.counts(g), [2])
        self.play(g, 'enemy.invoke')
        self.assertEqual((self.counts(g), self.armor(g, 2)), ([2], 2))
        self.portable(g)

    @matrix('ET-V06', 'ETM-30', 'ETM-44')
    def test_empty_group_validates_all_declarations_without_synthetic_witness_query(self):
        g = self.game(board=('conditional.two', 'unknown.metadata'))
        self.play(g)
        group = g.state.end_turn_batches[-1]
        self.assertEqual((group.subjects, group.plans, group.total), ((), (), 0))
        self.assertTrue(group.completed)
        self.portable(g)

    @matrix('ET-V06', 'ETM-30', 'ETM-32', 'ETM-44')
    def test_closed_selected_and_random_empty_children_remain_bound_by_waiting_parent(self):
        for route in ('selected', 'random'):
            with self.subTest(route=route):
                self.setUp()
                def outer(c):
                    plain = next(i for i in c.state.players[1].board if c.state.entities[i].card_id == 'plain')
                    selector = EndTurnSelector('selected', (1,), ('minion',), (plain,))
                    effect = TriggerEndTurnEffects(1, EndTurnRequest(selector), c.source_id)
                    if route == 'random':
                        effect = TriggerRandomEndTurnEffects(1, EndTurnProducerRequest(selector), c.source_id)
                    return [effect, ask(c, GainArmor(1, 1))]
                self.body('outer', outer)
                g = self.game(board=('plain', 'outer'), hand=('grant.false', 'invoke'))
                self.play(g, 'grant.false')
                carrier = self.find(g, 'plain')
                identity = next(a.id for a in g.state.entities[carrier].abilities if a.kind == 'end_turn_repeat')
                self.play(g)
                # Empty child has already legitimately closed before caller's ask;
                # its complete historical marker is bound by the unfinished parent proof.
                self.assertIsNotNone(g.state.pending_choice)
                self.assertEqual(g.state.end_turn_batches[-1].subjects, ())
                self.assertTrue(g.state.end_turn_batches[-1].completed)
                self.portable(g)
                snapshot = g.snapshot()
                marker = self.nodes(snapshot['resolution_frame'], 'FinishEndTurnBatch')[0]
                self.change_count(marker['fields']['context'], identity)
                self.reject(g, snapshot)
                self.finish(g)
                self.portable(g)

    @matrix('ET-V06', 'ETM-31', 'ETM-32')
    def test_random_false_body_draws_once_but_truly_empty_pool_preserves_rng(self):
        self.script('random', lambda c: [TriggerRandomEndTurnEffects(1,
            EndTurnProducerRequest(EndTurnSelector('owner', (1,), ('minion',))), c.source_id)])
        for board, draw in ((('false.source', 'never'), True), (('false.source', 'plain'), False)):
            with self.subTest(board=board):
                g = self.game(board=board, hand=('random',))
                before = g._rng.getstate()
                self.play(g, 'random')
                selection = g.state.end_turn_batches[-1].activation.selection
                self.assertEqual(selection.rng_before != selection.rng_after, draw)
                self.assertEqual(before != g._rng.getstate(), draw)
                self.assertEqual(g.state.end_turn_batches[-1].subjects, ())
                self.portable(g)

    @matrix('ET-V07', 'ETM-25')
    def test_finite_natural_and_effect_guard_consumes_once_before_waiting_callback(self):
        for natural in (True, False):
            with self.subTest(natural=natural):
                g = self.waiting(natural=natural, board=('conditional.three', 'beast', 'finite'))
                finite = g.state.entities[self.find(g, 'finite')]
                ability = next(a for a in finite.abilities if a.kind == 'limited_trigger')
                self.assertEqual(ability.uses_remaining, 1)
                events = [e for e in g.events if e.kind == 'limited_trigger_used']
                self.assertEqual((len(events), events[0].amount), (1, 1))
                self.finish(g)
                self.assertEqual(self.armor(g), 3)
                self.assertEqual(len([e for e in g.events if e.kind == 'limited_trigger_used']), 1)
                self.assertTrue(all(row.guard_passed for row in g.state.end_turn_history))
                self.portable(g)

    @matrix('ET-V07', 'ETM-25')
    def test_first_finite_callback_reads_postconsumption_trigger_before_any_extra(self):
        self.body('post.finite', lambda c: [GainArmor(c.player_id, c.trigger.uses_remaining), ask(c)],
            kind='limited', uses=2)
        for natural in (True, False):
            with self.subTest(natural=natural):
                g = self.waiting(natural=natural, board=('conditional.three', 'beast', 'post.finite'))
                self.assertEqual(self.armor(g), 1)
                self.assertEqual([e.amount for e in g.events if e.kind == 'limited_trigger_used'], [1])
                self.finish(g)
                self.assertEqual(self.armor(g), 3)
                self.assertEqual(len([e for e in g.events if e.kind == 'limited_trigger_used']), 1)
                self.portable(g)

    @matrix('ET-V07', 'ETM-26')
    def test_nested_same_finite_subject_has_independent_once_only_consumption(self):
        def finite(c):
            return [TriggerEndTurnEffects(1, request(mode='selected', carriers=('minion',),
                entities=(c.source_id,)), c.source_id)] if c.end_turn.subject.ability.uses_remaining == 2 else [ask(c)]
        self.body('nested.finite', finite, kind='limited', uses=2)
        g = self.game(board=('conditional.two', 'beast', 'nested.finite'))
        self.play(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(g.state.end_turn_batches), 2)
        self.finish(g)
        self.assertEqual([e.amount for e in g.events if e.kind == 'limited_trigger_used'], [1, 0])
        self.assertTrue(all(b.completed for b in g.state.end_turn_batches))
        self.portable(g)

    def first_then_guard(self, *, natural=False, kind='limited', skip=False):
        self.minion('dual')
        def first(c):
            dual = next(i for i in c.state.players[1].board if c.state.entities[i].card_id == 'dual')
            effects = [Silence(dual)]
            if skip:
                effects.append(RemoveHeroPower(1, power=hero_power_references(c.state, 1, scope='additional')[0])
                    if kind == 'hero_power' else Destroy(next(i for i in c.state.players[1].board
                        if c.state.entities[i].card_id == 'last')))
            return [ask(c, *effects, ask(c))]
        self.body('first', first)
        if kind == 'hero_power':
            self.power('last', lambda c: [GainArmor(1, 1)],
                triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),))
            self.script('install.last', lambda c: [AddHeroPower(1, 'last', c.source_id)])
        else:
            self.body('last', lambda c: [GainArmor(1, 1)], kind=kind)
        g = self.game(board=('dual', 'first') if kind == 'hero_power' else ('dual', 'first', 'last'),
            hand=('grant.false', 'invoke', 'install.last') if kind == 'hero_power' else ('grant.false', 'invoke'))
        self.play(g, 'grant.false')
        identity = next(a.id for a in g.state.entities[self.find(g, 'dual')].abilities
            if a.kind == 'end_turn_repeat')
        if kind == 'hero_power':
            self.play(g, 'install.last')
        self.end(g) if natural else self.play(g)
        self.choose(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(g.state.entities[self.find(g, 'dual')].abilities)
        self.portable(g)
        return g, identity

    def guard_negative(self, *, natural, kind, skip=False):
        g, identity = self.first_then_guard(natural=natural, kind=kind, skip=skip)
        name = 'CheckLimitedTrigger' if natural and kind == 'limited' else (
            'CheckHeroPowerTrigger' if natural and kind == 'hero_power' else 'CheckActiveEndTurn')
        self.assertTrue(self.nodes(g.snapshot()['resolution_frame'], name))
        before = g.snapshot()
        from hs_sim.engine.end_turn_acceptance import validate_control_work
        called = []
        def corrupt(r, work):
            if type(work).__name__ == name:
                context = (work.end_turn_context if name == 'CheckLimitedTrigger' else
                    work.context if name == 'CheckHeroPowerTrigger' else work.acceptance)
                if context is not None and context.end_turn is not None and context.source.card_id == 'last':
                    saved = copy.deepcopy(context.state)
                    for e in saved.entities.values():
                        e.abilities = [replace(a, end_turn_repeat=replace(a.end_turn_repeat, repetitions=4))
                            if a.id == identity else a for a in e.abilities]
                    changed = replace(context, state=saved)
                    if name == 'CheckLimitedTrigger':
                        work = replace(work, end_turn_context=changed)
                    elif name == 'CheckHeroPowerTrigger':
                        work = replace(work, context=changed)
                    else:
                        work = replace(work, context=changed, acceptance=changed)
                    called.append(True)
            return validate_control_work(r, work)
        with patch('hs_sim.engine.end_turn_acceptance.validate_control_work', side_effect=corrupt):
            with self.assertRaises(ResolutionError):
                self.choose(g)
        self.assertTrue(called)
        self.assertEqual(g.snapshot(), before)
        self.finish(g)
        self.assertTrue(g.state.end_turn_batches[-1].completed)
        self.portable(g)

    @matrix('ET-V07', 'ETM-27')
    def test_effect_finite_guard_rejects_false_original_change_before_legal_skip(self):
        self.guard_negative(natural=False, kind='limited', skip=True)

    @matrix('ET-V07', 'ETM-25', 'ETM-27')
    def test_natural_finite_guard_binds_independent_original_false_declaration(self):
        self.guard_negative(natural=True, kind='limited')

    @matrix('ET-V08', 'ETM-28')
    def test_effect_installed_power_guard_rejects_false_original_change_before_skip(self):
        self.guard_negative(natural=False, kind='hero_power', skip=True)

    @matrix('ET-V08', 'ETM-28')
    def test_natural_installed_power_guard_uses_real_late_installation_order(self):
        self.guard_negative(natural=True, kind='hero_power')

    @matrix('ET-V08', 'ETM-28')
    def test_installed_end_power_repeats_do_not_pay_or_use_manual_power(self):
        g = self.game(board=('conditional.three', 'beast'), power='end.power')
        before_mana = g.state.players[1].mana
        self.play(g)
        self.assertEqual((self.counts(g), self.armor(g)), ([3], 3))
        self.assertEqual(g.state.players[1].mana, before_mana - 1)
        self.assertFalse(g.state.hero_power_history)
        self.assertNotIn('hero_power_started', [e.kind for e in g.events])
        self.portable(g)

    @matrix('ET-V08', 'ETM-24', 'ETM-28')
    def test_installed_power_replaced_in_body_keeps_old_extra_fresh_view(self):
        self.behavior('replace.self', lambda c: [ReplaceHeroPower(1, 'power', source_id=c.source_id),
            GainArmor(1, 1)])
        self.install('card', CardDefinition('replace.power', 'Replace', CardType.HERO_POWER,
            passive_hero_power=True, triggers=(TriggerSpec('turn_ended', 'replace.self', EndTurnSpec()),)))
        g = self.game(board=('conditional.two', 'beast'), power='replace.power')
        old = g.state.players[1].hero_power_id
        self.play(g)
        self.assertEqual(self.armor(g), 2)
        self.assertNotEqual(g.state.players[1].hero_power_id, old)
        self.assertEqual({r.capture.subject.source_id for r in g.state.end_turn_history}, {old})
        self.portable(g)

    @matrix('ET-V09', 'ETM-03', 'ETM-12', 'ETM-13')
    def test_source_independent_player_policy_survives_donor_transform_death_and_transfer(self):
        self.player_spec('policy', repeats=(2, 3))
        operations = (Destroy, lambda i: Transform(i, 'dragon'), lambda i: ChangeControl(i, 2))
        for index, operation in enumerate(operations):
            self.script('change.' + str(index), lambda c, op=operation: [op(c.state.players[1].board[0])])
        for index, operation in enumerate(operations):
            with self.subTest(operation=operation):
                name = 'change.' + str(index)
                g = self.game(board=('plain', 'end'), hand=('add.policy', name, 'invoke'))
                self.play(g, 'add.policy')
                instance = g.state.players[1].player_effects[0]
                self.play(g, name)
                self.play(g)
                plan = g.state.end_turn_batches[-1].plans[0]
                self.assertEqual((plan.repetitions, len(plan.contributors), self.armor(g)), (3, 2, 3))
                self.assertEqual([s.spec_index for s in plan.contributors], [0, 1])
                self.assertTrue(all(s.player_effect.id == instance.id for s in plan.contributors))
                self.portable(g)

    @matrix('ET-V09', 'ETM-03')
    def test_minion_policy_does_not_turn_player_body_into_donor_minion(self):
        self.player_spec('policy', scope='minion')
        self.player_spec('body', repeats=(), triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),))
        g = self.game(board=('plain', 'end'), hand=('add.policy', 'add.body', 'invoke'))
        self.play(g, 'add.policy')
        self.play(g, 'add.body')
        self.play(g)
        group = g.state.end_turn_batches[-1]
        self.assertEqual([p.repetitions for s, p in zip(group.subjects, group.plans) if s.player_effect is None], [2])
        self.assertEqual([p.repetitions for s, p in zip(group.subjects, group.plans) if s.player_effect is not None], [1])
        self.portable(g)

    @matrix('ET-V10', 'ETM-13', 'ETM-20', 'ETM-22', 'ETM-23')
    def test_three_natural_owner_roots_capture_three_two_one_and_expire_once(self):
        self.player_spec('clock', duration=3)
        g = self.game(board=('end',), hand=('add.clock',))
        self.play(g, 'add.clock')
        clocks = []
        for n in range(3):
            self.end(g)
            plan = g.state.end_turn_batches[-1].plans[0]
            clocks.append(plan.contributors[0].player_effect.remaining_turns)
            self.portable(g)
            if n != 2:
                self.end(g)
        self.assertEqual(clocks, [3, 2, 1])
        self.assertFalse(g.state.players[1].player_effects)
        self.assertEqual(self.armor(g), 6)
        self.portable(g)

    @matrix('ET-V10', 'ETM-13', 'ETM-23')
    def test_effect_roots_keep_two_independent_instances_and_shared_dr_end_spec_index(self):
        self.player_spec('shared', duration=3, repeats=(2, 3), shared=True)
        self.minion('rattle', deathrattle='armor')
        self.script('dr', lambda c: [TriggerDeathrattles(c.state.players[1].board[1], c.source_id)])
        g = self.game(board=('plain', 'rattle', 'end'), hand=('add.shared', 'add.shared', 'dr', 'invoke'))
        self.play(g, 'add.shared')
        self.play(g, 'add.shared')
        self.play(g, 'dr')
        self.play(g)
        plan = g.state.end_turn_batches[-1].plans[0]
        self.assertEqual((plan.repetitions, len(plan.contributors)), (3, 4))
        self.assertEqual(len({s.player_effect.id for s in plan.contributors}), 2)
        self.assertEqual([s.player_effect.remaining_turns for s in plan.contributors], [3] * 4)
        self.assertEqual(g.state.deathrattle_batches[-1].payloads[0].plan.repetitions, 2)
        self.portable(g)

    @matrix('ET-V10', 'ETM-20', 'ETM-21', 'ETM-29')
    def test_new_instance_during_natural_body_is_not_in_original_countdown_tail(self):
        self.player_spec('short', duration=1)
        self.body('new.instance', lambda c: [AddPlayerEffect(1, 'short', c.source_id)]
            if c.end_turn.repeat_index == 0 else [])
        g = self.game(board=('new.instance',), hand=('add.short',))
        self.play(g, 'add.short')
        original = g.state.players[1].player_effects[0].id
        self.end(g)
        self.assertEqual([e.remaining_turns for e in g.state.players[1].player_effects], [1])
        self.assertNotEqual(g.state.players[1].player_effects[0].id, original)
        self.assertEqual(self.counts(g), [2])
        self.portable(g)

    @matrix('ET-V10', 'ETM-22')
    def test_opponent_scope_subject_does_not_tick_its_owner_player_policy(self):
        self.player_spec('clock', duration=3)
        g = self.game(board=('opponent',), hand=('add.clock',))
        self.play(g, 'add.clock')
        self.end(g)
        self.assertEqual(g.state.players[1].player_effects[0].remaining_turns, 2)
        self.end(g)
        self.assertEqual(g.state.players[1].player_effects[0].remaining_turns, 2)
        self.assertEqual(self.counts(g), [2])
        self.portable(g)

    @matrix('ET-V10', 'ETM-13', 'ETM-35', 'ETM-37')
    def test_false_player_policy_expiry_cannot_hide_later_foreign_clock_increase(self):
        # Parent is physical HP, so its minion-only PE declaration is genuinely false.
        self.player_spec('clock', scope='minion', duration=3, shared=True)
        self.minion('rattle', deathrattle='armor')
        def parent(c):
            target = next(i for i in c.state.players[1].board if c.state.entities[i].card_id == 'rattle')
            instance = c.state.players[1].player_effects[0]
            return [TriggerDeathrattles(target, c.source_id), TickPlayerEffect(1, instance.id, 3),
                TriggerDeathrattles(target, c.source_id), TickPlayerEffect(1, instance.id, 2),
                TriggerDeathrattles(target, c.source_id), TickPlayerEffect(1, instance.id, 1), ask(c)]
        self.behavior('clock.parent', parent)
        self.install('card', CardDefinition('clock.parent', 'Parent', CardType.HERO_POWER,
            passive_hero_power=True, triggers=(TriggerSpec('turn_ended', 'clock.parent', EndTurnSpec()),)))
        g = self.game(board=('rattle',), power='clock.parent', hand=('add.clock', 'invoke'))
        self.play(g, 'add.clock')
        self.play(g)
        self.assertFalse(g.state.players[1].player_effects)
        self.assertFalse(self.nodes(g.snapshot()['resolution_frame'], 'FinishDeathrattleBatch'))
        self.assertEqual(self.counts(g), [1])
        clocks = [b.payloads[0].plan.contributors[0].instance.remaining_turns for b in g.state.deathrattle_batches]
        self.assertEqual(clocks, [3, 2, 1])
        snapshot = g.snapshot()
        snapshot['state']['deathrattle_batches'][2]['payloads'][0]['plan']['contributors'][0]['instance']['remaining_turns'] = 3
        self.reject(g, snapshot)
        self.finish(g)
        self.assertEqual(self.armor(g), 6)
        self.portable(g)

    @matrix('ET-V06', 'ETM-44')
    def test_empty_prepare_group_rejects_bad_false_profile_and_rolls_back_before_positions(self):
        g = self.game(board=('false.source', 'unknown.metadata'))
        before = g.snapshot()
        from hs_sim.engine.end_turns import prepare_group
        calls = []
        def corrupt(r, event, activation, subjects):
            self.assertEqual(subjects, ())
            entity = r.state.entities[self.find(g, 'false.source')]
            entity.abilities = [replace(a, end_turn_repeat=spec(5,
                eligibility=condition(('dragon',), profile='missing.profile')))
                if a.kind == 'end_turn_repeat' else a for a in entity.abilities]
            calls.append(True)
            return prepare_group(r, event, activation, subjects)
        with patch('hs_sim.engine.end_turns.prepare_group', side_effect=corrupt):
            with self.assertRaises(ResolutionError):
                self.play(g)
        self.assertTrue(calls)
        self.assertEqual(g.snapshot(), before)
        self.play(g)
        self.assertEqual(g.state.end_turn_batches[-1].subjects, ())
        self.portable(g)

    @matrix('ET-V06', 'ETM-29', 'ETM-44')
    def test_natural_empty_group_finish_survives_ordinary_tail_choice(self):
        self.raw('tail', lambda c: [ask(c, GainArmor(1, 1))])
        g = self.game(board=('plain', 'tail'), hand=('grant.false',))
        self.play(g, 'grant.false')
        identity = next(a.id for a in g.state.entities[self.find(g, 'plain')].abilities
            if a.kind == 'end_turn_repeat')
        self.end(g)
        self.assertEqual(g.state.end_turn_batches[-1].subjects, ())
        self.assertFalse(g.state.end_turn_batches[-1].completed)
        snapshot = g.snapshot()
        markers = self.nodes(snapshot['resolution_frame'], 'FinishEndTurnBatch')
        self.assertEqual(len(markers), 1)
        self.change_count(markers[0]['fields']['context'], identity)
        self.reject(g, snapshot)
        self.finish(g)
        self.assertEqual((g.state.turn, self.armor(g)), (2, 1))
        self.portable(g)

    @matrix('ET-V11', 'ETM-35')
    def test_false_surviving_source_full_declaration_cannot_change_current_state(self):
        g, _, identity = self.dynamic_false()
        snapshot = g.snapshot()
        self.change_count(snapshot['state'], identity)
        self.reject(g, snapshot)
        self.finish(g)
        self.portable(g)

    @matrix('ET-V11', 'ETM-35', 'ETM-37')
    def test_original_finish_false_declaration_cannot_change_or_be_erased(self):
        g, carrier, identity = self.dynamic_false()
        for mutation in ('count', 'erase'):
            with self.subTest(mutation=mutation):
                snapshot = g.snapshot()
                context = self.nodes(snapshot['resolution_frame'], 'FinishEndTurnBatch')[0]['fields']['context']
                if mutation == 'count':
                    self.change_count(context, identity)
                else:
                    entity = context['fields']['state']['state']['entities'][str(carrier)]
                    entity['abilities'] = [a for a in entity['abilities'] if a['id'] != identity]
                self.reject(g, snapshot)
        self.finish(g)
        self.portable(g)

    @matrix('ET-V11', 'ETM-35')
    def test_global_duplicate_id_cannot_be_hidden_by_false_source_map(self):
        g, _, identity = self.dynamic_false()
        snapshot = g.snapshot()
        subject = g.state.end_turn_batches[0].subjects[0].ability
        self.assertNotEqual(subject.id, identity)
        self.edit_ability(snapshot['state'], identity, lambda a: a.__setitem__('id', subject.id))
        self.reject(g, snapshot)

    @matrix('ET-V11', 'ETM-11', 'ETM-35')
    def test_removed_false_source_death_record_is_bound_after_live_attachment_reset(self):
        self.body('death.parent', lambda c: [ask(c, Destroy(c.state.players[1].board[0]), ask(c))])
        g, carrier, identity = self.dynamic_false(body='death.parent')
        self.choose(g)
        self.assertEqual(len(g.state.death_history), 1)
        snapshot = g.snapshot()
        snapshot['state']['entities'][str(carrier)]['abilities'] = []
        self.rehash(snapshot)
        restored = Game.from_snapshot(snapshot, self.fresh())
        self.assertEqual(restored.snapshot(), snapshot)
        self.change_count(snapshot['state']['death_history'][0], identity)
        self.reject(g, snapshot)
        self.finish(g)
        self.portable(g)

    @matrix('ET-V11', 'ETM-35')
    def test_completed_history_surviving_contributor_cannot_be_another_family(self):
        self.minion('mixed', end_turn_repeats=(spec(2),),
            spell_repeats=(SpellRepeatSpec(class_mode='any'),))
        g = self.game(board=('mixed', 'end'), hand=())
        self.end(g)
        carrier = g.state.entities[self.find(g, 'mixed')]
        foreign_id = next(a.id for a in carrier.abilities if a.kind == 'spell_repeat')
        snapshot = g.snapshot()
        source = snapshot['state']['end_turn_batches'][0]['plans'][0]['contributors'][0]
        source['ability']['id'] = foreign_id
        for row in snapshot['state']['end_turn_history']:
            row['capture']['plan']['contributors'][0]['ability']['id'] = foreign_id
        self.reject(g, snapshot)

    @matrix('ET-V11', 'ETM-19')
    def test_completed_history_does_not_requery_later_unknown_witness(self):
        self.script('after', lambda c: [Silence(c.state.players[1].board[0]),
            Summon(1, 'unknown.metadata')])
        g = self.game(board=('conditional.two', 'beast', 'end'), hand=('invoke', 'after'))
        self.play(g)
        self.play(g, 'after')
        self.assertEqual(self.counts(g), [2])
        self.portable(g)

    def foreign_child(self, family):
        declaration = {'battlecry': BattlecryRepeatSpec(kinds=(CardType.MINION,)),
            'combo': ComboRepeatSpec(), 'spell': SpellRepeatSpec(class_mode='any',
                match=RepeatMatchSpec(recipient_metadata=RecipientMetadataFilter(
                    spell_schools=(SpellSchool.ARCANE,)))),
            'deathrattle': DeathrattleRepeatSpec()}[family]
        self.minion('dual', **{family + '_repeats': (declaration,)})
        def child(c):
            index = getattr(c, family).repeat_index if family != 'spell' else c.cast.iteration
            effects = [Silence(next(i for i in c.state.players[1].board
                if c.state.entities[i].card_id == 'dual'))] if index == 1 else []
            return [ask(c, *effects, GainArmor(1, 1))]
        self.behavior('foreign.body', child)
        if family == 'spell':
            self.script('foreign.child', child, spell_school=SpellSchool.ARCANE)
        else:
            fields = {family: 'foreign.body', 'cost': 1}
            if family == 'combo':
                fields['keywords'] = (Keyword.COMBO,)
            self.minion('foreign.child', **fields)
        def parent(c):
            target = next(i for i in (c.state.players[1].board if family == 'deathrattle' else
                c.state.players[1].hand) if c.state.entities[i].card_id == 'foreign.child')
            effect = TriggerDeathrattles(target, c.source_id) if family == 'deathrattle' else PlayFromHand(PlayCard(1, target))
            return [ask(c, effect, ask(c))]
        self.body('foreign.parent', parent)
        g = self.game(board=('dual', 'foreign.parent', 'foreign.child') if family == 'deathrattle'
            else ('dual', 'foreign.parent'), hand=('grant.false', 'invoke') if family == 'deathrattle'
            else ('grant.false', 'invoke', 'foreign.child'))
        self.play(g, 'grant.false')
        carrier = self.find(g, 'dual')
        identity = next(a.id for a in g.state.entities[carrier].abilities if a.kind == 'end_turn_repeat')
        foreign_id = next(a.id for a in g.state.entities[carrier].abilities if a.kind == family + '_repeat')
        self.play(g)
        self.choose(g)
        self.choose(g)
        self.assertFalse(g.state.entities[carrier].abilities)
        self.assertEqual(self.counts(g, 0), [1])
        if family == 'spell':
            self.assertEqual([(play.card_id, play.spell_payload.casts) for play in g.state.play_history],
                [('grant.false', 1), ('invoke', 1), ('foreign.child', 2)])
        self.portable(g)
        return g, identity, foreign_id

    def foreign_root_identity(self, g, family):
        carriers = [entity.id for entity in g.state.entities.values()
            if entity.card_id == 'foreign.child']
        self.assertEqual(len(carriers), 1)
        source_id = carriers[0]
        if family == 'deathrattle':
            records = [record for record in g.state.deathrattle_history
                if record.capture.carrier_id == source_id]
            self.assertTrue(records)
            group_ids = {record.capture.group_id for record in records}
            self.assertEqual(len(group_ids), 1)
            self.assertTrue(all(record.capture.card_id == 'foreign.child' for record in records))
            return {'kind': 'deathrattle', 'id': next(iter(group_ids)),
                'source_id': source_id, 'completed': all(record.completed for record in records)}
        plays = [play for play in g.state.play_history if play.card_id == 'foreign.child']
        self.assertEqual(len(plays), 1)
        child = plays[0]
        self.assertEqual(child.source_id, source_id)
        return {'kind': 'play', 'id': child.id, 'source_id': source_id,
            'completed': child.completed}

    def foreign_root_finishes(self, snapshot, root):
        endings = ('FinishBattlecryAcceptance', 'FinishComboAcceptance',
            'FinishSpellAcceptance', 'FinishDeathrattleBatch')
        result = {name: [] for name in endings}
        for name in endings:
            for marker in self.nodes(snapshot['resolution_frame'], name):
                fields = marker['fields']
                if name == 'FinishDeathrattleBatch':
                    capture = fields['context']['fields']['deathrattle']['fields']
                    matched = (root['kind'] == 'deathrattle' and
                        (capture['group_id'], capture['carrier_id']) ==
                        (root['id'], root['source_id']))
                elif root['kind'] != 'play':
                    matched = False
                elif name == 'FinishSpellAcceptance':
                    matched = fields['submission']['fields']['play']['fields']['id'] == root['id']
                else:
                    play = fields['context']['fields']['play']['fields']
                    matched = (play['id'], play['source_id']) == (root['id'], root['source_id'])
                if matched:
                    result[name].append(marker)
        return result

    @matrix('ET-V12', 'ETM-36')
    def test_four_later_foreign_root_originals_bind_false_source_now_removed(self):
        endings = {'battlecry': 'FinishBattlecryAcceptance', 'combo': 'FinishComboAcceptance',
            'spell': 'FinishSpellAcceptance', 'deathrattle': 'FinishDeathrattleBatch'}
        for family, ending in endings.items():
            with self.subTest(family=family):
                self.setUp()
                g, identity, _ = self.foreign_child(family)
                root = self.foreign_root_identity(g, family)
                self.assertFalse(root['completed'])
                base = g.snapshot()
                markers = self.foreign_root_finishes(base, root)[ending]
                self.assertEqual(len(markers), 2 if family == 'combo' else 1)
                parents = [batch for batch in g.state.end_turn_batches
                    if any(subject.card_id == 'foreign.parent' for subject in batch.subjects)]
                self.assertEqual(len(parents), 1)
                parent = parents[0]
                self.assertFalse(parent.completed)
                windows = ('submission', 'resolution') if family == 'spell' else ('context',)
                for marker_index in range(len(markers)):
                    for window in windows:
                        with self.subTest(marker=marker_index, window=window):
                            snapshot = copy.deepcopy(base)
                            marker = self.foreign_root_finishes(snapshot, root)[ending][marker_index]
                            context = marker['fields'][window]
                            self.assertIsNotNone(context)
                            original = context['fields']['state']['state']
                            self.assertEqual(original['end_turn_batches'][parent.id - 1],
                                base['state']['end_turn_batches'][parent.id - 1])
                            self.change_count(context, identity)
                            self.reject(g, snapshot)
                self.finish(g)
                self.assertEqual(self.armor(g), 2)
                self.portable(g)

    @matrix('ET-V12', 'ETM-35', 'ETM-36')
    def test_completed_foreign_refs_cannot_reuse_removed_old_end_source_id(self):
        for family in ('battlecry', 'combo', 'spell', 'deathrattle'):
            with self.subTest(family=family):
                self.setUp()
                g, identity, foreign_id = self.foreign_child(family)
                self.choose(g)
                self.assertIsNotNone(g.state.pending_choice)
                snapshot = g.snapshot()
                root = self.foreign_root_identity(g, family)
                self.assertTrue(root['completed'])
                child_finishes = self.foreign_root_finishes(snapshot, root)
                self.assertFalse(any(child_finishes.values()))
                parents = [batch for batch in g.state.end_turn_batches
                    if any(subject.card_id == 'foreign.parent' for subject in batch.subjects)]
                self.assertEqual(len(parents), 1)
                parent = parents[0]
                self.assertFalse(parent.completed)
                parent_finishes = self.nodes(snapshot['resolution_frame'], 'FinishEndTurnBatch')
                self.assertEqual(len(parent_finishes), 1)
                self.assertEqual(parent_finishes[0]['fields']['batch']['fields']['id'], parent.id)
                outer_plays = [play for play in g.state.play_history if play.card_id == 'invoke']
                self.assertEqual(len(outer_plays), 1)
                self.assertFalse(outer_plays[0].completed)
                outer_finishes = self.nodes(snapshot['resolution_frame'], 'FinishSpellAcceptance')
                self.assertEqual(len(outer_finishes), 1)
                self.assertEqual(outer_finishes[0]['fields']['submission']['fields']['play']['fields']['id'], outer_plays[0].id)
                endings = ('FinishBattlecryAcceptance', 'FinishComboAcceptance', 'FinishDeathrattleBatch')
                self.assertFalse(any(self.nodes(snapshot['resolution_frame'], name) for name in endings))
                changed = []
                def rewrite(v):
                    if isinstance(v, dict):
                        if isinstance(v.get('contributors'), list):
                            for index, value in enumerate(v['contributors']):
                                if value == foreign_id:
                                    v['contributors'][index] = identity
                                    changed.append(True)
                        if v.get('kind') == family + '_repeat' and v.get('id') == foreign_id:
                            v['id'] = identity
                            changed.append(True)
                        for child in v.values():
                            rewrite(child)
                    elif isinstance(v, list):
                        for child in v:
                            rewrite(child)
                rewrite(snapshot['state'])
                self.assertTrue(changed)
                self.reject(g, snapshot)
                self.finish(g)
                self.portable(g)

    @matrix('ET-V12', 'ETM-36')
    def test_late_retained_power_payload_compares_batch_window_not_old_root_id(self):
        def retained(c):
            if c.rewind_attempt == 0 and c.power_payload.repeat_index == 1:
                child = hero_power_references(c.state, 1, scope='additional')[0]
                return [TriggerHeroPower(1, c.source_id, targeting='explicit', choices='player', power=child)]
            if c.rewind_attempt == 1 and c.power_payload.repeat_index == 1:
                return [Silence(c.state.players[1].board[0]), ask(c)]
            return []
        self.power('retained', retained, keywords=(Keyword.REWIND,), rewind=RewindSpec(1))
        self.minion('hp.two', hero_power_repeats=(HeroPowerRepeatSpec(),))
        self.body('parent', lambda c: [ask(c, TriggerHeroPower(1, c.source_id,
            targeting='explicit', choices='player'), ask(c))])
        self.script('add.power', lambda c: [AddHeroPower(1, 'power', c.source_id)])
        g = self.game(board=('plain', 'parent', 'hp.two', 'retainer'), power='retained',
            hand=('grant.false', 'add.power', 'invoke'))
        self.play(g, 'grant.false')
        identity = next(a.id for a in g.state.entities[self.find(g, 'plain')].abilities
            if a.kind == 'end_turn_repeat')
        self.play(g, 'add.power')
        self.play(g)
        self.choose(g)
        self.assertEqual(len(g.state.hero_power_history), 2)
        self.assertTrue(g.state.hero_power_history[1].completed)
        self.assertFalse(g.state.entities[self.find(g, 'plain')].abilities)
        snapshot = g.snapshot()
        invoke = self.nodes(snapshot['resolution_frame'], 'InvokeHeroPowerPayload')[-1]
        capture = invoke['fields']['context']['fields']['power_payload']['fields']
        child_batch = next(b for b in g.state.hero_power_payload_batches if b.power_id == 2)
        self.assertEqual((capture['power_id'], capture['iteration']), (1, 2))
        self.assertGreater(capture['batch_id'], child_batch.id)
        self.change_count(invoke['fields']['context'], identity)
        self.reject(g, snapshot)
        self.finish(g)
        self.portable(g)

    @matrix('ET-V12', 'ETM-37')
    def test_earlier_power_finish_may_legitimately_lack_later_end_group(self):
        self.power('earlier', lambda c: [TriggerEndTurnEffects(1, request(), c.source_id)])
        g = self.game(board=('conditional.two', 'beast', 'waiting'), hand=(), power='earlier')
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        self.assertIsNotNone(g.state.pending_choice)
        finish = next(w for w in (*g._frame.prefix, *g._frame.continuation)
            if type(w).__name__ == 'FinishHeroPower')
        self.assertEqual(finish.context.state.end_turn_batches, [])
        self.portable(g)
        self.finish(g)
        self.assertEqual(g.state.players[1].mana, 8)
        self.portable(g)

    @matrix('ET-V12', 'ETM-24', 'ETM-37')
    def test_later_effect_end_invoke_acceptance_is_bound_independently_of_finish(self):
        # A real granted-false setup before the root, not a printed mismatch.
        self.body('first', lambda c: [ask(c, Silence(c.state.players[1].board[0]), ask(c))])
        g = self.game(board=('plain', 'first', 'end'), hand=('grant.false', 'invoke'))
        self.play(g, 'grant.false')
        identity = next(a.id for a in g.state.entities[self.find(g, 'plain')].abilities
            if a.kind == 'end_turn_repeat')
        self.play(g)
        self.choose(g)
        snapshot = g.snapshot()
        invokes = self.nodes(snapshot['resolution_frame'], 'InvokeEndTurn')
        self.assertTrue(invokes)
        self.change_count(invokes[-1]['fields']['acceptance'], identity)
        self.reject(g, snapshot)
        self.finish(g)
        self.portable(g)

    @matrix('ET-V13', 'ETM-37', 'ETM-38')
    def test_finish_prebatch_original_is_legitimate_and_own_marker_cannot_be_inserted(self):
        g, _, _ = self.dynamic_false()
        marker = next(w for w in (*g._frame.prefix, *g._frame.continuation)
            if type(w).__name__ == 'FinishEndTurnBatch')
        self.assertEqual(len(marker.context.state.end_turn_batches), marker.batch.id - 1)
        self.assertEqual(len(marker.context.state.end_turn_history), marker.batch.first_id - 1)
        self.portable(g)
        snapshot = g.snapshot()
        wire = self.nodes(snapshot['resolution_frame'], 'FinishEndTurnBatch')[0]
        original = wire['fields']['context']['fields']['state']['state']
        original['end_turn_batches'].append(copy.deepcopy(snapshot['state']['end_turn_batches'][0]))
        original['end_turn_history'].extend(copy.deepcopy(snapshot['state']['end_turn_history']))
        self.reject(g, snapshot)

    @matrix('ET-V13', 'ETM-38')
    def test_missing_duplicate_and_nested_reordered_finish_markers_rejected(self):
        self.body('parent', lambda c: [TriggerEndTurnEffects(1, request(mode='selected',
            carriers=('minion',), entities=(c.state.players[1].board[-1],)), c.source_id)])
        g = self.game(board=('conditional.two', 'beast', 'parent', 'waiting'))
        self.play(g)
        self.assertIsNotNone(g.state.pending_choice)
        for mutation in ('missing', 'duplicate', 'reorder'):
            with self.subTest(mutation=mutation):
                snapshot = g.snapshot()
                queue = self.queue(snapshot)
                positions = [i for i, w in enumerate(queue) if w.get('type', '').endswith('.FinishEndTurnBatch')]
                self.assertEqual(len(positions), 2)
                if mutation == 'missing':
                    queue.pop(positions[0])
                elif mutation == 'duplicate':
                    queue.insert(positions[0], copy.deepcopy(queue[positions[0]]))
                else:
                    queue[positions[0]], queue[positions[1]] = queue[positions[1]], queue[positions[0]]
                self.reject(g, snapshot)
        self.finish(g)
        self.portable(g)

    @matrix('ET-V13', 'ETM-38')
    def test_whole_group_proof_and_all_capture_deletion_rejected_by_active_parent(self):
        self.body('parent', lambda c: [TriggerEndTurnEffects(1, request(mode='selected',
            carriers=('minion',), entities=(c.state.players[1].board[-1],)), c.source_id)])
        g = self.game(board=('plain', 'parent', 'waiting'), hand=('grant.false', 'invoke'))
        self.play(g, 'grant.false')
        self.play(g)
        child = g.state.end_turn_batches[-1]
        self.assertEqual(child.id, 2)
        snapshot = g.snapshot()
        snapshot['state']['end_turn_batches'] = snapshot['state']['end_turn_batches'][:1]
        snapshot['state']['end_turn_history'] = snapshot['state']['end_turn_history'][:child.first_id - 1]
        queue = self.queue(snapshot)
        queue[:] = [w for w in queue if not (
            w.get('type', '').endswith('.FinishEndTurnBatch') and w['fields']['batch']['fields']['id'] == 2)]
        self.reject(g, snapshot)

    @matrix('ET-V13', 'ETM-38')
    def test_last_repeat_coordinated_plan_history_and_queue_trim_rejected(self):
        g = self.waiting()
        snapshot = g.snapshot()
        batch = snapshot['state']['end_turn_batches'][0]
        batch['plans'][0]['repetitions'] = 2
        snapshot['state']['end_turn_history'] = snapshot['state']['end_turn_history'][:2]
        for row in snapshot['state']['end_turn_history']:
            row['capture']['plan']['repetitions'] = 2
        queue = self.queue(snapshot)
        queue[:] = [w for w in queue if not (
            w.get('type', '').endswith('.InvokeEndTurn') and
            w['fields']['acceptance']['fields']['end_turn']['fields']['repeat_index'] == 2)]
        self.reject(g, snapshot)

    @matrix('ET-V13', 'ETM-37')
    def test_completed_original_prefix_cannot_be_rewritten_in_later_group(self):
        self.script('wait.root', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', carriers=('minion',), entities=(c.state.players[1].board[-1],)), c.source_id)])
        g = self.game(board=('conditional.two', 'beast', 'end', 'waiting'), hand=('invoke', 'wait.root'))
        self.play(g)
        self.finish(g)
        self.play(g, 'wait.root')
        snapshot = g.snapshot()
        marker = self.nodes(snapshot['resolution_frame'], 'FinishEndTurnBatch')[0]
        original = marker['fields']['context']['fields']['state']['state']
        original['end_turn_history'][0]['completed'] = False
        self.reject(g, snapshot)
        self.finish(g)
        self.portable(g)

    @matrix('ET-V13', 'ETM-38')
    def test_closing_rejects_whole_current_batch_removal_after_last_invoke(self):
        g, _, _ = self.dynamic_false()
        before = g.snapshot()
        from hs_sim.engine.end_turn_acceptance import validate_queue
        called = []
        def corrupt(state, registry, queue, maximum, **keywords):
            if keywords.get('closing') is not None:
                self.assertFalse(any(type(w).__name__ == 'InvokeEndTurn' for w in queue))
                state.end_turn_batches.clear()
                state.end_turn_history.clear()
                called.append(True)
            return validate_queue(state, registry, queue, maximum, **keywords)
        with patch('hs_sim.engine.end_turn_acceptance.validate_queue', side_effect=corrupt):
            with self.assertRaises(ResolutionError):
                self.choose(g)
        self.assertTrue(called)
        self.assertEqual(g.snapshot(), before)
        self.finish(g)
        self.portable(g)

    @matrix('ET-V13', 'ETM-39')
    def test_terminal_checks_complete_group_before_interrupt_and_queue_drop(self):
        self.body('fatal', lambda c: [ask(c, Damage(c.state.players[2].hero_id, 30))])
        g = self.waiting(board=('conditional.three', 'beast', 'fatal'))
        before = g.snapshot()
        from hs_sim.engine.end_turn_acceptance import validate_terminal_queue
        called = []
        def corrupt(r, queue):
            self.assertEqual(r.state.status, 'finished')
            r.state.end_turn_batches.clear()
            r.state.end_turn_history.clear()
            called.append(True)
            return validate_terminal_queue(r, queue)
        with patch('hs_sim.engine.end_turn_acceptance.validate_terminal_queue', side_effect=corrupt):
            with self.assertRaises(ResolutionError):
                self.choose(g)
        self.assertTrue(called)
        self.assertEqual(g.snapshot(), before)
        self.choose(g)
        self.assertEqual(g.state.status, 'finished')
        self.assertEqual(self.counts(g), [3])
        self.assertTrue(g.state.end_turn_batches[0].interrupted)
        self.portable(g)

    @matrix('ET-V13', 'ETM-39')
    def test_fatal_last_body_still_binds_independent_original_finish_false_source(self):
        self.body('fatal.last', lambda c: [ask(c, Damage(c.state.players[2].hero_id, 30))])
        g, _, identity = self.dynamic_false(body='fatal.last')
        before = g.snapshot()
        from hs_sim.engine.end_turn_acceptance import validate_terminal_queue
        called = []
        def corrupt(r, queue):
            altered = []
            for w in queue:
                if type(w).__name__ == 'FinishEndTurnBatch':
                    saved = copy.deepcopy(w.context.state)
                    for e in saved.entities.values():
                        e.abilities = [replace(a, end_turn_repeat=replace(a.end_turn_repeat, repetitions=4))
                            if a.id == identity else a for a in e.abilities]
                    w = replace(w, context=replace(w.context, state=saved))
                    called.append(True)
                altered.append(w)
            return validate_terminal_queue(r, tuple(altered))
        with patch('hs_sim.engine.end_turn_acceptance.validate_terminal_queue', side_effect=corrupt):
            with self.assertRaises(ResolutionError):
                self.choose(g)
        self.assertTrue(called)
        self.assertEqual(g.snapshot(), before)
        self.choose(g)
        self.assertEqual(g.state.status, 'finished')
        self.portable(g)

    @matrix('ET-V14', 'ETM-40', 'ETM-41')
    def test_each_waiting_and_terminal_position_has_fresh_restore_clone_and_replay(self):
        g = self.waiting()
        waits = 0
        while g.state.pending_choice is not None:
            self.portable(g)
            waits += 1
            self.choose(g)
        self.assertEqual(waits, 3)
        self.assertEqual(self.armor(g), 3)
        self.portable(g)

    @matrix('ET-V14', 'ETM-40')
    def test_both_player_ports_hide_private_match_proof_and_are_deeply_detached(self):
        g = self.waiting()
        before = g.snapshot()
        for viewer in (1, 2):
            port = g.for_player(viewer)
            view, actions, events = port.observe(), port.legal_actions(), port.events()
            encoded = json.dumps((view, actions, events))
            for key in ('source_eligibility', 'profile_id', 'end_turn_batches', 'end_turn_history',
                    'resolution_frame', 'acceptance', 'contributors', 'guard_event', 'rng_state'):
                self.assertNotIn('"' + key + '"', encoded)
            view['observation']['players'][0]['hero']['armor'] = 999
            actions['actions'].clear()
            events.clear()
            self.assertEqual(g.snapshot(), before)
        self.portable(g)

    @matrix('ET-V15', 'ETM-42')
    def test_budget_checks_true_expansion_before_capture_positions_but_false_huge_is_unit(self):
        self.source('huge', spec(1000, eligibility=condition()))
        for witness, failure in (('beast', True), ('plain', False)):
            with self.subTest(witness=witness):
                g = self.game(board=('huge', witness, 'end'), rules=Ruleset(max_resolution_steps=50))
                before = g.snapshot()
                if failure:
                    with patch('hs_sim.engine.end_turns.EndTurnCapture') as allocation:
                        with self.assertRaises(ResolutionLimitExceeded):
                            self.play(g)
                        allocation.assert_not_called()
                    self.assertEqual(g.snapshot(), before)
                    self.assertFalse(g.state.end_turn_batches)
                else:
                    self.play(g)
                    self.assertEqual(self.counts(g), [1])
                self.portable(g)

    @matrix('ET-V15', 'ETM-41')
    def test_waiting_randomness_then_registered_failure_rolls_back_selection_transaction(self):
        self.behavior('fail', lambda c: (_ for _ in ()).throw(ValueError('deliberate fixture failure')))
        self.body('rng.wait', lambda c: [ask(c, RandomDamage((c.state.players[1].hero_id,
            c.state.players[2].hero_id), 1, c.source_id),
            InvokeBehavior('fail', c.source_id, c.player_id))])
        g = self.waiting(board=('conditional.two', 'beast', 'rng.wait'))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g)
        self.assertEqual(g.snapshot(), before)
        self.portable(g)

    @matrix('ET-V15', 'ETM-41')
    def test_later_extra_body_exception_rolls_back_payment_all_facts_and_clock(self):
        def failure(c):
            if c.end_turn.repeat_index:
                raise ValueError('deliberate later extra failure')
            return [GainArmor(1, 1)]
        self.body('failure', failure)
        self.player_spec('clock', duration=3)
        g = self.game(board=('conditional.two', 'beast', 'failure'), hand=('add.clock', 'invoke'))
        self.play(g, 'add.clock')
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g)
        self.assertEqual(g.snapshot(), before)
        self.portable(g)

    @matrix('ET-V15', 'ETM-29')
    def test_natural_listener_slot_interleaving_and_clock_tail_are_preserved(self):
        self.raw('raw.ten', lambda c: [GainArmor(1, 10)])
        self.raw('tail', lambda c: [ask(c, GainArmor(1, 100))])
        self.player_spec('short', duration=1)
        g = self.game(board=('conditional.two', 'beast', 'end', 'raw.ten', 'end', 'tail'), hand=('add.short',))
        self.play(g, 'add.short')
        self.end(g)
        self.assertEqual([e.amount for e in g.events if e.kind == 'armor_gained'], [1, 1, 10, 1, 1])
        self.assertTrue(all(row.completed for row in g.state.end_turn_history))
        self.assertFalse(g.state.end_turn_batches[0].completed)
        self.assertEqual(g.state.players[1].player_effects[0].remaining_turns, 1)
        self.portable(g)
        self.choose(g)
        self.assertFalse(g.state.players[1].player_effects)
        self.assertEqual((g.state.turn, self.armor(g)), (2, 114))
        self.portable(g)

    @matrix('ET-V15', 'ETM-34')
    def test_each_outer_deathrattle_draws_independently_inner_repeats_keep_selection(self):
        self.minion('dr.source', deathrattle_repeats=(DeathrattleRepeatSpec(),))
        self.behavior('produce', lambda c: [TriggerRandomEndTurnEffects(1,
            EndTurnProducerRequest(EndTurnSelector('owner', (1,), ('minion',))), c.source_id)])
        self.minion('rattle', deathrattle='produce')
        self.script('dr', lambda c: [TriggerDeathrattles(c.state.players[1].board[2], c.source_id)])
        g = self.game(board=('conditional.two', 'beast', 'rattle', 'dr.source', 'waiting'), hand=('dr',))
        self.play(g, 'dr')
        self.finish(g)
        groups = g.state.end_turn_batches
        self.assertEqual(len(groups), 2)
        self.assertEqual([b.plans[0].repetitions for b in groups], [2, 2])
        self.assertEqual([len(b.activation.selection.candidates) for b in groups], [1, 1])
        self.assertEqual(groups[0].activation.selection.rng_after, groups[1].activation.selection.rng_before)
        self.assertEqual(self.armor(g), 4)
        self.portable(g)

    @matrix('ET-V15', 'ETM-41')
    def test_retained_power_results_create_distinct_end_roots_without_recapturing_old_positions(self):
        self.power('retained', lambda c: [TriggerEndTurnEffects(1, request(), c.source_id)],
            keywords=(Keyword.REWIND,), rewind=RewindSpec(1))
        self.body('remove.witness', lambda c: [Transform(c.state.players[1].board[1], 'plain'),
            ask(c, GainArmor(1, 1))] if c.end_turn.repeat_index == 0 else [ask(c, GainArmor(1, 1))])
        g = self.game(board=('conditional.two', 'beast', 'remove.witness', 'retainer'), power='retained', hand=())
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        self.finish(g)
        self.assertEqual([b.plans[0].repetitions for b in g.state.end_turn_batches], [2, 1])
        self.assertEqual(self.armor(g), 3)
        self.assertEqual(len(g.state.hero_power_history), 1)
        self.assertEqual(g.state.players[1].mana, 8)
        self.portable(g)

    @matrix('ET-V01', 'ETM-44')
    def test_capture_requires_real_registry_even_for_a_false_unit_plan(self):
        g = self.game(board=('false.source', 'end'))
        self.play(g)
        subject = g.state.end_turn_batches[0].subjects[0]
        self.assertEqual(capture_plan(g.state, self.r, subject), EndTurnRepeatPlan())
        with self.assertRaises(ValueError):
            capture_plan(g.state, None, subject)
        self.portable(g)

    @matrix('ET-V05', 'ETM-24')
    def test_each_extra_reads_new_armor_without_recapturing_the_accepted_plan(self):
        self.body('fresh', lambda c: [GainArmor(c.player_id,
            c.state.entities[c.state.players[c.player_id].hero_id].armor + 1)])
        g = self.game(board=('conditional.three', 'beast', 'fresh'))
        self.play(g)
        self.assertEqual([e.amount for e in g.events if e.kind == 'armor_gained'], [1, 2, 4])
        self.assertEqual((self.counts(g), self.armor(g)), ([3], 7))
        self.portable(g)

    @matrix('ET-V09', 'ETM-03', 'ETM-12')
    def test_player_repeat_policy_with_paid_spell_donor_has_no_physical_source_condition(self):
        self.player_spec('spell.donor', scope='minion')
        self.script('from.spell', lambda c: [AddPlayerEffect(1, 'spell.donor', c.source_id)])
        g = self.game(board=('end',), hand=('from.spell', 'invoke'))
        donor = self.play(g, 'from.spell')
        self.play(g)
        source = g.state.end_turn_batches[-1].plans[0].contributors[0]
        self.assertEqual(source.carrier_id, donor)
        self.assertEqual(self.r.card(source.card_id).kind, CardType.SPELL)
        self.assertEqual((self.counts(g), self.armor(g)), ([2], 2))
        self.portable(g)

    @matrix('ET-V10', 'ETM-13', 'ETM-35', 'ETM-37')
    def test_false_parent_policy_binds_three_completed_end_root_clocks_after_expiry(self):
        self.player_spec('clock', scope='minion', duration=3)
        def parent(c):
            target = next(i for i in c.state.players[1].board if c.state.entities[i].card_id == 'end')
            selected = request(mode='selected', carriers=('minion',), entities=(target,))
            instance = c.state.players[1].player_effects[0]
            return [TriggerEndTurnEffects(1, selected, c.source_id), TickPlayerEffect(1, instance.id, 3),
                TriggerEndTurnEffects(1, selected, c.source_id), TickPlayerEffect(1, instance.id, 2),
                TriggerEndTurnEffects(1, selected, c.source_id), TickPlayerEffect(1, instance.id, 1), ask(c)]
        self.behavior('clock.parent', parent)
        self.install('card', CardDefinition('clock.parent', 'Parent', CardType.HERO_POWER,
            passive_hero_power=True, triggers=(TriggerSpec('turn_ended', 'clock.parent', EndTurnSpec()),)))
        self.script('clock.invoke', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', carriers=('hero_power',),
                entities=(c.state.players[1].hero_power_id,)), c.source_id)])
        g = self.game(board=('end',), power='clock.parent', hand=('add.clock', 'clock.invoke'))
        self.play(g, 'add.clock')
        self.play(g, 'clock.invoke')
        parent_group = next(b for b in g.state.end_turn_batches if any(s.card_id == 'clock.parent' for s in b.subjects))
        self.assertEqual([s.card_id for s in parent_group.subjects], ['clock.parent'])
        self.assertIsNotNone(g.state.pending_choice)
        children = [b for b in g.state.end_turn_batches if b.activation.parent_id is not None]
        self.assertEqual(len(children), 3)
        clocks = [b.plans[0].contributors[0].player_effect.remaining_turns for b in children]
        self.assertEqual(clocks, [3, 2, 1])
        self.assertFalse(g.state.players[1].player_effects)
        self.assertEqual(self.counts(g, parent_group.id - 1)[-1], 1)
        self.portable(g)
        snapshot = g.snapshot()
        last_id = children[-1].id
        last = snapshot['state']['end_turn_batches'][last_id - 1]
        last['plans'][0]['contributors'][0]['player_effect']['remaining_turns'] = 3
        for row in snapshot['state']['end_turn_history']:
            if row['capture']['batch_id'] == last_id:
                row['capture']['plan']['contributors'][0]['player_effect']['remaining_turns'] = 3
        self.reject(g, snapshot)
        self.finish(g)
        self.portable(g)

    @matrix('ET-V11', 'ETM-35')
    def test_false_source_duplicate_of_secret_quest_and_dormancy_ids_is_rejected(self):
        self.install('secret_condition', 'never.secret', lambda c: False)
        self.install('card', CardDefinition('secret', 'Secret', CardType.SPELL, cost=0,
            keywords=(Keyword.SECRET,), secret=SecretSpec('secret', ('card_committed',),
                'never.secret', 'noop')))
        self.install('card', CardDefinition('quest', 'Quest', CardType.SPELL, cost=0,
            keywords=(Keyword.SIDEQUEST,), quest=QuestSpec('sidequest',
                (QuestStageSpec('quest', 10, ('card_drawn',), 'noop', 'noop'),))))
        g = self.game(board=('plain', 'waiting', 'dormant'), hand=('secret', 'quest', 'grant.false', 'invoke'))
        self.play(g, 'secret')
        self.play(g, 'quest')
        self.play(g, 'grant.false')
        identity = next(a.id for a in g.state.entities[self.find(g, 'plain')].abilities if a.kind == 'end_turn_repeat')
        self.play(g)
        catalogue = {'secret': g.state.entities[g.state.players[1].secrets[0]].secret_instance_id,
            'quest': g.state.entities[g.state.players[1].quests[0]].quest_progress.id,
            'dormancy': g.state.entities[self.find(g, 'dormant')].dormancy.id}
        self.portable(g)
        for family, other in catalogue.items():
            with self.subTest(family=family):
                self.assertNotEqual(identity, other)
                snapshot = g.snapshot()
                self.edit_ability(snapshot['state'], identity, lambda a: a.__setitem__('id', other))
                self.reject(g, snapshot)

    @matrix('ET-V12', 'ETM-36')
    def test_later_power_root_finish_binds_false_source_after_last_invoke_is_gone(self):
        self.power('child', lambda c: [ask(c, Silence(c.state.players[1].board[0]), ask(c))])
        self.body('parent', lambda c: [ask(c, TriggerHeroPower(1, c.source_id,
            targeting='explicit', choices='player'), ask(c))])
        g = self.game(board=('plain', 'parent'), power='child', hand=('grant.false', 'invoke'))
        self.play(g, 'grant.false')
        identity = next(a.id for a in g.state.entities[self.find(g, 'plain')].abilities if a.kind == 'end_turn_repeat')
        self.play(g)
        self.choose(g)
        self.choose(g)
        snapshot = g.snapshot()
        self.assertFalse(self.nodes(snapshot['resolution_frame'], 'InvokeHeroPowerPayload'))
        markers = self.nodes(snapshot['resolution_frame'], 'FinishHeroPower')
        self.assertEqual(len(markers), 1)
        self.assertTrue(self.nodes(snapshot['resolution_frame'], 'FinishEndTurnBatch'))
        self.change_count(markers[0]['fields']['context'], identity)
        self.reject(g, snapshot)
        self.finish(g)
        self.portable(g)

    @matrix('ET-V13', 'ETM-25', 'ETM-37')
    def test_finite_actual_guard_event_and_once_only_consumption_cannot_be_rewritten(self):
        g = self.waiting(board=('conditional.two', 'beast', 'finite'))
        source = self.find(g, 'finite')
        for mutation in ('amount', 'uses', 'guard_id'):
            with self.subTest(mutation=mutation):
                snapshot = g.snapshot()
                if mutation == 'amount':
                    for row in snapshot['state']['end_turn_history']:
                        row['guard_event']['amount'] = 0
                elif mutation == 'uses':
                    ability = next(a for a in snapshot['state']['entities'][str(source)]['abilities']
                        if a['kind'] == 'limited_trigger')
                    ability['uses_remaining'] = 2
                else:
                    snapshot['state']['end_turn_history'][1]['guard_id'] = 2
                self.reject(g, snapshot)
        self.finish(g)
        self.assertEqual(self.armor(g), 2)
        self.portable(g)

    @matrix('ET-V02', 'ETM-04')
    def test_recipient_transform_before_group_accepts_new_physical_card_face(self):
        self.script('make.end', lambda c: [Transform(c.state.players[1].board[2], 'end')])
        g = self.game(board=('conditional.two', 'beast', 'plain'), hand=('make.end', 'invoke'))
        carrier = self.find(g, 'plain')
        self.play(g, 'make.end')
        self.play(g)
        subject = g.state.end_turn_batches[0].subjects[0]
        self.assertEqual((subject.source_id, subject.card_id), (carrier, 'end'))
        self.assertEqual((self.counts(g), self.armor(g)), ([2], 2))
        self.portable(g)

    @matrix('ET-V05', 'ETM-19')
    def test_expired_dynamic_source_history_uses_its_acceptance_turn(self):
        self.script('grant.expiring', lambda c: [GrantEndTurnRepeatAura(c.state.players[1].board[0],
            spec(eligibility=condition()), c.source_id, expires_turn=c.state.turn)])
        g = self.game(board=('plain', 'beast', 'end'), hand=('grant.expiring', 'invoke'))
        self.play(g, 'grant.expiring')
        self.end(g)
        self.end(g)
        self.play(g)
        nonempty = [b for b in g.state.end_turn_batches if b.subjects]
        self.assertEqual([b.plans[0].repetitions for b in nonempty], [2, 1])
        self.assertEqual(nonempty[0].plans[0].contributors[0].ability.expires_turn, 1)
        self.portable(g)

    @matrix('ET-V15', 'ETM-33')
    def test_one_random_carrier_with_many_bodies_freezes_all_subject_plans_once(self):
        self.minion('many', triggers=tuple(TriggerSpec('turn_ended', 'armor', EndTurnSpec()) for _ in range(3)))
        self.script('random', lambda c: [TriggerRandomEndTurnEffects(1,
            EndTurnProducerRequest(EndTurnSelector('owner', (1,), ('minion',))), c.source_id)])
        g = self.game(board=('conditional.two', 'beast', 'many'), hand=('random',))
        self.play(g, 'random')
        group = g.state.end_turn_batches[0]
        self.assertEqual((len(group.activation.selection.candidates), len(group.subjects)), (1, 3))
        self.assertEqual((self.counts(g), self.armor(g)), ([2, 2, 2], 6))
        self.assertNotEqual(group.activation.selection.rng_before, group.activation.selection.rng_after)
        self.portable(g)

    @matrix('ET-V15', 'ETM-41')
    def test_ordinary_power_rewind_retries_nested_end_root_with_one_net_payment(self):
        self.power('rewind', lambda c: [TriggerEndTurnEffects(1, request(), c.source_id)],
            keywords=(Keyword.REWIND,), rewind=RewindSpec(1))
        self.body('change', lambda c: [Transform(c.state.players[1].board[1], 'plain'),
            GainArmor(1, 1)] if c.end_turn.repeat_index == 0 else [GainArmor(1, 1)])
        g = self.game(board=('conditional.two', 'beast', 'change'), power='rewind', hand=())
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        self.assertIsNotNone(g.state.pending_choice)
        self.portable(g)
        self.choose(g, 'retry')
        self.assertEqual((len(g.state.end_turn_batches), self.counts(g)), (1, [2]))
        self.assertEqual((self.armor(g), g.state.players[1].mana,
            g.state.players[1].hero_power_uses_this_turn), (2, 8, 1))
        self.assertEqual(len([e for e in g.events if e.kind == 'timeline_rewound']), 1)
        self.portable(g)

    @matrix('ET-V04', 'ETM-16')
    def test_full_witness_query_does_not_execute_nonselected_body_conditions(self):
        self.install('trigger_condition', 'forbidden', lambda c:
            (_ for _ in ()).throw(ValueError('witness query executed body condition')))
        self.minion('witness', metadata=metadata(('beast',)),
            triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec('controller', 'forbidden')),))
        self.script('selected', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', carriers=('minion',), entities=(c.state.players[1].board[-1],)), c.source_id)])
        g = self.game(board=('conditional.two', 'witness', 'end'), hand=('selected',))
        self.play(g, 'selected')
        self.assertEqual((self.counts(g), self.armor(g)), ([2], 2))
        self.portable(g)

    @matrix('ET-V15', 'ETM-42')
    def test_recursive_effect_groups_share_budget_and_roll_back_the_outer_paid_action(self):
        self.body('recursive', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', carriers=('minion',), entities=(c.source_id,)), c.source_id)])
        g = self.game(board=('conditional.two', 'beast', 'recursive'), rules=Ruleset(max_resolution_steps=100))
        before = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            self.play(g)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(g.state.status, 'playing')
        self.assertFalse(g.state.end_turn_batches)
        self.portable(g)


if __name__ == '__main__':
    unittest.main()
