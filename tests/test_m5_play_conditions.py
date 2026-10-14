"""Frozen resource conditions and physical hand-entry provenance across layers."""
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, CostSpec, EndTurn, Game, IllegalAction,
    Keyword, PaymentType, PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice,
    SnapshotError, TargetMode, TargetSpec, TriggerSpec, UseHandAction, Zone)
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChangeManaCrystals, ChoiceOption,
    Damage, Draw, GainArmor, GainTemporaryMana, GrantKeyword, ModifyCost, Overload, RefreshMana,
    RequestChoice, ReturnToHand)
from hs_sim.engine.hand_history import hand_entry
from hs_sim.engine.play_history import preplay_conditions
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard, ReorderZone


class PlayConditionTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        self.r.register_card(CardDefinition('plain','Plain',CardType.MINION,attack=1,health=9))
        self.spell('draw',lambda c:[Draw(c.player_id)])
        self.spell('make',lambda c:[AddToHand(c.player_id,'WW_434')])
        self.spell('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        self.spell('noop',lambda c:[])

    def spell(self,name,fn,**kwargs):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,**kwargs))

    def game(self,hand=(),board=(),enemy_hand=(),enemy_board=(),**fields):
        defaults=dict(deck=('plain',)*10,max_mana=10,mana=10);defaults.update(fields)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=hand,board=board,**defaults),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy_board,deck=('plain',)*10,max_mana=10,mana=10)),seed=112),self.r)

    def find(self,g,card,player=1,zone='hand'):
        return next(i for i in getattr(g.state.players[player],zone) if g.state.entities[i].card_id==card)
    def play(self,g,card,target=None):
        i=self.find(g,card,g.state.active_player);g.apply(PlayCard(g.state.active_player,i,target));return i
    def hero(self,g,player=1):return g.state.players[player].hero_id
    def flags(self,g,card,player=1):return preplay_conditions(g.state,g.state.entities[self.find(g,card,player)],self.r)
    def ref(self,c,card):return CardReference.capture(next(e for e in c.state.entities.values() if e.zone==Zone.HAND and e.card_id==card))
    def check(self,g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r).snapshot(),g.snapshot())
        self.assertEqual(g.clone().snapshot(),g.snapshot());self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def test_finale_uses_exact_remaining_mana(self):
        for mana,active in ((2,True),(3,False)):
            g=self.game(hand=('ETC_325',),mana=mana);self.assertEqual(self.flags(g,'ETC_325')['finale'],active)
            i=self.play(g,'ETC_325');self.assertEqual(Keyword.LIFESTEAL in g.state.entities[i].keywords,active)
            self.assertEqual(g.state.play_history[-1].finale,active);self.check(g)

    def test_zero_cost_finale_at_zero_mana(self):
        for mana,attack in ((0,2),(1,1)):
            g=self.game(hand=('JAM_017',),board=('plain',),mana=mana);i=g.state.players[1].board[0]
            self.play(g,'JAM_017',i);self.assertEqual(g.state.entities[i].attack,attack);self.assertIn(Keyword.RUSH,g.state.entities[i].keywords);self.check(g)

    def test_finale_uses_discounted_quote(self):
        self.spell('discount',lambda c:[ModifyCost(self.ref(c,'ETC_325').entity_id,CostSpec(delta=-1))])
        g=self.game(hand=('discount','ETC_325'),mana=1);self.play(g,'discount');i=self.play(g,'ETC_325')
        self.assertIn(Keyword.LIFESTEAL,g.state.entities[i].keywords);self.assertEqual(g.state.play_history[-1].cost,1);self.check(g)

    def test_finale_includes_temporary_mana_in_expenditure(self):
        g=self.game(hand=('ETC_325',),max_mana=1,mana=2,temporary_mana=1);self.play(g,'ETC_325')
        record=g.state.play_history[-1];self.assertEqual((record.mana_before,record.mana_after,record.mana_crystals),(2,0,1));self.assertTrue(record.finale);self.check(g)

    def test_finale_uses_available_mana_after_locked_crystals(self):
        g=self.game(hand=('ETC_325',),max_mana=5,mana=2,overload_locked=3);self.play(g,'ETC_325');self.assertTrue(g.state.play_history[-1].finale);self.check(g)

    def test_health_payment_finale_requires_no_remaining_mana(self):
        self.spell('health',lambda c:[ModifyCost(self.ref(c,'ETC_325').entity_id,CostSpec(payment=PaymentType.HEALTH))])
        for mana in (0,2):
            g=self.game(hand=('health','ETC_325'),mana=mana);self.play(g,'health');self.play(g,'ETC_325');record=g.state.play_history[-1]
            self.assertEqual((record.mana_before,record.mana_after),(mana,mana));self.assertEqual(record.finale,mana==0);self.check(g)

    def test_payment_reaction_does_not_rewrite_finale(self):
        self.r.register_behavior('refund',lambda c:[GainTemporaryMana(c.player_id,1)])
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=1,triggers=(TriggerSpec('mana_spent','refund'),)))
        g=self.game(hand=('ETC_325',),board=('watcher',),mana=2);i=self.play(g,'ETC_325')
        self.assertGreater(g.state.players[1].mana,0);self.assertIn(Keyword.LIFESTEAL,g.state.entities[i].keywords);self.check(g)

    def test_resource_changes_in_body_do_not_rewrite_finale(self):
        self.spell('refresh',lambda c:[RefreshMana(c.player_id,10),GainArmor(c.player_id,int(c.play.finale))],cost=2,keywords=(Keyword.FINALE,))
        g=self.game(hand=('refresh',),mana=2);self.play(g,'refresh');self.assertEqual(g.state.entities[self.hero(g)].armor,1);self.assertEqual(g.state.players[1].mana,10);self.check(g)

    def test_manathirst_threshold_and_spent_crystals(self):
        for crystals,damage in ((7,2),(8,3),(10,3)):
            g=self.game(hand=('RLK_843',),max_mana=crystals,mana=1);self.play(g,'RLK_843',self.hero(g,2))
            self.assertEqual(g.state.entities[self.hero(g,2)].health,30-damage);self.check(g)

    def test_temporary_mana_does_not_raise_manathirst(self):
        g=self.game(hand=('RLK_843',),max_mana=7,temporary_mana=1,mana=8);self.play(g,'RLK_843',self.hero(g,2))
        self.assertFalse(g.state.play_history[-1].manathirst);self.assertEqual(g.state.entities[self.hero(g,2)].health,28);self.check(g)

    def test_locked_crystals_still_satisfy_manathirst(self):
        g=self.game(hand=('RLK_843',),max_mana=8,overload_locked=7,mana=1);self.play(g,'RLK_843',self.hero(g,2));self.assertTrue(g.state.play_history[-1].manathirst);self.check(g)

    def test_manathirst_minion_buffs_and_shield(self):
        g=self.game(hand=('RLK_518',),max_mana=8,mana=3);i=self.play(g,'RLK_518');e=g.state.entities[i]
        self.assertEqual((e.attack,e.health),(4,7));self.assertIn(Keyword.DIVINE_SHIELD,e.keywords);self.check(g)

    def test_manathirst_does_not_spend_threshold_mana(self):
        g=self.game(hand=('RLK_843',),max_mana=8,mana=8);self.play(g,'RLK_843',self.hero(g,2));self.assertEqual(g.state.players[1].mana,7);self.check(g)

    def test_crystal_reaction_cannot_retroactively_enable_manathirst(self):
        self.r.register_behavior('ramp',lambda c:[ChangeManaCrystals(c.player_id,1)])
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=1,triggers=(TriggerSpec('mana_spent','ramp'),)))
        g=self.game(hand=('RLK_843',),board=('watcher',),max_mana=7,mana=1);self.play(g,'RLK_843',self.hero(g,2))
        self.assertEqual(g.state.players[1].max_mana,8);self.assertFalse(g.state.play_history[-1].manathirst);self.check(g)

    def test_scenario_hand_is_not_newly_acquired(self):
        g=self.game(hand=('WW_434',));self.assertFalse(self.flags(g,'WW_434')['quickdraw']);self.play(g,'WW_434')
        self.assertEqual(g.state.play_history[-1].hand_entry_turn,0);self.check(g)

    def test_drawn_card_enables_quickdraw_target(self):
        g=self.game(hand=('draw',),deck=('WW_434','plain'));self.play(g,'draw');self.assertTrue(self.flags(g,'WW_434')['quickdraw'])
        with self.assertRaises(IllegalAction):self.play(g,'WW_434')
        self.play(g,'WW_434',self.hero(g,2));self.assertEqual(g.state.entities[self.hero(g,2)].health,24);self.assertEqual(g.state.hand_entries[-1].reason,'draw');self.check(g)

    def test_generated_card_enables_quickdraw(self):
        g=self.game(hand=('make',));self.play(g,'make');self.play(g,'WW_434',self.hero(g,2));self.assertTrue(g.state.play_history[-1].quickdraw);self.check(g)

    def test_old_card_cannot_choose_quickdraw_target(self):
        g=self.game(hand=('WW_434',))
        with self.assertRaises(IllegalAction):self.play(g,'WW_434',self.hero(g,2))
        self.play(g,'WW_434');self.assertEqual(g.state.entities[self.hero(g,2)].health,30);self.check(g)

    def test_quickdraw_expires_across_turns(self):
        g=self.game(hand=('make',));self.play(g,'make');g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertFalse(self.flags(g,'WW_434')['quickdraw']);self.play(g,'WW_434');self.check(g)

    def test_opponent_turn_acquisition_not_next_own_turn(self):
        self.spell('gift',lambda c:[AddToHand(1,'WW_434')])
        g=self.game(enemy_hand=('gift',));g.apply(EndTurn(1));self.play(g,'gift');self.assertTrue(self.flags(g,'WW_434')['quickdraw'])
        g.apply(EndTurn(2));self.assertFalse(self.flags(g,'WW_434')['quickdraw']);self.check(g)

    def test_current_copy_acquires_fresh_turn_without_refreshing_original(self):
        self.spell('copy',lambda c:[CopyCard(self.ref(c,'WW_434'),1)])
        g=self.game(hand=('WW_434','copy'));self.play(g,'copy');values=[preplay_conditions(g.state,g.state.entities[i],self.r)['quickdraw'] for i in g.state.players[1].hand]
        self.assertEqual(values,[False,True]);self.check(g)

    def test_base_copy_acquires_fresh_turn(self):
        self.spell('copy',lambda c:[CopyCard(self.ref(c,'WW_434'),1,mode='base')])
        g=self.game(hand=('WW_434','copy'));self.play(g,'copy');i=g.state.players[1].hand[-1]
        self.assertEqual(hand_entry(g.state,g.state.entities[i].hand_entry_id).turn,1);self.check(g)

    def test_return_to_hand_is_new_acquisition(self):
        g=self.game(hand=('bounce',),board=('WW_434',));i=g.state.players[1].board[0];self.play(g,'bounce')
        self.assertEqual(self.find(g,'WW_434'),i);self.assertTrue(self.flags(g,'WW_434')['quickdraw']);self.assertEqual(g.state.hand_entries[-1].reason,'return');self.check(g)

    def test_return_to_original_owner_records_correct_player(self):
        self.spell('steal',lambda c:[ChangeControl(c.state.players[2].board[0],1)])
        self.spell('returnowner',lambda c:[ReturnToHand(c.state.players[1].board[0],to_owner=True)])
        g=self.game(hand=('steal','returnowner'),enemy_board=('WW_434',));self.play(g,'steal');self.play(g,'returnowner')
        self.assertEqual(g.state.hand_entries[-1].player_id,2);self.assertTrue(self.flags(g,'WW_434',2)['quickdraw']);self.check(g)

    def test_move_between_hands_records_new_controller(self):
        self.spell('give',lambda c:[MoveCard(self.ref(c,'WW_434'),2,Zone.HAND)])
        g=self.game(hand=('WW_434','give'));self.play(g,'give');self.assertTrue(self.flags(g,'WW_434',2)['quickdraw']);self.check(g)

    def test_deck_roundtrip_refreshes_entry(self):
        self.spell('away',lambda c:[MoveCard(self.ref(c,'WW_434'),1,Zone.DECK,position='top')])
        g=self.game(hand=('WW_434','away','draw'));old=g.state.entities[self.find(g,'WW_434')].hand_entry_id
        self.play(g,'away');self.play(g,'draw');self.assertNotEqual(g.state.entities[self.find(g,'WW_434')].hand_entry_id,old);self.assertTrue(self.flags(g,'WW_434')['quickdraw']);self.check(g)

    def test_same_hand_move_does_not_refresh_entry(self):
        self.spell('stay',lambda c:[MoveCard(self.ref(c,'WW_434'),1,Zone.HAND)])
        g=self.game(hand=('WW_434','stay'));before=len(g.state.hand_entries);self.play(g,'stay');self.assertEqual(len(g.state.hand_entries),before);self.assertFalse(self.flags(g,'WW_434')['quickdraw']);self.check(g)

    def test_reorder_does_not_refresh_entry(self):
        self.spell('reverse',lambda c:[ReorderZone(c.player_id,Zone.HAND,tuple(reversed(c.state.players[c.player_id].hand)))])
        g=self.game(hand=('WW_434','noop','reverse'));self.play(g,'reverse');self.assertFalse(self.flags(g,'WW_434')['quickdraw']);self.check(g)

    def test_forge_and_corrupt_preserve_acquisition(self):
        g=self.game(hand=('TTN_042','DMF_073','CS2_029'));i=self.find(g,'TTN_042');first=g.state.entities[i].hand_entry_id
        g.apply(UseHandAction(1,i,'forge'));self.assertEqual(g.state.entities[i].hand_entry_id,first)
        corrupt=self.find(g,'DMF_073');entry=g.state.entities[corrupt].hand_entry_id;self.play(g,'CS2_029',self.hero(g,2))
        self.assertEqual(g.state.entities[corrupt].card_id,'DMF_073t');self.assertEqual(g.state.entities[corrupt].hand_entry_id,entry);self.check(g)

    def test_trade_only_drawn_card_gets_new_hand_entry(self):
        g=self.game(hand=('WW_434',),deck=('WW_434',));i=self.find(g,'WW_434');g.apply(UseHandAction(1,i,'trade'))
        self.assertFalse(g.state.play_history);self.assertEqual(len(g.state.hand_entries),2);self.assertTrue(self.flags(g,'WW_434')['quickdraw']);self.check(g)

    def test_burned_draw_has_no_successful_acquisition(self):
        self.spell('filldraw',lambda c:[AddToHand(1,'plain'),Draw(1)])
        g=self.game(hand=('plain',)*9+('filldraw',),deck=('WW_434',));before=len(g.state.hand_entries);self.play(g,'filldraw')
        self.assertEqual(len(g.state.hand_entries),before+1);e=next(e for e in g.state.entities.values() if e.card_id=='WW_434');self.assertEqual(e.zone,Zone.GRAVEYARD);self.assertIsNone(e.hand_entry_id);self.check(g)

    def test_failed_action_rolls_back_entry_allocator_and_resources(self):
        def fail(c):raise RuntimeError('intentional')
        from hs_sim.engine.effects import InvokeBehavior
        self.r.register_behavior('fail',fail);self.spell('bad',lambda c:[AddToHand(1,'WW_434'),InvokeBehavior('fail',c.source_id,c.player_id)])
        g=self.game(hand=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_rehydrate_only_refreshes_when_newly_acquired(self):
        for fresh in (False,True):
            g=self.game(hand=('draw',) if fresh else ('WW_823',),deck=('WW_823','plain'),mana=4)
            if fresh:self.play(g,'draw')
            self.play(g,'WW_823',self.hero(g));self.assertEqual(g.state.players[1].mana,4 if fresh else 2);self.check(g)

    def test_sunspot_damage_uses_lifesteal(self):
        self.spell('hurt',lambda c:[Damage(c.state.players[1].hero_id,10),AddToHand(1,'WW_434')])
        g=self.game(hand=('hurt',));self.play(g,'hurt');self.play(g,'WW_434',self.hero(g,2))
        self.assertEqual(g.state.entities[self.hero(g)].health,26);self.check(g)

    def test_conditional_targeting_for_finale_and_manathirst(self):
        for condition,keyword,fields in (('finale',Keyword.FINALE,{}),('manathirst',Keyword.MANATHIRST,{'manathirst':8})):
            self.spell(condition,lambda c:[Damage(c.target_id,1,c.source_id)] if c.target_id is not None else [],cost=1,keywords=(keyword,),target_condition=condition,requires_target=True,**fields)
        for card,fields,active in (('finale',{'mana':1},True),('finale',{'mana':2},False),('manathirst',{'max_mana':7,'mana':1},False),('manathirst',{'max_mana':8,'mana':1},True)):
            g=self.game(hand=(card,),**fields);self.play(g,card,self.hero(g,2) if active else None);self.check(g)

    def test_player_port_uses_same_quickdraw_targets(self):
        g=self.game(hand=('make',));self.play(g,'make');port=g.for_player(1);listing=port.legal_actions()
        ref=listing['observation']['players'][0]['hand'][0]['ref'];actions=[a for a in listing['actions'] if a['type']=='play_card' and a['card']==ref]
        self.assertTrue(actions);self.assertTrue(all(a.get('target') for a in actions));self.assertTrue(port.submit({'revision':listing['revision'],'action':actions[0]})['accepted']);self.check(g)

    def test_conditions_visible_only_to_hand_controller(self):
        g=self.game(hand=('make',));self.play(g,'make');own=g.observe(1)['players'][0]['hand'][0];enemy=g.observe(2)['players'][0]['hand'][0]
        self.assertTrue(own['play_conditions']['quickdraw']);self.assertNotIn('play_conditions',enemy)
        for key in ('hand_entry_id','hand_entries','mana_before','zone_epoch'):self.assertNotIn(key,json.dumps(g.observe(1)))
        self.check(g)

    def test_hidden_conditions_do_not_change_enemy_observation(self):
        games=[self.game(hand=(card,)) for card in ('WW_434','RLK_518')]
        self.assertEqual(games[0].observe(2),games[1].observe(2))

    def test_opening_mulligan_and_coin_predate_first_turn_draw(self):
        from opening_fixtures import registry,setup
        self.r=registry();g=Game.from_decks(setup(self.r,1,71),self.r)
        self.assertTrue(all(x.turn==0 for x in g.state.hand_entries));self.check(g)
        pending=g.state.pending_choice
        g.apply(SelectChoice(1,pending.id,(pending.options[0].id,)))
        self.check(g);g=Game.from_snapshot(g.snapshot(),self.r)
        g.apply(SelectChoice(2,g.state.pending_choice.id,()))
        entries=g.state.hand_entries;self.assertEqual(entries[-1].turn,1)
        self.assertEqual(entries[-1].reason,'draw');self.assertTrue(all(x.turn==0 for x in entries[:-1]))
        for player in g.state.players.values():
            fresh=[i for i in player.hand if preplay_conditions(g.state,g.state.entities[i],self.r)['quickdraw']]
            self.assertEqual(len(fresh),1 if player.id==1 else 0)
        self.check(g)

    def test_generated_acquisition_survives_pending_choice(self):
        self.spell('makechoice',lambda c:[AddToHand(1,'WW_434'),RequestChoice(1,(ChoiceOption('go','Go'),),c.source_id)])
        g=self.game(hand=('makechoice',));self.play(g,'makechoice');self.check(g);g=Game.from_snapshot(g.snapshot(),self.r)
        g.apply(SelectChoice(1,g.state.pending_choice.id,('go',)));self.play(g,'WW_434',self.hero(g,2));self.assertTrue(g.state.play_history[-1].quickdraw);self.check(g)

    def test_previous_snapshot_schema_is_rejected(self):
        g=self.game();data=g.snapshot();self.assertEqual(data['schema_version'],266);data['schema_version']=30
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_real_player_port_conditions_example(self):
        from examples.extra_play_conditions import run
        game,snapshot=run();self.assertEqual(len(game.history),8);self.assertEqual(snapshot['schema_version'],266)

    def test_finale_choice_saves_original_conditions(self):
        self.r.register_behavior('resume',lambda c:[GainArmor(c.player_id,3 if c.play.finale else 1)])
        from hs_sim.engine.effects import InvokeBehavior
        self.spell('choice',lambda c:[RequestChoice(1,(ChoiceOption('go','Go',(RefreshMana(1,10),InvokeBehavior('resume',c.source_id,c.player_id,play_id=c.play.id))),),c.source_id)],cost=2,keywords=(Keyword.FINALE,))
        g=self.game(hand=('choice',),mana=2);self.play(g,'choice');self.check(g);restored=Game.from_snapshot(g.snapshot(),self.r)
        for m in (g,restored):m.apply(SelectChoice(1,m.state.pending_choice.id,('go',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.state.entities[self.hero(g)].armor,3);self.check(g)

    def test_counterspell_suppresses_effect_but_preserves_conditions(self):
        g=self.game(hand=('RLK_843',),enemy_hand=('EX1_287',));g.apply(EndTurn(1));self.play(g,'EX1_287');g.apply(EndTurn(2))
        self.play(g,'RLK_843',self.hero(g,2));record=g.state.play_history[-1];self.assertTrue(record.countered and record.manathirst)
        self.assertEqual(g.state.entities[self.hero(g,2)].health,30);self.check(g)

    def test_rehashed_hand_history_corruption_rejected(self):
        g=self.game(hand=('make',));self.play(g,'make')
        for field,value in (('turn',99),('turn',True),('action',999),('zone_epoch',999),('player_id',2),('entity_id',999),('reason','imaginary')):
            data=g.snapshot();data['state']['hand_entries'][-1][field]=value;self.rehash(data)
            with self.subTest(field=field),self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_rehashed_play_condition_corruption_rejected(self):
        g=self.game(hand=('RLK_843',));self.play(g,'RLK_843',self.hero(g,2))
        for field,value in (('mana_after',20),('mana_before',True),('mana_crystals',-1),('hand_entry_id',999),('hand_entry_turn',1),('manathirst_threshold',7)):
            data=g.snapshot();data['state']['play_history'][0][field]=value;self.rehash(data)
            with self.subTest(field=field),self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def rehash(self,data):
        data['state_hash']=canonical_hash({k:v for k,v in data.items() if k not in ('schema_version','events','events_hash','state_hash')})

    def test_missing_or_boolean_acquisition_pointer_rejected(self):
        g=self.game(hand=('WW_434',));i=self.find(g,'WW_434')
        for value in (None,True,999):
            data=g.snapshot();data['state']['entities'][str(i)]['hand_entry_id']=value;self.rehash(data)
            with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_invalid_manathirst_definition_rejected(self):
        for threshold in (True,0,-1,'8'):
            with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','Bad',CardType.SPELL,keywords=(Keyword.MANATHIRST,),manathirst=threshold))
        with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','Bad',CardType.SPELL,keywords=(Keyword.MANATHIRST,)))

    def test_keywords_cannot_be_granted_as_fake_condition_mechanics(self):
        for keyword in (Keyword.FINALE,Keyword.MANATHIRST,Keyword.QUICKDRAW):
            name='grant_'+keyword.value;self.spell(name,lambda c,k=keyword:[GrantKeyword(c.state.players[1].board[0],k)])
        for keyword in (Keyword.FINALE,Keyword.MANATHIRST,Keyword.QUICKDRAW):
            g=self.game(hand=('grant_'+keyword.value,),board=('plain',));before=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,'grant_'+keyword.value)
            self.assertEqual(g.snapshot(),before)

    def test_real_metadata_and_zero_cost_are_explicit(self):
        self.assertEqual(self.r.card('WW_434').metadata.tribes,('dragon',))
        self.assertEqual({x.value for x in self.r.card('JAM_017').metadata.classes},{'warrior','demon_hunter'})
        self.assertEqual(self.r.card('JAM_017').cost,0)


if __name__=='__main__':unittest.main()
