"""Native global Hero Power eligibility, with accepted-window preservation."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,IllegalAction,Keyword,KeywordAuraSpec,
    PlayCard,PlayerSetup,Registry,ResolutionError,Scenario,SelectChoice,SnapshotError,
    TriggerHeroPower,TriggerSpec,UseHeroPower)
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Destroy,
    GainArmor,GrantKeyword,InvokeBehavior,ReplaceHeroPower,RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.dormancy import AwakenMinion,MakeDormant
from hs_sim.engine.hero_powers import AddHeroPower,hero_powers_can_activate
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]; MIND='ICC_902'; FLAG=Keyword.HERO_POWER_SUPPRESSOR
PIN='34edcf15375e26c61048fb435653c3e5f0ca5c1729e276482825e271c68a5d0b'
def evidence():
    p=json.loads((ROOT/'data/support/hero-power-prohibition-basics.json').read_bytes())
    if canonical_digest(p)!=PIN: raise ValueError('Hero Power prohibition raw changed')
    return p
def registry():
    r=Registry('isolated-native-hero-power-prohibition-v1'); raw=next(x for x in evidence()['records'] if x['id']==MIND)
    r.register_card(CardDefinition('hero','Diagnostic hero',CardType.HERO,health=80,metadata=metadata()))
    r.register_card(CardDefinition('plain','Diagnostic minion',CardType.MINION,health=5,metadata=metadata()))
    r.register_card(CardDefinition(MIND,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=(FLAG,),metadata=metadata_from_record(raw)))
    r.register_behavior('armor',lambda c:(GainArmor(c.player_id,2),))
    r.register_card(CardDefinition('active','Diagnostic active power',CardType.HERO_POWER,cost=2,on_use='armor',metadata=metadata()))
    r.register_card(CardDefinition('new-active','Diagnostic replaced power',CardType.HERO_POWER,cost=2,on_use='armor',metadata=metadata()))
    r.register_behavior('passive',lambda c:(GainArmor(c.player_id,1),) if c.event.player_id==c.player_id else ())
    r.register_card(CardDefinition('passive','Diagnostic passive power',CardType.HERO_POWER,passive_hero_power=True,
        triggers=(TriggerSpec('turn_started','passive'),),metadata=metadata()))
    r.register_card(CardDefinition('end-passive','Diagnostic end passive power',CardType.HERO_POWER,passive_hero_power=True,
        triggers=(TriggerSpec('turn_ended','passive'),),metadata=metadata()))
    r.register_behavior('bookkeep',lambda c:(ReplaceHeroPower(c.player_id,'new-active',source_id=c.source_id),) if c.event.player_id==c.player_id else ())
    r.register_card(CardDefinition('updating','Diagnostic ordinary power with maintenance',CardType.HERO_POWER,cost=2,on_use='armor',
        triggers=(TriggerSpec('turn_started','bookkeep'),),metadata=metadata()))
    def explode(c): raise ResolutionError('Diagnostic Hero Power prohibition failure')
    r.register_behavior('explode',explode)
    def waiting(c): return (RequestChoice(c.player_id,(
        ChoiceOption('ok','Continue',(Summon(c.player_id,MIND),GainArmor(c.player_id,2))),
        ChoiceOption('fault','Fail',(Summon(c.player_id,MIND),InvokeBehavior('explode',c.source_id,c.player_id))),),c.source_id),)
    r.register_behavior('waiting',waiting)
    r.register_card(CardDefinition('waiting','Diagnostic accepted waiting power',CardType.HERO_POWER,cost=2,on_use='waiting',metadata=metadata()))
    targeted={'silence':lambda c:(Silence(c.target_id),),'destroy':lambda c:(Destroy(c.target_id,c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),'transform':lambda c:(Transform(c.target_id,'plain'),),
        'control':lambda c:(ChangeControl(c.target_id,2),),'sleep':lambda c:(MakeDormant(c.target_id,None),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'print-copy':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),)}
    for name,script in targeted.items():
        r.register_behavior(name,script); r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.SPELL,
            on_play=name,requires_target=True,metadata=metadata()))
    scripts={'proxy':lambda c:(TriggerHeroPower(c.player_id,c.source_id),),
        'install-passive':lambda c:(ReplaceHeroPower(c.player_id,'passive',source_id=c.source_id),),
        'awake':lambda c:(AwakenMinion(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==MIND),c.source_id),),
        'replace':lambda c:(ReplaceHeroPower(c.player_id,'new-active',source_id=c.source_id),),
        'add':lambda c:(AddHeroPower(c.player_id,'new-active',c.source_id),),
        'summon':lambda c:(Summon(c.player_id,MIND),),
        'fault':lambda c:(Summon(c.player_id,MIND),InvokeBehavior('explode',c.source_id,c.player_id))}
    for name,script in scripts.items():
        r.register_behavior(name,script); r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.SPELL,on_play=name,metadata=metadata()))
    def arrive(c):
        return (Summon(c.player_id,MIND),) if c.event.player_id==c.player_id else ()
    def depart(c):
        return (Destroy(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==MIND),c.source_id),) if c.event.player_id==c.player_id else ()
    for name,script in (('arrive',arrive),('depart',depart)):
        r.register_behavior(name,script)
        r.register_card(CardDefinition(name,'Diagnostic earlier capture-window observer',CardType.MINION,health=5,
            triggers=(TriggerSpec('turn_started',name),),metadata=metadata()))
    return r

class HeroPowerProhibitionTests(unittest.TestCase):
    def game(self,hand=('silence','destroy','proxy'),board=(MIND,),power='active',enemy_power='active',enemy_board=()):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*5,hero_power_card_id=power,max_mana=10,mana=10),
            PlayerSetup('hero',hand=('silence',),board=enemy_board,deck=('plain',)*5,hero_power_card_id=enemy_power,max_mana=10,mana=10)),seed=138),registry())
    def card(self,g,name,p=1): return next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
    def play(self,g,name,target=None): return g.apply(PlayCard(g.state.active_player,self.card(g,name,g.state.active_player),target))
    def use(self,g,p=1,power=None): return g.apply(UseHeroPower(p,power or g.state.players[p].hero_power_id))
    def armor(self,g,p=1): return g.state.entities[g.state.players[p].hero_id].armor
    def portable(self,g):
        s=g.snapshot(); self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s); self.assertEqual(replay(build_replay(g),registry()).snapshot(),s); return s
    def blocked(self,g,p=1):
        before=g.snapshot()
        with self.assertRaisesRegex(IllegalAction,'disabled'): self.use(g,p)
        self.assertEqual(g.snapshot(),before)
        self.assertFalse(any(type(a) is UseHeroPower for a in g.legal_actions()))

    def test_one_real_adapter_four_sources_and_internal_flag_are_not_full_pool(self):
        p=evidence(); self.assertEqual(len(p['records']),4); self.assertFalse(p['CN_calibrated']); self.assertEqual(p['new_combinations'],0)
        self.assertEqual((registry().card(MIND).cost,registry().card(MIND).attack,registry().card(MIND).health),(3,2,5))
        self.assertNotIn('CORE_ICC_902',registry().cards)

    def test_native_marker_cannot_be_granted_or_declared_on_wrong_carriers(self):
        with self.assertRaises(ValueError): GrantKeyword(3,FLAG)
        with self.assertRaises(ValueError): KeywordAuraSpec(FLAG)
        for kind in (CardType.HERO,CardType.HERO_POWER,CardType.SPELL,CardType.WEAPON):
            with self.subTest(kind=kind),self.assertRaises(ValueError): Registry('wrong').register_card(CardDefinition('bad','bad',kind,keywords=(FLAG,)))

    def test_manual_both_players_are_blocked_without_payment_uses_or_history(self):
        g=self.game(); self.blocked(g); self.assertEqual(g.state.players[1].mana,10); self.assertFalse(g.state.hero_power_history)
        g.apply(EndTurn(1)); self.blocked(g,2); self.assertEqual(g.state.players[2].mana,10); self.portable(g)

    def test_opponent_controlled_source_also_blocks_the_active_player(self):
        g=self.game(board=(),enemy_board=(MIND,)); self.blocked(g); self.portable(g)

    def test_pure_global_query_has_no_state_effect(self):
        g=self.game(); before=g.snapshot(); self.assertFalse(hero_powers_can_activate(g.state)); self.assertEqual(g.snapshot(),before)

    def test_effect_activation_is_recorded_disabled_without_payment_use_or_rng(self):
        g=self.game(); before=g._rng.getstate(); self.play(g,'proxy'); record=g.state.hero_power_history[-1]
        self.assertEqual(record.failure,'disabled'); self.assertTrue(record.completed)
        self.assertEqual(record.payloads,())
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn,0); self.assertEqual(self.armor(g),0)
        self.assertEqual(g._rng.getstate(),before); self.portable(g)

    def test_effect_activation_of_passive_power_is_also_an_explicit_disabled_attempt(self):
        g=self.game(power='passive'); self.play(g,'proxy')
        self.assertEqual(g.state.hero_power_history[-1].failure,'disabled'); self.portable(g)

    def test_passive_start_payload_is_blocked_and_restored_after_source_silence(self):
        g=self.game(enemy_power='passive'); g.apply(EndTurn(1)); self.assertEqual(self.armor(g,2),0)
        self.play(g,'silence',g.state.players[1].board[0]); g.apply(EndTurn(2)); g.apply(EndTurn(1))
        self.assertEqual(self.armor(g,2),1); self.portable(g)

    def test_passive_end_payload_is_blocked_without_stopping_turn_progress(self):
        g=self.game(power='end-passive'); g.apply(EndTurn(1)); self.assertEqual(self.armor(g),0)
        self.assertEqual(g.state.active_player,2); self.portable(g)

    def test_ordinary_power_maintenance_listener_keeps_updating_under_prohibition(self):
        g=self.game(enemy_power='updating'); old=g.state.players[2].hero_power_id; g.apply(EndTurn(1))
        new=g.state.players[2].hero_power_id; self.assertNotEqual(old,new)
        self.assertEqual(g.state.entities[new].card_id,'new-active'); self.blocked(g,2); self.portable(g)

    def test_replacement_keeps_global_disable_without_changing_use_budget(self):
        g=self.game(hand=('replace',)); self.play(g,'replace')
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,'new-active'); self.blocked(g); self.portable(g)

    def test_additional_installed_powers_share_same_current_prohibition(self):
        g=self.game(hand=('add',)); self.play(g,'add'); before=g.snapshot()
        for power in g.state.players[1].hero_power_ids:
            with self.assertRaisesRegex(IllegalAction,'disabled'): self.use(g,power=power)
        self.assertEqual(g.snapshot(),before); self.portable(g)

    def test_source_silence_removes_gate_and_preserves_actual_payment(self):
        g=self.game(); self.play(g,'silence',g.state.players[1].board[0]); self.assertTrue(hero_powers_can_activate(g.state))
        self.use(g); self.assertEqual((self.armor(g),g.state.players[1].mana),(2,8)); self.portable(g)

    def test_source_death_return_or_transform_remove_current_gate(self):
        for script in ('destroy','bounce','transform'):
            with self.subTest(script=script):
                g=self.game(hand=(script,)); self.play(g,script,g.state.players[1].board[0])
                self.assertTrue(hero_powers_can_activate(g.state)); self.use(g); self.assertEqual(self.armor(g),2); self.portable(g)

    def test_dormant_carrier_does_not_gate_and_awakened_carrier_does(self):
        g=self.game(hand=('sleep','awake')); target=g.state.players[1].board[0]; self.play(g,'sleep',target)
        self.assertTrue(hero_powers_can_activate(g.state)); self.use(g); self.portable(g)
        self.play(g,'awake'); self.assertFalse(hero_powers_can_activate(g.state)); self.portable(g)

    def test_change_control_keeps_both_player_gate(self):
        g=self.game(hand=('control',)); self.play(g,'control',g.state.players[1].board[0])
        self.assertFalse(hero_powers_can_activate(g.state)); self.blocked(g); self.portable(g)

    def test_current_copy_keeps_active_native_gate_after_original_dies(self):
        g=self.game(hand=('copy','destroy')); original=g.state.players[1].board[0]
        self.play(g,'copy',original); self.play(g,'destroy',original); self.blocked(g); self.portable(g)

    def test_current_copy_of_silenced_source_is_inert(self):
        g=self.game(hand=('silence','copy')); original=g.state.players[1].board[0]
        self.play(g,'silence',original); self.play(g,'copy',original)
        self.assertTrue(hero_powers_can_activate(g.state)); self.use(g); self.portable(g)

    def test_printed_copy_restores_printed_native_gate(self):
        g=self.game(hand=('silence','print-copy')); original=g.state.players[1].board[0]
        self.play(g,'silence',original); self.play(g,'print-copy',original); self.blocked(g); self.portable(g)

    def test_multiple_sources_keep_gate_until_last_source_retires(self):
        g=self.game(hand=('destroy','destroy'),board=(MIND,MIND)); self.play(g,'destroy',g.state.players[1].board[0]); self.blocked(g)
        self.play(g,'destroy',g.state.players[1].board[0]); self.assertTrue(hero_powers_can_activate(g.state)); self.use(g); self.portable(g)

    def test_source_in_hand_does_not_gate_until_actual_board_entry(self):
        g=self.game(hand=(MIND,'proxy'),board=()); self.assertTrue(hero_powers_can_activate(g.state))
        self.play(g,MIND); self.blocked(g); self.portable(g)

    def test_accepted_waiting_power_finishes_when_source_appears_in_its_payload(self):
        g=self.game(board=(),power='waiting'); self.use(g); waiting=self.portable(g)
        h=Game.from_snapshot(deepcopy(waiting),registry()); choice=g.state.pending_choice.id
        g.apply(SelectChoice(1,choice,('ok',))); h.apply(SelectChoice(1,choice,('ok',)))
        self.assertEqual(g.snapshot(),h.snapshot()); self.assertEqual(self.armor(g),2)
        self.assertTrue(g.state.hero_power_history[-1].completed); self.assertFalse(hero_powers_can_activate(g.state)); self.portable(g)

    def test_passive_captured_before_source_arrives_keeps_its_accepted_window(self):
        g=self.game(hand=('install-passive',),board=('arrive',)); self.play(g,'install-passive')
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertFalse(hero_powers_can_activate(g.state)); self.assertEqual(self.armor(g),1); self.portable(g)

    def test_passive_captured_under_source_does_not_unblock_after_source_retires(self):
        g=self.game(hand=('install-passive',),board=('depart',MIND)); self.play(g,'install-passive')
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertTrue(hero_powers_can_activate(g.state)); self.assertEqual(self.armor(g),0); self.portable(g)

    def test_action_and_choice_failures_restore_source_gate_and_usage(self):
        g=self.game(hand=('fault',),board=()); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'fault')
        self.assertEqual(g.snapshot(),before); self.use(g); self.assertTrue(hero_powers_can_activate(g.state))
        h=self.game(board=(),power='waiting'); self.use(h); before=h.snapshot()
        with self.assertRaises(ResolutionError): h.apply(SelectChoice(1,h.state.pending_choice.id,('fault',)))
        self.assertEqual(h.snapshot(),before); self.portable(h)

    def test_tampered_native_origin_and_old_schema_are_rejected(self):
        g=self.game(); s=self.portable(g); source=g.state.players[1].board[0]
        bad=deepcopy(s); row=next(e for e in bad['state']['entities'][str(source)]['abilities'] if e['keyword']==FLAG.value)
        row['origin']='granted'
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())
        bad=deepcopy(s); bad['schema_version']=239
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())

    def test_player_views_hide_internal_proof_and_match_legal_action_gate(self):
        g=self.game(); before=g.snapshot(); self.blocked(g)
        for player in (1,2):
            text=json.dumps(g.for_player(player).observe())
            for key in ('source-contract-audit','ability_id','hero_power_history'): self.assertNotIn(key,text)
        self.assertEqual(g.snapshot(),before)

if __name__=='__main__': unittest.main()
