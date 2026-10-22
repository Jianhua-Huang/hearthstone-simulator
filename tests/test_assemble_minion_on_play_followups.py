"""Actual minion play timing, printed tribes, native Kindred plans and recovery."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import assemble_minion_on_play_followups as cards
from hs_sim.cards.native_assemble_entry_cards import FETCHER, POOL_ID as ASSEMBLE_POOL
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe, AssemblePrefix, AssembleSuffix, compatible
from hs_sim.engine.assemble_on_play import AssembleOnPlaySource
from hs_sim.engine.effects import (ChoiceOption, Destroy, GainArmor, InvokeBehavior, RequestChoice,
    ReturnToHand, Summon)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_physical import PROFILE
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_damage_health_followups import fixture as base_fixture
from test_assemble_card_play_followups import META, COIN, LOOT, KILL

RUNNER, PREPPER, DINO, FIREGILL, THIEF, QUEEN = cards.SOURCES
CHALLENGER = 'TLC_251'
BATTLECRY, OWNER_END = 'CORE_UNG_809', 'TIME_428'
P = 'k431.'
BEAST, DEMON, MURLOC, ALL, NONE, NOOP, WATCH, FAIL, REPLAY, SUMMON = (
    P + x for x in ('beast', 'demon', 'murloc', 'all', 'none', 'noop', 'watch', 'fail', 'replay', 'summon'))
CTX = GenerationContext('k431-explicit-native-assembly-domain', 'experimental')
DECK = (COIN,) * 24


def recipe(primary, secondary=None, half='bottom'):
    return AssembleRecipe(primary, secondary or primary, half).card_id


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = base_fixture.__wrapped__('normal', role)
    r._version += '.k431.' + mode
    for cid, tribes in ((BEAST, ('beast',)), (DEMON, ('demon',)), (MURLOC, ('murloc',)),
            (ALL, ('all',)), (NONE, ())):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=20,
            metadata=replace(META, tribes=tribes)))
    r.register_behavior(NOOP, lambda c: ())
    r.register_card(CardDefinition(NOOP, NOOP, CardType.SPELL, on_play=NOOP, metadata=META))
    def fail(c):
        raise ResolutionError('K431 deliberate native minion continuation failure')
    r.register_behavior(FAIL, fail)
    def watch(c):
        if mode == 'wait_token':
            target = c.state.entities.get(c.event.target_id)
            if target is None or target.card_id != cards.TOKEN:
                return ()
        source = next((i for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id == recipe(THIEF)), None)
        extras = (ChoiceOption('depart', 'Return actual source', (ReturnToHand(source),)),) if source else ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue'),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1), InvokeBehavior(FAIL, c.source_id, c.player_id))),
            *extras), c.source_id),)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('card_drawn' if mode == 'wait_draw' else 'minion_summoned', WATCH),)))
    r.register_behavior(REPLAY, lambda c: (ReplayWholeCards(c.player_id, c.source_id,
        WholeCardHistoryQuery(c.player_id, len(c.state.play_history) + 1, kinds=(CardType.MINION,),
            exclude_card_ids=(BEAST, DEMON, MURLOC, ALL, NONE, CHALLENGER)), physical_profile=PROFILE),))
    r.register_card(CardDefinition(REPLAY, REPLAY, CardType.SPELL, on_play=REPLAY, metadata=META))
    r.register_behavior(SUMMON, lambda c: (Summon(c.player_id, recipe(THIEF)),))
    r.register_card(CardDefinition(SUMMON, SUMMON, CardType.SPELL, on_play=SUMMON, metadata=META))
    if mode == 'assemble':
        r.register_pool(PoolDefinition(ASSEMBLE_POOL, 'k431-neutral-four-and-current-class-five',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in (THIEF, QUEEN, PREPPER)), complete=True))
    r.validate()
    return r


class AssembleMinionOnPlayTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), mode='normal'):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_10', hand=hand, board=board, deck=DECK, mana=50, max_mana=50, mana_cap=50),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=DECK, mana=50, max_mana=50, mana_cap=50)),
            seed=431, generation_context=CTX), fixture(mode))

    def eid(self, g, cid, p=1, zone='board'):
        return next(i for i in getattr(g.state.players[p], zone) if g.state.entities[i].card_id == cid)

    def count(self, g, cid, p=1, zone='board'):
        return sum(g.state.entities[i].card_id == cid for i in getattr(g.state.players[p], zone))

    def play(self, g, cid, target=None):
        p = g.state.active_player
        source = self.eid(g, cid, p, 'hand')
        g.apply(PlayCard(p, source, target))
        return source

    def cycle(self, g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def pick(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def prime(self, cid, primer, **kwargs):
        g = self.game((primer, cid), **kwargs)
        self.play(g, primer); self.cycle(g)
        return g

    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot()))
        reader = fixture(mode, 'reader')
        self.assertIsNot(reader, g.registry)
        other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe()) + json.dumps(g.player_events(p))
            for key in ('rng_state', 'resolution_frame', 'condition_id', 'assemble_on_play_sources'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_a_seven_full_rows_fourteen_primary_faces_and_exact_native_self_reconstruction(self):
        d = cards.load_batch(); r = fixture()
        rows = {row['record']['id']: row for row in d['existing_dependencies']}
        self.assertEqual(len(rows), 7); self.assertEqual(len(d['official_observations']), 14)
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']), o['response_sha256'])
            check_face(rows[o['card_id']]['record'], o['face'], o['locale'])
        for cid in cards.SOURCES:
            old = r.card(cid); new = r.card(recipe(cid))
            self.assertEqual(canonical_digest(asdict(old)), rows[cid]['definition_sha256'])
            self.assertEqual((new.cost, new.attack, new.health, new.keywords, new.metadata),
                (old.cost, old.attack, old.health, old.keywords, old.metadata))
            self.assertIsNotNone(new.on_play)
            self.assertIsNone(new.battlecry)
            self.assertEqual(r.assemble_on_play_sources[cid].original_behavior_id, old.on_play)
        self.assertEqual(dict(r.kindred_profiles), r._kindred_profiles)
        with self.assertRaises(TypeError): r.kindred_profiles['fake'] = r.kindred_profiles[THIEF]
        with self.assertRaises(TypeError): r.assemble_on_play_sources['fake'] = r.assemble_on_play_sources[THIEF]

    def test_b_runner_original_and_self_use_accepted_left_right_and_middle_positions(self):
        for cid in (RUNNER, recipe(RUNNER)):
            for hand, reward in (((cid, NOOP), 1), ((NOOP, cid), 1), ((NOOP, cid, NOOP), 0)):
                with self.subTest(cid=cid, hand=hand):
                    g = self.game(hand); mana = g.state.players[1].mana
                    self.play(g, cid)
                    self.assertEqual(self.count(g, COIN, zone='hand'), reward)
                    self.assertEqual(g.state.players[1].mana, mana - 1)
                    self.assertFalse(g.state.battlecry_history)
                    self.assertEqual(g.state.play_history[-1].outcast, bool(reward))

    def test_c_prepper_self_grants_original_hero_deadline_after_source_departure(self):
        cid = recipe(PREPPER)
        g = self.game((cid, KILL)); source = self.play(g, cid)
        hero = g.state.players[1].hero_id
        self.assertIn(Keyword.IMMUNE, g.state.entities[hero].keywords)
        self.play(g, KILL, source)
        self.assertIn(Keyword.IMMUNE, g.state.entities[hero].keywords)
        g.apply(EndTurn(1)); self.assertIn(Keyword.IMMUNE, g.state.entities[hero].keywords)
        g.apply(EndTurn(2)); self.assertNotIn(Keyword.IMMUNE, g.state.entities[hero].keywords)
        self.portable(g)

    def test_d_prepper_middle_has_no_reward_and_borrowed_outcast_has_no_native_immunity(self):
        g = self.game((NOOP, recipe(PREPPER), NOOP)); self.play(g, recipe(PREPPER))
        self.assertNotIn(Keyword.IMMUNE, g.state.entities[g.state.players[1].hero_id].keywords)
        cid = recipe(PREPPER, RUNNER)
        g = self.game((cid, NOOP)); self.play(g, cid)
        self.assertEqual(self.count(g, COIN, zone='hand'), 1)
        self.assertNotIn(Keyword.IMMUNE, g.state.entities[g.state.players[1].hero_id].keywords)

    def test_e_four_kindred_originals_and_self_recipes_use_real_native_components(self):
        for original, primer in ((DINO, DEMON), (FIREGILL, MURLOC), (THIEF, MURLOC), (QUEEN, BEAST)):
            for cid in (original, recipe(original)):
                with self.subTest(cid=cid):
                    g = self.prime(cid, primer, enemy=(NONE, NONE))
                    enemies = tuple(g.state.players[2].board)
                    self.play(g, cid)
                    row = g.state.kindred_history[-1]
                    self.assertTrue(row.condition.matched); self.assertTrue(row.completed)
                    self.assertEqual(row.card_id, cid); self.assertEqual(row.repetitions, 1)
                    self.assertFalse(g.state.battlecry_history)
                    if original == DINO:
                        self.assertEqual([g.state.entities[i].damage for i in enemies], [6, 6])
                    elif original == FIREGILL:
                        self.assertIn(Keyword.RUSH, g.state.entities[self.eid(g, primer)].keywords)
                        self.assertNotIn(Keyword.RUSH, g.state.entities[self.eid(g, cid)].keywords)
                    elif original == THIEF:
                        self.assertEqual(self.count(g, cards.TOKEN), 2)
                    else:
                        self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack, 5)
                        self.assertIn(Keyword.RUSH, g.state.entities[self.eid(g, cid)].keywords)

    def test_f_first_current_opponent_and_empty_latest_owner_turn_do_not_qualify(self):
        cid = recipe(THIEF)
        g = self.game((MURLOC, cid)); self.play(g, MURLOC); self.play(g, cid)
        self.assertFalse(g.state.kindred_history[-1].condition.matched)
        self.assertEqual(self.count(g, cards.TOKEN), 0)
        g = self.game((cid,), enemy_hand=(MURLOC,))
        g.apply(EndTurn(1)); self.play(g, MURLOC); g.apply(EndTurn(2)); self.play(g, cid)
        self.assertFalse(g.state.kindred_history[-1].condition.matched)
        g = self.prime(cid, MURLOC); self.cycle(g); self.play(g, cid)
        self.assertFalse(g.state.kindred_history[-1].condition.matched)
        self.portable(g)

    def test_g_borrowed_kindred_uses_assembled_primary_tribes_instead_of_donor_tribes(self):
        cid = recipe(THIEF, QUEEN, 'top')
        for primer, matched in ((MURLOC, True), (DEMON, False), (ALL, True), (NONE, False)):
            with self.subTest(primer=primer):
                g = self.prime(cid, primer); self.play(g, cid)
                row = g.state.kindred_history[-1]
                self.assertEqual(row.condition.matched, matched)
                self.assertEqual(self.count(g, cards.TOKEN), 2 if matched else 0)
                self.assertEqual(g.registry.card(cid).metadata.tribes, ('murloc',))
        self.portable(g)

    def test_h_borrowed_outcast_uses_assembled_hand_position_and_clears_original_kindred(self):
        cid = recipe(THIEF, RUNNER, 'top')
        g = self.game((cid, NOOP)); self.play(g, cid)
        self.assertEqual(self.count(g, cards.TOKEN), 2)
        self.assertFalse(g.state.kindred_history)
        self.assertEqual(self.count(g, COIN, zone='hand'), 0)
        self.assertIsNone(g.registry.kindred_profiles.get(cid))

    def test_i_next_kindred_doubles_component_once_with_single_payment(self):
        cid = recipe(THIEF)
        g = self.game((MURLOC, CHALLENGER, cid)); self.play(g, MURLOC); self.cycle(g)
        self.play(g, CHALLENGER); mana = g.state.players[1].mana
        self.play(g, cid)
        row = g.state.kindred_history[-1]
        self.assertEqual(row.repetitions, 2); self.assertEqual(row.plan, ('active', 'active'))
        self.assertEqual(self.count(g, cards.TOKEN), 4)
        self.assertEqual(g.state.players[1].mana, mana - 4)
        self.assertFalse(g.state.players[1].player_effects)
        self.portable(g)

    def test_j_unqualified_kindred_consumes_next_source_without_running_component(self):
        cid = recipe(THIEF)
        g = self.game((CHALLENGER, cid)); self.play(g, CHALLENGER); self.play(g, cid)
        row = g.state.kindred_history[-1]
        self.assertEqual(row.repetitions, 2); self.assertFalse(row.condition.matched)
        self.assertEqual(row.plan, ()); self.assertFalse(g.state.players[1].player_effects)
        self.assertEqual(self.count(g, cards.TOKEN), 0)

    def test_k_natural_summon_does_not_execute_on_play_or_kindred(self):
        g = self.game((SUMMON,))
        self.play(g, SUMMON)
        self.assertEqual(self.count(g, recipe(THIEF)), 1)
        self.assertEqual(self.count(g, cards.TOKEN), 0)
        self.assertFalse(g.state.kindred_history)
        self.assertFalse(g.state.battlecry_history)

    def test_l_kindred_wait_restores_in_distinct_registry_and_retains_accepted_source_after_departure(self):
        cid = recipe(THIEF)
        g = self.prime(cid, MURLOC, board=(WATCH,), mode='wait_token')
        self.play(g, cid); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.count(g, cards.TOKEN), 1)
        other = self.portable(g, 'wait_token')
        for game in (g, other):
            self.pick(game, 'depart'); self.assertEqual(self.count(game, cid, zone='hand'), 1)
            self.assertIsNotNone(game.state.pending_choice)
            self.pick(game)
            self.assertEqual(self.count(game, cards.TOKEN), 2)
            self.assertTrue(game.state.kindred_history[-1].completed)
        self.assertEqual(other.snapshot(), g.snapshot())

    def test_m_pending_kindred_failure_rolls_back_choice_armor_and_entire_continuation(self):
        cid = recipe(THIEF)
        g = self.prime(cid, MURLOC, board=(WATCH,), mode='wait_token'); self.play(g, cid)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        while g.state.pending_choice is not None: self.pick(g)
        self.assertEqual(self.count(g, cards.TOKEN), 2)
        self.portable(g, 'wait_token')

    def test_n_outcast_draw_wait_keeps_original_position_and_is_portable(self):
        cid = recipe(RUNNER)
        g = self.game((cid, NOOP), board=(WATCH,), mode='wait_draw'); self.play(g, cid)
        self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g, 'wait_draw')
        for game in (g, other): self.pick(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.count(g, COIN, zone='hand'), 1)
        self.assertTrue(g.state.play_history[-1].outcast)

    def test_o_generated_physical_kindred_reuses_native_matching_and_outcast_does_not_fake_hand_edge(self):
        cid = recipe(QUEEN)
        g = self.game((BEAST, cid, REPLAY)); self.play(g, BEAST); self.cycle(g)
        self.play(g, cid); self.play(g, REPLAY)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack, 10)
        self.assertEqual([r.card_id for r in g.state.kindred_history], [cid, cid])
        self.assertTrue(all(r.completed for r in g.state.kindred_history))
        self.portable(g)
        cid = recipe(RUNNER)
        g = self.game((cid, REPLAY)); self.play(g, cid); self.play(g, REPLAY)
        self.assertEqual(self.count(g, COIN, zone='hand'), 1)
        self.assertEqual(self.count(g, cid), 2)
        self.portable(g)

    def test_p_independent_new_bodies_execute_as_battlecry_without_old_outcast_or_kindred_guards(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                cid = recipe(BATTLECRY, donor)
                g = self.game((cid,), board=(MURLOC,), enemy=(NONE,))
                target = self.eid(g, NONE, 2); self.play(g, cid)
                self.assertFalse(g.state.kindred_history)
                if donor == RUNNER: self.assertEqual(self.count(g, COIN, zone='hand'), 1)
                elif donor == PREPPER:
                    self.assertIn(Keyword.IMMUNE, g.state.entities[g.state.players[1].hero_id].keywords)
                elif donor == DINO: self.assertEqual(g.state.entities[target].damage, 12)
                elif donor == FIREGILL:
                    self.assertIn(Keyword.RUSH, g.state.entities[self.eid(g, MURLOC)].keywords)
                elif donor == THIEF: self.assertEqual(self.count(g, cards.TOKEN), 2)
                else: self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack, 5)

    def test_q_deathrattle_and_owner_end_bodies_are_independent_of_native_play_conditions(self):
        cid = recipe(LOOT, THIEF)
        g = self.game((KILL,), board=(cid,)); self.play(g, KILL, self.eid(g, cid))
        self.assertEqual(self.count(g, cards.TOKEN), 2); self.assertFalse(g.state.kindred_history)
        cid = recipe(OWNER_END, RUNNER)
        g = self.game(board=(cid,)); g.apply(EndTurn(1))
        self.assertEqual(self.count(g, COIN, zone='hand'), 1)
        self.assertFalse(g.state.kindred_history)

    def test_r_missing_and_forged_original_minion_contexts_are_rejected(self):
        r = fixture(); g = self.game(board=(recipe(RUNNER),)); source = self.eid(g, recipe(RUNNER))
        behavior = r.behavior(r.card(recipe(RUNNER)).on_play)
        with self.assertRaises(ValueError): behavior(RuleContext(g.state, source, 1))
        g = self.game((recipe(RUNNER),)); source = self.play(g, recipe(RUNNER))
        with self.assertRaises(ValueError): behavior(RuleContext(g.state, source, 2, play=g.state.play_history[-1]))
        with self.assertRaises(ValueError): behavior(RuleContext(g.state, source, 1, play=g.state.play_history[-1]))

    def test_s_full_source_token_and_original_kindred_profile_drift_are_rejected(self):
        for cid in (RUNNER, THIEF, cards.TOKEN):
            r = fixture.__wrapped__()
            r._cards[cid] = replace(r.card(cid), health=r.card(cid).health + 1)
            with self.assertRaises(TargetValidationError): cards.register_assemble_minion_on_play_followups(r)
        r = fixture.__wrapped__()
        r._kindred_profiles[THIEF] = replace(r._kindred_profiles[THIEF], active=cards.PREFIX + 'draw')
        with self.assertRaises(TargetValidationError): cards.register_assemble_minion_on_play_followups(r)

    def test_t_source_declaration_duplicate_freeze_and_unreviewed_eligible_suffix_are_explicit(self):
        r = fixture.__wrapped__(); p = r.assemble_on_play_sources[RUNNER]
        with self.assertRaises(ValueError): r.register_assemble_on_play_source(p)
        with self.assertRaises(ValueError):
            r.register_assemble_on_play_source(replace(p, original_behavior_id=cards.PREFIX + 'draw'))
        self.game()
        with self.assertRaises(ValueError): fixture().register_assemble_on_play_source(p)
        with self.assertRaises(ValueError): AssemblePrefix('on_play')
        with self.assertRaises(ValueError):
            compatible(r.assemble_templates[RUNNER].prefix, AssembleSuffix('old.body', ('battlecry',)))

    def test_u_real_demon_hunter_offer_borrows_kindred_on_neutral_murloc_primary(self):
        cid = recipe(THIEF, QUEEN, 'top')
        g = self.game((MURLOC, FETCHER), mode='assemble'); self.play(g, MURLOC); self.cycle(g)
        self.play(g, FETCHER)
        q = g.state.pending_choice
        option = next(o.id for o in q.options if o.card_id == cid)
        self.pick(g, option)
        self.assertEqual(g.state.entities[self.eid(g, FETCHER)].zone, Zone.BOARD)
        mana = g.state.players[1].mana; self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, mana - 4)
        self.assertEqual(self.count(g, cards.TOKEN), 2)
        self.assertTrue(g.state.kindred_history[-1].condition.matched)
        self.portable(g, 'assemble')

    def test_v_saved_derived_kindred_condition_tampering_is_rejected_after_rehash(self):
        cid = recipe(THIEF); g = self.prime(cid, MURLOC); self.play(g, cid)
        saved = json.loads(json.dumps(g.snapshot()))
        condition = saved['state']['kindred_history'][-1]['condition']
        condition['matched'] = False
        for row in condition['rows']:
            row['matched'] = False
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as caught:
            Game.from_snapshot(saved, fixture('normal', 'reader'))
        self.assertIn('Kindred', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
