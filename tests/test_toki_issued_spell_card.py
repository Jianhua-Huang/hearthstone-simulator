"""Actual Toki's issued physical spell sets; formal historical pool is separate."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.toki_issued_spell_card import CARD,POOL_ID,SPEC,load_batch
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,IllegalAction,PlayCard,PlayerSetup,
    ResolutionError,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.effects import AddToHand,ChoiceOption,Destroy,InvokeBehavior,RequestChoice
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.issued_spell_sets import matching_plays
from hs_sim.engine.model import BattlecryRepeatSpec
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference,CopyCard

P='fixture.issued.';UNIT=P+'unit';WATCH=P+'watch';REPEAT=P+'repeat';SPELL='CS2_024'
CONTEXT=GenerationContext('explicit-toki-experiment','experimental')


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r=build_registry();meta=replace(r.card('CORE_EX1_012').metadata,collectible=False,tribes=())
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,attack=1,health=9,metadata=meta))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=30,metadata=meta,battlecry_repeats=(BattlecryRepeatSpec(2,(CardType.MINION,)),)))
    def fail(c):raise ResolutionError('Issued spell set reaction fixture failure')
    r.register_behavior(P+'fail',fail)
    def copy(c):return(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,source_id=c.source_id),)
    def transform(c):return(TransformStoredCard(CardReference.capture(c.state.entities[c.target_id]),UNIT,c.source_id),)
    for key,body in(('copy',copy),('transform',transform)):
        r.register_behavior(P+key,body);r.register_card(CardDefinition(P+key,P+key,CardType.SPELL,on_play=P+key,
            targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.SPELL,))))
    r.register_behavior(P+'kill',lambda c:(Destroy(c.target_id,c.source_id),))
    r.register_card(CardDefinition(P+'kill',P+'kill',CardType.SPELL,on_play=P+'kill',requires_target=True))
    r.register_behavior(P+'cast',lambda c:(CastSpell(c.player_id,SPELL,c.source_id,target_id=c.state.players[3-c.player_id].hero_id,targeting='explicit'),))
    r.register_card(CardDefinition(P+'cast',P+'cast',CardType.SPELL,on_play=P+'cast'))
    def watch(c):
        event=c.event
        if mode=='fail_birth' and event.kind=='card_added_to_hand' and c.state.entities[event.target_id].card_id==SPELL:
            return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if mode=='fill_reward' and event.kind=='card_played':
            pid=event.player_id
            for e in c.state.players[pid].player_effects:
                plan=e.issued_spell_set
                if plan is not None and matching_plays(c.state,plan,dict(event.data)['play_id']):
                    return tuple(AddToHand(pid,UNIT,c.source_id)for _ in range(10-len(c.state.players[pid].hand)))
        wait=(mode=='wait_birth'and event.kind=='card_added_to_hand' and c.state.entities[event.target_id].card_id==SPELL or
            mode=='wait_consumed'and event.kind=='player_effect_removed' and dict(event.data).get('effect_key')==SPEC)
        if wait:return(RequestChoice(event.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',
            (InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=meta,
        triggers=tuple(TriggerSpec(k,P+'watch')for k in('card_added_to_hand','card_played','player_effect_removed'))))
    if mode!='missing':
        members=(PoolMember(SPELL),)
        if mode=='unknown':
            from hs_sim.engine.pools import PoolCard
            r.register_pool_card(replace(r.pool_card(SPELL),card_id=P+'unknown'));members=(*members,PoolMember(P+'unknown'))
        if mode=='empty':members=()
        r.register_pool(PoolDefinition(POOL_ID,'explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,members,complete=mode!='incomplete'))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')});return s


class TokiIssuedTests(unittest.TestCase):
    def game(self,hand=(CARD,),mode='normal',active=1,repeat=False):
        ps=[]
        for p in(1,2):
            watching=(p==active and mode=='fill_reward'or p!=active and mode in('wait_birth','wait_consumed','fail_birth'))
            board=((REPEAT,)if p==active and repeat else())+((WATCH,)if watching else())
            ps.append(PlayerSetup('HERO_08',hand=hand if p==active else('EX1_287',),deck=(UNIT,)*10,board=board,max_mana=10,mana=10))
        return Game.from_scenario(Scenario(tuple(ps),active_player=active,seed=317,generation_context=CONTEXT),fixture(mode))
    def play(self,g,cid=CARD,target=None,eid=None):
        p=g.state.active_player
        if eid is None:eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid,target));return eid
    def programs(self,g,p=None):
        p=g.state.active_player if p is None else p
        return[e for e in g.state.players[p].player_effects if e.issued_spell_set is not None]
    def frost(self,g,eid):return self.play(g,target=g.state.players[3-g.state.active_player].hero_id,eid=eid)
    def members(self,g,index=0):return[a.entity_id for a in self.programs(g)[index].issued_spell_set.allocations]
    def tokens(self,g,p=None):
        p=g.state.active_player if p is None else p
        return[i for i in g.state.players[p].hand if g.state.entities[i].card_id==CARD]
    def portable(self,g,mode='normal',fresh=False):
        s=g.snapshot();r=fixture.__wrapped__(mode)if fresh else fixture(mode)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),r).snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),r).snapshot(),s);return s
    def turns(self,g):
        p=g.state.active_player;g.apply(EndTurn(p));g.apply(EndTurn(3-p))

    def test_full_source_three_face_ten_primary_faces_and_stale_enchantment_are_distinct(self):
        d=load_batch();self.assertEqual(len(d['official_observations']),10);self.assertEqual(len(d['evidence_only']),2)
        self.assertIn('4',d['evidence_only'][0]['record']['text_en']);self.assertIn('ALL 3',d['cards'][0]['record']['text_en'])
        r=build_registry();self.assertEqual((r.card(CARD).cost,r.card(CARD).attack,r.card(CARD).health),(3,3,3))
        self.assertFalse(any(k[0]==POOL_ID for k in r.pools));self.assertNotIn(CARD+'e1',r.cards)

    def test_three_identical_faces_are_distinct_physical_members_and_reward_once_after_all(self):
        g=self.game();self.play(g);ids=self.members(g);self.assertEqual(len(set(ids)),3)
        self.assertEqual(self.programs(g)[0].issued_spell_set.selected,(SPELL,)*3);self.assertEqual(g.state.players[1].mana,7)
        self.portable(g,fresh=True)
        for eid in ids[:2]:self.frost(g,eid);self.assertFalse(self.tokens(g))
        self.frost(g,ids[2]);self.assertEqual(len(self.tokens(g)),1);self.assertFalse(self.programs(g))
        self.assertEqual(g.state.players[1].mana,1);self.assertEqual(sum(e.kind=='issued_spell_set_reward_delivered'for e in g.events),1);self.portable(g)

    def test_completion_persists_across_turns_and_original_toki_death(self):
        g=self.game(hand=(CARD,P+'kill'));root=self.play(g);ids=self.members(g);self.play(g,P+'kill',root)
        self.frost(g,ids[0]);self.turns(g)
        for eid in ids[1:]:self.frost(g,eid)
        self.assertEqual(g.state.entities[root].zone,Zone.GRAVEYARD);self.assertEqual(len(self.tokens(g)),1);self.portable(g)

    def test_raw_casts_do_not_substitute_for_playing_original_members(self):
        g=self.game(hand=(CARD,P+'cast',P+'cast',P+'cast'));self.play(g)
        for _ in range(3):self.play(g,P+'cast')
        self.assertFalse(self.tokens(g));self.assertEqual(len(self.programs(g)),1)
        for eid in self.members(g):self.frost(g,eid)
        self.assertEqual(len(self.tokens(g)),1);self.portable(g)

    def test_same_named_and_current_copied_cards_do_not_replace_originals_under_local_policy(self):
        g=self.game(hand=(CARD,SPELL,P+'copy'));old=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==SPELL)
        self.play(g);ids=self.members(g);self.play(g,P+'copy',ids[0]);copy=next(i for i in g.state.players[1].hand if i not in ids and i!=old and g.state.entities[i].card_id==SPELL)
        self.frost(g,old);self.frost(g,copy);self.assertFalse(self.tokens(g));self.turns(g)
        for eid in ids:self.frost(g,eid)
        self.assertEqual(len(self.tokens(g)),1);self.portable(g)

    def test_transformed_minion_is_not_a_spell_play_as_required_by_official_fix(self):
        g=self.game(hand=(CARD,P+'transform'));self.play(g);ids=self.members(g);self.play(g,P+'transform',ids[0])
        self.play(g,eid=ids[0])
        for eid in ids[1:]:self.frost(g,eid)
        self.assertFalse(self.tokens(g));self.assertEqual(g.state.play_history[-3].kind,CardType.MINION);self.portable(g)

    def test_countered_original_is_still_a_completed_physical_spell_play(self):
        g=self.game();self.play(g);ids=self.members(g);self.frost(g,ids[0]);self.frost(g,ids[1])
        g.apply(EndTurn(1));self.play(g,'EX1_287');g.apply(EndTurn(2));self.frost(g,ids[2])
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(len(self.tokens(g)),1);self.portable(g)

    def test_repeated_battlecry_has_two_independent_sets_and_each_returns_one_toki(self):
        g=self.game(repeat=True);self.play(g);self.assertEqual(len(self.programs(g)),2);first=self.members(g,0);second=self.members(g,1)
        self.assertFalse(set(first)&set(second))
        for eid in first:self.frost(g,eid)
        self.assertEqual(len(self.tokens(g)),1);self.assertEqual(len(self.programs(g)),1);self.turns(g)
        for eid in second:self.frost(g,eid)
        self.assertEqual(len(self.tokens(g)),2);self.assertFalse(self.programs(g));self.portable(g)

    def test_each_physical_birth_can_suspend_without_losing_next_member(self):
        g=self.game(mode='wait_birth');self.play(g)
        for i in range(3):
            self.assertEqual(len(self.programs(g)[0].issued_spell_set.allocations),i+1);self.portable(g,'wait_birth',fresh=i==0)
            q=g.state.pending_choice;g.apply(SelectChoice(1,q.id,('ok',)))
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(self.members(g)),3);self.portable(g,'wait_birth')

    def test_consumption_wait_keeps_exact_reward_and_failed_selection_rolls_back(self):
        g=self.game(mode='wait_consumed');self.play(g);ids=self.members(g)
        for eid in ids:self.frost(g,eid)
        self.assertFalse(self.programs(g));self.assertFalse(self.tokens(g));saved=self.portable(g,'wait_consumed',fresh=True);q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,q.id,('bad',)))
        self.assertEqual(g.snapshot(),saved);g.apply(SelectChoice(1,q.id,('ok',)));self.assertEqual(len(self.tokens(g)),1);self.portable(g,'wait_consumed')

    def test_initial_overflow_records_all_actual_members_without_replacing_burned_cards(self):
        g=self.game(hand=(CARD,)+(UNIT,)*9);self.play(g);facts=self.programs(g)[0].issued_spell_set.allocations
        self.assertEqual([f.zone for f in facts],[Zone.HAND,Zone.GRAVEYARD,Zone.GRAVEYARD]);self.frost(g,facts[0].entity_id)
        self.assertFalse(self.tokens(g));self.assertEqual(len(self.programs(g)),1);self.portable(g)

    def test_accepted_reward_uses_ordinary_full_hand_overflow(self):
        g=self.game(mode='fill_reward');self.play(g);ids=self.members(g)
        for eid in ids:self.frost(g,eid)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertFalse(self.tokens(g));self.assertFalse(self.programs(g))
        burns=[e for e in g.events if e.kind=='card_burned'];self.assertTrue(any(g.state.entities[e.target_id].card_id==CARD for e in burns));self.portable(g,'fill_reward')

    def test_second_player_owns_generated_set_and_returned_toki(self):
        g=self.game(active=2);self.play(g)
        for eid in self.members(g):self.frost(g,eid)
        self.assertEqual(len(self.tokens(g,2)),1);self.assertFalse(self.tokens(g,1));self.portable(g)

    def test_missing_incomplete_and_unknown_qualified_pool_restore_exact_action(self):
        for mode in('missing','incomplete','unknown'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);saved=g.snapshot()
                with self.assertRaises((ValueError,ResolutionError)):self.play(g)
                self.assertEqual(g.snapshot(),saved)

    def test_empty_domain_creates_neither_spells_nor_a_fake_completed_program(self):
        g=self.game(mode='empty');n=len(g.state.entities);self.play(g);self.assertEqual(len(g.state.entities),n)
        self.assertFalse(self.programs(g));self.assertFalse(self.tokens(g));self.portable(g,'empty')

    def test_birth_reaction_failure_rolls_back_sampling_program_and_payment(self):
        g=self.game(mode='fail_birth');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),saved)

    def test_rehashed_group_candidates_allocations_and_rng_are_bound_to_original_acceptance(self):
        g=self.game();self.play(g);saved=g.snapshot()
        for field in('selected','allocations','rng_after'):
            with self.subTest(field=field):
                bad=deepcopy(saved);plan=next(e['issued_spell_set']for e in bad['state']['players']['1']['player_effects']if e['issued_spell_set']is not None)
                if field=='selected':plan[field][0]='EX1_279'
                elif field=='allocations':plan[field][0]['entity_id']=plan[field][1]['entity_id']
                else:plan[field]=plan['rng_before']
                with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture())

    def test_rehashed_snapshot_cannot_drop_the_whole_original_program(self):
        g=self.game();self.play(g);bad=g.snapshot()
        bad['state']['players']['1']['player_effects']=[e for e in bad['state']['players']['1']['player_effects']if e['issued_spell_set']is None]
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture())

    def test_native_program_candidates_rng_and_invisible_effect_are_not_player_data(self):
        g=self.game();self.play(g);saved=g.snapshot()
        for p in(1,2):
            view=json.dumps(g.for_player(p).observe())
            for hidden in('issued_spell_set','issued_spell_member','rng_before','acceptance_event',SPEC):self.assertNotIn(hidden,view)
        self.assertEqual(g.snapshot(),saved);self.portable(g)


if __name__=='__main__':unittest.main()
