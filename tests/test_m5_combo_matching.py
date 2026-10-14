"""B2-02 physical Combo operands, two independent windows and whole-root proof.

Synthetic declarations exercise actual paid MINION/WEAPON/HERO entry points.
They do not establish a constructed tribal source, CN timing, pre-entry face
transformation, arbitrary dynamic Combo bodies, or same-action paid nesting.
"""
import copy
import json
import unittest
from dataclasses import replace

from hs_sim.engine import (AppendageSpec, CardClass, CardDefinition, CardMetadata,
    CardType, EndTurn, Game, IllegalAction, Keyword, LaunchStarship, PlayCard,
    PlayerEffectSpec, PlayerSetup, Registry, ResolutionError,
    ResolutionLimitExceeded, RewindSpec, Scenario, SelectChoice, SnapshotError,
    TargetSpec, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.model import (BattlecryRepeatSpec, ComboRecipient,
    ComboRecipientMetadataFilter, ComboRepeatMatchSpec, ComboRepeatSpec,
    RepeatSourceEligibility, RepeatWitnessProfile)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, DamageBatch, Destroy, GainArmor, InvokeBehavior, RandomDamage,
    RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.combo_matching import (capture_recipient, combo_match_from_dict,
    combo_match_to_dict, combo_repeat_recipient_matches)
from hs_sim.engine.combo_modifiers import AddComboRepeatModifier, RemoveComboRepeatModifier
from hs_sim.engine.combo_repeats import GrantComboRepeatAura, capture_plan_from_state
from hs_sim.engine.battlecry_modifiers import AddBattlecryRepeatModifier
from hs_sim.engine.spell_modifiers import AddSpellRepeatModifier
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.resolver import PlayFromHand
from hs_sim.engine.interrupts import CounterMinion
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.starships import construction


def metadata(tribes=()):
    return CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=tribes)


def specification(count=2, *, tribes=None, scope='friendly', eligibility=None,
                  kinds=(CardType.MINION,)):
    recipient = None if tribes is None else ComboRecipientMetadataFilter(
        'accepted_window_face_printed', tribes)
    matching = (ComboRepeatMatchSpec(recipient, eligibility)
                if recipient is not None or eligibility is not None else None)
    return ComboRepeatSpec(count, kinds, scope, matching)


def witness(*, another=True, tribes=('beast',), profile='repeat.witness.controlled'):
    return RepeatSourceEligibility(profile, tribes, another)


def find(state, name, player=1):
    return next(i for i in state.players[player].board
                if state.entities[i].card_id == name)


def ask(context, effects=()):
    return RequestChoice(context.player_id,
        (ChoiceOption('ok', 'Resolve', tuple(effects)),), source_id=context.source_id)


def fixture_registry():
    registry = Registry('combo-matching-public-fixtures-v1')
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

    def combo(name, *, behavior='armor', tribes=('dragon',), **fields):
        fields['keywords'] = tuple(dict.fromkeys((*fields.get('keywords', ()), Keyword.COMBO)))
        minion(name, tribes=tribes, combo=behavior, **fields)

    def script(name, callback, **fields):
        registry.register_behavior(name, callback)
        registry.register_card(CardDefinition(name, name, CardType.SPELL,
            on_play=name, metadata=metadata(), **fields))

    def watch(name, event, callback):
        registry.register_behavior(name, callback)
        minion(name, cost=0, triggers=(TriggerSpec(event, name),))

    for name, tribes in (('plain', ()), ('dragon', ('dragon',)), ('beast', ('beast',)),
            ('multi', ('dragon', 'beast')), ('all', ('all',)), ('unknown.tribes', None),
            ('hidden.card', ()), ('opponent.hidden', ())):
        minion(name, tribes=tribes)
    minion('unknown.metadata', meta=None)
    minion('dormant.beast', tribes=('beast',), dormant_turns=None)
    minion('retainer', retain_rewind_outcomes=True)
    for name, spec, tribes in (
            ('friendly.2', specification(), ()),
            ('friendly.3', specification(3), ()),
            ('friendly.5', specification(5), ()),
            ('tribal.2', specification(tribes=('dragon',)), ()),
            ('tribal.3', specification(3, tribes=('dragon',)), ()),
            ('tribal.5', specification(5, tribes=('dragon',)), ()),
            ('beast.5', specification(5, tribes=('beast',)), ()),
            ('self.source', specification(3, scope='self'), ()),
            ('conditional', specification(tribes=('dragon',), eligibility=witness()), ()),
            ('conditional.any', specification(eligibility=witness()), ()),
            ('conditional.dragon', specification(eligibility=witness(tribes=('dragon',))), ('dragon',)),
            ('ordinary.dragon', specification(eligibility=witness(another=False, tribes=('dragon',))), ('dragon',)),
            ('conditional.active', specification(eligibility=witness(profile='repeat.witness.active_live')), ()),
            ('any.witness', specification(eligibility=witness(tribes=())), ()),
            ('all.kinds', specification(kinds=(CardType.MINION, CardType.WEAPON, CardType.HERO)), ()),
            ('all.kinds.tribal', specification(tribes=('dragon',), kinds=(CardType.MINION, CardType.WEAPON, CardType.HERO)), ()),
            ('huge', specification(100001, tribes=('dragon',)), ())):
        minion(name, tribes=tribes, combo_repeats=(spec,))
    for name, tribes in (('dragon.combo', ('dragon',)), ('beast.combo', ('beast',)),
            ('plain.combo', ()), ('multi.combo', ('dragon', 'beast')),
            ('all.combo', ('all',)), ('unknown.tribes.combo', None)):
        combo(name, tribes=tribes)
    combo('unknown.metadata.combo', meta=None)
    combo('self.combo', combo_repeats=(specification(3, scope='self', tribes=('dragon',)),))
    registry.register_behavior('ask', lambda c: [ask(c, (GainArmor(c.player_id, 2),))])
    combo('dragon.ask', behavior='ask')
    combo('beast.ask', behavior='ask', tribes=('beast',))
    registry.register_behavior('generic.ask', lambda c: [ask(c)])
    combo('generic.dragon.ask', on_play='generic.ask')
    combo('generic.beast.ask', tribes=('beast',), on_play='generic.ask')
    registry.register_behavior('generic.transform', lambda c: [ask(c, (Transform(c.source_id, 'beast'),))])
    combo('generic.transform.combo', on_play='generic.transform')
    minion('no.combo', tribes=('dragon',), on_play='generic.ask')
    registry.register_behavior('empty', lambda c: [])
    combo('empty.combo', behavior='empty')
    registry.register_behavior('retained', lambda c: [ask(c, (
        *((ReturnToHand(find(c.state, 'beast')), Transform(c.source_id, 'plain'))
          if c.combo.iteration == 1 and c.combo.repeat_index == 1 else ()),
        GainArmor(c.player_id, 1)))])
    combo('retained.combo', behavior='retained', keywords=(Keyword.REWIND,), rewind=RewindSpec(1))
    registry.register_behavior('ordinary.rewind', lambda c: [GainArmor(c.player_id, c.rewind_attempt + 1)])
    combo('rewind.combo', behavior='ordinary.rewind', keywords=(Keyword.REWIND,), rewind=RewindSpec(1))
    registry.register_behavior('fatal', lambda c: [Damage(c.state.players[2].hero_id, 100)])
    combo('fatal.combo', behavior='fatal')
    registry.register_behavior('bad.body', lambda c: [RandomDamage((c.state.players[2].hero_id,), 1), Summon(1, 'missing')])
    combo('bad.combo', behavior='bad.body')
    registry.register_behavior('fail.after.random', lambda c: [Summon(1, 'missing')])
    registry.register_behavior('bad.choice', lambda c: [ask(c, (RandomDamage((c.state.players[2].hero_id,), 1),
        InvokeBehavior('fail.after.random', c.source_id, c.player_id)))])
    combo('bad.choice.combo', behavior='bad.choice')
    minion('limb', tribes=('beast',))
    combo('giant.combo', keywords=(Keyword.COLOSSAL,), colossal=(AppendageSpec('limb'),))
    combo('part.dragon', keywords=(Keyword.STARSHIP_PIECE,))
    combo('part.beast', tribes=('beast',), keywords=(Keyword.STARSHIP_PIECE,))
    minion('ship.body', tribes=('beast',), health=0, starship_for=(CardClass.NEUTRAL,))
    combo('magnet.combo', tribes=('mech',), keywords=(Keyword.MAGNETIC,), magnetic_tribes=('mech',))
    minion('mech', tribes=('mech',))
    registry.register_behavior('equipped', lambda c: [GainArmor(c.player_id,
        2 if c.state.players[c.player_id].weapon_id == c.source_id else 99)])
    registry.register_card(CardDefinition('weapon.combo', 'Weapon Combo', CardType.WEAPON,
        cost=1, attack=1, durability=2, keywords=(Keyword.COMBO,), combo='equipped'))
    registry.register_behavior('replaced', lambda c: [GainArmor(c.player_id,
        2 if c.state.players[c.player_id].hero_id == c.source_id else 99)])
    registry.register_card(CardDefinition('hero.combo', 'Hero Combo', CardType.HERO,
        cost=1, health=30, hero_card=True, initial_hero_power='power',
        keywords=(Keyword.COMBO,), combo='replaced'))
    minion('bc.source', battlecry_repeats=(BattlecryRepeatSpec(),))
    registry.register_behavior('mixed.generic', lambda c: [ask(c, (GainArmor(c.player_id, 5),))])
    combo('mixed.combo', on_play='mixed.generic', battlecry='armor')
    script('prime', lambda c: [])
    script('policy.both', lambda c: [AddComboRepeatModifier(c.player_id, specification(2, tribes=('dragon',)), c.source_id, 2, trigger='play'),
        AddComboRepeatModifier(c.player_id, specification(3, tribes=('dragon',)), c.source_id, 2, trigger='activation')])
    script('policy.play.one', lambda c: [AddComboRepeatModifier(c.player_id,
        specification(tribes=('dragon',)), c.source_id, 1, trigger='play')])
    script('policy.activation.one', lambda c: [AddComboRepeatModifier(c.player_id,
        specification(tribes=('dragon',)), c.source_id, 1, trigger='activation')])
    script('policy.false', lambda c: [AddComboRepeatModifier(c.player_id,
        specification(5, tribes=('dragon',)), c.source_id, 2, trigger='play')])
    script('policy.unlimited', lambda c: [AddComboRepeatModifier(c.player_id,
        specification(tribes=('dragon',)), c.source_id, trigger='play')])
    script('policy.expire', lambda c: [AddComboRepeatModifier(c.player_id,
        specification(tribes=('dragon',)), c.source_id, 1, c.state.turn, 'activation')])
    registry.register_behavior('policy.power', lambda c: [
        AddComboRepeatModifier(1, specification(tribes=('dragon',)), c.source_id, 1, trigger='play'),
        AddComboRepeatModifier(1, specification(3, tribes=('dragon',)), c.source_id, 1, trigger='activation')])
    registry.register_card(CardDefinition('policy.power', 'Policy power', CardType.HERO_POWER, on_use='policy.power'))
    script('mixed.policies', lambda c: [AddBattlecryRepeatModifier(1, source_id=c.source_id, uses=1),
        AddComboRepeatModifier(1, specification(3), c.source_id, 1, trigger='activation')])
    script('scrap', lambda c: [DamageBatch(tuple(Damage(i, 100) for i in c.state.players[1].board))])
    script('bounce', lambda c: [ReturnToHand(c.target_id)], targeting=TargetSpec())
    script('other.enchantment', lambda c: [Buff(find(c.state, 'plain'), 1, 1)])
    script('other.spell.modifier', lambda c: [AddSpellRepeatModifier(1, source_id=c.source_id)])
    script('other.bc.modifier', lambda c: [AddBattlecryRepeatModifier(1, source_id=c.source_id)])
    effect_spec = PlayerEffectSpec('other.effect', 'hidden.card')
    registry.register_player_effect(effect_spec)
    script('other.player.effect', lambda c: [AddPlayerEffect(1, 'other.effect', c.source_id)])
    script('copy', lambda c: [CopyMinion(c.target_id, 1)], targeting=TargetSpec())
    watch('commit.wait', 'card_committed', lambda c: [ask(c)] if c.play.kind == CardType.MINION else [])
    watch('counter', 'minion_counter_check', lambda c: [CounterMinion(dict(c.event.data)['window_id'])])
    watch('fill', 'minion_counter_check', lambda c: [Summon(1, 'plain') for _ in range(6)])
    watch('entry.morph', 'minion_summoned', lambda c: [Transform(c.event.source_id, 'beast')]
        if c.state.entities[c.event.source_id].card_id == 'dragon.ask' else [])
    watch('entry.steal', 'minion_summoned', lambda c: [ChangeControl(c.event.source_id, 2)]
        if c.state.entities[c.event.source_id].card_id == 'dragon.ask' else [])
    watch('entry.remove', 'minion_summoned', lambda c: [ReturnToHand(find(c.state, 'beast'))]
        if c.state.entities[c.event.source_id].card_id == 'dragon.ask' else [])
    watch('limb.remove', 'minion_summoned', lambda c: [ReturnToHand(c.event.source_id)]
        if c.state.entities[c.event.source_id].card_id == 'limb' else [])
    watch('limb.silence', 'minion_summoned', lambda c: [Silence(find(c.state, 'giant.combo'))]
        if c.state.entities[c.event.source_id].card_id == 'limb' else [])
    for name, operation in (('giant.kill', Destroy), ('giant.bounce', ReturnToHand),
                            ('giant.steal', lambda i: ChangeControl(i, 2)),
                            ('giant.morph', lambda i: Transform(i, 'plain'))):
        watch(name, 'minion_summoned', lambda c, op=operation: [op(c.event.source_id)]
            if c.state.entities[c.event.source_id].card_id == 'giant.combo' else [])
    watch('commit.lethal', 'card_committed', lambda c: [Damage(c.state.players[2].hero_id, 100)]
        if c.play.kind == CardType.MINION else [])
    watch('entry.lethal', 'minion_summoned', lambda c: [Damage(c.state.players[2].hero_id, 100)]
        if c.state.entities[c.event.source_id].card_id == 'dragon.combo' else [])
    watch('used.wait', 'combo_modifier_used', lambda c: [ask(c)])
    watch('bc.used.wait', 'battlecry_modifier_used', lambda c: [ask(c)])
    return registry


