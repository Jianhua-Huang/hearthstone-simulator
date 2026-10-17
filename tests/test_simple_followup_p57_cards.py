"""Native chains, original health receipts, completed plays and real owner turns."""
from dataclasses import asdict, fields
from functools import lru_cache
import json
import random
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.next_play_price_cards import PREFIX as PRICE_PREFIX
from hs_sim.cards.simple_followup_p57_cards import (EGG, BEAST, EGGS, CHAIN,
    HARDSHIP, VANESSA, TAX, DEFERRED, PARENT, ROOTS, PREFIX, POOL_ID,
    load_batch, register_simple_followup_p57_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity, Scenario,
    SelectChoice, TargetSpec, UseHandAction, UseHeroPower, Zone)
from hs_sim.engine.effects import (ChoiceOption, Damage, Destroy, GainArmor,
    InvokeBehavior, RequestChoice, Silence, Summon, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.hand_capacity import hand_capacity
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerateFromPool, GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.turn_scheduling import QueueTurns, SkipTurns
from hs_sim.engine.zones import FillHandWithCard
from hs_sim.targets import canonical_digest

TEST = 'p57.test.'
YETI, BC, ONE, UNKNOWN_BC, UNKNOWN_ONE = 'CORE_CS2_182', TEST + 'battlecry', TEST + 'one', TEST + 'unknown_bc', TEST + 'unknown_one'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
COLLECTIBLE = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())
MEMBERS = (BC, ONE, YETI)
CONTEXT = GenerationContext('p57-complete-explicit-fixture', 'experimental')


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata', lambda r: None):
        r = build_registry()
    present = tuple(cid in r.cards for cid in ROOTS)
    if not any(present):
        register_simple_followup_p57_cards(r)
    elif not all(present):
        raise AssertionError('P57 assembly must contain all nine accepted complete definitions')
    register_candidate_pool_metadata(r)
    r.validate()
    return r


def registry(mode=None, members=MEMBERS):
    r = batch_registry()
    r.register_behavior(TEST + 'armor', lambda c: (GainArmor(c.player_id, 1),))
    r.register_card(CardDefinition(BC, 'Printed Battlecry', CardType.MINION, cost=4,
        attack=2, health=4, battlecry=TEST + 'armor', metadata=COLLECTIBLE))
    r.register_card(CardDefinition(ONE, 'One cost', CardType.MINION, cost=1,
        attack=1, health=2, metadata=COLLECTIBLE))
    r.register_card(CardDefinition(TEST + 'victim', 'Actual original victim', CardType.MINION,
        attack=1, health=1, keywords=(Keyword.REBORN,), metadata=META))
    r.register_card(CardDefinition(TEST + 'shield', 'Prevented damage survives', CardType.MINION,
        attack=1, health=2, keywords=(Keyword.DIVINE_SHIELD,), metadata=META))
    r.register_card(CardDefinition(TEST + 'power', 'Spell bonus', CardType.MINION,
        health=5, spell_damage=2, metadata=META))
    scripts = dict(kill=lambda c: (Destroy(c.target_id, c.source_id),),
        silence=lambda c: (Silence(c.target_id),),
        trigger=lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        spell=lambda c: (GainArmor(c.player_id, 1),),
        summon=lambda c: (Summon(c.player_id, VANESSA),),
        fill=lambda c: (FillHandWithCard(c.player_id, YETI, c.source_id),),
        extra=lambda c: (QueueTurns((c.player_id,), c.source_id),),
        skip=lambda c: (SkipTurns(2, source_id=c.source_id),),
        fail=lambda c: (_ for _ in ()).throw(ResolutionError('P57 deliberate continuation failure')))
    for name, body in scripts.items():
        r.register_behavior(TEST + name, body)
        r.register_card(CardDefinition(TEST + name, name, CardType.SPELL, on_play=TEST + name,
            targeting=TargetSpec() if name in ('kill', 'silence', 'trigger') else None, metadata=META))
    r.register_card(CardDefinition(TEST + 'power_summon', 'Summon only', CardType.HERO_POWER,
        cost=2, on_use=TEST + 'summon', metadata=META))
    for cid, cost, battlecry in ((UNKNOWN_BC, 4, True), (UNKNOWN_ONE, 1, False)):
        r.register_pool_card(PoolCard(cid, CardType.MINION, cost, COLLECTIBLE,
            battlecry=battlecry, deathrattle=False, choose_one=False))
    for cid in members:
        if cid not in r.pool_cards:
            r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID, 'p57-complete-explicit-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode:
        def eligible(c):
            if mode == 'egg':
                return c.state.entities[c.event.target_id].card_id == EGGS[1]
            if mode == 'death':
                return c.state.entities[c.event.source_id].card_id == TEST + 'victim'
            return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id == HARDSHIP
        r.register_trigger_condition(TEST + 'eligible', eligible)
        r.register_behavior(TEST + 'watch', lambda c: (RequestChoice(1, (
            ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Fail', (
                InvokeBehavior(TEST + 'fail', c.source_id, 1),))), c.source_id),))
        event = {'egg': 'minion_summoned', 'health': 'health_resolved', 'death': 'minion_died'}[mode]
        r.register_card(CardDefinition(TEST + 'watch', 'Original receipt witness', CardType.WEAPON,
            durability=5, metadata=META, limited_triggers=(LimitedTriggerSpec(
                event, TEST + 'watch', condition_id=TEST + 'eligible'),)))
    r.validate()
    return r


