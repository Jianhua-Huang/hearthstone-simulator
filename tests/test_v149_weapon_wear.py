"""Public synchronous wear combinations, synthetic requirements, no CN claim."""
import copy,json,unittest
from dataclasses import replace,dataclass
from hs_sim.engine import (Game,Registry,CardDefinition,CardType,CardClass,CardMetadata,Keyword,PlayerSetup,
    Scenario,Attack,PlayCard,EndTurn,SelectChoice,SnapshotError,TriggerSpec,Zone,
    WeaponWearSpec,WeaponWearProfile,WeaponWearPredicate,GrantWeaponWearPolicy,HeroAttackQuery,hero_attack_count)
from hs_sim.engine.effects import (Damage,GainArmor,EquipWeapon,ModifyWeapon,Destroy,Buff,GrantKeyword,
    ChoiceOption,RequestChoice,RandomDamage,ReplaceHero,Silence,Transform,ChangeControl,CopyMinion,ReturnToHand)
from hs_sim.engine.model import HealthRule,HealthFlow,HealthOp,HealthLayer,DamageKind,RewindSpec
from hs_sim.engine.interrupts import RedirectAttack
from hs_sim.engine.resolver import BeginAttack,default_mechanics,damage_batch,settle_health_batch
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,CopyCard
from hs_sim.engine.effects import Effect,CombatExchange


@dataclass(frozen=True)
class RepeatIntrinsicFinish(Effect):
    pass


def repeat_finish(r,effect):
    from hs_sim.engine.equipment import finish_exchange
    from hs_sim.engine.model import HeroAttackReference
    row=r.state.hero_attack_history[-1];c=row.combat
    finish_exchange(r,CombatExchange(c.identity.physical_hero_id,c.defender_id,c.weapon_id,
        hero_attack=HeroAttackReference(c.identity,c.delivery)))


def stale_installation_batch(r,effect):
    # Internal adversarial fixture inserts a replacement after combat acceptance.
    # There is no public before-wear callback or weapon bounce API in this pack.
    if effect.combat is None:return damage_batch(r,effect)
    from hs_sim.engine.equipment import validate_exchange,equip_weapon
    from hs_sim.engine.hero_attack_history import accept
    validate_exchange(r,effect.combat);accept(r,effect.combat)
    from hs_sim.engine.character_attacks import accept as accept_character_attack
    accept_character_attack(r,effect.combat)
    equip_weapon(r,EquipWeapon(1,'many'))
    return settle_health_batch(r,effect.hits,effect.combat)


class WeaponWearTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('isolated-public-weapon-wear-v149');self.cards=[];self.behaviors=[];self.games=[]
        self.card('hero',CardType.HERO,attack=2,health=100)
        self.card('newhero',CardType.HERO,attack=3,health=100)
        self.card('plain',CardType.MINION,attack=1,health=30)
        self.card('dragon',CardType.MINION,health=5,tribes=('dragon',))
        self.card('fragile_dragon',CardType.MINION,health=1,tribes=('dragon',))
        self.card('sleepdragon',CardType.MINION,health=5,tribes=('dragon',),dormant_turns=2)
        self.card('shield',CardType.MINION,health=30,keywords=(Keyword.DIVINE_SHIELD,))
        self.card('axe',CardType.WEAPON,attack=2,durability=1)
        self.card('many',CardType.WEAPON,attack=2,durability=5)
        self.card('gore',CardType.WEAPON,attack=2,durability=1,cost=3,weapon_wear_policies=(self.spec('replace_with_attack',preds=(WeaponWearPredicate('defender_kind','minion'),)),))
        self.card('storm',CardType.WEAPON,attack=2,durability=2,weapon_wear_policies=(self.spec('prevent_durability',preds=(WeaponWearPredicate('friendly_tribe_present','dragon'),)),))

    def spec(self,mode,scope='self_weapon',window='pre_wear_current',preds=(),priority=0,presence='active_living'):
        return WeaponWearSpec(mode,WeaponWearProfile(scope,window,presence),preds,priority)

    def card(self,name,kind,tribes=(),**kw):
        kw['metadata']=kw.get('metadata',CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=tribes))
        c=CardDefinition(name,name,kind,**kw);self.r.register_card(c);self.cards.append(c)

    def behavior(self,name,fn):self.r.register_behavior(name,fn);self.behaviors.append((name,fn))
    def spell(self,name,fn,**kw):self.behavior(name,fn);self.card(name,CardType.SPELL,on_play=name,**kw)
    def watcher(self,name,event,fn,**kw):self.behavior(name,fn);self.card(name,CardType.MINION,health=100,triggers=(TriggerSpec(event,name),),**kw)
    def fresh(self):
        r=Registry(self.r.version)
        for c in self.cards:r.register_card(c)
        for n,f in self.behaviors:r.register_behavior(n,f)
        return r
    def game(self,weapon='gore',board=(),enemy=('plain',),hand=(),mechanics=None):
        g=Game.from_scenario(Scenario((PlayerSetup('hero',weapon_card_id=weapon,board=board,hand=hand,mana=10,max_mana=10,deck=('plain',)*10),
            PlayerSetup('hero',board=enemy,mana=10,max_mana=10,deck=('plain',)*10)),seed=149),self.r,mechanics=mechanics)
        self.games.append(g);return g
    def hero(self,g,p=1):return g.state.players[p].hero_id
    def enemy(self,g):return g.state.players[2].board[0]
    def attack(self,g,target=None):return g.apply(Attack(1,self.hero(g),target or self.enemy(g)))
    def cast(self,g,name,position=None):
        i=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name);g.apply(PlayCard(1,i,position=position));return i
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def row(self,g):return g.state.hero_attack_history[-1]
    def check(self,g,mechanics=None):
        s=g.snapshot();self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),self.fresh(),mechanics).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),self.fresh(),mechanics).snapshot(),s)
        text=json.dumps([g.observe(1),g.observe(2),g.player_events(1),g.player_events(2)])
        for forbidden in ('wear_receipt','wear_acceptance','hero_allocation','next_attachment_id','weapon_wear_committed'):
            self.assertNotIn(forbidden,text)
    def reject(self,g,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as e:Game.from_snapshot(s,self.fresh())
        self.assertNotIn('digest mismatch',str(e.exception))

    def test_minion_replacement_preserves_prepared_damage_and_completed_count(self):
        g=self.game();wid=g.state.players[1].weapon_id;self.attack(g)
        self.assertEqual((g.state.entities[wid].attack,g.state.entities[wid].durability),(1,1))
        self.assertEqual(g.state.entities[self.enemy(g)].health,26)
        self.assertEqual(g.state.entities[self.hero(g)].attack,3)
        self.assertEqual(hero_attack_count(g.state,1,HeroAttackQuery()),1)
        self.assertEqual((self.row(g).wear_receipt.plan.axis,self.row(g).wear_receipt.attack_before,self.row(g).wear_receipt.attack_after),('attack',2,1));self.check(g)

    def test_hero_target_wears_last_durability_and_shield_still_replaces(self):
        g=self.game();wid=g.state.players[1].weapon_id;self.attack(g,self.hero(g,2))
        self.assertIsNone(g.state.players[1].weapon_id);self.assertEqual(g.state.entities[wid].durability,0)
        self.assertFalse(self.row(g).wear_receipt.plan.decisions[0].eligible);self.check(g)
        self.setUp();g=self.game(enemy=('shield',));self.attack(g)
        self.assertEqual(g.state.entities[self.enemy(g)].health,30);self.assertEqual(self.row(g).wear_receipt.plan.axis,'attack');self.check(g)

    def test_final_attack_defender_kind_is_independent_of_health_redirect(self):
        rule=HealthRule(HealthFlow.DAMAGE,HealthOp.REDIRECT,layer=HealthLayer.TARGET,target_relation='self',damage_kinds=(DamageKind.COMBAT,),redirect_to='friendly_hero')
        self.card('redirector',CardType.MINION,health=30,health_rules=(rule,))
        self.watcher('redirect','attack_declared',lambda c:[RedirectAttack(dict(c.event.data)['window_id'],c.state.players[2].board[0])])
        g=self.game(board=('redirect',),enemy=('redirector',));self.attack(g,self.hero(g,2))
        self.assertEqual(g.state.entities[self.enemy(g)].health,30);self.assertEqual(g.state.entities[self.hero(g,2)].health,96)
        self.assertEqual(self.row(g).wear_receipt.current.defender_kind,CardType.MINION);self.assertEqual(self.row(g).wear_receipt.plan.axis,'attack');self.check(g)

    def test_current_dragon_metadata_sleep_and_opponent_scope(self):
        for board,enemy,loss in [(('dragon',),('plain',),0),(('sleepdragon',),('plain',),1),((),('dragon',),1)]:
            with self.subTest(board=board):
                g=self.game(weapon='storm',board=board,enemy=enemy);self.attack(g)
                self.assertEqual(self.row(g).wear_receipt.durability_before-self.row(g).wear_receipt.durability_after,loss);self.check(g)

    def test_current_and_accepted_windows_differ_when_source_dies_in_same_batch(self):
        rule=HealthRule(HealthFlow.DAMAGE,HealthOp.REDIRECT,layer=HealthLayer.TARGET,target_relation='friendly',target_kinds=(CardType.HERO,),damage_kinds=(DamageKind.COMBAT,),redirect_to='self')
        for window,expected in [('pre_wear_current',1),('combat_accept_original',0)]:
            self.setUp();spec=self.spec('prevent_durability','friendly_minion',window,preds=(WeaponWearPredicate('own_turn'),))
            self.card('source',CardType.MINION,health=1,health_rules=(rule,),weapon_wear_policies=(spec,))
            g=self.game(weapon='many',board=('source',));sid=g.state.players[1].board[0];self.attack(g)
            self.assertEqual(g.state.entities[sid].zone,Zone.GRAVEYARD)
            self.assertEqual(self.row(g).wear_receipt.durability_before-self.row(g).wear_receipt.durability_after,expected);self.check(g)

    def test_dragon_same_batch_death_profiles_use_original_or_current_witness(self):
        rule=HealthRule(HealthFlow.DAMAGE,HealthOp.REDIRECT,layer=HealthLayer.TARGET,target_relation='friendly',target_kinds=(CardType.HERO,),damage_kinds=(DamageKind.COMBAT,),redirect_to='self')
        for window,amount in [('pre_wear_current',1),('combat_accept_original',0)]:
            self.setUp();self.card('lostdragon',CardType.MINION,health=1,tribes=('dragon',),health_rules=(rule,))
            spec=self.spec('prevent_durability',window=window,preds=(WeaponWearPredicate('friendly_tribe_present','dragon'),))
            self.card('conditional',CardType.WEAPON,attack=2,durability=3,weapon_wear_policies=(spec,))
            g=self.game(weapon='conditional',board=('lostdragon',));self.attack(g)
            self.assertEqual(self.row(g).wear_receipt.plan.amount,amount);self.check(g)

    def test_all_rows_foreign_and_losing_priorities_replace_only_once(self):
        one=self.spec('replace_with_attack',priority=2);two=self.spec('replace_with_attack',priority=1)
        self.card('dual',CardType.WEAPON,attack=3,durability=1,weapon_wear_policies=(one,two))
        self.card('source',CardType.MINION,health=30,weapon_wear_policies=(self.spec('prevent_durability','friendly_minion',preds=(WeaponWearPredicate('own_turn'),)),))
        g=self.game(weapon='dual',board=('source',),enemy=('source',));wid=g.state.players[1].weapon_id;self.attack(g)
        r=self.row(g).wear_receipt;self.assertEqual(len(r.plan.decisions),4);self.assertEqual(sum(x.eligible for x in r.plan.decisions),3)
        self.assertEqual(r.plan.replacement[1],g.state.entities[wid].abilities[1].id)
        self.assertEqual((r.attack_after,r.durability_after),(2,1));self.assertEqual(len(r.plan.preventions),1);self.check(g)

    def test_silence_transform_control_and_leave_reenter_use_new_current_rows(self):
        operations=[lambda c,s:[Silence(s)],lambda c,s:[Transform(s,'source')],lambda c,s:[ChangeControl(s,2)],lambda c,s:[ReturnToHand(s)]]
        for i,op in enumerate(operations):
            self.setUp();spec=self.spec('prevent_durability','friendly_minion')
            self.card('source',CardType.MINION,health=30,weapon_wear_policies=(spec,))
            self.watcher('watch','attack_declared',lambda c,op=op:op(c,c.state.players[1].board[0]))
            g=self.game(weapon='many',board=('source','watch'));sid=g.state.players[1].board[0];oldids=[a.id for a in g.state.entities[sid].abilities];self.attack(g)
            r=self.row(g).wear_receipt;self.assertEqual(r.plan.amount,0 if i==1 else 1)
            if i==1:self.assertTrue(set(oldids).isdisjoint({d.ability_id for d in r.plan.decisions}))
            self.check(g)

    def test_declared_weapon_replacement_uses_new_physical_accepted_weapon(self):
        self.watcher('swap','attack_declared',lambda c:[EquipWeapon(1,'gore')])
        g=self.game(weapon='many',board=('swap',));old=g.state.players[1].weapon_id;self.attack(g);new=g.state.players[1].weapon_id
        self.assertNotEqual(old,new);self.assertEqual(self.row(g).combat.weapon_id,new)
        self.assertEqual(g.state.entities[old].durability,5);self.assertEqual(g.state.entities[new].durability,1);self.check(g)

    def test_zero_attack_signed_delta_keeps_durability_and_used_opportunity(self):
        self.card('small',CardType.WEAPON,attack=1,durability=1,keywords=(Keyword.MEGA_WINDFURY,),weapon_wear_policies=(self.spec('replace_with_attack'),))
        g=self.game(weapon='small');wid=g.state.players[1].weapon_id;self.attack(g);self.attack(g)
        r=self.row(g).wear_receipt;self.assertEqual((r.attack_before,r.attack_after,r.durability_after),(0,0,1))
        self.assertEqual(g.state.entities[wid].enchantments[-1].attack,-1);self.assertEqual(g.state.entities[self.hero(g)].attacks_this_turn,2)
        self.assertEqual(hero_attack_count(g.state,1,HeroAttackQuery()),2);self.check(g)

    def test_grant_expiry_is_natural_and_other_loss_origins_are_unchanged(self):
        spec=self.spec('prevent_durability')
        self.spell('grant',lambda c:[GrantWeaponWearPolicy(c.state.players[1].weapon_id,spec,c.source_id,c.state.turn)])
        self.spell('modify',lambda c:[ModifyWeapon(c.state.players[1].weapon_id,durability=-1,source_id=c.source_id)])
        g=self.game(weapon='many',hand=('grant','modify'));self.cast(g,'grant');self.attack(g)
        self.assertEqual(self.row(g).wear_receipt.plan.amount,0);self.cast(g,'modify')
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].durability,4)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.attack(g)
        self.assertEqual(self.row(g).wear_receipt.plan.amount,1);self.check(g)

    def test_current_base_weapon_copy_gets_new_ids_and_no_wear_history_copy(self):
        def copy_current(c):
            e=next(c.state.entities[i]for i in c.state.players[1].hand if c.state.entities[i].card_id=='gore')
            ref=CardReference.capture(e)
            return [CopyCard(ref,1,mode='current'),CopyCard(ref,1,mode='base')]
        from hs_sim.engine.effects import ModifyCost
        from hs_sim.engine.model import CostSpec
        self.spell('discount',lambda c:[ModifyCost(next(i for i in c.state.players[1].hand if c.state.entities[i].card_id=='gore'),CostSpec(delta=-1),c.source_id)])
        self.spell('copy',copy_current)
        g=self.game(hand=('gore','discount','copy'));self.attack(g);self.cast(g,'discount');self.cast(g,'copy')
        hand=[g.state.entities[i]for i in g.state.players[1].hand]
        self.assertEqual([e.cost for e in hand],[2,2,3]);self.assertEqual(len(g.state.hero_attack_history),1)
        original={a.id for a in hand[0].abilities}
        for e in hand[1:]:self.assertTrue(original.isdisjoint({a.id for a in e.abilities}))
        self.check(g)

    def test_magnetic_foreign_declaration_current_copy_remains_independent(self):
        spec=self.spec('prevent_durability','friendly_minion')
        self.card('host',CardType.MINION,health=30,tribes=('mech',))
        self.card('magnet',CardType.MINION,health=3,keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',),weapon_wear_policies=(spec,))
        self.spell('copyhost',lambda c:[CopyMinion(c.state.players[1].board[0],1,mode='current')])
        g=self.game(weapon='many',board=('host',),hand=('magnet','copyhost'));source=self.cast(g,'magnet',position=0);self.cast(g,'copyhost')
        self.attack(g);r=self.row(g).wear_receipt;self.assertEqual(len(r.plan.preventions),2)
        rows=[x.rows[0]for x in r.current.board if x.rows];self.assertNotEqual(rows[0].ability_id,rows[1].ability_id)
        self.assertEqual([x.source_id for x in rows],[source,source]);self.assertEqual([x.declaration.card_id for x in rows],['magnet','magnet']);self.check(g)

    def test_true_declared_wait_nested_known_stale_grant_restore_and_rng_rollback(self):
        spec=self.spec('prevent_durability','friendly_minion')
        def wait(c):
            source=c.state.players[1].board[0]
            return [RequestChoice(1,(ChoiceOption('ok','ok',(ReturnToHand(source),GrantWeaponWearPolicy(source,spec,c.source_id))),
                ChoiceOption('bad','bad',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),EquipWeapon(1,'plain')))),source_id=c.source_id)]
        self.watcher('wait','attack_declared',wait)
        g=self.game(weapon='many',board=('wait',));self.attack(g);self.assertIsNotNone(g.state.pending_choice);self.check(g)
        before=g.snapshot()
        with self.assertRaises(Exception):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(self.row(g).wear_receipt.plan.amount,1);self.check(g)

    def test_last_wear_weapon_deathrattle_wait_replaces_hero_without_rewear(self):
        self.behavior('dr',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',(ReplaceHero(1,'newhero'),EquipWeapon(1,'many'))),),source_id=c.source_id)])
        self.card('last',CardType.WEAPON,attack=3,durability=1,deathrattle='dr')
        g=self.game(weapon='last');wid=g.state.players[1].weapon_id;oldhero=self.hero(g);self.attack(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(hero_attack_count(g.state,1,HeroAttackQuery()),1);self.check(g)
        self.choose(g);self.assertNotEqual(self.hero(g),oldhero)
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].durability,5)
        self.assertEqual(self.row(g).combat.weapon_id,wid);self.assertEqual(sum(e.kind=='weapon_wear_committed'for e in g.events),1);self.check(g)

    def test_rewind_created_weapon_deleted_keeps_original_closed_allocation(self):
        # Synthetic producer exercises the real voluntary BeginAttack path inside
        # a genuine paid/retried spell; it is not a forced-hero card adapter.
        self.spell('retry',lambda c:[EquipWeapon(1,'gore'),BeginAttack(Attack(1,c.state.players[1].hero_id,c.state.players[2].board[0])),
            RequestChoice(1,(ChoiceOption('ok','ok',()),),source_id=c.source_id)],rewind=RewindSpec(1),keywords=(Keyword.REWIND,))
        g=self.game(weapon=None,hand=('retry',));self.cast(g,'retry');first=self.row(g).combat.weapon_id;self.check(g)
        self.choose(g);self.assertEqual(g.state.pending_choice.purpose.value,'rewind');self.choose(g,'retry')
        self.assertNotIn(first,g.state.entities);self.assertNotEqual(self.row(g).combat.weapon_id,first);self.check(g)
        events=[e for e in g.events if e.kind=='weapon_wear_committed'];self.assertEqual(len(events),2)
        self.assertNotEqual(dict(events[0].data)['combat']['identity']['record_id'],dict(events[1].data)['combat']['identity']['record_id'])
        s=g.snapshot();raw=next(e for e in s['events']if e['kind']=='weapon_wear_committed')
        raw['data']['accepted']['weapon']['allocation']=[x for x in raw['data']['accepted']['weapon']['allocation']if x[0]!='next_entity_id'];self.reject(g,s)

    def test_genuine_paid_weapon_payload_wait_preserves_original_proof_scope(self):
        self.behavior('paid',lambda c:[BeginAttack(Attack(1,c.state.players[1].hero_id,c.state.players[2].board[0])),
            RequestChoice(1,(ChoiceOption('ok','ok',(GainArmor(1,1),)),),source_id=c.source_id)])
        self.card('paidweapon',CardType.WEAPON,attack=2,durability=1,cost=3,on_play='paid',weapon_wear_policies=(self.spec('replace_with_attack'),))
        g=self.game(weapon=None,hand=('paidweapon',));physical=self.cast(g,'paidweapon')
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(self.row(g).combat.weapon_id,physical);self.check(g)
        self.choose(g);self.assertEqual(len(g.state.play_history),1);self.assertEqual(self.row(g).wear_receipt.durability_after,1);self.check(g)

    def test_rehashed_current_and_closed_future_foreign_cropped_results_rejected(self):
        g=self.game();self.attack(g);s=g.snapshot()
        alterations=[lambda x:x['state']['hero_attack_history'][0]['wear_receipt']['plan'].update(amount=0),
            lambda x:x['state']['hero_attack_history'][0]['wear_acceptance'].update(record_id=99999),
            lambda x:x['state']['hero_attack_history'][0]['wear_receipt']['current'].update(next_attachment_id=99999),
            lambda x:x['state']['hero_attack_history'][0]['wear_receipt']['plan']['decisions'].clear(),
            lambda x:x['state']['hero_attack_history'][0]['wear_receipt'].update(attack_enchantment_id=99999),
            lambda x:next(e for e in x['events']if e['kind']=='weapon_wear_committed')['data']['receipt']['current'].update(root_action_number=99999),
            lambda x:next(e for e in x['events']if e['kind']=='weapon_wear_committed')['data']['combat'].update(weapon_id=x['state']['players']['2']['hero_id'])]
        for i,change in enumerate(alterations):
            with self.subTest(change=i):
                f=copy.deepcopy(s);change(f);self.reject(g,f)

    def test_rehashed_waiting_grant_unknown_physical_source_rejected(self):
        spec=self.spec('prevent_durability')
        self.watcher('wait','attack_declared',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',(GrantWeaponWearPolicy(c.state.players[1].weapon_id,spec,c.source_id),)),),source_id=c.source_id)])
        g=self.game(board=('wait',));self.attack(g);s=g.snapshot()
        def mutate(x):
            if type(x)is dict:
                if str(x.get('type','')).endswith('GrantWeaponWearPolicy'):x['fields']['source_id']=99999;return True
                return any(mutate(v)for v in x.values())
            if type(x)is list:return any(mutate(v)for v in x)
            return False
        self.assertTrue(mutate(s['resolution_frame']));self.reject(g,s)

    def test_unknown_tribes_origin_profile_and_duplicate_finish_are_explicit(self):
        self.card('unknown',CardType.MINION,health=30,metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=None))
        g=self.game(weapon='storm',board=('unknown',));before=g.snapshot()
        with self.assertRaisesRegex(Exception,'Unknown current minion tribe'):self.attack(g)
        self.assertEqual(g.snapshot(),before)
        with self.assertRaises(ValueError):WeaponWearSpec('prevent_durability',origin='effect_loss')
        with self.assertRaises(ValueError):WeaponWearProfile(window='after_attack')
        self.setUp();self.spell('reuse',lambda c:[RepeatIntrinsicFinish()])
        mechanics=default_mechanics();mechanics.register(RepeatIntrinsicFinish,repeat_finish)
        g=self.game(hand=('reuse',),mechanics=mechanics);self.attack(g);before=g.snapshot()
        with self.assertRaisesRegex(Exception,'unique original accepted exchange'):self.cast(g,'reuse')
        self.assertEqual(g.snapshot(),before);self.check(g,mechanics)

    def test_summoned_final_defender_uses_minion_policy_and_original_declaration(self):
        from hs_sim.engine.interrupts import SummonAttackTarget
        self.watcher('summoner','attack_declared',lambda c:[SummonAttackTarget(dict(c.event.data)['window_id'],2,'shield')])
        g=self.game(board=('summoner',),enemy=());declared=self.hero(g,2);self.attack(g,declared)
        r=self.row(g);self.assertEqual(r.declaration.identity.declared_target_id,declared)
        self.assertNotEqual(r.combat.defender_id,declared);self.assertEqual(r.combat.defender_card_id,'shield')
        self.assertEqual(r.wear_receipt.plan.axis,'attack');self.assertEqual(g.state.entities[r.combat.defender_id].health,30)
        self.check(g)

    def test_titan_opportunities_freeze_cancellation_and_destroy_are_separate(self):
        from hs_sim.engine import UseMinionAbility
        from hs_sim.engine.model import ActivatedAbilitySpec
        from hs_sim.engine.effects import Freeze
        self.behavior('ability',lambda c:[])
        self.card('titan',CardType.MINION,health=30,keywords=(Keyword.TITAN,),
            activated_abilities=tuple(ActivatedAbilitySpec(x,'ability')for x in ('a','b','c')),
            weapon_wear_policies=(self.spec('prevent_durability','friendly_minion'),))
        self.spell('destroyweapon',lambda c:[Destroy(c.state.players[1].weapon_id,c.source_id)])
        g=self.game(weapon='many',board=('titan',),hand=('destroyweapon',));tid=g.state.players[1].board[0];wid=g.state.players[1].weapon_id
        self.attack(g);self.assertEqual(self.row(g).wear_receipt.plan.amount,0)
        self.assertEqual(g.state.entities[tid].attacks_this_turn,0)
        g.apply(UseMinionAbility(1,tid,'a'));self.assertEqual(g.state.entities[tid].attacks_this_turn,1)
        self.assertEqual(g.state.entities[self.hero(g)].attacks_this_turn,1)
        self.cast(g,'destroyweapon');self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(g.state.entities[wid].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[wid].durability,5)
        self.assertEqual(hero_attack_count(g.state,1,HeroAttackQuery()),1);self.check(g)
        self.setUp();self.watcher('freeze','attack_declared',lambda c:[Freeze(c.event.source_id)])
        g=self.game(weapon='many',board=('freeze',));wid=g.state.players[1].weapon_id;self.attack(g)
        r=self.row(g);self.assertEqual(r.terminal.reason,'attacker_frozen')
        self.assertIsNone(r.wear_acceptance);self.assertIsNone(r.wear_receipt)
        self.assertEqual(g.state.entities[wid].durability,5);self.assertEqual(g.state.entities[self.hero(g)].attacks_this_turn,1)
        self.check(g)

    def test_multitribe_minion_and_dragon_location_use_explicit_carrier_scope(self):
        self.behavior('locationbody',lambda c:[])
        self.card('dualtribe',CardType.MINION,health=10,tribes=('mech','dragon'))
        self.card('dragonlocation',CardType.LOCATION,durability=3,tribes=('dragon',),on_use='locationbody')
        for board,amount in [(('dualtribe',),0),(('dragonlocation',),1)]:
            with self.subTest(board=board):
                g=self.game(weapon='storm',board=board);self.attack(g)
                self.assertEqual(self.row(g).wear_receipt.plan.amount,amount)
                self.assertTrue(all(dict(x.allocation)['kind']=='minion'for x in self.row(g).wear_receipt.current.board));self.check(g)

    def test_compact_closed_inputs_after_retry_reject_future_owner_foreign_issuer_and_epoch(self):
        self.spell('retry',lambda c:[EquipWeapon(1,'gore'),BeginAttack(Attack(1,c.state.players[1].hero_id,c.state.players[2].board[0])),
            RequestChoice(1,(ChoiceOption('ok','ok',()),),source_id=c.source_id)],rewind=RewindSpec(1),keywords=(Keyword.REWIND,))
        g=self.game(weapon=None,hand=('retry',));self.cast(g,'retry');old=self.row(g).combat.weapon_id
        self.choose(g);self.choose(g,'retry');self.assertNotIn(old,g.state.entities);self.check(g)
        s=g.snapshot()
        def original(x):return next(e for e in x['events']if e['kind']=='weapon_wear_committed')['data']
        def future_owner(x):
            c=original(x)['combat'];c['identity']['owner_turn_id']=99999;c['delivery']['identity']['owner_turn_id']=99999
        def foreign_issuer(x):
            row=original(x)['accepted']['weapon']['rows'][0]
            row['source_id']=old;row['grant_allocation']=copy.deepcopy(original(x)['accepted']['hero_allocation'])
        def future_epoch(x):
            a=original(x)['accepted']['weapon']['allocation']
            next(v for v in a if v[0]=='zone_epoch')[1]=99999
        for mutate in (future_owner,foreign_issuer,future_epoch):
            with self.subTest(mutate=mutate.__name__):
                f=copy.deepcopy(s);mutate(f);self.reject(g,f)

    def test_original_weapon_stale_after_acceptance_never_wears_new_installation(self):
        from hs_sim.engine.effects import DamageBatch
        mechanics=default_mechanics('isolated-v149-stale-installation');mechanics.replace(DamageBatch,stale_installation_batch)
        g=self.game(mechanics=mechanics);old=g.state.players[1].weapon_id;self.attack(g)
        new=g.state.players[1].weapon_id;r=self.row(g).wear_receipt
        self.assertNotEqual(old,new);self.assertEqual(self.row(g).combat.weapon_id,old)
        self.assertTrue(r.original_stale);self.assertIsNone(r.attack_enchantment_id)
        self.assertEqual((r.durability_before,r.durability_after,r.attack_before,r.attack_after),(1,1,2,2))
        self.assertEqual(g.state.entities[new].durability,5);self.assertEqual(g.state.entities[self.enemy(g)].health,26)
        self.assertEqual(hero_attack_count(g.state,1,HeroAttackQuery()),1);self.check(g,mechanics)

    def test_inactive_starship_dragon_witness_becomes_live_only_after_launch(self):
        from hs_sim.engine import LaunchStarship
        from hs_sim.engine.starships import construction
        self.card('dragonship',CardType.MINION,cost=5,tribes=('dragon',),starship_for=(CardClass.NEUTRAL,))
        self.card('piece',CardType.MINION,attack=2,health=4,keywords=(Keyword.STARSHIP_PIECE,))
        self.spell('killpiece',lambda c:[Destroy(c.state.players[1].board[0],c.source_id)])
        g=self.game(weapon='storm',board=('piece',),hand=('killpiece',));self.cast(g,'killpiece')
        ship=construction(g.state,1);self.assertFalse(ship.active);sid=ship.id
        self.attack(g);self.assertEqual(self.row(g).wear_receipt.plan.amount,1)
        self.assertTrue(any(dict(x.allocation)['entity_id']==sid and not x.active for x in self.row(g).wear_receipt.current.board));self.check(g)
        g.apply(EndTurn(1));g.apply(EndTurn(2));g.apply(LaunchStarship(1,sid));self.attack(g)
        self.assertEqual(self.row(g).wear_receipt.plan.amount,0);self.check(g)

