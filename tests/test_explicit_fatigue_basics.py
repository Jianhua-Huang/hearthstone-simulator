"""One actual fatigue tick and one pinned native representative, without combos."""
from copy import deepcopy
from pathlib import Path
import json
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, EndTurn, Game,
    HealthFlow, HealthLayer, HealthOp, HealthRule, Keyword, PlayCard, PlayerSetup,
    Registry, ResolutionError, Scenario, SelectChoice, SnapshotError, TakeFatigue,
    health_result)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (Buff, ChoiceOption, Damage, Draw, GainArmor,
    InvokeBehavior, RequestChoice, Silence)
from hs_sim.engine.model import DamageKind
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT = Path(__file__).resolve().parents[1]
PIN = '817ec01bae5e9ba04537bb98134ad3c45d1343500634b76fdc1fe570256f60b3'


def evidence():
    packet = json.loads((ROOT/'data/support/explicit-fatigue-basics.json').read_bytes())
    if canonical_digest(packet) != PIN:
        raise ValueError('Fatigue representative requires the complete pinned raw packet')
    return packet


def registry():
    r = Registry('explicit-fatigue-basics-v1')
    for cid, keywords, rules in (
        ('ft.hero', (), ()), ('ft.immune', (Keyword.IMMUNE,), ()),
        ('ft.cap', (), (HealthRule(HealthFlow.DAMAGE, HealthOp.CAP, 1,
            layer=HealthLayer.TARGET, target_relation='friendly',
            target_kinds=(CardType.HERO,)),)),
    ):
        r.register_card(CardDefinition(cid, cid, CardType.HERO, health=30,
            keywords=keywords, health_rules=rules, metadata=metadata(collectible=False)))
    for cid in ('ft.filler', 'ft.hidden'):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=1,
            metadata=metadata()))
    raw = evidence()['records'][0]
    def growth(c):
        if c.event is None or c.event.kind != 'fatigue':
            raise ResolutionError('Native growth requires its original fatigue event')
        return (Buff(c.source_id, c.event.amount, c.event.amount),)
    r.register_behavior('ft.growth', growth)
    r.register_behavior('ft.native', lambda c: (
        TakeFatigue(c.player_id, c.source_id, 'ft.growth'),))
    r.register_card(CardDefinition(raw['id'], raw['name'], CardType.MINION,
        cost=raw['cost'], attack=raw['attack'], health=raw['health'],
        battlecry='ft.native', metadata=metadata(CardClass.WARLOCK, tribes=('demon',))))
    def fail(c): raise ResolutionError('Deliberate fatigue callback failure')
    def wait(c):
        amount = c.event.amount if c.event is not None and c.event.kind == 'fatigue' else 0
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', (GainArmor(c.player_id, amount),)),
            ChoiceOption('bad', 'Fail', (TakeFatigue(c.player_id, c.source_id),
                InvokeBehavior('ft.fail', c.source_id, c.player_id))),
        ), c.source_id),)
    r.register_behavior('ft.fail', fail)
    r.register_behavior('ft.wait', wait)
    operations = {
        'tick': lambda c: (TakeFatigue(c.player_id, c.source_id),),
        'enemy': lambda c: (TakeFatigue(3-c.player_id, c.source_id),),
        'twice': lambda c: (TakeFatigue(c.player_id, c.source_id), TakeFatigue(c.player_id, c.source_id)),
        'draw': lambda c: (Draw(c.player_id, source_id=c.source_id),),
        'fixed': lambda c: (Damage(c.state.players[c.player_id].hero_id, 4, kind=DamageKind.FATIGUE),),
        'wait.before': lambda c: (*wait(c), TakeFatigue(c.player_id, c.source_id)),
        'wait.after': lambda c: (TakeFatigue(c.player_id, c.source_id, 'ft.wait'), TakeFatigue(c.player_id, c.source_id)),
        'invalid': lambda c: (TakeFatigue(c.player_id, 999999),),
        'unknown': lambda c: (TakeFatigue(c.player_id, c.source_id, 'ft.missing.callback'),),
        'fail.after': lambda c: (TakeFatigue(c.player_id, c.source_id, 'ft.fail'),),
        'fatal.tick': lambda c: (Damage(c.state.players[c.player_id].hero_id, 29,
            c.source_id, DamageKind.SPELL), TakeFatigue(c.player_id, c.source_id),
            TakeFatigue(c.player_id, c.source_id), GainArmor(c.player_id, 99)),
        'fatal.draw': lambda c: (Damage(c.state.players[c.player_id].hero_id, 29,
            c.source_id, DamageKind.SPELL), Draw(c.player_id, 3, c.source_id),
            GainArmor(c.player_id, 99)),
        'silence': lambda c: (Silence(next(i for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id == 'ETC_068')),),
    }
    for name, fn in operations.items():
        cid = 'ft.'+name
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            metadata=metadata(CardClass.WARLOCK)))
    return r


