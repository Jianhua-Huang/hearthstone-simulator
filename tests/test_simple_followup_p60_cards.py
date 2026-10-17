"""Frozen selection, real rewards, native payments and completed constructed starts."""
from dataclasses import asdict
from functools import lru_cache
import json
import random
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p60_cards import (BARNABUS, QUEEN, MEGAFIN, SULFURAS,
    POWER, SOLITOS, FLOWER, FISH, ANCIENT, WHISPER, ROOTS, RAPTOR, PREFIX, POOL_ID,
    load_batch, register_simple_followup_p60_cards)
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    DeckPolicy, DeckSpec, EndTurn, Game, IllegalAction, Keyword, MatchSetup, PlayCard,
    PlayerSetup, Rarity, Scenario, SelectChoice, TargetSpec, UseHeroPower, Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (ChoiceOption, Damage, Destroy, EquipWeapon,
    InvokeBehavior, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import DamageKind, LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.targets import canonical_digest

TEST = 'p60.test.'
YETI = 'CORE_CS2_182'
MURL_A, MURL_B, ALL_RACE, BEAST, UNKNOWN = (TEST + x for x in ('murl_a', 'murl_b', 'all', 'beast', 'unknown'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
MEMBERS = (MURL_A, MURL_B, ALL_RACE, BEAST)
CONTEXT = GenerationContext('p60-complete-explicit-fixture', 'experimental')


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata', lambda r: None):
        r = build_registry()
    present = tuple(cid in r.cards for cid in ROOTS)
    if not any(present): register_simple_followup_p60_cards(r)
    elif not all(present): raise AssertionError('P60 complete ten-definition assembly required')
    register_candidate_pool_metadata(r); r.validate(); return r


def registry(mode=None, members=MEMBERS):
    r = batch_registry()
    for cid, cls, tribe in ((MURL_A, CardClass.NEUTRAL, 'murloc'), (MURL_B, CardClass.WARRIOR, 'murloc'),
            (ALL_RACE, CardClass.NEUTRAL, 'all'), (BEAST, CardClass.NEUTRAL, 'beast')):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=2, attack=2, health=6,
            metadata=CardMetadata(True, (cls,), Rarity.COMMON, tribes=(tribe,))))
    r.register_card(CardDefinition(TEST + 'power', 'Spell bonus', CardType.MINION, health=9,
        spell_damage=5, metadata=META))
    r.register_card(CardDefinition(TEST + 'dormant', 'Dormant occupancy', CardType.MINION,
        health=5, dormant_turns=2, metadata=META))
    r.register_card(CardDefinition(TEST + 'setup', 'Actual opening setup', CardType.MINION,
        cost=0, attack=1, health=2, battlecry=TEST + 'setup',
        metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())))
    r.register_behavior(TEST + 'setup', lambda c: (EquipWeapon(c.player_id, TEST + 'watch'),))
    def grow(c):
        target = next(i for i in c.state.players[1].hand if c.state.entities[i].card_id == SOLITOS)
        return (BuffStoredCard(CardReference.capture(c.state.entities[target]), 2, 3, c.source_id),)
    scripts = dict(kill=lambda c: (Destroy(c.target_id, c.source_id),),
        wound=lambda c: (Damage(c.state.players[1].hero_id, 3, c.source_id),), grow=grow,
        return_deck=lambda c: (MoveCard(CardReference.capture(c.state.entities[c.target_id]), 1, Zone.DECK,
            reset=True, source_id=c.source_id),),
        fail=lambda c: (_ for _ in ()).throw(ResolutionError('P60 deliberate continuation failure')))
    for name, body in scripts.items():
        r.register_behavior(TEST + name, body)
        r.register_card(CardDefinition(TEST + name, name, CardType.SPELL, cost=3 if name == 'wound' else 0, on_play=TEST + name,
            targeting=TargetSpec() if name == 'kill' else None, metadata=META))
    r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 2,
        CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=('murloc',)),
        battlecry=False, deathrattle=False, choose_one=False))
    for cid in members:
        if cid not in r.pool_cards: r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID, 'p60-complete-explicit-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode:
        def eligible(c):
            source = c.state.entities.get(c.event.source_id)
            return source is not None and source.card_id == {'barnabus': BARNABUS, 'megafin': MEGAFIN, 'starting': FISH}[mode]
        def watch(c):
            options = [ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Fail',
                (InvokeBehavior(TEST + 'fail', c.source_id, 1),))]
            if mode == 'barnabus':
                target = c.state.players[1].deck[1]
                options.append(ChoiceOption('cycle', 'Original second deck minion reenters', (
                    MoveCard(CardReference.capture(c.state.entities[target]), 1, Zone.HAND, source_id=c.source_id),
                    InvokeBehavior(TEST + 'return_deck', c.source_id, 1, target))))
            return (RequestChoice(1, tuple(options), c.source_id),)
        r.register_trigger_condition(TEST + 'eligible', eligible); r.register_behavior(TEST + 'watch', watch)
        event = {'barnabus': 'cost_modified', 'megafin': 'card_added_to_hand', 'starting': 'temporary_starting_hand_replaced'}[mode]
        r.register_card(CardDefinition(TEST + 'watch', 'Original accepted operation witness', CardType.WEAPON,
            durability=5, metadata=META, limited_triggers=(LimitedTriggerSpec(event, TEST + 'watch', condition_id=TEST + 'eligible'),)))
    r.validate(); return r


