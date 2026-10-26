"""The actual Platysaur draw belongs to the original composed Deathrattle."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_scourge_tamer_card import CARD as TAMER, BODY as TAMER_BODY
from hs_sim.cards.storm_gates_card import CARD as QUEST, TEMPLATE, FIRST, SECOND
from hs_sim.cards.zombeast_native_draw_memory import (CARD, load_batch,
    register_zombeast_native_draw_memory)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    Game, PlayerSetup, Registry, ResolutionError, Scenario, SnapshotError,
    TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.crafted_faces import (CraftedMinionRecipe, native_domains,
    validate_part_shape)
from hs_sim.engine.crafted_offers import ResolveCraft
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.deathrattle_memory import validate_carrier
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k573.'
HERO, POWER, UNIT, KILL, QUIET, BOUNCE, CURRENT, BASE, HAND_COPY, CONTROL, CHANGE, WATCH = (
    P+x for x in ('hero', 'power', 'unit', 'kill', 'quiet', 'bounce', 'current',
        'base', 'hand-copy', 'control', 'change', 'watch'))
META = CardMetadata(False, (CardClass.HUNTER,), None)
SECOND_PART = 'LOOT_258'
RECIPE = CraftedMinionRecipe(TEMPLATE, CARD, SECOND_PART)
CONTEXT = GenerationContext('explicit-k573-native-draw-memory-fixture', 'experimental')


@lru_cache(None)
def originals():
    return build_registry()


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    source = originals(); r = Registry(P+mode)
    for cid in (CARD, TAMER, QUEST, TEMPLATE, SECOND_PART):
        r.register_card(source.card(cid))
    for name in (TAMER_BODY, 'cards.storm_gates.progress', 'cards.storm_gates.reward',
            'cards.deathrattle_memory.draw', 'cards.deathrattle_memory.discard'):
        r.register_behavior(name, source.behavior(name))
    if mode != 'unadapted': register_zombeast_native_draw_memory(r)
    r.register_crafted_minion_part(SECOND_PART)
    r.register_crafted_minion_blueprint(source.crafted_minion_blueprints[TEMPLATE])
    r.register_behavior(P+'noop', lambda c: ())
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100, metadata=META))
    r.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, cost=2,
        on_use=P+'noop', metadata=META))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=2, health=30, metadata=META))
    scripts = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        QUIET: lambda c: (Silence(c.target_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        CURRENT: lambda c: (CopyMinion(c.target_id, c.player_id),),
        BASE: lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        HAND_COPY: lambda c: (CopyCard(MinionReference.capture(c.state.entities[c.target_id]),
            c.player_id, mode='current', source_id=c.source_id),),
        CONTROL: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        CHANGE: lambda c: (Transform(c.target_id, UNIT),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            metadata=META, targeting=TargetSpec(TargetMode.REQUIRED, kinds=(CardType.MINION,))))
    def fail(c):
        raise ResolutionError('K573 intentional native memory failure')
    def watch(c):
        if c.event.kind == 'card_drawn':
            entity = c.state.entities.get(c.event.source_id)
            if entity is None or entity.card_id != RECIPE.card_id or entity.zone != Zone.BOARD:
                return ()
            links = tuple(link for a in entity.abilities if a.deathrattle_memory is not None
                for link in a.deathrattle_memory.draws)
            if not any(link.draw_id == dict(c.event.data)['draw_id'] for link in links):
                raise AssertionError('The actual draw notification preceded its native memory commit')
            if mode == 'kill-draw': return (Destroy(entity.id, c.source_id),)
            if mode == 'fail-draw': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        elif c.event.kind != 'card_discarded' or mode != 'wait-discard':
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'continue', ()),
            ChoiceOption('bad', 'fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
        ), c.source_id),)
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=100,
        triggers=(TriggerSpec('card_discarded' if mode == 'wait-discard' else 'card_drawn', P+'watch'),),
        metadata=META))
    for cid in (CARD, SECOND_PART): r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    for pool, cid in ((FIRST, CARD), (SECOND, SECOND_PART)):
        r.register_pool(PoolDefinition(pool, 'explicit-native-draw-link-v1',
            CONTEXT.target_id, CONTEXT.mode, (PoolMember(cid),), complete=True))
    r.validate(); return r


def rehash(value):
    value['events_hash'] = canonical_hash(value['events'])
    value['state_hash'] = canonical_hash({k:v for k,v in value.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return value


class ZombeastNativeDrawMemoryTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, *, hand=(TAMER, KILL), own=(), enemy=(), player=1,
            opposing_hand=(), deck=(UNIT,)*8, mode='normal'):
        self.mode = mode
        setups = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            hand=hand if p == player else opposing_hand, board=own if p == player else enemy,
            deck=deck if p == player else (UNIT,)*8, mana=30, max_mana=30, mana_cap=30)
            for p in (1, 2))
        return Game.from_scenario(Scenario(setups, active_player=player, seed=573,
            generation_context=CONTEXT), fixture(mode))

    def pick(self, g, cid):
        option = next(row for row in g._frame.options if any(
            type(e) is ResolveCraft and e.card_id == cid for e in row.effects))
        self.choose(g, option.id)

    def craft(self, g, player=1):
        self.play(g, TAMER, player=player); self.pick(g, CARD); self.pick(g, SECOND_PART)
        return self.entity(g, RECIPE.card_id, player).id

    def memory(self, g, eid):
        return next(a.deathrattle_memory for a in g.state.entities[eid].abilities
            if a.deathrattle_memory is not None)

    def test_complete_original_face_and_definition_pin_do_not_authorize_formal_pool_membership(self):
        data = load_batch(); raw = data['existing_dependencies'][0]['record']
        for face in data['official_observations']: batch.check_face(raw, face['face'], face['locale'])
        self.assertEqual(len(data['official_observations']), 2)
        before = batch.registration_prefix(build_registry,
            'hs_sim.cards.zombeast_native_draw_memory.register_zombeast_native_draw_memory',
            register_zombeast_native_draw_memory)
        self.assertNotIn(CARD, before.crafted_minion_parts)
        self.assertIn(CARD, originals().crafted_minion_parts)
        self.assertFalse(any(key[0] in (FIRST, SECOND) for key in originals().pools))
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_paid_tamer_and_composed_battlecry_draw_and_death_keep_one_original_physical_card(self):
        for player in (1, 2):
            with self.subTest(player=player):
                g = self.game(player=player, hand=(TAMER, KILL, UNIT))
                other = self.entity(g, UNIT, player).id; eid = self.craft(g, player)
                self.assertFalse(self.memory(g, eid).draws)
                self.play(g, RECIPE.card_id, player=player); link, = self.memory(g, eid).draws
                self.assertNotEqual(link.entity_id, other)
                self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].max_health), (2, 5))
                self.assertEqual(g.state.players[player].mana, 27)
                self.play(g, KILL, eid, player)
                self.assertEqual(g.state.discard_history[-1].entity_id, link.entity_id)
                self.assertIn(other, g.state.players[player].hand)
                self.assertEqual(g.state.death_history[-1].components, RECIPE.parts)

    def test_actual_standard_sidequest_keeps_discount_and_original_draw_deathrattle(self):
        g = self.game(hand=(QUEST, SECOND_PART, SECOND_PART, SECOND_PART, KILL))
        self.play(g, QUEST)
        for _ in range(3): self.play(g, SECOND_PART)
        self.pick(g, CARD); self.pick(g, SECOND_PART); eid = self.entity(g, RECIPE.card_id).id
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[eid]).amount, 0)
        mana = g.state.players[1].mana; self.play(g, RECIPE.card_id)
        self.assertEqual(g.state.players[1].mana, mana)
        link, = self.memory(g, eid).draws; self.play(g, KILL, eid)
        self.assertEqual(g.state.discard_history[-1].entity_id, link.entity_id)
        self.portable(g)

    def test_current_board_copy_preserves_original_link_and_discards_it_at_most_once(self):
        g = self.game(hand=(TAMER, CURRENT, KILL, KILL)); eid = self.craft(g)
        self.play(g, RECIPE.card_id); self.play(g, CURRENT, eid)
        copy = next(i for i in g.state.players[1].board
            if i != eid and g.state.entities[i].card_id == RECIPE.card_id)
        self.assertEqual(self.memory(g, copy).draws, self.memory(g, eid).draws)
        self.play(g, KILL, eid); self.play(g, KILL, copy)
        self.assertEqual(len(g.state.discard_history), 1); self.portable(g)

    def test_current_hand_copy_retains_old_link_then_real_paid_replay_adds_new_draw(self):
        g = self.game(hand=(TAMER, HAND_COPY, KILL, KILL)); eid = self.craft(g)
        self.play(g, RECIPE.card_id); self.play(g, HAND_COPY, eid)
        copy = self.entity(g, RECIPE.card_id).id
        self.assertEqual(self.memory(g, copy).draws, self.memory(g, eid).draws)
        self.play(g, RECIPE.card_id); self.assertEqual(len(self.memory(g, copy).draws), 2)
        self.play(g, KILL, eid); self.play(g, KILL, copy)
        self.assertEqual(len(g.state.discard_history), 2); self.portable(g)

    def test_base_copy_uses_fresh_empty_memory_without_replaying_battlecry(self):
        g = self.game(hand=(TAMER, BASE, KILL, KILL)); eid = self.craft(g)
        self.play(g, RECIPE.card_id); self.play(g, BASE, eid)
        copy = next(i for i in g.state.players[1].board
            if i != eid and g.state.entities[i].card_id == RECIPE.card_id)
        self.assertFalse(self.memory(g, copy).draws)
        self.play(g, KILL, copy); self.assertFalse(g.state.discard_history)
        self.play(g, KILL, eid); self.assertEqual(len(g.state.discard_history), 1)

    def test_bounce_resets_original_native_memory_and_actual_replay_draws_a_fresh_card(self):
        g = self.game(hand=(TAMER, BOUNCE, KILL)); eid = self.craft(g)
        self.play(g, RECIPE.card_id); old, = self.memory(g, eid).draws
        self.play(g, BOUNCE, eid); self.assertFalse(self.memory(g, eid).draws)
        self.play(g, RECIPE.card_id); new, = self.memory(g, eid).draws
        self.assertNotEqual(new.entity_id, old.entity_id); self.play(g, KILL, eid)
        self.assertIn(old.entity_id, g.state.players[1].hand)
        self.assertEqual(g.state.discard_history[-1].entity_id, new.entity_id)

    def test_drawn_card_leaving_and_returning_is_not_rebound_to_original_memory(self):
        g = self.game(hand=(TAMER, BOUNCE, KILL)); eid = self.craft(g)
        self.play(g, RECIPE.card_id); link, = self.memory(g, eid).draws
        self.play(g, UNIT); self.play(g, BOUNCE, link.entity_id); self.play(g, KILL, eid)
        self.assertIn(link.entity_id, g.state.players[1].hand)
        self.assertFalse(g.state.discard_history)

    def test_silence_and_transform_remove_native_discard_memory(self):
        for action in (QUIET, CHANGE):
            with self.subTest(action=action):
                g = self.game(hand=(TAMER, action, KILL)); eid = self.craft(g)
                self.play(g, RECIPE.card_id); self.play(g, action, eid); self.play(g, KILL, eid)
                self.assertFalse(g.state.discard_history)

    def test_draw_notification_already_contains_link_if_source_is_immediately_destroyed(self):
        g = self.game(hand=(TAMER,), own=(WATCH,), mode='kill-draw'); eid = self.craft(g)
        self.play(g, RECIPE.card_id)
        self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.discard_history), 1); self.portable(g)

    def test_draw_wait_restores_original_memory_and_failed_choice_rolls_back_exact_frame(self):
        g = self.game(own=(WATCH,), mode='wait-draw'); eid = self.craft(g)
        self.play(g, RECIPE.card_id); saved = g.snapshot(); other = self.portable(g)
        self.assertEqual(len(self.memory(g, eid).draws), 1)
        with self.assertRaisesRegex(ResolutionError, 'K573 intentional'): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for current in (g, other): self.choose(current, 'ok'); self.play(current, KILL, eid)
        self.assertEqual(g.snapshot(), other.snapshot())

    def test_discard_wait_restores_frozen_composed_death_record_and_original_link(self):
        g = self.game(own=(WATCH,), mode='wait-discard'); eid = self.craft(g)
        self.play(g, RECIPE.card_id); self.play(g, KILL, eid)
        saved = g.snapshot(); other = self.portable(g)
        with self.assertRaisesRegex(ResolutionError, 'K573 intentional'): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for current in (g, other): self.choose(current, 'ok')
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_fatigue_creates_no_hand_link_and_death_does_not_discard_another_card(self):
        g = self.game(hand=(TAMER, KILL, UNIT), deck=()); eid = self.craft(g)
        self.play(g, RECIPE.card_id); self.assertFalse(self.memory(g, eid).draws)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 99)
        self.play(g, KILL, eid); self.assertFalse(g.state.discard_history)

    def test_control_change_keeps_original_draw_owner_and_physical_acquisition(self):
        g = self.game(hand=(TAMER, CONTROL, KILL), opposing_hand=(UNIT,)); eid = self.craft(g)
        self.play(g, RECIPE.card_id); link, = self.memory(g, eid).draws
        enemy = self.entity(g, UNIT, 2).id; self.play(g, CONTROL, eid); self.play(g, KILL, eid)
        self.assertEqual(g.state.discard_history[-1].entity_id, link.entity_id)
        self.assertIn(enemy, g.state.players[2].hand)

    def test_memory_is_private_and_both_original_crafting_waits_restore(self):
        g = self.game(); self.play(g, TAMER)
        for chosen in (CARD, SECOND_PART):
            other = self.portable(g)
            for current in (g, other): self.pick(current, chosen)
            self.assertEqual(g.snapshot(), other.snapshot())
        self.play(g, RECIPE.card_id)
        for player in (1, 2):
            view = json.dumps(g.for_player(player).observe())
            for key in ('deathrattle_memory', 'draw_id', 'hand_entry_id', 'resolution_frame'):
                self.assertNotIn('"'+key+'"', view)

    def test_unreviewed_memory_carrier_grants_and_foreign_recipe_are_rejected(self):
        g = self.game(); eid = self.craft(g); self.play(g, RECIPE.card_id)
        ability = next(a for a in g.state.entities[eid].abilities if a.deathrattle_memory is not None)
        unrelated = CraftedMinionRecipe(TEMPLATE, SECOND_PART, SECOND_PART)
        for card, components, value in ((UNIT, (), ability),
                (unrelated.card_id, unrelated.parts, ability)):
            with self.subTest(card=card, origin=value.origin), self.assertRaises(ValueError):
                validate_carrier(g.state, g.registry, card, CardType.MINION, (value,), components)
        with self.assertRaisesRegex(ValueError, 'physical provenance'):
            replace(ability, origin='granted')

    def test_rehashed_printed_donor_or_physical_draw_link_changes_are_rejected(self):
        g = self.game(); eid = self.craft(g); self.play(g, RECIPE.card_id); saved = g.snapshot()
        for field in ('donor', 'draw', 'hand'):
            with self.subTest(field=field):
                bad = deepcopy(saved)
                a = next(x for x in bad['state']['entities'][str(eid)]['abilities']
                    if x['deathrattle_memory'] is not None)
                if field == 'donor': a['deathrattle_card_id'] = SECOND_PART
                elif field == 'draw': a['deathrattle_memory']['draws'][0]['draw_id'] = 99999
                else: a['deathrattle_memory']['draws'][0]['hand_entry_id'] = 99999
                with self.assertRaises(SnapshotError) as caught:
                    Game.from_snapshot(rehash(bad), fixture('normal', 'independent-reader'))
                self.assertNotIn('digest mismatch', str(caught.exception))

    def test_other_native_memory_domains_and_multiple_memory_donors_stay_explicitly_unsupported(self):
        with self.assertRaisesRegex(ValueError, 'native Deathrattle memory domain'):
            validate_part_shape(originals(), originals().card('CATA_210'))
        with self.assertRaisesRegex(ValueError, 'multiple native Deathrattle memory donors'):
            native_domains((originals().card(CARD), originals().card(CARD)))

    def test_failure_during_actual_draw_rolls_back_payment_deck_and_memory(self):
        g = self.game(own=(WATCH,), mode='fail-draw'); self.craft(g); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K573 intentional'): self.play(g, RECIPE.card_id)
        self.assertEqual(g.snapshot(), saved)

    def test_missing_adapter_is_not_silently_removed_from_complete_original_inventory(self):
        g = self.game(mode='unadapted'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, TAMER)
        self.assertEqual(g.snapshot(), saved)
        self.assertEqual(tuple(x.card_id for x in g.registry.pool(FIRST, CONTEXT).members), (CARD,))

    def test_mutated_original_definition_rejects_before_donor_registration(self):
        r = Registry(P+'bad'); card = originals().card(CARD)
        r.register_card(replace(card, attack=card.attack+1))
        for body in (card.battlecry, card.deathrattle): r.register_behavior(body, originals().behavior(body))
        with self.assertRaisesRegex(TargetValidationError, 'Unreviewed complete'):
            register_zombeast_native_draw_memory(r)
        self.assertNotIn(CARD, r.crafted_minion_parts)


if __name__ == '__main__':
    unittest.main()
