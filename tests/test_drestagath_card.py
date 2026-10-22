"""Native tutor checks and honest missing Yogg; generic fallback contract tests."""
from dataclasses import asdict
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from hs_sim.cards.drestagath_card import (CARD,GODS,POOL,POLICY,QUERY,load_batch,
    register_drestagath_card)
from hs_sim.cards.empire_cthun_cards import register_empire_cthun_cards
from hs_sim.cards.nzoth_card import register_nzoth_card
from hs_sim.cards.yshaarj_card import register_yshaarj_card
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,
    Registry,Scenario,SelectChoice,SnapshotError,TriggerSpec)
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Destroy,InvokeBehavior,
    RequestChoice,Silence,TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass,CardMetadata,Keyword,Rarity,TargetSpec,Zone
from hs_sim.engine.pools import (GenerateFromPool,GenerationContext,PoolCard,PoolDefinition,
    PoolMember,PoolQuery,resolve_candidates)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face

P='fixture.drestagath.'
HERO,UNIT,ZERO,KILL,MUTE,GIVE,TRIGGER,WATCH,GENERIC,PREWAIT,A,B=(P+x for x in
    ('hero','unit','zero','kill','mute','give','trigger','watch','generic','prewait','a','b'))
GEN_POOL=P+'pool'
GEN_QUERY=PoolQuery(card_ids=(A,B))
META=CardMetadata(True,(CardClass.ROGUE,),Rarity.COMMON,tribes=())


@lru_cache(maxsize=None)
def registry(mode='normal',role='writer'):
    assert role in ('writer','reader')
    r=Registry('drestagath-'+mode)
    for register in (register_empire_cthun_cards,register_nzoth_card,register_yshaarj_card,
            register_drestagath_card):register(r)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,
        metadata=CardMetadata(False,(CardClass.ROGUE,),Rarity.NONE,tribes=())))
    for cid in (UNIT,A,B):
        definition=CardDefinition(cid,cid,CardType.MINION,attack=1,health=3,metadata=META)
        r.register_card(definition);r.register_pool_card(PoolCard.from_definition(definition))
    r.register_pool(PoolDefinition(GEN_POOL,'fixture-v1','local-2026-09-23','experimental',
        (PoolMember(A),PoolMember(B))))
    def fail(c):raise ResolutionError('Deliberate empty-tutor continuation failure')
    r.register_behavior(P+'fail',fail)
    def choice(c):return RequestChoice(3-c.player_id,(ChoiceOption('ok','Continue'),
        ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id)
    def generic(c):
        fallback=(GenerateFromPool(c.player_id,GEN_POOL,source_id=c.source_id),)
        if mode=='fallback-wait':fallback=(choice(c),*fallback)
        if mode=='fallback-fail':fallback=(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        return (DrawMatching(c.player_id,GEN_QUERY,'skip',source_id=c.source_id,on_empty=fallback),)
    r.register_behavior(GENERIC,generic)
    operations={ZERO:lambda c:(),KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        MUTE:lambda c:(Silence(c.target_id),),GIVE:lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        TRIGGER:lambda c:(TriggerDeathrattles(c.target_id,c.source_id,times=2),),
        GENERIC:generic,PREWAIT:lambda c:(choice(c),*generic(c))}
    for cid,body in operations.items():
        if cid!=GENERIC:r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid in (KILL,MUTE,GIVE,TRIGGER)else None))
    if mode=='draw-wait':
        def watch(c):
            if c.event.player_id!=c.player_id:return ()
            return (choice(c),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=3,metadata=META,
            triggers=(TriggerSpec('card_drawn',WATCH),)))
    r.validate();r.freeze();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
    return s


