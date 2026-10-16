"""Five real native providers; current source typing and continuous targeting."""
from copy import deepcopy
from dataclasses import asdict,replace
import json,unittest
from pathlib import Path
from hs_sim.cards import build_registry
from hs_sim.cards.native_health_attack_provider_cards import QUANTUM,BRALMA,GOLDRINN,KAYN,SURVIVALIST,ROOTS,BATCH_HASH,load_batch
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,Keyword,PlayCard,PlayerSetup,
    Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.attack_policies import GrantAttackPolicy
from hs_sim.engine.dormancy import MakeDormant,AwakenMinion
from hs_sim.engine.effects import (Buff,ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,Draw,GrantKeyword,Heal,InvokeBehavior,
    RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.keyword_auras import GrantKeywordAura
from hs_sim.engine.model import AttackPolicyCondition,AttackPolicySpec,DamageKind,HealthFlow,HealthLayer,HealthOp,HealthRule,KeywordAuraSpec,TribeChangeSpec
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1];YETI='CORE_CS2_182';BOLT='CORE_CS2_024';FIREBALL='CORE_CS2_029';DORMANT='EDR_979';WEAPON='EDR_253'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


def registry():
    r=build_registry();r.register_behavior('k82.noop',lambda c:())
    def fail(c):raise ResolutionError('K82 deliberate failure')
    r.register_behavior('k82.fail',fail)
    for name,tribes in(('normal',()),('elemental',('elemental',)),('beast',('beast',)),('all',('all',)),('dual',('undead','elemental')),('unknown',None)):
        r.register_card(CardDefinition('k82.'+name,name,CardType.MINION,attack=3,health=20,metadata=replace(META,tribes=tribes)))
    r.register_card(CardDefinition('k82.taunt','taunt',CardType.MINION,attack=1,health=20,keywords=(Keyword.TAUNT,),metadata=META))
    r.register_card(CardDefinition('k82.stealth','stealth',CardType.MINION,attack=1,health=20,keywords=(Keyword.STEALTH,),metadata=META))
    r.register_card(CardDefinition('k82.location','location',CardType.LOCATION,durability=2,on_use='k82.noop',metadata=META))
    r.register_card(CardDefinition('k82.piece','piece',CardType.MINION,attack=1,health=1,keywords=(Keyword.STARSHIP_PIECE,),metadata=META))
    def wait(c):return(RequestChoice(c.player_id,(ChoiceOption('keep','Keep'),ChoiceOption('fail','Fail',(InvokeBehavior('k82.fail',c.source_id,c.player_id),))),source_id=c.source_id),)
    def health_wait(c):return wait(c)if c.event.target_id==c.state.players[2].hero_id else()
    def kill_kayn(c):
        if c.event.player_id==c.player_id:return ()
        ids=[i for i in c.state.players[3-c.player_id].board if c.state.entities[i].card_id==KAYN]
        return(Destroy(ids[0],c.source_id),)if ids else()
    for name,event,body in(('health_wait','damage_dealt',health_wait),('kill_kayn','attack_declared',kill_kayn)):
        r.register_behavior('k82.'+name,body);r.register_card(CardDefinition('k82.'+name,name,CardType.MINION,health=30,triggers=(TriggerSpec(event,'k82.'+name),),metadata=META))
    def blast(c):return(Damage(c.target_id,3,c.source_id,kind=DamageKind.MINION_ABILITY),)
    r.register_behavior('k82.blast',blast)
    r.register_card(CardDefinition('k82.blast_elemental','blast',CardType.MINION,attack=1,health=4,battlecry='k82.blast',targeting=TargetSpec(),metadata=replace(META,tribes=('elemental',))))
    r.register_behavior('k82.dr_beast',lambda c:(Damage(c.state.players[3-c.player_id].hero_id,3,c.source_id),))
    r.register_card(CardDefinition('k82.dr_beast','death beast',CardType.MINION,attack=1,health=1,deathrattle='k82.dr_beast',metadata=replace(META,tribes=('beast',))))
    def script(c,op):
        if op=='hurt':return(Damage(c.target_id,2,c.source_id),)
        if op=='heal':return(Heal(c.target_id,2,c.source_id),)
        if op=='kill':return(Destroy(c.target_id,c.source_id),)
        if op=='silence':return(Silence(c.target_id),)
        if op=='control':return(ChangeControl(c.target_id,c.player_id),)
        if op=='copy':return(CopyMinion(c.target_id,c.player_id),)
        if op=='sleep':return(MakeDormant(c.target_id,1,c.source_id),)
        if op=='wake':return(AwakenMinion(c.target_id,c.source_id),)
        if op=='shield':return(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),)
        if op=='beast':return(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('beast',)),c.source_id),)
        if op=='unknown':return()
        raise AssertionError(op)
    for op in('hurt','heal','kill','silence','control','copy','sleep','shield','beast'):
        key='k82.script_'+op;r.register_behavior(key,lambda c,op=op:script(c,op));r.register_card(CardDefinition(key,op,CardType.SPELL,on_play=key,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),metadata=META))
    r.register_behavior('k82.wake',lambda c:tuple(AwakenMinion(i,c.source_id)for p in c.state.players.values()for i in p.board if c.state.entities[i].dormancy is not None))
    r.register_card(CardDefinition('k82.script_wake','wake',CardType.SPELL,on_play='k82.wake',metadata=META))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events']);saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')});return saved


class NativeHealthAttackProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),seed=1082):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*10,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*10,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=seed),self.r)
    def entities(self,g,cid,p=1,zone='board'):
        s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid]
    def first(self,g,cid,p=1,zone='board'):return self.entities(g,cid,p,zone)[0]
    def play(self,g,cid,target=None,p=1):
        eid=self.first(g,cid,p,'hand').id;g.apply(PlayCard(p,eid,target));return eid
    def script(self,g,op,target=None,p=1):return self.play(g,'k82.script_'+op,target,p)
    def hero(self,g,p=2):return g.state.entities[g.state.players[p].hero_id]
    def choose(self,g,key='keep'):q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,registry()).snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
    def attack(self,g,cid,target=None,p=1):g.apply(Attack(p,self.first(g,cid,p).id,self.hero(g,3-p).id if target is None else target))
    def test_five_complete_roots_keep_all_unimplemented_chromatus_faces(self):
        d=load_batch();self.assertEqual(canonical_digest(d),BATCH_HASH);self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['evidence_only'])),(5,0,7))
        for row in d['cards']+d['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual((self.r.card(KAYN).attack,self.r.card(KAYN).health,self.r.card(KAYN).metadata.deck_identity),(3,5,'BT_187'))
        for cid in('CATA_432','CATA_432t1','CATA_432t2','CATA_432t3','CATA_432t4','BT_187'):self.assertNotIn(cid,self.r.cards)
    def test_old1076_definitions_and_default_fingerprint_are_unchanged(self):
        old=json.loads((ROOT/'outputs/card-integration-20261014/k82-before/definition-digests.json').read_bytes());self.assertEqual(len(old),1076)
        self.assertEqual(old,{cid:canonical_digest(asdict(self.r.card(cid)))for cid in old});self.assertEqual(representative().fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')
    def test_quantum_doubles_effect_spell_and_combat_without_changing_stats(self):
        for mode,amount in(('hurt',4),('bolt',6),('attack',6)):
            with self.subTest(mode=mode):
                g=self.game((BOLT,'k82.script_hurt'),board=('k82.normal',),enemy=(QUANTUM,));q=self.first(g,QUANTUM,2)
                if mode=='hurt':self.script(g,'hurt',q.id)
                elif mode=='bolt':self.play(g,BOLT,q.id)
                else:self.attack(g,'k82.normal',q.id)
                self.assertEqual(g.state.entities[q.id].health,9-amount);self.assertEqual(g.state.entities[q.id].attack,4)
    def test_quantum_does_not_double_healing_and_silence_removes_multiplier(self):
        g=self.game(('k82.script_hurt','k82.script_heal','k82.script_silence','k82.script_hurt'),enemy=(QUANTUM,));q=self.first(g,QUANTUM,2).id
        self.script(g,'hurt',q);self.script(g,'heal',q);self.assertEqual(g.state.entities[q].health,7)
        self.script(g,'silence',q);self.script(g,'hurt',q);self.assertEqual(g.state.entities[q].health,5)
    def test_quantum_divine_shield_still_prevents_whole_modified_packet(self):
        g=self.game(('k82.script_shield','k82.script_hurt'),enemy=(QUANTUM,));q=self.first(g,QUANTUM,2).id;self.script(g,'shield',q);self.script(g,'hurt',q)
        self.assertEqual(g.state.entities[q].health,9);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[q].keywords)
    def test_bralma_matches_current_elemental_secondary_and_all_types(self):
        for cid,damage in(('k82.elemental',4),('k82.dual',4),('k82.all',4),('k82.beast',3),('k82.normal',3)):
            with self.subTest(cid=cid):
                g=self.game(board=(BRALMA,cid));self.attack(g,cid);self.assertEqual(self.hero(g).health,30-damage);self.assertEqual(self.first(g,cid).attack,3)
    def test_bralma_applies_to_minion_ability_but_not_actual_spell(self):
        g=self.game(('k82.blast_elemental',FIREBALL),board=(BRALMA,));self.play(g,'k82.blast_elemental',self.hero(g).id);self.assertEqual(self.hero(g).health,26)
        self.play(g,FIREBALL,self.hero(g).id);self.assertEqual(self.hero(g).health,20)
    def test_bralma_current_tribe_change_can_remove_qualification(self):
        g=self.game(('k82.script_beast',),board=(BRALMA,'k82.elemental'));source=self.first(g,'k82.elemental').id;self.script(g,'beast',source);self.attack(g,'k82.elemental');self.assertEqual(self.hero(g).health,27)
    def test_bralma_unknown_source_tribes_fail_without_spending_attack(self):
        g=self.game(board=(BRALMA,'k82.unknown'));saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Unknown current tribe set'):self.attack(g,'k82.unknown')
        self.assertEqual(g.snapshot(),saved)
    def test_bralma_enemy_source_is_not_buffed_and_control_changes_provider_owner(self):
        g=self.game(('k82.script_control',),enemy=(BRALMA,),board=('k82.elemental',));self.script(g,'control',self.first(g,BRALMA,2).id);self.attack(g,'k82.elemental');self.assertEqual(self.hero(g).health,26)
        h=self.game(board=(BRALMA,),enemy=('k82.elemental',));h.apply(EndTurn(1));self.attack(h,'k82.elemental',p=2);self.assertEqual(self.hero(h,1).health,27)
    def test_goldrinn_doubles_beast_combat_and_its_own_rush_damage(self):
        g=self.game((GOLDRINN,),board=('k82.beast',),enemy=('k82.normal',));self.play(g,GOLDRINN);self.attack(g,'k82.beast');self.assertEqual(self.hero(g).health,24)
        victim=self.first(g,'k82.normal',2).id;self.attack(g,GOLDRINN,victim);self.assertEqual(g.state.entities[victim].health,2);self.assertEqual(self.first(g,GOLDRINN).attack,9);self.portable(g)
    def test_goldrinn_doubles_original_beast_deathrattle_from_graveyard(self):
        g=self.game(('k82.script_kill',),board=(GOLDRINN,'k82.dr_beast'));self.script(g,'kill',self.first(g,'k82.dr_beast').id);self.assertEqual(self.hero(g).health,24)
    def test_tribal_provider_silence_dormancy_and_current_copy_use_shared_lifecycle(self):
        for op in('silence','sleep','kill'):
            with self.subTest(op=op):
                g=self.game(('k82.script_'+op,),board=(BRALMA,'k82.elemental'));self.script(g,op,self.first(g,BRALMA).id);self.attack(g,'k82.elemental');self.assertEqual(self.hero(g).health,27)
        g=self.game(('k82.script_copy','k82.script_kill'),board=(BRALMA,'k82.elemental'));old=self.first(g,BRALMA).id;self.script(g,'copy',old);self.script(g,'kill',old);self.attack(g,'k82.elemental');self.assertEqual(self.hero(g).health,26)
    def test_modified_damage_wait_restores_and_choice_failure_preserves_committed_boundary(self):
        g=self.game(board=(BRALMA,'k82.elemental','k82.health_wait'));self.attack(g,'k82.elemental');self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.hero(g).health,26);self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertEqual(self.hero(g).health,26)
    def test_native_tribal_rule_domains_reject_unrelated_filters_or_floor(self):
        for relation,op,amount in(('friendly_elemental_minions',HealthOp.ADD,1),('friendly_beast_minions',HealthOp.SCALE,2)):
            for override in(dict(amount=3),dict(target_relation='enemy'),dict(layer=HealthLayer.TARGET),dict(operation=HealthOp.FLOOR),dict(denominator=2)):
                with self.subTest(relation=relation,override=override),self.assertRaises(ValueError):HealthRule(**dict(dict(flow=HealthFlow.DAMAGE,operation=op,amount=amount,source_relation=relation),**override))
    def test_kayn_charge_and_ready_friend_ignore_only_enemy_taunt(self):
        g=self.game((KAYN,),board=(YETI,),enemy=('k82.taunt',));saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.attack(g,YETI)
        self.assertEqual(g.snapshot(),saved);self.play(g,KAYN);self.attack(g,YETI);self.attack(g,KAYN);self.assertEqual(self.hero(g).health,23);self.portable(g)
    def test_kayn_allows_hero_weapon_attack_through_taunt(self):
        g=self.game((KAYN,WEAPON),enemy=('k82.taunt',));self.play(g,KAYN);self.play(g,WEAPON);before=self.hero(g).health
        g.apply(Attack(1,self.hero(g,1).id,self.hero(g).id));self.assertLess(self.hero(g).health,before)
    def test_kayn_does_not_remove_new_minion_or_stealth_target_restrictions(self):
        g=self.game((YETI,),board=(KAYN,),enemy=('k82.taunt',));self.play(g,YETI)
        with self.assertRaises(IllegalAction):self.attack(g,YETI)
        h=self.game(board=(KAYN,YETI),enemy=('k82.taunt','k82.stealth'))
        with self.assertRaises(IllegalAction):self.attack(h,YETI,self.first(h,'k82.stealth',2).id)
    def test_kayn_loss_silence_dormancy_and_control_revoke_new_target_permission(self):
        for op in('kill','silence','sleep'):
            with self.subTest(op=op):
                g=self.game(('k82.script_'+op,),board=(KAYN,YETI),enemy=('k82.taunt',));self.script(g,op,self.first(g,KAYN).id)
                with self.assertRaises(IllegalAction):self.attack(g,YETI)
        g=self.game(('k82.script_control',),board=(YETI,),enemy=(KAYN,'k82.taunt'));self.script(g,'control',self.first(g,KAYN,2).id);self.attack(g,YETI);self.assertEqual(self.hero(g).health,26)
    def test_kayn_accepted_attack_survives_provider_departure(self):
        g=self.game(board=(KAYN,YETI),enemy=('k82.taunt','k82.kill_kayn'));self.attack(g,YETI);self.assertEqual(self.hero(g).health,26);self.assertEqual(g.state.character_attack_history[-1].terminal.status,'completed');self.assertFalse(self.entities(g,KAYN));self.portable(g)
    def test_friendly_taunt_provider_cannot_be_dynamic_or_weapon_declaration(self):
        with self.assertRaises(ValueError):GrantAttackPolicy(1,AttackPolicySpec('friendly_ignore_taunt'))
        with self.assertRaises(ValueError):AttackPolicySpec('friendly_ignore_taunt',conditions=(AttackPolicyCondition('attack','gt',0),))
        with self.assertRaises(ValueError):self.r.register_card(CardDefinition('k82.bad_weapon','bad',CardType.WEAPON,attack=1,durability=2,attack_policies=(AttackPolicySpec('friendly_ignore_taunt'),)))
    def test_survivalist_alone_is_immune_but_enemy_board_does_not_disable_it(self):
        g=self.game((SURVIVALIST,),enemy=(YETI,));source=self.play(g,SURVIVALIST);self.assertIn(Keyword.IMMUNE,g.state.entities[source].keywords);self.portable(g)
    def test_survivalist_other_minion_entry_and_departure_recompute_without_grants(self):
        g=self.game((YETI,'k82.script_kill'),board=(SURVIVALIST,));source=self.first(g,SURVIVALIST).id;original_ids=[a.id for a in g.state.entities[source].abilities]
        other=self.play(g,YETI);self.assertNotIn(Keyword.IMMUNE,g.state.entities[source].keywords);self.script(g,'kill',other);self.assertIn(Keyword.IMMUNE,g.state.entities[source].keywords)
        self.assertEqual([a.id for a in g.state.entities[source].abilities],original_ids)
    def test_survivalist_dormant_minion_counts_but_location_and_building_do_not(self):
        g=self.game(board=(SURVIVALIST,DORMANT));self.assertNotIn(Keyword.IMMUNE,self.first(g,SURVIVALIST).keywords)
        h=self.game(board=(SURVIVALIST,'k82.location'));self.assertIn(Keyword.IMMUNE,self.first(h,SURVIVALIST).keywords)
        ship=self.game(('k82.script_kill',),board=(SURVIVALIST,'k82.piece'));self.script(ship,'kill',self.first(ship,'k82.piece').id)
        self.assertTrue(any(ship.state.entities[i].starship_building for i in ship.state.players[1].board));self.assertIn(Keyword.IMMUNE,self.first(ship,SURVIVALIST).keywords);self.portable(ship)
    def test_survivalist_does_not_supply_hand_immunity_and_current_copy_has_another_minion(self):
        g=self.game((SURVIVALIST,));self.assertNotIn(Keyword.IMMUNE,self.first(g,SURVIVALIST,zone='hand').keywords)
        h=self.game(('k82.script_copy',),board=(SURVIVALIST,));self.script(h,'copy',self.first(h,SURVIVALIST).id);self.assertTrue(all(Keyword.IMMUNE not in e.keywords for e in self.entities(h,SURVIVALIST)))
    def test_survivalist_immune_blocks_enemy_targeting_and_silence_then_opens_it(self):
        g=self.game(('k82.script_silence',),board=(SURVIVALIST,),enemy_hand=(BOLT,));g.apply(EndTurn(1));saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,BOLT,self.first(g,SURVIVALIST).id,p=2)
        self.assertEqual(g.snapshot(),saved);g.apply(EndTurn(2));self.script(g,'silence',self.first(g,SURVIVALIST).id);g.apply(EndTurn(1));self.play(g,BOLT,self.first(g,SURVIVALIST).id,p=2);self.assertEqual(self.first(g,SURVIVALIST).health,3)
    def test_survivalist_profile_rejects_other_keywords_and_dynamic_grant(self):
        with self.assertRaises(ValueError):KeywordAuraSpec(Keyword.CHARGE,'self',condition='controller_no_other_minions')
        with self.assertRaises(ValueError):GrantKeywordAura(1,KeywordAuraSpec(Keyword.IMMUNE,'self',condition='controller_no_other_minions'))
    def test_public_views_do_not_expose_provider_attachments_or_private_state(self):
        g=self.game(board=(SURVIVALIST,),enemy=(KAYN,));public=json.dumps(g.for_player(1).legal_actions(),ensure_ascii=False)
        for key in('health_rule','attack_policy','keyword_aura','next_attachment_id','original_entities','resolution_frame'):self.assertNotIn(key,public)
    def test_actual_schema300_default_and_constructed_are_rejected(self):
        for name,r in(('constructed-v90-core375-schema300.json',build_registry()),('default-v65-core375-schema300.json',representative())):
            saved=json.loads((ROOT/'outputs/card-integration-20261014/k82-before'/name).read_bytes())
            from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
            with self.subTest(name=name),self.assertRaisesRegex(SnapshotError,f'1 through {SNAPSHOT_SCHEMA_VERSION-1}'):Game.from_snapshot(saved,r)


if __name__=='__main__':unittest.main()
