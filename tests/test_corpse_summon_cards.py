"""Real corpse debit, original recipients, fixed token and native entry boundaries."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT, historical_definition_digests
from copy import deepcopy
from dataclasses import asdict,replace
import json,unittest
from pathlib import Path
from hs_sim.cards import build_registry
from hs_sim.cards.corpse_summon_cards import load_batch,BATCH_HASH,CHOW,TOMB,COMMANDER,ARMY,DRAKE,ZOMBIE,FOOTMAN,GHOUL
from hs_sim.engine import (BattlecryRepeatSpec,CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,PlayCard,
    PlayerSetup,Ruleset,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.corpse_summon_rewards import CorpseSummonProfile
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Destroy,GainArmor,GainResource,InvokeBehavior,
    RequestChoice,ReturnToHand,Silence,SpendResource,Summon,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import Resource
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine.resource_operations import SpendUpToResource
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

YETI='CORE_CS2_182';META=CardMetadata(False,(CardClass.NEUTRAL,),None)


def registry():
    r=build_registry()
    def fail(c):raise ResolutionError('K71 deliberate late failure')
    r.register_behavior('k71.fail',fail)
    def resummon(c):
        e=c.state.entities[c.target_id]
        return(SummonStoredCard(CardReference.capture(e),e.controller),)
    r.register_behavior('k71.resummon',resummon)
    scripts={
        'destroy':lambda c:(Destroy(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'summon_commander':lambda c:(Summon(c.player_id,COMMANDER),),
        'auto_chow':lambda c:(CastSpell(c.player_id,CHOW,c.source_id),),
        'auto_army':lambda c:(CastSpell(c.player_id,ARMY,c.source_id),),
    }
    for key,body in scripts.items():
        cid='k71.'+key;r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,key,CardType.SPELL,on_play=cid,requires_target=key in('destroy','silence','bounce'),metadata=META))
    r.register_card(CardDefinition('k71.bc_double','Native repeat fixture',CardType.MINION,health=10,battlecry_repeats=(BattlecryRepeatSpec(),),metadata=META))
    def wait(c):
        result=c.resource_result
        if result is None or result.source_card_id not in(CHOW,TOMB,COMMANDER,ARMY):return()
        target=next((i for i in c.state.players[1].board if c.state.entities[i].card_id in(DRAKE,ZOMBIE)),None)
        options=[ChoiceOption('ok','Continue',(GainArmor(c.state.players[1].hero_id,1),)),
            ChoiceOption('fault','Fail',(InvokeBehavior('k71.fail',c.source_id,1),)),
            ChoiceOption('refund','Gain later corpses',(GainResource(1,Resource.CORPSES,9),)),
            ChoiceOption('debit','Independent later debit',(SpendUpToResource(1,Resource.CORPSES,1,c.source_id),)),
            ChoiceOption('fill','Fill later board',tuple(Summon(1,YETI)for _ in range(7))),
            ChoiceOption('kill_source','Destroy original source',(Destroy(result.source_id,c.source_id),))]
        if target is not None:
            options.extend((ChoiceOption('bounce','Return original',(ReturnToHand(target),)),
                ChoiceOption('reenter','Return then summon',(ReturnToHand(target),InvokeBehavior('k71.resummon',c.source_id,1,target))),
                ChoiceOption('transform','Transform original',(Transform(target,YETI),)),
                ChoiceOption('give','Transfer original',(ChangeControl(target,2),)),
                ChoiceOption('new','Later same name',(Summon(1,c.state.entities[target].card_id),)),
                ChoiceOption('kill','Destroy original',(Destroy(target,c.source_id),))))
        return(RequestChoice(1,tuple(options),c.source_id),)
    def crash(c):
        return(InvokeBehavior('k71.fail',c.source_id,1),)if c.resource_result is not None and c.resource_result.source_card_id in(CHOW,TOMB,COMMANDER,ARMY)else()
    def gain_on_summon(c):
        return(GainResource(1,Resource.CORPSES,1),)if c.state.entities[c.event.target_id].card_id==DRAKE else()
    def spend_on_summon(c):
        return(SpendResource(1,Resource.CORPSES,1),)if c.state.entities[c.event.target_id].card_id==DRAKE else()
    def crash_on_summon(c):
        return(InvokeBehavior('k71.fail',c.source_id,1),)if c.state.entities[c.event.target_id].card_id==DRAKE else()
    for key,event,body in(('wait','resource_spent',wait),('crash','resource_spent',crash),
            ('gain','minion_summoned',gain_on_summon),('spend','minion_summoned',spend_on_summon),('summon_crash','minion_summoned',crash_on_summon)):
        cid='k71.watch.'+key;r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,key,CardType.MINION,attack=1,health=12,triggers=(TriggerSpec(event,cid),),metadata=META))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
    return saved


def wires(value,name):
    result=[]
    if isinstance(value,dict):
        if value.get('type','').endswith('.'+name):result.append(value)
        for x in value.values():result.extend(wires(x,name))
    elif isinstance(value,list):
        for x in value:result.extend(wires(x,name))
    return result


class CorpseSummonCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),corpses=12,enemy=(),rules=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=30,max_mana=30,mana_cap=30,corpses=corpses),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=20,max_mana=20,mana_cap=30)),seed=1071),self.r,ruleset=rules)
    def entities(self,g,cid,p=1,zone='board'):
        s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid]
    def play(self,g,cid,target=None):
        eid=self.entities(g,cid,zone='hand')[0].id;g.apply(PlayCard(1,eid,target));return eid
    def bank(self,g):return g.state.players[1].resources[Resource.CORPSES]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=g.snapshot();other=Game.from_snapshot(saved,registry());self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return other
    def waiting(self,card=CHOW,corpses=12,extra=()):
        g=self.game((card,),board=('k71.watch.wait',*extra),corpses=corpses);self.play(g,card)
        self.assertIsNotNone(g.state.pending_choice);return g
    def test_eight_complete_raw_faces_and_exact_native_tokens(self):
        data=load_batch();self.assertEqual(canonical_digest(data),BATCH_HASH);self.assertEqual((len(data['cards']),len(data['dependencies'])),(4,4))
        for row in data['cards']+data['dependencies']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(set(t.lower()for t in self.r.card(DRAKE).metadata.tribes),{'dragon','undead'})
        for cid in(FOOTMAN,GHOUL):self.assertEqual(self.r.card(cid).corpse_value,0)
        self.assertEqual((self.r.card(FOOTMAN).attack,self.r.card(FOOTMAN).health),(1,3))
        self.assertEqual((self.r.card(GHOUL).attack,self.r.card(GHOUL).health),(2,2))
        self.assertEqual(self.r.card(TOMB).metadata.deck_identity,'RLK_118');self.assertEqual(self.r.card(COMMANDER).metadata.deck_identity,'RLK_506')
    def test_old1008_definitions_and_default_fingerprint_are_unchanged(self):
        before=json.loads((Path(__file__).resolve().parents[1]/'tests/fixtures/history/card-integration-20261014/k71-before/definition-digests.json').read_text(encoding='utf-8'))
        self.assertEqual(len(before),1008);self.assertEqual(before,historical_definition_digests(self.r,before))
        self.assertEqual(representative().fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)
    def test_chow_summons_five_then_spends_fixed_eight_for_rush(self):
        g=self.game((CHOW,));source=self.play(g,CHOW);self.assertEqual(self.bank(g),4)
        self.assertEqual(len(self.entities(g,DRAKE)),5);self.assertTrue(all(Keyword.RUSH in e.keywords for e in self.entities(g,DRAKE)))
        self.assertEqual(g.state.corpse_spend_history[-1].source_id,source);self.assertEqual(g.state.corpse_spend_history[-1].amount,8);self.portable(g)
    def test_chow_insufficient_bank_never_partially_pays_or_grants(self):
        for corpses in(0,1,7):
            with self.subTest(corpses=corpses):
                g=self.game((CHOW,),corpses=corpses);self.play(g,CHOW);self.assertEqual(self.bank(g),corpses)
                self.assertFalse(g.state.corpse_spend_history);self.assertTrue(all(Keyword.RUSH not in e.keywords for e in self.entities(g,DRAKE)))
    def test_tomb_summons_two_taunts_and_pays_four_for_reborn(self):
        g=self.game((TOMB,),corpses=4);self.play(g,TOMB);self.assertEqual(self.bank(g),0)
        self.assertEqual(len(self.entities(g,ZOMBIE)),2)
        self.assertTrue(all({Keyword.TAUNT,Keyword.REBORN}<=e.keywords for e in self.entities(g,ZOMBIE)));self.portable(g)
    def test_tomb_insufficient_bank_still_summons_without_reborn(self):
        g=self.game((TOMB,),corpses=3);self.play(g,TOMB);self.assertEqual(self.bank(g),3)
        self.assertTrue(all(Keyword.TAUNT in e.keywords and Keyword.REBORN not in e.keywords for e in self.entities(g,ZOMBIE)))
    def test_summon_reactions_can_supply_or_remove_threshold_before_acceptance(self):
        g=self.game((CHOW,),board=('k71.watch.gain',),corpses=5);self.play(g,CHOW)
        self.assertEqual(self.bank(g),2);self.assertTrue(all(Keyword.RUSH in e.keywords for e in self.entities(g,DRAKE)))
        other=self.game((CHOW,),board=('k71.watch.spend',),corpses=12);self.play(other,CHOW)
        self.assertEqual(self.bank(other),7);self.assertTrue(all(Keyword.RUSH not in e.keywords for e in self.entities(other,DRAKE)))
        self.assertEqual([r.amount for r in other.state.corpse_spend_history],[1]*5)
    def test_post_summon_full_board_keeps_fixed_debit_policy_without_fake_receivers(self):
        g=self.game((TOMB,),board=(YETI,)*7);self.play(g,TOMB)
        self.assertEqual(self.bank(g),8);self.assertFalse(self.entities(g,ZOMBIE));self.assertEqual(len(g.state.card_summon_history),2);self.portable(g)
    def test_one_free_slot_rewards_only_actual_delivery(self):
        g=self.game((CHOW,),board=(YETI,)*6);self.play(g,CHOW);self.assertEqual(len(self.entities(g,DRAKE)),1)
        self.assertIn(Keyword.RUSH,self.entities(g,DRAKE)[0].keywords);self.assertEqual(self.bank(g),4)
    def test_existing_same_name_minion_is_not_an_original_recipient(self):
        g=self.game((CHOW,),board=(DRAKE,));old=self.entities(g,DRAKE)[0].id;self.play(g,CHOW)
        self.assertNotIn(Keyword.RUSH,g.state.entities[old].keywords);self.assertEqual(sum(Keyword.RUSH in e.keywords for e in self.entities(g,DRAKE)),5)
    def test_quantity_extras_share_original_reward_without_extra_payment(self):
        g=self.game((TOMB,),board=('CORE_DAL_575',));self.play(g,TOMB)
        self.assertEqual(len(self.entities(g,ZOMBIE)),4);self.assertTrue(all(Keyword.REBORN in e.keywords for e in self.entities(g,ZOMBIE)))
        self.assertEqual([x.amount for x in g.state.corpse_spend_history],[4]);self.portable(g)
    def test_chow_quantity_extras_at_capacity_all_receive_rush(self):
        g=self.game((CHOW,),board=('CORE_DAL_575',));self.play(g,CHOW)
        self.assertEqual(len(self.entities(g,DRAKE)),6);self.assertTrue(all(Keyword.RUSH in e.keywords for e in self.entities(g,DRAKE)));self.assertEqual(self.bank(g),4)
    def test_debit_choice_preserves_original_group_and_independent_replay(self):
        g=self.waiting();other=self.portable(g);self.assertEqual(self.bank(g),4)
        self.assertTrue(all(Keyword.RUSH not in e.keywords for e in self.entities(g,DRAKE)))
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertTrue(all(Keyword.RUSH in e.keywords for e in self.entities(g,DRAKE)))
    def test_departure_and_reentry_cannot_steal_old_keyword_reward(self):
        g=self.waiting();target=self.entities(g,DRAKE)[0].id;self.choose(g,'reenter')
        self.assertEqual(g.state.entities[target].zone,Zone.BOARD);self.assertNotIn(Keyword.RUSH,g.state.entities[target].keywords)
        self.assertEqual(sum(Keyword.RUSH in e.keywords for e in self.entities(g,DRAKE)),4);self.portable(g)
    def test_returned_original_does_not_receive_hand_keyword(self):
        g=self.waiting();target=self.entities(g,DRAKE)[0].id;self.choose(g,'bounce')
        self.assertEqual(g.state.entities[target].zone,Zone.HAND);self.assertNotIn(Keyword.RUSH,g.state.entities[target].keywords)
    def test_same_residence_transform_follows_original_recipient(self):
        g=self.waiting();target=self.entities(g,DRAKE)[0].id;self.choose(g,'transform')
        self.assertEqual(g.state.entities[target].card_id,YETI);self.assertIn(Keyword.RUSH,g.state.entities[target].keywords);self.portable(g)
    def test_same_residence_control_change_keeps_original_reward_identity(self):
        g=self.waiting();target=self.entities(g,DRAKE)[0].id;self.choose(g,'give')
        self.assertEqual(g.state.entities[target].controller,2);self.assertIn(Keyword.RUSH,g.state.entities[target].keywords);self.portable(g)
    def test_later_same_name_summon_is_not_in_original_group(self):
        g=self.waiting();self.choose(g,'new');last=self.entities(g,DRAKE)[-1]
        self.assertNotIn(Keyword.RUSH,last.keywords);self.assertEqual(sum(Keyword.RUSH in e.keywords for e in self.entities(g,DRAKE)),5)
    def test_dead_original_is_not_resurrected_by_reward(self):
        g=self.waiting();target=self.entities(g,DRAKE)[0].id;self.choose(g,'kill')
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(sum(Keyword.RUSH in e.keywords for e in self.entities(g,DRAKE)),4)
    def test_independent_later_debit_cannot_replace_original_amount(self):
        g=self.waiting();self.choose(g,'debit');self.assertEqual([r.amount for r in g.state.corpse_spend_history],[8,1])
        self.assertTrue(all(Keyword.RUSH in e.keywords for e in self.entities(g,DRAKE)));self.portable(g)
    def test_choice_failure_rolls_back_to_original_paid_waiting_boundary(self):
        g=self.waiting();saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.assertEqual(self.bank(g),4)
    def test_resource_and_summon_exceptions_roll_back_whole_card(self):
        for watcher in('crash','summon_crash'):
            g=self.game((CHOW,),board=('k71.watch.'+watcher,));saved=g.snapshot()
            with self.subTest(watcher=watcher),self.assertRaises(ResolutionError):self.play(g,CHOW)
            self.assertEqual(g.snapshot(),saved)
    def test_army_raises_exact_actual_corpses_up_to_five(self):
        for corpses in(0,1,3,10):
            g=self.game((ARMY,),corpses=corpses);self.play(g,ARMY);amount=min(corpses,5)
            self.assertEqual((len(self.entities(g,GHOUL)),self.bank(g)),(amount,corpses-amount))
            self.assertEqual(g.state.corpse_spend_history[-1].amount,amount)
        self.portable(g)
    def test_army_capacity_bounds_debit_at_original_acceptance(self):
        g=self.game((ARMY,),board=(YETI,)*6);self.play(g,ARMY)
        self.assertEqual((self.bank(g),len(self.entities(g,GHOUL))),(11,1));self.portable(g)
    def test_raise_uses_configured_board_capacity_and_counts_every_occupant(self):
        g=self.game((ARMY,),board=(YETI,'CORE_REV_990',YETI),rules=Ruleset(max_board=4));self.play(g,ARMY)
        self.assertEqual((self.bank(g),len(self.entities(g,GHOUL))),(11,1));self.portable(g)
    def test_full_raise_board_debits_zero_and_creates_no_minion(self):
        g=self.game((ARMY,),board=(YETI,)*7);self.play(g,ARMY)
        self.assertEqual(self.bank(g),12);self.assertFalse(self.entities(g,GHOUL));self.assertEqual(g.state.corpse_spend_history[-1].amount,0)
    def test_later_refund_does_not_increase_already_debited_raise_count(self):
        g=self.waiting(ARMY,corpses=2);self.assertEqual(self.bank(g),0);self.choose(g,'refund')
        self.assertEqual((self.bank(g),len(self.entities(g,GHOUL))),(9,2));self.portable(g)
    def test_later_capacity_loss_does_not_refund_or_rewrite_original_debit(self):
        g=self.waiting(ARMY,corpses=4);self.choose(g,'fill')
        self.assertEqual((self.bank(g),len(self.entities(g,GHOUL))),(0,0));self.assertEqual(g.state.corpse_spend_history[-1].amount,4);self.portable(g)
    def test_raise_quantity_extras_do_not_spend_extra_corpses(self):
        g=self.game((ARMY,),board=('CORE_DAL_575',),corpses=10);self.play(g,ARMY)
        self.assertEqual((self.bank(g),len(self.entities(g,GHOUL))),(5,6));self.portable(g)
    def test_commander_native_battlecry_and_body_share_exact_footman(self):
        g=self.game((COMMANDER,));source=self.play(g,COMMANDER)
        self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords);self.assertEqual((self.bank(g),len(self.entities(g,FOOTMAN))),(6,6))
        self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)
    def test_commander_repeated_battlecry_accepts_new_capacity_and_bank(self):
        g=self.game((COMMANDER,),board=('k71.bc_double',),corpses=10);self.play(g,COMMANDER)
        self.assertEqual((self.bank(g),len(self.entities(g,FOOTMAN))),(5,5))
        self.assertEqual([r.amount for r in g.state.corpse_spend_history],[5,0]);self.assertEqual(len(g.state.battlecry_history),2);self.portable(g)
    def test_ordinary_commander_summon_does_not_fabricate_battlecry(self):
        g=self.game(('k71.summon_commander',));self.play(g,'k71.summon_commander')
        self.assertEqual(self.bank(g),12);self.assertFalse(self.entities(g,FOOTMAN));self.assertFalse(g.state.battlecry_history)
    def test_commander_death_during_debit_does_not_change_accepted_count(self):
        g=self.waiting(COMMANDER,corpses=3);source=self.entities(g,COMMANDER)[0].id;self.choose(g,'kill_source')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual((self.bank(g),len(self.entities(g,FOOTMAN))),(1,3));self.portable(g)
    def test_no_corpse_tokens_stay_no_corpse_after_silence_and_death(self):
        g=self.game(('k71.silence','k71.destroy','k71.destroy'),board=(FOOTMAN,GHOUL),corpses=0)
        foot=self.entities(g,FOOTMAN)[0].id;ghoul=self.entities(g,GHOUL)[0].id;self.play(g,'k71.silence',foot)
        self.play(g,'k71.destroy',foot);self.play(g,'k71.destroy',ghoul)
        self.assertEqual(self.bank(g),0);self.assertEqual([d.corpse_value for d in g.state.death_history],[0,0]);self.portable(g)
    def test_no_corpse_token_return_and_native_reentry_keep_definition(self):
        g=self.game(('k71.bounce','k71.destroy'),board=(FOOTMAN,),corpses=0);target=self.entities(g,FOOTMAN)[0].id
        self.play(g,'k71.bounce',target);g.apply(PlayCard(1,target));self.play(g,'k71.destroy',target);self.assertEqual(self.bank(g),0)
    def test_reborn_zombie_yields_normal_corpse_and_consumed_keyword(self):
        g=self.game((TOMB,'k71.destroy'),corpses=4);self.play(g,TOMB);target=self.entities(g,ZOMBIE)[0].id;self.play(g,'k71.destroy',target)
        self.assertEqual(self.bank(g),1);reborn=next(e for e in self.entities(g,ZOMBIE)if e.health==1)
        self.assertNotIn(Keyword.REBORN,reborn.keywords);self.assertEqual(reborn.corpse_value,1);self.portable(g)
    def test_automatic_spells_use_actual_cast_and_physical_debit_source(self):
        for driver,token in(('auto_chow',DRAKE),('auto_army',GHOUL)):
            g=self.game(('k71.'+driver,));source=self.play(g,'k71.'+driver)
            cast=next(c for c in g.state.cast_history if c.card_id==(CHOW if driver=='auto_chow'else ARMY))
            self.assertEqual(cast.caster_id,source);self.assertNotEqual(cast.source_id,source)
            self.assertEqual(len(self.entities(g,token)),5);self.assertEqual(g.state.corpse_spend_history[-1].source_id,cast.source_id)
            self.assertEqual(g.state.corpse_spend_history[-1].source_card_id,cast.card_id);self.portable(g)
    def test_saved_complete_group_cannot_be_truncated_duplicated_or_replaced(self):
        for ids in((),(1,),(1,1),(999,)):
            g=self.waiting();saved=g.snapshot();items=wires(saved['resolution_frame'],'FinishCorpseSummons');self.assertTrue(items)
            items[0]['fields']['summon_ids']['tuple']=list(ids)
            with self.subTest(ids=ids),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry())
    def test_saved_raise_capacity_cannot_be_retimed_or_rebound(self):
        for field,value in(('cap',0),('cap',6),('board_limit',8)):
            g=self.waiting(ARMY,corpses=2);saved=g.snapshot();items=wires(saved['resolution_frame'],'FinishCorpseSummons');self.assertTrue(items)
            items[0]['fields'][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry())
    def test_private_original_group_and_payment_context_do_not_leak(self):
        g=self.waiting()
        for player in(1,2):
            text=json.dumps(g.for_player(player).observe(),ensure_ascii=False)
            for field in('summon_ids','board_limit','resolution_frame','corpse_spend_history','source_allocation','rng_state'):
                self.assertNotIn(field,text)
    def test_profiles_are_frozen_and_reject_invented_unsupported_shapes(self):
        original=self.r.corpse_summon_profiles[CHOW]
        for changes in(dict(count=0),dict(mode='unknown'),dict(keyword=Keyword.TAUNT),dict(corpse_cost=0)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(original,**changes)
        with self.assertRaises(TypeError):self.r.corpse_summon_profiles['bad']=original
        with self.assertRaises(ValueError):CorpseSummonProfile(ARMY,GHOUL,'raise',5,keyword=Keyword.RUSH)
    def test_current_default_restore_and_previous_schema_rejection(self):
        root=Path(__file__).resolve().parents[1];self.assertGreater(SNAPSHOT_SCHEMA_VERSION,290)
        for label,factory in(('constructed-v79',build_registry),('default-v65',representative)):
            old=json.loads((root/f'tests/fixtures/history/card-integration-20261014/k71-before/{label}-core365-schema290.json').read_text(encoding='utf-8'))
            with self.subTest(label=label),self.assertRaises(SnapshotError):Game.from_snapshot(old,factory())
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08'),PlayerSetup('HERO_08'))),representative())
        self.assertEqual(Game.from_snapshot(g.snapshot(),representative()).snapshot(),g.snapshot())


if __name__=='__main__':unittest.main()
