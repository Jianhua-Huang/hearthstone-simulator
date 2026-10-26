"""New real secondary bodies and existing exceptions through ordinary crafting."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_scourge_tamer_card import CARD as TAMER, BODY as TAMER_BODY
from hs_sim.cards.storm_gates_card import CARD as QUEST, TEMPLATE, FIRST, SECOND
from hs_sim.cards.zombeast_secondary_reference_cards import (PARTS, DEFINITIONS,
    EXISTING, REFERENCE_PATH, load_batch, register_zombeast_secondary_reference_cards)
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, IllegalAction, Keyword, PlayerSetup, Registry, ResolutionError,
    Scenario, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.crafted_faces import CraftedMinionRecipe
from hs_sim.engine.crafted_offers import ResolveCraft
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import CopyMinion, Damage, InvokeBehavior, Silence
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k574.'
HERO, POWER, UNIT, HIT, QUIET, COPY, WATCH = (
    P+x for x in ('hero', 'power', 'unit', 'hit', 'quiet', 'copy', 'watch'))
META = CardMetadata(False, (CardClass.HUNTER,), None)
PRIMARY = 'CORE_EX1_014'
BANANA = 'EX1_014t'
UNREVIEWED = 'CORE_CS2_120'
CONTEXT = GenerationContext('explicit-k574-secondary-fixture', 'experimental')


@lru_cache(None)
def originals():
    return build_registry()


def before_registry(corrupt=None):
    source = originals(); r = Registry(P+'native')
    for cid in (*EXISTING, PRIMARY, BANANA, TAMER, QUEST, TEMPLATE, UNREVIEWED):
        card = source.card(cid)
        r.register_card(replace(card, attack=card.attack+1) if cid == corrupt else card)
    for name in (TAMER_BODY, 'cards.storm_gates.progress', 'cards.storm_gates.reward',
            source.card(PRIMARY).battlecry, source.card(BANANA).on_play):
        r.register_behavior(name, source.behavior(name))
    return r


@lru_cache(None)
def fixture(mode='LOOT_125|normal', role='writer'):
    part, variant = mode.split('|'); r = before_registry(); r._version = P+mode
    register_zombeast_secondary_reference_cards(r)
    r.register_crafted_minion_part(PRIMARY)
    r.register_crafted_minion_blueprint(originals().crafted_minion_blueprints[TEMPLATE])
    r.register_behavior(P+'noop', lambda c: ())
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100, metadata=META))
    r.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, cost=2,
        on_use=P+'noop', metadata=META))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=2, health=30, metadata=META))
    for cid, body in {
        HIT: lambda c: (Damage(c.target_id, 1, c.source_id),),
        QUIET: lambda c: (Silence(c.target_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id),),
    }.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            metadata=META, targeting=TargetSpec(TargetMode.REQUIRED, kinds=(CardType.MINION,))))
    def fail(c):
        raise ResolutionError('K574 intentional failure after native body')
    def watch(c):
        source = c.state.entities.get(c.event.source_id)
        return (InvokeBehavior(P+'fail', c.source_id, c.player_id),) if (
            source is not None and source.card_id == CraftedMinionRecipe(TEMPLATE, PRIMARY, part).card_id) else ()
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=100,
        triggers=(TriggerSpec('card_played', P+'watch'),), metadata=META))
    for cid in (*PARTS, PRIMARY, UNREVIEWED):
        if cid not in r.pool_cards: r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    seconds = (part, UNREVIEWED) if variant == 'unreviewed' else (part,)
    for pool, ids in ((FIRST, (PRIMARY,)), (SECOND, seconds)):
        r.register_pool(PoolDefinition(pool, 'explicit-secondary-reference-v1', CONTEXT.target_id,
            CONTEXT.mode, tuple(PoolMember(cid) for cid in ids), complete=True))
    r.validate(); return r


class ZombeastSecondaryReferenceTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def recipe(self, part):
        return CraftedMinionRecipe(TEMPLATE, PRIMARY, part).card_id

    def game(self, part='LOOT_125', *, hand=None, own=(), enemy=(UNIT,),
            player=1, opposing_hand=(), variant='normal'):
        self.mode = part+'|'+variant
        if hand is None: hand = (TAMER,)
        setups = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            hand=hand if p == player else opposing_hand, board=own if p == player else enemy,
            deck=(UNIT,)*12, mana=30, max_mana=30, mana_cap=30) for p in (1, 2))
        return Game.from_scenario(Scenario(setups, active_player=player, seed=574,
            generation_context=CONTEXT), fixture(self.mode))

    def pick(self, g, cid):
        option = next(row for row in g._frame.options if any(
            type(e) is ResolveCraft and e.card_id == cid for e in row.effects))
        self.choose(g, option.id)

    def craft(self, g, part, player=1):
        self.play(g, TAMER, player=player); self.pick(g, PRIMARY); self.pick(g, part)
        return self.entity(g, self.recipe(part), player).id

    def test_complete_seven_rows_fourteen_faces_and_existing_declarations_are_pinned(self):
        data = load_batch(); rows = {x['record']['id']: x['record']
            for x in data['cards']+data['existing_dependencies']}
        self.assertEqual((len(rows), len(data['official_observations'])), (7, 14))
        for face in data['official_observations']: batch.check_face(rows[face['card_id']], face['face'], face['locale'])
        boundary = batch.registration_prefix(build_registry,
            'hs_sim.cards.zombeast_secondary_reference_cards.register_zombeast_secondary_reference_cards',
            register_zombeast_secondary_reference_cards)
        self.assertFalse(set(DEFINITIONS) & set(boundary.cards))
        self.assertFalse(set(PARTS) & set(boundary.crafted_minion_parts))
        self.assertTrue(set(PARTS) <= set(originals().crafted_minion_parts))

    def test_reference_retains_complete_originals_zero_cost_aliases_and_unconfirmed_cases(self):
        ref = batch.read(REFERENCE_PATH)
        self.assertEqual((len(ref['outer_records']), len(ref['first_reference_ids']),
            len(ref['second_reference_ids']), len(ref['second_exclusions'])), (259, 34, 38, 1))
        rows = {x['record']['id']: x['record'] for x in ref['outer_records']}
        for x in ref['outer_records']: self.assertEqual(batch.canonical(x['record']), x['record_sha256'])
        self.assertIsNone(rows['ICC_023']['cost'])
        self.assertEqual(ref['numeric_normalizations'], {'ICC_023': {'cost': 0}})
        self.assertIn('ICC_023', ref['second_reference_ids'])
        self.assertIn('EX1_028', rows); self.assertNotIn('EX1_028', ref['second_reference_ids'])
        self.assertIn('CORE_EX1_028', ref['second_reference_ids'])
        self.assertEqual(ref['second_exclusions'][0]['card_id'], 'GIL_607t')
        self.assertIn('AV_128', ref['second_reference_ids'])
        self.assertEqual(ref['unconfirmed_secondary_boundaries'], ['GDB_842', 'TOY_866'])
        self.assertFalse(ref['full_role_partition_certified']); self.assertFalse(ref['runtime_bindings_added'])

    def test_all_seven_actual_tamer_choices_and_plays_keep_one_body_original_cost_and_entry(self):
        for index, part in enumerate(PARTS):
            with self.subTest(part=part):
                player = 1+index%2; g = self.game(part, player=player); eid = self.craft(g, part, player)
                face = g.registry.card(self.recipe(part)); second = originals().card(part)
                first = originals().card(PRIMARY)
                self.assertEqual((face.cost, face.attack, face.health),
                    (first.cost+second.cost, first.attack+second.attack, first.health+second.health))
                self.play(g, face.id, player=player)
                self.assertEqual(g.state.players[player].mana, 29-face.cost)
                self.assertEqual(g.state.entities[eid].components, (PRIMARY, part))
                bananas = sum(g.state.entities[i].card_id == BANANA for i in g.state.players[3-player].hand)
                self.assertEqual(bananas, 0 if part == 'TIME_046' else 2)

    def test_each_new_actual_minion_has_its_own_paid_standalone_entry_and_printed_keywords(self):
        for part in DEFINITIONS:
            with self.subTest(part=part):
                g = self.game(part, hand=(part,)); native = originals().card(part)
                eid = self.play(g, part)
                self.assertEqual(g.state.players[1].mana, 30-native.cost)
                self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].max_health),
                    (native.attack, native.health))
                self.assertEqual(g.state.entities[eid].keywords, set(native.keywords))
                self.assertFalse(g.state.battlecry_history)
                self.assertFalse(g.state.players[2].hand)

    def test_basilisk_native_poison_and_shield_use_actual_combat_and_shared_death(self):
        part = 'LOOT_125'; g = self.game(part); eid = self.craft(g, part); self.play(g, self.recipe(part))
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); enemy = self.entity(g, UNIT, 2, zone='board').id
        health = g.state.entities[eid].health; g.apply(Attack(1, eid, enemy))
        self.assertEqual(g.state.entities[enemy].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[eid].health, health)
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[eid].keywords)
        self.assertIn(Keyword.POISONOUS, g.state.entities[eid].keywords); self.portable(g)

    def test_both_real_elusive_bodies_reject_enemy_spell_target_without_payment(self):
        for part in ('DRG_066', 'ICC_419'):
            with self.subTest(part=part):
                g = self.game(part, opposing_hand=(HIT,)); eid = self.craft(g, part)
                self.play(g, self.recipe(part)); g.apply(EndTurn(1)); saved = g.snapshot()
                with self.assertRaises(IllegalAction): self.play(g, HIT, eid, 2)
                self.assertEqual(g.snapshot(), saved)

    def test_all_type_current_copy_and_silence_keep_recipe_and_summed_base_body(self):
        for part in ('DMF_532', 'GIL_681'):
            with self.subTest(part=part):
                g = self.game(part, hand=(TAMER, COPY, QUIET)); eid = self.craft(g, part)
                self.play(g, self.recipe(part)); self.play(g, COPY, eid)
                copies = [i for i in g.state.players[1].board if g.state.entities[i].card_id == self.recipe(part)]
                self.assertEqual(len(copies), 2)
                self.assertTrue(all(has_any_tribe(g.registry, g.state.entities[i], ('demon',)) for i in copies))
                self.assertEqual(sum(g.state.entities[i].card_id == BANANA for i in g.state.players[2].hand), 2)
                self.play(g, QUIET, eid)
                face = g.registry.card(self.recipe(part))
                self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].max_health), (face.attack, face.health))
                self.assertEqual(face.metadata.tribes, ('all',))
                if part == 'DMF_532': self.portable(g)

    def test_circus_taunt_blocks_actual_enemy_hero_attack_and_accepts_the_original_body(self):
        part = 'DMF_532'; g = self.game(part); eid = self.craft(g, part); self.play(g, self.recipe(part))
        g.apply(EndTurn(1)); enemy = self.entity(g, UNIT, 2, zone='board').id; saved = g.snapshot()
        with self.assertRaises(IllegalAction): g.apply(Attack(2, enemy, g.state.players[1].hero_id))
        self.assertEqual(g.snapshot(), saved); g.apply(Attack(2, enemy, eid))
        self.assertEqual(g.state.entities[eid].damage, 2)

    def test_three_turn_dormancy_uses_owner_clock_and_never_replays_suppressed_native_entry(self):
        part = 'TIME_046'; g = self.game(part); eid = self.craft(g, part); self.play(g, self.recipe(part))
        self.assertFalse(g.state.entities[eid].active)
        self.assertEqual(g.state.entities[eid].dormancy.remaining_turns, 3)
        before = sum(e.kind == 'minion_summoned' for e in g.events); other = self.portable(g)
        for current in (g, other):
            for remaining in (2, 1):
                current.apply(EndTurn(1)); current.apply(EndTurn(2))
                self.assertEqual(current.state.entities[eid].dormancy.remaining_turns, remaining)
            current.apply(EndTurn(1)); current.apply(EndTurn(2))
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertIsNone(g.state.entities[eid].dormancy)
        self.assertEqual(sum(e.kind == 'minion_summoned' for e in g.events), before)
        self.assertFalse(any(g.state.entities[i].card_id == BANANA for i in g.state.players[2].hand))

    def test_helmet_cannot_attack_native_policy_survives_composition_and_silence_removes_it(self):
        part = 'TSC_065'; g = self.game(part, hand=(TAMER, QUIET)); eid = self.craft(g, part)
        self.play(g, self.recipe(part)); g.apply(EndTurn(1)); g.apply(EndTurn(2)); saved = g.snapshot()
        target = g.state.players[2].hero_id
        with self.assertRaises(IllegalAction): g.apply(Attack(1, eid, target))
        self.assertEqual(g.snapshot(), saved); self.play(g, QUIET, eid); g.apply(Attack(1, eid, target))
        self.assertLess(g.state.entities[target].health, 100); self.portable(g)

    def test_actual_standard_sidequest_uses_original_discount_and_new_all_type_body(self):
        part = 'GIL_681'; g = self.game(part, hand=(QUEST, PRIMARY, PRIMARY, PRIMARY))
        self.play(g, QUEST)
        for _ in range(3): self.play(g, PRIMARY)
        self.pick(g, PRIMARY); self.pick(g, part); eid = self.entity(g, self.recipe(part)).id
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[eid]).amount, 3)
        self.play(g, self.recipe(part))
        self.assertTrue(has_any_tribe(g.registry, g.state.entities[eid], ('dragon',)))

    def test_both_original_offer_waits_restore_and_hide_other_players_private_material(self):
        part = 'DRG_066'; g = self.game(part); self.play(g, TAMER)
        for cid in (PRIMARY, part):
            other = self.portable(g)
            for current in (g, other): self.pick(current, cid)
            self.assertEqual(g.snapshot(), other.snapshot())
        view = json.dumps(g.for_player(2).observe())
        self.assertNotIn(self.recipe(part), view)
        for key in ('candidate_ids', 'rng_before', 'first_reference_ids', 'printing_relations'):
            self.assertNotIn(key, view)

    def test_failure_after_real_body_rolls_back_payment_and_native_opponent_bananas(self):
        part = 'LOOT_125'; g = self.game(part, own=(WATCH,), variant='fail'); self.craft(g, part)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K574 intentional'): self.play(g, self.recipe(part))
        self.assertEqual(g.snapshot(), saved)

    def test_unknown_eligible_original_part_is_not_silently_removed_from_second_pool(self):
        g = self.game(variant='unreviewed'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, TAMER)
        self.assertEqual(g.snapshot(), saved)
        self.assertEqual(len(g.registry.pool(SECOND, CONTEXT).members), 2)

    def test_existing_declaration_change_rejects_before_any_new_card_or_donor_is_installed(self):
        r = before_registry('TSC_065'); initial = set(r.cards)
        with self.assertRaisesRegex(TargetValidationError, 'Unreviewed complete existing'):
            register_zombeast_secondary_reference_cards(r)
        self.assertEqual(set(r.cards), initial)
        self.assertFalse(set(PARTS) & set(r.crafted_minion_parts))


if __name__ == '__main__':
    unittest.main()
