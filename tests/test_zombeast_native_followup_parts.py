"""Real donor bodies through the original two-step source and lifecycle."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_scourge_tamer_card import CARD as TAMER, BODY as TAMER_BODY
from hs_sim.cards.storm_gates_card import CARD as QUEST, TEMPLATE, FIRST, SECOND
from hs_sim.cards.zombeast_native_followup_parts import (PARTS, CHILDREN,
    load_batch, register_zombeast_native_followup_parts)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, Keyword, PlayerSetup, Registry, ResolutionError, Scenario,
    TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.crafted_faces import CraftedMinionRecipe
from hs_sim.engine.crafted_offers import ResolveCraft
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (ChoiceOption, Damage, Destroy, Heal, InvokeBehavior,
    RequestChoice, Silence)
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k572.'
HERO, POWER, UNIT, KILL, QUIET, HIT, HEAL, WATCH = (
    P+x for x in ('hero', 'power', 'unit', 'kill', 'quiet', 'hit', 'heal', 'watch'))
META = CardMetadata(False, (CardClass.HUNTER,), None)
SECOND_PART = 'LOOT_258'
DRAWER = 'TIME_601'
NEIGHBOR = 'CORE_LOOT_413'
UNREVIEWED = 'CORE_CS2_120'
CONTEXT = GenerationContext('explicit-k572-native-followup-fixture', 'experimental')


@lru_cache(None)
def originals():
    return build_registry()


def native_registry(corrupt=None):
    source = originals(); r = Registry(P+'native')
    ids = (*PARTS, *CHILDREN, TAMER, QUEST, TEMPLATE, SECOND_PART, DRAWER, NEIGHBOR, UNREVIEWED)
    bodies = {TAMER_BODY, 'cards.storm_gates.progress', 'cards.storm_gates.reward'}
    for cid in ids:
        card = source.card(cid)
        r.register_card(replace(card, health=card.health+1) if cid == corrupt else card)
        bodies.update(x for x in (card.on_play, card.battlecry, card.deathrattle) if x)
        bodies.update(x.behavior_id for x in card.triggers)
    prefixes = tuple(body.rsplit('.', 1)[0]+'.' for body in bodies)
    for body in sorted(source._behaviors):
        if body in bodies or body.startswith(prefixes):
            r.register_behavior(body, source.behavior(body))
    return r


@lru_cache(None)
def fixture(mode='TLC_245|normal', role='writer'):
    part, variant = mode.split('|'); r = native_registry(); source = originals()
    register_zombeast_native_followup_parts(r)
    r.register_crafted_minion_part(SECOND_PART)
    r.register_crafted_minion_blueprint(source.crafted_minion_blueprints[TEMPLATE])
    r.register_behavior(P+'noop', lambda c: ())
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100, metadata=META))
    r.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, cost=2,
        on_use=P+'noop', metadata=META))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=2, health=30, metadata=META))
    for cid, body in {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        QUIET: lambda c: (Silence(c.target_id),),
        HIT: lambda c: (Damage(c.target_id, 10, c.source_id),),
        HEAL: lambda c: (Heal(c.target_id, 7, c.source_id),),
    }.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            metadata=META, targeting=TargetSpec(TargetMode.REQUIRED,
                kinds=(CardType.MINION, CardType.HERO))))
    def fail(c):
        raise ResolutionError('K572 intentional failure after actual native followup')
    def watch(c):
        entity = c.state.entities.get(c.event.source_id)
        if entity is None:
            return ()
        if variant == 'fail' and entity.card_id == CraftedMinionRecipe(TEMPLATE, part, SECOND_PART).card_id:
            return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        if variant == 'wait' and entity.card_id == DRAWER:
            return (RequestChoice(c.player_id, (
                ChoiceOption('ok', 'continue', ()),
                ChoiceOption('bad', 'fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
            ), c.source_id),)
        return ()
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=100,
        triggers=(TriggerSpec('minion_summoned' if variant == 'wait' else 'card_played', P+'watch'),),
        metadata=META))
    for cid in (*PARTS, SECOND_PART, DRAWER, UNREVIEWED):
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    seconds = (SECOND_PART, UNREVIEWED) if variant == 'unreviewed' else (SECOND_PART,)
    for pool, ids in ((FIRST, (part,)), (SECOND, seconds),
            ('constructed.cards', ('TIME_058', DRAWER))):
        r.register_pool(PoolDefinition(pool, 'explicit-native-followup-v1',
            CONTEXT.target_id, CONTEXT.mode, tuple(PoolMember(cid) for cid in ids),
            complete=not(variant == 'incomplete' and pool == SECOND)))
    r.validate(); return r


class ZombeastNativeFollowupPartsTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def recipe(self, part):
        return CraftedMinionRecipe(TEMPLATE, part, SECOND_PART).card_id

    def game(self, part='TLC_245', *, player=1, hand=None, own=(), enemy=(UNIT,),
            opposing_hand=(), variant='normal'):
        self.mode = part+'|'+variant
        if hand is None:
            hand = (TAMER,)
        setups = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            hand=hand if p == player else opposing_hand, board=own if p == player else enemy,
            deck=(UNIT,)*8, mana=30, max_mana=30, mana_cap=30) for p in (1, 2))
        return Game.from_scenario(Scenario(setups, active_player=player, seed=572,
            generation_context=CONTEXT), fixture(self.mode))

    def pick(self, g, cid):
        option = next(row for row in g._frame.options if any(
            type(e) is ResolveCraft and e.card_id == cid for e in row.effects))
        self.choose(g, option.id)

    def craft(self, g, part, player=1):
        self.play(g, TAMER, player=player)
        self.pick(g, part); self.pick(g, SECOND_PART)
        return self.entity(g, self.recipe(part), player).id

    def test_complete_original_rows_faces_and_definitions_are_pinned_before_adaptation(self):
        data = load_batch(); rows = {x['record']['id']: x['record'] for x in data['existing_dependencies']}
        self.assertEqual((len(rows), len(data['official_observations'])), (13, 18))
        for face in data['official_observations']:
            batch.check_face(rows[face['card_id']], face['face'], face['locale'])
        before = batch.registration_prefix(build_registry,
            'hs_sim.cards.zombeast_native_followup_parts.register_zombeast_native_followup_parts',
            register_zombeast_native_followup_parts)
        self.assertFalse(set(PARTS) & set(before.crafted_minion_parts))
        self.assertTrue(set(PARTS) <= set(originals().crafted_minion_parts))
        self.assertFalse(any(key[0] in (FIRST, SECOND) for key in originals().pools))
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_each_actual_paid_tamer_offer_and_composed_play_keep_original_body_and_payment(self):
        for index, part in enumerate(PARTS):
            with self.subTest(part=part):
                player = 1+index%2; g = self.game(part, player=player)
                eid = self.craft(g, part, player); original = originals().card(part)
                face = g.registry.card(self.recipe(part))
                self.assertEqual((face.cost, face.attack, face.health),
                    (original.cost+1, original.attack+1, original.health+3))
                self.play(g, face.id, player=player)
                if part in ('TLC_245', 'TLC_246'):
                    self.choose(g, 'attack' if part == 'TLC_245' else 'UNG_999t7')
                self.assertEqual(g.state.entities[eid].components, (part, SECOND_PART))
                self.assertEqual(g.state.players[player].mana, 28-original.cost)

    def test_rockfang_copies_original_adjacent_deathrattle_onto_crafted_physical_carrier(self):
        part = 'BE_731'; g = self.game(part, hand=(TAMER, NEIGHBOR, KILL))
        eid = self.craft(g, part); self.play(g, NEIGHBOR); self.play(g, self.recipe(part))
        self.assertEqual(sum(a.kind == 'deathrattle' for a in g.state.entities[eid].abilities), 1)
        self.play(g, KILL, eid)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 3)
        self.assertEqual(g.state.death_history[-1].components, (part, SECOND_PART)); self.portable(g)

    def test_macaw_generates_an_actual_original_beast_without_executing_its_battlecry(self):
        part = 'CORE_UNG_912'; g = self.game(part); self.craft(g, part)
        before = len(g.state.battlecry_history); self.play(g, self.recipe(part))
        held, = g.state.players[1].hand
        self.assertIn(g.state.entities[held].card_id, ('TIME_058', DRAWER))
        self.assertEqual(len(g.state.battlecry_history), before+1)
        self.assertEqual(len(g.state.players[1].board), 2)

    def test_native_raptor_choice_wait_restores_and_real_plants_are_summoned_only_on_death(self):
        part = 'TLC_245'; g = self.game(part, hand=(TAMER, KILL)); eid = self.craft(g, part)
        self.play(g, self.recipe(part)); other = self.portable(g)
        for current in (g, other):
            self.choose(current, 'plants'); self.play(current, KILL, eid)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(sum(g.state.entities[i].card_id == 'UNG_999t2t1'
            for i in g.state.players[1].board), 2)
        self.assertEqual(sum(a.kind == 'deathrattle' for a in g.state.entities[eid].abilities), 1)
        self.portable(g)

    def test_other_raptor_choices_modify_the_summed_body_and_silence_removes_grants(self):
        part = 'TLC_245'
        for option in ('attack', 'shield'):
            with self.subTest(option=option):
                g = self.game(part, hand=(TAMER, QUIET)); eid = self.craft(g, part)
                base = g.registry.card(self.recipe(part)); self.play(g, self.recipe(part)); self.choose(g, option)
                self.assertEqual(g.state.entities[eid].attack, base.attack+(3 if option == 'attack' else 0))
                self.assertEqual(Keyword.DIVINE_SHIELD in g.state.entities[eid].keywords, option == 'shield')
                self.play(g, QUIET, eid)
                self.assertEqual(g.state.entities[eid].attack, base.attack)
                self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[eid].keywords)

    def test_pterrordax_timed_stealth_expires_at_original_owner_start_on_composed_body(self):
        part = 'TLC_246'; g = self.game(part); eid = self.craft(g, part)
        self.play(g, self.recipe(part)); other = self.portable(g)
        for current in (g, other): self.choose(current, 'UNG_999t10')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertIn(Keyword.STEALTH, g.state.entities[eid].keywords)
        g.apply(EndTurn(1)); self.assertIn(Keyword.STEALTH, g.state.entities[eid].keywords)
        g.apply(EndTurn(2)); self.assertNotIn(Keyword.STEALTH, g.state.entities[eid].keywords)
        self.portable(g)

    def test_pterrordax_permanent_elusive_and_windfury_keep_original_choice_identity(self):
        part = 'TLC_246'
        for option, keyword in (('UNG_999t5', Keyword.ELUSIVE), ('UNG_999t7', Keyword.WINDFURY)):
            with self.subTest(option=option):
                g = self.game(part); eid = self.craft(g, part); self.play(g, self.recipe(part))
                self.choose(g, option); g.apply(EndTurn(1)); g.apply(EndTurn(2))
                self.assertIn(keyword, g.state.entities[eid].keywords)

    def test_crater_gator_lock_survives_source_death_and_expires_at_original_owner_start(self):
        part = 'TLC_250'; g = self.game(part, hand=(TAMER, HIT, HEAL, HEAL, HEAL, KILL))
        target = g.state.players[2].hero_id; self.play(g, HIT, target)
        eid = self.craft(g, part); self.play(g, self.recipe(part)); self.play(g, HEAL, target)
        self.assertEqual(g.state.entities[target].health, 90)
        self.play(g, KILL, eid); self.play(g, HEAL, target)
        self.assertEqual(g.state.entities[target].health, 90); self.portable(g)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g, HEAL, target)
        self.assertEqual(g.state.entities[target].health, 97)

    def test_dreambound_raptor_uses_real_other_minion_play_and_silence_removes_listener(self):
        part = 'EDR_849'; g = self.game(part, hand=(TAMER, UNIT, UNIT, QUIET))
        eid = self.craft(g, part); self.play(g, self.recipe(part))
        self.assertFalse(g.state.entities[eid].keywords)
        child = self.play(g, UNIT); self.assertEqual(len(g.state.entities[child].keywords), 1)
        self.assertFalse(g.state.entities[eid].keywords)
        self.play(g, QUIET, eid); child2 = self.play(g, UNIT)
        self.assertFalse(g.state.entities[child2].keywords); self.portable(g)

    def test_thresher_shields_actual_crafted_carrier_after_a_spell_and_not_its_own_play(self):
        part = 'TLC_256'; g = self.game(part, hand=(TAMER, HIT, QUIET, HIT))
        eid = self.craft(g, part); self.play(g, self.recipe(part))
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[eid].keywords)
        self.play(g, HIT, g.state.players[2].hero_id)
        self.assertIn(Keyword.DIVINE_SHIELD, g.state.entities[eid].keywords)
        self.play(g, QUIET, eid); self.play(g, HIT, g.state.players[2].hero_id)
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[eid].keywords)

    def test_guard_dog_death_summons_actual_one_cost_deathrattle_without_its_own_play(self):
        part = 'JAIL_878'; g = self.game(part, hand=(TAMER, KILL)); eid = self.craft(g, part)
        self.play(g, self.recipe(part)); self.play(g, KILL, eid)
        child = self.entity(g, 'TIME_058', zone='board')
        self.assertTrue(child.active); self.assertIsNone(child.dormancy)
        self.assertEqual(len(g.state.deathrattle_history), 1)
        self.assertEqual(g.state.death_history[-1].components, (part, SECOND_PART)); self.portable(g)

    def test_flutterwing_death_keeps_two_turn_dormancy_and_no_summoned_battlecry(self):
        part = 'TIME_058'; g = self.game(part, hand=(TAMER, KILL)); eid = self.craft(g, part)
        self.play(g, self.recipe(part)); count = len(g.state.battlecry_history); self.play(g, KILL, eid)
        child = self.entity(g, DRAWER, zone='board')
        self.assertFalse(child.active); self.assertEqual(child.dormancy.remaining_turns, 2)
        self.assertEqual(len(g.state.battlecry_history), count)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.assertEqual(g.state.entities[child.id].dormancy.remaining_turns, 1)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.assertIsNone(g.state.entities[child.id].dormancy)

    def test_generated_child_wait_restores_and_bad_branch_rolls_back_without_resampling(self):
        part = 'TIME_058'; g = self.game(part, hand=(TAMER, KILL), own=(WATCH,), variant='wait')
        eid = self.craft(g, part); self.play(g, self.recipe(part)); self.play(g, KILL, eid)
        saved = g.snapshot(); other = self.portable(g)
        with self.assertRaisesRegex(ResolutionError, 'K572 intentional failure'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for current in (g, other): self.choose(current, 'ok')
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_failure_after_native_effect_rolls_back_original_payment_rng_and_delivery(self):
        part = 'CORE_UNG_912'; g = self.game(part, own=(WATCH,), variant='fail')
        self.craft(g, part); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K572 intentional failure'):
            self.play(g, self.recipe(part))
        self.assertEqual(g.snapshot(), saved)

    def test_both_original_offer_waits_restore_and_do_not_expose_complete_inventory(self):
        part = 'TLC_245'; g = self.game(part); self.play(g, TAMER)
        for chosen in (part, SECOND_PART):
            other = self.portable(g)
            for current in (g, other): self.pick(current, chosen)
            self.assertEqual(g.snapshot(), other.snapshot())
        view = json.dumps(g.for_player(2).observe())
        self.assertNotIn(self.recipe(part), view)
        for key in ('crafted_minion_parts', 'rng_before', 'first_candidates', 'pool_members'):
            self.assertNotIn(key, view)

    def test_actual_standard_sidequest_rewards_new_donor_with_original_three_mana_discount(self):
        part = 'TLC_245'; g = self.game(part, hand=(QUEST, SECOND_PART, SECOND_PART, SECOND_PART))
        self.play(g, QUEST)
        for _ in range(3): self.play(g, SECOND_PART)
        self.pick(g, part); self.pick(g, SECOND_PART)
        body = self.entity(g, self.recipe(part)); face = g.registry.card(body.card_id)
        self.assertEqual(quote_cost(g.state, g.registry, body).amount, max(0, face.cost-3))
        mana = g.state.players[1].mana; self.play(g, body.card_id); self.choose(g, 'plants')
        self.assertEqual(g.state.players[1].mana, mana-max(0, face.cost-3))
        self.assertEqual(sum(a.kind == 'deathrattle' for a in g.state.entities[body.id].abilities), 1)
        self.portable(g)

    def test_unknown_eligible_parts_and_incomplete_pool_still_fail_atomically(self):
        for variant in ('unreviewed', 'incomplete'):
            with self.subTest(variant=variant):
                g = self.game(variant=variant); saved = g.snapshot()
                with self.assertRaises(ResolutionError): self.play(g, TAMER)
                self.assertEqual(g.snapshot(), saved)

    def test_complete_part_or_child_mutation_rejects_before_any_donor_is_registered(self):
        for cid in ('BE_731', 'UNG_999t2t1'):
            with self.subTest(cid=cid):
                r = native_registry(cid)
                with self.assertRaisesRegex(TargetValidationError, 'Unreviewed native followup'):
                    register_zombeast_native_followup_parts(r)
                self.assertFalse(set(PARTS) & set(r.crafted_minion_parts))


if __name__ == '__main__':
    unittest.main()
