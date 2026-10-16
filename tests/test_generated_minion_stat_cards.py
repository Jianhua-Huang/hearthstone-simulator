"""Creation numeric material belongs to actual fresh entities, before notification."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
from functools import lru_cache
import json
import random
import re
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.generated_minion_stat_cards import KAROV, TRIUMPH, ROOTS, GRANTS, QUERIES, POOL_ID, load_batch
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import CardClass, CardDefinition, CardMetadata, CardType, Game, PlayCard, PlayerSetup, Scenario, SelectChoice
from hs_sim.engine.actions import EndTurn
from hs_sim.engine.card_creation import CreatedMinionGrant, CreatedMinionStats, DiscoveryMinionGift
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy, Draw, GainArmor,
                                  InvokeBehavior, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import CostSpec, Keyword, LimitedTriggerSpec, Rarity, SpellSchool, SummonStats, TargetSpec, Zone
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromPool, GenerationContext, PoolCard, PoolDefinition, PoolMember, resolve_candidates, sample_candidates
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard
from hs_sim.targets import canonical_digest

P = 'k119.test.'
YETI = 'CORE_CS2_182'
LEGEND = 'EX1_563'
EIGHT = 'GVG_079'
FOREIGN = 'CORE_UNG_848'
FOREIGN_LEGEND = 'RLK_541'
UNKNOWN = P + 'unknown'
MEMBERS = (LEGEND, EIGHT, FOREIGN, FOREIGN_LEGEND, YETI, KAROV, TRIUMPH)
CTX = GenerationContext('k119-explicit-experiment', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())


@lru_cache(None)
def registry(members=MEMBERS, mode=None, pool=True):
    r = build_registry()
    for cid in members:
        if cid in r.cards and cid not in r.pool_cards:
            r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if UNKNOWN in members:
        r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 9,
            CardMetadata(True, (CardClass.WARLOCK,), Rarity.LEGENDARY, tribes=(), factions=(), subtypes=())))
    if pool:
        r.register_pool(PoolDefinition(POOL_ID, 'k119-weighted-v1', CTX.target_id, CTX.mode,
            tuple(PoolMember(cid, 3 if cid == LEGEND else 1) for cid in members), complete=True))
    def hand_minion(c):
        return CardReference.capture(next(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id == LEGEND))
    def wait_before(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('hand', 'Generate fixed stats', (GenerateFromPool(c.player_id, POOL_ID,
                QUERIES[KAROV], count=3, source_id=c.source_id, cost=CostSpec(set_to=1), minion_stats=GRANTS[KAROV]),)),
            ChoiceOption('deck', 'Shuffle doubled stats', (GenerateFromPool(c.player_id, POOL_ID,
                QUERIES[TRIUMPH], count=5, source_id=c.source_id, destination='deck',
                minion_stats=GRANTS[TRIUMPH], shuffle_actor_id=c.player_id),)),), c.source_id),)
    scripts = {
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'draw': lambda c: (Draw(c.player_id),),
        'copy': lambda c: (CopyCard(hand_minion(c), c.player_id, source_id=c.source_id),),
        'basecopy': lambda c: (CopyCard(hand_minion(c), c.player_id, mode='base', source_id=c.source_id),),
        'before': wait_before,
        'fail': lambda c: (_ for _ in ()).throw(ResolutionError('K119 deliberate creation failure')),
        'wrong_hand': lambda c: (AddToHand(c.player_id, TRIUMPH, c.source_id, minion_stats=GRANTS[KAROV]),),
        'wrong_deck': lambda c: (AddToDeck(c.player_id, TRIUMPH, source_id=c.source_id, minion_stats=GRANTS[TRIUMPH]),),
        'missing_source': lambda c: (AddToHand(c.player_id, LEGEND, 99999, minion_stats=GRANTS[KAROV]),),
        'no_source': lambda c: (AddToHand(c.player_id, LEGEND, minion_stats=GRANTS[KAROV]),),
        'mixed': lambda c: (AddToHand(c.player_id, LEGEND, c.source_id, minion_stats=GRANTS[KAROV],
                                    minion_grant=CreatedMinionGrant(health=1)),),
        'wrong_branch': lambda c: (RequestChoice(c.player_id, (
            ChoiceOption('good', 'Good', (AddToHand(c.player_id, LEGEND, c.source_id, minion_stats=GRANTS[KAROV]),)),
            ChoiceOption('bad', 'Wrong carrier', (AddToDeck(c.player_id, TRIUMPH, source_id=c.source_id,
                                                        minion_stats=GRANTS[TRIUMPH]),)),), c.source_id),),
    }
    for name, body in scripts.items():
        r.register_behavior(P + name, body)
        r.register_card(CardDefinition(P + name, name, CardType.SPELL, on_play=P + name, metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
            if name in ('kill', 'silence', 'bounce') else None))
    if mode:
        def eligible(c):
            return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in ROOTS
        def watch(c):
            if mode == 'fail_second':
                made = [e for e in c.state.entities.values() if any(
                    a.label == 'created_minion_stats' and a.source_id == c.event.source_id for a in e.enchantments)]
                return (InvokeBehavior(P + 'fail', c.source_id, c.player_id),) if len(made) >= 2 else ()
            if mode == 'probe':
                e = c.state.entities[c.event.target_id]
                return (GainArmor(c.player_id, e.cost + e.attack + e.max_health),)
            return (RequestChoice(c.player_id, (
                ChoiceOption('ok', 'Continue', ()),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(P + 'fail', c.source_id, c.player_id),)),), c.source_id),)
        r.register_trigger_condition(P + 'eligible', eligible)
        r.register_behavior(P + 'watch', watch)
        r.register_card(CardDefinition(P + 'watch', 'Creation observer', CardType.MINION, health=6, metadata=META,
            limited_triggers=(LimitedTriggerSpec('card_created', P + 'watch', condition_id=P + 'eligible', uses=5),)))
    r.validate()
    return r


class GeneratedMinionStatTests(unittest.TestCase):
    def game(self, hand=(TRIUMPH,), board=(), enemy_hand=(), members=MEMBERS, mode=None,
             pool=True, context=CTX, deck=(YETI,) * 4):
        self.config = (members, mode, pool)
        if mode:
            board = (*board, P + 'watch')
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_09', hand=hand, board=board, deck=deck, mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_08', hand=enemy_hand, deck=(YETI,) * 4, mana=40, max_mana=40, mana_cap=40),
        ), seed=119, generation_context=context), registry(*self.config))

    def play(self, g, cid=TRIUMPH, target=None, player=1):
        eid = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(player, eid, target,
            len(g.state.players[player].board) if g.registry.card(cid).kind == CardType.MINION else None))
        return eid

    def source(self, g):
        return next(i for i in g.state.players[1].board if g.state.entities[i].card_id == KAROV)

    def kill(self, g):
        source = self.source(g)
        self.play(g, P + 'kill', source)
        return source

    def created(self, g, source):
        return [g.state.entities[e.target_id] for e in g.events if e.kind == 'card_created' and e.source_id == source]

    def candidates(self, g, cid):
        return resolve_candidates(g.registry, CTX, POOL_ID, QUERIES[cid],
                                  source_card_id=cid, exclude_source_by_rule=True, player_id=1)

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(*self.config))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(*self.config)).snapshot(), saved)
        for seat in (1, 2):
            public = json.dumps(g.for_player(seat).observe()) + json.dumps(g.for_player(seat).legal_actions()) + json.dumps(g.player_events(seat))
            for field in ('minion_stats', 'CreatedMinionStats', 'resolution_frame', 'rng_state', 'deck_shuffle_history'):
                self.assertNotIn('"' + field + '"', public)
            self.assertNotIn('entities', g.for_player(seat).observe()['observation'])
        return other

    def resume(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def nodes(self, value, suffix):
        if isinstance(value, dict):
            if value.get('type', '').endswith('.' + suffix):
                yield value['fields']
            for item in value.values():
                yield from self.nodes(item, suffix)
        elif isinstance(value, list):
            for item in value:
                yield from self.nodes(item, suffix)

    def reject(self, saved):
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as caught:
            Game.from_snapshot(saved, registry(*self.config))
        self.assertNotIn('digest mismatch', str(caught.exception))

    def test_complete_four_rows_four_primary_faces_and_actual_class_school(self):
        data = load_batch()
        r = registry()
        for row in data['cards'] + data['evidence_only']:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        norm = lambda s: re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]', '', s)
        raw = {x['record']['id']: x['record'] for x in data['cards']}
        for o in data['official_observations']['observations']:
            rec = raw[o['card_id']]
            cn = o['locale'] == 'zh_CN'
            self.assertEqual(o['face']['name'], rec['name' if cn else 'name_en'])
            self.assertEqual(norm(o['face']['text']), norm(rec['text' if cn else 'text_en']))
        self.assertEqual(len(data['official_observations']['observations']), 4)
        for cid in ROOTS:
            self.assertEqual(r.card(cid).metadata, metadata_from_record(raw[cid]))
        self.assertEqual((r.card(KAROV).cost, r.card(KAROV).attack, r.card(KAROV).health), (6, 6, 6))
        self.assertEqual(r.card(KAROV).keywords, (Keyword.TAUNT,))
        self.assertEqual(r.card(KAROV).metadata.classes, (CardClass.PRIEST,))
        self.assertEqual((r.card(TRIUMPH).cost, r.card(TRIUMPH).spell_school), (1, SpellSchool.ARCANE))
        self.assertTrue(all(x['record']['id'] not in r.cards for x in data['evidence_only']))
        self.assertFalse(data['formal_pool_complete'])
        self.assertFalse(data['cn_calibrated'])

    def test_native_death_gets_three_distinct_one_one_one_cards_without_touching_old_names(self):
        g = self.game(hand=(P + 'kill', LEGEND), board=(KAROV,), members=(LEGEND,), mode='probe')
        old = g.state.players[1].hand[1]
        source = self.kill(g)
        cards = self.created(g, source)
        self.assertEqual(len({e.id for e in cards}), 3)
        self.assertTrue(all((e.card_id, e.cost, e.attack, e.max_health, e.zone) == (LEGEND, 1, 1, 1, Zone.HAND) for e in cards))
        self.assertTrue(all(e.enchantments[-1].source_id == source for e in cards))
        self.assertEqual((g.state.entities[old].cost, g.state.entities[old].attack, g.state.entities[old].max_health), (9, 4, 12))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 9)
        self.assertEqual(len(g.state.death_history), 1)
        self.assertFalse(g.state.battlecry_history)
        self.assertEqual(g.state.players[1].mana, 40)
        self.portable(g)

    def test_karov_uses_full_printed_legendary_anyclass_weighted_pool_before_stat_changes(self):
        g = self.game(hand=(P + 'kill',), board=(KAROV,))
        candidates = self.candidates(g, KAROV)
        self.assertEqual({m.card_id for m in candidates}, {LEGEND, FOREIGN_LEGEND})
        self.assertEqual(QUERIES[KAROV].class_mode, 'any')
        rng = random.Random()
        rng.setstate(g._rng.getstate())
        expected = sample_candidates(rng, candidates, 3, replacement=True)
        source = self.kill(g)
        self.assertEqual(tuple(e.card_id for e in self.created(g, source)), expected)
        self.assertEqual(g._rng.getstate(), rng.getstate())
        self.portable(g)

    def test_silence_removes_native_deathrattle_before_death(self):
        g = self.game(hand=(P + 'silence', P + 'kill'), board=(KAROV,), members=(LEGEND,))
        source = self.source(g)
        self.play(g, P + 'silence', source)
        self.kill(g)
        self.assertFalse(self.created(g, source))
        self.portable(g)

    def test_opponent_turn_death_delivers_to_original_owner(self):
        g = self.game(hand=(), board=(KAROV,), enemy_hand=(P + 'kill',), members=(LEGEND,))
        source = self.source(g)
        g.apply(EndTurn(1))
        self.play(g, P + 'kill', source, 2)
        self.assertEqual(len(self.created(g, source)), 3)
        self.assertTrue(all(e.controller == 1 and e.zone == Zone.HAND for e in self.created(g, source)))
        self.portable(g)

    def test_hand_overflow_installs_complete_stats_cost_and_source_on_burned_results(self):
        g = self.game(hand=(P + 'kill',) + (YETI,) * 9, board=(KAROV,), members=(LEGEND,))
        cards = self.created(g, self.kill(g))
        self.assertEqual([e.zone for e in cards], [Zone.HAND, Zone.GRAVEYARD, Zone.GRAVEYARD])
        self.assertTrue(all((e.cost, e.attack, e.max_health) == (1, 1, 1) for e in cards))
        self.assertEqual(len([e for e in g.events if e.kind == 'card_burned']), 2)
        self.portable(g)

    def test_first_hand_creation_wait_restores_remaining_typed_material_without_resampling(self):
        g = self.game(hand=(P + 'kill',), board=(KAROV,), members=(LEGEND,), mode='wait')
        source = self.kill(g)
        self.assertEqual(len(self.created(g, source)), 1)
        material = list(self.nodes(g.snapshot()['resolution_frame'], 'CreatedMinionStats'))
        self.assertGreaterEqual(len(material), 2)
        self.assertTrue(all(row['set_to']['fields'] == {'attack': 1, 'health': 1} for row in material))
        other = self.portable(g)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.resume(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        rng = g._rng.getstate()
        for game in (g, other):
            while game.state.pending_choice:
                self.resume(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g._rng.getstate(), rng)
        self.assertEqual(len(self.created(g, source)), 3)
        self.portable(g)

    def test_acquisition_failure_rolls_back_native_death_or_complete_shuffle_with_rng(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g = self.game(hand=(P + 'kill',) if cid == KAROV else (TRIUMPH,),
                    board=(KAROV,) if cid == KAROV else (), members=(LEGEND,), mode='fail_second')
                saved = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'K119 deliberate'):
                    self.kill(g) if cid == KAROV else self.play(g)
                self.assertEqual(g.snapshot(), saved)

    def test_triumph_shuffles_five_doubled_cards_as_one_original_semantic_operation(self):
        g = self.game(members=(EIGHT,), mode='probe')
        old = list(g.state.players[1].deck)
        source = self.play(g)
        cards = self.created(g, source)
        self.assertEqual(len({e.id for e in cards}), 5)
        self.assertTrue(all((e.card_id, e.cost, e.attack, e.max_health, e.zone) == (EIGHT, 8, 14, 14, Zone.DECK) for e in cards))
        self.assertTrue(all(e.enchantments[-1].source_id == source for e in cards))
        self.assertTrue(all((g.state.entities[i].attack, g.state.entities[i].max_health) == (4, 5) for i in old))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 5 * (8 + 14 + 14))
        self.assertEqual(len(g.state.deck_shuffle_history), 1)
        row = g.state.deck_shuffle_history[0]
        self.assertEqual((row.actor_id, row.player_id, row.declared_count, row.profile, row.source.entity_id), (1, 1, 5, 'semantic', source))
        self.assertFalse(g.state.card_summon_history)
        self.assertEqual((g.state.players[1].mana, len(g.state.cast_history)), (39, 1))
        self.portable(g)

    def test_triumph_samples_all_before_random_insertions_and_preserves_complete_rng_order(self):
        g = self.game()
        candidates = self.candidates(g, TRIUMPH)
        self.assertEqual({m.card_id for m in candidates}, {LEGEND, EIGHT, FOREIGN})
        rng = random.Random()
        rng.setstate(g._rng.getstate())
        expected = sample_candidates(rng, candidates, 5, replacement=True)
        initial = list(g.state.players[1].deck)
        source = self.play(g)
        cards = self.created(g, source)
        self.assertEqual(tuple(e.card_id for e in cards), expected)
        for e in cards:
            initial.insert(rng.randrange(len(initial) + 1), e.id)
        self.assertEqual(g.state.players[1].deck, initial)
        self.assertEqual(g._rng.getstate(), rng.getstate())
        self.portable(g)

    def test_triumph_full_hand_creates_in_deck_without_transient_acquisition_or_burn(self):
        g = self.game(hand=(TRIUMPH,) + (YETI,) * 9, members=(EIGHT,))
        cards = self.created(g, self.play(g))
        self.assertEqual(len(cards), 5)
        self.assertTrue(all(e.zone == Zone.DECK and e.hand_lifetime is None for e in cards))
        self.assertFalse([e for e in g.events if e.kind in ('card_burned', 'card_added_to_hand')])
        self.portable(g)

    def test_shuffle_wait_restores_five_complete_entities_and_one_batch_without_redoubling(self):
        g = self.game(members=(EIGHT,), mode='wait')
        source = self.play(g)
        self.assertEqual(len(self.created(g, source)), 5)
        other = self.portable(g)
        rng = g._rng.getstate()
        for game in (g, other):
            while game.state.pending_choice:
                self.resume(game)
            self.assertTrue(all(e.attack == 14 and e.max_health == 14 for e in self.created(game, source)))
            self.assertEqual(len(game.state.deck_shuffle_history), 1)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g._rng.getstate(), rng)
        self.portable(g)

    def test_draw_play_silence_and_bounce_reuse_existing_numeric_lifecycle(self):
        for action in ('silence', 'bounce'):
            g = self.game(hand=(TRIUMPH, P + 'draw', P + action), members=(EIGHT,), deck=())
            source = self.play(g)
            self.play(g, P + 'draw')
            eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == EIGHT)
            self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].max_health), (14, 14))
            self.play(g, EIGHT)
            self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].max_health), (14, 14))
            self.play(g, P + action, eid)
            self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].max_health), (7, 7))
            self.assertFalse(g.state.entities[eid].enchantments)
            self.assertEqual(len(self.created(g, source)), 5)
            self.portable(g)

    def test_one_one_current_and_base_copies_preserve_only_requested_existing_material(self):
        for action in ('copy', 'basecopy'):
            g = self.game(hand=(P + 'kill', P + action), board=(KAROV,), members=(LEGEND,))
            self.kill(g)
            source = self.play(g, P + action)
            new = self.created(g, source)[0]
            self.assertEqual((new.cost, new.attack, new.max_health), (1, 1, 1) if action == 'copy' else (9, 4, 12))
            self.portable(g)

    def test_unknown_complete_eligible_candidate_or_missing_context_rolls_back_before_rng(self):
        for cid in ROOTS:
            for case in ('unknown', 'context', 'pool'):
                with self.subTest(cid=cid, case=case):
                    g = self.game(hand=(P + 'kill',) if cid == KAROV else (TRIUMPH,),
                        board=(KAROV,) if cid == KAROV else (), members=(*MEMBERS, UNKNOWN) if case == 'unknown' else MEMBERS,
                        context=None if case == 'context' else CTX, pool=case != 'pool')
                    saved = g.snapshot()
                    with patch.object(random.Random, 'randrange', side_effect=AssertionError('Must validate full pool before RNG')) as calls:
                        with self.assertRaises(ResolutionError):
                            self.kill(g) if cid == KAROV else self.play(g)
                        calls.assert_not_called()
                    self.assertEqual(g.snapshot(), saved)

    def test_empty_pool_is_rng_neutral_without_spurious_shuffle_or_generated_card(self):
        for cid in ROOTS:
            g = self.game(hand=(P + 'kill',) if cid == KAROV else (TRIUMPH,),
                board=(KAROV,) if cid == KAROV else (), members=(YETI,))
            rng = g._rng.getstate()
            source = self.kill(g) if cid == KAROV else self.play(g)
            self.assertFalse(self.created(g, source))
            self.assertFalse(g.state.deck_shuffle_history)
            self.assertEqual(g._rng.getstate(), rng)
            self.portable(g)

    def test_finite_numeric_payload_keeps_legacy_grants_and_rejects_discovery_board_or_temporary_shapes(self):
        self.assertEqual(set(asdict(CreatedMinionGrant(health=1))), {'attack', 'health', 'keywords', 'reborn_policy', 'identity', 'special'})
        with self.assertRaises(FrozenInstanceError):
            GRANTS[KAROV].double = True
        for kw in ({}, {'double': 1}, {'double': 'yes'}, {'set_to': {'attack': 1, 'health': 1}},
                   {'set_to': SummonStats(attack=1)}, {'set_to': SummonStats(1, 1), 'double': True}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                CreatedMinionStats(**kw)
        with self.assertRaises(ValueError):
            DiscoveryMinionGift('invalid', 'Wrong gift', GRANTS[KAROV])
        with self.assertRaises(TypeError):
            DiscoverFromPool(1, POOL_ID, QUERIES[KAROV], source_id=1, minion_stats=GRANTS[KAROV])
        good = GenerateFromPool(1, POOL_ID, QUERIES[TRIUMPH], source_id=1, minion_stats=GRANTS[TRIUMPH])
        for change in ({'source_id': None}, {'destination': 'board'}, {'replacement': False},
                       {'temporary_until_turn': 1}, {'query': replace(QUERIES[TRIUMPH], collectible=None)},
                       {'minion_stats': CreatedMinionGrant(health=1)}, {'shuffle_actor_id': True},
                       {'shuffle_actor_id': 1}, {'destination': 'deck', 'position': 'top', 'shuffle_actor_id': 1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(good, **change)

    def test_wrong_carriers_missing_sources_and_unselected_invalid_branch_fail_atomically(self):
        for name in ('wrong_hand', 'wrong_deck', 'missing_source', 'no_source', 'mixed', 'wrong_branch'):
            g = self.game(hand=(P + name,))
            saved = g.snapshot()
            with self.assertRaises((ResolutionError, ValueError)):
                self.play(g, P + name)
            self.assertEqual(g.snapshot(), saved)

    def test_wait_before_generation_roundtrips_strict_numeric_payload_and_rejects_rehashed_malformed_fields(self):
        g = self.game(hand=(P + 'before',), members=(LEGEND,))
        self.play(g, P + 'before')
        other = self.portable(g)
        for game in (g, other):
            self.resume(game, 'hand')
        self.assertEqual(g.snapshot(), other.snapshot())
        h = self.game(hand=(P + 'before',), members=(LEGEND,))
        self.play(h, P + 'before')
        for field, value in (('double', 1), ('unexpected', 1)):
            saved = deepcopy(h.snapshot())
            row = next(self.nodes(saved['resolution_frame'], 'CreatedMinionStats'))
            row[field] = value
            self.reject(saved)
        saved = deepcopy(h.snapshot())
        del next(self.nodes(saved['resolution_frame'], 'CreatedMinionStats'))['double']
        self.reject(saved)
        saved = deepcopy(h.snapshot())
        next(self.nodes(saved['resolution_frame'], 'SummonStats'))['health'] = 0
        self.reject(saved)
        saved = h.snapshot()
        saved['schema_version'] = SNAPSHOT_SCHEMA_VERSION - 1
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, registry(*self.config))

    def test_owner_sees_fixed_hand_values_while_both_players_keep_generated_deck_identity_private(self):
        g = self.game(hand=(P + 'kill',), board=(KAROV,), members=(LEGEND,))
        self.kill(g)
        own = g.for_player(1).observe()['observation']['players'][0]['hand']
        self.assertTrue(all((x['cost']['amount'], x['attack'], x['max_health']) == (1, 1, 1) for x in own))
        self.assertNotIn(LEGEND, json.dumps(g.for_player(2).observe()))
        self.portable(g)
        h = self.game(members=(EIGHT,))
        self.play(h)
        for seat in (1, 2):
            self.assertNotIn(EIGHT, json.dumps(h.for_player(seat).observe()))
        self.portable(h)


if __name__ == '__main__':
    unittest.main()
