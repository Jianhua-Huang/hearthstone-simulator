"""B1: controlled physical witnesses, original spell windows and private proof.

These are synthetic public-mechanism examples, not CN card-rule evidence.
Ordinary existence and another share a query but differ by physical carrier ID.
"""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import copy
import json
import unittest
from dataclasses import replace

import test_m5_spell_repeats as foundation
import test_m5_spell_match as matching
from hs_sim.engine import (CardDefinition, CardMetadata, CardClass, CardType,
    Game, Keyword, RewindSpec, ResolutionError, ResolutionLimitExceeded,
    SpellRepeatSpec, SpellSchool, SnapshotError, EndTurn, Zone, GrantSpellRepeatAura)
from hs_sim.engine.model import (RecipientMetadataFilter, RepeatMatchSpec,
    RepeatSourceEligibility, RepeatWitnessProfile, SpellRepeatModifier, DormancyState,
    AbilityInstance)
from hs_sim.engine.effects import (GainArmor, RequestChoice, ChoiceOption, Summon,
    Silence, Destroy, ChangeControl, ReturnToHand, Transform, Damage, RandomDamage,
    CopyMinion, RandomDestroy)
from hs_sim.engine.spell_modifiers import AddSpellRepeatModifier, RemoveSpellRepeatModifier
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.resolver import PlayFromHand, Resolution
from hs_sim.engine import PlayCard
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.repeat_matching import repeat_match_to_dict, repeat_match_from_dict
from hs_sim.engine.repeat_source_conditions import qualifying_repeat_witnesses, validate_source_declaration
from hs_sim.engine.spell_repeats import execution_count
from hs_sim.engine.card_spell_repeats import GrantCardSpellRepeat
from hs_sim.engine.zones import CardReference
from hs_sim.engine.information import validate_spell_modifier_view


