"""Bounded synthetic DAMAGE floor combinations, not a Riot card adapter."""
from dataclasses import replace
import json, os
from pathlib import Path
import unittest
from hs_sim.engine import (Attack, AuraSpec, CardDefinition, CardType, CostSpec, DamageKind,
    EndTurn, Game, HealthFlow, HealthLayer, HealthOp, HealthRule, HealthLossReplacementSpec,
    Keyword, PaymentType, PlayCard, PlayerSetup, Registry, ResolutionError, Scenario,
    SelectChoice, SnapshotError, SpellSchool, StatRelationSpec, TriggerSpec, Zone, LoseHealth)
from hs_sim.engine.effects import (AddCostModifier, Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    DamageBatch, Destroy, EquipWeapon, GainArmor, GrantHealthRule, GrantKeyword, Heal,
    InvokeBehavior, RandomDamage, RequestChoice, Silence, Summon, Transform)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.health_outcomes import health_result, is_honorable_kill, is_overkill
from hs_sim.engine.health_floors import validate_frame_references
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.replay import build_replay, replay


def floor(value=1, **kw):
    return HealthRule(HealthFlow.DAMAGE,HealthOp.FLOOR,value,layer=HealthLayer.TARGET,**kw)
SELF=floor(target_relation='self')
FRIEND=floor(target_relation='friendly',target_kinds=(CardType.MINION,))
HERO78=floor(78,target_relation='self',target_kinds=(CardType.HERO,))


