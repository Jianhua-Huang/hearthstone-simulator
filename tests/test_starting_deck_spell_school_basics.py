"""Original constructed SPELL subset, resumable branches and one native opening."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CheckDeckCondition,
    ChoicePurpose, DeckCondition, DeckCostCondition, DeckSpellSchoolCondition, DeckSpec,
    EndTurn, Game, MatchSetup, OpeningHook, PlayCard, PlayerSetup, Rarity, ResolutionError,
    Scenario, SelectChoice, SnapshotError, SpellSchool, TargetSpec, UnknownDeckFacts,
    UseHeroPower, Zone, matches_deck_condition)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand, ChangeManaCrystals, ChoiceOption, Damage,
    Draw, GainArmor, InvokeBehavior, ReplaceHeroPower, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.zones import AddToDeck, DestroyDeckMatching
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry
from test_current_deck_empty_basics import rehash
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE = 'SW_448'
POWER = 'EX1_625t'
CONDITION = DeckSpellSchoolCondition(SpellSchool.SHADOW)
SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/starting-deck-spell-school-basics.json'
PIN = '5c817b82e40a09c470c2b0bf9faac731b9be04b6e64cf1a66e1828a000c05440'


def evidence():
    packet = json.loads(SUPPORT.read_bytes())
    if canonical_digest(packet) != PIN or [r['id'] for r in packet['records']] != ['CORE_SW_448', NATIVE, POWER]:
        raise ValueError('Complete native starting-deck school source changed')
    for row in packet['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Complete original card row changed')
    return {r['id']: r['data'] for r in packet['records']}


def pause(player):
    return RequestChoice(player, (ChoiceOption('ok', 'OK', ()),))


def branch(player):
    return CheckDeckCondition(player, CONDITION, (GainArmor(player, 3),), (GainArmor(player, 1),))


def registry():
    r = opening_registry()
    raw = evidence()
    r.register_behavior('school.base.power', lambda c: (GainArmor(c.player_id, 1),))
    r.register_card(CardDefinition('priest.power', 'Experimental Priest Power', CardType.HERO_POWER,
        cost=2, on_use='school.base.power', metadata=metadata(CardClass.PRIEST, collectible=False)))
    r.register_card(CardDefinition('priest.hero', 'Experimental Priest Hero', CardType.HERO, health=30,
        initial_hero_power='priest.power', metadata=metadata(CardClass.PRIEST, collectible=False)))
    r.register_behavior('school.native.start', lambda c: (CheckDeckCondition(c.player_id, CONDITION,
        (ReplaceHeroPower(c.player_id, POWER, source_id=c.source_id),)),))
    row = raw[NATIVE]
    r.register_card(CardDefinition(NATIVE, row['name'], CardType.MINION, cost=row['cost'],
        attack=row['attack'], health=row['health'], metadata=metadata_from_record(row),
        opening_hooks=(OpeningHook('before_deal', 'school.native.start'),)))
    row = raw[POWER]
    r.register_behavior('school.native.power', lambda c: (Damage(c.target_id, 2, c.source_id),))
    r.register_card(CardDefinition(POWER, row['name'], CardType.HERO_POWER, cost=row['cost'],
        on_use='school.native.power', targeting=TargetSpec(), metadata=metadata_from_record(row)))
    for school in SpellSchool:
        r.register_card(CardDefinition('spell.' + school.value, school.value, CardType.SPELL, cost=1,
            spell_school=school, metadata=metadata(CardClass.PRIEST)))
    r.register_card(CardDefinition('spell.none', 'Known schoolless spell', CardType.SPELL, cost=1,
        metadata=metadata(CardClass.PRIEST)))
    r.register_card(CardDefinition('spell.no_meta', 'Known typed spell without class facts', CardType.SPELL,
        spell_school=SpellSchool.SHADOW))
    r.register_card(CardDefinition('minion.no_meta', 'Known typed minion without class facts', CardType.MINION, health=1))
    r.register_card(CardDefinition('neutral.weapon', 'Experimental weapon', CardType.WEAPON, attack=1,
        durability=1, metadata=metadata()))
    r.register_card(CardDefinition('neutral.location', 'Experimental location', CardType.LOCATION,
        durability=1, on_use='school.base.power', metadata=metadata()))

    def prepare(c):
        return (ChangeManaCrystals(c.player_id, 9),
            *(AddToHand(c.player_id, cid) for cid in c.state.players[c.player_id].original_deck if cid.startswith('tool.')))

    def fail(c):
        raise ResolutionError('Expected school-condition continuation failure')

    def board_native(c):
        return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == NATIVE)

    r.register_behavior('school.prepare', prepare)
    r.register_card(CardDefinition('fixture.prepare', 'Experimental tools', CardType.MINION, health=1,
        opening_hooks=(OpeningHook('after_mulligan', 'school.prepare'),), metadata=metadata()))
    r.register_behavior('school.fail', fail)
    scripts = {
        'tool.add.fire': lambda c: (AddToDeck(c.player_id, 'spell.fire'),),
        'tool.clear': lambda c: (DestroyDeckMatching(c.player_id, count=40, reveal=False),),
        'tool.draw': lambda c: (Draw(c.player_id),),
        'tool.wait': lambda c: (pause(c.player_id), branch(c.player_id)),
        'tool.selected': lambda c: (CheckDeckCondition(c.player_id, CONDITION,
            (pause(c.player_id), AddToDeck(c.player_id, 'spell.fire'), GainArmor(c.player_id, 3)),
            (pause(c.player_id), DestroyDeckMatching(c.player_id, count=40, reveal=False), GainArmor(c.player_id, 1))),),
        'tool.fail': lambda c: (branch(c.player_id), InvokeBehavior('school.fail', c.source_id, c.player_id)),
        'tool.wait.fail': lambda c: (pause(c.player_id), branch(c.player_id), InvokeBehavior('school.fail', c.source_id, c.player_id)),
        'tool.fetch.native': lambda c: (AddToHand(c.player_id, NATIVE),),
        'tool.replace.power': lambda c: (ReplaceHeroPower(c.player_id, 'priest.power', source_id=c.source_id),),
        'tool.silence.native': lambda c: (Silence(board_native(c)),),
        'tool.bounce.native': lambda c: (ReturnToHand(board_native(c)),),
    }
    for cid, fn in scripts.items():
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=1, battlecry=cid, metadata=metadata()))
    for cid, phase, fn in (
        ('fixture.wait.before', 'before_deal', lambda c: (pause(c.player_id), branch(c.player_id))),
        ('fixture.wait.after', 'after_mulligan', lambda c: (CheckDeckCondition(c.player_id, CONDITION,
            (pause(c.player_id), GainArmor(c.player_id, 3)), (pause(c.player_id), GainArmor(c.player_id, 1))),)),
        ('fixture.wait.fail', 'before_deal', lambda c: (pause(c.player_id), branch(c.player_id),
            InvokeBehavior('school.fail', c.source_id, c.player_id))),
    ):
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=1,
            opening_hooks=(OpeningHook(phase, cid),), metadata=metadata()))
    return r


class StartingDeckSpellSchoolTests(unittest.TestCase):
    def match(self, spells=('spell.shadow',), *, extra=(), native=True, second_spells=(),
              second_native=False, first=1, finish=True):
        r = registry()
        def cards(prefix):
            self.assertLessEqual(len(prefix), 30)
            return tuple(prefix) + tuple(f'card.{i}' for i in range(1, 31 - len(prefix)))
        own = cards(((NATIVE,) if native else ()) + tuple(extra) + tuple(spells))
        other = cards(((NATIVE,) if second_native else ()) + tuple(second_spells))
        decks = tuple(DeckSpec('priest.hero', 'priest.power', CardClass.PRIEST, ids) for ids in (own, other))
        g = Game.from_decks(MatchSetup(decks, policy(r), 'coin', 83, first), r)
        return self.finish(g) if finish else g

    def choose(self, g, options=None):
        q = g.state.pending_choice
        if options is None:
            options = () if q.purpose == ChoicePurpose.MULLIGAN else ('ok',)
        g.apply(SelectChoice(q.player_id, q.id, tuple(options)))

    def finish(self, g):
        while g.state.pending_choice:
            self.choose(g)
        return g

    def query(self, g, player=1, school=SpellSchool.SHADOW):
        return matches_deck_condition(g.state, g.registry, player, DeckSpellSchoolCondition(school))

    def power(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_power_id]

    def play(self, g, card_id):
        player = g.state.active_player
        identity = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == card_id)
        g.apply(PlayCard(player, identity))
        return identity

    def check(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, registry())
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        return restored

    def nested(self, value, name):
        if isinstance(value, dict):
            if value.get('type', '').endswith('.' + name):
                return value
            values = value.values()
        elif isinstance(value, list):
            values = value
        else:
            return None
        for child in values:
            found = self.nested(child, name)
            if found is not None:
                return found

    def reject(self, saved):
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(rehash(saved), registry())

    def test_full_raw_pin_native_definition_and_exact_related_power(self):
        raw = evidence()
        r = registry()
        native, power = r.card(NATIVE), r.card(POWER)
        self.assertEqual((native.cost, native.attack, native.health), (5, 5, 6))
        self.assertEqual(native.metadata, metadata_from_record(raw[NATIVE]))
        self.assertEqual((native.metadata.classes, native.metadata.rarity), ((CardClass.PRIEST,), Rarity.LEGENDARY))
        self.assertNotIn('CARDRACE', raw[NATIVE]['tags'])
        self.assertIsNone(native.battlecry)
        self.assertEqual(native.opening_hooks, (OpeningHook('before_deal', 'school.native.start'),))
        self.assertEqual(raw[NATIVE]['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'], raw[POWER]['dbf_id'])
        self.assertEqual((power.kind, power.cost, power.metadata), (CardType.HERO_POWER, 2, metadata_from_record(raw[POWER])))
        self.assertIn('$2', raw[POWER]['text_en'])
        self.assertNotIn('CORE_SW_448', r.cards)

    def test_each_known_school_is_a_parameter_not_a_new_executor(self):
        for school in SpellSchool:
            with self.subTest(school=school):
                g = self.match(('spell.' + school.value,), native=False)
                self.assertTrue(self.query(g, school=school))
                other = SpellSchool.FIRE if school != SpellSchool.FIRE else SpellSchool.SHADOW
                self.assertFalse(self.query(g, school=other))

    def test_nonspells_are_excluded_from_the_school_subset(self):
        g = self.match(extra=('neutral.weapon', 'neutral.location'))
        self.assertTrue(self.query(g))
        self.assertEqual(self.power(g).card_id, POWER)
        self.check(g)

    def test_multiple_shadow_spells_and_physical_duplicate_are_allowed(self):
        g = self.match(('spell.shadow', 'spell.shadow'))
        self.assertTrue(self.query(g))
        self.assertFalse(matches_deck_condition(g.state, g.registry, 1, DeckCondition('starting')))
        self.check(g)

    def test_known_different_school_fails_even_with_a_shadow_spell(self):
        g = self.match(('spell.shadow', 'spell.fire'))
        self.assertFalse(self.query(g))
        self.assertEqual(self.power(g).card_id, 'priest.power')
        self.check(g)

    def test_known_schoolless_spell_fails_without_guessing_it_is_shadow(self):
        g = self.match(('spell.none',))
        self.assertFalse(self.query(g))
        self.assertEqual(self.power(g).card_id, 'priest.power')
        self.check(g)

    def test_empty_spell_subset_has_explicit_universal_true_policy(self):
        g = self.match(())
        self.assertTrue(self.query(g))
        self.assertEqual(self.power(g).card_id, POWER)
        self.assertTrue(all(g.registry.card(cid).kind != CardType.SPELL for cid in g.state.players[1].original_deck))
        self.check(g)

    def test_query_and_native_hook_use_the_requested_players_own_origin(self):
        g = self.match(('spell.fire',), second_spells=('spell.shadow',), second_native=True)
        self.assertFalse(self.query(g, 1))
        self.assertTrue(self.query(g, 2))
        self.assertEqual([self.power(g, p).card_id for p in (1, 2)], ['priest.power', POWER])
        self.check(g)

    def test_scenario_starting_facts_are_unknown_even_with_matching_current_deck(self):
        g = Game.from_scenario(Scenario((PlayerSetup('priest.hero', deck=('spell.shadow',)),
            PlayerSetup('priest.hero'))), registry())
        with self.assertRaises(UnknownDeckFacts):
            self.query(g)
        self.check(g)

    def test_forged_scenario_original_tuple_cannot_supply_an_opening(self):
        g = Game.from_scenario(Scenario((PlayerSetup('priest.hero'), PlayerSetup('priest.hero'))), registry())
        saved = g.snapshot()
        saved['state']['players']['1']['original_deck'] = ['spell.shadow']
        restored = Game.from_snapshot(rehash(saved), registry())
        with self.assertRaises(UnknownDeckFacts):
            self.query(restored)

    def test_host_query_does_not_require_unrelated_class_identity_metadata(self):
        g = self.match(native=False)
        state = g.state
        # Host-only query probe. This is not a separately legal constructed deck.
        state.players[1].original_deck = ('spell.no_meta', 'minion.no_meta')
        self.assertTrue(matches_deck_condition(state, g.registry, 1, CONDITION))
        with self.assertRaises(UnknownDeckFacts):
            matches_deck_condition(state, g.registry, 1, DeckCondition('starting'))

    def test_unknown_later_definition_is_not_short_circuited_after_a_failed_spell(self):
        g = self.match(native=False)
        state = g.state
        state.players[1].original_deck = ('spell.fire', 'unknown.not.implemented')
        with self.assertRaises(UnsupportedDefinitionError):
            matches_deck_condition(state, g.registry, 1, CONDITION)

    def test_queries_leave_rng_state_events_history_and_actions_unchanged(self):
        g = self.match()
        before = g.snapshot()
        for player in (1, 2):
            for school in SpellSchool:
                self.query(g, player, school)
        self.assertEqual(g.snapshot(), before)

    def test_full_mulligan_and_coin_do_not_change_original_school_facts(self):
        g = self.match(finish=False)
        original = g.state.players[1].original_deck
        restored = self.check(g)
        for game in (g, restored):
            self.choose(game, tuple(o.id for o in game.state.pending_choice.options))
            self.choose(game, tuple(o.id for o in game.state.pending_choice.options))
            self.assertEqual(game.state.players[1].original_deck, original)
            self.assertTrue(self.query(game))
            self.assertIn('coin', [game.state.entities[i].card_id for i in game.state.players[2].hand])
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.check(g)

    def test_real_generated_different_school_does_not_rewrite_origin_or_power(self):
        g = self.match(extra=('fixture.prepare', 'tool.add.fire'))
        original = g.state.players[1].original_deck
        self.play(g, 'tool.add.fire')
        self.assertIn('spell.fire', [g.state.entities[i].card_id for i in g.state.players[1].deck])
        self.assertEqual(g.state.players[1].original_deck, original)
        self.assertTrue(self.query(g))
        self.assertEqual(self.power(g).card_id, POWER)
        self.check(g)

    def test_real_current_deck_clear_does_not_make_a_failed_origin_pass(self):
        g = self.match(('spell.fire',), extra=('fixture.prepare', 'tool.clear'))
        self.play(g, 'tool.clear')
        self.assertEqual(g.state.players[1].deck, [])
        self.assertFalse(self.query(g))
        self.assertEqual(self.power(g).card_id, 'priest.power')
        self.check(g)

    def test_real_draw_and_normal_turns_keep_original_facts(self):
        g = self.match(extra=('fixture.prepare', 'tool.draw'))
        original = g.state.players[1].original_deck
        self.play(g, 'tool.draw')
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.assertEqual(g.state.players[1].original_deck, original)
        self.assertTrue(self.query(g))
        self.check(g)

    def test_native_before_deal_replaces_once_before_any_offered_hand(self):
        g = self.match(finish=False)
        kinds = [e.kind for e in g.events]
        self.assertLess(kinds.index('opening_effect'), kinds.index('opening_hand_dealt'))
        self.assertLess(kinds.index('hero_power_replaced'), kinds.index('opening_hand_dealt'))
        self.assertEqual(kinds.count('hero_power_replaced'), 1)
        self.assertEqual(self.power(g).zone, Zone.HERO_POWER)
        old = next(e for e in g.state.entities.values() if e.controller == 1 and e.card_id == 'priest.power')
        self.assertEqual(old.zone, Zone.GRAVEYARD)
        self.check(g)

    def test_native_second_player_can_be_first_and_both_hooks_use_their_own_decks(self):
        g = self.match(first=2, second_spells=('spell.shadow',), second_native=True)
        self.assertEqual(g.state.active_player, 2)
        self.assertEqual([self.power(g, p).card_id for p in (1, 2)], [POWER, POWER])
        self.assertEqual([e.player_id for e in g.events if e.kind == 'opening_effect'], [2, 1])
        self.check(g)

    def test_native_mind_spike_uses_original_targeted_damage_and_pays_two_once(self):
        g = self.match()
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        enemy = g.state.players[2].hero_id
        before = g.state.entities[enemy].health
        power = self.power(g)
        g.apply(UseHeroPower(1, power.id, enemy))
        self.assertEqual((g.state.entities[enemy].health, g.state.players[1].mana), (before - 2, 0))
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn, 1)
        self.assertEqual(len(g.state.hero_power_history), 1)
        self.assertTrue(g.state.hero_power_history[0].completed)
        self.check(g)

    def test_player_command_can_target_with_installed_real_power(self):
        g = self.match()
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        port = g.for_player(1)
        dto = port.legal_actions()
        action = next(a for a in dto['actions'] if a['type'] == 'use_hero_power')
        before = sum(g.state.entities[g.state.players[p].hero_id].health for p in (1, 2))
        result = port.submit({'revision': dto['revision'], 'action': action})
        self.assertTrue(result['accepted'])
        self.assertEqual(sum(g.state.entities[g.state.players[p].hero_id].health for p in (1, 2)), before - 2)
        self.assertEqual(g.state.players[1].mana, 0)
        self.check(g)

    def test_normal_native_play_does_not_reexecute_start_of_game_hook(self):
        g = self.match(extra=('fixture.prepare', 'tool.fetch.native', 'tool.replace.power'))
        self.play(g, 'tool.fetch.native')
        self.play(g, 'tool.replace.power')
        identity = self.play(g, NATIVE)
        entity = g.state.entities[identity]
        self.assertEqual((entity.attack, entity.health, self.power(g).card_id), (5, 6, 'priest.power'))
        self.assertEqual(sum(e.kind == 'opening_effect' for e in g.events), 2)
        self.check(g)

    def test_silence_and_bounce_of_native_source_do_not_restore_old_power(self):
        g = self.match(extra=('fixture.prepare', 'tool.fetch.native', 'tool.silence.native', 'tool.bounce.native'))
        self.play(g, 'tool.fetch.native')
        identity = self.play(g, NATIVE)
        self.play(g, 'tool.silence.native')
        self.play(g, 'tool.bounce.native')
        self.assertEqual(g.state.entities[identity].zone, Zone.HAND)
        self.assertEqual(self.power(g).card_id, POWER)
        self.check(g)

    def test_unexecuted_new_condition_restores_before_deal_then_runs_normally(self):
        g = self.match(extra=('fixture.wait.before',), finish=False)
        self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.EFFECT)
        self.assertIsNotNone(self.nested(g.snapshot()['resolution_frame'], 'DeckSpellSchoolCondition'))
        restored, cloned = self.check(g), g.clone()
        for game in (g, restored, cloned):
            self.finish(game)
            self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 3)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(g.snapshot(), cloned.snapshot())
        self.check(g)

    def test_after_mulligan_selected_opening_branch_restores_and_keeps_first_turn_pending(self):
        g = self.match(extra=('fixture.wait.after',), finish=False)
        self.choose(g)
        self.choose(g)
        self.assertEqual((g.state.opening.stage, g.state.pending_choice.purpose), ('starting', ChoicePurpose.EFFECT))
        restored = self.check(g)
        self.choose(g)
        self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual((g.state.entities[g.state.players[1].hero_id].armor, g.state.opening.stage), (3, 'complete'))
        self.check(g)

    def test_waiting_condition_before_branch_restores_and_continues_after_play(self):
        g = self.match(extra=('fixture.prepare', 'tool.wait'))
        self.play(g, 'tool.wait')
        restored = self.check(g)
        self.choose(g)
        self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 3)
        self.check(g)

    def test_selected_success_branch_can_add_fire_after_wait_without_changing_origin(self):
        g = self.match(extra=('fixture.prepare', 'tool.selected'))
        self.play(g, 'tool.selected')
        restored = self.check(g)
        self.choose(g)
        self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertTrue(self.query(g))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 3)
        self.assertIn('spell.fire', [g.state.entities[i].card_id for i in g.state.players[1].deck])
        self.check(g)

    def test_selected_failure_branch_can_clear_current_deck_after_wait(self):
        g = self.match(('spell.fire',), extra=('fixture.prepare', 'tool.selected'))
        self.play(g, 'tool.selected')
        restored = self.check(g)
        self.choose(g)
        self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertFalse(self.query(g))
        self.assertEqual((g.state.entities[g.state.players[1].hero_id].armor, g.state.players[1].deck), (1, []))
        self.check(g)

    def test_late_action_failure_rolls_back_original_branch_and_entire_play(self):
        g = self.match(extra=('fixture.prepare', 'tool.fail'))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'tool.fail')
        self.assertEqual(g.snapshot(), before)
        self.check(g)

    def test_waiting_failure_rolls_back_to_original_choice_and_branch(self):
        g = self.match(extra=('fixture.prepare', 'tool.wait.fail'))
        self.play(g, 'tool.wait.fail')
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g)
        self.assertEqual(g.snapshot(), before)
        self.check(g)

    def test_opening_choice_failure_rolls_back_before_deal_without_faking_mulligan(self):
        g = self.match(extra=('fixture.wait.fail',), finish=False)
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.EFFECT)
        self.check(g)

    def test_typed_school_payload_and_both_original_declarations_roundtrip(self):
        g = self.match()
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        for declaration, fields in ((CONDITION, {'spell_school', 'scope'}),
            (DeckCondition('starting'), {'scope', 'predicate'}), (DeckCostCondition(4, 'local'), {'cost', 'cost_basis', 'scope'})):
            wire = codec.encode(declaration)
            self.assertEqual(codec.decode(wire), declaration)
            self.assertEqual(set(wire['fields']), fields)
            for field in fields:
                bad = deepcopy(wire)
                del bad['fields'][field]
                with self.assertRaises(ValueError):
                    codec.decode(bad)

    def test_declaration_requires_exact_enum_starting_scope_and_immutable_value(self):
        for school in ('shadow', None, True, 7, (), ['shadow']):
            with self.subTest(school=school), self.assertRaises(ValueError):
                DeckSpellSchoolCondition(school)
        for scope in ('current', '', None, True):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                DeckSpellSchoolCondition(SpellSchool.SHADOW, scope)
        with self.assertRaises(FrozenInstanceError):
            CONDITION.scope = 'current'
        with self.assertRaises(ValueError):
            DeckCondition('starting', 'all_spells_school')

    def test_waiting_payload_rejects_school_scope_extra_fields_and_boolean_player(self):
        g = self.match(extra=('fixture.wait.before',), finish=False)
        for field, value in (('spell_school', 'shadow'), ('spell_school', None), ('scope', 'current'), ('invented', 1)):
            saved = g.snapshot()
            self.nested(saved['resolution_frame'], 'DeckSpellSchoolCondition')['fields'][field] = value
            self.reject(saved)
        saved = g.snapshot()
        self.nested(saved['resolution_frame'], 'CheckDeckCondition')['fields']['player_id'] = True
        self.reject(saved)

    def test_constructed_original_deck_tampering_is_rejected_by_existing_boundary(self):
        g = self.match()
        saved = g.snapshot()
        saved['state']['players']['1']['original_deck'][0] = 'spell.fire'
        self.reject(saved)

    def test_player_views_hide_deck_school_inventory_and_condition_frames(self):
        g = self.match(native=False, extra=('fixture.wait.before',), finish=False)
        for viewer in (1, 2):
            text = json.dumps(g.observe(viewer)) + json.dumps(g.player_events(viewer)) + json.dumps(g.for_player(viewer).legal_actions())
            for private in ('DeckSpellSchoolCondition', 'spell.shadow', 'original_deck', 'on_match', 'on_miss', 'resolution_frame'):
                self.assertNotIn(private, text)
        self.check(g)

    def test_layout_schema_and_previous_payloads_remain_while_handler_advances(self):
        g = self.match()
        self.assertEqual((g.snapshot()['schema_version'], g.ruleset.id, g.mechanics.version),
            (265, 'prototype-v302', CORE_EFFECTS_VERSION))
        saved = g.snapshot()
        saved['mechanics_version']['version'] = 'core-effects-v230'
        self.reject(saved)
        self.check(g)


if __name__ == '__main__':
    unittest.main()