class RepeatSourceConditionTests(unittest.TestCase):
    spell = foundation.SpellRepeatTests.spell
    game = foundation.SpellRepeatTests.game
    play = foundation.SpellRepeatTests.play
    hero = foundation.SpellRepeatTests.hero
    choose = foundation.SpellRepeatTests.choose
    events = foundation.SpellRepeatTests.events
    watch = matching.SpellMatchTests.watch
    pause = matching.SpellMatchTests.pause
    ask = matching.SpellMatchTests.ask
    armor = matching.SpellMatchTests.armor
    subject = matching.SpellMatchTests.subject
    casts = matching.SpellMatchTests.casts
    portable = matching.SpellMatchTests.portable
    fresh_registry = matching.SpellMatchTests.fresh_registry
    reject = matching.SpellMatchTests.reject
    work = matching.SpellMatchTests.work
    is_proof = staticmethod(matching.SpellMatchTests.is_proof)
    proofs = matching.SpellMatchTests.proofs
    delete_proofs = matching.SpellMatchTests.delete_proofs

    @staticmethod
    def meta(tribes=()):
        return CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=tribes)

    def minion(self, name, **kw):
        kw.setdefault('metadata', self.meta())
        foundation.SpellRepeatTests.minion(self, name, **kw)

    @staticmethod
    def eligibility(profile='repeat.witness.controlled', tribes=('dragon',), another=True):
        return RepeatSourceEligibility(profile, tribes, another)

    @classmethod
    def spec(cls, casts=2, *, another=True, profile='repeat.witness.controlled',
             tribes=('dragon',), schools=(SpellSchool.ARCANE,), mode='any'):
        return SpellRepeatSpec(casts, mode, RepeatMatchSpec(
            RecipientMetadataFilter(spell_schools=schools) if schools is not None else None,
            cls.eligibility(profile, tribes, another)))

    def setUp(self):
        foundation.SpellRepeatTests.setUp(self)
        for name, tribes in (('dragon', ('dragon',)), ('multitribe', ('beast', 'dragon')),
                            ('alltribes', ('all',)), ('emptytribes', ()),
                            ('unknowntribes', None)):
            self.minion(name, health=5, metadata=self.meta(tribes))
        self.minion('unknownmeta', health=5, metadata=None)
        self.minion('dormant.dragon', health=5, metadata=self.meta(('dragon',)), dormant_turns=None)
        for another, suffix in ((False, 'ordinary'), (True, 'another')):
            self.minion('cond.' + suffix, health=6, metadata=self.meta(('dragon',)),
                spell_repeats=(self.spec(another=another),))
        self.minion('cond.plain', health=6, spell_repeats=(self.spec(),))
        self.minion('cond.active', health=6,
            spell_repeats=(self.spec(profile='repeat.witness.active_live'),))
        self.minion('cond.anywitness', health=6, metadata=None,
            spell_repeats=(self.spec(tribes=()),))
        self.minion('cond.unknownself', health=6, metadata=None,
            spell_repeats=(self.spec(),))
        self.minion('cond.3', health=6, spell_repeats=(self.spec(3),))
        self.minion('cond.5', health=6, spell_repeats=(self.spec(5),))
        self.minion('unconditional.3', health=6, spell_repeats=(SpellRepeatSpec(3, 'any'),))
        self.minion('retainer', health=6, retain_rewind_outcomes=True)
        self.minion('carrier', health=6)
        self.minion('huge.conditional', health=6, spell_repeats=(self.spec(1001),))
        for cid, school in (('arcane', SpellSchool.ARCANE), ('fire', SpellSchool.FIRE),
                            ('schoolless', None), ('inner.arcane', SpellSchool.ARCANE)):
            self.spell(cid, lambda c: [GainArmor(c.player_id, 2)], cost=1, spell_school=school)
        self.spell('ask.arcane', self.ask, cost=1, spell_school=SpellSchool.ARCANE)
        for name, effect in (('steal', lambda i: ChangeControl(i, 2)),
                             ('transform', lambda i: Transform(i, 'plain')),
                             ('bounce', ReturnToHand), ('silence', Silence)):
            self.spell('ask.source.' + name, lambda c, effect=effect: [RequestChoice(1,
                (ChoiceOption('ok', 'Change the accepted carrier',
                    (effect(c.play.spell_payload.contributors[0].carrier_id), GainArmor(1, 2))),),
                source_id=c.source_id)], cost=1, spell_school=SpellSchool.ARCANE)
        self.spell('noop.arcane', lambda c: [], cost=1, spell_school=SpellSchool.ARCANE)
        self.spell('false.remove.source', lambda c: [Silence(next(i for i in c.state.players[1].board
            if c.state.entities[i].card_id == 'cond.plain')), self.pause(c)],
            cost=1, spell_school=SpellSchool.ARCANE)
        self.r.register_card(CardDefinition('empty.arcane', 'empty.arcane', CardType.SPELL,
            cost=1, spell_school=SpellSchool.ARCANE, metadata=self.meta()))
        self.spell('fatal.arcane', lambda c: [Damage(c.state.players[2].hero_id, 50, c.source_id)],
            cost=1, spell_school=SpellSchool.ARCANE)
        self.spell('hit.arcane', lambda c: [Damage(c.target_id, 2, c.source_id)],
            cost=1, spell_school=SpellSchool.ARCANE, requires_target=True)
        self.spell('add.dragon', lambda c: [Summon(1, 'dragon'), GainArmor(1, 2)],
            cost=1, spell_school=SpellSchool.ARCANE)
        self.spell('remove.dragon', lambda c: [
            *([ReturnToHand(self.witness_id(c.state))] if self.witness_id(c.state, optional=True) else []),
            GainArmor(1, 2)],
            cost=1, spell_school=SpellSchool.ARCANE)
        self.spell('kill.ask', lambda c: [Destroy(self.witness_id(c.state)), self.pause(c), GainArmor(1, 2)],
            cost=1, spell_school=SpellSchool.ARCANE)
        self.spell('fail.random', lambda c: [RandomDamage((c.state.players[2].hero_id,), 1),
            *([GrantSpellRepeatAura(c.state.players[1].board[0], self.spec(), 999999)]
              if c.state.entities[c.state.players[2].hero_id].health < 30 else [])],
            spell_school=SpellSchool.ARCANE)
        self.spell('ordinary.rewind', lambda c: [Summon(1, 'dragon'),
            GainArmor(1, c.rewind_attempt + 1)], cost=1, spell_school=SpellSchool.ARCANE,
            keywords=(Keyword.REWIND,), rewind=RewindSpec(1))
        self.spell('random.rewind', lambda c: [GainArmor(1, 1)], cost=1,
            spell_school=SpellSchool.ARCANE, keywords=(Keyword.REWIND,), rewind=RewindSpec(3))
        self.watch('commit.random', 'card_committed', lambda c: [RandomDestroy(tuple(
            i for i in c.state.players[1].board if c.state.entities[i].card_id in ('dragon', 'emptytribes')))])
        self.spell('kill.nested', self.kill_nested, cost=1, spell_school=SpellSchool.ARCANE)
        self.spell('inner.ask', self.ask, cost=1, spell_school=SpellSchool.ARCANE)
        self.spell('retained.rewind', lambda c: [
            *([ReturnToHand(self.witness_id(c.state))] if self.witness_id(c.state, optional=True) else []),
            self.pause(c), GainArmor(1, 2)], cost=1, spell_school=SpellSchool.ARCANE,
            keywords=(Keyword.REWIND,), rewind=RewindSpec(1))
        self.watch('commit.add', 'card_committed', lambda c: [Summon(1, 'dragon')])
        self.watch('commit.remove', 'card_committed', lambda c: [ReturnToHand(self.witness_id(c.state))])
        self.watch('commit.wait', 'card_committed', lambda c: [self.pause(c)])
        self.watch('tail.wait', 'card_played', lambda c: [self.pause(c)])
        self.watch('commit.fatal', 'card_committed', lambda c: [Damage(c.state.players[2].hero_id, 50)])
        self.watch('nested.add', 'card_played', self.nested_add)
        self.watch('nested.remove', 'card_played', self.nested_remove)
        self.watch('nested.doom', 'card_played', self.nested_doom)
        self.r.register_behavior('grant.donor', lambda c: [GrantSpellRepeatAura(
            next(i for i in c.state.players[1].board if c.state.entities[i].card_id == 'carrier'),
            self.spec(), c.source_id)])
        self.minion('grant.donor', health=5, metadata=self.meta(('dragon',)), battlecry='grant.donor')
        self.r.register_behavior('grant.expiring', lambda c: [GrantSpellRepeatAura(
            c.state.players[1].board[0], self.spec(), c.source_id, c.state.turn)])
        self.minion('grant.expiring', health=5, battlecry='grant.expiring')
        self.r.register_behavior('policy', lambda c: [AddSpellRepeatModifier(1,
            SpellRepeatSpec(2, 'any', RepeatMatchSpec(RecipientMetadataFilter(
                spell_schools=(SpellSchool.ARCANE,)))), c.source_id, uses=3)])
        self.minion('policy', health=5, battlecry='policy')
        self.r.register_behavior('setup.max', self.setup_max)
        self.minion('setup.max', health=5, battlecry='setup.max')
        self.r.register_behavior('remove.policy', lambda c: [RemoveSpellRepeatModifier(1,
            c.state.players[1].spell_modifiers[0].id)])
        self.minion('remove.policy', health=5, battlecry='remove.policy')
        self.r.register_behavior('expire.policy', lambda c: [AddSpellRepeatModifier(1,
            SpellRepeatSpec(2, 'any', RepeatMatchSpec(RecipientMetadataFilter(
                spell_schools=(SpellSchool.ARCANE,)))), c.source_id, uses=3, expires_turn=c.state.turn)])
        self.minion('expire.policy', health=5, battlecry='expire.policy')
        self.r.register_behavior('grant.unknown', lambda c: [GrantSpellRepeatAura(999999,
            self.spec(profile='missing.profile'), c.source_id)])
        self.minion('grant.unknown', health=5, battlecry='grant.unknown')
        self.r.register_behavior('setup.counter', lambda c: [SetSecret(2, 'EX1_287')])
        self.minion('setup.counter', health=5, battlecry='setup.counter')
        self.r.register_behavior('setup.redirect', lambda c: [SetSecret(2, 'tt_010')])
        self.minion('setup.redirect', health=5, battlecry='setup.redirect')
        self.r.register_behavior('grant.witness', lambda c: [GrantSpellRepeatAura(i, spec, c.source_id)
            for i in c.state.players[1].board if c.state.entities[i].card_id == 'dragon'
            for spec in (SpellRepeatSpec(2, 'any'), SpellRepeatSpec(3, 'any'))])
        self.minion('grant.witness', health=5, battlecry='grant.witness')
        self.r.register_repeat_witness_profile(RepeatWitnessProfile('test.presence.include',
            include_dormant=getattr(self, 'presence_include_dormant', True), include_starship_building=True))
        for name, kwargs in (('dormant', dict(include_dormant=False)),
                             ('building', dict(include_starship_building=False)),
                             ('doomed', dict(include_doomed=False)),
                             ('health', dict(require_positive_health=True))):
            self.r.register_repeat_witness_profile(RepeatWitnessProfile('test.exclude.' + name,
                **{'include_starship_building': True, **kwargs}))

    @staticmethod
    def witness_id(state, optional=False):
        return next((i for i in state.players[1].board if state.entities[i].card_id == 'dragon'),
                    None if optional else 0)

    def entity(self, g, cid, player=1):
        return next(g.state.entities[i] for i in g.state.players[player].board
                    if g.state.entities[i].card_id == cid)

    def setup_max(self, c):
        eid = next(i for i in c.state.players[1].hand if c.state.entities[i].card_id == 'ask.arcane')
        return [AddSpellRepeatModifier(1, SpellRepeatSpec(2, 'any'), c.source_id, uses=1),
                GrantCardSpellRepeat(CardReference.capture(c.state.entities[eid]), 4, c.source_id)]

    def inner_play(self, c):
        inner = next(i for i in c.state.players[1].hand if c.state.entities[i].card_id == 'inner.arcane')
        return PlayFromHand(PlayCard(1, inner))

    def nested_add(self, c):
        if c.state.entities[c.event.source_id].card_id == 'arcane':
            return [RequestChoice(1, (ChoiceOption('nested', 'Create a new root',
                (Summon(1, 'dragon'), self.inner_play(c), self.pause(c))),), source_id=c.source_id)]
        return [self.pause(c)] if c.state.entities[c.event.source_id].card_id == 'inner.arcane' else []

    def nested_remove(self, c):
        if c.state.entities[c.event.source_id].card_id == 'arcane':
            return [RequestChoice(1, (ChoiceOption('nested', 'Create a new root',
                (ReturnToHand(self.witness_id(c.state)), self.inner_play(c), self.pause(c))),), source_id=c.source_id)]
        return [self.pause(c)] if c.state.entities[c.event.source_id].card_id == 'inner.arcane' else []

    def nested_doom(self, c):
        if c.state.entities[c.event.source_id].card_id == 'kill.ask':
            return [self.inner_play(c), self.pause(c)]
        return [self.pause(c)] if c.state.entities[c.event.source_id].card_id == 'inner.arcane' else []

    def kill_nested(self, c):
        if c.cast.iteration == 1:
            eid = next(i for i in c.state.players[1].hand if c.state.entities[i].card_id == 'inner.ask')
            return [RequestChoice(1, (ChoiceOption('nested', 'Use the deferred witness',
                (Destroy(self.witness_id(c.state)), PlayFromHand(PlayCard(1, eid)), self.pause(c))),),
                source_id=c.source_id), GainArmor(1, 2)]
        return [self.pause(c), GainArmor(1, 2)]

    def query(self, g, carrier, eligibility=None, state=None):
        return qualifying_repeat_witnesses(state or g.state, g.registry, player_id=1,
            carrier_id=carrier, eligibility=eligibility or self.eligibility())

    def finish_choices(self, g):
        while g.state.pending_choice:
            self.choose(g, 'ok')

    @staticmethod
    def nodes(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from RepeatSourceConditionTests.nodes(child)
        elif isinstance(value, list):
            for child in value:
                yield from RepeatSourceConditionTests.nodes(child)

    def test_ordinary_self_and_another_physical_identity_are_distinct(self):
        for cid, extra, expected in (('cond.ordinary', (), 2), ('cond.another', (), 1),
                                    ('cond.another', ('cond.another',), 2)):
            with self.subTest(cid=cid, extra=extra):
                g = self.game(hand=('arcane',), board=(cid, *extra))
                ids = tuple(g.state.players[1].board)
                self.assertEqual(self.query(g, ids[0], self.eligibility(another=cid.endswith('another'))),
                    ids[1:] if cid.endswith('another') else ids)
                self.play(g, 'arcane')
                p = self.subject(g)
                self.assertEqual((p.spell_payload.casts, self.armor(g)), (expected, expected * 2))
                self.assertEqual(len(p.spell_payload.contributors), len(ids) if expected == 2 else 0)
                self.portable(g)

    def test_donor_dragon_can_witness_for_a_distinct_non_dragon_carrier(self):
        g = self.game(hand=('grant.donor', 'ask.arcane'), board=('carrier',))
        carrier = self.entity(g, 'carrier').id
        donor = self.play(g, 'grant.donor')
        self.assertEqual(self.query(g, carrier), (donor,))
        self.play(g, 'ask.arcane')
        contributor = self.subject(g).spell_payload.contributors[0]
        self.assertEqual((contributor.carrier_id, contributor.ability.source_id), (carrier, donor))
        self.portable(g)
        self.finish_choices(g)
        self.assertEqual(self.armor(g), 4)
        self.portable(g)

    def test_beneficiary_uses_current_controller_and_board_not_owner_or_active_player(self):
        g = self.game(board=('cond.plain', 'dragon'), enemy=('dragon',))
        carrier, witness = self.entity(g, 'cond.plain').id, self.entity(g, 'dragon').id
        state = copy.deepcopy(g.state)
        state.active_player = 2
        state.entities[witness].owner = 2
        self.assertEqual(self.query(g, carrier, state=state), (witness,))
        state.entities[witness].controller = 2
        with self.assertRaises(ValueError): self.query(g, carrier, state=state)
        state.players[1].board.remove(witness)
        state.players[2].board.append(witness)
        self.assertEqual(self.query(g, carrier, state=state), ())
        state.entities[witness].controller = 1
        state.players[2].board.remove(witness)
        state.players[1].board.append(witness)
        state.entities[witness].zone = Zone.GRAVEYARD
        with self.assertRaises(ValueError): self.query(g, carrier, state=state)
        state.players[1].board.remove(witness)
        state.players[1].graveyard.append(witness)
        self.assertEqual(self.query(g, carrier, state=state), ())

    def test_current_physical_face_or_all_leaf_not_base_face(self):
        for cid, expected in (('dragon', True), ('multitribe', True), ('alltribes', True),
                              ('emptytribes', False)):
            g = self.game(hand=('arcane',), board=('cond.plain', cid))
            carrier, witness = self.entity(g, 'cond.plain').id, self.entity(g, cid).id
            self.assertEqual(self.query(g, carrier), (witness,) if expected else ())
            self.play(g, 'arcane')
            self.assertEqual(self.armor(g), 4 if expected else 2)
        g = self.game(board=('cond.plain', 'multitribe', 'dragon'))
        carrier = self.entity(g, 'cond.plain').id
        self.assertEqual(self.query(g, carrier, self.eligibility(tribes=('mech', 'beast'))),
            (self.entity(g, 'multitribe').id,))
        self.assertEqual(self.query(g, carrier, self.eligibility(tribes=('mech', 'demon'))), ())
        g = self.game(hand=('transform', 'arcane'), board=('cond.plain', 'dragon'))
        self.play(g, 'transform', self.entity(g, 'dragon').id)
        self.play(g, 'arcane')
        self.assertEqual(self.armor(g), 2)
        self.portable(g)

    def test_source_and_witness_silence_have_different_roles(self):
        for target, expected in (('dragon', 4), ('cond.plain', 2)):
            g = self.game(hand=('silence', 'arcane'), board=('cond.plain', 'dragon'))
            self.play(g, 'silence', self.entity(g, target).id)
            self.play(g, 'arcane')
            self.assertEqual(self.armor(g), expected)
            self.portable(g)

    def test_empty_tribes_query_is_any_physical_witness_and_unknown_self_is_excluded_first(self):
        g = self.game(hand=('arcane',), board=('cond.anywitness', 'unknownmeta'))
        carrier, witness = self.entity(g, 'cond.anywitness').id, self.entity(g, 'unknownmeta').id
        self.assertEqual(self.query(g, carrier, self.eligibility(tribes=())), (witness,))
        self.play(g, 'arcane')
        self.assertEqual(self.armor(g), 4)
        self.portable(g)
        g = self.game(hand=('arcane',), board=('cond.unknownself', 'dragon'))
        self.play(g, 'arcane')
        self.assertEqual(self.armor(g), 4)
        self.portable(g)

    def test_known_true_never_short_circuits_unknown_eligible_metadata_or_tribes(self):
        for unknown in ('unknownmeta', 'unknowntribes'):
            for witnesses in (('dragon', unknown), (unknown, 'dragon')):
                with self.subTest(witnesses=witnesses):
                    g = self.game(hand=('arcane',), board=('cond.plain', *witnesses))
                    before = g.snapshot()
                    with self.assertRaises((ResolutionError, ValueError)):
                        self.play(g, 'arcane')
                    self.assertEqual(g.snapshot(), before)
                    with self.assertRaises((ResolutionError, ValueError)):
                        self.query(g, self.entity(g, 'cond.plain').id)
                    self.assertEqual(g.snapshot(), before)

    def test_physically_excluded_unknown_does_not_require_tribes(self):
        g = self.game(board=('cond.plain', 'unknowntribes'), enemy=('unknownmeta',))
        carrier, witness = self.entity(g, 'cond.plain').id, self.entity(g, 'unknowntribes').id
        for gate in ('dormant', 'doomed', 'health', 'building', 'enemy'):
            with self.subTest(gate=gate):
                state = copy.deepcopy(g.state)
                entity = state.entities[witness]
                if gate == 'dormant': entity.dormancy = DormancyState(999, None, state.turn)
                if gate == 'doomed': entity.doomed = True
                if gate == 'health': entity.damage = entity.base_health
                if gate == 'building': entity.starship_building = True
                if gate == 'enemy':
                    entity.controller = 2
                    state.players[1].board.remove(witness)
                    state.players[2].board.append(witness)
                self.assertEqual(self.query(g, carrier,
                    self.eligibility('repeat.witness.active_live'), state), ())

    def test_presence_each_explicit_profile_gate_has_include_exclude_pair(self):
        g = self.game(board=('cond.plain', 'dragon'))
        carrier, witness = self.entity(g, 'cond.plain').id, self.entity(g, 'dragon').id
        for gate in ('dormant', 'doomed', 'health', 'building'):
            with self.subTest(gate=gate):
                state = copy.deepcopy(g.state)
                entity = state.entities[witness]
                if gate == 'dormant': entity.dormancy = DormancyState(999, None, state.turn)
                if gate == 'doomed': entity.doomed = True
                if gate == 'health': entity.damage = entity.base_health
                if gate == 'building': entity.starship_building = True
                self.assertEqual(self.query(g, carrier, self.eligibility('test.presence.include'), state), (witness,))
                self.assertEqual(self.query(g, carrier, self.eligibility('test.exclude.' + gate), state), ())

    def test_dormant_default_and_active_profile_have_actual_paid_root_difference(self):
        for source, expected in (('cond.plain', 2), ('cond.active', 1)):
            g = self.game(hand=('arcane',), board=(source, 'dormant.dragon'))
            self.play(g, 'arcane')
            self.assertEqual(self.subject(g).spell_payload.casts, expected)
            self.assertEqual(self.armor(g), expected * 2)
            self.portable(g)

    def test_query_is_pure_complete_ordered_and_does_not_weight_duplicate_cards_or_attachments(self):
        g = self.game(hand=('grant.witness',), board=('cond.plain', 'dragon', 'dragon', 'multitribe'))
        self.play(g, 'grant.witness')
        before = g.snapshot()
        ids = tuple(i for i in g.state.players[1].board if g.state.entities[i].card_id != 'grant.witness')
        self.assertTrue(all(len(g.state.entities[i].abilities) == 2 for i in ids[1:3]))
        for profile in ('repeat.witness.controlled', 'repeat.witness.active_live', 'test.presence.include'):
            self.assertEqual(self.query(g, ids[0], self.eligibility(profile)), ids[1:])
            self.assertEqual(g.snapshot(), before)
        self.assertEqual(len(set(ids[1:])), 3)

    def test_complete_max_keeps_low_equal_high_sources_with_finite_and_card_sources(self):
        g = self.game(hand=('setup.max', 'ask.arcane'),
            board=('cond.plain', 'unconditional.3', 'dragon'))
        self.play(g, 'setup.max'); self.play(g, 'ask.arcane')
        p = self.subject(g)
        self.assertEqual(p.spell_payload.casts, 4)
        self.assertEqual([s.ability.spell_repeat.casts for s in p.spell_payload.contributors], [2, 3])
        self.assertEqual([m.spec.casts for m in p.spell_submission.modifiers], [2])
        self.assertEqual([a.spell_repeat.casts for a in p.card_spell_repeats], [4])
        self.assertFalse(g.state.players[1].spell_modifiers)
        self.portable(g)
        for remove_index in (0, 1):
            snap = g.snapshot()
            del snap['state']['play_history'][-1]['spell_payload']['contributors'][remove_index]
            self.reject(snap)
        self.finish_choices(g)
        self.assertEqual((self.armor(g), g.state.players[1].mana), (8, 9))
        self.portable(g)

    def test_all_conditional_low_equal_high_matching_sources_are_retained(self):
        g = self.game(hand=('ask.arcane',), board=('cond.plain', 'cond.3', 'cond.5', 'dragon'))
        self.play(g, 'ask.arcane')
        self.assertEqual([s.ability.spell_repeat.casts for s in self.subject(g).spell_payload.contributors], [2, 3, 5])
        for index in (0, 1, 2):
            snap = g.snapshot()
            del snap['state']['play_history'][-1]['spell_payload']['contributors'][index]
            self.reject(snap)
        self.finish_choices(g)
        self.assertEqual(self.armor(g), 10)
        self.portable(g)

    def test_before_late_window_changes_truth_without_moving_player_consumption(self):
        for watch, witness, expected in (('commit.add', (), 2), ('commit.remove', ('dragon',), 2)):
            g = self.game(hand=('policy', 'arcane'), board=('cond.plain', watch, *witness))
            self.play(g, 'policy'); self.play(g, 'arcane')
            p = self.subject(g)
            self.assertEqual(p.spell_payload.casts, expected)
            self.assertEqual(len(p.spell_payload.contributors), int(watch == 'commit.add'))
            self.assertEqual(g.state.players[1].spell_modifiers[0].uses_remaining, 2)
            self.portable(g)
        g = self.game(hand=('arcane',), board=('cond.plain', 'commit.add'))
        self.play(g, 'arcane')
        self.assertEqual((self.armor(g), self.subject(g).spell_payload.casts), (4, 2))

    def test_true_false_changes_after_acceptance_do_not_recapture_current_root(self):
        for first, board, expected in (('remove.dragon', ('cond.plain', 'dragon'), (4, 2)),
                                        ('add.dragon', ('cond.plain',), (2, 4))):
            g = self.game(hand=(first, 'arcane'), board=board)
            self.play(g, first)
            first_play = self.subject(g)
            self.assertEqual(self.armor(g), expected[0])
            self.assertEqual(execution_count(Resolution(g), first_play), expected[0] // 2)
            self.play(g, 'arcane')
            self.assertEqual(self.armor(g), sum(expected))
            self.assertEqual(execution_count(Resolution(g), first_play), expected[0] // 2)
            self.portable(g)

    def test_source_new_grant_expiry_control_copy_and_transform_use_lifecycle(self):
        g = self.game(hand=('grant.expiring', 'arcane', 'arcane'), board=('carrier', 'dragon'))
        self.play(g, 'grant.expiring'); self.play(g, 'arcane')
        self.assertEqual(self.armor(g), 4)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g, 'arcane')
        self.assertEqual(self.armor(g), 6)
        self.portable(g)
        for action in ('transform', 'steal', 'bounce'):
            g = self.game(hand=(action, 'arcane'), board=('cond.plain', 'dragon'))
            self.play(g, action, self.entity(g, 'cond.plain').id)
            self.play(g, 'arcane')
            self.assertEqual(self.armor(g), 2)
            self.portable(g)
        g = self.game(hand=('copy', 'arcane'), board=('cond.another',))
        self.play(g, 'copy', self.entity(g, 'cond.another').id)
        abilities = [e.abilities[0].id for e in (g.state.entities[i] for i in g.state.players[1].board)]
        self.assertEqual(len(set(abilities)), 2)
        self.play(g, 'arcane')
        self.assertEqual((self.armor(g), len(self.subject(g).spell_payload.contributors)), (4, 2))
        self.portable(g)

    def test_actual_witness_control_and_transform_change_only_later_roots(self):
        for action in ('steal', 'bounce', 'transform'):
            g = self.game(hand=('arcane', action, 'arcane'), board=('cond.plain', 'dragon'))
            self.play(g, 'arcane')
            self.play(g, action, self.entity(g, 'dragon').id)
            self.play(g, 'arcane')
            self.assertEqual(self.armor(g), 6)
            self.portable(g)

    def test_all_false_unit_empty_counter_roots_have_distinct_acceptance_receipts(self):
        for cid, counter in (('arcane', False), ('noop.arcane', False),
                             ('empty.arcane', False), ('arcane', True)):
            with self.subTest(cid=cid, counter=counter):
                g = self.game(hand=(cid,), board=('cond.plain', 'tail.wait'),
                    enemy=('unknownmeta',))
                if counter:
                    g = self.game(hand=('setup.counter', cid),
                        board=('cond.plain', 'tail.wait'))
                    self.play(g, 'setup.counter')
                self.play(g, cid)
                p = self.subject(g)
                if counter:
                    self.assertTrue(p.countered)
                    self.assertIsNone(p.spell_payload)
                    self.assertEqual([c.failure for c in self.casts(g)], ['countered'])
                    self.assertFalse(self.casts(g)[0].payload_started)
                else:
                    self.assertEqual((p.spell_payload.casts, p.spell_payload.contributors), (1, ()))
                self.assertFalse(g.state.spell_repeats)
                self.assertTrue(p.completed)
                self.assertFalse(p.spell_acceptance_closed)
                self.portable(g)
                snap = g.snapshot(); self.delete_proofs(snap); self.reject(snap)
                snap = g.snapshot(); snap['state']['play_history'][-1]['spell_acceptance_closed'] = True
                self.reject(snap)
                self.choose(g, 'ok')
                self.assertTrue(self.subject(g).spell_acceptance_closed)
                self.portable(g)

    def test_all_false_proof_preserves_noncontributing_source_in_original_context(self):
        g = self.game(hand=('ask.arcane',), board=('cond.plain',))
        self.play(g, 'ask.arcane')
        snap = g.snapshot()
        proof = self.proofs(snap)[0]
        state = proof['fields']['resolution']['fields']['state']['state']
        carrier = next(e for e in state['entities'].values() if e['card_id'] == 'cond.plain')
        carrier['abilities'][0]['spell_repeat']['match']['source_eligibility']['exclude_carrier'] = False
        self.reject(snap)
        for phase in ('submission', 'resolution'):
            snap = g.snapshot()
            state = self.proofs(snap)[0]['fields'][phase]['fields']['state']['state']
            carrier = next(e for e in state['entities'].values() if e['card_id'] == 'cond.plain')
            carrier['abilities'] = [a for a in carrier['abilities'] if a['kind'] != 'spell_repeat']
            self.reject(snap)
        self.portable(g)
        self.choose(g, 'ok')
        self.assertEqual(self.armor(g), 2)

    def test_removed_false_source_still_binds_same_identity_between_original_windows(self):
        g = self.game(hand=('false.remove.source',), board=('cond.plain',))
        self.play(g, 'false.remove.source')
        self.assertEqual((self.subject(g).spell_payload.casts, self.subject(g).spell_payload.contributors), (1, ()))
        self.assertFalse(any(a.kind == 'spell_repeat' for a in self.entity(g, 'cond.plain').abilities))
        self.portable(g)
        for phase in ('submission', 'resolution'):
            snap = g.snapshot()
            state = self.proofs(snap)[0]['fields'][phase]['fields']['state']['state']
            carrier = next(e for e in state['entities'].values() if e['card_id'] == 'cond.plain')
            carrier['abilities'][0]['spell_repeat']['match']['source_eligibility']['exclude_carrier'] = False
            self.reject(snap)
        self.choose(g, 'ok')
        self.portable(g)

    def test_first_last_and_finish_play_tail_wait_keep_original_truth_and_proof(self):
        g = self.game(hand=('ask.arcane',), board=('cond.plain', 'dragon', 'tail.wait'))
        self.play(g, 'ask.arcane')
        for armor, completed in ((0, False), (2, False), (4, True)):
            self.assertEqual((self.armor(g), self.subject(g).completed), (armor, completed))
            self.assertEqual(len(self.proofs(g.snapshot())), 1)
            self.assertFalse(self.subject(g).spell_acceptance_closed)
            self.portable(g)
            self.choose(g, 'ok')
        self.assertTrue(self.subject(g).spell_acceptance_closed)
        self.portable(g)

    def test_nested_new_paid_roots_recompute_true_false_without_parent_reclassification(self):
        for watch, witnesses, quotas in (('nested.add', (), [1, 2]),
                                         ('nested.remove', ('dragon',), [2, 1])):
            with self.subTest(watch=watch):
                g = self.game(hand=('arcane', 'inner.arcane'), board=('cond.plain', watch, *witnesses))
                self.play(g, 'arcane'); self.portable(g)
                self.choose(g, 'nested')
                self.assertEqual([p.spell_payload.casts for p in g.state.play_history], quotas)
                self.assertEqual(g.snapshot()['resolution_frame']['fields']['spell_acceptances'], {'tuple': [2, 1]})
                self.assertEqual(len(self.proofs(g.snapshot())), 2)
                self.portable(g)
                snap = g.snapshot()
                proofs = self.proofs(snap)
                proofs[0]['fields']['resolution'], proofs[1]['fields']['resolution'] = (
                    proofs[1]['fields']['resolution'], proofs[0]['fields']['resolution'])
                self.reject(snap)
                self.finish_choices(g)
                self.assertEqual((self.armor(g), g.state.players[1].mana), (6, 8))
                self.assertTrue(all(p.spell_acceptance_closed for p in g.state.play_history))
                self.portable(g)

    def test_doomed_witness_inside_outer_repeat_is_qualified_by_inner_profile(self):
        for source, inner_count in (('cond.plain', 2), ('cond.active', 1)):
            with self.subTest(source=source):
                g = self.game(hand=('kill.nested', 'inner.ask'), board=(source, 'dragon'))
                self.play(g, 'kill.nested')
                self.portable(g)
                self.choose(g, 'nested')
                self.assertEqual([p.spell_payload.casts for p in g.state.play_history], [2, inner_count])
                witness = self.entity(g, 'dragon')
                self.assertTrue(witness.doomed)
                self.assertFalse(g.state.death_history)
                self.assertEqual(g.snapshot()['resolution_frame']['fields']['spell_acceptances'], {'tuple': [2, 1]})
                self.portable(g)
                while g.state.pending_choice:
                    self.choose(g, 'ok')
                    self.portable(g)
                self.assertEqual((self.armor(g), len(g.state.death_history)), (4 + inner_count * 2, 1))

    def test_nonmatching_recipient_still_validates_every_required_witness_before_intersection(self):
        for cid in ('fire', 'schoolless'):
            g = self.game(hand=(cid,), board=('cond.plain', 'unknowntribes'))
            before = g.snapshot()
            # Public reads and legal operation enumeration do not execute the
            # later source condition; failure belongs to actual resolution.
            self.assertTrue(any(a.entity_id == g.state.players[1].hand[0]
                for a in g.legal_actions() if isinstance(a, PlayCard)))
            g.observe(1); g.observe(2)
            self.assertEqual(g.snapshot(), before)
            with self.assertRaises(ResolutionError): self.play(g, cid)
            self.assertEqual(g.snapshot(), before)
        g = self.game(hand=('fire', 'schoolless'), board=('cond.plain', 'dragon'))
        for cid in ('fire', 'schoolless'):
            self.play(g, cid)
            self.assertEqual((self.subject(g).spell_payload.casts, self.subject(g).spell_payload.contributors), (1, ()))
        self.assertEqual(self.armor(g), 4)
        self.portable(g)

    def test_all_false_post_finish_ledger_and_unique_tail_cannot_be_cut_or_duplicated(self):
        g = self.game(hand=('empty.arcane',), board=('cond.plain', 'tail.wait'))
        self.play(g, 'empty.arcane')
        self.assertTrue(self.subject(g).completed)
        self.assertEqual(g.snapshot()['resolution_frame']['fields']['spell_acceptances'], {'tuple': [1]})
        for mutation in ('ledger.delete', 'ledger.empty', 'proof.duplicate', 'closed.cut'):
            snap = g.snapshot()
            frame = snap['resolution_frame']['fields']
            if mutation == 'ledger.delete': del frame['spell_acceptances']
            elif mutation == 'ledger.empty': frame['spell_acceptances']['tuple'] = []
            elif mutation == 'proof.duplicate': self.work(snap)[-1].append(copy.deepcopy(self.proofs(snap)[0]))
            else:
                snap['state']['play_history'][-1]['spell_acceptance_closed'] = True
                self.delete_proofs(snap)
            self.reject(snap)
        self.portable(g)

    def test_unknown_profile_rejected_in_live_original_death_and_rewind_saved_states(self):
        snapshots = []
        g = self.game(hand=('ask.arcane',), board=('cond.plain', 'dragon'))
        self.play(g, 'ask.arcane'); snapshots.append(('waiting', g.snapshot()))
        g = self.game(hand=('kill',), board=('cond.plain', 'dragon'))
        self.play(g, 'kill', self.entity(g, 'cond.plain').id)
        self.assertTrue(g.state.death_history)
        snapshots.append(('dead', g.snapshot()))
        g = self.game(hand=('ordinary.rewind',), board=('cond.plain',))
        self.play(g, 'ordinary.rewind')
        self.assertIsNotNone(g.snapshot()['rewind_session'])
        snapshots.append(('rewind', g.snapshot()))
        for phase, snapshot in snapshots:
            conditions = [n for n in self.nodes(snapshot)
                if set(n) == {'profile_id', 'tribes_any', 'exclude_carrier'}]
            self.assertTrue(conditions, phase)
            for index in range(len(conditions)):
                with self.subTest(phase=phase, index=index):
                    corrupted = copy.deepcopy(snapshot)
                    candidates = [n for n in self.nodes(corrupted)
                        if set(n) == {'profile_id', 'tribes_any', 'exclude_carrier'}]
                    candidates[index]['profile_id'] = 'missing.saved.profile'
                    self.reject(corrupted)

    def test_ordinary_rewind_rechecks_random_changed_original_late_truth(self):
        g = self.game(hand=('random.rewind',),
            board=('cond.plain', 'dragon', 'emptytribes', 'commit.random'))
        original_rng = g.snapshot()['rng_state']
        self.play(g, 'random.rewind')
        self.assertEqual((self.armor(g), self.subject(g).spell_payload.casts), (2, 2))
        after_first_rng = g.snapshot()['rng_state']
        self.assertNotEqual(original_rng, after_first_rng)
        for expected in (2, 2, 1):
            self.portable(g)
            self.choose(g, 'retry')
            self.assertEqual((self.armor(g), self.subject(g).spell_payload.casts), (expected, expected))
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].mana, 9)
        self.assertNotEqual(after_first_rng, g.snapshot()['rng_state'])
        self.portable(g)

    def test_accepted_carrier_transfer_and_witness_changes_are_legal_but_identity_edits_are_not(self):
        # The witness may change without modifying the original immutable quota.
        for change in ('steal', 'transform', 'bounce'):
            g = self.game(hand=('ask.arcane', change), board=('cond.plain', 'dragon'))
            self.play(g, 'ask.arcane')
            self.finish_choices(g)
            accepted = self.subject(g)
            self.play(g, change, self.entity(g, 'dragon').id)
            self.assertEqual(execution_count(Resolution(g), accepted), 2)
            self.portable(g)
        g = self.game(hand=('grant.donor', 'ask.arcane'), board=('carrier',))
        self.play(g, 'grant.donor'); self.play(g, 'ask.arcane')
        snap = g.snapshot()
        contributor = snap['state']['play_history'][-1]['spell_payload']['contributors'][0]
        contributor['ability']['source_id'] = contributor['carrier_id']
        self.reject(snap)
        self.portable(g)

    def test_accepted_carrier_silence_transfer_transform_and_bounce_do_not_cancel_extras(self):
        for effect in ('steal', 'transform', 'bounce', 'silence'):
            with self.subTest(effect=effect):
                g = self.game(hand=('ask.source.' + effect, 'arcane'), board=('cond.plain', 'dragon'))
                self.play(g, 'ask.source.' + effect)
                self.portable(g)
                self.choose(g, 'ok')
                self.assertIsNotNone(g.state.pending_choice)
                self.assertEqual(self.subject(g).spell_payload.casts, 2)
                self.portable(g)
                self.choose(g, 'ok')
                self.assertEqual(self.armor(g), 4)
                self.portable(g)
                self.play(g, 'arcane')
                self.assertEqual((self.armor(g), self.subject(g).spell_payload.casts), (6, 1))
                self.portable(g)

    def test_private_source_field_never_leaks_or_mutates_through_player_projection(self):
        g = self.game(hand=('policy', 'ask.arcane'), board=('cond.plain', 'dragon'))
        self.play(g, 'policy'); self.play(g, 'ask.arcane')
        before = g.snapshot()
        for viewer in (1, 2):
            view = g.observe(viewer)
            match = view['players'][0]['spell_modifiers'][0]['match']
            self.assertEqual(set(match), {'recipient_metadata', 'recipient_cost'})
            match['recipient_metadata']['spell_schools'].append('fire')
            match['source_eligibility'] = {'profile_id': 'forged'}
            self.assertEqual(g.snapshot(), before)
            self.assertNotIn('source_eligibility', json.dumps(g.observe(viewer)))
        self.portable(g)

    def test_source_condition_private_wire_fields_are_strict_and_public_wire_stays_separate(self):
        encoded = repeat_match_to_dict(self.spec().match)
        self.assertEqual(set(encoded), {'recipient_metadata', 'source_eligibility', 'recipient_cost'})
        self.assertEqual(repeat_match_from_dict(encoded), self.spec().match)
        for field in ('recipient_metadata', 'source_eligibility'):
            bad = copy.deepcopy(encoded); del bad[field]
            with self.assertRaises(ValueError): repeat_match_from_dict(bad)
        for field in ('profile_id', 'tribes_any', 'exclude_carrier'):
            bad = copy.deepcopy(encoded); del bad['source_eligibility'][field]
            with self.assertRaises(ValueError): repeat_match_from_dict(bad)
        for change in (dict(exclude_carrier=1), dict(tribes_any=['dragon', 'dragon']),
                       dict(tribes_any='dragon'), dict(profile_id=''), dict(extra=True)):
            bad = copy.deepcopy(encoded); bad['source_eligibility'].update(change)
            with self.assertRaises(ValueError): repeat_match_from_dict(bad)
        public = dict(casts=2, class_mode='any', match={'recipient_metadata': encoded['recipient_metadata'], 'recipient_cost': None},
                      uses_remaining=1, expires_turn=None)
        validate_spell_modifier_view(public, 'spell_modifier_added')
        public['match']['source_eligibility'] = None
        with self.assertRaises(ValueError): validate_spell_modifier_view(public, 'spell_modifier_added')

    def test_invalid_types_profiles_and_unsupported_consumers_fail_explicitly(self):
        for kwargs in (dict(exclude_carrier=1), dict(tribes_any=['dragon']),
                       dict(tribes_any=('dragon', 'dragon')), dict(profile_id='')):
            with self.assertRaises(ValueError): RepeatSourceEligibility(**{'profile_id': 'x', **kwargs})
        for kwargs in (dict(id=''), dict(id='x', basis='live'), dict(id='x', include_dormant=1)):
            with self.assertRaises(ValueError): RepeatWitnessProfile(**kwargs)
        with self.assertRaises(ValueError): RepeatMatchSpec(source_eligibility={})
        with self.assertRaises(ValueError): AddSpellRepeatModifier(1, self.spec())
        with self.assertRaises(ValueError): SpellRepeatModifier(1, self.spec(), None, None, 1)
        with self.assertRaises(ValueError): AbilityInstance(1, 'card_spell_repeat', spell_repeat=self.spec())
        with self.assertRaises(ValueError): validate_source_declaration(self.r, self.spec(), allow_source=False)
        with self.assertRaises(ValueError): self.minion('bad.profile', health=4,
            spell_repeats=(self.spec(profile='missing.profile'),))
        g = self.game(hand=('grant.unknown',), board=())
        before = g.snapshot()
        with self.assertRaises((ValueError, ResolutionError)): self.play(g, 'grant.unknown')
        self.assertEqual(g.snapshot(), before)

    def test_same_profile_id_changed_policy_changes_fingerprint_and_duplicate_frozen_registration_rejects(self):
        fresh = self.fresh_registry()
        self.assertEqual(self.r.fingerprint(), fresh.fingerprint())
        with self.assertRaises(ValueError): self.r.register_repeat_witness_profile(
            RepeatWitnessProfile('test.presence.include'))
        case = type(self)()
        case.presence_include_dormant = False
        case.setUp()
        different = case.r
        self.assertNotEqual(self.r.fingerprint(), different.fingerprint())
        g = self.game(hand=('ask.arcane',), board=('cond.plain', 'dragon'))
        self.play(g, 'ask.arcane')
        with self.assertRaises(SnapshotError): Game.from_snapshot(g.snapshot(), different)
        with self.assertRaises(ValueError): g.registry.register_repeat_witness_profile(RepeatWitnessProfile('too.late'))
        self.portable(g)

    def test_snapshot_condition_declaration_and_attachment_identity_cannot_be_forged(self):
        g = self.game(hand=('ask.arcane',), board=('cond.plain', 'dragon', 'carrier'))
        self.play(g, 'ask.arcane')
        self.assertEqual(g.snapshot()['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        old = g.snapshot(); old['schema_version'] = 101; self.reject(old)
        for field, value in (('profile_id', 'repeat.witness.active_live'),
                             ('tribes_any', ['beast']), ('exclude_carrier', False)):
            snap = g.snapshot()
            contributor = snap['state']['play_history'][-1]['spell_payload']['contributors'][0]
            contributor['ability']['spell_repeat']['match']['source_eligibility'][field] = value
            self.reject(snap)
        for field in ('source_eligibility', 'recipient_metadata'):
            snap = g.snapshot()
            entity = next(e for e in snap['state']['entities'].values() if e['card_id'] == 'cond.plain')
            del entity['abilities'][0]['spell_repeat']['match'][field]
            self.reject(snap)
        snap = g.snapshot()
        src = next(e for e in snap['state']['entities'].values() if e['card_id'] == 'cond.plain')
        dst = next(e for e in snap['state']['entities'].values() if e['card_id'] == 'carrier')
        dst['abilities'].append(src['abilities'].pop())
        self.reject(snap)
        self.portable(g)

    def test_frame_codec_gates_unknown_profile_inside_every_supported_immutable_container(self):
        g = self.game(board=())
        codec = FrameCodec(g.mechanics, g.registry)
        good = self.spec()
        bad = self.spec(profile='unknown.frame.profile')
        for value in (bad.match.source_eligibility, bad.match, bad,
                      GrantSpellRepeatAura(999, bad),
                      AbilityInstance(999, 'spell_repeat', spell_repeat=bad)):
            with self.subTest(kind=type(value).__name__):
                # Encode/decode both enforce semantics, independent of a live holder.
                with self.assertRaises(ValueError): codec.decode(codec.encode(value))
        mismatch = replace(g.registry.repeat_witness_profile('repeat.witness.controlled'), include_dormant=False)
        with self.assertRaises(ValueError): codec.decode(codec.encode(mismatch))
        self.assertEqual(codec.decode(codec.encode(good)), good)

    def test_execution_count_respects_explicit_submission_and_closed_late_window(self):
        g = self.game(hand=('arcane',), board=('cond.plain', 'dragon', 'commit.wait'))
        self.play(g, 'arcane')
        p = self.subject(g)
        self.assertIsNotNone(p.spell_submission)
        self.assertEqual(p.spell_submission.modifiers, ())
        before = g.snapshot()
        for candidate in (p, replace(p, spell_submission=None)):
            with self.assertRaises((ResolutionError, ValueError)):
                execution_count(Resolution(g), candidate)
            self.assertEqual(g.snapshot(), before)
        self.choose(g, 'ok')
        self.assertEqual(execution_count(Resolution(g), self.subject(g)), 2)
        self.portable(g)

    def test_redirect_changes_only_accepted_target_and_counter_never_queries_unknown_witness(self):
        g = self.game(hand=('setup.redirect', 'hit.arcane'), board=('cond.plain', 'dragon'),
            enemy=('plain',))
        self.play(g, 'setup.redirect')
        original = self.entity(g, 'plain', 2).id
        self.play(g, 'hit.arcane', original)
        p = self.subject(g)
        self.assertEqual((p.card_id, p.target_id, p.spell_payload.casts), ('hit.arcane', original, 2))
        self.assertNotEqual(p.spell_payload.target_id, original)
        self.assertEqual(self.entity(g, 'plain', 2).health, 8)
        self.assertEqual({c.target_id for c in self.casts(g)}, {p.spell_payload.target_id})
        self.portable(g)
        g = self.game(hand=('setup.counter', 'arcane'), board=('cond.plain', 'unknowntribes', 'tail.wait'))
        self.play(g, 'setup.counter'); self.play(g, 'arcane')
        self.assertTrue(self.subject(g).countered)
        self.assertIsNone(self.subject(g).spell_payload)
        before = g.snapshot()
        with self.assertRaises(ResolutionError): execution_count(Resolution(g), self.subject(g))
        self.assertEqual(g.snapshot(), before)
        self.portable(g)

    def test_ordinary_rewind_recaptures_truth_but_retained_outcomes_hold_plan(self):
        g = self.game(hand=('ordinary.rewind',), board=('cond.plain',))
        self.play(g, 'ordinary.rewind')
        self.assertEqual((self.armor(g), self.subject(g).spell_payload.casts), (1, 1))
        self.portable(g)
        self.choose(g, 'retry')
        self.assertEqual((self.armor(g), self.subject(g).spell_payload.casts), (2, 1))
        self.assertEqual(len([i for i in g.state.players[1].board if g.state.entities[i].card_id == 'dragon']), 1)
        self.portable(g)
        g = self.game(hand=('retained.rewind',), board=('cond.plain', 'dragon', 'retainer'))
        self.play(g, 'retained.rewind')
        for expected_armor in (0, 2, 4, 6):
            self.assertEqual(self.armor(g), expected_armor)
            self.assertEqual(self.subject(g).spell_payload.casts, 2)
            self.portable(g)
            self.choose(g, 'ok')
        self.assertEqual(self.armor(g), 8)
        self.assertEqual(self.subject(g).spell_payload.casts, 2)
        self.portable(g)

    def test_budget_and_mid_body_failure_roll_back_all_query_proof_rng_and_resources(self):
        for cid, board in (('arcane', ('huge.conditional', 'dragon')),
                            ('fail.random', ('cond.plain', 'dragon'))):
            g = self.game(hand=(cid,), board=board)
            before = g.snapshot()
            with self.assertRaises((ResolutionError, ResolutionLimitExceeded)):
                self.play(g, cid)
            self.assertEqual(g.snapshot(), before)

    def test_terminal_before_or_after_board_acceptance_keeps_existing_interruption_policy(self):
        for cid, board, accepted in (('arcane', ('cond.plain', 'dragon', 'commit.fatal'), False),
                                    ('fatal.arcane', ('cond.plain', 'dragon'), True)):
            g = self.game(hand=(cid,), board=board)
            self.play(g, cid)
            self.assertEqual(g.state.status, 'finished')
            self.assertEqual(self.subject(g).spell_payload is not None, accepted)
            self.assertTrue(self.subject(g).interrupted)
            self.assertIsNone(g.snapshot()['resolution_frame'])
            self.portable(g)

    def test_all_public_modifier_events_and_two_seat_views_keep_old_match_shape(self):
        g = self.game(hand=('policy', 'arcane', 'remove.policy', 'expire.policy', 'ask.arcane'),
            board=('cond.plain', 'dragon'), enemy_hand=('unknownmeta',))
        self.play(g, 'policy'); self.play(g, 'arcane'); self.play(g, 'remove.policy')
        self.play(g, 'expire.policy'); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.play(g, 'ask.arcane')
        forbidden = ('source_eligibility', 'spell_submission', 'spell_payload', 'resolution_frame',
                     'spell_acceptances', 'spell_policy_receipts', 'policy_source_id', 'modifier_id',
                     'carrier_id', 'witnesses', 'behavior_ids', 'rng_state')
        for seat in (1, 2):
            view = g.observe(seat)
            self.assertEqual(view['version'], 'player-view-v86')
            rows = [e for e in g.player_events(seat) if e['kind'].startswith('spell_modifier_')]
            self.assertEqual({e['kind'] for e in rows}, {'spell_modifier_added', 'spell_modifier_used',
                'spell_modifier_removed', 'spell_modifier_expired'})
            for row in rows:
                self.assertEqual(set(row['spell_modifier']['match']), {'recipient_metadata', 'recipient_cost'})
                validate_spell_modifier_view(row['spell_modifier'], row['kind'])
            encoded = json.dumps([view, rows])
            for key in forbidden: self.assertNotIn('"' + key + '"', encoded)
        self.assertNotIn('unknownmeta', json.dumps(g.observe(1)))
        self.portable(g)


if __name__ == '__main__':
    unittest.main()
