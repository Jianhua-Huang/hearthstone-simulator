"""Real constructed starting-hand capture and one necessary temporary source."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, DeckSpec, EndTurn, Game,
    MatchSetup, OpeningHook, PlayCard, PlayerSetup, Rarity, ResolutionError, Scenario, SelectChoice,
    SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Draw, GainTemporaryMana,
    ModifyCost, RequestChoice, Summon)
from hs_sim.engine.hand_upgrades import UpgradeHandCard
from hs_sim.engine.model import StartingHandCard
from hs_sim.engine.opening import StartFirstTurn, validate_opening_boundary
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.starting_hands import ReplaceHandWithTemporaryStartingHand, starting_hand
from hs_sim.engine.temporary_hands import ReturnTemporaryHand, validate_boundary
from hs_sim.engine.zones import AddToDeck, CardReference, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry

FINS = 'TIME_706'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/starting-hand-basics.json'
PIN = 'e328f70eaece0b279bf07368bc83ed4334e9bd727a0bf3e29ca4aa8b26616a7f'
BASE = ('card.1', 'card.2', 'card.3', 'card.4', FINS, 'card.5', 'card.6', 'card.7', 'card.8', 'card.9')
OTHER = ('card.1', 'card.2', 'card.3', 'card.4', 'card.7', 'card.5', 'card.6', FINS, 'card.8', 'card.9')


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN:
        raise ValueError('Complete starting-hand raw changed')
    for row in raw['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Starting-hand full raw row changed')
    return {row['id']: row['data'] for row in raw['records']}


def registry(scripts=(), *, hook=None, hook_phase='after_mulligan', watch=None, fault=False):
    r = opening_registry()
    for kind, cid in ((CardType.HERO_POWER, 'paladin.power'), (CardType.HERO, 'paladin.hero')):
        r.register_card(CardDefinition(cid, cid, kind, cost=2 if kind == CardType.HERO_POWER else 0,
            health=30 if kind == CardType.HERO else 0, on_use='power' if kind == CardType.HERO_POWER else None,
            initial_hero_power='paladin.power' if kind == CardType.HERO else None,
            metadata=metadata(CardClass.PALADIN, collectible=False)))
    def fins(c):
        work = (ReplaceHandWithTemporaryStartingHand(c.player_id, c.source_id),)
        return work + ((AddToDeck(c.player_id, 'card.1'), AddToHand(c.player_id, 'missing.after.fins')) if fault else ())
    row = evidence()[FINS]
    r.register_behavior('fins', fins)
    r.register_card(CardDefinition(FINS, row['name'], CardType.MINION, cost=row['cost'], attack=row['attack'],
        health=row['health'], battlecry='fins', metadata=metadata(CardClass.PALADIN, rarity=Rarity.LEGENDARY, tribes=('murloc',))))
    r.register_card(CardDefinition('copies', 'Copies', CardType.MINION, cost=1, attack=1, health=1,
        metadata=metadata(max_copies=10)))
    for name, callback in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=metadata()))
    if watch:
        event, callback = watch
        r.register_behavior('watch', callback)
        r.register_card(CardDefinition('watch', 'Watch', CardType.MINION, health=5,
            triggers=(TriggerSpec(event, 'watch'),), metadata=metadata()))
    if hook is not None or watch:
        def opening(c):
            return ((Summon(1, 'watch'),) if watch else ()) + (() if hook is None else tuple(hook(c)))
        r.register_behavior('opening.probe', opening)
        r.register_card(CardDefinition('opening.probe', 'Opening probe', CardType.MINION, health=1,
            opening_hooks=(OpeningHook(hook_phase, 'opening.probe'),), metadata=metadata()))
    return r


class StartingHandTests(unittest.TestCase):
    def setUp(self):
        self.scripts = []
        self.options = {}

    def script(self, name, callback):
        self.scripts.append((name, callback))

    def game(self, *, first=1, finish=True, cards=None, other=None):
        r = registry(self.scripts, **self.options)
        own = list(BASE if cards is None else cards)
        if cards is None:
            for slot, (name, _) in zip((3, 7, 6, 1), self.scripts):
                own[slot] = name
            if self.options.get('hook') is not None or self.options.get('watch'):
                own[9] = 'opening.probe'
        decks = tuple(DeckSpec('paladin.hero', 'paladin.power', CardClass.PALADIN, tuple(group))
            for group in (own, OTHER if other is None else other))
        g = Game.from_decks(MatchSetup(decks, policy(r, deck_size=len(own)), 'coin', 71, first), r)
        return self.finish(g) if finish else g

    def choose(self, g, ids=()):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, tuple(str(v) for v in ids)))

    def finish(self, g):
        while g.state.pending_choice is not None:
            q = g.state.pending_choice
            self.choose(g, () if q.purpose.value == 'mulligan' else ('ok',))
        return g

    def ready(self, g, player=1, minimum=2):
        for _ in range(24):
            state = g.state
            if state.active_player == player and state.players[player].mana >= minimum and any(
                    state.entities[eid].card_id == FINS for eid in state.players[player].hand):
                return g
            g.apply(EndTurn(state.active_player))
            self.finish(g)
        self.fail('Necessary Fins source did not become playable')

    def play(self, g, cid=FINS, player=None):
        player = g.state.active_player if player is None else player
        eid = next(eid for eid in g.state.players[player].hand if g.state.entities[eid].card_id == cid)
        g.apply(PlayCard(player, eid))
        return eid

    def portable(self, g):
        raw = json.loads(json.dumps(g.snapshot()))
        fresh = registry(self.scripts, **self.options)
        restored = Game.from_snapshot(raw, fresh)
        self.assertEqual(restored.snapshot(), raw)
        self.assertEqual(g.clone().snapshot(), raw)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, **self.options)).snapshot(), raw)
        return restored

    def faces(self, g, player=1):
        state = g.state
        return tuple(state.entities[eid].card_id for eid in state.players[player].hand)

    def invalid(self, g, change, validator=validate_opening_boundary):
        bad = self.portable(g)
        with self.assertRaises((ValueError, ResolutionError)):
            change(bad)
            validator(bad)

    def wait(self, c):
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),), c.source_id),)

    def test_final_hands_include_actual_coin_and_exclude_first_normal_draw(self):
        g = self.game()
        state = g.state
        groups = state.opening.starting_hands
        self.assertEqual(tuple(len(group) for group in groups), (3, 5))
        self.assertEqual(tuple(v.entity_id for v in groups[0]), tuple(state.players[1].hand[:3]))
        self.assertEqual(tuple(v.entity_id for v in groups[1]), tuple(state.players[2].hand))
        self.assertEqual(groups[1][-1].card_id, 'coin')
        self.assertNotIn(state.draw_history[0].entity_id, tuple(v.entity_id for v in groups[0]))
        kinds = [e.kind for e in g.events]
        self.assertLess(kinds.index('mulligan_completed'), kinds.index('starting_hands_captured'))
        self.assertLess(kinds.index('starting_hands_captured'), kinds.index('game_started'))
        self.portable(g)

    def test_partial_mulligan_freezes_replacements_and_original_kept_order(self):
        g = self.game(finish=False)
        offered = g.state.opening.offered[0]
        self.choose(g, (offered[2], offered[0]))
        self.assertIsNone(g.state.opening.starting_hands)
        self.choose(g)
        ids = tuple(v.entity_id for v in g.state.opening.starting_hands[0])
        self.assertEqual(ids, tuple(g.state.players[1].hand[:3]))
        self.assertEqual(ids[1], offered[1])
        self.assertFalse(set(ids).intersection((offered[0], offered[2])))
        self.portable(g)

    def test_reverse_first_player_captures_groups_by_player_not_turn_order(self):
        g = self.game(first=2)
        groups = g.state.opening.starting_hands
        self.assertEqual(tuple(len(group) for group in groups), (5, 3))
        self.assertEqual(groups[0][-1].card_id, 'coin')
        self.assertEqual(tuple(v.entity_id for v in groups[1]), tuple(g.state.players[2].hand[:3]))
        self.portable(g)

    def test_equal_printed_faces_keep_distinct_actual_starting_entities(self):
        g = self.game(cards=('copies',) * 10, other=('copies',) * 10)
        groups = g.state.opening.starting_hands
        ids = tuple(v.entity_id for group in groups for v in group)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(tuple(v.card_id for v in groups[0]), ('copies',) * 3)
        self.portable(g)

    def test_before_deal_wait_has_no_final_record_and_restores(self):
        self.options.update(hook=self.wait, hook_phase='before_deal')
        g = self.game(finish=False)
        self.assertEqual(g.state.opening.stage, 'dealing')
        self.assertIsNone(g.state.opening.starting_hands)
        g = self.portable(g)
        self.choose(g, ('ok',))
        self.finish(g)
        self.assertEqual(len(g.state.opening.starting_hands[0]), 3)
        self.portable(g)

    def test_after_mulligan_wait_freezes_only_after_all_opening_work(self):
        self.options['hook'] = lambda c: (RequestChoice(c.player_id,
            (ChoiceOption('ok', 'Add', (AddToHand(c.player_id, 'card.30'),)),), c.source_id),)
        g = self.game(finish=False)
        self.choose(g)
        self.choose(g)
        self.assertEqual(g.state.opening.stage, 'starting')
        self.assertIsNone(g.state.opening.starting_hands)
        g = self.portable(g)
        self.choose(g, ('ok',))
        self.assertEqual(g.state.opening.starting_hands[0][-1].card_id, 'card.30')
        self.assertEqual(len(g.state.opening.starting_hands[0]), 4)
        self.portable(g)

    def test_first_turn_publication_wait_already_has_record_before_default_draw(self):
        self.options['watch'] = ('turn_started', self.wait)
        g = self.game(finish=False)
        self.choose(g)
        self.choose(g)
        self.assertEqual(g.state.opening.stage, 'complete')
        self.assertEqual(len(g.state.opening.starting_hands[0]), 3)
        self.assertFalse(g.state.draw_history)
        g = self.portable(g)
        self.choose(g, ('ok',))
        self.assertEqual(len(g.state.draw_history), 1)
        self.assertEqual(len(g.state.opening.starting_hands[0]), 3)
        self.portable(g)

    def test_real_fins_creates_recorded_faces_and_restores_actual_original_group(self):
        g = self.ready(self.game())
        starting = g.state.opening.starting_hands[0]
        before_hand = tuple(g.state.players[1].hand)
        rng = g._rng.getstate()
        source = self.play(g)
        originals = tuple(eid for eid in before_hand if eid != source)
        root = g.state.temporary_hands[0]
        self.assertEqual(tuple(v.entity_id for v in root.originals), originals)
        self.assertEqual(self.faces(g), tuple(v.card_id for v in starting))
        self.assertEqual(tuple(g.state.entities[eid].origin_entity_id for eid in g.state.players[1].hand), tuple(v.entity_id for v in starting))
        self.assertFalse(set(g.state.players[1].hand).intersection(v.entity_id for v in starting))
        self.assertEqual(g.state.players[1].board, [source])
        self.assertEqual(g.state.players[1].mana, 0)
        self.assertEqual(g._rng.getstate(), rng)
        self.assertTrue(all(g.state.entities[eid].zone == Zone.SETASIDE for eid in originals))
        self.portable(g)
        g.apply(EndTurn(1))
        self.assertEqual(tuple(g.state.players[1].hand), originals)
        self.assertEqual(g.state.temporary_hands[0].phase, 'completed')
        self.portable(g)

    def test_second_actor_gets_its_own_four_plus_coin_and_own_end_return(self):
        g = self.ready(self.game(), 2)
        faces = tuple(v.card_id for v in g.state.opening.starting_hands[1])
        original = tuple(g.state.players[2].hand)
        source = self.play(g, player=2)
        self.assertEqual(self.faces(g, 2), faces)
        self.assertEqual(faces[-1], 'coin')
        self.assertEqual(g.state.temporary_hands[0].request.player_id, 2)
        g.apply(EndTurn(2))
        self.assertEqual(tuple(g.state.players[2].hand), tuple(eid for eid in original if eid != source))
        self.portable(g)

    def test_full_three_raw_rows_equal_extraction_only_necessary_fins_is_adapted(self):
        full = {row['id']: row for row in json.loads((FIXTURE.parents[1] / 'extracted/cards.json').read_text(encoding='utf-8'))}
        rows = evidence()
        self.assertEqual(tuple(rows), (FINS, FINS + 'e2', FINS + 'e3'))
        for cid, row in rows.items():
            self.assertEqual(row, full[cid])
        r = registry()
        self.assertNotIn(FINS + 'e2', r.cards)
        self.assertNotIn(FINS + 'e3', r.cards)
        self.assertIn('starting', rows[FINS]['text_en'])

    def test_later_original_face_upgrade_does_not_rewrite_frozen_starting_face(self):
        self.script('upgrade', lambda c: (UpgradeHandCard(CardReference.capture(c.state.entities[next(eid for eid in c.state.players[1].hand
            if c.state.entities[eid].card_id == 'card.7')]), 'card.30', c.source_id),))
        g = self.ready(self.game())
        original = next(v for v in g.state.opening.starting_hands[0] if v.card_id == 'card.7')
        self.play(g, 'upgrade')
        self.assertEqual(g.state.entities[original.entity_id].card_id, 'card.30')
        self.play(g)
        self.assertIn('card.7', self.faces(g))
        self.assertNotIn('card.30', self.faces(g))
        self.portable(g)
        g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[original.entity_id].card_id, 'card.30')

    def test_later_original_cost_is_preserved_on_return_but_not_on_printed_starting_copy(self):
        self.script('discount', lambda c: (ModifyCost(next(eid for eid in c.state.players[1].hand
            if c.state.entities[eid].card_id == 'card.7'), CostSpec(delta=-1)),))
        g = self.ready(self.game())
        original = next(v for v in g.state.opening.starting_hands[0] if v.card_id == 'card.7')
        self.play(g, 'discount')
        self.play(g)
        body = next(eid for eid in g.state.players[1].hand if g.state.entities[eid].card_id == 'card.7')
        self.assertEqual(g.state.entities[body].cost, 1)
        g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[original.entity_id].cost, 0)
        self.portable(g)

    def test_departed_original_is_recreated_without_moving_its_physical_deck_entity(self):
        self.script('depart', lambda c: (MoveCard(CardReference.capture(c.state.entities[next(eid for eid in c.state.players[1].hand
            if c.state.entities[eid].card_id == 'card.7')]), 1, Zone.DECK, position='bottom', source_id=c.source_id),))
        g = self.ready(self.game())
        old = next(v for v in g.state.opening.starting_hands[0] if v.card_id == 'card.7')
        self.play(g, 'depart')
        self.play(g)
        self.assertIn(old.entity_id, g.state.players[1].deck)
        self.assertIn('card.7', self.faces(g))
        self.assertNotIn(old.entity_id, g.state.players[1].hand)
        self.portable(g)

    def test_same_mechanism_second_play_uses_same_frozen_basis_and_returns_lifo(self):
        self.script('mana', lambda c: (GainTemporaryMana(1, 2),))
        g = self.ready(self.game())
        original = tuple(g.state.players[1].hand)
        source = self.play(g)
        first = g.state.temporary_hands[0]
        self.play(g, 'mana')
        self.play(g)
        second = g.state.temporary_hands[1]
        self.assertEqual(first.copied_from, second.copied_from)
        self.portable(g)
        g.apply(EndTurn(1))
        self.assertEqual(tuple(g.state.players[1].hand), tuple(eid for eid in original if eid != source))
        ends = [dict(e.data)['hand_id'] for e in g.events if e.kind == 'temporary_starting_hand_restored']
        self.assertEqual(ends, [2, 1])
        self.portable(g)

    def test_genuine_empty_starting_group_differs_from_missing_record(self):
        self.options['hook'] = lambda c: tuple(MoveCard(CardReference.capture(c.state.entities[eid]), 1, Zone.DECK,
            position='top', source_id=c.source_id) for eid in c.state.players[1].hand)
        g = self.ready(self.game())
        self.assertEqual(starting_hand(g.state, 1), ())
        held = tuple(g.state.players[1].hand)
        source = self.play(g)
        self.assertFalse(g.state.players[1].hand)
        g.apply(EndTurn(1))
        self.assertEqual(tuple(g.state.players[1].hand), tuple(eid for eid in held if eid != source))
        self.portable(g)

    def test_full_final_starting_hand_fits_only_after_original_group_is_saved(self):
        self.options['hook'] = lambda c: (AddToHand(1, 'card.30'),) * 7
        g = self.ready(self.game())
        self.assertEqual(len(g.state.opening.starting_hands[0]), 10)
        self.play(g)
        self.assertEqual(len(g.state.players[1].hand), 10)
        root = g.state.temporary_hands[0]
        self.assertTrue(all(g.state.entities[eid].zone == Zone.HAND for eid in root.introduced))
        g.apply(EndTurn(1))
        self.assertEqual(len(g.state.players[1].hand), 9)
        self.portable(g)

    def test_later_generated_and_drawn_cards_follow_existing_whole_hand_cleanup(self):
        self.script('new.cards', lambda c: (AddToHand(1, 'card.30'), Draw(1)))
        g = self.ready(self.game())
        self.play(g)
        held = tuple(v.entity_id for v in g.state.temporary_hands[0].originals)
        self.play(g, 'new.cards')
        generated = next(eid for eid in g.state.players[1].hand if g.state.entities[eid].card_id == 'card.30')
        drawn = g.state.players[1].hand[-1]
        g.apply(EndTurn(1))
        self.assertEqual(tuple(g.state.players[1].hand), held)
        self.assertEqual(g.state.entities[generated].zone, Zone.SETASIDE)
        self.assertEqual(g.state.entities[drawn].zone, Zone.SETASIDE)
        self.portable(g)

    def test_played_starting_copy_remains_on_board_after_hand_return(self):
        g = self.ready(self.game(), minimum=3)
        self.play(g)
        body = self.play(g, 'card.4')
        g.apply(EndTurn(1))
        self.assertIn(body, g.state.players[1].board)
        self.assertNotIn(body, g.state.players[1].hand)
        self.portable(g)

    def test_materialization_wait_commits_entire_group_and_restores_without_recreation(self):
        def watch(c):
            return self.wait(c) if c.state.entities[c.event.target_id].origin_entity_id is not None else ()
        self.options['watch'] = ('card_added_to_hand', watch)
        g = self.ready(self.game())
        self.play(g)
        introduced = g.state.temporary_hands[0].introduced
        self.assertEqual(tuple(g.state.players[1].hand), introduced)
        self.assertEqual(len(introduced), 3)
        waits = 0
        while g.state.pending_choice is not None:
            g = self.portable(g)
            self.choose(g, ('ok',))
            waits += 1
            self.assertEqual(g.state.temporary_hands[0].introduced, introduced)
        self.assertEqual(waits, 3)

    def test_return_wait_commits_original_group_once_and_restores(self):
        self.options['watch'] = ('card_moved_to_hand', self.wait)
        g = self.ready(self.game())
        self.play(g)
        originals = tuple(v.entity_id for v in g.state.temporary_hands[0].originals)
        g.apply(EndTurn(1))
        self.assertEqual(tuple(g.state.players[1].hand), originals)
        self.assertEqual(g.state.temporary_hands[0].phase, 'completed')
        self.assertIsNotNone(g.state.pending_choice)
        while g.state.pending_choice is not None:
            g = self.portable(g)
            self.choose(g, ('ok',))
        self.assertEqual(sum(e.kind == 'temporary_starting_hand_restored' for e in g.events), 1)

    def test_late_acceptance_failure_restores_payment_rng_originals_and_baseline(self):
        self.options['fault'] = True
        g = self.ready(self.game())
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g)
        self.assertEqual(g.snapshot(), before)

    def test_late_return_failure_rolls_back_the_entire_ending_window(self):
        self.options['watch'] = ('card_moved_to_hand', lambda c: (AddToHand(1, 'missing.return.fins'),))
        g = self.ready(self.game())
        self.play(g)
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(), before)

    def test_terminal_cleanup_preserves_hidden_originals_and_frozen_baseline(self):
        self.script('kill', lambda c: (Damage(c.state.players[2].hero_id, 50, c.source_id),))
        g = self.ready(self.game())
        baseline = g.state.opening.starting_hands
        self.play(g)
        self.play(g, 'kill')
        self.assertEqual(g.state.status, 'finished')
        self.assertEqual(g.state.temporary_hands[0].phase, 'ended')
        self.assertEqual(g.state.opening.starting_hands, baseline)
        self.portable(g)

    def test_scenario_never_invents_starting_hand_and_failed_real_play_rolls_back(self):
        g = Game.from_scenario(Scenario((PlayerSetup('paladin.hero', hand=(FINS,), mana=10, max_mana=10),
            PlayerSetup('paladin.hero')), seed=71), registry())
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'final constructed'):
            self.play(g)
        self.assertEqual(g.snapshot(), before)
        self.assertIsNone(g.state.opening)

    def test_invalid_actor_missing_source_and_boolean_fields_are_rejected(self):
        for args in ((True, 1), (1, True), (3, 1), (1, 0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                ReplaceHandWithTemporaryStartingHand(*args)
        self.script('bad', lambda c: (ReplaceHandWithTemporaryStartingHand(2, c.source_id),))
        g = self.ready(self.game())
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.scripts = [('bad', lambda c: (ReplaceHandWithTemporaryStartingHand(1, 999999),))]
        g = self.ready(self.game())
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'bad')
        self.assertEqual(g.snapshot(), before)

    def test_reordered_frozen_basis_and_wrong_acquisition_are_rejected(self):
        g = self.game()
        groups = g.state.opening.starting_hands
        self.invalid(g, lambda bad: setattr(bad._state, 'opening', replace(bad._state.opening,
            starting_hands=(tuple(reversed(groups[0])), groups[1]))))
        self.invalid(g, lambda bad: setattr(bad._state, 'opening', replace(bad._state.opening,
            starting_hands=((replace(groups[0][0], hand_entry_id=groups[1][0].hand_entry_id),) + groups[0][1:], groups[1]))))

    def test_entire_capture_record_and_private_receipt_cannot_be_removed(self):
        g = self.game()
        self.invalid(g, lambda bad: setattr(bad._state, 'opening', replace(bad._state.opening, starting_hands=None)))
        def lose_receipt(bad):
            i = next(i for i, event in enumerate(bad._events) if event.kind == 'starting_hands_captured')
            bad._events[i] = replace(bad._events[i], kind='missing.starting.capture')
        self.invalid(g, lose_receipt)
        self.invalid(g, lambda bad: bad._events.append(next(e for e in bad._events if e.kind == 'starting_hands_captured')))

    def test_temporary_source_basis_and_creation_origin_cannot_be_replaced(self):
        g = self.ready(self.game())
        self.play(g)
        self.invalid(g, lambda bad: bad._state.temporary_hands.__setitem__(0,
            replace(bad._state.temporary_hands[0], copied_from=tuple(reversed(bad._state.temporary_hands[0].copied_from)))), validate_boundary)
        self.invalid(g, lambda bad: setattr(bad._state.entities[bad._state.temporary_hands[0].introduced[0]],
            'origin_entity_id', None), validate_boundary)

    def test_schema166_and_strict_final_group_and_request_decoders(self):
        g = self.ready(self.game())
        self.play(g)
        saved = g.snapshot()
        self.assertEqual(saved['schema_version'], 266)
        for version in (1, 164, 165, 217, True, '166'):
            bad = json.loads(json.dumps(saved))
            bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(SnapshotError):
                Game.from_snapshot(bad, registry())
        for mutation in (lambda raw: raw['state']['opening'].pop('starting_hands'),
                lambda raw: raw['state']['opening']['starting_hands'][0][0].__setitem__('extra', 1),
                lambda raw: raw['state']['opening']['starting_hands'][0][0].__setitem__('hand_entry_id', True),
                lambda raw: raw['state']['temporary_hands'][0]['request'].__setitem__('source_player_id', 2)):
            bad = json.loads(json.dumps(saved))
            mutation(bad)
            with self.assertRaises(SnapshotError):
                Game.from_snapshot(bad, registry())

    def test_player_views_and_events_never_include_private_starting_material(self):
        g = self.ready(self.game())
        self.play(g)
        before = g.snapshot()
        for player in (1, 2):
            encoded = json.dumps(g.observe(player))
            for field in ('starting_hands', 'copied_from', 'originals', 'origin_entity_id', 'setaside', 'temporary_hands'):
                self.assertNotIn(field, encoded)
            self.assertFalse(any(e['kind'].startswith(('starting_hands_', 'temporary_starting_hand_')) for e in g.player_events(player)))
        self.assertEqual(g.snapshot(), before)
        self.portable(g)

    def test_repeated_first_turn_capture_and_early_private_return_are_rejected(self):
        self.script('early', lambda c: (StartFirstTurn(),))
        g = self.ready(self.game())
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'early')
        self.assertEqual(g.snapshot(), before)
        self.scripts = [('early', lambda c: (ReturnTemporaryHand(1),))]
        g = self.ready(self.game())
        self.play(g)
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'early')
        self.assertEqual(g.snapshot(), before)

    def test_ending_wait_must_keep_actual_temporary_hand_expiry(self):
        self.options['watch'] = ('turn_ended', self.wait)
        g = self.ready(self.game())
        self.play(g)
        g.apply(EndTurn(1))
        self.assertEqual(g.state.temporary_hands[0].phase, 'active')
        from hs_sim.engine.resolver import ExpireTurn
        self.invalid(g, lambda bad: setattr(bad, '_frame', replace(bad._frame, continuation=tuple(work for work in bad._frame.continuation
            if type(work) is not ExpireTurn))), validate_boundary)
