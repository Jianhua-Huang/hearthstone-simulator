"""Native Wildfire uses existing persistent hero attachments and health rules."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, DamageKind, EndTurn, Game,
    HealingKind, HealthFlow, HealthOp, HealthRule, PlayCard, PlayerSetup, Registry,
    ResolutionError, Scenario, SelectChoice, SnapshotError, SpellSchool,
    TargetSpec, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.effects import (ChoiceOption, Damage, GrantHealthRule, Heal,
    InvokeBehavior, ReplaceHero, ReplaceHeroPower, RequestChoice)
from hs_sim.engine.health_rules import prepare_health
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]
NATIVE='BAR_546';POWER='HERO_08bp'
PIN='7d1c112214be84cd8737571e1be0ad489ff18d8fa4bcdcd3f67948466892eebf'
RULE=HealthRule(HealthFlow.DAMAGE,HealthOp.ADD,1,source_relation='friendly',damage_kinds=(DamageKind.HERO_POWER,))


def evidence():
    packet=json.loads((ROOT/'data/support/whole-game-hero-power-damage-basics.json').read_bytes())
    if canonical_digest(packet)!=PIN:raise ValueError('Complete native Wildfire evidence changed')
    return packet


def registry():
    r=Registry('whole-game-hero-power-damage-independent-v1');raw={x['id']:x for x in evidence()['records']}
    for cid in ('wg.hero','wg.hero2','wg.hero3'):
        r.register_card(CardDefinition(cid,cid,CardType.HERO,health=30,metadata=metadata(collectible=False)))
    for cid in ('wg.body','wg.hidden'):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=12,metadata=metadata()))
    # A named ordinary phase reads the current hero when the body executes.
    r.register_behavior('wg.cb.native.plan',lambda c:(InvokeBehavior('wg.cb.native.grant',c.source_id,c.player_id),))
    r.register_behavior('wg.cb.native.grant',lambda c:(GrantHealthRule(c.state.players[c.player_id].hero_id,RULE,c.source_id),))
    row=raw[NATIVE]
    r.register_card(CardDefinition(NATIVE,row['name'],CardType.SPELL,cost=row['cost'],spell_school=SpellSchool.FIRE,
        on_play='wg.cb.native.plan',metadata=metadata_from_record(row)))
    row=raw[POWER]
    r.register_behavior('wg.cb.native.power',lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.HERO_POWER),))
    r.register_card(CardDefinition(POWER,row['name'],CardType.HERO_POWER,cost=row['cost'],on_use='wg.cb.native.power',
        targeting=TargetSpec(),metadata=metadata_from_record(row)))
    r.register_behavior('wg.cb.power2',lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.HERO_POWER),))
    r.register_behavior('wg.cb.quiet',lambda c:())
    r.register_card(CardDefinition('wg.power2','Replacement damage diagnostic',CardType.HERO_POWER,cost=2,
        on_use='wg.cb.power2',targeting=TargetSpec(),metadata=metadata(collectible=False)))
    r.register_card(CardDefinition('wg.quiet','Nondamaging power diagnostic',CardType.HERO_POWER,cost=2,
        on_use='wg.cb.quiet',metadata=metadata(collectible=False)))
    operations={
        'power2':lambda c:(ReplaceHeroPower(c.player_id,'wg.power2',source_id=c.source_id),),
        'power':lambda c:(ReplaceHeroPower(c.player_id,POWER,source_id=c.source_id),),
        'quiet':lambda c:(ReplaceHeroPower(c.player_id,'wg.quiet',source_id=c.source_id),),
        'hero2':lambda c:(ReplaceHero(c.player_id,'wg.hero2',hero_power_card_id='wg.power2'),),
        'hero3':lambda c:(ReplaceHero(c.player_id,'wg.hero3',hero_power_card_id=POWER),),
    }
    for key,body in operations.items():
        r.register_behavior('wg.cb.op.'+key,body)
        r.register_card(CardDefinition('wg.op.'+key,key+' diagnostic',CardType.SPELL,on_play='wg.cb.op.'+key,metadata=metadata()))
    def fail(c):raise ResolutionError('Deliberate persistent Hero Power damage rollback')
    r.register_behavior('wg.cb.fail',fail)
    def wait(c):
        if c.event.source_id is None or c.state.entities[c.event.source_id].card_id!=NATIVE:return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),
            ChoiceOption('hero','Replace hero',(ReplaceHero(c.player_id,'wg.hero2',hero_power_card_id=POWER),)),
            ChoiceOption('bad','Fail',(ReplaceHero(c.player_id,'wg.hero2',hero_power_card_id=POWER),
                InvokeBehavior('wg.cb.fail',c.source_id,c.player_id))),
        ),c.source_id),)
    r.register_behavior('wg.cb.wait',wait)
    r.register_behavior('wg.cb.counter',lambda c:(CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==NATIVE else ())
    for key,event,body in (('start','card_committed','wg.cb.wait'),('grant','ability_granted','wg.cb.wait'),
            ('counter','card_committed','wg.cb.counter')):
        r.register_card(CardDefinition('wg.watch.'+key,key+' diagnostic',CardType.MINION,health=8,metadata=metadata(),triggers=(TriggerSpec(event,body),)))
    return r


class WholeGameHeroPowerDamageTests(unittest.TestCase):
    def game(self,hand=(),board=(),*,enemy_hand=(),power=POWER):
        return Game.from_scenario(Scenario((
            PlayerSetup('wg.hero',hand=hand,board=board,deck=('wg.body',)*12,mana=10,max_mana=10,hero_power_card_id=power),
            PlayerSetup('wg.hero',hand=enemy_hand,deck=('wg.body',)*12,mana=10,max_mana=10,hero_power_card_id=POWER)),seed=110),registry())
    def hero(self,g,seat=1):return g.state.entities[g.state.players[seat].hero_id]
    def rules(self,g,seat=1):return [a for a in self.hero(g,seat).abilities if a.kind=='health_rule' and not a.consumed]
    def play(self,g,cid=NATIVE):
        p=g.state.active_player;i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,i));return i
    def use(self,g,target=None):
        p=g.state.active_player;power=g.state.players[p].hero_power_id
        if g.state.entities[power].card_id=='wg.quiet':target=None
        else:target=target or g.state.players[3-p].hero_id
        return g.apply(UseHeroPower(p,power,target))
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def damage(self,result):return [e for e in result.events if e.kind=='damage_dealt']
    def check(self,g):
        saved=json.loads(json.dumps(g.snapshot()));variants=(Game.from_snapshot(saved,registry()),g.clone(),replay(build_replay(g),registry()))
        for other in variants:self.assertEqual(other.snapshot(),saved)
        return variants

    def test_complete_native_raw_pin_four_records_and_two_isolated_adapters(self):
        packet=evidence();raw={x['id']:x for x in json.loads((ROOT/'data/extracted/cards.json').read_bytes())}
        self.assertEqual((len(packet['records']),packet['executable_representatives']),(4,[NATIVE,POWER]))
        self.assertEqual(packet['candidate_ids'],['BAR_546','BAR_546e','BAR_546e2'])
        for row in packet['records']:self.assertEqual(row,raw[row['id']])
        r=registry();card=r.card(NATIVE)
        self.assertEqual((card.name,card.kind,card.cost,card.spell_school),('野火',CardType.SPELL,1,SpellSchool.FIRE))
        self.assertIsNone(card.targeting);self.assertEqual(card.health_rules,())
        self.assertTrue(packet['historical_before_22_0_2_policy_excluded'])
        self.assertTrue(all(i not in r.cards for i in packet['evidence_only']))

    def test_native_spell_installs_one_untimed_rule_after_source_enters_graveyard(self):
        g=self.game((NATIVE,));source=self.play(g);rows=self.rules(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(len(rows),1)
        self.assertEqual((rows[0].health_rule,rows[0].source_id,rows[0].origin,rows[0].expires_turn),(RULE,source,'granted',None))
        self.assertEqual(g.state.players[1].mana,9);self.assertEqual(self.damage(self.use(g))[0].amount,2);self.check(g)

    def test_two_native_casts_stack_distinct_physical_rules_without_extra_payment(self):
        g=self.game((NATIVE,NATIVE));sources=[self.play(g),self.play(g)];rows=self.rules(g)
        self.assertEqual(len({a.id for a in rows}),2);self.assertEqual([a.source_id for a in rows],sources)
        self.assertEqual(g.state.players[1].mana,8);event=self.damage(self.use(g))[0]
        self.assertEqual(event.amount,3);self.assertEqual(dict(event.data)['base_amount'],1)
        self.assertEqual(len(dict(event.data)['rule_ids']),2);self.assertEqual(g.state.players[1].mana,6)

    def test_each_player_has_independent_permanent_bonus(self):
        g=self.game((NATIVE,),enemy_hand=(NATIVE,NATIVE));self.play(g)
        self.assertEqual(self.damage(self.use(g))[0].amount,2);g.apply(EndTurn(1))
        self.assertEqual(self.damage(self.use(g))[0].amount,1)
        self.play(g);self.play(g);self.assertEqual((len(self.rules(g,1)),len(self.rules(g,2))),(1,2));self.check(g)

    def test_untimed_bonus_survives_owner_and_opponent_turn_boundaries(self):
        g=self.game((NATIVE,));self.play(g);ability=self.rules(g)[0].id
        for _ in range(3):
            self.assertEqual(self.damage(self.use(g))[0].amount,2);self.cycle(g)
            self.assertEqual([a.id for a in self.rules(g)],[ability]);self.assertIsNone(self.rules(g)[0].expires_turn)
        self.check(g)

    def test_replacing_power_uses_new_base_damage_and_original_hero_rule(self):
        g=self.game((NATIVE,'wg.op.power2','wg.op.power'));self.play(g);hero=self.hero(g).id;ability=self.rules(g)[0].id
        old=g.state.players[1].hero_power_id;self.play(g,'wg.op.power2')
        self.assertNotEqual(g.state.players[1].hero_power_id,old);self.assertEqual(self.hero(g).id,hero)
        self.assertEqual(self.rules(g)[0].id,ability);self.assertEqual(self.damage(self.use(g))[0].amount,3)
        self.play(g,'wg.op.power');self.assertEqual(self.damage(self.use(g))[0].amount,2);self.check(g)

    def test_nondamaging_power_does_not_gain_a_damage_body_and_bonus_returns(self):
        g=self.game((NATIVE,'wg.op.quiet','wg.op.power'));self.play(g);self.play(g,'wg.op.quiet')
        self.assertEqual(self.damage(self.use(g)),[]);self.assertEqual(len(self.rules(g)),1)
        self.play(g,'wg.op.power');self.assertEqual(self.damage(self.use(g))[0].amount,2);self.check(g)

    def test_wildfire_before_any_power_slot_applies_when_power_is_later_installed(self):
        g=self.game((NATIVE,'wg.op.power'),power=None);self.assertIsNone(g.state.players[1].hero_power_id)
        self.play(g);self.assertEqual(len(self.rules(g)),1);self.play(g,'wg.op.power')
        self.assertEqual(self.damage(self.use(g))[0].amount,2);self.check(g)

    def test_hero_replacement_preserves_granted_rule_with_fresh_identity(self):
        g=self.game((NATIVE,'wg.op.hero2','wg.op.hero3'));source=self.play(g);old=self.hero(g).id;old_ability=self.rules(g)[0].id
        self.play(g,'wg.op.hero2');new=self.hero(g).id;first=self.rules(g)[0]
        self.assertNotEqual(old,new);self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        self.assertEqual((first.health_rule,first.source_id,first.expires_turn),(RULE,source,None));self.assertNotEqual(first.id,old_ability)
        self.assertEqual(self.damage(self.use(g))[0].amount,3);self.play(g,'wg.op.hero3')
        self.assertNotEqual(self.hero(g).id,new);self.assertEqual(len(self.rules(g)),1);self.assertNotEqual(self.rules(g)[0].id,first.id)
        self.assertEqual(self.damage(self.use(g))[0].amount,2);self.check(g)

    def test_public_native_spell_command_pays_one_and_following_power_pays_two(self):
        g=self.game((NATIVE,));port=g.for_player(1);public=port.legal_actions()
        ref=public['observation']['players'][0]['hand'][0]['ref']
        action=next(a for a in public['actions'] if a['type']=='play_card' and a.get('card')==ref)
        result=port.submit({'revision':public['revision'],'action':action});self.assertTrue(result['accepted'],result['error'])
        self.assertEqual(g.state.players[1].mana,9);self.assertEqual(len(self.rules(g)),1)
        public=port.legal_actions();target=public['observation']['players'][1]['hero']['ref']
        action=next(a for a in public['actions'] if a['type']=='use_hero_power' and a.get('target')==target)
        result=port.submit({'revision':public['revision'],'action':action});self.assertTrue(result['accepted'],result['error'])
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(self.hero(g,2).health,28);self.check(g)

    def test_countered_native_spell_keeps_payment_but_does_not_install_bonus(self):
        g=self.game((NATIVE,),('wg.watch.counter',));self.play(g)
        self.assertEqual(g.state.players[1].mana,9);self.assertEqual(self.rules(g),[])
        self.assertEqual(self.damage(self.use(g))[0].amount,1);self.check(g)

    def test_damage_classifier_and_healing_filters_preserve_unrelated_packets(self):
        g=self.game((NATIVE,),('wg.body',));source=self.play(g);target=self.hero(g,2).id;body=g.state.players[1].board[0]
        before=g.snapshot()
        for kind,holder in ((DamageKind.SPELL,source),(DamageKind.COMBAT,body),(DamageKind.EFFECT,source),
                (DamageKind.FATIGUE,None),(DamageKind.MINION_ABILITY,body)):
            packet=prepare_health(g.state,g.registry,Damage(target,1,holder,kind));self.assertEqual((packet.amount,packet.rule_ids),(1,()))
        power=g.state.players[1].hero_power_id;healing=prepare_health(g.state,g.registry,Heal(target,1,power,HealingKind.HERO_POWER))
        self.assertEqual((healing.amount,healing.rule_ids),(1,()));self.assertEqual(g.snapshot(),before)

    def test_commit_waiting_restore_then_replacement_installs_on_current_hero(self):
        g=self.game((NATIVE,),('wg.watch.start',));old=self.hero(g).id;self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.rules(g),[]);self.assertEqual(g.state.players[1].mana,9)
        variants=(g,*self.check(g))
        for other in variants:
            self.choose(other,'hero');self.assertNotEqual(self.hero(other).id,old);self.assertEqual(len(self.rules(other)),1)
            self.assertEqual(self.damage(self.use(other))[0].amount,2);self.assertEqual(other.state.players[1].mana,7)
        for other in variants[1:]:self.assertEqual(other.snapshot(),g.snapshot())

    def test_grant_waiting_restore_then_hero_replacement_preserves_exactly_one_bonus(self):
        g=self.game((NATIVE,),('wg.watch.grant',));source=self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(self.rules(g)),1);variants=(g,*self.check(g))
        for other in variants:
            self.choose(other,'hero');self.assertEqual(len(self.rules(other)),1);self.assertEqual(self.rules(other)[0].source_id,source)
            self.assertEqual(self.damage(self.use(other))[0].amount,2)
        for other in variants[1:]:self.assertEqual(other.snapshot(),g.snapshot())

    def test_failed_waiting_branch_rolls_back_hero_replacement_and_keeps_native_one(self):
        g=self.game((NATIVE,),('wg.watch.grant',));self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.assertEqual(len(self.rules(g)),1)
        self.choose(g);self.assertEqual(self.damage(self.use(g))[0].amount,2);self.check(g)

    def test_rehashed_waiting_snapshot_rejects_unknown_rule_fields(self):
        g=self.game((NATIVE,),('wg.watch.grant',));self.play(g);bad=deepcopy(g.snapshot())
        row=next(a for a in bad['state']['entities'][str(self.hero(g).id)]['abilities'] if a['kind']=='health_rule')
        row['health_rule']['unknown']=1
        bad['state_hash']=canonical_hash({k:v for k,v in bad.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as caught:Game.from_snapshot(bad,registry())
        self.assertNotIn('digest mismatch',str(caught.exception));self.check(g)

    def test_player_views_exclude_hidden_cards_internal_rule_and_continuations(self):
        g=self.game((NATIVE,),('wg.watch.grant',),enemy_hand=('wg.hidden',));self.play(g)
        for seat in (1,2):
            wire=json.dumps((g.for_player(seat).observe(),g.for_player(seat).legal_actions()),ensure_ascii=False)
            for field in ('health_rule','resolution_frame','source_sha256','work_queue'):self.assertNotIn(field,wire)
            if seat==1:self.assertNotIn('wg.hidden',wire)


if __name__=='__main__':unittest.main()
