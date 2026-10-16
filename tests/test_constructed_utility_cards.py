"""Real current-series card consumers of buffs, removals and complete summons."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.utility_cards import UtilityStep,load_batch
from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,TriggerSpec,UseHandAction,UseLocation)
from hs_sim.engine.effects import (Buff,ChoiceOption,Damage,Destroy,DestroyBatch,
    GainArmor,RequestChoice,ReturnToHand,Silence,Summon)
from hs_sim.engine.errors import IllegalAction
from hs_sim.engine.model import CardClass,CardMetadata,Resource,Zone
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import TargetValidationError


def registry(*,waiting=False,return_after_damage=False):
    r=build_registry()
    for name,body in [('kill',lambda c:(Destroy(c.target_id),)),
        ('hit',lambda c:(Damage(c.target_id,1,c.source_id),)),
        ('silence',lambda c:(Silence(c.target_id),)),
        ('buff',lambda c:(Buff(c.target_id,attack=3,source_id=c.source_id),))]:
        r.register_behavior('k04.test.'+name,body)
        r.register_card(CardDefinition('k04.test.'+name,name,CardType.SPELL,
            on_play='k04.test.'+name,requires_target=True))
    r.register_card(CardDefinition('k04.test.big','Big',CardType.MINION,attack=8,health=9))
    r.register_card(CardDefinition('k04.test.dormant','Dormant',CardType.MINION,health=9,dormant_turns=2))
    r.register_behavior('k04.test.wound',lambda c:(Damage(c.state.players[1].hero_id,10,c.source_id),))
    r.register_card(CardDefinition('k04.test.wound','Wound',CardType.SPELL,on_play='k04.test.wound'))
    r.register_behavior('k04.test.break_weapon',lambda c:(Destroy(c.state.players[1].weapon_id),))
    r.register_card(CardDefinition('k04.test.break_weapon','Break weapon',CardType.SPELL,on_play='k04.test.break_weapon'))
    if waiting or return_after_damage:
        def watch(c):
            if c.state.entities[c.event.source_id].card_id not in ('DINO_406','EDR_468'):
                return ()
            effects=(ReturnToHand(c.event.target_id),) if return_after_damage else (Summon(c.player_id,'BOT_102t'),)
            return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue',effects),),c.source_id),)
        r.register_behavior('k04.test.wait',watch)
        r.register_card(CardDefinition('k04.test.wait','Damage observer',CardType.MINION,health=5,
            metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=()),
            triggers=(TriggerSpec('damage_dealt','k04.test.wait'),)))
    return r


class ConstructedUtilityCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.registry=registry(); cls.batch=load_batch()

    def game(self,hand=(),*,board=(),enemy=(),deck=(),corpses=0,weapon=None,
             enemy_weapon=None,custom_registry=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('test.hero',hand=hand,board=board,deck=deck,mana=30,max_mana=30,
                mana_cap=30,corpses=corpses,weapon_card_id=weapon),
            PlayerSetup('test.hero',board=enemy,weapon_card_id=enemy_weapon),
        ),seed=23),custom_registry or self.registry)

    def play(self,g,cid,target=None):
        eid=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid)
        g.apply(PlayCard(1,eid,target_id=target)); return eid

    def test_all_67_roots_execute_paid_complete_bodies_and_needed_triggers(self):
        roots=[r for r in self.batch['cards'] if r['recipe']['root']]
        self.assertEqual(len(roots),67)
        for row in roots:
            cid=row['record']['id']; recipe=row['recipe']
            with self.subTest(cid=cid):
                g=self.game((cid,'k04.test.kill','k04.test.hit','CORE_CS2_182','TLC_443t','k04.test.break_weapon'),
                    board=('CORE_CS2_182','TLC_443t','EX1_506a'),
                    enemy=('k04.test.big','TLC_443t','JAIL_877'),
                    deck=('CORE_CS2_182',)*5,corpses=10,
                    weapon=None if row['record']['type']=='WEAPON' else 'EDR_253',enemy_weapon='EDR_253')
                eid=g.state.players[1].hand[0]
                if cid in ('CORE_CS2_108','CORE_EX1_131'):
                    self.play(g,'k04.test.hit',g.state.players[2].board[0])
                action=next(a for a in g.legal_actions() if isinstance(a,PlayCard) and a.entity_id==eid)
                g.apply(action)
                self.assertEqual(g.state.players[1].mana,30-recipe['cost'])
                if recipe['trigger']=='friendly_hero_attack':
                    attack=next(a for a in g.legal_actions() if isinstance(a,Attack) and a.attacker_id==g.state.players[1].hero_id)
                    g.apply(attack)
                if recipe['trigger']=='own_turn_start':
                    g.apply(EndTurn(1)); g.apply(EndTurn(2))
                if 'deathrattle' in recipe['bodies']:
                    if row['record']['type']=='WEAPON': self.play(g,'k04.test.break_weapon')
                    else: self.play(g,'k04.test.kill',eid)
                if 'on_use' in recipe['bodies']:
                    g.apply(UseLocation(1,eid))
                self.assertIsNone(g.state.pending_choice)
                self.assertEqual(sum(e.kind=='card_played' and e.source_id==eid for e in g.events),1)

    def test_tokens_and_multiple_printed_tribes_are_complete_current_definitions(self):
        self.assertEqual(len(self.batch['cards']),92)
        self.assertEqual(self.registry.card('TLC_443t').metadata.tribes,('undead','beast'))
        self.assertEqual(self.registry.card('RLK_063t').metadata.tribes,('undead','dragon'))
        self.assertEqual(self.registry.card('CORE_SW_068').metadata.tribes,('demon','mech'))
        self.assertEqual(self.registry.card('CORE_GIL_534').metadata.tribes,('quilboar',))
        self.assertEqual((self.registry.card('GVG_079').attack,self.registry.card('GVG_079').health),(7,7))
        self.assertIn(Keyword.CHARGE,self.registry.card('HERO_11bpt').keywords)

    def test_buff_grants_and_reborn_use_existing_keyword_and_silence_lifecycle(self):
        g=self.game(('CAP_801','k04.test.kill'),board=('CORE_CS2_182',))
        target=g.state.players[1].board[0]
        self.play(g,'CAP_801',target)
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].max_health),(6,8))
        self.assertTrue({Keyword.REBORN,Keyword.TAUNT}<=g.state.entities[target].keywords)
        self.play(g,'k04.test.kill',target)
        reborn=g.state.players[1].board[0]
        self.assertNotEqual(reborn,target)
        self.assertEqual((g.state.entities[reborn].attack,g.state.entities[reborn].health),(4,1))
        self.assertNotIn(Keyword.REBORN,g.state.entities[reborn].keywords)

    def test_destroy_predicates_use_current_stats_and_reject_invalid_targets_before_payment(self):
        g=self.game(('CORE_CS2_108','k04.test.hit'),enemy=('CORE_CS2_182',))
        target=g.state.players[2].board[0]; before=g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g,'CORE_CS2_108',target)
        self.assertEqual(g.snapshot(),before)
        self.play(g,'k04.test.hit',target); self.play(g,'CORE_CS2_108',target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        g=self.game(('CORE_EX1_005','k04.test.buff'),enemy=('CORE_CS2_182',))
        target=g.state.players[2].board[0]
        self.play(g,'k04.test.buff',target); self.play(g,'CORE_EX1_005',target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)

    def test_undead_and_beast_target_domains_include_the_same_dual_tribe_token(self):
        g=self.game(('CORE_EDR_002','DINO_419'),board=('TLC_443t','CORE_CS2_182'))
        target,plain=g.state.players[1].board
        before=g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g,'CORE_EDR_002',plain)
        self.assertEqual(g.snapshot(),before)
        self.play(g,'CORE_EDR_002',target); self.play(g,'DINO_419',target)
        self.assertTrue({Keyword.POISONOUS,Keyword.RUSH,Keyword.TAUNT}<=g.state.entities[target].keywords)
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].max_health),(4,4))

    def test_hand_buff_limits_taunts_and_corpse_success_without_double_payment(self):
        g=self.game(('CORE_CFM_753','CORE_WW_329','CORE_RLK_712','CORE_CS2_182','TLC_443t'),corpses=2)
        plain,taunt=g.state.players[1].hand[-2:]
        self.play(g,'CORE_CFM_753'); self.play(g,'CORE_WW_329'); self.play(g,'CORE_RLK_712')
        self.assertEqual((g.state.entities[plain].attack,g.state.entities[plain].max_health),(7,8))
        self.assertEqual((g.state.entities[taunt].attack,g.state.entities[taunt].max_health),(7,7))
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0)
        self.assertEqual(g.state.players[1].mana,22)

    def test_grave_strength_selects_one_resource_branch(self):
        for bank,gain in ((4,1),(5,3)):
            with self.subTest(bank=bank):
                g=self.game(('RLK_707',),board=('CORE_CS2_182',),corpses=bank)
                target=g.state.players[1].board[0]
                self.play(g,'RLK_707')
                self.assertEqual(g.state.entities[target].attack,4+gain)
                self.assertEqual(g.state.players[1].resources[Resource.CORPSES],bank if bank==4 else 0)

    def test_summon_then_buff_includes_the_new_beast_from_longneck_deathrattle(self):
        g=self.game(('k04.test.kill',),board=('DINO_130','CORE_CS2_182'))
        self.play(g,'k04.test.kill',g.state.players[1].board[0])
        stats={g.state.entities[e].card_id:(g.state.entities[e].attack,g.state.entities[e].max_health) for e in g.state.players[1].board}
        self.assertEqual(stats,{'CORE_CS2_182':(5,6),'DINO_130t':(4,4)})

    def test_twisting_nether_removes_minions_and_locations_in_one_batch(self):
        g=self.game(('CORE_EX1_312',),board=('CORE_EX1_110','JAIL_877','k04.test.dormant'),
            enemy=('CORE_CS2_182','JAIL_877'))
        self.play(g,'CORE_EX1_312')
        self.assertEqual(len(g.state.death_history),4)
        self.assertEqual(len({d.batch for d in g.state.death_history}),1)
        self.assertEqual({g.state.entities[e].card_id for e in g.state.players[1].board},{'EX1_110t','k04.test.dormant'})
        self.assertFalse(g.state.players[2].board)

    def test_doomsayer_own_start_uses_one_batch_and_spares_new_deathrattle_children(self):
        g=self.game(board=('CORE_NEW1_021','CORE_EX1_110'),enemy=('CORE_CS2_182',))
        g.apply(EndTurn(1)); self.assertEqual(len(g.state.death_history),0)
        g.apply(EndTurn(2))
        self.assertEqual(len(g.state.death_history),3)
        self.assertEqual(len({d.batch for d in g.state.death_history}),1)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].board],['EX1_110t'])

    def test_attack_threshold_wipes_and_overload_are_complete(self):
        g=self.game(('CORE_EX1_197','END_028'),board=('CORE_CS2_182',),enemy=('k04.test.big',))
        self.play(g,'CORE_EX1_197')
        self.assertFalse(g.state.players[2].board); self.assertEqual(len(g.state.players[1].board),1)
        self.play(g,'END_028')
        self.assertFalse(g.state.players[1].board)
        self.assertEqual(g.state.players[1].overload_owed,2)

    def test_deathrattle_summons_preserve_complete_token_bodies_and_slot_limits(self):
        for cid,expected in [('CORE_AV_337',[('AV_337t',2)]),('CORE_EX1_110',[('EX1_110t',1)]),
            ('CORE_LOOT_368',[('CS2_065',3)]),('TLC_468',[('TLC_468t1',1),('TLC_468t2',1)]),
            ('TIME_017',[('GVG_079',1)])]:
            with self.subTest(cid=cid):
                g=self.game(('k04.test.kill',),board=(cid,))
                self.play(g,'k04.test.kill',g.state.players[1].board[0])
                ids=[g.state.entities[e].card_id for e in g.state.players[1].board]
                self.assertEqual(ids,[name for name,count in expected for _ in range(count)])
        g=self.game(('EDR_492',),board=('CORE_CS2_182',)*5)
        self.play(g,'EDR_492'); self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(sum(g.state.entities[e].card_id=='EDR_492t' for e in g.state.players[1].board),1)

    def test_paradox_summons_do_not_recursively_execute_battlecry(self):
        g=self.game(('TIME_059',))
        self.play(g,'TIME_059')
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].board],['TIME_059']*3)
        self.assertEqual(sum(e.kind=='card_played' for e in g.events),1)

    def test_freeze_water_elemental_and_frostwyrm_keep_complete_bodies(self):
        g=self.game(('CORE_BT_072',),enemy=('CORE_CS2_182',))
        target=g.state.players[2].board[0]
        self.play(g,'CORE_BT_072',target)
        self.assertIsNotNone(g.state.entities[target].frozen_until_owner_turn)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].board],['CS2_033','CS2_033'])
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        g.apply(Attack(1,g.state.players[1].board[0],g.state.players[2].hero_id))
        self.assertIsNotNone(g.state.entities[g.state.players[2].hero_id].frozen_until_owner_turn)
        g=self.game(('CORE_RLK_063',),enemy=('CORE_CS2_182',))
        self.play(g,'CORE_RLK_063',g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25)
        self.assertIsNotNone(g.state.entities[g.state.players[2].board[0]].frozen_until_owner_turn)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].card_id,'RLK_063t')

    def test_frail_ghoul_spawn_charge_end_turn_death_and_last_weapon_charge(self):
        g=self.game(('JAIL_450',))
        self.play(g,'JAIL_450'); hero=g.state.players[1].hero_id
        g.apply(Attack(1,hero,g.state.players[2].hero_id))
        ghoul=g.state.players[1].board[0]
        self.assertEqual(g.state.entities[ghoul].card_id,'HERO_11bpt')
        self.assertIn(Keyword.CHARGE,g.state.entities[ghoul].keywords)
        g.apply(Attack(1,ghoul,g.state.players[2].hero_id))
        g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[ghoul].zone,Zone.GRAVEYARD)
        for index in range(2):
            g.apply(EndTurn(2))
            g.apply(Attack(1,hero,g.state.players[2].hero_id))
            self.assertEqual(len(g.state.players[1].board),1)
            if index==0: g.apply(EndTurn(1))
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),g.snapshot())

    def test_location_summon_and_rat_deathrattle_share_normal_use_and_draw(self):
        g=self.game(('JAIL_877','k04.test.kill'),deck=('CORE_CS2_182',))
        loc=self.play(g,'JAIL_877'); before=g.state.players[1].mana
        g.apply(UseLocation(1,loc))
        self.assertEqual(g.state.players[1].mana,before)
        self.assertEqual((g.state.entities[loc].durability,g.state.entities[loc].location_cooldown),(1,2))
        rat=next(e for e in g.state.players[1].board if g.state.entities[e].card_id=='JAIL_877t')
        self.play(g,'k04.test.kill',rat)
        self.assertEqual([d.card_id for d in g.state.draw_history],['CORE_CS2_182'])

    def test_trade_and_prepare_use_their_distinct_real_payment_and_lock_rules(self):
        g=self.game(('CORE_SW_429',),deck=('CORE_CS2_182',))
        eid=g.state.players[1].hand[0]
        g.apply(UseHandAction(1,eid,'trade'))
        self.assertEqual(g.state.players[1].mana,29)
        self.assertEqual(g.state.entities[eid].zone,Zone.DECK)
        self.assertFalse(any(g.state.entities[e].card_id=='SW_429t' for e in g.state.players[1].board))
        g=self.game(('JAIL_457',),board=('CORE_CS2_182',))
        eid=g.state.players[1].hand[0]
        g.apply(UseHandAction(1,eid,'prepare'))
        self.assertEqual(g.state.players[1].mana,27)
        self.assertEqual(g.state.entities[eid].zone,Zone.HAND)
        self.assertEqual(len(g.state.players[1].board),1)
        with self.assertRaises(IllegalAction): g.apply(PlayCard(1,eid))
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        mana=g.state.players[1].mana
        g.apply(PlayCard(1,eid))
        self.assertEqual(g.state.players[1].mana,mana)
        friend=next(e for e in g.state.players[1].board if e!=eid)
        self.assertEqual(g.state.entities[friend].attack,5)

    def test_random_removal_returns_original_owner_and_replays_rng(self):
        g=self.game(('k04.test.kill',),board=('CORE_ULD_280',),enemy=('CORE_CS2_182','TLC_443t'))
        self.play(g,'k04.test.kill',g.state.players[1].board[0])
        self.assertEqual(len(g.state.players[2].hand),1)
        self.assertEqual(len(g.state.players[2].board),1)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),g.snapshot())

    def test_stage_after_real_wait_includes_new_elemental_and_preserves_player_privacy(self):
        g=self.game(('DINO_406',),board=('k04.test.wait',),custom_registry=registry(waiting=True))
        self.play(g,'DINO_406',g.state.players[2].hero_id)
        saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(g.for_player(2).legal_actions()['observation']['pending_choice'],{'player_id':1})
        restored=Game.from_snapshot(saved,registry(waiting=True))
        self.assertEqual(restored.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(waiting=True)).snapshot(),saved)
        for game in (g,restored): game.apply(SelectChoice(1,game.state.pending_choice.id,('continue',)))
        self.assertEqual(restored.snapshot(),g.snapshot())
        spark=next(e for e in g.state.players[1].board if g.state.entities[e].card_id=='BOT_102t')
        self.assertEqual((g.state.entities[spark].attack,g.state.entities[spark].max_health),(2,2))
        self.assertEqual(g.state.players[1].mana,27)

    def test_board_target_returned_during_damage_is_not_buffed_as_a_hand_card(self):
        g=self.game(('EDR_468',),board=('k04.test.wait','CORE_CS2_182'),custom_registry=registry(return_after_damage=True))
        target=g.state.players[1].board[1]
        self.play(g,'EDR_468',target)
        g.apply(SelectChoice(1,g.state.pending_choice.id,('continue',)))
        self.assertEqual(g.state.entities[target].zone,Zone.HAND)
        self.assertEqual(g.state.entities[target].attack,4)

    def test_corrupted_pin_and_unknown_operations_are_rejected(self):
        data=load_batch(); data['cards'][0]['record']['text']+='unreviewed'
        with TemporaryDirectory() as folder:
            path=Path(folder)/'changed.json'; path.write_text(json.dumps(data),encoding='utf-8')
            with patch('hs_sim.cards.utility_cards.BATCH_PATH',path),self.assertRaises(TargetValidationError): load_batch()
        with self.assertRaises(ValueError): UtilityStep('invented_mechanism')
        with self.assertRaises(ValueError): UtilityStep('destroy',amount=3)
