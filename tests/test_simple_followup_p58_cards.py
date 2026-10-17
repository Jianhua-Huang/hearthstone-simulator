"""Real source pins and grouped native lifecycle, choice, death and cast paths."""
from dataclasses import asdict
from functools import lru_cache
import json
import random
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p58_cards import (NIGHTMARE, DREAM, SISTER, AWAKENING,
    HOOKTAIL, CHEST, ULFARR, LIFESOURCE, STRIKER, ORDINANCE, ROOTS, EXISTING, PARENT,
    PREFIX, POOL_ID, load_batch, register_simple_followup_p58_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice,
    TargetSpec, UseHandAction, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CostSpec,
    Damage, Destroy, Draw, GainArmor, InvokeBehavior, ModifyCost, RequestChoice,
    ReturnToHand, Silence, Summon, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.spell_history import CastFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import AddToDeck, CardReference
from hs_sim.targets import canonical_digest

TEST = 'p58.test.'
YETI = 'CORE_CS2_182'
NEUTRAL, MAGE, WARRIOR, EIGHT_A, EIGHT_B, DRAGON, ALL_RACE = (TEST + n for n in
    ('neutral', 'mage', 'warrior', 'eight_a', 'eight_b', 'dragon', 'all'))
UNKNOWN = TEST + 'unknown8'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
MEMBERS = (NEUTRAL, MAGE, WARRIOR, EIGHT_A, EIGHT_B)
CONTEXT = GenerationContext('p58-complete-explicit-fixture', 'experimental')


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata', lambda r: None):
        r = build_registry()
    present = tuple(cid in r.cards for cid in ROOTS)
    if not any(present):
        register_simple_followup_p58_cards(r)
    elif not all(present):
        raise AssertionError('P58 assembly must contain all ten complete definitions')
    register_candidate_pool_metadata(r)
    r.validate()
    return r


def registry(mode=None, members=MEMBERS):
    r = batch_registry()
    for cid, cost, cls, tribes in ((NEUTRAL, 4, CardClass.NEUTRAL, ()),
            (MAGE, 4, CardClass.MAGE, ()), (WARRIOR, 4, CardClass.WARRIOR, ()),
            (EIGHT_A, 8, CardClass.NEUTRAL, ()), (EIGHT_B, 8, CardClass.NEUTRAL, ()),
            (DRAGON, 1, CardClass.NEUTRAL, ('dragon',)), (ALL_RACE, 1, CardClass.NEUTRAL, ('all',))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=2,
            health=6, metadata=CardMetadata(True, (cls,), Rarity.COMMON, tribes=tribes)))
    r.register_card(CardDefinition(TEST + 'dormant', 'Dormant', CardType.MINION,
        health=5, dormant_turns=2, metadata=META))
    r.register_card(CardDefinition(TEST + 'power', 'Spell bonus', CardType.MINION,
        health=9, spell_damage=2, metadata=META))
    def sister(c, effect):
        target = next(i for p in (1, 2) for i in c.state.players[p].board if c.state.entities[i].card_id == SISTER)
        return (effect(target),)
    scripts = dict(
        kill=lambda c: (Destroy(c.target_id, c.source_id),),
        give=lambda c: (ChangeControl(c.target_id, 3-c.state.entities[c.target_id].controller),),
        grow=lambda c: (Buff(c.target_id, 2, 2, c.source_id), ModifyCost(c.target_id, CostSpec(set_to=0), c.source_id)),
        spell=lambda c: (GainArmor(c.player_id, 1),),
        silence=lambda c: (Silence(c.target_id),),
        trigger=lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        summon_dragon=lambda c: (Summon(c.player_id, DRAGON),),
        give_sister=lambda c: sister(c, lambda i: ChangeControl(i, 2)),
        silence_sister=lambda c: sister(c, Silence),
        kill_sister=lambda c: sister(c, lambda i: Destroy(i, c.source_id)),
        auto=lambda c: (CastFromPool(c.player_id, POOL_ID,
            PoolQuery(kinds=(CardType.SPELL,), collectible=False), count=3, source_id=c.source_id),),
        reenter=lambda c: (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]), 1,
            cause=SummonCause.capture(c)),),
        fail=lambda c: (_ for _ in ()).throw(ResolutionError('P58 deliberate continuation failure')))
    for name, body in scripts.items():
        r.register_behavior(TEST + name, body)
        r.register_card(CardDefinition(TEST + name, name, CardType.SPELL, on_play=TEST + name,
            targeting=TargetSpec() if name in ('kill', 'give', 'grow', 'silence', 'trigger') else None, metadata=META))
    r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 8,
        CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=()),
        battlecry=False, deathrattle=False, choose_one=False))
    for cid in members:
        if cid not in r.pool_cards:
            r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID, 'p58-complete-explicit-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode:
        def eligible(c):
            if mode == 'ordinance':
                return any(root.request.cause.source.card_id == ORDINANCE and
                    any(d.outcome == 'delivered' and d.entity.entity_id == c.event.target_id for d in root.deliveries)
                    for root in c.state.card_summon_history)
            source = c.state.entities.get(c.event.source_id)
            return source is not None and source.card_id == {'nightmare': NIGHTMARE,
                'lifesource': LIFESOURCE, 'ordinance': ORDINANCE}[mode]
        def watch(c):
            options = [ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Fail',
                (InvokeBehavior(TEST + 'fail', c.source_id, 1),))]
            if mode == 'nightmare':
                target = c.event.target_id
                options.append(ChoiceOption('cycle', 'Original leaves and reenters', (
                    ReturnToHand(target), InvokeBehavior(TEST + 'reenter', c.source_id, 1, target))))
            if mode == 'lifesource':
                options.extend((ChoiceOption('draw', 'Remove last physical deck minion', (Draw(1, source_id=c.source_id),)),
                    ChoiceOption('insert', 'Insert physical deck minion', (AddToDeck(1, YETI, source_id=c.source_id),))))
            return (RequestChoice(1, tuple(options), c.source_id),)
        r.register_trigger_condition(TEST + 'eligible', eligible)
        r.register_behavior(TEST + 'watch', watch)
        event = {'nightmare': 'stats_changed', 'lifesource': 'card_added_to_hand', 'ordinance': 'minion_summoned'}[mode]
        r.register_card(CardDefinition(TEST + 'watch', 'Original materials witness', CardType.WEAPON,
            durability=5, metadata=META, limited_triggers=(LimitedTriggerSpec(event, TEST + 'watch',
                condition_id=TEST + 'eligible'),)))
    r.validate()
    return r


