"""Genuine default CAST, stored/history CAST and whole-card target preference."""
from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
from random import Random
import unittest

from hs_sim.engine import (CardDefinition, CardType, Game, PlayCard, PlayerSetup, Registry,
    Scenario, SelectChoice)
from hs_sim.engine.automatic_targets import AutomaticTargetPreference as Preference
from hs_sim.engine.effects import (ChoiceOption, Damage, DamageKind, Effect, GainArmor,
    RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import (CardClass, CardMetadata, ChooseBranch, ChooseOneSpec, Keyword,
    Rarity, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell, CastStoredSpell
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.zones import CardReference


@dataclass(frozen=True)
class TargetBodyFailure(Effect):
    source_id: int


def make_mechanics():
    value = default_mechanics('automatic-target-runtime-tests-v1')
    def fail(r, e): raise ResolutionError('target-body deliberate failure')
    value.register(TargetBodyFailure, fail)
    return value


def make_registry(preference=Preference.ENEMY_IF_AVAILABLE, mode=TargetMode.REQUIRED,
        relation='any', visibility='omniscient', route='generated', executor=1,
        body='wait', target_zone='characters', branch=False, predicate=False):
    registry = Registry('automatic-target-runtime-tests-v1')
    meta = CardMetadata(False, (CardClass.MAGE,), Rarity.COMMON)
    registry.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30, metadata=meta))
    registry.register_card(CardDefinition('plain', 'Minion', CardType.MINION, health=4))
    registry.register_card(CardDefinition('small', 'Small', CardType.MINION, health=1))
    registry.register_card(CardDefinition('protected', 'Protected', CardType.MINION, health=4,
        keywords=(Keyword.STEALTH, Keyword.ELUSIVE)))
    registry.register_card(CardDefinition('watcher', 'Watcher', CardType.MINION, health=4,
        triggers=(TriggerSpec('spell_cast_started', 'bounce'),)))
    def bounce(c):
        cast_id = dict(c.event.data).get('cast_id')
        cast = c.state.cast_history[cast_id - 1] if cast_id else None
        return (ReturnToHand(c.event.target_id),) if cast and cast.origin == 'effect' and c.event.target_id in c.state.players[2].board else ()
    registry.register_behavior('bounce', bounce)
    def text(c):
        if c.cast.origin == 'hand': return ()
        if body == 'fail': return (TargetBodyFailure(c.source_id),)
        if body == 'lethal': return (Damage(c.target_id, 100, c.source_id, DamageKind.SPELL),)
        if body == 'damage': return (Damage(c.target_id, 1, c.source_id, DamageKind.SPELL),) if c.target_id else ()
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue', (GainArmor(c.player_id, 1),)),), source_id=c.source_id),)
    registry.register_behavior('text', text)
    if target_zone == 'hand':
        target = TargetSpec(mode, (Zone.HAND,), (CardType.SPELL,), relation)
    elif target_zone == 'minions':
        target = TargetSpec(mode, (Zone.BOARD,), (CardType.MINION,), relation)
    elif target_zone == 'heroes':
        target = TargetSpec(mode, (Zone.HERO,), (CardType.HERO,), relation)
    else: target = TargetSpec(mode=mode, relation=relation)
    rule = 'any_entity'
    if visibility == 'player':
        rule = 'visible_spell'
        registry.register_target_rule(rule, lambda c: bool(c.target and c.target.get('card_id') and
            c.target.get('kind') == CardType.SPELL.value), visibility='player')
    elif predicate:
        rule = 'large'
        registry.register_target_rule(rule, lambda c: c.state.entities[c.target_id].health >= 4, visibility='omniscient')
    if branch:
        branches = ChooseOneSpec((ChooseBranch('minions', 'Minions', 'text',
            TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))),
            ChooseBranch('heroes', 'Heroes', 'text', TargetSpec(zones=(Zone.HERO,), kinds=(CardType.HERO,)))),
            ChooseBranch('both', 'Both', 'text', target))
        registry.register_card(CardDefinition('target', 'Target', CardType.SPELL, choose_one=branches, metadata=meta))
    else:
        registry.register_card(CardDefinition('target', 'Target', CardType.SPELL,
            targeting=target, target_rule=rule, on_play='text', metadata=meta))
    def launch(c):
        if route == 'whole':
            return (ReplayWholeCards(executor, c.source_id,
                WholeCardHistoryQuery(1, len(c.state.play_history) + 1), choices='player',
                target_preference=preference),)
        if route == 'stored':
            entity = next(e for e in c.state.entities.values() if e.card_id == 'target' and e.zone == Zone.HAND and e.controller == 1)
            return (CastStoredSpell(CardReference.capture(entity), executor,
                c.source_id, choices='player', target_preference=preference),)
        if route == 'history':
            return (RecastSpell(executor, 1, c.source_id, choices='player', target_preference=preference),)
        return (CastSpell(executor, 'target', c.source_id, choices='player',
            branch_id='minions' if branch else None, target_preference=preference),)
    registry.register_behavior('launch', launch)
    registry.register_card(CardDefinition('launch', 'Launch', CardType.SPELL, cost=3, on_play='launch', metadata=meta))
    registry.register_card(CardDefinition('hidden', 'Hidden', CardType.SPELL, metadata=meta))
    return registry


