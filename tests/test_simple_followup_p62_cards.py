"""Real entries, original material, strict source labels and independent cached readers."""
from dataclasses import asdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards import simple_followup_p62_cards as cards
from hs_sim.cards.simple_followup_p62_cards import (FRAME, TYPHOON, PRAYER, RITUAL, TICK,
    SANDS, COIN, STONE, TREANT, DRAGON, WHELP, RAPTOR, ROOTS, PREFIX, POOL_ID, load_batch,
    register_simple_followup_p62_cards)
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice, TargetSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, Destroy,
    InvokeBehavior, RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import AddToDeck, CardReference
from hs_sim.targets import canonical_digest

TEST = 'p62.test.'
YETI = 'CORE_CS2_182'
A, B, ALL, MAGE, PRIEST, UNKNOWN, UNKNOWN_SPELL, SEEDER = (TEST + i for i in
    ('a', 'b', 'all', 'mage', 'priest', 'unknown', 'unknown_spell', 'seeder'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
MEMBERS = (A, B, ALL, MAGE, PRIEST)
CONTEXT = GenerationContext('p62-complete-explicit-fixture', 'experimental')
SOURCE_PIN = hashlib.sha256(Path(__file__).read_bytes() + Path(cards.__file__).read_bytes()
    + cards.BATCH_PATH.read_bytes()).hexdigest()


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata', lambda r: None): r = build_registry()
    present = tuple(i in r.cards for i in ROOTS)
    if not any(present): register_simple_followup_p62_cards(r)
    elif not all(present): raise AssertionError('P62 requires complete assigned assembly')
    register_candidate_pool_metadata(r); r.validate(); return r


def registry(mode=None, members=MEMBERS):
    r = batch_registry()
    for cid, tribes in ((A, ('dragon',)), (B, ('beast',)), (ALL, ('all',))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=6, attack=3, health=8,
            metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=tribes)))
    r.register_behavior(TEST + 'noop', lambda c: ())
    for cid, cls in ((MAGE, CardClass.MAGE), (PRIEST, CardClass.PRIEST)):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=2, on_play=TEST + 'noop',
            metadata=CardMetadata(True, (cls,), Rarity.COMMON, tribes=())))
    r.register_behavior(TEST + 'seed', lambda c: (AddToDeck(c.player_id, A, position='bottom', source_id=c.source_id),))
    r.register_card(CardDefinition(SEEDER, 'Death adds a current deck candidate', CardType.MINION, health=1,
        deathrattle=TEST + 'seed', metadata=META))
    r.register_card(CardDefinition(TEST + 'power', 'Spell Damage2', CardType.MINION, health=8, spell_damage=2, metadata=META))
    def reenter(c):
        return (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]), 1, cause=SummonCause.capture(c)),)
    scripts = dict(kill=lambda c: (Destroy(c.target_id, c.source_id),), buff=lambda c: (Buff(c.target_id, 2, 3, c.source_id),),
        wound=lambda c: (Damage(c.state.players[1].hero_id, 3, c.source_id),), reenter=reenter,
        fail=lambda c: (_ for _ in ()).throw(ResolutionError('P62 deliberate continuation failure')))
    for name, body in scripts.items():
        r.register_behavior(TEST + name, body)
        r.register_card(CardDefinition(TEST + name, name, CardType.SPELL, on_play=TEST + name,
            targeting=TargetSpec() if name in ('kill', 'buff') else None, metadata=META))
    for cid, kind, cls, cost in ((UNKNOWN, CardType.MINION, CardClass.NEUTRAL, 6),
            (UNKNOWN_SPELL, CardType.SPELL, CardClass.MAGE, 2)):
        r.register_pool_card(PoolCard(cid, kind, cost,
            CardMetadata(True, (cls,), Rarity.COMMON, tribes=()), battlecry=False, deathrattle=False, choose_one=False))
    for cid in members:
        if cid not in r.pool_cards: r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID, 'p62-finite-complete-v1', CONTEXT.target_id, CONTEXT.mode,
        tuple(PoolMember(cid) for cid in members), complete=True))
    if mode:
        event = {'shuffle': 'card_shuffled', 'frame': 'minion_died', 'discard': 'card_discarded'}[mode]
        def eligible(c):
            if mode == 'shuffle': return any(row.source is not None and row.source.card_id == TYPHOON for row in c.state.deck_shuffle_history)
            return c.event.player_id == 2
        def watch(c):
            if mode == 'discard': return (AddToHand(2, YETI, c.source_id),)
            options = [ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Fail', (InvokeBehavior(TEST + 'fail', c.source_id, 1),))]
            if mode == 'shuffle':
                target = c.state.players[1].board[0]
                options.append(ChoiceOption('cycle', 'Original remaining target leaves and reenters',
                    (ReturnToHand(target), InvokeBehavior(TEST + 'reenter', c.source_id, 1, target))))
            return (RequestChoice(1, tuple(options), c.source_id),)
        r.register_trigger_condition(TEST + 'eligible', eligible); r.register_behavior(TEST + 'watch', watch)
        r.register_card(CardDefinition(TEST + 'watch', 'Actual native checkpoint witness', CardType.WEAPON, durability=5,
            metadata=META, limited_triggers=(LimitedTriggerSpec(event, TEST + 'watch', condition_id=TEST + 'eligible'),)))
    return r


@lru_cache(maxsize=None)
def fixture_registry(mode, members, role, source_pin):
    if role not in ('writer', 'reader') or source_pin != SOURCE_PIN: raise AssertionError('Incomplete immutable fixture key')
    r = registry(mode, members); r.freeze(); return r


class SimpleFollowupP62Tests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), deck=(YETI,) * 12, enemy_hand=(), enemy_deck=(YETI,) * 8,
            mode=None, members=MEMBERS, hand_cap=None):
        self.config = mode, members
        writer = fixture_registry(mode, members, 'writer', SOURCE_PIN)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
            mana=30, max_mana=30, mana_cap=40, hand_cap=hand_cap, weapon_card_id=TEST + 'watch' if mode else None),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=enemy_deck,
                mana=30, max_mana=30, mana_cap=40)), seed=6262, generation_context=CONTEXT), writer)

    def first(self, g, cid, zone='hand', player=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None):
        e = self.first(g, cid); g.apply(PlayCard(1, e.id, target_id=target,
            position=len(g.state.players[1].board) if e.kind == CardType.MINION else None)); return e.id

    def choose(self, g, key):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        reader = fixture_registry(*self.config, 'reader', SOURCE_PIN)
        self.assertIsNot(g.registry, reader); self.assertEqual(g.registry.fingerprint(), reader.fingerprint())
        saved = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        self.assertIsNot(g.state, other.state)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(g.for_player(player).legal_actions()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'behavior_id', 'source_json', 'death_history'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_full_twelve_new_rows_twenty_three_raws_thirty_eight_strict_faces_and_twenty_two_edges(self):
        from tools.card_batch import check_face
        d = load_batch(); rows = {x['record']['id']: x['record'] for x in d['cards'] + d['evidence_only']}
        self.assertEqual(len(rows), 23); self.assertEqual(len(d['official_observations']), 38)
        self.assertEqual(len(d['collectible_candidate_roots']), 2); self.assertEqual(len(d['noncollectible_ids']), 10)
        for o in d['official_observations']:
            check_face(rows[o['card_id']], o['face'], o['locale'], numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
        parents = {(o['card_id'], o['locale']): o for o in d['parent_observations']}
        self.assertEqual(len(d['exact_parent_child_links']), 22)
        for edge in d['exact_parent_child_links']:
            self.assertEqual(rows[edge['child']]['dbf_id'], edge['dbf_id'])
            self.assertIn(edge['dbf_id'], parents[edge['parent'], edge['locale']]['face']['childIds'])
        self.assertEqual(set(d['raw_only_parent_ids']), {'EDR_460', 'EDR_461', 'END_009', 'CATA_132'})
        self.assertFalse(d['parents_implemented'] or d['formal_pool_complete'] or d['cn_calibrated'])

    def test_old_complete_definitions_and_pool_rows_remain_exact(self):
        before, after = build_registry(), batch_registry()
        self.assertEqual(set(after.cards) - set(before.cards), set(ROOTS) - set(before.cards))
        for cid, card in before.cards.items(): self.assertEqual(card, after.card(cid))
        for cid, card in before.pool_cards.items(): self.assertEqual(card, after.pool_card(cid))

    def test_frame_actual_pair_current_deathrattle_deck_then_original_selected_card_on_top(self):
        g = self.game(hand=(FRAME,), enemy=(SEEDER, B), enemy_deck=(MAGE,))
        mana = g.state.players[1].mana; self.play(g, FRAME)
        self.assertFalse(g.state.players[2].board); self.assertEqual(g.state.players[1].mana, mana - 5)
        q = g.state.pending_choice; self.assertEqual(tuple(o.card_id for o in q.options), (A,)); self.portable(g)
        actual = self.first(g, A, 'deck', 2).id; self.choose(g, q.options[0].id)
        self.assertEqual(g.state.players[2].deck[0], actual); self.portable(g)

    def test_frame_duplicate_physical_deck_choices_and_empty_no_rng(self):
        g = self.game(hand=(FRAME,), enemy_deck=(A, A, MAGE)); original = tuple(g.state.players[2].deck)
        self.play(g, FRAME); q = g.state.pending_choice
        self.assertEqual(len(q.options), 2); self.assertEqual({o.card_id for o in q.options}, {A})
        self.assertTrue(all(o.entity_id is None for o in q.options))
        self.choose(g, q.options[1].id); self.assertEqual(tuple(g.state.players[2].deck), (original[1], original[0], original[2]))
        self.portable(g)
        g = self.game(hand=(FRAME,), enemy_deck=()); rng = g._rng.getstate(); self.play(g, FRAME)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_frame_real_death_wait_failure_restores_pair_and_continues_discovery(self):
        g = self.game(hand=(FRAME,), enemy=(A, B, YETI), enemy_deck=(A,), mode='frame')
        self.play(g, FRAME); self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved); self.choose(g, 'ok'); self.portable(g)
        self.choose(g, g.state.pending_choice.options[0].id)
        self.assertEqual(len(g.state.players[2].board), 1); self.portable(g)

    def test_typhoon_original_owners_uniform_recipients_semantic_shuffle_and_reset(self):
        g = self.game(hand=(TYPHOON, TEST + 'buff'), board=(A,), enemy=(B,), deck=(YETI,), enemy_deck=(YETI,))
        a = self.first(g, A, 'board'); b = self.first(g, B, 'board', 2); self.play(g, TEST + 'buff', a.id)
        rng = random.Random(); rng.setstate(g._rng.getstate()); expected = {p: list(g.state.players[p].deck) for p in (1, 2)}
        recipients = {}
        for i in (a.id, b.id):
            p = rng.sample((1, 2), 1)[0]; recipients[i] = p; expected[p].insert(rng.randrange(len(expected[p]) + 1), i)
        source = self.play(g, TYPHOON)
        self.assertEqual(g._rng.getstate(), rng.getstate())
        for p in (1, 2): self.assertEqual(g.state.players[p].deck, expected[p]); self.assertFalse(g.state.players[p].board)
        self.assertEqual((g.state.entities[a.id].owner, g.state.entities[b.id].owner), (1, 2))
        for i in (a.id, b.id): self.assertEqual(g.state.entities[i].controller, recipients[i])
        self.assertEqual((g.state.entities[a.id].attack, g.state.entities[a.id].max_health), (3, 8))
        self.assertEqual(len(g.state.deck_shuffle_history), 2)
        self.assertTrue(all(x.actor_id == 1 and x.source.entity_id == source for x in g.state.deck_shuffle_history)); self.portable(g)

    def test_typhoon_wait_original_remaining_target_reentry_skips_without_extra_rng(self):
        g = self.game(hand=(TYPHOON,), board=(YETI, A), mode='shuffle', deck=(), enemy_deck=())
        target = g.state.players[1].board[1]; rng = random.Random(); rng.setstate(g._rng.getstate())
        rng.sample((1, 2), 1); rng.randrange(1)
        self.play(g, TYPHOON); self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved); self.choose(g, 'cycle')
        self.assertEqual(tuple(g.state.players[1].board), (target,)); self.assertEqual(g._rng.getstate(), rng.getstate())
        self.assertEqual(len(g.state.deck_shuffle_history), 1); self.portable(g)

    def test_prayer_printed_lifesteal_spell_damage_and_real_target(self):
        g = self.game(hand=(PRAYER, TEST + 'wound'), board=(TEST + 'power',), enemy=(A,))
        target = self.first(g, A, 'board', 2).id; self.play(g, TEST + 'wound'); source = self.play(g, PRAYER, target)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 30)
        hit = next(health_result(e) for e in g.events if e.kind == 'health_resolved' and e.target_id == target)
        self.assertEqual((hit.modified_amount, hit.damage_kind, hit.source_id), (8, 'spell', source))
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD); self.portable(g)

    def test_ritual_actual_two_six_cost_summons_capacity_and_original_cause(self):
        for board, added in (((), 2), ((YETI,) * 6, 1)):
            g = self.game(hand=(RITUAL,), board=board); source = self.play(g, RITUAL)
            new = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id != YETI]
            self.assertEqual(len(new), added); self.assertTrue(all(e.base_cost == 6 for e in new))
            self.assertTrue(any(r.request.cause.source.entity_id == source for r in g.state.card_summon_history)); self.portable(g)

    def test_generation_complete_unknown_eligible_candidate_rolls_back_before_rng(self):
        for cid, unknown in ((RITUAL, UNKNOWN), (SANDS, UNKNOWN_SPELL)):
            g = self.game(hand=(cid,), members=MEMBERS + (unknown,)); saved = g.snapshot(); rng = g._rng.getstate()
            with self.assertRaises(ResolutionError): self.play(g, cid)
            self.assertEqual(g.snapshot(), saved); self.assertEqual(g._rng.getstate(), rng)

    def test_sands_current_class_spell_discovery_waiting_and_native_delivery(self):
        g = self.game(hand=(SANDS,)); self.play(g, SANDS); q = g.state.pending_choice
        self.assertEqual(tuple(o.card_id for o in q.options), (MAGE,)); self.portable(g)
        self.choose(g, q.options[0].id); self.assertEqual(self.first(g, MAGE).kind, CardType.SPELL); self.portable(g)

    def test_grimy_coin_zero_cost_real_temporary_mana_and_spell_damage_empty_pool(self):
        for enemy in ((), (A,)):
            g = self.game(hand=(COIN,), board=(TEST + 'power',), enemy=enemy); mana = g.state.players[1].mana
            rng = g._rng.getstate(); source = self.play(g, COIN)
            self.assertEqual(g.state.players[1].mana, mana + 1)
            if enemy:
                target = self.first(g, A, 'board', 2); self.assertEqual(target.health, 4)
                self.assertTrue(any(e.source_id == source and e.kind == 'health_resolved' for e in g.events))
            else: self.assertEqual(g._rng.getstate(), rng)
            self.portable(g)

    def test_oathstone_all_friendly_dragon_and_all_deaths_new_bodies_no_opponent(self):
        g = self.game(hand=(STONE,) + (TEST + 'kill',) * 3, board=(A, ALL, YETI), enemy=(A,))
        a = self.first(g, A, 'board').id; all_id = self.first(g, ALL, 'board').id; enemy = self.first(g, A, 'board', 2).id
        for i in (a, all_id, enemy): self.play(g, TEST + 'kill', i)
        self.play(g, STONE); actual = [g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual([e.card_id for e in actual], [YETI, A, ALL])
        self.assertTrue(all(e.id not in (a, all_id, enemy) for e in actual)); self.portable(g)

    def test_oathstone_empty_original_death_inventory_no_rng(self):
        g = self.game(hand=(STONE,)); rng = g._rng.getstate(); self.play(g, STONE)
        self.assertEqual(g._rng.getstate(), rng); self.assertFalse(g.state.players[1].board); self.portable(g)

    def test_tick_actual_battlecry_effective_hand_capacity_then_original_opponent_discards(self):
        g = self.game(hand=(TICK, TEST + 'kill'), enemy_hand=(A, MAGE), hand_cap=4, mode='discard')
        original = tuple(g.state.players[2].hand); source = self.play(g, TICK)
        self.assertEqual(len(g.state.players[1].hand), 4); self.assertEqual(len(g.state.draw_history), 3)
        self.play(g, TEST + 'kill', source)
        self.assertTrue(all(g.state.entities[i].zone == Zone.GRAVEYARD for i in original))
        self.assertEqual(len(g.state.players[2].hand), 1)
        self.assertEqual(self.first(g, YETI, player=2).card_id, YETI); self.portable(g)

    def test_four_actual_named_minions_printed_stats_keywords_and_rush(self):
        expected = {TREANT: (2, 2), DRAGON: (8, 8), WHELP: (3, 3), RAPTOR: (2, 1)}
        for cid, stats in expected.items():
            g = self.game(hand=(cid,), enemy=(YETI,)); source = self.play(g, cid); e = g.state.entities[source]
            self.assertEqual((e.attack, e.max_health), stats)
            if cid == WHELP: self.assertIn(Keyword.TAUNT, e.keywords)
            if cid == RAPTOR:
                with self.assertRaises(IllegalAction): g.apply(Attack(1, source, g.state.players[2].hero_id))
                g.apply(Attack(1, source, g.state.players[2].board[0]))
            self.portable(g)

    def test_cached_readers_are_distinct_frozen_and_wrong_registry_is_constructed_separately(self):
        g = self.game(hand=(COIN,)); reader = fixture_registry(*self.config, 'reader', SOURCE_PIN)
        self.assertIsNot(g.registry, reader); self.assertIs(reader, fixture_registry(*self.config, 'reader', SOURCE_PIN))
        with self.assertRaises(ValueError): reader.register_card(CardDefinition(TEST + 'forbidden', 'Forbidden', CardType.MINION, health=1))
        wrong = registry(None, (A,)); wrong.freeze(); self.assertIsNot(wrong, reader)
        with self.assertRaises(ValueError): Game.from_snapshot(g.snapshot(), wrong)
        self.portable(g)


if __name__ == '__main__': unittest.main()
