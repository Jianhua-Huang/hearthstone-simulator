"""Four paid Prime chains and actual generated spell/attack/copy/resurrection effects."""
from dataclasses import replace
from functools import lru_cache
import json, unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_prime_leaves as native
from hs_sim.engine import Attack, EndTurn, Game, IllegalAction, PlayerSetup, ResolutionError, Scenario
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, Damage, Destroy, DestroyBatch, Draw,
    GainArmor, GrantKeyword, InvokeBehavior, RandomDamage, RequestChoice, ReturnToHand, Silence, TriggerDeathrattles)
from hs_sim.engine.model import (BattlecryRepeatSpec, CardDefinition, CardType, CastWhenDrawnSpec,
    DamageKind, DeathrattleRepeatSpec, Keyword, SummonQuantitySpec, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.registry import Registry
from hs_sim.engine.resurrection_summons import candidates as resurrection_candidates
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format

VASHJ, KARGATH, ZIXOR, KANRETHAD = native.ROOTS
VP, KP, ZP, CP = native.DEPENDENCIES
P = 'k711.'
A, B, DEMON, DEMON_B, ALL, IMMUNE, BIG, DEADLY, QUANTITY, BC_REPEAT, DR_REPEAT = (
    P+x for x in ('a', 'b', 'demon', 'demon_b', 'all', 'immune', 'big', 'deadly', 'quantity', 'bc_repeat', 'dr_repeat'))
LOW, MID, HIGH, AUTO, KILL, CLEAR, DRAW, HIT, HUSH, RETURN, CONTROL, POISON, BOOST, BC, EARLY = (
    P+x for x in ('low', 'mid', 'high', 'auto', 'kill', 'clear', 'draw', 'hit', 'hush', 'return', 'control', 'poison', 'boost', 'bc', 'early'))
WATCH_DRAW, WATCH_COPY, WATCH_ARMOR, WATCH_RES, FAIL = (
    P+x for x in ('watch_draw', 'watch_copy', 'watch_armor', 'watch_res', 'fail'))
UNITS = (A, B, DEMON, DEMON_B, ALL, IMMUNE, BIG, DEADLY, QUANTITY, BC_REPEAT, DR_REPEAT)
SPELLS = (LOW, MID, HIGH, AUTO, KILL, CLEAR, DRAW, HIT, HUSH, RETURN, CONTROL, POISON, BOOST, BC, EARLY)
HELPERS = (*UNITS, *SPELLS, WATCH_DRAW, WATCH_COPY, WATCH_ARMOR, WATCH_RES)
CHEAP_DEMON = P+'cheap_demon'


@lru_cache(None)
def host(role='writer'):
    h = build_cn37_local_pool_format(); r = h.registry; meta = metadata(collectible=False)
    r.register_card(CardDefinition(CHEAP_DEMON, CHEAP_DEMON, CardType.MINION, cost=1, attack=1, health=1,
        metadata=metadata(collectible=False, tribes=('demon',))))
    for cid, attack, hp, cost, tribes, extra in ((A, 2, 3, 4, (), {}), (B, 1, 1, 1, (), {}),
            (DEMON, 3, 4, 4, ('demon',), {}), (DEMON_B, 4, 6, 6, ('demon',), {}),
            (ALL, 2, 2, 2, ('all',), {}), (IMMUNE, 0, 1, 1, (), dict(keywords=(Keyword.IMMUNE,))),
            (BIG, 0, 30, 1, (), {}), (DEADLY, 10, 10, 1, (), {}),
            (QUANTITY, 0, 12, 1, (), dict(summon_quantities=(SummonQuantitySpec(),))),
            (BC_REPEAT, 0, 12, 1, (), dict(battlecry_repeats=(BattlecryRepeatSpec(2),))),
            (DR_REPEAT, 0, 12, 1, (), dict(deathrattle_repeats=(DeathrattleRepeatSpec(2),)))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=attack, health=hp, cost=cost,
            metadata=metadata(collectible=False, tribes=tribes), **extra))
    r.register_behavior(FAIL, lambda c: (_ for _ in ()).throw(ResolutionError('K711 intentional accepted Prime continuation failure')))
    def waiting(c):
        entity = c.state.entities.get(c.event.target_id)
        issuer = c.state.entities.get(c.event.source_id)
        options = (ChoiceOption('continue', 'Continue'), ChoiceOption('fault', 'Fail after RNG',
            (RandomDamage((c.state.players[2].hero_id,), 1, c.source_id), InvokeBehavior(FAIL, c.source_id, c.player_id))))
        if c.event.kind == 'card_drawn':
            if issuer is None or issuer.card_id != VP or entity is None or entity.zone != Zone.HAND: return ()
            ref = CardReference.capture(entity)
            options += (ChoiceOption('cycle', 'Move and draw original again',
                (MoveCard(ref, c.player_id, Zone.DECK, position='top', source_id=c.source_id), Draw(c.player_id, source_id=c.source_id))),)
        elif c.event.kind == 'minion_summoned':
            if c.source.card_id == WATCH_COPY:
                if entity is None or entity.card_id != ZP or entity.origin_entity_id is None: return ()
                original = c.state.entities.get(entity.origin_entity_id)
                if original is None or original.card_id != ZP: return ()
                if Keyword.RUSH not in entity.keywords: raise ResolutionError('Prime copy lost its complete printed Rush before notification')
                if original.zone == Zone.BOARD:
                    options += (ChoiceOption('bounce', 'Return original source', (ReturnToHand(original.id),)),
                        ChoiceOption('buff', 'Buff original source', (Buff(original.id, 2, 2, c.source_id),)))
            else:
                row = next((x for x in c.state.resurrection_history if x.entity_id == c.event.target_id), None)
                res_source = None if row is None else c.state.entities.get(row.source_id)
                if res_source is None or res_source.card_id != CP: return ()
        else:
            if c.event.player_id != c.player_id or c.event.amount != 10: return ()
        return (RequestChoice(c.player_id, options, c.source_id),)
    r.register_behavior(P+'wait', waiting)
    for cid, event in ((WATCH_DRAW, 'card_drawn'), (WATCH_COPY, 'minion_summoned'),
            (WATCH_RES, 'minion_summoned'), (WATCH_ARMOR, 'armor_gained')):
        r.register_card(CardDefinition(cid, cid, CardType.WEAPON, durability=20, metadata=meta,
            triggers=(TriggerSpec(event, P+'wait'),)))
    bodies = {LOW: lambda c: (), MID: lambda c: (), HIGH: lambda c: (),
        AUTO: lambda c: (GainArmor(c.player_id, 2),), KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        CLEAR: lambda c: (DestroyBatch(tuple(i for p in (1, 2) for i in c.state.players[p].board), c.source_id),),
        DRAW: lambda c: (Draw(c.player_id, source_id=c.source_id),),
        HIT: lambda c: (Damage(c.target_id, 1, c.source_id, DamageKind.SPELL),),
        HUSH: lambda c: (Silence(c.target_id),), RETURN: lambda c: (ReturnToHand(c.target_id),),
        CONTROL: lambda c: (ChangeControl(c.target_id, 2),), POISON: lambda c: (GrantKeyword(c.target_id, Keyword.POISONOUS, c.source_id),),
        BOOST: lambda c: (Buff(c.target_id, 2, 3, c.source_id), Damage(c.target_id, 1, c.source_id)),
        BC: lambda c: (TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]), c.source_id),),
        EARLY: lambda c: (TriggerDeathrattles(c.target_id, c.source_id),)}
    costs = {LOW: 2, MID: 5, HIGH: 7, AUTO: 5}
    targeted = {KILL, HIT, HUSH, RETURN, CONTROL, POISON, BOOST, BC, EARLY}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=costs.get(cid, 0), on_play=cid, metadata=meta,
            targeting=TargetSpec() if cid in targeted else None,
            keywords=(Keyword.CASTS_WHEN_DRAWN,) if cid == AUTO else (),
            cast_when_drawn=CastWhenDrawnSpec() if cid == AUTO else None))
    r.validate(); return h


