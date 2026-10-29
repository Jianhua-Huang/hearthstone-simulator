"""Actual legacy champion entries, original operands and pinned source controls."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.cards import legacy_champion_dependencies as native
from hs_sim.cards.constructed import build_registry
from hs_sim.engine import Attack, Game, PlayerSetup, ResolutionError, Scenario
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, Destroy, Draw,
    GainArmor, Heal, InvokeBehavior, RandomDamage, RequestChoice, Silence)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, HealingKind, Keyword, TriggerSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.zones import AddToDeck, CardReference, MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

TIRION, ANTONIDAS, GROM, CAIRNE, SYLVANAS, LORTHEMAR = native.CARDS
P = 'k655.'
KILL, HIT, HEAL, QUIET, SILENCE, DRAW, GROW, WATCH, FAIL, HIDDEN, DORMANT, LOCATION = (
    P + s for s in ('kill', 'hit', 'heal', 'quiet', 'silence', 'draw', 'grow', 'watch', 'fail', 'hidden', 'dormant', 'location'))


@lru_cache(maxsize=None)
def source(role='writer'):
    return build_registry()


@lru_cache(maxsize=None)
def host(role='writer'):
    return build_cn37_local_pool_format()


@lru_cache(maxsize=None)
def registry(mode='normal', role='writer'):
    r = opening_registry(); original = source(role)
    for cid in (*native.REUSED.values(), 'EX1_383t', 'EX1_110t', 'CS2_029'):
        card = original.card(cid)
        r.register_card(card); r.register_pool_card(original.pool_card(cid))
        try:
            r.target_rule(card.target_rule)
        except UnsupportedDefinitionError:
            r.register_target_rule(card.target_rule, original.target_rule(card.target_rule),
                visibility=original.target_visibility(card.target_rule))
        names = {card.on_play, card.battlecry, card.deathrattle, card.on_use,
            *(t.behavior_id for t in card.triggers)} - {None}
        for name in names:
            if name not in r._behaviors:
                r.register_behavior(name, original.behavior(name))
    if mode == 'bare':
        return r
    native.register_legacy_champion_dependencies(r)

    def fail(c):
        raise ValueError('K655 deliberate rollback after actual native work')

    def grow(c):
        ref = CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]])
        return (BuffStoredCard(ref, 3, 2, c.source_id),)

    def wait(c):
        if mode == 'control_fail' and c.event.kind == 'control_changed':
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        if mode == 'move_deck':
            if c.event.kind != 'stored_card_buffed' or c.state.entities[c.event.target_id].card_id != 'card.1':
                return ()
            target = next(i for i in c.state.players[1].deck if c.state.entities[i].card_id == 'card.2')
            return (MoveCard(CardReference.capture(c.state.entities[target]), 1, Zone.HAND, source_id=c.source_id),
                AddToDeck(1, 'card.3', source_id=c.source_id))
        accepted = (mode == 'deck_wait' and c.event.kind == 'stored_card_buffed' or
            mode == 'death_wait' and c.event.kind == 'minion_died' and
            c.state.entities[c.event.source_id].card_id == SYLVANAS)
        if not accepted:
            return ()
        return (RequestChoice(1, (ChoiceOption('continue', 'Continue'), ChoiceOption('fail', 'Fail', (
            RandomDamage((c.state.players[2].hero_id,), 1, c.source_id), InvokeBehavior(FAIL, c.source_id, 1)))),
            c.source_id, prompt='Original champion notification'),)

    bodies = {KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        HIT: lambda c: (Damage(c.target_id, 1, c.source_id, DamageKind.SPELL),),
        HEAL: lambda c: (Heal(c.target_id, 20, c.source_id, HealingKind.SPELL),),
        QUIET: lambda c: (GainArmor(c.player_id, 1),), SILENCE: lambda c: (Silence(c.target_id),),
        DRAW: lambda c: (Draw(c.player_id, source_id=c.source_id),), GROW: grow, WATCH: wait, FAIL: fail}
    for name, body in bodies.items():
        r.register_behavior(name, body)
    for cid in (KILL, HIT, HEAL, QUIET, SILENCE, DRAW, GROW):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            requires_target=cid in (KILL, HIT, HEAL, SILENCE), metadata=metadata()))
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=30, metadata=metadata(),
        triggers=tuple(TriggerSpec(event, WATCH) for event in ('stored_card_buffed', 'minion_died', 'control_changed'))))
    r.register_card(CardDefinition(HIDDEN, HIDDEN, CardType.MINION, attack=2, health=3,
        keywords=(Keyword.STEALTH, Keyword.ELUSIVE), metadata=metadata()))
    r.register_card(CardDefinition(DORMANT, DORMANT, CardType.MINION, health=3, dormant_turns=2, metadata=metadata()))
    r.register_card(CardDefinition(LOCATION, LOCATION, CardType.LOCATION, durability=2, on_use=QUIET, metadata=metadata()))
    return r


class LegacyChampionDependenciesTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(registry)

    def game(self, *, hand=(), board=(), enemy=(), deck=('card.40',) * 6, mode='normal', weapon=None):
        self.mode = mode
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero', hand=hand,
            board=board, deck=deck, mana=60, max_mana=60, mana_cap=60, weapon_card_id=weapon),
            PlayerSetup('warrior.hero', board=enemy, deck=('card.39',) * 6)), seed=655), registry(mode))

    def check_private(self, g):
        for output in (g.for_player(2).observe(), g.player_events(2)):
            text = json.dumps(output, default=str)
            for value in ('card.1', 'card.2', 'rng_state', 'resolution_frame', 'zone_epoch', 'hand_entry_id'):
                self.assertNotIn(value, text)

    def test_complete_raw_faces_metadata_and_original_core_definitions_are_preserved(self):
        d = native.load_batch(); r = registry(); original = source()
        self.assertEqual(len(d['cards']), 6); self.assertEqual(len(d['official_observations']), 12)
        for row in d['cards']:
            cid = row['record']['id']; card = r.card(cid)
            self.assertEqual(batch.canonical(asdict(card)), row['definition_sha256'])
            self.assertEqual(card.id, cid); self.assertEqual(card.metadata.deck_identity, cid)
            if cid in native.REUSED:
                self.assertEqual(r.card(native.REUSED[cid]), original.card(native.REUSED[cid]))
                self.assertEqual(replace(card, id=native.REUSED[cid], metadata=original.card(native.REUSED[cid]).metadata,
                    deathrattle=original.card(native.REUSED[cid]).deathrattle),
                    original.card(native.REUSED[cid]))
        self.assertEqual(set(r.card(TIRION).keywords), {Keyword.TAUNT, Keyword.DIVINE_SHIELD})
        self.assertEqual(r.card(CAIRNE).keywords, (Keyword.TAUNT,))
        self.assertEqual(r.card(GROM).keywords, (Keyword.CHARGE,))
        self.assertEqual(r.card(GROM).stat_relations[0].amount, 6)
        self.assertEqual(r.card(ANTONIDAS).triggers[0].event, 'spell_cast_started')
        self.assertIn('undead', r.card(SYLVANAS).metadata.tribes)

    def test_real_local_host_plays_six_exact_legacy_faces_with_complete_source_available(self):
        f = host(); g = Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=native.CARDS,
            mana=60, max_mana=60, mana_cap=60), PlayerSetup('HERO_08')), seed=655,
            generation_context=f.context), f.registry)
        for cid in native.CARDS:
            self.play(g, cid)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], list(native.CARDS))
        self.assertEqual(g.state.players[1].mana, 18)
        self.assertTrue(set(native.CARDS).isdisjoint(f.root_card_ids))
        for dependency in ('WON_113', 'AT_072', 'BAR_080'):
            self.assertIn(dependency, f.registry.cards)

    def test_tirion_shield_and_real_death_equip_exact_ashbringer_replacing_old_weapon(self):
        g = self.game(hand=(TIRION, HIT, KILL), weapon='EX1_383t')
        old_weapon = g.state.players[1].weapon_id; target = self.play(g, TIRION)
        self.play(g, HIT, target)
        self.assertEqual(g.state.entities[target].health, 8)
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[target].keywords)
        self.play(g, KILL, target)
        weapon = g.state.entities[g.state.players[1].weapon_id]
        self.assertEqual((weapon.card_id, weapon.attack, weapon.durability), ('EX1_383t', 5, 3))
        self.assertNotEqual(weapon.id, old_weapon); self.assertEqual(g.state.entities[old_weapon].zone, Zone.GRAVEYARD)

    def test_cairne_real_death_summons_fresh_baine_in_original_death_slot(self):
        g = self.game(hand=(KILL,), board=('card.1', CAIRNE, 'card.2'))
        target = self.entity(g, CAIRNE, zone='board').id; self.play(g, KILL, target)
        ids = g.state.players[1].board; body = g.state.entities[ids[1]]
        self.assertEqual([g.state.entities[i].card_id for i in ids], ['card.1', 'EX1_110t', 'card.2'])
        self.assertEqual((body.attack, body.health), (5, 5)); self.assertNotEqual(body.id, target)
        self.portable(g)

    def test_antonidas_original_cast_start_gives_fireball_and_generated_fireball_is_playable(self):
        g = self.game(hand=(QUIET,), board=(ANTONIDAS,))
        self.play(g, QUIET)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], ['CS2_029'])
        self.play(g, 'CS2_029', g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 24)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], ['CS2_029'])
        self.assertEqual(len(g.state.play_history), 2)

    def test_grom_charge_is_real_and_damage_heal_silence_use_live_attack_condition(self):
        g = self.game(hand=(GROM, HIT, HEAL, HIT, SILENCE))
        target = self.play(g, GROM); enemy_hero = g.state.players[2].hero_id
        g.apply(Attack(1, target, enemy_hero)); self.assertEqual(g.state.entities[enemy_hero].health, 26)
        self.play(g, HIT, target); self.assertEqual(g.state.entities[target].attack, 10)
        self.play(g, HEAL, target); self.assertEqual(g.state.entities[target].attack, 4)
        self.play(g, HIT, target); self.assertEqual(g.state.entities[target].attack, 10)
        self.play(g, SILENCE, target); self.assertEqual(g.state.entities[target].attack, 4)
        self.assertNotIn(Keyword.CHARGE, g.state.entities[target].keywords)

    def test_sylvanas_untargeted_control_includes_hidden_enemy_excludes_dormant_and_location(self):
        g = self.game(hand=(KILL,), board=(SYLVANAS,), enemy=(HIDDEN, DORMANT, LOCATION))
        original = self.entity(g, HIDDEN, player=2, zone='board').id
        self.play(g, KILL, self.entity(g, SYLVANAS, zone='board').id)
        self.assertIn(original, g.state.players[1].board); self.assertEqual(g.state.entities[original].controller, 1)
        self.assertEqual(len(g.state.players[2].board), 2); self.assertIsNone(g.state.pending_choice)
        self.portable(g)

    def test_sylvanas_empty_enemy_does_not_consume_randomness_or_create_a_choice(self):
        g = self.game(hand=(KILL,), board=(SYLVANAS,))
        rng = g._rng.getstate(); self.play(g, KILL, self.entity(g, SYLVANAS, zone='board').id)
        self.assertEqual(g._rng.getstate(), rng); self.assertFalse(g.state.players[1].board)
        self.assertIsNone(g.state.pending_choice)

    def test_sylvanas_wait_before_random_body_restores_and_replays_original_death(self):
        g = self.game(hand=(KILL,), board=(SYLVANAS, WATCH), enemy=('card.4', 'card.5'), mode='death_wait')
        self.play(g, KILL, self.entity(g, SYLVANAS, zone='board').id)
        self.assertIsNotNone(g.state.pending_choice); restored = self.portable(g)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)
        self.assertEqual(len(g.state.players[1].board), 2)

    def test_sylvanas_exception_after_actual_random_control_rolls_back_payment_death_and_rng(self):
        g = self.game(hand=(KILL,), board=(SYLVANAS, WATCH), enemy=('card.4', 'card.5'), mode='control_fail')
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K655 deliberate rollback after actual native work'):
            self.play(g, KILL, self.entity(g, SYLVANAS, zone='board').id)
        self.assertEqual(g.snapshot(), saved)

    def test_lorthemar_doubles_current_deck_operands_each_time_and_retains_physical_cards(self):
        g = self.game(hand=(GROW, LORTHEMAR, LORTHEMAR, DRAW), deck=('card.1', QUIET, 'card.2', 'EX1_383t'))
        original = tuple(g.state.players[1].deck); self.play(g, GROW); self.play(g, LORTHEMAR)
        a, spell, b, weapon = (g.state.entities[i] for i in original)
        self.assertEqual((a.attack, a.health, b.attack, b.health), (14, 12, 8, 8))
        self.play(g, LORTHEMAR)
        self.assertEqual((a.id, g.state.entities[a.id].attack, g.state.entities[a.id].health), (original[0], 28, 24))
        self.assertEqual(tuple(g.state.players[1].deck), original)
        self.assertEqual(g.state.entities[weapon.id].attack, 5)
        self.play(g, DRAW)
        drawn = g.state.entities[original[0]]
        self.assertEqual((drawn.zone, drawn.attack, drawn.health), (Zone.HAND, 28, 24)); self.portable(g)
        self.check_private(g)

    def test_lorthemar_wait_after_first_attachment_restores_remaining_original_deck_work(self):
        g = self.game(hand=(LORTHEMAR,), board=(WATCH,), deck=('card.1', QUIET, 'card.2'), mode='deck_wait')
        self.play(g, LORTHEMAR); self.assertIsNotNone(g.state.pending_choice)
        restored = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        while g.state.pending_choice is not None:
            self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g); self.check_private(g)
        self.assertEqual([(g.state.entities[i].attack, g.state.entities[i].health) for i in g.state.players[1].deck
            if g.state.entities[i].kind == CardType.MINION], [(8, 8), (8, 8)])

    def test_lorthemar_does_not_buff_moved_original_or_new_deck_arrival_during_notifications(self):
        g = self.game(hand=(LORTHEMAR,), board=(WATCH,), deck=('card.1', 'card.2'), mode='move_deck')
        second = g.state.players[1].deck[1]; self.play(g, LORTHEMAR)
        self.assertIn(second, g.state.players[1].hand)
        self.assertEqual((g.state.entities[second].attack, g.state.entities[second].health), (4, 4))
        fresh = self.entity(g, 'card.3', zone='deck')
        self.assertEqual((fresh.attack, fresh.health), (4, 4)); self.portable(g)

    def test_preflight_missing_named_dependency_or_changed_core_cannot_partially_install(self):
        for mode in ('missing', 'changed'):
            r = registry('bare', mode)
            if mode == 'missing':
                del r._cards['CS2_029']
            else:
                r._cards['CORE_EX1_383'] = replace(r.card('CORE_EX1_383'), attack=9)
            old = set(r.cards)
            with self.assertRaises((TargetValidationError, UnsupportedDefinitionError)):
                native.register_legacy_champion_dependencies(r)
            self.assertEqual(set(r.cards), old); self.assertTrue(set(native.CARDS).isdisjoint(r.cards))

    def test_explicit_legacy_layout_declarations_validate_both_full_primary_bodies(self):
        d = native.load_batch(); rows = {v['record']['id']: v['record'] for v in d['cards']}
        for observation in d['official_observations']:
            cid = observation['card_id']; row = rows[cid]; face = observation['face']; loc = observation['locale']
            original = deepcopy((row, face)); decl = d['display_normalizations'].get(cid)
            batch.check_face(row, face, loc, decl); self.assertEqual((row, face), original)
            local_decl = decl.get(loc) if decl and set(decl) & {'zh_CN', 'en_US'} else decl
            if local_decl:
                with self.assertRaises(ValueError):
                    batch.check_face(row, face, loc)

    def test_legacy_layout_allowance_rejects_changed_complete_source_or_wrong_replacements(self):
        d = native.load_batch(); rows = {v['record']['id']: v['record'] for v in d['cards']}
        for o in d['official_observations']:
            cid = o['card_id']
            if cid not in d['display_normalizations'] or not d['display_normalizations'][cid].get(o['locale']):
                continue
            row = rows[cid]; decl = d['display_normalizations'][cid]
            for changed in (dict(row, id='other'), dict(row, tags=dict(row['tags'], EXTRA_UNREVIEWED_TAG=1))):
                with self.subTest(cid=cid, loc=o['locale']), self.assertRaises(ValueError):
                    batch.check_face(changed, o['face'], o['locale'], decl)
            for wrong in ({'&': ' '}, {'&': '', '_': ''}, {'&': '', '{0}': ''},
                    {'<b>圣盾</b>。<b>嘲讽</b>。': '<b>圣盾</b>，<b>嘲讽</b>。'}, {'。': '，'},
                    dict(decl['zh_CN'], **{'&': ''})):
                with self.subTest(cid=cid, loc=o['locale'], wrong=wrong), self.assertRaises(ValueError):
                    batch.check_face(row, o['face'], o['locale'], wrong)

    def test_primary_additional_rules_wrong_stats_and_types_remain_strict(self):
        d = native.load_batch(); rows = {v['record']['id']: v['record'] for v in d['cards']}
        for o in d['official_observations']:
            row = rows[o['card_id']]; decl = d['display_normalizations'].get(row['id'])
            for key, value in (('text', o['face']['text'] + ' Draw a card.'),
                    ('attack', row['attack'] + 1), ('health', row['health'] + 1), ('manaCost', row['cost'] + 1), ('cardTypeId', 5)):
                with self.subTest(cid=row['id'], loc=o['locale'], key=key), self.assertRaises(ValueError):
                    batch.check_face(row, dict(o['face'], **{key: value}), o['locale'], decl)


if __name__ == '__main__':
    unittest.main()
