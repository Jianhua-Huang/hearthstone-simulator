"""Healing Rain: immune base units through the shared health/split interpreter.

These tests verify the explicit local policy; they do not certify CN timing.
"""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_split_healing_cards import (
    HEALING_RAIN, load_batch, register_native_split_healing_cards)
from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard,
    PlayerSetup, Registry, Scenario, SelectChoice, TargetSpec, Zone)
from hs_sim.engine.effects import (ChoiceOption, Damage, Destroy, EquipWeapon, Heal,
    InvokeBehavior, RandomDamage, RequestChoice)
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import (DamageKind, HealingKind, HealthFlow, HealthLayer,
    HealthOp, HealthRule, LimitedTriggerSpec, PlayerEffectSpec, RewindSpec, SpellSchool)
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.random_split_damage import (
    FinishRandomSplitRoot, RandomSplitDamage, RandomSplitHealing, SplitDamageScope,
    SplitHealingRoot, closed_root, quote_budget)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import canonical_digest

P = 'k188.'
HERO, BODY = P+'hero', P+'body'


@lru_cache(maxsize=None)
def registry(mode=None):
    r = Registry('k188-split-healing-'+str(mode))
    register_native_split_healing_cards(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100))
    r.register_card(CardDefinition(BODY, BODY, CardType.MINION, health=20))
    r.register_card(CardDefinition(P+'power', P+'power', CardType.MINION, health=20, spell_damage=5))
    for name, rule in (
        ('scale', HealthRule(HealthFlow.HEALING, HealthOp.SCALE, 2,
            source_relation='friendly', healing_kinds=(HealingKind.SPELL,), schools=(SpellSchool.NATURE,))),
        ('incoming', HealthRule(HealthFlow.HEALING, HealthOp.ADD, 1,
            layer=HealthLayer.TARGET, target_relation='friendly')),
        ('convert', HealthRule(HealthFlow.HEALING, HealthOp.CONVERT, source_relation='friendly')),
        ('prevent', HealthRule(HealthFlow.HEALING, HealthOp.PREVENT, source_relation='friendly')),
        ('redirect', HealthRule(HealthFlow.HEALING, HealthOp.REDIRECT,
            layer=HealthLayer.TARGET, target_relation='friendly', redirect_to='enemy_hero')),
    ):
        r.register_card(CardDefinition(P+name, P+name, CardType.MINION, health=20, health_rules=(rule,)))
    r.register_player_effect(PlayerEffectSpec(P+'next', P+'next', kind='next_healing_damage'))
    def fail(c):
        raise ResolutionError('k188 deliberate health continuation failure')
    r.register_behavior(P+'fail', fail)
    bodies = dict(
        ordinary=lambda c: (RandomSplitDamage(c.player_id, c.cast.id, c.source_id, 1,
            SplitDamageScope('enemy', (CardType.HERO,))),),
        zero=lambda c: (RandomSplitHealing(c.player_id, c.cast.id, c.source_id, 0),),
        next=lambda c: (AddPlayerEffect(c.player_id, P+'next', c.source_id),),
        dormant=lambda c: (MakeDormant(c.target_id, 2, c.source_id),),
        enemy_cast=lambda c: (CastSpell(2, HEALING_RAIN, c.source_id),),
        rewind=lambda c: (CastSpell(c.player_id, HEALING_RAIN, c.source_id),),
    )
    for amount in (1, 2, 20, 99):
        bodies['wound'+str(amount)] = lambda c, amount=amount: (
            Damage(c.target_id, amount, c.source_id, DamageKind.EFFECT),)
    for name, fn in bodies.items():
        r.register_behavior(P+name, fn)
        targeted = name.startswith('wound') or name == 'dormant'
        kwargs = dict(targeting=TargetSpec(zones=(Zone.HERO, Zone.BOARD),
            kinds=(CardType.HERO, CardType.MINION))) if targeted else {}
        if name == 'rewind':
            kwargs.update(keywords=(Keyword.REWIND,), rewind=RewindSpec())
        r.register_card(CardDefinition(P+name, P+name, CardType.SPELL, on_play=P+name, **kwargs))
    if mode:
        def eligible(c):
            v = health_result(c.event)
            return (v is not None and v.source_card_id == HEALING_RAIN and
                v.split_packet is not None and v.split_packet.index == 1)
        def watch(c):
            if mode == 'fail':
                return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
            hero = c.state.players[1].hero_id
            options = [ChoiceOption('ok', 'Continue'),
                ChoiceOption('bad', 'Failed continuation', (
                    RandomDamage((c.state.players[2].hero_id,), 1, c.source_id),
                    EquipWeapon(1, BODY))),
                ChoiceOption('fill', 'Heal to full', (Heal(hero, 100, c.source_id),)),
                ChoiceOption('nested', 'Nested actual damage cast', (CastSpell(1, P+'ordinary', c.source_id),))]
            for i in c.state.players[1].board:
                if c.state.entities[i].card_id == BODY:
                    options.append(ChoiceOption('injure', 'New injured candidate', (Damage(i, 2, c.source_id),)))
                if c.state.entities[i].card_id == P+'convert':
                    options.append(ChoiceOption('remove', 'Remove live converter', (Destroy(i, c.source_id),)))
            return (RequestChoice(c.player_id, tuple(options), c.source_id),)
        r.register_trigger_condition(P+'eligible', eligible)
        r.register_behavior(P+'watch', watch)
        r.register_card(CardDefinition(P+'watch', P+'watch', CardType.MINION, health=20,
            limited_triggers=(LimitedTriggerSpec('health_resolved', P+'watch', condition_id=P+'eligible'),)))
    r.validate()
    return r


