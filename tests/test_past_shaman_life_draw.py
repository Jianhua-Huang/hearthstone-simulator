"""Actual original life/draw cards through shared copies, clocks and draw-casts."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from test_past_shaman_nature_common import fixture as common_fixture,HURTHERO,SPAWN,TOKEN
from test_past_hunter_nature_leaves import A,B,DORMANT,POWER,KILL,HUSH,WEAK
from hs_sim.cards import past_shaman_life_draw as native
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.copy_materials import CopyEntryMaterial
from hs_sim.engine.crafted_faces import CraftedMinionBlueprint,CraftedMinionRecipe
from hs_sim.engine.effects import AddCostModifier,Buff,ChoiceOption,Damage,Draw,InvokeBehavior,RandomDamage,RequestChoice,TriggerDeathrattles
from hs_sim.engine.model import CardAbilityCondition,CardDefinition,CardType,CostSpec,Keyword,PlayerEffectSpec,SpellEffectModifierSpec,SpellSchool,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

REINCARNATE,REINCARNATE2,SPORES,ECHO,BREW,ONCE,REACTION,FLASH,METEOR=native.ROOTS
ASTEROID=native.DEPENDENCIES[0]
P='k674.'
ELEMENTAL,ALL,BEAST3,DRAGON3,ELEMENTAL3,MURLOC3,ALL3,NATURE,FIRE,GROW,TRIGGER,DRAW,DISCOUNT,SUMMON_E,WATCH,FAIL,TEMPLATE,PART1,PART2,BOOST,BOOST_SPEC=(P+x for x in('elemental','all','beast3','dragon3','elemental3','murloc3','all3','nature','fire','grow','trigger','draw','discount','summon-e','watch','fail','template','part1','part2','boost','boost-spec'))
CRAFT=CraftedMinionRecipe(TEMPLATE,PART1,PART2).card_id
CTX=GenerationContext('k674-complete-four-tribe-fixture','experimental')
FILL=P+'fill'


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=common_fixture('k674-'+role);native.register_past_shaman_life_draw(r)
    for cid,cost,tribes,attack,hp in((ELEMENTAL,1,('elemental',),1,4),(ALL,1,('all',),1,4),
            (BEAST3,3,('beast',),2,6),(DRAGON3,3,('dragon',),2,6),(ELEMENTAL3,3,('elemental',),2,6),(MURLOC3,3,('murloc',),2,6),(ALL3,3,('all',),2,6),
            (TEMPLATE,0,('beast','undead'),0,1),(PART1,1,('beast',),2,3),(PART2,2,('undead',),1,4)):
        card=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=hp,metadata=metadata(tribes=tribes,collectible=cid!=TEMPLATE))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_crafted_minion_blueprint(CraftedMinionBlueprint(TEMPLATE,'beast','undead'))
    r.register_crafted_minion_part(PART1);r.register_crafted_minion_part(PART2)
    members=(ALL3,)if role.startswith('all-')else(BEAST3,DRAGON3,ELEMENTAL3,MURLOC3)
    r.register_pool(PoolDefinition('constructed.cards','k674-full-four-tribes',CTX.target_id,CTX.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    r.register_player_effect(PlayerEffectSpec(BOOST_SPEC,BOOST,spell_effects=(SpellEffectModifierSpec((ASTEROID,),value_add=1),)))
    from hs_sim.engine.effects import Summon
    scripts={NATURE:lambda c:(),FIRE:lambda c:(),GROW:lambda c:(Buff(c.target_id,5,5,source_id=c.source_id),),
        TRIGGER:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),
        DISCOUNT:lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-2,card_types=(CardType.SPELL,)),source_id=c.source_id),),
        SUMMON_E:lambda c:(Summon(c.player_id,ELEMENTAL),),BOOST:lambda c:(AddPlayerEffect(c.player_id,BOOST_SPEC,c.source_id),),
        FILL:lambda c:(Draw(c.player_id,3,c.source_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);fields={}
        if cid in(GROW,TRIGGER):fields['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=2 if cid in(NATURE,FIRE)else 0,on_play=cid,
            spell_school=SpellSchool.NATURE if cid==NATURE else SpellSchool.FIRE if cid==FIRE else None,
            metadata=metadata(collectible=False),**fields))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K674 deliberate rollback')))
    def watch(c):
        if c.event.kind=='minion_died':
            death=next(d for d in c.state.death_history if d.id==dict(c.event.data)['death_id'])
            enabled=death.cause.source_card_id in(REINCARNATE,REINCARNATE2)
        else:
            source=c.state.entities.get(c.event.source_id);enabled=source is not None and source.card_id==METEOR
        if not enabled:return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,
        triggers=(TriggerSpec('minion_died',WATCH),TriggerSpec('damage_dealt',WATCH)),metadata=metadata(collectible=False,tribes=())))
    r.validate();return r


class ShamanLifeDrawTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(('all-'if mode=='all'else'')+role))
    def game(self,hand=(),*,board=(),enemy=(),deck=(NATURE,)*10,enemy_deck=(FIRE,)*10,all_pool=False):
        self.mode='all'if all_pool else'small';role='all-writer'if all_pool else'writer'
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',board=enemy,deck=enemy_deck,mana=10,max_mana=10)),seed=674,generation_context=CTX),fixture(role))
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def ids(self,g,p=1,zone='hand'):return[g.state.entities[e].card_id for e in getattr(g.state.players[p],zone)]
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def finish(self,g):
        n=0
        while g.state.pending_choice is not None:
            self.choose(g,g.state.pending_choice.options[0].id);n+=1;self.assertLess(n,25)

    def test_ten_complete_native_faces_and_twenty_two_primary_faces(self):
        d=native.load_batch();r=fixture('writer');self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['official_observations'])),(9,1,22))
        for row in d['cards']+d['dependencies']:
            cid=row['record']['id'];self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(r.pool_card(cid))),row['pool_card_sha256'])
        self.assertFalse(r.card(BREW).hand_repeat.echo);self.assertNotIn(Keyword.ECHO,r.card(BREW).keywords)
        self.assertIsNotNone(r.card(ASTEROID).cast_when_drawn);self.assertIsNone(r.card(ASTEROID).spell_school)

    def test_all_nine_real_root_hand_entries_pay_original_cost_once(self):
        for cid in native.ROOTS:
            with self.subTest(card=cid):
                g=self.game((cid,),board=(A,),enemy=(B,));target=self.hero(g).id if cid==BREW else g.state.players[2].board[0]if cid in(REINCARNATE,REINCARNATE2)else None
                self.play(g,cid,target);self.finish(g);self.assertEqual(g.state.players[1].mana,10-g.registry.card(cid).cost)
                self.assertEqual([c.card_id for c in g.state.cast_history],[cid])

    def test_reincarnate_both_original_faces_reset_buffs_and_summon_fresh_original_enemy_body(self):
        for cid in(REINCARNATE,REINCARNATE2):
            g=self.game((GROW,cid),enemy=(A,));old=g.state.players[2].board[0];self.play(g,GROW,old);self.play(g,cid,old)
            fresh=g.state.entities[g.state.players[2].board[0]]
            self.assertNotEqual(fresh.id,old);self.assertEqual((fresh.card_id,fresh.attack,fresh.health,fresh.origin_entity_id),(A,2,8,old))
            self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_reincarnate_retains_original_dynamic_composition_but_drops_ordinary_buffs(self):
        g=self.game((CRAFT,GROW,REINCARNATE));self.play(g,CRAFT);old=g.state.players[1].board[0]
        self.play(g,GROW,old);self.play(g,REINCARNATE,old);fresh=g.state.entities[g.state.players[1].board[0]]
        self.assertEqual((fresh.card_id,fresh.components,fresh.attack,fresh.health),(CRAFT,(PART1,PART2),3,7));self.portable(g)

    def test_reincarnate_deathrattle_fills_last_slot_before_return_and_has_no_overflow_entity(self):
        g=self.game((REINCARNATE,),enemy=(A,)*6+(SPAWN,));old=g.state.players[2].board[-1];next_id=g.state.next_entity_id
        self.play(g,REINCARNATE,old);self.assertEqual(self.ids(g,2,'board'),[A]*6+[TOKEN])
        self.assertEqual(g.state.next_entity_id,next_id+1);self.assertNotIn(SPAWN,self.ids(g,2,'board'));self.portable(g)

    def test_reincarnate_waiting_preserves_printed_material_and_failed_resume_rng(self):
        g=self.game((REINCARNATE,),board=(A,),enemy=(WATCH,));old=g.state.players[1].board[0];self.play(g,REINCARNATE,old)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.players[1].board,[]);self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.finish(g);self.assertEqual(self.ids(g,zone='board'),[A]);self.portable(g)

    def test_living_spores_natural_death_returns_base_without_regranting_spores(self):
        g=self.game((GROW,SPORES,KILL,KILL),board=(A,));old=g.state.players[1].board[0];self.play(g,GROW,old);self.play(g,SPORES);self.play(g,KILL,old)
        fresh=g.state.entities[g.state.players[1].board[0]];self.assertEqual((fresh.card_id,fresh.attack,fresh.health),(A,2,8))
        self.assertFalse(any(a.kind=='deathrattle'and not a.consumed for a in fresh.abilities));self.play(g,KILL,fresh.id)
        self.assertEqual(g.state.players[1].board,[]);self.portable(g)

    def test_two_actual_spores_grants_each_resummon_once_and_live_trigger_preserves_original(self):
        g=self.game((SPORES,SPORES,KILL),board=(A,));old=g.state.players[1].board[0];self.play(g,SPORES);self.play(g,SPORES);self.play(g,KILL,old)
        self.assertEqual(self.ids(g,zone='board'),[A,A]);self.portable(g)
        g=self.game((SPORES,TRIGGER),board=(A,));old=g.state.players[1].board[0];self.play(g,SPORES);self.play(g,TRIGGER,old)
        self.assertEqual(self.ids(g,zone='board'),[A,A]);self.assertIn(old,g.state.players[1].board);self.assertEqual(g.state.death_history,[]);self.portable(g)

    def test_spirit_echo_moves_one_original_dead_entity_once_even_with_two_real_grants(self):
        g=self.game((GROW,ECHO,ECHO,KILL),board=(A,));old=g.state.players[1].board[0]
        self.play(g,GROW,old);self.play(g,ECHO);self.play(g,ECHO);self.play(g,KILL,old)
        self.assertEqual(self.ids(g).count(A),1);self.assertIn(old,g.state.players[1].hand)
        self.assertEqual((g.state.entities[old].attack,g.state.entities[old].health),(2,8));self.portable(g)

    def test_spirit_echo_live_deathrattle_moves_original_without_a_death_or_copy(self):
        g=self.game((ECHO,TRIGGER),board=(A,));old=g.state.players[1].board[0];self.play(g,ECHO);self.play(g,TRIGGER,old)
        self.assertEqual(g.state.players[1].board,[]);self.assertIn(old,g.state.players[1].hand)
        self.assertEqual(g.state.death_history,[]);self.assertEqual(self.ids(g).count(A),1);self.portable(g)

    def test_spirit_echo_full_hand_on_actual_enemy_combat_does_not_duplicate_or_evict(self):
        g=self.game((ECHO,FILL)+(NATURE,)*8,board=(WEAK,),enemy=(B,));old=g.state.players[1].board[0]
        self.play(g,ECHO);self.play(g,FILL);self.assertEqual(len(g.state.players[1].hand),10)
        hand=list(g.state.players[1].hand);g.apply(EndTurn(1));g.apply(Attack(2,g.state.players[2].board[0],old))
        self.assertEqual(g.state.players[1].hand,hand);self.assertNotIn(old,g.state.players[1].hand)
        self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_grants_exclude_dormant_and_enemy_and_silence_removes_actual_granted_body(self):
        g=self.game((SPORES,HUSH,KILL),board=(A,DORMANT),enemy=(B,));old=g.state.players[1].board[0]
        self.play(g,SPORES);self.assertFalse(any(a.kind=='deathrattle'for a in self.entity(g,DORMANT,zone='board').abilities))
        self.assertFalse(any(a.kind=='deathrattle'for a in self.entity(g,B,2,'board').abilities));self.play(g,HUSH,old);self.play(g,KILL,old)
        self.assertEqual(self.ids(g,zone='board'),[DORMANT])

    def test_witch_brew_repeatable_copies_can_really_cost_zero_and_expire_at_end(self):
        g=self.game((HURTHERO,DISCOUNT,BREW));self.play(g,HURTHERO);self.play(g,DISCOUNT)
        for _ in range(5):self.play(g,BREW,self.hero(g).id)
        self.assertEqual((self.hero(g).health,g.state.players[1].mana),(30,10));self.portable(g)
        self.assertIn(BREW,self.ids(g));g.apply(EndTurn(1));self.assertNotIn(BREW,self.ids(g));self.portable(g)

    def test_once_upon_time_uses_four_original_tribal_three_cost_requests_and_real_capacity(self):
        g=self.game((ONCE,));self.play(g,ONCE);self.assertEqual(self.ids(g,zone='board'),[BEAST3,DRAGON3,ELEMENTAL3,MURLOC3]);self.portable(g)
        g=self.game((ONCE,),board=(A,)*6);n=g.state.next_entity_id;self.play(g,ONCE)
        self.assertEqual(self.ids(g,zone='board'),[A]*6+[BEAST3]);self.assertEqual(g.state.next_entity_id,n+1)

    def test_once_upon_time_all_tribe_candidate_can_supply_each_independent_tribal_slot(self):
        g=self.game((ONCE,),all_pool=True);self.play(g,ONCE);self.assertEqual(self.ids(g,zone='board'),[ALL3]*4);self.portable(g)

    def test_elementary_reaction_prior_elemental_or_all_actual_play_copies_original_top_draw(self):
        for cid in(ELEMENTAL,ALL):
            g=self.game((cid,REACTION),deck=(A,NATURE,FIRE));self.play(g,cid);self.cycle(g);self.play(g,REACTION)
            self.assertEqual(self.ids(g).count(NATURE),2);self.assertEqual(len(set(e for e in g.state.players[1].hand if g.state.entities[e].card_id==NATURE)),2);self.portable(g)

    def test_elementary_reaction_current_turn_or_only_summoned_elemental_does_not_qualify(self):
        g=self.game((ELEMENTAL,REACTION),deck=(NATURE,));self.play(g,ELEMENTAL);self.play(g,REACTION);self.assertEqual(self.ids(g).count(NATURE),1)
        g=self.game((SUMMON_E,REACTION),deck=(A,NATURE));self.play(g,SUMMON_E);self.cycle(g);self.play(g,REACTION);self.assertEqual(self.ids(g).count(NATURE),1)

    def test_elementary_reaction_empty_deck_uses_actual_fatigue_without_creating_copy(self):
        g=self.game((REACTION,),deck=());self.play(g,REACTION);self.assertEqual(self.hero(g).health,29);self.assertEqual(self.ids(g),[])

    def test_flash_draws_first_activates_next_own_turn_then_only_current_nature_prices_and_expires(self):
        g=self.game((FLASH,NATURE,NATURE,NATURE,FIRE),deck=(NATURE,)*5);self.play(g,FLASH);self.play(g,NATURE)
        self.assertEqual(g.state.players[1].mana,6);self.assertEqual(len(g.state.players[1].player_effects),1);self.portable(g)
        self.cycle(g);self.assertEqual(g.state.players[1].player_effects,[])
        self.play(g,NATURE);self.play(g,NATURE);self.play(g,FIRE);self.assertEqual(g.state.players[1].mana,6);self.portable(g)
        self.cycle(g);self.play(g,NATURE);self.assertEqual(g.state.players[1].mana,8);self.portable(g)

    def test_two_real_flash_promises_stack_without_early_discount_or_opponent_start_consumption(self):
        g=self.game((FLASH,FLASH,NATURE),deck=(NATURE,)*5);self.play(g,FLASH);self.play(g,FLASH);self.assertEqual(g.state.players[1].mana,6)
        g.apply(EndTurn(1));self.assertEqual(len(g.state.players[1].player_effects),2);g.apply(EndTurn(2))
        self.play(g,NATURE);self.assertEqual(g.state.players[1].mana,10);self.portable(g)

    def test_meteor_actual_damage_precedes_five_individually_shuffled_real_asteroids(self):
        g=self.game((METEOR,),board=(A,POWER),enemy=(B,),deck=(NATURE,FIRE));old=list(g.state.players[1].deck)
        self.play(g,METEOR);self.assertEqual(self.entity(g,A,zone='board').health,1);self.assertEqual(self.entity(g,B,2,'board').health,23)
        deck=g.state.players[1].deck;self.assertEqual(self.ids(g,zone='deck').count(ASTEROID),5);self.assertEqual([eid for eid in deck if eid in old],old);self.portable(g)

    def test_meteor_wait_before_shuffles_keeps_actual_damage_and_failed_resume_rng(self):
        g=self.game((METEOR,),board=(A,),enemy=(WATCH,),deck=(NATURE,));self.play(g,METEOR)
        self.assertIsNotNone(g.state.pending_choice);self.assertNotIn(ASTEROID,self.ids(g,zone='deck'));self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.finish(g);self.assertEqual(self.ids(g,zone='deck').count(ASTEROID),5);self.portable(g)

    def test_asteroid_paid_entry_and_actual_existing_per_card_value_program(self):
        g=self.game((ASTEROID,));self.play(g,ASTEROID);self.assertEqual((self.hero(g,2).health,g.state.players[1].mana),(28,9));self.portable(g)
        g=self.game((BOOST,ASTEROID),board=(POWER,));self.play(g,BOOST);self.play(g,ASTEROID)
        self.assertEqual(self.hero(g,2).health,25);self.portable(g)

    def test_two_actual_drawn_asteroids_auto_cast_then_one_replacement_card_reaches_hand(self):
        g=self.game((DRAW,),board=(POWER,),deck=(ASTEROID,ASTEROID,A));self.play(g,DRAW)
        self.assertEqual(self.hero(g,2).health,22);self.assertEqual(self.ids(g),[A]);self.assertEqual(g.state.players[1].deck,[])
        self.assertEqual([c.card_id for c in g.state.cast_history],[DRAW,ASTEROID,ASTEROID]);self.assertEqual(g.state.players[1].mana,10);self.portable(g)

    def test_base_resummon_and_nature_predicate_reject_wrong_material_or_identity_policy(self):
        g=self.game(board=(A,));material=CopyEntryMaterial.capture(g.state,self.entity(g,A,zone='board'),'base_resummon','base',registry=g.registry)
        material.__post_init__()
        cause=SummonCause(SourceAllocationFact.capture(g.state,self.hero(g)),1,g.state.turn,g.state.action_number)
        SummonByCard(1,(material,),cause)
        with self.assertRaises(ValueError):SummonByCard(2,(material,),cause)
        with self.assertRaises(ValueError):SummonByCard(1,(replace(material,captured_action=material.captured_action+1),),cause)
        with self.assertRaises(ValueError):replace(material,mode='current').__post_init__()
        with self.assertRaises(ValueError):CardAbilityCondition('nature_spell',basis='current')
        with self.assertRaises(ValueError):CardAbilityCondition('nature_spell',present=False,basis='printed')

    def test_real_standard_once_and_meteor_use_complete_views_and_actual_asteroid_dependencies(self):
        self.mode='host';h=host('writer');deck=('CORE_EX1_169',)*16
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_02',hand=(ONCE,METEOR),deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=('LOOT_077t',),deck=deck,mana=10,max_mana=10)),seed=674,generation_context=h.context),h.registry)
        self.play(g,ONCE);self.assertEqual(len(g.state.players[1].board),4);self.portable(g)
        self.cycle(g);self.play(g,METEOR);self.finish(g);self.assertEqual(self.ids(g,zone='deck').count(ASTEROID),5);self.portable(g)