class AutomaticTargetRuntimeTests(unittest.TestCase):
    def game(self, friendly=('plain',), enemy=('plain', 'small'), **config):
        self.config = config
        return Game.from_scenario(Scenario((PlayerSetup('hero', board=friendly,
            hand=('target', 'launch', 'hidden'), deck=('plain',) * 4, mana=10, max_mana=10),
            PlayerSetup('hero', board=enemy, hand=('hidden', 'hidden'), deck=('plain',) * 4,
                mana=10, max_mana=10)), seed=232), make_registry(**config), mechanics=make_mechanics())

    def play(self, game, card, target_id=None):
        source = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == card)
        return game.apply(PlayCard(1, source, target_id))

    def launched(self, **kwargs):
        game = self.game(**kwargs)
        if kwargs.get('route') in ('history', 'whole'):
            self.play(game, 'target', game.state.players[2].hero_id)
        self.play(game, 'launch')
        return game

    def portable(self, game, label):
        value = json.loads(json.dumps(game.snapshot())); payload = build_replay(game)
        branches = (Game.from_snapshot(value, make_registry(**self.config), make_mechanics()), game.clone(),
            replay(payload, make_registry(**self.config), make_mechanics()))
        for branch in branches:
            self.assertEqual(branch.snapshot(), value)
            for viewer in (1, 2):
                self.assertEqual(branch.observe(viewer), game.observe(viewer))
                self.assertEqual(branch.player_events(viewer), game.player_events(viewer))
                self.assertEqual(branch.for_player(viewer).legal_actions(), game.for_player(viewer).legal_actions())
        directory = os.environ.get('AUTOMATIC_TARGET_RUNTIME_INPUT_DIR')
        if directory:
            self.serial = getattr(self, 'serial', 0) + 1
            p = Path(directory) / self.id() / f'{self.serial:03d}-{label}.json'; p.parent.mkdir(parents=True, exist_ok=True)
            with p.open('x', encoding='utf-8') as f:
                json.dump({'host_privileged_input': True, 'method_id': self.id(), 'snapshot': value,
                    'replay': payload, 'actual_preferred_CAST': True}, f, ensure_ascii=False, indent=2); f.write('\n')
        return branches

    @staticmethod
    def rehash(snapshot):
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})

    @staticmethod
    def target_finisher(snapshot):
        return next(w for w in snapshot['resolution_frame']['fields']['continuation']['tuple']
            if w.get('type', '').endswith('.FinishSpellCast') and w['fields']['target_proof'] is not None)

    def negative(self, mutate, **kwargs):
        game = self.launched(**kwargs); before = game.snapshot(); bad = deepcopy(before)
        mutate(bad); self.rehash(bad)
        with self.assertRaises(SnapshotError) as rejected:
            Game.from_snapshot(bad, make_registry(**self.config), make_mechanics())
        self.assertNotIn('digest mismatch', str(rejected.exception))
        self.assertEqual(game.snapshot(), before)
        self.portable(game, 'valid-origin-for-semantic-negative')

    def test_default_generated_cast_prefers_enemy_after_complete_legal_filter(self):
        game = self.launched(); state = game.state; cast = state.cast_history[-1]; selection = cast.target_selection
        self.assertEqual(selection.partition.legal_ids, tuple(sorted((state.players[1].hero_id,
            state.players[2].hero_id, *state.players[1].board, *state.players[2].board))))
        self.assertEqual(selection.partition.selection_ids, selection.partition.enemy_ids)
        self.assertEqual(state.entities[cast.target_id].controller, 2)
        rng = Random(); rng.setstate(selection.rng_before)
        self.assertEqual(rng.choice(selection.partition.enemy_ids), cast.target_id)
        self.assertEqual(rng.getstate(), selection.rng_after)
        self.portable(game, 'generated-preference')

    def test_any_preference_matches_original_random_target_and_rng_exactly(self):
        old = self.launched(preference=None); new = self.launched(preference=Preference.ANY)
        self.assertEqual(old.state.cast_history[-1].target_id, new.state.cast_history[-1].target_id)
        self.assertEqual(old.snapshot()['rng_state'], new.snapshot()['rng_state'])
        self.assertIsNone(old.state.cast_history[-1].target_selection)
        self.assertEqual(new.state.cast_history[-1].target_selection.partition.selection_ids,
            new.state.cast_history[-1].target_selection.partition.legal_ids)
        self.portable(new, 'any-compatibility')

    def test_no_legal_enemy_uses_all_legal_friendly_candidates(self):
        game = self.launched(relation='friendly'); part = game.state.cast_history[-1].target_selection.partition
        self.assertEqual(part.enemy_ids, ())
        self.assertEqual(part.selection_ids, part.legal_ids)
        self.assertEqual(len(part.legal_ids), 2)
        self.portable(game, 'friendly-fallback')

    def test_executor_current_controller_decides_enemy_instead_of_original_caster_owner(self):
        game = self.launched(executor=2); cast = game.state.cast_history[-1]
        self.assertEqual(cast.player_id, 2)
        self.assertEqual(game.state.entities[cast.target_id].controller, 1)
        self.assertEqual(cast.target_selection.partition.source_controller, 2)
        self.portable(game, 'opponent-executor')

    def test_required_empty_records_failure_without_target_rng_or_body(self):
        game = self.launched(friendly=(), enemy=(), target_zone='minions'); cast = game.state.cast_history[-1]
        self.assertEqual(cast.failure, 'no_target'); self.assertTrue(cast.completed)
        self.assertEqual(cast.target_selection.rng_before, cast.target_selection.rng_after)
        self.assertIsNone(game.state.pending_choice)
        self.portable(game, 'required-empty')

    def test_optional_empty_keeps_no_target_no_failure_and_actual_body(self):
        game = self.launched(friendly=(), enemy=(), target_zone='minions', mode=TargetMode.OPTIONAL)
        cast = game.state.cast_history[-1]
        self.assertIsNone(cast.failure); self.assertIsNone(cast.target_id)
        self.assertEqual(cast.target_selection.rng_before, cast.target_selection.rng_after)
        self.assertIsNotNone(game.state.pending_choice)
        self.portable(game, 'optional-empty')

    def test_if_available_empty_keeps_actual_body_without_rng(self):
        game = self.launched(friendly=(), enemy=(), target_zone='minions', mode=TargetMode.IF_AVAILABLE)
        cast = game.state.cast_history[-1]
        self.assertIsNone(cast.failure); self.assertEqual(cast.target_selection.rng_before, cast.target_selection.rng_after)
        self.portable(game, 'if-available-empty')

    def test_singleton_enemy_still_consumes_exactly_one_existing_choice(self):
        game = self.launched(target_zone='heroes', relation='enemy'); cast = game.state.cast_history[-1]; s = cast.target_selection
        self.assertEqual(s.partition.selection_ids, (game.state.players[2].hero_id,))
        probe = Random(); probe.setstate(s.rng_before); probe.choice(s.partition.selection_ids)
        self.assertEqual(probe.getstate(), s.rng_after); self.assertNotEqual(s.rng_before, s.rng_after)
        self.portable(game, 'singleton-rng')

    def test_host_predicate_filters_enemies_before_preference(self):
        game = self.launched(target_zone='minions', predicate=True); part = game.state.cast_history[-1].target_selection.partition
        self.assertEqual(len(part.legal_ids), 2); self.assertEqual(len(part.enemy_ids), 1)
        self.assertEqual(game.state.entities[part.enemy_ids[0]].card_id, 'plain')
        self.portable(game, 'host-predicate')

    def test_automatic_protection_policy_is_shared_and_preserved(self):
        game = self.launched(friendly=(), enemy=('protected',), target_zone='minions')
        cast = game.state.cast_history[-1]
        self.assertEqual(cast.target_selection.partition.enemy_ids, tuple(game.state.players[2].board))
        self.portable(game, 'existing-protection-policy')

    def test_player_predicate_uses_original_knowledge_and_hidden_enemy_hand_is_not_eligible(self):
        game = self.launched(visibility='player', target_zone='hand'); cast = game.state.cast_history[-1]
        self.assertEqual(cast.target_selection.partition.enemy_ids, ())
        self.assertEqual(set(cast.target_selection.partition.legal_ids), set(game.state.players[1].hand))
        proof = self.target_finisher(game.snapshot())['fields']['target_proof']['fields']
        self.assertIsInstance(proof['information_json'], str)
        self.portable(game, 'original-player-knowledge')

    def test_real_waiting_target_restores_clones_replays_and_finishes_without_reselection(self):
        game = self.launched(); original_target = game.state.cast_history[-1].target_id
        rng_after = game.snapshot()['rng_state']; branches = (game, *self.portable(game, 'waiting'))
        for branch in branches:
            choice = branch.state.pending_choice; branch.apply(SelectChoice(choice.player_id, choice.id, ('ok',)))
            self.assertEqual(branch.state.cast_history[-1].target_id, original_target)
            self.assertEqual(branch.snapshot()['rng_state'], rng_after)
        for branch in branches: self.assertEqual(branch.snapshot(), game.snapshot())
        self.assertEqual(game.state.players[1].mana, 7)
        self.portable(game, 'resumed')

    def test_target_leaving_during_cast_started_reactions_does_not_rewrite_original_pool(self):
        game = self.launched(friendly=('watcher',), enemy=('plain',), target_zone='minions')
        cast = game.state.cast_history[-1]
        self.assertEqual(game.state.entities[cast.target_id].zone, Zone.HAND)
        self.assertEqual(cast.target_selection.partition.enemy_ids, (cast.target_id,))
        self.portable(game, 'original-window-after-leaving')

    def test_branch_effective_target_domain_is_used_in_original_proof(self):
        game = self.launched(branch=True); cast = game.state.cast_history[-1]
        self.assertEqual(cast.branch_id, 'minions')
        self.assertTrue(all(game.state.entities[i].kind == CardType.MINION for i in cast.target_selection.partition.legal_ids))
        self.portable(game, 'effective-branch-domain')

    def test_stored_spell_cast_uses_same_preference_without_fabricating_hand_play(self):
        game = self.launched(route='stored'); cast = game.state.cast_history[-1]
        self.assertEqual(cast.from_zone, Zone.HAND); self.assertIsNone(cast.play_id)
        self.assertEqual(len(game.state.play_history), 1)
        self.assertEqual(game.state.entities[cast.target_id].controller, 2)
        self.portable(game, 'stored-cast')

    def test_historical_recast_uses_same_preference_and_original_cast_link(self):
        game = self.launched(route='history'); cast = game.state.cast_history[-1]
        self.assertEqual(cast.origin, 'history'); self.assertEqual(cast.recast_id, 1)
        self.assertEqual(game.state.entities[cast.target_id].controller, 2)
        self.portable(game, 'historical-cast')

    def test_whole_card_replay_binds_root_preference_and_actual_target_finish(self):
        game = self.launched(route='whole'); cast = game.state.cast_history[-1]
        self.assertEqual(game.state.whole_card_replay_ledger.stack, (1,))
        self.assertEqual(cast.target_selection.partition.preference, Preference.ENEMY_IF_AVAILABLE)
        branches = (game, *self.portable(game, 'whole-target-waiting'))
        for branch in branches:
            choice = branch.state.pending_choice; branch.apply(SelectChoice(choice.player_id, choice.id, ('ok',)))
        for branch in branches: self.assertEqual(branch.snapshot(), game.snapshot())
        self.assertEqual(game.state.whole_card_replay_ledger.stack, ())
        self.portable(game, 'whole-target-finished')

    def test_real_lethal_interrupts_preferred_cast_and_original_paid_parent(self):
        game = self.launched(target_zone='heroes', relation='enemy', body='lethal')
        self.assertEqual(game.state.status, 'finished')
        self.assertTrue(game.state.cast_history[-1].interrupted)
        self.assertTrue(game.state.play_history[-1].interrupted)
        self.portable(game, 'preferred-terminal')

    def test_body_error_after_target_rng_rolls_back_all_original_action_state(self):
        game = self.game(body='fail'); before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'target-body deliberate failure'): self.play(game, 'launch')
        self.assertEqual(game.snapshot(), before)
        self.portable(game, 'target-then-body-rollback')

    def test_unknown_preference_and_explicit_conflict_reject_before_execution(self):
        with self.assertRaises(ValueError): CastSpell(1, 'target', target_preference='enemy_if_available')
        with self.assertRaises(ValueError): CastSpell(1, 'target', target_id=1, targeting='explicit', target_preference=Preference.ANY)
        with self.assertRaises(ValueError): RecastSpell(1, 1, targeting='original', target_preference=Preference.ANY)

    def test_target_partition_and_original_knowledge_never_enter_either_player_port(self):
        game = self.launched(visibility='player', target_zone='hand')
        for viewer in (1, 2):
            p = game.for_player(viewer); value = json.dumps({'view': p.observe(), 'events': p.events(), 'actions': p.legal_actions()})
            for name in ('target_selection', 'AutomaticTargetProof', 'rng_before', 'legal_ids', 'information_json', 'before_state'):
                self.assertNotIn(name, value)
        self.portable(game, 'target-privacy')

    def test_missing_original_target_finish_proof_is_rejected(self):
        self.negative(lambda s: self.target_finisher(s)['fields'].__setitem__('target_proof', None))

    def test_original_legal_pool_cannot_be_trimmed_even_if_enemy_draw_stays_same(self):
        def mutate(s):
            part = self.target_finisher(s)['fields']['target_proof']['fields']['selection']['fields']['partition']['fields']
            friendly = next(i for i in part['legal_ids']['tuple'] if i not in part['enemy_ids']['tuple'])
            part['legal_ids']['tuple'].remove(friendly)
        self.negative(mutate)

    def test_original_target_rng_after_cannot_be_replaced(self):
        def mutate(s):
            rng = s['state']['cast_history'][-1]['target_selection']['rng_after']; rng[1][0] ^= 1
        self.negative(mutate)

    def test_original_target_proof_cannot_borrow_future_action_clock(self):
        def mutate(s):
            state = self.target_finisher(s)['fields']['target_proof']['fields']['before_state']['state']
            state['action_number'] += 1
        self.negative(mutate)

    def test_original_player_visibility_cannot_be_dropped(self):
        self.negative(lambda s: self.target_finisher(s)['fields']['target_proof']['fields'].__setitem__('information_json', None),
            visibility='player', target_zone='hand')

    def test_receipt_codec_rejects_unknown_field(self):
        self.negative(lambda s: s['state']['cast_history'][-1]['target_selection'].update(extra=1))

    def test_old_schema112_is_rejected_instead_of_defaulting_the_new_cast_field(self):
        game = self.launched(); snapshot = game.snapshot(); snapshot['schema_version'] = 112
        with self.assertRaisesRegex(SnapshotError, '1 through 265'):
            Game.from_snapshot(snapshot, make_registry(**self.config), make_mechanics())

    def test_automatic_condition_clocks_cannot_be_changed_while_waiting(self):
        game = self.launched(); bad = game.snapshot()
        self.assertTrue(game.state.cast_history[-1].combo)
        bad['state']['cast_history'][-1]['combo'] = False; self.rehash(bad)
        with self.assertRaisesRegex(SnapshotError, 'original condition clocks'):
            Game.from_snapshot(bad, make_registry(**self.config), make_mechanics())
        self.portable(game, 'original-condition-clocks')

    def test_stored_caster_keeps_owner_one_while_controller_two_defines_enemy(self):
        game = self.launched(route='stored', executor=2); cast = game.state.cast_history[-1]
        source = game.state.entities[cast.source_id]
        self.assertEqual((source.owner, source.controller), (1, 2))
        self.assertEqual(cast.target_selection.partition.source_controller, 2)
        self.assertEqual(game.state.entities[cast.target_id].controller, 1)
        branches = (game, *self.portable(game, 'actual-owner-controller-separated'))
        for branch in branches:
            choice = branch.state.pending_choice
            self.assertEqual(choice.player_id, 2)
            branch.apply(SelectChoice(2, choice.id, ('ok',)))
        for branch in branches: self.assertEqual(branch.snapshot(), game.snapshot())
        self.portable(game, 'other-controller-resumed')
