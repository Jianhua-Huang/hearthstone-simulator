"""Position-selected fusion, attachment lifetime and player/replay contracts.

Synthetic timing cases test the documented prototype contract, not CN certification.
"""
import json
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError,
    TriggerSpec, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, Freeze, GainArmor, GrantKeyword, RemoveEnchantment, RequestChoice,
    ReturnToHand, Silence, Transform)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.magnetic import host_eligible
from hs_sim.engine.model import CardClass, CardMetadata, Resource
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference


class MagneticTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        for name,tribes in (('mech',('mech',)),('plain',()),('beast',('beast',)),
                            ('undead',('undead',)),('all',('all',))):
            self.r.register_card(CardDefinition(name,name,CardType.MINION,attack=2,health=4,
                metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=tribes)))
        for name,fn in (
            ('kill',lambda c:[Destroy(c.target_id)]),
            ('ping',lambda c:[Damage(c.target_id,1,c.source_id)]),
            ('silence',lambda c:[Silence(c.target_id)]),
            ('bounce',lambda c:[ReturnToHand(c.target_id)]),
            ('transform',lambda c:[Transform(c.target_id,'plain')]),
            ('copy',lambda c:[CopyMinion(c.target_id,1)]),
            ('basecopy',lambda c:[CopyMinion(c.target_id,1,mode='base')]),
            ('steal',lambda c:[ChangeControl(c.target_id,2)]),
            ('freeze',lambda c:[Freeze(c.target_id)]),
            ('remove',lambda c:[RemoveEnchantment(c.target_id,c.state.entities[c.target_id].enchantments[0].id)]),
        ):self.spell(name,fn,requires_target=True)

    def spell(self,name,fn,**kw):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,**kw))

    def game(self,hand=('BOT_911',),board=('mech',),enemy_board=(),enemy_hand=(),**kw):
        defaults=dict(max_mana=10,mana=10,deck=('plain',)*12);defaults.update(kw)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=hand,board=board,**defaults),
            PlayerSetup('HERO_08',board=enemy_board,hand=enemy_hand,deck=('plain',)*12,max_mana=10,mana=10)),seed=114),self.r)

    def find(self,g,card,player=1,zone='hand'):
        return next(i for i in getattr(g.state.players[player],zone) if g.state.entities[i].card_id==card)

    def play(self,g,card,target=None,position=None):
        player=g.state.active_player;i=self.find(g,card,player)
        g.apply(PlayCard(player,i,target,position));return i

    def host(self,g):return g.state.entities[g.state.players[1].board[0]]
    def hero(self,g,player=1):return g.state.entities[g.state.players[player].hero_id]
    def check(self,g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r).snapshot(),g.snapshot())
        self.assertEqual(g.clone().snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def fuse(self,g,card='BOT_911',position=0):return self.play(g,card,position=position)

    def test_left_fuses_without_replacing_host(self):
        g=self.game();old=self.host(g).id;i=self.fuse(g);e=self.host(g)
        self.assertEqual((e.id,e.card_id,e.attack,e.health),(old,'mech',4,8))
        self.assertEqual(g.state.players[1].board,[old]);self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.players[1].mana,6);self.check(g)

    def test_right_edge_and_unspecified_position_summon_normally(self):
        for position in (None,1):
            g=self.game();i=self.play(g,'BOT_911',position=position)
            self.assertEqual(g.state.players[1].board[-1],i);self.assertEqual(self.host(g).attack,2)
            self.assertEqual(g.state.magnetic_history,[]);self.check(g)

    def test_middle_slot_selects_exact_right_neighbor(self):
        g=self.game(board=('plain','mech','mech'));ids=tuple(g.state.players[1].board)
        self.fuse(g,position=2);self.assertEqual(tuple(g.state.players[1].board),ids)
        self.assertEqual([g.state.entities[i].attack for i in ids],[2,2,4]);self.check(g)

    def test_left_of_non_mech_still_summons(self):
        g=self.game(board=('plain','mech'));i=self.fuse(g)
        self.assertEqual(g.state.players[1].board[0],i);self.assertEqual(g.state.magnetic_history,[]);self.check(g)

    def test_full_board_allows_fusion_but_no_eighth_body(self):
        g=self.game(board=('mech',)*7);i=self.find(g,'BOT_911');before=g.snapshot()
        for position in (None,7):
            with self.assertRaises(IllegalAction):g.apply(PlayCard(1,i,position=position))
            self.assertEqual(g.snapshot(),before)
        positions=[a.position for a in g.legal_actions() if isinstance(a,PlayCard) and a.entity_id==i]
        self.assertEqual(positions,list(range(7)));self.fuse(g);self.assertEqual(len(g.state.players[1].board),7);self.check(g)

    def test_full_board_without_matching_neighbor_has_no_play(self):
        g=self.game(board=('plain',)*7)
        self.assertFalse(any(isinstance(a,PlayCard) for a in g.legal_actions()))
        with self.assertRaises(IllegalAction):self.fuse(g)

    def test_extra_tribes_are_source_specific(self):
        for card,tribe,merge in (('DEEP_015','undead',True),('DEEP_015','beast',False),
                                ('TTN_087','beast',True),('TTN_087','undead',False),
                                ('BOT_911','undead',False),('BOT_911','all',True)):
            with self.subTest(card=card,tribe=tribe):
                g=self.game(hand=(card,),board=(tribe,));self.fuse(g,card)
                self.assertEqual(len(g.state.magnetic_history),int(merge));self.check(g)

    def test_magnetic_does_not_itself_imply_mech_tribe(self):
        g=self.game(board=('TTN_087',));self.fuse(g)
        self.assertEqual(len(g.state.players[1].board),2);self.assertEqual(g.state.magnetic_history,[])

    def test_enemy_and_dormant_hosts_ineligible(self):
        self.r.register_card(CardDefinition('sleep','Sleep',CardType.MINION,health=5,dormant_turns=2,
            metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('mech',))))
        g=self.game(board=('sleep',),enemy_board=('mech',));source=g.state.entities[self.find(g,'BOT_911')]
        for e in (self.host(g),g.state.entities[g.state.players[2].board[0]]):
            self.assertFalse(host_eligible(g.state,self.r,source,e))
        self.fuse(g);self.assertEqual(len(g.state.players[1].board),2);self.check(g)

    def test_location_is_not_a_host(self):
        g=self.game(board=('CORE_REV_990',));self.fuse(g);self.assertEqual(len(g.state.players[1].board),2);self.check(g)

    def test_host_damage_and_readiness_are_retained(self):
        g=self.game(hand=('ping','BOT_563'));h=self.host(g).id
        self.play(g,'ping',h);g.apply(Attack(1,h,self.hero(g,2).id));turn=self.host(g).summoned_turn
        self.fuse(g,'BOT_563');e=self.host(g)
        self.assertEqual((e.attack,e.max_health,e.health,e.damage,e.attacks_this_turn,e.summoned_turn),(8,9,8,1,1,turn))
        with self.assertRaises(IllegalAction):g.apply(Attack(1,h,self.hero(g,2).id))
        self.check(g)

    def test_frozen_host_stays_frozen(self):
        g=self.game(hand=('freeze','BOT_548'));h=self.host(g).id;self.play(g,'freeze',h);self.fuse(g,'BOT_548')
        self.assertTrue(self.host(g).frozen)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,h,self.hero(g,2).id))
        self.check(g)

    def test_rush_grant_does_not_allow_new_host_to_hit_hero(self):
        g=self.game(hand=('mech','TTN_087'),board=(),enemy_board=('plain',));h=self.play(g,'mech');self.fuse(g,'TTN_087')
        with self.assertRaises(IllegalAction):g.apply(Attack(1,h,self.hero(g,2).id))
        g.apply(Attack(1,h,g.state.players[2].board[0]));self.check(g)

    def test_fusion_is_play_without_summon_death_or_corpse(self):
        g=self.game();self.fuse(g)
        kinds=[e.kind for e in g.events]
        self.assertIn('magnetized',kinds);self.assertIn('card_played',kinds);self.assertNotIn('minion_summoned',kinds)
        self.assertEqual(g.state.death_history,[]);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0)
        record=g.state.play_history[-1];self.assertTrue(record.completed);self.assertEqual((record.position,record.magnetic_target_id),(0,self.host(g).id));self.check(g)

    def test_fusion_counts_for_next_combo(self):
        g=self.game(hand=('BOT_035','EX1_134'));self.fuse(g,'BOT_035');self.play(g,'EX1_134',self.hero(g,2).id)
        self.assertTrue(g.state.play_history[-1].combo);self.check(g)

    def test_cannot_supply_spell_target_to_fusion(self):
        g=self.game();before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'BOT_911',self.host(g).id,0)
        self.assertEqual(g.snapshot(),before)

    def test_two_fusions_have_distinct_groups_and_abilities(self):
        g=self.game(hand=('BOT_911','BOT_911'));self.fuse(g);self.fuse(g)
        e=self.host(g);self.assertEqual((e.attack,e.health),(6,12));self.assertEqual([x.id for x in g.state.magnetic_history],[1,2])
        self.assertEqual({a.magnetic_id for a in e.abilities if a.origin=='granted'},{1,2});self.check(g)

    def test_two_shields_are_not_two_damage_blocks(self):
        g=self.game(hand=('BOT_911','BOT_911','ping','ping'));self.fuse(g);self.fuse(g);h=self.host(g).id
        self.play(g,'ping',h);self.assertEqual(self.host(g).health,12);self.play(g,'ping',h);self.assertEqual(self.host(g).health,11);self.check(g)

    def test_new_fusion_can_restore_consumed_shield(self):
        g=self.game(hand=('BOT_911','BOT_911','ping','ping'));self.fuse(g);h=self.host(g).id
        self.play(g,'ping',h);self.fuse(g);self.play(g,'ping',h);self.assertEqual(self.host(g).health,12);self.check(g)

    def test_spider_bomb_grants_deathrattle_to_host(self):
        g=self.game(hand=('BOT_251','kill'),enemy_board=('plain',));h=self.host(g).id;source=self.fuse(g,'BOT_251');self.play(g,'kill',h)
        self.assertEqual(g.state.players[2].board,[]);self.assertEqual(len(g.state.death_history),2)
        self.assertNotIn(source,[d.entity_id for d in g.state.death_history]);self.check(g)

    def test_duplicate_deathrattles_both_resolve(self):
        g=self.game(hand=('BOT_251','BOT_251','kill'),enemy_board=('plain','plain'));h=self.host(g).id
        self.fuse(g,'BOT_251');self.fuse(g,'BOT_251');self.play(g,'kill',h)
        self.assertEqual(g.state.players[2].board,[]);self.assertEqual(len(g.state.death_history),3);self.check(g)

    def test_missile_launcher_uses_host_as_damage_source(self):
        g=self.game(hand=('BOT_107','BOT_035'),enemy_board=('plain','plain'));self.fuse(g,'BOT_107');self.fuse(g,'BOT_035');g.apply(EndTurn(1))
        self.assertEqual(g.state.players[2].board,[]);self.assertEqual(self.hero(g).health,29);self.assertEqual(self.hero(g,2).health,29)
        self.assertEqual(self.host(g).health,10);self.check(g)

    def test_zilliax_lifesteal_heals_host_controller(self):
        g=self.game(hand=('ping','BOT_548'));self.play(g,'ping',self.hero(g).id);self.fuse(g,'BOT_548')
        g.apply(Attack(1,self.host(g).id,self.hero(g,2).id));self.assertEqual(self.hero(g).health,30);self.check(g)

    def test_reborn_rebuilds_base_host_without_magnetic_attachments(self):
        g=self.game(hand=('DEEP_015','kill'));h=self.host(g).id;self.fuse(g,'DEEP_015');self.play(g,'kill',h)
        e=self.host(g);self.assertNotEqual(e.id,h);self.assertEqual((e.card_id,e.attack,e.health),('mech',2,1))
        self.assertFalse(e.enchantments);self.assertNotIn(Keyword.REBORN,e.keywords);self.assertEqual(len(g.state.death_history),1);self.check(g)

    def test_silence_removes_all_groups(self):
        g=self.game(hand=('BOT_911','BOT_035','silence'));self.fuse(g);self.fuse(g,'BOT_035');self.play(g,'silence',self.host(g).id)
        self.assertEqual((self.host(g).attack,self.host(g).health),(2,4));self.assertEqual(self.host(g).keywords,set())
        self.assertEqual(len(g.state.magnetic_history),2);self.check(g)

    def test_removing_one_group_keeps_other_group(self):
        g=self.game(hand=('BOT_911','BOT_035','remove'));self.fuse(g);self.fuse(g,'BOT_035');self.play(g,'remove',self.host(g).id)
        e=self.host(g);self.assertEqual((e.attack,e.health),(4,6));self.assertIn(Keyword.POISONOUS,e.keywords);self.assertNotIn(Keyword.TAUNT,e.keywords);self.check(g)

    def test_copy_preserves_groups_with_new_attachment_identity(self):
        g=self.game(hand=('BOT_911','copy'));self.fuse(g);h=self.host(g).id;self.play(g,'copy',h)
        a,b=[g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual((b.attack,b.health),(4,8));self.assertEqual(b.enchantments[0].magnetic_id,1)
        self.assertTrue({x.id for x in a.enchantments+a.abilities}.isdisjoint(x.id for x in b.enchantments+b.abilities));self.check(g)

    def test_removing_original_group_does_not_mutate_copy(self):
        g=self.game(hand=('BOT_911','copy','remove'));self.fuse(g);h=self.host(g).id;self.play(g,'copy',h);self.play(g,'remove',h)
        copied=g.state.entities[g.state.players[1].board[1]];self.assertEqual(copied.attack,4);self.assertIn(Keyword.TAUNT,copied.keywords);self.check(g)

    def test_base_copy_omits_groups(self):
        g=self.game(hand=('BOT_911','basecopy'));self.fuse(g);self.play(g,'basecopy',self.host(g).id)
        e=g.state.entities[g.state.players[1].board[1]];self.assertEqual((e.attack,e.health),(2,4));self.assertFalse(e.enchantments);self.check(g)

    def test_bounce_resets_groups_but_retains_history(self):
        g=self.game(hand=('BOT_911','bounce'));h=self.host(g).id;self.fuse(g);self.play(g,'bounce',h);e=g.state.entities[h]
        self.assertEqual((e.zone,e.attack,e.health),(Zone.HAND,2,4));self.assertFalse(e.enchantments);self.assertEqual(len(g.state.magnetic_history),1);self.check(g)

    def test_transform_resets_groups_but_retains_history(self):
        g=self.game(hand=('BOT_911','transform'));self.fuse(g);self.play(g,'transform',self.host(g).id)
        self.assertEqual(self.host(g).card_id,'plain');self.assertFalse(self.host(g).enchantments);self.check(g)

    def test_control_change_preserves_group_and_current_controller(self):
        g=self.game(hand=('BOT_251','steal'),board=('mech','plain'));h=self.host(g).id;self.fuse(g,'BOT_251');self.play(g,'steal',h)
        self.assertEqual(g.state.entities[h].controller,2);self.assertEqual(g.state.entities[h].attack,4)
        self.assertEqual(g.state.magnetic_history[0].player_id,1);self.check(g)

    def stored_buff(self,attack,health,temporary=False):
        self.spell('buffhand',lambda c:[BuffStoredCard(CardReference.capture(c.state.entities[next(i for i in c.state.players[1].hand if c.state.entities[i].card_id=='BOT_035')]),
            attack,health,expires_turn=c.state.turn if temporary else None)])

    def test_hand_buff_is_included_in_frozen_stats(self):
        self.stored_buff(3,4);g=self.game(hand=('buffhand','BOT_035'));self.play(g,'buffhand');self.fuse(g,'BOT_035')
        self.assertEqual((self.host(g).attack,self.host(g).health),(7,10));self.assertEqual((g.state.magnetic_history[0].attack,g.state.magnetic_history[0].health),(5,6));self.check(g)

    def test_negative_hand_attack_is_clamped_before_transfer(self):
        self.stored_buff(-10,0);g=self.game(hand=('buffhand','BOT_035'));self.play(g,'buffhand');self.fuse(g,'BOT_035')
        self.assertEqual(self.host(g).attack,2);self.assertEqual(g.state.magnetic_history[0].attack,0);self.check(g)

    def test_current_contract_freezes_temporary_numeric_buff(self):
        self.stored_buff(3,4,True);g=self.game(hand=('buffhand','BOT_035'));self.play(g,'buffhand');self.fuse(g,'BOT_035');g.apply(EndTurn(1))
        self.assertEqual((self.host(g).attack,self.host(g).health),(7,10));self.check(g)

    def test_entry_battlecry_is_only_run_for_independent_play(self):
        self.r.register_behavior('armor',lambda c:[GainArmor(1,3)])
        self.r.register_card(CardDefinition('entry','Entry',CardType.MINION,attack=1,health=1,
            keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',),on_play='armor',requires_target=True))
        for position,armor in ((0,0),(1,3)):
            g=self.game(hand=('entry',));self.play(g,'entry',None if position==0 else self.hero(g).id,position)
            self.assertEqual(self.hero(g).armor,armor);self.check(g)

    def test_player_actions_explain_position_selected_host(self):
        g=self.game();port=g.for_player(1);listing=port.legal_actions();ref=listing['observation']['players'][0]['board'][0]['ref']
        actions=[a for a in listing['actions'] if a['type']=='play_card']
        self.assertEqual({a['position']:a['magnetic_target'] for a in actions},{0:ref,1:None})
        action=next(a for a in actions if a['magnetic_target']==ref)
        self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted']);self.check(g)

    def test_player_rejects_magnetic_hint_that_disagrees_with_position(self):
        g=self.game();port=g.for_player(1);listing=port.legal_actions();a=next(a for a in listing['actions'] if a['type']=='play_card' and a['position']==0)
        a['magnetic_target']=None;before=g.snapshot();self.assertFalse(port.submit({'revision':listing['revision'],'action':a})['accepted']);self.assertEqual(g.snapshot(),before)

    def test_player_can_omit_redundant_magnetic_hint(self):
        g=self.game();port=g.for_player(1);listing=port.legal_actions();a=next(a for a in listing['actions'] if a['type']=='play_card' and a['position']==0)
        del a['magnetic_target'];self.assertTrue(port.submit({'revision':listing['revision'],'action':a})['accepted']);self.assertEqual(len(g.state.magnetic_history),1);self.check(g)

    def test_public_upgrade_list_has_card_identities_not_internal_groups(self):
        g=self.game();self.fuse(g)
        for seat in (1,2):
            own=next(p for p in g.observe(seat)['players'] if p['id']==1);self.assertEqual(own['board'][0]['magnetic_upgrades'],['BOT_911'])
            self.assertNotIn('magnetic_id',json.dumps(g.observe(seat)))

    def test_hidden_magnetic_hand_identity_does_not_leak(self):
        a=self.game(hand=('BOT_911',));b=self.game(hand=('BOT_035',));self.assertEqual(a.observe(2),b.observe(2))
        self.assertEqual(a.observe(1)['players'][0]['hand'][0]['magnetic_tribes'],['mech'])

    def test_fusion_event_choice_can_save_resume_and_replay(self):
        self.r.register_behavior('pause',lambda c:[RequestChoice(1,(ChoiceOption('go','Go',(GainArmor(1,2),)),),c.source_id)])
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=2,triggers=(TriggerSpec('magnetized','pause'),)))
        g=self.game(board=('mech','watcher'));self.fuse(g);self.assertIsNotNone(g.state.pending_choice);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for m in (g,restored):m.apply(SelectChoice(1,m.state.pending_choice.id,('go',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertTrue(g.state.play_history[-1].completed);self.check(g)

    def test_event_failure_rolls_back_entire_merge(self):
        def fail(c):raise ResolutionError('intentional magnetic rollback')
        self.r.register_behavior('fail',fail)
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=2,triggers=(TriggerSpec('magnetized','fail'),)))
        g=self.game(board=('mech','watcher'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.fuse(g)
        self.assertEqual(g.snapshot(),before)

    def rehash(self,data):
        data['state_hash']=canonical_hash({k:v for k,v in data.items() if k not in ('schema_version','events','events_hash','state_hash')})

    def test_rehashed_invalid_magnetic_history_is_rejected(self):
        g=self.game();self.fuse(g)
        for field,value in (('id',2),('play_id',999),('target_id',999),('source_id',999),('player_id',2),
                            ('card_id','plain'),('host_card_id','plain'),('attack',True),('health',0),('enchantment_id',999999),('ability_ids',[True])):
            data=g.snapshot();data['state']['magnetic_history'][0][field]=value;self.rehash(data)
            with self.subTest(field=field),self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_missing_merge_history_or_play_target_is_rejected(self):
        g=self.game();self.fuse(g)
        data=g.snapshot();data['state']['magnetic_history']=[];self.rehash(data)
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)
        data=g.snapshot();data['state']['play_history'][0]['magnetic_target_id']=None;self.rehash(data)
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_rehashed_attachment_unknown_group_is_rejected(self):
        g=self.game();self.fuse(g);data=g.snapshot();data['state']['entities'][str(self.host(g).id)]['enchantments'][0]['magnetic_id']=99;self.rehash(data)
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_previous_snapshot_schema_is_rejected(self):
        g=self.game();data=g.snapshot();data['schema_version']=31
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_invalid_magnetic_declaration_is_rejected(self):
        for tribes,keywords,kind in (((),(Keyword.MAGNETIC,),CardType.MINION),
                (('mech',),(),CardType.MINION),(('mech','mech'),(Keyword.MAGNETIC,),CardType.MINION),
                (['mech'],(Keyword.MAGNETIC,),CardType.MINION),(('mech',),(Keyword.MAGNETIC,),CardType.SPELL)):
            with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','Bad',kind,health=1,magnetic_tribes=tribes,keywords=keywords))

    def test_magnetic_cannot_be_granted_without_a_source_contract(self):
        self.spell('grant',lambda c:[GrantKeyword(c.state.players[1].board[0],Keyword.MAGNETIC)])
        g=self.game(hand=('grant',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'grant')
        self.assertEqual(g.snapshot(),before)

    def test_donor_discount_does_not_change_host_cost(self):
        from hs_sim.engine import CostSpec
        from hs_sim.engine.effects import ModifyCost
        self.spell('discount',lambda c:[ModifyCost(next(i for i in c.state.players[1].hand if c.state.entities[i].card_id=='BOT_911'),CostSpec(delta=-3))])
        g=self.game(hand=('discount','BOT_911','bounce'));self.play(g,'discount');self.fuse(g)
        self.assertEqual(g.state.play_history[-1].cost,1);h=self.host(g).id;self.play(g,'bounce',h)
        self.assertEqual(g.quote_cost(h).amount,0);self.check(g)

    def test_host_incoming_aura_is_not_copied_into_contribution(self):
        g=self.game(board=('mech','CS2_222'));self.assertEqual((self.host(g).attack,self.host(g).health),(3,5))
        self.fuse(g);self.assertEqual((self.host(g).attack,self.host(g).health),(5,9))
        self.assertEqual((g.state.magnetic_history[0].attack,g.state.magnetic_history[0].health),(2,4));self.check(g)

    def test_donor_ongoing_aura_operates_from_host(self):
        from hs_sim.engine.model import AuraSpec
        self.r.register_card(CardDefinition('aura','Aura',CardType.MINION,attack=1,health=1,
            keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',),auras=(AuraSpec(2,health=1),)))
        g=self.game(hand=('aura','silence'),board=('mech','plain'));self.fuse(g,'aura')
        other=g.state.players[1].board[1];self.assertEqual((g.state.entities[other].attack,g.state.entities[other].health),(4,5))
        self.assertEqual((self.host(g).attack,self.host(g).health),(3,5))
        self.play(g,'silence',self.host(g).id);self.assertEqual((g.state.entities[other].attack,g.state.entities[other].health),(2,4));self.check(g)

    def test_inherited_finite_trigger_consumes_on_host(self):
        from hs_sim.engine import LimitedTriggerSpec
        self.r.register_behavior('burst',lambda c:[GainArmor(c.player_id,c.source.attack)])
        self.r.register_card(CardDefinition('burst','Burst',CardType.MINION,attack=1,health=1,
            keywords=(Keyword.MAGNETIC,Keyword.SPELLBURST),magnetic_tribes=('mech',),
            limited_triggers=(LimitedTriggerSpec.spellburst('burst'),)))
        self.spell('noop',lambda c:[])
        g=self.game(hand=('burst','noop','noop'));self.fuse(g,'burst');self.play(g,'noop');self.play(g,'noop')
        self.assertEqual(self.hero(g).armor,3);self.assertEqual([a.uses_remaining for a in self.host(g).abilities if a.kind=='limited_trigger'],[0]);self.check(g)

    def test_rehashed_group_with_wrong_source_or_stats_is_rejected(self):
        g=self.game();self.fuse(g)
        for field,value in (('source_id',self.hero(g).id),('attack',99),('health',99),('expires_turn',3)):
            data=g.snapshot();data['state']['entities'][str(self.host(g).id)]['enchantments'][0][field]=value;self.rehash(data)
            with self.subTest(field=field),self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_real_player_port_fusion_example(self):
        from examples.magnetic_fusion import run
        game,snapshot=run();self.assertEqual(len(game.history),8);self.assertEqual(snapshot['schema_version'],266)


if __name__=='__main__':unittest.main()
