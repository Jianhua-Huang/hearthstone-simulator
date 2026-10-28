"""Actual Mage quest payments, owner turns, original decks and full rewards."""
from dataclasses import asdict
from functools import lru_cache
import json,unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import deck,metadata,registry as opening_registry,setup
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards import past_mage_quests as native
from hs_sim.cards.lost_city_quest_cards import WARP_USED
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayCard,PlayerSetup,ResolutionError,Scenario,SelectChoice,UseHeroPower
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (AddCostModifier,AddToHand,ChangeManaCrystals,ChoiceOption,
    InvokeBehavior,RequestChoice,SpendMana,Summon,Transform)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CardClass,CardDefinition,CardType,CostSpec,Keyword,OpeningHook,PaymentType,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.turn_scheduling import QueueTurns
from hs_sim.engine.zones import CardReference,CopyCard,ModifyStoredCost,MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format

DRACONIC,ALLIES,TEMPLE,WAYGATE=native.LEAVES
DRAGON,SCROLL=native.TOKENS
WARP=native.WARP
P='k625.'
S0,S1,S3,S7,S8,LOOP,EL,OTHER,FILL,NEUTRAL,WARRIOR,UNKNOWN=(P+x for x in
    ('spell0','spell1','spell3','spell7','spell8','loop','elemental','other','fill','neutral','warrior','unknown'))
DIRECT,MINION_DEBIT,HEALTH,AUTO,EXTRA,SUMMON_EL,ALTER_EL,DISCOUNT=(P+x for x in
    ('direct','minion_debit','health','auto','extra','summon_elemental','alter_elemental','discount'))
WAIT,FAIL,COUNTER,FULL_WATCH,BOOT=(P+x for x in('wait','fail','counter','full_watch','boot'))

def context(mode):return GenerationContext('k625-diagnostic-'+mode,'experimental')


