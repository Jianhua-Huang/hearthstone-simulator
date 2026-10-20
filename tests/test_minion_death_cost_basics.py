"""Independent death quantity prices, sharing original deaths and queries."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.information import VIEW_VERSION
from hs_sim.engine.player_api import API_VERSION
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (BoardMinionCostSpec, CardClass, CardDefinition, CardType, CostSpec,
    EndTurn, Game, HandCountCostSpec, HeroMissingHealthCostSpec, IllegalAction, InteractableSpec,
    MinionDeathCostSpec, PlayerSetup, PlayerSpellCountCostSpec, PlayerHeroPowerCountCostSpec,
    PlayerSpellManaCostSpec, PlayCard, Rarity, ResolutionError, Scenario, SelectChoice,
    SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.costs import (capture_cost_input, capture_generated_quote_fact, capture_quote_fact, quote_cost)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, CopyMinion, Damage,
    DamageBatch, Destroy, ChangeControl, InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand,
    Silence, Summon, Transform)
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact, validate_intrinsic_history_prefix,
    validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.locations import DestroyLocation
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

GIANT, DRAKE = 'AV_265', 'BRM_025'
PATH = Path(__file__).resolve().parents[1] / 'data/support/minion-death-cost-basics.json'
PIN = 'bb34721e899a4bd477dd10a339ab726a3dc6e3e5ebec4e7b95191536397c19e5'
TURN_PROFILE = 'cost.minion-deaths-both-turn-v1'

def evidence():
    support = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support) != PIN: raise ValueError('Death price full evidence changed')
    for row in support['records']:
        if canonical_digest(row['data']) != row['data_sha256']: raise ValueError('Death price raw changed')
    return {row['id']: row['data'] for row in support['records']}

def registry():
    r = opening_registry()
    for cid, spec, race, card_class, rarity in (
            (GIANT, MinionDeathCostSpec(), 'DEMON', CardClass.DEMON_HUNTER, Rarity.EPIC),
            (DRAKE, MinionDeathCostSpec(TURN_PROFILE), 'DRAGON', CardClass.NEUTRAL, Rarity.COMMON)):
        raw = evidence()[cid]
        r.register_card(CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'],
            attack=raw['attack'], health=raw['health'], metadata=metadata(card_class, rarity=rarity, tribes=(race,)),
            minion_death_cost=spec))
    r.register_card(CardDefinition('death.victim', 'Ordinary victim', CardType.MINION, health=2))
    r.register_card(CardDefinition('death.morph', 'Another ordinary face', CardType.MINION, health=3))
    r.register_card(CardDefinition('death.weapon', 'Uncounted weapon', CardType.WEAPON, attack=1, durability=2))
    r.register_behavior('death.noop', lambda c: ())
    r.register_card(CardDefinition('death.location', 'Uncounted location', CardType.LOCATION,
        durability=2, on_use='death.noop'))
    def held(c, cid=GIANT):
        return next(eid for eid in c.state.players[c.player_id].hand if c.state.entities[eid].card_id == cid)
    def priced(c):
        return next(eid for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id in (GIANT, DRAKE))
    def area(c):
        return (DamageBatch(tuple(Damage(eid, 3, c.source_id) for player in c.state.players.values()
            for eid in player.board if c.state.entities[eid].card_id == 'death.victim')),)
    scripts = {
        'death.area': area,
        'death.acquire': lambda c: (AddToHand(c.player_id, GIANT), AddToHand(c.player_id, DRAKE)),
        'death.populate': lambda c: tuple(Summon(c.player_id, 'death.victim') for _ in range(3)),
        'death.local': lambda c: (ModifyCost(held(c), CostSpec(delta=-4)),),
        'death.external': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-2, card_ids=(GIANT,))),),
        'death.copy': lambda c: (CopyMinion(priced(c), c.player_id, mode='base'),),
        'death.silence': lambda c: (Silence(priced(c)),),
        'death.bounce': lambda c: (ReturnToHand(priced(c)),),
        'death.destroy.weapon': lambda c: (Destroy(c.state.players[c.player_id].weapon_id, c.source_id),),
        'death.destroy.location': lambda c: (DestroyLocation(next(eid for eid in c.state.players[c.player_id].board
            if c.state.entities[eid].card_id == 'death.location'), c.source_id),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    for cid, body in (
            ('death.kill', lambda c: (Destroy(c.target_id, c.source_id),)),
            ('death.damage', lambda c: (Damage(c.target_id, 3, c.source_id),)),
            ('death.take', lambda c: (ChangeControl(c.target_id, c.player_id),)),
            ('death.give', lambda c: (ChangeControl(c.target_id, 3-c.player_id),)),
            ('death.return', lambda c: (ReturnToHand(c.target_id),)),
            ('death.transform', lambda c: (Transform(c.target_id, 'death.morph'),)),
            ('death.remove', lambda c: (RemoveFromGame((MinionReference.capture(c.state.entities[c.target_id]),), c.source_id),))):
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    def batch_pause(c):
        if dict(c.event.data)['death_id'] != 1: return ()
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Finish death events', ()),), c.source_id),)
    r.register_behavior('death.batch.pause', batch_pause)
    r.register_card(CardDefinition('death.batch.watch', 'Observe complete death batch', CardType.MINION,
        health=5, triggers=(TriggerSpec('minion_died', 'death.batch.pause'),)))
    r.register_behavior('death.fail', lambda c: (Destroy(next(eid for eid in c.state.players[c.player_id].board
        if c.state.entities[eid].card_id == 'death.victim'), c.source_id), AddToHand(c.player_id, 'unknown.death.price')))
    def paid_pause(c):
        if c.state.entities[c.event.source_id].card_id != DRAKE: return ()
        victim = next(eid for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id == 'death.victim')
        return (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Later death and acquisition', (Destroy(victim, c.source_id), AddToHand(c.player_id, DRAKE))),
            ChoiceOption('fault', 'Delayed failure', (InvokeBehavior('death.fail', c.source_id, c.player_id),)),
        ), c.source_id),)
    r.register_behavior('death.paid.pause', paid_pause)
    r.register_card(CardDefinition('death.paid.watch', 'Pause paid Drake', CardType.MINION,
        health=5, triggers=(TriggerSpec('card_played', 'death.paid.pause'),)))
    return r

def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({key: value for key, value in saved.items()
        if key not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved

class MinionDeathCostTests(unittest.TestCase):
    def game(self, hand=(GIANT, DRAKE), *, board=(), enemy_board=(), enemy_hand=(), weapon=None, mana=10):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, weapon_card_id=weapon,
                deck=('card.1',)*3, mana=mana, max_mana=10),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy_board, deck=('card.1',)*3,
                mana=10, max_mana=10)), seed=20), registry())
    def source(self, g, cid=GIANT, player=1):
        return next(g.state.entities[eid] for eid in g.state.players[player].hand if g.state.entities[eid].card_id == cid)
    def fact(self, g, cid=GIANT, player=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, cid, player)))
    def price(self, g, cid=GIANT, player=1): return self.fact(g, cid, player).amount
    def play(self, g, cid, target=None):
        eid = self.source(g, cid, g.state.active_player).id
        g.apply(PlayCard(g.state.active_player, eid, target))
        return eid
    def victim(self, g, player=1):
        return next(eid for eid in g.state.players[player].board if g.state.entities[eid].card_id == 'death.victim')
    def twice(self, *, extras=(), enemy=(), board=(), victim_count=2):
        g = self.game((GIANT, DRAKE, 'death.kill', 'death.kill', *extras),
            board=('death.victim',)*victim_count + board, enemy_board=enemy)
        self.play(g, 'death.kill', self.victim(g)); self.play(g, 'death.kill', self.victim(g))
        return g
    def choose(self, g, option='continue'):
        c = g.state.pending_choice
        g.apply(SelectChoice(c.player_id, c.id, (option,)))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry())
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for player in (1, 2): self.assertEqual(other.observe(player), g.observe(player))
        return saved

    def test_two_real_full_raw_records_are_pinned(self):
        raw = evidence()
        original = {v['id']: v for v in json.loads((PATH.parents[1] / 'extracted/cards.json').read_bytes())}
        self.assertEqual(raw, {cid: original[cid] for cid in (GIANT, DRAKE)})
        self.assertEqual([(raw[cid]['cost'], raw[cid]['attack'], raw[cid]['health']) for cid in (GIANT, DRAKE)],
            [(13, 8, 8), (6, 6, 4)])
        self.assertIn('friendly minion that died this game', raw[GIANT]['text_en'])
        self.assertIn('minion that died this turn', raw[DRAKE]['text_en'])

    def test_only_real_finite_profiles_and_one_ordinary_quantity_are_registered(self):
        for profile in (None, True, 'cost.minion-deaths-enemy-game-v1', 'arbitrary.formula'):
            with self.subTest(profile=profile), self.assertRaises(ValueError): MinionDeathCostSpec(profile)
        r = registry()
        for changes in ({'kind': CardType.WEAPON, 'health': 0, 'durability': 2}, {'minion_death_cost': 'formula'},
                {'interactable': InteractableSpec('death.noop')}, {'board_minion_cost': BoardMinionCostSpec()},
                {'hand_count_cost': HandCountCostSpec()}, {'hero_missing_health_cost': HeroMissingHealthCostSpec()},
                {'player_spell_count_cost': PlayerSpellCountCostSpec()},
                {'player_hero_power_count_cost': PlayerHeroPowerCountCostSpec()},
                {'player_spell_mana_cost': PlayerSpellManaCostSpec()}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                r.register_card(replace(r.card(GIANT), id='bad.death.price', **changes))

    def test_empty_history_keeps_both_printed_prices(self):
        g = self.game()
        self.assertEqual((self.price(g), self.price(g, DRAKE)), (13, 6))
        f = self.fact(g).intrinsic.minion_deaths
        self.assertEqual((f.records, f.selected_ids, f.death_history_length, f.next_death_id, f.quantity), ((), (), 0, 1, 0))
        self.portable(g)

    def test_two_friendly_deaths_count_occurrences_not_card_identities(self):
        g = self.twice()
        f = self.fact(g).intrinsic.minion_deaths
        self.assertEqual((self.price(g), self.price(g, DRAKE), f.quantity, f.selected_ids), (11, 4, 2, (1, 2)))
        self.assertEqual([row.card_id for row in f.records], ['death.victim']*2)
        self.assertNotEqual(f.records[0].entity_id, f.records[1].entity_id)
        self.portable(g)

    def test_opponent_death_is_ignored_by_friendly_game_but_counts_this_turn(self):
        g = self.game((GIANT, DRAKE, 'death.kill'), enemy_board=('death.victim',))
        self.play(g, 'death.kill', self.victim(g, 2))
        self.assertEqual((self.price(g), self.price(g, DRAKE)), (13, 5))
        self.assertEqual(self.fact(g).intrinsic.minion_deaths.records, tuple(g.state.death_history))
        self.portable(g)

    def test_friendly_scope_uses_controller_at_death_instead_of_original_owner(self):
        g = self.game((GIANT, DRAKE, 'death.take', 'death.kill'),
            enemy_board=('death.victim',), enemy_hand=(GIANT,))
        eid = self.victim(g, 2)
        self.play(g, 'death.take', eid); self.play(g, 'death.kill', eid)
        row = g.state.death_history[0]
        self.assertEqual((row.owner, row.controller, self.price(g), self.price(g, player=2)), (2, 1, 12, 13))
        self.portable(g)

    def test_given_away_original_friendly_minion_is_not_counted_for_owner(self):
        g = self.game((GIANT, DRAKE, 'death.give', 'death.kill'),
            board=('death.victim',), enemy_hand=(GIANT,))
        eid = self.victim(g)
        self.play(g, 'death.give', eid); self.play(g, 'death.kill', eid)
        self.assertEqual((self.price(g), self.price(g, player=2)), (13, 12))
        self.portable(g)

    def test_complete_death_batch_is_visible_before_first_individual_death_choice(self):
        g = self.game((GIANT, DRAKE, 'death.area'), board=('death.victim',)*2 + ('death.batch.watch',),
            enemy_board=('death.victim',))
        self.play(g, 'death.area')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((self.price(g), self.price(g, DRAKE)), (11, 3))
        f = self.fact(g).intrinsic.minion_deaths
        self.assertEqual((len(f.records), len({r.batch for r in f.records})), (3, 1))
        saved = self.portable(g)
        other = Game.from_snapshot(saved, registry())
        self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())

    def test_unrecorded_fatal_state_is_not_a_death_occurrence(self):
        g = self.game(board=('death.victim',))
        state = g.state
        state.entities[self.victim(g)].damage = 2
        from hs_sim.engine.death_causes import sync_state
        sync_state(state)
        source = state.entities[self.source(g).id]
        self.assertEqual(quote_cost(state, g.registry, source).amount, 13)
        self.assertEqual(state.death_history, [])
        self.assertEqual(g.state.entities[self.victim(g)].health, 2)

    def test_turn_scope_resets_while_all_game_scope_retains_old_deaths(self):
        g = self.twice(extras=('death.kill',), victim_count=3)
        g.apply(EndTurn(1))
        self.assertEqual((self.price(g), self.price(g, DRAKE)), (11, 6))
        g.apply(EndTurn(2)); self.play(g, 'death.kill', self.victim(g))
        self.assertEqual((self.price(g), self.price(g, DRAKE)), (10, 5))
        self.portable(g)

    def test_deaths_before_card_acquisition_are_retained(self):
        g = self.game(('death.kill', 'death.acquire'), board=('death.victim',))
        self.play(g, 'death.kill', self.victim(g)); self.play(g, 'death.acquire')
        self.assertEqual((self.price(g), self.price(g, DRAKE)), (12, 5))
        self.assertEqual(self.source(g).abilities, [])
        self.portable(g)

    def test_actual_damage_and_destroy_each_record_one_death(self):
        g = self.game((GIANT, DRAKE, 'death.damage', 'death.kill'), board=('death.victim',)*2)
        self.play(g, 'death.damage', self.victim(g)); self.play(g, 'death.kill', self.victim(g))
        self.assertEqual([r.cause.kind for r in g.state.death_history], ['damage', 'destroy'])
        self.assertEqual((self.price(g), self.price(g, DRAKE)), (11, 4))
        self.portable(g)

    def test_bounce_transform_and_non_death_removal_do_not_count(self):
        for operation in ('death.return', 'death.transform', 'death.remove'):
            with self.subTest(operation=operation):
                g = self.game((GIANT, DRAKE, operation), board=('death.victim',))
                self.play(g, operation, self.victim(g))
                self.assertEqual((self.price(g), self.price(g, DRAKE), g.state.death_history), (13, 6, []))
                self.portable(g)

    def test_weapon_and_location_destructions_remain_in_prefix_but_do_not_count(self):
        g = self.game((GIANT, DRAKE, 'death.destroy.weapon', 'death.destroy.location', 'death.kill'),
            board=('death.location', 'death.victim'), weapon='death.weapon')
        self.play(g, 'death.destroy.weapon'); self.play(g, 'death.destroy.location')
        self.assertEqual((self.price(g), self.price(g, DRAKE)), (13, 6))
        self.play(g, 'death.kill', self.victim(g))
        f = self.fact(g).intrinsic.minion_deaths
        self.assertEqual((len(f.records), f.selected_ids, f.quantity, f.next_death_id), (3, (3,), 1, 4))
        self.portable(g)

    def test_summoning_and_live_board_size_do_not_count_as_deaths(self):
        g = self.game((GIANT, DRAKE, 'death.populate'))
        self.play(g, 'death.populate')
        self.assertEqual((len(g.state.players[1].board), self.price(g), self.price(g, DRAKE)), (3, 13, 6))
        self.portable(g)

    def test_six_real_deaths_clamp_turn_price_to_zero(self):
        g = self.game((GIANT, DRAKE, 'death.area'), board=('death.victim',)*3, enemy_board=('death.victim',)*3)
        self.play(g, 'death.area')
        self.assertEqual((self.price(g), self.price(g, DRAKE)), (10, 0))
        self.play(g, DRAKE)
        self.assertEqual(g.state.play_history[-1].cost, 0)
        self.portable(g)

    def test_pure_physical_and_generated_quotes_share_original_query(self):
        g = self.twice(); before = g.snapshot()
        for cid in (GIANT, DRAKE):
            for _ in range(2):
                f = capture_generated_quote_fact(g.state, g.registry, 1, cid)
                validate_generated_quote_fact(g.registry, f)
                self.assertEqual(f.amount, self.price(g, cid))
                g.for_player(1).legal_actions()
        self.assertEqual(g.snapshot(), before)

    def test_local_and_external_cost_layers_follow_original_death_quantity(self):
        g = self.twice(extras=('death.local', 'death.external'))
        self.play(g, 'death.local'); self.play(g, 'death.external')
        f = self.fact(g)
        self.assertEqual((f.intrinsic.amount, f.local_amount, f.amount), (11, 7, 5))
        generated = capture_generated_quote_fact(g.state, g.registry, 1, GIANT, cost=CostSpec(delta=-4))
        self.assertEqual(generated.amount, 5)
        self.portable(g)

    def test_player_display_legal_submission_and_actual_payment_use_same_deaths(self):
        g = self.twice(); port = g.for_player(1); dto = port.legal_actions()
        view = next(v for v in g.observe(1)['players'][0]['hand'] if v['card_id'] == DRAKE)
        action = next(v for v in dto['actions'] if v.get('card') == view['ref'])
        self.assertEqual(view['cost']['amount'], 4)
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (4, 6))
        self.portable(g)

    def test_insufficient_payment_preserves_deaths_accounts_and_rng(self):
        g = self.twice(); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, GIANT)
        self.assertEqual(g.snapshot(), before)

    def test_printed_copy_silence_and_bounce_requery_player_history(self):
        g = self.twice(extras=('death.local', 'death.copy', 'death.silence', 'death.bounce'))
        self.play(g, 'death.local'); self.play(g, GIANT)
        self.play(g, 'death.copy'); self.play(g, 'death.silence'); self.play(g, 'death.bounce')
        self.assertEqual(self.price(g), 11)
        self.portable(g)

    def test_paid_choice_portability_and_later_death_keep_original_price(self):
        g = self.twice(board=('death.paid.watch',), victim_count=3)
        self.play(g, DRAKE)
        stage = g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.assertEqual((stage.minion_deaths.quantity, stage.amount), (2, 4))
        saved = self.portable(g)
        for current in (g, Game.from_snapshot(saved, registry()), g.clone(), replay(build_replay(g), registry())):
            self.choose(current)
            self.assertEqual(self.price(current, DRAKE), 3)
            validate_intrinsic_history_prefix(stage, current.state, current.registry)
            self.assertEqual(current.state.play_history[2].submitted_cost.quote.intrinsic, stage)
        self.portable(g)

    def test_old_turn_price_prefix_restores_after_actual_turn_handoff(self):
        g = self.twice(); self.play(g, DRAKE)
        stage = g.state.play_history[-1].submitted_cost.quote.intrinsic
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        validate_intrinsic_history_prefix(stage, g.state, g.registry)
        self.assertEqual(stage.minion_deaths.quantity, 2)
        self.assertEqual(self.price(g), 11)
        self.portable(g)

    def test_delayed_error_rolls_back_new_death_and_waiting_state(self):
        g = self.twice(board=('death.paid.watch',), victim_count=3); self.play(g, DRAKE)
        before = self.portable(g)
        with self.assertRaisesRegex(ResolutionError, 'unknown.death.price'): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)
        self.choose(g); self.portable(g)

    def test_complete_death_fact_requires_original_cursor_order_and_quantity(self):
        g = self.twice(); f = self.fact(g).intrinsic.minion_deaths
        for changes in ({'records': f.records[:1]}, {'records': tuple(reversed(f.records))},
                {'death_history_length': 1}, {'next_death_id': 4}, {'next_death_batch': f.records[-1].batch},
                {'quantity': 1}, {'after': 12}, {'selected_ids': (2, 1)}, {'selected_ids': (1, 1)},
                {'selected_ids': (1, True)}, {'turn': True}, {'next_entity_id': f.records[-1].entity_id}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(f, **changes)

    def test_frozen_selection_cannot_change_scope_or_drop_a_known_death(self):
        g = self.twice(); stage = self.fact(g).intrinsic; f = stage.minion_deaths
        bad = replace(stage, minion_deaths=replace(f, selected_ids=(1,), quantity=1, after=12), amount=12)
        with self.assertRaisesRegex(ValueError, 'complete original minion selection'):
            validate_intrinsic_stage_fact(g.registry, bad)
        with self.assertRaises(ValueError): replace(stage, minion_deaths=replace(f, player_id=2))

    def test_nonselected_unknown_death_face_is_not_hidden_by_zero_count(self):
        g = self.game((GIANT, 'death.kill'), enemy_board=('death.victim',))
        self.play(g, 'death.kill', self.victim(g, 2))
        stage = self.fact(g).intrinsic; f = stage.minion_deaths; row = f.records[0]
        changed = replace(row, card_id='unknown.death.price', cause=replace(row.cause, target_card_id='unknown.death.price'))
        bad = replace(stage, minion_deaths=replace(f, records=(changed,)))
        with self.assertRaisesRegex(ValueError, 'unknown.death.price'): validate_intrinsic_stage_fact(g.registry, bad)

    def test_nonminion_board_destruction_cannot_be_selected_as_a_minion(self):
        g = self.game((GIANT, 'death.destroy.location'), board=('death.location',))
        self.play(g, 'death.destroy.location')
        stage = self.fact(g).intrinsic; f = stage.minion_deaths
        bad = replace(stage, minion_deaths=replace(f, selected_ids=(1,), quantity=1, after=12), amount=12)
        with self.assertRaisesRegex(ValueError, 'complete original minion selection'):
            validate_intrinsic_stage_fact(g.registry, bad)

    def test_original_full_cause_allocation_and_physical_prefix_are_bound(self):
        g = self.twice(); stage = self.fact(g).intrinsic; f = stage.minion_deaths
        row = f.records[0]
        with self.assertRaises(ValueError):
            replace(f, records=(replace(row, cause=replace(row.cause, source_id=f.next_entity_id)), f.records[1]))
        # A structurally valid repeated entity in different batches is still two
        # occurrences. Borrowing today's other physical root cannot authenticate
        # it as the original first death, even when the count stays two.
        borrowed = replace(row, entity_id=f.records[1].entity_id, cause=f.records[1].cause)
        changed = replace(stage, minion_deaths=replace(f, records=(borrowed, f.records[1])))
        validate_intrinsic_stage_fact(g.registry, changed)
        with self.assertRaisesRegex(ValueError, 'original physical destruction prefix'):
            validate_intrinsic_history_prefix(changed, g.state, g.registry)

    def test_full_origin_recomputes_original_inventory_and_physical_subject_allocator(self):
        g = self.twice(extras=('death.kill',), victim_count=3); f = self.fact(g); stage = f.intrinsic
        validate_intrinsic_origin(stage, g.state, g.registry)
        with self.assertRaises(ValueError):
            replace(f, quote_input=replace(f.quote_input, source_id=stage.minion_deaths.next_entity_id))
        self.play(g, 'death.kill', self.victim(g))
        validate_intrinsic_history_prefix(stage, g.state, g.registry)
        with self.assertRaises(ValueError): validate_intrinsic_origin(stage, g.state, g.registry)

    def test_rehashed_wire_cannot_drop_or_rewrite_complete_original_deaths(self):
        g = self.twice(); self.play(g, DRAKE); saved = self.portable(g)
        for edit in ('quantity', 'missing_field', 'missing_fact', 'extra', 'drop', 'cursor', 'source', 'cause', 'selected', 'zone', 'boolean'):
            bad = deepcopy(saved)
            stage = bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']
            f = stage['minion_deaths']
            if edit == 'quantity': f['quantity'] += 1
            elif edit == 'missing_field': del stage['minion_deaths']
            elif edit == 'missing_fact': stage['minion_deaths'] = None
            elif edit == 'extra': f['invented'] = 1
            elif edit == 'drop': f['records'].pop()
            elif edit == 'cursor': f['death_history_length'] += 1
            elif edit == 'source': f['records'][0]['entity_id'] = f['records'][1]['entity_id']
            elif edit == 'cause': f['records'][0]['cause']['source_card_id'] = 'unknown.death.price'
            elif edit == 'selected': f['selected_ids'] = [1]
            elif edit == 'zone': f['records'][0]['zone'] = 'weapon'
            else: f['records'][0]['controller'] = True
            with self.subTest(edit=edit), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())

    def test_player_costs_hide_internal_death_inventory_and_opponent_hand(self):
        g = self.game((GIANT, DRAKE, 'death.kill'), board=('death.victim',), enemy_hand=(GIANT, 'card.1'))
        self.play(g, 'death.kill', self.victim(g)); own = g.observe(1)
        self.assertEqual(own['players'][0]['hand'][0]['cost']['amount'], 12)
        self.assertTrue(all(row['card_id'] is None and row.get('cost') is None for row in own['players'][1]['hand']))
        for secret in ('minion_deaths', 'death_history_length', 'next_death_id', 'submitted_cost', 'payment_state'):
            self.assertNotIn(secret, json.dumps(own))

    def test_default_none_and_current_protocol_reject_prior_saved_shapes(self):
        g = self.game(('card.1',))
        self.assertIsNone(self.fact(g, 'card.1').intrinsic.minion_deaths)
        self.play(g, 'card.1'); saved = self.portable(g)
        self.assertEqual((g.ruleset.id, g.mechanics.version, saved['schema_version']),
            ('prototype-v302', CORE_EFFECTS_VERSION, SNAPSHOT_SCHEMA_VERSION))
        self.assertEqual((g.observe(1)['version'], g.for_player(1).observe()['version']),
            (VIEW_VERSION, API_VERSION))
        for version in (1, 174, 175, 176, 217, True, '177'):
            bad = deepcopy(saved); bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaisesRegex(SnapshotError, f'schemas 1 through {SNAPSHOT_SCHEMA_VERSION-1}'):
                Game.from_snapshot(bad, registry())

if __name__ == '__main__': unittest.main()