class ExplicitFatigueTests(unittest.TestCase):
    def game(self, hand=('ft.tick',), deck=('ft.filler',), *, armor=0,
             hero='ft.hero', enemy_hand=(), enemy_deck=('ft.filler',)):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, deck=deck, max_mana=10, mana=10, armor=armor),
            PlayerSetup('ft.hero', hand=enemy_hand, deck=enemy_deck, max_mana=10, mana=10),
        ), seed=321), registry())
    def hero(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id]
    def play(self, g, card='ft.tick', player=1):
        entity = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == card)
        g.apply(PlayCard(player, entity))
        return entity
    def choose(self, g, option='ok'):
        choice = g.state.pending_choice
        g.apply(SelectChoice(choice.player_id, choice.id, (option,)))
    def amounts(self, g):
        return [e.amount for e in g.events if e.kind == 'fatigue']
    def check(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap, registry()).snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), snap)

    def test_effect_rejects_invalid_accounts_sources_and_callbacks(self):
        for args in ((True,), (0,), (3,), (1, True), (1, 0), (1, None, 'x'), (1, 1, ''), (1, 1, False)):
            with self.subTest(args=args), self.assertRaises(ValueError): TakeFatigue(*args)
        self.assertEqual(TakeFatigue(2), TakeFatigue(2, None, None))

    def test_raw_packet_keeps_full_records_and_only_one_executable_representative(self):
        packet = evidence()
        self.assertEqual(packet['executable_representatives'], ['ETC_068'])
        all_raw = {c['id']: c for c in json.loads((ROOT/'data/extracted/cards.json').read_bytes())}
        for raw in packet['records']: self.assertEqual(raw, all_raw[raw['id']])
        self.assertEqual(packet['records'][0]['name'], '次中音号小鬼')
        self.assertFalse(packet['CN_calibrated'])

    def test_explicit_tick_does_not_require_or_draw_from_empty_deck(self):
        g = self.game(); before = tuple(g.state.players[1].deck)
        self.play(g)
        self.assertEqual(tuple(g.state.players[1].deck), before)
        self.assertEqual((g.state.players[1].fatigue, self.hero(g).health), (1, 29))
        self.assertEqual(g.state.draw_history, [])
        self.assertFalse(any(e.kind == 'card_drawn' for e in g.events))
        self.check(g)

    def test_explicit_event_and_health_packet_remain_source_less(self):
        g = self.game(); self.play(g)
        event = next(e for e in g.events if e.kind == 'fatigue')
        result = next(health_result(e) for e in g.events if e.kind == 'health_resolved')
        self.assertIsNone(event.source_id); self.assertEqual(dict(event.data), {})
        self.assertEqual((result.damage_kind, result.base_amount, result.spell_bonus), ('fatigue', 1, 0))
        self.assertIsNone(result.source_id); self.assertIsNone(result.source_card_id)

    def test_fixed_fatigue_classification_is_not_an_account_tick(self):
        g = self.game(('ft.fixed',)); self.play(g, 'ft.fixed')
        self.assertEqual((g.state.players[1].fatigue, self.hero(g).health), (0, 26))
        self.assertEqual(self.amounts(g), [])

    def test_empty_deck_and_explicit_ticks_share_the_same_progression(self):
        for order in (('ft.draw', 'ft.tick', 'ft.draw'), ('ft.tick', 'ft.draw', 'ft.tick')):
            with self.subTest(order=order):
                g = self.game(order, deck=())
                for card in order: self.play(g, card)
                self.assertEqual(self.amounts(g), [1, 2, 3])
                self.assertEqual((g.state.players[1].fatigue, self.hero(g).health), (3, 24))
                self.assertEqual(len(g.state.draw_history), order.count('ft.draw'))
                self.assertTrue(all(d.outcome == 'fatigue' and d.completed for d in g.state.draw_history))
                self.check(g)

    def test_accounts_remain_independent_for_both_players(self):
        g = self.game(('ft.tick', 'ft.enemy', 'ft.tick'))
        for card in ('ft.tick', 'ft.enemy', 'ft.tick'): self.play(g, card)
        self.assertEqual([g.state.players[p].fatigue for p in (1, 2)], [2, 1])
        self.assertEqual([self.hero(g, p).health for p in (1, 2)], [27, 29])
        self.assertEqual(self.amounts(g), [1, 1, 2])
        self.check(g)

    def test_armor_absorbs_damage_without_resetting_counter(self):
        g = self.game(('ft.twice',), armor=2); self.play(g, 'ft.twice')
        self.assertEqual((g.state.players[1].fatigue, self.hero(g).armor, self.hero(g).health), (2, 0, 29))
        self.assertEqual(self.amounts(g), [1, 2])

    def test_immune_hero_still_advances_counter_and_native_nominal_growth(self):
        g = self.game(('ft.tick', 'ETC_068'), hero='ft.immune')
        self.play(g); entity = self.play(g, 'ETC_068')
        self.assertEqual((g.state.players[1].fatigue, self.hero(g).health), (2, 30))
        self.assertEqual((g.state.entities[entity].attack, g.state.entities[entity].health), (4, 4))
        self.assertTrue(all(health_result(e).damage_dealt == 0 for e in g.events if e.kind == 'health_resolved'))
        self.check(g)

    def test_natural_empty_deck_draw_keeps_immune_progression(self):
        g = self.game(('ft.draw', 'ft.draw'), deck=(), hero='ft.immune')
        self.play(g, 'ft.draw'); self.play(g, 'ft.draw')
        self.assertEqual((g.state.players[1].fatigue, self.hero(g).health), (2, 30))
        self.assertEqual([dict(e.data)['draw_id'] for e in g.events if e.kind == 'fatigue'], [1, 2])
        self.check(g)

    def test_damage_cap_does_not_change_nominal_native_growth(self):
        g = self.game(('ft.tick', 'ETC_068'), hero='ft.cap')
        self.play(g); entity = self.play(g, 'ETC_068')
        self.assertEqual((self.hero(g).health, g.state.players[1].fatigue), (28, 2))
        self.assertEqual((g.state.entities[entity].attack, g.state.entities[entity].health), (4, 4))
        results = [health_result(e) for e in g.events if e.kind == 'health_resolved']
        self.assertEqual([(r.base_amount, r.damage_dealt) for r in results], [(1, 1), (2, 1)])

    def test_lethal_explicit_tick_stops_unstarted_ticks_and_followups(self):
        g = self.game(('ft.fatal.tick',)); self.play(g, 'ft.fatal.tick')
        self.assertEqual((g.state.status, g.state.winner), ('finished', 2))
        self.assertEqual((g.state.players[1].fatigue, self.hero(g).armor), (1, 0))
        self.assertEqual(self.amounts(g), [1]); self.assertEqual(g.state.draw_history, [])
        self.check(g)

    def test_lethal_empty_draw_stops_remaining_attempts(self):
        g = self.game(('ft.fatal.draw',), deck=()); self.play(g, 'ft.fatal.draw')
        self.assertEqual((g.state.status, g.state.winner, g.state.players[1].fatigue), ('finished', 2, 1))
        self.assertEqual(len(g.state.draw_history), 1)
        self.assertTrue(g.state.draw_history[0].interrupted)
        self.assertEqual(self.hero(g).armor, 0)
        self.check(g)

    def test_native_imp_pays_once_and_gains_the_actual_first_nominal_number(self):
        g = self.game(('ETC_068',)); entity = self.play(g, 'ETC_068')
        self.assertEqual((g.state.players[1].mana, self.hero(g).health), (8, 29))
        self.assertEqual((g.state.entities[entity].attack, g.state.entities[entity].health), (3, 3))
        self.assertEqual(g.state.draw_history, [])
        self.check(g)

    def test_native_imp_uses_existing_account_instead_of_restarting_at_one(self):
        g = self.game(('ft.twice', 'ETC_068')); self.play(g, 'ft.twice')
        entity = self.play(g, 'ETC_068')
        self.assertEqual((g.state.players[1].fatigue, self.hero(g).health), (3, 24))
        self.assertEqual((g.state.entities[entity].attack, g.state.entities[entity].health), (5, 5))

    def test_silencing_original_card_does_not_remove_account_progression(self):
        g = self.game(('ETC_068', 'ft.silence', 'ft.tick')); entity = self.play(g, 'ETC_068')
        self.play(g, 'ft.silence'); self.play(g)
        self.assertEqual(g.state.players[1].fatigue, 2)
        self.assertEqual((g.state.entities[entity].attack, g.state.entities[entity].health), (2, 2))

    def test_turn_boundaries_do_not_reset_either_player_fatigue(self):
        g = self.game(('ft.tick',), deck=(), enemy_deck=()); self.play(g)
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual([g.state.players[p].fatigue for p in (1, 2)], [2, 1])
        self.assertEqual([self.hero(g, p).health for p in (1, 2)], [27, 29])
        self.check(g)

    def test_unstarted_tick_survives_choice_save_clone_and_independent_replay(self):
        g = self.game(('ft.wait.before',)); self.play(g, 'ft.wait.before')
        self.assertEqual(g.state.players[1].fatigue, 0); self.check(g)
        restored = Game.from_snapshot(g.snapshot(), registry()); cloned = g.clone()
        for game in (g, restored, cloned): self.choose(game)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(g.snapshot(), cloned.snapshot())
        self.assertEqual((g.state.players[1].fatigue, self.hero(g).health), (1, 29))
        self.check(g)

    def test_accepted_callback_number_survives_waiting_before_later_tick(self):
        g = self.game(('ft.wait.after',)); self.play(g, 'ft.wait.after')
        self.assertEqual((g.state.players[1].fatigue, self.hero(g).health), (1, 29))
        self.check(g)
        restored = Game.from_snapshot(g.snapshot(), registry())
        self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual((g.state.players[1].fatigue, self.hero(g).armor, self.hero(g).health), (2, 0, 28))
        self.check(g)

    def test_failed_choice_rolls_back_new_tick_and_preserves_waiting_prefix(self):
        g = self.game(('ft.wait.after',)); self.play(g, 'ft.wait.after'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before); self.assertEqual(g.state.players[1].fatigue, 1)
        self.choose(g); self.check(g)

    def test_missing_physical_source_fails_without_advancing_account(self):
        g = self.game(('ft.invalid',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'ft.invalid')
        self.assertEqual(g.snapshot(), before)

    def test_unknown_callback_fails_without_advancing_account(self):
        g = self.game(('ft.unknown',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'ft.unknown')
        self.assertEqual(g.snapshot(), before)

    def test_failed_callback_rolls_back_counter_damage_events_and_payment(self):
        g = self.game(('ft.fail.after',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'ft.fail.after')
        self.assertEqual(g.snapshot(), before)

    def test_player_view_does_not_receive_callback_state_or_hidden_deck_identity(self):
        g = self.game(('ft.wait.after',), enemy_hand=('ft.hidden',), enemy_deck=('ft.hidden',))
        self.play(g, 'ft.wait.after')
        own = json.dumps(g.for_player(1).observe(), ensure_ascii=False)
        self.assertNotIn('ft.hidden', own); self.assertNotIn('on_fatigue', own)
        self.assertNotIn('RuleContext', own); self.assertNotIn('continuation', own)
        for player in (1, 2): self.assertNotIn('context', json.dumps(g.for_player(player).observe()))

    def test_pending_effect_codec_is_strict_and_previous_schema_is_rejected(self):
        g = self.game(('ft.wait.before',)); self.play(g, 'ft.wait.before')
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g._state)
        raw = codec.encode(TakeFatigue(1))
        self.assertEqual(codec.decode(raw), TakeFatigue(1))
        bad = deepcopy(raw); bad['unknown'] = 1
        with self.assertRaises(ValueError): codec.decode(bad)
        source = g.state.players[1].graveyard[0]
        with self.assertRaises(ValueError): codec.encode(TakeFatigue(1, source, 'ft.missing.callback'))
        old = deepcopy(g.snapshot()); old['schema_version'] = 220
        with self.assertRaisesRegex(SnapshotError, 'schemas 1 through 264'): Game.from_snapshot(old, registry())
        self.assertIn(TakeFatigue, g.mechanics.effect_types)
