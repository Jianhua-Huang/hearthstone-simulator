"""Ranked spells: actual crystal changes, stored lifecycle, and boundary evidence."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, EndTurn, Game,
    ManaRankFamily, PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice,
    SnapshotError, TargetSpec, TriggerSpec, Zone, rank_for_maximum)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddToHand, ChangeManaCrystals, ChoiceOption, Damage,
    Draw, GainTemporaryMana, ModifyCost, Overload, RequestChoice, RevealHandCard, SetManaCap)
from hs_sim.engine.model import DamageKind
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

FORMS = ('BAR_319', 'BAR_319t', 'BAR_319t2')
FAMILY = ManaRankFamily('wicked-stab-ranks-v1', FORMS)
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'data/support/mana-ranks.json'
PIN = '6867d77c0b413778273c5f756bb99cd029d6ea41847b24ea0b7444a5350876cb'


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN:
        raise ValueError('Complete Ranked-spell evidence changed')
    for row in raw['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original Ranked-spell record changed')
    return {row['id']: row['data'] for row in raw['records']}


def registry(scripts=(), *, enabled=True, watcher=False):
    r = opening_registry(); rows = evidence()
    for stage, cid in enumerate(FORMS):
        row = rows[cid]
        r.register_behavior('body.' + cid, lambda c, amount=(stage+1)*2:
            (Damage(c.target_id, amount, c.source_id, DamageKind.SPELL),))
        r.register_card(CardDefinition(cid, row['name'], CardType.SPELL, cost=row['cost'],
            on_play='body.' + cid, targeting=TargetSpec(),
            metadata=metadata(CardClass.ROGUE, collectible=stage == 0)))
    if enabled:
        r.register_mana_rank_family(FAMILY)
    if watcher:
        r.register_behavior('watch', lambda c: (Damage(c.state.players[2].hero_id,
            FORMS.index(next(c.state.entities[i].card_id for i in c.state.players[1].hand
                if c.state.entities[i].card_id in FORMS))+1, c.source_id),))
        r.register_card(CardDefinition('probe.watch', 'Rank at crystal fact probe', CardType.MINION, health=8,
            triggers=(TriggerSpec('mana_changed', 'watch'),), metadata=metadata()))
    for name, callback, cost in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=cost, on_play=name, metadata=metadata()))
    return r


class ManaRankTests(unittest.TestCase):
    def setUp(self): self.scripts = []; self.options = {}
    def script(self, name, callback, cost=0): self.scripts.append((name, callback, cost))
    def crystal(self, name='gain', amount=1, player=1, filled=False):
        self.script(name, lambda c: (ChangeManaCrystals(player, amount, filled),))
    def game(self, hand=(FORMS[0],), *, deck=(), maximum=4, mana=None, enemy_maximum=4,
             enemy_hand=(), enemy_deck=(), board=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, deck=deck, board=board, max_mana=maximum,
                mana=maximum if mana is None else mana),
            PlayerSetup('warrior.hero', hand=enemy_hand, deck=enemy_deck, max_mana=enemy_maximum,
                mana=enemy_maximum)), seed=86), registry(self.scripts, **self.options))
    def entity(self, g, cid, player=1, zone=Zone.HAND):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone.value)
            if g.state.entities[i].card_id == cid)
    def play(self, g, cid, target=None):
        p = g.state.active_player; source = self.entity(g, cid, p).id
        g.apply(PlayCard(p, source, target)); return source
    def ref(self, c, cid, zone=Zone.HAND):
        return CardReference.capture(next(c.state.entities[i] for i in getattr(c.state.players[1], zone.value)
            if c.state.entities[i].card_id == cid))
    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(snap, registry(self.scripts, **self.options))
        self.assertEqual(restored.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, **self.options)).snapshot(), snap)
        return restored

    def test_fixed_thresholds_and_invalid_maximum_values(self):
        self.assertEqual([rank_for_maximum(n) for n in (0, 4, 5, 9, 10, 16)], [0, 0, 1, 1, 2, 2])
        for value in (-1, True, 5.0, '5'):
            with self.subTest(value=value), self.assertRaises(ValueError): rank_for_maximum(value)

    def test_complete_three_raw_forms_and_real_body_values(self):
        rows = evidence(); self.assertEqual(tuple(rows), FORMS)
        self.assertIn('5 Mana', rows[FORMS[0]]['text_en'])
        self.assertIn('10 Mana', rows[FORMS[1]]['text_en'])
        self.assertEqual([rows[c]['cost'] for c in FORMS], [2, 2, 2])
        for maximum, stage in ((4, 0), (5, 1), (10, 2)):
            with self.subTest(maximum=maximum):
                g = self.game(maximum=maximum); target = g.state.players[2].hero_id
                self.play(g, FORMS[stage], target)
                self.assertEqual(g.state.entities[target].health, 30-(stage+1)*2)
                self.assertEqual(g.state.play_history[-1].card_id, FORMS[stage]); self.portable(g)

    def test_initial_hand_and_deck_rank_at_each_boundary(self):
        for maximum, expected in ((0, 0), (4, 0), (5, 1), (9, 1), (10, 2)):
            with self.subTest(maximum=maximum):
                g = self.game(deck=(FORMS[0],), maximum=maximum)
                self.assertIsNotNone(self.entity(g, FORMS[expected]))
                self.assertIsNotNone(self.entity(g, FORMS[expected], zone=Zone.DECK)); self.portable(g)

    def test_empty_crystal_growth_upgrades_hand_and_deck(self):
        self.crystal(); g = self.game((FORMS[0], 'gain'), deck=(FORMS[0],))
        source = self.entity(g, FORMS[0]).id; self.play(g, 'gain')
        self.assertEqual(g.state.players[1].max_mana, 5)
        self.assertEqual((g.state.entities[source].card_id, self.entity(g, FORMS[1], zone=Zone.DECK).base_cost),
            (FORMS[1], 2)); self.portable(g)

    def test_jump_from_four_to_ten_selects_final_form_once(self):
        self.crystal(amount=6); g = self.game((FORMS[0], 'gain'), deck=(FORMS[0],))
        old = self.entity(g, FORMS[0]); source, epoch = old.id, old.zone_epoch
        self.play(g, 'gain')
        self.assertEqual((g.state.entities[source].card_id, g.state.entities[source].zone_epoch), (FORMS[2], epoch+1))
        self.assertIsNotNone(self.entity(g, FORMS[2], zone=Zone.DECK)); self.portable(g)

    def test_rank_uses_maximum_not_available_mana(self):
        g = self.game(maximum=5, mana=0)
        self.assertIsNotNone(self.entity(g, FORMS[1]))
        g = self.game(maximum=10, mana=0)
        self.assertIsNotNone(self.entity(g, FORMS[2]))

    def test_temporary_available_mana_above_five_does_not_rank(self):
        self.script('temp', lambda c: (GainTemporaryMana(1, 3),))
        g = self.game((FORMS[0], 'temp')); self.play(g, 'temp')
        self.assertEqual(g.state.players[1].mana, 7)
        self.assertIsNotNone(self.entity(g, FORMS[0])); self.portable(g)

    def test_overload_does_not_reduce_rank_from_maximum(self):
        self.script('lock', lambda c: (Overload(1, 4),))
        g = self.game((FORMS[0], 'lock'), maximum=5); self.play(g, 'lock')
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(g.state.players[1].overload_locked, 4)
        self.assertIsNotNone(self.entity(g, FORMS[1])); self.portable(g)

    def test_crystal_loss_does_not_downgrade_current_face(self):
        self.crystal('lose', -6); g = self.game((FORMS[0], 'lose'), maximum=10)
        self.play(g, 'lose'); self.assertEqual(g.state.players[1].max_mana, 4)
        self.assertIsNotNone(self.entity(g, FORMS[2])); self.portable(g)

    def test_lower_mana_cap_does_not_downgrade(self):
        self.script('cap', lambda c: (SetManaCap(1, 3),))
        g = self.game((FORMS[0], 'cap'), maximum=10); self.play(g, 'cap')
        self.assertEqual(g.state.players[1].max_mana, 3)
        self.assertIsNotNone(self.entity(g, FORMS[2]))

    def test_each_players_stored_cards_use_their_own_maximum(self):
        g = self.game(maximum=5, enemy_maximum=10, enemy_hand=(FORMS[0],), enemy_deck=(FORMS[0],))
        self.assertIsNotNone(self.entity(g, FORMS[1]))
        self.assertIsNotNone(self.entity(g, FORMS[2], 2))
        self.assertIsNotNone(self.entity(g, FORMS[2], 2, Zone.DECK)); self.portable(g)

    def test_normal_turn_growth_ranks_both_stored_zones_before_draw(self):
        g = self.game(deck=(FORMS[0],)); source = self.entity(g, FORMS[0], zone=Zone.DECK).id
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(g.state.players[1].max_mana, 5)
        self.assertEqual((g.state.entities[source].card_id, g.state.entities[source].zone), (FORMS[1], Zone.HAND))
        self.assertTrue(all(g.state.entities[i].card_id == FORMS[1] for i in g.state.players[1].hand)); self.portable(g)

    def test_new_hand_acquisition_at_ten_ranks_before_reactions(self):
        self.script('add', lambda c: (AddToHand(1, FORMS[0]),))
        g = self.game(('add',), maximum=10); self.play(g, 'add')
        self.assertIsNotNone(self.entity(g, FORMS[2])); self.portable(g)

    def test_new_deck_acquisition_at_ten_uses_the_same_threshold(self):
        self.script('add', lambda c: (AddToDeck(1, FORMS[0], position='bottom'),))
        g = self.game(('add',), maximum=10); self.play(g, 'add')
        self.assertIsNotNone(self.entity(g, FORMS[2], zone=Zone.DECK)); self.portable(g)

    def test_drawing_a_ranked_physical_card_preserves_its_identity(self):
        self.script('draw', lambda c: (Draw(1, source_id=c.source_id),))
        g = self.game(('draw',), deck=(FORMS[0],), maximum=10)
        source = self.entity(g, FORMS[2], zone=Zone.DECK).id; self.play(g, 'draw')
        self.assertEqual(self.entity(g, FORMS[2]).id, source); self.portable(g)

    def test_transfer_uses_new_holder_maximum_and_preserves_physical_owner(self):
        self.script('give', lambda c: (MoveCard(self.ref(c, FORMS[0]), 2, Zone.HAND),))
        g = self.game((FORMS[0], 'give'), enemy_maximum=10); source = self.entity(g, FORMS[0]).id
        self.play(g, 'give'); entity = g.state.entities[source]
        self.assertEqual((entity.card_id, entity.owner, entity.controller), (FORMS[2], 1, 2)); self.portable(g)

    def test_current_and_base_copies_are_ranked_after_materialization(self):
        self.script('copy', lambda c: (CopyCard(self.ref(c, FORMS[0]), 2, mode='current'),
            CopyCard(self.ref(c, FORMS[0]), 2, mode='base')))
        g = self.game((FORMS[0], 'copy'), enemy_maximum=10); self.play(g, 'copy')
        copies = [g.state.entities[i] for i in g.state.players[2].hand]
        self.assertEqual([e.card_id for e in copies], [FORMS[2], FORMS[2]])
        self.assertTrue(all(next(a for a in e.abilities if a.kind == 'on_play').behavior_id ==
            'body.' + FORMS[2] for e in copies)); self.portable(g)

    def test_discarded_card_stays_unranked_and_fresh_acquisition_ranks(self):
        from hs_sim.engine.zones import DiscardCard
        self.script('away', lambda c: (DiscardCard(self.ref(c, FORMS[0])),))
        self.crystal(amount=6)
        self.script('fresh', lambda c: (AddToHand(1, FORMS[0]),))
        g = self.game((FORMS[0], 'away', 'gain', 'fresh')); source = self.entity(g, FORMS[0]).id
        self.play(g, 'away'); self.play(g, 'gain')
        self.assertEqual((g.state.entities[source].card_id, g.state.entities[source].zone), (FORMS[0], Zone.GRAVEYARD))
        self.play(g, 'fresh'); self.assertNotEqual(self.entity(g, FORMS[2]).id, source); self.portable(g)

    def test_committed_spell_does_not_rank_in_play_or_graveyard(self):
        self.crystal(amount=6); g = self.game((FORMS[0], 'gain'))
        source = self.play(g, FORMS[0], g.state.players[2].hero_id); self.play(g, 'gain')
        self.assertEqual((g.state.entities[source].zone, g.state.entities[source].card_id), (Zone.GRAVEYARD, FORMS[0]))
        self.assertEqual(g.state.play_history[0].played_face.card_id, FORMS[0]); self.portable(g)

    def test_upgrading_preserves_local_cost_adjustment(self):
        self.script('discount', lambda c: (ModifyCost(self.ref(c, FORMS[0]).entity_id, CostSpec(delta=-1)),))
        self.crystal(); g = self.game((FORMS[0], 'discount', 'gain')); self.play(g, 'discount')
        source = self.entity(g, FORMS[0]).id; self.play(g, 'gain'); entity = self.entity(g, FORMS[1])
        self.assertEqual((entity.id, quote_unselected_cost(g.state, g.registry, entity).amount), (source, 1))
        self.portable(g)

    def test_old_captured_reference_is_stale_after_rank_change(self):
        self.script('stale', lambda c: (ChangeManaCrystals(1, 1),
            MoveCard(self.ref(c, FORMS[0]), 1, Zone.DECK)))
        g = self.game((FORMS[0], 'stale')); self.play(g, 'stale')
        self.assertIsNotNone(self.entity(g, FORMS[1])); self.assertEqual(g.state.players[1].deck, [])

    def test_reactions_to_crystal_fact_already_see_ranked_face(self):
        self.crystal(amount=6); self.options['watcher'] = True
        g = self.game((FORMS[0], 'gain'), board=('probe.watch',)); self.play(g, 'gain')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27); self.portable(g)

    def test_waiting_restore_and_replay_rank_once_on_choice_resume(self):
        self.script('choice', lambda c: (RequestChoice(1,
            (ChoiceOption('gain', 'Gain crystals', (ChangeManaCrystals(1, 6),)),), c.source_id),))
        g = self.game((FORMS[0], 'choice')); self.play(g, 'choice')
        restored = self.portable(g)
        for instance in (g, restored):
            instance.apply(SelectChoice(1, instance.state.pending_choice.id, ('gain',)))
            self.assertIsNotNone(self.entity(instance, FORMS[2]))
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_failed_action_rolls_back_crystals_face_epoch_and_information(self):
        self.script('bad', lambda c: (ChangeManaCrystals(1, 6), AddToHand(1, 'missing.card')))
        g = self.game((FORMS[0], 'bad')); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'bad')
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_repeated_unrelated_events_do_not_upgrade_again(self):
        self.crystal(); self.script('noop', lambda c: ())
        g = self.game((FORMS[0], 'gain', 'noop')); self.play(g, 'gain')
        before = self.entity(g, FORMS[1]).zone_epoch; self.play(g, 'noop')
        self.assertEqual(self.entity(g, FORMS[1]).zone_epoch, before)

    def test_owner_observes_new_hand_face_and_opponent_sees_no_identity(self):
        self.crystal(); g = self.game((FORMS[0], 'gain')); self.play(g, 'gain')
        self.assertEqual(g.observe(1)['players'][0]['hand'][0]['card_id'], FORMS[1])
        self.assertIsNone(g.observe(2)['players'][0]['hand'][0]['card_id'])
        for viewer in (1, 2):
            self.assertNotIn('mana_rank_families', json.dumps(g.observe(viewer)))
            self.assertNotIn('zone_epoch', json.dumps(g.observe(viewer)))

    def test_rank_change_conceals_previously_revealed_hand_identity(self):
        self.script('reveal', lambda c: (RevealHandCard(self.ref(c, FORMS[0]).entity_id),))
        self.crystal(); g = self.game((FORMS[0], 'reveal', 'gain')); self.play(g, 'reveal'); self.play(g, 'gain')
        self.assertIsNone(g.observe(2)['players'][0]['hand'][0]['card_id']); self.portable(g)

    def test_restore_rejects_an_unsettled_face_without_repair(self):
        g = self.game(); g._state.players[1].max_mana = 5
        g._state.players[1].mana_spent = 1  # Leave the same available balance.
        malformed = g.snapshot()
        with self.assertRaisesRegex(SnapshotError, 'Unsettled mana rank'):
            Game.from_snapshot(malformed, registry())

    def test_empty_profile_preserves_existing_registry_fingerprints(self):
        from hs_sim.engine.representative import build_registry
        # The 2026-10-10 historical baseline remains archived; assert current unchanged fixtures.
        self.assertEqual(opening_registry().fingerprint(), 'e2a56b63d48cf1e07a587ade4a9d7bc67cedfdecd1d692ca82a0040113b2f7e5')
        default = build_registry()
        self.assertEqual((default.version, len(default.cards)), ('representative-m5-v65', 311))
        self.assertEqual(default.fingerprint(), 'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')
        self.assertEqual(default_mechanics().version, CORE_EFFECTS_VERSION)

    def test_opt_in_profile_changes_fingerprint_and_is_frozen(self):
        enabled = registry(); disabled = registry(enabled=False)
        self.assertNotEqual(enabled.fingerprint(), disabled.fingerprint())
        enabled.freeze()
        with self.assertRaisesRegex(ValueError, 'frozen'):
            enabled.register_mana_rank_family(ManaRankFamily('new', ('x', 'y', 'z')))
        with self.assertRaises(TypeError): enabled.mana_rank_families['new'] = FAMILY

    def test_invalid_and_duplicate_families_are_rejected(self):
        for forms in (['a', 'b', 'c'], ('a', 'b'), ('a', 'a', 'c'), ('a', {}, 'c')):
            with self.subTest(forms=forms), self.assertRaises(ValueError): ManaRankFamily('bad', forms)
        with self.assertRaises(ValueError): ManaRankFamily('bad', FORMS, version='other')
        r = registry()
        with self.assertRaisesRegex(ValueError, 'Duplicate'): r.register_mana_rank_family(FAMILY)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            r.register_mana_rank_family(ManaRankFamily('other', FORMS))

    def test_missing_or_incompatible_forms_do_not_become_whiteboards(self):
        r = registry(enabled=False)
        r.register_mana_rank_family(ManaRankFamily('missing', (FORMS[0], 'missing.1', 'missing.2')))
        with self.assertRaises(ValueError): r.freeze()
        r = registry(enabled=False)
        r.register_card(CardDefinition('different', 'Different', CardType.SPELL, cost=3,
            on_play='body.'+FORMS[0], metadata=metadata(CardClass.ROGUE)))
        r.register_mana_rank_family(ManaRankFamily('cost', (FORMS[0], FORMS[1], 'different')))
        with self.assertRaisesRegex(ValueError, 'retain printed'): r.freeze()

    def test_unregistered_family_is_not_implicitly_guessed_from_card_name(self):
        self.options['enabled'] = False
        g = self.game(maximum=10); self.assertIsNotNone(self.entity(g, FORMS[0]))
        self.assertEqual(g.registry.mana_rank_families, {}); self.portable(g)
