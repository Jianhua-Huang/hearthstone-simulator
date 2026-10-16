"""One Vicious Slitherspear and shared real owner-turn numeric expiry."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, CastSpell, EndTurn, Game, KeywordExpiry,
    OwnerTurnExpiry, PlayCard, PlayerSetup, Registry, ResolutionError, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, Destroy, GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.model import Enchantment
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.turn_scheduling import QueueTurns, SkipTurns
from opening_fixtures import metadata
from hs_sim.targets import canonical_digest

CARD='TSC_827'
PIN='96042f385ff9a0c14292bbd9cb38cea449190ef06a877ee0cd64897f7adb88a9'


def evidence():
    data=json.loads((Path(__file__).resolve().parents[1]/'data/support/owner-turn-buff-expiry-basics.json').read_bytes())
    if canonical_digest(data)!=PIN:raise ValueError('Complete numeric owner expiry evidence changed')
    for row in data['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Raw numeric expiry card changed')
    return data


def registry():
    r=Registry('isolated-next-owner-start-numeric-buff-v1')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata(tribes=())))
    r.register_card(CardDefinition('other','Other',CardType.MINION,attack=1,health=8,metadata=metadata(tribes=())))
    raw=evidence()['records'][0]['data']
    def slither(c):
        if c.event.player_id!=c.player_id:return ()
        return (Buff(c.source_id,1,source_id=c.source_id,until_owner_turn_start=c.player_id),)
    r.register_behavior('slither',slither)
    r.register_card(CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],
        health=raw['health'],triggers=(TriggerSpec('spell_cast_finished','slither'),),
        metadata=metadata_from_record(raw)))
    def actor(c):return c.state.players[c.player_id].board[0]
    def until(c,target,attack=0,health=0,player=None):
        return Buff(target,attack,health,c.source_id,until_owner_turn_start=c.player_id if player is None else player)
    def waiting(c):
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),
            ChoiceOption('fault','Fail',(InvokeBehavior('late-fault',c.source_id,c.player_id),)),
        ),c.source_id),)
    scripts={
        'noop':lambda c:(),
        'auto':lambda c:(CastSpell(c.player_id,'noop',source_id=c.source_id),),
        'extra-own':lambda c:(QueueTurns((c.player_id,),c.source_id),),
        'extra-other':lambda c:(QueueTurns((3-c.player_id,3-c.player_id),c.source_id),),
        'skip-own':lambda c:(SkipTurns(c.player_id,1,c.source_id),),
        'global':lambda c:(Buff(actor(c),3,source_id=c.source_id,expires_turn=c.state.turn),),
        'health':lambda c:(until(c,actor(c),health=3),),
        'hurt':lambda c:(Damage(actor(c),1,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'control':lambda c:(ChangeControl(c.target_id,2),),
        'copy':lambda c:(CopyMinion(c.target_id,2),),
        'copy-base':lambda c:(CopyMinion(c.target_id,2,mode='base'),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'transform':lambda c:(Transform(c.target_id,'other'),),
        'sleep':lambda c:(MakeDormant(c.target_id,None,c.source_id),),
        'awake':lambda c:(AwakenMinion(actor(c),c.source_id),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'two':lambda c:(until(c,actor(c),2),until(c,c.state.players[c.player_id].board[1],2)),
        'foreign':lambda c:(until(c,c.state.players[3-c.player_id].board[0],2,player=c.player_id),),
        'wait':waiting,
        'fault':lambda c:(until(c,actor(c),2),InvokeBehavior('late-fault',c.source_id,c.player_id)),
    }
    targeted={'silence','control','copy','copy-base','bounce','transform','sleep','kill'}
    for name,body in scripts.items():
        r.register_behavior(name,body)
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,requires_target=name in targeted,metadata=metadata(tribes=())))
    r.register_behavior('late-fault',lambda c:(AddToHand(c.player_id,'unknown.owner-buff'),))
    def expired(c):
        board=c.state.players[c.player_id].board
        if c.event.target_id not in board[:2]:return ()
        return (GainArmor(c.player_id,sum(c.state.entities[i].attack for i in board[:2])),)
    r.register_behavior('expired',expired)
    r.register_card(CardDefinition('observer','Atomic expiry observer',CardType.MINION,health=5,
        triggers=(TriggerSpec('attachments_expired','expired'),),metadata=metadata(tribes=())))
    r.register_behavior('expire-wait',lambda c:waiting(c) if c.event.target_id==actor(c) else ())
    r.register_card(CardDefinition('waiter','Expiry pause',CardType.MINION,health=5,
        triggers=(TriggerSpec('attachments_expired','expire-wait'),),metadata=metadata(tribes=())))
    r.register_behavior('renew',lambda c:(until(c,actor(c),2),) if c.event.target_id==actor(c) else ())
    r.register_card(CardDefinition('renewer','Next interval observer',CardType.MINION,health=5,
        triggers=(TriggerSpec('attachments_expired','renew'),),metadata=metadata(tribes=())))
    return r


class OwnerTurnBuffExpiryBasicsTests(unittest.TestCase):
    def game(self,hand=(),*,board=(CARD,),enemy=(),enemy_hand=(),active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('other',)*8,mana=10,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,board=enemy,deck=('other',)*8,mana=10,max_mana=10),
        ),active_player=active,seed=43),registry())
    def actor(self,g):return g.state.players[1].board[0]
    def cast(self,g,name,target=None,p=1):
        eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(p,eid,target))
    def choose(self,g,name='ok'):
        q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(name,)))
    def attack_value(self,g,value,eid=None):self.assertEqual(g.state.entities[self.actor(g) if eid is None else eid].attack,value)
    def clocks(self,g,eid=None):
        return tuple(e.owner_turn_expiry for e in g.state.entities[self.actor(g) if eid is None else eid].enchantments if e.owner_turn_expiry is not None)
    def next_own(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));restored=Game.from_snapshot(saved,registry())
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return restored
    def reject(self,saved):
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())

    def test_raw_pin_single_native_and_shared_clock_identity(self):
        data=evidence();card=registry().card(CARD)
        self.assertEqual(data['new_real_card_adapters'],[CARD]);self.assertIs(OwnerTurnExpiry,KeywordExpiry)
        self.assertEqual((card.cost,card.attack,card.health,card.metadata.tribes),(1,1,3,('naga',)))

    def test_strict_explicit_player_and_separate_additive_numeric_attachment(self):
        for player in (True,0,3,1.0,'1'):
            with self.subTest(player=player),self.assertRaises(ValueError):Buff(1,1,until_owner_turn_start=player)
        with self.assertRaises(ValueError):Buff(1,1,expires_turn=1,until_owner_turn_start=1)
        clock=OwnerTurnExpiry(1,1,2,'turn_started',1)
        for changes in ({'cost':1},{'expires_turn':1},{'set_attack':2},{'remove_on_silence':False}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):Enchantment(1,owner_turn_expiry=clock,**changes)

    def test_multiple_native_spell_buffs_survive_opponent_turn_then_expire(self):
        g=self.game(('noop','noop'));self.cast(g,'noop');self.cast(g,'noop');self.attack_value(g,3)
        self.assertEqual([(e.player_id,e.owner_turn_index,e.created_owner_turn_id) for e in self.clocks(g)],[(1,2,1)]*2)
        g.apply(EndTurn(1));self.attack_value(g,3);g.apply(EndTurn(2));self.attack_value(g,1);self.assertEqual(self.clocks(g),());self.portable(g)

    def test_manual_parent_and_effect_spell_each_use_original_owner_deadline(self):
        g=self.game(('auto',));self.cast(g,'auto');self.attack_value(g,3)
        self.assertEqual(len(self.clocks(g)),2);self.next_own(g);self.attack_value(g,1);self.portable(g)

    def test_extra_own_start_expires_without_global_turn_parity(self):
        g=self.game(('extra-own',));self.cast(g,'extra-own');self.attack_value(g,2)
        g.apply(EndTurn(1));self.assertEqual((g.state.active_player,g.state.turn),(1,2));self.attack_value(g,1);self.portable(g)

    def test_multiple_other_turns_preserve_buff_until_actual_own_start(self):
        g=self.game(('extra-other',));self.cast(g,'extra-other');self.attack_value(g,2);g.apply(EndTurn(1))
        starts=0
        while g.state.active_player==2:
            self.attack_value(g,2);starts+=1;self.assertLess(starts,5);g.apply(EndTurn(2))
        self.assertGreaterEqual(starts,2);self.attack_value(g,1);self.portable(g)

    def test_skipped_own_slot_is_not_a_started_interval(self):
        g=self.game(('skip-own',));self.cast(g,'skip-own');g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(g.state.active_player,2);self.attack_value(g,2)
        self.assertEqual(sum(r.player_id==1 for r in g.state.owner_turn_history),1)
        g.apply(EndTurn(2));self.attack_value(g,1);self.portable(g)

    def test_explicit_owner_can_differ_from_current_carrier_and_active_player(self):
        g=self.game(enemy_hand=('foreign',),active=2);source=self.actor(g)
        self.cast(g,'foreign',p=2);self.attack_value(g,3,source)
        self.assertEqual(self.clocks(g,source)[0].player_id,2)
        g.apply(EndTurn(2));self.attack_value(g,3);g.apply(EndTurn(1));self.attack_value(g,1);self.portable(g)

    def test_global_end_turn_buff_keeps_original_lifetime(self):
        g=self.game(('global',));self.cast(g,'global');self.attack_value(g,5)
        g.apply(EndTurn(1));self.attack_value(g,2);g.apply(EndTurn(2));self.attack_value(g,1);self.portable(g)

    def test_health_expiry_uses_original_maximum_health_removal_clamp(self):
        g=self.game(('health','hurt'));source=self.actor(g);self.cast(g,'health');self.cast(g,'hurt')
        self.assertEqual(g.state.entities[source].health,5);self.next_own(g)
        self.assertEqual((g.state.entities[source].health,g.state.entities[source].max_health,g.state.entities[source].damage),(3,3,0));self.portable(g)

    def test_current_copy_preserves_bound_owner_and_base_copy_resets_numeric_clock(self):
        for mode in ('copy','copy-base'):
            with self.subTest(mode=mode):
                g=self.game(('noop',mode));source=self.actor(g);self.cast(g,'noop');clock=self.clocks(g)[0]
                self.cast(g,mode,source);copied=g.state.players[2].board[-1]
                self.attack_value(g,2 if mode=='copy' else 1,copied)
                self.assertEqual(self.clocks(g,copied),(clock,) if mode=='copy' else ())
                g.apply(EndTurn(1));self.attack_value(g,2 if mode=='copy' else 1,copied)
                g.apply(EndTurn(2));self.attack_value(g,1,copied);self.portable(g)

    def test_control_move_does_not_rebind_original_player(self):
        g=self.game(('noop','control'));source=self.actor(g);self.cast(g,'noop');self.cast(g,'control',source)
        self.attack_value(g,2,source);self.assertEqual(self.clocks(g,source)[0].player_id,1)
        self.next_own(g);self.attack_value(g,1,source);self.portable(g)

    def test_silence_bounce_and_transform_remove_numeric_clock(self):
        for action in ('silence','bounce','transform'):
            with self.subTest(action=action):
                g=self.game(('noop',action));source=self.actor(g);self.cast(g,'noop');self.cast(g,action,source)
                self.assertEqual(self.clocks(g,source),())
                if action=='bounce':self.cast(g,CARD)
                self.attack_value(g,1,source);self.portable(g)

    def test_dormant_carrier_still_expires_at_bound_start(self):
        g=self.game(('noop','sleep','awake'));source=self.actor(g);self.cast(g,'noop');self.cast(g,'sleep',source)
        self.next_own(g);self.assertEqual(self.clocks(g,source),());self.cast(g,'awake');self.attack_value(g,2,source)
        self.portable(g)

    def test_death_record_keeps_frozen_original_clock_after_live_cleanup(self):
        g=self.game(('noop','kill'));source=self.actor(g);self.cast(g,'noop');self.cast(g,'kill',source)
        record=next(r for r in g.state.death_history if r.entity_id==source)
        clock=next(e.owner_turn_expiry for e in record.enchantments if e.owner_turn_expiry is not None)
        self.next_own(g);self.assertEqual(self.clocks(g,source),())
        self.assertEqual(next(e.owner_turn_expiry for e in record.enchantments if e.owner_turn_expiry is not None),clock);self.portable(g)

    def test_all_numeric_expiries_are_removed_before_any_expiry_listener(self):
        g=self.game(('two',),board=(CARD,'other','observer'));self.cast(g,'two');self.next_own(g)
        self.attack_value(g,1);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4);self.portable(g)

    def test_expiry_wait_restores_after_atomic_removal_before_turn_start_events(self):
        g=self.game(('noop',),board=(CARD,'waiter'));self.cast(g,'noop');self.next_own(g)
        self.assertIsNotNone(g.state.pending_choice);self.attack_value(g,1)
        restored=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
        for branch in (g,restored):self.choose(branch);self.attack_value(branch,1);self.portable(branch)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_regrant_during_start_expiry_targets_later_genuine_start(self):
        g=self.game(('noop',),board=(CARD,'renewer'));self.cast(g,'noop');self.next_own(g)
        self.attack_value(g,3);self.assertEqual(self.clocks(g)[0].owner_turn_index,3);self.portable(g)

    def test_immediate_and_payload_wait_failures_preserve_original_numeric_state(self):
        g=self.game(('fault',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.cast(g,'fault')
        self.assertEqual(g.snapshot(),before)
        g=self.game(('wait',));self.cast(g,'wait');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_original_context_validates_its_own_creation_interval(self):
        g=self.game(('noop',));self.cast(g,'noop');source=self.actor(g);context=RuleContext(g.state,source,1)
        self.next_own(g);codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        restored=codec.decode(codec.encode(context));self.assertEqual(restored.state.entities[source].attack,2)
        bad=deepcopy(context.state);enchantment=bad.entities[source].enchantments[0]
        bad.entities[source].enchantments[0]=replace(enchantment,owner_turn_expiry=replace(enchantment.owner_turn_expiry,owner_turn_index=3))
        with self.assertRaises(ValueError):codec.encode(RuleContext(bad,source,1))

    def test_rehashed_wire_rejects_missing_wrong_clock_and_due_current_attachment(self):
        g=self.game(('noop',));self.cast(g,'noop');saved=g.snapshot();key=str(self.actor(g))
        for mode in ('missing','future','creation','global','end','bool'):
            with self.subTest(mode=mode):
                bad=deepcopy(saved);e=bad['state']['entities'][key]['enchantments'][0]
                if mode=='missing':del e['owner_turn_expiry']
                elif mode=='future':e['owner_turn_expiry']['owner_turn_index']=3
                elif mode=='creation':e['owner_turn_expiry']['created_turn']=2
                elif mode=='global':e['expires_turn']=1
                elif mode=='end':e['owner_turn_expiry']['boundary']='turn_ended'
                else:e['owner_turn_expiry']['player_id']=True
                self.reject(bad)
        old=deepcopy(saved['state']['entities'][key]['enchantments'][0]);self.next_own(g);bad=g.snapshot()
        bad['state']['entities'][key]['enchantments'].append(old);bad['state']['entities'][key]['attack_bonus']=1
        self.reject(bad)

    def test_public_interfaces_do_not_export_clock_facts_or_work_frames(self):
        g=self.game(('noop',));self.cast(g,'noop');before=g.snapshot()
        for p in (1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.for_player(p).legal_actions())
            for key in ('owner_turn_expiry','until_owner_turn_start','created_owner_turn_id','resolution_frame'):
                self.assertNotIn('"'+key+'"',public)
        self.assertEqual(g.snapshot(),before)