@lru_cache(maxsize=None)
def shared_registry(mode, members): return registry(mode, members)


class SimpleFollowupP60Tests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), deck=(YETI,) * 10, mode=None,
            members=MEMBERS, rules=None, hand_cap=None, weapon=None, power=None):
        self.config = mode, members
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
            mana=50, max_mana=50, mana_cap=50, hand_cap=hand_cap,
            weapon_card_id=TEST + 'watch' if mode else weapon, hero_power_card_id=power),
            PlayerSetup('HERO_08', board=enemy, deck=(YETI,) * 10, mana=50, max_mana=50, mana_cap=50)),
            seed=6060, generation_context=CONTEXT), shared_registry(*self.config), ruleset=rules or Ruleset())

    def first(self, g, cid, zone='hand', player=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None):
        e = self.first(g, cid)
        g.apply(PlayCard(1, e.id, target_id=target, position=len(g.state.players[1].board)
            if e.kind == CardType.MINION else None)); return e.id

    def quote(self, g, entity_id):
        state = g.state; return quote_cost(state, g.registry, state.entities[entity_id])

    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(*self.config))
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(*self.config)).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(g.for_player(player).legal_actions()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'pool_id', 'behavior_id', 'source_json', 'starting_hands', 'temporary_hands'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_frozen_twenty_one_rows_forty_two_faces_thirty_real_edges_and_standard_dependency_scope(self):
        from tools.card_batch import check_face
        data = load_batch(); rows = {x['record']['id']: x for k in ('cards', 'existing_dependencies', 'evidence_only') for x in data[k]}
        self.assertEqual((len(rows), len(data['official_observations']), len(data['exact_parent_child_links'])), (21, 42, 30))
        faces = {(o['card_id'], o['locale']): o['face'] for o in data['official_observations']}
        for o in data['official_observations']:
            raw = rows[o['card_id']]['record']; check_face(raw, o['face'], o['locale'])
            self.assertEqual(canonical_digest(raw), rows[raw['id']]['record_sha256'])
        for link in data['exact_parent_child_links']:
            self.assertIn(link['dbf_id'], faces[link['parent'], link['locale']]['childIds'])
            self.assertEqual(rows[link['child']]['record']['dbf_id'], link['dbf_id'])
        self.assertTrue(all(x['parent'] != 'TLC_602t' for x in data['exact_parent_child_links']))
        self.assertIn('Quest Rewards', faces['TLC_602t', 'en_US']['text'])
        self.assertFalse(data['formal_pool_complete'] or data['cn_calibrated'] or data['parents_implemented'])

    def test_ten_new_definitions_one_collectible_nine_noncollectible_and_old_complete_data(self):
        before, after = build_registry(), batch_registry()
        self.assertEqual(set(after.cards) - set(before.cards), set(ROOTS) - set(before.cards))
        for cid, card in before.cards.items(): self.assertEqual(after.card(cid), card)
        for cid, card in before.pool_cards.items(): self.assertEqual(after.pool_cards[cid], card)
        self.assertEqual(dict(before.pools), dict(after.pools)); self.assertEqual(dict(before.generation_families), dict(after.generation_families))
        for cid, pin in load_batch()['existing_dependency_definition_pins'].items(): self.assertEqual(canonical_digest(asdict(after.card(cid))), pin)
        for row in load_batch()['cards']:
            raw = row['record']; card = after.card(raw['id'])
            self.assertEqual((card.cost, card.metadata), (raw['cost'], metadata_from_record(raw)))
            if card.kind == CardType.MINION: self.assertEqual((card.attack, card.health), (raw['attack'], raw['health']))
            if card.kind == CardType.WEAPON: self.assertEqual((card.attack, card.durability), (raw['attack'], raw['health']))
        self.assertEqual(sum(after.card(cid).metadata.collectible for cid in ROOTS), 1)

    def test_barnabus_only_original_physical_deck_minions_become_zero(self):
        g = self.game((BARNABUS, YETI), deck=(YETI, TEST + 'wound', BEAST))
        original = tuple(g.state.players[1].deck); self.play(g, BARNABUS)
        self.assertEqual(tuple(g.state.players[1].deck), original)
        self.assertEqual([self.quote(g, i).amount for i in original], [0, 3, 0])
        self.assertEqual(self.quote(g, self.first(g, YETI).id).amount, 4)
        self.assertFalse(g.state.cast_history)

    def test_barnabus_original_deck_references_wait_restore_failure_and_reentry(self):
        g = self.game((BARNABUS,), deck=(YETI, BEAST), mode='barnabus')
        first, second = g.state.players[1].deck; self.play(g, BARNABUS)
        saved = g.snapshot(); self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved); self.choose(g, 'cycle')
        self.assertEqual(self.quote(g, first).amount, 0)
        self.assertEqual(self.quote(g, second).amount, 2)
        self.assertEqual(g.state.entities[second].zone, Zone.DECK)

    def test_queen_is_current_eight_eight_rush_and_twenty_raptors_one_semantic_shuffle(self):
        g = self.game((QUEEN,), deck=()); source = self.play(g, QUEEN)
        self.assertIn(Keyword.RUSH, g.state.entities[source].keywords)
        self.assertEqual(len(g.state.players[1].deck), 20)
        self.assertTrue(all(g.state.entities[i].card_id == RAPTOR for i in g.state.players[1].deck))
        self.assertEqual(len(set(g.state.players[1].deck)), 20)
        row, = g.state.deck_shuffle_history
        self.assertEqual((row.actor_id, row.player_id, row.declared_count, row.profile), (1, 1, 20, 'semantic'))
        self.portable(g)

    def test_megafin_real_effective_hand_capacity_and_full_murloc_all_pool(self):
        for cap, override in ((6, None), (10, 13)):
            g = self.game((MEGAFIN,), rules=Ruleset(max_hand=cap), hand_cap=override)
            self.play(g, MEGAFIN)
            self.assertEqual(len(g.state.players[1].hand), override or cap)
            self.assertTrue(all(g.state.entities[i].card_id in (MURL_A, MURL_B, ALL_RACE) for i in g.state.players[1].hand))

    def test_megafin_original_batch_wait_restore_and_unknown_before_rng(self):
        g = self.game((MEGAFIN,), mode='megafin', rules=Ruleset(max_hand=6))
        self.play(g, MEGAFIN); saved = g.snapshot(); self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved); self.choose(g)
        self.assertEqual(len(g.state.players[1].hand), 6)
        g = self.game((MEGAFIN,), members=(MURL_A, UNKNOWN)); saved, calls = g.snapshot(), []
        original = random.Random.randrange
        def spy(rng, *args, **kwargs): calls.append(args); return original(rng, *args, **kwargs)
        with patch.object(random.Random, 'randrange', spy), self.assertRaises(ResolutionError): self.play(g, MEGAFIN)
        self.assertEqual(g.snapshot(), saved); self.assertFalse(calls)

    def test_sulfuras_real_weapon_battlecry_installs_exact_power_with_two_mana_payment(self):
        g = self.game((SULFURAS,), board=(TEST + 'power',)); source = self.play(g, SULFURAS)
        weapon = g.state.entities[source]
        self.assertEqual((weapon.zone, weapon.attack, weapon.durability), (Zone.WEAPON, 4, 2))
        power = g.state.players[1].hero_power_id
        self.assertEqual(g.state.entities[power].card_id, POWER)
        mana = g.state.players[1].mana; g.apply(UseHeroPower(1, power))
        self.assertEqual(g.state.players[1].mana, mana - 2)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 22)
        result = g.state.damage_history[-1].health_result
        self.assertEqual((result.base_amount, result.spell_bonus, result.damage_kind), (8, 0, DamageKind.HERO_POWER.value))
        with self.assertRaises(IllegalAction): g.apply(UseHeroPower(1, power))
        self.portable(g)

    def test_power_random_enemy_domain_excludes_dormant_and_location(self):
        g = self.game(enemy=(TEST + 'dormant', 'EDR_520'), power=POWER)
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 22)
        self.assertEqual(len(g.state.players[2].board), 2)

    def test_flower_ordinary_hero_attack_buffs_current_group_not_dormant_or_enemy(self):
        g = self.game((FLOWER,), board=(YETI, TEST + 'dormant'), enemy=(BEAST,))
        self.play(g, FLOWER); target = self.first(g, BEAST, 'board', 2).id
        g.apply(Attack(1, g.state.players[1].hero_id, target))
        self.assertEqual((self.first(g, YETI, 'board').attack, self.first(g, YETI, 'board').max_health), (6, 7))
        self.assertEqual(self.first(g, TEST + 'dormant', 'board').max_health, 5)
        self.assertEqual(g.state.entities[target].max_health, 6)

    def test_flower_last_wear_reward_uses_original_weapon_completion(self):
        g = self.game((FLOWER,), board=(YETI,)); weapon = self.play(g, FLOWER)
        for index in range(5):
            g.apply(Attack(1, g.state.players[1].hero_id, g.state.players[2].hero_id))
            if index < 4: g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(g.state.entities[weapon].zone, Zone.GRAVEYARD)
        self.assertEqual((self.first(g, YETI, 'board').attack, self.first(g, YETI, 'board').max_health), (14, 15))

    def test_final_solitos_current_copy_material_and_actual_death_random_five(self):
        g = self.game((TEST + 'grow', SOLITOS, TEST + 'kill'), board=(TEST + 'power',))
        self.play(g, TEST + 'grow'); source = self.play(g, SOLITOS)
        bodies = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == SOLITOS]
        self.assertEqual(len(bodies), 2); self.assertEqual({(e.attack, e.max_health) for e in bodies}, {(10, 11)})
        self.assertTrue(all(Keyword.TAUNT in e.keywords and Keyword.REBORN in e.keywords for e in bodies))
        self.play(g, TEST + 'kill', source)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 25)
        result = g.state.damage_history[-1].health_result
        self.assertEqual((result.base_amount, result.spell_bonus, result.damage_kind), (5, 0, DamageKind.MINION_ABILITY.value))
        reborn = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == SOLITOS and g.state.entities[i].health == 1]
        self.assertEqual(len(reborn), 1); self.assertNotIn(Keyword.REBORN, reborn[0].keywords)

    def test_solitos_native_copy_capacity_and_two_real_named_taunt_bodies(self):
        g = self.game((SOLITOS,), board=(YETI,) * 6); self.play(g, SOLITOS)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual(sum(g.state.entities[i].card_id == SOLITOS for i in g.state.players[1].board), 1)
        g = self.game((ANCIENT, WHISPER))
        for cid in (ANCIENT, WHISPER):
            source = self.play(g, cid); e = g.state.entities[source]
            self.assertEqual((e.attack, e.max_health), (5, 5)); self.assertIn(Keyword.TAUNT, e.keywords)

    def test_time706_scenario_cannot_invent_constructed_starting_hands(self):
        g = self.game((FISH,)); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, FISH)
        self.assertEqual(g.snapshot(), saved)

    def test_time706_real_completed_opening_wait_restore_played_temporary_card_and_own_end(self):
        self.config = 'starting', MEMBERS; r = registry(*self.config)
        decks = (DeckSpec('HERO_04', 'HERO_04bp', CardClass.PALADIN, (FISH, *((TEST + 'setup',) * 7))),
            DeckSpec('HERO_04', 'HERO_04bp', CardClass.PALADIN, (TEST + 'setup',) * 8))
        policy = DeckPolicy('p60-real-opening', CONTEXT.target_id, CONTEXT.mode, tuple(r.cards), deck_size=8, max_copies=8)
        g = Game.from_decks(MatchSetup(decks, policy, 'GAME_005', seed=6060, first_player=1), r)
        while g.state.pending_choice:
            q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, ()))
        self.assertEqual(g.state.opening.stage, 'complete')
        starting = tuple(x.card_id for x in g.state.opening.starting_hands[0]); self.assertEqual(len(starting), 3)
        for _ in range(16):
            if (g.state.active_player == 1 and g.state.players[1].mana >= 2 and
                    any(g.state.entities[i].card_id == FISH for i in g.state.players[1].hand)):
                break
            g.apply(EndTurn(g.state.active_player))
        else:
            self.fail('Real opening deck did not draw the fish through ordinary turns')
        self.play(g, TEST + 'setup'); source = self.first(g, FISH).id
        saved_originals = tuple(i for i in g.state.players[1].hand if i != source)
        self.play(g, FISH)
        self.assertEqual(tuple(g.state.entities[i].card_id for i in g.state.players[1].hand), starting)
        self.assertTrue(set(saved_originals).isdisjoint(g.state.players[1].hand))
        saved = g.snapshot(); self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved); self.choose(g)
        temporary = self.play(g, TEST + 'setup')
        g.apply(EndTurn(1))
        self.assertEqual(tuple(g.state.players[1].hand), saved_originals)
        self.assertEqual(g.state.entities[temporary].zone, Zone.BOARD)
        self.assertEqual(g.state.temporary_hands[-1].phase, 'completed')
        self.portable(g)


if __name__ == '__main__': unittest.main()
