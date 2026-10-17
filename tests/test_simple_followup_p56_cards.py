"""Original physical choices, actual death/resource facts and native openings."""
from functools import lru_cache
import json
import random
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p56_cards import (DEJA, FATE, YSONDRE, MADNESS,
    RITE, FARM, TWO, ALL, IMPROVISER, HOGGER, ROOTS, PARENT, POOL_ID,
    load_batch, register_simple_followup_p56_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    DeckPolicy, DeckSpec, EndTurn, Game, Keyword, MatchSetup, PlayCard,
    PlayerSetup, Rarity, Resource, Scenario, SelectChoice, TargetSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (Buff, ChoiceOption, CostSpec, Destroy, GainArmor,
    GainResource, InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import LimitedTriggerSpec, SpellSchool
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.targets import canonical_digest

TEST = 'p56.test.'
YETI = 'CORE_CS2_182'
COUNTER = 'CORE_EX1_287'
DRAGON, ALL_RACE, UNDEAD = (TEST + n for n in ('dragon', 'all', 'undead'))
ZERO, THREE, EIGHT = (TEST + str(n) for n in (0, 3, 8))
UNKNOWN, UNKNOWN_SECRET = TEST + 'unknown3', TEST + 'unknown_secret'
LEGENDS = tuple(TEST + 'legend_' + n for n in ('spell', 'minion', 'weapon'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
MEMBERS = (DRAGON, ALL_RACE, UNDEAD, ZERO, THREE, EIGHT, COUNTER)
CONTEXT = GenerationContext('p56-complete-explicit-fixture', 'experimental')


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata', lambda r: None):
        r = build_registry()
    present = tuple(cid in r.cards for cid in ROOTS)
    if not any(present):
        register_simple_followup_p56_cards(r)
    elif not all(present):
        raise AssertionError('P56 assembly must contain all ten complete definitions')
    register_candidate_pool_metadata(r)
    r.validate()
    return r


def registry(mode=None, members=MEMBERS):
    r = batch_registry()
    for cid, cost, tribes in ((DRAGON, 4, ('dragon',)), (ALL_RACE, 5, ('all',)),
            (UNDEAD, 2, ('undead',)), (ZERO, 0, ()), (THREE, 3, ()), (EIGHT, 8, ())):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=2,
            health=6, metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=tribes)))
    for name, keywords, dormant in (('stealth', (Keyword.STEALTH,), 0),
            ('elusive', (Keyword.ELUSIVE,), 0), ('dormant', (), 2)):
        r.register_card(CardDefinition(TEST + name, name, CardType.MINION, attack=1,
            health=5, keywords=keywords, dormant_turns=dormant, metadata=META))
    for cid, kind in zip(LEGENDS, (CardType.SPELL, CardType.MINION, CardType.WEAPON)):
        r.register_card(CardDefinition(cid, cid, kind, cost=2,
            attack=2 if kind != CardType.SPELL else 0, health=5 if kind == CardType.MINION else 0,
            durability=3 if kind == CardType.WEAPON else 0,
            metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.LEGENDARY, tribes=())))
    scripts = {
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'buff': lambda c: (Buff(c.target_id, 3, 4, c.source_id),
            ModifyCost(c.target_id, CostSpec(delta=-1), c.source_id)),
        'spell': lambda c: (GainArmor(c.player_id, 1),),
        'grow_hand': lambda c: tuple(effect for i in c.state.players[2].hand
            for effect in (BuffStoredCard(CardReference.capture(c.state.entities[i]), 3, 4, c.source_id), ModifyCost(i, CostSpec(delta=-1), c.source_id))),
        'cycle': lambda c: (ReturnToHand(c.target_id), InvokeBehavior(TEST + 'reenter', c.source_id, 1, c.target_id)),
        'reenter': lambda c: (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]), 2,
            cause=SummonCause.capture(c)),),
        'bury': lambda c: (MoveCard(CardReference.capture(c.state.entities[c.target_id]), 2, Zone.DECK,
            source_id=c.source_id),),
        'fail': lambda c: (_ for _ in ()).throw(ResolutionError('P56 deliberate continuation failure')),
    }
    for name, body in scripts.items():
        r.register_behavior(TEST + name, body)
        r.register_card(CardDefinition(TEST + name, name, CardType.SPELL, on_play=TEST + name,
            targeting=TargetSpec() if name in ('kill', 'buff') else None, metadata=META))
    r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 3,
        CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=('dragon',)),
        battlecry=False, deathrattle=False, choose_one=False))
    r.register_pool_card(PoolCard(UNKNOWN_SECRET, CardType.SPELL, 3,
        CardMetadata(True, (CardClass.MAGE,), Rarity.COMMON, tribes=()), keywords=(Keyword.SECRET,),
        battlecry=False, deathrattle=False, choose_one=False))
    for cid in members:
        if cid not in r.pool_cards:
            r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID, 'p56-complete-explicit-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode:
        def eligible(c):
            source = c.state.entities.get(c.event.source_id)
            return source is not None and source.card_id == {'farm': FARM, 'two': TWO, 'deja': DEJA}[mode]

        def watch(c):
            options = [ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Fail',
                (InvokeBehavior(TEST + 'fail', c.source_id, 1),))]
            if mode == 'farm':
                options.append(ChoiceOption('gain', 'Later corpses', (GainResource(1, Resource.CORPSES, 5),)))
            elif mode == 'deja':
                target = c.state.players[2].hand[0]
                options.append(ChoiceOption('bury', 'Original leaves hand',
                    (InvokeBehavior(TEST + 'bury', c.source_id, 1, target),)))
            else:
                selected = dict(c.event.data)['option_ids']
                target = json.loads(selected[0])['entity_id']
                options.append(ChoiceOption('cycle', 'Reenter selected original',
                    (InvokeBehavior(TEST + 'cycle', c.source_id, 1, target),)))
            return (RequestChoice(1, tuple(options), c.source_id),)
        r.register_behavior(TEST + 'watch', watch)
        r.register_trigger_condition(TEST + 'eligible', eligible)
        r.register_card(CardDefinition(TEST + 'watch', 'Original acceptance witness', CardType.WEAPON,
            durability=5, metadata=META, limited_triggers=(LimitedTriggerSpec(
                'resource_spent' if mode == 'farm' else 'choice_selected', TEST + 'watch',
                condition_id=TEST + 'eligible'),)))
    r.validate()
    return r


