"""Actual Cinder Sigil clocks and deferred spell units share the original kernel."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.cinder_sigil_card import CARD, PROGRAM, load_batch, register_cinder_sigil_card
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    Registry, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone, health_result)
from hs_sim.engine.effects import ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.model import (DamageKind, HealthFlow, HealthLayer, HealthOp, HealthRule,
    Keyword, PlayerEffectSpec, SpellSchool)
from hs_sim.engine.player_effects import RemovePlayerEffect
from hs_sim.engine.random_split_damage import (DELAYED_SPELL_PROFILE, NON_SPELL_PROFILE,
    PROFILE, RandomSplitDamage, quote_budget)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.engine.spell_casts import CastSpell

P = 'k207.'
HERO, FRAIL, BODY, SMALL, SHIELD, DORMANT, POWER, SCALE, WATCH, EMPTY = (
    P+x for x in ('hero', 'frail', 'body', 'small', 'shield', 'dormant', 'power', 'scale', 'watch', 'empty'))


@lru_cache(None)
def registry(mode=None):
    r = Registry(P+str(mode)); register_cinder_sigil_card(r)
    for card in (
        CardDefinition(HERO, HERO, CardType.HERO, health=80),
        CardDefinition(FRAIL, FRAIL, CardType.HERO, health=5),
        CardDefinition(BODY, BODY, CardType.MINION, health=10),
        CardDefinition(SMALL, SMALL, CardType.MINION, health=1),
        CardDefinition(SHIELD, SHIELD, CardType.MINION, health=1, keywords=(Keyword.DIVINE_SHIELD,)),
        CardDefinition(DORMANT, DORMANT, CardType.MINION, health=10, dormant_turns=20),
        CardDefinition(POWER, POWER, CardType.MINION, health=20, spell_damage=5),
        CardDefinition(SCALE, SCALE, CardType.MINION, health=20, health_rules=(HealthRule(
            HealthFlow.DAMAGE, HealthOp.SCALE, 2, layer=HealthLayer.SOURCE,
            source_relation='friendly', damage_kinds=(DamageKind.SPELL,)),)),
    ): r.register_card(card)
    r.register_behavior(P+'empty', lambda c: ())
    r.register_card(CardDefinition(EMPTY, EMPTY, CardType.SPELL, on_play=P+'empty'))
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('K207 deliberate failure')))
    r.register_behavior(P+'auto', lambda c: (CastSpell(c.player_id, CARD, c.source_id),))
    r.register_behavior(P+'enemy', lambda c: (CastSpell(3-c.player_id, CARD, c.source_id),))
    r.register_behavior(P+'remove', lambda c: tuple(RemovePlayerEffect(c.player_id, x.id)
        for x in c.state.players[c.player_id].player_effects if x.spec_id == PROGRAM))
    for name in ('auto', 'enemy', 'remove'):
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name))

    def watch(c):
        if mode == 'start_install':
            if c.event.player_id == c.player_id and sum(x.card_id == CARD for x in c.state.cast_history) == 1:
                return (CastSpell(c.player_id, CARD, c.source_id),)
            return ()
        if c.event.kind == 'player_effect_expired':
            if dict(c.event.data).get('effect_key') != PROGRAM:
                return ()
        else:
            result = health_result(c.event)
            if result is None or result.source_card_id != CARD:
                return ()
        if mode == 'fail':
            return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue'),
            ChoiceOption('bad', 'Rollback', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
            ChoiceOption('new', 'Install another Sigil', (CastSpell(c.player_id, CARD, c.source_id),)),
        ), c.source_id),)
    r.register_behavior(P+'watch', watch)
    event = {'start_install': 'turn_started', 'expiry_wait': 'player_effect_expired',
             'packet_wait': 'health_resolved', 'fail': 'health_resolved'}.get(mode)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=30,
        triggers=() if event is None else (TriggerSpec(event, P+'watch'),)))
    r.validate(); return r


class CinderSigilTests(unittest.TestCase):
    def game(self, hand=(CARD,), board=(), enemy=(), actor=1, mode=None, enemy_hero=HERO):
        self.mode = mode
        own = PlayerSetup(HERO, hand=hand, board=board, deck=(EMPTY,)*12,
                          mana=60, max_mana=60, mana_cap=60)
        other = PlayerSetup(enemy_hero, board=enemy, deck=(EMPTY,)*12,
                            mana=60, max_mana=60, mana_cap=60)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own),
            active_player=actor, seed=207), registry(mode))

    def play(self, g, cid=CARD):
        p = g.state.active_player
        eid = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(p, eid)); return eid

    def end(self, g, times=1):
        for _ in range(times): g.apply(EndTurn(g.state.active_player))

    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def finish(self, g):
        while g.state.pending_choice is not None: self.choose(g)

    def hero(self, g, player): return g.state.entities[g.state.players[player].hero_id]
    def sigils(self, g, player): return [e for e in g.state.players[player].player_effects if e.spec_id == PROGRAM]
    def results(self, g): return [r for e in g.events if (r := health_result(e)) is not None and r.source_card_id == CARD]

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); r = registry.__wrapped__(self.mode)
        self.assertEqual(Game.from_snapshot(deepcopy(saved), r).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        return Game.from_snapshot(deepcopy(saved), r)

    def test_complete_face_and_shared_main_registry_installation(self):
        from hs_sim.cards import build_registry
        r = build_registry(); card = r.card(CARD); data = load_batch()
        self.assertEqual((card.name, card.cost, card.spell_school, card.ongoing_effect_id),
                         ('燃薪咒符', 2, SpellSchool.FEL, PROGRAM))
        self.assertEqual(card.metadata.classes[0].value, 'demon_hunter')
        self.assertEqual(data['cards'][0]['record']['tags']['349'], 1)
        self.assertTrue(r.player_effect(PROGRAM).capture_health_source)

    def test_original_payment_clock_and_no_second_cast(self):
        g = self.game(); source = self.play(g)
        self.assertEqual(g.state.players[1].mana, 58)
        self.assertFalse(g.state.split_damage_history)
        instance = self.sigils(g, 1)[0]
        self.assertEqual((instance.remaining_turns, instance.source_player_id), (1, 1))
        self.assertIsNotNone(instance.source_allocation)
        self.portable(g); self.end(g)
        self.assertEqual(self.hero(g, 2).health, 80)
        self.end(g)
        self.assertEqual(self.hero(g, 2).health, 74)
        self.assertFalse(self.sigils(g, 1)); self.assertEqual(len(g.state.cast_history), 1)
        root = g.state.split_damage_history[0]
        self.assertEqual((root.request.cast_id, root.quote.cast, root.quote.budget), (None, None, 6))
        self.assertEqual(root.quote.player_effect, instance)
        self.assertEqual(root.quote.source.entity_id, source)
        self.assertEqual(len(root.packets), 6); self.assertTrue(root.completed)

    def test_second_seat_uses_original_player_and_enemy_scope(self):
        g = self.game(actor=2); self.play(g); self.end(g, 2)
        self.assertEqual(self.hero(g, 1).health, 74)
        self.assertEqual(self.hero(g, 2).health, 80)
        self.assertTrue(all(r.source_controller == 2 for r in self.results(g)))

    def test_real_spell_packets_keep_fel_school_and_ignore_spell_damage(self):
        g = self.game(board=(POWER,)); self.play(g); self.end(g, 2)
        root = g.state.split_damage_history[0]
        self.assertEqual((root.quote.budget, root.quote.spell_bonus, root.quote.contributions), (6, 0, ()))
        self.assertTrue(all(r.damage_kind == DamageKind.SPELL.value and r.spell_bonus == 0 for r in self.results(g)))
        self.assertEqual(root.quote.school, SpellSchool.FEL)
        self.assertEqual(self.hero(g, 2).health, 74)

    def test_ordinary_spell_source_rules_still_apply_to_each_unit(self):
        g = self.game(board=(SCALE, POWER)); self.play(g); self.end(g, 2)
        self.assertEqual(g.state.split_damage_history[0].quote.budget, 6)
        self.assertEqual(self.hero(g, 2).health, 68)

    def test_current_target_pool_excludes_friendlies_and_dormant_and_requeries_deaths(self):
        g = self.game(board=(BODY,), enemy=(SMALL, SHIELD, DORMANT))
        self.play(g); self.end(g, 2)
        root = g.state.split_damage_history[0]
        for packet in root.packets:
            self.assertTrue(all(x.allocation.controller == 2 and x.allocation.card_id != DORMANT
                                for x in packet.selection.candidates))
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].damage, 0)
        self.assertTrue(root.completed)
        self.portable(g)

    def test_multiple_sigils_expire_independently(self):
        g = self.game(hand=(CARD,)*3)
        for _ in range(3): self.play(g)
        self.assertEqual(len(self.sigils(g, 1)), 3)
        self.end(g, 2)
        self.assertEqual(self.hero(g, 2).health, 62)
        roots = g.state.split_damage_history
        self.assertEqual(len(roots), 3)
        self.assertEqual(len({x.request.player_effect.id for x in roots}), 3)
        self.assertEqual(len(g.state.cast_history), 3)

    def test_sigil_capacity_is_checked_before_payment(self):
        g = self.game(hand=(CARD,)*6)
        for _ in range(5): self.play(g)
        before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g)
        self.assertEqual(g.snapshot(), before)

    def test_auto_out_of_turn_cast_fires_at_the_first_actual_owner_start(self):
        g = self.game(hand=(P+'enemy',)); self.play(g, P+'enemy')
        self.assertEqual(len(self.sigils(g, 2)), 1)
        self.assertEqual(g.state.players[1].mana, 60)
        self.end(g)
        self.assertEqual(self.hero(g, 1).health, 74)
        self.assertFalse(self.sigils(g, 2))
        self.assertEqual(len(g.state.cast_history), 2)

    def test_removed_sigil_does_not_execute_expiry_damage(self):
        g = self.game(hand=(CARD, P+'remove')); self.play(g); self.play(g, P+'remove')
        self.end(g, 2)
        self.assertFalse(g.state.split_damage_history)
        self.assertEqual(self.hero(g, 2).health, 80)

    def test_sigil_installed_by_start_reaction_does_not_tick_the_same_boundary(self):
        g = self.game(board=(WATCH,), mode='start_install'); self.play(g); self.end(g, 2)
        self.assertEqual(self.hero(g, 2).health, 74)
        self.assertEqual(len(self.sigils(g, 1)), 1)
        self.end(g, 2)
        self.assertEqual(self.hero(g, 2).health, 68)
        self.assertFalse(self.sigils(g, 1))

    def test_expiry_wait_preserves_source_before_split_acceptance_and_new_instance_is_later(self):
        g = self.game(board=(WATCH,), mode='expiry_wait'); self.play(g); self.end(g, 2)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(g.state.split_damage_history)
        self.assertFalse(self.sigils(g, 1)); self.portable(g)
        self.choose(g, 'new'); self.finish(g)
        self.assertEqual(self.hero(g, 2).health, 74)
        self.assertEqual(len(self.sigils(g, 1)), 1)
        self.end(g, 2); self.finish(g)
        self.assertEqual(self.hero(g, 2).health, 68)

    def test_packet_wait_restore_clone_replay_and_failure_preserve_original_rng(self):
        g = self.game(board=(WATCH,), mode='packet_wait'); self.play(g); self.end(g, 2)
        waits = 0
        while g.state.pending_choice is not None:
            if waits in (0, 2, 5):
                other = self.portable(g); before = g.snapshot()
                with self.assertRaises(ResolutionError): self.choose(g, 'bad')
                self.assertEqual(g.snapshot(), before)
                self.choose(g); self.choose(other)
                self.assertEqual(g.snapshot(), other.snapshot())
            else: self.choose(g)
            waits += 1
        self.assertEqual(waits, 6)
        self.assertEqual(self.hero(g, 2).health, 74)

    def test_expiry_failure_rolls_back_entire_boundary_and_instance(self):
        g = self.game(board=(WATCH,), mode='fail'); self.play(g); self.end(g)
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.end(g)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(len(self.sigils(g, 1)), 1)

    def test_terminal_hero_damage_interrupts_remaining_units(self):
        g = self.game(enemy_hero=FRAIL); self.play(g); self.end(g, 2)
        self.assertEqual(g.state.status, 'finished')
        root = g.state.split_damage_history[0]
        self.assertTrue(root.interrupted); self.assertEqual(root.reason, 'terminal')
        self.assertEqual(len(root.packets), 5)
        self.portable(g)

    def test_delayed_request_rejects_live_wrong_player_cast_kind_and_numeric_policy(self):
        g = self.game(); source = self.play(g); instance = self.sigils(g, 1)[0]
        request = RandomSplitDamage(1, None, source, 6, profile=DELAYED_SPELL_PROFILE,
                                    spell_bonus_multiplier=0, player_effect=instance)
        with self.assertRaises(ResolutionError): quote_budget(g.state, g.registry, request, g.state.action_number, len(g.events))
        for changes in (dict(player_id=2), dict(cast_id=1), dict(player_effect=None),
                        dict(spell_bonus_multiplier=1), dict(kind=DamageKind.EFFECT),
                        dict(profile=PROFILE, cast_id=1), dict(profile=NON_SPELL_PROFILE, kind=DamageKind.EFFECT)):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(request, **changes)

    def test_captured_source_quote_is_independent_of_later_physical_source(self):
        g = self.game(board=(WATCH,), mode='packet_wait'); source = self.play(g); self.end(g, 2)
        root = g.state.split_damage_history[0]
        detached = g.state
        detached.entities[source].controller = 2
        detached.entities[source].card_id = EMPTY
        quote = quote_budget(detached, g.registry, root.request, root.quote.root_action, root.quote.event_cursor)
        self.assertEqual((quote.source.entity_id, quote.source.card_id, quote.source.controller), (source, CARD, 1))
        self.assertEqual(quote.source, root.quote.source)

    def test_capture_declaration_is_finite_and_old_schema_is_rejected(self):
        for changes in (dict(capture_health_source=1), dict(kind='persistent', duration=None, tick_event=None),
                        dict(duration=2), dict(tick_event='turn_ended'), dict(on_expire=None)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(registry().player_effect(PROGRAM), **changes)
        g = self.game(); self.play(g); saved = g.snapshot(); saved['schema_version'] = 403
        self.assertGreaterEqual(SNAPSHOT_SCHEMA_VERSION, 404)
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry())

    def test_saved_live_sigil_cannot_omit_its_declared_source_and_player_projection_hides_it(self):
        g = self.game(); self.play(g); saved = json.loads(json.dumps(g.snapshot()))
        def erase(value):
            if isinstance(value, dict):
                if value.get('spec_id') == PROGRAM and 'source_allocation' in value:
                    value['source_allocation'] = None; value['source_player_id'] = None
                for item in value.values(): erase(item)
            elif isinstance(value, list):
                for item in value: erase(item)
        erase(saved)
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as error: Game.from_snapshot(saved, registry())
        self.assertNotIn('digest mismatch', str(error.exception))
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe())+json.dumps(g.for_player(player).legal_actions())
            for key in ('source_allocation', 'source_player_id', 'player_effect', 'SplitBudgetQuote', 'rng_state'):
                if key == 'player_effect': continue  # The public player_effects DTO is intentional.
                self.assertNotIn(key, public)


if __name__ == '__main__':
    unittest.main()
