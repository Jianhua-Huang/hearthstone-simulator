"""One current-turn manual card type rule, with two necessary native sources."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,HandActionSpec,IllegalAction,
    PlayCard,PlayerEffectSpec,PlayerSetup,QueueTurns,Registry,ResolutionError,Scenario,
    SelectChoice,SnapshotError,SpellSchool,TargetSpec,TriggerSpec,UseHandAction,UseHeroPower)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (ChoiceOption,Damage,DamageKind,GainArmor,InvokeBehavior,
    RefreshMana,RequestChoice)
from hs_sim.engine.hand_upgrades import UpgradeHandCard
from hs_sim.engine.player_effects import AddPlayerEffect,RemovePlayerEffect,manual_play_allowed
from hs_sim.engine.play_history import prepare_play
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.resolver import PlayFromHand,Resolution
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_cost_proof import capture_hand_cost_proof,validate_hand_cost_proof
from hs_sim.engine.zones import CardReference,DrawMatching
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]
PIN='0d2c474f3f2ce2b17f2e2d1a983cf60151cd56102785694f62bcd4c3b300c556'
MIN='BE_EVENT_100'; SPELL='BE_EVENT_101'
MIN_RULE='turn.only.minions'; SPELL_RULE='turn.only.spells'

def evidence():
    value=json.loads((ROOT/'data/support/player-turn-play-type-basics.json').read_bytes())
    if canonical_digest(value)!=PIN: raise ValueError('Current-turn type source pin changed')
    return value

def registry(min_permission=CardType.MINION):
    r=Registry('independent-current-turn-card-type-v1')
    r.register_card(CardDefinition('hero','Diagnostic hero',CardType.HERO,health=60,metadata=metadata()))
    r.register_behavior('noop',lambda c:())
    r.register_card(CardDefinition('power','Diagnostic power',CardType.HERO_POWER,on_use='noop',metadata=metadata()))
    r.register_player_effect(PlayerEffectSpec(MIN_RULE,MIN,kind='turn_rule',allowed_card_types=(min_permission,)))
    r.register_player_effect(PlayerEffectSpec(SPELL_RULE,SPELL,kind='turn_rule',allowed_card_types=(CardType.SPELL,)))
    for row in evidence()['records']:
        kind,rule,school=(CardType.MINION,MIN_RULE,SpellSchool.SHADOW) if row['id']==MIN else (CardType.SPELL,SPELL_RULE,SpellSchool.HOLY)
        def arrival(c,kind=kind,rule=rule,cost=row['cost']):
            return (DrawMatching(c.player_id,PoolQuery(kinds=(kind,)),'skip',2,'random',c.source_id),
                RefreshMana(c.player_id,cost),AddPlayerEffect(c.player_id,rule,c.source_id))
        r.register_behavior(row['id']+'.arrival',arrival)
        r.register_card(CardDefinition(row['id'],row['name'],CardType.SPELL,cost=row['cost'],spell_school=school,
            on_play=row['id']+'.arrival',metadata=metadata_from_record(row)))
    r.register_card(CardDefinition('minion','Diagnostic minion',CardType.MINION,cost=1,attack=1,health=3,metadata=metadata()))
    r.register_card(CardDefinition('weapon','Diagnostic weapon',CardType.WEAPON,cost=1,attack=1,durability=2,metadata=metadata()))
    r.register_card(CardDefinition('location','Diagnostic location',CardType.LOCATION,cost=1,durability=2,on_use='noop',metadata=metadata()))
    r.register_card(CardDefinition('new.hero','Diagnostic playable hero',CardType.HERO,cost=1,health=60,
        hero_card=True,initial_hero_power='power',metadata=metadata()))
    r.register_behavior('hit',lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),))
    r.register_card(CardDefinition('spell','Diagnostic targeted spell',CardType.SPELL,cost=1,on_play='hit',
        targeting=TargetSpec(),metadata=metadata(),hand_actions=(HandActionSpec('trade','trade',1),)))
    r.register_card(CardDefinition('locked','Diagnostic native locked minion',CardType.MINION,health=1,
        manual_playable=False,metadata=metadata()))
    def fail(c): raise ResolutionError('Diagnostic rule failure')
    r.register_behavior('fail',fail)
    def waiting(c):
        return (RequestChoice(c.player_id,(
            ChoiceOption('finish','Finish',(GainArmor(c.player_id,1),)),
            ChoiceOption('rule','Install rule',(AddPlayerEffect(c.player_id,MIN_RULE,c.source_id),GainArmor(c.player_id,1))),
            ChoiceOption('fail','Fail',(InvokeBehavior('fail',c.source_id,c.player_id),))),c.source_id),)
    def first(c,name):
        return next(i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==name)
    scripts={
        'min.rule':lambda c:(AddPlayerEffect(c.player_id,MIN_RULE,c.source_id),),
        'spell.rule':lambda c:(AddPlayerEffect(c.player_id,SPELL_RULE,c.source_id),),
        'min.wait':waiting,'spell.wait':waiting,
        'min.remove':lambda c:tuple(RemovePlayerEffect(c.player_id,e.id) for e in c.state.players[c.player_id].player_effects),
        'min.removeone':lambda c:(RemovePlayerEffect(c.player_id,c.state.players[c.player_id].player_effects[0].id),),
        'min.auto':lambda c:(CastSpell(c.player_id,'spell',c.source_id,c.state.players[3-c.player_id].hero_id,'explicit'),),
        'min.bypass':lambda c:(PlayFromHand(PlayCard(c.player_id,first(c,'spell'),c.state.players[3-c.player_id].hero_id)),),
        'min.upgrade':lambda c:(UpgradeHandCard(CardReference.capture(c.state.entities[first(c,'minion')]),'weapon',c.source_id,True),),
        'min.extra':lambda c:(QueueTurns((c.player_id,),c.source_id),),
        'spell.fault':lambda c:(AddPlayerEffect(c.player_id,MIN_RULE,c.source_id),InvokeBehavior('fail',c.source_id,c.player_id)),
    }
    for name,fn in scripts.items():
        r.register_behavior(name,fn);kind=CardType.MINION if name.startswith('min.') else CardType.SPELL
        r.register_card(CardDefinition(name,'Diagnostic '+name,kind,health=3 if kind==CardType.MINION else 0,
            battlecry=name if kind==CardType.MINION else None,on_play=name if kind==CardType.SPELL else None,metadata=metadata()))
    r.register_behavior('late',lambda c:(AddPlayerEffect(c.player_id,MIN_RULE,c.source_id),) if c.event.player_id==c.player_id else ())
    r.register_card(CardDefinition('late','Diagnostic late end install',CardType.MINION,health=3,
        triggers=(TriggerSpec('turn_ended','late'),),metadata=metadata()))
    return r

class PlayerTurnPlayTypeTests(unittest.TestCase):
    def game(self,hand=(MIN,'minion','spell'),deck=('minion','spell','minion','spell'),enemy=('minion','spell'),board=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,deck=deck,board=board,hero_power_card_id='power',max_mana=10,mana=10),
            PlayerSetup('hero',hand=enemy,deck=('minion',)*8,hero_power_card_id='power',max_mana=10,mana=10)),seed=161),registry())
    def card(self,g,name,player=1): return next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==name)
    def play(self,g,name,player=1,target=None): return g.apply(PlayCard(player,self.card(g,name,player),target))
    def portable(self,g):
        s=g.snapshot(); self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s);return s
    def blocked(self,g,name):
        eid=self.card(g,name);s=g.snapshot();self.assertFalse(any(isinstance(a,PlayCard) and a.entity_id==eid for a in g.legal_actions()))
        with self.assertRaisesRegex(IllegalAction,'card type'): g.apply(PlayCard(1,eid))
        self.assertEqual(g.snapshot(),s)

    def test_two_complete_native_sources_and_unverified_cn_are_pinned(self):
        p=evidence();self.assertFalse(p['CN_calibrated']);self.assertFalse(p['formal_pool_closed'])
        self.assertEqual([x['id'] for x in p['records']],[MIN,SPELL])
        self.assertEqual([registry().card(x).cost for x in (MIN,SPELL)],[5,6])
        self.assertIn('only play minions',p['records'][0]['text_en'])
        self.assertIn('only play spells',p['records'][1]['text_en'])

    def test_native_minion_draw_refresh_and_permission(self):
        g=self.game();self.play(g,MIN)
        self.assertEqual(g.state.players[1].mana,10)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],['spell','spell'])
        self.assertEqual(len(g.state.players[1].hand),4);self.blocked(g,'spell');self.play(g,'minion');self.portable(g)

    def test_native_spell_draw_refresh_and_permission(self):
        g=self.game(hand=(SPELL,'minion','spell'));self.play(g,SPELL)
        self.assertEqual(g.state.players[1].mana,10)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],['minion','minion'])
        self.blocked(g,'minion');self.play(g,'spell',target=g.state.players[2].hero_id);self.portable(g)

    def test_all_other_manual_types_are_rejected_before_payment(self):
        g=self.game(hand=(MIN,'spell','weapon','location','new.hero'));self.play(g,MIN)
        for name in ('spell','weapon','location','new.hero'): self.blocked(g,name)
        self.assertEqual(g.state.players[1].mana,10);self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_rule_alone_does_not_change_spell_hero_targets(self):
        g=self.game(hand=(SPELL,'spell'));self.play(g,SPELL);eid=self.card(g,'spell')
        self.assertIn(g.state.players[2].hero_id,g.legal_targets(eid));self.play(g,'spell',target=g.state.players[2].hero_id);self.portable(g)

    def test_current_type_after_real_stored_upgrade_controls_permission(self):
        g=self.game(hand=(MIN,'min.upgrade','minion'));self.play(g,MIN);eid=self.card(g,'minion');self.play(g,'min.upgrade')
        self.assertEqual(g.state.entities[eid].kind,CardType.WEAPON);self.blocked(g,'weapon');self.portable(g)

    def test_allowed_type_never_overrides_native_manual_prohibition(self):
        g=self.game(hand=(MIN,'locked'));self.play(g,MIN);eid=self.card(g,'locked');s=g.snapshot()
        with self.assertRaisesRegex(IllegalAction,'manually played'):g.apply(PlayCard(1,eid))
        self.assertEqual(g.snapshot(),s);self.portable(g)

    def test_price_queries_are_pure_and_do_not_grant_permission(self):
        g=self.game();self.play(g,MIN);s=g.snapshot();self.assertEqual(g.quote_cost(self.card(g,'spell')).amount,1)
        self.assertEqual(g.snapshot(),s);self.blocked(g,'spell')

    def test_automatic_spell_payload_and_hero_power_are_not_manual_play(self):
        g=self.game(hand=(MIN,'min.auto'));self.play(g,MIN);self.play(g,'min.auto')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,59)
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.portable(g)

    def test_alternative_trade_operation_is_not_manual_play(self):
        g=self.game();self.play(g,MIN);eid=self.card(g,'spell');action=UseHandAction(1,eid,'trade')
        self.assertIn(action,g.legal_actions());g.apply(action);self.assertEqual(g.state.players[1].mana,9);self.portable(g)

    def test_internal_manual_entry_cannot_bypass_type_gate(self):
        g=self.game(hand=(MIN,'min.bypass','spell'));self.play(g,MIN);s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'card type'):self.play(g,'min.bypass')
        self.assertEqual(g.snapshot(),s);self.portable(g)

    def test_multiple_same_rules_remove_one_without_releasing_permission(self):
        g=self.game(hand=('min.rule','min.rule','min.removeone','spell'));self.play(g,'min.rule');self.play(g,'min.rule')
        self.assertEqual(len(g.state.players[1].player_effects),2)
        self.play(g,'min.removeone');self.assertEqual(len(g.state.players[1].player_effects),1)
        self.blocked(g,'spell');self.portable(g)

    def test_conflicting_type_rules_intersect_without_new_policy(self):
        g=self.game(hand=('spell.rule','spell.wait','minion','spell'));self.play(g,'spell.rule');self.play(g,'spell.wait')
        g.apply(SelectChoice(1,g.state.pending_choice.id,('rule',)))
        self.blocked(g,'minion');self.blocked(g,'spell');self.portable(g)

    def test_explicit_removal_restores_new_manual_actions(self):
        g=self.game(hand=(MIN,'min.remove','spell'));self.play(g,MIN);self.play(g,'min.remove')
        self.assertFalse(g.state.players[1].player_effects);self.play(g,'spell',target=g.state.players[2].hero_id);self.portable(g)

    def test_actual_turn_cleanup_and_other_actor(self):
        g=self.game();self.play(g,MIN);g.apply(EndTurn(1));self.assertFalse(g.state.players[1].player_effects)
        self.play(g,'spell',2,g.state.players[1].hero_id);g.apply(EndTurn(2))
        self.play(g,'spell',target=g.state.players[2].hero_id);self.portable(g)

    def test_extra_actual_turn_does_not_extend_rule(self):
        g=self.game(hand=(MIN,'min.extra','spell'));self.play(g,MIN);self.play(g,'min.extra');g.apply(EndTurn(1))
        self.assertEqual(g.state.active_player,1);self.assertFalse(g.state.players[1].player_effects)
        self.play(g,'spell',target=g.state.players[2].hero_id);self.portable(g)

    def test_late_end_rule_retires_at_same_cleanup(self):
        g=self.game(hand=('spell',),board=('late',));g.apply(EndTurn(1))
        self.assertFalse(g.state.players[1].player_effects);self.portable(g)

    def test_waiting_accepted_minion_restores_rule_and_original_payment(self):
        g=self.game(hand=(MIN,'min.wait'));self.play(g,MIN);self.play(g,'min.wait');s=self.portable(g)
        restored=Game.from_snapshot(deepcopy(s),registry());choice=g.state.pending_choice.id
        for h in (g,restored):h.apply(SelectChoice(1,choice,('finish',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_spell_installs_incompatible_rule_after_acceptance_and_finishes(self):
        g=self.game(hand=('spell.wait','spell'));self.play(g,'spell.wait');s=self.portable(g)
        restored=Game.from_snapshot(s,registry());choice=g.state.pending_choice.id
        for h in (g,restored):h.apply(SelectChoice(1,choice,('rule',)))
        self.assertTrue(g.state.play_history[-1].completed);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1);self.blocked(g,'spell');self.portable(g)

    def test_failed_action_or_waiting_selection_preserves_boundary(self):
        g=self.game(hand=('spell.fault',MIN,'min.wait'));s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'spell.fault')
        self.assertEqual(g.snapshot(),s);self.play(g,MIN);self.play(g,'min.wait');s=self.portable(g)
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,g.state.pending_choice.id,('fail',)))
        self.assertEqual(g.snapshot(),s);self.portable(g)

    def test_original_payment_proof_checks_accepted_state_not_current_rule(self):
        g=self.game(hand=(SPELL,'spell'));self.play(g,SPELL);g._state.action_number+=1
        r=Resolution(g);eid=self.card(g,'spell');entity=r.state.entities[eid];q=quote_cost(r.state,r.registry,entity)
        p=prepare_play(r.state,r.registry,entity,r.state.players[2].hero_id,q)
        _,proof=capture_hand_cost_proof(r,p,q);validate_hand_cost_proof(proof,r.registry)
        bad=deepcopy(proof);e=bad.payment_state.players[1].player_effects[0]
        bad.payment_state.players[1].player_effects[0]=replace(e,spec_id=MIN_RULE)
        with self.assertRaisesRegex(ValueError,'type permission'):validate_hand_cost_proof(bad,r.registry)

    def test_declared_policy_is_strict_independent_and_fingerprint_bound(self):
        spec=registry().player_effect(MIN_RULE)
        for kw in ({'allowed_card_types':[]},{'allowed_card_types':('MINION',)},
                {'allowed_card_types':(CardType.MINION,CardType.MINION)},
                {'allowed_card_types':(CardType.HERO_POWER,)},{'allowed_card_types':()},
                {'target_policy':'spells_no_heroes'},{'kind':'persistent'},
                {'duration':1},{'triggers':(TriggerSpec('turn_ended','noop'),)}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):replace(spec,**kw)
        self.assertNotEqual(registry().fingerprint(),registry(CardType.SPELL).fingerprint())

    def test_unknown_stale_rule_wrong_registry_and_old_schema_rejected(self):
        g=self.game();self.play(g,MIN);s=self.portable(g)
        for field,value in (('spec_id','unknown'),('created_turn',0)):
            bad=deepcopy(s);bad['state']['players']['1']['player_effects'][0][field]=value
            with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry(CardType.SPELL))
        with self.assertRaises(SnapshotError):Game.from_snapshot({**s,'schema_version':249},registry())

    def test_public_commands_refuse_type_without_leaking_hidden_receipts(self):
        g=self.game();self.play(g,MIN);s=g.snapshot();port=g.for_player(1);view=port.observe()
        hand=view['observation']['players'][0]['hand'];ref=next(x['ref'] for x in hand if x['card_id']=='spell')
        reply=port.submit({'revision':view['revision'],'action':{'type':'play_card','card':ref}})
        self.assertFalse(reply['accepted']);self.assertEqual(reply['error'],'invalid_action')
        for seat in (1,2):
            effects=g.observe(seat)['players'][0]['player_effects'];self.assertEqual(effects[0]['effect_kind'],'turn_rule')
            self.assertEqual(set(effects[0]),{'effect_key','card_id','effect_kind','remaining_turns'})
        self.assertEqual(g.snapshot(),s);self.portable(g)

if __name__=='__main__':unittest.main()
