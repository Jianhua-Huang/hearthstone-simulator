"""Genn's actual hand form and starting-power fact, under explicit local windows."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_hand_parity_card import CARD, WORGEN, load_batch
from hs_sim.cards.upgraded_hero_power_cards import UPGRADES
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    IllegalAction, PlayCard, PlayerSetup, Registry, ResolutionError, Scenario, SelectChoice,
    SnapshotError, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.construction import DeckPolicy, DeckSpec, MatchSetup
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, InvokeBehavior, ModifyCost,
    ReplaceHeroPower, RequestChoice)
from hs_sim.engine.hand_parity import HandParityTransformProfile
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, CopyCard, DiscardCard, MoveCard

P = 'k217b.'
EVEN, ODD, ZERO, WATCH = (P+x for x in ('even', 'odd', 'zero', 'watch'))
CMD = P+'cmd.'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(None)
def registry(mode=None):
    from hs_sim.cards import build_registry
    r = build_registry(); r.register_behavior(P+'empty', lambda c: ())
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('Deliberate Genn rollback')))
    for cid, cost in ((EVEN, 2), (ODD, 3), (ZERO, 0)):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=cost, on_play=P+'empty', metadata=META))
    def reference(c, cid=CARD, zone=Zone.HAND):
        return CardReference.capture(next(c.state.entities[i] for i in getattr(c.state.players[c.player_id], zone.value)
            if c.state.entities[i].card_id == cid))
    scripts = {
        'add': lambda c: (AddToHand(c.player_id, CARD, c.source_id),),
        'zero': lambda c: (AddToHand(c.player_id, ZERO, c.source_id),),
        'discard_even': lambda c: (DiscardCard(reference(c, EVEN), c.source_id),),
        'hand': lambda c: (MoveCard(reference(c, zone=Zone.DECK), c.player_id, Zone.HAND, source_id=c.source_id),),
        'transfer': lambda c: (MoveCard(reference(c), 3-c.player_id, Zone.HAND, source_id=c.source_id),),
        'discount': lambda c: tuple(ModifyCost(i, CostSpec(set_to=2), c.source_id)
            for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == ODD),
        'decorate': lambda c: (BuffStoredCard(reference(c), 3, 4, c.source_id, cost=CostSpec(set_to=1)),),
        'copy': lambda c: (CopyCard(reference(c), c.player_id, mode='current', source_id=c.source_id),),
        'swap_other': lambda c: (ReplaceHeroPower(c.player_id, 'HERO_05bp'),),
        'swap_back': lambda c: (ReplaceHeroPower(c.player_id, 'HERO_08bp'),),
        'swap_special': lambda c: (ReplaceHeroPower(c.player_id, 'EX1_tk33'),),
    }
    for name, body in scripts.items():
        r.register_behavior(P+name, body)
        r.register_card(CardDefinition(CMD+name, name, CardType.SPELL, on_play=P+name, metadata=META))
    def watch(c):
        if c.event.player_id != c.player_id: return ()
        transform = c.event.kind == 'stored_card_transformed' and c.state.entities[c.event.target_id].card_id == WORGEN
        replace = c.event.kind == 'hero_power_replaced'
        if mode == 'fail_transform' and transform or mode == 'fail_replace' and replace:
            return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        if mode == 'wait_transform' and transform or mode == 'wait_replace' and replace:
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
        return ()
    behavior = P+'watch.'+str(mode); r.register_behavior(behavior, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('stored_card_transformed', behavior), TriggerSpec('hero_power_replaced', behavior))))
    r.validate(); return r


@lru_cache(None)
def independent_registry(mode=None):
    return registry.__wrapped__(mode)


class NativeHandParityTests(unittest.TestCase):
    def game(self, hand=(CARD, EVEN, ODD), board=(), deck=(ZERO,)*4, owner=1,
             power='HERO_08bp', additional=(), hero='HERO_08', mode=None, enemy_hand=()):
        self.owner, self.mode = owner, mode
        own = PlayerSetup(hero, hero_power_card_id=power, additional_hero_power_card_ids=additional,
            hand=hand, board=board, deck=deck, mana=30, max_mana=30, mana_cap=30)
        other = PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', hand=enemy_hand,
            deck=(ZERO,)*4, mana=30, max_mana=30, mana_cap=30)
        return Game.from_scenario(Scenario((own, other) if owner == 1 else (other, own),
            active_player=owner, seed=218), registry(mode))
    def ids(self, g, cid, zone='hand', player=None):
        return tuple(i for i in getattr(g.state.players[self.owner if player is None else player], zone)
            if g.state.entities[i].card_id == cid)
    def power(self, g):
        eid = g.state.players[self.owner].hero_power_id
        return None if eid is None else g.state.entities[eid]
    def hero(self, g, player): return g.state.entities[g.state.players[player].hero_id]
    def play(self, g, cid, index=0):
        source = self.ids(g, cid)[index]; g.apply(PlayCard(self.owner, source)); return source
    def use(self, g, target=None): g.apply(UseHeroPower(self.owner, self.power(g).id, target))
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        # Alternate two independently constructed immutable blueprints, rather
        # than rebuilding the entire content catalog at every checkpoint.
        primary, other = registry(self.mode), independent_registry(self.mode)
        r = other if g.registry is primary else primary
        self.assertIsNot(r, g.registry)
        restored = Game.from_snapshot(deepcopy(saved), r)
        self.assertEqual(restored.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe())
            for key in ('starting_hero_power_card_id', 'rng_state', 'hand_entry_id', 'submitted_cost'):
                self.assertNotIn(key, public)
        return restored
    def rehash(self, data):
        data['events_hash'] = canonical_hash(data['events'])
        data['state_hash'] = canonical_hash({k: v for k, v in data.items()
            if k not in ('schema_version', 'state_hash', 'events', 'events_hash')})
        return data

    def test_full_root_worgen_evidence_and_original_twenty_two_power_dependencies(self):
        data = load_batch(); r = registry()
        self.assertEqual((len(data['existing_dependencies']), len(data['official_observations'])), (22, 4))
        self.assertEqual((r.card(CARD).attack, r.card(CARD).health), (5, 4))
        self.assertEqual((r.card(WORGEN).cost, r.card(WORGEN).attack, r.card(WORGEN).health), (4, 6, 5))
        self.assertIsNone(r.card(CARD).battlecry); self.assertIsNotNone(r.card(WORGEN).battlecry)
        self.assertEqual(r.hand_parity_profiles[CARD].transformed_id, WORGEN)

    def test_coherent_initial_even_odd_zero_and_empty_other_hand_forms(self):
        for hand in ((CARD,), (CARD, EVEN, ZERO), (CARD, ODD, ODD)):
            g = self.game(hand); self.assertFalse(self.ids(g, CARD)); self.assertEqual(len(self.ids(g, WORGEN)), 1)
        g = self.game((CARD, EVEN, ODD)); self.assertEqual(len(self.ids(g, CARD)), 1); self.portable(g)

    def test_playing_last_opposite_parity_card_upgrades_same_physical_original_hand_slot(self):
        for owner in (1, 2):
            g = self.game(owner=owner); source = self.ids(g, CARD)[0]; entry = g.state.entities[source].hand_entry_id
            self.play(g, EVEN)
            self.assertEqual((g.state.entities[source].card_id, g.state.entities[source].hand_entry_id), (WORGEN, entry))
            self.assertEqual(g.state.players[owner].hand[0], source); self.assertEqual(g.state.players[owner].mana, 28)
            self.portable(g)

    def test_discard_and_generated_entry_use_actual_remaining_and_delivered_hand(self):
        g = self.game((CMD+'discard_even', CARD, EVEN, ODD)); self.play(g, CMD+'discard_even')
        self.assertEqual(len(self.ids(g, WORGEN)), 1); self.assertEqual(len(g.state.discard_history), 1)
        g = self.game((CMD+'add', EVEN)); self.play(g, CMD+'add')
        self.assertEqual(len(self.ids(g, WORGEN)), 1); self.portable(g)

    def test_current_cost_only_change_waits_for_next_actual_own_hand_change(self):
        g = self.game((CMD+'discount', CARD, EVEN, ODD)); self.play(g, CMD+'discount')
        self.assertEqual(len(self.ids(g, CARD)), 1)
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[self.ids(g, ODD)[0]]).amount, 2)
        g.apply(EndTurn(1)); self.assertEqual(len(self.ids(g, CARD)), 1)
        g = self.portable(g); g.apply(EndTurn(2))
        self.assertEqual(len(self.ids(g, WORGEN)), 1); self.portable(g)

    def test_transformation_keeps_local_stats_cost_and_granted_material(self):
        g = self.game((CMD+'decorate', CARD, EVEN, ODD)); self.play(g, CMD+'decorate')
        source = self.ids(g, CARD)[0]; self.play(g, ODD); entity = g.state.entities[source]
        self.assertEqual((entity.card_id, entity.attack, entity.health), (WORGEN, 9, 9))
        self.assertEqual(quote_cost(g.state, g.registry, entity).amount, 1); self.portable(g)

    def test_root_in_deck_does_not_transform_until_actual_hand_entry(self):
        g = self.game((CMD+'hand', EVEN), deck=(CARD, ZERO)); source = self.ids(g, CARD, 'deck')[0]
        self.assertEqual(g.state.entities[source].card_id, CARD); self.play(g, CMD+'hand')
        self.assertEqual(self.ids(g, WORGEN), (source,)); self.portable(g)

    def test_untransformed_board_root_never_acquires_worgen_battlecry(self):
        g = self.game(); source = self.play(g, CARD); self.play(g, EVEN)
        self.assertEqual(g.state.entities[source].card_id, CARD)
        self.assertEqual(self.power(g).card_id, 'HERO_08bp'); self.portable(g)

    def test_transferred_root_uses_actual_new_owner_hand(self):
        g = self.game((CMD+'transfer', CARD, EVEN, ODD), enemy_hand=(EVEN,))
        source = self.ids(g, CARD)[0]; self.play(g, CMD+'transfer')
        self.assertEqual(g.state.entities[source].controller, 2)
        self.assertEqual(self.ids(g, WORGEN, player=2), (source,)); self.portable(g)

    def test_current_copy_and_original_can_both_transform_without_extra_generated_replacement(self):
        g = self.game((CMD+'copy', CARD, EVEN, ODD)); self.play(g, CMD+'copy')
        sources = set(self.ids(g, CARD)); self.assertEqual(len(sources), 2); self.play(g, ODD)
        self.assertEqual(set(self.ids(g, WORGEN)), sources); self.portable(g)

    def test_all_accepted_sources_finish_before_first_private_wait_notification(self):
        g = self.game((CARD, CARD, EVEN, ODD), board=(WATCH,), mode='wait_transform'); self.play(g, ODD)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(len(self.ids(g, WORGEN)), 2)
        self.assertFalse(self.ids(g, CARD)); g = self.portable(g); self.choose(g)
        self.assertIsNotNone(g.state.pending_choice); self.choose(g); self.portable(g)

    def test_scenario_setup_retains_existing_constructed_only_suspend_guard(self):
        with self.assertRaisesRegex(ValueError, 'Only a constructed opening can suspend'):
            self.game((CARD, EVEN), board=(WATCH,), mode='wait_transform')

    def test_actual_constructed_opening_transforms_before_mulligan_and_preserves_initial_power_fact(self):
        self.owner, self.mode = 1, None; r = registry()
        policy = DeckPolicy(P+'opening', P+'experimental', 'experimental', (CARD, 'CS2_182'),
            deck_size=8, max_copies=7)
        deck = DeckSpec('HERO_08', 'HERO_08bp', CardClass.MAGE, (CARD,)+('CS2_182',)*7)
        g = Game.from_decks(MatchSetup((deck, deck), policy, 'GAME_005', seed=1, first_player=1), r)
        self.assertEqual(len(self.ids(g, WORGEN, player=2)), 1)
        self.assertTrue(all(p.starting_hero_power_card_id == 'HERO_08bp' for p in g.state.players.values()))
        g = self.portable(g)
        while g.state.pending_choice is not None:
            q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, ()))
        self.assertEqual(len(self.ids(g, WORGEN, player=2)), 1)
        self.assertTrue(all(p.starting_hero_power_card_id == 'HERO_08bp' for p in g.state.players.values()))
        self.portable(g)
        mixed_policy = DeckPolicy(P+'mixed-opening', P+'experimental', 'experimental',
            (CARD, 'CS2_182', 'EX1_287'), deck_size=8, max_copies=7)
        mixed_deck = DeckSpec('HERO_08', 'HERO_08bp', CardClass.MAGE, (CARD, 'EX1_287')+('CS2_182',)*6)
        mixed = Game.from_decks(MatchSetup((mixed_deck, mixed_deck), mixed_policy,
            'GAME_005', seed=0, first_player=1), r)
        self.assertEqual(len(self.ids(mixed, CARD, player=2)), 1)
        self.assertFalse(self.ids(mixed, WORGEN, player=2)); self.portable(mixed)

    def test_failed_transform_reaction_rolls_back_triggering_card_payment_hand_and_form(self):
        g = self.game(board=(WATCH,), mode='fail_transform'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, ODD)
        self.assertEqual(g.snapshot(), before)

    def test_worgen_upgrades_all_eleven_starting_types_with_one_cost_installation(self):
        for index, (base, upgraded) in enumerate(UPGRADES.items(), 1):
            g = self.game((WORGEN,), power=base, hero=f'HERO_{index:02}', owner=1+index%2)
            original = self.power(g).id; self.play(g, WORGEN)
            self.assertEqual(self.power(g).card_id, upgraded); self.assertNotEqual(self.power(g).id, original)
            self.assertEqual(quote_cost(g.state, g.registry, self.power(g)).amount, 1)
            self.assertEqual(g.state.players[self.owner].starting_hero_power_card_id, base)
            self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD)

    def test_first_upgrade_after_use_is_fresh_but_already_upgraded_second_battlecry_does_not_refresh(self):
        g = self.game((WORGEN, WORGEN)); enemy = self.hero(g, 2).id
        self.use(g, enemy); self.play(g, WORGEN); upgraded = self.power(g).id
        self.use(g, enemy); self.assertEqual(self.hero(g, 2).health, 27); self.play(g, WORGEN)
        self.assertEqual((self.power(g).id, self.power(g).uses_this_turn), (upgraded, 1))
        self.assertEqual(quote_cost(g.state, g.registry, self.power(g)).amount, 1)
        saved = g.snapshot()
        with self.assertRaises(IllegalAction): self.use(g, enemy)
        self.assertEqual(g.snapshot(), saved); self.portable(g)

    def test_initial_already_upgraded_face_lowers_same_entity_without_resetting_usage(self):
        g = self.game((WORGEN,), power='HERO_08bp2'); original = self.power(g).id
        self.use(g, self.hero(g, 2).id); self.play(g, WORGEN)
        self.assertEqual((self.power(g).id, self.power(g).uses_this_turn), (original, 1))
        self.assertEqual(quote_cost(g.state, g.registry, self.power(g)).amount, 1); self.portable(g)

    def test_replaced_and_other_class_stolen_basics_do_not_become_original_starting_type_after_restore(self):
        for replacement in ('swap_other', 'swap_special'):
            g = self.game((CMD+replacement, WORGEN)); self.play(g, CMD+replacement)
            current = self.power(g).id; g = self.portable(g); self.play(g, WORGEN)
            self.assertEqual(self.power(g).id, current)
            self.assertEqual(g.state.players[1].starting_hero_power_card_id, 'HERO_08bp')
            self.assertEqual(quote_cost(g.state, g.registry, self.power(g)).amount, 2); self.portable(g)

    def test_reacquired_same_starting_basic_type_can_upgrade_even_with_different_physical_id(self):
        g = self.game((CMD+'swap_other', CMD+'swap_back', WORGEN)); original = self.power(g).id
        self.play(g, CMD+'swap_other'); self.play(g, CMD+'swap_back'); self.assertNotEqual(self.power(g).id, original)
        self.play(g, WORGEN); self.assertEqual(self.power(g).card_id, 'HERO_08bp2'); self.portable(g)

    def test_no_initial_power_does_not_fabricate_upgrade_for_a_later_installation(self):
        g = self.game((CMD+'swap_back', WORGEN), power=None); self.play(g, CMD+'swap_back')
        original = self.power(g).id; self.play(g, WORGEN)
        self.assertIsNone(g.state.players[1].starting_hero_power_card_id)
        self.assertEqual(self.power(g).id, original); self.assertEqual(self.power(g).card_id, 'HERO_08bp'); self.portable(g)

    def test_additional_slots_are_preserved_outside_original_primary_upgrade(self):
        g = self.game((WORGEN,), additional=('HERO_01bp2',)); extra = g.state.players[1].additional_hero_power_ids[0]
        self.play(g, WORGEN); self.assertEqual(g.state.players[1].additional_hero_power_ids, [extra])
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[extra]).amount, 2); self.portable(g)

    def test_replacement_wait_restores_one_cost_installation_and_failed_choice_atomically(self):
        g = self.game((WORGEN,), board=(WATCH,), mode='wait_replace'); self.play(g, WORGEN)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(self.power(g).card_id, 'HERO_08bp2')
        self.assertEqual(quote_cost(g.state, g.registry, self.power(g)).amount, 1)
        g = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before); self.choose(g); self.portable(g)

    def test_failed_replacement_reaction_restores_battlecry_play_initial_fact_and_old_power(self):
        g = self.game((WORGEN,), board=(WATCH,), mode='fail_replace'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, WORGEN)
        self.assertEqual(g.snapshot(), before)

    def test_initial_power_fact_has_strict_wire_type_identity_and_schema(self):
        g = self.game()
        for value in (EVEN, '', 1, 'unknown.power'):
            saved = g.snapshot(); saved['state']['players']['1']['starting_hero_power_card_id'] = value
            with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(saved), registry())
        saved = g.snapshot(); del saved['state']['players']['1']['starting_hero_power_card_id']
        with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(saved), registry())
        self.assertGreaterEqual(SNAPSHOT_SCHEMA_VERSION, 411)
        saved = g.snapshot(); saved['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry())

    def test_profile_is_read_only_typed_and_rejects_duplicate_or_chained_sources(self):
        r = registry.__wrapped__()
        with self.assertRaises(TypeError): r.hand_parity_profiles[CARD] = HandParityTransformProfile(CARD, WORGEN)
        with self.assertRaises(ValueError): r.register_hand_parity_profile(HandParityTransformProfile(CARD, WORGEN))
        with self.assertRaises(ValueError): r.register_hand_parity_profile(HandParityTransformProfile(WORGEN, CARD))
        with self.assertRaises(ValueError): r.register_hand_parity_profile(HandParityTransformProfile(EVEN, WORGEN))
