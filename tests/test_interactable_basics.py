"""Necessary Rift opener and independent recurring hand-investment action."""
from dataclasses import replace
import json
from pathlib import Path
import random
import unittest

from hs_sim.engine import (Attack, CardClass, CardDefinition, CardType, EndTurn, Game,
    IllegalAction, InteractableSpec, InstallInteractable, Keyword, PlayCard, PlayerSetup,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, UseInteractable, Zone)
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, Destroy,
    RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.interactables import FinishInteractableUse, validate_boundary
from hs_sim.engine.pools import SummonFromCandidates
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import AddToDeck, CardReference
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry

OPEN, OBJECT = 'TLC_446t', 'TLC_446t1'
BEASTS = ('TLC_446t2', 'TLC_446t3', 'TLC_446t4')
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/interactable-basics.json'
PIN = '7fe0889b4bb20a3ff77cba36a1446a0a7d2ed34fcb445430d93ba045f6d732e5'


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN:
        raise ValueError('Complete interactable raw changed')
    for r in raw['records']:
        if r['id'] != r['data']['id'] or canonical_digest(r['data']) != r['data_sha256']:
            raise ValueError('Original interactable row changed')
    return {r['id']: r['data'] for r in raw['records']}


def registry(scripts=(), *, watch=None, fault=False, wait_payload=False):
    r = opening_registry()
    rows = evidence()
    r.register_behavior('open.rift', lambda c: (InstallInteractable(c.player_id, OBJECT, c.source_id),))
    def summon(c):
        work = tuple(SummonFromCandidates(c.player_id, BEASTS, c.source_id) for _ in range(2))
        if wait_payload:
            work = (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),), c.source_id),) + work
        return work + ((AddToDeck(c.player_id, 'card.11'), AddToHand(c.player_id, 'missing.rift')) if fault else ())
    r.register_behavior('use.rift', summon)
    row = rows[OPEN]
    r.register_card(CardDefinition(OPEN, row['name'], CardType.SPELL,
        cost=row['cost'], on_play='open.rift', metadata=metadata(CardClass.WARLOCK, collectible=False)))
    row = rows[OBJECT]
    r.register_card(CardDefinition(OBJECT, row['name'], CardType.MINION,
        cost=row['cost'], health=row['health'], corpse_value=0, interactable=InteractableSpec('use.rift'),
        metadata=metadata(CardClass.WARLOCK, collectible=False)))
    for cid, keywords in zip(BEASTS, ((Keyword.RUSH, Keyword.LIFESTEAL),
            (Keyword.CHARGE, Keyword.ELUSIVE), (Keyword.TAUNT, Keyword.REBORN))):
        row = rows[cid]
        r.register_card(CardDefinition(cid, row['name'], CardType.MINION,
            cost=row['cost'], attack=row['attack'], health=row['health'], keywords=keywords,
            metadata=metadata(CardClass.WARLOCK, collectible=False, tribes=('beast', 'demon'))))
    for name, callback in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=metadata()))
    if watch:
        event, callback = watch
        r.register_behavior('watch', callback)
        r.register_card(CardDefinition('watch', 'Interpreter observer', CardType.MINION,
            health=4, triggers=(TriggerSpec(event, 'watch'),), metadata=metadata()))
    return r


