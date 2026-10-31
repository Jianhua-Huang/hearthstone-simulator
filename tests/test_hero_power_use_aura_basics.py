"""Finite and unbounded native permissions reuse each installed power's uses."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,HeroPowerUseAuraSpec,
    IllegalAction,PlayCard,PlayerSetup,Registry,ResolutionError,Scenario,SelectChoice,SnapshotError,
    UseHeroPower)
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Destroy,GainArmor,
    InvokeBehavior,ReplaceHeroPower,RequestChoice,ReturnToHand,SetHeroPowerUses,Silence,Transform)
from hs_sim.engine.hero_powers import AddHeroPower,effective_use_limit
from hs_sim.engine.dormancy import AwakenMinion,MakeDormant
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]; FINITE='AT_080'; UNBOUNDED='AT_008'
PIN='f57ef1de6abf62ed4042432bd97884706b0ed4a998c635e271ed8d14655ff2c9'
def evidence():
    p=json.loads((ROOT/'data/support/hero-power-use-aura-basics.json').read_bytes())
    if canonical_digest(p)!=PIN: raise ValueError('Native use aura raw changed')
    return p
def registry():
    r=Registry('isolated-native-hero-power-use-aura-v1'); raw={x['id']:x for x in evidence()['records']}
    r.register_card(CardDefinition('hero','Diagnostic hero',CardType.HERO,health=80,metadata=metadata()))
    r.register_card(CardDefinition('plain','Diagnostic minion',CardType.MINION,health=5,metadata=metadata()))
    for name,cap in ((FINITE,2),(UNBOUNDED,None)):
        c=raw[name]; r.register_card(CardDefinition(name,c['name'],CardType.MINION,cost=c['cost'],attack=c['attack'],health=c['health'],
            hero_power_use_aura=HeroPowerUseAuraSpec(cap),metadata=metadata_from_record(c)))
    r.register_behavior('armor',lambda c:(GainArmor(c.player_id,1),))
    for name,cap in (('power',1),('richer',3),('replacement',1)):
        r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.HERO_POWER,cost=2,on_use='armor',uses_per_turn=cap,metadata=metadata()))
    def explode(c): raise ResolutionError('Diagnostic native use-cap failure')
    r.register_behavior('explode',explode)
    def wait(c): return (RequestChoice(c.player_id,(
        ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
        ChoiceOption('fault','Fail',(InvokeBehavior('explode',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior('waiting',wait)
    r.register_card(CardDefinition('waiting','Diagnostic waiting power',CardType.HERO_POWER,cost=2,on_use='waiting',metadata=metadata()))
    targeted={'silence':lambda c:(Silence(c.target_id),),'destroy':lambda c:(Destroy(c.target_id,c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),'transform':lambda c:(Transform(c.target_id,'plain'),),
        'control':lambda c:(ChangeControl(c.target_id,2),),'sleep':lambda c:(MakeDormant(c.target_id,None),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),'base-copy':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),)}
    for name,script in targeted.items():
        r.register_behavior(name,script); r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.SPELL,
            on_play=name,requires_target=True,metadata=metadata()))
    scripts={'replace':lambda c:(ReplaceHeroPower(c.player_id,'replacement',source_id=c.source_id),),
        'add':lambda c:(AddHeroPower(c.player_id,'replacement',c.source_id),),
        'set-three':lambda c:(SetHeroPowerUses(c.player_id,3),),
        'awake':lambda c:(AwakenMinion(c.state.players[c.player_id].board[0],c.source_id),),
        'fault':lambda c:(SetHeroPowerUses(c.player_id,3),InvokeBehavior('explode',c.source_id,c.player_id))}
    for name,script in scripts.items():
        r.register_behavior(name,script); r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.SPELL,on_play=name,metadata=metadata()))
    return r

class HeroPowerUseAuraTests(unittest.TestCase):
    def game(self,board=(FINITE,),hand=('silence','destroy'),power='power',enemy_board=()):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*6,hero_power_card_id=power,max_mana=10,mana=10),
            PlayerSetup('hero',hand=('silence',),board=enemy_board,deck=('plain',)*6,hero_power_card_id='power',max_mana=10,mana=10)),seed=140),registry())
    def card(self,g,name,p=1): return next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
    def play(self,g,name,target=None): return g.apply(PlayCard(g.state.active_player,self.card(g,name,g.state.active_player),target))
    def use(self,g,p=1,power=None): return g.apply(UseHeroPower(p,power or g.state.players[p].hero_power_id))
    def power(self,g,p=1): return g.state.entities[g.state.players[p].hero_power_id]
    def limit(self,g,p=1): return effective_use_limit(g.state,self.power(g,p))
    def armor(self,g,p=1): return g.state.entities[g.state.players[p].hero_id].armor
    def portable(self,g):
        s=g.snapshot(); self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s); self.assertEqual(replay(build_replay(g),registry()).snapshot(),s); return s
    def reject(self,g):
        s=g.snapshot()
        with self.assertRaises(IllegalAction): self.use(g)
        self.assertEqual(g.snapshot(),s)

    def test_two_necessary_real_sources_five_raw_rows_remain_uncalibrated(self):
        p=evidence(); self.assertEqual(len(p['records']),5); self.assertFalse(p['CN_calibrated']); self.assertEqual(p['new_combinations'],0)
        self.assertEqual(registry().card(FINITE).hero_power_use_aura.limit,2); self.assertIsNone(registry().card(UNBOUNDED).hero_power_use_aura.limit)
        self.assertNotIn('CORE_AT_008',registry().cards)

    def test_cap_is_positive_integer_or_none_and_native_only(self):
        for value in (True,False,0,-1,2.0,'2'):
            with self.subTest(value=value),self.assertRaises(ValueError): HeroPowerUseAuraSpec(value)
        for kind in (CardType.SPELL,CardType.HERO_POWER,CardType.HERO,CardType.WEAPON):
            with self.subTest(kind=kind),self.assertRaises(ValueError): Registry('bad').register_card(CardDefinition('bad','bad',kind,hero_power_use_aura=HeroPowerUseAuraSpec()))

    def test_finite_two_uses_pay_twice_and_do_not_rewrite_base_cap(self):
        g=self.game(); self.assertEqual(self.limit(g),2); self.use(g); self.use(g); self.reject(g)
        self.assertEqual((self.armor(g),g.state.players[1].mana,self.power(g).use_limit,self.power(g).uses_this_turn),(2,6,1,2)); self.portable(g)

    def test_true_unbounded_uses_still_require_actual_mana(self):
        g=self.game(board=(UNBOUNDED,)); self.assertIsNone(self.limit(g))
        for _ in range(5): self.use(g)
        self.assertEqual((self.armor(g),self.power(g).use_limit,self.power(g).uses_this_turn),(5,1,5))
        self.reject(g); self.portable(g)

    def test_effective_cap_query_is_pure_and_opponent_gets_no_own_source_bonus(self):
        g=self.game(); before=g.snapshot(); self.assertEqual((self.limit(g),self.limit(g,2)),(2,1)); self.assertEqual(g.snapshot(),before)

    def test_same_finite_sources_take_max_instead_of_adding_permissions(self):
        g=self.game(board=(FINITE,FINITE)); self.use(g); self.use(g); self.reject(g); self.assertEqual(self.limit(g),2); self.portable(g)

    def test_unbounded_source_dominates_finite_source_until_it_retires(self):
        g=self.game(board=(FINITE,UNBOUNDED),hand=('destroy',)); self.assertIsNone(self.limit(g)); self.use(g); self.use(g)
        self.play(g,'destroy',g.state.players[1].board[1]); self.assertEqual(self.limit(g),2); self.reject(g); self.portable(g)

    def test_larger_intrinsic_or_explicit_base_cap_is_preserved(self):
        g=self.game(power='richer'); self.assertEqual(self.limit(g),3); self.use(g); self.use(g); self.use(g); self.reject(g); self.portable(g)
        h=self.game(hand=('set-three','silence')); self.play(h,'set-three'); self.play(h,'silence',h.state.players[1].board[0])
        self.assertEqual((self.limit(h),self.power(h).use_limit),(3,3)); self.portable(h)

    def test_source_silence_after_one_use_does_not_leave_second_permission(self):
        g=self.game(); self.use(g); self.play(g,'silence',g.state.players[1].board[0]); self.assertEqual(self.limit(g),1); self.reject(g); self.portable(g)

    def test_source_death_return_or_transform_retires_without_refunding_uses(self):
        for script in ('destroy','bounce','transform'):
            with self.subTest(script=script):
                g=self.game(hand=(script,)); self.use(g); self.play(g,script,g.state.players[1].board[0])
                self.assertEqual(self.limit(g),1); self.assertEqual(self.power(g).uses_this_turn,1); self.reject(g); self.portable(g)

    def test_infinite_source_retirement_keeps_all_prior_used_units(self):
        g=self.game(board=(UNBOUNDED,)); self.use(g); self.use(g); self.use(g)
        self.play(g,'silence',g.state.players[1].board[0]); self.assertEqual((self.limit(g),self.power(g).uses_this_turn),(1,3)); self.reject(g); self.portable(g)

    def test_source_enters_after_base_use_without_resetting_that_use(self):
        g=self.game(board=(),hand=(FINITE,)); self.use(g); self.play(g,FINITE)
        self.assertEqual((self.limit(g),self.power(g).uses_this_turn),(2,1)); self.use(g); self.reject(g); self.portable(g)

    def test_dormancy_and_awakening_change_live_permission_only(self):
        g=self.game(hand=('sleep','awake')); self.play(g,'sleep',g.state.players[1].board[0]); self.assertEqual(self.limit(g),1)
        self.use(g); self.play(g,'awake'); self.assertEqual((self.limit(g),self.power(g).uses_this_turn),(2,1)); self.use(g); self.portable(g)

    def test_control_transfer_moves_contribution_to_current_controller(self):
        g=self.game(hand=('control',)); self.play(g,'control',g.state.players[1].board[0]); self.assertEqual((self.limit(g),self.limit(g,2)),(1,2))
        g.apply(EndTurn(1)); self.use(g,2); self.use(g,2); self.portable(g)

    def test_current_copy_keeps_permission_after_original_dies(self):
        g=self.game(hand=('copy','destroy')); original=g.state.players[1].board[0]; self.play(g,'copy',original); self.play(g,'destroy',original)
        self.assertEqual(self.limit(g),2); self.use(g); self.use(g); self.portable(g)

    def test_current_copy_of_silenced_source_is_inert_but_base_copy_restores(self):
        for mode,cap in (('copy',1),('base-copy',2)):
            with self.subTest(mode=mode):
                g=self.game(hand=('silence',mode)); original=g.state.players[1].board[0]
                self.play(g,'silence',original); self.play(g,mode,original); self.assertEqual(self.limit(g),cap); self.portable(g)

    def test_each_actual_turn_resets_existing_power_uses_not_source_budget(self):
        g=self.game(); self.use(g); self.use(g); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(self.power(g).uses_this_turn,0); self.use(g); self.use(g); self.portable(g)

    def test_replaced_power_reads_current_source_using_existing_replacement_policy(self):
        g=self.game(hand=('replace',)); self.use(g); self.play(g,'replace')
        self.assertEqual(self.power(g).card_id,'replacement'); self.assertEqual(self.limit(g),2); self.portable(g)

    def test_additional_power_reads_source_without_merging_independent_used_counts(self):
        g=self.game(hand=('add',)); self.play(g,'add'); ids=g.state.players[1].hero_power_ids
        for power in ids: self.use(g,power=power); self.use(g,power=power)
        self.assertEqual([g.state.entities[i].uses_this_turn for i in ids],[2,2]); self.portable(g)

    def test_waiting_skill_keeps_paid_use_through_restore_and_resume(self):
        g=self.game(power='waiting'); self.use(g); waiting=self.portable(g); h=Game.from_snapshot(deepcopy(waiting),registry()); choice=g.state.pending_choice.id
        g.apply(SelectChoice(1,choice,('ok',))); h.apply(SelectChoice(1,choice,('ok',)))
        self.assertEqual(g.snapshot(),h.snapshot()); self.assertEqual(self.power(g).uses_this_turn,1); self.use(g); self.portable(g)

    def test_action_and_later_choice_errors_roll_back_base_cap_and_used_count(self):
        g=self.game(hand=('fault',)); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'fault')
        self.assertEqual(g.snapshot(),before)
        h=self.game(power='waiting'); self.use(h); before=h.snapshot()
        with self.assertRaises(ResolutionError): h.apply(SelectChoice(1,h.state.pending_choice.id,('fault',)))
        self.assertEqual(h.snapshot(),before); self.portable(h)

    def test_player_view_shows_same_nullable_effective_cap_without_source_proof(self):
        for board,cap in (((FINITE,),2),((UNBOUNDED,),None)):
            with self.subTest(cap=cap):
                g=self.game(board=board); before=g.snapshot(); view=g.for_player(1).observe()['observation']
                players=view['players']; player=players[0] if type(players)is list else players.get('1',players.get(1))
                self.assertEqual(player['hero_power']['use_limit'],cap); self.assertEqual(view['version'],'player-view-v122')
                text=json.dumps(view); self.assertNotIn('hero_power_use_aura',text); self.assertNotIn('ability_id',text); self.assertEqual(g.snapshot(),before)

    def test_unknown_cap_missing_state_field_and_old_schema_are_rejected(self):
        g=self.game(); snapshot=self.portable(g); source=g.state.players[1].board[0]
        for what in ('changed','missing','origin'):
            bad=deepcopy(snapshot); abilities=bad['state']['entities'][str(source)]['abilities']; row=next(a for a in abilities if a['kind']=='hero_power_use_aura')
            if what=='changed': row['hero_power_use_aura']['limit']=3
            elif what=='missing': del row['hero_power_use_aura']
            else: row['origin']='granted'
            with self.subTest(what=what),self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())
        bad=deepcopy(snapshot); bad['schema_version']=240
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())

if __name__=='__main__': unittest.main()
