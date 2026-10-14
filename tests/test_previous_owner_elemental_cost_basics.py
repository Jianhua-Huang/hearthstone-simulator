"""Finite Scorch history condition through the original intrinsic/paid stage."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import unittest

import test_owner_turn_type_history_basics as fixtures
import test_m5_owner_turn_startup as startup_fixtures
import test_m5_owner_turn_opening as opening_fixtures
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CostSpec,
    DamageKind, Game, IllegalAction, IntrinsicCostSpec, PlayedTypeQuery, PlayerDrawCountCostSpec,
    PlayCard, QueueTurns, Rarity, ResolutionError, SnapshotError, SpellSchool,
    TargetSpec, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.costs import capture_cost_input, capture_quote_fact, capture_generated_quote_fact
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Damage,
    Destroy, GainArmor, InvokeBehavior, ModifyCost, RequestChoice, Summon, Transform)
from hs_sim.engine.intrinsic_costs import (validate_definition_intrinsics,
    validate_generated_quote_fact, validate_intrinsic_stage_fact,
    validate_intrinsic_origin, validate_intrinsic_history_prefix)
from hs_sim.engine.model import PreviousOwnerTurnMatch
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import PlayFromHand
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import _intrinsic_stage_from_dict
from hs_sim.targets import canonical_digest
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE='TRL_313'
ELEMENTAL=fixtures.NATIVE
CONDITION='previous_owner_turn_elemental'
SUPPORT=Path(__file__).resolve().parents[1]/'data/support/previous-owner-elemental-cost-basics.json'
PIN='deba86cbb9b3087114ccec023d363e6c4238fb8a82393daf21e082d4252af740'


def evidence():
    support=json.loads(SUPPORT.read_bytes())
    if canonical_digest(support)!=PIN:raise ValueError('Complete Scorch condition evidence changed')
    for row in support['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Complete raw row changed')
    return {row['id']:row['data'] for row in support['records']}


def native_definition():
    raw=evidence()[NATIVE]
    return CardDefinition(NATIVE,raw['name'],CardType.SPELL,cost=raw['cost'],
        on_play='native.scorch',spell_school=SpellSchool.FIRE,
        targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),
        metadata=CardMetadata(True,(CardClass.MAGE,),Rarity.RARE,tribes=()),
        intrinsic_costs=(IntrinsicCostSpec(set_to=1,condition=CONDITION),))


class PreviousOwnerElementalCostTests(unittest.TestCase):
    game=fixtures.OwnerTurnTypeHistoryTests.game
    play=fixtures.OwnerTurnTypeHistoryTests.play
    end=fixtures.OwnerTurnTypeHistoryTests.end
    choose=fixtures.OwnerTurnTypeHistoryTests.choose
    script=fixtures.OwnerTurnTypeHistoryTests.script
    next_own=fixtures.OwnerTurnTypeHistoryTests.next_own
    fresh_registry=fixtures.OwnerTurnTypeHistoryTests.fresh_registry

    def setUp(self):
        fixtures.OwnerTurnTypeHistoryTests.setUp(self)
        self.r.register_behavior('native.scorch',lambda c:[Damage(c.target_id,4,c.source_id,DamageKind.SPELL)])
        self.r.register_card(native_definition())
        self.r.register_card(CardDefinition('fire','Plain Fire fixture',CardType.SPELL,
            on_play='nothing',spell_school=SpellSchool.FIRE,metadata=fixtures.fixtures.metadata()))

    def source(self,g,player=1):
        return next(g.state.entities[e] for e in g.state.players[player].hand if g.state.entities[e].card_id==NATIVE)

    def fact(self,g,player=1):
        return capture_quote_fact(g.state,g.registry,capture_cost_input(self.source(g,player)))

    def closed(self,extras=(),*,board=(),enemy_board=('empty',)):
        g=self.game((ELEMENTAL,NATIVE,*extras),board=board,enemy_board=enemy_board)
        self.play(g,ELEMENTAL);self.next_own(g);return g

    def scorch(self,g,player=None,target=None):
        player=g.state.active_player if player is None else player
        target=g.state.players[3-player].board[0] if target is None else target
        return self.play(g,NATIVE,player=player,target=target)

    def check(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        for other in (Game.from_snapshot(saved,self.fresh_registry(),mechanics=g.mechanics),
                g.clone(),replay(build_replay(g),self.fresh_registry(),mechanics=g.mechanics)):
            self.assertEqual(other.snapshot(),saved)
        return saved

    def typed(self,g,stage):
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(stage)),stage)
        self.assertEqual(_intrinsic_stage_from_dict(json.loads(json.dumps(asdict(stage)))),stage)

    def test_complete_native_raw_pin_fire_school_rare_mage_and_full_body(self):
        raw=evidence()[NATIVE];card=self.r.card(NATIVE)
        self.assertEqual((raw['dbf_id'],card.cost,raw['tags']['SPELL_SCHOOL'],card.spell_school),(50122,4,2,SpellSchool.FIRE))
        self.assertEqual((card.metadata.classes,card.metadata.rarity,card.intrinsic_costs),
            ((CardClass.MAGE,),Rarity.RARE,(IntrinsicCostSpec(set_to=1,condition=CONDITION),)))
        self.assertEqual((card.targeting.zones,card.targeting.kinds,card.targeting.relation),((Zone.BOARD,),(CardType.MINION,),'any'))
        self.assertIsNone(card.battlecry);self.assertIsNone(card.deathrattle);self.assertEqual(card.keywords,())
        g=self.game((NATIVE,),enemy_board=('empty',));target=g.state.players[2].board[0];self.scorch(g)
        self.assertEqual((g.state.entities[target].health,g.state.play_history[-1].cost,g.state.players[1].mana),(1,4,6));self.check(g)

    def test_initial_board_and_current_only_elemental_do_not_grant_previous_turn_price(self):
        g=self.game((NATIVE,ELEMENTAL),board=(ELEMENTAL,))
        self.assertEqual(self.fact(g).amount,4);self.play(g,ELEMENTAL)
        condition=self.fact(g).intrinsic.condition_facts[0]
        self.assertIsNone(condition.owner_turn);self.assertFalse(condition.matched);self.assertEqual(self.fact(g).amount,4)

    def test_native_elemental_identifier_matches_the_production_raw_metadata_parser(self):
        printed=metadata_from_record(evidence()[ELEMENTAL])
        self.assertEqual((printed.tribes,self.r.card(ELEMENTAL).metadata.tribes),(('elemental',),('elemental',)))
        g=self.closed();self.assertEqual(self.fact(g).intrinsic.condition_facts[0].query.tribes,printed.tribes)
        self.assertEqual(self.fact(g).amount,1)

    def test_previous_own_elemental_prices_fire_spell_at_one(self):
        g=self.closed();f=self.fact(g);condition=f.intrinsic.condition_facts[0]
        self.assertEqual((condition.query,condition.owner_turn.id,condition.matched,f.amount),
            (PlayedTypeQuery(CardType.MINION,('elemental',)),1,True,1))
        self.assertEqual([r.face.card_id for r in condition.rows],[ELEMENTAL]);self.typed(g,f.intrinsic);self.check(g)

    def test_previous_fire_school_spell_does_not_grant_elemental_condition(self):
        g=self.game((NATIVE,'fire'));self.play(g,'fire');self.next_own(g)
        f=self.fact(g);self.assertFalse(f.intrinsic.condition_facts[0].matched)
        self.assertEqual((f.intrinsic.condition_facts[0].rows,f.amount),((),4));self.check(g)

    def test_complete_false_true_false_rows_are_retained(self):
        g=self.game((NATIVE,'empty',ELEMENTAL,'dragon'))
        for card in ('empty',ELEMENTAL,'dragon'):self.play(g,card)
        self.next_own(g);condition=self.fact(g).intrinsic.condition_facts[0]
        self.assertEqual([r.matched for r in condition.rows],[False,True,False])
        self.assertEqual([r.face.play_id for r in condition.rows],[1,2,3]);self.assertEqual(self.fact(g).amount,1);self.check(g)

    def test_multiple_previous_elementals_remain_one_boolean_condition(self):
        g=self.game((NATIVE,ELEMENTAL,ELEMENTAL))
        self.play(g,ELEMENTAL);self.play(g,ELEMENTAL);self.next_own(g)
        self.assertEqual((len(self.fact(g).intrinsic.condition_facts[0].rows),self.fact(g).amount),(2,1));self.check(g)

    def test_empty_previous_own_interval_supersedes_older_elemental(self):
        g=self.closed();self.next_own(g);condition=self.fact(g).intrinsic.condition_facts[0]
        self.assertEqual((condition.owner_turn.id,condition.rows,condition.matched,self.fact(g).amount),(3,(),False,4));self.check(g)

    def test_opponent_submission_does_not_change_payers_previous_own_condition(self):
        g=self.game((NATIVE,),enemy_hand=(ELEMENTAL,));self.end(g);self.play(g,ELEMENTAL);self.end(g)
        self.assertEqual(self.fact(g).amount,4);self.assertEqual(self.fact(g).intrinsic.condition_facts[0].owner_turn.player_id,1);self.check(g)

    def test_actual_extra_own_turn_uses_the_latest_closed_interval(self):
        self.script('extra',lambda c:[QueueTurns((c.player_id,))])
        g=self.game((NATIVE,ELEMENTAL,'extra'));self.play(g,ELEMENTAL);self.play(g,'extra');self.end(g)
        self.assertEqual(g.state.active_player,1);self.assertEqual(self.fact(g).intrinsic.condition_facts[0].owner_turn.id,1)
        self.assertEqual(self.fact(g).amount,1);self.end(g);self.end(g)
        self.assertEqual(self.fact(g).amount,4);self.check(g)

    def test_same_turn_new_elemental_does_not_replace_empty_previous_interval(self):
        g=self.game((NATIVE,ELEMENTAL));self.next_own(g);self.play(g,ELEMENTAL)
        self.assertFalse(self.fact(g).intrinsic.condition_facts[0].matched);self.assertEqual(self.fact(g).amount,4);self.check(g)

    def test_unknown_selected_minion_is_not_hidden_after_a_true_row(self):
        g=self.game((NATIVE,ELEMENTAL,'unknown'));self.play(g,ELEMENTAL);self.play(g,'unknown');self.next_own(g)
        before=g.snapshot()
        with self.assertRaisesRegex(ValueError,'known Minion tribes'):self.fact(g)
        self.assertEqual(g.snapshot(),before)

    def test_older_unknown_outside_latest_selected_interval_does_not_poison_price(self):
        g=self.game((NATIVE,'unknown'));self.play(g,'unknown');self.next_own(g);self.next_own(g)
        self.assertEqual(self.fact(g).amount,4);self.assertEqual(self.fact(g).intrinsic.condition_facts[0].rows,());self.check(g)

    def test_known_empty_and_all_tribes_use_the_original_predicate(self):
        for card,price in (('empty',4),('all',1)):
            g=self.game((NATIVE,card));self.play(g,card);self.next_own(g)
            self.assertEqual(self.fact(g).amount,price);self.check(g)

    def test_frozen_printed_elemental_survives_transform_transfer_and_death(self):
        self.script('shape',lambda c:[Transform(c.state.players[1].board[0],'empty')])
        self.script('transfer',lambda c:[ChangeControl(c.state.players[1].board[0],2)])
        self.script('kill',lambda c:[Destroy(c.state.players[2].board[0],c.source_id)])
        g=self.game((NATIVE,ELEMENTAL,'shape','transfer','kill'));self.play(g,ELEMENTAL)
        original=g.state.play_history[0].played_face
        for card in ('shape','transfer','kill'):self.play(g,card)
        self.next_own(g);self.assertEqual((self.fact(g).amount,g.state.play_history[0].played_face),(1,original));self.check(g)

    def test_summoned_elemental_is_not_a_previous_hand_submission(self):
        self.script('make',lambda c:[Summon(c.player_id,ELEMENTAL)])
        g=self.game((NATIVE,'make'));self.play(g,'make');self.next_own(g)
        self.assertEqual((self.fact(g).amount,len(g.state.successful_summon_history)),(4,1));self.check(g)

    def test_newly_acquired_native_uses_players_existing_history(self):
        self.script('acquire',lambda c:[AddToHand(c.player_id,NATIVE)])
        g=self.game((ELEMENTAL,'acquire'));self.play(g,ELEMENTAL);self.next_own(g);self.play(g,'acquire')
        self.assertEqual(self.fact(g).amount,1);self.check(g)

    def test_generated_quote_uses_same_fixed_query_without_state_mutation(self):
        g=self.closed();before=g.snapshot();f=capture_generated_quote_fact(g.state,g.registry,1,NATIVE)
        self.assertEqual(f.amount,1);validate_generated_quote_fact(g.registry,f);self.typed(g,f.intrinsic)
        self.assertEqual(g.snapshot(),before)

    def test_quoted_physical_base_differs_from_printed_but_match_sets_one(self):
        g=self.closed();value=replace(capture_cost_input(self.source(g)),base_cost=9)
        f=capture_quote_fact(g.state,g.registry,value)
        self.assertEqual((f.intrinsic.printed_cost,f.intrinsic.base_cost,f.amount),(4,9,1))
        validate_intrinsic_stage_fact(g.registry,f.intrinsic);self.typed(g,f.intrinsic)

    def test_original_local_price_layer_applies_after_conditional_intrinsic(self):
        self.script('local',lambda c:[ModifyCost(self.source_from_context(c).id,CostSpec(set_to=2))])
        g=self.closed(('local',));self.play(g,'local');f=self.fact(g)
        self.assertEqual((f.intrinsic.amount,f.local_amount,f.amount),(1,2,2))
        self.scorch(g);self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(2,8));self.check(g)

    def source_from_context(self,c):
        return next(c.state.entities[e] for e in c.state.players[c.player_id].hand if c.state.entities[e].card_id==NATIVE)

    def test_native_only_accepts_real_board_minion_targets(self):
        g=self.closed();before=g.snapshot()
        with self.assertRaises(IllegalAction):self.scorch(g,target=g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(),before);self.scorch(g,target=g.state.players[1].board[0]);self.check(g)

    def watcher(self,event):
        self.r.register_behavior('condition-wait',lambda c:[RequestChoice(c.player_id,
            (ChoiceOption('ok','ok',(GainArmor(c.player_id,1),)),
             ChoiceOption('bad','bad',(InvokeBehavior('failure',c.source_id,c.player_id),))),source_id=c.source_id)]
            if c.play is not None and c.play.card_id==NATIVE else [])
        self.r.register_card(CardDefinition('condition-watcher','condition-watcher',CardType.MINION,health=5,
            metadata=fixtures.fixtures.metadata(),triggers=(TriggerSpec(event,'condition-wait'),)))

    def waiting(self,event,completed):
        self.watcher(event);g=self.closed(board=('condition-watcher',));target=g.state.players[2].board[0];self.scorch(g)
        record=g.state.play_history[-1];stage=record.submitted_cost.quote.intrinsic
        self.assertEqual((record.cost,record.completed,stage.amount,g.state.players[1].mana),(1,completed,1,9))
        saved=self.check(g);self.typed(g,stage)
        clones=(Game.from_snapshot(saved,self.fresh_registry()),g.clone(),replay(build_replay(g),self.fresh_registry()))
        self.choose(g)
        for other in clones:
            self.choose(other);self.assertEqual(other.snapshot(),g.snapshot())
        self.assertEqual((g.state.players[1].mana,g.state.entities[target].health),(9,1))
        validate_intrinsic_history_prefix(stage,g.state,g.registry);self.check(g)

    def test_committed_wait_restores_frozen_condition_and_single_payment(self):
        self.waiting('card_committed',False)

    def test_completed_wait_restores_frozen_condition_and_single_payment(self):
        self.waiting('card_played',True)

    def test_failed_choice_rolls_back_receipt_histories_and_damage(self):
        self.watcher('card_committed');g=self.closed(board=('condition-watcher',));self.scorch(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.check(g)

    def test_later_empty_turn_changes_new_quote_without_repricing_old_paid_root(self):
        g=self.closed((NATIVE,));self.scorch(g);stage=g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.next_own(g);self.assertEqual((stage.amount,self.fact(g).amount),(1,4))
        validate_intrinsic_history_prefix(stage,g.state,g.registry);self.check(g)

    def test_same_price_omitted_false_row_is_rejected_at_origin_and_retained_prefix(self):
        g=self.game((NATIVE,ELEMENTAL,'empty'));self.play(g,ELEMENTAL);self.play(g,'empty');self.next_own(g)
        stage=self.fact(g).intrinsic;condition=stage.condition_facts[0]
        short=replace(condition,rows=condition.rows[:1]);changed=replace(stage,condition_facts=(short,))
        validate_intrinsic_stage_fact(g.registry,changed);self.assertEqual(changed.amount,1)
        with self.assertRaises(ValueError):validate_intrinsic_origin(changed,g.state,g.registry)
        with self.assertRaises(ValueError):validate_intrinsic_history_prefix(changed,g.state,g.registry)

    def test_fixed_query_rejects_foreign_kind_or_tribe_even_same_boolean(self):
        g=self.closed();stage=self.fact(g).intrinsic
        wrong=PreviousOwnerTurnMatch(1,PlayedTypeQuery(CardType.SPELL,spell_school=SpellSchool.FIRE),
            stage.condition_facts[0].owner_turn,(),False)
        with self.assertRaises(ValueError):replace(stage,condition_facts=(wrong,))

    def test_declarations_reject_unknown_labels_mixed_queries_and_quantity_formulas(self):
        for value in (True,'previous_owner_turn_any_tribe','previous_owner_turn_spell_count'):
            with self.assertRaises(ValueError):IntrinsicCostSpec(condition=value)
        for card in (replace(native_definition(),intrinsic_costs=(IntrinsicCostSpec(set_to=1,condition=CONDITION),IntrinsicCostSpec(delta=-1))),
                replace(native_definition(),player_draw_count_cost=PlayerDrawCountCostSpec())):
            with self.assertRaises(ValueError):validate_definition_intrinsics(card)

    def test_old_same_subject_spell_condition_keeps_original_school_semantics(self):
        self.r.register_card(CardDefinition('old-fire','Original school condition',CardType.SPELL,cost=4,
            on_play='nothing',spell_school=SpellSchool.FIRE,metadata=fixtures.fixtures.metadata(),
            intrinsic_costs=(IntrinsicCostSpec(set_to=1),)))
        g=self.game((NATIVE,'old-fire','fire'));self.play(g,'fire');self.next_own(g)
        source=next(g.state.entities[e] for e in g.state.players[1].hand if g.state.entities[e].card_id=='old-fire')
        old=capture_quote_fact(g.state,g.registry,capture_cost_input(source))
        self.assertEqual((old.amount,self.fact(g).amount),(1,4));self.assertEqual(old.intrinsic.condition_facts[0].query.kind,CardType.SPELL)
        self.check(g)

    def test_player_command_quotes_one_and_private_condition_stays_out_of_view(self):
        g=self.closed();port=g.for_player(1);dto=port.legal_actions()
        row=next(r for r in g.observe(1)['players'][0]['hand'] if r['card_id']==NATIVE)
        action=next(a for a in dto['actions'] if a.get('card')==row['ref'])
        self.assertTrue(port.submit({'revision':dto['revision'],'action':action})['accepted'])
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana),(1,9))
        for player in (1,2):
            data=json.dumps((g.observe(player),g.for_player(player).observe(),g.for_player(player).legal_actions()))
            for field in ('condition_facts','owner_turn_history','played_face','history_profile_id'):self.assertNotIn(field,data)
        self.check(g)

    def test_read_only_repeated_quotes_do_not_allocate_or_consume_rng(self):
        g=self.closed();before=g.snapshot()
        for _ in range(3):self.assertEqual(self.fact(g).amount,1)
        self.assertEqual(g.snapshot(),before)

    def test_existing_wire_roundtrip_and_old_engine_ids_reject_without_schema_migration(self):
        g=self.closed();self.typed(g,self.fact(g).intrinsic);saved=self.check(g)
        self.assertEqual((g.ruleset.id,g.mechanics.version,saved['schema_version']),('prototype-v302',CORE_EFFECTS_VERSION,265))
        for key,subkey,value in (('ruleset','id','prototype-v222'),('mechanics_version','version','core-effects-v216')):
            bad=deepcopy(saved);bad[key][subkey]=value
            with self.assertRaises(SnapshotError):Game.from_snapshot(bad,self.fresh_registry())

    def test_unpublished_real_start_uses_previous_closed_query_and_allows_progress(self):
        fixture=startup_fixtures.StartExpiryIntervalTests();fixture.setUp()
        fixture.r.register_behavior('native.scorch',lambda c:[Damage(c.target_id,4,c.source_id,DamageKind.SPELL)])
        fixture.r.register_card(native_definition());g=fixture.startup_paid_game('choice')
        stage=capture_generated_quote_fact(g.state,g.registry,1,NATIVE).intrinsic
        self.assertIsNone(stage.boundary.last_owner_turn.publication_event)
        self.assertEqual((stage.condition_facts[0].owner_turn.id,stage.amount),(1,4))
        fixture.choose(g);fixture.choose(g);validate_intrinsic_history_prefix(stage,g.state,g.registry)

    def test_pre_first_paid_face_is_excluded_from_previous_own_condition(self):
        fixture=opening_fixtures.OpeningPaidPhaseTests();fixture.setUp()
        fixture.r.register_behavior('native.scorch',lambda c:[Damage(c.target_id,4,c.source_id,DamageKind.SPELL)])
        fixture.r.register_card(native_definition())
        g=fixture.opening(payload_choice=True)
        stage=capture_generated_quote_fact(g.state,g.registry,1,NATIVE).intrinsic
        self.assertEqual((stage.boundary.owner_history_length,stage.condition_facts[0].owner_turn,stage.amount),(0,None,4))
        fixture.choose(g);validate_intrinsic_history_prefix(stage,g.state,g.registry)

