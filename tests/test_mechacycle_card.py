"""Mechacycle's actual Deathrattle and original scoped printed-mana roots."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import random
import unittest

from hs_sim.cards.mechacycle_card import CARD, load_batch, register_mechacycle_card
from hs_sim.engine import (CardDefinition, CardType, Game, PlayCard, PlayerSetup, Ruleset,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, Destroy, InvokeBehavior,
    RequestChoice, Silence, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.mana_worth_summons import (ManaWorthEntryLink, SummonManaWorth, query,
    validate_link, validate_recipe)
from hs_sim.engine.model import (CardClass, CardMetadata, DeathrattleRepeatSpec, Keyword,
    Rarity, SummonQuantitySpec, TargetMode, TargetSpec)
from hs_sim.engine.pools import (GenerationContext, PoolCard, PoolDefinition, PoolMember,
    resolve_candidates, sample_candidates)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from tools.card_batch import canonical, check_face

P = 'fixture.mechacycle.'
PLAIN, M0, M1, M2, M3, M4, M5, ALL, DUAL, NON, TOKEN, UNKNOWN, KILL, LIVE, MUTE, GIVE, DOUBLE, REPEAT, WATCH = (
    P + x for x in ('plain','m0','m1','m2','m3','m4','m5','all','dual','non','token','unknown',
        'kill','live','mute','give','double','repeat','watch'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
CTX = GenerationContext('fixture-mechacycle', 'experimental')
DEFAULT = ((M2, 1), (NON, 10), (M5, 1), (TOKEN, 1))


@lru_cache(maxsize=None)
def registry(mode=None, members=DEFAULT, role='writer'):
    assert role in ('writer', 'reader')
    r = build_registry(); register_mechacycle_card(r)
    r.register_card(CardDefinition(PLAIN, PLAIN, CardType.MINION, health=12, metadata=META))
    rows = ((M0,0,('mech',),True),(M1,1,('mech',),True),(M2,2,('mech',),True),
        (M3,3,('mech',),True),(M4,4,('mech',),True),(M5,5,('mech',),True),
        (ALL,2,('all',),True),(DUAL,2,('beast','mech'),True),(NON,1,('beast',),True),
        (TOKEN,1,('mech',),False))
    for cid,cost,tribes,collectible in rows:
        meta = CardMetadata(collectible,(CardClass.NEUTRAL,),Rarity.COMMON if collectible else None,tribes=tribes)
        card = CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=4,metadata=meta)
        r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    if any(cid == UNKNOWN for cid,_ in members):
        tribes = ('beast',) if mode == 'unknown_nonmech' else ('mech',)
        r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,2,
            CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=tribes),attack=1))
    r.register_pool(PoolDefinition('constructed.cards','fixture-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid,weight) for cid,weight in members),complete=True))
    targeting = TargetSpec(TargetMode.REQUIRED,zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='any')
    bodies = {KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        LIVE:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        MUTE:lambda c:(Silence(c.target_id),), GIVE:lambda c:(ChangeControl(c.target_id,2),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=targeting,metadata=META))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=12,metadata=META,
        summon_quantities=(SummonQuantitySpec(),)))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=12,metadata=META,
        deathrattle_repeats=(DeathrattleRepeatSpec(),)))
    def fail(c): raise ResolutionError('Mechacycle deliberate late failure')
    r.register_behavior(P+'fail',fail)
    if mode in ('wait','fail','kill','nested','lethal'):
        def watch(c):
            if c.state.entities[c.event.target_id].card_id != M2: return ()
            if mode == 'kill': return (Destroy(c.event.target_id,c.source_id),)
            if mode == 'fail': return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode == 'lethal': return (Damage(c.state.players[3-c.player_id].hero_id,100,c.source_id),)
            if mode == 'nested':
                root = next(x for x in reversed(c.state.card_summon_history)
                    if type(x.request.producer_link) is ManaWorthEntryLink)
                return (SummonByCard(c.player_id,(SummonEntryMaterial(M1),),root.request.cause),)
            return (RequestChoice(3-c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=12,metadata=META,
            triggers=(TriggerSpec('minion_summoned',WATCH),)))
    return r


class MechacycleTests(unittest.TestCase):
    def game(self,mode=None,*,members=DEFAULT,board=(PLAIN,CARD,PLAIN),hand=(KILL,LIVE,MUTE,GIVE),seat=1,limit=7):
        self.config=(mode,members);self.seat=seat
        own=PlayerSetup('HERO_08',hand=hand,board=board+((WATCH,)if mode in('wait','fail','kill','nested','lethal')else()),
            deck=(PLAIN,)*2,mana=10,max_mana=10)
        other=PlayerSetup('HERO_01',deck=(PLAIN,)*2)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,
            generation_context=CTX,seed=370),registry(mode,members),ruleset=Ruleset(max_board=limit))
    def play(self,g,cid,target=None):
        source=next(i for i in g.state.players[self.seat].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(self.seat,source,target));return source
    def carrier(self,g):return next(e.id for e in g.state.entities.values()if e.card_id==CARD and e.zone==Zone.BOARD)
    def kill(self,g):return self.play(g,KILL,self.carrier(g))
    def roots(self,g):return [r for r in g.state.card_summon_history if type(r.request.producer_link)is ManaWorthEntryLink]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def finish(self,g):
        while g.state.pending_choice:self.choose(g)
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));r=registry(*self.config,'reader')
        self.assertIsNot(r,g.registry)
        for other in(g.clone(),Game.from_snapshot(saved,r),replay(build_replay(g),r)):
            self.assertTrue(other.snapshot()==saved,'Original scoped mana-budget roots must restore and replay')
        return Game.from_snapshot(saved,r)
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()
            if k not in('schema_version','events','events_hash','state_hash')});return s

    def test_complete_raw_and_both_primary_faces_keep_real_hunter_mech(self):
        d=load_batch();row=d['cards'][0];self.assertEqual(canonical(row['record']),row['record_sha256'])
        self.assertEqual(len(d['official_observations']),2)
        for o in d['official_observations']:check_face(row['record'],o['face'],o['locale'])
        c=registry().card(CARD);self.assertEqual((c.cost,c.attack,c.health),(4,3,3))
        self.assertEqual(c.keywords,(Keyword.TAUNT,));self.assertEqual(c.metadata.tribes,('mech',))

    def test_real_four_mana_hand_play_does_not_execute_deathrattle(self):
        g=self.game(board=(),hand=(CARD,KILL));source=self.play(g,CARD)
        self.assertEqual(g.state.players[1].mana,6);self.assertFalse(self.roots(g))
        self.play(g,KILL,source);self.assertEqual(len(self.roots(g)),2);self.portable(g)

    def test_natural_middle_death_uses_two_mech_picks_and_original_slots(self):
        g=self.game();left,source,right=g.state.players[1].board;self.kill(g);roots=self.roots(g)
        ids=[r.deliveries[0].entity.entity_id for r in roots]
        self.assertEqual(g.state.players[1].board,[left,*ids,right])
        self.assertEqual([r.request.producer_link.remaining for r in roots],[4,2])
        self.assertEqual([r.request.position for r in roots],[1,2])
        self.assertTrue(all(r.request.producer_link.tribe=='mech' and r.request.cause.source.entity_id==source for r in roots))
        self.assertTrue(all(tuple(m.card_id for m in r.request.pool_basis.candidates)==(M2,)for r in roots));self.portable(g)

    def test_live_trigger_uses_original_carrier_right_and_keeps_carrier(self):
        g=self.game();left,source,right=g.state.players[1].board;self.play(g,LIVE,source)
        ids=[r.deliveries[0].entity.entity_id for r in self.roots(g)]
        self.assertEqual(g.state.players[1].board,[left,source,*ids,right]);self.assertFalse(g.state.death_history)

    def test_full_live_board_skips_actual_delivery_and_rng(self):
        g=self.game(board=(PLAIN,CARD)+(PLAIN,)*5);rng=g._rng.getstate();self.play(g,LIVE,self.carrier(g))
        root,=self.roots(g);self.assertIsNone(root.selected);self.assertEqual(root.status,'skipped')
        self.assertEqual(g._rng.getstate(),rng)

    def test_natural_single_free_slot_keeps_spent_pick_and_empty_remaining_root(self):
        g=self.game(board=(PLAIN,CARD)+(PLAIN,)*5);self.kill(g);roots=self.roots(g)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(len(roots),2)
        self.assertEqual((roots[0].selected,roots[1].selected),(0,None))
        self.assertEqual(roots[1].rng_before,roots[1].rng_after)

    def test_empty_mech_domain_has_complete_empty_root_and_no_rng(self):
        g=self.game(members=((NON,1),(M5,1),(TOKEN,1)));rng=g._rng.getstate();self.kill(g)
        root,=self.roots(g);self.assertIsNone(root.selected);self.assertEqual(root.request.pool_basis.candidates,())
        self.assertEqual(g._rng.getstate(),rng)

    def test_zero_cost_mechs_keep_budget_and_stop_at_actual_board_capacity(self):
        g=self.game(members=((M0,1),),board=(CARD,),limit=3);self.kill(g);roots=self.roots(g)
        self.assertEqual(len(g.state.players[1].board),3);self.assertEqual(len(roots),4)
        self.assertTrue(all(r.request.producer_link.remaining==4 for r in roots))
        self.assertEqual([r.request.position for r in roots],[0,1,2,3]);self.assertIsNone(roots[-1].selected)
        self.assertEqual(roots[-1].rng_before,roots[-1].rng_after)

    def test_all_and_dual_tribes_are_mechs_and_uncollectible_or_over_budget_are_not(self):
        members=((ALL,1),(DUAL,1),(NON,9),(M5,1),(TOKEN,1));g=self.game(members=members);self.kill(g)
        for root in self.roots(g):
            self.assertEqual({m.card_id for m in root.request.pool_basis.candidates},{ALL,DUAL})

    def test_weighted_rng_and_printed_cost_are_reaccepted_for_each_remaining_budget(self):
        members=((M1,2),(M3,1),(NON,9));g=self.game(members=members);rng=random.Random();rng.setstate(g._rng.getstate())
        remaining=4;expected=[]
        while remaining:
            candidates=resolve_candidates(g.registry,CTX,'constructed.cards',query(remaining,'mech'),player_id=1,source_card_id=CARD)
            cid=sample_candidates(rng,candidates,1,replacement=True)[0];expected.append(cid)
            remaining-=g.registry.pool_card(cid).cost
        self.kill(g);actual=[r.request.materials[r.selected].card_id for r in self.roots(g)]
        self.assertEqual(actual,expected);self.assertEqual(g._rng.getstate(),rng.getstate())
        self.assertEqual(sum(g.registry.pool_card(cid).cost for cid in actual),4)

    def test_quantity_extras_charge_original_pick_once_and_advance_by_actual_deliveries(self):
        g=self.game(board=(PLAIN,CARD,PLAIN,DOUBLE));left,source,right,provider=g.state.players[1].board;self.kill(g)
        roots=self.roots(g);ids=[d.entity.entity_id for r in roots for d in r.deliveries]
        self.assertEqual(len(ids),4);self.assertEqual([r.request.position for r in roots],[1,3])
        self.assertEqual(g.state.players[1].board,[left,*ids,right,provider]);self.assertEqual([r.request.producer_link.remaining for r in roots],[4,2])

    def test_two_native_deathrattle_invocations_have_separate_original_budgets(self):
        g=self.game(board=(CARD,REPEAT));self.kill(g);roots=self.roots(g)
        self.assertEqual([r.request.producer_link.remaining for r in roots],[4,2,4,2])
        self.assertEqual(sum(r.request.producer_link.previous_root_id is None for r in roots),2);self.portable(g)

    def test_entry_death_does_not_refund_printed_mana(self):
        g=self.game('kill');self.kill(g);self.assertEqual(len(self.roots(g)),2)
        self.assertTrue(all(r.status=='completed' for r in self.roots(g)))
        self.assertFalse(any(g.state.entities[i].card_id==M2 for i in g.state.players[1].board))

    def test_terminal_entry_interrupts_actual_scoped_root_and_remaining_budget(self):
        g=self.game('lethal');self.kill(g);root,=self.roots(g)
        self.assertEqual(g.state.status,'finished');self.assertEqual(root.status,'interrupted')
        self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_same_cause_nested_summon_never_becomes_a_budget_entry(self):
        g=self.game('nested');self.kill(g);roots=self.roots(g)
        self.assertEqual(len(roots),2);self.assertEqual(len(g.state.card_summon_history),4)
        self.assertTrue(all(d.entity.card_id==M2 for r in roots for d in r.deliveries))
        self.assertEqual([r.request.position for r in roots],[1,2])

    def test_silenced_source_does_not_create_budget_or_consume_rng(self):
        g=self.game();self.play(g,MUTE,self.carrier(g));rng=g._rng.getstate();self.kill(g)
        self.assertFalse(self.roots(g));self.assertEqual(g._rng.getstate(),rng)

    def test_transferred_source_death_benefits_actual_controller(self):
        g=self.game();source=self.carrier(g);self.play(g,GIVE,source);self.play(g,KILL,source)
        self.assertTrue(all(r.request.player_id==2 and r.request.cause.player_id==2 for r in self.roots(g)))
        self.assertEqual(sum(g.state.entities[i].card_id==M2 for i in g.state.players[2].board),2)

    def test_wait_after_each_original_pick_restores_and_replays_without_resampling(self):
        g=self.game('wait');self.kill(g);self.assertEqual(g.state.pending_choice.player_id,2)
        other=self.portable(g);rng=g._rng.getstate();self.choose(g);self.choose(other)
        self.assertTrue(g.snapshot()==other.snapshot());self.assertNotEqual(g._rng.getstate(),rng)
        other=self.portable(g);self.finish(g);self.finish(other);self.assertTrue(g.snapshot()==other.snapshot());self.portable(g)

    def test_failed_entry_and_failed_pending_choice_preserve_transaction(self):
        g=self.game('fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.kill(g)
        self.assertTrue(g.snapshot()==saved)
        g=self.game('wait');self.kill(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertTrue(g.snapshot()==saved)

    def test_unknown_eligible_mech_errors_even_on_full_board_but_nonmech_is_not_eligible(self):
        for board in((CARD,),(CARD,)+(PLAIN,)*6):
            g=self.game(members=((UNKNOWN,1),),board=board);saved=g.snapshot()
            with self.assertRaises((ResolutionError,UnsupportedDefinitionError)):self.play(g,LIVE,self.carrier(g))
            self.assertTrue(g.snapshot()==saved)
        g=self.game('unknown_nonmech',members=((M2,1),(UNKNOWN,1)));self.kill(g)
        self.assertEqual(len(self.roots(g)),2)

    def test_scoped_link_and_position_cannot_change_between_original_roots(self):
        g=self.game('wait');self.kill(g);self.choose(g);root=self.roots(g)[-1]
        for field,value in(('tribe',None),('position',0)):
            with self.assertRaises(ValueError):
                link=replace(root.request.producer_link,**{field:value})
                basis=replace(root.request.pool_basis,query=query(link.remaining,link.tribe))
                request=replace(root.request,producer_link=link,pool_basis=basis,position=link.position)
                validate_link(g.state,g.registry,replace(root,request=request))
        self.finish(g)

    def test_codec_finite_scopes_and_rehashed_saved_link_reject_drift(self):
        g=self.game('wait');self.kill(g);root=self.roots(g)[0];link=root.request.producer_link
        codec=FrameCodec(g.mechanics,g.registry)
        for value in(link,SummonManaWorth(1,'constructed.cards',4,root.request.cause,'mech',1)):
            self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(value)))),value)
        for value in('dragon',True,[],1):
            with self.assertRaises(ValueError):replace(link,tribe=value)
        for value in(True,-1,'left'):
            with self.assertRaises(ValueError):replace(link,position=value)
        s=deepcopy(g.snapshot());s['state']['card_summon_history'][0]['request']['producer_link']['tribe']=None
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry(*self.config,'reader'))
        with self.assertRaises(ValueError):
            root_request=replace(root.request,pool_basis=replace(root.request.pool_basis,on_summon=P+'irrelevant'))
            validate_recipe(root_request)

    def test_second_seat_and_player_views_hide_original_budget_and_candidates(self):
        g=self.game('wait',seat=2);self.kill(g);before=g.snapshot()
        for pid in(1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            g.for_player(pid).legal_actions()
            for key in('producer_link','previous_root_id','pool_basis','rng_state'):
                self.assertNotIn('"'+key+'"',public)
        self.assertTrue(g.snapshot()==before);self.portable(g)
