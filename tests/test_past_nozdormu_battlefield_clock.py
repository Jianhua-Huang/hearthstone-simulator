"""Actual live clock sources, ordinary lifecycle and shared host continuations."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import past_nozdormu_battlefield_clock as native
from hs_sim.cards.nozdormu_turn_clock_card import CARD as ETERNAL,register_nozdormu_turn_clock_card
from hs_sim.engine import (DeckPolicy,DeckSpec,EndTurn,Game,IllegalAction,MatchSetup,PlayerSetup,
    ResolutionError,Scenario,SelectChoice,SnapshotError)
from hs_sim.engine.battlefield_turn_clocks import BattlefieldTurnClockProfile,POLICY,sources,validate_profile
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,GainArmor,
    InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.model import CardClass,CardDefinition,CardType,Keyword,RewindSpec,TargetSpec,Zone
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.turn_clocks import AdvanceTurnTime,ADVANCE,INSTALL,KINDS,TIMEOUT,current,history_action_to_dict
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

CARD=native.CARD;P='k691.';A=P+'plain';KILL=P+'kill';HUSH=P+'hush';OUT=P+'out';TAKE=P+'take'
COPY=P+'copy';MUTATE=P+'mutate';SLEEP=P+'sleep';ASK=P+'ask';OTHER=P+'other';CHAIN=P+'chain'
BROKEN=P+'broken';FAIL=P+'fail';REMOVE=P+'remove';EXTRA=P+'extra';SKIP=P+'skip';REWIND=P+'rewind';SPAWN=P+'spawn'


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=opening_registry();register_nozdormu_turn_clock_card(r);native.register_past_nozdormu_battlefield_clock(r)
    r.register_card(CardDefinition(A,A,CardType.MINION,attack=1,health=40,metadata=metadata(collectible=False)))
    def ask(c,pid,after=()):
        return(RequestChoice(pid,(ChoiceOption('a','A',(GainArmor(pid,1),)+after),
            ChoiceOption('b','B',(GainArmor(pid,2),)+after)),c.source_id),)
    def chain(c):
        return ask(c,c.player_id,(RequestChoice(3-c.player_id,(ChoiceOption('continue','Continue'),),c.source_id),))
    def remove(c):
        target=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD)
        return(RequestChoice(c.player_id,(ChoiceOption('remove','Remove last clock',(Destroy(target,c.source_id),)),),c.source_id),)
    scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),
        OUT:lambda c:(ReturnToHand(c.target_id),),TAKE:lambda c:(ChangeControl(c.target_id,c.player_id),),
        COPY:lambda c:(CopyMinion(c.target_id,c.player_id,cause=SummonCause.capture(c)),),
        MUTATE:lambda c:(Transform(c.target_id,A),),SLEEP:lambda c:(MakeDormant(c.target_id,1,c.source_id),),
        ASK:lambda c:ask(c,c.player_id),OTHER:lambda c:ask(c,3-c.player_id),CHAIN:chain,REMOVE:remove,
        BROKEN:lambda c:(RequestChoice(c.player_id,(ChoiceOption('fault','Fault',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))),),c.source_id),),
        EXTRA:lambda c:(QueueTurns((c.player_id,),c.source_id),),SKIP:lambda c:(SkipTurns(3-c.player_id,source_id=c.source_id),),
        REWIND:lambda c:(GainArmor(c.player_id,c.rewind_attempt+1),),
        SPAWN:lambda c:(Summon(c.player_id,CARD,c.source_id),AddToHand(c.player_id,KILL,source_id=c.source_id))}
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K691 deliberate host timeout rollback')))
    for cid,body in scripts.items():
        r.register_behavior(cid,body);kw=dict(keywords=(Keyword.REWIND,),rewind=RewindSpec(2))if cid==REWIND else{}
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid in(KILL,HUSH,OUT,TAKE,COPY,MUTATE,SLEEP)else None,
            metadata=metadata(collectible=cid==SPAWN),**kw))
    r.validate();return r


class PastNozdormuBattlefieldClockTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))
    def game(self,hand=(),*,board=(),enemy=(),player=1,seed=691):
        self.mode='small'
        return Game.from_scenario(Scenario(tuple(PlayerSetup('mage.hero',hand=hand if p==player else(),
            board=board if p==player else enemy,deck=(A,)*12,mana=20,max_mana=20,mana_cap=20)for p in(1,2)),
            active_player=player,seed=seed),fixture('writer'))
    def unit(self,g,cid=CARD,p=1):return self.entity(g,cid,p,'board')
    def tick(self,g,ms):g.apply(AdvanceTurnTime(current(g)['owner_turn_id'],ms))
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def reject(self,snapshot):
        snapshot['events_hash']=canonical_hash(snapshot['events'])
        if 'turn_clock'in snapshot:snapshot['turn_clock']['events']=[deepcopy(e)for e in snapshot['events']if e['kind']in KINDS]
        snapshot['state_hash']=canonical_hash({k:v for k,v in snapshot.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as error:Game.from_snapshot(snapshot,fixture('independent-reader'))
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_complete_actual_nine_mana_face_primary_roles_and_full_original_domain(self):
        d=native.load_batch();r=fixture();card=r.card(CARD)
        self.assertEqual((card.cost,card.attack,card.health),(9,8,8));self.assertEqual(len(d['official_observations']),8)
        self.assertEqual(len(d['original_candidate_ids']),732);self.assertEqual(canonical_digest(asdict(card)),d['cards'][0]['definition_sha256'])
        self.assertNotEqual(card,r.card(ETERNAL));self.assertEqual(r._turn_clock_profiles[CARD].policy,POLICY)

    def test_profile_rejects_wrong_source_limit_policy_or_missing_native_marker(self):
        for kw in(dict(source_card_id=ETERNAL),dict(limit_ms=15001),dict(limit_ms=True),dict(policy='invented')):
            with self.assertRaises(ValueError):replace(BattlefieldTurnClockProfile(CARD,native.BEHAVIOR),**kw)
        r=opening_registry();r.register_card(CardDefinition(CARD,'Wrong blank',CardType.MINION,health=8))
        with self.assertRaises(ValueError):validate_profile(r,BattlefieldTurnClockProfile(CARD,native.BEHAVIOR))

    def test_hand_deck_or_eternal_board_alone_cannot_impose_live_clock(self):
        g=self.game((CARD,),board=(ETERNAL,));self.assertIsNone(current(g));before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(AdvanceTurnTime(1,1))
        self.assertEqual(g.snapshot(),before);self.assertNotIn('turn_clock',g.snapshot())

    def test_actual_paid_nozdormu_immediately_arms_current_turn_without_opening(self):
        g=self.game((CARD,));self.assertIsNone(current(g));source=self.play(g,CARD)
        self.assertEqual(g.state.players[1].mana,11);self.assertEqual(current(g)['remaining_ms'],15000)
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.assertFalse(any(e.kind==INSTALL for e in g.events))
        self.assertEqual(g.snapshot()['turn_clock']['policy'],POLICY);self.portable(g)

    def test_initial_board_source_arms_both_players_actual_intervals(self):
        g=self.game(board=(CARD,));self.tick(g,4000);self.assertEqual(current(g)['remaining_ms'],11000)
        token=current(g)['owner_turn_id'];self.end(g);self.assertEqual(current(g)['remaining_ms'],15000)
        self.assertEqual(current(g)['player_id'],2);self.assertNotEqual(current(g)['owner_turn_id'],token)

    def test_partial_host_time_preserves_rng_action_and_full_source_material(self):
        g=self.game(board=(CARD,));rng=g._rng.getstate();action=g.state.action_number;self.tick(g,1234)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.action_number,action)
        event=next(e for e in g.events if e.kind==ADVANCE);rows=json.loads(dict(event.data)['battlefield_sources'])
        self.assertEqual(rows[0]['allocation']['entity_id'],self.unit(g).id);self.assertEqual(rows[0]['ability']['behavior_id'],native.BEHAVIOR)
        self.assertEqual(current(g)['remaining_ms'],13766);self.portable(g)

    def test_exact_expiry_ordinary_end_once_and_overflow_never_charges_new_turn(self):
        g=self.game(board=(CARD,));self.tick(g,40000)
        self.assertEqual(g.state.active_player,2);self.assertEqual(sum(e.kind=='turn_ended'for e in g.events),1)
        self.assertEqual(current(g)['remaining_ms'],15000);self.assertEqual(next(e.amount for e in g.events if e.kind==ADVANCE),15000)

    def test_each_source_retirement_revokes_last_cap_without_erasing_elapsed_receipt(self):
        for spell in(HUSH,KILL,OUT,MUTATE):
            g=self.game((spell,),board=(CARD,));self.tick(g,3500);self.play(g,spell,self.unit(g).id)
            self.assertIsNone(current(g));self.assertEqual(sum(e.amount for e in g.events if e.kind==ADVANCE),3500)
            before=g.snapshot()
            with self.assertRaises(IllegalAction):g.apply(AdvanceTurnTime(1,1))
            self.assertEqual(g.snapshot(),before)

    def test_bounce_reentry_keeps_original_interval_elapsed_instead_of_reset(self):
        g=self.game((OUT,),board=(CARD,));source=self.unit(g).id;self.tick(g,8000);self.play(g,OUT,source)
        self.assertIsNone(current(g));self.play(g,CARD)
        self.assertEqual(current(g)['remaining_ms'],7000);self.tick(g,7000);self.assertEqual(g.state.active_player,2);self.portable(g)

    def test_multiple_both_side_sources_share_one_cap_and_retire_independently(self):
        g=self.game((HUSH,KILL),board=(CARD,),enemy=(CARD,));self.tick(g,3000)
        self.assertEqual(len(sources(g)),2);self.play(g,HUSH,self.unit(g).id);self.assertEqual(len(sources(g)),1)
        self.assertEqual(current(g)['remaining_ms'],12000);self.play(g,KILL,self.unit(g,p=2).id);self.assertIsNone(current(g))

    def test_actual_current_copy_keeps_rule_after_original_is_silenced(self):
        g=self.game((COPY,HUSH),board=(CARD,));original=self.unit(g).id;self.tick(g,2000);self.play(g,COPY,original)
        self.assertEqual(len(sources(g)),2);self.play(g,HUSH,original);self.assertEqual(len(sources(g)),1)
        self.assertEqual(current(g)['remaining_ms'],13000);self.tick(g,1000);self.portable(g)

    def test_copy_of_silenced_source_does_not_regain_printed_clock(self):
        g=self.game((HUSH,COPY),board=(CARD,));original=self.unit(g).id;self.play(g,HUSH,original);self.play(g,COPY,original)
        self.assertEqual(sources(g),());self.assertIsNone(current(g))

    def test_control_change_preserves_global_cap_and_captures_current_controller(self):
        g=self.game((TAKE,),enemy=(CARD,));source=self.unit(g,p=2).id;self.tick(g,3000);self.play(g,TAKE,source)
        self.assertEqual(current(g)['remaining_ms'],12000);self.assertEqual(sources(g)[0]['allocation']['controller'],1)
        self.tick(g,1000);self.portable(g)

    def test_dormancy_temporarily_removes_source_and_awakening_restores_rule(self):
        g=self.game((SLEEP,),board=(CARD,));self.play(g,SLEEP,self.unit(g).id);self.assertIsNone(current(g))
        self.end(g);self.assertIsNone(current(g));self.end(g);self.assertIsNotNone(current(g))

    def test_actual_extra_turn_and_skipped_enemy_slot_receive_fresh_owner_budget(self):
        for spell in(EXTRA,SKIP):
            g=self.game((spell,),board=(CARD,));self.play(g,spell);old=current(g)['owner_turn_id'];self.tick(g,15000)
            self.assertEqual(g.state.active_player,1);self.assertNotEqual(current(g)['owner_turn_id'],old)
            self.assertEqual(current(g)['remaining_ms'],15000)

    def test_timeout_resumes_actual_paid_choice_without_repayment_then_natural_end(self):
        g=self.game((ASK,),board=(CARD,));self.play(g,ASK);before=g.state.players[1].mana;self.tick(g,15000)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.active_player,2);self.assertEqual(g.state.players[1].mana,before)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(sum(e.kind==TIMEOUT for e in g.events),1);self.portable(g)

    def test_partial_time_waiting_choice_restores_and_manual_selection_keeps_remaining(self):
        g=self.game((ASK,),board=(CARD,));self.play(g,ASK);self.tick(g,4000);g=self.portable(g);self.choose(g,'a')
        self.assertEqual(current(g)['remaining_ms'],11000);self.portable(g)

    def test_opponent_choice_pauses_host_input_without_consuming_rng_or_time(self):
        g=self.game((OTHER,),board=(CARD,));self.play(g,OTHER);self.assertTrue(current(g)['paused']);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.tick(g,1000)
        self.assertEqual(g.snapshot(),before);self.choose(g,'a');self.assertEqual(current(g)['remaining_ms'],15000)

    def test_expired_active_continuation_waits_for_actual_opponent_then_ends_old_turn(self):
        g=self.game((CHAIN,),board=(CARD,));self.play(g,CHAIN);self.tick(g,15000)
        self.assertEqual(g.state.pending_choice.player_id,2);self.assertEqual(current(g)['remaining_ms'],0);g=self.portable(g)
        self.choose(g);self.assertEqual(g.state.active_player,2);self.assertEqual(current(g)['remaining_ms'],15000)

    def test_expired_work_removing_last_provider_releases_cap_by_explicit_local_policy(self):
        g=self.game((REMOVE,),board=(CARD,));self.play(g,REMOVE);self.tick(g,15000)
        self.assertIsNone(current(g));self.assertEqual(g.state.active_player,1);self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_timeout_failure_rolls_back_time_random_choice_and_actual_history(self):
        g=self.game((BROKEN,),board=(CARD,));self.play(g,BROKEN);before=g.snapshot();history=g.history
        with self.assertRaises(ResolutionError):self.tick(g,15000)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.history,history)

    def test_rewind_keeps_charged_time_and_live_provider_across_original_retry(self):
        g=self.game((REWIND,),board=(CARD,));self.play(g,REWIND);self.tick(g,6000);self.choose(g,'retry')
        self.assertEqual(current(g)['remaining_ms'],9000);self.tick(g,9000)
        self.assertEqual(g.state.active_player,2);self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_original_both_decks_clock_survives_live_source_silence_and_shares_elapsed(self):
        self.mode='small';r=fixture('writer');cards=(ETERNAL,)+(SPAWN,)*7
        decks=tuple(DeckSpec('mage.hero','mage.power',CardClass.MAGE,cards)for _ in(1,2))
        policy=DeckPolicy('k691.clock','k691.target','experimental',tuple(r.cards),deck_size=8,max_copies=8,legendary_copies=1)
        g=Game.from_decks(MatchSetup(decks,policy,'coin',691,1),r)
        while g.state.pending_choice is not None:
            c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,()))
        self.tick(g,2000);self.play(g,SPAWN);self.tick(g,3000);self.play(g,KILL,self.unit(g).id)
        self.assertEqual(current(g)['remaining_ms'],10000);self.assertEqual(sum(e.kind==INSTALL for e in g.events),1)
        self.tick(g,1000);self.assertEqual(dict([e for e in g.events if e.kind==ADVANCE][-1].data)['policy'],'original-decks-turn-time-v1')
        self.portable(g)

    def test_rehashed_source_profile_ability_allocation_empty_or_duplicate_receipts_reject(self):
        g=self.game(board=(CARD,));self.tick(g,1000);saved=g.snapshot();index=next(i for i,e in enumerate(saved['events'])if e['kind']==ADVANCE)
        mutations=(lambda rows:[],lambda rows:rows+rows,lambda rows:[dict(rows[0],profile_id=ETERNAL)],
            lambda rows:[dict(rows[0],ability=dict(rows[0]['ability'],behavior_id='unknown.clock'))],
            lambda rows:[dict(rows[0],allocation=dict(rows[0]['allocation'],next_entity_id=999999))])
        for mutation in mutations:
            bad=deepcopy(saved);rows=json.loads(bad['events'][index]['data']['battlefield_sources'])
            bad['events'][index]['data']['battlefield_sources']=json.dumps(mutation(rows));self.reject(bad)
        bad=deepcopy(saved);del bad['turn_clock'];self.reject(bad)

    def test_rehashed_time_interval_amount_and_policy_cannot_borrow_other_clock(self):
        g=self.game(board=(CARD,));self.tick(g,1000);saved=g.snapshot();index=next(i for i,e in enumerate(saved['events'])if e['kind']==ADVANCE)
        for key,value in(('owner_turn_id',2),('previous_ms',3),('policy','original-decks-turn-time-v1')):
            bad=deepcopy(saved);bad['events'][index]['data'][key]=value;self.reject(bad)

    def test_public_players_see_clock_values_without_private_source_time_or_rng_receipts(self):
        g=self.game(board=(CARD,));self.tick(g,2000)
        for pid in(1,2):
            port=g.for_player(pid);view=port.observe();self.assertEqual(view['observation']['turn_clock']['remaining_ms'],13000)
            text=json.dumps((view,port.events()))
            for word in('battlefield_sources','next_attachment_id','rng_before','turn_time_advanced','owner_turn_id'):self.assertNotIn(word,text)
            before=g.snapshot();result=port.submit(dict(revision=view['revision'],action=history_action_to_dict(AdvanceTurnTime(1,1))))
            self.assertFalse(result['accepted']);self.assertEqual(g.snapshot(),before)

    def test_standard_host_actual_nine_mana_entry_and_timed_natural_end_restore(self):
        self.mode='host';h=host('writer')
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(CARD,),deck=('CORE_CS2_182',)*8,
            mana=20,max_mana=20,mana_cap=20),PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*8)),generation_context=h.context,seed=691),h.registry)
        self.play(g,CARD);self.assertEqual(g.state.players[1].mana,11);self.tick(g,15000)
        self.assertEqual(g.state.active_player,2);self.assertEqual(current(g)['remaining_ms'],15000);self.portable(g)
