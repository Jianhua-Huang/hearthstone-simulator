"""Actual Elise manufacture and finite location components through native entries."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import base64
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.elise_location_cards import CARD, RAPTOR, TEMPLATES, PARTS, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardType, ChoicePurpose, DeckPolicy,
    DamageKind, DeckSpec, EndTurn, Game, IllegalAction, Keyword, MatchSetup, OpeningHook, PlayCard,
    PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec,
    UnknownDeckFacts, UseLocation, Zone)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.composed_locations import (PREFIX, VERSION, ROOT, OFFER, PICK, CREATED,
    USE, STEP, END, LocationRecipe, recipe_from_id, use_components, checked_recipe)
from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import (AddToHand, ChangeManaCrystals, ChoiceOption, Damage,
    Destroy, GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Summon)
from hs_sim.engine.locations import DestroyLocation, ModifyLocation
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import CardReference, DestroyDeckMatching, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from test_current_deck_empty_basics import rehash

P = 'fixture.elise.'
UNIT, WATCH, FILLER, PREP, TRIGGER = (P + x for x in ('unit', 'watch', 'filler', 'prepare', 'trigger'))
SPELLS = ('CORE_CS2_029', 'CORE_CS2_032', 'CORE_CS2_024')
CTX = GenerationContext('elise-complete-explicit-spell-experiment', 'experimental')


def location(tier, first, second):
    return LocationRecipe(TEMPLATES[tier - 1], f'TLC_100t{tier}{first}', f'TLC_100t{tier}{second}').card_id


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r = build_registry()
    r.register_behavior(P + 'sentinel', lambda c: (GainArmor(c.player_id, 99),))
    for cid, cost, health in ((UNIT, 0, 8), (FILLER, 0, 2), *(
            (P + f'cost{i}', i, 2) for i in (1, 2, 3, 5, 6, 7, 8, 9))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=1,
            health=health, metadata=metadata(), keywords=(Keyword.TAUNT,) if cid == UNIT else (),
            battlecry=P + 'sentinel' if cid == UNIT else None))
    r.register_behavior(P + 'fail', lambda c: fail())

    def reenter(c):
        target = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id == UNIT)
        return (SummonStoredCard(CardReference.capture(target), c.player_id),)
    r.register_behavior(P + 'reenter', reenter)

    def watch(c):
        e = c.event
        if mode == 'kill_crafter' and e.kind == 'choice_requested' and e.source_id is not None:
            source = c.state.entities[e.source_id]
            return (Destroy(source.id, c.source_id),) if source.card_id == CARD and source.zone == Zone.BOARD else ()
        if mode == 'craft_fill' and e.kind == 'choice_selected' and c.state.entities[e.source_id].card_id == CARD:
            return tuple(AddToHand(c.player_id, FILLER, c.source_id) for _ in range(10 - len(c.state.players[c.player_id].hand)))
        if e.kind == 'location_activated' and mode == 'wait_activation':
            extra = () if e.target_id is None else (ChoiceOption('bounce', 'Return and reenter original target',
                (ReturnToHand(e.target_id), InvokeBehavior(P + 'reenter', c.source_id, c.player_id))),)
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('kill', 'Destroy original location', (DestroyLocation(e.source_id, c.source_id),)),
                *extra), c.source_id),)
        if e.kind == 'minion_summoned' and c.state.entities[e.target_id].card_id == RAPTOR:
            if mode == 'fail_summon':
                raise ResolutionError('Explicit Elise summon observer failed')
            if mode == 'wait_summon':
                return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
                    ChoiceOption('bad', 'Fail', (InvokeBehavior(P + 'fail', c.source_id, c.player_id),))), c.source_id),)
        return ()
    r.register_behavior(P + 'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, triggers=tuple(
        TriggerSpec(kind, P + 'watch') for kind in ('location_activated', 'minion_summoned', 'choice_requested', 'choice_selected'))))

    def prepare(c):
        source = next(e for e in c.state.entities.values() if e.controller == c.player_id and e.card_id == CARD)
        move = () if source.zone == Zone.HAND else (MoveCard(CardReference.capture(source), c.player_id, Zone.HAND),)
        observer = (Summon(c.player_id, WATCH),) if mode in ('kill_crafter', 'craft_fill') else ()
        return (ChangeManaCrystals(c.player_id, 9), *move, AddToHand(c.player_id, TRIGGER),
            AddToHand(c.player_id, P + 'empty'), *observer)
    r.register_behavior(P + 'prepare', prepare)
    r.register_card(CardDefinition(PREP, PREP, CardType.MINION, health=2, metadata=metadata(),
        opening_hooks=(OpeningHook('after_mulligan', P + 'prepare'),)))
    def trigger(c):
        source = next(c.state.entities[i] for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == CARD)
        return (TriggerBattlecry(MinionReference.capture(source), c.source_id),)
    r.register_behavior(P + 'trigger', trigger)
    r.register_card(CardDefinition(TRIGGER, TRIGGER, CardType.MINION, health=2, battlecry=P + 'trigger', metadata=metadata()))
    def last(c):
        entity = next(c.state.entities[i] for i in c.state.players[c.player_id].board if c.state.entities[i].card_id.startswith(PREFIX))
        return (ModifyLocation(entity.id, 1 - entity.durability, c.source_id),)
    for key, body in (('last', last), ('hit', lambda c: (Damage(c.state.players[2].hero_id, 1, c.source_id,
            kind=DamageKind.SPELL),)),
            ('empty', lambda c: (DestroyDeckMatching(c.player_id, count=40, reveal=False),))):
        r.register_behavior(P + key, body)
        r.register_card(CardDefinition(P + key, key, CardType.SPELL, on_play=P + key))
    members = tuple(PoolMember(cid) for cid in SPELLS)
    if mode == 'unknown_pool':
        unknown = CardDefinition(P + 'unknown', 'Explicit eligible but unimplemented spell', CardType.SPELL,
            metadata=metadata(CardClass.MAGE))
        r.register_pool_card(PoolCard.from_definition(unknown)); members += (PoolMember(unknown.id),)
    r.register_pool(PoolDefinition('constructed.cards', 'elise-fixture-v1', CTX.target_id, CTX.mode, members, complete=True))
    r.validate()
    return r


def fail():
    raise ResolutionError('Explicit Elise choice observer failed')


class EliseLocationTests(unittest.TestCase):
    def game(self, tier=1, parts=(2, 6), *, board=(), enemy=(), hand=(), mode='normal'):
        cid = location(tier, *parts)
        observer = (WATCH,) if mode in ('wait_activation', 'wait_summon', 'fail_summon') else ()
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', board=observer + board + (cid,), hand=hand, deck=(FILLER,) * 12, mana=10, max_mana=10),
            PlayerSetup('HERO_08', board=enemy, deck=(FILLER,) * 12, mana=10, max_mana=10)),
            seed=312, generation_context=CTX), fixture(mode))
    def match(self, *, count=10, mode='normal', seed=312):
        r = fixture(mode)
        own = (CARD, PREP) + tuple(P + f'cost{i}' for i in (1, 2, 3, 5, 6, 7, 8, 9)[:count - 2])
        own += (FILLER,) * (30 - len(own))
        policy = DeckPolicy('elise-explicit-opening', CTX.target_id, CTX.mode,
            tuple(dict.fromkeys((*own, FILLER))), max_copies=30)
        setup = MatchSetup((DeckSpec('HERO_08', 'HERO_08bp', CardClass.MAGE, own),
            DeckSpec('HERO_08', 'HERO_08bp', CardClass.MAGE, (FILLER,) * 30)), policy, 'GAME_005', seed, 1)
        g = Game.from_decks(setup, r)
        while g.state.pending_choice:
            self.choose(g, ())
        return g
    def entity(self, g, cid, player=1, zone='board'):
        return next(i for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)
    def play(self, g, cid, target=None):
        eid = self.entity(g, cid, zone='hand'); g.apply(PlayCard(1, eid, target)); return eid
    def choose(self, g, keys):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (keys,) if isinstance(keys, str) else tuple(keys)))
    def use(self, g, target=None):
        eid = next(i for i in g.state.players[1].board if g.state.entities[i].card_id.startswith(PREFIX))
        g.apply(UseLocation(1, eid, target)); return eid
    def cycle(self, g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
    def armor(self, g):
        return g.state.entities[g.state.players[1].hero_id].armor
    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, fixture.__wrapped__(mode)).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), fixture.__wrapped__(mode)).snapshot(), saved)
        return saved
    def craft(self, g, tier=1):
        self.play(g, CARD); self.choose(g, TEMPLATES[tier - 1])
        first = g.state.pending_choice.options[0].id; self.choose(g, first)
        second = g.state.pending_choice.options[0].id; self.choose(g, second)
        return location(tier, int(first[-1]), int(second[-1]))
    def events(self, g, kind):
        return tuple(e for e in g.events if e.kind == kind)

    def test_complete_source_eligibility_templates_and_existing_raptor_pin(self):
        data = load_batch(); r = fixture()
        self.assertEqual(len(data['official_observations']), 52)
        self.assertEqual([len(PARTS[t]) for t in (1, 2, 3)], [6, 7, 7])
        self.assertEqual(canonical_digest(asdict(r.card(RAPTOR))), data['existing_dependency_definition_pins'][RAPTOR])
        self.assertNotIn('TLC_100t17', r.cards)
        for tier, template in enumerate(TEMPLATES, 1):
            f = r.card(template)
            self.assertEqual((f.cost, f.durability, f.manual_playable), ((1, 5, 10)[tier - 1], 2, False))
            self.assertTrue(all(r.card(cid).choice_only and r.card(cid).on_play is None for cid in PARTS[tier]))

    def test_all_114_ordered_recipes_are_immutable_and_keep_only_real_requirements(self):
        r = fixture(); before = (len(r.cards), r.fingerprint()); total = 0
        for tier, parts in PARTS.items():
            for first in parts:
                for second in parts:
                    if first == second: continue
                    recipe = LocationRecipe(TEMPLATES[tier - 1], first, second); f = r.card(recipe.card_id)
                    self.assertEqual(recipe_from_id(recipe.card_id), recipe)
                    self.assertEqual(f.targeting is not None, first.endswith('7') or second.endswith('7'))
                    self.assertEqual(f.deathrattle is not None, first.endswith('1') or second.endswith('1'))
                    total += 1
        self.assertEqual(total, 114); self.assertEqual(before, (len(r.cards), r.fingerprint()))

    def test_invalid_duplicate_cross_tier_disabled_and_noncanonical_recipes_reject(self):
        r = fixture()
        for values in ((TEMPLATES[0], 'TLC_100t12', 'TLC_100t17'),
                (TEMPLATES[0], 'TLC_100t12', 'TLC_100t22'), ('unknown', 'TLC_100t12', 'TLC_100t16')):
            with self.subTest(values=values), self.assertRaises(ValueError): r.card(LocationRecipe(*values).card_id)
        with self.assertRaises(ValueError): LocationRecipe(TEMPLATES[0], 'TLC_100t12', 'TLC_100t12')
        raw = json.dumps([VERSION, TEMPLATES[0], 'TLC_100t12', 'TLC_100t16']).encode()
        cid = PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip('=')
        with self.assertRaises(ValueError): r.card(cid)

    def test_real_deck_root_pays_once_and_builds_one_physical_location_at_each_tier(self):
        for tier in (1, 2, 3):
            g = self.match(); mana = g.state.players[1].mana; cid = self.craft(g, tier)
            reward = self.entity(g, cid, zone='hand')
            self.assertEqual(g.state.players[1].mana, mana - 4)
            self.assertEqual((len(self.events(g, ROOT)), len(self.events(g, PICK)), len(self.events(g, CREATED))), (1, 3, 1))
            self.assertEqual((len(g.state.play_history), len(g.state.cast_history)), (1, 0))
            self.assertEqual(g.state.entities[reward].kind, CardType.LOCATION)
        self.portable(g)

    def test_nine_starting_costs_do_not_manufacture(self):
        g = self.match(count=9); self.play(g, CARD)
        self.assertFalse(g.state.pending_choice); self.assertFalse(self.events(g, ROOT))

    def test_unknown_starting_deck_is_explicit_and_original_root_rolls_back(self):
        g = self.game(hand=(CARD,)); before = g.snapshot()
        with self.assertRaises(UnknownDeckFacts): self.play(g, CARD)
        self.assertEqual(g.snapshot(), before)

    def test_three_waiting_menus_restore_without_reroll_and_exclude_only_chosen_part(self):
        g = self.match(); self.play(g, CARD); self.portable(g)
        self.choose(g, TEMPLATES[1]); self.portable(g)
        first_options = tuple(o.id for o in g.state.pending_choice.options)
        first = first_options[0]; self.choose(g, first); self.portable(g)
        data = dict(self.events(g, OFFER)[-1].data)
        self.assertEqual(data['candidates'], tuple(cid for cid in PARTS[2] if cid != first))
        self.assertEqual(len(g.state.pending_choice.options), 3)
        self.assertNotIn(first, tuple(o.id for o in g.state.pending_choice.options))
        self.choose(g, g.state.pending_choice.options[0].id); self.portable(g)

    def test_invalid_menu_input_does_not_reroll_or_change_original_offer(self):
        g = self.match(); self.play(g, CARD); self.choose(g, TEMPLATES[0]); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.choose(g, 'TLC_100t17')
        self.assertEqual(g.snapshot(), before)

    def test_original_starting_cost_facts_survive_current_deck_emptying(self):
        g = self.match()
        # An explicit host effect changes only the remaining physical deck.
        self.play(g, P + 'empty'); self.assertFalse(g.state.players[1].deck)
        self.play(g, CARD); self.assertIsNotNone(g.state.pending_choice)

    def test_accepted_manufacture_survives_crafter_death_and_normal_full_hand_burn(self):
        g = self.match(mode='kill_crafter'); cid = self.craft(g)
        self.assertEqual(g.state.entities[self.entity(g, CARD, zone='graveyard')].zone, Zone.GRAVEYARD)
        self.assertIsNotNone(self.entity(g, cid, zone='hand')); self.portable(g, 'kill_crafter')
        g = self.match(mode='craft_fill'); cid = self.craft(g)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertEqual(g.state.entities[self.entity(g, cid, zone='graveyard')].zone, Zone.GRAVEYARD)
        reward = self.entity(g, cid, zone='graveyard')
        self.assertTrue(any(e.kind == 'card_burned' and e.target_id == reward for e in g.events))

    def test_automatic_battlecry_uses_original_menu_sampling_and_no_second_payment(self):
        g = self.match(); self.craft(g); mana = g.state.players[1].mana
        self.play(g, TRIGGER)
        self.assertFalse(g.state.pending_choice)
        self.assertEqual(g.state.players[1].mana, mana)
        self.assertEqual((len(self.events(g, ROOT)), len(self.events(g, CREATED))), (2, 2))
        self.portable(g)

    def test_moonlight_and_lava_at_all_tiers_keep_next_spell_across_turns(self):
        for tier, bonus, armor in ((1, 1, 3), (2, 2, 6), (3, 4, 12)):
            g = self.game(tier, hand=(P + 'hit',)); self.use(g); self.cycle(g)
            self.assertEqual(self.armor(g), armor); self.assertEqual(len(g.state.players[1].player_effects), 1)
            self.play(g, P + 'hit')
            self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 29 - bonus)
            self.assertFalse(g.state.players[1].player_effects)
        self.portable(g)

    def test_raptors_precede_attack_buff_in_both_selection_orders_at_all_tiers(self):
        for tier, count, bonus in ((1, 1, 1), (2, 2, 2), (3, 4, 4)):
            for parts in ((4, 5), (5, 4)):
                g = self.game(tier, parts); self.use(g)
                units = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == RAPTOR]
                self.assertEqual(len(units), count)
                self.assertTrue(all((e.attack, e.health) == (2 + bonus, 1) and Keyword.RUSH in e.keywords for e in units))
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack, bonus)
                g.apply(EndTurn(1))
                self.assertTrue(all(g.state.entities[e.id].attack == 2 for e in units))
        self.portable(g)

    def test_current_copy_keeps_keywords_fixed_stats_no_battlecry_and_precedes_buff(self):
        for tier, size, bonus in ((2, 3, 2), (3, 5, 4)):
            for parts in ((4, 7), (7, 4)):
                g = self.game(tier, parts, board=(UNIT,)); target = self.entity(g, UNIT); self.use(g, target)
                copies = [g.state.entities[i] for i in g.state.players[1].board if i != target and g.state.entities[i].card_id == UNIT]
                self.assertEqual(len(copies), 1)
                self.assertEqual((copies[0].attack, copies[0].health), (size + bonus, size))
                self.assertIn(Keyword.TAUNT, copies[0].keywords); self.assertEqual(self.armor(g), 0)
        self.portable(g)

    def test_geyser_is_deathrattle_only_and_last_use_keeps_captured_lava(self):
        for tier, damage, armor in ((1, 1, 3), (2, 3, 6), (3, 5, 12)):
            g = self.game(tier, (1, 6), enemy=(UNIT,)); source = self.use(g)
            self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)
            self.cycle(g); self.cycle(g); self.use(g)
            self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
            self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30 - damage)
            self.assertEqual(g.state.entities[self.entity(g, UNIT, 2)].health, 8 - damage)
            self.assertEqual(self.armor(g), armor * 2)
        self.portable(g)

    def test_full_board_rejects_early_summon_use_but_last_durability_frees_original_slot(self):
        g = self.game(3, (1, 5), board=(UNIT,) * 6, hand=(P + 'last',))
        before = g.snapshot()
        with self.assertRaises(IllegalAction): self.use(g)
        self.assertEqual(g.snapshot(), before)
        self.play(g, P + 'last'); source = self.use(g)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual(sum(g.state.entities[i].card_id == RAPTOR for i in g.state.players[1].board), 1)

    def test_real_discovery_cost_reduction_and_ordered_continuation_at_all_tiers(self):
        for tier, reduction, armor in ((1, 1, 3), (2, 4, 6), (3, 7, 12)):
            for parts in ((3, 6), (6, 3)):
                g = self.game(tier, parts); self.use(g)
                self.assertEqual(self.armor(g), 0 if parts[0] == 3 else armor)
                q = g.state.pending_choice; chosen = q.options[0].card_id
                self.choose(g, q.options[0].id)
                entity = g.state.entities[self.entity(g, chosen, zone='hand')]
                self.assertEqual(local_cost(entity)[0], max(0, g.registry.card(chosen).cost - reduction))
                self.assertEqual(self.armor(g), armor)
        self.portable(g)

    def test_discovery_wait_preserves_next_summon_component_in_independent_restore(self):
        g = self.game(2, (3, 5)); self.use(g); self.portable(g)
        self.assertFalse(any(g.state.entities[i].card_id == RAPTOR for i in g.state.players[1].board))
        self.choose(g, g.state.pending_choice.options[0].id)
        self.assertEqual(sum(g.state.entities[i].card_id == RAPTOR for i in g.state.players[1].board), 2)
        self.portable(g)

    def test_unknown_eligible_spell_is_not_removed_from_discovery_pool(self):
        g = self.game(1, (3, 6), mode='unknown_pool'); before = g.snapshot()
        with self.assertRaises(ValueError): self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_captured_body_survives_source_destruction_during_activation_wait(self):
        g = self.game(3, (5, 6), mode='wait_activation'); source = self.use(g)
        self.assertFalse(self.events(g, USE)); self.portable(g, 'wait_activation')
        self.choose(g, 'kill')
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(self.armor(g), 12)
        self.assertEqual(sum(g.state.entities[i].card_id == RAPTOR for i in g.state.players[1].board), 4)
        self.portable(g, 'wait_activation')

    def test_copy_original_target_leaves_and_reenters_but_other_component_still_executes(self):
        g = self.game(2, (7, 6), board=(UNIT,), mode='wait_activation')
        target = self.entity(g, UNIT); presence = g.state.entities[target].entered_order
        self.use(g, target); self.portable(g, 'wait_activation'); self.choose(g, 'bounce')
        self.assertGreater(g.state.entities[target].entered_order, presence)
        self.assertEqual(sum(g.state.entities[i].card_id == UNIT for i in g.state.players[1].board), 1)
        self.assertEqual(self.armor(g), 6); self.portable(g, 'wait_activation')

    def test_waiting_summon_and_failed_choice_keep_original_component_cursor(self):
        g = self.game(1, (5, 6), mode='wait_summon'); self.use(g); saved = self.portable(g, 'wait_summon')
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved); self.choose(g, 'ok')
        self.assertEqual(self.armor(g), 3); self.portable(g, 'wait_summon')
        g = self.game(1, (5, 6), mode='fail_summon'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_rehashed_finished_component_and_sampling_material_tampering_rejects(self):
        g = self.game(); self.use(g); saved = g.snapshot()
        changed = deepcopy(saved); event = next(e for e in changed['events'] if e['kind'] == STEP)
        event['data']['component'] = 'TLC_100t13'
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(changed), fixture())
        g = self.match(); self.play(g, CARD); self.choose(g, TEMPLATES[0]); changed = g.snapshot()
        event = next(e for e in changed['events'] if e['kind'] == OFFER and e['data']['template'] is not None)
        event['data']['candidates'] = event['data']['candidates'][:-1]
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(changed), fixture())

    def test_waiting_component_cannot_be_removed_duplicated_or_advanced_after_rehash(self):
        g = self.game(1, (5, 6), mode='wait_summon'); self.use(g); saved = g.snapshot()
        def edit(value, mode):
            if isinstance(value, list):
                for index, item in enumerate(value):
                    if isinstance(item, dict) and item.get('type') == 'hs_sim.engine.composed_locations.ContinueLocationUse':
                        if mode == 'remove': value.pop(index)
                        elif mode == 'duplicate': value.insert(index, deepcopy(item))
                        else: item['fields']['index'] = 2
                        return True
                    if edit(item, mode): return True
            elif isinstance(value, dict):
                for item in value.values():
                    if edit(item, mode): return True
            return False
        for mode in ('remove', 'duplicate', 'advance'):
            changed = deepcopy(saved); self.assertTrue(edit(changed, mode))
            with self.subTest(mode=mode), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(changed), fixture('wait_summon'))

    def test_owner_hand_recipe_public_board_and_private_manufacture_information(self):
        g = self.match(); cid = self.craft(g)
        owner = g.observe(1); opponent = g.observe(2)
        mine = next(p for p in owner['players'] if p['id'] == 1)['hand']
        hidden = next(p for p in opponent['players'] if p['id'] == 1)['hand']
        self.assertTrue(any(item.get('location_recipe') for item in mine))
        self.assertFalse(any(item.get('location_recipe') or item.get('card_id') == cid for item in hidden))
        for p in (1, 2):
            projected = json.dumps(g.observe(p)) + json.dumps(g.player_events(p))
            self.assertNotIn('rng_before', projected); self.assertNotIn('location_craft_offered', projected)
        # A public location exposes the selected recipe, without the discarded menus.
        self.play(g, cid)
        public = next(p for p in g.observe(2)['players'] if p['id'] == 1)['board']
        self.assertTrue(any(item.get('location_recipe') for item in public))
