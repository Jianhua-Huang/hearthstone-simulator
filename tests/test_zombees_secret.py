"""Real played-minion Secret, exact original summon deliveries and forced combat."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json,unittest
from unittest.mock import patch
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import zombees_secret as native
from hs_sim.engine import EndTurn,Game,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Destroy,GainArmor,InvokeBehavior,RandomDamage,
    RequestChoice,ReturnToHand,Summon,Transform)
from hs_sim.engine.interrupts import CounterMinion
from hs_sim.engine.model import CardClass,CardDefinition,CardType,Keyword,SecretSpec,SummonQuantitySpec,TriggerSpec,Zone
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_attack_groups import SummonAttackProfile,validate_request
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.local_pool_format import build_cn37_local_pool_format

CARD,TOKEN=native.CARD,native.TOKEN
P='k645.'
M,OTHER,WEAK,WALL,DOUBLE,POWER,AUTO,WATCH,FAIL,COUNTER=(P+x for x in
    ('minion','other','weak','wall','double','power','auto','watch','fail','counter'))


def prompt(c):
    return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
        RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),
        source_id=c.source_id,prompt='Original Zombees reaction')


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_zombees_secret(r)
    def fail(c):raise ValueError('K645 deliberate failure')
    r.register_behavior(FAIL,fail)
    def battle(c):
        if mode in('battlecry_wait','battlecry_reveal_wait'):return(prompt(c),GainArmor(c.player_id,2))
        if mode=='battlecry_transform':return(Transform(c.source_id,OTHER),)
        if mode=='battlecry_return':return(ReturnToHand(c.source_id),)
        if mode=='battlecry_death':return(Destroy(c.source_id,c.source_id),)
        return(GainArmor(c.player_id,2),)
    r.register_behavior(M,battle)
    for cid,attack,health,extra in ((M,1,10,dict(battlecry=M,dormant_turns=2 if mode=='dormant'else 0)),
            (OTHER,0,12,{}),(WEAK,1,2,{}),(WALL,0,20,{}),(DOUBLE,0,10,dict(summon_quantities=(SummonQuantitySpec(),))),
            (POWER,0,10,dict(spell_damage=7))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=attack,health=health,metadata=metadata(),**extra))
    r.register_behavior(AUTO,lambda c:(Summon(c.player_id,M),))
    r.register_card(CardDefinition(AUTO,AUTO,CardType.SPELL,on_play=AUTO,metadata=metadata()))
    r.register_behavior(COUNTER,lambda c:(CounterMinion(c.window.id),))
    r.register_secret_condition(COUNTER,lambda c:c.state.entities[c.event.source_id].kind==CardType.MINION)
    r.register_card(CardDefinition(COUNTER,COUNTER,CardType.SPELL,keywords=(Keyword.SECRET,),
        secret=SecretSpec(COUNTER,('card_committed',),COUNTER,COUNTER),metadata=metadata(CardClass.MAGE)))
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id)
        if e.kind=='secret_revealed'and source is not None and source.card_id==CARD:
            row=c.state.play_history[-1];target=row.source_id
            if mode in('reveal_wait','battlecry_reveal_wait'):return(prompt(c),)
            if mode=='reveal_transform':return(Transform(target,OTHER),)
            if mode=='reveal_transfer':return(ChangeControl(target,1),)
            if mode=='reveal_depart':return(ReturnToHand(target),Summon(2,M))
        if e.kind=='minion_summoned'and e.player_id==1:
            if mode=='summon_wait':return(prompt(c),)
            if mode=='root_fail':return(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))
            if mode=='nested'and not any(row.request.cause.source.entity_id==c.source_id for row in c.state.card_summon_history):
                return(SummonByCard(1,(SummonEntryMaterial(TOKEN),),SummonCause.capture(c)),)
        if mode=='attack_wait'and e.kind=='attack_finished'and source is not None and source.card_id==TOKEN:return(prompt(c),)
        return ()
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,metadata=metadata(),triggers=tuple(
        TriggerSpec(event,WATCH)for event in('secret_revealed','minion_summoned','attack_finished'))))
    r.validate();return r


def wires(value,name):
    result=[]
    if isinstance(value,dict):
        if value.get('type','').endswith('.'+name):result.append(value)
        for item in value.values():result.extend(wires(item,name))
    elif isinstance(value,list):
        for item in value:result.extend(wires(item,name))
    return result


@lru_cache(None)
def host():return build_cn37_local_pool_format()


class ZombeesSecretTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,*,mode='normal',board=(),watch=False,own_minion=False):
        self.mode=mode;hand=(CARD,COUNTER,M)if mode=='counter'else(CARD,M)
        g=Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board+((WATCH,)if watch else()),
            deck=(WALL,)*8,mana=10,max_mana=10),PlayerSetup('warrior.hero',hand=(M,WEAK,WALL,AUTO),
            deck=(WALL,)*8,mana=10,max_mana=10)),seed=645),registry(mode))
        self.play(g,CARD)
        if mode=='counter':self.play(g,COUNTER)
        if own_minion:self.play(g,M)
        g.apply(EndTurn(1));return g
    def trigger(self,g,cid=M):return self.play(g,cid,player=2)
    def bees(self,g):return tuple(g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==TOKEN)
    def roots(self,g):return tuple(row for row in g.state.card_summon_history if row.request.cause.source.card_id==CARD)
    def finish(self,g):
        while g.state.pending_choice:self.choose(g)
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')});return s

    def test_full_original_rows_primary_faces_real_token_and_both_printed_tribes(self):
        d=native.load_batch();rows={x['record']['id']:x['record']for x in d['dependencies']}
        for o in d['official_observations']:batch.check_face(rows[o['card_id']],o['face'],o['locale'])
        token=registry().card(TOKEN);self.assertEqual((token.cost,token.attack,token.health),(1,1,1))
        self.assertEqual(token.metadata.tribes,('beast','undead'));self.assertEqual(rows[CARD]['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'],rows[TOKEN]['dbf_id'])
        self.assertFalse(token.metadata.collectible);self.assertFalse(d['source_scope_bound']);self.assertFalse(d['cn_calibrated'])

    def test_invalid_final_token_does_not_partially_register(self):
        r=opening_registry();before=r.fingerprint();d=deepcopy(native.load_batch());d['dependencies'][-1]['record']['attack']=2
        with patch.object(native,'load_batch',return_value=d),self.assertRaises(ValueError):native.register_zombees_secret(r)
        self.assertEqual(r.fingerprint(),before)

    def test_real_secret_after_battlecry_summons_four_then_forces_four_ordinary_attacks(self):
        g=self.game();target=self.trigger(g)
        self.assertEqual(g.state.entities[target].health,6);self.assertFalse(g.state.players[1].secrets);self.assertFalse(self.bees(g))
        self.assertEqual((len(self.roots(g)),len(g.state.character_attack_history)),(4,4));self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,2)
        self.assertTrue(all(row.declaration.forced and row.declaration.combat_relation=='any_minions'for row in g.state.character_attack_history))
        self.assertEqual(g.state.players[1].mana,8);self.assertEqual(len(g.state.play_history),2)
        summons=[e.sequence for e in g.events if e.kind=='minion_summoned'and e.player_id==1]
        attacks=[e.sequence for e in g.events if e.kind=='attack_declared'];self.assertLess(max(summons),min(attacks));self.portable(g)

    def test_early_target_death_skips_remaining_attacks_and_keeps_unspent_bees(self):
        g=self.game();target=self.trigger(g,WEAK)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(len(self.bees(g)),2)
        self.assertEqual(len(g.state.character_attack_history),2);self.assertEqual(len(self.roots(g)),4);self.portable(g)

    def test_one_free_slot_does_not_refill_failed_requests_after_combat_opens_space(self):
        g=self.game(board=(WALL,)*6);target=self.trigger(g)
        self.assertEqual(g.state.entities[target].health,9);self.assertEqual((len(self.roots(g)),len(g.state.character_attack_history)),(4,1))
        self.assertEqual(len(g.state.players[1].board),6);self.assertFalse(self.bees(g));self.portable(g)

    def test_full_owner_board_preserves_secret_until_a_relevant_play_with_space(self):
        g=self.game(board=(WALL,)*7);self.trigger(g)
        self.assertEqual(len(g.state.players[1].secrets),1);self.assertFalse(self.roots(g));self.assertFalse(g.state.character_attack_history)

    def test_quantity_extra_actual_deliveries_join_group_up_to_real_capacity(self):
        g=self.game(board=(DOUBLE,));target=self.trigger(g,WALL)
        self.assertEqual((len(self.roots(g)),len(self.bees(g)),len(g.state.character_attack_history)),(4,6,6))
        self.assertEqual(g.state.entities[target].health,14);self.assertEqual(len(g.state.players[1].board),7);self.portable(g)

    def test_existing_same_named_token_is_not_borrowed_into_original_attack_group(self):
        g=self.game(board=(TOKEN,));old=g.state.players[1].board[0];target=self.trigger(g,WALL)
        self.assertEqual(g.state.entities[old].attacks_this_turn,0);self.assertEqual(len(g.state.character_attack_history),4)
        self.assertEqual(g.state.entities[target].health,16);self.assertEqual(len(self.bees(g)),5)

    def test_nested_same_named_summon_with_different_cause_is_not_group_member(self):
        g=self.game(mode='nested',watch=True);target=self.trigger(g,WALL)
        self.assertEqual((len(self.roots(g)),len(self.bees(g)),len(g.state.character_attack_history)),(4,5,4))
        self.assertEqual(g.state.entities[target].health,16)
        original={d.entity.entity_id for row in self.roots(g)for d in row.deliveries if d.entity is not None}
        self.assertEqual({row.declaration.source_id for row in g.state.character_attack_history},original);self.portable(g)

    def test_battlecry_transformation_follows_original_continuous_minion_residence(self):
        g=self.game(mode='battlecry_transform');target=self.trigger(g)
        self.assertEqual((g.state.entities[target].card_id,g.state.entities[target].health),(OTHER,8));self.assertEqual(len(self.bees(g)),4);self.portable(g)

    def test_battlecry_departure_death_or_dormancy_does_not_reveal_without_original_active_body(self):
        for mode in('battlecry_return','battlecry_death','dormant'):
            g=self.game(mode=mode);self.trigger(g)
            self.assertEqual(len(g.state.players[1].secrets),1);self.assertFalse(self.roots(g));self.assertFalse(g.state.character_attack_history)

    def test_countered_minion_does_not_create_a_target_or_reveal_zombees(self):
        g=self.game(mode='counter');self.trigger(g)
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(len(g.state.players[1].secrets),1);self.assertFalse(self.roots(g));self.portable(g)

    def test_original_hand_submission_survives_battlecry_choice_and_later_reveal_choice(self):
        for mode,wanted in(('battlecry_wait',1),('battlecry_reveal_wait',2)):
            g=self.game(mode=mode,watch=True);target=self.trigger(g);submitted=g.state.play_history[-1].action;count=0
            self.assertIsNotNone(g.state.pending_choice)
            while g.state.pending_choice:
                g=self.portable(g);self.choose(g);count+=1
            self.assertEqual(count,wanted);self.assertGreater(g.state.action_number,submitted)
            self.assertEqual(g.state.entities[target].health,6);self.assertEqual(len(self.roots(g)),4);self.portable(g)

    def test_owner_plays_and_opponent_spell_summons_do_not_trigger_minion_hand_play_secret(self):
        g=self.game(own_minion=True);self.trigger(g,AUTO)
        self.assertEqual(len(g.state.players[1].secrets),1);self.assertFalse(self.roots(g));self.trigger(g)
        self.assertEqual(len(self.roots(g)),4);self.assertFalse(g.state.players[1].secrets)

    def test_reveal_transform_and_control_change_keep_original_explicit_minion_target(self):
        for mode,health,controller in(('reveal_transform',8,2),('reveal_transfer',6,1)):
            g=self.game(mode=mode,watch=True);target=self.trigger(g)
            self.assertEqual((g.state.entities[target].health,g.state.entities[target].controller),(health,controller))
            self.assertEqual(len(g.state.character_attack_history),4);self.portable(g)

    def test_reveal_departure_and_new_same_named_body_do_not_retarget_accepted_attacks(self):
        g=self.game(mode='reveal_depart',watch=True);old=self.trigger(g)
        self.assertEqual(g.state.entities[old].zone,Zone.HAND);self.assertEqual(len(self.bees(g)),4)
        self.assertFalse(g.state.character_attack_history);fresh=self.entity(g,M,2,'board');self.assertNotEqual(fresh.id,old);self.assertEqual(fresh.health,10);self.portable(g)

    def test_global_spell_damage_does_not_change_token_combat_damage(self):
        g=self.game(board=(POWER,));target=self.trigger(g,WALL)
        self.assertEqual(g.state.entities[target].health,16);self.assertEqual(len(g.state.character_attack_history),4)

    def test_reveal_wait_restores_original_event_source_and_complete_request_group(self):
        g=self.game(mode='reveal_wait',watch=True);target=self.trigger(g);self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);self.choose(g);self.assertEqual(g.state.entities[target].health,6);self.assertEqual(len(self.roots(g)),4);self.portable(g)

    def test_each_summon_wait_restores_exact_completed_and_pending_requests(self):
        g=self.game(mode='summon_wait',watch=True);target=self.trigger(g);count=0
        while g.state.pending_choice:
            g=self.portable(g);self.choose(g);count+=1
        self.assertEqual(count,4);self.assertEqual(g.state.entities[target].health,6);self.assertEqual(len(self.roots(g)),4);self.portable(g)

    def test_each_forced_combat_wait_restores_without_repeating_attacks(self):
        g=self.game(mode='attack_wait',watch=True);target=self.trigger(g);count=0
        while g.state.pending_choice:
            g=self.portable(g);self.choose(g);count+=1
        self.assertEqual(count,4);self.assertEqual(g.state.entities[target].health,6);self.assertEqual(len(g.state.character_attack_history),4);self.portable(g)

    def test_action_and_choice_failures_roll_back_payment_history_allocators_and_rng(self):
        g=self.game(mode='root_fail',watch=True);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.trigger(g)
        self.assertEqual(g.snapshot(),before)
        g=self.game(mode='summon_wait',watch=True);self.trigger(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.finish(g);self.assertEqual(len(self.roots(g)),4)

    def test_rehashed_waiting_target_cannot_borrow_future_or_other_residence(self):
        g=self.game(mode='summon_wait',watch=True);self.trigger(g);saved=g.snapshot();nodes=wires(saved['resolution_frame'],'AttackSummonedGroup');self.assertTrue(nodes)
        for node in nodes:node['fields']['target']['fields']['presence_id']=10**8
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry('summon_wait','independent-reader'))

    def test_queued_group_requires_actual_original_minion_event_and_secret_reveal(self):
        g=self.game(mode='summon_wait',watch=True);self.trigger(g)
        node=wires(g.snapshot()['resolution_frame'],'AttackSummonedGroup')[0]
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state,origin_events=g.events);effect=codec.decode(node)
        validate_request(g.registry,effect,g.state,g.events)
        with self.assertRaises(ValueError):validate_request(g.registry,effect,g.state,tuple(e for e in g.events if e.kind!='secret_revealed'))
        bad=replace(effect,original=replace(effect.original,event=replace(effect.original.event,source_id=g.state.players[2].hero_id)))
        with self.assertRaises(ValueError):validate_request(g.registry,bad,g.state,g.events)
        future=replace(effect,original=replace(effect.original,event=replace(effect.original.event,action=effect.original.state.action_number+1)))
        with self.assertRaises(ValueError):validate_request(g.registry,future,g.state,g.events)

    def test_profile_cannot_borrow_ordinary_spell_body_or_automatic_minimum_target_policy(self):
        r=registry('profile_only');before=r.fingerprint()
        with self.assertRaises(ValueError):r.register_summon_attack_profile(SummonAttackProfile(AUTO,TOKEN,4,target_policy='opponent_played_minion'))
        with self.assertRaises(ValueError):SummonAttackProfile(CARD,TOKEN,4,combat_relation='any_minions',target_policy='lowest_health_enemy_if_no_deck_minions')
        self.assertEqual(r.fingerprint(),before)

    def test_player_view_does_not_expose_secret_or_frozen_original_group_context(self):
        g=self.game(mode='summon_wait',watch=True);self.assertNotIn(CARD,json.dumps(g.for_player(2).observe()))
        self.trigger(g);view=json.dumps(g.for_player(2).observe())
        for name in('resolution_frame','SummonAttackProfile','RuleContext','rng_state'):self.assertNotIn(name,view)
        self.portable(g)

    def test_real_local_host_secret_summons_real_dual_tribe_tokens_and_attacks_original_standard_minion(self):
        f=host();g=Game.from_scenario(Scenario((PlayerSetup('HERO_05',hand=(CARD,),mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=('CORE_EX1_162',),deck=('CORE_EX1_162',)*8,mana=10,max_mana=10)),seed=645,generation_context=f.context),f.registry)
        self.play(g,CARD);g.apply(EndTurn(1));target=self.play(g,'CORE_EX1_162',player=2)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(len(self.roots(g)),4)
        self.assertEqual(len(self.bees(g)),2);self.assertTrue(all(f.registry.card(e.card_id).metadata.tribes==('beast','undead')for e in self.bees(g)))


if __name__=='__main__':unittest.main()
