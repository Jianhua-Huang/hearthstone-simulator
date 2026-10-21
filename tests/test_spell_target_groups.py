"""Joint-arrow preparation for Flame Shock; no activation is claimed here."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (CardDefinition, CardMetadata, CardClass, CardType, Game, Keyword,
    PlayerSetup, Scenario, SpellSchool, TargetSpec, Zone)
from hs_sim.engine.spell_target_groups import (SpellTargetGroupPlan, SpellTargetGroupSelection,
    prepare_spell_target_group, spell_target_group_selections, validate_spell_target_group)
from hs_sim.targets import canonical_digest

CARD = 'BE_302'
P = 'k355.'
PLAIN, STEALTH, ELUSIVE, IMMUNE, DORMANT, TARGETLESS = (P+x for x in
    ('plain', 'stealth', 'elusive', 'immune', 'dormant', 'targetless'))
PACKET = Path(__file__).resolve().parents[1]/'data/cards/flame-shock-v1.json'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(maxsize=1)
def registry():
    r = build_registry()
    raw = json.loads(PACKET.read_text(encoding='utf-8'))['cards'][0]['record']
    r.register_behavior(P+'unexecuted', lambda c: ())
    # The fixture supplies the real target domain, never an executable card adapter.
    r.register_card(CardDefinition(CARD, raw['name'], CardType.SPELL, cost=raw['cost'],
        metadata=metadata_from_record(raw), spell_school=SpellSchool.FIRE,
        on_play=P+'unexecuted', targeting=TargetSpec(relation='enemy')))
    r.register_card(CardDefinition(TARGETLESS, TARGETLESS, CardType.SPELL, metadata=META))
    for cid, keyword in ((PLAIN, None), (STEALTH, Keyword.STEALTH), (ELUSIVE, Keyword.ELUSIVE),
                         (IMMUNE, Keyword.IMMUNE), (DORMANT, None)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1, attack=3, health=5,
            metadata=META, keywords=() if keyword is None else (keyword,),
            dormant_turns=2 if cid == DORMANT else 0))
    r.freeze()
    return r


class SpellTargetGroupTests(unittest.TestCase):
    def game(self, enemy=(PLAIN,), *, seat=1, own=(PLAIN,)):
        players = [PlayerSetup('HERO_08', hand=(CARD, TARGETLESS), board=own, mana=10, max_mana=10),
                   PlayerSetup('HERO_08', board=enemy, mana=10, max_mana=10)]
        if seat == 2:
            players.reverse()
        return Game.from_scenario(Scenario(tuple(players), active_player=seat, seed=355), registry())

    def source(self, g, seat=1, card=CARD):
        return next(i for i in g._state.players[seat].hand if g._state.entities[i].card_id == card)

    def plan(self, g, *, seat=1, automatic=False, min_count=2, max_count=2, definition=None):
        return prepare_spell_target_group(g._state, g.registry, self.source(g, seat), seat,
            min_count=min_count, max_count=max_count, automatic=automatic, definition=definition)

    def check(self, g, selection, *, seat=1, automatic=False, min_count=2, max_count=2, definition=None):
        return validate_spell_target_group(g._state, g.registry, selection, self.source(g, seat), seat,
            min_count=min_count, max_count=max_count, automatic=automatic, definition=definition)

    def test_real_source_and_both_complete_primary_faces_preserve_two_enemy_text_and_overload(self):
        packet = json.loads(PACKET.read_text(encoding='utf-8'))
        row = packet['cards'][0]
        self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        raw = row['record']
        self.assertEqual((raw['id'], raw['dbf_id'], raw['cost'], raw['tags']['CLASS'],
            raw['tags']['SPELL_SCHOOL']), (CARD, 130974, 1, 8, 2))
        self.assertEqual(raw['text_en'], 'Deal $2 damage to two different enemies. <b>Overload:</b> (1).')
        self.assertEqual({x['locale'] for x in packet['official_observations']}, {'en_US', 'zh_CN'})
        for face in packet['official_observations']:
            self.assertEqual(face['face']['id'], raw['dbf_id'])
        self.assertFalse(packet['behavior_verified'])

    def test_manual_domain_keeps_enemy_hero_and_excludes_real_target_protections_and_dormancy(self):
        g = self.game((PLAIN, STEALTH, ELUSIVE, IMMUNE, DORMANT))
        plan = self.plan(g)
        self.assertEqual(set(plan.target_ids), {g._state.players[2].hero_id, g._state.players[2].board[0]})
        self.assertFalse(set(plan.target_ids) & {g._state.players[1].hero_id, *g._state.players[1].board})

    def test_automatic_domain_reuses_automatic_eligibility_including_protected_enemies(self):
        g = self.game((PLAIN, STEALTH, ELUSIVE, IMMUNE, DORMANT))
        plan = self.plan(g, automatic=True)
        enemy = g._state.players[2]
        self.assertEqual(set(plan.target_ids), {enemy.hero_id, *enemy.board[:-1]})
        self.assertNotIn(enemy.board[-1], plan.target_ids)

    def test_distinct_arrows_preserve_original_player_order(self):
        g = self.game(); plan = self.plan(g); first, second = plan.target_ids
        a = SpellTargetGroupSelection(plan, (first, second))
        b = SpellTargetGroupSelection(plan, (second, first))
        self.assertEqual(tuple(x.entity_id for x in a.targets), (first, second))
        self.assertEqual(tuple(x.entity_id for x in b.targets), (second, first))
        self.assertEqual(self.check(g, a), a)
        self.assertEqual(self.check(g, b), b)
        with self.assertRaises(ValueError):
            SpellTargetGroupSelection(plan, (first, first))

    def test_enumeration_retains_every_ordered_distinct_submission_once(self):
        g = self.game((PLAIN, PLAIN)); plan = self.plan(g)
        result = tuple(spell_target_group_selections(plan))
        self.assertEqual(len(result), 6)
        self.assertEqual(len({x.target_ids for x in result}), 6)
        for row in result:
            self.assertEqual(len(set(row.target_ids)), 2)
            self.check(g, row)

    def test_only_one_enemy_never_invents_a_second_target_for_an_exact_two_request(self):
        g = self.game(()); plan = self.plan(g)
        self.assertEqual(plan.target_ids, (g._state.players[2].hero_id,))
        self.assertEqual(tuple(spell_target_group_selections(plan)), ())
        with self.assertRaises(ValueError):
            SpellTargetGroupSelection(plan, plan.target_ids)

    def test_partial_count_requires_independent_explicit_producer_policy(self):
        g = self.game(()); plan = self.plan(g, min_count=1)
        selection, = spell_target_group_selections(plan)
        self.check(g, selection, min_count=1)
        with self.assertRaises(ValueError):
            self.check(g, selection)

    def test_no_rng_mana_history_events_or_state_are_changed_by_prepare_select_or_validate(self):
        g = self.game((PLAIN, PLAIN)); before = g.snapshot(); rng = g._rng.getstate()
        for selection in spell_target_group_selections(self.plan(g, automatic=True)):
            self.check(g, selection, automatic=True)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(g._rng.getstate(), rng)

    def test_complete_original_domain_cannot_be_cropped_even_when_selection_still_fits(self):
        g = self.game((PLAIN, PLAIN)); plan = self.plan(g)
        cropped = replace(plan, candidates=plan.candidates[:2])
        selected = SpellTargetGroupSelection(cropped, cropped.target_ids)
        with self.assertRaises(ValueError):
            self.check(g, selected)
        with self.assertRaises(ValueError):
            replace(plan, candidates=tuple(reversed(plan.candidates)))

    def test_effective_definition_is_bound_to_independent_actual_producer_input(self):
        g = self.game(); definition = replace(g.registry.card(CARD), targeting=TargetSpec(relation='friendly'))
        plan = self.plan(g, definition=definition)
        selection = next(spell_target_group_selections(plan))
        self.check(g, selection, definition=definition)
        with self.assertRaises(ValueError):
            self.check(g, selection)
        with self.assertRaises(ValueError):
            self.plan(g, definition=replace(definition, id='borrowed.spell'))

    def test_original_physical_facts_are_detached_and_later_residence_is_not_the_original_window(self):
        g = self.game(); plan = self.plan(g); selection = next(spell_target_group_selections(plan))
        state = deepcopy(g._state); original = deepcopy(selection)
        state.entities[plan.target_ids[-1]].zone_epoch += 1
        self.assertEqual(selection, original)
        with self.assertRaises(ValueError):
            validate_spell_target_group(state, g.registry, selection, self.source(g), 1, min_count=2, max_count=2)
        self.check(g, selection)

    def test_live_target_protection_change_requires_a_new_complete_window(self):
        g = self.game(); selection = next(spell_target_group_selections(self.plan(g)))
        state = deepcopy(g._state); state.entities[g._state.players[2].board[0]].keywords.add(Keyword.STEALTH)
        with self.assertRaises(ValueError):
            validate_spell_target_group(state, g.registry, selection, self.source(g), 1, min_count=2, max_count=2)

    def test_automatic_effect_player_does_not_overwrite_physical_source_controller(self):
        g = self.game(); source = self.source(g)
        plan = prepare_spell_target_group(g._state, g.registry, source, 2,
            min_count=2, max_count=2, automatic=True)
        self.assertEqual((plan.player_id, plan.source.controller), (2, 1))
        self.assertEqual(set(plan.target_ids), {g._state.players[1].hero_id, *g._state.players[1].board})
        with self.assertRaises(ValueError):
            prepare_spell_target_group(g._state, g.registry, source, 2, min_count=2, max_count=2)

    def test_second_seat_uses_its_actual_opponent(self):
        g = self.game(seat=2); plan = self.plan(g, seat=2)
        self.assertEqual(set(plan.target_ids), {g._state.players[1].hero_id, *g._state.players[1].board})
        self.check(g, next(spell_target_group_selections(plan)), seat=2)

    def test_shape_rejects_boolean_duplicate_missing_and_foreign_targets(self):
        g = self.game(); plan = self.plan(g)
        for targets in ([*plan.target_ids], (True, plan.target_ids[-1]), (plan.target_ids[0],),
                        (plan.target_ids[0], g._state.players[1].hero_id)):
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                SpellTargetGroupSelection(plan, targets)
        for changes in ({'automatic': 1}, {'min_count': True}, {'max_count': 1}, {'candidates': list(plan.candidates)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(plan, **changes)

    def test_candidate_facts_cannot_borrow_another_allocator_window(self):
        g = self.game(); plan = self.plan(g)
        fact = replace(plan.candidates[0], next_entity_id=plan.source.next_entity_id+1)
        with self.assertRaises(ValueError):
            replace(plan, candidates=(fact, *plan.candidates[1:]))

    def test_source_player_mode_and_count_are_not_self_certified_from_a_supplied_plan(self):
        g = self.game(); selection = next(spell_target_group_selections(self.plan(g)))
        for kwargs in ({'min_count': 1}, {'max_count': 3}, {'automatic': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.check(g, selection, **kwargs)
        with self.assertRaises(ValueError):
            validate_spell_target_group(g._state, g.registry, selection, self.source(g), 2,
                min_count=2, max_count=2, automatic=True)

    def test_targetless_nonspell_and_unknown_physical_sources_cannot_acquire_arrows(self):
        g = self.game()
        for source in (self.source(g, card=TARGETLESS), g._state.players[1].board[0], g._state.next_entity_id):
            with self.subTest(source=source), self.assertRaises(ValueError):
                prepare_spell_target_group(g._state, g.registry, source, 1, min_count=2, max_count=2)


if __name__ == '__main__':
    unittest.main()
