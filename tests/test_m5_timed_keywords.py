"""Printed/granted deadlines, physical lifecycle and resumable boundaries (R-129)."""
import json
import unittest
from copy import deepcopy
from dataclasses import replace

from hs_sim.engine import (Game, Registry, CardDefinition, CardType, Keyword, TimedKeywordSpec,
    KeywordExpiry, AbilityInstance, Scenario, PlayerSetup, PlayCard, EndTurn, Attack,
    SelectChoice, TriggerSpec, Zone, SnapshotError, ResolutionError, DamageKind)
from hs_sim.engine.effects import (GrantKeyword, Summon, Destroy, Damage, CopyMinion,
    ReturnToHand, ShuffleIntoDeck, Transform, Silence, ChangeControl, GainArmor,
    RequestChoice, ChoiceOption, RandomDamage)
from hs_sim.engine.dormancy import MakeDormant, AwakenMinion
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.engine.summon_sources import CopyStoredMinion, ResurrectMinion
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.replay import replay, build_replay
from hs_sim.engine.serialization import canonical_hash


class TimedKeywordTests(unittest.TestCase):
    def setUp(self):
        self.r = Registry('timed-keyword-tests-v1')
        self.r.register_card(CardDefinition('hero','hero',CardType.HERO,health=30))
        self.r.register_card(CardDefinition('body','body',CardType.MINION,attack=2,health=5))
        self.cloak('cloak')

    def cloak(self, cid, spec=None, **kw):
        spec = spec or TimedKeywordSpec(Keyword.STEALTH)
        kw['keywords'] = tuple(dict.fromkeys((*kw.get('keywords',()),spec.keyword)))
        self.r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=3,
            timed_keywords=(spec,),**kw))

    def script(self, cid, fn):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))

    def watch(self, cid, event, fn):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.MINION,health=4,triggers=(TriggerSpec(event,cid),)))

    def game(self, hand=(), board=(), enemy=(), enemy_hand=(), active=1):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,
            deck=('body',)*8,mana=10,max_mana=10),PlayerSetup('hero',hand=enemy_hand,board=enemy,
            deck=('body',)*8,mana=10,max_mana=10)),active_player=active,seed=88),self.r)

    def play(self, g, cid, player=1):
        i=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(player,i));return i

    def turn(self, g): g.apply(EndTurn(g.state.active_player))
    def board(self, g, p=1): return g.state.players[p].board
    def hidden(self, g, i): return Keyword.STEALTH in g.state.entities[i].keywords
    def timed(self, g, i): return [a for a in g.state.entities[i].abilities if a.timed_keyword is not None]
    def armor(self, g, p=1): return g.state.entities[g.state.players[p].hero_id].armor
    def choose(self, g):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,('ok',)))
    def pause(self, c): return RequestChoice(c.player_id,(ChoiceOption('ok','OK',()),),source_id=c.source_id)
    def check(self, g):
        s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s,self.r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),s)
    def reject(self, s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error: Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_printed_hand_waits_for_entry_and_survives_turns(self):
        g=self.game(hand=('cloak',));i=g.state.players[1].hand[0]
        self.assertIsNone(self.timed(g,i)[0].keyword_expiry)
        self.turn(g);self.turn(g);self.assertIsNone(self.timed(g,i)[0].keyword_expiry)
        self.play(g,'cloak');self.assertEqual(self.timed(g,i)[0].keyword_expiry.owner_turn_index,3);self.check(g)

    def test_play_has_stealth_until_own_next_start(self):
        g=self.game(hand=('cloak',));i=self.play(g,'cloak');self.assertTrue(self.hidden(g,i))
        self.turn(g);self.assertTrue(self.hidden(g,i));self.turn(g)
        self.assertFalse(self.hidden(g,i));self.assertEqual(self.timed(g,i),[]);self.check(g)

    def test_opponent_summon_expires_at_immediately_upcoming_own_start(self):
        self.script('summon',lambda c:[Summon(2,'cloak')]);g=self.game(hand=('summon',));self.play(g,'summon')
        i=self.board(g,2)[0];self.assertEqual(self.timed(g,i)[0].keyword_expiry.owner_turn_index,1)
        self.turn(g);self.assertFalse(self.hidden(g,i));self.check(g)

    def test_scenario_active_player_two_uses_correct_parity(self):
        g=self.game(board=('cloak',),enemy=('cloak',),active=2)
        self.assertEqual(self.timed(g,self.board(g)[0])[0].keyword_expiry.owner_turn_index,1)
        self.assertEqual(self.timed(g,self.board(g,2)[0])[0].keyword_expiry.owner_turn_index,2)
        self.turn(g);self.assertFalse(self.hidden(g,self.board(g)[0]));self.check(g)

    def test_expiry_precedes_start_listener_and_draw(self):
        self.watch('observe','turn_started',lambda c:[GainArmor(1,10 if any(Keyword.STEALTH in e.keywords
            for e in c.state.entities.values() if e.zone==Zone.BOARD and e.controller==1) else 1)])
        g=self.game(board=('cloak','observe'));self.turn(g);self.turn(g)
        self.assertEqual(self.armor(g),11)
        index=next(n for n,e in enumerate(g.events) if e.kind=='attachments_expired')
        events=[e.kind for e in g.events[index:]]
        self.assertLess(events.index('attachments_expired'),events.index('turn_started'))
        self.assertLess(events.index('turn_started'),events.index('card_drawn'));self.check(g)

    def test_entry_listener_sees_armed_keyword(self):
        self.watch('entry','minion_summoned',lambda c:[GainArmor(1, c.state.entities[c.event.target_id].abilities[0].keyword_expiry.owner_turn_index)])
        self.script('summon',lambda c:[Summon(1,'cloak')]);g=self.game(hand=('summon',),board=('entry',))
        self.play(g,'summon');self.assertEqual(self.armor(g),2);self.check(g)

    def test_current_copy_keeps_original_player_and_deadline(self):
        self.script('copy',lambda c:[CopyMinion(c.state.players[1].board[0],2)])
        g=self.game(hand=('copy',),board=('cloak',));self.play(g,'copy')
        a=self.timed(g,self.board(g)[0])[0];b=self.timed(g,self.board(g,2)[0])[0]
        self.assertNotEqual(a.id,b.id);self.assertEqual(a.keyword_expiry,b.keyword_expiry)
        self.turn(g);self.assertTrue(self.hidden(g,self.board(g,2)[0]))
        self.turn(g);self.assertFalse(self.hidden(g,self.board(g,2)[0]));self.check(g)

    def test_base_copy_binds_recipient_new_deadline(self):
        self.script('copy',lambda c:[CopyMinion(c.state.players[1].board[0],2,mode='base')])
        g=self.game(hand=('copy',),board=('cloak',));self.play(g,'copy')
        self.assertEqual(self.timed(g,self.board(g,2)[0])[0].keyword_expiry.player_id,2)
        self.turn(g);self.assertFalse(self.hidden(g,self.board(g,2)[0]));self.assertTrue(self.hidden(g,self.board(g)[0]));self.check(g)

    def test_current_copy_after_expiry_does_not_reinstall_printed_flag(self):
        self.script('copy',lambda c:[CopyMinion(c.state.players[1].board[0],1)])
        g=self.game(hand=('copy',),board=('cloak',));self.turn(g);self.turn(g);self.play(g,'copy')
        self.assertTrue(all(not self.hidden(g,i) for i in self.board(g)));self.check(g)

    def test_base_copy_after_expiry_reinstalls_flag(self):
        self.script('copy',lambda c:[CopyMinion(c.state.players[1].board[0],1,mode='base')])
        g=self.game(hand=('copy',),board=('cloak',));self.turn(g);self.turn(g);self.play(g,'copy')
        self.assertFalse(self.hidden(g,self.board(g)[0]));self.assertTrue(self.hidden(g,self.board(g)[1]));self.check(g)

    def test_transfer_does_not_rearm_or_rebind(self):
        self.script('steal',lambda c:[ChangeControl(c.state.players[1].board[0],2)])
        g=self.game(hand=('steal',),board=('cloak',));i=self.board(g)[0];old=self.timed(g,i)[0].keyword_expiry
        self.play(g,'steal');self.assertEqual(self.timed(g,i)[0].keyword_expiry,old)
        self.turn(g);self.assertTrue(self.hidden(g,i));self.turn(g);self.assertFalse(self.hidden(g,i));self.check(g)

    def test_bounce_discards_clock_then_replay_arms_fresh(self):
        self.script('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        g=self.game(hand=('bounce',),board=('cloak',));i=self.board(g)[0];self.play(g,'bounce')
        self.assertIsNone(self.timed(g,i)[0].keyword_expiry);self.turn(g);self.turn(g)
        self.play(g,'cloak');self.assertEqual(self.timed(g,i)[0].keyword_expiry.owner_turn_index,3);self.check(g)

    def test_shuffle_reset_and_stored_summon_arm_at_arrival(self):
        self.script('shuffle',lambda c:[ShuffleIntoDeck(c.state.players[1].board[0])])
        self.script('recruit',lambda c:[SummonStoredCard(CardReference.capture(next(e for e in c.state.entities.values()
            if e.zone==Zone.DECK and e.card_id=='cloak')),2)])
        g=self.game(hand=('shuffle','recruit'),board=('cloak',));i=self.board(g)[0];self.play(g,'shuffle')
        self.assertIsNone(self.timed(g,i)[0].keyword_expiry);self.play(g,'recruit')
        self.assertEqual(self.timed(g,i)[0].keyword_expiry.owner_turn_index,1);self.check(g)

    def test_current_stored_copy_arms_for_destination(self):
        self.script('copy',lambda c:[CopyStoredMinion(CardReference.capture(c.state.entities[c.state.players[1].hand[0]]),2)])
        g=self.game(hand=('cloak','copy'));self.play(g,'copy')
        self.assertEqual(self.timed(g,self.board(g,2)[0])[0].keyword_expiry.owner_turn_index,1);self.check(g)

    def test_hand_copy_remains_unarmed_until_play(self):
        self.script('copy',lambda c:[CopyCard(CardReference.capture(c.state.entities[c.state.players[1].hand[0]]),2)])
        g=self.game(hand=('cloak','copy'));self.play(g,'copy');i=g.state.players[2].hand[0]
        self.assertIsNone(self.timed(g,i)[0].keyword_expiry);self.turn(g);self.play(g,'cloak',2)
        self.assertEqual(self.timed(g,i)[0].keyword_expiry.owner_turn_index,2);self.check(g)

    def test_transform_to_timed_definition_arms_now(self):
        self.script('transform',lambda c:[Transform(c.state.players[1].board[0],'cloak')])
        g=self.game(hand=('transform',),board=('body',));self.turn(g);self.turn(g);self.play(g,'transform')
        self.assertEqual(self.timed(g,self.board(g)[0])[0].keyword_expiry.owner_turn_index,3);self.check(g)

    def test_transform_away_clears_old_deadline(self):
        self.script('transform',lambda c:[Transform(c.state.players[1].board[0],'body')])
        g=self.game(hand=('transform',),board=('cloak',));self.play(g,'transform');self.turn(g);self.turn(g)
        self.assertEqual(self.timed(g,self.board(g)[0]),[]);self.check(g)

    def test_silence_removes_flag_and_deadline(self):
        self.script('silence',lambda c:[Silence(c.state.players[1].board[0])])
        g=self.game(hand=('silence',),board=('cloak',));self.play(g,'silence');self.turn(g);self.turn(g)
        self.assertFalse(any(e.kind=='attachments_expired' for e in g.events));self.check(g)

    def test_dormant_entry_clock_runs_while_inactive(self):
        self.cloak('sleep',dormant_turns=2);g=self.game(board=('sleep',));i=self.board(g)[0]
        self.assertFalse(self.hidden(g,i));self.assertIsNotNone(self.timed(g,i)[0].keyword_expiry)
        self.turn(g);self.turn(g);self.assertEqual(self.timed(g,i),[])
        self.turn(g);self.turn(g);self.assertIsNone(g.state.entities[i].dormancy)
        self.assertFalse(self.hidden(g,i));self.check(g)

    def test_dormancy_does_not_pause_existing_clock(self):
        self.script('sleep',lambda c:[MakeDormant(c.state.players[1].board[0],None)])
        self.script('wake',lambda c:[AwakenMinion(c.state.players[1].board[0])])
        g=self.game(hand=('sleep','wake'),board=('cloak',));i=self.board(g)[0];self.play(g,'sleep')
        self.turn(g);self.turn(g);self.play(g,'wake');self.assertFalse(self.hidden(g,i));self.check(g)

    def test_attack_consumes_timed_stealth_early(self):
        g=self.game(board=('cloak',));i=self.board(g)[0];g.apply(Attack(1,i,g.state.players[2].hero_id))
        self.assertFalse(self.hidden(g,i));self.assertTrue(self.timed(g,i)[0].consumed)
        self.turn(g);self.turn(g);self.assertEqual(self.timed(g,i),[]);self.check(g)

    def test_minion_ability_damage_consumes_stealth(self):
        self.script('hit',lambda c:[Damage(c.state.players[2].hero_id,1,c.state.players[1].board[0],DamageKind.MINION_ABILITY)])
        g=self.game(hand=('hit',),board=('cloak',));self.play(g,'hit');self.assertFalse(self.hidden(g,self.board(g)[0]));self.check(g)

    def test_reborn_has_new_printed_deadline(self):
        self.cloak('reborn',keywords=(Keyword.REBORN,))
        self.script('kill',lambda c:[Destroy(c.state.players[1].board[0])])
        g=self.game(hand=('kill',),board=('reborn',));self.turn(g);self.turn(g);self.play(g,'kill');i=self.board(g)[0]
        self.assertEqual(g.state.entities[i].health,1);self.assertTrue(self.hidden(g,i))
        self.assertEqual(self.timed(g,i)[0].keyword_expiry.owner_turn_index,3);self.check(g)

    def test_resurrection_reinstalls_definition_after_expiry(self):
        self.script('kill',lambda c:[Destroy(c.state.players[1].board[0])])
        self.script('resurrect',lambda c:[ResurrectMinion(1,c.state.death_history[0].id)])
        g=self.game(hand=('kill','resurrect'),board=('cloak',));self.turn(g);self.turn(g)
        self.play(g,'kill');self.play(g,'resurrect');self.assertTrue(self.hidden(g,self.board(g)[0]));self.check(g)

    def test_expiry_cleans_dead_entity_but_preserves_frozen_death_receipt(self):
        self.script('kill',lambda c:[Destroy(c.state.players[1].board[0])])
        g=self.game(hand=('kill',),board=('cloak',));i=self.board(g)[0];self.play(g,'kill');old=g.state.death_history[0]
        self.turn(g);self.turn(g);self.assertEqual(self.timed(g,i),[])
        self.assertEqual(g.state.death_history[0],old);self.check(g)

    def test_granted_timed_and_permanent_copies_are_independent(self):
        self.script('grant',lambda c:[GrantKeyword(c.state.players[1].board[0],Keyword.STEALTH)])
        g=self.game(hand=('grant',),board=('cloak',));self.play(g,'grant');self.turn(g);self.turn(g)
        self.assertTrue(self.hidden(g,self.board(g)[0]));self.assertEqual(self.timed(g,self.board(g)[0]),[]);self.check(g)

    def test_granted_opponent_boundary_and_multiple_occurrences(self):
        spec=TimedKeywordSpec(Keyword.STEALTH,player='opponent',occurrences=2)
        self.script('grant',lambda c:[GrantKeyword(c.state.players[1].board[0],Keyword.STEALTH,duration=spec)])
        g=self.game(hand=('grant',),board=('body',));i=self.board(g)[0];self.play(g,'grant')
        self.assertEqual(self.timed(g,i)[0].keyword_expiry,KeywordExpiry(2,1,2,'turn_started',1))
        self.turn(g);self.turn(g);self.assertTrue(self.hidden(g,i));self.turn(g);self.assertFalse(self.hidden(g,i));self.check(g)

    def test_end_boundary_removes_after_end_reactions(self):
        self.cloak('end',TimedKeywordSpec(Keyword.STEALTH,'turn_ended'))
        self.watch('see','turn_ended',lambda c:[GainArmor(1,int(Keyword.STEALTH in c.state.entities[c.state.players[1].board[0]].keywords))])
        g=self.game(board=('end','see'));self.turn(g);self.assertEqual(self.armor(g),1)
        self.assertFalse(self.hidden(g,self.board(g)[0]));self.check(g)

    def test_end_boundary_reactions_can_renew_but_same_end_is_settled(self):
        self.cloak('end',TimedKeywordSpec(Keyword.STEALTH,'turn_ended'))
        self.watch('renew','attachments_expired',lambda c:[Silence(c.source_id),
            GrantKeyword(c.event.target_id,Keyword.TAUNT,duration=TimedKeywordSpec(Keyword.TAUNT,'turn_ended'))])
        g=self.game(board=('end','renew'));self.turn(g)
        self.assertEqual(len([e for e in g.events if e.kind=='attachments_expired']),2);self.check(g)

    def test_start_expiry_reactions_finish_before_start_capture(self):
        self.watch('renew','attachments_expired',lambda c:[GrantKeyword(c.event.target_id,Keyword.STEALTH,duration=TimedKeywordSpec(Keyword.STEALTH))])
        self.watch('see','turn_started',lambda c:[GainArmor(1,int(Keyword.STEALTH in c.state.entities[c.state.players[1].board[0]].keywords))])
        g=self.game(board=('cloak','renew','see'));self.turn(g);self.turn(g)
        self.assertEqual(self.armor(g),2);self.assertEqual(self.timed(g,self.board(g)[0])[0].keyword_expiry.owner_turn_index,3);self.check(g)

    def test_all_due_flags_removed_before_any_expiry_listener(self):
        self.watch('observe','attachments_expired',lambda c:[GainArmor(1,sum(Keyword.STEALTH in e.keywords for e in c.state.entities.values()))])
        g=self.game(board=('cloak','cloak','observe'));self.turn(g);self.turn(g)
        self.assertEqual(self.armor(g),0);self.check(g)

    def test_expiry_choice_saves_before_turn_start_and_resumes(self):
        self.watch('pause','attachments_expired',lambda c:[self.pause(c)])
        g=self.game(board=('cloak','pause'));self.turn(g);self.turn(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(any(e.kind=='turn_started' and dict(e.data).get('turn')==3 for e in g.events));self.check(g)
        other=Game.from_snapshot(g.snapshot(),self.r);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertTrue(any(e.kind=='turn_started' and dict(e.data).get('turn')==3 for e in g.events));self.check(g)

    def test_turn_start_grant_waits_for_next_boundary(self):
        self.watch('grant','turn_started',lambda c:[GrantKeyword(c.state.players[1].board[0],Keyword.STEALTH,duration=TimedKeywordSpec(Keyword.STEALTH))]
            if c.event.player_id==1 else [])
        g=self.game(board=('body','grant'));self.turn(g);self.turn(g)
        self.assertEqual(self.timed(g,self.board(g)[0])[0].keyword_expiry.owner_turn_index,3);self.check(g)

    def test_end_choice_keeps_flag_until_end_effects_complete(self):
        self.cloak('end',TimedKeywordSpec(Keyword.STEALTH,'turn_ended'))
        self.watch('pause','turn_ended',lambda c:[self.pause(c)]);g=self.game(board=('end','pause'));self.turn(g)
        self.assertTrue(self.hidden(g,self.board(g)[0]));self.check(g);self.choose(g)
        self.assertFalse(self.hidden(g,self.board(g)[0]));self.check(g)

    def test_expiry_failure_rolls_back_turn_rng_and_deadlines(self):
        self.watch('fail','attachments_expired',lambda c:[RandomDamage((c.state.players[1].hero_id,c.state.players[2].hero_id),1),Summon(1,'missing')])
        g=self.game(board=('cloak','fail'));self.turn(g);before=g.snapshot()
        with self.assertRaisesRegex(ValueError,'unsupported card'): self.turn(g)
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_public_duration_contains_no_attachment_or_source_identity(self):
        g=self.game(board=('cloak',),enemy_hand=('cloak',));row=g.observe(2)['players'][0]['board'][0]
        self.assertEqual(row['keyword_durations'],[dict(keyword='stealth',boundary='turn_started',player_id=1,owner_turn_index=2)])
        hand=g.observe(1)['players'][1]['hand'][0];self.assertNotIn('keyword_durations',hand)
        self.assertNotIn('keyword_expiry',json.dumps(g.observe(1)));self.check(g)

    def test_timed_grant_rejects_hero_transactionally(self):
        self.script('grant',lambda c:[GrantKeyword(c.state.players[1].hero_id,Keyword.STEALTH,duration=TimedKeywordSpec(Keyword.STEALTH))])
        g=self.game(hand=('grant',));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'board minions'):self.play(g,'grant')
        self.assertEqual(g.snapshot(),before)

    def test_invalid_duration_specs_rejected(self):
        for kwargs in (dict(keyword=Keyword.COMBO),dict(keyword='stealth'),dict(keyword=Keyword.STEALTH,occurrences=True),
                dict(keyword=Keyword.STEALTH,occurrences=0),dict(keyword=Keyword.STEALTH,boundary='draw'),dict(keyword=Keyword.STEALTH,player=1)):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):TimedKeywordSpec(**kwargs)

    def test_invalid_definition_duration_rejected(self):
        base=CardDefinition('bad','bad',CardType.MINION,health=1,keywords=(Keyword.STEALTH,))
        for fields in (dict(timed_keywords=[TimedKeywordSpec(Keyword.STEALTH)]),dict(timed_keywords=(TimedKeywordSpec(Keyword.TAUNT),)),
                dict(timed_keywords=(TimedKeywordSpec(Keyword.STEALTH),)*2),dict(kind=CardType.SPELL,timed_keywords=(TimedKeywordSpec(Keyword.STEALTH),))):
            with self.subTest(fields=fields),self.assertRaises(ValueError):self.r.register_card(replace(base,**fields))

    def test_dual_expiry_or_keyword_mismatch_rejected(self):
        for kw in (dict(expires_turn=3,duration=TimedKeywordSpec(Keyword.STEALTH)),dict(duration=TimedKeywordSpec(Keyword.TAUNT))):
            with self.subTest(kw=kw),self.assertRaises(ValueError):GrantKeyword(1,Keyword.STEALTH,**kw)
        with self.assertRaises(ValueError):AbilityInstance(1,'keyword',keyword=Keyword.STEALTH,keyword_expiry=KeywordExpiry(1,1,2,'turn_started',1))

    def test_snapshot_rejects_missing_deadline(self):
        g=self.game(board=('cloak',));s=g.snapshot();s['state']['entities'][str(self.board(g)[0])]['abilities'][0]['keyword_expiry']=None;self.reject(s)

    def test_snapshot_rejects_wrong_player_parity(self):
        g=self.game(board=('cloak',));s=g.snapshot();s['state']['entities'][str(self.board(g)[0])]['abilities'][0]['keyword_expiry']['player_id']=2;self.reject(s)

    def test_snapshot_rejects_wrong_count_and_boundary(self):
        g=self.game(board=('cloak',))
        for k,v in (('owner_turn_index',3),('created_turn',2),('boundary','turn_ended'),('player_id',True)):
            s=g.snapshot();s['state']['entities'][str(self.board(g)[0])]['abilities'][0]['keyword_expiry'][k]=v
            with self.subTest(k=k):self.reject(s)

    def test_snapshot_rejects_elapsed_deadline(self):
        g=self.game(board=('cloak',));i=self.board(g)[0];self.turn(g);self.turn(g);s=g.snapshot()
        a=AbilityInstance(s['state']['next_attachment_id'],'keyword',keyword=Keyword.STEALTH,
            timed_keyword=TimedKeywordSpec(Keyword.STEALTH),keyword_expiry=KeywordExpiry(1,1,2,'turn_started',1))
        from dataclasses import asdict
        s['state']['entities'][str(i)]['abilities'].append(asdict(a));s['state']['next_attachment_id']+=1;self.reject(s)

    def test_snapshot_rejects_previous_schema(self):
        g=self.game(board=('cloak',));s=g.snapshot();self.assertEqual(s['schema_version'],266);s['schema_version']=83;self.reject(s)

    def test_grants_with_different_deadlines_expire_independently(self):
        self.script('grant',lambda c:[GrantKeyword(c.state.players[1].board[0],Keyword.STEALTH,
            duration=TimedKeywordSpec(Keyword.STEALTH,occurrences=2))])
        g=self.game(hand=('grant',),board=('cloak',));i=self.board(g)[0];self.play(g,'grant')
        self.turn(g);self.turn(g);self.assertTrue(self.hidden(g,i));self.assertEqual(len(self.timed(g,i)),1)
        self.turn(g);self.turn(g);self.assertFalse(self.hidden(g,i));self.check(g)

    def test_expiry_reaction_terminal_prevents_new_turn_event_and_draw(self):
        self.watch('lethal','attachments_expired',lambda c:[Damage(c.state.players[2].hero_id,100)])
        g=self.game(board=('cloak','lethal'));self.turn(g);cards=len(g.state.players[1].hand);self.turn(g)
        self.assertEqual(g.state.winner,1);self.assertEqual(len(g.state.players[1].hand),cards)
        self.assertFalse(any(e.kind=='turn_started' and dict(e.data).get('turn')==3 for e in g.events));self.check(g)

    def test_timed_shield_consumption_does_not_restore_at_boundary(self):
        self.cloak('shield',TimedKeywordSpec(Keyword.DIVINE_SHIELD))
        self.script('hit',lambda c:[Damage(c.state.players[1].board[0],1)])
        g=self.game(hand=('hit',),board=('shield',));i=self.board(g)[0];self.play(g,'hit')
        self.assertEqual(g.state.entities[i].health,3);self.assertTrue(self.timed(g,i)[0].consumed)
        self.turn(g);self.turn(g);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[i].keywords);self.check(g)

    def test_pending_timed_grant_effect_round_trips(self):
        self.script('grant',lambda c:[self.pause(c),GrantKeyword(c.state.players[1].board[0],Keyword.STEALTH,
            duration=TimedKeywordSpec(Keyword.STEALTH))])
        g=self.game(hand=('grant',),board=('body',));self.play(g,'grant');self.check(g)
        other=Game.from_snapshot(g.snapshot(),self.r);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertTrue(self.hidden(g,self.board(g)[0]));self.check(g)

    def test_magnetic_pending_printed_duration_arms_on_host(self):
        from hs_sim.engine import CardMetadata,CardClass
        meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('mech',))
        self.r.register_card(CardDefinition('host','host',CardType.MINION,health=4,metadata=meta))
        self.cloak('magnet',keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',),metadata=meta)
        g=self.game(hand=('magnet',),board=('host',));i=g.state.players[1].hand[0]
        g.apply(PlayCard(1,i,position=0));host=self.board(g)[0]
        self.assertEqual(self.timed(g,host)[0].keyword_expiry.owner_turn_index,2);self.assertTrue(self.hidden(g,host))
        self.turn(g);self.turn(g);self.assertFalse(self.hidden(g,host));self.assertEqual(g.state.entities[host].max_health,7);self.check(g)

    def test_starship_construction_waits_until_launch_to_arm(self):
        from hs_sim.engine import CardClass,LaunchStarship
        from hs_sim.engine.starships import construction
        self.r.register_card(CardDefinition('ship','ship',CardType.MINION,starship_for=(CardClass.NEUTRAL,)))
        self.cloak('piece',keywords=(Keyword.STARSHIP_PIECE,))
        self.script('kill',lambda c:[Destroy(c.state.players[1].board[0])])
        g=self.game(hand=('kill',),board=('piece',));self.play(g,'kill');ship=construction(g.state,1)
        self.assertIsNone(self.timed(g,ship.id)[0].keyword_expiry);self.turn(g);self.turn(g)
        self.assertIsNone(self.timed(g,ship.id)[0].keyword_expiry);self.check(g)
        g.apply(LaunchStarship(1,ship.id));self.assertEqual(self.timed(g,ship.id)[0].keyword_expiry.owner_turn_index,3)
        self.assertTrue(self.hidden(g,ship.id));self.check(g)

    def test_timed_stealth_expiry_leaves_combo_and_battlecry_repeat_auras(self):
        from hs_sim.engine import BattlecryRepeatSpec,ComboRepeatSpec
        self.cloak('both',battlecry_repeats=(BattlecryRepeatSpec(kinds=(CardType.MINION,)),),combo_repeats=(ComboRepeatSpec(),))
        self.r.register_behavior('armor',lambda c:[GainArmor(1,1)])
        self.r.register_card(CardDefinition('combo','combo',CardType.MINION,health=3,
            keywords=(Keyword.COMBO,),combo='armor',battlecry='armor'))
        self.script('prime',lambda c:[])
        g=self.game(hand=('prime','combo'),board=('both',));self.turn(g);self.turn(g)
        self.play(g,'prime');self.play(g,'combo');self.assertEqual(self.armor(g),4)
        self.assertEqual((len(g.state.combo_history),len(g.state.battlecry_history)),(2,2));self.check(g)

    def test_real_combo_example_recovers_between_expiry_and_start(self):
        from examples.timed_keywords import run
        g,s=run();self.assertEqual(s['schema_version'],266)
        self.assertEqual((len(g.history),len(g.state.combo_history),len(g.state.battlecry_history)),(8,4,2))


if __name__=='__main__':unittest.main()
