"""Native modular construction; three necessary real templates, two faces."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import random
import unittest

from hs_sim.engine import (AuraSpec, CardClass, CardDefinition, CardType, Game,
    Keyword, ModularProfile, ModularSelection, OpeningHook, PlayCard,
    PlayerSetup, Rarity, ResolutionError, Scenario, SelectChoice, SnapshotError,
    Zone, assemble_modular_card, validate_deck)
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption,
    CopyMinion, Destroy, InvokeBehavior, RequestChoice, ReturnToHand, ShuffleIntoDeck,
    Silence, Summon, Transform)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.targets import canonical_digest
from opening_fixtures import deck, metadata, policy, registry as opening_registry, setup
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

ROOT = 'TOY_330'
VIRUS, PERFECT, PYLON = 'TOY_330t96', 'TOY_330t99', 'TOY_330t95'
PATH = Path(__file__).resolve().parents[1] / 'data/support/modular-deck-basics.json'
PIN = 'e28d94d06f1f30ee48724f821c7c4052cd7f4792776e6644995febb05d1087a4'
SIX = {Keyword.ELUSIVE, Keyword.POISONOUS, Keyword.DIVINE_SHIELD,
    Keyword.TAUNT, Keyword.LIFESTEAL, Keyword.RUSH}


def evidence():
    value = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(value) != PIN:
        raise ValueError('Modular complete evidence changed')
    result = {}
    for row in value['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Modular original raw changed')
        result[row['id']] = row['data']
    return result


def profile():
    raw = evidence()
    return ModularProfile(ROOT, raw[ROOT]['name'],
        metadata(rarity=Rarity.LEGENDARY, tribes=('MECH',)),
        tuple(cid for cid, row in raw.items() if row['tags'].get('ZILLIAX_CUSTOMIZABLE_FUNCTIONALMODULE')),
        tuple(cid for cid, row in raw.items() if row['tags'].get('ZILLIAX_CUSTOMIZABLE_COSMETICMODULE')))


def selection(*, pylon=False, cosmetic='TOY_330t5'):
    return ModularSelection(ROOT, (PYLON if pylon else VIRUS, PERFECT), cosmetic)


def registry(*, compile_faces=True, wait=False, fault=False):
    r = opening_registry()
    r.register_modular_profile(profile())
    for cid in (VIRUS, PERFECT, PYLON):
        raw = evidence()[cid]
        flags = tuple(Keyword[tag] for tag in ('ELUSIVE', 'POISONOUS', 'DIVINE_SHIELD',
            'TAUNT', 'LIFESTEAL', 'RUSH') if raw['tags'].get(tag))
        r.register_modular_module(CardDefinition(cid, raw['name'], CardType.MINION,
            cost=raw['cost'], attack=raw['attack'], health=raw['health'], keywords=flags,
            auras=(AuraSpec(attack=1),) if cid == PYLON else ()))
    if compile_faces:
        for chosen in (selection(), selection(pylon=True)):
            assemble_modular_card(r, chosen)
    def first(c):
        return c.state.players[c.player_id].board[0]
    effects = {
        'mod.buff': lambda c: (Buff(first(c), 3, 2),),
        'mod.silence': lambda c: (Silence(first(c)),),
        'mod.bounce': lambda c: (ReturnToHand(first(c)),),
        'mod.shuffle': lambda c: (ShuffleIntoDeck(first(c)),),
        'mod.base': lambda c: (CopyMinion(first(c), c.player_id, mode='base'),),
        'mod.current': lambda c: (CopyMinion(first(c), c.player_id),),
        'mod.control': lambda c: (ChangeControl(first(c), 3 - c.player_id),),
        'mod.transform': lambda c: (Transform(first(c), 'card.1'),),
        'mod.kill': lambda c: (Destroy(first(c)),),
        'mod.revive': lambda c: (ResurrectMinion(c.player_id, c.state.death_history[-1].id),),
        'mod.create': lambda c: (AddToHand(c.player_id, selection().card_id),),
        'mod.fail': lambda c: (Buff(first(c), 3, 2), Summon(c.player_id, 'missing.modular.body')),
        'mod.wait.copy': lambda c: (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Copy printed face', (CopyMinion(first(c), c.player_id, mode='base'),)),), c.source_id),),
        'mod.wait.fail': lambda c: (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Run delayed fault', (InvokeBehavior('mod.fail', c.source_id, c.player_id),)),), c.source_id),),
    }
    for cid, behavior in effects.items():
        r.register_behavior(cid, behavior)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata()))
    if wait:
        r.register_behavior('opening.modular.pause', lambda c: (RequestChoice(c.player_id,
            (ChoiceOption('ok', 'Continue'),), c.source_id),) + (
                (InvokeBehavior('opening.modular.fail', c.source_id, c.player_id),) if fault else ()))
        r.register_behavior('opening.modular.fail', lambda c: (AddToHand(c.player_id, 'unknown.opening.face'),))
        r.register_behavior('opening.modular.noop', lambda c: ())
        r.register_card(CardDefinition('opening.modular', 'Opening fixture', CardType.SPELL,
            on_play='opening.modular.noop', opening_hooks=(OpeningHook('before_deal', 'opening.modular.pause'),),
            metadata=metadata()))
    return r


def cards(*, pylon=False, wait=False):
    return (selection(pylon=pylon).card_id, *(('opening.modular',) if wait else ()),
        *(f'card.{n}' for n in range(1, 29 if wait else 30)))


def format_policy(r, **kwargs):
    # The format knows the real collectible blueprint, not generated IDs.
    return replace(policy(r, **kwargs), allowed_card_ids=(ROOT, *(cid for cid in r.cards if cid not in r.modular_faces)))


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class ModularConstructionTests(unittest.TestCase):
    def test_complete_22_raw_records_and_native_options_are_pinned(self):
        rows = evidence()
        original = {row['id']: row for row in json.loads(
            (PATH.parents[1] / 'extracted/cards.json').read_text(encoding='utf-8'))}
        self.assertEqual(len(rows), 22)
        for cid, raw in rows.items(): self.assertEqual(raw, original[cid])
        p = profile()
        self.assertEqual((len(p.module_card_ids), len(p.cosmetic_card_ids)), (8, 8))
        self.assertTrue(all(rows[ROOT][field] is None for field in ('cost', 'attack', 'health')))
        self.assertEqual((rows[VIRUS]['cost'], rows[PERFECT]['cost'], rows[PYLON]['cost']), (4, 5, 3))
        self.assertTrue(all('RARITY' not in rows[c]['tags'] for c in p.module_card_ids))
        self.assertIn('+1 Attack', rows[PYLON]['text_en'])
        self.assertEqual(rows[ROOT]['tags']['SIDEBOARD_TYPE'], 2)

    def test_selection_is_immutable_and_only_functional_order_is_canonicalized(self):
        chosen = selection()
        opposite = ModularSelection(ROOT, chosen.module_card_ids[::-1], chosen.cosmetic_card_id)
        self.assertEqual(chosen, opposite); self.assertEqual(chosen.card_id, opposite.card_id)
        self.assertNotEqual(chosen.card_id, selection(cosmetic='TOY_330t6').card_id)
        with self.assertRaises(FrozenInstanceError): chosen.cosmetic_card_id = 'other'
        for modules in ((VIRUS,), (VIRUS, VIRUS), (VIRUS, PERFECT, PYLON), [VIRUS, PERFECT]):
            with self.subTest(modules=modules), self.assertRaises(ValueError):
                ModularSelection(ROOT, modules, 'TOY_330t5')
        with self.assertRaises(ValueError): replace(chosen, version='modular-v0')

    def test_profiles_reject_unreviewed_metadata_and_overlapping_options(self):
        p = profile()
        for changes in ({'metadata': metadata()}, {'metadata': metadata(CardClass.MAGE, rarity=Rarity.LEGENDARY)},
                {'metadata': replace(p.metadata, max_copies=2)},
                {'cosmetic_card_ids': (VIRUS,)}, {'module_card_ids': (ROOT, PERFECT)}, {'version': 'modular-v0'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(p, **changes)
        r = registry(compile_faces=False)
        with self.assertRaises(ValueError): r.register_modular_profile(p)
        with self.assertRaises(ValueError): r.register_modular_profile(replace(p, source_card_id='other.root'))

    def test_supported_face_has_summed_printed_values_and_six_keywords(self):
        r = registry(); card = r.card(selection().card_id)
        self.assertEqual((card.cost, card.attack, card.health), (9, 5, 7))
        self.assertEqual(set(card.keywords), SIX)
        self.assertEqual((card.metadata.deck_identity, card.metadata.rarity, card.metadata.tribes),
            (ROOT, Rarity.LEGENDARY, ('MECH',)))
        self.assertEqual(r.modular_faces[card.id], selection())
        self.assertFalse(card.starship_for); self.assertIsNone(card.choose_one)

    def test_assembly_is_deterministic_idempotent_and_only_creates_requested_faces(self):
        r = registry(compile_faces=False); before = set(r.cards)
        cid = assemble_modular_card(r, selection())
        fingerprint = r.fingerprint()
        self.assertEqual(assemble_modular_card(r, selection()), cid)
        self.assertEqual(r.fingerprint(), fingerprint)
        self.assertEqual(set(r.cards) - before, {cid})
        self.assertEqual(len(r.modular_faces), 1)
        r2 = registry(compile_faces=False); assemble_modular_card(r2, selection())
        self.assertEqual(r2.fingerprint(), fingerprint)

    def test_invalid_or_unadapted_selection_does_not_mutate_registry(self):
        r = registry(compile_faces=False); before = r.fingerprint()
        for chosen in (replace(selection(), source_card_id='unknown.root'),
                replace(selection(), module_card_ids=('TOY_330t92', PERFECT)),
                replace(selection(), module_card_ids=('outside', PERFECT)),
                replace(selection(), cosmetic_card_id='outside')):
            with self.subTest(chosen=chosen), self.assertRaises(ValueError): assemble_modular_card(r, chosen)
            self.assertEqual(r.fingerprint(), before); self.assertFalse(r.modular_faces)
        with self.assertRaisesRegex(UnsupportedDefinitionError, 'no executable adapter'):
            assemble_modular_card(r, ModularSelection(ROOT, ('TOY_330t92', PERFECT), 'TOY_330t5'))
        self.assertEqual(len(r.modular_modules), 3)
        self.assertIn('TOY_330t92', r.modular_profiles[ROOT].module_card_ids)

    def test_blueprint_modules_cosmetics_and_arbitrary_alias_are_not_physical_cards(self):
        r = registry()
        for cid in (ROOT, VIRUS, 'TOY_330t5', 'modular:forged'):
            with self.subTest(cid=cid), self.assertRaises(ValueError):
                r.register_card(CardDefinition(cid, cid, CardType.MINION, health=1))
            with self.assertRaises(UnsupportedDefinitionError): r.card(cid)
        with self.assertRaises(ValueError):
            r.register_modular_module(replace(r.modular_modules[VIRUS], id='outside'))
        with self.assertRaises(ValueError):
            r.register_modular_module(replace(r.modular_modules[VIRUS], on_play='power'))

    def test_templates_use_ordinary_reference_validation_and_failure_is_atomic(self):
        r = registry(compile_faces=False)
        r._modular_modules[VIRUS] = replace(r.modular_modules[VIRUS], battlecry='missing.behavior')
        before = (dict(r.cards), dict(r.modular_faces))
        with self.assertRaisesRegex(UnsupportedDefinitionError, 'missing.behavior'):
            assemble_modular_card(r, selection())
        self.assertEqual((dict(r.cards), dict(r.modular_faces)), before)

    def test_compiled_face_and_recipe_forgery_are_detected_before_legality(self):
        for edit in ('face', 'recipe', 'orphan'):
            with self.subTest(edit=edit):
                r = registry(); cid = selection().card_id
                if edit == 'face': r._cards[cid] = replace(r.card(cid), health=8)
                elif edit == 'recipe': r._modular_faces[cid] = selection(pylon=True)
                else: del r._modular_faces[cid]
                with self.assertRaises(ValueError): r.fingerprint()
                with self.assertRaises(ValueError): validate_deck(deck(cards=cards()), r, format_policy(r))

    def test_registered_format_root_authorizes_only_compiled_complete_faces(self):
        r = registry(); p = format_policy(r)
        self.assertNotIn(selection().card_id, p.allowed_card_ids)
        self.assertTrue(validate_deck(deck(cards=cards()), r, p).valid)
        for cid in (ROOT, VIRUS, 'TOY_330t5'):
            result = validate_deck(deck(cards=(cid, *cards()[1:])), r, p)
            self.assertIn('unsupported_definition', {i.code for i in result.issues})

    def test_root_and_face_bans_and_root_copy_group_are_enforced(self):
        r = registry(); own = deck(cards=cards())
        for banned in (ROOT, selection().card_id):
            result = validate_deck(own, r, format_policy(r, banned_card_ids=(banned,)))
            self.assertIn('format_legality', {i.code for i in result.issues})
        result = validate_deck(own, r, replace(format_policy(r), allowed_card_ids=tuple(r.cards)))
        self.assertIn('format_legality', {i.code for i in result.issues})
        for second in (selection().card_id, selection(pylon=True).card_id):
            result = validate_deck(deck(cards=(cards()[0], second, *cards()[2:])), r, format_policy(r))
            self.assertIn('copy_limit', {i.code for i in result.issues})

    def test_frozen_registry_cannot_add_or_recompile_recipes(self):
        r = registry(); r.freeze(); before = r.fingerprint()
        for mutate in (lambda: assemble_modular_card(r, selection()),
                lambda: r.register_modular_profile(profile()),
                lambda: r.register_modular_module(r.modular_modules[VIRUS])):
            with self.assertRaisesRegex(ValueError, 'frozen'): mutate()
        self.assertEqual(r.fingerprint(), before)
        with self.assertRaises(TypeError): r.modular_faces['new'] = selection()


class ModularRuntimeTests(unittest.TestCase):
    def scenario(self, spells=(), *, pylon=False):
        self.options = {}
        face = selection(pylon=pylon).card_id
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero', hand=(face, *spells),
            mana=10, max_mana=10),
            PlayerSetup('warrior.hero')), seed=7), registry())

    def play(self, g, cid):
        eid = next(e for e in g.state.players[1].hand if g.state.entities[e].card_id == cid)
        g.apply(PlayCard(1, eid))
        return eid

    def choose(self, g, options=None):
        choice = g.state.pending_choice
        g.apply(SelectChoice(choice.player_id, choice.id,
            (choice.options[0].id,) if options is None else options))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, registry(**self.options))
        self.assertEqual(restored.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(**self.options)).snapshot(), saved)
        for actor in (1, 2): self.assertEqual(restored.observe(actor), g.observe(actor))
        return saved

    def constructed(self, *, first=1, wait=False, fault=False, seed=71):
        self.options = dict(wait=wait, fault=fault)
        r = registry(**self.options)
        s = replace(setup(r, first=first, seed=seed, decks=(deck(cards=cards(wait=wait)),
            deck(CardClass.WARRIOR, cards(pylon=True)))), policy=format_policy(r))
        return Game.from_decks(s, r)

    def test_two_players_have_independent_recipes_original_entities_and_mulligans(self):
        for first in (1, 2):
            with self.subTest(first=first):
                g = self.constructed(first=first)
                self.assertEqual(tuple(map(len, g.state.opening.original_entities)), (30, 30))
                for pid, pylon in ((1, False), (2, True)):
                    original = g.state.opening.original_entities[pid - 1]
                    self.assertEqual(tuple(g.state.entities[e].card_id for e in original), cards(pylon=pylon))
                    self.assertEqual(g.state.players[pid].original_deck, cards(pylon=pylon))
                self.portable(g)
                while g.state.pending_choice: self.choose(g, ())
                self.assertEqual(g.state.opening.stage, 'complete'); self.portable(g)

    def test_mulligan_returns_same_assembled_physical_identity(self):
        def draws_face(seed):
            values = list(cards()); random.Random(seed).shuffle(values)
            return selection().card_id in values[:3]
        seed = next(n for n in range(300) if draws_face(n))
        g = self.constructed(seed=seed)
        original = g.state.opening.original_entities[0][0]
        self.assertIn(original, g.state.players[1].hand)
        choice = g.state.pending_choice
        option = next(o for o in choice.options if o.card_id == selection().card_id)
        self.choose(g, (option.id,))
        while g.state.pending_choice: self.choose(g, ())
        self.assertEqual(g.state.entities[original].card_id, selection().card_id)
        self.assertEqual(g.registry.modular_faces[g.state.entities[original].card_id], selection())
        self.portable(g)

    def test_before_deal_wait_restores_original_recipe_and_fault_rolls_back(self):
        for fault in (False, True):
            with self.subTest(fault=fault):
                g = self.constructed(wait=True, fault=fault)
                self.assertEqual(len(g.state.players[1].deck), 30)
                saved = self.portable(g)
                if fault:
                    with self.assertRaises(ResolutionError): self.choose(g)
                    self.assertEqual(g.snapshot(), saved); self.portable(g)
                else:
                    self.choose(g)
                    while g.state.pending_choice: self.choose(g, ())
                    self.portable(g)

    def test_paid_face_uses_sum_cost_stats_and_keywords_without_components(self):
        g = self.scenario(); eid = self.play(g, selection().card_id); e = g.state.entities[eid]
        self.assertEqual((g.state.players[1].mana, e.base_cost, e.attack, e.max_health), (1, 9, 5, 7))
        self.assertEqual(e.keywords, SIX); self.assertFalse(e.components)
        self.assertEqual(len(g.state.play_history), 1)
        self.portable(g)

    def test_silence_preserves_assembled_printed_stats_and_base_copy_restores_text(self):
        g = self.scenario(('mod.buff', 'mod.silence', 'mod.current', 'mod.base'))
        eid = self.play(g, selection().card_id)
        self.play(g, 'mod.buff'); self.play(g, 'mod.silence')
        e = g.state.entities[eid]
        self.assertEqual((e.attack, e.max_health), (5, 7)); self.assertFalse(e.keywords)
        self.play(g, 'mod.current'); current = g.state.entities[g.state.players[1].board[-1]]
        self.assertTrue(current.silenced); self.assertFalse(current.keywords)
        self.play(g, 'mod.base'); printed = g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual((printed.base_cost, printed.attack, printed.max_health), (9, 5, 7))
        self.assertEqual(printed.keywords, SIX); self.assertNotEqual(printed.id, eid)
        self.assertEqual(printed.card_id, e.card_id); self.portable(g)

    def test_pylon_aura_is_installed_and_removed_through_ordinary_lifecycle(self):
        # A base copy is another independent printed body, so each benefits from the other source.
        g = self.scenario(('mod.base', 'mod.silence'), pylon=True)
        self.assertEqual(g.registry.card(selection(pylon=True).card_id).auras, (AuraSpec(1),))
        eid = self.play(g, selection(pylon=True).card_id); self.play(g, 'mod.base')
        first, second = (g.state.entities[e] for e in g.state.players[1].board)
        self.assertEqual((first.attack, second.attack, first.max_health, second.max_health), (6, 6, 4, 4))
        self.play(g, 'mod.silence')
        first, second = (g.state.entities[e] for e in g.state.players[1].board)
        self.assertEqual((first.attack, second.attack, first.max_health, second.max_health), (6, 5, 4, 4))
        self.assertFalse(first.keywords); self.portable(g)

    def test_bounce_shuffle_control_and_transform_follow_physical_card_identity(self):
        for operation in ('mod.bounce', 'mod.shuffle', 'mod.control', 'mod.transform'):
            with self.subTest(operation=operation):
                g = self.scenario(('mod.silence', operation)); eid = self.play(g, selection().card_id)
                self.play(g, 'mod.silence'); self.play(g, operation); e = g.state.entities[eid]
                if operation in ('mod.bounce', 'mod.shuffle'):
                    self.assertEqual(e.zone, Zone.HAND if operation == 'mod.bounce' else Zone.DECK)
                    self.assertEqual((e.base_cost, e.base_attack, e.base_health), (9, 5, 7))
                    self.assertFalse(e.silenced); self.assertEqual(e.keywords, SIX)
                elif operation == 'mod.control':
                    self.assertEqual(e.controller, 2); self.assertTrue(e.silenced)
                else:
                    self.assertEqual(e.card_id, 'card.1'); self.assertEqual((e.base_attack, e.base_health), (4, 4))
                self.portable(g)

    def test_death_history_revival_recreates_assembled_printed_face(self):
        g = self.scenario(('mod.silence', 'mod.kill', 'mod.revive'))
        eid = self.play(g, selection().card_id); self.play(g, 'mod.silence'); self.play(g, 'mod.kill')
        record = g.state.death_history[-1]
        self.assertEqual(record.card_id, selection().card_id); self.assertFalse(record.components)
        self.play(g, 'mod.revive'); restored = g.state.entities[g.state.players[1].board[-1]]
        self.assertNotEqual(restored.id, eid); self.assertEqual(restored.keywords, SIX)
        self.assertEqual((restored.base_cost, restored.attack, restored.max_health), (9, 5, 7))
        self.portable(g)

    def test_created_face_and_choice_copy_use_complete_recipe_and_restore(self):
        g = self.scenario(('mod.create', 'mod.wait.copy'))
        self.play(g, 'mod.create'); self.assertEqual(len(g.state.players[1].hand), 3)
        eid = self.play(g, selection().card_id); self.play(g, 'mod.wait.copy')
        self.portable(g); self.choose(g)
        self.assertEqual(len(g.state.players[1].board), 2)
        self.assertTrue(all(g.state.entities[e].card_id == g.state.entities[eid].card_id for e in g.state.players[1].board))
        self.portable(g)

    def test_failed_delayed_choice_restores_entities_recipe_rng_and_player_view(self):
        g = self.scenario(('mod.wait.fail',)); self.play(g, selection().card_id)
        self.play(g, 'mod.wait.fail'); saved = self.portable(g); view = g.observe(1)
        with self.assertRaisesRegex(ResolutionError, 'missing.modular.body'): self.choose(g)
        self.assertEqual(g.snapshot(), saved); self.assertEqual(g.observe(1), view); self.portable(g)

    def test_recipe_mapping_and_opponent_hidden_face_are_not_published(self):
        g = self.scenario()
        opponent = json.dumps(g.observe(2)); own = json.dumps(g.observe(1))
        self.assertIn(selection().card_id, own)
        for private in (selection().card_id, ROOT, 'module_card_ids', 'cosmetic_card_id', 'modular-v1', 'original_deck'):
            self.assertNotIn(private, opponent)
        # Public board text is visible only after the physical face enters play.
        self.play(g, selection().card_id)
        shown = g.observe(2)['players'][0]['board'][0]
        self.assertEqual(shown['card_id'], selection().card_id)
        self.assertEqual(set(shown['keywords']), {k.value for k in SIX})

    def test_rehashed_original_or_setup_recipe_change_is_semantically_rejected(self):
        g = self.constructed(); saved = self.portable(g)
        for part in ('state', 'setup'):
            bad = deepcopy(saved)
            target = bad['state']['players']['1']['original_deck'] if part == 'state' else bad['match_setup']['decks'][0]['cards']
            target[0] = selection(pylon=True).card_id
            with self.subTest(part=part), self.assertRaisesRegex(SnapshotError, 'Modular original deck differs'):
                Game.from_snapshot(rehash(bad), registry())

    def test_recipe_fingerprint_and_previous_rules_rejected_without_layout_change(self):
        g = self.constructed(); saved = self.portable(g)
        self.assertEqual((g.ruleset.id, g.mechanics.version, saved['schema_version']),
            ('prototype-v302', CORE_EFFECTS_VERSION, 265))
        self.assertNotIn('modular', saved['state']['players']['1'])
        r = registry(compile_faces=False); assemble_modular_card(r, selection(cosmetic='TOY_330t6'))
        with self.assertRaisesRegex(SnapshotError, 'fingerprint'): Game.from_snapshot(saved, r)
        old = deepcopy(saved); old['ruleset']['id'] = 'prototype-v180'
        with self.assertRaises(SnapshotError): Game.from_snapshot(old, registry())


if __name__ == '__main__':
    unittest.main()
