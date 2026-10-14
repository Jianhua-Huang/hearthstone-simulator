"""Independent appendages, source paths and resumable entry sequencing."""
import json
import unittest

from hs_sim.engine import (AppendageSpec, CardDefinition, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError,
    SummonStoredCard, TriggerSpec, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage, DamageBatch,
    Destroy, GainArmor, GrantKeyword, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.model import Resource
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard


class ColossalTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        for name,a,h in (('plain',2,4),('left',1,2),('right',2,1)):
            self.r.register_card(CardDefinition(name,name,CardType.MINION,attack=a,health=h))
        self.body('body',(AppendageSpec('left','left'),AppendageSpec('right'),AppendageSpec('right')))
        for name,fn in (
            ('kill',lambda c:[Destroy(c.target_id)]),('silence',lambda c:[Silence(c.target_id)]),
            ('bounce',lambda c:[ReturnToHand(c.target_id)]),('copy',lambda c:[CopyMinion(c.target_id,1)]),
            ('basecopy',lambda c:[CopyMinion(c.target_id,1,mode='base')]),
            ('transform',lambda c:[Transform(c.target_id,'body')]),('plainform',lambda c:[Transform(c.target_id,'plain')]),
            ('steal',lambda c:[ChangeControl(c.target_id,2)]),
            ('buff',lambda c:[Buff(c.target_id,5,6)]),('hurt',lambda c:[Damage(c.target_id,6,c.source_id)]),
        ):self.spell(name,fn,requires_target=True)
        self.spell('summon',lambda c:[Summon(1,'body',0)])

    def body(self,name,spec,**fields):
        kw=fields.pop('keywords',())
        self.r.register_card(CardDefinition(name,name,CardType.MINION,attack=3,health=5,
            keywords=(Keyword.COLOSSAL,*kw),colossal=spec,**fields))

    def spell(self,name,fn,**fields):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,**fields))

    def game(self,hand=(),board=(),enemy_board=(),enemy_hand=(),**kw):
        defaults=dict(deck=('plain',)*12,max_mana=10,mana=10);defaults.update(kw)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=hand,board=board,**defaults),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy_board,deck=('plain',)*12,max_mana=10,mana=10)),seed=116),self.r)
    def find(self,g,card,player=1,zone='hand'):
        return next(i for i in getattr(g.state.players[player],zone) if g.state.entities[i].card_id==card)
    def play(self,g,card,target=None,position=None):
        player=g.state.active_player;i=self.find(g,card,player);g.apply(PlayCard(player,i,target,position));return i
    def board(self,g,player=1):return [g.state.entities[i].card_id for i in g.state.players[player].board]
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def check(self,g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r).snapshot(),g.snapshot())
        self.assertEqual(g.clone().snapshot(),g.snapshot());self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def test_hand_play_places_limbs_around_original_body(self):
        g=self.game(hand=('body',),board=('plain','plain'));i=self.play(g,'body',position=1)
        self.assertEqual(self.board(g),['plain','left','body','right','right','plain'])
        rec=g.state.colossal_history[0];self.assertEqual(rec.entity_id,i);self.assertTrue(rec.completed)
        self.assertEqual(rec.reason,'play');self.assertEqual(rec.attempted,3);self.check(g)

    def test_initial_scenario_is_existing_state_not_new_summon(self):
        g=self.game(board=('body',));self.assertEqual(self.board(g),['body']);self.assertEqual(g.state.colossal_history,[]);self.check(g)

    def test_each_appendage_is_independent_physical_entity(self):
        g=self.game(hand=('body',));i=self.play(g,'body');rec=g.state.colossal_history[0]
        self.assertEqual(len(set((i,*rec.limbs))),4)
        self.assertTrue(all(g.state.entities[j].owner==1 for j in rec.limbs));self.check(g)

    def test_full_board_rejects_body_without_consuming_it(self):
        g=self.game(hand=('body',),board=('plain',)*7);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'body')
        self.assertEqual(g.snapshot(),before)

    def test_one_slot_allows_body_and_records_failed_limbs(self):
        g=self.game(hand=('body',),board=('plain',)*6);self.play(g,'body')
        rec=g.state.colossal_history[0];self.assertEqual(rec.limbs,(None,None,None));self.assertEqual(rec.attempted,3)
        self.assertEqual(sum(e.kind=='summon_failed' for e in g.events),3);self.assertTrue(rec.completed);self.check(g)

    def test_partial_capacity_uses_declared_order(self):
        g=self.game(hand=('body',),board=('plain',)*4);self.play(g,'body')
        self.assertEqual(self.board(g)[-3:],['left','body','right']);rec=g.state.colossal_history[0]
        self.assertIsNone(rec.limbs[-1]);self.assertIsNotNone(rec.limbs[0]);self.check(g)

    def test_direct_summon_does_not_play_or_pay_for_limbs(self):
        g=self.game(hand=('summon',));self.play(g,'summon')
        self.assertEqual(self.board(g),['left','body','right','right']);self.assertEqual(len(g.state.play_history),1)
        self.assertEqual(g.state.players[1].mana,10);self.assertEqual(g.state.colossal_history[0].reason,'summon');self.check(g)

    def test_direct_summon_failure_does_not_create_history(self):
        g=self.game(hand=('summon',),board=('plain',)*7);self.play(g,'summon');self.assertEqual(g.state.colossal_history,[]);self.check(g)

    def stored(self,zone='hand',player=1):
        self.spell('pull',lambda c:[SummonStoredCard(CardReference.capture(c.state.entities[next(i for i in getattr(c.state.players[1],zone) if c.state.entities[i].card_id=='body')]),player,0)])

    def test_summon_from_hand_moves_same_entity_without_battlecry(self):
        self.stored();g=self.game(hand=('pull','body'));i=self.find(g,'body');self.play(g,'pull')
        self.assertEqual(g.state.colossal_history[0].entity_id,i);self.assertEqual(g.state.colossal_history[0].reason,'stored')
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(g.state.entities[i].zone,Zone.BOARD);self.check(g)

    def test_summon_from_deck_moves_same_entity_without_draw(self):
        self.stored('deck');g=self.game(hand=('pull',),deck=('body','plain'));i=self.find(g,'body',zone='deck');self.play(g,'pull')
        self.assertEqual(g.state.colossal_history[0].entity_id,i);self.assertNotIn('card_drawn',[e.kind for e in g.events]);self.check(g)

    def test_stored_summon_can_change_controller_and_preserve_owner(self):
        self.stored(player=2);g=self.game(hand=('pull','body'));i=self.find(g,'body');self.play(g,'pull')
        self.assertEqual((g.state.entities[i].owner,g.state.entities[i].controller),(1,2));self.assertEqual(self.board(g,2),['left','body','right','right']);self.check(g)

    def test_failed_stored_summon_preserves_hidden_card(self):
        self.stored();g=self.game(hand=('pull','body'),board=('plain',)*7);i=self.find(g,'body');self.play(g,'pull')
        self.assertEqual(g.state.entities[i].zone,Zone.HAND);self.assertEqual(g.state.colossal_history,[])
        self.assertNotIn('body',json.dumps(g.observe(2)));self.check(g)

    def test_copy_body_creates_fresh_limbs_not_copies_of_existing_ones(self):
        g=self.game(hand=('copy',),board=('body',));i=self.find(g,'body',zone='board');self.play(g,'copy',i)
        rec=g.state.colossal_history[0];self.assertEqual((rec.reason,rec.origin_id,rec.copy_mode),('copy',i,'current'))
        self.assertEqual(self.board(g),['body','left','body','right','right']);self.check(g)

    def test_copy_appendage_does_not_recreate_body(self):
        g=self.game(hand=('copy',),board=('TSC_639t',));self.play(g,'copy',g.state.players[1].board[0])
        self.assertEqual(self.board(g),['TSC_639t','TSC_639t']);self.assertEqual(g.state.colossal_history,[]);self.check(g)

    def test_silenced_current_copy_has_no_expansion(self):
        g=self.game(hand=('silence','copy'),board=('body',));i=g.state.players[1].board[0];self.play(g,'silence',i);self.play(g,'copy',i)
        self.assertEqual(self.board(g),['body','body']);self.assertEqual(g.state.colossal_history,[]);self.check(g)

    def test_base_copy_of_silenced_body_restores_expansion(self):
        g=self.game(hand=('silence','basecopy'),board=('body',));i=g.state.players[1].board[0];self.play(g,'silence',i);self.play(g,'basecopy',i)
        self.assertEqual(len(g.state.colossal_history),1);self.assertEqual(len(self.board(g)),5);self.check(g)

    def test_transform_into_colossal_keeps_id_and_creates_limbs(self):
        g=self.game(hand=('transform',),board=('plain',));i=g.state.players[1].board[0];self.play(g,'transform',i)
        self.assertEqual(g.state.colossal_history[0].entity_id,i);self.assertEqual(g.state.colossal_history[0].reason,'transform')
        self.assertEqual(sum(e.kind=='minion_summoned' for e in g.events),3);self.check(g)

    def test_transform_body_away_leaves_existing_appendages(self):
        g=self.game(hand=('body','plainform'));i=self.play(g,'body');limbs=g.state.colossal_history[0].limbs;self.play(g,'plainform',i)
        self.assertEqual(self.board(g),['left','plain','right','right']);self.assertTrue(all(j in g.state.players[1].board for j in limbs));self.check(g)

    def test_bounce_body_leaves_appendages_and_replay_creates_new_ones(self):
        g=self.game(hand=('body','bounce'));i=self.play(g,'body');first=g.state.colossal_history[0].limbs;self.play(g,'bounce',i);self.play(g,'body')
        self.assertEqual(len(g.state.colossal_history),2);self.assertTrue(set(first).isdisjoint(g.state.colossal_history[1].limbs));self.check(g)

    def test_death_of_body_does_not_kill_appendages(self):
        g=self.game(hand=('body','kill'));i=self.play(g,'body');self.play(g,'kill',i)
        self.assertEqual(self.board(g),['left','right','right']);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],1);self.check(g)

    def test_control_transfer_does_not_resummon_or_transfer_appendages(self):
        g=self.game(hand=('body','steal'));i=self.play(g,'body');self.play(g,'steal',i)
        self.assertEqual(self.board(g),['left','right','right']);self.assertEqual(self.board(g,2),['body']);self.assertEqual(len(g.state.colossal_history),1);self.check(g)

    def test_reborn_creates_one_health_body_and_fresh_full_health_limbs(self):
        self.body('reborn',(AppendageSpec('left'),),keywords=(Keyword.REBORN,))
        g=self.game(hand=('reborn','kill'));i=self.play(g,'reborn');self.play(g,'kill',i);rec=g.state.colossal_history[-1]
        self.assertEqual(rec.reason,'reborn');self.assertNotEqual(rec.entity_id,i)
        self.assertEqual(g.state.entities[rec.entity_id].health,1);self.assertEqual(g.state.entities[rec.limbs[0]].health,2);self.check(g)

    def test_silence_body_does_not_silence_appendages(self):
        g=self.game(hand=('TSC_639','silence'));i=self.play(g,'TSC_639');self.play(g,'silence',i)
        self.assertTrue(all(Keyword.TAUNT in g.state.entities[j].keywords for j in g.state.colossal_history[0].limbs));self.check(g)

    def watcher(self,name,fn):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.MINION,health=3,triggers=(TriggerSpec('minion_summoned',name),)))

    def test_limb_death_can_free_space_for_next_limb(self):
        self.watcher('pop',lambda c:[Destroy(c.target_id)] if c.state.entities[c.target_id].card_id in ('left','right') else [])
        g=self.game(hand=('body',),board=('pop',)+('plain',)*4);self.play(g,'body');rec=g.state.colossal_history[0]
        self.assertTrue(all(i is not None for i in rec.limbs));self.assertEqual(len(g.state.death_history),3);self.check(g)

    def test_choice_between_limbs_saves_exact_remaining_sequence(self):
        self.watcher('pause',lambda c:[RequestChoice(1,(ChoiceOption('go','Go'),),c.source_id)] if c.state.entities[c.target_id].card_id=='left' else [])
        g=self.game(hand=('body',),board=('pause',));self.play(g,'body');self.assertEqual(g.state.colossal_history[0].attempted,1)
        self.assertFalse(g.state.colossal_history[0].completed);self.check(g);restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):match.apply(SelectChoice(1,match.state.pending_choice.id,('go',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertTrue(g.state.colossal_history[0].completed);self.check(g)

    def test_body_removed_between_limbs_cancels_remaining_expansion(self):
        self.watcher('removebody',lambda c:[ReturnToHand(next(i for i in c.state.players[1].board if c.state.entities[i].card_id=='body'))] if c.state.entities[c.target_id].card_id=='left' else [])
        g=self.game(hand=('body',),board=('removebody',));self.play(g,'body');rec=g.state.colossal_history[0]
        self.assertTrue(rec.canceled and rec.completed);self.assertEqual(rec.attempted,1);self.assertEqual(self.board(g),['removebody','left']);self.check(g)

    def test_battlecry_observes_completed_appendage_board(self):
        self.r.register_behavior('count',lambda c:[GainArmor(1,len(c.state.players[1].board))])
        self.body('count',(AppendageSpec('left'),AppendageSpec('right')),on_play='count')
        g=self.game(hand=('count',));self.play(g,'count');self.assertEqual(self.hero(g).armor,3);self.check(g)

    def test_limb_summon_events_precede_body_event(self):
        g=self.game(hand=('body',));i=self.play(g,'body');rec=g.state.colossal_history[0]
        self.assertEqual([e.target_id for e in g.events if e.kind=='minion_summoned'],[*rec.limbs,i]);self.check(g)

    def test_spawned_limbs_do_not_execute_their_battlecry(self):
        self.r.register_behavior('armor',lambda c:[GainArmor(1,9)])
        self.r.register_card(CardDefinition('limbcry','Limb',CardType.MINION,health=1,on_play='armor'))
        self.body('cry',(AppendageSpec('limbcry'),));g=self.game(hand=('cry',));self.play(g,'cry');self.assertEqual(self.hero(g).armor,0);self.check(g)

    def test_engineering_budget_failure_rolls_back_all_spawned_entities(self):
        from hs_sim.engine import Ruleset, ResolutionLimitExceeded
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=('body',)),PlayerSetup('HERO_08'))),self.r,Ruleset(max_resolution_steps=2))
        before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g,'body')
        self.assertEqual(g.snapshot(),before)

    def test_trigger_failure_rolls_back_history_and_allocation(self):
        def fail(c):raise ResolutionError('intentional appendage failure')
        self.watcher('fail',fail);g=self.game(hand=('body',),board=('fail',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'body')
        self.assertEqual(g.snapshot(),before)

    def test_terminal_during_expansion_closes_pending_record(self):
        self.watcher('lethal',lambda c:[Damage(c.state.players[2].hero_id,50,c.source_id)] if c.state.entities[c.target_id].card_id=='left' else [])
        g=self.game(hand=('body',),board=('lethal',));self.play(g,'body');self.assertEqual(g.state.status,'finished')
        self.assertTrue(g.state.colossal_history[0].canceled);self.check(g)

    def test_glugg_gains_printed_stats_not_current_buffs(self):
        g=self.game(hand=('TSC_639','buff','kill'));i=self.play(g,'TSC_639');tail=g.state.colossal_history[0].limbs[0]
        self.play(g,'buff',tail);self.play(g,'kill',tail);e=g.state.entities[i]
        self.assertEqual((e.attack,e.health),(5,7));self.check(g)

    def test_glugg_does_not_gain_enemy_death_stats(self):
        g=self.game(hand=('TSC_639','kill'),enemy_board=('plain',));i=self.play(g,'TSC_639');self.play(g,'kill',g.state.players[2].board[0])
        self.assertEqual(g.state.entities[i].attack,3);self.check(g)

    def test_ozumat_has_six_distinct_pinned_tentacle_definitions(self):
        g=self.game(hand=('TID_711',));self.play(g,'TID_711');limbs=g.state.colossal_history[0].limbs
        self.assertEqual(len({g.state.entities[i].card_id for i in limbs}),6);self.assertEqual(len(self.board(g)),7);self.check(g)

    def test_ozumat_deathrattle_counts_current_friendly_tentacles(self):
        g=self.game(hand=('TID_711','kill'),board=('plain',)*4,enemy_board=('plain',)*4);i=self.play(g,'TID_711');self.play(g,'kill',i)
        self.assertEqual(len(self.board(g,2)),2);self.check(g)

    def test_ozumat_simultaneous_dead_tentacles_do_not_count(self):
        self.spell('clear',lambda c:[DamageBatch(tuple(Damage(i,99,c.source_id) for i in c.state.players[1].board))])
        g=self.game(hand=('TID_711','clear'),enemy_board=('plain',)*2);self.play(g,'TID_711');self.play(g,'clear')
        self.assertEqual(len(self.board(g,2)),2);self.check(g)

    def test_ozumat_each_destruction_queries_current_enemy_board(self):
        self.r.register_behavior('hatch',lambda c:[Summon(c.player_id,'plain')])
        self.r.register_card(CardDefinition('egg','Egg',CardType.MINION,health=1,deathrattle='hatch'))
        g=self.game(hand=('TID_711','kill'),board=('plain',)*4,enemy_board=('egg',))
        i=self.play(g,'TID_711');self.play(g,'kill',i)
        self.assertEqual(self.board(g,2),[]);self.check(g)

    def test_lure_on_left_forces_enemy_attack_and_lifesteal(self):
        g=self.game(hand=('hurt','TSC_216'),enemy_board=('plain',));self.play(g,'hurt',self.hero(g).id);i=self.play(g,'TSC_216')
        self.assertEqual(self.board(g),['TSC_216t','TSC_216']);g.apply(EndTurn(1))
        self.assertEqual(self.board(g,2),[]);self.assertEqual(g.state.entities[i].health,8);self.assertEqual(self.hero(g).health,30);self.check(g)

    def test_lure_without_friendly_behemoth_does_nothing(self):
        g=self.game(board=('TSC_216t',),enemy_board=('plain',));g.apply(EndTurn(1));self.assertEqual(self.board(g,2),['plain']);self.check(g)

    def test_lure_ignores_enemy_behemoth_as_defender(self):
        g=self.game(board=('TSC_216t',),enemy_board=('TSC_216','plain'));g.apply(EndTurn(1));self.assertEqual(len(self.board(g,2)),2);self.check(g)

    def test_player_port_and_hidden_hand_isolation(self):
        a=self.game(hand=('TSC_216',));b=self.game(hand=('TSC_639',));self.assertEqual(a.observe(2),b.observe(2))
        self.assertEqual(a.observe(1)['players'][0]['hand'][0]['colossal_appendages'],[{'card_id':'TSC_216t','side':'left'}])
        port=a.for_player(1);listing=port.legal_actions();action=next(x for x in listing['actions'] if x['type']=='play_card')
        self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted']);self.assertEqual(self.board(a),['TSC_216t','TSC_216']);self.check(a)

    def rehash(self,data):
        data['state_hash']=canonical_hash({k:v for k,v in data.items() if k not in ('schema_version','events','events_hash','state_hash')})

    def test_rehashed_invalid_history_rejected(self):
        g=self.game(hand=('body',));self.play(g,'body')
        for field,value in (('id',2),('entity_id',9999),('card_id','plain'),('player_id',True),('turn',99),('action',99),('attempted',0),('limbs',[None]),('completed',False),('origin_id',1)):
            data=g.snapshot();data['state']['colossal_history'][0][field]=value;self.rehash(data)
            with self.subTest(field=field),self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_pending_expansion_cannot_drop_its_remaining_work(self):
        self.watcher('pause',lambda c:[RequestChoice(1,(ChoiceOption('go','Go'),),c.source_id)] if c.state.entities[c.target_id].card_id=='left' else [])
        g=self.game(hand=('body',),board=('pause',));self.play(g,'body');data=g.snapshot()
        def strip(value):
            if isinstance(value,dict):
                for k,v in list(value.items()):
                    if isinstance(v,list):value[k]=[strip(x) for x in v if not (isinstance(x,dict) and 'SummonAppendage' in str(x.get('type','')))]
                    elif isinstance(v,dict):strip(v)
            return value
        strip(data['resolution_frame']);self.rehash(data)
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_previous_snapshot_schema_rejected(self):
        g=self.game();data=g.snapshot();data['schema_version']=32
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_invalid_definition_rejected(self):
        for spec,kw in (((),(Keyword.COLOSSAL,)),((AppendageSpec('left'),),()),(['left'],(Keyword.COLOSSAL,))):
            with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','Bad',CardType.MINION,health=1,colossal=spec,keywords=kw))
        with self.assertRaises(ValueError):AppendageSpec('left','middle')

    def test_unknown_or_recursive_appendages_rejected_when_registry_frozen(self):
        for card in ('missing','body'):
            self.r=build_registry();self.body('body',(AppendageSpec(card),))
            with self.assertRaises(ValueError):self.game()

    def test_keyword_cannot_be_granted_without_appendage_contract(self):
        self.spell('grant',lambda c:[GrantKeyword(c.state.players[1].board[0],Keyword.COLOSSAL)])
        g=self.game(hand=('grant',),board=('plain',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'grant')
        self.assertEqual(g.snapshot(),before)

    def test_stored_reference_does_not_hit_returned_card(self):
        from hs_sim.engine.zones import MoveCard
        def stale(c):
            e=c.state.entities[next(i for i in c.state.players[1].hand if c.state.entities[i].card_id=='body')]
            ref=CardReference.capture(e)
            return [MoveCard(ref,1,Zone.DECK),SummonStoredCard(ref,1)]
        self.spell('stale',stale);g=self.game(hand=('stale','body'));self.play(g,'stale');self.assertEqual(self.board(g),[]);self.check(g)

    def test_stored_summon_preserves_hand_stats_without_copying_to_limbs(self):
        from hs_sim.engine.hand_upgrades import BuffStoredCard
        def buffpull(c):
            e=c.state.entities[next(i for i in c.state.players[1].hand if c.state.entities[i].card_id=='body')]
            ref=CardReference.capture(e);return [BuffStoredCard(ref,5,6),SummonStoredCard(ref,1)]
        self.spell('buffpull',buffpull);g=self.game(hand=('buffpull','body'));self.play(g,'buffpull');rec=g.state.colossal_history[0]
        self.assertEqual(g.state.entities[rec.entity_id].attack,8);self.assertEqual(g.state.entities[rec.limbs[0]].attack,1);self.check(g)

    def test_random_forced_combat_seed_replays_multiple_candidates(self):
        g=self.game(hand=('TSC_216',),enemy_board=('plain','plain'));self.play(g,'TSC_216');g.apply(EndTurn(1))
        self.assertEqual(len(self.board(g,2)),1);self.check(g)

    def test_real_player_port_example(self):
        from examples.colossal_appendages import run
        game,snapshot=run();self.assertEqual(len(game.history),5);self.assertEqual(snapshot['schema_version'],265)


if __name__=='__main__':unittest.main()
