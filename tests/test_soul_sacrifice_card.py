"""Actual Soul Immolation, physical damage steps and unchanged Star delivery."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry as assembled_registry
from hs_sim.cards.soul_sacrifice_card import ROOT,STAR,BODY,load_batch,register_soul_sacrifice_card
from hs_sim.engine import (CardDefinition,CardType,DamageKind,EndTurn,Game,HealthFlow,HealthOp,
    HealthRule,IllegalAction,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TriggerSpec,
    UseHeroPower)
from hs_sim.engine.effects import (ChoiceOption,Damage,GainArmor,GrantHealthRule,InvokeBehavior,
    ReplaceHeroPower,RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_rules import power_damage_rule
from hs_sim.engine.hero_powers import AddHeroPower,TriggerHeroPower
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest

P='soul.test.';DEMON='CS2_065';BODY_MINION='CS2_182';OTHER='HERO_08bp'


@lru_cache(maxsize=1)
def full_registry():return assembled_registry()


@lru_cache(maxsize=None)
def registry(role,mode=None):
    assert role in ('writer','reader')
    r=build_registry();full=full_registry()
    # Reuse the real pre-existing definition and bodies, not a second Star recipe.
    power=full.card(STAR)
    for name in (power.on_use,*(t.behavior_id for t in power.triggers)):
        r.register_behavior(name,full.behavior(name))
    r.register_card(power);r.register_card(full.card(DEMON))
    register_soul_sacrifice_card(r)
    meta=r.card(BODY_MINION).metadata
    r.register_card(CardDefinition(P+'boost',P+'boost',CardType.MINION,health=12,spell_damage=6,
        health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.ADD,1,
            source_relation='friendly',damage_kinds=(DamageKind.HERO_POWER,)),),metadata=meta))
    def fail(c):raise ResolutionError('Soul deliberate continuation failure')
    r.register_behavior(P+'fail',fail)
    bodies={
        'other':lambda c:(ReplaceHeroPower(c.player_id,OTHER,source_id=c.source_id),),
        'star':lambda c:(ReplaceHeroPower(c.player_id,STAR,source_id=c.source_id),),
        'additional':lambda c:(AddHeroPower(c.player_id,STAR,c.source_id),),
        'trigger':lambda c:(TriggerHeroPower(c.player_id,c.source_id),),
        'spell':lambda c:(Damage(c.state.players[3-c.player_id].hero_id,1,c.source_id,DamageKind.SPELL),),
        'bad-rule':lambda c:(GrantHealthRule(c.state.players[c.player_id].hero_power_id,
            replace(power_damage_rule(),source_relation='friendly'),c.source_id),),
        'bad-expiry':lambda c:(GrantHealthRule(c.state.players[c.player_id].hero_power_id,
            power_damage_rule(),c.source_id,expires_turn=c.state.turn+1),),
        'bad-owner':lambda c:(GrantHealthRule(c.state.players[c.player_id].hero_power_id,
            power_damage_rule(),c.source_id,until_owner_turn_start=c.player_id),),
    }
    for key,body in bodies.items():
        r.register_behavior(P+key,body)
        r.register_card(CardDefinition(P+key,P+key,CardType.SPELL,on_play=P+key,metadata=meta))
    if mode is not None:
        def watch(c):
            if mode in ('commit','counter'):
                source=c.state.entities.get(c.event.source_id)
                if source is None or source.card_id!=ROOT:return ()
            elif mode=='grant':
                if c.event.source_id is None or c.state.entities[c.event.source_id].card_id!=ROOT:return ()
                if dict(c.event.data).get('ability_kind')!='health_rule':return ()
            elif c.event.target_id is None or c.state.entities[c.event.target_id].card_id!=STAR:
                return ()
            if mode=='counter':return (CounterSpell(dict(c.event.data)['window_id']),)
            return (RequestChoice(c.player_id,(
                ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
                ChoiceOption('star','Replace with Star',(ReplaceHeroPower(c.player_id,STAR,source_id=c.source_id),)),
                ChoiceOption('other','Replace with other',(ReplaceHeroPower(c.player_id,OTHER,source_id=c.source_id),)),
                ChoiceOption('fail','Fail',(ReplaceHeroPower(c.player_id,OTHER,source_id=c.source_id),
                    InvokeBehavior(P+'fail',c.source_id,c.player_id))),
            ),c.source_id),)
        r.register_behavior(P+'watch',watch)
        event={'commit':'card_committed','counter':'card_committed','grant':'ability_granted',
            'install':'hero_power_replaced'}[mode]
        r.register_card(CardDefinition(P+'watch',P+'watch',CardType.MINION,health=8,
            triggers=(TriggerSpec(event,P+'watch'),),metadata=meta))
    r.validate();r.freeze();return r


class SoulSacrificeTests(unittest.TestCase):
    def game(self,hand=(ROOT,),*,power=OTHER,mode=None,boost=False,enemy_hand=(),enemy_board=()):
        self.mode=mode
        own=((P+'watch',)if mode is not None else())+((P+'boost',)if boost else())
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=own,deck=(BODY_MINION,)*12,mana=10,max_mana=10,
                hero_power_card_id=power),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy_board,deck=(BODY_MINION,)*12,
                mana=10,max_mana=10,hero_power_card_id=OTHER)),seed=235101),registry('writer',mode))
    def power(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_power_id]
    def play(self,g,cid=ROOT):
        pid=g.state.active_player
        card=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        return g.apply(PlayCard(pid,card,position=len(g.state.players[pid].board)
            if g.registry.card(cid).kind==CardType.MINION else None))
    def use(self,g,power=None):
        pid=g.state.active_player
        return g.apply(UseHeroPower(pid,power or g.state.players[pid].hero_power_id))
    def damage(self,result):return [e for e in result.events if e.kind=='damage_dealt']
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        r=registry('reader'if g.registry is registry('writer',self.mode)else'writer',self.mode)
        self.assertIsNot(r,g.registry);s=json.loads(json.dumps(g.snapshot()))
        other=Game.from_snapshot(s,r)
        for v in (other,g.clone(),replay(build_replay(g),r)):self.assertEqual(v.snapshot(),s)
        for pid in (1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for field in ('rng_state','resolution_frame','original_entities','source_guard'):
                self.assertNotIn(field,wire)
        return other

    def test_a00_complete_raw_four_faces_and_unchanged_existing_power(self):
        from tools.card_batch import check_face
        d=load_batch();rows={x['record']['id']:x['record']for k in ('cards','existing_dependencies')for x in d[k]}
        self.assertEqual(len(d['official_observations']),4)
        for o in d['official_observations']:
            check_face(rows[o['card_id']],o['face'],o['locale'],d['display_normalizations'].get(o['card_id']))
        self.assertEqual(rows[STAR]['tags']['TAG_SCRIPT_DATA_NUM_1'],2)
        r=registry('writer');self.assertEqual(r.card(ROOT),full_registry().card(ROOT))
        self.assertEqual(r.card(STAR),full_registry().card(STAR));self.assertEqual(r.card(ROOT).cost,2)
        self.assertEqual(r.card(ROOT).spell_school.value,'shadow');self.assertIsNone(r.card(ROOT).targeting)
    def test_b00_first_spell_installs_fresh_printed_power_and_pays_separately(self):
        g=self.game();old=self.power(g).id;self.play(g)
        power=self.power(g);self.assertNotEqual(power.id,old);self.assertEqual(power.card_id,STAR)
        self.assertEqual(g.state.entities[old].zone.value,'graveyard');self.assertEqual(power.uses_this_turn,0)
        self.assertEqual(g.state.players[1].mana,8);event=self.damage(self.use(g))[0]
        self.assertEqual((event.amount,dict(event.data)['base_amount']),(2,2))
        self.assertEqual(g.state.players[1].mana,7);self.portable(g)
    def test_b01_subsequent_spells_stack_on_same_power_and_keep_use_and_cost(self):
        g=self.game((ROOT,ROOT),power=STAR);power=self.power(g);self.play(g);self.play(g)
        self.assertEqual(self.power(g).id,power.id);self.assertEqual(power.cost,1)
        self.assertEqual(len([a for a in self.power(g).abilities if a.kind=='health_rule']),2)
        self.assertEqual(self.damage(self.use(g))[0].amount,4);self.assertEqual(g.state.players[1].mana,5)
        self.portable(g)
    def test_b02_upgrade_does_not_refresh_an_already_used_power(self):
        g=self.game(power=STAR);self.use(g);power=self.power(g);self.play(g)
        self.assertEqual((self.power(g).uses_this_turn,self.power(g).id),(1,power.id))
        saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.use(g)
        self.assertEqual(g.snapshot(),saved);self.portable(g)
    def test_b03_friendly_demon_refresh_keeps_the_existing_damage_step(self):
        g=self.game((ROOT,DEMON),power=STAR);self.play(g);power=self.power(g)
        self.assertEqual(self.damage(self.use(g))[0].amount,3);self.play(g,DEMON)
        self.assertEqual((self.power(g).id,self.power(g).uses_this_turn),(power.id,0))
        self.assertEqual(self.damage(self.use(g))[0].amount,3);self.portable(g)
    def test_c00_retirement_and_reinstallation_do_not_carry_old_physical_steps(self):
        g=self.game((ROOT,P+'other',ROOT),power=STAR);self.play(g);old=self.power(g).id
        self.play(g,P+'other');self.play(g)
        self.assertNotEqual(self.power(g).id,old);self.assertEqual(self.damage(self.use(g))[0].amount,2)
        self.assertEqual(len([a for a in g.state.entities[old].abilities if a.kind=='health_rule']),1)
        self.portable(g)
    def test_c01_both_players_have_independent_current_power_damage(self):
        g=self.game(enemy_hand=(ROOT,ROOT));self.play(g)
        self.assertEqual(self.damage(self.use(g))[0].amount,2);g.apply(EndTurn(1))
        self.play(g);self.play(g);self.assertEqual(self.damage(self.use(g))[0].amount,3)
        self.portable(g)
    def test_c02_native_kind_ignores_spell_damage_and_combines_with_existing_power_rules(self):
        g=self.game((ROOT,P+'spell'),power=STAR,boost=True);self.play(g)
        self.assertEqual(self.damage(self.use(g))[0].amount,4)
        self.assertEqual(self.damage(self.play(g,P+'spell'))[0].amount,7);self.portable(g)
    def test_c03_source_local_step_does_not_boost_an_independent_additional_power(self):
        g=self.game((ROOT,P+'additional'),power=STAR);self.play(g);self.play(g,P+'additional')
        second=g.state.players[1].additional_hero_power_ids[0]
        self.assertEqual(self.damage(self.use(g,second))[0].amount,2)
        self.assertEqual(self.damage(self.use(g))[0].amount,3);self.portable(g)
    def test_c04_effect_activation_uses_the_same_step_without_manual_payment_or_use(self):
        g=self.game((ROOT,P+'trigger'),power=STAR);self.play(g)
        self.assertEqual(self.damage(self.play(g,P+'trigger'))[0].amount,3)
        self.assertEqual((g.state.players[1].mana,self.power(g).uses_this_turn),(8,0));self.portable(g)
    def test_d00_countered_spell_pays_but_neither_installs_nor_upgrades(self):
        for power in (OTHER,STAR):
            with self.subTest(power=power):
                g=self.game(power=power,mode='counter');old=deepcopy(self.power(g));self.play(g)
                self.assertEqual(self.power(g),old);self.assertEqual(g.state.players[1].mana,8);self.portable(g)
    def test_d01_commit_wait_resolves_against_current_power_and_failed_choice_rolls_back(self):
        g=self.game(mode='commit');self.play(g);saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),saved)
        self.choose(g,'star');self.choose(other,'star');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(self.damage(self.use(g))[0].amount,3);self.portable(g)
    def test_d02_post_upgrade_wait_restores_exact_step_and_choice_failure(self):
        g=self.game(power=STAR,mode='grant');self.play(g);saved=g.snapshot();other=self.portable(g)
        self.assertEqual(len([a for a in self.power(g).abilities if a.kind=='health_rule']),1)
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),saved)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(self.damage(self.use(g))[0].amount,3);self.portable(g)
    def test_d03_post_install_wait_restores_new_power_and_printed_damage(self):
        g=self.game(mode='install');self.play(g);other=self.portable(g)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(self.damage(self.use(g))[0].amount,2);self.portable(g)
    def test_e00_unrelated_or_timed_power_rules_reject_and_roll_back(self):
        for key in ('bad-rule','bad-expiry','bad-owner'):
            with self.subTest(key=key):
                g=self.game((P+key,),power=STAR);saved=g.snapshot()
                with self.assertRaises((ResolutionError,ValueError)):self.play(g,P+key)
                self.assertEqual(g.snapshot(),saved);self.portable(g)
    def test_e01_rehashed_snapshot_rejects_changed_power_rule_scope_and_expiry(self):
        g=self.game(power=STAR);self.play(g);saved=g.snapshot()
        for key,value in (('source_relation','friendly'),('amount',2),('expires_turn',g.state.turn+1),('origin','printed')):
            with self.subTest(key=key):
                bad=deepcopy(saved)
                row=next(a for a in bad['state']['entities'][str(self.power(g).id)]['abilities']if a['kind']=='health_rule')
                (row['health_rule']if key in ('source_relation','amount')else row)[key]=value
                bad['state_hash']=canonical_hash({k:v for k,v in bad.items()if k not in
                    ('schema_version','events','events_hash','state_hash')})
                with self.assertRaises(SnapshotError)as caught:Game.from_snapshot(bad,registry('reader'))
                self.assertNotIn('digest mismatch',str(caught.exception))
        self.portable(g)
    def test_f00_player_command_uses_the_ordinary_spell_entry(self):
        g=self.game();port=g.for_player(1);view=port.legal_actions()
        action=next(a for a in view['actions']if a['type']=='play_card')
        result=port.submit({'revision':view['revision'],'action':action})
        self.assertTrue(result['accepted'],result['error']);self.assertEqual(self.power(g).card_id,STAR)
        self.assertEqual(g.state.players[1].mana,8);self.portable(g)


if __name__=='__main__':unittest.main()
