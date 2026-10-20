"""Real entry adapters and reviewed fragments, using explicit experimental pools."""
from dataclasses import asdict
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_assemble_entry_cards import (CARETAKER, FETCHER, FLESH,
    FRAGMENT_SOURCES, NURTURER, POOL_ID, ROOTS, SHAPER, load_batch)
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, TargetSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe, recipe_from_id, validate_template
from hs_sim.engine.assemble_offers import ResolveAssemble
from hs_sim.engine.effects import CopyMinion, Damage, Destroy, ReturnToHand
from hs_sim.engine.model import CardClass, CardMetadata, ChoicePurpose
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face

COIN, RAVEN, FOX, FREYA = 'GAME_005', 'KAR_300', 'BE_859', 'BE_856'
FLY, HOARDER, MOSQUITO, PHOENIX, CAIRNE, DANCER = FRAGMENT_SOURCES[:5]+(FRAGMENT_SOURCES[-1],)
FOX_POOL = (FOX, FREYA, CAIRNE)
FLESH_POOL = (FOX, FREYA, MOSQUITO)
TARGET_POOL = (MOSQUITO, PHOENIX, CAIRNE)
CTX = GenerationContext('k329-explicit-reviewed-fixture', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
P = 'fixture.native_assemble_entries.'
KILL, RETURN, COPY, REVIVE, HURT = (P+x for x in ('kill', 'return', 'copy', 'revive', 'hurt'))


@lru_cache(maxsize=None)
def fixture(members=FRAGMENT_SOURCES, mode='normal'):
    registry = build_registry()
    bodies = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        RETURN: lambda c: (ReturnToHand(c.target_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        REVIVE: lambda c: (ResurrectMinion(c.player_id, c.state.death_history[-1].id, source_id=c.source_id),),
        HURT: lambda c: (Damage(c.state.players[c.player_id].hero_id, 12, c.source_id),),
    }
    for cid, body in bodies.items():
        registry.register_behavior(cid, body)
        target = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)) if cid in (KILL, RETURN, COPY) else None
        registry.register_card(CardDefinition(cid, 'Explicit test operation', CardType.SPELL,
            metadata=META, on_play=cid, targeting=target))
    if mode == 'normal':
        registry.register_pool(PoolDefinition(POOL_ID, 'explicit-reviewed-v1', CTX.target_id,
            CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    elif mode == 'ordinary_only':
        registry.register_pool(PoolDefinition('constructed.cards', 'explicit-ordinary-v1', CTX.target_id,
            CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    elif mode != 'missing':
        raise ValueError('Unknown test mode')
    return registry


class NativeAssembleEntryTests(unittest.TestCase):
    readers = {}

    def game(self, hand=(FETCHER,), members=FRAGMENT_SOURCES, mode='normal', paladin=False, seed=1):
        hero, power = ('HERO_04', 'HERO_04bp') if paladin else ('HERO_06', 'HERO_06bp')
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hero_power_card_id=power, hand=hand,
                deck=(COIN,)*12, max_mana=10, mana=10),
            PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp',
                deck=(COIN,)*12, max_mana=10, mana=10)), seed=seed, generation_context=CTX), fixture(members, mode))

    def play(self, game, cid, target=None):
        eid = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == cid)
        game.apply(PlayCard(1, eid, target_id=target)); return eid

    def offer(self, game):
        return next(effect.offer for option in game._frame.options for effect in option.effects
            if isinstance(effect, ResolveAssemble))

    def choose(self, game, donor=None, half=None):
        choice = game.state.pending_choice
        option = next(item for item in choice.options if donor is None or (
            recipe_from_id(item.card_id).secondary_card_id == donor and recipe_from_id(item.card_id).half == half))
        game.apply(SelectChoice(1, choice.id, (option.id,))); return option.card_id

    def portable(self, game, members=FRAGMENT_SOURCES, mode='normal'):
        key = (members, mode)
        if key not in self.readers: self.readers[key] = fixture.__wrapped__(*key)
        registry = self.readers[key]; saved = json.loads(json.dumps(game.snapshot()))
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(saved, registry).snapshot(), saved)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), saved)
        for seat in (1, 2):
            public = json.dumps(game.for_player(seat).observe())+json.dumps(game.player_events(seat))
            for hidden in ('"primary_candidates"', '"secondary_candidates"', '"rng_state"', '"rng_before"'):
                self.assertNotIn(hidden, public)
        return Game.from_snapshot(saved, registry)

    def coins(self, game):
        return sum(game.state.entities[i].card_id == COIN for i in game.state.players[1].hand)

    def test_five_complete_roots_nine_pinned_fragments_and_bilingual_main_faces(self):
        data = load_batch(); registry = fixture()
        rows = {row['record']['id']: row['record'] for row in data['cards']+data['existing_dependencies']}
        self.assertEqual(tuple(row['record']['id'] for row in data['cards']), ROOTS)
        self.assertEqual(len(data['official_observations']), 28)
        for row in data['cards']:
            raw = row['record']
            self.assertEqual(asdict(registry.card(raw['id']).metadata), asdict(metadata_from_record(raw)))
        # Existing Core faces retain their reviewed, shared deck identities.
        # Their entire definitions, including those identities, are pinned below.
        for row in data['existing_dependencies']:
            self.assertEqual(canonical_digest(asdict(registry.card(row['record']['id']))), row['definition_sha256'])
        for observation in data['official_observations']:
            check_face(rows[observation['card_id']], observation['face'], observation['locale'])

    def test_reviewed_halves_reconstruct_the_whole_original_and_do_not_install_a_formal_pool(self):
        registry = build_registry()
        self.assertEqual(tuple(cid for cid in registry.assemble_templates if cid in FRAGMENT_SOURCES), FRAGMENT_SOURCES)
        for template in registry.assemble_templates.values(): validate_template(registry, template)
        self.assertFalse(any(pool.id == POOL_ID for pool in registry.pools.values()))
        self.assertFalse(load_batch()['formal_pool_complete']); self.assertFalse(load_batch()['cn_calibrated'])

    def test_fetcher_real_payment_and_original_exact_four_cost_primary(self):
        game = self.game(); original = self.play(game, FETCHER); offer = self.offer(game)
        self.assertEqual(game.state.players[1].mana, 7)
        self.assertEqual(game.state.entities[original].zone, Zone.BOARD)
        self.assertEqual(offer.spec.source_id, original)
        self.assertEqual((offer.spec.primary_query.min_cost, offer.spec.primary_query.max_cost), (4, 4))
        self.assertTrue(all(game.registry.card(cid).cost == 4 for cid in offer.primary_candidates))
        self.assertEqual(game.state.pending_choice.purpose, ChoicePurpose.ASSEMBLE)
        self.assertEqual(game.state.players[1].hand, [])

    def test_nurturer_real_entry_constrains_only_the_one_cost_primary(self):
        game = self.game(hand=(NURTURER,)); self.play(game, NURTURER); offer = self.offer(game)
        self.assertEqual(offer.primary_card_id, FLY)
        self.assertEqual(offer.primary_candidates, (FLY,))
        self.assertEqual(set(offer.secondary_card_ids), {HOARDER, 'BE_855'})
        self.assertEqual(game.state.players[1].mana, 7)
        self.choose(game); self.assertIsNone(game.state.pending_choice)

    def test_caretaker_uses_original_beast_constraint_and_primary_cost_band(self):
        game = self.game(hand=(CARETAKER,)); self.play(game, CARETAKER); offer = self.offer(game)
        self.assertEqual(offer.spec.primary_query.tribes_any, ('beast',))
        for cid in offer.primary_candidates: self.assertIn('beast', game.registry.card(cid).metadata.tribes)
        cost = game.registry.card(offer.primary_card_id).cost
        self.assertTrue(all(cost <= game.registry.card(cid).cost <= cost+2 for cid in offer.secondary_candidates))
        self.assertEqual(game.state.players[1].mana, 8)

    def test_current_hero_class_filters_donors_even_for_another_class_source(self):
        game = self.game(hand=(FETCHER,), paladin=True); self.play(game, FETCHER); offer = self.offer(game)
        for cid in ('BE_855', FREYA, FOX):
            self.assertNotIn(cid, offer.primary_candidates); self.assertNotIn(cid, offer.secondary_candidates)
        foreign = self.game(hand=(CARETAKER,), paladin=True)
        self.play(foreign, CARETAKER); self.assertNotIn(FOX, self.offer(foreign).primary_candidates)

    def test_shaper_end_turn_primary_can_keep_its_prefix_and_replace_the_payload(self):
        game = self.game(hand=(SHAPER,), paladin=True); self.play(game, SHAPER); offer = self.offer(game)
        self.assertEqual(offer.primary_card_id, DANCER); self.assertEqual(offer.spec.primary_trait, 'end_turn')
        cid = self.choose(game, HOARDER, 'bottom'); definition = game.registry.card(cid)
        self.assertEqual((definition.cost, definition.attack, definition.health), (2, 2, 3))
        self.assertIsNone(definition.deathrattle); self.assertEqual(len(definition.triggers), 1)
        self.assertEqual(definition.triggers[0].behavior_id, game.registry.card(HOARDER).deathrattle)
        self.play(game, cid); before = self.coins(game); game.apply(EndTurn(1))
        self.assertEqual(self.coins(game), before+1)
        self.assertFalse(any(game.state.entities[i].card_id == 'BE_152t' for i in game.state.players[1].hand))
        self.portable(game)

    def test_flesh_waits_then_buffs_the_newly_delivered_card_and_other_hand_minions(self):
        game = self.game(hand=(FLESH, RAVEN), members=FLESH_POOL)
        raven = game.state.players[1].hand[1]; self.play(game, FLESH); offer = self.offer(game)
        self.assertEqual(offer.primary_card_id, FOX); self.assertEqual(offer.spec.primary_trait, 'deathrattle')
        self.assertEqual((game.state.entities[raven].attack, game.state.entities[raven].health), (2, 2))
        self.assertEqual(game.state.players[1].hand, [raven])
        cid = self.choose(game, FREYA, 'top'); new = game.state.entities[game.state.players[1].hand[-1]]
        self.assertEqual(new.card_id, cid); self.assertEqual((new.attack, new.health), (4, 6))
        self.assertEqual((game.state.entities[raven].attack, game.state.entities[raven].health), (4, 4))
        self.assertIsNotNone(game.registry.card(cid).battlecry)
        self.assertIsNone(game.registry.card(cid).deathrattle)
        self.assertEqual(game.state.players[1].mana, 7)
        self.play(game, cid); self.assertEqual(self.coins(game), 4)
        self.portable(game, FLESH_POOL)

    def test_flesh_pending_restore_keeps_original_choice_then_delivers_one_buff(self):
        game = self.game(hand=(FLESH, RAVEN), members=FLESH_POOL); self.play(game, FLESH)
        restored = self.portable(game, FLESH_POOL); rng = game.snapshot()['rng_state']
        self.choose(game, FREYA, 'top'); self.choose(restored, FREYA, 'top')
        self.assertEqual(game.snapshot(), restored.snapshot()); self.assertEqual(game.snapshot()['rng_state'], rng)
        self.assertEqual([game.state.entities[i].attack for i in game.state.players[1].hand], [4, 4])

    def test_real_pending_choices_resume_all_offered_halves_without_resampling(self):
        game = self.game(members=FOX_POOL); self.play(game, FETCHER); saved = self.portable(game, FOX_POOL).snapshot()
        for option in game.state.pending_choice.options:
            with self.subTest(option=option.id):
                restored = Game.from_snapshot(saved, self.readers[(FOX_POOL, 'normal')])
                restored.apply(SelectChoice(1, restored.state.pending_choice.id, (option.id,)))
                self.assertEqual(restored.state.entities[restored.state.players[1].hand[-1]].card_id, option.card_id)
                self.assertEqual(restored.snapshot()['rng_state'], saved['rng_state'])

    def test_top_replacement_uses_primary_current_attack_and_removes_old_taunt_deathrattle(self):
        game = self.game(members=FOX_POOL); self.play(game, FETCHER)
        cid = self.choose(game, FREYA, 'top'); card = game.registry.card(cid)
        self.assertEqual((card.cost, card.attack, card.health), (4, 2, 4))
        self.assertNotIn(Keyword.TAUNT, card.keywords); self.assertIsNone(card.deathrattle)
        self.play(game, cid); self.assertEqual(self.coins(game), 2)
        self.assertEqual(game.state.players[1].mana, 3)

    def test_return_and_paid_replay_keep_same_physical_recipe_without_old_deathrattle(self):
        game = self.game(hand=(FETCHER, RETURN), members=FOX_POOL); self.play(game, FETCHER)
        cid = self.choose(game, FREYA, 'top'); eid = self.play(game, cid)
        self.play(game, RETURN, eid); self.assertIn(eid, game.state.players[1].hand)
        self.assertEqual(game.state.entities[eid].card_id, cid)
        self.play(game, COIN); self.assertEqual(self.play(game, cid), eid)
        self.assertEqual(self.coins(game), 3); self.assertEqual(game.state.death_history, [])
        self.portable(game, FOX_POOL)

    def test_bottom_replacement_natural_death_and_real_resurrection_keep_new_printed_body(self):
        game = self.game(hand=(FETCHER, KILL, REVIVE, KILL), members=FOX_POOL); self.play(game, FETCHER)
        cid = self.choose(game, CAIRNE, 'bottom'); eid = self.play(game, cid)
        card = game.registry.card(cid)
        self.assertIn(Keyword.TAUNT, card.keywords)
        self.assertEqual(card.deathrattle, game.registry.card(CAIRNE).deathrattle)
        self.play(game, KILL, eid)
        self.assertEqual(game.state.death_history[-1].card_id, cid)
        babies = [i for i in game.state.players[1].board if game.state.entities[i].card_id != FETCHER]
        self.assertEqual([(game.state.entities[i].attack, game.state.entities[i].health) for i in babies], [(5, 5)])
        self.play(game, REVIVE)
        revived = next(i for i in game.state.players[1].board if game.state.entities[i].card_id == cid)
        self.assertNotEqual(revived, eid); self.assertEqual(game.state.entities[revived].attack, 2)
        self.portable(game, FOX_POOL); self.play(game, KILL, revived)
        self.assertEqual(len([i for i in game.state.players[1].board if game.state.entities[i].card_id != FETCHER]), 2)

    def test_base_copy_preserves_new_recipe_and_does_not_execute_its_battlecry(self):
        game = self.game(hand=(FETCHER, COPY), members=FOX_POOL); self.play(game, FETCHER)
        cid = self.choose(game, FREYA, 'top'); eid = self.play(game, cid)
        self.play(game, COPY, eid)
        copies = [game.state.entities[i] for i in game.state.players[1].board if game.state.entities[i].card_id == cid]
        self.assertEqual(len(copies), 2); self.assertEqual(self.coins(game), 2)
        self.assertEqual([(c.attack, c.health) for c in copies], [(2, 4), (2, 4)])
        self.portable(game, FOX_POOL)

    def test_targeted_transplanted_payload_requires_real_target_and_drops_original_heal(self):
        game = self.game(hand=(CARETAKER, HURT), members=TARGET_POOL)
        self.play(game, HURT); self.play(game, CARETAKER)
        self.assertEqual(self.offer(game).primary_card_id, MOSQUITO)
        cid = self.choose(game, PHOENIX, 'bottom'); saved = game.snapshot()
        with self.assertRaises(IllegalAction): self.play(game, cid)
        self.assertEqual(game.snapshot(), saved)
        enemy = game.state.players[2].hero_id; self.play(game, cid, enemy)
        self.assertEqual(game.state.entities[enemy].health, 27)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 18)
        self.portable(game, TARGET_POOL)

    def test_targeted_fragment_cannot_be_transplanted_to_deathrattle_or_end_turn(self):
        registry = fixture(); suffix = registry.assemble_templates[PHOENIX].suffix
        self.assertEqual(suffix.allowed_timings, ('battlecry',))
        for primary in (FOX, DANCER):
            with self.subTest(primary=primary), self.assertRaises((ValueError, ResolutionError)):
                registry.card(AssembleRecipe(primary, PHOENIX, 'bottom').card_id)

    def test_no_dedicated_pool_is_transactional_and_does_not_fall_back_to_ordinary_pool(self):
        for mode in ('missing', 'ordinary_only'):
            with self.subTest(mode=mode):
                game = self.game(mode=mode); saved = game.snapshot()
                with self.assertRaises(ResolutionError): self.play(game, FETCHER)
                self.assertEqual(game.snapshot(), saved)

    def test_unknown_eligible_fragment_is_not_pruned_from_primary_or_secondary_domain(self):
        for hand, members in (((CARETAKER,), (MOSQUITO, PHOENIX, 'BE_999')),
                ((FETCHER,), (*FOX_POOL, 'BE_999'))):
            with self.subTest(hand=hand):
                game = self.game(hand=hand, members=members); saved = game.snapshot()
                with self.assertRaises(ResolutionError): self.play(game, hand[0])
                self.assertEqual(game.snapshot(), saved)

    def test_invalid_pending_selection_keeps_paid_source_and_original_complete_offer(self):
        game = self.game(members=FOX_POOL); self.play(game, FETCHER); saved = game.snapshot()
        choice = game.state.pending_choice
        for player, selected in ((2, (choice.options[0].id,)), (1, ('keep',)), (1, ())):
            with self.subTest(player=player, selected=selected), self.assertRaises(IllegalAction):
                game.apply(SelectChoice(player, choice.id, selected))
            self.assertEqual(game.snapshot(), saved)

    def test_implicit_compilation_is_read_only_and_preserves_primary_metadata(self):
        game = self.game(members=FOX_POOL); self.play(game, FETCHER)
        count, fingerprint = len(game.registry.cards), game.registry.fingerprint()
        for option in game.state.pending_choice.options:
            card = game.registry.card(option.card_id)
            self.assertEqual(card.metadata, game.registry.card(FOX).metadata)
            self.assertEqual((card.name, card.kind), (game.registry.card(FOX).name, CardType.MINION))
        self.choose(game); self.assertEqual(len(game.registry.cards), count)
        self.assertEqual(game.registry.fingerprint(), fingerprint)
        self.portable(game, FOX_POOL)


if __name__ == '__main__': unittest.main()
