"""Real Whirlpool entry, one-shot physical copies and complete source views."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import past_priest_nature_source as native
from hs_sim.cards.simple_followup_p89_cards import WO,NATURE_PAST_POOL,QUERIES
from hs_sim.engine import Game,PlayCard,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,GainArmor,InvokeBehavior,
    RandomDamage,RequestChoice,Summon,Transform)
from hs_sim.engine.minion_copy_destruction import DestroyMinionCopies
from hs_sim.engine.model import (CardClass,CardDefinition,CardType,CostSpec,Keyword,
    SummonStats,TriggerSpec,Zone)
from hs_sim.engine.pools import PoolMember,resolve_candidates
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.zones import AddToDeck,CardReference,CopyCard,DestroyStoredBatch,MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError,canonical_digest

P='k665.'
HERO,WATCH,A,B,RATTLE,REBORN,DORMANT,LOCATION,PREP,CHANGE,QUEUE,STALE,FAULT=(P+x for x in
    ('hero','watch-hero','a','b','rattle','reborn','dormant','location','prepare','change','queue','stale','fault'))
TSC=native.CARD


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=opening_registry();native.register_past_priest_nature_card(r)
    r.register_behavior(FAULT,lambda c:(_ for _ in ()).throw(ResolutionError('K665 deliberate rollback')))
    def waiting(c):
        # Event contexts freeze individually at each notice. All stored targets
        # departed before even the first board notice; the live board mark batch
        # is asserted by the test at its committed waiting boundary instead.
        if any(c.state.entities[i].card_id==A for p in (1,2)for z in ('hand','deck')for i in getattr(c.state.players[p],z)):
            raise ResolutionError('A reaction observed an unfinished stored departure batch')
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
            InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,waiting)
    for cid,fields in ((HERO,{}),(WATCH,dict(triggers=tuple(TriggerSpec(k,WATCH)
            for k in ('destroyed','card_destroyed_in_hand','card_destroyed_in_deck'))))):
        r.register_card(CardDefinition(cid,cid,CardType.HERO,health=60,metadata=metadata(CardClass.MAGE),**fields))
    r.register_card(CardDefinition(A,'Same printed name',CardType.MINION,cost=2,attack=2,health=4,metadata=metadata()))
    r.register_card(CardDefinition(B,'Same printed name',CardType.MINION,cost=2,attack=2,health=4,metadata=metadata()))
    def destroyed(c):
        if c.destruction is None or c.source.zone!=Zone.GRAVEYARD:
            raise ResolutionError('Stored native body lost its actual destruction')
        return(GainArmor(c.player_id,2),)
    r.register_behavior(P+'native',destroyed)
    r.register_behavior(P+'discard',lambda c:(GainArmor(c.player_id,19),))
    r.register_behavior(RATTLE,lambda c:(Summon(c.player_id,RATTLE),AddToHand(c.player_id,RATTLE,c.source_id),
        AddToDeck(c.player_id,RATTLE,position='bottom',source_id=c.source_id)))
    r.register_card(CardDefinition(RATTLE,RATTLE,CardType.MINION,attack=1,health=3,deathrattle=RATTLE,
        on_destroyed=P+'native',on_discard=P+'discard',metadata=metadata()))
    r.register_card(CardDefinition(REBORN,REBORN,CardType.MINION,attack=1,health=3,keywords=(Keyword.REBORN,),metadata=metadata()))
    r.register_card(CardDefinition(DORMANT,DORMANT,CardType.MINION,attack=1,health=3,dormant_turns=2,metadata=metadata()))
    r.register_behavior(LOCATION,lambda c:())
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,durability=2,on_use=LOCATION,metadata=metadata()))
    def first(c,cid,zone='hand',player=1):
        return c.state.entities[next(i for i in getattr(c.state.players[player],zone)if c.state.entities[i].card_id==cid)]
    def prepare(c):
        ref=CardReference.capture(first(c,A))
        return(Buff(first(c,A,'board').id,3,4,c.source_id),
            CopyCard(ref,1,stats=SummonStats(1,1),cost=CostSpec(set_to=0),source_id=c.source_id),
            CopyCard(ref,2,destination=Zone.DECK,position='bottom',cost=CostSpec(set_to=0),source_id=c.source_id))
    def change(c):return(Transform(first(c,A,'board').id,B),TransformStoredCard(CardReference.capture(first(c,A)),B))
    def queued(c):
        refs=tuple(CardReference.capture(c.state.entities[i])for p in (1,2)for z in ('hand','deck')
            for i in getattr(c.state.players[p],z)if c.state.entities[i].card_id==A)
        return(RequestChoice(c.player_id,(ChoiceOption('batch','Stored batch',(DestroyStoredBatch(refs,c.source_id),)),
            ChoiceOption('copies','All minion copies',(DestroyMinionCopies(c.source_id),)),
            ChoiceOption('source','Invalid source',(DestroyMinionCopies(999999),))),c.source_id),)
    def stale(c):
        ref=CardReference.capture(first(c,A));other=CardReference.capture(first(c,A,'deck'))
        return(MoveCard(ref,1,Zone.DECK,position='bottom',source_id=c.source_id),
            TransformStoredCard(other,B),DestroyStoredBatch((ref,other),c.source_id))
    for cid,body in ((PREP,prepare),(CHANGE,change),(QUEUE,queued),(STALE,stale)):
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata(collectible=False)))
    r.validate();return r


class PriestNatureSourceTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(TSC,),*,board=(),enemy=(),other_hand=(),deck=('card.1',)*8,other_deck=('card.2',)*8,watch=False,rules=None):
        self.mode='small'
        return Game.from_scenario(Scenario((PlayerSetup(WATCH if watch else HERO,hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup(HERO,hand=other_hand,board=enemy,deck=other_deck,mana=10,max_mana=10)),seed=665),fixture(),
            ruleset=Ruleset()if rules is None else rules)

    def actual(self,hero='HERO_09'):
        self.mode='host';h=host();deck=('CORE_EX1_169',)*20
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=('CORE_EX1_169',),board=(WO,),deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=deck,mana=10,max_mana=10)),seed=665,generation_context=h.context),h.registry)

    def ids(self,g,zone='board',player=1):return[g.state.entities[i].card_id for i in getattr(g.state.players[player],zone)]
    def hero(self,g,player=1):return g.state.entities[g.state.players[player].hero_id]
    def finish(self,g):
        for _ in range(40):
            if g.state.pending_choice is None:return
            self.choose(g)
        self.fail('Unbounded original destruction notices')

    def test_complete_full_raw_union_native_pins_and_one_real_native_card(self):
        d=native.load_batch();h=host();native.checked_native(h.registry,d)
        self.assertEqual(len(d['full_union_records']),174);self.assertEqual(len(d['merged_member_ids']),86)
        self.assertEqual(d['merged_member_ids'][:-1],d['original_member_ids'])
        for row in d['cards']+d['existing_dependencies']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            self.assertEqual(canonical_digest(asdict(h.registry.card(row['record']['id']))),row['definition_sha256'])
        c=h.registry.card(TSC);self.assertEqual((c.cost,c.kind,c.spell_school.value),(8,CardType.SPELL,'nature'))
        self.assertFalse(d['new_standard_roots']);self.assertFalse(d['membership_uses_executable_coverage'])
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_complete_priest_and_five_independently_empty_candidate_views(self):
        h=host();d=native.load_batch();p=h.registry.pool(NATURE_PAST_POOL,h.context)
        self.assertEqual(p.members[:86],tuple(PoolMember(cid)for cid in d['merged_member_ids']))
        from hs_sim.cards.past_rogue_nature_source import ROOTS
        self.assertEqual(p.members[86:],tuple(PoolMember(cid)for cid in ROOTS))
        for view in d['views']:
            values=resolve_candidates(h.registry,h.context,p.id,QUERIES[WO],current_class=CardClass(view['current_class']),
                source_card_id=WO,exclude_source_by_rule=True)
            self.assertEqual([v.card_id for v in values],view['actual_ids'])
            self.assertEqual([v.weight for v in values],[1]*len(values))

    def test_source_rejects_cropping_reordering_reweighting_and_borrowed_version(self):
        h=host();p=h.registry.pool(NATURE_PAST_POOL,h.context)
        class Proxy:
            def __getattr__(self,key):return getattr(h.registry,key)
            def pool(self,*args):return self.changed
        for patch in ({'members':p.members[:-1]},{'members':tuple(reversed(p.members))},
                {'members':(replace(p.members[0],weight=2),)+p.members[1:]},
                {'version':'borrowed'},{'complete':False},{'target_id':'other-context'}):
            with self.subTest(patch=tuple(patch)):
                q=Proxy();q.changed=replace(p,**patch)
                from hs_sim.cards.past_rogue_nature_source import local_pool
                with self.assertRaises(TargetValidationError):native.register_scopes(q,h.context,reviewed_pool=local_pool(h.registry,h.context))

    def test_late_native_member_failure_registers_no_partial_scopes(self):
        h=host();calls=[]
        class Proxy:
            def __getattr__(self,key):return getattr(h.registry,key)
            def card(self,cid):return replace(h.registry.card(cid),cost=9)if cid==TSC else h.registry.card(cid)
            def register_generation_scope(self,v):calls.append(v)
        with self.assertRaises(TargetValidationError):native.register_scopes(Proxy(),h.context)
        self.assertEqual(calls,[])

    def test_real_paid_spell_destroys_both_boards_and_all_existing_hand_deck_copies(self):
        g=self.game((TSC,A,B),board=(A,),enemy=(B,),other_hand=(A,B,'card.3'),deck=(A,B,'card.1'),other_deck=(B,A,'card.2'))
        targets={e.id for e in g.state.entities.values()if e.card_id in(A,B)}
        board=set(g.state.players[1].board+g.state.players[2].board);rng=g.snapshot()['rng_state']
        self.play(g,TSC)
        self.assertEqual(g.state.players[1].mana,2);self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in targets))
        self.assertEqual({d.entity_id for d in g.state.death_history},board)
        notices=[e for e in g.events if e.kind in('card_destroyed_in_hand','card_destroyed_in_deck')]
        self.assertEqual({e.target_id for e in notices},targets-board)
        self.assertEqual(self.ids(g,'hand',2),['card.3']);self.assertEqual(self.ids(g,'deck'),['card.1'])
        self.assertFalse(any(e.kind in('card_discarded','card_drawn','damage','healed')for e in g.events))
        self.portable(g)

    def test_changed_stats_and_generated_discounted_copies_still_match_same_identity(self):
        g=self.game((PREP,TSC,A),board=(A,));self.play(g,PREP)
        copies=[g.state.entities[i]for p in (1,2)for z in ('hand','deck')for i in getattr(g.state.players[p],z)
            if g.state.entities[i].card_id==A]
        self.assertEqual(len(copies),3);self.assertEqual(sum(c.cost==0 for c in copies),2)
        self.assertEqual(self.entity(g,A,zone='board').attack,5)
        self.play(g,TSC);self.assertTrue(all(g.state.entities[c.id].zone==Zone.GRAVEYARD for c in copies));self.portable(g)

    def test_current_transformed_identity_is_used_without_matching_same_printed_name(self):
        g=self.game((CHANGE,TSC,A,A),board=(A,),deck=(A,B));self.play(g,CHANGE)
        self.assertEqual(self.ids(g),[B]);self.play(g,TSC)
        self.assertEqual(self.ids(g,'hand'),[A]);self.assertEqual(self.ids(g,'deck'),[A]);self.portable(g)

    def test_dormant_and_location_carriers_are_not_seeds_or_ordinary_board_victims(self):
        g=self.game((TSC,DORMANT,LOCATION),board=(A,DORMANT,LOCATION),deck=(DORMANT,LOCATION,A))
        sleeping=self.entity(g,DORMANT,zone='board').id;location=self.entity(g,LOCATION,zone='board').id
        self.play(g,TSC);self.assertEqual(self.ids(g),[DORMANT,LOCATION])
        self.assertIsNotNone(g.state.entities[sleeping].dormancy);self.assertEqual(g.state.entities[location].durability,2)
        self.assertEqual(self.ids(g,'hand'),[DORMANT,LOCATION]);self.assertEqual(self.ids(g,'deck'),[DORMANT,LOCATION]);self.portable(g)

    def test_no_active_minion_does_not_destroy_stored_cards_or_consume_rng(self):
        g=self.game((TSC,A,DORMANT),board=(DORMANT,LOCATION),deck=(A,DORMANT));rng=g.snapshot()['rng_state']
        self.play(g,TSC);self.assertEqual(self.ids(g,'hand'),[A,DORMANT]);self.assertEqual(self.ids(g,'deck'),[A,DORMANT])
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertFalse(g.state.death_history)
        self.assertFalse(any(e.kind.startswith('card_destroyed_in_')for e in g.events))

    def test_native_stored_bodies_are_not_discards_deaths_and_new_rattle_copies_survive(self):
        g=self.game((TSC,RATTLE),board=(RATTLE,),other_hand=(RATTLE,),deck=(RATTLE,),other_deck=(RATTLE,))
        stored={e.id for e in g.state.entities.values()if e.card_id==RATTLE and e.zone in(Zone.HAND,Zone.DECK)}
        old=self.entity(g,RATTLE,zone='board').id;self.play(g,TSC)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in stored))
        self.assertEqual([d.entity_id for d in g.state.death_history],[old])
        self.assertEqual((self.hero(g).armor,self.hero(g,2).armor),(4,4))
        self.assertEqual(self.ids(g),[RATTLE]);self.assertNotEqual(self.entity(g,RATTLE,zone='board').id,old)
        self.assertEqual(self.ids(g,'hand'),[RATTLE]);self.assertEqual(self.ids(g,'deck'),[RATTLE]);self.portable(g)

    def test_reborn_occurs_once_after_the_original_batch_and_survives(self):
        g=self.game((TSC,REBORN),board=(REBORN,),deck=(REBORN,))
        old=self.entity(g,REBORN,zone='board').id;self.play(g,TSC)
        self.assertEqual([d.entity_id for d in g.state.death_history],[old])
        self.assertEqual(self.ids(g),[REBORN]);self.assertNotEqual(self.entity(g,REBORN,zone='board').id,old)
        self.assertEqual(self.entity(g,REBORN,zone='board').health,1)
        self.assertEqual(self.ids(g,'hand'),[]);self.assertEqual(self.ids(g,'deck'),[]);self.portable(g)

    def test_all_stored_departures_commit_before_waiting_reactions(self):
        g=self.game((TSC,A),board=(A,),enemy=(A,),other_hand=(A,),deck=(A,),other_deck=(A,),watch=True)
        targets={e.id for e in g.state.entities.values()if e.card_id==A};self.play(g,TSC)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD or
            (g.state.entities[i].zone==Zone.BOARD and g.state.entities[i].doomed)for i in targets))
        self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.finish(g);self.portable(g)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in targets))
        self.assertEqual(len([e for e in g.events if e.kind.startswith('card_destroyed_in_')]),4)

    def test_both_new_effects_roundtrip_in_real_pending_choices_and_resume(self):
        for branch in ('batch','copies'):
            with self.subTest(branch=branch):
                g=self.game((QUEUE,A),board=(A,),deck=(A,));self.play(g,QUEUE);self.portable(g)
                saved=deepcopy(g.snapshot())
                with self.assertRaises(ResolutionError):self.choose(g,'source')
                self.assertEqual(g.snapshot(),saved);self.choose(g,branch)
                self.assertEqual(self.ids(g,'hand'),[]);self.assertEqual(self.ids(g,'deck'),[])
                self.assertEqual(self.ids(g),[A]if branch=='batch'else[]);self.portable(g)

    def test_general_stored_batch_skips_departed_residence_and_changed_face(self):
        g=self.game((STALE,A),deck=(A,));self.play(g,STALE)
        self.assertEqual(self.ids(g,'deck'),[B,A]);self.assertFalse(any(e.kind.startswith('card_destroyed_in_')for e in g.events))
        self.portable(g)

    def test_shared_request_shape_and_codec_reject_duplicate_mutable_or_invalid_source(self):
        g=self.game((A,),deck=(A,));ref=CardReference.capture(self.entity(g,A))
        for thunk in (lambda:DestroyStoredBatch((ref,ref)),lambda:DestroyStoredBatch([ref]),
                lambda:DestroyStoredBatch((ref,),reveal=1),lambda:DestroyMinionCopies(True),lambda:DestroyMinionCopies(-1)):
            with self.assertRaises(ValueError):thunk()
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        for effect in (DestroyStoredBatch((ref,),g.state.players[1].hero_id),DestroyMinionCopies(g.state.players[1].hero_id)):
            self.assertEqual(codec.decode(codec.encode(effect)),effect)

    def test_whole_physical_budget_failure_rolls_back_payment_zones_notices_and_rng(self):
        g=self.game((TSC,A),board=(A,),enemy=(A,),other_hand=(A,),deck=(A,)*30,other_deck=(A,)*30,
            rules=Ruleset(max_resolution_steps=50));saved=deepcopy(g.snapshot())
        with self.assertRaisesRegex(ResolutionError,'physical batch budget'):self.play(g,TSC)
        self.assertEqual(g.snapshot(),saved)

    def test_revealed_destroyed_copies_do_not_expose_unmatched_enemy_cards_or_internal_pools(self):
        g=self.game((TSC,),board=(A,),other_hand=(A,'card.3'),other_deck=(A,'card.4'))
        self.assertNotIn('card.3',json.dumps(g.for_player(1).observe()))
        self.play(g,TSC);view=json.dumps(g.for_player(1).observe())
        self.assertIn(A,view);self.assertNotIn('card.3',view);self.assertNotIn('card.4',view)
        for forbidden in ('full_union_records','resolution_frame','original_card','rng_state',NATURE_PAST_POOL):
            self.assertNotIn(forbidden,view)

    def test_actual_wo_discovers_full_priest_view_generated_whirlpool_pays_and_clears_source(self):
        g=self.actual();self.play(g,'CORE_EX1_169');self.assertIsNotNone(g.state.pending_choice)
        q=g.state.pending_choice;self.assertEqual({o.card_id for o in q.options},{'DEEP_026',TSC})
        self.assertNotIn(TSC,json.dumps(g.for_player(2).observe()));self.portable(g)
        self.choose(g,next(o.id for o in q.options if o.card_id==TSC))
        self.assertNotIn(TSC,json.dumps(g.for_player(2).observe()))
        source=self.entity(g,WO,zone='board').id;mana=g.state.players[1].mana;self.play(g,TSC)
        self.assertEqual(g.state.players[1].mana,mana-8);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_all_five_verified_empty_classes_use_real_wo_entry_without_rng_or_choice(self):
        for hero in ('HERO_11','HERO_10','HERO_08','HERO_04','HERO_07'):
            with self.subTest(hero=hero):
                g=self.actual(hero);rng=g.snapshot()['rng_state'];self.play(g,'CORE_EX1_169')
                self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],rng)
                self.assertEqual(self.ids(g,'hand'),[]);self.assertEqual(self.ids(g),[WO])
                if hero=='HERO_08':self.portable(g)

    def test_nonempty_unreviewed_shaman_cannot_fall_back_to_implemented_subset(self):
        g=self.actual('HERO_02');saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.play(g,'CORE_EX1_169')
        self.assertEqual(g.snapshot(),saved)


if __name__=='__main__':unittest.main()