@lru_cache(maxsize=None)
def shared_registry(mode, members):
    return registry(mode, members)


class SimpleFollowupP56Tests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), deck=(YETI,) * 8,
            enemy_deck=(YETI,) * 8, corpses=0, mode=None, members=MEMBERS):
        self.config = mode, members
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board,
            deck=deck, mana=40, max_mana=40, mana_cap=40, corpses=corpses,
            weapon_card_id=TEST + 'watch' if mode else None),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=enemy_deck,
                mana=40, max_mana=40, mana_cap=40)), seed=5656, generation_context=CONTEXT),
            shared_registry(*self.config))

    def first(self, g, cid, zone='hand', player=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone)
            if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None, player=1):
        e = self.first(g, cid, player=player)
        g.apply(PlayCard(player, e.id, target_id=target, position=len(g.state.players[player].board)
            if e.kind == CardType.MINION else None))
        return e.id

    def choose(self, g, ids=None):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, tuple(ids) if ids is not None else (q.options[0].id,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(*self.config))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(*self.config)).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(
                g.for_player(player).legal_actions()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'pool_id', 'behavior_id', 'source_json', 'death_history'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_eleven_complete_rows_twenty_two_faces_four_exact_links(self):
        from tools.card_batch import check_face
        data = load_batch()
        rows = {x['record']['id']: x for k in ('cards', 'evidence_only') for x in data[k]}
        self.assertEqual((len(rows), len(data['official_observations']), len(data['exact_parent_child_links'])), (11, 22, 4))
        faces = {(o['card_id'], o['locale']): o['face'] for o in data['official_observations']}
        for o in data['official_observations']:
            raw = rows[o['card_id']]['record']
            check_face(raw, o['face'], o['locale'])
            self.assertEqual(canonical_digest(raw), rows[raw['id']]['record_sha256'])
        for link in data['exact_parent_child_links']:
            self.assertIn(link['dbf_id'], faces[link['parent'], link['locale']]['childIds'])
            self.assertEqual(rows[link['child']]['record']['dbf_id'], link['dbf_id'])
        self.assertFalse(data['formal_pool_complete'] or data['cn_calibrated'])
        self.assertEqual(data['numeric_normalizations'], {})

    def test_ten_definitions_eight_collectible_and_all_old_definitions_pools_unchanged(self):
        before, after = build_registry(), batch_registry()
        self.assertEqual(set(after.cards) - set(before.cards), set(ROOTS) - set(before.cards))
        for cid, card in before.cards.items():
            self.assertEqual(after.card(cid), card)
        for cid, card in before.pool_cards.items():
            self.assertEqual(after.pool_cards[cid], card)
        self.assertEqual(dict(before.pools), dict(after.pools))
        self.assertEqual(dict(before.generation_families), dict(after.generation_families))
        for row in load_batch()['cards']:
            raw = row['record']; card = after.card(raw['id'])
            self.assertEqual((card.cost, card.metadata), (raw['cost'], metadata_from_record(raw)))
            if card.kind == CardType.MINION:
                self.assertEqual((card.attack, card.health), (raw['attack'], raw['health']))
        self.assertEqual(sum(after.card(cid).metadata.collectible for cid in ROOTS), 8)
        self.assertEqual(after.card(RITE).spell_school, SpellSchool.SHADOW)
        self.assertEqual(after.card(IMPROVISER).hand_actions[0].cost, 1)
        self.assertNotIn(PARENT, after.cards)

    def test_deja_distinct_faces_preserves_physical_hand_and_current_material(self):
        g = self.game((TEST + 'grow_hand', DEJA), enemy_hand=(DRAGON, DRAGON))
        self.play(g, TEST + 'grow_hand')
        old = tuple(g.state.players[2].hand)
        source = self.play(g, DEJA)
        self.assertEqual(len(g.state.pending_choice.options), 1)
        self.portable(g)
        self.choose(g)
        new = self.first(g, DRAGON)
        self.assertEqual(tuple(g.state.players[2].hand), old)
        self.assertNotIn(new.id, old)
        self.assertEqual((new.owner, new.controller, new.zone), (1, 1, Zone.HAND))
        self.assertEqual((new.attack, new.max_health, new.cost), (5, 10, 3))
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.portable(g)

    def test_deja_reveals_only_offered_faces(self):
        g = self.game((DEJA,), enemy_hand=(DRAGON, UNDEAD, ZERO, THREE, EIGHT))
        self.play(g, DEJA)
        offered = {o.card_id for o in g.state.pending_choice.options}
        self.assertEqual(len(offered), 3)
        visible = json.dumps(g.for_player(1).observe()) + json.dumps(g.player_events(1))
        for cid in {DRAGON, UNDEAD, ZERO, THREE, EIGHT} - offered:
            self.assertNotIn(cid, visible)
        self.portable(g)

    def test_deja_original_physical_residence_is_not_followed_into_deck(self):
        g = self.game((DEJA,), enemy_hand=(DRAGON,), mode='deja')
        original = g.state.players[2].hand[0]
        self.play(g, DEJA)
        self.choose(g)
        self.portable(g)
        self.choose(g, ('bury',))
        self.assertEqual(g.state.entities[original].zone, Zone.DECK)
        self.assertFalse(g.state.players[1].hand)
        self.portable(g)

    def test_fate_two_separate_physical_discoveries_restore_and_empty_first(self):
        g = self.game((FATE,), deck=(DRAGON, DRAGON), enemy_deck=(UNDEAD,))
        decks = tuple(tuple(g.state.players[p].deck) for p in (1, 2))
        self.play(g, FATE)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options], [DRAGON])
        self.portable(g)
        self.choose(g)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options], [UNDEAD])
        self.portable(g)
        self.choose(g)
        self.assertEqual(tuple(tuple(g.state.players[p].deck) for p in (1, 2)), decks)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [DRAGON, UNDEAD])
        g = self.game((FATE,), deck=(), enemy_deck=(UNDEAD,))
        self.play(g, FATE)
        self.assertEqual(g.state.pending_choice.options[0].card_id, UNDEAD)
        self.choose(g)

    def test_ysondre_counts_current_actual_death_and_later_second_death(self):
        g = self.game((TEST + 'kill', MADNESS, TEST + 'kill'), board=(YSONDRE,), members=(ALL_RACE,))
        self.play(g, TEST + 'kill', self.first(g, YSONDRE, 'board').id)
        self.assertEqual(len(g.state.players[1].board), 1)
        self.assertEqual(self.first(g, ALL_RACE, 'board').card_id, ALL_RACE)
        self.play(g, MADNESS)
        self.assertEqual(g.state.pending_choice.options[0].card_id, YSONDRE)
        self.choose(g)
        self.play(g, TEST + 'kill', self.first(g, YSONDRE, 'board').id)
        self.assertEqual(len(g.state.players[1].board), 3)
        self.assertEqual(sum(d.card_id == YSONDRE for d in g.state.death_history), 2)
        self.portable(g)

    def test_ysondre_friendly_at_actual_death_does_not_count_enemy_death(self):
        g = self.game((TEST + 'kill', TEST + 'kill'), board=(YSONDRE,),
            enemy=(YSONDRE,), members=(ALL_RACE,))
        self.play(g, TEST + 'kill', self.first(g, YSONDRE, 'board', 2).id)
        self.play(g, TEST + 'kill', self.first(g, YSONDRE, 'board').id)
        self.assertEqual((len(g.state.players[1].board), len(g.state.players[2].board)), (1, 1))
        self.assertEqual(len(g.state.death_history), 2)

    def test_madness_uses_real_unique_dragon_or_all_deaths_and_new_base_body(self):
        g = self.game((TEST + 'buff', TEST + 'kill', TEST + 'kill', TEST + 'kill', MADNESS),
            board=(DRAGON, DRAGON, ALL_RACE), enemy=(UNDEAD,))
        original = self.first(g, DRAGON, 'board').id
        self.play(g, TEST + 'buff', original)
        for target in tuple(g.state.players[1].board):
            self.play(g, TEST + 'kill', target)
        self.play(g, MADNESS)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {DRAGON, ALL_RACE})
        self.assertEqual(len(g.state.pending_choice.options), 2)
        self.portable(g)
        option = next(o for o in g.state.pending_choice.options if o.card_id == DRAGON)
        self.choose(g, (option.id,))
        new = self.first(g, DRAGON, 'board')
        self.assertNotEqual(new.id, original)
        self.assertEqual((new.attack, new.max_health), (2, 6))
        self.assertEqual(len(g.state.death_history), 3)
        self.portable(g)

    def test_rite_plain_or_original_gift_branch_and_resource_bank(self):
        for bank in (0, 1, 2, 5):
            with self.subTest(bank=bank):
                g = self.game((RITE,), corpses=bank, members=(UNDEAD, ALL_RACE))
                self.play(g, RITE)
                self.assertEqual(g.state.players[1].resources[Resource.CORPSES], bank - (2 if bank >= 2 else 0))
                self.assertTrue({o.card_id for o in g.state.pending_choice.options}.issubset({UNDEAD, ALL_RACE}))
                self.portable(g)
                if bank >= 2:
                    self.assertEqual(len(g._frame.options[0].effects[0].batch.spec.gift_pool.members), 10)
                self.choose(g)
                self.assertIsNone(g.state.pending_choice)
                self.portable(g)

    def test_farm_exact_actual_capped_cost_including_zero_and_full_board(self):
        for bank, cid, remaining in ((0, ZERO, 0), (3, THREE, 0), (12, EIGHT, 4)):
            with self.subTest(bank=bank):
                g = self.game((FARM,), corpses=bank, members=(ZERO, THREE, EIGHT))
                self.play(g, FARM)
                self.assertEqual(self.first(g, cid, 'board').card_id, cid)
                self.assertEqual(g.state.players[1].resources[Resource.CORPSES], remaining)
                spent = [e for e in g.events if e.kind == 'resource_spent']
                self.assertEqual(spent[-1].amount, min(bank, 8))
        g = self.game((FARM,), board=(YETI,) * 7, corpses=3, members=(THREE,))
        self.play(g, FARM)
        self.assertEqual((g.state.players[1].resources[Resource.CORPSES], len(g.state.players[1].board)), (0, 7))

    def test_farm_original_debit_survives_later_bank_gain_wait_restore_and_failure(self):
        g = self.game((FARM,), corpses=3, mode='farm', members=(THREE, EIGHT))
        self.play(g, FARM)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 0)
        saved = g.snapshot()
        self.portable(g)
        with self.assertRaises(ResolutionError):
            self.choose(g, ('bad',))
        self.assertEqual(g.snapshot(), saved)
        self.choose(g, ('gain',))
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 5)
        self.assertEqual(self.first(g, THREE, 'board').card_id, THREE)
        self.portable(g)

    def test_farm_unknown_complete_candidate_rolls_back_payment_debit_and_rng(self):
        g = self.game((FARM,), corpses=3, members=(THREE, UNKNOWN))
        saved, calls = g.snapshot(), []
        original = random.Random.randrange
        def spy(rng, *args, **kwargs):
            calls.append(args)
            return original(rng, *args, **kwargs)
        with patch.object(random.Random, 'randrange', spy), self.assertRaises(ResolutionError):
            self.play(g, FARM)
        self.assertEqual(g.snapshot(), saved)
        self.assertFalse(calls)

    def test_two_public_minion_target_domain_selection_and_nondeath_batch(self):
        g = self.game((TWO,), enemy=(YETI, TEST + 'stealth', TEST + 'dormant', TEST + 'elusive'))
        ids = tuple(g.state.players[2].board)
        self.play(g, TWO)
        q = g.state.pending_choice
        self.assertEqual((q.min_count, q.max_count), (2, 2))
        self.assertEqual({o.entity_id for o in q.options}, {ids[0], ids[3]})
        self.portable(g)
        self.choose(g, tuple(o.id for o in q.options))
        self.assertEqual([g.state.entities[i].zone for i in (ids[0], ids[3])], [Zone.SETASIDE] * 2)
        self.assertFalse(g.state.death_history)
        self.assertEqual(g.state.players[2].resources[Resource.CORPSES], 0)
        event, = [e for e in g.events if e.kind == 'cards_removed_from_game']
        self.assertEqual(event.amount, 2)
        self.portable(g)

    def test_two_fewer_targets_and_original_selected_residence_not_retargeted(self):
        for enemy in ((), (YETI,)):
            g = self.game((TWO,), enemy=enemy)
            self.play(g, TWO)
            if enemy:
                self.assertEqual(g.state.pending_choice.min_count, 1)
                self.choose(g)
                self.assertFalse(g.state.players[2].board)
            else:
                self.assertIsNone(g.state.pending_choice)
        g = self.game((TWO,), enemy=(YETI, DRAGON), mode='two')
        ids = tuple(g.state.players[2].board)
        self.play(g, TWO)
        q = g.state.pending_choice
        self.choose(g, tuple(o.id for o in q.options))
        self.portable(g)
        self.choose(g, ('cycle',))
        self.assertEqual((g.state.entities[ids[0]].zone, g.state.entities[ids[1]].zone), (Zone.BOARD, Zone.SETASIDE))
        self.assertFalse(g.state.death_history)
        self.portable(g)

    def test_all_removes_both_physical_boards_including_dormant_without_death(self):
        g = self.game((ALL,), board=(YSONDRE, TEST + 'dormant', 'EDR_520'), enemy=(DRAGON, TEST + 'stealth'))
        location = self.first(g, 'EDR_520', 'board').id
        old = tuple(i for i in g.state.players[1].board + g.state.players[2].board if i != location)
        source = self.play(g, ALL)
        self.assertEqual(tuple(g.state.players[1].board), (location, source))
        self.assertFalse(g.state.players[2].board)
        self.assertTrue(all(g.state.entities[i].zone == Zone.SETASIDE for i in old))
        self.assertFalse(g.state.death_history)
        self.assertEqual((g.state.players[1].resources[Resource.CORPSES], g.state.players[2].resources[Resource.CORPSES]), (0, 0))
        event, = [e for e in g.events if e.kind == 'cards_removed_from_game']
        self.assertEqual(event.amount, 4)
        self.portable(g)

    def test_improviser_actual_own_current_turn_spell_and_native_duplicate_secret_attempts(self):
        g = self.game((IMPROVISER,), members=(COUNTER,))
        self.play(g, IMPROVISER)
        self.assertFalse(g.state.cast_history or g.state.players[1].secrets)
        g = self.game((TEST + 'spell', IMPROVISER), members=(COUNTER,))
        self.play(g, TEST + 'spell')
        self.play(g, IMPROVISER)
        self.assertEqual(len(g.state.players[1].secrets), 1)
        attempts = [c for c in g.state.cast_history if c.card_id == COUNTER]
        self.assertEqual(len(attempts), 2)
        self.assertTrue(all(c.origin == 'effect' for c in attempts))
        self.portable(g)
        g = self.game((TEST + 'spell', IMPROVISER), members=(COUNTER,))
        self.play(g, TEST + 'spell')
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.play(g, IMPROVISER)
        self.assertFalse(g.state.players[1].secrets)

    def test_improviser_unknown_qualified_secret_rejects_without_cropping_pool(self):
        g = self.game((TEST + 'spell', IMPROVISER), members=(COUNTER, UNKNOWN_SECRET))
        self.play(g, TEST + 'spell')
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, IMPROVISER)
        self.assertEqual(g.snapshot(), saved)

    def test_hogger_true_opening_copies_all_legendary_kinds_once_and_keeps_original_deck(self):
        self.config = None, MEMBERS
        r = registry()
        first = (HOGGER, *LEGENDS, *((YETI,) * 4))
        decks = (DeckSpec('HERO_01', 'HERO_01bp', CardClass.WARRIOR, first),
            DeckSpec('HERO_08', 'HERO_08bp', CardClass.MAGE, (YETI,) * 8))
        policy = DeckPolicy('p56-opening', CONTEXT.target_id, CONTEXT.mode,
            tuple(r.cards), deck_size=8, max_copies=8)
        g = Game.from_decks(MatchSetup(decks, policy, 'GAME_005', seed=5656, first_player=1), r)
        self.assertEqual(tuple(g.state.players[1].original_deck), first)
        all_first = [e for e in g.state.entities.values() if e.owner == 1]
        self.assertEqual(sum(e.card_id == HOGGER for e in all_first), 1)
        for cid in LEGENDS:
            self.assertEqual(sum(e.card_id == cid for e in all_first), 2)
        self.assertEqual(len(g.state.players[1].hand) + len(g.state.players[1].deck), 11)
        self.assertEqual(len(g.state.deck_shuffle_history), 1)
        self.portable(g)
        while g.state.pending_choice:
            self.choose(g, ())
        self.assertEqual(len(g.state.deck_shuffle_history), 1)
        self.assertEqual(tuple(g.state.players[1].original_deck), first)
        self.portable(g)


if __name__ == '__main__':
    unittest.main()
