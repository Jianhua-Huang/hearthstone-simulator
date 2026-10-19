"""Timeway Warden's original captive, native memory and shared dormancy lifecycle."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry as assembled_registry
from hs_sim.cards.timeway_warden_card import ROOT, load_batch, register_timeway_warden_card
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction, PlayCard,
    PlayerSetup, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (ChoiceOption, Destroy, InvokeBehavior, RandomDamage,
    RequestChoice, ReturnToHand, Silence, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CopyCard

P = 'warden.test.'
KILL, SILENCE, BOUNCE, COPY, BASE, TRIGGER, AWAKE, DORMANT, SUMMON, WATCH = (
    P+x for x in ('kill', 'silence', 'bounce', 'copy', 'base', 'trigger', 'awake', 'dormant', 'summon', 'watch'))
FILL = 'CS2_182'


@lru_cache(maxsize=None)
def registry(role, mode=None):
    assert role in ('writer', 'reader')
    r = build_registry(); register_timeway_warden_card(r)
    meta = replace(r.card(FILL).metadata, deck_identity=None)
    bodies = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        SILENCE: lambda c: (Silence(c.target_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        COPY: lambda c: (CopyCard(MinionReference.capture(c.state.entities[c.target_id]),
            c.player_id, mode='current', source_id=c.source_id),),
        BASE: lambda c: (CopyCard(MinionReference.capture(c.state.entities[c.target_id]),
            c.player_id, mode='base', source_id=c.source_id),),
        TRIGGER: lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        AWAKE: lambda c: (AwakenMinion(c.state.players[2].board[0], c.source_id),),
        DORMANT: lambda c: (MakeDormant(c.state.players[2].board[0], 3, c.source_id),),
        SUMMON: lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(ROOT),), SummonCause.capture(c)),),
    }
    for name, body in bodies.items():
        r.register_behavior(name, body)
        extra = {} if name in (AWAKE, DORMANT, SUMMON) else {
            'targeting': TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))}
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=meta, **extra))
    def fail(c): raise ResolutionError('Warden deliberate rollback')
    r.register_behavior(P+'fail', fail)
    if mode:
        event = {'dormant': 'minion_dormant', 'kill-on-dormant': 'minion_dormant',
                 'awakened': 'minion_awakened', 'death': 'minion_died',
                 'early-death': 'battlecry_started', 'target-leaves': 'battlecry_started'}[mode]
        def watch(c):
            e = c.event; source = c.state.entities.get(e.source_id)
            if source is None or source.card_id != ROOT: return ()
            if mode in ('kill-on-dormant', 'early-death'): return (Destroy(e.source_id, c.source_id),)
            if mode == 'target-leaves': return (ReturnToHand(e.target_id),)
            return (RequestChoice(c.player_id, (
                ChoiceOption('ok', 'Continue', ()),
                ChoiceOption('fail', 'Fail', (RandomDamage((c.state.players[2].hero_id,), 1, c.source_id),
                    InvokeBehavior(P+'fail', c.source_id, c.player_id)))), c.source_id),)
        r.register_behavior(WATCH, watch)
        r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=9,
            triggers=(TriggerSpec(event, WATCH),), metadata=meta))
    r.validate(); r.freeze(); return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class TimewayWardenTests(unittest.TestCase):
    def game(self, *, mode=None, hand=(ROOT, KILL), enemy=(FILL, FILL), enemy_hand=()):
        self.mode = mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=((WATCH,) if mode else ()),
                deck=(FILL,)*12, mana=10, max_mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy,
                deck=(FILL,)*12, mana=10, max_mana=10)), seed=240442), registry('writer', mode))
    def play(self, g, cid=ROOT, target=None, *, eid=None):
        pid = g.state.active_player
        eid = eid or next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        return g.apply(PlayCard(pid, eid, target, len(g.state.players[pid].board)
            if g.registry.card(cid).kind == CardType.MINION else None))
    def source(self, g, pid=1):
        return next(i for i in g.state.players[pid].board if g.state.entities[i].card_id == ROOT)
    def memory(self, g, eid):
        return next(a.deathrattle_memory for a in g.state.entities[eid].abilities
            if a.kind == 'deathrattle' and not a.consumed and a.deathrattle_memory is not None
            and a.deathrattle_memory.spec.kind == 'dormancy_link')
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; return g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g):
        r = registry('reader' if g.registry is registry('writer', self.mode) else 'writer', self.mode)
        s = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(s, r)
        for candidate in (other, g.clone(), replay(build_replay(g), r)): self.assertEqual(candidate.snapshot(), s)
        for pid in (1, 2):
            wire = json.dumps(g.for_player(pid).observe()) + json.dumps(g.for_player(pid).legal_actions()) + json.dumps(g.player_events(pid))
            for private in ('RememberedDormancy', 'dormancy_link', 'deathrattle_memory', 'rng_state', 'resolution_frame'):
                self.assertNotIn(private, wire)
        return other
    def test_a00_complete_two_primary_faces_and_original_enchantment_count(self):
        from tools.card_batch import check_face
        data = load_batch(); raw = data['cards'][0]['record']
        self.assertEqual(len(data['official_observations']), 2)
        for item in data['official_observations']: check_face(raw, item['face'], item['locale'])
        card = registry('writer').card(ROOT); self.assertEqual(card, assembled_registry().card(ROOT))
        self.assertEqual((card.cost, card.attack, card.health), (4, 2, 6))
        self.assertEqual(data['evidence_only'][0]['record']['tags']['SCORE_VALUE_1'], 10000)
        self.assertNotIn(ROOT+'e', registry('writer').cards)
    def test_b00_actual_enemy_target_and_one_original_captive_among_identical_faces(self):
        g = self.game(); target, other = g.state.players[2].board; before = g._rng.getstate()
        self.play(g, target=target); source = self.source(g); link = self.memory(g, source).dormancies[0]
        self.assertEqual((link.entity_id, link.dormancy_id), (target, g.state.entities[target].dormancy.id))
        self.assertEqual(link.battlecry_id, g.state.battlecry_history[-1].id)
        self.assertEqual(g.state.entities[target].dormancy.remaining_turns, 10000)
        self.assertIsNone(g.state.entities[other].dormancy); self.assertEqual(g._rng.getstate(), before)
        self.assertEqual(g.state.players[1].mana, 6); self.portable(g)
    def test_b01_empty_enemy_board_plays_without_a_captive(self):
        g = self.game(enemy=()); self.play(g)
        self.assertFalse(self.memory(g, self.source(g)).dormancies); self.portable(g)
    def test_b02_target_contract_rejects_friendly_hero_and_already_dormant(self):
        g = self.game(hand=(ROOT, ROOT)); target, other = g.state.players[2].board
        self.play(g, target=target); spell = g.state.players[1].hand[0]
        self.assertEqual(set(g.legal_targets(spell)), {other})
        saved = g.snapshot()
        for bad in (self.source(g), g.state.players[2].hero_id, target):
            with self.subTest(bad=bad), self.assertRaises(IllegalAction): self.play(g, target=bad)
            self.assertEqual(g.snapshot(), saved)
    def test_c00_source_natural_death_awakens_exact_original_target_without_new_summon(self):
        g = self.game(); target, other = g.state.players[2].board
        self.play(g, target=target); source = self.source(g); result = self.play(g, KILL, source)
        self.assertIsNone(g.state.entities[target].dormancy); self.assertEqual(g.state.entities[target].health, 5)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.players[2].board, [target, other])
        self.assertEqual(sum(e.kind == 'minion_awakened' for e in result.events), 1)
        self.assertFalse(any(e.kind == 'minion_summoned' for e in result.events)); self.portable(g)
    def test_c01_owner_countdown_is_real_ten_thousand_not_permanent_or_global_turns(self):
        g = self.game(); target = g.state.players[2].board[0]; self.play(g, target=target)
        g.apply(EndTurn(1)); self.assertEqual(g.state.entities[target].dormancy.remaining_turns, 9999)
        g.apply(EndTurn(2)); self.assertEqual(g.state.entities[target].dormancy.remaining_turns, 9999)
        self.portable(g)
    def test_c02_captive_is_committed_before_dormancy_reaction_kills_warden(self):
        g = self.game(mode='kill-on-dormant'); target = g.state.players[2].board[0]
        result = self.play(g, target=target)
        self.assertIsNone(g.state.entities[target].dormancy)
        self.assertEqual(sum(e.kind == 'minion_awakened' for e in result.events), 1)
        self.assertEqual(g.state.deathrattle_history[-1].capture.ability.deathrattle_memory.dormancies[0].entity_id, target)
        self.portable(g)
    def test_c03_source_dead_before_payload_cannot_retroactively_change_old_death(self):
        g = self.game(mode='early-death'); target = g.state.players[2].board[0]; self.play(g, target=target)
        self.assertEqual(g.state.entities[target].dormancy.remaining_turns, 10000)
        self.assertFalse(g.state.deathrattle_history[-1].capture.ability.deathrattle_memory.dormancies)
        self.portable(g)
    def test_c04_target_departure_before_payload_does_not_imprison_hand_or_rebind_name(self):
        g = self.game(mode='target-leaves'); target, other = g.state.players[2].board; self.play(g, target=target)
        self.assertEqual(g.state.entities[target].zone, Zone.HAND); self.assertIsNone(g.state.entities[other].dormancy)
        self.assertFalse(self.memory(g, self.source(g)).dormancies); self.portable(g)
    def test_d00_silence_removes_source_deathrattle_and_does_not_release_captive(self):
        g = self.game(hand=(ROOT, SILENCE, KILL)); target = g.state.players[2].board[0]
        self.play(g, target=target); source = self.source(g); self.play(g, SILENCE, source); self.play(g, KILL, source)
        self.assertIsNotNone(g.state.entities[target].dormancy); self.assertFalse(g.state.deathrattle_history); self.portable(g)
    def test_d01_reentered_source_only_releases_its_new_captive(self):
        g = self.game(hand=(ROOT, BOUNCE, KILL)); first, second = g.state.players[2].board
        self.play(g, target=first); source = self.source(g); self.play(g, BOUNCE, source)
        self.play(g, target=second, eid=source); self.assertEqual(len(self.memory(g, source).dormancies), 1)
        self.play(g, KILL, source); self.assertIsNotNone(g.state.entities[first].dormancy)
        self.assertIsNone(g.state.entities[second].dormancy); self.portable(g)
    def test_d02_current_copy_keeps_original_link_and_base_copy_starts_empty(self):
        g = self.game(hand=(ROOT, COPY, BASE, KILL)); target = g.state.players[2].board[0]
        self.play(g, target=target); source = self.source(g); original = self.memory(g, source)
        self.play(g, COPY, source); self.play(g, BASE, source)
        copies = [i for i in g.state.players[1].hand if g.state.entities[i].card_id == ROOT]
        self.assertEqual(self.memory(g, copies[0]), original); self.assertFalse(self.memory(g, copies[1]).dormancies)
        self.portable(g)
    def test_d03_two_physical_sources_keep_separate_captives(self):
        g = self.game(hand=(ROOT, ROOT, KILL)); first, second = g.state.players[2].board
        self.play(g, target=first); source = self.source(g); self.play(g, target=second); self.play(g, KILL, source)
        self.assertIsNone(g.state.entities[first].dormancy); self.assertIsNotNone(g.state.entities[second].dormancy)
        self.portable(g)
    def test_e00_dormancy_wait_restores_complete_link_once_before_battlecry_finishes(self):
        g = self.game(mode='dormant'); target = g.state.players[2].board[0]; self.play(g, target=target)
        source = self.source(g); self.assertEqual(len(self.memory(g, source).dormancies), 1)
        g = self.portable(g); self.choose(g); self.assertEqual(len(self.memory(g, source).dormancies), 1)
        self.portable(g)
    def test_e01_death_wait_restores_original_memory_before_release(self):
        g = self.game(mode='death'); target = g.state.players[2].board[0]
        self.play(g, target=target); self.play(g, KILL, self.source(g)); self.assertIsNotNone(g.state.entities[target].dormancy)
        g = self.portable(g); self.choose(g); self.assertIsNone(g.state.entities[target].dormancy); self.portable(g)
    def test_e02_awakening_wait_resumes_once_from_actual_frozen_deathrattle(self):
        g = self.game(mode='awakened'); target = g.state.players[2].board[0]
        self.play(g, target=target); self.play(g, KILL, self.source(g)); self.assertIsNone(g.state.entities[target].dormancy)
        g = self.portable(g); self.choose(g); self.assertEqual(len(g.state.deathrattle_history), 1); self.portable(g)
    def test_e03_failed_nested_choice_rolls_back_original_link_wait_rng_and_information(self):
        for mode in ('dormant', 'death', 'awakened'):
            with self.subTest(mode=mode):
                g = self.game(mode=mode); target = g.state.players[2].board[0]; self.play(g, target=target)
                if mode != 'dormant': self.play(g, KILL, self.source(g))
                saved = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'deliberate rollback'): self.choose(g, 'fail')
                self.assertEqual(g.snapshot(), saved); self.portable(g)
    def test_f00_active_deathrattle_release_does_not_require_source_death(self):
        g = self.game(hand=(ROOT, TRIGGER, KILL)); target = g.state.players[2].board[0]
        self.play(g, target=target); source = self.source(g); self.play(g, TRIGGER, source)
        self.assertIsNone(g.state.entities[target].dormancy); self.assertEqual(g.state.entities[source].zone, Zone.BOARD)
        result = self.play(g, KILL, source); self.assertFalse(any(e.kind == 'minion_awakened' for e in result.events))
        self.portable(g)
    def test_f01_later_distinct_dormancy_of_same_minion_is_not_the_old_captive_interval(self):
        g = self.game(hand=(ROOT, AWAKE, DORMANT, KILL)); target = g.state.players[2].board[0]
        self.play(g, target=target); source = self.source(g); old = g.state.entities[target].dormancy.id
        self.play(g, AWAKE); self.play(g, DORMANT); self.assertNotEqual(g.state.entities[target].dormancy.id, old)
        self.play(g, KILL, source); self.assertEqual(g.state.entities[target].dormancy.remaining_turns, 3); self.portable(g)
    def test_f02_ordinary_summoned_warden_has_no_fake_battlecry_or_captive(self):
        g = self.game(hand=(SUMMON, KILL)); self.play(g, SUMMON); source = self.source(g)
        self.assertFalse(self.memory(g, source).dormancies); self.play(g, KILL, source)
        self.assertFalse(g.state.battlecry_history)
        self.assertTrue(all(g.state.entities[i].dormancy is None for i in g.state.players[2].board)); self.portable(g)
    def test_f03_second_player_uses_its_actual_accepted_source_and_enemy_target(self):
        g = self.game(hand=(SUMMON,), enemy_hand=(ROOT, KILL)); self.play(g, SUMMON)
        target = self.source(g); g.apply(EndTurn(1)); self.play(g, target=target); source = self.source(g, 2)
        self.assertEqual(self.memory(g, source).dormancies[0].player_id, 1)
        self.play(g, KILL, source); self.assertIsNone(g.state.entities[target].dormancy); self.portable(g)
    def test_g00_complete_rehashed_memory_rejects_other_target_future_clock_and_missing_links(self):
        g = self.game(); target, other = g.state.players[2].board; self.play(g, target=target); source = self.source(g)
        original = g.snapshot()
        def memory(saved):
            row = saved['state']['entities'][str(source)]
            return next(a['deathrattle_memory'] for a in row['abilities'] if a['deathrattle_memory'] is not None)
        for field, value in (('entity_id', other), ('battlecry_id', 100000), ('dormancy_id', g.state.next_attachment_id)):
            with self.subTest(field=field):
                bad = deepcopy(original); memory(bad)['dormancies'][0][field] = value
                with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), g.registry)
        bad = deepcopy(original); del memory(bad)['dormancies']
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), g.registry)
        bad = deepcopy(original); bad['schema_version'] = SNAPSHOT_SCHEMA_VERSION - 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, g.registry)


if __name__ == '__main__': unittest.main()