class InteractableTests(unittest.TestCase):
    def setUp(self):
        self.scripts, self.options = [], {}

    def script(self, name, callback):
        self.scripts.append((name, callback))

    def game(self, hand=(OPEN, 'card.1', 'card.2'), *, board=(), actor=1):
        own = PlayerSetup('mage.hero', hand=hand, deck=('card.9',) * 5, board=board,
            mana=10, max_mana=10)
        other = PlayerSetup('warrior.hero', hand=('card.3',), deck=('card.10',) * 5,
            mana=10, max_mana=10)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own),
            active_player=actor, seed=79), registry(self.scripts, **self.options))

    def play(self, g, cid=OPEN, actor=1):
        eid = next(eid for eid in g.state.players[actor].hand if g.state.entities[eid].card_id == cid)
        g.apply(PlayCard(actor, eid))
        return eid

    def obj(self, g, actor=1):
        return next(eid for eid in g.state.players[actor].board if g.state.entities[eid].card_id == OBJECT)

    def use(self, g, actor=1):
        action = UseInteractable(actor, self.obj(g, actor), g.state.players[actor].hand[0])
        g.apply(action)
        return action.card_entity_id

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, registry(self.scripts, **self.options))
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, **self.options)).snapshot(), saved)
        return restored

    def choose(self, g):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, ('ok',)))

    def wait(self, c):
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),), c.source_id),)

    def test_real_opener_installs_inert_public_object_without_summoning_a_minion(self):
        g = self.game()
        source = self.play(g)
        obj = g.state.entities[self.obj(g)]
        self.assertEqual(g.state.players[1].board, [obj.id])
        self.assertTrue(obj.interactable_object)
        self.assertFalse(obj.active)
        self.assertFalse(obj.is_character)
        self.assertFalse(obj.abilities)
        self.assertEqual(g.state.players[1].mana, 5)
        self.assertFalse(any(e.kind == 'minion_summoned' and e.target_id == obj.id for e in g.events))
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.portable(g)

    def test_real_investment_is_free_removal_and_two_normal_random_summons(self):
        g = self.game()
        self.play(g)
        rng = random.Random()
        rng.setstate(g._rng.getstate())
        expected = [rng.choice(BEASTS), rng.choice(BEASTS)]
        plays = len(g.state.play_history)
        casts = len(g.state.cast_history)
        card = self.use(g)
        record = g.state.interactable_history[0]
        self.assertIsNotNone(record.finished_event)
        self.assertEqual(record.invested.entity_id, card)
        self.assertEqual(g.state.entities[card].zone, Zone.SETASIDE)
        self.assertEqual([g.state.entities[eid].card_id for eid in g.state.players[1].board[1:]], expected)
        self.assertEqual(g._rng.getstate(), rng.getstate())
        self.assertEqual(g.state.players[1].mana, 5)
        self.assertEqual((len(g.state.play_history), len(g.state.cast_history)), (plays, casts))
        self.assertFalse(any(e.kind in ('card_discarded', 'card_destroyed_in_deck') for e in g.events))
        self.portable(g)

    def test_complete_raw_opener_object_and_three_finite_tokens_are_pinned(self):
        rows = evidence()
        original = {r['id']: r for r in json.loads((FIXTURE.parents[1] /
            'extracted/cards.json').read_text(encoding='utf-8'))}
        self.assertEqual(len(rows), 7)
        for cid, row in rows.items():
            self.assertEqual(row, original[cid])
        self.assertEqual(rows[OBJECT]['tags']['INTERACTABLE_OBJECT'], 1)
        self.assertEqual(rows[OBJECT]['tags']['UNTOUCHABLE'], 1)
        self.assertIn('Once per turn', rows[OBJECT]['text_en'])
        self.assertNotIn('TLC_446', registry().cards)

    def test_legal_actions_offer_each_own_hand_card_and_consume_only_one_use(self):
        g = self.game()
        self.play(g)
        obj = self.obj(g)
        held = tuple(g.state.players[1].hand)
        legal = [a for a in g.legal_actions() if type(a) is UseInteractable]
        self.assertEqual({(a.entity_id, a.card_entity_id) for a in legal}, {(obj, eid) for eid in held})
        self.use(g)
        self.assertFalse(any(type(a) is UseInteractable for a in g.legal_actions()))
        before = g.snapshot()
        with self.assertRaisesRegex(IllegalAction, 'already been used'):
            self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_empty_hand_has_no_investment_action(self):
        g = self.game((OPEN,))
        self.play(g)
        self.assertFalse(any(type(a) is UseInteractable for a in g.legal_actions()))
        self.portable(g)

    def test_wrong_owner_enemy_hand_and_nonhand_card_are_rejected(self):
        g = self.game()
        self.play(g)
        obj = self.obj(g)
        for action in (UseInteractable(2, obj, g.state.players[2].hand[0]),
                UseInteractable(1, obj, g.state.players[2].hand[0]), UseInteractable(1, obj, obj)):
            before = g.snapshot()
            with self.assertRaises(IllegalAction):
                g.apply(action)
            self.assertEqual(g.snapshot(), before)

    def test_consumption_is_per_real_owner_interval_and_reopens_next_owner_start(self):
        g = self.game()
        self.play(g)
        self.use(g)
        first = g.state.interactable_history[0]
        g.apply(EndTurn(1))
        with self.assertRaises(IllegalAction):
            self.use(g)
        g.apply(EndTurn(2))
        self.use(g)
        second = g.state.interactable_history[1]
        self.assertNotEqual(first.owner_turn_id, second.owner_turn_id)
        self.assertEqual(first.entity_id, second.entity_id)
        self.portable(g)

    def test_invested_spell_does_not_execute_its_body_or_pay_its_card_cost(self):
        self.script('lethal', lambda c: (Damage(c.state.players[2].hero_id, 30),))
        g = self.game((OPEN, 'lethal'))
        self.play(g)
        self.use(g)
        self.assertEqual(g.state.status, 'playing')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)
        self.assertEqual(g.state.players[1].mana, 5)
        self.portable(g)

    def test_current_hand_face_after_in_place_upgrade_is_valid_investment(self):
        from hs_sim.engine.hand_upgrades import UpgradeHandCard
        self.script('upgrade', lambda c: (UpgradeHandCard(
            CardReference.capture(c.state.entities[c.state.players[1].hand[-1]]), 'card.2'),))
        g = self.game((OPEN, 'upgrade', 'card.1'))
        self.play(g)
        self.play(g, 'upgrade')
        card = g.state.players[1].hand[0]
        self.use(g)
        self.assertEqual(g.state.interactable_history[0].invested.card_id, 'card.2')
        self.assertEqual(g.state.interactable_history[0].invested.entity_id, card)
        self.portable(g)

    def test_object_is_not_an_attack_source_or_target(self):
        g = self.game(board=('card.4',))
        self.play(g)
        obj = self.obj(g)
        hero = g.state.players[2].hero_id
        for action in (Attack(1, obj, hero), Attack(1, g.state.players[1].board[0], obj)):
            with self.assertRaises(IllegalAction):
                g.apply(action)
        self.assertFalse(any(type(a) is Attack and obj in (a.attacker_id, a.defender_id)
            for a in g.legal_actions()))

    def test_ordinary_damage_destroy_buff_silence_return_and_transform_skip_object(self):
        def touch(c):
            obj = next(eid for eid in c.state.players[1].board if c.state.entities[eid].card_id == OBJECT)
            return (Damage(obj, 99), Destroy(obj), Buff(obj, 5, 5), Silence(obj), ReturnToHand(obj), Transform(obj, 'card.1'))
        self.script('touch', touch)
        g = self.game((OPEN, 'touch', 'card.1'))
        self.play(g)
        obj = self.obj(g)
        before = g.state.entities[obj]
        self.play(g, 'touch')
        self.assertEqual(g.state.entities[obj], before)
        self.assertFalse(g.state.death_history)
        self.portable(g)

    def test_full_board_opener_has_no_object_and_no_false_minion_summon(self):
        g = self.game(board=('card.4',) * 7)
        original = g.state.players[1].board
        self.play(g)
        self.assertEqual(g.state.players[1].board, original)
        self.assertTrue(any(e.kind == 'interactable_install_skipped' for e in g.events))
        self.assertFalse(any(e.kind == 'minion_summoned' for e in g.events))
        self.portable(g)

    def test_last_board_slot_can_be_installed_and_full_use_removes_without_rng(self):
        g = self.game(board=('card.4',) * 6)
        self.play(g)
        rng = g._rng.getstate()
        card = self.use(g)
        self.assertEqual(g.state.entities[card].zone, Zone.SETASIDE)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual(g._rng.getstate(), rng)
        self.assertEqual(len([e for e in g.events if e.kind == 'random_choice_skipped']), 2)
        self.portable(g)

    def test_one_free_slot_summons_only_first_beast_and_consumes_one_random_draw(self):
        g = self.game(board=('card.4',) * 5)
        self.play(g)
        rng = random.Random()
        rng.setstate(g._rng.getstate())
        expected = rng.choice(BEASTS)
        self.use(g)
        self.assertEqual(g.state.entities[g.state.players[1].board[-1]].card_id, expected)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual(g._rng.getstate(), rng.getstate())
        self.portable(g)

    def test_installed_objects_have_independent_once_per_turn_usage(self):
        g = self.game((OPEN, OPEN, 'card.1', 'card.2'))
        self.play(g)
        self.play(g)
        objs = list(g.state.players[1].board)
        for obj in objs:
            g.apply(UseInteractable(1, obj, g.state.players[1].hand[0]))
        self.assertEqual([r.entity_id for r in g.state.interactable_history], objs)
        self.portable(g)

    def test_removal_reaction_wait_has_consumed_use_and_retired_hand_before_payload(self):
        self.options['watch'] = ('cards_removed_from_game', self.wait)
        g = self.game(board=('watch',))
        self.play(g)
        held = list(g.state.players[1].hand)
        self.use(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].hand, held[1:])
        self.assertEqual(len(g.state.players[1].board), 2)
        self.assertIsNone(g.state.interactable_history[0].finished_event)
        restored = self.portable(g)
        self.choose(g)
        self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(len(g.state.interactable_history), 1)
        self.assertEqual(len(g.state.players[1].board), 4)
        self.portable(g)

    def test_payload_choice_and_restored_queue_complete_one_root_without_reinvestment(self):
        self.options['wait_payload'] = True
        g = self.game()
        self.play(g)
        invested = self.use(g)
        restored = self.portable(g)
        self.choose(g)
        self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(g.state.players[1].setaside, [invested])
        self.assertEqual(len(g.state.interactable_history), 1)
        self.assertIsNotNone(g.state.interactable_history[0].finished_event)
        self.portable(g)

    def test_late_payload_error_rolls_back_investment_use_summons_information_and_rng(self):
        self.options['fault'] = True
        g = self.game()
        self.play(g)
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'missing.rift'):
            self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_player_command_uses_public_object_and_own_hand_handles(self):
        g = self.game()
        self.play(g)
        port = g.for_player(1)
        listing = port.legal_actions()
        actions = [a for a in listing['actions'] if a['type'] == 'use_interactable']
        self.assertEqual(len(actions), 2)
        self.assertEqual(set(actions[0]), {'type', 'object', 'card'})
        result = port.submit(dict(revision=listing['revision'], action=actions[0]))
        self.assertTrue(result['accepted'], result.get('error'))
        self.assertFalse(any(a['type'] == 'use_interactable' for a in port.legal_actions()['actions']))
        self.portable(g)

    def test_public_object_view_hides_internal_health_and_receipts(self):
        g = self.game()
        self.play(g)
        for viewer in (1, 2):
            obj = next(e for p in g.observe(viewer)['players'] for e in p['board'] if e['card_id'] == OBJECT)
            self.assertEqual(obj['interactable'], dict(used=False, uses_per_turn=1))
            self.assertFalse(set(obj) & {'attack', 'health', 'max_health', 'entity_id', 'owner_turn_id'})
        self.use(g)
        before = g.snapshot()
        for viewer in (1, 2):
            obj = next(e for p in g.observe(viewer)['players'] for e in p['board'] if e['card_id'] == OBJECT)
            self.assertTrue(obj['interactable']['used'])
            text = json.dumps((g.observe(viewer), g.player_events(viewer)))
            for field in ('interactable_history', 'invested', 'hand_entry_id', 'use_id', 'setaside'):
                self.assertNotIn(field, text)
            removed = next(e for e in g.player_events(viewer) if e['kind'] == 'cards_removed_from_game')
            self.assertEqual(removed['removed_cards'], [dict(player_id=1, from_zone='hand', card_id='card.1')])
            self.assertIsNone(removed['target'])
        self.assertEqual(g.snapshot(), before)
        self.portable(g)

    def test_enemy_hand_handle_and_raw_engine_ids_do_not_authorize_investment(self):
        g = self.game()
        self.play(g)
        port = g.for_player(1)
        listing = port.legal_actions()
        command = next(a for a in listing['actions'] if a['type'] == 'use_interactable')
        for card in (g.state.players[1].hand[0], port.observe()['observation']['players'][1]['hand'][0]['ref']):
            before = g.snapshot()
            result = port.submit(dict(revision=listing['revision'], action={**command, 'card': card}))
            self.assertFalse(result['accepted'])
            self.assertEqual(g.snapshot(), before)

    def test_second_player_investment_and_actor_port_remain_independent(self):
        g = self.game(actor=2)
        opponent_hand = g.state.players[1].hand
        self.play(g, actor=2)
        invested = self.use(g, actor=2)
        self.assertEqual(g.state.entities[invested].controller, 2)
        self.assertEqual(g.state.players[2].setaside, [invested])
        self.assertEqual(g.state.interactable_history[0].player_id, 2)
        self.assertEqual(g.state.players[1].hand, opponent_hand)
        self.portable(g)

    def test_snapshot_refuses_missing_history_or_completed_receipt(self):
        g = self.game()
        self.play(g)
        self.use(g)
        for change in (lambda s: s['state'].pop('interactable_history'),
                lambda s: s['state']['interactable_history'][0].update(finished_event=1),
                lambda s: s['state']['interactable_history'][0].update(player_id=2)):
            saved = json.loads(json.dumps(g.snapshot()))
            change(saved)
            with self.assertRaises(SnapshotError):
                Game.from_snapshot(saved, registry())

    def test_pending_root_requires_its_actual_finish_in_waiting_queue(self):
        self.options['wait_payload'] = True
        g = self.game()
        self.play(g)
        self.use(g)
        bad = self.portable(g)
        frame = bad._frame
        bad._frame = replace(frame, continuation=tuple(e for e in frame.continuation if type(e) is not FinishInteractableUse))
        with self.assertRaisesRegex(ValueError, 'completion'):
            validate_boundary(bad)

    def test_duplicate_owner_interval_use_history_is_rejected(self):
        g = self.game()
        self.play(g)
        self.use(g)
        bad = self.portable(g)
        record = bad._state.interactable_history[0]
        bad._state.interactable_history.append(replace(record, id=2))
        with self.assertRaisesRegex(ValueError, 'only once'):
            validate_boundary(bad)

    def test_object_marker_cannot_turn_an_ordinary_minion_inert(self):
        g = self.game(board=('card.4',))
        saved = json.loads(json.dumps(g.snapshot()))
        saved['state']['entities'][str(g.state.players[1].board[0])]['interactable_object'] = True
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, registry())

    def test_object_definition_cannot_be_created_as_normal_hand_card_or_summon(self):
        for name, effect, reason in (('hand', AddToHand(1, OBJECT), 'Unsupported generated hand card type'),
                ('summon', Summon(1, OBJECT), 'dedicated board installation')):
            self.scripts = []
            self.script(name, lambda c, e=effect: (e,))
            g = self.game((name,))
            before = g.snapshot()
            with self.assertRaisesRegex(ResolutionError, reason):
                self.play(g, name)
            self.assertEqual(g.snapshot(), before)

    def test_action_codec_requires_exact_owned_carrier_and_card_fields(self):
        from hs_sim.engine.actions import action_from_dict, action_to_dict
        action = UseInteractable(1, 7, 8)
        wire = action_to_dict(action)
        self.assertEqual(action_from_dict(wire), action)
        for change in (lambda d: d.pop('card_entity_id'), lambda d: d.update(target_id=8),
                lambda d: d.update(entity_id=True), lambda d: d.update(card_entity_id=0)):
            bad = dict(wire)
            change(bad)
            with self.assertRaises(ValueError):
                action_from_dict(bad)

    def test_ordinary_minion_target_domain_excludes_inert_carrier(self):
        from hs_sim.engine.model import TargetSpec
        from hs_sim.engine.targeting import legal_target_ids
        g = self.game(board=('card.4',))
        self.play(g)
        source = g.state.entities[g.state.players[1].hand[0]]
        definition = replace(g.registry.card(source.card_id),
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)))
        self.assertEqual(legal_target_ids(g.state, g.registry, source, definition),
            (g.state.players[1].board[0],))

    def test_carrier_definition_rejects_ordinary_combat_and_lifecycle_fields(self):
        definition = registry().card(OBJECT)
        self.assertFalse(definition.hand_playable)
        for change in (dict(attack=1), dict(health=2), dict(keywords=(Keyword.RUSH,)),
                dict(on_play='open.rift'), dict(on_use='use.rift'), dict(uses_per_turn=2),
                dict(corpse_value=1), dict(metadata=metadata(collectible=True))):
            r = registry()
            with self.assertRaises(ValueError):
                r.register_card(replace(definition, id='invalid.carrier', **change))

    def test_terminal_removal_reaction_retains_consumed_root_without_future_work(self):
        self.options['watch'] = ('cards_removed_from_game',
            lambda c: (Damage(c.state.players[2].hero_id, 30, c.source_id),))
        g = self.game(board=('watch',))
        self.play(g)
        spent = self.use(g)
        self.assertEqual(g.state.status, 'finished')
        self.assertEqual(g.state.winner, 1)
        self.assertEqual(g.state.players[1].setaside, [spent])
        self.assertIsNone(g.state.interactable_history[0].finished_event)
        self.assertEqual(len(g.state.players[1].board), 2)
        self.assertFalse(g.legal_actions())
        self.portable(g)


if __name__ == '__main__':
    unittest.main()
