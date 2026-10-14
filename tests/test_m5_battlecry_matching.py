"""B2-01 public Battlecry recipient, physical self and sustained conditions.

Synthetic fixtures establish the local public mechanism contract. They do not
adapt Dark Gifts, certify a constructed tribal source, or calibrate CN rules.
"""
import copy
import json
import unittest
from dataclasses import replace

from hs_sim.engine import (AppendageSpec, CardClass, CardDefinition, CardMetadata,
    CardType, EndTurn, Game, Keyword, PlayCard, PlayerSetup, Registry,
    ResolutionError, ResolutionLimitExceeded, RewindSpec, Scenario, SelectChoice,
    SnapshotError, TriggerSpec, Zone, PlayerEffectSpec, TargetSpec, LaunchStarship)
from hs_sim.engine.model import (AbilityInstance, BattlecryRecipient,
    BattlecryRecipientMetadataFilter, BattlecryRepeatMatchSpec,
    BattlecryRepeatSpec, RepeatSourceEligibility, RepeatWitnessProfile)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, Destroy, GainArmor, InvokeBehavior, RandomDamage, RandomDestroy,
    RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.battlecry_matching import (battlecry_match_from_dict,
    battlecry_match_to_dict, battlecry_repeat_recipient_matches, capture_recipient)
from hs_sim.engine.battlecry_modifiers import AddBattlecryRepeatModifier
from hs_sim.engine.battlecry_modifiers import RemoveBattlecryRepeatModifier
from hs_sim.engine.battlecry_repeats import (FinishBattlecryAcceptance,
    GrantBattlecryRepeatAura, capture_plan_from_state)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.combo_modifiers import AddComboRepeatModifier
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.information import validate_battlecry_modifier_view
from hs_sim.engine.interrupts import CounterMinion
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.resolver import PlayFromHand
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_modifiers import AddSpellRepeatModifier
from hs_sim.engine.starships import construction


def metadata(tribes=()):
    return CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=tribes)


def specification(count=2, *, tribes=None, scope='friendly', eligibility=None,
                  kinds=None):
    if kinds is None:
        kinds = ((CardType.MINION,) if scope == 'self' else
                 (CardType.MINION, CardType.WEAPON, CardType.HERO))
    recipient = None if tribes is None else BattlecryRecipientMetadataFilter(
        'accepted_carrier_face_printed', tribes)
    matching = (BattlecryRepeatMatchSpec(recipient, eligibility)
                if recipient is not None or eligibility is not None else None)
    return BattlecryRepeatSpec(count, kinds, scope, matching)


def witness(*, another=True, tribes=('dragon',), profile='repeat.witness.controlled'):
    return RepeatSourceEligibility(profile, tribes, another)


def find(state, name, player=1):
    return next(i for i in state.players[player].board
                if state.entities[i].card_id == name)


def ask(context, effects=()):
    return RequestChoice(context.player_id,
        (ChoiceOption('ok', 'Resolve', tuple(effects)),), source_id=context.source_id)


