"""Fabled+ construction only; real combat bodies are explicitly unavailable."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, DeckSizeRule,
    DeckValidationError, FabledSpec, Game, Keyword, OpeningHook, PlayCard,
    PlayerSetup, Rarity, ResolutionError, Scenario, SelectChoice, SnapshotError,
    expand_fabled_cards, validate_deck)
from hs_sim.engine.effects import AddToHand, ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.pools import GenerationContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import deck, metadata, policy, registry as opening_registry, setup
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION


ROOT = 'TIME_005'
MEMBERS = ('TIME_005t1', 'TIME_005t2', 'TIME_005t8', 'TIME_005t3',
           'TIME_005t4', 'TIME_005t6', 'TIME_005t5', 'TIME_005t7', 'TIME_005t9')
SHEEP = 'TIME_005t9t'
PATH = Path(__file__).resolve().parents[1] / 'data/support/fabled-plus-basics.json'
PIN = '30e3abd18aa949821657d31c2714361c8f4b3659b5ebaf7dbd86b302638ce7ff'


def evidence():
    value = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(value) != PIN:
        raise ValueError('Fabled+ full evidence changed')
    result = {}
    for row in value['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Fabled+ original raw changed')
        result[row['id']] = row['data']
    return result


def registry(*, size=True, bundle=True, wait=False, fault=False):
    r = opening_registry()
    cls = CardClass.WARLOCK
    r.register_card(CardDefinition('warlock.power', 'Fixture power', CardType.HERO_POWER,
        cost=2, on_use='power', metadata=metadata(cls, collectible=False)))
    r.register_card(CardDefinition('warlock.hero', 'Fixture hero', CardType.HERO, health=30,
        initial_hero_power='warlock.power', metadata=metadata(cls, collectible=False)))
    # These faces prove construction metadata and original physical identity.
    # Their combat bodies are not adapted; a play never silently becomes blank.
    def unavailable(context):
        raise ValueError('Fabled+ construction fixture has no combat adapter')
    r.register_behavior('fabledplus.unavailable', unavailable)
    for cid, raw in evidence().items():
        tags = raw['tags']
        flags = tuple(k for tag, k in (('TAUNT', Keyword.TAUNT), ('RUSH', Keyword.RUSH))
                      if tags.get(tag))
        r.register_card(CardDefinition(cid, raw['name'], CardType.MINION,
            cost=raw['cost'], attack=raw['attack'], health=raw['health'], keywords=flags,
            on_play='fabledplus.unavailable' if cid != SHEEP else None,
            battlecry='fabledplus.unavailable' if tags.get('BATTLECRY') else None,
            deathrattle='fabledplus.unavailable' if tags.get('DEATHRATTLE') else None,
            metadata=metadata(cls, collectible=raw['collectible'],
                rarity=Rarity.LEGENDARY if tags.get('RARITY') == 5 else None)))
    if bundle:
        r.register_fabled(FabledSpec(ROOT, MEMBERS))
    if size:
        r.register_deck_size_rule(DeckSizeRule(ROOT, 40))
    if wait:
        r.register_behavior('opening.fail', lambda context: (
            AddToHand(context.player_id, 'unknown.after.opening'),))
        def pause(context):
            return (RequestChoice(context.player_id,
                (ChoiceOption('ok', 'Continue'),), context.source_id),) + (
                (InvokeBehavior('opening.fail', context.source_id, context.player_id),) if fault else ())
        r.register_behavior('opening.pause', pause)
        r.register_behavior('opening.noop', lambda context: ())
        r.register_card(CardDefinition('opening.pause', 'Opening fixture', CardType.SPELL,
            on_play='opening.noop', opening_hooks=(OpeningHook('before_deal', 'opening.pause'),),
            metadata=metadata()))
    return r


def physical(r, *, wait=False):
    ordinary = tuple(f'card.{n}' for n in range(1, 30 if wait else 31))
    return expand_fabled_cards((ROOT, *(('opening.pause',) if wait else ()), *ordinary), r)


class FabledPlusConstructionTests(unittest.TestCase):
    def report(self, cards=None, *, r=None, p=None, cls=CardClass.WARLOCK):
        r = r or registry()
        return validate_deck(deck(cls, physical(r) if cards is None else cards), r, p or policy(r))

    def codes(self, result):
        return {issue.code for issue in result.issues}

    def test_complete_raw_has_nine_tokens_and_excludes_related_sheep(self):
        rows = evidence()
        original = {r['id']: r for r in json.loads(
            (PATH.parents[1] / 'extracted/cards.json').read_text(encoding='utf-8'))}
        self.assertEqual(tuple(rows), (ROOT, *MEMBERS, SHEEP))
        for cid, raw in rows.items():
            self.assertEqual(raw, original[cid])
        self.assertEqual(rows[ROOT]['tags']['FABLED_PLUS'], 1)
        self.assertEqual(rows[ROOT]['tags']['DECK_RULE_MOD_DECK_SIZE'], 40)
        self.assertEqual(rows[ROOT]['tags']['RARITY'], 5)
        self.assertEqual(tuple(cid for cid, raw in rows.items()
            if raw['tags'].get('IS_FABLED_BUNDLE_CARD')), MEMBERS)
        self.assertEqual(len(rows[ROOT]['related_dbf_ids']), 10)
        self.assertTrue(all('RARITY' not in rows[c]['tags'] for c in MEMBERS))
        self.assertNotIn('IS_FABLED_BUNDLE_CARD', rows[SHEEP]['tags'])

    def test_reviewed_tokens_keep_absent_rarity_and_complete_bundle_is_valid(self):
        r = registry()
        self.assertTrue(all(r.card(cid).metadata.rarity is None for cid in MEMBERS))
        self.assertTrue(self.report(r=r).valid)
        self.assertEqual(r.fabled[ROOT].version, 'fabled-v2')

    def test_expansion_produces_ten_family_slots_and_thirty_other_slots(self):
        r = registry(); selected = (ROOT, *(f'card.{i}' for i in range(1, 31)))
        complete = expand_fabled_cards(selected, r)
        self.assertEqual(complete, (ROOT, *MEMBERS, *selected[1:]))
        self.assertEqual(len(complete), 40)
        self.assertEqual(len(selected), 31)
        self.assertEqual(Counter(complete)[ROOT], 1)
        self.assertEqual(sum(cid in {ROOT, *MEMBERS} for cid in complete), 10)

    def test_existing_capacity_rule_requires_forty_not_thirty_or_forty_nine(self):
        r = registry(); cards = physical(r)
        for bad in (cards[:30], (*cards, *cards[-9:])):
            with self.subTest(length=len(bad)):
                self.assertIn('deck_size', self.codes(self.report(bad, r=r)))
        self.assertEqual(policy(r).deck_size, 30)
        self.assertTrue(self.report(r=r).valid)

    def test_omitted_capacity_or_bundle_declaration_is_not_inferred(self):
        for options, code in (({'size': False}, 'deck_size'), ({'bundle': False}, 'uncollectible')):
            r = registry(**options)
            with self.subTest(options=options):
                cards = (ROOT, *MEMBERS, *(f'card.{i}' for i in range(1, 31)))
                self.assertIn(code, self.codes(self.report(cards, r=r)))
                with self.assertRaises(DeckValidationError):
                    Game.from_decks(setup(r, decks=(deck(CardClass.WARLOCK, cards),
                        deck(CardClass.WARRIOR))), r)

    def test_every_original_member_and_root_is_required_exactly_once(self):
        r = registry(); cards = physical(r)
        for cid in (ROOT, *MEMBERS):
            bad = list(cards); bad[bad.index(cid)] = 'card.31'
            with self.subTest(missing=cid):
                codes = self.codes(self.report(tuple(bad), r=r))
                self.assertIn('uncollectible' if cid == ROOT else 'fabled_bundle', codes)
        bad = (ROOT, MEMBERS[0], MEMBERS[0], *cards[3:])
        self.assertIn('fabled_bundle', self.codes(self.report(bad, r=r)))

    def test_nonlegendary_member_identity_still_has_a_one_copy_group_limit(self):
        r = registry(); old = r.card(MEMBERS[1])
        r._cards[MEMBERS[1]] = replace(old,
            metadata=replace(old.metadata, deck_identity=MEMBERS[0], max_copies=2))
        self.assertIn('copy_limit', self.codes(self.report(r=r)))

    def test_rarity_exemption_does_not_authorize_sheep_or_other_cards(self):
        r = registry(); cards = physical(r)
        codes = self.codes(self.report((*cards[:-1], SHEEP), r=r))
        self.assertIn('uncollectible', codes)
        old = r.card('card.1'); r._cards['card.1'] = replace(old,
            metadata=replace(old.metadata, rarity=None))
        self.assertIn('unknown_metadata', self.codes(self.report(r=r)))

    def test_native_class_member_bans_and_format_filters_remain_strict(self):
        r = registry()
        for p in (policy(r, banned_card_ids=(ROOT,)), policy(r, banned_card_ids=(MEMBERS[0],)),
                  replace(policy(r), allowed_card_ids=tuple(c for c in r.cards if c != MEMBERS[-1]))):
            with self.subTest(policy=p):
                self.assertIn('format_legality', self.codes(self.report(r=r, p=p)))
        codes = self.codes(self.report(r=r, cls=CardClass.MAGE))
        self.assertIn('class', codes); self.assertIn('uncollectible', codes)

    def test_unregistered_or_wrong_native_token_cannot_be_granted(self):
        r = registry(); old = r.card(MEMBERS[0])
        r._cards[MEMBERS[0]] = replace(old,
            metadata=replace(old.metadata, classes=(CardClass.MAGE,)))
        with self.assertRaises(ValueError): r.validate()
        with self.assertRaises(ValueError): FabledSpec(ROOT, MEMBERS, 'fabled-v1')


class FabledPlusRuntimeTests(unittest.TestCase):
    def constructed(self, *, first=1, wait=False, fault=False):
        self.options = dict(wait=wait, fault=fault)
        r = registry(**self.options)
        return Game.from_decks(setup(r, first=first, decks=(
            deck(CardClass.WARLOCK, physical(r, wait=wait)), deck(CardClass.WARRIOR))), r)

    def choose(self, game, *, mulligan=False):
        choice = game.state.pending_choice
        return game.apply(SelectChoice(choice.player_id, choice.id,
            () if mulligan else (choice.options[0].id,)))

    def portable(self, game):
        saved = json.loads(json.dumps(game.snapshot()))
        restored = Game.from_snapshot(saved, registry(**self.options))
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(game), registry(**self.options)).snapshot(), saved)
        for actor in (1, 2): self.assertEqual(restored.observe(actor), game.observe(actor))

    def test_forty_and_thirty_originals_use_ordinary_opening_and_mulligan(self):
        for first in (1, 2):
            with self.subTest(first=first):
                game = self.constructed(first=first)
                self.assertEqual(tuple(map(len, game.state.opening.original_entities)), (40, 30))
                own = game.state.opening.original_entities[0]
                self.assertEqual(tuple(game.state.entities[e].card_id for e in own),
                    game.state.players[1].original_deck)
                self.assertEqual(len(set(own)), 40)
                self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 30)
                self.portable(game)
                while game.state.pending_choice: self.choose(game, mulligan=True)
                self.portable(game)
                self.assertEqual(game._generation_context.starting_decks[0],
                    game.state.players[1].original_deck)

    def test_before_deal_choice_has_all_original_tokens_and_resumes(self):
        game = self.constructed(wait=True)
        self.assertEqual(len(game.state.players[1].deck), 40)
        self.portable(game); self.choose(game); self.portable(game)
        while game.state.pending_choice: self.choose(game, mulligan=True)
        self.portable(game)

    def test_failed_opening_choice_restores_complete_original_group(self):
        game = self.constructed(wait=True, fault=True); saved = game.snapshot()
        with self.assertRaises(ResolutionError): self.choose(game)
        self.assertEqual(game.snapshot(), saved); self.portable(game)

    def test_construction_only_combat_bodies_explicitly_fail_and_roll_back(self):
        self.options = {}
        for cid in (ROOT, *MEMBERS):
            with self.subTest(cid=cid):
                game = Game.from_scenario(Scenario((PlayerSetup('warlock.hero', hand=(cid,),
                    mana=10, max_mana=10), PlayerSetup('warrior.hero')), seed=7,
                    generation_context=GenerationContext('synthetic-test-target', 'experimental',
                        starting_decks=((), ()))), registry())
                saved = game.snapshot(); actor_view = game.observe(1)
                with self.assertRaisesRegex(ResolutionError, 'no combat adapter'):
                    game.apply(PlayCard(1, game.state.players[1].hand[0]))
                self.assertEqual(game.snapshot(), saved)
                self.assertEqual(game.observe(1), actor_view); self.portable(game)

    def test_complete_origin_crop_and_rehashed_setup_tampering_are_rejected(self):
        game = self.constructed(); saved = game.snapshot()
        for change in (lambda s: s['state']['players']['1']['original_deck'].__setitem__(1, SHEEP),
                       lambda s: s['match_setup']['decks'][0]['cards'].__setitem__(1, SHEEP)):
            with self.subTest(change=change):
                bad = deepcopy(saved); change(bad); bad['state_hash'] = canonical_hash(bad['state'])
                with self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())

    def test_changed_declaration_and_previous_rules_are_rejected_without_new_layout(self):
        game = self.constructed(); saved = game.snapshot()
        self.assertEqual((game.ruleset.id, game.mechanics.version, saved['schema_version']),
            ('prototype-v302', CORE_EFFECTS_VERSION, 266))
        changed = registry(bundle=False); changed.register_fabled(FabledSpec(ROOT, MEMBERS[::-1]))
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, changed)
        old = deepcopy(saved); old['ruleset']['id'] = 'prototype-v179'
        with self.assertRaises(SnapshotError): Game.from_snapshot(old, registry())
        self.assertNotIn('fabled', saved['state']['players']['1'])

    def test_player_cannot_see_opponent_original_family_or_registry_declarations(self):
        game = self.constructed(); observation = json.dumps(game.observe(2))
        for private in (ROOT, *MEMBERS, 'original_deck', 'companion_card_ids', 'fabled-v2'):
            self.assertNotIn(private, observation)
