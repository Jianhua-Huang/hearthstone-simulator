"""Real Saber combat credit and immutable original board-to-hand base material."""
from copy import deepcopy
from dataclasses import replace
import json,re,unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_combat_copy_cards import SABRE,load_batch
from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,Game,Keyword,LaunchStarship,
    PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial,validate_captured_card_copy
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,ForceAttack,
    GrantKeyword,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.jade import SummonJadeGolem
from hs_sim.engine.model import TargetSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import CombatDamage
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.starships import construction
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference,CopyCard
from hs_sim.targets import canonical_digest

P='k100.';VICTIM=P+'victim';YETI='CORE_CS2_182';TIDE='CORE_EX1_509';WATCH=P+'watch'


def registry():
    r=build_registry()
    # Preserve real artwork already installed by later native content. Only
    # fill an absent fixture definition, after checking the original full face.
    from test_jade_basics import FORMS,evidence as jade_evidence,registry as jade_fixture
    jade=jade_fixture()
    raw=jade_evidence()
    for cid in FORMS:
        if cid in r.cards:
            expected=replace(jade.card(cid),metadata=metadata_from_record(raw[cid]))
            if r.card(cid)!=expected:raise ValueError('Existing real Jade artwork changed its complete original face')
        else:r.register_card(jade.card(cid))
    family=jade.jade_families['jade.classic']
    if family.id in r.jade_families:
        if r.jade_families[family.id]!=family:raise ValueError('Existing real Jade family changed its original declaration')
    else:r.register_jade_family(family)
    def attacker(c):return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==SABRE)
    def force(c):return(ForceAttack(attacker(c),c.target_id,'any_minions'),)
    def reenter(c):return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id),)
    def defer(c):
        target=c.state.entities[c.target_id];material=CapturedCardCopyMaterial.capture(c.state,target)
        copy=CopyCard(material,c.player_id,mode='base',source_id=c.source_id)
        return(RequestChoice(c.player_id,(
            ChoiceOption('continue','Original base copy',(copy,)),
            ChoiceOption('transform','Change the later live face',(Transform(target.id,YETI),copy)),
            ChoiceOption('cycle','Reenter the original physical minion',(ReturnToHand(target.id),InvokeBehavior(P+'reenter',c.source_id,c.player_id,target.id),copy)),
            ChoiceOption('fail','Copy then fail',(copy,InvokeBehavior(P+'fail',c.source_id,c.player_id))),
        ),c.source_id),)
    scripts={
        'force':force,'late_fail':lambda c:(*force(c),InvokeBehavior(P+'fail',c.source_id,c.player_id)),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),'bare':lambda c:(CombatDamage(attacker(c),c.target_id),),
        'poison':lambda c:(GrantKeyword(c.target_id,Keyword.POISONOUS,c.source_id),),
        'shield':lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),),
        'buff':lambda c:(Buff(c.target_id,1,1,c.source_id),),'damage':lambda c:(Damage(c.target_id,1,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),'transform':lambda c:(Transform(c.target_id,VICTIM),),
        'control':lambda c:(ChangeControl(c.target_id,2),),'reenter':reenter,'defer':defer,
        'jade':lambda c:(SummonJadeGolem(2,c.source_id),),
    }
    r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('Deliberate K100 late failure')))
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        targeting=None if name=='jade'else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,targeting=targeting))
    r.register_card(CardDefinition(VICTIM,'Original victim',CardType.MINION,attack=1,health=2))
    r.register_card(CardDefinition(P+'mutual','Mutual lethal',CardType.MINION,attack=3,health=2))
    def watch(c):
        source=c.state.entities[c.event.source_id]
        if source.card_id!=SABRE or c.state.entities[c.event.target_id].kind!=CardType.MINION:return ()
        return(RequestChoice(c.player_id,(
            ChoiceOption('continue','Continue',()),
            ChoiceOption('kill_source','Remove original source',(Destroy(source.id,c.source_id),)),
            ChoiceOption('silence_source','Silence original source',(Silence(source.id),)),
            ChoiceOption('other_victim','A later same-face physical body',(SummonByCard(2,(SummonEntryMaterial(VICTIM),),SummonCause.capture(c)),)),
            ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),)),
        ),c.source_id),)
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,'Original attack boundary',CardType.MINION,health=8,triggers=(TriggerSpec('attack_finished',P+'watch'),)))
    r.validate();return r


class NativeCombatCopyCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(SABRE,),enemy=(VICTIM,),active=1,weapon=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*3,mana=40,max_mana=40,mana_cap=40,weapon_card_id=weapon),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*3,mana=40,max_mana=40,mana_cap=40)),active_player=active,seed=100),self.r)
    def eid(self,g,cid,p=1,zone='board'):
        return next(i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,name,target=None):
        cid=name if name==SABRE else P+name;source=self.eid(g,cid,g.state.active_player,'hand')
        g.apply(PlayCard(g.state.active_player,source,target,position=len(g.state.players[g.state.active_player].board)if cid==SABRE else None));return source
    def attack(self,g,target=None):
        source=self.eid(g,SABRE);target=self.eid(g,VICTIM,2)if target is None else target
        g.apply(Attack(1,source,target));return source,target
    def copies(self,g,origin,p=1):return[g.state.entities[i]for i in g.state.players[p].hand if g.state.entities[i].origin_entity_id==origin]
    def choose(self,g,key='continue'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('CapturedCardCopyMaterial','CopyLocalState','resolution_frame','death_history','next_attachment_id','character_attack_history'):
                self.assertNotIn('"'+key+'"',public)
        return other
    def material_node(self,value):
        if isinstance(value,dict):
            if {'origin','local','components','next_attachment_id','galakrond_invocations','jade_size'}<=set(value)and isinstance(value.get('origin'),dict):return value
            for child in value.values():
                found=self.material_node(child)
                if found is not None:return found
        elif isinstance(value,list):
            for child in value:
                found=self.material_node(child)
                if found is not None:return found

    def copy_node(self,value):
        if isinstance(value,dict):
            if str(value.get('type','')).endswith('.CopyCard'):return value['fields']
            for child in value.values():
                found=self.copy_node(child)
                if found is not None:return found
        elif isinstance(value,list):
            for child in value:
                found=self.copy_node(child)
                if found is not None:return found

    def test_full_original_face_two_primary_faces_and_complete_metadata(self):
        data=load_batch();raw=data['cards'][0]['record'];self.assertEqual(canonical_digest(raw),data['cards'][0]['record_sha256'])
        self.assertEqual(self.r.card(SABRE).metadata,replace(metadata_from_record(raw),deck_identity=SABRE))
        self.assertEqual(self.r.card(SABRE).keywords,(Keyword.STEALTH,));self.assertEqual(len(data['official_observations']),2)
        for o in data['official_observations']:
            f=o['face'];cn=o['locale'].startswith('zh');self.assertEqual(f['name'],raw['name'if cn else'name_en'])
            self.assertEqual(re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',f['text']),re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',raw['text'if cn else'text_en']))
        self.assertFalse(data['cn_calibrated']);self.assertFalse(data['formal_pool_complete'])

    def test_native_face_pays_four_once_and_is_not_immediately_attack_ready(self):
        g=self.game((SABRE,),board=());source=self.play(g,SABRE)
        self.assertEqual((g.state.players[1].mana,g.state.entities[source].attack,g.state.entities[source].health),(36,5,3))
        self.assertIn(Keyword.STEALTH,g.state.entities[source].keywords);saved=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,source,self.eid(g,VICTIM,2)))
        self.assertEqual(g.snapshot(),saved);self.portable(g)

    def test_real_completed_attack_gets_one_original_printed_copy_after_death(self):
        g=self.game();rng=g._rng.getstate();source,victim=self.attack(g);copy,=self.copies(g,victim)
        self.assertEqual((copy.card_id,copy.attack,copy.health,copy.damage,copy.controller),(VICTIM,1,2,0,1))
        self.assertEqual(len(g.state.death_history),1);self.assertEqual(g.state.death_history[0].entity_id,victim)
        self.assertEqual(g.state.entities[victim].zone,Zone.GRAVEYARD);self.assertEqual(g._rng.getstate(),rng)
        self.assertNotIn(Keyword.STEALTH,g.state.entities[source].keywords);self.portable(g)

    def test_nonlethal_and_hero_attack_do_not_reward(self):
        # Yeti's retaliation would kill Saber; a shield isolates nonlethal damage.
        g=self.game((P+'shield',P+'buff'),enemy=(YETI,));victim=self.eid(g,YETI,2);self.play(g,'shield',self.eid(g,SABRE));self.play(g,'buff',victim)
        self.attack(g,victim);self.assertFalse(self.copies(g,victim));self.assertEqual(len(g.state.death_history),0)
        g=self.game();self.attack(g,g.state.players[2].hero_id);self.assertEqual(g.state.players[1].hand,[])

    def test_defensive_kill_and_other_attacker_do_not_reward(self):
        g=self.game();source=self.eid(g,SABRE);self.attack(g,g.state.players[2].hero_id)
        g.apply(EndTurn(1));g.apply(Attack(2,self.eid(g,VICTIM,2),source));self.assertEqual(g.state.players[1].hand,[])
        g=self.game(board=(SABRE,YETI));victim=self.eid(g,VICTIM,2);g.apply(Attack(1,self.eid(g,YETI),victim));self.assertFalse(self.copies(g,victim))

    def test_mutual_lethal_source_does_not_receive_copy(self):
        g=self.game(enemy=(P+'mutual',));victim=self.eid(g,P+'mutual',2);self.attack(g,victim)
        self.assertEqual(len(g.state.death_history),2);self.assertFalse(self.copies(g,victim));self.portable(g)

    def test_spell_kill_and_bare_combat_are_not_completed_native_attacks(self):
        for name in('kill','bare'):
            with self.subTest(name=name):
                g=self.game((P+name,));victim=self.eid(g,VICTIM,2);self.play(g,name,victim)
                self.assertEqual(g.state.character_attack_history,[]);self.assertFalse(self.copies(g,victim));self.portable(g)

    def test_actual_poison_death_qualifies_and_copy_has_fresh_original_base(self):
        g=self.game((P+'poison',P+'shield',P+'buff'),enemy=(YETI,));victim=self.eid(g,YETI,2)
        self.play(g,'buff',victim);self.play(g,'poison',self.eid(g,SABRE));self.play(g,'shield',self.eid(g,SABRE));self.attack(g,victim)
        self.assertEqual(g.state.death_history[0].cause.kind,'poison');copy,=self.copies(g,victim)
        self.assertEqual((copy.card_id,copy.attack,copy.health,copy.damage),(YETI,4,5,0));self.assertEqual(copy.enchantments,[]);self.portable(g)

    def test_silenced_or_transformed_source_no_longer_has_original_trigger(self):
        for name in('silence','transform'):
            g=self.game((P+name,));source=self.eid(g,SABRE);victim=self.eid(g,VICTIM,2);self.play(g,name,source)
            g.apply(Attack(1,source,victim));self.assertFalse(self.copies(g,victim))

    def test_native_force_can_kill_friendly_minion_using_same_credit_path(self):
        g=self.game((P+'force',),board=(SABRE,VICTIM),enemy=());victim=self.eid(g,VICTIM)
        self.play(g,'force',victim);copy,=self.copies(g,victim);self.assertEqual(copy.card_id,VICTIM)
        self.assertEqual(g.state.character_attack_history[-1].terminal.status,'completed');self.portable(g)

    def test_actual_acquisition_full_hand_burns_new_body_without_an_extra_death(self):
        g=self.game((YETI,)*10);source,victim=self.attack(g)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertFalse(self.copies(g,victim));self.assertEqual(len(g.state.death_history),1)
        burned=[e for e in g.state.entities.values()if e.origin_entity_id==victim];self.assertEqual(len(burned),1);self.assertEqual(burned[0].zone,Zone.GRAVEYARD);self.portable(g)

    def test_original_attack_wait_keeps_frozen_board_context_after_actual_death(self):
        g=self.game(board=(WATCH,SABRE));source,victim=self.attack(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(g.state.death_history),1);self.assertFalse(self.copies(g,victim))
        call=g.snapshot()['resolution_frame']['fields']['continuation']['tuple'][0]['fields']
        self.assertEqual(call['behavior_id'],'cards.native_combat_copy.sabre')
        original=call['context']['fields']['state']['state'];self.assertEqual(original['entities'][str(victim)]['zone'],'board')
        self.assertEqual(original['death_history'],[]);self.assertEqual(g.state.entities[victim].zone,Zone.GRAVEYARD)
        other=self.portable(g)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.copies(g,victim)),1)

    def test_accepted_original_material_survives_later_source_death_or_silence(self):
        for key in('kill_source','silence_source'):
            g=self.game(board=(WATCH,SABRE));source,victim=self.attack(g);other=self.portable(g)
            for current in(g,other):self.choose(current,key)
            self.assertEqual(g.snapshot(),other.snapshot());copy,=self.copies(g,victim);self.assertEqual(copy.card_id,VICTIM)

    def test_later_same_face_target_does_not_replace_original_victim(self):
        g=self.game(board=(WATCH,SABRE));source,victim=self.attack(g);self.choose(g,'other_victim');copy,=self.copies(g,victim)
        self.assertEqual(copy.origin_entity_id,victim);later=self.eid(g,VICTIM,2);self.assertNotEqual(later,victim);self.assertFalse(self.copies(g,later));self.portable(g)

    def test_failed_waiting_choice_preserves_attack_death_rng_and_original_queued_copy(self):
        g=self.game(board=(WATCH,SABRE));source,victim=self.attack(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertEqual(len(self.copies(g,victim)),1);self.portable(g)

    def test_late_failure_rolls_back_paid_spell_attack_death_and_created_copy(self):
        g=self.game((P+'late_fail',));victim=self.eid(g,VICTIM,2);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'late_fail',victim)
        self.assertEqual(g.snapshot(),saved)

    def test_frozen_board_base_copy_keeps_original_face_after_live_transform_or_reentry(self):
        for key in('transform','cycle'):
            g=self.game((P+'defer',),board=(VICTIM,),enemy=());original=self.eid(g,VICTIM);self.play(g,'defer',original);other=self.portable(g)
            for current in(g,other):self.choose(current,key)
            self.assertEqual(g.snapshot(),other.snapshot());copy,=self.copies(g,original);self.assertEqual((copy.card_id,copy.attack,copy.health),(VICTIM,1,2))
            self.assertEqual(g.state.death_history,[])

    def test_new_board_material_prohibits_current_recipe_and_nonminion_board_origins(self):
        g=self.game();source=g.state.entities[self.eid(g,SABRE)];material=CapturedCardCopyMaterial.capture(g.state,source)
        validate_captured_card_copy(g.state,self.r,material);op=CopyCard(material,1,mode='base');codec=FrameCodec(g.mechanics,g.registry)
        self.assertEqual(codec.decode(codec.encode(op)),op)
        with self.assertRaises(ValueError):CopyCard(material,1,mode='current')
        for kind in(CardType.SPELL,CardType.WEAPON,CardType.LOCATION,CardType.HERO):
            with self.assertRaises(ValueError):replace(material,origin=replace(material.origin,kind=kind))

    def test_rehashed_future_or_wrong_kind_frozen_material_is_rejected(self):
        g=self.game((P+'defer',),board=(VICTIM,),enemy=());self.play(g,'defer',self.eid(g,VICTIM));saved=g.snapshot()
        for key in('future','kind','component','current'):
            with self.subTest(key=key):
                bad=deepcopy(saved);node=self.material_node(bad);self.assertIsNotNone(node)
                if key=='future':node['origin']['fields']['next_entity_id']=g.state.next_entity_id+100
                elif key=='kind':node['origin']['fields']['kind']={'enum':'hs_sim.engine.model.CardType','value':'weapon'}
                elif key=='component':node['components']={'tuple':['unknown.k100']}
                else:self.copy_node(bad)['mode']='current'
                bad['state_hash']=canonical_hash({k:v for k,v in bad.items()if k not in('schema_version','events','events_hash','state_hash')})
                with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())

    def test_copied_actual_jade_innate_size_does_not_advance_growth(self):
        g=self.game((P+'jade',),enemy=());self.play(g,'jade');victim=g.state.players[2].board[0];original=g.state.entities[victim];self.assertEqual(original.jade_size,1)
        history=tuple(g.state.jade_history);self.attack(g,victim);copy,=self.copies(g,victim)
        self.assertEqual((copy.jade_size,copy.attack,copy.health,copy.base_cost),(1,1,1,1));self.assertEqual(tuple(g.state.jade_history),history);self.portable(g)

    def test_actual_launched_ship_copy_preserves_full_composed_printed_recipe(self):
        g=self.game((P+'kill',P+'force'),board=(SABRE,'SC_403a'),enemy=());self.play(g,'kill',self.eid(g,'SC_403a'))
        ship=construction(g.state,1);g.apply(LaunchStarship(1,ship.id));original=g.state.entities[ship.id];parts=original.components;base=(original.attack,original.health)
        self.assertTrue(parts);self.play(g,'force',ship.id);copy,=self.copies(g,ship.id)
        self.assertEqual(copy.components,parts);self.assertEqual((copy.attack,copy.health),base);self.portable(g)


if __name__=='__main__':unittest.main()
