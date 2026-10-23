from dataclasses import replace
from functools import lru_cache
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin, event_player
from hs_sim.cards import build_registry
from hs_sim.cards.past_one_cost_grant_cards import (
    ASHTONGUE, CLOCKER, ETHEREAL, GUARDIAN, JOUSTER, LACKEY, LEAVES,
    POGO, ROCKET, SECRET, SLITHERSPEAR, TRAPPER, load_batch,
)
from hs_sim.engine import (
    BoardPresenceReference, CardDefinition, CardType, EndTurn, Game, Keyword,
    PlayCard, PlayerSetup, Scenario, TargetSpec, TriggerSpec, UseHeroPower, Zone,
)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.card_conditions import matches_ability
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.cross_zone import RandomBuffStoredMinion
from hs_sim.engine.effects import (
    Buff, ChangeControl, ChoiceOption, Damage, Destroy, GrantKeyword, InvokeBehavior,
    RequestChoice, ReturnToHand, Silence, Transform, TriggerDeathrattles,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_rules import spell_bonus
from hs_sim.engine.joust import joust_result
from hs_sim.engine.model import CardAbilityCondition, CostSpec, DamageKind, TargetMode, TribeChangeSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.sacrifice import GrantCapturedSpellDamage, MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from tools.card_batch import check_face


P = 'k457.'
ZERO, HURT, LETHAL, KILL, BOLT, GROW, BOUNCE, TAKE, SILENCE, BC, DR, RECRUIT, FAIL, WATCH, UNKNOWN = (
    P+k for k in ('zero', 'hurt', 'lethal', 'kill', 'bolt', 'grow', 'bounce', 'take',
        'silence', 'battlecry', 'deathrattle', 'recruit', 'fail', 'watch', 'unknown'))
YETI, RAVEN, MECH, COUNTER, FLASHBACK = 'CORE_CS2_182', 'KAR_300', 'BOT_059', 'CORE_EX1_287', 'TIME_711'
CONTEXT = GenerationContext('k457-explicit-ten-grant-leaves', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry()
    r.register_pool(PoolDefinition('constructed.past.cards', 'explicit-ten-grants-v1',
        CONTEXT.target_id, CONTEXT.mode, tuple(PoolMember(cid) for cid in LEAVES), complete=True))
    r.register_card(CardDefinition(UNKNOWN, UNKNOWN, CardType.MINION, cost=1, attack=1, health=2,
        metadata=replace(r.card(YETI).metadata, collectible=False, tribes=None, deck_identity=UNKNOWN)))

    def fail(c):
        raise ResolutionError('K457 deliberate continuation failure')

    def hand_mech(c):
        target = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id == YETI)
        return (ChangeMinionTribes(CardReference.capture(target), TribeChangeSpec('set', ('mech',)), c.source_id),)

    def recruit(c):
        return (SummonFromZone(c.player_id, zone=Zone.HAND, query=PoolQuery(card_ids=(POGO,)),
            selection='first', source_id=c.source_id, cause=SummonCause.capture(c)),)

    bodies = {
        ZERO: lambda c: (), HURT: lambda c: (Damage(c.target_id, 1, c.source_id, DamageKind.EFFECT),),
        LETHAL: lambda c: (Damage(c.target_id, 6, c.source_id, DamageKind.EFFECT),),
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        BOLT: lambda c: (Damage(c.target_id, 1, c.source_id, DamageKind.SPELL),),
        GROW: lambda c: (Buff(c.target_id, attack=2, health=1, source_id=c.source_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        TAKE: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        SILENCE: lambda c: (Silence(c.target_id),),
        BC: lambda c: (TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]), c.source_id),),
        DR: lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        P+'shield': lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),),
        P+'hand_mech': hand_mech, RECRUIT: recruit, FAIL: fail,
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        target = None if cid in (ZERO, RECRUIT, P+'hand_mech', FAIL) else (
            TargetSpec() if cid == BOLT else TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,)))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, targeting=target))

    def watch(c):
        event = c.event
        if event_player(c) != c.player_id:
            return ()
        if event.kind == 'damage_dealt' and c.state.entities[event.target_id].card_id != YETI:
            return ()
        if mode == 'fail':
            return () if event.kind == 'damage_dealt' else (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        if event.kind == 'ability_granted':
            return ()
        options = [ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))]
        if event.kind == 'damage_dealt':
            target = event.target_id
            options.extend((
                ChoiceOption('kill', 'Destroy the original recipient', (Destroy(target, c.source_id),)),
                ChoiceOption('steal', 'Transfer the original recipient', (ChangeControl(target, 2),)),
                ChoiceOption('transform', 'Transform in the same board residence', (Transform(target, RAVEN),)),
                ChoiceOption('reset', 'Return and recruit the same physical card', (
                    ReturnToHand(target), SummonFromZone(c.player_id, zone=Zone.HAND,
                        query=PoolQuery(card_ids=(YETI,)), selection='first', source_id=c.source_id,
                        cause=SummonCause.capture(c)))),
            ))
        if event.kind == 'joust_resolved':
            result = joust_result(event)
            options.append(ChoiceOption('source_bounce', 'Return the original Jouster', (ReturnToHand(event.source_id),)))
            if result.own is not None:
                options.append(ChoiceOption('cheapen', 'Change the original revealed card cost',
                    (ModifyStoredCost(result.own.card, CostSpec(delta=-9), c.source_id),)))
        return (RequestChoice(c.player_id, tuple(options), c.source_id),)

    behavior = WATCH+'.'+mode
    r.register_behavior(behavior, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=40,
        metadata=replace(r.card(YETI).metadata, collectible=False, deck_identity=WATCH),
        triggers=tuple(TriggerSpec(event, behavior) for event in
            ('damage_dealt', 'ability_granted', 'joust_resolved', 'stored_card_buffed')) if mode != 'normal' else ()))
    r.validate()
    return r


class PastOneCostGrantTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), board=(), *, enemy_hand=(), enemy_board=(), deck=(), enemy_deck=(),
             active=1, mode='normal'):
        self.mode = mode; marker = () if mode == 'normal' else (WATCH,)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=marker+board, deck=deck,
                hero_power_card_id='HERO_08bp', mana=10, max_mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board, deck=enemy_deck,
                hero_power_card_id='HERO_08bp', mana=10, max_mana=10)),
            active_player=active, seed=457, generation_context=CONTEXT), fixture(mode))

    def bonus(self, g, player=1):
        return spell_bonus(g.state, player, g.registry)

    def test_ten_complete_raw_rows_and_twenty_full_primary_faces(self):
        data = load_batch(); rows = {x['record']['id']: x['record'] for x in data['dependencies']}
        self.assertEqual((len(rows), len(data['official_observations'])), (10, 20))
        for x in data['official_observations']: check_face(rows[x['card_id']], x['face'], x['locale'])
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_ten_native_bodies_pay_original_one_mana_and_merchant_can_have_no_target(self):
        rows = {x['record']['id']: x['record'] for x in load_batch()['dependencies']}
        for cid in LEAVES:
            with self.subTest(card=cid):
                g = self.game((cid,)); eid = self.play(g, cid)
                self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].health,
                    g.state.players[1].mana), (rows[cid]['attack'], rows[cid]['health'], 9))
                self.assertEqual(Keyword.DIVINE_SHIELD in g.state.entities[eid].keywords, cid == CLOCKER)

    def test_three_merchants_damage_then_grant_on_same_surviving_minion_without_spell_scaling(self):
        for cid, keyword in ((GUARDIAN, Keyword.DIVINE_SHIELD), (ROCKET, Keyword.RUSH), (ETHEREAL, None)):
            with self.subTest(card=cid):
                g = self.game((cid,), board=(YETI, 'CORE_EX1_012'))
                target = self.entity(g, YETI, zone='board').id; self.play(g, cid, target)
                self.assertEqual(g.state.entities[target].damage, 1)
                if keyword is None: self.assertEqual(self.bonus(g), 2)
                else: self.assertIn(keyword, g.state.entities[target].keywords)

    def test_lethal_damage_skips_all_three_grants(self):
        for cid in (GUARDIAN, ROCKET, ETHEREAL):
            with self.subTest(card=cid):
                h = self.game((cid,), board=(POGO,)); target = self.entity(h, POGO, zone='board').id
                self.play(h, cid, target); self.assertEqual(h.state.entities[target].zone, Zone.GRAVEYARD)
                self.assertFalse(any(a.kind in ('spell_damage', 'keyword') and a.origin != 'printed'
                    for a in h.state.entities[target].abilities))

    def test_shield_prevents_hit_but_the_following_guardian_grant_restores_it(self):
        g = self.game((P+'shield', GUARDIAN), board=(YETI,)); target = self.entity(g, YETI, zone='board').id
        self.play(g, P+'shield', target); self.play(g, GUARDIAN, target)
        self.assertEqual(g.state.entities[target].damage, 0)
        self.assertIn(Keyword.DIVINE_SHIELD, g.state.entities[target].keywords)

    def test_spell_damage_is_granted_to_recipient_controller_and_silence_removes_it(self):
        g = self.game((ETHEREAL, SILENCE), enemy_board=(YETI,))
        target = self.entity(g, YETI, 2, 'board').id; self.play(g, ETHEREAL, target)
        self.assertEqual((self.bonus(g), self.bonus(g, 2)), (0, 1))
        self.play(g, SILENCE, target); self.assertEqual(self.bonus(g, 2), 0)

    def test_granted_spell_damage_changes_a_real_subsequent_spell(self):
        g = self.game((ETHEREAL, BOLT), board=(YETI,)); self.play(g, ETHEREAL, self.entity(g, YETI, zone='board').id)
        self.play(g, BOLT, g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].damage, 2)

    def test_damage_wait_restores_and_keeps_original_board_residence_through_control_or_transform(self):
        for choice in ('continue', 'steal', 'transform'):
            with self.subTest(choice=choice):
                g = self.game((ETHEREAL,), board=(YETI,), mode='wait')
                target = self.entity(g, YETI, zone='board').id; self.play(g, ETHEREAL, target)
                self.assertIsNotNone(g.state.pending_choice); self.assertEqual(self.bonus(g), 0)
                g = self.portable(g); self.choose(g, choice)
                self.assertEqual(self.bonus(g, 2 if choice == 'steal' else 1), 1)
                if choice == 'transform': self.assertEqual(g.state.entities[target].card_id, RAVEN)
                self.portable(g)

    def test_all_three_grants_skip_same_entity_after_return_and_recruit(self):
        for cid in (GUARDIAN, ROCKET, ETHEREAL):
            with self.subTest(card=cid):
                g = self.game((cid,), board=(YETI,), mode='wait')
                target = self.entity(g, YETI, zone='board').id; old = g.state.entities[target].board_presence_id
                self.play(g, cid, target); g = self.portable(g); self.choose(g, 'reset')
                current = g.state.entities[target]
                self.assertNotEqual(current.board_presence_id, old)
                self.assertEqual((current.card_id, current.zone), (YETI, Zone.BOARD))
                self.assertNotIn(Keyword.DIVINE_SHIELD, current.keywords); self.assertNotIn(Keyword.RUSH, current.keywords)
                self.assertEqual(self.bonus(g), 0); self.portable(g)

    def test_destroyed_original_recipient_is_not_revived_by_spell_damage_grant(self):
        g = self.game((ETHEREAL,), board=(YETI,), mode='wait'); target = self.entity(g, YETI, zone='board').id
        self.play(g, ETHEREAL, target); self.choose(g, 'kill')
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD); self.assertEqual(self.bonus(g), 0)

    def test_captured_spell_damage_codec_rejects_future_presence_unknown_source_and_invalid_amount(self):
        g = self.game(board=(YETI,)); target = self.entity(g, YETI, zone='board').id
        ref = BoardPresenceReference.capture(g.state, target)
        effect = GrantCapturedSpellDamage(ref, 1, target)
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(effect)), effect)
        for value in (0, -1, True):
            with self.subTest(amount=value), self.assertRaises(ValueError): GrantCapturedSpellDamage(ref, value, target)
        for bad in (replace(effect, source_id=999999), replace(effect,
                beneficiary=replace(ref, presence_id=g.state.next_order))):
            with self.assertRaises(ValueError): codec.encode(bad)

    def test_secret_structural_condition_is_printed_and_distinct_from_battlecry(self):
        r = fixture(); self.assertTrue(matches_ability(SECRET, r.card(COUNTER)))
        self.assertFalse(matches_ability(SECRET, r.card(ZERO)))
        with self.assertRaises(ValueError): CardAbilityCondition('secret', basis='current')

    def test_lackey_changes_only_next_secret_to_one_and_zero_spells_do_not_consume(self):
        g = self.game((LACKEY, COUNTER, COUNTER, ZERO, POGO)); self.play(g, LACKEY)
        self.assertEqual(quote_unselected_cost(g.state, g.registry, self.entity(g, COUNTER)).amount, 1)
        self.play(g, ZERO); self.play(g, POGO); self.assertEqual(len(g.state.players[1].cost_modifiers), 1)
        self.play(g, COUNTER); self.assertEqual(g.state.players[1].mana, 7)
        self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertEqual(quote_unselected_cost(g.state, g.registry, self.entity(g, COUNTER)).amount, 3)
        self.portable(g)

    def test_unused_lackey_discount_expires_at_end_of_that_turn(self):
        g = self.game((LACKEY, COUNTER)); self.play(g, LACKEY); g.apply(EndTurn(1))
        self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertEqual(quote_unselected_cost(g.state, g.registry, self.entity(g, COUNTER)).amount, 3)

    def test_lackey_source_death_does_not_remove_its_effect_early(self):
        g = self.game((LACKEY, COUNTER, KILL)); source = self.play(g, LACKEY); self.play(g, KILL, source)
        self.assertEqual(quote_unselected_cost(g.state, g.registry, self.entity(g, COUNTER)).amount, 1)

    def test_ashtongue_echoes_exact_damage_to_original_controller_even_on_enemy_lethal_hit(self):
        g = self.game(board=(ASHTONGUE,), enemy_hand=(LETHAL,), active=2)
        target = self.entity(g, ASHTONGUE, zone='board').id; self.play(g, LETHAL, target, player=2)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].damage, 6)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].damage, 0)

    def test_ashtongue_zero_damage_and_silence_do_not_echo(self):
        g = self.game((P+'shield', HURT, SILENCE, HURT), board=(ASHTONGUE,))
        target = self.entity(g, ASHTONGUE, zone='board').id
        self.play(g, P+'shield', target); self.play(g, HURT, target)
        self.play(g, SILENCE, target); self.play(g, HURT, target)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].damage, 0)

    def test_trapper_checks_original_death_attack_and_draws_physical_card(self):
        for buffed in (False, True):
            with self.subTest(buffed=buffed):
                g = self.game((GROW, KILL) if buffed else (KILL,), board=(TRAPPER,), deck=(RAVEN,))
                target = self.entity(g, TRAPPER, zone='board').id; physical = g.state.players[1].deck[0]
                if buffed: self.play(g, GROW, target)
                self.play(g, KILL, target)
                self.assertEqual(physical in g.state.players[1].hand, buffed)

    def test_trapper_live_activation_uses_current_attack_and_empty_deck_uses_normal_fatigue(self):
        g = self.game((GROW, DR), board=(TRAPPER,)); target = self.entity(g, TRAPPER, zone='board').id
        self.play(g, GROW, target); self.play(g, DR, target)
        self.assertEqual(g.state.entities[target].zone, Zone.BOARD)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].damage, 1)

    def test_pogo_replaying_same_entity_counts_previous_plays_but_not_current_play(self):
        g = self.game((POGO, BOUNCE, BOUNCE)); source = self.play(g, POGO)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (1, 1))
        for expected in (3, 5):
            self.play(g, BOUNCE, source); self.assertEqual(self.play(g, POGO), source)
            self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (expected, expected))
        self.portable(g)

    def test_pogo_retrigger_excludes_its_original_native_play_not_every_played_pogo(self):
        g = self.game((POGO, POGO, BC, BC)); first = self.play(g, POGO)
        self.play(g, BC, first); self.assertEqual(g.state.entities[first].attack, 1)
        second = self.play(g, POGO); self.assertEqual(g.state.entities[second].attack, 3)
        self.play(g, BC, first); self.assertEqual(g.state.entities[first].attack, 3)

    def test_pogo_return_then_recruit_is_a_new_native_attachment_and_counts_all_prior_plays(self):
        g = self.game((POGO, BOUNCE, RECRUIT, BC)); first = self.play(g, POGO)
        self.play(g, BOUNCE, first); self.play(g, RECRUIT)
        self.assertEqual(g.state.entities[first].attack, 1)
        self.play(g, BC, first); self.assertEqual(g.state.entities[first].attack, 3)
        self.portable(g)

    def test_pogo_does_not_count_opponents_played_pogos(self):
        g = self.game((POGO,), enemy_hand=(POGO,), active=2)
        self.play(g, POGO, player=2); g.apply(EndTurn(2)); source = self.play(g, POGO)
        self.assertEqual(g.state.entities[source].attack, 1)

    def test_clocker_has_shield_and_randomly_buffs_one_current_hand_mech(self):
        g = self.game((CLOCKER, YETI, P+'hand_mech')); self.play(g, P+'hand_mech')
        source = self.play(g, CLOCKER)
        self.assertIn(Keyword.DIVINE_SHIELD, g.state.entities[source].keywords)
        self.assertEqual((self.entity(g, YETI).attack, self.entity(g, YETI).health), (5, 6))

    def test_clocker_empty_hand_domain_preserves_rng_and_unknown_current_tribe_rolls_back(self):
        g = self.game((CLOCKER,)); rng = g._rng.getstate(); self.play(g, CLOCKER)
        self.assertEqual(g._rng.getstate(), rng)
        h = self.game((CLOCKER, UNKNOWN)); before = h.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Unknown current tribe'): self.play(h, CLOCKER)
        self.assertEqual(h.snapshot(), before)

    def test_slitherspear_buffs_last_through_opponent_turn_and_expire_at_own_start(self):
        g = self.game((ZERO, ZERO), board=(SLITHERSPEAR,), deck=(RAVEN,), enemy_deck=(RAVEN,))
        source = self.entity(g, SLITHERSPEAR, zone='board').id
        self.play(g, ZERO); self.play(g, ZERO); self.assertEqual(g.state.entities[source].attack, 3)
        g.apply(EndTurn(1)); self.assertEqual(g.state.entities[source].attack, 3)
        g = self.portable(g); g.apply(EndTurn(2)); self.assertEqual(g.state.entities[source].attack, 1)

    def test_slitherspear_expiry_keeps_original_players_clock_after_transfer(self):
        g = self.game((ZERO, TAKE), board=(SLITHERSPEAR,), deck=(RAVEN,), enemy_deck=(RAVEN,))
        source = self.entity(g, SLITHERSPEAR, zone='board').id
        self.play(g, ZERO); self.play(g, TAKE, source); g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[source].attack, 2)
        g.apply(EndTurn(2)); self.assertEqual(g.state.entities[source].attack, 1)

    def test_countered_spell_and_hero_power_do_not_grant_slitherspear_attack(self):
        g = self.game((ZERO,), board=(SLITHERSPEAR,), enemy_hand=(COUNTER,), active=2)
        self.play(g, COUNTER, player=2); g.apply(EndTurn(2)); self.play(g, ZERO)
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id, g.state.players[2].hero_id))
        self.assertEqual(self.entity(g, SLITHERSPEAR, zone='board').attack, 1)

    def test_jouster_rewards_only_original_win_and_preserves_deck_entities_and_order(self):
        for own, enemy, won in (((YETI,), (RAVEN,), True), ((RAVEN,), (RAVEN,), False),
                ((RAVEN,), (YETI,), False), ((), (YETI,), False), ((YETI,), (), True)):
            with self.subTest(own=own, enemy=enemy):
                g = self.game((JOUSTER,), deck=own, enemy_deck=enemy)
                decks = [list(g.state.players[p].deck) for p in (1, 2)]
                source = self.play(g, JOUSTER)
                self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health),
                    (2, 3) if won else (1, 2))
                self.assertEqual([g.state.players[p].deck for p in (1, 2)], decks)

    def test_joust_wait_uses_original_costs_after_reveal_and_does_not_requery(self):
        g = self.game((JOUSTER,), deck=(YETI,), enemy_deck=(RAVEN,), mode='wait')
        source = self.play(g, JOUSTER); rng = g._rng.getstate()
        g = self.portable(g); self.choose(g, 'cheapen')
        self.assertEqual(g.state.entities[source].attack, 2)
        self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_joust_reward_does_not_buff_original_source_after_it_returns_to_hand(self):
        g = self.game((JOUSTER,), deck=(YETI,), enemy_deck=(RAVEN,), mode='wait')
        source = self.play(g, JOUSTER); self.choose(g, 'source_bounce')
        self.assertEqual((g.state.entities[source].zone, g.state.entities[source].attack), (Zone.HAND, 1))

    def test_clocker_hand_reward_wait_restores_without_second_buff(self):
        g = self.game((CLOCKER, YETI, P+'hand_mech'), mode='wait'); self.play(g, P+'hand_mech')
        self.play(g, CLOCKER); g = self.portable(g); self.choose(g)
        self.assertEqual((self.entity(g, YETI).attack, self.entity(g, YETI).health), (5, 6))

    def test_late_grant_random_hand_and_joust_failures_roll_back_entire_action(self):
        for cid in (GUARDIAN, ROCKET, ETHEREAL, CLOCKER, JOUSTER):
            with self.subTest(card=cid):
                hand = (CLOCKER, YETI, P+'hand_mech') if cid == CLOCKER else (cid,)
                g = self.game(hand, board=(YETI,) if cid in (GUARDIAN, ROCKET, ETHEREAL) else (),
                    deck=(YETI,), enemy_deck=(RAVEN,), mode='fail')
                if cid == CLOCKER: self.play(g, P+'hand_mech')
                target = self.entity(g, YETI, zone='board').id if cid in (GUARDIAN, ROCKET, ETHEREAL) else None
                before = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'K457 deliberate'): self.play(g, cid, target)
                self.assertEqual(g.snapshot(), before)

    def test_real_flashback_summons_grant_bodies_without_battlecry_or_joust(self):
        g = self.game((FLASHBACK, RAVEN)); self.play(g, RAVEN); self.play(g, FLASHBACK)
        self.assertEqual(len(g.state.players[1].board), 3)
        self.assertFalse(g.state.battlecry_history); self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertFalse(any(e.kind == 'joust_resolved' for e in g.events))
        self.portable(g)

    def test_production_past_domain_is_not_bound_from_the_ten_leaves(self):
        self.assertNotIn('constructed.past.cards', build_registry().pools)


if __name__ == '__main__':
    unittest.main()
