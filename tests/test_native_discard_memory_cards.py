"""Successful original discards become copied, resettable native memory."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.native_discard_memory_cards import HOARDER,load_batch
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,IllegalAction,LaunchStarship,PlayCard,
    PlayerSetup,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.costs import local_cost,quote_unselected_cost
from hs_sim.engine.deathrattle_memory import DiscardForDeathrattle
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,CopyMinion,Destroy,
    InvokeBehavior,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import CostSpec,TargetSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.starships import construction
from hs_sim.engine.zones import CardReference,CopyCard,DiscardCard
from hs_sim.targets import canonical_digest

YETI='CORE_CS2_182';PREFIX='k98.'


def registry():
    r=build_registry()
    def gem(c):return next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==HOARDER)
    def recover(c):
        row=c.state.discard_history[-1]
        return(ReturnToHand(row.entity_id,discard=row),)
    def reenter(c):return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id),)
    def trigger(c):return(TriggerBattlecry(MinionReference.capture(gem(c)),c.source_id,c.target_id,targeting='explicit'),)
    def prepare(c):return(BuffStoredCard(CardReference.capture(c.state.entities[c.target_id]),3,4,c.source_id,cost=CostSpec(delta=-2)),)
    def defer(c):
        source=gem(c);card=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==YETI)
        ref=CardReference.capture(card);request=DiscardForDeathrattle(ref,MinionReference.capture(source),
            tuple(a.id for a in active_abilities(source,'deathrattle')if a.deathrattle_memory is not None))
        return(RequestChoice(c.player_id,(
            ChoiceOption('go','Discard',(request,)),
            ChoiceOption('cycle_source','Reenter source',(ReturnToHand(source.id),InvokeBehavior(PREFIX+'reenter',c.source_id,c.player_id,source.id),request)),
            ChoiceOption('cycle_card','Reacquire card',(DiscardCard(ref,c.source_id),InvokeBehavior(PREFIX+'recover',c.source_id,c.player_id),request)),
        ),source_id=c.source_id),)
    scripts={
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'base':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),'bounce':lambda c:(ReturnToHand(c.target_id),),
        'silence':lambda c:(Silence(c.target_id),),'transform':lambda c:(Transform(c.target_id,YETI),),
        'control':lambda c:(ChangeControl(c.target_id,2),),'prepare':prepare,'trigger':trigger,'defer':defer,
        'fill':lambda c:tuple(AddToHand(c.player_id,YETI,c.source_id)for _ in range(10)),
    }
    r.register_behavior(PREFIX+'recover',recover);r.register_behavior(PREFIX+'reenter',reenter)
    r.register_card(CardDefinition(PREFIX+'recover','Recover physical discarded minion',CardType.SPELL,on_play=PREFIX+'recover'))
    r.register_behavior(PREFIX+'fail',lambda c:(AddToHand(c.player_id,'unknown.k98'),))
    for name,body in scripts.items():
        r.register_behavior(PREFIX+name,body)
        targeting=None if name in('fill','defer')else TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')if name=='prepare'else TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,CardType.SPELL,CardType.WEAPON,CardType.LOCATION,CardType.HERO),relation='friendly')if name=='trigger'else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        r.register_card(CardDefinition(PREFIX+name,name,CardType.SPELL,on_play=PREFIX+name,targeting=targeting))
    def watch(c,mode):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=HOARDER:return ()
        if mode=='kill':return(Destroy(source.id,c.source_id),)
        if mode=='copy':return(CopyMinion(source.id,c.player_id),)
        return(RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(PREFIX+'fail',c.source_id,c.player_id),)),
        ),source_id=c.source_id),)
    for name in('kill','copy','wait'):
        behavior=PREFIX+'watch_'+name;r.register_behavior(behavior,lambda c,name=name:watch(c,name))
        r.register_card(CardDefinition(behavior,name,CardType.MINION,health=8,triggers=(TriggerSpec('card_discarded',behavior),)))
    def copy_wait(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=HOARDER:return ()
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',()),),source_id=c.source_id),)
    r.register_behavior(PREFIX+'copy_wait',copy_wait)
    r.register_card(CardDefinition(PREFIX+'copy_wait','Recovery observer',CardType.MINION,health=8,
        triggers=(TriggerSpec('card_added_to_hand',PREFIX+'copy_wait'),)))
    r.register_behavior(PREFIX+'own_kill',lambda c:(Destroy(c.discard.source_id,c.source_id),))
    for name,body in(('own_kill',PREFIX+'own_kill'),('own_fail',PREFIX+'fail')):
        r.register_card(CardDefinition(PREFIX+name,name,CardType.MINION,cost=2,attack=1,health=2,on_discard=body))
    return r


class NativeDiscardMemoryCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(HOARDER,YETI,PREFIX+'kill'),board=(),enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
        ),seed=98),self.r)
    def find(self,g,cid,p=1,zone='hand'):return next(i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid=HOARDER,target=None):
        p=g.state.active_player;i=self.find(g,cid,p)
        g.apply(PlayCard(p,i,target,position=len(g.state.players[p].board)if self.r.card(cid).kind==CardType.MINION else None));return i
    def memory(self,g,i):return next(a.deathrattle_memory for a in g.state.entities[i].abilities if a.deathrattle_memory is not None)
    def price(self,g,i):return quote_unselected_cost(g.state,self.r,g.state.entities[i]).amount
    def setup(self,g):
        target=self.find(g,YETI);source=self.play(g,target=target);return source,target
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in (1,2):
            text=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())
            for private in('discard_ids','deathrattle_memory','SourceAllocationFact','resolution_frame','rng_state'):
                self.assertNotIn(private,text)
        return other
    def reject(self,saved):
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as caught:Game.from_snapshot(saved,self.r)
        self.assertNotIn('digest mismatch',str(caught.exception))
    def nodes(self,value,typename):
        if isinstance(value,dict):
            if value.get('type','').endswith('.'+typename):yield value['fields']
            for child in value.values():yield from self.nodes(child,typename)
        elif isinstance(value,list):
            for child in value:yield from self.nodes(child,typename)

    def test_full_raw_primary_faces_and_native_declaration(self):
        data=load_batch();row=data['cards'][0];self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(len(data['official_observations']),2);self.assertFalse(data['cn_calibrated'])
        self.assertEqual(self.r.card(HOARDER).native_deathrattle.kind,'discard_link')

    def test_paid_successful_chosen_discard_recovers_fresh_base_card_with_discount(self):
        g=self.game();source,target=self.setup(g);self.assertEqual(self.memory(g,source).discard_ids,(1,))
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(g.state.players[1].mana,37)
        self.play(g,PREFIX+'kill',source);new=self.find(g,YETI);self.assertNotEqual(new,target)
        self.assertEqual((self.price(g,new),g.state.entities[new].origin_entity_id),(3,target));self.portable(g)

    def test_empty_other_hand_is_targetless_and_no_memory_is_invented(self):
        g=self.game((HOARDER,));source=self.play(g);self.assertEqual(self.memory(g,source).discard_ids,())
        self.assertFalse(g.state.discard_history);self.portable(g)

    def test_owned_hand_only_rejects_source_board_and_opponent_without_payment(self):
        g=self.game(board=(YETI,),enemy_hand=(YETI,));saved=g.snapshot()
        for target in(self.find(g,HOARDER),self.find(g,YETI,zone='board'),self.find(g,YETI,2)):
            with self.assertRaises(IllegalAction):self.play(g,target=target)
            self.assertEqual(g.snapshot(),saved)

    def test_all_playable_hand_types_have_printed_recovery_and_original_identity(self):
        for cid in(YETI,'CS2_029','FIR_922','CATA_584','CATA_190h'):
            with self.subTest(cid=cid):
                g=self.game((HOARDER,cid,PREFIX+'kill'));target=self.find(g,cid);source=self.play(g,target=target)
                self.play(g,PREFIX+'kill',source);new=self.find(g,cid)
                self.assertNotEqual(new,target);self.assertEqual(self.price(g,new),max(0,self.r.card(cid).cost-1))

    def test_original_local_stats_and_cost_are_not_copied_into_printed_recovery(self):
        g=self.game((PREFIX+'prepare',HOARDER,YETI,PREFIX+'kill'));target=self.find(g,YETI)
        self.play(g,PREFIX+'prepare',target);source=self.play(g,target=target);self.play(g,PREFIX+'kill',source)
        new=self.find(g,YETI);self.assertEqual((g.state.entities[new].attack,g.state.entities[new].health,self.price(g,new)),(4,5,3))

    def test_discard_notification_killing_source_already_sees_complete_memory(self):
        g=self.game((HOARDER,YETI),board=(PREFIX+'watch_kill',));source,target=self.setup(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertNotEqual(self.find(g,YETI),target);self.portable(g)

    def test_own_discard_body_killing_source_already_sees_complete_memory(self):
        g=self.game((HOARDER,PREFIX+'own_kill'));target=self.find(g,PREFIX+'own_kill');source=self.play(g,target=target)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertNotEqual(self.find(g,PREFIX+'own_kill'),target);self.portable(g)

    def test_discard_notification_current_copy_carries_accepted_memory(self):
        g=self.game((HOARDER,YETI,PREFIX+'kill'),board=(PREFIX+'watch_copy',));source,target=self.setup(g)
        copied=next(i for i in g.state.players[1].board if i!=source and g.state.entities[i].card_id==HOARDER)
        self.assertEqual(self.memory(g,copied).discard_ids,(1,));self.play(g,PREFIX+'kill',copied)
        self.assertNotEqual(self.find(g,YETI),target);self.assertEqual(self.memory(g,source).discard_ids,(1,));self.portable(g)

    def test_current_and_base_copy_have_distinct_original_memory(self):
        g=self.game((HOARDER,YETI,PREFIX+'copy',PREFIX+'base',PREFIX+'kill',PREFIX+'kill'));source,target=self.setup(g)
        self.play(g,PREFIX+'copy',source);copy=g.state.players[1].board[-1];self.play(g,PREFIX+'base',source);base=g.state.players[1].board[-1]
        self.assertEqual(self.memory(g,copy).discard_ids,(1,));self.assertEqual(self.memory(g,base).discard_ids,())
        self.play(g,PREFIX+'kill',base);self.assertFalse(any(g.state.entities[i].card_id==YETI for i in g.state.players[1].hand))
        self.play(g,PREFIX+'kill',copy);self.assertEqual(self.price(g,self.find(g,YETI)),3);self.portable(g)

    def test_silence_and_transform_remove_remembered_native_deathrattle(self):
        for action in('silence','transform'):
            g=self.game((HOARDER,YETI,PREFIX+action,PREFIX+'kill'));source,target=self.setup(g)
            self.play(g,PREFIX+action,source);self.play(g,PREFIX+'kill',source)
            self.assertFalse(any(g.state.entities[i].card_id==YETI for i in g.state.players[1].hand))

    def test_bounce_then_same_id_replay_starts_a_new_memory(self):
        g=self.game((HOARDER,YETI,'CS2_029',PREFIX+'bounce'));source,target=self.setup(g)
        self.play(g,PREFIX+'bounce',source);self.assertEqual(self.memory(g,source).discard_ids,())
        self.play(g,target=self.find(g,'CS2_029'));self.assertEqual(self.memory(g,source).discard_ids,(2,));self.portable(g)

    def test_control_transfer_returns_to_actual_deathrattle_executor(self):
        g=self.game((HOARDER,YETI,PREFIX+'control',PREFIX+'kill'));source,target=self.setup(g)
        self.play(g,PREFIX+'control',source);self.play(g,PREFIX+'kill',source)
        self.assertEqual(self.price(g,self.find(g,YETI,2)),3);self.assertFalse(any(g.state.entities[i].card_id==YETI for i in g.state.players[1].hand));self.portable(g)

    def test_repeated_actual_battlecry_appends_only_successful_occurrences_in_order(self):
        g=self.game((HOARDER,YETI,'FIR_922',PREFIX+'trigger',PREFIX+'kill'));source,target=self.setup(g)
        self.play(g,PREFIX+'trigger',self.find(g,'FIR_922'));self.assertEqual(self.memory(g,source).discard_ids,(1,2))
        self.play(g,PREFIX+'kill',source);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[YETI,'FIR_922']);self.portable(g)

    def test_first_recovery_wait_restores_remaining_original_discard_copy_request(self):
        g=self.game((HOARDER,YETI,'FIR_922',PREFIX+'trigger',PREFIX+'kill'),board=(PREFIX+'copy_wait',));source,target=self.setup(g)
        self.play(g,PREFIX+'trigger',self.find(g,'FIR_922'));self.play(g,PREFIX+'kill',source)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g)
        for current in(g,other):
            while current.state.pending_choice is not None:self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[YETI,'FIR_922'])

    def test_discarded_launched_starship_retains_original_composed_base_recipe(self):
        g=self.game((PREFIX+'kill',PREFIX+'bounce',HOARDER,PREFIX+'kill'),board=('SC_403a',))
        piece=self.find(g,'SC_403a',zone='board');self.play(g,PREFIX+'kill',piece)
        ship=construction(g.state,1);g.apply(LaunchStarship(1,ship.id));body=g.state.entities[ship.id]
        base=(body.base_attack,body.base_health);parts=body.components;self.play(g,PREFIX+'bounce',ship.id)
        source=self.play(g,target=ship.id);self.play(g,PREFIX+'kill',source)
        copy=next(e for e in g.state.entities.values()if e.origin_entity_id==ship.id)
        self.assertEqual(copy.components,parts);self.assertEqual((copy.attack,copy.health),base);self.portable(g)

    def test_original_discarded_entity_reacquisition_does_not_rebind_recovery_recipe(self):
        g=self.game((HOARDER,YETI,PREFIX+'recover',PREFIX+'kill'));source,target=self.setup(g)
        self.play(g,PREFIX+'recover');self.assertEqual(g.state.entities[target].zone,Zone.HAND)
        self.play(g,PREFIX+'kill',source)
        ids=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==YETI]
        self.assertEqual(len(ids),2);new=next(i for i in ids if i!=target)
        self.assertEqual((g.state.entities[new].origin_entity_id,self.price(g,new)),(target,3));self.portable(g)

    def test_waiting_restore_clone_replay_and_choice_error_rollback_preserve_link(self):
        g=self.game(board=(PREFIX+'watch_wait',));source,target=self.setup(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.memory(g,source).discard_ids,(1,));saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.play(g,PREFIX+'kill',source);self.assertEqual(self.price(g,self.find(g,YETI)),3)

    def test_own_discard_failure_rolls_back_payment_hand_memory_and_history(self):
        g=self.game((HOARDER,PREFIX+'own_fail'));target=self.find(g,PREFIX+'own_fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,target=target)
        self.assertEqual(g.snapshot(),saved)

    def test_deferred_request_roundtrip_and_new_source_residence_skips_old_memory(self):
        g=self.game((YETI,PREFIX+'defer'),board=(HOARDER,));source=self.find(g,HOARDER,zone='board')
        self.play(g,PREFIX+'defer');other=self.portable(g)
        for current in(g,other):self.choose(current,'cycle_source')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.memory(g,source).discard_ids,())
        self.assertEqual(len(g.state.discard_history),1);self.portable(g)

    def test_same_id_new_hand_entry_does_not_receive_old_discard_request(self):
        g=self.game((YETI,PREFIX+'defer'),board=(HOARDER,));target=self.find(g,YETI);self.play(g,PREFIX+'defer');self.choose(g,'cycle_card')
        self.assertEqual(g.state.entities[target].zone,Zone.HAND);self.assertEqual(len(g.state.discard_history),1)
        self.assertEqual(self.memory(g,self.find(g,HOARDER,zone='board')).discard_ids,());self.portable(g)

    def test_full_hand_burn_uses_shared_base_creation_with_discount(self):
        g=self.game((HOARDER,YETI,PREFIX+'fill'),enemy_hand=(PREFIX+'kill',));source,target=self.setup(g);self.play(g,PREFIX+'fill')
        g.apply(EndTurn(1));self.play(g,PREFIX+'kill',source)
        copied=[e for e in g.state.entities.values()if e.origin_entity_id==target]
        self.assertEqual(len(copied),1);self.assertEqual(copied[0].zone,Zone.GRAVEYARD);self.assertEqual(local_cost(copied[0])[0],3);self.portable(g)

    def test_rehashed_memory_unknown_duplicate_or_foreign_occurrences_are_rejected(self):
        g=self.game();source,target=self.setup(g)
        for ids in([999],[1,1],[True]):
            saved=deepcopy(g.snapshot());entities=saved['state']['entities'];entity=entities[str(source)]if isinstance(entities,dict)else next(e for e in entities if e['id']==source)
            memory=next(a['deathrattle_memory']for a in entity['abilities']if a['deathrattle_memory']is not None)
            memory['discard_ids']=ids;self.reject(saved)
        g=self.game((YETI,PREFIX+'defer'),board=(HOARDER,));source=self.find(g,HOARDER,zone='board')
        self.play(g,PREFIX+'defer');self.choose(g,'cycle_card');saved=deepcopy(g.snapshot())
        memory=next(a['deathrattle_memory']for a in saved['state']['entities'][str(source)]['abilities']if a['deathrattle_memory']is not None)
        memory['discard_ids']=[1];self.reject(saved)

    def test_rehashed_discard_base_material_cannot_forge_components_or_innate_size(self):
        g=self.game();self.setup(g)
        for key,value in(('components',['unknown.k98']),('jade_size',3)):
            saved=deepcopy(g.snapshot());saved['state']['discard_history'][0][key]=value;self.reject(saved)

    def test_rehashed_deferred_source_or_card_future_reference_is_rejected(self):
        g=self.game((YETI,PREFIX+'defer'),board=(HOARDER,));self.play(g,PREFIX+'defer')
        for typename,field in(('MinionReference','entered_order'),('CardReference','zone_epoch')):
            saved=deepcopy(g.snapshot());nodes=list(self.nodes(saved,typename));self.assertTrue(nodes)
            for node in nodes:node[field]=999999
            self.reject(saved)
