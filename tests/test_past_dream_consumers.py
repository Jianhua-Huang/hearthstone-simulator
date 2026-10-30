"""Three real Dream sources retain the five actual effects and shared delivery."""
from dataclasses import asdict
from functools import lru_cache
import random
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import past_dream_consumers as native
from hs_sim.cards.complex_dream_cards import register_complex_dream_cards,YSERA_IDS
from hs_sim.cards.simple_followup_p17_cards import register_simple_followup_p17_cards
from hs_sim.cards.fixed_dream_source import register_fixed_dream_source,DREAMS,DRYAD
from hs_sim.cards.shaladrassil_cards import ROOT as SHALA,PREFIX as SHALA_PREFIX
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Destroy,InvokeBehavior,
    RandomDamage,RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.model import (BattlecryRepeatSpec,CardDefinition,CardType,
    EndTurnRepeatSpec,TargetSpec,TriggerSpec,Zone)
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

YSERA,AWAKENED,NARALEX=native.ROOTS
SISTER,AWAKENS,DRAKE,DREAM,NIGHTMARE=DREAMS
P='k687.';A=P+'plain';POWER=P+'power';HUSH=P+'hush';BOUNCE=P+'bounce'
TAKE=P+'take';MUTATE=P+'mutate';SUMMON=P+'summon';DOUBLE_END=P+'double_end'
DOUBLE_BC=P+'double_bc';WATCH=P+'watch';FAIL=P+'fail'


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=opening_registry()
    register_complex_dream_cards(r);register_simple_followup_p17_cards(r);register_fixed_dream_source(r)
    # The original ordered callback is registry-independent. Its unused Shaladrassil
    # entry callback is installed for declaration validation, never executed here.
    original=host(role).registry
    for body in ('dreams','ordered'):r.register_behavior(SHALA_PREFIX+body,original.behavior(SHALA_PREFIX+body))
    r.register_card(original.card(SHALA));r.register_pool_card(original.pool_card(SHALA))
    native.register_past_dream_consumers(r)
    for cid,bonus in ((A,0),(POWER,2)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=40,
            spell_damage=bonus,metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(DOUBLE_END,DOUBLE_END,CardType.MINION,health=40,
        end_turn_repeats=(EndTurnRepeatSpec(2,'minion'),),metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(DOUBLE_BC,DOUBLE_BC,CardType.MINION,health=40,
        battlecry_repeats=(BattlecryRepeatSpec(2),),metadata=metadata(collectible=False)))
    board=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    scripts={HUSH:lambda c:(Silence(c.target_id),),BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        TAKE:lambda c:(ChangeControl(c.target_id,c.player_id),),
        MUTATE:lambda c:(Transform(c.target_id,A),),SUMMON:lambda c:(Summon(c.player_id,AWAKENED),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            targeting=None if cid==SUMMON else board,metadata=metadata(collectible=False)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K687 deliberate delivery rollback')))
    def wait(c):
        if c.state.entities[c.event.target_id].card_id not in DREAMS:return()
        options=(ChoiceOption('continue','Continue'),
            ChoiceOption('remove','Remove original source',(Destroy(c.event.source_id,c.source_id),)),
            ChoiceOption('fault','Fail after random damage',(
                RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
                InvokeBehavior(FAIL,c.source_id,c.player_id))))
        return(RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(WATCH,wait)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=40,
        triggers=(TriggerSpec('card_added_to_hand',WATCH),),metadata=metadata(collectible=False)))
    r.validate();return r


class PastDreamConsumersTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),player=1,seed=687):
        self.mode='small'
        return Game.from_scenario(Scenario(tuple(PlayerSetup('mage.hero'if p==1 else'warrior.hero',
            hand=hand if p==player else enemy_hand,board=board if p==player else enemy,
            deck=('card.1',)*20,mana=20,max_mana=20,mana_cap=20)for p in(1,2)),
            active_player=player,seed=seed),fixture('writer'))
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]
    def dreams(self,g,p=1):return[cid for cid in self.hand(g,p)if cid in DREAMS]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def draws(self,g,n):
        rng=random.Random();rng.setstate(g._rng.getstate())
        return[DREAMS[rng.randrange(5)]for _ in range(n)],rng.getstate()
    def drain(self,g):
        for _ in range(12):
            if g.state.pending_choice is None:return
            self.choose(g)
        self.fail('Dream delivery did not finish its finite notifications')

    def test_complete_original_faces_five_pins_and_eight_parent_declarations(self):
        d=native.load_batch();r=fixture();self.assertEqual(d['member_ids'],list(DREAMS))
        self.assertEqual(d['member_weights'],[1]*5);self.assertEqual(len(d['original_candidate_ids']),732)
        parents=[x for x in d['official_observations']if x['card_id']in(*native.ROOTS,DRYAD)]
        self.assertEqual(len(parents),8);self.assertTrue(all(x['face']['childIds']==[217,808,340,301,489]for x in parents))
        for row in d['cards']+d['existing_dependencies']:
            cid=row['record']['id']
            if cid=='TIME_013':continue
            self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(r.pool_card(cid))),row['pool_card_sha256'])
        self.assertTrue({YSERA,AWAKENED}<=YSERA_IDS);self.assertNotIn('DREAM_05e',r.cards)
        self.assertEqual(r.card(NARALEX).dormant_triggers[0].behavior_id,native.ONE_BODY)

    def test_three_real_paid_entries_and_no_early_end_reward(self):
        for cid in native.ROOTS:
            with self.subTest(cid=cid):
                g=self.game((cid,));source=self.play(g,cid);raw=fixture().card(cid)
                self.assertEqual(g.state.players[1].mana,20-raw.cost)
                self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(raw.attack,raw.health))
                self.assertEqual(len(self.dreams(g)),5 if cid==AWAKENED else 0)
                self.assertEqual(g.state.entities[source].active,cid!=NARALEX)
                self.assertIsNone(g.state.pending_choice)

    def test_ysera_two_independent_equal_ticket_draws_and_rng(self):
        g=self.game((YSERA,));source=self.play(g,YSERA);expected,rng=self.draws(g,2);self.end(g)
        self.assertEqual(self.dreams(g),expected);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.portable(g)

    def test_ysera_allows_same_dream_twice_with_replacement(self):
        seed=next(s for s in range(1000)if
            (lambda r:r.randrange(5)==r.randrange(5))(random.Random(s)))
        g=self.game(board=(YSERA,),seed=seed);expected,rng=self.draws(g,2);self.end(g)
        self.assertEqual(len(set(expected)),1);self.assertEqual(self.dreams(g),expected);self.assertEqual(g._rng.getstate(),rng)

    def test_ysera_only_owner_end_and_second_player_gets_own_rewards(self):
        g=self.game(board=(YSERA,),player=2);self.end(g)
        self.assertEqual(len(self.dreams(g,2)),2);self.assertEqual(self.dreams(g,1),[])
        self.end(g);self.assertEqual(len(self.dreams(g,2)),2);self.portable(g)

    def test_ysera_silence_transform_and_return_retire_end_body(self):
        for cid in (HUSH,MUTATE,BOUNCE):
            with self.subTest(cid=cid):
                g=self.game((cid,),board=(YSERA,));self.play(g,cid,self.unit(g,YSERA).id);self.end(g)
                self.assertEqual(self.dreams(g),[])

    def test_ysera_control_change_moves_end_recipient(self):
        g=self.game((TAKE,),enemy=(YSERA,));self.play(g,TAKE,self.unit(g,YSERA,2).id)
        self.end(g);self.assertEqual(len(self.dreams(g)),2);self.assertEqual(self.dreams(g,2),[]);self.portable(g)

    def test_awakened_gets_every_dream_once_as_automatic_permutation(self):
        g=self.game((AWAKENED,),seed=19);self.play(g,AWAKENED)
        self.assertEqual(set(self.dreams(g)),set(DREAMS));self.assertEqual(len(self.dreams(g)),5)
        self.assertNotEqual(tuple(self.dreams(g)),DREAMS);self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].mana,11);self.assertEqual(len(g.state.cast_history),0);self.portable(g)

    def test_awakened_full_hand_preserves_order_and_burns_four_real_cards(self):
        g=self.game((AWAKENED,),seed=19);self.play(g,AWAKENED);order=self.dreams(g)
        full=self.game((AWAKENED,)+(A,)*9,seed=19);old=full.state.players[1].hand[1:];self.play(full,AWAKENED)
        self.assertEqual(self.dreams(full),order[:1]);self.assertEqual(full.state.players[1].hand[:9],old)
        burned=[e for e in full.state.entities.values()if e.card_id in DREAMS and e.zone==Zone.GRAVEYARD]
        self.assertEqual(len(burned),4);self.assertEqual({e.card_id for e in burned},set(order[1:]));self.portable(full)

    def test_awakened_plain_summon_does_not_run_battlecry(self):
        g=self.game((SUMMON,));self.play(g,SUMMON);self.assertEqual(self.dreams(g),[])
        self.assertEqual(self.unit(g,AWAKENED).health,12)

    def test_naralex_two_dormant_owner_ends_then_wakes_without_more_gifts(self):
        g=self.game((NARALEX,));source=self.play(g,NARALEX)
        self.assertEqual(g.state.entities[source].dormancy.remaining_turns,2);self.end(g)
        self.assertEqual(len(self.dreams(g)),1);self.end(g)
        self.assertEqual(g.state.entities[source].dormancy.remaining_turns,1);self.end(g)
        self.assertEqual(len(self.dreams(g)),2);self.end(g)
        self.assertIsNone(g.state.entities[source].dormancy);self.assertTrue(g.state.entities[source].active)
        self.end(g);self.assertEqual(len(self.dreams(g)),2);self.portable(g)

    def test_naralex_dormant_source_is_not_a_spell_target(self):
        g=self.game((HUSH,),board=(NARALEX,));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,HUSH,self.unit(g,NARALEX).id)
        self.assertEqual(g.snapshot(),before)

    def test_real_end_repeats_include_dormant_and_ysera_independent_draws(self):
        g=self.game(board=(DOUBLE_END,YSERA,NARALEX));expected,rng=self.draws(g,6);self.end(g)
        self.assertEqual(self.dreams(g),expected);self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_battlecry_repeat_gets_two_whole_five_sets_with_one_payment(self):
        g=self.game((AWAKENED,),board=(DOUBLE_BC,));self.play(g,AWAKENED)
        self.assertEqual(len(self.dreams(g)),10)
        self.assertTrue(all(self.dreams(g).count(cid)==2 for cid in DREAMS))
        self.assertEqual(g.state.players[1].mana,11);self.portable(g)

    def test_ysera_first_delivery_wait_keeps_second_draw_after_source_dies(self):
        g=self.game(board=(YSERA,WATCH));source=self.unit(g,YSERA).id;expected,rng=self.draws(g,2);self.end(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.dreams(g),expected[:1])
        g=self.portable(g);self.choose(g,'remove');self.drain(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.dreams(g),expected)
        self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_awakened_wait_restores_complete_frozen_order(self):
        expected=self.game((AWAKENED,),seed=19);self.play(expected,AWAKENED);order=self.dreams(expected)
        g=self.game((AWAKENED,),board=(WATCH,),seed=19);self.play(g,AWAKENED)
        self.assertEqual(self.dreams(g),order[:1]);g=self.portable(g);self.drain(g)
        self.assertEqual(self.dreams(g),order);self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_delivery_failure_restores_wait_rng_payment_and_remaining_cards(self):
        g=self.game((AWAKENED,),board=(WATCH,));self.play(g,AWAKENED);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.state.players[1].mana,11)
        self.drain(g);self.assertEqual(set(self.dreams(g)),set(DREAMS));self.portable(g)

    def test_naralex_wait_restores_dormancy_and_original_owner_clock(self):
        g=self.game(board=(NARALEX,WATCH));source=self.unit(g,NARALEX).id;self.end(g)
        g=self.portable(g);self.drain(g);self.end(g);self.end(g);self.drain(g)
        self.assertEqual(len(self.dreams(g)),2);self.end(g)
        self.assertIsNone(g.state.entities[source].dormancy);self.portable(g)

    def test_generated_five_real_effects_through_normal_paid_actions(self):
        g=self.game((AWAKENED,));source=self.play(g,AWAKENED)
        sister=self.play(g,SISTER);drake=self.play(g,DRAKE);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,NIGHTMARE,sister)
        self.assertEqual(g.snapshot(),before);self.play(g,AWAKENS)
        self.assertEqual(g.state.entities[source].health,12);self.assertEqual(self.hero(g).health,25)
        self.assertEqual(self.hero(g,2).health,25);self.assertEqual(g.state.entities[sister].zone,Zone.GRAVEYARD)
        self.assertEqual((g.state.entities[drake].attack,g.state.entities[drake].health),(7,1))
        self.play(g,NIGHTMARE,drake);self.assertEqual((g.state.entities[drake].attack,g.state.entities[drake].health),(12,6))
        self.play(g,DREAM,drake);returned=self.entity(g,DRAKE)
        self.assertEqual((returned.attack,returned.health),(7,6));self.end(g);self.end(g)
        self.assertEqual(self.entity(g,DRAKE).zone,Zone.HAND);self.portable(g)

    def test_generated_awakens_exempts_both_added_yseras_and_uses_spell_damage(self):
        g=self.game((AWAKENED,),board=(YSERA,POWER),enemy=(A,));source=self.play(g,AWAKENED);self.play(g,AWAKENS)
        self.assertEqual(g.state.entities[source].health,12);self.assertEqual(self.unit(g,YSERA).health,12)
        self.assertEqual(self.unit(g,A,2).health,33);self.assertEqual(self.hero(g).health,23)
        self.assertEqual(self.hero(g,2).health,23);self.portable(g)

    def test_generated_nightmare_destroys_at_original_caster_next_start(self):
        g=self.game((AWAKENED,),board=(A,));self.play(g,AWAKENED);target=self.unit(g,A).id
        self.play(g,NIGHTMARE,target);self.end(g);self.assertEqual(g.state.entities[target].zone,Zone.BOARD)
        self.end(g);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.portable(g)

    def test_generated_dream_returns_stolen_minion_to_original_owner(self):
        g=self.game((AWAKENED,TAKE),enemy=(A,));self.play(g,AWAKENED);target=self.unit(g,A,2).id
        self.play(g,TAKE,target);self.play(g,DREAM,target)
        self.assertEqual(g.state.entities[target].zone,Zone.HAND);self.assertIn(target,g.state.players[2].hand)
        self.assertEqual(self.dreams(g,2),[]);self.portable(g)

    def test_standard_host_gets_and_executes_full_finite_recipe(self):
        self.mode='host';h=host('writer')
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(AWAKENED,),deck=('CORE_CS2_182',)*8,
            mana=20,max_mana=20,mana_cap=20),PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*8)),
            generation_context=h.context,seed=19),h.registry)
        source=self.play(g,AWAKENED);self.assertEqual(set(self.dreams(g)),set(DREAMS))
        self.play(g,DRAKE);self.play(g,AWAKENS);self.assertEqual(g.state.entities[source].health,12)
        self.assertEqual(self.unit(g,DRAKE).health,1);self.portable(g)
