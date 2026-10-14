"""Signed public Buff deltas; synthetic contracts, not a MIS_100 real adapter."""
from copy import deepcopy
import json,os
from pathlib import Path
import unittest

from hs_sim.engine import (AuraSpec,CardDefinition,CardType,EndTurn,Game,Keyword,
                          PlayCard,PlayerSetup,Registry,Resource,Scenario,SelectChoice,
                          SnapshotError,Zone)
from hs_sim.engine.effects import (Buff,ChoiceOption,CopyMinion,Damage,Destroy,GainArmor,
                                  RandomDamage,RemoveEnchantment,RequestChoice,SetStats,
                                  Silence,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash,state_from_dict


def death_choice(c):
    return [RequestChoice(c.player_id,(
        ChoiceOption('record',str(c.death.max_health),(GainArmor(c.player_id,1),)),
        ChoiceOption('other','other',(GainArmor(c.player_id,2),)),
    ),source_id=c.source_id)]


def wait_body(c):
    enemy=c.state.players[2].hero_id
    return [Damage(c.target_id,3,c.source_id),Buff(c.target_id,-5,-5,c.source_id),
        RequestChoice(c.player_id,(
            ChoiceOption('safe','safe',(Buff(c.target_id,health=-1,source_id=c.source_id),)),
            ChoiceOption('bad','bad',(Buff(c.target_id,health=-20,source_id=c.source_id),
                RandomDamage((enemy,),1,c.source_id),Buff(enemy,health=-1,source_id=999999))),
        ),source_id=c.source_id),Buff(c.target_id,health=2,source_id=c.source_id)]


def bad_body(c):
    enemy=c.state.players[2].hero_id
    return [RandomDamage(tuple(c.state.players[1].board),1,c.source_id),
            Buff(c.target_id,health=-20,source_id=c.source_id),
            Buff(enemy,health=-1,source_id=999999)]


def registry():
    r=Registry('negative-health-buff-isolated-v127')
    r.register_card(CardDefinition('hero','hero',CardType.HERO,health=30))
    for name,a,h in [('large',4,12),('medium',3,6),('small',2,3)]:
        r.register_card(CardDefinition(name,name,CardType.MINION,attack=a,health=h))
    r.register_behavior('death_choice',death_choice)
    r.register_card(CardDefinition('death','death',CardType.MINION,attack=2,health=4,deathrattle='death_choice'))
    r.register_card(CardDefinition('aura','aura',CardType.MINION,attack=1,health=4,auras=(AuraSpec(0,health=3),)))
    bodies={
        'neg':lambda c:[Buff(c.target_id,-5,-5,c.source_id)],
        'minus_one':lambda c:[Buff(c.target_id,health=-1,source_id=c.source_id)],
        'lethal':lambda c:[Buff(c.target_id,health=-20,source_id=c.source_id)],
        'hero_lethal':lambda c:[Buff(c.target_id,health=-35,source_id=c.source_id)],
        'hurt':lambda c:[Damage(c.target_id,3,c.source_id)],
        'set_ten':lambda c:[SetStats(c.target_id,health=10,source_id=c.source_id)],
        'remove_first':lambda c:[RemoveEnchantment(c.target_id,c.state.entities[c.target_id].enchantments[0].id)],
        'remove_middle':lambda c:[RemoveEnchantment(c.target_id,c.state.entities[c.target_id].enchantments[1].id)],
        'silence':lambda c:[Silence(c.target_id)],
        'kill':lambda c:[Destroy(c.target_id,c.source_id)],
        'temporary':lambda c:[Buff(c.target_id,health=-5,source_id=c.source_id,expires_turn=c.state.turn)],
        'copy_current':lambda c:[CopyMinion(c.target_id,c.player_id,mode='current')],
        'copy_base':lambda c:[CopyMinion(c.target_id,c.player_id,mode='base')],
        'transform':lambda c:[Transform(c.target_id,'small')],
        'wait':wait_body,
        'bad':bad_body,
    }
    for name,fn in bodies.items():
        r.register_behavior(name,fn)
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,requires_target=True))
    return r


