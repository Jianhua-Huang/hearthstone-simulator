"""Real native/Assemble entrances over small explicitly diagnostic domains."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import assemble_remaining_split_minions as cards
from hs_sim.cards.native_assemble_entry_cards import NURTURER, SHAPER, POOL_ID
from hs_sim.engine import (Attack, BoardPresenceReference, CardClass, CardDefinition,
    CardMetadata, CardType, EndTurn, Game, PlayerSetup, Scenario, SelectChoice,
    TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe, validate_template
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Destroy, ForceAttack,
    GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Silence, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

EXPLORER, HUCKSTER, SCRYER, SERPENT = cards.SOURCES
BASE, LOOT, COIN, FLAME = 'CORE_UNG_809', 'CORE_EX1_096', 'GAME_005', 'UNG_809t1'
DRAIN, CAIRNE = 'CORE_GIL_622', 'CORE_EX1_110'
DRAGONS = ('CORE_NEW1_023', 'CORE_DRG_079', 'CORE_LOOT_137')
MAGE = ('CS2_028', 'CS2_032', 'EX1_279', 'CATA_484')
IMP, JARAXXUS = 'CORE_EX1_319', 'CORE_EX1_323'
P = 'fixture.remaining_split.'
KILL, MUTE, BOUNCE, GIVE, FORCE, ACTIVE, WATCH, FAIL, UNKNOWN = (
    P+name for name in ('kill', 'mute', 'bounce', 'give', 'force', 'active', 'watch', 'fail', 'unknown'))
CTX = GenerationContext('k523-remaining-split-diagnostic', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
HEROES = {CardClass.HUNTER: 'HERO_05', CardClass.ROGUE: 'HERO_03',
    CardClass.MAGE: 'HERO_08', CardClass.PALADIN: 'HERO_04'}


def recipe(donor, half='bottom'):
    # A one-cost primary cannot accept a four-cost secondary. The real Shaper
    # instead selects Serpent as the sole ending primary, with two legal donors.
    return (AssembleRecipe(SERPENT, DRAIN, 'top' if half == 'bottom' else 'bottom')
        if donor == SERPENT else AssembleRecipe(BASE, donor, half))


@lru_cache(maxsize=None)
def fixture(donor=EXPLORER, mode='normal', role='writer'):
    r = build_registry()
    r._version += '.k523.'+donor+'.'+mode
    target = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
    bodies = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        MUTE: lambda c: (Silence(c.target_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        GIVE: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        FORCE: lambda c: (ForceAttack(BoardPresenceReference.capture(c.state, c.target_id),
            c.state.players[3-c.player_id].hero_id),),
        ACTIVE: lambda c: (TriggerDeathrattles(c.target_id, c.source_id, 2),),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, targeting=target, metadata=META))

    def fail(c):
        raise ResolutionError('deliberate remaining split draw failure')

    def watch(c):
        if c.event.player_id != c.player_id:
            return ()
        if mode == 'fail':
            return (GainArmor(c.player_id, 2), InvokeBehavior(FAIL, c.source_id, c.player_id))
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 2),
                InvokeBehavior(FAIL, c.source_id, c.player_id)))), c.source_id),)

    r.register_behavior(FAIL, fail)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=12, metadata=META,
        triggers=(TriggerSpec('card_drawn', WATCH),)))
    domain = (SERPENT, DRAIN, CAIRNE) if donor == SERPENT else (BASE, LOOT, donor)
    r.register_pool(PoolDefinition(POOL_ID, 'three-full-split-source-diagnostic-v1',
        CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in domain), complete=True))
    if mode != 'no_pool':
        members = DRAGONS+MAGE+(IMP,)
        if mode == 'unknown':
            r.register_pool_card(replace(r.pool_card(MAGE[0]), card_id=UNKNOWN, identity=UNKNOWN))
            members += (UNKNOWN,)
        r.register_pool(PoolDefinition(cards.POOL_ID, 'explicit-small-diagnostic-domain-v1',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    return r


class RemainingSplitTests(CardBatchTestMixin, unittest.TestCase):
    def registry_factory(self, mode, role):
        return fixture(self.donor, mode, role)

    def game(self, donor=EXPLORER, mode='normal', actor=1, board=(), extra=(), deck=None,
            enemy_hand=(), own_hero=None):
        self.donor, self.mode = donor, mode
        r = fixture(donor, mode)
        own_hero = own_hero or HEROES[r.card(donor).metadata.classes[0]]
        root = SHAPER if donor == SERPENT else NURTURER
        hand = (root, KILL, MUTE, BOUNCE, GIVE, FORCE, ACTIVE)+extra
        return Game.from_scenario(Scenario(tuple(PlayerSetup(
            own_hero if p == actor else 'HERO_08', hand=hand if p == actor else enemy_hand,
            board=board if p == actor else (), deck=deck if p == actor and deck is not None else (COIN,)*12,
            mana=30, max_mana=30, mana_cap=30) for p in (1, 2)),
            active_player=actor, seed=523, generation_context=CTX), r)

    def play(self, g, cid, target=None, player=None):
        return super().play(g, cid, target, player=g.state.active_player if player is None else player)

    def manufacture(self, g, half='bottom'):
        self.play(g, SHAPER if self.donor == SERPENT else NURTURER)
        cid = recipe(self.donor, half).card_id
        q = g.state.pending_choice
        option = next(x for x in q.options if x.card_id == cid)
        g.apply(SelectChoice(q.player_id, q.id, (option.id,)))
        return cid

    def finish_discovery(self, g):
        q = g.state.pending_choice
        self.assertIsNotNone(q)
        self.assertEqual({o.card_id for o in q.options}, set(DRAGONS))
        self.assertNotIn('options', json.dumps(g.for_player(3-q.player_id).observe()))
        selected = q.options[0].card_id
        g.apply(SelectChoice(q.player_id, q.id, (q.options[0].id,)))
        return selected

    def test_four_whole_sources_eight_primary_faces_exact_halves_and_separate_core_evidence(self):
        data, r = cards.load_batch(), fixture()
        rows = {x['record']['id']: x['record'] for x in data['cards']}
        self.assertEqual(len(data['official_observations']), 8)
        self.assertNotIn('CORE_OG_330', r.cards)
        for cid, raw in rows.items():
            card = r.card(cid)
            self.assertEqual((card.cost, card.attack, card.health), (raw['cost'], raw['attack'], raw['health']))
            self.assertEqual(card.metadata.deck_identity, cid)
            validate_template(r, r.assemble_templates[cid])
        self.assertEqual(r.assemble_templates[SCRYER].suffix.behavior_id, cards.SPELL_BODY)
        self.assertEqual(r.card(HUCKSTER).metadata.tribes, ('undead',))
        for obs in data['official_observations']:
            path = Path(obs['response_file'])
            self.assertEqual(batch.sha(path), obs['response_sha256'])
            faces = json.loads(path.read_text(encoding='utf-8-sig'))['cards']
            self.assertEqual([f for f in faces if f['id'] == rows[obs['card_id']]['dbf_id']], [obs['face']])
            batch.check_face(rows[obs['card_id']], obs['face'], obs['locale'])
        with patch.object(cards, 'BATCH_HASH', '0'*64), self.assertRaises(TargetValidationError):
            cards.load_batch()
        with self.assertRaises(TargetValidationError):
            cards.register_assemble_remaining_split_minions(r)

    def test_four_borrowed_bodies_through_actual_assemble_and_payment_for_both_players(self):
        for donor in cards.SOURCES:
            for actor in (1, 2):
                with self.subTest(donor=donor, actor=actor):
                    g = self.game(donor, actor=actor, deck=(COIN,)*8)
                    cid = self.manufacture(g)
                    mana = g.state.players[actor].mana
                    entity = self.play(g, cid)
                    self.assertEqual(g.state.players[actor].mana, mana-g.registry.card(cid).cost)
                    hand = [g.state.entities[i].card_id for i in g.state.players[actor].hand]
                    if donor == EXPLORER:
                        result = self.finish_discovery(g)
                        self.assertIn(result, [g.state.entities[i].card_id for i in g.state.players[actor].hand])
                    elif donor == HUCKSTER:
                        self.assertEqual(sum(cid in MAGE for cid in hand), 1)
                    else:
                        count = 1 if donor == SCRYER else 2
                        rows = [x for x in g.state.draw_history if x.source_id == entity]
                        self.assertEqual(len(rows), count)
                    self.assertNotIn(FLAME, [g.state.entities[i].card_id for i in g.state.players[actor].hand])

    def test_four_borrowed_prefixes_keep_original_body_and_real_timing(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                g = self.game(donor)
                cid = self.manufacture(g, 'top')
                entity = self.play(g, cid)
                if donor in (HUCKSTER, SCRYER):
                    self.assertNotIn(FLAME, [g.state.entities[i].card_id for i in g.state.players[1].hand])
                    self.play(g, KILL, entity)
                elif donor == SERPENT:
                    self.assertNotIn(FLAME, [g.state.entities[i].card_id for i in g.state.players[1].hand])
                    g.apply(EndTurn(1))
                else:
                    self.assertIn('poisonous', {k.value for k in g.state.entities[entity].keywords})
                if donor == SERPENT:
                    self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)
                else:
                    self.assertEqual(sum(g.state.entities[i].card_id == FLAME for i in g.state.players[1].hand), 1)
                self.assertFalse(any(x.source_id == entity for x in g.state.draw_history))

    def test_native_discovery_draw_generation_and_owner_end_entrances(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                g = self.game(donor, extra=(donor,))
                entity = self.play(g, donor)
                if donor == EXPLORER:
                    self.finish_discovery(g)
                elif donor in (HUCKSTER, SCRYER):
                    self.play(g, KILL, entity)
                    self.assertEqual(g.state.entities[entity].zone, Zone.GRAVEYARD)
                    if donor == HUCKSTER:
                        self.assertEqual(sum(g.state.entities[i].card_id in MAGE for i in g.state.players[1].hand), 1)
                    else:
                        self.assertEqual(len([x for x in g.state.draw_history if x.source_id == entity]), 1)
                else:
                    g.apply(EndTurn(1))
                    self.assertEqual(len([x for x in g.state.draw_history if x.source_id == entity]), 2)

    def test_scryer_moves_the_original_physical_spell_and_skips_empty_match_without_fatigue(self):
        g = self.game(SCRYER, board=(SCRYER,), deck=(BASE, COIN, BASE))
        source = self.entity(g, SCRYER, zone='board').id
        spell = next(i for i in g.state.players[1].deck if g.state.entities[i].card_id == COIN)
        self.play(g, ACTIVE, source)
        self.assertIn(spell, g.state.players[1].hand)
        self.assertEqual(len(g.state.players[1].deck), 2)
        rows = [x for x in g.state.draw_history if x.source_id == source]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].entity_id, spell)
        self.assertFalse(any(e.kind == 'fatigue' for e in g.events))

    def test_huckster_current_opponent_class_changes_after_real_hero_replacement(self):
        g = self.game(HUCKSTER, board=(HUCKSTER,), enemy_hand=(JARAXXUS,))
        source = self.entity(g, HUCKSTER, zone='board').id
        g.apply(EndTurn(1))
        self.play(g, JARAXXUS)
        self.assertEqual(g.state.players[2].hero_class, CardClass.WARLOCK)
        g.apply(EndTurn(2))
        self.play(g, KILL, source)
        self.assertEqual(sum(g.state.entities[i].card_id == IMP for i in g.state.players[1].hand), 1)
        self.assertFalse(any(g.state.entities[i].card_id in MAGE for i in g.state.players[1].hand))

    def test_huckster_same_class_and_active_repeated_deathrattles_stay_random(self):
        g = self.game(HUCKSTER, board=(HUCKSTER,), own_hero='HERO_08')
        source = self.entity(g, HUCKSTER, zone='board').id
        before_rng = g.snapshot()['rng_state']
        self.play(g, ACTIVE, source)
        self.assertEqual(g.state.entities[source].zone, Zone.BOARD)
        self.assertEqual(sum(g.state.entities[i].card_id in MAGE for i in g.state.players[1].hand), 2)
        self.assertNotEqual(g.snapshot()['rng_state'], before_rng)

    def test_serpent_normal_and_forced_attacks_block_even_without_spent_opportunity(self):
        for forced in (False, True):
            with self.subTest(forced=forced):
                g = self.game(SERPENT, board=(SERPENT,))
                source = self.entity(g, SERPENT, zone='board').id
                if forced:
                    self.play(g, FORCE, source)
                    self.assertEqual(g.state.entities[source].attacks_this_turn, 0)
                else:
                    g.apply(Attack(1, source, g.state.players[2].hero_id))
                self.assertFalse(cards.did_not_attack(RuleContext(g._state, source, 1)))
                g.apply(EndTurn(1))
                self.assertFalse(any(x.source_id == source for x in g.state.draw_history))

    def test_serpent_attack_gate_resets_by_turn_and_by_actual_reentry(self):
        g = self.game(SERPENT, board=(SERPENT,))
        source = self.entity(g, SERPENT, zone='board').id
        old_presence = BoardPresenceReference.capture(g.state, source)
        g.apply(Attack(1, source, g.state.players[2].hero_id))
        self.play(g, BOUNCE, source)
        self.play(g, SERPENT)
        self.assertEqual(self.entity(g, SERPENT, zone='board').id, source)
        self.assertNotEqual(BoardPresenceReference.capture(g.state, source), old_presence)
        self.assertTrue(cards.did_not_attack(RuleContext(g._state, source, 1)))
        g.apply(EndTurn(1))
        self.assertEqual(len([x for x in g.state.draw_history if x.source_id == source]), 2)
        g.apply(EndTurn(2))
        g.apply(EndTurn(1))
        self.assertEqual(len([x for x in g.state.draw_history if x.source_id == source]), 4)

    def test_control_keeps_original_attack_fact_and_silence_retires_original_end(self):
        g = self.game(SERPENT, board=(SERPENT,))
        source = self.entity(g, SERPENT, zone='board').id
        g.apply(Attack(1, source, g.state.players[2].hero_id))
        self.play(g, GIVE, source)
        self.assertFalse(cards.did_not_attack(RuleContext(g._state, source, 2)))
        self.play(g, MUTE, source)
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.assertFalse(any(x.source_id == source for x in g.state.draw_history))

    def test_missing_generation_pool_and_unknown_eligible_member_roll_back_real_death(self):
        for mode in ('no_pool', 'unknown'):
            with self.subTest(mode=mode):
                g = self.game(HUCKSTER, mode, board=(HUCKSTER,))
                source = self.entity(g, HUCKSTER, zone='board').id
                before = g.snapshot()
                with self.assertRaises((ValueError, ResolutionError)):
                    self.play(g, KILL, source)
                self.assertEqual(g.snapshot(), before)

    def test_real_assemble_then_discovery_wait_restores_clones_replays_and_private_choices(self):
        g = self.game(EXPLORER)
        self.play(g, NURTURER)
        saved = json.loads(json.dumps(g.snapshot()))
        independent = fixture(EXPLORER, 'normal', 'reader')
        legs = (g, Game.from_snapshot(saved, independent), g.clone(), replay(build_replay(g), independent))
        cid = AssembleRecipe(BASE, EXPLORER, 'bottom').card_id
        for leg in legs:
            q = leg.state.pending_choice
            option = next(o for o in q.options if o.card_id == cid)
            leg.apply(SelectChoice(q.player_id, q.id, (option.id,)))
            self.play(leg, cid)
            self.finish_discovery(leg)
        self.assertTrue(all(leg.snapshot() == g.snapshot() for leg in legs))
        for player in (1, 2):
            view = json.dumps(g.for_player(player).observe())
            for field in ('rng_state', 'resolution_frame', 'hand_entry_id'):
                self.assertNotIn('"'+field+'"', view)

    def test_death_draw_wait_and_late_failures_restore_original_transaction(self):
        g = self.game(SCRYER, 'wait', board=(SCRYER, WATCH))
        source = self.entity(g, SCRYER, zone='board').id
        self.play(g, KILL, source)
        saved = json.loads(json.dumps(g.snapshot()))
        with self.assertRaises(ResolutionError):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        independent = fixture(SCRYER, 'wait', 'reader')
        legs = (g, Game.from_snapshot(saved, independent), g.clone(), replay(build_replay(g), independent))
        for leg in legs:
            self.choose(leg)
        self.assertTrue(all(leg.snapshot() == g.snapshot() for leg in legs))
        bad = self.game(SCRYER, 'fail', board=(SCRYER, WATCH))
        source = self.entity(bad, SCRYER, zone='board').id
        before = bad.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(bad, KILL, source)
        self.assertEqual(bad.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
