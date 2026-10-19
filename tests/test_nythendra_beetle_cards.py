"""Real Nythendra, finite base forms and shared lifecycle/interpreter edges."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.nythendra_beetle_cards import load_batch, register_nythendra_beetle_cards
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, Keyword,
    PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, GainArmor, GrantDeathrattle, GrantKeyword, InvokeBehavior, RequestChoice,
    ReturnToHand, SetStats, Silence, Transform, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import SummonQuantitySpec
from hs_sim.engine.nythendra_reform import (ROOT, BEETLE, FORMS, SPLIT_START, SPLIT_STEP,
    SPLIT_DONE, REFORM_START, REFORM_CHILD, FinishNythendraReform)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.summon_sources import Resurrect
from hs_sim.engine.actions import Concede
from opening_fixtures import registry as opening_registry

P = 'nythendra.test.'
PLAIN = 'card.1'


@lru_cache(None)
def registry(role='writer', mode=None):
    r = opening_registry(); register_nythendra_beetle_cards(r)
    def fail(c): raise ResolutionError('deliberate beetle rollback')
    def gift(c):
        return (GrantDeathrattle(c.target_id, P+'death', c.source_id),
                GrantKeyword(c.target_id, Keyword.REBORN, c.source_id))
    r.register_behavior(P+'fail', fail)
    r.register_behavior(P+'death', lambda c: (GainArmor(c.player_id, 11),))
    bodies = {
        'kill':lambda c:(Destroy(c.target_id, c.source_id),),
        'set3':lambda c:(SetStats(c.target_id, attack=3, health=12),),
        'set2':lambda c:(SetStats(c.target_id, attack=2),),
        'zero':lambda c:(SetStats(c.target_id, attack=0),),
        'huge':lambda c:(SetStats(c.target_id, attack=2147483647),),
        'buff':lambda c:(Buff(c.target_id, 5, 8, source_id=c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'steal':lambda c:(ChangeControl(c.target_id, 3-c.player_id),),
        'morph':lambda c:(Transform(c.target_id, PLAIN),),
        'copy':lambda c:(CopyMinion(c.target_id, c.player_id),),
        'base':lambda c:(CopyMinion(c.target_id, c.player_id, mode='base'),),
        'twice':lambda c:(TriggerDeathrattles(c.target_id, c.source_id, times=2),),
        'gift':gift,
        'sleep':lambda c:(SummonByCard(c.player_id, (SummonEntryMaterial(BEETLE, dormant_turns=2),), SummonCause.capture(c)),),
        'resurrect':lambda c:(Resurrect(c.player_id, source_id=c.source_id, cause=SummonCause.capture(c)),),
    }
    for name, body in bodies.items():
        r.register_behavior(P+name, body)
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name,
            targeting=None if name in ('sleep','resurrect') else TargetSpec(kinds=(CardType.MINION,), zones=(Zone.BOARD,))))
    r.register_card(CardDefinition(P+'quantity', 'Summon doubler', CardType.MINION, health=20,
        summon_quantities=(SummonQuantitySpec(),)))
    if mode:
        def watch(c):
            if mode.startswith('start_'):
                if c.event.player_id != c.player_id:return ()
                target = next((eid for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id==BEETLE), None)
                if target is None:return ()
                if mode=='start_steal':return (ChangeControl(target, 3-c.player_id),)
                if mode=='start_kill':return (Destroy(target, c.source_id),)
                if mode=='start_silence':return (Silence(target),)
            elif mode=='remove_wait':
                if not any(row[3]==BEETLE for row in dict(c.event.data)['removed']):return ()
            else:
                entity=c.state.entities[c.event.target_id]
                if entity.card_id != (BEETLE if mode in ('split_wait','split_destroy') else FORMS[2]):return ()
                if mode=='split_destroy':return (Destroy(entity.id, c.source_id),)
            return (RequestChoice(c.player_id, (ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))), c.source_id),)
        r.register_behavior(P+'watch', watch)
        event = 'turn_started' if mode.startswith('start_') else 'cards_removed_from_game' if mode=='remove_wait' else 'minion_summoned'
        r.register_card(CardDefinition(P+'watch', 'Observer', CardType.MINION, health=20,
            triggers=(TriggerSpec(event, P+'watch'),)))
    r.validate(); r.freeze(); return r


class NythendraBeetleTests(unittest.TestCase):
    def game(self, board=(ROOT,), hand=(P+'kill',), *, enemy=(), mode=None, seat=1, rules=None):
        own=PlayerSetup('mage.hero', board=(*((P+'watch',) if mode else ()), *board),
            hand=hand, deck=(PLAIN,)*6, mana=10, max_mana=10)
        other=PlayerSetup('warrior.hero', board=enemy, deck=(PLAIN,)*6, mana=10, max_mana=10)
        kw={} if rules is None else {'ruleset':rules}
        return Game.from_scenario(Scenario((own,other) if seat==1 else (other,own), active_player=seat, seed=289), registry('writer',mode), **kw)
    def units(self,g,pid=1,cid=None):
        return [g.state.entities[i] for i in g.state.players[pid].board if cid is None or g.state.entities[i].card_id==cid]
    def play(self,g,cid,target=None):
        pid=g.state.active_player
        eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        definition=g.registry.card(cid)
        g.apply(PlayCard(pid,eid,target,position=len(g.state.players[pid].board) if definition.kind==CardType.MINION else None))
        return eid
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def finish(self,g):
        while g.state.pending_choice:self.choose(g)
    def own_start(self,g):
        g.apply(EndTurn(g.state.active_player));self.finish(g)
        g.apply(EndTurn(g.state.active_player))
    def portable(self,g,mode=None):
        snap=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(snap,registry('reader',mode))
        self.assertEqual(other.snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),registry('reader',mode)).snapshot(),snap)
        return other
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events'])
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        return s

    def test_a01_complete_faces_runes_tribes_and_explicit_finite_forms(self):
        r=registry();data=load_batch()
        self.assertEqual([x['record']['id'] for x in data['cards']],[ROOT,BEETLE])
        self.assertEqual(len(data['official_observations']),4)
        self.assertEqual(r.card(ROOT).metadata.runes.unholy,2)
        self.assertEqual(r.card(ROOT).metadata.tribes,('undead','dragon'))
        for n,cid in FORMS.items():
            d=r.card(cid);self.assertEqual((d.cost,d.attack,d.health),(n,n,n))
            self.assertIn(Keyword.TAUNT,d.keywords)
            if n<7:self.assertFalse(d.metadata.collectible);self.assertNotIn(cid,r.pool_cards)

    def test_a02_real_paid_root_death_seven_tokens_and_seven_form(self):
        g=self.game(board=(),hand=(ROOT,P+'kill'))
        root=self.play(g,ROOT);self.assertEqual(g.state.players[1].mana,3)
        self.play(g,P+'kill',root);self.assertEqual(len(self.units(g,cid=BEETLE)),7)
        self.assertEqual(len(g.state.death_history),1);self.own_start(g)
        self.assertEqual([e.card_id for e in self.units(g)],[ROOT]);self.portable(g)

    def test_a03_split_reads_captured_attack_not_health_and_reforms_survivor_count(self):
        g=self.game(hand=(P+'set3',P+'kill',P+'kill'))
        root=self.units(g)[0].id;self.play(g,P+'set3',root);self.play(g,P+'kill',root)
        self.assertEqual(len(self.units(g)),3);self.play(g,P+'kill',self.units(g)[1].id)
        self.own_start(g);e=self.units(g)[0]
        self.assertEqual((e.card_id,e.attack,e.health),(FORMS[2],2,2))
        self.assertEqual(g.state.death_history[0].attack,3)

    def test_a04_zero_attack_split_has_no_entry_or_rng_consumption(self):
        g=self.game(hand=(P+'zero',P+'kill'));root=self.units(g)[0].id
        self.play(g,P+'zero',root);before=g.snapshot()['rng_state'];self.play(g,P+'kill',root)
        self.assertEqual(self.units(g),[]);self.assertEqual(g.state.card_summon_history,[])
        self.assertEqual(g.snapshot()['rng_state'],before)

    def test_a05_int_max_attack_only_materializes_available_board_slots(self):
        g=self.game(board=(PLAIN,ROOT),hand=(P+'huge',P+'kill'));root=self.units(g)[1].id
        self.play(g,P+'huge',root);self.play(g,P+'kill',root)
        self.assertEqual(len(self.units(g,cid=BEETLE)),6)
        start=next(e for e in g.events if e.kind==SPLIT_START)
        self.assertEqual(start.amount,2147483647);self.assertEqual(len(g.state.card_summon_history),6)

    def test_a06_near_full_board_keeps_other_entities_and_stops_at_capacity(self):
        g=self.game(board=(PLAIN,)*6+(ROOT,));root=self.units(g)[-1].id
        self.play(g,P+'kill',root)
        self.assertEqual(len(self.units(g,cid=BEETLE)),1);self.assertEqual(len(self.units(g)),7)

    def test_a07_effect_trigger_two_distinct_deathrattles_each_keep_own_attack_count(self):
        g=self.game(hand=(P+'set2',P+'twice'));root=self.units(g)[0].id
        self.play(g,P+'set2',root);self.play(g,P+'twice',root)
        self.assertEqual(len(self.units(g,cid=BEETLE)),4)
        self.assertEqual([x.source_attack for x in g.state.deathrattle_history],[2,2])
        self.assertEqual(len([e for e in g.events if e.kind==SPLIT_START]),2)

    def test_a08_attributed_split_reuses_existing_summon_quantity(self):
        g=self.game(board=(P+'quantity',ROOT),hand=(P+'set2',P+'kill'))
        root=self.units(g)[1].id;self.play(g,P+'set2',root);self.play(g,P+'kill',root)
        self.assertEqual(len(self.units(g,cid=BEETLE)),4)
        self.assertEqual([len(x.deliveries) for x in g.state.card_summon_history],[2,2])

    def test_a09_summon_reactions_free_slots_and_do_not_clip_original_split_count(self):
        g=self.game(hand=(P+'set3',P+'kill'),mode='split_destroy');root=self.units(g)[1].id
        self.play(g,P+'set3',root);self.play(g,P+'kill',root)
        self.assertEqual(self.units(g,cid=BEETLE),[]);self.assertEqual(len(g.state.card_summon_history),3)
        self.assertEqual(len(g.state.death_history),4)

    def test_b01_friendly_family_merges_together_but_only_on_own_start(self):
        g=self.game(board=(BEETLE,BEETLE),hand=(),enemy=(BEETLE,))
        own=[e.id for e in self.units(g)]
        g.apply(EndTurn(1));self.assertEqual([e.id for e in self.units(g)],own)
        self.assertEqual([e.card_id for e in self.units(g,2)],[FORMS[1]])
        g.apply(EndTurn(2));self.assertEqual([e.card_id for e in self.units(g)],[FORMS[2]])
        self.assertEqual([e.card_id for e in self.units(g,2)],[FORMS[1]])

    def test_b02_beetle_buffs_are_not_summed_and_reform_is_fresh_summon(self):
        g=self.game(board=(BEETLE,BEETLE),hand=(P+'buff',))
        old=self.units(g)[0].id;self.play(g,P+'buff',old);self.own_start(g)
        e=self.units(g)[0];self.assertNotEqual(e.id,old)
        self.assertEqual((e.card_id,e.attack,e.health),(FORMS[2],2,2))
        self.assertFalse(any(isinstance(a,Attack) and a.attacker_id==e.id for a in g.legal_actions()))

    def test_b03_silenced_other_beetle_is_consumed_but_all_silenced_do_not_start(self):
        g=self.game(board=(BEETLE,BEETLE),hand=(P+'silence',))
        self.play(g,P+'silence',self.units(g)[0].id);self.own_start(g)
        self.assertEqual([e.card_id for e in self.units(g)],[FORMS[2]])
        h=self.game(board=(BEETLE,),hand=(P+'silence',));eid=self.units(h)[0].id
        self.play(h,P+'silence',eid);self.own_start(h);self.assertEqual(self.units(h)[0].id,eid)

    def test_b04_retirement_does_not_die_or_trigger_granted_deathrattle_reborn_corpses(self):
        g=self.game(board=(BEETLE,BEETLE),hand=(P+'gift',));ids=[e.id for e in self.units(g)]
        self.play(g,P+'gift',ids[0]);self.own_start(g)
        self.assertEqual(g.state.death_history,[])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.assertTrue(all(g.state.entities[eid].zone==Zone.SETASIDE for eid in ids))
        self.assertEqual([e.card_id for e in self.units(g)],[FORMS[2]])

    def test_b05_smaller_native_form_bounces_with_native_cost_and_replays(self):
        g=self.game(board=(BEETLE,BEETLE),hand=(P+'bounce',));self.own_start(g)
        eid=self.units(g)[0].id;self.play(g,P+'bounce',eid)
        self.assertEqual(g.state.entities[eid].card_id,FORMS[2]);self.assertEqual(g.registry.card(FORMS[2]).cost,2)
        self.play(g,FORMS[2]);self.assertEqual((self.units(g)[0].attack,self.units(g)[0].health),(2,2))

    def test_b06_smaller_native_base_current_copy_and_silence_keep_base_form(self):
        g=self.game(board=(BEETLE,BEETLE),hand=(P+'buff',P+'base',P+'copy',P+'silence'))
        self.own_start(g);eid=self.units(g)[0].id;self.play(g,P+'buff',eid)
        self.play(g,P+'base',eid);self.play(g,P+'copy',eid)
        self.assertEqual([(e.card_id,e.attack,e.health)for e in self.units(g)],[(FORMS[2],7,10),(FORMS[2],2,2),(FORMS[2],7,10)])
        self.play(g,P+'silence',eid);self.assertEqual((self.units(g)[0].attack,self.units(g)[0].health),(2,2))

    def test_b07_dormant_beetle_does_not_join_active_group(self):
        g=self.game(board=(BEETLE,BEETLE),hand=(P+'sleep',));self.play(g,P+'sleep')
        sleeper=self.units(g)[-1].id;self.own_start(g)
        self.assertFalse(g.state.entities[sleeper].active)
        self.assertEqual(sorted(e.card_id for e in self.units(g)),sorted((BEETLE,FORMS[2])))

    def test_b08_captured_source_control_change_cannot_reform_for_old_controller(self):
        g=self.game(board=(BEETLE,BEETLE),hand=(),mode='start_steal');self.own_start(g)
        self.assertEqual([e.card_id for e in self.units(g)][-1],FORMS[1])
        self.assertEqual([e.card_id for e in self.units(g,2)],[BEETLE])

    def test_b09_captured_start_trigger_survives_silence_during_same_window(self):
        g=self.game(board=(BEETLE,),hand=(),mode='start_silence');self.own_start(g)
        self.assertEqual([e.card_id for e in self.units(g)][-1],FORMS[1])

    def test_b10_smaller_form_natural_death_and_resurrection_keep_native_identity(self):
        g=self.game(board=(BEETLE,BEETLE),hand=(P+'silence',P+'kill',P+'resurrect'))
        self.own_start(g);eid=self.units(g)[0].id
        self.play(g,P+'silence',eid);self.play(g,P+'kill',eid);self.play(g,P+'resurrect')
        e=self.units(g)[0];self.assertEqual((e.card_id,e.attack,e.health),(FORMS[2],2,2))
        self.assertIn(Keyword.TAUNT,e.keywords);self.assertNotEqual(e.id,eid)
        self.portable(g)

    def test_b11_transform_excludes_original_beetle_and_reform_keeps_leftmost_slot(self):
        g=self.game(board=(PLAIN,BEETLE,BEETLE,PLAIN),hand=(P+'morph',))
        self.play(g,P+'morph',self.units(g)[1].id);self.own_start(g)
        self.assertEqual([e.card_id for e in self.units(g)],[PLAIN,PLAIN,FORMS[1],PLAIN])

    def test_b12_reform_uses_ordinary_attributed_summon_quantity(self):
        g=self.game(board=(P+'quantity',BEETLE,BEETLE),hand=());self.own_start(g)
        self.assertEqual([e.card_id for e in self.units(g)],[P+'quantity',FORMS[2],FORMS[2]])
        self.assertEqual(len(g.state.card_summon_history),1)
        self.assertEqual(len(g.state.card_summon_history[0].deliveries),2)

    def test_c01_split_wait_independent_restore_replay_and_failed_choice_rollback(self):
        g=self.game(hand=(P+'set3',P+'kill'),mode='split_wait');root=self.units(g)[1].id
        self.play(g,P+'set3',root);self.play(g,P+'kill',root)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,'split_wait')
        snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),snap);self.finish(g);self.finish(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.units(g,cid=BEETLE)),3)

    def test_c02_removal_wait_preserves_complete_native_group_before_entry(self):
        g=self.game(board=(BEETLE,BEETLE),hand=(),mode='remove_wait');self.own_start(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(self.units(g)),1)
        other=self.portable(g,'remove_wait');self.finish(g);self.finish(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.units(g)[-1].card_id,FORMS[2])

    def test_c03_native_entry_wait_preserves_original_retirement_and_child_root(self):
        g=self.game(board=(BEETLE,BEETLE),hand=(),mode='entry_wait');self.own_start(g)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g,'entry_wait');self.finish(g)
        self.assertEqual(self.units(g)[-1].card_id,FORMS[2])

    def test_c04_fully_rehashed_changed_split_acceptance_ordinal_is_rejected(self):
        g=self.game(hand=(P+'kill',),mode='split_wait');self.play(g,P+'kill',self.units(g)[1].id)
        s=json.loads(json.dumps(g.snapshot()))
        # Alter the independent private accepted receipt, with all outer hashes repaired.
        e=next(e for e in s['events'] if e['kind']==SPLIT_START)
        payload=json.loads(e['data']['work'])
        def corrupt(v):
            if type(v)is dict:
                for k,x in v.items():
                    if k=='ordinal':v[k]=1
                    else:corrupt(x)
            elif type(v)is list:
                for x in v:corrupt(x)
        corrupt(payload);e['data']['work']=json.dumps(payload)
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry('reader','split_wait'))

    def test_c05_fully_rehashed_native_group_count_cannot_change_accepted_form(self):
        g=self.game(board=(BEETLE,BEETLE),hand=(),mode='remove_wait');self.own_start(g)
        s=json.loads(json.dumps(g.snapshot()));event=next(e for e in s['events']if e['kind']==REFORM_START)
        event['data']['work']=event['data']['work'].replace(FORMS[2],FORMS[1])
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry('reader','remove_wait'))

    def test_c06_private_receipts_and_enemy_hand_never_enter_player_view(self):
        g=self.game(board=(BEETLE,BEETLE),hand=());self.own_start(g)
        for pid in (1,2):
            dto=json.dumps(g.observe(pid),sort_keys=True)
            for private in (REFORM_START,REFORM_CHILD,'rng_state','paid_hand_choice_boundary','resolution_frame'):
                self.assertNotIn(private,dto)

    def test_c07_both_seats_use_actual_owner_turn_and_native_form(self):
        g=self.game(board=(BEETLE,BEETLE),hand=(),seat=2);self.own_start(g)
        self.assertEqual([e.card_id for e in self.units(g,2)],[FORMS[2]])

    def test_c08_concession_during_original_split_wait_preserves_terminal_prefix(self):
        g=self.game(mode='split_wait');self.play(g,P+'kill',self.units(g)[1].id)
        g.apply(Concede(1));self.assertEqual(g.state.status,'finished')
        self.assertEqual(len(self.units(g,cid=BEETLE)),1);self.portable(g,'split_wait')

    def test_c09_completed_deathrattle_cannot_lose_all_private_split_receipts(self):
        g=self.game();self.play(g,P+'kill',self.units(g)[0].id)
        s=json.loads(json.dumps(g.snapshot()))
        for e in s['events']:
            if e['kind'] in (SPLIT_START,SPLIT_STEP,SPLIT_DONE):e['kind']='host_note'
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry('reader'))

    def test_c10_zero_count_receipt_still_rejects_future_cause_clock_or_source_epoch(self):
        g=self.game(hand=(P+'zero',P+'kill'));eid=self.units(g)[0].id
        self.play(g,P+'zero',eid);self.play(g,P+'kill',eid)
        for field in ('action','zone_epoch'):
            with self.subTest(field=field):
                s=json.loads(json.dumps(g.snapshot()));e=next(x for x in s['events']if x['kind']==SPLIT_START)
                work=json.loads(e['data']['work'])
                def alter(v):
                    count=0
                    if type(v)is dict:
                        for k,x in v.items():
                            if k==field:v[k]=10000;count+=1
                            else:count+=alter(x)
                    elif type(v)is list:
                        for x in v:count+=alter(x)
                    return count
                self.assertEqual(alter(work),1);e['data']['work']=json.dumps(work)
                with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry('reader'))