def fixture_registry():
    registry = Registry('battlecry-matching-public-fixtures-v1')
    registry.register_card(CardDefinition('hero', 'Hero', CardType.HERO,
        health=30, metadata=metadata()))
    registry.register_behavior('armor', lambda c: [GainArmor(c.player_id, 2)])
    registry.register_card(CardDefinition('power', 'Power', CardType.HERO_POWER,
        on_use='armor', metadata=metadata()))

    def minion(name, *, tribes=(), meta='known', **fields):
        fields.setdefault('health', 6)
        fields.setdefault('cost', 1)
        fields['metadata'] = None if meta is None else metadata(tribes)
        registry.register_card(CardDefinition(name, name, CardType.MINION, **fields))

    for name, tribes in (('plain', ()), ('dragon', ('dragon',)),
            ('beast', ('beast',)), ('multi', ('beast', 'dragon')), ('all', ('all',)),
            ('unknown.tribes', None), ('hidden.source.card', ())):
        minion(name, tribes=tribes)
    minion('unknown.metadata', meta=None)
    minion('dormant.dragon', tribes=('dragon',), dormant_turns=None)
    minion('retainer', retain_rewind_outcomes=True)
    for name, spec, tribes in (
            ('friendly.2', specification(), ()),
            ('friendly.3', specification(3), ()),
            ('friendly.5', specification(5), ()),
            ('tribal.2', specification(tribes=('dragon',)), ()),
            ('tribal.3', specification(3, tribes=('dragon',)), ()),
            ('tribal.5', specification(5, tribes=('dragon',)), ()),
            ('beast.5', specification(5, tribes=('beast',)), ()),
            ('self.source', specification(scope='self'), ()),
            ('conditional', specification(tribes=('dragon',), eligibility=witness()), ()),
            ('conditional.dragon', specification(tribes=('dragon',), eligibility=witness()), ('dragon',)),
            ('ordinary.dragon', specification(tribes=('dragon',), eligibility=witness(another=False)), ('dragon',)),
            ('conditional.active', specification(tribes=('dragon',), eligibility=witness(profile='repeat.witness.active_live')), ()),
            ('conditional.any', specification(eligibility=witness(tribes=())), ()),
            ('conditional.narrow', specification(tribes=('dragon',), eligibility=witness(), kinds=(CardType.MINION,)), ()),
            ('witness.only', specification(eligibility=witness()), ()),
            ('another.dragon.any', specification(eligibility=witness()), ('dragon',)),
            ('huge', specification(100001, tribes=('dragon',)), ())):
        minion(name, tribes=tribes, battlecry_repeats=(spec,))
    for name, tribes in (('dragon.cry', ('dragon',)), ('beast.cry', ('beast',)),
            ('multi.cry', ('beast', 'dragon')), ('all.cry', ('all',)),
            ('empty.cry', ()), ('unknown.tribes.cry', None)):
        minion(name, tribes=tribes, battlecry='armor')
    minion('unknown.metadata.cry', meta=None, battlecry='armor')
    minion('self.cry', tribes=('dragon',), battlecry='armor',
        battlecry_repeats=(specification(scope='self'),))
    registry.register_behavior('ask', lambda c: [ask(c, (GainArmor(c.player_id, 2),))])
    minion('dragon.ask', tribes=('dragon',), battlecry='ask')
    minion('beast.ask', tribes=('beast',), battlecry='ask')
    registry.register_behavior('generic.ask', lambda c: [ask(c)])
    minion('generic.dragon.ask', tribes=('dragon',), on_play='generic.ask', battlecry='armor')
    minion('generic.beast.ask', tribes=('beast',), on_play='generic.ask', battlecry='armor')
    registry.register_behavior('generic.transform', lambda c: [
        ask(c, (Transform(c.source_id, 'beast'),))])
    minion('generic.transform.cry', tribes=('dragon',),
        on_play='generic.transform', battlecry='armor')
    registry.register_behavior('self.transform', lambda c: [ask(c,
        (Transform(c.source_id, 'beast'), GainArmor(c.player_id, 2)))])
    minion('self.transform.cry', tribes=('dragon',), battlecry='self.transform',
        battlecry_repeats=(specification(scope='self', tribes=('dragon',)),))
    registry.register_behavior('remove.witness', lambda c: [ask(c, (
        *((ReturnToHand(find(c.state, 'dragon')),)
          if c.battlecry.repeat_index == 1 else ()), GainArmor(c.player_id, 2)))])
    minion('remove.witness.cry', tribes=('beast',), battlecry='remove.witness')
    registry.register_behavior('add.witness', lambda c: [
        Summon(c.player_id, 'dragon'), GainArmor(c.player_id, 2)])
    minion('add.witness.cry', tribes=('beast',), battlecry='add.witness')
    registry.register_behavior('empty', lambda c: [])
    minion('empty.body.cry', tribes=('dragon',), battlecry='empty')
    minion('no.battlecry', tribes=('dragon',), on_play='generic.ask')
    registry.register_behavior('retained', lambda c: [ask(c, (
        *((ReturnToHand(find(c.state, 'dragon')), Transform(c.source_id, 'beast'))
          if c.battlecry.iteration == 1 and c.battlecry.repeat_index == 1 else ()),
        GainArmor(c.player_id, 1)))])
    minion('retained.cry', tribes=('dragon',), battlecry='retained',
        keywords=(Keyword.REWIND,), rewind=RewindSpec(1))
    registry.register_behavior('ordinary.rewind', lambda c: [GainArmor(c.player_id,
        c.rewind_attempt + 1)])
    minion('rewind.cry', tribes=('dragon',), battlecry='ordinary.rewind',
        keywords=(Keyword.REWIND,), rewind=RewindSpec(2))
    registry.register_behavior('fail.after.random', lambda c: [Summon(c.player_id, 'missing')])
    registry.register_behavior('bad.choice', lambda c: [ask(c, (
        RandomDamage((c.state.players[2].hero_id,), 1),
        InvokeBehavior('fail.after.random', c.source_id, c.player_id)))])
    minion('bad.choice.cry', tribes=('dragon',), battlecry='bad.choice')
    registry.register_behavior('bad.body', lambda c: [
        RandomDamage((c.state.players[2].hero_id,), 1), Summon(c.player_id, 'missing')])
    minion('bad.body.cry', tribes=('dragon',), battlecry='bad.body')
    registry.register_behavior('fatal', lambda c: [Damage(c.state.players[2].hero_id, 100)])
    minion('fatal.cry', tribes=('dragon',), battlecry='fatal')
    minion('limb', tribes=('dragon',))
    minion('giant.cry', tribes=('dragon',), battlecry='armor',
        keywords=(Keyword.COLOSSAL,), colossal=(AppendageSpec('limb'),))
    minion('part.dragon', tribes=('dragon',), battlecry='armor', keywords=(Keyword.STARSHIP_PIECE,))
    minion('part.beast', tribes=('beast',), battlecry='armor', keywords=(Keyword.STARSHIP_PIECE,))
    minion('ship.body', tribes=('beast',), health=0, starship_for=(CardClass.NEUTRAL,))
    registry.register_behavior('nested.paid', lambda c: [ask(c, (
        ReturnToHand(find(c.state, 'dragon')),
        PlayFromHand(PlayCard(c.player_id, next(i for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id == 'beast.ask'))), GainArmor(c.player_id, 1)))]
        if c.battlecry.repeat_index == 1 else [GainArmor(c.player_id, 1)])
    minion('nested.paid.cry', tribes=('beast',), battlecry='nested.paid')
    registry.register_behavior('generic.move.source', lambda c: [
        ChangeControl(find(c.state, 'tribal.2'), 2), ask(c)])
    minion('move.source.cry', tribes=('dragon',), on_play='generic.move.source', battlecry='armor')
    registry.register_behavior('generic.grant.source', lambda c: [GrantBattlecryRepeatAura(
        find(c.state, 'plain'), specification(tribes=('dragon',)), c.source_id), ask(c)])
    minion('grant.source.cry', tribes=('dragon',), on_play='generic.grant.source', battlecry='armor')
    registry.register_card(CardDefinition('weapon.cry', 'Weapon', CardType.WEAPON,
        cost=1, attack=1, durability=2, battlecry='armor'))
    registry.register_card(CardDefinition('hero.cry', 'Hero card', CardType.HERO,
        cost=1, health=30, hero_card=True, initial_hero_power='power', battlecry='armor'))

    def script(name, callback, **fields):
        registry.register_behavior(name, callback)
        registry.register_card(CardDefinition(name, name, CardType.SPELL,
            on_play=name, metadata=metadata(), **fields))

    def watch(name, event, callback):
        registry.register_behavior(name, callback)
        minion(name, triggers=(TriggerSpec(event, name),))

    for name, spec, uses in (
            ('policy.dragon.one', specification(tribes=('dragon',)), 1),
            ('policy.dragon.two', specification(tribes=('dragon',)), 2),
            ('policy.dragon.3', specification(3, tribes=('dragon',)), 1),
            ('policy.beast.two', specification(tribes=('beast',)), 2),
            ('policy.any.one', specification(), 1)):
        script(name, lambda c, spec=spec, uses=uses: [AddBattlecryRepeatModifier(
            c.player_id, spec, c.source_id, uses)])
    script('policy.hidden', lambda c: [AddBattlecryRepeatModifier(c.player_id,
        specification(tribes=('dragon',)), c.state.players[c.player_id].deck[0], 2)])
    script('grant.self', lambda c: [GrantBattlecryRepeatAura(find(c.state, 'dragon.cry'),
        specification(scope='self'), c.source_id)])
    script('copy', lambda c: [CopyMinion(c.target_id, c.player_id)],
        targeting=TargetSpec(kinds=(CardType.MINION,), relation='friendly'))
    script('silence', lambda c: [Silence(c.target_id)])
    script('bounce', lambda c: [ReturnToHand(c.target_id)])
    script('morph', lambda c: [Transform(c.target_id, 'beast')])
    script('steal', lambda c: [ChangeControl(c.target_id, 2)])
    script('invoke', lambda c: [TriggerBattlecry(MinionReference.capture(
        c.state.entities[find(c.state, 'dragon.cry')]), c.source_id)])
    script('other.enchantment', lambda c: [Buff(find(c.state, 'plain'), 1, 1, c.source_id)])
    script('other.spell.modifier', lambda c: [AddSpellRepeatModifier(c.player_id, source_id=c.source_id)])
    script('other.combo.modifier', lambda c: [AddComboRepeatModifier(c.player_id, source_id=c.source_id)])
    registry.register_player_effect(PlayerEffectSpec('other.effect', 'other.player.effect'))
    script('other.player.effect', lambda c: [AddPlayerEffect(c.player_id, 'other.effect', c.source_id)])
    script('scrap.parts', lambda c: [Destroy(i) for i in c.state.players[c.player_id].board
        if c.state.entities[i].card_id in ('part.dragon', 'part.beast')])
    script('bounce.ship', lambda c: [ReturnToHand(next(i for i in c.state.players[c.player_id].board
        if c.state.entities[i].card_id == 'ship.body'))])
    script('policy.dragon.expiring', lambda c: [AddBattlecryRepeatModifier(c.player_id,
        specification(tribes=('dragon',)), c.source_id, expires_turn=c.state.turn)])
    script('policy.remove', lambda c: [RemoveBattlecryRepeatModifier(c.player_id,
        c.state.players[c.player_id].battlecry_modifiers[0].id)])
    watch('commit.wait', 'card_committed', lambda c: [ask(c)]
        if c.play.kind == CardType.MINION else [])
    watch('commit.add', 'card_committed', lambda c: [Summon(1, 'dragon')]
        if c.play.kind == CardType.MINION else [])
    watch('commit.remove', 'card_committed', lambda c: [ReturnToHand(find(c.state, 'dragon'))]
        if c.play.kind == CardType.MINION else [])
    watch('commit.random', 'card_committed', lambda c: [RandomDestroy(tuple(
        i for i in c.state.players[1].board if c.state.entities[i].card_id in ('dragon', 'plain')))]
        if c.play.kind == CardType.MINION else [])
    watch('counter', 'minion_counter_check', lambda c: [CounterMinion(dict(c.event.data)['window_id'])])
    watch('entry.morph', 'minion_summoned', lambda c: [Transform(c.event.source_id, 'beast')]
        if c.state.entities[c.event.source_id].card_id == 'dragon.ask' else [])
    watch('limb.grant', 'minion_summoned', lambda c: [GrantBattlecryRepeatAura(
        find(c.state, 'giant.cry'), specification(scope='self'), c.event.source_id)]
        if c.state.entities[c.event.source_id].card_id == 'limb' else [])
    watch('limb.witness', 'minion_summoned', lambda c: [Summon(1, 'dragon')]
        if c.state.entities[c.event.source_id].card_id == 'limb' else [])
    watch('limb.silence', 'minion_summoned', lambda c: [Silence(find(c.state, 'giant.cry'))]
        if c.state.entities[c.event.source_id].card_id == 'limb' else [])
    return registry


