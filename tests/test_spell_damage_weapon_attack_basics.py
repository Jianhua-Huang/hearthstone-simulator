"""Spirit Claws reuses the existing all-school Spell Damage presence query."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,EquippedWeaponReference,
    Game,PlayCard,PlayerSetup,Registry,ResolutionError,Scenario,SelectChoice,SnapshotError,
    SpellSchool,StatRelationLayer,StatRelationOperand,StatRelationSpec,TriggerSpec,Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.dormancy import AwakenMinion,MakeDormant
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,
    EquipWeapon,GainArmor,InvokeBehavior,ModifyWeapon,RequestChoice,ReturnToHand,Silence,
    Summon,TransferWeapon,Transform)
from hs_sim.engine.health_rules import spell_bonus
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.stat_relations import GrantStatRelation,conditional_attack
from hs_sim.engine.zones import CardReference,CopyCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

CARD='KAR_063'
PIN='9abf50026408c97570da70e45153bbaefa6c2e6cf55be5e56a92df163698cde1'
REL=StatRelationSpec(operand=StatRelationOperand.CONTROLLER_HAS_SPELL_DAMAGE,
    layer=StatRelationLayer.CONDITIONAL_ATTACK,amount=2)
PROVIDERS=('generic','school','large')


def evidence():
    data=json.loads((Path(__file__).resolve().parents[1]/'data/support/spell-damage-weapon-attack-basics.json').read_bytes())
    if canonical_digest(data)!=PIN:raise ValueError('Complete Spell Damage weapon evidence changed')
    for row in data['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Raw Spell Damage weapon changed')
    return data


def registry():
    r=Registry('isolated-spell-damage-presence-weapon-attack-v1')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata(tribes=())))
    raw=evidence()['records'][0]['data']
    r.register_card(CardDefinition(CARD,raw['name'],CardType.WEAPON,cost=raw['cost'],attack=raw['attack'],
        durability=raw['health'],stat_relations=(REL,),metadata=metadata_from_record(raw)))
    r.register_card(CardDefinition('axe','Axe',CardType.WEAPON,attack=4,durability=2,metadata=metadata(tribes=())))
    r.register_card(CardDefinition('plain','Plain',CardType.MINION,attack=1,health=20,metadata=metadata(tribes=())))
    for cid,amount,schools in (('generic',1,()),('school',2,(SpellSchool.NATURE,)),('large',4,())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=5,
            spell_damage=amount,spell_damage_schools=schools,metadata=metadata(tribes=())))
    def source(c):return next(i for i in c.state.players[1].board if c.state.entities[i].card_id in PROVIDERS)
    def wid(c):return c.state.players[c.player_id].weapon_id
    def choice(c):
        sid=source(c)
        return (RequestChoice(c.player_id,(
            ChoiceOption('silence','Remove provider',(Silence(sid),)),
            ChoiceOption('keep','Keep provider',()),
            ChoiceOption('fault','Remove then fail',(Silence(sid),InvokeBehavior('late-fault',c.source_id,c.player_id))),
        ),c.source_id),)
    scripts={
        'summon':lambda c:(Summon(c.player_id,'generic'),),
        'silence':lambda c:(Silence(source(c)),),
        'sleep':lambda c:(MakeDormant(source(c),None),),
        'wake':lambda c:(AwakenMinion(source(c)),),
        'destroy-source':lambda c:(Destroy(source(c),c.source_id),),
        'lethal-source':lambda c:(Damage(source(c),99,c.source_id),),
        'bounce':lambda c:(ReturnToHand(source(c)),),
        'transform':lambda c:(Transform(source(c),'plain'),),
        'give-source':lambda c:(ChangeControl(source(c),2),),
        'buff':lambda c:(ModifyWeapon(wid(c),attack=2,source_id=c.source_id),),
        'negative':lambda c:(ModifyWeapon(wid(c),attack=-2,source_id=c.source_id),),
        'hero-buff':lambda c:(Buff(c.state.players[c.player_id].hero_id,3,source_id=c.source_id),),
        'wear':lambda c:(ModifyWeapon(wid(c),durability=-2,source_id=c.source_id),),
        'kill':lambda c:(Destroy(wid(c),c.source_id),),
        'equip':lambda c:(EquipWeapon(c.player_id,CARD),),
        'replace':lambda c:(EquipWeapon(c.player_id,'axe'),),
        'take':lambda c:(TransferWeapon(EquippedWeaponReference.capture(c.state.entities[c.state.players[2].weapon_id]),1,c.source_id),),
        'copy':lambda c:(CopyCard(CardReference.capture(next(c.state.entities[i]
            for i in c.state.players[1].hand if c.state.entities[i].card_id==CARD)),2,Zone.HAND),),
        'wait':choice,
        'fault':lambda c:(Silence(source(c)),InvokeBehavior('late-fault',c.source_id,c.player_id)),
    }
    for name,body in scripts.items():
        r.register_behavior(name,body);r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,metadata=metadata(tribes=())))
    r.register_behavior('late-fault',lambda c:(AddToHand(c.player_id,'unknown.spell-damage-weapon'),))
    r.register_behavior('declared',lambda c:choice(c) if c.event.source_id==c.state.players[c.player_id].hero_id else ())
    r.register_card(CardDefinition('watcher','Declaration listener',CardType.MINION,health=5,
        triggers=(TriggerSpec('attack_declared','declared'),),metadata=metadata(tribes=())))
    def observe(c):
        if c.event.player_id!=c.player_id:return ()
        weapon=c.state.entities[c.state.players[c.player_id].weapon_id]
        hero=c.state.entities[c.state.players[c.player_id].hero_id]
        if weapon.attack!=hero.weapon_attack:raise ValueError('Stale normalized weapon contribution')
        return (GainArmor(2,weapon.attack),)
    r.register_behavior('observe',observe)
    r.register_card(CardDefinition('observer','Source event listener',CardType.MINION,health=5,
        triggers=(TriggerSpec('minion_summoned','observe'),TriggerSpec('silenced','observe')),metadata=metadata(tribes=())))
    r.register_behavior('silence-after-damage',lambda c:(Silence(source(c)),)
        if c.event.source_id==c.state.players[c.player_id].hero_id else ())
    r.register_card(CardDefinition('damage-watch','Prepared damage listener',CardType.MINION,health=5,
        triggers=(TriggerSpec('damage_dealt','silence-after-damage'),),metadata=metadata(tribes=())))
    return r


class SpellDamageWeaponAttackBasicsTests(unittest.TestCase):
    def game(self,hand=(),*,board=('generic',),enemy=(),weapon=CARD,enemy_weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*4,weapon_card_id=weapon,mana=10,max_mana=10),
            PlayerSetup('hero',board=enemy,deck=('plain',)*4,weapon_card_id=enemy_weapon,mana=10,max_mana=10),
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

    def test_complete_raw_pin_and_only_necessary_spirit_claws(self):
        data=evidence();card=registry().card(CARD)
        self.assertEqual(data['new_real_card_adapters'],[CARD])
        self.assertEqual((card.cost,card.attack,card.durability,card.stat_relations),(1,1,3,(REL,)))
        self.assertEqual(card.metadata.classes,('shaman',))

    def test_closed_native_weapon_spec_and_no_grant(self):
        for changes in ({'amount':0},{'amount':True},{'layer':StatRelationLayer.FINAL_ATTACK},{'card_count':1},{'count_tribe':'naga'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(REL,**changes)
        with self.assertRaises(ValueError):GrantStatRelation(1,REL,1)
        with self.assertRaises(ValueError):Registry('bad').register_card(CardDefinition('bad','Bad',CardType.MINION,
            health=3,stat_relations=(REL,),metadata=metadata(tribes=())))
        with self.assertRaises(ValueError):Registry('mixed').register_card(CardDefinition('bad','Bad',CardType.WEAPON,
            durability=2,stat_relations=(REL,StatRelationSpec()),metadata=metadata(tribes=())))

    def test_generic_school_and_multiple_sources_give_fixed_bonus(self):
        for board,amount in (((),0),(('plain',),0),(('generic',),1),(('school',),2),(('large',),4),(PROVIDERS,7)):
            with self.subTest(board=board):
                g=self.game(board=board);self.assertEqual(spell_bonus(g.state,1,g.registry),amount)
                self.values(g,3 if amount else 1,2 if amount else 0);self.portable(g)

    def test_source_acquisition_and_last_silence_refresh_event_context(self):
        g=self.game(('summon','silence'),board=('observer',));self.cast(g,'summon');self.values(g,3,2)
        self.assertEqual(self.hero(g,2).armor,3);self.cast(g,'silence');self.values(g,1,0)
        self.assertEqual(self.hero(g,2).armor,4);self.portable(g)

    def test_removing_one_of_multiple_sources_keeps_presence(self):
        g=self.game(('silence',),board=('generic','school'));self.cast(g,'silence');self.values(g,3,2)
        self.assertEqual(spell_bonus(g.state,1,g.registry),2);self.portable(g)

    def test_source_dormancy_and_awaken_recompute_without_new_attachments(self):
        g=self.game(('sleep','wake'),board=('school',));sid=g.state.players[1].board[0]
        ids=[a.id for a in g.state.entities[sid].abilities]
        self.cast(g,'sleep');self.values(g,1,0);self.portable(g)
        self.cast(g,'wake');self.values(g,3,2);self.assertEqual([a.id for a in g.state.entities[sid].abilities],ids);self.portable(g)

    def test_source_death_return_and_transform_remove_presence(self):
        for name in ('destroy-source','lethal-source','bounce','transform'):
            with self.subTest(name=name):
                g=self.game((name,));self.cast(g,name);self.values(g,1,0);self.portable(g)

    def test_source_control_and_only_current_controller_presence(self):
        g=self.game(('give-source',),enemy_weapon=CARD);self.values(g,3,2);self.values(g,1,0,2)
        self.cast(g,'give-source');self.values(g,1,0);self.values(g,3,2,2)
        g.apply(EndTurn(1));self.values(g,1,0);self.values(g,3,2,2);self.portable(g)

    def test_ordinary_weapon_modification_and_hero_own_attack_remain_separate(self):
        g=self.game(('buff','hero-buff','silence'));self.cast(g,'buff');self.values(g,5,2)
        self.cast(g,'hero-buff');self.assertEqual(self.hero(g).attack,8)
        self.cast(g,'silence');self.values(g,3,0);self.assertEqual(self.hero(g).attack,6)
        self.assertEqual(self.weapon(g).base_attack,1);self.portable(g)

    def test_zero_floor_is_after_ordinary_and_conditional_sum(self):
        g=self.game(('negative','silence'));self.cast(g,'negative');self.values(g,1,2)
        self.cast(g,'silence');self.values(g,0,0);self.portable(g)

    def test_manual_play_and_equip_reuse_same_relation_and_original_payment(self):
        for name in (CARD,'equip'):
            with self.subTest(name=name):
                g=self.game((name,),weapon=None);self.cast(g,name);self.values(g,3,2)
                self.assertEqual(g.state.players[1].mana,9 if name==CARD else 10);self.portable(g)

    def test_physical_weapon_transfer_recomputes_new_controller_presence(self):
        g=self.game(('take',),board=(),enemy=('school',),weapon=None,enemy_weapon=CARD);old=self.weapon(g,2).id
        self.cast(g,'take');self.assertEqual(self.weapon(g).id,old);self.values(g,1,0);self.portable(g)

    def test_current_hand_copy_reads_destination_presence(self):
        g=self.game((CARD,'copy'),weapon=None);original=g.state.entities[g.state.players[1].hand[0]]
        self.assertEqual(original.attack,3);self.cast(g,'copy');copied=g.state.entities[g.state.players[2].hand[0]]
        self.assertEqual((copied.card_id,copied.attack,copied.conditional_attack),(CARD,1,0));self.portable(g)

    def test_declared_wait_restore_reads_current_attack_before_damage(self):
        g=self.game(board=('generic','watcher'));self.attack(g);self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g)
        for branch in (g,restored):
            self.choose(branch,'silence');self.values(branch,1,0)
            self.assertEqual((self.hero(branch,2).damage,self.weapon(branch).durability,self.hero(branch).attacks_this_turn),(1,2,1));self.portable(branch)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_prepared_damage_is_not_repriced_by_later_source_silence(self):
        g=self.game(board=('generic','damage-watch'));self.attack(g);self.values(g,1,0)
        self.assertEqual((self.hero(g,2).damage,self.weapon(g).durability),(3,2));self.portable(g)

    def test_last_wear_freezes_death_attack_despite_later_source_loss(self):
        g=self.game(('wear','silence'));old=self.weapon(g).id;self.cast(g,'wear');self.attack(g)
        self.assertIsNone(g.state.players[1].weapon_id);self.assertEqual(self.hero(g).weapon_attack,0)
        record=next(r for r in g.state.death_history if r.entity_id==old);self.assertEqual(record.attack,3)
        self.cast(g,'silence');self.assertEqual(record.attack,3);self.portable(g)

    def test_replace_and_destroy_remove_equipment_contribution(self):
        for name,attack in (('replace',4),('kill',0)):
            with self.subTest(name=name):
                g=self.game((name,));self.cast(g,name);self.assertEqual(self.hero(g).weapon_attack,attack);self.portable(g)

    def test_immediate_and_waiting_failure_restore_source_and_cache(self):
        g=self.game(('fault',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.cast(g,'fault')
        self.assertEqual(g.snapshot(),before)
        g=self.game(('wait',));self.cast(g,'wait');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);restored=self.portable(g)
        self.choose(restored,'silence');self.values(restored,1,0);self.portable(restored)

    def test_original_context_keeps_its_own_source_and_rejects_stale_cache(self):
        g=self.game(('silence',));wid=self.weapon(g).id;context=RuleContext(g.state,wid,1);self.cast(g,'silence')
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);old=codec.decode(codec.encode(context))
        self.assertEqual(old.state.entities[wid].attack,3)
        bad=deepcopy(context.state);bad.entities[wid].conditional_attack=0
        with self.assertRaises(ValueError):codec.encode(RuleContext(bad,wid,1))

    def test_rehashed_cache_native_amount_grant_and_duplicate_are_rejected(self):
        g=self.game();saved=g.snapshot();wid=str(self.weapon(g).id)
        for mode in ('cache','amount','grant','duplicate'):
            with self.subTest(mode=mode):
                bad=deepcopy(saved);entity=bad['state']['entities'][wid];ability=next(a for a in entity['abilities'] if a['kind']=='stat_relation')
                if mode=='cache':entity['conditional_attack']=0
                elif mode=='amount':ability['stat_relation']['amount']=3
                elif mode=='grant':ability['origin']='granted'
                else:
                    extra=deepcopy(ability);extra['id']=bad['state']['next_attachment_id'];bad['state']['next_attachment_id']+=1;entity['abilities'].append(extra)
                self.reject(bad)

    def test_pure_query_and_player_views_hide_formula_and_private_frame(self):
        g=self.game();before=g.snapshot();self.assertEqual(conditional_attack(g.state,self.weapon(g),g.registry),2)
        with self.assertRaises(ValueError):conditional_attack(g.state,self.weapon(g))
        for p in (1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.for_player(p).legal_actions())
            for key in ('controller_has_spell_damage','conditional_attack','stat_relation','resolution_frame'):
                self.assertNotIn('"'+key+'"',public)
        self.assertEqual(g.snapshot(),before)
