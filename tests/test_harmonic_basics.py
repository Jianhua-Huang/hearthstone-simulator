"""Two existing progress stages express independent held-spell alternation."""
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, EndTurn, Game,
    HandProgressSpec, PlayCard, PlayerSetup, Rarity, ResolutionError, Scenario,
    SelectChoice, SpellSchool, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Draw, ModifyWeapon,
    RequestChoice, RevealHandCard)
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.model import DamageKind
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import deck, metadata, registry as opening_registry, setup

HARMONIC, DISSONANT, KNIFE = 'ETC_717', 'ETC_717t', 'CS2_082'
FORMS = (HARMONIC, DISSONANT)
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'data/support/harmonic-basics.json'
PIN = '5fe71867bb02ce6f77ea4fb0b9a342d424b33c61060a2d8e0f15303d32088dbc'


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN: raise ValueError('Complete Harmonic evidence changed')
    for row in raw['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original Harmonic record changed')
    return {row['id']: row['data'] for row in raw['records']}


def registry(scripts=(), *, bad_condition=False, end_probe=None, swap_probe=False):
    r = opening_registry(); rows = evidence()
    r.register_trigger_condition('harmonic.owner.end', (lambda c: 'invalid') if bad_condition else
        lambda c: c.event.player_id == c.player_id)
    for cid, other, damage, attack in ((HARMONIC, DISSONANT, 1, 3), (DISSONANT, HARMONIC, 3, 1)):
        def body(c, damage=damage, attack=attack):
            effects = (Damage(c.target_id, damage, c.source_id, DamageKind.SPELL),)
            weapon = c.state.players[c.player_id].weapon_id
            return effects if weapon is None else (*effects, ModifyWeapon(weapon, attack=attack, source_id=c.source_id))
        r.register_behavior('body.' + cid, body)
        r.register_card(CardDefinition(cid, rows[cid]['name'], CardType.SPELL, cost=rows[cid]['cost'],
            on_play='body.' + cid, targeting=TargetSpec(), spell_school=SpellSchool.SHADOW,
            hand_progress=HandProgressSpec('event', goal=1, upgrade_card_id=other,
                event='turn_ended', condition_id='harmonic.owner.end'),
            metadata=metadata(CardClass.ROGUE, collectible=cid == HARMONIC, rarity=Rarity.RARE)))
    row = rows[KNIFE]
    r.register_card(CardDefinition(KNIFE, row['name'], CardType.WEAPON, cost=row['cost'],
        attack=row['attack'], durability=row['health'],
        metadata=metadata(CardClass.ROGUE, collectible=False, rarity=Rarity.FREE)))
    # Explicit synthetic opening substrate, not an implementation of the real Rogue power.
    r.register_card(CardDefinition('probe.rogue.power', 'Synthetic Rogue power', CardType.HERO_POWER,
        cost=2, on_use='power', metadata=metadata(CardClass.ROGUE, collectible=False)))
    r.register_card(CardDefinition('probe.rogue.hero', 'Synthetic Rogue hero', CardType.HERO, health=30,
        initial_hero_power='probe.rogue.power', metadata=metadata(CardClass.ROGUE, collectible=False)))
    if end_probe is not None:
        def at_end(c):
            if c.event.player_id != c.player_id: return ()
            if end_probe == 'get': return (AddToHand(c.player_id, HARMONIC),)
            if end_probe == 'random': return (AddToDeck(c.player_id, 'card.1'),)
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),), c.source_id),)
        r.register_behavior('probe.end', at_end)
        r.register_card(CardDefinition('probe.end', 'Ordinary end fact probe', CardType.MINION, health=2,
            triggers=(TriggerSpec('turn_ended', 'probe.end'),), metadata=metadata()))
    if swap_probe:
        r.register_behavior('probe.swap', lambda c: (RequestChoice(c.player_id,
            (ChoiceOption('ok', 'Continue'),), c.source_id),))
        r.register_card(CardDefinition('probe.swap', 'Ordinary upgrade fact probe', CardType.MINION, health=2,
            triggers=(TriggerSpec('hand_card_upgraded', 'probe.swap'),), metadata=metadata()))
    for name, callback in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=metadata()))
    return r