def registry():
    r=Registry('isolated-v146-damage-current-hp-floor-local-M6')
    cards=(CardDefinition('hero','Hero',CardType.HERO,health=80),
        CardDefinition('floorhero','Hero floor',CardType.HERO,health=80,health_rules=(HERO78,)),
        CardDefinition('plain','Plain',CardType.MINION,attack=2,health=10),
        CardDefinition('self','Self',CardType.MINION,attack=3,health=10,health_rules=(SELF,)),
        CardDefinition('one','One',CardType.MINION,health=1,health_rules=(SELF,)),
        CardDefinition('shield','Shield',CardType.MINION,health=1,health_rules=(SELF,),keywords=(Keyword.DIVINE_SHIELD,)),
        CardDefinition('immune','Immune',CardType.MINION,health=1,health_rules=(SELF,),keywords=(Keyword.IMMUNE,)),
        CardDefinition('friend','Friend',CardType.MINION,health=2,health_rules=(FRIEND,)),
        CardDefinition('hero_guard','Hero guard',CardType.MINION,health=2,
            health_rules=(floor(1,target_relation='friendly',target_kinds=(CardType.HERO,)),)),
        CardDefinition('high','High floor',CardType.MINION,health=3,
            health_rules=(floor(5,target_relation='friendly',target_kinds=(CardType.MINION,)),)),
        CardDefinition('over','Over max floor',CardType.MINION,health=3,health_rules=(floor(100,target_relation='self'),)),
        CardDefinition('life','Poison life',CardType.MINION,health=10,keywords=(Keyword.POISONOUS,Keyword.LIFESTEAL)),
        CardDefinition('replace','Replace',CardType.MINION,health=6,health_loss_replacements=(HealthLossReplacementSpec(),)),
        CardDefinition('actor','Actor',CardType.MINION,health=8,keywords=(Keyword.CHARGE,),
            stat_relations=(StatRelationSpec(),),health_rules=(SELF,)),
        CardDefinition('defender','Defender',CardType.MINION,health=5,
            stat_relations=(StatRelationSpec(),),health_rules=(SELF,)),
        CardDefinition('aura','Aura',CardType.MINION,health=3,auras=(AuraSpec(health=2),)),
        CardDefinition('reborn','Reborn',CardType.MINION,health=3,keywords=(Keyword.REBORN,),health_rules=(SELF,)),
        CardDefinition('redirect','Redirect',CardType.MINION,health=5,health_rules=(SELF,
            HealthRule(HealthFlow.DAMAGE,HealthOp.REDIRECT,layer=HealthLayer.TARGET,
                target_relation='friendly',target_kinds=(CardType.HERO,),redirect_to='self'),)),
        CardDefinition('convert_h','Convert healing',CardType.MINION,health=8,health_rules=(
            HealthRule(HealthFlow.HEALING,HealthOp.CONVERT,target_relation='friendly'),)),
        CardDefinition('convert_d','Convert damage',CardType.MINION,health=8,health_rules=(
            HealthRule(HealthFlow.DAMAGE,HealthOp.CONVERT,target_relation='friendly'),)),
        CardDefinition('filter','Filter',CardType.MINION,health=3,health_rules=(
            floor(1,target_relation='friendly',damage_kinds=(DamageKind.SPELL,),schools=(SpellSchool.FIRE,)),)),
        CardDefinition('numbers','Numbers',CardType.MINION,health=3,health_rules=(
            HealthRule(HealthFlow.DAMAGE,HealthOp.ADD,2),
            HealthRule(HealthFlow.DAMAGE,HealthOp.SCALE,2),
            HealthRule(HealthFlow.DAMAGE,HealthOp.CAP,12,layer=HealthLayer.TARGET)),),
        CardDefinition('fusion','Fusion',CardType.MINION,health=5,keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',)))
    for card in cards:r.register_card(card)
    def declare(c):
        if c.event.player_id!=1:return []
        return [RequestChoice(1,(ChoiceOption('change','Change',
            (Buff(c.event.source_id,health=-3,source_id=c.source_id),)),),source_id=c.source_id)]
    r.register_behavior('declare',declare)
    r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=6,
        triggers=(TriggerSpec('attack_declared','declare'),)))
    def inner(c):
        copy=c.state.players[1].board[-1]
        return [RequestChoice(1,(ChoiceOption('inner','Inner',
            (GrantHealthRule(copy,SELF,c.source_id),Damage(copy,100,c.source_id))),),source_id=c.source_id)]
    r.register_behavior('inner',inner)
    def waiting(c):
        good=(GrantHealthRule(c.target_id,SELF,c.source_id,c.state.turn+2),
            CopyMinion(c.target_id,1),InvokeBehavior('inner',player_id=1,source_id=c.source_id))
        bad=(GrantHealthRule(c.target_id,SELF,c.source_id),Damage(c.target_id,100,c.source_id),
            Destroy(c.state.players[1].board[-1],c.source_id),
            RandomDamage((c.state.players[2].hero_id,),3,c.source_id),EquipWeapon(1,'plain'))
        return [RequestChoice(1,(ChoiceOption('good','Good',good),ChoiceOption('bad','Bad',bad)),source_id=c.source_id)]
    def after_result(c):
        return [Silence(c.target_id),RequestChoice(1,(ChoiceOption('ok','Ok',
            (GainArmor(1,1),)),),source_id=c.source_id)]
    r.register_behavior('after_result',after_result)
    def stale(c):
        old=c.target_id
        return [Destroy(old,c.source_id),Summon(1,'plain'),RequestChoice(1,(ChoiceOption('ok','Ok',
            (GrantHealthRule(old,SELF,c.source_id),)),),source_id=c.source_id)]
    def provider_batch(c):
        provider=c.state.players[1].board[0];hero=c.state.players[1].hero_id
        return [DamageBatch((Damage(provider,3,c.source_id),Damage(hero,100,c.source_id))),Damage(hero,3,c.source_id)]
    def poison(c):
        source=c.state.players[1].board[0]
        return [Damage(c.state.players[1].hero_id,5,c.source_id),
            Damage(c.target_id,100,source,DamageKind.MINION_ABILITY)]
    scripts={
        'hit':lambda c:[Damage(c.target_id,10,c.source_id)],
        'fixed_hit':lambda c:[Damage(c.state.players[2].board[0],10,c.source_id)],
        'hit6':lambda c:[Damage(c.target_id,6,c.source_id)],
        'hit1':lambda c:[Damage(c.target_id,1,c.source_id)],
        'zero':lambda c:[Damage(c.target_id,0,c.source_id)],
        'many':lambda c:[DamageBatch(tuple(Damage(c.target_id,6,c.source_id) for _ in range(3)))],
        'many10':lambda c:[DamageBatch((Damage(c.target_id,10,c.source_id),Damage(c.target_id,10,c.source_id)))],
        'fire':lambda c:[Damage(c.target_id,10,c.source_id,DamageKind.SPELL)],
        'heal':lambda c:[Heal(c.target_id,10,c.source_id)],
        'silence':lambda c:[Silence(c.target_id)],
        'kill':lambda c:[Destroy(c.target_id,c.source_id)],
        'grant':lambda c:[GrantHealthRule(c.target_id,SELF,c.source_id)],
        'temp':lambda c:[GrantHealthRule(c.target_id,SELF,c.source_id,c.state.turn)],
        'copy':lambda c:[CopyMinion(c.target_id,2)],
        'copybase':lambda c:[CopyMinion(c.target_id,2,mode='base')],
        'steal':lambda c:[ChangeControl(c.target_id,2)],
        'plainform':lambda c:[Transform(c.target_id,'plain')],
        'floorform':lambda c:[Transform(c.target_id,'self')],
        'negative':lambda c:[Buff(c.target_id,health=-20,source_id=c.source_id)],
        'loss':lambda c:[LoseHealth(c.target_id,4,c.source_id)],
        'setup_low':lambda c:[Damage(c.target_id,9,c.source_id),GrantHealthRule(c.target_id,floor(5,target_relation='self'),c.source_id)],
        'pay_setup':lambda c:[AddCostModifier(1,CostSpec(payment=PaymentType.HEALTH),1)],
        'wait':waiting,'stale':stale,'provider_batch':provider_batch,'poison':poison,
        'capture_wait':lambda c:[Damage(c.target_id,10,c.source_id,on_result='after_result')],
    }
    for name,behavior in scripts.items():
        r.register_behavior(name,behavior)
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,requires_target=name!='fixed_hit',
            spell_school=SpellSchool.FIRE if name=='fire' else None))
    r.register_card(CardDefinition('pay','HP payment',CardType.SPELL,cost=79))
    return r


