"""Independent acquisition identity, necessary four bodies, and saved boundaries."""
from dataclasses import replace
import json
from pathlib import Path
import random
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, Game, IllegalAction, PlayCard,
    PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, SpellSchool,
    TargetSpec, TriggerSpec, UnidentifiedFamily, Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Draw, EquipWeapon,
    GainArmor, RequestChoice, Summon)
from hs_sim.engine.hand_upgrades import upgrade_face
from hs_sim.engine.model import DamageKind, Rarity
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import Resolution, default_mechanics
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import deck, metadata, registry as opening_registry, setup

BASE = 'LOOT_285'
FORMS = ('LOOT_285t', 'LOOT_285t2', 'LOOT_285t3', 'LOOT_285t4')
GOLEM, WEAPON = 'LOOT_285t3t', 'LOOT_285t4t'
FAMILY = UnidentifiedFamily('unidentified-shield-v1', BASE, FORMS)
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'data/support/unidentified-basics.json'
PIN = '86b4e7a0ef4ad78cae01bd0ce91aa9d0594fc175b847fd3bca98e84b6ebd0093'


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN:
        raise ValueError('Complete unidentified evidence changed')
    for row in raw['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original unidentified record changed')
    return {row['id']: row['data'] for row in raw['records']}


def registry(scripts=(), *, enabled=True, watcher=False, forms=FORMS):
    r = opening_registry(); rows = evidence()
    bodies = {
        BASE: lambda c: (GainArmor(c.player_id, 5),),
        FORMS[0]: lambda c: (GainArmor(c.player_id, 5), GainArmor(c.player_id, 10)),
        FORMS[1]: lambda c: (GainArmor(c.player_id, 5), Damage(c.target_id, 5, c.source_id, DamageKind.SPELL)),
        FORMS[2]: lambda c: (GainArmor(c.player_id, 5), Summon(c.player_id, GOLEM)),
        FORMS[3]: lambda c: (GainArmor(c.player_id, 5), EquipWeapon(c.player_id, WEAPON)),
    }
    for cid, body in bodies.items():
        row = rows[cid]; r.register_behavior('body.' + cid, body)
        r.register_card(CardDefinition(cid, row['name'], CardType.SPELL, cost=row['cost'],
            on_play='body.' + cid, targeting=TargetSpec() if cid == FORMS[1] else None,
            metadata=metadata(CardClass.WARRIOR, collectible=cid == BASE, rarity=Rarity.COMMON)))
    row = rows[GOLEM]
    r.register_card(CardDefinition(GOLEM, row['name'], CardType.MINION, cost=row['cost'],
        attack=row['attack'], health=row['health'],
        metadata=metadata(CardClass.WARRIOR, collectible=False, rarity=None)))
    row = rows[WEAPON]
    r.register_card(CardDefinition(WEAPON, row['name'], CardType.WEAPON, cost=row['cost'],
        attack=row['attack'], durability=row['health'],
        metadata=metadata(CardClass.WARRIOR, collectible=False, rarity=None)))
    if enabled: r.register_unidentified_family(replace(FAMILY, forms=forms))
    if watcher:
        def observe_entry(c):
            if c.state.entities[c.target_id].card_id not in FORMS:
                raise ResolutionError('Acquisition reaction observed an unsettled base')
            return (GainArmor(c.player_id, 1),)
        r.register_behavior('watch', observe_entry)
        r.register_card(CardDefinition('probe.watch', 'Acquisition fact probe', CardType.MINION, health=2,
            triggers=(TriggerSpec('card_added_to_hand', 'watch'),), metadata=metadata()))
    for name, callback in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=metadata()))
    return r


