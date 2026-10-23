from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_one_cost_mana_overload_cards import ANCIENT, ARTIFICER, LEAVES, TROGG, VALISHJ, load_batch
from hs_sim.engine import (
    CardDefinition, CardType, EndTurn, Game, PlayerSetup, Scenario, TriggerSpec,
    UseHeroPower, Zone,
)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (
    AddCostModifier, ChangeControl, ChoiceOption, Destroy, GainTemporaryMana,
    InvokeBehavior, ModifyCost, Overload, RequestChoice, ReturnToHand, Silence,
    SpendMana, Transform, UnlockOverload,
)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import CostSpec, PaymentType, TargetMode, TargetSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from tools import card_batch as batch


P='test.k466.'
NOOP,OWE_TWO,CLEAR,AUTO,SILENCE,KILL,FREE,HEALTH,SELF_DESTRUCT,RESUMMON,FAIL,WATCH=(
    P+s for s in ('noop','owe_two','clear','auto','silence','kill','free','health','self_destruct','resummon','fail','watch'))
FIRE,YETI,COUNTER,BRANN,FLASHBACK='CORE_CS2_029','CORE_CS2_182','CORE_EX1_287','LOE_077','TIME_711'
TAKE=P+'take'
CONTEXT=GenerationContext('k466-explicit-mana-overload','experimental')


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=build_registry()
    r.register_pool(PoolDefinition('constructed.past.cards','four-mana-leaves-v1',CONTEXT.target_id,
        CONTEXT.mode,tuple(PoolMember(cid) for cid in LEAVES),complete=True))
    def fail(c):raise ResolutionError('K466 deliberate native failure')
    def resume_minion(c):
        return (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,
            cause=SummonCause.capture(c)),)
    def destroy_artificer(c):
        return tuple(Destroy(i,c.source_id) for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id==ARTIFICER)
    scripts={
        NOOP:lambda c:(), OWE_TWO:lambda c:(Overload(c.player_id,2),),
        CLEAR:lambda c:(UnlockOverload(c.player_id),), AUTO:lambda c:(CastSpell(c.player_id,FIRE,c.source_id,
            targeting='explicit',target_id=c.state.players[3-c.player_id].hero_id),),
        SILENCE:lambda c:(Silence(c.target_id),), KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        TAKE:lambda c:(ChangeControl(c.target_id,2),),
        FREE:lambda c:(AddCostModifier(c.player_id,CostSpec(set_to=0,card_ids=(FIRE,ANCIENT,)),uses_remaining=1,source_id=c.source_id),),
        HEALTH:lambda c:(AddCostModifier(c.player_id,CostSpec(payment=PaymentType.HEALTH,card_ids=(FIRE,ANCIENT,)),uses_remaining=1,source_id=c.source_id),),
        SELF_DESTRUCT:destroy_artificer, RESUMMON:resume_minion, FAIL:fail,
    }
    for cid,body in scripts.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=3 if cid==SELF_DESTRUCT else 0,on_play=cid,
            targeting=TargetSpec(TargetMode.REQUIRED,(Zone.BOARD,),(CardType.MINION,)) if cid in (SILENCE,KILL,TAKE) else None))
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id);cid=None if source is None else source.card_id
        mana=e.kind=='mana_consumption_resolved' and cid==ANCIENT
        armor=e.kind=='armor_gained' and e.player_id==c.player_id and e.target_id==c.state.players[c.player_id].hero_id
        growth=e.kind=='stats_changed' and cid in (ANCIENT,TROGG)
        if mode=='reprice' and e.kind=='card_committed' and cid==FIRE:
            return (ModifyCost(e.source_id,CostSpec(delta=3),c.source_id),)
        if mode=='fail' and (growth or armor):return (InvokeBehavior(FAIL,c.source_id,c.player_id),)
        if mode!='boundary' or not (mana or armor or growth and cid==TROGG):return ()
        choices=(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(FAIL,c.source_id,c.player_id),)))
        if mana:
            target=e.source_id
            choices+=(ChoiceOption('mana','Gain Mana',(GainTemporaryMana(1,2),)),
                ChoiceOption('nested','Nested debit',(GainTemporaryMana(1,2),SpendMana(1,1,c.source_id))),
                ChoiceOption('transform','Transform',(Transform(target,YETI),)),
                ChoiceOption('control','Transfer',(ChangeControl(target,2),)),
                ChoiceOption('kill','Kill',(Destroy(target,c.source_id),)),
                ChoiceOption('reenter','Return and summon',(ReturnToHand(target),
                    InvokeBehavior(RESUMMON,c.source_id,1,target))))
        return (RequestChoice(c.player_id,choices,c.source_id),)
    body=WATCH+'.'+mode;r.register_behavior(body,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.WEAPON,attack=0,durability=50,
        triggers=tuple(TriggerSpec(e,body) for e in ('mana_consumption_resolved','armor_gained','stats_changed','card_committed'))
            if mode!='normal' else ()))
    r.validate();return r


class PastOneCostManaOverloadTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)

    def game(self,hand=(),board=(),*,mana=None,temporary=0,locked=0,owed=0,enemy_hand=(),enemy_board=(),active=1,mode='normal'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=(NOOP,)*8,mana=10-locked+temporary if mana is None else mana,
                max_mana=10,temporary_mana=temporary,overload_locked=locked,overload_owed=owed,
                hero_power_card_id='HERO_08bp',weapon_card_id=WATCH if mode!='normal' else None),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy_board,deck=(NOOP,)*8,mana=10,max_mana=10,
                hero_power_card_id='HERO_08bp')),active_player=active,seed=466,generation_context=CONTEXT),fixture(mode))

    def hero(self,g,player=1):return g.state.entities[g.state.players[player].hero_id]

    def test_four_complete_source_rows_and_eight_full_primary_faces(self):
        d=load_batch();rows={x['record']['id']:x['record'] for x in d['dependencies']};hashes={}
        self.assertEqual((set(rows),len(d['official_observations'])),(set(LEAVES),8))
        for o in d['official_observations']:
            if o['response_file'] not in hashes:hashes[o['response_file']]=batch.sha(Path(o['response_file']))
            self.assertEqual(hashes[o['response_file']],o['response_sha256'])
            batch.check_face(rows[o['card_id']],o['face'],o['locale'],d['display_normalizations'].get(o['card_id']))
        self.assertEqual(batch.sha(Path(d['source']['path'])),d['source']['sha256']);self.assertFalse(d['cn_calibrated'])

    def test_valishj_counter_display_keeps_complete_body_and_rejects_changed_chinese_source(self):
        d=load_batch();raw=next(x['record'] for x in d['dependencies'] if x['record']['id']==VALISHJ)
        for o in [x for x in d['official_observations'] if x['card_id']==VALISHJ]:
            bad=deepcopy(o['face']);bad['text']='<i>( )</i>'
            with self.assertRaises(ValueError):batch.check_face(raw,bad,o['locale'],{'@':''})
            if o['locale']=='zh_CN':
                changed=deepcopy(raw);changed['text']+=' 抽两张牌。'
                with self.assertRaises(ValueError):batch.check_face(changed,o['face'],o['locale'],{'@':''})

    def test_four_real_hand_entries_pay_once_and_keep_original_native_stats(self):
        for cid in LEAVES:
            g=self.game((cid,));source=self.play(g,cid);e=g.state.entities[source];c=g.registry.card(cid)
            expected=10 if cid==ANCIENT else c.attack
            self.assertEqual((e.attack,e.health),(expected,10 if cid==ANCIENT else c.health))
            self.assertEqual(g.state.players[1].mana,0 if cid==ANCIENT else 9)

    def test_ancient_zero_remaining_mana_is_one_native_one_one_and_zero_actual_debit(self):
        g=self.game((ANCIENT,),mana=1);source=self.play(g,ANCIENT);e=g.state.entities[source]
        self.assertEqual((e.attack,e.health,g.state.players[1].mana),(1,1,0))
        self.assertEqual([r.actual for r in g.state.mana_consumption_history],[0])

    def test_ancient_consumes_real_temporary_and_unlocked_accounts(self):
        for temporary,locked,owed,amount in ((4,0,0,13),(0,3,4,6),(4,3,0,10)):
            g=self.game((ANCIENT,),temporary=temporary,locked=locked,owed=owed);source=self.play(g,ANCIENT)
            row,=g.state.mana_consumption_history;self.assertEqual(row.actual,amount)
            self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(amount+1,amount+1))
            self.assertEqual((g.state.players[1].mana,g.state.players[1].temporary_mana),(0,0))
            self.assertEqual(g.state.players[1].overload_owed,owed)

    def test_free_ancient_spends_ten_and_health_paid_ancient_does_not_subtract_mana_twice(self):
        for discount,health in ((FREE,30),(HEALTH,29)):
            g=self.game((discount,ANCIENT));self.play(g,discount);source=self.play(g,ANCIENT)
            self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(11,11))
            self.assertEqual(g.state.mana_consumption_history[0].actual,10);self.assertEqual(self.hero(g).health,health)

    def test_actual_battlecry_repeat_rechecks_zero_remaining_mana_and_pays_root_once(self):
        g=self.game((ANCIENT,),board=(BRANN,));source=self.play(g,ANCIENT)
        self.assertEqual([r.actual for r in g.state.mana_consumption_history],[9,0])
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(10,10))
        self.assertEqual(len(g.state.battlecry_history),2);self.assertEqual(len(g.state.play_history),1)

    def test_ancient_pending_debit_restores_original_ref_and_applies_growth_once(self):
        g=self.game((ANCIENT,),mode='boundary');source=self.play(g,ANCIENT)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual((g.state.entities[source].attack,g.state.players[1].mana),(1,0))
        g=self.portable(g);self.choose(g)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(10,10))
        self.assertEqual(len(g.state.mana_consumption_history),1)

    def test_original_debit_amount_survives_later_gain_and_nested_debit(self):
        for option,remaining,amounts in (('mana',2,[9]),('nested',1,[9,1])):
            g=self.game((ANCIENT,),mode='boundary');source=self.play(g,ANCIENT);self.choose(g,option)
            self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(10,10))
            self.assertEqual(g.state.players[1].mana,remaining);self.assertEqual([r.actual for r in g.state.mana_consumption_history],amounts)

    def test_original_growth_does_not_buff_transformed_transferred_or_reentered_same_id(self):
        for option in ('transform','control','reenter','kill'):
            with self.subTest(boundary=option):
                g=self.game((ANCIENT,),mode='boundary');source=self.play(g,ANCIENT);before_epoch=g.state.entities[source].zone_epoch
                self.choose(g,option);e=g.state.entities[source]
                self.assertEqual(g.state.players[1].mana,0)
                if option=='transform':self.assertEqual((e.card_id,e.attack,e.health),(YETI,4,5))
                elif option=='control':self.assertEqual((e.controller,e.attack,e.health),(2,1,1))
                elif option=='reenter':self.assertEqual((e.card_id,e.attack,e.health),(ANCIENT,1,1));self.assertGreater(e.zone_epoch,before_epoch)
                else:self.assertEqual(e.zone,Zone.GRAVEYARD)

    def test_growth_profile_rejects_partial_spend_other_source_and_mixed_callback(self):
        g=self.game(board=(ANCIENT,));source=self.entity(g,ANCIENT,zone='board');ref=MinionReference.capture(source)
        for kwargs in ({'amount':1},{'source_id':g.state.players[1].hero_id},{'on_result':NOOP},{'source_growth':False}):
            values=dict(player_id=1,source_id=source.id,source_growth=ref);values.update(kwargs)
            with self.assertRaises(ValueError):SpendMana(**values)
        request=SpendMana(1,None,source.id,source_growth=ref);codec=FrameCodec(g.mechanics,g.registry)
        self.assertEqual(codec.decode(codec.encode(request)),request)

    def test_old_schema_rejects_instead_of_silently_dropping_new_growth_shape(self):
        g=self.game((ANCIENT,),mode='boundary');self.play(g,ANCIENT);saved=g.snapshot();self.assertEqual(saved['schema_version'],549)
        saved['schema_version']=548
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,fixture('boundary','old-schema-reader'))

    def test_unmodified_historical_default_snapshot_is_rejected_with_its_matching_registry(self):
        from hs_sim.engine.representative import build_registry as defaults
        old=batch.read(Path('outputs/card-integration-20261014/k466-past-one-cost-mana-overload/before-01.json'))
        saved=old['default_snapshot'];r=defaults()
        self.assertEqual(saved['registry_fingerprint'],r.fingerprint());self.assertEqual(saved['schema_version'],548)
        with self.assertRaisesRegex(SnapshotError,'schema'):Game.from_snapshot(saved,r)

    def test_valishj_counts_manual_spell_plays_rather_than_cost_and_caps_empty_crystals(self):
        g=self.game((NOOP,NOOP,NOOP,VALISHJ),mana=6)
        for _ in range(3):self.play(g,NOOP)
        self.play(g,VALISHJ);self.assertEqual(g.state.players[1].mana,8)
        g=self.game((NOOP,NOOP,VALISHJ));self.play(g,NOOP);self.play(g,NOOP);self.play(g,VALISHJ)
        self.assertEqual(g.state.players[1].mana,10)

    def test_valishj_no_prior_spell_and_new_turn_does_not_reuse_old_spell_count(self):
        g=self.game((VALISHJ,));self.play(g,VALISHJ);self.assertEqual(g.state.players[1].mana,9)
        g=self.game((NOOP,VALISHJ));self.play(g,NOOP);g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,VALISHJ)
        self.assertEqual(g.state.players[1].mana,9)

    def test_valishj_automatic_spell_and_hero_power_are_not_new_manual_spells(self):
        g=self.game((AUTO,VALISHJ),mana=6);self.play(g,AUTO);self.play(g,VALISHJ)
        self.assertEqual(g.state.players[1].mana,6)
        g=self.game((VALISHJ,),mana=6)
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_ids[0],g.state.players[2].hero_id));self.play(g,VALISHJ)
        self.assertEqual(g.state.players[1].mana,3)

    def test_valishj_original_countered_manual_play_remains_in_current_turn_count(self):
        g=self.game((NOOP,VALISHJ),enemy_hand=(COUNTER,),active=2)
        self.play(g,COUNTER,player=2);g.apply(EndTurn(2));self.play(g,NOOP)
        self.assertTrue(g.state.play_history[-1].countered);self.play(g,VALISHJ)
        self.assertEqual(g.state.players[1].mana,10)

    def test_trogg_uses_each_actual_positive_increment_and_not_existing_debt_or_unlock(self):
        g=self.game((TROGG,OWE_TWO,OWE_TWO,CLEAR),owed=3,locked=2);source=self.play(g,TROGG)
        self.assertEqual(g.state.entities[source].attack,1);self.play(g,OWE_TWO);self.play(g,OWE_TWO)
        self.assertEqual(g.state.entities[source].attack,5);self.play(g,CLEAR);self.assertEqual(g.state.entities[source].attack,5)
        self.assertEqual([r.amount for r in g.state.overload_history],[2,2])

    def test_trogg_opponent_overload_and_later_locked_turn_do_not_add_growth(self):
        g=self.game((OWE_TWO,),board=(TROGG,),enemy_hand=(OWE_TWO,));source=self.entity(g,TROGG,zone='board').id
        self.play(g,OWE_TWO);g.apply(EndTurn(1));self.play(g,OWE_TWO,player=2);g.apply(EndTurn(2))
        self.assertEqual(g.state.entities[source].attack,3);self.assertEqual(g.state.players[1].overload_locked,2)

    def test_trogg_silence_and_current_controller_use_original_event_owner(self):
        g=self.game((SILENCE,OWE_TWO),board=(TROGG,));source=self.entity(g,TROGG,zone='board').id
        self.play(g,SILENCE,source);self.play(g,OWE_TWO);self.assertEqual(g.state.entities[source].attack,1)
        g=self.game((TAKE,OWE_TWO),board=(TROGG,),enemy_hand=(OWE_TWO,));source=self.entity(g,TROGG,zone='board').id
        self.play(g,TAKE,source);self.play(g,OWE_TWO);self.assertEqual(g.state.entities[source].attack,1)
        g.apply(EndTurn(1));self.play(g,OWE_TWO,player=2)
        self.assertEqual((g.state.entities[source].controller,g.state.entities[source].attack),(2,3))

    def test_trogg_growth_wait_restores_original_overload_receipt(self):
        g=self.game((OWE_TWO,),board=(TROGG,),mode='boundary');self.play(g,OWE_TWO)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g)
        self.assertEqual(self.entity(g,TROGG,zone='board').attack,3);self.assertEqual(g.state.players[1].overload_owed,2)

    def test_artificer_gets_original_four_cost_before_spell_payload(self):
        g=self.game((FIRE,),board=(ARTIFICER,),mode='boundary');self.play(g,FIRE,g.state.players[2].hero_id)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual((self.hero(g).armor,self.hero(g,2).health),(4,30))
        g=self.portable(g);self.choose(g);self.assertEqual((self.hero(g).armor,self.hero(g,2).health),(4,24))

    def test_artificer_reads_submitted_price_even_after_committed_source_is_repriced(self):
        g=self.game((FIRE,),board=(ARTIFICER,),mode='reprice');source=self.play(g,FIRE,g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[source].cost,7);self.assertEqual(self.hero(g).armor,4)
        play=next(r for r in g.state.play_history if r.source_id==source);self.assertEqual(play.submitted_cost.quote.amount,4)

    def test_artificer_zero_cost_does_not_award_printed_armor_and_health_payment_is_not_zero_cost(self):
        for setup,armor,health,mana in ((FREE,0,30,10),(HEALTH,4,26,10)):
            g=self.game((setup,FIRE),board=(ARTIFICER,));self.play(g,setup);self.play(g,FIRE,g.state.players[2].hero_id)
            self.assertEqual((self.hero(g).armor,self.hero(g).health,g.state.players[1].mana),(armor,health,mana))

    def test_artificer_automatic_cast_is_excluded_while_the_manual_outer_card_can_count(self):
        g=self.game((AUTO,),board=(ARTIFICER,));self.play(g,AUTO)
        self.assertEqual(self.hero(g).armor,0);self.assertEqual(self.hero(g,2).health,24)

    def test_artificer_started_manual_countered_spell_retains_original_price(self):
        g=self.game((FIRE,),board=(ARTIFICER,),enemy_hand=(COUNTER,),active=2)
        self.play(g,COUNTER,player=2);g.apply(EndTurn(2));self.play(g,FIRE,g.state.players[2].hero_id)
        self.assertEqual((self.hero(g).armor,self.hero(g,2).health),(4,30))

    def test_artificer_original_start_precedes_spell_removing_its_source(self):
        g=self.game((SELF_DESTRUCT,),board=(ARTIFICER,));self.play(g,SELF_DESTRUCT)
        self.assertFalse(g.state.players[1].board);self.assertEqual(self.hero(g).armor,3)

    def test_artificer_silenced_or_opponent_spell_does_not_award_armor(self):
        g=self.game((SILENCE,FIRE),board=(ARTIFICER,));self.play(g,SILENCE,self.entity(g,ARTIFICER,zone='board').id)
        self.play(g,FIRE,g.state.players[2].hero_id);self.assertEqual(self.hero(g).armor,0)
        g=self.game(board=(ARTIFICER,),enemy_hand=(FIRE,),active=2);self.play(g,FIRE,g.state.players[1].hero_id,player=2)
        self.assertEqual(self.hero(g).armor,0)

    def test_late_failures_restore_mana_debit_overload_and_original_spell_payment(self):
        for cid,board in ((ANCIENT,()),(OWE_TWO,(TROGG,)),(FIRE,(ARTIFICER,))):
            g=self.game((cid,),board=board,mode='fail');before=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,cid,g.state.players[2].hero_id if cid==FIRE else None)
            self.assertEqual(g.snapshot(),before)

    def test_failing_choice_does_not_repeat_already_accepted_debit(self):
        g=self.game((ANCIENT,),mode='boundary');self.play(g,ANCIENT);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.assertEqual([r.actual for r in g.state.mana_consumption_history],[9])

    def test_actual_flashback_contains_four_members_without_summoned_battlecries(self):
        g=self.game((FLASHBACK,));self.play(g,FLASHBACK);row,=g.state.pool_summon_history
        self.assertEqual({x.card_id for x in row.spec.basis.candidates},set(LEAVES))
        self.assertEqual(len(g.state.players[1].board),2);self.assertFalse(g.state.battlecry_history)


if __name__=='__main__':unittest.main()
