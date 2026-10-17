"""Grouped original materials, fresh continuations and location all-Mana casts."""
from functools import lru_cache
import json
import random
import unittest
from unittest.mock import patch

from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p55_cards import (DISCOVER, DISCOUNT, SET, SUMMON,
    BURST, SWEEP, WEAPON, SCOUT, TYRANT, DRAKE, SHRINE, ROOTS, PARENTS,
    POOL_ID, load_batch, register_simple_followup_p55_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice,
    TargetSpec, UseLocation, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (ChoiceOption, Damage, GainArmor, GainTemporaryMana,
    InvokeBehavior, RequestChoice, ReturnToHand, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.locations import RefreshLocation
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import (GenerationContext, PoolCard, PoolDefinition, PoolMember,
    PoolQuery, SummonFromPool)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.targets import canonical_digest

TEST = 'p55.test.'
YETI = 'CORE_CS2_182'
STONE = 'TLC_467'
THALNOS = 'CORE_EX1_012'
AXE = 'CS2_106'
SPELL0, SPELL4 = TEST + 'spell0', TEST + 'spell4'
UNKNOWN_SPELL, UNKNOWN_MINION = TEST + 'unsupported_spell4', TEST + 'unsupported_deathrattle'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
MEMBERS = (STONE, THALNOS, YETI, SPELL0, SPELL4)
CONTEXT = GenerationContext('p55-complete-explicit-fixture', 'experimental')


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata', lambda r: None):
        r = build_registry()
    present = tuple(cid in r.cards for cid in ROOTS)
    if not any(present):
        register_simple_followup_p55_cards(r)
    elif not all(present):
        raise AssertionError('P55 assembly must contain the complete ten accepted definitions')
    register_candidate_pool_metadata(r)
    r.validate()
    return r


def registry(mode=None, members=MEMBERS):
    r = batch_registry()
    for cid, cost in ((SPELL0, 0), (SPELL4, 4)):
        r.register_behavior(cid, lambda c: (GainArmor(c.player_id, 1),))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=cost, on_play=cid,
            metadata=CardMetadata(True, (CardClass.NEUTRAL,), None, tribes=())))
    r.register_card(CardDefinition(TEST + 'power', 'Ordinary Spell Damage', CardType.MINION,
        health=20, spell_damage=5, metadata=META))
    r.register_card(CardDefinition(TEST + 'new', 'Later friendly character', CardType.MINION,
        attack=2, health=4, metadata=META))
    r.register_behavior(TEST + 'death', lambda c: (Summon(1, TEST + 'new'),
        Damage(c.state.players[1].hero_id, 5, c.source_id)))
    r.register_card(CardDefinition(TEST + 'death', 'Enemy death reaction', CardType.MINION,
        attack=1, health=2, deathrattle=TEST + 'death', metadata=META))
    r.register_card(CardDefinition(TEST + 'dormant', 'Physical dormant occupancy', CardType.MINION,
        attack=1, health=9, dormant_turns=2, metadata=META))

    def pool_gap(c):
        return (SummonFromPool(c.player_id, POOL_ID,
            PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=6, max_cost=6),
            source_id=c.source_id, cause=SummonCause.capture(c), entry_keywords=(Keyword.TAUNT, Keyword.LIFESTEAL)),)

    scripts = dict(
        kill=lambda c: (),
        hand_back=lambda c: (MoveCard(CardReference.capture(c.state.entities[c.target_id]), 1, Zone.HAND, source_id=c.source_id),),
        reenter=lambda c: (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),
            c.state.entities[c.target_id].controller, cause=SummonCause.capture(c)),),
        refresh=lambda c: tuple(RefreshLocation(i, c.source_id) for i in c.state.players[1].board
            if c.state.entities[i].card_id == SHRINE),
        fail=lambda c: (_ for _ in ()).throw(ResolutionError('P55 deliberate continuation failure')),
        pool_gap=pool_gap)
    for name, body in scripts.items():
        r.register_behavior(TEST + name, body)
        r.register_card(CardDefinition(TEST + name, name, CardType.SPELL, on_play=TEST + name, metadata=META))
    r.register_pool_card(PoolCard(UNKNOWN_SPELL, CardType.SPELL, 4,
        CardMetadata(True, (CardClass.NEUTRAL,), None, tribes=()), battlecry=False, deathrattle=False, choose_one=False))
    r.register_pool_card(PoolCard(UNKNOWN_MINION, CardType.MINION, 5,
        CardMetadata(True, (CardClass.NEUTRAL,), None, tribes=()), battlecry=False, deathrattle=True, choose_one=False))
    for cid in members:
        if cid not in r.pool_cards:
            r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID, 'p55-complete-explicit-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode:
        def eligible(c):
            if mode == 'sweep':
                return c.state.entities[c.event.target_id].card_id == TEST + 'death'
            source = c.state.entities.get(c.event.source_id)
            return source is not None and source.card_id == {
                'discount': DISCOUNT, 'set': SET, 'burst': BURST, 'shrine': SHRINE}[mode]

        def watch(c):
            options = [ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Fail',
                (InvokeBehavior(TEST + 'fail', c.source_id, 1),))]
            if mode == 'set':
                target = c.state.players[2].board[1]
                options.append(ChoiceOption('cycle', 'Reenter original second enemy',
                    (ReturnToHand(target), InvokeBehavior(TEST + 'reenter', c.source_id, 1, target))))
            if mode == 'discount':
                target = next(i for i in c.state.players[1].hand if c.state.entities[i].card_id == TYRANT)
                options.append(ChoiceOption('cycle', 'Leave and reenter original hand slot', (
                    MoveCard(CardReference.capture(c.state.entities[target]), 1, Zone.DECK, position='top', source_id=c.source_id),
                    InvokeBehavior(TEST + 'hand_back', c.source_id, 1, target))))
            if mode == 'burst':
                options.append(ChoiceOption('spawn', 'New current enemy', (Summon(2, TEST + 'new'),)))
            if mode == 'shrine':
                options.append(ChoiceOption('gain', 'Add later temporary Mana', (GainTemporaryMana(1, 3),)))
            return (RequestChoice(1, tuple(options), c.source_id),)

        event = {'discount': 'cost_modified', 'set': 'stats_changed', 'burst': 'stats_changed',
                 'sweep': 'minion_died', 'shrine': 'mana_consumption_resolved'}[mode]
        r.register_behavior(TEST + 'watch', watch)
        r.register_trigger_condition(TEST + 'eligible', eligible)
        r.register_card(CardDefinition(TEST + 'watch', 'Original continuation witness', CardType.WEAPON,
            durability=5, metadata=META, limited_triggers=(LimitedTriggerSpec(event, TEST + 'watch', condition_id=TEST + 'eligible'),)))
    r.validate()
    return r


