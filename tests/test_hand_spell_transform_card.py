"""Bootleg Alchemist: original physical selection, full pool and retained Cost."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.hand_spell_transform_card import CARD, POOL_ID, load_batch, register_hand_spell_transform_card
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CostSpec,
    Game, Keyword, PlayCard, PlayerSetup, Rarity, Registry, Scenario, SelectChoice,
    SummonStats, TriggerSpec, Zone)
from hs_sim.engine.costs import local_cost, quote_unselected_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, GainArmor, InvokeBehavior,
    RequestChoice, Summon)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.model import CostAuraSpec, PaymentType
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.stored_pool_transforms import DRAW, TransformStoredFromPool, decode
from hs_sim.engine.zones import CardReference, CopyCard, ModifyStoredCost, MoveCard

P = 'k208.'
HERO, A, S, W, L, H, D1, D2, D5, D6, D8, M7, U7, UNKNOWN, WATCH, AURA = (
    P+x for x in ('hero', 'a', 'spell', 'weapon', 'location', 'hero_card', 'd1', 'd2',
                 'd5', 'd6', 'd8', 'm7', 'u7', 'unknown', 'watch', 'aura'))
MEMBERS = (D1, D2, D5, D6, D8, M7, U7)
CTX = GenerationContext('k208-explicit-full-spells', 'experimental')
META = CardMetadata(True, (CardClass.MAGE,), Rarity.COMMON)


@lru_cache(None)
def registry(members=MEMBERS, mode=None, pool=True, unknown_cost=7):
    r = Registry(P+'host'); register_hand_spell_transform_card(r)
    r.register_behavior(P+'marker', lambda c: (GainArmor(c.player_id, 9),))
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=80))
    r.register_card(CardDefinition(P+'power', 'Power', CardType.HERO_POWER, on_use=P+'marker'))
    for card in (
        CardDefinition(A, 'Original minion', CardType.MINION, cost=2, attack=1, health=4,
                       keywords=(Keyword.RUSH,), metadata=META),
        CardDefinition(S, 'Original spell', CardType.SPELL, cost=2, on_play=P+'marker', metadata=META),
        CardDefinition(W, 'Original weapon', CardType.WEAPON, cost=2, attack=1, durability=3, metadata=META),
        CardDefinition(L, 'Original location', CardType.LOCATION, cost=2, durability=2, on_use=P+'marker', metadata=META),
        CardDefinition(H, 'Original Hero card', CardType.HERO, cost=2, health=30, hero_card=True,
                       initial_hero_power=P+'power', metadata=META),
        CardDefinition(AURA, AURA, CardType.MINION, health=20,
                       cost_auras=(CostAuraSpec(CostSpec(delta=-1)),)),
    ): r.register_card(card)
    for cid, cost, collectible, cls in ((D1, 7, True, CardClass.MAGE), (D2, 7, True, CardClass.WARLOCK),
            (D5, 5, True, CardClass.NEUTRAL), (D6, 6, True, CardClass.MAGE),
            (D8, 8, True, CardClass.MAGE), (U7, 7, False, CardClass.MAGE)):
        card = CardDefinition(cid, cid, CardType.SPELL, cost=cost, on_play=P+'marker',
                              metadata=CardMetadata(collectible, (cls,), Rarity.COMMON))
        r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    card = CardDefinition(M7, M7, CardType.MINION, cost=7, health=2, metadata=META)
    r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    if UNKNOWN in members: r.register_pool_card(PoolCard(UNKNOWN, CardType.SPELL, unknown_cost, META))
    if pool: r.register_pool(PoolDefinition(POOL_ID, P+'full-v1', CTX.target_id, CTX.mode,
        tuple(PoolMember(cid, 3 if cid == D2 else 1) for cid in members), complete=True))

    def original(c):
        return next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == A)
    def modify(c, spec): return (ModifyStoredCost(CardReference.capture(original(c)), spec, c.source_id),)
    def copy(c, base=False):
        entity = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
                      if c.state.entities[i].card_id in (D1, D2, D5, D6))
        return (CopyCard(CardReference.capture(entity), c.player_id, mode='base' if base else 'current', source_id=c.source_id),)
    def back(c):
        return (MoveCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, Zone.HAND, source_id=c.source_id),)
    r.register_behavior(P+'back', back)
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('K208 deliberate failure')))
    scripts = dict(discount=lambda c: modify(c, CostSpec(delta=-1)), zero=lambda c: modify(c, CostSpec(set_to=0)),
        expensive=lambda c: modify(c, CostSpec(set_to=20)), health=lambda c: modify(c, CostSpec(payment=PaymentType.HEALTH)),
        copy=copy, base=lambda c: copy(c, True), summon=lambda c: (Summon(c.player_id, CARD, c.source_id),))
    for name, body in scripts.items():
        r.register_behavior(P+name, body)
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name))

    def watch(c):
        source = c.state.entities.get(c.event.source_id)
        if source is None or source.card_id != CARD: return ()
        if mode in ('stale', 'mutate'):
            e = original(c); ref = CardReference.capture(e)
            if mode == 'mutate': return (ModifyStoredCost(ref, CostSpec(set_to=0), c.source_id),)
            return (MoveCard(ref, c.player_id, Zone.DECK, source_id=c.source_id),
                    InvokeBehavior(P+'back', c.source_id, c.player_id, e.id))
        if mode == 'fail': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        if mode == 'inspect':
            e = c.state.entities[c.event.target_id]
            return (GainArmor(c.player_id, local_cost(e)[0]),)
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue'),
            ChoiceOption('bad', 'Rollback', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
        ), c.source_id),)
    r.register_behavior(P+'watch', watch)
    event = 'choice_selected' if mode in ('stale', 'mutate') else 'stored_card_transformed'
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20,
        triggers=() if mode is None else (TriggerSpec(event, P+'watch'),)))
    r.validate(); return r


class HandSpellTransformTests(unittest.TestCase):
    def game(self, hand=(CARD, A), board=(), enemy_hand=(S,), actor=1,
             members=MEMBERS, mode=None, pool=True, unknown_cost=7):
        self.config = members, mode, pool, unknown_cost
        own = PlayerSetup(HERO, hand=hand, board=board, mana=80, max_mana=80, mana_cap=80)
        other = PlayerSetup(HERO, hand=enemy_hand, mana=80, max_mana=80, mana_cap=80)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own),
            active_player=actor, seed=208, generation_context=CTX), registry(*self.config))

    def eid(self, g, cid):
        return next(i for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id == cid)
    def play(self, g, cid=CARD):
        eid = self.eid(g, cid); g.apply(PlayCard(g.state.active_player, eid)); return eid
    def choose(self, g, eid=None, key='ok'):
        q = g.state.pending_choice
        if eid is not None: key = next(x.id for x in q.options if x.entity_id == eid)
        g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def draws(self, g): return [decode(g, e) for e in g.events if e.kind == DRAW]
    def armor(self, g): return g.state.entities[g.state.players[1].hero_id].armor
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); r = registry.__wrapped__(*self.config)
        self.assertEqual(Game.from_snapshot(deepcopy(saved), r).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        return Game.from_snapshot(deepcopy(saved), r)

    def test_complete_real_face_metadata_and_central_assembly(self):
        from hs_sim.cards import build_registry
        r = build_registry(); card = r.card(CARD)
        self.assertEqual((card.name, card.cost, card.attack, card.health), ('偷贩炼金师', 5, 3, 3))
        self.assertEqual(card.metadata.classes, (CardClass.MAGE,))
        self.assertEqual(len(load_batch()['official_observations']), 2)
        self.assertNotIn('JAIL_313e', r.cards)

    def test_actual_choice_excludes_source_enemy_and_does_not_discover(self):
        g = self.game(hand=(CARD, A, S, W, L, H))
        expected = set(g.state.players[1].hand[1:]); source = self.play(g)
        self.assertEqual({x.entity_id for x in g.state.pending_choice.options}, expected)
        self.assertNotIn(source, expected)
        self.assertEqual(g.state.players[1].mana, 75)
        self.assertFalse(any(e.kind == 'card_discovered' for e in g.events))
        self.assertFalse(self.draws(g))
        self.portable(g)

    def test_all_five_original_card_types_transform_same_physical_hand_slot(self):
        for cid in (A, S, W, L, H):
            with self.subTest(kind=cid):
                g = self.game(hand=(CARD, cid)); target = self.eid(g, cid); old = g.state.entities[target]
                self.play(g); self.choose(g, target)
                e = g.state.entities[target]
                self.assertEqual(g.state.players[1].hand, [target])
                self.assertIn(e.card_id, (D1, D2)); self.assertEqual(e.kind, CardType.SPELL)
                self.assertEqual((e.zone_epoch, e.owner, e.controller), (old.zone_epoch+1, old.owner, old.controller))
                self.assertEqual(local_cost(e)[0], 2)
                self.assertEqual(self.armor(g), 0)

    def test_duplicate_cards_are_distinct_and_only_selected_entity_changes(self):
        g = self.game(hand=(CARD, A, A)); first, second = g.state.players[1].hand[1:]
        self.play(g); self.assertEqual(len(g.state.pending_choice.options), 2)
        self.choose(g, second)
        self.assertEqual(g.state.entities[first].card_id, A)
        self.assertIn(g.state.entities[second].card_id, (D1, D2))

    def test_full_weighted_any_class_spell_tier_is_used(self):
        g = self.game(); target = self.eid(g, A); self.play(g); self.choose(g, target)
        row, = self.draws(g)
        self.assertEqual(row.candidates, ((D1, 1), (D2, 3)))
        self.assertEqual((row.request.query.min_cost, row.request.query.max_cost), (7, 7))
        self.assertEqual(row.request.retained_cost, 2)
        self.assertIsNone(row.request.retained_stats)

    def test_local_discount_and_zero_are_retained_and_determine_real_tiers(self):
        for script, cost, wanted in ((P+'discount', 1, D6), (P+'zero', 0, D5)):
            with self.subTest(script=script):
                g = self.game(hand=(script, CARD, A)); target = self.eid(g, A)
                self.play(g, script); self.play(g); self.choose(g, target)
                e = g.state.entities[target]
                self.assertEqual((e.card_id, local_cost(e)[0]), (wanted, cost))

    def test_external_discount_applies_once_and_current_quote_selects_tier(self):
        g = self.game(board=(AURA,)); target = self.eid(g, A)
        self.play(g); self.choose(g, target); e = g.state.entities[target]
        self.assertEqual((e.card_id, local_cost(e)[0]), (D6, 2))
        self.assertEqual(quote_unselected_cost(g.state, g.registry, e).amount, 1)

    def test_retention_does_not_copy_original_payment_currency(self):
        g = self.game(hand=(P+'health', CARD, A)); target = self.eid(g, A)
        self.play(g, P+'health')
        self.assertEqual(local_cost(g.state.entities[target])[1], PaymentType.HEALTH)
        self.play(g); self.choose(g, target)
        self.assertEqual(local_cost(g.state.entities[target]), (2, PaymentType.MANA))

    def test_retained_cost_is_installed_before_first_transform_notification(self):
        g = self.game(board=(WATCH,), mode='inspect'); target = self.eid(g, A)
        self.play(g); self.choose(g, target)
        self.assertEqual(self.armor(g), 2)

    def test_original_choice_numbers_are_not_requoted_after_choice_reaction(self):
        g = self.game(board=(WATCH,), mode='mutate'); target = self.eid(g, A)
        self.play(g); self.choose(g, target)
        self.assertIn(g.state.entities[target].card_id, (D1, D2))
        self.assertEqual(local_cost(g.state.entities[target])[0], 2)

    def test_leave_and_reenter_original_hand_reference_stays_stale_without_rng(self):
        g = self.game(board=(WATCH,), mode='stale'); target = self.eid(g, A)
        self.play(g); before = g._rng.getstate(); self.choose(g, target)
        self.assertEqual(g.state.entities[target].card_id, A)
        self.assertFalse(self.draws(g)); self.assertEqual(g._rng.getstate(), before)

    def test_empty_hand_and_plain_summon_do_not_require_unused_pool(self):
        g = self.game(hand=(CARD,), pool=False); self.play(g)
        self.assertIsNone(g.state.pending_choice); self.assertFalse(self.draws(g))
        g = self.game(hand=(P+'summon', A), pool=False); self.play(g, P+'summon')
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g.state.entities[self.eid(g, A)].card_id, A)

    def test_empty_selected_tier_keeps_original_and_does_not_draw_rng(self):
        g = self.game(hand=(P+'expensive', CARD, A)); target = self.eid(g, A)
        self.play(g, P+'expensive'); self.play(g); before = g._rng.getstate(); self.choose(g, target)
        self.assertEqual(g.state.entities[target].card_id, A)
        self.assertEqual(self.draws(g)[0].selected, ())
        self.assertEqual(g._rng.getstate(), before)

    def test_missing_pool_and_unknown_eligible_spell_fail_selected_transaction(self):
        for config in (dict(pool=False), dict(members=MEMBERS+(UNKNOWN,))):
            with self.subTest(config=config):
                g = self.game(**config); target = self.eid(g, A); self.play(g); before = g.snapshot()
                with self.assertRaises((ResolutionError, ValueError)): self.choose(g, target)
                self.assertEqual(g.snapshot(), before)

    def test_unknown_ineligible_tier_does_not_poison_selected_full_domain(self):
        g = self.game(members=MEMBERS+(UNKNOWN,), unknown_cost=8)
        target = self.eid(g, A); self.play(g); self.choose(g, target)
        self.assertEqual(self.draws(g)[0].candidates, ((D1, 1), (D2, 3)))

    def test_selected_real_spell_uses_retained_payment_and_new_printed_body(self):
        g = self.game(); target = self.eid(g, A); self.play(g); self.choose(g, target)
        self.assertEqual(g.state.players[1].mana, 75)
        g.apply(PlayCard(1, target))
        self.assertEqual(g.state.players[1].mana, 73)
        self.assertEqual(self.armor(g), 9)
        self.assertEqual(len(g.state.cast_history), 1)

    def test_current_copy_keeps_retained_cost_base_copy_uses_printed_cost(self):
        g = self.game(hand=(CARD, A, P+'copy', P+'base')); target = self.eid(g, A)
        self.play(g); self.choose(g, target); self.play(g, P+'copy'); self.play(g, P+'base')
        copies = [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].kind == CardType.SPELL]
        self.assertEqual(sorted(local_cost(e)[0] for e in copies), [2, 2, 7])

    def test_both_choice_and_transform_wait_are_portable_and_choice_failure_rolls_back(self):
        g = self.game(board=(WATCH,), mode='wait'); target = self.eid(g, A)
        self.play(g); other = self.portable(g)
        self.choose(g, target); self.choose(other, target)
        self.assertEqual(g.snapshot(), other.snapshot())
        other = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, key='bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())

    def test_second_seat_and_failed_transformation_preserve_original_paid_choice(self):
        g = self.game(actor=2); target = self.eid(g, A); self.play(g); self.choose(g, target)
        self.assertEqual(g.state.entities[target].controller, 2)
        g = self.game(board=(WATCH,), mode='fail'); target = self.eid(g, A)
        self.play(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, target)
        self.assertEqual(g.snapshot(), before)

    def test_new_cost_only_shape_does_not_relax_old_minion_stats_guards(self):
        g = self.game(); ref = CardReference.capture(g.state.entities[self.eid(g, A)])
        valid = TransformStoredFromPool(ref, POOL_ID, PoolQuery(kinds=(CardType.SPELL,), collectible=True), 1, retained_cost=0)
        for changes in (dict(retained_cost=True), dict(source_id=None), dict(query=PoolQuery(kinds=(CardType.MINION,), collectible=True)),
                        dict(query=PoolQuery(kinds=(CardType.SPELL,), collectible=False)),
                        dict(target=replace(ref, zone=Zone.DECK)), dict(retained_stats=SummonStats(2, 2))):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(valid, **changes)

    def test_player_choices_use_opaque_ids_and_do_not_expose_numeric_material_or_enemy_hand(self):
        g = self.game(); self.play(g)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe())+json.dumps(g.for_player(player).legal_actions())
            for key in ('retained_cost', 'reference', 'zone_epoch', 'entity_id', 'rng_state', 'StoredPoolTransformDraw'):
                self.assertNotIn(key, public)
        self.assertNotIn(A, json.dumps(g.for_player(2).observe()))


if __name__ == '__main__':
    unittest.main()
