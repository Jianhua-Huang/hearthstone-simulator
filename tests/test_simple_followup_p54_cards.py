"""Grouped real Osk faces and native resource, target and continuation boundaries."""
from functools import lru_cache
import json
import random
import unittest
from unittest.mock import patch

from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p54_cards import (DRAW, HEAL, REFRESH, DAMAGE, SECRET, TEAM,
    SELF_DRAW, ELUSIVE, NUKE, ARMOR, ATTACK, CONTROL, ROOTS, PARENT, POOL_ID,
    load_batch, register_simple_followup_p54_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Ruleset, Scenario, SelectChoice,
    TargetSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (Buff, ChoiceOption, Damage, InvokeBehavior, RequestChoice,
    ReturnToHand, Silence, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

TEST = 'p54.test.'
YETI = 'CORE_CS2_182'
COUNTER = 'CORE_EX1_287'
UNKNOWN_SECRET = TEST + 'unsupported_secret'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
CONTEXT = GenerationContext('p54-complete-explicit-fixture', 'experimental')
MEMBERS = (COUNTER, 'CORE_EX1_610', 'CORE_CS2_029', YETI)


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata', lambda r: None):
        r = build_registry()
    present = tuple(cid in r.cards for cid in ROOTS)
    if not any(present):
        register_simple_followup_p54_cards(r)
    elif not all(present):
        raise AssertionError('P54 assembly must contain the complete twelve physical faces')
    register_candidate_pool_metadata(r)
    r.validate()
    return r


def registry(mode=None, members=MEMBERS):
    r = batch_registry()
    r.register_card(CardDefinition(TEST + 'power', 'Spell Damage five', CardType.MINION,
        health=20, spell_damage=5, metadata=META))
    r.register_card(CardDefinition(TEST + 'large', 'Large physical target', CardType.MINION,
        attack=3, health=30, metadata=META))
    r.register_card(CardDefinition(TEST + 'dormant', 'Physical dormant occupancy', CardType.MINION,
        attack=1, health=9, dormant_turns=2, metadata=META))
    scripts = dict(
        enhance=lambda c: (Buff(c.state.players[1].hero_id, health=10), Damage(c.state.players[1].hero_id, 7, c.source_id)),
        setup_secret=lambda c: (SetSecret(1, COUNTER),),
        cleanse=lambda c: tuple(Silence(i) for i in c.state.players[1].board),
        reenter=lambda c: (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),
            c.state.entities[c.target_id].controller, cause=SummonCause.capture(c)),),
        fail=lambda c: (_ for _ in ()).throw(ResolutionError('P54 deliberate continuation failure')))
    for name, body in scripts.items():
        r.register_behavior(TEST + name, body)
        r.register_card(CardDefinition(TEST + name, name, CardType.SPELL, on_play=TEST + name, metadata=META))
    r.register_pool_card(PoolCard(UNKNOWN_SECRET, CardType.SPELL, 3,
        CardMetadata(True, (CardClass.MAGE,), None, tribes=()), keywords=(Keyword.SECRET,),
        battlecry=False, deathrattle=False, choose_one=False))
    for cid in members:
        if cid not in r.pool_cards:
            r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID, 'p54-complete-explicit-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode:
        def eligible(c):
            if mode == 'draw':
                return c.event.player_id == 1
            if mode == 'control':
                return c.state.entities[c.event.target_id].card_id == CONTROL
            source = c.state.entities.get(c.event.source_id)
            return source is not None and source.card_id == (TEAM if mode == 'team' else ELUSIVE)

        def watch(c):
            options = [ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Fail',
                (InvokeBehavior(TEST + 'fail', c.source_id, 1),))]
            if mode in ('team', 'elusive', 'control'):
                if mode == 'team':
                    target = c.state.players[1].board[1]
                elif mode == 'control':
                    target = c.state.players[2].board[0]
                else:
                    target = c.event.target_id
                options.append(ChoiceOption('cycle', 'Return and reenter original physical target',
                    (ReturnToHand(target), InvokeBehavior(TEST + 'reenter', c.source_id, 1, target))))
            return (RequestChoice(1, tuple(options), c.source_id),)

        event = 'card_drawn' if mode == 'draw' else 'minion_summoned' if mode == 'control' else 'stats_changed'
        r.register_behavior(TEST + 'watch', watch)
        r.register_trigger_condition(TEST + 'eligible', eligible)
        r.register_card(CardDefinition(TEST + 'watch', 'Original continuation witness', CardType.WEAPON,
            durability=5, metadata=META, limited_triggers=(LimitedTriggerSpec(event, TEST + 'watch',
                condition_id=TEST + 'eligible'),)))
    r.validate()
    return r


