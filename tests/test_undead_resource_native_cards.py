"""Actual native mana, death thresholds, physical tutor and generated spell values."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT, historical_definition_digests
from copy import deepcopy
from dataclasses import asdict,replace
import json,unittest
from pathlib import Path
from hs_sim.cards import build_registry
from hs_sim.cards.undead_resource_native_cards import(BROODMOTHER,AESSINA,RAPTOR,EXPERIMENT,CHILLER,BREATH,BATCH_HASH,load_batch)
from hs_sim.engine import(Attack,CardClass,CardDefinition,CardMetadata,CardType,DeckPolicy,DeckSpec,EndTurn,Game,IllegalAction,MatchSetup,OpeningHook,
    Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import(AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,DestroyBatch,Draw,
    ForceAttack,InvokeBehavior,RequestChoice,Silence,Transform,TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CostSpec,DamageKind
from hs_sim.engine.native_spell_values import SpellBaseDamageProfile,public_value
from hs_sim.engine.physical_draw_groups import DrawGroupReward,DrawGroupSlot
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.turn_start_draws import TurnDrawSuppressionProfile
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.zones import CardReference,CopyCard,ModifyStoredCost,MoveCard
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1];YETI='CORE_CS2_182';PRIMER='TIME_614'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


def registry():
    r=build_registry();r.register_behavior('k77.noop',lambda c:())
    r.register_behavior('k77.opening_chiller',lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(CHILLER),),SummonCause.capture(c)),))
    r.register_card(replace(r.card(YETI),id='k77.opening_source',metadata=replace(r.card(YETI).metadata,deck_identity='k77.opening_source'),
        opening_hooks=(OpeningHook('after_mulligan','k77.opening_chiller'),)))
    for name,cost in(('dr3',3),('dr5',5)):
        r.register_card(CardDefinition('k77.'+name,name,CardType.MINION,cost=cost,attack=2,health=2,deathrattle='k77.noop',metadata=META))
    r.register_card(CardDefinition('k77.fodder','Actual death fixture',CardType.MINION,attack=1,health=1,metadata=META))
    r.register_card(CardDefinition('k77.wall','Surviving defender',CardType.MINION,attack=1,health=30,metadata=META))
    r.register_card(CardDefinition('k77.spellpower','Actual global spell bonus',CardType.MINION,health=9,spell_damage=2,metadata=META))
    def fail(c):raise ResolutionError('K77 deliberate failure')
    r.register_behavior('k77.fail',fail)
    def deck_cost(c,amount):return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(set_to=amount),c.source_id)for i in c.state.players[c.player_id].deck)
    def kill_fodder(c):return(DestroyBatch(tuple(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id=='k77.fodder'),c.source_id),)
    r.register_behavior('k77.kill_fodder',kill_fodder)
    def deaths(c,n):
        work=[];capacity=7-len(c.state.players[c.player_id].board)
        if capacity<1:raise ResolutionError('Death fixture requires a real available board slot')
        while n:
            count=min(n,capacity);n-=count
            request=SummonByCard(c.player_id,(SummonEntryMaterial('k77.fodder'),),SummonCause.capture(c))
            work.extend((request,)*count)
            work.append(InvokeBehavior('k77.kill_fodder',c.source_id,c.player_id))
        return tuple(work)
    scripts={
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'buff':lambda c:(Buff(c.target_id,3,source_id=c.source_id),),
        'zero_attack':lambda c:(Buff(c.target_id,-3,source_id=c.source_id),),
        'draw':lambda c:(Draw(c.player_id,source_id=c.source_id),),
        'give_aessina':lambda c:(AddToHand(c.player_id,AESSINA,c.source_id),),
        'trigger':lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        'trigger2':lambda c:(TriggerDeathrattles(c.target_id,c.source_id,2),),
        'transform':lambda c:(Transform(c.target_id,YETI),),
        'control':lambda c:(ChangeControl(c.target_id,c.player_id),),
        'to3':lambda c:deck_cost(c,3),'to4':lambda c:deck_cost(c,4),
        'deaths19':lambda c:deaths(c,19),'deaths20':lambda c:deaths(c,20),
        'recast':lambda c:(RecastSpell(c.player_id,next(x.id for x in c.state.cast_history if x.card_id==BREATH),c.source_id,
            c.state.players[3-c.player_id].hero_id,'explicit'),),
        'copy_spell':lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,Zone.HAND,mode='current',source_id=c.source_id),),
        'shuffle_spell':lambda c:(MoveCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,Zone.DECK,source_id=c.source_id),),
        'whole':lambda c:(ReplayWholeCards(c.player_id,c.source_id,WholeCardHistoryQuery(c.player_id,c.play.id,kinds=(CardType.SPELL,),
            exclude_play_ids=tuple(p.id for p in c.state.play_history if p.id<c.play.id and p.card_id!=BREATH))),),
    }
    targeted={'kill','silence','buff','zero_attack','trigger','trigger2','transform','control'}
    for name,body in scripts.items():
        r.register_behavior('k77.'+name,body);target=TargetSpec()if name in targeted else TargetSpec(zones=(Zone.HAND,),kinds=(CardType.SPELL,),relation='friendly')if name in('copy_spell','shuffle_spell')else None
        r.register_card(CardDefinition('k77.'+name,name,CardType.SPELL,on_play='k77.'+name,targeting=target,metadata=META))
    def draw_wait(c):
        if c.event.player_id!=c.player_id or c.state.entities[c.event.target_id].card_id not in('k77.dr3','k77.dr5'):return()
        ref=CardReference.capture(c.state.entities[c.event.target_id])
        return(RequestChoice(c.player_id,(ChoiceOption('keep','Continue',()),ChoiceOption('give','Give original away',
            (MoveCard(ref,3-c.player_id,Zone.HAND,source_id=c.source_id),AddToHand(c.player_id,'k77.dr3',c.source_id))),
            ChoiceOption('fail','Fail',(InvokeBehavior('k77.fail',c.source_id,c.player_id),))),c.source_id),)
    def generated(c,mode):
        if c.event.player_id!=c.player_id or c.state.entities[c.event.target_id].card_id!=BREATH:return()
        if mode=='grow':return(Buff(c.event.source_id,1,source_id=c.source_id),)
        return(RequestChoice(c.player_id,(ChoiceOption('keep','Continue',()),ChoiceOption('fail','Fail',
            (InvokeBehavior('k77.fail',c.source_id,c.player_id),))),c.source_id),)
    def start(c):
        if c.event.player_id!=c.player_id:return()
        target=next((i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CHILLER),None)
        if target is None:return()
        return(RequestChoice(c.player_id,(ChoiceOption('keep','Keep suppression',()),ChoiceOption('kill','Remove source',
            (Destroy(target,c.source_id),)),ChoiceOption('fail','Fail',(InvokeBehavior('k77.fail',c.source_id,c.player_id),))),c.source_id),)
    for name,event,body in(('wait_draw','card_drawn',draw_wait),('wait_generated','card_added_to_hand',lambda c:generated(c,'wait')),
        ('grow_generated','card_added_to_hand',lambda c:generated(c,'grow')),('wait_start','turn_started',start)):
        r.register_behavior('k77.'+name,body);r.register_card(CardDefinition('k77.'+name,name,CardType.MINION,health=20,
            triggers=(TriggerSpec(event,'k77.'+name),),metadata=META))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events']);saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')});return saved


class UndeadResourceNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),deck=(YETI,)*8,enemy_deck=(YETI,)*8,mana=40):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=mana,max_mana=mana,mana_cap=40,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=enemy_deck,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=1077),self.r)
    def entities(self,g,cid,p=1,zone='board'):
        s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid]
    def first(self,g,cid,p=1,zone='board'):return self.entities(g,cid,p,zone)[0]
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def play(self,g,cid,target=None,p=1):
        eid=self.first(g,cid,p,'hand').id;g.apply(PlayCard(p,eid,target));return eid
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def qualified(self,hand=(),**kwargs):
        g=self.game((PRIMER,RAPTOR,*hand),board=(CHILLER,*kwargs.pop('board',())),**kwargs)
        self.play(g,PRIMER);self.cycle(g);return g
    def portable(self,g):
        saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,registry()).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
    def choose(self,g,key):q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def price(self,g,cid):return quote_cost(g.state,self.r,self.first(g,cid,zone='hand')).amount
    def generated(self,g):return self.entities(g,BREATH,zone='hand')

    def test_full_source_pins_fixed_spell_and_native_multi_tribes(self):
        data=load_batch();self.assertEqual(canonical_digest(data),BATCH_HASH);self.assertEqual((len(data['cards']),len(data['dependencies'])),(5,1))
        for row in data['cards']+data['dependencies']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(set(self.r.card(BROODMOTHER).metadata.tribes),{'dragon','undead'})
        self.assertEqual(set(self.r.card(EXPERIMENT).metadata.tribes),{'dragon','undead'})
        self.assertEqual(set(self.r.card(RAPTOR).metadata.tribes),{'beast','undead'})
        self.assertEqual((self.r.card(BREATH).cost,self.r.card(BREATH).metadata.collectible),(2,False))
    def test_old1042_complete_definitions_and_unused_default_fingerprint_equal(self):
        old=json.loads((ROOT/'outputs/card-integration-20261014/k77-before/definition-digests.json').read_bytes())
        self.assertEqual(len(old),1042);self.assertEqual(old,historical_definition_digests(self.r,old))
        self.assertEqual(representative().fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)
    def test_native_profiles_are_validated_read_only_and_frozen(self):
        r=build_registry()
        with self.assertRaises(TypeError):r.turn_draw_profiles['bad']=TurnDrawSuppressionProfile(CHILLER)
        with self.assertRaises(ValueError):r.register_turn_draw_profile(TurnDrawSuppressionProfile(CHILLER))
        with self.assertRaises(ValueError):r.register_spell_value_profile(SpellBaseDamageProfile(YETI,EXPERIMENT))
        r.freeze()
        with self.assertRaises(ValueError):r.register_spell_value_profile(SpellBaseDamageProfile(BREATH,EXPERIMENT))
    def test_broodmother_rush_refreshes_attack_amount_before_retaliation(self):
        g=self.game((BROODMOTHER,),enemy=('k77.wall',),mana=10);source=self.play(g,BROODMOTHER)
        self.assertEqual(g.state.players[1].mana,6);g.apply(Attack(1,source,self.first(g,'k77.wall',2).id))
        self.assertEqual((g.state.players[1].mana,g.state.players[1].max_mana),(8,10))
        self.assertEqual(g.state.entities[source].health,4);self.portable(g)
    def test_broodmother_current_buff_attack_refresh_caps_at_available_crystals(self):
        g=self.game((BROODMOTHER,'k77.buff'),enemy=('k77.wall',),mana=10);source=self.play(g,BROODMOTHER);self.play(g,'k77.buff',source)
        g.apply(Attack(1,source,self.first(g,'k77.wall',2).id));self.assertEqual(g.state.players[1].mana,10)
    def test_broodmother_silence_and_other_attacker_do_not_refresh(self):
        g=self.game(('k77.silence',),board=(BROODMOTHER,YETI),enemy=('k77.wall',),mana=5)
        source=self.first(g,BROODMOTHER).id;self.play(g,'k77.silence',source);g.apply(Attack(1,source,self.first(g,'k77.wall',2).id))
        self.assertEqual(g.state.players[1].mana,5)
    def test_aessina_nineteen_friendly_deaths_do_not_fire(self):
        g=self.game(('k77.deaths19',AESSINA));self.play(g,'k77.deaths19');self.assertEqual(len(g.state.death_history),19)
        self.play(g,AESSINA);self.assertEqual(self.hero(g,2).health,30);self.assertFalse(any(e.kind=='random_choice'for e in g.events))
    def test_aessina_twenty_actual_deaths_before_acquisition_fire_twenty_ability_packets(self):
        g=self.game(('k77.deaths20','k77.give_aessina'),board=('k77.spellpower',));self.play(g,'k77.deaths20')
        self.assertEqual(len(g.state.death_history),20);self.play(g,'k77.give_aessina');self.play(g,AESSINA);self.assertEqual(self.hero(g,2).health,10)
        packets=[e for e in g.events if e.kind=='damage_dealt'and e.source_id==self.first(g,AESSINA).id]
        self.assertEqual(len(packets),20);self.assertTrue(all(e.amount==1 for e in packets));self.portable(g)
    def test_aessina_opponent_deaths_do_not_satisfy_friendly_threshold(self):
        g=self.game((AESSINA,),enemy_hand=('k77.deaths20',));g.apply(EndTurn(1));self.play(g,'k77.deaths20',p=2);g.apply(EndTurn(2))
        self.play(g,AESSINA);self.assertEqual(self.hero(g,2).health,30)
    def test_raptor_inactive_kindred_tutors_deathrattle_without_zero_reward(self):
        g=self.game((RAPTOR,),deck=(YETI,'k77.dr3','k77.dr5'));self.play(g,RAPTOR)
        self.assertEqual(self.price(g,'k77.dr3'),3);self.assertFalse(self.entities(g,'k77.dr5',zone='hand'));self.portable(g)
    def test_raptor_active_kindred_zeroes_only_original_single_draw(self):
        g=self.qualified(deck=('k77.dr3',));self.play(g,RAPTOR)
        self.assertEqual(self.price(g,'k77.dr3'),0);self.assertEqual(len(g.state.draw_history),2);self.portable(g)
    def test_raptor_kindred_double_source_repeats_cost_component_without_second_tutor(self):
        g=self.qualified(('TLC_251',),deck=('k77.dr3','k77.dr3'));self.play(g,'TLC_251');self.play(g,RAPTOR)
        self.assertEqual(len(self.entities(g,'k77.dr3',zone='hand')),1);self.assertEqual(self.price(g,'k77.dr3'),0)
        self.assertEqual(g.state.kindred_history[-1].repetitions,2);self.assertEqual(len(g.state.players[1].deck),1);self.portable(g)
    def test_raptor_uses_current_stored_deck_cost_in_both_directions(self):
        g=self.game(('k77.to3',RAPTOR),deck=('k77.dr5',));self.play(g,'k77.to3');self.play(g,RAPTOR);self.assertEqual(self.price(g,'k77.dr5'),3)
        h=self.game(('k77.to4',RAPTOR),deck=('k77.dr3',));self.play(h,'k77.to4');self.play(h,RAPTOR);self.assertFalse(self.entities(h,'k77.dr3',zone='hand'))
    def test_raptor_empty_match_does_not_draw_vanilla_or_fatigue(self):
        for deck in((),(YETI,)):
            g=self.game((RAPTOR,),deck=deck);self.play(g,RAPTOR);self.assertEqual(self.hero(g).health,30)
            self.assertFalse(g.state.draw_history)
    def test_raptor_waiting_original_reward_restores_and_failed_resume_rolls_back(self):
        g=self.qualified(board=('k77.wait_draw',),deck=('k77.dr3',));self.play(g,RAPTOR);self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'keep');self.assertEqual(self.price(g,'k77.dr3'),0);self.portable(g)
    def test_raptor_departed_original_does_not_reward_same_name_replacement(self):
        g=self.qualified(board=('k77.wait_draw',),deck=('k77.dr3',));self.play(g,RAPTOR);self.choose(g,'give')
        self.assertEqual(self.price(g,'k77.dr3'),3);self.assertEqual(self.first(g,'k77.dr3',2,'hand').base_cost,3);self.portable(g)
    def test_draw_slot_current_bounds_and_zero_set_reward_argument_validation(self):
        self.assertEqual(DrawGroupReward('set_cost_all',0,2).repetitions,2)
        for kwargs in({'max_current_cost':True},{'current_deathrattle':1},{'query':PoolQuery(kinds=(CardType.SPELL,)),'current_deathrattle':True}):
            with self.assertRaises(ValueError):DrawGroupSlot(**kwargs)
    def test_experiment_natural_death_generates_native_attack_damage_not_one(self):
        g=self.game(('k77.kill',),board=(EXPERIMENT,));self.play(g,'k77.kill',self.first(g,EXPERIMENT).id)
        self.assertEqual(public_value(self.generated(g)[0]),3);self.play(g,BREATH,self.hero(g,2).id)
        self.assertEqual(self.hero(g,2).health,27);self.assertEqual(g.state.cast_history[-1].native_spell_value.spell_base_value.amount,3);self.portable(g)
    def test_experiment_buff_uses_frozen_death_attack_after_zone_reset(self):
        g=self.game(('k77.buff','k77.kill'),board=(EXPERIMENT,));source=self.first(g,EXPERIMENT).id;self.play(g,'k77.buff',source);self.play(g,'k77.kill',source)
        self.assertEqual(public_value(self.generated(g)[0]),6);self.assertEqual(g.state.deathrattle_history[-1].source_attack,6)
        self.play(g,BREATH,self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,24)
    def test_experiment_live_deathrattle_trigger_has_real_value_without_death_record(self):
        g=self.game(('k77.trigger','k77.buff'),board=(EXPERIMENT,));source=self.first(g,EXPERIMENT).id;self.play(g,'k77.trigger',source)
        self.assertFalse(g.state.death_history);self.play(g,'k77.buff',source);self.assertEqual(public_value(self.generated(g)[0]),3)
        self.play(g,BREATH,self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,27);self.portable(g)
    def test_experiment_repeated_live_body_captures_each_actual_execution_attack(self):
        g=self.game(('k77.trigger2',),board=(EXPERIMENT,'k77.grow_generated'));self.play(g,'k77.trigger2',self.first(g,EXPERIMENT).id)
        self.assertEqual([public_value(e)for e in self.generated(g)],[3,4])
        self.assertEqual([r.source_attack for r in g.state.deathrattle_history],[3,4]);self.portable(g)
    def test_experiment_zero_is_bound_value_and_spell_power_is_separate(self):
        g=self.game(('k77.zero_attack','k77.kill'),board=(EXPERIMENT,'k77.spellpower'));source=self.first(g,EXPERIMENT).id
        self.play(g,'k77.zero_attack',source);self.play(g,'k77.kill',source);self.assertEqual(public_value(self.generated(g)[0]),0)
        self.play(g,BREATH,self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,28);self.portable(g)
    def test_experiment_generated_value_is_installed_before_notification_waiting(self):
        g=self.game(('k77.kill',),board=(EXPERIMENT,'k77.wait_generated'));self.play(g,'k77.kill',self.first(g,EXPERIMENT).id)
        self.assertEqual(public_value(self.generated(g)[0]),3);self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        self.choose(g,'keep');self.portable(g)
    def test_native_value_current_copy_and_history_recast_preserve_original_base(self):
        g=self.game(('k77.trigger','k77.copy_spell','k77.recast'),board=(EXPERIMENT,));self.play(g,'k77.trigger',self.first(g,EXPERIMENT).id)
        self.play(g,'k77.copy_spell',self.generated(g)[0].id);values=[a.id for e in self.generated(g)for a in e.abilities if a.kind=='spell_base_value']
        self.assertEqual(len(set(values)),2)
        for _ in range(2):self.play(g,BREATH,self.hero(g,2).id)
        self.play(g,'k77.recast');self.assertEqual(self.hero(g,2).health,21);self.portable(g)
    def test_native_value_shuffle_and_normal_draw_preserve_same_physical_payload(self):
        g=self.game(('k77.trigger','k77.shuffle_spell','k77.draw'),board=(EXPERIMENT,),deck=());self.play(g,'k77.trigger',self.first(g,EXPERIMENT).id)
        source=self.generated(g)[0].id;self.play(g,'k77.shuffle_spell',source);self.play(g,'k77.draw')
        self.assertEqual((self.generated(g)[0].id,public_value(self.generated(g)[0])),(source,3));self.portable(g)
    def test_native_value_countered_spell_has_no_payload_claim_and_rolls_back_unbound(self):
        counter=self.game(('k77.trigger',),board=(EXPERIMENT,),enemy_hand=('CORE_EX1_287',))
        self.play(counter,'k77.trigger',self.first(counter,EXPERIMENT).id);counter.apply(EndTurn(1))
        self.play(counter,'CORE_EX1_287',p=2);counter.apply(EndTurn(2));self.play(counter,BREATH,self.hero(counter,2).id)
        self.assertEqual(self.hero(counter,2).health,30);self.assertIsNone(counter.state.cast_history[-1].native_spell_value)
        self.assertFalse(counter.state.cast_history[-1].payload_started);self.portable(counter)
        g=self.game((BREATH,));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,BREATH,self.hero(g,2).id)
        self.assertEqual(g.snapshot(),saved)
        listing=g.for_player(1).legal_actions();self.assertIsNone(listing['actions'])
    def test_native_value_whole_card_history_keeps_original_and_countered_parameters(self):
        for countered in(False,True):
            g=self.game(('k77.trigger','k77.whole'),board=(EXPERIMENT,),enemy_hand=('CORE_EX1_287',)if countered else())
            self.play(g,'k77.trigger',self.first(g,EXPERIMENT).id)
            if countered:
                g.apply(EndTurn(1));self.play(g,'CORE_EX1_287',p=2);g.apply(EndTurn(2))
            self.play(g,BREATH,self.hero(g,2).id);self.play(g,'k77.whole')
            row=g.state.cast_history[-1];self.assertEqual(row.card_id,BREATH)
            self.assertEqual(row.native_spell_value.spell_base_value.amount,3);self.portable(g)
    def test_native_value_player_only_visible_amount_without_private_proof(self):
        g=self.game(('k77.trigger',),board=(EXPERIMENT,));self.play(g,'k77.trigger',self.first(g,EXPERIMENT).id)
        own=g.observe(1);enemy=g.observe(2);card=next(x for x in own['players'][0]['hand']if x['card_id']==BREATH)
        self.assertEqual(card['base_damage'],3);self.assertTrue(all('base_damage'not in x for x in enemy['players'][0]['hand']))
        for view in(own,enemy):
            text=json.dumps(view)
            for name in('spell_base_value','deathrattle_id','source_attack','native_spell_value','rng_state'):
                self.assertNotIn(name,text)
    def test_native_value_rehashed_amount_and_missing_cast_claim_are_rejected(self):
        g=self.game(('k77.trigger',),board=(EXPERIMENT,));self.play(g,'k77.trigger',self.first(g,EXPERIMENT).id);self.play(g,BREATH,self.hero(g,2).id)
        saved=g.snapshot();bad=deepcopy(saved);bad['state']['cast_history'][-1]['native_spell_value']=None
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())
        bad=deepcopy(saved);bad['state']['cast_history'][-1]['native_spell_value']['spell_base_value']['amount']=4
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())
    def test_chiller_skips_only_own_normal_start_draw(self):
        g=self.game(board=(CHILLER,));self.cycle(g)
        self.assertEqual(len(g.state.players[1].deck),8);self.assertFalse(g.state.players[1].hand)
        self.assertEqual(len(g.state.players[2].deck),7);self.assertEqual(len(g.state.draw_history),1);self.portable(g)
    def test_chiller_first_normal_draw_uses_same_source_policy_after_full_opening(self):
        for first in(1,2):
            decks=(DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,('k77.opening_source',)+(YETI,)*29),DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,(YETI,)*30))
            policy=DeckPolicy('k77-opening','k77-fixture','experimental',tuple(self.r.cards),max_copies=30)
            g=Game.from_decks(MatchSetup(decks,policy,'GAME_005',1077,first),self.r)
            while g.state.pending_choice is not None:
                q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
            self.assertEqual(g.state.opening.stage,'complete');self.assertTrue(self.entities(g,CHILLER))
            self.assertEqual([len(g.state.players[p].hand)for p in(1,2)],[3,5]if first==1 else[5,4])
            self.assertEqual(len(g.state.draw_history),0 if first==1 else 1);self.portable(g)
    def test_chiller_does_not_suppress_explicit_draw_or_create_empty_deck_fatigue(self):
        g=self.game(('k77.draw',),board=(CHILLER,),deck=(YETI,));self.play(g,'k77.draw');self.assertEqual(len(self.entities(g,YETI,zone='hand')),1)
        self.cycle(g);self.assertEqual(self.hero(g).health,30)
        h=self.game(('k77.draw',),board=(CHILLER,),deck=());self.play(h,'k77.draw');self.assertEqual(self.hero(h).health,29)
    def test_chiller_silence_death_and_transform_remove_source(self):
        for spell in('k77.silence','k77.kill','k77.transform'):
            g=self.game((spell,),board=(CHILLER,));self.play(g,spell,self.first(g,CHILLER).id);self.cycle(g)
            self.assertEqual(len(g.state.players[1].hand),1);self.assertEqual(len(g.state.players[1].deck),7)
    def test_chiller_control_change_applies_to_current_controller(self):
        g=self.game(board=(CHILLER,),enemy_hand=('k77.control',));g.apply(EndTurn(1));source=self.first(g,CHILLER).id
        self.play(g,'k77.control',source,p=2);g.apply(EndTurn(2));self.assertEqual(len(g.state.players[1].deck),7)
        g.apply(EndTurn(1));self.assertEqual(len(g.state.players[2].deck),7);self.portable(g)
    def test_chiller_waiting_start_source_rechecks_after_choice_and_restores(self):
        for key,draws in(('keep',0),('kill',1)):
            g=self.game(board=(CHILLER,'k77.wait_start'));self.cycle(g);self.assertIsNotNone(g.state.pending_choice);self.portable(g)
            saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.choose(g,'fail')
            self.assertEqual(g.snapshot(),saved);self.choose(g,key);self.assertEqual(len(g.state.players[1].hand),draws);self.portable(g)
    def test_old_schema_and_native_typed_record_fields_are_strict(self):
        old=json.loads((ROOT/'outputs/card-integration-20261014/k77-before/constructed-v85-core370-schema295.json').read_bytes())
        with self.assertRaises(SnapshotError):Game.from_snapshot(old,build_registry())
        g=self.game(('k77.trigger',),board=(EXPERIMENT,));self.play(g,'k77.trigger',self.first(g,EXPERIMENT).id)
        bad=g.snapshot();bad['state']['deathrattle_history'][0]['source_attack']=True
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())


if __name__=='__main__':unittest.main()
