"""Full weighted references with strict actual-result execution and physical sources."""
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.amber_past_minions import POOL,QUERY,SOURCE,load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,
    PlayCard,PlayerSetup,Rarity,ResolutionError,Scenario,SelectChoice,TriggerSpec)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import ChoiceOption,Destroy,GainArmor,RequestChoice
from hs_sim.engine.generation_scopes import GenerationScope,coverage_source,pool_digest
from hs_sim.engine.pools import DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.local_pool_format import build_cn37_local_pool_format

P='fixture.amber.';MISSING=P+'a.missing';KNOWN=P+'z.known';KILL=P+'kill';WATCH=P+'watch'
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=(),factions=(),subtypes=())
CTX=GenerationContext('amber-complete-reference-test','experimental')
RECIPE=AssembleRecipe(SOURCE,'CORE_YOP_034','top').card_id


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=build_registry()
    def forbidden(c):raise ResolutionError('A summoned minion must not run its Battlecry')
    r.register_behavior(P+'cry',forbidden)
    r.register_card(CardDefinition(KNOWN,KNOWN,CardType.MINION,cost=1,attack=2,health=3,battlecry=P+'cry',metadata=META))
    r.register_pool_card(PoolCard.from_definition(r.card(KNOWN)))
    r.register_pool_card(PoolCard(MISSING,CardType.MINION,2,META,battlecry=False,deathrattle=False,choose_one=False,attack=1))
    r.register_behavior(KILL,lambda c:(Destroy(c.target_id,c.source_id),))
    r.register_card(CardDefinition(KILL,KILL,CardType.SPELL,cost=1,on_play=KILL,requires_target=True))
    def watcher(c):
        if c.event.player_id!=c.player_id or c.state.entities[c.event.target_id].card_id!=KNOWN:return()
        if mode=='fault':raise ResolutionError('late arrival fault')
        if mode=='wait':return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue',(GainArmor(c.player_id,2),)),),c.source_id),)
        return()
    r.register_behavior(WATCH,watcher)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=3,triggers=(TriggerSpec('minion_summoned',WATCH),)))
    pool=PoolDefinition(POOL,'full-test-reference-v1',CTX.target_id,CTX.mode,(PoolMember(MISSING),PoolMember(KNOWN)),complete=True)
    r.register_pool(pool)
    r.register_generation_scope(GenerationScope('amber-test',POOL,CTX.target_id,CTX.mode,SOURCE,None,QUERY,pool_digest(pool),
        definition_validation='all_candidates'if mode=='strict'else'selected_summon'))
    return r


