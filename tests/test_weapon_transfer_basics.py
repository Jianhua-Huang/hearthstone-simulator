"""Transfer actual equipment without recreating material or resetting Hero uses."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,EquippedWeaponReference,
    Game,IllegalAction,Keyword,PlayCard,PlayerSetup,Registry,ResolutionError,Scenario,
    SelectChoice,SnapshotError,TransferWeapon,TriggerSpec,Zone)
from hs_sim.engine.effects import (ChoiceOption,Destroy,GainArmor,GrantKeyword,
    InvokeBehavior,ModifyWeapon,RequestChoice)
from hs_sim.engine.equipment import weapon_transfer_reference
from hs_sim.engine.information import VIEW_VERSION
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]
PIN='9cb7036102f460c602e9325ea6468c4b396f6823de0a2357095d2e7a366b165b'
def evidence():
    value=json.loads((ROOT/'data/support/weapon-transfer-basics.json').read_bytes())
    if canonical_digest(value)!=PIN: raise ValueError('Weapon transfer evidence changed')
    return value

def registry():
    r=Registry('isolated-physical-weapon-transfer-v1')
    r.register_card(CardDefinition('hero','Diagnostic hero',CardType.HERO,health=80,metadata=metadata()))
    r.register_card(CardDefinition('plain','Diagnostic minion',CardType.MINION,attack=1,health=30,metadata=metadata()))
    r.register_behavior('death',lambda c:(GainArmor(c.player_id,c.death.attack),))
    def explode(c): raise ResolutionError('Diagnostic transfer failure')
    r.register_behavior('explode',explode)
    r.register_behavior('waiting-death',lambda c:(RequestChoice(c.player_id,
        (ChoiceOption('ok','Continue',(GainArmor(c.player_id,c.death.attack),)),
        ChoiceOption('fault','Fail',(InvokeBehavior('explode',c.source_id,c.player_id),))),c.source_id),))
    for name,attack,durability,keywords,body in (('own',1,3,(),'death'),('weapon',3,2,(),'death'),
            ('wind',2,3,(Keyword.WINDFURY,),None),('waiting-own',1,3,(),'waiting-death')):
        r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.WEAPON,attack=attack,durability=durability,
            keywords=keywords,deathrattle=body,metadata=metadata()))
    def enemy(c): return c.state.entities[c.state.players[3-c.player_id].weapon_id]
    def ref(c): return EquippedWeaponReference.capture(enemy(c))
    def take(c):
        return () if c.state.players[3-c.player_id].weapon_id is None else (TransferWeapon(ref(c),c.player_id,c.source_id),)
    def wait(c):
        return (RequestChoice(c.player_id,(ChoiceOption('take','Take',(TransferWeapon(ref(c),c.player_id,c.source_id),)),),c.source_id),)
    def two(c):
        original=ref(c)
        return (TransferWeapon(original,c.player_id,c.source_id),TransferWeapon(original,3-c.player_id,c.source_id))
    def expired(c):
        original=ref(c)
        return (Destroy(original.entity_id,c.source_id),TransferWeapon(original,c.player_id,c.source_id))
    def event_wait(c):
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),),c.source_id),)
    r.register_behavior('event-wait',event_wait)
    r.register_card(CardDefinition('watch','Diagnostic transfer listener',CardType.MINION,health=5,
        triggers=(TriggerSpec('weapon_transferred','event-wait'),),metadata=metadata()))
    scripts={
        'setup':lambda c:(ModifyWeapon(enemy(c).id,attack=4,durability=-1,source_id=c.source_id),
            GrantKeyword(enemy(c).id,Keyword.LIFESTEAL,source_id=c.source_id)),
        'temporary':lambda c:(GrantKeyword(enemy(c).id,Keyword.LIFESTEAL,source_id=c.source_id,expires_turn=c.state.turn),),
        'take':take,'wait':wait,'two':two,'expired':expired,
        'same':lambda c:(TransferWeapon(EquippedWeaponReference.capture(c.state.entities[c.state.players[c.player_id].weapon_id]),c.player_id,c.source_id),),
        'system':lambda c:(TransferWeapon(ref(c),c.player_id),),
        'fault':lambda c:(*take(c),InvokeBehavior('explode',c.source_id,c.player_id)),
        'bad-source':lambda c:(TransferWeapon(ref(c),c.player_id,999999),),
        'bad-face':lambda c:(TransferWeapon(replace(ref(c),card_id='plain'),c.player_id,c.source_id),),
        'unknown-face':lambda c:(TransferWeapon(replace(ref(c),card_id='unknown'),c.player_id,c.source_id),),
        'destroy-own':lambda c:(Destroy(c.state.players[c.player_id].weapon_id,c.source_id),),
    }
    for name,script in scripts.items():
        r.register_behavior(name,script)
        r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.SPELL,on_play=name,metadata=metadata()))
    raw=next(x for x in evidence()['records'] if x['id']=='DRG_082')
    r.register_behavior('stickyfinger',take)
    r.register_card(CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        on_play='stickyfinger',metadata=metadata_from_record(raw)))
    return r

class WeaponTransferTests(unittest.TestCase):
    def game(self,hand=('take',),own=None,enemy='weapon',board=()):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*6,
            weapon_card_id=own,max_mana=10,mana=10),PlayerSetup('hero',hand=('take',),board=('plain',),deck=('plain',)*6,
            weapon_card_id=enemy,max_mana=10,mana=10)),seed=148),registry())
    def hero(self,g,p=1): return g.state.entities[g.state.players[p].hero_id]
    def weapon(self,g,p=1):
        identity=g.state.players[p].weapon_id
        return None if identity is None else g.state.entities[identity]
    def play(self,g,name):
        p=g.state.active_player; card=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(p,card))
    def transfers(self,g): return [e for e in g.events if e.kind=='weapon_transferred']
    def portable(self,g):
        s=g.snapshot()
        for h in (Game.from_snapshot(json.loads(json.dumps(s)),registry()),g.clone(),replay(build_replay(g),registry())):
            self.assertEqual(h.snapshot(),s)
            for p in (1,2):
                self.assertEqual(h.observe(p),g.observe(p)); self.assertEqual(h.player_events(p),g.player_events(p))
        return s
    def attack(self,g): return g.apply(Attack(1,self.hero(g).id,g.state.players[2].board[0]))

    def test_one_real_adapter_keeps_two_full_raw_rows_and_no_special_take_return_body(self):
        value=evidence(); self.assertEqual(len(value['records']),2); self.assertFalse(value['CN_calibrated'])
        self.assertEqual(value['new_combinations'],0); self.assertNotIn('DEEP_012',registry().cards)
        self.assertIn('pirate',registry().card('DRG_082').metadata.tribes)
        g=self.game(hand=('DRG_082',)); original=self.weapon(g,2).id; self.play(g,'DRG_082')
        self.assertEqual((self.weapon(g).id,g.state.players[1].mana,len(g.state.play_history)),(original,5,1))
        self.assertIsNone(self.weapon(g,2)); self.portable(g)

    def test_transfer_preserves_original_entity_owner_and_current_material(self):
        g=self.game(hand=('setup','take')); self.play(g,'setup'); before=self.weapon(g,2); allocation=g.state.next_entity_id
        self.play(g,'take'); after=self.weapon(g)
        self.assertEqual((after.id,after.owner,after.controller,after.attack,after.durability),(before.id,2,1,7,1))
        self.assertEqual((after.enchantments,after.abilities),(before.enchantments,before.abilities))
        self.assertEqual(g.state.next_entity_id,allocation); self.assertIn(Keyword.LIFESTEAL,after.keywords); self.portable(g)

    def test_new_installation_invalidates_old_epoch_and_order(self):
        g=self.game(); ref=EquippedWeaponReference.capture(self.weapon(g,2)); self.play(g,'take'); after=self.weapon(g)
        self.assertEqual(after.zone_epoch,ref.zone_epoch+1); self.assertGreater(after.entered_order,ref.entered_order)
        self.assertEqual(weapon_transfer_reference(self.transfers(g)[0]),ref); self.portable(g)

    def test_source_departure_is_not_destruction_or_deathrattle(self):
        g=self.game(); original=self.weapon(g,2).id; self.play(g,'take')
        self.assertFalse(g.state.death_history); self.assertEqual(self.hero(g,2).armor,0)
        self.assertFalse(any(e.kind=='weapon_destroyed' and e.target_id==original for e in g.events)); self.portable(g)

    def test_existing_destination_weapon_uses_ordinary_replacement_death(self):
        g=self.game(own='own'); old=self.weapon(g).id; incoming=self.weapon(g,2).id; self.play(g,'take')
        self.assertEqual((self.weapon(g).id,self.hero(g).armor,self.hero(g,2).armor),(incoming,1,0))
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        self.assertEqual([d.entity_id for d in g.state.death_history],[old]); self.portable(g)

    def test_empty_source_real_battlecry_still_pays_once(self):
        g=self.game(hand=('DRG_082',),enemy=None); self.play(g,'DRG_082')
        self.assertEqual(g.state.players[1].mana,5); self.assertFalse(self.transfers(g)); self.assertIsNone(self.weapon(g)); self.portable(g)

    def test_same_controller_request_is_noop_without_new_installation(self):
        g=self.game(hand=('same',),own='own'); before=self.weapon(g); self.play(g,'same')
        self.assertEqual(self.weapon(g),before); self.assertFalse(self.transfers(g)); self.portable(g)

    def test_transferred_equipment_refreshes_active_hero_contribution(self):
        g=self.game(hand=('setup','take')); self.play(g,'setup'); self.play(g,'take')
        self.assertEqual(self.hero(g).attack,7); self.assertIn(Keyword.LIFESTEAL,self.hero(g).keywords)
        self.assertEqual(self.hero(g,2).weapon_attack,0); self.portable(g)

    def test_transfer_does_not_reset_already_used_hero_attack(self):
        g=self.game(own='own'); self.attack(g); self.assertEqual(self.hero(g).attacks_this_turn,1); self.play(g,'take')
        self.assertEqual(self.hero(g).attacks_this_turn,1); before=g.snapshot()
        with self.assertRaises(IllegalAction): self.attack(g)
        self.assertEqual(g.snapshot(),before); self.portable(g)

    def test_incoming_windfury_changes_limit_without_resetting_actual_used_count(self):
        g=self.game(own='own',enemy='wind'); self.attack(g); self.play(g,'take')
        self.assertEqual(self.hero(g).attacks_this_turn,1); self.attack(g)
        self.assertEqual((self.hero(g).attacks_this_turn,self.weapon(g).durability),(2,2)); self.portable(g)

    def test_last_durability_and_deathrattle_now_belong_to_new_controller(self):
        g=self.game(hand=('setup','take')); self.play(g,'setup'); original=self.weapon(g,2).id; self.play(g,'take'); self.attack(g)
        self.assertIsNone(self.weapon(g)); self.assertEqual((self.hero(g).armor,self.hero(g,2).armor),(7,0))
        death=next(d for d in g.state.death_history if d.entity_id==original)
        self.assertEqual(death.controller,1); self.portable(g)

    def test_actual_turn_expiry_keeps_original_temporary_keyword_deadline(self):
        g=self.game(hand=('temporary','take')); self.play(g,'temporary'); before=self.weapon(g,2).abilities; self.play(g,'take')
        self.assertEqual(self.weapon(g).abilities,before); self.assertIn(Keyword.LIFESTEAL,self.weapon(g).keywords)
        g.apply(EndTurn(1)); self.assertNotIn(Keyword.LIFESTEAL,self.weapon(g).keywords); self.portable(g)

    def test_transfer_back_preserves_original_owner_and_two_installations(self):
        g=self.game(); original=self.weapon(g,2).id; self.play(g,'take'); first_epoch=self.weapon(g).zone_epoch
        g.apply(EndTurn(1)); self.play(g,'take')
        self.assertEqual((self.weapon(g,2).id,self.weapon(g,2).owner,self.weapon(g,2).controller),(original,2,2))
        self.assertEqual(self.weapon(g,2).zone_epoch,first_epoch+1); self.assertIsNone(self.weapon(g)); self.portable(g)

    def test_old_reference_cannot_transfer_the_new_installation(self):
        g=self.game(hand=('two',)); self.play(g,'two')
        self.assertIsNotNone(self.weapon(g)); self.assertIsNone(self.weapon(g,2)); self.assertEqual(len(self.transfers(g)),1)
        self.assertTrue(any(e.kind=='effect_skipped' and dict(e.data).get('reason')=='stale_equipped_weapon' for e in g.events)); self.portable(g)

    def test_destroyed_source_is_not_recreated_by_later_transfer_request(self):
        g=self.game(hand=('expired',)); original=self.weapon(g,2).id; self.play(g,'expired')
        self.assertIsNone(self.weapon(g)); self.assertIsNone(self.weapon(g,2)); self.assertFalse(self.transfers(g))
        self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD); self.portable(g)

    def test_typed_reference_waiting_frame_restores_then_transfers_same_entity(self):
        g=self.game(hand=('wait',)); original=self.weapon(g,2).id; self.play(g,'wait'); snapshot=self.portable(g)
        h=Game.from_snapshot(deepcopy(snapshot),registry()); action=SelectChoice(1,g.state.pending_choice.id,('take',))
        g.apply(action); h.apply(action); self.assertEqual(g.snapshot(),h.snapshot()); self.assertEqual(self.weapon(g).id,original); self.portable(g)

    def test_old_weapon_replacement_waits_after_completed_transfer_and_restores(self):
        g=self.game(own='waiting-own'); incoming=self.weapon(g,2).id; self.play(g,'take'); snapshot=self.portable(g)
        self.assertEqual(self.weapon(g).id,incoming); self.assertIsNone(self.weapon(g,2))
        h=Game.from_snapshot(deepcopy(snapshot),registry()); action=SelectChoice(1,g.state.pending_choice.id,('ok',))
        g.apply(action); h.apply(action); self.assertEqual(g.snapshot(),h.snapshot()); self.assertEqual(self.hero(g).armor,1); self.portable(g)

    def test_transferred_event_callbacks_remain_portable_while_another_capture_is_queued(self):
        g=self.game(board=('watch','watch')); self.play(g,'take'); snapshot=self.portable(g)
        h=Game.from_snapshot(deepcopy(snapshot),registry())
        for _ in range(2):
            action=SelectChoice(1,g.state.pending_choice.id,('ok',)); g.apply(action); h.apply(action)
            self.assertEqual(g.snapshot(),h.snapshot()); self.portable(g)
        self.assertEqual(self.hero(g).armor,2)

    def test_action_failure_and_later_choice_failure_keep_correct_transaction_boundary(self):
        g=self.game(hand=('fault',),own='own'); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'fault')
        self.assertEqual(g.snapshot(),before)
        h=self.game(own='waiting-own'); self.play(h,'take'); before=h.snapshot()
        with self.assertRaises(ResolutionError): h.apply(SelectChoice(1,h.state.pending_choice.id,('fault',)))
        self.assertEqual(h.snapshot(),before); self.portable(h)

    def test_unknown_source_unknown_definition_and_non_weapon_reference_reject(self):
        for name in ('bad-source','unknown-face','bad-face'):
            with self.subTest(name=name):
                g=self.game(hand=(name,)); before=g.snapshot()
                with self.assertRaises(ResolutionError): self.play(g,name)
                self.assertEqual(g.snapshot(),before)

    def test_reference_and_effect_inputs_are_strict_and_capture_is_pure(self):
        g=self.game(); before=g.snapshot(); ref=EquippedWeaponReference.capture(self.weapon(g,2))
        self.assertEqual(g.snapshot(),before)
        for change in ({'player_id':True},{'zone_epoch':-1},{'entered_order':0},{'entity_id':0}):
            with self.subTest(change=change),self.assertRaises(ValueError): replace(ref,**change)
        with self.assertRaises(ValueError): EquippedWeaponReference.capture(self.hero(g))
        with self.assertRaises(ValueError): TransferWeapon(ref,True)
        with self.assertRaises(ValueError): TransferWeapon(ref.entity_id,1)

    def test_source_less_transfer_has_explicit_new_controller_and_public_target(self):
        g=self.game(hand=('system',)); self.play(g,'system'); event=self.transfers(g)[0]
        self.assertIsNone(event.source_id); self.assertEqual((event.player_id,event.target_id),(1,self.weapon(g).id)); self.portable(g)

    def test_transfer_envelope_rejects_changed_installation_and_same_controller(self):
        g=self.game(); self.play(g,'take'); event=self.transfers(g)[0]; ref=weapon_transfer_reference(event)
        for bad in (replace(event,amount=2),replace(event,player_id=ref.player_id),replace(event,target_id=True),replace(event,data=())):
            with self.subTest(bad=bad),self.assertRaises(ValueError): weapon_transfer_reference(bad)

    def test_rehashed_snapshot_rejects_changed_epoch_missing_source_and_old_schema(self):
        g=self.game(); self.play(g,'take'); snapshot=self.portable(g)
        for mode in ('epoch','owner','source'):
            bad=deepcopy(snapshot); event=next(e for e in bad['events'] if e['kind']=='weapon_transferred')
            if mode=='epoch': event['data']['new_zone_epoch']+=1
            elif mode=='owner': event['data']['owner_id']=1
            else: event['source_id']=999999
            bad['events_hash']=canonical_hash(bad['events'])
            with self.subTest(mode=mode),self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())
        bad=deepcopy(snapshot); bad['schema_version']=244
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())

    def test_player_view_keeps_visible_physical_handle_without_private_reference(self):
        g=self.game(); before=g.for_player(1).observe()['observation']['players'][1]['weapon']['ref']; self.play(g,'take')
        snapshot=g.snapshot()
        for p in (1,2):
            view=g.for_player(p).observe()['observation']; events=g.player_events(p)
            self.assertEqual(view['version'],VIEW_VERSION); self.assertIsNone(view['players'][1]['weapon'])
            self.assertEqual(view['players'][0]['weapon']['card_id'],'weapon')
            text=json.dumps(events)
            for private in ('new_zone_epoch','new_entered_order','owner_id','"weapon":'):
                self.assertNotIn(private,text)
        self.assertEqual(g.observe(1)['players'][0]['weapon']['ref'],before); self.assertEqual(g.snapshot(),snapshot); self.portable(g)

if __name__=='__main__': unittest.main()
