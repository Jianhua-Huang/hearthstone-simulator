"""Real Ivus over existing resource records and original-residence rewards."""
from copy import deepcopy
from functools import lru_cache
import json,random,unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.past_remaining_mana_rewards_cards import BODY,IVUS,load_batch,register_past_remaining_mana_rewards_cards
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,
    PlayerSetup,Registry,Scenario,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.effects import (AddCostModifier,ChoiceOption,GrantKeyword,InvokeBehavior,
    RefreshMana,RequestChoice,ReturnToHand,Summon)
from hs_sim.engine.model import BattlecryRepeatSpec,CostSpec,RewindSpec
from hs_sim.engine.bonus_effects import GrantManaRandomGrowth,MANA_GROWTH_KEYWORDS
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.serialization import canonical_hash,rng_from_json
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from tools import card_batch as batch

P='k495.'
HERO,POWER,A,WATCH,DOUBLE=(P+x for x in('hero','power','plain','watch','double'))
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=Registry(P+mode);register_past_remaining_mana_rewards_cards(r)
    r.register_behavior(P+'empty',lambda c:())
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=100,initial_hero_power=POWER,metadata=META))
    r.register_card(CardDefinition(POWER,POWER,CardType.HERO_POWER,on_use=P+'empty',metadata=META))
    r.register_card(CardDefinition(A,A,CardType.MINION,attack=1,health=10,metadata=META))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=10,metadata=META,
        battlecry_repeats=(BattlecryRepeatSpec(2),)))
    r.register_card(CardDefinition(P+'retry','Synthetic mana-reward retry probe',CardType.MINION,cost=1,attack=1,health=1,
        battlecry=BODY,keywords=(Keyword.REWIND,),rewind=RewindSpec(),metadata=META))
    def fail(c):raise ResolutionError('K495 deliberate late reward failure')
    r.register_behavior(P+'fail',fail)
    def reenter(c):return(SummonStoredCard(CardReference.capture(c.source),c.player_id,cause=SummonCause.capture(c)),)
    r.register_behavior(P+'reenter',reenter)
    scripts=dict(discount=lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-1,card_types=(CardType.MINION,),
        card_ids=(IVUS,)),uses_remaining=1,source_id=c.source_id),),summon=lambda c:(Summon(c.player_id,IVUS),))
    for key,body in scripts.items():
        r.register_behavior(P+key,body);r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,metadata=META))
    def watch(c):
        e=c.event
        if e.source_id is None or c.state.entities[e.source_id].card_id!=IVUS:return ()
        if e.kind=='mana_consumed':
            if mode=='refund'and len(c.state.mana_consumption_history)==1:return(RefreshMana(c.player_id,2),)
            if mode=='pre_keywords':return tuple(GrantKeyword(e.source_id,k,c.source_id)for k in MANA_GROWTH_KEYWORDS)
            if mode=='pre_charge':return(GrantKeyword(e.source_id,Keyword.CHARGE,c.source_id),)
            if mode in('spend_wait','reenter'):
                if mode=='reenter':return(ReturnToHand(e.source_id),InvokeBehavior(P+'reenter',e.source_id,c.player_id))
                return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                    ChoiceOption('bounce','Bounce',(ReturnToHand(e.source_id),)),
                    ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        if e.kind=='random_choice'and'mana_id'in dict(e.data):
            if mode=='roll_fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode=='roll_wait':return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        return ()
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,metadata=META,
        triggers=(TriggerSpec('mana_consumed',WATCH),TriggerSpec('random_choice',WATCH))))
    r.validate();return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in
        ('schema_version','events','events_hash','state_hash')})
    return saved


class PastRemainingManaRewardTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)

    def game(self,hand=(IVUS,),*,board=(),enemy=(),mode='normal',mana=10,maximum=10,temporary=0,locked=0,owed=0,seed=495):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=tuple(hand),board=tuple(board),deck=(A,)*10,
            mana=mana,max_mana=maximum,mana_cap=40,temporary_mana=temporary,overload_locked=locked,overload_owed=owed),
            PlayerSetup(HERO,board=tuple(enemy),deck=(A,)*10,mana=10,max_mana=10,mana_cap=40)),seed=seed),fixture(mode))

    def board(self,g):return self.entity(g,IVUS,zone='board')
    def rolls(self,g):return[e for e in g.events if e.kind=='random_choice'and'mana_id'in dict(e.data)]
    def finish_choices(self,g):
        while g.state.pending_choice is not None:self.choose(g)

    def test_full_original_row_two_primary_faces_and_keywords_are_not_printed(self):
        d=load_batch();raw=d['dependencies'][0]['record'];self.assertEqual(raw['id'],IVUS)
        self.assertEqual(len(d['official_observations']),2)
        for o in d['official_observations']:
            self.assertEqual(batch.sha(o['response_file']),o['response_sha256']);batch.check_face(raw,o['face'],o['locale'])
        self.assertEqual(fixture().card(IVUS).keywords,());self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])

    def test_actual_constructed_boundary_adds_exact_one_full_definition(self):
        from hs_sim.cards import build_registry
        r=batch.registration_prefix(build_registry,
            'hs_sim.cards.past_remaining_mana_rewards_cards.register_past_remaining_mana_rewards_cards',
            register_past_remaining_mana_rewards_cards,after=True)
        self.assertEqual(len(r.cards),2696);self.assertEqual(r.card(IVUS),fixture().card(IVUS))

    def test_paid_one_and_original_all_mana_debit_are_distinct_records(self):
        g=self.game();source=self.play(g,IVUS);row=g.state.mana_consumption_history[0]
        self.assertEqual((g.state.play_history[0].submitted_cost.quote.amount,row.requested,row.actual),(1,None,9))
        self.assertEqual((row.source_id,row.source_card_id,row.source_kind,row.cast_id),(source,IVUS,CardType.MINION,None))
        self.assertEqual(g.state.players[1].mana,0);self.assertEqual(len(self.rolls(g)),9);self.assertFalse(g.state.cast_history);self.portable(g)

    def test_one_mana_start_pays_card_and_zero_debit_has_no_rng_or_rewards(self):
        g=self.game(mana=1);before=g.snapshot()['rng_state'];self.play(g,IVUS)
        self.assertEqual(g.state.mana_consumption_history[0].actual,0);self.assertFalse(self.rolls(g))
        self.assertEqual((self.board(g).attack,self.board(g).max_health),(1,1));self.assertFalse(self.board(g).keywords)
        self.assertEqual(g.snapshot()['rng_state'],before)

    def test_one_remaining_point_delivers_exactly_one_of_four_real_outcomes(self):
        for seed in(0,1,3,4):
            g=self.game(mana=2,seed=seed);self.play(g,IVUS);choices=self.rolls(g)
            self.assertEqual(len(choices),1);chosen=dict(choices[0].data)['outcome']
            self.assertIn(chosen,('stats',*(k.value for k in MANA_GROWTH_KEYWORDS)))
            self.assertEqual((self.board(g).attack,self.board(g).max_health),(3,3)if chosen=='stats'else(1,1))
            self.assertEqual(len(self.board(g).keywords),0 if chosen=='stats'else 1)

    def test_each_spent_unit_is_a_stat_pair_or_one_nonredundant_named_keyword(self):
        g=self.game();self.play(g,IVUS);choices=self.rolls(g);values=[dict(e.data)['outcome']for e in choices]
        stats=values.count('stats');keywords=[x for x in values if x!='stats']
        self.assertEqual(len(keywords),len(set(keywords)));self.assertEqual(stats+len(keywords),9)
        self.assertEqual((self.board(g).attack,self.board(g).max_health),(1+2*stats,1+2*stats))
        self.assertEqual(self.board(g).keywords,{Keyword(k)for k in keywords});self.portable(g)

    def test_temporary_mana_and_locked_owed_accounts_use_the_original_spender(self):
        g=self.game(mana=9,maximum=7,temporary=3,locked=1,owed=2);self.play(g,IVUS);row=g.state.mana_consumption_history[0]
        player=g.state.players[1]
        self.assertEqual((row.actual,row.temporary_before,row.temporary_after),(8,2,0))
        self.assertEqual((player.mana,player.max_mana,player.overload_locked,player.overload_owed),(0,7,1,2))
        self.assertEqual(player.mana_spent,6);self.assertEqual(len(self.rolls(g)),8);self.portable(g)

    def test_temporary_mana_above_crystal_count_is_not_lost_or_counted_as_crystals(self):
        g=self.game(mana=11,maximum=3,temporary=8);self.play(g,IVUS)
        self.assertEqual(g.state.mana_consumption_history[0].actual,10)
        self.assertEqual((g.state.players[1].max_mana,g.state.players[1].mana_spent,g.state.players[1].temporary_mana),(3,3,0))
        self.assertEqual(len(self.rolls(g)),10)

    def test_reaction_refund_does_not_change_original_reward_count_or_get_spent_again(self):
        g=self.game(board=(WATCH,),mode='refund');self.play(g,IVUS)
        self.assertEqual(g.state.players[1].mana,2);self.assertEqual(g.state.mana_consumption_history[0].actual,9)
        self.assertEqual(len(self.rolls(g)),9);self.assertEqual(len(g.state.mana_consumption_history),1);self.portable(g)

    def test_already_present_keywords_leave_repeatable_stats_and_singleton_rng(self):
        g=self.game(board=(WATCH,),mode='pre_keywords');before=g.snapshot()['rng_state'];self.play(g,IVUS)
        self.assertEqual((self.board(g).attack,self.board(g).max_health),(19,19))
        self.assertEqual(self.board(g).keywords,set(MANA_GROWTH_KEYWORDS))
        self.assertTrue(all(dict(e.data)['outcome']=='stats'for e in self.rolls(g)))
        oracle=random.Random();oracle.setstate(rng_from_json(before))
        for _ in range(9):oracle.choice(('stats',))
        self.assertEqual(rng_from_json(g.snapshot()['rng_state']),oracle.getstate())

    def test_named_rush_candidate_does_not_use_general_bonus_usefulness_filter(self):
        g=self.game(board=(WATCH,),mode='pre_charge',mana=2,seed=1);self.play(g,IVUS)
        self.assertIn(Keyword.CHARGE,self.board(g).keywords);self.assertIn(Keyword.RUSH,self.board(g).keywords)
        self.assertEqual(dict(self.rolls(g)[0].data)['outcome'],Keyword.RUSH.value)

    def test_rush_result_uses_normal_new_minion_attack_restriction(self):
        g=self.game(enemy=(A,),mana=2,seed=1);source=self.play(g,IVUS)
        attacks=[a for a in g.legal_actions()if isinstance(a,Attack)and a.attacker_id==source]
        self.assertTrue(attacks);self.assertFalse(any(a.defender_id==g.state.players[2].hero_id for a in attacks))

    def test_repeated_battlecry_has_independent_original_debit_and_zero_second_result(self):
        g=self.game(board=(DOUBLE,));self.play(g,IVUS)
        self.assertEqual([r.actual for r in g.state.mana_consumption_history],[9,0]);self.assertEqual(len(self.rolls(g)),9)
        self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_repeated_battlecry_rechecks_refunded_mana_only_in_its_new_activation(self):
        g=self.game(board=(DOUBLE,WATCH),mode='refund');self.play(g,IVUS)
        self.assertEqual([r.actual for r in g.state.mana_consumption_history],[9,2])
        self.assertEqual(len(self.rolls(g)),11);self.assertEqual(g.state.players[1].mana,0);self.portable(g)

    def test_ordinary_summon_does_not_spend_mana_or_invent_battlecry_rewards(self):
        g=self.game((P+'summon',));self.play(g,P+'summon')
        self.assertEqual(g.state.players[1].mana,10);self.assertFalse(g.state.mana_consumption_history)
        self.assertEqual((self.board(g).attack,self.board(g).max_health),(1,1));self.assertFalse(self.rolls(g))

    def test_zero_price_real_play_still_spends_all_actual_remaining_mana(self):
        g=self.game((P+'discount',IVUS));self.play(g,P+'discount');self.play(g,IVUS)
        self.assertEqual(g.state.play_history[-1].submitted_cost.quote.amount,0)
        self.assertEqual(g.state.mana_consumption_history[0].actual,10);self.assertEqual(len(self.rolls(g)),10)

    def test_original_source_reentering_after_spend_does_not_receive_old_rewards(self):
        g=self.game(board=(WATCH,),mode='reenter');before=g.snapshot()['rng_state'];source=self.play(g,IVUS)
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.assertEqual(g.state.mana_consumption_history[0].actual,9)
        self.assertEqual((self.board(g).attack,self.board(g).max_health),(1,1));self.assertFalse(self.rolls(g))
        self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)

    def test_wait_after_debit_restores_original_amount_before_any_random_pick(self):
        g=self.game(board=(WATCH,),mode='spend_wait');self.play(g,IVUS)
        self.assertEqual(g.state.players[1].mana,0);self.assertFalse(self.rolls(g))
        self.assertIn('GrantManaRandomGrowth',json.dumps(g.snapshot()['resolution_frame']));other=self.portable(g)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.rolls(g)),9);self.portable(g)

    def test_bounce_during_spend_wait_leaves_original_debit_without_rng_or_retargeting(self):
        g=self.game(board=(WATCH,),mode='spend_wait');before=g.snapshot()['rng_state'];source=self.play(g,IVUS)
        self.choose(g,'bounce');self.assertEqual(g.state.entities[source].zone,Zone.HAND)
        self.assertEqual(g.state.players[1].mana,0);self.assertFalse(self.rolls(g));self.assertEqual(g.snapshot()['rng_state'],before)

    def test_roll_wait_restores_and_all_choices_finish_once(self):
        g=self.game(board=(WATCH,),mode='roll_wait');self.play(g,IVUS)
        self.assertEqual(len(self.rolls(g)),1);other=self.portable(g)
        self.finish_choices(g);self.finish_choices(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(len(self.rolls(g)),9);self.portable(g)

    def test_failing_choice_preserves_waiting_rng_debit_and_reward_prefix(self):
        g=self.game(board=(WATCH,),mode='roll_wait');self.play(g,IVUS);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.finish_choices(g);self.assertEqual(len(self.rolls(g)),9)

    def test_late_roll_failure_rolls_back_card_payment_debit_and_rng_together(self):
        g=self.game(board=(WATCH,),mode='roll_fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,IVUS)
        self.assertEqual(g.snapshot(),before);self.assertFalse(g.state.mana_consumption_history)

    def test_real_retry_restores_resource_ledger_and_only_new_effective_random_prefix(self):
        from hs_sim.engine.hero_health_history import effective_events
        g=self.game((P+'retry',));self.play(g,P+'retry');self.choose(g,'retry')
        self.assertEqual([r.actual for r in g.state.mana_consumption_history],[9])
        self.assertEqual(g.state.players[1].mana,0)
        rolls=[e for e in effective_events(g.events)if e.kind=='random_choice'and'mana_id'in dict(e.data)]
        self.assertEqual(len(rolls),9);self.assertGreater(len(self.rolls(g)),9);self.portable(g)

    def test_rehashed_queued_future_debit_index_and_residence_are_rejected(self):
        g=self.game(board=(WATCH,),mode='roll_wait');self.play(g,IVUS);saved=g.snapshot()
        def find(value):
            if isinstance(value,dict):
                if str(value.get('type','')).endswith('.GrantManaRandomGrowth'):return value
                for v in value.values():
                    hit=find(v)
                    if hit:return hit
            elif isinstance(value,list):
                for v in value:
                    hit=find(v)
                    if hit:return hit
        for field in('debit','index','presence'):
            bad=deepcopy(saved);node=find(bad['resolution_frame']);self.assertIsNotNone(node)
            f=node['fields']
            if field=='debit':f['mana_id']=999
            elif field=='index':f['index']=1000
            else:f['target']['fields']['presence_id']=g.state.next_order+1
            with self.subTest(field=field),self.assertRaises(SnapshotError):
                Game.from_snapshot(rehash(bad),fixture('roll_wait','forgery'))
        self.portable(g)

    def test_rewards_do_not_publish_resource_history_or_private_resolution_frame(self):
        g=self.game();self.play(g,IVUS)
        for player in(1,2):
            view=json.dumps(g.for_player(player).observe());events=json.dumps(g.player_events(player))
            for key in('mana_consumption_history','resolution_frame','GrantManaRandomGrowth'):
                self.assertNotIn(key,view);self.assertNotIn(key,events)
