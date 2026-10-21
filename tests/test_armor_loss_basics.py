"""Direct Hero armor removal is an account delta, never damage or payment."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (ArmorLossResult, CardDefinition, CardType, Game,
    HealthFlow, HealthLayer, HealthOp, HealthRule, Keyword, LoseArmor, PlayCard,
    PlayerSetup, Registry, ResolutionError, Scenario, SelectChoice, SnapshotError,
    TriggerSpec, armor_loss_result)
from hs_sim.engine.effects import (ChoiceOption, Damage, GainArmor, InvokeBehavior,
    ReplaceHero, RequestChoice)
from hs_sim.engine.model import Event
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resources import validate_armor_loss_events
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT = Path(__file__).resolve().parents[1]
PIN = 'c2e42381e7f12ea45574fc6c558d490e5986809b42da2074f5f97751df60e947'


def evidence():
    value = json.loads((ROOT / 'data/support/armor-loss-basics.json').read_bytes())
    if canonical_digest(value) != PIN:
        raise ValueError('Direct armor loss evidence changed')
    return value


def registry():
    r = Registry('isolated-direct-armor-loss-v1')
    for name, keywords in (('hero', ()), ('immune', (Keyword.IMMUNE,)),
            ('shield', (Keyword.DIVINE_SHIELD,)), ('replacement', ())):
        r.register_card(CardDefinition(name, 'Diagnostic ' + name, CardType.HERO,
            health=80, keywords=keywords, metadata=metadata()))
    r.register_card(CardDefinition('plain', 'Diagnostic minion', CardType.MINION,
        health=5, metadata=metadata()))
    r.register_card(CardDefinition('cap', 'Diagnostic damage cap', CardType.MINION,
        health=5, health_rules=(HealthRule(HealthFlow.DAMAGE, HealthOp.CAP, 1,
            layer=HealthLayer.TARGET, target_relation='friendly',
            target_kinds=(CardType.HERO,)),), metadata=metadata()))
    def result(c):
        row = c.armor_result
        if type(row) is not ArmorLossResult or c.state.entities[row.hero_id].armor != row.after:
            raise ResolutionError('Direct armor callback lost its original debit context')
        return (GainArmor(3 - row.player_id, row.actual),)
    r.register_behavior('result', result)
    def explode(c):
        raise ResolutionError('Diagnostic armor failure')
    r.register_behavior('explode', explode)
    def waiting(c):
        row = c.armor_result
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', (GainArmor(3 - row.player_id, row.actual),)),
            ChoiceOption('fault', 'Fail', (InvokeBehavior('explode', c.source_id, c.player_id),)),
        ), c.source_id),)
    r.register_behavior('waiting', waiting)
    scripts = {
        'fixed': lambda c: (LoseArmor(2, 5, c.source_id),),
        'all': lambda c: (LoseArmor(2, source_id=c.source_id),),
        'zero': lambda c: (LoseArmor(2, 0, c.source_id),),
        'own': lambda c: (LoseArmor(1, 5, c.source_id),),
        'result': lambda c: (LoseArmor(2, 5, c.source_id, 'result'),),
        'wait': lambda c: (LoseArmor(2, 5, c.source_id, 'waiting'),),
        'fault': lambda c: (LoseArmor(2, 5, c.source_id), InvokeBehavior('explode', c.source_id, 1)),
        'bad-source': lambda c: (LoseArmor(2, 5, 999999),),
        'bad-callback': lambda c: (LoseArmor(2, 5, c.source_id, 'unknown'),),
        'replace': lambda c: (ReplaceHero(2, 'replacement', armor=4), LoseArmor(2, source_id=c.source_id)),
        'sequential': lambda c: (LoseArmor(2, 5, c.source_id), LoseArmor(2, source_id=c.source_id)),
        'after': lambda c: (LoseArmor(2, 5, c.source_id), GainArmor(2, 2)),
        'system': lambda c: (LoseArmor(2, 5),),
        'damage': lambda c: (Damage(c.state.players[2].hero_id, 5, c.source_id),),
    }
    for name, script in scripts.items():
        behavior = 'spell.' + name
        r.register_behavior(behavior, script)
        r.register_card(CardDefinition(name, 'Diagnostic ' + name, CardType.SPELL,
            on_play=behavior, metadata=metadata()))
    r.register_behavior('react', lambda c: (GainArmor(c.event.player_id, 7),))
    r.register_card(CardDefinition('reactor', 'Diagnostic loss reaction', CardType.MINION,
        health=5, triggers=(TriggerSpec('armor_lost', 'react'),), metadata=metadata()))
    r.register_behavior('damage-watch', lambda c: (GainArmor(c.player_id, 1),))
    r.register_card(CardDefinition('watch', 'Diagnostic damage listener', CardType.MINION,
        health=5, triggers=(TriggerSpec('damage_dealt', 'damage-watch'),), metadata=metadata()))
    raw = next(x for x in evidence()['records'] if x['id'] == 'DRG_069')
    r.register_behavior('platebreaker', lambda c: (LoseArmor(3 - c.player_id, source_id=c.source_id),))
    r.register_card(CardDefinition(raw['id'], raw['name'], CardType.MINION,
        cost=raw['cost'], attack=raw['attack'], health=raw['health'],
        on_play='platebreaker', metadata=metadata_from_record(raw)))
    return r


class ArmorLossTests(unittest.TestCase):
    def game(self, hand=('fixed',), armor=9, own_armor=0, enemy_hero='hero', board=(), enemy_board=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=('plain',) * 6,
                armor=own_armor, max_mana=10, mana=10),
            PlayerSetup(enemy_hero, board=enemy_board, hand=('plain',),
                deck=('plain',) * 6, armor=armor, max_mana=10, mana=10)), seed=142), registry())

    def play(self, g, name):
        card = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, card))

    def hero(self, g, p=2):
        return g.state.entities[g.state.players[p].hero_id]

    def rows(self, g):
        return [armor_loss_result(e) for e in g.events if e.kind == 'armor_loss_resolved']

    def portable(self, g):
        snapshot = g.snapshot()
        for h in (Game.from_snapshot(json.loads(json.dumps(snapshot)), registry()),
                g.clone(), replay(build_replay(g), registry())):
            self.assertEqual(h.snapshot(), snapshot)
            for viewer in (1, 2):
                self.assertEqual(h.observe(viewer), g.observe(viewer))
                self.assertEqual(h.player_events(viewer), g.player_events(viewer))
        return snapshot

    def test_one_necessary_real_adapter_retains_all_five_raw_records(self):
        value = evidence()
        self.assertEqual(len(value['records']), 5)
        self.assertFalse(value['CN_calibrated'])
        self.assertEqual(value['new_combinations'], 0)
        for name in ('AV_109', 'MIS_902', 'TTN_803', 'YOG_500'):
            self.assertNotIn(name, registry().cards)
        g = self.game(hand=('DRG_069',), armor=17)
        self.play(g, 'DRG_069')
        self.assertEqual((self.hero(g).armor, g.state.players[1].mana), (0, 5))
        self.assertIsNone(self.rows(g)[0].requested)
        self.assertEqual(self.rows(g)[0].actual, 17)
        self.portable(g)

    def test_requested_fixed_loss_uses_current_balance(self):
        g = self.game()
        self.play(g, 'fixed')
        self.assertEqual(self.hero(g).armor, 4)
        self.assertEqual(self.rows(g), [ArmorLossResult(2, self.hero(g).id, 5, 9, 4, 5)])
        self.portable(g)

    def test_loss_is_capped_and_never_negative(self):
        g = self.game(armor=3)
        self.play(g, 'fixed')
        self.assertEqual((self.hero(g).armor, self.rows(g)[0].actual), (0, 3))
        self.portable(g)

    def test_all_loss_reads_entire_balance(self):
        g = self.game(hand=('all',), armor=25)
        self.play(g, 'all')
        self.assertEqual((self.hero(g).armor, self.rows(g)[0].actual), (0, 25))
        self.portable(g)

    def test_zero_request_keeps_armor_without_positive_loss_event(self):
        g = self.game(hand=('zero',))
        self.play(g, 'zero')
        self.assertEqual((self.hero(g).armor, self.rows(g)[0].actual), (9, 0))
        self.assertFalse(any(e.kind == 'armor_lost' for e in g.events))
        self.portable(g)

    def test_empty_balance_has_result_but_no_positive_reaction(self):
        g = self.game(hand=('all',), armor=0, board=('reactor',))
        self.play(g, 'all')
        self.assertEqual((self.hero(g).armor, self.rows(g)[0].actual), (0, 0))
        self.assertFalse(any(e.kind == 'armor_lost' for e in g.events))
        self.portable(g)

    def test_own_player_account_and_optional_system_source(self):
        g = self.game(hand=('own', 'system'), own_armor=8)
        self.play(g, 'own')
        self.assertEqual((self.hero(g, 1).armor, self.hero(g).armor), (3, 9))
        self.play(g, 'system')
        self.assertIsNone(next(e.source_id for e in g.events if e.kind == 'armor_lost' and e.player_id == 2))
        self.portable(g)

    def test_immune_shield_and_damage_cap_do_not_block_removal(self):
        for hero, board in (('immune', ()), ('shield', ()), ('hero', ('cap',))):
            with self.subTest(hero=hero):
                g = self.game(hand=('all',), enemy_hero=hero, enemy_board=board)
                before = self.hero(g)
                self.play(g, 'all')
                self.assertEqual((self.hero(g).armor, self.hero(g).health), (0, 80))
                self.assertEqual(self.hero(g).keywords, before.keywords)
                self.portable(g)

    def test_removal_does_not_publish_damage_health_or_payment(self):
        g = self.game(board=('watch',))
        self.play(g, 'fixed')
        self.assertEqual((self.hero(g, 1).armor, self.hero(g).health), (0, 80))
        self.assertFalse({'damage_dealt', 'damage_prevented', 'health_lost', 'armor_spent'} & {e.kind for e in g.events})
        self.assertEqual(g.state.damage_history, [])
        self.assertEqual(g.state.hero_health_change_history, [])
        self.portable(g)

    def test_damage_and_direct_removal_keep_distinct_facts(self):
        g = self.game(hand=('damage', 'fixed'), board=('watch',))
        self.play(g, 'damage')
        self.assertEqual(self.hero(g, 1).armor, 1)
        self.assertFalse(self.rows(g))
        self.play(g, 'fixed')
        self.assertEqual((self.hero(g, 1).armor, self.rows(g)[0].actual), (1, 4))
        self.portable(g)

    def test_callback_reads_actual_delta_and_not_requested_value(self):
        g = self.game(hand=('result',), armor=3)
        self.play(g, 'result')
        self.assertEqual((self.hero(g, 1).armor, self.hero(g).armor), (3, 0))
        self.portable(g)

    def test_zero_callback_executes_with_immutable_zero_result(self):
        g = self.game(hand=('wait',), armor=0)
        self.play(g, 'wait')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.rows(g)[0].actual, 0)
        self.portable(g)

    def test_reactions_precede_callback_without_changing_original_context(self):
        g = self.game(hand=('result',), armor=3, board=('reactor',))
        self.play(g, 'result')
        self.assertEqual((self.hero(g).armor, self.hero(g, 1).armor), (7, 3))
        gains = [e for e in g.events if e.kind == 'armor_gained']
        self.assertEqual([(e.player_id, e.amount) for e in gains], [(2, 7), (1, 3)])
        self.assertEqual((self.rows(g)[0].before, self.rows(g)[0].after), (3, 0))
        self.portable(g)

    def test_sequential_operations_read_new_current_balance(self):
        g = self.game(hand=('sequential',))
        self.play(g, 'sequential')
        self.assertEqual([(x.before, x.after, x.actual) for x in self.rows(g)], [(9, 4, 5), (4, 0, 4)])
        self.portable(g)

    def test_replacement_uses_new_installed_hero_not_retired_hero(self):
        g = self.game(hand=('replace',))
        old = self.hero(g).id
        self.play(g, 'replace')
        self.assertNotEqual(self.hero(g).id, old)
        self.assertEqual((self.rows(g)[0].hero_id, self.rows(g)[0].before), (self.hero(g).id, 13))
        self.assertEqual(g.state.entities[old].armor, 9)
        self.assertEqual(self.hero(g).armor, 0)
        self.portable(g)

    def test_waiting_resumes_after_json_restore_clone_and_replay(self):
        g = self.game(hand=('wait',), armor=3, board=('reactor',))
        self.play(g, 'wait')
        snapshot = self.portable(g)
        h = Game.from_snapshot(deepcopy(snapshot), registry())
        action = SelectChoice(2, g.state.pending_choice.id, ('ok',))
        g.apply(action)
        h.apply(action)
        self.assertEqual(g.snapshot(), h.snapshot())
        self.assertEqual((self.hero(g).armor, self.hero(g, 1).armor), (7, 3))
        self.portable(g)

    def test_action_and_choice_exceptions_keep_transaction_boundaries(self):
        g = self.game(hand=('fault',))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'fault')
        self.assertEqual(g.snapshot(), before)
        h = self.game(hand=('wait',))
        self.play(h, 'wait')
        before = h.snapshot()
        with self.assertRaises(ResolutionError):
            h.apply(SelectChoice(2, h.state.pending_choice.id, ('fault',)))
        self.assertEqual(h.snapshot(), before)
        self.portable(h)

    def test_unknown_source_and_callback_are_rejected_with_rollback(self):
        for name in ('bad-source', 'bad-callback'):
            with self.subTest(name=name):
                g = self.game(hand=(name,))
                before = g.snapshot()
                with self.assertRaises(ResolutionError):
                    self.play(g, name)
                self.assertEqual(g.snapshot(), before)

    def test_strict_effect_and_result_inputs(self):
        for amount in (True, -1, 2.0, '5'):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                LoseArmor(1, amount)
        with self.assertRaises(ValueError):
            LoseArmor(1, on_result='result')
        with self.assertRaises(ValueError):
            LoseArmor(3)
        row = ArmorLossResult(1, 2, 5, 3, 0, 3)
        for change in ({'actual': 5}, {'after': 1}, {'before': True}, {'hero_id': 0}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(row, **change)

    def test_result_parser_rejects_missing_duplicate_and_changed_headers(self):
        row = ArmorLossResult(1, 2, 5, 3, 0, 3)
        event = Event(1, 1, 'armor_loss_resolved', target_id=2, player_id=1, amount=3,
            data=(('result', row.payload()),))
        self.assertEqual(armor_loss_result(event), row)
        self.assertIsNone(armor_loss_result(None))
        self.assertIsNone(armor_loss_result(replace(event, kind='unrelated')))
        for bad in (replace(event, amount=5), replace(event, player_id=2),
                replace(event, data=()), replace(event, data=(('result', row.payload()[:-1]),)),
                replace(event, data=(('result', row.payload() + (('actual', 3),)),)),
                replace(event, data=(('result', list(row.payload())),))):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                armor_loss_result(bad)
        with self.assertRaises(ValueError):
            armor_loss_result(replace(event, kind='armor_lost', amount=0,
                data=(('result', ArmorLossResult(1, 2, 0, 3, 3, 0).payload()),)))

    def test_event_validation_preserves_pairs_and_retained_hero_identity(self):
        g = self.game()
        self.play(g, 'fixed')
        events = list(g.events)
        resolved = next(i for i, e in enumerate(events) if e.kind == 'armor_loss_resolved')
        for bad in (events[:resolved + 1] + events[resolved + 2:],
                events[:resolved] + events[resolved + 1:]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_armor_loss_events(g.state, bad)
        bad = list(events)
        bad[resolved + 1] = replace(bad[resolved + 1], source_id=None)
        with self.assertRaises(ValueError):
            validate_armor_loss_events(g.state, bad)

    def test_rehashed_snapshot_rejects_inconsistent_result_and_old_schema(self):
        g = self.game()
        self.play(g, 'fixed')
        snapshot = self.portable(g)
        bad = deepcopy(snapshot)
        row = next(e for e in bad['events'] if e['kind'] == 'armor_loss_resolved')
        row['amount'] = 6
        bad['events_hash'] = canonical_hash(bad['events'])
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(bad, registry())
        bad = deepcopy(snapshot)
        bad['schema_version'] = 241
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(bad, registry())

    def test_player_projection_exposes_delta_without_private_result(self):
        g = self.game(hand=('after',))
        self.play(g, 'after')
        before = g.snapshot()
        for viewer in (1, 2):
            view = g.for_player(viewer).observe()['observation']
            self.assertEqual(view['version'], 'player-view-v114')
            self.assertEqual(view['players'][1]['hero']['armor'], 6)
            events = g.player_events(viewer)
            loss = [e for e in events if e['kind'] == 'armor_lost']
            self.assertEqual([e['amount'] for e in loss], [5])
            text = json.dumps(events)
            self.assertNotIn('armor_loss_resolved', text)
            self.assertNotIn('"result"', text)
            self.assertNotIn('"requested"', text)
        self.assertEqual(g.snapshot(), before)
        self.portable(g)


if __name__ == '__main__':
    unittest.main()