class HealthFloorTests(unittest.TestCase):
    def blob(self,value,label):
        if not os.environ.get('V146_INPUT_DIR'):return
        p=Path(os.environ['V146_INPUT_DIR'])/self._testMethodName;p.mkdir(parents=True,exist_ok=True)
        n=getattr(self,'input_number',0)+1;self.input_number=n
        (p/(f'{n:03d}-'+label+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    def game(self,hand=(),board=(),enemy=('self',),hero='hero',enemyhero='hero',armor=0,enemyarmor=0):
        g=Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,armor=armor,mana=10,max_mana=10,deck=('plain',)*6),
            PlayerSetup(enemyhero,board=enemy,armor=enemyarmor,mana=10,max_mana=10,deck=('plain',)*6)),seed=146),registry())
        self.blob(g.snapshot(),'initial');return g
    def cast(self,g,name,target):
        self.blob(g.snapshot(),'before-'+name);p=g.state.active_player
        i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(p,i,target))
    def choose(self,g,name):
        self.blob(g.snapshot(),'before-choice-'+name);p=g.state.pending_choice
        return g.apply(SelectChoice(p.player_id,p.id,(name,)))
    def results(self,r):return [health_result(e) for e in r.events if e.kind=='health_resolved']
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));self.blob(s,'portable')
        restored=Game.from_snapshot(s,registry());self.assertEqual(restored.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        return restored
    def private(self,g):
        raw=json.dumps(g.observe(1))+json.dumps(g.observe(2))+json.dumps(g.for_player(1).legal_actions())
        for word in ('floor_plan','floor_prevented','HealthFloorPlan','next_attachment_id','source_id','resolution_frame'):
            self.assertNotIn('"'+word+'"',raw)
        for p in (1,2):
            for e in g.player_events(p):self.assertNotIn('floor_plan',e)
    def reject(self,s,label):
        s['events_hash']=canonical_hash(s['events'])
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        self.blob(s,'rehashed-negative-'+label)
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_repeated_target_batch_live_allowance_and_positive_full_prevention(self):
        g=self.game(('many',));t=g.state.players[2].board[0]
        result=self.cast(g,'many',t);rows=self.results(result)
        self.assertEqual([(r.health_before,r.damage_dealt,r.floor_prevented,r.modified_amount) for r in rows],
            [(10,6,0,6),(4,3,3,6),(1,0,6,6)])
        self.assertEqual(g.state.entities[t].health,1)
        self.assertEqual([e.amount for e in result.events if e.kind=='damage_dealt'],[6,3])
        self.assertTrue(all(r.prevention is None for r in rows));self.private(g);self.portable(g)

    def test_partial_armor_floor_and_live_second_packet_conservation(self):
        g=self.game(('many10',),enemy=(),enemyhero='floorhero',enemyarmor=4)
        h=g.state.players[2].hero_id;rows=self.results(self.cast(g,'many10',h))
        self.assertEqual([(r.armor_absorbed,r.health_lost,r.floor_prevented) for r in rows],[(4,2,4),(0,0,10)])
        self.assertEqual((g.state.entities[h].health,g.state.entities[h].armor),(78,0));self.portable(g)

    def test_shield_immune_and_original_zero_precede_floor(self):
        for face,expected in (('shield','divine_shield'),('immune','immune')):
            g=self.game(('fixed_hit','fixed_hit'),enemy=(face,));t=g.state.players[2].board[0]
            first=self.results(self.cast(g,'fixed_hit',None))[0]
            self.assertEqual((first.prevention,first.floor_prevented,first.damage_dealt),(expected,0,0))
            second=self.results(self.cast(g,'fixed_hit',None))[0]
            self.assertEqual(second.floor_prevented,10 if face=='shield' else 0)
            self.assertEqual(second.prevention,None if face=='shield' else 'immune');self.portable(g)
        g=self.game(('zero',),enemy=('shield',));t=g.state.players[2].board[0]
        self.assertEqual(self.results(self.cast(g,'zero',t))[0].prevention,'zero_damage')
        self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[t].keywords)

    def test_maximum_row_union_and_source_death_batch_freeze(self):
        g=self.game(('hit',),enemy=('friend','high','plain'));t=g.state.players[2].board[-1]
        r=self.results(self.cast(g,'hit',t))[0]
        self.assertEqual((r.health_after,r.floor_plan.floor,len(r.floor_plan.rows)),(5,5,2))
        self.assertEqual(tuple(row.ability.id for row in r.floor_plan.rows),tuple(sorted(row.ability.id for row in r.floor_plan.rows)))
        self.portable(g)
        g=self.game(('provider_batch',),board=('hero_guard',),enemy=());h=g.state.players[1].hero_id
        result=self.cast(g,'provider_batch',h);rows=self.results(result)
        self.assertEqual([(r.damage_dealt,r.floor_prevented) for r in rows],[(3,0),(79,21),(3,0)])
        self.assertIsNotNone(rows[1].floor_plan);self.assertIsNone(rows[2].floor_plan)
        self.assertEqual(g.state.death_history[0].card_id,'hero_guard');self.portable(g)

    def test_routing_conversion_numeric_and_kind_filters_accept_final_recipient(self):
        g=self.game(('hit',),enemy=('redirect','numbers'));h=g.state.players[2].hero_id;t=g.state.players[2].board[0]
        r=self.results(self.cast(g,'hit',h))[0]
        self.assertEqual((r.target_id,r.modified_amount,r.health_lost,r.floor_prevented),(t,12,4,8));self.portable(g)
        g=self.game(('heal',),enemy=('convert_h','self'));t=g.state.players[2].board[-1]
        r=self.results(self.cast(g,'heal',t))[0];self.assertTrue(r.converted)
        self.assertEqual((r.health_lost,r.floor_prevented),(9,1));self.portable(g)
        g=self.game(('hit','heal'),enemy=('convert_d','self'));t=g.state.players[2].board[-1]
        r=self.results(self.cast(g,'hit',t))[0];self.assertIsNone(r.floor_plan);self.assertEqual(r.flow,'healing')
        g=self.game(('fire','hit'),enemy=('filter','plain'));t=g.state.players[2].board[-1]
        self.assertIsNotNone(self.results(self.cast(g,'fire',t))[0].floor_plan)
        self.assertIsNone(self.results(self.cast(g,'hit',t))[0].floor_plan)

    def test_actual_poison_lifesteal_and_death_result_facts(self):
        g=self.game(('poison',),board=('life',),enemy=('one',));t=g.state.players[2].board[0];h=g.state.players[1].hero_id
        result=self.cast(g,'poison',t);r=self.results(result)[-1]
        self.assertEqual((r.damage_dealt,r.floor_prevented,r.doomed_after),(0,100,False))
        self.assertFalse(any(e.kind=='lifesteal' for e in result.events));self.assertEqual(g.state.entities[h].health,75)
        g=self.game(('poison',),board=('life',),enemy=('self',));t=g.state.players[2].board[0]
        result=self.cast(g,'poison',t);poison=[r for r in self.results(result) if r.target_id==t][0]
        self.assertEqual((poison.health_lost,poison.floor_prevented,poison.doomed_after),(9,91,True))
        self.assertEqual(next(e.amount for e in result.events if e.kind=='lifesteal'),9)
        record=g.state.death_history[-1];self.assertEqual(record.cause.kind,'poison')
        self.assertEqual(record.cause.health_result,poison)
        event=next(e for e in result.events if e.kind=='health_resolved' and e.target_id==t)
        self.assertFalse(is_honorable_kill(event,poison.source_id));self.assertFalse(is_overkill(event,poison.source_id));self.portable(g)

    def test_health_loss_replacement_receives_post_floor_live_allowed_quantity(self):
        g=self.game(('many10',),board=('replace',),hero='floorhero',enemy=(),armor=1);h=g.state.players[1].hero_id
        result=self.cast(g,'many10',h);rows=self.results(result)
        self.assertEqual([(r.armor_absorbed,r.health_replaced,r.health_lost,r.floor_prevented) for r in rows],[(1,2,0,7),(0,4,0,6)])
        self.assertEqual((g.state.entities[h].health,g.state.entities[h].max_health),(86,86))
        self.assertEqual([e.amount for e in result.events if e.kind=='health_loss_replaced'],[2,4]);self.portable(g)

    def test_prepared_combat_reciprocal_values_freeze_derived_attack(self):
        g=self.game(board=('actor',),enemy=('defender',));a=g.state.players[1].board[0];d=g.state.players[2].board[0]
        result=g.apply(Attack(1,a,d));rows=self.results(result)
        self.assertEqual([(r.modified_amount,r.damage_dealt,r.floor_prevented) for r in rows],[(8,4,4),(5,5,0)])
        self.assertEqual((g.state.entities[a].attack,g.state.entities[d].attack),(3,1));self.portable(g)

    def test_real_declared_wait_changes_health_before_preparation_delivery(self):
        g=self.game(board=('actor','watcher'),enemy=('defender',));a=g.state.players[1].board[0];d=g.state.players[2].board[0]
        g.apply(Attack(1,a,d));self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g)
        for branch in (g,restored):
            result=self.choose(branch,'change');rows=self.results(result)
            self.assertEqual([(r.modified_amount,r.damage_dealt,r.floor_prevented) for r in rows],[(5,4,1),(5,4,1)])
            self.assertEqual((branch.state.entities[a].attack,branch.state.entities[d].attack),(1,1));self.portable(branch)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_copy_current_base_independent_dynamic_rows_silence_and_regrant(self):
        g=self.game(('grant','hit6','copy','copybase','silence','grant'),board=('plain',),enemy=());t=g.state.players[1].board[0]
        self.cast(g,'grant',t);self.cast(g,'hit6',t);old=next(a for a in g.state.entities[t].abilities if a.kind=='health_rule')
        self.cast(g,'copy',t);copy=g.state.players[2].board[-1]
        row=next(a for a in g.state.entities[copy].abilities if a.kind=='health_rule')
        self.assertNotEqual(row.id,old.id);self.assertEqual(row.source_id,old.source_id)
        self.assertEqual(g.state.entities[copy].health,4)
        self.cast(g,'copybase',t);base=g.state.players[2].board[-1]
        self.assertFalse(any(a.kind=='health_rule' for a in g.state.entities[base].abilities))
        self.assertEqual(g.state.entities[base].health,10)
        self.cast(g,'silence',copy);self.cast(g,'grant',copy)
        self.assertEqual(len([a for a in g.state.entities[copy].abilities if a.kind=='health_rule']),1);self.portable(g)

    def test_controller_rebinding_transform_epoch_and_dynamic_expiry(self):
        g=self.game(('steal','hit','plainform','floorform','hit'),board=('friend',),enemy=('plain',));f=g.state.players[1].board[0];t=g.state.players[2].board[0]
        self.cast(g,'steal',f);r=self.results(self.cast(g,'hit',t))[0];self.assertEqual(r.health_after,1)
        epoch=g.state.entities[f].zone_epoch;self.cast(g,'plainform',f);self.assertGreater(g.state.entities[f].zone_epoch,epoch)
        self.cast(g,'floorform',f);r=self.results(self.cast(g,'hit',f))[0];self.assertEqual(r.health_after,1);self.portable(g)
        g=self.game(('temp','hit','hit'),board=('plain',),enemy=());t=g.state.players[1].board[0]
        self.cast(g,'temp',t);self.cast(g,'hit',t);self.assertEqual(g.state.entities[t].health,1)
        g.apply(EndTurn(1));g.apply(EndTurn(2));r=self.results(self.cast(g,'hit',t))[0]
        self.assertIsNone(r.floor_plan);self.assertEqual(g.state.entities[t].zone,Zone.GRAVEYARD);self.portable(g)

    def test_signed_buff_aura_removal_below_floor_destroy_and_hp_payment_axes(self):
        g=self.game(('hit','kill','hit'),board=('self','aura'),enemy=());t,a=g.state.players[1].board
        self.cast(g,'hit',t);self.assertEqual(g.state.entities[t].health,2)
        # Existing aura removal clamps remaining HP to new max; DAMAGE floor
        # neither changes that policy nor heals/clears damage received.
        removed=self.cast(g,'kill',a)
        self.assertEqual((g.state.entities[t].health,g.state.entities[t].max_health,g.state.entities[t].damage),(2,10,8))
        self.assertFalse(any(e.kind in ('health_resolved','healed') for e in removed.events))
        self.cast(g,'hit',t);self.assertEqual(g.state.entities[t].health,1);self.portable(g)
        g=self.game(('setup_low','hit'),enemy=('plain',));t=g.state.players[2].board[0]
        self.cast(g,'setup_low',t);r=self.results(self.cast(g,'hit',t))[0]
        self.assertEqual((r.health_before,r.health_after,r.floor_prevented),(1,1,10));self.portable(g)
        g=self.game(('hit','kill','negative'),board=('over','self','self'),enemy=());a,b,c=g.state.players[1].board
        r=self.results(self.cast(g,'hit',a))[0];self.assertEqual((r.health_before,r.health_after),(3,3))
        self.cast(g,'kill',b);self.cast(g,'negative',c)
        self.assertEqual((g.state.entities[b].zone,g.state.entities[c].zone),(Zone.GRAVEYARD,Zone.GRAVEYARD));self.portable(g)
        g=self.game(('pay_setup','pay','loss'),hero='floorhero',enemy=());h=g.state.players[1].hero_id
        self.cast(g,'pay_setup',h);self.cast(g,'pay',None);self.assertEqual(g.state.entities[h].health,1)
        self.cast(g,'loss',h);self.assertLess(g.state.entities[h].health,1);self.assertEqual(g.state.status,'finished');self.portable(g)
        g=self.game(('kill','hit'),board=('reborn',),enemy=());old=g.state.players[1].board[0]
        self.cast(g,'kill',old);new=g.state.players[1].board[0]
        self.assertNotEqual(old,new);self.assertEqual(g.state.entities[new].health,1)
        r=self.results(self.cast(g,'hit',new))[0];self.assertEqual((r.damage_dealt,r.floor_prevented),(0,10));self.portable(g)

    def test_nested_real_waiting_original_paid_scope_and_new_local_ids(self):
        g=self.game(('wait',),board=('plain',),enemy=('plain',));t=g.state.players[1].board[0]
        self.cast(g,'wait',t);proof=g._frame.paid_hand_choice_boundary;restored=self.portable(g)
        for branch in (g,restored):
            self.choose(branch,'good');copy=branch.state.players[1].board[-1]
            self.assertNotEqual(copy,t);self.assertIsNotNone(branch.state.pending_choice);self.portable(branch)
            effect=GrantHealthRule(copy,SELF,proof.event.source_id)
            validate_frame_references(branch.state,branch.registry,effect)
            with self.assertRaisesRegex(ValueError,'Unknown or future health floor grant reference'):
                FrameCodec(branch.mechanics,branch.registry).encode(replace(proof,work=(effect,)))
            self.choose(branch,'inner');self.assertEqual(branch.state.entities[copy].health,1)
            self.assertEqual(len([a for a in branch.state.entities[copy].abilities if a.kind=='health_rule']),2)
            self.private(branch);self.portable(branch)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_rehashed_closed_plan_numeric_carrier_and_allocation_negatives(self):
        g=self.game(('hit',));t=g.state.players[2].board[0];self.cast(g,'hit',t);s=g.snapshot()
        def result(s):return next(e for e in s['events'] if e['kind']=='health_resolved')['data']['result']
        def setfield(rows,key,value):next(r for r in rows if r[0]==key)[1]=value
        for key,value in (('floor_prevented',True),('floor_prevented',2),('modified_amount',11)):
            bad=json.loads(json.dumps(s));setfield(result(bad),key,value);self.reject(bad,key+str(value))
        for key,value in (('floor',2),('next_attachment_id',s['state']['next_attachment_id']+10),
                ('target_id',s['state']['next_entity_id']+10),('target_zone_epoch',100)):
            bad=json.loads(json.dumps(s));plan=dict(result(bad))['floor_plan'];setfield(plan,key,value);self.reject(bad,'plan-'+key)
        for key,value in (('carrier_id',s['state']['next_entity_id']+10),('card_id','unregistered'),('controller',True)):
            bad=json.loads(json.dumps(s));row=dict(dict(result(bad))['floor_plan'])['rows'][0];setfield(row,key,value);self.reject(bad,'row-'+key)
        bad=json.loads(json.dumps(s));row=dict(dict(result(bad))['floor_plan'])['rows'][0]
        ability=dict(row)['ability'];setfield(ability,'source_id',g.state.players[1].hero_id);self.reject(bad,'changed-original-row')
        bad=json.loads(json.dumps(s));dict(result(bad))['floor_plan'].append(['unknown',1]);self.reject(bad,'unknown-plan-field')
        bad=json.loads(json.dumps(s));raw=result(bad)
        for key,value in (('prevention','zero_damage'),('damage_dealt',0),('health_lost',0),
                ('floor_prevented',0),('health_after',dict(raw)['health_before'])):
            setfield(raw,key,value)
        event=next(e for e in bad['events'] if e['kind']=='health_resolved');event['amount']=0
        self.reject(bad,'positive-budget-cannot-be-fake-zero-damage')
        borrowed=self.game(('hit',),enemy=('friend','friend','plain'))
        target=borrowed.state.players[2].board[-1];self.cast(borrowed,'hit',target)
        bad=borrowed.snapshot();rows=dict(dict(result(bad))['floor_plan'])['rows']
        setfield(rows[0],'carrier_id',dict(rows[1])['carrier_id'])
        setfield(rows[0],'zone_epoch',dict(rows[1])['zone_epoch'])
        setfield(rows[0],'entered_order',dict(rows[1])['entered_order'])
        self.reject(bad,'borrow-allocated-row-from-other-physical-carrier')
        for kwargs in ({'amount':True},{'amount':0},{'amount':-1},{'flow':HealthFlow.HEALING},{'layer':HealthLayer.SOURCE}):
            values=dict(flow=HealthFlow.DAMAGE,operation=HealthOp.FLOOR,amount=1,layer=HealthLayer.TARGET);values.update(kwargs)
            with self.assertRaises(ValueError):HealthRule(**values)
        with self.assertRaises(ValueError):HealthOp('live_hp_formula')
        with self.assertRaises(ValueError):registry().register_card(CardDefinition('bad','Bad',CardType.MINION,health=5,
            keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',),health_rules=(SELF,)))

    def test_future_grant_waiting_rejection_known_stale_and_rng_transaction_rollback(self):
        g=self.game(('wait',),board=('plain','plain'));t=g.state.players[1].board[0]
        self.cast(g,'wait',t);before=g.snapshot();restored=self.portable(g)
        def typed(v):
            if type(v) is dict:
                if v.get('type')=='hs_sim.engine.effects.GrantHealthRule':return v
                for child in v.values():
                    found=typed(child)
                    if found:return found
            if type(v) is list:
                for child in v:
                    found=typed(child)
                    if found:return found
        for field in ('target_id','source_id'):
            bad=json.loads(json.dumps(before));grant=typed(bad['resolution_frame']['fields']['options'])
            grant['fields'][field]=bad['state']['next_entity_id']+10;self.reject(bad,'future-waiting-'+field)
        for branch in (g,restored):
            self.blob(branch.snapshot(),'actual-failed-choice-input')
            with self.assertRaises(ResolutionError):self.choose(branch,'bad')
            self.assertEqual(branch.snapshot(),before)
            self.choose(branch,'good');self.choose(branch,'inner');self.portable(branch)
        g=self.game(('stale',),board=('plain',),enemy=());old=g.state.players[1].board[0]
        self.cast(g,'stale',old);self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.portable(g)
        self.choose(g,'ok');self.assertFalse(any(a.kind=='health_rule' for a in g.state.entities[old].abilities));self.portable(g)

    def test_captured_result_row_survives_silence_wait_and_later_transform(self):
        g=self.game(('capture_wait','floorform'),enemy=('self',));t=g.state.players[2].board[0]
        self.cast(g,'capture_wait',t);self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(any(a.kind=='health_rule' for a in g.state.entities[t].abilities))
        restored=self.portable(g)
        for branch in (g,restored):
            self.choose(branch,'ok');self.cast(branch,'floorform',t);self.portable(branch)
        self.assertEqual(g.snapshot(),restored.snapshot())
