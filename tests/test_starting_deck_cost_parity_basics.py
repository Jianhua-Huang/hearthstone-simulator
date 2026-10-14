"""Starting printed-cost parity on original facts and one independent Genn adapter."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CheckDeckCondition, ChoicePurpose,
    CostSpec, DeckCondition, DeckSpec, EndTurn, Game, MatchSetup, OpeningHook, PlayCard,
    PlayerSetup, Rarity, ResolutionError, Scenario, SelectChoice, SnapshotError, UnknownDeckFacts,
    UseHeroPower, Zone, matches_deck_condition)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import local_cost, quote_cost
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChangeManaCrystals, ChoiceOption,
    Destroy, Draw, GainArmor, InvokeBehavior, ModifyCost, ReplaceHeroPower, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.zones import AddToDeck, CardReference, DestroyDeckMatching, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry
from test_current_deck_empty_basics import rehash
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE = 'GIL_692'
EVEN = DeckCondition('starting', 'all_even_cost')
ODD = DeckCondition('starting', 'all_odd_cost')
SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/starting-deck-cost-parity-basics.json'
PIN = 'bd6bd2dedd2e3d8b3dcbe606e5e119b57e9be917920bcc284bd4c64631a64f3d'


def evidence():
    packet = json.loads(SUPPORT.read_bytes())
    if canonical_digest(packet) != PIN or [r['id'] for r in packet['records']] != [NATIVE, 'GIL_826', 'CORE_GIL_692', 'CORE_GIL_826']:
        raise ValueError('Complete native starting parity source changed')
    for row in packet['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Complete original card row changed')
    return {r['id']: r['data'] for r in packet['records']}


def pause(player):
    return RequestChoice(player, (ChoiceOption('ok', 'OK', ()),))


def branch(player, odd=False):
    return CheckDeckCondition(player, ODD if odd else EVEN, (GainArmor(player, 3),), (GainArmor(player, 1),))


def registry():
    r = opening_registry()
    raw = evidence()
    r.register_behavior('parity.native.start', lambda c: (CheckDeckCondition(c.player_id, EVEN,
        (ModifyCost(c.state.players[c.player_id].hero_power_id, CostSpec(set_to=1, card_types=(CardType.HERO_POWER,)), c.source_id),)),))
    row = raw[NATIVE]
    r.register_card(CardDefinition(NATIVE, row['name'], CardType.MINION, cost=row['cost'],
        attack=row['attack'], health=row['health'], metadata=metadata_from_record(row),
        opening_hooks=(OpeningHook('before_deal', 'parity.native.start'),)))
    for i in range(1, 31):
        for name, cost in (('even', 2), ('odd', 3)):
            r.register_card(CardDefinition(f'{name}.{i}', 'Explicit experimental parity minion',
                CardType.MINION, cost=cost, health=2, metadata=metadata()))
    r.register_behavior('parity.nop', lambda c: ())
    for name, kind, cost, fields in (
        ('zero.spell', CardType.SPELL, 0, {}),
        ('even.spell', CardType.SPELL, 4, {}),
        ('odd.spell', CardType.SPELL, 3, {}),
        ('even.weapon', CardType.WEAPON, 2, dict(attack=1, durability=1)),
        ('even.location', CardType.LOCATION, 2, dict(durability=1, on_use='parity.nop')),
        ('even.hero', CardType.HERO, 4, dict(health=30, hero_card=True, initial_hero_power='mage.power', on_play='parity.nop')),
        ('large.odd', CardType.SPELL, 101, {}),
        ('large.even', CardType.SPELL, 100, {}),
    ):
        r.register_card(CardDefinition(name, 'Explicit experimental parity card', kind, cost=cost,
            metadata=metadata(CardClass.MAGE if kind == CardType.HERO else CardClass.NEUTRAL), **fields))
    r.register_card(CardDefinition('no.meta.even', 'Typed even card without class facts', CardType.MINION, cost=2, health=1))

    def prepare(c):
        return (ChangeManaCrystals(c.player_id, 9),
            *(AddToHand(c.player_id, cid) for cid in c.state.players[c.player_id].original_deck
              if cid.startswith(('tool.', 'oddtool.'))))

    def fail(c):
        raise ResolutionError('Expected parity continuation failure')

    def board_native(c):
        return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == NATIVE)

    def fetch_native(c):
        source = c.state.opening.original_entities[c.player_id - 1][0]
        entity = c.state.entities[source]
        return () if entity.zone == Zone.HAND else (MoveCard(CardReference.capture(entity), c.player_id, Zone.HAND),)

    r.register_behavior('parity.prepare', prepare)
    r.register_behavior('parity.fail', fail)
    for name, cost in (('fixture.prepare', 0), ('fixture.odd.prepare', 1)):
        r.register_card(CardDefinition(name, name, CardType.MINION, cost=cost, health=1,
            opening_hooks=(OpeningHook('after_mulligan', 'parity.prepare'),), metadata=metadata()))
    scripts = {
        'tool.set.local': lambda c: (ModifyCost(c.state.players[c.player_id].deck[0], CostSpec(set_to=1), c.source_id),),
        'tool.external': lambda c: (AddCostModifier(c.player_id, CostSpec(set_to=1), c.source_id),),
        'tool.add.odd': lambda c: (AddToDeck(c.player_id, 'odd.spell'),),
        'tool.clear': lambda c: (DestroyDeckMatching(c.player_id, count=40, reveal=False),),
        'tool.draw': lambda c: (Draw(c.player_id),),
        'tool.wait': lambda c: (pause(c.player_id), branch(c.player_id)),
        'oddtool.wait': lambda c: (pause(c.player_id), branch(c.player_id, True)),
        'tool.selected': lambda c: (CheckDeckCondition(c.player_id, EVEN,
            (pause(c.player_id), AddToDeck(c.player_id, 'odd.spell'), GainArmor(c.player_id, 3)),
            (pause(c.player_id), DestroyDeckMatching(c.player_id, count=40, reveal=False), GainArmor(c.player_id, 1))),),
        'tool.fail': lambda c: (branch(c.player_id), InvokeBehavior('parity.fail', c.source_id, c.player_id)),
        'tool.wait.fail': lambda c: (pause(c.player_id), branch(c.player_id), InvokeBehavior('parity.fail', c.source_id, c.player_id)),
        'tool.fetch': fetch_native,
        'tool.silence': lambda c: (Silence(board_native(c)),),
        'tool.bounce': lambda c: (ReturnToHand(board_native(c)),),
        'tool.kill': lambda c: (Destroy(board_native(c)),),
        'tool.replace.power': lambda c: (ReplaceHeroPower(c.player_id, 'mage.power', source_id=c.source_id),),
    }
    for cid, fn in scripts.items():
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1 if cid.startswith('oddtool.') else 0,
            health=1, battlecry=cid, metadata=metadata()))
    for name, cost, odd in (('fixture.wait', 0, False), ('fixture.odd.wait', 1, True)):
        r.register_behavior(name, lambda c, odd=odd: (pause(c.player_id), branch(c.player_id, odd)))
        r.register_card(CardDefinition(name, name, CardType.MINION, cost=cost, health=1,
            opening_hooks=(OpeningHook('before_deal', name),), metadata=metadata()))
    return r


class StartingDeckCostParityTests(unittest.TestCase):
    def match(self, mode='even', *, extra=(), native=True, other_mode='odd', other_native=False,
              first=1, finish=True):
        r = registry()
        def cards(mode, prefix):
            return tuple(prefix) + tuple(f'{mode}.{i}' for i in range(1, 31 - len(prefix)))
        own = cards(mode, ((NATIVE,) if native else ()) + tuple(extra))
        other = cards(other_mode, (NATIVE,) if other_native else ())
        setup = MatchSetup((DeckSpec('mage.hero', 'mage.power', CardClass.MAGE, own),
            DeckSpec('warrior.hero', 'warrior.power', CardClass.WARRIOR, other)), policy(r), 'coin', 84, first)
        g = Game.from_decks(setup, r)
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

    def query(self, g, player=1, odd=False):
        return matches_deck_condition(g.state, g.registry, player, ODD if odd else EVEN)

    def power(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_power_id]

    def armor(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].armor

    def play(self, g, cid):
        player = g.state.active_player
        identity = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(player, identity))
        return identity

    def portable(self, g):
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

    def test_full_raw_pin_genn_complete_definition_and_baku_core_raw_only(self):
        r, raw = registry(), evidence()
        card = r.card(NATIVE)
        self.assertEqual((card.cost, card.attack, card.health, card.metadata.classes, card.metadata.rarity),
            (6, 6, 5, (CardClass.NEUTRAL,), Rarity.LEGENDARY))
        self.assertEqual(card.metadata, metadata_from_record(raw[NATIVE]))
        self.assertNotIn('CARDRACE', raw[NATIVE]['tags'])
        self.assertIsNone(card.battlecry)
        self.assertEqual(card.opening_hooks, (OpeningHook('before_deal', 'parity.native.start'),))
        self.assertIn('starting', raw[NATIVE]['text_en'])
        self.assertTrue(all(cid not in r.cards for cid in raw if cid != NATIVE))

    def test_all_even_and_all_odd_are_distinct_origin_conditions(self):
        for mode, want in (('even', False), ('odd', True)):
            with self.subTest(mode=mode):
                g = self.match(mode, native=False)
                self.assertEqual(self.query(g, odd=True), want)
                self.assertEqual(self.query(g), not want)

    def test_all_legal_deck_card_kinds_and_zero_cost_count(self):
        g = self.match(extra=('zero.spell', 'even.spell', 'even.weapon', 'even.location', 'even.hero'))
        self.assertTrue(self.query(g))
        self.assertFalse(self.query(g, odd=True))
        self.assertEqual(local_cost(self.power(g))[0], 1)

    def test_duplicate_printed_costs_do_not_require_unique_card_identity(self):
        g = self.match(extra=('even.spell', 'even.spell'))
        self.assertTrue(self.query(g))
        self.assertFalse(matches_deck_condition(g.state, g.registry, 1, DeckCondition('starting')))

    def test_one_wrong_parity_of_any_deck_type_is_enough_to_fail(self):
        for cid in ('odd.30', 'odd.spell'):
            with self.subTest(card=cid):
                g = self.match(extra=(cid,))
                self.assertFalse(self.query(g))
                self.assertEqual(local_cost(self.power(g))[0], 2)

    def test_large_nonnegative_printed_costs_are_not_a_mana_cap_filter(self):
        even = self.match(extra=('large.even',))
        odd = self.match('odd', native=False, extra=('large.odd',))
        self.assertTrue(self.query(even))
        self.assertTrue(self.query(odd, odd=True))

    def test_requested_player_uses_own_constructed_origin(self):
        g = self.match()
        self.assertTrue(self.query(g, 1))
        self.assertFalse(self.query(g, 1, True))
        self.assertFalse(self.query(g, 2))
        self.assertTrue(self.query(g, 2, True))

    def test_scenario_current_cards_cannot_substitute_starting_facts(self):
        for cards in ((), ('even.1',), ('odd.1',)):
            with self.subTest(cards=cards):
                g = Game.from_scenario(Scenario((PlayerSetup('mage.hero', deck=cards), PlayerSetup('warrior.hero'))), registry())
                for condition in (EVEN, ODD):
                    with self.assertRaises(UnknownDeckFacts):
                        matches_deck_condition(g.state, g.registry, 1, condition)

    def test_forged_scenario_original_tuple_does_not_supply_an_opening(self):
        g = Game.from_scenario(Scenario((PlayerSetup('mage.hero'), PlayerSetup('warrior.hero'))), registry())
        saved = g.snapshot()
        saved['state']['players']['1']['original_deck'] = ['even.1']
        restored = Game.from_snapshot(rehash(saved), registry())
        with self.assertRaises(UnknownDeckFacts):
            self.query(restored)

    def test_host_cost_query_needs_no_unrelated_identity_metadata(self):
        g = self.match(native=False)
        state = g.state
        # Host operand probe, not a claim that unknown-class construction is legal.
        state.players[1].original_deck = ('no.meta.even',)
        self.assertTrue(matches_deck_condition(state, g.registry, 1, EVEN))
        with self.assertRaises(UnknownDeckFacts):
            matches_deck_condition(state, g.registry, 1, DeckCondition('starting'))

    def test_known_wrong_parity_does_not_short_circuit_later_unknown_definition(self):
        g = self.match(native=False)
        state = g.state
        state.players[1].original_deck = ('odd.1', 'unknown.not.implemented')
        with self.assertRaises(UnsupportedDefinitionError):
            matches_deck_condition(state, g.registry, 1, EVEN)

    def test_pure_queries_do_not_change_rng_events_history_or_action(self):
        g = self.match()
        before = g.snapshot()
        for player in (1, 2):
            self.query(g, player)
            self.query(g, player, True)
        self.assertEqual(g.snapshot(), before)

    def test_full_mulligan_and_coin_do_not_change_original_parity(self):
        g = self.match(finish=False)
        original = g.state.players[1].original_deck
        restored = self.portable(g)
        for game in (g, restored):
            self.choose(game, tuple(o.id for o in game.state.pending_choice.options))
            self.choose(game, tuple(o.id for o in game.state.pending_choice.options))
            self.assertEqual(game.state.players[1].original_deck, original)
            self.assertTrue(self.query(game))
        self.assertEqual(g.snapshot(), restored.snapshot())

    def test_real_local_fee_change_does_not_change_original_printed_parity(self):
        g = self.match(extra=('fixture.prepare', 'tool.set.local'))
        identity = g.state.players[1].deck[0]
        self.assertEqual(g.registry.card(g.state.entities[identity].card_id).cost % 2, 0)
        self.play(g, 'tool.set.local')
        self.assertEqual(local_cost(g.state.entities[identity])[0], 1)
        self.assertTrue(self.query(g))

    def test_external_hypothetical_hand_quote_does_not_replace_original_printed_costs(self):
        g = self.match(extra=('fixture.prepare', 'tool.external'))
        self.play(g, 'tool.external')
        identity = g.state.players[1].deck[0]
        state = g.state
        self.assertEqual(quote_cost(state, g.registry, state.entities[identity]).amount, 1)
        self.assertEqual(g.registry.card(g.state.entities[identity].card_id).cost % 2, 0)
        self.assertTrue(self.query(g))

    def test_generated_odd_card_changes_current_deck_but_not_initial_even_condition(self):
        g = self.match(extra=('fixture.prepare', 'tool.add.odd'))
        original = g.state.players[1].original_deck
        self.play(g, 'tool.add.odd')
        self.assertIn('odd.spell', [g.state.entities[i].card_id for i in g.state.players[1].deck])
        self.assertEqual(g.state.players[1].original_deck, original)
        self.assertTrue(self.query(g))

    def test_clear_current_deck_does_not_make_wrong_origin_even(self):
        g = self.match(extra=('odd.spell', 'fixture.prepare', 'tool.clear'))
        self.play(g, 'tool.clear')
        self.assertEqual(g.state.players[1].deck, [])
        self.assertFalse(self.query(g))

    def test_real_draw_and_normal_turns_preserve_original_costs(self):
        g = self.match(extra=('fixture.prepare', 'tool.draw'))
        original = g.state.players[1].original_deck
        self.play(g, 'tool.draw')
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.assertEqual(g.state.players[1].original_deck, original)
        self.assertTrue(self.query(g))

    def test_native_attaches_cost_to_same_initial_physical_power_before_deal(self):
        g = self.match(finish=False)
        power = self.power(g)
        self.assertEqual((power.card_id, power.base_cost, local_cost(power)[0]), ('mage.power', 2, 1))
        self.assertEqual(sum(e.card_id == 'mage.power' for e in g.state.entities.values()), 1)
        kinds = [e.kind for e in g.events]
        self.assertLess(kinds.index('opening_effect'), kinds.index('opening_hand_dealt'))
        self.assertNotIn('hero_power_replaced', kinds)

    def test_second_player_first_and_both_independent_even_origins(self):
        g = self.match(other_mode='even', other_native=True, first=2)
        self.assertEqual(g.state.active_player, 2)
        self.assertEqual([local_cost(self.power(g, p))[0] for p in (1, 2)], [1, 1])
        self.assertEqual([e.player_id for e in g.events if e.kind == 'opening_effect'], [2, 1])

    def test_native_first_turn_uses_one_mana_once_and_replay_continues_next_turn(self):
        g = self.match()
        power = self.power(g)
        enemy = g.state.players[2].hero_id
        hp = g.state.entities[enemy].health
        g.apply(UseHeroPower(1, power.id))
        self.assertEqual((g.state.players[1].mana, g.state.entities[enemy].health), (0, hp - 1))
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn, 1)
        restored = self.portable(g)
        for game in (g, restored):
            game.apply(EndTurn(1))
            game.apply(EndTurn(2))
            game.apply(UseHeroPower(1, self.power(game).id))
            self.assertEqual(game.state.players[1].mana, 1)
        self.assertEqual(g.snapshot(), restored.snapshot())

    def test_player_command_can_use_one_cost_initial_skill(self):
        g = self.match()
        port = g.for_player(1)
        dto = port.legal_actions()
        action = next(a for a in dto['actions'] if a['type'] == 'use_hero_power')
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        self.assertEqual((g.state.players[1].mana, g.state.players[1].hero_power_uses_this_turn), (0, 1))

    def test_normal_native_play_silence_and_bounce_do_not_remove_power_cost(self):
        g = self.match(extra=('fixture.prepare', 'tool.fetch', 'tool.silence', 'tool.bounce'))
        self.play(g, 'tool.fetch')
        identity = self.play(g, NATIVE)
        self.assertEqual(identity, g.state.opening.original_entities[0][0])
        self.assertEqual((g.state.entities[identity].attack, g.state.entities[identity].health), (6, 5))
        self.play(g, 'tool.silence')
        self.play(g, 'tool.bounce')
        self.assertEqual(g.state.entities[identity].zone, Zone.HAND)
        self.assertEqual(local_cost(self.power(g))[0], 1)
        self.assertEqual(len(self.power(g).enchantments), 1)

    def test_death_of_actual_opening_source_does_not_revoke_power_cost(self):
        g = self.match(extra=('fixture.prepare', 'tool.fetch', 'tool.kill'))
        self.play(g, 'tool.fetch')
        identity = self.play(g, NATIVE)
        self.assertEqual(identity, g.state.opening.original_entities[0][0])
        self.play(g, 'tool.kill')
        self.assertEqual(g.state.entities[identity].zone, Zone.GRAVEYARD)
        self.assertEqual(local_cost(self.power(g))[0], 1)

    def test_later_same_card_id_power_replacement_gets_its_new_ordinary_cost(self):
        g = self.match(extra=('fixture.prepare', 'tool.replace.power'))
        original = self.power(g)
        self.play(g, 'tool.replace.power')
        new = self.power(g)
        self.assertNotEqual(new.id, original.id)
        self.assertEqual((new.card_id, new.base_cost, local_cost(new)[0]), ('mage.power', 2, 2))
        self.assertEqual(g.state.entities[original.id].zone, Zone.GRAVEYARD)

    def test_before_deal_waiting_new_predicate_restores_then_both_variants_continue(self):
        for mode, extra, odd in (('even', 'fixture.wait', False), ('odd', 'fixture.odd.wait', True)):
            with self.subTest(mode=mode):
                g = self.match(mode, native=False, extra=(extra,), finish=False)
                self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.EFFECT)
                payload = self.nested(g.snapshot()['resolution_frame'], 'DeckCondition')
                self.assertEqual(payload['fields']['predicate'], ODD.predicate if odd else EVEN.predicate)
                restored = self.portable(g)
                for game in (g, restored):
                    self.finish(game)
                    self.assertEqual(self.armor(game), 3)
                self.assertEqual(g.snapshot(), restored.snapshot())

    def test_unexecuted_condition_in_actual_play_can_resume_for_even_and_odd(self):
        for mode, prepare, tool, odd in (('even', 'fixture.prepare', 'tool.wait', False),
            ('odd', 'fixture.odd.prepare', 'oddtool.wait', True)):
            with self.subTest(mode=mode):
                g = self.match(mode, native=False, extra=(prepare, tool))
                self.play(g, tool)
                restored = self.portable(g)
                self.choose(g)
                self.choose(restored)
                self.assertEqual(g.snapshot(), restored.snapshot())
                self.assertEqual(self.armor(g), 3)
                self.assertTrue(self.query(g, odd=odd))

    def test_selected_success_and_failure_branches_keep_original_facts_after_wait(self):
        for bad, armor in ((False, 3), (True, 1)):
            with self.subTest(failed_origin=bad):
                g = self.match(extra=('fixture.prepare', 'tool.selected') + (('odd.spell',) if bad else ()))
                self.play(g, 'tool.selected')
                restored = self.portable(g)
                self.choose(g)
                self.choose(restored)
                self.assertEqual(g.snapshot(), restored.snapshot())
                self.assertEqual(self.armor(g), armor)
                self.assertEqual(self.query(g), not bad)

    def test_action_failure_restores_branch_payment_and_original_facts(self):
        g = self.match(extra=('fixture.prepare', 'tool.fail'))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'tool.fail')
        self.assertEqual(g.snapshot(), before)

    def test_waiting_failure_restores_original_choice_and_unexecuted_predicate(self):
        g = self.match(extra=('fixture.prepare', 'tool.wait.fail'))
        self.play(g, 'tool.wait.fail')
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g)
        self.assertEqual(g.snapshot(), before)
        self.portable(g)

    def test_original_two_field_payload_roundtrips_both_new_values(self):
        g = self.match()
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        for declaration in (EVEN, ODD, DeckCondition(), DeckCondition('current', 'empty')):
            wire = codec.encode(declaration)
            self.assertEqual(set(wire['fields']), {'scope', 'predicate'})
            self.assertEqual(codec.decode(wire), declaration)
            for field in ('scope', 'predicate'):
                bad = deepcopy(wire)
                del bad['fields'][field]
                with self.assertRaises(ValueError):
                    codec.decode(bad)

    def test_parity_values_are_finite_and_starting_only(self):
        for predicate in ('all_even_cost', 'all_odd_cost'):
            with self.assertRaises(ValueError):
                DeckCondition('current', predicate)
        for predicate in ('all_even', 'all_odd', 'even', 'cost % 2', True, None):
            with self.subTest(value=predicate), self.assertRaises(ValueError):
                DeckCondition('starting', predicate)

    def test_waiting_wire_rejects_wrong_scope_unknown_predicate_and_extra_field(self):
        g = self.match(native=False, extra=('fixture.wait',), finish=False)
        for field, value in (('scope', 'current'), ('predicate', 'guess'), ('predicate', True), ('invented', 1)):
            saved = g.snapshot()
            self.nested(saved['resolution_frame'], 'DeckCondition')['fields'][field] = value
            self.reject(saved)

    def test_rehashed_original_deck_tampering_is_rejected_by_existing_opening_boundary(self):
        g = self.match()
        saved = g.snapshot()
        saved['state']['players']['1']['original_deck'][0] = 'odd.spell'
        self.reject(saved)

    def test_private_deck_parity_and_frames_do_not_enter_player_projections(self):
        g = self.match(native=False, extra=('fixture.wait',), finish=False)
        for viewer in (1, 2):
            text = json.dumps(g.observe(viewer)) + json.dumps(g.player_events(viewer)) + json.dumps(g.for_player(viewer).legal_actions())
            for private in ('all_even_cost', 'all_odd_cost', 'original_deck', 'resolution_frame', 'even.1', 'odd.1'):
                self.assertNotIn(private, text)

    def test_original_wire_layout_stays_and_previous_handler_is_rejected(self):
        g = self.match()
        self.assertEqual((g.snapshot()['schema_version'], g.ruleset.id, g.mechanics.version),
            (266, 'prototype-v302', CORE_EFFECTS_VERSION))
        saved = g.snapshot()
        saved['mechanics_version']['version'] = 'core-effects-v231'
        self.reject(saved)


if __name__ == '__main__':
    unittest.main()
