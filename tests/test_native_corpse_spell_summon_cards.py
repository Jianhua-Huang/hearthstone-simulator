"""Real Echoes: current corpse/capacity gate and independent original Outcast."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.native_corpse_spell_summon_cards import ECHO, POOL_ID, QUERY, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, Keyword,
                           PlayCard, PlayerSetup, Ruleset, Scenario, SelectChoice, SnapshotError)
from hs_sim.engine.effects import (ChoiceOption, Destroy, GainResource, InvokeBehavior,
                                   RequestChoice, SpendResource)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec, Rarity, Resource, SpellRepeatSpec, SpellSchool
from hs_sim.engine.pools import (GenerationContext, PoolCard, PoolDefinition, PoolMember,
                                SummonFromPool)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import canonical_digest

P = 'k131.test.'
YETI, SENJIN = 'CORE_CS2_182', 'CORE_CS2_179'
CONTEXT = GenerationContext('k131-complete-explicit-experiment', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())


@lru_cache(None)
def registry(mode=None, members=(YETI, SENJIN), pool=True):
    r = build_registry()
    def fail(c):
        raise ResolutionError('K131 deliberate late failure')
    r.register_behavior(P + 'fail', fail)
    r.register_behavior(P + 'auto', lambda c: (CastSpell(c.player_id, ECHO, c.source_id),))
    r.register_card(CardDefinition(P + 'auto', 'Automatic Echoes', CardType.SPELL, metadata=META, on_play=P + 'auto'))
    r.register_card(CardDefinition(P + 'repeat', 'Shared spell repeats', CardType.MINION, health=9, metadata=META,
                                    spell_repeats=(SpellRepeatSpec(2, class_mode='any'),)))
    r.register_card(CardDefinition(P + 'dormant', 'Dormant slot occupant', CardType.MINION, health=3,
                                    dormant_turns=2, metadata=META))
    unknown = CardDefinition(P + 'unknown', 'Unknown eligible four', CardType.MINION, cost=4, health=4,
                            metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=()))
    r.register_pool_card(PoolCard.from_definition(unknown))
    if mode:
        event = 'resource_spent' if mode == 'payment_wait' else 'minion_summoned'
        def eligible(c):
            if event == 'resource_spent':
                return c.event.player_id == c.player_id
            return any(root.request.cause.source.card_id == ECHO and any(d.entity is not None and
                       d.entity.entity_id == c.event.target_id for d in root.deliveries)
                       for root in c.state.card_summon_history)
        def watch(c):
            if mode == 'summon_fail':
                return (InvokeBehavior(P + 'fail', c.source_id, c.player_id),)
            target = c.event.target_id
            fixed = SummonByCard(c.player_id, (SummonEntryMaterial(YETI),), SummonCause.capture(c))
            options = [ChoiceOption('ok', 'Continue'),
                       ChoiceOption('fill', 'Fill remaining slots', (fixed,) * 7),
                       ChoiceOption('spend', 'Other actual debit', (SpendResource(c.player_id, Resource.CORPSES, 4),)),
                       ChoiceOption('gain', 'Gain one corpse', (GainResource(c.player_id, Resource.CORPSES, 1),)),
                       ChoiceOption('fault', 'Fail', (InvokeBehavior(P + 'fail', c.source_id, c.player_id),))]
            if target is not None:
                options.append(ChoiceOption('kill', 'Kill first original', (Destroy(target, c.source_id),)))
            return (RequestChoice(c.player_id, tuple(options), c.source_id),)
        r.register_behavior(P + 'watch', watch)
        r.register_trigger_condition(P + 'eligible', eligible)
        r.register_card(CardDefinition(P + 'watch', 'One real reaction window', CardType.MINION, health=9, metadata=META,
                        limited_triggers=(LimitedTriggerSpec(event, P + 'watch', condition_id=P + 'eligible', uses=1),)))
    if pool:
        r.register_pool(PoolDefinition(POOL_ID, 'k131-explicit-fixture-v1', CONTEXT.target_id, CONTEXT.mode,
                                      tuple(PoolMember(cid) for cid in members), complete=True))
    r.validate()
    return r


class NativeCorpseSpellSummonTests(unittest.TestCase):
    def game(self, *, hand=(ECHO,), board=(), bank=4, mode=None, members=(YETI, SENJIN), pool=True,
             context=CONTEXT, maximum=7, hero='HERO_10'):
        self.options = (mode, members, pool)
        if mode:
            board = (P + 'watch',) + board
        return Game.from_scenario(Scenario((PlayerSetup(hero, hand=hand, board=board, corpses=bank,
            mana=30, max_mana=30, mana_cap=30, deck=(YETI,) * 4),
            PlayerSetup('HERO_08', deck=(YETI,) * 4)), generation_context=context, seed=131),
            registry(*self.options), Ruleset(max_board=maximum))

    def play(self, g, cid=ECHO):
        source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, source))
        return source

    def roots(self, g):
        return [x for x in g.state.card_summon_history if x.request.cause.cast_card_id == ECHO]

    def delivered(self, g):
        return [d.entity.entity_id for row in self.roots(g) for d in row.deliveries if d.entity is not None]

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        fresh = registry.__wrapped__(*self.options)
        other = Game.from_snapshot(saved, fresh)
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), fresh).snapshot(), saved)
        for pid in (1, 2):
            public = json.dumps(g.for_player(pid).observe()) + json.dumps(g.player_events(pid))
            for key in ('requires_board_space', 'card_summon_history', 'corpse_spend_history', 'rng_state', 'resolution_frame'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_full_source_two_primary_faces_dual_classes_school_and_no_fake_minion_source(self):
        data = load_batch()
        raw = data['cards'][0]['record']
        self.assertEqual(canonical_digest(raw), data['cards'][0]['record_sha256'])
        for ob in data['official_observations']['observations']:
            face = ob['face']
            self.assertEqual(face['id'], raw['dbf_id'])
            self.assertEqual(set(face['multiClassIds']), {1, 14})
        c = registry().card(ECHO)
        self.assertEqual((c.cost, c.spell_school, c.keywords), (5, SpellSchool.SHADOW, (Keyword.OUTCAST,)))
        self.assertEqual(set(c.metadata.classes), {CardClass.DEATH_KNIGHT, CardClass.DEMON_HUNTER})
        self.assertFalse(data['dependencies'] or data['evidence_only'])

    def test_only_one_definition_and_no_old_pool_definition_family_or_pool_changes(self):
        with patch('hs_sim.cards.native_corpse_spell_summon_cards.register_native_corpse_spell_summon_cards', lambda r: None):
            old = build_registry()
        new = build_registry()
        self.assertEqual(set(new.cards) - set(old.cards), {ECHO})
        self.assertTrue(all(asdict(c) == asdict(new.card(cid)) for cid, c in old.cards.items()))
        self.assertEqual(dict(new.pool_cards), dict(old.pool_cards))
        self.assertEqual(dict(new.generation_families), dict(old.generation_families))
        self.assertEqual(dict(new.pools), dict(old.pools))

    def test_current_bank_zero_three_four_eight_and_original_outcast_are_independent(self):
        for bank in (0, 3, 4, 8):
            for active in (False, True):
                with self.subTest(bank=bank, active=active):
                    hand = (ECHO, YETI) if active else (YETI, ECHO, YETI)
                    g = self.game(hand=hand, bank=bank)
                    self.play(g)
                    paid = bank >= 4
                    self.assertEqual(len(self.delivered(g)), 1 + paid + active)
                    self.assertEqual(g.state.players[1].resources[Resource.CORPSES], bank - 4 * paid)
                    self.assertEqual(len(g.state.corpse_spend_history), int(paid))
                    self.assertEqual((g.state.players[1].mana, len(g.state.cast_history)), (25, 1))

    def test_both_original_hand_edges_and_both_hero_classes_use_same_recipe(self):
        for hero in ('HERO_10', 'HERO_11'):
            for hand in ((ECHO, YETI), (YETI, ECHO)):
                with self.subTest(hero=hero, hand=hand):
                    g = self.game(hero=hero, hand=hand)
                    self.play(g)
                    self.assertEqual(len(self.delivered(g)), 3)
                    self.assertTrue(all(x.request.cause.origin == 'spell_cast' for x in self.roots(g)))

    def test_full_after_first_or_already_full_preserves_corpses(self):
        for maximum, occupied in ((7, 6), (7, 7), (8, 7), (9, 8)):
            with self.subTest(maximum=maximum, occupied=occupied):
                g = self.game(board=(YETI,) * occupied, maximum=maximum)
                before_rng = g.snapshot()['rng_state']
                self.play(g)
                self.assertEqual(len(self.delivered(g)), min(1, maximum - occupied))
                self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 4)
                self.assertFalse(g.state.corpse_spend_history)
                if occupied == maximum:
                    self.assertEqual(g.snapshot()['rng_state'], before_rng)

    def test_two_free_slots_pay_once_then_final_outcast_attempt_skips(self):
        g = self.game(board=(YETI,) * 5)
        self.play(g)
        self.assertEqual((len(self.delivered(g)), len(g.state.players[1].board)), (2, 7))
        self.assertEqual((g.state.players[1].resources[Resource.CORPSES], len(g.state.corpse_spend_history)), (0, 1))

    def test_dormant_occupants_count_against_actual_capacity(self):
        g = self.game(board=(P + 'dormant',) * 6)
        self.play(g)
        self.assertEqual(len(self.delivered(g)), 1)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 4)

    def test_first_actual_death_adds_fourth_corpse_before_gate(self):
        g = self.game(mode='first_wait', bank=3)
        self.play(g)
        self.assertEqual(len(self.delivered(g)), 1)
        self.assertFalse(g.state.corpse_spend_history)
        other = self.portable(g)
        for h in (g, other):
            self.choose(h, 'kill')
            self.assertEqual(len(self.delivered(h)), 3)
            self.assertEqual((h.state.players[1].resources[Resource.CORPSES], len(h.state.corpse_spend_history)), (0, 1))
        self.assertEqual(g.snapshot(), other.snapshot())

    def test_first_reaction_spend_or_fill_is_rechecked_before_native_debit(self):
        for branch in ('spend', 'fill'):
            with self.subTest(branch=branch):
                g = self.game(mode='first_wait')
                self.play(g)
                self.portable(g)
                self.choose(g, branch)
                self.assertEqual(len(g.state.corpse_spend_history), int(branch == 'spend'))
                self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 0 if branch == 'spend' else 4)
                self.assertEqual(len(self.delivered(g)), 2 if branch == 'spend' else 1)

    def test_resource_wait_resumes_without_second_payment_and_post_payment_full_does_not_refund(self):
        for branch in ('ok', 'fill'):
            with self.subTest(branch=branch):
                g = self.game(mode='payment_wait')
                self.play(g)
                self.assertEqual((len(self.delivered(g)), len(g.state.corpse_spend_history)), (1, 1))
                other = self.portable(g)
                saved = g.snapshot()
                with self.assertRaises(ResolutionError):
                    self.choose(g, 'fault')
                self.assertEqual(g.snapshot(), saved)
                for h in (g, other):
                    self.choose(h, branch)
                    self.assertEqual(len(self.delivered(h)), 3 if branch == 'ok' else 1)
                    self.assertEqual((h.state.players[1].resources[Resource.CORPSES], len(h.state.corpse_spend_history)), (0, 1))
                self.assertEqual(g.snapshot(), other.snapshot())

    def test_first_summon_reaction_failure_rolls_back_entire_paid_command(self):
        g = self.game(mode='summon_fail')
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g)
        self.assertEqual(g.snapshot(), before)

    def test_real_khadgar_extra_bodies_do_not_multiply_the_corpse_payment(self):
        g = self.game(board=('CORE_DAL_575',))
        self.play(g)
        self.assertEqual(len(self.delivered(g)), 6)
        self.assertEqual([len(x.deliveries) for x in self.roots(g)], [2, 2, 2])
        self.assertEqual((g.state.players[1].resources[Resource.CORPSES], len(g.state.corpse_spend_history)), (0, 1))

    def test_shared_spell_repeat_creates_independent_casts_and_current_bank_checks(self):
        g = self.game(board=(P + 'repeat',), bank=8)
        self.play(g)
        self.assertEqual((len(self.delivered(g)), len(g.state.cast_history), len(g.state.corpse_spend_history)), (6, 2, 2))
        self.assertEqual({x.request.cause.cast_id for x in self.roots(g)}, {1, 2})
        self.assertEqual((g.state.players[1].mana, g.state.players[1].resources[Resource.CORPSES]), (25, 0))
        self.portable(g)

    def test_automatic_cast_has_no_hand_outcast_and_uses_ordinary_gate(self):
        g = self.game(hand=(P + 'auto',))
        self.play(g, P + 'auto')
        self.assertEqual(len(self.delivered(g)), 2)
        self.assertFalse([x.outcast for x in g.state.cast_history if x.card_id == ECHO][0])
        self.portable(g)

    def test_complete_unknown_pool_and_missing_binding_fail_before_rng_without_cropping(self):
        for kwargs in (dict(members=(YETI, P + 'unknown')), dict(pool=False), dict(context=None)):
            with self.subTest(kwargs=kwargs):
                g = self.game(**kwargs)
                before = g.snapshot()
                with self.assertRaises((ResolutionError, ValueError)):
                    self.play(g)
                self.assertEqual(g.snapshot(), before)

    def test_empty_explicit_fixture_pool_has_no_random_bodies(self):
        g = self.game(members=(), bank=0)
        before_rng = g.snapshot()['rng_state']
        self.play(g)
        self.assertFalse(self.delivered(g))
        self.assertEqual(g.snapshot()['rng_state'], before_rng)

    def test_capacity_gate_rejects_non_plain_or_unattributed_resource_branches(self):
        g = self.game(mode='first_wait')
        self.play(g)
        original = self.roots(g)[0].request
        request = SummonFromPool(1, POOL_ID, QUERY, source_id=original.cause.source.entity_id, cause=original.cause)
        valid = SpendResource(1, Resource.CORPSES, 4, on_success=(request,), requires_board_space=True)
        for changes in (dict(requires_board_space=1), dict(required=True), dict(amount=0), dict(on_success=()),
                        dict(on_failure=(GainResource(1, Resource.CORPSES, 1),)),
                        dict(on_success=(replace(request, cause=None),))):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(valid, **changes)
        self.assertFalse(SpendResource(1, Resource.CORPSES, 4).requires_board_space)

    def test_waiting_future_cast_in_gate_is_rejected_and_previous_schema_is_rejected(self):
        g = self.game(mode='first_wait')
        self.play(g)
        saved = deepcopy(g.snapshot())
        def gates(value):
            if isinstance(value, dict):
                if (value.get('type') == 'hs_sim.engine.effects.SpendResource' and
                        value['fields'].get('requires_board_space') is True):
                    yield value['fields']
                for child in value.values():
                    yield from gates(child)
            elif isinstance(value, list):
                for child in value:
                    yield from gates(child)
        entries = list(gates(saved['resolution_frame']))
        self.assertGreaterEqual(len(entries), 1)
        # The codec stores dataclasses as a typed wrapper with plain field maps.
        def corrupt(value):
            if isinstance(value, dict):
                if 'cast_id' in value and value.get('cast_card_id') == ECHO:
                    value['cast_id'] = 999999
                    return True
                return any(corrupt(child) for child in value.values())
            if isinstance(value, list):
                return any(corrupt(child) for child in value)
            return False
        self.assertTrue(corrupt(entries[0]))
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, registry.__wrapped__(*self.options))
        old = g.snapshot()
        old['schema_version'] = SNAPSHOT_SCHEMA_VERSION - 1
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(old, registry.__wrapped__(*self.options))


if __name__ == '__main__':
    unittest.main()
