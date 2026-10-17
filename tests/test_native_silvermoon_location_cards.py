"""Real Silvermoon faces, original location lifecycle and non-spell partition."""
from dataclasses import asdict
from functools import lru_cache
import json
import random
import unittest

from hs_sim.cards.native_silvermoon_location_cards import FACES, load_batch, register_native_silvermoon_location_cards
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, Keyword, PlayCard, PlayerSetup, Rarity, Registry, Scenario, SelectChoice,
    TargetSpec, UseLocation, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import ChoiceOption, Damage, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import IllegalAction, ResolutionError, SnapshotError
from hs_sim.engine.excess_damage import DamageExcessToHero, prepare_partition
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.health_rules import rule_sources
from hs_sim.engine.locations import DestroyLocation, ModifyLocation
from hs_sim.engine.model import DamageKind, HealthFlow, HealthLayer, HealthOp, HealthRule, LimitedTriggerSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference

P = 'k155.'
HERO, H1, H3, H7, H20, SHIELD, IMMUNE = (P + n for n in ('hero', 'h1', 'h3', 'h7', 'h20', 'shield', 'immune'))
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.NONE, tribes=())


@lru_cache(maxsize=2)
def registry(role):
    assert role in ('writer', 'reader')
    r = Registry('k155-native-silvermoon-v1')
    register_native_silvermoon_location_cards(r)
    r.register_card(CardDefinition(HERO, 'Mage fixture', CardType.HERO, health=100,
        metadata=CardMetadata(False, (CardClass.MAGE,), Rarity.NONE, tribes=())))
    for cid, hp, kw in ((H1, 1, ()), (H3, 3, ()), (H7, 7, ()), (H20, 20, ()),
            (SHIELD, 3, (Keyword.DIVINE_SHIELD,)), (IMMUNE, 3, (Keyword.IMMUNE,))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1, attack=1, health=hp,
            keywords=kw, metadata=META))
    r.register_card(CardDefinition(P + 'stealth', 'Stealth fixture', CardType.MINION, health=1,
        keywords=(Keyword.STEALTH,), metadata=META))
    r.register_card(CardDefinition(P + 'spell_power', 'Spell Damage fixture', CardType.MINION,
        health=20, spell_damage=100, metadata=META))
    for name, layer in (('source_double', HealthLayer.SOURCE), ('target_double', HealthLayer.TARGET)):
        rule = HealthRule(HealthFlow.DAMAGE, HealthOp.SCALE, 2, layer=layer,
            source_relation='friendly' if layer == HealthLayer.SOURCE else 'any',
            target_kinds=(CardType.HERO, CardType.MINION) if layer == HealthLayer.SOURCE else (CardType.MINION,),
            damage_kinds=(DamageKind.EFFECT,))
        r.register_card(CardDefinition(P + name, name, CardType.MINION, health=20, health_rules=(rule,), metadata=META))
    r.register_behavior(P + 'noop', lambda c: ())
    r.register_card(CardDefinition(P + 'other_location', 'Physical non-minion slot', CardType.LOCATION,
        durability=3, on_use=P + 'noop', metadata=META))
    r.register_behavior(P + 'wound', lambda c: (Damage(c.target_id, 5, c.source_id),))
    r.register_card(CardDefinition(P + 'wound', 'Damage fixture', CardType.SPELL, on_play=P + 'wound',
        targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='enemy'), metadata=META))
    r.register_behavior(P + 'lower', lambda c: (ModifyLocation(next(i for i in c.state.players[c.player_id].board
        if c.state.entities[i].card_id in FACES), durability=-2, source_id=c.source_id),))
    r.register_card(CardDefinition(P + 'lower', 'Durability fixture', CardType.SPELL, on_play=P + 'lower', metadata=META))
    def fail(c): raise ResolutionError('deliberate K155 rollback')
    r.register_behavior(P + 'raise_failure', fail)
    def eligible(c):
        return (c.event.source_id is not None and c.state.entities[c.event.source_id].kind == CardType.LOCATION
            and c.event.target_id is not None and c.state.entities[c.event.target_id].kind == CardType.MINION)
    r.register_trigger_condition(P + 'location_damage', eligible)
    def wait(c):
        options = (ChoiceOption('ok', 'Continue'),
            ChoiceOption('bad', 'Fail', (InvokeBehavior(P + 'raise_failure', c.source_id, c.player_id),)),
            ChoiceOption('destroy', 'Destroy original location', (DestroyLocation(c.event.source_id, c.source_id),)))
        return (RequestChoice(c.player_id, options, c.source_id),)
    r.register_behavior(P + 'wait', wait)
    r.register_card(CardDefinition(P + 'wait', 'Actual damage reaction', CardType.MINION, health=20, metadata=META,
        limited_triggers=(LimitedTriggerSpec('damage_dealt', P + 'wait', condition_id=P + 'location_damage'),)))
    r.validate(); r.freeze()
    return r


