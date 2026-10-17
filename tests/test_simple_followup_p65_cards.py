"""Original native deliveries, distance plans, actual casts and private boundaries."""
from dataclasses import asdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards import simple_followup_p65_cards as cards
from hs_sim.cards.simple_followup_p65_cards import (MOTHER, DRAKREST, TOTEM, UMBRA, SHOT,
    ANCESTOR, WORMHOLE, SHADES, RIFT, OSK, SHADE, ROOTS, PREFIX, POOL_ID, load_batch,
    register_simple_followup_p65_cards)
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, ChoicePurpose,
    EndTurn, Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice,
    SpellSchool, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.bonus_effects import BONUS_EFFECTS
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, Draw, GainArmor,
    InvokeBehavior, RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import LimitedTriggerSpec, SummonQuantitySpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.targets import canonical_digest

TEST = 'p65.test.'
YETI = 'CORE_CS2_182'
A, B, SEED, CHILD, DUAL, ALL, SINGLE, NONE, DR, MAGE_DR, DRUID_DR, UNKNOWN, UNKNOWN_TRIBE, WATCH = (
    TEST + s for s in ('a', 'b', 'seed', 'child', 'dual', 'all', 'single', 'none', 'dr', 'mage_dr',
        'druid_dr', 'unknown', 'unknown_tribe', 'watch'))