class NativeSplitHealingTests(unittest.TestCase):
    def game(self, hand=(P+'wound20', HEALING_RAIN), board=(), enemy=(), mode=None):
        self.mode = mode
        if mode:
            board = (*board, P+'watch')
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO, hand=hand, board=board, deck=(BODY,)*6, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup(HERO, board=enemy, deck=(BODY,)*6, mana=30, max_mana=30, mana_cap=30)), seed=188), registry(mode))

    def hero(self, g, p=1):
        return g.state.players[p].hero_id

    def eid(self, g, cid):
        return next(i for i in g.state.players[1].board if g.state.entities[i].card_id == cid)

    def play(self, g, cid=HEALING_RAIN, target=None):
        i = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, i, target))
        return i

    def wound(self, g, amount=20, target=None):
        self.play(g, P+'wound'+str(amount), target if target is not None else self.hero(g))

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def values(self, g):
        return [v for e in g.events if (v := health_result(e)) is not None and
            v.source_card_id == HEALING_RAIN and v.split_packet is not None]

    def portable(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        reader = registry.__wrapped__(self.mode)
        self.assertIsNot(reader, g.registry)
        other = Game.from_snapshot(deepcopy(snapshot), reader)
        self.assertEqual(other.snapshot(), snapshot)
        self.assertEqual(g.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), snapshot)
        return other

    def rehash(self, s):
        s['events_hash'] = canonical_hash(s['events'])
        s['state_hash'] = canonical_hash({k: s[k] for k in (
            'ruleset', 'registry_fingerprint', 'mechanics_version', 'state', 'rng_state',
            'resolution_frame', 'rewind_session', 'match_setup', 'generation_context', 'information')})
        return s

    def reject(self, s):
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(self.rehash(s), registry(self.mode))
        self.assertNotIn('digest mismatch', str(error.exception))

    def test_complete_original_face_metadata_and_immune_tag(self):
        d = load_batch(); row, = d['cards']; raw = row['record']
        card = registry().card(HEALING_RAIN)
        self.assertEqual(canonical_digest(raw), row['record_sha256'])
        self.assertEqual(card.metadata, metadata_from_record(raw))
        self.assertEqual((card.cost, card.spell_school, raw['tags']['CLASS'], raw['tags']['349']),
            (3, SpellSchool.NATURE, 8, 1))
        self.assertEqual(len(d['official_observations']), 2)
        self.assertFalse(d['formal_pool_complete'] or d['cn_calibrated'])

    def test_paid_real_spell_has_twelve_healing_units_and_no_damage_history(self):
        g = self.game(); self.wound(g); source = self.play(g); root, = g.state.split_healing_history
        self.assertIs(type(root), SplitHealingRoot)
        self.assertEqual((root.request.source_id, root.quote.cast.source_id), (source, source))
        self.assertEqual((root.quote.budget, len(root.packets), g.state.players[1].mana), (12, 12, 27))
        self.assertEqual(g.state.entities[self.hero(g)].health, 92)
        self.assertEqual(g.state.split_damage_history, [])
        self.assertEqual([(v.original_flow, v.flow, v.base_amount, v.spell_bonus, v.healed)
            for v in self.values(g)], [('healing', 'healing', 1, 0, 1)]*12)

    def test_live_pool_drops_fully_healed_candidates_and_stops_after_three(self):
        g = self.game((P+'wound1', P+'wound2', HEALING_RAIN), board=(BODY,))
        self.wound(g, 1); self.wound(g, 2, self.eid(g, BODY)); self.play(g)
        root, = g.state.split_healing_history
        self.assertEqual((len(root.packets), root.reason), (3, 'empty_pool'))
        self.assertEqual(sum(v.healed for v in self.values(g)), 3)
        for p in root.packets:
            self.assertTrue(all(c.health < g.state.entities[c.allocation.entity_id].max_health for c in p.selection.candidates))
        self.assertEqual(root.empty_selection.rng_before, root.empty_selection.rng_after)

    def test_full_friendly_characters_stop_without_rng_or_health_delivery(self):
        g = self.game((HEALING_RAIN,), board=(BODY,)); before = g.snapshot()['rng_state']; self.play(g)
        root, = g.state.split_healing_history
        self.assertEqual((root.packets, root.reason), ((), 'empty_pool'))
        self.assertEqual(g.snapshot()['rng_state'], before)
        self.assertEqual(self.values(g), [])
        self.portable(g)

    def test_enemy_and_injured_dormant_minion_are_excluded(self):
        g = self.game((P+'wound2', P+'wound20', P+'dormant', HEALING_RAIN), board=(BODY,), enemy=(BODY,))
        body = self.eid(g, BODY); self.wound(g, 2, body); self.play(g, P+'dormant', body)
        self.wound(g, target=self.hero(g, 2)); self.play(g)
        root, = g.state.split_healing_history
        self.assertEqual(root.packets, ())

    def test_spell_power_does_not_amplify_base_units_or_normal_healing(self):
        g = self.game(board=(P+'power',)); self.wound(g); self.play(g); root, = g.state.split_healing_history
        self.assertEqual((root.quote.spell_bonus, root.quote.budget, root.quote.contributions), (0, 12, ()))
        self.assertTrue(all(v.spell_bonus == 0 and v.healed == 1 for v in self.values(g)))

    def test_live_healing_multiplier_applies_once_to_each_base_unit(self):
        g = self.game((P+'wound99', HEALING_RAIN), board=(P+'scale',)); self.wound(g, 99); self.play(g)
        self.assertEqual(g.state.entities[self.hero(g)].health, 25)
        self.assertEqual([v.modified_amount for v in self.values(g)], [2]*12)
        self.assertEqual(g.state.split_healing_history[0].quote.budget, 12)

    def test_recipient_rule_uses_ordinary_target_numeric_layer(self):
        g = self.game((P+'wound99', HEALING_RAIN), board=(P+'incoming',)); self.wound(g, 99); self.play(g)
        self.assertEqual([v.healed for v in self.values(g)], [2]*12)

    def test_prevented_healing_still_consumes_twelve_selected_base_units(self):
        g = self.game(board=(P+'prevent',)); self.wound(g); self.play(g)
        self.assertEqual((len(self.values(g)), sum(v.healed for v in self.values(g))), (12, 0))
        self.assertEqual(g.state.entities[self.hero(g)].health, 80)

    def test_routing_keeps_original_selection_and_records_actual_recipient(self):
        g = self.game(board=(P+'redirect',)); self.wound(g); self.play(g)
        self.assertEqual({(v.original_target_id, v.target_id) for v in self.values(g)},
            {(self.hero(g), self.hero(g, 2))})
        self.assertEqual(len(self.values(g)), 12)

    def test_conversion_preserves_healing_origin_and_immune_spell_packets(self):
        g = self.game(board=(P+'convert', P+'power')); self.wound(g); self.play(g)
        self.assertEqual(g.state.entities[self.hero(g)].health, 68)
        self.assertEqual([(v.original_flow, v.flow, v.damage_kind, v.spell_bonus, v.damage_dealt)
            for v in self.values(g)], [('healing', 'damage', 'spell', 0, 1)]*12)
        self.assertEqual(g.state.split_damage_history, [])
        self.portable(g)

    def test_next_healing_conversion_is_consumed_by_one_real_unit_batch(self):
        g = self.game((P+'wound20', P+'next', HEALING_RAIN)); self.wound(g); self.play(g, P+'next'); self.play(g)
        self.assertEqual([v.flow for v in self.values(g)], ['damage']+['healing']*11)
        self.assertEqual(g.state.players[1].player_effects, [])

    def test_terminal_converted_unit_interrupts_remaining_budget(self):
        g = self.game((P+'wound99', HEALING_RAIN), board=(P+'convert',)); self.wound(g, 99); self.play(g)
        root, = g.state.split_healing_history
        self.assertEqual((g.state.status, len(root.packets), root.reason), ('finished', 1, 'terminal'))
        self.assertTrue(root.interrupted)
        self.portable(g)

    def test_first_unit_wait_independent_restore_clone_and_replay(self):
        g = self.game(mode='wait'); self.wound(g); self.play(g)
        self.assertIsNotNone(g.state.pending_choice)
        first = g.state.split_healing_history[0].packets[0].selection
        other = self.portable(g)
        for x in (g, other): self.choose(x)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.split_healing_history[0].packets[0].selection, first)
        self.assertEqual(len(self.values(g)), 12)

    def test_waiting_failure_rolls_back_choice_rng_health_and_original_budget(self):
        g = self.game(mode='wait'); self.wound(g); self.play(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g)
        self.assertEqual(g.state.players[1].mana, 27)

    def test_failure_during_first_health_reaction_rolls_back_entire_paid_cast(self):
        g = self.game(mode='fail'); self.wound(g); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'): self.play(g)
        self.assertEqual(g.snapshot(), before)

    def test_later_units_requery_a_newly_injured_character(self):
        g = self.game(board=(BODY,), mode='wait'); self.wound(g); self.play(g)
        body = self.eid(g, BODY)
        self.assertNotIn(body, [c.allocation.entity_id for c in g.state.split_healing_history[0].packets[0].selection.candidates])
        self.choose(g, 'injure')
        self.assertIn(body, [c.allocation.entity_id for c in g.state.split_healing_history[0].packets[1].selection.candidates])

    def test_becoming_full_during_wait_stops_without_additional_rng(self):
        g = self.game(mode='wait'); self.wound(g); self.play(g); before = g.snapshot()['rng_state']; self.choose(g, 'fill')
        self.assertEqual(len(self.values(g)), 1)
        self.assertEqual(g.snapshot()['rng_state'], before)

    def test_live_converter_removal_changes_later_packets_without_reselecting_first(self):
        g = self.game(board=(P+'convert',), mode='wait'); self.wound(g); self.play(g); self.choose(g, 'remove')
        self.assertEqual([v.flow for v in self.values(g)], ['damage']+['healing']*11)

    def test_nested_damage_and_healing_share_allocator_with_separate_histories(self):
        g = self.game(mode='wait'); self.wound(g); self.play(g); self.choose(g, 'nested')
        h, = g.state.split_healing_history; d, = g.state.split_damage_history
        self.assertEqual((h.id, d.id, d.parent_id, g.state.next_split_damage_root_id), (1, 2, 1, 3))
        self.assertTrue(h.completed and d.completed)
        event = next(e for e in g.events if e.kind == 'split_healing_closed')
        self.assertEqual(closed_root(g.state, event), h)
        self.portable(g)

    def test_out_of_turn_cast_selects_actual_casters_friendly_characters(self):
        g = self.game((P+'wound20', P+'enemy_cast')); self.wound(g, target=self.hero(g, 2)); self.play(g, P+'enemy_cast')
        root, = g.state.split_healing_history
        self.assertEqual(root.request.player_id, 2)
        self.assertEqual({v.target_id for v in self.values(g)}, {self.hero(g, 2)})

    def test_zero_base_units_close_without_selection_or_rng(self):
        g = self.game((P+'zero',)); before = g.snapshot()['rng_state']; self.play(g, P+'zero')
        root, = g.state.split_healing_history
        self.assertEqual((root.quote.budget, root.packets, root.reason), (0, (), 'exhausted'))
        self.assertEqual(g.snapshot()['rng_state'], before)

    def test_real_rewind_restores_healing_history_and_replays_actual_retry(self):
        g = self.game((P+'wound20', P+'rewind')); self.wound(g); self.play(g, P+'rewind')
        self.portable(g); self.choose(g, 'retry'); self.portable(g)
        self.assertEqual(g.state.entities[self.hero(g)].health, 92)
        self.assertEqual(len(g.state.split_healing_history), 1)

    def test_rehashed_wait_cannot_drop_root_or_change_accepted_amount(self):
        g = self.game(mode='wait'); self.wound(g); self.play(g)
        self.assertEqual(Game.from_snapshot(self.rehash(deepcopy(g.snapshot())), registry(self.mode)).snapshot(), g.snapshot())
        for change in ('drop', 'amount', 'container'):
            with self.subTest(change=change):
                s = deepcopy(g.snapshot())
                if change == 'drop': s['state']['split_healing_history'] = []
                elif change == 'amount': s['state']['split_healing_history'][0]['request']['amount'] = 11
                else: s['state']['split_damage_history'] = s['state'].pop('split_healing_history'); s['state']['split_healing_history'] = []
                self.reject(s)

    def test_typed_profile_rejects_other_scope_invalid_units_or_missing_cast(self):
        for changes in ({'scope': SplitDamageScope()}, {'amount': True}, {'amount': -1}, {'cast_id': None}, {'profile': 'damage'}):
            with self.subTest(changes=changes):
                args = dict(player_id=1, cast_id=1, source_id=1, amount=12); args.update(changes)
                with self.assertRaises(ValueError): RandomSplitHealing(**args)

    def test_public_projection_excludes_split_proofs_and_private_unit_history(self):
        g = self.game(mode='wait'); self.wound(g); self.play(g)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for key in ('split_healing_history', 'split_packet', 'rng_before', 'rng_after', 'resolution_frame', 'contributions'):
                self.assertNotIn('"'+key+'"', public)

    def test_current_assembly_adds_only_original_card_and_rejects_old_schema(self):
        with patch('hs_sim.cards.native_split_healing_cards.register_native_split_healing_cards', lambda r: None):
            before = build_registry()
        after = build_registry()
        self.assertEqual(set(after.cards)-set(before.cards), {HEALING_RAIN})
        for cid, card in before.cards.items(): self.assertEqual(asdict(card), asdict(after.card(cid)))
        self.assertEqual(dict(before.pool_cards), dict(after.pool_cards))
        g = self.game(); s = g.snapshot(); s['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError): Game.from_snapshot(s, registry())


if __name__ == '__main__':
    unittest.main()
