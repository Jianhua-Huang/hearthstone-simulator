"""Real fixed reward effects and minimal original physical/weapon capabilities."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json,unittest
from random import Random
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from test_past_linked_discovery_summons import fixture as linked_fixture
from hs_sim.cards import past_fixed_rewards_turns as native
from hs_sim.engine import Attack,EndTurn,Game,PlayerSetup,Scenario
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,Damage,Destroy,Draw,GainArmor,
    InvokeBehavior,ModifyWeapon,RandomDamage,RequestChoice)
from hs_sim.engine.equipment import EquipWeaponCopy
from hs_sim.engine.errors import ResolutionError,SnapshotError
from hs_sim.engine.model import (CardDefinition,CardType,CostSpec,DamageKind,EquippedWeaponReference,
    Keyword,LimitedTriggerSpec,Rarity,TargetSpec,Zone)
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference,ModifyStoredCost

XARIL,KING,ARFUS,MEDIVH,OAKHEART,ALANNA,TEMPORUS,TOGWAGGLE,ELISE,RIN=native.ROOTS
FROSTMOURNE,ATIESH,DRAGON,RANSOM,MAP,MONKEY,AZARI=native.FROSTMOURNE,native.ATIESH,native.DRAGON,native.RANSOM,native.MAP,native.MONKEY,native.AZARI
P='k734.'
A,B1,B2,B3,L,VICTIM,SPAWNER=(P+x for x in('a','b1','b2','b3','legend','victim','spawner'))
ZERO,KILL,DRAW,WEAR,LAST,COPY_WEAPON,BUFF,STORED_BUFF,DISCOUNT,PRICE5,AUTO,FILL=(P+x for x in
    ('zero','kill','draw','wear','last','copy_weapon','buff','stored_buff','discount','price5','auto','fill'))
WATCH_DEATH,WATCH_SUMMON,WATCH_SWAP,WATCH_TURN,FAIL=(P+x for x in('watch_death','watch_summon','watch_swap','watch_turn','fail'))
CTX=GenerationContext(P+'controlled-original-pool','experimental')


def fixture(role='writer',mode='small'):
    return cached_fixture(role,mode)


@lru_cache(None)
def cached_fixture(role,mode):
    r,host_context=linked_fixture(P+role,'host'if mode=='host'else'small')
    if mode!='host':native.register_past_fixed_rewards_turns(r)
    plain=metadata(collectible=False,tribes=())
    r.register_behavior(P+'cry',lambda c:(GainArmor(c.player_id,99),))
    r.register_behavior(P+'spawn',lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(A),),SummonCause.capture(c)),))
    for cid,cost,atk,hp,extra in((A,3,2,12,{}),(B1,1,1,8,{}),(B2,2,2,8,{}),(B3,3,3,8,{}),
            (L,4,4,4,dict(battlecry=P+'cry')),(VICTIM,2,0,4,dict(battlecry=P+'cry')),
            (SPAWNER,2,0,2,dict(deathrattle=P+'spawn'))):
        card=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=atk,health=hp,
            metadata=metadata(rarity=Rarity.LEGENDARY if cid==L else Rarity.COMMON,tribes=()),**extra)
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    def weapon(c):return c.state.entities[c.state.players[c.player_id].weapon_id]
    def copy_weapon(c):return(EquipWeaponCopy(c.player_id,CapturedCardCopyMaterial.capture(c.state,weapon(c)),c.source_id),)
    def stored_buff(c):
        from hs_sim.engine.cross_zone import BuffStoredCard
        return(BuffStoredCard(CardReference.capture(c.state.entities[c.target_id]),2,3,c.source_id),)
    bodies={ZERO:lambda c:(),PRICE5:lambda c:(),KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),
        WEAR:lambda c:(ModifyWeapon(EquippedWeaponReference.capture(weapon(c)),durability=-99,source_id=c.source_id),),
        LAST:lambda c:(ModifyWeapon(EquippedWeaponReference.capture(weapon(c)),durability=-2,source_id=c.source_id),),
        COPY_WEAPON:copy_weapon,BUFF:lambda c:(Buff(c.target_id,2,3,c.source_id),),STORED_BUFF:stored_buff,
        DISCOUNT:lambda c:(ModifyStoredCost(CardReference.capture(c.state.entities[c.target_id]),CostSpec(delta=-4),c.source_id),),
        AUTO:lambda c:(CastSpell(c.player_id,PRICE5,c.source_id),),
        FILL:lambda c:tuple(AddToHand(c.player_id,ZERO,c.source_id)for _ in range(10))}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        targets=TargetSpec(zones=(Zone.HAND,Zone.DECK,Zone.BOARD),
            kinds=(CardType.MINION,CardType.SPELL,CardType.WEAPON))if cid in(STORED_BUFF,DISCOUNT)else TargetSpec()
        card=CardDefinition(cid,cid,CardType.SPELL,cost=5 if cid==PRICE5 else 0,on_play=cid,metadata=plain,
            targeting=targets if cid in(KILL,BUFF,STORED_BUFF,DISCOUNT)else None)
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K734 deliberate rollback')))
    def relevant(c):return c.event.action>0 and(c.event.kind!='turn_started'or c.event.player_id==c.player_id)
    def wait(c):
        return(RequestChoice(c.player_id,(
            ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fault',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))) ,c.source_id),)
    for cid,event in((WATCH_DEATH,'minion_died'),(WATCH_SUMMON,'minion_summoned'),(WATCH_SWAP,'decks_exchanged'),(WATCH_TURN,'turn_started')):
        r.register_behavior(cid,wait);r.register_trigger_condition(cid,relevant)
        r.register_card(CardDefinition(cid,cid,CardType.MINION if cid==WATCH_SUMMON else CardType.WEAPON,
            health=10 if cid==WATCH_SUMMON else 0,durability=0 if cid==WATCH_SUMMON else 40,metadata=plain,
            limited_triggers=(LimitedTriggerSpec(event,cid,cid),)))
    if mode!='host':r.register_pool(PoolDefinition(native.POOL,P+'controlled-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in(A,B1,B2,B3,L,VICTIM))))
    r.validate();return r,host_context if mode=='host'else CTX


class FixedRewardTurnTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode)[0])
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=None,enemy_deck=None,weapon=None,mode='small',seed=734,active=1):
        self.mode=mode;r,ctx=fixture('writer',mode)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hero_power_card_id='HERO_08bp',hand=hand,board=board,
            deck=(A,)*4 if deck is None else deck,mana=40,max_mana=40,mana_cap=40,armor=500,weapon_card_id=weapon),
            PlayerSetup('HERO_08',hero_power_card_id='HERO_08bp',hand=enemy_hand,board=enemy,
            deck=(A,)*4 if enemy_deck is None else enemy_deck,mana=40,max_mana=40,mana_cap=40,armor=500)),
            active_player=active,seed=seed,generation_context=ctx),r)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def weapon(self,g,p=1):return g.state.entities[g.state.players[p].weapon_id]
    def faces(self,g,p=1,zone='hand'):return[g.state.entities[i].card_id for i in getattr(g.state.players[p],zone)]
    def drain(self,g):
        while g.state.pending_choice:self.choose(g,g.state.pending_choice.options[0].id)
    def fault(self,g):
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
    def memory(self,g):return next(a.deathrattle_memory for a in self.weapon(g).abilities if a.kind=='deathrattle')

    def test_complete_forty_five_rows_eighty_primary_faces_and_all_thirty_nine_definitions(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),80)
        self.assertEqual(sum(len(d[k])for k in('cards','dependencies','existing_dependencies','evidence_only')),45)
        self.assertEqual(len(d['original_candidate_ids']),732);self.assertEqual(len(native.DEPENDENCIES),29)
        for cid in native.ROOTS+native.DEPENDENCIES:self.assertEqual(fixture()[0].card(cid),fixture('independent-reader')[0].card(cid))
        self.assertEqual(d['fixed_Toxin_weights'],[1]*5);self.assertEqual(d['fixed_Death_Knight_weights'],[1]*8)
        self.assertEqual((fixture()[0].card(FROSTMOURNE).cost,fixture()[0].card(FROSTMOURNE).attack,fixture()[0].card(FROSTMOURNE).durability),(7,5,3))

    def test_all_ten_current_host_roots_and_twenty_nine_real_child_paid_entries(self):
        for cid in native.ROOTS+native.DEPENDENCIES:
            with self.subTest(cid=cid):
                g=self.game((cid,),board=(A,),enemy=(VICTIM,),mode='host')
                target=None
                if cid in(native.FIRE_TOXIN,native.ATTACK_TOXIN,native.COIL,native.OBLITERATE):target=self.unit(g,VICTIM,2).id
                if cid in(native.RETURN_TOXIN,native.STEALTH_TOXIN):target=self.unit(g,A).id
                before=g.state.players[1].mana;self.play(g,cid,target);self.drain(g)
                self.assertEqual(g.state.players[1].mana,before-g.registry.card(cid).cost)
                self.assertTrue(any(row.card_id==cid for row in g.state.play_history))

    def test_all_five_actually_generated_Xaril_Toxins_execute_without_substituting_Poisons(self):
        ids=tuple(sorted(native.TOXINS))
        for cid in native.TOXINS:
            with self.subTest(cid=cid):
                seed=next(n for n in range(200)if ids[Random(n).randrange(5)]==cid)
                g=self.game((XARIL,),board=(A,),enemy=(A,),seed=seed);self.play(g,XARIL)
                self.assertIn(cid,self.faces(g));old_deck=len(g.state.players[1].deck)
                own=self.unit(g,A);enemy=self.unit(g,A,2)
                target=enemy.id if cid==native.FIRE_TOXIN else own.id if cid!=native.DRAW_TOXIN else None
                self.play(g,cid,target)
                if cid==native.DRAW_TOXIN:self.assertEqual(len(g.state.players[1].deck),old_deck-1)
                if cid==native.FIRE_TOXIN:self.assertEqual(g.state.entities[enemy.id].health,10)
                if cid==native.ATTACK_TOXIN:self.assertEqual(g.state.entities[own.id].attack,5)
                if cid==native.RETURN_TOXIN:self.assertEqual(self.entity(g,A).id,own.id)
                if cid==native.STEALTH_TOXIN:
                    self.assertIn(Keyword.STEALTH,g.state.entities[own.id].keywords)
                    g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertNotIn(Keyword.STEALTH,g.state.entities[own.id].keywords)
        self.portable(g)

    def test_Xaril_natural_Deathrattle_and_Arfus_each_keep_complete_named_candidates(self):
        for source,ids in((XARIL,native.TOXINS),(ARFUS,native.REWARDS)):
            with self.subTest(source=source):
                g=self.game((KILL,),board=(source,));self.play(g,KILL,self.unit(g,source).id)
                self.assertEqual(len(self.faces(g)),1);self.assertIn(self.faces(g)[0],ids);self.portable(g)

    def test_all_eight_actually_generated_Arfus_rewards_are_real_playable_effects(self):
        ids=tuple(sorted(native.REWARDS))
        for cid in native.REWARDS:
            with self.subTest(cid=cid):
                seed=next(n for n in range(300)if ids[Random(n).randrange(8)]==cid)
                g=self.game((KILL,),board=(ARFUS,A),enemy=(VICTIM,),seed=seed)
                self.play(g,KILL,self.unit(g,ARFUS).id);self.assertIn(cid,self.faces(g))
                target=self.unit(g,VICTIM,2).id if cid in(native.COIL,native.OBLITERATE)else None
                self.play(g,cid,target);self.assertTrue(any(row.card_id==cid for row in g.state.play_history))

    def test_Lich_King_only_controller_end_generates_one_complete_reward(self):
        g=self.game((),board=(KING,));g.apply(EndTurn(1))
        rewards=[x for x in self.faces(g)if x in native.REWARDS];self.assertEqual(len(rewards),1)
        g.apply(EndTurn(2));self.assertEqual([x for x in self.faces(g)if x in native.REWARDS],rewards);self.portable(g)

    def test_Frostmourne_final_swing_includes_actual_kill_and_resummons_fresh_without_Battlecry(self):
        g=self.game((LAST,),enemy=(VICTIM,),weapon=FROSTMOURNE);old=self.unit(g,VICTIM,2).id
        self.play(g,LAST);g.apply(Attack(1,self.hero(g).id,old))
        self.assertIsNone(g.state.players[1].weapon_id);fresh=self.unit(g,VICTIM)
        self.assertNotEqual(fresh.id,old);self.assertEqual((fresh.attack,fresh.max_health),(0,4))
        self.assertEqual(self.hero(g).armor,500);self.portable(g)

    def test_Frostmourne_nonlethal_attack_and_spell_kill_are_not_weapon_kills(self):
        g=self.game((KILL,WEAR),enemy=(A,VICTIM),weapon=FROSTMOURNE)
        g.apply(Attack(1,self.hero(g).id,self.unit(g,A,2).id));self.play(g,KILL,self.unit(g,VICTIM,2).id)
        self.assertEqual(self.memory(g).weapon_kills,());self.play(g,WEAR)
        self.assertFalse(g.state.players[1].board);self.portable(g)

    def test_Frostmourne_current_weapon_copy_keeps_original_memory_but_new_weapon_is_empty(self):
        g=self.game((COPY_WEAPON,WEAR,FROSTMOURNE),enemy=(VICTIM,),weapon=FROSTMOURNE)
        old=self.weapon(g).id;g.apply(Attack(1,self.hero(g).id,self.unit(g,VICTIM,2).id))
        link,=self.memory(g).weapon_kills;self.play(g,COPY_WEAPON)
        self.assertNotEqual(self.weapon(g).id,old);self.assertEqual(self.memory(g).weapon_kills,(link,))
        self.play(g,WEAR);self.assertEqual(self.faces(g,zone='board').count(VICTIM),2)
        self.play(g,FROSTMOURNE);self.assertEqual(self.memory(g).weapon_kills,());self.portable(g)

    def test_Frostmourne_native_links_reject_changed_original_killing_blow_after_rehash(self):
        g=self.game((),enemy=(VICTIM,),weapon=FROSTMOURNE)
        g.apply(Attack(1,self.hero(g).id,self.unit(g,VICTIM,2).id));wid=self.weapon(g).id
        for field,value in(('death_id',999999),('weapon',dict(entity_id=wid,player_id=1,card_id=FROSTMOURNE,zone_epoch=999,entered_order=1))):
            saved=deepcopy(g.snapshot());memory=next(a['deathrattle_memory']for a in saved['state']['entities'][str(wid)]['abilities']if a['deathrattle_memory']is not None)
            memory['weapon_kills'][0][field]=value
            saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
            with self.subTest(field=field),self.assertRaises(SnapshotError):Game.from_snapshot(saved,fixture('independent-reader')[0])

    def test_Frostmourne_destroyed_weapon_summon_wait_restores_frozen_native_memory(self):
        g=self.game((WEAR,),board=(WATCH_SUMMON,),enemy=(VICTIM,),weapon=FROSTMOURNE)
        g.apply(Attack(1,self.hero(g).id,self.unit(g,VICTIM,2).id))
        self.play(g,WEAR);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g);self.fault(g);self.choose(g);self.portable(g)

    def test_Atiesh_uses_original_discounted_CAST_cost_and_loses_one_durability(self):
        g=self.game((DISCOUNT,PRICE5),weapon=ATIESH);self.play(g,DISCOUNT,self.entity(g,PRICE5).id)
        before=self.weapon(g).durability;self.play(g,PRICE5)
        self.assertEqual(self.weapon(g).durability,before-1)
        self.assertIn(B1,self.faces(g,zone='board'));self.portable(g)

    def test_Atiesh_full_board_and_empty_cost_pool_still_spend_the_actual_charge(self):
        g=self.game((native.FIRE_TOXIN,),board=(A,)*7,enemy=(A,),weapon=ATIESH)
        self.play(g,native.FIRE_TOXIN,self.unit(g,A,2).id);self.assertEqual(self.weapon(g).durability,2)
        self.assertEqual(len(g.state.players[1].board),7)
        g=self.game((PRICE5,),weapon=ATIESH);self.play(g,PRICE5);self.assertEqual(self.weapon(g).durability,2);self.assertFalse(g.state.players[1].board)

    def test_Atiesh_opponent_cast_does_not_spend_charge(self):
        g=self.game((),enemy_hand=(ZERO,),weapon=ATIESH);g.apply(EndTurn(1));self.play(g,ZERO,player=2)
        self.assertEqual(self.weapon(g).durability,3);self.assertFalse(g.state.players[1].board)

    def test_Atiesh_original_summon_wait_restores_charge_and_failed_choice_rng(self):
        g=self.game((native.FIRE_TOXIN,),board=(WATCH_SUMMON,),enemy=(A,),weapon=ATIESH)
        self.play(g,native.FIRE_TOXIN,self.unit(g,A,2).id)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.weapon(g).durability,3)
        self.portable(g);self.fault(g);self.choose(g);self.assertEqual(self.weapon(g).durability,2);self.portable(g)

    def test_Oakheart_recruits_original_current_Attack_one_two_three_without_Battlecry(self):
        g=self.game((OAKHEART,),deck=(B1,B2,B3,L));original={cid:self.entity(g,cid,zone='deck').id for cid in(B1,B2,B3)}
        self.play(g,OAKHEART)
        self.assertEqual([self.unit(g,cid).id for cid in(B1,B2,B3)],list(original.values()))
        self.assertEqual(self.faces(g,zone='deck'),[L]);self.assertEqual(self.hero(g).armor,500);self.portable(g)

    def test_Oakheart_partial_capacity_keeps_unrecruited_originals(self):
        g=self.game((OAKHEART,),board=(A,)*5,deck=(B1,B2,B3));self.play(g,OAKHEART)
        self.assertEqual(self.faces(g,zone='board').count(B1),1);self.assertEqual(self.faces(g,zone='deck'),[B2,B3])

    def test_Alanna_counts_actual_successful_original_cost_including_automatic_cast(self):
        g=self.game((PRICE5,AUTO,ALANNA));self.play(g,PRICE5);self.play(g,AUTO);self.play(g,ALANNA)
        self.assertEqual(self.faces(g,zone='board').count(DRAGON),2);self.portable(g)

    def test_Alanna_does_not_count_discounted_printed_five_cost_as_actual_five(self):
        g=self.game((DISCOUNT,PRICE5,ALANNA));self.play(g,DISCOUNT,self.entity(g,PRICE5).id);self.play(g,PRICE5);self.play(g,ALANNA)
        self.assertNotIn(DRAGON,self.faces(g,zone='board'));self.portable(g)

    def test_Temporus_runs_two_enemy_then_two_owner_actual_turns_and_resumes_normal_successor(self):
        g=self.game((TEMPORUS,));self.play(g,TEMPORUS);self.portable(g);sequence=[]
        for _ in range(5):g.apply(EndTurn(g.state.active_player));sequence.append(g.state.active_player)
        self.assertEqual(sequence,[2,2,1,1,2]);self.portable(g)

    def test_Temporus_second_player_uses_same_relative_schedule(self):
        g=self.game(enemy_hand=(TEMPORUS,),active=2);self.play(g,TEMPORUS,player=2);seq=[]
        for _ in range(5):g.apply(EndTurn(g.state.active_player));seq.append(g.state.active_player)
        self.assertEqual(seq,[1,1,2,2,1]);self.portable(g)

    def test_Temporus_real_start_wait_restores_remaining_original_schedule(self):
        g=self.game((TEMPORUS,),weapon=WATCH_TURN);self.play(g,TEMPORUS)
        g.apply(EndTurn(1));g.apply(EndTurn(2));g.apply(EndTurn(2))
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.fault(g);self.choose(g);self.portable(g)

    def test_Togwaggle_swap_keeps_original_order_IDs_owner_stats_cost_and_no_draw(self):
        g=self.game((TOGWAGGLE,DISCOUNT),deck=(A,B1),enemy_deck=(B2,L));old={p:tuple(g.state.players[p].deck)for p in(1,2)}
        self.play(g,DISCOUNT,old[1][0]);draws=len(g.state.draw_history);self.play(g,TOGWAGGLE)
        self.assertEqual(tuple(g.state.players[1].deck),old[2]);self.assertEqual(tuple(g.state.players[2].deck),old[1])
        self.assertEqual((g.state.entities[old[1][0]].owner,g.state.entities[old[1][0]].controller),(1,2))
        self.assertEqual(len(g.state.draw_history),draws);self.assertIn(RANSOM,self.faces(g,2));self.portable(g)

    def test_Ransom_exchanges_the_actual_current_whole_decks_back(self):
        g=self.game((TOGWAGGLE,),deck=(A,B1),enemy_deck=(B2,L));original=tuple(g.state.players[1].deck)
        self.play(g,TOGWAGGLE);g.apply(EndTurn(1));self.play(g,RANSOM,player=2)
        self.assertEqual(tuple(g.state.players[1].deck),original[1:]);self.portable(g)

    def test_Togwaggle_two_full_ninety_nine_card_decks_do_not_burn_from_intermediate_overflow(self):
        g=self.game((TOGWAGGLE,),deck=(A,)*99,enemy_deck=(B1,)*99)
        old={p:tuple(g.state.players[p].deck)for p in(1,2)};self.play(g,TOGWAGGLE)
        self.assertEqual(tuple(g.state.players[1].deck),old[2]);self.assertEqual(tuple(g.state.players[2].deck),old[1])
        self.assertFalse(any(e.kind=='card_burned'for e in g.events));self.portable(g)

    def test_Togwaggle_notification_wait_observes_both_final_inventories_atomically(self):
        g=self.game((TOGWAGGLE,),deck=(A,B1),enemy_deck=(B2,),weapon=WATCH_SWAP);self.play(g,TOGWAGGLE)
        self.assertEqual(self.faces(g,zone='deck'),[B2]);self.assertEqual(self.faces(g,2,'deck'),[A,B1])
        self.portable(g);self.fault(g);self.choose(g);self.assertIn(RANSOM,self.faces(g,2));self.portable(g)

    def test_Death_Grip_moves_original_enemy_minion_with_modifiers_without_draw(self):
        g=self.game((native.GRIP,),enemy_deck=(VICTIM,ZERO));eid=self.entity(g,VICTIM,2,'deck').id
        self.play(g,native.GRIP);self.assertEqual(self.entity(g,VICTIM).id,eid)
        self.assertEqual((g.state.entities[eid].owner,g.state.entities[eid].controller),(2,1));self.assertFalse(g.state.draw_history)
        self.assertFalse(any(e.kind=='random_choice'for e in g.events));self.portable(g)

    def test_Death_Grip_no_matching_minion_neither_draws_fatigues_nor_uses_rng(self):
        g=self.game((native.GRIP,),enemy_deck=(ZERO,));rng=g.snapshot()['rng_state'];self.play(g,native.GRIP)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertFalse(g.state.draw_history);self.assertEqual(self.hero(g).armor,500)

    def test_Doom_Pact_counts_only_actual_original_destroyed_minions_before_removing_top_cards(self):
        g=self.game((native.PACT,),board=(B1,),enemy=(SPAWNER,),deck=(A,B2,B3,L))
        self.play(g,native.PACT);self.assertEqual(self.faces(g,zone='deck'),[B3,L])
        self.assertEqual(self.faces(g,2,'board'),[A]);self.assertFalse(g.state.draw_history);self.portable(g)

    def test_Doom_Pact_death_wait_restores_actual_causes_before_counted_milling(self):
        g=self.game((native.PACT,),board=(B1,),enemy=(VICTIM,),weapon=WATCH_DEATH)
        self.play(g,native.PACT);self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.fault(g);self.choose(g)
        self.assertEqual(len(g.state.players[1].deck),2);self.portable(g)

    def test_Army_removes_only_original_top_five_and_summons_original_minions_without_Battlecry(self):
        g=self.game((native.ARMY,),deck=(VICTIM,ZERO,B1,ZERO,ZERO,L));ids={cid:self.entity(g,cid,zone='deck').id for cid in(VICTIM,B1)}
        self.play(g,native.ARMY);self.assertEqual(self.faces(g,zone='deck'),[L])
        self.assertEqual([self.unit(g,cid).id for cid in(VICTIM,B1)],list(ids.values()));self.assertEqual(self.hero(g).armor,500)
        self.assertFalse(g.state.draw_history);self.portable(g)

    def test_Army_full_board_removes_minions_without_fallback_draw_or_sixth_card(self):
        g=self.game((native.ARMY,),board=(A,)*7,deck=(B1,B2,B3,VICTIM,L,A));rng=g.snapshot()['rng_state']
        self.play(g,native.ARMY);self.assertEqual(self.faces(g,zone='deck'),[A]);self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertFalse(g.state.draw_history);self.portable(g)

    def test_Elise_real_Map_draw_and_Golden_Monkey_chain_preserves_physical_hand_identity(self):
        g=self.game((ELISE,DRAW,ZERO),deck=());self.play(g,ELISE);self.play(g,DRAW);self.assertIn(MAP,self.faces(g))
        self.play(g,MAP);self.assertIn(MONKEY,self.faces(g));original=self.entity(g,ZERO).id
        self.play(g,MONKEY);self.assertEqual(g.state.entities[original].card_id,L);self.assertEqual(g.state.entities[original].zone,Zone.HAND);self.portable(g)

    def test_Golden_Monkey_transforms_all_original_hand_and_deck_refs_using_full_controlled_pool(self):
        g=self.game((MONKEY,ZERO,B1),deck=(A,B2));original=tuple(g.state.players[1].hand[1:])+tuple(g.state.players[1].deck)
        self.play(g,MONKEY);self.assertTrue(all(g.state.entities[i].card_id==L for i in original));self.portable(g)

    def test_Rin_all_five_actual_Seals_exact_Demons_and_Azari_destroy_whole_enemy_deck(self):
        g=self.game((KILL,),board=(RIN,));self.play(g,KILL,self.unit(g,RIN).id)
        for cid in native.SEALS:self.assertIn(cid,self.faces(g));self.play(g,cid)
        self.assertIn(AZARI,self.faces(g));self.play(g,AZARI);self.assertFalse(g.state.players[2].deck)
        self.assertEqual([g.registry.card(cid).attack for cid in self.faces(g,zone='board')],[2,3,4,5,6,10])
        self.assertFalse(g.state.draw_history);self.portable(g)

    def test_Seal_full_board_still_gets_next_actual_Seal(self):
        g=self.game((native.SEALS[0],),board=(A,)*7);self.play(g,native.SEALS[0])
        self.assertIn(native.SEALS[1],self.faces(g));self.assertNotIn(native.HOUNDS[0],self.faces(g,zone='board'))

    def test_private_native_weapon_memory_zone_references_and_future_schedule_do_not_enter_player_views(self):
        g=self.game((),enemy=(VICTIM,),weapon=FROSTMOURNE);g.apply(Attack(1,self.hero(g).id,self.unit(g,VICTIM,2).id))
        for p in(1,2):
            text=json.dumps(g.for_player(p).observe())
            for field in('weapon_kills','deathrattle_memory','resolution_frame','rng_state','source_cost'):
                self.assertNotIn('"'+field+'"',text)
        self.portable(g)
