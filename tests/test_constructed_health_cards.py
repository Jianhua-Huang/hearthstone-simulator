"""Real health-card batches exercise public effects, domains and suspended casts."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.health_cards import load_batch, HealthStep
from hs_sim.engine import (
    CardDefinition, CardType, Game, Keyword, PlayCard, PlayerSetup, Scenario,
    SelectChoice, TriggerSpec,
)
from hs_sim.engine.effects import (
    Buff, ChoiceOption, CopyMinion, Damage, DamageBatch, Destroy,
    ChangeControl, GainArmor, RequestChoice, Silence, Summon,
)
from hs_sim.engine.errors import IllegalAction
from hs_sim.engine.model import DamageKind, HealthFlow, HealthOp, HealthRule, HealingKind, Zone
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError


def registry(*, waiting=False, buff_entry=False):
    r = build_registry()
    r.register_behavior('k02.test.wound', lambda c: (DamageBatch(tuple(
        Damage(p.hero_id, 10, c.source_id) for p in c.state.players.values())),))
    r.register_card(CardDefinition('k02.test.wound', 'Test wounds', CardType.SPELL,
        on_play='k02.test.wound'))
    r.register_behavior('k02.test.armor', lambda c: (GainArmor(c.player_id, 7),))
    r.register_card(CardDefinition('k02.test.armor', 'Test armor', CardType.SPELL,
        on_play='k02.test.armor'))
    for name, body in (
        ('kill', lambda c: (Destroy(c.target_id),)),
        ('hit', lambda c: (Damage(c.target_id, 1, c.source_id),)),
        ('silence', lambda c: (Silence(c.target_id),)),
        ('copy', lambda c: (CopyMinion(c.target_id, c.player_id),)),
        ('summon', lambda c: (Summon(c.player_id, 'CORE_EX1_319'),)),
        ('transfer', lambda c: (ChangeControl(c.target_id, 2),)),
    ):
        r.register_behavior('k02.test.'+name, body)
        r.register_card(CardDefinition('k02.test.'+name, name, CardType.SPELL,
            on_play='k02.test.'+name, requires_target=name not in ('summon',)))
    r.register_card(CardDefinition('k02.test.dormant', 'Dormant target', CardType.MINION,
        health=7, dormant_turns=2))
    r.register_card(CardDefinition('k02.test.heal_double', 'Spell healing multiplier', CardType.MINION,
        health=5, health_rules=(HealthRule(HealthFlow.HEALING, HealthOp.SCALE, 2,
            source_relation='friendly', healing_kinds=(HealingKind.SPELL,)),)))
    if waiting:
        def wait(c):
            if c.state.entities[c.event.source_id].card_id != 'CORE_CS2_094':
                return ()
            return (RequestChoice(c.player_id, (
                ChoiceOption('continue', 'Continue', (GainArmor(c.player_id, 1),)),), c.source_id),)
        r.register_behavior('k02.test.wait', wait)
        r.register_card(CardDefinition('k02.test.wait', 'Wait observer', CardType.MINION,
            health=5, triggers=(TriggerSpec('damage_dealt', 'k02.test.wait'),)))
    if buff_entry:
        def entry(c):
            entity = c.state.entities[c.event.target_id]
            if entity.card_id in ('TIME_427', 'TIME_431'):
                return (Buff(entity.id, health=2, source_id=c.source_id),)
            return ()
        r.register_behavior('k02.test.entry', entry)
        r.register_card(CardDefinition('k02.test.entry', 'Entry health observer', CardType.MINION,
            health=5, triggers=(TriggerSpec('minion_summoned', 'k02.test.entry'),)))
    return r


class ConstructedHealthCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = registry()
        cls.batch = load_batch()

    def game(self, hand=(), board=(), enemy=(), *, deck=(), armor=0, active=1,
             custom_registry=None, seed=17):
        return Game.from_scenario(Scenario((
            PlayerSetup('test.hero', hand=hand, board=board, deck=deck,
                        mana=20, max_mana=20, mana_cap=20, armor=armor),
            PlayerSetup('test.hero', board=enemy),
        ), active_player=active, seed=seed), custom_registry or self.registry)

    def play(self, game, cid, target=None):
        eid = next(e for e in game.state.players[1].hand if game.state.entities[e].card_id == cid)
        game.apply(PlayCard(1, eid, target_id=target))
        return eid

    def test_all_48_roots_have_complete_paid_cast_or_minion_death_paths(self):
        self.assertEqual(len(self.batch['cards']), 48)
        for row in self.batch['cards']:
            raw, recipe = row['record'], row['recipe']
            cid = raw['id']
            with self.subTest(cid=cid):
                game = self.game((cid, 'k02.test.wound', 'k02.test.armor', 'k02.test.kill'),
                    board=('TLC_248',), enemy=('TLC_248',), deck=('CORE_CS2_182',))
                self.play(game, 'k02.test.wound')
                self.play(game, 'k02.test.armor')
                target = None
                if recipe['target'] in ('minion', 'enemy_minion'):
                    target = game.state.players[2].board[0]
                elif recipe['target'] == 'character':
                    target = game.state.players[2].hero_id
                elif recipe['target'] == 'friendly_character':
                    target = game.state.players[1].hero_id
                before_events = len(game.events)
                eid = self.play(game, cid, target)
                self.assertEqual(game.state.players[1].mana, 20-(raw['cost'] or 0))
                if raw['type'] == 'MINION':
                    self.assertIn(eid, game.state.players[1].board)
                    self.assertEqual(game.state.entities[eid].attack, raw['attack'])
                else:
                    self.assertEqual(game.state.entities[eid].zone, Zone.GRAVEYARD)
                if 'deathrattle' in recipe['bodies']:
                    self.play(game, 'k02.test.kill', eid)
                    self.assertEqual(game.state.entities[eid].zone, Zone.GRAVEYARD)
                effects = [e for e in game.events[before_events:] if e.kind in ('damage_dealt', 'healed')]
                self.assertTrue(effects, cid)
                self.assertEqual(sum(e.kind == 'card_played' and e.source_id == eid for e in game.events), 1)

    def test_direct_spell_amounts_and_bonus_match_real_card_values(self):
        for cid, amount in (('CORE_CS2_029', 6), ('CORE_DS1_185', 2), ('CORE_EX1_279', 10), ('Core_CS2_008', 1)):
            with self.subTest(cid=cid):
                game = self.game((cid,), board=('EX1_012',))
                target = game.state.players[2].hero_id
                self.play(game, cid, target)
                self.assertEqual(game.state.entities[target].health, 30-amount-1)

    def test_battlecry_damage_does_not_use_spell_damage(self):
        for cid, amount in (('CORE_CS2_042', 4), ('CORE_CS2_189', 1), ('CORE_UNG_084', 3)):
            with self.subTest(cid=cid):
                game = self.game((cid,), board=('EX1_012',))
                target = game.state.players[2].hero_id
                self.play(game, cid, target)
                self.assertEqual(game.state.entities[target].health, 30-amount)

    def test_printed_target_domain_rejects_hero_and_enemy_healing_before_payment(self):
        for cid, target_seat in (('CORE_CS1_130', 2), ('CORE_CFM_604', 2)):
            with self.subTest(cid=cid):
                game = self.game((cid,))
                before = game.snapshot()
                with self.assertRaises(IllegalAction):
                    self.play(game, cid, game.state.players[target_seat].hero_id)
                self.assertEqual(game.snapshot(), before)

    def test_healing_amounts_and_draw_respect_actual_damage_and_caps(self):
        for cid, amount, draw in (('CORE_AT_055',5,0), ('CORE_TRL_307',4,1), ('CORE_CFM_604',12,1)):
            with self.subTest(cid=cid):
                game = self.game((cid,'k02.test.wound'), deck=('CORE_CS2_182',))
                self.play(game,'k02.test.wound')
                hero = game.state.players[1].hero_id
                self.play(game,cid,hero)
                self.assertEqual(game.state.entities[hero].health,min(30,20+amount))
                self.assertEqual(len(game.state.players[1].hand),draw)

    def test_spell_healing_kind_uses_multiplier_and_battlecry_healing_does_not(self):
        for cid,amount in (('CORE_AT_055',10),('CORE_EX1_011',2)):
            with self.subTest(cid=cid):
                game=self.game((cid,'k02.test.wound','k02.test.wound'),
                    board=('k02.test.heal_double','EX1_012'))
                self.play(game,'k02.test.wound')
                self.play(game,'k02.test.wound')
                hero=game.state.players[1].hero_id
                self.play(game,cid,hero)
                self.assertEqual(game.state.entities[hero].health,10+amount)

    def test_all_minion_damage_ignores_dormant_and_has_one_death_batch(self):
        game = self.game(('CORE_EX1_400',), board=('CORE_EX1_008',),
            enemy=('CORE_ICC_023','CORE_LOEA10_3','k02.test.dormant'))
        shield = game.state.players[1].board[0]
        first, second, dormant = game.state.players[2].board
        self.play(game,'CORE_EX1_400')
        self.assertEqual(game.state.entities[shield].health,1)
        self.assertNotIn(Keyword.DIVINE_SHIELD,game.state.entities[shield].keywords)
        self.assertEqual(game.state.entities[dormant].health,7)
        records = [d for d in game.state.death_history if d.entity_id in (first,second)]
        self.assertEqual(len(records),2)
        self.assertEqual(len({d.batch for d in records}),1)

    def test_all_characters_and_all_enemies_have_distinct_scopes(self):
        for cid, own_health, enemy_health, friend_health, foe_health in (
            ('CORE_CS2_062',27,27,2,25),('CORE_CS2_093',30,28,5,26)):
            with self.subTest(cid=cid):
                game = self.game((cid,),board=('CORE_CS2_182',),enemy=('TLC_248',))
                self.play(game,cid)
                p1,p2=game.state.players.values()
                self.assertEqual((game.state.entities[p1.hero_id].health,game.state.entities[p2.hero_id].health),
                                 (own_health,enemy_health))
                self.assertEqual((game.state.entities[p1.board[0]].health,game.state.entities[p2.board[0]].health),
                                 (friend_health,foe_health))

    def test_latest_self_damage_lifesteal_and_repeat_share_one_payment(self):
        game = self.game(('CATA_304','k02.test.wound'))
        self.play(game,'k02.test.wound')
        eid=self.play(game,'CATA_304')
        self.assertEqual(game.state.entities[eid].health,4)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health,24)
        game=self.game(('CORE_EX1_319',),board=('LOE_077',))
        self.play(game,'CORE_EX1_319')
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health,24)
        self.assertEqual(game.state.players[1].mana,19)

    def test_current_source_health_and_armor_are_read_at_battlecry(self):
        for cid, expected in (('TIME_427',23),('TIME_431',26)):
            with self.subTest(cid=cid):
                r=registry(buff_entry=True)
                game=self.game((cid,'k02.test.wound'),board=('k02.test.entry',),enemy=('TLC_248',),custom_registry=r)
                self.play(game,'k02.test.wound')
                target=game.state.players[2].board[0] if cid=='TIME_427' else game.state.players[1].hero_id
                self.play(game,cid,target)
                self.assertEqual(game.state.entities[target].health,expected)
        game=self.game(('CORE_ONY_024',),enemy=('TLC_248',),armor=7)
        target=game.state.players[2].board[0]
        self.play(game,'CORE_ONY_024',target)
        self.assertEqual(game.state.entities[target].health,21)

    def test_two_real_eradicator_bodies_and_silenced_deathrattle(self):
        game=self.game(('EDR_459','k02.test.kill'),board=('CORE_CS2_182',),enemy=('TLC_248',))
        friend=game.state.players[1].board[0]
        enemy=game.state.players[2].board[0]
        eid=self.play(game,'EDR_459')
        self.assertEqual(game.state.entities[friend].health,2)
        self.assertEqual(game.state.entities[eid].health,6)
        self.play(game,'k02.test.kill',eid)
        self.assertEqual(game.state.entities[enemy].health,25)
        game=self.game(('k02.test.silence','k02.test.kill'),board=('FIR_778',),enemy=('TLC_248',))
        eid=game.state.players[1].board[0]
        self.play(game,'k02.test.silence',eid)
        self.play(game,'k02.test.kill',eid)
        self.assertEqual(game.state.entities[game.state.players[2].board[0]].health,28)

    def test_new_deathrattle_survives_current_copy_with_own_physical_source(self):
        game=self.game(('k02.test.copy','k02.test.kill'),board=('FIR_778',),enemy=('TLC_248',))
        original=game.state.players[1].board[0]
        self.play(game,'k02.test.copy',original)
        copied=game.state.players[1].board[1]
        self.assertNotEqual(copied,original)
        self.play(game,'k02.test.kill',copied)
        self.assertIn(original,game.state.players[1].board)
        self.assertEqual(game.state.entities[game.state.players[2].board[0]].health,19)

    def test_summon_does_not_execute_printed_battlecry(self):
        game=self.game(('k02.test.summon',))
        self.play(game,'k02.test.summon')
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health,30)

    def test_real_deathrattle_opponent_turn_condition_reads_current_turn(self):
        for active, expected in ((1,29),(2,26)):
            with self.subTest(active=active):
                game=self.game(board=('FIR_958',),enemy=('TLC_248',),active=active)
                if active==1:
                    game=self.game(('k02.test.kill',),board=('FIR_958',),enemy=('TLC_248',))
                    self.play(game,'k02.test.kill',game.state.players[1].board[0])
                else:
                    from hs_sim.engine.actions import Attack
                    game.apply(Attack(2,game.state.players[2].board[0],game.state.players[1].board[0]))
                self.assertEqual(game.state.entities[game.state.players[2].hero_id].health,expected)

    def test_split_damage_is_two_real_hits_and_replays_rng(self):
        game=self.game(('k02.test.kill',),board=('TLC_249',),enemy=('TLC_248',))
        self.play(game,'k02.test.kill',game.state.players[1].board[0])
        events=[e for e in game.events if e.kind=='damage_dealt']
        self.assertEqual(sum(e.amount for e in events),2)
        self.assertEqual(len(events),2)
        self.assertEqual(replay(build_replay(game),registry()).snapshot(),game.snapshot())

    def test_transferred_deathrattle_uses_controller_for_enemy_and_turn(self):
        game=self.game(('k02.test.transfer','k02.test.kill'),board=('FIR_958',))
        eid=game.state.players[1].board[0]
        self.play(game,'k02.test.transfer',eid)
        self.assertEqual((game.state.entities[eid].owner,game.state.entities[eid].controller),(1,2))
        self.play(game,'k02.test.kill',eid)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health,26)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health,30)

    def test_waiting_damage_then_draw_restores_and_is_private(self):
        r=registry(waiting=True)
        game=self.game(('CORE_CS2_094',),board=('k02.test.wait',),deck=('CORE_CS2_182',),custom_registry=r)
        eid=self.play(game,'CORE_CS2_094',game.state.players[2].hero_id)
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(game.state.players[1].mana,17)
        self.assertEqual(game.state.players[1].hand,[])
        self.assertEqual(game.observe(2)['pending_choice'],{'player_id':1})
        restored=Game.from_snapshot(json.loads(json.dumps(game.snapshot())),registry(waiting=True))
        self.assertEqual(restored.snapshot(),game.snapshot())
        self.assertEqual(game.clone().snapshot(),game.snapshot())
        self.assertEqual(replay(build_replay(game),registry(waiting=True)).snapshot(),game.snapshot())
        game.apply(SelectChoice(1,game.state.pending_choice.id,('continue',)))
        restored.apply(SelectChoice(1,restored.state.pending_choice.id,('continue',)))
        self.assertEqual(restored.snapshot(),game.snapshot())
        self.assertEqual(len(game.state.players[1].hand),1)
        self.assertEqual(game.state.players[1].mana,17)
        self.assertEqual(sum(e.kind=='card_played' and e.source_id==eid for e in game.events),1)

    def test_opaque_card_and_tampered_source_do_not_become_partial_effects(self):
        changed=load_batch()
        changed['cards'][0]['record']['text_en']+=' Additional unimplemented effect.'
        with TemporaryDirectory() as folder:
            p=Path(folder)/'changed.json';p.write_text(json.dumps(changed),encoding='utf-8')
            with patch('hs_sim.cards.health_cards.BATCH_PATH',p), self.assertRaises(TargetValidationError):
                load_batch()
        from hs_sim.engine.registry import UnsupportedDefinitionError
        with self.assertRaises(UnsupportedDefinitionError):
            self.registry.card('CATA_552')
        with self.assertRaises(ValueError):
            HealthStep('invented_effect','self',1)
