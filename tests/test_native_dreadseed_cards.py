"""Actual Dreadseed entry, owner clocks, awakening, native causes and recovery."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import random
import re
import unittest
from unittest.mock import patch

from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.native_dreadseed_cards import (SLUMBER, HARVEST, CORRUPTER, ROOTS, SEEDS, HOUND, CROW, SERPENT,
    SUMMON_BRANCH, DAMAGE_BRANCH, CHOICE_ONLY, DEPENDENCIES, EVIDENCE_ONLY, TURNS, PREFIX, load_batch)
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (Attack, AwakenMinion, CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    IllegalAction, Keyword, MakeDormant, PlayCard, PlayerSetup, Scenario, SelectChoice, TargetSpec, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, Damage, Destroy, InvokeBehavior, RequestChoice,
    Silence, Summon, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind, LimitedTriggerSpec
from hs_sim.engine.registry import Registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest

P = 'k123.test.'
YETI = 'CORE_CS2_182'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())


@lru_cache(None)
def registry(mode=None, missing=None):
    original = Registry.register_card
    def register(r, card):
        if card.id != missing:
            return original(r, card)
    with patch.object(Registry, 'register_card', register):
        r = build_registry()
    scripts = {
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'trigger': lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        'wake': lambda c: (AwakenMinion(c.state.players[1].board[0], c.source_id),),
        'sleep': lambda c: (MakeDormant(c.target_id, 1, c.source_id),),
        'steal': lambda c: (ChangeControl(c.target_id, 2),),
        'silence': lambda c: (Silence(c.target_id),),
        'hurt10': lambda c: (Damage(c.state.players[1].hero_id, 10, c.source_id, DamageKind.EFFECT),),
        'hurt29': lambda c: (Damage(c.state.players[1].hero_id, 29, c.source_id, DamageKind.EFFECT),),
        'fail': lambda c: (_ for _ in ()).throw(ResolutionError('K123 deliberate reaction failure')),
    }
    for name, body in scripts.items():
        r.register_behavior(P + name, body)
        r.register_card(CardDefinition(P + name, name, CardType.SPELL, metadata=META, on_play=P + name,
            targeting=None if name in ('fail', 'wake', 'hurt10', 'hurt29') else TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    r.register_card(CardDefinition(P + 'both', 'Existing native Choose Both', CardType.MINION, health=8,
        metadata=META, choose_both=True))
    r.register_card(CardDefinition(P + 'power', 'Existing Spell Damage', CardType.MINION, health=9,
        metadata=META, spell_damage=2))
    r.register_card(CardDefinition(P + 'shield', 'Original Divine Shield', CardType.MINION, health=5,
        metadata=META, keywords=(Keyword.DIVINE_SHIELD,)))
    if mode:
        def first_entry(c):
            roots = [x for x in c.state.card_summon_history if x.request.cause.source.card_id in ROOTS and
                any(d.outcome == 'delivered' and d.entity.entity_id == c.event.target_id for d in x.deliveries)]
            if not roots:
                return False
            root = roots[0]
            return root == next(x for x in c.state.card_summon_history if
                x.request.cause.source.entity_id == root.request.cause.source.entity_id)
        def watch(c):
            if mode == 'fail':
                return (InvokeBehavior(P + 'fail', c.source_id, 1),)
            extra = (Summon(1, YETI),) if mode == 'fill' else ()
            return (RequestChoice(1, (ChoiceOption('ok', 'Continue', extra),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(P + 'fail', c.source_id, 1),))), c.source_id),)
        r.register_behavior(P + 'watch', watch)
        r.register_trigger_condition(P + 'first', first_entry)
        r.register_card(CardDefinition(P + 'watch', 'First original entry observer', CardType.MINION, health=9,
            metadata=META, limited_triggers=(LimitedTriggerSpec('minion_summoned', P + 'watch', condition_id=P + 'first'),)))
    r.validate()
    return r


class NativeDreadseedTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), mode=None, missing=None, seed=123, deck=(YETI,) * 10, health=30):
        self.config = (mode, missing)
        if mode:
            board = (*board, P + 'watch')
        if health != 30:
            hand = (P + 'hurt' + str(30 - health), *hand)
        g = Game.from_scenario(Scenario((
            PlayerSetup('HERO_06', hand=hand, board=board, deck=deck, mana=50, max_mana=50, mana_cap=50),
            PlayerSetup('HERO_08', board=enemy, deck=(YETI,) * 10),
        ), seed=seed), registry(*self.config))
        if health != 30:
            self.play(g, P + 'hurt' + str(30 - health))
        return g

    def first(self, g, cid, zone='hand'):
        return next(g.state.entities[i] for i in getattr(g.state.players[1], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None, branch=None):
        eid = self.first(g, cid).id
        g.apply(PlayCard(1, eid, target, position=len(g.state.players[1].board)
            if g.registry.card(cid).kind == CardType.MINION else None, branch_id=branch))
        return eid

    def bodies(self, g, source):
        return [g.state.entities[d.entity.entity_id] for root in g.state.card_summon_history
            if root.request.cause.source.entity_id == source for d in root.deliveries if d.outcome == 'delivered']

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def cycle(self, g):
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))

    def hero(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id]

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        fresh = registry.__wrapped__(*self.config)
        other = Game.from_snapshot(saved, fresh)
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry.__wrapped__(*self.config)).snapshot(), saved)
        for player in (1, 2):
            wire = json.dumps(g.for_player(player).observe()) + json.dumps(g.for_player(player).legal_actions()) + json.dumps(g.player_events(player))
            for key in ('resolution_frame', 'rng_state', 'SummonEntryMaterial', 'behavior_id', 'dormancy_id', 'card_summon_history'):
                self.assertNotIn('"' + key + '"', wire)
        return other

    def test_complete_twelve_rows_sixteen_faces_exact_seed_stats_dual_tribes_and_printed_abilities(self):
        data = load_batch()
        r = registry()
        self.assertEqual(len(data['cards'] + data['dependencies'] + data['evidence_only']), 12)
        self.assertEqual(len(data['official_observations']['observations']), 16)
        norm = lambda s: re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]', '', s)
        rows = {x['record']['id']: x['record'] for x in data['cards'] + data['dependencies']}
        for group in ('cards', 'dependencies', 'evidence_only'):
            for row in data[group]:
                self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        for o in data['official_observations']['observations']:
            raw = rows[o['card_id']]
            cn = o['locale'] == 'zh_CN'
            self.assertEqual(o['face']['name'], raw['name' if cn else 'name_en'])
            self.assertEqual(norm(o['face']['text']), norm(raw['text' if cn else 'text_en']))
        for cid in ROOTS + DEPENDENCIES:
            c, raw = r.card(cid), rows[cid]
            self.assertEqual(c.metadata, metadata_from_record(raw))
            self.assertEqual(c.cost, 0 if cid in CHOICE_ONLY else raw['cost'])
            self.assertIsNone(c.spell_school)
        for cid, stats in ((HOUND, (2, 4, 4)), (CROW, (1, 3, 3)), (SERPENT, (3, 5, 5))):
            c = r.card(cid)
            self.assertEqual((c.cost, c.attack, c.health), stats)
            self.assertEqual(c.metadata.tribes, ('beast', 'undead'))
            self.assertEqual(c.dormant_turns, TURNS[cid])
        self.assertEqual(r.card(CROW).keywords, (Keyword.ELUSIVE,))
        self.assertEqual(r.card(SERPENT).keywords, (Keyword.TAUNT, Keyword.LIFESTEAL))
        self.assertIsNone(r.card(CROW).on_awaken)
        self.assertIsNone(r.card(SERPENT).on_awaken)

    def test_eight_new_definitions_preserve_existing_default_and_only_add_three_seed_metadata_rows(self):
        with patch('hs_sim.cards.native_dreadseed_cards.register_native_dreadseed_cards', lambda r: None):
            before = build_registry()
        after = build_registry()
        self.assertEqual(set(after.cards) - set(before.cards), set(ROOTS + DEPENDENCIES))
        self.assertTrue(all(asdict(before.card(cid)) == asdict(after.card(cid)) for cid in before.cards))
        self.assertEqual(set(after.pool_cards) - set(before.pool_cards), set(SEEDS))
        self.assertTrue(all(after.pool_card(cid) == card for cid, card in before.pool_cards.items()))
        self.assertEqual(dict(after.pools), dict(before.pools))
        self.assertEqual(dict(after.generation_families), dict(before.generation_families))
        from hs_sim.engine.representative import build_registry as default
        self.assertEqual(default().fingerprint(), DEFAULT_REPRESENTATIVE_FINGERPRINT)
        for cid in EVIDENCE_ONLY:
            self.assertNotIn(cid, after.cards)

    def test_harvest_draws_original_card_then_one_exact_named_random_seed_without_external_pool(self):
        g = self.game((HARVEST,))
        deck = list(g.state.players[1].deck)
        rng = random.Random()
        rng.setstate(g._rng.getstate())
        expected = SEEDS[rng.randrange(3)]
        source = self.play(g, HARVEST)
        body, = self.bodies(g, source)
        self.assertEqual(body.card_id, expected)
        self.assertEqual(g.state.players[1].hand, [deck[0]])
        self.assertEqual(g.state.players[1].deck, deck[1:])
        self.assertEqual(g._rng.getstate(), rng.getstate())
        self.assertEqual(body.dormancy.remaining_turns, TURNS[expected])
        self.assertEqual(g.state.players[1].mana, 48)
        self.assertEqual(len(g.state.cast_history), 1)
        self.assertEqual(g.state.card_summon_history[-1].request.cause.origin, 'spell_cast')
        self.portable(g)

    def test_harvest_full_board_keeps_actual_draw_and_payment_without_seed_rng(self):
        g = self.game((HARVEST,), board=(YETI,) * 7)
        rng = g._rng.getstate()
        source = self.play(g, HARVEST)
        self.assertFalse(self.bodies(g, source))
        self.assertEqual(len(g.state.players[1].hand), 1)
        self.assertEqual(g.state.players[1].mana, 48)
        self.assertEqual(g._rng.getstate(), rng)
        self.portable(g)

    def test_harvest_fatigue_then_summon_and_lethal_fatigue_stop_use_normal_pipeline(self):
        g = self.game((HARVEST,), deck=())
        source = self.play(g, HARVEST)
        self.assertEqual(self.hero(g).health, 29)
        self.assertEqual(len(self.bodies(g, source)), 1)
        g = self.game((HARVEST,), deck=(), health=1)
        rng = g._rng.getstate()
        source = self.play(g, HARVEST)
        self.assertFalse(self.bodies(g, source))
        self.assertEqual(g._rng.getstate(), rng)
        self.assertEqual(g.state.winner, 2)

    def test_native_battlecry_and_natural_death_each_summon_one_with_distinct_original_causes(self):
        g = self.game((CORRUPTER, P + 'kill'), board=(YETI,))
        left = g.state.players[1].board[0]
        source = self.play(g, CORRUPTER)
        first, = self.bodies(g, source)
        first_cause = g.state.card_summon_history[-1].request.cause
        self.assertEqual((first_cause.origin, first_cause.source.entity_id), ('card_effect', source))
        self.assertEqual(first_cause.source.zone, Zone.BOARD)
        self.assertEqual(len(g.state.battlecry_history), 1)
        self.assertFalse(g.state.deathrattle_history)
        self.play(g, P + 'kill', source)
        first_again, second = self.bodies(g, source)
        self.assertEqual(first_again.id, first.id)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(g.state.players[1].board, [left, second.id, first.id])
        self.assertEqual(g.state.card_summon_history[-1].request.position, 1)
        self.assertEqual(g.state.card_summon_history[-1].request.cause.origin, 'card_effect')
        self.assertEqual(g.state.card_summon_history[-1].request.cause.source.zone, Zone.GRAVEYARD)
        self.assertGreater(g.state.card_summon_history[-1].request.cause.action, first_cause.action)
        self.assertEqual(len(g.state.battlecry_history), 1)
        self.assertEqual(len(g.state.deathrattle_history), 1)
        self.assertEqual(g.state.players[1].mana, 46)
        self.portable(g)

    def test_live_deathrattle_trigger_uses_carrier_right_side_and_does_not_create_battlecry(self):
        g = self.game((P + 'trigger',), board=(YETI, CORRUPTER, YETI))
        left, carrier, right = g.state.players[1].board
        self.assertFalse(g.state.card_summon_history)
        self.play(g, P + 'trigger', carrier)
        body, = self.bodies(g, carrier)
        self.assertEqual(g.state.players[1].board, [left, carrier, body.id, right])
        self.assertEqual(g.state.card_summon_history[-1].request.position, 2)
        self.assertFalse(g.state.battlecry_history)
        self.assertFalse(g.state.death_history)
        self.portable(g)

    def test_slumber_two_named_requests_use_two_independent_random_draws_and_single_payment(self):
        g = self.game((SLUMBER,))
        rng = random.Random()
        rng.setstate(g._rng.getstate())
        expected = tuple(SEEDS[rng.randrange(3)] for _ in range(2))
        source = self.play(g, SLUMBER, branch=SUMMON_BRANCH)
        self.assertEqual(tuple(e.card_id for e in self.bodies(g, source)), expected)
        self.assertEqual(len({e.id for e in self.bodies(g, source)}), 2)
        self.assertEqual(g._rng.getstate(), rng.getstate())
        self.assertEqual((g.state.players[1].mana, len(g.state.cast_history)), (47, 1))
        self.assertTrue(all(e.dormancy is not None for e in self.bodies(g, source)))
        self.portable(g)

    def test_slumber_one_free_slot_or_full_board_rechecks_capacity_before_each_rng(self):
        for count in (6, 7):
            with self.subTest(count=count):
                g = self.game((SLUMBER,), board=(YETI,) * count)
                rng = random.Random()
                rng.setstate(g._rng.getstate())
                if count == 6:
                    rng.randrange(3)
                source = self.play(g, SLUMBER, branch=SUMMON_BRANCH)
                self.assertEqual(len(self.bodies(g, source)), 7 - count)
                self.assertEqual(g._rng.getstate(), rng.getstate())
                self.assertEqual(g.state.players[1].mana, 47)

    def test_slumber_damage_is_spell_damage_all_active_minions_not_heroes_or_dormant_seeds(self):
        g = self.game((SLUMBER,), board=(YETI, HOUND, P + 'power'), enemy=(YETI, P + 'shield'))
        friendly = g.state.players[1].board[0]
        dormant = g.state.players[1].board[1]
        enemy, shield = g.state.players[2].board
        rng = g._rng.getstate()
        self.play(g, SLUMBER, branch=DAMAGE_BRANCH)
        self.assertEqual((g.state.entities[friendly].health, g.state.entities[enemy].health), (1, 1))
        self.assertEqual(g.state.entities[dormant].health, 4)
        self.assertEqual(g.state.entities[shield].health, 5)
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[shield].keywords)
        self.assertEqual((self.hero(g).health, self.hero(g, 2).health), (30, 30))
        self.assertEqual(g._rng.getstate(), rng)
        self.portable(g)

    def test_real_choose_both_summons_first_then_captures_damage_board_after_entry_reaction(self):
        g = self.game((SLUMBER,), board=(P + 'both',), enemy=(YETI,), mode='fill')
        source = self.play(g, SLUMBER, branch=SLUMBER + ':combined')
        self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g)
        for game in (g, other):
            self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(self.bodies(g, source)), 2)
        extra = self.first(g, YETI, 'board')
        self.assertEqual(extra.health, 3)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health, 3)
        self.assertTrue(all(e.health == g.registry.card(e.card_id).health and e.dormancy for e in self.bodies(g, source)))
        self.assertEqual((g.state.players[1].mana, len(g.state.cast_history)), (47, 1))
        self.portable(g)

    def test_branch_choice_is_required_and_descriptors_are_nonphysical_without_extra_payment(self):
        g = self.game((SLUMBER,))
        saved = g.snapshot()
        for branch in (None, 'unknown', SLUMBER + ':combined'):
            with self.subTest(branch=branch), self.assertRaises(IllegalAction):
                self.play(g, SLUMBER, branch=branch)
            self.assertEqual(g.snapshot(), saved)
        for cid in CHOICE_ONLY:
            c = g.registry.card(cid)
            self.assertTrue(c.choice_only)
            self.assertIsNone(c.on_play)
            self.assertNotIn(cid, g.registry.pool_cards)

    def test_three_owner_clocks_keep_identity_opponent_start_does_not_tick_and_wake_has_no_new_summon(self):
        g = self.game(board=SEEDS)
        entities = {g.state.entities[i].card_id: i for i in g.state.players[1].board}
        for n in range(1, 4):
            g.apply(EndTurn(1))
            for cid, eid in entities.items():
                remaining = max(TURNS[cid] - (n - 1), 0)
                self.assertEqual(g.state.entities[eid].dormancy.remaining_turns if remaining else 0, remaining)
            g.apply(EndTurn(2))
            for cid, eid in entities.items():
                e = g.state.entities[eid]
                self.assertEqual(e.card_id, cid)
                self.assertEqual(e.dormancy.remaining_turns if e.dormancy else 0, max(TURNS[cid] - n, 0))
        self.assertFalse(g.state.card_summon_history)
        self.assertFalse(g.state.battlecry_history)
        self.assertEqual(set(g.state.players[1].board), set(entities.values()))
        self.portable(g)

    def test_hound_grants_current_hero_attack_only_at_awake_and_expires_same_turn(self):
        g = self.game(board=(HOUND,))
        self.assertEqual(self.hero(g).attack, 0)
        self.cycle(g)
        self.assertEqual(self.hero(g).attack, 0)
        self.cycle(g)
        self.assertEqual(self.hero(g).attack, 3)
        self.portable(g)
        g.apply(EndTurn(1))
        self.assertEqual(self.hero(g).attack, 0)

    def test_hound_new_sleep_uses_actual_current_controller_for_awake_reward(self):
        g = self.game((P + 'wake', P + 'steal', P + 'sleep'), board=(HOUND,))
        eid = g.state.players[1].board[0]
        self.play(g, P + 'wake')
        self.assertEqual(self.hero(g).attack, 3)
        self.play(g, P + 'steal', eid)
        self.play(g, P + 'sleep', eid)
        g.apply(EndTurn(1))
        self.assertEqual(self.hero(g).attack, 0)
        self.assertEqual(self.hero(g, 2).attack, 3)
        self.assertIsNone(g.state.entities[eid].dormancy)
        self.portable(g)
        g.apply(EndTurn(2))
        self.assertEqual(self.hero(g, 2).attack, 0)

    def test_silenced_awake_hound_never_regains_callback_after_another_sleep(self):
        g = self.game((P + 'wake', P + 'silence', P + 'sleep'), board=(HOUND,))
        eid = g.state.players[1].board[0]
        self.play(g, P + 'wake')
        self.play(g, P + 'silence', eid)
        self.play(g, P + 'sleep', eid)
        self.cycle(g)
        self.assertIsNone(g.state.entities[eid].dormancy)
        self.assertEqual(self.hero(g).attack, 0)
        self.portable(g)

    def test_crow_keeps_elusive_after_wake_and_serpent_lifesteal_uses_normal_combat(self):
        g = self.game((P + 'kill',), board=(CROW, SERPENT), enemy=(YETI,), health=20)
        crow, serpent = g.state.players[1].board
        self.cycle(g)
        self.assertIn(Keyword.ELUSIVE, g.state.entities[crow].keywords)
        with self.assertRaises(IllegalAction):
            self.play(g, P + 'kill', crow)
        self.cycle(g)
        self.cycle(g)
        self.assertIsNone(g.state.entities[serpent].dormancy)
        with self.assertRaises(IllegalAction):
            g.apply(Attack(1, serpent, g.state.players[2].board[0]))
        self.cycle(g)
        g.apply(Attack(1, serpent, g.state.players[2].board[0]))
        self.assertEqual(self.hero(g).health, 25)
        self.assertEqual(g.state.entities[serpent].health, 1)
        self.portable(g)

    def test_first_seed_wait_restores_original_selected_material_then_resumes_remaining_random_work(self):
        for cid, branch in ((HARVEST, None), (CORRUPTER, None), (SLUMBER, SUMMON_BRANCH)):
            with self.subTest(cid=cid):
                g = self.game((cid,), mode='wait')
                source = self.play(g, cid, branch=branch)
                self.assertEqual(len(self.bodies(g, source)), 1)
                saved = g.snapshot()
                other = self.portable(g)
                with self.assertRaises(ResolutionError):
                    self.choose(g, 'bad')
                self.assertEqual(g.snapshot(), saved)
                for game in (g, other):
                    self.choose(game)
                self.assertEqual(g.snapshot(), other.snapshot())
                self.assertEqual(len(self.bodies(g, source)), 2 if cid == SLUMBER else 1)
                self.portable(g)

    def test_entry_failure_rolls_back_original_draw_payment_rng_and_summon_allocation(self):
        for cid, branch in ((HARVEST, None), (CORRUPTER, None), (SLUMBER, SUMMON_BRANCH)):
            with self.subTest(cid=cid):
                g = self.game((cid,), mode='fail')
                saved = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'K123 deliberate'):
                    self.play(g, cid, branch=branch)
                self.assertEqual(g.snapshot(), saved)

    def test_named_complete_unknown_seed_is_never_cropped_before_rng_even_on_full_board(self):
        for count in (0, 7):
            with self.subTest(count=count):
                g = self.game((HARVEST,), board=(YETI,) * count, missing=CROW)
                saved = g.snapshot()
                self.assertNotIn(CROW, g.registry.cards)
                with patch.object(random.Random, 'randrange', side_effect=AssertionError('RNG before complete named validation')) as call:
                    with self.assertRaises(ResolutionError):
                        self.play(g, HARVEST)
                    call.assert_not_called()
                self.assertEqual(g.snapshot(), saved)


if __name__ == '__main__':
    unittest.main()
