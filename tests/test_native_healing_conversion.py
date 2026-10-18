"""Ruby Sanctum: original complete healing groups and ordinary health results."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_healing_conversion_cards import CARD, PROGRAM, load_batch, register_native_healing_conversion_cards
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction,
    Keyword, LimitedTriggerSpec, PlayCard, PlayerSetup, Registry, Scenario, SelectChoice,
    UseHeroPower, UseLocation, Zone)
from hs_sim.engine.effects import (ChoiceOption, Damage, DamageBatch, GainArmor, Heal, HealBatch,
    InvokeBehavior, ReplaceHero, RequestChoice)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.locations import DestroyLocation, ModifyLocation
from hs_sim.engine.model import DamageKind, HealingKind, PlayerEffectSpec
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell

P = 'k181.'
HERO, NEW, FILL, LIFE, SHIELD, POWER = (P+x for x in ('hero', 'new', 'filler', 'life_minion', 'shield', 'power'))


@lru_cache(maxsize=4)
def registry(role='writer', wait=False):
    r = Registry('k181-' + str(wait))
    register_native_healing_conversion_cards(r)
    for cid, kind, kw in (
        (HERO, CardType.HERO, dict(health=100)), (NEW, CardType.HERO, dict(health=100)),
        (FILL, CardType.MINION, dict(attack=2, health=12, keywords=(Keyword.CHARGE,))),
        (LIFE, CardType.MINION, dict(attack=2, health=12, keywords=(Keyword.CHARGE, Keyword.LIFESTEAL))),
        (SHIELD, CardType.MINION, dict(health=12, keywords=(Keyword.DIVINE_SHIELD,))),
    ):
        r.register_card(CardDefinition(cid, cid, kind, **kw))
    def hero(c, other=False):
        return c.state.players[3-c.player_id if other else c.player_id].hero_id
    def locations(c):
        return [i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == CARD]
    def group(c):
        ids = [hero(c)] + [i for i in c.state.players[c.player_id].board
                           if c.state.entities[i].kind == CardType.MINION]
        return (HealBatch(tuple(Heal(i, 3, c.source_id, HealingKind.SPELL) for i in ids)),)
    def life(c):
        ids = [i for i in c.state.players[2].board if c.state.entities[i].kind == CardType.MINION]
        return (DamageBatch(tuple(Damage(i, 2, c.source_id, DamageKind.SPELL) for i in ids)),)
    def fail(c):
        raise ResolutionError('k181 original health reaction failure')
    r.register_behavior(P+'fail', fail)
    scripts = dict(
        heal=lambda c: (Heal(hero(c), 3, c.source_id, HealingKind.SPELL),),
        other=lambda c: (Heal(hero(c, True), 3, c.source_id, HealingKind.SPELL),),
        twice=lambda c: (Heal(hero(c), 3, c.source_id, HealingKind.SPELL), Heal(hero(c), 3, c.source_id, HealingKind.SPELL)),
        batch=group, life=life,
        empty=lambda c: (HealBatch(()),),
        zero=lambda c: (Heal(hero(c), 0, c.source_id, HealingKind.SPELL),),
        invalid=lambda c: (Heal(locations(c)[0], 3, c.source_id, HealingKind.SPELL),),
        destroy=lambda c: (DestroyLocation(locations(c)[0], c.source_id),),
        drain=lambda c: (ModifyLocation(locations(c)[0], -2, c.source_id),),
        replace=lambda c: (ReplaceHero(c.player_id, NEW),),
        failheal=lambda c: (Heal(hero(c), 3, c.source_id, HealingKind.SPELL, on_result=P+'fail'),),
        wrong=lambda c: (AddPlayerEffect(c.player_id, PROGRAM, c.source_id),),
        enemy=lambda c: (CastSpell(2, P+'heal', c.source_id),),
    )
    for name, fn in scripts.items():
        r.register_behavior(P+name, fn)
        r.register_card(CardDefinition(P+name, P+name, CardType.SPELL, on_play=P+name,
            keywords=(Keyword.LIFESTEAL,) if name == 'life' else ()))
    r.register_behavior(POWER, lambda c: (Heal(hero(c), 3, c.source_id, HealingKind.HERO_POWER),))
    r.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, cost=2, on_use=POWER))
    if wait:
        r.register_trigger_condition(P+'watch', lambda c: dict(c.event.data).get('effect_key') == PROGRAM)
        r.register_behavior(P+'watch', lambda c: (
            GainArmor(c.player_id, len(c.state.damage_history)),
            RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id)))
        r.register_card(CardDefinition(P+'watch', P+'watch', CardType.MINION, health=12,
            limited_triggers=(LimitedTriggerSpec('player_effect_removed', P+'watch', condition_id=P+'watch'),)))
    r.validate()
    r.freeze()
    return r


def game(hand=(), board=(CARD,), enemy=(), wait=False):
    if wait:
        board = (*board, P+'watch')
    return Game.from_scenario(Scenario((
        PlayerSetup(HERO, hand=hand, board=board, deck=(FILL,)*12, mana=40, max_mana=40, mana_cap=40, hero_power_card_id=POWER),
        PlayerSetup(HERO, hand=(P+'heal',), board=enemy, deck=(FILL,)*12)), seed=181), registry('writer', wait))


def location(g, n=0):
    return [i for i in g.state.players[1].board if g.state.entities[i].card_id == CARD][n]


def use(g, n=0):
    g.apply(UseLocation(1, location(g, n)))


def play(g, cid):
    eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
    g.apply(PlayCard(1, eid, position=len(g.state.players[1].board) if cid == CARD else None))
    return eid


def hp(g, player=1):
    return g.state.entities[g.state.players[player].hero_id].health


def select(g, key='ok'):
    q = g.state.pending_choice
    g.apply(SelectChoice(q.player_id, q.id, (key,)))


class NativeHealingConversionTests(unittest.TestCase):
    def portable(self, g, wait=False):
        snap = g.snapshot()
        reader = registry('reader', wait)
        self.assertIsNot(reader, g.registry)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(snap)), reader).snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), snap)
        for pid in (1, 2):
            visible = json.dumps(g.observe(pid)) + json.dumps(g.player_events(pid)) + json.dumps(g.for_player(pid).legal_actions())
            for key in ('source_allocation', 'health_rule', 'next_healing_conversion', 'resolution_frame', 'rng_state'):
                self.assertNotIn('"'+key+'"', visible)

    def programs(self, g):
        return [e for e in g.state.players[1].player_effects if e.spec_id == PROGRAM]

    def test_01_full_original_native_location_face_and_pure_program(self):
        from tools.card_batch import check_face
        d = load_batch()
        for o in d['official_observations']:
            check_face(d['cards'][0]['record'], o['face'], o['locale'])
        card = registry().card(CARD)
        self.assertEqual((card.kind, card.cost, card.durability), (CardType.LOCATION, 1, 3))
        self.assertEqual(registry().player_effect(PROGRAM).kind, 'next_healing_damage')

    def test_02_real_paid_location_and_free_activation_use_existing_cooldown(self):
        g = game(hand=(CARD,), board=())
        eid = play(g, CARD)
        self.assertEqual(g.state.players[1].mana, 39)
        use(g)
        self.assertEqual(g.state.entities[eid].durability, 2)
        self.assertEqual(g.state.players[1].mana, 39)
        self.assertEqual(len(self.programs(g)), 1)
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            use(g)
        self.assertEqual(g.snapshot(), before)
        self.portable(g)

    def test_03_next_heal_deals_original_amount_at_full_health_then_second_heals(self):
        g = game(hand=(P+'heal', P+'heal'))
        use(g)
        source = play(g, P+'heal')
        self.assertEqual(hp(g), 97)
        self.assertFalse(self.programs(g))
        result = g.state.damage_history[-1].health_result
        self.assertEqual((result.source_id, result.damage_dealt, result.damage_kind), (source, 3, 'spell'))
        self.assertTrue(result.converted)
        play(g, P+'heal')
        self.assertEqual(hp(g), 100)
        self.portable(g)

    def test_04_whole_three_packet_heal_batch_converts_and_consumes_once(self):
        g = game(hand=(P+'batch',), board=(CARD, FILL, FILL))
        use(g)
        instance = self.programs(g)[0]
        play(g, P+'batch')
        self.assertEqual(hp(g), 97)
        self.assertEqual([g.state.entities[i].health for i in g.state.players[1].board if g.state.entities[i].kind == CardType.MINION], [9, 9])
        results = [r.health_result for r in g.state.damage_history]
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r.converted and instance.id in r.rule_ids for r in results))
        self.assertEqual(len({r.batch_id for r in results}), 1)
        self.assertEqual(sum(e.kind == 'player_effect_removed' for e in g.events), 1)
        self.assertFalse(self.programs(g))
        self.portable(g)

    def test_05_two_separate_heals_are_two_effects_not_one_merged_batch(self):
        g = game(hand=(P+'twice',))
        use(g)
        play(g, P+'twice')
        self.assertEqual(hp(g), 100)
        rows = [r.health_result for r in g.state.healing_history]
        self.assertEqual([r.converted for r in rows], [True, False])
        self.assertNotEqual(rows[0].batch_id, rows[1].batch_id)
        self.portable(g)

    def test_06_duplicate_programs_consume_together_without_double_conversion(self):
        g = game(hand=(P+'heal',), board=(CARD, CARD))
        use(g, 0)
        use(g, 1)
        self.assertEqual(len(self.programs(g)), 2)
        play(g, P+'heal')
        self.assertEqual(hp(g), 97)
        self.assertFalse(self.programs(g))
        self.assertEqual(sum(e.kind == 'player_effect_removed' for e in g.events), 2)
        self.portable(g)

    def test_07_original_source_location_can_leave_before_the_next_heal(self):
        g = game(hand=(P+'destroy', P+'heal'))
        eid = location(g)
        use(g)
        play(g, P+'destroy')
        self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD)
        self.assertEqual(len(self.programs(g)), 1)
        play(g, P+'heal')
        self.assertEqual(hp(g), 97)
        self.portable(g)

    def test_08_last_durability_activation_still_installs_independent_program(self):
        g = game(hand=(P+'drain', P+'heal'))
        eid = location(g)
        play(g, P+'drain')
        use(g)
        self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD)
        self.assertEqual(len(self.programs(g)), 1)
        play(g, P+'heal')
        self.assertEqual(hp(g), 97)
        self.portable(g)

    def test_09_replacing_hero_keeps_player_program_and_hits_new_hero(self):
        g = game(hand=(P+'replace', P+'heal'))
        use(g)
        old = g.state.players[1].hero_id
        play(g, P+'replace')
        self.assertNotEqual(g.state.players[1].hero_id, old)
        play(g, P+'heal')
        self.assertEqual(hp(g), 97)
        self.portable(g)

    def test_10_turn_end_expires_unconsumed_program_before_next_player(self):
        g = game(hand=(P+'heal',))
        use(g)
        g.apply(EndTurn(1))
        self.assertFalse(self.programs(g))
        self.assertTrue(any(e.kind == 'player_effect_expired' for e in g.events))
        g.apply(EndTurn(2))
        play(g, P+'heal')
        self.assertEqual(hp(g), 100)
        self.assertFalse(g.state.damage_history)
        self.portable(g)

    def test_11_healing_enemy_is_still_your_healing_but_opponent_source_is_not(self):
        g = game(hand=(P+'enemy', P+'other'))
        use(g)
        play(g, P+'enemy')
        self.assertEqual(len(self.programs(g)), 1)
        self.assertEqual(hp(g, 2), 100)
        play(g, P+'other')
        self.assertEqual(hp(g, 2), 97)
        self.assertFalse(self.programs(g))
        self.portable(g)

    def test_12_real_hero_power_heal_uses_existing_hero_power_damage_class(self):
        g = game()
        use(g)
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        self.assertEqual(hp(g), 97)
        self.assertEqual(g.state.damage_history[-1].health_result.damage_kind, 'hero_power')
        self.portable(g)

    def test_13_empty_and_invalid_healing_groups_do_not_invent_a_heal(self):
        g = game(hand=(P+'empty', P+'invalid', P+'heal'))
        use(g)
        play(g, P+'empty')
        play(g, P+'invalid')
        self.assertEqual(len(self.programs(g)), 1)
        play(g, P+'heal')
        self.assertEqual(hp(g), 97)
        self.portable(g)

    def test_14_real_zero_amount_healing_consumes_without_inventing_damage(self):
        g = game(hand=(P+'zero',))
        use(g)
        play(g, P+'zero')
        self.assertFalse(self.programs(g))
        self.assertEqual(hp(g), 100)
        self.assertEqual(g.state.damage_history[-1].health_result.damage_dealt, 0)
        self.assertTrue(g.state.damage_history[-1].health_result.converted)
        self.portable(g)

    def test_15_actual_minion_lifesteal_restoration_converts_once_without_recursion(self):
        g = game(board=(CARD, LIFE), enemy=(FILL,))
        use(g)
        life = next(i for i in g.state.players[1].board if g.state.entities[i].card_id == LIFE)
        g.apply(Attack(1, life, g.state.players[2].board[0]))
        self.assertEqual(hp(g), 98)
        self.assertFalse(self.programs(g))
        self.assertEqual(sum(e.kind == 'lifesteal' for e in g.events), 1)
        self.portable(g)

    def test_16_whole_multitarget_lifesteal_restoration_group_converts_all(self):
        g = game(hand=(P+'life',), enemy=(FILL, FILL))
        use(g)
        play(g, P+'life')
        self.assertEqual(hp(g), 96)
        self.assertEqual(sum(e.kind == 'player_effect_removed' for e in g.events), 1)
        rows = [dict(e.data) for e in g.events if e.kind == 'lifesteal']
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r['converted'] for r in rows))
        self.portable(g)

    def test_17_shield_prevention_with_no_lifesteal_restoration_does_not_consume(self):
        g = game(board=(CARD, LIFE), enemy=(SHIELD,))
        use(g)
        life = next(i for i in g.state.players[1].board if g.state.entities[i].card_id == LIFE)
        g.apply(Attack(1, life, g.state.players[2].board[0]))
        self.assertEqual(len(self.programs(g)), 1)
        self.assertEqual(hp(g), 100)
        self.portable(g)

    def test_18_removal_reaction_wait_sees_entire_committed_health_batch(self):
        g = game(hand=(P+'batch',), board=(CARD, FILL), wait=True)
        use(g)
        play(g, P+'batch')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(g.state.damage_history), 3)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 3)
        self.assertFalse(self.programs(g))
        self.portable(g, True)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            select(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        reader = Game.from_snapshot(saved, registry('reader', True))
        select(g)
        select(reader)
        self.assertEqual(g.snapshot(), reader.snapshot())
        self.portable(g, True)

    def test_19_reaction_failure_rolls_back_original_program_and_health(self):
        g = game(hand=(P+'failheal',))
        use(g)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'original health reaction failure'):
            play(g, P+'failheal')
        self.assertEqual(g.snapshot(), saved)
        self.assertEqual(len(self.programs(g)), 1)
        self.portable(g)

    def test_20_finite_declaration_wrong_source_and_old_schema_fail_explicitly(self):
        spec = registry().player_effect(PROGRAM)
        for kw in (dict(spell_damage=1), dict(duration=1), dict(next_turn_end=True)):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                replace(spec, **kw)
        g = game(hand=(P+'wrong',))
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            play(g, P+'wrong')
        self.assertEqual(g.snapshot(), saved)
        saved['schema_version'] = 384
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, registry('reader'))
