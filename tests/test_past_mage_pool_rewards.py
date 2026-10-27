"""Actual pool consumers use explicit complete diagnostic domains, not cropped production pools."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import past_mage_pool_rewards as native
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, ResolutionError, Scenario, TriggerSpec)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, DestroyBatch, GainArmor, InvokeBehavior, RequestChoice, Summon)
from hs_sim.engine.model import CardMetadata, CostSpec, Rarity, SpellSchool, TargetSpec, Zone
from hs_sim.engine.pools import (FillHandFromPool, GenerateFromPool, GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery)
from hs_sim.engine.zones import AddToDeck, CardReference, DestroyDeckBatch
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

SYNTH, CRASH, NOVA, PORTAL, APEX, VOLLEY, MAGIC, CHAOS, SECRET, EVOKE, SCORCH, TORCH, COLD, SNOW, COMPANION = native.LEAVES
P='k603.'
EL1,EL2,EL3,FIVE,SIX,TEN,NAGA,OTHER,BIG,POWER,NOOP,DOOM,WAIT,FAIL,ADD_MINION,REMOVE_MINION,ADD_BOTTOM=(
    P+x for x in('el1','el2','el3','five','six','ten','naga','other','big','power','noop','doom','wait','fail','add_minion','remove_minion','add_bottom'))
SPELLS={s:P+s.value for s in SpellSchool}
FIRE,FROST=SPELLS[SpellSchool.FIRE],SPELLS[SpellSchool.FROST]
UNTYPED=P+'untyped'
NAGA_WAIT=P+'naga_wait'
META=CardMetadata(True,(CardClass.PALADIN,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


def context(mode='normal'):return GenerationContext('k603-explicit-diagnostic-'+mode,'experimental')


def registry(mode='normal',role='writer'):return _registry(mode,role)


@lru_cache(None)
def _registry(mode,role):
    r=build_registry()
    def fail(c):raise ResolutionError('K603 deliberate saved branch failure')
    r.register_behavior(FAIL,fail)
    r.register_behavior(P+'armor',lambda c:(GainArmor(c.player_id,1),))
    r.register_behavior(NOOP,lambda c:())
    r.register_behavior(DOOM,lambda c:(DestroyBatch(tuple(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id=='REV_845'),c.source_id),))
    for cid,body in((NOOP,NOOP),(DOOM,DOOM)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=body))
    for school,cid in SPELLS.items():r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=4,spell_school=school,on_play=P+'armor',metadata=META))
    r.register_card(CardDefinition(UNTYPED,UNTYPED,CardType.SPELL,cost=2,on_play=P+'armor',metadata=META))
    for cid,cost,tribes,power in((EL1,1,('elemental',),0),(EL2,2,('elemental',),0),(EL3,3,('elemental',),0),
            (FIVE,5,(),0),(SIX,6,('elemental',),0),(TEN,10,(),0),(NAGA,3,('naga',),0),
            (OTHER,2,(),0),(BIG,1,(),0),(POWER,1,(),2)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=50 if cid==BIG else 4,
            spell_damage=power,metadata=replace(META,tribes=tribes)))
    def watch(c):
        event=c.event;source=c.state.entities.get(event.source_id);cid=c.source.card_id
        if cid==WAIT and event.kind=='card_added_to_hand' and source is not None and source.card_id==NOVA:
            count=sum(c.state.entities[i].card_id==FIRE for i in c.state.players[c.player_id].hand)
            if count==1:return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                ChoiceOption('extra','Add frost',(AddToHand(c.player_id,FROST,c.source_id),)),
                ChoiceOption('fault','Fail',(InvokeBehavior(FAIL,c.source_id,c.player_id),))),c.source_id),)
        if event.kind=='damage_dealt' and source is not None and source.card_id==APEX:
            if cid==ADD_MINION:return(AddToDeck(c.player_id,EL1,'bottom',c.source_id),)
            if cid==REMOVE_MINION:
                refs=tuple(CardReference.capture(c.state.entities[i])for i in c.state.players[c.player_id].deck if c.state.entities[i].kind==CardType.MINION)
                return(DestroyDeckBatch(refs,c.source_id),)
        if cid==ADD_BOTTOM and event.kind=='minion_summoned' and source is not None and source.card_id==SIX:
            return(AddToDeck(c.player_id,FIRE,'bottom',c.source_id),)
        if cid==NAGA_WAIT and event.kind=='minion_summoned' and source is not None and source.card_id==NAGA:
            if sum(c.state.entities[i].card_id==NAGA for i in c.state.players[c.player_id].board)==1:
                return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                    ChoiceOption('extra','Occupy another slot',(Summon(c.player_id,OTHER),)),
                    ChoiceOption('fault','Fail',(InvokeBehavior(FAIL,c.source_id,c.player_id),))),c.source_id),)
        return()
    r.register_behavior(P+'watch',watch)
    for cid in(WAIT,ADD_MINION,REMOVE_MINION,ADD_BOTTOM,NAGA_WAIT):r.register_card(CardDefinition(cid,cid,CardType.MINION,health=20,
        triggers=tuple(TriggerSpec(event,P+'watch')for event in('card_added_to_hand','damage_dealt','minion_summoned'))))
    secrets=sorted(c.id for c in r.cards.values()if c.kind==CardType.SPELL and c.secret is not None and c.metadata is not None and CardClass.MAGE in c.metadata.classes)[:2]
    assert len(secrets)==2
    ids=[EL1,EL2,EL3,FIVE,SIX,TEN,NAGA,OTHER,BIG,POWER,*SPELLS.values(),UNTYPED,*secrets]
    for cid in ids:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if mode=='unknown':
        for cid,kind,cost,meta,school in((P+'unknown_elemental',CardType.MINION,1,replace(META,tribes=('elemental',)),None),
                (P+'unknown_fire',CardType.SPELL,4,META,SpellSchool.FIRE)):
            r.register_pool_card(PoolCard(cid,kind,cost,meta,school));ids.append(cid)
    r.register_pool(PoolDefinition(native.POOL,P+'complete-v1',context(mode).target_id,'experimental',tuple(PoolMember(cid)for cid in ids),complete=True))
    r.validate();return r


class PastMagePoolRewardTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'

    def game(self,hand=(),*,deck=(NOOP,)*4,enemy_deck=(NOOP,)*4,board=(),enemy_board=(),enemy_hand=(),player=1,mode='normal'):
        self.mode=mode
        setups=tuple(PlayerSetup('HERO_08',hand=hand if p==player else enemy_hand,deck=deck if p==player else enemy_deck,
            board=board if p==player else enemy_board,mana=30,max_mana=30,mana_cap=30)for p in(1,2))
        return Game.from_scenario(Scenario(setups,active_player=player,seed=603,generation_context=context(mode)),registry(mode))

    def paid(self,g,cid,target=None,player=1):
        entity=self.entity(g,cid,player);amount=quote_cost(g.state,g.registry,entity).amount;mana=g.state.players[player].mana
        source=self.play(g,cid,target,player);self.assertEqual(g.state.players[player].mana,mana-amount)
        self.assertEqual((g.state.play_history[-1].card_id,g.state.play_history[-1].cost),(cid,amount));return source

    def hero(self,g,p):return g.state.entities[g.state.players[p].hero_id]

    def test_twenty_six_full_records_fifty_two_primary_faces_and_real_collection_roles(self):
        data=native.load_batch();rows={r['record']['id']:r for r in(*data['dependencies'],*data['existing_dependencies'])}
        self.assertEqual((len(rows),len(data['official_observations'])),(26,52))
        for obs in data['official_observations']:batch.check_face(rows[obs['card_id']]['record'],obs['face'],obs['locale'],numeric_normalizations=data['numeric_normalizations'].get(obs['card_id']))
        self.assertTrue(registry().card('REV_845').metadata.collectible)
        self.assertTrue(all(not registry().card(cid).metadata.collectible for cid in native.TOKENS))
        self.assertEqual((registry().card(EVOKE).cost,native.COLLECTIBLE_ROOTS),(0,()))

    def test_synthesize_generates_original_one_two_three_cost_elementals_across_classes_both_seats(self):
        for player in(1,2):
            g=self.game((SYNTH,),player=player);source=self.paid(g,SYNTH,player=player)
            generated=[g.state.entities[i]for i in g.state.players[player].hand]
            self.assertEqual([g.registry.card(x.card_id).cost for x in generated],[1,2,3])
            self.assertTrue(all('elemental'in g.registry.card(x.card_id).metadata.tribes for x in generated))
            created={e.target_id for e in g.events if e.kind=='card_created' and e.source_id==source}
            self.assertEqual({x.id for x in generated},created)
            self.assertTrue(all(g.registry.card(x.card_id).metadata.classes==(CardClass.PALADIN,)for x in generated))

    def test_crash_fills_only_original_remaining_capacity_with_naga_and_full_board_has_no_rng(self):
        g=self.game((CRASH,),board=(OTHER,)*5);self.paid(g,CRASH)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board[-2:]],[NAGA,NAGA]);self.assertEqual(len(g.state.players[1].board),7)
        g=self.game((CRASH,),board=(OTHER,)*7);rng=g.snapshot()['rng_state'];self.paid(g,CRASH)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(len(g.state.players[1].board),7)

    def test_supernova_fills_foreign_fire_spells_at_permanent_one_cost_and_real_play_uses_it(self):
        g=self.game((NOVA,));source=self.paid(g,NOVA)
        self.assertEqual(len(g.state.players[1].hand),10)
        self.assertTrue(all(g.state.entities[i].card_id==FIRE for i in g.state.players[1].hand))
        self.assertTrue(all(quote_cost(g.state,g.registry,g.state.entities[i]).amount==1 for i in g.state.players[1].hand))
        self.paid(g,FIRE);self.assertEqual(self.hero(g,1).armor,1)
        created={e.target_id for e in g.events if e.kind=='card_created' and e.source_id==source}
        self.assertTrue(set(g.state.players[1].hand)<=created)

    def test_spell_fill_wait_preserves_actual_cast_cause_original_capacity_and_selected_count(self):
        g=self.game((CRASH,),board=(NAGA_WAIT,));source=self.paid(g,CRASH);self.assertIsNotNone(g.state.pending_choice)
        root=g.state.pool_summon_history[-1]
        self.assertEqual((root.spec.count,len(root.selected)),(6,6))
        self.assertEqual((root.spec.cause.origin,root.spec.cause.source.entity_id,root.spec.cause.cast_id),('spell_cast',source,g.state.cast_history[-1].id))
        other=self.portable(g);before=other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),before);self.choose(other,'extra')
        self.assertEqual(len(other.state.players[1].board),7)
        self.assertEqual(sum(other.state.entities[i].card_id==NAGA for i in other.state.players[1].board),5)
        self.assertEqual((other.state.pool_summon_history[-1].spec.count,len(other.state.pool_summon_history[-1].selected)),(6,6))

    def test_supernova_wait_restores_original_count_and_cost_with_failure_rollback_and_late_burn(self):
        g=self.game((NOVA,),board=(WAIT,));source=self.paid(g,NOVA);self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g);before=other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),before);self.choose(other,'extra')
        hand=[other.state.entities[i]for i in other.state.players[1].hand]
        self.assertEqual((len(hand),sum(e.card_id==FIRE for e in hand)),(10,9))
        burned=[e for e in other.state.entities.values()if e.card_id==FIRE and e.zone==Zone.GRAVEYARD]
        self.assertEqual(len(burned),1)
        self.assertTrue(any(e.kind=='card_burned' and e.source_id==source and e.target_id==burned[0].id for e in other.events))
        self.assertTrue(all(quote_cost(other.state,other.registry,e).amount==1 for e in hand if e.card_id==FIRE))

    def test_portal_apex_and_volley_use_real_printed_five_six_ten_domains_and_spell_damage(self):
        for cid,damage,body in((PORTAL,8,SIX),(APEX,7,FIVE),(VOLLEY,12,TEN)):
            g=self.game((cid,),board=(POWER,));self.paid(g,cid,None if cid==VOLLEY else g.state.players[2].hero_id)
            self.assertEqual(self.hero(g,2).health,30-damage)
            self.assertEqual(g.state.entities[g.state.players[1].board[-1]].card_id,body)
        self.portable(g)

    def test_apex_freezes_initial_deck_condition_before_damage_changes_deck(self):
        g=self.game((APEX,),board=(ADD_MINION,));self.paid(g,APEX,g.state.players[2].hero_id)
        self.assertTrue(any(g.state.entities[i].card_id==FIVE for i in g.state.players[1].board))
        self.assertTrue(any(g.state.entities[i].kind==CardType.MINION for i in g.state.players[1].deck))
        g=self.game((APEX,),deck=(EL1,NOOP),board=(REMOVE_MINION,));self.paid(g,APEX,g.state.players[2].hero_id)
        self.assertFalse(any(g.state.entities[i].card_id==FIVE for i in g.state.players[1].board))
        self.assertFalse(any(g.state.entities[i].kind==CardType.MINION for i in g.state.players[1].deck))

    def test_chaos_reads_current_bottom_six_only_after_real_summon_reaction(self):
        g=self.game((CHAOS,),deck=(NOOP,)*8,board=(ADD_BOTTOM,));original=tuple(g.state.players[1].deck)
        self.paid(g,CHAOS,g.state.players[2].hero_id)
        self.assertEqual(self.hero(g,2).health,24);self.assertEqual(g.state.players[1].deck,list(original[:3]))
        self.assertTrue(any(g.state.entities[i].card_id==SIX for i in g.state.players[1].board))
        self.assertTrue(any(g.state.entities[i].card_id==FIRE for i in g.state.players[1].graveyard));self.portable(g)

    def test_chaos_still_destroys_deck_when_board_is_full_without_summon_rng(self):
        g=self.game((CHAOS,),deck=(NOOP,)*8,board=(OTHER,)*7);original=tuple(g.state.players[1].deck);rng=g.snapshot()['rng_state']
        self.paid(g,CHAOS,g.state.players[2].hero_id);self.assertEqual(g.state.players[1].deck,list(original[:2]))
        self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_magic_discovery_excludes_successful_own_used_schools_and_has_real_choice(self):
        g=self.game((FIRE,MAGIC));self.paid(g,FIRE);self.paid(g,MAGIC)
        choice=g.state.pending_choice;self.assertIsNotNone(choice)
        self.assertTrue(all(g.registry.card(o.card_id).spell_school not in(None,SpellSchool.FIRE)for o in choice.options))
        other=self.portable(g);self.choose(other,choice.options[0].id)
        self.assertEqual(len(other.state.players[1].hand),1)

    def test_magic_all_schools_used_does_not_fall_back_to_unfiltered_pool_or_rng(self):
        g=self.game((*SPELLS.values(),MAGIC))
        for cid in SPELLS.values():self.paid(g,cid)
        rng=g.snapshot()['rng_state'];self.paid(g,MAGIC)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_secret_discovery_uses_current_mage_pool_and_delivers_permanent_one_cost(self):
        g=self.game((SECRET,));self.paid(g,SECRET);choice=g.state.pending_choice
        self.assertIsNotNone(choice);self.assertTrue(all(g.registry.card(o.card_id).secret is not None for o in choice.options))
        selected=choice.options[0].card_id;self.choose(g,choice.options[0].id)
        self.assertEqual(quote_cost(g.state,g.registry,self.entity(g,selected)).amount,1);self.paid(g,selected)
        self.assertEqual(len(g.state.players[1].secrets),1)

    def test_evocation_only_consumes_on_next_actual_elemental_and_expires_this_turn(self):
        g=self.game((EVOKE,OTHER,EL2,EL3));self.paid(g,EVOKE)
        self.assertEqual(quote_cost(g.state,g.registry,self.entity(g,EL2)).amount,0)
        g.for_player(1).legal_actions();self.paid(g,OTHER);self.assertEqual(quote_cost(g.state,g.registry,self.entity(g,EL2)).amount,0)
        self.paid(g,EL2);self.assertEqual(g.state.play_history[-1].cost,0);self.paid(g,EL3);self.assertEqual(g.state.play_history[-1].cost,3)
        g=self.game((EVOKE,EL3));self.paid(g,EVOKE);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(quote_cost(g.state,g.registry,self.entity(g,EL3)).amount,3)

    def test_scorch_previous_owner_turn_elemental_price_is_real_and_summon_does_not_count_as_play(self):
        for cid,price in((EL1,1),(PORTAL,4)):
            g=self.game((cid,SCORCH),enemy_board=(BIG,));target=g.state.players[2].board[0]
            self.paid(g,cid,target if cid==PORTAL else None);g.apply(EndTurn(1));g.apply(EndTurn(2))
            self.assertEqual(quote_cost(g.state,g.registry,self.entity(g,SCORCH)).amount,price)
            self.paid(g,SCORCH,target);self.assertEqual(g.state.play_history[-1].cost,price)
        self.portable(g)

    def test_torch_shuffles_original_real_roaring_face_then_draws_and_executes_six_damage(self):
        g=self.game((TORCH,),deck=());self.paid(g,TORCH,g.state.players[2].hero_id)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],['LOE_002t'])
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.paid(g,'LOE_002t',g.state.players[2].hero_id)
        self.assertEqual(self.hero(g,2).health,21)

    def test_cold_case_real_skeletons_gain_armor_and_actual_deathrattles_ignore_spell_damage(self):
        g=self.game((COLD,DOOM),board=(POWER,));self.paid(g,COLD)
        self.assertEqual(self.hero(g,1).armor,4)
        skeletons=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id=='REV_845'];self.assertEqual(len(skeletons),2)
        self.assertEqual([(x.attack,x.health)for x in skeletons],[(2,2),(2,2)])
        self.play(g,DOOM);self.assertEqual(self.hero(g,2).health,26);self.assertEqual(len(g.state.death_history),2)

    def test_real_snowman_chain_three_six_nine_preserves_original_freezing_attack_behavior(self):
        g=self.game((SNOW,));self.paid(g,SNOW);self.paid(g,'AV_282t2');self.paid(g,'AV_282t4')
        bodies=tuple(g.state.players[1].board);self.assertEqual([g.state.entities[i].card_id for i in bodies],['AV_282t','AV_282t3','AV_282t5'])
        self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].health)for i in bodies],[(3,3),(6,6),(9,9)])
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        for i in bodies:g.apply(Attack(1,i,g.state.players[2].hero_id));self.assertTrue(self.hero(g,2).frozen)
        self.assertEqual(self.hero(g,2).health,12);self.portable(g)

    def test_elemental_companion_complete_three_candidates_and_each_real_native_body(self):
        g=self.game((COMPANION,));self.paid(g,COMPANION);chosen=g.state.entities[g.state.players[1].board[0]].card_id
        self.assertIn(chosen,('DEEP_002t','DEEP_002t2','DEEP_002t3'))
        for cid,price in(('DEEP_002t',3),('DEEP_002t2',4),('DEEP_002t3',4)):
            g=self.game((FIRE,),board=(cid,));self.assertEqual(quote_cost(g.state,g.registry,self.entity(g,FIRE)).amount,price)
            if cid=='DEEP_002t2':self.assertEqual(g.registry.card(cid).spell_damage,2)
            if cid=='DEEP_002t3':self.assertIn(Keyword.ELUSIVE,g.state.entities[g.state.players[1].board[0]].keywords)

    def test_unknown_eligible_members_reject_atomic_without_cropping_but_real_tribe_filter_excludes_them(self):
        for cid in(SYNTH,NOVA):
            g=self.game((cid,),mode='unknown');before=g.snapshot()
            with self.assertRaises((ResolutionError,ValueError)):self.play(g,cid)
            self.assertEqual(g.snapshot(),before)
        g=self.game((CRASH,),mode='unknown');self.paid(g,CRASH)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[NAGA]*7)

    def test_fixed_one_fire_fill_is_finite_and_does_not_accept_other_school_or_cost_shapes(self):
        request=GenerateFromPool(1,native.POOL,native.FIRE_SPELLS,source_id=1,cost=CostSpec(set_to=1))
        FillHandFromPool(request).__post_init__()
        for bad in(replace(request,query=PoolQuery(kinds=(CardType.SPELL,),collectible=True,spell_schools=(SpellSchool.FROST,))),
                replace(request,cost=CostSpec(set_to=2)),replace(request,expires_turn=1)):
            with self.assertRaises(ValueError):FillHandFromPool(bad)

    def test_last_bad_collector_dependency_does_not_leave_partial_registration(self):
        original=native.register_past_mage_pool_rewards
        prefix=batch.registration_prefix(build_registry,'hs_sim.cards.past_mage_pool_rewards.register_past_mage_pool_rewards',original)
        data=deepcopy(native.load_batch());data['dependencies'][-1]['record']['type']='SPELL';before=prefix.fingerprint()
        with patch.object(native,'load_batch',return_value=data),self.assertRaises(TargetValidationError):original(prefix)
        self.assertEqual(prefix.fingerprint(),before)
