"""Full one-cost view, native Disciple and immutable original-deck eligibility."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.one_cost_past_pool import (CARD,SOURCE,POOL_ID,QUERY,load_batch,native_profile,register_one_cost_past_card)
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import CardDefinition,CardType,Game,Keyword,PlayerSetup,ResolutionError,Scenario,Zone
from hs_sim.engine.effects import ChoiceOption,InvokeBehavior,RequestChoice,ReturnToHand
from hs_sim.engine.generation_scopes import GenerationScope
from hs_sim.engine.invoke import invoke_count
from hs_sim.engine.model import CardClass,TriggerSpec
from hs_sim.engine.pools import GenerateFromPool,resolve_candidates,sample_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.representative import build_registry
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest
from tools import card_batch as batch

P='k569.';UNIT,WATCH,START,BOUNCE,FAULT,UNKNOWN=(P+x for x in ('unit','watch','start','bounce','fault','unknown'))


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    if mode=='small':r=build_registry();register_one_cost_past_card(r);fmt=None
    elif mode=='shaman':
        from test_invoke_basics import registry
        r=registry();register_one_cost_past_card(r);fmt=None
    else:fmt=build_cn37_local_pool_format();r=fmt.registry
    def fail(c):raise ResolutionError('k569 deliberate resume failure')
    def watch(c):
        if c.event.kind!='minion_summoned' or c.state.entities[c.event.target_id].card_id not in load_batch()['candidate_ids']:return ()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',
            (InvokeBehavior(FAULT,c.source_id,c.player_id),))),c.source_id),)if mode=='wait'else()
    r.register_behavior(FAULT,fail);r.register_behavior(WATCH,watch);r.register_behavior(START,lambda c:())
    r.register_behavior(BOUNCE,lambda c:(ReturnToHand(c.target_id),))
    r.register_behavior(UNKNOWN,lambda c:(GenerateFromPool(c.player_id,POOL_ID,QUERY,source_id=c.source_id),))
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,attack=1,health=9))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,triggers=(TriggerSpec('minion_summoned',WATCH),)))
    for cid in (START,BOUNCE,UNKNOWN):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,requires_target=cid==BOUNCE))
    r.validate();return r,fmt


def candidates(*,qualified=False,opponent_qualified=False):
    r,fmt=fixture();context=replace(fmt.context,starting_decks=((CARD,)if qualified else(),(CARD,)if opponent_qualified else()))
    return resolve_candidates(r,context,POOL_ID,QUERY,source_card_id=SOURCE,player_id=1,exclude_source_by_rule=True)


def seed_for_disciple():
    rows=candidates(qualified=True)
    return next(seed for seed in range(10000)if CARD in sample_candidates(Random(seed),rows,2,replacement=True))


class OneCostPastPoolTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role)[0])

    def game(self,hand,*,mode='normal',hero='HERO_03',player=1,seed=1,qualified=False):
        self.mode=mode;r,fmt=fixture(mode)
        own=PlayerSetup(hero,hand=hand,board=(WATCH,)if mode=='wait'else(),
            deck=((CARD,)if qualified else())+(UNIT,)*8,mana=20,max_mana=20,mana_cap=20)
        other=PlayerSetup('HERO_08',deck=(UNIT,)*8,mana=10,max_mana=10)
        players=(own,other)if player==1 else(other,own)
        context=None if fmt is None else replace(fmt.context,starting_decks=tuple(p.deck for p in players))
        return Game.from_scenario(Scenario(players,active_player=player,seed=seed,generation_context=context),r)

    def bodies(self,g):
        return[g.state.entities[d.entity.entity_id]for root in g.state.card_summon_history for d in root.deliveries if d.outcome=='delivered']

    def test_full_source_candidate_and_twenty_family_evidence_rows_preserved(self):
        data=load_batch();raw={r['id']:r for r in batch.read(data['source'])}
        self.assertEqual(len(data['candidate_ids']),282);self.assertEqual(len(set(data['candidate_ids'])),282)
        for key in ('cards','existing_dependencies','evidence_only'):
            for row in data[key]:self.assertEqual(row['record'],raw[row['record']['id']])
        for face in data['official_faces']:batch.check_face(raw[face['card_id']],face['face'],face['locale'],{})
        reference=data['candidate_reference'];self.assertEqual(batch.sha(reference['path']),reference['sha256'])
        self.assertEqual(data['candidate_ids'],reference['reference']['complete_candidate_ids'])
        self.assertEqual(len(native_profile().families),5);self.assertFalse(data['formal_pool_complete'])

    def test_actual_paid_disciple_records_no_main_attempt_without_reward_or_success(self):
        g=self.game((CARD,),mode='small');rng=g._rng.getstate();source=self.play(g,CARD)
        self.assertEqual(g.state.players[1].mana,19);e=g.state.entities[source]
        self.assertEqual((e.attack,e.health,e.zone),(1,2,Zone.BOARD));self.assertIn(Keyword.INVOKE,e.keywords)
        self.assertEqual((len(g.state.invoke_history),invoke_count(g.state,1)),(1,0))
        row=g.state.invoke_history[0];self.assertIsNone(row.main_id);self.assertEqual(row.source_id,source)
        self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_two_real_disciple_plays_have_two_unsuccessful_attempts_and_no_fake_two_use_condition(self):
        g=self.game((CARD,CARD),mode='small');self.play(g,CARD);self.play(g,CARD)
        self.assertEqual(len(g.state.invoke_history),2);self.assertEqual(invoke_count(g.state,1),0)
        self.assertEqual(len([e for e in g.events if e.kind=='galakrond_invoked']),2)

    def test_real_disciple_delegates_to_existing_actual_shaman_main_and_upgrade(self):
        from test_invoke_basics import SHAMAN,ELEMENTAL,CONTEXT
        self.mode='shaman';r,_=fixture('shaman')
        g=Game.from_scenario(Scenario((PlayerSetup('hero.mage',hand=(CARD,CARD),deck=(SHAMAN[0],),mana=10,max_mana=10,
            hero_power_card_id='dummy.power'),PlayerSetup('hero.mage')),generation_context=CONTEXT),r)
        self.play(g,CARD);self.play(g,CARD)
        main=g.state.entities[g.state.players[1].deck[0]]
        self.assertEqual(main.card_id,SHAMAN[1]);self.assertEqual(main.galakrond_invocations,2)
        self.assertEqual(invoke_count(g.state,1),2)
        self.assertEqual(sum(g.state.entities[i].card_id==ELEMENTAL for i in g.state.players[1].board),2)
        self.assertEqual(r.invoke_profile.version,'invoke-v1');self.portable(g)

    def test_production_real_families_keep_unadapted_forms_and_gifts_explicit(self):
        r,_=fixture();profile=r.invoke_profile
        self.assertEqual(profile.version,load_batch()['invoke_profile_version'])
        for family in profile.families:
            for cid in family.forms:
                with self.assertRaises(UnsupportedDefinitionError):r.card(cid)
            with self.assertRaises(UnsupportedDefinitionError):r.behavior(family.gift_behavior)

    def test_complete_pool_and_nine_preexisting_missing_metadata_rows_are_registered(self):
        r,fmt=fixture();data=load_batch();pool=r.pool(POOL_ID,fmt.context)
        self.assertEqual([m.card_id for m in pool.members],data['candidate_ids']);self.assertTrue(pool.complete)
        self.assertTrue(all(m.weight==1 for m in pool.members))
        original={row['record']['id']:row for k in ('cards','existing_dependencies')for row in data[k]}
        for cid in data['candidate_ids']:
            self.assertEqual(r.pool_card(cid).metadata,metadata_from_record(original[cid]['record']))
            self.assertEqual(r.card(cid).kind,CardType.MINION)
        self.assertTrue({SOURCE,'TIME_704','GDB_857'} <=
            {scope.source_card_id for scope in r.generation_scopes.values()})

    def test_starting_deck_gate_preserves_raw_member_and_uses_only_original_recipient(self):
        self.assertEqual(len(candidates()),281);self.assertNotIn(CARD,{m.card_id for m in candidates()})
        self.assertEqual(len(candidates(qualified=True)),282)
        self.assertIn(CARD,{m.card_id for m in candidates(qualified=True)})
        self.assertNotIn(CARD,{m.card_id for m in candidates(opponent_qualified=True)})
        r,fmt=fixture()
        with self.assertRaisesRegex(ResolutionError,'starting decks'):
            resolve_candidates(r,fmt.context,POOL_ID,QUERY,source_card_id=SOURCE,player_id=1,exclude_source_by_rule=True)
        self.assertIn(CARD,{m.card_id for m in r.pool(POOL_ID,fmt.context).members})

    def test_full_local_flashback_plain_then_combo_two_real_bodies(self):
        normal=self.game((SOURCE,));self.play(normal,SOURCE)
        combo=self.game((START,SOURCE));self.play(combo,START);self.play(combo,SOURCE)
        plain,buffed=self.bodies(normal),self.bodies(combo)
        self.assertEqual(len(plain),2);self.assertEqual([e.card_id for e in plain],[e.card_id for e in buffed])
        self.assertEqual([e.attack+1 for e in plain],[e.attack for e in buffed])
        self.assertFalse(normal.state.battlecry_history);self.assertFalse(normal.state.invoke_history)
        self.assertEqual((normal.state.players[1].mana,combo.state.players[1].mana),(18,18));self.portable(combo)

    def test_original_qualification_can_generate_disciple_then_bounce_and_play_real_battlecry(self):
        # Scenario checks the original-deck gate; this is not a legal Standard starting deck claim.
        g=self.game((SOURCE,BOUNCE),qualified=True,seed=seed_for_disciple());self.play(g,SOURCE)
        source=self.entity(g,CARD,zone='board').id
        self.assertFalse(g.state.invoke_history);self.play(g,BOUNCE,source);self.play(g,CARD)
        self.assertEqual(len(g.state.invoke_history),1);self.assertEqual(invoke_count(g.state,1),0)
        self.assertIsNone(g.state.invoke_history[0].main_id)

    def test_waiting_between_pool_entries_restores_original_rng_and_bad_resume_is_atomic(self):
        g=self.game((START,SOURCE),mode='wait');self.play(g,START);self.play(g,SOURCE)
        self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
        for game in (g,restored):
            while game.state.pending_choice:self.choose(game)
            self.assertEqual(len(self.bodies(game)),2)
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_any_recipient_class_and_second_seat_use_same_class_independent_view(self):
        for hero,player in (('HERO_08',1),('HERO_06',2)):
            with self.subTest(hero=hero,player=player):
                g=self.game((SOURCE,),hero=hero,player=player);self.play(g,SOURCE,player=player)
                self.assertEqual(len(self.bodies(g)),2)
                self.assertTrue(all(e.controller==player for e in self.bodies(g)))
                self.assertNotIn(CARD,[e.card_id for e in self.bodies(g)])

    def test_unknown_source_same_query_rejected_and_class_dependent_none_scope_invalid(self):
        g=self.game((UNKNOWN,));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Unreviewed generation scope'):self.play(g,UNKNOWN)
        self.assertEqual(g.snapshot(),before)
        r,fmt=fixture();scope=next(s for s in r.generation_scopes.values()if s.source_card_id==SOURCE)
        self.assertIsNone(scope.current_class)
        with self.assertRaises(ValueError):replace(scope,query=replace(QUERY,class_mode='current'))

    def test_eligible_missing_disciple_definition_errors_without_pool_trimming(self):
        r,fmt=fixture('missing-probe');r._cards.pop(CARD)
        context=replace(fmt.context,starting_decks=((CARD,),()))
        self.assertEqual(len(r.pool(POOL_ID,context).members),282)
        with self.assertRaises(UnsupportedDefinitionError):resolve_candidates(r,context,POOL_ID,QUERY,
            source_card_id=SOURCE,player_id=1,exclude_source_by_rule=True)


if __name__=='__main__':unittest.main()
