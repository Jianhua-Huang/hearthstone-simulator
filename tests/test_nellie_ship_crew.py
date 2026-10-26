"""Nellie uses full host Pirate discovery and the original physical Ship."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.nellie_ship_crew import CARD, SHIP, PROFILE_ID, load_batch, register_nellie_ship_crew
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game,
    IllegalAction, PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError,
    TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.colossal_crew import ColossalCrewTarget, PROFILE, QUERY, validate_spec
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.pools import DiscoverFromPool, GenerationContext, PoolDefinition, PoolMember, resolve_candidates
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k583.'
UNIT, WATCH, KILL, QUIET, COPY, BASE, BOUNCE, GIVE, REPEAT, UNKNOWN = (
    P+x for x in ('unit', 'watch', 'kill', 'silence', 'copy', 'base', 'bounce', 'give', 'repeat', 'unknown-pirate'))
SOURCE = 'CATA_EVENT_000'
CONTEXT = GenerationContext(P+'explicit-native-adapter-fixture', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None)


@lru_cache(None)
def host(mode='normal', role='writer'):
    f = build_cn37_local_pool_format(); r = f.registry
    originals = [v for v in r.pools.values() if v.target_id == f.target_id and v.mode == f.context.mode]
    for pool in originals:
        if pool.id == 'constructed.past.cards' or mode in ('single', 'unknown') and pool.id == 'constructed.cards': continue
        r.register_pool(replace(pool, target_id=CONTEXT.target_id, mode=CONTEXT.mode))
    # The full thirteen-member source remains closed. This explicit one-card
    # fixture tests the native adapter; its Pirate domain normally stays full.
    r.register_pool(PoolDefinition('constructed.past.cards', P+'one-native-body',
        CONTEXT.target_id, CONTEXT.mode, (PoolMember(CARD),), complete=True))
    if mode in ('single', 'unknown'):
        original = next(v for v in originals if v.id == 'constructed.cards')
        members = (PoolMember('BE_734'),) if mode == 'single' else (*original.members, PoolMember(UNKNOWN))
        if mode == 'unknown': r.register_pool_card(replace(r.pool_card('CORE_NEW1_018'), card_id=UNKNOWN))
        r.register_pool(replace(original, target_id=CONTEXT.target_id, mode=CONTEXT.mode,
            version=P+'explicit-pirate-fixture:'+mode, members=members))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=1, health=20, metadata=META))
    def fail(c): raise ResolutionError('K583 deliberate crew failure')
    def redeploy(c):
        ship = next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == SHIP)
        return (SummonStoredCard(CardReference.capture(ship), c.player_id),)
    def watch(c):
        event = c.event
        if (mode == 'silence-before' and event.kind == 'minion_summoned' and
                event.player_id == c.player_id and c.state.entities[event.target_id].card_id == SHIP):
            return (Silence(event.target_id),)
        if event.player_id != c.player_id or event.kind != 'colossal_crew_remembered': return ()
        ship = c.state.entities[event.target_id]
        links = next(a.deathrattle_memory.discoveries for a in ship.abilities if a.deathrattle_memory is not None)
        if mode == 'late-failure' and len(links) == 3: return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        if len(links) != 1: return ()
        if mode == 'kill-ship': return (Destroy(ship.id, c.source_id),)
        if mode == 'kill-root': return (Destroy(event.source_id, c.source_id),)
        if mode == 'waiting': return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'continue'),
            ChoiceOption('bad', 'fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
            ChoiceOption('move', 'return and replay original Ship',
                (ReturnToHand(ship.id), InvokeBehavior(P+'redeploy', c.source_id, c.player_id))),
        ), c.source_id),)
        return ()
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'redeploy', redeploy); r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=tuple(TriggerSpec(kind, P+'watch') for kind in ('colossal_crew_remembered', 'minion_summoned'))))
    scripts = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        QUIET: lambda c: (Silence(c.target_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id),),
        BASE: lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        GIVE: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        REPEAT: lambda c: (TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]),
            c.source_id, choices='player'),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(TargetMode.REQUIRED, zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    r.validate(); return r


class NellieShipCrewTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(host)
    mode = 'normal'

    def game(self, hand=(), *, player=1, mode='normal', own=()):
        self.mode = mode
        if mode in ('late-failure', 'kill-ship', 'kill-root', 'waiting', 'silence-before'): own = (WATCH, *own)
        return Game.from_scenario(Scenario(tuple(PlayerSetup('HERO_09',
            hand=(SOURCE, *hand) if p == player else (), board=own if p == player else (),
            deck=(UNIT,)*12, mana=40, max_mana=40, mana_cap=40) for p in (1, 2)),
            active_player=player, seed=583, generation_context=CONTEXT), host(mode))

    def reward(self, g, player=1):
        self.play(g, SOURCE, player=player); return self.play(g, CARD, player=player)

    def pick(self, g):
        choice = g.state.pending_choice; option = choice.options[0]
        g.apply(SelectChoice(choice.player_id, choice.id, (option.id,))); return option.card_id

    def complete(self, g): return [self.pick(g) for _ in range(3)]

    def memory(self, g, ship):
        return next(a.deathrattle_memory for a in g.state.entities[ship].abilities if a.deathrattle_memory is not None)

    def ship(self, g, player=1): return self.entity(g, SHIP, player, 'board').id

    def hand(self, g, player=1): return [g.state.entities[i].card_id for i in g.state.players[player].hand]

    def costs(self, g, player=1):
        return [e['cost']['amount'] for e in g.observe(player)['players'][player-1]['hand']]

    def test_complete_raw_parent_ship_enchantments_faces_and_full_host_pirate_query(self):
        data = load_batch(); raw = data['cards'][0]['record']
        for face in data['official_observations']: batch.check_face(raw, face['face'], face['locale'])
        self.assertEqual([v['record']['id'] for v in data['evidence_only']], ['TSC_660e', 'TSC_660e2'])
        r = host(); rows = resolve_candidates(r, CONTEXT, 'constructed.cards', QUERY, current_class=CardClass.PRIEST, source_card_id=CARD)
        self.assertEqual(len(r.pool('constructed.cards', CONTEXT).members), 1322)
        self.assertEqual(len(rows), 8); self.assertTrue(all(v.card_id in r.cards for v in rows))
        target = ColossalCrewTarget(PROFILE_ID, 1, None, None, ())
        valid = DiscoverFromPool(1, 'constructed.cards', QUERY, source_id=1,
            prompt='发现一名奈利的海盗船员', discoveries=3, destination='memory', memory_target=target)
        validate_spec(valid)
        for changes in ({'discoveries': 1}, {'destination': 'hand'}, {'replacement': False}):
            with self.assertRaises(ValueError): replace(valid, **changes)

    def test_both_seats_real_paid_source_three_actual_choices_no_early_hand_cards_and_one_cost_delivery(self):
        for player in (1, 2):
            g = self.game((KILL,), player=player); self.reward(g, player); ship = self.ship(g, player)
            self.assertEqual([g.state.entities[i].card_id for i in g.state.players[player].board], [SOURCE, CARD, SHIP])
            self.assertEqual(g.state.players[player].mana, 27)
            self.assertEqual(self.hand(g, player), [KILL])
            chosen = self.complete(g)
            self.assertEqual([v.card_id for v in self.memory(g, ship).discoveries], chosen)
            self.assertEqual(self.hand(g, player), [KILL])
            self.play(g, KILL, ship, player=player)
            self.assertEqual(self.hand(g, player), chosen); self.assertEqual(self.costs(g, player), [1]*3)

    def test_each_of_three_real_discovery_waits_restores_clone_replay_and_invalid_selection_is_atomic(self):
        g = self.game(); self.reward(g)
        for _ in range(3):
            restored = self.portable(g); saved = g.snapshot()
            with self.assertRaises(IllegalAction): self.choose(g, 'not-an-option')
            self.assertEqual(g.snapshot(), saved)
            self.assertEqual(self.pick(g), self.pick(restored)); self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertIsNone(g.state.pending_choice)

    def test_short_explicit_pirate_fixture_allows_three_independent_equal_selections_and_real_one_mana_play(self):
        g = self.game((KILL,), mode='single'); self.reward(g); ship = self.ship(g)
        self.assertEqual(self.complete(g), ['BE_734']*3)
        self.assertEqual(len({v.discovery_id for v in self.memory(g, ship).discoveries}), 3)
        self.play(g, KILL, ship); before = g.state.players[1].mana; self.play(g, 'BE_734')
        self.assertEqual(g.state.players[1].mana, before-1)
        self.assertEqual(self.entity(g, 'BE_734', zone='board').base_health, g.registry.card('BE_734').health)

    def test_real_repeated_native_battlecry_appends_three_new_original_choices(self):
        g = self.game((REPEAT, KILL)); parent = self.reward(g); self.complete(g); ship = self.ship(g)
        self.play(g, REPEAT, parent); self.complete(g)
        links = self.memory(g, ship).discoveries
        self.assertEqual(len(links), 6); self.assertEqual(len({v.battlecry_id for v in links}), 2)
        self.play(g, KILL, ship); self.assertEqual(self.hand(g), [v.card_id for v in links])
        self.assertEqual(self.costs(g), [1]*6)

    def test_current_ship_copy_keeps_crew_and_base_copy_has_empty_memory(self):
        for script, count in ((COPY, 3), (BASE, 0)):
            g = self.game((script, KILL)); self.reward(g); chosen = self.complete(g); original = self.ship(g)
            self.play(g, script, original)
            copied = next(i for i in g.state.players[1].board if g.state.entities[i].card_id == SHIP and i != original)
            self.assertEqual(len(self.memory(g, copied).discoveries), count)
            self.play(g, KILL, copied); self.assertEqual(self.hand(g), chosen if count else [])

    def test_silence_and_return_to_hand_use_original_native_memory_reset(self):
        for script in (QUIET, BOUNCE):
            g = self.game((script, KILL)); self.reward(g); self.complete(g); ship = self.ship(g)
            self.play(g, script, ship)
            if script == BOUNCE: self.play(g, SHIP)
            self.play(g, KILL, ship); self.assertEqual(self.hand(g), [])

    def test_ship_control_change_delivers_original_order_to_its_deathrattle_controller(self):
        g = self.game((GIVE, KILL)); self.reward(g); chosen = self.complete(g); ship = self.ship(g)
        self.play(g, GIVE, ship); self.play(g, KILL, ship)
        self.assertEqual(self.hand(g, 2), chosen); self.assertEqual(self.costs(g, 2), [1]*3)

    def test_full_hand_receives_first_two_crew_and_burns_third_in_original_order(self):
        g = self.game((KILL, *(UNIT,)*8)); self.reward(g); chosen = self.complete(g)
        self.play(g, KILL, self.ship(g))
        self.assertEqual(self.hand(g)[-2:], chosen[:2])
        burns = [e for e in g.events if e.kind == 'card_burned']
        self.assertEqual(len(burns), 1)
        self.assertEqual(g.state.entities[burns[0].target_id].card_id, chosen[2])

    def test_ship_death_after_first_choice_returns_only_first_and_later_choices_do_not_rewrite_death(self):
        g = self.game(mode='kill-ship'); self.reward(g); first = self.pick(g)
        self.assertEqual(self.hand(g), [first]); self.pick(g); self.pick(g)
        self.assertEqual(self.hand(g), [first]); self.assertEqual(len(g.state.card_discovery_history), 3)
        self.portable(g)

    def test_silenced_original_ship_before_selection_has_no_crew_or_false_memory_notifications(self):
        g = self.game((KILL,), mode='silence-before'); self.reward(g); ship = self.ship(g)
        self.complete(g)
        self.assertFalse(any(e.kind == 'colossal_crew_remembered' for e in g.events))
        self.assertFalse(any(a.deathrattle_memory is not None for a in g.state.entities[ship].abilities))
        self.play(g, KILL, ship); self.assertEqual(self.hand(g), [])

    def test_parent_death_during_accepted_first_selection_does_not_stop_remaining_ship_memory(self):
        g = self.game((KILL,), mode='kill-root'); parent = self.reward(g); chosen = self.complete(g)
        self.assertEqual(g.state.entities[parent].zone, Zone.GRAVEYARD)
        self.play(g, KILL, self.ship(g)); self.assertEqual(self.hand(g), chosen)

    def test_nested_memory_notification_wait_and_same_id_reentry_never_borrows_remaining_choices(self):
        g = self.game((KILL,), mode='waiting'); self.reward(g); self.pick(g); ship = self.ship(g)
        restored = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g, 'move'); self.choose(restored, 'move'); self.assertEqual(g.snapshot(), restored.snapshot())
        self.pick(g); self.pick(g); self.assertEqual(self.memory(g, ship).discoveries, ())
        self.play(g, KILL, ship); self.assertEqual(self.hand(g), [])

    def test_third_choice_failure_rolls_back_only_current_action_to_two_accepted_selections(self):
        g = self.game(mode='late-failure'); self.reward(g); self.pick(g); self.pick(g); saved = g.snapshot()
        self.assertEqual(len(self.memory(g, self.ship(g)).discoveries), 2)
        with self.assertRaises(ResolutionError): self.pick(g)
        self.assertEqual(g.snapshot(), saved)

    def test_eligible_unknown_pirate_is_not_removed_and_play_payment_rng_events_roll_back(self):
        g = self.game(mode='unknown'); self.play(g, SOURCE); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, UNKNOWN): self.play(g, CARD)
        self.assertEqual(g.snapshot(), saved)

    def test_hidden_crew_never_enters_opponent_dto_and_delivery_is_private_hand_information(self):
        g = self.game((KILL,)); self.reward(g); chosen = self.complete(g)
        encoded = json.dumps(g.observe(2))
        for cid in chosen: self.assertNotIn(cid, encoded)
        for key in ('deathrattle_memory', 'discovery_id', 'colossal_id', PROFILE_ID): self.assertNotIn(key, encoded)
        self.play(g, KILL, self.ship(g))
        self.assertTrue(all(v.get('card_id') is None for v in g.observe(2)['players'][0]['hand']))
        self.assertEqual(self.hand(g), chosen)

    def test_rehashed_wrong_selected_face_unknown_profile_and_old_schema_are_rejected(self):
        g = self.game(); self.reward(g); self.pick(g); saved = g.snapshot(); ship = self.ship(g)
        bad = deepcopy(saved)
        memory = next(a['deathrattle_memory'] for a in bad['state']['entities'][str(ship)]['abilities'] if a.get('deathrattle_memory'))
        link = memory['discoveries'][0]; link['card_id'] = 'CORE_NEW1_018' if link['card_id'] != 'CORE_NEW1_018' else 'BE_734'
        bad['state_hash'] = canonical_hash({k:v for k,v in bad.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, host('normal', 'independent-reader'))
        bad = deepcopy(saved)
        def rewrite(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == 'profile_id' and item == PROFILE_ID: value[key] = 'unknown-crew-profile'
                    else: rewrite(item)
            elif isinstance(value, list):
                for item in value: rewrite(item)
        rewrite(bad); self.assertIn('unknown-crew-profile', json.dumps(bad))
        bad['state_hash'] = canonical_hash({k:v for k,v in bad.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, host('normal', 'independent-reader'))
        bad = deepcopy(saved); bad['schema_version'] = 598
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, host('normal', 'independent-reader'))

    def test_profile_overlap_and_late_child_metadata_failure_do_not_leave_half_registration(self):
        r = build_registry(); profile = r.colossal_crew_profiles[PROFILE_ID]
        with self.assertRaises(ValueError): r.register_colossal_crew_profile(replace(profile, id='duplicate-ship'))
        for cid in (CARD, SHIP): del r._cards[cid]
        del r._behaviors[profile.producer_behavior_id]; del r._behaviors[profile.deathrattle_behavior_id]
        del r._colossal_crew_profiles[PROFILE_ID]
        r._pool_cards[SHIP] = replace(r.pool_card(SHIP), cost=6)
        before = (dict(r.cards), dict(r.pool_cards), dict(r._behaviors), dict(r.colossal_crew_profiles))
        with self.assertRaises(TargetValidationError): register_nellie_ship_crew(r)
        self.assertEqual((dict(r.cards), dict(r.pool_cards), dict(r._behaviors), dict(r.colossal_crew_profiles)), before)


if __name__ == '__main__': unittest.main()