class UnidentifiedTests(unittest.TestCase):
    def setUp(self): self.scripts = []; self.options = {}
    def script(self, name, callback): self.scripts.append((name, callback))
    def game(self, hand=(BASE,), *, deck_cards=(), enemy_hand=(), board=(), seed=86):
        return Game.from_scenario(Scenario((
            PlayerSetup('warrior.hero', hand=hand, deck=deck_cards, board=board, max_mana=10, mana=10),
            PlayerSetup('mage.hero', hand=enemy_hand, max_mana=10, mana=10)), seed=seed),
            registry(self.scripts, **self.options))
    def entity(self, g, cid=None, player=1, zone=Zone.HAND):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone.value)
            if (cid is None and g.state.entities[i].card_id in (BASE, *FORMS)) or g.state.entities[i].card_id == cid)
    def ref(self, c, cid=None, player=1, zone=Zone.HAND):
        return CardReference.capture(next(c.state.entities[i] for i in getattr(c.state.players[player], zone.value)
            if (cid is None and c.state.entities[i].card_id in (BASE, *FORMS)) or c.state.entities[i].card_id == cid))
    def play(self, g, cid, target=None):
        p = g.state.active_player; source = self.entity(g, cid, p).id
        g.apply(PlayCard(p, source, target)); return source
    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(snap, registry(self.scripts, **self.options))
        self.assertEqual(restored.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, **self.options)).snapshot(), snap)
        return restored
    def opening(self):
        cards = (BASE, *(f'card.{i}' for i in range(1, 30)))
        for seed in range(1000):
            order = list(cards); random.Random(seed).shuffle(order)
            if BASE in order[:3]: break
        r = registry(self.scripts, **self.options)
        return Game.from_decks(setup(r, seed=seed, decks=(deck(CardClass.WARRIOR, cards), deck())), r)
    def select(self, g, options=()):
        pending = g.state.pending_choice
        g.apply(SelectChoice(pending.player_id, pending.id, tuple(options)))

    def test_complete_raw_four_bonuses_and_necessary_tokens(self):
        rows = evidence(); self.assertEqual(set(rows), {BASE, *FORMS, GOLEM, WEAPON})
        self.assertIn('bonus effect', rows[BASE]['text_en'])
        self.assertEqual([rows[c]['cost'] for c in (BASE, *FORMS)], [6]*5)
        self.assertEqual((rows[GOLEM]['attack'], rows[GOLEM]['health']), (5, 5))
        self.assertEqual((rows[WEAPON]['attack'], rows[WEAPON]['health']), (5, 2))

    def test_scenario_identifies_hand_but_not_deck_once(self):
        rng = random.Random(86); expected = rng.choice(FORMS)
        g = self.game(deck_cards=(BASE,)); entity = self.entity(g)
        self.assertEqual(entity.card_id, expected)
        self.assertEqual(self.entity(g, BASE, zone=Zone.DECK).card_id, BASE)
        self.assertEqual(g._rng.getstate(), rng.getstate())
        entry = next(row for row in g.state.hand_entries if row.entity_id == entity.id)
        self.assertEqual((entry.card_id, entity.zone_epoch), (BASE, entry.zone_epoch+1)); self.portable(g)

    def test_multiple_physical_bases_each_consume_one_ordered_sample(self):
        rng = random.Random(91); expected = [rng.choice(FORMS) for _ in range(3)]
        g = self.game((BASE, BASE), enemy_hand=(BASE,), seed=91)
        actual = [g.state.entities[i].card_id for p in (1, 2) for i in g.state.players[p].hand]
        self.assertEqual(actual, expected); self.assertEqual(g._rng.getstate(), rng.getstate()); self.portable(g)

    def test_each_selected_form_executes_its_complete_real_body(self):
        seen = set()
        for seed in range(20):
            cid = random.Random(seed).choice(FORMS)
            if cid in seen: continue
            seen.add(cid); g = self.game(seed=seed); source = self.entity(g).id
            target = g.state.players[2].hero_id if cid == FORMS[1] else None
            self.play(g, cid, target)
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 15 if cid == FORMS[0] else 5)
            self.assertEqual(g.state.players[1].mana, 4)
            if cid == FORMS[1]: self.assertEqual(g.state.entities[target].health, 25)
            if cid == FORMS[2]:
                token = self.entity(g, GOLEM, zone=Zone.BOARD)
                self.assertEqual((token.attack, token.health), (5, 5))
            if cid == FORMS[3]:
                token = g.state.entities[g.state.players[1].weapon_id]
                self.assertEqual((token.card_id, token.attack, token.durability), (WEAPON, 5, 2))
            self.assertEqual((g.state.play_history[-1].source_id, g.state.play_history[-1].card_id), (source, cid))
            self.portable(g)
        self.assertEqual(seen, set(FORMS))

    def test_target_requirement_depends_on_actual_identified_body(self):
        g = self.game((FORMS[1],)); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, FORMS[1])
        self.assertEqual(g.snapshot(), before)
        self.play(g, FORMS[1], g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 25)

    def test_existing_identified_forms_never_sample(self):
        g = self.game(FORMS); self.assertEqual(g._rng.getstate(), random.Random(86).getstate())
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], list(FORMS)); self.portable(g)

    def test_acquisition_is_settled_before_entry_reaction(self):
        self.options['watcher'] = True
        self.script('get', lambda c: (AddToHand(c.player_id, BASE),))
        g = self.game(('get',), board=('probe.watch',)); self.play(g, 'get')
        self.assertIn(self.entity(g).card_id, FORMS)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 1); self.portable(g)

    def test_fresh_acquisition_keeps_creation_cost_modifier(self):
        self.script('get', lambda c: (AddToHand(c.player_id, BASE, cost=CostSpec(delta=-2)),))
        g = self.game(('get',)); self.play(g, 'get'); entity = self.entity(g)
        quote = quote_unselected_cost(g.state, g.registry, entity)
        self.assertEqual((entity.base_cost, quote.amount), (6, 4)); self.portable(g)

    def test_add_to_deck_stays_base_until_real_draw(self):
        self.script('get', lambda c: (AddToDeck(1, BASE, position='top'),))
        self.script('draw', lambda c: (Draw(1),))
        g = self.game(('get', 'draw')); before = g._rng.getstate(); self.play(g, 'get')
        source = self.entity(g, BASE, zone=Zone.DECK).id
        self.assertEqual(g._rng.getstate(), before); self.play(g, 'draw')
        self.assertEqual(self.entity(g).id, source); self.assertIn(self.entity(g).card_id, FORMS)
        self.assertEqual(len(g.state.draw_history), 1); self.portable(g)

    def test_physical_deck_to_hand_move_keeps_entity_and_identifies(self):
        self.script('move', lambda c: (MoveCard(self.ref(c, BASE, zone=Zone.DECK), 1, Zone.HAND),))
        g = self.game(('move',), deck_cards=(BASE,)); source = self.entity(g, BASE, zone=Zone.DECK).id
        self.play(g, 'move'); self.assertEqual(self.entity(g).id, source); self.portable(g)

    def test_captured_old_reference_cannot_move_after_identification(self):
        def stale(c):
            ref = self.ref(c, BASE, zone=Zone.DECK)
            return (MoveCard(ref, 1, Zone.HAND), MoveCard(ref, 1, Zone.DECK))
        self.script('move', stale); g = self.game(('move',), deck_cards=(BASE,))
        source = self.entity(g, BASE, zone=Zone.DECK).id; self.play(g, 'move')
        self.assertEqual((g.state.entities[source].zone, g.state.entities[source].card_id),
            (Zone.HAND, random.Random(86).choice(FORMS)))
        self.assertEqual(sum(e.kind == 'zone_target_skipped' for e in g.events), 1); self.portable(g)

    def test_identified_face_survives_deck_move_and_return_without_reroll(self):
        self.script('away', lambda c: (MoveCard(self.ref(c), 1, Zone.DECK, position='top', reset=True),))
        self.script('draw', lambda c: (Draw(1),))
        g = self.game((BASE, 'away', 'draw')); entity = self.entity(g); rng = g._rng.getstate()
        self.play(g, 'away'); self.assertEqual(g.state.entities[entity.id].card_id, entity.card_id)
        self.play(g, 'draw'); self.assertEqual((self.entity(g).id, self.entity(g).card_id), (entity.id, entity.card_id))
        self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_transfer_of_identified_hand_keeps_selected_face(self):
        self.script('move', lambda c: (MoveCard(self.ref(c), 2, Zone.HAND),))
        g = self.game((BASE, 'move')); entity = self.entity(g); rng = g._rng.getstate(); self.play(g, 'move')
        other = self.entity(g, player=2)
        self.assertEqual((other.id, other.card_id), (entity.id, entity.card_id))
        self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_current_copy_of_identified_card_keeps_face_and_modifier(self):
        self.script('get', lambda c: (AddToHand(1, BASE, cost=CostSpec(delta=-2)),))
        self.script('copy', lambda c: (CopyCard(self.ref(c), 1),))
        g = self.game(('get', 'copy')); self.play(g, 'get'); entity = self.entity(g); rng = g._rng.getstate()
        self.play(g, 'copy'); copies = [g.state.entities[i] for i in g.state.players[1].hand]
        self.assertEqual([e.card_id for e in copies], [entity.card_id]*2)
        self.assertEqual(len({e.id for e in copies}), 2)
        self.assertEqual([quote_unselected_cost(g.state, g.registry, e).amount for e in copies], [4, 4])
        self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_base_copy_of_identified_card_retains_face_but_resets_modifier(self):
        self.script('get', lambda c: (AddToHand(1, BASE, cost=CostSpec(delta=-2)),))
        self.script('copy', lambda c: (CopyCard(self.ref(c), 1, mode='base'),))
        g = self.game(('get', 'copy')); self.play(g, 'get'); face = self.entity(g).card_id; rng = g._rng.getstate()
        self.play(g, 'copy'); copies = [g.state.entities[i] for i in g.state.players[1].hand]
        self.assertEqual([e.card_id for e in copies], [face]*2)
        self.assertEqual([quote_unselected_cost(g.state, g.registry, e).amount for e in copies], [4, 6])
        self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_copy_unidentified_deck_card_to_hand_selects_for_new_entity(self):
        self.script('copy', lambda c: (CopyCard(self.ref(c, BASE, zone=Zone.DECK), 1),))
        g = self.game(('copy',), deck_cards=(BASE,)); original = self.entity(g, BASE, zone=Zone.DECK)
        self.play(g, 'copy'); entity = self.entity(g)
        self.assertNotEqual(entity.id, original.id); self.assertEqual(entity.origin_entity_id, original.id)
        self.assertEqual(g.state.entities[original.id].card_id, BASE); self.portable(g)

    def test_copy_unidentified_deck_card_to_deck_does_not_sample(self):
        self.script('copy', lambda c: (CopyCard(self.ref(c, BASE, zone=Zone.DECK), 1, Zone.DECK, position='top'),))
        g = self.game(('copy',), deck_cards=(BASE,)); rng = g._rng.getstate(); self.play(g, 'copy')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck], [BASE, BASE])
        self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_generated_burn_never_enters_hand_or_samples(self):
        self.script('get', lambda c: (AddToHand(2, BASE),))
        g = self.game(('get',), enemy_hand=tuple(f'card.{i}' for i in range(1, 11)))
        rng = g._rng.getstate(); self.play(g, 'get')
        burned = g.state.entities[g.state.players[2].graveyard[-1]]
        self.assertEqual(burned.card_id, BASE); self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_draw_burn_never_identifies(self):
        self.script('draw', lambda c: (Draw(1, 2),))
        g = self.game(('draw', *(f'card.{i}' for i in range(1, 10))), deck_cards=('card.10', BASE))
        rng = g._rng.getstate(); self.play(g, 'draw')
        burned = g.state.entities[g.state.players[1].graveyard[-1]]
        self.assertEqual(burned.card_id, BASE); self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_unrelated_events_never_reroll_or_invalidate_selected_identity(self):
        self.script('noop', lambda c: (GainArmor(1, 1), GainArmor(1, 1)))
        g = self.game((BASE, 'noop')); entity = self.entity(g); rng = g._rng.getstate(); self.play(g, 'noop')
        self.assertEqual((self.entity(g).card_id, self.entity(g).zone_epoch), (entity.card_id, entity.zone_epoch))
        self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_failed_acquisition_rolls_back_rng_face_entities_payment_and_information(self):
        self.script('bad', lambda c: (AddToHand(1, BASE), AddToHand(1, 'missing.card')))
        g = self.game(('bad',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'bad')
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_waiting_before_acquisition_restores_and_replays_same_sample(self):
        self.script('choose', lambda c: (RequestChoice(1,
            (ChoiceOption('get', 'Get shield', (AddToHand(1, BASE),)),), c.source_id),))
        g = self.game(('choose',)); self.play(g, 'choose'); restored = self.portable(g)
        before_rng = g._rng.getstate()
        self.assertEqual(restored._rng.getstate(), before_rng)
        for instance in (g, restored): self.select(instance, ('get',))
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertIn(self.entity(g).card_id, FORMS); self.portable(g)

    def test_waiting_after_acquisition_preserves_result_and_rng_without_reroll(self):
        self.script('choose', lambda c: (AddToHand(1, BASE), RequestChoice(1,
            (ChoiceOption('done', 'Done'),), c.source_id)))
        g = self.game(('choose',)); self.play(g, 'choose'); entity = self.entity(g); rng = g._rng.getstate()
        restored = self.portable(g)
        for instance in (g, restored):
            self.assertEqual(instance._rng.getstate(), rng); self.select(instance, ('done',))
            self.assertEqual(instance._rng.getstate(), rng); self.assertEqual(self.entity(instance).card_id, entity.card_id)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_mulligan_offer_stays_base_and_kept_hand_settles_after_both_submit(self):
        g = self.opening(); entity = self.entity(g, BASE); self.portable(g)
        self.assertEqual(g.state.opening.stage, 'mulligan')
        self.select(g); self.assertEqual(g.state.entities[entity.id].card_id, BASE); self.portable(g)
        self.select(g); self.assertEqual(g.state.opening.stage, 'complete')
        self.assertIn(g.state.entities[entity.id].card_id, FORMS); self.portable(g)

    def test_rejected_mulligan_card_remains_unidentified_in_deck(self):
        g = self.opening(); entity = self.entity(g, BASE); self.select(g, (str(entity.id),)); self.portable(g)
        self.select(g)
        # A rejected card may naturally become the first-turn draw; only actual hand entries identify.
        final = g.state.entities[entity.id]
        if final.zone == Zone.DECK:
            self.assertEqual(final.card_id, BASE)
        else:
            self.assertEqual(final.zone, Zone.HAND); self.assertIn(final.card_id, FORMS)
        self.portable(g)

    def test_owner_sees_selected_identity_opponent_has_only_card_back(self):
        self.script('get', lambda c: (AddToHand(1, BASE),))
        g = self.game(('get',)); self.play(g, 'get')
        self.assertEqual(g.observe(1)['players'][0]['hand'][0]['card_id'], self.entity(g).card_id)
        self.assertIsNone(g.observe(2)['players'][0]['hand'][0]['card_id'])
        for viewer in (1, 2):
            text = json.dumps(g.observe(viewer))
            for private in ('rng_state', 'unidentified_families', 'zone_epoch', 'hand_entries'):
                self.assertNotIn(private, text)
        self.portable(g)

    def test_restore_rejects_unsettled_hand_instead_of_repairing_or_sampling(self):
        g = self.game(); entity = g._state.entities[self.entity(g).id]
        upgrade_face(Resolution(g), entity, BASE); g._information.sync(g)
        malformed = g.snapshot()
        with self.assertRaisesRegex(SnapshotError, 'Unsettled unidentified'):
            Game.from_snapshot(malformed, registry())

    def test_empty_profile_preserves_existing_registry_and_mechanics_fingerprints(self):
        from unittest.mock import patch
        from hs_sim.engine.representative import build_registry
        import hs_sim.engine.registry as registry_module
        dumps = registry_module.json.dumps
        for candidate in (opening_registry(), build_registry(), registry(enabled=False)):
            payloads = []
            def capture(payload, *args, **kwargs):
                payloads.append(payload)
                return dumps(payload, *args, **kwargs)
            with patch.object(registry_module.json, 'dumps', side_effect=capture):
                candidate.fingerprint()
            self.assertEqual(len(payloads), 1)
            self.assertFalse(candidate.unidentified_families)
            self.assertNotIn('unidentified_families', payloads[0])
        scenario = Scenario((PlayerSetup('warrior.hero'), PlayerSetup('mage.hero')))
        disabled = Game.from_scenario(scenario, registry(enabled=False))
        enabled = Game.from_scenario(scenario, registry())
        self.assertEqual(disabled.snapshot()['mechanics_version'], enabled.snapshot()['mechanics_version'])
        self.assertEqual(enabled.snapshot()['mechanics_version']['version'], default_mechanics().version)

    def test_opt_in_policy_and_order_enter_fingerprint_and_freeze(self):
        enabled, disabled = registry(), registry(enabled=False)
        self.assertNotEqual(enabled.fingerprint(), disabled.fingerprint())
        self.assertNotEqual(enabled.fingerprint(), registry(forms=tuple(reversed(FORMS))).fingerprint())
        enabled.freeze()
        with self.assertRaisesRegex(ValueError, 'frozen'): enabled.register_unidentified_family(FAMILY)
        with self.assertRaises(TypeError): enabled.unidentified_families['new'] = FAMILY

    def test_invalid_duplicate_and_shared_families_rejected(self):
        for forms in (list(FORMS), FORMS[:3], (*FORMS[:3], FORMS[0]), (*FORMS[:3], BASE), (*FORMS[:3], {})):
            with self.subTest(forms=forms), self.assertRaises(ValueError): UnidentifiedFamily('bad', BASE, forms)
        with self.assertRaises(ValueError): replace(FAMILY, version='other')
        r = registry()
        with self.assertRaisesRegex(ValueError, 'Duplicate'): r.register_unidentified_family(FAMILY)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            r.register_unidentified_family(UnidentifiedFamily('other', 'new', FORMS))
        with self.assertRaises(ValueError): r.register_unidentified_family({'base': BASE})

    def test_missing_or_incompatible_forms_are_not_whiteboards(self):
        r = registry(enabled=False)
        r.register_unidentified_family(replace(FAMILY, forms=(*FORMS[:3], 'missing')))
        with self.assertRaises(ValueError): r.freeze()
        for changes in ({'cost': 7}, {'metadata': metadata(CardClass.MAGE, collectible=False)},
                        {'spell_school': SpellSchool.ARCANE}, {'kind': CardType.MINION, 'health': 1}, {'on_play': None}):
            with self.subTest(changes=changes):
                r = registry(enabled=False)
                r.register_card(replace(r.card(FORMS[0]), id='incompatible', **changes))
                r.register_unidentified_family(replace(FAMILY, forms=(*FORMS[:3], 'incompatible')))
                with self.assertRaises(ValueError): r.freeze()

    def test_unregistered_base_is_not_inferred_from_name_or_text(self):
        self.options['enabled'] = False; g = self.game()
        self.assertEqual(self.entity(g).card_id, BASE)
        self.assertEqual(g._rng.getstate(), random.Random(86).getstate()); self.portable(g)
