"""Actual native providers: payments, live conditions, combat and accepted tails."""
from copy import deepcopy
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.static_provider_cards import load_batch
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,
    HealingKind,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,SummonByCard,
    SummonCause,SummonEntryMaterial,TriggerSpec,UseHeroPower,Zone)
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,
    GrantKeyword,Heal,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import DamageKind,TribeChangeSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import canonical_digest

RUSH='CS3_038';SHADOW='END_031';TUTOR='TIME_856';GROM='CORE_EX1_414';BRAVE='CORE_OG_218'
PIRATE='CORE_WON_351';WARL='CORE_EX1_507';CAPTAIN='CORE_NEW1_027';CLEAVE='CORE_SCH_605'
KHAD='CORE_DAL_575';EXTRA='CATA_208';YETI='CORE_CS2_182';TIDE='CORE_EX1_506';AXE='CS2_106'
ROOTS=(RUSH,SHADOW,TUTOR,GROM,BRAVE,PIRATE,WARL,CAPTAIN,CLEAVE,KHAD,EXTRA)


def registry(mode=None):
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
    r.register_card(CardDefinition('k26.zero_body','Zero Attack defender',CardType.MINION,health=8,metadata=meta))
    scripts={
        'ping':lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        'zero':lambda c:(Damage(c.target_id,0,c.source_id,DamageKind.SPELL),),
        'heal1':lambda c:(Heal(c.target_id,1,c.source_id,HealingKind.SPELL),),
        'heal8':lambda c:(Heal(c.target_id,8,c.source_id,HealingKind.SPELL),),
        'silence':lambda c:(Silence(c.target_id),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'enemy_copy':lambda c:(CopyMinion(c.target_id,2),),
        'steal':lambda c:(ChangeControl(c.target_id,2),),
        'murloc':lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('murloc',)),c.source_id),),
        'shield':lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),),
        'break_weapon':lambda c:(Destroy(c.state.players[c.player_id].weapon_id,c.source_id),),
        'summon':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(YETI),),SummonCause.capture(c)),),
        'legacy':lambda c:(Summon(c.player_id,YETI),),
    }
    for name,body in scripts.items():
        key='k26.'+name;r.register_behavior(key,body)
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,
            requires_target=name not in ('summon','break_weapon','legacy'),metadata=meta))
    r.register_card(CardDefinition('k26.power','Reinforce fixture',CardType.HERO_POWER,cost=2,on_use='m2.reinforce',metadata=meta))
    r.register_behavior('k26.fail',lambda c:(AddToHand(c.player_id,'missing.k26'),))
    if mode:
        def wait(c):
            prefix=()
            if mode=='summon':
                history=c.state.card_summon_history
                if not history or not history[-1].deliveries or history[-1].deliveries[-1].index!=0:return ()
                if c.state.entities[c.event.target_id].card_id!=YETI:return ()
                prefix=tuple(Destroy(i,c.source_id)for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==KHAD)
            elif mode=='damage' and c.state.entities[c.event.target_id].card_id!=EXTRA:return ()
            return (*prefix,RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(
                InvokeBehavior('k26.fail',c.source_id,c.player_id),))),c.source_id))
        r.register_behavior('k26.wait',wait)
        event={'summon':'minion_summoned','attack':'attack_declared','damage':'damage_dealt'}[mode]
        r.register_card(CardDefinition('k26.watch','Boundary observer',CardType.MINION,health=8,metadata=meta,
            triggers=(TriggerSpec(event,'k26.wait'),)))
    return r


class StaticProviderCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),mode=None,power=None):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,hero_power_card_id=power),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40)),seed=426),registry(mode)if mode else self.r)
    def eid(self,g,cid,p=1,zone='board'):
        return next(i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def entity(self,g,cid,p=1):return g.state.entities[self.eid(g,cid,p)]
    def play(self,g,cid,target=None):
        p=g.state.active_player;i=self.eid(g,cid,p,'hand');g.apply(PlayCard(p,i,target_id=target));return i
    def op(self,g,name,target=None):return self.play(g,'k26.'+name,target)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def portable(self,g):
        s=g.snapshot();other=Game.from_snapshot(s,registry(self.mode));self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),s);return other
    def reject(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry(self.mode))

    def test_eleven_complete_source_pins_and_explicit_spell_damage_two(self):
        data=load_batch();self.assertEqual(tuple(x['record']['id']for x in data['cards']),ROOTS)
        for row in data['cards']:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            card=self.r.card(raw['id']);self.assertEqual((card.cost,card.attack,card.health),(raw['cost'],raw['attack'],raw['health']))
            self.assertEqual(card.metadata.deck_identity,row['recipe']['deck_identity'])
        raw=next(x['record']for x in data['cards']if x['record']['id']==TUTOR)
        self.assertEqual(raw['tags']['SPELLPOWER'],1);self.assertEqual(self.r.card(TUTOR).spell_damage,2)

    def test_each_root_enters_with_its_printed_body_and_one_payment(self):
        for cid in ROOTS:
            with self.subTest(card=cid):
                g=self.game((cid,));i=self.play(g,cid);card=g.registry.card(cid);e=g.state.entities[i]
                self.assertEqual((e.attack,e.health),(card.attack,card.health));self.assertEqual(g.state.players[1].mana,40-card.cost)
                self.assertEqual(sum(v.kind=='card_played'for v in g.events),1)
                self.assertEqual(sum(v.kind=='minion_summoned'for v in g.events),1)

    def test_actual_rush_entry_can_attack_minion_but_not_hero(self):
        g=self.game((RUSH,),enemy=(YETI,));i=self.play(g,RUSH);before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,i,self.hero(g,2).id))
        self.assertEqual(g.snapshot(),before);g.apply(Attack(1,i,self.eid(g,YETI,2)))
        self.assertEqual(self.entity(g,YETI,2).health,2);self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)

    def test_shadow_stealth_rejects_enemy_target_then_breaks_on_own_attack(self):
        g=self.game(('CORE_CS2_029',),board=(SHADOW,),enemy_hand=('CORE_CS2_029',));i=self.eid(g,SHADOW)
        self.play(g,'CORE_CS2_029',self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,23)
        self.assertIn(Keyword.STEALTH,g.state.entities[i].keywords);g.apply(Attack(1,i,self.hero(g,2).id))
        self.assertNotIn(Keyword.STEALTH,g.state.entities[i].keywords);self.end(g);self.play(g,'CORE_CS2_029',i)
        self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)

    def test_spell_damage_adds_three_and_silencing_one_removes_only_its_two(self):
        g=self.game(('CORE_CS2_029','k26.silence','CORE_CS2_029'),board=(SHADOW,TUTOR))
        self.play(g,'CORE_CS2_029',self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,21)
        self.op(g,'silence',self.eid(g,TUTOR));self.play(g,'CORE_CS2_029',self.hero(g,2).id)
        self.assertEqual(self.hero(g,2).health,14);self.portable(g)

    def test_spell_damage_does_not_benefit_opponent(self):
        g=self.game(board=(TUTOR,),enemy_hand=('CORE_CS2_029',));self.end(g)
        self.play(g,'CORE_CS2_029',self.hero(g).id);self.assertEqual(self.hero(g).health,24)

    def test_grom_damaged_condition_is_live_not_repeated_per_hit(self):
        g=self.game(('k26.ping','k26.ping','k26.heal1','k26.heal8'),board=(GROM,));i=self.eid(g,GROM)
        self.op(g,'ping',i);self.assertEqual(g.state.entities[i].attack,10)
        self.op(g,'ping',i);self.assertEqual(g.state.entities[i].attack,10)
        self.op(g,'heal1',i);self.assertEqual(g.state.entities[i].attack,10)
        self.op(g,'heal8',i);self.assertEqual((g.state.entities[i].attack,g.state.entities[i].health),(4,9));self.portable(g)

    def test_bloodhoof_has_three_conditional_attack_and_silence_removes_it(self):
        g=self.game(('k26.ping','k26.silence'),board=(BRAVE,));i=self.eid(g,BRAVE)
        self.op(g,'ping',i);self.assertEqual(g.state.entities[i].attack,5)
        self.op(g,'silence',i);self.assertEqual(g.state.entities[i].attack,2);self.assertNotIn(Keyword.TAUNT,g.state.entities[i].keywords)

    def test_grom_first_exchange_uses_pre_damage_attack_then_refreshes_to_ten(self):
        g=self.game((GROM,),enemy=(YETI,));i=self.play(g,GROM);g.apply(Attack(1,i,self.eid(g,YETI,2)))
        self.assertEqual(self.entity(g,YETI,2).health,1);self.assertEqual((g.state.entities[i].attack,g.state.entities[i].health),(10,5))

    def test_weapon_presence_tracks_actual_equipment_and_break(self):
        g=self.game((AXE,'k26.break_weapon'),board=(PIRATE,));i=self.eid(g,PIRATE)
        self.assertEqual(g.state.entities[i].attack,1);self.play(g,AXE);self.assertEqual(g.state.entities[i].attack,3)
        self.op(g,'break_weapon');self.assertEqual(g.state.entities[i].attack,1);self.portable(g)

    def test_weapon_presence_rebinds_to_current_controller_not_original_owner(self):
        g=self.game((AXE,'k26.steal'),board=(PIRATE,),enemy_hand=(AXE,));i=self.eid(g,PIRATE)
        self.play(g,AXE);self.op(g,'steal',i);self.assertEqual(g.state.entities[i].attack,1)
        self.end(g);self.play(g,AXE);self.assertEqual(g.state.entities[i].attack,3);self.portable(g)

    def test_warleader_buffs_only_other_friendly_current_murlocs(self):
        g=self.game(board=(WARL,TIDE,YETI),enemy=(TIDE,))
        self.assertEqual(self.entity(g,WARL).attack,3);self.assertEqual(self.entity(g,TIDE).attack,4)
        self.assertEqual(self.entity(g,YETI).attack,4);self.assertEqual(self.entity(g,TIDE,2).attack,2)

    def test_warleader_source_silence_death_and_bounce_remove_contribution(self):
        for op in ('silence','kill','bounce'):
            with self.subTest(operation=op):
                g=self.game(('k26.'+op,),board=(WARL,TIDE));self.op(g,op,self.eid(g,WARL));self.assertEqual(self.entity(g,TIDE).attack,2)

    def test_tribal_aura_uses_current_race_and_recipient_silence_restores_printed_race(self):
        g=self.game(('k26.murloc','k26.silence'),board=(WARL,YETI));i=self.eid(g,YETI)
        self.op(g,'murloc',i);self.assertEqual(g.state.entities[i].attack,6)
        self.op(g,'silence',i);self.assertEqual(g.state.entities[i].attack,4);self.portable(g)

    def test_captains_stack_independently_without_buffing_their_own_source(self):
        g=self.game(('k26.silence',),board=(CAPTAIN,CAPTAIN,PIRATE));caps=g.state.players[1].board[:2]
        self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].max_health)for i in caps],[(4,4),(4,4)])
        self.assertEqual((self.entity(g,PIRATE).attack,self.entity(g,PIRATE).max_health),(3,4))
        self.op(g,'silence',caps[0]);self.assertEqual((self.entity(g,PIRATE).attack,self.entity(g,PIRATE).max_health),(2,3))
        self.portable(g)

    def test_recipient_silence_does_not_remove_external_pirate_aura(self):
        g=self.game(('k26.silence',),board=(CAPTAIN,PIRATE));self.op(g,'silence',self.eid(g,PIRATE))
        self.assertEqual((self.entity(g,PIRATE).attack,self.entity(g,PIRATE).max_health),(2,3))

    def test_actual_cleave_hits_both_neighbors_and_has_one_combat_exchange(self):
        g=self.game(board=(CLEAVE,),enemy=(YETI,YETI,YETI));targets=g.state.players[2].board
        g.apply(Attack(1,self.eid(g,CLEAVE),targets[1]));self.assertEqual([g.state.entities[i].health for i in targets],[1,1,1])
        self.assertEqual(self.entity(g,CLEAVE).health,2);self.assertEqual(sum(v.kind=='attack_declared'for v in g.events),1);self.portable(g)

    def test_cleave_on_hero_has_no_neighbors_and_silence_removes_extra_hits(self):
        g=self.game(board=(CLEAVE,),enemy=(YETI,YETI,YETI));g.apply(Attack(1,self.eid(g,CLEAVE),self.hero(g,2).id))
        self.assertEqual(self.hero(g,2).health,26);self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[5,5,5])
        g=self.game(('k26.silence',),board=(CLEAVE,),enemy=(YETI,YETI,YETI));self.op(g,'silence',self.eid(g,CLEAVE))
        targets=g.state.players[2].board;g.apply(Attack(1,self.eid(g,CLEAVE),targets[1]))
        self.assertEqual([g.state.entities[i].health for i in targets],[5,1,5])

    def test_khadgar_doubles_battlecry_tokens_not_the_played_minion(self):
        g=self.game((TIDE,),board=(KHAD,));i=self.play(g,TIDE);board=g.state.players[1].board
        self.assertEqual(len(board),4);self.assertEqual(sum(g.state.entities[j].card_id==TIDE for j in board),1)
        self.assertEqual(sum(g.state.entities[j].attack==1 and g.state.entities[j].health==1 for j in board),2)
        self.assertEqual(g.state.players[1].mana,38);self.assertEqual(len(g.state.card_summon_history),1);self.portable(g)

    def test_khadgar_multiplier_product_and_full_board_clamp(self):
        g=self.game((TIDE,),board=(KHAD,KHAD));self.play(g,TIDE);self.assertEqual(len(g.state.players[1].board),7)
        g=self.game((TIDE,),board=(KHAD,YETI,YETI,YETI,YETI));self.play(g,TIDE)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(len(g.state.card_summon_history[-1].deliveries),2)

    def test_khadgar_silence_disables_later_own_card_summons(self):
        g=self.game(('k26.silence',TIDE),board=(KHAD,));self.op(g,'silence',self.eid(g,KHAD));self.play(g,TIDE)
        self.assertEqual(len(g.state.players[1].board),3);self.portable(g)

    def test_khadgar_accepted_extra_survives_source_death_and_waiting_rollback(self):
        g=self.game(('k26.summon',),board=(KHAD,'k26.watch'),mode='summon');self.op(g,'summon')
        self.assertIsNotNone(g.state.pending_choice);self.assertNotIn(KHAD,[g.state.entities[i].card_id for i in g.state.players[1].board])
        restored=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        for branch in (g,restored):self.choose(branch);self.assertEqual(sum(branch.state.entities[i].card_id==YETI for i in branch.state.players[1].board),2)
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_incoming_damage_plus_one_is_self_only_and_not_a_cap(self):
        g=self.game(('k26.ping','k26.ping','CORE_CS2_029'),board=(EXTRA,YETI));i=self.eid(g,EXTRA)
        self.op(g,'ping',self.eid(g,YETI));self.assertEqual(self.entity(g,YETI).health,4)
        self.op(g,'ping',i);self.assertEqual(g.state.entities[i].health,4)
        self.play(g,'CORE_CS2_029',i);self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)

    def test_incoming_damage_plus_one_applies_to_combat_and_shield_then_silence(self):
        g=self.game(('k26.shield','k26.ping','k26.ping','k26.silence','k26.ping'),board=(EXTRA,));i=self.eid(g,EXTRA)
        self.op(g,'shield',i);self.op(g,'ping',i);self.assertEqual(g.state.entities[i].health,6)
        self.op(g,'ping',i);self.assertEqual(g.state.entities[i].health,4)
        self.op(g,'silence',i);self.op(g,'ping',i);self.assertEqual(g.state.entities[i].health,3)
        g=self.game(board=(EXTRA,),enemy=(YETI,));self.end(g);g.apply(Attack(2,self.eid(g,YETI,2),self.eid(g,EXTRA)))
        self.assertEqual(self.entity(g,EXTRA).health,1)

    def test_zero_attack_counter_is_not_created_into_one_damage(self):
        g=self.game(board=(EXTRA,),enemy=('k26.zero_body',));g.apply(Attack(1,self.eid(g,EXTRA),self.eid(g,'k26.zero_body',2)))
        self.assertEqual(self.entity(g,EXTRA).health,6)

    def test_zero_base_spell_still_gets_spell_bonus_then_recipient_modifier(self):
        g=self.game(('k26.zero',),board=(EXTRA,TUTOR));self.op(g,'zero',self.eid(g,EXTRA))
        self.assertEqual(self.entity(g,EXTRA).health,3)

    def test_khadgar_covers_existing_representative_combo_producer(self):
        g=self.game((KHAD,'CORE_EX1_131'));self.play(g,KHAD);self.play(g,'CORE_EX1_131')
        self.assertEqual(len(g.state.players[1].board),4);self.assertEqual(len(g.state.card_summon_history),1);self.portable(g)

    def test_opponent_summon_does_not_borrow_friendly_khadgar(self):
        g=self.game(board=(KHAD,),enemy_hand=(TIDE,));self.end(g);self.play(g,TIDE)
        self.assertEqual(len(g.state.players[2].board),2);self.assertEqual(len(g.state.players[1].board),1);self.portable(g)

    def test_hero_power_is_not_a_card_for_default_khadgar_quantity(self):
        g=self.game(board=(KHAD,),power='k26.power');g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual(len(g.state.players[1].board),2);self.assertEqual(len(g.state.card_summon_history),1);self.portable(g)

    def test_unattributed_legacy_request_still_fails_and_rolls_back(self):
        g=self.game(('k26.legacy',),board=(KHAD,));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.op(g,'legacy')
        self.assertEqual(g.snapshot(),before)

    def test_health_rule_waiting_restores_actual_modified_damage(self):
        g=self.game(('k26.ping',),board=(EXTRA,'k26.watch'),mode='damage');self.op(g,'ping',self.eid(g,EXTRA))
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.entity(g,EXTRA).health,4)
        restored=self.portable(g);self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())

    def test_attack_waiting_resumes_cleave_through_public_choice(self):
        g=self.game(board=(CLEAVE,'k26.watch'),enemy=(YETI,YETI,YETI),mode='attack');targets=g.state.players[2].board
        g.apply(Attack(1,self.eid(g,CLEAVE),targets[1]));self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g)
        for branch in (g,restored):self.choose(branch);self.assertEqual([branch.state.entities[i].health for i in targets],[1,1,1])
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_original_native_declarations_and_private_work_are_not_replaceable(self):
        for cid,kind,field,value in ((GROM,'stat_relation','stat_relation',None),(KHAD,'summon_quantity','summon_quantity',None)):
            with self.subTest(card=cid):
                g=self.game(board=(cid,));s=g.snapshot();rows=s['state']['entities'][str(self.eid(g,cid))]['abilities']
                row=next(a for a in rows if a['kind']==kind);row[field]['amount'if cid==GROM else'factor']=7 if cid==GROM else 3
                self.reject(s)
        g=self.game(board=(WARL,TIDE,KHAD,TUTOR));before=g.snapshot()
        for p in (1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.for_player(p).legal_actions())
            for key in ('conditional_attack','stat_relations','resolution_frame','health_rules','rule_ids'):
                self.assertNotIn('"'+key+'"',public)
        self.assertEqual(g.snapshot(),before)
