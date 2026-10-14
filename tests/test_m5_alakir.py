"""Al'Akir: settled attack capture, two-card generation and existing public contracts."""
from hs_sim.engine.model import CostAuraSpec
import json
import unittest

from hs_sim.engine import (Attack, AuraSpec, CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, Herald, IllegalAction, Keyword, PlayCard, PlayerSetup, ResolutionError,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.costs import local_cost, quote_cost
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, GainArmor, RequestChoice, ReturnToHand, SetStats, Silence, Summon, Transform)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec, PaymentType, Rarity
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.representative import build_registry, ATTACK_COST_POOL_ID, ATTACK_COST_POOL_IDS
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, CopyCard


CONTEXT = GenerationContext('local-2026-09-23', 'experimental')


class AlakirTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.r.register_card(CardDefinition('shaman', 'Shaman fixture', CardType.HERO, health=30,
            metadata=CardMetadata(False, (CardClass.SHAMAN,), None)))
        self.minion('plain', attack=1, health=9)
        self.r.register_behavior('noop', lambda c: [])
        self.r.register_card(CardDefinition('site', 'Site fixture', CardType.LOCATION, durability=2, on_use='noop'))
        self.spell('kill', lambda c: [Destroy(c.target_id)], requires_target=True)
        self.spell('silence', lambda c: [Silence(c.target_id)], requires_target=True)
        self.spell('bounce', lambda c: [ReturnToHand(c.target_id)], requires_target=True)
        self.spell('copy', lambda c: [CopyMinion(c.target_id, 1)], requires_target=True)
        self.spell('summon', lambda c: [Summon(1, 'CATA_153')])
        for count in (2, 4):
            self.spell(f'herald{count}', lambda c, count=count:
                [*[Herald(1, c.source_id) for _ in range(count)],
                 *[Destroy(i) for i in c.state.players[1].board]])
    def minion(self, name, **kw):
        self.r.register_card(CardDefinition(name, name, CardType.MINION, **kw))
    def spell(self, name, fn, **kw):
        self.r.register_behavior(name, fn)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, **kw))
    def watch(self, event, fn):
        self.r.register_behavior('watch', fn)
        self.minion('watch', health=9, triggers=(TriggerSpec(event, 'watch'),))
    def game(self, hand=('CATA_153',), board=(), enemy=(), context=CONTEXT, seed=157):
        return Game.from_scenario(Scenario((
            PlayerSetup('shaman', hand=hand, board=board, deck=('plain',)*8, max_mana=10, mana=10),
            PlayerSetup('HERO_01', board=enemy, deck=('plain',)*8, max_mana=10, mana=10)),
            generation_context=context, seed=seed), self.r)
    def play(self, g, card, target=None, position=None):
        i = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == card)
        g.apply(PlayCard(1, i, target, position)); return i
    def body(self, g):
        return next(g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == 'CATA_153')
    def bodies(self, c):
        return [i for i in c.state.players[1].board if c.state.entities[i].card_id == 'CATA_153']
    def generated(self, g):
        return [g.state.entities[e.target_id] for e in g.events if e.kind == 'card_created' and
                e.source_id is not None and g.state.entities[e.source_id].card_id == 'CATA_153']
    def assert_generated(self, g, printed_cost, count=2):
        values = self.generated(g)
        self.assertEqual(len(values), count)
        self.assertTrue(all(e.base_cost == printed_cost for e in values))
        self.assertTrue(all(local_cost(e) == (1, PaymentType.MANA) for e in values))
        self.assertEqual(len({e.id for e in values}), count)
        return values
    def check(self, g):
        s = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s, self.r).snapshot(), s)
        self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), s)
    def ranked(self, count):
        g = self.game(hand=(f'herald{count}', 'CATA_153'), board=('plain',)*7)
        self.play(g, f'herald{count}'); return g

    def test_default_reads_two_limb_auras_before_battlecry(self):
        g = self.game(); self.play(g, 'CATA_153')
        self.assertEqual(self.body(g).attack, 4); self.assert_generated(g, 4)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],
                         ['CATA_153t', 'CATA_153', 'CATA_153t1']); self.check(g)

    def test_two_heralds_generate_six_cost_minions(self):
        g = self.ranked(2); self.play(g, 'CATA_153')
        self.assertEqual(self.body(g).attack, 6); self.assert_generated(g, 6); self.check(g)

    def test_four_heralds_generate_two_distinct_ten_cost_entities(self):
        g = self.ranked(4); self.play(g, 'CATA_153')
        self.assertEqual(self.body(g).attack, 10)
        values = self.assert_generated(g, 10)
        self.assertEqual([e.card_id for e in values], ['OG_141', 'OG_141']); self.check(g)

    def test_full_board_body_generates_at_base_attack(self):
        g = self.game(board=('plain',)*6); self.play(g, 'CATA_153')
        self.assertEqual(g.state.colossal_history[0].limbs, (None, None))
        self.assertEqual(self.body(g).attack, 2); self.assert_generated(g, 2); self.check(g)

    def test_only_one_free_appendage_slot_changes_generated_cost(self):
        g = self.game(board=('plain',)*5); self.play(g, 'CATA_153')
        self.assertIsNone(g.state.colossal_history[0].limbs[1])
        self.assertEqual(self.body(g).attack, 3); self.assert_generated(g, 3); self.check(g)

    def test_hand_attack_buff_is_included(self):
        self.spell('handbuff', lambda c: [BuffStoredCard(CardReference.capture(next(
            c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id == 'CATA_153')), 3, 0)])
        g = self.game(hand=('handbuff', 'CATA_153')); self.play(g, 'handbuff'); self.play(g, 'CATA_153')
        self.assertEqual(self.body(g).attack, 7); self.assert_generated(g, 7); self.check(g)

    def test_external_attack_aura_is_included(self):
        self.minion('attack_aura', health=9, auras=(AuraSpec(2),))
        g = self.game(board=('attack_aura',)); self.play(g, 'CATA_153')
        self.assertEqual(self.body(g).attack, 6); self.assert_generated(g, 6); self.check(g)

    def test_appendage_death_reaction_changes_captured_attack(self):
        self.watch('minion_summoned', lambda c: [Destroy(c.event.source_id)]
                   if c.state.entities[c.event.source_id].card_id == 'CATA_153t' else [])
        g = self.game(board=('watch',)); self.play(g, 'CATA_153')
        self.assertEqual(self.body(g).attack, 3); self.assert_generated(g, 3); self.check(g)

    def test_body_summon_reaction_changes_attack_before_battlecry(self):
        self.watch('minion_summoned', lambda c: [Buff(c.event.source_id, 2)]
                   if c.state.entities[c.event.source_id].card_id == 'CATA_153' else [])
        g = self.game(board=('watch',)); self.play(g, 'CATA_153')
        self.assertEqual(self.body(g).attack, 6); self.assert_generated(g, 6); self.check(g)

    def test_body_removed_before_battlecry_cancels_generation_without_context(self):
        self.watch('minion_summoned', lambda c: [Destroy(c.event.source_id)]
                   if c.state.entities[c.event.source_id].card_id == 'CATA_153' else [])
        g = self.game(board=('watch',), context=None); self.play(g, 'CATA_153')
        self.assertEqual(self.generated(g), []); self.check(g)

    def test_body_silenced_before_battlecry_cancels_generation(self):
        self.watch('minion_summoned', lambda c: [Silence(c.event.source_id)]
                   if c.state.entities[c.event.source_id].card_id == 'CATA_153' else [])
        g = self.game(board=('watch',), context=None); self.play(g, 'CATA_153')
        self.assertEqual(self.generated(g), []); self.assertTrue(self.body(g).silenced); self.check(g)

    def test_body_control_change_before_battlecry_cancels_original_entry(self):
        self.watch('minion_summoned', lambda c: [ChangeControl(c.event.source_id, 2)]
                   if c.state.entities[c.event.source_id].card_id == 'CATA_153' else [])
        g = self.game(board=('watch',), context=None); self.play(g, 'CATA_153')
        self.assertEqual(self.generated(g), []); self.check(g)

    def test_source_transform_before_battlecry_does_not_use_new_face(self):
        self.watch('minion_summoned', lambda c: [Transform(c.event.source_id, 'plain')]
                   if c.state.entities[c.event.source_id].card_id == 'CATA_153' else [])
        g = self.game(board=('watch',), context=None); self.play(g, 'CATA_153')
        self.assertFalse(any(e.kind == 'card_created' for e in g.events)); self.check(g)

    def test_summon_does_not_run_battlecry(self):
        g = self.game(hand=('summon',), context=None); self.play(g, 'summon')
        self.assertEqual(self.body(g).attack, 4); self.assertEqual(self.generated(g), []); self.check(g)

    def test_current_copy_summons_limbs_without_battlecry(self):
        g = self.game(hand=('copy',), board=('CATA_153',), context=None)
        self.play(g, 'copy', self.body(g).id)
        self.assertEqual(len(g.state.players[1].board), 4); self.assertEqual(self.generated(g), []); self.check(g)

    def test_generated_cost_persists_across_turns_and_source_death(self):
        g = self.game(hand=('CATA_153', 'kill')); i = self.play(g, 'CATA_153')
        self.play(g, 'kill', i); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assert_generated(g, 4); self.check(g)

    def test_generated_card_payment_uses_one_mana(self):
        g = self.game(); self.play(g, 'CATA_153')
        generated = self.generated(g); before = g.state.players[1].mana
        g.apply(PlayCard(1, generated[0].id))
        self.assertEqual(g.state.players[1].mana, before-1); self.check(g)

    def test_current_copy_preserves_discount_base_copy_does_not(self):
        def duplicate(c):
            card = next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].base_cost == 4)
            return [CopyCard(CardReference.capture(card), 1, Zone.HAND),
                    CopyCard(CardReference.capture(card), 1, Zone.HAND, mode='base')]
        self.spell('duplicate', duplicate)
        g = self.game(hand=('CATA_153', 'duplicate')); self.play(g, 'CATA_153'); self.play(g, 'duplicate')
        values = [g.state.entities[i] for i in g.state.players[1].hand]
        self.assertEqual([local_cost(e)[0] for e in values], [1, 1, 1, 4]); self.check(g)

    def test_bouncing_played_generated_card_resets_its_cost(self):
        g = self.game(hand=('CATA_153', 'bounce')); self.play(g, 'CATA_153')
        i = self.generated(g)[0].id; g.apply(PlayCard(1, i)); self.play(g, 'bounce', i)
        self.assertEqual(local_cost(g.state.entities[i])[0], 4); self.check(g)

    def test_creation_reactions_see_one_cost_from_first_event(self):
        self.watch('card_created', lambda c: [GainArmor(1, local_cost(c.state.entities[c.event.target_id])[0])])
        g = self.game(board=('watch',)); self.play(g, 'CATA_153')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2); self.check(g)

    def test_cost_aura_modifies_payment_not_printed_cost_filter(self):
        self.minion('cost_aura', health=9, cost_auras=(CostAuraSpec(CostSpec(delta=2)),))
        # A global +2 allows the body at ten mana; generated cards then cost three.
        g = self.game(board=('cost_aura',)); self.play(g, 'CATA_153')
        values = self.assert_generated(g, 4)
        self.assertTrue(all(quote_cost(g.state, self.r, e).amount == 3 for e in values)); self.check(g)

    def test_second_card_uses_same_frozen_attack_after_first_creation(self):
        self.watch('card_created', lambda c: [Buff(i, 2) for i in self.bodies(c)])
        g = self.game(board=('watch',)); self.play(g, 'CATA_153')
        self.assertEqual(self.body(g).attack, 8); self.assert_generated(g, 4); self.check(g)

    def test_source_death_after_first_creation_does_not_cancel_second(self):
        self.watch('card_created', lambda c: [Destroy(i) for i in self.bodies(c)])
        g = self.game(board=('watch',)); self.play(g, 'CATA_153')
        self.assert_generated(g, 4); self.assertFalse(any(g.state.entities[i].card_id == 'CATA_153'
                                                      for i in g.state.players[1].board)); self.check(g)

    def test_full_hand_burns_second_modified_card_without_acquisition(self):
        g = self.game(hand=('CATA_153', *('plain',)*9)); self.play(g, 'CATA_153')
        values = self.assert_generated(g, 4)
        self.assertEqual([e.zone for e in values], [Zone.HAND, Zone.GRAVEYARD])
        self.assertIsNotNone(values[0].hand_entry_id); self.assertIsNone(values[1].hand_entry_id); self.check(g)

    def test_generated_identities_and_costs_are_private(self):
        g = self.game(); self.play(g, 'CATA_153')
        own = g.observe(1)['players'][0]['hand']; hidden = g.observe(2)['players'][0]['hand']
        self.assertTrue(all(e['cost'] == {'amount': 1, 'payment': 'mana'} for e in own))
        self.assertTrue(all(e['card_id'] is None and 'cost' not in e for e in hidden)); self.check(g)

    def test_pending_limb_reaction_restores_before_attack_capture(self):
        def choose(c):
            if c.state.entities[c.event.source_id].card_id != 'CATA_153t': return []
            return [RequestChoice(1, (ChoiceOption('buff', 'Buff body',
                     tuple(Buff(i, 2) for i in self.bodies(c))),))]
        self.watch('minion_summoned', choose)
        g = self.game(board=('watch',)); self.play(g, 'CATA_153')
        self.assertEqual(self.generated(g), []); self.check(g)
        restored = g.clone()
        for match in (g, restored):
            match.apply(SelectChoice(1, match.state.pending_choice.id, ('buff',)))
            self.assert_generated(match, 6); self.check(match)
        self.assertEqual(g.snapshot(), restored.snapshot())

    def test_pending_creation_reaction_restores_frozen_second_card(self):
        self.watch('card_created', lambda c: [RequestChoice(1, (ChoiceOption('done', 'Continue',
            tuple(Buff(i, 2) for i in self.bodies(c))),))])
        g = self.game(board=('watch',)); self.play(g, 'CATA_153'); self.assert_generated(g, 4, 1); self.check(g)
        restored = g.clone()
        for match in (g, restored):
            while match.state.pending_choice:
                match.apply(SelectChoice(1, match.state.pending_choice.id, ('done',)))
            self.assert_generated(match, 4); self.assertEqual(self.body(match).attack, 8); self.check(match)
        self.assertEqual(g.snapshot(), restored.snapshot())

    def test_no_candidate_does_not_fall_back_to_other_cost(self):
        self.watch('minion_summoned', lambda c: [Buff(c.event.source_id, 30)]
                   if c.state.entities[c.event.source_id].card_id == 'CATA_153' else [])
        g = self.game(board=('watch',)); rng = g.snapshot()['rng_state']; self.play(g, 'CATA_153')
        self.assertEqual(self.generated(g), []); self.assertEqual(g.snapshot()['rng_state'], rng); self.check(g)

    def test_zero_attack_uses_zero_not_base_attack(self):
        self.watch('minion_summoned', lambda c: [SetStats(c.event.source_id, attack=0),
            *[Silence(i) for i in c.state.players[1].board if c.state.entities[i].card_id in ('CATA_153t', 'CATA_153t1')]]
            if c.state.entities[c.event.source_id].card_id == 'CATA_153' else [])
        g = self.game(board=('watch',)); self.play(g, 'CATA_153')
        self.assertEqual(self.body(g).attack, 0); self.assertEqual(self.generated(g), []); self.check(g)

    def test_negative_attack_buff_clamps_to_zero_cost_candidate(self):
        self.minion('zero', health=1, metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=()))
        self.r.register_pool_card(PoolCard.from_definition(self.r.card('zero')))
        self.r.register_pool(PoolDefinition(ATTACK_COST_POOL_ID, 'zero-v1', 'zero-target', 'experimental',
            (PoolMember('zero'), PoolMember('CS2_182'))))
        self.watch('minion_summoned', lambda c: [Buff(c.event.source_id, -40)]
                   if c.state.entities[c.event.source_id].card_id == 'CATA_153' else [])
        g = self.game(board=('watch',), context=GenerationContext('zero-target', 'experimental'))
        self.play(g, 'CATA_153'); self.assert_generated(g, 0); self.check(g)

    def test_attack_above_ten_is_not_clamped_to_mana_limit(self):
        self.minion('large', cost=20, attack=8, health=8,
            metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=()))
        self.r.register_pool_card(PoolCard.from_definition(self.r.card('large')))
        self.r.register_pool(PoolDefinition(ATTACK_COST_POOL_ID, 'large-v1', 'large-target', 'experimental',
            (PoolMember('large'), PoolMember('OG_141'))))
        self.watch('minion_summoned', lambda c: [Buff(c.event.source_id, 16)]
                   if c.state.entities[c.event.source_id].card_id == 'CATA_153' else [])
        g = self.game(board=('watch',), context=GenerationContext('large-target', 'experimental'))
        self.play(g, 'CATA_153'); self.assert_generated(g, 20); self.check(g)

    def test_generation_does_not_require_matching_hero_class(self):
        self.r.register_pool(PoolDefinition(ATTACK_COST_POOL_ID, 'class-v1', 'class-target', 'experimental',
            (PoolMember('CATA_150'),)))
        self.watch('minion_summoned', lambda c: [Buff(c.event.source_id, 4)]
                   if c.state.entities[c.event.source_id].card_id == 'CATA_153' else [])
        g = self.game(board=('watch',), context=GenerationContext('class-target', 'experimental'))
        self.play(g, 'CATA_153'); values = self.assert_generated(g, 8)
        self.assertTrue(all(e.card_id == 'CATA_150' for e in values)); self.check(g)

    def test_missing_context_rolls_back_body_limbs_cost_and_rng(self):
        g = self.game(context=None); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'CATA_153')
        self.assertEqual(g.snapshot(), before)

    def test_formal_pool_does_not_fall_back_to_experimental(self):
        g = self.game(context=GenerationContext(CONTEXT.target_id, 'standard')); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'CATA_153')
        self.assertEqual(g.snapshot(), before)

    def test_unimplemented_eligible_candidate_is_not_silently_removed(self):
        row = PoolCard('missing', CardType.MINION, 4,
            CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=()))
        self.r.register_pool_card(row)
        self.r.register_pool(PoolDefinition(ATTACK_COST_POOL_ID, 'fixture', 'missing-target', 'experimental',
            (PoolMember('CS2_182'), PoolMember('missing'))))
        g = self.game(context=GenerationContext('missing-target', 'experimental')); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'CATA_153')
        self.assertEqual(g.snapshot(), before)

    def test_pool_is_explicit_and_ignores_new_executable_minions(self):
        pool = self.r.pool(ATTACK_COST_POOL_ID, CONTEXT)
        self.assertEqual({m.card_id for m in pool.members}, set(ATTACK_COST_POOL_IDS))
        self.assertFalse(pool.complete); self.assertNotIn('plain', self.r.pool_cards)

    def test_rush_windfury_body_attacks_minions_twice_but_not_face(self):
        g = self.game(enemy=('plain', 'plain')); i = self.play(g, 'CATA_153')
        with self.assertRaises(IllegalAction): g.apply(Attack(1, i, g.state.players[2].hero_id))
        for target in tuple(g.state.players[2].board): g.apply(Attack(1, i, target))
        self.assertEqual(g.state.entities[i].attacks_this_turn, 2)
        with self.assertRaises(IllegalAction): g.apply(Attack(1, i, g.state.players[2].board[0]))
        self.check(g)

    def test_old_snapshot_schema_rejected(self):
        g = self.game(); s = g.snapshot(); s['schema_version'] = 39
        with self.assertRaises(SnapshotError): Game.from_snapshot(s, self.r)


if __name__ == '__main__': unittest.main()
