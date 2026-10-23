"""Pre-delivery observer eligibility through actual Discover producers."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.native_discovery_cost_cards import CARD as COST_CARD, register_native_discovery_cost_cards
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game,
    PlayerSetup, Registry, Scenario, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy, InvokeBehavior,
    RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.discovery_trigger_sources import DiscoveryTriggerProfile
from hs_sim.engine.discovery_delivery import COMPLETED
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import ChoicePurpose, Rarity, SummonQuantitySpec
from hs_sim.engine.pools import (DiscoverFromPool, GenerateFromPool, GenerationContext,
    PoolCard, PoolDefinition, PoolMember, PoolQuery)
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.engine.zones import CardReference

P = 'k476.'
HERO, OBS, LEGACY, PLAIN, TOKEN, DOUBLE, WATCH = (
    P+x for x in ('hero', 'observer', 'legacy', 'plain', 'token', 'double', 'watch'))
DISC, HAND, EACH, ALL, DEAD, AUTO, GEN, MENU, KILL, FAIL, REENTER = (
    P+x for x in ('discover', 'hand', 'each', 'all', 'dead', 'auto', 'generate', 'menu', 'kill', 'fail', 'reenter'))
POOL = P+'pool'
REFRESH, CONTROL, SPELL_POOL = P+'refresh', P+'control', P+'spell-pool'
CONTEXT = GenerationContext('k476-observer-qualification', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = Registry('k476-'+mode)
    register_native_discovery_cost_cards(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=30,
        metadata=replace(META, classes=(CardClass.MAGE,))))
    r.register_card(CardDefinition(PLAIN, PLAIN, CardType.MINION, health=3, metadata=META))
    r.register_card(CardDefinition(TOKEN, TOKEN, CardType.MINION, health=1, metadata=META))
    def fail(c): raise ResolutionError('K476 deliberate observer failure')
    r.register_behavior(FAIL, fail)
    r.register_behavior(REENTER, lambda c: (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),
        c.player_id, cause=SummonCause.capture(c)),))
    r.register_behavior(OBS, lambda c: () if c.event.player_id != c.player_id else
        (InvokeBehavior(FAIL, c.source_id, c.player_id),) if mode == 'trigger_fail' else
        (AddToHand(c.player_id, TOKEN, c.source_id),))
    r.register_card(CardDefinition(OBS, OBS, CardType.MINION, cost=1, attack=1, health=2,
        metadata=META, triggers=(TriggerSpec(COMPLETED, OBS),)))
    def choices(c):
        old = c.state.card_discovery_history[-1].trigger_sources
        original = old[0].source.entity_id if old else None
        options = [ChoiceOption('continue', 'Continue'), ChoiceOption('fail', 'Fail',
            (InvokeBehavior(FAIL, c.source_id, c.player_id),))]
        if original is not None:
            options.extend((ChoiceOption('kill', 'Remove original', (Destroy(original, c.source_id),)),
                ChoiceOption('mute', 'Silence original', (Silence(original),)),
                ChoiceOption('morph', 'Transform original', (Transform(original, PLAIN),)),
                ChoiceOption('reenter', 'Return and recruit original', (ReturnToHand(original),
                    InvokeBehavior(REENTER, c.source_id, c.player_id, original)))))
        return (RequestChoice(c.player_id, tuple(options), c.source_id),)
    def legacy(c):
        if c.event.player_id != c.player_id: return ()
        return choices(c) if mode == 'completion_wait' else (AddToHand(c.player_id, TOKEN, c.source_id),)
    r.register_behavior(LEGACY, legacy)
    r.register_card(CardDefinition(LEGACY, LEGACY, CardType.MINION, health=5,
        metadata=META, triggers=(TriggerSpec(COMPLETED, LEGACY),)))
    r.register_card(CardDefinition(DOUBLE, DOUBLE, CardType.MINION, health=5,
        metadata=META, summon_quantities=(SummonQuantitySpec(2),)))
    for cid in (OBS, PLAIN, LEGACY): r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL, 'v1', CONTEXT.target_id, CONTEXT.mode,
        tuple(PoolMember(cid) for cid in (OBS, PLAIN, LEGACY)), complete=True))
    r.register_behavior(P+'noop', lambda c: ())
    spells = tuple(P+'spell'+str(i) for i in range(3))
    for cid in spells:
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=P+'noop',
            metadata=replace(META, collectible=True, rarity=Rarity.COMMON)))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_card(CardDefinition(CONTROL, CONTROL, CardType.SPELL, choice_only=True, metadata=META))
    r.register_pool(PoolDefinition(SPELL_POOL, 'v1', CONTEXT.target_id, CONTEXT.mode,
        tuple(PoolMember(cid) for cid in spells), complete=True))
    def discover(c, **kw):
        return DiscoverFromPool(c.player_id, POOL, source_id=c.source_id,
            destination='board', cause=SummonCause.capture(c), **kw)
    def resurrect(c):
        d = next(d for d in reversed(c.state.death_history) if d.card_id == OBS)
        return (RequestChoice(c.player_id, (ChoiceOption('revive', 'Revive',
            (ResurrectMinion(c.player_id, d.id, source_id=c.source_id, cause=SummonCause.capture(c)),), card_id=OBS),),
            c.source_id, purpose=ChoicePurpose.CARD_DISCOVERY),)
    scripts = {
        DISC: lambda c: (discover(c),),
        HAND: lambda c: (DiscoverFromPool(c.player_id, POOL, source_id=c.source_id),),
        EACH: lambda c: (discover(c, discoveries=2),),
        ALL: lambda c: (discover(c, discoveries=2, delivery='after_all'),),
        DEAD: resurrect,
        AUTO: lambda c: (CastSpell(c.player_id, DISC, c.source_id),),
        GEN: lambda c: (GenerateFromPool(c.player_id, POOL, source_id=c.source_id),),
        MENU: lambda c: (RequestChoice(c.player_id, (ChoiceOption('plain', 'Plain',
            (AddToHand(c.player_id, PLAIN, c.source_id),), card_id=PLAIN),), c.source_id),),
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        REFRESH: lambda c: (DiscoverFromPool(c.player_id, SPELL_POOL,
            PoolQuery(kinds=(CardType.SPELL,), collectible=True), source_id=c.source_id,
            refresh_card_id=CONTROL),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            requires_target=cid == KILL, metadata=META))
    def watch(c):
        if mode != 'entry_wait' or not c.state.card_discovery_history: return ()
        original = c.state.card_discovery_history[-1].trigger_sources
        if c.event.target_id in {s.source.entity_id for s in original}: return ()
        return choices(c)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=5,
        metadata=META, triggers=(TriggerSpec('minion_summoned', WATCH),)))
    if mode != 'unprofiled': r.register_discovery_trigger_profile(DiscoveryTriggerProfile(OBS, OBS))
    r.validate(); return r


def rehash(s):
    s['events_hash'] = canonical_hash(s['events'])
    s['state_hash'] = canonical_hash({k:v for k,v in s.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return s


class DiscoveryTriggerSourceTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(DISC,), *, board=(), enemy=(), mode='normal'):
        self.mode = mode
        if mode == 'entry_wait': board = (*board, WATCH)
        return Game.from_scenario(Scenario((PlayerSetup(HERO, hand=hand, board=board, deck=(PLAIN,)*5,
            mana=20, max_mana=20, mana_cap=20), PlayerSetup(HERO, board=enemy, deck=(PLAIN,)*5,
            mana=20, max_mana=20, mana_cap=20)), seed=476, generation_context=CONTEXT), fixture(mode))

    def pick(self, g, cid=PLAIN):
        q = g.state.pending_choice
        self.choose(g, next(o.id for o in q.options if o.card_id == cid))

    def tokens(self, g, player=1):
        return [g.state.entities[i] for i in g.state.players[player].hand if g.state.entities[i].card_id == TOKEN]

    def test_source_existing_before_delivery_triggers_once(self):
        g = self.game(board=(OBS,)); old = g.state.players[1].board[0]
        self.play(g, DISC); self.pick(g)
        self.assertEqual([s.source.entity_id for s in g.state.card_discovery_history[0].trigger_sources], [old])
        self.assertEqual([t.origin_entity_id for t in self.tokens(g)], [None])
        self.assertEqual(len(self.tokens(g)), 1)

    def test_new_observer_summoned_by_same_discovery_does_not_trigger_itself(self):
        g = self.game(); self.play(g, DISC); self.pick(g, OBS)
        self.assertFalse(g.state.card_discovery_history[0].trigger_sources); self.assertFalse(self.tokens(g))

    def test_both_new_quantity_bodies_are_excluded_from_original_window(self):
        g = self.game(board=(DOUBLE,)); self.play(g, DISC); self.pick(g, OBS)
        self.assertEqual(sum(g.state.entities[i].card_id == OBS for i in g.state.players[1].board), 2)
        self.assertFalse(self.tokens(g)); self.portable(g)

    def test_existing_source_triggers_once_with_two_new_quantity_bodies(self):
        g = self.game(board=(OBS, DOUBLE)); self.play(g, DISC); self.pick(g, OBS)
        self.assertEqual(len(g.state.card_discovery_history[0].trigger_sources), 1)
        self.assertEqual(len(self.tokens(g)), 1)

    def test_discovered_resurrection_cannot_add_returned_source_to_own_roster(self):
        g = self.game((KILL, DEAD), board=(OBS,)); old = g.state.players[1].board[0]
        self.play(g, KILL, old); self.play(g, DEAD); self.choose(g, 'revive')
        self.assertFalse(g.state.card_discovery_history[0].trigger_sources); self.assertFalse(self.tokens(g))
        self.assertEqual(sum(g.state.entities[i].card_id == OBS for i in g.state.players[1].board), 1)

    def test_unprofiled_observers_keep_existing_completion_capture_policy(self):
        g = self.game(); self.play(g, DISC); self.pick(g, LEGACY)
        self.assertEqual(len(self.tokens(g)), 1); self.assertFalse(g.state.card_discovery_history[0].trigger_sources)

    def test_empty_profile_table_preserves_existing_ordinary_trigger_behavior(self):
        g = self.game(mode='unprofiled'); self.play(g, DISC); self.pick(g, OBS)
        self.assertEqual(len(self.tokens(g)), 1); self.assertFalse(g.state.card_discovery_history[0].trigger_sources)

    def test_multiple_original_observers_follow_existing_physical_listener_order(self):
        g = self.game(board=(OBS, LEGACY, OBS)); original = tuple(g.state.players[1].board)
        self.play(g, DISC); self.pick(g)
        sources = [e.source_id for e in g.events if e.kind == 'card_created' and e.source_id in original]
        self.assertEqual(sources, list(original)); self.assertEqual(len(self.tokens(g)), 3)

    def test_enemy_observer_is_not_in_friendly_original_roster(self):
        g = self.game(board=(OBS,), enemy=(OBS,)); self.play(g, DISC); self.pick(g)
        self.assertEqual(len(g.state.card_discovery_history[0].trigger_sources), 1)
        self.assertEqual(len(self.tokens(g)), 1); self.assertFalse(self.tokens(g, 2))

    def test_each_delivery_allows_new_source_only_for_later_actual_selection(self):
        g = self.game((EACH,)); self.play(g, EACH); self.pick(g, OBS)
        self.assertFalse(self.tokens(g)); self.assertIsNotNone(g.state.pending_choice)
        self.pick(g, PLAIN); self.assertEqual(len(self.tokens(g)), 1)
        self.assertEqual([len(r.trigger_sources) for r in g.state.card_discovery_history], [0, 1])

    def test_after_all_selections_do_not_backfill_later_delivery_sources(self):
        g = self.game((ALL,)); self.play(g, ALL); self.pick(g, OBS); self.pick(g, PLAIN)
        self.assertEqual([len(r.trigger_sources) for r in g.state.card_discovery_history], [0, 0])
        self.assertFalse(self.tokens(g))

    def test_hand_delivery_keeps_existing_board_source_eligibility(self):
        g = self.game((HAND,), board=(OBS,)); self.play(g, HAND); self.pick(g, OBS)
        self.assertEqual(len(self.tokens(g)), 1)
        self.assertEqual(sum(g.state.entities[i].card_id == OBS for i in g.state.players[1].hand), 1)

    def test_automatic_choice_uses_same_pre_delivery_source_roster(self):
        g = self.game((AUTO,), board=(OBS,)); old = g.state.players[1].board[0]; self.play(g, AUTO)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len([e for e in g.events if e.kind == 'card_created' and e.source_id == old]), 1)
        self.assertEqual(len(g.state.card_discovery_history[0].trigger_sources), 1); self.portable(g)

    def test_generate_and_non_discovery_menu_do_not_reserve_observers(self):
        g = self.game((GEN, MENU), board=(OBS,)); self.play(g, GEN); self.play(g, MENU); self.choose(g, 'plain')
        self.assertFalse(g.state.card_discovery_history); self.assertFalse(self.tokens(g))

    def test_original_source_removed_before_completion_does_not_trigger(self):
        g = self.game(board=(OBS,), mode='entry_wait'); self.play(g, DISC); self.pick(g)
        self.assertIsNotNone(g.state.pending_choice); self.choose(g, 'kill')
        self.assertFalse(self.tokens(g)); self.assertEqual(len(g.state.card_discovery_history[0].trigger_sources), 1)

    def test_silenced_or_transformed_source_cannot_reuse_original_ability(self):
        for key in ('mute', 'morph'):
            with self.subTest(key=key):
                g = self.game(board=(OBS,), mode='entry_wait'); self.play(g, DISC); self.pick(g)
                self.choose(g, key); self.assertFalse(self.tokens(g))

    def test_reentered_same_entity_cannot_reuse_original_presence(self):
        g = self.game(board=(OBS,), mode='entry_wait'); old = g.state.players[1].board[0]
        self.play(g, DISC); self.pick(g); self.choose(g, 'reenter')
        self.assertIn(old, g.state.players[1].board); self.assertFalse(self.tokens(g))
        self.assertGreater(g.state.entities[old].zone_epoch, g.state.card_discovery_history[0].trigger_sources[0].source.zone_epoch)

    def test_waiting_before_completion_restores_original_roster_and_continues_once(self):
        g = self.game(board=(OBS,), mode='entry_wait'); self.play(g, DISC); self.pick(g)
        restored = self.portable(g); self.choose(g); self.choose(restored)
        self.assertEqual(restored.snapshot(), g.snapshot()); self.assertEqual(len(self.tokens(g)), 1)

    def test_already_captured_ordinary_trigger_survives_earlier_listener_removal(self):
        g = self.game(board=(LEGACY, OBS), mode='completion_wait'); self.play(g, DISC); self.pick(g)
        self.assertIsNotNone(g.state.pending_choice); restored = self.portable(g)
        self.choose(g, 'kill'); self.choose(restored, 'kill')
        self.assertEqual(restored.snapshot(), g.snapshot()); self.assertEqual(len(self.tokens(g)), 1)

    def test_waiting_failure_rolls_back_roster_allocations_and_choice(self):
        g = self.game(board=(OBS,), mode='entry_wait'); self.play(g, DISC); self.pick(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before); self.choose(g); self.assertEqual(len(self.tokens(g)), 1)

    def test_completed_trigger_failure_rolls_back_delivery_and_original_roster(self):
        g = self.game(mode='trigger_fail', board=(OBS,)); self.play(g, DISC); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g)
        self.assertEqual(g.snapshot(), before); self.assertFalse(g.state.card_discovery_history)

    def test_genuine_refresh_control_never_reserves_discovery_observers(self):
        g = self.game((REFRESH,), board=(OBS,)); self.play(g, REFRESH); self.choose(g, 'refresh')
        row = g.state.card_discovery_history[0]
        self.assertTrue(row.is_control); self.assertFalse(row.trigger_sources); self.assertFalse(self.tokens(g))
        self.portable(g)

    def test_qualification_itself_does_not_consume_randomness(self):
        a = self.game(); self.play(a, DISC); self.pick(a, OBS)
        b = self.game(mode='unprofiled'); self.play(b, DISC); self.pick(b, OBS)
        self.assertEqual(a._rng.getstate(), b._rng.getstate())

    def test_modified_or_missing_original_roster_is_rejected_on_restore(self):
        g = self.game(board=(OBS,)); self.play(g, DISC); self.pick(g); saved = g.snapshot()
        bad = deepcopy(saved); bad['state']['card_discovery_history'][0]['trigger_sources'] = []
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), fixture())
        bad = deepcopy(saved); s = bad['state']['card_discovery_history'][0]['trigger_sources'][0]
        s['next_attachment_id'] = 10**9
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), fixture())

    def test_private_source_roster_does_not_enter_player_observations(self):
        g = self.game(board=(OBS,)); self.play(g, DISC); self.pick(g)
        for p in (1, 2): self.assertNotIn('"trigger_sources"', json.dumps(g.for_player(p).observe()))

    def test_nonempty_roster_survives_real_discovery_conditioned_payment_and_replay(self):
        g = self.game((DISC, COST_CARD), board=(OBS,), enemy=(PLAIN,))
        self.play(g, DISC); self.pick(g); before = g.state.players[1].mana
        self.play(g, COST_CARD, g.state.players[2].board[0])
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (0, before))
        self.assertEqual(len(g.state.card_discovery_history[0].trigger_sources), 1)
        self.portable(g)

    def test_nonempty_roster_roundtrips_inside_original_offered_execution_selection(self):
        from hs_sim.engine.offered_card_selection import capture, selection_from_dict, validate_origin
        g = self.game(board=(OBS,)); self.play(g, DISC); self.pick(g)
        selection = capture(g.state, fixture(), 1, g._rng.getstate())
        restored = selection_from_dict(json.loads(json.dumps(asdict(selection))))
        self.assertEqual(restored, selection); validate_origin(restored, g.state, fixture())
        self.assertEqual(len(restored.discovery.trigger_sources), 1)

    def test_profile_requires_native_trigger_and_rejects_duplicate_registration(self):
        r = Registry('k476-bad-profile'); r.register_behavior(OBS, lambda c: ())
        r.register_card(CardDefinition(OBS, OBS, CardType.MINION, health=2, triggers=(TriggerSpec(COMPLETED, OBS),)))
        first = r.fingerprint(); r.register_discovery_trigger_profile(DiscoveryTriggerProfile(OBS, OBS))
        self.assertNotEqual(first, r.fingerprint())
        with self.assertRaises(ValueError): r.register_discovery_trigger_profile(DiscoveryTriggerProfile(OBS, OBS))
        r.register_card(CardDefinition(PLAIN, PLAIN, CardType.MINION, health=2))
        with self.assertRaises(ValueError): r.register_discovery_trigger_profile(DiscoveryTriggerProfile(PLAIN, OBS))

    def test_prior_snapshot_schema_is_rejected(self):
        g = self.game(); old = g.snapshot(); old['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError): Game.from_snapshot(old, fixture())
