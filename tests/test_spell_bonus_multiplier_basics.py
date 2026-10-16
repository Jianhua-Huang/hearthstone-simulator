"""Scale Spell Damage providers at the existing packet window, with one real card."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, DamageKind, Game,
    Keyword, PlayCard, PlayerSetup, Rarity, Registry, ResolutionError, Scenario,
    SelectChoice, SnapshotError, SpellSchool, TargetSpec, Zone, health_result)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.errors import IllegalAction
from hs_sim.engine.effects import (ChoiceOption, Damage, DamageBatch, GainArmor,
    InvokeBehavior, RequestChoice, Silence, Summon)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT = Path(__file__).resolve().parents[1]
PIN = 'f2d6a4b45d443a5b4cfcd1539527218c20cc37668d761a423259921de717aa82'
NATIVE = 'AT_004'


def evidence():
    packet = json.loads((ROOT/'data/support/spell-bonus-multiplier-basics.json').read_bytes())
    if canonical_digest(packet) != PIN:
        raise ValueError('Spell bonus representative requires its complete pinned raw packet')
    return packet


def registry():
    r = Registry('spell-bonus-multiplier-basics-v1')
    r.register_card(CardDefinition('sb.hero', 'Hero', CardType.HERO, health=80,
        metadata=metadata(CardClass.MAGE, collectible=False)))
    for cid, bonus, schools in (
        ('sb.one', 1, ()), ('sb.three', 3, ()),
        ('sb.arcane', 2, (SpellSchool.ARCANE,)), ('sb.fire', 3, (SpellSchool.FIRE,)),
    ):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=2,
            spell_damage=bonus, spell_damage_schools=schools, metadata=metadata()))
    for cid, health, keywords in (
        ('sb.body', 24, ()), ('sb.weak', 3, ()), ('sb.hidden', 1, ()),
        ('sb.shield', 24, (Keyword.DIVINE_SHIELD,)),
    ):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1,
            health=health, keywords=keywords, metadata=metadata()))

    def hit(c, callback=None):
        return Damage(c.target_id, 2, c.source_id, DamageKind.SPELL,
            callback, spell_bonus_multiplier=2)

    def provider(c):
        return next(i for i in c.state.players[c.player_id].board
            if r.card(c.state.entities[i].card_id).spell_damage)

    def fail(c):
        raise ResolutionError('Deliberate spell bonus callback failure')

    def wait_before(c):
        pid = provider(c)
        return RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', ()),
            ChoiceOption('remove', 'Silence provider', (Silence(pid),)),
            ChoiceOption('bad', 'Silence and fail', (Silence(pid),
                InvokeBehavior('sb.fail', c.source_id, c.player_id))),
        ), c.source_id)

    def result_wait(c):
        value = c.health_result
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Accept applied bonus', (GainArmor(c.player_id, value.spell_bonus),)),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 99),
                InvokeBehavior('sb.fail', c.source_id, c.player_id))),
        ), c.source_id),)

    r.register_behavior('sb.fail', fail)
    r.register_behavior('sb.cb.result', lambda c: (GainArmor(c.player_id, c.health_result.spell_bonus),))
    r.register_behavior('sb.cb.result.wait', result_wait)
    operations = {
        'native': lambda c: (hit(c),),
        'ordinary': lambda c: (Damage(c.target_id, 2, c.source_id, DamageKind.SPELL),),
        'summon.before': lambda c: (Summon(c.player_id, 'sb.one'), hit(c)),
        'silence.before': lambda c: (Silence(provider(c)), hit(c)),
        'sequential': lambda c: (replace(hit(c), target_id=provider(c)), hit(c)),
        'batch': lambda c: (DamageBatch((replace(hit(c), target_id=provider(c)), hit(c))),),
        'wait.before': lambda c: (wait_before(c), hit(c)),
        'result': lambda c: (hit(c, 'sb.cb.result'),),
        'result.wait': lambda c: (hit(c, 'sb.cb.result.wait'),),
        'fail.after': lambda c: (hit(c, 'sb.fail'),),
        'unknown': lambda c: (hit(c, 'sb.missing.callback'),),
    }
    for name, body in operations.items():
        bid = 'sb.'+name
        r.register_behavior(bid, body)
        if name != 'native':
            r.register_card(CardDefinition(bid, bid, CardType.SPELL, cost=1,
                on_play=bid, targeting=TargetSpec(kinds=(CardType.MINION,), zones=(Zone.BOARD,)),
                spell_school=SpellSchool.ARCANE, metadata=metadata(CardClass.MAGE)))
    raw = evidence()['records'][0]
    r.register_card(CardDefinition(raw['id'], raw['name'], CardType.SPELL,
        cost=raw['cost'], on_play='sb.native',
        targeting=TargetSpec(kinds=(CardType.MINION,), zones=(Zone.BOARD,)),
        spell_school=SpellSchool.ARCANE,
        metadata=metadata(CardClass.MAGE, rarity=Rarity.EPIC)))
    return r


class SpellBonusMultiplierBasicsTests(unittest.TestCase):
    def game(self, hand=(NATIVE,), board=('sb.one',), enemy=('sb.body',),
             enemy_hand=(), active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('sb.hero', hand=hand, board=board, deck=('sb.hidden',),
                mana=10, max_mana=10),
            PlayerSetup('sb.hero', hand=enemy_hand, board=enemy, deck=('sb.hidden',),
                mana=10, max_mana=10),
        ), seed=414, active_player=active), registry())

    def entity(self, g, cid='sb.body', p=2):
        return next(g.state.entities[i] for i in g.state.players[p].board
            if g.state.entities[i].card_id == cid)

    def play(self, g, cid=NATIVE, target=None):
        p = g.state.active_player
        source = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(p, source, target if target is not None else self.entity(g).id))
        return source

    def results(self, g):
        return [health_result(e) for e in g.events if e.kind == 'health_resolved']

    def choose(self, g, option='ok'):
        c = g.state.pending_choice
        g.apply(SelectChoice(c.player_id, c.id, (option,)))

    def check(self, g):
        s = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s, registry()).snapshot(), s)
        self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), s)

    def test_complete_raw_pin_and_only_constructed_representative(self):
        packet = evidence()
        self.assertEqual(packet['executable_representatives'], [NATIVE])
        self.assertEqual(len(packet['records']), 4)
        raw = {c['id']: c for c in json.loads((ROOT/'data/extracted/cards.json').read_bytes())}
        for row in packet['records']: self.assertEqual(row, raw[row['id']])
        card = registry().card(NATIVE)
        self.assertEqual((card.cost, card.spell_school, card.metadata.rarity), (1, SpellSchool.ARCANE, Rarity.EPIC))
        self.assertFalse(packet['CN_calibrated'])

    def test_coefficient_rejects_noninteger_nonpositive_and_nonspell_requests(self):
        for value in (True, False, 0, -1, 1.5, '2', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Damage(1, 2, 3, DamageKind.SPELL, spell_bonus_multiplier=value)
        for kind in (DamageKind.EFFECT, DamageKind.COMBAT, DamageKind.MINION_ABILITY, DamageKind.HERO_POWER):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                Damage(1, 2, 3, kind, spell_bonus_multiplier=2)
        with self.assertRaises(ValueError): Damage(1, 2, kind=DamageKind.FATIGUE, spell_bonus_multiplier=2)

    def test_native_base_two_plus_double_bonus_zero_one_and_three(self):
        for board, amount, bonus in (((), 2, 0), (('sb.one',), 4, 2), (('sb.three',), 8, 6)):
            with self.subTest(board=board):
                g = self.game(board=board)
                source = self.play(g)
                r = self.results(g)[0]
                self.assertEqual((r.base_amount, r.spell_bonus, r.modified_amount, r.damage_dealt), (2, bonus, amount, amount))
                self.assertEqual((self.entity(g).health, g.state.players[1].mana), (24-amount, 9))
                self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
                self.check(g)

    def test_default_ordinary_spell_does_not_double_base_or_bonus(self):
        g = self.game(hand=('sb.ordinary',))
        self.play(g, 'sb.ordinary')
        r = self.results(g)[0]
        self.assertEqual((r.base_amount, r.spell_bonus, r.damage_dealt), (2, 1, 3))
        self.assertEqual(Damage(1, 2).spell_bonus_multiplier, 1)

    def test_school_matching_and_unrestricted_providers_share_one_scaled_sum(self):
        g = self.game(board=('sb.one', 'sb.arcane', 'sb.fire'))
        self.play(g)
        r = self.results(g)[0]
        self.assertEqual((r.base_amount, r.spell_bonus, r.damage_dealt), (2, 6, 8))

    def test_native_uses_source_controller_and_can_target_either_side_minion(self):
        for player, target_player in ((1, 1), (1, 2), (2, 1), (2, 2)):
            with self.subTest(player=player, target_player=target_player):
                g = self.game(board=('sb.one', 'sb.body'), enemy=('sb.three', 'sb.body'),
                    enemy_hand=(NATIVE,), active=player)
                target = self.entity(g, p=target_player)
                self.play(g, target=target.id)
                r = self.results(g)[0]
                self.assertEqual((r.source_controller, r.spell_bonus, r.damage_dealt),
                    (player, 2 if player == 1 else 6, 4 if player == 1 else 8))

    def test_native_legal_actions_reject_hero_and_missing_target_transactionally(self):
        g = self.game()
        source = g.state.players[1].hand[0]
        legal = [a for a in g.legal_actions() if isinstance(a, PlayCard) and a.entity_id == source]
        self.assertEqual({a.target_id for a in legal}, {*g.state.players[1].board, *g.state.players[2].board})
        before = g.snapshot()
        for target in (None, g.state.players[2].hero_id):
            with self.subTest(target=target), self.assertRaises(IllegalAction):
                g.apply(PlayCard(1, source, target))
            self.assertEqual(g.snapshot(), before)

    def test_provider_added_before_packet_is_quoted_at_actual_damage_window(self):
        g = self.game(hand=('sb.summon.before',), board=())
        self.play(g, 'sb.summon.before')
        self.assertEqual(self.results(g)[0].damage_dealt, 4)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], ['sb.one'])
        self.check(g)

    def test_provider_silenced_before_packet_does_not_use_planner_snapshot_bonus(self):
        g = self.game(hand=('sb.silence.before',))
        self.play(g, 'sb.silence.before')
        r = self.results(g)[0]
        self.assertEqual((r.spell_bonus, r.damage_dealt), (0, 2))
        self.check(g)

    def test_simultaneous_batch_freezes_bonus_even_when_first_hit_kills_provider(self):
        g = self.game(hand=('sb.batch',))
        provider = self.entity(g, 'sb.one', 1).id
        self.play(g, 'sb.batch')
        self.assertEqual([(r.spell_bonus, r.damage_dealt) for r in self.results(g)], [(2, 4), (2, 4)])
        self.assertEqual(g.state.entities[provider].zone, Zone.GRAVEYARD)
        self.check(g)

    def test_separate_packets_requote_after_provider_death(self):
        g = self.game(hand=('sb.sequential',))
        self.play(g, 'sb.sequential')
        self.assertEqual([(r.spell_bonus, r.damage_dealt) for r in self.results(g)], [(2, 4), (0, 2)])
        self.check(g)

    def test_native_lethal_uses_original_death_checkpoint_and_saved_result(self):
        g = self.game(enemy=('sb.weak',))
        target = self.entity(g, 'sb.weak').id
        self.play(g, target=target)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual((self.results(g)[0].base_amount, self.results(g)[0].damage_dealt), (2, 4))
        self.assertEqual(len([e for e in g.events if e.kind == 'minion_died']), 1)
        self.check(g)

    def test_shield_prevents_scaled_packet_without_changing_quote(self):
        g = self.game(enemy=('sb.shield',))
        self.play(g, target=self.entity(g, 'sb.shield').id)
        r = self.results(g)[0]
        self.assertEqual((r.base_amount, r.spell_bonus, r.modified_amount, r.damage_dealt), (2, 2, 4, 0))
        self.assertEqual(self.entity(g, 'sb.shield').health, 24)

    def test_pending_coefficient_survives_save_clone_and_independent_replay(self):
        g = self.game(hand=('sb.wait.before',))
        self.play(g, 'sb.wait.before')
        self.assertEqual(self.results(g), [])
        self.assertEqual(g.state.players[1].mana, 9)
        self.check(g)
        restored = Game.from_snapshot(g.snapshot(), registry())
        cloned = g.clone()
        for game in (g, restored, cloned): self.choose(game)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(g.snapshot(), cloned.snapshot())
        self.assertEqual(self.results(g)[0].damage_dealt, 4)
        self.check(g)

    def test_waiting_provider_change_is_quoted_after_choice_not_at_request(self):
        g = self.game(hand=('sb.wait.before',))
        self.play(g, 'sb.wait.before')
        self.choose(g, 'remove')
        self.assertEqual((self.results(g)[0].spell_bonus, self.results(g)[0].damage_dealt), (0, 2))
        self.check(g)

    def test_failed_prepacket_choice_preserves_payment_provider_and_pending_packet(self):
        g = self.game(hand=('sb.wait.before',))
        self.play(g, 'sb.wait.before')
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g)
        self.assertEqual(self.results(g)[0].damage_dealt, 4)

    def test_result_callback_reads_applied_bonus_and_unchanged_base(self):
        g = self.game(hand=('sb.result',))
        self.play(g, 'sb.result')
        r = self.results(g)[0]
        self.assertEqual((r.base_amount, r.spell_bonus, r.damage_dealt), (2, 2, 4))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2)
        self.check(g)

    def test_pending_result_callback_restores_without_damage_or_bonus_reexecution(self):
        g = self.game(hand=('sb.result.wait',))
        self.play(g, 'sb.result.wait')
        self.assertEqual(self.entity(g).health, 20)
        self.check(g)
        restored = Game.from_snapshot(g.snapshot(), registry())
        for game in (g, restored): self.choose(game)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual((len(self.results(g)), self.entity(g).health,
            g.state.entities[g.state.players[1].hero_id].armor), (1, 20, 2))
        self.check(g)

    def test_failed_result_choice_preserves_committed_damage_and_original_result(self):
        g = self.game(hand=('sb.result.wait',))
        self.play(g, 'sb.result.wait')
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g)
        self.assertEqual((len(self.results(g)), self.entity(g).health), (1, 20))

    def test_unknown_or_failed_callback_rolls_back_payment_events_and_damage(self):
        for cid in ('sb.unknown', 'sb.fail.after'):
            with self.subTest(cid=cid):
                g = self.game(hand=(cid,))
                before = g.snapshot()
                with self.assertRaises(ResolutionError): self.play(g, cid)
                self.assertEqual(g.snapshot(), before)

    def test_player_view_does_not_receive_internal_coefficient_frame_or_hidden_identity(self):
        g = self.game(hand=('sb.wait.before',), enemy_hand=('sb.hidden',))
        self.play(g, 'sb.wait.before')
        self.assertNotIn('sb.hidden', json.dumps(g.for_player(1).observe(), ensure_ascii=False))
        for player in (1, 2):
            visible = json.dumps(g.for_player(player).observe(), ensure_ascii=False)
            for name in ('spell_bonus_multiplier', 'RuleContext', 'resolution_frame'):
                self.assertNotIn(name, visible)

    def test_effect_codec_and_rehashed_pending_frame_reject_invalid_coefficient_or_unknown_field(self):
        g = self.game(hand=('sb.wait.before',))
        source = self.play(g, 'sb.wait.before')
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g._state)
        value = Damage(self.entity(g).id, 2, source, DamageKind.SPELL, spell_bonus_multiplier=2)
        raw = codec.encode(value)
        self.assertEqual(codec.decode(raw), value)
        for field, value in (('spell_bonus_multiplier', True), ('spell_bonus_multiplier', 0), ('unknown', 1)):
            with self.subTest(field=field, value=value):
                bad = deepcopy(raw)
                bad['fields'][field] = value
                with self.assertRaises(ValueError): codec.decode(bad)
                snap = g.snapshot()
                changed = []
                def corrupt(v):
                    if type(v) is dict:
                        if v.get('type') == raw['type']:
                            v['fields'][field] = value
                            changed.append(True)
                        for item in tuple(v.values()): corrupt(item)
                    elif type(v) is list:
                        for item in v: corrupt(item)
                corrupt(snap['resolution_frame'])
                self.assertTrue(changed, 'The actual pending Damage operand must be changed')
                snap['state_hash'] = canonical_hash({k: v for k, v in snap.items()
                    if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
                with self.assertRaises(SnapshotError): Game.from_snapshot(snap, registry())

    def test_previous_schema_is_rejected_with_original_engine_requirement(self):
        g = self.game()
        old = g.snapshot()
        old['schema_version'] = 221
        with self.assertRaisesRegex(SnapshotError, f'schemas 1 through {SNAPSHOT_SCHEMA_VERSION-1}'):
            Game.from_snapshot(old, registry())


if __name__ == '__main__':
    unittest.main()
