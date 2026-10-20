"""Black Empire followups through original casts, attacks and physical entries."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.black_empire_followup_cards import (DANCER, RECKONING, HALLS,
    RIFT, NEGOTIATOR, DEVOURER, HAMMER, TANK, BOARS, BLOOM, HUNTER, TIGER,
    BLESSING, FINAL, ELEMENTAL, BOAR, PLANT, BUG, ROOTS, DEPENDENCIES, load_batch)
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice,
    SpellSchool, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (ChoiceOption, Damage, Destroy, GainArmor,
    GrantKeyword, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass, CardMetadata, Rarity
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from tools.card_batch import check_face

P = 'fixture.black_empire_followups.'
KILL, HURT, ARMOR, HIT, FATAL, SHIELD, DUMMY, SHADOW, OUTCARD, WRONG, POWER, WATCH, UNKNOWN = (
    P+n for n in ('kill', 'hurt', 'armor', 'hit', 'fatal', 'shield', 'dummy',
        'shadow', 'outcast', 'wrong', 'power', 'watch', 'unknown'))
COIN, RAVEN, DAGGER, PROTOTYPE, BRAWLER = 'GAME_005', 'KAR_300', 'CS2_082', 'BE_207', 'BE_560'
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())
CTX = GenerationContext('k327-complete-explicit-fixture', 'experimental')


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    registry = build_registry()
    def own_hunter(c):
        return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == HUNTER)
    bodies = {KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        HURT: lambda c: (Damage(c.state.players[c.player_id].hero_id, 12, c.source_id),),
        ARMOR: lambda c: (GainArmor(c.player_id, 10),),
        HIT: lambda c: (Damage(own_hunter(c), 1, c.source_id),),
        FATAL: lambda c: (Damage(own_hunter(c), 20, c.source_id),),
        SHIELD: lambda c: (GrantKeyword(own_hunter(c), Keyword.DIVINE_SHIELD, c.source_id),),
        SHADOW: lambda c: (Damage(c.state.players[3-c.player_id].hero_id, 1, c.source_id),),
        P+'noop': lambda c: ()}
    for cid, body in bodies.items(): registry.register_behavior(cid, body)
    for cid in (KILL, HURT, ARMOR, HIT, FATAL, SHIELD):
        registry.register_card(CardDefinition(cid, 'Explicit test operation', CardType.SPELL,
            metadata=META, on_play=cid, targeting=TargetSpec(zones=(Zone.BOARD,),
                kinds=(CardType.MINION,)) if cid == KILL else None))
    for cid, price, school, keywords in ((SHADOW, 3, SpellSchool.SHADOW, ()),
            (OUTCARD, 1, SpellSchool.FEL, (Keyword.OUTCAST,)), (WRONG, 4, SpellSchool.FIRE, ())):
        registry.register_card(CardDefinition(cid, 'Explicit generated probe', CardType.SPELL,
            cost=price, spell_school=school, keywords=keywords, metadata=replace(META, collectible=True),
            on_play=SHADOW if cid == SHADOW else P+'noop'))
        registry.register_pool_card(PoolCard.from_definition(registry.card(cid)))
    registry.register_card(CardDefinition(DUMMY, 'Explicit durable probe', CardType.MINION,
        attack=1, health=30, metadata=META))
    registry.register_card(CardDefinition(POWER, 'Explicit spell power probe', CardType.MINION,
        health=10, spell_damage=1, metadata=META))
    members = (SHADOW, OUTCARD, WRONG)
    minions = (BRAWLER,)
    if mode == 'unknown_spell':
        registry.register_pool_card(PoolCard(UNKNOWN, CardType.SPELL, 3,
            replace(META, collectible=True), spell_school=SpellSchool.SHADOW))
        members = (UNKNOWN, WRONG)
    elif mode == 'unknown_minion':
        registry.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 8, registry.card(BRAWLER).metadata))
        minions = (UNKNOWN,)
    for pool_id, ids in (('constructed.cards', members), ('constructed.minions', minions)):
        registry.register_pool(PoolDefinition(pool_id, 'k327-explicit-full-fixture-v1',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in ids), complete=True))
    if mode.startswith('wait_'):
        event_kind = {'wait_split': 'damage_dealt', 'wait_boars': 'minion_summoned',
            'wait_shuffle': 'card_added_to_deck'}[mode]
        def observe(c):
            eid = c.event.source_id if mode == 'wait_split' else c.event.target_id
            entity = c.state.entities.get(eid)
            if entity is None or entity.card_id != {'wait_split': HALLS,
                    'wait_boars': BOAR, 'wait_shuffle': FINAL}[mode]: return ()
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),), c.source_id),)
        registry.register_behavior(WATCH, observe)
        registry.register_card(CardDefinition(WATCH, 'Explicit continuation observer', CardType.MINION,
            health=20, metadata=META, triggers=(TriggerSpec(event_kind, WATCH),)))
    registry.validate()
    return registry


class BlackEmpireFollowupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.readers = {}

    def game(self, hand=(), board=(), *, deck=None, enemy_board=(), enemy_weapon=None,
            mode='normal'):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=((WATCH,) if mode.startswith('wait_') else ())+board,
                deck=(COIN,)*8 if deck is None else deck, mana=10, max_mana=10, hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', board=enemy_board, deck=(COIN,)*8, mana=10, max_mana=10,
                weapon_card_id=enemy_weapon, hero_power_card_id='HERO_08bp')),
            seed=327, generation_context=CTX), fixture(mode))

    def play(self, game, cid, target=None):
        eid = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == cid)
        game.apply(PlayCard(1, eid, target_id=target)); return eid

    def bodies(self, game, cid, player=1):
        return [game.state.entities[i] for i in game.state.players[player].board if game.state.entities[i].card_id == cid]

    def hand_count(self, game, cid):
        return sum(game.state.entities[i].card_id == cid for i in game.state.players[1].hand)

    def portable(self, game, mode='normal'):
        if mode not in self.readers: self.readers[mode] = fixture.__wrapped__(mode)
        saved = game.snapshot(); registry = self.readers[mode]
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(saved, registry).snapshot(), saved)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), saved)
        for player in (1, 2): self.assertNotIn('"rng_state"', json.dumps(game.for_player(player).observe()))
        return Game.from_snapshot(saved, registry)

    def finish_choices(self, game, limit):
        count = 0
        while game.state.pending_choice:
            q = game.state.pending_choice
            game.apply(SelectChoice(q.player_id, q.id, ('continue',))); count += 1
            self.assertLessEqual(count, limit)
        return count

    def test_twelve_roots_six_dependencies_thirty_six_complete_primary_faces(self):
        data = load_batch(); registry = fixture()
        self.assertEqual(tuple(x['record']['id'] for x in data['cards']), ROOTS)
        self.assertEqual(tuple(x['record']['id'] for x in data['dependencies']), DEPENDENCIES)
        self.assertEqual(len(data['official_observations']), 36)
        rows = {x['record']['id']: x['record'] for x in data['cards']+data['dependencies']}
        for cid, raw in rows.items():
            self.assertEqual(asdict(registry.card(cid).metadata), asdict(metadata_from_record(raw)))
            self.assertEqual(registry.card(cid).cost, raw['cost'])
        for observation in data['official_observations']:
            check_face(rows[observation['card_id']], observation['face'], observation['locale'])
        self.assertEqual(set(registry.card(BOAR).metadata.tribes), {'mech', 'beast'})
        self.assertEqual(rows[HALLS]['tags']['349'], 1)
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_dancer_only_own_end_gives_real_blessing_and_spell_buffs_original_minion(self):
        game = self.game(board=(DANCER, RAVEN)); raven = self.bodies(game, RAVEN)[0].id
        game.apply(EndTurn(1)); self.assertEqual(self.hand_count(game, BLESSING), 1)
        game.apply(EndTurn(2)); self.assertEqual(self.hand_count(game, BLESSING), 1)
        self.play(game, BLESSING, raven)
        self.assertEqual((game.state.entities[raven].attack, game.state.entities[raven].health), (4, 5))

    def test_reckoning_shuffles_real_final_spell_with_distinct_lifesteal_damage(self):
        game = self.game((HURT, RECKONING), (DUMMY,), deck=(), enemy_board=(DUMMY, DUMMY))
        self.play(game, HURT); self.play(game, RECKONING)
        self.assertEqual([e.health for e in self.bodies(game, DUMMY, 2)], [29, 29])
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 18)
        self.assertEqual(len(game.state.players[1].deck), 1)
        final = game.state.players[1].deck[0]; self.assertEqual(game.state.entities[final].card_id, FINAL)
        game.apply(EndTurn(1)); game.apply(EndTurn(2)); self.assertIn(final, game.state.players[1].hand)
        self.play(game, FINAL)
        self.assertEqual([e.health for e in self.bodies(game, DUMMY, 2)], [26, 26])
        self.assertEqual(self.bodies(game, DUMMY)[0].health, 30)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 24)

    def test_halls_original_spellpower_immunity_lifesteal_and_eight_cost_summon(self):
        game = self.game((HURT, ARMOR, HALLS), (POWER,))
        self.play(game, HURT); self.play(game, ARMOR); self.play(game, HALLS)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 22)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 26)
        body = self.bodies(game, BRAWLER)[0]
        self.assertEqual((body.attack, body.health), (6, 6))
        self.assertEqual(game.state.players[1].mana, 2)

    def test_halls_unknown_summon_rolls_back_all_prior_split_healing_payment_and_rng(self):
        game = self.game((HURT, HALLS), mode='unknown_minion'); self.play(game, HURT); saved = game.snapshot()
        with self.assertRaises(ResolutionError): self.play(game, HALLS)
        self.assertEqual(game.snapshot(), saved)

    def test_rift_generates_two_new_shadow_spells_without_tutoring_original_deck(self):
        game = self.game((RIFT,), deck=(SHADOW,)); original = game.state.players[1].deck[0]
        self.play(game, RIFT)
        self.assertEqual(self.hand_count(game, SHADOW), 2)
        self.assertEqual(game.state.players[1].deck, [original])
        self.assertNotIn(original, game.state.players[1].hand)

    def test_rift_full_hand_keeps_one_new_card_and_burns_the_other(self):
        game = self.game((RIFT,)+(COIN,)*9); self.play(game, RIFT)
        self.assertEqual(len(game.state.players[1].hand), 10)
        self.assertEqual(self.hand_count(game, SHADOW), 1)
        self.assertEqual(sum(e.card_id == SHADOW and e.zone == Zone.GRAVEYARD for e in game.state.entities.values()), 1)

    def test_unknown_eligible_rift_card_is_not_dropped_from_its_full_domain(self):
        game = self.game((RIFT,), mode='unknown_spell'); saved = game.snapshot()
        with self.assertRaises(ResolutionError): self.play(game, RIFT)
        self.assertEqual(game.snapshot(), saved)

    def test_negotiator_casts_three_cost_spell_once_per_real_battlecry_and_death(self):
        game = self.game((NEGOTIATOR, KILL)); source = self.play(game, NEGOTIATOR)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 29)
        self.play(game, KILL, source)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 28)
        self.assertEqual(self.hand_count(game, SHADOW), 0)

    def test_devourer_uses_original_left_right_outcast_and_unconditional_death(self):
        for hand, initial in (((DEVOURER, KILL, COIN), 1), ((COIN, DEVOURER, KILL), 0),
                ((KILL, COIN, DEVOURER), 1)):
            with self.subTest(hand=hand):
                game = self.game(hand); source = self.play(game, DEVOURER)
                self.assertEqual(self.hand_count(game, OUTCARD), initial)
                self.play(game, KILL, source)
                self.assertEqual(self.hand_count(game, OUTCARD), initial+1)

    def test_hammer_summons_two_real_rush_elementals_on_each_including_last_swing(self):
        game = self.game((HAMMER,)); weapon = self.play(game, HAMMER); hero = game.state.players[1].hero_id
        game.apply(Attack(1, hero, game.state.players[2].hero_id))
        self.assertEqual(len(self.bodies(game, ELEMENTAL)), 2)
        game.apply(EndTurn(1)); game.apply(EndTurn(2))
        game.apply(Attack(1, hero, game.state.players[2].hero_id))
        self.assertEqual(len(self.bodies(game, ELEMENTAL)), 4)
        self.assertEqual(game.state.entities[weapon].zone, Zone.GRAVEYARD)
        for body in self.bodies(game, ELEMENTAL): self.assertIn(Keyword.RUSH, body.keywords)

    def test_hammer_replacement_and_opponent_attack_do_not_borrow_its_reward(self):
        game = self.game((HAMMER, DAGGER), enemy_weapon=DAGGER)
        self.play(game, HAMMER); game.apply(EndTurn(1))
        game.apply(Attack(2, game.state.players[2].hero_id, game.state.players[1].hero_id))
        self.assertEqual(self.bodies(game, ELEMENTAL), [])
        game.apply(EndTurn(2)); self.play(game, DAGGER)
        game.apply(Attack(1, game.state.players[1].hero_id, game.state.players[2].hero_id))
        self.assertEqual(self.bodies(game, ELEMENTAL), [])

    def test_tank_copies_current_body_twice_and_each_real_body_keeps_own_deathrattle(self):
        game = self.game((KILL, TANK, KILL, KILL, KILL), (PROTOTYPE,))
        self.play(game, KILL, self.bodies(game, PROTOTYPE)[0].id); self.play(game, TANK)
        tanks = self.bodies(game, TANK); self.assertEqual(len(tanks), 3)
        for body in tanks: self.assertEqual((body.attack, body.health), (4, 4))
        for body in tanks: self.play(game, KILL, body.id)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 21)

    def test_boars_dual_tribes_charge_and_actual_capacity(self):
        game = self.game((BOARS,)); self.play(game, BOARS)
        boars = self.bodies(game, BOAR); self.assertEqual(len(boars), 2)
        for body in boars:
            self.assertIn(Keyword.CHARGE, body.keywords)
            game.apply(Attack(1, body.id, game.state.players[2].hero_id))
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 28)
        full = self.game((BOARS,), (DUMMY,)*6); self.play(full, BOARS)
        self.assertEqual((len(full.state.players[1].board), len(self.bodies(full, BOAR))), (7, 1))

    def test_bloom_two_actual_plants_and_original_named_bug_death_dependency(self):
        game = self.game((BLOOM, KILL)); self.play(game, BLOOM)
        ids = [i for i in game.state.players[1].hand if game.state.entities[i].card_id == PLANT]
        self.assertEqual(len(set(ids)), 2)
        source = self.play(game, PLANT); self.play(game, KILL, source)
        bug = self.bodies(game, BUG)[0]
        self.assertEqual((bug.attack, bug.health), (5, 5)); self.assertIn(Keyword.TAUNT, bug.keywords)
        self.assertEqual(self.hand_count(game, PLANT), 1)

    def test_hunter_actual_positive_damage_triggers_even_when_fatal_but_not_shielded(self):
        for operation, dies in ((HIT, False), (FATAL, True)):
            with self.subTest(operation=operation):
                game = self.game((operation,), (HUNTER,), enemy_board=(DUMMY,))
                source = self.bodies(game, HUNTER)[0].id; self.play(game, operation)
                self.assertEqual(game.state.players[2].board, [])
                self.assertEqual(game.state.entities[source].zone == Zone.GRAVEYARD, dies)
        game = self.game((SHIELD, HIT), (HUNTER,), enemy_board=(DUMMY,))
        self.play(game, SHIELD); self.play(game, HIT)
        self.assertEqual(len(game.state.players[2].board), 1)

    def test_hunter_elusive_rejects_targeted_spell_before_any_payment(self):
        game = self.game((KILL,), enemy_board=(HUNTER,)); saved = game.snapshot()
        with self.assertRaises(IllegalAction): self.play(game, KILL, self.bodies(game, HUNTER, 2)[0].id)
        self.assertEqual(game.snapshot(), saved)

    def test_tiger_attacks_owner_enemy_on_both_players_turn_starts(self):
        for owner in (1, 2):
            with self.subTest(owner=owner):
                game = self.game(board=(TIGER,) if owner == 1 else (), enemy_board=(TIGER,) if owner == 2 else ())
                target = game.state.players[3-owner].hero_id
                game.apply(EndTurn(1)); self.assertEqual(game.state.entities[target].health, 24)
                game.apply(EndTurn(2)); self.assertEqual(game.state.entities[target].health, 18)

    def test_boar_summon_wait_restores_original_fixed_group_without_extra_bodies(self):
        game = self.game((BOARS,), mode='wait_boars'); self.play(game, BOARS)
        self.assertIsNotNone(game.state.pending_choice)
        game = self.portable(game, 'wait_boars'); self.assertEqual(self.finish_choices(game, 2), 2)
        self.assertEqual(len(self.bodies(game, BOAR)), 2); self.portable(game, 'wait_boars')

    def test_shuffle_notification_wait_restores_the_same_single_final_spell(self):
        game = self.game((RECKONING,), deck=(), mode='wait_shuffle'); self.play(game, RECKONING)
        self.assertIsNotNone(game.state.pending_choice); original = game.state.players[1].deck[:]
        game = self.portable(game, 'wait_shuffle'); self.assertEqual(self.finish_choices(game, 1), 1)
        self.assertEqual(game.state.players[1].deck, original); self.portable(game, 'wait_shuffle')

    def test_split_wait_restores_all_eight_original_packets_before_one_summon(self):
        game = self.game((HURT, HALLS), mode='wait_split'); self.play(game, HURT); self.play(game, HALLS)
        self.assertIsNotNone(game.state.pending_choice); self.assertEqual(self.bodies(game, BRAWLER), [])
        game = self.portable(game, 'wait_split'); self.assertEqual(self.finish_choices(game, 8), 8)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 22)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 26)
        self.assertEqual(len(self.bodies(game, BRAWLER)), 1); self.portable(game, 'wait_split')


if __name__ == '__main__': unittest.main()