@lru_cache(maxsize=None)
def shared_registry(mode, members):
    return registry(mode, members)


class SimpleFollowupP55Tests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), deck=(YETI,) * 12, mode=None, members=MEMBERS, mana=30):
        self.config = (mode, members)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
            mana=mana, max_mana=30, mana_cap=30, weapon_card_id=TEST + 'watch' if mode else None),
            PlayerSetup('HERO_08', board=enemy, deck=(YETI,) * 12, mana=30, max_mana=30,
                mana_cap=30)), seed=5555, generation_context=CONTEXT), shared_registry(*self.config))

    def first(self, g, cid, zone='hand', player=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone)
                    if g.state.entities[i].card_id == cid)

    def play(self, g, cid):
        entity = self.first(g, cid)
        g.apply(PlayCard(1, entity.id, position=len(g.state.players[1].board)
                         if entity.kind in (CardType.MINION, CardType.LOCATION) else None))
        return entity.id

    def choose(self, g, key='ok'):
        g.apply(SelectChoice(1, g.state.pending_choice.id, (key,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(*self.config))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(*self.config)).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(
                g.for_player(player).legal_actions()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'pool_id', 'behavior_id', 'source_json', 'mana_consumption_history'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_fifteen_full_rows_thirty_faces_twenty_links_and_parent_only_zero_are_preserved(self):
        from tools.card_batch import check_face
        data = load_batch()
        rows = {x['record']['id']: x for k in ('cards', 'skipped', 'evidence_only') for x in data[k]}
        self.assertEqual(len(rows), 15)
        self.assertEqual(len(data['official_observations']), 30)
        faces = {(o['card_id'], o['locale']): o['face'] for o in data['official_observations']}
        for o in data['official_observations']:
            raw = rows[o['card_id']]['record']
            check_face(raw, o['face'], o['locale'], numeric_normalizations=data['numeric_normalizations'].get(raw['id']))
            self.assertEqual(canonical_digest(raw), rows[raw['id']]['record_sha256'])
        self.assertEqual(len(data['exact_parent_child_links']), 20)
        for link in data['exact_parent_child_links']:
            self.assertIn(link['dbf_id'], faces[link['parent'], link['locale']]['childIds'])
            self.assertEqual(rows[link['child']]['record']['dbf_id'], link['dbf_id'])
        self.assertEqual(data['numeric_normalizations'], {'CS3_002': {'cost': 0}})
        self.assertIsNone(rows['CS3_002']['record']['cost'])
        self.assertNotIn('COST', rows['CS3_002']['record']['tags'])
        self.assertFalse(data['parents_implemented'] or data['formal_pool_complete'] or data['cn_calibrated'])

    def test_ten_new_complete_definitions_location_durability_tokens_and_all_old_data_are_unchanged(self):
        before, after = build_registry(), batch_registry()
        self.assertEqual(set(after.cards) - set(before.cards), set(ROOTS) - set(before.cards))
        for cid, card in before.cards.items():
            self.assertEqual(after.card(cid), card)
        for cid, card in before.pool_cards.items():
            self.assertEqual(after.pool_cards[cid], card)
        self.assertEqual(dict(before.pools), dict(after.pools))
        self.assertEqual(dict(before.generation_families), dict(after.generation_families))
        for row in load_batch()['cards']:
            raw = row['record'];card = after.card(raw['id'])
            self.assertEqual((card.cost, card.metadata), (raw['cost'], metadata_from_record(raw)))
            if card.kind == CardType.MINION:
                self.assertEqual((card.attack, card.health), (raw['attack'], raw['health']))
                self.assertFalse(card.keywords or card.activated_abilities)
        shrine = after.card(SHRINE)
        self.assertEqual((shrine.kind, shrine.health, shrine.durability), (CardType.LOCATION, 0, 3))
        self.assertTrue(shrine.on_use)
        for cid in (SCOUT, TYRANT, DRAKE):
            self.assertIsNone(after.card(cid).battlecry)
        self.assertEqual(after.card(SCOUT).metadata.tribes, ('murloc',))
        self.assertEqual(after.card(TYRANT).metadata.tribes, ('demon',))
        self.assertEqual(after.card(DRAKE).metadata.tribes, ('dragon',))
        for cid in (*PARENTS, SUMMON):
            self.assertEqual(cid in before.cards, cid in after.cards)
        from hs_sim.engine.representative import build_registry as default
        self.assertEqual(default().fingerprint(), DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_discover_real_selected_deathrattle_creation_has_minus_three_cost_and_portable_choice(self):
        for cid in (STONE, THALNOS):
            with self.subTest(cid=cid):
                g = self.game((DISCOVER,))
                self.play(g, DISCOVER)
                self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {STONE, THALNOS})
                other = self.portable(g) if cid == STONE else None
                key = next(o.id for o in g.state.pending_choice.options if o.card_id == cid)
                self.choose(g, key)
                if other is not None:
                    self.choose(other, key);self.assertEqual(g.snapshot(), other.snapshot())
                card = self.first(g, cid)
                self.assertEqual(quote_unselected_cost(g.state, g.registry, card).amount, max(0, g.registry.card(cid).cost - 3))
                self.assertEqual(g.state.players[1].mana, 24)

    def test_hand_discount_original_current_minion_group_skips_reentered_same_id_and_non_minions(self):
        g = self.game((DISCOUNT, SCOUT, TYRANT, SPELL4), mode='discount')
        target = self.first(g, TYRANT)
        self.play(g, DISCOUNT)
        other, saved = self.portable(g), g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game, 'cycle')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(quote_unselected_cost(g.state, g.registry, self.first(g, SCOUT)).amount, 0)
        self.assertEqual(quote_unselected_cost(g.state, g.registry, g.state.entities[target.id]).amount, 5)
        self.assertEqual(quote_unselected_cost(g.state, g.registry, self.first(g, SPELL4)).amount, 4)

    def test_enemy_set_two_two_original_residences_exclude_dormant_friend_and_reentered_second(self):
        g = self.game((SET,), board=(YETI,), enemy=(YETI, YETI, TEST + 'dormant'), mode='set')
        first, second = (g.state.entities[i] for i in g.state.players[2].board[:2])
        self.play(g, SET)
        other = self.portable(g)
        for game in (g, other):
            self.choose(game, 'cycle')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual((g.state.entities[first.id].attack, g.state.entities[first.id].health), (2, 2))
        self.assertEqual((g.state.entities[second.id].attack, g.state.entities[second.id].health), (4, 5))
        self.assertNotEqual(g.state.entities[second.id].board_presence_id, second.board_presence_id)
        self.assertEqual(self.first(g, TEST + 'dormant', 'board', 2).health, 9)
        self.assertEqual(self.first(g, YETI, 'board').attack, 4)

    def test_burst_self_buff_then_fresh_random_enemy_pool_wait_restore_and_no_spell_bonus(self):
        g = self.game((BURST,), board=(TEST + 'power',), mode='burst')
        source = self.play(g, BURST)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (8, 7))
        other, saved = self.portable(g), g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game, 'spawn')
        self.assertEqual(g.snapshot(), other.snapshot())
        new, = [e for e in g.state.entities.values() if e.card_id == TEST + 'new' and e.controller == 2]
        choice = next(e for e in g.events if e.kind == 'random_choice' and e.source_id == source)
        self.assertIn(new.id, dict(choice.data)['candidates'])
        result = g.state.damage_history[-1].health_result
        self.assertEqual((result.base_amount, result.spell_bonus, result.damage_kind), (4, 0, 'minion_ability'))

    def test_sweep_damage_and_deaths_complete_before_fresh_current_friendly_heal_batch(self):
        g = self.game((SWEEP,), board=(TEST + 'power',), enemy=(TEST + 'death',), mode='sweep')
        self.play(g, SWEEP)
        self.assertFalse(g.state.healing_history)
        other, saved = self.portable(g), g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        new = self.first(g, TEST + 'new', 'board')
        restored = {row.health_result.target_id for row in g.state.healing_history}
        self.assertIn(new.id, restored)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 30)
        damage = [row.health_result for row in g.state.damage_history if row.health_result.source_card_id == SWEEP]
        self.assertTrue(all((v.base_amount, v.spell_bonus, v.damage_kind) == (3, 0, 'minion_ability') for v in damage))
        self.assertTrue(all(row.health_result.base_amount == 6 for row in g.state.healing_history))

    def test_weapon_buff_then_physical_filtered_draw_empty_skip_and_vanilla_bodies(self):
        for deck in ((YETI, AXE), (YETI,), ()):
            with self.subTest(deck=deck):
                g = self.game((WEAPON,), deck=deck)
                originals = set(g.state.players[1].deck)
                source = self.play(g, WEAPON)
                self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (8, 8))
                self.assertEqual(g.state.players[1].fatigue, 0)
                if AXE in deck:
                    self.assertIn(self.first(g, AXE).id, originals)
                else:
                    self.assertFalse(g.state.players[1].hand)
        for cid, expected in ((SCOUT, (1, 1)), (TYRANT, (5, 5)), (DRAKE, (14, 12))):
            g = self.game((cid,));source = self.play(g, cid)
            self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), expected)

    def test_shrine_real_location_play_zero_and_nonzero_all_mana_exact_cost_without_extra_payment(self):
        for mana, spell in ((0, SPELL0), (4, SPELL4)):
            with self.subTest(mana=mana):
                g = self.game(board=(SHRINE,), mana=mana)
                source = self.first(g, SHRINE, 'board').id
                g.apply(UseLocation(1, source))
                row, = g.state.mana_consumption_history
                self.assertEqual((row.actual, row.requested, row.source_id, row.source_kind), (mana, None, source, CardType.LOCATION))
                cast, = g.state.cast_history
                self.assertEqual((cast.card_id, cast.origin, cast.player_id), (spell, 'effect', 1))
                self.assertEqual(g.state.players[1].mana, 0)
                self.assertEqual((g.state.entities[source].durability, g.state.entities[source].location_cooldown), (2, 2))
                self.assertFalse(g.state.play_history)
        g = self.game((SHRINE,), mana=5)
        source = self.play(g, SHRINE)
        self.assertEqual((g.state.players[1].mana, g.state.entities[source].durability), (4, 3))
        g.apply(UseLocation(1, source));self.assertEqual(g.state.mana_consumption_history[0].actual, 4)

    def test_shrine_original_mana_result_wait_restore_failure_ignores_later_balance_change(self):
        g = self.game(board=(SHRINE,), mana=4, mode='shrine')
        source = self.first(g, SHRINE, 'board').id
        g.apply(UseLocation(1, source))
        self.assertFalse(g.state.cast_history)
        other, saved = self.portable(g), g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.choose(game, 'gain')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual((g.state.players[1].mana, len(g.state.mana_consumption_history)), (3, 1))
        self.assertEqual(g.state.cast_history[0].card_id, SPELL4)
        self.assertEqual(g.state.entities[source].durability, 2)

    def test_shrine_cooldown_and_last_durability_retirement_keep_accepted_zero_mana_cast(self):
        g = self.game((TEST + 'refresh', TEST + 'refresh'), board=(SHRINE,), mana=0)
        source = self.first(g, SHRINE, 'board').id
        g.apply(UseLocation(1, source));saved = g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(UseLocation(1, source))
        self.assertEqual(g.snapshot(), saved)
        for _ in range(2):
            self.play(g, TEST + 'refresh');g.apply(UseLocation(1, source))
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.cast_history), 5)
        self.assertEqual(sum(row.card_id == SPELL0 for row in g.state.cast_history), 3)
        self.assertEqual(len(g.state.mana_consumption_history), 3)
        self.portable(g)

    def test_unknown_full_discovery_or_exact_spell_pool_errors_before_rng_and_restores_outer_action(self):
        for shrine in (False, True):
            with self.subTest(shrine=shrine):
                g = self.game(() if shrine else (DISCOVER,), board=(SHRINE,) if shrine else (),
                    mana=4 if shrine else 30, members=(SPELL4, UNKNOWN_SPELL) if shrine else (STONE, UNKNOWN_MINION))
                saved, calls = g.snapshot(), []
                original = random.Random.randrange
                def spy(rng, *args, **kwargs):
                    calls.append(args);return original(rng, *args, **kwargs)
                with patch.object(random.Random, 'randrange', autospec=True, side_effect=spy):
                    with self.assertRaises(ResolutionError):
                        if shrine:g.apply(UseLocation(1, self.first(g, SHRINE, 'board').id))
                        else:self.play(g, DISCOVER)
                self.assertFalse(calls)
                self.assertEqual(g.snapshot(), saved)

    def test_historical_pool_entry_gap_is_now_satisfied_by_original_preentry_recipe(self):
        SummonEntryMaterial(YETI, keywords=(Keyword.TAUNT, Keyword.LIFESTEAL)).__post_init__()
        g = self.game((TEST + 'pool_gap',))
        self.play(g, TEST + 'pool_gap')
        root = g.state.card_summon_history[-1]
        self.assertEqual(root.request.pool_basis.entry_keywords, (Keyword.TAUNT, Keyword.LIFESTEAL))
        self.assertTrue(all(m.keywords == (Keyword.TAUNT, Keyword.LIFESTEAL) for m in root.request.materials))
        self.assertIsNotNone(g.registry.card(SUMMON).battlecry)
        self.assertEqual(load_batch()['skipped'][0]['record']['id'], SUMMON)


if __name__ == '__main__':
    unittest.main()
