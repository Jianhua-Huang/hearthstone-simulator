"""Actual Moonlit copies draw originals; Volume discovers only its actual roots."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry, past_arcane_physical_discovery as native
from hs_sim.engine import (CardDefinition, CardType, CastSpell, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, ResolutionError, Scenario, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Draw, GainArmor, InvokeBehavior, RequestChoice)
from hs_sim.engine.hand_choice_followups import (DiscoverForPlayFollowup, selected, validate_shape)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CastWhenDrawnSpec, ChoicePurpose, CostSpec
from hs_sim.engine.physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.stored_spell_damage import GrantStoredSpellDamage
from hs_sim.engine.zones import CardReference, ChooseFromZone, DestroyStoredCard, ModifyStoredCost, MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

MOON, VOLUME = native.LEAVES
P = 'k597.'
UNIT, FILLING, FROST, ARCANE, FIRE, PREP, CYCLE, RETURN, AUTO_MOON, AUTO_VOLUME, FAULT = (
    P+x for x in ('unit', 'filling', 'frost', 'arcane', 'fire', 'prep', 'cycle', 'return', 'auto_moon', 'auto_volume', 'fault'))
INITIAL_WAIT, ORIGINAL_WAIT, VOLUME_WAIT, EXTRA_WATCH, BUFF_WATCH, FILL_WATCH, FAIL_COPY = (
    P+x for x in ('initial_wait', 'original_wait', 'volume_wait', 'extra_watch', 'buff_watch', 'fill_watch', 'fail_copy'))
WATCHES = (INITIAL_WAIT, ORIGINAL_WAIT, VOLUME_WAIT, EXTRA_WATCH, BUFF_WATCH, FILL_WATCH, FAIL_COPY)
TRAP = P+'trap'


@lru_cache(None)
def host(role='writer'):
    f = build_cn37_local_pool_format(); r = f.registry
    def fault(c): raise ResolutionError('K597 deliberate continuation failure')
    def prep(c):
        work = []
        for i in c.state.players[c.player_id].deck:
            entity = c.state.entities[i]; ref = CardReference.capture(entity)
            work.append(ModifyStoredCost(ref, CostSpec(set_to=0), c.source_id))
            if entity.kind == CardType.MINION:work.append(BuffStoredCard(ref, 2, 3, c.source_id))
            if entity.card_id == ARCANE:work.append(GrantStoredSpellDamage(ref, 1, c.source_id))
        return tuple(work)
    def original(c):return c.state.entities[selected(c.state.hand_choice_followups[-1]).card.entity_id]
    def cycle(c):
        return (MoveCard(CardReference.capture(original(c)), c.player_id, Zone.HAND, source_id=c.source_id),
            InvokeBehavior(RETURN, c.source_id, c.player_id))
    def restore(c):return (MoveCard(CardReference.capture(original(c)), c.player_id, Zone.DECK, source_id=c.source_id),)
    def watch(c):
        event = c.event; source = c.state.entities.get(event.source_id); cid = c.source.card_id
        if source is None or event.player_id != c.player_id:return ()
        options = (ChoiceOption('continue', 'Continue'), ChoiceOption('fault', 'Fail',
            (InvokeBehavior(FAULT, c.source_id, c.player_id),)))
        if cid == FILL_WATCH and event.kind == 'choice_requested' and source.card_id == MOON:
            return (AddToHand(c.player_id, FROST, c.source_id),)
        if cid == FAIL_COPY and event.kind == 'card_created' and source.card_id == VOLUME:
            return (InvokeBehavior(FAULT, c.source_id, c.player_id),)
        if cid == INITIAL_WAIT and event.kind == 'card_added_to_hand' and source.card_id == MOON:
            return (RequestChoice(c.player_id, options, c.source_id),)
        if cid == ORIGINAL_WAIT and event.kind == 'card_drawn' and source.card_id == MOON:
            return (RequestChoice(c.player_id, options, c.source_id),)
        if event.kind == 'card_drawn' and source.card_id == VOLUME:
            roots = [row for row in c.state.draw_history if row.source_id == source.id and row.parent_id is None]
            if cid == EXTRA_WATCH and len(roots) == 1:return (Draw(c.player_id, 1, c.source_id),)
            target = c.state.entities[event.target_id]
            if cid == BUFF_WATCH and target.zone == Zone.HAND:
                ref = CardReference.capture(target)
                return (ModifyStoredCost(ref, CostSpec(set_to=0), c.source_id), GrantStoredSpellDamage(ref, 1, c.source_id))
            if cid == VOLUME_WAIT and len(roots) == 1:
                options += (ChoiceOption('drop', 'Destroy original arrival',
                    (DestroyStoredCard(CardReference.capture(target), c.source_id),)),)
                return (RequestChoice(c.player_id, options, c.source_id),)
        return ()
    for cid, body in ((FAULT, fault), (PREP, prep), (CYCLE, cycle), (RETURN, restore),
            (AUTO_MOON, lambda c:(CastSpell(c.player_id, MOON, c.source_id),)),
            (AUTO_VOLUME, lambda c:(CastSpell(c.player_id, VOLUME, c.source_id),)),
            (FROST, lambda c:(GainArmor(c.player_id, 1),)), (ARCANE, lambda c:(GainArmor(c.player_id, 2),)),
            (FIRE, lambda c:(GainArmor(c.player_id, 3),)), (TRAP, lambda c:(GainArmor(c.player_id, 1),)),
            (P+'fill', lambda c:(AddToHand(c.player_id, FROST, c.source_id),))):
        r.register_behavior(cid, body)
    r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, cost=1, attack=2, health=3))
    r.register_card(CardDefinition(FILLING, FILLING, CardType.MINION, health=3, battlecry=P+'fill'))
    r.register_card(CardDefinition(TRAP, TRAP, CardType.SPELL, on_play=TRAP,
        keywords=(Keyword.CASTS_WHEN_DRAWN,), cast_when_drawn=CastWhenDrawnSpec()))
    for cid in WATCHES:r.register_card(CardDefinition(cid, cid, CardType.MINION, health=20,
        triggers=tuple(TriggerSpec(k, P+'watch')for k in ('choice_requested', 'card_created', 'card_added_to_hand', 'card_drawn'))))
    for cid in (PREP, CYCLE, RETURN, AUTO_MOON, AUTO_VOLUME, FROST, ARCANE, FIRE):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=1 if cid in (FROST, ARCANE, FIRE) else 0,
            on_play=cid, spell_school=SpellSchool.FROST if cid == FROST else SpellSchool.ARCANE if cid == ARCANE else None))
    return f


class PastArcanePhysicalDiscoveryTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(lambda mode, role:host(role).registry)

    def game(self, hand=(), *, deck=(), board=(), mana=20, player=1):
        f = host(); setups = tuple(PlayerSetup('HERO_03', hand=hand if p == player else (), board=board if p == player else (),
            deck=deck if p == player else (UNIT,)*8, mana=mana, max_mana=20, mana_cap=20) for p in (1, 2))
        return Game.from_scenario(Scenario(setups, active_player=player, seed=597, generation_context=f.context), f.registry)

    def paid(self, g, cid, player=1):
        mana = g.state.players[player].mana; source = self.play(g, cid, player=player); cost = g.registry.card(cid).cost
        self.assertEqual((g.state.play_history[-1].card_id, g.state.play_history[-1].cost), (cid, cost))
        self.assertEqual(g.state.players[player].mana, mana-cost); return source

    def pick(self, g, cid=None, index=None):
        q = g.state.pending_choice; self.assertEqual(q.purpose, ChoicePurpose.CARD_DISCOVERY)
        option = q.options[index] if index is not None else next(o for o in q.options if cid is None or o.card_id == cid)
        self.choose(g, option.id); return option.card_id

    def play_copy(self, g):
        root = g.state.hand_choice_followups[-1]; identity = root.initial_entity_id
        g.apply(PlayCard(root.request.player_id, identity)); return identity

    def test_two_full_original_rows_four_primary_faces_and_no_new_standard_roots(self):
        data = native.load_batch(); self.assertEqual((len(data['dependencies']), len(data['official_observations'])), (2, 4))
        rows = {v['record']['id']:v['record']for v in data['dependencies']}
        for row in data['official_observations']:batch.check_face(rows[row['card_id']], row['face'], row['locale'])
        self.assertEqual([host().registry.card(cid).cost for cid in native.LEAVES], [2, 4]); self.assertEqual(native.COLLECTIBLE_ROOTS, ())

    def test_moonlit_both_actors_get_current_copy_and_playing_that_copy_draws_original(self):
        for player in (1, 2):
            g = self.game((PREP, MOON), deck=(UNIT,), player=player); self.play(g, PREP, player=player)
            original = self.entity(g, UNIT, player, 'deck').id; self.paid(g, MOON, player); other = self.portable(g); self.pick(other)
            root = other.state.hand_choice_followups[-1]; self.assertEqual(root.reward_mode, 'draw_original')
            copy = other.state.entities[root.initial_entity_id]; self.assertNotEqual(copy.id, original)
            self.assertEqual((copy.cost, copy.attack, copy.health), (0, 4, 6)); self.play_copy(other)
            self.assertEqual(other.state.players[player].hand, [original]); self.assertEqual(len(other.state.card_discovery_history), 1)
            root = other.state.hand_choice_followups[-1]; self.assertEqual(root.status, 'completed')
            self.assertEqual(other.state.draw_history[root.reward_draw_id-1].entity_id, original); self.portable(other)

    def test_preexisting_same_name_card_does_not_consume_the_followup(self):
        g = self.game((UNIT, MOON), deck=(UNIT,)); original = self.entity(g, UNIT, zone='deck').id
        self.paid(g, MOON); self.pick(g); self.play(g, UNIT)
        self.assertFalse(g.state.draw_history); self.assertEqual(g.state.hand_choice_followups[-1].status, 'armed')
        self.play_copy(g); self.assertEqual(g.state.players[1].hand, [original]); self.portable(g)

    def test_moonlit_original_that_leaves_and_reenters_is_not_rebound_or_replaced_by_top_draw(self):
        g = self.game((CYCLE, MOON), deck=(UNIT, FROST)); self.paid(g, MOON); self.pick(g, UNIT)
        original = selected(g.state.hand_choice_followups[-1]).card.entity_id; self.play(g, CYCLE); rng = g._rng.getstate()
        self.play_copy(g); self.assertEqual(g.state.hand_choice_followups[-1].status, 'exhausted')
        self.assertIn(original, g.state.players[1].deck); self.assertFalse(g.state.draw_history); self.assertEqual(g._rng.getstate(), rng)

    def test_moonlit_acquisition_wait_preserves_original_copy_binding_and_failed_resume(self):
        g = self.game((MOON,), deck=(UNIT,), board=(INITIAL_WAIT,)); self.paid(g, MOON); self.pick(g)
        other = self.portable(g); saved = other.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):self.choose(other, 'fault')
        self.assertEqual(other.snapshot(), saved); self.choose(other); self.play_copy(other); self.portable(other)

    def test_moonlit_actual_original_draw_wait_preserves_single_draw_id_and_no_second_discovery(self):
        g = self.game((MOON,), deck=(UNIT,), board=(ORIGINAL_WAIT,)); self.paid(g, MOON); self.pick(g); self.play_copy(g)
        self.assertEqual(len(g.state.draw_history), 1); other = self.portable(g); saved = other.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):self.choose(other, 'fault')
        self.assertEqual(other.snapshot(), saved); self.choose(other)
        self.assertEqual(len(other.state.draw_history), 1); self.assertEqual(len(other.state.card_discovery_history), 1); self.portable(other)

    def test_burned_initial_copy_never_arms_and_full_reward_hand_burns_the_true_original(self):
        g = self.game((MOON,)+(FROST,)*9, deck=(UNIT,), board=(FILL_WATCH,)); self.paid(g, MOON); self.pick(g)
        self.assertEqual(g.state.hand_choice_followups[-1].status, 'not_hand'); self.assertFalse(g.state.draw_history)
        g = self.game((MOON,)+(FROST,)*9, deck=(FILLING,)); original = self.entity(g, FILLING, zone='deck').id
        self.paid(g, MOON); self.pick(g); self.play_copy(g)
        self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD); self.assertEqual(g.state.draw_history[-1].outcome, 'burned')
        self.assertEqual(g.state.hand_choice_followups[-1].status, 'completed'); self.portable(g)

    def test_moonlit_followup_expires_and_empty_deck_does_not_consume_rng(self):
        g = self.game((MOON,), deck=(UNIT, FROST, FROST)); self.paid(g, MOON); self.pick(g, UNIT)
        g.apply(EndTurn(1)); self.assertEqual(g.state.hand_choice_followups[-1].status, 'expired'); g.apply(EndTurn(2))
        count = len(g.state.draw_history); self.play_copy(g); self.assertEqual(len(g.state.draw_history), count)
        g = self.game((MOON,)); rng = g._rng.getstate(); self.paid(g, MOON)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g._rng.getstate(), rng); self.assertFalse(g.state.card_discovery_history)

    def test_automatic_moonlit_discovery_can_arm_the_real_same_turn_copy(self):
        g = self.game((AUTO_MOON,), deck=(UNIT,)); self.play(g, AUTO_MOON)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g.state.hand_choice_followups[-1].status, 'armed')
        self.play_copy(g); self.assertEqual(len(g.state.draw_history), 1); self.portable(g)

    def test_moonlit_original_drawn_cast_and_replacement_finish_its_reserved_root_once(self):
        g = self.game((MOON,), deck=(TRAP, FROST)); self.paid(g, MOON); self.pick(g, TRAP); self.play_copy(g)
        root = g.state.hand_choice_followups[-1]
        self.assertEqual(root.status, 'completed'); self.assertEqual(root.reward_draw_id, 1)
        self.assertEqual([(r.card_id, r.parent_id)for r in g.state.draw_history], [(TRAP, None), (FROST, 1)])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2); self.portable(g)

    def test_typed_original_reward_rejects_unrelated_draw_and_finite_profile_combinations(self):
        req = ChooseFromZone(1, 1, Zone.DECK, operation='copy_current', distinct='card', source_id=3, discovery=True)
        for mode in (True, 'unknown'):
            with self.assertRaises(ValueError):DiscoverForPlayFollowup(req, mode)
        for changes in ({'operation':'copy_base'}, {'sample_size':2}, {'query':PoolQuery(kinds=(CardType.SPELL,))}, {'discovery':False}):
            with self.assertRaises(ValueError):DiscoverForPlayFollowup(replace(req, **changes), 'draw_original')
        g = self.game((MOON,), deck=(UNIT,)); self.paid(g, MOON); self.pick(g); self.play_copy(g)
        state = deepcopy(g.state); state.hand_choice_followups[-1] = replace(state.hand_choice_followups[-1], reward_draw_id=999)
        with self.assertRaisesRegex(ValueError, 'unknown'):validate_shape(state)

    def test_volume_finale_draws_three_original_spells_and_discovers_one_new_copy(self):
        for player in (1, 2):
            g = self.game((VOLUME,), deck=(UNIT, FROST, ARCANE, FIRE), mana=4, player=player)
            source = self.paid(g, VOLUME, player); self.assertEqual(len(g.state.draw_history), 3)
            self.assertTrue(all(row.source_id == source and g.registry.card(row.card_id).kind == CardType.SPELL for row in g.state.draw_history))
            self.assertEqual(len(g.state.pending_choice.options), 3); other = self.portable(g); rng = other._rng.getstate()
            self.pick(other); self.assertEqual(len(other.state.players[player].hand), 4)
            self.assertEqual(len(other.state.card_discovery_history), 1); self.assertEqual(other._rng.getstate(), rng); self.portable(other)

    def test_volume_without_finale_and_automatic_cast_have_no_discovery_fact(self):
        g = self.game((VOLUME,), deck=(FROST, ARCANE, FIRE), mana=5); self.paid(g, VOLUME)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(len(g.state.players[1].hand), 3); self.assertFalse(g.state.card_discovery_history)
        g = self.game((AUTO_VOLUME,), deck=(FROST, ARCANE, FIRE), mana=0); self.play(g, AUTO_VOLUME)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(len(g.state.players[1].hand), 3); self.assertFalse(g.state.card_discovery_history); self.portable(g)

    def test_volume_short_matching_pool_and_duplicate_faces_keep_actual_physical_options(self):
        g = self.game((VOLUME,), deck=(FROST, FROST), mana=4); self.paid(g, VOLUME)
        self.assertEqual(len(g.state.draw_history), 2); self.assertEqual([o.card_id for o in g.state.pending_choice.options], [FROST, FROST])
        original = g.state.draw_history[1].entity_id; self.pick(g, index=1)
        self.assertEqual(g.state.entities[g.state.players[1].hand[-1]].origin_entity_id, original); self.portable(g)

    def test_volume_empty_match_has_no_fatigue_rng_or_discovery(self):
        for deck in ((), (UNIT, UNIT)):
            g = self.game((VOLUME,), deck=deck, mana=4); rng = g._rng.getstate(); self.paid(g, VOLUME)
            self.assertFalse(g.state.draw_history); self.assertFalse(g.state.card_discovery_history)
            self.assertIsNone(g.state.pending_choice); self.assertEqual(g._rng.getstate(), rng)

    def test_volume_reaction_draws_do_not_join_the_original_three_options(self):
        g = self.game((VOLUME,), deck=(UNIT, FROST, ARCANE, FIRE), board=(EXTRA_WATCH,), mana=4); source = self.paid(g, VOLUME)
        self.assertEqual(len(g.state.draw_history), 4); self.assertEqual(sum(row.source_id == source for row in g.state.draw_history), 3)
        self.assertNotIn(UNIT, [o.card_id for o in g.state.pending_choice.options]); self.pick(g); self.portable(g)

    def test_volume_copy_uses_current_material_for_still_resident_original_arrivals(self):
        g = self.game((VOLUME,), deck=(FROST, ARCANE, FIRE), board=(BUFF_WATCH,), mana=4); self.paid(g, VOLUME)
        self.assertTrue(all(o.preview.cost == 0 for o in g.state.pending_choice.options)); self.pick(g)
        copied = g.state.entities[g.state.players[1].hand[-1]]
        self.assertEqual(copied.cost, 0); self.assertEqual(sum(a.spell_damage for a in copied.abilities if a.kind == 'spell_damage'), 1); self.portable(g)

    def test_volume_drawn_cast_original_is_offered_and_its_replacement_leaf_is_not_an_extra_spell(self):
        g = self.game((VOLUME,), deck=(UNIT, TRAP, FROST, FIRE), mana=4); source = self.paid(g, VOLUME)
        self.assertEqual(sum(r.source_id == source and r.parent_id is None for r in g.state.draw_history), 3)
        self.assertEqual(len(g.state.pending_choice.options), 3); self.assertIn(TRAP, [o.card_id for o in g.state.pending_choice.options])
        self.assertNotIn(UNIT, [o.card_id for o in g.state.pending_choice.options]); self.pick(g, TRAP); self.portable(g)

    def test_volume_burned_actual_roots_remain_options_with_complete_pre_draw_material(self):
        g = self.game((PREP, VOLUME)+(FROST,)*8, deck=(FROST, ARCANE, FIRE), mana=4); self.play(g, PREP)
        self.paid(g, VOLUME); self.assertEqual(len(g.state.pending_choice.options), 3)
        burned = next(row for row in g.state.draw_history if row.outcome == 'burned')
        self.pick(g, burned.card_id); created = [e for e in g.state.entities.values() if e.origin_entity_id == burned.entity_id]
        self.assertEqual(len(created), 1); self.assertEqual(created[0].zone, Zone.GRAVEYARD); self.assertEqual(created[0].cost, 0); self.portable(g)

    def test_volume_first_draw_wait_and_departed_original_keep_original_group_and_replay(self):
        g = self.game((VOLUME,), deck=(FROST, ARCANE, FIRE), board=(VOLUME_WAIT,), mana=4); self.paid(g, VOLUME)
        self.assertEqual(len(g.state.draw_history), 1); first = g.state.draw_history[0].card_id
        other = self.portable(g); saved = other.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):self.choose(other, 'fault')
        self.assertEqual(other.snapshot(), saved); self.choose(other, 'drop')
        self.assertEqual(len(other.state.pending_choice.options), 3); self.pick(other, first); self.portable(other)

    def test_volume_copy_failure_rolls_back_only_selection_after_paid_draws(self):
        g = self.game((VOLUME,), deck=(FROST, ARCANE, FIRE), board=(FAIL_COPY,), mana=4); self.paid(g, VOLUME)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):self.pick(g)
        self.assertEqual(g.snapshot(), saved); self.assertEqual(len(g.state.draw_history), 3)

    def test_spell_copy_group_profile_rejects_unrelated_slots_or_kindred(self):
        reward = DrawGroupReward('discover_spell_copy'); slots = (DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,))),)*3
        for values in ((DrawGroupSlot(),)*3, slots[:2], (DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,))),)*3):
            with self.assertRaises(ValueError):DrawPhysicalGroup(1, 3, values, reward)
        with self.assertRaises(ValueError):DrawPhysicalGroup(1, 3, slots, reward, kindred_pair=True)

    def test_final_bad_metadata_is_rejected_before_partial_registration(self):
        r = batch.registration_prefix(build_registry, 'hs_sim.cards.past_arcane_physical_discovery.register_past_arcane_physical_discovery',
            native.register_past_arcane_physical_discovery)
        r.register_pool_card(replace(host().registry.pool_card(VOLUME), cost=9)); before = r.fingerprint()
        with self.assertRaisesRegex(TargetValidationError, VOLUME):native.register_past_arcane_physical_discovery(r)
        self.assertEqual(r.fingerprint(), before)

    def test_private_records_original_scope_and_old_schema_remain_explicit(self):
        g = self.game((MOON,), deck=(UNIT,)); self.paid(g, MOON); saved = json.loads(json.dumps(g.snapshot())); saved['schema_version'] = 603
        with self.assertRaises(ValueError):Game.from_snapshot(saved, host('independent-reader').registry)
        self.assertGreaterEqual(SNAPSHOT_SCHEMA_VERSION, 604); public = json.dumps(g.for_player(2).observe())
        for word in ('reward_mode', 'reward_draw_id', 'hand_choice_followups', 'rng_state', 'resolution_frame'):
            self.assertNotIn('"'+word+'"', public)
        ref = batch.read(native.ROOT/'data/cards/past-arcane-local-reference-v1.json'); self.assertEqual(len(ref['candidate_ids']), 84)
        self.assertFalse(any(s.source_card_id == 'TIME_857'for s in host().registry.generation_scopes.values()))