@lru_cache(None)
def donor():return build_registry()


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();original=donor();warp=original.card(WARP)
    r.register_card(warp);r.register_pool_card(original.pool_cards[WARP])
    r.register_behavior(warp.on_play,original.behavior(warp.on_play))
    r.register_player_effect(original.player_effect(WARP_USED))
    native.register_past_mage_quests(r)
    r.register_behavior(P+'noop',lambda c:())
    for cid,cost,cls in ((S0,0,CardClass.MAGE),(S1,1,CardClass.MAGE),(S3,3,CardClass.MAGE),
            (S7,7,CardClass.MAGE),(S8,8,CardClass.MAGE),(NEUTRAL,3,CardClass.NEUTRAL),(WARRIOR,3,CardClass.WARRIOR)):
        card=CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=P+'noop',metadata=metadata(cls,tribes=()))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    for cid,tribes in ((EL,('elemental',)),(OTHER,()),(FILL,()),(ALTER_EL,('elemental',))):
        kw={'battlecry':ALTER_EL}if cid==ALTER_EL else{}
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=3,
            metadata=metadata(tribes=tribes),**kw))
    scripts={
        LOOP:lambda c:(AddToHand(c.player_id,LOOP,c.source_id),),
        DIRECT:lambda c:(SpendMana(c.player_id,8,c.source_id),),
        MINION_DEBIT:lambda c:(SpendMana(c.player_id,8,c.source_id),),
        HEALTH:lambda c:(AddCostModifier(c.player_id,CostSpec(payment=PaymentType.HEALTH,card_ids=(S3,))),),
        AUTO:lambda c:(CastSpell(c.player_id,S0,c.source_id),),
        EXTRA:lambda c:(QueueTurns((c.player_id,),c.source_id),),
        SUMMON_EL:lambda c:(Summon(c.player_id,EL),),
        ALTER_EL:lambda c:(Transform(c.source_id,FILL),),
        DISCOUNT:lambda c:(ModifyStoredCost(CardReference.capture(next(c.state.entities[i]
            for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==S8)),CostSpec(set_to=3),c.source_id),),
    }
    for cid,body in scripts.items():
        r.register_behavior(cid,body)
        if cid==ALTER_EL:continue
        minion=cid in (MINION_DEBIT,HEALTH,DISCOUNT)
        r.register_card(CardDefinition(cid,cid,CardType.MINION if minion else CardType.SPELL,
            health=3 if minion else 0,metadata=metadata(CardClass.MAGE,tribes=()),
            **({'battlecry':cid}if minion else{'on_play':cid})))
    members=[S3,NEUTRAL,WARRIOR,TEMPLE,WAYGATE]
    if mode=='empty':members.remove(S3)
    if mode=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,3,metadata(CardClass.MAGE,tribes=())))
        members.append(UNKNOWN)
    r.register_pool(PoolDefinition(native.POOL,'k625-full-diagnostic-'+mode,context(mode).target_id,
        context(mode).mode,tuple(PoolMember(cid)for cid in members),complete=True))
    def fail(c):raise ResolutionError('K625 deliberate reward reaction failure')
    r.register_behavior(FAIL,fail)
    def watch(c):
        event=c.event;target=c.state.entities.get(event.target_id);source=c.state.entities.get(event.source_id)
        relevant=(event.kind=='minion_summoned'and target.card_id==DRAGON or
            event.kind=='card_drawn'and source is not None and source.card_id==ALLIES or
            event.kind=='hero_power_replaced'and target.card_id==SCROLL or
            event.kind=='card_added_to_hand'and(target.card_id==WARP or
                target.card_id==S3 and source is not None and source.card_id==SCROLL))
        if not relevant:return ()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',
            (InvokeBehavior(FAIL,c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(WAIT,watch)
    r.register_card(CardDefinition(WAIT,WAIT,CardType.MINION,health=20,metadata=metadata(tribes=()),
        triggers=tuple(TriggerSpec(event,WAIT)for event in('minion_summoned','card_drawn','hero_power_replaced','card_added_to_hand'))))
    r.register_behavior(COUNTER,lambda c:(CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id!=c.player_id else ())
    r.register_card(CardDefinition(COUNTER,COUNTER,CardType.MINION,health=3,metadata=metadata(tribes=()),
        triggers=(TriggerSpec('card_committed',COUNTER),)))
    def fill_watch(c):
        if c.event.player_id!=c.player_id or c.state.entities[c.event.source_id].card_id!=LOOP:return ()
        quests=[c.state.entities[i]for i in c.state.players[c.player_id].quests]
        return tuple(AddToHand(c.player_id,FILL,c.source_id)for _ in range(10))if any(
            q.card_id==WAYGATE and q.quest_progress.value==7 for q in quests)else ()
    r.register_behavior(FULL_WATCH,fill_watch)
    r.register_card(CardDefinition(FULL_WATCH,FULL_WATCH,CardType.MINION,health=20,metadata=metadata(tribes=()),
        triggers=(TriggerSpec('card_committed',FULL_WATCH),)))
    def opening_spell(c):
        original_ids=c.state.opening.original_entities[c.player_id-1]
        return next(c.state.entities[i]for i in original_ids if c.state.entities[i].card_id==S0)
    def boot_copy(c):
        spell=opening_spell(c)
        work=[CopyCard(CardReference.capture(spell),c.player_id,source_id=c.source_id),AddToHand(c.player_id,LOOP,c.source_id)]
        if mode=='full':work.append(Summon(c.player_id,FULL_WATCH))
        if mode=='wait':work.append(Summon(c.player_id,WAIT))
        return tuple(work)
    def boot_move(c):
        spell=opening_spell(c);work=[]
        if spell.zone!=Zone.HAND:work.append(MoveCard(CardReference.capture(spell),c.player_id,Zone.HAND,source_id=c.source_id))
        return (*work,InvokeBehavior(BOOT+'.copy',c.source_id,c.player_id))
    def boot(c):
        spell=opening_spell(c)
        work=[ChangeManaCrystals(c.player_id,10,filled=True)]
        if mode=='replaced':work.append(TransformStoredCard(CardReference.capture(spell),S0,c.source_id))
        return (*work,InvokeBehavior(BOOT+'.move',c.source_id,c.player_id))
    r.register_behavior(BOOT+'.move',boot_move);r.register_behavior(BOOT+'.copy',boot_copy)
    r.register_behavior(BOOT,boot)
    r.register_card(CardDefinition(BOOT,BOOT,CardType.MINION,health=2,metadata=metadata(CardClass.MAGE,tribes=()),
        opening_hooks=(OpeningHook('after_mulligan',BOOT),)))
    r.validate();return r


class PastMageQuestTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,hand,*,board=(),deck_cards=(FILL,S3,FILL,S0,S1),enemy_hand=(),enemy_board=(),mode='normal',hand_cap=None):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=deck_cards,
            mana=30,max_mana=30,mana_cap=30,hand_cap=hand_cap,hero_power_card_id='mage.power'),
            PlayerSetup('warrior.hero',hand=enemy_hand,board=enemy_board,deck=(FILL,)*12,mana=30,max_mana=30,mana_cap=30,
                hero_power_card_id='warrior.power')),
            seed=625,generation_context=context(mode)),registry(mode))
    def opening(self,mode='normal'):
        self.mode=mode;r=registry(mode)
        cards=(WAYGATE,BOOT,S0)+tuple('card.'+str(i)for i in range(1,28))
        g=Game.from_decks(setup(r,decks=(deck(cards=cards),deck(CardClass.WARRIOR)),seed=625),r)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        return g
    def progress(self,g,source):return g.state.entities[source].quest_progress.value
    def hand(self,g,player=1):return tuple(g.state.entities[i].card_id for i in g.state.players[player].hand)
    def board(self,g):return tuple(g.state.entities[i].card_id for i in g.state.players[1].board)
    def next_owner_turn(self,g):
        g.apply(EndTurn(g.state.active_player))
        if g.state.active_player!=1:g.apply(EndTurn(g.state.active_player))
    def resolve_wait(self,g):
        g=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(saved,g.snapshot());self.choose(g);return g
    def complete_temple(self,g):
        source=self.play(g,TEMPLE)
        for _ in range(10):self.play(g,LOOP)
        return source

    def test_full_records_primary_faces_and_unchanged_native_time_warp(self):
        d=native.load_batch();rows={v['record']['id']:v['record']for v in d['dependencies']+d['existing_dependencies']}
        self.assertEqual(len(rows),7)
        for o in d['official_observations']:batch.check_face(rows[o['card_id']],o['face'],o['locale'])
        r=registry();self.assertEqual(asdict(r.card(WARP)),asdict(donor().card(WARP)))
        self.assertEqual(asdict(r.pool_cards[WARP]),asdict(donor().pool_cards[WARP]))
        self.assertFalse(d['source_scope_bound']);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        for cid,goal in zip(native.LEAVES,(8,2,10,8)):
            self.assertEqual((r.card(cid).cost,r.card(cid).quest.stages[0].goal),(1,goal))

    def test_draconic_actual_paid_seven_and_one_rewards_complete_six_six_dragon(self):
        g=self.game((DRACONIC,S7,S1));q=self.play(g,DRACONIC)
        self.assertEqual(self.progress(g,q),0);self.play(g,S7);self.assertEqual(self.progress(g,q),7)
        self.play(g,S1);self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD)
        dragon=self.entity(g,DRAGON,zone='board');self.assertEqual((dragon.attack,dragon.health),(6,6))
        self.assertEqual(g.registry.card(DRAGON).metadata.tribes,('dragon',));self.assertEqual(len(g.state.play_history),3)
        self.portable(g)

    def test_draconic_does_not_credit_earlier_payments_or_own_activation(self):
        g=self.game((S7,DRACONIC,S1));self.play(g,S7);q=self.play(g,DRACONIC);self.play(g,S1)
        self.assertEqual(self.progress(g,q),1)

    def test_draconic_uses_actual_discounted_mana_and_skips_zero_cast(self):
        g=self.game((DRACONIC,DISCOUNT,S8,S0));q=self.play(g,DRACONIC)
        self.play(g,DISCOUNT);self.play(g,S8);self.play(g,S0);self.assertEqual(self.progress(g,q),3)

    def test_draconic_health_payment_and_hero_power_and_minion_debit_do_not_count(self):
        g=self.game((DRACONIC,HEALTH,S3,MINION_DEBIT));q=self.play(g,DRACONIC)
        for cid in(HEALTH,S3,MINION_DEBIT):self.play(g,cid)
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual(self.progress(g,q),0);self.assertEqual(g.state.mana_consumption_history[0].actual,8)
        self.portable(g)

    def test_draconic_direct_spell_consumption_is_counted_once(self):
        g=self.game((DRACONIC,DIRECT));q=self.play(g,DRACONIC);self.play(g,DIRECT)
        self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD);self.assertEqual(self.board(g),(DRAGON,))
        self.assertEqual((len(g.state.mana_consumption_history),len(g.state.cast_history)),(1,2))
        self.portable(g)

    def test_draconic_other_players_mana_is_not_counted(self):
        g=self.game((DRACONIC,),enemy_hand=(S8,));q=self.play(g,DRACONIC);g.apply(EndTurn(1));self.play(g,S8,player=2)
        self.assertEqual(self.progress(g,q),0)

    def test_draconic_countered_payment_counts_and_reward_full_board_does_not_overfill(self):
        g=self.game((DRACONIC,S8),board=(FILL,)*7);q=self.play(g,DRACONIC);self.play(g,S8)
        self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD);self.assertEqual(self.board(g),(FILL,)*7)
        g=self.game((DRACONIC,S8),enemy_hand=(COUNTER,));q=self.play(g,DRACONIC)
        g.apply(EndTurn(1));self.play(g,COUNTER,player=2);g.apply(EndTurn(2));self.play(g,S8)
        self.assertTrue(g.state.play_history[-1].countered);self.assertIn(DRAGON,self.board(g))
        self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD)

    def test_draconic_summon_reward_waits_restores_and_rolls_back_bad_choice(self):
        g=self.game((DRACONIC,S8),board=(WAIT,));q=self.play(g,DRACONIC);self.play(g,S8)
        self.assertTrue(g.state.entities[q].quest_progress.completing);g=self.resolve_wait(g)
        self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD);self.assertIn(DRAGON,self.board(g))

    def test_allies_only_one_elemental_per_genuine_owner_turn(self):
        g=self.game((ALLIES,EL,EL));q=self.play(g,ALLIES);self.play(g,EL);self.play(g,EL)
        self.assertEqual(self.progress(g,q),1);self.assertEqual(len(g.state.entities[q].quest_progress.keys),1)
        self.portable(g)

    def test_allies_two_consecutive_owner_turns_tutor_three_original_spells(self):
        g=self.game((ALLIES,EL,EL));q=self.play(g,ALLIES);self.play(g,EL);self.next_owner_turn(g);self.play(g,EL)
        self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD)
        self.assertEqual({v.card_id for v in g.state.draw_history if v.source_id==q},{S3,S0,S1})
        self.assertEqual(len([v for v in g.state.draw_history if v.source_id==q]),3);self.portable(g)

    def test_allies_gap_resets_then_two_new_owner_turns_complete(self):
        g=self.game((ALLIES,EL,EL,EL));q=self.play(g,ALLIES);self.play(g,EL);self.next_owner_turn(g)
        self.next_owner_turn(g);self.assertEqual(self.progress(g,q),0)
        self.play(g,EL);self.next_owner_turn(g);self.play(g,EL);self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD)

    def test_allies_extra_turn_is_a_real_next_owner_turn(self):
        g=self.game((ALLIES,EL,EL,EXTRA));q=self.play(g,ALLIES);self.play(g,EL);self.play(g,EXTRA)
        g.apply(EndTurn(1));self.assertEqual(g.state.active_player,1);self.play(g,EL)
        self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD);self.portable(g)

    def test_allies_before_activation_and_summoned_elementals_do_not_count(self):
        g=self.game((EL,ALLIES,SUMMON_EL));self.play(g,EL);q=self.play(g,ALLIES);self.play(g,SUMMON_EL)
        self.assertEqual(self.progress(g,q),0)

    def test_allies_enemy_elemental_does_not_complete_or_reset_owner_credit(self):
        g=self.game((ALLIES,EL),enemy_hand=(EL,));q=self.play(g,ALLIES);self.play(g,EL)
        g.apply(EndTurn(1));self.play(g,EL,player=2);self.assertEqual(self.progress(g,q),1)
        g.apply(EndTurn(2));self.assertEqual(self.progress(g,q),1)

    def test_allies_uses_original_submitted_tribes_after_body_transformation(self):
        g=self.game((ALLIES,ALTER_EL));q=self.play(g,ALLIES);e=self.play(g,ALTER_EL)
        self.assertEqual(g.state.entities[e].card_id,FILL);self.assertEqual(self.progress(g,q),1);self.portable(g)

    def test_allies_no_matching_spells_does_not_invent_draws_or_fatigue(self):
        g=self.game((ALLIES,EL,EL),deck_cards=(FILL,)*8);q=self.play(g,ALLIES);self.play(g,EL)
        self.next_owner_turn(g);self.play(g,EL)
        self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD)
        self.assertFalse([v for v in g.state.draw_history if v.source_id==q])

    def test_allies_draw_reward_all_wait_positions_portable(self):
        g=self.game((ALLIES,EL,EL),board=(WAIT,));q=self.play(g,ALLIES);self.play(g,EL);self.next_owner_turn(g);self.play(g,EL)
        count=0
        while g.state.pending_choice:g=self.resolve_wait(g);count+=1
        self.assertEqual(count,3);self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD)

    def test_allies_tutor_uses_normal_capacity_and_burns_excess_original_spell(self):
        g=self.game((ALLIES,EL,EL),hand_cap=3);q=self.play(g,ALLIES);self.play(g,EL)
        self.next_owner_turn(g);self.play(g,EL)
        rows=[v for v in g.state.draw_history if v.source_id==q]
        self.assertEqual(len(rows),3);self.assertEqual(sum(v.outcome=='burned'for v in rows),1)
        self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD);self.portable(g)

    def test_temple_ten_actual_owner_casts_exclude_own_installation(self):
        g=self.game((TEMPLE,LOOP));q=self.play(g,TEMPLE);self.assertEqual(self.progress(g,q),0)
        for _ in range(9):self.play(g,LOOP)
        self.assertEqual(self.progress(g,q),9);self.play(g,LOOP)
        self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,SCROLL);self.portable(g)

    def test_temple_automatic_spell_counts_as_an_independent_actual_cast(self):
        g=self.game((TEMPLE,AUTO));q=self.play(g,TEMPLE);self.play(g,AUTO)
        self.assertEqual(self.progress(g,q),2)

    def test_temple_enemy_spells_do_not_count(self):
        g=self.game((TEMPLE,),enemy_hand=(S0,));q=self.play(g,TEMPLE);g.apply(EndTurn(1));self.play(g,S0,player=2)
        self.assertEqual(self.progress(g,q),0)

    def test_temple_countered_owner_cast_still_uses_existing_cast_attempt_policy(self):
        g=self.game((TEMPLE,S0),enemy_hand=(COUNTER,));q=self.play(g,TEMPLE)
        g.apply(EndTurn(1));self.play(g,COUNTER,player=2);g.apply(EndTurn(2));self.play(g,S0)
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(self.progress(g,q),1);self.portable(g)

    def test_scroll_uses_fixed_mage_spell_domain_and_two_less_local_cost(self):
        g=self.game((TEMPLE,LOOP));self.complete_temple(g);power=g.state.players[1].hero_power_id
        before=g.state.players[1].mana;g.apply(UseHeroPower(1,power))
        made=self.entity(g,S3);self.assertEqual((made.cost,g.state.players[1].mana),(1,before-2))
        self.assertNotIn(NEUTRAL,self.hand(g));self.assertNotIn(WARRIOR,self.hand(g))
        self.assertNotIn(TEMPLE,self.hand(g));self.assertNotIn(WAYGATE,self.hand(g));self.portable(g)

    def test_scroll_empty_eligible_domain_keeps_rng_and_creates_no_card(self):
        g=self.game((TEMPLE,LOOP),mode='empty');self.complete_temple(g)
        before=g.snapshot();g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual(self.hand(g),(LOOP,));self.assertEqual(g.snapshot()['rng_state'],before['rng_state'])

    def test_scroll_unknown_eligible_member_rejects_and_rolls_back_without_pool_truncation(self):
        g=self.game((TEMPLE,LOOP),mode='unknown');self.complete_temple(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError)as caught:g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertIsInstance(caught.exception.__cause__,UnsupportedDefinitionError);self.assertEqual(g.snapshot(),saved)
        self.assertIn(UNKNOWN,[v.card_id for v in g.registry.pool(native.POOL,context('unknown')).members])

    def test_temple_replacement_and_scroll_delivery_waits_are_recoverable(self):
        g=self.game((TEMPLE,LOOP),board=(WAIT,));q=self.complete_temple(g);g=self.resolve_wait(g)
        self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD)
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));g=self.resolve_wait(g)
        self.assertEqual(self.entity(g,S3).cost,1)

    def test_main_quests_are_mutually_exclusive_without_spending_second_payment(self):
        g=self.game((TEMPLE,WAYGATE,DRACONIC,ALLIES));self.play(g,TEMPLE);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,WAYGATE)
        self.assertEqual(g.snapshot(),saved)
        self.play(g,DRACONIC);self.play(g,ALLIES);self.assertEqual(len(g.state.players[1].quests),3)

    def test_waygate_actual_opening_original_face_excluded_and_same_face_copy_counts(self):
        g=self.opening();self.assertIn(WAYGATE,self.hand(g));q=self.play(g,WAYGATE)
        originals=set(g.state.opening.original_entities[0])
        original=next(i for i in g.state.players[1].hand if i in originals and g.state.entities[i].card_id==S0)
        copied=next(i for i in g.state.players[1].hand if i not in originals and g.state.entities[i].card_id==S0)
        g.apply(PlayCard(1,original));self.assertEqual(self.progress(g,q),0)
        g.apply(PlayCard(1,copied));self.assertEqual(self.progress(g,q),1);self.portable(g)

    def test_waygate_replaced_original_face_follows_explicit_existing_provenance_policy(self):
        g=self.opening('replaced');q=self.play(g,WAYGATE);originals=set(g.state.opening.original_entities[0])
        e=next(i for i in g.state.players[1].hand if i in originals and g.state.entities[i].card_id==S0)
        self.assertTrue(g.state.entities[e].face_replaced);g.apply(PlayCard(1,e))
        self.assertEqual(self.progress(g,q),1);self.portable(g)

    def test_waygate_eight_generated_casts_deliver_native_once_per_game_time_warp(self):
        g=self.opening();q=self.play(g,WAYGATE)
        for _ in range(8):self.play(g,LOOP)
        self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD);self.assertIn(WARP,self.hand(g))
        self.play(g,WARP);self.assertEqual(sum(x.spec_id==WARP_USED for x in g.state.players[1].player_effects),1)
        g.apply(EndTurn(1));self.assertEqual(g.state.active_player,1);self.portable(g)

    def test_waygate_full_hand_reward_stays_pending_then_delivers_when_real_space_opens(self):
        g=self.opening('full');q=self.play(g,WAYGATE)
        for _ in range(8):self.play(g,LOOP)
        self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD);self.assertNotIn(WARP,self.hand(g))
        self.assertEqual(g.state.quest_hand_rewards[-1].phase,'pending');g=self.portable(g)
        self.play(g,FILL);self.assertIn(WARP,self.hand(g));self.assertEqual(g.state.quest_hand_rewards[-1].phase,'delivered')
        self.portable(g)

    def test_waygate_unknown_opening_rejects_owned_cast_instead_of_guessing(self):
        g=self.game((WAYGATE,S0));self.play(g,WAYGATE);saved=g.snapshot()
        with self.assertRaises(ResolutionError)as caught:self.play(g,S0)
        self.assertIsInstance(caught.exception.__cause__,UnsupportedDefinitionError);self.assertEqual(g.snapshot(),saved)

    def test_waygate_opponent_cast_does_not_demand_our_unknown_opening(self):
        g=self.game((WAYGATE,),enemy_hand=(S0,));q=self.play(g,WAYGATE);g.apply(EndTurn(1));self.play(g,S0,player=2)
        self.assertEqual(self.progress(g,q),0)

    def test_waygate_reward_wait_restores_and_failure_choice_preserves_transaction(self):
        g=self.opening('wait');q=self.play(g,WAYGATE)
        for _ in range(8):self.play(g,LOOP)
        self.assertTrue(g.state.entities[q].quest_progress.completing);g=self.resolve_wait(g)
        self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD);self.assertIn(WARP,self.hand(g))

    def test_live_quest_keys_and_original_deck_material_do_not_leak_to_players(self):
        g=self.opening();q=self.play(g,WAYGATE);self.play(g,LOOP);self.assertEqual(self.progress(g,q),1)
        for p in(1,2):
            view=json.dumps(g.for_player(p).observe());self.assertNotIn('cast:',view)
            self.assertNotIn('original_entities',view);self.assertNotIn('quest_hand_rewards',view)
        self.portable(g)

    def test_complete_local_host_three_real_quest_entries_use_existing_public_slots(self):
        fmt=build_cn37_local_pool_format()
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(DRACONIC,ALLIES,TEMPLE,'BAR_542'),
            deck=('CS2_029',)*6,mana=10,max_mana=10),PlayerSetup('HERO_01')),generation_context=fmt.context),fmt.registry)
        self.play(g,DRACONIC);self.play(g,ALLIES);self.play(g,TEMPLE);self.play(g,'BAR_542')
        self.assertEqual(len(g.state.players[1].quests),3)
        self.assertEqual(self.progress(g,self.entity(g,DRACONIC,zone='quests').id),7)
        self.assertEqual(self.progress(g,self.entity(g,TEMPLE,zone='quests').id),1)
        for cid in native.DEPENDENCIES:self.assertIn(cid,fmt.registry.cards)
