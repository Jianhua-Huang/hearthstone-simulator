"""P04 actual branch domains, Dark Gifts, positive damage and named Stingers."""
from dataclasses import asdict, replace
import json
import re
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_fixed_p04_cards import (
    COGHAMMER, NIGHTMARES, SLEEP, HORROR, WASP, INFESTATION,
    BURST, POWER, FIGURE, WITS_END, TERROR, STINGER, GRUB,
    ROOTS, DEPENDENCIES, CHOICE_ONLY, load_batch, register_simple_fixed_p04_cards,
)
from hs_sim.engine import (
    Attack, CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice,
    TargetSpec, TriggerSpec, Zone,
)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.dark_gifts import GrantDarkGift, public_gifts
from hs_sim.engine.effects import (
    AddToHand, ChangeControl, ChoiceOption, Damage, DamageBatch, GrantKeyword,
    Heal, InvokeBehavior, RequestChoice, ReturnToHand, Silence,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

TEST = 'p04.test.'
YETI = 'CORE_CS2_182'
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())


def registry():
    r = build_registry()
    present = tuple(cid in r.cards for cid in ROOTS + DEPENDENCIES)
    if any(present) and not all(present):
        raise AssertionError('Partial P04 registration is not accepted')
    if not all(present):
        register_simple_fixed_p04_cards(r)

    def gift(c, p=None, zone='hand', cid=YETI):
        player = c.player_id if p is None else p
        e = next(c.state.entities[i] for i in getattr(c.state.players[player], zone) if c.state.entities[i].card_id == cid)
        return (GrantDarkGift(CardReference.capture(e), 'EDR_100t6', c.source_id),)

    def wait(c, extra=()):
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', ()),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(TEST+'fail', c.source_id, c.player_id),)),
            *extra,
        ), source_id=c.source_id),)

    def summon_watch(c):
        if c.state.entities[c.event.target_id].card_id != TERROR:
            return ()
        enemy = next((c.state.entities[i] for i in c.state.players[2].board if c.state.entities[i].card_id == YETI), None)
        extra = () if enemy is None else (ChoiceOption('replace', 'Bounce original and summon new enemy', (
            ReturnToHand(enemy.id), SummonByCard(2, (SummonEntryMaterial(YETI),), SummonCause.capture(c)),
        )),)
        return wait(c, extra)

    def damage_watch(c):
        target = c.state.entities.get(c.event.target_id)
        return wait(c) if target is not None and target.card_id == WASP else ()

    def created_watch(c):
        target = c.state.entities.get(c.event.target_id)
        return wait(c) if target is not None and target.card_id == STINGER else ()

    scripts = {
        'ping': lambda c: (Damage(c.target_id, 1, c.source_id),),
        'hit2': lambda c: (Damage(c.target_id, 2, c.source_id),),
        'lethal': lambda c: (Damage(c.target_id, 30, c.source_id),),
        'zero': lambda c: (Damage(c.target_id, 0, c.source_id),),
        'pair': lambda c: (DamageBatch((Damage(c.target_id, 1, c.source_id), Damage(c.target_id, 1, c.source_id))),),
        'heal': lambda c: (Heal(c.target_id, 20, c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'control': lambda c: (ChangeControl(c.target_id, 2),),
        'shield': lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),),
        'immune': lambda c: (GrantKeyword(c.target_id, Keyword.IMMUNE, c.source_id),),
        'gift': gift,
        'gift_self': lambda c: gift(c, cid=HORROR),
        'gift_enemy': lambda c: gift(c, p=2),
        'gift_deck': lambda c: gift(c, zone='deck'),
        'wound_hero': lambda c: (Damage(c.state.players[2].hero_id, 28, c.source_id),),
    }
    targeted = {'ping', 'hit2', 'lethal', 'zero', 'pair', 'heal', 'silence', 'control', 'shield', 'immune'}
    for name, body in scripts.items():
        key = TEST+name
        r.register_behavior(key, body)
        r.register_card(CardDefinition(key, name, CardType.SPELL, on_play=key, metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)) if name in targeted else None))
    r.register_behavior(TEST+'fail', lambda c: (AddToHand(c.player_id, 'p04.missing'),))
    for name, event, body in (('summon_watch', 'minion_summoned', summon_watch),
                              ('damage_watch', 'damage_dealt', damage_watch),
                              ('created_watch', 'card_added_to_hand', created_watch)):
        key = TEST+name
        r.register_behavior(key, body)
        r.register_card(CardDefinition(key, name, CardType.MINION, health=10, metadata=META,
                                       triggers=(TriggerSpec(event, key),)))
    r.register_behavior(TEST+'death_wait', lambda c: wait(c))
    r.register_card(CardDefinition(TEST+'tiny', 'Death waiting fixture', CardType.MINION, health=1,
                                   deathrattle=TEST+'death_wait', metadata=META))
    r.register_card(CardDefinition(TEST+'bonus', 'Spell damage', CardType.MINION, health=8, spell_damage=1, metadata=META))
    r.register_card(CardDefinition(TEST+'both', 'Existing ordinary Choose Both', CardType.MINION, health=8, choose_both=True, metadata=META))
    r.register_card(CardDefinition(TEST+'charge', 'Printed Charge without Dark Gift', CardType.MINION, cost=4, attack=4, health=5,
                                   keywords=(Keyword.CHARGE,), metadata=META))
    r.register_card(CardDefinition(TEST+'dormant', 'Dormant fixture', CardType.MINION, health=5, dormant_turns=2, metadata=META))
    r.validate()
    return r