@lru_cache(None)
def fixture(role='writer'):
    full = host(role).registry; r = Registry('k711-four-prime-original-named-bodies-v1')
    for bid, body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX): r.register_behavior(bid, body)
    for cid in ('HERO_08', 'HERO_08bp', *HELPERS, CHEAP_DEMON): r.register_card(full.card(cid))
    native.register_past_prime_leaves(r); r.validate(); return r


class PastPrimeLeafTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'small'
    registry_factory = staticmethod(lambda mode, role: host(role).registry if mode == 'host' else fixture(role))

    def game(self, hand=(), *, board=(), enemy=(), enemy_hand=(), deck=(), watch=None, real_host=False):
        self.mode = 'host' if real_host else 'small'
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
            mana=40, max_mana=40, mana_cap=40, weapon_card_id=watch, hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(B,)*8, mana=40, max_mana=40,
            mana_cap=40, hero_power_card_id='HERO_08bp')), seed=711, generation_context=host().context if real_host else None),
            self.registry_factory(self.mode, 'writer'))

    def unit(self, g, cid, player=1): return self.entity(g, cid, player, 'board')
    def bodies(self, g, cid, player=1):
        return [g.state.entities[i] for i in g.state.players[player].board if g.state.entities[i].card_id == cid]
    def cost(self, g, cid, player=1): return quote_unselected_cost(g.state, g.registry, self.entity(g, cid, player)).amount
    def armor(self, g, player=1): return g.state.entities[g.state.players[player].hero_id].armor
    def finish(self, g):
        count = 0
        while g.state.pending_choice is not None:
            count += 1; self.assertLess(count, 35); self.choose(g)
    def fault(self, g):
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)

    def test_complete_eight_original_faces_named_client_links_and_nonphysical_evidence(self):
        d = native.load_batch(); r = fixture()
        self.assertEqual(len(d['cards']), 4); self.assertEqual(len(d['dependencies']), 4)
        self.assertEqual(len(d['official_observations']), 18); self.assertEqual(len(d['original_candidate_ids']), 732)
        self.assertFalse(any(cid in r.cards for cid in native.EVIDENCE))
        for parent, child in zip(native.ROOTS, native.DEPENDENCIES):
            self.assertIsNotNone(r.card(parent).deathrattle); self.assertFalse(r.pool_card(child).metadata.collectible)

    def test_four_actual_paid_roots_shuffle_exact_prime_then_real_draw_and_paid_generated_entry(self):
        for parent, child in zip(native.ROOTS, native.DEPENDENCIES):
            with self.subTest(parent=parent):
                g = self.game((parent, KILL, DRAW)); eid = self.play(g, parent)
                self.assertEqual(g.state.players[1].mana, 40-g.registry.card(parent).cost)
                self.play(g, KILL, eid); generated = self.entity(g, child, zone='deck')
                self.assertEqual(generated.owner, 1)
                row = g.state.deck_shuffle_history[-1]
                self.assertEqual((row.actor_id, row.player_id, row.declared_count), (1, 1, 1))
                self.play(g, DRAW); self.assertEqual(self.entity(g, child).id, generated.id)
                prime_id = self.play(g, child)
                self.assertEqual(g.state.entities[prime_id].zone, Zone.BOARD)
                self.assertEqual(g.state.players[1].mana, 40-g.registry.card(parent).cost-g.registry.card(child).cost)

    def test_early_deathrattle_and_actual_repeat_each_shuffle_one_real_named_body(self):
        g = self.game((VASHJ, EARLY, KILL), board=(DR_REPEAT,)); eid = self.play(g, VASHJ)
        self.play(g, EARLY, eid); self.assertEqual(len(g.state.players[1].deck), 2)
        self.play(g, KILL, eid); self.assertEqual(len(g.state.players[1].deck), 4)
        self.assertTrue(all(g.state.entities[i].card_id == VP for i in g.state.players[1].deck))
        self.assertEqual(len(g.state.deck_shuffle_history), 4); self.portable(g)

    def test_source_control_and_silence_use_original_deathrattle_controller_lifecycle(self):
        g = self.game((KARGATH, CONTROL, KILL)); eid = self.play(g, KARGATH)
        self.play(g, CONTROL, eid); self.play(g, KILL, eid)
        self.assertEqual(sum(g.state.entities[i].card_id == KP for i in g.state.players[2].deck), 1)
        self.assertEqual(g.state.deck_shuffle_history[-1].actor_id, 2)
        g = self.game((ZIXOR, HUSH, KILL)); eid = self.play(g, ZIXOR)
        self.play(g, HUSH, eid); self.play(g, KILL, eid); self.assertEqual(g.state.players[1].deck, [])

    def test_both_vashj_faces_have_real_spell_damage_and_source_loss_removes_it(self):
        for cid in (VASHJ, VP):
            with self.subTest(cid=cid):
                g = self.game((HIT, HIT, HUSH), board=(cid,)); enemy = g.state.players[2].hero_id
                self.play(g, HIT, enemy); self.assertEqual(g.state.entities[enemy].health, 28)
                self.play(g, HUSH, self.unit(g, cid).id); self.play(g, HIT, enemy)
                self.assertEqual(g.state.entities[enemy].health, 27)

    def test_vashj_prime_three_real_spell_draws_discount_each_and_leave_minions(self):
        g = self.game((VP,), deck=(LOW, A, MID, HIGH)); self.play(g, VP)
        self.assertEqual(len(g.state.draw_history), 3)
        self.assertEqual({g.state.entities[i].card_id for i in g.state.players[1].hand}, {LOW, MID, HIGH})
        self.assertEqual({cid: self.cost(g, cid) for cid in (LOW, MID, HIGH)}, {LOW: 0, MID: 2, HIGH: 4})
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck], [A])

    def test_vashj_no_matching_spells_has_no_draw_fatigue_or_rng(self):
        g = self.game((VP,), deck=(A, B)); rng = g.snapshot()['rng_state']; self.play(g, VP)
        self.assertEqual(g.state.draw_history, []); self.assertEqual(g.snapshot()['rng_state'], rng)

    def test_vashj_full_hand_burn_does_not_discount_unrelated_hand_cards(self):
        g = self.game((VP,)+(B,)*9, deck=(HIGH, HIGH, HIGH)); self.play(g, VP)
        self.assertEqual([x.outcome for x in g.state.draw_history], ['hand', 'burned', 'burned'])
        self.assertEqual(self.cost(g, HIGH), 4); self.assertEqual(self.cost(g, B), 1)

    def test_vashj_cast_when_drawn_replacement_is_not_misidentified_as_original_discount(self):
        g = self.game((VP,), deck=(AUTO, A)); self.play(g, VP)
        self.assertEqual(self.armor(g), 2); self.assertEqual(self.cost(g, A), 4)
        self.assertEqual([r.outcome for r in g.state.draw_history], ['cast', 'hand'])
        self.assertEqual(len(g.state.cast_history), 1); self.portable(g)

    def test_vashj_wait_restore_and_failed_choice_keep_original_draw_discount(self):
        g = self.game((VP,), deck=(LOW, MID, HIGH), watch=WATCH_DRAW); self.play(g, VP)
        self.assertIsNotNone(g.state.pending_choice); self.portable(g); self.fault(g); self.finish(g)
        self.assertEqual([self.cost(g, cid) for cid in (LOW, MID, HIGH)], [0, 2, 4]); self.portable(g)

    def test_vashj_departure_and_immediate_redraw_do_not_rebind_old_hand_residence(self):
        g = self.game((VP,), deck=(HIGH,), watch=WATCH_DRAW); self.play(g, VP); self.choose(g, 'cycle'); self.finish(g)
        self.assertEqual(self.cost(g, HIGH), 7)
        self.assertEqual(len(g.state.draw_history), 2)
        self.assertNotEqual(g.state.draw_history[0].hand_entry_id, g.state.draw_history[1].hand_entry_id)

    def test_vashj_real_battlecry_repeat_performs_six_draws_without_second_payment(self):
        g = self.game((VP,), board=(BC_REPEAT,), deck=(LOW,)*6); self.play(g, VP)
        self.assertEqual(len(g.state.draw_history), 6); self.assertEqual(g.state.players[1].mana, 33)
        self.assertEqual(len(g.state.battlecry_history), 2)

    def test_kargath_prime_rush_real_attack_kill_grants_ten_armor(self):
        g = self.game((KP,), enemy=(B,)); eid = self.play(g, KP); victim = self.unit(g, B, 2).id
        g.apply(Attack(1, eid, victim)); self.assertEqual(self.armor(g), 10)
        self.assertEqual(g.state.death_history[-1].cause.kind, 'damage'); self.portable(g)

    def test_kargath_fresh_rush_cannot_attack_hero_and_failure_is_atomic(self):
        g = self.game((KP,)); eid = self.play(g, KP); saved = g.snapshot()
        with self.assertRaises(IllegalAction): g.apply(Attack(1, eid, g.state.players[2].hero_id))
        self.assertEqual(g.snapshot(), saved)

    def test_kargath_nonlethal_attack_and_unrelated_destruction_do_not_grant_armor(self):
        g = self.game((KP, KILL), enemy=(BIG,)); eid = self.play(g, KP); target = self.unit(g, BIG, 2).id
        g.apply(Attack(1, eid, target)); self.assertEqual(self.armor(g), 0)
        self.play(g, KILL, target); self.assertEqual(self.armor(g), 0)

    def test_kargath_defensive_counterattack_kill_and_source_death_have_no_local_reward(self):
        g = self.game(board=(KP,), enemy=(DEMON,)); prime = self.unit(g, KP).id; attacker = self.unit(g, DEMON, 2).id
        g.apply(EndTurn(1)); g.apply(Attack(2, attacker, prime))
        self.assertEqual(g.state.entities[attacker].zone, Zone.GRAVEYARD); self.assertEqual(self.armor(g), 0)
        g = self.game((KP,), enemy=(DEADLY,)); eid = self.play(g, KP)
        g.apply(Attack(1, eid, self.unit(g, DEADLY, 2).id))
        self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD); self.assertEqual(self.armor(g), 0)

    def test_kargath_mature_hero_attack_and_silenced_source_do_not_grant_minion_kill_reward(self):
        g = self.game((KP,), deck=(B,)*2); eid = self.play(g, KP)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); g.apply(Attack(1, eid, g.state.players[2].hero_id))
        self.assertEqual(self.armor(g), 0)
        g = self.game((HUSH,), board=(KP,), enemy=(B,)); eid = self.unit(g, KP).id
        self.play(g, HUSH, eid); g.apply(Attack(1, eid, self.unit(g, B, 2).id)); self.assertEqual(self.armor(g), 0)

    def test_kargath_armor_notification_wait_keeps_one_accepted_reward_and_replay(self):
        g = self.game((KP,), enemy=(B,), watch=WATCH_ARMOR); eid = self.play(g, KP)
        g.apply(Attack(1, eid, self.unit(g, B, 2).id)); self.assertEqual(self.armor(g), 10)
        self.assertIsNotNone(g.state.pending_choice); self.portable(g); self.fault(g); self.finish(g)
        self.assertEqual(self.armor(g), 10)

    def test_kargath_original_poison_combat_death_counts_as_attack_kill(self):
        g = self.game((KP, POISON), enemy=(BIG,)); eid = self.play(g, KP); self.play(g, POISON, eid)
        g.apply(Attack(1, eid, self.unit(g, BIG, 2).id)); self.assertEqual(self.armor(g), 10)
        self.assertEqual(g.state.death_history[-1].cause.kind, 'poison')

    def test_zixor_prime_creates_three_current_rush_copies_without_recursive_battlecries(self):
        g = self.game((ZP,)); eid = self.play(g, ZP)
        units = self.bodies(g, ZP); self.assertEqual(len(units), 4)
        self.assertEqual([e.origin_entity_id for e in units if e.id != eid], [eid]*3)
        self.assertTrue(all(Keyword.RUSH in e.keywords for e in units))
        self.assertEqual(len(g.state.battlecry_history), 1); self.assertEqual(g.state.players[1].mana, 32)

    def test_zixor_current_copy_preserves_buffs_damage_and_independent_attachments(self):
        g = self.game((BOOST, BC), board=(ZP,)); eid = self.unit(g, ZP).id
        self.play(g, BOOST, eid); self.play(g, BC, eid); units = self.bodies(g, ZP)
        self.assertEqual([(e.attack, e.max_health, e.damage) for e in units], [(6, 7, 1)]*4)
        self.assertEqual(len({e.abilities[0].id for e in units}), 4); self.portable(g)

    def test_zixor_capacity_and_quantity_use_original_public_entry_policies(self):
        g = self.game((ZP,), board=(B,)*5); self.play(g, ZP)
        self.assertEqual(len(self.bodies(g, ZP)), 2); self.assertEqual(len(g.state.players[1].board), 7)
        g = self.game((ZP,), board=(QUANTITY,)); self.play(g, ZP)
        self.assertEqual(len(self.bodies(g, ZP)), 6); self.assertEqual(len(g.state.players[1].board), 7)

    def test_zixor_first_copy_wait_restores_and_bad_choice_rolls_back(self):
        g = self.game((ZP,), watch=WATCH_COPY); self.play(g, ZP)
        self.assertIsNotNone(g.state.pending_choice); self.portable(g); self.fault(g); self.finish(g)
        self.assertEqual(len(self.bodies(g, ZP)), 4); self.portable(g)

    def test_zixor_returned_original_is_not_rebound_by_remaining_copies(self):
        g = self.game((ZP,), watch=WATCH_COPY); eid = self.play(g, ZP)
        self.choose(g, 'bounce'); self.portable(g); self.finish(g)
        self.assertEqual(g.state.entities[eid].zone, Zone.HAND)
        self.assertEqual(len(self.bodies(g, ZP)), 1)

    def test_zixor_later_copies_use_ordinary_per_execution_current_material_policy(self):
        g = self.game((ZP,), watch=WATCH_COPY); eid = self.play(g, ZP)
        self.choose(g, 'buff'); self.finish(g)
        copied = [x for x in self.bodies(g, ZP) if x.id != eid]
        self.assertEqual([(e.attack, e.max_health) for e in copied], [(4, 4), (6, 6), (6, 6)])

    def test_kanrethad_source_aura_only_discounts_friendly_demons_and_clamps_at_zero(self):
        g = self.game((KANRETHAD, DEMON, ALL, A, CHEAP_DEMON), enemy_hand=(DEMON,)); self.play(g, KANRETHAD)
        self.assertEqual((self.cost(g, DEMON), self.cost(g, ALL), self.cost(g, A), self.cost(g, DEMON, 2), self.cost(g, CHEAP_DEMON)), (3, 1, 4, 4, 0))
        self.assertEqual(g.state.players[1].mana, 38)

    def test_kanrethad_aura_stacks_and_silence_death_remove_only_original_sources(self):
        g = self.game((KANRETHAD, KANRETHAD, DEMON, HUSH, KILL)); first = self.play(g, KANRETHAD)
        second = self.play(g, KANRETHAD); self.assertEqual(self.cost(g, DEMON), 2)
        self.play(g, HUSH, first); self.assertEqual(self.cost(g, DEMON), 3)
        self.play(g, KILL, second); self.assertEqual(self.cost(g, DEMON), 4)

    def test_kanrethad_control_transfer_moves_current_cost_aura_to_new_controller(self):
        g = self.game((KANRETHAD, CONTROL, DEMON), enemy_hand=(DEMON,)); eid = self.play(g, KANRETHAD)
        self.play(g, CONTROL, eid)
        self.assertEqual((self.cost(g, DEMON), self.cost(g, DEMON, 2)), (4, 3)); self.portable(g)

    def test_kanrethad_prime_uses_three_original_friendly_demon_deaths_not_enemy_or_other_types(self):
        g = self.game((CLEAR, CP), board=(DEMON, DEMON, DEMON_B, A), enemy=(DEMON,)); self.play(g, CLEAR)
        expected = {d.id for d in g.state.death_history if d.controller == 1 and d.card_id in (DEMON, DEMON_B)}
        self.play(g, CP); root = g.state.resurrection_summon_history[-1]
        self.assertEqual({d.id for d in resurrection_candidates(g.registry, root.basis)}, expected)
        self.assertEqual({r.death_id for r in g.state.resurrection_history}, expected)
        self.assertEqual(len(self.bodies(g, DEMON)), 2); self.assertEqual(len(self.bodies(g, DEMON_B)), 1)
        self.assertTrue(all(e.damage == 0 for e in self.bodies(g, DEMON)+self.bodies(g, DEMON_B)))

    def test_kanrethad_empty_and_small_graveyards_follow_explicit_local_without_replacement_profile(self):
        g = self.game((CP,)); rng = g.snapshot()['rng_state']; self.play(g, CP)
        self.assertEqual(g.state.resurrection_history, []); self.assertEqual(g.snapshot()['rng_state'], rng)
        g = self.game((CLEAR, CP), board=(DEMON,)); self.play(g, CLEAR); self.play(g, CP)
        self.assertEqual(len(g.state.resurrection_history), 1)

    def test_kanrethad_prime_original_resurrection_wait_restore_and_failure_preserve_inventory(self):
        g = self.game((CLEAR, CP), board=(DEMON, DEMON_B, ALL), watch=WATCH_RES); self.play(g, CLEAR); self.play(g, CP)
        self.assertIsNotNone(g.state.pending_choice); self.portable(g); self.fault(g); self.finish(g)
        self.assertEqual(len(g.state.resurrection_history), 3); self.portable(g)

    def test_actual_standard_host_all_four_generated_prime_entries_and_private_deck_views(self):
        for parent, child in zip(native.ROOTS, native.DEPENDENCIES):
            with self.subTest(parent=parent):
                g = self.game((parent, KILL, DRAW), real_host=True); eid = self.play(g, parent); self.play(g, KILL, eid)
                for viewer in (1, 2):
                    view = json.dumps(g.for_player(viewer).observe())
                    self.assertNotIn('rng_state', view)
                self.play(g, DRAW); self.play(g, child)
        self.portable(g)


if __name__ == '__main__': unittest.main()
