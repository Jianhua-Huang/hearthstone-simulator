"""Native Hero Power damage addition through unchanged health/lifecycle code."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, DamageKind, EndTurn,
    Game, HealingKind, HealthFlow, HealthOp, HealthRule, IllegalAction, PlayCard,
    PlayerSetup, Registry, ResolutionError, Scenario, SelectChoice, SnapshotError,
    TargetSpec, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.dormancy import MakeDormant, AwakenMinion
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, Heal, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.health_rules import prepare_health
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]
NATIVE='AT_003'; POWER='HERO_08bp'
PIN='1d14d5280d78f2aa61da774cc775a54fb6f92abacb66be2c9140988825c33cf6'
RULE=HealthRule(HealthFlow.DAMAGE,HealthOp.ADD,1,source_relation='friendly',damage_kinds=(DamageKind.HERO_POWER,))


def evidence():
    packet=json.loads((ROOT/'data/support/hero-power-damage-basics.json').read_bytes())
    if canonical_digest(packet)!=PIN:raise ValueError('Native Hero Power damage evidence changed')
    return packet


def registry():
    r=Registry('hero-power-damage-independent-basics-v1');raw={x['id']:x for x in evidence()['records']}
    r.register_card(CardDefinition('hd.hero','Hero',CardType.HERO,health=30,metadata=metadata(collectible=False)))
    for cid in ('hd.body','hd.hidden'):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=2,health=15,metadata=metadata()))
    row=raw[NATIVE]
    r.register_card(CardDefinition(NATIVE,row['name'],CardType.MINION,cost=row['cost'],attack=row['attack'],health=row['health'],
        health_rules=(RULE,),metadata=metadata_from_record(row)))
    row=raw[POWER]
    r.register_behavior('hd.cb.native.power',lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.HERO_POWER),))
    r.register_card(CardDefinition(POWER,row['name'],CardType.HERO_POWER,cost=row['cost'],on_use='hd.cb.native.power',
        targeting=TargetSpec(),metadata=metadata_from_record(row)))
    ops={
        'silence':lambda c:(Silence(c.target_id),),
        'kill':lambda c:(Destroy(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'transform':lambda c:(Transform(c.target_id,'hd.body'),),
        'control':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'base-copy':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        'dormant':lambda c:(MakeDormant(c.target_id,None,c.source_id),),
        'awaken':lambda c:(AwakenMinion(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==NATIVE),c.source_id),),
        'spell':lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
    }
    untargeted={'awaken'}
    for key,body in ops.items():
        r.register_behavior('hd.cb.'+key,body)
        r.register_card(CardDefinition('hd.op.'+key,key+' diagnostic',CardType.SPELL,on_play='hd.cb.'+key,
            targeting=None if key in untargeted else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),metadata=metadata()))
    def fail(c):raise ResolutionError('Deliberate independent Hero Power damage rollback')
    r.register_behavior('hd.cb.fail',fail)
    r.register_behavior('hd.cb.silence-source',lambda c:tuple(Silence(i) for i in c.state.players[c.player_id].board
        if c.state.entities[i].card_id==NATIVE))
    def wait(c):
        if c.event.source_id is None or c.state.entities[c.event.source_id].card_id!=POWER:return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),
            ChoiceOption('silence','Silence source',(InvokeBehavior('hd.cb.silence-source',c.source_id,c.player_id),)),
            ChoiceOption('bad','Fail',(InvokeBehavior('hd.cb.fail',c.source_id,c.player_id),)),
        ),c.source_id),)
    r.register_behavior('hd.cb.wait',wait)
    for key,event in (('start','hero_power_started'),('result','health_resolved')):
        r.register_card(CardDefinition('hd.watch.'+key,key+' diagnostic',CardType.MINION,health=8,metadata=metadata(),
            triggers=(TriggerSpec(event,'hd.cb.wait'),)))
    return r


class HeroPowerDamageBasicTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy_board=(),*,enemy_hand=(),deck=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hd.hero',hand=hand,board=board,deck=deck or ('hd.body',)*10,mana=10,max_mana=10,hero_power_card_id=POWER),
            PlayerSetup('hd.hero',hand=enemy_hand,board=enemy_board,deck=('hd.body',)*10,mana=10,max_mana=10,hero_power_card_id=POWER)),seed=109),registry())
    def source(self,g,cid=NATIVE,player=1):
        return next(i for i in g.state.players[player].board if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        p=g.state.active_player;i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        return g.apply(PlayCard(p,i,target,len(g.state.players[p].board) if g.registry.card(cid).kind==CardType.MINION else None))
    def use(self,g,target=None):
        p=g.state.active_player
        return g.apply(UseHeroPower(p,g.state.players[p].hero_power_id,target or g.state.players[3-p].hero_id))
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def damage(self,result):return [e for e in result.events if e.kind=='damage_dealt']
    def check(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        variants=(Game.from_snapshot(saved,registry()),g.clone(),replay(build_replay(g),registry()))
        for other in variants:self.assertEqual(other.snapshot(),saved)
        return variants

    def test_complete_raw_pin_native_metadata_and_only_two_executable_adapters(self):
        packet=evidence();raw={x['id']:x for x in json.loads((ROOT/'data/extracted/cards.json').read_bytes())}
        self.assertEqual((len(packet['records']),packet['executable_representatives']),(5,[NATIVE,POWER]))
        self.assertEqual(packet['candidate_ids'],['AT_003','CORE_AT_003','PVPDR_SCH_Maget3','YOD_008'])
        for row in packet['records']:self.assertEqual(row,raw[row['id']])
        r=registry();m,p=r.card(NATIVE),r.card(POWER)
        self.assertEqual((m.name,m.cost,m.attack,m.health,m.metadata.tribes),('英雄之魂',2,3,2,('undead',)))
        self.assertEqual(m.health_rules,(RULE,));self.assertIsNone(m.battlecry);self.assertIsNone(m.deathrattle);self.assertIsNone(m.on_play)
        self.assertEqual((p.cost,p.kind,p.metadata.collectible),(2,CardType.HERO_POWER,False))
        self.assertTrue(all(i not in r.cards for i in packet['evidence_only']))

    def test_native_fireblast_base_one_and_one_or_two_physical_sources_add(self):
        for copies in range(3):
            with self.subTest(copies=copies):
                g=self.game(board=(NATIVE,)*copies);event=self.damage(self.use(g))[0]
                self.assertEqual(event.amount,1+copies)
                self.assertEqual(dict(event.data)['base_amount'],1)
                self.assertEqual(len(dict(event.data)['rule_ids']),copies)

    def test_native_public_command_pays_once_and_rejects_second_use(self):
        g=self.game(board=(NATIVE,));port=g.for_player(1);public=port.legal_actions()
        enemy=public['observation']['players'][1]['hero']['ref']
        action=next(a for a in public['actions'] if a['type']=='use_hero_power' and a.get('target')==enemy)
        result=port.submit({'revision':public['revision'],'action':action})
        self.assertTrue(result['accepted'],result['error']);self.assertEqual(g.state.players[1].mana,8)
        power=g.state.entities[g.state.players[1].hero_power_id]
        self.assertEqual((power.uses_this_turn,g.state.players[1].hero_power_uses_this_turn),(1,1))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28)
        saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.use(g)
        self.assertEqual(saved,g.snapshot());self.check(g)

    def test_source_relation_follows_controller_and_both_players_power(self):
        g=self.game(board=(NATIVE,),enemy_board=(NATIVE,NATIVE))
        self.assertEqual(self.damage(self.use(g))[0].amount,2)
        g.apply(EndTurn(1));self.assertEqual(self.damage(self.use(g))[0].amount,3);self.check(g)

    def test_bonus_applies_to_any_side_character_target(self):
        for seat,kind in ((1,'hero'),(2,'hero'),(1,'body'),(2,'body')):
            with self.subTest(seat=seat,kind=kind):
                g=self.game(board=(NATIVE,'hd.body'),enemy_board=('hd.body',))
                target=g.state.players[seat].hero_id if kind=='hero' else self.source(g,'hd.body',seat)
                self.assertEqual(self.damage(self.use(g,target))[0].amount,2)

    def test_kind_filter_excludes_spell_combat_effect_fatigue_minion_and_healing(self):
        g=self.game(hand=('hd.op.spell',),board=(NATIVE,'hd.body'));target=g.state.players[2].hero_id
        spell=g.state.players[1].hand[0];body=self.source(g,'hd.body');power=g.state.players[1].hero_power_id
        saved=g.snapshot()
        for kind,source in ((DamageKind.SPELL,spell),(DamageKind.COMBAT,body),(DamageKind.EFFECT,spell),
                (DamageKind.FATIGUE,None),(DamageKind.MINION_ABILITY,body)):
            packet=prepare_health(g.state,g.registry,Damage(target,1,source,kind));self.assertEqual(packet.amount,1);self.assertEqual(packet.rule_ids,())
        healing=prepare_health(g.state,g.registry,Heal(target,1,power,HealingKind.HERO_POWER))
        self.assertEqual((healing.flow,healing.amount,healing.rule_ids),(HealthFlow.HEALING,1,()))
        self.assertEqual(prepare_health(g.state,g.registry,Damage(target,1,power,DamageKind.HERO_POWER)).amount,2)
        self.assertEqual(saved,g.snapshot())

    def test_hand_and_deck_do_not_provide_bonus_but_normal_play_does(self):
        g=self.game(hand=(NATIVE,),deck=(NATIVE,)*10);target=g.state.players[2].hero_id
        power=g.state.players[1].hero_power_id
        self.assertEqual(prepare_health(g.state,g.registry,Damage(target,1,power,DamageKind.HERO_POWER)).amount,1)
        self.play(g,NATIVE);self.assertEqual(self.damage(self.use(g))[0].amount,2);self.check(g)

    def test_silencing_source_removes_bonus(self):
        g=self.game(('hd.op.silence',),(NATIVE,));self.play(g,'hd.op.silence',self.source(g))
        self.assertEqual(self.damage(self.use(g))[0].amount,1);self.check(g)

    def test_death_bounce_or_transform_removes_source_bonus(self):
        for operation in ('kill','bounce','transform'):
            with self.subTest(operation=operation):
                g=self.game(('hd.op.'+operation,),(NATIVE,));self.play(g,'hd.op.'+operation,self.source(g))
                self.assertEqual(self.damage(self.use(g))[0].amount,1)

    def test_transferred_source_only_modifies_new_controller_power(self):
        g=self.game(('hd.op.control',),(NATIVE,));source=self.source(g);self.play(g,'hd.op.control',source)
        self.assertEqual(self.damage(self.use(g))[0].amount,1)
        g.apply(EndTurn(1));self.assertEqual(self.damage(self.use(g))[0].amount,2);self.check(g)

    def test_current_copy_retains_silence_and_base_copy_recovers_native_rule(self):
        g=self.game(('hd.op.silence','hd.op.copy','hd.op.base-copy'),(NATIVE,));source=self.source(g)
        self.play(g,'hd.op.silence',source);self.play(g,'hd.op.copy',source);self.play(g,'hd.op.base-copy',source)
        self.assertEqual(self.damage(self.use(g))[0].amount,2);self.check(g)

    def test_dormancy_excludes_source_and_awakening_restores_existing_rule(self):
        g=self.game(('hd.op.dormant','hd.op.awaken'),(NATIVE,));self.play(g,'hd.op.dormant',self.source(g))
        target=g.state.players[2].hero_id;power=g.state.players[1].hero_power_id
        self.assertEqual(prepare_health(g.state,g.registry,Damage(target,1,power,DamageKind.HERO_POWER)).amount,1)
        self.play(g,'hd.op.awaken');self.assertEqual(self.damage(self.use(g))[0].amount,2);self.check(g)

    def test_waiting_start_then_source_silence_requotes_at_actual_damage_window(self):
        g=self.game(board=(NATIVE,'hd.watch.start'));self.use(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        variants=(g,*self.check(g))
        for other in variants:
            self.choose(other,'silence');self.assertEqual(other.state.entities[other.state.players[2].hero_id].health,29)
            self.assertEqual(other.state.players[1].mana,8);self.assertTrue(other.state.hero_power_history[-1].completed)
        for other in variants[1:]:self.assertEqual(other.snapshot(),g.snapshot())

    def test_waiting_health_result_keeps_already_dealt_damage_after_source_silence(self):
        g=self.game(board=(NATIVE,'hd.watch.result'));self.use(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28)
        variants=(g,*self.check(g))
        for other in variants:
            self.choose(other,'silence');self.assertEqual(other.state.entities[other.state.players[2].hero_id].health,28)
            self.assertEqual(sum(e.kind=='damage_dealt' for e in other.events),1)
            self.assertEqual(other.state.players[1].mana,8)
        for other in variants[1:]:self.assertEqual(other.snapshot(),g.snapshot())

    def test_failed_waiting_branch_rolls_back_without_repayment_or_extra_damage(self):
        g=self.game(board=(NATIVE,'hd.watch.result'));self.use(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(before,g.snapshot());self.choose(g)
        self.assertEqual(g.state.players[1].mana,8);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28);self.check(g)

    def test_shared_quote_and_later_native_root_use_current_live_sources(self):
        # Pure packet diagnostics, not a new native source or combination family.
        g=self.game(board=(NATIVE,));source=self.source(g);power=g.state.players[1].hero_power_id
        from hs_sim.engine.health_rules import rule_sources
        rows=rule_sources(g.state)
        packets=[prepare_health(g.state,g.registry,Damage(t,1,power,DamageKind.HERO_POWER),rules=rows)
            for t in (source,g.state.players[2].hero_id)]
        self.assertEqual([p.amount for p in packets],[2,2]);self.assertEqual(packets[0].rule_ids,packets[1].rule_ids)
        # Actual independent native roots observe later source removal.
        self.assertEqual(self.damage(self.use(g,source))[0].amount,2)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(self.damage(self.use(g))[0].amount,1);self.check(g)

    def test_waiting_snapshot_rejects_unknown_rule_fields(self):
        g=self.game(board=(NATIVE,'hd.watch.start'));self.use(g);saved=deepcopy(g.snapshot())
        source=self.source(g);row=next(a for a in saved['state']['entities'][str(source)]['abilities'] if a['kind']=='health_rule')
        row['health_rule']['unknown']=1
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as caught:Game.from_snapshot(saved,registry())
        self.assertNotIn('digest mismatch',str(caught.exception))

    def test_player_views_hide_opponent_hand_deck_and_internal_rule_frames(self):
        g=self.game(board=(NATIVE,'hd.watch.start'),enemy_hand=('hd.hidden',));self.use(g)
        for seat in (1,2):
            view=g.for_player(seat).observe();encoded=json.dumps(view,ensure_ascii=False)
            self.assertNotIn('health_rule',encoded);self.assertNotIn('work_queue',encoded);self.assertNotIn('acceptance_state',encoded)
            if seat==1:self.assertNotIn('hd.hidden',encoded)


if __name__=='__main__':unittest.main()
