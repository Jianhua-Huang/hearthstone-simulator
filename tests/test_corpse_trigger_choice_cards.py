"""Real corpse end/death/summon triggers and Volcoross original choice payment."""
from copy import deepcopy
from dataclasses import asdict
import json,unittest
from pathlib import Path
from hs_sim.cards import build_registry
from hs_sim.cards.corpse_trigger_choice_cards import load_batch,BATCH_HASH,NECRO,DIREHORN,FLOWER,VOLCOROSS,FOOTMAN
from hs_sim.engine import (BattlecryRepeatSpec,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Destroy,DestroyBatch,GainArmor,InvokeBehavior,RequestChoice,
    ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.guarded_corpse_spends import SpendCorpsesForMinion
from hs_sim.engine.model import EndTurnSpec,LimitedTriggerSpec,Resource
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.targets import canonical_digest

YETI='CORE_CS2_182';META=CardMetadata(False,(CardClass.NEUTRAL,),None)


def registry():
    r=build_registry()
    def fail(c):raise ResolutionError('K72 deliberate late failure')
    r.register_behavior('k72.fail',fail)
    def reenter(c):
        e=c.state.entities[c.target_id];return(SummonStoredCard(CardReference.capture(e),e.controller),)
    from hs_sim.engine.zones import CardReference
    r.register_behavior('k72.reenter',reenter)
    scripts=dict(destroy=lambda c:(Destroy(c.target_id,c.source_id),),silence=lambda c:(Silence(c.target_id),),
        kill_yetis=lambda c:(DestroyBatch(tuple(i for i in c.state.players[1].board if c.state.entities[i].card_id==YETI),c.source_id),),
        summon_yeti=lambda c:(Summon(2,YETI),))
    for key,body in scripts.items():
        cid='k72.'+key;r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,key,CardType.SPELL,on_play=cid,requires_target=key in('destroy','silence'),metadata=META))
    r.register_card(CardDefinition('k72.form','Different face',CardType.MINION,attack=1,health=8,metadata=META))
    r.register_card(CardDefinition('k72.power','Spell damage fixture',CardType.MINION,health=8,spell_damage=5,metadata=META))
    r.register_card(CardDefinition('k72.bc_double','Native repeat fixture',CardType.MINION,health=12,battlecry_repeats=(BattlecryRepeatSpec(),),metadata=META))
    def wait(c):
        roots=(NECRO,DIREHORN,FLOWER,VOLCOROSS)
        source=next((i for i in c.state.players[1].board if c.state.entities[i].card_id in roots),None)
        target=c.state.successful_summon_history[-1].entity_id if c.state.successful_summon_history else None
        options=[ChoiceOption('ok','Continue',(GainArmor(c.state.players[1].hero_id,1),)),
            ChoiceOption('fault','Fail',(InvokeBehavior('k72.fail',c.source_id,c.player_id),))]
        if source is not None:
            options.extend((ChoiceOption('source_die','Destroy source',(Destroy(source,c.source_id),)),
                ChoiceOption('source_bounce','Return source',(ReturnToHand(source),))))
        if target is not None and c.state.entities[target].card_id==YETI:
            options.extend((ChoiceOption('target_bounce','Return original target',(ReturnToHand(target),)),
                ChoiceOption('target_reenter','Return then summon',(ReturnToHand(target),InvokeBehavior('k72.reenter',c.source_id,2,target))),
                ChoiceOption('target_transform','Transform target',(Transform(target,'k72.form'),)),
                ChoiceOption('target_give','Transfer target',(ChangeControl(target,1),))))
        return(RequestChoice(1,tuple(options),c.source_id),)
    r.register_behavior('k72.wait',wait)
    r.register_card(CardDefinition('k72.wait','Once-only resource window',CardType.MINION,attack=1,health=12,
        limited_triggers=(LimitedTriggerSpec('resource_spent','k72.wait'),),metadata=META))
    def kill_necro(c):
        return tuple(Destroy(i,c.source_id)for i in c.state.players[1].board if c.state.entities[i].card_id==NECRO)
    r.register_behavior('k72.kill_necro',kill_necro)
    r.register_card(CardDefinition('k72.kill_necro','Earlier native end source',CardType.MINION,health=9,
        triggers=(TriggerSpec('turn_ended','k72.kill_necro',EndTurnSpec()),),metadata=META))
    for key,action in(('kill',lambda c:Destroy(c.event.target_id,c.source_id)),('transform',lambda c:Transform(c.event.target_id,'k72.form'))):
        cid='k72.first_'+key
        r.register_behavior(cid,lambda c,action=action:(action(c),)if c.event.player_id==2 else())
        r.register_card(CardDefinition(cid,key,CardType.MINION,health=9,triggers=(TriggerSpec('minion_summoned',cid),),metadata=META))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events']);saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')});return saved


