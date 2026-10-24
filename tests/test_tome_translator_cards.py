"""Real decoded faces and the two public capabilities they require."""
from dataclasses import asdict
from functools import lru_cache
import json
import unittest

from hs_sim.cards import tome_translator_cards as cards
from hs_sim.cards.constructed import build_registry
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TargetSpec, Zone)
from hs_sim.engine.adjacent_stat_gains import GainRandomAdjacentStats
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChoiceOption, Damage, InvokeBehavior, RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference, DamageKind, LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, resolve_candidates
from hs_sim.engine.random_split_damage import NON_SPELL_PROFILE, RandomSplitDamage, SplitDamageScope, split_candidates
from hs_sim.engine.registry import RuleContext, UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face, sha, registration_prefix

SUMMON, DISCOUNT, SPLIT, GAIN = cards.FORMS
P = 'k451.'
N, DORMANT, HIT, GAIN_SPELL, REENTER, RETURN, WATCH, FAIL = (
    P + name for name in ('minion', 'dormant', 'hit', 'gain', 'reenter', 'return', 'watch', 'fail'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
CTX = GenerationContext('k451-complete-two-cost-deathrattle-domain', 'experimental')
COIN, YETI, FLAMES, RUST = 'GAME_005', 'CS2_182', 'CORE_CS2_032', 'CORE_SW_072'


def rehash(snapshot):
    snapshot['events_hash'] = canonical_hash(snapshot['events'])
    snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return snapshot


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    registry = build_registry()
    registry._version += '.k451.' + mode
    registry.register_card(CardDefinition(N, N, CardType.MINION, attack=1, health=20, metadata=META))
    registry.register_card(CardDefinition(DORMANT, DORMANT, CardType.MINION, attack=9, health=20,
        dormant_turns=2, metadata=META))

    def reenter(c):
        entity = c.state.entities[c.target_id]
        return (SummonStoredCard(CardReference.capture(entity), c.player_id),)

    registry.register_behavior(REENTER, reenter)
    operations = {
        HIT: lambda c: (Damage(c.target_id, 2, c.source_id),),
        GAIN_SPELL: lambda c: (GainRandomAdjacentStats(
            BoardPresenceReference.capture(c.state, c.target_id), c.target_id),),
        RETURN: lambda c: (ReturnToHand(c.target_id),
            InvokeBehavior(REENTER, c.source_id, c.player_id, c.target_id)),
    }
    for cid, body in operations.items():
        registry.register_behavior(cid, body)
        registry.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)), metadata=META))

    def fail(c):
        raise ResolutionError('K451 deliberate failure after native selection')

    registry.register_behavior(FAIL, fail)
    if mode.endswith('_wait') or mode.endswith('_fail'):
        event = ('random_choice' if mode.startswith('gain') else
                 'damage_dealt' if mode.startswith('split') else 'minion_summoned')

        def wait(c):
            options = [ChoiceOption('go', 'Continue', ())]
            if event == 'random_choice':
                options += [ChoiceOption('wound', 'Damage the chosen donor',
                    (Damage(c.event.target_id, 2, c.source_id),)),
                    ChoiceOption('reenter', 'Return and summon the original recipient',
                    (ReturnToHand(c.event.source_id),
                     InvokeBehavior(REENTER, c.source_id, c.player_id, c.event.source_id)))]
            return (RequestChoice(c.player_id, tuple(options), c.source_id),)

        registry.register_behavior(WATCH, wait)
        condition = P + 'actual_generated' if event == 'minion_summoned' else 'always'
        if condition != 'always':
            registry.register_trigger_condition(condition, lambda c: c.event.target_id is not None and
                c.state.entities[c.event.target_id].card_id in cards.load_batch()['candidate_domain_ids'])
        registry.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, attack=1, health=20,
            limited_triggers=(LimitedTriggerSpec(event, FAIL if mode.endswith('_fail') else WATCH,
                condition_id=condition, uses=1),), metadata=META))
    members = list(cards.load_batch()['candidate_domain_ids'])
    if mode == 'unknown':
        missing = CardDefinition(P + 'unknown', 'Unknown eligible original', CardType.MINION, cost=2,
            deathrattle=P + 'absent', metadata=CardMetadata(True, (CardClass.NEUTRAL,), None))
        registry.register_pool_card(PoolCard.from_definition(missing))
        members.append(missing.id)
    registry.register_pool(PoolDefinition(cards.POOL_ID, 'k451-full-reviewed-candidate-domain',
        CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    registry.validate()
    return registry


class TomeTranslatorTests(unittest.TestCase):
    def game(self, hand=(), board=(), *, enemy=(), mode='normal', mana=30):
        if mode.endswith('_wait') or mode.endswith('_fail'):
            board = (WATCH,) + board
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board,
            deck=(COIN,) * 16, mana=mana, max_mana=mana, mana_cap=40, hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', board=enemy, deck=(COIN,) * 16)), seed=6,
            generation_context=CTX), fixture(mode))

    def ids(self, game, cid, player=1, zone='board'):
        return [i for i in getattr(game.state.players[player], zone) if game.state.entities[i].card_id == cid]

    def play(self, game, cid, target=None):
        entity_id = self.ids(game, cid, zone='hand')[0]
        game.apply(PlayCard(1, entity_id, target))
        return entity_id

    def choose(self, game, option='go'):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def portable(self, game, mode='normal'):
        snapshot = json.loads(json.dumps(game.snapshot()))
        reader = fixture(mode, 'reader')
        self.assertIsNot(reader, game.registry)
        restored = Game.from_snapshot(snapshot, reader)
        self.assertEqual(restored.snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), reader).snapshot(), snapshot)
        for player in (1, 2):
            visible = json.dumps(game.for_player(player).observe()) + json.dumps(game.player_events(player))
            for key in ('resolution_frame', 'rng_state', 'GainRandomAdjacentStats', 'SplitPacketProof'):
                self.assertNotIn(key, visible)
        return restored

    def test_a_thirty_one_full_rows_ten_faces_four_bodies_and_unregistered_root(self):
        data = cards.load_batch()
        rows = {row['record']['id']: row for key in ('cards', 'existing_dependencies', 'evidence_only')
            for row in data[key]}
        self.assertEqual((len(rows), len(data['official_observations'])), (31, 10))
        for observation in data['official_observations']:
            self.assertEqual(sha(observation['response_file']), observation['response_sha256'])
            check_face(rows[observation['card_id']]['record'], observation['face'], observation['locale'],
                data['display_normalizations'].get(observation['card_id']))
        registry = fixture()
        for row in data['existing_dependencies']:
            self.assertEqual(canonical_digest(asdict(registry.card(row['record']['id']))), row['definition_sha256'])
        for cid in cards.FORMS:
            card = registry.card(cid)
            self.assertEqual((card.cost, card.attack, card.health, card.metadata.collectible), (4, 5, 4, False))
        from hs_sim.cards.tome_translator_root_card import register_tome_translator_root_card
        original_boundary = registration_prefix(build_registry,
            'hs_sim.cards.tome_translator_root_card.register_tome_translator_root_card',
            register_tome_translator_root_card)
        with self.assertRaises(UnsupportedDefinitionError):
            original_boundary.card('BE_327')
        self.assertFalse(data['limitations']['root_registered'])

    def test_b_exact_complete_twenty_four_member_native_summon_domain(self):
        game = self.game()
        rows = resolve_candidates(game.registry, CTX, cards.POOL_ID, cards.DEATHRATTLES,
            current_class=game.state.players[1].hero_class, source_card_id=SUMMON, player_id=1)
        self.assertEqual({row.card_id for row in rows}, set(cards.load_batch()['candidate_domain_ids']))
        self.assertEqual(len(rows), 24)

    def test_c_two_physical_summons_without_their_battlecries(self):
        game = self.game((SUMMON,))
        source = self.play(game, SUMMON)
        children = [game.state.entities[i] for i in game.state.players[1].board if i != source]
        self.assertEqual(len(children), 2)
        for child in children:
            self.assertIn(child.card_id, cards.load_batch()['candidate_domain_ids'])
        self.assertEqual(len(game.state.battlecry_history), 1)
        self.portable(game)

    def test_d_last_available_slot_is_used_without_dropping_the_host(self):
        game = self.game((SUMMON,), board=(N,) * 5)
        source = self.play(game, SUMMON)
        self.assertEqual(len(game.state.players[1].board), 7)
        self.assertEqual(len([i for i in game.state.players[1].board if i != source and
            game.state.entities[i].card_id != N]), 1)

    def test_e_first_actual_summon_wait_restores_second_original_request(self):
        game = self.game((SUMMON,), mode='summon_wait')
        source = self.play(game, SUMMON)
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(len(game.state.players[1].board), 3)
        restored = self.portable(game, 'summon_wait')
        self.choose(game)
        self.choose(restored)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual(len(game.state.players[1].board), 4)
        self.assertIn(source, game.state.players[1].board)
        self.portable(game, 'summon_wait')

    def test_f_unknown_eligible_native_dependency_is_not_pruned(self):
        game = self.game((SUMMON,), mode='unknown')
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, SUMMON)
        self.assertEqual(game.snapshot(), before)

    def test_g_next_spell_discount_is_not_spent_by_intervening_minion(self):
        game = self.game((DISCOUNT, RUST, FLAMES, FLAMES))
        self.play(game, DISCOUNT)
        self.play(game, RUST)
        before = game.state.players[1].mana
        self.play(game, FLAMES)
        self.assertEqual(before - game.state.players[1].mana, 3)
        before = game.state.players[1].mana
        self.play(game, FLAMES)
        self.assertEqual(before - game.state.players[1].mana, 7)
        self.portable(game)

    def test_h_unused_discount_expires_at_original_turn_end(self):
        game = self.game((DISCOUNT, FLAMES))
        self.play(game, DISCOUNT)
        self.portable(game)
        game.apply(EndTurn(1))
        game.apply(EndTurn(2))
        before = game.state.players[1].mana
        self.play(game, FLAMES)
        self.assertEqual(before - game.state.players[1].mana, 7)

    def test_i_zero_cost_next_spell_still_consumes_the_single_use(self):
        game = self.game((DISCOUNT, COIN, FLAMES))
        self.play(game, DISCOUNT)
        self.play(game, COIN)
        before = game.state.players[1].mana
        self.play(game, FLAMES)
        self.assertEqual(before - game.state.players[1].mana, 7)

    def test_j_six_nonspell_packets_reach_both_sides_but_no_hero_or_original_source(self):
        game = self.game((SPLIT,), board=(N,), enemy=(N,))
        source = self.play(game, SPLIT)
        root = game.state.split_damage_history[-1]
        self.assertEqual(len(root.packets), 6)
        self.assertEqual(root.request.scope.exclude_source, BoardPresenceReference.capture(game.state, source))
        self.assertEqual(game.state.entities[source].health, 4)
        self.assertEqual(sum(20 - game.state.entities[i].health for player in (1, 2)
            for i in self.ids(game, N, player)), 6)
        self.assertTrue(all(game.state.entities[game.state.players[p].hero_id].health == 30 for p in (1, 2)))
        for packet in root.packets:
            offered = {candidate.allocation.entity_id for candidate in packet.selection.candidates}
            self.assertEqual(offered, set(self.ids(game, N) + self.ids(game, N, 2)))
        self.portable(game)

    def test_k_only_original_source_produces_empty_pool_without_rng(self):
        game = self.game((SPLIT,))
        before = game.snapshot()['rng_state']
        source = self.play(game, SPLIT)
        root = game.state.split_damage_history[-1]
        self.assertEqual(root.packets, ())
        self.assertTrue(root.completed)
        self.assertEqual(game.state.entities[source].health, 4)
        self.assertEqual(game.snapshot()['rng_state'], before)

    def test_l_split_packet_wait_preserves_excluded_original_residence(self):
        game = self.game((SPLIT,), enemy=(N,), mode='split_wait')
        source = self.play(game, SPLIT)
        self.assertIsNotNone(game.state.pending_choice)
        restored = self.portable(game, 'split_wait')
        self.choose(game)
        self.choose(restored)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual(game.state.entities[source].health, 4)
        self.assertEqual(len(game.state.split_damage_history[-1].packets), 6)
        self.portable(game, 'split_wait')

    def test_m_split_rehashed_wrong_source_reference_is_rejected(self):
        game = self.game((SPLIT,), enemy=(N,))
        self.play(game, SPLIT)
        saved = game.snapshot()
        saved['state']['split_damage_history'][-1]['request']['scope']['exclude_source']['entity_id'] = self.ids(game, N, 2)[0]
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(rehash(saved), fixture('normal', 'reader'))

    def test_n_split_late_failure_reverts_health_rng_and_whole_play(self):
        game = self.game((SPLIT,), enemy=(N,), mode='split_fail')
        before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K451 deliberate failure'):
            self.play(game, SPLIT)
        self.assertEqual(game.snapshot(), before)

    def test_o_split_exclusion_does_not_bind_the_same_id_after_real_reentry(self):
        game = self.game((RETURN,), board=(N, SPLIT))
        source = self.ids(game, SPLIT)[0]
        old = BoardPresenceReference.capture(game.state, source)
        self.play(game, RETURN, source)
        new = BoardPresenceReference.capture(game.state, source)
        self.assertNotEqual(old, new)
        scope = SplitDamageScope('any', (CardType.MINION,), old)
        self.assertIn(source, [row.allocation.entity_id for row in split_candidates(game.state, game.registry, 1, scope)])
        current = SplitDamageScope('any', (CardType.MINION,), new)
        self.assertNotIn(source, [row.allocation.entity_id for row in split_candidates(game.state, game.registry, 1, current)])
        self.portable(game)

    def test_p_gain_uses_one_real_neighbor_current_attack_and_remaining_health(self):
        game = self.game((HIT, GAIN), board=(YETI,))
        donor = self.ids(game, YETI)[0]
        self.play(game, HIT, donor)
        source = self.play(game, GAIN)
        entity = game.state.entities[source]
        self.assertEqual((entity.attack, entity.max_health), (9, 7))
        self.assertEqual(game.state.entities[donor].health, 3)
        self.portable(game)

    def test_q_dormant_adjacent_slot_does_not_bridge_to_a_far_minion(self):
        game = self.game((GAIN_SPELL,), board=(N, DORMANT, N))
        source = self.ids(game, N)[0]
        before = game.snapshot()['rng_state']
        self.play(game, GAIN_SPELL, source)
        self.assertEqual((game.state.entities[source].attack, game.state.entities[source].max_health), (1, 20))
        self.assertEqual(game.snapshot()['rng_state'], before)

    def test_r_adjacent_pool_contains_only_two_physical_friendly_neighbors(self):
        game = self.game((GAIN_SPELL,), board=(YETI, N, YETI), enemy=(YETI,))
        source = self.ids(game, N)[0]
        self.play(game, GAIN_SPELL, source)
        event = next(event for event in reversed(game.events) if event.kind == 'random_choice')
        self.assertEqual(set(dict(event.data)['candidates']), set(self.ids(game, YETI)))
        self.assertEqual((game.state.entities[source].attack, game.state.entities[source].max_health), (5, 25))

    def test_s_gain_frozen_donor_numbers_survive_choice_and_later_damage(self):
        game = self.game((GAIN,), board=(YETI,), mode='gain_wait')
        source = self.play(game, GAIN)
        self.assertIsNotNone(game.state.pending_choice)
        restored = self.portable(game, 'gain_wait')
        self.choose(game, 'wound')
        self.choose(restored, 'wound')
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual((game.state.entities[source].attack, game.state.entities[source].max_health), (9, 9))
        self.assertEqual(game.state.entities[self.ids(game, YETI)[0]].health, 3)
        self.portable(game, 'gain_wait')

    def test_t_old_gain_does_not_attach_to_recipient_reentry(self):
        game = self.game((GAIN,), board=(YETI,), mode='gain_wait')
        source = self.play(game, GAIN)
        old = BoardPresenceReference.capture(game.state, source)
        self.portable(game, 'gain_wait')
        self.choose(game, 'reenter')
        self.assertNotEqual(BoardPresenceReference.capture(game.state, source), old)
        self.assertEqual((game.state.entities[source].attack, game.state.entities[source].max_health), (5, 4))
        self.portable(game, 'gain_wait')

    def test_u_gain_late_failure_rolls_back_rng_and_original_play(self):
        game = self.game((GAIN,), board=(YETI,), mode='gain_fail')
        before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K451 deliberate failure'):
            self.play(game, GAIN)
        self.assertEqual(game.snapshot(), before)

    def test_v_nonboard_source_split_still_quotes_its_independent_damage(self):
        game = self.game((SPLIT,))
        source = self.ids(game, SPLIT, zone='hand')[0]
        quoted = game.registry.behavior(cards.PREFIX + SPLIT)(RuleContext(game.state, source, 1))
        self.assertEqual(len(quoted), 1)
        self.assertIsNone(quoted[0].scope.exclude_source)
        self.assertEqual(quoted[0].amount, 6)

    def test_w_structurally_invalid_exclusions_and_gains_are_rejected(self):
        game = self.game(board=(N, N))
        one, two = self.ids(game, N)
        reference = BoardPresenceReference.capture(game.state, one)
        with self.assertRaises(ValueError):
            SplitDamageScope('enemy', (CardType.MINION,), reference)
        with self.assertRaises(ValueError):
            RandomSplitDamage(1, None, two, 6, SplitDamageScope('any', (CardType.MINION,), reference),
                profile=NON_SPELL_PROFILE, kind=DamageKind.MINION_ABILITY)
        with self.assertRaises(ValueError):
            GainRandomAdjacentStats(reference, two)

    def test_x_previous_snapshot_schema_is_explicitly_rejected(self):
        game = self.game()
        saved = game.snapshot()
        saved['schema_version'] -= 1
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, fixture('normal', 'reader'))
