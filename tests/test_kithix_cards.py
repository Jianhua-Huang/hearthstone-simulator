"""Kithix's real gate, three original Rituals and exact pool-delivery followups."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from hs_sim.cards.kithix_cards import CARD, RITUALS, P, load_batch, register_kithix_cards
from hs_sim.cards.ritual_cards import DRAW as BASIC, register_ritual_cards
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, Destroy,
    InvokeBehavior, RequestChoice, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_history import EVENT as HAND_ENTERED
from hs_sim.engine.model import CardClass, CardMetadata, PlayerEffectSpec, Rarity, SummonQuantitySpec
from hs_sim.engine.pools import (GenerationContext, PoolCard, PoolDefinition, PoolMember,
    PoolQuery, SummonFromPool)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.rituals import completed_rituals
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonCause
from tools.card_batch import canonical, check_face

F='fixture.kithix.'
PLAIN,LEG1,LEG2,DOUBLE,WATCH,RAWPOOL,UNKNOWN=(F+x for x in
    ('plain','legend_one','legend_two','double','watch','raw_pool','unknown'))
CTX=GenerationContext('fixture-kithix','experimental')
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
LEG_META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.LEGENDARY,tribes=())


@lru_cache(maxsize=None)
def fixture(mode=None,role='writer'):
    if role not in('writer','reader'):raise ValueError('Independent registry role required')
    r=build_registry();register_ritual_cards(r);register_kithix_cards(r)
    r.register_card(CardDefinition(PLAIN,PLAIN,CardType.MINION,cost=1,attack=1,health=6,metadata=META))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=12,metadata=META,
        summon_quantities=(SummonQuantitySpec(2,(CardType.MINION,)),)))
    for cid,a,h in((LEG1,2,4),(LEG2,4,7)):
        c=CardDefinition(cid,cid,CardType.MINION,cost=5,attack=a,health=h,metadata=LEG_META)
        r.register_card(c);r.register_pool_card(PoolCard.from_definition(c))
    members=(LEG1,LEG2)
    if mode=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,5,LEG_META,attack=2));members=(LEG1,UNKNOWN)
    r.register_pool(PoolDefinition('constructed.cards','fixture-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in members),complete=True))
    def fail(c):raise ResolutionError('Kithix deliberate late failure')
    r.register_behavior(F+'fail',fail)
    r.register_behavior(F+'live_copy',lambda c:(AddToHand(c.player_id,c.state.entities[c.target_id].card_id,c.source_id),))
    r.register_behavior(RAWPOOL,lambda c:(SummonFromPool(c.player_id,'constructed.cards',source_id=c.source_id,
        cause=SummonCause.capture(c),on_summon=F+'live_copy'),))
    r.register_card(CardDefinition(RAWPOOL,RAWPOOL,CardType.SPELL,on_play=RAWPOOL))
    if mode and mode!='unknown':
        def watch(c):
            target=c.state.entities.get(c.event.target_id)
            if target is None or target.card_id not in(LEG1,LEG2):return()
            if mode=='kill':return(Destroy(target.id,c.source_id),)
            if mode=='transform':return(Transform(target.id,PLAIN),)
            if mode=='give':return(ChangeControl(target.id,2),)
            if mode=='buff':return(Buff(target.id,5,5,c.source_id),)
            if mode=='fail':return(InvokeBehavior(F+'fail',c.source_id,c.player_id),)
            return(RequestChoice(3-c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(F+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(F+'watch',watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=12,metadata=META,
            triggers=(TriggerSpec(HAND_ENTERED if mode=='wait_hand'else'minion_summoned',F+'watch'),)))
    return r


class KithixCardTests(unittest.TestCase):
    def game(self,mode=None,*,hand=(BASIC,CARD),board=(),enemy_deck=(PLAIN,)*30,seat=1):
        self.mode=mode;self.seat=seat
        own=PlayerSetup('HERO_08',hand=hand,deck=(PLAIN,)*30,
            board=((WATCH,)if mode and mode!='unknown'else())+board,mana=10,max_mana=10)
        other=PlayerSetup('HERO_01',deck=enemy_deck,board=(PLAIN,),mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,
            generation_context=CTX,seed=369),fixture(mode))
    def play(self,g,cid=CARD):
        i=next(i for i in g.state.players[self.seat].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(self.seat,i));return i
    def end(self,g,n=1):
        for _ in range(n):g.apply(EndTurn(g.state.active_player))
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def ready(self,mode=None,**kwargs):
        g=self.game(mode,**kwargs);self.play(g,BASIC);self.end(g,4);return g
    def start(self,g,ritual):
        source=self.play(g);self.assertIsNotNone(g.state.pending_choice);self.choose(g,ritual);return source
    def legs(self,g):return[e for e in g.state.entities.values()if e.card_id in(LEG1,LEG2)and e.zone==Zone.BOARD]
    def copies(self,g):return[g.state.entities[i]for i in g.state.players[self.seat].hand
        if g.state.entities[i].card_id in(LEG1,LEG2)]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=fixture(self.mode,'reader')
        for other in(g.clone(),Game.from_snapshot(s,r),replay(build_replay(g),r)):
            self.assertTrue(other.snapshot()==s,'Original choice, ritual, physical draws and delivery copies must restore')
        return Game.from_snapshot(s,r)
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()
            if k not in('schema_version','events','events_hash','state_hash')});return s

    def test_complete_root_three_rituals_and_eight_primary_faces_keep_evidence_rows(self):
        d=load_batch();rows={x['record']['id']:x for x in d['cards']+d['dependencies']}
        self.assertEqual(len(d['official_observations']),8)
        for row in d['cards']+d['dependencies']+d['evidence_only']:
            self.assertEqual(canonical(row['record']),row['record_sha256'])
        for o in d['official_observations']:
            check_face(rows[o['card_id']]['record'],o['face'],o['locale'],{'@':''}if o['card_id']!=CARD else None)
        self.assertEqual((fixture().card(CARD).cost,fixture().card(CARD).attack,fixture().card(CARD).health),(6,6,6))
        for cid in RITUALS:self.assertTrue(fixture().card(cid).choice_only)

    def test_no_completed_ritual_means_paid_six_six_without_choice_or_program(self):
        g=self.game(hand=(CARD,));source=self.play(g);self.assertIsNone(g.state.pending_choice)
        self.assertEqual((g.state.entities[source].attack,g.state.players[1].mana),(6,4));self.portable(g)

    def test_active_but_unfinished_ritual_does_not_satisfy_real_completion_gate(self):
        g=self.game();self.play(g,BASIC);self.play(g);self.assertIsNone(g.state.pending_choice)
        self.assertEqual(completed_rituals(g.state,1),());self.portable(g)

    def test_genuine_completion_offers_all_three_original_nonphysical_choices(self):
        g=self.ready();self.play(g);q=g.state.pending_choice
        self.assertEqual(tuple(o.id for o in q.options),RITUALS)
        self.assertEqual(tuple(o.card_id for o in q.options),RITUALS);self.portable(g)

    def test_choice_restores_and_starts_exact_instance_without_cast_or_extra_payment(self):
        g=self.ready();source=self.play(g);before=g.state;other=self.portable(g)
        self.choose(g,RITUALS[0]);self.choose(other,RITUALS[0]);self.assertTrue(g.snapshot()==other.snapshot())
        instance=next(e for e in g.state.players[1].player_effects if e.spec_id==P+RITUALS[0])
        self.assertEqual((instance.source_id,instance.remaining_turns),(source,2))
        self.assertEqual(g.state.players[1].mana,4);self.assertEqual(g.state.cast_history,before.cast_history);self.portable(g)

    def test_famine_draws_five_original_enemy_deck_entities_to_actor(self):
        g=self.ready();self.start(g,RITUALS[0]);self.end(g,3);ids=tuple(g.state.players[2].deck[:5]);self.end(g)
        self.assertTrue(set(ids)<=set(g.state.players[1].hand));self.assertTrue(set(ids).isdisjoint(g.state.players[2].deck))
        self.assertTrue(all(g.state.entities[i].controller==1 for i in ids))
        self.assertEqual(len(completed_rituals(g.state,1)),2);self.portable(g)

    def test_famine_empty_enemy_deck_uses_actor_fatigue_and_keeps_actor_deck_draw(self):
        g=self.ready(enemy_deck=());self.start(g,RITUALS[0]);self.end(g,4)
        self.assertEqual(g.state.players[1].fatigue,5);self.assertEqual(len(completed_rituals(g.state,1)),2);self.portable(g)

    def test_dominance_three_real_deliveries_get_matching_one_cost_base_face_copies(self):
        g=self.ready();self.start(g,RITUALS[1]);self.end(g,4)
        self.assertEqual(len(self.legs(g)),3);copies=self.copies(g);self.assertEqual(len(copies),3)
        self.assertEqual([e.card_id for e in self.legs(g)],[e.card_id for e in copies])
        self.assertEqual([local_cost(e)[0]for e in copies],[1,1,1]);self.portable(g)

    def test_original_deliveries_still_get_original_faces_after_death_transform_or_transfer(self):
        for mode in('kill','transform','give'):
            with self.subTest(mode=mode):
                g=self.ready(mode);self.start(g,RITUALS[1]);self.end(g,4)
                self.assertEqual(len(self.copies(g)),3);self.assertTrue(all(local_cost(e)[0]==1 for e in self.copies(g)));self.portable(g)

    def test_entry_buff_does_not_bake_into_explicit_original_face_copy_policy(self):
        g=self.ready('buff');self.start(g,RITUALS[1]);self.end(g,4)
        self.assertTrue(all(e.attack in(7,9)for e in self.legs(g)))
        self.assertTrue(all(e.attack in(2,4)for e in self.copies(g)));self.portable(g)

    def test_quantity_extras_each_keep_exact_original_main_delivery_copy(self):
        g=self.ready(board=(DOUBLE,));self.start(g,RITUALS[1]);self.end(g,4)
        self.assertEqual(len(self.legs(g)),5);self.assertEqual(len(self.copies(g)),5);self.portable(g)

    def test_full_board_has_no_actual_delivery_copy_or_rng(self):
        g=self.ready(board=(PLAIN,)*6);self.start(g,RITUALS[1]);self.end(g,3);rng=g._rng.getstate();self.end(g)
        self.assertFalse(self.legs(g));self.assertFalse(self.copies(g));self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_conquest_buffs_only_current_own_minions_in_hand_deck_and_board(self):
        g=self.ready(board=(PLAIN,));source=self.start(g,RITUALS[2]);self.end(g,4)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(12,12))
        own=g.state.players[1]
        for i in(*own.hand,*own.deck,*own.board):
            e=g.state.entities[i]
            if e.card_id==PLAIN:self.assertEqual((e.attack,e.health),(7,12))
        e=g.state.entities[g.state.players[2].board[0]];self.assertEqual((e.attack,e.health),(1,6));self.portable(g)

    def test_original_delivery_entry_wait_restores_then_creates_each_copy_once(self):
        g=self.ready('wait');self.start(g,RITUALS[1]);self.end(g,4)
        self.assertEqual(len(self.legs(g)),1);self.assertFalse(self.copies(g));other=self.portable(g)
        self.choose(g,'ok');self.choose(other,'ok');self.assertTrue(g.snapshot()==other.snapshot())
        while g.state.pending_choice:self.choose(g,'ok')
        self.assertEqual(len(self.copies(g)),3);self.portable(g)

    def test_copy_hand_entry_wait_keeps_already_accepted_followup_marker(self):
        g=self.ready('wait_hand');self.start(g,RITUALS[1]);self.end(g,4)
        self.assertEqual(len(self.copies(g)),1);other=self.portable(g)
        self.choose(g,'ok');self.choose(other,'ok');self.assertTrue(g.snapshot()==other.snapshot())
        while g.state.pending_choice:self.choose(g,'ok')
        self.assertEqual(len(self.copies(g)),3);self.portable(g)

    def test_failed_entry_and_selection_roll_back_original_clock_fact_rng_and_copy_work(self):
        g=self.ready('fail');self.start(g,RITUALS[1]);self.end(g,3);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.end(g)
        self.assertTrue(g.snapshot()==before)
        g=self.ready('wait');self.start(g,RITUALS[1]);self.end(g,4);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertTrue(g.snapshot()==before)

    def test_unknown_eligible_legendary_is_not_removed_or_replaced_by_whiteboard(self):
        g=self.ready('unknown');self.start(g,RITUALS[1]);self.end(g,3);before=g.snapshot()
        with self.assertRaises((ResolutionError,UnsupportedDefinitionError,ValueError)):self.end(g)
        self.assertTrue(g.snapshot()==before)

    def test_old_live_friendly_followup_still_skips_dead_original(self):
        g=self.game('kill',hand=(RAWPOOL,));self.play(g,RAWPOOL);self.assertFalse(self.copies(g));self.portable(g)

    def test_changed_saved_delivery_policy_cannot_borrow_old_accepted_root(self):
        g=self.ready('wait');self.start(g,RITUALS[1]);self.end(g,4);s=deepcopy(g.snapshot())
        def change(value):
            if isinstance(value,dict):
                if value.get('followup_policy')=='original_delivery':value['followup_policy']='live_friendly';return True
                for child in value.values():
                    if change(child):return True
            elif isinstance(value,list):
                for child in value:
                    if change(child):return True
            return False
        self.assertTrue(change(s['state']))
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),fixture(self.mode))

    def test_invalid_followup_modes_or_missing_callback_are_rejected(self):
        for kw in(dict(followup_policy='bad'),dict(followup_policy=True),dict(followup_policy='original_delivery')):
            with self.assertRaises(ValueError):SummonFromPool(1,'constructed.cards',**kw)

    def test_choice_only_display_exception_is_limited_to_real_ritual_spells(self):
        for kind,program in((CardType.MINION,'ritual'),(CardType.SPELL,'persistent')):
            with self.subTest(kind=kind,program=program):
                r=build_registry();cid=F+'display'
                with self.assertRaises(ValueError):
                    r.register_card(CardDefinition(cid,cid,kind,choice_only=True,
                        health=1 if kind==CardType.MINION else 0))
                    r.register_behavior(F+'expire',lambda c:())
                    kw=dict(duration=2,tick_event='turn_started',on_expire=F+'expire')if program=='ritual'else{}
                    r.register_player_effect(PlayerEffectSpec(F+'program',cid,kind=program,**kw))
                    r.freeze()

    def test_second_seat_choice_and_both_player_dtos_hide_original_pool_basis(self):
        g=self.ready('wait',seat=2);self.start(g,RITUALS[1]);self.end(g,4);before=g.snapshot()
        for pid in(1,2):
            text=json.dumps(g.for_player(pid).observe());g.for_player(pid).legal_actions()
            for key in('pool_basis','followup_policy','PoolSummonBasis','card_summon_history'):
                self.assertNotIn(key,text)
        self.assertTrue(g.snapshot()==before);self.portable(g)
