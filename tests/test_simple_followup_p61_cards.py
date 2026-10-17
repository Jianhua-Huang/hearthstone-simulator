"""Actual public entries, immutable choices, native lifecycles and portable waits."""
from dataclasses import asdict
from functools import lru_cache
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.simple_followup_p61_cards import (DANCE, ROAR, WAVES, ANNIHILATION, PAST,
    PRESENT, FUTURE, HOLD, CENARIUS, SPIRIT, ANCIENT, ROOTS, PREFIX, POOL_ID,
    load_batch, register_simple_followup_p61_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice,
    TargetSpec, UseLocation, Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, Destroy, Heal,
    InvokeBehavior, RequestChoice, ReturnToHand, SetStats, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.locations import RefreshLocation
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.targets import canonical_digest

TEST = 'p61.test.'
YETI = 'CORE_CS2_182'
DRAGON, ALL, DEMON, UNKNOWN, IMMUNE, STEALTH, ELUSIVE = (TEST + x for x in
    ('dragon', 'all', 'demon', 'unknown', 'immune', 'stealth', 'elusive'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
MEMBERS = (DEMON, DRAGON, ALL)
CONTEXT = GenerationContext('p61-complete-explicit-fixture', 'experimental')
DEMON_BC, DORMANT, SEEDER, FILLER = (TEST + x for x in ('demon_bc', 'dormant', 'seeder', 'filler'))


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata', lambda r: None):
        r = build_registry()
    present = tuple(cid in r.cards for cid in ROOTS)
    if not any(present): register_simple_followup_p61_cards(r)
    elif not all(present): raise AssertionError('P61 complete ten-definition assembly required')
    register_candidate_pool_metadata(r); r.validate(); return r


def registry(mode=None, members=MEMBERS):
    r = batch_registry()
    for cid, tribe in ((DRAGON, 'dragon'), (ALL, 'all'), (DEMON, 'demon')):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=6, attack=2, health=8,
            metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=(tribe,))))
    for cid, keyword in ((IMMUNE, Keyword.IMMUNE), (STEALTH, Keyword.STEALTH), (ELUSIVE, Keyword.ELUSIVE)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=2, health=8, keywords=(keyword,), metadata=META))
    r.register_behavior(TEST + 'demon_bc', lambda c: (Damage(c.state.players[c.player_id].hero_id, 3, c.source_id),))
    r.register_card(CardDefinition(DEMON_BC, 'Actual recruited demon with unexecuted Battlecry', CardType.MINION,
        cost=7, attack=3, health=6, battlecry=TEST + 'demon_bc',
        metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('demon',))))
    r.register_card(CardDefinition(DORMANT, 'Dormant occupancy', CardType.MINION, health=8, dormant_turns=2, metadata=META))
    from hs_sim.engine.zones import AddToDeck
    r.register_behavior(TEST + 'seed', lambda c: (AddToDeck(c.player_id, DEMON_BC, position='bottom', source_id=c.source_id),))
    r.register_behavior(TEST + 'fill', lambda c: tuple(SummonByCard(c.player_id,
        (SummonEntryMaterial(YETI),), SummonCause.capture(c)) for _ in range(7)))
    r.register_card(CardDefinition(SEEDER, 'Death changes actual bottom three', CardType.MINION,
        health=1, deathrattle=TEST + 'seed', metadata=META))
    r.register_card(CardDefinition(FILLER, 'Death fills actual capacity', CardType.MINION,
        health=1, deathrattle=TEST + 'fill', metadata=META))
    def refresh(c): return (RefreshLocation(c.target_id, c.source_id),)
    def deck_again(c):
        return (MoveCard(CardReference.capture(c.state.entities[c.target_id]), 1, Zone.DECK, source_id=c.source_id),)
    scripts = dict(kill=lambda c: (Destroy(c.target_id, c.source_id),), heal=lambda c: (
        Heal(c.state.players[c.player_id].hero_id, 100, c.source_id),),
        wound=lambda c: (Damage(c.state.players[c.player_id].hero_id, 3, c.source_id),),
        set_stats=lambda c: (SetStats(c.state.players[c.player_id].hero_id, health=40, source_id=c.source_id),),
        buff=lambda c: (Buff(c.target_id, 2, 3, c.source_id),),
        silence=lambda c: (Silence(c.target_id),), refresh=refresh, deck_again=deck_again,
        fail=lambda c: (_ for _ in ()).throw(ResolutionError('P61 deliberate continuation failure')))
    for name, body in scripts.items():
        r.register_behavior(TEST + name, body)
        r.register_card(CardDefinition(TEST + name, name, CardType.SPELL, on_play=TEST + name,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.LOCATION,)) if name == 'refresh' else
                TargetSpec() if name in ('kill', 'buff', 'silence') else None, metadata=META))
    r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 6,
        CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=('demon',)),
        battlecry=False, deathrattle=False, choose_one=False))
    for cid in members:
        if cid not in r.pool_cards: r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID, 'p61-complete-explicit-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode:
        event = ('minion_summoned' if mode == 'annihilation_wait' else
            'choice_selected' if mode in ('dance_leave', 'waves_cycle', 'waves_fill') else 'ability_granted')
        def eligible(c):
            if mode == 'annihilation_wait':
                return any(root.request.cause.source.card_id == ANNIHILATION and
                    any(d.outcome == 'delivered' and d.entity.entity_id == c.event.target_id for d in root.deliveries)
                    for root in c.state.card_summon_history)
            source = c.state.entities.get(c.event.source_id)
            return source is not None and source.card_id == {
                'dance_leave': DANCE, 'waves_cycle': WAVES, 'waves_fill': WAVES, 'grant_wait': SPIRIT}[mode]
        def watch(c):
            if mode == 'dance_leave':
                target = c.state.players[2].board[0]
                return (ReturnToHand(target),)
            if mode == 'waves_cycle':
                target = c.state.players[1].deck[1]
                return (MoveCard(CardReference.capture(c.state.entities[target]), 1, Zone.HAND, source_id=c.source_id),
                    InvokeBehavior(TEST + 'deck_again', c.source_id, 1, target))
            if mode == 'waves_fill': return (AddToHand(c.player_id, YETI, c.source_id),)
            if mode == 'annihilation_wait':
                target = c.state.players[1].deck[-1]
                return (RequestChoice(1, (ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Fail',
                    (InvokeBehavior(TEST + 'fail', c.source_id, 1),)), ChoiceOption('cycle', 'Original final deck slot leaves and returns',
                    (MoveCard(CardReference.capture(c.state.entities[target]), 1, Zone.HAND, source_id=c.source_id),
                     InvokeBehavior(TEST + 'deck_again', c.source_id, 1, target)))), c.source_id),)
            return (RequestChoice(1, (ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Fail',
                (InvokeBehavior(TEST + 'fail', c.source_id, 1),)), ChoiceOption('leave', 'Return original recipient',
                (ReturnToHand(c.event.target_id),))), c.source_id),)
        r.register_behavior(TEST + 'watch', watch); r.register_trigger_condition(TEST + 'eligible', eligible)
        r.register_card(CardDefinition(TEST + 'watch', 'Original public-operation witness', CardType.WEAPON,
            durability=5, metadata=META, limited_triggers=(LimitedTriggerSpec(event, TEST + 'watch', condition_id=TEST + 'eligible'),)))
    r.validate(); return r