class AmberPastMinionTests(unittest.TestCase):
    def game(self,*,mode='normal',seed=0,player=1,assembled=False,full=False):
        source=RECIPE if assembled else SOURCE
        board=((WATCH,)if mode in ('wait','fault')else())+(source,)
        if full:board=(source,)+(KNOWN,)*6
        own=PlayerSetup('HERO_02',hand=(KILL,),board=board,mana=10,max_mana=10)
        other=PlayerSetup('HERO_09')
        g=Game.from_scenario(Scenario((own,other)if player==1 else(other,own),seed=seed,active_player=player,generation_context=CTX),registry(mode),mode='debug')
        return g

    def act(self,g,assembled=False):
        p=g.state.active_player;own=g.state.players[p]
        g.apply(EndTurn(p)if assembled else PlayCard(p,own.hand[0],next(e for e in own.board if g.state.entities[e].card_id==SOURCE)))

    def portable(self,g,mode='normal'):
        saved=g.snapshot();reader=registry(mode,'reader')
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)

    def test_full_local_reference_preserves_all_records_and_independent_exclusions(self):
        d=load_batch();self.assertEqual(len(d['member_ids']),3387);self.assertEqual(len(d['excluded_ids']),29)
        self.assertFalse(d['membership_uses_executable_coverage']);self.assertFalse(d['formal_pool_complete'])
        f=build_cn37_local_pool_format();pool=f.registry.pool(POOL,f.context)
        context=replace(f.context,starting_decks=((),()))
        candidates=resolve_candidates(f.registry,context,POOL,QUERY,source_card_id=SOURCE,player_id=1,exclude_source_by_rule=True)
        self.assertEqual([m.card_id for m in pool.members],d['member_ids'])
        self.assertGreater(len([m for m in candidates if m.card_id not in f.registry.cards]),2000)
        self.assertFalse(set(d['excluded_ids']).intersection(m.card_id for m in candidates))
        self.assertTrue(all(m.weight==1 for m in candidates))
        self.assertEqual(len(f.registry.pool('constructed.past.cards',f.context).members),72)

    def test_missing_unselected_definition_is_retained_in_pure_candidates(self):
        r=registry();rows=resolve_candidates(r,CTX,POOL,QUERY,source_card_id=SOURCE,exclude_source_by_rule=True)
        self.assertEqual([m.card_id for m in rows],[MISSING,KNOWN]);self.assertNotIn(MISSING,r.cards)

    def test_named_spell_discovery_bypasses_ordinary_pool_and_context_binding(self):
        # Presence of a source scope must not turn a complete named recipe into
        # an ordinary generation request. No pool/context exists for this menu.
        r=build_registry();meta=replace(META,collectible=False)
        spells=(P+'named.one',P+'named.two');menu=P+'named.menu'
        for cid in spells:
            card=CardDefinition(cid,cid,CardType.SPELL,metadata=meta)
            r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
        pool=PoolDefinition(POOL,'isolated-reference',CTX.target_id,CTX.mode,(),complete=True)
        r.register_pool(pool);r.register_generation_scope(GenerationScope('named-unrelated-scope',POOL,
            CTX.target_id,CTX.mode,SOURCE,None,QUERY,pool_digest(pool),definition_validation='selected_summon'))
        r.register_behavior(menu,lambda c:(DiscoverFromPool(c.player_id,'named.fixed.cards',source_id=c.source_id,fixed_candidates=spells),))
        r.register_card(CardDefinition(menu,menu,CardType.SPELL,on_play=menu))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_02',hand=(menu,)),PlayerSetup('HERO_09'))),r)
        g.apply(PlayCard(1,g.state.players[1].hand[0]));self.assertIsNotNone(g.state.pending_choice)
        saved=g.snapshot();other=Game.from_snapshot(saved,r);q=g.state.pending_choice
        action=SelectChoice(q.player_id,q.id,(q.options[0].id,))
        g.apply(action);other.apply(action);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertIn(g.state.entities[g.state.players[1].hand[0]].card_id,spells)

    def test_default_all_candidate_policy_keeps_its_pre_rng_rejection(self):
        g=self.game(mode='strict');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.act(g)
        self.assertEqual(g.snapshot(),before)

    def test_actual_missing_result_is_not_resampled_and_whole_action_rolls_back(self):
        g=self.game(seed=1);before=g.snapshot();rng=Random();rng.setstate(g._rng.getstate())
        rows=resolve_candidates(g.registry,CTX,POOL,QUERY,source_card_id=SOURCE,exclude_source_by_rule=True)
        self.assertEqual(sample_candidates(rng,rows,1,replacement=True),(MISSING,))
        with self.assertRaisesRegex(ResolutionError,MISSING):self.act(g)
        self.assertEqual(g.snapshot(),before)

    def test_native_deathrattle_both_seats_runs_original_summon_without_battlecry(self):
        for p in (1,2):
            with self.subTest(player=p):
                g=self.game(player=p);self.act(g)
                self.assertEqual([g.state.entities[e].card_id for e in g.state.players[p].board],[KNOWN])
                root=g.state.pool_summon_history[-1]
                self.assertEqual(root.selected,(KNOWN,));self.assertEqual(root.spec.basis.source.card_id,SOURCE)
                self.assertEqual(len(root.spec.basis.candidates),2);self.assertEqual(g.state.players[p].mana,9)
        self.portable(g)

    def test_assembled_end_turn_uses_approved_donor_but_keeps_physical_source(self):
        g=self.game(assembled=True);self.act(g,True)
        root=g.state.pool_summon_history[-1]
        self.assertEqual(root.spec.basis.source.card_id,RECIPE)
        self.assertEqual(coverage_source(g.registry,RECIPE),SOURCE)
        self.assertEqual(root.selected,(KNOWN,));self.assertEqual(root.status,'completed')
        for p in (1,2):
            port=g.for_player(p)
            self.assertNotIn(MISSING,json.dumps((port.observe(),port.legal_actions(),port.events()),ensure_ascii=False))
        self.portable(g)

    def test_using_only_warden_prefix_cannot_borrow_its_suffix_scope(self):
        r=registry();wrong=AssembleRecipe(SOURCE,'CORE_YOP_034','bottom').card_id
        with self.assertRaises(UnsupportedDefinitionError):resolve_candidates(r,CTX,POOL,QUERY,source_card_id=wrong,exclude_source_by_rule=True)

    def test_wrong_source_or_query_stays_unreviewed(self):
        r=registry()
        for source,query in (('CORE_YOP_034',QUERY),(SOURCE,replace(QUERY,max_cost=1)),(None,QUERY)):
            with self.subTest(source=source),self.assertRaises(UnsupportedDefinitionError):
                resolve_candidates(r,CTX,POOL,query,source_card_id=source,exclude_source_by_rule=True)

    def test_wait_restores_full_reference_and_resumes_original_choice_once(self):
        g=self.game(mode='wait',assembled=True);self.act(g,True)
        self.assertIsNotNone(g.state.pending_choice)
        saved=g.snapshot();other=Game.from_snapshot(saved,registry('wait','reader'))
        q=g.state.pending_choice;action=SelectChoice(q.player_id,q.id,('continue',))
        g.apply(action);other.apply(action);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(len(g.state.pool_summon_history),1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
        self.portable(g,'wait')

    def test_late_arrival_error_rolls_back_payment_death_selection_and_rng(self):
        g=self.game(mode='fault');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'late arrival fault'):self.act(g)
        self.assertEqual(g.snapshot(),before)

    def test_full_board_uses_original_preselection_and_no_extra_delivery(self):
        g=self.game(assembled=True,full=True);self.act(g,True)
        root=g.state.pool_summon_history[-1]
        self.assertEqual(root.selected,(KNOWN,));self.assertEqual(len(g.state.players[1].board),7)
        self.assertNotEqual(root.rng_before,root.rng_after);self.portable(g)

    def test_definition_policy_does_not_authorize_arbitrary_generation_queries(self):
        scope=registry().generation_scopes['amber-test']
        with self.assertRaises(ValueError):replace(scope,query=replace(QUERY,max_cost=1))
        with self.assertRaises(ValueError):replace(scope,definition_validation='ignore')
