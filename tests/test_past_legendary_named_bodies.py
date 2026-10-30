"""Named Legendary recipes use real dependency faces and shared execution facts."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import past_legendary_named_bodies as native
from hs_sim.engine import Attack,EndTurn,Game,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import (Buff,ChangeControl,ChoiceOption,Damage,Destroy,DestroyBatch,
    InvokeBehavior,RandomDamage,RequestChoice,Silence,Transform,TriggerDeathrattles)
from hs_sim.engine.model import CardDefinition,CardType,Keyword,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError,canonical_digest
from tools import card_batch as cb

CHILL,SALLY,MUKLA,LEEROY,ONYXIA,FLARK,BOOM,NOMI,NOZARI,CAGE,STALAGG,FEUGEN=native.ROOTS
LWHELP,OWHELP,BOT,ELEMENTAL,BOAR,THADDIUS=native.DEPENDENCIES
BANANA='EX1_014t';BOMB='BOT_031'
P='k684.';A=P+'plain';DRAGON=P+'dragon';ALL=P+'all';DORMANT=P+'dormant';LOCATION=P+'location';POWER=P+'power'
KILL=P+'kill';WIPE=P+'wipe';BUFF=P+'buff';HUSH=P+'hush';TURN=P+'turn';TAKE=P+'take';TRIGGER=P+'trigger'
HURT=P+'hurt';SUMMON=P+'summon';WATCH=P+'summonwatch';DAMAGEWATCH=P+'damagewatch';FAIL=P+'fail';NOOP=P+'noop'


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=opening_registry();full=host(role).registry
    # Borrow actual registered dependency definitions and callables, never a fixture reimplementation.
    for cid in(BANANA,BOMB):
        card=full.card(cid);key=card.on_play or card.deathrattle
        r.register_behavior(key,full.behavior(key));r.register_card(card);r.register_pool_card(full.pool_card(cid))
    native.register_past_legendary_named_bodies(r)
    for cid,tribes,dormant,power in((A,(),0,0),(DRAGON,('dragon',),0,0),(ALL,('all',),0,0),
            (DORMANT,(),3,0),(POWER,(),0,9)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=40,dormant_turns=dormant,
            spell_damage=power,metadata=metadata(collectible=False,tribes=tribes)))
    r.register_behavior(NOOP,lambda c:())
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,durability=2,on_use=NOOP,metadata=metadata(collectible=False)))
    board=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),BUFF:lambda c:(Buff(c.target_id,3,4,c.source_id),),
        HUSH:lambda c:(Silence(c.target_id),),TURN:lambda c:(Transform(c.target_id,A),),
        TAKE:lambda c:(ChangeControl(c.target_id,3-c.player_id),),TRIGGER:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        WIPE:lambda c:(DestroyBatch(tuple(c.state.players[c.player_id].board),c.source_id),),
        HURT:lambda c:tuple(Damage(c.state.players[p].hero_id,8,c.source_id)for p in(1,2)),
        SUMMON:lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(ONYXIA),),SummonCause.capture(c)),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            targeting=None if cid in(WIPE,HURT,SUMMON)else board,metadata=metadata(collectible=False)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K684 deliberate named-body rollback')))
    def wait(c):
        event=c.event
        if event.kind=='minion_summoned':
            if c.state.entities[event.target_id].card_id!=OWHELP:return()
        else:
            source=c.state.entities.get(event.source_id)
            if source is None or source.card_id!=BOT:return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,wait)
    for cid,event in((WATCH,'minion_summoned'),(DAMAGEWATCH,'damage_dealt')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=40,triggers=(TriggerSpec(event,WATCH),),metadata=metadata(collectible=False)))
    r.validate();return r


@lru_cache(None)
def official_fixture():
    d=native.load_batch();row=next(x['record']for x in d['cards']if x['record']['id']==CHILL)
    index={(x['locale'],x['face']['id']):{k:v for k,v in x.items()if k not in('card_id','locale')}
        for x in d['official_observations']}
    return row,index,d['display_normalizations'][CHILL]


class PastLegendaryNamedTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=('card.1',)*20,player=1):
        self.mode='small'
        return Game.from_scenario(Scenario(tuple(PlayerSetup('mage.hero'if p==1 else'warrior.hero',
            hand=hand if p==player else enemy_hand,board=board if p==player else enemy,
            deck=deck if p==player else('card.1',)*20,mana=40,max_mana=40,mana_cap=40)for p in(1,2)),
            active_player=player,seed=684),fixture('writer'))
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def board(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].board]
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]

    def test_complete_rows_real_linked_dependencies_and_full_reference_are_preserved(self):
        d=native.load_batch();r=fixture();self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['official_observations'])),(12,6,28))
        self.assertEqual(len(d['original_candidate_ids']),732);self.assertFalse(d['complete_past_legendary_source_bound'])
        for row in d['cards']+d['dependencies']:
            cid=row['record']['id'];self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(r.pool_card(cid))),row['pool_card_sha256'])
        self.assertNotEqual(LWHELP,OWHELP);self.assertEqual((r.card(THADDIUS).cost,r.card(THADDIUS).attack,r.card(THADDIUS).health),(10,11,11))
        with patch.object(native,'BATCH_HASH',''):
            with self.assertRaises(TargetValidationError):native.load_batch()

    def test_chillmaw_display_mapping_is_exact_locale_scoped_and_does_not_change_source(self):
        row,index,mapping=official_fixture();saved=deepcopy(row)
        for locale in('zh_CN','en_US'):cb.catalog_official(row,locale,index,display_normalizations=mapping)
        self.assertEqual(row,saved)
        face=index['zh_CN',row['dbf_id']]['face']
        with self.assertRaises(ValueError):cb.check_face(row,dict(face,text=face['text'].replace('3','4')),'zh_CN',mapping)
        changed=deepcopy(row);changed['health']+=1
        with self.assertRaises(ValueError):cb.check_face(changed,face,'zh_CN',mapping)
        with self.assertRaises(ValueError):cb.check_face(row,face,'zh_CN')
        changed=deepcopy(row);changed['id']='unknown.chillmaw'
        with self.assertRaises(ValueError):cb.check_face(changed,face,'zh_CN',mapping)

    def test_all_eighteen_faces_have_ordinary_paid_entry_and_complete_printed_stats(self):
        for cid in(*native.ROOTS,*native.DEPENDENCIES):
            with self.subTest(card=cid):
                g=self.game((cid,));self.play(g,cid);card=g.registry.card(cid);e=self.unit(g,cid)
                self.assertEqual((e.attack,e.health),(card.attack,card.health));self.assertEqual(g.state.players[1].mana,40-card.cost)
                self.assertEqual([x.card_id for x in g.state.play_history],[cid])

    def test_mukla_gives_two_known_actual_bananas_that_keep_their_original_buff(self):
        g=self.game((MUKLA,),enemy=(A,));self.play(g,MUKLA);self.assertEqual(self.hand(g,2),[BANANA,BANANA])
        for pid in(1,2):self.assertIn(BANANA,json.dumps(g.for_player(pid).observe()))
        g.apply(EndTurn(1));target=self.unit(g,A,2).id;self.play(g,BANANA,target,2)
        e=g.state.entities[target];self.assertEqual((e.attack,e.health),(2,41));self.portable(g)

    def test_mukla_full_enemy_hand_burns_real_cards_without_replacing_old_entities(self):
        g=self.game((MUKLA,),enemy_hand=(A,)*10);old=tuple(g.state.players[2].hand);self.play(g,MUKLA)
        self.assertEqual(tuple(g.state.players[2].hand),old)
        self.assertEqual(sum(e.card_id==BANANA and e.zone==Zone.GRAVEYARD for e in g.state.entities.values()),2)
        self.assertFalse(g.state.draw_history)

    def test_leeroy_summons_his_two_enemy_whelps_and_can_immediately_attack_hero(self):
        g=self.game((LEEROY,));self.play(g,LEEROY);self.assertEqual(self.board(g,2),[LWHELP,LWHELP])
        g.apply(Attack(1,self.unit(g,LEEROY).id,self.hero(g,2).id));self.assertEqual(self.hero(g,2).health,24);self.portable(g)

    def test_onyxia_fills_only_actual_remaining_slots_with_her_distinct_whelp(self):
        for board,expected in(((),6),((A,DORMANT,LOCATION),3)):
            g=self.game((ONYXIA,),board=board);before=g.snapshot()['rng_state'];self.play(g,ONYXIA)
            self.assertEqual(self.board(g).count(OWHELP),expected);self.assertNotIn(LWHELP,self.board(g))
            self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_nomi_requires_current_empty_deck_and_six_actual_elementals_obey_capacity(self):
        for deck,board,expected in((('card.1',),(),0),((),(),6),((),(A,A,A),3)):
            g=self.game((NOMI,),deck=deck,board=board);self.play(g,NOMI);self.assertEqual(self.board(g).count(ELEMENTAL),expected)
        self.portable(g)

    def test_flark_uses_four_existing_goblin_bombs_with_their_real_deathrattles(self):
        g=self.game((FLARK,WIPE));self.play(g,FLARK);self.assertEqual(self.board(g).count(BOMB),4)
        self.play(g,WIPE);self.assertEqual(self.hero(g,2).health,22);self.assertFalse(self.board(g));self.portable(g)

    def test_doctor_boom_has_two_actual_boom_bots_and_each_damage_is_one_to_four(self):
        g=self.game((BOOM,KILL,KILL),board=(POWER,));self.play(g,BOOM);self.assertEqual(self.board(g).count(BOT),2)
        amounts=[]
        for _ in range(2):
            before=self.hero(g,2).health;self.play(g,KILL,self.unit(g,BOT).id);amounts.append(before-self.hero(g,2).health)
        self.assertTrue(all(1<=n<=4 for n in amounts));self.assertEqual(self.hero(g).health,30);self.portable(g)

    def test_boom_bot_targets_only_current_enemy_characters(self):
        g=self.game((KILL,),board=(BOT,A,POWER),enemy=(A,))
        before=self.hero(g,2).health+self.unit(g,A,2).health;self.play(g,KILL,self.unit(g,BOT).id)
        self.assertIn(before-self.hero(g,2).health-self.unit(g,A,2).health,range(1,5))
        self.assertEqual((self.hero(g).health,self.unit(g,A).health),(30,40))

    def test_sally_uses_actual_buffed_death_attack_and_not_spell_damage_or_heroes(self):
        g=self.game((BUFF,KILL),board=(SALLY,A,POWER),enemy=(A,A));sid=self.unit(g,SALLY).id
        self.play(g,BUFF,sid);self.play(g,KILL,sid)
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[36,36])
        self.assertEqual((self.hero(g).health,self.hero(g,2).health,self.unit(g,A).health),(30,30,40));self.portable(g)

    def test_live_sally_deathrattle_uses_current_execution_attack_without_removing_carrier(self):
        g=self.game((BUFF,TRIGGER),board=(SALLY,),enemy=(A,));sid=self.unit(g,SALLY).id
        self.play(g,BUFF,sid);self.play(g,TRIGGER,sid);self.assertIn(sid,g.state.players[1].board)
        self.assertEqual(self.unit(g,A,2).health,36);self.portable(g)

    def test_chillmaw_reads_own_execution_hand_dragon_or_all_and_hits_only_active_minions(self):
        for own,other,amount in(((DRAGON,),(),3),((ALL,),(),3),((),(DRAGON,),0)):
            g=self.game((KILL,*own),board=(CHILL,A,DORMANT,LOCATION,POWER),enemy=(A,),enemy_hand=other)
            self.play(g,KILL,self.unit(g,CHILL).id)
            self.assertEqual((self.unit(g,A).health,self.unit(g,A,2).health,self.unit(g,DORMANT).health),(40-amount,40-amount,40))
            self.assertEqual((self.hero(g).health,self.hero(g,2).health),(30,30))
        self.portable(g)

    def test_stolen_chillmaw_uses_current_death_controller_hand(self):
        g=self.game((TAKE,KILL),board=(CHILL,A),enemy=(A,),enemy_hand=(DRAGON,));sid=self.unit(g,CHILL).id
        self.play(g,TAKE,sid);self.play(g,KILL,sid);self.assertEqual((self.unit(g,A).health,self.unit(g,A,2).health),(37,37));self.portable(g)

    def test_nozari_restores_both_actual_heroes_in_one_shared_batch(self):
        g=self.game((HURT,NOZARI),board=(A,),enemy=(A,));self.play(g,HURT)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(22,22));self.play(g,NOZARI)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(30,30));self.portable(g)

    def test_cage_head_creates_exact_charge_taunt_boar_that_can_attack_immediately(self):
        g=self.game((KILL,),board=(CAGE,));self.play(g,KILL,self.unit(g,CAGE).id);boar=self.unit(g,BOAR)
        self.assertEqual((boar.attack,boar.health),(9,9));self.assertIn(Keyword.TAUNT,boar.keywords)
        g.apply(Attack(1,boar.id,self.hero(g,2).id));self.assertEqual(self.hero(g,2).health,21);self.portable(g)

    def test_cage_head_uses_original_death_slot_or_live_carrier_right_side(self):
        for action,expected in((KILL,[A,BOAR,DRAGON]),(TRIGGER,[A,CAGE,BOAR,DRAGON])):
            g=self.game((action,),board=(A,CAGE,DRAGON));self.play(g,action,self.unit(g,CAGE).id)
            self.assertEqual(self.board(g),expected)
        self.portable(g)

    def test_counterpart_death_fact_enables_only_later_surviving_partner(self):
        g=self.game((KILL,KILL),board=(STALAGG,FEUGEN));self.play(g,KILL,self.unit(g,STALAGG).id)
        self.assertNotIn(THADDIUS,self.board(g));self.play(g,KILL,self.unit(g,FEUGEN).id)
        self.assertEqual(self.board(g),[THADDIUS]);self.portable(g)

    def test_simultaneous_partner_deaths_each_see_the_same_complete_death_batch(self):
        g=self.game((WIPE,),board=(STALAGG,FEUGEN));self.play(g,WIPE)
        self.assertEqual(self.board(g),[THADDIUS,THADDIUS]);self.portable(g)

    def test_other_player_counterpart_counts_but_transformed_old_face_does_not(self):
        g=self.game((KILL,KILL),board=(STALAGG,),enemy=(FEUGEN,));self.play(g,KILL,self.unit(g,FEUGEN,2).id)
        self.play(g,KILL,self.unit(g,STALAGG).id);self.assertEqual(self.board(g),[THADDIUS])
        g=self.game((TURN,KILL,KILL),board=(STALAGG,FEUGEN));old=self.unit(g,FEUGEN).id
        self.play(g,TURN,old);self.play(g,KILL,old);self.play(g,KILL,self.unit(g,STALAGG).id);self.assertFalse(self.board(g));self.portable(g)

    def test_plain_named_summon_does_not_invent_onyxia_battlecry(self):
        g=self.game((SUMMON,));self.play(g,SUMMON);self.assertEqual(self.board(g),[ONYXIA]);self.portable(g)

    def test_silence_removes_named_deathrattle_instead_of_running_card_text_again(self):
        for cid in(CHILL,SALLY,CAGE,STALAGG,FEUGEN,BOT):
            g=self.game((HUSH,KILL,DRAGON),board=(cid,),enemy=(A,));sid=self.unit(g,cid).id
            self.play(g,HUSH,sid);self.play(g,KILL,sid);self.assertFalse(self.board(g))
            self.assertEqual((self.unit(g,A,2).health,self.hero(g,2).health),(40,30))

    def test_onyxia_summon_wait_restores_full_original_plan_and_rng_failure_rolls_back(self):
        g=self.game((ONYXIA,),board=(WATCH,));self.play(g,ONYXIA);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);waits=0
        while g.state.pending_choice is not None:self.choose(g);waits+=1
        self.assertEqual((waits,self.board(g).count(OWHELP),g.state.players[1].mana),(5,5,31));self.portable(g)

    def test_boom_bot_damage_wait_keeps_original_random_result_and_recovers_after_fault(self):
        g=self.game((KILL,),board=(BOT,DAMAGEWATCH));self.play(g,KILL,self.unit(g,BOT).id)
        self.assertIsNotNone(g.state.pending_choice);hp=self.hero(g,2).health;self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertEqual(self.hero(g,2).health,hp);self.portable(g)

    def test_second_player_fixed_summons_and_first_player_sources_do_not_swap_owner(self):
        g=self.game((LEEROY,),player=2);self.play(g,LEEROY,player=2)
        self.assertEqual((self.board(g,1),self.board(g,2)),([LWHELP,LWHELP],[LEEROY]));self.portable(g)

    def test_real_standard_host_accepts_paid_leeroy_but_does_not_claim_full_past_source(self):
        self.mode='host';h=host('writer');g=Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=(LEEROY,),deck=('CORE_CS2_182',)*20,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*20,mana=10,max_mana=10)),seed=684,generation_context=h.context),h.registry)
        self.play(g,LEEROY);self.assertEqual(g.state.players[1].mana,10-h.registry.card(LEEROY).cost)
        self.assertEqual(self.board(g,2),[LWHELP,LWHELP]);self.assertNotIn('MIS_701',h.registry.cards);self.portable(g)
