"""Real Podling replacement through ordinary, pool and current-copy transforms."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.plucky_podling_card import CARD, load_batch
from hs_sim.engine import CardDefinition, CardType, Game, PlayCard, PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone
from hs_sim.engine.cross_zone import TransformCapturedMinion, TransformMinionFromPool, TransformMinionIntoCopy
from hs_sim.engine.effects import Buff, ChangeControl, ChoiceOption, CopyMinion, Damage, Destroy, GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import AbilityInstance, CardClass, CardMetadata, NativeSourceCondition, SummonStats
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.transform_replacements import EVENT, TransformReplacementDraw

P='podling.test.'
NORMAL, REQUEST, WATCH, FAIL = (P+x for x in ('normal','request','watch','fail'))
FILL, DIRECT, CAPTURED, RANDOM, COPY, QUIET, CURRENT, GIVE, BOUNCE, KILL, BEFORE, BUFF_SOURCE = (
    P+x for x in ('fill','direct','captured','random','copy','quiet','current','give','bounce','kill','before','buff_source'))
R2,R4,R5A,R5B=(P+x for x in ('r2','r4','r5a','r5b'))
CONTEXT=GenerationContext('podling-fixture-v1','experimental')


@lru_cache(maxsize=None)
def registry(role='writer',mode='normal'):
    assert role in ('writer','reader')
    r=build_registry();meta=CardMetadata(True,(CardClass.NEUTRAL,),None,tribes=())
    r.register_behavior(P+'bc',lambda c:(GainArmor(c.player_id,99),))
    for cid,cost,attack,hp in ((NORMAL,1,1,2),(REQUEST,3,3,6),(R2,2,2,4),(R4,4,4,6),(R5A,5,5,7),(R5B,5,6,8)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=hp,metadata=meta,battlecry=P+'bc'))
        if cid!=NORMAL:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    members=[PoolMember(x) for x in (REQUEST,R2,R4)]
    if mode!='empty':members.extend((PoolMember(R5A),PoolMember(R5B,3)))
    if mode=='unknown':
        c=replace(r.card(R5A),id=P+'unimplemented');r.register_pool_card(PoolCard.from_definition(c));members.append(PoolMember(c.id))
    if mode!='missing':r.register_pool(PoolDefinition('constructed.cards','podling-fixture-v1',CONTEXT.target_id,CONTEXT.mode,
        tuple(sorted(members,key=lambda x:x.card_id))))
    def original(c):
        return next(c.state.entities[i] for cid in (CARD,NORMAL) for pid in (1,2)
            for i in c.state.players[pid].board if c.state.entities[i].card_id==cid)
    def direct(c):return Transform(original(c).id,REQUEST)
    def captured(c):return TransformCapturedMinion(MinionReference.capture(original(c)),REQUEST,c.source_id)
    def copy(c):
        src=next(c.state.entities[i] for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==REQUEST)
        return (TransformMinionIntoCopy(MinionReference.capture(original(c)),MinionReference.capture(src),c.source_id,stats=SummonStats(1,1)),)
    def kill(c):
        e=next(c.state.entities[i] for pid in (1,2) for i in c.state.players[pid].board if c.state.entities[i].card_id in (R4,R5A,R5B))
        return (Destroy(e.id,c.source_id),)
    scripts={FILL:lambda c:(),DIRECT:lambda c:(direct(c),),CAPTURED:lambda c:(captured(c),),
        RANDOM:lambda c:(TransformMinionFromPool(MinionReference.capture(original(c)),'constructed.cards',2,source_id=c.source_id),),
        COPY:copy,QUIET:lambda c:(Silence(original(c).id),),CURRENT:lambda c:(CopyMinion(original(c).id,c.player_id),),
        GIVE:lambda c:(ChangeControl(original(c).id,2),),BOUNCE:lambda c:(ReturnToHand(original(c).id),),KILL:kill,
        BEFORE:lambda c:(RequestChoice(c.player_id,(ChoiceOption('go','Transform',(captured(c),)),ChoiceOption('skip','Skip')),c.source_id),),
        BUFF_SOURCE:lambda c:(Buff(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==REQUEST),10,10,c.source_id),),}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    def fail(c):raise ResolutionError('Deliberate Podling reaction failure')
    r.register_behavior(P+'fail_body',fail)
    def watch(c,mode):
        data=dict(c.event.data)
        if data.get('old_card_id')!=CARD:return ()
        if mode=='fail':return (InvokeBehavior(P+'fail_body',c.source_id,c.player_id),)
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail_body',c.source_id,c.player_id),))),c.source_id),)
    for cid,mode in ((WATCH,'watch'),(FAIL,'fail')):
        r.register_behavior(cid,lambda c,mode=mode:watch(c,mode))
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=5,triggers=(TriggerSpec('transformed',cid),)))
    r.validate();r.freeze();return r


class PluckyPodlingTests(unittest.TestCase):
    def game(self,hand=(DIRECT,),board=(CARD,),*,mode='normal',context=True):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_02',hand=hand,board=board,deck=(FILL,)*20,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=(FILL,)*20,mana=10,max_mana=10)),seed=264,
            generation_context=CONTEXT if context else None),registry('writer',mode))
    def play(self,g,cid=DIRECT,target=None):
        i=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid);g.apply(PlayCard(1,i,target));return i
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def receipts(self,g):return [e for e in g.events if e.kind==EVENT]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry('reader',self.mode))
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry('reader',self.mode)).snapshot(),s);return other
    def rehash(self,s):
        keys=('ruleset','registry_fingerprint','mechanics_version','state','rng_state','resolution_frame','rewind_session','match_setup','generation_context','information')
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:s[k] for k in keys});return s

    def test_a00_full_original_face_body_native_declaration_and_existing_definition_shape(self):
        d=load_batch();self.assertEqual(len(d['official_observations']),2)
        c=registry().card(CARD);self.assertEqual((c.cost,c.attack,c.health),(1,1,2))
        self.assertEqual(c.native_condition,NativeSourceCondition('transform_destination_plus_two'))
        self.assertFalse(c.triggers);self.assertFalse(c.keywords)

    def test_a01_real_paid_podling_then_one_direct_transform_uses_destination_plus_two(self):
        g=self.game((CARD,DIRECT),board=());i=self.play(g,CARD);self.play(g)
        self.assertIn(g.state.entities[i].card_id,(R5A,R5B));self.assertEqual(g.state.players[1].mana,9)
        events=[e for e in g.events if e.kind=='transformed'];self.assertEqual(len(events),1)
        self.assertEqual(dict(events[0].data)['old_card_id'],CARD);self.assertNotIn(REQUEST,[dict(e.data)['card_id'] for e in events])
        self.assertEqual(len(self.receipts(g)),1);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)

    def test_a02_captured_and_random_cost_tier_entry_share_one_original_replacement(self):
        for operation in (CAPTURED,RANDOM):
            with self.subTest(operation=operation):
                g=self.game((operation,));i=g.state.players[1].board[0];self.play(g,operation)
                self.assertIn(g.state.entities[i].card_id,(R5A,R5B));self.assertEqual(len(self.receipts(g)),1)

    def test_a03_real_hex_uses_frog_printed_zero_then_two_cost_replacement(self):
        g=self.game(('CORE_EX1_246',));i=g.state.players[1].board[0];self.play(g,'CORE_EX1_246',i)
        self.assertEqual(g.state.entities[i].card_id,R2);self.assertEqual(len(self.receipts(g)),1)

    def test_a04_non_native_and_silenced_original_follow_regular_transform_without_random(self):
        for board,hand in (((NORMAL,),(DIRECT,)),((CARD,),(QUIET,DIRECT))):
            with self.subTest(board=board):
                g=self.game(hand,board)
                if QUIET in hand:self.play(g,QUIET)
                rng=g._rng.getstate();self.play(g);self.assertEqual(g.state.entities[g.state.players[1].board[0]].card_id,REQUEST)
                self.assertEqual(g._rng.getstate(),rng);self.assertFalse(self.receipts(g))

    def test_a05_original_current_copy_gets_new_native_identity_and_each_can_replace_once(self):
        g=self.game((CURRENT,DIRECT,DIRECT));self.play(g,CURRENT);ids=tuple(g.state.players[1].board)
        ability_ids=[next(a.id for a in g.state.entities[i].abilities if a.kind=='transform_replacement') for i in ids]
        self.assertEqual(len(set(ability_ids)),2)
        self.play(g);self.play(g);self.assertEqual(len(self.receipts(g)),2)
        self.assertTrue(all(g.state.entities[i].card_id in (R5A,R5B) for i in ids))

    def test_b00_source_control_change_uses_current_physical_controller_without_owner_rewrite(self):
        g=self.game((GIVE,DIRECT));i=g.state.players[1].board[0];self.play(g,GIVE);self.play(g)
        self.assertIn(g.state.entities[i].card_id,(R5A,R5B));self.assertEqual((g.state.entities[i].owner,g.state.entities[i].controller),(1,2))
        self.assertEqual(self.receipts(g)[0].player_id,2);self.portable(g)

    def test_b01_bounce_and_real_replay_reinstall_native_replacement(self):
        g=self.game((BOUNCE,DIRECT));i=g.state.players[1].board[0];self.play(g,BOUNCE);self.play(g,CARD);self.play(g)
        self.assertIn(g.state.entities[i].card_id,(R5A,R5B));self.assertEqual(len(self.receipts(g)),1)

    def test_b02_current_copy_transform_replacement_does_not_borrow_requested_copy_stats_or_buffs(self):
        g=self.game((BUFF_SOURCE,COPY),(CARD,REQUEST));self.play(g,BUFF_SOURCE);i=g.state.players[1].board[0];self.play(g,COPY)
        e=g.state.entities[i];base=g.registry.card(e.card_id);self.assertIn(e.card_id,(R5A,R5B))
        self.assertEqual((e.attack,e.max_health),(base.attack,base.health));self.assertFalse(e.damage)

    def test_b03_full_board_transform_keeps_original_slot_and_creates_no_extra_minion(self):
        g=self.game(board=(NORMAL,CARD)+(NORMAL,)*5);ids=tuple(g.state.players[1].board);i=ids[1];self.play(g)
        self.assertEqual(tuple(g.state.players[1].board),ids);self.assertIn(g.state.entities[i].card_id,(R5A,R5B))
        self.assertFalse(g.state.card_summon_history);self.assertFalse(g.state.death_history)

    def test_c00_real_ascendance_grants_original_return_to_actual_replacement_body(self):
        g=self.game(('CATA_567',KILL));i=g.state.players[1].board[0];self.play(g,'CATA_567')
        self.assertEqual(g.state.entities[i].card_id,R4)
        self.assertTrue(any(a.deathrattle_memory is not None for a in g.state.entities[i].abilities));self.play(g,KILL)
        returned=[g.state.entities[j] for j in g.state.players[1].board if g.state.entities[j].card_id==CARD]
        self.assertEqual(len(returned),1);self.assertTrue(any(a.kind=='transform_replacement' for a in returned[0].abilities))

    def test_c01_empty_replacement_tier_keeps_original_without_rng_or_fake_transform(self):
        g=self.game(mode='empty');i=g.state.players[1].board[0];rng=g._rng.getstate();self.play(g)
        self.assertEqual(g.state.entities[i].card_id,CARD);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(len(self.receipts(g)),1);self.assertFalse([e for e in g.events if e.kind=='transformed'])
        self.portable(g)

    def test_c02_unknown_eligible_and_missing_pool_or_context_reject_without_partial_change(self):
        for mode,context in (('unknown',True),('missing',True),('normal',False)):
            with self.subTest(mode=mode,context=context):
                g=self.game(mode=mode,context=context);s=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g)
                self.assertEqual(g.snapshot(),s)

    def test_d00_wait_before_original_transform_restores_then_draws_exactly_once(self):
        g=self.game((BEFORE,));self.play(g,BEFORE);self.assertFalse(self.receipts(g));other=self.portable(g)
        self.choose(g,'go');self.choose(other,'go');self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.receipts(g)),1)

    def test_d01_wait_after_replacement_restores_proof_and_bad_choice_does_not_resample(self):
        g=self.game(board=(CARD,WATCH));self.play(g);other=self.portable(g);s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Deliberate Podling reaction failure'):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),s);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())

    def test_d02_late_reaction_failure_rolls_back_native_replacement_random_and_receipt(self):
        g=self.game(board=(CARD,FAIL));s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Deliberate Podling reaction failure'):self.play(g)
        self.assertEqual(g.snapshot(),s)

    def test_d03_rehashed_original_destination_cannot_borrow_old_candidates_or_draw(self):
        g=self.game();self.play(g);s=g.snapshot();event=next(e for e in s['events'] if e['kind']==EVENT)
        def change(value):
            if isinstance(value,dict):
                if 'requested_card_id' in value:value['requested_card_id']=R2;return True
                return any(change(x) for x in value.values())
            if isinstance(value,list):return any(change(x) for x in value)
            return False
        self.assertTrue(change(event));self.rehash(s)
        with self.assertRaises(ValueError):Game.from_snapshot(s,registry('reader'))

    def test_d04_native_declaration_is_pure_printed_and_private_receipt_stays_out_of_views(self):
        g=self.game();i=g.state.players[1].board[0]
        with self.assertRaises(ValueError):AbilityInstance(999,'transform_replacement',source_id=i)
        with self.assertRaises(ValueError):AbilityInstance(999,'transform_replacement',source_id=i,origin='granted',native_condition=NativeSourceCondition('transform_destination_plus_two'))
        self.play(g)
        for pid in (1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for text in (EVENT,'"rng_before"','"candidates"','"next_attachment_id"'):self.assertNotIn(text,wire)


if __name__=='__main__':unittest.main()
