"""One Likkim and the original owed/locked accounts, stats and equipment."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,EquippedWeaponReference,
    Game,Keyword,PlayCard,PlayerSetup,Registry,ResolutionError,Scenario,SelectChoice,SnapshotError,
    StatRelationLayer,StatRelationOperand,StatRelationSpec,TriggerSpec,Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,Destroy,EquipWeapon,GainArmor,
    InvokeBehavior,ModifyWeapon,Overload,RequestChoice,TransferWeapon,UnlockOverload)
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.stat_relations import GrantStatRelation,conditional_attack
from hs_sim.engine.zones import CardReference,CopyCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

CARD='TRL_352'
PIN='d3b5ae342aca628d47d4f2725b73a40a1f90e3c6eef0bad133df7ac8f928b023'
REL=StatRelationSpec(operand=StatRelationOperand.CONTROLLER_OVERLOADED_MANA,
    layer=StatRelationLayer.CONDITIONAL_ATTACK,amount=2)


def evidence():
    data=json.loads((Path(__file__).resolve().parents[1]/'data/support/overload-weapon-attack-basics.json').read_bytes())
    if canonical_digest(data)!=PIN:raise ValueError('Complete overload weapon evidence changed')
    for row in data['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Raw overload weapon changed')
    return data


def registry():
    r=Registry('isolated-overload-presence-weapon-attack-v1')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata(tribes=())))
    raw=evidence()['records'][0]['data']
    r.register_card(CardDefinition(CARD,raw['name'],CardType.WEAPON,cost=raw['cost'],attack=raw['attack'],
        durability=raw['health'],stat_relations=(REL,),metadata=metadata_from_record(raw)))
    r.register_card(CardDefinition('axe','Axe',CardType.WEAPON,attack=4,durability=2,metadata=metadata(tribes=())))
    r.register_card(CardDefinition('plain','Plain',CardType.MINION,attack=1,health=20,metadata=metadata(tribes=())))
    def wid(c):return c.state.players[c.player_id].weapon_id
    def choice(c):
        return (RequestChoice(c.player_id,(
            ChoiceOption('clear','Clear overload',(UnlockOverload(c.player_id),)),
            ChoiceOption('add','Add overload',(Overload(c.player_id,1),)),
            ChoiceOption('fault','Clear then fail',(UnlockOverload(c.player_id),InvokeBehavior('late-fault',c.source_id,c.player_id))),
        ),c.source_id),)
    scripts={
        'add':lambda c:(Overload(c.player_id,1),),
        'more':lambda c:(Overload(c.player_id,2),),
        'zero':lambda c:(Overload(c.player_id,0),),
        'clear':lambda c:(UnlockOverload(c.player_id),),
        'unlock':lambda c:(UnlockOverload(c.player_id,False),),
        'buff':lambda c:(ModifyWeapon(wid(c),attack=2,source_id=c.source_id),),
        'negative':lambda c:(ModifyWeapon(wid(c),attack=-5,source_id=c.source_id),),
        'hero-buff':lambda c:(Buff(c.state.players[c.player_id].hero_id,3,source_id=c.source_id),),
        'wear':lambda c:(ModifyWeapon(wid(c),durability=-2,source_id=c.source_id),),
        'kill':lambda c:(Destroy(wid(c),c.source_id),),
        'equip':lambda c:(EquipWeapon(c.player_id,CARD),),
        'replace':lambda c:(EquipWeapon(c.player_id,'axe'),),
        'take':lambda c:(TransferWeapon(EquippedWeaponReference.capture(c.state.entities[c.state.players[3-c.player_id].weapon_id]),c.player_id,c.source_id),),
        'copy':lambda c:(CopyCard(CardReference.capture(next(c.state.entities[i]
            for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==CARD)),2,Zone.HAND),),
        'wait':choice,
        'fault':lambda c:(UnlockOverload(c.player_id),InvokeBehavior('late-fault',c.source_id,c.player_id)),
    }
    for name,body in scripts.items():
        r.register_behavior(name,body);r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,metadata=metadata(tribes=())))
    r.register_behavior('late-fault',lambda c:(AddToHand(c.player_id,'unknown.overload-weapon'),))
    r.register_behavior('declared',lambda c:choice(c) if c.event.source_id==c.state.players[c.player_id].hero_id else ())
    r.register_card(CardDefinition('watcher','Declaration listener',CardType.MINION,health=5,
        triggers=(TriggerSpec('attack_declared','declared'),),metadata=metadata(tribes=())))
    def observe(c):
        if c.event.player_id!=c.player_id:return ()
        weapon=c.state.entities[c.state.players[c.player_id].weapon_id]
        hero=c.state.entities[c.state.players[c.player_id].hero_id]
        if weapon.attack!=hero.weapon_attack:raise ValueError('Stale normalized weapon contribution')
        return (GainArmor(3-c.player_id,weapon.attack),)
    r.register_behavior('observe',observe)
    r.register_card(CardDefinition('observer','Mana event listener',CardType.MINION,health=5,
        triggers=(TriggerSpec('mana_changed','observe'),),metadata=metadata(tribes=())))
    r.register_behavior('clear-after-damage',lambda c:(UnlockOverload(c.player_id),)
        if c.event.source_id==c.state.players[c.player_id].hero_id else ())
    r.register_card(CardDefinition('damage-watch','Prepared damage listener',CardType.MINION,health=5,
        triggers=(TriggerSpec('damage_dealt','clear-after-damage'),),metadata=metadata(tribes=())))
    return r


class OverloadWeaponAttackBasicsTests(unittest.TestCase):
    def game(self,hand=(),*,owed=0,locked=0,enemy_owed=0,enemy_locked=0,weapon=CARD,enemy_weapon=None,board=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*4,weapon_card_id=weapon,
                overload_owed=owed,overload_locked=locked,mana=10-locked,max_mana=10),
            PlayerSetup('hero',deck=('plain',)*4,weapon_card_id=enemy_weapon,
                overload_owed=enemy_owed,overload_locked=enemy_locked,mana=10-enemy_locked,max_mana=10),
        ),seed=53),registry())
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def weapon(self,g,p=1):return g.state.entities[g.state.players[p].weapon_id]
    def cast(self,g,name):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(1,eid))
    def choose(self,g,name):q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(name,)))
    def values(self,g,attack,bonus,p=1):
        self.assertEqual((self.weapon(g,p).attack,self.weapon(g,p).conditional_attack),(attack,bonus))
        self.assertEqual(self.hero(g,p).weapon_attack,attack if g.state.active_player==p else 0)
    def attack(self,g):return g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));restored=Game.from_snapshot(saved,registry())
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return restored
    def reject(self,saved):
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())

    def test_complete_raw_pin_and_only_necessary_likkim(self):
        data=evidence();card=registry().card(CARD)
        self.assertEqual(data['new_real_card_adapters'],[CARD])
        self.assertEqual((card.cost,card.attack,card.durability,card.stat_relations),(2,1,3,(REL,)))
        self.assertEqual(card.metadata.classes,('shaman',))

    def test_closed_native_weapon_spec_and_no_new_grant(self):
        for changes in ({'amount':0},{'amount':True},{'layer':StatRelationLayer.FINAL_ATTACK},{'card_count':1},{'count_tribe':'naga'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(REL,**changes)
        with self.assertRaises(ValueError):GrantStatRelation(1,REL,1)
        with self.assertRaises(ValueError):Registry('bad').register_card(CardDefinition('bad','Bad',CardType.MINION,
            health=3,keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',),
            stat_relations=(REL,),metadata=metadata(tribes=('mech',))))
        with self.assertRaises(ValueError):Registry('mixed').register_card(CardDefinition('bad','Bad',CardType.WEAPON,
            durability=2,stat_relations=(REL,StatRelationSpec()),metadata=metadata(tribes=())))

    def test_pending_locked_and_both_are_presence_not_quantity(self):
        for owed,locked,attack in ((0,0,1),(1,0,3),(0,1,3),(2,4,3)):
            with self.subTest(owed=owed,locked=locked):
                g=self.game(owed=owed,locked=locked,enemy_owed=8);self.values(g,attack,attack-1);self.portable(g)

    def test_add_clear_and_zero_keep_original_account_and_history(self):
        g=self.game(('zero','add','more','clear'));before=g.snapshot()['rng_state'];self.cast(g,'zero');self.values(g,1,0)
        self.assertEqual(g.state.overload_history,[]);self.cast(g,'add');self.values(g,3,2)
        self.cast(g,'more');self.values(g,3,2);self.assertEqual(g.state.players[1].overload_owed,3)
        self.cast(g,'clear');self.values(g,1,0);self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)

    def test_unlock_only_preserves_pending_and_clear_both_removes_bonus(self):
        g=self.game(('unlock','clear'),owed=2,locked=1);self.cast(g,'unlock');self.values(g,3,2)
        self.assertEqual((g.state.players[1].overload_owed,g.state.players[1].overload_locked),(2,0))
        self.cast(g,'clear');self.values(g,1,0);self.portable(g)

    def test_real_turn_transition_moves_owed_to_locked_then_releases(self):
        g=self.game(owed=1);g.apply(EndTurn(1));self.values(g,3,2)
        g.apply(EndTurn(2));self.values(g,3,2);self.assertEqual((g.state.players[1].overload_owed,g.state.players[1].overload_locked),(0,1))
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.values(g,1,0);self.portable(g)

    def test_only_current_controller_account_and_active_hero_contribution(self):
        g=self.game(enemy_owed=1,enemy_weapon=CARD);self.values(g,1,0);self.values(g,3,2,2)
        g.apply(EndTurn(1));self.values(g,1,0);self.values(g,3,2,2);self.portable(g)

    def test_ordinary_weapon_modification_is_additive_and_survives_condition_loss(self):
        g=self.game(('buff','clear'),owed=1);self.cast(g,'buff');self.values(g,5,2)
        self.assertEqual(self.weapon(g).base_attack,1);self.cast(g,'clear');self.values(g,3,0);self.portable(g)

    def test_zero_floor_is_after_ordinary_and_conditional_sum(self):
        g=self.game(('negative','clear'),owed=1);self.cast(g,'negative');self.values(g,0,2)
        self.cast(g,'clear');self.values(g,0,0);self.portable(g)

    def test_hero_own_numeric_attack_remains_separate(self):
        g=self.game(('hero-buff','clear'),owed=1);self.cast(g,'hero-buff');self.assertEqual(self.hero(g).attack,6)
        self.cast(g,'clear');self.assertEqual(self.hero(g).attack,4);self.portable(g)

    def test_play_and_equip_use_same_relation_and_original_cost(self):
        for card in (CARD,'equip'):
            with self.subTest(card=card):
                g=self.game((card,),weapon=None,owed=1);self.cast(g,card);self.values(g,3,2)
                self.assertEqual(g.state.players[1].mana,8 if card==CARD else 10);self.portable(g)

    def test_physical_transfer_reads_new_controller_account(self):
        g=self.game(('take',),weapon=None,enemy_weapon=CARD,enemy_owed=1);old=self.weapon(g,2).id
        self.cast(g,'take');self.assertEqual(self.weapon(g).id,old);self.values(g,1,0);self.portable(g)

    def test_current_hand_copy_recomputes_new_controller_resource_bonus(self):
        g=self.game((CARD,'copy'),weapon=None,owed=1)
        original=g.state.entities[g.state.players[1].hand[0]];self.assertEqual(original.attack,3);self.cast(g,'copy')
        copied=g.state.entities[g.state.players[2].hand[0]]
        self.assertEqual((copied.card_id,copied.attack,copied.conditional_attack),(CARD,1,0))
        self.assertEqual((original.attack,original.conditional_attack),(3,2));self.portable(g)

    def test_resource_event_context_sees_updated_weapon_and_hero(self):
        g=self.game(('add','clear'),board=('observer',));self.cast(g,'add');self.values(g,3,2)
        self.assertEqual(self.hero(g,2).armor,3);self.cast(g,'clear');self.values(g,1,0)
        self.assertEqual(self.hero(g,2).armor,4);self.portable(g)

    def test_declared_wait_restores_then_reads_current_attack_before_damage(self):
        g=self.game(owed=1,board=('watcher',));self.attack(g);self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g)
        for branch in (g,restored):
            self.choose(branch,'clear');self.values(branch,1,0)
            self.assertEqual((self.hero(branch,2).damage,self.weapon(branch).durability,self.hero(branch).attacks_this_turn),(1,2,1));self.portable(branch)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_accepted_damage_is_not_repriced_after_later_resource_clear(self):
        g=self.game(owed=1,board=('damage-watch',));self.attack(g);self.values(g,1,0)
        self.assertEqual((self.hero(g,2).damage,self.weapon(g).durability),(3,2));self.portable(g)

    def test_last_wear_and_later_clear_preserve_frozen_death_attack(self):
        g=self.game(('wear','clear'),owed=1);old=self.weapon(g).id;self.cast(g,'wear');self.attack(g)
        self.assertIsNone(g.state.players[1].weapon_id);self.assertEqual(self.hero(g).weapon_attack,0)
        record=next(r for r in g.state.death_history if r.entity_id==old);self.assertEqual(record.attack,3)
        self.cast(g,'clear');self.assertEqual(record.attack,3);self.portable(g)

    def test_replace_and_destroy_remove_old_equipment_contribution(self):
        for card,attack in (('replace',4),('kill',0)):
            with self.subTest(card=card):
                g=self.game((card,),owed=1);self.cast(g,card);self.assertEqual(self.hero(g).weapon_attack,attack);self.portable(g)

    def test_immediate_and_waiting_failure_restore_resource_and_cache(self):
        g=self.game(('fault',),owed=1);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.cast(g,'fault')
        self.assertEqual(g.snapshot(),before)
        g=self.game(('wait',),owed=1);self.cast(g,'wait');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_original_context_keeps_its_own_account_and_rejects_stale_cache(self):
        g=self.game(('clear',),owed=1);wid=self.weapon(g).id;context=RuleContext(g.state,wid,1);self.cast(g,'clear')
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);old=codec.decode(codec.encode(context))
        self.assertEqual(old.state.entities[wid].attack,3)
        bad=deepcopy(context.state);bad.entities[wid].conditional_attack=0
        with self.assertRaises(ValueError):codec.encode(RuleContext(bad,wid,1))

    def test_rehashed_saved_cache_scope_and_duplicate_are_rejected(self):
        g=self.game(owed=1);saved=g.snapshot();wid=str(self.weapon(g).id)
        for mode in ('cache','amount','grant','duplicate'):
            with self.subTest(mode=mode):
                bad=deepcopy(saved);entity=bad['state']['entities'][wid];ability=next(a for a in entity['abilities'] if a['kind']=='stat_relation')
                if mode=='cache':entity['conditional_attack']=0
                elif mode=='amount':ability['stat_relation']['amount']=3
                elif mode=='grant':ability['origin']='granted'
                else:
                    extra=deepcopy(ability);extra['id']=bad['state']['next_attachment_id'];bad['state']['next_attachment_id']+=1;entity['abilities'].append(extra)
                self.reject(bad)

    def test_pure_query_and_player_interfaces_hide_formula_and_private_frame(self):
        g=self.game(owed=1);before=g.snapshot();self.assertEqual(conditional_attack(g.state,self.weapon(g),g.registry),2)
        for p in (1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.for_player(p).legal_actions())
            for key in ('controller_overloaded_mana','conditional_attack','stat_relation','resolution_frame'):
                self.assertNotIn('"'+key+'"',public)
        self.assertEqual(g.snapshot(),before)
