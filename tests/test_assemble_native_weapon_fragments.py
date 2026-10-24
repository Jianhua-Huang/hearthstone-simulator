"""Existing native weapon bodies, exercised through real Assemble requests.

The small domains and injected source hands are diagnostic. They do not certify
the formal curated pool or a legal starting deck containing those source cards.
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
from hs_sim.cards import assemble_native_weapon_fragments as cards
from hs_sim.cards.native_assemble_entry_cards import FETCHER, NURTURER, FLESH, POOL_ID
from hs_sim.cards.simple_followup_p89_cards import PAST_POOL
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, DeckPolicy,
    DeckSpec, Game, Keyword, MatchSetup, OpeningHook, PlayerSetup, Rarity, Scenario,
    SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import (AddToHand, ChangeManaCrystals, ChoiceOption, Damage,
    Destroy, GainArmor, InvokeBehavior, RequestChoice, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

STAFF, BLADE, SHOVEL, GLAIVE, CHAIN, COG = cards.SOURCES
BASE, DRAIN, CAIRNE, CINDER, GOLEM = 'CORE_UNG_809', 'CORE_GIL_622', 'CORE_EX1_110', 'TLC_249', 'BE_861'
RECRUIT, DEMON, FLAME, COIN = 'CS2_101t', 'CORE_EX1_319', 'UNG_809t1', 'GAME_005'
P = 'fixture.assemble_native_weapon.'
KILL, HURT, ACTIVE, SUMMON, FILL, WEAPON, BOOT, PLAIN, WATCH, FAIL = (
    P+x for x in ('kill', 'hurt', 'active', 'summon', 'fill', 'weapon', 'boot', 'plain', 'watch', 'fail'))
CTX = GenerationContext('k521-native-weapon-domains', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
COLLECTIBLE = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())
HEROES = {CardClass.DEATH_KNIGHT: 'HERO_11', CardClass.PALADIN: 'HERO_04',
    CardClass.HUNTER: 'HERO_05', CardClass.DEMON_HUNTER: 'HERO_10', CardClass.WARRIOR: 'HERO_01'}


def base_and_root(donor, mode):
    if mode == 'death':
        return (GOLEM if donor == BLADE else CINDER), FLESH
    return (DRAIN, FETCHER) if donor == BLADE else (BASE, NURTURER)


@lru_cache(maxsize=None)
def fixture(donor, mode='normal', role='writer'):
    r = build_registry()
    r._version += '.k521.'+donor+'.'+mode
    target = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
    for cid, body in (
            (KILL, lambda c: (Destroy(c.target_id, c.source_id),)),
            (HURT, lambda c: (Damage(c.target_id, 1, c.source_id),)),
            (ACTIVE, lambda c: (TriggerDeathrattles(c.target_id, c.source_id),)),
            (SUMMON, lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(RECRUIT),), SummonCause.capture(c)),))):
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            metadata=META, targeting=None if cid == SUMMON else TargetSpec() if cid == HURT else target))
    r.register_card(CardDefinition(FILL, FILL, CardType.MINION, attack=2, health=6, metadata=META))
    r.register_card(CardDefinition(WEAPON, WEAPON, CardType.WEAPON, attack=1, durability=4, metadata=META))
    r.register_behavior(PLAIN, lambda c: ())
    r.register_card(CardDefinition(PLAIN, PLAIN, CardType.SPELL, on_play=PLAIN, metadata=COLLECTIBLE))
    root = base_and_root(donor, mode)[1]

    def boot(c):
        supplied = (root, KILL, WATCH) if mode in ('wait', 'fail') else (root, KILL)
        return (ChangeManaCrystals(c.player_id, 10, filled=True),
            *(AddToHand(c.player_id, cid, c.source_id) for cid in supplied),
            AddToDeck(c.player_id, PLAIN, 'bottom', c.source_id))

    r.register_behavior(BOOT, boot)
    r.register_card(CardDefinition(BOOT, BOOT, CardType.MINION, health=1, metadata=COLLECTIBLE,
        opening_hooks=(OpeningHook('after_mulligan', BOOT),)))

    def fail(c):
        raise ResolutionError('deliberate native weapon projection failure')

    def watch(c):
        source = c.state.entities.get(c.event.source_id)
        if source is None or not source.card_id.startswith('assemble:'):
            return ()
        if mode == 'fail':
            return (GainArmor(c.player_id, 1), InvokeBehavior(FAIL, c.source_id, c.player_id))
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1),
                InvokeBehavior(FAIL, c.source_id, c.player_id)))), c.source_id),)

    r.register_behavior(FAIL, fail)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=8, metadata=META,
        triggers=(TriggerSpec('card_drawn', WATCH),)))
    base, _ = base_and_root(donor, mode)
    other = DRAIN if donor == BLADE and mode == 'death' else CAIRNE if donor == BLADE else BASE if mode == 'death' else 'CORE_EX1_096'
    r.register_pool(PoolDefinition(POOL_ID, 'three-complete-reviewed-physical-sources-v1',
        CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in (base, other, donor)), complete=True))
    if mode != 'missing_past':
        r.register_pool(PoolDefinition(PAST_POOL, 'one-real-demon-diagnostic-domain-v1',
            CTX.target_id, CTX.mode, (PoolMember(DEMON),), complete=True))
    if mode == 'missing_projection':
        r._assemble_projections.pop(donor)
    return r


class AssembleNativeWeaponTests(CardBatchTestMixin, unittest.TestCase):
    def registry_factory(self, mode, role):
        return fixture(self.donor, mode, role)

    def game(self, donor, mode='normal', actor=1, board=(), enemy=(), extra=(), deck=None):
        self.donor, self.mode = donor, mode
        r = fixture(donor, mode)
        hero = HEROES[r.card(donor).metadata.classes[0]]
        _, root = base_and_root(donor, mode)
        if donor == SHOVEL and mode != 'no_opening':
            self.assertFalse(board or enemy or extra or deck)
            cls = r.card(donor).metadata.classes[0]
            contents = (BOOT,)+(PLAIN,)*11
            policy = DeckPolicy(P+'opening', CTX.target_id, CTX.mode, (BOOT, PLAIN), deck_size=12, max_copies=12)
            g = Game.from_decks(MatchSetup(tuple(DeckSpec(hero, hero+'bp', cls, contents)
                for _ in (1, 2)), policy, COIN, seed=521, first_player=actor), r)
            while g.state.pending_choice is not None:
                q = g.state.pending_choice
                g.apply(SelectChoice(q.player_id, q.id, ()))
            if mode in ('wait', 'fail'):
                self.play(g, WATCH)
            return g
        return Game.from_scenario(Scenario(tuple(PlayerSetup(hero,
            hand=(root, KILL, HURT, HURT, ACTIVE, SUMMON, *extra) if p == actor else (),
            board=board if p == actor else enemy, deck=deck or (COIN,)*20,
            weapon_card_id=WEAPON if p == actor else None, mana=30, max_mana=30, mana_cap=30)
            for p in (1, 2)), active_player=actor, seed=521, generation_context=CTX), r)

    def play(self, g, cid, target=None):
        return super().play(g, cid, target, player=g.state.active_player)

    def manufacture(self, g, half='bottom'):
        base, root = base_and_root(self.donor, self.mode)
        self.play(g, root)
        cid = AssembleRecipe(base, self.donor, half).card_id
        q = g.state.pending_choice
        option = next(x for x in q.options if x.card_id == cid)
        g.apply(SelectChoice(q.player_id, q.id, (option.id,)))
        return cid

    def assert_body(self, g, donor, source, player=1):
        own = g.state.players[player]
        if donor == STAFF:
            self.assertFalse(own.board)
            self.assertFalse(g.state.players[3-player].board)
        elif donor == BLADE:
            effects = [x for x in own.player_effects if x.spec_id == g.registry.card(BLADE).battlecry]
            self.assertEqual(len(effects), 1)
            self.assertEqual(effects[0].source_id, source)
        elif donor == SHOVEL:
            rows = [x for x in g.state.draw_history if x.source_id == source]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].card_id, PLAIN)
            self.assertNotIn(rows[0].entity_id, g.state.opening.original_entities[player-1])
            self.assertEqual(rows[0].outcome, 'hand')
        elif donor == GLAIVE:
            self.assertEqual(sum(g.state.entities[i].card_id == DEMON for i in own.hand), 1)
        elif donor == CHAIN:
            target = next(g.state.entities[i] for i in own.board if g.state.entities[i].card_id == FILL)
            self.assertEqual((target.attack, target.max_health, target.health), (3, 8, 7))
        else:
            recipients = [g.state.entities[i] for i in own.board
                if Keyword.DIVINE_SHIELD in g.state.entities[i].keywords and Keyword.TAUNT in g.state.entities[i].keywords]
            self.assertEqual(len(recipients), 1 if own.board else 0)

    def test_six_complete_originals_twelve_primary_faces_and_exact_program_are_preserved(self):
        d = cards.load_batch()
        r = fixture(COG)
        rows = {x['record']['id']: x for x in d['existing_dependencies']}
        self.assertEqual(len(d['official_observations']), 12)
        for cid, row in rows.items():
            original, projected = r.card(cid), r.assemble_projections[cid]
            self.assertEqual(batch.canonical(asdict(original)), row['definition_sha256'])
            self.assertEqual(projected.source_kind, CardType.WEAPON)
            self.assertEqual(projected.suffix.behavior_id, original.battlecry or original.deathrattle)
        for obs in d['official_observations']:
            p = Path(obs['response_file'])
            self.assertEqual(batch.sha(p), obs['response_sha256'])
            body = json.loads(p.read_text(encoding='utf-8-sig'))
            row = rows[obs['card_id']]['record']
            self.assertEqual([x for x in body['cards'] if x['id'] == row['dbf_id']], [obs['face']])
            batch.check_face(row, obs['face'], obs['locale'])
        self.assertEqual(batch.canonical(asdict(r.player_effect(r.card(BLADE).battlecry))),
            batch.canonical(d['original_player_effects'][BLADE]))

    def test_shovel_real_opening_battlecry_both_seats_draws_new_same_face_physical_card(self):
        for actor in (1, 2):
            with self.subTest(actor=actor):
                g = self.game(SHOVEL, actor=actor)
                mana = g.state.players[actor].mana
                cid = self.manufacture(g)
                source = self.play(g, cid)
                self.assert_body(g, SHOVEL, source, actor)
                self.assertEqual(g.state.players[actor].mana, mana-g.registry.card(NURTURER).cost-g.registry.card(BASE).cost)
                self.assertIsNone(g.state.players[actor].weapon_id)

    def test_blade_borrowed_program_changes_all_recruit_zones_and_outlives_minion(self):
        g = self.game(BLADE, board=(RECRUIT,), extra=(RECRUIT,), deck=(RECRUIT, COIN))
        cid = self.manufacture(g)
        source = self.play(g, cid)
        self.assert_body(g, BLADE, source)
        for zone in ('hand', 'deck', 'board'):
            recruits = [g.state.entities[i] for i in getattr(g.state.players[1], zone)
                if g.state.entities[i].card_id == RECRUIT]
            self.assertEqual(len(recruits), 1)
            self.assertEqual((recruits[0].attack, recruits[0].max_health), (2, 2))
        self.play(g, KILL, source)
        self.play(g, SUMMON)
        recruits = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == RECRUIT]
        self.assertEqual(len(recruits), 2)
        self.assertTrue(all((x.attack, x.max_health) == (2, 2) for x in recruits))

    def test_remaining_four_real_battlecries_pay_base_once_and_do_not_equip_weapons(self):
        for donor in (STAFF, GLAIVE, CHAIN, COG):
            with self.subTest(donor=donor):
                board = (FILL,) if donor == CHAIN else ()
                g = self.game(donor, board=board, enemy=(FILL,) if donor == STAFF else ())
                mana = g.state.players[1].mana
                weapon = g.state.players[1].weapon_id
                if donor == CHAIN:
                    self.play(g, HURT, g.state.players[1].board[0])
                cid = self.manufacture(g)
                source = self.play(g, cid)
                self.assert_body(g, donor, source)
                self.assertEqual(g.state.players[1].mana, mana-g.registry.card(NURTURER).cost-g.registry.card(BASE).cost)
                self.assertEqual(g.state.players[1].weapon_id, weapon)
                self.assertEqual(g.state.entities[weapon].durability, 4)
                self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)

    def test_all_six_real_natural_death_bodies_keep_original_carrier_and_payment(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                board = (FILL,) if donor == CHAIN else ()
                g = self.game(donor, 'death', board=board, enemy=(FILL,) if donor == STAFF else ())
                mana = g.state.players[1].mana
                if donor == CHAIN:
                    self.play(g, HURT, g.state.players[1].board[0])
                cid = self.manufacture(g)
                source = self.play(g, cid)
                self.assertEqual(g.state.entities[source].zone, Zone.BOARD)
                self.play(g, KILL, source)
                self.assert_body(g, donor, source)
                base, root = base_and_root(donor, 'death')
                self.assertEqual(g.state.players[1].mana, mana-g.registry.card(root).cost-g.registry.card(base).cost)
                self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)

    def test_four_weapon_death_prefixes_keep_only_real_minion_body(self):
        for donor in (STAFF, SHOVEL, GLAIVE, CHAIN):
            with self.subTest(donor=donor):
                g = self.game(donor)
                cid = self.manufacture(g, 'top')
                source = self.play(g, cid)
                self.assertFalse(any(g.state.entities[i].card_id == FLAME for i in g.state.players[1].hand))
                self.play(g, KILL, source)
                self.assertEqual(sum(g.state.entities[i].card_id == FLAME for i in g.state.players[1].hand), 1)
                self.assertTrue(any(g.state.entities[i].card_id == NURTURER for i in g.state.players[1].board))
                self.assertFalse(any(x.source_id == source for x in g.state.draw_history))
                self.assertFalse(any(g.state.entities[i].card_id == DEMON for i in g.state.players[1].hand))

    def test_two_weapon_battlecry_prefixes_retain_minion_body_without_weapon_program(self):
        for donor in (BLADE, COG):
            with self.subTest(donor=donor):
                g = self.game(donor, 'death')
                hero = g.state.players[1].hero_id
                if donor == BLADE:
                    self.play(g, HURT, hero)
                cid = self.manufacture(g, 'top')
                source = self.play(g, cid)
                self.assertEqual(g.state.entities[source].zone, Zone.BOARD)
                self.assertFalse(g.state.players[1].player_effects)
                if donor == BLADE:
                    self.assertEqual(g.state.entities[hero].health, 30)
                else:
                    self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28)
                    self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[source].keywords)

    def test_cog_live_body_can_select_carrier_and_dead_empty_pool_does_not_draw_rng(self):
        g = self.game(COG)
        cid = self.manufacture(g)
        root = self.entity(g, NURTURER, zone='board').id
        self.play(g, KILL, root)
        source = self.play(g, cid)
        self.assertTrue({Keyword.DIVINE_SHIELD, Keyword.TAUNT}.issubset(g.state.entities[source].keywords))
        g = self.game(COG, 'death')
        cid = self.manufacture(g)
        source = self.play(g, cid)
        rng = g._rng.getstate()
        self.play(g, KILL, source)
        self.assertFalse(g.state.players[1].board)
        self.assertEqual(g._rng.getstate(), rng)

    def test_chain_active_and_natural_death_use_current_damaged_friendly_minions(self):
        g = self.game(CHAIN, 'death', board=(FILL, FILL))
        damaged, full = g.state.players[1].board
        cid = self.manufacture(g)
        source = self.play(g, cid)
        self.play(g, HURT, source)
        self.play(g, HURT, damaged)
        self.play(g, ACTIVE, source)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health), (5, 5))
        self.assertEqual((g.state.entities[damaged].attack, g.state.entities[damaged].max_health), (3, 8))
        self.assertEqual((g.state.entities[full].attack, g.state.entities[full].max_health), (2, 6))
        self.play(g, KILL, source)
        self.assertEqual((g.state.entities[damaged].attack, g.state.entities[damaged].max_health), (4, 10))
        self.assertEqual((g.state.entities[full].attack, g.state.entities[full].max_health), (2, 6))

    def test_actual_physical_draw_wait_independently_restores_clones_replays_and_finishes(self):
        g = self.game(SHOVEL, 'wait')
        cid = self.manufacture(g)
        self.play(g, cid)
        self.assertIsNotNone(g.state.pending_choice)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate native weapon'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        reader = fixture(SHOVEL, 'wait', 'independent-reader')
        self.assertIsNot(reader, g.registry)
        legs = (g, Game.from_snapshot(json.loads(json.dumps(saved)), reader), g.clone(), replay(build_replay(g), reader))
        for other in legs:
            self.assertEqual(other.snapshot(), saved)
            self.choose(other)
            self.assertIsNone(other.state.pending_choice)
        self.assertTrue(all(other.snapshot() == g.snapshot() for other in legs))
        for player in (1, 2):
            view = json.dumps(g.for_player(player).observe())
            for key in ('rng_state', 'resolution_frame', 'submitted_cost', 'hand_entry_id'):
                self.assertNotIn('"'+key+'"', view)

    def test_late_actual_draw_failure_rolls_back_minion_payment_physical_card_and_rng(self):
        g = self.game(SHOVEL, 'fail')
        cid = self.manufacture(g)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate native weapon'):
            self.play(g, cid)
        self.assertEqual(g.snapshot(), saved)

    def test_missing_original_opening_past_domain_and_projection_remain_explicit_and_atomic(self):
        for donor, mode in ((SHOVEL, 'no_opening'), (GLAIVE, 'missing_past'), (STAFF, 'missing_projection')):
            with self.subTest(donor=donor, mode=mode):
                g = self.game(donor, mode)
                if mode != 'missing_projection':
                    cid = self.manufacture(g)
                saved = g.snapshot()
                with self.assertRaises((ResolutionError, ValueError)):
                    self.play(g, NURTURER if mode == 'missing_projection' else cid)
                self.assertEqual(g.snapshot(), saved)
                self.assertIn(donor, [x.card_id for x in g.registry.pool(POOL_ID, CTX).members])

    def test_last_full_original_program_conflict_rejects_before_any_projection_install(self):
        r = fixture(COG)
        before = r.fingerprint()
        bad = deepcopy(cards.load_batch())
        bad['original_player_effects'][BLADE]['duration'] = 2
        with patch.object(cards, 'load_batch', lambda: bad):
            with self.assertRaisesRegex(TargetValidationError, 'persistent program'):
                cards.register_assemble_native_weapon_fragments(r)
        self.assertEqual(r.fingerprint(), before)


if __name__ == '__main__':
    unittest.main()
