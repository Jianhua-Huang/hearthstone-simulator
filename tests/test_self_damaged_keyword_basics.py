"""The necessary real Worgen, continuous Windfury and original attack allowance."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, GrantKeywordAura,
    IllegalAction, Keyword, KeywordAuraSpec, PlayCard, PlayerSetup, ResolutionError, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, Zone, attack_limit, has_action_remaining)
from hs_sim.engine.dormancy import MakeDormant, AwakenMinion
from hs_sim.engine.effects import (Damage, DamageBatch, GainArmor, GrantKeyword, Heal, Summon, Transform)
from hs_sim.engine.model import AbilityInstance
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from test_self_damaged_attack_basics import registry as attack_registry, REL as ATTACK_REL
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

WORGEN='EX1_412'
PATH=Path(__file__).resolve().parents[1]/'data/support/self-damaged-keyword-basics.json'
PIN='cd302e20447dfcf40570b6880980e650c77664351a4bba332f8ae4b2954694a8'
REL=KeywordAuraSpec(Keyword.WINDFURY, 'self', condition='self_damaged')

def evidence():
    support=json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support)!=PIN: raise ValueError('Self-damaged keyword complete evidence changed')
    for row in support['records']:
        if canonical_digest(row['data'])!=row['data_sha256']: raise ValueError('Self-damaged keyword raw changed')
    return support['records'][0]['data']

def registry():
    r=attack_registry();raw=evidence()
    r.register_card(CardDefinition(WORGEN,raw['name'],CardType.MINION,cost=raw['cost'],
        attack=raw['attack'],health=raw['health'],stat_relations=(replace(ATTACK_REL,amount=1),),
        keyword_auras=(REL,),metadata=metadata()))
    def quote(c):
        e=c.state.entities[c.target_id]
        return (GainArmor(c.player_id,e.attack+(100 if Keyword.WINDFURY in e.keywords else 0)),)
    r.register_behavior('wf.quote',quote)
    def observe(c):
        e=c.state.entities[c.event.target_id]
        return (GainArmor(c.player_id,10 if Keyword.WINDFURY in e.keywords else 1),)
    r.register_behavior('wf.observe',observe)
    r.register_card(CardDefinition('wf.observe','Observe saved health context',CardType.MINION,health=5,
        triggers=(TriggerSpec('damage_dealt','wf.observe'),TriggerSpec('healed','wf.observe')),metadata=metadata()))
    r.register_card(CardDefinition('wf.external','Existing external Windfury',CardType.MINION,health=5,
        keyword_auras=(KeywordAuraSpec(Keyword.WINDFURY,'friendly_minions'),),metadata=metadata()))
    scripts={
        'wf.hurt':lambda c:(Damage(c.target_id,1,c.source_id,on_result='wf.quote'),),
        'wf.full':lambda c:(Heal(c.target_id,30,c.source_id,on_result='wf.quote'),),
        'wf.batch':lambda c:(DamageBatch((Damage(c.target_id,1,c.source_id,on_result='wf.quote'),
            Damage(c.target_id,1,c.source_id,on_result='wf.quote'))),),
        'wf.permanent':lambda c:(GrantKeyword(c.target_id,Keyword.WINDFURY,c.source_id),),
        'wf.summon':lambda c:(Summon(c.player_id,WORGEN),),
        'wf.into':lambda c:(Transform(c.target_id,WORGEN),),
    }
    for name,body in scripts.items():
        r.register_behavior(name,body)
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,requires_target=name!='wf.summon',metadata=metadata()))
    for name,cls in (('wf.sleep',MakeDormant),('wf.awake',AwakenMinion)):
        if cls is MakeDormant:
            def sleep(c):return (MakeDormant(c.state.players[c.player_id].board[0],None,c.source_id),)
            body=sleep
        else:
            def awake(c):return (AwakenMinion(c.state.players[c.player_id].board[0],c.source_id),)
            body=awake
        r.register_behavior(name,body)
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,metadata=metadata()))
    return r

class SelfDamagedKeywordBasicsTests(unittest.TestCase):
    def game(self,hand=(),board=(WORGEN,),enemy=('plain',),enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,mana=10,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,board=enemy,mana=10,max_mana=10),
        ),seed=33),registry())
    def actor(self,g):return g.state.players[1].board[0]
    def cast(self,g,name,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        card=g.registry.card(name)
        return g.apply(PlayCard(1,eid,(self.actor(g) if target is None else target) if card.requires_target else None))
    def choose(self,g,name):
        p=g.state.pending_choice;return g.apply(SelectChoice(p.player_id,p.id,(name,)))
    def rows(self,g,eid):return tuple(a for a in g.state.entities[eid].abilities if a.kind=='keyword_aura')
    def wind(self,g,expected=True,eid=None):
        e=g.state.entities[self.actor(g) if eid is None else eid]
        self.assertEqual(Keyword.WINDFURY in e.keywords,expected)
        self.assertEqual(attack_limit(g.state,e,g.registry),2 if expected else 1)
    def remaining(self,g,eid=None):
        return has_action_remaining(g.state,g.state.entities[self.actor(g) if eid is None else eid],g.registry)
    def attack(self,g,target=None):
        return g.apply(Attack(1,self.actor(g),g.state.players[2].hero_id if target is None else target))
    def portable(self,g):
        snap=json.loads(json.dumps(g.snapshot()));restored=Game.from_snapshot(snap,registry())
        self.assertEqual(restored.snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),snap);return restored
    def reject(self,snap):
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(snap,registry())

    def test_full_raw_single_adapter_and_no_unconditional_windfury(self):
        raw=evidence();self.assertEqual((raw['id'],raw['cost'],raw['attack'],raw['health']),(WORGEN,3,3,3))
        self.assertEqual(raw['text_en'],'Has +1 Attack and <b>Windfury</b> while damaged.')
        card=registry().card(WORGEN)
        self.assertEqual(card.keyword_auras,(REL,));self.assertNotIn(Keyword.WINDFURY,card.keywords)
        self.assertEqual(card.stat_relations,(replace(ATTACK_REL,amount=1),))
        self.assertEqual([r['id'] for r in json.loads(PATH.read_text(encoding='utf-8'))['records']],[WORGEN])

    def test_closed_exact_typed_real_condition_and_self_scope(self):
        self.assertEqual(KeywordAuraSpec(Keyword.WINDFURY).condition,'always')
        for kwargs in ({'condition':True},{'condition':'self_healthy'},{'condition':'always'},
                {'target':'friendly_minions'},{'target':'friendly_hand_minions'},{'include_self':True},
                {'adjacent_only':True},{'keyword':Keyword.IMMUNE},{'keyword':Keyword.DIVINE_SHIELD}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):replace(REL,**kwargs)
        with self.assertRaises(FrozenInstanceError):REL.condition='always'

    def test_printed_ordinary_definition_and_duplicate_native_instance_guards(self):
        from hs_sim.engine.keyword_auras import validate_definition,validate_carrier
        card=registry().card(WORGEN)
        for bad in (replace(card,keyword_auras=(REL,REL)),replace(card,kind=CardType.HERO),
                replace(card,keywords=(Keyword.MAGNETIC,),magnetic_tribes=('MECH',))):
            with self.subTest(card=bad),self.assertRaises(ValueError):validate_definition(bad)
        g=self.game();eid=self.actor(g);a=self.rows(g,eid)[0]
        with self.assertRaises(ValueError):validate_carrier(g.registry,WORGEN,CardType.MINION,(a,replace(a,id=a.id+100)))

    def test_optional_grants_and_non_native_lifecycle_are_explicitly_rejected(self):
        with self.assertRaises(ValueError):GrantKeywordAura(1,REL)
        with self.assertRaises(ValueError):AbilityInstance(1,'keyword_aura',keyword_aura=REL)
        g=self.game();a=self.rows(g,self.actor(g))[0]
        for kwargs in ({'origin':'granted'},{'source_id':None},{'consumed':True},
                {'expires_turn':g.state.turn+1},{'remove_on_silence':False}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):replace(a,**kwargs)
        self.assertIsNotNone(GrantKeywordAura(1,KeywordAuraSpec(Keyword.WINDFURY)))

    def test_damage_switches_current_keyword_without_permanent_grant_or_aura_cache(self):
        g=self.game(('hurt',));eid=self.actor(g);before=self.rows(g,eid);self.wind(g,False)
        self.cast(g,'hurt');self.wind(g);e=g.state.entities[eid]
        self.assertEqual((e.attack,e.damage,e.attacks_this_turn),(4,1,0))
        self.assertEqual(self.rows(g,eid),before);self.assertFalse(e.aura_keywords)
        self.assertFalse(any(a.kind=='keyword' and a.keyword==Keyword.WINDFURY for a in e.abilities));self.portable(g)

    def test_repeated_damage_does_not_stack_or_reset_spent_attacks(self):
        g=self.game(('hurt','hurt'));self.cast(g,'hurt');self.attack(g);self.cast(g,'hurt');self.wind(g)
        self.assertEqual((g.state.entities[self.actor(g)].damage,g.state.entities[self.actor(g)].attacks_this_turn),(2,1))
        self.assertEqual(len(self.rows(g,self.actor(g))),1);self.assertTrue(self.remaining(g));self.portable(g)

    def test_partial_heal_keeps_windfury(self):
        g=self.game(('hurt2','heal'));self.cast(g,'hurt2');self.cast(g,'heal');self.wind(g)
        self.assertEqual(g.state.entities[self.actor(g)].damage,1);self.portable(g)

    def test_full_heal_revokes_windfury_and_next_injury_reactivates(self):
        g=self.game(('hurt','full','hurt'));self.cast(g,'hurt');self.wind(g)
        self.cast(g,'full');self.wind(g,False);self.assertEqual(g.state.entities[self.actor(g)].attack,3)
        self.cast(g,'hurt');self.wind(g);self.portable(g)

    def test_zero_and_prevented_damage_and_overheal_keep_healthy_limit(self):
        g=self.game(('hurt0','full','shield','hurt'));self.cast(g,'hurt0');self.cast(g,'full')
        self.cast(g,'shield');self.cast(g,'hurt');self.wind(g,False)
        self.assertEqual(g.state.entities[self.actor(g)].damage,0);self.portable(g)

    def test_first_attack_into_damage_activates_second_opportunity(self):
        g=self.game();enemy=g.state.players[2].board[0];self.attack(g,enemy);self.wind(g)
        self.assertEqual(g.state.entities[enemy].damage,3)
        self.assertEqual(g.state.entities[self.actor(g)].attacks_this_turn,1);self.assertTrue(self.remaining(g))
        self.attack(g);self.assertFalse(self.remaining(g));self.portable(g)

    def test_first_healthy_hero_attack_then_injury_opens_only_one_extra_attack(self):
        g=self.game(('hurt',));self.attack(g);self.assertFalse(self.remaining(g));self.wind(g,False)
        self.cast(g,'hurt');self.wind(g);self.assertTrue(self.remaining(g));self.attack(g)
        self.assertEqual(g.state.entities[self.actor(g)].attacks_this_turn,2)
        with self.assertRaises(IllegalAction):self.attack(g)
        self.portable(g)

    def test_full_heal_after_one_attack_revokes_second_without_refunding_first(self):
        g=self.game(('hurt','full','hurt'));self.cast(g,'hurt');self.attack(g);self.cast(g,'full');self.wind(g,False)
        self.assertEqual(g.state.entities[self.actor(g)].attacks_this_turn,1);self.assertFalse(self.remaining(g))
        before=g.snapshot()
        with self.assertRaises(IllegalAction):self.attack(g)
        self.assertEqual(g.snapshot(),before);self.cast(g,'hurt');self.wind(g)
        self.assertTrue(self.remaining(g));self.portable(g)

    def test_heal_reinjure_after_two_attacks_never_opens_a_third(self):
        g=self.game(('hurt','full','hurt'));self.cast(g,'hurt');self.attack(g);self.attack(g)
        self.cast(g,'full');self.cast(g,'hurt');self.wind(g);self.assertFalse(self.remaining(g))
        self.assertEqual(g.state.entities[self.actor(g)].attacks_this_turn,2)
        with self.assertRaises(IllegalAction):self.attack(g)
        self.portable(g)

    def test_actual_new_owner_turn_resets_spent_attacks_without_changing_condition(self):
        g=self.game(('hurt',));self.cast(g,'hurt');self.attack(g);self.attack(g)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.wind(g)
        self.assertEqual(g.state.entities[self.actor(g)].attacks_this_turn,0)
        self.assertTrue(self.remaining(g));self.portable(g)

    def test_keyword_is_ready_before_damage_result_callback(self):
        g=self.game(('wf.hurt',));self.cast(g,'wf.hurt');self.wind(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,104);self.portable(g)

    def test_keyword_is_revoked_before_healing_result_callback(self):
        g=self.game(('hurt','wf.full'));self.cast(g,'hurt');self.cast(g,'wf.full');self.wind(g,False)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,3);self.portable(g)

    def test_saved_event_context_has_current_injury_and_healing_keyword(self):
        g=self.game(('hurt','full'),board=(WORGEN,'wf.observe'))
        self.cast(g,'hurt');self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,10)
        self.cast(g,'full');self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,11)
        self.wind(g,False);self.portable(g)

    def test_primary_batch_callbacks_see_final_continuous_keyword(self):
        g=self.game(('wf.batch',));self.cast(g,'wf.batch');self.wind(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,208)
        self.assertEqual(g.state.entities[self.actor(g)].damage,2);self.portable(g)

    def test_real_declared_wait_restores_keyword_and_original_combat_allowance(self):
        g=self.game(board=(WORGEN,'watcher'));enemy=g.state.players[2].board[0]
        self.attack(g,enemy);self.assertIsNotNone(g.state.pending_choice);self.wind(g,False)
        restored=self.portable(g);clone=g.clone()
        for branch in (g,restored,clone):
            self.choose(branch,'hurt');self.wind(branch)
            self.assertEqual((branch.state.entities[enemy].damage,branch.state.entities[self.actor(branch)].damage),(4,2))
            self.assertEqual(branch.state.entities[self.actor(branch)].attacks_this_turn,1)
            self.assertTrue(self.remaining(branch));self.portable(branch)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.snapshot(),clone.snapshot())

    def test_manual_play_installs_native_condition_without_early_extra_attack(self):
        g=self.game((WORGEN,'hurt'),board=());eid=g.state.players[1].hand[0]
        g.apply(PlayCard(1,eid));self.wind(g,False);self.cast(g,'hurt');self.wind(g)
        with self.assertRaises(IllegalAction):self.attack(g)
        self.assertEqual(len(self.rows(g,eid)),1);self.portable(g)

    def test_summon_installs_native_condition_without_early_extra_attack(self):
        g=self.game(('wf.summon','hurt'),board=());self.cast(g,'wf.summon')
        eid=self.actor(g);self.wind(g,False);self.cast(g,'hurt');self.wind(g)
        with self.assertRaises(IllegalAction):self.attack(g)
        self.assertEqual(len(self.rows(g,eid)),1);self.portable(g)

    def test_silence_removes_condition_and_preserves_spent_attack(self):
        g=self.game(('hurt','silence'));self.cast(g,'hurt');self.attack(g);eid=self.actor(g)
        self.cast(g,'silence');self.wind(g,False)
        self.assertEqual((g.state.entities[eid].damage,g.state.entities[eid].attacks_this_turn),(1,1))
        self.assertEqual(self.rows(g,eid),());self.assertFalse(self.remaining(g));self.portable(g)

    def test_current_copy_reads_own_damage_and_preserves_printed_provenance(self):
        g=self.game(('hurt','copy','full'));eid=self.actor(g);self.cast(g,'hurt');self.cast(g,'copy')
        copied=g.state.players[2].board[-1];self.wind(g,True,copied)
        self.assertNotEqual(self.rows(g,eid)[0].id,self.rows(g,copied)[0].id)
        self.assertEqual(self.rows(g,copied)[0].source_id,eid)
        self.cast(g,'full');self.wind(g,False);self.wind(g,True,copied);self.portable(g)

    def test_base_copy_starts_healthy_and_current_silenced_copy_stays_silenced(self):
        g=self.game(('hurt','copybase','silence','copy'));self.cast(g,'hurt');self.cast(g,'copybase')
        base=g.state.players[2].board[-1];self.wind(g,False,base)
        self.assertEqual(len(self.rows(g,base)),1);self.cast(g,'silence');self.cast(g,'copy')
        copied=g.state.players[2].board[-1];self.wind(g,False,copied)
        self.assertEqual(self.rows(g,copied),());self.portable(g)

    def test_bounce_resets_health_condition_and_old_spent_attack(self):
        g=self.game(('hurt','bounce'));self.cast(g,'hurt');self.attack(g);eid=self.actor(g)
        self.cast(g,'bounce',eid);self.wind(g,False,eid)
        self.assertEqual((g.state.entities[eid].zone,g.state.entities[eid].damage,
            g.state.entities[eid].attacks_this_turn),(Zone.HAND,0,0))
        g.apply(PlayCard(1,eid));self.wind(g,False);self.portable(g)

    def test_transform_away_removes_condition(self):
        g=self.game(('hurt','away'));self.cast(g,'hurt');self.cast(g,'away');self.wind(g,False)
        self.assertEqual(self.rows(g,self.actor(g)),());self.portable(g)

    def test_transform_into_reinstalls_healthy_native_condition(self):
        g=self.game(('wf.into','hurt'),board=('plain',));self.cast(g,'wf.into');self.wind(g,False)
        self.assertEqual(len(self.rows(g,self.actor(g))),1);self.cast(g,'hurt');self.wind(g);self.portable(g)

    def test_control_change_preserves_self_condition_and_native_attachment(self):
        g=self.game(('hurt','control'));eid=self.actor(g);before=self.rows(g,eid)
        self.cast(g,'hurt');self.cast(g,'control',eid);self.wind(g,True,eid)
        self.assertEqual(g.state.entities[eid].controller,2);self.assertEqual(self.rows(g,eid),before);self.portable(g)

    def test_dormancy_suppresses_own_condition_and_awake_recomputes_current_damage(self):
        g=self.game(('hurt','wf.sleep','wf.awake'));eid=self.actor(g);self.cast(g,'hurt');self.wind(g)
        self.cast(g,'wf.sleep');self.wind(g,False)
        self.assertEqual(g.state.entities[eid].damage,1);self.assertFalse(g.state.entities[eid].active)
        self.portable(g);self.cast(g,'wf.awake');self.wind(g);self.portable(g)

    def test_max_health_set_revokes_condition_before_boundary(self):
        g=self.game(('hurt','sethp'));self.cast(g,'hurt');self.cast(g,'sethp');self.wind(g,False)
        self.assertEqual(g.state.entities[self.actor(g)].damage,0);self.portable(g)

    def test_max_health_gain_preserves_condition(self):
        g=self.game(('hurt','hp'));self.cast(g,'hurt');self.cast(g,'hp');self.wind(g)
        self.assertEqual(g.state.entities[self.actor(g)].damage,1);self.portable(g)

    def test_health_aura_removal_clamp_can_revoke_condition_without_healing(self):
        g=self.game(('hurt','kill'),board=(WORGEN,'aura'));eid,aura=g.state.players[1].board
        self.cast(g,'hurt');self.wind(g);self.cast(g,'kill',aura);self.wind(g,False)
        self.assertEqual(g.state.entities[eid].damage,0);self.portable(g)

    def test_healing_does_not_remove_existing_permanent_same_keyword(self):
        g=self.game(('hurt','wf.permanent','full'));self.cast(g,'hurt');self.cast(g,'wf.permanent');self.cast(g,'full')
        self.wind(g);e=g.state.entities[self.actor(g)]
        self.assertEqual(e.damage,0);self.assertTrue(any(a.kind=='keyword' and a.keyword==Keyword.WINDFURY for a in e.abilities))
        self.portable(g)

    def test_healing_keeps_existing_external_same_keyword_until_its_source_leaves(self):
        g=self.game(('hurt','full','kill'),board=(WORGEN,'wf.external'));eid,aura=g.state.players[1].board
        self.cast(g,'hurt');self.cast(g,'full');self.wind(g)
        self.assertEqual(g.state.entities[eid].aura_keywords,{Keyword.WINDFURY})
        self.cast(g,'kill',aura);self.wind(g,False);self.portable(g)

    def test_lethal_health_freezes_own_keyword_without_new_permanent_attachment(self):
        g=self.game(('hurt','hurt2'));eid=self.actor(g);self.cast(g,'hurt');self.cast(g,'hurt2',eid)
        row=g.state.death_history[-1]
        self.assertEqual((row.entity_id,row.attack,row.damage),(eid,4,3));self.assertIn(Keyword.WINDFURY,row.keywords)
        self.assertEqual(len([a for a in row.abilities if a.kind=='keyword_aura']),1)
        self.assertFalse(any(a.kind=='keyword' and a.keyword==Keyword.WINDFURY for a in row.abilities));self.portable(g)

    def test_pending_choice_restore_clone_replay_uses_current_keyword(self):
        g=self.game(('wait',));self.cast(g,'wait');restored=self.portable(g);clone=g.clone()
        for branch in (g,restored,clone):self.choose(branch,'hurt');self.wind(branch);self.portable(branch)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.snapshot(),clone.snapshot())

    def test_immediate_failure_restores_keyword_damage_and_original_inputs(self):
        g=self.game(('fault',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.cast(g,'fault')
        self.assertEqual(g.snapshot(),before);self.wind(g,False);self.portable(g)

    def test_waiting_failure_restores_original_waiting_keyword(self):
        g=self.game(('wait',));self.cast(g,'wait');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.wind(g,False);self.choose(g,'hurt');self.wind(g);self.portable(g)

    def test_player_view_and_legal_attacks_update_without_revealing_private_condition(self):
        g=self.game(('hurt','full'),enemy_hand=(WORGEN,));self.cast(g,'hurt');self.attack(g)
        self.assertTrue(any(type(a)is Attack and a.attacker_id==self.actor(g) for a in g.legal_actions()))
        self.cast(g,'full');self.wind(g,False)
        self.assertFalse(any(type(a)is Attack and a.attacker_id==self.actor(g) for a in g.legal_actions()))
        before=g.snapshot()
        for _ in range(3):
            public=json.dumps(g.observe(1))+json.dumps(g.observe(2))+json.dumps(g.for_player(1).legal_actions())
            for word in ('keyword_aura','keyword_auras','self_damaged','resolution_frame','next_attachment_id'):
                self.assertNotIn('"'+word+'"',public)
            g.legal_actions();self.wind(g,False)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_rehashed_wire_rejects_malformed_missing_and_non_native_self_spec(self):
        g=self.game(('hurt',));self.cast(g,'hurt');snap=g.snapshot();eid=self.actor(g)
        for field,value in (('condition',True),('condition','unknown_predicate'),('condition','always'),
                ('keyword','immune'),('target','friendly_minions'),('include_self',True)):
            bad=deepcopy(snap);a=next(a for a in bad['state']['entities'][str(eid)]['abilities'] if a['kind']=='keyword_aura')
            a['keyword_aura'][field]=value
            with self.subTest(field=field,value=value):self.reject(bad)
        bad=deepcopy(snap);a=next(a for a in bad['state']['entities'][str(eid)]['abilities'] if a['kind']=='keyword_aura')
        del a['keyword_aura']['condition'];self.reject(bad)
        bad=deepcopy(snap);a=next(a for a in bad['state']['entities'][str(eid)]['abilities'] if a['kind']=='keyword_aura')
        a['origin']='granted';self.reject(bad);self.portable(g)

    def test_rehashed_wire_rejects_stale_or_forged_effective_keyword_cache(self):
        g=self.game(('hurt',));self.cast(g,'hurt');eid=self.actor(g);bad=g.snapshot()
        bad['state']['entities'][str(eid)]['keywords'].remove('windfury');self.reject(bad)
        healthy=self.game();eid=self.actor(healthy);bad=healthy.snapshot()
        bad['state']['entities'][str(eid)]['keywords'].append('windfury');self.reject(bad)
        self.portable(g);self.portable(healthy)

    def test_strict_versions_and_all_previous_schemas(self):
        g=self.game();snap=g.snapshot();self.assertEqual(snap['schema_version'],266)
        self.assertEqual(snap['mechanics_version']['version'],CORE_EFFECTS_VERSION)
        for value in (1,179,180,True,181.0,217):
            bad=deepcopy(snap);bad['schema_version']=value
            with self.subTest(value=value),self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
        self.portable(g)

if __name__=='__main__':unittest.main()
