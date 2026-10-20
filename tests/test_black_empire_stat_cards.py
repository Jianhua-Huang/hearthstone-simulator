"""Real Black Empire actions over native stored cards, health and payment paths."""
from dataclasses import asdict
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.black_empire_stat_cards import (DANCE, SHAPE, RAIN, BRAWLER,
    UNKNOWABLE, ZAKAJZ, SLAMMER, FIRE, BEAR, FREYA, FOX, IMP, TROGG, ROOTS, load_batch)
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice,
    SpellSchool, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import Buff, ChoiceOption, Damage, Destroy, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass, CardMetadata
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from tools.card_batch import check_face

P = 'fixture.black_empire_stats.'
KILL, HURT, GROW, DUMMY, COMBO, SHADOW_A, SHADOW_B, OTHER, POWER, WATCH, UNKNOWN = (
    P+n for n in ('kill', 'hurt', 'grow', 'dummy', 'combo', 'shadow_a',
        'shadow_b', 'other', 'power', 'watch', 'unknown'))
RAVEN, COIN, DAGGER, HERALD, PROTOTYPE, SQUIRE = (
    'KAR_300', 'GAME_005', 'CS2_082', 'BE_169', 'BE_207', 'EX1_008')
CTX = GenerationContext('k326-complete-explicit-fixture', 'experimental')
MINION_META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    registry = build_registry()
    bodies = {KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        HURT: lambda c: (Damage(c.target_id, 1, c.source_id),),
        GROW: lambda c: (Buff(c.target_id, 3, 4, c.source_id),), P+'noop': lambda c: ()}
    for name, body in bodies.items(): registry.register_behavior(name, body)
    for cid in (KILL, HURT, GROW):
        registry.register_card(CardDefinition(cid, 'Explicit test operation', CardType.SPELL,
            on_play=cid, targeting=TargetSpec() if cid == HURT else
                TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    for cid, price, school in ((SHADOW_A, 4, SpellSchool.SHADOW),
            (SHADOW_B, 3, SpellSchool.SHADOW), (OTHER, 2, SpellSchool.FIRE)):
        registry.register_card(CardDefinition(cid, 'Explicit held spell', CardType.SPELL,
            cost=price, spell_school=school, on_play=P+'noop'))
    registry.register_card(CardDefinition(DUMMY, 'Explicit durable probe', CardType.MINION,
        cost=2, attack=1, health=30, metadata=MINION_META))
    registry.register_card(CardDefinition(COMBO, 'Explicit Combo probe', CardType.MINION,
        cost=2, attack=2, health=3, keywords=(Keyword.COMBO,), combo=P+'noop', metadata=MINION_META))
    registry.register_card(CardDefinition(POWER, 'Explicit spell power probe', CardType.MINION,
        health=10, spell_damage=1, metadata=MINION_META))
    members = (HERALD,)
    if mode == 'unknown_pool':
        registry.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 3, registry.card(HERALD).metadata))
        members = (UNKNOWN,)
    registry.register_pool(PoolDefinition('constructed.minions', 'k326-explicit-one-member-v1',
        CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode.startswith('wait_'):
        event_kind = {'wait_draw': 'card_drawn', 'wait_cost': 'cost_modified',
            'wait_health': 'damage_dealt'}[mode]
        def observe(c):
            if mode == 'wait_health':
                source = c.state.entities.get(c.event.source_id)
                if source is None or source.card_id != TROGG: return ()
                options = (ChoiceOption('continue', 'Continue'),
                    ChoiceOption('remove', 'Remove surviving original target', (Destroy(c.event.target_id),)))
            else:
                target = c.state.entities.get(c.event.target_id)
                if target is None or target.controller != c.player_id: return ()
                options = (ChoiceOption('continue', 'Continue'),)
            return (RequestChoice(c.player_id, options, c.source_id),)
        registry.register_behavior(WATCH, observe)
        registry.register_card(CardDefinition(WATCH, 'Explicit continuation observer', CardType.MINION,
            health=20, triggers=(TriggerSpec(event_kind, WATCH),), metadata=MINION_META))
    registry.validate()
    return registry


class BlackEmpireStatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.readers = {}

    def game(self, hand=(), board=(), *, deck=(), enemy_board=(), enemy_hand=(),
            enemy_deck=(), armor=0, mana=10, weapon=None, mode='normal'):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=((WATCH,) if mode.startswith('wait_') else ())+board,
                deck=deck, armor=armor, mana=mana, max_mana=10, weapon_card_id=weapon,
                hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board, deck=enemy_deck,
                mana=10, max_mana=10, hero_power_card_id='HERO_08bp')),
            seed=326, generation_context=CTX), fixture(mode))

    def play(self, game, cid, target=None):
        eid = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == cid)
        game.apply(PlayCard(1, eid, target_id=target)); return eid

    def on_board(self, game, cid, player=1):
        return next(i for i in game.state.players[player].board if game.state.entities[i].card_id == cid)

    def price(self, game, eid): return quote_unselected_cost(game.state, game.registry, game.state.entities[eid]).amount

    def portable(self, game, mode='normal'):
        if mode not in self.readers: self.readers[mode] = fixture.__wrapped__(mode)
        registry = self.readers[mode]; saved = game.snapshot()
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(saved, registry).snapshot(), saved)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), saved)
        for player in (1, 2):
            self.assertNotIn('"rng_state"', json.dumps(game.for_player(player).observe()))
        return Game.from_snapshot(saved, registry)

    def choose(self, game, key='continue'):
        q = game.state.pending_choice
        game.apply(SelectChoice(q.player_id, q.id, (key,)))

    def test_thirteen_full_rows_twenty_six_primary_faces_and_explicit_zero_cost(self):
        data = load_batch(); registry = fixture()
        self.assertEqual(tuple(x['record']['id'] for x in data['cards']), ROOTS)
        self.assertEqual(len(data['official_observations']), 26)
        rows = {x['record']['id']: x['record'] for x in data['cards']}
        for cid, raw in rows.items():
            self.assertEqual(asdict(registry.card(cid).metadata), asdict(metadata_from_record(raw)))
            self.assertEqual(registry.card(cid).cost, 0 if cid == DANCE else raw['cost'])
        for observation in data['official_observations']:
            cid = observation['card_id']
            check_face(rows[cid], observation['face'], observation['locale'],
                {'~GAMEPLAY_ASPROXY_BE_994': ''} if cid == TROGG else None,
                numeric_normalizations={'cost': 0} if cid == DANCE else None)
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_dance_only_hits_undamaged_enemies_and_uses_spell_power_at_zero_mana(self):
        game = self.game((HURT, DANCE), (POWER,), enemy_board=(DUMMY, RAVEN), mana=0)
        wounded = self.on_board(game, DUMMY, 2); healthy = self.on_board(game, RAVEN, 2)
        self.play(game, HURT, wounded)
        self.play(game, DANCE)
        self.assertEqual(game.state.entities[wounded].health, 29)
        self.assertEqual(game.state.entities[healthy].zone, Zone.GRAVEYARD)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 28)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 30)

    def test_shape_draws_original_minion_before_buffing_all_held_beasts(self):
        game = self.game((SHAPE, RAVEN), deck=(RAVEN, OTHER))
        original = next(i for i in game.state.players[1].deck if game.state.entities[i].card_id == RAVEN)
        self.play(game, SHAPE)
        self.assertIn(original, game.state.players[1].hand)
        for i in game.state.players[1].hand:
            self.assertEqual((game.state.entities[i].attack, game.state.entities[i].health), (4, 4))
        self.assertEqual(len(game.state.players[1].deck), 1)

    def test_shape_no_minion_match_still_buffs_hand_without_fatigue(self):
        game = self.game((SHAPE, RAVEN), deck=(OTHER,))
        self.play(game, SHAPE)
        raven = game.state.entities[game.state.players[1].hand[0]]
        self.assertEqual((raven.attack, raven.health), (4, 4))
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 30)
        self.assertEqual(len(game.state.players[1].deck), 1)

    def test_rain_requeries_after_reborn_and_empty_remaining_packets_do_not_draw_rng(self):
        game = self.game((RAIN,), enemy_board=(PROTOTYPE,))
        expected = Random(); expected.setstate(game._rng.getstate())
        expected.choice((0,)); expected.choice((0,))
        self.play(game, RAIN)
        self.assertEqual(game.state.players[2].board, [])
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 30)
        self.assertEqual(game._rng.getstate(), expected.getstate())

    def test_rain_applies_spell_power_to_all_five_sequential_packets(self):
        game = self.game((RAIN,), (POWER,), enemy_board=(DUMMY,))
        target = self.on_board(game, DUMMY, 2); self.play(game, RAIN)
        self.assertEqual(game.state.entities[target].health, 15)

    def test_brawler_checks_inclusive_current_armor_and_can_charge_hero(self):
        for armor, attack in ((9, 6), (10, 10)):
            with self.subTest(armor=armor):
                game = self.game((BRAWLER,), armor=armor); source = self.play(game, BRAWLER)
                self.assertEqual(game.state.entities[source].attack, attack)
                game.apply(Attack(1, source, game.state.players[2].hero_id))
                self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 30-attack)

    def test_unknowable_sets_only_own_held_combo_minions_and_preserves_cost(self):
        game = self.game((UNKNOWABLE, COMBO, DUMMY), deck=(COMBO,), enemy_hand=(COMBO,))
        combo = game.state.players[1].hand[1]; other = game.state.players[1].hand[2]
        self.play(game, UNKNOWABLE)
        self.assertEqual((game.state.entities[combo].attack, game.state.entities[combo].health, self.price(game, combo)), (6, 6, 2))
        for eid in (other, game.state.players[1].deck[0], game.state.players[2].hand[0]):
            self.assertNotEqual((game.state.entities[eid].attack, game.state.entities[eid].health), (6, 6))

    def test_zakajz_updates_own_hand_and_deck_but_not_weapons_board_or_opponent(self):
        game = self.game((ZAKAJZ, DUMMY, OTHER, DAGGER), (DUMMY,), deck=(DUMMY, OTHER, DAGGER),
            enemy_hand=(DUMMY, OTHER), enemy_deck=(DUMMY, OTHER))
        ids = tuple(game.state.players[1].hand[1:]+game.state.players[1].deck)
        before = {i: self.price(game, i) for i in ids}
        enemies = {i: self.price(game, i) for i in game.state.players[2].hand+game.state.players[2].deck}
        self.play(game, ZAKAJZ)
        for i in ids:
            delta = {CardType.MINION: -1, CardType.SPELL: 1, CardType.WEAPON: 0}[game.state.entities[i].kind]
            self.assertEqual(self.price(game, i), before[i]+delta)
        self.assertEqual({i: self.price(game, i) for i in enemies}, enemies)
        self.assertEqual(game.state.entities[self.on_board(game, DUMMY)].base_cost, 2)

    def test_zakajz_repeated_edits_stack_with_minion_zero_floor(self):
        game = self.game((ZAKAJZ, ZAKAJZ, RAVEN, OTHER)); raven, spell = game.state.players[1].hand[-2:]
        self.play(game, ZAKAJZ); self.play(game, ZAKAJZ)
        self.assertEqual((self.price(game, raven), self.price(game, spell)), (0, 4))

    def test_slammer_uses_live_enemy_count_payment_rush_and_two_attacks(self):
        game = self.game((SLAMMER, KILL), (DUMMY,), enemy_board=(DUMMY, RAVEN))
        source = game.state.players[1].hand[0]
        self.assertEqual(self.price(game, source), 6)
        self.play(game, KILL, self.on_board(game, RAVEN, 2)); self.assertEqual(self.price(game, source), 7)
        self.play(game, SLAMMER); self.assertEqual(game.state.players[1].mana, 3)
        with self.assertRaises(IllegalAction): game.apply(Attack(1, source, game.state.players[2].hero_id))
        target = self.on_board(game, DUMMY, 2)
        game.apply(Attack(1, source, target)); game.apply(Attack(1, source, target))
        self.assertEqual(game.state.entities[target].health, 18)

    def test_fire_deals_damage_then_summons_original_pool_body_without_battlecry(self):
        game = self.game((FIRE,), weapon=DAGGER)
        self.play(game, FIRE, game.state.players[2].hero_id)
        body = game.state.entities[self.on_board(game, HERALD)]
        self.assertEqual((body.attack, body.health), (3, 3))
        self.assertNotIn(Keyword.RUSH, body.keywords)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 27)
        self.assertEqual(game.state.players[1].mana, 7)

    def test_unknown_eligible_fire_summon_rolls_back_prior_damage_payment_and_rng(self):
        game = self.game((FIRE,), mode='unknown_pool'); saved = game.snapshot()
        with self.assertRaises(ResolutionError): self.play(game, FIRE, game.state.players[2].hero_id)
        self.assertEqual(game.snapshot(), saved)

    def test_bear_uses_buffed_current_attack_and_expires_at_turn_end(self):
        game = self.game((KILL, BEAR), (PROTOTYPE,))
        self.play(game, KILL, self.on_board(game, PROTOTYPE)); source = self.play(game, BEAR)
        hero = game.state.players[1].hero_id
        self.assertEqual(game.state.entities[hero].attack, game.state.entities[source].attack)
        self.assertEqual(game.state.entities[hero].attack, 3)
        game.apply(EndTurn(1)); self.assertEqual(game.state.entities[hero].attack, 0)

    def test_freya_doubles_all_stored_beasts_without_touching_board_or_opponent(self):
        game = self.game((FREYA, RAVEN, DUMMY), (RAVEN,), deck=(RAVEN, DUMMY), enemy_hand=(RAVEN,))
        beasts = [game.state.players[1].hand[1], game.state.players[1].deck[0]]
        self.play(game, FREYA)
        for eid in beasts: self.assertEqual((game.state.entities[eid].attack, game.state.entities[eid].health), (4, 4))
        for eid in (self.on_board(game, RAVEN), game.state.players[2].hand[0]):
            self.assertEqual((game.state.entities[eid].attack, game.state.entities[eid].health), (2, 2))
        self.assertEqual(game.state.entities[game.state.players[1].deck[1]].attack, 1)

    def test_freya_doubles_existing_current_beast_buffs(self):
        game = self.game((SHAPE, FREYA, RAVEN), deck=(RAVEN,))
        self.play(game, SHAPE); self.play(game, FREYA)
        for eid in game.state.players[1].hand:
            self.assertEqual((game.state.entities[eid].attack, game.state.entities[eid].health), (8, 8))

    def test_fox_draws_original_death_attack_not_printed_attack(self):
        game = self.game((GROW, KILL), (FOX,), deck=(COIN,)*5)
        source = self.on_board(game, FOX); self.play(game, GROW, source); self.play(game, KILL, source)
        self.assertEqual(len(game.state.players[1].hand), 5)
        self.assertEqual(game.state.players[1].deck, [])
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 30)

    def test_imp_discounts_exactly_one_original_shadow_spell_and_empty_match_skips_rng(self):
        game = self.game((KILL, SHADOW_A, SHADOW_B, OTHER), (IMP,), enemy_hand=(SHADOW_A,))
        targets = game.state.players[1].hand[1:3]; other = game.state.players[1].hand[3]
        before = [self.price(game, i) for i in targets]
        self.play(game, KILL, self.on_board(game, IMP))
        self.assertEqual(sorted(a-self.price(game, i) for a, i in zip(before, targets)), [0, 2])
        self.assertEqual(self.price(game, other), 2)
        self.assertEqual(self.price(game, game.state.players[2].hand[0]), 4)
        empty = self.game((KILL, OTHER), (IMP,)); rng = empty._rng.getstate()
        self.play(empty, KILL, self.on_board(empty, IMP)); self.assertEqual(empty._rng.getstate(), rng)

    def test_trogg_original_survival_reward_handles_survivor_fatal_and_divine_shield(self):
        for target_card, rewarded in ((DUMMY, True), (RAVEN, False), (SQUIRE, True)):
            with self.subTest(target=target_card):
                game = self.game((TROGG,), enemy_board=(target_card,))
                source = self.play(game, TROGG, self.on_board(game, target_card, 2))
                self.assertEqual(game.state.entities[source].max_health, 14 if rewarded else 8)
                self.assertEqual(Keyword.TAUNT in game.state.entities[source].keywords, rewarded)

    def test_shape_draw_wait_restores_before_one_hand_buff_batch(self):
        game = self.game((SHAPE, RAVEN), deck=(RAVEN,), mode='wait_draw')
        self.play(game, SHAPE); self.assertIsNotNone(game.state.pending_choice)
        game = self.portable(game, 'wait_draw'); self.choose(game)
        for eid in game.state.players[1].hand:
            self.assertEqual((game.state.entities[eid].attack, game.state.entities[eid].health), (4, 4))
        self.portable(game, 'wait_draw')

    def test_zakajz_cost_waits_restore_the_original_physical_batch_without_duplicate_edits(self):
        game = self.game((ZAKAJZ, DUMMY, OTHER), deck=(DUMMY, OTHER), mode='wait_cost')
        ids = game.state.players[1].hand[1:]+game.state.players[1].deck[:]
        self.play(game, ZAKAJZ); self.assertIsNotNone(game.state.pending_choice)
        game = self.portable(game, 'wait_cost'); waits = 0
        while game.state.pending_choice:
            self.choose(game); waits += 1; self.assertLessEqual(waits, 4)
        self.assertEqual(waits, 4)
        self.assertEqual([self.price(game, i) for i in ids], [1, 3, 1, 3])
        self.portable(game, 'wait_cost')

    def test_trogg_health_wait_preserves_accepted_survival_when_reaction_removes_target(self):
        game = self.game((TROGG,), enemy_board=(DUMMY,), mode='wait_health')
        target = self.on_board(game, DUMMY, 2); source = self.play(game, TROGG, target)
        self.assertIsNotNone(game.state.pending_choice)
        game = self.portable(game, 'wait_health'); self.choose(game, 'remove')
        self.assertEqual(game.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual(game.state.entities[source].max_health, 14)
        self.assertIn(Keyword.TAUNT, game.state.entities[source].keywords)
        self.portable(game, 'wait_health')


if __name__ == '__main__': unittest.main()
