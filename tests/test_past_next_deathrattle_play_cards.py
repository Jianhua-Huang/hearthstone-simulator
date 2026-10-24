"""Real next-Deathrattle payment and original minion residence, via real plays."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.past_next_deathrattle_play_cards import (
    SHAMBLER,load_batch,register_past_next_deathrattle_play_cards)
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,
    IllegalAction,Keyword,PlayCard,PlayerSetup,Registry,Scenario,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.effects import (AddCostModifier,ChangeControl,ChoiceOption,CopyMinion,Destroy,
    Damage,GainArmor,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import AppendageSpec,CostSpec,RewindSpec
from hs_sim.engine.costs import capture_cost_input,quote_input
from hs_sim.engine.interrupts import CounterMinion
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.zones import CardReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.serialization import canonical_hash
from tools import card_batch as batch

P='k494.'
HERO,POWER,A,R,ZERO,WATCH,COUNTER=(P+x for x in('hero','power','plain','rattle','zero','watch','counter'))
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=Registry(P+mode);register_past_next_deathrattle_play_cards(r)
    r.register_behavior(P+'empty',lambda c:())
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=100,initial_hero_power=POWER,metadata=META))
    r.register_card(CardDefinition(POWER,POWER,CardType.HERO_POWER,on_use=P+'empty',metadata=META))
    r.register_card(CardDefinition(A,A,CardType.MINION,cost=4,attack=2,health=8,metadata=META))
    def fail(c):raise ResolutionError('K494 deliberate native failure')
    r.register_behavior(P+'fail',fail)
    def reenter(c):
        return(SummonStoredCard(CardReference.capture(c.source),c.player_id,cause=SummonCause.capture(c)),)
    r.register_behavior(P+'reenter',reenter)
    def battlecry(c):
        if mode!='bc_wait':return(GainArmor(c.player_id,2),)
        return(GainArmor(c.player_id,2),RequestChoice(c.player_id,(
            ChoiceOption('continue','Continue'),ChoiceOption('bounce','Bounce',(ReturnToHand(c.source_id),)),
            ChoiceOption('reenter','New residence',(ReturnToHand(c.source_id),InvokeBehavior(P+'reenter',c.source_id,c.player_id))),
            ChoiceOption('transform','Transform',(Transform(c.source_id,A),)),
            ChoiceOption('give','Give',(ChangeControl(c.source_id,3-c.player_id),)),
            ChoiceOption('copy','Copy',(CopyMinion(c.source_id,c.player_id),))),c.source_id))
    def deathrattle(c):
        if mode=='order'and c.state.entities[c.state.players[c.player_id].hero_id].armor<2:
            raise ResolutionError('The original Battlecry must finish before this paid death')
        return(GainArmor(c.player_id,5),)
    r.register_behavior(P+'bc',battlecry);r.register_behavior(P+'dr',deathrattle)
    r.register_card(CardDefinition(R,R,CardType.MINION,cost=3,attack=2,health=3,
        battlecry=P+'bc',deathrattle=P+'dr',metadata=META))
    r.register_card(CardDefinition(ZERO,ZERO,CardType.MINION,cost=0,attack=1,health=1,
        deathrattle=P+'dr',metadata=META))
    r.register_behavior(P+'lethal',lambda c:(Damage(c.state.players[3-c.player_id].hero_id,200,c.source_id),))
    r.register_card(CardDefinition(P+'terminal','Terminal',CardType.MINION,cost=2,attack=1,health=1,
        battlecry=P+'bc',deathrattle=P+'lethal',metadata=META))
    r.register_card(CardDefinition(P+'colossal','Colossal',CardType.MINION,cost=5,attack=2,health=3,
        battlecry=P+'bc',deathrattle=P+'dr',keywords=(Keyword.COLOSSAL,),colossal=(AppendageSpec(A),),metadata=META))
    for key,body in dict(silence=lambda c:(Silence(c.target_id),),kill=lambda c:(Destroy(c.target_id,c.source_id),),
            give=lambda c:(ChangeControl(c.target_id,3-c.state.entities[c.target_id].controller),)).items():
        r.register_behavior(P+key,body);r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    r.register_behavior(P+'summon',lambda c:(Summon(c.player_id,R),))
    r.register_card(CardDefinition(P+'summon','Summon',CardType.SPELL,on_play=P+'summon',metadata=META))
    r.register_card(CardDefinition(P+'retry',R,CardType.MINION,cost=3,attack=2,health=3,battlecry=P+'bc',deathrattle=P+'dr',
        keywords=(Keyword.REWIND,),rewind=RewindSpec(),metadata=META))
    def watch(c):
        if c.state.entities[c.event.target_id].card_id not in(R,P+'retry',P+'colossal'):return ()
        if mode=='death_fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if mode!='death_wait':return ()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,metadata=META,
        triggers=(TriggerSpec('minion_died',WATCH),)))
    r.register_behavior(COUNTER,lambda c:(CounterMinion(dict(c.event.data)['window_id']),)if
        c.state.entities[c.event.source_id].card_id==R else())
    r.register_card(CardDefinition(COUNTER,COUNTER,CardType.MINION,health=10,metadata=META,
        triggers=(TriggerSpec('minion_counter_check',COUNTER),)))
    r.validate();return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in
        ('schema_version','events','events_hash','state_hash')})
    return saved


class PastNextDeathrattlePlayTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)

    def game(self,hand=(),*,board=(),enemy=(),mode='normal',mana=40):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=tuple(hand),board=tuple(board),deck=(A,)*15,
            mana=mana,max_mana=40,mana_cap=40),PlayerSetup(HERO,board=tuple(enemy),deck=(A,)*15,mana=40,max_mana=40,mana_cap=40)),
            seed=494),fixture(mode))
    def board(self,g,cid=SHAMBLER,p=1):return self.entity(g,cid,p,zone='board')
    def armor(self,g,p=1):return g.state.entities[g.state.players[p].hero_id].armor
    def activate(self,g):return self.play(g,SHAMBLER)
    def price(self,g,cid=R):return g.quote_cost(self.entity(g,cid).id).amount

    def test_full_original_row_both_primary_faces_and_no_own_deathrattle(self):
        d=load_batch();raw=d['dependencies'][0]['record'];self.assertEqual(raw['id'],SHAMBLER)
        self.assertEqual(len(d['official_observations']),2)
        for o in d['official_observations']:
            self.assertEqual(batch.sha(o['response_file']),o['response_sha256']);batch.check_face(raw,o['face'],o['locale'])
        self.assertIsNone(fixture().card(SHAMBLER).deathrattle)
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_actual_constructed_boundary_adds_exact_one_definition(self):
        from hs_sim.cards import build_registry
        r=batch.registration_prefix(build_registry,
            'hs_sim.cards.past_next_deathrattle_play_cards.register_past_next_deathrattle_play_cards',
            register_past_next_deathrattle_play_cards,after=True)
        self.assertEqual(len(r.cards),2695);self.assertEqual(r.card(SHAMBLER),fixture().card(SHAMBLER))

    def test_paid_source_creates_one_deathrattle_price_and_previews_do_not_consume(self):
        g=self.game((SHAMBLER,R,A));source=self.activate(g)
        self.assertEqual((g.state.players[1].mana,self.board(g).attack,self.board(g).max_health),(39,1,3))
        for _ in range(3):self.assertEqual(self.price(g),2);self.assertEqual(self.price(g,A),4)
        m=g.state.players[1].cost_modifiers[0];self.assertEqual((m.uses_remaining,m.source_id),(1,source))
        self.assertTrue(m.deathrattle_only and m.destroy_after_play);self.portable(g)

    def test_plain_minion_does_not_consume_and_next_qualified_play_dies(self):
        g=self.game((SHAMBLER,A,R));self.activate(g);self.play(g,A)
        self.assertEqual(len(g.state.players[1].cost_modifiers),1);source=self.play(g,R)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.armor(g),7)
        self.assertEqual(g.state.players[1].cost_modifiers,[]);self.assertEqual(g.state.players[1].mana,33);self.portable(g)

    def test_original_battlecry_finishes_before_deathrattle(self):
        g=self.game((SHAMBLER,R),mode='order');self.activate(g);self.play(g,R)
        self.assertEqual(self.armor(g),7);self.assertEqual(len(g.state.death_history),1)

    def test_multiple_real_sources_stack_prices_but_destroy_one_physical_minion(self):
        g=self.game((SHAMBLER,SHAMBLER,R));self.activate(g);self.activate(g)
        self.assertEqual(self.price(g),1);self.play(g,R)
        self.assertEqual((g.state.players[1].mana,len(g.state.death_history),self.armor(g)),(37,1,7))
        self.assertEqual(len(g.state.cost_use_history[-1].consumable_ids),2);self.portable(g)

    def test_zero_price_still_consumes_and_destroys(self):
        g=self.game((SHAMBLER,ZERO));self.activate(g);self.assertEqual(self.price(g,ZERO),0)
        source=self.play(g,ZERO);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.players[1].mana,39);self.assertFalse(g.state.players[1].cost_modifiers)

    def test_ordinary_summon_does_not_consume_or_destroy(self):
        g=self.game((SHAMBLER,P+'summon',R));self.activate(g);self.play(g,P+'summon')
        self.assertEqual(len(g.state.players[1].cost_modifiers),1);self.assertEqual(self.board(g,R).health,3)
        self.assertFalse(g.state.death_history);self.assertEqual(self.price(g),2)

    def test_delivered_modifier_survives_source_silence_death_and_control_change(self):
        for spell in('silence','kill','give'):
            g=self.game((SHAMBLER,P+spell,R));source=self.activate(g);self.play(g,P+spell,source)
            self.assertEqual(self.price(g),2);target=self.play(g,R);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
            self.assertFalse(g.state.players[1].cost_modifiers)

    def test_unused_modifier_has_no_implicit_end_of_turn_expiry(self):
        g=self.game((SHAMBLER,R));self.activate(g);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(self.price(g),2);self.play(g,R);self.assertFalse(g.state.players[1].cost_modifiers);self.portable(g)

    def test_insufficient_payment_rolls_back_and_keeps_original_use(self):
        g=self.game((SHAMBLER,R),mana=1);self.activate(g);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,R)
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.price(g),2)

    def test_current_physical_abilities_override_the_printed_qualification(self):
        g=self.game((SHAMBLER,R,A));self.activate(g)
        value=capture_cost_input(self.entity(g,R));empty=replace(value,abilities=())
        self.assertEqual(quote_input(g.state,g.registry,empty).amount,3)
        other=replace(capture_cost_input(self.entity(g,A)),abilities=value.abilities)
        self.assertEqual(quote_input(g.state,g.registry,other).amount,3)
        self.assertEqual(len(g.state.players[1].cost_modifiers),1)

    def test_countered_original_consumes_price_but_creates_no_death(self):
        g=self.game((SHAMBLER,R),enemy=(COUNTER,));self.activate(g);source=self.play(g,R)
        self.assertEqual(g.state.play_history[-1].minion_result,'countered')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertFalse(g.state.death_history)
        self.assertFalse(g.state.players[1].cost_modifiers);self.assertEqual(self.armor(g),0);self.portable(g)

    def test_battlecry_wait_serializes_original_paid_death_and_resumes(self):
        g=self.game((SHAMBLER,R),mode='bc_wait');self.activate(g);self.play(g,R)
        self.assertIn('DestroyPaidMinion',json.dumps(g.snapshot()['resolution_frame']))
        other=self.portable(g);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(self.armor(g),7);self.portable(g)

    def test_bounced_original_is_not_destroyed_in_hand(self):
        g=self.game((SHAMBLER,R),mode='bc_wait');self.activate(g);source=self.play(g,R);self.choose(g,'bounce')
        self.assertEqual(g.state.entities[source].zone,Zone.HAND);self.assertFalse(g.state.death_history)
        self.assertFalse(g.state.players[1].cost_modifiers)

    def test_same_entity_reentering_during_battlecry_is_a_different_residence(self):
        g=self.game((SHAMBLER,R),mode='bc_wait');self.activate(g);source=self.play(g,R)
        presence=g.state.entities[source].board_presence_id;self.choose(g,'reenter')
        self.assertNotEqual(g.state.entities[source].board_presence_id,presence)
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.assertFalse(g.state.death_history);self.portable(g)

    def test_in_place_transformation_still_uses_original_residence(self):
        g=self.game((SHAMBLER,R),mode='bc_wait');self.activate(g);source=self.play(g,R);self.choose(g,'transform')
        self.assertEqual((g.state.entities[source].card_id,g.state.entities[source].zone),(A,Zone.GRAVEYARD))
        self.assertEqual(self.armor(g),2);self.portable(g)

    def test_control_transfer_preserves_original_residence_and_real_death_controller(self):
        g=self.game((SHAMBLER,R),mode='bc_wait');self.activate(g);source=self.play(g,R);self.choose(g,'give')
        self.assertEqual((g.state.entities[source].zone,g.state.death_history[-1].controller),(Zone.GRAVEYARD,2))
        self.assertEqual((self.armor(g),self.armor(g,2)),(2,5));self.portable(g)

    def test_current_board_copy_is_not_the_original_paid_death_target(self):
        g=self.game((SHAMBLER,R),mode='bc_wait');self.activate(g);source=self.play(g,R);self.choose(g,'copy')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        copies=[i for i in g.state.players[1].board if g.state.entities[i].card_id==R]
        self.assertEqual(len(copies),1);self.assertNotEqual(copies[0],source)

    def test_actual_death_wait_and_failed_choice_keep_one_paid_death(self):
        g=self.game((SHAMBLER,R),board=(WATCH,),mode='death_wait');self.activate(g);self.play(g,R)
        before=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_colossal_delayed_body_keeps_full_proofs_through_paid_death_wait(self):
        g=self.game((SHAMBLER,P+'colossal'),board=(WATCH,),mode='death_wait')
        self.activate(g);source=self.play(g,P+'colossal')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertIsNotNone(g.state.pending_choice)
        self.assertIn('FinishBattlecryAcceptance',json.dumps(g.snapshot()['resolution_frame']))
        other=self.portable(g);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(self.armor(g),7);self.assertEqual(g.state.players[1].mana,35)
        self.assertEqual(self.board(g,A).card_id,A);self.portable(g)

    def test_late_death_failure_restores_hand_payment_modifier_and_birth(self):
        g=self.game((SHAMBLER,R),board=(WATCH,),mode='death_fail');self.activate(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,R)
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.price(g),2);self.portable(g)

    def test_paid_death_terminal_abandons_remaining_proofs_without_losing_payment(self):
        g=self.game((SHAMBLER,P+'terminal'));self.activate(g);self.play(g,P+'terminal')
        self.assertEqual(g.state.winner,1);self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertEqual(g.state.players[1].mana,38);self.portable(g)

    def test_real_rewind_reclaims_original_price_once_and_keeps_sparse_death(self):
        g=self.game((SHAMBLER,P+'retry'));self.activate(g);self.play(g,P+'retry');self.choose(g,'retry')
        self.assertFalse(g.state.players[1].cost_modifiers);self.assertEqual(self.armor(g),7)
        self.assertEqual(g.state.players[1].mana,37);self.assertGreater(g.state.death_history[-1].id,len(g.state.death_history));self.portable(g)

    def test_invalid_death_selectors_and_unsourced_followups_are_rejected(self):
        spec=CostSpec(delta=-1,card_types=(CardType.MINION,))
        for kw in(dict(deathrattle_only=True),dict(source_id=1,destroy_after_play=True),
                dict(source_id=1,deathrattle_only=True,destroy_after_play=True,combo_only=True)):
            with self.subTest(kw=kw),self.assertRaises(ValueError):AddCostModifier(1,spec,uses_remaining=1,**kw)

    def test_rehashed_queued_original_entry_and_paid_flag_edits_are_rejected(self):
        g=self.game((SHAMBLER,R),mode='bc_wait');self.activate(g);self.play(g,R);saved=g.snapshot()
        def find(value):
            if isinstance(value,dict):
                if str(value.get('type','')).endswith('.DestroyPaidMinion'):return value
                for v in value.values():
                    hit=find(v)
                    if hit:return hit
            elif isinstance(value,list):
                for v in value:
                    hit=find(v)
                    if hit:return hit
        for kind in('entry','price'):
            bad=deepcopy(saved)
            if kind=='entry':
                item=find(bad['resolution_frame']);self.assertIsNotNone(item)
                fields=item['fields'];fields['entry']['fields']['next_order']=g.state.next_order+20
            else:bad['state']['cost_use_history'][-1]['player_modifiers'][0]['destroy_after_play']=False
            with self.subTest(kind=kind),self.assertRaises(SnapshotError):
                Game.from_snapshot(rehash(bad),fixture('bc_wait','forgery'))
        self.portable(g)
