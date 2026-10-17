"""Actual held forms, captured private material and independent delayed promises."""
from dataclasses import asdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards import simple_followup_p63_cards as cards
from hs_sim.cards.simple_followup_p63_cards import (PRAYER, RITUAL, LIGHT, FULL_LIGHT, GOLD,
    STORM, MINER, INFORMANT, ARATOR, WHELP, ROOTS, FORMS, PREFIX, PROMISE, POOL_ID,
    load_batch, register_simple_followup_p63_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CostSpec, EndTurn,
    Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice,
    TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, Destroy, InvokeBehavior,
    RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference, CopyCard, DiscardCard, ModifyStoredCost
from hs_sim.targets import canonical_digest

TEST = 'p63.test.'
YETI, RECRUIT = 'CORE_CS2_182', 'CS2_101t'
A, B, RARE, MAGE, PRIEST, UNKNOWN, NO_RARITY, ALL = (TEST + i for i in
    ('a', 'b', 'rare', 'mage', 'priest', 'unknown', 'no_rarity', 'all'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
MEMBERS = (A, B, RARE, MAGE, PRIEST)
CONTEXT = GenerationContext('p63-complete-explicit-fixture', 'experimental')
SOURCE_PIN = hashlib.sha256(Path(__file__).read_bytes() + Path(cards.__file__).read_bytes()
    + cards.BATCH_PATH.read_bytes()).hexdigest()


def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata', lambda r: None): r = build_registry()
    present = tuple(i in r.cards for i in ROOTS)
    if not any(present): register_simple_followup_p63_cards(r)
    elif not all(present): raise AssertionError('P63 requires complete assigned assembly')
    register_candidate_pool_metadata(r); r.validate(); return r


def registry(mode=None, members=MEMBERS):
    r = batch_registry()
    for cid, cost, cls, rarity in ((A, 3, CardClass.NEUTRAL, Rarity.COMMON),
            (B, 5, CardClass.NEUTRAL, Rarity.COMMON), (RARE, 3, CardClass.NEUTRAL, Rarity.RARE),
            (MAGE, 5, CardClass.MAGE, Rarity.COMMON), (PRIEST, 5, CardClass.PRIEST, Rarity.COMMON)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=3, health=12,
            metadata=CardMetadata(True, (cls,), rarity, tribes=())))
    for cid, tribes in ((NO_RARITY, ()), (ALL, ('all',))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=8,
            metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=tribes)))
    def held(c):
        return next(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id in (*ROOTS, *FORMS.values()))
    def copy(c, mode):
        return (CopyCard(CardReference.capture(held(c)), c.player_id, mode=mode, source_id=c.source_id),)
    def fail(c): raise ResolutionError('P63 deliberate continuation failure')
    def weaken(c):
        e = c.state.entities[c.state.players[2].hand[-1]]
        return (ModifyStoredCost(CardReference.capture(e), CostSpec(delta=-1), c.source_id),)
    scripts = dict(noop=lambda c: (), fail=fail,
        auto=lambda c: (CastSpell(c.player_id, TEST + 'noop', c.source_id),) * 3,
        autofail=lambda c: (CastSpell(c.player_id, TEST + 'noop', c.source_id),) * 2
            + (CastSpell(c.player_id, TEST + 'fail', c.source_id),),
        acquire=lambda c: (AddToHand(c.player_id, GOLD, c.source_id),),
        cost=lambda c: (ModifyStoredCost(CardReference.capture(held(c)), CostSpec(delta=-2), c.source_id),),
        copy=lambda c: copy(c, 'current'), base=lambda c: copy(c, 'base'), weaken=weaken,
        kill=lambda c: (Destroy(c.target_id, c.source_id),),
        buff=lambda c: (Buff(c.target_id, 2, 3, c.source_id),),
        wound=lambda c: (Damage(c.target_id, 2, c.source_id),),
        bounce=lambda c: (ReturnToHand(c.target_id),), silence=lambda c: (Silence(c.target_id),))
    for name, body in scripts.items():
        r.register_behavior(TEST + name, body)
        driver = name in ('auto', 'autofail', 'cost', 'copy', 'base', 'weaken')
        r.register_card(CardDefinition(TEST + name, name, CardType.MINION if driver else CardType.SPELL,
            health=1 if driver else 0, battlecry=TEST + name if driver else None,
            on_play=None if driver else TEST + name,
            targeting=TargetSpec() if name in ('kill', 'buff', 'wound', 'bounce', 'silence') else None, metadata=META))
    r.register_behavior(TEST + 'counter', lambda c: (CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id != c.player_id else ())
    r.register_card(CardDefinition(TEST + 'counter', 'Counter witness', CardType.MINION, health=8,
        triggers=(TriggerSpec('card_committed', TEST + 'counter'),), metadata=META))
    r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 5,
        CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=()),
        battlecry=False, deathrattle=False, choose_one=False))
    for cid in members:
        if cid not in r.pool_cards: r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL_ID, 'p63-finite-complete-v1', CONTEXT.target_id, CONTEXT.mode,
        tuple(PoolMember(cid) for cid in members), complete=True))
    if mode:
        event = dict(upgrade='hand_card_upgraded', reveal='card_revealed', destroy='card_destroyed_in_deck',
            buff='stats_changed', consume='player_effect_removed')[mode]
        def eligible(c):
            if mode == 'upgrade': return c.state.entities[c.event.target_id].card_id in FORMS.values()
            if mode == 'reveal': return c.event.player_id == 2
            return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in (MINER, ARATOR, WHELP)
        def watch(c):
            options = [ChoiceOption('ok', 'Continue'),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(TEST + 'fail', c.source_id, 1),))]
            if mode == 'reveal':
                target = c.state.entities[c.event.target_id]
                options.append(ChoiceOption('replace', 'Discard original and acquire another rightmost card',
                    (DiscardCard(CardReference.capture(target), c.source_id), AddToHand(2, B, c.source_id))))
            if mode == 'buff':
                remaining = c.state.players[1].board[1]
                options.append(ChoiceOption('bounce', 'Original remaining recruit leaves', (ReturnToHand(remaining),)))
            return (RequestChoice(1, tuple(options), c.source_id),)
        r.register_trigger_condition(TEST + 'eligible', eligible); r.register_behavior(TEST + 'watch', watch)
        r.register_card(CardDefinition(TEST + 'watch', 'Actual checkpoint witness', CardType.WEAPON, durability=5,
            metadata=META, limited_triggers=(LimitedTriggerSpec(event, TEST + 'watch', condition_id=TEST + 'eligible'),)))
    return r


