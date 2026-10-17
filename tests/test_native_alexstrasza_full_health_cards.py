"""Real pending Battlecry rewards, including accepted reentrant callbacks."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.native_alexstrasza_full_health_cards import CARD, PENDING, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game,
    Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice, SnapshotError,
    TargetSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Damage, Destroy,
    GrantKeyword, Heal, InvokeBehavior, ReplaceHero, RequestChoice, ReturnToHand, Silence,
    Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_loss import ChangeHeroMaxHealth, SetHeroHealth
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import LimitedTriggerSpec, PlayerEffect, TriggerSpec
from hs_sim.engine.player_effects import (AddPlayerEffect, ConsumePlayerEffect,
    PlayerEffectDamage, RemovePlayerEffect)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash

P = 'k150.'
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())


@lru_cache(maxsize=None)
def registry(mode=None, reader=False):
    # The cache key includes the complete fixture configuration and a separate
    # reader identity. No mutable state or writer registry is used as reader.
    r = build_registry()
    r.register_card(CardDefinition(P+'hero', 'Other hero', CardType.HERO, health=30, metadata=META))
    r.register_card(CardDefinition(P+'smallhero', 'Small hero', CardType.HERO, health=10, metadata=META))
    r.register_card(CardDefinition(P+'sheep', 'Sheep', CardType.MINION, health=1, attack=1, metadata=META))
    def fail(c):
        raise ResolutionError('K150 deliberate failure')
    r.register_behavior(P+'fail', fail)
    def manual(c):
        instance = next(e for e in c.state.players[c.player_id].player_effects if e.spec_id == PENDING)
        hit = PlayerEffectDamage(c.player_id, instance, c.state.players[3-c.player_id].hero_id, 15)
        gate = ConsumePlayerEffect(c.player_id, instance, (hit,))
        waiting = RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue'),
            ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id)
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Consume once', (gate, gate)),
            ChoiceOption('bad', 'Fail after reward', (ConsumePlayerEffect(c.player_id, instance,
                (hit, InvokeBehavior(P+'fail', c.source_id, c.player_id))),)),
            ChoiceOption('replace', 'Retire, add another, then stale consume', (
                RemovePlayerEffect(c.player_id, instance.id),
                AddPlayerEffect(c.player_id, PENDING, instance.source_id, capture_health_source=True), gate)),
            ChoiceOption('after', 'Wait after consumption', (
                ConsumePlayerEffect(c.player_id, instance, (waiting, hit)),))), c.source_id),)
    scripts = {
        'heal': lambda c: (Heal(c.state.players[c.player_id].hero_id, 100, c.source_id),),
        'heal_enemy': lambda c: (Heal(c.state.players[3-c.player_id].hero_id, 100, c.source_id),),
        'wound': lambda c: (Damage(c.state.players[c.player_id].hero_id, 3, c.source_id),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'transform': lambda c: (Transform(c.target_id, P+'sheep'),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'take': lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        'leech': lambda c: (GrantKeyword(c.target_id, Keyword.LIFESTEAL, c.source_id),),
        'immune': lambda c: (GrantKeyword(c.state.players[3-c.player_id].hero_id, Keyword.IMMUNE, c.source_id),),
        'summon': lambda c: (Summon(c.player_id, CARD),),
        'low': lambda c: (SetHeroHealth(c.state.players[c.player_id].hero_id, 5, c.source_id),),
        'setfull': lambda c: (SetHeroHealth(c.state.players[c.player_id].hero_id, 30, c.source_id),),
        'shrink': lambda c: (ChangeHeroMaxHealth(c.player_id, -15, c.source_id, 'clamp_current'),),
        'replace': lambda c: (ReplaceHero(c.player_id, P+'hero', hero_power_card_id='HERO_08bp'),),
        'badheal': lambda c: (Heal(c.state.players[c.player_id].hero_id, 100, c.source_id),
            InvokeBehavior(P+'fail', c.source_id, c.player_id)),
        'manual': manual,
    }
    targeted = ('kill', 'silence', 'transform', 'bounce', 'take', 'leech')
    for name, body in scripts.items():
        r.register_behavior(P+name, body)
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name, metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)) if name in targeted else None))
    if mode:
        def eligible(c):
            if mode == 'nested':
                h = c.health_result
                return h.target_id == c.state.players[c.player_id].hero_id and h.healed > 0 and h.health_after == h.max_health_after
            return dict(c.event.data).get('effect_key') == PENDING
        def watch(c):
            if mode == 'nested':
                return (Damage(c.state.players[c.player_id].hero_id, 1, c.source_id),
                    Heal(c.state.players[c.player_id].hero_id, 1, c.source_id))
            if mode == 'retire':
                return (Transform(c.event.source_id, P+'sheep'),)
            if mode == 'fail':
                return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
            return (RequestChoice(c.player_id, (
                ChoiceOption('ok', 'Continue'),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
        event = 'health_resolved' if mode == 'nested' else 'player_effect_added' if mode == 'retire' else 'player_effect_removed'
        r.register_trigger_condition(P+'eligible', eligible)
        r.register_behavior(P+'watch', watch)
        r.register_card(CardDefinition(P+'watch', 'Earlier observer', CardType.WEAPON, durability=8,
            metadata=META, limited_triggers=(LimitedTriggerSpec(event, P+'watch', condition_id=P+'eligible'),)))
    r.validate()
    r.freeze()
    return r


class NativeAlexstraszaFullHealthTests(unittest.TestCase):
    def game(self, hand=(), *, mode=None, player=1, own_hero='HERO_08', armor=0, enemy_armor=0):
        self.mode = mode
        players = [PlayerSetup('HERO_08', armor=enemy_armor, deck=('CORE_CS2_182',)*8,
            mana=40, max_mana=40, mana_cap=40) for _ in (1, 2)]
        players[player-1] = PlayerSetup(own_hero, hand=hand, armor=armor,
            deck=('CORE_CS2_182',)*8, mana=40, max_mana=40, mana_cap=40,
            weapon_card_id=P+'watch' if mode else None)
        return Game.from_scenario(Scenario(tuple(players), active_player=player, seed=150), registry(mode))

    def play(self, g, cid, target=None):
        s = g.state
        p = s.active_player
        eid = next(i for i in s.players[p].hand if s.entities[i].card_id == cid)
        g.apply(PlayCard(p, eid, target_id=target,
            position=len(s.players[p].board) if s.entities[eid].kind == CardType.MINION else None))
        return eid

    def hero(self, g, p=1):
        s = g.state
        return s.entities[s.players[p].hero_id]

    def pending(self, g, p=1):
        return [e for e in g.state.players[p].player_effects if e.spec_id == PENDING]

    def hits(self, g):
        return [health_result(e) for e in g.events if e.kind == 'health_resolved'
            and health_result(e).source_card_id == CARD]

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        reader = registry(self.mode, True)
        self.assertIsNot(reader, g.registry)
        s = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(s, reader)
        for actual in (other.snapshot(), g.clone().snapshot(), replay(build_replay(g), reader).snapshot()):
            self.assertEqual(canonical_hash(s), canonical_hash(actual))
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe()) + json.dumps(g.player_events(p))
            for key in ('source_allocation', 'resolution_frame', 'on_success', 'next_attachment_id'):
                self.assertNotIn('"'+key+'"', public)
        return other

    def test_complete_original_root_and_enchantment_evidence_with_two_primary_faces(self):
        from tools.card_batch import check_face
        data = load_batch()
        self.assertEqual(([r['record']['id'] for r in data['cards']],
            [r['record']['id'] for r in data['evidence_only']]), ([CARD], ['CATA_307e']))
        self.assertEqual(len(data['official_observations']), 2)
        for obs in data['official_observations']:
            check_face(data['cards'][0]['record'], obs['face'], obs['locale'])
        definition = registry().card(CARD)
        self.assertEqual((definition.cost, definition.attack, definition.health, definition.metadata.tribes), (7, 8, 8, ('dragon',)))
        self.assertTrue(definition.battlecry)
        self.assertEqual(definition.triggers, ())

    def test_paid_battlecry_sets_only_remaining_health_keeps_maximum_and_armor(self):
        g = self.game((CARD,), armor=7)
        self.play(g, CARD)
        self.assertEqual((self.hero(g).health, self.hero(g).max_health, self.hero(g).armor), (15, 30, 7))
        self.assertEqual(g.state.players[1].mana, 33)
        self.assertEqual(len(self.pending(g)), 1)
        self.assertFalse(self.hits(g))
        self.portable(g)

    def test_battlecry_increases_low_health_without_healing_or_maximum_change(self):
        g = self.game((P+'low', CARD))
        self.play(g, P+'low')
        self.play(g, CARD)
        self.assertEqual((self.hero(g).health, self.hero(g).max_health), (15, 30))
        self.assertFalse(any(e.kind == 'healed' for e in g.events))

    def test_plain_summon_does_not_arm_or_set_health(self):
        g = self.game((P+'summon', P+'wound', P+'heal'))
        self.play(g, P+'summon')
        self.assertEqual(self.hero(g).health, 30)
        self.play(g, P+'wound')
        self.play(g, P+'heal')
        self.assertFalse(self.pending(g))
        self.assertEqual(self.hero(g, 2).health, 30)
        self.portable(g)

    def test_full_heal_consumes_once_and_later_overheal_or_second_recovery_cannot_repeat(self):
        g = self.game((CARD, P+'heal', P+'heal', P+'wound', P+'heal'))
        self.play(g, CARD)
        self.play(g, P+'heal')
        self.play(g, P+'heal')
        self.play(g, P+'wound')
        self.play(g, P+'heal')
        self.assertEqual(self.hero(g, 2).health, 15)
        self.assertEqual(len(self.hits(g)), 1)
        self.assertFalse(self.pending(g))
        self.portable(g)

    def test_two_already_captured_nested_full_health_callbacks_cannot_reward_twice(self):
        g = self.game((CARD, P+'heal'), mode='nested')
        self.play(g, CARD)
        self.play(g, P+'heal')
        self.assertEqual((self.hero(g).health, self.hero(g, 2).health), (30, 15))
        self.assertEqual(len(self.hits(g)), 1)
        self.assertFalse(self.pending(g))
        self.portable(g)

    def test_pending_reward_survives_each_physical_source_retirement(self):
        for operation in ('kill', 'silence', 'transform', 'take', 'bounce'):
            with self.subTest(operation=operation):
                g = self.game((CARD, P+operation, P+'heal'))
                source = self.play(g, CARD)
                original = self.pending(g)[0].source_allocation
                self.play(g, P+operation, source)
                self.play(g, P+'heal')
                hit = self.hits(g)[0]
                self.assertEqual((hit.source_id, hit.source_card_id, hit.source_controller), (source, CARD, 1))
                self.assertEqual(hit.source_zone_epoch, dict(original)['zone_epoch'])
                self.assertEqual(self.hero(g, 2).health, 15)
                self.portable(g)

    def test_capture_precedes_assignment_reaction_transform_and_does_not_borrow_later_keywords(self):
        g = self.game((CARD, P+'leech', P+'heal'), mode='retire')
        source = self.play(g, CARD)
        self.assertEqual(g.state.entities[source].card_id, P+'sheep')
        self.play(g, P+'leech', source)
        self.play(g, P+'heal')
        self.assertEqual(self.hits(g)[0].source_card_id, CARD)
        self.assertFalse(any(e.kind == 'lifesteal' for e in g.events))
        self.portable(g)

    def test_each_actual_replayed_battlecry_installs_a_distinct_reward(self):
        g = self.game((CARD, P+'bounce', P+'heal'), enemy_armor=10)
        source = self.play(g, CARD)
        self.play(g, P+'bounce', source)
        self.play(g, CARD)
        rows = self.pending(g)
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0].id, rows[1].id)
        self.assertNotEqual(rows[0].source_allocation, rows[1].source_allocation)
        self.play(g, P+'heal')
        self.assertEqual(self.hero(g, 2).health, 10)
        self.assertEqual(len(self.hits(g)), 2)
        self.assertFalse(self.pending(g))
        self.portable(g)

    def test_player_two_only_own_full_health_and_original_beneficiary(self):
        g = self.game((CARD, P+'heal_enemy', P+'heal'), player=2)
        self.play(g, CARD)
        self.play(g, P+'heal_enemy')
        self.assertEqual(len(self.pending(g, 2)), 1)
        self.play(g, P+'heal')
        self.assertEqual((self.hero(g, 1).health, self.hero(g, 2).health), (15, 30))
        self.assertEqual(self.hits(g)[0].source_controller, 2)
        self.portable(g)

    def test_shared_immunity_prevents_damage_but_does_not_refund_consumed_reward(self):
        g = self.game((CARD, P+'immune', P+'heal'))
        self.play(g, CARD)
        self.play(g, P+'immune')
        self.play(g, P+'heal')
        self.assertEqual(self.hero(g, 2).health, 30)
        self.assertEqual(self.hits(g)[0].prevention, 'immune')
        self.assertFalse(self.pending(g))
        self.portable(g)

    def test_full_assignment_and_maximum_only_clamp_use_original_transition_envelopes(self):
        for operation in ('setfull', 'shrink'):
            with self.subTest(operation=operation):
                g = self.game((CARD, P+operation))
                self.play(g, CARD)
                self.play(g, P+operation)
                self.assertEqual(self.hero(g, 2).health, 15)
                self.assertFalse(self.pending(g))
                self.portable(g)

    def test_already_full_small_maximum_is_checked_after_actual_assignment(self):
        g = self.game((CARD,), own_hero=P+'smallhero')
        self.play(g, CARD)
        self.assertEqual((self.hero(g).health, self.hero(g).max_health), (10, 10))
        self.assertEqual(self.hero(g, 2).health, 15)
        self.assertFalse(self.pending(g))
        self.portable(g)

    def test_new_hero_keeps_pending_and_healing_targets_current_physical_hero(self):
        g = self.game((CARD, P+'replace', P+'heal'))
        self.play(g, CARD)
        original = self.hero(g).id
        self.play(g, P+'replace')
        self.assertNotEqual(self.hero(g).id, original)
        self.play(g, P+'heal')
        self.assertEqual(self.hero(g, 2).health, 15)
        self.portable(g)

    def test_typed_pending_consume_restores_and_duplicate_success_runs_once(self):
        g = self.game((CARD, P+'manual'))
        self.play(g, CARD)
        self.play(g, P+'manual')
        other = self.portable(g)
        self.choose(g)
        self.choose(other)
        self.assertEqual(self.hero(g, 2).health, 15)
        self.assertEqual(len(self.hits(g)), 1)
        self.assertEqual(canonical_hash(g.snapshot()), canonical_hash(other.snapshot()))
        self.portable(g)

    def test_stale_consumption_cannot_borrow_a_new_same_specification_instance(self):
        g = self.game((CARD, P+'manual', P+'heal'))
        self.play(g, CARD)
        old = self.pending(g)[0].id
        self.play(g, P+'manual')
        self.choose(g, 'replace')
        self.assertEqual(self.hero(g, 2).health, 30)
        self.assertNotEqual(self.pending(g)[0].id, old)
        self.play(g, P+'heal')
        self.assertEqual(self.hero(g, 2).health, 15)
        self.portable(g)

    def test_choice_exception_rolls_back_consumption_damage_and_information(self):
        g = self.game((CARD, P+'manual'))
        self.play(g, CARD)
        self.play(g, P+'manual')
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate failure'):
            self.choose(g, 'bad')
        self.assertEqual(canonical_hash(before), canonical_hash(g.snapshot()))
        self.assertEqual(len(self.pending(g)), 1)
        self.choose(g, 'after')
        self.assertFalse(self.pending(g))
        self.assertEqual(self.hero(g, 2).health, 30)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate failure'):
            self.choose(g, 'bad')
        self.assertEqual(canonical_hash(saved), canonical_hash(g.snapshot()))
        other = self.portable(g)
        self.choose(g)
        self.choose(other)
        self.assertEqual(self.hero(g, 2).health, 15)
        self.assertEqual(canonical_hash(g.snapshot()), canonical_hash(other.snapshot()))

    def test_consumption_precedes_removal_reactions_and_terminal_damage_stops_queue(self):
        g = self.game((CARD, P+'heal'), mode='wait')
        self.play(g, CARD)
        self.play(g, P+'heal')
        self.assertFalse(self.pending(g))
        self.assertEqual(self.hero(g, 2).health, 30)
        other = self.portable(g)
        self.choose(g)
        self.choose(other)
        self.assertEqual(self.hero(g, 2).health, 15)
        self.assertEqual(canonical_hash(g.snapshot()), canonical_hash(other.snapshot()))
        terminal = self.game((CARD, CARD, P+'heal'))
        self.play(terminal, CARD)
        self.play(terminal, CARD)
        self.play(terminal, P+'heal')
        self.assertEqual(terminal.state.status, 'finished')
        self.assertEqual(len(self.hits(terminal)), 2)
        self.portable(terminal)

    def test_root_exception_restores_original_unconsumed_instance_and_complete_action(self):
        for mode, spell in ((None, P+'badheal'), ('fail', P+'heal')):
            with self.subTest(mode=mode):
                g = self.game((CARD, spell), mode=mode)
                self.play(g, CARD)
                before = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'deliberate failure'):
                    self.play(g, spell)
                self.assertEqual(canonical_hash(before), canonical_hash(g.snapshot()))
                self.portable(g)

    def test_strict_consume_payload_and_owner_or_future_instance_reject(self):
        g = self.game((CARD,))
        self.play(g, CARD)
        instance = self.pending(g)[0]
        for args in ((True, instance), (1, object()), (1, instance, []), (1, instance, ('bad',))):
            with self.assertRaises(ValueError):
                ConsumePlayerEffect(*args)
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        request = ConsumePlayerEffect(1, instance)
        self.assertEqual(codec.decode(codec.encode(request)), request)
        for bad in (ConsumePlayerEffect(2, instance),
                ConsumePlayerEffect(1, replace(instance, id=g.state.next_attachment_id))):
            with self.assertRaises(ValueError):
                codec.encode(bad)
        with self.assertRaises(ValueError):
            replace(instance, entered_order=g.state.next_order)
        self.assertIs(type(instance), PlayerEffect)

    def test_current_format_restores_and_previous_format_is_explicitly_rejected(self):
        g = self.game((CARD,))
        self.play(g, CARD)
        self.assertEqual(g.snapshot()['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        saved = deepcopy(g.snapshot())
        saved['schema_version'] = SNAPSHOT_SCHEMA_VERSION - 1
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, registry(None, True))
        self.portable(g)


if __name__ == '__main__':
    unittest.main()
