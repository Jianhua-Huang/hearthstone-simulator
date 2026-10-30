"""Actual legendary armor, school and current-deck consumers."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from tools import card_batch as cb
from hs_sim.cards import past_legendary_armor_deck as native
from hs_sim.engine import Attack,EndTurn,Game,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import (AddCostModifier,ChoiceOption,Damage,Destroy,Draw,GainArmor,
    InvokeBehavior,ModifyCost,RandomDamage,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,DamageKind,Keyword,SpellSchool,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.registry import Registry
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from hs_sim.local_pool_format import build_cn37_local_pool_format

GALV,BRUK,RENO,DREK,VAND=native.ROOTS
P='k697.';A=P+'low';B=P+'high';EQUAL=P+'equal';ALIAS=P+'alias';U=P+'universal';BIG=P+'big_hero';BC=P+'battlecry'
GAIN7=P+'gain7';GAIN8=P+'gain8';GAIN15=P+'gain15';OTHER15=P+'other15';HURT=P+'hurt'
NATURE=P+'nature';FIRE=P+'fire';EFFECT=P+'effect';HUSH=P+'hush';KILL=P+'kill';DRAW=P+'draw'
SELF_LOW=P+'self_low';SELF_HIGH=P+'self_high';DECK_LOW=P+'deck_low';DECK_HIGH=P+'deck_high';CHEAP=P+'cheap'
WATCH=P+'watch';FAIL=P+'fail';STAT_WATCH=P+'stat_watch';HEAL_WATCH=P+'heal_watch'
SUMMON_WATCH=P+'summon_watch';COST_WATCH=P+'cost_watch'
HELPERS=(A,B,EQUAL,ALIAS,U,BIG,BC,GAIN7,GAIN8,GAIN15,OTHER15,HURT,NATURE,FIRE,EFFECT,HUSH,KILL,DRAW,
    SELF_LOW,SELF_HIGH,DECK_LOW,DECK_HIGH,CHEAP,STAT_WATCH,HEAL_WATCH,SUMMON_WATCH,COST_WATCH)


@lru_cache(None)
def host(role='writer'):
    h=build_cn37_local_pool_format();r=h.registry;meta=metadata(collectible=False)
    for cid,cost in((A,2),(B,6),(EQUAL,4),(ALIAS,2)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=2,health=20,
            metadata=replace(meta,deck_identity=A if cid==ALIAS else cid)))
    r.register_card(CardDefinition(U,U,CardType.MINION,cost=3,attack=1,health=20,spell_damage=2,metadata=meta))
    r.register_card(CardDefinition(BIG,BIG,CardType.HERO,health=50,metadata=meta))
    r.register_behavior(BC,lambda c:(GainArmor(c.player_id,100),))
    r.register_card(CardDefinition(BC,BC,CardType.MINION,cost=2,attack=2,health=20,battlecry=BC,metadata=meta))
    def self_cost(c,amount):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id in(DREK,VAND))
        return(ModifyCost(e.id,CostSpec(set_to=amount),c.source_id),)
    def deck_cost(c,amount):
        e=c.state.entities[c.state.players[c.player_id].deck[0]]
        return(ModifyStoredCost(CardReference.capture(e),CostSpec(set_to=amount),c.source_id),)
    scripts={GAIN7:lambda c:(GainArmor(c.player_id,7),),GAIN8:lambda c:(GainArmor(c.player_id,8),),
        GAIN15:lambda c:(GainArmor(c.player_id,15),),OTHER15:lambda c:(GainArmor(3-c.player_id,15),),
        HURT:lambda c:(Damage(c.state.players[c.player_id].hero_id,20,c.source_id),),
        NATURE:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),),
        FIRE:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),),
        EFFECT:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.EFFECT),),
        HUSH:lambda c:(Silence(c.target_id),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),
        SELF_LOW:lambda c:self_cost(c,1),SELF_HIGH:lambda c:self_cost(c,8),
        DECK_LOW:lambda c:deck_cost(c,1),DECK_HIGH:lambda c:deck_cost(c,8),
        CHEAP:lambda c:(AddCostModifier(c.player_id,CostSpec(set_to=1,card_types=(CardType.MINION,)),c.source_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=cid,metadata=meta,
            spell_school=SpellSchool.NATURE if cid==NATURE else SpellSchool.FIRE if cid==FIRE else None,
            targeting=TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION))if cid in(NATURE,FIRE,EFFECT,HUSH,KILL)else None))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K697 deliberate continuation failure')))
    def watch(c):
        source=c.state.entities.get(c.event.source_id);target=c.state.entities.get(c.event.target_id)
        if c.event.kind=='minion_summoned':
            if target is None or target.card_id not in(A,B,BC):return()
        elif source is None or source.card_id not in(GALV,RENO,VAND):return()
        leave=()if source is None or source.zone!=Zone.BOARD else(ReturnToHand(source.id),)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('leave','Retire source',leave),
            ChoiceOption('draw','Move original deck cards',(Draw(c.player_id,2,c.source_id),)),
            ChoiceOption('fault','Fail after random work',(
                RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    for cid,event in((STAT_WATCH,'stats_changed'),(HEAL_WATCH,'healed'),(SUMMON_WATCH,'minion_summoned'),(COST_WATCH,'cost_modified')):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=40,metadata=meta,triggers=(TriggerSpec(event,WATCH),)))
    r.validate();return h


@lru_cache(None)
def fixture(role='writer'):
    full=host(role).registry;r=Registry('k697-real-legendary-armor-deck-v1')
    for bid,body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):r.register_behavior(bid,body)
    for cid in('TIME_013','HERO_08','HERO_08bp',*HELPERS):
        r.register_card(full.card(cid))
        if cid in full.pool_cards:r.register_pool_card(full.pool_card(cid))
    native.register_past_legendary_armor_deck(r);r.validate();return r


class PastLegendaryArmorDeckTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),deck=(A,B),enemy=(),armor=0,watch=None,big=False,real_host=False):
        self.mode='host'if real_host else'small';h=host('writer')
        return Game.from_scenario(Scenario((PlayerSetup(BIG if big else'HERO_08',hand=hand,board=board,deck=deck,
            mana=30,max_mana=30,mana_cap=30,armor=armor,weapon_card_id=watch,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',board=enemy,deck=(A,)*8,hero_power_card_id='HERO_08bp')),
            seed=697,generation_context=h.context if real_host else None),h.registry if real_host else fixture('writer'))

    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def cost(self,g,cid,zone='deck'):return local_cost(self.entity(g,cid,zone=zone))[0]
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def fault_atomic(self,g):
        self.assertIsNotNone(g.state.pending_choice);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_complete_raw_primary_and_actual_five_definitions(self):
        d=native.load_batch();r=fixture();self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(len(d['official_observations']),14)
        for row in d['cards']:
            cid=row['record']['id'];self.assertEqual(cb.canonical(asdict(r.card(cid))),row['definition_sha256'])
        self.assertEqual(r.card(BRUK).spell_damage_schools,(SpellSchool.NATURE,));self.assertEqual(r.card(BRUK).spell_damage,3)
        self.assertFalse(d['complete_past_legendary_source_bound']);self.assertFalse(d['new_standard_roots'])

    def test_real_paid_five_entries_keep_physical_faces_and_single_payment(self):
        for cid in native.ROOTS:
            g=self.game((cid,),deck=());source=self.play(g,cid);self.finish(g);card=g.registry.card(cid)
            self.assertEqual((g.state.entities[source].card_id,g.state.players[1].mana),(cid,30-card.cost))
            self.assertEqual(len(g.state.play_history),1)

    def test_galvangar_counts_spent_lifetime_armor_and_charge_really_attacks(self):
        g=self.game((GAIN7,GAIN8,HURT,GALV));self.play(g,GAIN7);self.play(g,GAIN8);self.play(g,HURT)
        self.assertEqual(self.hero(g).armor,0);source=self.play(g,GALV)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(9,9))
        g.apply(Attack(1,source,self.hero(g,2).id));self.assertEqual(self.hero(g,2).health,21);self.portable(g)

    def test_galvangar_fourteen_initial_armor_and_opponent_gains_are_not_fifteen(self):
        for hand,armor in(((GALV,),30),((GAIN7,GAIN7,GALV),0),((OTHER15,GALV),0)):
            g=self.game(hand,armor=armor)
            for cid in hand[:-1]:self.play(g,cid)
            source=self.play(g,GALV);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(6,6))
            self.assertNotIn(Keyword.CHARGE,g.state.entities[source].keywords)

    def test_galvangar_counts_previous_turn_actual_gains(self):
        g=self.game((GAIN15,GALV));self.play(g,GAIN15)
        g.apply(EndTurn(1));g.apply(EndTurn(2));source=self.play(g,GALV)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(9,9))

    def test_galvangar_buff_wait_recovers_and_moved_source_does_not_gain_charge(self):
        g=self.game((GAIN15,GALV),watch=STAT_WATCH);self.play(g,GAIN15);source=self.play(g,GALV)
        g=self.portable(g);self.fault_atomic(g);self.choose(g,'leave');self.finish(g)
        self.assertEqual(g.state.entities[source].zone,Zone.HAND);self.assertNotIn(Keyword.CHARGE,g.state.entities[source].keywords)
        self.portable(g)

    def test_brukan_bonuses_nature_only_and_stacks_with_universal_provider(self):
        g=self.game((NATURE,FIRE,EFFECT),board=(BRUK,U));target=self.hero(g,2).id
        self.play(g,NATURE,target);self.assertEqual(self.hero(g,2).health,23)
        self.play(g,FIRE,target);self.assertEqual(self.hero(g,2).health,19)
        self.play(g,EFFECT,target);self.assertEqual(self.hero(g,2).health,17);self.portable(g)

    def test_brukan_silence_and_death_retire_actual_school_provider(self):
        for removal in(HUSH,KILL):
            g=self.game((removal,NATURE),board=(BRUK,));self.play(g,removal,self.unit(g,BRUK).id)
            self.play(g,NATURE,self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,28)

    def test_reno_unique_current_deck_heals_actual_fifty_health_maximum(self):
        g=self.game((HURT,RENO),deck=(A,B),big=True);self.play(g,HURT);self.assertEqual(self.hero(g).health,30)
        self.play(g,RENO);self.assertEqual(self.hero(g).health,50);self.portable(g)

    def test_reno_duplicates_and_same_identity_printings_fail(self):
        for deck in((A,A),(A,ALIAS)):
            g=self.game((HURT,RENO),deck=deck);self.play(g,HURT);self.play(g,RENO);self.assertEqual(self.hero(g).health,10)

    def test_reno_empty_current_deck_and_duplicate_hand_still_heal(self):
        g=self.game((HURT,RENO,A,A),deck=());self.play(g,HURT);self.play(g,RENO)
        self.assertEqual(self.hero(g).health,30)

    def test_reno_reads_deck_after_physical_duplicate_is_drawn(self):
        g=self.game((HURT,DRAW,RENO),deck=(A,A,B));self.play(g,HURT);self.play(g,DRAW);self.play(g,RENO)
        self.assertEqual(self.hero(g).health,30);self.assertEqual(len(g.state.players[1].deck),2)

    def test_reno_healing_wait_preserves_actual_result_and_rolls_back_fault(self):
        g=self.game((HURT,RENO),deck=(A,B),watch=HEAL_WATCH);self.play(g,HURT);self.play(g,RENO)
        g=self.portable(g);self.fault_atomic(g);self.finish(g);self.assertEqual(self.hero(g).health,30)

    def test_drekthar_recruits_one_original_physical_deck_card_without_battlecry(self):
        g=self.game((DREK,),deck=(BC,));original=g.state.players[1].deck[0];self.play(g,DREK)
        self.assertIn(original,g.state.players[1].board);self.assertEqual(g.state.players[1].deck,[])
        self.assertEqual(self.hero(g).armor,0);self.assertEqual(len(g.state.play_history),1)
        self.assertEqual(g.state.players[1].mana,26);self.portable(g)

    def test_drekthar_equality_or_any_higher_minion_fails_full_comparison(self):
        for deck in((A,EQUAL),(A,B)):
            g=self.game((DREK,),deck=deck);before=tuple(g.state.players[1].deck);rng=g.snapshot()['rng_state'];self.play(g,DREK)
            self.assertEqual(tuple(g.state.players[1].deck),before);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_drekthar_uses_current_stored_deck_cost_and_not_printed_cost(self):
        g=self.game((DECK_LOW,DREK),deck=(B,));self.play(g,DECK_LOW);original=g.state.players[1].deck[0];self.play(g,DREK)
        self.assertIn(original,g.state.players[1].board)
        g=self.game((DECK_HIGH,DREK),deck=(A,));self.play(g,DECK_HIGH);self.play(g,DREK)
        self.assertEqual(len(g.state.players[1].deck),1)

    def test_drekthar_source_local_cost_changes_threshold(self):
        g=self.game((SELF_LOW,DREK),deck=(A,));self.play(g,SELF_LOW);self.play(g,DREK)
        self.assertEqual(len(g.state.players[1].deck),1);self.assertEqual(g.state.players[1].mana,28)
        g=self.game((SELF_HIGH,DREK),deck=(B,));self.play(g,SELF_HIGH);self.play(g,DREK)
        self.assertEqual(g.state.players[1].deck,[]);self.assertEqual(g.state.players[1].mana,21)

    def test_drekthar_global_hand_payment_does_not_replace_explicit_local_basis(self):
        g=self.game((CHEAP,DREK),deck=(A,));self.play(g,CHEAP);self.play(g,DREK)
        self.assertEqual(g.state.players[1].mana,28);self.assertEqual(g.state.players[1].deck,[])

    def test_drekthar_empty_pool_nonminions_and_full_board_do_not_consume_rng(self):
        for deck,board in(((),()),((NATURE,),()),((A,),(B,)*6)):
            g=self.game((DREK,),deck=deck,board=board);before=tuple(g.state.players[1].deck);rng=g.snapshot()['rng_state']
            self.play(g,DREK);self.assertEqual(tuple(g.state.players[1].deck),before);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_drekthar_summon_wait_preserves_delivery_and_never_recruits_twice(self):
        g=self.game((DREK,),deck=(A,A),watch=SUMMON_WATCH);self.play(g,DREK)
        g=self.portable(g);self.fault_atomic(g);self.finish(g);self.assertEqual(len(g.state.players[1].deck),1)
        self.assertEqual(len(g.state.players[1].board),2);self.portable(g)

    def test_vanndar_discounts_only_current_physical_deck_minions(self):
        g=self.game((VAND,B),deck=(B,B,NATURE));self.play(g,VAND)
        self.assertEqual([local_cost(g.state.entities[i])[0]for i in g.state.players[1].deck],[3,3,1])
        self.assertEqual(self.cost(g,B,'hand'),6);self.assertEqual(g.state.players[1].mana,26)

    def test_vanndar_any_equal_or_lower_minion_prevents_all_discounts(self):
        for deck in((B,EQUAL),(B,A)):
            g=self.game((VAND,),deck=deck);before=[local_cost(g.state.entities[i])[0]for i in g.state.players[1].deck]
            self.play(g,VAND);self.assertEqual([local_cost(g.state.entities[i])[0]for i in g.state.players[1].deck],before)

    def test_vanndar_source_and_deck_use_current_local_costs(self):
        g=self.game((SELF_LOW,VAND),deck=(A,));self.play(g,SELF_LOW);self.play(g,VAND);self.assertEqual(self.cost(g,A),0)
        g=self.game((DECK_LOW,VAND),deck=(B,));self.play(g,DECK_LOW);self.play(g,VAND);self.assertEqual(self.cost(g,B),1)
        g=self.game((SELF_HIGH,VAND),deck=(B,));self.play(g,SELF_HIGH);self.play(g,VAND);self.assertEqual(self.cost(g,B),6)

    def test_vanndar_waiting_moved_later_original_reference_is_skipped(self):
        g=self.game((VAND,),deck=(B,B),watch=COST_WATCH);self.play(g,VAND)
        g=self.portable(g);self.fault_atomic(g);self.choose(g,'draw');self.finish(g)
        self.assertEqual([local_cost(g.state.entities[i])[0]for i in g.state.players[1].hand],[3,6])
        self.assertEqual(g.state.players[1].deck,[]);self.portable(g)

    def test_vanndar_accepted_original_group_continues_after_source_leaves(self):
        g=self.game((VAND,),deck=(B,B),watch=COST_WATCH);source=self.play(g,VAND)
        self.assertIsNotNone(g.state.pending_choice);self.choose(g,'leave');self.finish(g)
        self.assertEqual(g.state.entities[source].zone,Zone.HAND)
        self.assertEqual([local_cost(g.state.entities[i])[0]for i in g.state.players[1].deck],[3,3])

    def test_complete_standard_host_five_real_entries_and_physical_consumers(self):
        g=self.game((GAIN15,GALV),real_host=True);self.play(g,GAIN15);source=self.play(g,GALV)
        self.assertEqual(g.state.entities[source].attack,9)
        g=self.game((BRUK,NATURE),real_host=True);self.play(g,BRUK);self.play(g,NATURE,self.hero(g,2).id)
        self.assertEqual(self.hero(g,2).health,25)
        g=self.game((HURT,RENO),real_host=True);self.play(g,HURT);self.play(g,RENO);self.assertEqual(self.hero(g).health,30)
        g=self.game((DREK,),deck=(A,),real_host=True);old=g.state.players[1].deck[0];self.play(g,DREK)
        self.assertIn(old,g.state.players[1].board)
        g=self.game((VAND,DRAW),deck=(B,),real_host=True);self.play(g,VAND);self.play(g,DRAW)
        self.assertEqual(self.cost(g,B,'hand'),3);self.portable(g)


class GalvangarPrimaryDisplayTests(unittest.TestCase):
    def rows(self):
        d=native.load_batch();raw=d['cards'][0]['record']
        return raw,[x for x in d['official_observations']if x['card_id']==GALV]

    def test_complete_bilingual_primary_preserves_fifteen_and_both_labels(self):
        raw,faces=self.rows();old=deepcopy(raw)
        for x in faces:cb.check_face(raw,x['face'],x['locale'],{'@':'','{0}':''})
        self.assertEqual(raw,old)

    def test_changed_pinned_chinese_row_cannot_borrow_armor_label(self):
        raw,faces=self.rows();face=next(x['face']for x in faces if x['locale']=='zh_CN')
        for key,value in(('id','other'),('source_entity_version','99')):
            altered=deepcopy(raw);altered[key]=value
            with self.assertRaises(ValueError):cb.check_face(altered,face,'zh_CN',{'@':'','{0}':''})

    def test_changed_rule_numbers_keywords_or_labels_reject(self):
        raw,faces=self.rows()
        for x in faces:
            for old,new in(('15','16'),('3','4'),('冲锋','嘲讽')if x['locale']=='zh_CN'else('Charge','Taunt')):
                face=deepcopy(x['face']);face['text']=face['text'].replace(old,new)
                with self.assertRaises(ValueError):cb.check_face(raw,face,x['locale'],{'@':'','{0}':''})

    def test_display_does_not_accept_changed_live_values_or_unknown_markers(self):
        raw,faces=self.rows()
        for x in faces:
            for markers in({'@':'','{0}':'15'},{'@':'','{0}':'','{1}':''}):
                with self.assertRaises(ValueError):cb.check_face(raw,x['face'],x['locale'],markers)


if __name__=='__main__':unittest.main()
