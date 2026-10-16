"""Actual corpse consumers: physical draw, gain lifecycle, quest loop and powers."""
from copy import deepcopy
from dataclasses import asdict, replace
import json, unittest
from pathlib import Path

from hs_sim.cards import build_registry
from hs_sim.cards.corpse_consumer_native_cards import (load_batch,BATCH_HASH,SWARM,ANTS,BITES,ANT,FALRIC,QUEST,TYRAX,GRAVE,THALENA,KISS)
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,
    Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,UseHeroPower,UseLocation,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.corpse_gains import CorpseGainProfile
from hs_sim.engine.dormancy import AwakenMinion,MakeDormant
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,DestroyBatch,GainResource,
    InvokeBehavior,RequestChoice,ReturnToHand,Silence,SpendResource,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import UpgradeHandCard
from hs_sim.engine.locations import DestroyLocation
from hs_sim.engine.model import AbilityInstance,LimitedTriggerSpec,PaymentType,Resource
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine.resource_operations import SpendUpToResource
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

YETI='CORE_CS2_182';FOOTMAN='RLK_061t';META=CardMetadata(False,(CardClass.NEUTRAL,),None)


def registry():
    r=build_registry()
    def fail(c):raise ResolutionError('K73 deliberate late failure')
    r.register_behavior('k73.fail',fail)
    def reenter(c):
        e=c.state.entities[c.target_id]
        return(SummonStoredCard(CardReference.capture(e),e.controller),)
    r.register_behavior('k73.reenter',reenter)
    def upgrade(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==YETI)
        return(UpgradeHandCard(CardReference.capture(e),FALRIC,c.source_id),)
    scripts=dict(gain2=lambda c:(GainResource(c.player_id,Resource.CORPSES,2),),
        gain0=lambda c:(GainResource(c.player_id,Resource.CORPSES,0),),
        spend3=lambda c:(SpendResource(c.player_id,Resource.CORPSES,3),),
        spend12=lambda c:(SpendResource(c.player_id,Resource.CORPSES,12),),
        cap20=lambda c:(SpendUpToResource(c.player_id,Resource.CORPSES,20,c.source_id),),
        cap0=lambda c:(SpendUpToResource(c.player_id,Resource.CORPSES,0,c.source_id),),
        kill=lambda c:(Destroy(c.target_id,c.source_id),),
        kill_all=lambda c:(DestroyBatch(tuple(c.state.players[1].board),c.source_id),),
        silence=lambda c:(Silence(c.target_id),),bounce=lambda c:(ReturnToHand(c.target_id),),
        give=lambda c:(ChangeControl(c.target_id,2),),copy=lambda c:(CopyMinion(c.target_id,c.player_id),),
        form=lambda c:(Transform(c.target_id,'k73.shape'),),falric=lambda c:(Transform(c.target_id,FALRIC),),
        dormant=lambda c:(MakeDormant(c.target_id,None,c.source_id),),
        awake=lambda c:tuple(AwakenMinion(i,c.source_id)for i in c.state.players[c.player_id].board if c.state.entities[i].dormancy is not None),
        grave_kill=lambda c:(DestroyLocation(c.target_id,c.source_id),),upgrade=upgrade)
    no_target={'gain2','gain0','spend3','spend12','cap20','cap0','kill_all','upgrade','awake'}
    for key,body in scripts.items():
        cid='k73.'+key;r.register_behavior(cid,body)
        fields=dict(targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.LOCATION,)))if key=='grave_kill'else dict(requires_target=key not in no_target)
        r.register_card(CardDefinition(cid,key,CardType.SPELL,on_play=cid,metadata=META,**fields))
    r.register_card(CardDefinition('k73.shape','Changed target',CardType.MINION,attack=1,health=9,metadata=META))
    r.register_card(CardDefinition('k73.spellpower','Spell Damage source',CardType.MINION,health=6,spell_damage=2,metadata=META))
    r.register_card(CardDefinition('k73.both','Both choices source',CardType.MINION,health=6,choose_both=True,metadata=META))
    def wait(c):
        options=[ChoiceOption('keep','Continue',()),ChoiceOption('fail','Fail',(InvokeBehavior('k73.fail',c.source_id,c.player_id),))]
        if c.event.kind=='resource_spent' and c.state.cast_history:
            target=c.state.cast_history[-1].target_id
            if target is not None:
                options.extend((ChoiceOption('form','Transform original target',(Transform(target,'k73.shape'),)),
                    ChoiceOption('give','Give original target',(ChangeControl(target,1),)),
                    ChoiceOption('bounce','Return original target',(ReturnToHand(target),)),
                    ChoiceOption('reenter','Return then summon',(ReturnToHand(target),InvokeBehavior('k73.reenter',c.source_id,2,target)))))
        return(RequestChoice(c.player_id,tuple(options),c.source_id),)
    r.register_behavior('k73.wait',wait)
    for cid,event in(('k73.wait','resource_spent'),('k73.gain_wait','resource_gained')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=12,
            limited_triggers=(LimitedTriggerSpec(event,'k73.wait'),),metadata=META))
    r.register_card(CardDefinition('k73.breaker','Late rollback source',CardType.MINION,health=12,
        triggers=(TriggerSpec('resource_spent','k73.fail'),),metadata=META))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
    return saved


