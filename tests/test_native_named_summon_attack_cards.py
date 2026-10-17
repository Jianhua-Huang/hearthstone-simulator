"""Native fixed summons retain exact deliveries across entry and combat waits."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_named_summon_attack_cards import TRAVELER, SHADOW, PREFIX, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, Keyword,
    PlayCard, PlayerSetup, Ruleset, Scenario, SelectChoice, SnapshotError, TargetSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, Destroy, InvokeBehavior,
    RequestChoice, ReturnToHand, Transform, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec, RewindSpec, SummonQuantitySpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P = 'k142.'
YETI = 'CORE_CS2_182'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


def registry(mode=None):
    r = build_registry()
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('K142 deliberate failure')))
    r.register_behavior(P+'noop', lambda c: ())
    scripts = {
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'trigger': lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        'twice_trigger': lambda c: (TriggerDeathrattles(c.target_id, c.source_id, times=2),),
        'rewind': lambda c: () if c.rewind_attempt else (Destroy(c.target_id, c.source_id),),
        'reenter': lambda c: (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),
            c.state.entities[c.target_id].controller, cause=SummonCause.capture(c)),),
    }
    for name, body in scripts.items():
        r.register_behavior(P+name, body)
        if name == 'reenter':
            continue
        kw = dict(keywords=(Keyword.REWIND,), rewind=RewindSpec()) if name == 'rewind' else {}
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, cost=1, on_play=P+name,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)), metadata=META, **kw))
    r.register_card(CardDefinition(P+'tank', 'Current enemy tank', CardType.MINION,
        attack=1, health=20, metadata=META))
    r.register_card(CardDefinition(P+'twice', 'Ordinary quantity source', CardType.MINION,
        health=5, metadata=META, summon_quantities=(SummonQuantitySpec(),)))
    r.register_card(CardDefinition(P+'dormant', 'Excluded dormant enemy', CardType.MINION,
        health=20, dormant_turns=20, metadata=META))
    r.register_card(CardDefinition(P+'location', 'Excluded physical location', CardType.LOCATION,
        durability=3, on_use=P+'noop', metadata=META))
    r.register_behavior(P+'bomb', lambda c: (Damage(c.state.players[1].hero_id, 30, c.source_id),))
    r.register_card(CardDefinition(P+'bomb', 'Actual terminal combat reaction', CardType.MINION,
        attack=1, health=3, deathrattle=P+'bomb', metadata=META))
    if mode:
        event = 'attack_declared' if mode == 'combat' else 'minion_summoned'

        def eligible(c):
            eid = c.event.source_id if mode == 'combat' else c.event.target_id
            current = c.state.entities.get(eid)
            return current is not None and any(root.request.cause.source.card_id == TRAVELER and
                any(d.entity is not None and (d.entity.entity_id, d.entity.entered_order) ==
                    (eid, current.entered_order) for d in root.deliveries) for root in c.state.card_summon_history)

        def watch(c):
            if mode == 'fail':
                return (InvokeBehavior(P+'fail', c.source_id, 1),)
            eid = c.event.target_id
            options = [ChoiceOption('ok', 'Continue'),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'fail', c.source_id, 1),)),
                ChoiceOption('reenter', 'Leave and reenter same entity', (ReturnToHand(eid),
                    InvokeBehavior(P+'reenter', c.source_id, 1, target_id=eid)))]
            if mode != 'combat':
                options.extend((ChoiceOption('kill', 'Destroy original receiver', (Destroy(eid, c.source_id),)),
                    ChoiceOption('transfer', 'Transfer original receiver', (ChangeControl(eid, 2),)),
                    ChoiceOption('transform', 'Transform same continuous body', (Transform(eid, YETI),))))
            return (RequestChoice(1, tuple(options), c.source_id),)

        r.register_behavior(P+'watch', watch)
        r.register_trigger_condition(P+'eligible', eligible)
        r.register_card(CardDefinition(P+'watch', 'Actual boundary witness', CardType.WEAPON,
            durability=5, metadata=META,
            limited_triggers=(LimitedTriggerSpec(event, P+'watch', condition_id=P+'eligible'),)))
    r.validate()
    return r


@lru_cache(maxsize=None)
def shared(mode):
    return registry(mode)


def wires(value, name):
    if isinstance(value, dict):
        if value.get('type', '').endswith('.'+name):
            yield value
        for child in value.values():
            yield from wires(child, name)
    elif isinstance(value, list):
        for child in value:
            yield from wires(child, name)


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


def edit_controls(value, kind):
    if isinstance(value, dict):
        for child in value.values():
            edit_controls(child, kind)
    elif isinstance(value, list):
        found = next((i for i, x in enumerate(value) if isinstance(x, dict) and
            x.get('type', '').endswith('.ContinueNamedMinion')), None)
        if found is not None:
            original = value[found]
            if kind == 'drop':
                value.pop(found)
            else:
                value.insert(found, deepcopy(original))
        for child in list(value):
            edit_controls(child, kind)


class NativeNamedSummonAttackTests(unittest.TestCase):
    def game(self, hand=(P+'kill',), board=(TRAVELER,), enemy=(YETI,), mode=None, limit=7):
        self.mode = mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board,
            deck=(YETI,)*10, mana=30, max_mana=30, mana_cap=30,
            weapon_card_id=P+'watch' if mode else None),
            PlayerSetup('HERO_08', board=enemy, deck=(YETI,)*10, mana=30, max_mana=30, mana_cap=30)),
            seed=142), shared(mode), ruleset=Ruleset(max_board=limit))

    def first(self, g, cid, zone='board', player=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None):
        source = self.first(g, cid, 'hand').id
        g.apply(PlayCard(1, source, target))
        return source

    def kill(self, g):
        return self.play(g, P+'kill', self.first(g, TRAVELER).id)

    def choose(self, g, key='ok'):
        g.apply(SelectChoice(1, g.state.pending_choice.id, (key,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(self.mode))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(self.mode)).snapshot(), saved)
        return other

    def test_complete_parent_shadow_four_faces_and_exact_old_dependency(self):
        from tools.card_batch import check_face
        d = load_batch()
        rows = {x['record']['id']: x['record'] for x in d['cards']+d['existing_dependencies']}
        self.assertEqual(len(d['official_observations']), 4)
        for o in d['official_observations']:
            check_face(rows[o['card_id']], o['face'], o['locale'])
        r = shared(None)
        raw = rows[TRAVELER]
        self.assertEqual((r.card(TRAVELER).cost, r.card(TRAVELER).attack, r.card(TRAVELER).health,
            r.card(TRAVELER).metadata), (3, 4, 1, metadata_from_record(raw)))
        self.assertEqual(canonical_digest(asdict(r.card(SHADOW))), d['existing_dependency_definition_pins'][SHADOW])
        self.assertFalse(r.card(SHADOW).keywords)

    def test_native_hand_play_pays_only_body_and_does_not_run_deathrattle(self):
        g = self.game((TRAVELER,), board=())
        source = self.play(g, TRAVELER)
        self.assertEqual(g.state.players[1].mana, 27)
        self.assertEqual(g.state.entities[source].zone, Zone.BOARD)
        self.assertFalse(g.state.card_summon_history)

    def test_real_natural_death_summons_exact_shadow_and_attacks_by_ordinary_combat(self):
        g = self.game(board=(SHADOW, TRAVELER))
        old = self.first(g, SHADOW).id
        self.kill(g)
        root, = g.state.card_summon_history
        delivery, = root.deliveries
        self.assertNotEqual(delivery.entity.entity_id, old)
        self.assertTrue(delivery.followup_started)
        self.assertEqual(root.status, 'completed')
        self.assertEqual(g.state.entities[delivery.entity.entity_id].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[old].zone, Zone.BOARD)
        self.assertEqual(self.first(g, YETI, player=2).health, 1)
        self.assertEqual(len(g.state.character_attack_history), 1)
        self.assertEqual(g.state.players[1].mana, 29)
        self.portable(g)

    def test_no_enemy_minion_does_not_attack_hero_dormant_or_location_or_use_rng(self):
        for enemy in ((), (P+'dormant', P+'location')):
            with self.subTest(enemy=enemy):
                g = self.game(enemy=enemy)
                rng = g._rng.getstate()
                self.kill(g)
                self.assertEqual(g._rng.getstate(), rng)
                self.assertEqual(self.first(g, SHADOW).health, 1)
                self.assertFalse(g.state.character_attack_history)
                self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)

    def test_live_trigger_keeps_carrier_and_uses_actual_receiver_to_its_right(self):
        g = self.game((P+'trigger',), enemy=())
        carrier = self.first(g, TRAVELER).id
        self.play(g, P+'trigger', carrier)
        self.assertEqual(g.state.players[1].board, [carrier, self.first(g, SHADOW).id])
        self.assertFalse(g.state.death_history)
        self.assertTrue(g.state.card_summon_history[0].deliveries[0].followup_started)

    def test_original_recipient_player_is_separate_from_active_killing_player(self):
        g = self.game(board=(YETI,), enemy=(TRAVELER,))
        self.play(g, P+'kill', self.first(g, TRAVELER, player=2).id)
        root, = g.state.card_summon_history
        self.assertEqual(root.request.player_id, 2)
        self.assertEqual(self.first(g, YETI).health, 1)
        self.assertEqual(g.state.players[1].mana, 29)
        self.assertEqual(g.state.players[2].mana, 30)

    def test_quantity_extras_each_follow_their_delivery_and_reuse_new_space_after_combat(self):
        g = self.game(board=(P+'twice', TRAVELER), enemy=(P+'tank',), limit=2)
        self.kill(g)
        root, = g.state.card_summon_history
        self.assertEqual(root.plan.total, 2)
        self.assertEqual(len(root.deliveries), 2)
        self.assertTrue(all(d.outcome == 'delivered' and d.followup_started for d in root.deliveries))
        self.assertEqual(self.first(g, P+'tank', player=2).health, 12)
        self.assertEqual(len(g.state.character_attack_history), 2)
        self.portable(g)

    def test_two_actual_deathrattle_invocations_have_independent_roots_and_receipts(self):
        g = self.game((P+'twice_trigger',))
        self.play(g, P+'twice_trigger', self.first(g, TRAVELER).id)
        self.assertEqual(len(g.state.card_summon_history), 2)
        self.assertEqual(len({x.id for x in g.state.card_summon_history}), 2)
        self.assertEqual(len(g.state.character_attack_history), 2)
        self.assertEqual(self.first(g, TRAVELER).zone, Zone.BOARD)

    def test_entry_wait_restore_clone_replay_failure_and_single_bound_callback(self):
        g = self.game(mode='entry')
        self.kill(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(g.state.card_summon_history[0].deliveries[0].followup_started)
        other, saved = self.portable(g), g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(g.state.character_attack_history), 1)

    def test_entry_death_control_or_reentry_never_redirects_to_same_named_or_new_body(self):
        for key in ('kill', 'transfer', 'reenter'):
            with self.subTest(key=key):
                g = self.game(board=(SHADOW, TRAVELER), mode='entry')
                self.kill(g)
                self.choose(g, key)
                self.assertIsNone(g.state.pending_choice)
                self.assertFalse(g.state.character_attack_history)
                self.assertEqual(g.state.card_summon_history[0].status, 'completed')

    def test_same_residence_transform_uses_current_body_without_rebinding(self):
        g = self.game(enemy=(P+'tank',), mode='entry')
        self.kill(g)
        target = g.state.card_summon_history[0].deliveries[0].entity.entity_id
        self.choose(g, 'transform')
        self.assertEqual(g.state.entities[target].card_id, YETI)
        self.assertEqual((g.state.entities[target].health, self.first(g, P+'tank', player=2).health), (4, 16))
        self.assertEqual(len(g.state.character_attack_history), 1)

    def test_combat_wait_restore_and_original_defender_reentry_cancels_old_attack(self):
        g = self.game(mode='combat')
        self.kill(g)
        self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g)
        for game in (g, other):
            self.choose(game, 'reenter')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.first(g, YETI, player=2).health, 5)
        self.assertEqual(self.first(g, SHADOW).health, 1)
        self.assertFalse(g.state.damage_history)

    def test_entry_exception_and_terminal_combat_preserve_native_transaction_boundaries(self):
        g = self.game(mode='fail')
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.kill(g)
        self.assertEqual(g.snapshot(), saved)
        g = self.game(board=(P+'twice', TRAVELER), enemy=(P+'bomb',))
        self.kill(g)
        root, = g.state.card_summon_history
        self.assertEqual((g.state.winner, root.status, len(root.deliveries)), (2, 'interrupted', 1))
        self.assertTrue(root.deliveries[0].followup_started)

    def test_actual_rewind_retires_named_roots_but_preserves_complete_diagnostic_receipts(self):
        g = self.game((P+'rewind',))
        self.play(g, P+'rewind', self.first(g, TRAVELER).id)
        self.assertIsNotNone(g.state.pending_choice)
        self.choose(g, 'retry')
        self.assertFalse(g.state.card_summon_history)
        self.assertFalse(g.state.character_attack_history)
        self.assertTrue(any(e.kind == 'named_summon_followup_started' for e in g.events))
        self.assertEqual(self.first(g, TRAVELER).zone, Zone.BOARD)
        self.portable(g)

    def test_rehashed_callback_receiver_behavior_queue_and_material_edits_are_rejected(self):
        g = self.game(mode='entry')
        self.kill(g)
        original = g.snapshot()
        for kind in ('index', 'residence', 'behavior', 'drop', 'duplicate', 'material'):
            with self.subTest(kind=kind):
                saved = deepcopy(original)
                if kind in ('drop', 'duplicate'):
                    edit_controls(saved['resolution_frame'], kind)
                elif kind == 'material':
                    saved['state']['card_summon_history'][0]['request']['materials'][0]['on_summon'] = None
                else:
                    wire = next(wires(saved['resolution_frame'], 'ContinueNamedMinion'))
                    if kind == 'index':
                        wire['fields']['index'] = 1
                    if kind == 'residence':
                        wire['fields']['beneficiary']['fields']['presence_id'] += 1
                    if kind == 'behavior':
                        wire['fields']['behavior_id'] = P+'noop'
                with self.assertRaises((SnapshotError, ValueError)):
                    Game.from_snapshot(rehash(saved), registry(self.mode))

    def test_started_event_receipt_and_old_schema_are_checked_and_player_dto_stays_private(self):
        g = self.game(mode='combat')
        self.kill(g)
        saved = g.snapshot()
        saved['events'] = [e for e in saved['events'] if e['kind'] != 'named_summon_followup_started']
        from types import SimpleNamespace
        from hs_sim.engine.named_summon_followups import validate_events
        with self.assertRaisesRegex(ValueError, 'receipts differ'):
            validate_events(SimpleNamespace(_events=tuple(e for e in g.events if
                e.kind != 'named_summon_followup_started')), {r.id: r for r in g.state.card_summon_history})
        with self.assertRaises((SnapshotError, ValueError)):
            Game.from_snapshot(rehash(saved), registry(self.mode))
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for key in ('on_summon', 'followup', 'resolution_frame', 'card_summon_history', 'rng_state'):
                self.assertNotIn('"'+key+'"', public)
        old = g.snapshot()
        old['schema_version'] = 348
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(old, registry(self.mode))


if __name__ == '__main__':
    unittest.main()
