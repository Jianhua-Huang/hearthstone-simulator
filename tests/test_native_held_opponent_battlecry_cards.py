"""Mind Sweeper keeps original held conditions across actual Battlecry origins."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

import test_native_held_opponent_copy_cards as f
from hs_sim.cards.native_held_opponent_copy_cards import SWEEPER as CARD,load_batch
from hs_sim.engine.battlecry_sources import TriggerBattlecry,RepeatBattlecry
from hs_sim.engine.counter_policies import GrantCounterPolicy
from hs_sim.engine.discovery_delivery import COMPLETED
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Destroy,GainArmor,
    InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.errors import ResolutionError,SnapshotError
from hs_sim.engine.held_opponent_copies import ability
from hs_sim.engine.model import CounterPolicySpec,Keyword,LimitedTriggerSpec,RewindSpec,TriggerSpec
from hs_sim.engine.played_battlecries import RepeatPlayedBattlecry
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_physical import PROFILE
from hs_sim.engine.whole_card_replays import ReplayWholeCards,PlayDiscoveredOptions
from hs_sim.engine.zones import CardReference,ChooseFromZone,CopyMatching,CopyCard

P='k196.';TANK=P+'tank';SHIELD=P+'shield';IMMUNE=P+'immune';DORMANT=P+'dormant'
WATCH=P+'watch';POWER=P+'spellpower';RETAIN=P+'retain';PROBE=P+'probe';ACQUIRE=P+'acquire'


@lru_cache(maxsize=None)
def registry(mode=None):
    r=f.registry.__wrapped__(P+str(mode))
    for cid,fields in((TANK,{}),(SHIELD,{'keywords':(Keyword.DIVINE_SHIELD,)}),
                     (IMMUNE,{'keywords':(Keyword.IMMUNE,)}),(DORMANT,{'dormant_turns':2}),
                     (POWER,{'spell_damage':5}),(RETAIN,{'retain_rewind_outcomes':True})):
        r.register_card(f.CardDefinition(cid,cid,f.CardType.MINION,health=30,**fields))
    def source(c):
        return next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD)
    def native_records(c,origin=None):
        return[b for b in c.state.battlecry_history if b.payload.card_id==CARD and b.completed and
            b.failure is None and(origin is None or b.origin==origin)]
    def trigger(c):return(TriggerBattlecry(MinionReference.capture(source(c)),c.source_id),)
    bodies={
        'copy':lambda c:(CopyMatching(c.player_id,3-c.player_id,f.Zone.DECK,source_id=c.source_id),),
        'copy_own':lambda c:(CopyMatching(c.player_id,c.player_id,f.Zone.DECK,source_id=c.source_id),),
        'generate':lambda c:(AddToHand(c.player_id,f.C,c.source_id),),
        'summon':lambda c:(Summon(c.player_id,CARD),),
        'trigger':trigger,'rewind':trigger,
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'control':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'arm':lambda c:(GrantCounterPolicy(MinionReference.capture(c.state.entities[c.state.players[3-c.player_id].board[0]]),CounterPolicySpec(f.CardType.MINION),c.source_id),),
        'whole':lambda c:(ReplayWholeCards(c.player_id,c.source_id,
            WholeCardHistoryQuery(c.player_id,len(c.state.play_history)+1,kinds=(f.CardType.MINION,)),physical_profile=PROFILE),),
        'pair':lambda c:tuple(CopyCard(CardReference.capture(next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==CARD)),c.player_id,mode=m,source_id=c.source_id)for m in('current','base')),
    }
    for name,body in bodies.items():
        r.register_behavior(P+name,body)
        fields={'targeting':f.MINION_TARGET}if name in('bounce','control')else{}
        if name=='rewind':fields.update(keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        r.register_card(f.CardDefinition(P+name,P+name,f.CardType.SPELL,cost=3 if name=='rewind'else 0,on_play=P+name,**fields))
    def repeat(c):return(RepeatBattlecry(c.player_id,c.source_id,native_records(c)[0].id),)
    def effect_history(c):return(RepeatBattlecry(c.player_id,c.source_id,native_records(c,'effect')[0].id),)
    def last_history(c):return(RepeatBattlecry(c.player_id,c.source_id,native_records(c)[-1].id),)
    def played(c):return(RepeatPlayedBattlecry(c.player_id,c.source_id,next(p.id for p in c.state.play_history if p.card_id==CARD)),)
    for name,body in(('history',repeat),('effect_history',effect_history),('last_history',last_history),('played',played)):
        r.register_behavior(P+name,body);r.register_card(f.CardDefinition(P+name,P+name,f.CardType.MINION,health=10,battlecry=P+name))
    r.register_behavior(ACQUIRE,lambda c:(AddToHand(c.player_id,CARD,c.source_id),))
    r.register_card(f.CardDefinition(ACQUIRE,ACQUIRE,f.CardType.SPELL,cost=1,on_play=ACQUIRE))
    r.register_behavior(PROBE,lambda c:(ChooseFromZone(c.player_id,c.player_id,f.Zone.HAND,
        PoolQuery(kinds=(f.CardType.MINION,)),operation='copy_current',distinct='entity',discovery=True,source_id=c.source_id),))
    r.register_behavior(PROBE+'.play',lambda c:(PlayDiscoveredOptions(c.player_id,c.source_id,dict(c.event.data)['discovery_id']),)
        if c.event.player_id==c.player_id and c.event.source_id==c.source_id else())
    r.register_card(f.CardDefinition(PROBE,PROBE,f.CardType.MINION,health=10,battlecry=PROBE,
        triggers=(TriggerSpec(COMPLETED,PROBE+'.play'),)))
    if mode in('wait_hand','wait_effect','wait_generated','entry_silence','entry_death','entry_return','entry_morph'):
        entry=mode.startswith('entry_');event='minion_summoned'if entry else'battlecry_started'
        def eligible(c):
            if entry:return c.state.entities[c.event.target_id].card_id==CARD and c.event.player_id==c.player_id
            row=c.state.battlecry_history[dict(c.event.data)['battlecry_id']-1]
            return(row.payload.card_id==CARD and row.player_id==c.player_id and
                (row.origin=='hand'if mode=='wait_hand'else row.origin=='effect'and
                 (row.physical_child_id is not None if mode=='wait_generated'else row.physical_child_id is None)))
        def watch(c):
            target=c.event.target_id if entry else c.event.source_id
            if mode=='entry_silence':return(Silence(target),)
            if mode=='entry_death':return(Destroy(target,c.source_id),)
            if mode=='entry_return':return(ReturnToHand(target),)
            if mode=='entry_morph':return(Transform(target,TANK),)
            return(RequestChoice(c.player_id,(
                ChoiceOption('ok','Continue'),ChoiceOption('bounce','Return source',(ReturnToHand(target),)),
                ChoiceOption('silence','Silence source',(Silence(target),)),
                ChoiceOption('death','Destroy source',(Destroy(target,c.source_id),)),
                ChoiceOption('control','Transfer source',(ChangeControl(target,3-c.player_id),)),
                ChoiceOption('morph','Replace source',(Transform(target,TANK),)),
                ChoiceOption('enemy','Add a new enemy',(Summon(3-c.player_id,TANK),)),
                ChoiceOption('fail','Rollback',(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(f.P+'fail',c.source_id,c.player_id))),
            ),c.source_id),)
        r.register_trigger_condition(WATCH,eligible);r.register_behavior(WATCH,watch)
        r.register_card(f.CardDefinition(WATCH,WATCH,f.CardType.MINION,health=30,
            limited_triggers=(LimitedTriggerSpec(event,WATCH,condition_id=WATCH),)))
    r.validate();return r


class NativeHeldOpponentBattlecryTests(unittest.TestCase):
    def game(self,hand=(CARD,P+'copy'),enemy_deck=(f.B,),mode=None,actor=1,enemy=(TANK,TANK),board=()):
        self.mode=mode
        if mode and(mode.startswith('entry_')or mode.startswith('wait_')):board=(*board,WATCH)
        own=f.PlayerSetup(f.HERO,hand=hand,deck=(f.B,)*6,board=board,mana=100,max_mana=100,mana_cap=100)
        other=f.PlayerSetup(f.HERO,deck=enemy_deck,board=enemy,mana=100,max_mana=100,mana_cap=100)
        return f.Game.from_scenario(f.Scenario((own,other)if actor==1 else(other,own),active_player=actor,seed=196),registry(mode))

    def play(self,g,cid,target=None,entity=None):
        p=g.state.active_player;eid=entity if entity is not None else next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(f.PlayCard(p,eid,target));return eid

    def qualify(self,g):
        self.play(g,P+'copy');p=g.state.active_player
        e=next(g.state.entities[i]for i in g.state.players[p].hand if g.state.entities[i].copy_origin is not None)
        self.play(g,e.card_id,entity=e.id)

    def native(self,g):return[b for b in g.state.battlecry_history if b.payload.card_id==CARD]
    def damage(self,g,p=None):
        p=3-g.state.active_player if p is None else p
        return[g.state.entities[i].damage for i in g.state.players[p].board if g.state.entities[i].card_id==TANK]
    def choose(self,g,key='ok'):
        c=g.state.pending_choice;g.apply(f.SelectChoice(c.player_id,c.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));reader=registry.__wrapped__(self.mode)
        self.assertIsNot(reader,g.registry);self.assertEqual(f.Game.from_snapshot(deepcopy(s),reader).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(f.replay(f.build_replay(g),reader).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for field in('"held_opponent_copy"','"copy_origin"','"play_ids"','"progress_keys"','"battlecry_history"','"resolution_frame"'):
                self.assertNotIn(field,public)
    def roundtrip(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(f.Game.from_snapshot(s,registry.__wrapped__(self.mode)).snapshot(),s)
    def reject(self,s,g):
        keys=('ruleset','registry_fingerprint','mechanics_version','state','rng_state','resolution_frame','rewind_session','match_setup','generation_context','information')
        s['state_hash']=canonical_hash({k:s[k]for k in keys})
        with self.assertRaises(SnapshotError)as error:f.Game.from_snapshot(s,g.registry)
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_native_two_cost_two_three_has_empty_original_condition_without_copy_play(self):
        g=self.game();d=g.registry.card(CARD);raw=load_batch()['cards'][1]['record']
        self.assertEqual((d.name,d.cost,d.attack,d.health),(raw['name'],2,2,3));mana=g.state.players[1].mana
        eid=self.play(g,CARD);self.assertEqual(g.state.players[1].mana,mana-2)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(2,3));self.assertEqual(self.damage(g),[0,0])
        self.assertFalse(self.native(g)[0].held_opponent_copy.matched);self.portable(g)

    def test_qualified_copy_play_deals_two_to_each_enemy_and_not_friends_or_heroes(self):
        g=self.game(board=(TANK,));self.qualify(g);self.play(g,CARD)
        self.assertEqual(self.damage(g),[2,2]);self.assertEqual(self.damage(g,1),[0])
        self.assertEqual([g.state.entities[g.state.players[p].hero_id].health for p in(1,2)],[100,100])
        fact=self.native(g)[0].held_opponent_copy;self.assertEqual(fact.play_ids,(2,));self.portable(g)

    def test_copied_minion_also_satisfies_original_condition(self):
        g=self.game(enemy_deck=(f.A,));self.qualify(g);self.play(g,CARD)
        self.assertEqual(self.damage(g),[2,2]);self.portable(g)

    def test_acquisition_own_copy_and_generated_other_class_do_not_satisfy_condition(self):
        for action in('copy','copy_own','generate'):
            with self.subTest(action=action):
                g=self.game((CARD,P+action));self.play(g,P+action)
                if action!='copy':
                    cid=f.C if action=='generate'else f.B;self.play(g,cid)
                self.play(g,CARD);self.assertEqual(self.damage(g),[0,0]);self.portable(g)

    def test_actual_damage_pipeline_keeps_shield_immune_dormant_and_ignores_spell_damage(self):
        g=self.game(enemy=(TANK,SHIELD,IMMUNE,DORMANT),board=(POWER,));self.qualify(g);self.play(g,CARD)
        by={g.state.entities[i].card_id:g.state.entities[i]for i in g.state.players[2].board}
        self.assertEqual(by[TANK].damage,2);self.assertEqual([by[i].damage for i in(SHIELD,IMMUNE,DORMANT)],[0,0,0])
        self.assertNotIn(Keyword.DIVINE_SHIELD,by[SHIELD].keywords);self.assertIsNotNone(by[DORMANT].dormancy);self.portable(g)

    def test_empty_enemy_board_still_completes_a_real_qualified_battlecry(self):
        g=self.game(enemy=());self.qualify(g);self.play(g,CARD)
        self.assertTrue(self.native(g)[0].completed);self.assertTrue(self.native(g)[0].held_opponent_copy.matched);self.portable(g)

    def test_current_copy_keeps_earned_condition_and_base_copy_does_not(self):
        g=self.game((CARD,P+'copy',P+'pair'));self.qualify(g);self.play(g,P+'pair')
        rows=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==CARD]
        self.assertEqual([ability(e).consumed for e in rows],[True,True,False])
        self.play(g,CARD,entity=rows[-1].id);self.assertEqual(self.damage(g),[0,0])
        self.play(g,CARD,entity=rows[1].id);self.assertEqual(self.damage(g),[2,2]);self.portable(g)

    def test_later_acquired_holder_does_not_borrow_the_original_play(self):
        g=self.game((CARD,P+'copy'),enemy_deck=(ACQUIRE,));self.qualify(g)
        rows=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==CARD]
        self.assertEqual([ability(e).consumed for e in rows],[True,False])
        self.play(g,CARD,entity=rows[1].id);self.assertEqual(self.damage(g),[0,0]);self.portable(g)

    def test_original_hand_fact_survives_entry_silence_death_return_and_morph(self):
        for mode in('entry_silence','entry_death','entry_return','entry_morph'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);self.qualify(g);self.play(g,CARD)
                self.assertEqual(self.damage(g),[2,2]);self.assertTrue(self.native(g)[0].held_opponent_copy.matched)
                self.roundtrip(g)
                if mode=='entry_return':self.portable(g)

    def test_hand_start_wait_preserves_condition_after_return_silence_death_control_or_morph(self):
        g=self.game(mode='wait_hand');self.qualify(g);self.play(g,CARD)
        self.assertEqual(self.damage(g),[0,0]);self.portable(g);pending=g.snapshot()
        for action in('bounce','silence','death','control','morph'):
            with self.subTest(action=action):
                branch=f.Game.from_snapshot(deepcopy(pending),registry.__wrapped__(self.mode));self.choose(branch,action)
                self.assertEqual(self.damage(branch),[2,2]);self.assertTrue(self.native(branch)[0].held_opponent_copy.matched)
                self.roundtrip(branch)
                if action=='control':self.portable(branch)

    def test_enemy_targets_are_read_after_the_actual_start_choice(self):
        g=self.game(mode='wait_hand');self.qualify(g);self.play(g,CARD);self.choose(g,'enemy')
        self.assertEqual(self.damage(g),[2,2,2]);self.portable(g)

    def test_failed_start_choice_restores_original_fact_information_and_payment(self):
        g=self.game(mode='wait_hand');self.qualify(g);self.play(g,CARD);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K195 deliberate'):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.portable(g);self.choose(g);self.assertEqual(self.damage(g),[2,2]);self.portable(g)

    def test_direct_activation_uses_its_real_summoned_carrier_not_a_qualified_hand_card(self):
        g=self.game((CARD,P+'copy',P+'summon',P+'trigger'));self.qualify(g);self.play(g,P+'summon');self.play(g,P+'trigger')
        self.assertEqual(self.damage(g),[0,0]);self.assertFalse(self.native(g)[0].held_opponent_copy.matched);self.portable(g)

    def test_direct_activation_and_its_history_keep_original_earned_state_after_reentry(self):
        g=self.game((CARD,P+'copy',P+'trigger',P+'bounce',P+'effect_history'));self.qualify(g);source=self.play(g,CARD)
        self.play(g,P+'trigger');self.assertEqual(self.damage(g),[4,4]);original=self.native(g)[-1].held_opponent_copy
        self.play(g,P+'bounce',source);self.play(g,CARD);self.assertFalse(self.native(g)[-1].held_opponent_copy.matched)
        self.play(g,P+'effect_history');self.assertEqual(self.damage(g),[6,6]);self.assertEqual(self.native(g)[-1].held_opponent_copy,original);self.portable(g)

    def test_false_effect_history_does_not_borrow_a_later_true_holder(self):
        g=self.game((P+'summon',P+'trigger',P+'bounce',P+'copy',P+'effect_history'))
        self.play(g,P+'summon');self.play(g,P+'trigger');source=self.native(g)[0].source_id
        self.play(g,P+'bounce',source);self.qualify(g);self.play(g,CARD);self.assertEqual(self.damage(g),[2,2])
        self.play(g,P+'effect_history');self.assertEqual(self.damage(g),[2,2]);self.assertFalse(self.native(g)[-1].held_opponent_copy.matched);self.portable(g)

    def test_direct_start_wait_freezes_condition_before_source_cleanup(self):
        g=self.game((CARD,P+'copy',P+'trigger'),mode='wait_effect');self.qualify(g);self.play(g,CARD)
        self.play(g,P+'trigger');self.portable(g);pending=g.snapshot()
        for action in('bounce','silence','death','morph'):
            with self.subTest(action=action):
                branch=f.Game.from_snapshot(deepcopy(pending),registry.__wrapped__(self.mode));self.choose(branch,action)
                self.assertEqual(self.damage(branch),[4,4]);self.roundtrip(branch)
                if action=='bounce':self.portable(branch)

    def test_hand_and_nested_activation_history_use_original_false_and_true_conditions(self):
        g=self.game((CARD,P+'bounce',P+'copy',P+'history',P+'last_history'));source=self.play(g,CARD)
        self.play(g,P+'bounce',source);self.qualify(g);self.play(g,CARD);self.assertEqual(self.damage(g),[2,2])
        self.play(g,P+'history');self.assertEqual(self.damage(g),[2,2]);self.assertFalse(self.native(g)[-1].held_opponent_copy.matched)
        self.play(g,P+'last_history');self.assertEqual(self.damage(g),[2,2]);self.assertFalse(self.native(g)[-1].held_opponent_copy.matched);self.portable(g)

    def test_true_hand_history_does_not_use_the_replay_casters_empty_progress(self):
        g=self.game((CARD,P+'copy',P+'history',P+'last_history'));self.qualify(g);self.play(g,CARD)
        original=self.native(g)[0].held_opponent_copy;self.play(g,P+'history');self.play(g,P+'last_history')
        self.assertEqual(self.damage(g),[6,6]);self.assertTrue(all(b.held_opponent_copy==original for b in self.native(g)));self.portable(g)

    def test_played_history_can_use_a_qualified_countered_hand_submission(self):
        g=self.game((CARD,P+'copy',P+'arm',P+'played'));self.qualify(g);self.play(g,P+'arm');self.play(g,CARD)
        self.assertTrue(g.state.play_history[-1].countered);self.assertFalse(self.native(g))
        self.play(g,P+'played');self.assertEqual(self.damage(g),[2,2]);self.assertEqual(self.native(g)[0].origin,'played_history');self.portable(g)

    def test_source_control_changes_do_not_replace_old_history_or_current_execution_enemies(self):
        g=self.game((CARD,P+'copy',P+'control',P+'history'));self.qualify(g);source=self.play(g,CARD)
        self.play(g,P+'control',source);self.play(g,P+'history');self.assertEqual(self.damage(g),[4,4])
        self.assertEqual(self.native(g)[-1].player_id,1);self.assertEqual(g.state.entities[source].damage,2);self.portable(g)

    def test_second_player_uses_its_own_original_hand_fact_and_enemy_board(self):
        g=self.game(actor=2);self.qualify(g);self.play(g,CARD)
        self.assertEqual(self.damage(g),[2,2]);self.assertEqual(self.native(g)[0].held_opponent_copy.player_id,2);self.portable(g)

    def test_generated_base_replay_has_no_original_hand_condition(self):
        g=self.game((CARD,P+'copy',P+'whole'));self.qualify(g);self.play(g,CARD);self.assertEqual(self.damage(g),[2,2])
        self.play(g,P+'whole');self.assertEqual(self.damage(g),[2,2])
        record=self.native(g)[-1];self.assertEqual(record.origin,'effect');self.assertIsNotNone(record.physical_child_id)
        self.assertFalse(record.held_opponent_copy.matched);self.portable(g)

    def test_current_offered_physical_copy_inherits_earned_state_and_freezes_generated_body(self):
        g=self.game((CARD,CARD,P+'copy',PROBE),mode='wait_generated');self.qualify(g);self.play(g,PROBE)
        c=g.state.pending_choice;key=next(o.id for o in c.options if o.card_id==CARD);self.choose(g,key)
        self.assertTrue(self.native(g),json.dumps({'events':[(e.kind,e.source_id,e.player_id)for e in g.events[-18:]],
            'pending':None if g.state.pending_choice is None else[(o.id,o.card_id)for o in g.state.pending_choice.options],
            'discoveries':len(g.state.card_discovery_history),'whole_roots':len(g.state.whole_card_replay_ledger.roots)},ensure_ascii=False))
        record=self.native(g)[-1];self.assertIsNotNone(record.physical_child_id);self.assertTrue(record.held_opponent_copy.matched)
        self.assertEqual(self.damage(g),[0,0]);self.portable(g);self.choose(g,'silence')
        self.assertEqual(self.damage(g),[2,2]);self.portable(g)

    def test_outer_rewind_preserves_original_source_condition_and_real_activation_count(self):
        for retain in(False,True):
            with self.subTest(retain=retain):
                g=self.game((CARD,P+'copy',P+'rewind'),board=(RETAIN,)if retain else());self.qualify(g);self.play(g,CARD)
                mana=g.state.players[1].mana;self.play(g,P+'rewind');self.portable(g)
                if not retain:self.choose(g,'retry')
                self.assertEqual(g.state.players[1].mana,mana-3);self.assertEqual(len(g.state.play_history),4)
                self.assertEqual(self.damage(g),[6,6]if retain else[4,4]);self.assertEqual(len([b for b in self.native(g)if b.origin=='effect']),2 if retain else 1);self.portable(g)

    def test_rehashed_missing_hand_fact_or_borrowed_noncopy_witness_is_rejected(self):
        g=self.game();self.qualify(g);self.play(g,CARD);self.portable(g)
        s=deepcopy(g.snapshot());s['state']['battlecry_history'][-1]['held_opponent_copy']=None;self.reject(s,g)
        s=deepcopy(g.snapshot());s['state']['battlecry_history'][-1]['held_opponent_copy']['play_ids']=[1];self.reject(s,g)

    def test_rehashed_history_cannot_replace_original_condition_with_the_new_caster(self):
        g=self.game((CARD,P+'copy',P+'history'));self.qualify(g);self.play(g,CARD);self.play(g,P+'history');self.portable(g)
        s=deepcopy(g.snapshot());row=s['state']['battlecry_history'][-1]
        row['held_opponent_copy']['source_id']=row['source_id'];row['held_opponent_copy']['hand_entry_id']=None
        self.reject(s,g)

    def test_unrelated_battlecry_cannot_invent_a_held_condition(self):
        g=self.game((CARD,P+'copy',P+'history'));self.qualify(g);self.play(g,CARD);self.play(g,P+'history')
        s=deepcopy(g.snapshot());parent=next(b for b in s['state']['battlecry_history']if b['payload']['card_id']==P+'history')
        parent['held_opponent_copy']=deepcopy(s['state']['battlecry_history'][-1]['held_opponent_copy']);self.reject(s,g)

    def test_old_398_snapshot_is_rejected(self):
        g=self.game();s=g.snapshot();s['schema_version']=398
        with self.assertRaises(SnapshotError):f.Game.from_snapshot(s,g.registry)
