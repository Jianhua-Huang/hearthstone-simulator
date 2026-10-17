"""Previous printed rune facts and original fixed summon combat deliveries."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT, historical_definition_digests
from copy import deepcopy
from dataclasses import asdict
import json,unittest
from pathlib import Path
from hs_sim.cards import build_registry
from hs_sim.cards.blood_rune_native_cards import BATCH_HASH,BLADE,SURGERY,NURSE,load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,Keyword,PlayCard,
    PlayerSetup,Runes,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,UseHeroPower,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Damage,Destroy,ForceAttack,InvokeBehavior,RequestChoice,
    ReturnToHand,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,LimitedTriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

YETI='CORE_CS2_182';META=CardMetadata(False,(CardClass.NEUTRAL,),None);ROOT=Path(__file__).resolve().parents[1]


def registry():
    r=build_registry()
    for name,runes in(('blood',Runes(blood=1)),('unholy',Runes(unholy=2)),('dual',Runes(blood=1,unholy=1)),('frost',Runes(frost=1))):
        r.register_card(CardDefinition('k75.prev_'+name,name,CardType.MINION,health=5,metadata=CardMetadata(False,(CardClass.DEATH_KNIGHT,),None,runes=runes)))
    r.register_card(CardDefinition('k75.unknown','Unknown printed rune basis',CardType.MINION,health=5))
    r.register_card(CardDefinition('k75.wall','Surviving target',CardType.MINION,health=20,metadata=META))
    r.register_card(CardDefinition('k75.shield','Shield target',CardType.MINION,health=20,keywords=(Keyword.DIVINE_SHIELD,),metadata=META))
    r.register_card(CardDefinition('k75.reborn','Reborn target',CardType.MINION,health=2,keywords=(Keyword.REBORN,),metadata=META))
    r.register_card(CardDefinition('k75.spellpower','Spell power control',CardType.MINION,health=5,spell_damage=2,metadata=META))
    r.register_behavior('k75.shifted',lambda c:(Transform(c.source_id,YETI),))
    r.register_card(CardDefinition('k75.shifted','Original dual-rune face',CardType.MINION,health=5,battlecry='k75.shifted',
        metadata=CardMetadata(False,(CardClass.DEATH_KNIGHT,),None,runes=Runes(blood=1,unholy=1))))
    r.register_behavior('k75.rune_spell',lambda c:())
    r.register_card(CardDefinition('k75.rune_spell','Countered rune spell',CardType.SPELL,on_play='k75.rune_spell',metadata=CardMetadata(False,(CardClass.DEATH_KNIGHT,),None,runes=Runes(unholy=1))))
    r.register_behavior('k75.hurt',lambda c:(Damage(c.state.players[c.player_id].hero_id,20,c.source_id,DamageKind.EFFECT),))
    r.register_card(CardDefinition('k75.hurt','Fixed health control',CardType.SPELL,on_play='k75.hurt',metadata=META))
    def fail(c):raise ResolutionError('K75 deliberate late failure')
    r.register_behavior('k75.fail',fail)
    def reenter(c):
        e=c.state.entities[c.target_id];return(SummonStoredCard(CardReference.capture(e),e.controller),)
    r.register_behavior('k75.reenter',reenter)
    def summon_wait(c):
        if c.state.entities[c.event.target_id].card_id!=NURSE:return()
        cast=c.state.cast_history[-1];target=cast.target_id;nurse=c.event.target_id
        return(RequestChoice(1,(ChoiceOption('keep','Continue',()),
            ChoiceOption('form','Transform original target',(Transform(target,'k75.wall'),)),
            ChoiceOption('give','Control original target',(ChangeControl(target,1),)),
            ChoiceOption('target_reenter','Return original target then summon',(ReturnToHand(target),InvokeBehavior('k75.reenter',c.source_id,2,target))),
            ChoiceOption('nurse_reenter','Return original nurse then summon',(ReturnToHand(nurse),InvokeBehavior('k75.reenter',c.source_id,1,nurse)))),c.source_id),)
    def attack_wait(c):
        return(RequestChoice(1,(ChoiceOption('keep','Continue',()),ChoiceOption('fail','Fail',(InvokeBehavior('k75.fail',c.source_id,1),))),c.source_id),)
    def nested(c):
        if c.state.entities[c.event.target_id].card_id!=NURSE:return()
        return(SummonByCard(c.player_id,(SummonEntryMaterial(NURSE),),SummonCause.capture(c)),)
    def kill_target(c):
        if c.state.entities[c.event.target_id].card_id!=NURSE:return()
        return(Destroy(c.state.cast_history[-1].target_id,c.source_id),)
    for key,event,body in(('wait_summon','minion_summoned',summon_wait),('wait_attack','attack_finished',attack_wait),
            ('nested','minion_summoned',nested),('kill_target','minion_summoned',kill_target)):
        r.register_behavior('k75.'+key,body)
        r.register_card(CardDefinition('k75.'+key,key,CardType.MINION,health=20,
            limited_triggers=(LimitedTriggerSpec(event,'k75.'+key),),metadata=META))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events']);saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')});return saved


def wires(value,name):
    result=[]
    if isinstance(value,dict):
        if value.get('type','').endswith('.'+name):result.append(value)
        for x in value.values():result.extend(wires(x,name))
    elif isinstance(value,list):
        for x in value:result.extend(wires(x,name))
    return result


class BloodRuneNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),enemy_hand=()):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=1075),self.r)
    def entities(self,g,cid,p=1,zone='board'):
        s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid]
    def play(self,g,cid,target=None,p=1,branch=None):
        eid=self.entities(g,cid,p,'hand')[0].id;g.apply(PlayCard(p,eid,target,branch_id=branch));return eid
    def weapon(self,g):return g.state.entities[g.state.players[1].weapon_id]
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=g.snapshot();other=Game.from_snapshot(saved,registry());self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return other
    def surgery(self,g):return self.play(g,SURGERY,next(g.state.entities[i].id for i in g.state.players[2].board if g.state.entities[i].card_id!='CORE_CS2_182'))
    def attacks(self,g):return g.state.character_attack_history

    def test_full_records_official_four_and_fixed_nurse_properties(self):
        data=load_batch();self.assertEqual(canonical_digest(data),BATCH_HASH)
        self.assertEqual((len(data['cards']),len(data['dependencies']),len(data['evidence_only'])),(2,1,2))
        for row in data['cards']+data['dependencies']+data['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        nurse=self.r.card(NURSE);self.assertEqual((nurse.cost,nurse.attack,nurse.health),(2,3,1));self.assertEqual(nurse.keywords,(Keyword.LIFESTEAL,))
        self.assertEqual(tuple(t.lower()for t in nurse.metadata.tribes),('undead',));self.assertEqual(self.r.summon_attack_profiles[SURGERY].count,4)
    def test_old1034_complete_definitions_and_default_fingerprint_equal(self):
        old=json.loads((ROOT/'outputs/card-integration-20261014/k75-before/definition-digests.json').read_text(encoding='utf-8'))
        self.assertEqual(len(old),1034);self.assertEqual(old,historical_definition_digests(self.r,old))
        self.assertEqual(representative().fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)
    def test_blade_first_card_does_not_read_its_own_dual_runes(self):
        g=self.game((BLADE,));self.play(g,BLADE);self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),(2,2));self.portable(g)
    def test_previous_unholy_blood_dual_frost_and_nonrune_are_independent(self):
        for cid,expected in(('k75.prev_unholy',(3,2)),('k75.prev_blood',(2,3)),('k75.prev_dual',(3,3)),('k75.prev_frost',(2,2)),(YETI,(2,2))):
            g=self.game((cid,BLADE));self.play(g,cid);self.play(g,BLADE);self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),expected);self.portable(g)
    def test_actual_swarm_previous_dual_rune_face_gives_both_bonuses(self):
        g=self.game(('EDR_813',BLADE));self.play(g,'EDR_813',branch='ants');self.play(g,BLADE)
        self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),(3,3));self.portable(g)
    def test_previous_printed_face_survives_its_actual_self_transformation(self):
        g=self.game(('k75.shifted',BLADE));source=self.play(g,'k75.shifted');self.assertEqual(g.state.entities[source].card_id,YETI)
        self.play(g,BLADE);self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),(3,3));self.portable(g)
    def test_previous_play_across_turns_ignores_hero_power_and_opponent_play(self):
        g=self.game(('k75.prev_blood',BLADE),enemy_hand=(YETI,));self.play(g,'k75.prev_blood')
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,self.hero(g,2).id));g.apply(EndTurn(1));self.play(g,YETI,p=2);g.apply(EndTurn(2))
        self.play(g,BLADE);self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),(2,3));self.portable(g)
    def test_countered_actual_play_still_counts_as_previous_printed_runes(self):
        g=self.game(('k75.rune_spell',BLADE),enemy_hand=('CORE_EX1_287',));g.apply(EndTurn(1));self.play(g,'CORE_EX1_287',p=2);g.apply(EndTurn(2))
        self.play(g,'k75.rune_spell');self.assertTrue(g.state.play_history[-1].countered);self.play(g,BLADE)
        self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),(3,2));self.portable(g)
    def test_second_real_weapon_play_can_read_first_weapon_dual_runes(self):
        g=self.game((BLADE,BLADE));self.play(g,BLADE);old=self.weapon(g).id;self.play(g,BLADE)
        self.assertNotEqual(self.weapon(g).id,old);self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),(3,3));self.portable(g)
    def test_unknown_previous_rune_metadata_fails_explicitly_and_rolls_back(self):
        g=self.game(('k75.unknown',BLADE));self.play(g,'k75.unknown');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'rune metadata is unknown'):self.play(g,BLADE)
        self.assertEqual(g.snapshot(),before)
    def test_surgery_all_four_real_requests_precede_four_forced_attacks(self):
        g=self.game(('k75.hurt',SURGERY),enemy=('k75.wall',));self.play(g,'k75.hurt');self.surgery(g)
        self.assertEqual((len(self.entities(g,NURSE)),len(self.attacks(g))), (4,4));self.assertEqual(self.entities(g,'k75.wall',2)[0].health,8)
        self.assertEqual(self.hero(g).health,22);self.assertEqual(len(g.state.card_summon_history),4)
        events=[e.kind for e in g.events];self.assertLess(max(i for i,k in enumerate(events)if k=='minion_summoned'),events.index('attack_declared'));self.portable(g)
    def test_surgery_is_combat_and_lifesteal_ignores_spell_damage_bonus(self):
        g=self.game(('k75.hurt',SURGERY),board=('k75.spellpower',),enemy=('k75.wall',));self.play(g,'k75.hurt');self.surgery(g)
        self.assertEqual(self.entities(g,'k75.wall',2)[0].health,8);self.assertEqual(self.hero(g).health,22);self.assertEqual(len(self.attacks(g)),4)
    def test_surgery_early_target_death_skips_remaining_attacks_and_keeps_nurses(self):
        g=self.game((SURGERY,),enemy=(YETI,));self.play(g,SURGERY,self.entities(g,YETI,2)[0].id)
        self.assertEqual((len(self.attacks(g)),len(self.entities(g,NURSE))),(2,2));self.assertFalse(self.entities(g,YETI,2));self.portable(g)
    def test_reborn_target_is_a_new_body_and_not_a_retarget(self):
        g=self.game((SURGERY,),enemy=('k75.reborn',));self.surgery(g)
        self.assertEqual(len(self.attacks(g)),1);self.assertEqual(self.entities(g,'k75.reborn',2)[0].health,1)
        self.assertEqual(len(self.entities(g,NURSE)),4);self.portable(g)
    def test_board_capacity_is_resolved_before_later_attacks_free_slots(self):
        g=self.game((SURGERY,),board=(YETI,)*6,enemy=(YETI,));self.play(g,SURGERY,self.entities(g,YETI,2)[0].id)
        self.assertEqual((len(self.attacks(g)),len(self.entities(g,NURSE))),(1,0));self.assertEqual(len(g.state.card_summon_history),4)
        self.assertEqual(len(g.state.players[1].board),6);self.portable(g)
    def test_full_board_produces_no_attack_or_fake_nurse(self):
        g=self.game((SURGERY,),board=(YETI,)*7,enemy=('k75.wall',));self.surgery(g)
        self.assertFalse(self.entities(g,NURSE));self.assertFalse(self.attacks(g));self.assertEqual(self.entities(g,'k75.wall',2)[0].health,20)
    def test_preexisting_same_name_nurse_is_outside_original_group(self):
        g=self.game((SURGERY,),board=(NURSE,),enemy=('k75.wall',));old=self.entities(g,NURSE)[0].id;self.surgery(g)
        self.assertEqual(len(self.entities(g,NURSE)),5);self.assertEqual(len(self.attacks(g)),4);self.assertEqual(g.state.entities[old].attacks_this_turn,0);self.portable(g)
    def test_nested_same_name_summon_is_not_an_original_request_delivery(self):
        g=self.game((SURGERY,),board=('k75.nested',),enemy=('k75.wall',));self.surgery(g)
        self.assertEqual((len(self.entities(g,NURSE)),len(self.attacks(g))),(5,4));self.assertEqual(self.entities(g,'k75.wall',2)[0].health,8);self.portable(g)
    def test_actual_quantity_extras_of_original_requests_also_attack(self):
        g=self.game((SURGERY,),board=('CORE_DAL_575',),enemy=('k75.wall',));self.surgery(g)
        self.assertEqual((len(self.entities(g,NURSE)),len(self.attacks(g))),(6,6));self.assertEqual(self.entities(g,'k75.wall',2)[0].health,2);self.portable(g)
    def test_divine_shield_prevents_one_lifesteal_packet(self):
        g=self.game(('k75.hurt',SURGERY),enemy=('k75.shield',));self.play(g,'k75.hurt');self.surgery(g)
        self.assertEqual((self.entities(g,'k75.shield',2)[0].health,self.hero(g).health),(11,19));self.portable(g)
    def test_selected_target_spell_legality_and_forced_attacks_ignore_other_taunt(self):
        g=self.game((SURGERY,),board=(YETI,),enemy=('k75.wall','RLK_061t'));eid=self.entities(g,SURGERY,zone='hand')[0].id
        for target in(None,self.hero(g,2).id,self.entities(g,YETI)[0].id):
            before=g.snapshot()
            with self.assertRaises(IllegalAction):g.apply(PlayCard(1,eid,target))
            self.assertEqual(g.snapshot(),before)
        self.surgery(g);self.assertEqual(self.entities(g,'k75.wall',2)[0].health,8);self.assertEqual(self.entities(g,'RLK_061t',2)[0].health,3)
    def test_target_dies_during_summons_but_real_later_requests_still_deliver(self):
        g=self.game((SURGERY,),board=('k75.kill_target',),enemy=('k75.wall',));self.surgery(g)
        self.assertEqual(len(self.entities(g,NURSE)),4);self.assertFalse(self.attacks(g));self.assertFalse(self.entities(g,'k75.wall',2));self.portable(g)
    def test_original_target_transform_follows_continuous_residence(self):
        g=self.game((SURGERY,),board=('k75.wait_summon',),enemy=(YETI,));self.play(g,SURGERY,self.entities(g,YETI,2)[0].id)
        self.portable(g);self.choose(g,'form');self.assertEqual(self.entities(g,'k75.wall',2)[0].health,8);self.assertEqual(len(self.attacks(g)),4);self.portable(g)
    def test_original_target_control_change_does_not_choose_a_new_enemy(self):
        g=self.game((SURGERY,),board=('k75.wait_summon',),enemy=('k75.wall',));self.surgery(g);self.choose(g,'give')
        self.assertFalse(self.attacks(g));self.assertEqual(self.entities(g,'k75.wall')[0].health,20);self.assertEqual(len(self.entities(g,NURSE)),4);self.portable(g)
    def test_original_target_reentry_never_borrows_old_forced_attacks(self):
        g=self.game((SURGERY,),board=('k75.wait_summon',),enemy=('k75.wall',));self.surgery(g);self.portable(g);self.choose(g,'target_reenter')
        self.assertFalse(self.attacks(g));self.assertEqual(self.entities(g,'k75.wall',2)[0].health,20);self.portable(g)
    def test_original_nurse_reentry_is_not_rebound_into_the_group(self):
        g=self.game((SURGERY,),board=('k75.wait_summon',),enemy=('k75.wall',));self.surgery(g);self.choose(g,'nurse_reenter')
        self.assertEqual(len(self.attacks(g)),3);self.assertEqual(self.entities(g,'k75.wall',2)[0].health,11);self.portable(g)
    def test_real_attack_wait_restore_clone_replay_and_choice_failure_rollback(self):
        g=self.game((SURGERY,),board=('k75.wait_attack',),enemy=('k75.wall',));self.surgery(g);self.assertEqual(len(self.attacks(g)),1)
        other=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g,'keep');self.choose(other,'keep');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(len(self.attacks(g)),4);self.portable(g)
    def test_future_target_and_truncated_original_group_request_rejected(self):
        g=self.game((SURGERY,),board=('k75.wait_summon',),enemy=('k75.wall',));self.surgery(g);saved=g.snapshot()
        bad=deepcopy(saved);nodes=wires(bad,'AttackSummonedGroup');self.assertTrue(nodes)
        for node in nodes:node['fields']['target']['fields']['presence_id']=10**8
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())
        bad=deepcopy(saved)
        def omit_one(value):
            if isinstance(value,dict):
                for x in value.values():omit_one(x)
            elif isinstance(value,list):
                rows=[x for x in value if isinstance(x,dict)and x.get('type','').endswith('.SummonByCard')]
                if rows:value.remove(rows[-1])
                for x in value:omit_one(x)
        omit_one(bad['resolution_frame'])
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())
    def test_attack_tail_omission_in_live_and_original_work_is_rejected(self):
        g=self.game((SURGERY,),board=('k75.wait_attack',),enemy=('k75.wall',));self.surgery(g);bad=g.snapshot()
        nodes=wires(bad['resolution_frame'],'ForceAttack');self.assertTrue(nodes);target=nodes[-1]['fields']['attacker_id']
        def omit(value):
            if isinstance(value,dict):
                for x in value.values():omit(x)
            elif isinstance(value,list):
                value[:]=[x for x in value if not(isinstance(x,dict)and x.get('type','').endswith('.ForceAttack')and x['fields']['attacker_id']==target)]
                for x in value:omit(x)
        omit(bad['resolution_frame'])
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())
    def test_previous293_schema_rejected_and_private_material_stays_private(self):
        g=self.game((SURGERY,),board=('k75.wait_summon',),enemy=('k75.wall',));self.surgery(g);saved=g.snapshot();saved['schema_version']=293
        self.assertGreater(SNAPSHOT_SCHEMA_VERSION,293)
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())
        for p in(1,2):
            visible=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for key in('original','presence_id','zone_epoch','card_summon_history','character_attack_history','source_allocation','resolution_frames'):
                self.assertNotIn('"'+key+'"',visible)
        self.choose(g,'keep')


if __name__=='__main__':unittest.main()
