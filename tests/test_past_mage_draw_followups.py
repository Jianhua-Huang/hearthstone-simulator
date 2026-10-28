"""Actual root draws, frozen costs and whole-group discards for three spells."""
from copy import deepcopy
from functools import lru_cache
import json,unittest
from unittest.mock import patch
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import past_mage_draw_followups as native
from hs_sim.engine import Game,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import AddToHand,ChoiceOption,Draw,InvokeBehavior,RequestChoice
from hs_sim.engine.model import CardClass,CardDefinition,CardType,CastWhenDrawnSpec,CostSpec,Keyword,LimitedTriggerSpec,Zone
from hs_sim.engine.physical_draw_groups import DrawGroupReward,DrawGroupSlot,DrawPhysicalGroup,SPELL_COST_FOLLOWUP
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.zones import CardReference,ModifyStoredCost,MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format

SPRING,BOOK,SEA=native.LEAVES
P='k624.'
S1,S2,S5,CAST,FILL,M2,M3,M5,UNKNOWN=(P+x for x in('spell3','spell4','spell5','draw_cast','fill','minion2','minion3','minion5','unknown'))
WAIT,EXTRA,CYCLE,RETURN,DISCARD_WAIT,DISCARD_FAIL,SUMMON_WAIT,FILL_HAND,REPRICE,FAIL=(P+x for x in
    ('wait','extra','cycle','return','discard_wait','discard_fail','summon_wait','fill_hand','reprice','fail'))

def context(mode):return GenerationContext('k624-explicit-diagnostic-'+mode,'experimental')


@lru_cache(None)
def registry(mode='normal',role='writer'):
    if mode not in ('normal','empty','unknown'):raise ValueError('Unknown draw-followup fixture')
    r=opening_registry();native.register_past_mage_draw_followups(r)
    r.register_behavior(FILL,lambda c:())
    for cid,cost in ((S1,3),(S2,4),(S5,5),(FILL,0),(CAST,3)):
        extra=dict(keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())if cid==CAST else{}
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=FILL,
            metadata=metadata(CardClass.MAGE,tribes=()),**extra))
    for cid,cost in ((M2,2),(M3,3),(M5,5)):
        card=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=4,metadata=metadata(tribes=()))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    members=[] if mode=='empty' else [M2,M3,M5]
    if mode=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,3,metadata(tribes=()),attack=1));members.append(UNKNOWN)
    r.register_pool(PoolDefinition(native.POOL,'k624-complete-cost-fixture-'+mode,context(mode).target_id,
        context(mode).mode,tuple(PoolMember(cid)for cid in members),complete=True))
    def reprice(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id==S1)
        return(ModifyStoredCost(CardReference.capture(e),CostSpec(set_to=2),c.source_id),)
    r.register_behavior(REPRICE,reprice);r.register_card(CardDefinition(REPRICE,REPRICE,CardType.SPELL,on_play=REPRICE))
    def fail(c):raise ResolutionError('K624 deliberate root reaction failure')
    r.register_behavior(FAIL,fail)
    for cid,event in ((WAIT,'card_drawn'),(EXTRA,'card_drawn'),(CYCLE,'card_drawn'),(RETURN,'card_drawn'),
            (DISCARD_WAIT,'card_discarded'),(DISCARD_FAIL,'card_discarded'),
            (SUMMON_WAIT,'minion_summoned'),(FILL_HAND,'spell_cast_accepted')):
        def eligible(c,cid=cid):
            if cid==SUMMON_WAIT:return c.event.player_id==c.player_id
            source=c.state.entities.get(c.event.source_id)
            return source is not None and source.card_id in native.LEAVES
        def watch(c,cid=cid):
            if cid==FILL_HAND:return(AddToHand(c.player_id,FILL,c.source_id),)
            if cid==EXTRA:return(Draw(c.player_id,source_id=c.source_id),)
            if cid in (CYCLE,RETURN):
                e=c.state.entities[c.event.target_id]
                move=MoveCard(CardReference.capture(e),c.player_id,Zone.DECK,'top',source_id=c.source_id)
                return (move,Draw(c.player_id,source_id=c.source_id)) if cid==CYCLE else (move,)
            failure=InvokeBehavior(FAIL,c.source_id,c.player_id)
            if cid==DISCARD_FAIL:return(failure,)
            options=[ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(failure,))]
            if cid==WAIT:
                e=c.state.entities[c.event.target_id]
                if e.zone==Zone.HAND:
                    options.append(ChoiceOption('change','Change live hand cost',
                        (ModifyStoredCost(CardReference.capture(e),CostSpec(set_to=5),c.source_id),)))
            return(RequestChoice(c.player_id,tuple(options),c.source_id),)
        r.register_behavior(cid,watch);r.register_trigger_condition(cid,eligible)
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=20,
            limited_triggers=(LimitedTriggerSpec(event,cid,cid),)))
    r.validate();return r


class PastMageDrawFollowupTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,hand,*,deck=(S1,S2,M3),board=(),weapon=None,hand_cap=None,mode='normal',seed=624):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,deck=deck,board=board,
            weapon_card_id=weapon,mana=10,max_mana=10,hand_cap=hand_cap),
            PlayerSetup('warrior.hero',deck=('card.1',)*8,mana=10,max_mana=10)),
            seed=seed,generation_context=context(mode)),registry(mode))
    def rollback_choice(self,g):
        g=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);return g
    def hand(self,g):return tuple(g.state.entities[i].card_id for i in g.state.players[1].hand)
    def board(self,g):return tuple(g.state.entities[i].card_id for i in g.state.players[1].board)

    def test_three_complete_original_rows_and_six_full_primary_faces(self):
        d=native.load_batch();rows={v['record']['id']:v['record']for v in d['dependencies']}
        for o in d['official_observations']:batch.check_face(rows[o['card_id']],o['face'],o['locale'])
        self.assertEqual(len(rows),3);self.assertFalse(d['new_standard_roots']);self.assertFalse(d['source_scope_bound'])

    def test_new_reward_shapes_reject_incomplete_slot_plans_and_unrelated_targets(self):
        for kind,count,amount in (('refresh_drawn_spells',2,2),('discard_drawn_spells',3,0)):
            DrawPhysicalGroup(1,1,(DrawGroupSlot(),)*count,DrawGroupReward(kind,amount))
            with self.assertRaises(ValueError):DrawPhysicalGroup(1,1,(DrawGroupSlot(),),DrawGroupReward(kind,amount))
        for slot in (DrawGroupSlot(),DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,)))):
            with self.assertRaises(ValueError):DrawPhysicalGroup(1,1,(slot,),DrawGroupReward(SPELL_COST_FOLLOWUP,behavior_id='known'))
        with self.assertRaises(ValueError):DrawPhysicalGroup(1,1,
            (DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,),exclude_source=True)),),
            DrawGroupReward(SPELL_COST_FOLLOWUP,behavior_id='known',target_id=1))

    def test_last_face_failure_preserves_whole_native_registration_boundary(self):
        r=opening_registry();before=r.fingerprint();d=deepcopy(native.load_batch());d['dependencies'][-1]['record']['cost']=-1
        with patch.object(native,'load_batch',return_value=d),self.assertRaises(ValueError):native.register_past_mage_draw_followups(r)
        self.assertEqual(r.fingerprint(),before)

    def test_spring_two_real_spell_roots_pay_five_then_refresh_four(self):
        g=self.game((SPRING,),deck=(S1,S2));source=self.play(g,SPRING)
        self.assertEqual(g.state.players[1].mana,9);self.assertEqual(self.hand(g),(S1,S2))
        self.assertEqual([r.source_id for r in g.state.draw_history],[source,source])

    def test_spring_mixed_root_types_only_credit_the_actual_spell(self):
        g=self.game((SPRING,),deck=(S1,M3));self.play(g,SPRING)
        self.assertEqual(g.state.players[1].mana,7)
        g=self.game((SPRING,),deck=(M3,M2));self.play(g,SPRING);self.assertEqual(g.state.players[1].mana,5)

    def test_spring_credits_its_original_spell_even_after_that_card_leaves_and_reenters(self):
        g=self.game((SPRING,),deck=(S1,M3),weapon=CYCLE);self.play(g,SPRING)
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(len(g.state.draw_history),3)

    def test_spring_fatigue_has_no_spell_reward(self):
        g=self.game((SPRING,),deck=());self.play(g,SPRING)
        self.assertEqual(g.state.players[1].mana,5);self.assertEqual(g.state.players[1].fatigue,2)

    def test_spring_burned_spell_is_not_a_successful_draw_reward(self):
        g=self.game((SPRING,),deck=(S1,S2),hand_cap=1);self.play(g,SPRING)
        self.assertEqual(g.state.players[1].mana,7)
        self.assertEqual([r.outcome for r in g.state.draw_history],['hand','burned'])

    def test_spring_draw_cast_root_counts_once_without_adding_replacement_spell(self):
        g=self.game((SPRING,),deck=(CAST,S1,S2));self.play(g,SPRING)
        self.assertEqual(len(g.state.draw_history),3);self.assertEqual(g.state.players[1].mana,9)
        self.assertEqual(self.hand(g),(S1,S2))

    def test_spring_extra_reaction_spell_draw_does_not_add_a_root_reward(self):
        g=self.game((SPRING,),deck=(S1,S2,M3),weapon=EXTRA);self.play(g,SPRING)
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(len(g.state.draw_history),3)

    def test_spring_wait_restores_original_root_prefix_and_refreshes_after_entire_group(self):
        g=self.game((SPRING,),deck=(S1,S2),weapon=WAIT);self.play(g,SPRING)
        self.assertEqual(g.state.players[1].mana,5);g=self.rollback_choice(g)
        self.assertEqual(g.state.players[1].mana,9);self.assertEqual(len(g.state.draw_history),2)

    def test_book_discards_only_original_spell_roots_and_keeps_preexisting_hand_spell(self):
        g=self.game((BOOK,FILL),deck=(S1,M3,S2));self.play(g,BOOK)
        self.assertEqual(self.hand(g),(FILL,M3));self.assertEqual(len(g.state.discard_history),2)
        self.assertEqual(g.state.players[1].mana,8)

    def test_book_extra_reaction_draw_is_not_a_discard_recipient(self):
        g=self.game((BOOK,),deck=(S1,S2,M3,M2),weapon=EXTRA);self.play(g,BOOK)
        self.assertIn(S2,self.hand(g));self.assertNotIn(S1,self.hand(g));self.assertEqual(len(g.state.discard_history),1)

    def test_book_does_not_rebind_an_original_card_that_left_and_was_redrawn(self):
        g=self.game((BOOK,),deck=(S1,S2,M3),weapon=CYCLE);self.play(g,BOOK)
        self.assertEqual(self.hand(g),(S1,M3));self.assertEqual(len(g.state.discard_history),1)

    def test_book_later_actual_root_can_discard_new_residency_of_the_same_physical_entity_once(self):
        g=self.game((BOOK,),deck=(S1,M3),weapon=RETURN);self.play(g,BOOK)
        self.assertEqual(self.hand(g),(M3,));self.assertEqual(len(g.state.discard_history),1)
        first,second=g.state.draw_history[:2];self.assertEqual(first.entity_id,second.entity_id)

    def test_book_burned_spells_are_not_discarded_again(self):
        g=self.game((BOOK,),deck=(S1,S2,S5),hand_cap=1);self.play(g,BOOK)
        self.assertFalse(self.hand(g));self.assertEqual(len(g.state.discard_history),1)
        self.assertEqual([r.outcome for r in g.state.draw_history],['hand','burned','burned'])

    def test_book_casts_when_drawn_before_discard_without_claiming_the_replacement(self):
        g=self.game((BOOK,),deck=(CAST,S1,M3,S2));self.play(g,BOOK)
        self.assertEqual(self.hand(g),(S1,M3));self.assertEqual(len(g.state.discard_history),1)
        self.assertEqual(len(g.state.cast_history),2)

    def test_book_moves_every_spell_before_first_discard_listener_and_recovers_exact_group(self):
        g=self.game((BOOK,FILL),deck=(S1,S2,M3),weapon=DISCARD_WAIT);self.play(g,BOOK)
        self.assertEqual(self.hand(g),(FILL,M3));self.assertEqual(len(g.state.discard_history),2)
        self.assertNotIn(FILL,json.dumps(g.for_player(2).observe()));g=self.rollback_choice(g)
        self.assertEqual(self.hand(g),(FILL,M3));self.assertEqual(len(g.state.discard_history),2)

    def test_book_discard_failure_rolls_back_payment_deck_all_draws_and_discard_history(self):
        g=self.game((BOOK,),deck=(S1,S2,M3),weapon=DISCARD_FAIL);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,BOOK)
        self.assertEqual(g.snapshot(),saved)

    def test_undersea_excludes_its_own_identity_and_summons_from_original_spell_cost(self):
        g=self.game((SEA,),deck=(SEA,S1,M2));source=self.play(g,SEA)
        self.assertEqual(self.hand(g),(S1,));self.assertEqual(self.board(g),(M3,))
        self.assertEqual(g.state.players[1].mana,4)
        cause=g.state.card_summon_history[-1].request.cause
        self.assertEqual((cause.origin,cause.source.entity_id),('spell_cast',source))

    def test_undersea_only_other_self_copies_in_deck_skip_without_fatigue_or_rng(self):
        g=self.game((SEA,),deck=(SEA,SEA,M3));before=g._rng.getstate();self.play(g,SEA)
        self.assertEqual(g._rng.getstate(),before);self.assertFalse(g.state.draw_history)
        self.assertFalse(self.board(g));self.assertEqual(g.state.players[1].fatigue,0)

    def test_undersea_uses_actual_pre_draw_stored_discount(self):
        g=self.game((SEA,REPRICE),deck=(S1,));self.play(g,REPRICE);self.play(g,SEA)
        self.assertEqual(self.entity(g,S1).cost,2);self.assertEqual(self.board(g),(M2,))

    def test_undersea_original_frozen_cost_survives_draw_wait_hand_reprice_and_replay(self):
        g=self.game((SEA,),deck=(S1,),weapon=WAIT);self.play(g,SEA)
        self.assertFalse(self.board(g));self.assertNotIn(S1,json.dumps(g.for_player(2).observe()))
        g=self.portable(g);self.choose(g,'change')
        self.assertEqual(self.entity(g,S1).cost,5);self.assertEqual(self.board(g),(M3,));self.portable(g)

    def test_undersea_burned_root_does_not_summon_under_declared_local_policy(self):
        g=self.game((SEA,),deck=(S1,),weapon=FILL_HAND,hand_cap=1);self.play(g,SEA)
        self.assertEqual(g.state.draw_history[0].outcome,'burned');self.assertFalse(self.board(g))

    def test_undersea_full_board_still_draws_without_inventing_entry_room(self):
        g=self.game((SEA,),deck=(S1,),board=(M2,)*7);self.play(g,SEA)
        self.assertEqual(self.hand(g),(S1,));self.assertEqual(len(self.board(g)),7)

    def test_undersea_draw_cast_cost_comes_from_root_not_different_cost_replacement(self):
        g=self.game((SEA,),deck=(CAST,S5),seed=1);self.play(g,SEA)
        self.assertEqual(g.state.draw_history[0].card_id,CAST)
        self.assertEqual(self.hand(g),(S5,));self.assertEqual(self.board(g),(M3,))

    def test_undersea_empty_complete_cost_domain_does_not_create_a_whiteboard(self):
        g=self.game((SEA,),deck=(S1,),mode='empty');self.play(g,SEA)
        self.assertEqual(self.hand(g),(S1,));self.assertFalse(self.board(g))

    def test_undersea_unknown_eligible_member_fails_without_cropping_and_rolls_back_root_draw(self):
        g=self.game((SEA,),deck=(S1,),mode='unknown');saved=g.snapshot()
        with self.assertRaises(ResolutionError) as caught:self.play(g,SEA)
        self.assertIsInstance(caught.exception.__cause__,UnsupportedDefinitionError)
        self.assertEqual(g.snapshot(),saved)

    def test_undersea_summon_wait_and_failed_choice_restore_original_root_and_cause(self):
        g=self.game((SEA,),deck=(S1,),weapon=SUMMON_WAIT);self.play(g,SEA)
        self.assertEqual(self.board(g),(M3,));g=self.rollback_choice(g)
        self.assertEqual(self.board(g),(M3,));self.assertEqual(len(g.state.draw_history),1)

    def test_real_local_host_executes_all_three_roots_with_complete_ordinary_minion_domain(self):
        f=build_cn37_local_pool_format();r=f.registry
        for cid,deck in ((SPRING,('CS2_024','CORE_EX1_162')),(BOOK,('CS2_024','CORE_EX1_162','CS2_029')),
                (SEA,(SEA,'CS2_024'))):
            g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(cid,),deck=deck,mana=10,max_mana=10),
                PlayerSetup('HERO_08',mana=10,max_mana=10)),seed=624,generation_context=f.context),r)
            self.play(g,cid)
            if cid==SPRING:self.assertEqual(g.state.players[1].mana,7)
            elif cid==BOOK:self.assertEqual(self.hand(g),('CORE_EX1_162',));self.assertEqual(len(g.state.discard_history),2)
            else:
                self.assertEqual(self.hand(g),('CS2_024',));self.assertEqual(len(self.board(g)),1)
                self.assertEqual(r.card(self.board(g)[0]).cost,2)


if __name__=='__main__':unittest.main()
