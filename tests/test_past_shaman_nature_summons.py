"""Real Shaman summons, source-bound material, portals and strict source display."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_past_hunter_nature_leaves import fixture as leaf_fixture,A,B,WEAK,KILL
from opening_fixtures import metadata
from tools import card_batch as cb
from hs_sim.cards import build_registry,past_shaman_nature_summons as native
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import ChoiceOption,InvokeBehavior,RandomDamage,RequestChoice,Summon
from hs_sim.engine.jade import CLASSIC
from hs_sim.engine.model import CardDefinition,CardType,Keyword,TriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.local_pool_format import build_cn37_local_pool_format

P='k671.'
THREE,HIGH,WATCH,FAIL,SPAWN,TOKEN=(P+x for x in('three','high','watch','fail','spawn','token'))
SPARKS,WOLVES,COMMAND,TURNS,BOOK,EYE,WEED,JADE,JADE2,HEX,SERPENT,MAELSTROM,DUNK=native.ROOTS
CTX=GenerationContext('k671-native-tokens','experimental')


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def materials():
    r=build_registry();ids=[cid for cid in native.EXISTING if cid!='TIME_013']
    return r.jade_families[CLASSIC],tuple((r.card(cid),r.pool_card(cid))for cid in ids)


@lru_cache(None)
def fixture(role='writer'):
    r=leaf_fixture('k671-'+role);family,tokens=materials()
    for card,pool in tokens:
        r.register_card(card);r.register_pool_card(pool)
    r.register_jade_family(family);native.register_past_shaman_nature_summons(r)
    r.register_card(CardDefinition(THREE,THREE,CardType.MINION,cost=3,attack=3,health=7,metadata=metadata(tribes=())))
    r.register_pool_card(PoolCard.from_definition(r.card(THREE)))
    r.register_pool(PoolDefinition('constructed.cards','k671-complete-cost-one-and-three-fixture',CTX.target_id,CTX.mode,
        (PoolMember(A),PoolMember(THREE)),complete=True))
    r.register_behavior(HIGH,lambda c:())
    r.register_card(CardDefinition(HIGH,HIGH,CardType.SPELL,cost=6,on_play=HIGH,metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(TOKEN,TOKEN,CardType.MINION,attack=1,health=8,metadata=metadata(tribes=())))
    r.register_behavior(SPAWN,lambda c:(Summon(c.player_id,TOKEN),))
    r.register_card(CardDefinition(SPAWN,SPAWN,CardType.MINION,attack=1,health=1,deathrattle=SPAWN,metadata=metadata(tribes=())))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K671 deliberate rollback')))
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=BOOK:return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,triggers=(TriggerSpec('damage_dealt',WATCH),),metadata=metadata(collectible=False)))
    r.validate();return r


class ShamanNatureSummonsTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(),watch=False):
        self.mode='small';board=board+((WATCH,)if watch else())
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=('card.1',)*18,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',board=enemy,deck=('card.2',)*18,mana=10,max_mana=10)),seed=671,generation_context=CTX),fixture())

    def hero(self,g,player=1):return g.state.entities[g.state.players[player].hero_id]
    def ids(self,g,player=1):return[g.state.entities[eid].card_id for eid in g.state.players[player].board]
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def finish(self,g):
        count=0
        while g.state.pending_choice is not None:
            self.choose(g,g.state.pending_choice.options[0].id);count+=1;self.assertLess(count,12)

    def test_all_complete_native_faces_existing_dependencies_and_jade_artwork_pins(self):
        d=native.load_batch();r=fixture();native.checked_existing(r,d)
        self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['existing_dependencies']),len(d['official_observations'])),(13,5,8,52))
        for row in d['cards']+d['dependencies']:
            cid=row['record']['id'];self.assertEqual(cb.canonical(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(cb.canonical(asdict(r.pool_card(cid))),row['pool_card_sha256'])
        self.assertEqual(len(d['original_shaman_member_ids']),71);self.assertFalse(d['complete_shaman_source_bound'])

    def test_all_thirteen_spells_really_enter_from_hand_and_pay_original_cost_once(self):
        for cid in native.ROOTS:
            with self.subTest(card=cid):
                g=self.game((cid,),enemy=(B,));card=g.registry.card(cid)
                target=self.entity(g,B,2,'board').id if cid in native.TARGETED else None
                self.play(g,cid,target)
                self.assertEqual(g.state.players[1].mana,10-card.cost)
                self.assertEqual([v.card_id for v in g.state.cast_history],[cid])
                self.assertEqual(sum(v.amount for v in g.state.overload_history),native.OVERLOAD.get(cid,0))

    def test_all_five_new_dependency_faces_have_real_paid_hand_entries(self):
        for cid in native.DEPENDENCIES:
            with self.subTest(card=cid):
                g=self.game((cid,),enemy=(B,));target=self.entity(g,B,2,'board').id if cid=='DMF_701t'else None
                self.play(g,cid,target);self.assertEqual(g.state.players[1].mana,10-g.registry.card(cid).cost)
                if cid!='DMF_701t':self.assertIn(cid,self.ids(g))

    def test_fixed_summons_have_exact_real_id_count_and_printed_keywords(self):
        for cid in(SPARKS,WOLVES,COMMAND,EYE):
            with self.subTest(card=cid):
                g=self.game((cid,));self.play(g,cid);token,count=native.FIXED[cid]
                self.assertEqual(self.ids(g),[token]*count)
                expected=Keyword.RUSH if cid in(SPARKS,COMMAND)else Keyword.TAUNT
                self.assertTrue(all(expected in g.state.entities[eid].keywords for eid in g.state.players[1].board))

    def test_named_summon_capacity_never_evicts_or_allocates_overflow_but_keeps_overload(self):
        g=self.game((EYE,),board=(A,)*6);before=g.state.next_entity_id;self.play(g,EYE)
        self.assertEqual(self.ids(g),[A]*6+['YOD_041t']);self.assertEqual(g.state.next_entity_id,before+1)
        self.assertEqual(g.state.players[1].mana,0);self.assertEqual(sum(v.amount for v in g.state.overload_history),3)
        self.cycle(g);self.assertEqual(g.state.players[1].mana,7);self.portable(g)

    def test_real_rush_spark_cannot_attack_hero_but_can_attack_enemy_minion_immediately(self):
        g=self.game((SPARKS,),enemy=(B,));self.play(g,SPARKS);spark=g.state.players[1].board[0]
        saved=deepcopy(g.snapshot())
        with self.assertRaises(IllegalAction):g.apply(Attack(1,spark,self.hero(g,2).id))
        self.assertEqual(g.snapshot(),saved);g.apply(Attack(1,spark,self.entity(g,B,2,'board').id))
        self.assertEqual(self.entity(g,B,2,'board').health,29)

    def test_turn_the_tides_grants_hero_attack_until_end_and_real_rush_elemental(self):
        g=self.game((TURNS,));self.play(g,TURNS)
        self.assertEqual(self.hero(g).attack,3);self.assertEqual(self.ids(g),['TTN_833t'])
        self.assertEqual((self.entity(g,'TTN_833t',zone='board').attack,self.entity(g,'TTN_833t',zone='board').health),(3,3))
        g.apply(EndTurn(1));self.assertEqual(self.hero(g).attack,0);self.portable(g)

    def test_pop_up_book_damage_precedes_capacity_and_creates_actual_zero_one_frogs(self):
        g=self.game((BOOK,),board=(WEAK,)+(A,)*6);old=self.entity(g,WEAK,zone='board').id
        self.play(g,BOOK,old);self.assertEqual(self.ids(g),[A]*6+['hexfrog'])
        frog=self.entity(g,'hexfrog',zone='board');self.assertEqual((frog.attack,frog.health),(0,1));self.assertIn(Keyword.TAUNT,frog.keywords)
        self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_damage_waiting_preserves_original_summon_material_payment_and_rng_rollback(self):
        g=self.game((BOOK,),enemy=(B,),watch=True);self.play(g,BOOK,self.entity(g,B,2,'board').id)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.ids(g),[WATCH]);self.portable(g)
        saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.finish(g)
        self.assertEqual(self.ids(g),[WATCH,'hexfrog','hexfrog']);self.assertEqual(g.state.players[1].mana,9);self.portable(g)

    def test_tumbleweed_damage_frees_own_slot_before_real_six_six_summon(self):
        g=self.game((WEED,),board=(WEAK,)*7,enemy=(B,));self.play(g,WEED)
        self.assertEqual(self.ids(g),['WW_090t']);self.assertEqual(self.entity(g,B,2,'board').health,24)
        self.assertEqual((self.entity(g,'WW_090t',zone='board').attack,self.entity(g,'WW_090t',zone='board').health),(6,6));self.portable(g)

    def test_two_distinct_jade_spells_share_growth_once_and_original_source_id(self):
        g=self.game((JADE,JADE2,JADE,JADE2),enemy=(B,));target=self.entity(g,B,2,'board').id;first=self.play(g,JADE,target);second=self.play(g,JADE2,target)
        self.assertEqual([r.size for r in g.state.jade_history],[1,2]);self.assertEqual([r.source_id for r in g.state.jade_history],[first,second])
        self.assertEqual(g.state.entities[target].health,24);self.play(g,JADE,target);self.cycle(g);self.play(g,JADE2,target)
        self.assertEqual([g.state.entities[eid].jade_size for eid in g.state.players[1].board],[1,2,3,4])
        self.assertEqual(g.state.entities[g.state.players[1].board[-1]].card_id,'CFM_712_t04');self.portable(g)

    def test_full_board_jade_attempt_uses_existing_growth_policy_without_evicting(self):
        g=self.game((JADE,),board=(A,)*7,enemy=(B,));before=g.state.next_entity_id;self.play(g,JADE,self.entity(g,B,2,'board').id)
        self.assertEqual(self.ids(g),[A]*7);self.assertEqual(g.state.next_entity_id,before)
        self.assertEqual([v.size for v in g.state.jade_history],[1]);self.assertEqual(self.entity(g,B,2,'board').health,27)

    def test_hex_transforms_original_entity_to_real_frog_without_death(self):
        g=self.game((HEX,),enemy=(B,));target=self.entity(g,B,2,'board').id;self.play(g,HEX,target)
        self.assertEqual(g.state.entities[target].card_id,'hexfrog');self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(0,1))
        self.assertEqual(g.state.players[2].board,[target]);self.assertEqual(g.state.death_history,[])
        self.assertIn(Keyword.TAUNT,g.state.entities[target].keywords);self.portable(g)

    def test_portals_use_complete_current_diagnostic_cost_pools_and_no_extra_hand_delivery(self):
        g=self.game((SERPENT,MAELSTROM),enemy=(B,));self.play(g,SERPENT,self.entity(g,B,2,'board').id);self.play(g,MAELSTROM)
        self.assertEqual(self.ids(g),[THREE,A]);self.assertEqual(self.entity(g,B,2,'board').health,26)
        self.assertEqual(g.state.players[1].hand,[]);self.assertEqual(g.state.players[1].mana,5);self.portable(g)

    def test_corrupt_preserves_real_hand_identity_then_damage_and_fresh_enemy_area(self):
        g=self.game((DUNK,HIGH),enemy=(B,A));original=self.entity(g,DUNK).id;self.play(g,HIGH)
        self.assertEqual(g.state.entities[original].card_id,'DMF_701t');self.assertIn(Keyword.CORRUPTED,g.state.entities[original].keywords)
        self.play(g,'DMF_701t',self.entity(g,B,2,'board').id)
        self.assertEqual((self.entity(g,B,2,'board').health,self.entity(g,A,2,'board').health),(24,6))
        self.assertEqual(g.state.players[1].mana,0);self.portable(g)

    def test_corrupted_area_hits_new_deathrattle_body_after_primary_damage(self):
        g=self.game(('DMF_701t',),enemy=(SPAWN,));self.play(g,'DMF_701t',self.entity(g,SPAWN,2,'board').id)
        self.assertEqual(self.ids(g,2),[TOKEN]);self.assertEqual(self.entity(g,TOKEN,2,'board').health,6)

    def test_uncorrupted_dunk_has_only_original_four_damage(self):
        g=self.game((DUNK,),enemy=(B,A));self.play(g,DUNK,self.entity(g,B,2,'board').id)
        self.assertEqual((self.entity(g,B,2,'board').health,self.entity(g,A,2,'board').health),(26,8))

    def test_hex_rejects_hero_and_damage_spells_accept_hero_without_an_arrow_to_locations(self):
        g=self.game((HEX,),enemy=(B,));saved=deepcopy(g.snapshot())
        with self.assertRaises(IllegalAction):self.play(g,HEX,self.hero(g,2).id)
        self.assertEqual(g.snapshot(),saved)
        for cid,damage in((BOOK,2),(JADE,3),(JADE2,3),(SERPENT,3),(DUNK,4)):
            with self.subTest(card=cid):
                g=self.game((cid,));self.play(g,cid,self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,30-damage)

    def test_real_standard_host_both_portals_pay_and_summon_from_actual_complete_cost_views(self):
        self.mode='host';h=host();deck=('CORE_EX1_169',)*15
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_02',hand=(SERPENT,MAELSTROM),deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=('LOOT_077t',),deck=deck,mana=10,max_mana=10)),seed=671,generation_context=h.context),h.registry)
        self.play(g,SERPENT,g.state.players[2].board[0]);self.assertTrue(any(g.registry.card(g.state.entities[eid].card_id).cost==3 for eid in g.state.players[1].board))
        self.play(g,MAELSTROM);self.assertTrue(any(g.registry.card(g.state.entities[eid].card_id).cost==1 for eid in g.state.players[1].board))
        self.assertEqual(g.state.players[1].mana,5);self.assertEqual(sum(r.amount for r in g.state.overload_history),1);self.portable(g)


class JadeLightningSourceDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        b=Path('outputs/card-integration-20261014/k671-shaman-nature-summons')
        cls.task=cb.read(b/'manifest-02.json');cls.rows=cb.pinned_rows(cls.task)
        cls.index=cb.catalog_index(cls.task['official_catalogs'],Path.cwd())

    def verify(self,cid,locale,*,row=None,face=None,normalization=None):
        r=self.rows[cid]if row is None else row;f=self.index[(locale,self.rows[cid]['dbf_id'])]['face']if face is None else face
        cb.check_face(r,f,locale,self.task['display_normalizations'][cid]if normalization is None else normalization)

    def test_all_four_complete_primary_faces_match_pinned_original_equivalent_bodies(self):
        for cid in('CFM_707','WON_082'):
            for locale in('zh_CN','en_US'):self.verify(cid,locale)

    def test_changed_damage_or_changed_alternate_body_cannot_use_display_projection(self):
        for cid in('CFM_707','WON_082'):
            for locale in('zh_CN','en_US'):
                with self.subTest(card=cid,locale=locale):
                    row=deepcopy(self.rows[cid]);key='text'if locale=='zh_CN'else'text_en';row[key]=row[key].replace('$3','$4',1)
                    with self.assertRaises(ValueError):self.verify(cid,locale,row=row)

    def test_changed_primary_number_and_unreviewed_marker_are_rejected(self):
        for cid in('CFM_707','WON_082'):
            face=deepcopy(self.index[('en_US',self.rows[cid]['dbf_id'])]['face']);face['text']=face['text'].replace('3','4')
            with self.assertRaises(ValueError):self.verify(cid,'en_US',face=face)
            with self.assertRaises(ValueError):self.verify(cid,'zh_CN',normalization={'{0}':'','3':'4'})

    def test_other_identity_cannot_borrow_exact_jade_lightning_source_rules(self):
        for cid in('CFM_707','WON_082'):
            row=deepcopy(self.rows[cid]);row['id']=cid+'.unreviewed'
            with self.assertRaises(ValueError):self.verify(cid,'zh_CN',row=row)
