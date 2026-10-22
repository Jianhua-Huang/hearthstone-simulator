"""Real Combo entry; every small assembly domain below is an explicit fixture."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.shadowcrafter_card import CARD, POOL, QUERY, load_batch
from hs_sim.engine import (CardDefinition, CardType, Game, IllegalAction, Keyword,
    PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import recipe_from_id
from hs_sim.engine.assemble_offers import Assemble, validate_offer
from hs_sim.engine.effects import Destroy
from hs_sim.engine.model import CardClass, CardMetadata, ChoicePurpose
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face
import test_native_assemble_entry_cards as previous

MAGE, FLY, HOARDER, BEAR, PALADIN = (
    'CORE_DRG_107', 'CORE_UNG_809', 'CORE_EX1_096', 'CORE_GIL_622', 'BE_152')
MEMBERS = (MAGE, FLY, HOARDER, BEAR)
P = 'fixture.shadowcrafter.'
ZERO, KILL, WATCH, BAD = (P+x for x in ('zero', 'kill', 'watch', 'unreviewed'))
CTX = GenerationContext('k389-explicit-reviewed-fixture', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(maxsize=None)
def fixture(mode='normal', members=MEMBERS):
    registry = build_registry()
    registry.register_behavior(ZERO, lambda c: ())
    registry.register_card(CardDefinition(ZERO, 'Explicit zero-cost starter', CardType.SPELL,
        metadata=META, on_play=ZERO))
    from hs_sim.engine import TargetSpec
    registry.register_behavior(KILL, lambda c: (Destroy(c.target_id, c.source_id),))
    registry.register_card(CardDefinition(KILL, 'Explicit removal', CardType.SPELL, metadata=META,
        on_play=KILL, targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    if mode in ('unknown', 'unreviewed'):
        metadata = replace(META, classes=(CardClass.MAGE,))
        if mode == 'unreviewed':
            registry.register_card(CardDefinition(BAD, 'Explicit unreviewed fixture', CardType.MINION,
                cost=1, attack=1, health=1, battlecry=ZERO, metadata=metadata))
            registry.register_pool_card(PoolCard.from_definition(registry.card(BAD)))
        else:
            registry.register_pool_card(PoolCard(BAD, CardType.MINION, 1, metadata))
        members = (*members, BAD)
    if mode != 'missing':
        registry.register_pool(PoolDefinition(POOL, 'explicit-reviewed-v1', CTX.target_id,
            CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode == 'fail':
        def reject(c):
            entity = c.state.entities.get(c.event.target_id)
            if entity is not None and entity.card_id.startswith('assemble:'):
                raise ResolutionError('Intentional selected-card creation failure')
            return ()
        registry.register_behavior(WATCH, reject)
        registry.register_card(CardDefinition(WATCH, 'Explicit creation failure fixture', CardType.MINION,
            attack=1, health=20, metadata=META, triggers=(TriggerSpec('card_created', WATCH),)))
    registry.freeze()
    return registry


class ShadowcrafterTests(unittest.TestCase):
    play = previous.NativeAssembleEntryTests.play
    choose = previous.NativeAssembleEntryTests.choose
    offer = previous.NativeAssembleEntryTests.offer
    readers = {}

    def game(self, hand=(ZERO, CARD), mode='normal', members=MEMBERS, hero='HERO_03'):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hero_power_card_id=hero+'bp', hand=hand,
                board=(WATCH,) if mode == 'fail' else (), deck=(ZERO,)*12, mana=10, max_mana=10),
            PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', hand=(ZERO,),
                deck=(ZERO,)*12, mana=10, max_mana=10)), seed=0, generation_context=CTX),
            fixture(mode, members))

    def start(self, game):
        self.play(game, ZERO)
        return self.play(game, CARD)

    def portable(self, game, mode='normal', members=MEMBERS):
        key = (mode, members)
        if key not in self.readers:
            self.readers[key] = fixture.__wrapped__(*key)
        registry = self.readers[key]
        saved = json.loads(json.dumps(game.snapshot()))
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(saved, registry).snapshot(), saved)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), saved)
        return Game.from_snapshot(saved, registry)

    def test_complete_original_record_two_faces_and_native_combo_definition(self):
        data = load_batch(); row = data['cards'][0]['record']; card = fixture().card(CARD)
        self.assertEqual(canonical_digest(row), data['cards'][0]['record_sha256'])
        self.assertEqual(asdict(card.metadata), asdict(metadata_from_record(row)))
        self.assertEqual((card.cost, card.attack, card.health), (2, 3, 2))
        self.assertEqual(card.keywords, (Keyword.COMBO,)); self.assertIsNotNone(card.combo)
        self.assertIsNone(card.battlecry); self.assertIsNone(card.on_play)
        self.assertEqual(len(data['official_observations']), 2)
        for observation in data['official_observations']:
            check_face(row, observation['face'], observation['locale'])
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])
        self.assertFalse(data['policy']['formal_pool_installed'])

    def test_noncombo_real_play_needs_no_assembly_domain(self):
        game = self.game(hand=(CARD,), mode='missing'); before = game.snapshot()['rng_state']
        eid = self.play(game, CARD)
        self.assertEqual((game.state.entities[eid].attack, game.state.entities[eid].health), (3, 2))
        self.assertEqual(game.state.players[1].mana, 8)
        self.assertIsNone(game.state.pending_choice); self.assertEqual(game.snapshot()['rng_state'], before)
        self.portable(game, 'missing')

    def test_real_combo_pays_once_and_accepts_complete_other_class_primary(self):
        game = self.game(); eid = self.start(game); offer = self.offer(game)
        self.assertEqual(game.state.players[1].mana, 8)
        self.assertEqual(game.state.entities[eid].zone, Zone.BOARD)
        self.assertEqual(offer.spec.source_id, eid); self.assertEqual(offer.spec.primary_query, QUERY)
        self.assertEqual(offer.primary_candidates, (MAGE,)); self.assertEqual(offer.primary_card_id, MAGE)
        self.assertEqual(game.state.pending_choice.purpose, ChoicePurpose.ASSEMBLE)
        self.assertNotEqual(offer.rng_before, offer.rng_after)

    def test_other_class_primaries_include_all_declared_foreign_classes_but_no_neutral(self):
        members = (*MEMBERS, PALADIN); game = self.game(members=members)
        self.start(game); offer = self.offer(game)
        self.assertEqual(set(offer.primary_candidates), {MAGE, PALADIN})
        for cid in (FLY, HOARDER, BEAR): self.assertNotIn(cid, offer.primary_candidates)
        self.assertFalse(any(CardClass.ROGUE in game.registry.card(cid).metadata.classes
            for cid in offer.primary_candidates))

    def test_captured_current_hero_class_controls_other_relation_not_printed_rogue(self):
        members = (*MEMBERS, PALADIN); game = self.game(members=members, hero='HERO_08')
        self.start(game); offer = self.offer(game)
        self.assertEqual(offer.primary_candidates, (PALADIN,)); self.assertNotIn(MAGE, offer.primary_candidates)
        self.assertEqual(offer.before.players[1].hero_class, CardClass.MAGE)

    def test_secondary_keeps_explicit_existing_current_class_and_primary_cost_band_policy(self):
        game = self.game(); self.start(game); offer = self.offer(game)
        self.assertEqual(set(offer.secondary_candidates), {FLY, HOARDER})
        self.assertEqual(set(offer.secondary_card_ids), {FLY, HOARDER})
        self.assertNotIn(MAGE, offer.secondary_candidates); self.assertNotIn(BEAR, offer.secondary_candidates)
        self.assertEqual(offer.spec.small_policy, 'error'); self.assertEqual(offer.spec.keep_policy, 'forbid')

    def test_every_actual_half_restores_then_delivers_one_immutable_foreign_definition(self):
        game = self.game(); self.start(game); reader = self.portable(game)
        saved = reader.snapshot(); primary = game.registry.card(MAGE)
        for option in game.state.pending_choice.options:
            with self.subTest(option=option.id):
                restored = Game.from_snapshot(saved, reader.registry)
                restored.apply(SelectChoice(1, restored.state.pending_choice.id, (option.id,)))
                self.assertIsNone(restored.state.pending_choice)
                self.assertEqual(len(restored.state.players[1].hand), 1)
                received = restored.state.entities[restored.state.players[1].hand[0]]
                self.assertEqual(received.card_id, option.card_id)
                recipe = recipe_from_id(received.card_id)
                self.assertEqual(recipe.primary_card_id, MAGE)
                result = restored.registry.card(received.card_id)
                self.assertEqual((result.name, result.cost, result.attack, result.health, result.metadata),
                    (primary.name, primary.cost, primary.attack, primary.health, primary.metadata))
                self.assertEqual(restored.state.players[1].mana, 8)
                self.assertEqual(restored.snapshot()['rng_state'], saved['rng_state'])

    def test_selected_bottom_is_real_paid_deathrattle_and_not_primary_spell_generator(self):
        game = self.game(hand=(ZERO, CARD, KILL)); self.start(game); cid = self.choose(game, HOARDER, 'bottom')
        self.assertEqual(game.registry.card(cid).deathrattle, game.registry.card(HOARDER).deathrattle)
        eid = self.play(game, cid)
        self.assertEqual(game.state.players[1].mana, 7)
        self.assertEqual(len(game.state.players[1].deck), 12)
        self.play(game, KILL, eid)
        self.assertEqual([game.state.entities[i].card_id for i in game.state.players[1].hand], [ZERO])
        self.assertEqual(len(game.state.players[1].deck), 11)
        self.portable(game)

    def test_selected_top_is_real_battlecry_retaining_primary_payload(self):
        game = self.game(); self.start(game)
        cid = self.choose(game, FLY, 'top'); definition = game.registry.card(cid)
        self.assertIsNone(definition.deathrattle)
        self.assertEqual(definition.battlecry, game.registry.card(MAGE).deathrattle)
        self.play(game, cid)
        self.assertEqual([game.state.entities[i].card_id for i in game.state.players[1].hand], ['EX1_277'])
        self.assertEqual(game.state.players[1].mana, 7)
        self.portable(game)

    def test_waiting_independent_reader_clone_and_replay_resume_same_original_choice(self):
        game = self.game(); self.start(game); restored = self.portable(game)
        for value in (game, restored): self.choose(value, HOARDER, 'bottom')
        self.assertEqual(game.snapshot(), restored.snapshot()); self.portable(game)

    def test_missing_real_domain_never_falls_back_to_global_minions(self):
        game = self.game(mode='missing'); self.play(game, ZERO); before = game.snapshot()
        with self.assertRaises(ResolutionError): self.play(game, CARD)
        self.assertEqual(game.snapshot(), before)

    def test_unknown_or_unreviewed_eligible_foreign_candidate_rolls_back_whole_combo_play(self):
        for mode in ('unknown', 'unreviewed'):
            with self.subTest(mode=mode):
                game = self.game(mode=mode); self.play(game, ZERO); before = game.snapshot()
                with self.assertRaises(ResolutionError): self.play(game, CARD)
                self.assertEqual(game.snapshot(), before)

    def test_later_creation_failure_rolls_back_selection_to_original_paid_pending_offer(self):
        game = self.game(mode='fail'); self.start(game); before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Intentional selected-card creation failure'):
            self.choose(game, HOARDER, 'bottom')
        self.assertEqual(game.snapshot(), before); self.assertEqual(game.state.players[1].mana, 8)
        self.portable(game, 'fail')

    def test_other_class_declaration_requires_actual_source_and_explicit_neutral_exclusion(self):
        self.assertEqual(Assemble(1, POOL, 1, primary_query=QUERY).primary_query, QUERY)
        for kwargs in (dict(source_id=None), dict(primary_query=PoolQuery(class_mode='other'))):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(Assemble(1, POOL, 1, primary_query=QUERY), **kwargs)

    def test_accepted_offer_rejects_changed_class_source_inventory_and_random_receipt(self):
        game = self.game(); self.start(game); offer = self.offer(game)
        for kwargs in (dict(spec=replace(offer.spec, primary_query=PoolQuery(class_mode='current'))),
                dict(primary_candidates=(MAGE, PALADIN)), dict(secondary_candidates=(HOARDER,)),
                dict(rng_after=offer.rng_before)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                validate_offer(game.registry, CTX, replace(offer, **kwargs))

    def test_rehashed_saved_original_class_query_or_candidate_inventory_cannot_be_rewritten(self):
        game = self.game(); self.start(game); saved = game.snapshot()
        def objects(value):
            if isinstance(value, dict):
                yield value
                for item in value.values(): yield from objects(item)
            elif isinstance(value, list):
                for item in value: yield from objects(item)
        for change in ('class', 'neutral', 'inventory'):
            bad = deepcopy(saved); changed = 0
            for node in objects(bad):
                fields = node.get('fields', {})
                if change in ('class', 'neutral') and node.get('type', '').endswith('PoolQuery') and fields.get('class_mode') == 'other':
                    fields['class_mode' if change == 'class' else 'include_neutral'] = 'current' if change == 'class' else True
                    changed += 1
                elif change == 'inventory' and 'primary_candidates' in fields:
                    fields['primary_candidates'] = {'tuple': [MAGE, PALADIN]}; changed += 1
            self.assertGreater(changed, 0, change)
            bad['state_hash'] = canonical_hash({k:v for k,v in bad.items()
                if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
            with self.subTest(change=change), self.assertRaises(SnapshotError): Game.from_snapshot(bad, fixture())

    def test_current_player_legal_command_uses_original_options_while_private_proof_stays_hidden(self):
        game = self.game(); self.start(game); before = game.snapshot()
        for seat in (1, 2):
            public = json.dumps(game.for_player(seat).observe())+json.dumps(game.player_events(seat))
            for hidden in ('primary_candidates', 'secondary_candidates', 'rng_before', 'rng_after', 'assemble_templates'):
                self.assertNotIn(hidden, public)
        self.assertEqual(game.snapshot(), before)
        listing = game.for_player(1).legal_actions()
        action = next(a for a in listing['actions'] if a['type'] == 'select_choice')
        self.assertTrue(game.for_player(1).submit({'revision': listing['revision'], 'action': action})['accepted'])
        self.assertIsNone(game.state.pending_choice); self.portable(game)

    def test_wrong_player_or_unknown_half_does_not_consume_accepted_offer(self):
        game = self.game(); self.start(game); before = game.snapshot(); choice = game.state.pending_choice
        for command in (SelectChoice(2, choice.id, (choice.options[0].id,)), SelectChoice(1, choice.id, ('unknown',))):
            with self.subTest(command=command), self.assertRaises(IllegalAction): game.apply(command)
            self.assertEqual(game.snapshot(), before)


if __name__ == '__main__': unittest.main()