def save_rejected(name,value):
    target=os.environ.get('HS_N127_EVIDENCE_DIR')
    if target:
        p=Path(target);p.mkdir(parents=True,exist_ok=True)
        (p/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def rehash(s):
    s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})


class NegativeHealthBuffTests(unittest.TestCase):
    def game(self,hand,board=('large',),enemy=()):
        self.r=registry()
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('small',)*5,mana=10,max_mana=10),
            PlayerSetup('hero',board=enemy,deck=('small',)*5,mana=10,max_mana=10),
        ),seed=127),self.r)

    def cast(self,g,name,target):
        cid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(1,cid,target))

    def target(self,g):return g.state.players[1].board[-1]

    def stats(self,g,target,maximum,damage,health,attack=None):
        e=g.state.entities[target]
        self.assertEqual((e.max_health,e.damage,e.health),(maximum,damage,health))
        if attack is not None:self.assertEqual(e.attack,attack)

    def no_health_effect(self,result):
        self.assertFalse(any(e.kind in ('damage_dealt','healed','health_resolved','lifesteal','damage_prevented') for e in result.events))

    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        restored=Game.from_snapshot(s,registry())
        self.assertEqual(restored.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        return restored

    def test_negative_delta_keeps_existing_damage_and_has_no_damage_or_heal_packet(self):
        g=self.game(('hurt','neg'));t=self.target(g)
        self.cast(g,'hurt',t);result=self.cast(g,'neg',t)
        self.stats(g,t,7,3,4,0);self.no_health_effect(result)
        e=g.state.entities[t]
        self.assertEqual((e.enchantments[-1].attack,e.enchantments[-1].health,e.enchantments[-1].set_health),(-5,-5,None))
        fact=next(e for e in result.events if e.kind=='stats_changed')
        self.assertEqual(dict(fact.data)['health_delta'],-5)

    def test_signed_add_set_add_and_middle_removal_use_acquisition_order(self):
        g=self.game(('neg','set_ten','neg','remove_middle'));t=self.target(g)
        for name in ('neg','set_ten','neg'):self.cast(g,name,t)
        self.stats(g,t,5,0,5)
        self.assertEqual([e.health for e in g.state.entities[t].enchantments],[-5,0,-5])
        self.cast(g,'remove_middle',t);self.stats(g,t,2,0,2)
        self.assertEqual([e.health for e in g.state.entities[t].enchantments],[-5,-5])

    def test_negative_delta_applies_before_health_aura_and_aura_removal_keeps_existing_clamp(self):
        g=self.game(('hurt','neg','kill'),board=('aura','medium'));a,t=g.state.players[1].board
        self.cast(g,'hurt',t);self.cast(g,'neg',t);self.stats(g,t,4,3,1)
        self.cast(g,'kill',a);self.stats(g,t,1,0,1)
        self.assertEqual([r.entity_id for r in g.state.death_history],[a])

    def test_silence_removes_negative_delta_keeps_damage_and_external_aura(self):
        g=self.game(('hurt','neg','silence'),board=('aura','large'));t=self.target(g)
        self.cast(g,'hurt',t);self.cast(g,'neg',t);self.stats(g,t,10,3,7)
        result=self.cast(g,'silence',t);self.stats(g,t,15,3,12,4)
        self.no_health_effect(result);self.assertFalse(g.state.entities[t].enchantments)

    def test_remove_negative_enchantment_restores_upper_limit_without_healing_damage(self):
        g=self.game(('hurt','neg','remove_first'));t=self.target(g)
        self.cast(g,'hurt',t);self.cast(g,'neg',t)
        result=self.cast(g,'remove_first',t);self.stats(g,t,12,3,9,4);self.no_health_effect(result)

    def test_expiring_negative_delta_keeps_damage_and_does_not_emit_healing(self):
        g=self.game(('hurt','temporary'));t=self.target(g)
        self.cast(g,'hurt',t);self.cast(g,'temporary',t);self.stats(g,t,7,3,4)
        result=g.apply(EndTurn(1));self.stats(g,t,12,3,9);self.no_health_effect(result)
        self.assertFalse(g.state.entities[t].enchantments)

    def test_current_copy_preserves_signed_order_damage_and_new_attachment_ids(self):
        g=self.game(('hurt','neg','minus_one','copy_current','remove_first'));t=self.target(g)
        for name in ('hurt','neg','minus_one','copy_current'):self.cast(g,name,t)
        new=self.target(g);self.assertNotEqual(new,t)
        self.stats(g,new,6,3,3)
        old=g.state.entities[t].enchantments;copied=g.state.entities[new].enchantments
        self.assertEqual([(e.attack,e.health,e.source_id) for e in old],[(e.attack,e.health,e.source_id) for e in copied])
        self.assertTrue(set(e.id for e in old).isdisjoint(e.id for e in copied))
        self.cast(g,'remove_first',new);self.stats(g,new,11,3,8);self.stats(g,t,6,3,3)
        self.portable(g)

    def test_base_copy_and_transform_reset_negative_delta_by_existing_lifecycle(self):
        g=self.game(('hurt','neg','copy_base','transform'));t=self.target(g)
        for name in ('hurt','neg','copy_base'):self.cast(g,name,t)
        new=self.target(g);self.stats(g,new,12,0,12,4)
        self.assertFalse(g.state.entities[new].enchantments)
        result=self.cast(g,'transform',t);self.stats(g,t,3,0,3,2);self.no_health_effect(result)
        self.assertFalse(g.state.entities[t].enchantments)
        self.assertFalse(g.state.death_history)

    def test_negative_maximum_is_not_clamped_to_one_and_freezes_health_state_death(self):
        g=self.game(('hurt','neg','lethal'));t=self.target(g)
        self.cast(g,'hurt',t);self.cast(g,'neg',t)
        result=self.cast(g,'lethal',t);self.no_health_effect(result)
        d=g.state.death_history[-1]
        self.assertEqual((d.entity_id,d.max_health,d.damage,d.cause.kind),(t,-13,3,'health_state'))
        self.assertEqual(d.cause.reason,'Buff');self.assertEqual([e.health for e in d.enchantments],[-5,-20])
        self.assertEqual(g.state.entities[t].zone,Zone.GRAVEYARD)
        self.portable(g)

    def test_negative_hero_health_uses_existing_terminal_checkpoint(self):
        g=self.game(('hero_lethal',));hero=g.state.players[2].hero_id
        result=self.cast(g,'hero_lethal',hero);self.no_health_effect(result)
        self.stats(g,hero,-5,0,-5)
        self.assertEqual((g.state.status,g.state.winner),('finished',1))
        self.assertEqual(g.state.entities[hero].death_cause.kind,'health_state')
        self.assertFalse(g.state.death_history)
        self.portable(g)

    def test_negative_aura_provider_death_cascades_in_distinct_frozen_batches(self):
        g=self.game(('neg','neg'),board=('aura','small'));a,t=g.state.players[1].board
        self.cast(g,'neg',t);self.stats(g,t,1,0,1)
        result=self.cast(g,'neg',a);self.no_health_effect(result)
        first,second=g.state.death_history
        self.assertEqual((first.entity_id,second.entity_id),(a,t))
        self.assertNotEqual(first.batch,second.batch)
        self.assertEqual((first.max_health,second.max_health),(-1,-2))
        self.assertEqual((first.cause.kind,second.cause.kind),('health_state','health_state'))
        self.assertIsNone(second.cause.source_id)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],2)
        self.portable(g)

    def test_lethal_negative_deathrattle_real_choice_restores_frozen_death_record(self):
        g=self.game(('neg',),board=('death',));t=self.target(g)
        self.cast(g,'neg',t);self.assertIsNotNone(g.state.pending_choice)
        d=g.state.death_history[-1];self.assertEqual((d.max_health,d.enchantments[-1].health),(-1,-5))
        restored=self.portable(g);clone=g.clone()
        for branch in (g,restored,clone):
            p=branch.state.pending_choice
            branch.apply(SelectChoice(p.player_id,p.id,('record',)))
            self.assertEqual(branch.state.death_history[-1],d)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.snapshot(),clone.snapshot())
        self.portable(g)

    def test_real_live_choice_restores_applied_negative_and_queued_negative_branch(self):
        g=self.game(('wait',));t=self.target(g)
        self.cast(g,'wait',t);self.stats(g,t,7,3,4)
        self.assertIsNotNone(g.snapshot()['resolution_frame'])
        restored=self.portable(g);clone=g.clone()
        for branch in (g,restored,clone):
            p=branch.state.pending_choice;branch.apply(SelectChoice(p.player_id,p.id,('safe',)))
            self.stats(branch,t,8,3,5)
            self.assertEqual([e.health for e in branch.state.entities[t].enchantments],[-5,-1,2])
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.snapshot(),clone.snapshot())
        self.portable(g)

    def test_failure_after_negative_death_rolls_back_damage_attachment_rng_and_history(self):
        g=self.game(('bad',));t=self.target(g);before=g.snapshot();history=g.history
        with self.assertRaises(ResolutionError):self.cast(g,'bad',t)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.history,history)
        self.assertFalse(g.state.death_history)

    def test_failed_selected_negative_lethal_branch_preserves_committed_wait_and_rng(self):
        g=self.game(('wait',));t=self.target(g);self.cast(g,'wait',t)
        before=g.snapshot();history=g.history;p=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(p.player_id,p.id,('bad',)))
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.history,history)
        self.stats(g,t,7,3,4);self.assertFalse(g.state.death_history)
        restored=self.portable(g);p=restored.state.pending_choice
        restored.apply(SelectChoice(p.player_id,p.id,('safe',)));self.stats(restored,t,8,3,5)

    def test_strict_archive_rejects_signed_type_cache_order_and_pending_payload_tampering(self):
        g=self.game(('neg','minus_one'));t=self.target(g)
        self.cast(g,'neg',t);self.cast(g,'minus_one',t);self.portable(g)
        for mode in ('bool','float','unknown','order','cache'):
            s=g.snapshot();e=s['state']['entities'][str(t)]
            if mode=='bool':e['enchantments'][0]['health']=True
            elif mode=='float':e['enchantments'][0]['health']=-5.0
            elif mode=='unknown':e['enchantments'][0]['unregistered']=1
            elif mode=='order':e['enchantments'].reverse()
            else:e['health_bonus']-=1
            rehash(s);save_rejected('signed-archive-'+mode,s)
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())
            # The primitive decoder checks operand types; attachment ordering
            # is validated by Game.from_snapshot's full-state invariants.
            if mode in ('bool','float','unknown'):
                with self.assertRaises(ValueError):state_from_dict(s['state'])
        wait=self.game(('wait',));self.cast(wait,'wait',self.target(wait))
        def payloads(v):
            if isinstance(v,dict):
                if v.get('type')=='hs_sim.engine.effects.Buff':yield v
                for x in v.values():yield from payloads(x)
            elif isinstance(v,list):
                for x in v:yield from payloads(x)
        for mode in ('bool','float','missing'):
            s=wait.snapshot();ps=list(payloads(s['resolution_frame']));self.assertTrue(ps)
            if mode=='missing':del ps[0]['fields']['health']
            else:ps[0]['fields']['health']=True if mode=='bool' else -1.0
            rehash(s);save_rejected('signed-pending-'+mode,s)
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())


if __name__=='__main__':unittest.main()