@lru_cache(maxsize=None)
def fixture_registry(mode, members, role, source_pin):
    if role not in ('writer', 'reader') or source_pin != SOURCE_PIN: raise AssertionError('Incomplete immutable fixture key')
    r = registry(mode, members); r.freeze(); return r


class SimpleFollowupP63Tests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), deck=(YETI,) * 12, enemy_hand=(),
            mode=None, members=MEMBERS, hand_cap=None):
        self.config = mode, members
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
            mana=30, max_mana=30, mana_cap=40, hand_cap=hand_cap, weapon_card_id=TEST + 'watch' if mode else None),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(YETI,) * 12,
                mana=30, max_mana=30, mana_cap=40)), seed=6363, generation_context=CONTEXT),
            fixture_registry(mode, members, 'writer', SOURCE_PIN))

    def first(self, g, cid, zone='hand', player=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None, player=1):
        e = self.first(g, cid, player=player); g.apply(PlayCard(player, e.id, target_id=target,
            position=len(g.state.players[player].board) if e.kind == CardType.MINION else None)); return e.id

    def choose(self, g, key):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        reader = fixture_registry(*self.config, 'reader', SOURCE_PIN)
        self.assertIsNot(g.registry, reader); self.assertEqual(g.registry.fingerprint(), reader.fingerprint())
        saved = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved); self.assertIsNot(g.state, other.state)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(g.for_player(player).legal_actions()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'behavior_id', 'source_json', 'death_history'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def cycle(self, g): g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def test_complete_ten_definitions_twenty_three_raws_thirty_strict_faces_twelve_links(self):
        from tools.card_batch import check_face
        d = load_batch(); rows = {x['record']['id']: x['record'] for k in ('cards', 'existing_dependencies', 'evidence_only') for x in d[k]}
        self.assertEqual(len(rows), 23); self.assertEqual(len(d['official_observations']), 30)
        self.assertEqual((len(d['collectible_candidate_roots']), len(d['noncollectible_ids'])), (9, 1))
        faces = {(o['card_id'], o['locale']): o['face'] for o in d['official_observations']}
        for o in d['official_observations']:
            check_face(rows[o['card_id']], o['face'], o['locale'],
                display_normalizations=d['display_normalizations'].get(o['card_id']),
                numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
        self.assertEqual(len(d['exact_parent_child_links']), 12)
        for e in d['exact_parent_child_links']:
            self.assertEqual(rows[e['child']]['dbf_id'], e['dbf_id'])
            self.assertIn(e['dbf_id'], faces[e['parent'], e['locale']]['childIds'])
        recruits = {i for i, raw in rows.items() if raw['name_en'] == 'Silver Hand Recruit' and raw['type'] == 'MINION'}
        self.assertEqual(recruits, set(d['silver_hand_recipient_ids']))
        self.assertFalse(d['formal_pool_complete'] or d['cn_calibrated'] or d['reachability_complete'])

    def test_old_full_definitions_and_pool_rows_and_existing_dependency_pins(self):
        before, after = build_registry(), batch_registry()
        self.assertEqual(set(after.cards) - set(before.cards), set(ROOTS) - set(before.cards))
        for cid, definition in before.cards.items(): self.assertEqual(definition, after.card(cid))
        for cid, definition in before.pool_cards.items(): self.assertEqual(definition, after.pool_card(cid))
        for cid, pin in load_batch()['existing_dependency_definition_pins'].items():
            self.assertEqual(canonical_digest(asdict(after.card(cid))), pin)

    def test_all_five_base_faces_upgrade_after_three_real_effect_casts_same_physical_entities(self):
        g = self.game(hand=tuple(FORMS) + (TEST + 'auto',))
        originals = {cid: self.first(g, cid).id for cid in FORMS}
        self.play(g, TEST + 'auto')
        self.assertEqual([c.origin for c in g.state.cast_history], ['effect'] * 3)
        for cid, eid in originals.items():
            e = g.state.entities[eid]; self.assertEqual(e.card_id, FORMS[cid]); self.assertEqual(e.zone, Zone.HAND)
            self.assertEqual(e.kind, g.registry.card(FORMS[cid]).kind)
        self.assertEqual((g.state.entities[originals[GOLD]].attack, g.state.entities[originals[GOLD]].health), (3, 3))
        self.assertIn(Keyword.LIFESTEAL, g.state.entities[originals[STORM]].keywords); self.portable(g)

    def test_hand_acceptance_opponent_counter_and_mid_payload_acquisition_do_not_falsely_advance(self):
        g = self.game(hand=(GOLD, TEST + 'noop'), enemy_hand=(TEST + 'noop',), enemy=(TEST + 'counter',))
        eid = self.first(g, GOLD).id; self.play(g, TEST + 'noop')
        self.assertEqual(progress_ability(g.state.entities[eid]).progress_value, 0)
        g.apply(EndTurn(1)); self.play(g, TEST + 'noop', player=2)
        self.assertEqual(progress_ability(g.state.entities[eid]).progress_value, 0); self.portable(g)
        g = self.game(hand=(TEST + 'acquire', TEST + 'noop'))
        self.play(g, TEST + 'acquire'); eid = self.first(g, GOLD).id
        self.assertEqual(progress_ability(g.state.entities[eid]).progress_value, 0)
        self.play(g, TEST + 'noop'); self.assertEqual(progress_ability(g.state.entities[eid]).progress_value, 1); self.portable(g)

    def test_third_failed_real_payload_rolls_back_progress_payment_entities_and_rng(self):
        g = self.game(hand=(GOLD, TEST + 'autofail')); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, TEST + 'autofail')
        self.assertEqual(g.snapshot(), saved); self.portable(g)

    def test_original_upgrade_wait_wrong_selection_restore_and_no_second_payment(self):
        g = self.game(hand=(GOLD, TEST + 'auto'), mode='upgrade'); mana = g.state.players[1].mana
        self.play(g, TEST + 'auto'); self.assertIsNotNone(g.state.pending_choice); saved = g.snapshot()
        with self.assertRaises(IllegalAction): self.choose(g, 'missing')
        self.assertEqual(saved, g.snapshot()); other = self.portable(g)
        for running in (g, other):
            self.choose(running, 'ok'); self.assertEqual(running.state.players[1].mana, mana)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_cost_and_current_copy_progress_preserved_base_copy_starts_fresh_minion_pays_once(self):
        g = self.game(hand=(GOLD, TEST + 'noop', TEST + 'noop', TEST + 'cost', TEST + 'copy', TEST + 'base', TEST + 'noop'))
        original = self.first(g, GOLD).id
        for _ in range(2): self.play(g, TEST + 'noop')
        self.play(g, TEST + 'cost'); self.play(g, TEST + 'copy'); self.play(g, TEST + 'base')
        held = [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id == GOLD]
        self.assertEqual([progress_ability(e).progress_value for e in held], [2, 2, 0])
        self.play(g, TEST + 'noop'); self.assertEqual(g.state.entities[original].card_id, FORMS[GOLD])
        self.assertEqual(g.quote_cost(original).amount, 1)
        mana = g.state.players[1].mana; hero = g.state.players[2].hero_id
        self.play(g, FORMS[GOLD], hero); self.assertEqual(g.state.players[1].mana, mana - 1)
        self.assertEqual(g.state.entities[hero].health, 26); self.portable(g)

    def test_real_base_prayer_damage_light_buff_and_full_light_creates_new_zero_progress_base(self):
        g = self.game(hand=(PRAYER, LIGHT, FULL_LIGHT), enemy=(A,))
        target = self.first(g, A, 'board', 2).id
        self.play(g, PRAYER, target); self.assertEqual(g.state.entities[target].health, 6)
        self.play(g, LIGHT, target); self.assertEqual((g.state.entities[target].attack, g.state.entities[target].health), (6, 9))
        original = self.play(g, FULL_LIGHT, target); new = self.first(g, LIGHT)
        self.assertNotEqual(original, new.id); self.assertEqual(progress_ability(new).progress_value, 0)
        self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD)
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].health), (9, 12)); self.portable(g)

    def test_ritual_exact_three_cost_pool_twice_and_unknown_eligible_candidate_rolls_back(self):
        g = self.game(hand=(RITUAL,)); self.play(g, RITUAL)
        bodies = [g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual(len(bodies), 2); self.assertTrue(all(e.card_id in (A, RARE) for e in bodies)); self.portable(g)
        g = self.game(hand=(WHELP,), members=MEMBERS + (UNKNOWN,)); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, WHELP)
        self.assertEqual(g.snapshot(), saved); self.portable(g)

    def test_gold_and_storm_real_spell_damage_and_lifesteal_exclude_friendly_minions(self):
        g = self.game(hand=(GOLD, STORM, TEST + 'wound'), board=(A,), enemy=(A, B))
        hero = g.state.players[1].hero_id; self.play(g, TEST + 'wound', hero)
        enemy = self.first(g, A, 'board', 2).id; self.play(g, GOLD, enemy)
        self.assertEqual(g.state.entities[enemy].health, 8)
        self.play(g, STORM); self.assertEqual(g.state.entities[hero].health, 30)
        self.assertEqual(g.state.entities[enemy].health, 6)
        self.assertEqual(self.first(g, B, 'board', 2).health, 10)
        self.assertEqual(self.first(g, A, 'board').health, 12); self.portable(g)

    def test_miner_destroys_original_top_then_same_rarity_current_class_neutral_discovery(self):
        g = self.game(hand=(MINER,), deck=(RARE, A), mode='destroy')
        top, second = g.state.players[1].deck; self.play(g, MINER)
        self.assertEqual(g.state.entities[top].zone, Zone.GRAVEYARD); self.assertEqual(g.state.players[1].deck, [second])
        saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(saved, g.snapshot()); other = self.portable(g)
        for running in (g, other):
            self.choose(running, 'ok'); q = running.state.pending_choice
            self.assertEqual({o.card_id for o in q.options}, {RARE}); self.choose(running, q.options[0].id)
            self.assertEqual(self.first(running, RARE).card_id, RARE)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)
        g = self.game(hand=(MINER,), deck=(A,)); self.play(g, MINER)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {A, B, MAGE}); self.portable(g)

    def test_miner_empty_deck_no_fatigue_no_discovery_unknown_rarity_explicit_error(self):
        g = self.game(hand=(MINER,), deck=()); rng = g._rng.getstate(); self.play(g, MINER)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g._rng.getstate(), rng)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 30); self.portable(g)
        g = self.game(hand=(MINER,), deck=(NO_RARITY,)); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'unknown printed rarity'): self.play(g, MINER)
        self.assertEqual(saved, g.snapshot()); self.portable(g)

    def test_informant_only_original_rightmost_revealed_and_copy_keeps_accepted_material_after_departure(self):
        g = self.game(hand=(TEST + 'weaken', INFORMANT), enemy_hand=(RARE, B), mode='reveal')
        self.play(g, TEST + 'weaken'); hidden, original = g.state.players[2].hand
        self.play(g, INFORMANT); other = self.portable(g)
        for running in (g, other):
            self.choose(running, 'replace'); self.assertIsNotNone(running.state.pending_choice)
            actor = json.dumps(running.for_player(1).observe())
            self.assertNotIn(RARE, actor); self.choose(running, 'copy')
            new = self.first(running, B); self.assertNotEqual(new.id, original)
            self.assertEqual(running.quote_cost(new.id).amount, 4)
            self.assertEqual(running.state.entities[original].zone, Zone.GRAVEYARD)
            self.assertEqual(running.state.players[2].hand[0], hidden)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_informant_tax_only_original_physical_card_and_stale_target_does_not_tax_new_rightmost(self):
        for mode in (None, 'reveal'):
            g = self.game(hand=(INFORMANT,), enemy_hand=(RARE, B), mode=mode)
            original = g.state.players[2].hand[-1]; self.play(g, INFORMANT)
            if mode: self.choose(g, 'replace')
            self.portable(g); self.choose(g, 'tax')
            from hs_sim.engine.costs import quote_unselected_cost
            current = g.state.entities[g.state.players[2].hand[-1]]
            self.assertEqual(quote_unselected_cost(g.state, g.registry, current).amount, 5 if mode else 7)
            self.assertEqual(current.id == original, not bool(mode)); self.portable(g)
        g = self.game(hand=(INFORMANT,)); rng = g._rng.getstate(); self.play(g, INFORMANT)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_arator_doubles_current_attack_and_remaining_health_only_named_friendly_recruits(self):
        g = self.game(hand=(TEST + 'buff', TEST + 'wound', ARATOR), board=(RECRUIT, ALL), enemy=(RECRUIT,))
        recruit = self.first(g, RECRUIT, 'board').id
        self.play(g, TEST + 'buff', recruit); self.play(g, TEST + 'wound', recruit)
        self.assertEqual((g.state.entities[recruit].attack, g.state.entities[recruit].health), (3, 2))
        self.play(g, ARATOR); e = g.state.entities[recruit]
        self.assertEqual((e.attack, e.health), (6, 4)); self.assertIn(Keyword.TAUNT, e.keywords)
        self.assertEqual(self.first(g, ALL, 'board').attack, 1)
        self.assertNotIn(Keyword.TAUNT, self.first(g, RECRUIT, 'board', 2).keywords); self.portable(g)

    def test_arator_original_group_stale_remaining_recruit_skips_after_actual_buff_wait(self):
        g = self.game(hand=(ARATOR,), board=(RECRUIT, RECRUIT), mode='buff')
        first, second = g.state.players[1].board; self.play(g, ARATOR); other = self.portable(g)
        for running in (g, other):
            self.choose(running, 'bounce'); self.assertEqual(running.state.entities[second].zone, Zone.HAND)
            self.assertEqual(running.state.entities[first].attack, 2)
            self.assertNotIn(Keyword.TAUNT, running.state.entities[second].keywords)
            self.assertEqual(running.state.entities[second].attack, 1)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_whelp_discovery_five_cost_current_class_and_source_independent_next_owner_start_once(self):
        g = self.game(hand=(WHELP, TEST + 'silence', TEST + 'kill'))
        source = self.play(g, WHELP); q = g.state.pending_choice
        self.assertEqual({o.card_id for o in q.options}, {B, MAGE}); other = self.portable(g)
        for running in (g, other):
            self.choose(running, running.state.pending_choice.options[0].id)
            self.assertEqual(len(running.state.players[1].player_effects), 1)
            self.play(running, TEST + 'silence', source); self.play(running, TEST + 'kill', source)
            running.apply(EndTurn(1)); self.assertEqual(len(running.state.players[1].player_effects), 1)
            self.assertEqual(running.state.players[1].temporary_mana, 0); running.apply(EndTurn(2))
            self.assertEqual(running.state.players[1].temporary_mana, 1)
            self.assertFalse(running.state.players[1].player_effects)
            running.apply(EndTurn(1)); self.assertEqual(running.state.players[1].temporary_mana, 0)
            running.apply(EndTurn(2)); self.assertEqual(running.state.players[1].temporary_mana, 0)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_whelp_two_actual_battlecries_independent_promises_consumption_wait_restore_and_failure_rollback(self):
        g = self.game(hand=(WHELP, WHELP), mode='consume')
        for _ in range(2):
            self.play(g, WHELP); self.choose(g, g.state.pending_choice.options[0].id)
        self.assertEqual(len(g.state.players[1].player_effects), 2)
        self.cycle(g); self.assertIsNotNone(g.state.pending_choice)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(saved, g.snapshot()); other = self.portable(g)
        for running in (g, other):
            while running.state.pending_choice is not None: self.choose(running, 'ok')
            self.assertEqual(running.state.players[1].temporary_mana, 2)
            self.assertFalse(running.state.players[1].player_effects)
            self.cycle(running); self.assertEqual(running.state.players[1].temporary_mana, 0)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g)

    def test_cached_readers_distinct_frozen_complete_config_and_wrong_registry_separately_built(self):
        g = self.game(hand=(GOLD,)); reader = fixture_registry(*self.config, 'reader', SOURCE_PIN)
        self.assertIsNot(g.registry, reader); self.assertIs(reader, fixture_registry(*self.config, 'reader', SOURCE_PIN))
        with self.assertRaises(ValueError): reader.register_card(CardDefinition(TEST + 'forbidden', 'Forbidden', CardType.MINION, health=1))
        wrong = registry(None, (A,)); wrong.freeze(); self.assertIsNot(wrong, reader)
        with self.assertRaises(ValueError): Game.from_snapshot(g.snapshot(), wrong)
        self.portable(g)


if __name__ == '__main__': unittest.main()
