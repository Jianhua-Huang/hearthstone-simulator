"""Independent Jade growth with real templates and only Spirit/Swarmer sources."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, JadeGolemFamily, Keyword, PlayCard, PlayerSetup, Rarity, Registry,
    ResolutionError, Scenario, SelectChoice, SnapshotError, SummonJadeGolem, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion,
    Destroy, GainArmor, RequestChoice, ReturnToHand, ShuffleIntoDeck, Silence,
    Summon, Transform)
from hs_sim.engine.jade import CLASSIC, VERSION, jade_count, printed_definition
from hs_sim.engine.model import TriggerSpec
from hs_sim.engine.player_target_inputs import (capture as capture_observation,
    decode as decode_observation, canonical)
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_sources import CopyStoredMinion, DeathQuery, ResurrectMinion, SummonFromZone, death_candidates
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.cross_zone import MinionScope, cost_value, minion_references
from hs_sim.engine.zones import CardReference, CopyCard, DrawMatching, MoveCard
from hs_sim.targets import canonical_digest


FORMS = ('CFM_712_t01', 'CFM_712_t04', 'CFM_712_t07', 'CFM_712_t20')
VIOLET_FORMS = ('JAIL_504tt01', 'JAIL_504tt04', 'JAIL_504tt07', 'JAIL_504tt20')
VIOLET = 'jade.violet'
SPIRIT, SWARMER = 'CFM_715', 'CFM_691'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/jade-basics.json'
PIN = 'c4ff0ca4f2bf0b3ded2d375dc88c432daa03844ad018d2dc331da33335718de0'


def evidence():
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(data) != PIN:
        raise ValueError('Complete Jade raw fixture changed')
    for row in data['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original complete Jade raw record changed')
    return {row['id']: row['data'] for row in data['records']}


def registry(extras=(), bulk=2, listener=False, omitted=None):
    r = Registry('jade-basic-tests-' + VERSION)
    r.register_jade_family(JadeGolemFamily(CLASSIC, VERSION, FORMS))
    r.register_jade_family(JadeGolemFamily(VIOLET, VERSION, VIOLET_FORMS))
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=40,
        metadata=CardMetadata(False, (CardClass.ROGUE,), None)))
    r.register_card(CardDefinition('plain', 'plain', CardType.MINION, attack=2, health=4))
    raw = evidence()
    for cid in (*FORMS, *VIOLET_FORMS):
        row = raw[cid]
        r.register_card(CardDefinition(cid, row['name'], CardType.MINION, cost=row['cost'],
            attack=row['attack'], health=row['health'], metadata=CardMetadata(False, (CardClass.NEUTRAL,), None)))
    r.register_behavior('jade.source', lambda c: (SummonJadeGolem(c.player_id, c.source_id),))
    for cid, kwargs, classes, tribes in (
            (SPIRIT, {'battlecry': 'jade.source'}, (CardClass.DRUID, CardClass.ROGUE, CardClass.SHAMAN), ('elemental',)),
            (SWARMER, {'deathrattle': 'jade.source', 'keywords': (Keyword.STEALTH,)}, (CardClass.ROGUE,), ())):
        row = raw[cid]
        r.register_card(CardDefinition(cid, row['name'], CardType.MINION, cost=row['cost'],
            attack=row['attack'], health=row['health'], metadata=CardMetadata(True, classes, Rarity.COMMON, tribes=tribes),
            **kwargs))
    probes = {
        'once': lambda c: (SummonJadeGolem(c.player_id, c.source_id),),
        'bulk': lambda c: (SummonJadeGolem(c.player_id, c.source_id, count=bulk),),
        'violet': lambda c: (SummonJadeGolem(c.player_id, c.source_id, VIOLET),),
        'zero': lambda c: (SummonJadeGolem(c.player_id, c.source_id, count=0),),
        'clear': lambda c: tuple(Destroy(i, c.source_id) for i in c.state.players[c.player_id].board),
    }
    probes.update(dict(extras))
    for cid, fn in probes.items():
        r.register_behavior(cid, lambda c, fn=fn: fn(c))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    if listener:
        def heard(c):
            if c.event.player_id != c.player_id:
                return ()
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue',
                (GainArmor(c.player_id, 1),)),), c.source_id),)
        r.register_behavior('heard', heard)
        r.register_card(CardDefinition('listener', 'listener', CardType.MINION, health=5,
            triggers=(TriggerSpec('minion_summoned', 'heard'),)))
    if omitted is not None:
        r._cards.pop(omitted)
    return r


class JadeBasicsTests(unittest.TestCase):
    def setUp(self):
        self.extras, self.bulk = [], 2

    def script(self, cid, fn):
        self.extras.append((cid, fn))

    def game(self, hand=('once',), board=(), enemy_board=(), enemy_hand=(), listener=False, omitted=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, mana=10, max_mana=10),
            PlayerSetup('hero', hand=enemy_hand, board=enemy_board, mana=10, max_mana=10)), seed=7),
            registry(self.extras, self.bulk, listener, omitted))

    def play(self, g, cid, pid=1):
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid, eid))
        return eid

    def bodies(self, g, pid=1):
        return [g.state.entities[i] for i in g.state.players[pid].board]

    def grown(self, size, extra_hand=()):
        self.bulk = size - 1
        g = self.game(hand=('bulk', 'clear', 'once', *extra_hand))
        self.play(g, 'bulk'); self.play(g, 'clear'); self.play(g, 'once')
        return g, self.bodies(g)[0]

    def check(self, g, listener=False):
        snap = g.snapshot()
        fresh = lambda: registry(self.extras, self.bulk, listener)
        restored = Game.from_snapshot(snap, fresh())
        self.assertEqual(restored.snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), fresh()).snapshot(), snap)
        for pid in (1, 2):
            self.assertEqual(restored.observe(pid), g.observe(pid))

    def rejected(self, g, fn):
        s = g.snapshot(); fn(s)
        s['events_hash'] = canonical_hash(s['events'])
        s['state_hash'] = canonical_hash({k: v for k, v in s.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(s, registry(self.extras, self.bulk))

    def test_real_raw_and_only_two_source_adapters(self):
        raw, r = evidence(), registry()
        self.assertEqual(len(raw), 10)
        self.assertEqual((r.card(SPIRIT).cost, r.card(SPIRIT).attack, r.card(SPIRIT).health), (4, 3, 3))
        self.assertEqual((r.card(SWARMER).cost, r.card(SWARMER).attack), (1, 1))
        self.assertEqual(len(r.jade_families), 2)
        self.assertNotIn('JAIL_504', r.cards)

    def test_real_battlecry_and_deathrattle_share_player_growth(self):
        self.script('kill', lambda c: (Destroy(next(i for i in c.state.players[1].board
            if c.state.entities[i].card_id == SWARMER), c.source_id),))
        g = self.game(hand=(SPIRIT, SWARMER, 'kill'))
        self.play(g, SPIRIT); self.play(g, SWARMER); self.play(g, 'kill')
        jades = [e for e in self.bodies(g) if e.jade_size is not None]
        self.assertEqual([e.jade_size for e in jades], [1, 2])
        self.assertEqual([row.source_id for row in g.state.jade_history], [g.state.players[1].board[0], g.state.death_history[0].entity_id])
        self.assertEqual(jade_count(g.state, 1), 2)
        self.check(g)

    def test_two_artwork_families_share_growth_without_new_card_ids(self):
        g = self.game(hand=('once', 'violet', 'once'))
        for cid in ('once', 'violet', 'once'): self.play(g, cid)
        self.assertEqual([(e.card_id, e.jade_size) for e in self.bodies(g)],
            [(FORMS[0], 1), (VIOLET_FORMS[0], 2), (FORMS[0], 3)])
        self.check(g)

    def test_players_have_independent_growth(self):
        g = self.game(hand=('bulk',), enemy_hand=('once',))
        self.play(g, 'bulk'); g.apply(EndTurn(1)); self.play(g, 'once', 2)
        self.assertEqual((jade_count(g.state, 1), jade_count(g.state, 2)), (2, 1))
        self.assertEqual(self.bodies(g, 2)[0].jade_size, 1)

    def test_artwork_thresholds_and_innate_cost(self):
        for size, form in ((3, 0), (4, 1), (6, 1), (7, 2), (19, 2), (20, 3)):
            with self.subTest(size=size):
                g, e = self.grown(size)
                self.assertEqual((e.card_id, e.base_attack, e.base_health, e.base_cost),
                    (FORMS[form], size, size, min(10, size)))
                self.assertFalse(e.enchantments)

    def test_thirty_is_size_cap_but_successful_attempt_count_continues(self):
        self.script('again', lambda c: (SummonJadeGolem(c.player_id, c.source_id),))
        g, e = self.grown(30, ('again',))
        self.play(g, 'again')
        self.assertEqual([b.jade_size for b in self.bodies(g)], [30, 30])
        self.assertEqual((jade_count(g.state, 1), e.base_cost), (31, 10))

    def test_full_board_advances_growth_without_allocating_entity(self):
        g = self.game(hand=('once', 'clear', 'once'), board=('plain',) * 7)
        before = g.state.next_entity_id
        self.play(g, 'once')
        self.assertEqual((jade_count(g.state, 1), g.state.next_entity_id), (1, before))
        self.assertIsNone(g.state.jade_history[0].entity_id)
        self.play(g, 'clear'); self.play(g, 'once')
        self.assertEqual(self.bodies(g)[0].jade_size, 2)
        self.check(g)

    def test_zero_count_has_no_growth_body_receipt_or_rng_change(self):
        g = self.game(hand=('zero',))
        rng = g.snapshot()['rng_state']; self.play(g, 'zero')
        self.assertEqual((g.state.jade_history, self.bodies(g)), ([], []))
        self.assertEqual(g.snapshot()['rng_state'], rng)

    def test_position_defaults_next_to_real_generator(self):
        g = self.game(hand=(SPIRIT,), board=('plain', 'plain'))
        source = self.play(g, SPIRIT)
        self.assertEqual(g.state.players[1].board[-2:], [source, g.state.jade_history[-1].entity_id])

    def test_explicit_summon_position(self):
        self.script('front', lambda c: (SummonJadeGolem(1, c.source_id, position=0),))
        g = self.game(hand=('front',), board=('plain',))
        self.play(g, 'front')
        self.assertEqual([e.jade_size for e in self.bodies(g)], [1, None])

    def test_stolen_generator_uses_new_controller_growth(self):
        self.script('steal', lambda c: (ChangeControl(next(i for i in c.state.players[1].board
            if c.state.entities[i].card_id == SWARMER), 2),))
        self.script('kill.enemy', lambda c: (Destroy(next(i for i in c.state.players[2].board
            if c.state.entities[i].card_id == SWARMER), c.source_id),))
        g = self.game(hand=('bulk', SWARMER, 'steal', 'kill.enemy'))
        for cid in ('bulk', SWARMER, 'steal', 'kill.enemy'): self.play(g, cid)
        self.assertEqual((jade_count(g.state, 1), jade_count(g.state, 2)), (2, 1))
        self.assertEqual(self.bodies(g, 2)[0].jade_size, 1)

    def test_literal_template_summon_does_not_advance_growth(self):
        self.script('literal', lambda c: (Summon(1, FORMS[2]),))
        g = self.game(hand=('literal', 'once'))
        self.play(g, 'literal'); self.play(g, 'once')
        self.assertEqual([e.jade_size for e in self.bodies(g)], [7, 1])
        self.assertEqual(jade_count(g.state, 1), 1)

    def test_silence_removes_buff_but_preserves_innate_size(self):
        self.script('buff', lambda c: (Buff(c.state.players[1].board[0], 4, 5, c.source_id),))
        self.script('silence', lambda c: (Silence(c.state.players[1].board[0]),))
        g, e = self.grown(5, ('buff', 'silence'))
        self.play(g, 'buff'); e = self.bodies(g)[0]; self.assertEqual((e.attack, e.max_health), (9, 10))
        self.play(g, 'silence'); e = self.bodies(g)[0]
        self.assertEqual((e.attack, e.max_health, e.jade_size, len(e.enchantments)), (5, 5, 5, 0))

    def test_normal_base_and_current_board_copies_preserve_frozen_size(self):
        self.script('copy.base', lambda c: (CopyMinion(c.state.players[1].board[0], 2, mode='base'),))
        self.script('copy.current', lambda c: (CopyMinion(c.state.players[1].board[0], 2),))
        g, e = self.grown(5, ('copy.base', 'copy.current'))
        self.play(g, 'copy.base'); self.play(g, 'copy.current')
        self.assertEqual([x.jade_size for x in self.bodies(g, 2)], [5, 5])
        self.assertEqual((jade_count(g.state, 1), jade_count(g.state, 2)), (5, 0))
        self.check(g)

    def test_bounce_removes_local_buff_and_preserves_size_and_cost(self):
        self.script('bounce', lambda c: (Buff(c.state.players[1].board[0], 2, 2),
            ReturnToHand(c.state.players[1].board[0])))
        g, e = self.grown(5, ('bounce',))
        self.play(g, 'bounce')
        now = g.state.entities[e.id]
        self.assertEqual((now.zone, now.base_attack, now.base_health, now.base_cost, now.jade_size), (Zone.HAND, 5, 5, 5, 5))
        self.assertFalse(now.enchantments)
        g.apply(PlayCard(1, now.id))
        self.assertEqual((self.bodies(g)[0].jade_size, jade_count(g.state, 1)), (5, 5))

    def test_shuffle_preserves_original_size_not_current_growth(self):
        self.script('shuffle', lambda c: (ShuffleIntoDeck(c.state.players[1].board[0]),))
        g, e = self.grown(6, ('shuffle',))
        self.play(g, 'shuffle')
        now = g.state.entities[e.id]
        self.assertEqual((now.zone, now.jade_size, now.base_cost), (Zone.DECK, 6, 6))
        self.check(g)

    def test_hidden_card_base_copy_retains_printed_size(self):
        self.script('bounce', lambda c: (ReturnToHand(c.state.players[1].board[0]),))
        self.script('copy.hand', lambda c: (CopyCard(CardReference.capture(next(
            c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].jade_size is not None)),
            2, Zone.HAND, mode='base', source_id=c.source_id),))
        g, e = self.grown(6, ('bounce', 'copy.hand'))
        self.play(g, 'bounce'); self.play(g, 'copy.hand')
        copied = g.state.entities[g.state.players[2].hand[0]]
        self.assertEqual((copied.base_attack, copied.base_cost, copied.jade_size), (6, 6, 6))
        self.assertEqual(jade_count(g.state, 2), 0)

    def test_move_with_reset_retains_immutable_size(self):
        self.script('bounce', lambda c: (ReturnToHand(c.state.players[1].board[0]),))
        self.script('move', lambda c: (MoveCard(CardReference.capture(next(c.state.entities[i]
            for i in c.state.players[1].hand if c.state.entities[i].jade_size is not None)),
            1, Zone.DECK, reset=True, position='bottom'),))
        g, e = self.grown(5, ('bounce', 'move'))
        self.play(g, 'bounce'); self.play(g, 'move')
        self.assertEqual((g.state.entities[e.id].jade_size, g.state.entities[e.id].base_cost), (5, 5))

    def test_explicit_transform_resets_innate_size_to_new_template(self):
        self.script('transform', lambda c: (Transform(c.state.players[1].board[0], FORMS[0]),))
        g, e = self.grown(5, ('transform',))
        self.play(g, 'transform')
        self.assertEqual((self.bodies(g)[0].jade_size, jade_count(g.state, 1)), (1, 5))

    def test_transform_to_other_minion_removes_jade_imprint(self):
        self.script('transform', lambda c: (Transform(c.state.players[1].board[0], 'plain'),))
        g, e = self.grown(2, ('transform',))
        self.play(g, 'transform')
        self.assertEqual((self.bodies(g)[0].jade_size, self.bodies(g)[0].base_attack), (None, 2))

    def test_resurrection_uses_frozen_death_size_not_new_growth(self):
        self.script('kill', lambda c: (Destroy(c.state.players[1].board[0]),))
        self.script('revive', lambda c: (ResurrectMinion(2, c.state.death_history[-1].id, source_id=c.source_id),))
        g, e = self.grown(5, ('kill', 'once', 'revive'))
        self.play(g, 'kill'); self.play(g, 'once'); self.play(g, 'revive')
        self.assertEqual((g.state.death_history[-1].jade_size, self.bodies(g, 2)[0].jade_size), (5, 5))
        self.assertEqual((jade_count(g.state, 1), jade_count(g.state, 2)), (6, 0))
        self.check(g)

    def test_frozen_copy_material_preserves_base_size_through_public_copy(self):
        self.script('copy.material', lambda c: (CopyMinion(c.state.players[1].board[0], 2,
            mode='base', cause=SummonCause.capture(c)),))
        g, e = self.grown(5, ('copy.material',))
        self.play(g, 'copy.material')
        self.assertEqual(self.bodies(g, 2)[0].jade_size, 5)
        self.assertEqual(g.state.card_summon_history[-1].request.materials[0].jade_size, 5)
        self.assertEqual(jade_count(g.state, 2), 0)
        self.check(g)

    def test_frozen_resurrection_material_preserves_base_size(self):
        self.script('kill', lambda c: (Destroy(c.state.players[1].board[0]),))
        self.script('revive.material', lambda c: (ResurrectMinion(2, c.state.death_history[-1].id,
            source_id=c.source_id, cause=SummonCause.capture(c)),))
        g, e = self.grown(5, ('kill', 'revive.material'))
        self.play(g, 'kill'); self.play(g, 'revive.material')
        self.assertEqual(self.bodies(g, 2)[0].jade_size, 5)
        self.assertEqual(jade_count(g.state, 2), 0)
        self.check(g)

    def test_printed_death_cost_uses_frozen_size(self):
        self.script('kill', lambda c: (Destroy(c.state.players[1].board[0]),))
        g, e = self.grown(5, ('kill',)); self.play(g, 'kill')
        found = death_candidates(g.state, g.registry, 1,
            DeathQuery(cards=PoolQuery(min_cost=5, max_cost=5)))
        self.assertEqual([row.entity_id for row in found], [e.id])

    def test_stored_minion_copy_uses_its_physical_size(self):
        self.script('bounce', lambda c: (ReturnToHand(c.state.players[1].board[0]),))
        self.script('copy.stored', lambda c: (CopyStoredMinion(CardReference.capture(next(
            c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].jade_size is not None)),
            2, mode='base'),))
        g, e = self.grown(5, ('bounce', 'copy.stored'))
        self.play(g, 'bounce'); self.play(g, 'copy.stored')
        self.assertEqual(self.bodies(g, 2)[0].jade_size, 5)

    def test_printed_zone_cost_uses_instance_size(self):
        self.script('shuffle', lambda c: (ShuffleIntoDeck(c.state.players[1].board[0]),))
        self.script('draw.five', lambda c: (DrawMatching(1, PoolQuery(min_cost=5, max_cost=5),
            'skip', selection='first', source_id=c.source_id),))
        g, e = self.grown(5, ('shuffle', 'draw.five'))
        self.play(g, 'shuffle'); self.play(g, 'draw.five')
        self.assertEqual(printed_definition(g.registry, g.state.entities[e.id]).cost, 5)
        self.assertEqual(g.registry.card(e.card_id).cost, 4)
        self.assertIn(e.id, g.state.players[1].hand)

    def test_cross_zone_printed_cost_uses_same_innate_size(self):
        g, e = self.grown(5)
        scope = MinionScope((Zone.BOARD,), PoolQuery(min_cost=5, max_cost=5))
        self.assertEqual([ref.entity_id for ref in minion_references(g.state, g.registry, 1, scope)], [e.id])
        self.assertEqual(cost_value(g.registry, e, 'printed'), 5)
        self.assertEqual(cost_value(g.registry, e, 'local'), 5)

    def recruited(self):
        self.script('shuffle', lambda c: (ShuffleIntoDeck(c.state.players[1].board[0]),))
        self.script('recruit', lambda c: (SummonFromZone(1, query=PoolQuery(min_cost=5, max_cost=5),
            selection='first', source_id=c.source_id, cause=SummonCause.capture(c)),))
        g, e = self.grown(5, ('shuffle', 'recruit'))
        self.play(g, 'shuffle'); self.play(g, 'recruit')
        return g, e

    def test_frozen_recruit_cost_preserves_original_physical_body(self):
        g, e = self.recruited()
        self.assertEqual(g.state.players[1].board, [e.id])
        self.assertEqual((self.bodies(g)[0].jade_size, jade_count(g.state, 1)), (5, 5))
        self.check(g)

    def test_frozen_recruit_candidate_cannot_drop_innate_size(self):
        g, e = self.recruited()
        def remove_size(s):
            s['state']['recruit_summon_history'][0]['rounds'][0]['basis']['inventory'][0]['jade_size'] = None
        self.rejected(g, remove_size)

    def test_choice_between_two_actual_summons_restores_and_replays(self):
        g = self.game(hand=('bulk',), board=('listener',), listener=True)
        self.play(g, 'bulk')
        for count in (1, 2):
            self.assertEqual(jade_count(g.state, 1), count)
            self.assertIsNotNone(g.state.pending_choice)
            self.check(g, listener=True)
            choice = g.state.pending_choice
            g.apply(SelectChoice(1, choice.id, ('ok',)))
        self.assertEqual([e.jade_size for e in self.bodies(g)], [None, 1, 2])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2)
        self.check(g, listener=True)

    def test_failed_action_rolls_back_growth_payment_entities_events_and_rng(self):
        self.script('bad', lambda c: (SummonJadeGolem(1, c.source_id), Summon(1, 'missing')))
        g = self.game(hand=('bad',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'bad')
        self.assertEqual(g.snapshot(), before)

    def test_missing_selected_template_is_error_even_with_full_board(self):
        g = self.game(hand=('once',), board=('plain',) * 7, omitted=FORMS[0])
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'once')
        self.assertEqual(g.snapshot(), before)

    def test_missing_named_family_never_silently_does_nothing(self):
        self.script('bad.family', lambda c: (SummonJadeGolem(1, c.source_id, 'unknown'),))
        g = self.game(hand=('bad.family',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'bad.family')
        self.assertEqual(g.snapshot(), before)

    def test_private_growth_count_and_receipts_do_not_leak_to_opponent(self):
        g = self.game(hand=('once',)); self.play(g, 'once')
        own, enemy = g.observe(1), g.observe(2)
        self.assertEqual(own['players'][0]['jade_count'], 1)
        self.assertNotIn('jade_count', enemy['players'][0])
        for viewer in (1, 2):
            encoded = json.dumps(g.observe(viewer), ensure_ascii=False)
            self.assertNotIn('jade_history', encoded); self.assertNotIn('jade_id', encoded)
            self.assertNotIn('jade_size', encoded); self.assertNotIn('jade_golem_attempted', encoded)

    def test_player_target_observation_accepts_only_own_exact_count(self):
        g = self.game(hand=('once',))
        proof = capture_observation(g, g._state, g._state.entities[g.state.players[1].hand[0]])
        self.assertEqual(decode_observation(proof)['players'][0]['jade_count'], 0)
        for pid, count in ((0, True), (0, -1), (1, 0)):
            with self.subTest(pid=pid, count=count):
                value = json.loads(proof.observation_json); value['players'][pid]['jade_count'] = count
                with self.assertRaises(ValueError):
                    decode_observation(replace(proof, observation_json=canonical(value)))

    def test_tampered_history_and_innate_base_are_rejected_after_rehash(self):
        g, e = self.grown(5)
        changes = (
            lambda s: s['state']['jade_history'][-1].update(size=6),
            lambda s: s['state']['jade_history'][-1].update(count_before=0),
            lambda s: s['state']['jade_history'][-1].update(family_version='another'),
            lambda s: s['state']['jade_history'].pop(),
            lambda s: s['state']['entities'][str(e.id)].update(jade_size=None),
            lambda s: s['state']['entities'][str(e.id)].update(base_cost=4),
            lambda s: next(ev for ev in s['events'] if ev['kind'] == 'jade_golem_attempted').update(amount=30),
        )
        for change in changes:
            with self.subTest(change=changes.index(change)): self.rejected(g, change)

    def test_jade_imprint_on_unrelated_body_is_rejected(self):
        g = self.game(board=('plain',))
        entity = g.state.players[1].board[0]
        self.rejected(g, lambda s: s['state']['entities'][str(entity)].update(jade_size=2))

    def test_old_schema_is_rejected(self):
        g = self.game(); s = g.snapshot(); self.assertEqual(s['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        for version in (1, 154):
            with self.subTest(version=version):
                with self.assertRaises(SnapshotError):
                    Game.from_snapshot({**s, 'schema_version': version}, registry())

    def test_exact_effect_input_and_duplicate_artwork_contract(self):
        for kwargs in ({'player_id': True}, {'player_id': 1, 'count': True},
                       {'player_id': 1, 'count': -1}, {'player_id': 1, 'position': True}):
            with self.assertRaises(ValueError): SummonJadeGolem(**kwargs)
        with self.assertRaises(ValueError): JadeGolemFamily(CLASSIC, VERSION, (FORMS[0],) * 4)
        r = registry()
        with self.assertRaises(ValueError): r.register_jade_family(JadeGolemFamily(CLASSIC, VERSION, FORMS))
        r.register_jade_family(JadeGolemFamily('duplicate.art', VERSION, FORMS))
        with self.assertRaises(ValueError): r.validate()


if __name__ == '__main__':
    unittest.main()