@lru_cache(maxsize=None)
def shared_registry(mode, members):
    return registry(mode, members)


class SimpleFollowupP54Tests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), deck=(YETI,) * 20, mode=None,
             members=MEMBERS, cap=None, mana=10, max_mana=10, locked=0, rules=None):
        self.config = (mode, members)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01', hand=hand, board=board,
            deck=deck, mana=mana, max_mana=max_mana, mana_cap=max(10, max_mana), overload_locked=locked,
            hand_cap=cap, weapon_card_id=TEST + 'watch' if mode else None),
            PlayerSetup('HERO_08', board=enemy, deck=(YETI,) * 10, mana=10, max_mana=10)),
            seed=5454, generation_context=CONTEXT), shared_registry(*self.config), rules)

    def first(self, g, cid, zone='hand', player=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone)
                    if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None):
        entity = self.first(g, cid)
        g.apply(PlayCard(1, entity.id, target, position=len(g.state.players[1].board)
                         if entity.kind == CardType.MINION else None))
        return entity.id

    def choose(self, g, key='ok'):
        g.apply(SelectChoice(1, g.state.pending_choice.id, (key,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(*self.config))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(*self.config)).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(
                g.for_player(player).legal_actions()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'pool_id', 'behavior_id', 'source_json', 'payment_state'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_thirteen_complete_original_rows_twenty_six_faces_and_twenty_four_exact_parent_links(self):
        from tools.card_batch import check_face
        data = load_batch()
        rows = {x['record']['id']: x for x in data['cards'] + data['evidence_only']}
        self.assertEqual(len(rows), 13)
        self.assertEqual(len(data['official_observations']), 26)
        faces = {(o['card_id'], o['locale']): o['face'] for o in data['official_observations']}
        for o in data['official_observations']:
            check_face(rows[o['card_id']]['record'], o['face'], o['locale'])
            self.assertEqual(o['response_sha256'], o['observation']['sha256'])
        self.assertEqual(len(data['exact_parent_child_links']), 24)
        for link in data['exact_parent_child_links']:
            self.assertEqual(rows[link['child']]['record']['dbf_id'], link['dbf_id'])
            self.assertIn(link['dbf_id'], faces[link['parent'], link['locale']]['childIds'])
        self.assertFalse(data['parent_implemented'] or data['formal_pool_complete'] or data['cn_calibrated'])
        self.assertFalse(data['numeric_normalizations'] or data['collectible_candidate_roots'])

    def test_twelve_independent_noncollectible_battlecry_faces_preserve_all_old_definitions_and_default(self):
        before, after = build_registry(), batch_registry()
        self.assertEqual(set(after.cards) - set(before.cards), set(ROOTS) - set(before.cards))
        for cid, card in before.cards.items():
            self.assertEqual(after.card(cid), card)
        for cid, card in before.pool_cards.items():
            self.assertEqual(after.pool_cards[cid], card)
        self.assertEqual(dict(before.pools), dict(after.pools))
        self.assertEqual(dict(before.generation_families), dict(after.generation_families))
        for row in load_batch()['cards']:
            raw = row['record']
            card = after.card(raw['id'])
            self.assertEqual((card.cost, card.attack, card.health, card.metadata), (6, 6, 6, metadata_from_record(raw)))
            self.assertTrue(card.battlecry)
            self.assertFalse(card.metadata.collectible or card.keywords or card.activated_abilities or card.hand_derivatives)
            self.assertEqual(canonical_digest(raw), row['record_sha256'])
        self.assertEqual(PARENT in before.cards, PARENT in after.cards)
        from hs_sim.engine.representative import build_registry as default
        self.assertEqual(default().fingerprint(), DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_all_twelve_actual_entry_points_pay_six_once_and_ordinary_summon_does_not_run_battlecry(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g = self.game((cid,))
                target = g.state.players[2].hero_id if cid == DAMAGE else None
                source = self.play(g, cid, target)
                self.assertEqual(g.state.entities[source].zone, Zone.BOARD)
                self.assertEqual((len(g.state.play_history), g.state.play_history[0].cost), (1, 6))
                self.assertEqual(g.state.players[1].mana, 10 if cid == REFRESH else 4)
        g = self.game(board=(SELF_DRAW, ELUSIVE, ARMOR, ATTACK, DRAW, HEAL))
        for cid in (SELF_DRAW, ELUSIVE, ARMOR, ATTACK, DRAW, HEAL):
            entity = self.first(g, cid, 'board')
            self.assertEqual((entity.attack, entity.health, entity.keywords), (6, 6, set()))
        self.assertFalse(g.state.draw_history or g.state.healing_history)

    def test_draw_full_uses_actual_hand_capacity_and_original_empty_deck_fatigue(self):
        for cap in (2, 5, 12):
            with self.subTest(cap=cap):
                g = self.game((DRAW,), cap=cap)
                self.play(g, DRAW)
                self.assertEqual(len(g.state.players[1].hand), cap)
                self.assertEqual(len(g.state.draw_history), cap)
        g = self.game((DRAW,), cap=2, deck=())
        self.play(g, DRAW)
        self.assertEqual(g.state.players[1].fatigue, 2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 27)

    def test_draw_original_queue_wait_restore_replay_and_failed_resume_do_not_duplicate_draws(self):
        g = self.game((DRAW,), cap=3, mode='draw')
        self.play(g, DRAW)
        other, saved = self.portable(g), g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual((len(g.state.players[1].hand), len(g.state.draw_history)), (3, 3))

    def test_full_heal_uses_enhanced_current_max_health_and_records_overheal(self):
        g = self.game((TEST + 'enhance', HEAL))
        self.play(g, TEST + 'enhance')
        self.play(g, HEAL)
        hero = g.state.entities[g.state.players[1].hero_id]
        self.assertEqual((hero.health, hero.max_health), (40, 40))
        result = g.state.healing_history[-1].health_result
        self.assertEqual((result.base_amount, result.healed, result.overheal), (40, 7, 33))

    def test_refresh_uses_current_crystals_retains_overload_lock_and_original_payment(self):
        for maximum, locked in ((8, 0), (10, 2), (14, 3)):
            with self.subTest(maximum=maximum, locked=locked):
                g = self.game((REFRESH,), mana=maximum - locked, max_mana=maximum, locked=locked)
                self.play(g, REFRESH)
                player = g.state.players[1]
                self.assertEqual((player.mana, player.max_mana, player.overload_locked), (maximum - locked, maximum, locked))
                self.assertEqual(g.state.play_history[0].cost, 6)

    def test_damage_faces_have_native_available_targets_other_minion_exclusion_and_no_spell_bonus(self):
        for cid, target_kind, amount in ((DAMAGE, 'hero', 5), (DAMAGE, 'minion', 5), (NUKE, 'minion', 20)):
            with self.subTest(cid=cid, target_kind=target_kind):
                g = self.game((cid,), board=(TEST + 'power',), enemy=(TEST + 'large',))
                target = g.state.players[2].hero_id if target_kind == 'hero' else self.first(g, TEST + 'large', 'board', 2).id
                self.play(g, cid, target)
                result = g.state.damage_history[-1].health_result
                self.assertEqual((result.base_amount, result.spell_bonus, result.damage_kind), (amount, 0, 'minion_ability'))
                self.assertEqual(g.state.entities[target].health, 30 - amount)
        g = self.game((NUKE,))
        saved = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(g, NUKE, g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(), saved)
        self.play(g, NUKE)
        self.assertFalse(g.state.damage_history)
        self.assertTrue(g.registry.card(NUKE).targeting.exclude_source)

    def test_secret_specifies_mage_even_for_warrior_and_full_or_duplicate_zone_uses_native_cast(self):
        g = self.game((SECRET,))
        self.play(g, SECRET)
        secret, = g.state.players[1].secrets
        self.assertEqual(g.state.entities[secret].card_id, COUNTER)
        cast, = g.state.cast_history
        self.assertEqual((cast.card_id, cast.origin, cast.player_id), (COUNTER, 'effect', 1))
        self.assertEqual(g.state.players[1].mana, 4)
        self.assertNotIn(COUNTER, json.dumps(g.for_player(2).observe()))
        self.portable(g)
        g = self.game((TEST + 'setup_secret', SECRET), rules=Ruleset(max_secret_zone=1))
        self.play(g, TEST + 'setup_secret')
        self.play(g, SECRET)
        self.assertEqual(len(g.state.players[1].secrets), 1)
        self.assertEqual(g.state.players[1].mana, 4)

    def test_secret_complete_unknown_eligible_mage_secret_rejects_before_rng_and_rolls_back_play(self):
        g = self.game((SECRET,), members=(COUNTER, UNKNOWN_SECRET))
        self.assertNotIn(UNKNOWN_SECRET, g.registry.cards)
        saved, calls = g.snapshot(), []
        original = random.Random.randrange
        def spy(rng, *args, **kwargs):
            calls.append(args)
            return original(rng, *args, **kwargs)
        with patch.object(random.Random, 'randrange', autospec=True, side_effect=spy):
            with self.assertRaises(ResolutionError):
                self.play(g, SECRET)
        self.assertFalse(calls)
        self.assertEqual(g.snapshot(), saved)

    def test_team_buff_captures_only_other_active_friends_and_old_second_residence_survives_reentry(self):
        g = self.game((TEAM,), board=(YETI, YETI, TEST + 'dormant'), enemy=(YETI,), mode='team')
        second = g.state.entities[g.state.players[1].board[1]]
        source = self.play(g, TEAM)
        other, saved = self.portable(g), g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game, 'cycle')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertNotEqual(g.state.entities[second.id].board_presence_id, second.board_presence_id)
        self.assertEqual((g.state.entities[second.id].attack, g.state.entities[second.id].health), (4, 5))
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (6, 6))
        self.assertEqual(self.first(g, TEST + 'dormant', 'board').health, 9)
        self.assertEqual(self.first(g, YETI, 'board', 2).health, 5)

    def test_self_buff_faces_keep_exact_stats_draw_armor_keyword_and_temporary_hero_attack(self):
        for cid, stats in ((SELF_DRAW, (7, 8)), (ELUSIVE, (6, 9)), (ARMOR, (6, 11)), (ATTACK, (11, 6))):
            with self.subTest(cid=cid):
                g = self.game((cid, TEST + 'cleanse'))
                source = self.play(g, cid)
                self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), stats)
                hero = g.state.players[1].hero_id
                self.assertEqual(g.state.entities[hero].armor, 5 if cid == ARMOR else 0)
                self.assertEqual(g.state.entities[hero].attack, 5 if cid == ATTACK else 0)
                self.assertEqual(len(g.state.draw_history), 1 if cid == SELF_DRAW else 0)
                self.assertEqual(Keyword.ELUSIVE in g.state.entities[source].keywords, cid == ELUSIVE)
                self.play(g, TEST + 'cleanse')
                self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (6, 6))
                self.assertNotIn(Keyword.ELUSIVE, g.state.entities[source].keywords)
                g.apply(EndTurn(1))
                self.assertEqual(g.state.entities[hero].attack, 0)

    def test_elusive_grant_original_self_reference_does_not_attach_to_reentered_same_id(self):
        g = self.game((ELUSIVE,), mode='elusive')
        source = self.play(g, ELUSIVE)
        other = self.portable(g)
        for game in (g, other):
            self.choose(game, 'cycle')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (6, 6))
        self.assertNotIn(Keyword.ELUSIVE, g.state.entities[source].keywords)

    def test_control_native_success_full_friendly_capacity_and_original_paid_target_reentry(self):
        g = self.game((CONTROL,), enemy=(YETI,))
        target = self.first(g, YETI, 'board', 2).id
        self.play(g, CONTROL, target)
        self.assertEqual(g.state.entities[target].controller, 1)
        g = self.game((CONTROL,), board=(YETI,) * 6, enemy=(YETI,))
        target = self.first(g, YETI, 'board', 2).id
        self.play(g, CONTROL, target)
        self.assertEqual((g.state.entities[target].controller, g.state.entities[target].zone), (2, Zone.BOARD))
        self.assertFalse(g.state.death_history)
        g = self.game((CONTROL,), enemy=(YETI,), mode='control')
        target = self.first(g, YETI, 'board', 2)
        self.play(g, CONTROL, target.id)
        other = self.portable(g)
        for game in (g, other):
            self.choose(game, 'cycle')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertNotEqual(g.state.entities[target.id].board_presence_id, target.board_presence_id)
        self.assertEqual(g.state.entities[target.id].controller, 2)


if __name__ == '__main__':
    unittest.main()
