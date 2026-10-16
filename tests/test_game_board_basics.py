"""Fixed public boards and only two necessary experimental Transfer Student forms."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import random
import unittest

from hs_sim.engine import (BoardCardFamily, BoardCardForm, CardClass, CardDefinition,
    CardType, EndTurn, Game, Keyword, MatchSetup, PlayCard, PlayerSetup, Rarity,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TargetMode, TargetSpec,
    UpgradeHandCard, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Draw,
    RandomDamage, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.game_boards import validate_state
from hs_sim.engine.player_target_inputs import (canonical, capture, decode, factory,
    validate_full_state)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard
from hs_sim.targets import canonical_digest
from opening_fixtures import deck, metadata, registry as opening_registry, setup

BASE, SHIELD, STRIKE = 'SCH_199', 'SCH_199t', 'SCH_199t2'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/board-environment-basics.json'
PIN = 'c45083b379872d7eeb4d5c97402c352f85e3178da00ddcb0727f2bfa187c0ca3'


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN:
        raise ValueError('Complete board-card raw changed')
    for row in raw['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original board-card row changed')
    return {row['id']: row['data'] for row in raw['records']}


def family(*, version='experimental-stw-org-v1', forms=None):
    # Local mapping policy, not authenticated by card raw or the client enum.
    return BoardCardFamily('transfer-student', version, BASE,
        forms or (BoardCardForm(1, SHIELD), BoardCardForm(2, STRIKE)))


def registry(scripts=(), *, board_family=True):
    r = opening_registry()
    rows = evidence()
    r.register_behavior('student.strike', lambda c: (Damage(c.target_id, 2, c.source_id),))
    for cid in (BASE, SHIELD, STRIKE):
        row = rows[cid]
        fields = ({'keywords': (Keyword.DIVINE_SHIELD,)} if cid == SHIELD else
            {'battlecry': 'student.strike', 'targeting': TargetSpec(TargetMode.IF_AVAILABLE)}
            if cid == STRIKE else {})
        r.register_card(CardDefinition(cid, row['name'], CardType.MINION, cost=row['cost'],
            attack=row['attack'], health=row['health'],
            metadata=metadata(CardClass.NEUTRAL, collectible=cid == BASE, rarity=Rarity.EPIC), **fields))
    if board_family:
        r.register_board_card_family(family())
    for name, callback in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name,
            metadata=metadata(collectible=False)))
    return r


def rehash(snapshot):
    snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})


class GameBoardTests(unittest.TestCase):
    def setUp(self):
        self.scripts = []

    def script(self, name, callback):
        self.scripts.append((name, callback))

    def game(self, board_id=1, *, hand=(BASE,), board=(), cards=(), actor=1, other_hand=()):
        own = PlayerSetup('mage.hero', hand=hand, deck=cards, board=board, mana=10, max_mana=10)
        other = PlayerSetup('warrior.hero', hand=other_hand, deck=('card.10',) * 4,
            mana=10, max_mana=10)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own),
            active_player=actor, board_id=board_id, seed=83), registry(self.scripts))

    def play(self, g, cid, *, actor=1, target=None):
        eid = next(i for i in g.state.players[actor].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(actor, eid, target))
        return eid

    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        make = lambda: registry(self.scripts)
        for other in (Game.from_snapshot(snap, make()), g.clone(), replay(build_replay(g), make())):
            self.assertEqual(other.snapshot(), snap)
            self.assertEqual([other.observe(p) for p in (1, 2)], [g.observe(p) for p in (1, 2)])
        return Game.from_snapshot(snap, make())

    def test_three_complete_real_raw_records_are_pinned_without_bulk_adaptation(self):
        rows = evidence()
        original = {r['id']: r for r in json.loads((FIXTURE.parents[1] /
            'extracted/cards.json').read_text(encoding='utf-8'))}
        self.assertEqual(set(rows), {BASE, SHIELD, STRIKE})
        for cid, row in rows.items():
            self.assertEqual(row, original[cid])
        self.assertEqual(rows[SHIELD]['tags']['DIVINE_SHIELD'], 1)
        self.assertIn('Deal 2 damage', rows[STRIKE]['text_en'])
        self.assertEqual({cid for cid in registry().cards if cid.startswith(BASE)}, set(rows))

    def test_public_board_is_shared_detached_and_does_not_reveal_hidden_cards(self):
        g = self.game(2, other_hand=('card.2',))
        for player in (1, 2):
            value = g.observe(player)
            self.assertEqual(value['board_id'], 2)
            enemy = value['players'][2 - player]
            self.assertTrue(all(row['card_id'] is None for row in enemy['hand']))
            self.assertFalse({'rng_state', 'state', 'entities', 'original_deck'} & value.keys())
            value['board_id'] = 99
        state = g.state
        state.board_id = 99
        self.assertEqual(g.state.board_id, 2)
        self.portable(g)

    def test_unspecified_board_remains_explicit_for_unrelated_cards(self):
        g = self.game(None, hand=('card.1',))
        self.assertIsNone(g.state.board_id)
        self.assertIsNone(g.snapshot()['state']['board_id'])
        self.assertIsNone(g.observe(1)['board_id'])
        self.play(g, 'card.1')
        self.portable(g)

    def test_configuration_rejects_boolean_zero_negative_and_nonnumeric_board_ids(self):
        r = registry()
        base = setup(r)
        for invalid in (True, False, 0, -1, '1', 1.5, {}, []):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    self.game(invalid, hand=())
                with self.assertRaises(ValueError):
                    replace(base, board_id=invalid)

    def test_unversioned_host_configuration_can_omit_board_but_serializes_it_explicitly(self):
        scenario = Scenario.from_dict({'players': [{'hero_card_id': 'mage.hero'},
            {'hero_card_id': 'warrior.hero'}]})
        self.assertIsNone(scenario.board_id)
        row = setup(registry()).to_dict()
        self.assertIn('board_id', row)
        row.pop('board_id')
        self.assertIsNone(MatchSetup.from_dict(row).board_id)
        row['board_id'] = 2
        self.assertEqual(MatchSetup.from_dict(row).board_id, 2)

    def test_initial_physical_cards_in_both_seats_and_all_three_zones_have_selected_face(self):
        for board_id, cid in ((1, SHIELD), (2, STRIKE)):
            for actor in (1, 2):
                g = self.game(board_id, hand=(BASE,), board=(BASE,), cards=(BASE,), actor=actor)
                owner = g.state.players[actor]
                for eid in owner.hand + owner.board + owner.deck:
                    self.assertEqual(g.state.entities[eid].card_id, cid)
                self.assertFalse(any(e.card_id == BASE for e in g.state.entities.values()))
                self.portable(g)

    def test_materialization_does_not_sample_rng_or_execute_targeted_battlecry(self):
        g = self.game(2, hand=(BASE,), board=(BASE,), cards=(BASE,))
        self.assertEqual(g._rng.getstate(), random.Random(83).getstate())
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)
        self.assertFalse(any(e.kind == 'damage' for e in g.events))
        self.assertEqual(g.state.players[1].mana, 10)

    def test_explicit_other_family_form_rebases_to_this_fixed_board(self):
        g = self.game(1, hand=(STRIKE,), board=(STRIKE,), cards=(STRIKE,))
        self.assertTrue(all(g.state.entities[eid].card_id == SHIELD
            for eid in g.state.players[1].hand + g.state.players[1].board + g.state.players[1].deck))
        self.portable(g)

    def test_real_shield_form_uses_ordinary_one_hit_consumption(self):
        self.script('hit', lambda c: (Damage(c.state.players[1].board[0], 1, c.source_id),))
        g = self.game(1, hand=(BASE, 'hit', 'hit'))
        eid = self.play(g, SHIELD)
        self.play(g, 'hit')
        e = g.state.entities[eid]
        self.assertEqual(e.health, 2)
        self.assertNotIn(Keyword.DIVINE_SHIELD, e.keywords)
        self.play(g, 'hit')
        self.assertEqual(g.state.entities[eid].health, 1)
        self.portable(g)

    def test_real_damage_form_exposes_targets_and_pays_once_for_two_damage(self):
        g = self.game(2)
        hero = g.state.players[2].hero_id
        eid = g.state.players[1].hand[0]
        self.assertIn(PlayCard(1, eid, hero, position=0), g.legal_actions())
        self.play(g, STRIKE, target=hero)
        self.assertEqual(g.state.players[1].mana, 8)
        self.assertEqual(g.state.entities[hero].health, 28)
        self.assertEqual(g.state.play_history[-1].card_id, STRIKE)
        self.assertEqual(g.state.entities[eid].zone, Zone.BOARD)
        self.portable(g)

    def test_player_port_can_play_selected_form_with_public_opaque_target(self):
        g = self.game(2)
        port = g.for_player(1)
        envelope = port.observe()
        view = envelope['observation']
        self.assertEqual(view['board_id'], 2)
        result = port.submit({'revision': envelope['revision'], 'action': {'type': 'play_card',
            'card': view['players'][0]['hand'][0]['ref'],
            'target': view['players'][1]['hero']['ref'], 'position': None}})
        self.assertTrue(result['accepted'], result.get('error'))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28)
        self.portable(g)

    def test_normal_summon_resolves_face_without_running_a_battlecry(self):
        self.script('summon', lambda c: (Summon(c.player_id, BASE),))
        g = self.game(2, hand=('summon',))
        self.play(g, 'summon')
        eid = g.state.players[1].board[0]
        self.assertEqual(g.state.entities[eid].card_id, STRIKE)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)
        self.portable(g)

    def test_later_hand_and_deck_acquisitions_resolve_before_owner_observation(self):
        self.script('create', lambda c: (AddToHand(c.player_id, BASE),
            AddToDeck(c.player_id, BASE, position='bottom')))
        g = self.game(1, hand=('create',))
        self.play(g, 'create')
        owner = g.state.players[1]
        self.assertEqual([g.state.entities[eid].card_id for eid in owner.hand + owner.deck], [SHIELD, SHIELD])
        self.assertEqual(g.observe(1)['players'][0]['hand'][0]['card_id'], SHIELD)
        self.assertIsNone(g.observe(2)['players'][0]['hand'][0]['card_id'])
        self.portable(g)

    def test_draw_preserves_existing_entity_and_selected_face(self):
        self.script('draw', lambda c: (Draw(c.player_id),))
        g = self.game(2, hand=('draw',), cards=(BASE,))
        eid = g.state.players[1].deck[0]
        self.play(g, 'draw')
        self.assertEqual(g.state.players[1].hand, [eid])
        self.assertEqual(g.state.entities[eid].card_id, STRIKE)
        self.portable(g)

    def test_hand_upgrade_uses_common_face_selection_and_preserves_physical_slot(self):
        self.script('upgrade', lambda c: (UpgradeHandCard(
            CardReference.capture(c.state.entities[c.state.players[1].hand[0]]), BASE),))
        g = self.game(1, hand=('upgrade', 'card.1'))
        eid = g.state.players[1].hand[1]
        self.play(g, 'upgrade')
        e = g.state.entities[eid]
        self.assertEqual((e.card_id, e.attack, e.health, e.cost), (SHIELD, 2, 2, 2))
        self.assertIn(Keyword.DIVINE_SHIELD, e.keywords)
        self.assertEqual(g.state.players[1].hand, [eid])
        self.portable(g)

    def test_board_transform_resolves_face_without_a_second_play_or_battlecry(self):
        self.script('transform', lambda c: (Transform(c.state.players[1].board[0], BASE),))
        g = self.game(2, hand=('transform',), board=('card.1',))
        eid = g.state.players[1].board[0]
        self.play(g, 'transform')
        self.assertEqual(g.state.players[1].board, [eid])
        self.assertEqual(g.state.entities[eid].card_id, STRIKE)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)
        self.assertEqual(len(g.state.play_history), 1)
        self.portable(g)

    def test_return_to_hand_keeps_selected_face_and_normal_printed_reset(self):
        self.script('bounce', lambda c: (ReturnToHand(c.state.players[1].board[0]),))
        self.script('hit', lambda c: (Damage(c.state.players[1].board[0], 1, c.source_id),))
        g = self.game(1, hand=(BASE, 'hit', 'bounce'))
        eid = self.play(g, SHIELD)
        self.play(g, 'hit')
        self.play(g, 'bounce')
        e = g.state.entities[eid]
        self.assertEqual((e.card_id, e.zone), (SHIELD, Zone.HAND))
        self.assertIn(Keyword.DIVINE_SHIELD, e.keywords)
        self.portable(g)

    def test_current_hand_copy_has_its_own_physical_identity_and_same_board_face(self):
        self.script('copy', lambda c: (CopyCard(
            CardReference.capture(c.state.entities[c.state.players[1].hand[0]]), c.player_id),))
        g = self.game(1, hand=('copy', BASE))
        original = g.state.players[1].hand[1]
        self.play(g, 'copy')
        ids = g.state.players[1].hand
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(ids[0], original)
        self.assertEqual([g.state.entities[i].card_id for i in ids], [SHIELD, SHIELD])
        self.portable(g)

    def test_silence_does_not_reselect_or_reinstall_the_selected_printed_ability(self):
        self.script('silence', lambda c: (Silence(c.state.players[1].board[0]),))
        g = self.game(1, hand=('silence',), board=(BASE,))
        eid = g.state.players[1].board[0]
        self.play(g, 'silence')
        self.assertEqual(g.state.entities[eid].card_id, SHIELD)
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[eid].keywords)
        self.portable(g)

    def test_real_turn_transitions_keep_the_same_board_without_rng_sampling(self):
        g = self.game(1, hand=(), cards=('card.1',) * 4)
        rng = g._rng.getstate()
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.assertEqual(g.state.board_id, 1)
        self.assertEqual(g._rng.getstate(), rng)
        self.portable(g)

    def test_waiting_choice_restores_same_board_and_creates_the_selected_face_once(self):
        self.script('wait', lambda c: (RequestChoice(c.player_id, (
            ChoiceOption('go', 'Continue', (AddToHand(c.player_id, BASE),)),), c.source_id),))
        g = self.game(2, hand=('wait',))
        self.play(g, 'wait')
        self.assertIsNotNone(g.state.pending_choice)
        restored = self.portable(g)
        for current in (g, restored):
            q = current.state.pending_choice
            current.apply(SelectChoice(q.player_id, q.id, ('go',)))
            self.assertEqual(current.state.board_id, 2)
            self.assertEqual([current.state.entities[i].card_id for i in current.state.players[1].hand], [STRIKE])
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.portable(g)

    def test_missing_mapping_after_random_work_rolls_back_the_complete_action(self):
        self.script('fault', lambda c: (RandomDamage((c.state.players[2].hero_id,), 1, c.source_id),
            AddToHand(c.player_id, BASE)))
        g = self.game(99, hand=('fault',))
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Unsupported game board'):
            self.play(g, 'fault')
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(g.state.board_id, 99)
        self.assertFalse(g.history)

    def test_required_missing_and_unmapped_board_refuse_physical_base_or_form(self):
        for board_id, message in ((None, 'requires a specified'), (99, 'Unsupported game board')):
            for cid in (BASE, SHIELD):
                with self.subTest(board_id=board_id, card=cid):
                    with self.assertRaisesRegex(ResolutionError, message):
                        self.game(board_id, hand=(cid,))

    def test_state_validator_rejects_unresolved_and_wrong_physical_faces(self):
        g = self.game(1)
        state = g.state
        eid = state.players[1].hand[0]
        for cid in (BASE, STRIKE):
            state.entities[eid].card_id = cid
            with self.assertRaisesRegex(ValueError, 'another game board form'):
                validate_state(state, g.registry)

    def test_current_snapshot_requires_board_field_and_rejects_wrong_type_even_with_rehashed_state(self):
        g = self.game(1)
        for invalid in ('missing', True, 0, -1, '1'):
            snap = deepcopy(g.snapshot())
            if invalid == 'missing':
                del snap['state']['board_id']
            else:
                snap['state']['board_id'] = invalid
            rehash(snap)
            with self.assertRaises(SnapshotError):
                Game.from_snapshot(snap, registry())
        snap = deepcopy(g.snapshot())
        snap['schema_version'] = 167
        with self.assertRaisesRegex(SnapshotError, f'schemas 1 through {SNAPSHOT_SCHEMA_VERSION-1}'):
            Game.from_snapshot(snap, registry())

    def test_constructed_opening_keeps_original_deck_identity_and_selected_physical_cards(self):
        r = registry()
        cards = (BASE,) + tuple(f'card.{i}' for i in range(1, 30))
        fixed = replace(setup(r, decks=(deck(cards=cards), deck(CardClass.WARRIOR, cards=cards))), board_id=2)
        g = Game.from_decks(fixed, r)
        self.assertEqual(g.snapshot()['match_setup']['board_id'], 2)
        self.assertEqual(g.state.players[1].original_deck, cards)
        self.assertEqual(sum(e.card_id == STRIKE for e in g.state.entities.values()), 2)
        self.portable(g)
        while g.state.pending_choice is not None:
            q = g.state.pending_choice
            g.apply(SelectChoice(q.player_id, q.id, ()))
        self.assertEqual(g.state.board_id, 2)
        self.portable(g)

    def test_constructed_snapshot_cannot_omit_setup_board_or_change_only_current_board(self):
        r = registry()
        g = Game.from_decks(replace(setup(r), board_id=1), r)
        for change in ('missing', 'different'):
            snap = deepcopy(g.snapshot())
            if change == 'missing':
                del snap['match_setup']['board_id']
            else:
                snap['state']['board_id'] = 2
            rehash(snap)
            with self.assertRaisesRegex(SnapshotError, '[Gg]ame board'):
                Game.from_snapshot(snap, registry())

    def test_finite_family_is_immutable_and_rejects_duplicate_or_unresolved_mapping(self):
        valid = family()
        with self.assertRaises(FrozenInstanceError):
            valid.base = 'card.1'
        for forms in ([BoardCardForm(1, SHIELD)], (BoardCardForm(1, BASE),),
                (BoardCardForm(1, SHIELD), BoardCardForm(1, STRIKE)), ({'board_id': 1, 'card_id': SHIELD},)):
            with self.assertRaises(ValueError):
                BoardCardFamily('student', 'v1', BASE, forms)
        for board_id in (True, 0, -1, '1'):
            with self.assertRaises(ValueError):
                BoardCardForm(board_id, SHIELD)

    def test_registration_refuses_shared_families_missing_cards_and_incomplete_printed_forms(self):
        r = registry()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            r.register_board_card_family(replace(family(), id='other'))
        for change in ('missing', 'stats', 'collectible', 'base_body'):
            r = registry()
            if change == 'missing':
                del r._cards[SHIELD]
            elif change == 'stats':
                r._cards[SHIELD] = replace(r.card(SHIELD), health=3)
            elif change == 'collectible':
                r._cards[SHIELD] = replace(r.card(SHIELD), metadata=metadata())
            else:
                r._cards[BASE] = replace(r.card(BASE), battlecry='student.strike')
            with self.assertRaises((ValueError, ResolutionError)):
                r.validate()

    def test_shared_result_can_serve_two_boards_but_mapping_and_policy_change_fingerprint(self):
        fingerprints = []
        for f in (family(), family(version='experimental-v2'),
                family(forms=(BoardCardForm(1, SHIELD), BoardCardForm(2, SHIELD)))):
            r = registry(board_family=False)
            r.register_board_card_family(f)
            fingerprints.append(r.fingerprint())
        self.assertEqual(len(set(fingerprints)), 3)
        r = registry()
        r.freeze()
        with self.assertRaises(ValueError):
            r.register_board_card_family(replace(family(), id='later'))
        with self.assertRaises(TypeError):
            r.board_card_families['later'] = family()

    def test_original_player_input_captures_public_board_and_rejects_missing_or_invalid_fact(self):
        g = self.game(2)
        source = g._state.entities[g._state.players[1].hand[0]]
        proof = capture(g, g._state, source)
        self.assertEqual(decode(proof)['board_id'], 2)
        validate_full_state(g._state, g.registry, source, proof)
        context = factory(proof)(source.id, g._state.players[2].hero_id)
        self.assertEqual(context.observation['board_id'], 2)
        context.observation['board_id'] = 99
        self.assertEqual(factory(proof)(source.id, None).observation['board_id'], 2)
        for invalid in ('missing', True, 0, '2'):
            value = json.loads(proof.observation_json)
            if invalid == 'missing':
                value.pop('board_id')
            else:
                value['board_id'] = invalid
            with self.assertRaises(ValueError):
                decode(replace(proof, observation_json=canonical(value)))


if __name__ == '__main__':
    unittest.main()
