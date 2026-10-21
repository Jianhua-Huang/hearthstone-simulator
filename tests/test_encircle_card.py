"""Encircle's six original summon requests, recipient scope and existing plans."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards import build_registry as assembled
from hs_sim.cards.encircle_card import CARD, TOKEN, POOL, QUERY, load_batch, register_encircle_card
from hs_sim.engine import (Attack, CardDefinition, CardType, CounterSpell, Game, GenerationContext,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Ruleset, Scenario, SelectChoice, SetSecret, SnapshotError)
from hs_sim.engine.effects import (ChoiceOption, Destroy, GainArmor, InvokeBehavior, RandomDamage,
    RequestChoice, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardClass, CardMetadata, LimitedTriggerSpec, Rarity, SecretSpec,
    SummonQuantitySpec, Zone)
from hs_sim.engine.pools import PoolCard, PoolDefinition, PoolMember, resolve_candidates, sample_candidates
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell, CastStoredSpell
from hs_sim.engine.zones import CardReference
from tools.card_batch import check_face

P = 'fixture.encircle.'
FILL, A, B, HIGH, SPELL, UNKNOWN, QTY, WATCH, SECRET = (P+x for x in
    ('fill', 'a', 'b', 'high', 'spell', 'unknown', 'quantity', 'watch', 'secret'))
CTX = GenerationContext('encircle-fixture', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON)


@lru_cache(maxsize=1)
def complete_registry(): return assembled()


@lru_cache(maxsize=None)
def fixture(mode=None, unknown=None, empty=False, role='writer'):
    if role not in ('writer', 'reader'): raise ValueError('Independent registry role required')
    r = build_registry(); r.register_card(complete_registry().card(TOKEN)); register_encircle_card(r)
    r.register_card(CardDefinition(FILL, FILL, CardType.MINION, attack=1, health=10, metadata=META))
    r.register_card(CardDefinition(QTY, QTY, CardType.MINION, health=10, metadata=META,
        summon_quantities=(SummonQuantitySpec(2, source_kinds=(CardType.SPELL,)),)))
    r.register_behavior(P+'battlecry', lambda c: (GainArmor(c.player_id, 99),))
    r.register_behavior(P+'noop', lambda c: ())
    for cid, cost, attack, health in ((A, 1, 1, 4), (B, 1, 2, 5), (HIGH, 2, 9, 9)):
        d = CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=attack, health=health,
            battlecry=P+'battlecry' if cid == B else None, metadata=replace(META, collectible=True))
        r.register_card(d); r.register_pool_card(PoolCard.from_definition(d))
    d = CardDefinition(SPELL, SPELL, CardType.SPELL, cost=1, on_play=P+'noop',
        metadata=replace(META, collectible=True, classes=(CardClass.MAGE,)))
    r.register_card(d); r.register_pool_card(PoolCard.from_definition(d))
    r.register_pool_card(PoolCard.from_definition(r.card(TOKEN)))
    members = (HIGH, SPELL, TOKEN) if empty else (A, B, HIGH, SPELL, TOKEN)
    if unknown:
        if unknown not in ('eligible', 'ineligible'): raise ValueError('Explicit unknown eligibility required')
        r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 1 if unknown == 'eligible' else 2,
            replace(META, collectible=True)))
        members += (UNKNOWN,)
    r.register_pool(PoolDefinition(POOL, 'encircle-complete-fixture-v1', CTX.target_id, CTX.mode,
        tuple(PoolMember(cid) for cid in members), complete=True))
    def fail(c): raise ResolutionError('Encircle deliberate failure')
    r.register_behavior(P+'fail', fail)
    scripts = {
        'auto': lambda c: (CastSpell(c.player_id, CARD, c.source_id),),
        'stored': lambda c: (CastStoredSpell(CardReference.capture(next(c.state.entities[i]
            for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == CARD)),
            c.player_id, c.source_id),),
        'arm': lambda c: (SetSecret(3-c.player_id, SECRET),),
        'silence': lambda c: (Silence(c.target_id),),
    }
    for key, body in scripts.items():
        cid = P+key; r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            requires_target=key == 'silence', metadata=META))
    r.register_secret_condition(P+'counter_condition', lambda c: c.window is not None and
        c.window.kind == 'spell' and c.window.player_id != c.player_id and not c.window.countered)
    r.register_behavior(P+'counter', lambda c: (CounterSpell(c.window.id),))
    r.register_card(CardDefinition(SECRET, SECRET, CardType.SPELL, keywords=(Keyword.SECRET,),
        secret=SecretSpec(SECRET, ('card_committed',), P+'counter_condition', P+'counter'), metadata=META))
    if mode:
        if mode not in ('own', 'enemy', 'end_fail'): raise ValueError('Explicit summon observation mode required')
        def eligible(c):
            roots = c.state.card_summon_history
            if not roots: return False
            root = roots[-1]
            return (root.request.cause.cast_card_id == CARD and c.event.player_id ==
                (3-c.player_id if mode in ('enemy', 'end_fail') else c.player_id))
        r.register_trigger_condition(P+'eligible', eligible)
        def wait(c):
            if mode == 'end_fail': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
            quantity = next((i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == QTY), None)
            choices = (ChoiceOption('ok', 'Continue'), ChoiceOption('fail', 'Fail', (
                RandomDamage((c.state.players[3-c.player_id].hero_id,), 1, c.source_id),
                InvokeBehavior(P+'fail', c.source_id, c.player_id))))
            if quantity is not None: choices += (ChoiceOption('kill', 'Remove multiplier', (Destroy(quantity),)),)
            return (RequestChoice(c.player_id, choices, c.source_id),)
        r.register_behavior(P+'wait', wait)
        r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=30, metadata=META,
            limited_triggers=(LimitedTriggerSpec('minion_summoned', P+'wait', condition_id=P+'eligible'),)))
    return r


class EncircleTests(unittest.TestCase):
    def game(self, hand=(CARD,), board=(), enemy=(), mode=None, unknown=None, empty=False,
             actor=1, context=True, capacity=7):
        self.config = (mode, unknown, empty); self.actor = actor
        if mode: board = (WATCH,)+board
        own = PlayerSetup('HERO_08', hand=hand, board=board, deck=(FILL,)*8, mana=20, max_mana=20, mana_cap=20)
        other = PlayerSetup('HERO_01', board=enemy, deck=(FILL,)*8, mana=20, max_mana=20, mana_cap=20)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own), active_player=actor,
            seed=354, generation_context=CTX if context else None), fixture(*self.config), Ruleset(max_board=capacity))

    def play(self, g, cid=CARD, target=None):
        pid = g.state.active_player
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid, eid, target)); return eid

    def bodies(self, g, pid=None):
        pid = self.actor if pid is None else pid; s = g.state
        return [s.entities[i] for i in s.players[pid].board]

    def tokens(self, g): return [e for e in self.bodies(g) if e.card_id == TOKEN]

    def roots(self, g): return [r for r in g.state.card_summon_history if r.request.cause.cast_card_id == CARD]

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); r = fixture(*self.config, 'reader')
        self.assertEqual(Game.from_snapshot(saved, r).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved); self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        for pid in (1, 2):
            public = json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for private in ('"card_summon_history"', '"pool_basis"', '"rng_state"', '"resolution_frame"', '"source_fact"'):
                self.assertNotIn(private, public)

    def choose(self, g, key):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def test_complete_real_root_primary_faces_and_unchanged_existing_token(self):
        data = load_batch(); raw = data['cards'][0]['record']
        for ob in data['official_observations']: check_face(raw, ob['face'], ob['locale'])
        root = complete_registry().card(CARD); token = complete_registry().card(TOKEN)
        self.assertEqual((root.cost, root.metadata.classes, root.metadata.rarity), (6, (CardClass.DEMON_HUNTER,), Rarity.EPIC))
        self.assertIsNone(root.spell_school)
        self.assertEqual((token.cost, token.attack, token.health, token.keywords), (2, 3, 1, (Keyword.RUSH,)))
        from hs_sim.cards.hatching_sigil_card import load_batch as hatching
        self.assertEqual(data['existing_dependencies'][0]['record'], hatching()['dependencies'][0]['record'])

    def test_paid_spell_summons_five_rush_bodies_then_one_opponent_minion_without_battlecry(self):
        g = self.game(); source = self.play(g)
        self.assertEqual(g.state.players[1].mana, 14); self.assertEqual(len(self.tokens(g)), 5)
        self.assertEqual(len(self.bodies(g, 2)), 1)
        self.assertTrue(all((e.attack, e.health, Keyword.RUSH in e.keywords) == (3, 1, True) for e in self.tokens(g)))
        roots = self.roots(g); self.assertEqual([r.request.player_id for r in roots], [1]*5+[2])
        self.assertTrue(all((r.request.cause.player_id, r.request.cause.source.entity_id) == (1, source) for r in roots))
        self.assertTrue(all(r.status == 'completed' for r in roots))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor, 0); self.portable(g)

    def test_fixed_entries_do_not_consume_rng_and_last_request_samples_complete_one_cost_pool_once(self):
        g = self.game(); local = Random(); local.setstate(g._rng.getstate())
        pool = resolve_candidates(g.registry, CTX, POOL, QUERY, player_id=2, source_card_id=CARD, exclude_source_by_rule=True)
        self.assertEqual({x.card_id for x in pool}, {A, B})
        expected = sample_candidates(local, pool, 1, replacement=True)[0]; self.play(g)
        self.assertEqual(self.bodies(g, 2)[0].card_id, expected); self.assertEqual(g._rng.getstate(), local.getstate())
        self.assertTrue(all(r.rng_before == r.rng_after for r in self.roots(g)[:5])); self.portable(g)

    def test_full_own_board_still_runs_opponent_tail(self):
        g = self.game(board=(FILL,)*7); self.play(g)
        self.assertFalse(self.tokens(g)); self.assertEqual(len(self.bodies(g, 2)), 1)
        self.assertTrue(all(r.selected is None for r in self.roots(g)[:5])); self.portable(g)

    def test_partial_own_capacity_keeps_five_original_attempts(self):
        g = self.game(board=(FILL,)*4); self.play(g)
        self.assertEqual(len(self.tokens(g)), 3); self.assertEqual(len(self.roots(g)), 6)
        self.assertEqual(len(self.bodies(g, 2)), 1); self.portable(g)

    def test_full_enemy_board_skips_random_selection_after_five_own_summons(self):
        g = self.game(enemy=(FILL,)*7); rng = g._rng.getstate(); self.play(g)
        self.assertEqual(len(self.tokens(g)), 5); self.assertEqual(g._rng.getstate(), rng)
        last = self.roots(g)[-1]; self.assertIsNone(last.selected)
        self.assertEqual({m.card_id for m in last.request.pool_basis.candidates}, {A, B}); self.portable(g)

    def test_empty_eligible_pool_skips_without_rng_or_invented_fallback(self):
        g = self.game(empty=True); rng = g._rng.getstate(); self.play(g)
        self.assertEqual(len(self.tokens(g)), 5); self.assertFalse(self.bodies(g, 2))
        self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_custom_board_capacity_uses_actual_limits_for_both_players(self):
        g = self.game(capacity=4); self.play(g)
        self.assertEqual(len(self.tokens(g)), 4); self.assertEqual(len(self.bodies(g, 2)), 1); self.portable(g)

    def test_caster_multiplier_applies_to_both_recipients_and_duplicates_selected_enemy_template(self):
        g = self.game(board=(QTY,)); self.play(g)
        self.assertEqual(len(self.tokens(g)), 6); self.assertEqual(len(self.bodies(g, 2)), 2)
        self.assertTrue(all(r.plan.total == 2 for r in self.roots(g)))
        self.assertEqual(len({e.card_id for e in self.bodies(g, 2)}), 1); self.portable(g)

    def test_opponent_multiplier_does_not_claim_the_original_cast(self):
        g = self.game(enemy=(QTY,)); self.play(g)
        self.assertEqual(len(self.tokens(g)), 5)
        self.assertEqual(len([e for e in self.bodies(g, 2) if e.card_id in (A, B)]), 1)
        self.assertTrue(all(r.plan.total == 1 for r in self.roots(g))); self.portable(g)

    def test_second_seat_preserves_original_caster_and_opponent_destination(self):
        g = self.game(actor=2); source = self.play(g)
        self.assertEqual([r.request.player_id for r in self.roots(g)], [2]*5+[1])
        self.assertTrue(all((r.request.cause.player_id, r.request.cause.source.entity_id) == (2, source) for r in self.roots(g)))
        self.assertEqual(len(self.bodies(g, 1)), 1); self.portable(g)

    def test_automatic_and_stored_casts_keep_actual_encircle_source_without_manual_payment(self):
        for name in ('auto', 'stored'):
            with self.subTest(name=name):
                g = self.game((P+name,)+(CARD,) if name == 'stored' else (P+name,))
                caller = self.play(g, P+name); cast = next(c for c in g.state.cast_history if c.card_id == CARD)
                self.assertNotEqual(cast.source_id, caller)
                self.assertTrue(all(r.request.cause.source.entity_id == cast.source_id and r.request.cause.cast_id == cast.id for r in self.roots(g)))
                self.assertEqual(g.state.players[1].mana, 20); self.assertEqual(len(self.tokens(g)), 5); self.portable(g)

    def test_countered_cast_spends_once_and_creates_no_summon_or_rng(self):
        g = self.game((P+'arm', CARD)); self.play(g, P+'arm'); rng = g._rng.getstate(); self.play(g)
        self.assertFalse(self.roots(g)); self.assertEqual(g.state.players[1].mana, 14)
        self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_rush_token_can_attack_minion_immediately_but_cannot_attack_hero(self):
        g = self.game(); self.play(g); token = self.tokens(g)[0]
        with self.assertRaises(IllegalAction): g.apply(Attack(1, token.id, g.state.players[2].hero_id))
        g.apply(Attack(1, token.id, self.bodies(g, 2)[0].id)); self.assertEqual(g.state.entities[token.id].zone, Zone.GRAVEYARD)
        self.portable(g)

    def test_wait_during_original_plan_restores_and_failed_choice_rolls_back_rng_and_materials(self):
        g = self.game(mode='own'); self.play(g); self.assertEqual(len(self.tokens(g)), 1)
        before = g.snapshot(); self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before)
        self.choose(g, 'ok'); self.assertEqual(len(self.tokens(g)), 5); self.assertEqual(len(self.bodies(g, 2)), 1); self.portable(g)

    def test_accepted_extra_is_retained_and_later_original_requests_recheck_multiplier(self):
        g = self.game(board=(QTY,), mode='own'); self.play(g)
        self.assertEqual(self.roots(g)[0].plan.total, 2); self.choose(g, 'kill')
        self.assertEqual([r.plan.total for r in self.roots(g)], [2, 1, 1, 1, 1, 1])
        self.assertEqual(len(self.tokens(g)), 6); self.assertEqual(len(self.bodies(g, 2)), 1); self.portable(g)

    def test_wait_after_enemy_selection_keeps_original_weighted_basis_and_no_reroll(self):
        g = self.game(mode='enemy'); self.play(g); before = g.snapshot(); rng = g._rng.getstate()
        self.assertEqual(len(self.tokens(g)), 5); enemy = self.bodies(g, 2)[0].id; self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before); self.choose(g, 'ok')
        self.assertEqual(self.bodies(g, 2)[0].id, enemy); self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_entire_action_failure_rolls_back_five_summons_cast_payment_and_rng(self):
        g = self.game(mode='end_fail'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g)
        self.assertEqual(g.snapshot(), before)

    def test_unknown_eligible_minion_errors_even_when_receiver_full_without_cropping(self):
        for enemy in ((), (FILL,)*7):
            with self.subTest(full=bool(enemy)):
                g = self.game(unknown='eligible', enemy=enemy); before = g.snapshot()
                with self.assertRaises(ResolutionError): self.play(g)
                self.assertEqual(g.snapshot(), before)

    def test_unknown_ineligible_metadata_is_filtered_by_actual_cost_not_implementation(self):
        g = self.game(unknown='ineligible'); self.play(g)
        self.assertEqual(len(self.tokens(g)), 5); self.assertEqual(len(self.bodies(g, 2)), 1); self.portable(g)

    def test_missing_generation_context_rejects_the_whole_original_action(self):
        g = self.game(context=False); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g)
        self.assertEqual(g.snapshot(), before)

    def test_rehashed_opponent_receipt_cannot_substitute_original_caster_or_crop_pool(self):
        g = self.game(mode='enemy'); self.play(g); saved = g.snapshot()
        for mutation in ('actor', 'pool'):
            with self.subTest(mutation=mutation):
                bad = deepcopy(saved); root = bad['state']['card_summon_history'][-1]
                if mutation == 'actor': root['request']['cause']['player_id'] = 2
                else: root['request']['pool_basis']['candidates'].pop()
                bad['state_hash'] = canonical_hash({k:v for k,v in bad.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
                with self.assertRaises(SnapshotError) as error: Game.from_snapshot(bad, fixture(*self.config, 'reader'))
                self.assertNotIn('digest mismatch', str(error.exception))


if __name__ == '__main__': unittest.main()
