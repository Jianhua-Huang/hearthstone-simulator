"""R-145: two pinned representatives under the internal R-144 profile."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from hs_sim.targets import TargetValidationError, canonical_digest, load_baseline
from hs_sim.engine import (AddPlayerEffect, CardClass, CardDefinition, CardType,
    EndTurn, EndTurnSpec, Game, IllegalAction, PlayCard, PlayerEffectSpec,
    PlayerSetup, Rarity, RemovePlayerEffect, Ruleset, Scenario,
    SelectChoice, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion,
    GainArmor, RequestChoice)
from hs_sim.engine.end_turns import activated_end_turns
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import EndTurnRepeatSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import (CARD_LIMITATIONS, EXPECTED_CARD_HASHES,
    build_registry)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'm5.sandfury_aura'
PINS = {'ICC_901': '070a2203d4bc37018eb158552c443b69698282fe69f0c7970d1d8c57efa45a6d',
        'CATA_480': '97a07ad8a9f0cb55fc0cef49192ef58b74e527bd0043c013996b402900cb5d15'}


def overlay_registry():
    """Explicit public synthetic carriers; neither real card gains a new body."""
    r = build_registry()
    r.register_behavior('fixture.armor', lambda c: [GainArmor(c.player_id, 1)])
    r.register_behavior('fixture.ten', lambda c: [GainArmor(c.player_id, 10)]
        if c.event.player_id == c.player_id else [])
    r.register_behavior('fixture.wait', lambda c: [RequestChoice(c.player_id,
        (ChoiceOption('one', 'one', (GainArmor(c.player_id, 1),)),), source_id=c.source_id)])
    r.register_behavior('fixture.tail', lambda c: [RequestChoice(c.player_id,
        (ChoiceOption('one', 'one', (GainArmor(c.player_id, 10),)),), source_id=c.source_id)]
        if c.event.player_id == c.player_id else [])
    for name, behavior in (('fixture.end', 'fixture.armor'), ('fixture.waiting', 'fixture.wait')):
        r.register_card(CardDefinition(name, name, CardType.MINION, attack=1, health=8,
            triggers=(TriggerSpec('turn_ended', behavior, EndTurnSpec()),)))
    r.register_card(CardDefinition('fixture.raw', 'fixture.raw', CardType.MINION,
        health=8, triggers=(TriggerSpec('turn_ended', 'fixture.ten'),)))
    r.register_card(CardDefinition('fixture.tail', 'fixture.tail', CardType.MINION,
        health=8, triggers=(TriggerSpec('turn_ended', 'fixture.tail'),)))
    r.register_card(CardDefinition('fixture.weapon', 'fixture.weapon', CardType.WEAPON,
        attack=1, durability=3,
        triggers=(TriggerSpec('turn_ended', 'fixture.armor', EndTurnSpec()),)))
    r.register_card(CardDefinition('fixture.power', 'fixture.power', CardType.HERO_POWER,
        passive_hero_power=True,
        triggers=(TriggerSpec('turn_ended', 'fixture.armor', EndTurnSpec()),)))
    r.register_player_effect(PlayerEffectSpec('fixture.player_body', 'CS2_182',
        triggers=(TriggerSpec('turn_ended', 'fixture.armor', EndTurnSpec()),)))
    r.register_behavior('fixture.install_body', lambda c: [AddPlayerEffect(c.player_id,
        'fixture.player_body', c.state.players[c.player_id].board[0])])
    r.register_card(CardDefinition('fixture.install_body', 'fixture.install_body',
        CardType.SPELL, on_play='fixture.install_body'))
    return r


class EndTurnRepresentativeTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.overlay = False

    def use_overlay(self):
        self.r = overlay_registry()
        self.overlay = True

    def game(self, board=('BOT_107',), hand=(), enemy=(), enemy_hand=(), weapon=None,
            power=None, rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_04', board=board, hand=hand, deck=('CS2_182',) * 18,
                mana=10, max_mana=10, weapon_card_id=weapon, hero_power_card_id=power),
            PlayerSetup('HERO_08', board=enemy, hand=enemy_hand, deck=('CS2_182',) * 18,
                mana=10, max_mana=10)), seed=145), self.r, ruleset=rules)

    def play(self, game, card, target=None):
        player = game.state.active_player
        entity = next(i for i in game.state.players[player].hand
            if game.state.entities[i].card_id == card)
        game.apply(PlayCard(player, entity, target))
        return entity

    def submit(self, game, card=None):
        port = game.for_player(game.state.active_player)
        listing = port.legal_actions()
        if card is None:
            action = next(a for a in listing['actions'] if a['type'] == 'end_turn')
        else:
            own = next(p for p in listing['observation']['players']
                if p['id'] == game.state.active_player)
            ref = next(e['ref'] for e in own['hand'] if e['card_id'] == card)
            action = next(a for a in listing['actions']
                if a['type'] == 'play_card' and a['card'] == ref and a.get('target') is None)
        response = port.submit({'revision': listing['revision'], 'action': action})
        self.assertTrue(response['accepted'], response)

    def end(self, game):
        game.apply(EndTurn(game.state.active_player))

    def choose(self, game):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, ('one',)))

    def settle_end(self, game):
        self.end(game)
        while game.state.pending_choice is not None:
            self.choose(game)

    def cycle(self, game):
        self.settle_end(game)
        self.settle_end(game)

    def card_entity(self, game, card, player=1):
        return next(game.state.entities[i] for i in game.state.players[player].board
            if game.state.entities[i].card_id == card)

    def effects(self, game, player=1):
        return [e for e in game.state.players[player].player_effects if e.spec_id == SOURCE]

    def health(self, game, player=1):
        return game.state.entities[game.state.players[player].hero_id].health

    def armor(self, game, player=1):
        return game.state.entities[game.state.players[player].hero_id].armor

    def batch(self, game):
        return game.state.end_turn_batches[-1]

    def check(self, game, fresh=True):
        registry = (overlay_registry() if self.overlay else build_registry()) if fresh else self.r
        snapshot = json.loads(json.dumps(game.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot, registry).snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), snapshot)

    def script(self, name, callback):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))

    def raw_records(self):
        return {e['id']: e for e in load_baseline().support['cards']}

    def test_drakkari_has_pinned_neutral_epic_three_mana_one_five_metadata(self):
        card = self.r.card('ICC_901')
        self.assertEqual((card.kind, card.cost, card.attack, card.health), (CardType.MINION, 3, 1, 5))
        self.assertEqual((card.metadata.classes, card.metadata.rarity,
            card.metadata.collectible), ((CardClass.NEUTRAL,), Rarity.EPIC, True))

    def test_sandfury_has_pinned_paladin_rare_holy_three_mana_metadata(self):
        card = self.r.card('CATA_480')
        self.assertEqual((card.kind, card.cost, card.attack, card.health), (CardType.SPELL, 3, 0, 0))
        self.assertEqual((card.metadata.classes, card.metadata.rarity,
            card.metadata.collectible, card.spell_school),
            ((CardClass.PALADIN,), Rarity.RARE, True, SpellSchool.HOLY))

    def test_two_complete_support_pins_equal_immutable_audit_raw(self):
        audit = json.loads((ROOT / 'outputs/v104-end-turn-representatives-pre-audit.json').read_text(encoding='utf-8'))
        candidates = {e['raw']['id']: e for e in audit['catalog']}
        rows = self.raw_records()
        for card, digest in PINS.items():
            with self.subTest(card=card):
                self.assertEqual(rows[card]['data'], candidates[card]['raw'])
                self.assertEqual(rows[card]['data_sha256'], digest)
                self.assertEqual(canonical_digest(rows[card]['data']), digest)
                self.assertEqual(EXPECTED_CARD_HASHES[card], digest)

    def test_previous_three_hundred_support_rows_remain_exactly_unchanged(self):
        audit = json.loads((ROOT / 'outputs/v104-end-turn-representatives-pre-audit.json').read_text(encoding='utf-8'))
        old_rows = [e for e in load_baseline().support['cards'] if e['id'] not in PINS and e['id'] not in ('CATA_472', 'TIME_064', 'RLK_541')]
        self.assertEqual(len(old_rows), 300)
        self.assertEqual(canonical_digest(old_rows), audit['baseline']['support_cards_canonical_sha256'])
        self.assertEqual((self.r.version, len(self.r.cards), len(EXPECTED_CARD_HASHES)),
            ('representative-m5-v65', 311, 305))

    def test_core_enchantment_and_battlegrounds_components_not_added(self):
        for card in ('CORE_ICC_901', 'ICC_901e', 'BG26_ICC_901', 'BG26_ICC_901_G',
                'CATA_480e', 'CATA_480t', 'TIME_064e'):
            with self.subTest(card=card):
                self.assertNotIn(card, self.r.cards)
                self.assertNotIn(card, EXPECTED_CARD_HASHES)

    def test_raw_placeholder_nulls_and_three_tags_remain_source_evidence(self):
        raw = self.raw_records()['CATA_480']['data']
        self.assertEqual(raw['dbf_id'], 123691)
        self.assertEqual(raw['text'], '你的随从的回合结束效果会触发两次。持续@回合。')
        self.assertIn('@', raw['text_en'])
        self.assertIsNone(raw['attack'])
        self.assertIsNone(raw['health'])
        self.assertEqual((raw['tags']['QUEST_PROGRESS_TOTAL'], raw['tags']['TAG_SCRIPT_DATA_NUM_1']), (3, 3))
        self.assertEqual((raw['reference_tags'], raw['related_dbf_ids']), ([], []))
        self.assertIn('R-145', CARD_LIMITATIONS['CATA_480'])
        self.assertIn('uncalibrated', CARD_LIMITATIONS['CATA_480'])

    def test_tampered_new_raw_pin_rejected_before_adapter_construction(self):
        for card in PINS:
            with self.subTest(card=card):
                baseline = load_baseline()
                row = next(e for e in baseline.support['cards'] if e['id'] == card)
                row['data']['cost'] = 4
                with patch('hs_sim.engine.representative.load_baseline', return_value=baseline):
                    with self.assertRaises(TargetValidationError):
                        build_registry()

    def test_drakkari_declares_only_a_printed_all_source_and_no_end_body(self):
        card = self.r.card('ICC_901')
        self.assertEqual(card.end_turn_repeats, (EndTurnRepeatSpec(2, 'all'),))
        self.assertEqual(card.triggers, ())
        game = self.game(board=('ICC_901',))
        ability = active_abilities(self.card_entity(game, 'ICC_901'), 'end_turn_repeat')[0]
        self.assertEqual((ability.origin, ability.source_id),
            ('printed', self.card_entity(game, 'ICC_901').id))
        self.end(game)
        self.assertEqual(self.batch(game).total, 0)

    def test_sandfury_is_one_ongoing_install_without_synthetic_trigger_or_on_play(self):
        card = self.r.card('CATA_480')
        spec = self.r.player_effect(SOURCE)
        self.assertEqual((card.ongoing_effect_id, card.on_play, card.triggers), (SOURCE, None, ()))
        self.assertEqual((spec.card_id, spec.kind, spec.duration, spec.tick_event),
            ('CATA_480', 'aura', 3, 'turn_ended'))
        self.assertEqual((spec.end_turn_repeats, spec.triggers, spec.on_expire),
            ((EndTurnRepeatSpec(2, 'minion'),), (), None))

    def test_both_normal_card_roots_pay_once_and_cata_spell_enters_graveyard(self):
        game = self.game(hand=('ICC_901', 'CATA_480'))
        self.submit(game, 'ICC_901')
        self.submit(game, 'CATA_480')
        source = self.effects(game)[0].source_id
        self.assertEqual(game.state.players[1].mana, 4)
        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual((self.effects(game)[0].source_id, self.effects(game)[0].source_card_id),
            (source, 'CATA_480'))
        self.assertEqual([e.kind for e in game.events].count('card_played'), 2)
        self.assertEqual([e.kind for e in game.events].count('player_effect_added'), 1)
        self.assertFalse(game.state.end_turn_batches)
        self.check(game)

    def test_countered_sandfury_pays_but_installs_no_instance(self):
        game = self.game(board=(), hand=('CATA_480',), enemy_hand=('EX1_287',))
        self.end(game)
        self.play(game, 'EX1_287')
        self.end(game)
        self.play(game, 'CATA_480')
        self.assertEqual(game.state.players[1].mana, 7)
        self.assertFalse(self.effects(game))
        self.assertIn('spell_countered', [e.kind for e in game.events])
        self.check(game)

    def test_ongoing_capacity_rejects_sandfury_before_payment(self):
        game = self.game(hand=('CATA_480', 'CATA_480'), rules=Ruleset(max_ongoing_effects=1))
        self.play(game, 'CATA_480')
        before = game.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(game, 'CATA_480')
        self.assertEqual(game.snapshot(), before)
        self.assertEqual(len(self.effects(game)), 1)
        self.check(game)

    def test_failed_internal_install_preserves_existing_sandfury_instance(self):
        # Native Aura installation must name its actual controlled spell.
        self.script('add', lambda c: [AddPlayerEffect(1, SOURCE, next(e.id
            for e in c.state.entities.values() if e.card_id == 'CATA_480' and e.controller == 1))])
        game = self.game(hand=('CATA_480', 'add'), rules=Ruleset(max_ongoing_effects=1))
        self.play(game, 'CATA_480')
        original = self.effects(game)[0]
        self.play(game, 'add')
        self.assertEqual(self.effects(game), [original])
        self.assertEqual([e.kind for e in game.events].count('player_effect_failed'), 1)
        self.check(game, fresh=False)

    def test_bot_without_repeat_source_has_one_wave(self):
        game = self.game()
        self.end(game)
        self.assertEqual((self.batch(game).total, self.health(game, 1), self.health(game, 2)), (1, 29, 29))
        self.assertEqual(self.card_entity(game, 'BOT_107').health, 4)
        self.check(game)

    def test_bot_with_only_drakkari_has_two_waves_and_one_complete_board_source(self):
        game = self.game(board=('BOT_107', 'ICC_901'))
        self.end(game)
        plan = self.batch(game).plans[0]
        self.assertEqual((plan.repetitions, len(plan.contributors)), (2, 1))
        self.assertEqual(plan.contributors[0].card_id, 'ICC_901')
        self.assertEqual((self.health(game), self.card_entity(game, 'ICC_901').health), (28, 3))
        self.check(game)

    def test_bot_with_only_sandfury_has_two_waves_and_one_owner_tick(self):
        game = self.game(hand=('CATA_480',))
        self.play(game, 'CATA_480')
        self.end(game)
        plan = self.batch(game).plans[0]
        self.assertEqual((plan.repetitions, len(plan.contributors)), (2, 1))
        self.assertEqual((plan.contributors[0].card_id, plan.contributors[0].spec_index), ('CATA_480', 0))
        self.assertEqual(self.effects(game)[0].remaining_turns, 2)
        self.assertEqual(self.health(game), 28)
        self.check(game)

    def test_both_real_sources_merge_max_and_retain_both_provenances(self):
        game = self.game(board=('BOT_107', 'ICC_901'), hand=('CATA_480',))
        source = self.play(game, 'CATA_480')
        self.end(game)
        plan = self.batch(game).plans[0]
        self.assertEqual((plan.repetitions, len(plan.contributors)), (2, 2))
        self.assertEqual([s.card_id for s in plan.contributors], ['ICC_901', 'CATA_480'])
        self.assertEqual(plan.contributors[1].player_effect.source_id, source)
        self.assertEqual((self.health(game, 1), self.health(game, 2)), (28, 28))
        self.check(game)

    def test_seven_boundaries_match_deterministic_real_candidate_and_fresh_continuation(self):
        game = self.game(hand=('ICC_901', 'CATA_480'))
        self.submit(game, 'ICC_901')
        self.submit(game, 'CATA_480')
        restored = Game.from_snapshot(json.loads(json.dumps(game.snapshot())), build_registry())
        for match in (game, restored):
            for _ in range(7):
                self.submit(match)
            self.assertEqual([b.total for b in match.state.end_turn_batches], [2, 0, 2, 0, 2, 0, 1])
            self.assertEqual((self.health(match, 1), self.health(match, 2)), (23, 23))
            self.assertEqual(self.card_entity(match, 'BOT_107').health, 4)
            self.assertFalse(self.effects(match))
            self.assertEqual([d.card_id for d in match.state.death_history], ['ICC_901'])
            self.assertEqual(len(activated_end_turns(match.state, 1, completed=True)), 7)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.check(game)

    def test_drakkari_only_control_loses_future_plan_after_third_boundary_death(self):
        game = self.game(board=('BOT_107', 'ICC_901'))
        for _ in range(7):
            self.end(game)
        self.assertEqual([b.total for b in game.state.end_turn_batches], [2, 0, 2, 0, 2, 0, 1])
        self.assertFalse(game.state.players[1].player_effects)
        self.assertEqual([d.card_id for d in game.state.death_history], ['ICC_901'])
        self.check(game)

    def test_sandfury_only_control_counts_casting_end_and_three_owner_boundaries(self):
        game = self.game(hand=('CATA_480',))
        self.play(game, 'CATA_480')
        for _ in range(7):
            self.end(game)
        self.assertEqual([b.total for b in game.state.end_turn_batches], [2, 0, 2, 0, 2, 0, 1])
        self.assertEqual([e.kind for e in game.events].count('player_effect_ticked'), 2)
        self.assertEqual([e.kind for e in game.events].count('player_effect_expired'), 1)
        self.assertFalse(game.state.death_history)
        self.check(game)

    def test_last_remaining_real_source_death_keeps_accepted_extra_before_expiry(self):
        game = self.game(board=('BOT_107', 'ICC_901'), hand=('CATA_480',))
        self.play(game, 'CATA_480')
        self.cycle(game)
        self.cycle(game)
        source = self.card_entity(game, 'ICC_901').id
        self.assertEqual(self.effects(game)[0].remaining_turns, 1)
        self.end(game)
        rows = game.state.end_turn_history[-2:]
        self.assertTrue(all(r.completed for r in rows))
        self.assertEqual(len(self.batch(game).plans[0].contributors), 2)
        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(self.batch(game).plans[0].contributors[1].player_effect.remaining_turns, 1)
        events = list(game.events)
        expired = max(i for i, e in enumerate(events) if e.kind == 'player_effect_expired')
        damage = max(i for i, e in enumerate(events) if e.kind == 'damage_dealt')
        self.assertGreater(expired, damage)
        self.check(game)

    def test_real_silence_removes_drakkari_future_source_but_not_sandfury(self):
        game = self.game(board=('BOT_107', 'ICC_901'), hand=('CATA_480', 'EX1_332'))
        self.play(game, 'CATA_480')
        self.play(game, 'EX1_332', self.card_entity(game, 'ICC_901').id)
        self.end(game)
        self.assertEqual([s.card_id for s in self.batch(game).plans[0].contributors], ['CATA_480'])
        self.assertEqual(self.batch(game).total, 2)
        self.check(game)

    def test_drakkari_copy_keeps_distinct_attachment_sources_with_max_two(self):
        self.script('copy', lambda c: [CopyMinion(c.state.players[1].board[1], 1)])
        game = self.game(board=('BOT_107', 'ICC_901'), hand=('copy',))
        self.play(game, 'copy')
        self.end(game)
        sources = self.batch(game).plans[0].contributors
        self.assertEqual((self.batch(game).total, len(sources)), (2, 2))
        self.assertEqual(len({s.carrier_id for s in sources}), 2)
        self.assertEqual(len({s.ability.id for s in sources}), 2)
        self.check(game, fresh=False)

    def test_transferred_board_source_changes_owner_without_transferring_player_source(self):
        self.use_overlay()
        self.script('transfer', lambda c: [ChangeControl(c.state.players[1].board[0], 2)])
        game = self.game(board=('ICC_901', 'fixture.end'), enemy=('fixture.end',),
            hand=('CATA_480', 'transfer'))
        self.play(game, 'CATA_480')
        self.play(game, 'transfer')
        self.end(game)
        self.assertEqual([s.card_id for s in self.batch(game).plans[0].contributors], ['CATA_480'])
        self.end(game)
        self.assertEqual([s.card_id for s in self.batch(game).plans[0].contributors], ['ICC_901'])
        self.assertEqual(self.effects(game, 1)[0].remaining_turns, 2)
        self.assertFalse(self.effects(game, 2))
        self.assertEqual((self.armor(game, 1), self.armor(game, 2)), (2, 2))
        self.check(game, fresh=False)

    def test_source_independent_sandfury_instance_survives_spell_graveyard(self):
        game = self.game(board=(), hand=('CATA_480',))
        source = self.play(game, 'CATA_480')
        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)
        self.cycle(game)
        instance = self.effects(game)[0]
        self.assertEqual((instance.source_id, instance.source_card_id, instance.remaining_turns),
            (source, 'CATA_480', 2))
        self.check(game)

    def test_duplicate_sandfury_instances_are_complete_sources_and_do_not_multiply(self):
        game = self.game(hand=('CATA_480', 'CATA_480'))
        self.play(game, 'CATA_480')
        self.play(game, 'CATA_480')
        originals = self.effects(game)
        self.assertEqual(len({e.id for e in originals}), 2)
        self.end(game)
        sources = self.batch(game).plans[0].contributors
        self.assertEqual((self.batch(game).total, len(sources)), (2, 2))
        self.assertEqual({s.player_effect.id for s in sources}, {e.id for e in originals})
        self.assertEqual([e.remaining_turns for e in self.effects(game)], [2, 2])
        self.check(game)

    def test_staggered_sandfury_instances_tick_and_expire_independently(self):
        game = self.game(hand=('CATA_480', 'CATA_480'))
        self.play(game, 'CATA_480')
        old = self.effects(game)[0].id
        self.cycle(game)
        self.play(game, 'CATA_480')
        new = self.effects(game)[1].id
        self.cycle(game)
        self.assertEqual([(e.id, e.remaining_turns) for e in self.effects(game)], [(old, 1), (new, 2)])
        self.end(game)
        self.assertEqual([(e.id, e.remaining_turns) for e in self.effects(game)], [(new, 1)])
        self.assertEqual(len(self.batch(game).plans[0].contributors), 2)
        self.check(game)

    def test_removing_one_same_key_instance_preserves_other_plan_and_clock(self):
        self.script('remove', lambda c: [RemovePlayerEffect(1,
            c.state.players[1].player_effects[0].id)])
        game = self.game(hand=('CATA_480', 'CATA_480', 'remove'))
        self.play(game, 'CATA_480')
        self.play(game, 'CATA_480')
        survivor = self.effects(game)[1].id
        self.play(game, 'remove')
        self.end(game)
        self.assertEqual([e.id for e in self.effects(game)], [survivor])
        self.assertEqual(self.effects(game)[0].remaining_turns, 2)
        self.assertEqual(len(self.batch(game).plans[0].contributors), 1)
        self.check(game, fresh=False)

    def test_real_sandfury_minion_filter_excludes_weapon_power_and_minion_sourced_player_body(self):
        self.use_overlay()
        game = self.game(board=('fixture.end',), hand=('CATA_480', 'fixture.install_body'),
            weapon='fixture.weapon', power='fixture.power')
        self.play(game, 'CATA_480')
        self.play(game, 'fixture.install_body')
        self.end(game)
        subjects = self.batch(game).subjects
        self.assertEqual([p.repetitions for p in self.batch(game).plans], [1, 1, 2, 1])
        pe = next(s for s in subjects if s.player_effect is not None)
        self.assertEqual(game.state.entities[pe.source_id].kind, CardType.MINION)
        self.assertEqual(self.armor(game), 5)
        self.check(game)

    def test_real_drakkari_all_filter_includes_the_same_explicit_carrier_overlay(self):
        self.use_overlay()
        game = self.game(board=('ICC_901', 'fixture.end'), hand=('fixture.install_body',),
            weapon='fixture.weapon', power='fixture.power')
        self.play(game, 'fixture.install_body')
        self.end(game)
        self.assertEqual([p.repetitions for p in self.batch(game).plans], [2, 2, 2, 2])
        self.assertEqual(self.armor(game), 8)
        self.check(game)

    def test_real_sandfury_never_repeats_ordinary_listener_or_its_clock(self):
        self.use_overlay()
        game = self.game(board=('fixture.end', 'fixture.raw'), hand=('CATA_480',))
        self.play(game, 'CATA_480')
        self.end(game)
        self.assertEqual((self.batch(game).total, self.armor(game)), (2, 12))
        self.assertEqual(self.effects(game)[0].remaining_turns, 2)
        self.assertEqual([e.kind for e in game.events].count('player_effect_ticked'), 1)
        self.check(game)

    def test_last_tick_first_and_extra_choices_restore_clone_and_replay_fresh_overlay(self):
        self.use_overlay()
        game = self.game(board=('fixture.waiting',), hand=('CATA_480',))
        self.play(game, 'CATA_480')
        self.cycle(game)
        self.cycle(game)
        self.assertEqual(self.effects(game)[0].remaining_turns, 1)
        self.end(game)
        self.check(game)
        self.choose(game)
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(self.effects(game)[0].remaining_turns, 1)
        self.assertEqual([r.completed for r in game.state.end_turn_history[-2:]], [True, False])
        self.check(game)
        restored = Game.from_snapshot(json.loads(json.dumps(game.snapshot())), overlay_registry())
        self.choose(game)
        self.choose(restored)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertFalse(self.effects(game))
        self.assertEqual([e.kind for e in game.events].count('player_effect_expired'), 1)
        self.check(game)

    def test_last_tick_tail_ordinary_choice_keeps_finished_bodies_before_one_expiry(self):
        self.use_overlay()
        game = self.game(board=('fixture.end', 'fixture.tail'), hand=('CATA_480',))
        self.play(game, 'CATA_480')
        self.cycle(game)
        self.cycle(game)
        self.end(game)
        self.assertIsNotNone(game.state.pending_choice)
        self.assertTrue(all(r.completed for r in game.state.end_turn_history[-2:]))
        self.assertFalse(self.batch(game).completed)
        self.assertEqual(self.effects(game)[0].remaining_turns, 1)
        self.check(game)
        self.choose(game)
        self.assertTrue(self.batch(game).completed)
        self.assertFalse(self.effects(game))
        self.assertEqual(self.armor(game), 36)
        self.check(game)

    def test_public_player_effect_dto_shows_card_and_remaining_without_internal_provenance(self):
        game = self.game(board=(), hand=('CATA_480', 'CATA_480'))
        self.play(game, 'CATA_480')
        self.play(game, 'CATA_480')
        for viewer in (1, 2):
            view = game.observe(viewer)
            player = next(p for p in view['players'] if p['id'] == 1)
            effects = player['player_effects']
            self.assertEqual(len(effects), 2)
            self.assertTrue(all(e == {'effect_key': SOURCE, 'card_id': 'CATA_480',
                'effect_kind': 'aura', 'remaining_turns': 3} for e in effects))
            text = json.dumps((view, game.player_events(viewer), game.for_player(viewer).legal_actions()))
            for hidden in ('end_turn_batches', 'end_turn_history', 'contributors', 'source_id',
                    'instance_id', 'source_card_id', 'guard_id', 'guard_event', 'repeat_index'):
                self.assertNotIn('"' + hidden + '"', text)
        self.check(game)


if __name__ == '__main__':
    unittest.main()
