"""Real acquired past spells through physical source and ranked death entry paths."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
from random import Random
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture as base_fixture, P, FILLER
from hs_sim.cards.past_recruit_resurrection import ROOTS, load_batch
from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayerSetup,
    ResolutionError, Scenario, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import ChoiceOption, Destroy, GrantKeyword, InvokeBehavior, RequestChoice
from hs_sim.engine.model import CostSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember, resolve_candidates, sample_candidates
from hs_sim.engine.recruit_summons import validate_record as validate_recruit
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.student_teaching import QUERY
from hs_sim.engine.summon_sources import DeathQuery, Resurrect, SummonFromZone
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from tools import card_batch as batch

S = 'k552.'
WATCH = S+'watch'
HIGH, MID, LOW, SMALL = 'CORE_LOOT_137', 'TTN_724', 'EDR_272', 'CORE_CS2_179'
NEW_HIGH = 'JAIL_890'
CTX = GenerationContext('k552-two-native-past-spells-test', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    fmt = base_fixture.__wrapped__('normal', role); r = fmt.registry
    for name in ('constructed.cards', 'constructed.minions', 'constructed.assemble'):
        r.register_pool(replace(r.pool(name, fmt.context), target_id=CTX.target_id, mode=CTX.mode))
    r.register_pool(PoolDefinition('constructed.past.spells', 'two-native-zone-spells-test-v1',
        CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in ROOTS), complete=True))

    def fail(c): raise ResolutionError('k552 deliberate late failure')

    def kill(c):
        return tuple(Destroy(i, c.source_id) for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id in (HIGH, MID, LOW, SMALL, FILLER))

    def seed(c):
        prices = {LOW:5, FILLER:6, 'OG_141':1, 'CORE_CS2_029':0}
        return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),
            CostSpec(set_to=prices[c.state.entities[i].card_id]), c.source_id)
            for i in c.state.players[c.player_id].deck)

    def observe(c):
        recruit = c.state.recruit_summon_history
        resurrection = c.state.resurrection_summon_history
        if mode in ('recruit_wait', 'recruit_fault') and recruit:
            root = recruit[-1]
            if root.spec.cause.cast_card_id != 'SCH_610': return ()
            if mode=='recruit_fault' and len(root.rounds)==2:
                return (InvokeBehavior(S+'fail', c.source_id, c.player_id),)
            if mode!='recruit_wait' or len(root.rounds)!=1: return ()
            work = tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),
                CostSpec(set_to=9), c.source_id) for i in c.state.players[c.player_id].deck)
        elif mode in ('resurrection_wait', 'resurrection_fault') and resurrection:
            root = resurrection[-1]
            if root.spec.cause.cast_card_id != 'VAC_948': return ()
            if mode=='resurrection_fault' and len(root.picks)==2:
                return (InvokeBehavior(S+'fail', c.source_id, c.player_id),)
            if mode!='resurrection_wait' or len(root.picks)!=1: return ()
            work = tuple(Destroy(i, c.source_id) for i in c.state.players[c.player_id].board
                if c.state.entities[i].card_id==NEW_HIGH)
        else:return ()
        return (*work, RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Continue', ()),
            ChoiceOption('fault', 'Fail', (InvokeBehavior(S+'fail', c.source_id, c.player_id),))), c.source_id))

    bodies = {'kill':kill, 'seed':seed, 'fail':fail,
        'grant':lambda c:(GrantKeyword(c.target_id, Keyword.TAUNT, c.source_id),),
        'kill_enemy':lambda c:tuple(Destroy(i, c.source_id) for i in c.state.players[3-c.player_id].board)}
    for name, body in bodies.items():
        r.register_behavior(S+name, body)
        r.register_card(CardDefinition(S+name, name, CardType.SPELL, on_play=S+name,
            requires_target=name=='grant'))
    r.register_behavior(S+'observe', observe)
    r.register_card(CardDefinition(WATCH, 'Zone observer', CardType.MINION, health=30,
        triggers=(TriggerSpec('minion_summoned', S+'observe'),)))
    r.validate();return replace(fmt, context=CTX)


class PastRecruitResurrectionTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(lambda mode, role:fixture(mode, role).registry)

    def game(self, hand, *, board=(), deck=(), enemy=(), mode='normal', seed=1):
        self.mode=mode;fmt=fixture(mode)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06', hand=hand, board=board, deck=deck, max_mana=10, mana=10),
            PlayerSetup('HERO_08', board=enemy)), seed=seed, generation_context=CTX), fmt.registry)

    def deaths(self, board=(HIGH,HIGH,MID,LOW,SMALL), *, mode='normal', extra=()):
        game=self.game((S+'kill','VAC_948'), board=(*board,*extra), mode=mode)
        self.play(game,S+'kill');return game

    def rehash(self, saved):
        saved['events_hash']=canonical_hash(saved['events'])
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        return saved

    def test_full_original_rows_primary_faces_and_explicit_unverified_local_policies(self):
        data=load_batch();source={r['id']:r for r in batch.read(data['source'])}
        self.assertEqual(batch.sha(data['source']),data['source_sha256'])
        for row in data['cards']:
            raw=row['record'];self.assertEqual(raw,source[raw['id']])
            card=fixture().registry.card(raw['id'])
            self.assertEqual((card.cost,card.kind),(raw['cost'],CardType.SPELL))
        for observation in data['official_faces']:
            batch.check_face(source[observation['card_id']],observation['face'],observation['locale'])
        self.assertEqual({c.value for c in fixture().registry.card('SCH_610').metadata.classes},{'druid','hunter'})
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])
        self.assertIn('not CN calibrated',data['local_rules']['hydration_cost_basis'])

    def test_animals_moves_two_original_deck_entities_and_grants_rush_without_drawing(self):
        game=self.game(('SCH_610',),deck=(FILLER,FILLER))
        original=tuple(game.state.players[1].deck);source=self.play(game,'SCH_610')
        self.assertEqual(set(game.state.players[1].board),set(original))
        self.assertFalse(game.state.players[1].deck);self.assertFalse(game.state.draw_history)
        self.assertEqual(game.state.players[1].mana,3)
        for i in original:
            body=game.state.entities[i]
            self.assertEqual((body.attack,body.health),(5,5))
            self.assertTrue({Keyword.RUSH,Keyword.STEALTH}<=body.keywords)
        root=game.state.recruit_summon_history[-1]
        self.assertEqual((root.status,len(root.rounds),root.spec.cause.source.entity_id),('completed',2,source))
        self.assertEqual(root.spec.cause.cast_card_id,'SCH_610');self.portable(game)

    def test_animals_current_deck_cost_includes_discounted_six_and_excludes_increased_five(self):
        game=self.game((S+'seed','SCH_610'),deck=(LOW,FILLER,'OG_141','CORE_CS2_029'))
        original={game.state.entities[i].card_id:i for i in game.state.players[1].deck}
        self.play(game,S+'seed');self.play(game,'SCH_610')
        self.assertEqual(game.state.players[1].board,[original[LOW]])
        root=game.state.recruit_summon_history[-1];basis=root.rounds[0].basis
        self.assertEqual(len(basis.inventory),4);self.assertEqual(basis.cost_basis,'local')
        self.assertEqual({x.allocation.card_id:x.current_cost for x in basis.inventory},
            {LOW:5,FILLER:6,'OG_141':1,'CORE_CS2_029':0})
        self.assertEqual(root.rounds[0].selected.entity_id,original[LOW])
        self.assertEqual(root.status,'exhausted');self.portable(game)

    def test_animals_wait_retains_owed_rush_then_requeries_changed_remaining_deck(self):
        game=self.game(('SCH_610',),board=(WATCH,),deck=(FILLER,FILLER),mode='recruit_wait')
        self.play(game,'SCH_610');root=game.state.recruit_summon_history[-1]
        selected=root.rounds[0].selected.entity_id
        self.assertNotIn(Keyword.RUSH,game.state.entities[selected].keywords)
        self.assertEqual(root.rounds[0].basis.inventory[0].current_cost,5)
        restored=self.portable(game);saved=restored.snapshot()
        with self.assertRaises(ResolutionError):self.choose(restored,'fault')
        self.assertEqual(restored.snapshot(),saved)
        self.choose(restored);self.choose(game)
        self.assertEqual(restored.snapshot(),game.snapshot())
        self.assertIn(Keyword.RUSH,game.state.entities[selected].keywords)
        root=game.state.recruit_summon_history[-1]
        self.assertEqual(root.status,'exhausted')
        self.assertEqual([x.current_cost for x in root.rounds[1].basis.inventory],[9])
        self.portable(game)

    def test_animals_full_board_and_empty_qualified_deck_preserve_rng_and_physical_inventory(self):
        for board,deck in (((FILLER,)*7,(FILLER,)),((),('OG_141','CORE_CS2_029'))):
            with self.subTest(full=bool(board)):
                game=self.game(('SCH_610',),board=board,deck=deck)
                original=tuple(game.state.players[1].deck);rng=game.snapshot()['rng_state']
                self.play(game,'SCH_610')
                self.assertEqual(tuple(game.state.players[1].deck),original)
                self.assertEqual(game.snapshot()['rng_state'],rng)
                self.assertEqual(game.state.players[1].mana,3)
                self.assertFalse(game.state.successful_summon_history)

    def test_actual_second_recruit_failure_rolls_back_payment_movements_keywords_and_rng(self):
        game=self.game(('SCH_610',),board=(WATCH,),deck=(FILLER,FILLER),mode='recruit_fault')
        saved=game.snapshot()
        with self.assertRaises(ResolutionError):self.play(game,'SCH_610')
        self.assertEqual(game.snapshot(),saved)

    def test_hydration_descends_remaining_cost_tiers_and_removes_all_same_card_deaths(self):
        game=self.deaths();old={r.entity_id for r in game.state.death_history}
        self.play(game,'VAC_948');root=game.state.resurrection_summon_history[-1]
        cards=[game.state.death_history[p.selected-1].card_id for p in root.picks]
        self.assertEqual(cards,[HIGH,MID,LOW]);self.assertEqual(len(root.basis.inventory),5)
        self.assertEqual(len(root.candidates),5);self.assertEqual(len(root.picks[1].available),3)
        self.assertTrue(old.isdisjoint(game.state.players[1].board))
        self.assertEqual(game.state.players[1].mana,2)
        self.assertEqual(root.status,'completed');self.portable(game)

    def test_hydration_uses_actual_taunt_at_death_and_friendly_controller(self):
        game=self.game((P+'quiet',S+'grant',S+'kill',S+'kill_enemy','VAC_948'),
            board=(HIGH,LOW,FILLER),enemy=(HIGH,))
        self.play(game,P+'quiet',self.entity(game,HIGH,zone='board').id)
        self.play(game,S+'grant',self.entity(game,FILLER,zone='board').id)
        self.play(game,S+'kill');self.play(game,S+'kill_enemy');self.play(game,'VAC_948')
        cards=[game.state.entities[i].card_id for i in game.state.players[1].board]
        self.assertEqual(cards,[LOW,FILLER])
        self.assertNotIn(Keyword.TAUNT,self.entity(game,FILLER,zone='board').keywords)
        root=game.state.resurrection_summon_history[-1]
        self.assertEqual((len(root.basis.inventory),len(root.candidates)),(4,2))

    def test_hydration_forced_tiers_do_not_consume_rng_and_empty_pool_finishes_normally(self):
        for board in ((HIGH,MID,LOW),()):
            with self.subTest(board=board):
                game=self.deaths(board);rng=game.snapshot()['rng_state']
                self.play(game,'VAC_948')
                self.assertEqual(game.snapshot()['rng_state'],rng)
                self.assertEqual(len(game.state.players[1].board),len(board))

    def test_hydration_wait_preserves_original_deaths_and_ignores_new_higher_cost_death(self):
        game=self.deaths(mode='resurrection_wait',extra=(WATCH,NEW_HIGH))
        self.play(game,'VAC_948');root=game.state.resurrection_summon_history[-1]
        self.assertEqual((len(root.basis.inventory),len(game.state.death_history)),(5,6))
        restored=self.portable(game);saved=restored.snapshot()
        with self.assertRaises(ResolutionError):self.choose(restored,'fault')
        self.assertEqual(restored.snapshot(),saved)
        self.choose(restored);self.choose(game);self.assertEqual(restored.snapshot(),game.snapshot())
        cards=[game.state.entities[i].card_id for i in game.state.players[1].board]
        self.assertEqual(cards,[WATCH,HIGH,MID,LOW]);self.portable(game)

    def test_actual_second_resurrection_failure_rolls_back_all_new_bodies_and_original_payment(self):
        game=self.deaths(mode='resurrection_fault',extra=(WATCH,));saved=game.snapshot()
        with self.assertRaises(ResolutionError):self.play(game,'VAC_948')
        self.assertEqual(game.snapshot(),saved)

    def test_finite_request_and_original_current_cost_inventory_are_strict(self):
        for fields in (dict(cost_basis=True),dict(cost_basis='current'),dict(cost_basis='local'),
                dict(cost_basis='local',query=QUERY),dict(selection='unknown')):
            with self.assertRaises(ValueError):SummonFromZone(1,**fields)
        for fields in (dict(selection='highest_cost'),dict(selection='highest_cost',distinct='card'),
                dict(selection=True)):
            with self.assertRaises(ValueError):Resurrect(1,**fields)
        game=self.game(('SCH_610',),deck=(FILLER,));self.play(game,'SCH_610')
        root=game.state.recruit_summon_history[-1];basis=root.rounds[0].basis
        with self.assertRaises(ValueError):replace(basis,cost_basis='printed')
        with self.assertRaises(ValueError):replace(basis.inventory[0],current_cost=True)
        changed=replace(basis,inventory=(replace(basis.inventory[0],current_cost=9),))
        with self.assertRaises(ValueError):validate_recruit(game.state,game.registry,
            replace(root,rounds=(replace(root.rounds[0],basis=changed),*root.rounds[1:])))

    def test_rehashed_current_cost_and_ranked_selection_cannot_diverge_from_original_receipts(self):
        game=self.game(('SCH_610',),board=(WATCH,),deck=(FILLER,FILLER),mode='recruit_wait')
        self.play(game,'SCH_610');saved=game.snapshot()
        for field,value in (('current_cost',True),('current_cost',9)):
            changed=deepcopy(saved)
            changed['state']['recruit_summon_history'][0]['rounds'][0]['basis']['inventory'][0][field]=value
            with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(changed),fixture(self.mode).registry)
        game=self.deaths(mode='resurrection_wait',extra=(WATCH,NEW_HIGH));self.play(game,'VAC_948')
        changed=deepcopy(game.snapshot());changed['state']['resurrection_summon_history'][0]['spec']['selection']='first'
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(changed),fixture(self.mode).registry)
        changed=deepcopy(game.snapshot());changed['schema_version']=588
        with self.assertRaises(SnapshotError):Game.from_snapshot(changed,fixture(self.mode).registry)

    def test_real_teacher_and_same_student_execute_both_native_zone_spells(self):
        registry=fixture().registry
        rows=resolve_candidates(registry,CTX,'constructed.past.spells',QUERY,
            current_class=registry.card('VAC_948').metadata.classes[0],source_card_id='TIME_704',player_id=1)
        for cid in ROOTS:
            with self.subTest(card=cid):
                seed=next(n for n in range(20)if cid in sample_candidates(Random(n),rows,3,replacement=False))
                game=self.game((S+'kill','TIME_704'),board=(HIGH,MID),deck=(FILLER,FILLER),seed=seed)
                self.play(game,S+'kill');self.play(game,'TIME_704')
                selected=next(o for o in game.state.pending_choice.options if o.card_id==cid)
                self.choose(game,selected.id);self.play(game,'TIME_704t')
                self.assertIsNone(game.state.pending_choice)
                self.assertTrue(any(r.card_id==cid and r.origin=='effect'for r in game.state.cast_history))
                if cid=='SCH_610':
                    self.assertEqual(sum(game.state.entities[i].card_id==FILLER
                        for i in game.state.players[1].board),2)
                    self.assertTrue(all(Keyword.RUSH in game.state.entities[i].keywords
                        for i in game.state.players[1].board if game.state.entities[i].card_id==FILLER))
                    self.assertEqual(game.state.recruit_summon_history[-1].spec.cause.cast_card_id,cid)
                else:self.assertEqual(len(game.state.resurrection_summon_history[-1].picks),2)
        self.portable(game)


if __name__=='__main__':unittest.main()