def wires(value,name):
    result=[]
    if isinstance(value,dict):
        if value.get('type','').endswith('.'+name):result.append(value)
        for x in value.values():result.extend(wires(x,name))
    elif isinstance(value,list):
        for x in value:result.extend(wires(x,name))
    return result


class CorpseTriggerChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),corpses=12,enemy=(),enemy_hand=()):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=30,max_mana=30,mana_cap=30,corpses=corpses),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=20,max_mana=20,mana_cap=30)),seed=1072),self.r)
    def entities(self,g,cid,p=1,zone='board'):
        s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid]
    def play(self,g,cid,target=None,p=1):
        eid=self.entities(g,cid,p,'hand')[0].id;g.apply(PlayCard(p,eid,target));return eid
    def bank(self,g):return g.state.players[1].resources[Resource.CORPSES]
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=g.snapshot();other=Game.from_snapshot(saved,registry());self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return other
    def flower_game(self,corpses=12,board=()):
        g=self.game(board=(*board,FLOWER),corpses=corpses,enemy_hand=(YETI,));self.end(g);self.play(g,YETI,p=2);return g
    def test_complete_four_roots_three_real_choices_and_unchanged_footman(self):
        data=load_batch();self.assertEqual(canonical_digest(data),BATCH_HASH)
        self.assertEqual((len(data['cards']),len(data['choices']),len(data['reused_dependencies'])),(4,3,1))
        for row in data['cards']+data['choices']+data['reused_dependencies']+data['evidence_only']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        for row in data['choices']:
            card=self.r.card(row['record']['id']);self.assertTrue(card.choice_only);self.assertFalse(card.hand_playable);self.assertNotIn(card.id,self.r.pool_cards)
        self.assertEqual(set(t.lower()for t in self.r.card(DIREHORN).metadata.tribes),{'beast','undead'})
        self.assertEqual(set(t.lower()for t in self.r.card(VOLCOROSS).metadata.tribes),{'elemental','beast'})
        self.assertEqual(self.r.card(FLOWER).attack,0);self.assertEqual(self.r.card(FOOTMAN).corpse_value,0)
    def test_old1016_definitions_and_default_fingerprint_stay_exact(self):
        before=json.loads((Path(__file__).resolve().parents[1]/'outputs/card-integration-20261014/k72-before/definition-digests.json').read_text(encoding='utf-8'))
        self.assertEqual(len(before),1016);self.assertEqual(before,{cid:canonical_digest(asdict(self.r.card(cid)))for cid in before})
        self.assertEqual(representative().fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')
    def test_necromancer_native_owner_end_raises_one_exact_footman(self):
        g=self.game(board=(NECRO,),corpses=2);self.end(g)
        self.assertEqual((self.bank(g),len(self.entities(g,FOOTMAN))),(1,1));self.end(g)
        self.assertEqual((self.bank(g),len(self.entities(g,FOOTMAN))),(1,1));self.portable(g)
    def test_necromancer_zero_corpses_or_full_board_never_debits(self):
        for board,bank in(((NECRO,),0),((NECRO,)+(YETI,)*6,5)):
            g=self.game(board=board,corpses=bank);self.end(g);self.assertEqual(self.bank(g),bank)
            self.assertFalse(g.state.corpse_spend_history);self.assertFalse(self.entities(g,FOOTMAN))
    def test_necromancer_quantity_extras_do_not_cost_extra_corpses(self):
        g=self.game(board=(NECRO,'CORE_DAL_575'),corpses=1);self.end(g)
        self.assertEqual((self.bank(g),len(self.entities(g,FOOTMAN))),(0,2));self.portable(g)
    def test_necromancer_earlier_end_death_cannot_spend_from_stale_source(self):
        g=self.game(board=('k72.kill_necro',NECRO),corpses=0);self.end(g)
        self.assertEqual(self.bank(g),1);self.assertFalse(self.entities(g,FOOTMAN));self.assertFalse(g.state.corpse_spend_history);self.portable(g)
    def test_necromancer_accepted_payment_survives_later_source_death(self):
        g=self.game(board=(NECRO,'k72.wait'),corpses=2);self.end(g);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g);self.choose(g,'source_die');self.assertEqual(len(self.entities(g,FOOTMAN)),1);self.assertEqual(self.bank(g),2)
    def test_direhorn_uses_real_friendly_death_and_newly_gained_corpse(self):
        g=self.game(('k72.destroy',),board=(DIREHORN,YETI),corpses=2);self.play(g,'k72.destroy',self.entities(g,YETI)[0].id)
        self.assertIn(Keyword.REBORN,self.entities(g,DIREHORN)[0].keywords);self.assertEqual(self.bank(g),0);self.portable(g)
    def test_direhorn_insufficient_corpses_do_not_partially_pay(self):
        g=self.game(('k72.destroy',),board=(DIREHORN,YETI),corpses=0);self.play(g,'k72.destroy',self.entities(g,YETI)[0].id)
        self.assertNotIn(Keyword.REBORN,self.entities(g,DIREHORN)[0].keywords);self.assertEqual(self.bank(g),1);self.assertFalse(g.state.corpse_spend_history)
    def test_direhorn_already_reborn_does_not_pay_for_another_death(self):
        g=self.game(('k72.destroy',)*2,board=(DIREHORN,YETI,YETI),corpses=5)
        self.play(g,'k72.destroy',self.entities(g,YETI)[0].id);self.play(g,'k72.destroy',self.entities(g,YETI)[0].id)
        self.assertEqual(self.bank(g),4);self.assertEqual([x.amount for x in g.state.corpse_spend_history],[3]);self.portable(g)
    def test_direhorn_multiple_same_batch_deaths_recheck_live_reborn(self):
        g=self.game(('k72.kill_yetis',),board=(DIREHORN,YETI,YETI),corpses=5);self.play(g,'k72.kill_yetis')
        self.assertEqual(self.bank(g),4);self.assertEqual([x.amount for x in g.state.corpse_spend_history],[3])
    def test_direhorn_self_or_opponent_death_does_not_spend(self):
        for own in(True,False):
            g=self.game(('k72.destroy',),board=(DIREHORN,),enemy=(YETI,),corpses=5)
            target=self.entities(g,DIREHORN)[0].id if own else self.entities(g,YETI,2)[0].id
            self.play(g,'k72.destroy',target);self.assertFalse(g.state.corpse_spend_history)
    def test_direhorn_reborn_new_body_can_later_gain_reborn_again(self):
        g=self.game(('k72.destroy',)*3,board=(DIREHORN,YETI,YETI),corpses=8)
        self.play(g,'k72.destroy',self.entities(g,YETI)[0].id);old=self.entities(g,DIREHORN)[0].id;self.play(g,'k72.destroy',old)
        new=self.entities(g,DIREHORN)[0];self.assertNotEqual(old,new.id);self.assertNotIn(Keyword.REBORN,new.keywords)
        self.play(g,'k72.destroy',self.entities(g,YETI)[0].id);self.assertIn(Keyword.REBORN,g.state.entities[new.id].keywords)
        self.assertEqual([r.amount for r in g.state.corpse_spend_history],[3,3]);self.portable(g)
    def test_direhorn_silence_removes_future_trigger(self):
        g=self.game(('k72.silence','k72.destroy'),board=(DIREHORN,YETI),corpses=5)
        self.play(g,'k72.silence',self.entities(g,DIREHORN)[0].id);self.play(g,'k72.destroy',self.entities(g,YETI)[0].id)
        self.assertEqual(self.bank(g),6);self.assertFalse(g.state.corpse_spend_history)
    def test_flower_enemy_summon_spends_original_player_bank_and_deals_three(self):
        g=self.flower_game();self.assertEqual(self.bank(g),10);self.assertEqual(self.entities(g,YETI,2)[0].health,2);self.portable(g)
    def test_flower_friendly_summon_or_insufficient_bank_does_not_damage(self):
        g=self.game((YETI,),board=(FLOWER,));self.play(g,YETI);self.assertEqual(self.bank(g),12);self.assertEqual(self.entities(g,YETI)[0].health,5)
        other=self.flower_game(corpses=1);self.assertEqual(self.bank(other),1);self.assertEqual(self.entities(other,YETI,2)[0].health,5)
    def test_flower_minion_ability_damage_ignores_spell_damage(self):
        g=self.flower_game(board=('k72.power',));self.assertEqual(self.entities(g,YETI,2)[0].health,2)
    def test_flower_target_killed_by_earlier_listener_does_not_spend(self):
        g=self.flower_game(board=('k72.first_kill',));self.assertEqual(self.bank(g),12);self.assertFalse(self.entities(g,YETI,2))
        self.assertFalse(g.state.corpse_spend_history)
    def test_flower_original_target_transform_before_payment_is_followed(self):
        g=self.flower_game(board=('k72.first_transform',));self.assertEqual(self.entities(g,'k72.form',2)[0].health,5);self.assertEqual(self.bank(g),10)
    def test_flower_multiple_sources_skip_later_payment_after_target_dies(self):
        g=self.game(board=(FLOWER,FLOWER),enemy_hand=(FOOTMAN,));self.end(g);self.play(g,FOOTMAN,p=2)
        self.assertEqual(self.bank(g),10);self.assertEqual([x.amount for x in g.state.corpse_spend_history],[2]);self.portable(g)
    def test_flower_divine_shield_keeps_target_alive_for_second_source(self):
        g=self.game(board=(FLOWER,FLOWER),enemy_hand=('CORE_EX1_008',));self.end(g);self.play(g,'CORE_EX1_008',p=2)
        self.assertEqual(self.bank(g),8);self.assertEqual([x.amount for x in g.state.corpse_spend_history],[2,2]);self.assertFalse(self.entities(g,'CORE_EX1_008',2))
    def test_flower_payment_choice_restores_clones_and_replays(self):
        g=self.flower_game(board=('k72.wait',));other=self.portable(g);self.choose(g,'ok');self.choose(other,'ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.entities(g,YETI,2)[0].health,2)
    def test_flower_departed_target_does_not_receive_hand_damage(self):
        g=self.flower_game(board=('k72.wait',));target=self.entities(g,YETI,2)[0].id;self.choose(g,'target_bounce')
        self.assertEqual(g.state.entities[target].zone,Zone.HAND);self.assertEqual(g.state.entities[target].health,5);self.assertEqual(self.bank(g),10)
    def test_flower_reentry_has_new_trigger_without_old_damage_rebinding(self):
        g=self.flower_game(board=('k72.wait',));target=self.entities(g,YETI,2)[0].id;self.choose(g,'target_reenter')
        self.assertEqual((g.state.entities[target].zone,g.state.entities[target].health),(Zone.BOARD,2))
        self.assertEqual([x.amount for x in g.state.corpse_spend_history],[2,2]);self.portable(g)
    def test_flower_same_residence_transform_and_control_after_payment_follow(self):
        for key in('target_transform','target_give'):
            g=self.flower_game(board=('k72.wait',));target=self.entities(g,YETI,2)[0].id;self.choose(g,key)
            self.assertEqual(g.state.entities[target].health,5 if key=='target_transform'else 2);self.portable(g)
    def test_flower_source_death_after_payment_keeps_accepted_damage(self):
        g=self.flower_game(board=('k72.wait',));self.choose(g,'source_die')
        self.assertEqual(self.entities(g,YETI,2)[0].health,2);self.assertEqual(self.bank(g),11);self.portable(g)
    def test_volcoross_no_affordable_option_skips_choice_and_corpse_payment(self):
        for corpses in(0,9):
            g=self.game((VOLCOROSS,),corpses=corpses);self.play(g,VOLCOROSS)
            self.assertIsNone(g.state.pending_choice);self.assertEqual(self.bank(g),corpses);self.assertEqual(self.entities(g,VOLCOROSS)[0].attack,5)
    def test_volcoross_offers_only_real_affordable_choices(self):
        for corpses,keys in((10,('10',)),(20,('10','20')),(30,('10','20','30'))):
            g=self.game((VOLCOROSS,),corpses=corpses);self.play(g,VOLCOROSS)
            self.assertEqual(tuple(x.id for x in g.state.pending_choice.options),keys)
            self.assertEqual(tuple(x.card_id for x in g.state.pending_choice.options),tuple('FIR_951t'+str(i+2)for i in range(len(keys))))
    def test_volcoross_each_choice_pays_exact_amount_and_buffs_both_stats(self):
        for amount in(10,20,30):
            g=self.game((VOLCOROSS,),corpses=30);self.play(g,VOLCOROSS);self.choose(g,str(amount));e=self.entities(g,VOLCOROSS)[0]
            self.assertEqual((e.attack,e.health,self.bank(g)),(5+amount,5+amount,30-amount))
        self.portable(g)
    def test_volcoross_real_choice_waiting_has_independent_restore_and_replay(self):
        g=self.game((VOLCOROSS,),corpses=30);self.play(g,VOLCOROSS);other=self.portable(g)
        self.choose(g,'20');self.choose(other,'20');self.assertEqual(g.snapshot(),other.snapshot())
    def test_volcoross_repeat_accepts_new_affordable_options_and_original_source(self):
        g=self.game((VOLCOROSS,),board=('k72.bc_double',),corpses=40);self.play(g,VOLCOROSS);self.choose(g,'10')
        self.assertEqual(tuple(x.id for x in g.state.pending_choice.options),('10','20','30'));self.choose(g,'30')
        e=self.entities(g,VOLCOROSS)[0];self.assertEqual((e.attack,e.health,self.bank(g)),(45,45,0));self.assertEqual(len(g.state.battlecry_history),2);self.portable(g)
    def test_volcoross_paid_source_return_does_not_buff_hand_or_refund(self):
        g=self.game((VOLCOROSS,),board=('k72.wait',),corpses=30);self.play(g,VOLCOROSS);source=self.entities(g,VOLCOROSS)[0].id;self.choose(g,'10')
        self.assertIsNotNone(g.state.pending_choice);self.choose(g,'source_bounce')
        self.assertEqual((g.state.entities[source].zone,g.state.entities[source].attack,self.bank(g)),(Zone.HAND,5,20));self.portable(g)
    def test_bad_resource_choice_rolls_back_to_same_waiting_boundary(self):
        g=self.flower_game(board=('k72.wait',));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
    def test_saved_future_source_or_wrong_gate_shape_is_rejected(self):
        g=self.game((VOLCOROSS,),corpses=30);self.play(g,VOLCOROSS);saved=g.snapshot()
        for field,value in(('entered_order',999999),('zone_epoch',999999)):
            bad=deepcopy(saved);items=wires(bad['resolution_frame'],'SpendCorpsesForMinion');self.assertTrue(items)
            items[0]['fields']['source']['fields'][field]=value
            with self.subTest(field=field),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())
    def test_private_source_and_summon_references_do_not_leak(self):
        g=self.game((VOLCOROSS,),corpses=30);self.play(g,VOLCOROSS)
        for p in(1,2):
            text=json.dumps(g.for_player(p).observe(),ensure_ascii=False)
            for field in('entered_order','zone_epoch','resolution_frame','summon_id','corpse_spend_history','rng_state'):
                self.assertNotIn(field,text)
    def test_guarded_payment_constructor_rejects_invalid_modes_and_thresholds(self):
        g=self.game(board=(DIREHORN,));ref=MinionReference.capture(self.entities(g,DIREHORN)[0])
        for changes in(dict(amount=0),dict(amount=True),dict(mode='invented'),dict(mode='summon'),dict(summon_id=1),dict(on_success=[])):
            kwargs=dict(source=ref,amount=3,on_success=());kwargs.update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):SpendCorpsesForMinion(**kwargs)
    def test_actual_old_schema291_rejected_and_current_default_restores(self):
        root=Path(__file__).resolve().parents[1];self.assertGreater(SNAPSHOT_SCHEMA_VERSION,291)
        for label,factory in(('constructed-v80',build_registry),('default-v65',representative)):
            old=json.loads((root/f'outputs/card-integration-20261014/k72-before/{label}-core366-schema291.json').read_text(encoding='utf-8'))
            with self.subTest(label=label),self.assertRaises(SnapshotError):Game.from_snapshot(old,factory())
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08'),PlayerSetup('HERO_08'))),representative())
        self.assertEqual(Game.from_snapshot(g.snapshot(),representative()).snapshot(),g.snapshot())


if __name__=='__main__':unittest.main()
