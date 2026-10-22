"""Actual Larva sources, complete finite class domain and native Combo effects."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards import class_larva_cards as cards
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (
    Attack, CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Registry, Scenario, SelectChoice,
    TargetSpec, TriggerSpec, Zone,
)
from hs_sim.engine.effects import (
    Buff, ChangeControl, ChoiceOption, Damage, Destroy, InvokeBehavior, RequestChoice, Silence,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import DamageKind, PLAYABLE_CARD_CLASSES
from hs_sim.engine.pools import PoolMember, sample_candidates
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError, canonical_digest

P = 'k414.'
NOP, HURT, KILL, TAKE, SILENCE = (P + x for x in ('nop', 'hurt', 'kill', 'take', 'silence'))
FILLER = 'CORE_CS2_182'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(None)
def full_registry():
    registry = build_registry()
    registry.freeze()
    return registry


def uninstalled_registry(mode=None):
    source = full_registry()
    registry = Registry('k414-native-larvae')
    for cid in cards.EXISTING + (FILLER, 'CS2_052'):
        definition = source.card(cid)
        registry.register_card(definition)
        for trigger in definition.triggers:
            # Compiled native utility bodies retain their registered child
            # instructions; copying only the outer callback is incomplete.
            for key in source._behaviors:
                if key == trigger.behavior_id or key.startswith(trigger.behavior_id + '.'):
                    registry.register_behavior(key, source.behavior(key))
    registry.register_behavior(NOP, lambda c: ())
    registry.register_card(CardDefinition(NOP, NOP, CardType.SPELL, on_play=NOP, metadata=META))

    def fail(c):
        raise ResolutionError('Deliberate Larva delivery failure')

    def wait(c):
        if (c.event.player_id != c.player_id or c.event.target_id is None or
                c.state.entities[c.event.target_id].card_id not in cards.LARVAE):
            return ()
        if mode == 'fail':
            return (InvokeBehavior(P + 'failure', c.source_id, c.player_id),)
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P + 'failure', c.source_id, c.player_id),))),
            c.source_id),)

    registry.register_behavior(P + 'failure', fail)
    registry.register_behavior(P + 'wait', wait)
    for cls in PLAYABLE_CARD_CLASSES:
        registry.register_card(CardDefinition(P + 'hero.' + cls.value, cls.value, CardType.HERO,
            health=30, metadata=CardMetadata(False, (cls,), None),
            triggers=(TriggerSpec('card_added_to_hand', P + 'wait'),) if mode else ()))
    bodies = {
        HURT: lambda c: (Damage(c.target_id, 2, c.source_id, DamageKind.EFFECT),),
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        TAKE: lambda c: (ChangeControl(c.target_id, 2),),
        SILENCE: lambda c: (Silence(c.target_id),),
    }
    for cid, body in bodies.items():
        registry.register_behavior(cid, body)
        registry.register_card(CardDefinition(cid, cid, CardType.SPELL,
            on_play=cid, targeting=TargetSpec(), metadata=META))
    return registry


@lru_cache(None)
def fixture_registry(role='writer', mode=None, missing=None):
    if role not in ('writer', 'reader'):
        raise AssertionError('Independent fixture role required')
    registry = uninstalled_registry(mode)
    cards.register_class_larva_cards(registry)
    if missing is not None:
        registry._cards.pop(missing)
    registry.validate()
    registry.freeze()
    return registry


class ClassLarvaTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), hero=CardClass.ROGUE, seed=414,
             mode=None, missing=None, full=False):
        registry = full_registry() if full else fixture_registry(mode=mode, missing=missing)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_03' if full else P + 'hero.' + hero.value, hand=hand, board=board,
                deck=(FILLER,) * 6, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_08' if full else P + 'hero.mage', board=enemy,
                deck=(FILLER,) * 6, mana=30, max_mana=30, mana_cap=30)), seed=seed), registry)

    def play(self, game, cid, target=None):
        player = game.state.active_player
        eid = next(i for i in game.state.players[player].hand if game.state.entities[i].card_id == cid)
        position = len(game.state.players[player].board) if game.state.entities[eid].kind == CardType.MINION else None
        game.apply(PlayCard(player, eid, target, position))
        return eid

    def hand(self, game, player=1):
        return tuple(game.state.entities[i].card_id for i in game.state.players[player].hand)

    def board(self, game, player=1):
        return tuple(game.state.entities[i].card_id for i in game.state.players[player].board)

    def hero(self, game, player=1):
        return game.state.entities[game.state.players[player].hero_id]

    def expected(self, game, count, player=1):
        rng = Random()
        rng.setstate(game._rng.getstate())
        current = game.state.players[player].hero_class
        candidates = tuple(PoolMember(cid) for cid in sorted(cards.LARVAE)
            if game.registry.pool_card(cid).metadata.classes != (current,))
        selected = tuple(sample_candidates(rng, candidates, 1, replacement=True)[0] for _ in range(count))
        return selected, rng.getstate()

    def choose(self, game, option='ok'):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def portable(self, game, mode=None):
        saved = json.loads(json.dumps(game.snapshot()))
        reader = fixture_registry('reader', mode)
        self.assertIsNot(reader, game.registry)
        restored = Game.from_snapshot(saved, reader)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(game), reader).snapshot(), saved)
        visible = json.dumps(game.for_player(2).observe()) + json.dumps(game.for_player(2).legal_actions())
        for field in ('rng_state', 'behavior_id', 'combo_history', 'resolution_frame'):
            self.assertNotIn('"' + field + '"', visible)
        return restored

    def test_a_complete_records_faces_class_family_and_neutral_placeholder(self):
        data = cards.load_batch()
        self.assertEqual(tuple(len(data[k]) for k in ('cards', 'dependencies', 'existing_dependencies', 'evidence_only')),
            (3, 12, 6, 1))
        self.assertEqual(len(data['official_observations']), 44)
        rows = {item['record']['id']: item['record'] for key in
            ('cards', 'dependencies', 'existing_dependencies', 'evidence_only') for item in data[key]}
        token_dbfs = {rows[cid]['dbf_id'] for cid in cards.LARVAE}
        for face in data['official_observations']:
            raw = rows[face['card_id']]
            self.assertEqual(face['face']['id'], raw['dbf_id'])
            if face['card_id'] in cards.ROOTS:
                expected = token_dbfs | ({rows['BE_720t12']['dbf_id']} if face['card_id'] == 'BE_720' else set())
                self.assertEqual(set(face['face']['childIds']), expected)
        self.assertEqual(metadata_from_record(rows['BE_720t12']).classes, (CardClass.NEUTRAL,))
        self.assertNotIn('BE_720t12', full_registry().cards)
        for cid in cards.LARVAE:
            definition = full_registry().card(cid)
            self.assertEqual((definition.cost, definition.attack, definition.health), (1, 2, 1))
            self.assertIn(Keyword.COMBO, definition.keywords)
            self.assertIsNone(definition.battlecry)
        self.assertEqual(full_registry().card('BE_724').spell_school.value, 'shadow')

    def test_b_actual_constructed_battlecry_and_spell_counts_payment_and_rng(self):
        for cid, count, price in (('BE_720', 1, 1), ('BE_724', 3, 2)):
            game = self.game((cid,), full=True)
            selected, rng = self.expected(game, count)
            source = self.play(game, cid)
            self.assertEqual(self.hand(game), selected)
            self.assertEqual(game._rng.getstate(), rng)
            self.assertEqual(game.state.players[1].mana, 30-price)
            self.assertEqual(len(game.state.play_history), 1)
            self.assertEqual(len(game.state.battlecry_history), int(cid == 'BE_720'))
            self.assertEqual(game.state.entities[source].zone, Zone.BOARD if cid == 'BE_720' else Zone.GRAVEYARD)

    def test_c_complete_generation_excludes_current_class_for_all_eleven_classes(self):
        for cls in PLAYABLE_CARD_CLASSES:
            game = self.game(('BE_724',), hero=cls)
            selected, rng = self.expected(game, 3)
            self.play(game, 'BE_724')
            self.assertEqual(self.hand(game), selected)
            self.assertEqual(game._rng.getstate(), rng)
            self.assertTrue(all(game.registry.card(cid).metadata.classes != (cls,) for cid in self.hand(game)))

    def test_d_natural_deathrattle_uses_new_controller_class_and_can_repeat_a_larva(self):
        game = self.game(('BE_722', TAKE, KILL))
        source = self.play(game, 'BE_722')
        self.play(game, TAKE, source)
        selected, rng = self.expected(game, 2, 2)
        self.play(game, KILL, source)
        self.assertEqual(self.hand(game, 2), selected)
        self.assertEqual(game._rng.getstate(), rng)
        self.assertEqual(game.state.deathrattle_history[-1].capture.player_id, 2)
        self.assertTrue(all(game.registry.card(cid).metadata.classes != (CardClass.MAGE,) for cid in selected))
        self.portable(game)
        # Sampling is with replacement, rather than inventing distinct results.
        candidates = tuple(PoolMember(cid) for cid in sorted(cards.LARVAE) if cid != 'BE_720t3')
        for seed in range(100):
            rng = Random(seed)
            first, second = (sample_candidates(rng, candidates, 1, replacement=True)[0] for _ in range(2))
            if first == second:
                break
        else:
            self.fail('Deterministic fixture seed for repeated finite samples was not found')
        game = self.game(('BE_722', KILL), seed=seed)
        source = self.play(game, 'BE_722')
        self.play(game, KILL, source)
        self.assertEqual(self.hand(game), (first, second))

    def test_e_silence_removes_the_real_deathrattle(self):
        game = self.game(('BE_722', SILENCE, KILL))
        source = self.play(game, 'BE_722')
        self.play(game, SILENCE, source)
        self.play(game, KILL, source)
        self.assertEqual(self.hand(game), ())
        self.assertEqual(game.state.deathrattle_history, [])

    def test_f_every_larva_as_first_card_is_a_plain_two_one_without_a_power_use(self):
        for cid in cards.LARVAE:
            game = self.game((cid,))
            source = self.play(game, cid)
            self.assertEqual(self.board(game), (cid,))
            self.assertEqual((game.state.entities[source].attack, game.state.entities[source].health), (2, 1))
            self.assertEqual(game.state.combo_history, [])
            self.assertEqual(game.state.hero_power_history, [])
            self.assertEqual(game.state.players[1].mana, 29)
            self.assertEqual((self.hero(game).health, self.hero(game, 2).health), (30, 30))

    def test_g_priest_and_mage_have_conditional_character_targets_and_minion_effects(self):
        for cid, expected_health in (('BE_720t1', 30), ('BE_720t8', 27)):
            game = self.game((HURT, cid), board=('CS2_052',))
            own = self.hero(game).id
            self.play(game, HURT, own)
            source = self.play(game, cid, own)
            self.assertEqual(self.hero(game).health, expected_health)
            self.assertEqual(len(game.state.combo_history), 1)
            self.assertEqual(game.state.hero_power_history, [])
            if cid == 'BE_720t8':
                packets = [health_result(event) for event in game.events if event.kind == 'health_resolved']
                actual = [packet for packet in packets if packet.source_id == source]
                self.assertEqual(len(actual), 1)
                self.assertEqual((actual[0].damage_kind, actual[0].spell_bonus), ('minion_ability', 0))
            self.assertEqual(game.state.players[1].hero_power_uses_this_turn, 0)

    def test_h_target_arrow_is_only_required_when_combo_is_enabled_and_invalid_target_rolls_back(self):
        game = self.game((NOP, 'BE_720t8'))
        self.play(game, NOP)
        before = game.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(game, 'BE_720t8')
        self.assertEqual(game.snapshot(), before)
        source = self.play(game, 'BE_720t8', self.hero(game, 2).id)
        self.assertEqual(self.hero(game, 2).health, 29)
        self.assertEqual(game.state.combo_history[-1].source_id, source)

    def test_i_hunter_warrior_and_warlock_execute_printed_packets_without_power_history(self):
        for cid in ('BE_720t5', 'BE_720t7', 'BE_720t9'):
            game = self.game((NOP, cid))
            self.play(game, NOP)
            self.play(game, cid)
            self.assertEqual(self.hero(game, 2).health, 28 if cid == 'BE_720t5' else 30)
            self.assertEqual(self.hero(game).health, 28 if cid == 'BE_720t7' else 30)
            self.assertEqual(self.hero(game).armor, 2 if cid == 'BE_720t9' else 0)
            self.assertEqual(self.hand(game), (FILLER,) if cid == 'BE_720t7' else ())
            self.assertEqual(len(game.state.play_history), 2)
            self.assertEqual(len(game.state.combo_history), 1)
            self.assertEqual(game.state.hero_power_history, [])

    def test_j_druid_and_demon_hunter_attack_expires_but_armor_remains(self):
        for cid in ('BE_720t6', 'BE_720t10'):
            game = self.game((NOP, cid))
            self.play(game, NOP)
            self.play(game, cid)
            self.assertEqual(self.hero(game).attack, 1)
            self.assertEqual(self.hero(game).armor, int(cid == 'BE_720t6'))
            game.apply(EndTurn(1))
            self.assertEqual(self.hero(game).attack, 0)
            self.assertEqual(self.hero(game).armor, int(cid == 'BE_720t6'))

    def test_k_rogue_equips_the_original_one_two_weapon(self):
        game = self.game((NOP, 'BE_720t3'))
        self.play(game, NOP)
        self.play(game, 'BE_720t3')
        weapon = game.state.entities[game.state.players[1].weapon_id]
        self.assertEqual((weapon.card_id, weapon.attack, weapon.durability), ('CS2_082', 1, 2))
        self.assertEqual(game.state.hero_power_history, [])

    def test_l_paladin_and_death_knight_summon_full_original_minions_with_native_combo_cause(self):
        for cid, child in (('BE_720t4', 'CS2_101t'), ('BE_720t11', 'HERO_11bpt')):
            game = self.game((NOP, cid))
            self.play(game, NOP)
            self.play(game, cid)
            self.assertEqual(self.board(game), (cid, child))
            summoned = game.state.entities[game.state.players[1].board[-1]]
            self.assertEqual((summoned.attack, summoned.health), (1, 1))
            self.assertEqual(len(game.state.combo_history), 1)
            if child == 'HERO_11bpt':
                self.assertIn(Keyword.CHARGE, summoned.keywords)
                game.apply(Attack(1, summoned.id, self.hero(game, 2).id))
                self.assertEqual(self.hero(game, 2).health, 29)
                game.apply(EndTurn(1))
                self.assertEqual(game.state.entities[summoned.id].zone, Zone.GRAVEYARD)
            self.assertEqual(game.state.hero_power_history, [])

    def test_m_shaman_uses_current_four_basic_totems_with_duplicate_summons_allowed(self):
        game = self.game((NOP, 'BE_720t2'), board=cards.BASIC_TOTEMS)
        self.play(game, NOP)
        self.play(game, 'BE_720t2')
        self.assertEqual(len(self.board(game)), 6)
        self.assertIn(self.board(game)[-1], cards.BASIC_TOTEMS)
        self.assertNotIn('CS2_052', self.board(game))
        self.assertEqual(game.state.hero_power_history, [])

    def test_n_strength_totem_buffs_one_other_friendly_minion_at_its_controller_end(self):
        game = self.game(board=(cards.STRENGTH_TOTEM, FILLER), enemy=(FILLER,))
        source, friend = game.state.players[1].board
        enemy, = game.state.players[2].board
        game.apply(EndTurn(1))
        self.assertEqual((game.state.entities[source].attack, game.state.entities[friend].attack,
            game.state.entities[enemy].attack), (0, 5, 4))
        game.apply(EndTurn(2))
        self.assertEqual(game.state.entities[friend].attack, 5)
        self.portable(game)
        solo = self.game(board=(cards.STRENGTH_TOTEM,))
        rng = solo._rng.getstate()
        solo.apply(EndTurn(1))
        self.assertEqual(solo._rng.getstate(), rng)
        self.assertEqual(solo.state.entities[solo.state.players[1].board[0]].attack, 0)

    def test_o_full_board_skips_only_the_summon_after_accepting_combo(self):
        for cid in ('BE_720t2', 'BE_720t4', 'BE_720t11'):
            game = self.game((NOP, cid), board=(FILLER,) * 6)
            self.play(game, NOP)
            rng = game._rng.getstate()
            self.play(game, cid)
            self.assertEqual(len(self.board(game)), 7)
            self.assertEqual(game._rng.getstate(), rng)
            self.assertEqual(len(game.state.combo_history), 1)
            self.assertEqual(game.state.players[1].mana, 29)

    def test_p_full_hand_samples_all_three_then_burns_without_dropping_candidates(self):
        game = self.game(('BE_724',) + (NOP,) * 9)
        selected, rng = self.expected(game, 3)
        self.play(game, 'BE_724')
        self.assertEqual(self.hand(game), (NOP,) * 9 + selected[:1])
        self.assertEqual(game._rng.getstate(), rng)
        burned = tuple(e.card_id for e in game.state.entities.values()
            if e.card_id in cards.LARVAE and e.zone == Zone.GRAVEYARD)
        self.assertEqual(burned, selected[1:])

    def test_q_unknown_eligible_leaf_and_unknown_totem_fail_before_rng_even_when_full(self):
        for full_hand in (False, True):
            game = self.game(('BE_724',) + ((NOP,) * 9 if full_hand else ()), missing='BE_720t1')
            before = game.snapshot()
            with self.assertRaises((ResolutionError, KeyError, ValueError)):
                self.play(game, 'BE_724')
            self.assertEqual(game.snapshot(), before)
        game = self.game((NOP, 'BE_720t2'), board=(FILLER,) * 6, missing='CS2_050')
        self.play(game, NOP)
        before = game.snapshot()
        with self.assertRaises((ResolutionError, KeyError, ValueError)):
            self.play(game, 'BE_720t2')
        self.assertEqual(game.snapshot(), before)

    def test_r_delivery_waiting_restores_replays_and_failure_preserves_remaining_samples(self):
        game = self.game(('BE_724',), mode='wait')
        selected, rng = self.expected(game, 3)
        self.play(game, 'BE_724')
        self.assertEqual(self.hand(game), selected[:1])
        restored = self.portable(game, 'wait')
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(game, 'fail')
        self.assertEqual(game.snapshot(), before)
        for branch in (game, restored):
            for count in (1, 2, 3):
                self.assertEqual(len(self.hand(branch)), count)
                self.choose(branch)
            self.assertIsNone(branch.state.pending_choice)
            self.assertEqual(self.hand(branch), selected)
            self.assertEqual(branch._rng.getstate(), rng)
            self.assertEqual(branch.state.players[1].mana, 28)
            self.assertEqual(len(branch.state.play_history), 1)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.portable(game, 'wait')

    def test_s_failed_delivery_rolls_back_payment_rng_created_cards_and_history(self):
        game = self.game(('BE_720',), mode='fail')
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, 'BE_720')
        self.assertEqual(game.snapshot(), before)

    def test_t_full_dependency_pin_rejects_before_partial_installation(self):
        registry = uninstalled_registry()
        registry._cards['CS2_082'] = replace(registry.card('CS2_082'), attack=2)
        prior_cards, prior_behaviors = set(registry.cards), set(registry._behaviors)
        with self.assertRaises(TargetValidationError):
            cards.register_class_larva_cards(registry)
        self.assertEqual(set(registry.cards), prior_cards)
        self.assertEqual(set(registry._behaviors), prior_behaviors)
        data = cards.load_batch()
        for item in data['existing_dependencies']:
            self.assertEqual(canonical_digest(asdict(full_registry().card(item['record']['id']))),
                item['definition_sha256'])


if __name__ == '__main__':
    unittest.main()