H, SPELL, LOC, STEALTH = (TEST + s for s in ('hand', 'spell', 'loc', 'stealth'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
MEMBERS = ((DUAL, 2), (ALL, 1), (SINGLE, 4), (NONE, 1), (DR, 1), (MAGE_DR, 1), (DRUID_DR, 1))
CONTEXT = GenerationContext('p65-complete-explicit-fixture', 'experimental')
SOURCE_PIN = hashlib.sha256(Path(__file__).read_bytes() + Path(cards.__file__).read_bytes()
    + cards.BATCH_PATH.read_bytes()).hexdigest()


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata', lambda r: None): r = build_registry()
    present = tuple(cid in r.cards for cid in ROOTS)
    if not any(present): register_simple_followup_p65_cards(r)
    elif not all(present): raise AssertionError('P65 requires complete assigned assembly')
    register_candidate_pool_metadata(r); r.validate(); return r


def registry(mode=None, members=MEMBERS):
    r = batch_registry(); r.register_behavior(TEST + 'noop', lambda c: ())
    r.register_behavior(TEST + 'armor', lambda c: (GainArmor(c.player_id, 1),))
    for cid, attack, health, tribes in ((A, 3, 20, ()), (B, 1, 20, ()), (CHILD, 1, 1, ()),
            (DUAL, 2, 5, ('beast', 'dragon')), (ALL, 2, 5, ('all',)), (SINGLE, 3, 5, ('beast',)),
            (NONE, 2, 5, ())):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=3, attack=attack, health=health,
            metadata=CardMetadata(cid in (DUAL, ALL, SINGLE, NONE), (CardClass.NEUTRAL,), Rarity.COMMON, tribes=tribes)))
    for cid, cls in ((DR, CardClass.NEUTRAL), (MAGE_DR, CardClass.MAGE), (DRUID_DR, CardClass.DRUID)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=6, attack=1, health=4,
            deathrattle=TEST + 'armor', metadata=CardMetadata(True, (cls,), Rarity.COMMON, tribes=('undead',))))
    r.register_card(CardDefinition(UNKNOWN_TRIBE, 'Unknown printed tribe facts', CardType.MINION, cost=3, health=5,
        metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=None)))
    r.register_card(CardDefinition(STEALTH, 'Auto-target witness', CardType.MINION, health=1, keywords=(Keyword.STEALTH,), metadata=META))
    r.register_card(CardDefinition(TEST + 'power', 'Spell Damage2', CardType.MINION, health=20, spell_damage=2, metadata=META))
    r.register_card(CardDefinition(TEST + 'double', 'Native quantity source', CardType.MINION, health=20,
        summon_quantities=(SummonQuantitySpec(2),), metadata=META))
    r.register_card(CardDefinition(LOC, 'Physical non-minion slot', CardType.LOCATION, durability=2, on_use=TEST + 'noop', metadata=META))
    for cid, cost, school in ((H, 8, None), (SPELL, 0, None), (TEST + 'nature', 0, SpellSchool.NATURE), (TEST + 'fire', 0, SpellSchool.FIRE)):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=cost, spell_school=school, on_play=TEST + 'noop', metadata=META))
    r.register_behavior(TEST + 'seed', lambda c: (SummonByCard(c.player_id,
        (SummonEntryMaterial(CHILD),), SummonCause.capture(c)),))
    r.register_card(CardDefinition(SEED, 'Recast death window', CardType.MINION, health=1, deathrattle=TEST + 'seed', metadata=META))
    def fail(c): raise ResolutionError('P65 deliberate continuation failure')
    def reenter(c):
        return (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, cause=SummonCause.capture(c)),)
    def copy(c, mode):
        e = next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id == ANCESTOR)
        return (CopyCard(CardReference.capture(e), 1, mode=mode, source_id=c.source_id),)
    scripts = dict(kill=lambda c: (Destroy(c.target_id, c.source_id),),
        hit=lambda c: (Damage(c.target_id, 2, c.source_id),), reenter=reenter, fail=fail,
        auto=lambda c: (CastSpell(c.player_id, TEST + 'nature', c.source_id),),
        acquire=lambda c: (AddToHand(c.player_id, ANCESTOR, c.source_id),),
        copy=lambda c: copy(c, 'current'), base=lambda c: copy(c, 'base'))
    for name, body in scripts.items():
        r.register_behavior(TEST + name, body)
        driver = name in ('auto', 'copy', 'base')
        r.register_card(CardDefinition(TEST + name, name, CardType.MINION if driver else CardType.SPELL,
            health=1 if driver else 0, on_play=None if driver else TEST + name,
            battlecry=TEST + name if driver else None,
            targeting=TargetSpec() if name in ('kill', 'hit') else None, metadata=META))
    r.register_behavior(TEST + 'counter', lambda c: (CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id != c.player_id else ())
    r.register_card(CardDefinition(TEST + 'counter', 'Counter witness', CardType.MINION, health=20,
        triggers=(TriggerSpec('card_committed', TEST + 'counter'),), metadata=META))
    r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 3,
        CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=('beast', 'dragon')),
        battlecry=False, deathrattle=True, choose_one=False))
    for cid, weight in members:
        if cid not in r.pool_cards: r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID, 'p65-complete-finite-v1', CONTEXT.target_id, CONTEXT.mode,
        tuple(PoolMember(cid, weight) for cid, weight in members), complete=True))
    if mode:
        event = dict(rift='health_resolved', entry='minion_summoned', bonus='ability_granted')[mode]
        def eligible(c):
            if mode == 'rift': return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id == RIFT
            if mode == 'entry': return c.state.entities[c.event.target_id].card_id in (SHADE, SINGLE, DUAL, ALL, DR, MAGE_DR)
            return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id == SHADES
        def watch(c):
            options = [ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Fail', (InvokeBehavior(TEST + 'fail', c.source_id, 1),))]
            if mode == 'rift':
                target = c.state.players[2].board[0]
                options.append(ChoiceOption('cycle', 'Original left neighbor leaves and reenters',
                    (ReturnToHand(target), InvokeBehavior(TEST + 'reenter', c.source_id, 2, target))))
            else: options.append(ChoiceOption('kill', 'Original recipient dies', (Destroy(c.event.target_id, c.source_id),)))
            return (RequestChoice(1, tuple(options), c.source_id),)
        r.register_trigger_condition(TEST + 'eligible', eligible); r.register_behavior(TEST + 'watch', watch)
        r.register_card(CardDefinition(WATCH, 'Actual checkpoint witness', CardType.MINION, health=20,
            limited_triggers=(LimitedTriggerSpec(event, TEST + 'watch', condition_id=TEST + 'eligible'),), metadata=META))
    return r


@lru_cache(maxsize=None)
def fixture_registry(mode, members, role, source_pin):
    if role not in ('writer', 'reader') or source_pin != SOURCE_PIN: raise AssertionError('Incomplete immutable fixture key')
    r = registry(mode, members); r.freeze(); return r


class SimpleFollowupP65Tests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), deck=(YETI,) * 12, enemy_hand=(), mode=None, members=MEMBERS):
        self.config = mode, members
        if mode: board = (WATCH,) + board
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
            mana=40, max_mana=40, mana_cap=40, hand_cap=None),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(YETI,) * 12,
                mana=40, max_mana=40, mana_cap=40)), seed=6565, generation_context=CONTEXT),
            fixture_registry(mode, members, 'writer', SOURCE_PIN))

    def first(self, g, cid, zone='hand', player=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None, player=1):
        e = self.first(g, cid, player=player); g.apply(PlayCard(player, e.id, target_id=target,
            position=len(g.state.players[player].board) if e.kind == CardType.MINION else None)); return e.id

    def choose(self, g, key):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def keep(self, g):
        if g.state.pending_choice is not None and g.state.pending_choice.purpose == ChoicePurpose.REWIND: self.choose(g, 'keep')

    def portable(self, g):
        reader = fixture_registry(*self.config, 'reader', SOURCE_PIN)
        self.assertIsNot(g.registry, reader); self.assertEqual(g.registry.fingerprint(), reader.fingerprint())
        saved = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved); self.assertIsNot(g.state, other.state)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe()) + json.dumps(g.for_player(p).legal_actions()) + json.dumps(g.player_events(p))
            for key in ('rng_state', 'resolution_frame', 'behavior_id', 'source_json', 'death_history', 'exclude_card_ids'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_a0_shades_actual_ordered_group_four_original_recipients_two_bonuses_and_rewind_restore(self):
        g = self.game(hand=(SHADES,)); source = self.play(g, SHADES)
        self.assertEqual(len(g.state.players[1].board), 4)
        for i in g.state.players[1].board:
            e = g.state.entities[i]; self.assertEqual(e.card_id, SHADE)
            self.assertEqual(len(set(e.keywords) & set(BONUS_EFFECTS)), 2)
        self.assertEqual(g.state.ordered_group_history[-1].status, 'completed')
        self.assertEqual(g.state.ordered_group_history[-1].request.group.cause.source.entity_id, source)
        self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.REWIND); other = self.portable(g)
        for running in (g, other): self.keep(running)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_a1_umbra_native_discover_original_completion_triggers_deathrattle_without_hand_delivery(self):
        g = self.game(hand=(UMBRA,)); self.play(g, UMBRA)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {DR, MAGE_DR})
        saved = g.snapshot()
        with self.assertRaises(IllegalAction): self.choose(g, 'missing')
        self.assertEqual(g.snapshot(), saved); other = self.portable(g)
        for running in (g, other):
            q = running.state.pending_choice; self.choose(running, next(o.id for o in q.options if o.card_id == DR))
            self.assertEqual(running.state.entities[running.state.players[1].hero_id].armor, 1)
            self.assertFalse(running.state.players[1].hand); self.assertEqual(self.first(running, DR, 'board').health, 4)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_a2_wormhole_native_pool_entry_forced_random_enemy_and_actual_rewind_retry(self):
        g = self.game(hand=(WORMHOLE,), enemy=(B,), members=((SINGLE, 1),)); self.play(g, WORMHOLE)
        self.assertEqual(len(g.state.players[1].board), 1)
        self.assertTrue(g.state.character_attack_history[-1].declaration.forced)
        other = self.portable(g)
        for running in (g, other):
            self.choose(running, 'retry'); self.keep(running)
            self.assertEqual(len(running.state.players[1].board), 1)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_a3_osk_original_enemy_group_forces_real_friendly_combat_and_singleton_skips_rng(self):
        g = self.game(hand=(OSK,), enemy=(A, B)); self.play(g, OSK)
        self.assertEqual(len(g.state.character_attack_history), 2)
        self.assertTrue(all(r.declaration.forced and r.declaration.combat_relation == 'friendly_minions' for r in g.state.character_attack_history))
        self.assertEqual(self.first(g, A, 'board', 2).health, 18); self.assertEqual(self.first(g, B, 'board', 2).health, 14); self.portable(g)
        g = self.game(hand=(OSK,), enemy=(A,)); rng = g._rng.getstate(); self.play(g, OSK)
        self.assertEqual(g._rng.getstate(), rng); self.assertFalse(g.state.character_attack_history); self.portable(g)

    def test_complete_ten_definitions_sixteen_raws_twenty_six_faces_four_actual_links_and_withdrawn_family(self):
        from tools.card_batch import check_face
        d = load_batch(); rows = {x['record']['id']: x['record'] for k in ('cards', 'existing_dependencies', 'evidence_only') for x in d[k]}
        self.assertEqual((len(d['cards']), len(rows), len(d['official_observations'])), (10, 16, 26))
        self.assertEqual((len(d['collectible_candidate_roots']), len(d['noncollectible_ids'])), (9, 1))
        faces = {(o['card_id'], o['locale']): o['face'] for o in d['official_observations']}
        for o in d['official_observations']:
            check_face(rows[o['card_id']], o['face'], o['locale'], numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
        self.assertEqual(len(d['exact_parent_child_links']), 4)
        for e in d['exact_parent_child_links']:
            self.assertEqual(rows[e['child']]['dbf_id'], e['dbf_id']); self.assertIn(e['dbf_id'], faces[e['parent'], e['locale']]['childIds'])
        self.assertEqual(set(d['withdrawn_ids']), {'TIME_443', 'TIME_443t', 'TIME_443t2'})
        self.assertFalse(d['parents_implemented'] or d['formal_pool_complete'] or d['cn_calibrated'] or d['reachability_complete'])

    def test_old_full_definitions_pool_rows_and_existing_shade_remain_exact(self):
        before, after = build_registry(), batch_registry()
        self.assertEqual(set(after.cards) - set(before.cards), set(ROOTS) - set(before.cards))
        for cid, value in before.cards.items(): self.assertEqual(value, after.card(cid))
        for cid, value in before.pool_cards.items(): self.assertEqual(value, after.pool_card(cid))
        self.assertEqual(canonical_digest(asdict(after.card(SHADE))), load_batch()['existing_dependency_definition_pins'][SHADE])

    def test_mother_original_middle_hand_distances_and_actual_payment_once(self):
        g = self.game(hand=(MOTHER,) + (H,) * 7); ids = g.state.players[1].hand[1:]; mana = g.state.players[1].mana
        self.play(g, MOTHER); self.portable(g); self.choose(g, str(ids[3]))
        self.assertEqual([g.quote_cost(i).amount for i in ids], [6, 5, 4, 3, 4, 5, 6])
        self.assertEqual(g.state.players[1].mana, mana - 9); self.portable(g)

    def test_mother_edge_original_zero_floor_and_empty_hand_no_choice_or_rng(self):
        g = self.game(hand=(MOTHER, SPELL) + (H,) * 6); ids = g.state.players[1].hand[1:]
        self.play(g, MOTHER); self.choose(g, str(ids[0]))
        self.assertEqual([g.quote_cost(i).amount for i in ids], [0, 4, 5, 6, 7, 8, 8]); self.portable(g)
        g = self.game(hand=(MOTHER,)); rng = g._rng.getstate(); self.play(g, MOTHER)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_rift_original_distance_spell_bonus_quoted_once_and_nonminion_slots_not_collapsed(self):
        g = self.game(hand=(RIFT,), board=(TEST + 'power',), enemy=(B,) * 7)
        ids = tuple(g.state.players[2].board); self.play(g, RIFT, ids[0])
        self.assertEqual([g.state.entities[i].health for i in ids], [13, 14, 15, 16, 17, 18, 19]); self.portable(g)
        g = self.game(hand=(RIFT,), enemy=(B, LOC, B, B)); ids = tuple(g.state.players[2].board)
        self.play(g, RIFT, ids[0]); self.assertEqual([g.state.entities[i].health for i in (ids[0], ids[2], ids[3])], [15, 17, 18]); self.portable(g)

    def test_rift_original_neighbor_reentry_skips_without_shifting_remaining_distances_wait_restore_rollback(self):
        g = self.game(hand=(RIFT,), enemy=(B, B, B), mode='rift'); left, center, right = g.state.players[2].board
        self.play(g, RIFT, center); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(saved, g.snapshot()); other = self.portable(g)
        for running in (g, other):
            self.choose(running, 'cycle'); self.assertEqual([running.state.entities[i].health for i in (left, center, right)], [20, 15, 16])
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_nature_held_fact_only_own_real_nature_cast_and_battlecry_gains_then_draws(self):
        g = self.game(hand=(ANCESTOR, TEST + 'fire', TEST + 'auto')); held = self.first(g, ANCESTOR).id
        self.play(g, TEST + 'fire'); self.assertEqual(progress_ability(g.state.entities[held]).progress_completions, 0)
        self.play(g, TEST + 'auto'); self.assertEqual(progress_ability(g.state.entities[held]).progress_completions, 1)
        source = self.play(g, ANCESTOR); self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (3, 4))
        self.assertEqual(len(g.state.draw_history), 1); self.portable(g)

    def test_nature_current_copy_retains_fact_base_copy_and_mid_payload_acquisition_do_not(self):
        g = self.game(hand=(ANCESTOR, TEST + 'nature', TEST + 'copy', TEST + 'base'))
        self.play(g, TEST + 'nature'); self.play(g, TEST + 'copy'); self.play(g, TEST + 'base')
        values = [progress_ability(g.state.entities[i]).progress_completions for i in g.state.players[1].hand if g.state.entities[i].card_id == ANCESTOR]
        self.assertEqual(values, [1, 1, 0]); self.portable(g)
        g = self.game(hand=(TEST + 'acquire',)); self.play(g, TEST + 'acquire'); source = self.play(g, ANCESTOR)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (2, 3)); self.assertFalse(g.state.draw_history); self.portable(g)

    def test_shot_actual_death_reactions_create_next_candidate_and_each_recast_is_new_free_physical_spell(self):
        g = self.game(hand=(SHOT,), enemy=(SEED,)); mana = g.state.players[1].mana
        self.play(g, SHOT, self.first(g, SEED, 'board', 2).id)
        self.assertFalse(g.state.players[2].board); self.assertEqual([c.origin for c in g.state.cast_history], ['hand', 'effect'])
        self.assertEqual(len({c.source_id for c in g.state.cast_history}), 2)
        self.assertEqual(g.state.players[1].mana, mana - 2); self.assertEqual(len(g.state.play_history), 1); self.portable(g)

    def test_shot_automatic_domain_keeps_stealthed_enemy_but_manual_target_is_rejected(self):
        g = self.game(hand=(SHOT,), enemy=(CHILD, STEALTH)); hidden = self.first(g, STEALTH, 'board', 2).id; saved = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, SHOT, hidden)
        self.assertEqual(saved, g.snapshot()); self.play(g, SHOT, self.first(g, CHILD, 'board', 2).id)
        self.assertFalse(g.state.players[2].board); self.assertEqual(len(g.state.cast_history), 2); self.portable(g)

    def test_shot_survival_or_counter_does_not_create_recasts_or_rng(self):
        for enemy in ((B,), (B, TEST + 'counter')):
            g = self.game(hand=(SHOT,), enemy=enemy); rng = g._rng.getstate()
            self.play(g, SHOT, self.first(g, B, 'board', 2).id)
            self.assertFalse(any(c.origin == 'effect' for c in g.state.cast_history)); self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_drakrest_actual_minion_attack_damages_other_enemy_group_but_hero_attack_does_not(self):
        g = self.game(board=(DRAKREST,), enemy=(B, B, B)); source = self.first(g, DRAKREST, 'board').id; ids = tuple(g.state.players[2].board)
        g.apply(Attack(1, source, ids[1])); self.assertEqual([g.state.entities[i].health for i in ids], [15, 15, 15]); self.portable(g)
        g = self.game(board=(DRAKREST,), enemy=(B,)); source = self.first(g, DRAKREST, 'board').id
        g.apply(Attack(1, source, g.state.players[2].hero_id)); self.assertEqual(self.first(g, B, 'board', 2).health, 20); self.portable(g)

    def test_totem_native_weighted_pool_keeps_dual_and_all_types_and_only_own_natural_end(self):
        g = self.game(board=(TOTEM,)); g.apply(EndTurn(1))
        generated = [g.state.entities[i] for i in g.state.players[1].hand]; self.assertEqual(len(generated), 1)
        self.assertIn(generated[0].card_id, (DUAL, ALL)); count = len(g.state.players[1].hand)
        g.apply(EndTurn(2)); self.assertEqual(len(g.state.players[1].hand), count + 1); self.portable(g)

    def test_totem_empty_pool_no_rng_unknown_eligible_or_unknown_tribes_explicit_error(self):
        g = self.game(board=(TOTEM,), members=((SINGLE, 1), (NONE, 1))); rng = g._rng.getstate(); g.apply(EndTurn(1))
        self.assertFalse(g.state.players[1].hand); self.assertEqual(g._rng.getstate(), rng); self.portable(g)
        for member in (UNKNOWN, UNKNOWN_TRIBE):
            g = self.game(board=(TOTEM,), members=((member, 1),)); saved = g.snapshot()
            with self.assertRaises(ResolutionError): g.apply(EndTurn(1))
            self.assertEqual(saved, g.snapshot()); self.portable(g)

    def test_umbra_quantity_extra_original_deliveries_all_trigger_and_dead_entry_is_not_rebound(self):
        g = self.game(hand=(UMBRA,), board=(TEST + 'double',), members=((DR, 1),)); self.play(g, UMBRA)
        self.choose(g, g.state.pending_choice.options[0].id)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2); self.assertEqual(len(g.state.players[1].board), 3); self.portable(g)
        g = self.game(hand=(UMBRA,), mode='entry', members=((DR, 1),)); self.play(g, UMBRA)
        self.choose(g, g.state.pending_choice.options[0].id); other = self.portable(g)
        for running in (g, other):
            self.choose(running, 'kill'); self.assertEqual(running.state.entities[running.state.players[1].hero_id].armor, 1)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_shades_original_second_bonus_skips_after_first_reward_death_and_failure_rolls_back(self):
        g = self.game(hand=(SHADES,), mode='bonus'); self.play(g, SHADES); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved); other = self.portable(g)
        for running in (g, other): self.choose(running, 'kill'); self.keep(running)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_empty_native_producers_and_full_board_finish_without_bonus_or_attack_rng(self):
        for cid in (UMBRA, WORMHOLE):
            g = self.game(hand=(cid,), members=()); rng = g._rng.getstate(); self.play(g, cid); self.keep(g)
            self.assertFalse(g.state.players[1].board); self.assertEqual(g._rng.getstate(), rng); self.portable(g)
        g = self.game(hand=(SHADES,), board=(B,) * 7); rng = g._rng.getstate(); self.play(g, SHADES); self.keep(g)
        self.assertEqual(g._rng.getstate(), rng); self.assertEqual(len(g.state.players[1].board), 7); self.portable(g)

    def test_cached_independent_readers_frozen_and_wrong_registry_constructed_separately(self):
        g = self.game(hand=(ANCESTOR,)); reader = fixture_registry(*self.config, 'reader', SOURCE_PIN)
        self.assertIsNot(g.registry, reader); self.assertIs(reader, fixture_registry(*self.config, 'reader', SOURCE_PIN))
        with self.assertRaises(ValueError): reader.register_card(CardDefinition(TEST + 'forbidden', 'Forbidden', CardType.MINION, health=1))
        wrong = registry(None, ((DUAL, 1),)); wrong.freeze(); self.assertIsNot(wrong, reader)
        with self.assertRaises(ValueError): Game.from_snapshot(g.snapshot(), wrong)
        self.portable(g)


if __name__ == '__main__': unittest.main()
