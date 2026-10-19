"""Real end-turn attacks, one combat budget, original windows and atomic recovery."""
from copy import deepcopy
from dataclasses import asdict
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.briarspawn_drake_card import CARD, load_batch, register_briarspawn_drake_card
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, EndTurnSpec, Game, Keyword,
    PlayCard, PlayerSetup, Registry, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, CombatExchange,
    Damage, ForceAttack, GrantKeyword, InvokeBehavior, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.forced_attack_sequences import AttackRandomEnemyMinion
from hs_sim.engine.interrupts import RedirectAttack
from hs_sim.engine.model import DamageKind, HealthFlow, HealthLayer, HealthOp, HealthRule
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import CombatDamage
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P = 'briar.test.'


def registry(mode=None):
    r = Registry('briarspawn-combat-tests-v1')
    r.register_card(CardDefinition(P+'hero', 'Hero', CardType.HERO, health=100))
    register_briarspawn_drake_card(r)
    for name, attack, health, keywords in (
            ('small', 2, 3, ()), ('exact', 2, 12, ()), ('large', 2, 15, ()),
            ('killer', 12, 3, ()), ('shield', 2, 3, (Keyword.DIVINE_SHIELD,)),
            ('immune', 2, 3, (Keyword.IMMUNE,)), ('stealth', 2, 3, (Keyword.STEALTH,))):
        r.register_card(CardDefinition(P+name, name, CardType.MINION, attack=attack,
            health=health, keywords=keywords))
    r.register_card(CardDefinition(P+'dormant', 'Dormant', CardType.MINION,
        attack=50, health=50, dormant_turns=2))
    rules = {
        'source_double': HealthRule(HealthFlow.DAMAGE, HealthOp.SCALE, 2,
            source_relation='friendly', damage_kinds=(DamageKind.COMBAT,)),
        'target_double': HealthRule(HealthFlow.DAMAGE, HealthOp.SCALE, 2,
            layer=HealthLayer.TARGET, target_relation='enemy', target_kinds=(CardType.MINION,),
            damage_kinds=(DamageKind.COMBAT,)),
        'target_prevent': HealthRule(HealthFlow.DAMAGE, HealthOp.PREVENT,
            layer=HealthLayer.TARGET, target_relation='enemy', target_kinds=(CardType.MINION,),
            damage_kinds=(DamageKind.COMBAT,)),
        'floor': HealthRule(HealthFlow.DAMAGE, HealthOp.FLOOR, 1,
            layer=HealthLayer.TARGET, target_relation='enemy', target_kinds=(CardType.MINION,),
            damage_kinds=(DamageKind.COMBAT,)),
        'redirect': HealthRule(HealthFlow.DAMAGE, HealthOp.REDIRECT,
            layer=HealthLayer.TARGET, target_relation='enemy', target_kinds=(CardType.HERO,),
            damage_kinds=(DamageKind.COMBAT,), redirect_to='self'),
    }
    for name, rule in rules.items():
        r.register_card(CardDefinition(P+name, name, CardType.MINION, health=30, health_rules=(rule,)))
    def source(c):
        return next(i for i in c.state.players[1].board if c.state.entities[i].card_id == CARD)
    def reenter(c):
        e = c.state.entities[c.target_id]
        return (SummonStoredCard(CardReference.capture(e), e.controller),)
    scripts = {
        'noop': lambda c: (),
        'silence': lambda c: (Silence(source(c)),),
        'control': lambda c: (ChangeControl(source(c), 2),),
        'zero': lambda c: (Buff(source(c), -12, 0, source_id=c.source_id),),
        'buff': lambda c: (Buff(source(c), 2, 3, source_id=c.source_id),),
        'drain': lambda c: (Damage(c.state.players[1].hero_id, 50, c.source_id),
            GrantKeyword(source(c), Keyword.LIFESTEAL, c.source_id)),
        'poison': lambda c: (GrantKeyword(source(c), Keyword.POISONOUS, c.source_id),),
        'immune_attack': lambda c: (GrantKeyword(source(c), Keyword.IMMUNE_WHILE_ATTACKING, c.source_id),),
        'freeze': lambda c: freeze(source(c)),
        'fail': lambda c: (AddToHand(c.player_id, 'missing.briar'),),
        'reenter': reenter,
    }
    def freeze(eid):
        from hs_sim.engine.effects import Freeze
        return (Freeze(eid),)
    for name, body in scripts.items():
        r.register_behavior(P+name, body)
        if name != 'reenter':
            r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name))
    if mode:
        def wait(c):
            return (RequestChoice(1, (ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Fail',
                (InvokeBehavior(P+'fail', c.source_id, 1),))), c.source_id),)
        def watch(c):
            event = c.event
            if mode == 'late_failure':
                return (InvokeBehavior(P+'fail', c.source_id, 1),)
            if c.state.entities[event.source_id].card_id != CARD:
                return ()
            if mode == 'wait_damage':
                return wait(c) if c.state.entities[event.target_id].kind == CardType.HERO else ()
            if mode == 'wait_declare': return wait(c)
            if mode in ('bounce', 'source_reentry', 'target_reentry'):
                target = event.target_id if mode == 'target_reentry' else event.source_id
                result = (ReturnToHand(target),)
                return (*result, InvokeBehavior(P+'reenter', c.source_id, 1, target)) if mode != 'bounce' else result
            if mode == 'redirect_hero':
                return (RedirectAttack(c.state.action_windows[-1].id, c.state.players[2].hero_id),)
            if mode == 'grow_target': return (Buff(event.target_id, 0, 20, source_id=c.source_id),)
            return ()
        event = 'turn_ended' if mode == 'late_failure' else 'damage_dealt' if mode == 'wait_damage' else 'attack_declared'
        r.register_behavior(P+'watch', watch)
        r.register_card(CardDefinition(P+'watch', 'Observer', CardType.MINION, health=30,
            triggers=(TriggerSpec(event, P+'watch', EndTurnSpec() if event == 'turn_ended' else None),)))
    return r


