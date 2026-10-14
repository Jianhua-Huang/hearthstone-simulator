"""Actual starting-deck eligibility; no speculative effect combinations."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    Game, PlayCard, PlayerSetup, Registry, ResolutionError, Scenario, SelectChoice,
    SnapshotError, Zone, Keyword, Rarity)
from hs_sim.engine.construction import DeckPolicy, DeckSpec, MatchSetup
from hs_sim.engine.cross_zone import MinionScope, TransformMinionsInZones
from hs_sim.engine.effects import AddToHand, ChoiceOption, RequestChoice, ShuffleIntoDeck
from hs_sim.engine.pools import (DiscoverFromPool, GenerateFromPool, GenerationContext,
    PoolCard, PoolDefinition, PoolMember, PoolQuery, SummonFromPool, resolve_candidates)
from hs_sim.engine.pool_offers import ChooseFromPools, PoolOfferGroup
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.starting_generation import CTHUN as CT_GROUP, GALAKROND, group_for
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import canonical_digest
from test_cthun_basics import registry as cthun_registry, CTHUN, BECKONER, ELDER
from test_invoke_basics import registry as galakrond_registry


TARGET = 'starting-generation-tests'
PIN = '16bbb51825c490a71a0017dc7c25d995735aaf9f2a06420cc10e27becd6f94af'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/starting-generation.json'


def raw_evidence():
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(data) != PIN:
        raise ValueError('Complete starting group survey changed')
    for row in data['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original complete group record changed')
    return data


def add_pool(r, name, ids):
    for cid in ids:
        if cid not in r.pool_cards:
            d = r.card(cid)
            if d.metadata is None:
                d = replace(d, metadata=CardMetadata(False, (CardClass.NEUTRAL,), None))
                r._cards[cid] = d  # Complete this synthetic fixture before freezing.
            r.register_pool_card(PoolCard.from_definition(d))
    r.register_pool(PoolDefinition(name, 'v1', TARGET, 'experimental', tuple(PoolMember(cid) for cid in ids)))


class StartingGenerationTests(unittest.TestCase):
    def setUp(self):
        self.extras = []

    def script(self, cid, fn):
        self.extras.append((cid, fn))

    def registry(self):
        r = cthun_registry(self.extras)
        r._cards['hero'] = replace(r.card('hero'), initial_hero_power='power')
        r.register_behavior('opening.noop', lambda c: ())
        r.register_card(CardDefinition('power', 'power', CardType.HERO_POWER,
            cost=2, on_use='opening.noop', metadata=CardMetadata(False, (CardClass.MAGE,), None)))
        r.register_card(CardDefinition('coin', 'coin', CardType.SPELL, on_play='opening.noop'))
        raw = {row['id']: row['data'] for row in raw_evidence()['records']}
        for cid in ('DRG_050', 'DRG_099', 'DRG_620'):
            row = raw[cid]
            metadata = CardMetadata(True, (CardClass.NEUTRAL,) if cid != 'DRG_620' else (CardClass.SHAMAN,),
                Rarity.COMMON if row['tags']['RARITY'] == 1 else Rarity.LEGENDARY, tribes=())
            r.register_pool_card(PoolCard(cid, CardType(row['type'].lower()), row['cost'], metadata,
                keywords=(Keyword.INVOKE, Keyword.RUSH) if cid == 'DRG_050' else (),
                battlecry=True))  # Only inventory metadata; no incomplete executable definitions.
        for name, ids in (('ct', (CTHUN,)), ('cultist', (BECKONER,)),
                          ('ordinary', ('plain',)), ('mixed', ('plain', BECKONER, CTHUN, 'DRG_050')),
                          ('ga', ('DRG_050',)), ('ga-hero', ('DRG_620',))):
            add_pool(r, name, ids)
        return r

    def context(self, decks=((), ())):
        return GenerationContext(TARGET, 'experimental', decks)

    def game(self, hand=('gen',), board=(), decks=((), ()), enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, mana=10, max_mana=10),
            PlayerSetup('hero', hand=enemy_hand, mana=10, max_mana=10)), seed=11,
            generation_context=self.context(decks)), self.registry())

    def play(self, g, cid, pid=1):
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid, eid)); return eid

    def candidates(self, pool='mixed', decks=((), ()), pid=1, query=PoolQuery()):
        return tuple(m.card_id for m in resolve_candidates(self.registry(), self.context(decks), pool, query, player_id=pid))

    def check(self, g, fresh=None):
        fresh = fresh or self.registry
        restored = Game.from_snapshot(g.snapshot(), fresh())
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual(g.clone().snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), fresh()).snapshot(), g.snapshot())
        for p in (1, 2):
            self.assertEqual(restored.observe(p), g.observe(p))

    def reject(self, g, mutate):
        s = g.snapshot(); mutate(s)
        s['events_hash'] = canonical_hash(s['events'])
        s['state_hash'] = canonical_hash({k: v for k, v in s.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(s, self.registry())

    def test_actual_pinned_two_group_inventory(self):
        raw = raw_evidence()
        self.assertEqual(len(raw['records']), 64)
        self.assertEqual(set(raw['groups']['cthun']), CT_GROUP)
        self.assertEqual(set(raw['groups']['galakrond']), GALAKROND)
        self.assertNotIn('DMF_254', CT_GROUP)

    def test_empty_original_decks_filter_both_groups_before_adapter_lookup(self):
        self.assertEqual(self.candidates(), ('plain',))

    def test_real_cthun_source_unlocks_its_group_only(self):
        self.assertEqual(self.candidates(decks=((BECKONER,), ())), (CTHUN, BECKONER, 'plain'))

    def test_original_cthun_itself_unlocks_same_group(self):
        self.assertEqual(self.candidates(pool='cultist', decks=((CTHUN,), ())), (BECKONER,))

    def test_other_seat_starting_card_does_not_unlock_first_seat(self):
        self.assertEqual(self.candidates(pool='ct', decks=((), (BECKONER,))), ())
        self.assertEqual(self.candidates(pool='ct', decks=((), (BECKONER,)), pid=2), (CTHUN,))

    def test_galakrond_source_does_not_unlock_classic_cthun(self):
        self.assertEqual(self.candidates(pool='ct', decks=(('DRG_050',), ())), ())

    def test_related_non_invoke_kronx_is_part_of_real_group(self):
        self.assertEqual(group_for(self.registry(), 'DRG_099'), 'galakrond')
        with self.assertRaises(UnsupportedDefinitionError):
            self.candidates(pool='ga', decks=(('DRG_099',), ()))

    def test_unadapted_galakrond_is_error_when_original_group_qualifies(self):
        with self.assertRaises(UnsupportedDefinitionError):
            self.candidates(pool='ga-hero', decks=(('DRG_050',), ()))

    def test_related_conditional_source_without_invoke_keyword_is_recognized(self):
        self.assertEqual(group_for(self.registry(), 'DRG_217'), 'galakrond')
        self.assertEqual(group_for(self.registry(), 'WON_144'), 'cthun')

    def test_true_rarity_filter_remains_independent_of_starting_qualification(self):
        decks = (('DRG_050',), ())
        self.assertEqual(self.candidates(pool='ga', decks=decks,
            query=PoolQuery(rarities=(Rarity.LEGENDARY,))), ())
        with self.assertRaises(UnsupportedDefinitionError):
            self.candidates(pool='ga', decks=decks, query=PoolQuery(rarities=(Rarity.COMMON,)))

    def test_unknown_original_facts_error_for_restricted_candidate(self):
        with self.assertRaises(ResolutionError):
            resolve_candidates(self.registry(), GenerationContext(TARGET, 'experimental'), 'ct', PoolQuery(), player_id=1)

    def test_missing_query_seat_errors_instead_of_borrowing_other_seat(self):
        with self.assertRaises(ResolutionError):
            resolve_candidates(self.registry(), self.context(((BECKONER,), ())), 'ct', PoolQuery())

    def test_irrelevant_query_can_filter_group_without_needing_origin(self):
        self.assertEqual(resolve_candidates(self.registry(), GenerationContext(TARGET, 'experimental'),
            'ct', PoolQuery(kinds=(CardType.SPELL,))), ())

    def test_ordinary_pool_still_works_with_unknown_original_facts(self):
        result = resolve_candidates(self.registry(), GenerationContext(TARGET, 'experimental'), 'ordinary', PoolQuery())
        self.assertEqual(tuple(x.card_id for x in result), ('plain',))

    def test_existing_cost_and_identity_exclusions_still_apply(self):
        self.assertEqual(self.candidates(pool='ct', decks=((BECKONER,), ()), query=PoolQuery(max_cost=7)), ())
        self.assertEqual(self.candidates(pool='ct', decks=((BECKONER,), ()), query=PoolQuery(exclude_card_ids=(CTHUN,))), ())

    def test_context_keeps_order_duplicates_and_rejects_loose_types(self):
        ctx = self.context(((BECKONER, BECKONER, CTHUN), ()))
        self.assertEqual(GenerationContext.from_dict(ctx.to_dict()), ctx)
        for decks in (((),), ([], ()), ((True,), ()), ((BECKONER,), (), ())):
            with self.assertRaises(ValueError):
                self.context(decks)
        with self.assertRaises(ValueError):
            GenerationContext.from_dict({'target_id': TARGET, 'mode': 'experimental'})

    def test_disallowed_empty_pool_preserves_rng_and_no_body(self):
        self.script('gen', lambda c: (GenerateFromPool(1, 'ct', source_id=c.source_id),))
        g = self.game(); before = g.snapshot()['rng_state']; self.play(g, 'gen')
        self.assertEqual(g.snapshot()['rng_state'], before)
        self.assertEqual(g.state.players[1].hand, []); self.check(g)

    def test_live_generation_inherits_original_qualification(self):
        self.script('gen', lambda c: (GenerateFromPool(1, 'ct', source_id=c.source_id),))
        g = self.game(decks=((BECKONER,), ())); self.play(g, 'gen')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [CTHUN]); self.check(g)

    def test_present_hand_or_board_does_not_replace_original_deck(self):
        self.script('gen', lambda c: (GenerateFromPool(1, 'ct', source_id=c.source_id),))
        g = self.game(hand=('gen', BECKONER), board=(CTHUN,)); self.play(g, 'gen')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [BECKONER]); self.check(g)

    def test_later_generated_or_shuffled_related_card_does_not_unlock(self):
        self.script('add', lambda c: (AddToHand(1, BECKONER),))
        self.script('shuffle', lambda c: (ShuffleIntoDeck(c.state.players[1].hand[-1]),))
        self.script('gen', lambda c: (GenerateFromPool(1, 'ct', source_id=c.source_id),))
        g = self.game(hand=('add', 'shuffle', 'gen'))
        for cid in ('add', 'shuffle', 'gen'):
            self.play(g, cid)
        self.assertEqual(g.state.players[1].hand, []); self.assertEqual(len(g.state.players[1].deck), 1); self.check(g)

    def test_literal_required_creation_is_not_random_pool_selection(self):
        self.script('gen', lambda c: (AddToHand(1, CTHUN),))
        g = self.game(); self.play(g, 'gen')
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id, CTHUN); self.check(g)

    def test_discover_waiting_restore_keeps_original_deck_qualification(self):
        self.script('discover', lambda c: (DiscoverFromPool(1, 'ct', source_id=c.source_id),))
        g = self.game(hand=('discover',), decks=((BECKONER,), ())); self.play(g, 'discover')
        self.check(g)
        choice = g.state.pending_choice
        g.apply(SelectChoice(1, choice.id, (choice.options[0].id,)))
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id, CTHUN); self.check(g)

    def test_repeated_discovery_restores_each_offer_with_same_origin(self):
        self.script('discover', lambda c: (DiscoverFromPool(1, 'ct', discoveries=2, source_id=c.source_id),))
        g = self.game(hand=('discover',), decks=((BECKONER,), ())); self.play(g, 'discover')
        for _ in range(2):
            self.check(g); choice = g.state.pending_choice
            g.apply(SelectChoice(1, choice.id, (choice.options[0].id,)))
        self.assertEqual(len(g.state.players[1].hand), 2); self.check(g)

    def test_grouped_offer_validation_uses_same_starting_decks(self):
        self.script('offer', lambda c: (ChooseFromPools(1, (PoolOfferGroup('ct'),), source_id=c.source_id),))
        g = self.game(hand=('offer',), decks=((BECKONER,), ())); self.play(g, 'offer'); self.check(g)
        choice = g.state.pending_choice; g.apply(SelectChoice(1, choice.id, (choice.options[0].id,)))
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id, CTHUN); self.check(g)

    def test_attributed_pool_summon_freezes_and_validates_same_origin(self):
        self.script('summon-pool', lambda c: (SummonFromPool(1, 'ct', source_id=c.source_id, cause=SummonCause.capture(c)),))
        g = self.game(hand=('summon-pool',), decks=((BECKONER,), ())); self.play(g, 'summon-pool')
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].card_id, CTHUN); self.check(g)

    def test_random_transform_requires_group_and_does_not_retroapply_ritual(self):
        self.script('evolve', lambda c: (TransformMinionsInZones(1, 'ct', cost_delta=8,
            scope=MinionScope((Zone.BOARD,)), source_id=c.source_id),))
        g = self.game(hand=('evolve',), board=('plain',), decks=((BECKONER,), ()))
        self.play(g, 'evolve'); e = g.state.entities[g.state.players[1].board[0]]
        self.assertEqual((e.card_id, e.attack), (CTHUN, 6)); self.check(g)

    def test_random_transform_without_starting_group_keeps_original_body(self):
        self.script('evolve', lambda c: (TransformMinionsInZones(1, 'ct', cost_delta=8,
            scope=MinionScope((Zone.BOARD,)), source_id=c.source_id),))
        g = self.game(hand=('evolve',), board=('plain',)); before = g.snapshot()['rng_state']; self.play(g, 'evolve')
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].card_id, 'plain')
        self.assertEqual(g.snapshot()['rng_state'], before); self.check(g)

    def test_galakrond_native_pool_can_generate_a_real_invoker_when_qualified(self):
        fn = lambda c, r: (GenerateFromPool(1, 'native-ga', source_id=c.source_id),)
        def fresh():
            r = galakrond_registry((('gagen', fn),)); add_pool(r, 'native-ga', ('DRG_242',)); return r
        g = Game.from_scenario(Scenario((PlayerSetup('hero.shaman', hand=('gagen',), mana=10, max_mana=10),
            PlayerSetup('hero.mage')), generation_context=self.context((('DRG_242',), ()))), fresh())
        self.play(g, 'gagen')
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id, 'DRG_242'); self.check(g, fresh)

    def test_constructed_opening_pins_both_actual_complete_decks(self):
        cards = (BECKONER,) * 4 + (ELDER,) * 4
        spec = DeckSpec('hero', 'power', CardClass.MAGE, cards)
        setup = MatchSetup((spec, spec), DeckPolicy('test', TARGET, 'experimental',
            (CTHUN, BECKONER, ELDER), deck_size=8, max_copies=4), 'coin', first_player=1)
        g = Game.from_decks(setup, self.registry())
        self.assertEqual(g.snapshot()['generation_context']['starting_decks'], [list(cards), list(cards)])
        self.assertEqual(g.state.players[1].original_deck, cards)
        self.check(g)

    def test_bad_later_candidate_rolls_back_rng_cards_events_and_payment(self):
        self.script('bad', lambda c: (GenerateFromPool(1, 'ct'), AddToHand(1, 'unknown')))
        g = self.game(hand=('bad',), decks=((BECKONER,), ())); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'bad')
        self.assertEqual(g.snapshot(), before)

    def test_original_deck_and_context_cannot_disagree_after_rehash(self):
        self.script('gen', lambda c: ())
        g = self.game(decks=((BECKONER,), ()))
        self.reject(g, lambda s: s['generation_context']['starting_decks'][0].clear())

    def test_player_views_do_not_receive_context_or_original_decks(self):
        self.script('gen', lambda c: (GenerateFromPool(1, 'ct'),))
        g = self.game(decks=((BECKONER,), ())); self.play(g, 'gen')
        for pid in (1, 2):
            view = json.dumps(g.observe(pid))
            self.assertNotIn('starting_decks', view); self.assertNotIn('original_deck', view)
            self.assertNotIn('generation_context', view)


if __name__ == '__main__':
    unittest.main()