class DrestagathTests(unittest.TestCase):
    def game(self,hand=(KILL,),board=(CARD,),deck=(UNIT,'BE_013'),enemy_hand=(),enemy_deck=(UNIT,)*10,mode='normal'):
        self.mode=mode
        if mode=='draw-wait':board=(*board,WATCH)
        return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=deck,
            mana=50,max_mana=50,mana_cap=50),PlayerSetup(HERO,hand=enemy_hand,deck=enemy_deck,
            mana=50,max_mana=50,mana_cap=50)),seed=387,
            generation_context=GenerationContext('local-2026-09-23','experimental')),registry(mode))
    def source(self,g):return next(i for i in g.state.players[1].board if g.state.entities[i].card_id==CARD)
    def play(self,g,cid=KILL,target=None):
        pid=g.state.active_player;e=next(g.state.entities[i]for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
    def select(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        reader=registry(self.mode,'reader');self.assertIsNot(reader,g.registry)
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,reader)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return other

    def test_complete_five_original_rows_two_primary_faces_and_three_unchanged_dependencies(self):
        data=load_batch();self.assertEqual(data['official_faces_verified'],2)
        self.assertEqual(data['pending_executable_dependencies'],['BE_009'])
        for face in data['official_observations']:check_face(data['cards'][0]['record'],face['face'],face['locale'])
        for row in data['existing_dependencies']:
            self.assertEqual(canonical_digest(asdict(registry().card(row['record']['id']))),row['definition_sha256'])

    def test_fixed_four_god_inventory_includes_missing_yogg_without_executable_blank(self):
        r=registry();pool=r.pool(POOL,GenerationContext('local-2026-09-23','experimental'))
        self.assertEqual(tuple(x.card_id for x in pool.members),GODS)
        self.assertNotIn('BE_009',r.cards);self.assertIn(Keyword.OLD_GOD,r.pool_card('BE_009').keywords)
        self.assertFalse(pool.complete)

    def test_real_four_mana_six_four_play_does_not_run_deathrattle(self):
        g=self.game(hand=(CARD,),board=());eid=self.play(g,CARD)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health,g.state.players[1].mana),(6,4,46))
        self.assertFalse(g.state.draw_history)

    def test_actual_death_draws_original_physical_old_god_not_deck_top(self):
        g=self.game();target=self.source(g);old=g.state.players[1].deck[-1];self.play(g,KILL,target)
        self.assertIn(old,g.state.players[1].hand);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].deck),1);self.assertEqual(g.state.draw_history[-1].entity_id,old)
        self.portable(g)

    def test_all_three_existing_native_old_gods_are_physical_cross_class_matches(self):
        for cid in GODS[1:]:
            g=self.game(deck=(UNIT,cid));eid=g.state.players[1].deck[-1];self.play(g,KILL,self.source(g))
            self.assertIn(eid,g.state.players[1].hand)

    def test_full_hand_burn_is_an_actual_match_and_does_not_enter_missing_yogg_fallback(self):
        g=self.game(hand=(ZERO,)*10,enemy_hand=(KILL,));target=self.source(g);old=g.state.players[1].deck[-1]
        g.apply(EndTurn(1));self.play(g,KILL,target)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.draw_history[-1].entity_id,old);self.portable(g)

    def test_current_controller_receives_own_deck_match_after_control_change(self):
        g=self.game(hand=(GIVE,KILL),enemy_deck=(UNIT,'BE_784'));target=self.source(g)
        expected=g.state.players[2].deck[-1];self.play(g,GIVE,target);self.play(g,KILL,target)
        self.assertIn(expected,g.state.players[2].hand);self.assertEqual(len(g.state.players[1].deck),2);self.portable(g)

    def test_silenced_source_has_no_tutor_or_missing_fallback(self):
        g=self.game(hand=(MUTE,KILL),deck=(UNIT,));target=self.source(g)
        self.play(g,MUTE,target);self.play(g,KILL,target);self.assertFalse(g.state.draw_history)

    def test_repeated_native_deathrattles_requery_each_actual_physical_match(self):
        g=self.game(hand=(TRIGGER,),deck=('BE_013','BE_017'));target=self.source(g)
        expected=set(g.state.players[1].deck);self.play(g,TRIGGER,target)
        self.assertEqual(set(g.state.players[1].hand),expected);self.assertEqual(len(g.state.draw_history),2)
        self.assertEqual(g.state.entities[target].zone,Zone.BOARD);self.portable(g)

    def test_native_no_match_reports_real_yogg_gap_and_rolls_back_entire_death(self):
        g=self.game(deck=(UNIT,));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'BE_009'):self.play(g,KILL,self.source(g))
        self.assertEqual(g.snapshot(),before)

    def test_ordinary_generation_excludes_old_gods_but_explicit_policy_checks_all_four(self):
        r=registry();context=GenerationContext('local-2026-09-23','experimental')
        self.assertEqual(resolve_candidates(r,context,POOL,QUERY),())
        with self.assertRaisesRegex(ValueError,'BE_009'):
            resolve_candidates(r,context,POOL,QUERY,policy=POLICY)

    def test_native_actual_draw_reaction_wait_keeps_original_source_after_death(self):
        g=self.game(mode='draw-wait');self.play(g,KILL,self.source(g));self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g)
        for match in (g,other):self.select(match)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.draw_history),1)

    def test_generic_empty_deck_fallback_generates_once_without_fatigue_or_draw_record(self):
        g=self.game(hand=(GENERIC,),board=(),deck=());self.play(g,GENERIC)
        self.assertEqual(len(g.state.players[1].hand),1);self.assertFalse(g.state.draw_history)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)
        self.assertIn(g.state.entities[g.state.players[1].hand[0]].card_id,(A,B));self.portable(g)

    def test_generic_no_match_in_nonempty_deck_preserves_unmatched_physical_cards(self):
        g=self.game(hand=(GENERIC,),board=(),deck=(UNIT,));before=tuple(g.state.players[1].deck);self.play(g,GENERIC)
        self.assertEqual(tuple(g.state.players[1].deck),before);self.assertEqual(len(g.state.players[1].hand),1)

    def test_generic_actual_match_prevents_generation_and_preserves_original_identity(self):
        g=self.game(hand=(GENERIC,),board=(),deck=(UNIT,A));expected=g.state.players[1].deck[-1]
        self.play(g,GENERIC);self.assertEqual(g.state.players[1].hand,[expected]);self.assertEqual(len(g.state.draw_history),1)

    def test_pending_request_preserves_new_empty_branch_through_json_clone_and_replay(self):
        g=self.game(hand=(PREWAIT,),board=(),deck=());self.play(g,PREWAIT)
        other=self.portable(g)
        for match in (g,other):self.select(match)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.players[1].hand),1)

    def test_generic_fallback_own_choice_restores_and_completes_once(self):
        g=self.game(hand=(GENERIC,),board=(),deck=(),mode='fallback-wait');self.play(g,GENERIC)
        self.assertFalse(g.state.players[1].hand);other=self.portable(g)
        for match in (g,other):self.select(match)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.players[1].hand),1)

    def test_immediate_fallback_failure_rolls_back_payment_action_and_rng(self):
        g=self.game(hand=(GENERIC,),board=(),deck=(),mode='fallback-fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,GENERIC)
        self.assertEqual(g.snapshot(),before)

    def test_failed_later_fallback_choice_keeps_accepted_pending_original_action(self):
        g=self.game(hand=(GENERIC,),board=(),deck=(),mode='fallback-wait');self.play(g,GENERIC);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g,'fail')
        self.assertEqual(g.snapshot(),before);self.select(g);self.assertEqual(len(g.state.players[1].hand),1)

    def test_empty_branch_rejects_mutable_untyped_repeated_and_fatigue_requests(self):
        for kw in ({'on_empty':[]},{'on_empty':('bad',)},{'on_empty':(Destroy(1),),'count':2},
                {'on_empty':(Destroy(1),),'count':0},{'on_empty':(Destroy(1),),'empty_deck':'fatigue'}):
            args=dict(player_id=1,query=PoolQuery(),empty_deck='skip');args.update(kw)
            with self.assertRaises(ValueError):DrawMatching(**args)

    def test_rehashed_pending_request_cannot_change_single_fallback_into_repeated_or_fatigue(self):
        g=self.game(hand=(PREWAIT,),board=(),deck=());self.play(g,PREWAIT);saved=g.snapshot()
        def mutate(value,field,new):
            if isinstance(value,dict):
                if value.get('type')=='hs_sim.engine.zones.DrawMatching':value['fields'][field]=new;return 1
                return sum(mutate(x,field,new)for x in value.values())
            if isinstance(value,list):return sum(mutate(x,field,new)for x in value)
            return 0
        for field,new in (('count',2),('empty_deck','fatigue')):
            bad=deepcopy(saved);self.assertGreater(mutate(bad,field,new),0)
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry(self.mode,'reader'))

    def test_player_projection_and_opaque_choice_hide_fallback_candidates_and_host_queue(self):
        g=self.game(hand=(PREWAIT,),board=(),deck=());self.play(g,PREWAIT)
        for pid in (1,2):
            visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for key in ('on_empty',GEN_POOL,POOL,'resolution_frame','rng_state'):
                self.assertNotIn(key,visible)
        port=g.for_player(2);commands=port.legal_actions();command=next(x for x in commands['actions']if x['type']=='select_choice')
        port.submit({'revision':commands['revision'],'action':command});self.assertEqual(len(g.state.players[1].hand),1)


if __name__=='__main__':unittest.main()
