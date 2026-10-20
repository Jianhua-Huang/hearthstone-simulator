import json
import unittest
from dataclasses import asdict, replace
from functools import lru_cache

from hs_sim.cards import build_registry
from hs_sim.cards.draw_type_native_cards import BOMB, DOMINATOR, MAGE, PREFIX, WATER, WELLSPRING, load_batch
from hs_sim.engine import (CardDefinition, CardType, CastWhenDrawnSpec, EndTurn, Game, Keyword,
    PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, UseLocation, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (ChoiceOption, Draw, GainArmor, RequestChoice)
from hs_sim.engine.model import CardClass, CardMetadata
from hs_sim.engine.physical_draw_groups import CapturePhysicalDrawGroup, DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face

P = 'fixture.draw_type_native.'
PLAIN, MECH, ALL, SD, UNKNOWN, GIFT, WATCH, PORTAL, BAD = tuple(P+x for x in (
    'plain', 'mech', 'all', 'sd', 'unknown', 'gift', 'watch', 'portal', 'bad'))
COIN = 'GAME_005'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(maxsize=None)
def fixture(mode='normal', role='writer'):
    if role not in ('writer', 'reader'): raise ValueError('Independent fixture registries required')
    r = build_registry()
    for cid, tribes in ((PLAIN, ()), (MECH, ('mech',)), (ALL, ('all',)), (UNKNOWN, None)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1, attack=1, health=10,
            metadata=replace(META, tribes=tribes)))
    r.register_card(CardDefinition(SD, SD, CardType.MINION, health=10, spell_damage=1, metadata=META))
    r.register_behavior(P+'gift', lambda c: (SummonByCard(3-c.player_id, (SummonEntryMaterial(MECH),), SummonCause.capture(c)),))
    r.register_card(CardDefinition(GIFT, GIFT, CardType.MINION, health=10, deathrattle=P+'gift', metadata=META))
    r.register_behavior(P+'noop', lambda c: ())
    r.register_card(CardDefinition(PORTAL, PORTAL, CardType.SPELL, metadata=META,
        keywords=(Keyword.CASTS_WHEN_DRAWN,), cast_when_drawn=CastWhenDrawnSpec(), on_play=P+'noop'))
    r.register_behavior(BAD, lambda c: (DrawPhysicalGroup(c.player_id, c.source_id, (DrawGroupSlot(),),
        DrawGroupReward('non_minion_followup', behavior_id=P+'not_registered')),))
    r.register_card(CardDefinition(BAD, BAD, CardType.SPELL, metadata=META, on_play=BAD))
    if mode != 'normal':
        def observe(c):
            entity = c.state.entities.get(c.event.target_id)
            if mode == 'water_fail':
                if entity is not None and entity.card_id == WATER:
                    raise ResolutionError('Explicit original draw followup failure')
                return ()
            if mode == 'bomb_fail':
                if c.event.target_id == c.state.players[2].hero_id:
                    raise ResolutionError('Explicit bomb damage observer failure')
                return ()
            source = c.state.entities.get(c.event.source_id)
            if mode == 'transform_wait':
                if entity is None or entity.card_id != DOMINATOR: return ()
            elif source is None or source.card_id not in (WELLSPRING, MAGE):
                return ()
            hero = c.state.entities[c.state.players[c.player_id].hero_id]
            if hero.armor: return ()
            marker = GainArmor(c.player_id, 1)
            if mode == 'draw_extra': return (marker, Draw(c.player_id, 1, c.source_id))
            if mode == 'draw_transform':
                return (marker, TransformStoredCard(CardReference.capture(entity), PLAIN, c.source_id))
            return (marker, RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),), c.source_id))
        event = ('minion_summoned' if mode == 'water_fail' else 'damage_dealt' if mode == 'bomb_fail' else
            'transformed' if mode == 'transform_wait' else 'card_drawn')
        r.register_behavior(WATCH, observe)
        r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
            triggers=(TriggerSpec(event, WATCH),)))
    return r


class DrawTypeNativeTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), deck=(COIN,)*10, mode='normal'):
        if mode != 'normal': board = (WATCH,)+board
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
            mana=10, max_mana=10), PlayerSetup('HERO_08', board=enemy, deck=(COIN,)*10,
            mana=10, max_mana=10)), seed=0), fixture(mode))

    def play(self, g, cid, position=None):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid, position=position)); return eid

    def use(self, g, source=None):
        if source is None: source = next(i for i in g.state.players[1].board if g.state.entities[i].card_id == WELLSPRING)
        g.apply(UseLocation(1, source)); return source

    def choose(self, g):
        c = g.state.pending_choice; g.apply(SelectChoice(c.player_id, c.id, ('continue',)))

    def waters(self, g):
        return [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == WATER]

    def portable(self, g, mode='normal'):
        saved = g.snapshot(); r = fixture(mode, 'reader')
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)), r).snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        for p in (1, 2):
            visible = json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in ('"rng_state"', '"draw_history"', '"arrivals"', '"behavior_id"'):
                self.assertNotIn(key, visible)

    def test_four_complete_roots_and_original_water_have_ten_primary_faces(self):
        data = load_batch(); rows = {x['record']['id']: x['record'] for x in data['cards']+data['existing_dependencies']}
        self.assertEqual(len(data['official_observations']), 10)
        for o in data['official_observations']: check_face(rows[o['card_id']], o['face'], o['locale'])
        r = fixture(); self.assertEqual(r.card(WELLSPRING).kind, CardType.LOCATION)
        self.assertEqual((r.card(WELLSPRING).cost, r.card(WELLSPRING).durability), (3, 2))
        self.assertEqual(canonical_digest(asdict(r.card(WATER))), data['existing_dependencies'][0]['definition_sha256'])

    def test_location_placement_has_no_draw_and_spell_draw_refreshes_two_on_use(self):
        g = self.game((WELLSPRING,), deck=(COIN,)); source = self.play(g, WELLSPRING)
        self.assertEqual(g.state.players[1].mana, 7); self.assertFalse(g.state.draw_history)
        self.use(g, source); self.assertEqual(g.state.players[1].mana, 9)
        self.assertEqual(g.state.entities[source].durability, 1); self.assertEqual(len(g.state.players[1].hand), 1)
        self.portable(g)

    def test_location_minion_and_fatigue_do_not_refresh_and_full_mana_is_capped(self):
        for deck, expected in (((PLAIN,), 7), ((), 7), ((COIN,), 9)):
            with self.subTest(deck=deck):
                g = self.game((WELLSPRING,), deck=deck); self.play(g, WELLSPRING); self.use(g)
                self.assertEqual(g.state.players[1].mana, expected)
        g = self.game(board=(WELLSPRING,)); self.use(g); self.assertEqual(g.state.players[1].mana, 10)

    def test_location_wait_preserves_original_draw_before_mana_reward(self):
        g = self.game((WELLSPRING,), deck=(COIN,), mode='draw_wait'); self.play(g, WELLSPRING); source = self.use(g)
        self.assertEqual(g.state.players[1].mana, 7); self.portable(g, 'draw_wait')
        self.choose(g); self.assertEqual(g.state.players[1].mana, 9)
        self.assertEqual(g.state.entities[source].durability, 1)

    def test_mage_draws_two_then_summons_one_real_water_per_original_non_minion(self):
        for deck, count in (((COIN, COIN), 2), ((COIN, PLAIN), 1), ((PLAIN, PLAIN), 0), ((), 0)):
            with self.subTest(deck=deck):
                g = self.game((MAGE,), deck=deck); source = self.play(g, MAGE)
                self.assertEqual(len(g.state.draw_history), 2); self.assertEqual(len(self.waters(g)), count)
                self.assertEqual(g.state.players[1].mana, 5)
                self.assertTrue(all((e.attack, e.health) == (3, 6) for e in self.waters(g)))
                self.assertTrue(all(d.source_id == source for d in g.state.draw_history))
        self.portable(g)

    def test_mage_wait_has_no_early_reward_and_resumes_original_group_once(self):
        g = self.game((MAGE,), deck=(COIN, COIN), mode='draw_wait'); self.play(g, MAGE)
        self.assertFalse(self.waters(g)); self.assertEqual(len(g.state.draw_history), 1)
        self.portable(g, 'draw_wait'); self.choose(g)
        self.assertEqual(len(g.state.draw_history), 2); self.assertEqual(len(self.waters(g)), 2)

    def test_mage_burned_non_minion_still_has_original_type_reward(self):
        g = self.game((MAGE,)+(COIN,)*9, deck=(COIN, COIN)); self.play(g, MAGE)
        self.assertEqual([d.outcome for d in g.state.draw_history], ['hand', 'burned'])
        self.assertEqual(len(self.waters(g)), 2)

    def test_mage_full_board_draws_but_does_not_make_phantom_waters(self):
        g = self.game((MAGE,), (PLAIN,)*6, deck=(COIN, COIN)); self.play(g, MAGE)
        self.assertEqual(len(g.state.draw_history), 2); self.assertEqual(len(self.waters(g)), 0)

    def test_reaction_draw_is_excluded_and_changed_hand_face_does_not_change_root_type(self):
        g = self.game((MAGE,), deck=(COIN, COIN, PLAIN), mode='draw_extra'); self.play(g, MAGE)
        self.assertEqual(len(g.state.draw_history), 3); self.assertEqual(len(self.waters(g)), 1)
        g = self.game((MAGE,), deck=(COIN, PLAIN), mode='draw_transform'); self.play(g, MAGE)
        self.assertEqual(len(self.waters(g)), 1)
        self.assertTrue(all(g.state.entities[i].card_id == PLAIN for i in g.state.players[1].hand))

    def test_draw_cast_replacement_counts_original_non_minion_not_replacement_leaf(self):
        g = self.game((MAGE,), deck=(PORTAL, PLAIN, PLAIN)); self.play(g, MAGE)
        self.assertEqual(len(g.state.draw_history), 3); self.assertEqual(len(self.waters(g)), 1)
        self.assertEqual(sum(d.parent_id is None for d in g.state.draw_history), 2); self.portable(g)

    def test_late_water_failure_rolls_back_draws_cost_and_created_bodies(self):
        g = self.game((MAGE,), deck=(COIN, COIN), mode='water_fail'); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Explicit original draw'): self.play(g, MAGE)
        self.assertEqual(g.snapshot(), saved)

    def test_dominator_transforms_only_original_adjacent_minions_without_replaying_battlecry(self):
        g = self.game((DOMINATOR,), (PLAIN, MECH, PLAIN), deck=()); old = tuple(g.state.players[1].board)
        source = self.play(g, DOMINATOR, 1)
        self.assertEqual(g.state.players[1].board, [old[0], source, old[1], old[2]])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],
            [DOMINATOR, DOMINATOR, DOMINATOR, PLAIN])
        self.assertEqual(sum(e.kind == 'transformed' for e in g.events), 2)
        self.assertFalse(g.state.draw_history); self.portable(g)

    def test_dominator_location_blocks_adjacency_and_single_edge_target_is_preserved(self):
        g = self.game((DOMINATOR,), (WELLSPRING, PLAIN)); old = tuple(g.state.players[1].board)
        self.play(g, DOMINATOR, 0)
        self.assertEqual((g.state.entities[old[0]].card_id, g.state.entities[old[1]].card_id), (WELLSPRING, PLAIN))
        g = self.game((DOMINATOR,), (PLAIN,)); original = g.state.players[1].board[0]
        self.play(g, DOMINATOR, 0); self.assertEqual(g.state.entities[original].card_id, DOMINATOR)

    def test_dominator_first_transform_wait_restores_second_original_target(self):
        g = self.game((DOMINATOR,), (PLAIN, PLAIN), mode='transform_wait')
        source = self.play(g, DOMINATOR, 2); self.assertIsNotNone(g.state.pending_choice)
        self.portable(g, 'transform_wait'); self.choose(g)
        self.assertEqual(sum(g.state.entities[i].card_id == DOMINATOR for i in g.state.players[1].board), 3)
        self.assertEqual(g.state.entities[source].zone, Zone.BOARD)

    def test_bomb_single_wave_and_friendly_current_mech_or_all_repeat_once(self):
        for board, count in (((), 1), ((MECH,), 2), ((ALL,), 2)):
            with self.subTest(board=board):
                g = self.game((BOMB,), board, (PLAIN, PLAIN)); self.play(g, BOMB)
                self.assertEqual(len(g.state.players[2].board), 2-count)
                self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30-3*count)
        self.portable(g)

    def test_bomb_empty_enemy_board_still_deals_damage_and_uses_spell_power_per_wave(self):
        g = self.game((BOMB,), (MECH, SD)); self.play(g, BOMB)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 22)
        g = self.game((BOMB,), enemy=(MECH, PLAIN)); self.play(g, BOMB)
        self.assertEqual(len(g.state.players[2].board), 1)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)

    def test_bomb_repeat_reads_mech_created_by_first_actual_death_reaction(self):
        g = self.game((BOMB,), enemy=(GIFT,)); self.play(g, BOMB)
        self.assertTrue(any(g.state.entities[i].card_id == MECH for i in g.state.players[1].board))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 24)

    def test_bomb_late_failure_and_unknown_current_tribe_roll_back_whole_spell(self):
        for mode, board in (('bomb_fail', ()), ('normal', (UNKNOWN,))):
            with self.subTest(mode=mode):
                g = self.game((BOMB,), board, (PLAIN, PLAIN), mode=mode); saved = g.snapshot()
                with self.assertRaises((ResolutionError, UnsupportedDefinitionError)): self.play(g, BOMB)
                self.assertEqual(g.snapshot(), saved)

    def test_reward_shape_unknown_callback_and_previous_schema_are_rejected(self):
        for args in ({'kind':'non_minion_followup'}, {'kind':'none','behavior_id':PREFIX+'water'},
                {'kind':'non_minion_followup','behavior_id':PREFIX+'water','amount':1}):
            with self.subTest(args=args), self.assertRaises(ValueError): DrawGroupReward(**args)
        g = self.game((BAD,)); saved = g.snapshot()
        with self.assertRaises((ResolutionError, UnsupportedDefinitionError)): self.play(g, BAD)
        self.assertEqual(g.snapshot(), saved)
        bad = json.loads(json.dumps(saved)); bad['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, fixture())

    def test_pending_original_type_reward_codec_validates_registered_callback(self):
        g = self.game((MAGE,), deck=(COIN, PLAIN), mode='draw_wait'); source = self.play(g, MAGE); s = g.state
        request = CapturePhysicalDrawGroup(1, source, (DrawGroupSlot(),)*2,
            DrawGroupReward('non_minion_followup', behavior_id=PREFIX+'water'),
            draw_id=s.draw_history[0].id, hand_cursor=len(s.hand_entries)-1)
        codec = FrameCodec(default_mechanics(), g.registry, origin_state=s)
        self.assertEqual(codec.decode(codec.encode(request)), request)
        with self.assertRaises((ValueError, UnsupportedDefinitionError)):
            codec.encode(replace(request, reward=DrawGroupReward('non_minion_followup', behavior_id=P+'missing')))
