"""Real Shaman transforms and Joust; complete pools, original references and recovery."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from test_past_shaman_nature_common import fixture as common_fixture,HURTHERO
from test_past_hunter_nature_leaves import A,B,DORMANT
from hs_sim.cards import past_shaman_transforms_joust as native
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.cross_zone import LEGENDARY_BOARD_QUERY,MinionScope,TransformMinionsInZones
from hs_sim.engine.effects import ChoiceOption,Damage,Destroy,InvokeBehavior,RandomDamage,RequestChoice
from hs_sim.engine.errors import SnapshotError
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.model import CardDefinition,CardType,Keyword,Rarity,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery,resolve_candidates,sample_candidates
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

STORM,DEVOLVE,MUTATE,UNSTABLE,EVOLVE,WAVE,EVIL,HEAL,HEAL2=native.ROOTS
P='k673.';C0,C1,L2,C4,C5,L8,C9,C10,C12=(P+x for x in('c0','c1','l2','c4','c5','l8','c9','c10','c12'))
WATCH,JWATCH,FAIL,CRY=(P+x for x in('watch','jwatch','fail','cry'))
CTX=GenerationContext('k673-complete-costs-and-legends','experimental')


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=common_fixture('k673-'+role);native.register_past_shaman_transforms_joust(r)
    r.register_behavior(CRY,lambda c:(Damage(c.state.players[3-c.player_id].hero_id,5,c.source_id),))
    for cid,cost in((C0,0),(C1,1),(L2,2),(C4,4),(C5,5),(L8,8),(C9,9),(C10,10),(C12,12)):
        card=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=2,health=14 if cid==C12 else 8,
            battlecry=CRY if cid in(L2,L8)else None,metadata=metadata(tribes=(),rarity=Rarity.LEGENDARY if cid in(L2,L8)else Rarity.COMMON))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    members=(C0,C1,C4,C5,C9,C10,C12)if role.startswith('empty-')else(C0,C1,L2,C4,C5,L8,C9,C10,C12)
    r.register_pool(PoolDefinition('constructed.cards','k673-full-diagnostic',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid,3 if cid==L8 else 1)for cid in members),complete=True))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K673 deliberate rollback')))
    def choices(c,joust=False):
        target=c.state.entities.get(c.event.target_id)
        if not joust and (target is None or target.controller!=1):return()
        options=[ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))]
        if not joust and len(c.state.players[1].board)>1:
            options.append(ChoiceOption('remove','Remove remaining',(Destroy(c.state.players[1].board[-1],c.source_id),)))
        return(RequestChoice(c.player_id,tuple(options),c.source_id),)
    for cid,event,body in((WATCH,'transformed',lambda c:choices(c)),(JWATCH,'joust_resolved',lambda c:choices(c,True))):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=20,health=20,
            triggers=(TriggerSpec(event,cid),),metadata=metadata(collectible=False,tribes=())))
    r.validate();return r


class ShamanTransformsJoustTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(('empty-'if mode=='empty'else'')+role))

    def game(self,hand=(),*,board=(),enemy=(),deck=(C4,),enemy_deck=(C1,),empty_pool=False):
        self.mode='empty'if empty_pool else'small'
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',board=enemy,deck=enemy_deck,mana=10,max_mana=10)),seed=673,generation_context=CTX),fixture('empty-writer'if empty_pool else'writer'))
    def hero(self,g,player=1):return g.state.entities[g.state.players[player].hero_id]
    def finish(self,g):
        n=0
        while g.state.pending_choice is not None:
            self.choose(g,g.state.pending_choice.options[0].id);n+=1;self.assertLess(n,12)

    def test_all_nine_complete_faces_and_twenty_primary_faces_have_exact_pins(self):
        d=native.load_batch();r=fixture('writer');self.assertEqual((len(d['cards']),len(d['official_observations'])),(9,20))
        self.assertEqual(len(d['original_shaman_member_ids']),71);self.assertFalse(d['complete_shaman_source_bound'])
        for row in d['cards']:
            cid=row['record']['id'];self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(r.pool_card(cid))),row['pool_card_sha256'])
        self.assertEqual(r.card(MUTATE).cost,0);self.assertIn(Keyword.ECHO,r.card(UNSTABLE).keywords)

    def test_all_nine_actual_hand_entries_pay_original_cost_once(self):
        for cid in native.ROOTS:
            with self.subTest(card=cid):
                g=self.game((cid,),board=(A,),enemy=(C4,));target=self.hero(g).id if cid in(HEAL,HEAL2)else g.state.players[1].board[0]if cid in(MUTATE,UNSTABLE)else g.state.players[2].board[0]if cid==EVIL else None
                self.play(g,cid,target);self.finish(g)
                self.assertEqual(g.state.players[1].mana,10-g.registry.card(cid).cost)
                self.assertEqual([r.card_id for r in g.state.cast_history],[cid])

    def test_storm_uses_all_costs_of_complete_legendary_view_preserves_entities_and_no_battlecry(self):
        g=self.game((STORM,),board=(A,C0,C5),enemy=(B,));ids=list(g.state.players[1].board);self.play(g,STORM)
        self.assertEqual(g.state.players[1].board,ids)
        self.assertTrue(all(g.state.entities[e].card_id in(L2,L8)for e in ids))
        self.assertTrue(any(g.registry.card(g.state.entities[e].card_id).cost!=1 for e in ids))
        self.assertEqual(self.hero(g,2).health,30);self.assertEqual(g.state.death_history,[]);self.portable(g)

    def test_storm_full_weighted_candidate_list_is_not_a_same_cost_or_batch_subset(self):
        g=self.game((STORM,),board=(A,));rng=Random();rng.setstate(g._rng.getstate())
        rows=resolve_candidates(g.registry,CTX,'constructed.cards',LEGENDARY_BOARD_QUERY)
        expected=sample_candidates(rng,rows,1,replacement=True)[0];self.play(g,STORM)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].card_id,expected)
        self.assertEqual([m.card_id for m in g.registry.pool('constructed.cards',CTX).members],[C0,C1,L2,C4,C5,L8,C9,C10,C12])
        self.assertEqual(g.registry.pool('constructed.cards',CTX).members[5].weight,3)

    def test_storm_excludes_dormant_and_enemy_minions_and_empty_group_has_no_rng(self):
        g=self.game((STORM,),board=(A,DORMANT),enemy=(B,));self.play(g,STORM)
        self.assertEqual(self.entity(g,DORMANT,zone='board').card_id,DORMANT);self.assertEqual(self.entity(g,B,2,'board').card_id,B)
        g=self.game((STORM,));rng=g.snapshot()['rng_state'];self.play(g,STORM);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_storm_empty_complete_legendary_domain_skips_without_rng_or_mutation(self):
        g=self.game((STORM,),board=(A,),empty_pool=True);old=g.state.players[1].board[0];rng=g.snapshot()['rng_state'];self.play(g,STORM)
        self.assertEqual((g.state.players[1].board,g.state.entities[old].card_id),([old],A));self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

    def test_storm_original_remaining_target_wait_restores_and_failed_choice_rolls_back_rng(self):
        g=self.game((STORM,),board=(A,A),enemy=(WATCH,));ids=list(g.state.players[1].board);self.play(g,STORM)
        self.assertIsNotNone(g.state.pending_choice);self.assertIn(g.state.entities[ids[0]].card_id,(L2,L8));self.assertEqual(g.state.entities[ids[1]].card_id,A)
        self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.finish(g);self.assertTrue(all(g.state.entities[e].card_id in(L2,L8)for e in ids));self.portable(g)

    def test_departed_remaining_storm_target_is_not_pulled_back_and_consumes_no_next_rng(self):
        g=self.game((STORM,),board=(A,A),enemy=(WATCH,));self.play(g,STORM);rng=g.snapshot()['rng_state']
        self.assertIsNotNone(g.state.pending_choice);self.choose(g,'remove')
        self.assertEqual(len(g.state.players[1].board),1);self.assertEqual(g.snapshot()['rng_state'],rng);self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_evolve_and_mutate_use_existing_printed_cost_tier(self):
        for cid in(EVOLVE,MUTATE):
            with self.subTest(card=cid):
                g=self.game((cid,),board=(A,));target=g.state.players[1].board[0];self.play(g,cid,target if cid==MUTATE else None)
                self.assertEqual(g.state.entities[target].card_id,L2);self.assertEqual(g.state.players[1].board,[target]);self.portable(g)

    def test_devolve_falls_to_existing_lower_available_tier_and_does_not_touch_our_board(self):
        g=self.game((DEVOLVE,),board=(A,),enemy=(C4,));target=g.state.players[2].board[0];self.play(g,DEVOLVE)
        self.assertEqual(g.state.entities[target].card_id,L2);self.assertEqual(self.entity(g,A,zone='board').card_id,A);self.portable(g)

    def test_primordial_wave_has_actual_enemy_devolve_then_friendly_evolve(self):
        g=self.game((WAVE,),board=(A,),enemy=(C4,));a=g.state.players[1].board[0];b=g.state.players[2].board[0];self.play(g,WAVE)
        self.assertEqual((g.state.entities[a].card_id,g.state.entities[b].card_id),(L2,L2));self.assertEqual(g.state.death_history,[]);self.portable(g)

    def test_explosive_evolution_uses_plus_three_cap_and_existing_above_ten_policy(self):
        for source,want in((A,C4),(C9,C10),(C12,C12)):
            with self.subTest(source=source):
                g=self.game((EVIL,),enemy=(source,));target=g.state.players[2].board[0];self.play(g,EVIL,target)
                self.assertEqual(g.state.entities[target].card_id,want)

    def test_friendly_target_restrictions_and_hero_targets_fail_atomically(self):
        for cid in(MUTATE,UNSTABLE,EVIL):
            g=self.game((cid,),enemy=(B,));saved=deepcopy(g.snapshot())
            with self.assertRaises(IllegalAction):self.play(g,cid,self.hero(g,2).id)
            self.assertEqual(g.snapshot(),saved)
            if cid!=EVIL:
                with self.assertRaises(IllegalAction):self.play(g,cid,g.state.players[2].board[0])
                self.assertEqual(g.snapshot(),saved)

    def test_real_unstable_evolution_echo_copy_pays_again_and_expires_at_end(self):
        g=self.game((UNSTABLE,),board=(A,));target=g.state.players[1].board[0];self.play(g,UNSTABLE,target)
        self.assertEqual(g.state.entities[target].card_id,L2);self.assertEqual(len(g.state.players[1].hand),1)
        self.portable(g);self.play(g,UNSTABLE,target);self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual(len(g.state.cast_history),2);g.apply(EndTurn(1));self.assertEqual(g.state.players[1].hand,[]);self.portable(g)

    def test_both_healing_waves_win_loss_tie_and_empty_decks_use_original_eight_or_sixteen(self):
        for cid in(HEAL,HEAL2):
            for own,enemy,amount in(((C4,),(C1,),16),((C1,),(C4,),8),((C1,),(C1,),8),((),(C1,),8),((C1,),(),16),((),(),8)):
                with self.subTest(card=cid,own=own,enemy=enemy):
                    g=self.game((HURTHERO,cid),deck=own,enemy_deck=enemy);self.play(g,HURTHERO)
                    decks=[list(g.state.players[p].deck)for p in(1,2)];self.play(g,cid,self.hero(g).id)
                    self.assertEqual(self.hero(g).health,10+amount);self.assertEqual([g.state.players[p].deck for p in(1,2)],decks)
                    self.assertEqual(g.state.players[1].mana,7)

    def test_healing_wave_original_joust_result_wait_precedes_heal_and_roundtrips(self):
        g=self.game((HURTHERO,HEAL),enemy=(JWATCH,));self.play(g,HURTHERO);self.play(g,HEAL,self.hero(g).id)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.hero(g).health,10);self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.finish(g);self.assertEqual(self.hero(g).health,26);self.portable(g)

    def test_untiered_policy_rejects_unreviewed_scope_cost_and_query_mixtures(self):
        base=TransformMinionsInZones(1,'constructed.cards',scope=native.BOARD,query=LEGENDARY_BOARD_QUERY,cost_basis='none',source_id=1)
        base.__post_init__()
        for kwargs in(dict(cost_delta=1),dict(scope=MinionScope()),dict(query=PoolQuery(kinds=(CardType.MINION,),collectible=True)),dict(retain_cost_basis='printed'),dict(source_id=None)):
            with self.subTest(fields=kwargs):
                with self.assertRaises(ValueError):replace(base,**kwargs).__post_init__()

    def test_current_codec_roundtrips_new_policy_and_rejects_previous_schema(self):
        g=self.game((STORM,),board=(A,A),enemy=(WATCH,));self.play(g,STORM);saved=deepcopy(g.snapshot())
        self.assertEqual(saved['schema_version'],SNAPSHOT_SCHEMA_VERSION);self.assertEqual(saved['mechanics_version']['version'],CORE_EFFECTS_VERSION);self.portable(g)
        saved['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,fixture('writer'))

    def test_real_standard_storm_and_healing_wave_keep_complete_host_and_recovery(self):
        self.mode='host';h=host();deck=('CORE_EX1_169',)*16
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_02',hand=(STORM,HEAL),board=('LOOT_077t',),deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=deck,mana=10,max_mana=10)),seed=673,generation_context=h.context),h.registry)
        self.play(g,STORM);entity=g.state.entities[g.state.players[1].board[0]]
        self.assertEqual(g.registry.pool_card(entity.card_id).metadata.rarity,Rarity.LEGENDARY)
        self.play(g,HEAL,self.hero(g).id);self.assertEqual(g.state.players[1].mana,1);self.portable(g)
