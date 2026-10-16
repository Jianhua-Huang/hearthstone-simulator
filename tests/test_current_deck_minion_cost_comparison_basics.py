"""Current-deck strict minion cost comparisons and one isolated DrekThar source."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CheckDeckCondition, CostSpec,
    DeckCondition, DeckCostCondition, DeckMinionCostCondition, DeckSpec, EndTurn, Game,
    MatchSetup, PlayCard, PlayerSetup, Rarity, ResolutionError, Scenario, SelectChoice,
    SnapshotError, SpellSchool, DeckSpellSchoolCondition, SummonFromZone, UnknownDeckFacts,
    matches_deck_condition)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import local_cost, quote_cost
from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Draw, GainArmor,
    InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.zones import AddToDeck, CardReference, DestroyDeckMatching
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry
from test_current_deck_empty_basics import rehash
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE = 'AV_100'
SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/current-deck-minion-cost-comparison-basics.json'
PIN = '8ea908995e88f9ed4455178df4bb362e4233bfd8a97e8dd49e19d8f514c1b3a5'
LESS = DeckMinionCostCondition(4, 'less', 'local')


def evidence():
    packet = json.loads(SUPPORT.read_bytes())
    if canonical_digest(packet) != PIN or [r['id'] for r in packet['records']] != [NATIVE, 'AV_223']:
        raise ValueError('Complete minion comparison evidence changed')
    for row in packet['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Complete card row changed')
    return {row['id']: row['data'] for row in packet['records']}


def pause(player):
    return RequestChoice(player, (ChoiceOption('ok', 'Continue', ()),))


def branch(player, comparison='less'):
    return CheckDeckCondition(player, DeckMinionCostCondition(4, comparison, 'local'),
        (GainArmor(player, 3),), (GainArmor(player, 1),))


def first_ref(c):
    return CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]])


def set_first(c, cost):
    return ModifyCost(c.state.players[c.player_id].deck[0], CostSpec(set_to=cost), source_id=c.source_id)


def registry():
    r = opening_registry()
    raw = evidence()[NATIVE]
    def native(c):
        cost = local_cost(c.state.entities[c.source_id])[0]
        return (CheckDeckCondition(c.player_id, DeckMinionCostCondition(cost, 'less', 'local'),
            (SummonFromZone(c.player_id, count=1, source_id=c.source_id),)),)
    r.register_behavior('cmp.native', native)
    r.register_card(CardDefinition(NATIVE, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], battlecry='cmp.native', metadata=metadata_from_record(raw)))
    for cid, cost in (('cmp.zero', 0), ('cmp.low', 2), ('cmp.equal', 4), ('cmp.high', 5), ('cmp.large', 101)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=1, health=2, metadata=metadata()))
    r.register_card(CardDefinition('cmp.no.meta', 'Known minion without irrelevant class facts', CardType.MINION, cost=2, health=2))
    r.register_card(CardDefinition('cmp.spell', 'Excluded expensive Spell', CardType.SPELL, cost=20))
    r.register_card(CardDefinition('cmp.weapon', 'Excluded expensive Weapon', CardType.WEAPON, cost=20, attack=1, durability=1))
    r.register_card(CardDefinition('cmp.location', 'Excluded expensive Location', CardType.LOCATION, cost=20, durability=1, on_use='power'))
    r.register_card(CardDefinition('cmp.hero', 'Excluded Hero card', CardType.HERO, cost=20, health=30,
        hero_card=True, initial_hero_power='mage.power', on_play='power', metadata=metadata(CardClass.MAGE)))
    r.register_behavior('cmp.cry', lambda c: (GainArmor(c.player_id, 9),))
    r.register_card(CardDefinition('cmp.cry', 'Experimental recruited Battlecry', CardType.MINION, cost=2,
        attack=1, health=2, battlecry='cmp.cry', metadata=metadata()))
    native_board = lambda c: next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == NATIVE)
    def late_failure(c):
        raise ResolutionError('Expected late comparison failure')
    r.register_behavior('cmp.late.fail', late_failure)
    scripts = {
        'cmp.check': lambda c: (branch(c.player_id),),
        'cmp.set.low': lambda c: (set_first(c, 3),),
        'cmp.set.equal': lambda c: (set_first(c, 4),),
        'cmp.set.high': lambda c: (set_first(c, 5),),
        'cmp.set.zero': lambda c: (set_first(c, 0),),
        'cmp.external': lambda c: (AddCostModifier(c.player_id, CostSpec(set_to=0), uses_remaining=1),),
        'cmp.add': lambda c: (AddToDeck(c.player_id, 'cmp.high', cost=CostSpec(set_to=3)),),
        'cmp.draw': lambda c: (Draw(c.player_id),),
        'cmp.clear': lambda c: (DestroyDeckMatching(c.player_id, count=40, reveal=False),),
        'cmp.face': lambda c: (TransformCapturedMinion(first_ref(c), 'cmp.high'),),
        'cmp.wait.less': lambda c: (pause(c.player_id), set_first(c, 3), branch(c.player_id)),
        'cmp.wait.greater': lambda c: (pause(c.player_id), set_first(c, 5), branch(c.player_id, 'greater')),
        'cmp.selected.yes': lambda c: (CheckDeckCondition(c.player_id, LESS,
            (pause(c.player_id), set_first(c, 5), GainArmor(c.player_id, 3)), (GainArmor(c.player_id, 1),)),),
        'cmp.selected.no': lambda c: (CheckDeckCondition(c.player_id, LESS, (GainArmor(c.player_id, 3),),
            (pause(c.player_id), set_first(c, 3), GainArmor(c.player_id, 1))),),
        'cmp.fail': lambda c: (branch(c.player_id), InvokeBehavior('cmp.late.fail', c.source_id, c.player_id)),
        'cmp.wait.fail': lambda c: (pause(c.player_id), set_first(c, 3), branch(c.player_id),
            InvokeBehavior('cmp.late.fail', c.source_id, c.player_id)),
        'cmp.silence': lambda c: (Silence(native_board(c)),),
        'cmp.bounce': lambda c: (ReturnToHand(native_board(c)),),
        'cmp.discount.native': lambda c: (ModifyCost(next(i for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id == NATIVE), CostSpec(set_to=2), source_id=c.source_id),),
    }
    for cid, fn in scripts.items():
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata(CardClass.MAGE)))
    return r


class CurrentDeckMinionCostComparisonTests(unittest.TestCase):
    def game(self, hand=(NATIVE,), deck=(), *, other_hand=(), other_deck=(), board=()):
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero', hand=hand, deck=deck, board=board,
            hero_power_card_id='mage.power', mana=10, max_mana=10), PlayerSetup('warrior.hero',
            hand=other_hand, deck=other_deck, hero_power_card_id='warrior.power', mana=10, max_mana=10)), seed=84), registry())

    def query(self, g, comparison='less', cost=4, player=1):
        return matches_deck_condition(g.state, g.registry, player, DeckMinionCostCondition(cost, comparison, 'local'))

    def play(self, g, cid=NATIVE):
        player = g.state.active_player
        identity = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(player, identity))
        return identity

    def choose(self, g):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, ('ok',)))

    def armor(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].armor

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

    def test_full_raw_pin_and_complete_native_with_other_raw_only(self):
        r, raw = registry(), evidence()
        card = r.card(NATIVE)
        self.assertEqual((card.cost, card.attack, card.health, card.metadata.classes, card.metadata.rarity),
            (4, 4, 4, (CardClass.NEUTRAL,), Rarity.LEGENDARY))
        self.assertEqual(card.metadata, metadata_from_record(raw[NATIVE]))
        self.assertNotIn('CARDRACE', raw[NATIVE]['tags'])
        self.assertIn('summon one', raw[NATIVE]['text_en'])
        self.assertEqual(card.battlecry, 'cmp.native')
        self.assertNotIn('AV_223', r.cards)

    def test_less_greater_and_equality_are_strict_and_parameterized(self):
        for card, less, greater in (('cmp.low', True, False), ('cmp.equal', False, False), ('cmp.high', False, True)):
            g = self.game(deck=(card,))
            self.assertEqual((self.query(g), self.query(g, 'greater')), (less, greater))
            self.assertFalse(self.query(g, cost=g.registry.card(card).cost))

    def test_every_minion_participates_and_duplicates_are_physical(self):
        g = self.game(deck=('cmp.low', 'cmp.low', 'cmp.high'))
        self.assertFalse(self.query(g))
        self.assertFalse(self.query(g, 'greater'))
        self.assertTrue(self.query(g, cost=6))
        self.assertEqual(len(g.state.players[1].deck), 3)

    def test_non_minion_types_are_excluded_even_with_large_costs(self):
        g = self.game(deck=('cmp.low', 'cmp.spell', 'cmp.weapon', 'cmp.location', 'cmp.hero'))
        self.assertTrue(self.query(g))
        self.assertFalse(self.query(g, 'greater'))

    def test_empty_deck_and_no_minion_subset_use_explicit_universal_policy(self):
        for cards in ((), ('cmp.spell', 'cmp.weapon')):
            g = self.game(deck=cards)
            self.assertTrue(self.query(g))
            self.assertTrue(self.query(g, 'greater', 0))
            self.assertTrue(self.query(g, cost=0))

    def test_zero_and_large_costs_are_not_mana_cap_comparisons(self):
        g = self.game(deck=('cmp.zero',))
        self.assertFalse(self.query(g, cost=0))
        self.assertTrue(self.query(g, cost=1))
        g = self.game(deck=('cmp.large',))
        self.assertTrue(self.query(g, 'greater', 100))
        self.assertTrue(self.query(g, cost=102))

    def test_specified_player_reads_own_current_zone(self):
        g = self.game(deck=('cmp.low',), other_deck=('cmp.high',), other_hand=('cmp.low',), board=('cmp.high',))
        self.assertTrue(self.query(g))
        self.assertTrue(self.query(g, 'greater', player=2))
        self.assertFalse(self.query(g, player=2))

    def test_current_scenario_needs_no_original_deck_or_irrelevant_metadata(self):
        g = self.game(deck=('cmp.no.meta',))
        self.assertTrue(self.query(g))
        with self.assertRaises(UnknownDeckFacts):
            matches_deck_condition(g.state, g.registry, 1, DeckCondition('starting'))
        with self.assertRaises(UnknownDeckFacts):
            matches_deck_condition(g.state, g.registry, 1, DeckCondition())

    def test_earlier_known_failure_does_not_hide_unknown_later_card(self):
        g = self.game(deck=('cmp.high', 'cmp.low'))
        state = g.state
        state.entities[state.players[1].deck[-1]].card_id = 'unknown.comparison.card'
        with self.assertRaises(UnsupportedDefinitionError):
            matches_deck_condition(state, g.registry, 1, LESS)

    def test_query_is_pure_with_rng_and_external_cost_uses_preserved(self):
        g = self.game(('cmp.external',), deck=('cmp.low',))
        self.play(g, 'cmp.external')
        saved = g.snapshot()
        self.assertTrue(self.query(g))
        self.assertFalse(self.query(g, 'greater'))
        self.assertEqual(g.snapshot(), saved)

    def test_real_local_set_changes_comparison_without_changing_printed_cost(self):
        g = self.game(('cmp.set.equal', 'cmp.set.high', 'cmp.set.zero'), deck=('cmp.low',))
        identity = g.state.players[1].deck[0]
        for card, less, greater in (('cmp.set.equal', False, False), ('cmp.set.high', False, True), ('cmp.set.zero', True, False)):
            self.play(g, card)
            self.assertEqual((self.query(g), self.query(g, 'greater')), (less, greater))
        self.assertEqual(g.registry.card(g.state.entities[identity].card_id).cost, 2)
        self.assertEqual(local_cost(g.state.entities[identity])[0], 0)
        self.portable(g)

    def test_external_hypothetical_hand_quote_does_not_replace_local_deck_cost(self):
        g = self.game(('cmp.external',), deck=('cmp.high',))
        self.play(g, 'cmp.external')
        entity = g.state.entities[g.state.players[1].deck[0]]
        self.assertEqual(quote_cost(g.state, g.registry, entity).amount, 0)
        self.assertEqual(local_cost(entity)[0], 5)
        self.assertFalse(self.query(g))
        self.assertTrue(self.query(g, 'greater'))

    def test_generated_deck_cost_then_draw_and_clear_recompute_current_subset(self):
        g = self.game(('cmp.add', 'cmp.add', 'cmp.draw', 'cmp.clear'))
        self.play(g, 'cmp.add')
        entity = g.state.entities[g.state.players[1].deck[0]]
        self.assertEqual((g.registry.card(entity.card_id).cost, local_cost(entity)[0]), (5, 3))
        self.assertTrue(self.query(g))
        self.assertFalse(self.query(g, 'greater'))
        self.play(g, 'cmp.draw')
        self.assertIn(entity.id, g.state.players[1].hand)
        self.assertTrue(self.query(g, 'greater'))
        self.play(g, 'cmp.add')
        self.play(g, 'cmp.clear')
        self.assertTrue(self.query(g))
        self.assertTrue(self.query(g, 'greater'))

    def test_physical_face_change_uses_new_kind_and_local_cost(self):
        g = self.game(('cmp.face',), deck=('cmp.low',))
        identity = g.state.players[1].deck[0]
        self.play(g, 'cmp.face')
        self.assertEqual(g.state.players[1].deck, [identity])
        self.assertFalse(self.query(g))
        self.assertTrue(self.query(g, 'greater'))
        self.portable(g)

    def test_full_thirty_slot_constructed_current_query_and_restore(self):
        r = registry()
        own = (NATIVE,) + tuple(f'card.{i}' for i in range(1, 30))
        other = tuple(f'card.{i}' for i in range(1, 31))
        g = Game.from_decks(MatchSetup((DeckSpec('mage.hero', 'mage.power', CardClass.MAGE, own),
            DeckSpec('warrior.hero', 'warrior.power', CardClass.WARRIOR, other)), policy(r), 'coin', 84, 1), r)
        while g.state.pending_choice:
            q = g.state.pending_choice
            g.apply(SelectChoice(q.player_id, q.id, ()))
        self.assertEqual(tuple(map(len, g.state.opening.original_entities)), (30, 30))
        current = [g.state.entities[i].card_id for i in g.state.players[1].deck]
        self.assertEqual(self.query(g), NATIVE not in current)
        self.assertTrue(self.query(g, player=2))
        self.portable(g)

    def test_native_recruits_exactly_one_original_minion_and_pays_once(self):
        g = self.game(deck=('cmp.low', 'cmp.low', 'cmp.spell'))
        original = set(g.state.players[1].deck)
        self.play(g)
        recruited = set(g.state.players[1].board).intersection(original)
        self.assertEqual(len(recruited), 1)
        self.assertEqual(len(g.state.players[1].deck), 2)
        self.assertEqual((g.state.players[1].mana, g.state.play_history[-1].cost), (6, 4))
        self.assertFalse(any(e.kind == 'card_drawn' for e in g.events))
        self.assertEqual(len(g.state.play_history), 1)
        self.portable(g)

    def test_native_equal_or_more_expensive_minion_prevents_recruit_and_rng(self):
        for card in ('cmp.equal', 'cmp.high'):
            g = self.game(deck=('cmp.low', card))
            original, rng = list(g.state.players[1].deck), g.snapshot()['rng_state']
            self.play(g)
            self.assertEqual(g.state.players[1].deck, original)
            self.assertEqual(g.snapshot()['rng_state'], rng)
            self.assertEqual(len(g.state.players[1].board), 1)

    def test_native_empty_subset_or_full_board_keeps_original_pool_and_rng(self):
        for deck, board in ((('cmp.spell',), ()), (('cmp.low',), ('cmp.low',) * 6)):
            g = self.game(deck=deck, board=board)
            original, rng = list(g.state.players[1].deck), g.snapshot()['rng_state']
            self.play(g)
            self.assertEqual(g.state.players[1].deck, original)
            self.assertEqual(g.snapshot()['rng_state'], rng)
            self.assertEqual(len(g.state.players[1].board), len(board) + 1)

    def test_native_recruit_uses_saved_cost_and_does_not_invoke_recruited_battlecry(self):
        g = self.game((NATIVE, 'cmp.set.low'), deck=('cmp.high',))
        self.play(g, 'cmp.set.low')
        original = g.state.players[1].deck[0]
        self.play(g)
        self.assertIn(original, g.state.players[1].board)
        g = self.game(deck=('cmp.cry',))
        self.play(g)
        self.assertEqual(self.armor(g), 0)
        self.assertEqual(len(g.state.players[1].board), 2)

    def test_native_threshold_uses_source_local_cost_at_battlecry_dispatch(self):
        g = self.game((NATIVE, 'cmp.discount.native'), deck=('cmp.low',))
        self.play(g, 'cmp.discount.native')
        identity = self.play(g)
        self.assertEqual((local_cost(g.state.entities[identity])[0], g.state.play_history[-1].cost), (2, 2))
        self.assertEqual(g.state.players[1].mana, 8)
        self.assertEqual(len(g.state.players[1].deck), 1)
        self.assertEqual(len(g.state.players[1].board), 1)
        self.portable(g)

    def test_native_second_player_uses_own_deck(self):
        g = self.game((), deck=('cmp.high',), other_hand=(NATIVE,), other_deck=('cmp.low', 'cmp.low'))
        g.apply(EndTurn(1))
        identity = self.play(g)
        self.assertIn(identity, g.state.players[2].board)
        self.assertEqual(len(g.state.players[2].board), 2)
        self.assertEqual(len(g.state.players[1].deck), 1)

    def test_native_public_command_pays_and_moves_the_selected_physical_card(self):
        g = self.game(deck=('cmp.low',))
        original = g.state.players[1].deck[0]
        port, dto = g.for_player(1), g.for_player(1).legal_actions()
        ref = next(row['ref'] for row in g.observe(1)['players'][0]['hand'] if row['card_id'] == NATIVE)
        action = next(row for row in dto['actions'] if row.get('card') == ref)
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        self.assertEqual(g.state.players[1].mana, 6)
        self.assertIn(original, g.state.players[1].board)

    def test_silence_bounce_and_new_play_do_not_revoke_old_recruit(self):
        g = self.game((NATIVE, 'cmp.silence', 'cmp.bounce', 'cmp.add', 'cmp.set.high'), deck=('cmp.low',))
        original = g.state.players[1].deck[0]
        identity = self.play(g)
        self.play(g, 'cmp.silence')
        self.play(g, 'cmp.bounce')
        self.assertIn(original, g.state.players[1].board)
        self.assertIn(identity, g.state.players[1].hand)
        self.play(g, 'cmp.add')
        self.play(g, 'cmp.set.high')
        self.play(g)
        self.assertIn(original, g.state.players[1].board)
        self.assertEqual(len(g.state.players[1].board), 2)
        self.assertEqual(len(g.state.players[1].deck), 1)
        self.portable(g)

    def test_unexecuted_condition_waits_then_reads_new_local_cost_for_both_comparisons(self):
        for card, deck, comparison in (('cmp.wait.less', 'cmp.high', 'less'), ('cmp.wait.greater', 'cmp.low', 'greater')):
            g = self.game((card,), deck=(deck,))
            self.play(g, card)
            self.assertFalse(self.query(g, comparison))
            restored = self.portable(g)
            self.choose(g)
            self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
            self.assertTrue(self.query(g, comparison))
            self.assertEqual(self.armor(g), 3)

    def test_selected_yes_and_no_branches_keep_choice_after_deck_cost_changes(self):
        for card, deck, armor, later in (('cmp.selected.yes', 'cmp.low', 3, False), ('cmp.selected.no', 'cmp.high', 1, True)):
            g = self.game((card,), deck=(deck,))
            self.play(g, card)
            restored = self.portable(g)
            self.choose(g)
            self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
            self.assertEqual((self.armor(g), self.query(g)), (armor, later))

    def test_action_failure_rolls_back_condition_and_payment(self):
        g = self.game(('cmp.fail',), deck=('cmp.low',))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'cmp.fail')
        self.assertEqual(g.snapshot(), before)

    def test_waiting_failure_preserves_original_choice_cost_and_branch(self):
        g = self.game(('cmp.wait.fail',), deck=('cmp.high',))
        self.play(g, 'cmp.wait.fail')
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g)
        self.assertEqual(g.snapshot(), before)
        self.portable(g)

    def test_new_four_fields_and_all_original_conditions_roundtrip(self):
        g = self.game()
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        for declaration, fields in ((LESS, {'cost', 'comparison', 'cost_basis', 'scope'}),
            (DeckMinionCostCondition(0, 'greater', 'local'), {'cost', 'comparison', 'cost_basis', 'scope'}),
            (DeckCondition(), {'scope', 'predicate'}), (DeckCostCondition(4, 'local'), {'cost', 'cost_basis', 'scope'}),
            (DeckSpellSchoolCondition(SpellSchool.SHADOW), {'spell_school', 'scope'})):
            wire = codec.encode(declaration)
            self.assertEqual(codec.decode(wire), declaration)
            self.assertEqual(set(wire['fields']), fields)
            for field in fields:
                bad = deepcopy(wire)
                del bad['fields'][field]
                with self.assertRaises(ValueError):
                    codec.decode(bad)

    def test_declaration_requires_finite_strict_scope_cost_comparison_and_basis(self):
        cases = [(value, 'less', 'local', 'current') for value in (True, -1, 4.0, '4', None)]
        cases += [(4, value, 'local', 'current') for value in (None, True, '<', '<=', 'greater_equal', '')]
        cases += [(4, 'less', value, 'current') for value in (None, True, 'printed', 'external', '')]
        cases += [(4, 'less', 'local', value) for value in (None, True, 'starting', 'hand', '')]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                DeckMinionCostCondition(*args)
        with self.assertRaises(TypeError):
            DeckMinionCostCondition(4, 'less')
        for predicate in ('all_minions_cost_less', 'all_minions_cost_greater'):
            with self.assertRaises(ValueError):
                DeckCondition('current', predicate)

    def test_pending_snapshot_rejects_illegal_values_and_extra_fields(self):
        g = self.game(('cmp.wait.less',), deck=('cmp.high',))
        self.play(g, 'cmp.wait.less')
        for field, value in (('cost', True), ('cost', -1), ('comparison', '<='), ('cost_basis', 'printed'),
            ('scope', 'starting'), ('invented', 1)):
            saved = g.snapshot()
            self.nested(saved['resolution_frame'], 'DeckMinionCostCondition')['fields'][field] = value
            self.reject(saved)
        saved = g.snapshot()
        self.nested(saved['resolution_frame'], 'CheckDeckCondition')['fields']['player_id'] = True
        self.reject(saved)

    def test_private_condition_and_hidden_deck_costs_stay_out_of_player_interfaces(self):
        g = self.game(('cmp.wait.less',), deck=('cmp.no.meta',))
        self.play(g, 'cmp.wait.less')
        for player in (1, 2):
            text = json.dumps(g.observe(player)) + json.dumps(g.player_events(player)) + json.dumps(g.for_player(player).legal_actions())
            for private in ('DeckMinionCostCondition', 'cost_basis', 'on_match', 'on_miss', 'cmp.no.meta'):
                self.assertNotIn(private, text)
        self.portable(g)

    def test_persistent_schema_stays_and_previous_handler_is_rejected(self):
        g = self.game()
        self.assertEqual((g.snapshot()['schema_version'], g.ruleset.id, g.mechanics.version), (SNAPSHOT_SCHEMA_VERSION, 'prototype-v302', CORE_EFFECTS_VERSION))
        saved = g.snapshot()
        saved['mechanics_version']['version'] = 'core-effects-v232'
        self.reject(saved)


if __name__ == '__main__':
    unittest.main()
