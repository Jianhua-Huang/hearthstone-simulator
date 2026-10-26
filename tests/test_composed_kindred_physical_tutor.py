"""Torga uses the complete original printed Kindred face of a physical craft."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
import test_zombeast_native_kindred_growth as native
from hs_sim.cards import build_registry
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayerSetup,
    ResolutionError, Scenario, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy, Draw,
    InvokeBehavior, RequestChoice)
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.kindred import has_native_kindred
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, DiscardCard

P = 'k577.'
WATCH = P+'watch'
TORGA, WISP = 'TLC_102', 'CORE_CS2_231'
PARTS = ('END_015', 'TLC_825', 'DINO_435')


@lru_cache(None)
def host(mode='TLC_825|normal', role='writer'):
    part, variant = mode.split('|')
    r, fmt = native.host(mode, 'k577-'+role)
    r._version += ':'+P
    def fail(c):
        raise ResolutionError('K577 intentional physical tutor failure')
    def watch(c):
        event = c.event; source = c.state.entities.get(event.source_id)
        if source is None or source.card_id != TORGA: return ()
        if variant == 'burn' and event.kind == 'minion_summoned':
            return (AddToHand(c.player_id, native.YETI, c.source_id),)*2
        if event.kind != 'card_drawn': return ()
        row = c.state.draw_history[dict(event.data)['draw_id']-1]
        if variant == 'fail-second' and row.card_id == WISP:
            return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        if row.card_id != native.recipe(part) or variant not in ('wait', 'transform', 'discard', 'nested', 'remove'):
            return ()
        effects = {
            'wait': (),
            'transform': (TransformStoredCard(CardReference.capture(c.state.entities[row.entity_id]), native.YETI, c.source_id),),
            'discard': (DiscardCard(CardReference.capture(c.state.entities[row.entity_id]), c.source_id),),
            'nested': (Draw(c.player_id, source_id=c.source_id),),
            'remove': (Destroy(source.id, c.source_id),),
        }[variant]
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'continue', effects),
            ChoiceOption('bad', 'fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
        ), c.source_id),)
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=100, metadata=native.META,
        triggers=(TriggerSpec('card_drawn', P+'watch'), TriggerSpec('minion_summoned', P+'watch'))))
    r.validate(); return r, fmt


def fixture(mode='TLC_825|normal', role='writer'):
    return host(mode, role)[0]


class ComposedKindredPhysicalTutorTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)
    pick = native.ZombeastNativeKindredGrowthTests.pick
    craft = native.ZombeastNativeKindredGrowthTests.craft

    def game(self, part='TLC_825', *, variant='normal', deck=(native.YETI, WISP, native.YETI), player=1, fillers=0):
        self.mode = part+'|'+variant; r, fmt = host(self.mode)
        hand = (native.TAMER, native.DECKCOPY, TORGA)+(native.YETI,)*fillers
        players = tuple(PlayerSetup(native.HERO, hero_power_card_id=native.POWER,
            hand=hand if p == player else (), board=(WATCH,) if p == player and variant != 'normal' else (native.UNIT,) if p != player else (),
            deck=deck if p == player else (native.YETI,)*8, mana=30, max_mana=30, mana_cap=30) for p in (1, 2))
        context = replace(fmt.context, starting_decks=tuple(p.deck for p in players))
        return Game.from_scenario(Scenario(players, active_player=player, seed=577,
            generation_context=context), r)

    def manufacture_and_store(self, g, part='TLC_825', player=1):
        eid = self.craft(g, part, player); self.play(g, native.DECKCOPY, eid, player=player)
        copy = next(i for i in g.state.players[player].deck if g.state.entities[i].card_id == native.recipe(part))
        self.assertNotEqual(copy, eid)
        return eid, copy

    def roots(self, g, source):
        return [row for row in g.state.draw_history if row.source_id == source]

    def test_shared_native_predicate_preserves_originals_and_resolves_three_complete_composed_faces(self):
        r = build_registry(); before = r.fingerprint()
        for part in PARTS:
            self.assertTrue(has_native_kindred(r, part))
            self.assertTrue(has_native_kindred(r, native.recipe(part)))
        self.assertFalse(has_native_kindred(r, native.recipe('TLC_827')))
        self.assertFalse(has_native_kindred(r, WISP)); self.assertFalse(has_native_kindred(r, native.FORGE))
        self.assertEqual(r.fingerprint(), before)

    def test_all_three_real_manufactured_deck_copies_tutor_original_physical_cards_and_activators(self):
        for index, part in enumerate(PARTS):
            with self.subTest(part=part):
                player = 1+index%2; g = self.game(part, player=player)
                original, copied = self.manufacture_and_store(g, part, player)
                source = self.play(g, TORGA, player=player); rows = self.roots(g, source)
                self.assertEqual([row.card_id for row in rows], [native.recipe(part), WISP])
                self.assertEqual(rows[0].entity_id, copied)
                self.assertEqual(g.state.entities[original].zone, Zone.HAND)
                self.assertEqual(g.state.entities[copied].zone, Zone.HAND)
                self.assertEqual(g.state.entities[copied].controller, player)
                self.assertEqual(g.state.players[player].mana, 29-g.registry.card(TORGA).cost)

    def test_first_compound_draw_wait_restores_original_pair_and_bad_resume_is_atomic(self):
        g = self.game(variant='wait'); _, copied = self.manufacture_and_store(g)
        source = self.play(g, TORGA); saved = g.snapshot(); other = self.portable(g)
        with self.assertRaisesRegex(ResolutionError, 'K577 intentional'): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for current in (g, other): self.choose(current, 'ok')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual([r.card_id for r in self.roots(g, source)], [native.recipe('TLC_825'), WISP])
        self.assertEqual(g.state.entities[copied].zone, Zone.HAND)

    def test_first_compound_transformed_during_draw_still_supplies_original_full_type(self):
        g = self.game(variant='transform'); _, copied = self.manufacture_and_store(g)
        source = self.play(g, TORGA); other = self.portable(g)
        for current in (g, other): self.choose(current, 'ok')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.entities[copied].card_id, native.YETI)
        self.assertEqual([r.card_id for r in self.roots(g, source)], [native.recipe('TLC_825'), WISP])

    def test_discarded_first_compound_does_not_remove_original_second_selector(self):
        g = self.game(variant='discard'); _, copied = self.manufacture_and_store(g)
        source = self.play(g, TORGA); self.choose(g, 'ok')
        self.assertEqual(g.state.entities[copied].zone, Zone.GRAVEYARD)
        self.assertEqual([r.card_id for r in self.roots(g, source)], [native.recipe('TLC_825'), WISP])

    def test_nested_plain_draw_does_not_become_the_original_kindred_subject(self):
        g = self.game(variant='nested'); self.manufacture_and_store(g)
        source = self.play(g, TORGA); self.choose(g, 'ok')
        self.assertEqual([r.card_id for r in self.roots(g, source)], [native.recipe('TLC_825'), WISP])
        self.assertEqual([r.card_id for r in g.state.draw_history], [native.recipe('TLC_825'), native.YETI, WISP])

    def test_burned_first_compound_retains_original_qualification_and_activation_type(self):
        g = self.game(variant='burn', fillers=7); _, copied = self.manufacture_and_store(g)
        source = self.play(g, TORGA); rows = self.roots(g, source)
        self.assertEqual([r.card_id for r in rows], [native.recipe('TLC_825'), WISP])
        self.assertEqual(g.state.entities[copied].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand), 10)

    def test_no_matching_activator_keeps_compound_first_without_fallback_or_fatigue(self):
        g = self.game(deck=(native.YETI,)); self.manufacture_and_store(g)
        source = self.play(g, TORGA)
        self.assertEqual([r.card_id for r in self.roots(g, source)], [native.recipe('TLC_825')])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck], [native.YETI])

    def test_plain_composition_is_not_kindred_and_does_not_become_a_fallback_draw(self):
        part = 'TLC_827'; g = self.game(part); self.manufacture_and_store(g, part)
        before = g._rng.getstate(); self.play(g, TORGA)
        self.assertFalse(g.state.draw_history); self.assertEqual(g._rng.getstate(), before)
        self.assertEqual(len(g.state.players[1].deck), 4)

    def test_second_draw_failure_rolls_back_both_original_physical_draws_payment_and_rng(self):
        g = self.game(variant='fail-second'); self.manufacture_and_store(g); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K577 intentional'): self.play(g, TORGA)
        self.assertEqual(g.snapshot(), saved)

    def test_rehashed_first_root_cannot_borrow_plain_face_qualification(self):
        g = self.game(variant='wait'); self.manufacture_and_store(g); self.play(g, TORGA)
        bad = deepcopy(g.snapshot()); bad['state']['draw_history'][0]['card_id'] = native.YETI
        bad['state_hash'] = canonical_hash(bad['state'])
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, fixture(self.mode, 'independent-reader'))

    def test_unapproved_native_part_is_an_explicit_error_instead_of_a_cropped_candidate(self):
        r = build_registry(); r._crafted_minion_parts.remove('TLC_825')
        with self.assertRaises(UnsupportedDefinitionError): has_native_kindred(r, native.recipe('TLC_825'))

    def test_actual_drawn_compound_plays_original_kindred_after_real_previous_owner_turn(self):
        g = self.game(); _, copied = self.manufacture_and_store(g); self.play(g, TORGA)
        self.play(g, WISP); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        original = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == native.recipe('TLC_825') and i != copied)
        self.assertLess(g.state.players[1].hand.index(original), g.state.players[1].hand.index(copied))
        # Play both actual copies with their independently installed native bodies.
        target = g.state.players[2].board[0]
        self.play(g, native.recipe('TLC_825'), target)
        self.play(g, native.recipe('TLC_825'), target)
        self.assertEqual(g.state.kindred_history[-1].source.entity_id, copied)
        self.assertTrue(g.state.kindred_history[-1].condition.matched)
        self.assertEqual(g.state.entities[target].health, 100-2*g.state.entities[copied].attack)

    def test_source_removed_after_first_compound_draw_keeps_original_player_and_second_draw(self):
        g = self.game(variant='remove', player=2); self.manufacture_and_store(g, player=2)
        source = self.play(g, TORGA, player=2); other = self.portable(g)
        for current in (g, other): self.choose(current, 'ok')
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertTrue(all(r.player_id == 2 for r in self.roots(g, source)))
        self.assertEqual([r.card_id for r in self.roots(g, source)], [native.recipe('TLC_825'), WISP])


if __name__ == '__main__':
    unittest.main()
