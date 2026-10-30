"""Real named Prime chain, pre-activation Choose One and complete Fungal entries."""
from functools import lru_cache
import json, unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import msshifn_prime_cards as native
from hs_sim.engine import Attack, EndTurn, Game, IllegalAction, PlayCard, PlayerSetup, ResolutionError, Scenario
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy, Draw, InvokeBehavior,
    RandomDamage, RequestChoice, ReturnToHand, Silence, TriggerDeathrattles)
from hs_sim.engine.model import (BattlecryRepeatSpec, BoardPresenceReference, CardDefinition, CardType,
    DeathrattleRepeatSpec, Keyword, SummonQuantitySpec, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.registry import Registry
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.local_pool_format import build_cn37_local_pool_format

MSSHIFN, PRIME = native.MSSHIFN, native.PRIME
GUARDIAN, BRUISER, GARGANTUAN = native.TOKENS
P = 'k712.'
A, B, BOTH, QUANTITY, BC_REPEAT, DR_REPEAT = (P+x for x in ('plain', 'small', 'both', 'quantity', 'bc_repeat', 'dr_repeat'))
KILL, DRAW, HUSH, RETURN, CONTROL, EARLY, COPY, SUMMON = (P+x for x in ('kill', 'draw', 'hush', 'return', 'control', 'early', 'copy', 'summon'))
WAIT_TOKEN, WAIT_INSERT, FAIL = (P+x for x in ('wait_token', 'wait_insert', 'fail'))
HELPERS = (A, B, BOTH, QUANTITY, BC_REPEAT, DR_REPEAT, KILL, DRAW, HUSH, RETURN, CONTROL, EARLY, COPY, SUMMON, WAIT_TOKEN, WAIT_INSERT)


@lru_cache(None)
def host(role='writer'):
    h = build_cn37_local_pool_format(); r = h.registry; meta = metadata(collectible=False)
    for cid, extra in ((A, {}), (B, {}), (BOTH, dict(choose_both=True)),
            (QUANTITY, dict(summon_quantities=(SummonQuantitySpec(),))),
            (BC_REPEAT, dict(battlecry_repeats=(BattlecryRepeatSpec(2),))),
            (DR_REPEAT, dict(deathrattle_repeats=(DeathrattleRepeatSpec(2),)))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1, attack=1 if cid == B else 0,
            health=1 if cid == B else 20, metadata=meta, **extra))
    r.register_behavior(FAIL, lambda c: (_ for _ in ()).throw(ResolutionError('K712 intentional accepted continuation failure')))
    def waiting(c):
        target = c.state.entities.get(c.event.target_id)
        if target is None or target.card_id not in (native.TOKENS if c.source.card_id == WAIT_TOKEN else (PRIME,)): return ()
        options = (ChoiceOption('continue', 'Continue'), ChoiceOption('fault', 'Fail after RNG',
            (RandomDamage((c.state.players[2].hero_id,), 1, c.source_id), InvokeBehavior(FAIL, c.source_id, c.player_id))))
        if c.source.card_id == WAIT_TOKEN:
            original = next((i for i in c.state.players[1].board if c.state.entities[i].card_id == PRIME), None)
            if original is not None: options += (ChoiceOption('kill_source', 'Destroy original Prime', (Destroy(original, c.source_id),)),)
        return (RequestChoice(c.player_id, options, c.source_id),)
    r.register_behavior(P+'wait', waiting)
    for cid, event in ((WAIT_TOKEN, 'minion_summoned'), (WAIT_INSERT, 'card_added_to_deck')):
        r.register_card(CardDefinition(cid, cid, CardType.WEAPON, durability=20, metadata=meta, triggers=(TriggerSpec(event, P+'wait'),)))
    bodies = {KILL: lambda c: (Destroy(c.target_id, c.source_id),), DRAW: lambda c: (Draw(c.player_id, source_id=c.source_id),),
        HUSH: lambda c: (Silence(c.target_id),), RETURN: lambda c: (ReturnToHand(c.target_id),),
        CONTROL: lambda c: (ChangeControl(c.target_id, 2),), EARLY: lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        COPY: lambda c: (CopyMinion(BoardPresenceReference.capture(c.state, c.target_id), c.player_id, cause=SummonCause.capture(c)),),
        SUMMON: lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(PRIME),), SummonCause.capture(c)),)}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=meta,
            targeting=None if cid in (DRAW, SUMMON) else TargetSpec()))
    r.validate(); return h