class ComboMatchingTests(unittest.TestCase):
    def setUp(self):
        self.registry = fixture_registry()
        self.extensions = []

    def extend(self, builder):
        builder(self.registry)
        self.extensions.append(builder)

    def fresh(self):
        registry = fixture_registry()
        for builder in self.extensions:
            builder(registry)
        self.assertEqual(registry.fingerprint(), self.registry.fingerprint())
        return registry

    def game(self, *, hand=('dragon.combo',), board=(), enemy=(), primed=True, power='power'):
        game = Game.from_scenario(Scenario((PlayerSetup('hero', hand=(('prime',) if primed else ()) + hand,
            board=board, hero_power_card_id=power, deck=('hidden.card',), mana=10, max_mana=10),
            PlayerSetup('hero', hand=('opponent.hidden',), board=enemy, deck=('plain',), mana=10, max_mana=10)),
            seed=153), self.registry)
        if primed:
            self.play(game, 'prime')
        return game

    def play(self, game, name='dragon.combo', target=None, position=None):
        entity = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == name)
        game.apply(PlayCard(1, entity, target, position=position))
        return entity

    def choose(self, game, option='ok'):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def portable(self, game):
        snapshot = json.loads(json.dumps(game.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot, self.fresh()).snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), self.fresh()).snapshot(), snapshot)
        self.private_absent(game)

    def finish_choices(self, game):
        while game.state.pending_choice is not None:
            self.portable(game)
            self.choose(game)

    def armor(self, game, player=1):
        return game.state.entities[game.state.players[player].hero_id].armor

    def receipt(self, game, index=-1):
        return game.state.play_history[index].combo_acceptance

    def policies(self, game, record=None):
        record = game.state.play_history[-1] if record is None else record
        return [r for r in game.state.combo_policy_receipts if r.play_id == record.id]

    def plan(self, game):
        return self.receipt(game).plan

    def private_absent(self, game):
        forbidden = ('combo_acceptance', 'combo_submission_receipt_id', 'combo_policy_receipts',
            'FinishComboAcceptance', 'resolution_frame', 'contributors', 'consumable_ids',
            'source_eligibility', 'profile_id', 'rng_state', 'consumption_applied')
        for player in (1, 2):
            port = game.for_player(player)
            encoded = json.dumps((port.observe(), port.legal_actions(), port.events()))
            for field in forbidden:
                self.assertNotIn('"' + field + '"', encoded)
        self.assertNotIn('opponent.hidden', json.dumps(game.for_player(1).observe()))

    def named(self, value, name):
        out = []
        if isinstance(value, dict):
            if value.get('type', '').endswith('.' + name):
                out.append(value)
            for key, child in value.items():
                if key == 'fields' and value.get('type') == 'hs_sim.engine.paid_hand_acceptance.PaidHandChoiceBoundaryProof':
                    for field, operand in child.items():
                        if field != 'work':
                            out.extend(self.named(operand, name))
                else:
                    out.extend(self.named(child, name))
        elif isinstance(value, list):
            for child in value:
                out.extend(self.named(child, name))
        return out

    def reject(self, snapshot):
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(snapshot, self.fresh())
        self.assertNotIn('digest mismatch', str(error.exception))

    def source_ability(self, snapshot, name):
        entity = next(e for e in snapshot['state']['entities'].values() if e['card_id'] == name)
        return next(a for a in entity['abilities'] if a['kind'] == 'combo_repeat')

    def check_once(self, game, record=None):
        record = game.state.play_history[-1] if record is None else record
        self.assertTrue(record.completed)
        self.assertEqual((record.cost, record.mana_before - record.mana_after), (1, 1))
        self.assertEqual(sum(e.kind == 'card_played' and dict(e.data).get('play_id') == record.id for e in game.events), 1)

    def test_same_named_self_sources_require_the_new_physical_paid_carrier(self):
        game = self.game(hand=('self.combo', 'self.combo'), board=('self.combo', 'self.source'))
        first = self.play(game, 'self.combo')
        first_ids = self.plan(game).contributors
        self.assertEqual((self.plan(game).repetitions, len(first_ids)), (3, 1))
        self.assertEqual(self.receipt(game).recipient, ComboRecipient(first, 'self.combo', CardType.MINION))
        second = self.play(game, 'self.combo')
        self.assertNotEqual(first, second)
        self.assertEqual((self.plan(game).repetitions, len(self.plan(game).contributors)), (3, 1))
        self.assertNotEqual(first_ids, self.plan(game).contributors)
        self.assertEqual(self.armor(game), 12)
        self.check_once(game)
        self.portable(game)

    def test_recipient_tribes_use_or_and_all_printed_metadata(self):
        for name, expected in (('dragon.combo', 2), ('beast.combo', 1), ('plain.combo', 1),
                               ('multi.combo', 2), ('all.combo', 2)):
            with self.subTest(recipient=name):
                game = self.game(hand=(name,), board=('tribal.2',))
                self.play(game, name)
                self.assertEqual(self.plan(game).repetitions, expected)
                self.assertEqual(self.armor(game), expected * 2)
                self.portable(game)

    def test_recipient_filter_requires_needed_metadata_and_rolls_back_atomically(self):
        for name in ('unknown.metadata.combo', 'unknown.tribes.combo'):
            game = self.game(hand=(name,), board=('tribal.2',))
            before = game.snapshot()
            with self.assertRaises(ResolutionError):
                self.play(game, name)
            self.assertEqual(game.snapshot(), before)

    def test_empty_recipient_restriction_does_not_require_metadata(self):
        game = self.game(hand=('unknown.metadata.combo',), board=('friendly.2',))
        self.play(game, 'unknown.metadata.combo')
        self.assertEqual(self.armor(game), 4)
        self.portable(game)

    def test_weapon_and_hero_use_paid_installed_operand_and_explicit_kinds(self):
        for name, kind in (('weapon.combo', CardType.WEAPON), ('hero.combo', CardType.HERO)):
            game = self.game(hand=(name,), board=('all.kinds', 'all.kinds.tribal', 'self.source'))
            entity = self.play(game, name)
            self.assertEqual(self.receipt(game).recipient, ComboRecipient(entity, name, kind))
            self.assertEqual((self.plan(game).repetitions, len(self.plan(game).contributors)), (2, 1))
            self.assertEqual(self.armor(game), 4)
            self.check_once(game)
            self.portable(game)

    def test_distinct_submission_and_activation_faces_are_a_pure_contract_only(self):
        first = ComboRecipient(31, 'dragon.combo', CardType.MINION)
        later = ComboRecipient(31, 'beast.combo', CardType.MINION)
        spec = specification(tribes=('dragon',))
        self.assertTrue(combo_repeat_recipient_matches(spec, recipient=first,
            recipient_definition=self.registry.card(first.card_id)))
        self.assertFalse(combo_repeat_recipient_matches(spec, recipient=later,
            recipient_definition=self.registry.card(later.card_id)))
        with self.assertRaises(ValueError):
            combo_repeat_recipient_matches(spec, recipient=later,
                recipient_definition=self.registry.card(first.card_id))

    def test_repeat_source_another_uses_actual_carrier_and_distinct_same_card_entities(self):
        for count, expected in ((1, 1), (2, 2)):
            game = self.game(hand=('beast.combo',), board=('conditional.dragon',) * count)
            self.play(game, 'beast.combo')
            self.assertEqual(self.plan(game).repetitions, expected)
            self.assertEqual(len(self.plan(game).contributors), count if count == 2 else 0)
            self.portable(game)
        game = self.game(board=('conditional.dragon',))
        self.play(game)
        self.assertEqual(self.plan(game).repetitions, 2)
        self.portable(game)

    def test_presence_profiles_keep_controlled_and_active_live_distinct(self):
        for source, expected in (('conditional.any', 2), ('conditional.active', 1)):
            game = self.game(board=(source, 'dormant.beast'))
            self.play(game)
            self.assertEqual(self.plan(game).repetitions, expected)
            self.portable(game)

    def test_source_query_is_complete_before_recipient_kind_scope_or_tribe_false(self):
        for name, source in (('weapon.combo', 'conditional'), ('beast.combo', 'conditional')):
            game = self.game(hand=(name,), board=(source, 'beast', 'unknown.metadata'))
            before = game.snapshot()
            with self.assertRaises(ResolutionError):
                self.play(game, name)
            self.assertEqual(game.snapshot(), before)

    def test_source_exclusion_and_empty_witness_filter_do_not_need_unused_metadata(self):
        game = self.game(hand=('unknown.metadata.combo',), board=('any.witness',))
        self.play(game, 'unknown.metadata.combo')
        self.assertEqual(self.plan(game).repetitions, 2)
        self.portable(game)

    def test_complete_max_keeps_lower_equal_higher_and_both_finite_phase_sources(self):
        game = self.game(hand=('policy.both', 'dragon.combo'), board=('tribal.2', 'tribal.3', 'tribal.5'))
        self.play(game, 'policy.both')
        self.play(game)
        self.assertEqual((self.plan(game).repetitions, len(self.plan(game).contributors),
            len(self.plan(game).consumable_ids)), (5, 5, 2))
        self.assertEqual([m.uses_remaining for m in game.state.players[1].combo_modifiers], [1, 1])
        self.assertEqual(sum(e.kind == 'combo_modifier_used' for e in game.events), 2)
        self.assertEqual(self.armor(game), 10)
        before_query = game.snapshot()
        accepted_again = capture_plan_from_state(game.state, self.registry, game.state.play_history[-1],
            self.receipt(game).recipient, self.policies(game)[1].modifiers)
        self.assertEqual(accepted_again, self.plan(game))
        self.assertEqual(game.snapshot(), before_query)
        self.check_once(game)
        self.portable(game)

    def test_filtered_policy_does_not_consume_on_a_false_recipient(self):
        game = self.game(hand=('policy.both', 'beast.combo', 'dragon.ask', 'dragon.combo'))
        self.play(game, 'policy.both')
        self.play(game, 'beast.combo')
        self.assertEqual([m.uses_remaining for m in game.state.players[1].combo_modifiers], [2, 2])
        self.assertEqual([r.modifiers for r in self.policies(game)], [(), ()])
        self.play(game, 'dragon.ask')
        self.finish_choices(game)
        self.assertEqual([m.uses_remaining for m in game.state.players[1].combo_modifiers], [1, 1])
        self.play(game)
        self.assertFalse(game.state.players[1].combo_modifiers)
        self.assertEqual(sum(e.kind == 'combo_modifier_used' for e in game.events), 4)
        self.portable(game)

    def test_disabled_first_combo_consumes_only_submission_and_keeps_empty_late_receipt(self):
        game = self.game(primed=False, board=('conditional', 'unknown.metadata'), power='policy.power')
        game.apply(UseHeroPower(1, game.state.players[1].hero_power_id))
        self.play(game)
        receipt = self.receipt(game)
        self.assertEqual(receipt.status, 'disabled')
        self.assertEqual((len(receipt.payloads), receipt.plan), (1, None))
        self.assertEqual([(r.phase, r.eligible, len(r.modifiers), r.consumption_applied)
            for r in self.policies(game)], [('play', True, 1, True), ('activation', False, 0, True)])
        self.assertEqual([m.trigger for m in game.state.players[1].combo_modifiers], ['activation'])
        self.assertEqual(game.state.combo_history, [])
        self.check_once(game)
        self.portable(game)

    def test_noncombo_physical_root_keeps_explicit_empty_two_phase_obligation(self):
        game = self.game(hand=('no.combo',), board=('conditional', 'unknown.metadata'))
        self.play(game, 'no.combo')
        self.assertEqual(self.receipt(game).status, 'no_payload')
        self.assertEqual([(r.phase, r.eligible, r.modifiers) for r in self.policies(game)],
            [('play', False, ()), ('activation', False, ())])
        self.portable(game)
        self.choose(game)
        self.check_once(game)
        self.portable(game)

    def test_empty_effect_body_is_activated_and_consumes_both_matching_phases(self):
        game = self.game(hand=('policy.both', 'empty.combo'))
        self.play(game, 'policy.both')
        self.play(game, 'empty.combo')
        self.assertEqual(self.receipt(game).status, 'activated')
        self.assertEqual(self.plan(game).repetitions, 3)
        self.assertEqual(len(game.state.combo_history), 3)
        self.assertTrue(all(r.completed for r in game.state.combo_history))
        self.assertEqual(self.armor(game), 0)
        self.check_once(game)
        self.portable(game)

    def test_generic_transform_after_acceptance_keeps_original_recipient_and_plan(self):
        game = self.game(hand=('generic.transform.combo', 'beast.combo'), board=('tribal.2',))
        entity = self.play(game, 'generic.transform.combo')
        original = self.receipt(game)
        self.assertEqual(game.state.combo_batches, [])
        self.assertEqual(original.recipient.card_id, 'generic.transform.combo')
        self.portable(game)
        self.choose(game)
        self.assertEqual(game.state.entities[entity].card_id, 'beast')
        self.assertEqual(self.armor(game), 4)
        self.play(game, 'beast.combo')
        self.assertEqual(self.plan(game).repetitions, 1)
        self.assertEqual(original.recipient.card_id, 'generic.transform.combo')
        self.assertEqual(self.armor(game), 6)
        self.portable(game)

    def test_normal_entry_transform_and_control_change_follow_actual_acceptance(self):
        for watcher in ('entry.morph', 'entry.steal'):
            game = self.game(hand=('dragon.ask',), board=('tribal.2', watcher))
            entity = self.play(game, 'dragon.ask')
            self.assertEqual(self.receipt(game).recipient.card_id, 'dragon.ask')
            self.assertEqual(self.plan(game).repetitions, 2)
            self.finish_choices(game)
            self.assertEqual((self.armor(game), self.armor(game, 2)), (4, 0))
            if watcher == 'entry.morph':
                self.assertEqual(game.state.entities[entity].card_id, 'beast')
            else:
                self.assertEqual(game.state.entities[entity].controller, 2)
            self.portable(game)

    def test_entry_listener_removing_witness_keeps_accepted_but_next_root_recaptures(self):
        game = self.game(hand=('dragon.ask', 'dragon.combo'), board=('conditional', 'beast', 'entry.remove'))
        self.play(game, 'dragon.ask')
        self.assertEqual(self.plan(game).repetitions, 2)
        self.finish_choices(game)
        self.play(game)
        self.assertEqual(self.plan(game).repetitions, 1)
        self.assertEqual(self.armor(game), 6)
        self.portable(game)

    def test_colossal_limb_witness_precedes_the_late_actual_window(self):
        game = self.game(hand=('giant.combo',), board=('conditional',))
        entity = self.play(game, 'giant.combo')
        self.assertEqual(self.plan(game).repetitions, 2)
        record = game.state.colossal_history[-1]
        self.assertEqual((record.play_id, self.receipt(game).colossal_record_id),
            (game.state.play_history[-1].id, record.id))
        self.assertEqual(self.receipt(game).recipient.carrier_id, entity)
        self.assertEqual(self.armor(game), 4)
        self.portable(game)

    def test_colossal_limb_listener_removes_witness_before_late_acceptance(self):
        game = self.game(hand=('giant.combo',), board=('conditional', 'limb.remove'))
        self.play(game, 'giant.combo')
        self.assertEqual(self.plan(game).repetitions, 1)
        self.assertEqual(self.armor(game), 2)
        self.portable(game)

    def test_colossal_silence_has_no_payload_and_preserves_activation_policy(self):
        game = self.game(hand=('policy.both', 'giant.combo'), board=('limb.silence',))
        self.play(game, 'policy.both')
        self.play(game, 'giant.combo')
        self.assertEqual(self.receipt(game).status, 'no_payload')
        self.assertEqual((self.receipt(game).payloads, self.receipt(game).plan), ((), None))
        self.assertEqual([m.uses_remaining for m in game.state.players[1].combo_modifiers], [1, 2])
        self.assertFalse(game.state.combo_history)
        self.check_once(game)
        self.portable(game)

    def test_colossal_lost_live_body_cancels_late_without_reverting_submission(self):
        for watcher in ('giant.kill', 'giant.bounce', 'giant.steal', 'giant.morph'):
            game = self.game(hand=('policy.both', 'giant.combo'), board=(watcher,))
            self.play(game, 'policy.both')
            self.play(game, 'giant.combo')
            self.assertEqual(self.receipt(game).status, 'colossal_canceled')
            self.assertEqual([m.uses_remaining for m in game.state.players[1].combo_modifiers], [1, 2])
            self.assertFalse(game.state.combo_history)
            self.check_once(game)
            self.portable(game)

    def test_counter_and_full_board_use_explicit_late_cancellation_receipts(self):
        for watcher, status in (('counter', 'countered'), ('fill', 'board_full')):
            game = self.game(hand=('policy.both', 'dragon.combo'), board=(watcher, 'conditional', 'unknown.metadata'))
            self.play(game, 'policy.both')
            self.play(game)
            self.assertEqual(self.receipt(game).status, status)
            self.assertEqual([m.uses_remaining for m in game.state.players[1].combo_modifiers], [1, 2])
            self.assertEqual(self.policies(game)[1].modifiers, ())
            self.assertFalse(game.state.combo_history)
            self.check_once(game)
            self.portable(game)

    def test_magnetic_paid_root_does_not_activate_inherited_host_combo(self):
        game = self.game(hand=('magnet.combo',), board=('mech',))
        entity = self.play(game, 'magnet.combo', position=0)
        self.assertEqual(self.receipt(game).status, 'magnetized')
        self.assertEqual(self.receipt(game).recipient.carrier_id, entity)
        self.assertEqual(game.state.combo_history, [])
        self.check_once(game)
        self.portable(game)

    def test_terminal_before_late_window_keeps_only_submission_consumption(self):
        game = self.game(hand=('policy.both', 'dragon.combo'), board=('commit.lethal',))
        self.play(game, 'policy.both')
        self.play(game)
        root = game.state.play_history[-1]
        self.assertTrue(root.interrupted)
        self.assertIsNone(root.combo_acceptance)
        self.assertEqual([(r.phase, len(r.modifiers)) for r in self.policies(game)], [('play', 1)])
        self.assertEqual([m.uses_remaining for m in game.state.players[1].combo_modifiers], [1, 2])
        self.assertFalse(game.state.combo_history)
        self.portable(game)

    def test_terminal_after_late_acceptance_keeps_uses_without_inventing_children(self):
        game = self.game(hand=('policy.both', 'dragon.combo'), board=('entry.lethal',))
        self.play(game, 'policy.both')
        self.play(game)
        self.assertEqual(self.receipt(game).status, 'activated')
        self.assertEqual(self.plan(game).repetitions, 3)
        self.assertEqual([m.uses_remaining for m in game.state.players[1].combo_modifiers], [1, 1])
        self.assertFalse(game.state.combo_history)
        self.portable(game)

    def test_terminal_during_first_child_interrupts_the_accepted_complete_root(self):
        game = self.game(hand=('policy.both', 'fatal.combo'))
        self.play(game, 'policy.both')
        self.play(game, 'fatal.combo')
        self.assertEqual(self.plan(game).repetitions, 3)
        self.assertEqual(len(game.state.combo_history), 1)
        self.assertTrue(game.state.combo_history[0].interrupted)
        self.assertTrue(game.state.combo_batches[0].interrupted)
        self.assertTrue(game.state.play_history[-1].interrupted)
        self.portable(game)

    def test_retained_outcomes_reuse_two_window_plan_after_recipient_and_witness_change(self):
        game = self.game(hand=('policy.play.one', 'retained.combo'), board=('conditional', 'beast', 'retainer'))
        self.play(game, 'policy.play.one')
        self.play(game, 'retained.combo')
        original = self.receipt(game)
        ids = [r.id for r in self.policies(game)]
        for _ in range(4):
            self.assertIsNotNone(game.state.pending_choice)
            self.assertEqual(self.receipt(game), original)
            self.assertEqual([r.id for r in self.policies(game)], ids)
            self.portable(game)
            self.choose(game)
        self.assertEqual([(r.iteration, r.repeat_index) for r in game.state.combo_history],
            [(1, 1), (1, 2), (2, 1), (2, 2)])
        self.assertEqual(self.armor(game), 4)
        self.assertEqual(sum(e.kind == 'combo_modifier_used' for e in game.events), 1)
        self.check_once(game)
        self.portable(game)

    def test_ordinary_retry_replaces_attempt_receipts_instead_of_depleting_twice(self):
        game = self.game(hand=('policy.play.one', 'rewind.combo'), board=('tribal.2',))
        self.play(game, 'policy.play.one')
        self.play(game, 'rewind.combo')
        original_ids = [r.id for r in self.policies(game)]
        self.portable(game)
        self.choose(game, 'retry')
        self.assertEqual([r.id for r in self.policies(game)], original_ids)
        self.assertEqual(len(game.state.combo_history), 2)
        self.assertEqual(len(game.state.combo_batches), 1)
        self.assertFalse(game.state.players[1].combo_modifiers)
        self.assertEqual(sum(e.kind == 'combo_modifier_used' for e in game.events), 2)
        self.assertEqual(self.armor(game), 4)
        self.portable(game)
        self.assertIsNone(game.state.pending_choice)
        self.assertEqual(game.state.status, 'playing')
        record = game.state.play_history[-1]
        self.assertTrue(record.completed)
        self.assertEqual((record.cost, record.mana_before - record.mana_after), (1, 1))
        self.assertEqual(game.state.players[1].mana, 9)
        self.assertEqual([r.card_id for r in game.state.play_history],
            ['prime', 'policy.play.one', 'rewind.combo'])
        self.assertEqual([r.id for r in game.state.play_history if r.source_id == record.source_id],
            [record.id])
        self.assertEqual(sum(e.kind == 'card_played' and dict(e.data).get('play_id') == record.id
            for e in game.events), 2)
        self.assertEqual(sum(e.kind == 'timeline_rewound' for e in game.events), 1)
        self.portable(game)

    def test_random_body_failure_restores_payment_both_receipts_and_rng(self):
        game = self.game(hand=('policy.both', 'bad.combo'))
        self.play(game, 'policy.both')
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, 'bad.combo')
        self.assertEqual(game.snapshot(), before)
        self.portable(game)

    def test_failure_after_choice_restores_the_accepted_wait_and_single_consumption(self):
        game = self.game(hand=('policy.both', 'bad.choice.combo'))
        self.play(game, 'policy.both')
        self.play(game, 'bad.choice.combo')
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(game)
        self.assertEqual(game.snapshot(), before)
        self.assertEqual([m.uses_remaining for m in game.state.players[1].combo_modifiers], [1, 1])
        self.portable(game)

    def test_excess_plan_is_rejected_before_any_persistent_activation_consumption(self):
        game = self.game(hand=('policy.both', 'dragon.combo'), board=('huge',))
        self.play(game, 'policy.both')
        before = game.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            self.play(game)
        self.assertEqual(game.snapshot(), before)
        self.assertEqual(game.state.status, 'playing')

    def test_spell_combo_numerical_branch_keeps_spell_ownership_and_no_combo_receipts(self):
        def extension(registry):
            registry.register_behavior('spell.combo.branch', lambda c: [GainArmor(c.player_id, 3 if c.play.combo else 1)])
            registry.register_card(CardDefinition('spell.combo.branch', 'Spell numerical Combo', CardType.SPELL,
                on_play='spell.combo.branch', keywords=(Keyword.COMBO,), metadata=metadata()))
        self.extend(extension)
        game = self.game(hand=('spell.combo.branch',))
        self.play(game, 'spell.combo.branch')
        record = game.state.play_history[-1]
        self.assertEqual(record.kind, CardType.SPELL)
        self.assertIsNone(record.combo_submission_receipt_id)
        self.assertIsNone(record.combo_acceptance)
        self.assertEqual(game.state.combo_policy_receipts, [])
        self.assertEqual(self.armor(game), 3)
        self.portable(game)

    def test_all_false_unit_plan_keeps_full_original_proof_until_root_completion(self):
        game = self.game(hand=('generic.beast.ask',), board=('tribal.2', 'self.source'))
        self.play(game, 'generic.beast.ask')
        self.assertEqual(self.plan(game).contributors, ())
        self.assertEqual(self.plan(game).repetitions, 1)
        self.assertEqual(game.state.combo_batches, [])
        proofs = self.named(game.snapshot()['resolution_frame'], 'FinishComboAcceptance')
        self.assertEqual(len(proofs), 2)
        self.portable(game)
        self.choose(game)
        self.assertEqual(len(game.state.combo_history), 1)
        self.portable(game)

    def test_active_false_source_specs_and_physical_carrier_identity_cannot_be_rebound(self):
        game = self.game(hand=('generic.beast.ask',), board=('tribal.2', 'self.source', 'plain'))
        self.play(game, 'generic.beast.ask')
        for mode in ('count', 'tribes', 'carrier'):
            snapshot = game.snapshot()
            ability = self.source_ability(snapshot, 'tribal.2')
            if mode == 'count':
                ability['combo_repeat']['repetitions'] = 3
            elif mode == 'tribes':
                ability['combo_repeat']['match']['recipient_metadata']['tribes_any'] = ['beast']
            else:
                source = next(e for e in snapshot['state']['entities'].values() if e['card_id'] == 'tribal.2')
                target = next(e for e in snapshot['state']['entities'].values() if e['card_id'] == 'plain')
                source['abilities'].remove(ability)
                target['abilities'].append(ability)
            self.reject(snapshot)

    def test_false_player_policies_keep_static_identity_owner_and_unconsumed_uses(self):
        game = self.game(hand=('policy.false', 'generic.beast.ask'))
        self.play(game, 'policy.false')
        self.play(game, 'generic.beast.ask')
        self.assertEqual(self.plan(game).contributors, ())
        self.assertEqual(game.state.players[1].combo_modifiers[0].uses_remaining, 2)
        for mode in ('tribes', 'owner', 'uses'):
            snapshot = game.snapshot()
            policies = snapshot['state']['players']['1']['combo_modifiers']
            if mode == 'tribes':
                policies[0]['spec']['match']['recipient_metadata']['tribes_any'] = ['beast']
            elif mode == 'owner':
                snapshot['state']['players']['2']['combo_modifiers'].append(policies.pop())
            else:
                policies[0]['uses_remaining'] = 1
            self.reject(snapshot)

    def test_active_operand_and_policy_phase_cannot_be_forged(self):
        game = self.game(hand=('generic.dragon.ask',), board=('tribal.2',))
        self.play(game, 'generic.dragon.ask')
        for mode in ('carrier', 'face', 'kind', 'phase', 'eligible', 'status'):
            snapshot = game.snapshot()
            root = snapshot['state']['play_history'][-1]
            receipt = root['combo_acceptance']
            if mode in ('carrier', 'face', 'kind'):
                receipt['recipient'][{'carrier': 'carrier_id', 'face': 'card_id', 'kind': 'kind'}[mode]] = {
                    'carrier': game.state.players[1].board[0], 'face': 'beast.combo', 'kind': 'weapon'}[mode]
            elif mode == 'phase':
                snapshot['state']['combo_policy_receipts'][-1]['phase'] = 'play'
            elif mode == 'eligible':
                snapshot['state']['combo_policy_receipts'][-1]['eligible'] = False
            else:
                receipt['status'] = 'disabled'
            self.reject(snapshot)

    def test_waiting_live_receipts_cannot_remain_unconsumed(self):
        game = self.game(hand=('policy.both', 'dragon.ask'))
        self.play(game, 'policy.both')
        self.play(game, 'dragon.ask')
        self.assertTrue(all(r.consumption_applied for r in game.state.combo_policy_receipts))
        snapshot = game.snapshot()
        snapshot['state']['combo_policy_receipts'][-1]['consumption_applied'] = False
        self.reject(snapshot)

    def test_delete_entire_unit_schedule_and_both_proofs_still_rejects_active_paid_root(self):
        game = self.game(hand=('generic.beast.ask',), board=('tribal.2',))
        self.play(game, 'generic.beast.ask')
        for names in ({'FinishComboAcceptance'}, {'BeginComboBatch'},
                      {'BeginComboBatch', 'FinishComboAcceptance', 'FinishPlay'}):
            snapshot = game.snapshot()
            queue = snapshot['resolution_frame']['fields']['continuation']['tuple']
            queue[:] = [work for work in queue if not any(work.get('type', '').endswith('.' + name) for name in names)]
            self.reject(snapshot)

    def test_completed_plan_rejects_other_global_attachment_families(self):
        for name in ('other.enchantment', 'other.spell.modifier', 'other.bc.modifier', 'other.player.effect'):
            game = self.game(hand=(name, 'dragon.combo'), board=('tribal.2', 'plain'))
            self.play(game, name)
            self.play(game)
            if name == 'other.enchantment':
                other = game.state.entities[find(game.state, 'plain')].enchantments[0].id
            elif name == 'other.spell.modifier':
                other = game.state.players[1].spell_modifiers[0].id
            elif name == 'other.bc.modifier':
                other = game.state.players[1].battlecry_modifiers[0].id
            else:
                other = game.state.players[1].player_effects[0].id
            snapshot = game.snapshot()
            snapshot['state']['play_history'][-1]['combo_acceptance']['plan']['contributors'] = [other]
            snapshot['state']['combo_batches'][-1]['plan']['contributors'] = [other]
            self.reject(snapshot)
            self.portable(game)

    def test_completed_plan_does_not_requery_later_witness_or_current_face(self):
        game = self.game(hand=('retained.combo',), board=('conditional', 'beast', 'retainer'))
        self.play(game, 'retained.combo')
        self.finish_choices(game)
        self.assertEqual(game.state.entities[game.state.play_history[-1].source_id].card_id, 'plain')
        self.assertEqual(self.plan(game).repetitions, 2)
        self.portable(game)

    def test_match_private_codec_is_exact_and_preserves_both_operands(self):
        match = ComboRepeatMatchSpec(ComboRecipientMetadataFilter(tribes_any=('dragon',)), witness())
        value = combo_match_to_dict(match)
        self.assertEqual(combo_match_from_dict(value), match)
        for corrupted in ({'recipient_metadata': value['recipient_metadata']},
                          dict(value, unexpected=True),
                          dict(value, source_eligibility=dict(value['source_eligibility'], exclude_carrier=1))):
            with self.assertRaises(ValueError):
                combo_match_from_dict(corrupted)

    def test_declarations_and_player_modifiers_reject_invalid_scope_and_physical_conditions(self):
        for kwargs in ({'scope': 'opponent'}, {'scope': 'self', 'kinds': (CardType.WEAPON,)},
                       {'scope': 'self', 'kinds': (CardType.MINION, CardType.HERO)},
                       {'kinds': (CardType.SPELL,)}, {'count': True}):
            with self.assertRaises(ValueError):
                specification(**kwargs)
        for trigger in ('play', 'activation'):
            for spec in (specification(scope='self'), specification(eligibility=witness())):
                with self.assertRaises(ValueError):
                    AddComboRepeatModifier(1, spec, trigger=trigger)
        with self.assertRaises(ValueError):
            self.registry.register_card(CardDefinition('invalid.profile', 'Invalid', CardType.MINION,
                health=5, combo_repeats=(specification(eligibility=witness(profile='missing')),)))

    def test_player_dtos_are_detached_and_hide_all_private_acceptance_fields(self):
        game = self.game(hand=('policy.both', 'dragon.ask'))
        self.play(game, 'policy.both')
        original = game.snapshot()
        for player in (1, 2):
            view = game.for_player(player).observe()['observation']
            owner = next(p for p in view['players'] if p['id'] == 1)
            for modifier in owner['combo_modifiers']:
                self.assertEqual(set(modifier), {'repetitions', 'kinds', 'uses_remaining', 'expires_turn', 'trigger', 'scope', 'match'})
                self.assertEqual(modifier['scope'], 'friendly')
                self.assertEqual(set(modifier['match']), {'recipient_metadata'})
                modifier['match']['recipient_metadata']['tribes_any'].append('beast')
        self.assertEqual(game.snapshot(), original)
        self.play(game, 'dragon.ask')
        self.private_absent(game)
        self.finish_choices(game)
        self.portable(game)

    def test_submission_wait_has_one_finish_after_its_pending_entry_and_proof(self):
        game = self.game(hand=('dragon.ask',), board=('commit.wait', 'tribal.2'))
        entity = self.play(game, 'dragon.ask')
        root = game.state.play_history[-1]
        self.assertEqual(game.state.entities[entity].zone, Zone.PLAY)
        self.assertIsNone(root.combo_acceptance)
        self.assertEqual([(r.phase, r.eligible) for r in self.policies(game)], [('play', True)])
        frame = game.snapshot()['resolution_frame']
        self.assertEqual(len(self.named(frame, 'FinishPlay')), 1)
        self.assertEqual(len(self.named(frame, 'FinishComboAcceptance')), 1)
        self.portable(game)
        self.choose(game)
        self.finish_choices(game)
        self.assertEqual(self.armor(game), 4)
        self.check_once(game)
        self.portable(game)

    def test_commit_reaction_replaces_future_policy_without_rematching_accepted_play_policy(self):
        def extension(registry):
            registry.register_behavior('commit.policy', lambda c: [AddComboRepeatModifier(1,
                specification(2, tribes=('dragon',)), c.source_id, 2, trigger='play')])
            registry.register_card(CardDefinition('commit.policy', 'Two-use commitment policy', CardType.SPELL,
                on_play='commit.policy', metadata=metadata()))
            def change(context):
                if context.play.kind != CardType.MINION:
                    return []
                original = next(m for m in context.state.players[1].combo_modifiers if m.trigger == 'play')
                return [RemoveComboRepeatModifier(1, original.id),
                    AddComboRepeatModifier(1, specification(5, tribes=('dragon',)), context.source_id, 1, trigger='play'),
                    AddComboRepeatModifier(1, specification(3, tribes=('dragon',)), context.source_id, 1, trigger='activation')]
            registry.register_behavior('commit.replace', change)
            registry.register_card(CardDefinition('commit.replace', 'Commit policy replacement', CardType.MINION,
                health=5, metadata=metadata(), triggers=(TriggerSpec('card_committed', 'commit.replace'),)))
        self.extend(extension)
        game = self.game(hand=('commit.policy', 'dragon.combo'), board=('commit.replace',))
        self.play(game, 'commit.policy')
        self.play(game)
        self.assertEqual(self.plan(game).repetitions, 3)
        self.assertEqual([r.modifiers[0].spec.repetitions for r in self.policies(game)], [2, 3])
        self.assertEqual([(m.trigger, m.spec.repetitions, m.uses_remaining)
            for m in game.state.players[1].combo_modifiers], [('play', 5, 1)])
        self.assertEqual(self.armor(game), 6)
        self.check_once(game)
        self.portable(game)

    def test_choice_paid_child_captures_before_parent_late_phase_in_actual_order(self):
        def extension(registry):
            def nested(context):
                if context.play.card_id != 'dragon.combo':
                    return []
                child = next(i for i in context.state.players[1].hand
                    if context.state.entities[i].card_id == 'dragon.ask')
                return [ask(context, (PlayFromHand(PlayCard(1, child)),))]
            registry.register_behavior('nested.counter', nested)
            registry.register_card(CardDefinition('nested.counter', 'Counter choice nesting', CardType.MINION,
                health=5, metadata=metadata(), triggers=(TriggerSpec('minion_counter_check', 'nested.counter'),)))
        self.extend(extension)
        game = self.game(hand=('policy.both', 'dragon.combo', 'dragon.ask'), board=('nested.counter',))
        self.play(game, 'policy.both')
        self.play(game)
        parent = game.state.play_history[-1]
        self.portable(game)
        self.choose(game)
        child = game.state.play_history[-1]
        self.assertGreater(child.action, parent.action)
        self.assertNotEqual(child.id, parent.id)
        self.assertEqual([(r.play_id, r.phase) for r in game.state.combo_policy_receipts],
            [(parent.id, 'play'), (child.id, 'play'), (child.id, 'activation')])
        self.finish_choices(game)
        self.assertEqual([(r.play_id, r.phase) for r in game.state.combo_policy_receipts],
            [(parent.id, 'play'), (child.id, 'play'), (child.id, 'activation'), (parent.id, 'activation')])
        self.assertEqual([r.modifiers[0].uses_remaining for r in game.state.combo_policy_receipts], [2, 1, 2, 1])
        self.assertFalse(game.state.players[1].combo_modifiers)
        self.assertEqual(self.armor(game), 12)
        self.assertTrue(all(r.completed for r in game.state.play_history))
        self.assertEqual(sum(e.kind == 'combo_modifier_used' for e in game.events), 4)
        self.check_once(game, next(r for r in game.state.play_history if r.id == parent.id))
        self.check_once(game, game.state.play_history[-1])
        self.portable(game)

    def test_nested_history_rejects_reordering_and_unreceipted_additional_consumption(self):
        def extension(registry):
            registry.register_behavior('nested.policy', lambda c: [
                AddComboRepeatModifier(1, specification(2, tribes=('dragon',)), c.source_id, 3, trigger='play'),
                AddComboRepeatModifier(1, specification(3, tribes=('dragon',)), c.source_id, 3, trigger='activation')])
            registry.register_card(CardDefinition('nested.policy', 'Three-use nested policies', CardType.SPELL,
                on_play='nested.policy', metadata=metadata()))
            def child_body(context):
                choices = [ChoiceOption('ok', 'Resolve', (GainArmor(context.player_id, 2),))]
                if context.combo.repeat_index == 1:
                    policy = next(m for m in context.state.players[1].combo_modifiers if m.trigger == 'activation')
                    choices.append(ChoiceOption('remove', 'Remove future activation policy',
                        (RemoveComboRepeatModifier(1, policy.id), GainArmor(1, 2))))
                return [RequestChoice(1, tuple(choices), source_id=context.source_id)]
            registry.register_behavior('nested.child', child_body)
            registry.register_card(CardDefinition('nested.child', 'Nested child', CardType.MINION,
                cost=1, health=5, metadata=metadata(('dragon',)), keywords=(Keyword.COMBO,), combo='nested.child'))
            def nested(context):
                if context.play.card_id != 'dragon.combo':
                    return []
                child = next(i for i in context.state.players[1].hand if context.state.entities[i].card_id == 'nested.child')
                return [ask(context, (PlayFromHand(PlayCard(1, child)),))]
            registry.register_behavior('nested.counter', nested)
            registry.register_card(CardDefinition('nested.counter', 'Nested', CardType.MINION, health=5,
                metadata=metadata(), triggers=(TriggerSpec('minion_counter_check', 'nested.counter'),)))
        self.extend(extension)
        game = self.game(hand=('nested.policy', 'dragon.combo', 'nested.child'), board=('nested.counter',))
        self.play(game, 'nested.policy')
        self.play(game)
        self.choose(game)
        self.portable(game)
        snapshot = game.snapshot()
        policies = snapshot['state']['combo_policy_receipts']
        policies[0], policies[1] = policies[1], policies[0]
        for index, receipt in enumerate(policies, 1):
            receipt['id'] = index
        self.reject(snapshot)
        snapshot = game.snapshot()
        policy = next(m for m in snapshot['state']['players']['1']['combo_modifiers'] if m['trigger'] == 'activation')
        self.assertEqual(policy['uses_remaining'], 2)
        policy['uses_remaining'] = 1
        self.reject(snapshot)
        # A declared removal is legal and differs from inventing an additional
        # finite use. Already accepted child repeats keep their plan; the later
        # parent window correctly sees no remaining activation policy.
        self.choose(game, 'remove')
        self.finish_choices(game)
        self.assertEqual(sum(e.kind == 'combo_modifier_removed' for e in game.events), 1)
        self.assertEqual([m.trigger for m in game.state.players[1].combo_modifiers], ['play'])
        self.assertEqual(game.state.players[1].combo_modifiers[0].uses_remaining, 1)
        self.assertTrue(all(r.completed for r in game.state.play_history))
        self.assertEqual(self.armor(game), 10)
        self.portable(game)

    def test_mixed_battlecry_and_combo_originals_share_durable_receipts_before_generic_wait(self):
        game = self.game(hand=('mixed.policies', 'mixed.combo'), board=('bc.used.wait',))
        self.play(game, 'mixed.policies')
        self.play(game, 'mixed.combo')
        root = game.state.play_history[-1]
        self.assertEqual((root.battlecry_acceptance.plan.repetitions, root.combo_acceptance.plan.repetitions), (2, 3))
        self.assertEqual((game.state.battlecry_batches, game.state.combo_batches), ([], []))
        proofs = self.named(game.snapshot()['resolution_frame'], 'FinishBattlecryAcceptance')
        self.assertTrue(proofs)
        self.portable(game)
        self.finish_choices(game)
        self.assertEqual((self.armor(game), len(game.state.battlecry_history), len(game.state.combo_history)), (15, 2, 3))
        self.check_once(game)
        self.portable(game)

    def test_consumption_listener_wait_restores_both_completed_consumptions_once(self):
        game = self.game(hand=('policy.both', 'dragon.combo'), board=('used.wait',))
        self.play(game, 'policy.both')
        self.play(game)
        self.assertFalse(game.state.combo_history)
        self.assertEqual([m.uses_remaining for m in game.state.players[1].combo_modifiers], [1, 2])
        self.assertEqual([r.phase for r in self.policies(game)], ['play'])
        self.assertTrue(all(r.consumption_applied for r in game.state.combo_policy_receipts))
        self.finish_choices(game)
        self.assertEqual(self.armor(game), 6)
        self.assertEqual([m.uses_remaining for m in game.state.players[1].combo_modifiers], [1, 1])
        self.assertEqual(sum(e.kind == 'combo_modifier_used' for e in game.events), 2)
        self.portable(game)

    def test_composite_paid_ship_matches_carrier_printed_tribe_not_combo_declaration_faces(self):
        def extension(registry):
            registry.register_behavior('ship.policy', lambda c: [AddComboRepeatModifier(1,
                specification(3, tribes=('beast',)), c.source_id, 1, trigger='play')])
            registry.register_card(CardDefinition('ship.policy', 'Ship policy', CardType.SPELL, on_play='ship.policy', metadata=metadata()))
        self.extend(extension)
        game = self.game(hand=('scrap', 'bounce', 'ship.policy'), board=('part.dragon', 'part.dragon'))
        self.play(game, 'scrap')
        ship = construction(game.state, 1)
        game.apply(LaunchStarship(1, ship.id))
        self.play(game, 'bounce', ship.id)
        self.play(game, 'ship.policy')
        game.apply(PlayCard(1, ship.id))
        accepted = self.receipt(game)
        self.assertEqual(accepted.recipient.card_id, 'ship.body')
        self.assertEqual({p.card_id for p in accepted.payloads}, {'part.dragon'})
        self.assertEqual((len(accepted.payloads), accepted.plan.repetitions), (2, 3))
        self.assertEqual([r.repeat_index for r in game.state.combo_history], [1, 2, 3, 1, 2, 3])
        self.assertEqual(self.armor(game), 12)
        self.assertFalse(game.state.players[1].combo_modifiers)
        self.assertEqual(sum(e.kind == 'combo_modifier_used' for e in game.events), 1)
        self.portable(game)

    def test_granted_self_repeat_copies_with_a_distinct_physical_carrier(self):
        def extension(registry):
            registry.register_behavior('grant.copy', lambda c: [GrantComboRepeatAura(c.target_id,
                specification(3, scope='self'), c.source_id), CopyMinion(c.target_id, 1)])
            registry.register_card(CardDefinition('grant.copy', 'Grant and copy', CardType.SPELL,
                on_play='grant.copy', targeting=TargetSpec(), metadata=metadata()))
        self.extend(extension)
        game = self.game(hand=('grant.copy', 'dragon.combo'), board=('plain',))
        self.play(game, 'grant.copy', find(game.state, 'plain'))
        self.play(game)
        self.assertEqual(self.plan(game).repetitions, 1)
        ids = [a.id for i in game.state.players[1].board for a in active_abilities(game.state.entities[i], 'combo_repeat')]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(self.armor(game), 2)
        self.portable(game)

    def test_cancelled_and_empty_paid_roots_cannot_delete_both_proofs_and_finish(self):
        cases = ((('no.combo',), (), True), (('dragon.combo',), (), False),
                 (('dragon.combo',), ('counter',), True))
        def extension(registry):
            registry.register_behavior('empty.used.wait', lambda c: [ask(c)] if c.play.kind == CardType.MINION else [])
            registry.register_card(CardDefinition('empty.used.wait', 'Completion wait', CardType.MINION,
                health=5, metadata=metadata(), triggers=(TriggerSpec('card_committed', 'empty.used.wait'),)))
            for name, event in (('full.late.wait', 'minion_entry_failed'), ('magnetic.late.wait', 'magnetized')):
                registry.register_behavior(name, lambda c: [ask(c)])
                registry.register_card(CardDefinition(name, name, CardType.MINION, health=5,
                    metadata=metadata(), triggers=(TriggerSpec(event, name),)))
        self.extend(extension)
        for hand, board, primed in cases:
            game = self.game(hand=hand, board=(*board, 'empty.used.wait'), primed=primed)
            self.play(game, hand[0])
            self.portable(game)
            snapshot = game.snapshot()
            queue = snapshot['resolution_frame']['fields']['continuation']['tuple']
            queue[:] = [work for work in queue if not any(work.get('type', '').endswith('.' + name)
                for name in ('FinishComboAcceptance', 'FinishPlay', 'MinionCounterPhase', 'ResolveMinionPlay'))]
            self.reject(snapshot)
        # These public events pause after the failed physical entry, with an
        # actual empty activation proof. Compact history later ignores zones;
        # the original negative window must require its consumed paid carrier.
        for name, board, position, status in (
                ('dragon.combo', ('fill', 'full.late.wait'), None, 'board_full'),
                ('magnet.combo', ('mech', 'magnetic.late.wait'), 0, 'magnetized')):
            game = self.game(hand=(name,), board=board)
            entity = self.play(game, name, position=position)
            self.assertEqual(self.receipt(game).status, status)
            self.assertEqual(game.state.entities[entity].zone, Zone.GRAVEYARD)
            self.portable(game)
            for mode in ('zone', 'controller', 'delete.complete.root'):
                snapshot = game.snapshot()
                if mode == 'delete.complete.root':
                    queue = snapshot['resolution_frame']['fields']['continuation']['tuple']
                    queue[:] = [work for work in queue if not any(work.get('type', '').endswith('.' + marker)
                        for marker in ('FinishComboAcceptance', 'FinishPlay'))]
                else:
                    proof = next(p for p in self.named(snapshot['resolution_frame'], 'FinishComboAcceptance')
                        if p['fields']['phase'] == 'activation')
                    original = proof['fields']['context']['fields']['state']['state']
                    source = original['entities'][str(entity)]
                    original['players']['1']['graveyard'].remove(entity)
                    if mode == 'zone':
                        source['zone'] = 'hand'
                        original['players']['1']['hand'].append(entity)
                    else:
                        source['controller'] = 2
                        original['players']['2']['graveyard'].append(entity)
                self.reject(snapshot)
            self.finish_choices(game)
            self.check_once(game)
            self.portable(game)

    def test_private_receipts_reject_missing_or_extra_fields(self):
        game = self.game(hand=('generic.dragon.ask',))
        self.play(game, 'generic.dragon.ask')
        for target, field in (('root', 'combo_submission_receipt_id'), ('acceptance', 'policy_receipt_id'),
                              ('policy', 'consumption_applied'), ('policy', 'recipient')):
            snapshot = game.snapshot()
            value = (snapshot['state']['play_history'][-1] if target == 'root' else
                snapshot['state']['play_history'][-1]['combo_acceptance'] if target == 'acceptance' else
                snapshot['state']['combo_policy_receipts'][-1])
            value.pop(field)
            self.reject(snapshot)
        snapshot = game.snapshot()
        snapshot['state']['combo_policy_receipts'][-1]['witnesses'] = []
        self.reject(snapshot)

    def test_completed_plan_cannot_shrink_lower_contributors_or_consumable_set(self):
        game = self.game(hand=('policy.both', 'dragon.combo'), board=('tribal.5',))
        self.play(game, 'policy.both')
        self.play(game)
        for field in ('contributors', 'consumable_ids'):
            snapshot = game.snapshot()
            plan = snapshot['state']['play_history'][-1]['combo_acceptance']['plan']
            plan[field] = plan[field][1:]
            snapshot['state']['combo_batches'][-1]['plan'] = copy.deepcopy(plan)
            self.reject(snapshot)

    def test_public_added_used_removed_and_expired_keep_same_detached_match_shape(self):
        def extension(registry):
            registry.register_behavior('remove.policy', lambda c: [RemoveComboRepeatModifier(1,
                context_policy.id) for context_policy in c.state.players[1].combo_modifiers])
            registry.register_card(CardDefinition('remove.policy', 'Remove policy', CardType.SPELL,
                on_play='remove.policy', metadata=metadata()))
        self.extend(extension)
        game = self.game(hand=('policy.play.one', 'dragon.combo', 'policy.unlimited', 'remove.policy', 'policy.expire'))
        for name in ('policy.play.one', 'dragon.combo', 'policy.unlimited', 'remove.policy', 'policy.expire'):
            self.play(game, name)
        game.apply(EndTurn(1))
        expected = {'combo_modifier_added', 'combo_modifier_used', 'combo_modifier_removed', 'combo_modifier_expired'}
        for player in (1, 2):
            result = game.player_events(player)
            events = result['events'] if isinstance(result, dict) else result
            selected = [e for e in events if e['kind'] in expected]
            self.assertEqual({e['kind'] for e in selected}, expected)
            for event in selected:
                self.assertEqual(event['combo_modifier']['scope'], 'friendly')
                self.assertEqual(set(event['combo_modifier']['match']), {'recipient_metadata'})
            self.assertEqual(next(e['combo_modifier']['uses_remaining'] for e in selected if e['kind'] == 'combo_modifier_used'), 0)
        self.portable(game)

    def test_public_event_codec_rejects_source_conditions_internal_identity_and_unknown_fields(self):
        game = self.game(hand=('policy.play.one',))
        self.play(game, 'policy.play.one')
        for field, value in (('source_eligibility', None), ('modifier_id', 999), ('witness_ids', [])):
            snapshot = game.snapshot()
            event = next(e for e in snapshot['information']['players']['1']['events'] if e['kind'] == 'combo_modifier_added')
            event['combo_modifier'][field] = value
            self.reject(snapshot)

    def test_native_example_restores_every_choice_and_uses_both_public_policy_windows(self):
        from examples.combo_matching import run
        game, waiting, summary = run()
        self.assertEqual(summary['accepted_counts'], [1, 3, 1])
        self.assertEqual(summary['contributor_counts'], [0, 4, 0])
        self.assertEqual((len(waiting), len(game.state.combo_history), len(game.state.combo_policy_receipts)), (5, 5, 6))
        self.assertEqual((summary['final_mana'], summary['armor']), (6, 5))

    def test_false_repeat_declaration_cannot_be_hidden_on_a_nonminion_physical_entity(self):
        game = self.game(hand=('weapon.combo', 'generic.beast.ask'), board=('tribal.2',))
        self.play(game, 'weapon.combo')
        self.play(game, 'generic.beast.ask')
        self.assertEqual(self.plan(game).contributors, ())
        for target_id in (game.state.players[1].hero_id, game.state.players[1].weapon_id):
            snapshot = game.snapshot()
            source = next(e for e in snapshot['state']['entities'].values() if e['card_id'] == 'tribal.2')
            ability = next(a for a in source['abilities'] if a['kind'] == 'combo_repeat')
            source['abilities'].remove(ability)
            snapshot['state']['entities'][str(target_id)]['abilities'].append(ability)
            self.reject(snapshot)

    def test_false_inactive_source_unknown_profile_is_rejected_in_all_zones(self):
        def extension(registry):
            registry.register_card(CardDefinition('dormant.source', 'Dormant source', CardType.MINION,
                health=5, dormant_turns=None, metadata=metadata(),
                combo_repeats=(specification(eligibility=witness()),)))
        self.extend(extension)
        game = self.game(hand=('generic.beast.ask',), board=('dormant.source',))
        self.play(game, 'generic.beast.ask')
        snapshot = game.snapshot()
        ability = self.source_ability(snapshot, 'dormant.source')
        ability['combo_repeat']['match']['source_eligibility']['profile_id'] = 'missing'
        self.reject(snapshot)
        self.portable(game)

    def test_terminal_retained_outcomes_do_not_complete_unstarted_iterations(self):
        def extension(registry):
            registry.register_card(CardDefinition('fatal.retained', 'Retained lethal', CardType.MINION,
                cost=1, health=5, metadata=metadata(('dragon',)), combo='fatal',
                keywords=(Keyword.COMBO, Keyword.REWIND), rewind=RewindSpec(2)))
        self.extend(extension)
        game = self.game(hand=('policy.both', 'fatal.retained'), board=('retainer',))
        self.play(game, 'policy.both')
        self.play(game, 'fatal.retained')
        self.assertEqual(self.receipt(game).status, 'activated')
        self.assertEqual(len(game.state.combo_history), 1)
        self.assertTrue(game.state.rewind_outcomes[0].interrupted)
        self.assertTrue(game.state.combo_history[0].interrupted)
        self.assertEqual([m.uses_remaining for m in game.state.players[1].combo_modifiers], [1, 1])
        self.portable(game)

    def test_summon_and_copy_do_not_spend_paid_combo_policy_or_create_combo_acceptance(self):
        def extension(registry):
            registry.register_behavior('summon.combo', lambda c: [Summon(1, 'dragon.combo')])
            registry.register_card(CardDefinition('summon.combo', 'Summon Combo', CardType.SPELL,
                on_play='summon.combo', metadata=metadata()))
        self.extend(extension)
        game = self.game(hand=('policy.both', 'summon.combo', 'copy'))
        self.play(game, 'policy.both')
        self.play(game, 'summon.combo')
        self.play(game, 'copy', find(game.state, 'dragon.combo'))
        self.assertEqual(game.state.combo_history, [])
        self.assertEqual(game.state.combo_policy_receipts, [])
        self.assertEqual([m.uses_remaining for m in game.state.players[1].combo_modifiers], [2, 2])
        self.assertTrue(all(r.combo_acceptance is None and r.combo_submission_receipt_id is None
            for r in game.state.play_history))
        self.portable(game)

    def test_expired_or_enemy_board_sources_do_not_contribute_to_the_new_root(self):
        game = self.game(board=('beast.5',), enemy=('tribal.5',))
        self.play(game)
        self.assertEqual(self.plan(game).repetitions, 1)
        self.assertEqual(self.plan(game).contributors, ())
        self.portable(game)

    def test_receipt_chronology_rejects_missing_phase_duplicate_phase_and_capture_before_play(self):
        game = self.game(hand=('generic.dragon.ask',))
        self.play(game, 'generic.dragon.ask')
        for mode in ('missing', 'duplicate', 'action'):
            snapshot = game.snapshot()
            receipts = snapshot['state']['combo_policy_receipts']
            if mode == 'missing':
                receipts.pop()
            elif mode == 'duplicate':
                receipts[-1]['phase'] = 'play'
            else:
                receipts[-1]['action'] = game.state.play_history[-1].action - 1
            self.reject(snapshot)

    def test_cancelled_colossal_link_cannot_borrow_another_entry_of_the_same_carrier(self):
        game = self.game(hand=('giant.combo',), board=('giant.bounce',))
        self.play(game, 'giant.combo')
        first = game.state.play_history[-1]
        self.play(game, 'giant.combo')
        second = game.state.play_history[-1]
        self.assertEqual(first.source_id, second.source_id)
        self.assertNotEqual(first.id, second.id)
        self.assertNotEqual(first.combo_acceptance.colossal_record_id, second.combo_acceptance.colossal_record_id)
        snapshot = game.snapshot()
        snapshot['state']['play_history'][-1]['combo_acceptance']['colossal_record_id'] = first.combo_acceptance.colossal_record_id
        self.reject(snapshot)
        self.portable(game)

    def false_parent_with_last_use_child(self, *, other_family=False):
        def extension(registry):
            registry.register_behavior('false.parent.generic', lambda c: [ask(c, (
                PlayFromHand(PlayCard(1, next(i for i in c.state.players[1].hand
                    if c.state.entities[i].card_id == 'dragon.ask'))),))])
            registry.register_card(CardDefinition('false.parent', 'False parent policy', CardType.MINION,
                cost=1, health=5, metadata=metadata(('beast',)), keywords=(Keyword.COMBO,),
                combo='armor', on_play='false.parent.generic'))
            registry.register_behavior('last.use.policy', lambda c: [AddComboRepeatModifier(1,
                specification(2, tribes=('dragon',)), c.source_id, 1, trigger='play'),
                *([AddBattlecryRepeatModifier(1, source_id=c.source_id)] if other_family else [])])
            registry.register_card(CardDefinition('last.use.policy', 'One-use Dragon policy',
                CardType.SPELL, on_play='last.use.policy', metadata=metadata()))
        self.extend(extension)
        game = self.game(hand=('last.use.policy', 'false.parent', 'dragon.ask'))
        self.play(game, 'last.use.policy')
        identity = game.state.players[1].combo_modifiers[0].id
        self.play(game, 'false.parent')
        parent = game.state.play_history[-1]
        self.assertEqual(parent.combo_acceptance.plan.contributors, ())
        self.assertEqual(game.state.players[1].combo_modifiers[0].uses_remaining, 1)
        self.portable(game)
        self.choose(game)
        child = game.state.play_history[-1]
        self.assertNotEqual(parent.id, child.id)
        self.assertFalse(game.state.players[1].combo_modifiers)
        self.assertEqual(child.combo_acceptance.plan.repetitions, 2)
        self.portable(game)
        return game, parent, child, identity

    def rewrite_later_contexts(self, snapshot, child_id, mutation):
        def visit(value):
            if isinstance(value, dict):
                if value.get('type', '').endswith('.RuleContext'):
                    play = value['fields'].get('play')
                    if isinstance(play, dict) and play.get('fields', {}).get('id') == child_id:
                        mutation(value)
                        return
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
        visit(snapshot['resolution_frame'])

    def test_false_original_policy_is_bound_after_later_last_use_removes_live_source(self):
        game, parent, child, identity = self.false_parent_with_last_use_child()
        snapshot = game.snapshot()
        for receipt in snapshot['state']['combo_policy_receipts']:
            if receipt['play_id'] == child.id:
                for modifier in receipt['modifiers']:
                    modifier['spec']['match']['recipient_metadata']['tribes_any'] = ['dragon', 'beast']
        def change(value):
            if isinstance(value, dict):
                if value.get('type', '').endswith('.ComboRepeatModifier') and value['fields']['id'] == identity:
                    value['fields']['spec']['fields']['match']['fields']['recipient_metadata']['fields']['tribes_any']['tuple'] = ['dragon', 'beast']
                if {'id', 'spec', 'uses_remaining', 'trigger'} <= set(value) and value['id'] == identity:
                    value['spec']['match']['recipient_metadata']['tribes_any'] = ['dragon', 'beast']
                for item in value.values():
                    change(item)
            elif isinstance(value, list):
                for item in value:
                    change(item)
        self.rewrite_later_contexts(snapshot, child.id, change)
        # The later operand still matches Dragon, its count/use chain agrees,
        # and the current policy is gone. The earlier false full declaration
        # must nevertheless prevent changing that policy to include Beast.
        self.reject(snapshot)
        self.finish_choices(game)
        self.assertEqual(self.armor(game), 6)
        self.portable(game)

    def test_other_original_global_family_id_cannot_become_a_later_consumed_combo_policy(self):
        game, parent, child, identity = self.false_parent_with_last_use_child(other_family=True)
        other = game.state.players[1].battlecry_modifiers[0].id
        snapshot = game.snapshot()
        snapshot['state']['players']['1']['battlecry_modifiers'] = []
        def rewrite(value):
            if isinstance(value, dict):
                if 'battlecry_modifiers' in value:
                    value['battlecry_modifiers'] = [m for m in value['battlecry_modifiers'] if m['id'] != other]
                if value.get('type', '').endswith('.ComboRepeatModifier') and value['fields']['id'] == identity:
                    value['fields']['id'] = other
                if {'id', 'spec', 'uses_remaining', 'trigger'} <= set(value) and value['id'] == identity:
                    value['id'] = other
                for field in ('contributors', 'consumable_ids'):
                    if field in value and isinstance(value[field], list):
                        value[field] = [other if i == identity else i for i in value[field]]
                if value.get('type', '').endswith('.ComboRepeatPlan'):
                    for field in ('contributors', 'consumable_ids'):
                        values = value['fields'][field]['tuple']
                        values[:] = [other if i == identity else i for i in values]
                for item in value.values():
                    rewrite(item)
            elif isinstance(value, list):
                for item in value:
                    rewrite(item)
        rewrite(snapshot['state'])
        self.rewrite_later_contexts(snapshot, child.id, rewrite)
        # Both live policies disappear. The old parent's complete global
        # attachment map still identifies this ID as Battlecry, not Combo.
        self.reject(snapshot)
        self.finish_choices(game)
        self.assertEqual(self.armor(game), 6)
        self.portable(game)


if __name__ == '__main__':
    unittest.main()