@lru_cache(maxsize=None)
def shared_registry(mode, members):
    return registry(mode, members)


class SimpleFollowupP57Tests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), mode=None,
            members=MEMBERS, mana=40, rules=None, power=None):
        self.config = mode, members
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board,
            deck=(YETI,) * 12, mana=mana, max_mana=40, mana_cap=40,
            weapon_card_id=TEST + 'watch' if mode else None, hero_power_card_id=power),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(YETI,) * 12,
                mana=40, max_mana=40, mana_cap=40)), seed=5757, generation_context=CONTEXT),
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
            for key in ('rng_state', 'resolution_frame', 'pool_id', 'behavior_id', 'source_json', 'play_history'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_eleven_full_rows_twenty_two_faces_twelve_links_and_five_explicit_attack_zeros(self):
        from tools.card_batch import check_face
        data = load_batch()
        rows = {x['record']['id']: x for k in ('cards', 'skipped', 'evidence_only') for x in data[k]}
        self.assertEqual((len(rows), len(data['official_observations']), len(data['exact_parent_child_links'])), (11, 22, 12))
        faces = {(o['card_id'], o['locale']): o['face'] for o in data['official_observations']}
        for o in data['official_observations']:
            raw = rows[o['card_id']]['record']
            check_face(raw, o['face'], o['locale'], numeric_normalizations=data['numeric_normalizations'].get(raw['id']))
            self.assertEqual(canonical_digest(raw), rows[raw['id']]['record_sha256'])
        for link in data['exact_parent_child_links']:
            self.assertIn(link['dbf_id'], faces[link['parent'], link['locale']]['childIds'])
            self.assertEqual(rows[link['child']]['record']['dbf_id'], link['dbf_id'])
        for cid in EGGS:
            self.assertIsNone(rows[cid]['record']['attack'])
            self.assertNotIn('ATK', rows[cid]['record']['tags'])
        self.assertFalse(data['formal_pool_complete'] or data['cn_calibrated'] or data['parent_implemented'])

    def test_nine_complete_definitions_three_roots_and_all_old_data_preserved(self):
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
                self.assertEqual((card.attack, card.health), (0 if card.id in EGGS else raw['attack'], raw['health']))
        self.assertEqual(sum(after.card(cid).metadata.collectible for cid in ROOTS), 3)
        self.assertEqual(after.card(DEFERRED), before.card(DEFERRED))
        self.assertNotIn(PARENT, after.cards)
        self.assertEqual(after.card(VANESSA).hand_actions[0].cost, 1)
        self.assertEqual(after.player_effect(PREFIX + 'pending_tax').triggers,
            after.player_effect(PRICE_PREFIX + 'pending_slow').triggers)

    def test_five_actual_deaths_follow_explicit_chain_to_new_twenty_twenty_taunt_beast(self):
        g = self.game((TEST + 'kill',) * 5, board=(EGG,))
        old_ids = []
        for cid, next_cid in zip(EGGS, CHAIN[1:]):
            original = self.first(g, cid, 'board').id; old_ids.append(original)
            self.play(g, TEST + 'kill', original)
            new = self.first(g, next_cid, 'board')
            self.assertNotIn(new.id, old_ids)
            self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD)
        beast = self.first(g, BEAST, 'board')
        self.assertEqual((beast.attack, beast.max_health), (20, 20))
        self.assertIn(Keyword.TAUNT, beast.keywords)
        self.assertEqual(g.registry.card(BEAST).metadata.tribes, ('beast',))
        self.assertEqual(len(g.state.death_history), 5)
        self.portable(g)

    def test_egg_trigger_full_board_silence_and_enemy_actual_controller(self):
        g = self.game((TEST + 'trigger',), board=(EGG, *((YETI,) * 6)))
        self.play(g, TEST + 'trigger', self.first(g, EGG, 'board').id)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertFalse(g.state.death_history)
        g = self.game((TEST + 'silence', TEST + 'kill'), board=(EGG,))
        target = self.first(g, EGG, 'board').id
        self.play(g, TEST + 'silence', target); self.play(g, TEST + 'kill', target)
        self.assertFalse(g.state.players[1].board)
        g = self.game((TEST + 'kill',), enemy=(EGG,))
        self.play(g, TEST + 'kill', self.first(g, EGG, 'board', 2).id)
        self.assertEqual(self.first(g, EGGS[1], 'board', 2).controller, 2)
        self.assertFalse(g.state.players[1].board)

    def test_egg_real_entry_wait_restores_and_failure_rolls_back_only_continuation(self):
        g = self.game((TEST + 'kill',), board=(EGG,), mode='egg')
        self.play(g, TEST + 'kill', self.first(g, EGG, 'board').id)
        self.assertEqual(self.first(g, EGGS[1], 'board').health, 3)
        saved = g.snapshot(); self.portable(g)
        with self.assertRaises(ResolutionError):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g)
        self.assertEqual(len(g.state.players[1].board), 1)

    def test_hardship_survival_and_prevention_draw_original_card_once(self):
        for cid in (YETI, TEST + 'shield'):
            g = self.game((HARDSHIP,), enemy=(cid,))
            top = g.state.players[1].deck[0]
            self.play(g, HARDSHIP, self.first(g, cid, 'board', 2).id)
            self.assertEqual(g.state.players[1].hand, [top])
            self.assertFalse(g.state.players[1].board or g.state.death_history)
        g = self.game((HARDSHIP,), enemy=(YETI,), board=(TEST + 'power',))
        self.play(g, HARDSHIP, self.first(g, YETI, 'board', 2).id)
        self.assertEqual(g.state.damage_history[-1].health_result.modified_amount, 3)

    def test_hardship_real_death_with_reborn_uses_original_fact_and_one_cost_pool(self):
        g = self.game((HARDSHIP,), enemy=(TEST + 'victim',), members=(ONE,))
        old = self.first(g, TEST + 'victim', 'board', 2).id
        self.play(g, HARDSHIP, old)
        self.assertEqual(self.first(g, ONE, 'board').card_id, ONE)
        self.assertEqual(g.state.entities[old].zone, Zone.GRAVEYARD)
        self.assertNotEqual(self.first(g, TEST + 'victim', 'board', 2).id, old)
        self.assertFalse(g.state.players[1].hand)
        self.portable(g)

    def test_hardship_health_and_death_waiting_keep_original_reward_without_repay(self):
        for mode, cid in (('health', YETI), ('death', TEST + 'victim')):
            g = self.game((HARDSHIP,), enemy=(cid,), mode=mode, members=(ONE,))
            self.play(g, HARDSHIP, self.first(g, cid, 'board', 2).id)
            saved = g.snapshot(); self.portable(g)
            with self.assertRaises(ResolutionError):
                self.choose(g, 'bad')
            self.assertEqual(g.snapshot(), saved)
            self.choose(g)
            self.assertEqual(g.state.players[1].mana, 39)
            if mode == 'health':
                self.assertEqual(len(g.state.players[1].hand), 1)
            else:
                self.assertEqual(self.first(g, ONE, 'board').card_id, ONE)

    def test_hardship_unknown_complete_pool_rolls_back_original_death_payment_rng(self):
        g = self.game((HARDSHIP,), enemy=(TEST + 'victim',), members=(ONE, UNKNOWN_ONE))
        saved, calls = g.snapshot(), []
        original = random.Random.randrange
        def spy(rng, *args, **kwargs):
            calls.append(args); return original(rng, *args, **kwargs)
        with patch.object(random.Random, 'randrange', spy), self.assertRaises(ResolutionError):
            self.play(g, HARDSHIP, self.first(g, TEST + 'victim', 'board', 2).id)
        self.assertEqual(g.snapshot(), saved)
        self.assertFalse(calls)

    def test_vanessa_self_play_excluded_then_actual_spell_and_minion_generate_discount(self):
        g = self.game((VANESSA, TEST + 'spell'), members=(BC,))
        self.play(g, VANESSA)
        self.assertEqual(len(g.state.players[1].hand), 1)
        self.play(g, TEST + 'spell')
        new = self.first(g, BC)
        self.assertEqual(self.quote(g, new.id).amount, 2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 1)
        self.play(g, BC)
        self.assertEqual(len(g.state.players[1].hand), 1)
        self.assertEqual(self.quote(g, self.first(g, BC).id).amount, 2)
        self.portable(g)

    def test_vanessa_prepare_and_summon_do_not_replace_actual_paid_card_trigger(self):
        g = self.game((VANESSA,), board=(VANESSA,), members=(BC,), mana=3)
        target = self.first(g, VANESSA).id
        g.apply(UseHandAction(1, target, 'prepare'))
        self.assertEqual(len(g.state.players[1].hand), 1)
        self.assertFalse(g.state.play_history)
        with self.assertRaises(IllegalAction):
            self.play(g, VANESSA)
        self.portable(g)
        g = self.game((TEST + 'summon',), members=(BC,))
        self.play(g, TEST + 'summon')
        self.assertEqual(self.first(g, VANESSA, 'board').card_id, VANESSA)
        self.assertEqual(len(g.state.players[1].hand), 1)
        g = self.game(board=(VANESSA,), members=(BC,), power=TEST + 'power_summon')
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        self.assertEqual(len(g.state.players[1].board), 2)
        self.assertFalse(g.state.players[1].hand or g.state.play_history)

    def test_vanessa_unknown_qualified_battlecry_fails_without_executable_crop(self):
        g = self.game((TEST + 'spell',), board=(VANESSA,), members=(BC, UNKNOWN_BC))
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, TEST + 'spell')
        self.assertEqual(g.snapshot(), saved)

    def test_tax_pending_survives_source_death_and_expires_after_opponent_actual_turn(self):
        g = self.game((TAX, TEST + 'kill'), enemy_hand=(YETI, TEST + 'spell'))
        source = self.play(g, TAX)
        self.assertEqual(self.quote(g, self.first(g, YETI, player=2).id).amount, 4)
        self.play(g, TEST + 'kill', source)
        self.portable(g)
        g.apply(EndTurn(1))
        self.assertEqual(self.quote(g, self.first(g, YETI, player=2).id).amount, 5)
        self.assertEqual(self.quote(g, self.first(g, TEST + 'spell', player=2).id).amount, 1)
        self.assertFalse(g.state.players[2].player_effects)
        self.portable(g)
        g.apply(EndTurn(2))
        self.assertEqual(self.quote(g, self.first(g, YETI, player=2).id).amount, 4)

    def test_tax_queued_or_skipped_slots_wait_for_real_opponent_start(self):
        for schedule in ('extra', 'skip'):
            g = self.game((TAX, TEST + schedule), enemy_hand=(YETI,))
            self.play(g, TAX); self.play(g, TEST + schedule)
            g.apply(EndTurn(1))
            self.assertEqual(g.state.active_player, 1)
            self.assertEqual(self.quote(g, self.first(g, YETI, player=2).id).amount, 4)
            g.apply(EndTurn(1))
            self.assertEqual(g.state.active_player, 2)
            self.assertEqual(self.quote(g, self.first(g, YETI, player=2).id).amount, 5)

    def test_historical_time615_probe_keeps_original_gap_and_native_capacity_request_is_now_registered(self):
        a = self.game((TEST + 'fill',), rules=Ruleset(max_hand=6))
        b = self.game((TEST + 'fill',), rules=Ruleset(max_hand=11))
        self.assertEqual(asdict(a.state), asdict(b.state))
        self.assertIsNone(a.state.players[1].hand_cap)
        self.assertEqual((hand_capacity(a.state.players[1], a.ruleset),
            hand_capacity(b.state.players[1], b.ruleset)), (6, 11))
        self.assertNotIn('rules', {f.name for f in fields(RuleContext)})
        self.assertNotIn('pool_id', {f.name for f in fields(FillHandWithCard)})
        self.assertNotIn('cost', {f.name for f in fields(FillHandWithCard)})
        self.assertNotIn('fill', {f.name for f in fields(GenerateFromPool)})
        self.play(a, TEST + 'fill'); self.play(b, TEST + 'fill')
        self.assertEqual((len(a.state.players[1].hand), len(b.state.players[1].hand)), (6, 11))
        from hs_sim.engine.pools import FillHandFromPool
        self.assertIn(FillHandFromPool, a.mechanics.effect_types)
        self.assertIsNotNone(a.registry.card(DEFERRED).on_play)
        self.assertEqual([x['record']['id'] for x in load_batch()['skipped']], [DEFERRED])


if __name__ == '__main__':
    unittest.main()
