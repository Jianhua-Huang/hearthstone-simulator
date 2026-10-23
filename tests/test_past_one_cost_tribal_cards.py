from dataclasses import asdict, replace
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.past_one_cost_tribal_cards import (
    CHUM, EGG, FOWL, GUIDE, HELBOAR, KINDLING, LEAVES, LYNX, OSCILLATOR,
    PEASANT, SHARD, SLAYER, SPRINGPAW, load_batch, register_past_one_cost_tribal_cards,
)
from hs_sim.engine import (
    Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction, Keyword, PlayCard,
    PlayerSetup, Registry, Scenario, SelectChoice, TargetSpec, TriggerSpec, UseHeroPower, Zone,
)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (
    Buff, ChangeControl, ChoiceOption, Destroy, InvokeBehavior, RequestChoice, Silence, TriggerDeathrattles,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import TargetMode, TribeChangeSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face


P = 'k455.'
KILL, SILENCE, TAKE, GROW, FAIL, WATCH, ZERO_MECH, UNKNOWN = (
    P + name for name in ('kill', 'silence', 'take', 'grow', 'fail', 'watch', 'zero_mech', 'unknown'))
YETI, RAVEN, MURLOC, FLASHBACK = 'CORE_CS2_182', 'KAR_300', 'ICC_220', 'TIME_711'
CONTEXT = GenerationContext('k455-explicit-ten-leaf-experiment', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry()
    r.register_pool(PoolDefinition('constructed.past.cards', 'explicit-ten-leaves-v1',
        CONTEXT.target_id, CONTEXT.mode, tuple(PoolMember(cid) for cid in LEAVES), complete=True))
    r.register_card(CardDefinition(ZERO_MECH, 'Diagnostic zero Mech', CardType.MINION,
        attack=1, health=1, metadata=replace(r.card(OSCILLATOR).metadata,
            collectible=False, deck_identity=ZERO_MECH)))
    r.register_card(CardDefinition(UNKNOWN, 'Diagnostic unknown tribe', CardType.MINION,
        cost=1, attack=1, health=1, metadata=replace(r.card(YETI).metadata,
            collectible=False, tribes=None, deck_identity=UNKNOWN)))

    def fail(c):
        raise ResolutionError('K455 deliberate followup failure')

    def change(c, cid, tribes):
        eid = next(i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == cid)
        return (ChangeMinionTribes(CardReference.capture(c.state.entities[eid]),
            TribeChangeSpec('set', tribes), c.source_id),)

    bodies = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        SILENCE: lambda c: (Silence(c.target_id),),
        TAKE: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        GROW: lambda c: (Buff(c.target_id, 2, 3, c.source_id),),
        P+'trigger': lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        FAIL: fail,
        P+'plain_beast': lambda c: change(c, YETI, ('beast',)),
        P+'plain_murloc': lambda c: change(c, YETI, ('murloc',)),
        P+'plain_elemental': lambda c: change(c, YETI, ('elemental',)),
        P+'plain_mech': lambda c: change(c, YETI, ('mech',)),
        P+'strip_raven': lambda c: change(c, RAVEN, ()),
        P+'strip_murloc': lambda c: change(c, MURLOC, ()),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            targeting=TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,))
                if cid in (KILL, SILENCE, TAKE, GROW, P+'trigger') else None))

    def watch(c):
        if c.event.player_id != c.player_id or c.event.target_id is None:
            return ()
        if c.state.entities[c.event.target_id].card_id not in (YETI, LYNX, FOWL):
            return ()
        if mode == 'fail':
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)

    watch_behavior = WATCH + '.' + mode
    r.register_behavior(watch_behavior, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=40,
        triggers=tuple(TriggerSpec(event, watch_behavior) for event in
            ('stored_card_buffed', 'card_added_to_hand', 'minion_summoned', 'card_drawn'))
            if mode != 'normal' else ()))
    r.validate()
    return r