@lru_cache(maxsize=None)
def shared_registry(mode, members): return registry(mode, members)


class SimpleFollowupP61Tests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), deck=(YETI,) * 8, mode=None,
            members=MEMBERS, hand_cap=None):
        self.config = mode, members
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
            mana=50, max_mana=50, mana_cap=50, hand_cap=hand_cap, weapon_card_id=TEST + 'watch' if mode else None),
            PlayerSetup('HERO_08', board=enemy, deck=(YETI,) * 8, mana=50, max_mana=50, mana_cap=50)),
            seed=6161, generation_context=CONTEXT), shared_registry(*self.config))

    def first(self, g, cid, zone='hand', player=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None):
        e = self.first(g, cid)
        g.apply(PlayCard(1, e.id, target_id=target, position=len(g.state.players[1].board)
            if e.kind in (CardType.MINION, CardType.LOCATION) else None)); return e.id

    def choose(self, g, key):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(*self.config))
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(*self.config)).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(g.for_player(player).legal_actions()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'behavior_id', 'source_json', 'hero_health_change_history'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_frozen_thirteen_rows_twenty_four_faces_six_edges_and_whole_alex_transfer(self):
        from tools.card_batch import check_face
        data = load_batch(); r = batch_registry()
        self.assertEqual(len(data['cards']), 10); self.assertEqual(len(data['official_observations']), 24)
        self.assertEqual(tuple(x['record']['id'] for x in data['evidence_only']), ('CATA_307', 'CATA_307e'))
        self.assertEqual(len(data['exact_parent_child_links']), 6)
        self.assertEqual(len(data['collectible_candidate_roots']), 8); self.assertEqual(len(data['noncollectible_ids']), 2)
        rows = {x['record']['id']: x['record'] for k in ('cards', 'existing_dependencies', 'evidence_only') for x in data[k]}
        faces = {(o['card_id'], o['locale']): o['face'] for o in data['official_observations']}
        for o in data['official_observations']:
            check_face(rows[o['card_id']], o['face'], o['locale'])
        for edge in data['exact_parent_child_links']:
            face = faces[edge['parent'], edge['locale']]
            self.assertIn(rows[edge['child']]['dbf_id'], face['childIds'])
        self.assertEqual(data['existing_dependency_definition_pins'][ANCIENT], canonical_digest(asdict(r.card(ANCIENT))))
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_annihilation_real_clear_bottom_three_physical_demons_all_and_no_battlecry(self):
        g = self.game(hand=(ANNIHILATION,), board=(YETI, DORMANT), enemy=(YETI,),
            deck=(DEMON, YETI, DEMON_BC, ALL))
        deck = tuple(g.state.players[1].deck); dead = (g.state.players[1].board[0], g.state.players[2].board[0])
        dormant = g.state.players[1].board[1]; mana = g.state.players[1].mana; rng = g._rng.getstate()
        source = self.play(g, ANNIHILATION)
        self.assertEqual(g.state.players[1].mana, mana - 8); self.assertEqual(g._rng.getstate(), rng)
        self.assertEqual(tuple(g.state.players[1].board), (dormant, deck[2], deck[3]))
        self.assertEqual(tuple(g.state.players[1].deck), deck[:2]); self.assertFalse(g.state.players[2].board)
        self.assertTrue(all(g.state.entities[i].zone == Zone.GRAVEYARD for i in dead))
        self.assertIsNotNone(g.state.entities[dormant].dormancy)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 30)
        roots = [r for r in g.state.card_summon_history if r.request.cause.source.entity_id == source]
        self.assertEqual(len(roots), 2)
        self.assertTrue(all(r.request.cause.cast_id is not None for r in roots)); self.portable(g)

    def test_annihilation_reads_actual_bottom_three_after_real_deathrattles(self):
        g = self.game(hand=(ANNIHILATION,), board=(SEEDER,), deck=(DEMON, YETI, DRAGON))
        original = tuple(g.state.players[1].deck); self.play(g, ANNIHILATION)
        self.assertEqual(tuple(g.state.players[1].deck), original)
        recruited = self.first(g, DEMON_BC, 'board'); self.assertNotIn(recruited.id, original)
        self.assertEqual(len(g.state.players[1].board), 1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 30); self.portable(g)

    def test_annihilation_real_deathrattle_capacity_and_empty_deck_keep_original_sources(self):
        g = self.game(hand=(ANNIHILATION,), board=(FILLER,), deck=(DEMON_BC, ALL, DEMON))
        original = tuple(g.state.players[1].deck); self.play(g, ANNIHILATION)
        self.assertEqual(tuple(g.state.players[1].deck), original)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertTrue(all(g.state.entities[i].card_id == YETI for i in g.state.players[1].board)); self.portable(g)
        g = self.game(hand=(ANNIHILATION,), enemy=(YETI,), deck=()); rng = g._rng.getstate()
        self.play(g, ANNIHILATION); self.assertFalse(g.state.players[1].board or g.state.players[2].board)
        self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_annihilation_wait_original_group_stale_reentry_failure_restore_and_replay(self):
        g = self.game(hand=(ANNIHILATION,), deck=(DEMON, DEMON_BC, ALL), mode='annihilation_wait')
        original = tuple(g.state.players[1].deck); epoch = g.state.entities[original[-1]].zone_epoch
        rng = g._rng.getstate(); self.play(g, ANNIHILATION)
        self.assertEqual(tuple(g.state.players[1].board), original[:1]); self.portable(g)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved); self.choose(g, 'cycle')
        self.assertEqual(tuple(g.state.players[1].board), original[:2])
        self.assertEqual(tuple(g.state.players[1].deck), original[2:])
        self.assertEqual(g.state.entities[original[-1]].zone_epoch, epoch + 2)
        self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_dance_real_payment_current_copy_and_waiting_portability(self):
        g = self.game(hand=(DANCE, TEST + 'buff'), board=(YETI,), enemy=(DRAGON,))
        own = self.first(g, YETI, 'board'); enemy = self.first(g, DRAGON, 'board', 2)
        self.play(g, TEST + 'buff', enemy.id); mana = g.state.players[1].mana
        self.play(g, DANCE, own.id); self.assertEqual(g.state.players[1].mana, mana - 5)
        self.assertNotIn(str(own.id), [x.id for x in g.state.pending_choice.options]); self.portable(g)
        self.choose(g, str(enemy.id)); copied = g.state.entities[own.id]
        self.assertEqual((copied.card_id, copied.attack, copied.max_health), (DRAGON, 4, 11))
        self.assertEqual(enemy.controller, 2); self.assertEqual(copied.controller, 1); self.portable(g)

    def test_dance_ordinary_enemy_target_restrictions_and_original_departure(self):
        g = self.game(hand=(DANCE,), board=(YETI,), enemy=(DRAGON, STEALTH, ELUSIVE, IMMUNE))
        own = self.first(g, YETI, 'board'); self.play(g, DANCE, own.id)
        self.assertEqual(tuple(x.entity_id for x in g.state.pending_choice.options), (self.first(g, DRAGON, 'board', 2).id,))
        g = self.game(hand=(DANCE,), board=(YETI,), enemy=(DRAGON,), mode='dance_leave')
        own = self.first(g, YETI, 'board'); enemy = self.first(g, DRAGON, 'board', 2)
        self.play(g, DANCE, enemy.id); self.choose(g, str(own.id))
        enemy = g.state.entities[enemy.id]
        self.assertEqual((enemy.zone, enemy.card_id), (Zone.HAND, DRAGON)); self.portable(g)

    def test_roar_no_dragon_and_current_all_tribe_second_distinct_target(self):
        for dragon in ((), (ALL,)):
            g = self.game(hand=(ROAR,) + dragon, enemy=(YETI, YETI))
            a, b = [g.state.entities[i] for i in g.state.players[2].board]
            self.play(g, ROAR, a.id); self.assertEqual(g.state.entities[a.id].health, 1)
            if dragon:
                self.assertEqual(tuple(x.entity_id for x in g.state.pending_choice.options), (b.id,)); self.portable(g)
                self.choose(g, str(b.id)); self.assertEqual(g.state.entities[b.id].health, 1)
            else: self.assertIsNone(g.state.pending_choice); self.assertEqual(g.state.entities[b.id].health, 5)
            self.portable(g)

    def test_roar_empty_second_pool_and_enemy_legality(self):
        g = self.game(hand=(ROAR, DRAGON), enemy=(YETI, STEALTH, ELUSIVE, IMMUNE))
        target = self.first(g, YETI, 'board', 2); self.play(g, ROAR, target.id)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g.state.entities[target.id].health, 1); self.portable(g)

    def test_waves_original_physical_duplicate_offers_bottom_order_and_no_draw(self):
        g = self.game(hand=(WAVES,), deck=(YETI, YETI, DRAGON, DEMON, ALL))
        original = tuple(g.state.players[1].deck); rng = random.Random(); rng.setstate(g._rng.getstate())
        expected = tuple(rng.sample(original, 3)); self.play(g, WAVES)
        q = g.state.pending_choice; offered = tuple(x.entity_id for x in q.options)
        self.assertEqual(offered, expected); self.assertEqual(len(set(offered)), 3); self.portable(g)
        selected = offered[0]; others = offered[1:]; key = q.options[0].id; self.choose(g, key)
        self.assertIn(selected, g.state.players[1].hand)
        self.assertEqual(tuple(g.state.players[1].deck), tuple(i for i in original if i not in offered) + others)
        self.assertFalse(any(e.kind == 'card_drawn' for e in g.events)); self.portable(g)

    def test_waves_original_offers_do_not_rebind_leave_reentry_and_empty_no_rng(self):
        g = self.game(hand=(WAVES,), deck=(YETI, DRAGON, ALL), mode='waves_cycle')
        original = tuple(g.state.players[1].deck); recycled = g.state.entities[original[1]]; epoch = recycled.zone_epoch
        self.play(g, WAVES); chosen = next(x for x in g.state.pending_choice.options if x.entity_id != recycled.id)
        self.choose(g, chosen.id); recycled = g.state.entities[recycled.id]
        self.assertEqual(recycled.zone_epoch, epoch + 2)
        self.assertEqual(recycled.zone, Zone.DECK); self.portable(g)
        g = self.game(hand=(WAVES,), deck=()); rng = g._rng.getstate(); self.play(g, WAVES)
        self.assertEqual(g._rng.getstate(), rng); self.assertIsNone(g.state.pending_choice); self.portable(g)

    def test_waves_full_hand_uses_native_overflow_without_losing_other_offers(self):
        g = self.game(hand=(WAVES,), deck=(YETI, DRAGON, ALL), hand_cap=1, mode='waves_fill')
        self.play(g, WAVES); q = g.state.pending_choice; chosen = q.options[0].entity_id
        self.choose(g, q.options[0].id); self.assertEqual(g.state.entities[chosen].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].deck), 2); self.portable(g)



    def test_gnomeregan_three_real_faces_cooldown_durability_and_deathrattle(self):
        g = self.game(hand=(PAST, TEST + 'refresh', TEST + 'refresh', TEST + 'kill'), board=(YETI,))
        target = self.first(g, YETI, 'board'); loc_id = self.play(g, PAST); loc = g.state.entities[loc_id]
        g.apply(UseLocation(1, loc_id, target.id)); loc = g.state.entities[loc_id]
        self.assertEqual((loc.card_id, loc.durability), (PRESENT, 2))
        with self.assertRaises(IllegalAction): g.apply(UseLocation(1, loc_id, target.id))
        self.play(g, TEST + 'refresh', loc_id); g.apply(UseLocation(1, loc_id, target.id))
        loc = g.state.entities[loc_id]
        self.assertEqual((loc.card_id, loc.durability), (FUTURE, 1)); self.portable(g)
        self.play(g, TEST + 'refresh', loc_id); g.apply(UseLocation(1, loc_id, target.id))
        loc = g.state.entities[loc_id]; target = g.state.entities[target.id]
        self.assertEqual(loc.zone, Zone.GRAVEYARD); self.assertEqual((target.attack, target.max_health), (10, 8))
        self.assertIn(Keyword.DIVINE_SHIELD, target.keywords)
        self.play(g, TEST + 'kill', target.id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 26); self.portable(g)

    def test_direct_present_and_future_enemy_grant_actual_death_controller(self):
        g = self.game(hand=(PRESENT, TEST + 'kill'), enemy=(YETI,))
        target = self.first(g, YETI, 'board', 2); loc = self.play(g, PRESENT)
        g.apply(UseLocation(1, loc, target.id)); self.assertEqual(g.state.entities[loc].card_id, FUTURE)
        self.play(g, TEST + 'kill', target.id)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 28); self.portable(g)

    def test_hold_actual_discovery_then_next_minion_one_cost_and_current_deck_condition(self):
        for deck, expected in (((), 1), ((YETI,), 6)):
            g = self.game(hand=(HOLD,), deck=deck); loc = self.play(g, HOLD)
            g.apply(UseLocation(1, loc)); q = g.state.pending_choice
            self.assertEqual({x.card_id for x in q.options}, {DEMON, ALL}); self.portable(g)
            self.choose(g, q.options[0].id); e = g.state.entities[g.state.players[1].hand[-1]]
            self.assertEqual(quote_cost(g.state, g.registry, e).amount, expected)
            g.apply(PlayCard(1, e.id, position=len(g.state.players[1].board)))
            self.assertEqual(g.state.entities[e.id].zone, Zone.BOARD); self.portable(g)

    def test_hold_unknown_eligible_full_pool_rolls_back_before_rng(self):
        g = self.game(hand=(HOLD,), members=MEMBERS + (UNKNOWN,)); loc = self.play(g, HOLD)
        saved = g.snapshot(); rng = g._rng.getstate()
        with self.assertRaises(ResolutionError): g.apply(UseLocation(1, loc))
        self.assertEqual(g.snapshot(), saved); self.assertEqual(g._rng.getstate(), rng)

    def test_cenarius_exact_three_native_choices_current_others_and_named_quantity(self):
        g = self.game(hand=(CENARIUS,), board=(YETI,)); yeti = self.first(g, YETI, 'board')
        source = self.play(g, CENARIUS); self.portable(g)
        for key in ('summon', 'buff', 'buff'): self.choose(g, key); self.portable(g)
        ancient = self.first(g, ANCIENT, 'board'); cenarius = g.state.entities[source]; yeti = g.state.entities[yeti.id]
        self.assertEqual((yeti.attack, yeti.max_health), (6, 11)); self.assertEqual((ancient.attack, ancient.max_health), (7, 11))
        self.assertEqual((cenarius.attack, cenarius.max_health), (5, 8)); self.assertIn(Keyword.TAUNT, ancient.keywords)
        self.assertEqual(len([e for e in g.events if e.kind == 'choice_selected']), 3)

    def test_spirit_real_death_chain_same_grant_empty_no_rng_and_controller(self):
        g = self.game(hand=(SPIRIT, TEST + 'kill', TEST + 'kill'), board=(YETI, YETI, YETI))
        a = self.first(g, YETI, 'board'); self.play(g, SPIRIT, a.id)
        a = g.state.entities[a.id]
        self.assertEqual((a.attack, a.max_health), (6, 7)); self.play(g, TEST + 'kill', a.id)
        receiver = next(g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].attack == 6)
        self.play(g, TEST + 'kill', receiver.id); last = g.state.entities[g.state.players[1].board[0]]
        self.assertEqual((last.attack, last.max_health), (6, 7)); self.portable(g)
        g = self.game(hand=(SPIRIT, TEST + 'kill'), enemy=(YETI,)); a = self.first(g, YETI, 'board', 2)
        self.play(g, SPIRIT, a.id); rng = g._rng.getstate(); self.play(g, TEST + 'kill', a.id)
        self.assertEqual(g._rng.getstate(), rng); self.assertFalse(g.state.players[1].board); self.portable(g)

    def test_grant_wait_failure_restores_original_choice_and_departure_skips_captured_buff(self):
        g = self.game(hand=(SPIRIT,), board=(YETI,), mode='grant_wait'); a = self.first(g, YETI, 'board')
        self.play(g, SPIRIT, a.id); self.assertEqual(a.attack, 4); self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved); self.choose(g, 'leave')
        a = g.state.entities[a.id]
        self.assertEqual((a.zone, a.attack, a.max_health), (Zone.HAND, 4, 5)); self.portable(g)


if __name__ == '__main__': unittest.main()