class BriarspawnDrakeTests(unittest.TestCase):
    def game(self, enemy=('small',), *, board=(), hand=(CARD,), mode=None, active=1, armor=0):
        self.mode = mode
        board = (*board, *((P+'watch',) if mode else ()))
        return Game.from_scenario(Scenario((
            PlayerSetup(P+'hero', hand=hand, board=board, deck=(P+'noop',)*8,
                mana=30, max_mana=30, mana_cap=30),
            PlayerSetup(P+'hero', board=tuple(P+x for x in enemy), deck=(P+'noop',)*8,
                mana=30, max_mana=30, mana_cap=30, armor=armor)), seed=266, active_player=active), registry(mode))
    def play(self, g, cid=CARD):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid)); return eid
    def hero(self, g, p=2): return g.state.entities[g.state.players[p].hero_id]
    def rows(self, g):
        return [x.health_result for x in g.state.damage_history if x.health_result.source_card_id == CARD]
    def end(self, g): g.apply(EndTurn(g.state.active_player))
    def choose(self, g, key='ok'):
        q=g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); reader = registry(self.mode)
        other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for player in (1,2):
            public = json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for key in ('character_attack_history','attack_source_presence','target_presence_id',
                        'excess_to_hero','resolution_frame','rng_state','partition_source'):
                self.assertNotIn('"'+key+'"', public)
        return other
    def rehash(self, saved):
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        return saved

    def test_a00_complete_original_body_metadata_and_central_registration(self):
        d=load_batch();row,=d['cards'];raw=row['record'];card=build_registry().card(CARD)
        self.assertEqual(canonical_digest(raw),row['record_sha256'])
        self.assertEqual((card.cost,card.attack,card.health,card.keywords),(10,12,7,()))
        self.assertEqual(card.metadata,metadata_from_record(raw));self.assertEqual(card.metadata.tribes,('dragon',))
        self.assertEqual(card.triggers[0].end_turn,EndTurnSpec())
        self.assertEqual(len(d['official_observations']),2)
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_a01_paid_same_turn_end_attack_has_one_original_window_and_reciprocal_combat(self):
        g=self.game();source=self.play(g);self.assertEqual(g.state.players[1].mana,20);self.end(g)
        self.assertEqual(self.hero(g).health,91);self.assertEqual(g.state.entities[source].health,5)
        row,=g.state.character_attack_history
        self.assertTrue(row.declaration.forced and row.declaration.excess_to_hero)
        self.assertEqual(row.terminal.status,'completed');self.assertEqual(g.state.entities[source].attacks_this_turn,0)
        self.assertEqual([x.damage_dealt for x in self.rows(g)],[3,9]);self.portable(g)

    def test_a02_exact_and_larger_health_never_duplicate_damage_or_create_zero_excess(self):
        for target,remaining in (('exact',0),('large',3)):
            with self.subTest(target=target):
                g=self.game((target,));target_id=g.state.players[2].board[0];self.play(g);self.end(g)
                self.assertEqual(self.hero(g).health,100);self.assertEqual([x.damage_dealt for x in self.rows(g)],[12])
                self.assertEqual(g.state.entities[target_id].health,remaining)

    def test_a03_empty_or_only_dormant_enemy_pool_has_no_attack_or_random_draw(self):
        for enemy in ((),('dormant',)):
            with self.subTest(enemy=enemy):
                g=self.game(enemy);self.play(g);rng=g._rng.getstate();self.end(g)
                self.assertEqual(g.state.character_attack_history,[]);self.assertEqual(g._rng.getstate(),rng)

    def test_a04_shield_immunity_and_stealth_keep_original_health_based_hero_share(self):
        for target,dealt in (('shield',0),('immune',0),('stealth',3)):
            with self.subTest(target=target):
                g=self.game((target,));self.play(g);self.end(g)
                self.assertEqual([x.damage_dealt for x in self.rows(g)],[dealt,9])
                self.assertEqual(self.hero(g).health,91)

    def test_a05_zero_attack_does_not_generate_excess_or_consume_divine_shield(self):
        g=self.game(('shield',),hand=(CARD,P+'zero'));self.play(g);self.play(g,P+'zero');self.end(g)
        self.assertEqual(self.hero(g).health,100)
        self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[g.state.players[2].board[0]].keywords)
        self.assertEqual([x.damage_dealt for x in self.rows(g)],[0])

    def test_b00_source_rules_quote_once_and_target_rules_do_not_change_hero_remainder(self):
        for provider,expected in (('source_double',[3,21]),('target_double',[6,9]),('target_prevent',[0,9]),('floor',[2,9])):
            with self.subTest(provider=provider):
                g=self.game(board=(P+provider,));self.play(g);self.end(g)
                self.assertEqual([x.damage_dealt for x in self.rows(g)],expected)
                self.assertEqual(self.hero(g).health,100-expected[1])

    def test_b01_armor_and_redirect_use_existing_recipient_settlement(self):
        g=self.game(armor=5);self.play(g);self.end(g)
        self.assertEqual((self.hero(g).health,self.hero(g).armor),(96,0))
        g=self.game(board=(P+'redirect',));holder=g.state.players[1].board[0];self.play(g);self.end(g)
        self.assertEqual(self.hero(g).health,100);self.assertEqual(g.state.entities[holder].health,21)
        self.assertEqual(self.rows(g)[1].original_target_id,self.hero(g).id)

    def test_b02_lifesteal_and_lethal_retaliation_finish_in_the_same_health_batch(self):
        g=self.game(('killer',),hand=(CARD,P+'drain'));source=self.play(g);self.play(g,P+'drain');self.end(g)
        self.assertEqual(self.hero(g,1).health,62);self.assertEqual(self.hero(g).health,91)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        rows=self.rows(g);self.assertEqual(len({x.batch_id for x in rows}),1)
        self.assertEqual(g.state.character_attack_history[0].terminal.status,'completed');self.portable(g)

    def test_b03_poisonous_kill_of_a_large_target_does_not_create_extra_hero_damage(self):
        g=self.game(('large',),hand=(CARD,P+'poison'));self.play(g);self.play(g,P+'poison');self.end(g)
        self.assertEqual(self.hero(g).health,100);self.assertEqual(g.state.players[2].board,[])

    def test_b04_attack_scoped_immunity_covers_the_existing_retaliation(self):
        g=self.game(('killer',),hand=(CARD,P+'immune_attack'));source=self.play(g);self.play(g,P+'immune_attack');self.end(g)
        self.assertEqual(g.state.entities[source].health,7);self.assertEqual(self.hero(g).health,91)

    def test_c00_ordinary_manual_attack_has_full_normal_damage_and_no_excess(self):
        g=self.game(hand=(),board=(CARD,));source=g.state.players[1].board[0];target=g.state.players[2].board[0]
        g.apply(Attack(1,source,target));self.assertEqual(self.hero(g).health,100)
        self.assertFalse(g.state.character_attack_history[0].declaration.excess_to_hero)
        self.assertEqual([x.damage_dealt for x in self.rows(g)],[12])

    def test_c01_frozen_body_still_performs_its_owner_end_forced_attack(self):
        g=self.game(hand=(CARD,P+'freeze'));self.play(g);self.play(g,P+'freeze');self.end(g)
        self.assertEqual(self.hero(g).health,91)

    def test_c02_opponent_turn_and_silenced_source_have_no_false_end_body(self):
        g=self.game(board=(CARD,),hand=(),active=2);self.end(g)
        self.assertEqual(g.state.character_attack_history,[])
        g=self.game(hand=(CARD,P+'silence'));self.play(g);self.play(g,P+'silence');self.end(g)
        self.assertEqual(g.state.character_attack_history,[])

    def test_c03_control_change_uses_actual_controller_end_and_enemy_hero(self):
        g=self.game((),board=(P+'small',),hand=(CARD,P+'control'));self.play(g);self.play(g,P+'control');self.end(g)
        self.assertEqual(g.state.character_attack_history,[]);self.end(g)
        self.assertEqual(self.hero(g,1).health,91);self.assertEqual(g.state.character_attack_history[0].declaration.player_id,2)

    def test_d00_departure_or_reentry_of_either_combatant_cancels_original_attack(self):
        for mode in ('bounce','source_reentry','target_reentry'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);self.play(g);self.end(g)
                self.assertEqual(self.hero(g).health,100);self.assertEqual(self.rows(g),[])
                self.assertEqual(g.state.character_attack_history[0].terminal.status,'cancelled')

    def test_d01_current_target_health_is_quoted_at_actual_combat_delivery(self):
        g=self.game(mode='grow_target');self.play(g);self.end(g)
        self.assertEqual(self.hero(g).health,100);self.assertEqual([x.damage_dealt for x in self.rows(g)],[12])
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,11)

    def test_d02_redirect_to_hero_delivers_one_full_hit_without_a_duplicate_excess_packet(self):
        g=self.game(mode='redirect_hero');self.play(g);self.end(g)
        self.assertEqual(self.hero(g).health,88);self.assertEqual([x.damage_dealt for x in self.rows(g)],[12])
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,3);self.portable(g)

    def test_e00_declaration_wait_restores_policy_and_bad_choice_rolls_back(self):
        g=self.game(mode='wait_declare');self.play(g);self.end(g);saved=g.snapshot();other=self.portable(g)
        self.assertEqual(self.hero(g).health,100)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.hero(g).health,91)

    def test_e01_damage_reaction_wait_sees_all_damage_and_retaliation_already_committed(self):
        g=self.game(('killer',),mode='wait_damage');source=self.play(g);self.end(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.hero(g).health,91)
        self.assertLessEqual(g.state.entities[source].health,0);other=self.portable(g)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())

    def test_e02_late_failure_rolls_back_the_entire_end_turn_and_rng(self):
        g=self.game(mode='late_failure');self.play(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.end(g)
        self.assertEqual(g.snapshot(),saved)

    def test_e03_saved_window_and_original_event_cannot_change_excess_policy(self):
        g=self.game(mode='wait_declare');self.play(g);self.end(g);saved=g.snapshot()
        for change_history in (False,True):
            bad=deepcopy(saved);bad['state']['action_windows'][0]['excess_to_hero']=False
            if change_history:bad['state']['character_attack_history'][0]['declaration']['excess_to_hero']=False
            with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(bad),registry(self.mode))
        bad=deepcopy(saved);bad['schema_version']=439
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry(self.mode))

    def test_e04_strict_boolean_and_complete_original_window_are_required(self):
        g=self.game(hand=(),board=(CARD,));a=capture_board_presence(g.state,g.state.players[1].board[0]);d=capture_board_presence(g.state,g.state.players[2].board[0])
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        for invalid in (1,'true',None):
            with self.assertRaises(ValueError):ForceAttack(a,d,excess_to_hero=invalid)
            with self.assertRaises(ValueError):AttackRandomEnemyMinion(a,1,excess_to_hero=invalid)
        with self.assertRaises(ValueError):ForceAttack(a,d,combat_relation='friendly_minions',excess_to_hero=True)
        with self.assertRaises(ValueError):CombatDamage(a.entity_id,d.entity_id,excess_to_hero=True)
        with self.assertRaises(ValueError):CombatExchange(a.entity_id,d.entity_id,excess_to_hero=True)
        request=ForceAttack(a,d,excess_to_hero=True);wire=codec.encode(request)
        self.assertEqual(codec.decode(wire),request)
        for missing in (False,True):
            bad=deepcopy(wire)
            if missing:bad['fields'].pop('excess_to_hero')
            else:bad['fields']['excess_to_hero']=1
            with self.assertRaises(ValueError):codec.decode(bad)

    def test_f00_real_freezing_trap_cancels_before_any_combat_or_excess(self):
        r=build_registry();r.register_card(CardDefinition(P+'small','Small',CardType.MINION,attack=2,health=3))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',board=(CARD,),deck=('CORE_CS2_182',)*8,
            mana=30,max_mana=30,mana_cap=30),PlayerSetup('HERO_08',hand=('CORE_EX1_611',),board=(P+'small',),
            deck=('CORE_CS2_182',)*8,mana=30,max_mana=30,mana_cap=30)),active_player=2,seed=266),r)
        source=g.state.players[1].board[0];trap=g.state.players[2].hand[0]
        g.apply(PlayCard(2,trap));self.end(g);self.end(g)
        self.assertEqual(g.state.entities[source].zone,Zone.HAND);self.assertEqual(g.state.entities[source].cost,12)
        self.assertEqual(self.hero(g).health,30);self.assertEqual(self.rows(g),[])
        self.assertEqual(g.state.character_attack_history[0].terminal.status,'cancelled')


if __name__=='__main__': unittest.main()
