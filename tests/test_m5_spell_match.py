"""A1 school/class matching at the two existing manual-spell windows."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import copy
import json
import unittest

import test_m5_spell_repeats as foundation
from hs_sim.engine import (CardDefinition, CardMetadata, CardClass, CardType, Game,
    Keyword, RewindSpec, ResolutionError, SnapshotError, SpellRepeatSpec,
    SpellSchool, TriggerSpec, GrantSpellRepeatAura)
from hs_sim.engine.model import RecipientMetadataFilter, RepeatMatchSpec
from hs_sim.engine.effects import (GainArmor, RequestChoice, ChoiceOption, Summon,
    Silence, Destroy, ChangeControl, ReturnToHand, ReplaceHero, Damage)
from hs_sim.engine.spell_modifiers import AddSpellRepeatModifier, RemoveSpellRepeatModifier
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
# Public expected parameters remain an explicit v52 literal.
from hs_sim.engine.resolver import PlayFromHand
from hs_sim.engine import PlayCard


class SpellMatchTests(unittest.TestCase):
    minion = foundation.SpellRepeatTests.minion
    spell = foundation.SpellRepeatTests.spell
    game = foundation.SpellRepeatTests.game
    play = foundation.SpellRepeatTests.play
    hero = foundation.SpellRepeatTests.hero
    choose = foundation.SpellRepeatTests.choose
    events = foundation.SpellRepeatTests.events

    @staticmethod
    def spec(casts=2, mode='any', schools=(SpellSchool.ARCANE,)):
        return SpellRepeatSpec(casts, mode, RepeatMatchSpec(
            RecipientMetadataFilter(spell_schools=schools)))

    def setUp(self):
        foundation.SpellRepeatTests.setUp(self)
        for cid, school, cls in (
                ('arcane', SpellSchool.ARCANE, CardClass.MAGE),
                ('fire', SpellSchool.FIRE, CardClass.MAGE),
                ('schoolless', None, CardClass.MAGE),
                ('neutral.arcane', SpellSchool.ARCANE, CardClass.NEUTRAL),
                ('same.arcane', SpellSchool.ARCANE, CardClass.WARRIOR),
                ('shared.arcane', SpellSchool.ARCANE, (CardClass.MAGE, CardClass.WARRIOR)),
                ('unknown.arcane', SpellSchool.ARCANE, None)):
            self.spell(cid, lambda c: [GainArmor(c.player_id, 2)], cost=1,
                spell_school=school, cls=cls)
        for mode in ('any', 'other'):
            for casts in (2, 3):
                self.minion(f'board.{mode}.{casts}', health=5,
                    spell_repeats=(self.spec(casts, mode),))
            self.granter(f'grant.{mode}', self.spec(mode=mode), uses=2)
        self.minion('board.fire.5', health=5,
            spell_repeats=(self.spec(5, schools=(SpellSchool.FIRE,)),))
        self.minion('board.union', health=5,
            spell_repeats=(self.spec(schools=(SpellSchool.ARCANE, SpellSchool.FIRE)),))
        self.minion('retainer', health=5, retain_rewind_outcomes=True)
        self.minion('carrier', health=5)
        self.granter('grant.once', self.spec(), uses=1)
        self.granter('grant.counter', self.spec(), uses=2, extra=(SetSecret(2, 'EX1_287'),))
        self.granter('grant.redirect', self.spec(), uses=2, extra=(SetSecret(2, 'tt_010'),))
        self.r.register_behavior('grant.aura', lambda c: [GrantSpellRepeatAura(
            next(i for i in c.state.players[1].board if c.state.entities[i].card_id == 'carrier'),
            self.spec(), c.source_id)])
        self.minion('grant.aura', health=4, battlecry='grant.aura')
        self.spell('ask.arcane', self.ask, cost=1, spell_school=SpellSchool.ARCANE)
        self.spell('ask.fire', self.ask, cost=1, spell_school=SpellSchool.FIRE)
        self.spell('inner.arcane', lambda c: [GainArmor(c.player_id, 1)],
            cost=1, spell_school=SpellSchool.ARCANE)
        self.spell('noop.arcane', lambda c: [], cost=1, spell_school=SpellSchool.ARCANE)
        self.r.register_card(CardDefinition('empty.arcane', 'empty.arcane', CardType.SPELL,
            cost=1, metadata=CardMetadata(False, (CardClass.MAGE,), None),
            spell_school=SpellSchool.ARCANE))
        self.spell('memo.arcane', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('ok', 'OK', (GainArmor(c.player_id,
                c.state.entities[c.state.players[c.player_id].hero_id].armor + 1),)),),
            source_id=c.source_id, repeat_key='scale')], cost=1, spell_school=SpellSchool.ARCANE)
        self.spell('death.arcane', lambda c: [Destroy(c.state.players[1].board[0]),
            *self.ask(c)], cost=1, spell_school=SpellSchool.ARCANE)
        self.spell('hit.arcane', lambda c: [Damage(c.target_id, 2, c.source_id)],
            cost=1, requires_target=True, spell_school=SpellSchool.ARCANE)
        self.spell('rewind.arcane', lambda c: [GainArmor(c.player_id, c.rewind_attempt + 1)],
            cost=1, spell_school=SpellSchool.ARCANE,
            keywords=(Keyword.REWIND,), rewind=RewindSpec(1))
        self.spell('retained.ask', self.ask, cost=1, spell_school=SpellSchool.ARCANE,
            keywords=(Keyword.REWIND,), rewind=RewindSpec(1))
        self.spell('fatal.arcane', lambda c: [Damage(c.state.players[2].hero_id, 50, c.source_id)],
            cost=1, spell_school=SpellSchool.ARCANE)
        self.watch('commit.wait', 'card_committed', lambda c: [self.pause(c)])
        self.watch('tail.wait', 'card_played', lambda c: [self.pause(c)])
        self.watch('tail.fatal', 'card_played', lambda c: [Damage(c.state.players[2].hero_id, 50, c.source_id)])
        self.watch('nested.wait', 'card_played', self.nested_wait)
        self.watch('commit.add', 'card_committed', lambda c: [Summon(1, 'board.any.3')])
        self.watch('commit.remove', 'card_committed', lambda c: [Silence(i)
            for i in c.state.players[1].board if c.state.entities[i].card_id == 'board.any.3'])
        self.watch('commit.policy.remove', 'card_committed', lambda c: [RemoveSpellRepeatModifier(1, m.id)
            for m in c.state.players[1].spell_modifiers])
        self.watch('commit.class', 'card_committed', lambda c: [ReplaceHero(1, 'HERO_08')])
        self.watch('commit.fatal', 'card_committed', lambda c: [Damage(c.state.players[2].hero_id, 50, c.source_id)])
        for cid, effect in (('silence', Silence), ('destroy', Destroy),
                ('bounce', ReturnToHand), ('steal', lambda i: ChangeControl(i, 2))):
            self.spell(f'ask.{cid}', lambda c, effect=effect: [RequestChoice(c.player_id,
                (ChoiceOption('ok', 'OK', (effect(c.play.spell_payload.contributors[0].carrier_id),
                    GainArmor(c.player_id, 2))),),
                source_id=c.source_id)], cost=1, spell_school=SpellSchool.ARCANE)

    def granter(self, cid, spec, *, uses=None, extra=()):
        self.r.register_behavior(cid, lambda c: [
            *([AddSpellRepeatModifier(1, spec, c.source_id, uses)] if spec is not None else []),
            *extra])
        self.minion(cid, health=4, battlecry=cid)

    def watch(self, cid, event, fn):
        self.r.register_behavior(cid, lambda c: fn(c) if c.event.source_id and
            c.state.entities[c.event.source_id].kind == CardType.SPELL else [])
        self.minion(cid, health=4, triggers=(TriggerSpec(event, cid),))

    def pause(self, c):
        return RequestChoice(c.player_id, (ChoiceOption('ok', 'OK', ()),), source_id=c.source_id)

    def ask(self, c):
        return [RequestChoice(c.player_id, (ChoiceOption('ok', 'OK',
            (GainArmor(c.player_id, 2),)),), source_id=c.source_id)]

    def nested_wait(self, c):
        subject = c.state.entities[c.event.source_id].card_id
        if subject == 'arcane':
            inner = next(i for i in c.state.players[1].hand
                if c.state.entities[i].card_id == 'inner.arcane')
            return [RequestChoice(c.player_id, (ChoiceOption('nested', 'Play the inner spell',
                (PlayFromHand(PlayCard(1, inner)), self.pause(c))),), source_id=c.source_id)]
        return [self.pause(c)] if subject == 'inner.arcane' else []

    def ready(self, grant='grant.any', hand=('arcane',), board=(), **kw):
        g = self.game(hand=(grant, *hand), board=board, **kw)
        self.play(g, grant)
        return g

    def armor(self, g):
        return self.hero(g).armor

    def modifiers(self, g):
        return g.state.players[1].spell_modifiers

    def subject(self, g):
        return next(p for p in reversed(g.state.play_history) if p.kind == CardType.SPELL)

    def casts(self, g, play=None):
        play = play or self.subject(g)
        return [c for c in g.state.cast_history if c.play_id == play.id]

    def fresh_registry(self):
        case = type(self)()
        case.setUp()
        return case.r

    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        fresh = self.fresh_registry()
        restored = Game.from_snapshot(snap, fresh)
        self.assertEqual(restored.snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), fresh).snapshot(), snap)
        return restored

    def reject(self, snap):
        snap['state_hash'] = canonical_hash({k: v for k, v in snap.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(snap, self.fresh_registry())
        self.assertNotIn('digest mismatch', str(error.exception))

    def work(self, snap):
        frame = snap['resolution_frame']['fields']
        return [frame[key]['tuple'] for key in ('prefix', 'continuation')]

    @staticmethod
    def is_proof(node):
        return node.get('type', '').endswith('.FinishSpellAcceptance')

    def proofs(self, snap):
        return [node for q in self.work(snap) for node in q if self.is_proof(node)]

    def delete_proofs(self, snap):
        self.assertEqual(len(self.proofs(snap)), 1)
        for q in self.work(snap):
            q[:] = [node for node in q if not self.is_proof(node)]

    def live_board_ability(self, snap, cid='board.any.2'):
        entity = next(e for e in snap['state']['entities'].values() if e['card_id'] == cid)
        return entity, next(a for a in entity['abilities'] if a['kind'] == 'spell_repeat')

    def test_school_and_class_intersection_consumes_only_matching_player_policy(self):
        for mode in ('any', 'other'):
            for subject in ('arcane', 'fire', 'schoolless', 'same.arcane', 'neutral.arcane', 'shared.arcane'):
                with self.subTest(mode=mode, subject=subject):
                    g = self.ready(f'grant.{mode}', hand=(subject,))
                    self.play(g, subject)
                    matched = subject == 'arcane' or mode == 'any' and subject.endswith('.arcane')
                    self.assertEqual((self.armor(g), len(self.casts(g))), (4, 2) if matched else (2, 1))
                    self.assertEqual(self.modifiers(g)[0].uses_remaining, 1 if matched else 2)
                    p = self.subject(g)
                    self.assertEqual(len(p.spell_submission.modifiers), int(matched))
                    self.assertEqual(p.spell_payload.casts, 2 if matched else 1)
                    self.assertTrue(p.spell_acceptance_closed)
        g = self.ready('grant.other', hero='HERO_08')
        self.play(g, 'arcane')
        self.assertEqual((self.armor(g), self.modifiers(g)[0].uses_remaining), (2, 2))
        self.portable(g)

    def test_known_school_does_not_require_class_metadata_for_any_scope(self):
        g = self.ready(hand=('unknown.arcane',))
        self.play(g, 'unknown.arcane')
        self.assertEqual((self.armor(g), self.modifiers(g)[0].uses_remaining), (4, 1))
        self.portable(g)
        g = self.ready('grant.other', hand=('unknown.arcane',))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'unknown.arcane')
        self.assertEqual(g.snapshot(), before)

    def test_nonmatching_root_does_not_spend_use_even_when_final_totals_match(self):
        g = self.ready(hand=('fire', 'arcane', 'arcane'))
        trace = []
        for cid in ('fire', 'arcane', 'arcane'):
            self.play(g, cid)
            trace.append((self.armor(g), self.modifiers(g)[0].uses_remaining if self.modifiers(g) else None,
                len(self.casts(g)), g.state.players[1].mana))
        self.assertEqual(trace, [(2, 2, 1, 9), (6, 1, 2, 8), (10, None, 2, 7)])
        self.portable(g)

    def test_board_school_filter_and_max_preserve_complete_matching_sources(self):
        for subject in ('arcane', 'fire', 'schoolless'):
            with self.subTest(subject=subject):
                g = self.game(hand=(subject,), board=('board.any.2', 'board.any.3', 'board.fire.5'))
                self.play(g, subject)
                expected = {'arcane': (6, 3, 2), 'fire': (10, 5, 1), 'schoolless': (2, 1, 0)}[subject]
                p = self.subject(g)
                self.assertEqual((self.armor(g), p.spell_payload.casts, len(p.spell_payload.contributors)), expected)
                self.assertEqual(p.spell_submission.modifiers, ())
                self.portable(g)

    def test_school_union_is_parameterized_and_schoolless_is_explicitly_unmatched(self):
        for subject in ('arcane', 'fire', 'schoolless'):
            with self.subTest(subject=subject):
                g = self.game(hand=(subject,), board=('board.union',))
                self.play(g, subject)
                self.assertEqual(self.armor(g), 2 if subject == 'schoolless' else 4)
        self.portable(g)

    def test_submission_and_late_board_window_stay_distinct(self):
        for subject, board, expected in (
                ('arcane', ('commit.add',), (6, 3, 1)),
                ('arcane', ('commit.remove', 'board.any.3'), (4, 2, 1)),
                ('fire', ('commit.add',), (2, 1, 2))):
            with self.subTest(subject=subject, board=board):
                g = self.ready(hand=(subject,), board=board)
                self.play(g, subject)
                self.assertEqual((self.armor(g), len(self.casts(g)), self.modifiers(g)[0].uses_remaining), expected)
                self.portable(g)

    def test_removed_submission_source_keeps_accepted_policy(self):
        g = self.ready(board=('commit.policy.remove',))
        self.play(g, 'arcane')
        self.assertEqual(self.armor(g), 4)
        self.assertFalse(self.modifiers(g))
        self.assertEqual(len(self.subject(g).spell_submission.modifiers), 1)
        self.portable(g)

    def test_class_uses_each_window_without_recapturing_submission(self):
        g = self.ready('grant.other', board=('board.other.3', 'commit.class'))
        self.play(g, 'arcane')
        p = self.subject(g)
        self.assertEqual((p.spell_submission.hero_class, p.spell_payload.hero_class),
            (CardClass.WARRIOR, CardClass.MAGE))
        self.assertEqual((self.armor(g), p.spell_payload.casts, p.spell_payload.contributors), (4, 2, ()))
        self.portable(g)

    def test_commit_wait_keeps_submission_and_does_not_accept_board_early(self):
        g = self.ready(hand=('arcane',), board=('commit.wait', 'board.any.3'))
        self.play(g, 'arcane')
        p = self.subject(g)
        self.assertEqual(self.modifiers(g)[0].uses_remaining, 1)
        self.assertIsNotNone(p.spell_submission)
        self.assertIsNone(p.spell_payload)
        self.assertFalse(p.spell_acceptance_closed)
        self.assertFalse(self.casts(g))
        self.assertFalse(g.state.spell_repeats)
        proof = self.proofs(g.snapshot())[0]
        self.assertIsNone(proof['fields']['resolution'])
        restored = self.portable(g)
        for branch in (g, restored):
            self.choose(branch, 'ok')
            self.assertEqual((self.armor(branch), len(self.casts(branch))), (6, 3))
        self.assertEqual(g.snapshot(), restored.snapshot())

    def test_first_last_and_completed_play_tail_all_restore_and_replay(self):
        g = self.game(hand=('ask.arcane',), board=('board.any.2', 'tail.wait'))
        self.play(g, 'ask.arcane')
        for armor, completed, cast_count in ((0, False, 1), (2, False, 2), (4, True, 2)):
            self.assertEqual((self.armor(g), self.subject(g).completed, len(self.casts(g))),
                (armor, completed, cast_count))
            self.assertFalse(self.subject(g).spell_acceptance_closed)
            self.assertEqual(len(self.proofs(g.snapshot())), 1)
            restored = self.portable(g)
            self.choose(g, 'ok')
            self.choose(restored, 'ok')
            self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertIsNone(g.state.pending_choice)
        self.assertTrue(self.subject(g).spell_acceptance_closed)
        self.assertEqual((self.armor(g), g.state.players[1].mana), (4, 9))
        self.portable(g)

    def test_accepted_board_plan_survives_public_source_lifecycle_changes(self):
        for effect in ('silence', 'destroy', 'bounce', 'steal'):
            with self.subTest(effect=effect):
                g = self.game(hand=(f'ask.{effect}',), board=('board.any.2',))
                self.play(g, f'ask.{effect}')
                self.portable(g)
                self.choose(g, 'ok')
                self.assertIsNotNone(g.state.pending_choice)
                self.portable(g)
                self.choose(g, 'ok')
                self.assertEqual((self.armor(g), len(self.casts(g))), (4, 2))
                self.portable(g)

    def test_granted_aura_uses_carrier_and_keeps_donor_provenance(self):
        g = self.ready('grant.aura', hand=('ask.arcane',), board=('carrier',))
        self.play(g, 'ask.arcane')
        source = self.subject(g).spell_payload.contributors[0]
        self.assertEqual(g.state.entities[source.carrier_id].card_id, 'carrier')
        self.assertEqual(g.state.entities[source.ability.source_id].card_id, 'grant.aura')
        self.assertNotEqual(source.carrier_id, source.ability.source_id)
        self.portable(g)
        self.choose(g, 'ok'); self.choose(g, 'ok')
        self.assertEqual(self.armor(g), 4)
        self.portable(g)

    def test_unit_noop_and_true_empty_have_explicit_late_acceptance(self):
        for cid, board, count, behaviors in (
                ('ask.fire', ('board.any.2',), 1, ('ask.fire',)),
                ('noop.arcane', ('board.any.2', 'tail.wait'), 2, ('noop.arcane',)),
                ('empty.arcane', ('board.any.2', 'tail.wait'), 2, ()),
                ('empty.arcane', ('tail.wait',), 1, ())):
            with self.subTest(cid=cid, board=board):
                g = self.game(hand=(cid,), board=board)
                self.play(g, cid)
                p = self.subject(g)
                self.assertEqual((p.spell_payload.casts, p.spell_payload.behavior_ids), (count, behaviors))
                self.assertFalse(p.spell_acceptance_closed)
                self.portable(g)
                self.choose(g, 'ok')
                self.assertEqual((self.armor(g), len(self.casts(g))), (2 if cid == 'ask.fire' else 0, count))
                self.assertTrue(self.subject(g).spell_acceptance_closed)
                self.portable(g)

    def test_countered_school_match_consumes_submission_without_payload(self):
        for cid, uses in (('arcane', 1), ('fire', 2), ('unknown.arcane', 1)):
            with self.subTest(cid=cid):
                # A countered root never evaluates the board's class filter,
                # even when that late filter would need unknown class metadata.
                g = self.ready('grant.counter', hand=(cid,), board=('board.other.3', 'tail.wait'))
                self.play(g, cid)
                p = self.subject(g)
                self.assertTrue(p.countered)
                self.assertIsNone(p.spell_payload)
                self.assertEqual((self.armor(g), len(self.casts(g)), self.modifiers(g)[0].uses_remaining), (0, 1, uses))
                self.assertFalse(self.casts(g)[0].payload_started)
                self.assertEqual(self.casts(g)[0].failure, 'countered')
                self.assertIsNotNone(self.proofs(g.snapshot())[0]['fields']['resolution'])
                self.portable(g)
                self.choose(g, 'ok')
                self.assertTrue(self.subject(g).spell_acceptance_closed)
                self.portable(g)

    def test_target_redirection_is_accepted_once_and_shared_by_both_casts(self):
        g = self.ready('grant.redirect', hand=('hit.arcane',), enemy=('plain',))
        target = g.state.players[2].board[0]
        self.play(g, 'hit.arcane', target)
        p = self.subject(g)
        self.assertNotEqual(p.target_id, p.spell_payload.target_id)
        self.assertEqual(len(self.events(g, 'spell_redirected')), 1)
        self.assertEqual({c.target_id for c in self.casts(g)}, {p.spell_payload.target_id})
        self.assertEqual(g.state.entities[target].health, 8)
        self.portable(g)

    def test_choice_memo_reuses_branch_and_recomputes_effect_under_school_plan(self):
        g = self.game(hand=('memo.arcane',), board=('board.any.2',))
        self.play(g, 'memo.arcane')
        self.portable(g)
        self.choose(g, 'ok')
        self.assertEqual((self.armor(g), len(self.events(g, 'choice_requested'))), (3, 1))
        self.assertIsNone(g.state.pending_choice)
        self.portable(g)

    def test_death_deferral_keeps_doomed_source_through_second_wait(self):
        g = self.game(hand=('death.arcane',), board=('board.any.2',))
        self.play(g, 'death.arcane')
        self.assertTrue(g.state.entities[g.state.players[1].board[0]].doomed)
        self.assertFalse(g.state.death_history)
        self.portable(g)
        self.choose(g, 'ok')
        self.assertFalse(g.state.death_history)
        self.portable(g)
        self.choose(g, 'ok')
        self.assertEqual((self.armor(g), len(g.state.death_history)), (4, 1))
        self.portable(g)

    def test_ordinary_rewind_closes_attempt_before_offer_then_recaptures(self):
        g = self.ready(hand=('rewind.arcane',))
        self.play(g, 'rewind.arcane')
        self.assertEqual((self.armor(g), self.modifiers(g)[0].uses_remaining), (2, 1))
        self.assertTrue(self.subject(g).spell_acceptance_closed)
        self.assertFalse(self.proofs(g.snapshot()))
        self.portable(g)
        self.choose(g, 'retry')
        self.assertEqual((self.armor(g), self.modifiers(g)[0].uses_remaining), (4, 1))
        self.assertEqual(len(g.state.spell_policy_receipts), 1)
        self.assertTrue(self.subject(g).spell_acceptance_closed)
        self.portable(g)

    def test_retained_outcomes_keep_one_submission_proof_through_all_choices(self):
        g = self.ready(hand=('retained.ask',), board=('retainer', 'board.any.2'))
        self.play(g, 'retained.ask')
        for armor in (0, 2, 4, 6):
            self.assertEqual(self.armor(g), armor)
            self.assertFalse(self.subject(g).spell_acceptance_closed)
            self.assertEqual(len(self.proofs(g.snapshot())), 1)
            self.assertEqual(self.modifiers(g)[0].uses_remaining, 1)
            self.portable(g)
            self.choose(g, 'ok')
        self.assertEqual((self.armor(g), len(self.casts(g)), len(g.state.play_history)), (8, 2, 2))
        self.assertTrue(self.subject(g).spell_acceptance_closed)
        self.portable(g)

    def test_terminal_before_and_after_late_acceptance_do_not_require_live_tail(self):
        for cid, board, accepted in (('arcane', ('commit.fatal',), False),
                ('fatal.arcane', (), True)):
            with self.subTest(cid=cid):
                g = self.ready(hand=(cid,), board=board)
                self.play(g, cid)
                self.assertEqual(g.state.status, 'finished')
                self.assertEqual(self.modifiers(g)[0].uses_remaining, 1)
                self.assertEqual(self.subject(g).spell_payload is not None, accepted)
                self.assertTrue(self.subject(g).interrupted)
                self.assertIsNone(g.snapshot()['resolution_frame'])
                self.portable(g)

    def test_missing_or_duplicate_proof_is_rejected_at_each_real_wait_phase(self):
        for phase in ('commit', 'first', 'last', 'tail', 'unit', 'empty', 'counter'):
            with self.subTest(phase=phase):
                if phase == 'commit':
                    g = self.ready(hand=('arcane',), board=('commit.wait',))
                    self.play(g, 'arcane')
                elif phase == 'counter':
                    g = self.ready('grant.counter', board=('tail.wait',))
                    self.play(g, 'arcane')
                else:
                    cid = 'ask.fire' if phase == 'unit' else 'empty.arcane' if phase == 'empty' else 'ask.arcane'
                    g = self.game(hand=(cid,), board=('board.any.2', 'tail.wait'))
                    self.play(g, cid)
                    for _ in range({'last': 1, 'tail': 2}.get(phase, 0)):
                        self.choose(g, 'ok')
                self.portable(g)
                snap = g.snapshot(); self.delete_proofs(snap); self.reject(snap)
                snap = g.snapshot(); proof = copy.deepcopy(self.proofs(snap)[0])
                self.work(snap)[-1].append(proof); self.reject(snap)

    def test_empty_submission_still_requires_original_proof(self):
        g = self.ready(hand=('fire',), board=('commit.wait',))
        self.play(g, 'fire')
        self.assertEqual(self.subject(g).spell_submission.modifiers, ())
        self.assertEqual(self.modifiers(g)[0].uses_remaining, 2)
        snap = g.snapshot(); self.delete_proofs(snap); self.reject(snap)

    def test_acceptance_context_cannot_borrow_retained_attempt_or_another_submit_face(self):
        g = self.ready(hand=('ask.arcane',))
        self.play(g, 'ask.arcane')
        for phase in ('submission', 'resolution'):
            with self.subTest(phase=phase):
                snap = g.snapshot()
                context = self.proofs(snap)[0]['fields'][phase]['fields']
                context['rewind_attempt'] = 1
                self.reject(snap)
        snap = g.snapshot()
        context = self.proofs(snap)[0]['fields']['submission']['fields']
        context['target_id'] = self.hero(g, 2).id
        self.reject(snap)
        snap = g.snapshot()
        context = self.proofs(snap)[0]['fields']['submission']['fields']
        state = context['state']['state']
        source = state['entities'][str(context['source_id'])]
        source['card_id'] = 'fire'
        self.reject(snap)
        snap = g.snapshot()
        context = self.proofs(snap)[0]['fields']['submission']['fields']
        state = context['state']['state']
        source = state['entities'][str(context['source_id'])]
        state['players']['1']['hand'].remove(source['id'])
        state['players']['1']['graveyard'].append(source['id'])
        source['zone'] = 'graveyard'
        self.reject(snap)

    def test_full_acceptance_tail_cannot_precede_or_duplicate_finish_play(self):
        g = self.game(hand=('ask.arcane',), board=('board.any.2', 'tail.wait'))
        self.play(g, 'ask.arcane')
        snap = g.snapshot()
        queue = self.work(snap)[-1]
        finishers = [node for node in queue if node.get('type', '').endswith('.FinishPlay')]
        self.assertEqual(len(finishers), 1)
        queue.append(copy.deepcopy(finishers[0]))
        self.reject(snap)
        snap = g.snapshot()
        queue = self.work(snap)[-1]
        proof = self.proofs(snap)[0]
        queue.remove(proof); queue.insert(0, proof)
        self.reject(snap)
        self.choose(g, 'ok'); self.choose(g, 'ok')
        self.assertTrue(self.subject(g).completed)
        snap = g.snapshot()
        self.work(snap)[-1].append(copy.deepcopy(finishers[0]))
        self.reject(snap)
        self.portable(g)

    def test_frame_acceptance_ledger_is_mandatory_and_strict(self):
        g = self.game(hand=('ask.arcane',), board=('board.any.2',))
        self.play(g, 'ask.arcane')
        original = g.snapshot()['resolution_frame']['fields']['spell_acceptances']
        self.assertEqual(original, {'tuple': [self.subject(g).id]})
        for value in ({'tuple': [True]}, {'tuple': [0]}, {'tuple': [1, 1]},
                {'tuple': []}, True, [1]):
            with self.subTest(value=value):
                snap = g.snapshot()
                snap['resolution_frame']['fields']['spell_acceptances'] = value
                self.reject(snap)
        snap = g.snapshot()
        del snap['resolution_frame']['fields']['spell_acceptances']
        self.reject(snap)
        self.portable(g)

    def test_completed_tail_cannot_claim_closed_and_delete_all_proof(self):
        g = self.game(hand=('ask.arcane',), board=('board.any.2', 'tail.wait'))
        self.play(g, 'ask.arcane'); self.choose(g, 'ok'); self.choose(g, 'ok')
        self.assertTrue(self.subject(g).completed)
        self.assertFalse(self.subject(g).spell_acceptance_closed)
        snap = g.snapshot()
        self.assertEqual(snap['resolution_frame']['fields']['spell_acceptances'], {'tuple': [1]})
        snap['state']['play_history'][-1]['spell_acceptance_closed'] = True
        self.delete_proofs(snap)
        self.reject(snap)
        self.portable(g)

    def test_choice_can_nest_paid_spell_and_ledger_preserves_lifo_until_parent_closes(self):
        g = self.game(hand=('arcane', 'inner.arcane'), board=('board.any.2', 'nested.wait'))
        self.play(g, 'arcane')
        self.assertEqual(self.armor(g), 4)
        self.portable(g)
        self.choose(g, 'nested')
        self.assertEqual((self.armor(g), len(g.state.play_history), len(g.state.cast_history)), (6, 2, 4))
        self.assertEqual([p.action for p in g.state.play_history], [1, 2])
        self.assertEqual(g.snapshot()['resolution_frame']['fields']['spell_acceptances'], {'tuple': [2, 1]})
        self.assertTrue(all(p.completed and not p.spell_acceptance_closed for p in g.state.play_history))
        for also_swap_ledger in (False, True):
            snap = g.snapshot()
            queue = self.work(snap)[-1]
            indexes = [i for i, node in enumerate(queue) if self.is_proof(node)]
            self.assertEqual(len(indexes), 2)
            a, b = indexes
            queue[a], queue[b] = queue[b], queue[a]
            if also_swap_ledger:
                snap['resolution_frame']['fields']['spell_acceptances']['tuple'].reverse()
            self.reject(snap)
        restored = self.portable(g)
        for branch in (g, restored):
            self.choose(branch, 'ok')
            self.assertIsNotNone(branch.state.pending_choice)
            self.assertEqual(branch.snapshot()['resolution_frame']['fields']['spell_acceptances'], {'tuple': [1]})
            self.assertEqual([p.spell_acceptance_closed for p in branch.state.play_history], [False, True])
            self.portable(branch)
            self.choose(branch, 'ok')
            self.assertIsNone(branch.state.pending_choice)
            self.assertTrue(all(p.spell_acceptance_closed for p in branch.state.play_history))
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(g.state.players[1].mana, 8)
        self.portable(g)

    def test_source_match_and_full_ability_identity_cannot_change_under_original_proof(self):
        g = self.game(hand=('ask.arcane',), board=('board.any.2', 'carrier'))
        self.play(g, 'ask.arcane')
        changes = (
            lambda e, a, s: a['spell_repeat']['match']['recipient_metadata'].update(spell_schools=['arcane', 'fire']),
            lambda e, a, s: a.update(origin='granted'),
            lambda e, a, s: a.update(source_id=next(x['id'] for x in s['state']['entities'].values() if x['card_id'] == 'carrier')),
            lambda e, a, s: a.update(expires_turn=s['state']['turn'] + 1),
            lambda e, a, s: a.update(remove_on_silence=False),
        )
        for change in changes:
            snap = g.snapshot(); entity, ability = self.live_board_ability(snap)
            change(entity, ability, snap); self.reject(snap)
        snap = g.snapshot(); entity, ability = self.live_board_ability(snap)
        carrier = next(e for e in snap['state']['entities'].values() if e['card_id'] == 'carrier')
        entity['abilities'].remove(ability); carrier['abilities'].append(ability)
        self.reject(snap)

    def test_complete_late_source_set_and_count_cannot_be_shrunk_locally(self):
        g = self.game(hand=('ask.arcane',), board=('board.any.2', 'board.any.3'))
        self.play(g, 'ask.arcane')
        self.assertEqual(self.armor(g), 0)
        self.assertIsNotNone(g.state.pending_choice)
        snap = g.snapshot(); play = snap['state']['play_history'][-1]
        play['spell_payload']['contributors'] = play['spell_payload']['contributors'][:1]
        play['spell_payload']['casts'] = 2
        snap['state']['spell_repeats'][-1]['casts'] = 2
        # One actual cast fits either count; local receipt/history agree, while
        # the untouched original full proof still requires both sources/three.
        self.reject(snap)
        snap = g.snapshot()
        snap['state']['play_history'][-1]['spell_payload']['contributors'].reverse()
        self.reject(snap)
        snap = g.snapshot(); snap['state']['spell_repeats'][-1]['casts'] = 2
        self.reject(snap)
        self.portable(g)

    def test_submission_school_declaration_and_consumption_cannot_change_locally(self):
        g = self.ready(hand=('ask.arcane',))
        self.play(g, 'ask.arcane')
        self.portable(g)
        for mode in ('school.expand', 'restore.use', 'source'):
            with self.subTest(mode=mode):
                snap = g.snapshot()
                modifier = snap['state']['players']['1']['spell_modifiers'][0]
                if mode == 'school.expand':
                    modifier['spec']['match']['recipient_metadata']['spell_schools'] = ['arcane', 'fire']
                elif mode == 'restore.use':
                    modifier['uses_remaining'] = 2
                else:
                    source = next(e for e in snap['state']['entities'].values()
                        if e['card_id'] == 'plain')
                    modifier.update(source_id=source['id'], source_card_id='plain')
                self.reject(snap)

    def test_post_finish_tail_terminal_preserves_completed_spell_facts(self):
        # Real card_played work starts after FinishPlay has completed the play.
        g = self.game(hand=('arcane',), board=('board.any.2', 'tail.fatal'))
        self.play(g, 'arcane')
        p = self.subject(g)
        self.assertEqual(g.state.status, 'finished')
        self.assertTrue(p.completed)
        self.assertFalse(p.interrupted)
        self.assertEqual((self.armor(g), len(self.casts(g))), (4, 2))
        self.assertIsNone(g.snapshot()['resolution_frame'])
        self.portable(g)

    def test_receipt_fields_are_mandatory_and_completed_ledger_is_compact(self):
        g = self.game(hand=('ask.arcane',), board=('board.any.2',))
        self.play(g, 'ask.arcane')
        self.assertEqual(g.snapshot()['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        old = g.snapshot(); old['schema_version'] = 100; self.reject(old)
        for field in ('spell_submission', 'spell_payload', 'spell_acceptance_closed'):
            snap = g.snapshot(); del snap['state']['play_history'][-1][field]; self.reject(snap)
        snap = g.snapshot(); snap['state']['play_history'][-1]['spell_acceptance_closed'] = True
        self.reject(snap)
        self.choose(g, 'ok'); self.choose(g, 'ok')
        play = g.snapshot()['state']['play_history'][-1]
        self.assertEqual(set(play['spell_submission']), {'hero_class', 'modifiers', 'cost_facts'})
        self.assertEqual(set(play['spell_payload']), {'target_id', 'behavior_ids', 'hero_class', 'contributors', 'casts', 'cost_facts'})
        self.assertNotIn('state', play['spell_submission'])
        self.assertNotIn('state', play['spell_payload'])
        self.portable(g)

    def test_public_parameters_include_school_without_proof_or_private_identity(self):
        g = self.ready(hand=('ask.arcane',), enemy_hand=('unknown.arcane',))
        self.play(g, 'ask.arcane')
        for viewer in (1, 2):
            view = g.observe(viewer)
            self.assertEqual(view['players'][0]['spell_modifiers'][0]['match'],
                {'recipient_metadata': {'basis': 'accepted_face_printed', 'spell_schools': ['arcane']}, 'recipient_cost': None})
            text = json.dumps(view)
            for key in ('spell_submission', 'spell_payload', 'spell_acceptance_closed',
                    'spell_policy_receipts', 'resolution_frame', 'policy_source_id',
                    'modifier_id', 'source_card_id', 'behavior_ids', 'rng_state'):
                self.assertNotIn('"' + key + '"', text)
        self.assertNotIn('unknown.arcane', json.dumps(g.observe(1)))
        self.assertNotIn('unknown.arcane', json.dumps(g.player_events(1)))
        self.portable(g)


if __name__ == '__main__':
    unittest.main()
