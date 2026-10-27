"""Real deck discoveries retain physical cards and their finite selected rewards."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry, past_arcane_deck_rewards as native
from hs_sim.engine import (CardDefinition, CardType, CastSpell, Game, PlayCard, PlayerSetup,
    ResolutionError, Scenario, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, InvokeBehavior,
    RequestChoice, Summon)
from hs_sim.engine.discovery_delivery import COMPLETED, original_recipient
from hs_sim.engine.health_rules import spell_bonus
from hs_sim.engine.hand_choice_followups import DiscoverForPlayFollowup
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import ChoicePurpose, CostSpec, DamageKind
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.stored_spell_damage import GrantStoredSpellDamage
from hs_sim.engine.zones import CardReference, ChooseFromZone, ModifyStoredCost, MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

QUIVER, CHEST = native.LEAVES
P = 'k595.'
UNIT, POWER, ARCANE, FIRE, WEAPON, PREP, WATCH, FILL_WATCH, FAULT, RETURN, CHANGE, AUTO = (
    P+x for x in ('unit', 'power', 'arcane', 'fire', 'weapon', 'prep', 'watch', 'fill_watch',
        'fault', 'return', 'change', 'auto'))


@lru_cache(None)
def host(role='writer'):
    f = build_cn37_local_pool_format(); r = f.registry
    def prep(c):
        work = []
        for identity in c.state.players[c.player_id].deck:
            entity = c.state.entities[identity]; ref = CardReference.capture(entity)
            work.append(ModifyStoredCost(ref, CostSpec(set_to=1), c.source_id))
            if entity.kind == CardType.MINION: work.append(BuffStoredCard(ref, 2, 3, c.source_id))
            if entity.card_id == ARCANE: work.append(GrantStoredSpellDamage(ref, 1, c.source_id))
        return tuple(work)
    def fault(c): raise ResolutionError('K595 deliberate late failure')
    def current(c, zone):
        return next(c.state.entities[i] for i in getattr(c.state.players[c.player_id], zone)
            if c.state.entities[i].card_id in (ARCANE, UNIT))
    def return_card(c):
        return (MoveCard(CardReference.capture(current(c, 'hand')), c.player_id, Zone.DECK, source_id=c.source_id),)
    def change_card(c):
        entity = current(c, 'hand'); ref = CardReference.capture(entity)
        return (ModifyStoredCost(ref, CostSpec(set_to=7), c.source_id),) + (
            (BuffStoredCard(ref, 5, 5, c.source_id),) if entity.kind == CardType.MINION else ())
    def watch(c):
        event = c.event; source = c.state.entities.get(event.source_id)
        if source is None or event.player_id != c.player_id or source.card_id not in native.LEAVES: return ()
        if c.source.card_id == FILL_WATCH:
            return (AddToHand(c.player_id, FIRE, c.source_id),) if event.kind == 'choice_requested' else ()
        if not (event.kind == 'stored_spell_damage_granted' and source.card_id == QUIVER or
                event.kind == 'card_moved_to_hand' and source.card_id == CHEST): return ()
        target = c.state.entities[event.target_id]; ref = CardReference.capture(target)
        lose = tuple(Destroy(i, c.source_id) for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id == POWER)
        options = (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fault', 'Late failure', (InvokeBehavior(FAULT, c.source_id, c.player_id),)),
            ChoiceOption('lose', 'Remove provider', lose),
            ChoiceOption('gain', 'Install provider', (Summon(c.player_id, POWER),)))
        if target.zone == Zone.DECK:
            options += (ChoiceOption('cycle', 'Leave and reenter deck',
                (MoveCard(ref, c.player_id, Zone.HAND, source_id=c.source_id),
                    InvokeBehavior(RETURN, c.source_id, c.player_id))),)
        else:
            options += (ChoiceOption('return', 'Return original to deck', (MoveCard(ref, c.player_id, Zone.DECK, source_id=c.source_id),)),
                ChoiceOption('change', 'Change original material', (InvokeBehavior(CHANGE, c.source_id, c.player_id),)))
        return (RequestChoice(c.player_id, options, c.source_id),)
    r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, cost=3, attack=3, health=4))
    r.register_card(CardDefinition(POWER, POWER, CardType.MINION, health=10, spell_damage=1))
    r.register_card(CardDefinition(WEAPON, WEAPON, CardType.WEAPON, cost=1, attack=2, durability=2))
    for cid in (WATCH, FILL_WATCH):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=20, triggers=tuple(
            TriggerSpec(event, P+'watch') for event in ('stored_spell_damage_granted', 'card_moved_to_hand', 'choice_requested'))))
    for cid, body in ((PREP, prep), (FAULT, fault), (RETURN, return_card), (CHANGE, change_card),
            (AUTO, lambda c: (CastSpell(c.player_id, CHEST, c.source_id),)),
            (ARCANE, lambda c: (Damage(c.state.players[3-c.player_id].hero_id, 2, c.source_id, DamageKind.SPELL),)),
            (FIRE, lambda c: (Damage(c.state.players[3-c.player_id].hero_id, 2, c.source_id, DamageKind.SPELL),))):
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=2 if cid in (ARCANE, FIRE) else 0,
            on_play=cid, spell_school=SpellSchool.ARCANE if cid == ARCANE else SpellSchool.FIRE if cid == FIRE else None))
    return f


class PastArcaneDeckRewardTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(lambda mode, role: host(role).registry)

    def game(self, hand=(), *, deck=(), board=(), player=1, seed=595):
        f = host()
        setups = tuple(PlayerSetup('HERO_03', hand=hand if p == player else (), board=board if p == player else (),
            deck=deck if p == player else (UNIT,)*5, mana=40, max_mana=40, mana_cap=40) for p in (1, 2))
        return Game.from_scenario(Scenario(setups, active_player=player, seed=seed, generation_context=f.context), f.registry)

    def paid(self, g, cid, player=1):
        before = g.state.players[player].mana; identity = self.play(g, cid, player=player)
        self.assertEqual((g.state.play_history[-1].card_id, g.state.play_history[-1].cost), (cid, 2))
        self.assertEqual(g.state.players[player].mana, before-2)
        return identity

    def pick(self, g, cid=None):
        q = g.state.pending_choice; self.assertEqual(q.purpose, ChoicePurpose.CARD_DISCOVERY)
        option = next(o for o in q.options if cid is None or o.card_id == cid)
        self.choose(g, option.id)

    def bonus(self, entity): return sum(a.spell_damage for a in entity.abilities if a.kind == 'spell_damage')

    def test_full_two_original_rows_four_complete_primary_faces(self):
        data = native.load_batch(); self.assertEqual(len(data['dependencies']), 2); self.assertEqual(len(data['official_observations']), 4)
        records = {x['record']['id']:x['record'] for x in data['dependencies']}
        for row in data['official_observations']: batch.check_face(records[row['card_id']], row['face'], row['locale'])
        self.assertEqual(native.COLLECTIBLE_ROOTS, ()); self.assertEqual({host().registry.card(cid).cost for cid in native.LEAVES}, {2})

    def test_quiver_paid_native_filters_spells_and_moves_original_in_both_seats(self):
        for player in (1, 2):
            g = self.game((QUIVER,), deck=(UNIT, ARCANE), player=player); identity = self.entity(g, ARCANE, player, 'deck').id
            self.paid(g, QUIVER, player); self.assertEqual([o.card_id for o in g.state.pending_choice.options], [ARCANE])
            other = self.portable(g); self.pick(other)
            self.assertEqual(other.state.players[player].hand, [identity]); self.assertEqual(self.bonus(other.state.entities[identity]), 1)
            self.assertFalse(other.state.draw_history); self.assertEqual(len(other.state.card_discovery_history), 1)

    def test_quiver_non_arcane_original_keeps_its_material_without_bonus(self):
        g = self.game((QUIVER, PREP), deck=(FIRE,)); self.play(g, PREP); identity = self.entity(g, FIRE, zone='deck').id
        self.paid(g, QUIVER); self.pick(g)
        self.assertEqual(self.entity(g, FIRE).id, identity); self.assertEqual(self.bonus(g.state.entities[identity]), 0)
        self.assertEqual(g.state.entities[identity].cost, 1); self.portable(g)

    def test_quiver_stacks_local_bonus_only_on_selected_original_actual_cast(self):
        g = self.game((PREP, QUIVER, FIRE), deck=(ARCANE,)); self.play(g, PREP); original = self.entity(g, ARCANE, zone='deck').id
        self.paid(g, QUIVER); self.pick(g); self.assertEqual(self.bonus(g.state.entities[original]), 2)
        self.assertEqual(spell_bonus(g.state, 1, g.registry), 0)
        self.play(g, ARCANE); self.play(g, FIRE)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 24)
        self.assertEqual(sum(a.spell_damage for a in g.state.cast_history[-2].local_spell_damage), 2); self.portable(g)

    def test_quiver_duplicate_faces_are_original_physical_options(self):
        g = self.game((QUIVER,), deck=(ARCANE, ARCANE, ARCANE, FIRE)); self.paid(g, QUIVER)
        options = g._frame.options; work = options[0].effects[0]
        self.assertEqual(len(work.offered), 3); self.assertEqual(len({o.card.entity_id for o in work.offered}), 3)
        chosen = work.offered[0].card.entity_id; self.choose(g, options[0].id)
        self.assertEqual(g.state.players[1].hand, [chosen]); self.assertEqual(len(g.state.players[1].deck), 3)

    def test_empty_deck_or_no_matching_spells_has_no_rng_choice_or_fatigue(self):
        for cid, deck in ((QUIVER, (UNIT,)), (QUIVER, ()), (CHEST, ())):
            g = self.game((cid,), deck=deck); rng = g._rng.getstate(); self.paid(g, cid)
            self.assertEqual(g._rng.getstate(), rng); self.assertIsNone(g.state.pending_choice)
            self.assertFalse(g.state.draw_history); self.assertFalse(g.state.card_discovery_history)

    def test_quiver_grant_wait_rollback_and_same_physical_reentry_stays_stale(self):
        g = self.game((QUIVER,), deck=(ARCANE,), board=(WATCH,)); original = self.entity(g, ARCANE, zone='deck').id
        self.paid(g, QUIVER); self.pick(g); other = self.portable(g); saved = other.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'): self.choose(other, 'fault')
        self.assertEqual(other.snapshot(), saved); self.choose(other, 'cycle')
        self.assertIn(original, other.state.players[1].deck); self.assertFalse(other.state.players[1].hand)
        event = next(e for e in other.events if e.kind == COMPLETED)
        self.assertIsNone(original_recipient(other.state, event)); self.portable(other)

    def test_quiver_bonus_is_present_on_full_hand_burned_original(self):
        g = self.game((QUIVER,)+(FIRE,)*9, deck=(ARCANE,), board=(FILL_WATCH,)); original = self.entity(g, ARCANE, zone='deck').id
        self.paid(g, QUIVER); self.pick(g)
        self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD); self.assertEqual(self.bonus(g.state.entities[original]), 1)
        self.assertFalse(g.state.players[1].deck); self.portable(g)

    def test_chest_without_provider_returns_one_original_of_any_type(self):
        for cid in (UNIT, FIRE, WEAPON):
            g = self.game((CHEST,), deck=(cid,)); original = self.entity(g, cid, zone='deck').id
            self.paid(g, CHEST); self.pick(g); self.assertEqual(g.state.players[1].hand, [original])
            self.assertFalse([e for e in g.events if e.kind == 'card_created' and e.source_id == g.state.play_history[-1].source_id])

    def test_chest_copies_current_minion_stats_cost_and_new_attachment_ids(self):
        g = self.game((PREP, CHEST), deck=(UNIT,), board=(POWER,)); self.play(g, PREP); original = self.entity(g, UNIT, zone='deck').id
        self.paid(g, CHEST); self.pick(g); hands = [g.state.entities[i] for i in g.state.players[1].hand]
        self.assertEqual(len(hands), 2); self.assertEqual(hands[0].id, original); self.assertNotEqual(hands[1].id, original)
        self.assertEqual([(e.cost, e.attack, e.health) for e in hands], [(1, 5, 7)]*2)
        self.assertEqual(hands[1].origin_entity_id, original); self.portable(g)

    def test_chest_copies_selected_spells_local_bonus_but_local_bonus_is_not_a_provider(self):
        for power, count in (((), 1), ((POWER,), 2)):
            g = self.game((PREP, CHEST), deck=(ARCANE,), board=power); self.play(g, PREP); self.paid(g, CHEST); self.pick(g)
            cards = [g.state.entities[i] for i in g.state.players[1].hand]
            self.assertEqual(len(cards), count); self.assertEqual([self.bonus(e) for e in cards], [1]*count)
            if count == 2:self.assertNotEqual(cards[0].abilities[-1].id, cards[1].abilities[-1].id)

    def test_chest_copy_condition_is_frozen_before_original_delivery_reactions(self):
        for initial, option, count in (((POWER,), 'lose', 2), ((), 'gain', 1)):
            g = self.game((CHEST,), deck=(UNIT,), board=(*initial, WATCH)); self.paid(g, CHEST); self.pick(g)
            self.assertIsNotNone(g.state.pending_choice); other = self.portable(g); self.choose(other, option)
            self.assertEqual(len(other.state.players[1].hand), count); self.portable(other)

    def test_chest_current_material_captured_before_original_changes(self):
        g = self.game((PREP, CHEST), deck=(UNIT,), board=(POWER, WATCH)); self.play(g, PREP); self.paid(g, CHEST); self.pick(g)
        self.choose(g, 'change'); cards = [g.state.entities[i] for i in g.state.players[1].hand]
        self.assertEqual([(e.cost, e.attack, e.health) for e in cards], [(7, 10, 12), (1, 5, 7)]); self.portable(g)

    def test_chest_copy_survives_original_return_and_failed_continuation(self):
        g = self.game((CHEST,), deck=(UNIT,), board=(POWER, WATCH)); original = self.entity(g, UNIT, zone='deck').id
        self.paid(g, CHEST); self.pick(g); other = self.portable(g); saved = other.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'): self.choose(other, 'fault')
        self.assertEqual(other.snapshot(), saved); self.choose(other, 'return')
        self.assertIn(original, other.state.players[1].deck); self.assertEqual(len(other.state.players[1].hand), 1)
        self.assertNotEqual(other.state.players[1].hand[0], original); self.portable(other)

    def test_chest_copy_overflows_independently_after_original_delivery(self):
        for filled in (False, True):
            g = self.game((CHEST,)+(FIRE,)*9, deck=(UNIT,), board=(POWER, *((FILL_WATCH,) if filled else ())))
            original = self.entity(g, UNIT, zone='deck').id; source = self.paid(g, CHEST); self.pick(g)
            copies = [e for e in g.state.entities.values() if e.origin_entity_id == original]
            self.assertEqual(len(copies), 1); self.assertEqual(copies[0].zone, Zone.GRAVEYARD)
            self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD if filled else Zone.HAND)
            self.assertEqual(len([e for e in g.events if e.kind == 'card_burned' and e.source_id == source]), 2 if filled else 1)

    def test_chest_automatic_cast_commits_actual_discovery_without_manual_repayment(self):
        g = self.game((AUTO,), deck=(UNIT,), board=(POWER,)); self.play(g, AUTO)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(len(g.state.players[1].hand), 2)
        self.assertEqual([v.card_id for v in g.state.play_history], [AUTO]); self.assertEqual(len(g.state.card_discovery_history), 1)
        self.portable(g)

    def test_finite_declarations_reject_unrelated_or_combined_profiles(self):
        req = ChooseFromZone(1, 1, Zone.DECK, PoolQuery(kinds=(CardType.SPELL,)), operation='take',
            distinct='entity', source_id=3, discovery=True, selected_reward='arcane_spell_damage')
        for changes in ({'selected_reward':True}, {'selected_reward':'unknown'}, {'owner_id':2}, {'operation':'draw'},
                {'sample_size':True}, {'sample_size':4}, {'query':PoolQuery()}, {'discovery':False},
                {'cost':CostSpec(set_to=0)}, {'destroy_unchosen':True}, {'source_id':None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):replace(req, **changes)
        with self.assertRaises(ValueError):DiscoverForPlayFollowup(req)

    def test_original_reward_frame_tampering_and_previous_schema_are_rejected(self):
        g = self.game((QUIVER,), deck=(ARCANE,)); self.paid(g, QUIVER); saved = json.loads(json.dumps(g.snapshot()))
        bad = deepcopy(saved); bad['schema_version'] = 601
        with self.assertRaises(ValueError):Game.from_snapshot(bad, host('independent-reader').registry)
        text = json.dumps(saved); self.assertIn('arcane_spell_damage', text)
        bad = json.loads(text.replace('arcane_spell_damage', 'copy_with_spell_damage'))
        with self.assertRaises(ValueError):Game.from_snapshot(bad, host('independent-reader').registry)
        self.assertGreaterEqual(SNAPSHOT_SCHEMA_VERSION, 602)

    def test_late_printed_metadata_mismatch_cannot_partly_register(self):
        r = batch.registration_prefix(build_registry, 'hs_sim.cards.past_arcane_deck_rewards.register_past_arcane_deck_rewards',
            native.register_past_arcane_deck_rewards)
        r.register_pool_card(replace(host().registry.pool_card(CHEST), cost=9)); before = r.fingerprint()
        with self.assertRaisesRegex(TargetValidationError, CHEST):native.register_past_arcane_deck_rewards(r)
        self.assertEqual(r.fingerprint(), before)

    def test_private_original_inventory_and_full_past_source_remain_explicit(self):
        g = self.game((CHEST,), deck=(UNIT, FIRE, ARCANE), board=(POWER,)); self.paid(g, CHEST)
        self.portable(g); public = json.dumps(g.for_player(2).observe())
        for name in ('selected_reward', 'CardReference', 'resolution_frame', 'rng_state', 'record_sha256'):
            self.assertNotIn('"'+name+'"', public)
        ref = batch.read(native.ROOT/'data/cards/past-arcane-local-reference-v1.json')
        self.assertEqual(len(ref['candidate_ids']), 84); self.assertTrue(set(native.LEAVES) <= set(ref['candidate_ids']))
        self.assertFalse(any(v.source_card_id == 'TIME_857' for v in host().registry.generation_scopes.values()))