class HarmonicTests(unittest.TestCase):
    def setUp(self): self.scripts = []; self.options = {}
    def script(self, name, callback): self.scripts.append((name, callback))
    def game(self, hand=(HARMONIC,), *, deck_cards=None, enemy_hand=(), board=(), weapon=None):
        cards = tuple(f'card.{i}' for i in range(1, 31)) if deck_cards is None else deck_cards
        return Game.from_scenario(Scenario((
            PlayerSetup('probe.rogue.hero', hand=hand, deck=cards, board=board,
                weapon_card_id=weapon, max_mana=10, mana=10),
            PlayerSetup('mage.hero', hand=enemy_hand, deck=tuple(f'card.{i}' for i in range(1, 31)),
                max_mana=10, mana=10)), seed=86), registry(self.scripts, **self.options))
    def entity(self, g, cid=None, player=1, zone=Zone.HAND):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone.value)
            if (cid is None and g.state.entities[i].card_id in FORMS) or g.state.entities[i].card_id == cid)
    def ref(self, c, cid=None, player=1, zone=Zone.HAND):
        return CardReference.capture(next(c.state.entities[i] for i in getattr(c.state.players[player], zone.value)
            if (cid is None and c.state.entities[i].card_id in FORMS) or c.state.entities[i].card_id == cid))
    def play(self, g, cid, target=None):
        source = self.entity(g, cid, g.state.active_player).id
        g.apply(PlayCard(g.state.active_player, source, target)); return source
    def round(self, g): g.apply(EndTurn(1)); g.apply(EndTurn(2))
    def progress(self, g, cid=None, player=1): return progress_ability(self.entity(g, cid, player))
    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(snap, registry(self.scripts, **self.options))
        self.assertEqual(restored.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, **self.options)).snapshot(), snap)
        return restored
    def select(self, g):
        pending = g.state.pending_choice
        g.apply(SelectChoice(pending.player_id, pending.id, ('ok',)))

    def test_complete_raw_two_forms_original_buffs_and_knife(self):
        rows = evidence(); self.assertEqual(set(rows), {HARMONIC, DISSONANT, 'ETC_717e', 'ETC_717te', KNIFE})
        self.assertEqual([rows[c]['cost'] for c in FORMS], [2, 2])
        self.assertEqual(rows[HARMONIC]['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'], rows[DISSONANT]['dbf_id'])
        self.assertIn('Swaps each turn', rows[HARMONIC]['text_en'])
        self.assertEqual((rows[KNIFE]['attack'], rows[KNIFE]['health']), (1, 2))

    def test_two_existing_stages_alternate_without_repeat_flag_or_new_module(self):
        r = registry(); r.freeze()
        for cid, other in ((HARMONIC, DISSONANT), (DISSONANT, HARMONIC)):
            spec = r.card(cid).hand_progress
            self.assertEqual((spec.kind, spec.goal, spec.event, spec.upgrade_card_id), ('event', 1, 'turn_ended', other))
            self.assertFalse(spec.repeat)
        self.assertEqual(r.mana_rank_families, {}); self.assertEqual(r.unidentified_families, {})

    def test_initial_current_faces_have_no_global_turn_parity_replacement(self):
        g = self.game(FORMS)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], list(FORMS))
        self.assertEqual([self.progress(g, c).progress_completions for c in FORMS], [0, 0]); self.portable(g)

    def test_owner_end_switches_once_and_preserves_physical_identity(self):
        g = self.game(); entity = self.entity(g); identity = self.progress(g).id; g.apply(EndTurn(1))
        result = self.entity(g)
        self.assertEqual((result.id, result.card_id, result.zone_epoch), (entity.id, DISSONANT, entity.zone_epoch+1))
        self.assertEqual((self.progress(g).id, self.progress(g).progress_completions), (identity, 1))
        self.assertEqual(sum(e.kind == 'hand_card_upgraded' for e in g.events), 1); self.portable(g)

    def test_opponent_end_does_not_switch_same_card_again(self):
        g = self.game(); g.apply(EndTurn(1)); entity = self.entity(g); g.apply(EndTurn(2))
        self.assertEqual((self.entity(g).card_id, self.entity(g).zone_epoch), (DISSONANT, entity.zone_epoch))
        self.assertEqual(self.progress(g).progress_completions, 1); self.portable(g)

    def test_both_players_use_separate_owner_end_windows(self):
        g = self.game(enemy_hand=(HARMONIC,)); g.apply(EndTurn(1))
        self.assertEqual((self.entity(g).card_id, self.entity(g, player=2).card_id), (DISSONANT, HARMONIC))
        g.apply(EndTurn(2)); self.assertEqual(self.entity(g, player=2).card_id, DISSONANT)
        self.assertEqual([self.progress(g, player=p).progress_completions for p in (1, 2)], [1, 1]); self.portable(g)

    def test_multiple_cycles_keep_one_chain_and_unique_actual_witnesses(self):
        g = self.game(); entity = self.entity(g); identity = self.progress(g).id
        for count in range(1, 5):
            self.round(g)
            self.assertEqual(self.entity(g).card_id, DISSONANT if count % 2 else HARMONIC)
            self.assertEqual((self.progress(g).id, self.progress(g).progress_completions), (identity, count))
        ability = self.progress(g)
        self.assertEqual(len(ability.progress_keys), len(set(ability.progress_keys)))
        self.assertEqual(ability.progress_units, (1,)*4); self.assertFalse(ability.consumed)
        self.assertEqual(self.entity(g).zone_epoch, entity.zone_epoch+4); self.portable(g)

    def test_deck_card_does_not_swap_or_gain_past_hand_progress(self):
        g = self.game((), deck_cards=('card.1', HARMONIC)); self.round(g)
        card = self.entity(g, HARMONIC, zone=Zone.DECK)
        self.assertEqual(progress_ability(card).progress_completions, 0); self.portable(g)

    def test_natural_start_draw_keeps_printed_face_until_next_owner_end(self):
        g = self.game(deck_cards=(HARMONIC, 'card.1')); self.round(g)
        held, drawn = [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id in FORMS]
        self.assertEqual((held.card_id, drawn.card_id), (DISSONANT, HARMONIC))
        self.assertEqual([progress_ability(e).progress_completions for e in (held, drawn)], [1, 0])
        g.apply(EndTurn(1))
        self.assertEqual([g.state.entities[e.id].card_id for e in (held, drawn)], [HARMONIC, DISSONANT]); self.portable(g)

    def test_fresh_acquisition_starts_current_printed_face_with_no_backfill(self):
        self.script('get', lambda c: (AddToHand(1, HARMONIC),))
        g = self.game(('get',)); self.round(g); self.play(g, 'get')
        self.assertEqual((self.entity(g).card_id, self.progress(g).progress_completions), (HARMONIC, 0))
        g.apply(EndTurn(1)); self.assertEqual(self.entity(g).card_id, DISSONANT); self.portable(g)

    def test_acquired_during_end_reactions_does_not_consume_earlier_captured_window(self):
        self.options['end_probe'] = 'get'; g = self.game((), board=('probe.end',)); g.apply(EndTurn(1))
        self.assertEqual((self.entity(g).card_id, self.progress(g).progress_completions), (HARMONIC, 0))
        g.apply(EndTurn(2)); g.apply(EndTurn(1))
        cards = [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id in FORMS]
        self.assertEqual([e.card_id for e in cards], [DISSONANT, HARMONIC]); self.portable(g)

    def test_leave_hand_pauses_current_face_and_preserves_earned_progress(self):
        self.script('away', lambda c: (MoveCard(self.ref(c), 1, Zone.DECK, position='bottom'),))
        g = self.game((HARMONIC, 'away')); self.round(g); entity = self.entity(g); self.play(g, 'away'); self.round(g)
        stored = g.state.entities[entity.id]
        self.assertEqual((stored.zone, stored.card_id, progress_ability(stored).progress_completions), (Zone.DECK, DISSONANT, 1))
        self.portable(g)

    def test_return_to_hand_resumes_only_at_a_new_owner_end(self):
        self.script('away', lambda c: (MoveCard(self.ref(c), 1, Zone.DECK, position='bottom'),))
        self.script('back', lambda c: (MoveCard(self.ref(c, zone=Zone.DECK), 1, Zone.HAND),))
        g = self.game((HARMONIC, 'away', 'back')); self.round(g); source = self.entity(g).id
        self.play(g, 'away'); self.round(g); self.play(g, 'back')
        self.assertEqual((self.entity(g).id, self.entity(g).card_id), (source, DISSONANT))
        g.apply(EndTurn(1)); self.assertEqual((self.entity(g).card_id, self.progress(g).progress_completions), (HARMONIC, 2))
        self.portable(g)

    def test_current_copy_preserves_face_and_progress_but_has_separate_chain_identity(self):
        self.script('copy', lambda c: (CopyCard(self.ref(c), 1),))
        g = self.game((HARMONIC, 'copy')); self.round(g); self.play(g, 'copy')
        cards = [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id in FORMS]
        self.assertEqual([e.card_id for e in cards], [DISSONANT]*2)
        self.assertEqual([progress_ability(e).progress_completions for e in cards], [1, 1])
        self.assertEqual(len({progress_ability(e).id for e in cards}), 2)
        g.apply(EndTurn(1)); self.assertEqual([g.state.entities[e.id].card_id for e in cards], [HARMONIC]*2); self.portable(g)

    def test_base_copy_uses_current_printed_face_with_fresh_progress(self):
        self.script('copy', lambda c: (CopyCard(self.ref(c), 1, mode='base'),))
        g = self.game((HARMONIC, 'copy')); self.round(g); self.play(g, 'copy')
        cards = [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id in FORMS]
        self.assertEqual([e.card_id for e in cards], [DISSONANT]*2)
        self.assertEqual([progress_ability(e).progress_completions for e in cards], [1, 0]); self.portable(g)

    def test_local_creation_discount_survives_each_face_change(self):
        self.script('get', lambda c: (AddToHand(1, HARMONIC, cost=CostSpec(delta=-1)),))
        g = self.game(('get',)); self.play(g, 'get')
        for count in range(3):
            entity = self.entity(g)
            self.assertEqual(quote_unselected_cost(g.state, g.registry, entity).amount, 1)
            if count < 2: self.round(g)
        self.portable(g)

    def test_base_copy_resets_discount_without_reverting_selected_face(self):
        self.script('get', lambda c: (AddToHand(1, HARMONIC, cost=CostSpec(delta=-1)),))
        self.script('copy', lambda c: (CopyCard(self.ref(c), 1, mode='base'),))
        g = self.game(('get', 'copy')); self.play(g, 'get'); self.round(g); self.play(g, 'copy')
        cards = [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id in FORMS]
        self.assertEqual([e.card_id for e in cards], [DISSONANT]*2)
        self.assertEqual([quote_unselected_cost(g.state, g.registry, e).amount for e in cards], [1, 2]); self.portable(g)

    def test_transfer_uses_new_holder_without_immediate_swap(self):
        self.script('move', lambda c: (MoveCard(self.ref(c), 2, Zone.HAND),))
        g = self.game((HARMONIC, 'move')); source = self.entity(g).id; self.play(g, 'move'); g.apply(EndTurn(1))
        self.assertEqual((self.entity(g, player=2).id, self.entity(g, player=2).card_id), (source, HARMONIC))
        g.apply(EndTurn(2)); self.assertEqual(self.entity(g, player=2).card_id, DISSONANT); self.portable(g)

    def test_both_real_bodies_use_actual_numbers_and_existing_weapon_modifier(self):
        for cid, damage, attack in ((HARMONIC, 1, 3), (DISSONANT, 3, 1)):
            with self.subTest(form=cid):
                g = self.game((cid,), weapon=KNIFE); target = g.state.players[2].hero_id
                source = self.play(g, cid, target); weapon = g.state.entities[g.state.players[1].weapon_id]
                self.assertEqual(g.state.entities[target].health, 30-damage)
                self.assertEqual((weapon.attack, weapon.durability), (1+attack, 2))
                self.assertEqual(g.state.players[1].mana, 8)
                self.assertEqual((g.state.play_history[-1].source_id, g.state.play_history[-1].card_id), (source, cid))
                self.portable(g)

    def test_no_weapon_still_executes_real_damage_body(self):
        g = self.game(); target = g.state.players[2].hero_id; self.play(g, HARMONIC, target)
        self.assertEqual(g.state.entities[target].health, 29); self.assertIsNone(g.state.players[1].weapon_id); self.portable(g)

    def test_played_card_in_graveyard_does_not_continue_swapping(self):
        g = self.game(); source = self.play(g, HARMONIC, g.state.players[2].hero_id); self.round(g)
        card = g.state.entities[source]
        self.assertEqual((card.zone, card.card_id), (Zone.GRAVEYARD, HARMONIC)); self.portable(g)

    def test_waiting_before_hand_listener_restores_same_single_swap(self):
        self.options['end_probe'] = 'wait'; g = self.game(board=('probe.end',)); g.apply(EndTurn(1))
        self.assertEqual(self.entity(g).card_id, HARMONIC); restored = self.portable(g)
        for instance in (g, restored):
            self.select(instance); self.assertEqual((self.entity(instance).card_id, self.progress(instance).progress_completions), (DISSONANT, 1))
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_waiting_after_swap_restores_result_without_second_completion(self):
        self.options['swap_probe'] = True; g = self.game(board=('probe.swap',)); g.apply(EndTurn(1))
        self.assertEqual(self.entity(g).card_id, DISSONANT); restored = self.portable(g)
        for instance in (g, restored):
            self.select(instance); self.assertEqual(self.progress(instance).progress_completions, 1)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_invalid_condition_rolls_back_prior_random_reaction_face_clock_and_information(self):
        self.options.update(bad_condition=True, end_probe='random')
        g = self.game(board=('probe.end',)); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'condition must return bool'): g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_owner_observes_face_and_public_progress_without_private_chain_fields(self):
        g = self.game(); g.apply(EndTurn(1)); own = g.observe(1)['players'][0]['hand'][0]
        self.assertEqual(own['card_id'], DISSONANT)
        self.assertEqual(own['hand_progress']['completions'], 1)
        self.assertIsNone(g.observe(2)['players'][0]['hand'][0]['card_id'])
        for viewer in (1, 2):
            text = json.dumps(g.observe(viewer))
            for private in ('progress_keys', 'progress_units', 'hand_entries', 'zone_epoch', 'rng_state'):
                self.assertNotIn(private, text)
        self.portable(g)

    def test_face_change_hides_previously_revealed_identity(self):
        self.script('reveal', lambda c: (RevealHandCard(self.ref(c).entity_id),))
        g = self.game((HARMONIC, 'reveal')); self.play(g, 'reveal')
        self.assertEqual(g.observe(2)['players'][0]['hand'][0]['card_id'], HARMONIC)
        g.apply(EndTurn(1)); self.assertIsNone(g.observe(2)['players'][0]['hand'][0]['card_id']); self.portable(g)

    def test_opening_kept_face_does_not_swap_during_mulligan_or_first_start(self):
        r = registry(); cards = tuple(HARMONIC if i == 1 else f'card.{i}' for i in range(1, 31))
        from hs_sim.engine import DeckSpec
        import random
        for seed in range(1000):
            order = list(cards); random.Random(seed).shuffle(order)
            if HARMONIC in order[:3]: break
        rogue = DeckSpec('probe.rogue.hero', 'probe.rogue.power', CardClass.ROGUE, cards)
        g = Game.from_decks(setup(r, seed=seed, decks=(rogue, deck())), r)
        kept = self.entity(g, HARMONIC).id
        while g.state.pending_choice is not None:
            self.portable(g); choice = g.state.pending_choice
            g.apply(SelectChoice(choice.player_id, choice.id, ()))
        entity = g.state.entities[kept]
        self.assertEqual((entity.zone, entity.card_id, progress_ability(entity).progress_completions), (Zone.HAND, HARMONIC, 0))
        self.portable(g)

    def test_incomplete_cycle_form_is_explicitly_rejected(self):
        from dataclasses import replace
        r = registry(); r._cards[HARMONIC] = replace(r.card(HARMONIC), hand_progress=
            HandProgressSpec('event', 1, upgrade_card_id='missing.form', event='turn_ended'))
        with self.assertRaises(ValueError): r.freeze()
