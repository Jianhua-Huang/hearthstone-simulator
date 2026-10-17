"""Real Ashalon, original Adapt choices, physical entry and durable memory."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json
import random
import unittest

from hs_sim.cards.constructed import build_registry
from hs_sim.cards.native_ashalon_adaptation_cards import CARD, PROGRAM, CHOICES, load_batch
from hs_sim.engine import (BattlecryRepeatSpec, CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice,
    SummonQuantitySpec, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.adapt import CHOICE_IDS, PLANT_ID, _KEYWORDS, _STATS
from hs_sim.engine.adapt_memory import AdaptAndRemember, SPORES
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy, GainArmor,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.errors import IllegalAction, ResolutionError, SnapshotError
from hs_sim.engine.interrupts import CounterMinion
from hs_sim.engine.model import PlayerEffectSpec, validate_adaptations
from hs_sim.engine.player_effects import AddPlayerEffect, RemovePlayerEffect
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash, rng_from_json
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_physical import PROFILE
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P = 'k151.'
PLAIN, BODY, HOST, MAGNET = (P + s for s in ('plain', 'body', 'host', 'magnet'))
ATTACK, HEALTH, STATS, SHIELD, STEALTH, SPORES_FACE = (
    'UNG_999t3', 'UNG_999t4', 'UNG_999t14', 'UNG_999t8', 'UNG_999t10', 'UNG_999t2')
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.NONE, tribes=())


def seed_for(*choices):
    for seed in range(100000):
        rng = random.Random(seed)
        if all(cid in rng.sample(CHOICE_IDS, 3) for cid in choices):
            return seed
    raise AssertionError('No fixture seed')


@lru_cache(maxsize=2)
def registry(role):
    assert role in ('writer', 'reader')
    r = build_registry()
    # Equal complete configuration; two genuinely independent immutable objects.
    r.register_card(CardDefinition(PLAIN, 'Plain fixture', CardType.MINION, cost=2, attack=2, health=3, metadata=META))
    r.register_behavior(P + 'body', lambda c: (GainArmor(c.player_id, c.source.attack),))
    r.register_card(CardDefinition(BODY, 'Entry probe', CardType.MINION, cost=1, attack=1, health=2,
        battlecry=P + 'body', metadata=META))
    mech = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.NONE, tribes=('mech',))
    r.register_card(CardDefinition(HOST, 'Host fixture', CardType.MINION, attack=2, health=5, metadata=mech))
    r.register_card(CardDefinition(MAGNET, 'Magnet fixture', CardType.MINION, cost=1, attack=1, health=2,
        keywords=(Keyword.MAGNETIC,), magnetic_tribes=('mech',), metadata=mech))
    r.register_card(CardDefinition(P + 'quantity', 'Quantity fixture', CardType.MINION, health=6,
        summon_quantities=(SummonQuantitySpec(),), metadata=META))
    r.register_card(CardDefinition(P + 'repeat', 'Repeat fixture', CardType.MINION, health=6,
        battlecry_repeats=(BattlecryRepeatSpec(),), metadata=META))

    scripts = dict(kill=lambda c: (Destroy(c.target_id),), silence=lambda c: (Silence(c.target_id),),
        bounce=lambda c: (ReturnToHand(c.target_id),), control=lambda c: (ChangeControl(c.target_id, 2),),
        transform=lambda c: (Transform(c.target_id, PLAIN),),
        copy=lambda c: (CopyMinion(c.target_id, c.player_id, cause=SummonCause.capture(c)),),
        summon=lambda c: (Summon(c.player_id, PLAIN),),
        remove=lambda c: (RemovePlayerEffect(c.player_id, c.state.players[c.player_id].player_effects[0].id),),
        add_counter=lambda c: (Summon(2, P + 'counter'),),
        add_fill=lambda c: (Summon(2, P + 'fill'),))
    scripts['replay'] = lambda c: (ReplayWholeCards(c.player_id, c.source_id,
        WholeCardHistoryQuery(c.player_id, len(c.state.play_history) + 1, kinds=(CardType.MINION,),
                             exclude_card_ids=(CARD,)), choices='player', physical_profile=PROFILE),)
    for name, fn in scripts.items():
        r.register_behavior(P + name, fn)
        args = dict(targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='any'))
        if name in ('summon', 'remove', 'add_counter', 'add_fill', 'replay'):
            args = {}
        r.register_card(CardDefinition(P + name, name, CardType.SPELL, on_play=P + name, metadata=META, **args))

    r.register_behavior(P + 'reenter', lambda c: (SummonStoredCard(
        CardReference.capture(c.state.entities[c.target_id]), c.player_id, cause=SummonCause.capture(c)),))
    def original(c, action):
        if c.event.target_id is None or c.state.entities[c.event.target_id].card_id != CARD:
            return ()
        target = c.event.target_id
        if action == 'reenter':
            return (ReturnToHand(target), InvokeBehavior(P + 'reenter', c.source_id, c.player_id, target))
        if action == 'kill': return (Destroy(target),)
        if action == 'control': return (ChangeControl(target, 2),)
        return (Transform(target, PLAIN),)
    for action in ('reenter', 'kill', 'control', 'transform'):
        key = P + 'watch_' + action
        r.register_behavior(key, lambda c, action=action: original(c, action))
        r.register_card(CardDefinition(key, key, CardType.MINION, health=6,
            triggers=(TriggerSpec('stats_changed', key),), metadata=META))
    r.register_behavior(P + 'counter', lambda c: (CounterMinion(dict(c.event.data)['window_id']),))
    r.register_card(CardDefinition(P + 'counter', 'Counter fixture', CardType.MINION, health=6,
        triggers=(TriggerSpec('minion_counter_check', P + 'counter'),), metadata=META))
    r.register_behavior(P + 'fill', lambda c: tuple(Summon(c.event.player_id, PLAIN) for _ in range(7)))
    r.register_card(CardDefinition(P + 'fill', 'Fill fixture', CardType.MINION, health=6,
        triggers=(TriggerSpec('minion_counter_check', P + 'fill'),), metadata=META))
    def entry(c):
        if c.state.entities[c.event.target_id].card_id not in (PLAIN, BODY): return ()
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'OK'),), c.source_id),)
    r.register_behavior(P + 'entry', entry)
    r.register_card(CardDefinition(P + 'entry', 'Entry wait', CardType.MINION, health=6,
        triggers=(TriggerSpec('minion_summoned', P + 'entry'),), metadata=META))
    def fail(c): raise ResolutionError('deliberate K151 rollback')
    r.register_behavior(P + 'fail', fail)
    r.register_behavior(P + 'program_wait', lambda c: (RequestChoice(c.player_id,
        (ChoiceOption('fail', 'Fail', (InvokeBehavior(P + 'fail', c.source_id, c.player_id),)),), c.source_id),)
        if dict(c.event.data).get('effect_key') == PROGRAM else ())
    r.register_card(CardDefinition(P + 'program_wait', 'Program wait', CardType.MINION, health=6,
        triggers=(TriggerSpec('player_effect_added', P + 'program_wait'),), metadata=META))
    r.register_player_effect(PlayerEffectSpec(P + 'other', PLAIN))
    r.validate(); r.freeze()
    return r


class NativeAshalonAdaptationTests(unittest.TestCase):
    def game(self, choices=(ATTACK, HEALTH), hand=(CARD, PLAIN), board=(), enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(PLAIN,) * 12, mana=50, max_mana=50, mana_cap=50),
            PlayerSetup('HERO_08', hand=enemy_hand, deck=(PLAIN,) * 12, mana=50, max_mana=50, mana_cap=50)),
            seed=seed_for(*choices)), registry('writer'))

    def eid(self, g, cid, player=None, zone='hand'):
        state = g.state; player = player or state.active_player
        return next(i for i in getattr(state.players[player], zone) if state.entities[i].card_id == cid)

    def play(self, g, cid, target=None, position=None):
        state = g.state; player = state.active_player; eid = self.eid(g, cid)
        if state.entities[eid].kind == CardType.MINION and position is None:
            position = len(state.players[player].board)
        g.apply(PlayCard(player, eid, target_id=target, position=position))
        return eid

    def choose(self, g, cid):
        q = g.state.pending_choice
        self.assertIn(cid, [o.id for o in q.options])
        g.apply(SelectChoice(q.player_id, q.id, (cid,)))

    def finish(self, g, choices=(ATTACK, HEALTH)):
        source = self.play(g, CARD)
        for cid in choices: self.choose(g, cid)
        return source

    def check(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        writer, reader = registry('writer'), registry('reader')
        self.assertIsNot(writer, reader)
        self.assertEqual(writer.fingerprint(), reader.fingerprint())
        self.assertEqual(Game.from_snapshot(saved, reader).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)

    def rehash(self, saved):
        saved['events_hash'] = canonical_hash(saved['events'])
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        return saved

    def test_complete_real_faces_and_existing_dependency_pins(self):
        data = load_batch(); r = registry('writer')
        self.assertEqual((len(data['cards']), len(data['official_observations'])), (8, 26))
        self.assertEqual({x['record']['id'] for x in data['cards']}, {CARD, *CHOICES})
        for cid, pin in data['existing_dependency_definition_pins'].items():
            self.assertEqual(canonical_digest(asdict(r.card(cid))), pin)
        self.assertTrue(all(r.card(cid).choice_only for cid in CHOICE_IDS))
        self.assertEqual((r.card(CARD).cost, r.card(CARD).attack, r.card(CARD).health), (5, 8, 8))
        self.assertIn(Keyword.RUSH, r.card(CARD).keywords)
        self.assertNotIn('TLC_229', r.cards)

    def test_two_fresh_offers_waiting_restore_and_one_complete_program(self):
        g = self.game(); source = self.play(g, CARD)
        rng = random.Random(); rng.setstate(rng_from_json(g.snapshot()['rng_state']))
        self.assertEqual(len(g.state.pending_choice.options), 3)
        self.assertFalse(g.state.players[1].player_effects)
        self.check(g)
        restored = Game.from_snapshot(g.snapshot(), registry('reader'))
        self.choose(g, ATTACK); self.choose(restored, ATTACK)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual([o.id for o in g.state.pending_choice.options], list(rng.sample(CHOICE_IDS, 3)))
        self.assertFalse(g.state.players[1].player_effects)
        self.check(g)
        self.choose(g, HEALTH)
        effects = g.state.players[1].player_effects
        self.assertEqual(len(effects), 1)
        self.assertEqual((effects[0].source_id, effects[0].source_card_id, effects[0].adaptations),
                         (source, CARD, (ATTACK, HEALTH)))
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health), (11, 11))
        self.assertEqual((g.state.players[1].mana, len(g.state.play_history)), (45, 1))
        self.check(g)

    def test_all_three_numeric_recipes_reach_future_minions_before_battlecry(self):
        for cid in _STATS:
            with self.subTest(cid=cid):
                g = self.game((cid, ATTACK), hand=(CARD, BODY))
                self.finish(g, (cid, ATTACK)); target = self.play(g, BODY)
                attack, health = _STATS[cid]
                self.assertEqual((g.state.entities[target].attack, g.state.entities[target].max_health),
                                 (1 + attack + 3, 2 + health))
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 1 + attack + 3)
                self.check(g)

    def test_all_six_keyword_recipes_use_ordinary_attachments_and_actor_deadlines(self):
        for cid, keyword in (*_KEYWORDS.items(), (STEALTH, Keyword.STEALTH)):
            with self.subTest(cid=cid):
                g = self.game((cid, ATTACK)); source = self.finish(g, (cid, ATTACK))
                target = self.play(g, PLAIN)
                self.assertIn(keyword, g.state.entities[target].keywords)
                grants = [a for a in g.state.entities[target].abilities if a.keyword == keyword and a.origin == 'granted']
                self.assertEqual(len(grants), 1)
                self.assertEqual(grants[0].source_id, source)
                if cid == STEALTH:
                    self.assertEqual(grants[0].keyword_expiry.player_id, 1)
                    g.apply(EndTurn(1)); g.apply(EndTurn(2))
                    self.assertNotIn(Keyword.STEALTH, g.state.entities[target].keywords)
                self.check(g)

    def test_repeated_same_adaptation_stacks_as_two_real_ordered_grants(self):
        g = self.game((ATTACK, ATTACK)); source = self.finish(g, (ATTACK, ATTACK))
        target = self.play(g, PLAIN)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[target].attack), (14, 8))
        self.assertEqual(g.state.players[1].player_effects[0].adaptations, (ATTACK, ATTACK))
        self.assertEqual(len([x for x in g.state.entities[target].enchantments if x.source_id == source]), 2)
        self.check(g)

    def test_original_residency_does_not_rebind_after_reentry_death_control_or_transform(self):
        for action in ('reenter', 'kill', 'control', 'transform'):
            with self.subTest(action=action):
                g = self.game(board=(P + 'watch_' + action,)); source = self.play(g, CARD)
                self.choose(g, ATTACK); first_state = g.state.entities[source]
                self.check(g)
                self.choose(g, HEALTH)
                self.assertEqual(g.state.entities[source].max_health, first_state.max_health)
                self.assertEqual(g.state.players[1].player_effects[0].source_card_id, CARD)
                target = self.play(g, PLAIN)
                self.assertEqual((g.state.entities[target].attack, g.state.entities[target].max_health), (5, 6))
                self.check(g)

    def test_program_survives_source_silence_bounce_and_control_and_belongs_to_actor(self):
        for action in ('silence', 'bounce', 'control'):
            with self.subTest(action=action):
                g = self.game(hand=(CARD, P + action, PLAIN), enemy_hand=(PLAIN,))
                source = self.finish(g); self.play(g, P + action, source)
                target = self.play(g, PLAIN)
                self.assertEqual((g.state.entities[target].attack, g.state.entities[target].max_health), (5, 6))
                g.apply(EndTurn(1)); enemy = self.play(g, PLAIN)
                self.assertEqual((g.state.entities[enemy].attack, g.state.entities[enemy].max_health), (2, 3))
                self.check(g)

    def test_ordinary_summons_copies_and_program_removal_do_not_reapply(self):
        g = self.game(hand=(CARD, PLAIN, P + 'copy', P + 'summon', P + 'remove', PLAIN))
        self.finish(g); target = self.play(g, PLAIN)
        self.play(g, P + 'copy', target); self.play(g, P + 'summon')
        stats = [(g.state.entities[i].attack, g.state.entities[i].max_health) for i in g.state.players[1].board]
        self.assertEqual(stats[-2:], [(5, 6), (2, 3)])
        self.play(g, P + 'remove'); target = self.play(g, PLAIN)
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].max_health), (2, 3))
        self.check(g)

    def test_magnetic_material_is_installed_on_original_component_before_merge(self):
        g = self.game((ATTACK, SHIELD), hand=(CARD, MAGNET), board=(HOST,))
        self.finish(g, (ATTACK, SHIELD)); host = self.eid(g, HOST, zone='board')
        source = self.play(g, MAGNET, position=0)
        self.assertEqual(g.state.play_history[-1].minion_result, 'magnetized')
        self.assertEqual((g.state.entities[host].attack, g.state.entities[host].max_health), (6, 7))
        self.assertIn(Keyword.DIVINE_SHIELD, g.state.entities[host].keywords)
        self.assertEqual(g.state.magnetic_history[-1].source_id, source)
        self.check(g)

    def test_entry_wait_observes_complete_program_before_battlecry_and_restores(self):
        g = self.game(hand=(CARD, BODY), board=(P + 'entry',))
        self.finish(g); target = self.play(g, BODY)
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].max_health), (4, 5))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)
        self.check(g); self.choose(g, 'ok')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 4)
        self.check(g)

    def test_counter_and_lost_capacity_do_not_install_or_consume_program(self):
        for watch, result in (('counter', 'countered'), ('fill', 'board_full')):
            with self.subTest(watch=watch):
                g = self.game(hand=(CARD, P + 'add_' + watch, PLAIN))
                self.finish(g); original = g.state.players[1].player_effects[0]
                self.play(g, P + 'add_' + watch); self.play(g, PLAIN)
                self.assertEqual(g.state.play_history[-1].minion_result, result)
                self.assertEqual(g.state.players[1].player_effects, [original])
                self.check(g)

    def test_real_generated_primary_granted_before_entry_but_quantity_extra_is_not_another_play(self):
        g = self.game(hand=(CARD, PLAIN, P + 'replay'), board=(P + 'quantity',))
        self.finish(g); self.play(g, PLAIN); self.play(g, P + 'replay')
        root = g.state.card_summon_history[-1]
        generated = [g.state.entities[d.entity.entity_id] for d in root.deliveries]
        self.assertEqual([(e.attack, e.max_health) for e in generated], [(5, 6), (2, 3)])
        self.assertEqual(len(g.state.play_history), 3)
        self.assertEqual(len(g.state.players[1].player_effects), 1)
        self.check(g)

    def test_living_spores_uses_original_death_attribution_group_quantity_and_unbuffed_plants(self):
        g = self.game((SPORES_FACE, ATTACK), hand=(CARD, P + 'kill'), board=(PLAIN, P + 'quantity', PLAIN))
        source = self.play(g, CARD, position=1)
        self.choose(g, SPORES_FACE); self.choose(g, ATTACK)
        self.play(g, P + 'kill', source)
        plants = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == PLANT_ID]
        self.assertEqual(len(plants), 4)
        self.assertTrue(all((e.attack, e.max_health) == (1, 1) for e in plants))
        groups = g.state.ordered_group_history
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].request.group.cause.source.entity_id, source)
        self.assertEqual(len(groups[0].request.group.members), 2)
        self.assertEqual(len(g.state.card_summon_history), 2)
        self.check(g)

    def test_each_repeated_battlecry_has_its_own_two_choices_and_complete_program(self):
        picks = (ATTACK, HEALTH, ATTACK, HEALTH)
        g = self.game(picks, board=(P + 'repeat',)); source = self.play(g, CARD)
        for cid in picks: self.choose(g, cid)
        self.assertEqual(len(g.state.players[1].player_effects), 2)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health), (14, 14))
        target = self.play(g, PLAIN)
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].max_health), (8, 9))
        self.check(g)

    def test_player_effect_public_program_has_only_fixed_faces_without_host_identity(self):
        g = self.game(); self.finish(g)
        for player in (1, 2):
            dto = next(p for p in g.observe(player)['players'] if p['id'] == 1)['player_effects'][0]
            self.assertEqual(dto['adaptations'], [ATTACK, HEALTH])
            self.assertFalse({'id', 'source_id', 'source_allocation'} & set(dto))
        self.check(g)

    def test_bad_selection_and_later_failure_restore_complete_waiting_state_and_rng(self):
        g = self.game(board=(P + 'program_wait',)); self.play(g, CARD)
        before = g.snapshot(); q = g.state.pending_choice
        with self.assertRaises(IllegalAction): g.apply(SelectChoice(q.player_id, q.id, ('unknown',)))
        self.assertEqual(g.snapshot(), before)
        self.choose(g, ATTACK); self.choose(g, HEALTH)
        self.assertEqual(g.state.players[1].player_effects[0].adaptations, (ATTACK, HEALTH))
        self.check(g); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate K151'):
            self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before)
        self.check(g)

    def test_strict_program_shape_kind_schema_and_independent_registry_reject_tampering(self):
        g = self.game(); self.finish(g); original = g.snapshot()
        for values in ([ATTACK], [ATTACK, 'unknown'], []):
            changed = deepcopy(original)
            changed['state']['players']['1']['player_effects'][0]['adaptations'] = values
            with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(changed), registry('reader'))
        changed = deepcopy(original); changed['schema_version'] -= 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(changed), registry('reader'))
        changed = deepcopy(original); changed['state']['players']['1']['player_effects'][0]['spec_id'] = P + 'other'
        with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(changed), registry('reader'))
        # A fresh production-only registry deliberately omits these fixtures.
        different = build_registry(); different.freeze()
        self.assertNotEqual(different.fingerprint(), registry('writer').fingerprint())
        with self.assertRaises(SnapshotError): Game.from_snapshot(original, different)
        for values in ([ATTACK, HEALTH], (ATTACK,), (ATTACK, HEALTH, ATTACK), (True, HEALTH)):
            with self.assertRaises(ValueError): validate_adaptations(values)
        with self.assertRaises(ValueError): PlayerEffectSpec('bad', CARD, kind='adaptations', spell_damage=1)


if __name__ == '__main__':
    unittest.main()