def wires(value,name):
    result=[]
    if isinstance(value,dict):
        if value.get('type','').endswith('.'+name):result.append(value)
        for x in value.values():result.extend(wires(x,name))
    elif isinstance(value,list):
        for x in value:result.extend(wires(x,name))
    return result


class CorpseConsumerNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),corpses=20,enemy=(),enemy_hand=(),deck=None,mana=30):
        deck=(YETI,)*8 if deck is None else deck
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=mana,max_mana=30,mana_cap=30,corpses=corpses,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=30,max_mana=30,mana_cap=30,corpses=20,hero_power_card_id='HERO_08bp')),seed=1073),self.r)
    def entities(self,g,cid,p=1,zone='board'):
        s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid]
    def play(self,g,cid,target=None,p=1,branch=None):
        eid=self.entities(g,cid,p,'hand')[0].id;g.apply(PlayCard(p,eid,target,branch_id=branch));return eid
    def bank(self,g,p=1):return g.state.players[p].resources[Resource.CORPSES]
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def portable(self,g):
        saved=g.snapshot();other=Game.from_snapshot(saved,registry());self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return other
    def quest(self,g):
        s=g.state;return s.entities[s.players[1].quests[0]]
    def power(self,g):return next(g.state.entities[i]for i in g.state.players[1].hero_power_ids if g.state.entities[i].card_id==KISS)

    def test_complete_roots_children_and_full_source_spender_membership(self):
        data=load_batch();self.assertEqual(canonical_digest(data),BATCH_HASH)
        self.assertEqual((len(data['cards']),len(data['dependencies'])),(4,6))
        source=json.loads((Path(__file__).resolve().parents[1]/data['source']['path']).read_text(encoding='utf-8-sig'))
        self.assertEqual([x['record']for x in data['corpse_spender_records']],[x for x in source if x['tags'].get('CORPSE_SPENDER')==1])
        self.assertEqual(len(data['corpse_spender_records']),81)
        for row in data['cards']+data['dependencies']+data['evidence_only']+data['corpse_spender_records']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
    def test_old1023_complete_definitions_and_default_fingerprint_unchanged(self):
        old=json.loads((Path(__file__).resolve().parents[1]/'outputs/card-integration-20261014/k73-before/definition-digests.json').read_text(encoding='utf-8'))
        self.assertEqual(len(old),1023);self.assertEqual(old,{cid:canonical_digest(asdict(self.r.card(cid)))for cid in old})
        self.assertEqual(representative().fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')
    def test_official_stats_dual_tribes_location_and_native_corpse_cost(self):
        for cid in(ANT,TYRAX):self.assertEqual(set(x.lower()for x in self.r.card(cid).metadata.tribes),{'beast','undead'})
        self.assertEqual((self.r.card(GRAVE).kind,self.r.card(GRAVE).durability),(CardType.LOCATION,2))
        self.assertEqual((self.r.card(KISS).cost,self.r.card(KISS).cost_payment),(3,PaymentType.CORPSES))
        self.assertEqual(self.r.card(FALRIC).metadata.deck_identity,'EDR_003')
    def test_falric_resource_gain_is_doubled_without_mutating_base_value(self):
        g=self.game(('k73.gain2',),board=(FALRIC,),corpses=0);self.play(g,'k73.gain2')
        self.assertEqual(self.bank(g),4);self.assertEqual(self.entities(g,FALRIC)[0].corpse_value,1)
        self.assertEqual([e.amount for e in g.events if e.kind=='resource_gained'],[4]);self.portable(g)
    def test_falric_multiple_live_sources_multiply_and_zero_stays_zero(self):
        g=self.game(('k73.gain0','k73.gain2'),board=(FALRIC,FALRIC),corpses=0)
        self.play(g,'k73.gain0');self.assertEqual(self.bank(g),0);self.play(g,'k73.gain2');self.assertEqual(self.bank(g),8)
    def test_falric_death_credit_multiplies_actual_amount_not_intrinsic_record(self):
        g=self.game(('k73.kill',),board=(FALRIC,YETI),corpses=0);self.play(g,'k73.kill',self.entities(g,YETI)[0].id)
        self.assertEqual(self.bank(g),2);self.assertEqual(g.state.death_history[-1].corpse_value,1)
        self.assertEqual(next(e.amount for e in g.events if e.kind=='resource_gained'),2);self.portable(g)
    def test_falric_cannot_turn_no_corpse_footman_into_positive_credit(self):
        g=self.game(('k73.kill',),board=(FALRIC,FOOTMAN),corpses=0);self.play(g,'k73.kill',self.entities(g,FOOTMAN)[0].id)
        self.assertEqual(self.bank(g),0);self.assertFalse([e for e in g.events if e.kind=='resource_gained'])
    def test_falric_simultaneous_self_and_ally_death_remove_provider_before_credit(self):
        g=self.game(('k73.kill_all',),board=(FALRIC,YETI),corpses=0);self.play(g,'k73.kill_all')
        self.assertEqual(self.bank(g),2);self.assertEqual([d.corpse_value for d in g.state.death_history],[1,1]);self.portable(g)
    def test_falric_one_dead_copy_still_uses_surviving_provider(self):
        g=self.game(('k73.kill',),board=(FALRIC,FALRIC),corpses=0);self.play(g,'k73.kill',self.entities(g,FALRIC)[0].id)
        self.assertEqual(self.bank(g),2)
    def test_falric_silence_removes_gain_source(self):
        g=self.game(('k73.silence','k73.gain2'),board=(FALRIC,),corpses=0)
        self.play(g,'k73.silence',self.entities(g,FALRIC)[0].id);self.play(g,'k73.gain2');self.assertEqual(self.bank(g),2);self.portable(g)
    def test_falric_bounce_stops_provider_and_replay_restores_it_on_play(self):
        g=self.game(('k73.bounce','k73.gain2','k73.gain2'),board=(FALRIC,),corpses=0);old=self.entities(g,FALRIC)[0].id
        self.play(g,'k73.bounce',old);self.play(g,'k73.gain2');self.assertEqual(self.bank(g),2)
        self.play(g,FALRIC);self.play(g,'k73.gain2');self.assertEqual(self.bank(g),6);self.portable(g)
    def test_falric_control_transfer_follows_current_beneficiary(self):
        g=self.game(('k73.give','k73.gain2'),board=(FALRIC,),enemy_hand=('k73.gain2',),corpses=0)
        self.play(g,'k73.give',self.entities(g,FALRIC)[0].id);self.play(g,'k73.gain2');self.assertEqual(self.bank(g),2)
        g.apply(EndTurn(1));self.play(g,'k73.gain2',p=2);self.assertEqual(self.bank(g,2),24);self.portable(g)
    def test_falric_transform_out_removes_and_transform_in_installs_provider(self):
        g=self.game(('k73.form','k73.gain2','k73.falric','k73.gain2'),board=(FALRIC,),corpses=0);eid=self.entities(g,FALRIC)[0].id
        self.play(g,'k73.form',eid);self.play(g,'k73.gain2');self.assertEqual(self.bank(g),2)
        self.play(g,'k73.falric',eid);self.play(g,'k73.gain2');self.assertEqual(self.bank(g),6);self.portable(g)
    def test_falric_current_copy_retains_native_provider(self):
        g=self.game(('k73.copy','k73.gain2'),board=(FALRIC,),corpses=0)
        self.play(g,'k73.copy',self.entities(g,FALRIC)[0].id);self.play(g,'k73.gain2');self.assertEqual(self.bank(g),8);self.portable(g)
    def test_falric_silenced_current_copy_does_not_reinstall_provider(self):
        g=self.game(('k73.silence','k73.copy','k73.gain2'),board=(FALRIC,),corpses=0);eid=self.entities(g,FALRIC)[0].id
        self.play(g,'k73.silence',eid);self.play(g,'k73.copy',eid);self.play(g,'k73.gain2');self.assertEqual(self.bank(g),2)
    def test_falric_dormant_provider_waits_for_real_awaken(self):
        g=self.game(('k73.dormant','k73.gain2','k73.awake','k73.gain2'),board=(FALRIC,),corpses=0);eid=self.entities(g,FALRIC)[0].id
        self.play(g,'k73.dormant',eid);self.play(g,'k73.gain2');self.assertEqual(self.bank(g),2)
        self.play(g,'k73.awake');self.play(g,'k73.gain2');self.assertEqual(self.bank(g),6);self.portable(g)
    def test_falric_hand_upgrade_uses_same_native_installation(self):
        g=self.game(('k73.upgrade',YETI,'k73.gain2'),corpses=0);self.play(g,'k73.upgrade')
        self.play(g,FALRIC);self.play(g,'k73.gain2');self.assertEqual(self.bank(g),4);self.portable(g)
    def test_falric_battlecry_draws_only_actual_tagged_spender(self):
        g=self.game((FALRIC,),deck=(YETI,'CATA_465',YETI),corpses=0);self.play(g,FALRIC)
        self.assertEqual([e.card_id for e in self.entities(g,'CATA_465',zone='hand')],['CATA_465'])
        self.assertEqual(len(g.state.players[1].deck),2);self.portable(g)
    def test_falric_empty_matching_deck_skips_without_draw_or_fatigue(self):
        for deck in((),(YETI,)):
            g=self.game((FALRIC,),deck=deck);self.play(g,FALRIC)
            self.assertFalse(g.state.players[1].hand);self.assertFalse([e for e in g.events if e.kind in('card_drawn','fatigue')])
    def test_falric_gain_reactions_see_actual_multiplied_bank_and_can_restore(self):
        g=self.game(('k73.gain2',),board=(FALRIC,'k73.gain_wait'),corpses=0);self.play(g,'k73.gain2')
        self.assertEqual(self.bank(g),4);self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g)
        self.choose(g,'keep');self.choose(restored,'keep');self.assertEqual(g.snapshot(),restored.snapshot())
    def test_swarm_ants_are_two_real_attributed_dual_tribe_minions(self):
        g=self.game((SWARM,),corpses=0);self.play(g,SWARM,branch='ants')
        self.assertEqual([(e.attack,e.health,e.corpse_value)for e in self.entities(g,ANT)],[(1,1,1),(1,1,1)])
        self.assertEqual(len(g.state.successful_summon_history),2);self.assertFalse(g.state.corpse_spend_history);self.portable(g)
    def test_swarm_damage_spends_exact_two_and_uses_spell_bonus(self):
        g=self.game((SWARM,),board=('k73.spellpower',),enemy=('k73.shape',),corpses=2);eid=self.entities(g,'k73.shape',2)[0].id
        self.play(g,SWARM,eid,branch='bites');self.assertEqual(g.state.entities[eid].health,3);self.assertEqual(self.bank(g),0)
        self.assertEqual([d.amount for d in g.state.corpse_spend_history],[2]);self.portable(g)
    def test_swarm_insufficient_bank_skips_damage_without_partial_spend(self):
        g=self.game((SWARM,),enemy=(YETI,),corpses=1);self.play(g,SWARM,self.entities(g,YETI,2)[0].id,branch='bites')
        self.assertEqual((self.bank(g),self.entities(g,YETI,2)[0].health,g.state.players[1].mana),(1,5,29))
        self.assertFalse(g.state.corpse_spend_history)
    def test_swarm_branches_enforce_target_and_combination_legality(self):
        g=self.game((SWARM,),enemy=(YETI,));eid=self.entities(g,SWARM,zone='hand')[0].id
        for action in(PlayCard(1,eid),PlayCard(1,eid,branch_id='bites'),PlayCard(1,eid,g.state.players[2].hero_id,branch_id='bites'),
                PlayCard(1,eid,branch_id='both'),PlayCard(1,eid,self.entities(g,YETI,2)[0].id,branch_id='ants')):
            before=g.snapshot()
            with self.assertRaises(IllegalAction):g.apply(action)
            self.assertEqual(g.snapshot(),before)
    def test_swarm_full_board_summon_branch_uses_existing_failed_summons(self):
        g=self.game((SWARM,),board=(YETI,)*7);self.play(g,SWARM,branch='ants');self.assertFalse(self.entities(g,ANT));self.assertEqual(len(g.state.players[1].board),7)
    def test_swarm_combined_source_uses_ants_then_real_corpse_payment(self):
        g=self.game((SWARM,),board=('k73.both',),enemy=(YETI,),corpses=2)
        self.play(g,SWARM,self.entities(g,YETI,2)[0].id,branch='both')
        self.assertEqual(len(self.entities(g,ANT)),2);self.assertEqual(self.entities(g,YETI,2)[0].health,1);self.assertEqual(self.bank(g),0);self.portable(g)
    def test_real_child_spells_are_executable_physical_faces(self):
        g=self.game((ANTS,BITES),enemy=(YETI,),corpses=2);self.play(g,ANTS);self.play(g,BITES,self.entities(g,YETI,2)[0].id)
        self.assertEqual((len(self.entities(g,ANT)),self.entities(g,YETI,2)[0].health),(2,1))
        self.assertFalse(self.r.card(ANTS).choice_only);self.assertFalse(self.r.card(BITES).choice_only)
    def test_swarm_original_target_transform_and_control_keep_same_residence(self):
        for choice in('form','give'):
            g=self.game((SWARM,),board=('k73.wait',),enemy=(YETI,),corpses=2);eid=self.entities(g,YETI,2)[0].id
            self.play(g,SWARM,eid,branch='bites');restored=self.portable(g);self.choose(g,choice);self.choose(restored,choice)
            self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.state.entities[eid].health,5 if choice=='form'else 1)
    def test_swarm_departure_and_reentry_never_rebind_paid_damage(self):
        for choice in('bounce','reenter'):
            g=self.game((SWARM,),board=('k73.wait',),enemy=(YETI,),corpses=2);eid=self.entities(g,YETI,2)[0].id
            self.play(g,SWARM,eid,branch='bites');self.portable(g);self.choose(g,choice)
            self.assertEqual(g.state.entities[eid].health,5);self.assertEqual(self.bank(g),0);self.portable(g)
    def test_swarm_late_resource_failure_rolls_back_whole_action(self):
        g=self.game((SWARM,),board=('k73.breaker',),enemy=(YETI,),corpses=2);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,SWARM,self.entities(g,YETI,2)[0].id,branch='bites')
        self.assertEqual(g.snapshot(),before)
    def test_quest_fixed_actual_amounts_complete_once_and_deliver_real_reward(self):
        g=self.game((QUEST,'k73.spend3','k73.spend12'));self.play(g,QUEST);self.play(g,'k73.spend3')
        self.assertEqual(self.quest(g).quest_progress.value,3);self.play(g,'k73.spend12')
        self.assertFalse(g.state.players[1].quests);self.assertEqual(len(self.entities(g,TYRAX,zone='hand')),1)
        self.assertEqual(self.bank(g),5);self.portable(g)
    def test_quest_capped_spend_uses_actual_not_requested_cap(self):
        g=self.game((QUEST,'k73.cap20'),corpses=7);self.play(g,QUEST);self.play(g,'k73.cap20')
        self.assertEqual(self.quest(g).quest_progress.value,7);self.assertEqual(self.bank(g),0);self.portable(g)
    def test_quest_zero_failed_and_enemy_spending_do_not_advance(self):
        g=self.game((QUEST,'k73.cap0','k73.spend3'),corpses=1,enemy_hand=('k73.spend3',))
        self.play(g,QUEST);self.play(g,'k73.cap0');self.play(g,'k73.spend3');g.apply(EndTurn(1));self.play(g,'k73.spend3',p=2)
        self.assertEqual(self.quest(g).quest_progress.value,0);self.portable(g)
    def test_quest_does_not_retroactively_count_earlier_spends(self):
        g=self.game(('k73.spend3',QUEST));self.play(g,'k73.spend3');self.play(g,QUEST)
        self.assertEqual(self.quest(g).quest_progress.value,0)
    def test_quest_real_corpse_power_payment_counts_once_as_actual_three(self):
        g=self.game((QUEST,THALENA,'k73.spend12'),board=(YETI,));self.play(g,QUEST);self.play(g,THALENA);self.play(g,'k73.spend12')
        g.apply(UseHeroPower(1,self.power(g).id,self.entities(g,YETI)[0].id))
        self.assertFalse(g.state.players[1].quests);self.assertEqual(len(self.entities(g,TYRAX,zone='hand')),1)
        self.assertEqual([r.origin for r in g.state.corpse_spend_history],['fixed','payment']);self.portable(g)
    def test_tyrax_death_places_open_real_grave_in_original_slot(self):
        g=self.game(('k73.kill',),board=(YETI,TYRAX,YETI),corpses=0);self.play(g,'k73.kill',self.entities(g,TYRAX)[0].id)
        grave=self.entities(g,GRAVE)[0];self.assertEqual((grave.durability,grave.location_cooldown),(2,0))
        self.assertEqual(g.state.players[1].board.index(grave.id),1);self.assertEqual(self.bank(g),1);self.portable(g)
    def test_grave_two_actual_uses_cooldown_damage_and_tyrax_resummon(self):
        g=self.game(board=(GRAVE,),corpses=0);eid=self.entities(g,GRAVE)[0].id;hero=g.state.players[2].hero_id
        g.apply(UseLocation(1,eid,hero));self.assertEqual(g.state.entities[hero].health,26)
        with self.assertRaises(IllegalAction):g.apply(UseLocation(1,eid,hero))
        self.cycle(g);self.assertEqual(g.state.entities[eid].location_cooldown,1)
        self.cycle(g);g.apply(UseLocation(1,eid,hero))
        self.assertEqual(g.state.entities[hero].health,22);self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.assertEqual([(e.attack,e.health)for e in self.entities(g,TYRAX)],[(8,8)]);self.assertEqual(self.bank(g),0);self.portable(g)
    def test_grave_damage_ignores_spell_damage_source(self):
        g=self.game(board=(GRAVE,'k73.spellpower'));g.apply(UseLocation(1,self.entities(g,GRAVE)[0].id,g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,26)
    def test_grave_destroyed_without_using_also_resummons_real_tyrax(self):
        g=self.game(('k73.grave_kill',),board=(GRAVE,),corpses=0);self.play(g,'k73.grave_kill',self.entities(g,GRAVE)[0].id)
        self.assertEqual(len(self.entities(g,TYRAX)),1);self.assertEqual(self.bank(g),0);self.portable(g)
    def test_thalena_adds_fixed_secondary_without_changing_primary(self):
        g=self.game((THALENA,));old=g.state.players[1].hero_power_id;self.play(g,THALENA)
        self.assertEqual(g.state.players[1].hero_power_id,old);self.assertEqual(len(g.state.players[1].hero_power_ids),2)
        self.assertNotEqual(self.power(g).id,old);self.portable(g)
    def test_kiss_pays_corpses_at_zero_mana_and_grants_attack_to_enemy_minion(self):
        g=self.game((THALENA,),enemy=(YETI,),corpses=3,mana=4);self.play(g,THALENA);eid=self.entities(g,YETI,2)[0].id
        g.apply(UseHeroPower(1,self.power(g).id,eid));self.assertEqual((self.bank(g),g.state.players[1].mana,g.state.entities[eid].attack),(0,0,7));self.portable(g)
    def test_kiss_insufficient_corpses_does_not_fall_back_to_mana(self):
        g=self.game((THALENA,),board=(YETI,),corpses=2);self.play(g,THALENA);before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(UseHeroPower(1,self.power(g).id,self.entities(g,YETI)[0].id))
        self.assertEqual(g.snapshot(),before)
    def test_kiss_has_own_use_counter_and_both_powers_can_activate(self):
        g=self.game((THALENA,),board=(YETI,));self.play(g,THALENA);power=self.power(g);target=self.entities(g,YETI)[0].id
        g.apply(UseHeroPower(1,power.id,target));g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,g.state.players[2].hero_id))
        with self.assertRaises(IllegalAction):g.apply(UseHeroPower(1,power.id,target))
        self.cycle(g);g.apply(UseHeroPower(1,power.id,target));self.assertEqual(g.state.entities[target].attack,10);self.portable(g)
    def test_kiss_cannot_target_hero_and_survives_thalena_silence(self):
        g=self.game((THALENA,'k73.silence'),board=(YETI,));self.play(g,THALENA);power=self.power(g)
        with self.assertRaises(IllegalAction):g.apply(UseHeroPower(1,power.id,g.state.players[2].hero_id))
        self.play(g,'k73.silence',self.entities(g,THALENA)[0].id)
        g.apply(UseHeroPower(1,power.id,self.entities(g,YETI)[0].id));self.assertEqual(self.bank(g),17)
    def test_thalena_existing_extra_power_is_explicitly_unsupported_and_rolls_back(self):
        g=self.game((THALENA,THALENA));self.play(g,THALENA);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'second-slot replacement/refresh')as caught:self.play(g,THALENA)
        self.assertIsInstance(caught.exception.__cause__,UnsupportedDefinitionError)
        self.assertEqual(g.snapshot(),before);self.assertEqual(len(g.state.players[1].hero_power_ids),2)
    def test_unknown_or_duplicate_native_corpse_gain_attachments_rejected(self):
        g=self.game(board=(FALRIC,));saved=g.snapshot();eid=str(self.entities(g,FALRIC)[0].id)
        for wrong in('missing',YETI):
            bad=deepcopy(saved);a=next(x for x in bad['state']['entities'][eid]['abilities']if x['kind']=='corpse_gain');a['corpse_gain_card_id']=wrong
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())
        bad=deepcopy(saved);row=bad['state']['entities'][eid];a=deepcopy(next(x for x in row['abilities']if x['kind']=='corpse_gain'))
        a['id']=bad['state']['next_attachment_id'];bad['state']['next_attachment_id']+=1;row['abilities'].append(a)
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())
    def test_future_resident_target_rejected_in_waiting_frames(self):
        g=self.game((SWARM,),board=('k73.wait',),enemy=(YETI,),corpses=2);self.play(g,SWARM,self.entities(g,YETI,2)[0].id,branch='bites')
        bad=g.snapshot();rows=wires(bad,'DamageResidentSpellTarget');self.assertTrue(rows)
        for row in rows:row['fields']['target']['fields']['presence_id']=10**8
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())
    def test_old292_schema_rejected_and_native_ability_fields_are_strict(self):
        g=self.game();bad=g.snapshot();bad['schema_version']=292
        self.assertGreater(SNAPSHOT_SCHEMA_VERSION,292)
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
        for kwargs in(dict(origin='granted'),dict(consumed=True),dict(behavior_id='unrelated'),dict(spell_damage=1)):
            values=dict(id=1,kind='corpse_gain',source_id=1,origin='printed',corpse_gain_card_id=FALRIC);values.update(kwargs)
            with self.assertRaises(ValueError):AbilityInstance(**values)
    def test_player_views_do_not_expose_gain_profile_or_opponent_hand_identity(self):
        g=self.game((FALRIC,),deck=('CATA_465',));self.play(g,FALRIC)
        own=json.dumps(g.observe(1),ensure_ascii=False);other=json.dumps(g.observe(2),ensure_ascii=False)
        self.assertIn('CATA_465',own);self.assertNotIn('CATA_465',other)
        for key in('corpse_gain_card_id','corpse_spender_records','rng_state','cast_history','resolution_frames'):
            self.assertNotIn(key,own);self.assertNotIn(key,other)


if __name__=='__main__':unittest.main()
