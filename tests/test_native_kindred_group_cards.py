"""Original sampled Kindred groups cross actual damage and freeze reactions."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import random
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_kindred_group_cards import STEGODON, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Destroy, InvokeBehavior,
    RequestChoice, ReturnToHand, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P = 'k140.'
YETI = 'CORE_CS2_182'
CHALLENGER = 'TLC_251'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


def registry(mode=None):
    r = build_registry()
    r.register_behavior(P+'noop', lambda c: ())
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('K140 deliberate failure')))
    r.register_behavior(P+'reenter', lambda c: (SummonStoredCard(
        CardReference.capture(c.state.entities[c.target_id]), 2,
        cause=SummonCause.capture(c)),))
    r.register_card(CardDefinition(P+'beast', 'Original previous turn Beast', CardType.MINION,
        cost=1, attack=1, health=2, metadata=replace(META, tribes=('beast',))))
    for name, health in (('tank', 20), ('small', 1)):
        r.register_card(CardDefinition(P+name, name, CardType.MINION, attack=1, health=health, metadata=META))
    r.register_card(CardDefinition(P+'power', 'Ordinary Spell Damage', CardType.MINION,
        health=20, spell_damage=7, metadata=META))
    r.register_card(CardDefinition(P+'dormant', 'Excluded sleeper', CardType.MINION,
        health=20, dormant_turns=50, metadata=META))
    r.register_card(CardDefinition(P+'location', 'Excluded physical location', CardType.LOCATION,
        durability=3, on_use=P+'noop', metadata=META))
    if mode:
        event = 'choice_skipped' if mode == 'sample' else 'frozen' if mode == 'freeze' else 'health_resolved'

        def eligible(c):
            source = c.state.entities.get(c.event.source_id)
            return source is not None and source.card_id == STEGODON

        def watch(c):
            if mode == 'fail':
                return (InvokeBehavior(P+'fail', c.source_id, 1),)
            targets = tuple(i for i in c.state.players[2].board
                if c.state.entities[i].kind == CardType.MINION and c.state.entities[i].active)
            options = [ChoiceOption('ok', 'Continue'),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'fail', c.source_id, 1),)),
                ChoiceOption('source', 'Remove original source', (Destroy(c.event.source_id, c.source_id),))]
            prompt = 'Continue'
            if mode == 'freeze':
                target = next(i for i in targets if not c.state.entities[i].frozen)
                prompt = str(target)
                options.extend((ChoiceOption('reenter', 'Leave and reenter', (
                    ReturnToHand(target), InvokeBehavior(P+'reenter', c.source_id, 1, target_id=target))),
                    ChoiceOption('transfer', 'Transfer original target', (ChangeControl(target, 1),)),
                    ChoiceOption('transform', 'Replace original face', (Transform(target, YETI),))))
            return (RequestChoice(1, tuple(options), c.source_id, prompt=prompt),)

        r.register_behavior(P+'watch', watch)
        r.register_trigger_condition(P+'eligible', eligible)
        r.register_card(CardDefinition(P+'watch', 'Original reaction witness', CardType.WEAPON,
            durability=5, metadata=META,
            limited_triggers=(LimitedTriggerSpec(event, P+'watch', condition_id=P+'eligible'),)))
    r.validate()
    return r


@lru_cache(maxsize=None)
def shared(mode):
    return registry(mode)


def wires(value, name):
    if isinstance(value, dict):
        if value.get('type', '').endswith('.'+name):
            yield value
        for child in value.values():
            yield from wires(child, name)
    elif isinstance(value, list):
        for child in value:
            yield from wires(child, name)


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class NativeKindredGroupTests(unittest.TestCase):
    def game(self, hand=(STEGODON,), enemy=(P+'tank', P+'tank'), board=(), mode=None):
        self.mode = mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board,
            deck=(YETI,)*10, mana=30, max_mana=30, mana_cap=30,
            weapon_card_id=P+'watch' if mode else None),
            PlayerSetup('HERO_08', board=enemy, deck=(YETI,)*10, mana=30, max_mana=30, mana_cap=30)),
            seed=140, generation_context=None), shared(mode))

    def play(self, g, cid, player=1):
        source = next(g.state.entities[i] for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(player, source.id))
        return source.id

    def cycle(self, g):
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))

    def qualified(self, extra=(), **kwargs):
        g = self.game((P+'beast', STEGODON, *extra), **kwargs)
        self.play(g, P+'beast')
        self.cycle(g)
        return g

    def choose(self, g, key='ok'):
        g.apply(SelectChoice(1, g.state.pending_choice.id, (key,)))

    def drain(self, g):
        while g.state.pending_choice is not None:
            self.choose(g)

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(self.mode))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(self.mode)).snapshot(), saved)
        return other

    def test_complete_source_two_full_faces_and_native_body_profile(self):
        from tools.card_batch import check_face
        data = load_batch()
        row, = data['cards']
        self.assertEqual(row['record_sha256'], canonical_digest(row['record']))
        self.assertEqual(len(data['official_observations']), 2)
        for o in data['official_observations']:
            check_face(row['record'], o['face'], o['locale'])
        r = shared(None)
        c = r.card(STEGODON)
        self.assertEqual((c.cost, c.attack, c.health, c.metadata), (4, 3, 4, metadata_from_record(row['record'])))
        self.assertIsNotNone(r.kindred_profiles[STEGODON].prepare)
        self.assertIsNotNone(r.kindred_profiles[STEGODON].active)

    def test_unqualified_native_damage_once_no_spell_bonus_and_no_freeze(self):
        g = self.game(board=(P+'power',))
        source = self.play(g, STEGODON)
        self.assertEqual(g.state.players[1].mana, 26)
        self.assertEqual(len(g.state.damage_history), 2)
        self.assertTrue(all(x.health_result.base_amount == 2 and x.health_result.spell_bonus == 0 for x in g.state.damage_history))
        self.assertTrue(all(not g.state.entities[i].frozen for i in g.state.players[2].board))
        root, = g.state.kindred_history
        self.assertEqual((root.plan, root.completed, root.source.entity_id), (('prepare',), True, source))

    def test_real_previous_owner_beast_freezes_original_two_after_single_damage_batch(self):
        g = self.qualified()
        self.play(g, STEGODON)
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board], [18, 18])
        self.assertTrue(all(g.state.entities[i].frozen for i in g.state.players[2].board))
        root, = g.state.kindred_history
        self.assertEqual((root.plan, root.started, root.finished), (('prepare', 'active'), ('prepare', 'active'), (1, 0)))
        self.assertTrue(root.completed)
        self.portable(g)

    def test_current_owner_beast_does_not_replace_previous_owner_turn_query(self):
        g = self.game((P+'beast', STEGODON))
        self.play(g, P+'beast')
        self.play(g, STEGODON)
        self.assertFalse(g.state.kindred_history[0].condition.matched)
        self.assertTrue(all(not g.state.entities[i].frozen for i in g.state.players[2].board))

    def test_zero_one_two_and_larger_groups_exclude_dormant_and_location(self):
        for n in (0, 1, 2, 4):
            with self.subTest(n=n):
                g = self.game(enemy=(P+'tank',)*n + (P+'dormant', P+'location'))
                before = g._rng.getstate()
                self.play(g, STEGODON)
                self.assertEqual(len(g.state.damage_history), min(n, 2))
                self.assertTrue(all(g.state.entities[x.health_result.target_id].card_id == P+'tank' for x in g.state.damage_history))
                if n == 0:
                    self.assertEqual(before, g._rng.getstate())

    def test_multiple_real_next_kindred_sources_repeat_only_freeze_and_consume_once(self):
        g = self.qualified((CHALLENGER, CHALLENGER))
        self.play(g, CHALLENGER)
        self.play(g, CHALLENGER)
        before = g.state.players[1].mana
        self.play(g, STEGODON)
        root, = g.state.kindred_history
        self.assertEqual((root.repetitions, len(root.sources), root.plan), (2, 2, ('prepare', 'active', 'active')))
        self.assertEqual(g.state.players[1].mana, before-4)
        self.assertEqual(len(g.state.damage_history), 2)
        self.assertEqual(sum(e.kind == 'freeze_unchanged' for e in g.events), 2)
        self.assertFalse(g.state.players[1].player_effects)

    def test_failed_condition_still_uses_existing_next_kindred_consumption_policy(self):
        g = self.game((CHALLENGER, STEGODON))
        self.play(g, CHALLENGER)
        self.play(g, STEGODON)
        root, = g.state.kindred_history
        self.assertFalse(root.condition.matched)
        self.assertEqual((root.plan, len(root.sources)), (('prepare',), 1))
        self.assertFalse(g.state.players[1].player_effects)

    def test_dead_original_recipient_does_not_receive_freeze_or_replacement(self):
        g = self.qualified(enemy=(P+'small', P+'tank'))
        self.play(g, STEGODON)
        self.assertEqual(len(g.state.players[2].board), 1)
        target = g.state.entities[g.state.players[2].board[0]]
        self.assertEqual((target.card_id, target.health, target.frozen), (P+'tank', 18, True))
        self.assertEqual(len(g.state.death_history), 1)

    def test_actual_sampling_callback_wait_preserves_original_activation_and_group(self):
        g = self.qualified(mode='sample')
        self.play(g, STEGODON)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(g.state.damage_history)
        self.assertTrue(list(wires(g.snapshot(), 'ResolveChoiceResult')))
        other = self.portable(g)
        self.choose(g)
        self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(g.state.damage_history), 2)
        self.assertTrue(all(g.state.entities[i].frozen for i in g.state.players[2].board))

    def test_damage_wait_restore_replay_and_failed_continue_never_redraw_or_repeat_damage(self):
        g = self.qualified(mode='damage', enemy=(P+'tank',)*4)
        self.play(g, STEGODON)
        self.assertIsNotNone(g.state.pending_choice)
        saved, rng = g.snapshot(), g._rng.getstate()
        other = self.portable(g)
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.drain(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g._rng.getstate(), rng)
        self.assertEqual(len(g.state.damage_history), 2)
        self.assertEqual(sum(g.state.entities[i].frozen for i in g.state.players[2].board), 2)

    def test_original_source_leaves_during_damage_reactions_but_original_freeze_finishes(self):
        g = self.qualified(mode='damage')
        source = self.play(g, STEGODON)
        self.choose(g, 'source')
        self.drain(g)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertTrue(all(g.state.entities[i].frozen for i in g.state.players[2].board))
        self.assertTrue(g.state.kindred_history[0].completed)

    def test_first_freeze_wait_does_not_freeze_transferred_or_replaced_original_other(self):
        for action in ('transfer', 'transform', 'reenter'):
            with self.subTest(action=action):
                g = self.qualified(mode='freeze')
                self.play(g, STEGODON)
                target = int(g.state.pending_choice.prompt)
                self.choose(g, action)
                self.assertIsNone(g.state.pending_choice)
                self.assertFalse(g.state.entities[target].frozen)
                self.assertTrue(g.state.kindred_history[0].completed)

    def test_direct_reaction_failure_restores_payment_rng_and_accepted_history(self):
        g = self.qualified(mode='fail')
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.play(g, STEGODON)
        self.assertEqual(g.snapshot(), saved)

    def test_rehashed_sample_caller_or_prepared_choice_future_identity_is_rejected(self):
        for mode, name in (('sample', 'ResolveChoiceResult'), ('damage', 'RunKindredComponent')):
            with self.subTest(mode=mode):
                g = self.qualified(mode=mode)
                self.play(g, STEGODON)
                saved = deepcopy(g.snapshot())
                wire = next(wires(saved, name))
                field = 'result' if mode == 'sample' else 'prepared_choice'
                wire['fields'][field]['fields']['choice']['fields']['id'] = g.state.next_choice_id+100
                with self.assertRaises((SnapshotError, ValueError)):
                    Game.from_snapshot(rehash(saved), registry(mode))

    def test_player_dto_does_not_export_original_kindred_or_sampled_reference_payloads(self):
        g = self.qualified(mode='damage')
        self.play(g, STEGODON)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(g.player_events(player))
            for key in ('kindred_history', 'prepared_choice', 'resolution_frame', 'rng_state', 'entered_order', 'zone_epoch'):
                self.assertNotIn('"'+key+'"', public)

    def test_old_schema_and_unqualified_manual_kindred_context_are_rejected(self):
        from hs_sim.engine.effects import RequestChoice
        g = self.qualified(mode='sample')
        self.play(g, STEGODON)
        wire = next(wires(g.snapshot(), 'ResolveChoiceResult'))
        from hs_sim.engine.continuations import FrameCodec
        activation = FrameCodec(g.mechanics, g.registry).decode(wire).kindred
        with self.assertRaisesRegex(ValueError, 'automatic preparation'):
            RequestChoice(1, (ChoiceOption('one', 'One'),), activation.original.source_id,
                on_select=P+'noop', kindred=activation)
        old = g.snapshot()
        old['schema_version'] = 346
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(old, registry(self.mode))


if __name__ == '__main__':
    unittest.main()
