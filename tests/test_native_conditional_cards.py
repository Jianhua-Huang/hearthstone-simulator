"""Actual continuous source qualifications and their shared payment/health lifecycle."""
from dataclasses import asdict,replace
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import reviewed_definition_digest
from hs_sim.cards.native_conditional_cards import load_batch
from hs_sim.engine import (AbilityInstance,Attack,AuraSpec,CardDefinition,CardType,EndTurn,Game,Keyword,
    NativeSourceCondition,PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec,UseHeroPower,Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.cross_zone import TakeCapturedMinion
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,DamageBatch,Destroy,Draw,Heal,
    InvokeBehavior,RequestChoice,Silence,Transform)
from hs_sim.engine.errors import IllegalAction,ResolutionError,SnapshotError
from hs_sim.engine.health_rules import spell_bonus
from hs_sim.engine.model import CostAuraSpec,CostSpec,DamageKind
from hs_sim.engine.native_conditions import validate_carrier
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import canonical_digest

SEER='END_022';SPIDER='JAIL_202';FLETCHER='TIME_606';YETI='CORE_CS2_182'


def registry(mode=None):
    r=build_registry()
    def seer(c):return next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==SEER)
    scripts=dict(heal=lambda c:(Heal(c.target_id,99,c.source_id),),kill=lambda c:(Destroy(c.target_id,c.source_id),),
        silence=lambda c:(Silence(c.target_id),),change=lambda c:(Transform(c.target_id,YETI),),
        give=lambda c:(TakeCapturedMinion(MinionReference.capture(c.state.entities[c.target_id]),3-c.player_id,c.source_id),),
        draw=lambda c:(Draw(c.player_id,source_id=c.source_id),),
        copy=lambda c:(CopyCard(MinionReference.capture(c.state.entities[c.target_id]),c.player_id,mode='current'),),
        cross_copy=lambda c:(CopyCard(MinionReference.capture(c.state.entities[c.target_id]),3-c.player_id,mode='current'),),
        hit=lambda c:(Damage(c.state.players[3-c.player_id].hero_id,1,c.source_id,DamageKind.SPELL),),
        wave=lambda c:(DamageBatch((Damage(seer(c).id,1,c.source_id,DamageKind.SPELL),Damage(c.state.players[3-c.player_id].hero_id,1,c.source_id,DamageKind.SPELL))),),
        heal_hit=lambda c:(Heal(seer(c).id,99,c.source_id),Damage(c.state.players[3-c.player_id].hero_id,1,c.source_id,DamageKind.SPELL)),
        fail=lambda c:(Destroy(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==SPIDER),c.source_id),AddToHand(c.player_id,'missing.k58',c.source_id)),
        fail_choice=lambda c:(AddToHand(c.player_id,'missing.k58',c.source_id),))
    for key,body in scripts.items():
        r.register_behavior('k58.'+key,body);r.register_card(CardDefinition('k58.'+key,key,CardType.SPELL,
            on_play='k58.'+key,requires_target=key in('heal','kill','silence','change','give','copy','cross_copy')))
    r.register_card(CardDefinition('k58.weapon','Ordinary2-Attack weapon fixture',CardType.WEAPON,cost=1,attack=2,durability=2))
    if mode:
        def watch(c):
            if mode=='turn_wait':
                if c.event.player_id!=2:return ()
                if c.state.entities[c.state.players[1].hero_id].attack!=0:raise ResolutionError('Turn-start capture retained an inactive hero aura')
            elif c.event.source_id is None or c.state.entities[c.event.source_id].kind!=CardType.HERO_POWER:return ()
            if mode=='power_kill':return(Destroy(next(i for i in c.state.players[1].board if c.state.entities[i].card_id==FLETCHER),c.source_id),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Rollback',(InvokeBehavior('k58.fail_choice',c.source_id,1),))),c.source_id),)
        behavior='k58.watch.'+mode
        r.register_behavior(behavior,watch);r.register_card(CardDefinition('k58.watch','Original-boundary observer',CardType.MINION,health=5,
            triggers=(TriggerSpec('turn_started'if mode=='turn_wait'else'mana_spent',behavior),)))
    return r


class NativeConditionalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),*,mana=20,mode=None,additional=(),deck=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hero_power_card_id='HERO_08bp',additional_hero_power_card_ids=additional,
            hand=hand,board=board,deck=(YETI,)*8 if deck is None else deck,mana=mana,max_mana=20,mana_cap=20),
            PlayerSetup('HERO_03',hero_power_card_id='HERO_03bp',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=20,max_mana=20,mana_cap=20)),seed=1058),registry(mode)if mode else self.r)
    def find(self,g,cid,p=1,zone='hand'):
        s=g.state;return next(s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def play(self,g,cid,target=None,p=1):
        eid=self.find(g,cid,p).id;g.apply(PlayCard(p,eid,target));return eid
    def wound(self,g,eid=None):
        eid=self.find(g,SEER,zone='board').id if eid is None else eid
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,eid))
    def power_cost(self,g,p=1,eid=None):
        s=g.state;return quote_cost(s,g.registry,s.entities[eid or s.players[p].hero_power_id]).amount
    def hero_attack(self,g,p=1):return g.state.entities[g.state.players[p].hero_id].attack
    def bonus(self,g,p=1):return spell_bonus(g.state,p,g.registry)
    def portable(self,g,mode=None):
        saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,registry(mode)).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def test_complete_three_printed_sources(self):
        data=load_batch();self.assertEqual([x['record']['id']for x in data['cards']],[SEER,SPIDER,FLETCHER])
        for row in data['cards']:self.assertEqual(canonical_digest(row['record']),row['record_sha256']);self.assertEqual(self.r.card(row['record']['id']).cost,1)
    def test_healthy_seer_does_not_supply_spell_damage(self):
        g=self.game(board=(SEER,));self.assertEqual(self.bonus(g),0)
    def test_wounded_seer_supplies_two_to_real_spell_packets(self):
        g=self.game(('k58.hit',),board=(SEER,));self.wound(g);self.assertEqual(self.bonus(g),2);self.play(g,'k58.hit');self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27);self.portable(g)
    def test_hero_power_damage_is_not_spell_damage(self):
        g=self.game(board=(SEER,SEER));first=self.find(g,SEER,zone='board').id;self.wound(g,first);self.assertEqual(g.state.entities[first].health,2);self.assertEqual(self.bonus(g),2)
    def test_healing_immediately_disables_seer(self):
        g=self.game(('k58.heal',),board=(SEER,));self.wound(g);self.play(g,'k58.heal',self.find(g,SEER,zone='board').id);self.assertEqual(self.bonus(g),0)
    def test_dead_seer_does_not_supply_a_bonus(self):
        g=self.game(('k58.kill',),board=(SEER,));self.wound(g);self.play(g,'k58.kill',self.find(g,SEER,zone='board').id);self.assertEqual(self.bonus(g),0)
    def test_silence_removes_native_conditional_provider(self):
        g=self.game(('k58.silence',),board=(SEER,));self.wound(g);self.play(g,'k58.silence',self.find(g,SEER,zone='board').id);self.assertEqual(self.bonus(g),0);self.portable(g)
    def test_transform_removes_old_seer_declaration(self):
        g=self.game(('k58.change',),board=(SEER,));self.wound(g);self.play(g,'k58.change',self.find(g,SEER,zone='board').id);self.assertEqual(self.bonus(g),0)
    def test_one_wounded_and_one_healthy_holder_are_independent(self):
        g=self.game(board=(SEER,SEER));self.wound(g);self.assertEqual(self.bonus(g),2)
    def test_current_copy_tests_new_holder_damage_not_original_provenance(self):
        g=self.game(('k58.copy','k58.heal'),board=(SEER,));original=self.find(g,SEER,zone='board').id;self.wound(g,original);self.play(g,'k58.copy',original);copied=self.play(g,SEER);self.play(g,'k58.heal',copied);self.assertEqual(self.bonus(g),2);self.assertNotEqual(original,copied);self.portable(g)
    def test_damage_batch_uses_its_original_provider_window(self):
        g=self.game(('k58.wave',),board=(SEER,));self.play(g,'k58.wave');self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,29);self.assertEqual(self.bonus(g),2)
    def test_later_packet_sees_healed_source_without_mutating_old_budget(self):
        g=self.game(('k58.heal_hit',),board=(SEER,));self.wound(g);self.play(g,'k58.heal_hit');self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,29);self.assertEqual(self.bonus(g),0)
    def test_transferred_seer_supplies_current_controller(self):
        g=self.game(('k58.give',),board=(SEER,));self.wound(g);self.play(g,'k58.give',self.find(g,SEER,zone='board').id);self.assertEqual((self.bonus(g,1),self.bonus(g,2)),(0,2));self.portable(g)
    def test_spider_gives_one_attack_to_current_friendly_hero(self):
        g=self.game(board=(SPIDER,));self.assertEqual((self.hero_attack(g),self.hero_attack(g,2)),(1,0))
    def test_spider_switches_off_and_on_at_real_turn_boundaries(self):
        g=self.game(board=(SPIDER,));g.apply(EndTurn(1));self.assertEqual(self.hero_attack(g),0);g.apply(EndTurn(2));self.assertEqual(self.hero_attack(g),1);self.portable(g)
    def test_two_physical_spiders_stack(self):
        g=self.game(board=(SPIDER,SPIDER));self.assertEqual(self.hero_attack(g),2)
    def test_silenced_spider_loses_aura_immediately(self):
        g=self.game(('k58.silence',),board=(SPIDER,));self.play(g,'k58.silence',self.find(g,SPIDER,zone='board').id);self.assertEqual(self.hero_attack(g),0)
    def test_dead_spider_loses_aura(self):
        g=self.game(('k58.kill',),board=(SPIDER,));self.play(g,'k58.kill',self.find(g,SPIDER,zone='board').id);self.assertEqual(self.hero_attack(g),0)
    def test_spider_current_controller_and_turn_are_both_required(self):
        g=self.game(('k58.give',),board=(SPIDER,));self.play(g,'k58.give',self.find(g,SPIDER,zone='board').id);self.assertEqual((self.hero_attack(g),self.hero_attack(g,2)),(0,0));g.apply(EndTurn(1));self.assertEqual(self.hero_attack(g,2),1);self.portable(g)
    def test_spider_composes_with_existing_weapon_attack_and_wear(self):
        g=self.game(('k58.weapon',),board=(SPIDER,));self.play(g,'k58.weapon');self.assertEqual(self.hero_attack(g),3);g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27);self.assertEqual(g.state.entities[g.state.players[1].weapon_id].durability,1)
    def test_spider_attack_executes_the_original_hero_combat_pipeline(self):
        g=self.game(board=(SPIDER,));g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,29);self.portable(g)
    def test_stale_hero_aura_cache_is_rejected_without_relying_on_hash_failure(self):
        g=self.game(board=(SPIDER,));g._state.entities[g._state.players[1].hero_id].aura_attack=7
        with self.assertRaisesRegex(ValueError,'Stale derived'):g._assert_stable()
    def test_transforming_spider_retires_the_old_hero_aura(self):
        g=self.game(('k58.change',),board=(SPIDER,));self.play(g,'k58.change',self.find(g,SPIDER,zone='board').id);self.assertEqual(self.hero_attack(g),0)
    def test_fletcher_three_or_fewer_cards_sets_hero_power_zero(self):
        for hand in [(),(YETI,)*3]:
            with self.subTest(size=len(hand)):self.assertEqual(self.power_cost(self.game(hand,board=(FLETCHER,))),0)
    def test_fletcher_four_cards_does_not_change_hero_power_cost(self):
        g=self.game((YETI,)*4,board=(FLETCHER,));self.assertEqual(self.power_cost(g),2)
    def test_playing_a_card_crosses_hand_threshold(self):
        g=self.game((YETI,)*4,board=(FLETCHER,));self.play(g,YETI);self.assertEqual(self.power_cost(g),0);self.portable(g)
    def test_draw_crosses_hand_threshold_back(self):
        g=self.game((YETI,)*3,board=(FLETCHER,),additional=('HERO_07bp',));self.assertEqual(self.power_cost(g),0)
        g.apply(UseHeroPower(1,g.state.players[1].additional_hero_power_ids[0]));self.assertEqual(len(g.state.players[1].hand),4);self.assertEqual(self.power_cost(g),2);self.portable(g)
    def test_zero_cost_power_remains_usable_with_zero_mana(self):
        g=self.game(board=(FLETCHER,),mana=0);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,g.state.players[2].hero_id));self.assertEqual(g.state.players[1].mana,0);self.portable(g)
    def test_silencing_fletcher_restores_ordinary_quote(self):
        g=self.game(('k58.silence',),board=(FLETCHER,));self.play(g,'k58.silence',self.find(g,FLETCHER,zone='board').id);self.assertEqual(self.power_cost(g),2)
    def test_killing_fletcher_restores_ordinary_quote(self):
        g=self.game(('k58.kill',),board=(FLETCHER,));self.play(g,'k58.kill',self.find(g,FLETCHER,zone='board').id);self.assertEqual(self.power_cost(g),2)
    def test_fletcher_does_not_discount_opponent_power(self):
        g=self.game(board=(FLETCHER,));self.assertEqual(self.power_cost(g,2),2)
    def test_transferred_fletcher_requalifies_new_controller_hand(self):
        g=self.game(('k58.give',),board=(FLETCHER,),enemy_hand=(YETI,)*4);self.play(g,'k58.give',self.find(g,FLETCHER,zone='board').id);self.assertEqual((self.power_cost(g),self.power_cost(g,2)),(2,2))
    def test_fletcher_applies_to_existing_additional_hero_power_slots(self):
        g=self.game(board=(FLETCHER,),additional=('HERO_07bp',));self.assertEqual(self.power_cost(g),0);self.assertEqual(self.power_cost(g,eid=g.state.players[1].additional_hero_power_ids[0]),0)
    def test_fletcher_does_not_discount_an_ordinary_hand_card(self):
        g=self.game((YETI,),board=(FLETCHER,));self.assertEqual(quote_cost(g.state,g.registry,self.find(g,YETI)).amount,4)
    def test_quotes_and_observations_do_not_change_any_condition_or_rng(self):
        g=self.game((YETI,),board=(SEER,SPIDER,FLETCHER));before=g.snapshot()
        for _ in range(2):self.bonus(g);self.power_cost(g);g.for_player(1).observe();g.for_player(2).observe();g.legal_actions()
        self.assertEqual(g.snapshot(),before)
    def test_original_zero_payment_survives_provider_removal_reaction(self):
        mode='power_kill';g=self.game(board=(FLETCHER,'k58.watch'),mana=0,mode=mode);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,g.state.players[2].hero_id));self.assertEqual(g.state.players[1].mana,0);self.assertEqual(self.power_cost(g),2);self.portable(g,mode)
    def test_zero_payment_wait_restores_native_condition_and_bad_choice_boundary(self):
        mode='power_wait';g=self.game(board=(FLETCHER,'k58.watch'),mana=0,mode=mode);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,g.state.players[2].hero_id));self.assertIsNotNone(g.state.pending_choice);self.portable(g,mode);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.portable(g,mode)
    def test_turn_start_wait_captures_fresh_hero_aura_before_draw(self):
        mode='turn_wait';g=self.game(board=(SPIDER,'k58.watch'),mode=mode);g.apply(EndTurn(1));self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.hero_attack(g),0);self.portable(g,mode);self.choose(g);self.portable(g,mode)
    def test_invalid_and_unbound_condition_shapes_are_rejected(self):
        for args in [('unknown',None),('self_damaged',3),('controller_hand_at_most',True),('controller_hand_at_most',-1)]:
            with self.assertRaises(ValueError):NativeSourceCondition(*args)
        with self.assertRaises(ValueError):self.r._validate_card(CardDefinition('bad','bad',CardType.MINION,health=1,native_condition=NativeSourceCondition('self_damaged')))
        with self.assertRaises(ValueError):AuraSpec(attack=1,target='friendly_hero',condition='always')
    def test_dynamic_conditional_grant_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):AbilityInstance(1,'spell_damage',source_id=1,spell_damage=2,native_condition=NativeSourceCondition('self_damaged'))
    def test_missing_and_duplicated_native_qualification_are_rejected(self):
        for cid in [SEER,FLETCHER]:
            g=self.game(board=(cid,));e=self.find(g,cid,zone='board');row=next(a for a in e.abilities if a.native_condition is not None)
            bad=[replace(a,native_condition=None)if a.id==row.id else a for a in e.abilities]
            with self.assertRaises(ValueError):validate_carrier(g.registry,e.card_id,e.kind,bad)
            with self.assertRaises(ValueError):validate_carrier(g.registry,e.card_id,e.kind,[*e.abilities,replace(row,id=99999)])
    def test_nonempty_condition_is_signed_and_old_null_pin_view_stays_exact(self):
        e=self.r.card(SEER);self.assertNotEqual(reviewed_definition_digest(e),reviewed_definition_digest(replace(e,native_condition=None)))
        plain=self.r.card(YETI);value=asdict(plain)
        for key in ['reborn_policy','hand_mirror','native_condition']:value.pop(key)
        self.assertEqual(reviewed_definition_digest(plain),canonical_digest(value))
    def test_player_projection_does_not_export_private_provider_objects(self):
        g=self.game(board=(SEER,SPIDER,FLETCHER));text=json.dumps(g.for_player(2).observe(),ensure_ascii=False);self.assertNotIn('native_condition',text);self.assertNotIn('controller_hand_at_most',text)
    def test_current_copy_uses_its_own_controller_hand_not_original_source_hand(self):
        g=self.game(('k58.cross_copy',),board=(FLETCHER,),enemy_hand=(YETI,)*4);self.play(g,'k58.cross_copy',self.find(g,FLETCHER,zone='board').id);g.apply(EndTurn(1));self.play(g,FLETCHER,p=2);self.assertEqual(self.power_cost(g,2),2);self.play(g,YETI,p=2);self.play(g,YETI,p=2);self.assertEqual(self.power_cost(g,2),0);self.assertEqual(self.power_cost(g),0);self.portable(g)
    def test_failure_rolls_back_aura_removal_hand_threshold_and_payment(self):
        g=self.game(('k58.fail',YETI,YETI,YETI),board=(SPIDER,FLETCHER));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k58.fail')
        self.assertEqual(g.snapshot(),before);self.assertEqual((self.hero_attack(g),self.power_cost(g)),(1,2))
    def test_life_tap_draws_one_then_deals_two_actual_hero_power_damage(self):
        g=self.game(additional=('HERO_07bp',));before=len(g.state.players[1].hand);g.apply(UseHeroPower(1,g.state.players[1].additional_hero_power_ids[0]));self.assertEqual(len(g.state.players[1].hand),before+1);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,28);self.portable(g)
    def test_life_tap_self_damage_does_not_use_spell_damage(self):
        g=self.game(('k58.wave',),board=(SEER,),additional=('HERO_07bp',));self.play(g,'k58.wave');self.assertEqual(self.bonus(g),2);g.apply(UseHeroPower(1,g.state.players[1].additional_hero_power_ids[0]));self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,28)
    def test_life_tap_still_damages_after_full_hand_burns_the_draw(self):
        g=self.game((YETI,)*10,additional=('HERO_07bp',));g.apply(UseHeroPower(1,g.state.players[1].additional_hero_power_ids[0]));self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,28)
    def test_life_tap_empty_deck_takes_fatigue_before_its_self_damage(self):
        g=self.game(additional=('HERO_07bp',),deck=());g.apply(UseHeroPower(1,g.state.players[1].additional_hero_power_ids[0]));self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27);self.assertEqual(g.state.players[1].fatigue,1)


if __name__=='__main__':unittest.main()
