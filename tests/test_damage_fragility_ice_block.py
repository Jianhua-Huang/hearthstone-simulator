"""Actual copied fragility and native fatal secret at atomic health settlement."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import damage_fragility_ice_block as native
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.effects import (Buff,ChoiceOption,CopyMinion,Damage,DamageBatch,Destroy,Draw,GainArmor,
    GrantHealthRule,GrantKeyword,Heal,InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.fatal_damage_secrets import RULE,validate_carrier,validate_definition
from hs_sim.engine.health_loss import LoseHealth,SetHeroHealth
from hs_sim.engine.model import (CardClass,CardDefinition,CardType,DamageKind,HealthFlow,HealthLayer,
    HealthLossReplacementSpec,HealthOp,HealthRule,Keyword,SecretSpec,SummonQuantitySpec,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.weapon_damage_replacement import RULE as WEAPON_RULE
from hs_sim.local_pool_format import build_cn37_local_pool_format

REVERB,BLOCK=native.LEAVES;P='k633.'
UNIT,FILL,WATCH,DOUBLE,SHIELD,IMMUNE,FLOOR,REPLACE,WEAPON=(P+x for x in
    ('unit','fill','watch','double','shield','immune','floor','replace','weapon'))
LOW,ARMOR,HIT,HUGE,TWICE,LIFE,ZERO,LOSS,SELF,BUFF,HURT,HEAL,BOUNCE,SILENCE,DRAW,AUTO,FAIL,FORGE=(P+x for x in
    ('low','armor','hit','huge','twice','life','zero','loss','self','buff','hurt','heal','bounce','silence','draw','auto','fail','forge'))


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_damage_fragility_ice_block(r)
    for cid,kw in ((UNIT,()),(FILL,()),(SHIELD,(Keyword.DIVINE_SHIELD,)),(IMMUNE,(Keyword.IMMUNE,)),(DOUBLE,()),(FLOOR,()),(REPLACE,()),(WATCH,())):
        extras={}
        if cid==DOUBLE:extras['summon_quantities']=(SummonQuantitySpec(),)
        if cid==FLOOR:extras['health_rules']=(HealthRule(HealthFlow.DAMAGE,HealthOp.FLOOR,1,layer=HealthLayer.TARGET,target_relation='friendly',target_kinds=(CardType.HERO,)),)
        if cid==REPLACE:extras['health_loss_replacements']=(HealthLossReplacementSpec(own_turn_only=False),)
        if cid==WATCH and mode!='normal':extras['triggers']=(TriggerSpec({'reveal':'secret_revealed','grant':'ability_granted','copy':'minion_summoned'}.get(mode,'health_resolved'),P+'watch'),)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=2 if cid in (UNIT,SHIELD,IMMUNE) else 0,health=10,keywords=kw,metadata=metadata(tribes=()),**extras))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,attack=1,durability=2,health_rules=(WEAPON_RULE,),metadata=metadata(tribes=())))
    def damage(c,n):return (Damage(c.state.players[3-c.player_id].hero_id,n,c.source_id,DamageKind.SPELL),)
    def twice(c):return (DamageBatch(tuple(Damage(c.state.players[3-c.player_id].hero_id,n,c.source_id,DamageKind.SPELL) for n in (3,99,1))),)
    scripts={LOW:lambda c:(SetHeroHealth(c.state.players[c.player_id].hero_id,5,c.source_id),),
        ARMOR:lambda c:(GainArmor(c.player_id,3),),HIT:lambda c:damage(c,3),HUGE:lambda c:damage(c,99),TWICE:twice,
        LIFE:lambda c:damage(c,99),ZERO:lambda c:damage(c,0),
        LOSS:lambda c:(LoseHealth(c.state.players[3-c.player_id].hero_id,99,c.source_id),),
        SELF:lambda c:(Damage(c.state.players[c.player_id].hero_id,99,c.source_id),),
        BUFF:lambda c:(Buff(c.target_id,2,3,c.source_id),),HURT:lambda c:(Damage(c.target_id,1,c.source_id),),
        HEAL:lambda c:(Heal(c.target_id,1,c.source_id),),BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        SILENCE:lambda c:(Silence(c.target_id),),DRAW:lambda c:(Draw(c.player_id,source_id=c.source_id),),
        AUTO:lambda c:(CastSpell(c.player_id,REVERB,c.source_id),),
        FORGE:lambda c:(GrantHealthRule(c.state.players[c.player_id].hero_id,RULE,c.source_id),)}
    for cid,body in scripts.items():
        extra={'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))} if cid in (BUFF,HURT,HEAL,BOUNCE,SILENCE) else {}
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            keywords=(Keyword.LIFESTEAL,) if cid==LIFE else (),metadata=metadata(tribes=()),**extra))
    def fail(c):raise ResolutionError('K633 deliberate RNG rollback')
    r.register_behavior(FAIL,fail)
    def watch(c):
        e=c.event;origin=c.state.entities.get(e.source_id);unit=c.state.entities.get(e.target_id)
        if mode=='reveal':
            if origin is None or origin.card_id!=BLOCK:return ()
        elif mode=='grant':
            if origin is None or origin.card_id not in (BLOCK,REVERB):return ()
        elif mode=='copy':
            if unit is None or unit.card_id not in (UNIT,SHIELD,IMMUNE) or unit.controller!=c.player_id:return ()
        elif mode=='result':
            if e.target_id!=c.state.players[c.player_id].hero_id:return ()
        else:return ()
        options=[ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))]
        if unit is not None and unit.zone==Zone.BOARD:options.append(ChoiceOption('hurt','Damage delivered copy',(Damage(unit.id,1,c.source_id),)))
        return (RequestChoice(c.player_id,tuple(options),c.source_id),)
    r.register_behavior(P+'watch',watch);r.validate();r.freeze();return r


@lru_cache(None)
def host():return build_cn37_local_pool_format().registry


class DamageFragilityIceBlockTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,hand=(),*,board=(),enemy=(),other_hand=(),deck=(FILL,)*10,weapon=None,player=1,mode='normal'):
        self.mode=mode
        setups=[PlayerSetup('mage.hero',hand=hand,board=board,deck=deck,weapon_card_id=weapon,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('warrior.hero',hand=other_hand,board=enemy,deck=(FILL,)*10,mana=40,max_mana=40,mana_cap=40)]
        if player==2:setups.reverse()
        return Game.from_scenario(Scenario(tuple(setups),active_player=player,seed=83),registry(mode))
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def units(self,g,p=1):return [g.state.entities[i] for i in g.state.players[p].board]
    def copies(self,g,p=1):return [e for e in self.units(g,p) if e.card_id in (UNIT,SHIELD,IMMUNE)]
    def fragile(self,g,e):return [a for a in g.state.entities[e].abilities if a.kind=='trigger' and a.behavior_id==native.PREFIX+'fragile' and not a.consumed]
    def arm(self,g,p=1):
        self.play(g,LOW,player=p);source=self.play(g,BLOCK,player=p);g.apply(EndTurn(p));return source
    def settle(self,g):
        while g.state.pending_choice is not None:
            g=self.portable(g);saved=g.snapshot()
            with self.assertRaisesRegex(ResolutionError,'K633'):self.choose(g,'fail')
            self.assertEqual(g.snapshot(),saved);self.choose(g)
        return g

    def test_complete_two_native_faces_two_enchantments_and_four_primary_observations(self):
        d=native.load_batch();rows={x['record']['id']:x['record'] for x in d['dependencies']}
        for o in d['official_observations']:batch.check_face(rows[o['card_id']],o['face'],o['locale'])
        self.assertEqual(set(registry().card(REVERB).metadata.classes),{CardClass.MAGE,CardClass.WARLOCK})
        self.assertEqual(registry().card(BLOCK).health_rules,(RULE,));self.assertFalse(d['cn_calibrated'])

    def test_reverb_real_payment_current_stats_damage_and_both_independent_marks(self):
        g=self.game((BUFF,HURT,REVERB),enemy=(UNIT,));original=self.entity(g,UNIT,2,'board').id
        self.play(g,BUFF,original);self.play(g,HURT,original);self.play(g,REVERB,original)
        copied=self.copies(g)[0];self.assertEqual((copied.attack,copied.health,copied.max_health),(4,12,13))
        self.assertEqual(g.state.players[1].mana,37);self.assertEqual((len(self.fragile(g,original)),len(self.fragile(g,copied.id))),(1,1));self.portable(g)

    def test_reverb_each_member_dies_only_after_its_own_positive_damage(self):
        g=self.game((REVERB,HURT,HURT),enemy=(UNIT,));original=self.entity(g,UNIT,2,'board').id
        self.play(g,REVERB,original);copied=self.copies(g)[0].id;self.play(g,HURT,original)
        self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[copied].zone,Zone.BOARD)
        self.play(g,HURT,copied);self.assertEqual(g.state.entities[copied].zone,Zone.GRAVEYARD);self.portable(g)

    def test_reverb_can_copy_friendly_or_enemy_and_keeps_multiclass_identity(self):
        for friendly in (True,False):
            g=self.game((REVERB,),board=(UNIT,) if friendly else (),enemy=() if friendly else (UNIT,))
            target=self.entity(g,UNIT,1 if friendly else 2,'board').id;self.play(g,REVERB,target)
            self.assertEqual(len(self.copies(g)),2 if friendly else 1);self.assertEqual(len(self.fragile(g,target)),1)

    def test_reverb_full_board_still_marks_original_without_allocating_copy(self):
        g=self.game((REVERB,HURT),board=(FILL,)*7,enemy=(UNIT,));original=self.entity(g,UNIT,2,'board').id
        self.play(g,REVERB,original);self.assertEqual(len(self.fragile(g,original)),1);self.assertFalse(self.copies(g))
        self.play(g,HURT,original);self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD)

    def test_reverb_shield_absorption_and_immune_damage_do_not_destroy_marked_body(self):
        g=self.game((REVERB,HURT,HURT),enemy=(SHIELD,));original=self.entity(g,SHIELD,2,'board').id
        self.play(g,REVERB,original);self.play(g,HURT,original);self.assertEqual(g.state.entities[original].zone,Zone.BOARD)
        self.play(g,HURT,original);self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD)
        g=self.game((REVERB,HURT),board=(IMMUNE,));original=self.entity(g,IMMUNE,1,'board').id
        self.play(g,REVERB,original);self.play(g,HURT,original);self.assertEqual(g.state.entities[original].zone,Zone.BOARD)

    def test_reverb_healing_does_not_trigger_and_silence_removes_fragility(self):
        g=self.game((REVERB,HEAL,SILENCE,HURT),enemy=(UNIT,));original=self.entity(g,UNIT,2,'board').id
        self.play(g,REVERB,original);copied=self.copies(g)[0].id;self.play(g,HEAL,copied)
        self.assertEqual(g.state.entities[copied].zone,Zone.BOARD);self.play(g,SILENCE,copied);self.play(g,HURT,copied)
        self.assertEqual(g.state.entities[copied].health,9);self.assertFalse(self.fragile(g,copied))

    def test_reverb_return_and_replay_resets_ordinary_granted_mark(self):
        g=self.game((REVERB,BOUNCE,HURT),enemy=(UNIT,));original=self.entity(g,UNIT,2,'board').id
        self.play(g,REVERB,original);copied=self.copies(g)[0].id;self.play(g,BOUNCE,copied);self.play(g,UNIT);self.play(g,HURT,copied)
        self.assertEqual(g.state.entities[copied].health,9);self.assertFalse(self.fragile(g,copied));self.portable(g)

    def test_reverb_quantity_expansion_copies_original_mark_to_each_real_delivery(self):
        g=self.game((REVERB,),board=(DOUBLE,),enemy=(UNIT,));original=self.entity(g,UNIT,2,'board').id;self.play(g,REVERB,original)
        self.assertEqual(len(self.copies(g)),2);self.assertTrue(all(len(self.fragile(g,e.id))==1 for e in self.copies(g)))

    def test_reverb_automatic_cast_uses_actual_random_original_target(self):
        g=self.game((AUTO,),enemy=(UNIT,));original=self.entity(g,UNIT,2,'board').id;self.play(g,AUTO)
        self.assertEqual(len(self.copies(g)),1);self.assertEqual(len(self.fragile(g,original)),1);self.portable(g)

    def test_reverb_hero_target_is_illegal_and_rolls_back_payment(self):
        g=self.game((REVERB,));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,REVERB,g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(),before)

    def test_reverb_original_grant_wait_freezes_copy_request_and_restores(self):
        g=self.game((REVERB,),board=(WATCH,),enemy=(UNIT,),mode='grant');original=self.entity(g,UNIT,2,'board').id
        self.play(g,REVERB,original);self.assertIsNotNone(g.state.pending_choice);g=self.settle(g)
        self.assertEqual(len(self.fragile(g,self.copies(g)[0].id)),1);self.portable(g)

    def test_reverb_copy_enters_already_fragile_before_summon_reactions(self):
        g=self.game((REVERB,),board=(WATCH,),enemy=(UNIT,),mode='copy');self.play(g,REVERB,self.entity(g,UNIT,2,'board').id)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);copied=self.copies(g)[0].id
        self.assertEqual(len(self.fragile(g,copied)),1);self.choose(g,'hurt');self.assertEqual(g.state.entities[copied].zone,Zone.GRAVEYARD);self.portable(g)

    def test_block_paid_hidden_secret_duplicate_is_atomic(self):
        g=self.game((BLOCK,BLOCK));source=self.play(g,BLOCK);self.assertEqual(g.state.players[1].mana,37)
        self.assertIn(source,g.state.players[1].secrets);public=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        self.assertNotIn(BLOCK,public);self.assertNotIn('secret_fatal_immunity',public);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,BLOCK)
        self.assertEqual(g.snapshot(),saved)

    def test_block_nonlethal_keeps_secret_then_fatal_preserves_remaining_health(self):
        g=self.game((LOW,BLOCK),other_hand=(HIT,HUGE));self.arm(g);self.play(g,HIT,player=2)
        self.assertEqual(self.hero(g).health,2);self.assertEqual(len(g.state.players[1].secrets),1)
        self.play(g,HUGE,player=2);self.assertEqual(self.hero(g).health,2);self.assertIn(Keyword.IMMUNE,self.hero(g).keywords)
        self.assertFalse(g.state.players[1].secrets);self.assertEqual(g.state.status,'playing');self.portable(g)

    def test_block_fatal_prevention_preserves_all_armor(self):
        g=self.game((LOW,ARMOR,BLOCK),other_hand=(HUGE,));self.play(g,ARMOR);self.arm(g);self.play(g,HUGE,player=2)
        self.assertEqual((self.hero(g).health,self.hero(g).armor),(5,3));self.assertFalse(g.state.players[1].secrets)

    def test_block_armor_can_make_proposed_damage_nonfatal(self):
        g=self.game((LOW,ARMOR,BLOCK),other_hand=(HIT,));self.play(g,ARMOR);self.arm(g);self.play(g,HIT,player=2)
        self.assertEqual((self.hero(g).health,self.hero(g).armor),(5,0));self.assertEqual(len(g.state.players[1].secrets),1)

    def test_block_positive_packets_in_same_batch_use_live_immunity_after_first_fatal(self):
        g=self.game((LOW,BLOCK),other_hand=(TWICE,));self.arm(g);self.play(g,TWICE,player=2)
        self.assertEqual(self.hero(g).health,2);self.assertFalse(g.state.players[1].secrets)
        rows=[e for e in g.events if e.kind=='damage_prevented'];self.assertEqual([dict(e.data)['reason'] for e in rows[-2:]],['rule_prevention','immune']);self.portable(g)

    def test_block_expires_this_opponent_turn_and_not_at_a_later_owner_start(self):
        g=self.game((LOW,BLOCK),other_hand=(HUGE,));self.arm(g);self.play(g,HUGE,player=2)
        self.assertIn(Keyword.IMMUNE,self.hero(g).keywords);g.apply(EndTurn(2))
        self.assertNotIn(Keyword.IMMUNE,self.hero(g).keywords);self.portable(g)

    def test_block_own_turn_lethal_damage_does_not_trigger(self):
        g=self.game((LOW,BLOCK,SELF));self.play(g,LOW);self.play(g,BLOCK);self.play(g,SELF)
        self.assertEqual(g.state.winner,2);self.assertEqual(len(g.state.players[1].secrets),1);self.assertNotIn(Keyword.IMMUNE,self.hero(g).keywords)

    def test_block_zero_damage_and_direct_health_loss_are_not_fatal_damage(self):
        g=self.game((LOW,BLOCK),other_hand=(ZERO,LOSS));self.arm(g);self.play(g,ZERO,player=2)
        self.assertEqual(len(g.state.players[1].secrets),1);self.play(g,LOSS,player=2)
        self.assertEqual(g.state.winner,2);self.assertEqual(len(g.state.players[1].secrets),1)

    def test_block_health_floor_prevents_death_without_consuming_secret(self):
        g=self.game((LOW,BLOCK),board=(FLOOR,),other_hand=(HUGE,));self.arm(g);self.play(g,HUGE,player=2)
        self.assertEqual(self.hero(g).health,1);self.assertEqual(len(g.state.players[1].secrets),1);self.assertNotIn(Keyword.IMMUNE,self.hero(g).keywords)

    def test_block_health_loss_replacement_takes_priority_over_secret(self):
        g=self.game((LOW,BLOCK),board=(REPLACE,),other_hand=(HUGE,));self.arm(g);self.play(g,HUGE,player=2)
        self.assertEqual(len(g.state.players[1].secrets),1);self.assertNotIn(Keyword.IMMUNE,self.hero(g).keywords);self.assertEqual(g.state.status,'playing')

    def test_block_weapon_durability_prevention_precedes_native_fatal_rule(self):
        g=self.game((LOW,BLOCK),weapon=WEAPON,other_hand=(HUGE,));self.arm(g);self.play(g,HUGE,player=2)
        self.assertEqual(self.hero(g).health,5);self.assertEqual(len(g.state.players[1].secrets),1)
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].durability,1)

    def test_block_prevented_damage_does_not_create_lifesteal_credit(self):
        g=self.game((LOW,BLOCK),other_hand=(LOW,LIFE));self.arm(g);self.play(g,LOW,player=2);self.play(g,LIFE,player=2)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(5,5));self.assertFalse(any(e.kind=='lifesteal' for e in g.events))

    def test_block_combat_damage_uses_existing_attack_and_preserves_source(self):
        g=self.game((LOW,BLOCK),enemy=(UNIT,),other_hand=(BUFF,BUFF));self.arm(g);attacker=self.entity(g,UNIT,2,'board').id
        self.play(g,BUFF,attacker,player=2);self.play(g,BUFF,attacker,player=2)
        g.apply(Attack(2,attacker,g.state.players[1].hero_id));self.assertEqual(self.hero(g).health,5)
        self.assertFalse(g.state.players[1].secrets);self.assertIn(Keyword.IMMUNE,self.hero(g).keywords)
        self.assertEqual(g.state.entities[attacker].zone,Zone.BOARD);self.portable(g)

    def test_block_both_seats_keep_actual_hero_and_secret_owner(self):
        g=self.game((LOW,BLOCK),other_hand=(HUGE,),player=2);self.arm(g,2);self.play(g,HUGE,player=1)
        self.assertEqual(self.hero(g,2).health,5);self.assertIn(Keyword.IMMUNE,self.hero(g,2).keywords);self.assertFalse(g.state.players[2].secrets)

    def test_block_reveal_wait_restore_clone_replay_and_rng_failure_rollback(self):
        g=self.game((LOW,BLOCK),board=(WATCH,),other_hand=(HUGE,),mode='reveal');self.arm(g);self.play(g,HUGE,player=2)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.hero(g).health,5);g=self.settle(g);self.portable(g)

    def test_block_ability_and_health_result_waits_preserve_whole_atomic_batch(self):
        for mode in ('grant','result'):
            g=self.game((LOW,BLOCK),board=(WATCH,),other_hand=(TWICE,),mode=mode);self.arm(g);self.play(g,TWICE,player=2)
            self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.hero(g).health,2);g=self.settle(g);self.portable(g)

    def test_fatal_rule_is_finite_and_cannot_be_granted_to_arbitrary_characters(self):
        for kwargs in ({'amount':1},{'target_relation':'self'},{'target_kinds':(CardType.MINION,)},{'layer':HealthLayer.SOURCE}):
            with self.assertRaises(ValueError):replace(RULE,**kwargs)
        card=registry().card(BLOCK)
        with self.assertRaises(ValueError):validate_definition(replace(card,secret=None))
        with self.assertRaises(ValueError):validate_definition(replace(card,secret=replace(card.secret,turn='any')))
        g=self.game((FORGE,));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,FORGE)
        self.assertEqual(g.snapshot(),saved)

    def test_new_operation_rejects_old_schema_and_foreign_granted_carrier(self):
        g=self.game((BLOCK,));self.play(g,BLOCK);saved=g.snapshot();old=json.loads(json.dumps(saved));old['schema_version']-=1
        with self.assertRaises(SnapshotError):Game.from_snapshot(old,registry())
        a=next(a for a in g.state.entities[g.state.players[1].secrets[0]].abilities if a.kind=='health_rule')
        with self.assertRaises(ValueError):validate_carrier(registry(),BLOCK,CardType.SPELL,(replace(a,origin='granted'),))
        self.assertEqual(len(g.state.players[1].secrets),1);self.portable(g)

    def test_complete_local_host_actual_copy_death_and_fatal_secret(self):
        r=host();unit='TTN_480t1'
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(REVERB,'CS2_024'),mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',board=(unit,)))),r)
        self.play(g,REVERB,g.state.players[2].board[0]);copied=g.state.players[1].board[0]
        self.assertTrue(self.fragile(g,copied));self.play(g,'CS2_024',copied);self.assertEqual(g.state.entities[copied].zone,Zone.GRAVEYARD)
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(BLOCK,),mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=('CS2_029',)*6,deck=(unit,)*3,mana=40,max_mana=40,mana_cap=40))),r)
        self.play(g,BLOCK);g.apply(EndTurn(1))
        for _ in range(5):self.play(g,'CS2_029',g.state.players[1].hero_id,player=2)
        self.assertEqual(self.hero(g).health,6);self.assertIn(Keyword.IMMUNE,self.hero(g).keywords);self.assertFalse(g.state.players[1].secrets)


if __name__=='__main__':unittest.main()