class NativeSilvermoonLocationTests(unittest.TestCase):
    def game(self, face=FACES[1], enemy=(H3,), board=(), hand=(), seed=5, armor=0):
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO, board=(() if face is None else (face,)) + board, hand=hand,
                deck=(H20,) * 20, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup(HERO, board=enemy, deck=(H20,) * 20, armor=armor)), seed=seed), registry('writer'))

    def loc(self, g):
        state = g.state
        return next(i for i in state.players[1].board if state.entities[i].card_id in FACES)

    def play(self, g, cid, target=None):
        state = g.state; eid = next(i for i in state.players[1].hand if state.entities[i].card_id == cid)
        position = len(state.players[1].board) if state.entities[eid].kind in (CardType.MINION, CardType.LOCATION) else None
        g.apply(PlayCard(1, eid, target_id=target, position=position))
        return eid

    def use(self, g):
        eid = self.loc(g); g.apply(UseLocation(1, eid)); return eid

    def choose(self, g, option='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (option,)))

    def hero(self, g, player=2): return g.state.entities[g.state.players[player].hero_id]

    def ready(self, g, eid):
        for _ in range(8):
            if g.state.active_player == 1 and g.state.entities[eid].location_cooldown == 0: return
            g.apply(EndTurn(g.state.active_player))
        self.fail('Location cooldown never reopened at the real owner start')

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); a, b = registry('writer'), registry('reader')
        self.assertIsNot(a, b); self.assertEqual(a.fingerprint(), b.fingerprint())
        other = Game.from_snapshot(saved, b)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), b).snapshot(), saved)
        return other

    def test_real_paid_three_uses_preserve_physical_identity_cooldown_and_last_body(self):
        g = self.game(face=None, hand=(FACES[0],), enemy=(H20,)); eid = self.play(g, FACES[0])
        self.assertEqual(g.state.players[1].mana, 26)
        initial = g.state.entities[eid]; identity = (initial.id, initial.owner, initial.controller,
            initial.entered_order, initial.board_presence_id)
        for index in (1, 2):
            self.use(g); e = g.state.entities[eid]
            self.assertEqual((e.id, e.owner, e.controller, e.entered_order, e.board_presence_id), identity)
            self.assertEqual((e.card_id, e.durability, e.location_cooldown), (FACES[index], 3-index, 2))
            self.assertEqual(e.zone_epoch, initial.zone_epoch + index)
            with self.assertRaises(IllegalAction): g.apply(UseLocation(1, eid))
            self.portable(g); self.ready(g, eid)
        self.use(g)
        self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].damage, 15)
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual(len(g.state.cast_history), 0)
        self.assertEqual(sum(e.kind == 'location_face_changed' for e in g.events), 2); self.portable(g)

    def test_past_random_hit_has_no_excess_and_advances_original(self):
        g = self.game(face=FACES[0]); target = g.state.players[2].board[0]; eid = self.use(g)
        self.assertEqual(g.state.entities[target].damage, 5)
        self.assertEqual(self.hero(g).damage, 0)
        self.assertEqual(g.state.entities[eid].card_id, FACES[1]); self.portable(g)

    def test_present_partitions_five_as_effect_and_spell_damage_does_not_expand_budget(self):
        g = self.game(board=(P + 'spell_power',)); target = g.state.players[2].board[0]; eid = self.use(g)
        self.assertEqual((g.state.entities[target].damage, self.hero(g).damage), (3, 2))
        self.assertEqual(g.state.entities[eid].card_id, FACES[2])
        results = [health_result(e) for e in g.events if health_result(e) is not None and health_result(e).source_id == eid]
        self.assertTrue(results)
        self.assertTrue(all(r.damage_kind == DamageKind.EFFECT.value and r.spell_bonus == 0 for r in results))
        self.assertFalse(g.state.cast_history); self.portable(g)

    def test_future_chooses_lowest_remaining_health_not_printed_maximum(self):
        g = self.game(face=FACES[2], enemy=(H7, H3), hand=(P + 'wound',))
        original, other = g.state.players[2].board
        self.play(g, P + 'wound', target=original); self.assertEqual(g.state.entities[original].health, 2)
        casts = len(g.state.cast_history); self.use(g)
        self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[other].damage, 0); self.assertEqual(self.hero(g).damage, 3)
        self.assertEqual(len(g.state.cast_history), casts); self.portable(g)

    def test_future_equal_health_ties_sample_physical_candidates_once(self):
        for seed in (0, 1, 5):
            with self.subTest(seed=seed):
                g = self.game(face=FACES[2], enemy=(H3, H3), seed=seed)
                ids = g.state.players[2].board; rng = random.Random(seed); chosen = rng.sample(list(ids), 1)[0]
                self.use(g)
                self.assertEqual(g.state.entities[chosen].zone, Zone.GRAVEYARD)
                self.assertEqual(g._rng.getstate(), rng.getstate())
        self.portable(g)

    def test_past_and_present_can_sample_higher_health_while_future_cannot(self):
        for face in FACES[:2]:
            g = self.game(face=face, enemy=(H1, H7), seed=5); low, high = g.state.players[2].board
            self.use(g)
            self.assertEqual((g.state.entities[low].damage, g.state.entities[high].damage), (0, 5))
            self.assertEqual(self.hero(g).damage, 0)

    def test_source_and_recipient_scaling_keep_one_original_budget(self):
        for name, expected in (('source_double', (3, 7)), ('target_double', (6, 2))):
            with self.subTest(name=name):
                g = self.game(board=(P + name,)); target = g.state.players[2].board[0]; self.use(g)
                self.assertEqual((g.state.entities[target].damage, self.hero(g).damage), expected); self.portable(g)

    def test_shield_immunity_and_hero_armor_do_not_reallocate_original_remainder(self):
        for cid in (SHIELD, IMMUNE):
            with self.subTest(cid=cid):
                g = self.game(enemy=(cid,), armor=1); target = g.state.players[2].board[0]; self.use(g)
                self.assertEqual(g.state.entities[target].damage, 0)
                self.assertEqual((self.hero(g).armor, self.hero(g).damage), (0, 1)); self.portable(g)

    def test_empty_pools_advance_without_rng_or_false_damage(self):
        for index, face in enumerate(FACES):
            g = self.game(face=face, enemy=()); before = g.snapshot()['rng_state']; eid = self.use(g)
            self.assertEqual(g.snapshot()['rng_state'], before)
            self.assertEqual(g.state.entities[eid].card_id, FACES[min(index+1, 2)])
            self.assertEqual(self.hero(g).damage, 0); self.portable(g)

    def test_last_use_present_body_runs_after_original_location_is_destroyed(self):
        g = self.game(hand=(P + 'lower',)); eid = self.loc(g); self.play(g, P + 'lower')
        self.assertEqual(g.state.entities[eid].durability, 1); self.use(g)
        self.assertEqual((g.state.entities[eid].zone, g.state.entities[eid].card_id), (Zone.GRAVEYARD, FACES[1]))
        self.assertEqual(self.hero(g).damage, 2)
        self.assertFalse(any(e.kind == 'location_face_changed' for e in g.events)); self.portable(g)

    def test_both_parcels_finish_before_wait_and_original_face_advances_after_resume(self):
        g = self.game(board=(P + 'wait',)); eid = self.use(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((self.hero(g).damage, g.state.entities[eid].card_id), (2, FACES[1]))
        other = self.portable(g); rng = g.snapshot()['rng_state']
        for game in (g, other): self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertEqual(g.state.entities[eid].card_id, FACES[2]); self.portable(g)

    def test_failed_wait_choice_restores_damage_rng_durability_and_owed_advance(self):
        g = self.game(board=(P + 'wait',)); self.use(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before); self.choose(g); self.portable(g)

    def test_departed_original_location_does_not_advance_a_dead_entity(self):
        g = self.game(board=(P + 'wait',)); eid = self.use(g); self.choose(g, 'destroy')
        self.assertEqual((g.state.entities[eid].zone, g.state.entities[eid].card_id), (Zone.GRAVEYARD, FACES[1]))
        self.assertEqual(self.hero(g).damage, 2); self.portable(g)

    def test_lowest_stealth_minion_is_eligible_and_enemy_location_is_not(self):
        g = self.game(face=FACES[2], enemy=(P + 'other_location', P + 'stealth', H3)); loc, low, high = g.state.players[2].board
        self.use(g)
        self.assertEqual(g.state.entities[loc].durability, 3)
        self.assertEqual(g.state.entities[low].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[high].damage, 0); self.assertEqual(self.hero(g).damage, 4); self.portable(g)

    def test_location_partition_codec_pure_quote_and_actual_source_type_guards(self):
        g = self.game(hand=(P + 'wound',)); loc = self.loc(g); target = g.state.players[2].board[0]
        ref = MinionReference.capture(g.state.entities[target]); request = DamageExcessToHero(ref, 5, loc, kind=DamageKind.EFFECT)
        codec = FrameCodec(g.mechanics, g.registry); self.assertEqual(codec.decode(codec.encode(request)), request)
        before = g.snapshot(); instructions, packets = prepare_partition(g.state, g.registry, request, rule_sources(g.state))
        self.assertEqual([i.amount for i in instructions], [3, 2])
        self.assertTrue(all(p.damage_kind == DamageKind.EFFECT and p.spell_bonus == 0 for p in packets))
        self.assertEqual(g.snapshot(), before)
        for source, kind in ((loc, DamageKind.SPELL), (target, DamageKind.EFFECT),
                (g.state.players[1].hand[0], DamageKind.EFFECT)):
            with self.assertRaises(ResolutionError):
                prepare_partition(g.state, g.registry, DamageExcessToHero(ref, 5, source, kind=kind), rule_sources(g.state))
        self.assertEqual(DamageExcessToHero(ref, 5, loc).kind, DamageKind.SPELL)
        with self.assertRaises(ValueError): DamageExcessToHero(ref, 5, loc, kind=DamageKind.MINION_ABILITY)

    def test_random_location_does_not_offer_manual_target_or_leak_internal_material(self):
        g = self.game(); eid = self.loc(g); before = g.snapshot()
        with self.assertRaises(IllegalAction): g.apply(UseLocation(1, eid, g.state.players[2].board[0]))
        self.assertEqual(g.snapshot(), before); self.use(g)
        for player in (1, 2):
            public = json.dumps(g.observe(player)) + json.dumps(g.player_events(player))
            for key in ('entered_order', 'zone_epoch', 'partition_source', 'source_keywords', 'resolution_frame'):
                self.assertNotIn('"' + key + '"', public)
        saved = g.snapshot(); saved['schema_version'] -= 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry('reader'))

    def test_complete_three_raws_six_primary_faces_four_real_links_and_main_definitions(self):
        data = load_batch(); self.assertEqual((len(data['cards']), len(data['official_observations']),
            len(data['exact_parent_child_links'])), (3, 6, 4))
        from hs_sim.cards.constructed import build_registry
        actual = build_registry(); actual.freeze()
        for index, cid in enumerate(FACES):
            self.assertEqual(asdict(actual.card(cid)), asdict(registry('writer').card(cid)))
            self.assertEqual((actual.card(cid).cost, actual.card(cid).durability), (4, 3))
            self.assertEqual(actual.card(cid).metadata.collectible, index == 0)


if __name__ == '__main__': unittest.main()
