"""Explicit infinity policy, genuine health settlement, original RNG and end window."""
from random import Random
from types import SimpleNamespace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.infinite_secret_cards import load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, EndTurnSpec,
    Game, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.damage_history import spell_damage_dealt
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, GainArmor, InvokeBehavior,
    RequestChoice, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_rules import prepare_health
from hs_sim.engine.infinite_damage import (INFINITE_HEALTH_POLICY, INFINITE_HEALTH_VALUE,
    InfiniteDamageMinion, RandomInfiniteDamageMinion, deliver)
from hs_sim.engine.model import DamageKind, HealthFlow, HealthLayer, HealthOp, HealthRule, SpellSchool
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import canonical_digest

MAX = INFINITE_HEALTH_VALUE


def registry(mode=None):
    r = build_registry(); meta = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
    r.register_card(CardDefinition('k13d.hero', 'Hero', CardType.HERO, health=100, metadata=meta))
    for cid, hp, keywords, extra in (
        ('a', 5, (), {}), ('b', 5, (), {}), ('big', 20, (), {}),
        ('shield', 5, (Keyword.DIVINE_SHIELD,), {}), ('immune', 5, (Keyword.IMMUNE,), {}),
        ('sleep', 50, (), dict(dormant_turns=3)), ('bonus', 10, (), dict(spell_damage=4)),
    ):
        r.register_card(CardDefinition('k13d.'+cid, cid, CardType.MINION, attack=1, health=hp,
            keywords=keywords, metadata=meta, **extra))
    r.register_card(CardDefinition('k13d.location', 'Location', CardType.LOCATION, durability=3,
        on_use='k13d.noop', metadata=meta))
    rules = {
        'double': (HealthRule(HealthFlow.DAMAGE, HealthOp.SCALE, 2, source_relation='friendly'),),
        'half': (HealthRule(HealthFlow.DAMAGE, HealthOp.SCALE, 1, denominator=2, source_relation='friendly'),),
        'cap': (HealthRule(HealthFlow.DAMAGE, HealthOp.CAP, 1, layer=HealthLayer.TARGET, target_kinds=(CardType.MINION,)),),
        'floor': (HealthRule(HealthFlow.DAMAGE, HealthOp.FLOOR, 1, layer=HealthLayer.TARGET, target_kinds=(CardType.MINION,)),),
        'prevent': (HealthRule(HealthFlow.DAMAGE, HealthOp.PREVENT, layer=HealthLayer.TARGET, schools=(SpellSchool.FIRE,)),),
        'convert': (HealthRule(HealthFlow.DAMAGE, HealthOp.CONVERT, source_relation='friendly'),),
        'heal_double': (HealthRule(HealthFlow.HEALING, HealthOp.SCALE, 2, source_relation='friendly'),),
        'redirect': (
            HealthRule(HealthFlow.DAMAGE, HealthOp.REDIRECT, layer=HealthLayer.TARGET,
                target_kinds=(CardType.MINION,), target_relation='enemy', redirect_to='friendly_hero'),
            HealthRule(HealthFlow.DAMAGE, HealthOp.CAP, 1, layer=HealthLayer.TARGET,
                target_kinds=(CardType.HERO,), target_relation='friendly')),
    }
    for cid, rows in rules.items():
        r.register_card(CardDefinition('k13d.'+cid, cid, CardType.MINION, health=20, health_rules=rows, metadata=meta))
    r.register_behavior('k13d.callback', lambda c: (RequestChoice(c.player_id,
        (ChoiceOption('ok', 'Keep original health result'),), c.source_id),))
    scripts = {
        'noop': lambda c: (),
        'wound': lambda c: (Damage(c.state.players[c.player_id].hero_id, 10, c.source_id),),
        'hit': lambda c: (Damage(c.target_id, 17, c.source_id, DamageKind.SPELL),),
        'fail': lambda c: (AddToHand(c.player_id, 'missing.k13d'),),
        'direct': lambda c: (InfiniteDamageMinion(MinionReference.capture(c.state.entities[c.target_id]),
                                                c.source_id, 'k13d.callback'),),
    }
    for cid, body in scripts.items():
        r.register_behavior('k13d.'+cid, body)
        r.register_card(CardDefinition('k13d.'+cid, cid, CardType.SPELL, on_play='k13d.'+cid,
            targeting=TargetSpec(kinds=(CardType.MINION,)) if cid in ('hit', 'direct') else None, metadata=meta))
    r.register_card(CardDefinition('k13d.life', 'Lifesteal secret', CardType.SPELL,
        keywords=(Keyword.SECRET, Keyword.LIFESTEAL), secret=r.card('END_024').secret,
        spell_school=SpellSchool.FIRE, metadata=meta))
    r.register_behavior('k13d.end', lambda c: (Damage(c.state.players[3-c.player_id].hero_id, 3,
        c.source_id, DamageKind.MINION_ABILITY),))
    r.register_card(CardDefinition('k13d.end', 'Ordinary end body', CardType.MINION, health=7,
        triggers=(TriggerSpec('turn_ended', 'k13d.end', EndTurnSpec()),), metadata=meta))
    if mode:
        def watch(c):
            if mode == 'transform': return (Transform(c.event.target_id, 'k13d.big'),)
            return (RequestChoice(c.player_id, (
                ChoiceOption('ok', 'Continue original work'),
                ChoiceOption('bad', 'Rollback', (InvokeBehavior('k13d.fail', c.source_id, c.player_id),)),
            ), c.source_id),)
        event = 'secret_revealed' if mode == 'reveal_wait' else 'random_choice'
        r.register_behavior('k13d.watch', watch)
        r.register_card(CardDefinition('k13d.watch', 'Observer', CardType.MINION, health=20,
            triggers=(TriggerSpec(event, 'k13d.watch'),), metadata=meta))
    return r


