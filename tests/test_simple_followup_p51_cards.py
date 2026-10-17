"""Grouped native hero, equipment and reused physical child boundaries."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import random
import unittest
from unittest.mock import patch

from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p51_cards import (
    HERO, WEAPON, POWER, INFERNAL, BODY_FORMS, PLUME, BLOOD_FORMS, RECIPES,
    ROOTS, EXISTING, PARENTS, load_batch, register_simple_followup_p51_cards)
from hs_sim.engine import (
    Attack, CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice,
    TargetSpec, UseHeroPower, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (
    Buff, ChoiceOption, Damage, Destroy, Freeze, GrantKeyword, InvokeBehavior,
    RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec, SpellSchool
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

TEST = 'p51.test.'
YETI = 'CORE_CS2_182'
FIRE = 'CORE_CS2_029'
OTHER_FIRE = 'CATA_581'
NATURE = 'CORE_CS2_009'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
CONTEXT = GenerationContext('p51-explicit-complete-fixture', 'experimental')
MEMBERS = (FIRE, OTHER_FIRE, NATURE)


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata', lambda r: None):
        r = build_registry()
    present = tuple(cid in r.cards for cid in ROOTS)
    if not any(present):
        register_simple_followup_p51_cards(r)
    elif not all(present):
        raise AssertionError('P51 assembly must contain all ten reviewed physical definitions')
    register_candidate_pool_metadata(r)
    r.validate()
    return r


def registry(mode=None, members=MEMBERS):
    r = batch_registry()
    for cid in members:
        if cid not in r.pool_cards:
            r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition('constructed.cards', 'p51-complete-explicit-v1',
        CONTEXT.target_id, CONTEXT.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    scripts = {name: (lambda c, n=n: (Damage(c.target_id, n, c.source_id),))
               for name, n in (('hit0', 0), ('hit1', 1), ('hit5', 5))}
    scripts.update(
        kill=lambda c: (Destroy(c.target_id, c.source_id),),
        silence=lambda c: (Silence(c.target_id),),
        shield=lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),),
        wound=lambda c: (Damage(c.state.players[1].hero_id, 10, c.source_id),),
        enhance=lambda c: (Buff(c.state.players[1].hero_id, health=10), Freeze(c.state.players[1].hero_id)),
        reenter=lambda c: (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),
            c.state.entities[c.target_id].controller, cause=SummonCause.capture(c)),),
        fail=lambda c: (_ for _ in ()).throw(ResolutionError('P51 deliberate continuation failure')))
    for name, body in scripts.items():
        r.register_behavior(TEST + name, body)
        targeted = name in ('hit0', 'hit1', 'hit5', 'kill', 'silence', 'shield')
        r.register_card(CardDefinition(TEST + name, name, CardType.SPELL,
            on_play=TEST + name, metadata=META, **({'targeting': TargetSpec()} if targeted else {})))
    r.register_card(CardDefinition(TEST + 'dormant', 'Physical dormant occupant', CardType.MINION,
        attack=1, health=9, dormant_turns=2, metadata=META))
    if mode:
        def eligible(c):
            if mode in ('hero', 'hero_fail'):
                return c.event.player_id == 1 and c.state.entities[c.event.target_id].card_id == WEAPON
            if mode == 'plume':
                return c.event.target_id is not None and c.state.entities[c.event.target_id].card_id == PLUME
            return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in (
                BODY_FORMS if mode == 'body' else BLOOD_FORMS)

        def watch(c):
            if mode == 'hero_fail':
                return (InvokeBehavior(TEST + 'fail', c.source_id, 1),)
            options = [ChoiceOption('ok', 'Continue', ()),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(TEST + 'fail', c.source_id, 1),))]
            if mode in ('body', 'blood'):
                target = next(i for i in c.state.players[1].board if c.state.entities[i].card_id == YETI)
                options.append(ChoiceOption('reenter', 'Return and reenter original recipient', (
                    ReturnToHand(target), InvokeBehavior(TEST + 'reenter', c.source_id, 1, target))))
            return (RequestChoice(1, tuple(options), c.source_id),)

        event = 'weapon_equipped' if mode in ('hero', 'hero_fail') else (
            'health_resolved' if mode == 'plume' else 'choice_skipped')
        r.register_behavior(TEST + 'watch', watch)
        r.register_trigger_condition(TEST + 'eligible', eligible)
        r.register_card(CardDefinition(TEST + 'watch', 'Native continuation witness',
            CardType.WEAPON if mode == 'body' else CardType.MINION, metadata=META,
            **({'durability': 5} if mode == 'body' else {'health': 20}),
            limited_triggers=(LimitedTriggerSpec(event, TEST + 'watch', condition_id=TEST + 'eligible'),)))
    r.validate()
    return r


@lru_cache(maxsize=None)
def shared_registry(mode, members):
    return registry(mode, members)


class SimpleFollowupP51Tests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), mode=None, members=MEMBERS,
             mana=30, armor=0, weapon=None, power='HERO_01bp'):
        self.config = (mode, members)
        if mode and mode != 'body':
            board = (TEST + 'watch', *board)
        if mode == 'body':
            weapon = TEST + 'watch'
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01', hand=hand, board=board,
            deck=(YETI,) * 8, mana=mana, max_mana=30, mana_cap=30, armor=armor,
            weapon_card_id=weapon, hero_power_card_id=power),
            PlayerSetup('HERO_08', board=enemy, deck=(YETI,) * 8, mana=30,
                max_mana=30, mana_cap=30)), seed=5151, generation_context=CONTEXT),
            shared_registry(*self.config))

    def first(self, g, cid, zone='hand', player=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone)
                    if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None):
        e = self.first(g, cid)
        g.apply(PlayCard(1, e.id, target, position=len(g.state.players[1].board)
                         if e.kind == CardType.MINION else None))
        return e.id

    def choose(self, g, key='ok'):
        g.apply(SelectChoice(1, g.state.pending_choice.id, (key,)))

    def current(self, g):
        return g.state.entities[g.state.players[1].hero_id]

    def created(self, g, source):
        return [g.state.entities[e.target_id] for e in g.events
                if e.kind == 'card_created' and e.source_id == source]

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(*self.config))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(*self.config)).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(
                g.for_player(player).legal_actions()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'pool_id', 'behavior_id', 'source_json', 'health_result'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_eighteen_full_rows_thirty_strict_faces_eight_parent_faces_and_eighteen_explicit_links(self):
        from tools.card_batch import check_face
        data = load_batch()
        rows = {x['record']['id']: x for key in ('cards', 'existing_dependencies', 'evidence_only') for x in data[key]}
        self.assertEqual(len(rows), 18)
        self.assertEqual(len(data['official_observations']), 30)
        for observation in data['official_observations']:
            cid = observation['card_id']
            check_face(rows[cid]['record'], observation['face'], observation['locale'],
                       data['display_normalizations'].get(cid))
            self.assertEqual(observation['observation']['sha256'], observation['response_sha256'])
        self.assertEqual(len(data['parent_observations']), 8)
        self.assertEqual(len(data['exact_parent_child_links']), 18)
        faces = {(o['card_id'], o['locale']): o['face'] for o in data['parent_observations']}
        for link in data['exact_parent_child_links']:
            self.assertEqual(rows[link['child']]['record']['dbf_id'], link['dbf_id'])
            self.assertIn(link['dbf_id'], faces[link['parent'], link['locale']]['childIds'])
        for locale in ('zh_CN', 'en_US'):
            face = faces[HERO, locale]
            self.assertEqual((face['manaCost'], face['health'], face['armor']), (8, 30, 5))
            self.assertTrue({1178, 1660, 1143} <= set(face['childIds']))
        self.assertEqual(data['collectible_candidate_roots'], [HERO])
        self.assertFalse(data['formal_pool_complete'] or data['cn_calibrated'] or data['parent_rules_implemented'])

    def test_exact_native_definitions_reuse_complete_recipes_and_preserve_old_registry_and_defaults(self):
        before, after = build_registry(), batch_registry()
        self.assertEqual(set(after.cards) - set(before.cards), set(ROOTS) - set(before.cards))
        for cid, card in before.cards.items():
            self.assertEqual(after.card(cid), card)
        for cid, card in before.pool_cards.items():
            self.assertEqual(after.pool_cards[cid], card)
        self.assertEqual(dict(before.pools), dict(after.pools))
        self.assertEqual(dict(before.generation_families), dict(after.generation_families))
        data = load_batch()
        for cid, pin in data['existing_dependency_definition_pins'].items():
            self.assertEqual(canonical_digest(asdict(after.card(cid))), pin)
        for row in data['cards']:
            raw = row['record']
            card = after.card(raw['id'])
            self.assertEqual(card.metadata, metadata_from_record(raw))
            self.assertEqual(card.cost, raw['cost'])
            if card.id in RECIPES:
                self.assertEqual(card, replace(after.card(RECIPES[card.id]), id=card.id,
                    name=raw['name'], metadata=metadata_from_record(raw)))
        hero, weapon = after.card(HERO), after.card(WEAPON)
        self.assertEqual((hero.kind, hero.health, hero.hero_armor, hero.initial_hero_power, hero.hero_card),
                         (CardType.HERO, 30, 5, POWER, True))
        self.assertEqual((weapon.kind, weapon.attack, weapon.health, weapon.durability),
                         (CardType.WEAPON, 3, 0, 8))
        self.assertEqual(sum(after.card(cid).metadata.collectible for cid in ROOTS), 1)
        for cid in PARENTS:
            self.assertEqual(cid in before.cards, cid in after.cards)
        from hs_sim.engine.representative import build_registry as default
        self.assertEqual(default().fingerprint(), DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_jaraxxus_real_hand_identity_preserves_health_adds_armor_retires_weapon_and_refreshes_power(self):
        g = self.game((TEST + 'wound', HERO), armor=3, weapon='CS2_106')
        self.play(g, TEST + 'wound')
        old_hero, old_weapon, old_power = self.current(g).id, g.state.players[1].weapon_id, g.state.players[1].hero_power_id
        g.apply(UseHeroPower(1, old_power))
        hp, armor, mana = self.current(g).health, self.current(g).armor, g.state.players[1].mana
        hand_id = self.play(g, HERO)
        p = g.state.players[1]
        self.assertEqual((p.hero_id, self.current(g).health, self.current(g).armor), (hand_id, hp, armor + 5))
        self.assertEqual((p.hero_class, p.mana), (CardClass.WARLOCK, mana - 8))
        self.assertTrue({old_hero, old_power, old_weapon} <= set(p.graveyard))
        weapon, power = g.state.entities[p.weapon_id], g.state.entities[p.hero_power_id]
        self.assertEqual((weapon.card_id, weapon.attack, weapon.durability), (WEAPON, 3, 8))
        self.assertEqual((power.card_id, power.uses_this_turn), (POWER, 0))
        self.assertEqual(len([e for e in g.events if e.kind == 'weapon_equipped' and e.target_id == weapon.id]), 1)
        self.assertFalse(any(e.kind == 'minion_died' and e.target_id == old_hero for e in g.events))
        g.apply(UseHeroPower(1, power.id))
        token = self.first(g, INFERNAL, 'board')
        self.assertEqual((token.attack, token.health), (6, 6))
        self.assertEqual(g.state.players[1].mana, mana - 10)
        self.portable(g)

    def test_hero_plays_on_physically_full_board_but_new_power_rejects_without_payment(self):
        g = self.game((HERO,), board=(YETI,) * 6 + (TEST + 'dormant',))
        original = g.state.players[1].board
        self.play(g, HERO)
        self.assertEqual(g.state.players[1].board, original)
        saved = g.snapshot()
        with self.assertRaises(IllegalAction):
            g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        self.assertEqual(g.snapshot(), saved)
        self.portable(g)

    def test_hero_insufficient_mana_and_illegal_position_are_atomic(self):
        for mana, position in ((7, None), (30, 0)):
            with self.subTest(mana=mana, position=position):
                g = self.game((HERO,), mana=mana, weapon='CS2_106')
                saved = g.snapshot()
                with self.assertRaises(IllegalAction):
                    g.apply(PlayCard(1, self.first(g, HERO).id, position=position))
                self.assertEqual(g.snapshot(), saved)

    def test_blood_fury_native_hand_weapon_payment_identity_attack_and_wear(self):
        g = self.game((WEAPON,), weapon='CS2_106')
        old = g.state.players[1].weapon_id
        eid = self.play(g, WEAPON)
        self.assertEqual((g.state.players[1].weapon_id, g.state.players[1].mana), (eid, 27))
        self.assertIn(old, g.state.players[1].graveyard)
        g.apply(Attack(1, self.current(g).id, g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[eid].durability, 7)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)
        self.portable(g)

    def test_jaraxxus_preserves_enhanced_max_health_freeze_and_spent_attack(self):
        g = self.game((TEST + 'enhance', HERO), weapon='CS2_106')
        g.apply(Attack(1, self.current(g).id, g.state.players[2].hero_id))
        self.play(g, TEST + 'enhance')
        health = self.current(g).health
        self.play(g, HERO)
        self.assertEqual((self.current(g).health, self.current(g).max_health,
            self.current(g).attacks_this_turn, self.current(g).frozen), (health, 40, 1, True))
        self.portable(g)

    def test_jaraxxus_equipment_wait_restore_replay_and_bad_resume_keep_one_payment_and_equip(self):
        g = self.game((HERO,), mode='hero', weapon='CS2_106')
        self.play(g, HERO)
        self.assertIsNotNone(g.state.pending_choice)
        weapon = g.state.players[1].weapon_id
        other, saved = self.portable(g), g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual((g.state.players[1].mana, g.state.players[1].weapon_id), (22, weapon))
        self.assertEqual(len([e for e in g.events if e.kind == 'weapon_equipped' and e.target_id == weapon]), 1)
        self.portable(g)

    def test_failed_equipment_continuation_restores_original_hero_power_class_weapon_hand_and_payment(self):
        g = self.game((HERO,), mode='hero_fail', weapon='CS2_106', armor=3)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.play(g, HERO)
        self.assertEqual(g.snapshot(), saved)

    def test_all_five_magmaw_forms_die_with_native_source_identity_and_only_attack_buff(self):
        for cid in BODY_FORMS:
            with self.subTest(cid=cid):
                g = self.game((TEST + 'kill',), board=(cid, YETI))
                source, target = self.first(g, cid, 'board'), self.first(g, YETI, 'board')
                self.play(g, TEST + 'kill', source.id)
                self.assertEqual((g.state.entities[source.id].card_id, g.state.entities[source.id].zone), (cid, Zone.GRAVEYARD))
                self.assertEqual((g.state.entities[target.id].attack, g.state.entities[target.id].health), (6, 5))
        g = self.game((TEST + 'kill',), board=(BODY_FORMS[0],))
        rng = g._rng.getstate()
        self.play(g, TEST + 'kill', self.first(g, BODY_FORMS[0], 'board').id)
        self.assertEqual(g._rng.getstate(), rng)

    def test_magmaw_original_recipient_wait_restore_replay_and_same_id_reentry_do_not_retarget(self):
        g = self.game((TEST + 'kill',), board=(BODY_FORMS[-1], YETI), mode='body')
        target = self.first(g, YETI, 'board')
        self.play(g, TEST + 'kill', self.first(g, BODY_FORMS[-1], 'board').id)
        other, saved = self.portable(g), g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game, 'reenter')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertNotEqual(g.state.entities[target.id].board_presence_id, target.board_presence_id)
        self.assertEqual(g.state.entities[target.id].attack, 4)

    def test_both_blood_forms_owner_end_heal_only_wounded_friendly_character_and_empty_pool_no_rng(self):
        for cid in BLOOD_FORMS:
            with self.subTest(cid=cid):
                g = self.game((TEST + 'hit1',), board=(cid, YETI), enemy=(YETI,))
                target = self.first(g, YETI, 'board').id
                self.play(g, TEST + 'hit1', target)
                g.apply(EndTurn(1))
                self.assertEqual(g.state.entities[target].health, 5)
                self.assertEqual(len(g.state.healing_history), 1)
                g.apply(EndTurn(2))
                self.assertEqual(len(g.state.healing_history), 1)
                empty_rng = g._rng.getstate()
                g.apply(EndTurn(1))
                self.assertEqual(g._rng.getstate(), empty_rng)

    def test_blood_original_wounded_recipient_wait_restore_replay_and_reentry_are_not_replaced(self):
        g = self.game((TEST + 'hit1',), board=(BLOOD_FORMS[1], YETI), mode='blood')
        target = self.first(g, YETI, 'board').id
        self.play(g, TEST + 'hit1', target)
        g.apply(EndTurn(1))
        other = self.portable(g)
        for game in (g, other):
            self.choose(game, 'reenter')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.entities[target].health, 5)
        self.assertFalse(g.state.healing_history)

    def test_plume_actual_nonlethal_and_lethal_damage_generate_cross_class_fire_discount_from_native_source(self):
        for damage, cid in (('hit1', FIRE), ('hit5', OTHER_FIRE)):
            with self.subTest(damage=damage, cid=cid):
                g = self.game((TEST + damage,), board=(PLUME,), members=(cid, NATURE))
                source = self.first(g, PLUME, 'board').id
                self.play(g, TEST + damage, source)
                card, = self.created(g, source)
                self.assertEqual(card.card_id, cid)
                self.assertEqual(quote_unselected_cost(g.state, g.registry, card).amount, max(0, g.registry.card(cid).cost - 3))
                self.assertEqual(g.state.entities[source].card_id, PLUME)

    def test_plume_lethal_accepted_reward_wait_restore_replay_and_failed_resume_do_not_require_living_source(self):
        g = self.game((TEST + 'hit5',), board=(PLUME,), members=(FIRE,), mode='plume')
        source = self.first(g, PLUME, 'board').id
        self.play(g, TEST + 'hit5', source)
        other, saved = self.portable(g), g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        card, = self.created(g, source)
        self.assertEqual((card.card_id, card.zone), (FIRE, Zone.HAND))

    def test_plume_zero_prevention_and_silence_do_not_generate(self):
        for prefix in ('hit0', 'shield', 'silence'):
            with self.subTest(prefix=prefix):
                hand = (TEST + prefix,) if prefix == 'hit0' else (TEST + prefix, TEST + 'hit1')
                g = self.game(hand, board=(PLUME,), members=(FIRE,))
                source = self.first(g, PLUME, 'board').id
                self.play(g, TEST + prefix, source)
                if prefix != 'hit0':
                    self.play(g, TEST + 'hit1', source)
                self.assertFalse(self.created(g, source))

    def test_plume_unknown_eligible_fire_fails_before_rng_and_rolls_back_lethal_damage(self):
        r = batch_registry()
        unknown = next(c.card_id for c in r.pool_cards.values() if c.card_id not in r.cards and
            c.kind == CardType.SPELL and c.spell_school == SpellSchool.FIRE and c.metadata.collectible)
        g = self.game((TEST + 'hit5',), board=(PLUME,), members=(FIRE, unknown))
        saved, calls = g.snapshot(), []
        original = random.Random.randrange
        def spy(rng, *args, **kwargs):
            calls.append(args)
            return original(rng, *args, **kwargs)
        with patch.object(random.Random, 'randrange', autospec=True, side_effect=spy):
            with self.assertRaises(ResolutionError):
                self.play(g, TEST + 'hit5', self.first(g, PLUME, 'board').id)
        self.assertFalse(calls)
        self.assertEqual(g.snapshot(), saved)


if __name__ == '__main__':
    unittest.main()
