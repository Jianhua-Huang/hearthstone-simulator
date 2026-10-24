"""Two real spell texts use ordinary minion effects, not delayed spell casts.

The host domains are diagnostic domains. Sources supplied across classes in
test hands do not certify a legal starting deck or an actual generation route.
"""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import assemble_periodic_spell_fragments as cards
from hs_sim.cards.native_assemble_entry_cards import NURTURER, FLESH, SHAPER, POOL_ID
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayerSetup,
    Scenario, SelectChoice, TriggerSpec)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Destroy, GainArmor,
    InvokeBehavior, RequestChoice, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardClass, CardMetadata, DamageKind, Keyword,
    SpellSchool, SummonQuantitySpec, TargetSpec)
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

CINDER, FLOCK = cards.SOURCES
BASE, LOOT, DRAIN, END, COIN = 'CORE_UNG_809', 'CORE_EX1_096', 'CORE_GIL_622', 'TIME_428', 'GAME_005'
FLAME = 'UNG_809t1'
P = 'fixture.assemble_periodic_spell.'
KILL, MUTE, GIVE, WATCH, FAIL, POWER, MULT, FILL = (
    P+s for s in ('kill', 'mute', 'give', 'watch', 'fail', 'power', 'mult', 'fill'))
CTX = GenerationContext('k520-two-periodic-spell-domains', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


def face(donor, base=BASE, half='bottom'):
    return AssembleRecipe(base, donor, half).card_id


@lru_cache(maxsize=None)
def fixture(donor, mode='normal', role='writer'):
    r = build_registry()
    r._version += '.k520.'+donor+'.'+mode
    for cid, body in (
            (KILL, lambda c: (Destroy(c.target_id, c.source_id),)),
            (MUTE, lambda c: (Silence(c.target_id),)),
            (GIVE, lambda c: (ChangeControl(c.target_id, 3-c.player_id),))):
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, metadata=META,
            on_play=cid, targeting=TargetSpec(kinds=(CardType.MINION,))))

    def fail(c):
        raise ResolutionError('deliberate periodic projection downstream failure')

    def watch(c):
        if mode not in ('wait', 'fail') or c.event is None:
            return ()
        if c.event.kind == 'minion_summoned':
            # The native notification identifies the entering minion itself.
            target = c.state.entities.get(c.event.target_id)
            if target is None or target.card_id != cards.HATCHLING:
                return ()
            if sum(c.state.entities[i].card_id == cards.HATCHLING
                    for i in c.state.players[target.controller].board) != 1:
                return ()
        else:
            source = c.state.entities.get(c.event.source_id)
            if source is None or not source.card_id.startswith('assemble:'):
                return ()
            # One suspension still covers the remaining five packet deliveries.
            if len(c.state.damage_history) != 1:
                return ()
        if mode == 'fail':
            return (GainArmor(c.player_id, 1), InvokeBehavior(FAIL, c.source_id, c.player_id))
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1),
                InvokeBehavior(FAIL, c.source_id, c.player_id)))), c.source_id),)

    r.register_behavior(FAIL, fail)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('damage_dealt', WATCH), TriggerSpec('minion_summoned', WATCH))))
    r.register_card(CardDefinition(POWER, POWER, CardType.MINION, health=20,
        spell_damage=4, metadata=META))
    r.register_card(CardDefinition(MULT, MULT, CardType.MINION, health=20, metadata=META,
        summon_quantities=(SummonQuantitySpec(factor=2, source_kinds=(CardType.SPELL,)),)))
    r.register_card(CardDefinition(FILL, FILL, CardType.MINION, health=20, metadata=META))
    members = (LOOT, DRAIN, donor) if mode == 'death' else (END, LOOT, donor) if mode == 'end' else (BASE, LOOT, donor)
    r.register_pool(PoolDefinition(POOL_ID, 'three-real-reviewed-physical-sources-v1',
        CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode == 'unknown':
        r._assemble_projections.pop(donor)
    return r


class AssemblePeriodicSpellTests(CardBatchTestMixin, unittest.TestCase):
    def registry_factory(self, mode, role):
        return fixture(self.donor, mode, role)

    def game(self, donor=CINDER, mode='normal', extra=(), board=(), actor=1):
        self.donor, self.mode = donor, mode
        hero = 'HERO_10' if donor == CINDER else 'HERO_06'
        root = FLESH if mode == 'death' else SHAPER if mode == 'end' else NURTURER
        return Game.from_scenario(Scenario(tuple(PlayerSetup(hero,
            hand=(root, *extra) if p == actor else (), board=board if p == actor else (),
            deck=(COIN,)*20, mana=30, max_mana=30, mana_cap=30) for p in (1, 2)),
            active_player=actor, seed=520, generation_context=CTX), fixture(donor, mode))

    def play(self, g, cid, target=None):
        return super().play(g, cid, target, player=g.state.active_player)

    def manufacture(self, g, base=BASE, half='bottom'):
        root = FLESH if self.mode == 'death' else SHAPER if self.mode == 'end' else NURTURER
        self.play(g, root)
        q = g.state.pending_choice
        cid = face(self.donor, base, half)
        option = next(o for o in q.options if o.card_id == cid)
        g.apply(SelectChoice(q.player_id, q.id, (option.id,)))
        return cid

    def hatchlings(self, g, player=1):
        return [g.state.entities[i] for i in g.state.players[player].board
            if g.state.entities[i].card_id == cards.HATCHLING]

    def full_cycle(self, g):
        g.apply(EndTurn(g.state.active_player))
        g.apply(EndTurn(g.state.active_player))

    def finish_all_choices(self, g):
        count = 0
        while g.state.pending_choice is not None:
            self.choose(g)
            count += 1
            self.assertLessEqual(count, 6)

    def test_complete_spell_and_token_faces_keep_original_programs_and_roles(self):
        d = cards.load_batch()
        r = fixture(CINDER)
        rows = {x['record']['id']: x for x in d['existing_dependencies']}
        for cid, row in rows.items():
            self.assertEqual(batch.canonical(asdict(r.card(cid))), row['definition_sha256'])
        self.assertEqual(len(d['official_observations']), 4)
        for obs in d['official_observations']:
            path = Path(obs['response_file'])
            self.assertEqual(batch.sha(path), obs['response_sha256'])
            body = json.loads(path.read_text(encoding='utf-8-sig'))
            raw = rows[obs['card_id']]['record']
            self.assertEqual([x for x in body['cards'] if x['id'] == raw['dbf_id']], [obs['face']])
            batch.check_face(raw, obs['face'], obs['locale'])
        for cid in cards.SOURCES:
            p = r.assemble_projections[cid]
            self.assertEqual(p.source_kind, CardType.SPELL)
            self.assertEqual(p.prefix.timing, 'start_turn')
            self.assertEqual(r.card(cid).kind, CardType.SPELL)
            self.assertEqual(batch.canonical(asdict(r.player_effect(r.card(cid).ongoing_effect_id))),
                batch.canonical(d['original_player_effects'][cid]))
        self.assertEqual(d['original_player_effects'][CINDER]['kind'], 'sigil')
        self.assertEqual(d['original_player_effects'][FLOCK]['kind'], 'objective')

    def test_paid_cinder_battlecry_both_seats_has_six_minion_packets_without_spell_bonus(self):
        for actor in (1, 2):
            with self.subTest(actor=actor):
                g = self.game(board=(POWER,), actor=actor)
                cid = self.manufacture(g)
                eid = self.play(g, cid)
                self.assertEqual(g.state.players[actor].mana, 26)
                self.assertEqual(g.state.entities[g.state.players[3-actor].hero_id].health, 24)
                root = g.state.split_damage_history[-1]
                self.assertEqual((root.quote.budget, root.quote.spell_bonus, root.quote.school), (6, 0, None))
                rows = [x.health_result for x in g.state.damage_history]
                self.assertEqual(len(rows), 6)
                self.assertTrue(all(x.damage_kind == DamageKind.MINION_ABILITY.value and x.source_card_id == cid for x in rows))
                self.assertFalse(g.state.cast_history)
                self.assertFalse(g.state.players[actor].player_effects)
                self.assertEqual(g.state.entities[eid].card_id, cid)

    def test_paid_flock_battlecry_both_seats_summons_three_exact_tokens(self):
        for actor in (1, 2):
            with self.subTest(actor=actor):
                g = self.game(FLOCK, board=(MULT,), actor=actor)
                cid = self.manufacture(g)
                self.play(g, cid)
                tokens = self.hatchlings(g, actor)
                self.assertEqual(len(tokens), 3)
                self.assertEqual({(e.attack, e.max_health) for e in tokens}, {(2, 1)})
                self.assertTrue(all(not e.keywords for e in tokens))
                self.assertFalse(g.state.players[actor].player_effects)
                self.assertEqual(g.state.players[actor].mana, 26)

    def test_each_spell_prefix_is_a_recurrent_minion_start_not_a_one_shot_install(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                g = self.game(donor)
                cid = self.manufacture(g, half='top')
                self.play(g, cid)
                self.assertIsNone(g.registry.card(cid).ongoing_effect_id)
                self.assertFalse(g.state.players[1].player_effects)
                self.assertFalse(any(g.state.entities[i].card_id == FLAME for i in g.state.players[1].hand))
                self.full_cycle(g)
                self.assertEqual(sum(g.state.entities[i].card_id == FLAME for i in g.state.players[1].hand), 1)
                self.full_cycle(g)
                self.assertEqual(sum(g.state.entities[i].card_id == FLAME for i in g.state.players[1].hand), 2)
                self.assertFalse(g.state.players[1].player_effects)

    def test_cinder_natural_death_keeps_original_minion_damage_source_and_no_extra_cast(self):
        g = self.game(mode='death', extra=(KILL,), board=(POWER,))
        cid = self.manufacture(g, LOOT)
        eid = self.play(g, cid)
        self.assertFalse(g.state.damage_history)
        before = len(g.state.cast_history)
        self.play(g, KILL, eid)
        self.assertEqual(len(g.state.cast_history), before+1)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 24)
        self.assertTrue(all(x.health_result.damage_kind == DamageKind.MINION_ABILITY.value
            and x.health_result.source_card_id == cid for x in g.state.damage_history))
        self.assertEqual(len(g.state.death_history), 1)

    def test_flock_natural_death_uses_original_slot_for_all_three_entries(self):
        g = self.game(FLOCK, 'death', extra=(KILL,), board=(FILL, FILL))
        cid = self.manufacture(g, LOOT)
        # Place a real physical source between the two surviving neighbours.
        eid = self.entity(g, cid).id
        from hs_sim.engine import PlayCard
        g.apply(PlayCard(1, eid, position=1))
        left, right = g.state.players[1].board[0], g.state.players[1].board[-1]
        self.play(g, KILL, eid)
        board = g.state.players[1].board
        self.assertEqual((board[0], board[-1]), (left, right))
        self.assertEqual(len(self.hatchlings(g)), 3)
        self.assertTrue(all(g.state.entities[i].card_id == cards.HATCHLING for i in board[1:4]))

    def test_real_end_producer_repeats_body_and_uses_current_remaining_capacity(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                g = self.game(donor, 'end')
                cid = self.manufacture(g, END)
                self.play(g, cid)
                g.apply(EndTurn(1))
                if donor == CINDER:
                    self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 24)
                else:
                    self.assertEqual(len(self.hatchlings(g)), 3)
                g.apply(EndTurn(2)); g.apply(EndTurn(1))
                if donor == CINDER:
                    self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 18)
                else:
                    self.assertEqual(len(self.hatchlings(g)), 5)
                self.assertFalse(g.state.players[1].player_effects)

    def test_waiting_each_body_restores_clones_and_replays_then_really_finishes(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                g = self.game(donor, 'wait', board=(WATCH,))
                cid = self.manufacture(g)
                self.play(g, cid)
                self.assertIsNotNone(g.state.pending_choice)
                saved = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'deliberate periodic'):
                    self.choose(g, 'bad')
                self.assertEqual(g.snapshot(), saved)
                reader = self.registry_factory(self.mode, 'independent-reader')
                self.assertIsNot(reader, g.registry)
                legs = (g, Game.from_snapshot(json.loads(json.dumps(saved)), reader),
                    g.clone(), replay(build_replay(g), reader))
                for other in legs:
                    self.assertEqual(other.snapshot(), saved)
                    self.finish_all_choices(other)
                self.assertTrue(all(other.snapshot() == g.snapshot() for other in legs))
                if donor == CINDER:
                    self.assertEqual(len(g.state.damage_history), 6)
                    self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 24)
                else:
                    self.assertEqual(len(self.hatchlings(g)), 3)
                for player in (1, 2):
                    view = json.dumps(g.for_player(player).observe())
                    for key in ('rng_state', 'resolution_frame', 'submitted_cost', 'hand_entry_id'):
                        self.assertNotIn('"'+key+'"', view)

    def test_late_body_failure_rolls_back_the_paid_minion_and_randomness(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                g = self.game(donor, 'fail', board=(WATCH,))
                cid = self.manufacture(g)
                saved = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'deliberate periodic'):
                    self.play(g, cid)
                self.assertEqual(g.snapshot(), saved)

    def test_silence_and_control_use_physical_minion_lifecycle_not_original_spell_clock(self):
        for helper in (MUTE, GIVE):
            with self.subTest(helper=helper):
                g = self.game(extra=(helper,))
                cid = self.manufacture(g, half='top')
                eid = self.play(g, cid)
                self.play(g, helper, eid)
                g.apply(EndTurn(1))
                self.assertEqual(sum(g.state.entities[i].card_id == FLAME for i in g.state.players[2].hand),
                    1 if helper == GIVE else 0)
                self.assertFalse(g.state.players[1].player_effects)
                self.assertFalse(g.state.players[2].player_effects)

    def test_unknown_eligible_projection_keeps_member_and_rolls_back_entire_offer(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                g = self.game(donor, 'unknown')
                saved = g.snapshot()
                with self.assertRaises((ResolutionError, ValueError)):
                    self.play(g, NURTURER)
                self.assertEqual(g.snapshot(), saved)
                self.assertIn(donor, [x.card_id for x in g.registry.pool(POOL_ID, CTX).members])

    def test_original_spells_keep_one_shot_clocks_spell_kind_and_spell_summon_quantity(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                self.donor, self.mode = donor, 'normal'
                hero = 'HERO_10' if donor == CINDER else 'HERO_06'
                board = (POWER,) if donor == CINDER else (MULT,)
                g = Game.from_scenario(Scenario((PlayerSetup(hero, hand=(donor,), board=board,
                    deck=(COIN,)*10, mana=10, max_mana=10),
                    PlayerSetup('HERO_08', deck=(COIN,)*10)), seed=520), fixture(donor))
                self.play(g, donor)
                self.assertEqual(len(g.state.players[1].player_effects), 1)
                self.full_cycle(g)
                self.assertFalse(g.state.players[1].player_effects)
                if donor == CINDER:
                    self.assertEqual(g.state.split_damage_history[0].quote.school, SpellSchool.FEL)
                    self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 24)
                else:
                    self.assertEqual(len(self.hatchlings(g)), 6)
                self.assertEqual(len(g.state.cast_history), 1)
                saved_count = len(g.state.split_damage_history) if donor == CINDER else len(self.hatchlings(g))
                self.full_cycle(g)
                self.assertEqual(len(g.state.split_damage_history) if donor == CINDER else len(self.hatchlings(g)), saved_count)

    def test_complete_native_program_conflict_rejects_before_installing_any_new_body(self):
        r = fixture(CINDER)
        before = r.fingerprint()
        bad = deepcopy(cards.load_batch())
        bad['original_player_effects'][FLOCK]['duration'] = 2
        with patch.object(cards, 'load_batch', lambda: bad):
            with self.assertRaisesRegex(TargetValidationError, 'owner clock'):
                cards.register_assemble_periodic_spell_fragments(r)
        self.assertEqual(r.fingerprint(), before)


if __name__ == '__main__':
    unittest.main()
