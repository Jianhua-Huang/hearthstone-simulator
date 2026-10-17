"""Actual three-end story and bounded named fill through public actions."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_lakkari_story_cards import CARD, IMP, SPEC, load_batch, register_native_lakkari_story_cards
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    FillBoardWithCard, Game, Keyword, PlayCard, PlayerSetup, Rarity, Registry, RewindSpec,
    Ruleset, Scenario, SelectChoice, SummonQuantitySpec, Zone)
from hs_sim.engine.effects import ChoiceOption, Damage, Destroy, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError, ResolutionLimitExceeded, SnapshotError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.ordered_group_batches import StartOrderedGroupEntry, SummonOrderedGroup
from hs_sim.engine.player_effects import RemovePlayerEffect
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import canonical_digest

P = 'k157.'
HERO, PLAIN = P + 'hero', P + 'plain'
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.NONE, tribes=())


@lru_cache(maxsize=4)
def registry(role, mode='normal'):
    assert role in ('writer', 'reader') and mode in ('normal', 'unknown')
    r = Registry('k157-native-lakkari-' + mode + '-v1')
    register_native_lakkari_story_cards(r)
    raw = load_batch()['existing_dependencies'][0]['record']
    if mode == 'normal':
        r.register_card(CardDefinition(IMP, raw['name'], CardType.MINION, cost=raw['cost'],
            attack=raw['attack'], health=raw['health'], metadata=metadata_from_record(raw)))
    r.register_card(CardDefinition(HERO, 'Warlock fixture', CardType.HERO, health=30,
        metadata=CardMetadata(False, (CardClass.WARLOCK,), Rarity.NONE, tribes=())))
    r.register_card(CardDefinition(PLAIN, 'Plain fixture', CardType.MINION, cost=1, attack=1, health=5, metadata=META))
    r.register_card(CardDefinition(P + 'dormant', 'Dormant physical slot', CardType.MINION,
        health=5, dormant_turns=2, metadata=META))
    r.register_behavior(P + 'noop', lambda c: ())
    r.register_card(CardDefinition(P + 'location', 'Location physical slot', CardType.LOCATION,
        durability=3, on_use=P + 'noop', metadata=META))
    r.register_card(CardDefinition(P + 'quantity', 'Quantity fixture', CardType.MINION,
        health=5, summon_quantities=(SummonQuantitySpec(),), metadata=META))
    def fail(c): raise ResolutionError('deliberate K157 rollback')
    r.register_behavior(P + 'raise_failure', fail)
    r.register_trigger_condition(P + 'is_imp', lambda c: c.event.target_id is not None and
        c.state.entities[c.event.target_id].card_id == IMP)
    for action in ('entry_wait', 'kill', 'occupy', 'fail', 'terminal', 'discard_wait', 'discard_summon'):
        key = P + action
        def watch(c, action=action):
            if action in ('entry_wait', 'discard_wait'):
                extra = () if action == 'entry_wait' else (SummonByCard(c.player_id,
                    (SummonEntryMaterial(PLAIN),), SummonCause.capture(c)),)
                return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue', extra),), c.source_id),)
            if action == 'kill': return (Destroy(c.event.target_id),)
            if action in ('occupy', 'discard_summon'):
                return (SummonByCard(c.player_id, (SummonEntryMaterial(PLAIN),), SummonCause.capture(c)),)
            if action == 'terminal': return (Damage(c.state.players[2].hero_id, 100, c.source_id),)
            return (InvokeBehavior(P + 'raise_failure', c.source_id, c.player_id),)
        r.register_behavior(key, watch)
        discard = action.startswith('discard_')
        trigger = LimitedTriggerSpec('card_discarded' if discard else 'minion_summoned', key,
            condition_id='always' if discard else P + 'is_imp', uses=100)
        r.register_card(CardDefinition(key, key, CardType.MINION, health=5, metadata=META, limited_triggers=(trigger,)))
    r.register_behavior(P + 'fill', lambda c: (FillBoardWithCard(c.player_id, IMP, SummonCause.capture(c)),))
    for name in ('fill', 'rewind'):
        r.register_card(CardDefinition(P + name, name, CardType.SPELL, cost=1, on_play=P + 'fill', metadata=META,
            keywords=(Keyword.REWIND,) if name == 'rewind' else (), rewind=RewindSpec() if name == 'rewind' else None))
    r.register_behavior(P + 'remove', lambda c: (RemovePlayerEffect(c.player_id,
        c.state.players[c.player_id].player_effects[0].id),))
    r.register_card(CardDefinition(P + 'remove', 'Remove one instance', CardType.SPELL, on_play=P + 'remove', metadata=META))
    r.validate(); r.freeze()
    return r


class NativeLakkariStoryTests(unittest.TestCase):
    def game(self, hand=(CARD,), board=(), limit=4, mode='normal', steps=1000):
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO, hand=hand, board=board, deck=(PLAIN,) * 24, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup(HERO, deck=(PLAIN,) * 24)), seed=31), registry('writer', mode),
            Ruleset(max_board=limit, max_mana=30, max_resolution_steps=steps))
    def play(self, g, cid=CARD):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid)); return eid
    def choose(self, g, option='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (option,)))
    def imps(self, g): return [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == IMP]
    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot())); a, b = registry('writer', mode), registry('reader', mode)
        self.assertIsNot(a, b); self.assertEqual(a.fingerprint(), b.fingerprint())
        other = Game.from_snapshot(saved, b)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), b).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.observe(player)) + json.dumps(g.player_events(player))
            for field in ('fill_capacity', 'fill_card', 'ordered_group_history', 'resolution_frame'):
                self.assertNotIn('"' + field + '"', public)
        return other
    def rehash(self, saved):
        saved['events_hash'] = canonical_hash(saved['events'])
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        return saved

    def test_01_real_story_pays_once_discards_and_runs_exactly_three_owner_ends(self):
        g = self.game(hand=(CARD, PLAIN, PLAIN, PLAIN)); source = self.play(g)
        self.assertEqual(g.state.players[1].mana, 23)
        self.assertEqual(g.state.players[1].player_effects[0].remaining_turns, 3); self.portable(g)
        for index in range(3):
            g.apply(EndTurn(1)); self.assertEqual(len(g.state.ordered_group_history), index+1)
            self.assertEqual(len(self.imps(g)), 4)
            if index < 2: self.assertEqual(g.state.players[1].player_effects[0].remaining_turns, 2-index)
            else: self.assertFalse(g.state.players[1].player_effects)
            roots = len(g.state.ordered_group_history); g.apply(EndTurn(2))
            self.assertEqual(len(g.state.ordered_group_history), roots)
        g.apply(EndTurn(1)); self.assertEqual(len(g.state.ordered_group_history), 3)
        self.assertEqual(sum(e.kind == 'card_discarded' and e.source_id == source for e in g.events), 3)
        for root in g.state.ordered_group_history:
            self.assertEqual((root.request.group.cause.origin, root.request.group.cause.cast_id), ('card_effect', None))
            self.assertEqual(root.request.group.cause.source.entity_id, source)
        self.assertEqual(len(g.state.cast_history), 1); self.portable(g)

    def test_02_empty_hand_does_not_gate_fill_or_consume_rng(self):
        g = self.game(); self.play(g); rng = g.snapshot()['rng_state']; g.apply(EndTurn(1))
        self.assertEqual(len(self.imps(g)), 4); self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertFalse(any(e.kind == 'card_discarded' for e in g.events)); self.portable(g)

    def test_03_actual_rule_limit_and_dormant_location_occupants_determine_initial_count(self):
        for limit in (3, 5, 8):
            g = self.game(board=(P + 'dormant', P + 'location'), limit=limit); self.play(g); g.apply(EndTurn(1))
            root, = g.state.ordered_group_history; cap = root.request.fill_capacity
            self.assertEqual((cap.limit, len(cap.occupants), cap.remaining), (limit, 2, limit-2))
            self.assertEqual(len(self.imps(g)), limit-2); self.assertEqual(len(root.selection.occurrences), limit-2)
            self.portable(g)

    def test_04_later_deaths_do_not_extend_original_fill_attempt_count(self):
        g = self.game(board=(P + 'kill',), limit=5); self.play(g); g.apply(EndTurn(1))
        root, = g.state.ordered_group_history
        self.assertEqual((root.request.fill_capacity.remaining, len(root.entry_root_ids)), (4, 4))
        self.assertFalse(self.imps(g)); self.assertEqual(len(g.state.players[1].board), 1)
        self.assertEqual(sum(e.kind == 'minion_died' and g.state.entities[e.target_id].card_id == IMP for e in g.events), 4)
        self.portable(g)

    def test_05_later_occupations_do_not_resize_original_group(self):
        g = self.game(board=(P + 'occupy',), limit=5); self.play(g); g.apply(EndTurn(1))
        root, = g.state.ordered_group_history
        self.assertEqual((root.request.fill_capacity.remaining, len(root.entry_root_ids)), (4, 4))
        self.assertEqual(len(self.imps(g)), 2); self.assertEqual(len(g.state.players[1].board), 5); self.portable(g)

    def test_06_discard_reactions_complete_before_capacity_acceptance(self):
        g = self.game(hand=(CARD, PLAIN), board=(P + 'discard_summon',)); self.play(g); g.apply(EndTurn(1))
        root, = g.state.ordered_group_history
        self.assertEqual((len(root.request.fill_capacity.occupants), root.request.fill_capacity.remaining), (2, 2))
        self.assertEqual(len(self.imps(g)), 2); self.portable(g)

    def test_07_discard_wait_restores_before_fill_root_then_captures_new_occupant(self):
        g = self.game(hand=(CARD, PLAIN), board=(P + 'discard_wait',)); self.play(g); g.apply(EndTurn(1))
        self.assertFalse(g.state.ordered_group_history); self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g)
        for game in (g, other): self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.ordered_group_history[0].request.fill_capacity.remaining, 2); self.portable(g)

    def test_08_entry_wait_retains_original_capacity_and_owed_group_tail(self):
        g = self.game(board=(P + 'entry_wait',)); self.play(g); g.apply(EndTurn(1))
        root, = g.state.ordered_group_history
        self.assertEqual((root.request.fill_capacity.remaining, len(root.entry_root_ids)), (3, 1))
        other = self.portable(g); rng = g.snapshot()['rng_state']
        while g.state.pending_choice:
            for game in (g, other): self.choose(game)
            self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(self.imps(g)), 3); self.assertEqual(g.snapshot()['rng_state'], rng); self.portable(g)

    def test_09_crop_owed_entry_and_rehash_capacity_edits_reject_restore(self):
        g = self.game(board=(P + 'entry_wait',)); self.play(g); g.apply(EndTurn(1))
        bad = g.clone(); f = bad._frame
        self.assertEqual(sum(type(w) is StartOrderedGroupEntry for w in (*f.prefix, *f.continuation)), 1)
        bad._frame = replace(f, prefix=tuple(w for w in f.prefix if type(w) is not StartOrderedGroupEntry),
            continuation=tuple(w for w in f.continuation if type(w) is not StartOrderedGroupEntry))
        with self.assertRaises((ValueError, SnapshotError)): Game.from_snapshot(bad.snapshot(), registry('reader'))
        for field, value in (('limit', 7), ('occupants', [])):
            saved = g.snapshot(); saved['state']['ordered_group_history'][0]['request']['fill_capacity'][field] = value
            with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(saved), registry('reader'))

    def test_10_full_board_retains_zero_group_named_recipe_without_random(self):
        g = self.game(board=(PLAIN,) * 4); self.play(g); rng = g.snapshot()['rng_state']; g.apply(EndTurn(1))
        root, = g.state.ordered_group_history
        self.assertEqual((root.request.fill_capacity.remaining, root.selection.occurrences, root.entry_root_ids), (0, (), ()))
        self.assertEqual(root.request.fill_card.card_id, IMP); self.assertEqual(root.status, 'completed')
        self.assertEqual(g.snapshot()['rng_state'], rng); self.portable(g)

    def test_11_unknown_named_material_rejects_even_full_and_rolls_back_owner_end(self):
        for board in ((), (PLAIN,) * 4):
            g = self.game(hand=(CARD, PLAIN), board=board, mode='unknown'); self.play(g); before = g.snapshot()
            with self.assertRaises((ValueError, ResolutionError)): g.apply(EndTurn(1))
            self.assertEqual(g.snapshot(), before)

    def test_12_entry_failure_rolls_back_discard_clock_group_and_random(self):
        g = self.game(hand=(CARD, PLAIN), board=(P + 'fail',)); self.play(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(), before); self.portable(g)

    def test_13_entry_terminal_preserves_actual_prefix_and_interrupts_group(self):
        g = self.game(board=(P + 'terminal',)); self.play(g); g.apply(EndTurn(1))
        self.assertNotEqual(g.state.status, 'playing'); root, = g.state.ordered_group_history
        self.assertEqual((root.status, len(root.entry_root_ids), len(self.imps(g))), ('interrupted', 1, 1)); self.portable(g)

    def test_14_quantity_extras_use_child_execution_without_extending_fill_originals(self):
        g = self.game(board=(P + 'quantity',), limit=3); self.play(g); g.apply(EndTurn(1))
        root, = g.state.ordered_group_history
        self.assertEqual((len(root.selection.occurrences), len(root.entry_root_ids)), (2, 2))
        self.assertEqual(len(self.imps(g)), 2); self.portable(g)

    def test_15_duplicate_stories_have_separate_sources_clocks_and_fill_windows(self):
        g = self.game(hand=(CARD, CARD, PLAIN, PLAIN)); a, b = self.play(g), self.play(g)
        self.assertNotEqual(a, b); self.assertEqual(g.state.players[1].mana, 16); g.apply(EndTurn(1))
        roots = g.state.ordered_group_history
        self.assertEqual([r.request.group.cause.source.entity_id for r in roots], [a, b])
        self.assertEqual([r.request.fill_capacity.remaining for r in roots], [4, 0])
        self.assertEqual([e.remaining_turns for e in g.state.players[1].player_effects], [2, 2]); self.portable(g)

    def test_16_removed_instance_has_no_later_trigger_or_clock(self):
        g = self.game(hand=(CARD, P + 'remove')); self.play(g); self.play(g, P + 'remove'); g.apply(EndTurn(1))
        self.assertFalse(g.state.players[1].player_effects); self.assertFalse(g.state.ordered_group_history); self.portable(g)

    def test_17_public_named_fill_retry_retires_first_group_and_replays_final_capacity(self):
        g = self.game(hand=(P + 'rewind',)); self.play(g, P + 'rewind')
        self.assertEqual(len(self.imps(g)), 4); self.portable(g); self.choose(g, 'retry')
        self.assertEqual(len(self.imps(g)), 4); self.assertEqual(g.state.players[1].mana, 29)
        self.assertEqual(len(g.state.ordered_group_history), 1); self.portable(g)

    def test_18_finite_fill_request_requires_both_facts_and_plain_original_occurrences(self):
        g = self.game(); self.play(g); g.apply(EndTurn(1)); request = g.state.ordered_group_history[0].request
        for change in (dict(fill_capacity=None), dict(fill_card=None), dict(bonus_effects=True),
                dict(group=replace(request.group, members=request.group.members[:-1])),
                dict(fill_card=SummonEntryMaterial(IMP, keywords=(Keyword.TAUNT,)))):
            with self.subTest(change=change):
                with self.assertRaises(ValueError): replace(request, **change)
        plain = SummonOrderedGroup(replace(request.group, members=()))
        self.assertIsNone(plain.fill_capacity); self.assertIsNone(plain.fill_card)
        saved = g.snapshot(); saved['schema_version'] -= 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry('reader'))

    def test_19_raw_primary_links_and_central_existing_imp_are_exact(self):
        data = load_batch(); self.assertEqual((len(data['cards']), len(data['existing_dependencies']), len(data['official_observations'])), (1, 1, 4))
        self.assertEqual(len(data['exact_parent_child_links']), 2)
        self.assertEqual(canonical_digest(asdict(registry('writer').card(IMP))), data['existing_definition_sha256'])
        from hs_sim.cards.constructed import build_registry
        r = build_registry(); r.freeze()
        self.assertEqual(asdict(r.card(CARD)), asdict(registry('writer').card(CARD)))
        self.assertEqual(asdict(r.card(IMP)), asdict(registry('writer').card(IMP)))
        self.assertEqual((r.player_effect(SPEC).duration, r.player_effect(SPEC).tick_event), (3, 'turn_ended'))

    def test_20_fill_capacity_budget_rejects_before_materializing_huge_group(self):
        g = self.game(limit=2000, steps=100); self.play(g); before = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded): g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(), before)


if __name__ == '__main__': unittest.main()
