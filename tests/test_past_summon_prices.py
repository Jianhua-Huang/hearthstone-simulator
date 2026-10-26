"""True past spell entry points and their source-bound historical prices."""
from dataclasses import replace
from functools import lru_cache
from random import Random
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture as base_fixture, P, FILLER
from hs_sim.cards.past_summon_prices import ROOTS, GHOUL, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardType, EndTurn, Game,
    PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec,
    TreantSummonCountCostSpec)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.assemble_offers import Assemble, candidates
from hs_sim.engine.costs import capture_generated_quote_fact, quote_unselected_cost
from hs_sim.engine.effects import ChoiceOption, InvokeBehavior, RequestChoice, Summon
from hs_sim.engine.intrinsic_costs import validate_generated_quote_fact
from hs_sim.engine.player_summon_count_costs import validate_definition, validate_fact
from hs_sim.engine.pools import (GenerationContext, PoolDefinition, PoolMember,
    resolve_candidates, sample_candidates)
from hs_sim.engine.student_teaching import QUERY
from hs_sim.local_pool_format import build_cn37_local_pool_format
from tools import card_batch as batch

WATCH = 'k551.watch'
CTX = GenerationContext('k551-five-known-past-spells-test', 'experimental')
SAFE_SPELL = 'CORE_EX1_169'


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    fmt = base_fixture.__wrapped__('normal', role); r = fmt.registry
    for name in ('constructed.cards', 'constructed.minions', 'constructed.assemble'):
        old = r.pool(name, fmt.context)
        if name=='constructed.cards' and mode=='bounded_casts':
            old = replace(old,members=tuple(PoolMember(cid) for cid in (SAFE_SPELL,'CORE_CS2_029',FILLER)))
        r.register_pool(replace(old,target_id=CTX.target_id,mode=CTX.mode))
    r.register_pool(PoolDefinition('constructed.past.spells','five-native-test-spells-v1',
        CTX.target_id,CTX.mode,tuple(PoolMember(cid) for cid in ROOTS),complete=True))
    r.register_pool(PoolDefinition('constructed.past.cards','two-native-test-minions-v1',
        CTX.target_id,CTX.mode,tuple(PoolMember(cid) for cid in ('OG_141','CORE_YOP_034')),complete=True))

    def fail(c): raise ResolutionError('k551 late failure')

    def observe(c):
        source = c.state.entities.get(c.event.source_id)
        if mode=='price_wait' and c.event.kind=='card_committed' and source is not None and source.card_id=='TTN_954':
            options=(ChoiceOption('more','Summon a real Treant',(Summon(c.player_id,'DAL_256t2'),)),
                ChoiceOption('fault','Fail',(InvokeBehavior('k551.fail',c.source_id,c.player_id),)))
        elif mode=='draw_wait' and c.event.kind=='card_drawn' and c.event.player_id==c.player_id:
            options=(ChoiceOption('continue','Continue',()),
                ChoiceOption('fault','Fail',(InvokeBehavior('k551.fail',c.source_id,c.player_id),)))
        else:return ()
        return (RequestChoice(c.player_id,options,c.source_id),)

    r.register_behavior('k551.fail',fail);r.register_behavior('k551.observe',observe)
    r.register_card(CardDefinition(WATCH,'Observer',CardType.MINION,attack=1,health=8,
        triggers=tuple(TriggerSpec(event,'k551.observe') for event in ('card_committed','card_drawn'))))
    r.validate();return replace(fmt,context=CTX)


class PastSummonPriceTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role).registry)

    def game(self,hand,*,board=(),enemy=(),deck=(FILLER,)*10,mode='normal',seed=1):
        self.mode=mode;fmt=fixture(mode)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06',hand=hand,board=board,deck=deck,max_mana=10,mana=10),
            PlayerSetup('HERO_08',board=enemy,deck=(FILLER,)*10)),seed=seed,generation_context=CTX),fmt.registry)

    def pick(self,game,key):
        choice=game.state.pending_choice
        game.apply(SelectChoice(choice.player_id,choice.id,(key,)))

    def price(self,game,cid):
        return quote_unselected_cost(game.state,game.registry,self.entity(game,cid)).amount

    def test_full_rows_original_copy_associations_and_unfiltered_twenty_nine_identity_family(self):
        data=load_batch();rows={x['record']['id']:x['record'] for key in ('cards','dependencies','evidence_only') for x in data[key]}
        source={x['id']:x for x in batch.read(data['source'])}
        self.assertEqual(len(rows),38);self.assertEqual(batch.sha(data['source']),data['source_sha256'])
        for cid,raw in rows.items():self.assertEqual(raw,source[cid])
        for observation in data['official_faces']:
            batch.check_face(rows[observation['card_id']],observation['face'],observation['locale'])
        expected=sorted(cid for cid,raw in source.items() if raw['tags'].get('2831')==1)
        self.assertEqual(data['treant_member_ids'],expected)
        self.assertEqual(set(data['missing_core_primary_ids']),{'CORE_ICC_085','CORE_REV_365'})
        self.assertEqual(fixture().registry.card('CORE_ICC_085').metadata.deck_identity,'ICC_085')
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_cultivation_counts_actual_successes_after_death_without_counting_failed_entries(self):
        game=self.game(('DAL_256','TTN_954',P+'kill'))
        self.assertEqual(self.price(game,'TTN_954'),8)
        self.play(game,'DAL_256')
        self.assertEqual(self.price(game,'TTN_954'),3)
        tree=next(i for i in game.state.players[1].board if game.state.entities[i].card_id=='DAL_256t2')
        self.play(game,P+'kill',tree)
        self.assertEqual(self.price(game,'TTN_954'),3)
        game.apply(EndTurn(1));game.apply(EndTurn(2))
        self.play(game,'TTN_954')
        self.assertEqual(game.state.players[1].mana,7)
        self.assertTrue(all((game.state.entities[i].attack,game.state.entities[i].health)==(4,4) for i in game.state.players[1].board))
        self.portable(game)

    def test_real_assemble_tree_header_counts_but_suffix_does_not_define_the_family(self):
        for primary,donor,quantity in (('EDR_861','CORE_EX1_007',1),('BE_255','EDR_861',0)):
            with self.subTest(primary=primary,donor=donor):
                probe=self.game(('BE_114','TTN_954'))
                spec=Assemble(1,'constructed.assemble',self.entity(probe,'BE_114').id)
                first=candidates(probe.registry,CTX,probe.state,spec);second=candidates(probe.registry,CTX,probe.state,spec,primary)
                seed=next(n for n in range(30000) if (lambda rng:sample_candidates(rng,first,1,replacement=False)==(primary,)
                    and donor in sample_candidates(rng,second,2,replacement=False))(Random(n)))
                game=self.game(('BE_114','TTN_954'),seed=seed)
                self.play(game,'BE_114');cid=AssembleRecipe(primary,donor,'bottom').card_id
                option=next(o for o in game.state.pending_choice.options if o.card_id==cid)
                self.pick(game,option.id);self.play(game,cid)
                self.assertEqual(self.price(game,'TTN_954'),8-quantity)
                fact=capture_generated_quote_fact(game.state,game.registry,1,'TTN_954')
                self.assertEqual(fact.intrinsic.player_summons.quantity,quantity)
                validate_generated_quote_fact(game.registry,fact)

    def test_frozen_treant_payment_restores_while_new_success_only_reprices_the_future(self):
        game=self.game(('TTN_954',),board=(WATCH,),mode='price_wait')
        self.play(game,'TTN_954');self.assertEqual(game.state.players[1].mana,2)
        saved=game.snapshot()
        with self.assertRaises(ResolutionError):self.pick(game,'fault')
        self.assertEqual(game.snapshot(),saved)
        restored=self.portable(game)
        for current in (game,restored):
            self.pick(current,'more')
            record=current.state.play_history[-1]
            self.assertEqual(record.submitted_cost.quote.intrinsic.player_summons.quantity,0)
            self.assertEqual(current.state.players[1].mana,2)
            self.assertEqual(capture_generated_quote_fact(current.state,current.registry,1,'TTN_954').amount,7)
        self.assertEqual(game.snapshot(),restored.snapshot())
        self.portable(game)

    def test_group_fact_rejects_changed_selection_group_and_unknown_price_formula(self):
        game=self.game(('TTN_954','DAL_256'));self.play(game,'DAL_256')
        full=capture_generated_quote_fact(game.state,game.registry,1,'TTN_954');fact=full.intrinsic.player_summons
        with self.assertRaises(ValueError):replace(fact,selected_ids=(),quantity=0,after=8)
        changed=replace(fact,spec=TreantSummonCountCostSpec(('DAL_256t2',)))
        with self.assertRaises(ValueError):validate_fact(game.registry,game.registry.card('TTN_954'),changed)
        with self.assertRaises(ValueError):TreantSummonCountCostSpec(('x','x'))
        with self.assertRaises(ValueError):validate_definition(replace(game.registry.card('TTN_954'),kind=CardType.MINION))

    def test_sunwell_uses_other_hand_count_then_fills_with_permanent_spells(self):
        for others in (0,9):
            with self.subTest(others=others):
                game=self.game(('RLK_590',*(FILLER,)*others))
                self.assertEqual(self.price(game,'RLK_590'),9-others)
                old=set(game.state.players[1].hand);self.play(game,'RLK_590')
                self.assertEqual(game.state.players[1].mana,1+others)
                hand=game.state.players[1].hand;created=set(hand)-old
                self.assertEqual(len(hand),10);self.assertEqual(len(created),10-others)
                self.assertTrue(all(game.registry.card(game.state.entities[i].card_id).kind==CardType.SPELL for i in created))
                self.assertFalse(game.state.draw_history)
                game.apply(EndTurn(1));game.apply(EndTurn(2))
                self.assertTrue(created <= set(game.state.players[1].hand))

    def test_infestation_packets_spell_damage_draw_armor_and_exact_ghoul_keep_one_cast(self):
        game=self.game(('CORE_ICC_085',),board=('CORE_EX1_012',))
        target=game.state.players[2].hero_id;self.play(game,'CORE_ICC_085',target)
        self.assertEqual(game.state.entities[target].health,24)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor,5)
        self.assertEqual(len(game.state.players[1].hand),5)
        ghoul=self.entity(game,GHOUL,zone='board');self.assertEqual((ghoul.attack,ghoul.health),(5,5))
        roots=[x for x in game.state.card_summon_history if x.request.cause.source.card_id=='CORE_ICC_085']
        self.assertEqual(len(roots),1);self.assertEqual(roots[0].request.cause.cast_card_id,'CORE_ICC_085')
        self.assertEqual(len(game.state.cast_history),1)

    def test_infestation_draw_wait_restores_before_armor_and_deferred_native_summon(self):
        game=self.game(('CORE_ICC_085',),board=(WATCH,),mode='draw_wait')
        self.play(game,'CORE_ICC_085',game.state.players[2].hero_id)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor,0)
        restored=self.portable(game)
        for current in (game,restored):
            count=0
            while current.state.pending_choice:self.pick(current,'continue');count+=1
            self.assertEqual(count,5)
            self.assertEqual(current.state.entities[current.state.players[1].hero_id].armor,5)
            self.entity(current,GHOUL,zone='board')
        self.assertEqual(game.snapshot(),restored.snapshot())

    def test_convoke_really_casts_eight_druid_spells_and_excludes_foreign_spells_and_minions(self):
        game=self.game(('CORE_REV_365',),mode='bounded_casts')
        self.play(game,'CORE_REV_365')
        self.assertEqual(len(game.state.cast_history),9)
        self.assertEqual([x.card_id for x in game.state.cast_history[1:]],[SAFE_SPELL]*8)
        self.assertEqual(game.state.players[1].temporary_mana,8)
        self.assertEqual(game.state.players[1].mana,8)
        self.portable(game)

    def test_frontier_discovers_original_ten_cost_and_real_one_cost_delivery_is_playable(self):
        game=self.game(('GDB_857',));self.play(game,'GDB_857')
        self.assertEqual(game.state.players[1].mana,3)
        self.portable(game)
        option=next(o for o in game.state.pending_choice.options if o.card_id=='OG_141')
        self.pick(game,option.id);self.assertEqual(self.price(game,'OG_141'),1)
        self.play(game,'OG_141')
        self.assertEqual(game.state.players[1].mana,2)
        self.assertEqual((self.entity(game,'OG_141',zone='board').attack,self.entity(game,'OG_141',zone='board').health),(10,10))

    def test_production_missing_past_domain_is_explicit_and_old_schema_is_rejected(self):
        fmt=build_cn37_local_pool_format()
        game=Game.from_scenario(Scenario((PlayerSetup('HERO_06',hand=('GDB_857',),mana=10,max_mana=10),
            PlayerSetup('HERO_08')),generation_context=fmt.context),fmt.registry)
        saved=game.snapshot()
        with self.assertRaises(ResolutionError):self.play(game,'GDB_857')
        self.assertEqual(game.snapshot(),saved)
        old=json.loads(json.dumps(saved));old['schema_version']=587
        with self.assertRaises(SnapshotError):Game.from_snapshot(old,fmt.registry)

    def test_real_teacher_and_student_run_all_five_native_spells(self):
        r=fixture().registry;rows=resolve_candidates(r,CTX,'constructed.past.spells',QUERY,
            current_class=CardClass.DRUID,source_card_id='TIME_704',player_id=1)
        for cid in ROOTS:
            with self.subTest(card=cid):
                seed=next(n for n in range(100) if cid in sample_candidates(Random(n),rows,3,replacement=False))
                game=self.game(('TIME_704',),mode='bounded_casts' if cid=='CORE_REV_365' else 'normal',seed=seed)
                self.play(game,'TIME_704');option=next(o for o in game.state.pending_choice.options if o.card_id==cid)
                self.pick(game,option.id)
                self.play(game,'TIME_704t',game.state.players[2].hero_id if cid=='CORE_ICC_085' else None)
                self.assertIsNone(game.state.pending_choice)
                if cid=='GDB_857':
                    self.assertEqual(len(game.state.players[1].hand),1)
                    created=game.state.entities[game.state.players[1].hand[0]]
                    self.assertIn(created.card_id,('OG_141','CORE_YOP_034'))
                    self.assertEqual(quote_unselected_cost(game.state,game.registry,created).amount,1)
                self.assertTrue(any(x.card_id==cid and x.origin=='effect' for x in game.state.cast_history))
                if cid=='CORE_ICC_085':self.entity(game,GHOUL,zone='board')
        self.portable(game)


if __name__=='__main__':unittest.main()
