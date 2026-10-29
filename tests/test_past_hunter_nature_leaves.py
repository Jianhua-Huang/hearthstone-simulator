"""Real hand entries and shared damage, progress, summon and Deathrattle edges."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import past_hunter_nature_leaves as native
from hs_sim.cards.simple_followup_p89_cards import WO
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import (ChoiceOption,Damage,Destroy,InvokeBehavior,RandomDamage,RequestChoice,Silence,Summon)
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,SecretSpec,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError,canonical_digest

P='k668.'
A,B,WEAK,DRAGON,ALL,DORMANT,SHIELD,IMMUNE,POWER,BEAST1,BEAST2,SECRET1,SECRET2,NOOP,KILL,HUSH,AUTO,COUNTER,WATCH,FAIL=(P+x for x in
    ('a','b','weak','dragon','all','dormant','shield','immune','power','beast1','beast2','secret1','secret2','noop','kill','hush','auto','counter','watch','fail'))
BREATH,COBRA,ARROW,STONE,INFEST,COBRA2=native.ROOTS
CTX=GenerationContext('k668-complete-two-beast-fixture','experimental')


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=opening_registry();native.register_past_hunter_nature_leaves(r)
    for cid,hp,tribes,keywords,power,dormant in (
            (A,8,(),(),0,0),(B,30,(),(),0,0),(WEAK,2,(),(),0,0),
            (DRAGON,4,('dragon',),(),0,0),(ALL,4,('all',),(),0,0),
            (DORMANT,8,(),(),0,2),(SHIELD,4,(),(Keyword.DIVINE_SHIELD,),0,0),
            (IMMUNE,4,(),(Keyword.IMMUNE,),0,0),(POWER,8,(),(),2,0),
            (BEAST1,4,('beast',),(),0,0),(BEAST2,5,('beast',),(),0,0)):
        card=CardDefinition(cid,cid,CardType.MINION,cost=1,attack=2,health=hp,keywords=keywords,
            spell_damage=power,dormant_turns=dormant,metadata=metadata(tribes=tribes))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_pool(PoolDefinition('constructed.cards','k668-two-beast-fixture',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in(BEAST1,BEAST2,A)),complete=True))
    r.register_behavior(NOOP,lambda c:())
    r.register_card(CardDefinition(NOOP,NOOP,CardType.SPELL,on_play=NOOP,metadata=metadata(collectible=False)))
    r.register_secret_condition(P+'never',lambda c:False)
    for cid in(SECRET1,SECRET2):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,keywords=(Keyword.SECRET,),
            secret=SecretSpec(cid,('turn_started',),P+'never',NOOP),metadata=metadata()))
    for cid,body in((KILL,lambda c:(Destroy(c.target_id,c.source_id),)),(HUSH,lambda c:(Silence(c.target_id),))):
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),metadata=metadata(collectible=False)))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,SECRET1,c.source_id),))
    r.register_card(CardDefinition(AUTO,AUTO,CardType.MINION,cost=1,health=4,battlecry=AUTO,metadata=metadata(collectible=False)))
    r.register_behavior(COUNTER,lambda c:(CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id!=c.player_id and c.state.entities[c.event.source_id].kind==CardType.SPELL else())
    r.register_card(CardDefinition(COUNTER,COUNTER,CardType.MINION,health=10,
        triggers=(TriggerSpec('card_committed',COUNTER),),metadata=metadata(collectible=False)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K668 deliberate rollback')))
    def wait(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id not in native.TARGETED:return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,wait)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,triggers=(TriggerSpec('damage_dealt',WATCH),),metadata=metadata(collectible=False)))
    r.validate();return r


class HunterNatureLeavesTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(),other_hand=(),watch=False):
        self.mode='small';board=board+((WATCH,)if watch else())
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=('card.1',)*14,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',hand=other_hand,board=enemy,deck=('card.2',)*14,mana=10,max_mana=10)),
            seed=668,generation_context=CTX),fixture())

    def ids(self,g,player=1,zone='board'):
        return[g.state.entities[eid].card_id for eid in getattr(g.state.players[player],zone)]

    def finish(self,g):
        count=0
        while g.state.pending_choice is not None:
            self.choose(g);count+=1
            self.assertLess(count,10)

    def hero(self,g,player=2):return g.state.entities[g.state.players[player].hero_id]

    def test_complete_original_rows_nine_native_faces_and_explicit_remaining_source(self):
        d=native.load_batch();r=fixture()
        self.assertEqual(d['remaining_hunter_ids'],['AV_333','REV_361','TID_075'])
        self.assertFalse(d['complete_hunter_source_bound']);self.assertEqual(len(d['original_hunter_member_ids']),9)
        for row in d['cards']+d['dependencies']:
            cid=row['record']['id'];card=r.card(cid)
            self.assertEqual(canonical_digest(asdict(card)),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(r.pool_card(cid))),row['pool_card_sha256'])
            self.assertEqual(card.cost,row['record']['cost'])
        with patch.object(native,'BATCH_HASH',''):
            with self.assertRaises(TargetValidationError):native.load_batch()

    def test_distinct_cobra_faces_damage_original_minion_and_enemy_hero_once(self):
        for cid in(COBRA,COBRA2):
            with self.subTest(card=cid):
                g=self.game((cid,),enemy=(A,));self.play(g,cid,self.entity(g,A,2,'board').id)
                self.assertEqual((self.entity(g,A,2,'board').health,self.hero(g).health),(5,27))
                self.assertEqual(g.state.players[1].mana,6)
                self.assertEqual([x.card_id for x in g.state.cast_history],[cid])

    def test_cobra_accepts_friendly_minion_but_hero_arrow_is_illegal_and_atomic(self):
        g=self.game((COBRA,),board=(A,));saved=deepcopy(g.snapshot())
        with self.assertRaises(IllegalAction):self.play(g,COBRA,self.hero(g).id)
        self.assertEqual(g.snapshot(),saved)
        self.play(g,COBRA,self.entity(g,A,zone='board').id)
        self.assertEqual((self.entity(g,A,zone='board').health,self.hero(g).health),(5,27))

    def test_breath_without_a_held_dragon_ignores_board_dragon(self):
        g=self.game((BREATH,),board=(DRAGON,),enemy=(A,));self.play(g,BREATH,self.entity(g,A,2,'board').id)
        self.assertEqual((self.entity(g,A,2,'board').health,self.hero(g).health),(5,30))

    def test_breath_uses_current_held_dragon_or_all_tribes(self):
        for held in(DRAGON,ALL):
            with self.subTest(held=held):
                g=self.game((BREATH,held),enemy=(A,));self.play(g,BREATH,self.entity(g,A,2,'board').id)
                self.assertEqual(self.hero(g).health,27);self.assertIn(held,self.ids(g,zone='hand'))

    def test_ordinary_spell_damage_modifies_both_cobra_packets(self):
        g=self.game((COBRA,),board=(POWER,),enemy=(A,));self.play(g,COBRA,self.entity(g,A,2,'board').id)
        self.assertEqual((self.entity(g,A,2,'board').health,self.hero(g).health),(3,25));self.portable(g)

    def test_toxic_arrow_grants_only_after_survival_and_uses_normal_poisonous_combat(self):
        g=self.game((ARROW,),board=(A,),enemy=(B,));target=self.entity(g,A,zone='board').id
        self.play(g,ARROW,target);self.assertTrue(Keyword.POISONOUS in g.state.entities[target].keywords)
        self.assertEqual(g.state.entities[target].health,6)
        g.apply(EndTurn(1));g.apply(EndTurn(2));g.apply(Attack(1,target,self.entity(g,B,2,'board').id))
        self.assertEqual(self.ids(g,2),[]);self.portable(g)

    def test_lethal_toxic_arrow_does_not_install_poisonous(self):
        g=self.game((ARROW,),enemy=(WEAK,));target=self.entity(g,WEAK,2,'board').id
        self.play(g,ARROW,target);self.assertEqual(self.ids(g,2),[])
        self.assertFalse(Keyword.POISONOUS in g.state.entities[target].keywords);self.assertEqual(len(g.state.death_history),1)

    def test_divine_shield_survivor_gains_poisonous_without_health_damage(self):
        g=self.game((ARROW,),board=(SHIELD,));target=self.entity(g,SHIELD,zone='board').id
        self.play(g,ARROW,target);self.assertEqual(g.state.entities[target].health,4)
        self.assertFalse(Keyword.DIVINE_SHIELD in g.state.entities[target].keywords);self.assertTrue(Keyword.POISONOUS in g.state.entities[target].keywords)

    def test_immune_survivor_and_silence_reuse_normal_keyword_lifecycle(self):
        g=self.game((ARROW,HUSH),board=(IMMUNE,));target=self.entity(g,IMMUNE,zone='board').id
        self.play(g,ARROW,target);self.assertEqual(g.state.entities[target].health,4)
        self.assertTrue(Keyword.POISONOUS in g.state.entities[target].keywords)
        self.play(g,HUSH,target);self.assertFalse(Keyword.POISONOUS in g.state.entities[target].keywords)

    def test_original_damage_batch_wait_resume_and_failed_rng_choice_are_atomic(self):
        g=self.game((COBRA,),enemy=(A,),watch=True);self.play(g,COBRA,self.entity(g,A,2,'board').id)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.hero(g).health,27)
        self.assertEqual(self.entity(g,A,2,'board').health,5);self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.finish(g);self.assertEqual(g.state.players[1].mana,6);self.portable(g)

    def test_all_emerald_stages_use_exact_named_ordinary_wolves(self):
        for count,cid in enumerate(native.STONES,2):
            with self.subTest(stage=cid):
                g=self.game((cid,));self.play(g,cid)
                self.assertEqual(self.ids(g),[native.WOLF]*count)
                self.assertTrue(all((g.state.entities[eid].attack,g.state.entities[eid].health)==(3,3)for eid in g.state.players[1].board))
                self.assertEqual(g.state.players[1].mana,5)

    def test_two_real_secret_plays_upgrade_same_held_entity_to_four_wolves(self):
        g=self.game((STONE,SECRET1,SECRET2));original=self.entity(g,STONE).id
        self.play(g,SECRET1);self.assertEqual(g.state.entities[original].card_id,native.STONES[1]);self.portable(g)
        self.play(g,SECRET2);self.assertEqual(g.state.entities[original].card_id,native.STONES[2])
        self.play(g,native.STONES[2]);self.assertEqual(self.ids(g),[native.WOLF]*4);self.assertEqual(g.state.players[1].mana,3);self.portable(g)

    def test_auto_secret_install_does_not_count_as_a_secret_hand_play(self):
        g=self.game((STONE,AUTO));self.play(g,AUTO)
        self.assertEqual(self.entity(g,STONE).card_id,STONE)
        self.assertEqual(progress_ability(self.entity(g,STONE)).progress_value,0)
        self.assertEqual(len(g.state.players[1].secrets),1);self.portable(g)

    def test_opponent_secret_and_other_spell_do_not_upgrade(self):
        g=self.game((STONE,NOOP),other_hand=(SECRET1,));self.play(g,NOOP)
        g.apply(EndTurn(1));self.play(g,SECRET1,player=2)
        self.assertEqual(self.entity(g,STONE).card_id,STONE)

    def test_committed_secret_counts_even_when_its_payload_is_countered(self):
        g=self.game((STONE,SECRET1),enemy=(COUNTER,));self.play(g,SECRET1)
        self.assertEqual(self.ids(g,zone='hand'),[native.STONES[1]])
        self.assertEqual(g.state.players[1].secrets,[]);self.assertTrue(g.state.play_history[-1].countered);self.portable(g)

    def test_wolf_capacity_does_not_replace_existing_minions_or_allocate_overflow(self):
        g=self.game((native.STONES[2],),board=(A,)*6);start=g.state.next_entity_id
        self.play(g,native.STONES[2]);self.assertEqual(self.ids(g),[A]*6+[native.WOLF])
        self.assertEqual(g.state.next_entity_id,start+1);self.assertEqual(g.state.players[1].mana,5)

    def test_infest_grants_initial_active_group_and_actual_death_generates_beast(self):
        g=self.game((INFEST,KILL),board=(A,DORMANT),enemy=(B,));self.play(g,INFEST)
        self.assertTrue(any(a.kind=='deathrattle'for a in self.entity(g,A,zone='board').abilities))
        self.assertFalse(any(a.kind=='deathrattle'for a in self.entity(g,DORMANT,zone='board').abilities))
        self.assertFalse(any(a.kind=='deathrattle'for a in self.entity(g,B,2,'board').abilities))
        self.play(g,KILL,self.entity(g,A,zone='board').id)
        self.assertEqual(len(g.state.players[1].hand),1);self.assertIn(self.ids(g,zone='hand')[0],(BEAST1,BEAST2));self.portable(g)

    def test_infest_grants_stack_and_silence_removes_the_ordinary_attachments(self):
        for silence in(False,True):
            with self.subTest(silence=silence):
                hand=(INFEST,INFEST,KILL)+((HUSH,)if silence else())
                g=self.game(hand,board=(A,));self.play(g,INFEST);self.play(g,INFEST);target=self.entity(g,A,zone='board').id
                if silence:self.play(g,HUSH,target)
                self.play(g,KILL,target);self.assertEqual(len(g.state.players[1].hand),0 if silence else 2)
                self.assertTrue(all(cid in(BEAST1,BEAST2)for cid in self.ids(g,zone='hand')))

    def test_empty_infest_and_full_wolf_board_do_not_consume_rng(self):
        g=self.game((INFEST,));saved=g.snapshot()['rng_state'];self.play(g,INFEST);self.assertEqual(g.snapshot()['rng_state'],saved)
        g=self.game((STONE,),board=(A,)*7);start=g.state.next_entity_id;saved=g.snapshot()['rng_state'];self.play(g,STONE)
        self.assertEqual(g.state.next_entity_id,start);self.assertEqual(g.snapshot()['rng_state'],saved)

    def test_real_standard_host_all_damage_faces_keep_actual_payment_and_lifetimes(self):
        self.mode='host';h=host();deck=('CORE_EX1_169',)*15
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_05',hand=(BREATH,COBRA,ARROW),board=(native.WOLF,),deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=(native.WOLF,native.WOLF),deck=deck,mana=10,max_mana=10)),seed=668,generation_context=h.context),h.registry)
        target=g.state.players[2].board[0];self.play(g,BREATH,target);self.assertEqual(self.hero(g).health,30)
        self.play(g,COBRA,g.state.players[2].board[0]);self.assertEqual(self.hero(g).health,27)
        own=g.state.players[1].board[0];self.play(g,ARROW,own);self.assertTrue(Keyword.POISONOUS in g.state.entities[own].keywords)
        self.assertEqual(g.state.players[1].mana,2);self.portable(g)

    def test_real_host_infest_reward_uses_complete_ordinary_pool_after_new_wolves(self):
        self.mode='host';h=host();deck=('CORE_EX1_169',)*15
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_05',hand=(INFEST,STONE),board=(native.WOLF,),deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=(native.WOLF,),deck=deck,mana=10,max_mana=10)),seed=668,generation_context=h.context),h.registry)
        original=g.state.players[1].board[0];self.play(g,INFEST);self.play(g,STONE)
        self.assertEqual(self.ids(g),[native.WOLF]*3)
        self.assertEqual([sum(a.kind=='deathrattle'for a in g.state.entities[eid].abilities)for eid in g.state.players[1].board],[1,0,0])
        g.apply(EndTurn(1));g.apply(EndTurn(2));g.apply(Attack(1,original,g.state.players[2].board[0]))
        rewards=[g.state.entities[eid]for eid in g.state.players[1].hand if g.state.entities[eid].card_id!='CORE_EX1_169']
        self.assertEqual(len(rewards),1);allowed=resolve_candidates(g.registry,h.context,'constructed.cards',native.BEASTS,current_class=g.state.players[1].hero_class)
        self.assertIn(rewards[0].card_id,[v.card_id for v in allowed]);self.portable(g)

    def test_unreviewed_shaman_full_source_remains_explicitly_unbound(self):
        self.mode='host';h=host();deck=('CORE_EX1_169',)*15
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_02',hand=('CORE_EX1_169',),board=(WO,),deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=deck,mana=10,max_mana=10)),seed=668,generation_context=h.context),h.registry)
        saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.play(g,'CORE_EX1_169')
        self.assertEqual(g.snapshot(),saved)
