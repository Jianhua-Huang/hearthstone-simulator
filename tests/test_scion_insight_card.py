"""Actual Scion discovery, ordinary Rune generation and original recipient boundaries."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.scion_insight_card import CARD, BODY, POOL, load_batch, register_scion_insight_card
from hs_sim.engine import (BattlecryRepeatSpec, CardDefinition, CardType, Game, PlayCard,
    PlayerSetup, Registry, Scenario, SelectChoice, SnapshotError, TriggerSpec)
from hs_sim.engine.card_conditions import UnknownCardFactError
from hs_sim.engine.card_discoveries import discovered_cards
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Destroy, GainArmor,
    InvokeBehavior, RequestChoice, ReturnToHand, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass, CardMetadata, ChoicePurpose, CostSpec, Keyword, Rarity, Runes, Zone
from hs_sim.engine.pool_offers import ChooseFromPools, PoolOfferGroup, ResolvePoolOffer
from hs_sim.engine.pools import (GenerateFromPool, GenerationContext, PoolCard, PoolDefinition,
    PoolMember, PoolQuery, matches_metadata, resolve_candidates)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from tools.card_batch import canonical, check_face

P='fixture.scion.'
HERO,B,F,U,BF,BU,FU,BB,BBB,BFU,NONE,UNKNOWN,MISSING,WATCH,REPEAT,NATURAL,GENERATE,NAMED=(
    P+n for n in ('hero','b','f','u','bf','bu','fu','bb','bbb','bfu','none','unknown','missing',
        'watch','repeat','natural','generate','named'))
CONTEXT=GenerationContext('scion-explicit-fixture','experimental')
META=CardMetadata(True,(CardClass.DEATH_KNIGHT,),Rarity.COMMON,runes=Runes(),tribes=())


@lru_cache(maxsize=None)
def registry(pool='all',mode='normal',role='writer'):
    assert role in ('writer','reader')
    r=Registry('scion-'+pool+'-'+mode);register_scion_insight_card(r)
    r.register_behavior(P+'noop',lambda c:())
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,
        metadata=replace(META,collectible=False,classes=(CardClass.MAGE,))))
    for cid,runes in ((B,Runes(1,0,0)),(F,Runes(0,1,0)),(U,Runes(0,0,1)),
            (BF,Runes(1,1,0)),(BU,Runes(1,0,1)),(FU,Runes(0,1,1)),(BB,Runes(2,0,0)),
            (BBB,Runes(3,0,0)),(BFU,Runes(1,1,1)),(NONE,Runes())):
        card=CardDefinition(cid,cid,CardType.MINION,cost=1,attack=1,health=3,metadata=replace(META,runes=runes))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    members={
        'all':(B,F,U,BF,BU,FU,BB,BBB,BFU,NONE,CARD),'blood':(B,),'frost':(F,),
        'unholy':(U,),'bf':(BF,),'bu':(BU,),'fu':(FU,),'bb':(BB,),
        'empty':(NONE,CARD,BBB,BFU),'unknown':(B,F,U,UNKNOWN),'missing':(B,F,U,MISSING),
    }[pool]
    if pool in ('unknown','missing'):
        cid=UNKNOWN if pool=='unknown' else MISSING
        r.register_pool_card(PoolCard(cid,CardType.MINION,1,replace(META,runes=None if pool=='unknown' else Runes(frost=1))))
    r.register_pool(PoolDefinition(POOL,'v1',CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(cid)for cid in members),complete=True))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=4,metadata=META,
        battlecry_repeats=(BattlecryRepeatSpec(),)))
    for cid,body in ((NATURAL,lambda c:(Summon(c.player_id,CARD),)),
            (GENERATE,lambda c:(GenerateFromPool(c.player_id,POOL,PoolQuery(collectible=True),source_id=c.source_id),)),
            (NAMED,lambda c:(AddToHand(c.player_id,BBB,c.source_id),))):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META))
    def fail(c):raise ResolutionError('Deliberate Scion reaction failure')
    r.register_behavior(P+'fail',fail)
    if mode!='normal':
        def watch(c):
            if mode=='full':
                if c.event.kind=='minion_summoned' and c.event.target_id is not None and c.state.entities[c.event.target_id].card_id==CARD:
                    return (AddToHand(c.player_id,NONE,c.source_id),)
                return ()
            if c.event.source_id is None or c.state.entities[c.event.source_id].card_id!=CARD:return ()
            eid=c.event.source_id
            if mode=='kill':return (Destroy(eid,c.source_id),)
            if mode=='control':return (ChangeControl(eid,2),)
            if mode=='bounce':return (ReturnToHand(eid),)
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return (RequestChoice(2,(ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',
                (InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=4,metadata=META,
            triggers=(TriggerSpec('minion_summoned'if mode=='full'else 'card_added_to_hand'if mode=='wait'else 'card_discovered',WATCH),)))
    r.validate();r.freeze();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
    return s


class ScionInsightTests(unittest.TestCase):
    def game(self,pool='all',mode='normal',pid=1,hand=None,board=(),seed=383):
        self.pool,self.mode,self.pid=pool,mode,pid
        if mode!='normal':board=(*board,WATCH)
        players=tuple(PlayerSetup(HERO,hand=((CARD,)if hand is None else hand)if p==pid else (),
            board=board if p==pid else (),deck=(NONE,)*8,mana=20,max_mana=20,mana_cap=20)for p in (1,2))
        return Game.from_scenario(Scenario(players,active_player=pid,seed=seed,generation_context=CONTEXT),registry(pool,mode))
    def play(self,g,cid=CARD):
        e=next(g.state.entities[i]for i in g.state.players[self.pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(self.pid,e.id,position=len(g.state.players[self.pid].board)if e.kind==CardType.MINION else None));return e.id
    def choose(self,g,cid=None,key=None):
        q=g.state.pending_choice
        o=next(o for o in q.options if (o.id==key if key is not None else cid is None or o.card_id==cid))
        g.apply(SelectChoice(q.player_id,q.id,(o.id,)));return o.card_id
    def portable(self,g):
        reader=registry(self.pool,self.mode,'reader');self.assertIsNot(reader,g.registry)
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,reader)
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),s);return other
    def hand(self,g,pid=1):return [g.state.entities[i]for i in g.state.players[pid].hand]
    def test_complete_pinned_source_and_both_primary_faces(self):
        d=load_batch();row=d['cards'][0];raw=row['record'];c=registry().card(CARD)
        self.assertEqual(canonical(raw),row['record_sha256'])
        self.assertEqual((c.cost,c.attack,c.health,c.battlecry,c.metadata.runes),(2,2,2,BODY,Runes()))
        self.assertFalse(c.keywords)
        for face in d['official_observations']:check_face(raw,face['face'],face['locale'])
    def test_real_payment_three_group_menu_and_genuine_discovery(self):
        g=self.game();eid=self.play(g);q=g.state.pending_choice
        self.assertEqual(g.state.players[1].mana,18);self.assertEqual(q.source_id,eid)
        self.assertEqual(q.purpose,ChoicePurpose.CARD_DISCOVERY);self.assertEqual(len(q.options),3)
        for o,rune in zip(q.options,('blood','frost','unholy')):
            self.assertGreater(getattr(g.registry.card(o.card_id).metadata.runes,rune),0)
            self.assertEqual(o.preview.cost,1)
        self.assertFalse(g.state.card_discovery_history);self.choose(g)
        self.assertEqual(len(discovered_cards(g.state,1)),1)
        self.assertEqual(len([e for e in g.events if e.kind=='card_discovered']),1)
    def test_single_and_mixed_runes_grant_all_matching_keywords_once(self):
        cases=(('blood',B,{Keyword.LIFESTEAL}),('frost',F,{Keyword.REBORN}),('unholy',U,{Keyword.RUSH}),
            ('bf',BF,{Keyword.LIFESTEAL,Keyword.REBORN}),('bu',BU,{Keyword.LIFESTEAL,Keyword.RUSH}),
            ('fu',FU,{Keyword.REBORN,Keyword.RUSH}),('bb',BB,{Keyword.LIFESTEAL}))
        for pool,cid,keywords in cases:
            with self.subTest(pool=pool):
                g=self.game(pool);eid=self.play(g);self.choose(g,cid)
                self.assertEqual(g.state.entities[eid].keywords,keywords)
                self.assertEqual([e.card_id for e in self.hand(g)],[cid])
                self.assertFalse(self.hand(g)[0].keywords)
    def test_multi_rune_overlaps_keep_separate_group_slots(self):
        g=self.game('bu');self.play(g);q=g.state.pending_choice
        self.assertEqual([o.card_id for o in q.options],[BU,BU]);self.assertEqual([o.id for o in q.options],['pool-1-1','pool-3-1'])
        self.choose(g,key='pool-3-1');self.assertEqual(len(discovered_cards(g.state,1)),1);self.assertEqual(len(self.hand(g)),1)
    def test_empty_groups_do_not_borrow_other_rune_options(self):
        g=self.game('blood');self.play(g)
        self.assertEqual([o.id for o in g.state.pending_choice.options],['pool-1-1']);self.choose(g,B)
    def test_empty_pool_and_only_banned_triples_do_not_consume_rng(self):
        g=self.game('empty');rng=g.snapshot()['rng_state'];eid=self.play(g)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertIsNone(g.state.pending_choice)
        self.assertFalse(g.state.card_discovery_history);self.assertFalse(g.state.entities[eid].keywords)
    def test_natural_summon_does_not_execute_battlecry(self):
        g=self.game(hand=(NATURAL,));self.play(g,NATURAL)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.card_discovery_history)
        self.assertEqual(len(g.state.players[1].board),1)
    def test_battlecry_repeat_gets_two_original_discoveries(self):
        g=self.game('blood',board=(REPEAT,));eid=self.play(g);self.choose(g,B)
        first=g.state.card_discovery_history[0];self.assertIsNotNone(g.state.pending_choice)
        self.choose(g,B);self.assertEqual(len(discovered_cards(g.state,1)),2)
        self.assertEqual(g.state.card_discovery_history[0],first);self.assertEqual(len(self.hand(g)),2)
        self.assertEqual(g.state.entities[eid].keywords,{Keyword.LIFESTEAL});self.assertEqual(g.state.players[1].mana,18)
    def test_other_seat_owns_discovery_and_original_recipient(self):
        g=self.game('frost',pid=2);eid=self.play(g);self.assertEqual(g.state.pending_choice.player_id,2)
        self.choose(g,F);self.assertEqual(g.state.entities[eid].keywords,{Keyword.REBORN})
        self.assertEqual(len(discovered_cards(g.state,2)),1);self.assertFalse(discovered_cards(g.state,1))
    def test_unknown_eligible_runes_fail_and_restore_whole_action(self):
        g=self.game('unknown');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)
    def test_unadapted_eligible_card_is_not_removed_and_all_groups_checked_before_rng(self):
        g=self.game('missing');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)
    def test_full_hand_burn_still_records_discovery_and_grants_source(self):
        g=self.game('blood','full',hand=(CARD,)+(NONE,)*9);eid=self.play(g)
        self.assertEqual(len(self.hand(g)),10);self.choose(g,B)
        self.assertEqual(len(self.hand(g)),10);self.assertEqual(g.state.entities[eid].keywords,{Keyword.LIFESTEAL})
        burned=[e for e in g.state.entities.values()if e.card_id==B and e.zone==Zone.GRAVEYARD]
        self.assertEqual(len(burned),1);self.assertEqual(len(discovered_cards(g.state,1)),1)
    def test_dead_original_source_is_not_replaced_by_a_new_minion(self):
        g=self.game('bu','kill');eid=self.play(g);self.choose(g,BU)
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertFalse(g.state.entities[eid].keywords)
        self.assertEqual([e.card_id for e in self.hand(g)],[BU])
    def test_changed_controller_and_returned_source_do_not_rebind_old_reference(self):
        for mode in ('control','bounce'):
            with self.subTest(mode=mode):
                g=self.game('bu',mode);eid=self.play(g);self.choose(g,BU)
                self.assertFalse(g.state.entities[eid].keywords)
                self.assertEqual(g.state.entities[eid].controller,2 if mode=='control'else 1)
                self.assertEqual(g.state.entities[eid].zone,Zone.BOARD if mode=='control'else Zone.HAND)
    def test_original_menu_and_after_delivery_wait_restore_clone_and_replay(self):
        g=self.game('bu','wait');eid=self.play(g);first=self.portable(g)
        for match in (g,first):self.choose(match,BU)
        self.assertEqual(g.snapshot(),first.snapshot());self.assertEqual(g.state.pending_choice.player_id,2)
        self.assertFalse(g.state.entities[eid].keywords);second=self.portable(g)
        for match in (g,second):self.choose(match,key='ok')
        self.assertEqual(g.snapshot(),second.snapshot());self.assertEqual(g.state.entities[eid].keywords,{Keyword.LIFESTEAL,Keyword.RUSH})
        self.portable(g)
    def test_reaction_exception_rolls_back_the_complete_selection(self):
        g=self.game('blood','fail');self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,B)
        self.assertEqual(g.snapshot(),before)
    def test_failure_inside_a_second_wait_preserves_accepted_original_discovery(self):
        g=self.game('blood','wait');self.play(g);self.choose(g,B);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,key='fail')
        self.assertEqual(g.snapshot(),before);self.choose(g,key='ok')
    def test_player_command_selects_opaque_option_and_hides_other_seat_menu(self):
        g=self.game('bu');eid=self.play(g);port=g.for_player(1);dto=port.legal_actions()
        command=next(a for a in dto['actions']if a['type']=='select_choice')
        port.submit({'revision':dto['revision'],'action':command})
        self.assertEqual(g.state.entities[eid].keywords,{Keyword.LIFESTEAL,Keyword.RUSH})
        for pid in (1,2):
            visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for key in ('card_discovery_history','original_offer','rune_recipient','resolution_frame','rng_state','eligible_ids'):
                self.assertNotIn('"'+key+'"',visible)
    def test_pending_complete_candidate_receipt_and_recipient_tampering_rejected(self):
        g=self.game('all');self.play(g)
        for field in ('eligible_ids','player_id'):
            saved=deepcopy(g.snapshot());changed=[]
            def visit(v):
                if isinstance(v,dict):
                    if v.get('type','').endswith('.CapturedOfferGroup')and field=='eligible_ids'and not changed:
                        v['fields']['eligible_ids']=[];changed.append(True)
                    if v.get('type','').endswith('.MinionReference')and field=='player_id'and not changed:
                        v['fields']['player_id']=2;changed.append(True)
                    for x in v.values():visit(x)
                elif isinstance(v,list):
                    for x in v:visit(x)
            visit(saved);self.assertTrue(changed)
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry('all','normal','reader'))
    def test_genuine_group_spec_rejects_wrong_shape_and_preclaimed_selection(self):
        g=self.game('bu');self.play(g);work=g._frame.options[0].effects[0];spec=work.receipt.spec
        for change in ({'groups':spec.groups[:2]},{'cost':CostSpec(delta=-1)},
                {'affordable':True},{'rune_recipient':replace(spec.rune_recipient,player_id=2)},
                {'groups':tuple(replace(x,count=2)for x in spec.groups)}):
            with self.subTest(change=change),self.assertRaises(ValueError):replace(spec,**change)
        self.choose(g,BU);result=g.state.card_discovery_history[-1].result
        with self.assertRaises(ValueError):replace(work,group_index=2,result=result)
    def test_ordinary_generation_excludes_three_runes_but_structural_queries_keep_the_fact(self):
        r=registry();rows=resolve_candidates(r,CONTEXT,POOL,PoolQuery(collectible=True))
        ids={m.card_id for m in rows};self.assertNotIn(BBB,ids);self.assertNotIn(BFU,ids)
        self.assertTrue({B,F,U,BF,BU,FU,BB}<=ids)
        self.assertTrue(matches_metadata(PoolQuery(runes_any=('blood',)),card_id=BFU,kind=CardType.MINION,
            cost=1,meta=r.card(BFU).metadata,spell_school=None,keywords=()))
    def test_unimplemented_banned_three_rune_row_is_excluded_before_implementation_check(self):
        r=Registry('scion-banned-only');cid=P+'unimplemented-triple'
        r.register_pool_card(PoolCard(cid,CardType.MINION,1,replace(META,runes=Runes(1,1,1))))
        r.register_pool(PoolDefinition(POOL,'v1',CONTEXT.target_id,CONTEXT.mode,(PoolMember(cid),)))
        self.assertEqual(resolve_candidates(r,CONTEXT,POOL,PoolQuery()),())
    def test_ordinary_generation_requires_known_eligible_death_knight_runes(self):
        r=registry('unknown')
        with self.assertRaises(UnknownCardFactError):resolve_candidates(r,CONTEXT,POOL,PoolQuery())
        self.assertEqual(resolve_candidates(r,CONTEXT,POOL,PoolQuery(kinds=(CardType.SPELL,))),())
    def test_named_delivery_of_three_rune_card_still_works(self):
        g=self.game(hand=(NAMED,));self.play(g,NAMED)
        self.assertEqual([e.card_id for e in self.hand(g)],[BBB]);self.assertFalse(g.state.card_discovery_history)


if __name__=='__main__':unittest.main()
