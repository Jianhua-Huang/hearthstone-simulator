"""Cost extrema, stable resurrection subjects and guarded follow-ups (R-096)."""
from dataclasses import replace
import unittest

from hs_sim.engine import (AppendageSpec, BuffCapturedMinion, CardDefinition, CardType,
    DeathQuery, EndTurn, Game, GrantCapturedKeyword, Keyword, MinionReference, PlayCard,
    PlayerSetup, PoolQuery, ResolutionError, Resurrect, ResurrectMinion, Scenario,
    SelectChoice, SnapshotError, SummonStats, TriggerSpec, Zone, death_candidates)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, GainArmor, GrantKeyword, ModifyCost, RequestChoice, ReturnToHand, Silence,
    Summon, Transform, InvokeBehavior)
from hs_sim.engine.model import CardClass, CardMetadata, CostSpec, SpellRepeatSpec, RewindSpec
from hs_sim.engine.registry import Registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_sources import ContinueResurrectedMinion


class ResurrectionFollowupTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('resurrection-followup-tests-v1')
        self.r.register_card(CardDefinition('hero','hero',CardType.HERO,health=30,
            metadata=CardMetadata(False,(CardClass.WARRIOR,),None)))
        for name,cost in (('a',1),('b',5),('c',5),('high',9)):
            self.minion(name,cost=cost,attack=2,health=3)
        self.spell('kill',lambda c:[Destroy(c.target_id)],requires_target=True)
        self.spell('nothing',lambda c:[])
        self.r.register_behavior('enhance',self.enhance)
        self.revive('revive')

    def minion(self,name,**kw):
        self.r.register_card(CardDefinition(name,name,CardType.MINION,
            metadata=CardMetadata(False,(CardClass.NEUTRAL,),None),**kw))
    def spell(self,name,fn,**kw):
        self.r.register_behavior('spell.'+name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play='spell.'+name,**kw))
    def revive(self,name,**kw):
        self.spell(name,lambda c:[Resurrect(1,source_id=c.source_id,on_summon='enhance',**kw)])
    def enhance(self,c):
        ref=MinionReference.capture(c.state.entities[c.target_id])
        return [BuffCapturedMinion(ref,2,2,c.source_id),GrantCapturedKeyword(ref,Keyword.REBORN,c.source_id),
            GrantCapturedKeyword(ref,Keyword.LIFESTEAL,c.source_id)]
    def watch(self,name,fn,event='minion_summoned'):
        self.r.register_behavior(name,fn)
        self.minion(name,health=3,triggers=(TriggerSpec(event,name),))
    def game(self,dead=('b',),hand=('revive',),board=(),enemy=(),seed=56):
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('kill',)*len(dead)+hand,
            board=dead+board,deck=('nothing',)*4,mana=10,max_mana=10),
            PlayerSetup('hero',board=enemy,deck=('nothing',)*4)),seed=seed),self.r)
        for name in dead:self.play(g,'kill',self.find(g,name,'board'))
        return g
    def find(self,g,name,zone='hand',player=1):
        return next(i for i in getattr(g.state.players[player],zone) if g.state.entities[i].card_id==name)
    def play(self,g,name='revive',target=None):
        eid=self.find(g,name);g.apply(PlayCard(1,eid,target));return eid
    def body(self,g,index=-1):return g.state.entities[g.state.resurrection_history[index].entity_id]
    def check(self,g):
        snap=g.snapshot();self.assertEqual(Game.from_snapshot(snap,self.r).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),snap)
    def candidates(self,g,**kw):return [d.card_id for d in death_candidates(g.state,self.r,1,DeathQuery(**kw))]

    def test_highest_preserves_all_tied_physical_deaths(self):
        g=self.game(dead=('a','b','c','b'))
        self.assertEqual(self.candidates(g,cost_extreme='highest'),['b','c','b']);self.check(g)

    def test_lowest_includes_zero_cost_deaths(self):
        self.minion('zero',cost=0,health=1);g=self.game(dead=('zero','a','b'))
        self.assertEqual(self.candidates(g,cost_extreme='lowest'),['zero'])

    def test_extreme_applies_after_query_filter(self):
        g=self.game(dead=('a','b','high'))
        self.assertEqual(self.candidates(g,cost_extreme='highest',cards=PoolQuery(max_cost=5)),['b'])

    def test_empty_extreme_is_empty_and_consumes_no_rng(self):
        self.revive('highest',query=DeathQuery(cost_extreme='highest'));g=self.game(dead=(),hand=('highest',))
        before=g.snapshot()['rng_state'];self.play(g,'highest')
        self.assertFalse(g.state.resurrection_history);self.assertEqual(g.snapshot()['rng_state'],before);self.check(g)

    def test_cost_basis_distinguishes_printed_from_captured_local_cost(self):
        self.spell('prepare',lambda c:[ModifyCost(c.target_id,CostSpec(set_to=0))],requires_target=True)
        g=self.game(dead=(),hand=('prepare','kill','kill'),board=('a','b'))
        b=self.find(g,'b','board');self.play(g,'prepare',b);self.play(g,'kill',b);self.play(g,'kill',self.find(g,'a','board'))
        self.assertEqual(self.candidates(g,cost_extreme='highest'),['b'])
        self.assertEqual(self.candidates(g,cost_extreme='highest',cost_basis='local_at_death'),['a'])
        self.assertEqual(self.candidates(g,cost_basis='local_at_death',cards=PoolQuery(max_cost=0)),['b']);self.check(g)

    def test_death_cost_uses_immutable_record_after_graveyard_entity_changes(self):
        # The host copy is detached: neither mutation nor current graveyard data defines history cost.
        g=self.game(dead=('a','b'));state=g.state;state.entities[state.death_history[0].entity_id].base_cost=99
        self.assertEqual([d.card_id for d in death_candidates(state,self.r,1,DeathQuery(cost_extreme='highest',cost_basis='local_at_death'))],['b'])

    def test_friendly_extreme_ignores_expensive_enemy_death(self):
        g=self.game(dead=('a',),hand=('kill','revive'),enemy=('high',));self.play(g,'kill',self.find(g,'high','board',2))
        self.assertEqual(self.candidates(g,cost_extreme='highest'),['a'])
        self.assertEqual(self.candidates(g,cost_extreme='highest',side='both'),['high'])

    def test_highest_batch_keeps_frozen_maximum_not_descending_lower_costs(self):
        self.revive('many',count=4,query=DeathQuery(cost_extreme='highest'),selection='first')
        g=self.game(dead=('a','b','c'),hand=('many',));self.play(g,'many')
        self.assertEqual([self.r.card(g.state.entities[x.entity_id].card_id).cost for x in g.state.resurrection_history],[5,5]);self.check(g)

    def test_distinct_card_deduplicates_only_after_cost_filter(self):
        self.revive('many',count=4,distinct='card',query=DeathQuery(cost_extreme='highest'),selection='first')
        g=self.game(dead=('b','b','c'),hand=('many',));self.play(g,'many')
        self.assertEqual([self.body(g,n).card_id for n in range(2)],['b','c']);self.check(g)

    def test_ties_are_seeded_and_each_tied_candidate_is_reachable(self):
        self.revive('highest',query=DeathQuery(cost_extreme='highest'))
        seen=set()
        for seed in range(12):
            g=self.game(dead=('a','b','c'),hand=('highest',),seed=seed);self.play(g,'highest');seen.add(self.body(g).card_id)
            if seed==0:self.check(g)
        self.assertEqual(seen,{'b','c'})

    def test_callback_buffs_only_successful_subject(self):
        g=self.game(board=('a',));self.play(g)
        e=self.body(g);self.assertEqual((e.attack,e.health),(4,5))
        self.assertTrue({Keyword.REBORN,Keyword.LIFESTEAL}<=e.keywords)
        self.assertEqual(g.state.entities[self.find(g,'a','board')].attack,2);self.check(g)

    def test_full_board_never_runs_callback(self):
        self.spell('fill',lambda c:[Summon(1,'a')]);g=self.game(hand=('fill','revive'),board=('a',)*6)
        self.play(g,'fill');before=g.snapshot()['rng_state'];self.play(g)
        self.assertFalse(g.state.resurrection_history);self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertTrue(all(not g.state.entities[i].keywords for i in g.state.players[1].board));self.check(g)

    def test_direct_resurrection_has_same_followup(self):
        self.spell('direct',lambda c:[ResurrectMinion(1,1,source_id=c.source_id,on_summon='enhance')])
        g=self.game(hand=('direct',));self.play(g,'direct');self.assertEqual(self.body(g).health,5);self.check(g)

    def test_callback_follows_summon_reaction_and_receives_original_death(self):
        self.watch('watch',lambda c:[GainArmor(1,c.state.entities[c.target_id].attack)])
        self.r.register_behavior('inspect',lambda c:[GainArmor(1,c.death.base_cost+c.state.entities[c.state.players[1].hero_id].armor)])
        self.spell('inspect',lambda c:[Resurrect(1,on_summon='inspect')])
        g=self.game(hand=('inspect',),board=('watch',));self.play(g,'inspect')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,9);self.check(g)

    def test_nested_resurrection_does_not_replace_outer_subject(self):
        self.watch('watch',lambda c:[ResurrectMinion(1,1)] if len(c.state.resurrection_history)==1 else [])
        g=self.game(board=('watch',));self.play(g)
        self.assertEqual([self.body(g,n).attack for n in range(2)],[4,2]);self.check(g)

    def test_colossal_callback_targets_body_after_appendages(self):
        self.minion('limb',health=1);self.minion('big',health=3,attack=4,
            keywords=(Keyword.COLOSSAL,),colossal=(AppendageSpec('limb'),))
        g=self.game(dead=('big',));self.play(g)
        self.assertEqual((self.body(g).attack,self.body(g).health),(6,5))
        self.assertNotIn(Keyword.REBORN,g.state.entities[self.find(g,'limb','board')].keywords);self.check(g)

    def test_transformed_subject_is_not_enhanced(self):
        self.watch('watch',lambda c:[Transform(c.target_id,'a')])
        g=self.game(board=('watch',));self.play(g)
        self.assertEqual((self.body(g).card_id,self.body(g).attack),('a',2));self.assertFalse(self.body(g).keywords);self.check(g)

    def test_control_changed_subject_is_not_enhanced(self):
        self.watch('watch',lambda c:[ChangeControl(c.target_id,2)])
        g=self.game(board=('watch',));self.play(g)
        self.assertEqual(self.body(g).controller,2);self.assertFalse(self.body(g).keywords);self.check(g)

    def test_transfer_away_and_back_keeps_history_but_invalidates_followup(self):
        self.watch('watch',lambda c:[ChangeControl(c.target_id,2),ChangeControl(c.target_id,1)])
        g=self.game(board=('watch',));self.play(g)
        self.assertEqual(self.body(g).controller,1);self.assertFalse(self.body(g).keywords);self.check(g)

    def test_resurrection_entry_provenance_is_required_in_snapshot(self):
        g=self.game();self.play(g)
        for field,value in (('entered_order',0),('entered_order',9999),('zone_epoch',1)):
            snap=g.snapshot();snap['state']['resurrection_history'][0][field]=value
            with self.assertRaises(SnapshotError):Game.from_snapshot(snap,self.r)
        snap=g.snapshot();del snap['state']['resurrection_history'][0]['entered_order']
        with self.assertRaises(SnapshotError):Game.from_snapshot(snap,self.r)

    def test_returned_and_resummoned_original_id_does_not_match_old_entry(self):
        from hs_sim.engine import SummonFromZone
        self.watch('watch',lambda c:[ReturnToHand(c.target_id),SummonFromZone(1,zone=Zone.HAND)]
            if 'resurrected_from' in dict(c.event.data) else [])
        g=self.game(board=('watch',));self.play(g)
        self.assertEqual(self.body(g).zone,Zone.BOARD);self.assertEqual(self.body(g).attack,2);self.assertFalse(self.body(g).keywords);self.check(g)

    def test_killed_subject_does_not_receive_callback(self):
        self.watch('watch',lambda c:[Destroy(c.target_id)])
        g=self.game(board=('watch',));self.play(g)
        self.assertEqual(self.body(g).zone,Zone.GRAVEYARD);self.assertFalse(self.body(g).keywords);self.check(g)

    def test_source_death_does_not_cancel_successful_followup(self):
        self.r.register_behavior('cry',lambda c:[Resurrect(1,source_id=c.source_id,on_summon='enhance')])
        self.minion('cry',health=2,on_play='cry')
        self.watch('watch',lambda c:[Destroy(next(x.source_id for x in c.state.resurrection_history if x.entity_id==c.target_id))]
            if 'resurrected_from' in dict(c.event.data) else [])
        g=self.game(hand=('cry',),board=('watch',));source=self.play(g,'cry')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.body(g).attack,4);self.check(g)

    def test_silence_between_buff_and_keywords_keeps_same_subject(self):
        self.watch('watch',lambda c:[Silence(c.target_id)],event='stats_changed')
        g=self.game(board=('watch',));self.play(g)
        self.assertEqual(self.body(g).attack,2);self.assertTrue({Keyword.REBORN,Keyword.LIFESTEAL}<=self.body(g).keywords);self.check(g)

    def test_transform_between_buff_and_keywords_cancels_keyword_grants(self):
        self.watch('watch',lambda c:[Transform(c.target_id,'a')],event='stats_changed')
        g=self.game(board=('watch',));self.play(g)
        self.assertEqual(self.body(g).card_id,'a');self.assertFalse(self.body(g).keywords);self.check(g)

    def test_silence_removes_added_buff_and_keywords(self):
        self.spell('silence',lambda c:[Silence(c.target_id)],requires_target=True)
        g=self.game(hand=('revive','silence'));self.play(g);self.play(g,'silence',self.body(g).id)
        self.assertEqual((self.body(g).attack,self.body(g).health),(2,3));self.assertFalse(self.body(g).keywords);self.check(g)

    def test_return_to_hand_resets_followup_enhancement(self):
        self.spell('bounce',lambda c:[ReturnToHand(c.target_id)],requires_target=True)
        g=self.game(hand=('revive','bounce'));self.play(g);self.play(g,'bounce',self.body(g).id)
        self.assertEqual((self.body(g).zone,self.body(g).attack),(Zone.HAND,2));self.assertFalse(self.body(g).keywords);self.check(g)

    def test_current_copy_keeps_keywords_base_copy_does_not(self):
        self.spell('copy',lambda c:[CopyMinion(c.target_id,1),CopyMinion(c.target_id,1,mode='base')],requires_target=True)
        g=self.game(hand=('revive','copy'));self.play(g);self.play(g,'copy',self.body(g).id)
        bodies=[g.state.entities[i] for i in g.state.players[1].board]
        self.assertIn(Keyword.REBORN,bodies[1].keywords);self.assertFalse(bodies[2].keywords);self.check(g)

    def test_death_after_grant_reborn_creates_base_one_health_entity(self):
        g=self.game(hand=('revive','kill'));self.play(g);eid=self.body(g).id;self.play(g,'kill',eid)
        reborn=g.state.entities[g.state.players[1].board[0]]
        self.assertEqual((reborn.attack,reborn.health),(2,1));self.assertFalse(reborn.keywords);self.check(g)

    def test_lifesteal_uses_new_entity_source(self):
        self.spell('hurt',lambda c:[Damage(c.state.players[1].hero_id,5),Damage(c.state.players[2].hero_id,2,c.target_id)],requires_target=True)
        g=self.game(hand=('revive','hurt'));self.play(g);self.play(g,'hurt',self.body(g).id)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27);self.check(g)

    def test_choice_during_summon_restores_guarded_pending_subject(self):
        self.watch('watch',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',()),),c.source_id)])
        g=self.game(board=('watch',));self.play(g);self.check(g)
        ch=g.state.pending_choice;restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):match.apply(SelectChoice(1,ch.id,('ok',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.body(g).attack,4);self.check(g)

    def test_choice_in_callback_restores_guarded_keyword(self):
        def choice(c):
            ref=MinionReference.capture(c.state.entities[c.target_id])
            return [RequestChoice(1,(ChoiceOption('ok','ok',(GrantCapturedKeyword(ref,Keyword.REBORN,c.source_id),)),),c.source_id)]
        self.r.register_behavior('choose',choice);self.spell('choose',lambda c:[Resurrect(1,on_summon='choose')])
        g=self.game(hand=('choose',));self.play(g,'choose');self.check(g)
        ch=g.state.pending_choice;g.apply(SelectChoice(1,ch.id,('ok',)))
        self.assertIn(Keyword.REBORN,self.body(g).keywords);self.check(g)

    def test_unsupported_callback_rejected_even_empty_zero_or_full(self):
        for name,count in (('bad',1),('zero',0)):
            self.spell(name,lambda c,n=count:[Resurrect(1,count=n,on_summon='missing')])
        g=self.game(dead=(),hand=('bad','zero'),board=('a',)*7)
        for name in ('bad','zero'):
            snap=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,name)
            self.assertEqual(g.snapshot(),snap)

    def test_callback_error_rolls_back_subject_and_randomness(self):
        self.r.register_behavior('bad',lambda c:[GainArmor(1,-1)])
        self.spell('bad',lambda c:[Resurrect(1,on_summon='bad')]);g=self.game(dead=('b','c'),hand=('bad',));snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),snap)

    def test_unknown_callback_in_saved_followup_is_rejected(self):
        self.watch('watch',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',()),),c.source_id)])
        g=self.game(board=('watch',));self.play(g);snap=g.snapshot()
        def corrupt(value):
            if isinstance(value,dict):
                if value.get('type','').endswith('.ContinueResurrectedMinion'):value['fields']['behavior_id']='missing'
                for item in value.values():corrupt(item)
            elif isinstance(value,list):
                for item in value:corrupt(item)
        corrupt(snap)
        with self.assertRaises(SnapshotError):Game.from_snapshot(snap,self.r)

    def test_nonexistent_successful_resurrection_cannot_invoke_callback(self):
        self.spell('bad',lambda c:[ContinueResurrectedMinion(999,MinionReference.capture(c.state.entities[c.state.players[1].board[0]]),'enhance')])
        g=self.game(dead=(),hand=('bad',),board=('a',));snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),snap)

    def test_followup_choice_failure_keeps_committed_resurrection(self):
        self.r.register_behavior('failure',lambda c:[GainArmor(1,-1)])
        self.r.register_behavior('choice_bad',lambda c:[RequestChoice(1,(ChoiceOption('bad','bad',(InvokeBehavior('failure',c.source_id,1),)),),c.source_id)])
        self.spell('bad',lambda c:[Resurrect(1,on_summon='choice_bad')]);g=self.game(hand=('bad',));self.play(g,'bad');snap=g.snapshot()
        ch=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,ch.id,('bad',)))
        self.assertEqual(g.snapshot(),snap);self.assertEqual(len(g.state.resurrection_history),1)

    def test_automatic_spell_cast_preserves_followup(self):
        from hs_sim.engine import CastSpell
        self.spell('auto',lambda c:[CastSpell(1,'revive',c.source_id)])
        g=self.game(hand=('auto',));self.play(g,'auto');self.assertEqual(self.body(g).attack,4);self.check(g)

    def test_rewind_retries_replace_resurrection_and_callback_results(self):
        self.spell('rewind',lambda c:[Resurrect(1,on_summon='enhance')],keywords=(Keyword.REWIND,),rewind=RewindSpec())
        g=self.game(hand=('rewind',));self.play(g,'rewind');ch=g.state.pending_choice
        g.apply(SelectChoice(1,ch.id,(next(o.id for o in ch.options if 'retry' in o.id),)))
        self.assertEqual(len(g.state.resurrection_history),1);self.assertEqual(self.body(g).attack,4);self.check(g)

    def test_public_observation_excludes_death_and_callback_internals(self):
        g=self.game();port=g.for_player(1);listing=port.legal_actions()
        action=next(a for a in listing['actions'] if a['type']=='play_card');self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        for viewer in (1,2):
            row=next(e for e in g.player_events(viewer) if e['kind']=='minion_resurrected')
            self.assertEqual(row['target']['card_id'],'b');self.assertNotIn('resurrection_id',row)
            self.assertNotIn('resurrection_history',g.observe(viewer))
        self.check(g)

    def test_invalid_extreme_basis_callbacks_and_guarded_keywords(self):
        for kw in ({'cost_extreme':'biggest'},{'cost_extreme':True},{'cost_basis':'paid'},{'cost_basis':None}):
            with self.assertRaises(ValueError):DeathQuery(**kw)
        for cls in (Resurrect,ResurrectMinion):
            for value in ('',False,{}):
                with self.assertRaises(ValueError):cls(1,1,on_summon=value)
        with self.assertRaises(ValueError):GrantCapturedKeyword(MinionReference(1,1,'a',0,1),'reborn')

    def test_corrupt_pending_resurrection_subject_and_origin_rejected_on_load(self):
        self.watch('watch',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',()),),c.source_id)])
        g=self.game(board=('watch',));self.play(g)
        def followup(value):
            if isinstance(value,dict):
                if value.get('type','').endswith('.ContinueResurrectedMinion'):return value['fields']
                for child in value.values():
                    result=followup(child)
                    if result is not None:return result
            if isinstance(value,list):
                for child in value:
                    result=followup(child)
                    if result is not None:return result
        for field,value in (('resurrection_id',999),('entity_id',g.state.players[1].hero_id),('player_id',2),
                ('card_id','a'),('zone_epoch',1),('entered_order',1)):
            snap=g.snapshot();fields=followup(snap);self.assertIsNotNone(fields)
            if field=='resurrection_id':fields[field]=value
            else:fields['beneficiary']['fields'][field]=value
            with self.subTest(field=field),self.assertRaises(SnapshotError):Game.from_snapshot(snap,self.r)

    def test_frozen_highest_batch_and_callback_survive_multiple_choices(self):
        self.watch('watch',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',()),),c.source_id)])
        self.revive('many',count=3,query=DeathQuery(cost_extreme='highest'),selection='first')
        g=self.game(dead=('a','b','c'),hand=('many',),board=('watch',));self.play(g,'many')
        while g.state.pending_choice:
            self.check(g);ch=g.state.pending_choice;g=Game.from_snapshot(g.snapshot(),self.r)
            g.apply(SelectChoice(1,ch.id,('ok',)))
        self.assertEqual([self.body(g,n).attack for n in range(2)],[4,4]);self.check(g)

    def test_guarded_keyword_expiry_removes_only_temporary_grant(self):
        self.r.register_behavior('temporary',lambda c:[GrantCapturedKeyword(
            MinionReference.capture(c.state.entities[c.target_id]),Keyword.TAUNT,c.source_id,c.state.turn)])
        self.spell('temporary',lambda c:[Resurrect(1,on_summon='temporary')])
        g=self.game(hand=('temporary',));self.play(g,'temporary');self.assertIn(Keyword.TAUNT,self.body(g).keywords)
        g.apply(EndTurn(1));self.assertNotIn(Keyword.TAUNT,self.body(g).keywords);self.check(g)

    def test_guarded_keyword_cannot_bypass_complex_ability_contract(self):
        self.r.register_behavior('titan',lambda c:[GrantCapturedKeyword(MinionReference.capture(c.state.entities[c.target_id]),Keyword.TITAN)])
        self.spell('titan',lambda c:[Resurrect(1,on_summon='titan')]);g=self.game(hand=('titan',));snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'titan')
        self.assertEqual(g.snapshot(),snap)

    def test_new_entry_dormancy_defers_no_fake_followup(self):
        from hs_sim.engine import AwakenMinion
        self.minion('sleeper',health=3,dormant_turns=1)
        self.spell('wake',lambda c:[AwakenMinion(c.target_id)],requires_target=True)
        # Wake through an explicit effect because sleeping minions cannot be active targets.
        self.spell('wake_all',lambda c:[AwakenMinion(c.state.players[1].board[0])])
        g=self.game(dead=(),hand=('wake_all','kill','revive'),board=('sleeper',))
        self.play(g,'wake_all');self.play(g,'kill',self.find(g,'sleeper','board'));self.play(g)
        self.assertIsNotNone(self.body(g).dormancy);self.assertNotIn(Keyword.REBORN,self.body(g).keywords);self.check(g)

    def test_lethal_summon_reaction_cancels_callback_and_remaining_batch(self):
        self.watch('watch',lambda c:[Damage(c.state.players[2].hero_id,50)])
        self.revive('many',count=2);g=self.game(dead=('b','c'),hand=('many',),board=('watch',));self.play(g,'many')
        self.assertEqual(g.state.status,'finished');self.assertEqual(len(g.state.resurrection_history),1)
        self.assertNotIn(Keyword.REBORN,self.body(g).keywords);self.check(g)


class AzeriteRatTests(unittest.TestCase):
    def setUp(self):
        from hs_sim.engine.representative import build_registry
        self.r=build_registry()
    def game(self,board=('CS2_182',),hand=('WW_001t26',)):
        self.r.register_behavior('kill_all',lambda c:[Destroy(i) for i in c.state.players[1].board])
        self.r.register_card(CardDefinition('kill_all','kill_all',CardType.SPELL,on_play='kill_all'))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_01',board=board,hand=('kill_all',)+hand,mana=10,max_mana=10),
            PlayerSetup('HERO_08')),seed=56),self.r)
        g.apply(PlayCard(1,g.state.players[1].hand[0]));return g
    def play(self,g):g.apply(PlayCard(1,g.state.players[1].hand[0]))
    def check(self,g):
        self.assertEqual(Game.from_snapshot(g.snapshot(),self.r).snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def test_rat_uses_highest_printed_cost_and_grants_three_enhancements(self):
        g=self.game(board=('CS2_182','CS2_179'));self.play(g)
        entity=g.state.entities[g.state.resurrection_history[0].entity_id]
        self.assertEqual((entity.card_id,entity.attack,entity.health),('CS2_182',6,7))
        self.assertTrue({Keyword.REBORN,Keyword.LIFESTEAL}<=entity.keywords);self.check(g)

    def test_rat_without_deaths_still_plays(self):
        g=self.game(board=());self.play(g)
        self.assertFalse(g.state.resurrection_history);self.assertEqual(len(g.state.players[1].board),1);self.check(g)

    def test_rat_is_executable_treasure_metadata(self):
        from hs_sim.engine.representative import EXCAVATE_CLASS_REWARDS
        self.assertIn('WW_001t26',self.r.cards)
        self.assertEqual(len(set(EXCAVATE_CLASS_REWARDS.values())-set(self.r.cards)),0)

    def test_death_knight_fourth_excavation_now_delivers_rat(self):
        from hs_sim.engine import Excavate, GenerationContext
        self.r.register_card(CardDefinition('dk','dk',CardType.HERO,health=30,
            metadata=CardMetadata(False,(CardClass.DEATH_KNIGHT,),None)))
        self.r.register_behavior('four',lambda c:[Excavate(1,c.source_id,count=4)])
        self.r.register_card(CardDefinition('four','four',CardType.SPELL,on_play='four'))
        g=Game.from_scenario(Scenario((PlayerSetup('dk',hand=('four',)),PlayerSetup('HERO_01')),
            generation_context=GenerationContext('local-2026-09-23','experimental')),self.r)
        self.play(g);self.assertEqual(g.state.excavation_history[-1].card_id,'WW_001t26');self.check(g)


if __name__=='__main__':unittest.main()
