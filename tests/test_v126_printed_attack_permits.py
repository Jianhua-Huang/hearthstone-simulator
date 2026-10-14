"""Bounded public permit cases; AT_109 raw is demand, not CN calibration."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (ActivatedAbilitySpec, Attack, AttackPolicySpec, AttackSourceBinding,
    AttackSourcePolicy, CardClass, CardDefinition, CardMetadata, CardReference, CardType,
    EndTurn, Game, GrantAttackPolicy, GrantPrintedAttackPermit, IllegalAction, Keyword,
    PlayCard, PlayerSetup, PrintedAttackPolicyDeclaration as Declaration, PrintedAttackPermit,
    PrintedAttackPermitRequest, Registry, ResolutionError, Scenario, SelectChoice,
    SnapshotError, SummonStoredCard, TriggerSpec, UseHeroPower, UseMinionAbility,
    capture_printed_attack_permit, is_inspire)
from hs_sim.engine.attack_policies import current_policies
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy, EquipWeapon,
    Freeze, GainArmor, GrantKeyword, InvokeBehavior, RandomDamage, RefreshHeroPower, RequestChoice,
    ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.lifecycle import copy_attachments
from hs_sim.engine.magnetic import transferable_abilities
from hs_sim.engine.model import AbilityInstance, Zone, validate_invariants
from hs_sim.engine.printed_attack_permits import permitted_rows
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.resolver import default_mechanics


BAN=AttackPolicySpec('cannot_attack')


class PrintedAttackPermitTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('isolated-v126-printed-restriction-permits')
        self.r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=100))
        self.r.register_behavior('power',lambda c:[GainArmor(c.player_id,1)])
        self.r.register_card(CardDefinition('power','Power',CardType.HERO_POWER,cost=1,on_use='power'))
        self.r.register_behavior('inspire',self.inspire)
        self.r.register_behavior('noop',lambda c:[])
        self.unitdef('plain',())
        self.unitdef('watch',(BAN,),triggers=(TriggerSpec('hero_power_used','inspire'),))
        self.unitdef('double',(BAN,BAN))
        self.unitdef('noheroes',(BAN,AttackPolicySpec('cannot_attack_heroes')))
        self.unitdef('titan',(BAN,),keywords=(Keyword.CHARGE,Keyword.TITAN),
                     activated_abilities=tuple(ActivatedAbilitySpec(str(i),'noop') for i in range(3)))
        self.spell('permit',lambda c:self.permit(c,c.target_id),True)
        self.spell('permit_second',lambda c:self.permit(c,c.target_id,1),True)
        self.spell('copy',lambda c:[CopyMinion(c.target_id,c.player_id)],True)
        self.spell('basecopy',lambda c:[CopyMinion(c.target_id,c.player_id,mode='base')],True)
        self.spell('silence',lambda c:[Silence(c.target_id)],True)
        self.spell('kill',lambda c:[Destroy(c.target_id)],True)
        self.spell('transform',lambda c:[Transform(c.target_id,'watch')],True)
        self.spell('freeze',lambda c:[Freeze(c.target_id)],True)
        self.spell('dormant',lambda c:[MakeDormant(c.target_id,None)],True)
        self.spell('awaken',lambda c:[AwakenMinion(c.state.players[c.player_id].board[0])])
        self.spell('refresh',lambda c:[RefreshHeroPower(c.player_id)])
        self.spell('summon',lambda c:[Summon(c.player_id,'watch')])
        self.spell('transfer',lambda c:[ChangeControl(c.target_id,2)],True)
        self.spell('foreign',lambda c:[GrantAttackPolicy(c.target_id,BAN,source_id=c.source_id)],True)

    def unitdef(self,name,policies,**kw):
        kw.setdefault('keywords',(Keyword.CHARGE,))
        self.r.register_card(CardDefinition(name,name,CardType.MINION,cost=0,attack=1,health=30,
                                           attack_policies=policies,**kw))

    def spell(self,name,fn,target=False):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,requires_target=target))

    def request(self,c,target,index=0):
        return capture_printed_attack_permit(c.state,self.r,target,
            Declaration(c.state.entities[target].card_id,index))

    def permit(self,c,target,index=0):
        request=self.request(c,target,index)
        return [GrantPrintedAttackPermit(request)] if request else []

    def inspire(self,c):
        if not is_inspire(c.state,c.event,c.player_id): return []
        return self.permit(c,c.source_id)

    def game(self,board=('watch',),hand=(),enemy=('plain',),enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',board=board,hand=hand,hero_power_card_id='power',deck=('plain',)*6,mana=10,max_mana=10),
            PlayerSetup('hero',board=enemy,hand=enemy_hand,hero_power_card_id='power',deck=('plain',)*6,mana=10,max_mana=10)),seed=71),self.r)

    def cast(self,g,name,target=None):
        p=g.state.active_player
        eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(p,eid,target))

    def use(self,g):
        p=g.state.active_player
        return g.apply(UseHeroPower(p,g.state.players[p].hero_power_id))

    def unit(self,g,pos=0,p=1): return g.state.entities[g.state.players[p].board[pos]]
    def permits(self,g,eid): return [a for a in g.state.entities[eid].abilities if a.kind=='printed_attack_permit']
    def policies(self,g,eid): return current_policies(g.state,g.state.entities[eid],self.r)
    def attacks(self,g,eid): return [a for a in g.legal_actions() if isinstance(a,Attack) and a.attacker_id==eid]
    def choose(self,g):
        c=g.state.pending_choice
        return g.apply(SelectChoice(c.player_id,c.id,(c.options[0].id,)))
    def check(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,self.r).snapshot(),g.snapshot())
        self.assertEqual(g.clone().snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())
    def private(self,g):
        value=json.dumps(g.observe(1))+json.dumps(g.observe(2))+json.dumps(g.for_player(1).legal_actions())
        for key in ('printed_attack_permit','permitted_ability_id','attack_policy_declaration','policy_index',
                    'expires_owner_turn_id','presence_id'):
            self.assertNotIn('"'+key+'"',value)

    def test_two_identical_printed_slots_are_not_one_blanket_ban(self):
        g=self.game(board=('double',),hand=('permit','permit_second')); eid=self.unit(g).id
        self.cast(g,'permit',eid); self.assertEqual(self.policies(g,eid),(BAN,)); self.assertFalse(self.attacks(g,eid))
        self.cast(g,'permit_second',eid); self.assertEqual(self.policies(g,eid),()); self.assertTrue(self.attacks(g,eid))
        self.assertEqual(len([a for a in self.unit(g).abilities if a.kind=='attack_policy']),2); self.check(g)

    def test_hero_target_restriction_remains_after_self_permission(self):
        g=self.game(board=('noheroes',),hand=('permit',)); eid=self.unit(g).id
        self.cast(g,'permit',eid)
        self.assertEqual(self.policies(g,eid),(AttackPolicySpec('cannot_attack_heroes'),))
        self.assertTrue(self.attacks(g,eid)); self.assertTrue(all(a.defender_id!=g.state.players[2].hero_id for a in self.attacks(g,eid)))
        with self.assertRaises(IllegalAction): g.apply(Attack(1,eid,g.state.players[2].hero_id))

    def test_foreign_granted_and_physical_source_bans_are_not_suppressed(self):
        def bound(c):
            source=c.state.players[1].board[1]
            return [GrantAttackPolicy(c.target_id,BAN,source_id=source,
                source_binding=AttackSourceBinding.capture(c.state,source,AttackSourcePolicy('live','preserve','ignore')))]
        self.spell('bound',bound,True)
        g=self.game(board=('watch','plain'),hand=('permit','foreign','bound','kill')); eid=self.unit(g).id
        self.cast(g,'permit',eid); self.cast(g,'foreign',eid); self.cast(g,'bound',eid)
        self.assertEqual(self.policies(g,eid),(BAN,BAN)); self.cast(g,'kill',self.unit(g,1).id)
        self.assertEqual(self.policies(g,eid),(BAN,)); self.assertFalse(self.attacks(g,eid)); self.check(g)

    def test_current_copy_maps_local_rows_twice_and_keeps_original_clock(self):
        g=self.game(hand=('copy','copy')); source=self.unit(g).id; self.use(g)
        self.cast(g,'copy',source); first=self.unit(g,1).id; self.cast(g,'copy',first); second=self.unit(g,2).id
        target_ids=[]
        for eid in (source,first,second):
            permit=self.permits(g,eid)[0]; row=next(a for a in g.state.entities[eid].abilities if a.kind=='attack_policy')
            self.assertEqual(permit.printed_attack_permit.permitted_ability_id,row.id)
            self.assertEqual(permit.printed_attack_permit.expires_owner_turn_id,1)
            self.assertEqual(row.source_id,source); self.assertTrue(self.attacks(g,eid)); target_ids.append(row.id)
        self.assertEqual(len(set(target_ids)),3); self.private(g); self.check(g)

    def test_base_copy_reinstalls_ban_without_temporary_permission(self):
        g=self.game(hand=('basecopy',)); source=self.unit(g).id; self.use(g); self.cast(g,'basecopy',source)
        copy=self.unit(g,1).id; self.assertEqual(self.permits(g,copy),[]); self.assertFalse(self.attacks(g,copy)); self.check(g)

    def test_captured_request_same_name_transform_is_stale_by_original_row(self):
        def driver(c):
            req=self.request(c,c.target_id)
            return [Transform(c.target_id,'watch'),GrantPrintedAttackPermit(req)]
        self.spell('driver',driver,True)
        g=self.game(hand=('driver',)); eid=self.unit(g).id; presence=self.unit(g).board_presence_id
        self.cast(g,'driver',eid); self.assertEqual(self.unit(g).board_presence_id,presence)
        self.assertEqual(self.permits(g,eid),[]); self.assertFalse(self.attacks(g,eid)); self.check(g)

    def test_captured_request_same_entity_bounce_reentry_is_stale_by_residence(self):
        self.r.register_behavior('reenter',lambda c:[SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),1)])
        def driver(c):
            req=self.request(c,c.target_id)
            return [ReturnToHand(c.target_id),RequestChoice(1,(ChoiceOption('reenter','Return',(
                InvokeBehavior('reenter',source_id=c.source_id,player_id=1,target_id=c.target_id),GrantPrintedAttackPermit(req))),),source_id=c.source_id)]
        self.spell('driver',driver,True)
        g=self.game(hand=('driver',)); eid=self.unit(g).id; old=self.unit(g).board_presence_id
        self.cast(g,'driver',eid); self.check(g); self.choose(g)
        self.assertNotEqual(self.unit(g).board_presence_id,old); self.assertEqual(self.permits(g,eid),[]); self.check(g)

    def test_real_choice_saved_request_restore_clone_replay_and_private_projection(self):
        def wait(c):
            return [RequestChoice(1,(ChoiceOption('allow','Allow',tuple(self.permit(c,c.target_id))),),source_id=c.source_id)]
        self.spell('wait',wait,True)
        g=self.game(hand=('wait',)); eid=self.unit(g).id; self.cast(g,'wait',eid); self.private(g); self.check(g)
        restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r); cloned=g.clone()
        self.choose(g); self.choose(restored); self.choose(cloned)
        self.assertEqual(g.snapshot(),restored.snapshot()); self.assertEqual(g.snapshot(),cloned.snapshot())
        self.assertTrue(self.attacks(g,eid)); self.private(g); self.check(g)

    def test_failure_rolls_back_permission_copy_ids_randomness_and_history(self):
        def bad(c):
            return self.permit(c,c.target_id)+[CopyMinion(c.target_id,1),
                RandomDamage((c.state.players[2].hero_id,c.state.players[2].board[0]),1),EquipWeapon(1,'plain')]
        self.spell('bad',bad,True)
        g=self.game(hand=('bad',)); before=g.snapshot()
        with self.assertRaises(ResolutionError) as failed: self.cast(g,'bad',self.unit(g).id)
        self.assertIn('weapon',str(failed.exception).lower())
        self.assertEqual(g.snapshot(),before); self.assertEqual(self.permits(g,self.unit(g).id),[])

    def test_control_transfer_never_rearms_original_owner_interval(self):
        g=self.game(hand=('transfer',)); eid=self.unit(g).id; self.use(g); original=self.permits(g,eid)[0]
        self.cast(g,'transfer',eid); self.assertEqual(self.permits(g,eid)[0],original)
        self.assertEqual(self.policies(g,eid),()); g.apply(EndTurn(1))
        self.assertEqual(self.permits(g,eid),[]); self.assertEqual(self.policies(g,eid),(BAN,))
        self.assertFalse(self.attacks(g,eid)); self.check(g)

    def test_completed_manual_inspire_can_repeat_without_consuming_printed_ban(self):
        g=self.game(hand=('refresh',)); eid=self.unit(g).id; original=next(a for a in self.unit(g).abilities if a.kind=='attack_policy')
        self.use(g); g.apply(Attack(1,eid,g.state.players[2].hero_id)); self.cast(g,'refresh'); self.use(g)
        self.assertEqual(len(self.permits(g,eid)),2); self.assertIn(original,self.unit(g).abilities)
        self.assertEqual(self.unit(g).attacks_this_turn,1); self.assertFalse(self.attacks(g,eid))
        self.assertEqual(self.policies(g,eid),()); g.apply(EndTurn(1))
        self.assertEqual(self.permits(g,eid),[]); self.assertIn(original,g.state.entities[eid].abilities); self.check(g)

    def test_completed_power_before_entry_does_not_retrospectively_grant_permission(self):
        g=self.game(board=(),hand=('summon',)); self.use(g); self.cast(g,'summon'); eid=self.unit(g).id
        self.assertEqual(self.permits(g,eid),[]); self.assertFalse(self.attacks(g,eid)); self.check(g)

    def test_listener_original_window_capture_does_not_borrow_transformed_row(self):
        def mutate(c):
            if is_inspire(c.state,c.event,c.player_id): return [Transform(c.state.players[1].board[1],'watch')]
            return []
        self.r.register_behavior('mutate',mutate)
        self.unitdef('mutator',(),triggers=(TriggerSpec('hero_power_used','mutate'),))
        g=self.game(board=('mutator','watch')); eid=self.unit(g,1).id; self.use(g)
        self.assertEqual(self.permits(g,eid),[]); self.assertFalse(self.attacks(g,eid)); self.check(g)

    def test_end_reaction_uses_old_interval_and_generic_expiry_removes_new_permit(self):
        self.r.register_behavior('endpermit',lambda c:self.permit(c,c.source_id))
        self.unitdef('endwatch',(BAN,),triggers=(TriggerSpec('turn_ended','endpermit'),))
        g=self.game(board=('endwatch',)); eid=self.unit(g).id; g.apply(EndTurn(1))
        grants=[e for e in g.events if e.kind=='ability_granted' and e.target_id==eid]
        self.assertEqual(len(grants),1); self.assertEqual(self.permits(g,eid),[])
        self.assertEqual(self.policies(g,eid),(BAN,)); self.check(g)

    def test_freeze_queries_current_permission_but_does_not_retroactively_shorten_clock(self):
        g=self.game(hand=('freeze','freeze')); eid=self.unit(g).id
        self.cast(g,'freeze',eid); self.assertEqual(self.unit(g).frozen_until_owner_turn,2)
        self.use(g); self.assertEqual(self.unit(g).frozen_until_owner_turn,2); self.assertFalse(self.attacks(g,eid))
        h=self.game(hand=('freeze',)); self.use(h); self.cast(h,'freeze',self.unit(h).id)
        self.assertEqual(self.unit(h).frozen_until_owner_turn,1); h.apply(EndTurn(1))
        self.assertIsNone(h.state.entities[self.unit(h).id].frozen_until_owner_turn); self.check(h)

    def test_permission_never_grants_titan_opportunities_or_resets_used_count(self):
        g=self.game(board=('titan',),hand=('permit',)); eid=self.unit(g).id; self.cast(g,'permit',eid)
        self.assertFalse(self.attacks(g,eid))
        choices=[a for a in g.legal_actions() if isinstance(a,UseMinionAbility)]
        self.assertEqual(len(choices),3); g.apply(choices[0]); self.assertEqual(self.unit(g).attacks_this_turn,1)
        self.assertFalse([a for a in g.legal_actions() if isinstance(a,UseMinionAbility)]); self.check(g)

    def test_silence_and_transform_remove_permission_without_recreating_old_declaration(self):
        g=self.game(hand=('silence','transform')); eid=self.unit(g).id; self.use(g); self.cast(g,'silence',eid)
        self.assertEqual(self.permits(g,eid),[]); self.assertEqual(self.policies(g,eid),())
        self.cast(g,'transform',eid); self.assertFalse(self.attacks(g,eid)); self.assertEqual(self.permits(g,eid),[]); self.check(g)

    def test_accepted_attack_finishes_after_same_name_transform_loses_permission(self):
        def react(c):
            if c.event.source_id!=c.source_id: return [Transform(c.event.source_id,'watch')]
            return []
        self.r.register_behavior('react',react)
        self.unitdef('reactor',(),triggers=(TriggerSpec('attack_declared','react'),))
        g=self.game(enemy=('reactor',)); eid=self.unit(g).id; self.use(g)
        target=g.state.players[2].hero_id; g.apply(Attack(1,eid,target))
        self.assertEqual(g.state.entities[target].damage,1); self.assertEqual(self.permits(g,eid),[])
        self.assertFalse(self.attacks(g,eid)); self.check(g)

    def test_magnetic_foreign_clause_cannot_be_cleared_by_host_native_permit(self):
        meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('mech',))
        self.unitdef('host',(BAN,),metadata=meta)
        self.unitdef('magnet',(BAN,),metadata=meta,keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',))
        g=self.game(board=('host',),hand=('permit','magnet')); eid=self.unit(g).id; self.cast(g,'permit',eid)
        source=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id=='magnet')
        g.apply(PlayCard(1,source,position=0)); self.assertEqual(self.policies(g,eid),(BAN,)); self.assertFalse(self.attacks(g,eid))
        self.assertEqual(capture_printed_attack_permit(g.state,self.r,eid,Declaration('magnet',0)),None); self.check(g)

    def test_magnetic_transfer_filter_excludes_local_permit_without_blanketing_restriction(self):
        g=self.game(); eid=self.unit(g).id; self.use(g); source=g.state.entities[eid]
        transferred=transferable_abilities(source)
        self.assertFalse(any(a.kind=='printed_attack_permit' for a in transferred))
        self.assertTrue(any(a.kind=='attack_policy' for a in transferred))

    def test_dormancy_does_not_reset_local_permission_or_its_original_expiry(self):
        g=self.game(hand=('dormant','awaken')); eid=self.unit(g).id; self.use(g); original=self.permits(g,eid)[0]
        self.cast(g,'dormant',eid); self.assertFalse(self.attacks(g,eid)); self.assertEqual(self.permits(g,eid)[0],original)
        self.cast(g,'awaken'); self.assertEqual(self.permits(g,eid)[0],original)
        g.apply(EndTurn(1)); self.assertEqual(self.permits(g,eid),[]); self.check(g)

    def test_codec_and_invariant_negative_types_slots_clock_and_local_identity(self):
        g=self.game(); eid=self.unit(g).id; self.use(g)
        codec=FrameCodec(default_mechanics(),self.r,origin_state=g.state)
        with self.assertRaises(ValueError): Declaration('watch',True)
        with self.assertRaises(ValueError): codec.encode(Declaration('watch',9))
        with self.assertRaises(ValueError): capture_printed_attack_permit(g.state,self.r,eid,Declaration('noheroes',1))
        original=g.snapshot()
        for mutation in ('slot','clock','row','type'):
            snap=deepcopy(original); ent=snap['state']['entities'][str(eid)]
            permit=next(a for a in ent['abilities'] if a['kind']=='printed_attack_permit')
            if mutation=='slot': permit['printed_attack_permit']['declaration']['policy_index']=9
            if mutation=='clock': permit['printed_attack_permit']['expires_owner_turn_id']=99
            if mutation=='row': permit['printed_attack_permit']['permitted_ability_id']=next(a['id'] for a in ent['abilities'] if a['kind']=='trigger')
            if mutation=='type': permit['printed_attack_permit']['permitted_ability_id']=True
            snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError): Game.from_snapshot(snap,self.r)

    def test_orphan_local_pointer_is_not_rematched_during_current_copy(self):
        g=self.game(board=('double','plain'),hand=('permit',)); eid=self.unit(g).id; self.cast(g,'permit',eid)
        state=g.state; source=state.entities[eid]; target=state.entities[self.unit(g,1).id]
        permitted=self.permits(g,eid)[0].printed_attack_permit.permitted_ability_id
        source.abilities=[a for a in source.abilities if a.id!=permitted]
        target.card_id=source.card_id; target.base_attack=source.base_attack; target.base_health=source.base_health
        copy_attachments(state,source,target)
        self.assertEqual(permitted_rows(state,target,self.r),frozenset())
        self.assertEqual(current_policies(state,target,self.r),(BAN,))

    def test_death_record_validates_saved_face_and_copy_resets_temporary_permission(self):
        from hs_sim.engine.summon_sources import ResurrectMinion
        self.spell('resurrect',lambda c:[ResurrectMinion(1,1)])
        g=self.game(hand=('kill','resurrect')); eid=self.unit(g).id; self.use(g); self.cast(g,'kill',eid)
        self.check(g); self.cast(g,'resurrect'); revived=self.unit(g).id
        self.assertEqual(self.permits(g,revived),[]); self.assertFalse(self.attacks(g,revived)); self.check(g)

    def test_real_choice_failure_keeps_waiting_request_and_successful_alternative(self):
        def wait(c):
            grant=tuple(self.permit(c,c.target_id))
            return [RequestChoice(1,(ChoiceOption('bad','Bad',grant+(CopyMinion(c.target_id,1),
                RandomDamage((c.state.players[2].hero_id,c.state.players[2].board[0]),1),
                EquipWeapon(1,'plain'))),ChoiceOption('good','Good',grant)),source_id=c.source_id)]
        self.spell('wait',wait,True)
        g=self.game(hand=('wait',)); eid=self.unit(g).id; self.cast(g,'wait',eid); self.check(g)
        original=g.snapshot(); restored=Game.from_snapshot(json.loads(json.dumps(original)),self.r)
        for candidate in (g,restored):
            choice=candidate.state.pending_choice
            with self.assertRaises(ResolutionError) as failed: candidate.apply(SelectChoice(1,choice.id,('bad',)))
            self.assertIn('weapon',str(failed.exception).lower())
            self.assertEqual(candidate.snapshot(),original)
            candidate.apply(SelectChoice(1,choice.id,('good',)))
        self.assertEqual(g.snapshot(),restored.snapshot()); self.assertTrue(self.attacks(g,eid)); self.check(g)