class PastOneCostTribalTests(unittest.TestCase):
    def game(self, hand=(), board=(), *, enemy_hand=(), enemy_board=(),
             deck=(), enemy_deck=(), mode='normal', active=1):
        self.mode = mode
        marker = () if mode == 'normal' else (WATCH,)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=marker + board, deck=deck,
                hero_power_card_id='HERO_08bp', mana=10, max_mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board, deck=enemy_deck,
                hero_power_card_id='HERO_08bp', mana=10, max_mana=10)),
            active_player=active, seed=455, generation_context=CONTEXT), fixture(mode))

    def entity(self, g, cid, player=1, zone='hand'):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone)
            if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None, player=1):
        eid = self.entity(g, cid, player).id
        g.apply(PlayCard(player, eid, target))
        return eid

    def quote(self, g, entity):
        return quote_unselected_cost(g.state, g.registry, entity).amount

    def choose(self, g, key='continue'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        reader = fixture(self.mode, 'independent-reader')
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(saved, reader).snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe())
            for private in ('rng_state', 'resolution_frame', 'submitted_cost', 'tribe_basis'):
                self.assertNotIn(private, public)

    def test_twelve_complete_rows_twenty_four_primary_faces_and_named_dependencies(self):
        data = load_batch()
        self.assertEqual((len(data['dependencies']), len(data['existing_dependencies']),
            len(data['official_observations'])), (11, 1, 24))
        rows = {x['record']['id']: x['record'] for x in data['dependencies'] + data['existing_dependencies']}
        faces = {(x['card_id'], x['locale']): x['face'] for x in data['official_observations']}
        for observation in data['official_observations']:
            cid = observation['card_id']
            check_face(rows[cid], observation['face'], observation['locale'],
                numeric_normalizations=data['numeric_normalizations'].get(cid))
        for locale in ('zh_CN', 'en_US'):
            for parent, child in ((SPRINGPAW, LYNX), (EGG, FOWL)):
                self.assertIn(rows[child]['dbf_id'], faces[parent, locale]['childIds'])
                self.assertEqual(faces[child, locale]['parentId'], rows[parent]['dbf_id'])
        self.assertEqual(canonical_digest(asdict(fixture().card(LYNX))),
            data['existing_dependencies'][0]['definition_sha256'])
        fowl = fixture().card(FOWL)
        self.assertEqual((fowl.cost, fowl.attack, fowl.health, fowl.metadata.tribes),
            (3, 3, 3, ('undead', 'beast')))
        self.assertFalse(data['formal_pool_complete'])
        self.assertFalse(data['cn_calibrated'])

    def test_ten_native_bodies_pay_the_original_one_mana(self):
        rows = {x['record']['id']: x['record'] for x in load_batch()['dependencies']}
        for cid in LEAVES:
            with self.subTest(card=cid):
                g = self.game((cid,))
                eid = self.play(g, cid, g.state.players[2].hero_id if cid == SHARD else None)
                e = g.state.entities[eid]
                self.assertEqual((e.attack, e.health, g.state.players[1].mana),
                    (rows[cid]['attack'] or 0, rows[cid]['health'], 9))
                self.assertEqual(Keyword.RUSH in e.keywords, cid == SPRINGPAW)

    def test_next_matching_tribe_only_and_zero_mana_play_consumes_the_modifier(self):
        for source, target in ((KINDLING, SHARD), (OSCILLATOR, ZERO_MECH)):
            with self.subTest(card=source):
                g = self.game((source, target, RAVEN), enemy_hand=(target,))
                self.play(g, source)
                self.assertEqual(len(g.state.players[1].cost_modifiers), 1)
                self.assertEqual(self.quote(g, self.entity(g, target)), 0)
                self.assertEqual(self.quote(g, self.entity(g, RAVEN)), 1)
                self.assertEqual(self.quote(g, self.entity(g, target, 2)), g.registry.card(target).cost)
                self.play(g, RAVEN)
                self.assertEqual(len(g.state.players[1].cost_modifiers), 1)
                self.play(g, target, g.state.players[2].hero_id if target == SHARD else None)
                self.assertEqual((g.state.players[1].mana, len(g.state.players[1].cost_modifiers)), (8, 0))

    def test_next_tribe_reads_current_hand_tribes(self):
        for source, change in ((KINDLING, 'plain_elemental'), (OSCILLATOR, 'plain_mech')):
            with self.subTest(card=source):
                g = self.game((source, YETI, P+change))
                self.play(g, source)
                self.assertEqual(self.quote(g, self.entity(g, YETI)), 4)
                self.play(g, P+change)
                self.assertEqual(self.quote(g, self.entity(g, YETI)), 3)
                self.play(g, YETI)
                self.assertEqual((g.state.players[1].mana, len(g.state.players[1].cost_modifiers)), (6, 0))

    def test_next_tribe_survives_source_death_and_unused_turns(self):
        g = self.game((KINDLING, SHARD, KILL), deck=(RAVEN,), enemy_deck=(RAVEN,))
        source = self.play(g, KINDLING)
        self.play(g, KILL, source)
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(self.quote(g, self.entity(g, SHARD)), 0)
        self.play(g, SHARD, g.state.players[2].hero_id)
        self.assertFalse(g.state.players[1].cost_modifiers)
        self.portable(g)

    def test_second_kindling_spends_first_discount_before_installing_its_new_one(self):
        g = self.game((KINDLING, KINDLING, YETI, P+'plain_elemental'))
        self.play(g, KINDLING); self.play(g, KINDLING); self.play(g, P+'plain_elemental')
        self.assertEqual(len(g.state.players[1].cost_modifiers), 1)
        self.assertEqual(self.quote(g, self.entity(g, YETI)), 3)
        self.play(g, YETI)
        self.assertEqual((g.state.players[1].mana, len(g.state.players[1].cost_modifiers)), (6, 0))

    def test_guide_only_changes_next_paid_hero_power(self):
        g = self.game((GUIDE, RAVEN), deck=(RAVEN,), enemy_deck=(RAVEN,))
        self.play(g, GUIDE); self.play(g, RAVEN)
        own = g.state.entities[g.state.players[1].hero_power_id]
        enemy = g.state.entities[g.state.players[2].hero_power_id]
        self.assertEqual((self.quote(g, own), self.quote(g, enemy)), (0, 2))
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id, g.state.players[2].hero_id))
        self.assertEqual(g.state.players[1].mana, 8)
        self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertEqual(self.quote(g, own), 2)
        self.portable(g)

    def test_guide_source_death_and_turn_change_do_not_expire_the_unused_zero(self):
        g = self.game((GUIDE, KILL), deck=(RAVEN,), enemy_deck=(RAVEN,))
        source = self.play(g, GUIDE); self.play(g, KILL, source)
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(self.quote(g, g.state.entities[g.state.players[1].hero_power_id]), 0)
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id, g.state.players[2].hero_id))
        self.assertFalse(g.state.players[1].cost_modifiers)

    def test_illegal_power_target_does_not_spend_guides_zero(self):
        g = self.game((GUIDE,)); self.play(g, GUIDE)
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            g.apply(UseHeroPower(1, g.state.players[1].hero_power_id, 999999))
        self.assertEqual(g.snapshot(), before)

    def test_shadowhoof_uses_temporary_hero_attack_that_survives_source_death(self):
        g = self.game((SLAYER, SLAYER, KILL), deck=(RAVEN,), enemy_deck=(RAVEN,))
        first = self.play(g, SLAYER); self.play(g, SLAYER); self.play(g, KILL, first)
        hero = g.state.entities[g.state.players[1].hero_id]
        self.assertEqual(hero.attack, 2)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].attack, 0)
        g.apply(Attack(1, hero.id, g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].damage, 2)
        g.apply(EndTurn(1)); self.assertEqual(g.state.entities[hero.id].attack, 0)

    def test_peasant_draws_one_extra_only_at_its_controllers_turn_start(self):
        g = self.game(board=(PEASANT,), deck=(RAVEN, YETI, RAVEN), enemy_deck=(RAVEN, YETI))
        g.apply(EndTurn(1))
        self.assertEqual((len(g.state.players[1].hand), len(g.state.players[2].hand)), (0, 1))
        physical = set(g.state.players[1].deck)
        g.apply(EndTurn(2))
        self.assertEqual(len(g.state.players[1].hand), 2)
        self.assertTrue(set(g.state.players[1].hand) <= physical)
        self.portable(g)

    def test_peasant_uses_new_controller_and_silence_stops_future_draws(self):
        g = self.game((TAKE,), board=(PEASANT,), deck=(RAVEN,)*3, enemy_deck=(RAVEN,)*3)
        self.play(g, TAKE, g.state.players[1].board[0])
        g.apply(EndTurn(1))
        self.assertEqual(len(g.state.players[2].hand), 2)
        h = self.game((SILENCE,), board=(PEASANT,), deck=(RAVEN,)*3, enemy_deck=(RAVEN,)*3)
        self.play(h, SILENCE, h.state.players[1].board[0])
        h.apply(EndTurn(1)); h.apply(EndTurn(2))
        self.assertEqual(len(h.state.players[1].hand), 1)

    def test_springpaw_and_generated_lynx_have_native_rush(self):
        g = self.game((SPRINGPAW,), enemy_board=(YETI,))
        source = self.play(g, SPRINGPAW)
        lynx = self.entity(g, LYNX)
        self.assertEqual((lynx.attack, lynx.health, lynx.cost), (1, 1, 1))
        self.assertIn(Keyword.RUSH, lynx.keywords)
        self.assertNotEqual(lynx.id, source)
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            g.apply(Attack(1, source, g.state.players[2].hero_id))
        self.assertEqual(g.snapshot(), before)
        target = g.state.players[2].board[0]
        g.apply(Attack(1, source, target))
        self.play(g, LYNX)
        g.apply(Attack(1, lynx.id, target))
        self.assertEqual(g.state.entities[target].damage, 2)

    def test_shard_targets_only_enemy_characters_and_freezes_hero_or_minion(self):
        for hero in (False, True):
            with self.subTest(hero=hero):
                g = self.game((SHARD,), board=(YETI,), enemy_board=(YETI,))
                source = self.entity(g, SHARD).id
                before = g.snapshot()
                with self.assertRaises(IllegalAction):
                    g.apply(PlayCard(1, source, g.state.players[1].board[0]))
                self.assertEqual(g.snapshot(), before)
                target = g.state.players[2].hero_id if hero else g.state.players[2].board[0]
                self.play(g, SHARD, target)
                self.assertIsNotNone(g.state.entities[target].frozen_until_owner_turn)

    def test_chum_randomly_buffs_one_original_physical_murloc_in_own_hand(self):
        g = self.game((CHUM, MURLOC, MURLOC, RAVEN), enemy_hand=(MURLOC,))
        candidates = [i for i in g.state.players[1].hand if g.state.entities[i].card_id == MURLOC]
        expected = Random(); expected.setstate(g._rng.getstate()); chosen = expected.choice(candidates)
        self.play(g, CHUM)
        for eid in candidates:
            self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].health),
                (2, 2) if eid == chosen else (1, 1))
        self.assertEqual(g._rng.getstate(), expected.getstate())
        self.assertEqual(self.entity(g, MURLOC, 2).attack, 1)

    def test_helboar_enemy_kill_buffs_the_original_owners_hand_not_active_players(self):
        g = self.game((SPRINGPAW, SPRINGPAW, YETI), board=(HELBOAR,),
            enemy_hand=(KILL, RAVEN), active=2)
        candidates = [i for i in g.state.players[1].hand if g.state.entities[i].card_id == SPRINGPAW]
        expected = Random(); expected.setstate(g._rng.getstate()); chosen = expected.choice(candidates)
        self.play(g, KILL, g.state.players[1].board[0], player=2)
        for eid in candidates:
            self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].health),
                (2, 2) if eid == chosen else (1, 1))
        self.assertEqual(g._rng.getstate(), expected.getstate())
        self.assertEqual(self.entity(g, RAVEN, 2).attack, 2)

    def test_both_random_rewards_use_current_tribes_and_exclude_removed_printed_tribes(self):
        for source, change, old, strip in ((CHUM, 'plain_murloc', MURLOC, 'strip_murloc'),
                (HELBOAR, 'plain_beast', RAVEN, 'strip_raven')):
            with self.subTest(card=source):
                hand = (YETI, old, P+change, P+strip) + ((source,) if source == CHUM else (KILL,))
                g = self.game(hand, board=(HELBOAR,) if source == HELBOAR else ())
                self.play(g, P+change); self.play(g, P+strip)
                if source == CHUM:
                    self.play(g, CHUM)
                else:
                    self.play(g, KILL, g.state.players[1].board[0])
                self.assertEqual((self.entity(g, YETI).attack, self.entity(g, YETI).health), (5, 6))
                self.assertEqual(self.entity(g, old).attack, g.registry.card(old).attack)

    def test_empty_matching_hands_consume_no_rng(self):
        for source in (CHUM, HELBOAR):
            with self.subTest(card=source):
                g = self.game((YETI, source) if source == CHUM else (YETI, KILL),
                    board=(HELBOAR,) if source == HELBOAR else ())
                before = g._rng.getstate()
                if source == CHUM:
                    self.play(g, CHUM)
                else:
                    self.play(g, KILL, g.state.players[1].board[0])
                self.assertEqual(g._rng.getstate(), before)
                self.assertEqual(self.entity(g, YETI).attack, 4)

    def test_unknown_current_tribe_fails_and_rolls_back_original_play_or_death(self):
        for source in (CHUM, HELBOAR):
            with self.subTest(card=source):
                g = self.game((UNKNOWN, source) if source == CHUM else (UNKNOWN, KILL),
                    board=(HELBOAR,) if source == HELBOAR else ())
                before = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'Unknown current tribe'):
                    self.play(g, CHUM) if source == CHUM else self.play(g, KILL, g.state.players[1].board[0])
                self.assertEqual(g.snapshot(), before)

    def test_random_reward_wait_restores_same_selected_entity_and_rng(self):
        g = self.game((CHUM, YETI, P+'plain_murloc'), mode='wait')
        self.play(g, P+'plain_murloc'); self.play(g, CHUM)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.entity(g, YETI).attack, 5)
        self.portable(g)
        before = g.snapshot(); rng = g._rng.getstate()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before)
        self.choose(g)
        self.assertEqual((self.entity(g, YETI).attack, g._rng.getstate()), (5, rng))
        self.portable(g)

    def test_native_acquisition_and_death_summon_wait_resume_once(self):
        for source in (SPRINGPAW, EGG):
            with self.subTest(card=source):
                g = self.game((SPRINGPAW,) if source == SPRINGPAW else (KILL,),
                    board=(EGG,) if source == EGG else (), mode='wait')
                if source == SPRINGPAW:
                    self.play(g, SPRINGPAW)
                else:
                    self.play(g, KILL, self.entity(g, EGG, zone='board').id)
                self.assertIsNotNone(g.state.pending_choice)
                self.portable(g); self.choose(g)
                ids = g.state.players[1].hand if source == SPRINGPAW else g.state.players[1].board
                self.assertEqual(sum(g.state.entities[i].card_id == (LYNX if source == SPRINGPAW else FOWL)
                    for i in ids), 1)
                self.portable(g)

    def test_late_reward_failures_roll_back_whole_native_action(self):
        for source in (SPRINGPAW, EGG, CHUM, HELBOAR):
            with self.subTest(card=source):
                board = (source,) if source in (EGG, HELBOAR) else ()
                hand = ((KILL,) if board else (source,)) + ((YETI, P+'plain_beast')
                    if source == HELBOAR else (YETI, P+'plain_murloc') if source == CHUM else ())
                g = self.game(hand, board=board, mode='fail')
                if source in (HELBOAR, CHUM):
                    self.play(g, P+('plain_beast' if source == HELBOAR else 'plain_murloc'))
                before = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'K455 deliberate'):
                    self.play(g, KILL, self.entity(g, source, zone='board').id) if board else self.play(g, source)
                self.assertEqual(g.snapshot(), before)

    def test_foul_egg_death_creates_a_fresh_printed_fowl_for_original_owner(self):
        g = self.game((GROW,), board=(RAVEN, EGG, YETI), enemy_hand=(KILL,))
        egg = self.entity(g, EGG, zone='board'); self.play(g, GROW, egg.id)
        g.apply(EndTurn(1)); self.play(g, KILL, egg.id, player=2)
        fowl = self.entity(g, FOWL, zone='board')
        self.assertNotEqual(fowl.id, egg.id)
        self.assertEqual((fowl.attack, fowl.health, fowl.controller), (3, 3, 1))
        self.assertFalse(fowl.enchantments)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], [RAVEN, FOWL, YETI])
        self.portable(g)

    def test_silence_removes_original_death_rewards(self):
        for source in (HELBOAR, EGG):
            with self.subTest(card=source):
                g = self.game((SILENCE, KILL, RAVEN), board=(source,))
                eid = self.entity(g, source, zone='board').id
                self.play(g, SILENCE, eid); self.play(g, KILL, eid)
                self.assertFalse(g.state.players[1].board)
                self.assertEqual(self.entity(g, RAVEN).attack, 2)

    def test_live_egg_activation_summons_on_its_right_and_resumes_without_another_fowl(self):
        g = self.game((P+'trigger',), board=(RAVEN, EGG, YETI), mode='wait')
        self.play(g, P+'trigger', self.entity(g, EGG, zone='board').id)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],
            [WATCH, RAVEN, EGG, FOWL, YETI])
        self.portable(g); self.choose(g)
        self.assertEqual(sum(g.state.entities[i].card_id == FOWL for i in g.state.players[1].board), 1)
        self.portable(g)

    def test_real_flashback_summons_native_bodies_without_battlecries(self):
        g = self.game((FLASHBACK, RAVEN))
        self.play(g, RAVEN); self.play(g, FLASHBACK)
        made = g.state.players[1].board[1:]
        self.assertEqual(len(made), 2)
        for eid in made:
            e = g.state.entities[eid]
            self.assertIn(e.card_id, LEAVES)
            self.assertEqual(e.attack, g.registry.card(e.card_id).attack + 1)
        self.assertFalse(g.state.battlecry_history)
        self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertFalse(g.state.players[1].hand)
        self.portable(g)

    def test_production_registry_has_no_fake_complete_past_domain(self):
        r = build_registry()
        self.assertNotIn('constructed.past.cards', r.pools)
        self.assertTrue(set(LEAVES) <= set(r.cards))

    def test_retained_lynx_drift_is_rejected_before_installing_new_behaviors(self):
        r = Registry('k455-deliberate-lynx-drift')
        r.register_card(replace(fixture().card(LYNX), attack=2))
        with self.assertRaises(TargetValidationError):
            register_past_one_cost_tribal_cards(r)
        self.assertEqual(set(r.cards), {LYNX})


if __name__ == '__main__':
    unittest.main()