class BattlecryMatchingTests(unittest.TestCase):
    def setUp(self):
        self.registry = fixture_registry()

    def game(self, *, hand=('dragon.cry',), board=(), enemy=(), seed=152):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board,
            deck=('hidden.source.card', 'plain'), mana=10, max_mana=10),
            PlayerSetup('hero', board=enemy, hand=('beast.cry',), deck=('plain',),
                mana=10, max_mana=10)), seed=seed), self.registry)

    def play(self, game, name='dragon.cry', target=None):
        entity = next(i for i in game.state.players[1].hand
            if game.state.entities[i].card_id == name)
        game.apply(PlayCard(1, entity, target))
        return entity

    def choose(self, game, option='ok'):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def finish_choices(self, game):
        while game.state.pending_choice is not None:
            self.portable(game)
            self.choose(game)

    def portable(self, game):
        snapshot = json.loads(json.dumps(game.snapshot()))
        fresh = fixture_registry()
        self.assertEqual(fresh.fingerprint(), self.registry.fingerprint())
        self.assertEqual(Game.from_snapshot(snapshot, fresh).snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), fixture_registry()).snapshot(), snapshot)

    def armor(self, game, player=1):
        return game.state.entities[game.state.players[player].hero_id].armor

    def receipt(self, game):
        return game.state.play_history[-1].battlecry_acceptance

    def plan(self, game):
        return self.receipt(game).plan

    def named(self, value, name):
        out = []
        if isinstance(value, dict):
            if value.get('type', '').endswith('.' + name):
                out.append(value)
            for child in value.values():
                out.extend(self.named(child, name))
        elif isinstance(value, list):
            for child in value:
                out.extend(self.named(child, name))
        return out

    def proof(self, game):
        return next(item for item in (*game._frame.prefix, *game._frame.continuation)
                    if type(item) is FinishBattlecryAcceptance)

    def reject(self, snapshot):
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(snapshot, fixture_registry())
        self.assertNotIn('digest mismatch', str(error.exception))

    def source_ability(self, snapshot, name):
        entity = next(e for e in snapshot['state']['entities'].values() if e['card_id'] == name)
        return next(a for a in entity['abilities'] if a['kind'] == 'battlecry_repeat')

    def test_friendly_and_self_match_physical_recipient_not_same_named_board_copy(self):
        game = self.game(hand=('self.cry', 'self.cry'), board=('self.cry', 'self.source'))
        first = self.play(game, 'self.cry')
        first_plan = self.plan(game)
        self.assertEqual((first_plan.repetitions, len(first_plan.contributors)), (2, 1))
        self.assertEqual(self.receipt(game).recipient, BattlecryRecipient(first, 'self.cry', CardType.MINION))
        second = self.play(game, 'self.cry')
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.plan(game).contributors), 1)
        self.assertNotEqual(first_plan.contributors, self.plan(game).contributors)
        self.assertEqual((self.armor(game), game.state.players[1].mana), (8, 8))
        self.portable(game)

    def test_copied_self_source_keeps_distinct_physical_identity(self):
        game = self.game(hand=('copy', 'dragon.cry'), board=('self.source',))
        original = game.state.players[1].board[0]
        self.play(game, 'copy', original)
        copies = [game.state.entities[i] for i in game.state.players[1].board]
        self.assertEqual(len(copies), 2)
        self.assertNotEqual(copies[0].abilities[0].id, copies[1].abilities[0].id)
        self.play(game)
        self.assertEqual(self.plan(game).contributors, ())
        self.assertEqual(self.armor(game), 2)
        self.portable(game)

    def test_dynamic_self_grant_uses_actual_carrier_not_appendage_donor(self):
        game = self.game(hand=('giant.cry',), board=('limb.grant',))
        body = self.play(game, 'giant.cry')
        ability = active_abilities(game.state.entities[body], 'battlecry_repeat')[0]
        self.assertNotEqual(ability.source_id, body)
        self.assertEqual(self.plan(game).contributors, (ability.id,))
        self.assertEqual(self.armor(game), 4)
        self.portable(game)

    def test_tribal_or_multitribe_all_and_empty_are_printed_metadata_queries(self):
        for name, count in (('dragon.cry', 2), ('multi.cry', 2), ('all.cry', 2),
                            ('beast.cry', 1), ('empty.cry', 1)):
            with self.subTest(name=name):
                game = self.game(hand=(name,), board=('tribal.2',))
                self.play(game, name)
                self.assertEqual((self.plan(game).repetitions, self.armor(game)), (count, count * 2))
                self.portable(game)
        recipient = BattlecryRecipient(77, 'beast.cry', CardType.MINION)
        self.assertTrue(battlecry_repeat_recipient_matches(specification(tribes=('dragon', 'beast')),
            recipient=recipient, recipient_definition=self.registry.card('beast.cry'), carrier_id=99))

    def test_empty_tribe_filter_does_not_demand_unused_metadata(self):
        for name in ('unknown.metadata.cry', 'unknown.tribes.cry'):
            recipient = BattlecryRecipient(77, name, CardType.MINION)
            self.assertTrue(battlecry_repeat_recipient_matches(specification(tribes=()),
                recipient=recipient, recipient_definition=self.registry.card(name), carrier_id=99))
        game = self.game(hand=('unknown.metadata.cry',), board=('friendly.2',))
        self.play(game, 'unknown.metadata.cry')
        self.assertEqual(self.armor(game), 4)
        self.portable(game)

    def test_required_recipient_metadata_unknown_rejects_paid_play_atomically(self):
        for name in ('unknown.metadata.cry', 'unknown.tribes.cry'):
            game = self.game(hand=(name,), board=('tribal.2',))
            before = game.snapshot()
            with self.assertRaises(ResolutionError):
                self.play(game, name)
            self.assertEqual(game.snapshot(), before)

    def test_nonminion_tribe_filter_is_false_without_irrelevant_metadata(self):
        for name in ('weapon.cry', 'hero.cry'):
            game = self.game(hand=(name,), board=('tribal.2', 'friendly.3'))
            self.play(game, name)
            self.assertEqual((self.plan(game).repetitions, len(self.plan(game).contributors)), (3, 1))
            self.assertEqual(self.armor(game), 6)
            self.assertEqual(self.receipt(game).recipient.kind, self.registry.card(name).kind)
            self.portable(game)

    def test_composed_ship_uses_physical_recipient_face_not_each_ability_declaration(self):
        game = self.game(hand=('scrap.parts', 'bounce.ship'),
            board=('tribal.2', 'beast.5', 'part.dragon', 'part.beast'))
        self.play(game, 'scrap.parts')
        ship_id = construction(game.state, 1).id
        game.apply(LaunchStarship(1, ship_id))
        self.assertEqual(game.state.battlecry_history, [])
        self.play(game, 'bounce.ship')
        self.play(game, 'ship.body')
        accepted = self.receipt(game)
        self.assertEqual(accepted.recipient, BattlecryRecipient(ship_id, 'ship.body', CardType.MINION))
        self.assertEqual([payload.card_id for payload in accepted.payloads], ['part.dragon', 'part.beast'])
        self.assertEqual((accepted.plan.repetitions, len(accepted.plan.contributors)), (5, 1))
        contributor = accepted.plan.contributors[0]
        self.assertEqual(active_abilities(game.state.entities[find(game.state, 'beast.5')],
            'battlecry_repeat')[0].id, contributor)
        self.assertEqual([record.repeat_index for record in game.state.battlecry_history],
            [1, 2, 3, 4, 5, 1, 2, 3, 4, 5])
        self.assertEqual((self.armor(game), game.state.players[1].mana), (20, 4))
        self.portable(game)

    def test_recipient_helper_requires_consistent_physical_definition_and_kind(self):
        game = self.game(board=('dragon.cry',))
        entity = find(game.state, 'dragon.cry')
        recipient = capture_recipient(game.state, self.registry, entity)
        self.assertEqual(recipient, BattlecryRecipient(entity, 'dragon.cry', CardType.MINION))
        before = game.snapshot()
        for replacement in (replace(recipient, card_id='beast.cry'), replace(recipient, kind=CardType.WEAPON)):
            with self.assertRaises(ValueError):
                battlecry_repeat_recipient_matches(specification(tribes=('dragon',)),
                    recipient=replacement, recipient_definition=self.registry.card('dragon.cry'), carrier_id=999)
        self.assertEqual(game.snapshot(), before)

    def test_another_excludes_source_carrier_but_played_recipient_can_witness(self):
        # A newly entered Dragon is a distinct physical witness for the source.
        game = self.game(board=('conditional.dragon',))
        played = self.play(game)
        self.assertNotEqual(played, game.state.players[1].board[0])
        self.assertEqual(self.plan(game).repetitions, 2)
        self.assertEqual(self.armor(game), 4)
        self.portable(game)
        # Its own Dragon identity is insufficient when the recipient is a Beast.
        game = self.game(hand=('beast.cry',), board=('conditional.dragon',))
        self.play(game, 'beast.cry')
        self.assertEqual(self.plan(game).contributors, ())
        self.portable(game)

    def test_same_card_different_entity_is_valid_another_witness(self):
        for sources, repetitions in ((1, 1), (2, 2)):
            game = self.game(hand=('beast.cry',), board=('another.dragon.any',) * sources)
            self.play(game, 'beast.cry')
            self.assertEqual(self.plan(game).repetitions, repetitions)
            self.assertEqual(len(self.plan(game).contributors), sources if sources == 2 else 0)
            self.assertEqual(self.armor(game), repetitions * 2)
            self.portable(game)

    def test_witness_profile_presence_changes_real_acceptance(self):
        # Use non-Dragon recipient so it cannot itself witness; matching tribe
        # is intentionally absent in these two registered dynamic declarations.
        for profile, expected in (('repeat.witness.controlled', 2), ('repeat.witness.active_live', 1)):
            registry = fixture_registry()
            registry.register_card(CardDefinition('profile.source', 'Profile source', CardType.MINION,
                health=5, metadata=metadata(), battlecry_repeats=(specification(
                    eligibility=witness(profile=profile)),)))
            game = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('beast.cry',),
                board=('profile.source', 'dormant.dragon'), mana=10, max_mana=10),
                PlayerSetup('hero')), seed=152), registry)
            self.play(game, 'beast.cry')
            self.assertEqual(self.plan(game).repetitions, expected)
            self.assertEqual(self.armor(game), expected * 2)
            self.assertEqual(Game.from_snapshot(game.snapshot(), registry).snapshot(), game.snapshot())

    def test_source_query_is_complete_before_kind_scope_and_tribe_false(self):
        for name, board in (('weapon.cry', ('conditional.narrow', 'dragon', 'unknown.metadata')),
                             ('beast.cry', ('conditional', 'dragon', 'unknown.tribes'))):
            game = self.game(hand=(name,), board=board)
            before = game.snapshot()
            with self.assertRaises(ResolutionError):
                self.play(game, name)
            self.assertEqual(game.snapshot(), before)
        registry = fixture_registry()
        registry.register_card(CardDefinition('self.conditional', 'Self condition', CardType.MINION,
            health=5, metadata=metadata(), battlecry_repeats=(specification(scope='self',
                eligibility=witness()),)))
        game = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('dragon.cry',),
            board=('self.conditional', 'unknown.metadata'), mana=10, max_mana=10),
            PlayerSetup('hero'))), registry)
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game)
        self.assertEqual(game.snapshot(), before)

    def test_physical_exclusion_and_any_witness_avoid_unused_metadata(self):
        registry = fixture_registry()
        registry.register_card(CardDefinition('unknown.source', 'Unknown source', CardType.MINION,
            health=5, battlecry_repeats=(specification(eligibility=witness()),)))
        game = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('dragon.cry',),
            board=('unknown.source',), mana=10, max_mana=10), PlayerSetup('hero'))), registry)
        self.play(game)
        self.assertEqual(self.plan(game).repetitions, 2)
        game = self.game(hand=('unknown.metadata.cry',), board=('conditional.any',))
        self.play(game, 'unknown.metadata.cry')
        self.assertEqual(self.plan(game).repetitions, 2)
        self.portable(game)

    def test_complete_max_retains_low_equal_high_and_finite_matching_sources(self):
        game = self.game(hand=('policy.dragon.one', 'policy.dragon.3', 'dragon.cry'),
            board=('tribal.2', 'tribal.3', 'tribal.5'))
        self.play(game, 'policy.dragon.one')
        self.play(game, 'policy.dragon.3')
        self.play(game)
        plan = self.plan(game)
        self.assertEqual((plan.repetitions, len(plan.contributors), len(plan.consumable_ids)), (5, 5, 2))
        self.assertFalse(game.state.players[1].battlecry_modifiers)
        self.assertEqual(sum(e.kind == 'battlecry_modifier_used' for e in game.events), 2)
        self.assertEqual((self.armor(game), game.state.players[1].mana), (10, 9))
        self.portable(game)

    def test_complete_plan_query_is_pure_and_does_not_consume_policy_or_rng(self):
        game = self.game(hand=('policy.dragon.two', 'dragon.cry'), board=('conditional', 'tribal.3', 'dragon'))
        self.play(game, 'policy.dragon.two')
        carrier = game.state.players[1].hand[0]
        recipient = capture_recipient(game.state, self.registry, carrier)
        before = game.snapshot()
        plan = capture_plan_from_state(game.state, self.registry, 1, recipient)
        self.assertEqual((plan.repetitions, len(plan.contributors), len(plan.consumable_ids)), (3, 3, 1))
        self.assertEqual(game.snapshot(), before)
        self.assertEqual(capture_plan_from_state(game.state, self.registry, 1, recipient), plan)
        self.assertEqual(game.snapshot(), before)
        self.play(game)
        self.assertEqual(self.plan(game), plan)
        self.assertEqual(game.state.players[1].battlecry_modifiers[0].uses_remaining, 1)
        self.portable(game)

    def test_player_tribe_filter_consumes_once_per_matching_paid_root(self):
        game = self.game(hand=('policy.dragon.two', 'beast.cry', 'dragon.ask', 'dragon.cry'))
        self.play(game, 'policy.dragon.two')
        self.play(game, 'beast.cry')
        self.assertEqual(game.state.players[1].battlecry_modifiers[0].uses_remaining, 2)
        self.play(game, 'dragon.ask')
        self.assertEqual(game.state.players[1].battlecry_modifiers[0].uses_remaining, 1)
        self.finish_choices(game)
        self.assertEqual(game.state.players[1].battlecry_modifiers[0].uses_remaining, 1)
        self.play(game)
        self.assertFalse(game.state.players[1].battlecry_modifiers)
        self.assertEqual(sum(e.kind == 'battlecry_modifier_used' for e in game.events), 2)
        self.assertEqual((self.armor(game), game.state.players[1].mana), (10, 7))
        self.portable(game)

    def test_opponent_filtered_source_and_modifier_do_not_contribute(self):
        game = self.game(board=('beast.5',), enemy=('tribal.5',))
        self.play(game)
        self.assertEqual(self.plan(game).contributors, ())
        self.assertEqual(self.armor(game), 2)
        self.portable(game)

    def test_commit_reactions_change_witness_before_original_acceptance(self):
        # Beast recipients cannot supply Dragon witnesses themselves.
        for watcher, starting, expected in (('commit.add', (), 2), ('commit.remove', ('dragon',), 1)):
            game = self.game(hand=('beast.cry',), board=('witness.only', watcher, *starting))
            self.play(game, 'beast.cry')
            self.assertEqual(self.plan(game).repetitions, expected)
            self.assertEqual(self.armor(game), expected * 2)
            self.portable(game)

    def test_normal_entry_transform_is_after_acceptance_and_keeps_old_face(self):
        game = self.game(hand=('dragon.ask',), board=('tribal.2', 'entry.morph'))
        played = self.play(game, 'dragon.ask')
        self.assertEqual(game.state.entities[played].card_id, 'beast')
        self.assertEqual(self.receipt(game).recipient.card_id, 'dragon.ask')
        self.assertEqual(self.plan(game).repetitions, 2)
        self.finish_choices(game)
        self.assertEqual(self.armor(game), 4)
        self.portable(game)

    def test_colossal_appendage_witness_is_before_delayed_acceptance(self):
        game = self.game(hand=('giant.cry',), board=('conditional',))
        self.play(game, 'giant.cry')
        self.assertTrue(game.state.colossal_history[0].completed)
        self.assertEqual(self.plan(game).repetitions, 2)
        self.assertEqual(self.armor(game), 4)
        self.portable(game)

    def test_generic_choice_stores_recipient_before_any_battlecry_batch(self):
        game = self.game(hand=('generic.transform.cry', 'beast.cry'), board=('tribal.2',))
        played = self.play(game, 'generic.transform.cry')
        self.assertEqual(game.state.battlecry_batches, [])
        self.assertEqual(self.receipt(game).recipient.carrier_id, played)
        self.assertEqual(self.plan(game).repetitions, 2)
        self.portable(game)
        self.choose(game)
        self.assertEqual(game.state.entities[played].card_id, 'beast')
        self.assertEqual(self.armor(game), 4)
        original = game.state.play_history[-1].battlecry_acceptance
        self.play(game, 'beast.cry')
        self.assertEqual(self.plan(game).repetitions, 1)
        self.assertEqual(original.recipient.card_id, 'generic.transform.cry')
        self.assertEqual(self.armor(game), 6)
        self.portable(game)

    def test_source_transfer_after_acceptance_does_not_cancel_but_next_root_rechecks_owner(self):
        game = self.game(hand=('move.source.cry', 'dragon.cry'), board=('tribal.2',))
        source_id = find(game.state, 'tribal.2')
        self.play(game, 'move.source.cry')
        self.assertEqual(game.state.entities[source_id].controller, 2)
        self.assertEqual(self.plan(game).repetitions, 2)
        self.portable(game)
        self.choose(game)
        self.assertEqual(self.armor(game), 4)
        self.play(game)
        self.assertEqual(self.plan(game).repetitions, 1)
        self.assertEqual(self.armor(game), 6)
        self.portable(game)

    def test_new_generic_source_grant_applies_only_to_the_next_accepted_root(self):
        game = self.game(hand=('grant.source.cry', 'dragon.cry'), board=('plain',))
        self.play(game, 'grant.source.cry')
        self.assertEqual(self.plan(game).contributors, ())
        self.assertEqual(len(active_abilities(game.state.entities[find(game.state, 'plain')],
            'battlecry_repeat')), 1)
        self.portable(game)
        self.choose(game)
        self.assertEqual(self.armor(game), 2)
        self.play(game)
        self.assertEqual(self.plan(game).repetitions, 2)
        self.assertEqual(self.armor(game), 6)
        self.portable(game)

    def test_nested_real_paid_root_accepts_new_condition_without_reclassifying_parent(self):
        game = self.game(hand=('nested.paid.cry', 'beast.ask'), board=('witness.only', 'dragon'))
        parent_id = self.play(game, 'nested.paid.cry')
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(len(game.state.play_history), 1)
        self.portable(game)
        self.choose(game)
        self.assertIsNotNone(game.state.pending_choice)
        parent, child = game.state.play_history
        self.assertEqual((parent.source_id, parent.battlecry_acceptance.plan.repetitions), (parent_id, 2))
        self.assertEqual(child.battlecry_acceptance.plan.repetitions, 1)
        self.assertNotEqual(parent.battlecry_acceptance.recipient.carrier_id,
            child.battlecry_acceptance.recipient.carrier_id)
        proofs = [item for item in (*game._frame.prefix, *game._frame.continuation)
            if type(item) is FinishBattlecryAcceptance]
        self.assertEqual(len(proofs), 2)
        self.portable(game)
        self.choose(game)
        self.assertEqual([batch.plan.repetitions for batch in game.state.battlecry_batches], [2, 1])
        self.assertEqual((self.armor(game), game.state.players[1].mana), (4, 8))
        self.assertTrue(all(record.completed for record in game.state.play_history))
        self.portable(game)

    def test_self_recipient_transformation_keeps_every_accepted_extra(self):
        game = self.game(hand=('self.transform.cry', 'beast.cry'))
        played = self.play(game, 'self.transform.cry')
        self.portable(game)
        self.choose(game)
        self.assertEqual(game.state.entities[played].card_id, 'beast')
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(self.plan(game).repetitions, 2)
        self.portable(game)
        self.choose(game)
        self.assertEqual(self.armor(game), 4)
        self.play(game, 'beast.cry')
        self.assertEqual(self.plan(game).contributors, ())
        self.portable(game)

    def test_removed_witness_does_not_reclassify_current_plan_or_history(self):
        game = self.game(hand=('remove.witness.cry', 'beast.cry'), board=('witness.only', 'dragon'))
        self.play(game, 'remove.witness.cry')
        self.assertEqual(self.plan(game).repetitions, 2)
        self.portable(game)
        self.choose(game)
        self.assertFalse(any(game.state.entities[i].card_id == 'dragon'
            for i in game.state.players[1].board))
        self.assertEqual(self.plan(game).repetitions, 2)
        self.portable(game)
        self.choose(game)
        self.assertEqual(self.armor(game), 4)
        original = game.state.play_history[-1].battlecry_acceptance
        self.play(game, 'beast.cry')
        self.assertEqual(self.plan(game).repetitions, 1)
        self.assertEqual(original.plan.repetitions, 2)
        self.portable(game)

    def test_all_false_unit_root_keeps_complete_original_proof_until_batch_finish(self):
        game = self.game(hand=('generic.beast.ask',), board=('tribal.2', 'self.source'))
        self.play(game, 'generic.beast.ask')
        self.assertEqual(self.plan(game).contributors, ())
        self.assertEqual(self.plan(game).repetitions, 1)
        self.assertEqual(game.state.battlecry_batches, [])
        proof = self.proof(game)
        self.assertEqual(len([a for e in proof.context.state.entities.values()
            for a in e.abilities if a.kind == 'battlecry_repeat']), 2)
        self.portable(game)
        self.choose(game)
        self.assertEqual(len(game.state.battlecry_history), 1)
        self.portable(game)

    def test_empty_effect_body_and_no_battlecry_have_distinct_receipts(self):
        game = self.game(hand=('policy.dragon.one', 'empty.body.cry', 'no.battlecry'))
        self.play(game, 'policy.dragon.one')
        self.play(game, 'empty.body.cry')
        self.assertEqual(len(self.receipt(game).payloads), 1)
        self.assertEqual(self.plan(game).repetitions, 2)
        self.assertFalse(game.state.players[1].battlecry_modifiers)
        self.assertEqual(len(game.state.battlecry_history), 2)
        self.play(game, 'no.battlecry')
        self.assertEqual(self.receipt(game).payloads, ())
        self.assertIsNone(self.plan(game))
        self.assertEqual(self.receipt(game).recipient.card_id, 'no.battlecry')
        self.assertEqual(self.named(game.snapshot()['resolution_frame'], 'FinishBattlecryAcceptance'), [])
        self.portable(game)
        self.choose(game)
        self.portable(game)

    def test_counter_skips_witness_queries_and_filtered_consumption(self):
        game = self.game(hand=('policy.dragon.one', 'dragon.cry'),
            board=('conditional', 'unknown.metadata', 'counter'))
        self.play(game, 'policy.dragon.one')
        self.play(game)
        self.assertEqual(game.state.play_history[-1].minion_result, 'countered')
        self.assertIsNone(self.receipt(game))
        self.assertEqual(game.state.players[1].battlecry_modifiers[0].uses_remaining, 1)
        self.assertEqual(game.state.battlecry_batches, [])
        self.portable(game)

    def test_commit_wait_precedes_recipient_receipt_and_matching_query(self):
        game = self.game(hand=('dragon.ask',), board=('tribal.2', 'commit.wait'))
        played = self.play(game, 'dragon.ask')
        self.assertEqual(game.state.entities[played].zone, Zone.PLAY)
        self.assertIsNone(self.receipt(game))
        self.portable(game)
        self.choose(game)
        self.assertEqual(self.receipt(game).recipient.carrier_id, played)
        self.assertEqual(self.plan(game).repetitions, 2)
        self.finish_choices(game)
        self.portable(game)

    def test_colossal_silence_before_delayed_acceptance_is_explicit_empty(self):
        game = self.game(hand=('giant.cry',), board=('tribal.2', 'limb.silence'))
        self.play(game, 'giant.cry')
        self.assertEqual(self.receipt(game).payloads, ())
        self.assertIsNone(self.plan(game))
        self.assertEqual(self.receipt(game).recipient.card_id, 'giant.cry')
        self.assertEqual(game.state.battlecry_history, [])
        self.portable(game)

    def test_effect_battlecry_origin_does_not_capture_or_consume_hand_policy(self):
        game = self.game(hand=('policy.dragon.one', 'invoke'), board=('dragon.cry', 'tribal.5'))
        self.play(game, 'policy.dragon.one')
        self.play(game, 'invoke')
        self.assertEqual(self.armor(game), 2)
        self.assertEqual([r.origin for r in game.state.battlecry_history], ['effect'])
        self.assertEqual(game.state.players[1].battlecry_modifiers[0].uses_remaining, 1)
        self.assertEqual(game.state.battlecry_batches, [])
        self.portable(game)

    def test_retained_outcomes_share_recipient_and_original_condition_plan(self):
        game = self.game(hand=('retained.cry',), board=('conditional', 'dragon', 'retainer'))
        self.play(game, 'retained.cry')
        recipient = self.receipt(game).recipient
        for index in range(4):
            self.assertIsNotNone(game.state.pending_choice)
            self.assertEqual(self.receipt(game).recipient, recipient)
            self.assertEqual(self.plan(game).repetitions, 2)
            self.portable(game)
            self.choose(game)
        self.assertIsNone(game.state.pending_choice)
        self.assertEqual([(r.iteration, r.repeat_index) for r in game.state.battlecry_history],
            [(1, 1), (1, 2), (2, 1), (2, 2)])
        self.assertEqual((self.armor(game), game.state.players[1].mana), (4, 9))
        self.portable(game)

    def test_ordinary_rewind_retry_rebuilds_receipt_without_extra_payment(self):
        game = self.game(hand=('policy.dragon.one', 'rewind.cry'), board=('tribal.2',))
        self.play(game, 'policy.dragon.one')
        played = self.play(game, 'rewind.cry')
        first = self.receipt(game)
        self.assertEqual(first.recipient.carrier_id, played)
        self.assertEqual(first.plan.repetitions, 2)
        self.portable(game)
        self.choose(game, 'retry')
        self.assertEqual(self.receipt(game).recipient.carrier_id, played)
        self.assertEqual(len(game.state.play_history), 2)
        self.assertFalse(game.state.players[1].battlecry_modifiers)
        # Diagnostic logs retain the abandoned attempt; current paid history
        # and budget are restored, then accepted/consumed once on the retry.
        self.assertEqual(sum(e.kind == 'battlecry_modifier_used' for e in game.events), 2)
        self.assertEqual(len(game.state.battlecry_batches), 1)
        self.assertEqual(len(game.state.battlecry_history), 2)
        self.assertEqual(game.state.players[1].mana, 9)
        self.portable(game)
        self.choose(game, 'keep')
        self.portable(game)

    def test_false_board_sources_are_statically_bound_without_live_reclassification(self):
        game = self.game(hand=('generic.beast.ask',), board=('tribal.2', 'self.source'))
        self.play(game, 'generic.beast.ask')
        self.assertEqual(self.plan(game).contributors, ())
        for field, value in (('scope', 'self'), ('repetitions', 3)):
            snapshot = game.snapshot()
            ability = self.source_ability(snapshot, 'self.source' if field == 'repetitions' else 'tribal.2')
            if field == 'scope':
                ability['battlecry_repeat']['kinds'] = ['minion']
            ability['battlecry_repeat'][field] = value
            self.reject(snapshot)
        self.portable(game)

    def test_false_player_policy_keeps_original_identity_and_unconsumed_uses(self):
        game = self.game(hand=('policy.dragon.two', 'generic.beast.ask'))
        self.play(game, 'policy.dragon.two')
        self.play(game, 'generic.beast.ask')
        self.assertEqual(self.plan(game).contributors, ())
        self.assertEqual(game.state.players[1].battlecry_modifiers[0].uses_remaining, 2)
        self.portable(game)
        for mode in ('tribes', 'uses.increase', 'owner'):
            snapshot = game.snapshot()
            policies = snapshot['state']['players']['1']['battlecry_modifiers']
            if mode == 'tribes':
                policies[0]['spec']['match']['recipient_metadata']['tribes_any'] = ['beast']
            elif mode == 'uses.increase':
                policies[0]['uses_remaining'] = 3
            else:
                snapshot['state']['players']['2']['battlecry_modifiers'].append(policies.pop())
            self.reject(snapshot)

    def test_false_source_same_attachment_cannot_be_moved_to_another_physical_carrier(self):
        game = self.game(hand=('generic.beast.ask',), board=('tribal.2', 'plain'))
        self.play(game, 'generic.beast.ask')
        snapshot = game.snapshot()
        entities = snapshot['state']['entities'].values()
        source = next(e for e in entities if e['card_id'] == 'tribal.2')
        target = next(e for e in entities if e['card_id'] == 'plain')
        target['abilities'].append(source['abilities'].pop())
        self.reject(snapshot)

    def test_completed_compact_plan_cannot_relabel_other_global_attachment_family_as_removed(self):
        for name in ('other.enchantment', 'other.spell.modifier',
                     'other.combo.modifier', 'other.player.effect'):
            game = self.game(hand=(name, 'dragon.cry'), board=('tribal.2', 'plain'))
            self.play(game, name)
            self.play(game)
            self.assertIsNone(game.snapshot()['resolution_frame'])
            self.assertTrue(game.state.play_history[-1].completed)
            if name == 'other.enchantment':
                other_id = game.state.entities[find(game.state, 'plain')].enchantments[0].id
            elif name == 'other.spell.modifier':
                other_id = game.state.players[1].spell_modifiers[0].id
            elif name == 'other.combo.modifier':
                other_id = game.state.players[1].combo_modifiers[0].id
            else:
                other_id = game.state.players[1].player_effects[0].id
            snapshot = game.snapshot()
            snapshot['state']['play_history'][-1]['battlecry_acceptance']['plan']['contributors'] = [other_id]
            snapshot['state']['battlecry_batches'][-1]['plan']['contributors'] = [other_id]
            self.reject(snapshot)
            self.portable(game)

    def test_recipient_receipt_and_active_original_operand_cannot_be_forged(self):
        game = self.game(hand=('generic.dragon.ask',), board=('tribal.2',))
        self.play(game, 'generic.dragon.ask')
        for mode in ('missing', 'carrier', 'face', 'kind', 'original.face'):
            snapshot = game.snapshot()
            receipt = snapshot['state']['play_history'][-1]['battlecry_acceptance']
            if mode == 'missing':
                receipt.pop('recipient')
            elif mode == 'carrier':
                receipt['recipient']['carrier_id'] = game.state.players[1].board[0]
            elif mode == 'face':
                receipt['recipient']['card_id'] = 'beast.cry'
            elif mode == 'kind':
                receipt['recipient']['kind'] = 'weapon'
            else:
                proof = self.named(snapshot['resolution_frame'], 'FinishBattlecryAcceptance')[0]
                proof['fields']['context']['fields']['play']['fields']['battlecry_acceptance']['fields']['recipient']['fields']['card_id'] = 'beast.cry'
            self.reject(snapshot)

    def test_false_unit_root_cannot_delete_complete_schedule_and_acceptance_proof(self):
        game = self.game(hand=('generic.beast.ask',), board=('tribal.2',))
        self.play(game, 'generic.beast.ask')
        for mode in ('proof', 'schedule', 'both'):
            snapshot = game.snapshot()
            queue = snapshot['resolution_frame']['fields']['continuation']['tuple']
            names = ({'FinishBattlecryAcceptance'} if mode == 'proof' else
                     {'BeginBattlecryBatch'} if mode == 'schedule' else
                     {'FinishBattlecryAcceptance', 'BeginBattlecryBatch'})
            queue[:] = [work for work in queue if not any(
                work.get('type', '').endswith('.' + name) for name in names)]
            self.reject(snapshot)

    def test_condition_fields_and_profiles_are_strict_in_private_wire_and_frames(self):
        matching = BattlecryRepeatMatchSpec(BattlecryRecipientMetadataFilter(
            tribes_any=('dragon',)), witness())
        encoded = battlecry_match_to_dict(matching)
        self.assertEqual(battlecry_match_from_dict(encoded), matching)
        for key in ('recipient_metadata', 'source_eligibility'):
            invalid = copy.deepcopy(encoded)
            invalid.pop(key)
            with self.assertRaises(ValueError):
                battlecry_match_from_dict(invalid)
        invalid = copy.deepcopy(encoded)
        invalid['source_eligibility']['exclude_carrier'] = 1
        with self.assertRaises(ValueError):
            battlecry_match_from_dict(invalid)
        game = self.game()
        codec = FrameCodec(game.mechanics, game.registry)
        bad = specification(eligibility=witness(profile='missing.profile'))
        for value in (bad, bad.match, bad.match.source_eligibility,
                      GrantBattlecryRepeatAura(999, bad),
                      AbilityInstance(999, 'battlecry_repeat', battlecry_repeat=bad)):
            with self.assertRaises(ValueError):
                codec.decode(codec.encode(value))

    def test_invalid_scope_basis_tribes_and_player_source_consumers_fail_explicitly(self):
        for callback in (
                lambda: BattlecryRecipientMetadataFilter('current_face_printed', ('dragon',)),
                lambda: BattlecryRecipientMetadataFilter(tribes_any=['dragon']),
                lambda: BattlecryRecipientMetadataFilter(tribes_any=('dragon', 'dragon')),
                lambda: BattlecryRepeatSpec(scope='self'),
                lambda: specification(scope='self', kinds=(CardType.MINION, CardType.WEAPON)),
                lambda: specification(scope='enemy'),
                lambda: AddBattlecryRepeatModifier(1, specification(scope='self')),
                lambda: AddBattlecryRepeatModifier(1, specification(eligibility=witness()))):
            with self.assertRaises(ValueError):
                callback()
        with self.assertRaises(ValueError):
            self.registry.register_card(CardDefinition('bad.profile', 'Bad profile', CardType.MINION,
                health=1, battlecry_repeats=(specification(eligibility=witness(profile='missing.profile')),)))
        with self.assertRaises(ValueError):
            self.registry.card('bad.profile')

    def test_public_player_rule_facts_include_scope_and_detached_tribes_only(self):
        game = self.game(hand=('policy.hidden', 'dragon.ask'))
        self.play(game, 'policy.hidden')
        expected = {'repetitions': 2, 'kinds': ['minion', 'weapon', 'hero'],
            'scope': 'friendly', 'match': {'recipient_metadata': {
                'basis': 'accepted_carrier_face_printed', 'tribes_any': ['dragon']}},
            'uses_remaining': 2, 'expires_turn': None}
        for seat in (1, 2):
            observed = next(p for p in game.observe(seat)['players'] if p['id'] == 1)
            self.assertEqual(observed['battlecry_modifiers'], [expected])
            observed['battlecry_modifiers'][0]['match']['recipient_metadata']['tribes_any'].append('beast')
            current = next(p for p in game.observe(seat)['players'] if p['id'] == 1)
            self.assertEqual(current['battlecry_modifiers'], [expected])
            event = next(e for e in game.player_events(seat) if e['kind'] == 'battlecry_modifier_added')
            self.assertIsNone(event['source'])
            self.assertEqual(event['battlecry_modifier'], expected)
        self.play(game, 'dragon.ask')
        forbidden = ('battlecry_acceptance', 'BattlecryRecipient', 'FinishBattlecryAcceptance',
            'resolution_frame', 'source_eligibility', 'profile_id', 'contributors',
            'consumable_ids', 'witness_ids', 'rng_state', 'policy_source_id')
        for seat in (1, 2):
            port = game.for_player(seat)
            payload = json.dumps((port.observe(), port.legal_actions(), port.events()))
            self.assertNotIn('hidden.source.card', payload)
            for key in forbidden:
                self.assertNotIn('"' + key + '"', payload)
        self.portable(game)
        self.finish_choices(game)
        self.portable(game)

    def test_public_modifier_wire_rejects_private_conditions_and_forged_scope(self):
        game = self.game(hand=('policy.dragon.two',))
        self.play(game, 'policy.dragon.two')
        view = next(p for p in game.observe(1)['players'] if p['id'] == 1)['battlecry_modifiers'][0]
        validate_battlecry_modifier_view(view, 'battlecry_modifier_added')
        for mode in ('source', 'scope', 'missing', 'basis'):
            invalid = copy.deepcopy(view)
            if mode == 'source':
                invalid['match']['source_eligibility'] = {'profile_id': 'repeat.witness.controlled',
                    'tribes_any': [], 'exclude_carrier': False}
            elif mode == 'scope':
                invalid['scope'] = 'self'
            elif mode == 'missing':
                invalid.pop('match')
            else:
                invalid['match']['recipient_metadata']['basis'] = 'current_face_printed'
            with self.assertRaises(ValueError):
                validate_battlecry_modifier_view(invalid, 'battlecry_modifier_added')

    def test_filtered_public_added_used_removed_and_expired_events_share_detached_rule_facts(self):
        cases = (('policy.dragon.one', 'dragon.cry', 'battlecry_modifier_used'),
                 ('policy.dragon.two', 'policy.remove', 'battlecry_modifier_removed'),
                 ('policy.dragon.expiring', None, 'battlecry_modifier_expired'))
        for grant, following, event_kind in cases:
            game = self.game(hand=(grant, *((following,) if following else ())))
            self.play(game, grant)
            if following:
                self.play(game, following)
            else:
                game.apply(EndTurn(1))
            for seat in (1, 2):
                event = next(e for e in game.player_events(seat) if e['kind'] == event_kind)
                view = event['battlecry_modifier']
                self.assertEqual(view['scope'], 'friendly')
                self.assertEqual(view['match'], {'recipient_metadata': {
                    'basis': 'accepted_carrier_face_printed', 'tribes_any': ['dragon']}})
                validate_battlecry_modifier_view(view, event_kind)
                self.assertNotIn('source_eligibility', json.dumps(view))
                self.assertNotIn('modifier_id', json.dumps(event))
            self.portable(game)

    def test_budget_and_mid_body_failures_roll_back_receipts_rng_and_resources(self):
        for name, board, error in (('dragon.cry', ('huge',), ResolutionLimitExceeded),
                ('bad.body.cry', ('tribal.2',), ResolutionError)):
            game = self.game(hand=(name,), board=board)
            before = game.snapshot()
            with self.assertRaises(error):
                self.play(game, name)
            self.assertEqual(game.snapshot(), before)
        game = self.game(hand=('policy.dragon.one', 'bad.choice.cry'))
        self.play(game, 'policy.dragon.one')
        self.play(game, 'bad.choice.cry')
        before = game.snapshot()
        self.assertFalse(game.state.players[1].battlecry_modifiers)
        with self.assertRaises(ResolutionError):
            self.choose(game)
        self.assertEqual(game.snapshot(), before)
        self.portable(game)

    def test_terminal_after_acceptance_keeps_original_recipient_and_interrupts_extras(self):
        game = self.game(hand=('fatal.cry',), board=('tribal.3',))
        played = self.play(game, 'fatal.cry')
        self.assertEqual(self.receipt(game).recipient.carrier_id, played)
        self.assertEqual(self.plan(game).repetitions, 3)
        self.assertEqual(len(game.state.battlecry_history), 1)
        self.assertTrue(game.state.battlecry_batches[0].interrupted)
        self.portable(game)


if __name__ == '__main__':
    unittest.main()
