"""Original first bodies execute with the composed source in the complete local host."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_scourge_tamer_card import CARD as TAMER
from hs_sim.cards.storm_gates_card import CARD as QUEST, TEMPLATE, FIRST, SECOND
from hs_sim.cards.zombeast_native_first_consumers import (PARTS, CHILDREN,
    load_batch, register_zombeast_native_first_consumers)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    Game, PlayerSetup, ResolutionError, Scenario, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.crafted_faces import CraftedMinionRecipe
from hs_sim.engine.crafted_offers import ResolveCraft
from hs_sim.engine.effects import (ChoiceOption, Destroy, InvokeBehavior, RequestChoice)
from hs_sim.engine.pools import PoolDefinition, PoolMember
from hs_sim.engine.suspicious_discoveries import OFFERED, decode
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k575.'
HERO, POWER, UNIT, WATCH = (P+x for x in ('hero', 'power', 'unit', 'watch'))
META = CardMetadata(False, (CardClass.HUNTER,), None)
SECOND_PART = 'LOOT_258'
YETI, KINDRED, ACTIVATOR = 'CORE_CS2_182', 'DINO_435', 'BE_193'


@lru_cache(None)
def host(mode='CORE_LOE_039|normal', role='writer'):
    part, variant = mode.split('|'); fmt = build_cn37_local_pool_format(); r = fmt.registry
    r._version = r.version+':'+P+mode
    r.register_behavior(P+'noop', lambda c: ())
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100, metadata=META))
    r.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, cost=2,
        on_use=P+'noop', metadata=META))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=1, health=30, metadata=META))
    def fail(c):
        raise ResolutionError('K575 intentional native followup failure')
    def watch(c):
        e = c.event; source = c.state.entities.get(e.source_id)
        if source is None or source.card_id != CraftedMinionRecipe(TEMPLATE, part, SECOND_PART).card_id:
            return ()
        if variant == 'leave' and e.kind == 'choice_selected':
            return (Destroy(source.id, c.source_id),)
        if variant == 'fail' and e.kind == 'card_added_to_hand':
            return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        if (variant == 'draw' and e.kind == 'card_drawn') or (
                variant == 'attack' and e.kind == 'attack_declared'):
            return (RequestChoice(c.player_id, (
                ChoiceOption('ok', 'continue', ()),
                ChoiceOption('bad', 'fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
            ), c.source_id, prompt='K575 native continuation'),)
        return ()
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=100,
        triggers=tuple(TriggerSpec(event, P+'watch') for event in
            ('choice_selected', 'card_added_to_hand', 'card_drawn', 'attack_declared')), metadata=META))
    for pool, cid in ((FIRST, part), (SECOND, SECOND_PART)):
        r.register_pool(PoolDefinition(pool, 'explicit-first-consumer-v1', fmt.context.target_id,
            fmt.context.mode, (PoolMember(cid),), complete=True))
    if variant == 'unadapted': r._crafted_minion_parts.remove(part)
    r.validate(); return r, fmt


def fixture(mode='CORE_LOE_039|normal', role='writer'):
    return host(mode, role)[0]


class ZombeastNativeFirstConsumerTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def recipe(self, part):
        return CraftedMinionRecipe(TEMPLATE, part, SECOND_PART).card_id

    def game(self, part='CORE_LOE_039', *, hand=None, own=(), enemy=(UNIT, UNIT, UNIT),
            deck=(KINDRED, ACTIVATOR, YETI), player=1, variant='normal', seed=575):
        self.mode = part+'|'+variant; r, fmt = host(self.mode)
        if hand is None: hand = (TAMER,)
        if variant in ('leave', 'fail', 'draw', 'attack'): own = (*own, WATCH)
        players = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            hand=hand if p == player else (), board=own if p == player else enemy,
            deck=deck if p == player else (YETI,)*8, mana=30, max_mana=30, mana_cap=30)
            for p in (1, 2))
        context = replace(fmt.context, starting_decks=tuple(p.deck for p in players))
        return Game.from_scenario(Scenario(players, active_player=player, seed=seed,
            generation_context=context), r)

    def pick(self, g, cid):
        option = next(row for row in g._frame.options if any(
            type(e) is ResolveCraft and e.card_id == cid for e in row.effects))
        self.choose(g, option.id)

    def craft(self, g, part, player=1):
        self.play(g, TAMER, player=player); self.pick(g, part); self.pick(g, SECOND_PART)
        return self.entity(g, self.recipe(part), player).id

    def suspicious(self, g):
        event = next(e for e in reversed(g.events) if e.kind == OFFERED)
        return decode(g, dict(event.data)['proof'])

    def settle(self, g, part):
        if g.state.pending_choice is None: return None
        if part == 'JAIL_EVENT_100':
            proof = self.suspicious(g); key = 'card'+str(proof.marked_index+1)
        elif part == 'END_013':
            option = next((o for o in g._frame.options
                if o.effects[0].selection.gift.destination == 'hand'), g._frame.options[0])
            key = option.id
        else: key = g._frame.options[0].id
        self.choose(g, key); return key

    def test_complete_original_faces_auxiliary_profile_and_native_declarations_are_pinned(self):
        data = load_batch(); rows = {x['record']['id']: x['record'] for x in data['existing_dependencies']}
        self.assertEqual((len(rows), len(data['official_observations'])), (7, 12))
        for face in data['official_observations']: batch.check_face(rows[face['card_id']], face['face'], face['locale'])
        before = batch.registration_prefix(build_registry,
            'hs_sim.cards.zombeast_native_first_consumers.register_zombeast_native_first_consumers',
            register_zombeast_native_first_consumers)
        self.assertFalse(set(PARTS) & set(before.crafted_minion_parts))
        self.assertTrue(set(PARTS) <= set(fixture().crafted_minion_parts))
        self.assertFalse(any(k[0] in (FIRST, SECOND) for k in build_registry().pools))

    def test_all_six_real_paid_tamers_and_composed_bodies_keep_original_cost_and_entry_identity(self):
        for index, part in enumerate(PARTS):
            with self.subTest(part=part):
                player = 1+index%2; g = self.game(part, player=player)
                eid = self.craft(g, part, player); face = g.registry.card(self.recipe(part))
                self.play(g, face.id, player=player); self.settle(g, part)
                self.assertEqual(g.state.entities[eid].components, (part, SECOND_PART))
                self.assertEqual(g.state.players[player].mana, 29-face.cost)
                row = next(x for x in reversed(g.state.battlecry_history) if x.source_id == eid)
                self.assertEqual(row.payload.card_id, part)

    def test_composed_fetcher_accepts_full_existing_assemble_pool_and_delivers_real_four_cost_face(self):
        part = 'BE_044'; g = self.game(part); eid = self.craft(g, part)
        self.play(g, self.recipe(part)); offer = g._frame.options[0].effects[0].offer
        self.assertEqual(offer.spec.source_id, eid)
        self.assertEqual((offer.spec.primary_query.min_cost, offer.spec.primary_query.max_cost), (4, 4))
        other = self.portable(g)
        for current in (g, other): self.settle(current, part)
        self.assertEqual(g.snapshot(), other.snapshot())
        created = [g.state.entities[i] for i in g.state.players[1].hand
            if g.state.entities[i].card_id.startswith('assemble:')]
        self.assertEqual(len(created), 1); self.assertEqual(g.registry.card(created[0].card_id).cost, 4)
        self.assertEqual(len(g.state.players[1].board), 2)

    def test_gorilla_requires_another_current_mech_and_uses_actual_mech_discovery(self):
        part = 'CORE_LOE_039'
        g = self.game(part); self.craft(g, part); self.play(g, self.recipe(part))
        self.assertIsNone(g.state.pending_choice)
        g = self.game(part, own=(part,)); eid = self.craft(g, part); self.play(g, self.recipe(part))
        self.assertIsNotNone(g.state.pending_choice)
        offered = [o.card_id for o in g._frame.options]
        self.assertTrue(all('mech' in g.registry.card(cid).metadata.tribes or
            'all' in g.registry.card(cid).metadata.tribes for cid in offered))
        self.settle(g, part)
        self.assertEqual(len(g.state.players[1].hand), 1)
        self.assertEqual(g.state.entities[eid].components, (part, SECOND_PART))

    def test_dark_gift_discovery_uses_full_native_pairing_and_preserves_created_gift(self):
        part = 'END_013'; g = self.game(part); eid = self.craft(g, part)
        self.play(g, self.recipe(part)); other = self.portable(g)
        option = next((o for o in g._frame.options if o.effects[0].selection.gift.destination == 'hand'), g._frame.options[0])
        selection = option.effects[0].selection
        for current in (g, other): self.choose(current, option.id)
        self.assertEqual(g.snapshot(), other.snapshot())
        created = [g.state.entities[e.target_id] for e in g.events
            if e.kind == 'card_created' and e.source_id == eid]
        self.assertEqual(len(created), 1)
        self.assertEqual(g.registry.card(created[0].card_id).cost, 1)
        self.assertEqual(created[0].zone, Zone.HAND if selection.gift.destination == 'hand' else Zone.DECK)
        self.assertTrue(created[0].abilities)

    def test_marked_suspicious_pick_uses_original_profile_but_rewards_composed_body(self):
        part = 'JAIL_EVENT_100'; g = self.game(part); eid = self.craft(g, part)
        self.play(g, self.recipe(part)); proof = self.suspicious(g)
        self.assertEqual(proof.request.profile_card_id, part)
        self.assertEqual(proof.source_card_id, self.recipe(part)); self.assertEqual(proof.request.source.entity_id, eid)
        attack, health = g.state.entities[eid].attack, g.state.entities[eid].max_health
        other = self.portable(g)
        for current in (g, other): self.settle(current, part)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].max_health), (attack+1, health+1))
        self.assertEqual(len(g.state.players[1].hand), 1)

    def test_suspicious_source_death_during_choice_preserves_delivery_without_rebinding_bonus(self):
        part = 'JAIL_EVENT_100'; g = self.game(part, variant='leave'); eid = self.craft(g, part)
        self.play(g, self.recipe(part)); self.settle(g, part)
        self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand), 1)
        self.assertEqual(sum(g.state.entities[i].card_id == self.recipe(part) for i in g.state.players[1].board), 0)
        self.portable(g)

    def test_wrong_suspicious_pick_keeps_delivery_but_does_not_grant_body_stats(self):
        part = 'JAIL_EVENT_100'; g = self.game(part); eid = self.craft(g, part)
        self.play(g, self.recipe(part)); proof = self.suspicious(g)
        before = (g.state.entities[eid].attack, g.state.entities[eid].max_health)
        self.choose(g, 'card'+str((proof.marked_index+1)%len(proof.offered)+1))
        self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].max_health), before)
        self.assertEqual(len(g.state.players[1].hand), 1)

    def test_torga_draws_original_kindred_and_activating_physical_cards_without_pool_generation(self):
        part = 'TLC_102'; g = self.game(part); self.craft(g, part); self.play(g, self.recipe(part))
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [KINDRED, ACTIVATOR])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck], [YETI])
        self.assertEqual(len(g.state.draw_history), 2)

    def test_torga_draw_wait_recovers_original_second_selector_and_rolls_back_failed_resume(self):
        part = 'TLC_102'; g = self.game(part, variant='draw'); self.craft(g, part)
        self.play(g, self.recipe(part)); saved = g.snapshot(); other = self.portable(g)
        with self.assertRaisesRegex(ResolutionError, 'K575 intentional'): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for current in (g, other):
            while current.state.pending_choice is not None: self.choose(current, 'ok')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [KINDRED, ACTIVATOR])

    def test_torga_without_native_kindred_does_not_fallback_to_draw_or_fatigue(self):
        part = 'TLC_102'; g = self.game(part, deck=(YETI,)); self.craft(g, part)
        self.play(g, self.recipe(part)); self.assertFalse(g.state.draw_history)
        self.assertEqual(len(g.state.players[1].deck), 1)

    def test_dreamsaber_uses_actual_quest_discounted_payment_to_attack_two_original_targets(self):
        part = 'EDR_014'; g = self.game(part); self.craft(g, part); self.play(g, self.recipe(part))
        self.assertFalse(g.state.character_attack_history)
        g = self.game(part, hand=(QUEST, SECOND_PART, SECOND_PART, SECOND_PART))
        self.play(g, QUEST)
        for _ in range(3): self.play(g, SECOND_PART)
        self.pick(g, part); self.pick(g, SECOND_PART); eid = self.entity(g, self.recipe(part)).id
        self.play(g, self.recipe(part)); attacks = g.state.character_attack_history
        self.assertEqual(len(attacks), 2)
        self.assertTrue(all(x.declaration.source_id == eid for x in attacks))
        self.assertEqual(len({x.declaration.target_id for x in attacks}), 2)
        self.assertEqual(g.state.players[1].mana, 23)

    def test_actual_two_forced_attacks_wait_restore_and_keep_original_paid_play(self):
        part = 'EDR_014'; g = self.game(part,
            hand=(QUEST, SECOND_PART, SECOND_PART, SECOND_PART), variant='attack')
        self.play(g, QUEST)
        for _ in range(3): self.play(g, SECOND_PART)
        self.pick(g, part); self.pick(g, SECOND_PART); self.play(g, self.recipe(part))
        saved = g.snapshot(); other = self.portable(g)
        with self.assertRaisesRegex(ResolutionError, 'K575 intentional'): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for current in (g, other):
            while current.state.pending_choice is not None: self.choose(current, 'ok')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(g.state.character_attack_history), 2)
        self.assertEqual(g.state.players[1].mana, 23)

    def test_failed_suspicious_delivery_restores_exact_menu_payment_rng_and_source(self):
        part = 'JAIL_EVENT_100'; g = self.game(part, variant='fail'); self.craft(g, part)
        self.play(g, self.recipe(part)); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K575 intentional'): self.settle(g, part)
        self.assertEqual(g.snapshot(), saved)

    def test_missing_adapter_never_trims_the_known_first_candidate(self):
        part = 'BE_044'; g = self.game(part, variant='unadapted'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, TAMER)
        self.assertEqual(g.snapshot(), saved)
        self.assertEqual(tuple(m.card_id for m in g.registry.pool(FIRST, g._generation_context).members), (part,))

    def test_original_profile_is_required_before_any_native_first_donor_is_approved(self):
        r = batch.registration_prefix(build_registry,
            'hs_sim.cards.zombeast_native_first_consumers.register_zombeast_native_first_consumers',
            register_zombeast_native_first_consumers)
        r._suspicious_discovery_profiles.pop('JAIL_EVENT_100')
        with self.assertRaisesRegex(TargetValidationError, 'complete original discovery profile'):
            register_zombeast_native_first_consumers(r)
        self.assertFalse(set(PARTS) & set(r.crafted_minion_parts))


if __name__ == '__main__':
    unittest.main()
