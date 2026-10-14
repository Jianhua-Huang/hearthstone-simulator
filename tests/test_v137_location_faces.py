"""Twelve bounded location face combinations. Synthetic-only, no TestCase imports."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import unittest

from hs_sim.engine import (AdvanceLocationFace, LocationFaceReference, CardDefinition,
    CardType, CostAuraSpec, CostSpec, DestroyLocation, EndTurn, Game, ModifyLocation,
    PlaceLocation, PlayCard, PlayerSetup, RefreshLocation, ResolutionError, Scenario,
    SelectChoice, SnapshotError, TargetSpec, TriggerSpec, UseLocation, Zone)
from hs_sim.engine.effects import (Buff, ChoiceOption, CopyMinion, Draw, EquipWeapon,
    GainArmor, InvokeBehavior, RandomDamage, RequestChoice, ShuffleIntoDeck, Summon)
from hs_sim.engine.lifecycle import attachment_id, refresh_entity
from hs_sim.engine.locations import (advance_location_face, validate_location_face_frame_references,
    validate_location_face_reference)
from hs_sim.engine.model import AbilityInstance, Enchantment, Event, Resource
from hs_sim.engine.registry import Registry, RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import Resolution
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard


class LocationFaceTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('synthetic-location-face-v1')
        self.behaviors=[]
        self.r.register_card(CardDefinition('hero','hero',CardType.HERO,health=30))
        self.r.register_card(CardDefinition('plain','plain',CardType.MINION,cost=5,attack=2,health=5))
        self.counter=0

    def behavior(self,name,callback):
        self.behaviors.append((name,callback));self.r.register_behavior(name,callback)

    def location(self,name,callback=None,**fields):
        self.behavior(name,callback or (lambda c:[GainArmor(c.player_id,7)]))
        args=dict(durability=3,on_use=name,cost=2);args.update(fields)
        self.r.register_card(CardDefinition(name,name,CardType.LOCATION,**args))

    def faces(self,callback=None,**fields):
        self.location('A',callback,**fields);self.location('B',cost=5,durability=9);self.location('C',cost=1,durability=2)

    def spell(self,name,callback):
        self.behavior(name,callback);self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name))

    def fresh_registry(self):
        registry=Registry('synthetic-location-face-v1')
        for name,callback in self.behaviors:registry.register_behavior(name,callback)
        for card in self.r.cards.values():registry.register_card(deepcopy(card))
        return registry

    def game(self,board=('A',),hand=(),enemy=('plain',),deck=('plain',)*6):
        return Game.from_scenario(Scenario((PlayerSetup('hero',board=board,hand=hand,deck=deck,max_mana=10,mana=10),
            PlayerSetup('hero',board=enemy,deck=deck,max_mana=10,mana=10)),seed=73),self.r)

    def eid(self,g):return next(i for i in g.state.players[1].board if g.state.entities[i].kind==CardType.LOCATION)
    def ref(self,c):return LocationFaceReference.capture(c.state,c.source_id)
    def board_ref(self,c):return LocationFaceReference.capture(c.state,c.state.players[1].board[0])
    def cast(self,g,name):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(1,eid))
    def select(self,g,name='ok'):
        choice=g.state.pending_choice;return g.apply(SelectChoice(choice.player_id,choice.id,(name,)))
    def armor(self,g):return g.state.entities[g.state.players[1].hero_id].armor
    def seal(self,g):
        g._information.sync(g);g._assert_stable();g._origin=g.snapshot()
    def stash(self,name,value):
        directory=os.environ.get('HS137_EVIDENCE_DIR')
        if directory:
            self.counter+=1;p=Path(directory)/(self._testMethodName+'-'+str(self.counter)+'-'+name+'.json')
            p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    def check(self,g):
        self.stash('stable',g.snapshot())
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.fresh_registry()).snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.fresh_registry()).snapshot(),g.snapshot())

    def test_01_original_physical_face_preserves_usage_identity_and_allocators(self):
        self.faces(lambda c:[AdvanceLocationFace(self.ref(c),'B',c.source_id)])
        g=self.game(board=('plain','A','plain'));eid=self.eid(g);before=g.state;e=before.entities[eid]
        identity=(e.id,e.owner,e.controller,e.entered_order,e.summoned_turn,e.origin_entity_id,e.board_presence_id)
        self.stash('before',g.snapshot());result=g.apply(UseLocation(1,eid));after=g.state;a=after.entities[eid]
        self.assertEqual(identity,(a.id,a.owner,a.controller,a.entered_order,a.summoned_turn,a.origin_entity_id,a.board_presence_id))
        self.assertEqual((a.card_id,a.base_cost,a.zone_epoch,a.durability,a.location_cooldown,a.uses_this_turn,a.use_limit),('B',5,e.zone_epoch+1,2,2,1,1))
        self.assertEqual(after.players[1].board,before.players[1].board)
        self.assertEqual((after.next_entity_id,after.next_order),(before.next_entity_id,before.next_order))
        kinds=[x.kind for x in result.events];self.assertEqual(kinds.count('location_face_changed'),1)
        for forbidden in ('location_placed','location_destroyed','minion_summoned','minion_died'):self.assertNotIn(forbidden,kinds)
        self.assertTrue(all(a.id>=before.next_attachment_id for a in a.abilities));self.check(g)

    def test_02_same_face_does_not_renew_consumed_rows_or_epoch(self):
        self.faces();self.spell('same',lambda c:[AdvanceLocationFace(self.board_ref(c),'A'),AdvanceLocationFace(self.board_ref(c),'A')])
        g=self.game(hand=('same',));eid=self.eid(g);e=g._state.entities[eid]
        e.abilities=[replace(a,consumed=True) for a in e.abilities];refresh_entity(e);self.seal(g)
        before=deepcopy(e);next_id=g.state.next_attachment_id;result=self.cast(g,'same')
        self.assertEqual(g.state.entities[eid],before);self.assertEqual(g.state.next_attachment_id,next_id)
        self.assertNotIn('location_face_changed',[e.kind for e in result.events]);self.check(g)

    def test_03_printed_rows_replaced_dynamic_order_source_cost_and_expiry_kept(self):
        self.behavior('old',lambda c:[GainArmor(1,100)]);self.behavior('new',lambda c:[GainArmor(1,4)]);self.behavior('dyn',lambda c:[GainArmor(1,2)])
        self.location('A',lambda c:[AdvanceLocationFace(self.ref(c),'B')],triggers=(TriggerSpec('location_face_changed','old'),),cost_auras=(CostAuraSpec(CostSpec(delta=-1)),))
        self.location('B',triggers=(TriggerSpec('location_face_changed','new'),),cost_auras=(CostAuraSpec(CostSpec(delta=-2)),))
        g=self.game(hand=('plain',));eid=self.eid(g);e=g._state.entities[eid]
        dyn=(AbilityInstance(attachment_id(g._state),'trigger',source_id=eid,event='location_face_changed',behavior_id='dyn',expires_turn=1),
             AbilityInstance(attachment_id(g._state),'cost_aura',source_id=eid,cost_aura=CostAuraSpec(CostSpec(delta=-1)),expires_turn=1))
        ench=Enchantment(attachment_id(g._state),source_id=eid,cost=1,expires_turn=1)
        old_ids={a.id for a in e.abilities};e.abilities.extend(dyn);e.enchantments.append(ench);refresh_entity(e);self.seal(g)
        hand=g.state.players[1].hand[0];self.assertEqual(g.quote_cost(hand).amount,3)
        g.apply(UseLocation(1,eid));e=g.state.entities[eid]
        self.assertEqual(self.armor(g),6);self.assertEqual(e.abilities[:2],list(dyn));self.assertEqual(e.enchantments,[ench])
        self.assertFalse(old_ids&{a.id for a in e.abilities});self.assertEqual(g.quote_cost(hand).amount,2)
        g.apply(EndTurn(1));e=g.state.entities[eid]
        self.assertFalse({a.id for a in dyn}&{a.id for a in e.abilities});self.assertEqual(e.enchantments,[]);self.check(g)

    def test_04_captured_old_bodies_continue_once_with_original_finish(self):
        self.faces(lambda c:[GainArmor(1,1),AdvanceLocationFace(self.ref(c),'B')]);self.behavior('second',lambda c:[GainArmor(1,3)])
        g=self.game();eid=self.eid(g);e=g._state.entities[eid]
        e.abilities.append(AbilityInstance(attachment_id(g._state),'on_use',source_id=eid,behavior_id='second'));refresh_entity(e);self.seal(g)
        result=g.apply(UseLocation(1,eid));self.assertEqual(self.armor(g),4)
        finish=[x for x in result.events if x.kind=='location_used'];self.assertEqual(len(finish),1)
        self.assertEqual((finish[0].source_id,finish[0].player_id,finish[0].target_id),(eid,1,None))
        self.assertEqual((g.state.entities[eid].durability,g.state.entities[eid].uses_this_turn),(2,1));self.check(g)

    def test_05_new_target_domain_and_public_commands_do_not_recheck_old_target(self):
        self.location('A',lambda c:[Buff(c.target_id,2,1),AdvanceLocationFace(self.ref(c),'B')],targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly'))
        self.location('B',targeting=TargetSpec(zones=(Zone.HERO,),kinds=(CardType.HERO,),relation='enemy'))
        self.spell('open',lambda c:[RefreshLocation(c.state.players[1].board[0])])
        g=self.game(board=('A','plain'),hand=('open',));eid=self.eid(g);target=g.state.players[1].board[1]
        result=g.apply(UseLocation(1,eid,target));self.assertEqual(g.state.entities[target].attack,4)
        self.assertEqual(next(x.target_id for x in result.events if x.kind=='location_used'),target)
        self.cast(g,'open');self.assertEqual(g.legal_targets(eid),(g.state.players[2].hero_id,))
        port=g.for_player(1);commands=port.legal_actions();self.assertIsNone(commands['error'])
        command=next(a for a in commands['actions'] if a['type']=='use_location')
        self.assertTrue(port.submit({'revision':commands['revision'],'action':command})['accepted']);self.check(g)

    def test_06_last_durability_deathrattle_slot_and_stale_advance(self):
        self.behavior('death',lambda c:[GainArmor(1,4)])
        self.faces(lambda c:[Summon(1,'plain'),AdvanceLocationFace(self.ref(c),'B')],durability=1,deathrattle='death')
        g=self.game(board=('A',)+('plain',)*6);eid=self.eid(g);before=deepcopy(g.state.entities[eid].abilities)
        result=g.apply(UseLocation(1,eid));e=g.state.entities[eid];death=g.state.death_history[-1]
        self.assertEqual((e.zone,e.card_id,death.card_id,death.durability),(Zone.GRAVEYARD,'A','A',0));self.assertEqual(death.abilities,tuple(before))
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(self.armor(g),4);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0)
        kinds=[x.kind for x in result.events];self.assertLess(kinds.index('location_destroyed'),kinds.index('minion_summoned'))
        self.assertEqual(kinds.count('location_used'),1);self.assertNotIn('location_face_changed',kinds);self.check(g)

    def test_07_modify_refresh_explicit_stage_and_deferred_dying_not_rescued(self):
        self.faces(durability=2)
        self.behavior('fresh',lambda c:[AdvanceLocationFace(LocationFaceReference.capture(c.state,c.target_id),'C')])
        def driver(c):
            ref=self.board_ref(c)
            return [ModifyLocation(ref.entity_id,4),AdvanceLocationFace(ref,'B'),RefreshLocation(ref.entity_id),InvokeBehavior('fresh',c.source_id,1,ref.entity_id)]
        self.spell('driver',driver);g=self.game(hand=('driver',));eid=self.eid(g);self.cast(g,'driver')
        self.assertEqual((g.state.entities[eid].card_id,g.state.entities[eid].durability,g.state.entities[eid].location_cooldown,g.state.entities[eid].zone_epoch),('C',6,0,2));self.check(g)
        # Focused handler guard inside an existing postponed-death state; this
        # does not claim a new full Starship death-deferral integration scenario.
        ref=LocationFaceReference.capture(g.state,eid);r=Resolution(g);r.death_deferrals=1;e=g._state.entities[eid];e.durability=0
        from hs_sim.engine.death_causes import mark
        mark(r,e,'durability','location-test',eid);before=deepcopy(e)
        advance_location_face(r,AdvanceLocationFace(ref,'B'));self.assertEqual(g._state.entities[eid],before)

    def test_08_two_true_waits_old_captured_context_restore_clone_replay(self):
        def body(c):
            ref=self.ref(c)
            return [AdvanceLocationFace(ref,'B'),RequestChoice(1,(ChoiceOption('ok','ok',(AdvanceLocationFace(ref,'C'),InvokeBehavior('current',c.source_id,1))),),source_id=c.source_id)]
        self.faces(body)
        self.behavior('current',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',(AdvanceLocationFace(self.ref(c),'C'),)),),source_id=c.source_id)])
        self.behavior('old-second',lambda c:[AdvanceLocationFace(self.ref(c),'B'),GainArmor(1,3)])
        g=self.game();eid=self.eid(g);e=g._state.entities[eid];e.abilities.append(AbilityInstance(attachment_id(g._state),'on_use',source_id=eid,behavior_id='old-second'));refresh_entity(e);self.seal(g)
        g.apply(UseLocation(1,eid));self.assertEqual(g.state.entities[eid].card_id,'B');self.check(g)
        candidates=(g,g.clone(),Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.fresh_registry()))
        for candidate in candidates:self.select(candidate);self.assertIsNotNone(candidate.state.pending_choice)
        self.assertEqual(g.snapshot(),candidates[1].snapshot());self.assertEqual(g.snapshot(),candidates[2].snapshot());self.check(g)
        for candidate in candidates:self.select(candidate)
        self.assertEqual(g.snapshot(),candidates[1].snapshot());self.assertEqual(g.snapshot(),candidates[2].snapshot())
        self.assertEqual((g.state.entities[eid].card_id,self.armor(g)),('C',3));self.check(g)

    def test_09_old_face_dead_same_name_and_physical_reentry_references_stay_stale(self):
        self.faces()
        def driver(c):
            ref=self.board_ref(c)
            return [AdvanceLocationFace(ref,'B'),AdvanceLocationFace(ref,'C'),DestroyLocation(ref.entity_id),PlaceLocation(1,'A'),AdvanceLocationFace(ref,'C')]
        self.spell('driver',driver);g=self.game(hand=('driver',));old=self.eid(g);self.cast(g,'driver')
        self.assertEqual((g.state.entities[old].zone,g.state.entities[old].card_id),(Zone.GRAVEYARD,'B'))
        new=self.eid(g);self.assertNotEqual(old,new);self.assertEqual(g.state.entities[new].card_id,'A');self.check(g)
        # Existing shuffle/draw/play route reuses an ID but allocates a new entry.
        self.setUp();self.faces()
        def shuffle(c):
            ref=self.board_ref(c);return [ShuffleIntoDeck(ref.entity_id),Draw(1),RequestChoice(1,(ChoiceOption('ok','ok',(AdvanceLocationFace(ref,'C'),)),))]
        self.spell('shuffle',shuffle);g=self.game(hand=('shuffle',),deck=());old=self.eid(g);ref=LocationFaceReference.capture(g.state,old);self.cast(g,'shuffle')
        self.check(g);self.select(g);g.apply(PlayCard(1,old));self.assertGreater(g.state.entities[old].entered_order,ref.entered_order)
        self.assertGreater(g.state.entities[old].zone_epoch,ref.zone_epoch);validate_location_face_reference(g.state,self.r,ref);self.check(g)

    def test_10_current_base_copy_boundaries_and_stored_location_copy(self):
        for mode in ('current','base'):
            with self.subTest(mode=mode):
                self.setUp();self.faces();self.spell('wrong',lambda c:[CopyMinion(c.state.players[1].board[0],1,mode=mode)])
                self.spell('copy',lambda c:[CopyCard(CardReference.capture(c.state.entities[c.state.players[1].hand[-1]]),1,mode=mode)])
                g=self.game(hand=('wrong','copy','B'));before=g.snapshot()
                with self.assertRaises(ResolutionError):self.cast(g,'wrong')
                self.assertEqual(g.snapshot(),before);stored=g.state.players[1].hand[-1];e=g._state.entities[stored];e.durability=4
                e.enchantments.append(Enchantment(attachment_id(g._state),cost=-1));refresh_entity(e);self.seal(g)
                self.cast(g,'copy');copied=g.state.entities[g.state.players[1].hand[-1]]
                self.assertNotEqual(copied.id,stored);self.assertEqual(copied.card_id,'B')
                self.assertEqual(copied.durability,4 if mode=='current' else 9)
                self.assertEqual((copied.location_cooldown,copied.uses_this_turn),(0,0))
                if mode=='current':self.assertFalse({a.id for a in copied.abilities}&{a.id for a in e.abilities})
                self.check(g)

    def test_11_rehashed_waiting_all_domain_negatives_and_context_scope(self):
        self.faces(lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',(AdvanceLocationFace(self.ref(c),'B',c.source_id),)),),source_id=c.source_id)])
        g=self.game(board=('A','plain'));g.apply(UseLocation(1,self.eid(g)));base=g.snapshot();self.check(g)
        def refs(value):
            if isinstance(value,dict):
                if value.get('type')=='hs_sim.engine.locations.LocationFaceReference':yield value['fields']
                for child in value.values():yield from refs(child)
            elif isinstance(value,list):
                for child in value:yield from refs(child)
        mutations=[('entity_id',g.state.next_entity_id,'Unknown original'),('card_id','unknown','unsupported card'),('card_id','plain','physical location'),('zone_epoch',g.state.entities[self.eid(g)].zone_epoch+1,'not been allocated'),('entered_order',g.state.next_order,'not been allocated'),('entered_order',g.state.entities[g.state.players[1].board[1]].entered_order,'not been allocated'),('card_id','B','captured identity'),('controller_id',2,'captured identity'),('entity_id',True,'integer'),('zone_epoch',True,'integer')]
        for field,value,reason in mutations:
            with self.subTest(field=field,value=value):
                snap=deepcopy(base)
                for row in refs(snap['resolution_frame']):row[field]=value
                snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')})
                self.stash('rehash-'+field,snap)
                with self.assertRaises(SnapshotError) as error:Game.from_snapshot(snap,self.fresh_registry())
                self.assertNotIn('digest mismatch',str(error.exception).lower());self.assertIn(reason,str(error.exception))
        from hs_sim.engine.continuations import FrameCodec
        def effects(value):
            if isinstance(value,dict):
                if value.get('type')=='hs_sim.engine.locations.AdvanceLocationFace':yield value
                for child in value.values():yield from effects(child)
            elif isinstance(value,list):
                for child in value:yield from effects(child)
        def reject(snap,label,reason):
            snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')})
            self.stash(label,snap)
            with self.assertRaises(SnapshotError) as error:Game.from_snapshot(snap,self.fresh_registry())
            self.assertNotIn('digest mismatch',str(error.exception).lower());self.assertIn(reason,str(error.exception))
        for field,value,reason in (('card_id','unknown','unsupported card'),('card_id','plain','physical location'),
                                  ('source_id',g.state.next_entity_id,'Unknown location face effect source'),('source_id',True,'integer')):
            snap=deepcopy(base)
            for row in effects(snap['resolution_frame']):row['fields'][field]=value
            reject(snap,'effect-'+field,reason)
        for kind in ('extra-ref-field','extra-effect-field','unknown-ref-type'):
            snap=deepcopy(base)
            effect=next(effects(snap['resolution_frame']))
            if kind=='extra-ref-field':effect['fields']['target']['fields']['epoch_policy']='latest'
            elif kind=='extra-effect-field':effect['fields']['reset']=True
            else:effect['fields']['target']['type']='unknown.LocationFaceReference'
            reject(snap,kind,'fields' if kind!='unknown-ref-type' else 'Unknown immutable frame type')
        ref=LocationFaceReference.capture(g.state,self.eid(g));future=replace(ref,zone_epoch=ref.zone_epoch+1)
        codec=FrameCodec(g.mechanics,self.r,origin_state=g.state)
        forged=codec.encode(AdvanceLocationFace(future,'B'))
        for position in ('prefix','continuation'):
            snap=deepcopy(base);snap['resolution_frame']['fields'][position]['tuple'].insert(0,deepcopy(forged))
            reject(snap,'real-'+position,'not been allocated')
        snap=deepcopy(base);effect=next(effects(snap['resolution_frame']))
        effect['fields']['target']['fields']['zone_epoch']=future.zone_epoch
        nested=RequestChoice(1,(ChoiceOption('inner','inner',(AdvanceLocationFace(future,'B'),)),))
        branch=snap['resolution_frame']['fields']['options']['tuple'][0]['fields']['effects']['tuple']
        branch.clear();branch.append(codec.encode(nested));reject(snap,'real-nested-unselected','not been allocated')
        # Strict public face event restore, including its event-time new identity.
        success=Game.from_snapshot(deepcopy(base),self.fresh_registry());self.select(success);self.check(success)
        public=success.snapshot()
        for label in ('unknown-face','non-location-face','same-face','extra-private-epoch','missing-target','different-new-identity'):
            snap=deepcopy(public)
            for knowledge in snap['information']['players'].values():
                for event in knowledge['events']:
                    if event['kind']!='location_face_changed':continue
                    face=event['location_face']
                    if label=='unknown-face':face['old_card_id']='unknown'
                    elif label=='non-location-face':face['old_card_id']='plain'
                    elif label=='same-face':face['old_card_id']=face['new_card_id']
                    elif label=='extra-private-epoch':face['zone_epoch']=1
                    elif label=='missing-target':event['target']=None
                    else:face['new_card_id']='C'
            reject(snap,'public-'+label,{'unknown-face':'unsupported card','non-location-face':'location definitions',
                'same-face':'two different','extra-private-epoch':'fields','missing-target':'two different',
                'different-new-identity':'new face identity'}[label])
        # Visit prefix/continuation/options/context using its true state scope.
        ref=LocationFaceReference.capture(g.state,self.eid(g));future=replace(ref,zone_epoch=ref.zone_epoch+1)
        for value in ((AdvanceLocationFace(future,'B'),),{'unselected':RequestChoice(1,(ChoiceOption('ok','ok',(AdvanceLocationFace(future,'B'),)),))}):
            with self.assertRaisesRegex(ValueError,'not been allocated'):validate_location_face_frame_references(g.state,self.r,value)
        old_state=deepcopy(g.state);g._state.entities[ref.entity_id].zone_epoch+=1;g._state.entities[ref.entity_id].card_id='B'
        context=RuleContext(old_state,ref.entity_id,1,event=Event(1,0,'test',data=(('reference',ref),)))
        validate_location_face_frame_references(g.state,self.r,context)
        bad_context=replace(context,event=replace(context.event,data=(('reference',future),)))
        with self.assertRaisesRegex(ValueError,'not been allocated'):validate_location_face_frame_references(g.state,self.r,bad_context)

    def test_12_true_choice_failure_rolls_back_face_rows_death_rng_and_public_DTO(self):
        def body(c):
            ref=self.ref(c);random=RandomDamage(tuple(c.state.players[2].board),1,c.source_id)
            bad=(random,AdvanceLocationFace(ref,'B'),ModifyLocation(ref.entity_id,-99),EquipWeapon(1,'plain'))
            good=(AdvanceLocationFace(ref,'B'),)
            return [RequestChoice(1,(ChoiceOption('bad','bad',bad),ChoiceOption('ok','ok',good)),source_id=c.source_id)]
        self.faces(body);g=self.game(enemy=('plain','plain'));eid=self.eid(g);g.apply(UseLocation(1,eid));before=g.snapshot();self.stash('before-failure',before)
        clone=g.clone();restored=Game.from_snapshot(json.loads(json.dumps(before)),self.fresh_registry())
        for candidate in (g,clone,restored):
            with self.assertRaises(ResolutionError) as error:self.select(candidate,'bad')
            self.assertIn('weapon',str(error.exception).lower());self.assertEqual(candidate.snapshot(),before);self.select(candidate)
        self.assertEqual(g.snapshot(),clone.snapshot());self.assertEqual(g.snapshot(),restored.snapshot())
        for player in (1,2):
            view=g.for_player(player).observe()['observation'];events=g.player_events(player)
            event=next(x for x in events if x['kind']=='location_face_changed')
            self.assertEqual(event['location_face'],{'old_card_id':'A','new_card_id':'B'})
            forbidden=('zone_epoch','entered_order','board_presence_id','abilities','resolution_frame','entity_id')
            text=json.dumps(view)+json.dumps(events)
            for field in forbidden:self.assertNotIn('"'+field+'"',text)
        self.assertEqual(g.state.entities[eid].location_cooldown,2)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[eid].location_cooldown,2)
        g.apply(EndTurn(2));self.assertEqual(g.state.entities[eid].location_cooldown,1)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(g.state.entities[eid].location_cooldown,0);self.check(g)


if __name__=='__main__':unittest.main()
