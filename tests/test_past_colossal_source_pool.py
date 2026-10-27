"""Real CATA generation uses the full Colossal view and its native followups."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
from pathlib import Path
from random import Random
import tempfile
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import past_colossal_source_pool as binding
from hs_sim.cards.simple_followup_p89_cards import QUERIES as OTHER_QUERIES
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayerSetup,
    ResolutionError, Scenario, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import ChoiceOption, Destroy, InvokeBehavior, RequestChoice
from hs_sim.engine.issued_spell_sets import QUERY as TOKI_QUERY
from hs_sim.engine.model import CardClass
from hs_sim.engine.pools import PoolQuery, resolve_candidates, sample_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.serialization import canonical_hash
from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format
from hs_sim.local_pool_format import build_cn37_local_pool_format, load_bindings
from hs_sim.targets import TargetValidationError, canonical_digest
from tools import card_batch as batch

SOURCE, POOL = binding.SOURCE, binding.POOL
UNIT, WATCH, KILL, FAULT = ('k585.'+v for v in ('unit', 'watch', 'kill', 'fault'))


@lru_cache(None)
def host(mode='normal', role='writer'):
    f = build_cn37_local_pool_format(); r = f.registry
    def fail(c): raise ResolutionError('K585 deliberate delivery failure')
    def watch(c):
        e = c.event
        if e.player_id != c.player_id or e.target_id is None: return ()
        if c.state.entities[e.target_id].card_id not in binding.load_batch()['member_ids']: return ()
        if mode == 'failure': return (InvokeBehavior(FAULT, c.source_id, c.player_id),)
        if mode != 'waiting': return ()
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fault', 'Fail', (InvokeBehavior(FAULT, c.source_id, c.player_id),))), c.source_id),)
    r.register_behavior(FAULT, fail); r.register_behavior(WATCH, watch)
    r.register_behavior(KILL, lambda c: (Destroy(c.target_id, c.source_id),))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=2, health=3))
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=30,
        triggers=(TriggerSpec('card_added_to_hand', WATCH),)))
    r.register_card(CardDefinition(KILL, KILL, CardType.SPELL, on_play=KILL, requires_target=True))
    if mode == 'missing': r._cards.pop('TSC_029')
    r.validate(); return f


def candidates():
    f = host()
    return resolve_candidates(f.registry, f.context, POOL, binding.QUERY,
        source_card_id=SOURCE, player_id=1, exclude_source_by_rule=True)


def seed_for(card_id):
    rows = candidates()
    return next(seed for seed in range(1000)
        if sample_candidates(Random(seed), rows, 1, replacement=True) == (card_id,))


class PastColossalSourcePoolTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(lambda mode, role: host(mode, role).registry)
    mode = 'normal'

    def game(self, desired='TSC_962', *, player=1, hero='HERO_09', mode='normal', enemy=(), hand=()):
        self.mode = mode; f = host(mode)
        players = tuple(PlayerSetup(hero if p == player else 'HERO_08',
            hand=(SOURCE, *hand) if p == player else (),
            board=((WATCH,) if mode in ('waiting','failure') else ()) if p == player else enemy,
            deck=(UNIT,)*12, mana=60, max_mana=60, mana_cap=60) for p in (1,2))
        return Game.from_scenario(Scenario(players, active_player=player,
            seed=seed_for(desired), generation_context=f.context), f.registry)

    def board(self, g, player=1):
        return [g.state.entities[i].card_id for i in g.state.players[player].board]

    def test_full_original_reference_producer_and_all_native_dependency_pins(self):
        data = binding.load_batch(); f = host()
        reference = batch.read(data['reference_document'])
        self.assertEqual(data['source_producer'], reference['source_producer'])
        self.assertEqual(data['member_ids'], reference['candidate_ids'])
        self.assertEqual(len(reference['candidate_records']), 13)
        self.assertEqual(len(reference['official_observations']), 26)
        self.assertEqual(len(data['native_pins']), 42)
        for row in data['native_pins']:
            self.assertEqual(canonical_digest(asdict(f.registry.card(row['card_id']))), row['definition_sha256'])
        raw = {v['record']['id']: v['record'] for v in reference['candidate_records']}
        for face in reference['official_observations']:
            batch.check_face(raw[face['card_id']], face['face'], face['locale'])
        self.assertFalse(data['membership_uses_executable_coverage'])
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])
        self.assertFalse(reference['runtime_bindings_added'])  # The historical reference stays untouched.

    def test_extended_union_keeps_both_exact_original_orders_identity_weights_and_five_scopes(self):
        f = host(); data = binding.load_batch(); pool = f.registry.pool(POOL, f.context)
        self.assertEqual([v.card_id for v in pool.members if v.card_id in data['merged_member_ids']], data['merged_member_ids'])
        self.assertEqual(len(pool.members), 72); self.assertTrue(all(v.weight == 1 for v in pool.members))
        self.assertEqual([v.card_id for v in candidates()], data['member_ids'])
        frontier = resolve_candidates(f.registry, f.context, POOL, binding.FRONTIER_QUERY,
            current_class=CardClass.DRUID, source_card_id='GDB_857', exclude_source_by_rule=True)
        self.assertEqual([v.card_id for v in frontier], data['frontier_member_ids'])
        self.assertEqual(set(data['member_ids']) & set(data['frontier_member_ids']), {'TID_712'})
        self.assertEqual(len(f.registry.generation_scopes), 5)
        scope = next(s for s in f.registry.generation_scopes.values() if s.source_card_id == SOURCE)
        self.assertIsNone(scope.current_class); self.assertEqual(scope.query, binding.QUERY)
        self.assertIn(POOL, load_bindings()['partially_scoped_pool_ids'])
        self.assertEqual(f.registry.pool_card('TSC_639').metadata, f.registry.card('TSC_639').metadata)

    def test_actual_complete_source_can_deliver_and_play_each_of_all_thirteen_native_bodies(self):
        for desired in binding.load_batch()['member_ids']:
            with self.subTest(card=desired):
                g = self.game(desired, hand=(KILL,)); probe = Random(); probe.setstate(g._rng.getstate())
                self.assertEqual(sample_candidates(probe, candidates(), 1, replacement=True), (desired,))
                source = self.play(g, SOURCE)
                self.assertEqual(g._rng.getstate(), probe.getstate())
                self.assertEqual(g.state.players[1].mana, 54)
                reward = self.entity(g, desired)
                self.assertEqual(quote_unselected_cost(g.state, g.registry, reward).amount, g.registry.card(desired).cost)
                self.play(g, KILL, source)  # Leave all seven ordinary slots for Ozaumat's six appendages.
                root = self.play(g, desired)
                while g.state.pending_choice is not None:
                    self.choose(g, g.state.pending_choice.options[0].id)
                record = next(v for v in g.state.colossal_history if v.entity_id == root)
                self.assertTrue(record.completed); self.assertTrue(all(v is not None for v in record.limbs))
                self.assertEqual(len(record.limbs), len(g.registry.card(desired).colossal))
                self.assertEqual(len(g.state.players[1].board), 1+len(g.registry.card(desired).colossal))
                self.assertEqual(g.state.play_history[-1].cost, g.registry.card(desired).cost)
        self.portable(g)

    def test_same_full_source_works_for_different_hero_classes_and_both_seats(self):
        for player, hero in ((1,'HERO_06'), (2,'HERO_08')):
            with self.subTest(player=player, hero=hero):
                g = self.game('TID_712', player=player, hero=hero)
                self.play(g, SOURCE, player=player); self.play(g, 'TID_712', player=player)
                self.assertEqual(g.state.players[player].mana, 44)
                self.assertEqual(self.board(g, player), [SOURCE,'TID_712t','TID_712','TID_712t2'])

    def test_generated_nellie_uses_full_real_pirates_then_ship_delivers_three_one_cost_cards(self):
        g = self.game('TSC_660', hero='HERO_09', hand=(KILL,))
        self.play(g, SOURCE); self.play(g, 'TSC_660'); selected = []
        for _ in range(3):
            q = g.state.pending_choice
            self.assertEqual(len(q.options), 3)
            selected.append(q.options[0].card_id); self.choose(g, q.options[0].id)
        self.assertFalse(any(g.state.entities[i].card_id in selected for i in g.state.players[1].hand))
        self.play(g, KILL, self.entity(g,'TSC_660t',zone='board').id)
        cards = [g.state.entities[i] for i in g.state.players[1].hand]
        self.assertEqual([e.card_id for e in cards], selected)
        self.assertEqual([quote_unselected_cost(g.state,g.registry,e).amount for e in cards], [1,1,1])
        self.portable(g)

    def test_generated_gigafin_destroys_then_returns_real_enemy_minions(self):
        g = self.game(enemy=(UNIT,UNIT), hand=(KILL,)); original = tuple(g.state.players[2].board)
        self.play(g,SOURCE); root = self.play(g,'TSC_962')
        self.assertEqual(self.board(g,2), [])
        self.assertEqual([v.entity_id for v in g.state.death_history], list(original))
        self.assertEqual(len(g.state.consumed_card_history), 2)
        self.play(g,KILL,root)
        self.assertEqual(self.board(g,2), [UNIT,UNIT])
        self.assertFalse(set(original) & set(g.state.players[2].board)); self.portable(g)

    def test_generated_xhilag_deals_eight_then_twelve_after_original_owner_start(self):
        g = self.game('TSC_219'); self.play(g,SOURCE); self.play(g,'TSC_219')
        self.assertEqual(len(g.state.players[1].board), 6)
        enemy = g.state.players[2].hero_id
        g.apply(EndTurn(1)); self.assertEqual(g.state.entities[enemy].health, 22)
        g.apply(EndTurn(2)); self.portable(g)
        g.apply(EndTurn(1)); self.assertEqual(g.state.entities[enemy].health, 10)

    def test_generated_glugg_retains_original_friendly_death_growth_after_metadata_addition(self):
        g = self.game('TSC_639', hand=(KILL,)); self.play(g,SOURCE); parent = self.play(g,'TSC_639')
        tail = self.entity(g,'TSC_639t',zone='board'); root = g.state.entities[parent]
        before = (root.attack,root.max_health); gain = (tail.attack,tail.max_health)
        self.play(g,KILL,tail.id); root = g.state.entities[parent]
        self.assertEqual((root.attack,root.max_health), (before[0]+gain[0],before[1]+gain[1]))

    def test_generation_notification_wait_restores_replays_and_invalid_branch_is_atomic(self):
        g = self.game('TSC_962', mode='waiting'); self.play(g,SOURCE)
        saved = g.snapshot(); restored = self.portable(g)
        self.assertEqual(self.entity(g,'TSC_962').zone, Zone.HAND)
        with self.assertRaises(ResolutionError): self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for current in (g,restored):
            self.choose(current); self.play(current,'TSC_962')
        self.assertEqual(g.snapshot(),restored.snapshot()); self.portable(g)

    def test_late_delivery_failure_rolls_back_payment_generation_events_and_rng(self):
        g = self.game(mode='failure'); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate delivery failure'): self.play(g,SOURCE)
        self.assertEqual(g.snapshot(), saved)

    def test_missing_eligible_definition_rejects_before_rng_without_removing_pool_member(self):
        g = self.game(mode='missing'); saved = g.snapshot(); f = host('missing')
        self.assertEqual(len(f.registry.pool(POOL,f.context).members),72)
        with self.assertRaisesRegex(ResolutionError,'TSC_029'): self.play(g,SOURCE)
        self.assertEqual(g.snapshot(),saved)

    def test_eight_other_past_views_and_wrong_queries_stay_closed_with_actual_spell_rollback(self):
        f = host()
        for source, query in OTHER_QUERIES.items():
            if source in (SOURCE,'TIME_016'): continue
            with self.subTest(source=source), self.assertRaises(UnsupportedDefinitionError):
                resolve_candidates(f.registry,f.context,POOL,query,current_class=CardClass.MAGE,
                    source_card_id=source,exclude_source_by_rule=True)
        with self.assertRaises(UnsupportedDefinitionError):
            resolve_candidates(f.registry,f.context,'constructed.past.spells',TOKI_QUERY,
                current_class=CardClass.MAGE,source_card_id='TIME_861',exclude_source_by_rule=True)
        with self.assertRaises(UnsupportedDefinitionError):
            resolve_candidates(f.registry,f.context,POOL,PoolQuery(kinds=(CardType.MINION,)),
                source_card_id=SOURCE,exclude_source_by_rule=True)
        for source in ('TIME_707','TIME_861'):
            g = self.game(hand=(source,)); saved = g.snapshot()
            with self.assertRaisesRegex(ResolutionError,'Unreviewed generation scope'): self.play(g,source)
            self.assertEqual(g.snapshot(),saved)

    def test_original_launch_metadata_deck_policy_and_unknown_source_are_not_silently_extended(self):
        f = host(); old = build_cn37_launch_candidate_format()
        self.assertNotIn('TSC_639',old.registry.pool_cards)
        self.assertEqual(f.root_card_ids,old.root_card_ids)
        self.assertEqual(f.policy.allowed_card_ids,old.policy.allowed_card_ids)
        self.assertEqual(f.policy.banned_card_ids,old.policy.banned_card_ids)
        with self.assertRaises(UnsupportedDefinitionError): old.registry.pool(POOL,old.context)
        with self.assertRaises(UnsupportedDefinitionError):
            resolve_candidates(f.registry,f.context,POOL,binding.QUERY,source_card_id='TIME_016',exclude_source_by_rule=True)

    def test_original_reference_and_manifest_tampering_are_rejected(self):
        data = binding.load_batch(); data['member_ids'].pop()
        manifest = load_bindings(); manifest['cata_colossal_binding']['member_count'] = 12
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'changed.json'; path.write_text(json.dumps(data),encoding='utf8')
            with patch.object(binding,'BATCH_PATH',path), self.assertRaises(TargetValidationError): binding.load_batch()
            path.write_text(json.dumps(manifest),encoding='utf8')
            with patch('hs_sim.local_pool_format.MANIFEST_PATH',path), self.assertRaises(TargetValidationError): load_bindings()

    def test_late_native_dependency_or_printed_metadata_failure_leaves_input_registry_unchanged(self):
        from hs_sim.cards.past_source_scoped_pools import local_pools
        f = build_cn37_launch_candidate_format(); r = f.registry
        last = binding.load_batch()['native_pins'][-1]['card_id']
        r._cards[last] = replace(r.card(last),health=r.card(last).health+1)
        before = r.fingerprint()
        with self.assertRaises(TargetValidationError): binding.merge_pools(r,f.context,local_pools(r,f.context))
        self.assertEqual(r.fingerprint(),before); self.assertNotIn('TSC_639',r.pool_cards)
        f = build_cn37_launch_candidate_format(); r = f.registry
        r.register_pool_card(replace(host().registry.pool_card('TSC_639'),cost=8)); before = dict(r.pool_cards)
        with self.assertRaises(TargetValidationError): binding.missing_metadata(r)
        self.assertEqual(dict(r.pool_cards),before)

    def test_rehashed_unknown_target_cannot_borrow_current_inventory_for_next_real_generation(self):
        g = self.game(hand=(SOURCE,)); self.play(g,SOURCE); saved = g.snapshot()
        saved['generation_context']['target_id'] = 'cn37-local-special-pools-v9-3b5f304928e2409f'
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        restored = Game.from_snapshot(saved,host('normal','independent-reader').registry)
        before = restored.snapshot()
        with self.assertRaises(ResolutionError): self.play(restored,SOURCE)
        self.assertEqual(restored.snapshot(),before)

    def test_generated_hand_is_private_and_inventory_or_scope_proof_never_enters_player_dto(self):
        g = self.game('TSC_219',player=2); self.play(g,SOURCE,player=2)
        self.assertIn('TSC_219',json.dumps(g.observe(2)))
        self.assertNotIn('TSC_219',json.dumps(g.observe(1)))
        for p in (1,2):
            view = json.dumps(g.observe(p))
            for key in ('generation_scopes','merged_member_ids','inventory_sha256','native_pins','rng_state'):
                self.assertNotIn('"'+key+'"',view)


if __name__ == '__main__': unittest.main()
