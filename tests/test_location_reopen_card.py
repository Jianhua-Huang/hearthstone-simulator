"""Welcome Home reaches real location use/destruction and shared ability history."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry as assembled_registry
from hs_sim.cards.location_reopen_card import ROOT, DEATH, load_batch, register_location_reopen_card
from hs_sim.engine import (CardDefinition, CardType, Game, IllegalAction, PlayCard, PlayerSetup,
    Scenario, SelectChoice, TargetSpec, TriggerSpec, UseLocation, Zone)
from hs_sim.engine.effects import (ChoiceOption, GainArmor, InvokeBehavior, RandomDamage, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.locations import DestroyLocation
from hs_sim.engine.model import Resource
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry

P = 'reopen.test.'
LOC, OLD_LOC, KILL, WATCH = (P+x for x in ('location', 'old', 'kill', 'watch'))
FILL = 'CS2_182'
SUMMONS = ('BOT_411', 'AT_066', 'TID_710')
POOL = 'constructed.cards'
TARGET = P+'target'


@lru_cache(maxsize=None)
def registry(role, mode=None, pool_mode=None):
    assert role in ('writer', 'reader')
    r = build_registry(); register_location_reopen_card(r)
    meta = replace(r.card(FILL).metadata, deck_identity=None)
    r.register_behavior(P+'use', lambda c: (GainArmor(c.player_id, 1),))
    r.register_behavior(P+'old', lambda c: (GainArmor(c.player_id, 2),))
    r.register_card(CardDefinition(LOC, LOC, CardType.LOCATION, durability=2,
        on_use=P+'use', metadata=meta))
    r.register_card(CardDefinition(OLD_LOC, OLD_LOC, CardType.LOCATION, durability=2,
        on_use=P+'use', deathrattle=P+'old', metadata=meta))
    r.register_behavior(KILL, lambda c: (DestroyLocation(c.target_id, c.source_id),))
    r.register_card(CardDefinition(KILL, KILL, CardType.SPELL, on_play=KILL,
        targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.LOCATION,)), metadata=meta))
    def fail(c): raise ResolutionError('Reopen deliberate rollback')
    r.register_behavior(P+'fail', fail)
    if mode:
        event = {'open': 'location_opened', 'grant': 'ability_granted', 'death': 'location_destroyed',
                 'summoned': 'minion_summoned', 'counter': 'card_committed', 'direct-fail': 'location_opened'}[mode]
        def watch(c):
            if mode == 'counter':
                source = c.state.entities.get(c.event.source_id)
                return (CounterSpell(dict(c.event.data)['window_id']),) if source is not None and source.card_id == ROOT else ()
            if mode == 'direct-fail': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
            if mode == 'summoned':
                entity = c.state.entities.get(c.event.target_id)
                if entity is None or entity.card_id not in SUMMONS: return ()
            return (RequestChoice(c.player_id, (
                ChoiceOption('ok', 'Continue', ()),
                ChoiceOption('destroy', 'Destroy original', (DestroyLocation(
                    c.event.target_id if mode in ('open', 'grant') else c.event.source_id, c.source_id),)),
                ChoiceOption('fail', 'Fail', (RandomDamage((c.state.players[2].hero_id,), 1, c.source_id),
                    InvokeBehavior(P+'fail', c.source_id, c.player_id)))), c.source_id),)
        r.register_behavior(WATCH, watch)
        r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=8,
            triggers=(TriggerSpec(event, WATCH),), metadata=meta))
    members = []
    for cid in ((*SUMMONS,) if pool_mode != 'empty' else ()) + (FILL, ROOT):
        if cid not in r.pool_cards: r.register_pool_card(PoolCard.from_definition(r.card(cid)))
        members.append(PoolMember(cid))
    if pool_mode == 'unknown':
        card = replace(r.card(SUMMONS[0]), id=P+'unknown', name=P+'unknown',
            metadata=replace(r.card(SUMMONS[0]).metadata, deck_identity=None))
        r.register_pool_card(PoolCard.from_definition(card)); members.append(PoolMember(card.id))
    r.register_pool(PoolDefinition(POOL, P+'v1', TARGET, 'experimental', tuple(members), complete=True))
    r.validate(); r.freeze(); return r


class LocationReopenTests(unittest.TestCase):
    def game(self, *, mode=None, pool_mode=None, hand=(ROOT, KILL), board=(LOC,), enemy=(LOC,)):
        self.mode, self.pool_mode = mode, pool_mode
        if mode: board += (WATCH,)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(FILL,)*10, mana=10, max_mana=10),
            PlayerSetup('HERO_08', board=enemy, deck=(FILL,)*10, mana=10, max_mana=10)), seed=239997,
            generation_context=GenerationContext(TARGET, 'experimental')), registry('writer', mode, pool_mode))
    def play(self, g, cid=ROOT, target=None, *, eid=None):
        pid = g.state.active_player
        eid = eid or next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        return g.apply(PlayCard(pid, eid, target, len(g.state.players[pid].board)
            if g.registry.card(cid).kind == CardType.LOCATION else None))
    def loc(self, g, pid=1):
        return next(i for i in g.state.players[pid].board if g.state.entities[i].kind == CardType.LOCATION)
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; return g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def grants(self, g, eid): return tuple(a for a in active_abilities(g.state.entities[eid], 'deathrattle') if a.behavior_id == DEATH)
    def summoned(self, g, pid=1):
        return tuple(g.state.entities[i] for i in g.state.players[pid].board if g.state.entities[i].card_id in SUMMONS)
    def portable(self, g):
        r = registry('reader' if g.registry is registry('writer', self.mode, self.pool_mode) else 'writer', self.mode, self.pool_mode)
        s = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(s, r)
        for candidate in (other, g.clone(), replay(build_replay(g), r)): self.assertEqual(candidate.snapshot(), s)
        for pid in (1, 2):
            wire = json.dumps(g.for_player(pid).observe()) + json.dumps(g.for_player(pid).legal_actions()) + json.dumps(g.player_events(pid))
            for private in ('rng_state', 'resolution_frame', 'SummonCause', 'original_entities'):
                self.assertNotIn(private, wire)
        return other
    def test_a00_complete_source_two_primary_faces_and_real_root(self):
        from tools.card_batch import check_face
        data = load_batch(); raw = data['cards'][0]['record']
        self.assertEqual(len(data['official_observations']), 2)
        for observation in data['official_observations']: check_face(raw, observation['face'], observation['locale'])
        r = registry('writer'); self.assertEqual(r.card(ROOT), assembled_registry().card(ROOT))
        self.assertEqual((r.card(ROOT).cost, r.card(ROOT).spell_school), (3, None))
        self.assertNotIn(ROOT+'e', r.cards)
    def test_b00_closed_location_reopens_without_restoring_durability_or_activation(self):
        g = self.game(); i = self.loc(g); g.apply(UseLocation(1, i))
        self.assertEqual(g.state.entities[i].location_cooldown, 2)
        result = self.play(g, target=i); loc = g.state.entities[i]
        self.assertEqual((loc.durability, loc.location_cooldown, loc.uses_this_turn), (1, 0, 1))
        self.assertEqual(len(self.grants(g, i)), 1); self.assertEqual(g.state.players[1].mana, 7)
        self.assertFalse(any(e.kind == 'location_activated' for e in result.events))
        self.assertFalse(self.summoned(g)); self.portable(g)
    def test_b01_already_open_location_accepts_independent_repeated_grants(self):
        g = self.game(hand=(ROOT, ROOT, KILL)); i = self.loc(g)
        self.play(g, target=i); self.play(g, target=i)
        grants = self.grants(g, i); self.assertEqual(len(grants), 2)
        self.assertNotEqual(grants[0].id, grants[1].id); self.assertEqual(g.state.entities[i].durability, 2)
        self.assertEqual(g.state.players[1].mana, 4); self.portable(g)
    def test_b02_actual_target_contract_accepts_both_locations_and_excludes_characters(self):
        g = self.game(board=(LOC, FILL)); spell = g.state.players[1].hand[0]
        self.assertEqual(set(g.legal_targets(spell)), {self.loc(g), self.loc(g, 2)})
        saved = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, target=g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(), saved)
    def test_c00_reopened_last_use_executes_one_original_granted_deathrattle(self):
        g = self.game(); i = self.loc(g); g.apply(UseLocation(1, i)); self.play(g, target=i)
        result = g.apply(UseLocation(1, i)); self.assertEqual(g.state.entities[i].zone, Zone.GRAVEYARD)
        self.assertEqual(len(self.summoned(g)), 1); self.assertEqual(self.summoned(g)[0].zone, Zone.BOARD)
        self.assertTrue(any(e.kind == 'location_destroyed' for e in result.events))
        self.assertEqual(len(g.state.deathrattle_history), 1); self.assertTrue(g.state.deathrattle_history[0].completed)
        self.assertFalse(any(e.kind == 'battlecry_started' for e in result.events)); self.portable(g)
    def test_c01_destroying_location_is_not_a_minion_death_or_extra_paid_play(self):
        g = self.game(); i = self.loc(g); self.play(g, target=i)
        before_corpses = g.state.players[1].resources[Resource.CORPSES]
        result = self.play(g, KILL, i)
        self.assertEqual(len(self.summoned(g)), 1)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES], before_corpses)
        death = g.state.death_history[-1]
        self.assertEqual(g.registry.card(death.card_id).kind, CardType.LOCATION)
        self.assertEqual(death.corpse_value, 0)
        self.assertFalse(any(e.kind == 'minion_died' and e.target_id == i for e in result.events)); self.portable(g)
    def test_c02_opponent_target_summons_for_its_actual_controller(self):
        g = self.game(); i = self.loc(g, 2); self.play(g, target=i); self.play(g, KILL, i)
        self.assertFalse(self.summoned(g)); self.assertEqual(len(self.summoned(g, 2)), 1); self.portable(g)
    def test_c03_existing_printed_deathrattle_and_granted_one_both_execute(self):
        g = self.game(board=(OLD_LOC,)); i = self.loc(g); self.play(g, target=i); self.play(g, KILL, i)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2)
        self.assertEqual(len(self.summoned(g)), 1)
        self.assertEqual(len(g.state.deathrattle_history), 2); self.portable(g)
    def test_c04_two_actual_grants_make_two_independent_random_summons(self):
        g = self.game(hand=(ROOT, ROOT, KILL)); i = self.loc(g)
        self.play(g, target=i); self.play(g, target=i); self.play(g, KILL, i)
        self.assertEqual(len(self.summoned(g)), 2); self.assertEqual(len(g.state.deathrattle_history), 2)
        self.assertTrue(all(row.completed for row in g.state.deathrattle_history)); self.portable(g)
    def test_d00_full_board_uses_the_destroyed_location_slot(self):
        g = self.game(board=(FILL, FILL, LOC, FILL, FILL, FILL, FILL)); i = self.loc(g)
        self.play(g, target=i); self.play(g, KILL, i)
        self.assertEqual(len(g.state.players[1].board), 7); self.assertEqual(len(self.summoned(g)), 1); self.portable(g)
    def test_d01_unknown_eligible_candidate_fails_at_death_and_rolls_back_that_action(self):
        g = self.game(pool_mode='unknown'); i = self.loc(g); self.play(g, target=i); saved = g.snapshot()
        with self.assertRaises(ResolutionError) as caught: self.play(g, KILL, i)
        self.assertIn(P+'unknown', str(caught.exception)); self.assertEqual(g.snapshot(), saved)
        self.assertEqual(len(self.grants(g, i)), 1); self.portable(g)
    def test_d02_complete_empty_pool_consumes_no_rng_and_does_not_undo_location_death(self):
        g = self.game(pool_mode='empty'); i = self.loc(g); self.play(g, target=i); before = g._rng.getstate()
        self.play(g, KILL, i); self.assertEqual(g._rng.getstate(), before)
        self.assertEqual(g.state.entities[i].zone, Zone.GRAVEYARD); self.assertFalse(self.summoned(g)); self.portable(g)
    def test_e00_reopen_wait_restores_before_actual_grant(self):
        g = self.game(mode='open'); i = self.loc(g); g.apply(UseLocation(1, i)); self.play(g, target=i)
        self.assertFalse(self.grants(g, i)); self.assertEqual(g.state.entities[i].location_cooldown, 0)
        g = self.portable(g); self.choose(g); self.assertEqual(len(self.grants(g, i)), 1); self.portable(g)
    def test_e01_destroy_during_reopen_response_prevents_grant_to_dead_location(self):
        g = self.game(mode='open'); i = self.loc(g); self.play(g, target=i); self.choose(g, 'destroy')
        self.assertEqual(g.state.entities[i].zone, Zone.GRAVEYARD)
        self.assertFalse(self.grants(g, i)); self.assertFalse(self.summoned(g)); self.portable(g)
    def test_e02_grant_wait_keeps_exactly_one_ordinary_ability(self):
        g = self.game(mode='grant'); i = self.loc(g); self.play(g, target=i)
        self.assertEqual(len(self.grants(g, i)), 1); g = self.portable(g); self.choose(g)
        self.assertEqual(len(self.grants(g, i)), 1); self.portable(g)
    def test_e03_death_wait_restores_original_source_before_one_summon(self):
        g = self.game(mode='death'); i = self.loc(g); self.play(g, target=i); self.play(g, KILL, i)
        self.assertFalse(self.summoned(g)); g = self.portable(g); self.choose(g)
        self.assertEqual(len(self.summoned(g)), 1); self.portable(g)
    def test_e04_summon_wait_keeps_original_location_death_attribution(self):
        g = self.game(mode='summoned'); i = self.loc(g); self.play(g, target=i); self.play(g, KILL, i)
        self.assertEqual(len(self.summoned(g)), 1); g = self.portable(g); self.choose(g)
        self.assertEqual(len(self.summoned(g)), 1); self.portable(g)
    def test_e05_failed_reaction_restores_wait_and_rng_or_whole_paid_play(self):
        for mode in ('open', 'direct-fail'):
            with self.subTest(mode=mode):
                g = self.game(mode=mode); i = self.loc(g)
                if mode == 'open': self.play(g, target=i)
                saved = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'deliberate rollback'):
                    self.choose(g, 'fail') if mode == 'open' else self.play(g, target=i)
                self.assertEqual(g.snapshot(), saved); self.portable(g)
    def test_f00_counter_keeps_closed_location_and_prevents_grant(self):
        g = self.game(mode='counter'); i = self.loc(g); g.apply(UseLocation(1, i)); self.play(g, target=i)
        self.assertEqual(g.state.entities[i].location_cooldown, 2); self.assertFalse(self.grants(g, i))
        self.assertEqual(g.state.players[1].mana, 7); self.portable(g)
if __name__ == '__main__': unittest.main()
