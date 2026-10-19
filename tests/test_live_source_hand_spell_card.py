"""Ido's native live source, one supplied card and ordinary reusable spell."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.live_source_hand_spell_card import CARD,SPELL,load_batch
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,
    SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.effects import AddToHand,ChoiceOption,Destroy,InvokeBehavior,RequestChoice,Transform
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.live_hand_spells import LiveHandSpellProfile,LiveHandSpellLease
from hs_sim.engine.cross_zone import TransformStoredIntoCopy
from hs_sim.engine.model import Keyword,SpellSchool,TargetSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference,DiscardCard
from test_infinite_cost_card import registry as base_registry,P,PLAIN

G='ido.test.'


@lru_cache(None)
def registry(role='writer',mode=None):
    r=base_registry.__wrapped__()
    r.register_behavior(G+'fill',lambda c:())
    r.register_card(CardDefinition(G+'fill','Filler',CardType.SPELL,on_play=G+'fill'))
    r.register_behavior(G+'discard',lambda c:(DiscardCard(CardReference.capture(c.state.entities[c.target_id]),c.source_id),))
    r.register_card(CardDefinition(G+'discard','Discard original',CardType.SPELL,on_play=G+'discard',
        targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.SPELL,),relation='friendly')))
    def auto(c):
        target=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==PLAIN)
        return (CastSpell(c.player_id,SPELL,c.source_id,target_id=target,targeting='explicit'),)
    r.register_behavior(G+'auto',auto);r.register_card(CardDefinition(G+'auto','Actual automatic cast',CardType.SPELL,on_play=G+'auto'))
    r.register_behavior(G+'morph',lambda c:(Transform(c.target_id,PLAIN),))
    r.register_card(CardDefinition(G+'morph','Replace original source',CardType.SPELL,on_play=G+'morph',
        targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')))
    def copy_face(c):
        other=next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==G+'fill')
        return (TransformStoredIntoCopy(CardReference.capture(c.state.entities[c.target_id]),CardReference.capture(other),c.source_id),)
    r.register_behavior(G+'copy_face',copy_face)
    r.register_card(CardDefinition(G+'copy_face','Ordinary current stored copy',CardType.SPELL,on_play=G+'copy_face',
        targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.SPELL,),relation='friendly')))
    if mode:
        def watch(c):
            target=c.state.entities.get(c.event.target_id);source=c.state.entities.get(c.event.source_id)
            if c.event.player_id!=c.player_id:return ()
            if mode in ('generation_wait','generation_fail'):
                if target is None or target.card_id!=SPELL:return ()
            elif mode=='return_fail':
                if source is None or source.card_id!=SPELL:return ()
            elif source is None or source.card_id!=SPELL:return ()
            if mode.endswith('fail'):return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode=='kill_source':
                parent=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD)
                return (Destroy(parent,c.source_id),)
            if mode=='fill_on_cast':return (AddToHand(c.player_id,G+'fill',c.source_id),)
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        event='card_added_to_hand' if mode.startswith('generation') else 'card_returned' if mode=='return_fail' else 'spell_cast_accepted'
        r.register_behavior(G+'watch',watch)
        r.register_card(CardDefinition(G+'watch','Observer',CardType.MINION,health=20,triggers=(TriggerSpec(event,G+'watch'),)))
    r.validate();r.freeze();return r


class LiveSourceHandSpellTests(unittest.TestCase):
    def game(self,hand=(CARD,),*,board=(PLAIN,),enemy_hand=(),enemy_board=(),mode=None,seat=1):
        own=PlayerSetup('HERO_08',hand=hand,board=(*((G+'watch',) if mode else ()),*board),deck=(G+'fill',)*25,
            mana=50,max_mana=50,mana_cap=50)
        enemy=PlayerSetup('HERO_08',hand=enemy_hand,board=enemy_board,deck=(G+'fill',)*25,mana=50,max_mana=50,mana_cap=50)
        return Game.from_scenario(Scenario((own,enemy) if seat==1 else (enemy,own),active_player=seat,seed=284),registry('writer',mode))
    def hand(self,g,cid):return next(i for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id==cid)
    def play(self,g,cid=CARD,target=None,eid=None):
        pid=g.state.active_player;eid=self.hand(g,cid) if eid is None else eid;g.apply(PlayCard(pid,eid,target));return eid
    def board(self,g,cid,seat=None):
        seat=g.state.active_player if seat is None else seat
        return [i for i in g.state.players[seat].board if g.state.entities[i].card_id==cid]
    def spells(self,g,seat=None):
        seat=g.state.active_player if seat is None else seat
        return [i for i in g.state.players[seat].hand if g.state.entities[i].card_id==SPELL]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode=None):
        snap=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(snap,registry('reader',mode))
        self.assertEqual(other.snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),registry('reader',mode)).snapshot(),snap);return other
    def cast(self,g,token=None):
        token=self.spells(g)[0] if token is None else token;target=self.board(g,PLAIN)[0]
        self.play(g,SPELL,target,token);return token

    def test_a01_complete_sources_native_live_profile_and_real_holy_spell(self):
        d=load_batch();r=registry();self.assertEqual(len(d['official_observations']),4)
        self.assertEqual((r.card(CARD).cost,r.card(CARD).attack,r.card(CARD).health),(4,2,7))
        self.assertIsNone(r.card(CARD).battlecry);self.assertFalse(r.card(CARD).triggers)
        self.assertEqual((r.card(SPELL).cost,r.card(SPELL).spell_school),(2,SpellSchool.HOLY))
        self.assertEqual(r.live_hand_spell_profiles[CARD],LiveHandSpellProfile(CARD,SPELL))

    def test_a02_real_paid_source_creates_one_bound_original_without_battlecry(self):
        g=self.game();rng=g._rng.getstate();source=self.play(g);token=self.spells(g)[0];row=g.state.live_hand_spells[0]
        self.assertEqual(g.state.players[1].mana,46);self.assertFalse(g.state.battlecry_history)
        self.assertEqual((row.source.entity_id,row.token_id),(source,token));self.assertEqual(len(g.state.live_hand_spells),1)
        self.assertEqual(g.state.entities[token].origin_entity_id,source);self.assertEqual(g._rng.getstate(),rng)

    def test_a03_paid_spell_buffs_shields_and_returns_original_through_new_hand_acquisition(self):
        g=self.game();self.play(g);token=self.spells(g)[0];entry=g.state.entities[token].hand_entry_id
        next_id=g.state.next_entity_id;self.cast(g,token);target=g.state.entities[self.board(g,PLAIN)[0]]
        self.assertEqual((target.attack,target.max_health),(6,7));self.assertIn(Keyword.DIVINE_SHIELD,target.keywords)
        self.assertEqual(self.spells(g),[token]);self.assertNotEqual(g.state.entities[token].hand_entry_id,entry)
        self.assertEqual(g.state.next_entity_id,next_id);self.assertEqual(g.state.players[1].mana,44)
        self.assertEqual(g.state.live_hand_spells[0].last_play_id,g.state.play_history[-1].id)

    def test_a04_repeated_paid_plays_keep_one_original_and_use_actual_cast_history(self):
        g=self.game();self.play(g);token=self.spells(g)[0];next_id=g.state.next_entity_id
        self.cast(g,token);self.cast(g,token);target=g.state.entities[self.board(g,PLAIN)[0]]
        self.assertEqual((target.attack,target.max_health),(8,9));self.assertEqual(g.state.players[1].mana,42)
        self.assertEqual(len(g.state.cast_history),2);self.assertEqual(self.spells(g),[token]);self.assertEqual(g.state.next_entity_id,next_id)

    def test_a05_source_death_silence_bounce_and_transform_retire_only_its_hand_card(self):
        for spell in (P+'kill',P+'silence',P+'bounce',G+'morph'):
            g=self.game((CARD,spell));source=self.play(g);token=self.spells(g)[0]
            self.play(g,spell,source);self.assertFalse(self.spells(g));self.assertTrue(g.state.live_hand_spells[0].retired)
            self.assertEqual(g.state.entities[token].zone,Zone.SETASIDE)
            self.assertFalse(g.state.discard_history)

    def test_a06_control_transfer_retires_old_supply_and_gives_new_controller_one(self):
        g=self.game((CARD,P+'steal'));source=self.play(g);old=self.spells(g)[0];self.play(g,P+'steal',source)
        self.assertFalse(self.spells(g,1));self.assertEqual(len(self.spells(g,2)),1);self.assertNotIn(old,self.spells(g,2))
        self.assertEqual([x.retired for x in g.state.live_hand_spells],[True,False])
        self.assertEqual(g.state.live_hand_spells[-1].source.player_id,2)

    def test_a07_initial_multiple_sources_have_complete_independent_supplies_before_notices(self):
        g=self.game((),board=(CARD,CARD,PLAIN));self.assertEqual(len(self.spells(g)),2)
        self.assertEqual(len({x.token_id for x in g.state.live_hand_spells}),2);self.portable(g)

    def test_a08_board_source_copy_has_its_own_supply_and_silenced_current_copy_has_none(self):
        g=self.game((CARD,P+'copy',P+'silence',P+'copy',P+'base'));source=self.play(g);self.play(g,P+'copy',source)
        self.assertEqual(len(self.spells(g)),2);self.play(g,P+'silence',source);self.assertEqual(len(self.spells(g)),1)
        self.play(g,P+'copy',source);self.assertEqual(len(self.spells(g)),1)
        self.play(g,P+'base',source);self.assertEqual(len(self.spells(g)),2)

    def test_a09_shuffling_original_into_deck_never_recreates_the_fixed_duplicate_bug(self):
        g=self.game((CARD,P+'deck',G+'fill',P+'draw'));self.play(g);token=self.spells(g)[0]
        count=g.state.next_entity_id;self.play(g,P+'deck',token);self.play(g,G+'fill')
        self.assertFalse(self.spells(g));self.assertEqual(g.state.next_entity_id,count)
        self.assertEqual(g.state.players[1].deck[0],token);self.play(g,P+'draw');self.assertEqual(self.spells(g),[token])
        self.assertEqual(len(g.state.live_hand_spells),1)

    def test_a10_source_exit_does_not_destroy_deck_card_and_later_draw_is_ordinary(self):
        g=self.game((CARD,P+'deck',P+'kill',P+'draw'));source=self.play(g);token=self.spells(g)[0]
        self.play(g,P+'deck',token);self.play(g,P+'kill',source);self.assertIn(token,g.state.players[1].deck)
        self.play(g,P+'draw');self.cast(g,token);self.assertFalse(self.spells(g));self.assertEqual(g.state.entities[token].zone,Zone.GRAVEYARD)

    def test_a11_discarding_supplied_original_does_not_create_new_supply(self):
        g=self.game((CARD,G+'discard',G+'fill'));self.play(g);token=self.spells(g)[0]
        self.play(g,G+'discard',token);count=g.state.next_entity_id;self.play(g,G+'fill')
        self.assertFalse(self.spells(g));self.assertEqual(g.state.next_entity_id,count);self.assertEqual(len(g.state.discard_history),1)

    def test_a12_full_hand_initial_overflow_is_one_original_attempt_without_retry_loop(self):
        g=self.game((G+'fill',)*10,board=(CARD,PLAIN));row=g.state.live_hand_spells[0]
        self.assertEqual(g.state.entities[row.token_id].zone,Zone.GRAVEYARD);count=g.state.next_entity_id
        self.play(g,G+'fill');self.assertFalse(self.spells(g));self.assertEqual(g.state.next_entity_id,count)

    def test_a13_full_hand_return_burns_original_once_without_recreating_cards(self):
        g=self.game((G+'fill',)*9,board=(CARD,PLAIN),mode='fill_on_cast');token=self.spells(g)[0]
        count=g.state.next_entity_id;self.cast(g,token)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(g.state.entities[token].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.next_entity_id,count+1);self.assertEqual(g.state.live_hand_spells[0].last_play_id,g.state.play_history[-1].id)

    def test_a14_unbound_generated_and_copied_spells_do_not_inherit_the_supply_lease(self):
        g=self.game((SPELL,P+'hand_copy'),board=(CARD,PLAIN));unbound=self.hand(g,SPELL);bound=g.state.live_hand_spells[0].token_id
        self.play(g,P+'hand_copy',bound);copy=self.spells(g)[-1];self.assertNotEqual(copy,bound)
        self.cast(g,copy);self.assertEqual(g.state.entities[copy].zone,Zone.GRAVEYARD)
        self.cast(g,unbound);self.assertEqual(self.spells(g),[bound]);self.assertEqual(len(g.state.live_hand_spells),1)

    def test_a15_automatic_holy_cast_does_not_create_additional_supplied_cards(self):
        g=self.game((CARD,G+'auto'));self.play(g);token=self.spells(g)[0];self.play(g,G+'auto')
        self.assertEqual(self.spells(g),[token]);self.assertEqual(len(g.state.live_hand_spells),1)
        self.assertEqual(g.state.entities[self.board(g,PLAIN)[0]].attack,6)

    def test_a16_actual_counterspell_still_returns_bound_card_without_applying_buff(self):
        g=self.game(('EX1_287',),enemy_board=(CARD,PLAIN),seat=2);self.play(g,'EX1_287');g.apply(EndTurn(2))
        token=self.spells(g)[0];self.cast(g,token)
        self.assertEqual(self.spells(g),[token]);self.assertTrue(g.state.play_history[-1].countered)
        self.assertEqual(g.state.entities[self.board(g,PLAIN)[0]].attack,4)

    def test_a17_source_death_during_actual_spell_acceptance_prevents_return_but_not_accepted_body(self):
        g=self.game(mode='kill_source');source=self.play(g);token=self.spells(g)[0];self.cast(g,token)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertFalse(self.spells(g))
        self.assertEqual(g.state.entities[self.board(g,PLAIN)[0]].attack,6)

    def test_a18_one_source_exit_leaves_other_original_supply_intact(self):
        g=self.game((P+'kill',),board=(CARD,CARD,PLAIN));rows=g.state.live_hand_spells
        self.play(g,P+'kill',rows[0].source.entity_id);self.assertEqual(self.spells(g),[rows[1].token_id])
        self.cast(g,rows[1].token_id);self.assertEqual(self.spells(g),[rows[1].token_id])

    def test_a19_bounce_and_replay_have_new_presence_and_one_fresh_supply(self):
        g=self.game((CARD,P+'bounce'));source=self.play(g);first=self.spells(g)[0]
        self.play(g,P+'bounce',source);self.play(g,eid=source);second=self.spells(g)[0]
        self.assertNotEqual(first,second);self.assertEqual([r.retired for r in g.state.live_hand_spells],[True,False])
        self.assertNotEqual(g.state.live_hand_spells[0].source,g.state.live_hand_spells[1].source)

    def test_a20_pending_creation_and_prebody_cast_recover_clone_and_replay(self):
        for mode in ('generation_wait','cast_wait'):
            g=self.game(mode=mode);self.play(g)
            if mode=='cast_wait':self.cast(g)
            self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,mode)
            self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.spells(g)),1)

    def test_a21_late_generation_and_return_errors_roll_back_whole_original_action(self):
        for mode in ('generation_fail','return_fail'):
            g=self.game(mode=mode)
            if mode=='return_fail':self.play(g)
            before=g.snapshot()
            with self.assertRaisesRegex(ResolutionError,'deliberate failure'):
                self.play(g) if mode=='generation_fail' else self.cast(g)
            self.assertEqual(g.snapshot(),before)

    def test_a22_failed_choice_keeps_exact_waiting_source_and_original_supply(self):
        g=self.game(mode='generation_wait');self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(len(self.spells(g)),1)

    def test_a23_player_projection_hides_lease_origin_and_opponent_spell_for_both_seats(self):
        for seat in (1,2):
            g=self.game(seat=seat);self.play(g)
            own=json.dumps(g.observe(seat));other=json.dumps(g.observe(3-seat))
            self.assertIn(SPELL,own);self.assertNotIn(SPELL,other)
            for value in (own,other):
                for key in ('live_hand_spells','token_id','created_action','last_play_id'):self.assertNotIn(key,value)

    def test_a24_complete_source_ledger_and_return_proof_reject_rehashed_tampering(self):
        g=self.game();self.play(g);self.cast(g);original=g.snapshot()
        changes=(lambda s:s['state']['live_hand_spells'].clear(),
            lambda s:s['state']['live_hand_spells'][0]['token'].update(entity_id=999999),
            lambda s:s['state']['live_hand_spells'][0].update(created_action=g.state.action_number+1),
            lambda s:s['state']['live_hand_spells'][0].update(last_play_id=0),
            lambda s:s['state']['live_hand_spells'][0].update(retired=True))
        for change in changes:
            bad=deepcopy(original);change(bad)
            bad['state_hash']=canonical_hash({k:v for k,v in bad.items() if k not in ('schema_version','events','events_hash','state_hash')})
            with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(bad,registry('reader'))
        self.portable(g)

    def test_a25_legal_current_stored_transform_does_not_invalidate_original_creation_proof(self):
        g=self.game((CARD,G+'copy_face',G+'fill'));self.play(g);token=self.spells(g)[0]
        original=g.state.live_hand_spells[0].token
        self.play(g,G+'copy_face',token);self.assertEqual(g.state.entities[token].card_id,G+'fill')
        self.assertFalse(self.spells(g));self.assertEqual(len(g.state.live_hand_spells),1)
        self.assertEqual(g.state.live_hand_spells[0].token.card_id,SPELL)
        self.assertEqual(g.state.live_hand_spells[0].token,original)
        self.assertEqual(g.state.live_hand_spells[0].token.entity_id,token)
        self.play(g,G+'fill',eid=token);self.assertFalse(self.spells(g));self.portable(g)


if __name__=='__main__':unittest.main()
