"""Real original entries; shared conditional prices, resources and health pipelines."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from test_past_shaman_nature_common import fixture as common_fixture,TOTEM,ALL,HURT,HURTHERO,SPAWN,TOKEN
from test_past_hunter_nature_leaves import A,B,DORMANT,POWER,DRAGON,NOOP
from hs_sim.cards import past_shaman_nature_resources as native
from hs_sim.cards.native_split_healing_cards import register_native_split_healing_cards
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import ChoiceOption,InvokeBehavior,RandomDamage,RequestChoice
from hs_sim.engine.model import CardClass,CardDefinition,CardType,TriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

ZAP,SHOCK,MIGHT,FUSION,DIG,SLIDE,TORRENT,BREATH,POTION,GIFTS,RAIN=native.ROOTS
P='k672.';ELEMENTAL,NAGA,SPELL,WATCH,FAIL=(P+x for x in('elemental','naga','spell','watch','fail'))
CTX=GenerationContext('k672-complete-three-card-fixture','experimental')


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=common_fixture('k672-'+role);register_native_split_healing_cards(r);native.register_past_shaman_nature_resources(r)
    for cid,cost,tribe in((ELEMENTAL,3,'elemental'),(NAGA,5,'naga')):
        card=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=2,health=7,metadata=metadata(tribes=(tribe,)))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_behavior(SPELL,lambda c:())
    card=CardDefinition(SPELL,SPELL,CardType.SPELL,cost=4,on_play=SPELL,metadata=metadata(CardClass.MAGE))
    r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_pool(PoolDefinition('constructed.cards','k672-three-complete-faces',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in(ELEMENTAL,NAGA,SPELL)),complete=True))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K672 deliberate rollback')))
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=TORRENT:return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,triggers=(TriggerSpec('damage_dealt',WATCH),),metadata=metadata(collectible=False)))
    r.validate();return r


class ShamanNatureResourcesTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(),watch=False):
        self.mode='small';board=board+((WATCH,)if watch else())
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=('card.1',)*18,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',board=enemy,deck=('card.2',)*18,mana=10,max_mana=10)),seed=672,generation_context=CTX),fixture())
    def hero(self,g,player=1):return g.state.entities[g.state.players[player].hero_id]
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def finish(self,g):
        count=0
        while g.state.pending_choice is not None:
            self.choose(g,g.state.pending_choice.options[0].id);count+=1;self.assertLess(count,15)

    def test_all_eleven_complete_original_faces_two_existing_pins_and_primary_zero_costs(self):
        d=native.load_batch();r=fixture()
        self.assertEqual((len(d['cards']),len(d['existing_dependencies']),len(d['official_observations'])),(11,2,26))
        self.assertEqual(len(d['original_shaman_member_ids']),71);self.assertFalse(d['complete_shaman_source_bound'])
        for row in d['cards']:
            cid=row['record']['id'];self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(r.pool_card(cid))),row['pool_card_sha256'])
        self.assertEqual((r.card(ZAP).cost,r.card(SHOCK).cost),(0,0))

    def test_ten_original_hand_entries_pay_once_and_dig_uses_separate_real_host_entry(self):
        for cid in native.ROOTS:
            if cid==DIG:continue
            with self.subTest(card=cid):
                g=self.game((cid,),board=(A,TOTEM),enemy=(B,));before=g.state.players[1].mana
                target=self.hero(g).id if cid==POTION else self.entity(g,B,2,'board').id if cid in native.TARGETED else None
                self.play(g,cid,target);self.finish(g)
                self.assertEqual(g.state.players[1].mana,before-g.registry.card(cid).cost)
                self.assertEqual([r.card_id for r in g.state.cast_history],[cid])
                self.assertEqual(sum(r.amount for r in g.state.overload_history),native.OVERLOAD.get(cid,0))

    def test_zap_both_sides_spell_damage_no_heroes_or_dormant_and_actual_overload(self):
        g=self.game((ZAP,),board=(A,POWER,DORMANT),enemy=(B,));self.play(g,ZAP)
        self.assertEqual(self.entity(g,A,zone='board').health,5);self.assertEqual(self.entity(g,B,2,'board').health,27)
        self.assertEqual(self.entity(g,DORMANT,zone='board').health,8)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(30,30));self.assertEqual(sum(r.amount for r in g.state.overload_history),2)
        self.cycle(g);self.assertEqual(g.state.players[1].mana,8);self.portable(g)

    def test_zero_cost_zap_keeps_real_target_damage_and_next_turn_one_crystal_lock(self):
        g=self.game((SHOCK,),board=(POWER,),enemy=(B,));self.play(g,SHOCK,self.entity(g,B,2,'board').id)
        self.assertEqual(self.entity(g,B,2,'board').health,26);self.assertEqual(g.state.players[1].mana,10)
        self.cycle(g);self.assertEqual(g.state.players[1].mana,9);self.portable(g)

    def test_all_printed_minion_targets_reject_hero_atomically_before_payment_or_excavation(self):
        for cid in(SHOCK,MIGHT,FUSION,DIG,TORRENT,BREATH):
            with self.subTest(card=cid):
                g=self.game((cid,));saved=deepcopy(g.snapshot())
                with self.assertRaises(IllegalAction):self.play(g,cid,self.hero(g,2).id)
                self.assertEqual(g.snapshot(),saved)

    def test_landslide_without_owed_or_locked_has_one_enemy_only_pulse(self):
        g=self.game((SLIDE,),board=(A,),enemy=(B,));self.play(g,SLIDE)
        self.assertEqual(self.entity(g,B,2,'board').health,29);self.assertEqual(self.entity(g,A,zone='board').health,8)

    def test_landslide_owed_condition_requeries_second_pulse_after_real_deathrattle(self):
        g=self.game((SHOCK,SLIDE),board=(A,),enemy=(SPAWN,));self.play(g,SHOCK,self.entity(g,A,zone='board').id)
        self.play(g,SLIDE);self.assertEqual([g.state.entities[e].card_id for e in g.state.players[2].board],[TOKEN])
        self.assertEqual(self.entity(g,TOKEN,2,'board').health,7);self.portable(g)

    def test_landslide_also_qualifies_actual_locked_crystal_without_new_owed_debt(self):
        g=self.game((SHOCK,SLIDE),board=(A,),enemy=(B,));self.play(g,SHOCK,self.entity(g,A,zone='board').id);self.cycle(g)
        self.assertEqual((g.state.players[1].overload_owed,g.state.players[1].overload_locked),(0,1))
        self.play(g,SLIDE);self.assertEqual(self.entity(g,B,2,'board').health,28);self.assertEqual(g.state.players[1].mana,7)

    def test_torrent_original_four_cost_and_previous_own_cast_actual_one_mana_payment(self):
        g=self.game((TORRENT,),enemy=(B,));self.play(g,TORRENT,self.entity(g,B,2,'board').id)
        self.assertEqual((g.state.players[1].mana,self.entity(g,B,2,'board').health),(6,22))
        g=self.game((NOOP,TORRENT),enemy=(B,));self.play(g,NOOP);self.cycle(g)
        self.play(g,TORRENT,self.entity(g,B,2,'board').id)
        self.assertEqual((g.state.players[1].mana,self.entity(g,B,2,'board').health),(9,22));self.portable(g)

    def test_torrent_current_turn_cast_does_not_replace_previous_own_interval(self):
        g=self.game((NOOP,TORRENT),enemy=(B,));self.play(g,NOOP);self.play(g,TORRENT,self.entity(g,B,2,'board').id)
        self.assertEqual(g.state.players[1].mana,6)

    def test_discounted_torrent_wait_preserves_price_health_and_rng_rollback(self):
        g=self.game((NOOP,TORRENT),enemy=(B,),watch=True);self.play(g,NOOP);self.cycle(g)
        self.play(g,TORRENT,self.entity(g,B,2,'board').id);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].mana,9);self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.finish(g);self.assertEqual(self.entity(g,B,2,'board').health,22);self.portable(g)

    def test_earthen_might_current_elemental_or_all_qualifies_real_reward_and_normal_does_not(self):
        for cid,qualified in((ELEMENTAL,True),(ALL,True),(A,False)):
            with self.subTest(card=cid):
                g=self.game((MIGHT,),enemy=(cid,));target=self.entity(g,cid,2,'board');atk,hp=target.attack,target.health
                self.play(g,MIGHT,target.id);self.assertEqual((g.state.entities[target.id].attack,g.state.entities[target.id].health),(atk+2,hp+2))
                self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].hand],[ELEMENTAL]if qualified else[])

    def test_primal_fusion_counts_only_friendly_active_current_totems_including_all(self):
        g=self.game((FUSION,),board=(TOTEM,ALL,DORMANT),enemy=(B,TOTEM));target=self.entity(g,B,2,'board').id
        self.play(g,FUSION,target);self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(4,32));self.portable(g)

    def test_primal_fusion_empty_totem_count_is_no_bonus_and_does_not_consume_rng(self):
        g=self.game((FUSION,),enemy=(B,));saved=g.snapshot()['rng_state'];self.play(g,FUSION,self.entity(g,B,2,'board').id)
        self.assertEqual(self.entity(g,B,2,'board').health,30);self.assertEqual(g.snapshot()['rng_state'],saved)

    def test_lightning_breath_held_dragon_hits_only_original_immediate_neighbors(self):
        g=self.game((BREATH,DRAGON),enemy=(A,B,A,B));board=list(g.state.players[2].board);self.play(g,BREATH,board[1])
        self.assertEqual([g.state.entities[e].health for e in board],[4,26,4,30]);self.portable(g)
        g=self.game((BREATH,),enemy=(A,B,A));board=list(g.state.players[2].board);self.play(g,BREATH,board[1])
        self.assertEqual([g.state.entities[e].health for e in board],[8,26,8])

    def test_amphibious_heals_first_then_real_spell_discovery_wait_restores(self):
        g=self.game((HURTHERO,POTION));self.play(g,HURTHERO);self.play(g,POTION,self.hero(g).id)
        self.assertEqual(self.hero(g).health,15);self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        self.finish(g);self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].hand],[SPELL]);self.portable(g)

    def test_natural_talent_delivers_real_naga_and_spell_each_with_actual_minus_two_price(self):
        g=self.game((GIFTS,));self.play(g,GIFTS)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].hand],[NAGA,SPELL])
        self.play(g,NAGA);self.play(g,SPELL);self.assertEqual(g.state.players[1].mana,2)
        self.assertEqual((g.registry.card(NAGA).cost,g.registry.card(SPELL).cost),(5,4));self.portable(g)

    def test_original_healing_rain_keeps_twelve_immune_units_and_core_face_unchanged(self):
        g=self.game((HURTHERO,HURT,RAIN),board=(A,POWER));self.play(g,HURTHERO);self.play(g,HURT,self.entity(g,A,zone='board').id)
        before=self.hero(g).health+sum(g.state.entities[e].health for e in g.state.players[1].board)
        self.play(g,RAIN);after=self.hero(g).health+sum(g.state.entities[e].health for e in g.state.players[1].board)
        self.assertEqual(after-before,12);self.assertEqual(g.state.cast_history[-1].card_id,RAIN)
        self.assertEqual(g.registry.card('CORE_LOOT_373').id,'CORE_LOOT_373');self.portable(g)

    def test_real_standard_dig_pays_four_each_advances_all_tiers_and_actual_shaman_reward(self):
        self.mode='host';h=host();deck=('CORE_EX1_169',)*16
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_02',hand=(DIG,)*4,deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=('LOOT_077t',)*4,deck=deck,mana=10,max_mana=10)),seed=672,generation_context=h.context),h.registry)
        sources=[]
        for i in range(4):
            if i==2:self.cycle(g)
            mana=g.state.players[1].mana;source=self.play(g,DIG,g.state.players[2].board[0]);sources.append(source)
            self.assertEqual(g.state.players[1].mana,mana-4)
        self.assertEqual(g.state.players[2].board,[])
        self.assertEqual([r.tier for r in g.state.excavation_history],[1,2,3,4])
        self.assertEqual([r.source_id for r in g.state.excavation_history],sources)
        self.assertEqual(g.state.excavation_history[-1].hero_class,CardClass.SHAMAN)
        self.assertIn(g.state.excavation_history[-1].card_id,[g.state.entities[e].card_id for e in g.state.players[1].hand]);self.portable(g)

    def test_real_standard_generators_use_complete_current_host_views_and_discovery_recovers(self):
        self.mode='host';h=host();deck=('CORE_EX1_169',)*16
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_02',hand=(GIFTS,POTION),deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=deck,mana=10,max_mana=10)),seed=672,generation_context=h.context),h.registry)
        self.play(g,GIFTS);self.assertEqual(len(g.state.players[1].hand),3)
        self.play(g,POTION,self.hero(g).id);self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        self.finish(g);self.assertEqual(g.state.players[1].mana,5);self.assertEqual(len(g.state.players[1].hand),3);self.portable(g)
