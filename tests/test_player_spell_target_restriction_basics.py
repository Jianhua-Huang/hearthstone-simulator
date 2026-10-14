"""One native current-turn actor rule shares target selection and old acceptance."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,IllegalAction,Keyword,PlayCard,
    PlayerEffectSpec,PlayerSetup,QueueTurns,Registry,ResolutionError,Scenario,SelectChoice,
    SnapshotError,TargetSpec,TriggerSpec,UseHeroPower)
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Damage,DamageBatch,DamageKind,Destroy,
    InvokeBehavior,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.player_effects import AddPlayerEffect,RemovePlayerEffect
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.targeting import accepts_target
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]
PIN='e14cd4d0d857d80e15612941b6bcad83c22e6f784f6d7cf108c865f5a6e0152d'
ARC='RLK_218'; RULE='target.current.spells.no.heroes'

def evidence():
    p=json.loads((ROOT/'data/support/player-spell-target-restriction-basics.json').read_bytes())
    if canonical_digest(p)!=PIN: raise ValueError('Player target rule full raw changed')
    return p

def registry():
    r=Registry('isolated-player-spell-target-rule-v1'); raw=evidence()['records'][0]
    r.register_card(CardDefinition('hero','Diagnostic hero',CardType.HERO,health=60,metadata=metadata()))
    r.register_card(CardDefinition('plain','Diagnostic minion',CardType.MINION,health=20,metadata=metadata()))
    r.register_behavior('noop',lambda c:())
    r.register_behavior('activate',lambda c:(AddPlayerEffect(c.player_id,RULE,c.source_id),))
    r.register_card(CardDefinition(ARC,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        spell_damage=2,battlecry='activate',metadata=metadata_from_record(raw)))
    r.register_player_effect(PlayerEffectSpec(RULE,ARC,kind='turn_rule',target_policy='spells_no_heroes'))
    r.register_behavior('hit',lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),))
    r.register_card(CardDefinition('spell','Diagnostic targeted spell',CardType.SPELL,cost=1,on_play='hit',targeting=TargetSpec(),metadata=metadata()))
    r.register_card(CardDefinition('power','Diagnostic targeted power',CardType.HERO_POWER,on_use='noop',targeting=TargetSpec(),metadata=metadata()))
    r.register_card(CardDefinition('battlecry','Diagnostic targeted battlecry',CardType.MINION,health=5,battlecry='noop',targeting=TargetSpec(),metadata=metadata()))
    def fail(c): raise ResolutionError('Diagnostic target rule failure')
    r.register_behavior('fault',fail)
    def source(c): return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==ARC)
    def waiting(c): return (RequestChoice(c.player_id,(
        ChoiceOption('hit','Hit',(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),)),
        ChoiceOption('restrict','Restrict then hit',(AddPlayerEffect(c.player_id,RULE,c.source_id),
                                                   Damage(c.target_id,1,c.source_id,DamageKind.SPELL))),
        ChoiceOption('fault','Fail',(InvokeBehavior('fault',c.source_id,c.player_id),)),
    ),c.source_id),)
    r.register_behavior('waiting',waiting)
    r.register_card(CardDefinition('waiting','Diagnostic waiting spell',CardType.SPELL,cost=1,on_play='waiting',targeting=TargetSpec(),metadata=metadata()))
    targeted={'silence':lambda c:(Silence(c.target_id),), 'destroy':lambda c:(Destroy(c.target_id,c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),), 'control':lambda c:(ChangeControl(c.target_id,2),)}
    scripts={'activate':lambda c:(AddPlayerEffect(c.player_id,RULE,c.source_id),),
        'auto':lambda c:(CastSpell(c.player_id,'spell',c.source_id),),
        'auto-other':lambda c:(CastSpell(2,'spell',c.source_id),),
        'extra':lambda c:(QueueTurns((c.player_id,),c.source_id),),
        'area':lambda c:(DamageBatch(tuple(Damage(c.state.players[p].hero_id,1,c.source_id,DamageKind.SPELL) for p in (1,2))),),
        'remove':lambda c:tuple(RemovePlayerEffect(c.player_id,e.id) for e in c.state.players[c.player_id].player_effects),
        'fault':lambda c:(AddPlayerEffect(c.player_id,RULE,c.source_id),InvokeBehavior('fault',c.source_id,c.player_id)),
        'late':lambda c:(RequestChoice(c.player_id,(ChoiceOption('add','Add',(AddPlayerEffect(c.player_id,RULE,c.source_id),)),),c.source_id),)}
    for name,fn in {**targeted,**scripts}.items():
        r.register_behavior('diag.'+name,fn)
        r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.SPELL,on_play='diag.'+name,
            requires_target=name in targeted,metadata=metadata()))
    def end(c):
        return (AddPlayerEffect(c.player_id,RULE,c.source_id),) if c.event.player_id==c.player_id else ()
    r.register_behavior('end',end)
    r.register_card(CardDefinition('ending','Diagnostic late end rule',CardType.MINION,health=5,
        triggers=(TriggerSpec('turn_ended','end'),),metadata=metadata()))
    return r

class PlayerSpellTargetRuleTests(unittest.TestCase):
    def game(self,hand=(ARC,'spell','spell'),board=('plain',),enemy=('plain',)):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*5,hero_power_card_id='power',max_mana=10,mana=10),
            PlayerSetup('hero',hand=('spell',),board=enemy,deck=('plain',)*5,hero_power_card_id='power',max_mana=10,mana=10)),seed=133),registry())
    def card(self,g,name,player=1): return next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==name)
    def play(self,g,name,target=None): return g.apply(PlayCard(g.state.active_player,self.card(g,name,g.state.active_player),target))
    def heroes(self,g,source): return tuple(i for i in g.legal_targets(source) if g.state.entities[i].kind==CardType.HERO)
    def portable(self,g):
        s=g.snapshot(); self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s); self.assertEqual(replay(build_replay(g),registry()).snapshot(),s); return s

    def test_full_native_source_and_static_policy_are_pinned(self):
        p=evidence(); self.assertEqual(p['records'][0]['id'],ARC); self.assertFalse(p['CN_calibrated'])
        self.assertEqual((registry().card(ARC).cost,registry().card(ARC).spell_damage),(3,2))

    def test_rule_kind_and_other_player_effect_text_cannot_be_combined(self):
        spec=registry().player_effect(RULE)
        for kw in ({'kind':'persistent'},{'target_policy':None},{'target_policy':'unknown'},
                {'duration':1},{'tick_event':'turn_ended'},{'spell_damage':1}):
            with self.subTest(kw=kw),self.assertRaises(ValueError): replace(spec,**kw)

    def test_native_battlecry_blocks_both_spell_heroes_but_preserves_minions(self):
        g=self.game(); spell=self.card(g,'spell'); self.assertEqual(len(self.heroes(g,spell)),2)
        self.play(g,ARC); self.assertEqual(self.heroes(g,spell),())
        self.assertEqual(len(g.legal_targets(spell)),3); self.portable(g)

    def test_validation_and_enumeration_refuse_heroes_before_payment(self):
        g=self.game(); self.play(g,ARC); spell=self.card(g,'spell'); hero=g.state.players[2].hero_id; before=g.snapshot()
        self.assertFalse(any(isinstance(a,PlayCard) and a.entity_id==spell and a.target_id==hero for a in g.legal_actions()))
        with self.assertRaises(IllegalAction): g.apply(PlayCard(1,spell,hero))
        self.assertEqual(g.snapshot(),before); self.play(g,'spell',g.state.players[2].board[0]); self.portable(g)

    def test_hero_power_and_minion_battlecry_keep_hero_targets(self):
        g=self.game(hand=(ARC,'spell','battlecry')); self.play(g,ARC)
        self.assertEqual(len(self.heroes(g,g.state.players[1].hero_power_id)),2)
        self.assertEqual(len(self.heroes(g,self.card(g,'battlecry'))),2)
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,g.state.players[2].hero_id)); self.play(g,'battlecry',g.state.players[2].hero_id); self.portable(g)

    def test_untargeted_spell_damage_to_heroes_is_not_prohibited(self):
        g=self.game(hand=(ARC,'area')); self.play(g,ARC); self.play(g,'area')
        self.assertEqual([g.state.entities[g.state.players[p].hero_id].health for p in (1,2)],[57,57]); self.portable(g)

    def test_source_silence_death_return_and_control_do_not_remove_actor_rule(self):
        for name in ('silence','destroy','bounce','control'):
            with self.subTest(name=name):
                g=self.game(hand=(ARC,name,'spell')); self.play(g,ARC)
                self.play(g,name,g.state.players[1].board[-1]); self.assertEqual(self.heroes(g,self.card(g,'spell')),()); self.portable(g)

    def test_actual_turn_cleanup_restores_targets_and_does_not_restrict_other_player(self):
        g=self.game(); self.play(g,ARC); g.apply(EndTurn(1)); self.assertFalse(g.state.players[1].player_effects)
        self.assertEqual(len(self.heroes(g,self.card(g,'spell',2))),2)
        g.apply(EndTurn(2)); self.assertEqual(len(self.heroes(g,self.card(g,'spell'))),2); self.portable(g)

    def test_extra_actual_turn_also_retires_previous_turn_rule(self):
        g=self.game(hand=(ARC,'extra','spell')); self.play(g,ARC); self.play(g,'extra'); g.apply(EndTurn(1))
        self.assertEqual(g.state.active_player,1); self.assertEqual(len(self.heroes(g,self.card(g,'spell'))),2); self.portable(g)

    def test_late_end_boundary_install_is_retired_before_next_actual_turn(self):
        g=self.game(hand=('spell',),board=('ending',)); g.apply(EndTurn(1))
        self.assertFalse(g.state.players[1].player_effects); self.portable(g)

    def test_rule_is_independent_of_secret_area_capacity(self):
        g=self.game(hand=('activate',)*6+('spell',))
        for _ in range(6): self.play(g,'activate')
        self.assertEqual(len(g.state.players[1].player_effects),6)
        self.assertEqual(self.heroes(g,self.card(g,'spell')),()); self.portable(g)

    def test_multiple_rules_and_explicit_removal_use_existing_instances(self):
        g=self.game(hand=('activate','activate','remove','spell')); self.play(g,'activate'); self.play(g,'activate')
        self.assertEqual(len(g.state.players[1].player_effects),2); self.play(g,'remove')
        self.assertEqual(len(self.heroes(g,self.card(g,'spell'))),2); self.portable(g)

    def test_automatic_selection_respects_same_actor_rule_as_explicit_local_policy(self):
        g=self.game(hand=(ARC,'auto')); self.play(g,ARC); self.play(g,'auto')
        cast=g.state.cast_history[-1]; self.assertNotIn(cast.target_id,[g.state.players[p].hero_id for p in (1,2)]); self.portable(g)

    def test_common_automatic_predicate_is_actor_specific(self):
        g=self.game(); self.play(g,ARC); state=g.state; source=state.entities[self.card(g,'spell')]
        self.assertFalse(accepts_target(state,g.registry,source,g.registry.card('spell'),state.players[2].hero_id,automatic=True))
        other=state.entities[self.card(g,'spell',2)]
        self.assertTrue(accepts_target(state,g.registry,other,g.registry.card('spell'),state.players[1].hero_id,automatic=True))

    def test_waiting_accepted_minion_target_restores_original_actor_effects(self):
        g=self.game(hand=(ARC,'waiting')); self.play(g,ARC); self.play(g,'waiting',g.state.players[2].board[0])
        wait=self.portable(g); self.assertEqual(len(g.state.players[1].player_effects),1)
        h=Game.from_snapshot(deepcopy(wait),registry()); choice=g.state.pending_choice.id
        g.apply(SelectChoice(1,choice,('hit',))); h.apply(SelectChoice(1,choice,('hit',)))
        self.assertEqual(g.snapshot(),h.snapshot()); self.portable(g)

    def test_rule_installed_after_old_target_acceptance_does_not_revoke_target(self):
        g=self.game(hand=('waiting','activate')); self.play(g,'waiting',g.state.players[2].hero_id)
        self.portable(g); g.apply(SelectChoice(1,g.state.pending_choice.id,('restrict',)))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,59)
        self.assertEqual(len(g.state.players[1].player_effects),1); self.portable(g)

    def test_historical_target_receipt_remains_valid_after_rule_expiry(self):
        g=self.game(); self.play(g,ARC); self.play(g,'spell',g.state.players[2].board[0])
        old=g.state.play_history[-1]
        g.apply(EndTurn(1)); self.assertFalse(g.state.players[1].player_effects)
        self.assertEqual(g.state.play_history[-1],old); self.portable(g)

    def test_failure_rolls_back_new_rule_and_choice_preserves_previous_rule(self):
        g=self.game(hand=('fault',ARC,'waiting')); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'fault')
        self.assertEqual(g.snapshot(),before); self.play(g,ARC); self.play(g,'waiting',g.state.players[2].board[0]); before=g.snapshot()
        with self.assertRaises(ResolutionError): g.apply(SelectChoice(1,g.state.pending_choice.id,('fault',)))
        self.assertEqual(g.snapshot(),before); self.portable(g)

    def test_public_effect_reports_current_turn_kind_without_private_source_or_receipt(self):
        g=self.game(); self.play(g,ARC); before=g.snapshot()
        for seat in (1,2):
            view=g.observe(seat); effects=view['players'][0]['player_effects']
            self.assertEqual(effects[0]['effect_kind'],'turn_rule')
            text=json.dumps(effects)
            for private in ('source_id','entered_order','target_policy','original_state_hash'): self.assertNotIn(private,text)
        self.assertEqual(g.snapshot(),before)

    def test_stale_current_rule_and_unknown_policy_or_old_schema_are_rejected(self):
        g=self.game(); self.play(g,ARC); self.play(g,'spell',g.state.players[2].board[0]); snapshot=self.portable(g)
        bad=deepcopy(snapshot); bad['state']['players']['1']['player_effects'][0]['created_turn']=0
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())
        bad=deepcopy(snapshot); bad['state']['players']['1']['player_effects'][0]['spec_id']='unknown.target.rule'
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())
        bad=deepcopy(snapshot); bad['schema_version']=236
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())

if __name__=='__main__': unittest.main()