class InfiniteSecretCardTests(unittest.TestCase):
    def game(self, enemy=('k13d.a',), board=(), mode=None, hand=()):
        self.mode = mode
        return Game.from_scenario(Scenario((
            PlayerSetup('k13d.hero', hand=('END_024', *hand), board=board, deck=('k13d.noop',)*5,
                        mana=20, max_mana=20, mana_cap=20),
            PlayerSetup('k13d.hero', board=enemy, deck=('k13d.noop',)*5,
                        mana=20, max_mana=20, mana_cap=20)), seed=229), registry(mode))
    def play(self, g, cid, target=None):
        eid = next(e for e in g.state.players[1].hand if g.state.entities[e].card_id == cid)
        g.apply(PlayCard(1, eid, target)); return eid
    def trigger(self, g, secret='END_024'):
        self.play(g, secret); g.apply(EndTurn(1)); g.apply(EndTurn(2))
    def rows(self, g):
        return [row.health_result for row in g.state.damage_history if row.health_result.source_card_id == 'END_024']
    def hero(self, g, player=1): return g.state.entities[g.state.players[player].hero_id]
    def portable(self, g):
        saved = g.snapshot(); other = Game.from_snapshot(saved, registry(self.mode))
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(self.mode)).snapshot(), saved); return other
    def finish(self, g, option='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (option,)))

    def test_full_pin_and_explicit_numeric_policy_are_separate_from_display_threshold(self):
        data = load_batch(); row = data['cards'][0]; r = registry()
        self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        self.assertEqual((row['recipe']['numeric_policy'], row['recipe']['infinite_value']), (INFINITE_HEALTH_POLICY, MAX))
        self.assertEqual(MAX, 2147483647); self.assertNotEqual(MAX, 1000000)
        self.assertEqual((r.card('END_024').cost, r.card('END_024').spell_school), (3, SpellSchool.FIRE))

    def test_opponent_end_deals_spell_damage_and_records_real_overkill_units(self):
        g = self.game(); target = g.state.players[2].board[0]; self.play(g, 'END_024')
        self.assertEqual(g.state.players[1].mana, 17); g.apply(EndTurn(1)); self.assertFalse(self.rows(g))
        g.apply(EndTurn(2)); row = self.rows(g)[0]
        self.assertEqual((row.base_amount, row.modified_amount, row.damage_dealt), (MAX, MAX, MAX))
        self.assertEqual((row.target_id, row.damage_kind, row.source_controller), (target, 'spell', 1))
        self.assertEqual(spell_damage_dealt(g.state, g.registry, 1, turn=2), MAX)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD); self.assertFalse(g.state.players[1].secrets)
        self.portable(g)

    def test_highest_uses_current_health_not_printed_maximum(self):
        g = self.game(('k13d.big', 'k13d.a'), hand=('k13d.hit',)); big, other = g.state.players[2].board
        self.play(g, 'k13d.hit', big); self.trigger(g)
        self.assertEqual(self.rows(g)[0].target_id, other); self.assertEqual(g.state.entities[big].health, 3); self.portable(g)

    def test_empty_board_keeps_secret_and_rng(self):
        g = self.game(()); before = g.snapshot()['rng_state']; self.trigger(g)
        self.assertEqual(g.snapshot()['rng_state'], before); self.assertEqual(len(g.state.players[1].secrets), 1)
        self.assertFalse(self.rows(g))

    def test_dormant_and_location_are_not_highest_ordinary_candidates(self):
        g = self.game(('k13d.sleep', 'k13d.location', 'k13d.a')); target = g.state.players[2].board[-1]
        self.trigger(g); self.assertEqual(self.rows(g)[0].target_id, target)
        self.assertEqual(len(g.state.players[2].board), 2); self.portable(g)

    def test_unique_maximum_has_no_random_draw(self):
        g = self.game(('k13d.big', 'k13d.a')); before = g.snapshot()['rng_state']; self.trigger(g)
        self.assertEqual(g.snapshot()['rng_state'], before)
        self.assertFalse(any(e.kind == 'random_choice' for e in g.events))

    def test_tied_maxima_draw_once_from_complete_physical_candidates(self):
        g = self.game(('k13d.a', 'k13d.b')); ids = tuple(g.state.players[2].board)
        expected = Random(); expected.setstate(g._rng.getstate()); selected = expected.choice(ids)
        self.trigger(g); draws = [e for e in g.events if e.kind == 'random_choice']
        self.assertEqual(len(draws), 1); self.assertEqual(dict(draws[0].data)['candidates'], ids)
        self.assertEqual(self.rows(g)[0].target_id, selected); self.assertEqual(g._rng.getstate(), expected.getstate()); self.portable(g)

    def test_divine_shield_and_immunity_prevent_damage_without_destroying(self):
        for cid, reason in (('shield', 'divine_shield'), ('immune', 'immune')):
            with self.subTest(cid=cid):
                g = self.game(('k13d.'+cid,)); target = g.state.players[2].board[0]; self.trigger(g)
                self.assertEqual((self.rows(g)[0].damage_dealt, self.rows(g)[0].prevention), (0, reason))
                self.assertEqual(g.state.entities[target].health, 5); self.assertFalse(g.state.death_history)
                self.assertFalse(g.state.players[1].secrets); self.portable(g)

    def test_spell_bonus_and_multiplier_saturate_at_explicit_limit(self):
        g = self.game(board=('k13d.bonus', 'k13d.double')); self.trigger(g)
        row = self.rows(g)[0]
        self.assertEqual((row.modified_amount, row.damage_dealt, row.spell_bonus), (MAX, MAX, 4)); self.portable(g)

    def test_integer_fraction_is_numeric_policy_not_symbolic_mathematical_infinity(self):
        g = self.game(board=('k13d.half',)); self.trigger(g)
        self.assertEqual(self.rows(g)[0].damage_dealt, MAX//2); self.portable(g)

    def test_target_cap_and_fire_prevention_use_existing_rules(self):
        for provider, actual in (('cap', 1), ('prevent', 0)):
            g = self.game(board=('k13d.'+provider,)); target = g.state.players[2].board[0]; self.trigger(g)
            self.assertEqual(self.rows(g)[0].damage_dealt, actual)
            self.assertEqual(g.state.entities[target].health, 5-actual); self.portable(g)

    def test_health_floor_limits_actual_units_and_history(self):
        g = self.game(board=('k13d.floor',)); target = g.state.players[2].board[0]; self.trigger(g)
        row = self.rows(g)[0]
        self.assertEqual((row.damage_dealt, row.floor_prevented, g.state.entities[target].health), (4, MAX-4, 1))
        self.assertEqual(spell_damage_dealt(g.state, g.registry, 1, turn=2), 4); self.portable(g)

    def test_redirection_and_hero_cap_reuse_actual_target_history(self):
        g = self.game(board=('k13d.redirect',)); target = g.state.players[2].board[0]; self.trigger(g)
        row = self.rows(g)[0]
        self.assertEqual((row.original_target_id, row.target_id, row.damage_dealt), (target, self.hero(g).id, 1))
        self.assertEqual(self.hero(g).health, 99); self.assertEqual(g.state.entities[target].health, 5); self.portable(g)

    def test_damage_conversion_preserves_bounded_healing_result(self):
        g = self.game(board=('k13d.convert', 'k13d.heal_double'), hand=('k13d.hit',))
        target = g.state.players[2].board[0]
        # The ordinary hit is converted too, so wound first in a separate direct scenario.
        r = registry(); g = Game.from_scenario(Scenario((
            PlayerSetup('k13d.hero', hand=('END_024', 'k13d.hit'), deck=('k13d.noop',)*3, mana=20, max_mana=20, mana_cap=20),
            PlayerSetup('k13d.hero', board=('k13d.big',), deck=('k13d.noop',)*3, mana=20, max_mana=20, mana_cap=20)), seed=229), r)
        target = g.state.players[2].board[0]; self.play(g, 'k13d.hit', target)
        # Use an explicit conversion fixture by playing its provider normally.
        # Register before any game freezes the registry; the provider starts in hand.
        g = self.game(('k13d.big',), hand=('k13d.hit', 'k13d.convert', 'k13d.heal_double'))
        target = g.state.players[2].board[0]; self.play(g, 'k13d.hit', target)
        self.play(g, 'k13d.convert'); self.play(g, 'k13d.heal_double'); self.trigger(g)
        row = self.rows(g)[0]
        self.assertTrue(row.converted); self.assertEqual((row.flow, row.modified_amount, row.healed), ('healing', MAX, 17))
        self.assertEqual(g.state.entities[target].health, 20); self.portable(g)

    def test_intrinsic_lifesteal_uses_actual_damage_and_bounded_restoration(self):
        g = self.game(board=('k13d.heal_double',), hand=('k13d.wound', 'k13d.life'))
        self.play(g, 'k13d.wound'); self.trigger(g, 'k13d.life')
        self.assertEqual(self.hero(g).health, 100)
        healing = [r.health_result for r in g.state.healing_history if r.health_result.from_lifesteal]
        self.assertEqual((len(healing), healing[0].modified_amount, healing[0].healed), (1, MAX, 10)); self.portable(g)

    def test_reveal_waiting_keeps_end_turn_and_original_rng_until_continuation(self):
        g = self.game(('k13d.a', 'k13d.b'), board=('k13d.watch',), mode='reveal_wait')
        before = g.snapshot()['rng_state']; self.trigger(g)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(g.snapshot()['rng_state'], before)
        self.assertEqual(g.state.turn, 2); self.assertFalse(self.rows(g)); other = self.portable(g)
        self.finish(g); self.finish(other); self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(self.rows(g)), 1); self.assertEqual(g.state.turn, 3); self.portable(g)

    def test_selected_tie_waiting_bad_choice_rolls_back_without_redraw(self):
        g = self.game(('k13d.a', 'k13d.b'), board=('k13d.watch',), mode='rng_wait'); self.trigger(g)
        self.assertIsNotNone(g.state.pending_choice); self.assertFalse(self.rows(g)); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.finish(g, 'bad')
        self.assertEqual(g.snapshot(), saved); other = self.portable(g)
        selected = next(e.target_id for e in g.events if e.kind == 'random_choice')
        self.finish(g); self.finish(other); self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.rows(g)[0].target_id, selected)
        self.assertEqual(sum(e.kind == 'random_choice' for e in g.events), 1); self.portable(g)

    def test_random_reaction_transform_invalidates_original_selection_without_redraw(self):
        g = self.game(('k13d.a', 'k13d.b'), board=('k13d.watch',), mode='transform'); self.trigger(g)
        self.assertFalse(self.rows(g)); self.assertEqual(len(g.state.players[2].board), 2)
        self.assertEqual(sum(e.kind == 'random_choice' for e in g.events), 1); self.portable(g)

    def test_shared_end_turn_order_has_no_secret_first_priority(self):
        g = self.game(('k13d.end',)); self.trigger(g)
        rows = [row.health_result for row in g.state.damage_history]
        self.assertEqual([row.source_card_id for row in rows], ['k13d.end', 'END_024'])
        self.assertEqual(self.hero(g).health, 97); self.portable(g)

    def test_public_callback_waiting_and_request_codec_roundtrip(self):
        g = self.game(hand=('k13d.direct',)); target = g.state.entities[g.state.players[2].board[0]]
        source = next(e for e in g.state.players[1].hand if g.state.entities[e].card_id == 'k13d.direct')
        ref = MinionReference.capture(target); request = RandomInfiniteDamageMinion((ref,), source, 'k13d.callback')
        codec = FrameCodec(g.mechanics, g.registry); self.assertEqual(codec.decode(codec.encode(request)), request)
        self.play(g, 'k13d.direct', target.id); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.damage_history[-1].health_result.damage_dealt, MAX); self.portable(g)
        self.finish(g); self.portable(g)

    def test_invalid_policy_and_unknown_callback_are_rejected_before_stale_skip(self):
        g = self.game(); source = next(e for e in g.state.players[1].hand if g.state.entities[e].card_id == 'END_024')
        ref = MinionReference(999, 2, 'k13d.a', 1, 1)
        with self.assertRaises(ValueError):
            deliver(SimpleNamespace(state=g.state, registry=g.registry), InfiniteDamageMinion(ref, source, 'missing.k13d'))
        target = g.state.players[2].board[0]
        for limit in (True, 1000000, MAX+1):
            with self.assertRaises(ResolutionError): prepare_health(g.state, g.registry, Damage(target, MAX, source, DamageKind.SPELL), numeric_limit=limit)
        for make in (lambda: InfiniteDamageMinion(ref, True), lambda: RandomInfiniteDamageMinion((ref, ref), source)):
            with self.assertRaises(ValueError): make()

    def test_player_view_has_no_private_numeric_policy_or_original_reference(self):
        g = self.game(('k13d.a', 'k13d.b'), board=('k13d.watch',), mode='rng_wait'); self.trigger(g)
        for viewer in (1, 2):
            public = json.dumps(g.for_player(viewer).observe())+json.dumps(g.player_events(viewer))
            for field in ('numeric_limit', 'zone_epoch', 'on_result', 'original_state_hash'):
                self.assertNotIn('"'+field+'"', public)


if __name__ == '__main__': unittest.main()