@lru_cache(None)
def fixture(role='writer'):
    full = host(role).registry; r = Registry('k712-msshifn-real-choose-one-v1')
    for bid, body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX): r.register_behavior(bid, body)
    for cid in ('HERO_08', 'HERO_08bp', *HELPERS): r.register_card(full.card(cid))
    native.register_msshifn_prime_cards(r); r.validate(); return r


class MsshifnPrimeTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'small'
    registry_factory = staticmethod(lambda mode, role: host(role).registry if mode == 'host' else fixture(role))

    def game(self, hand=(), *, board=(), enemy=(), deck=(), watch=None, real_host=False):
        self.mode = 'host' if real_host else 'small'
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
            mana=40, max_mana=40, mana_cap=40, weapon_card_id=watch, hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', board=enemy, deck=(B,)*8, mana=40, max_mana=40, mana_cap=40,
            hero_power_card_id='HERO_08bp')), seed=712, generation_context=host().context if real_host else None),
            self.registry_factory(self.mode, 'writer'))
    def prime(self, g, branch):
        eid = self.entity(g, PRIME).id; g.apply(PlayCard(1, eid, branch_id=branch)); return eid
    def unit(self, g, cid, player=1): return self.entity(g, cid, player, 'board')
    def board(self, g, player=1): return [g.state.entities[i].card_id for i in g.state.players[player].board]
    def finish(self, g):
        count = 0
        while g.state.pending_choice is not None:
            count += 1; self.assertLess(count, 15); self.choose(g)
    def fault(self, g):
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)

    def test_full_seven_original_faces_and_five_physical_metadata_roles(self):
        d = native.load_batch(); r = fixture()
        self.assertEqual(len(d['cards']), 1); self.assertEqual(len(d['dependencies']), 6)
        self.assertEqual(len(d['official_observations']), 12); self.assertEqual(len(d['original_candidate_ids']), 732)
        for cid in native.CHOICES:
            self.assertTrue(r.card(cid).choice_only); self.assertIsNone(r.card(cid).on_play); self.assertNotIn(cid, r.pool_cards)
        for cid in native.PHYSICAL: self.assertIn(cid, r.pool_cards)
        self.assertFalse(any(cid in r.cards for cid in native.EVIDENCE))
        self.assertIsNone(r.card(PRIME).battlecry); self.assertIsNotNone(r.card(PRIME).choose_one)

    def test_actual_root_death_shuffle_draw_and_paid_prime_guardian_entry(self):
        g = self.game((MSSHIFN, KILL, DRAW)); root = self.play(g, MSSHIFN)
        self.assertIn(Keyword.TAUNT, g.state.entities[root].keywords); self.assertEqual(g.state.players[1].mana, 37)
        self.play(g, KILL, root); inserted = self.entity(g, PRIME, zone='deck').id
        self.assertEqual((g.state.deck_shuffle_history[-1].actor_id, g.state.deck_shuffle_history[-1].player_id), (1, 1))
        self.play(g, DRAW); self.assertEqual(self.entity(g, PRIME).id, inserted); self.prime(g, native.TAUNT_OPTION)
        self.assertEqual(self.board(g), [PRIME, GUARDIAN]); self.assertEqual(g.state.players[1].mana, 27)
        self.portable(g)

    def test_all_five_physical_faces_have_ordinary_paid_entries(self):
        for cid in native.PHYSICAL:
            with self.subTest(card=cid):
                g = self.game((cid,)); eid = self.prime(g, native.RUSH_OPTION) if cid == PRIME else self.play(g, cid)
                self.assertEqual(g.state.entities[eid].card_id, cid)
                self.assertEqual(g.state.players[1].mana, 40-g.registry.card(cid).cost)
                self.assertEqual(len(g.state.play_history), 1)

    def test_guardian_branch_summons_exact_taunt_body_without_rush_or_battlecry(self):
        g = self.game((PRIME,)); self.prime(g, native.TAUNT_OPTION); e = self.unit(g, GUARDIAN)
        self.assertEqual((e.attack, e.max_health), (9, 9)); self.assertIn(Keyword.TAUNT, e.keywords)
        self.assertNotIn(Keyword.RUSH, e.keywords); self.assertEqual(g.state.battlecry_history, [])
        self.assertEqual(g.state.cast_history, []); self.assertEqual(g.state.play_history[-1].branch_id, native.TAUNT_OPTION)

    def test_rush_branch_exact_bruiser_can_attack_minion_immediately(self):
        g = self.game((PRIME,), enemy=(B,)); self.prime(g, native.RUSH_OPTION); e = self.unit(g, BRUISER)
        self.assertIn(Keyword.RUSH, e.keywords); self.assertNotIn(Keyword.TAUNT, e.keywords)
        target = self.unit(g, B, 2).id; g.apply(Attack(1, e.id, target))
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD); self.portable(g)

    def test_fresh_guardian_and_prime_cannot_attack_and_rush_cannot_hit_hero(self):
        for branch, body in ((native.TAUNT_OPTION, GUARDIAN), (native.RUSH_OPTION, BRUISER)):
            g = self.game((PRIME,)); self.prime(g, branch)
            for cid in (PRIME, body):
                before = g.snapshot()
                with self.assertRaises(IllegalAction): g.apply(Attack(1, self.unit(g, cid).id, g.state.players[2].hero_id))
                self.assertEqual(g.snapshot(), before)

    def test_legal_actions_offer_two_original_options_and_no_invented_combined_branch(self):
        g = self.game((PRIME,)); eid = self.entity(g, PRIME).id
        self.assertEqual({a.branch_id for a in g.legal_actions() if isinstance(a, PlayCard) and a.entity_id == eid}, set(native.CHOICES))
        self.assertEqual({a['branch'] for a in g.for_player(1).legal_actions()['actions'] if a['type'] == 'play_card'}, set(native.CHOICES))

    def test_missing_unknown_and_unauthorized_both_branch_reject_before_payment(self):
        for branch in (None, 'unknown', 'both'):
            g = self.game((PRIME,)); before = g.snapshot()
            with self.assertRaises(IllegalAction): self.prime(g, branch)
            self.assertEqual(g.snapshot(), before)

    def test_actual_choose_both_produces_one_named_gargantuan_not_two_bodies(self):
        g = self.game((PRIME,), board=(BOTH,)); eid = self.entity(g, PRIME).id
        self.assertEqual({a.branch_id for a in g.legal_actions() if isinstance(a, PlayCard) and a.entity_id == eid}, {'both'})
        self.prime(g, 'both'); self.assertEqual(self.board(g), [BOTH, PRIME, GARGANTUAN])
        e = self.unit(g, GARGANTUAN); self.assertEqual((e.attack, e.max_health), (9, 9))
        self.assertTrue({Keyword.TAUNT, Keyword.RUSH} <= e.keywords); self.assertEqual(g.state.players[1].mana, 30)
        self.portable(g)

    def test_choose_both_does_not_accept_single_option_and_silence_removes_policy(self):
        g = self.game((PRIME, HUSH), board=(BOTH,)); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.prime(g, native.TAUNT_OPTION)
        self.assertEqual(g.snapshot(), before); self.play(g, HUSH, self.unit(g, BOTH).id)
        self.prime(g, native.TAUNT_OPTION); self.assertIn(GUARDIAN, self.board(g))

    def test_prime_can_fill_last_board_slot_even_if_its_chosen_body_cannot_enter(self):
        g = self.game((PRIME,), board=(A,)*6); rng = g.snapshot()['rng_state']; self.prime(g, native.TAUNT_OPTION)
        self.assertEqual(len(self.board(g)), 7); self.assertNotIn(GUARDIAN, self.board(g))
        self.assertEqual(g.snapshot()['rng_state'], rng); self.assertEqual(g.state.players[1].mana, 30)

    def test_original_quantity_source_multiplies_chosen_summon_not_paid_prime(self):
        g = self.game((PRIME,), board=(QUANTITY,)); self.prime(g, native.RUSH_OPTION)
        self.assertEqual(self.board(g).count(PRIME), 1); self.assertEqual(self.board(g).count(BRUISER), 2)
        self.assertTrue(all(Keyword.RUSH in g.state.entities[i].keywords for i in g.state.players[1].board if g.state.entities[i].card_id == BRUISER))

    def test_battlecry_repeat_does_not_turn_real_choose_one_into_battlecry(self):
        g = self.game((PRIME,), board=(BC_REPEAT,)); self.prime(g, native.TAUNT_OPTION)
        self.assertEqual(self.board(g).count(GUARDIAN), 1); self.assertEqual(g.state.battlecry_history, [])

    def test_root_early_and_repeated_natural_deathrattle_each_shuffle_named_prime(self):
        g = self.game((MSSHIFN, EARLY, KILL), board=(DR_REPEAT,)); eid = self.play(g, MSSHIFN)
        self.play(g, EARLY, eid); self.assertEqual(len(g.state.players[1].deck), 2)
        self.play(g, KILL, eid); self.assertEqual(len(g.state.players[1].deck), 4)
        self.assertTrue(all(g.state.entities[i].card_id == PRIME for i in g.state.players[1].deck)); self.portable(g)

    def test_silenced_root_and_dead_prime_do_not_create_another_upgrade(self):
        g = self.game((MSSHIFN, HUSH, KILL)); eid = self.play(g, MSSHIFN)
        self.play(g, HUSH, eid); self.play(g, KILL, eid); self.assertEqual(g.state.players[1].deck, [])
        g = self.game((PRIME, KILL)); eid = self.prime(g, native.TAUNT_OPTION); self.play(g, KILL, eid)
        self.assertEqual(g.state.players[1].deck, []); self.assertEqual(self.board(g), [GUARDIAN])

    def test_root_control_change_uses_actual_deathrattle_controller_and_shuffle_actor(self):
        g = self.game((MSSHIFN, CONTROL, KILL)); eid = self.play(g, MSSHIFN)
        self.play(g, CONTROL, eid); self.play(g, KILL, eid)
        self.assertEqual(sum(g.state.entities[i].card_id == PRIME for i in g.state.players[2].deck), 1)
        self.assertEqual((g.state.deck_shuffle_history[-1].actor_id, g.state.deck_shuffle_history[-1].player_id), (2, 2))
        self.portable(g)

    def test_ordinary_summoned_prime_has_no_choose_payload_or_fake_battlecry(self):
        g = self.game((SUMMON,)); self.play(g, SUMMON)
        self.assertEqual(self.board(g), [PRIME]); self.assertEqual(g.state.battlecry_history, [])

    def test_current_prime_copy_keeps_material_without_reexecuting_choose_payload(self):
        g = self.game((PRIME, COPY)); eid = self.prime(g, native.TAUNT_OPTION); self.play(g, COPY, eid)
        self.assertEqual(self.board(g).count(PRIME), 2); self.assertEqual(self.board(g).count(GUARDIAN), 1)
        self.assertEqual(g.state.battlecry_history, []); self.portable(g)

    def test_returned_prime_can_choose_other_real_branch_on_next_paid_play(self):
        g = self.game((PRIME, RETURN)); eid = self.prime(g, native.TAUNT_OPTION)
        self.play(g, RETURN, eid); self.assertEqual(g.state.entities[eid].zone, Zone.HAND)
        self.prime(g, native.RUSH_OPTION); self.assertEqual(self.board(g), [GUARDIAN, PRIME, BRUISER])
        self.assertEqual(g.state.players[1].mana, 20); self.portable(g)

    def test_first_quantity_body_wait_restores_and_actual_failure_rolls_back(self):
        g = self.game((PRIME,), board=(QUANTITY,), watch=WAIT_TOKEN); self.prime(g, native.TAUNT_OPTION)
        self.assertIsNotNone(g.state.pending_choice); g = self.portable(g); self.fault(g); self.finish(g)
        self.assertEqual(self.board(g).count(GUARDIAN), 2); self.assertEqual(self.board(g).count(PRIME), 1); self.portable(g)

    def test_accepted_quantity_tail_keeps_original_prime_cause_after_source_death(self):
        g = self.game((PRIME,), board=(QUANTITY,), watch=WAIT_TOKEN); eid = self.prime(g, native.RUSH_OPTION)
        g = self.portable(g); self.choose(g, 'kill_source'); self.finish(g)
        self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD); self.assertEqual(self.board(g).count(BRUISER), 2)
        self.portable(g)

    def test_shuffle_notice_wait_restores_then_real_draw_and_choose_continue_once(self):
        g = self.game((MSSHIFN, KILL, DRAW), watch=WAIT_INSERT); eid = self.play(g, MSSHIFN); self.play(g, KILL, eid)
        self.assertIsNotNone(g.state.pending_choice); g = self.portable(g); self.fault(g); self.finish(g)
        self.assertEqual(len(g.state.players[1].deck), 1); self.play(g, DRAW); self.prime(g, native.RUSH_OPTION)
        self.assertEqual(self.board(g), [PRIME, BRUISER]); self.portable(g)

    def test_actual_standard_host_original_chain_and_all_three_chosen_bodies(self):
        for branch, body, board in ((native.TAUNT_OPTION, GUARDIAN, ()), (native.RUSH_OPTION, BRUISER, ()), ('both', GARGANTUAN, (BOTH,))):
            with self.subTest(branch=branch):
                g = self.game((MSSHIFN, KILL, DRAW), board=board, real_host=True)
                eid = self.play(g, MSSHIFN); self.play(g, KILL, eid); self.play(g, DRAW); self.prime(g, branch)
                self.assertIn(body, self.board(g)); self.assertEqual(g.state.players[1].mana, 27)
        self.portable(g)


if __name__ == '__main__': unittest.main()