@lru_cache(maxsize=None)
def shared_registry(mode, members):
    return registry(mode, members)


class SimpleFollowupP58Tests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), deck=(YETI,) * 10,
            mode=None, members=MEMBERS, rules=None, hand_cap=None, seed=5858):
        self.config = mode, members
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
            mana=40, max_mana=40, mana_cap=40, hand_cap=hand_cap,
            weapon_card_id=TEST + 'watch' if mode else None),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(YETI,) * 10,
                mana=40, max_mana=40, mana_cap=40)), seed=seed, generation_context=CONTEXT),
            shared_registry(*self.config), ruleset=rules or Ruleset())

    def first(self, g, cid, zone='hand', player=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone)
            if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None, player=1):
        e = self.first(g, cid, player=player)
        g.apply(PlayCard(player, e.id, target_id=target, position=len(g.state.players[player].board)
            if e.kind == CardType.MINION else None))
        return e.id

    def quote(self, g, entity_id):
        state = g.state
        return quote_cost(state, g.registry, state.entities[entity_id])

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(*self.config))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(*self.config)).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(
                g.for_player(player).legal_actions()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'pool_id', 'behavior_id', 'source_json', 'cast_history'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_fourteen_complete_rows_twenty_eight_faces_sixteen_links_exact_display_and_zeros(self):
        from tools.card_batch import check_face
        data = load_batch()
        rows = {x['record']['id']: x for k in ('cards', 'existing_dependencies', 'evidence_only') for x in data[k]}
        self.assertEqual((len(rows), len(data['official_observations']), len(data['exact_parent_child_links'])), (14, 28, 16))
        faces = {(o['card_id'], o['locale']): o['face'] for o in data['official_observations']}
        for o in data['official_observations']:
            raw = rows[o['card_id']]['record']
            check_face(raw, o['face'], o['locale'], data['display_normalizations'].get(raw['id']),
                numeric_normalizations=data['numeric_normalizations'].get(raw['id']))
            self.assertEqual(canonical_digest(raw), rows[raw['id']]['record_sha256'])
        for link in data['exact_parent_child_links']:
            self.assertIn(link['dbf_id'], faces[link['parent'], link['locale']]['childIds'])
            self.assertEqual(rows[link['child']]['record']['dbf_id'], link['dbf_id'])
        self.assertEqual(data['display_normalizations'], {ORDINANCE: {'@': '', '{0}': ''}})
        self.assertIn('3', rows[ORDINANCE]['record']['text'])
        self.assertIn('（8）', rows[ORDINANCE]['record']['text'])
        for cid, values in data['numeric_normalizations'].items():
            for field, zero in values.items():
                self.assertEqual(zero, 0); self.assertIsNone(rows[cid]['record'][field])
        self.assertFalse(data['formal_pool_complete'] or data['cn_calibrated'] or data['parent_implemented'])

    def test_ten_definitions_five_roots_exact_existing_pins_and_complete_old_inventory(self):
        before, after = build_registry(), batch_registry()
        self.assertEqual(set(after.cards) - set(before.cards), set(ROOTS) - set(before.cards))
        for cid, card in before.cards.items(): self.assertEqual(after.card(cid), card)
        for cid, card in before.pool_cards.items(): self.assertEqual(after.pool_cards[cid], card)
        self.assertEqual(dict(before.pools), dict(after.pools))
        self.assertEqual(dict(before.generation_families), dict(after.generation_families))
        for cid, pin in load_batch()['existing_dependency_definition_pins'].items():
            self.assertEqual(canonical_digest(asdict(after.card(cid))), pin)
        for row in load_batch()['cards']:
            raw = row['record']; card = after.card(raw['id'])
            self.assertEqual(card.metadata, metadata_from_record(raw))
            self.assertEqual(card.cost, raw['cost'] if raw['cost'] is not None else 0)
            if card.kind == CardType.MINION:
                self.assertEqual((card.attack, card.health), (raw['attack'] if raw['attack'] is not None else 0, raw['health']))
        self.assertEqual(sum(after.card(cid).metadata.collectible for cid in ROOTS), 5)
        self.assertNotIn(PARENT, after.cards)
        self.assertEqual(tuple(load_batch()['existing_dependency_definition_pins']), EXISTING)

    def test_nightmare_permanent_growth_and_current_turn_immunity_expire_independently(self):
        g = self.game((NIGHTMARE,), board=(YETI,))
        target = self.first(g, YETI, 'board').id
        self.play(g, NIGHTMARE, target)
        e = g.state.entities[target]
        self.assertEqual((e.attack, e.max_health), (9, 10))
        self.assertIn(Keyword.IMMUNE, e.keywords)
        g.apply(EndTurn(1))
        self.assertNotIn(Keyword.IMMUNE, g.state.entities[target].keywords)
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].max_health), (9, 10))

    def test_nightmare_original_residence_wait_restore_failure_and_reentry(self):
        g = self.game((NIGHTMARE,), board=(YETI,), mode='nightmare')
        target = self.first(g, YETI, 'board').id
        self.play(g, NIGHTMARE, target)
        saved = g.snapshot(); self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g, 'cycle')
        self.assertEqual(g.state.entities[target].zone, Zone.BOARD)
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].max_health), (4, 5))
        self.assertNotIn(Keyword.IMMUNE, g.state.entities[target].keywords)
        self.portable(g)

    def test_dream_shuffles_original_physical_stolen_minion_into_owner_deck_and_resets(self):
        g = self.game((TEST + 'grow', TEST + 'give', DREAM), board=(YETI,))
        target = self.first(g, YETI, 'board').id
        self.play(g, TEST + 'grow', target); self.play(g, TEST + 'give', target)
        self.assertEqual((g.state.entities[target].owner, g.state.entities[target].controller), (1, 2))
        self.play(g, DREAM, target)
        e = g.state.entities[target]
        self.assertEqual((e.owner, e.controller, e.zone, e.attack, e.max_health, e.base_cost), (1, 1, Zone.DECK, 4, 5, 4))
        self.assertIn(target, g.state.players[1].deck)
        self.assertFalse(g.state.death_history)
        row, = g.state.deck_shuffle_history
        self.assertEqual((row.actor_id, row.player_id, row.declared_count, row.profile), (1, 1, 1, 'semantic'))
        self.portable(g)

    def test_sister_elusive_aura_follows_current_control_silence_and_death(self):
        g = self.game((TEST + 'give_sister', TEST + 'silence_sister', TEST + 'kill_sister'), board=(SISTER,))
        def hero(p): return g.state.entities[g.state.players[p].hero_id]
        self.assertIn(Keyword.ELUSIVE, hero(1).keywords)
        self.assertNotIn(Keyword.ELUSIVE, hero(2).keywords)
        self.play(g, TEST + 'give_sister')
        self.assertNotIn(Keyword.ELUSIVE, hero(1).keywords)
        self.assertIn(Keyword.ELUSIVE, hero(2).keywords)
        self.play(g, TEST + 'silence_sister')
        self.assertNotIn(Keyword.ELUSIVE, hero(2).keywords)
        self.play(g, TEST + 'kill_sister')
        self.assertNotIn(Keyword.ELUSIVE, hero(1).keywords)
        self.assertNotIn(Keyword.ELUSIVE, hero(2).keywords)

    def test_awakening_one_enemy_spell_batch_with_bonus_and_physical_exclusions(self):
        g = self.game((AWAKENING,), board=(TEST + 'power', YETI),
            enemy=(YETI, TEST + 'dormant', 'EDR_520'))
        enemy = self.first(g, YETI, 'board', 2).id
        self.play(g, AWAKENING)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 23)
        self.assertEqual(g.state.entities[enemy].zone, Zone.GRAVEYARD)
        self.assertEqual(self.first(g, YETI, 'board').health, 5)
        self.assertEqual(len(g.state.damage_history), 2)
        self.assertTrue(all(d.health_result.base_amount == 5 and d.health_result.spell_bonus == 2 for d in g.state.damage_history))
        self.assertEqual(len(g.state.players[2].board), 2)

    def test_hooktail_chest_actual_opponent_and_native_coin_fill_capacity(self):
        g = self.game((HOOKTAIL, TEST + 'kill', TEST + 'spell'), rules=Ruleset(max_hand=6))
        self.play(g, HOOKTAIL)
        chest = self.first(g, CHEST, 'board', 2)
        self.assertEqual((chest.owner, chest.controller, chest.attack, chest.max_health), (2, 2, 0, 8))
        self.play(g, TEST + 'kill', chest.id)
        self.assertEqual(len(g.state.players[1].hand), 6)
        self.assertEqual(sum(g.state.entities[i].card_id == 'GAME_005' for i in g.state.players[1].hand), 5)
        self.play(g, 'GAME_005')
        self.assertEqual(len(g.state.players[1].hand), 5)
        self.portable(g)

    def test_chest_death_controller_opponent_and_full_enemy_board_use_native_paths(self):
        g = self.game((HOOKTAIL, TEST + 'give', TEST + 'kill'), enemy_hand=(YETI,))
        self.play(g, HOOKTAIL)
        target = self.first(g, CHEST, 'board', 2).id
        self.play(g, TEST + 'give', target); self.play(g, TEST + 'kill', target)
        self.assertEqual(len(g.state.players[2].hand), 10)
        self.assertEqual(sum(g.state.entities[i].card_id == 'GAME_005' for i in g.state.players[2].hand), 9)
        self.assertFalse(g.state.players[1].hand)
        g = self.game((HOOKTAIL,), enemy=(YETI,) * 7)
        self.play(g, HOOKTAIL)
        self.assertEqual(len(g.state.players[2].board), 7)
        self.assertFalse(any(g.state.entities[i].card_id == CHEST for i in g.state.players[2].board))

    def test_ulfarr_grants_other_affectable_minions_and_uses_each_frozen_carrier_printed_cost(self):
        g = self.game((TEST + 'grow', ULFARR, TEST + 'kill', TEST + 'kill', TEST + 'kill'),
            board=(YETI, EIGHT_A, TEST + 'dormant', 'EDR_520'), members=(NEUTRAL, EIGHT_B))
        old = self.first(g, YETI, 'board').id
        self.play(g, TEST + 'grow', old)
        source = self.play(g, ULFARR)
        for i in g.state.players[1].board:
            expected = i in (old, self.first(g, EIGHT_A, 'board').id)
            granted = any(a.kind == 'deathrattle' and a.behavior_id == PREFIX + 'carrier_rattle' for a in g.state.entities[i].abilities)
            self.assertEqual(granted, expected)
        self.portable(g)
        self.play(g, TEST + 'kill', source)
        self.play(g, TEST + 'kill', old)
        self.play(g, TEST + 'kill', self.first(g, EIGHT_A, 'board').id)
        self.assertEqual(self.first(g, NEUTRAL, 'board').card_id, NEUTRAL)
        self.assertEqual(self.first(g, EIGHT_B, 'board').card_id, EIGHT_B)
        captures = [x.capture.card_id for x in g.state.deathrattle_history if x.capture.ability.behavior_id == PREFIX + 'carrier_rattle']
        self.assertEqual(captures, [YETI, EIGHT_A])

    def test_lifesource_two_real_discoveries_current_class_plus_neutral_then_current_hand_discount(self):
        g = self.game((LIFESOURCE, YETI, TEST + 'spell'), deck=(TEST + 'spell',) * 4,
            members=(NEUTRAL, MAGE, WARRIOR))
        self.play(g, LIFESOURCE)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {NEUTRAL, MAGE})
        self.portable(g)
        self.choose(g, next(o.id for o in g.state.pending_choice.options if o.card_id == MAGE))
        self.assertIsNotNone(g.state.pending_choice)
        self.choose(g, next(o.id for o in g.state.pending_choice.options if o.card_id == NEUTRAL))
        self.assertTrue(all(self.quote(g, self.first(g, cid).id).amount == 2 for cid in (YETI, MAGE, NEUTRAL)))
        self.assertEqual(self.quote(g, self.first(g, TEST + 'spell').id).amount, 0)

    def test_lifesource_checks_physical_deck_after_discovery_reactions(self):
        for action, deck, expected in (('draw', (YETI,), 2), ('insert', (TEST + 'spell',), 4)):
            g = self.game((LIFESOURCE,), deck=deck, mode='lifesource', members=(NEUTRAL,))
            self.play(g, LIFESOURCE); self.choose(g, g.state.pending_choice.options[0].id)
            self.assertEqual(g.state.pending_choice.options[0].id, 'ok')
            self.portable(g)
            self.choose(g, action)
            self.choose(g, g.state.pending_choice.options[0].id)
            self.assertIsNone(g.state.pending_choice)
            self.assertEqual(self.quote(g, self.first(g, NEUTRAL).id).amount, expected)

    def test_striker_original_submitted_dragon_or_all_upgrades_same_physical_hand_card(self):
        for dragon in (DRAGON, ALL_RACE):
            g = self.game((STRIKER, dragon))
            original = self.first(g, STRIKER).id
            self.play(g, dragon)
            e = g.state.entities[original]
            self.assertEqual((e.card_id, e.attack, e.max_health, e.zone), ('CATA_551t', 6, 6, Zone.HAND))
            self.assertNotIn('CATA_551t', json.dumps(g.for_player(2).observe()))
            if dragon == DRAGON: self.portable(g)
        g = self.game((STRIKER, TEST + 'summon_dragon'))
        self.play(g, TEST + 'summon_dragon')
        self.assertEqual(self.first(g, STRIKER).card_id, STRIKER)

    def test_ordinance_three_other_completed_casts_produce_two_independent_random_entries(self):
        for previous, expected in ((0, 1), (2, 1), (3, 2)):
            g = self.game((*((TEST + 'spell',) * previous), ORDINANCE), members=(EIGHT_A, EIGHT_B))
            for _ in range(previous): self.play(g, TEST + 'spell')
            self.play(g, ORDINANCE)
            self.assertEqual(len(g.state.players[1].board), expected)
            root, = g.state.pool_summon_history
            self.assertEqual((root.spec.count, len(root.selected), len(root.entry_root_ids)), (expected,) * 3)
            self.assertTrue(root.spec.replacement)
            self.assertEqual([m.weight for m in root.spec.basis.candidates], [1, 1])
            local = random.Random(); local.setstate(root.rng_before)
            selected = tuple(root.spec.basis.candidates[local.randrange(2)].card_id for _ in range(expected))
            self.assertEqual((root.selected, root.rng_after), (selected, local.getstate()))
            self.assertTrue(all(g.state.entities[i].card_id in (EIGHT_A, EIGHT_B) for i in g.state.players[1].board))

    def test_ordinance_counts_actual_effect_casts_but_excludes_old_turn_and_opponent(self):
        g = self.game((TEST + 'auto', ORDINANCE), members=(EIGHT_A, TEST + 'spell'))
        self.play(g, TEST + 'auto')
        self.assertEqual((len(g.state.cast_history), len(g.state.play_history)), (4, 1))
        self.play(g, ORDINANCE)
        self.assertEqual(len(g.state.players[1].board), 2)
        g = self.game((*((TEST + 'spell',) * 3), ORDINANCE), enemy_hand=(TEST + 'spell',) * 3, members=(EIGHT_A,))
        for _ in range(3): self.play(g, TEST + 'spell')
        g.apply(EndTurn(1))
        for _ in range(3): self.play(g, TEST + 'spell', player=2)
        g.apply(EndTurn(2)); self.play(g, ORDINANCE)
        self.assertEqual(len(g.state.players[1].board), 1)

    def test_ordinance_original_batch_waiting_restore_failure_and_native_prepare(self):
        g = self.game((*((TEST + 'spell',) * 3), ORDINANCE), mode='ordinance', members=(EIGHT_A, EIGHT_B))
        for _ in range(3): self.play(g, TEST + 'spell')
        self.play(g, ORDINANCE)
        self.assertEqual(len(g.state.players[1].board), 1)
        saved = g.snapshot(); self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g)
        self.assertEqual(len(g.state.players[1].board), 2)
        g = self.game((ORDINANCE,), members=(EIGHT_A,))
        source = self.first(g, ORDINANCE).id
        g.apply(UseHandAction(1, source, 'prepare'))
        self.assertFalse(g.state.cast_history)
        with self.assertRaises(IllegalAction): self.play(g, ORDINANCE)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g, ORDINANCE)
        self.assertEqual(len(g.state.players[1].board), 1)

    def test_unknown_qualified_eight_fails_before_rng_even_full_board_and_rolls_back(self):
        g = self.game((ORDINANCE,), board=(YETI,) * 7, members=(EIGHT_A, UNKNOWN))
        saved, calls = g.snapshot(), []; original = random.Random.randrange
        def spy(rng, *args, **kwargs):
            calls.append(args); return original(rng, *args, **kwargs)
        with patch.object(random.Random, 'randrange', spy), self.assertRaises(ResolutionError): self.play(g, ORDINANCE)
        self.assertEqual(g.snapshot(), saved)
        self.assertFalse(calls)


if __name__ == '__main__':
    unittest.main()
