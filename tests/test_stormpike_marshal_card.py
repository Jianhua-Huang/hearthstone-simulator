"""Actual Marshal through original damage facts, native price, and payments."""
import unittest
from dataclasses import replace
from functools import lru_cache

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.mimiron_reported_tech_cards import load_batch
from hs_sim.cards.stormpike_marshal_card import ROOT,PROFILE,register_stormpike_marshal_card
from hs_sim.engine import (CardDefinition,CardMetadata,CardClass,CardType,DamageKind,Game,Keyword,
    PlayerSetup,Registry,ResolutionError,Scenario,TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.actions import EndTurn
from hs_sim.engine.costs import (capture_cost_input,capture_generated_quote_fact,capture_quote_fact,quote_cost)
from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.effects import (AddCostModifier,AddToHand,ChoiceOption,Damage,GainArmor,
    Heal,InvokeBehavior,ModifyCost,RequestChoice,ReturnToHand)
from hs_sim.engine.hero_damage_taken_costs import validate_fact,validate_prefix
from hs_sim.engine.model import CostSpec,PaymentType
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from hs_sim.engine.zones import CardReference,CopyCard
from tools import card_batch as batch

P='k505.'
HERO,UNIT,WATCH,HEAL,ARMOR,TAX,DISCOUNT,LOCAL,LIFE,COPY,GENERATE,BOUNCE,FACE,EXTRA,SKIP=(P+s for s in
    ('hero','unit','watch','heal','armor','tax','discount','local','life','copy','generate','bounce','face','extra','skip'))
HURT={amount:P+'hurt'+str(amount) for amount in (0,1,3,4,5,6)}
META=CardMetadata(False,(CardClass.NEUTRAL,),None)


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=Registry(P+mode);register_stormpike_marshal_card(r)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=1000,metadata=META,
        keywords=(Keyword.IMMUNE,) if mode=='immune' else ()))
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,cost=2,attack=1,health=10,metadata=META))
    for amount,cid in HURT.items():
        r.register_behavior(cid,lambda c,n=amount:(Damage(
            c.state.players[3-c.player_id].hero_id if mode=='immune' else c.target_id,
            n,c.source_id,DamageKind.SPELL),))
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,requires_target=mode!='immune',metadata=META))
    scripts={
        HEAL:lambda c:(Heal(c.target_id,10,c.source_id),),
        ARMOR:lambda c:(GainArmor(c.player_id,8),),
        TAX:lambda c:(AddCostModifier(c.player_id,CostSpec(delta=2,card_ids=(ROOT,)),source_id=c.source_id),),
        DISCOUNT:lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-1,card_ids=(ROOT,)),source_id=c.source_id),),
        LOCAL:lambda c:(ModifyCost(c.target_id,CostSpec(set_to=7),c.source_id),),
        LIFE:lambda c:(AddCostModifier(c.player_id,CostSpec(payment=PaymentType.HEALTH,card_ids=(ROOT,)),source_id=c.source_id),),
        COPY:lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,mode='base',source_id=c.source_id),),
        GENERATE:lambda c:(AddToHand(c.player_id,ROOT,c.source_id),),
        BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        FACE:lambda c:(TransformCapturedMinion(CardReference.capture(c.state.entities[c.target_id]),ROOT,c.source_id),),
        EXTRA:lambda c:(QueueTurns((c.player_id,c.player_id),c.source_id),),
        SKIP:lambda c:(SkipTurns(3-c.player_id,1,c.source_id),),
    }
    for cid,body in scripts.items():
        r.register_behavior(cid,body)
        targeting=(TargetSpec(TargetMode.REQUIRED,zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')
            if cid in (LOCAL,COPY,FACE) else None)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,targeting=targeting,
            requires_target=cid in (HEAL,BOUNCE)))
    def fail(c):raise ResolutionError('K505 intentional late failure')
    r.register_behavior(P+'fail',fail)
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=ROOT:return ()
        if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if mode in ('wait','fail_choice'):
            return (Damage(c.state.players[c.player_id].hero_id,1,c.source_id),
                RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),),source_id=c.source_id,
                    on_select=P+'fail' if mode=='fail_choice' else None))
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=8,metadata=META,
        triggers=(TriggerSpec('minion_summoned',P+'watch'),)))
    return r


class StormpikeMarshalTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)
    mode='normal'

    def game(self,hand=(ROOT,),player=1,start=None,mode='normal',own=(),enemy=(),
            enemy_hand=None):
        self.mode=mode
        if mode in ('wait','fail','fail_choice'):own=(*own,WATCH)
        if enemy_hand is None:enemy_hand=(HURT[0],HURT[1],HURT[3],HURT[3],HURT[4],HURT[5],HURT[6],HEAL)
        players=tuple(PlayerSetup(HERO,hand=hand if p==player else enemy_hand,
            board=own if p==player else enemy,deck=(UNIT,)*8,
            mana=30,max_mana=30,mana_cap=30) for p in (1,2))
        return Game.from_scenario(Scenario(players,active_player=start or 3-player,seed=505),fixture(mode))

    def price(self,g,player=1):return quote_cost(g.state,g.registry,self.entity(g,ROOT,player)).amount

    def damage(self,g,n=5,owner=1,actor=2,target=None):
        if self.mode=='immune':return self.play(g,HURT[n],player=actor)
        return self.play(g,HURT[n],target if target is not None else g.state.players[owner].hero_id,actor)

    def fact(self,g,player=1):
        return capture_quote_fact(g.state,g.registry,capture_cost_input(self.entity(g,ROOT,player))).intrinsic.hero_damage_taken

    def qualify(self,g,player=1):
        self.damage(g,owner=player,actor=3-player);g.apply(EndTurn(3-player))
        self.assertEqual(self.price(g,player),1)

    def test_full_reused_original_face_and_pending_mimiron_scope(self):
        data=load_batch();raw=next(v['record'] for v in data['evidence_only'] if v['record']['id']==ROOT)
        faces=[o for o in data['official_observations'] if o['card_id']==ROOT]
        self.assertEqual(len(faces),2)
        for o in faces:batch.check_face(raw,o['face'],o['locale'])
        r=batch.registration_prefix(build_registry,'hs_sim.cards.stormpike_marshal_card.register_stormpike_marshal_card',
            register_stormpike_marshal_card,after=True);card=r.card(ROOT)
        self.assertEqual((card.cost,card.attack,card.health,card.metadata),(raw['cost'],raw['attack'],raw['health'],metadata_from_record(raw)))
        self.assertEqual((card.cost,card.attack,card.health),(4,2,6));self.assertEqual(card.keywords,(Keyword.TAUNT,))
        self.assertEqual(card.hero_damage_taken_cost.profile_id,PROFILE)
        self.assertIn(ROOT,r.pool_cards)
        with self.assertRaises(UnsupportedDefinitionError):r.card('BE_588')

    def test_both_players_take_five_then_pay_one_and_enter_as_two_six_taunt(self):
        for p in (1,2):
            with self.subTest(player=p):
                g=self.game(player=p);self.assertEqual(self.price(g,p),4)
                self.damage(g,owner=p,actor=3-p);self.assertEqual(self.price(g,p),4)
                g.apply(EndTurn(3-p));self.assertEqual(self.price(g,p),1)
                before=g.state.players[p].mana;source=self.play(g,ROOT,player=p)
                self.assertEqual(g.state.players[p].mana,before-1)
                entity=g.state.entities[source];self.assertEqual((entity.attack,entity.health),(2,6))
                self.assertIn(Keyword.TAUNT,entity.keywords)

    def test_four_five_and_six_actual_damage_use_threshold_not_subtraction(self):
        for damage,price in ((4,4),(5,1),(6,1)):
            with self.subTest(damage=damage):
                g=self.game();self.damage(g,damage);g.apply(EndTurn(2))
                self.assertEqual((self.price(g),self.fact(g).quantity),(price,damage))

    def test_multiple_packets_sum_actual_damage_within_same_opponent_turn(self):
        g=self.game();self.damage(g,3);self.damage(g,1)
        self.damage(g,3);g.apply(EndTurn(2))
        self.assertEqual((self.price(g),self.fact(g).quantity),(1,7))

    def test_damage_on_separate_opponent_turns_does_not_accumulate(self):
        g=self.game();self.damage(g,3);g.apply(EndTurn(2));self.assertEqual(self.price(g),4)
        g.apply(EndTurn(1));self.damage(g,3);g.apply(EndTurn(2))
        self.assertEqual((self.price(g),self.fact(g).quantity),(4,3))

    def test_armor_damage_counts_without_health_loss(self):
        g=self.game(hand=(ROOT,ARMOR),start=1);self.play(g,ARMOR);g.apply(EndTurn(1))
        self.damage(g);hero=g.state.entities[g.state.players[1].hero_id]
        self.assertEqual((hero.health,hero.armor),(1000,3));g.apply(EndTurn(2))
        self.assertEqual((self.price(g),self.fact(g).quantity),(1,5))

    def test_immunity_and_zero_packets_do_not_satisfy_threshold(self):
        g=self.game(mode='immune');self.damage(g);self.damage(g,0);g.apply(EndTurn(2))
        self.assertEqual((self.price(g),self.fact(g).quantity),(4,0))

    def test_minion_or_opponents_hero_damage_is_not_own_hero_damage(self):
        g=self.game(enemy=(UNIT,));target=self.entity(g,UNIT,2,'board').id
        self.damage(g,5,target=target);self.damage(g,6,owner=2);g.apply(EndTurn(2))
        self.assertEqual((self.price(g),self.fact(g).quantity),(4,0))

    def test_damage_taken_on_own_turn_does_not_qualify(self):
        g=self.game(hand=(ROOT,HURT[5]),start=1);self.damage(g,actor=1)
        self.assertEqual(self.price(g),4);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual((self.price(g),self.fact(g).quantity),(4,0))

    def test_healing_received_after_damage_does_not_erase_damage_operand(self):
        g=self.game();self.damage(g);self.play(g,HEAL,g.state.players[1].hero_id,2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,1000)
        g.apply(EndTurn(2));self.assertEqual((self.price(g),self.fact(g).quantity),(1,5))

    def test_card_generated_after_damage_uses_current_shared_history(self):
        g=self.game(hand=(GENERATE,));self.damage(g);g.apply(EndTurn(2));self.play(g,GENERATE)
        self.assertEqual(self.price(g),1)
        quote=capture_generated_quote_fact(g.state,g.registry,1,ROOT)
        self.assertEqual((quote.intrinsic.hero_damage_taken.quantity,quote.intrinsic.hero_damage_taken.after),(5,1))

    def test_base_copy_and_hand_transform_requote_original_native_condition(self):
        g=self.game(hand=(ROOT,UNIT,COPY,FACE));self.qualify(g)
        self.play(g,COPY,self.entity(g,ROOT).id);self.play(g,FACE,self.entity(g,UNIT).id)
        roots=[g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id==ROOT]
        self.assertEqual(len(roots),3)
        self.assertEqual([quote_cost(g.state,g.registry,e).amount for e in roots],[1,1,1])

    def test_returned_source_retains_turn_condition_but_does_not_cache_discount(self):
        g=self.game(hand=(ROOT,BOUNCE));self.qualify(g);source=self.play(g,ROOT)
        self.play(g,BOUNCE,source);self.assertEqual(self.price(g),1)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(self.price(g),4)

    def test_fixed_native_stage_precedes_local_assignment_and_external_modifiers(self):
        g=self.game(hand=(ROOT,TAX,DISCOUNT,LOCAL));self.qualify(g)
        self.play(g,TAX);self.assertEqual(self.price(g),3)
        self.play(g,DISCOUNT);self.assertEqual(self.price(g),2)
        self.play(g,LOCAL,self.entity(g,ROOT).id);self.assertEqual(self.price(g),8)
        self.assertEqual(self.fact(g).after,1)
        before=g.state.players[1].mana;self.play(g,ROOT)
        self.assertEqual(g.state.players[1].mana,before-8)

    def test_actual_health_payment_uses_one_with_original_native_proof(self):
        g=self.game(hand=(ROOT,LIFE));self.qualify(g);self.play(g,LIFE)
        before=g.state.players[1].mana;health=g.state.entities[g.state.players[1].hero_id].health
        self.play(g,ROOT)
        self.assertEqual(g.state.players[1].mana,before)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,health-1)
        fact=g.state.play_history[-1].submitted_cost.quote.intrinsic.hero_damage_taken
        self.assertEqual((fact.quantity,fact.before,fact.after),(5,4,1))

    def test_own_extra_turn_requotes_most_recent_actual_turn_without_stale_damage(self):
        g=self.game(hand=(ROOT,EXTRA));self.qualify(g);self.play(g,EXTRA)
        g.apply(EndTurn(1));self.assertEqual(g.state.active_player,1)
        self.assertEqual((self.price(g),self.fact(g).quantity),(4,0))

    def test_skipped_slot_is_not_a_damage_turn_and_does_not_reuse_old_hits(self):
        g=self.game(hand=(ROOT,SKIP));self.qualify(g);self.play(g,SKIP)
        g.apply(EndTurn(1));self.assertEqual(g.state.active_player,1)
        self.assertEqual((self.price(g),self.fact(g).quantity),(4,0))

    def test_opponent_extra_turn_reads_only_preceding_actual_damage_interval(self):
        g=self.game(enemy_hand=(EXTRA,HURT[5],HURT[4]));self.play(g,EXTRA,player=2)
        self.damage(g);g.apply(EndTurn(2));self.assertEqual(g.state.active_player,2)
        self.assertEqual((self.price(g),self.fact(g).quantity),(1,5))
        self.damage(g,4);g.apply(EndTurn(2));self.assertEqual(g.state.active_player,2)
        self.assertEqual((self.price(g),self.fact(g).quantity),(4,4))
        g.apply(EndTurn(2));self.assertEqual((g.state.active_player,self.price(g)),(1,4))

    def test_query_is_pure_and_original_packet_prefix_cannot_be_rewritten(self):
        g=self.game();self.qualify(g);saved=g.snapshot();f=self.fact(g)
        for _ in range(3):self.assertEqual(self.price(g),1)
        self.assertEqual(g.snapshot(),saved);validate_fact(g.registry,g.registry.card(ROOT),f)
        validate_prefix(f,g.state,g.registry)
        for changes in (dict(quantity=4,after=1),dict(quantity=6,after=1),dict(after=0)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(f,**changes)

    def test_paid_waiting_restore_clone_replay_retains_original_quote_after_later_damage(self):
        g=self.game(mode='wait');self.qualify(g);self.play(g,ROOT)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.players[1].mana,29)
        self.assertEqual(len(g.state.damage_history),2);self.portable(g)
        f=g.state.play_history[-1].submitted_cost.quote.intrinsic.hero_damage_taken
        self.assertEqual((f.quantity,f.after,len(f.records)),(5,1,1));validate_prefix(f,g.state,g.registry)
        self.choose(g);self.assertEqual(g.state.players[1].mana,29)

    def test_late_failure_rolls_back_entire_payment_and_preserves_preexisting_damage(self):
        g=self.game(mode='fail');self.qualify(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,ROOT)
        self.assertEqual(g.snapshot(),saved);self.assertEqual(self.price(g),1)

    def test_failed_choice_keeps_original_paid_wait_and_private_packet_proof(self):
        g=self.game(mode='fail_choice');self.qualify(g);self.play(g,ROOT);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),saved);self.portable(g)