class SimpleFixedP04CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = registry()

    def game(self, hand=(), board=(), enemy=(), *, enemy_hand=(), deck=(YETI,)*8, hand_cap=None, active=1, seed=404):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=deck, hand_cap=hand_cap,
                        mana=40, max_mana=40, mana_cap=40, hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(YETI,)*8,
                        mana=40, max_mana=40, mana_cap=40, hero_power_card_id='HERO_08bp'),
        ), active_player=active, seed=seed), self.r)

    def entities(self, g, cid, p=1, zone='board'):
        return [g.state.entities[i] for i in getattr(g.state.players[p], zone) if g.state.entities[i].card_id == cid]

    def first(self, g, cid, p=1, zone='board'):
        return self.entities(g, cid, p, zone)[0]

    def play(self, g, cid, target=None, branch=None):
        p = g.state.active_player
        source = self.first(g, cid, p, 'hand').id
        g.apply(PlayCard(p, source, target, len(g.state.players[p].board) if self.r.card(cid).kind == CardType.MINION else None,
                         branch_id=branch))
        return source

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def drain(self, g):
        while g.state.pending_choice is not None:
            self.choose(g)

    def hero(self, g, p=1):
        return g.state.entities[g.state.players[p].hero_id]

    def cost(self, g, e):
        return quote_unselected_cost(g.state, self.r, e).amount

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry())
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe()) + json.dumps(g.for_player(p).legal_actions()) + json.dumps(g.player_events(p))
            for hidden in ('rng_state', 'resolution_frame', 'CardReference', 'MinionReference', 'SummonEntryMaterial', 'behavior_id'):
                self.assertNotIn(hidden, public)
        return other

    def test_complete_raw_pins_official_faces_options_and_existing_grub(self):
        d = load_batch()
        self.assertEqual(tuple(x['record']['id'] for x in d['cards']), ROOTS)
        self.assertEqual(tuple(x['record']['id'] for x in d['dependencies']), DEPENDENCIES)
        self.assertEqual(len(d['official_observations']['observations']), 26)
        self.assertFalse(d['cn_calibrated'])
        self.assertFalse(d['formal_pool_complete'])
        def normalize(text):
            return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]', '', text)
        for group in ('cards', 'dependencies', 'existing_dependencies', 'skipped', 'evidence_only'):
            for row in d[group]:
                raw = row['record']
                self.assertEqual(canonical_digest(raw), row['record_sha256'])
                for obs in (o for o in d['official_observations']['observations'] if o['card_id'] == raw['id']):
                    face = obs['face']
                    en = obs['locale'] == 'en-us'
                    self.assertEqual(face['name'], raw['name_en' if en else 'name'])
                    self.assertEqual(normalize(face['text']), normalize(raw['text_en' if en else 'text']))
                    for key, value in (('id', raw['dbf_id']), ('manaCost', raw['cost']), ('cardSetId', raw['card_set_id']),
                                       ('classId', raw['tags']['CLASS']), ('cardTypeId', raw['tags']['CARDTYPE'])):
                        self.assertEqual(face[key], value)
        for row in d['cards']+d['dependencies']:
            raw = row['record']; card = self.r.card(raw['id'])
            self.assertEqual(card.metadata, replace(metadata_from_record(raw), deck_identity=card.id))
            self.assertEqual(card.cost, 0 if card.choice_only else raw['cost'])
            self.assertEqual((card.attack, card.health), (raw['attack'] or 0, raw['health'] or 0))
        existing, = d['existing_dependencies']
        self.assertEqual(canonical_digest(asdict(self.r.card(GRUB))), existing['definition_sha256'])
        self.assertEqual(self.r.card(TERROR).metadata.tribes, ('demon',))
        self.assertEqual(self.r.card(GRUB).metadata.tribes, ('beast',))
        for cid in CHOICE_ONLY:
            self.assertTrue(self.r.card(cid).choice_only)
            self.assertFalse(self.r.card(cid).hand_playable)
            self.assertNotIn(cid, self.r.pool_cards)

    def test_coghammer_whole_root_skipped_with_full_current_and_historical_identity(self):
        d = load_batch(); row, = d['skipped']; old, = d['evidence_only']
        self.assertEqual(row['record']['id'], COGHAMMER)
        self.assertEqual(row['record']['tags']['858'], old['record']['dbf_id'])
        self.assertNotIn(COGHAMMER, ROOTS+DEPENDENCIES)
        self.assertIn('random target keyword', row['reason'])

    def test_nightmares_burst_hits_all_active_minions_as_one_spell_batch_not_heroes(self):
        g = self.game((NIGHTMARES,), (YETI, TEST+'bonus'), (YETI, TEST+'dormant'))
        source = self.play(g, NIGHTMARES, branch=BURST)
        self.assertEqual(self.first(g, YETI).health, 3)
        self.assertEqual(self.first(g, YETI, 2).health, 3)
        self.assertEqual(self.first(g, TEST+'dormant', 2).health, 5)
        self.assertEqual((self.hero(g).health, self.hero(g, 2).health), (30, 30))
        self.assertEqual([e.amount for e in g.events if e.kind == 'damage_dealt' and e.source_id == source], [2, 2, 2])
        self.assertEqual(g.state.players[1].mana, 39)

    def test_nightmares_damaged_branch_rejects_healthy_and_hero_targets_before_payment(self):
        g = self.game((NIGHTMARES,), (YETI,), (YETI,))
        source = self.first(g, NIGHTMARES, zone='hand').id
        self.assertFalse(g.legal_targets(source, branch_id=POWER))
        for target in (self.first(g, YETI).id, self.hero(g).id):
            saved = g.snapshot()
            with self.assertRaises(IllegalAction):
                self.play(g, NIGHTMARES, target, POWER)
            self.assertEqual(g.snapshot(), saved)
        self.play(g, NIGHTMARES, branch=BURST)

    def test_nightmares_targeted_buff_allows_actual_damaged_friendly_or_enemy(self):
        for p in (1, 2):
            g = self.game((TEST+'ping', NIGHTMARES), (YETI,), (YETI,))
            target = self.first(g, YETI, p).id
            self.play(g, TEST+'ping', target)
            self.play(g, NIGHTMARES, target, POWER)
            self.assertEqual((g.state.entities[target].attack, g.state.entities[target].health), (6, 6))
            self.assertEqual(g.state.cast_history[-1].branch_id, POWER)

    def test_nightmares_target_returns_to_healthy_state_and_is_no_longer_legal(self):
        g = self.game((TEST+'ping', TEST+'heal', NIGHTMARES), (YETI,))
        target = self.first(g, YETI).id
        self.play(g, TEST+'ping', target)
        source = self.first(g, NIGHTMARES, zone='hand').id
        self.assertIn(target, g.legal_targets(source, branch_id=POWER))
        self.play(g, TEST+'heal', target)
        self.assertNotIn(target, g.legal_targets(source, branch_id=POWER))

    def test_nightmares_burst_does_not_inherit_other_branch_target_requirement(self):
        g = self.game((NIGHTMARES,))
        self.play(g, NIGHTMARES, branch=BURST)
        self.assertEqual(g.state.players[1].mana, 39)
        self.assertIsNone(g.state.pending_choice)

    def test_sleep_summons_two_full_demon_taunts_that_cannot_attack(self):
        g = self.game((SLEEP,), enemy=(YETI,))
        self.play(g, SLEEP, branch=FIGURE)
        demons = self.entities(g, TERROR)
        self.assertEqual(len(demons), 2)
        self.assertTrue(all((e.attack, e.health, e.keywords) == (3, 6, frozenset((Keyword.TAUNT,))) for e in demons))
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        saved = g.snapshot()
        with self.assertRaises(IllegalAction):
            g.apply(Attack(1, demons[0].id, self.first(g, YETI, 2).id))
        self.assertEqual(g.snapshot(), saved)

    def test_sleep_demon_silence_removes_both_restriction_and_taunt(self):
        g = self.game((TEST+'silence',), (TERROR,))
        target = self.first(g, TERROR).id
        self.play(g, TEST+'silence', target)
        g.apply(Attack(1, target, self.hero(g, 2).id))
        self.assertEqual(self.hero(g, 2).health, 27)
        self.assertNotIn(Keyword.TAUNT, g.state.entities[target].keywords)

    def test_sleep_destruction_requires_enemy_minion_and_does_not_summon(self):
        g = self.game((SLEEP,), (YETI,), (YETI,))
        for target in (self.first(g, YETI).id, self.hero(g, 2).id):
            saved = g.snapshot()
            with self.assertRaises(IllegalAction):
                self.play(g, SLEEP, target, WITS_END)
            self.assertEqual(g.snapshot(), saved)
        target = self.first(g, YETI, 2).id
        self.play(g, SLEEP, target, WITS_END)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertFalse(self.entities(g, TERROR))

    def test_sleep_capacity_caps_summons_without_blocking_other_branch(self):
        for count, expected in ((6, 1), (7, 0)):
            g = self.game((SLEEP,), (YETI,)*count)
            self.play(g, SLEEP, branch=FIGURE)
            self.assertEqual(len(self.entities(g, TERROR)), expected)
            self.assertEqual(g.state.players[1].mana, 35)

    def test_native_required_combined_bodies_use_existing_order_and_one_payment(self):
        g = self.game((TEST+'ping', NIGHTMARES), (TEST+'both', YETI))
        target = self.first(g, YETI).id
        self.play(g, TEST+'ping', target)
        self.play(g, NIGHTMARES, target, NIGHTMARES+':combined')
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].health), (6, 5))
        self.assertEqual(g.state.players[1].mana, 39)
        h = self.game((SLEEP,), (TEST+'both',), (YETI,))
        self.play(h, SLEEP, self.first(h, YETI, 2).id, SLEEP+':combined')
        self.assertEqual(len(self.entities(h, TERROR)), 2)
        self.assertFalse(h.state.players[2].board)
        self.assertEqual(h.state.players[1].mana, 35)

    def test_sleep_combined_wait_restores_original_target_and_does_not_destroy_replacement(self):
        g = self.game((SLEEP,), (TEST+'both', TEST+'summon_watch'), (YETI,))
        old = self.first(g, YETI, 2).id
        self.play(g, SLEEP, old, SLEEP+':combined')
        other = self.portable(g)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g, 'replace'); self.choose(other, 'replace')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.drain(g)
        self.assertEqual(g.state.entities[old].zone, Zone.HAND)
        self.assertNotEqual(self.first(g, YETI, 2).id, old)
        self.assertEqual(len(self.entities(g, TERROR)), 2)
        self.portable(g)

    def test_horror_only_actual_dark_gift_held_minions_get_two_cost_discount(self):
        g = self.game((TEST+'gift', HORROR, YETI, TEST+'charge'), enemy_hand=(YETI,))
        self.play(g, TEST+'gift')
        original = self.first(g, YETI, zone='hand').id
        self.assertTrue(public_gifts(g.state.entities[original]))
        self.play(g, HORROR)
        self.assertEqual(self.cost(g, g.state.entities[original]), 2)
        self.assertEqual(self.cost(g, self.first(g, TEST+'charge', zone='hand')), 4)
        self.assertEqual(self.cost(g, self.first(g, YETI, 2, 'hand')), 4)
        self.assertIn(Keyword.TAUNT, self.first(g, HORROR).keywords)

    def test_horror_enemy_and_deck_actual_gifts_do_not_receive_hand_reward(self):
        g = self.game((TEST+'gift_enemy', TEST+'gift_deck', HORROR), enemy_hand=(YETI,))
        self.play(g, TEST+'gift_enemy'); self.play(g, TEST+'gift_deck')
        enemy = self.first(g, YETI, 2, 'hand').id
        deck = self.first(g, YETI, zone='deck').id
        self.assertTrue(public_gifts(g.state.entities[enemy])); self.assertTrue(public_gifts(g.state.entities[deck]))
        self.play(g, HORROR)
        self.assertEqual((self.cost(g, g.state.entities[enemy]), self.cost(g, g.state.entities[deck])), (4, 4))

    def test_horror_itself_has_left_hand_before_its_dark_gift_condition(self):
        g = self.game((TEST+'gift_self', HORROR))
        self.play(g, TEST+'gift_self')
        source = self.play(g, HORROR)
        self.assertTrue(public_gifts(g.state.entities[source]))
        self.assertFalse(any(e.kind == 'cost_modified' and e.target_id == source for e in g.events))

    def test_horror_multiple_battlecries_stack_and_shared_cost_floor_is_zero(self):
        g = self.game((TEST+'gift', HORROR, HORROR, HORROR, YETI))
        self.play(g, TEST+'gift')
        target = self.first(g, YETI, zone='hand').id
        for expected in (2, 0, 0):
            self.play(g, HORROR)
            self.assertEqual(self.cost(g, g.state.entities[target]), expected)
        self.portable(g)

    def test_wasp_positive_damage_gives_one_full_stinger_independent_of_amount(self):
        g = self.game((TEST+'hit2',), (WASP,))
        target = self.first(g, WASP).id
        self.play(g, TEST+'hit2', target)
        self.assertEqual(g.state.entities[target].health, 5)
        self.assertEqual(len(self.entities(g, STINGER, zone='hand')), 1)
        self.assertEqual(self.cost(g, self.first(g, STINGER, zone='hand')), 1)
        self.assertIn(Keyword.RUSH, g.state.entities[target].keywords)

    def test_wasp_each_actual_damage_packet_gets_its_own_stinger(self):
        g = self.game((TEST+'pair',), (WASP,))
        self.play(g, TEST+'pair', self.first(g, WASP).id)
        self.assertEqual(len(self.entities(g, STINGER, zone='hand')), 2)

    def test_wasp_lethal_damage_still_gets_stinger_from_original_notification(self):
        g = self.game((TEST+'lethal',), (WASP,))
        target = self.first(g, WASP).id
        self.play(g, TEST+'lethal', target)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual(len(self.entities(g, STINGER, zone='hand')), 1)
        self.portable(g)

    def test_wasp_zero_prevention_heal_and_other_target_do_not_reward(self):
        for action in ('zero', 'heal', 'shield', 'immune'):
            g = self.game((TEST+action, TEST+'ping'), (WASP, YETI))
            target = self.first(g, WASP).id
            self.play(g, TEST+action, target)
            self.play(g, TEST+'ping', target if action in ('shield', 'immune') else self.first(g, YETI).id)
            self.assertFalse(self.entities(g, STINGER, zone='hand'))

    def test_wasp_silence_removes_native_damage_reward(self):
        g = self.game((TEST+'silence', TEST+'ping'), (WASP,))
        target = self.first(g, WASP).id
        self.play(g, TEST+'silence', target); self.play(g, TEST+'ping', target)
        self.assertFalse(self.entities(g, STINGER, zone='hand'))

    def test_wasp_control_change_rewards_its_current_controller(self):
        g = self.game((TEST+'control', TEST+'ping'), (WASP,))
        target = self.first(g, WASP).id
        self.play(g, TEST+'control', target); self.play(g, TEST+'ping', target)
        self.assertFalse(self.entities(g, STINGER, zone='hand'))
        self.assertEqual(len(self.entities(g, STINGER, 2, 'hand')), 1)

    def test_wasp_full_hand_uses_ordinary_created_card_burn(self):
        g = self.game((YETI, YETI), (WASP,), enemy_hand=(TEST+'ping',), hand_cap=2, active=2)
        self.play(g, TEST+'ping', self.first(g, WASP).id)
        self.assertFalse(self.entities(g, STINGER, zone='hand'))
        self.assertEqual(len(self.entities(g, STINGER, zone='graveyard')), 1)

    def test_wasp_waiting_damage_restores_and_failed_choice_does_not_duplicate_reward(self):
        g = self.game((TEST+'ping',), (TEST+'damage_watch', WASP))
        self.play(g, TEST+'ping', self.first(g, WASP).id)
        other = self.portable(g)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(self.entities(g, STINGER, zone='hand')), 1)

    def test_infestation_gets_two_identical_complete_stingers_without_drawing(self):
        g = self.game((INFESTATION,))
        self.play(g, INFESTATION)
        cards = self.entities(g, STINGER, zone='hand')
        self.assertEqual(len(cards), 2)
        self.assertNotEqual(cards[0].id, cards[1].id)
        self.assertTrue(all(self.cost(g, e) == 1 for e in cards))
        self.assertFalse(g.state.draw_history)
        self.assertEqual(g.state.players[1].mana, 38)

    def test_infestation_overflow_does_not_drop_second_creation_or_relabel_it_draw(self):
        g = self.game((INFESTATION,), hand_cap=1)
        self.play(g, INFESTATION)
        self.assertEqual(len(self.entities(g, STINGER, zone='hand')), 1)
        self.assertEqual(len(self.entities(g, STINGER, zone='graveyard')), 1)
        self.assertFalse(g.state.draw_history)

    def test_infestation_first_created_card_wait_preserves_second_card_and_player_boundary(self):
        g = self.game((INFESTATION,), (TEST+'created_watch',))
        self.play(g, INFESTATION)
        other = self.portable(g)
        self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(self.entities(g, STINGER, zone='hand')), 2)
        self.choose(g)
        self.assertNotIn(STINGER, json.dumps(g.for_player(2).observe()))

    def test_stinger_is_two_spell_damage_plus_exact_existing_attributed_rush_grub(self):
        g = self.game((STINGER,), (TEST+'bonus',), (YETI,))
        source = self.play(g, STINGER, self.first(g, YETI, 2).id)
        self.assertEqual(self.first(g, YETI, 2).health, 2)
        grub = self.first(g, GRUB)
        self.assertEqual((grub.attack, grub.health, grub.keywords), (2, 1, frozenset((Keyword.RUSH,))))
        row = g.state.card_summon_history[-1]
        self.assertEqual((row.request.cause.source.entity_id, row.request.cause.cast_id), (source, g.state.cast_history[-1].id))
        self.assertEqual(g.state.players[1].mana, 39)

    def test_stinger_can_target_own_wasp_and_trigger_its_real_replacement_stinger(self):
        g = self.game((STINGER,), (WASP,))
        self.play(g, STINGER, self.first(g, WASP).id)
        self.assertEqual(self.first(g, WASP).health, 5)
        self.assertEqual(len(self.entities(g, STINGER, zone='hand')), 1)
        self.assertEqual(len(self.entities(g, GRUB)), 1)

    def test_stinger_death_choice_wait_restores_before_later_summon(self):
        g = self.game((STINGER,), enemy=(TEST+'tiny',))
        self.play(g, STINGER, self.first(g, TEST+'tiny', 2).id)
        self.assertFalse(self.entities(g, GRUB))
        other = self.portable(g)
        self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(self.entities(g, GRUB)), 1)

    def test_stinger_full_board_still_deals_damage_and_terminal_damage_stops_summon(self):
        g = self.game((STINGER,), (YETI,)*7)
        self.play(g, STINGER, self.hero(g, 2).id)
        self.assertEqual(self.hero(g, 2).health, 28)
        self.assertFalse(self.entities(g, GRUB))
        h = self.game((TEST+'wound_hero', STINGER))
        self.play(h, TEST+'wound_hero')
        self.play(h, STINGER, self.hero(h, 2).id)
        self.assertEqual(h.state.winner, 1)
        self.assertFalse(self.entities(h, GRUB))


if __name__ == '__main__':
    unittest.main()
