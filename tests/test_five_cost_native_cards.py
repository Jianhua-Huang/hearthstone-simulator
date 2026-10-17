"""Real five-cost roots, original draw results and actual batch destruction."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT, historical_definition_digests
from copy import deepcopy
from dataclasses import asdict,replace
import json,unittest
from pathlib import Path

from hs_sim.cards import build_registry
from hs_sim.cards.five_cost_native_cards import (RAGER,SOLDIER,MATRIARCH,ANCIENT,JAILBIRD,HOGDRIVER,SAWBONES,STORM,BROODLING,ROOTS,BATCH_HASH,load_batch)
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,CastWhenDrawnSpec,EndTurn,Game,
    Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,UseHandAction,Zone)
from hs_sim.engine.dark_gifts import DARK_GIFTS,GrantDarkGift
from hs_sim.engine.destruction_resources import DestroyMinionsForResources
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,Draw,ForceAttack,GrantKeyword,
    InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference,DamageKind
from hs_sim.engine.physical_draw_groups import DrawGroupReward,DrawGroupSlot,DrawPhysicalGroup
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1];YETI='CORE_CS2_182';SPELL='CORE_CS2_029'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


def registry():
    r=build_registry();r.register_behavior('k78.noop',lambda c:())
    def fail(c):raise ResolutionError('K78 deliberate failure')
    r.register_behavior('k78.fail',fail)
    for cid,attack,health,keywords in(('fodder',1,1,()),('wall',1,20,()),('reborn',1,1,(Keyword.REBORN,))):
        r.register_card(CardDefinition('k78.'+cid,cid,CardType.MINION,attack=attack,health=health,keywords=keywords,metadata=META))
    r.register_card(CardDefinition('k78.portal','Actual draw-cast root',CardType.SPELL,metadata=META,keywords=(Keyword.CASTS_WHEN_DRAWN,),
        cast_when_drawn=CastWhenDrawnSpec(),on_play='k78.noop'))
    r.register_card(CardDefinition('k78.power','Spell damage is separate',CardType.MINION,health=8,spell_damage=5,metadata=META))
    def choose(c):
        return (RequestChoice(c.player_id,(ChoiceOption('keep','Continue',()),ChoiceOption('fail','Fail',
            (InvokeBehavior('k78.fail',c.source_id,c.player_id),))),c.source_id),)
    def dr(c,mode):
        if mode=='wait':return choose(c)
        if mode=='spawn':return (Summon(c.player_id,'k78.fodder'),)
        target=next((i for p in c.state.players.values()for i in p.board if c.state.entities[i].card_id==('k78.wall'if mode=='collateral'else SAWBONES)),None)
        return (Destroy(target,c.source_id),)if target is not None else ()
    for mode in('wait','spawn','collateral','kill_source'):
        r.register_behavior('k78.dr_'+mode,lambda c,mode=mode:dr(c,mode))
        r.register_card(CardDefinition('k78.dr_'+mode,mode,CardType.MINION,attack=1,health=1,deathrattle='k78.dr_'+mode,metadata=META))
    def wait_draw(c):
        if c.event.player_id!=c.player_id or c.draw is None or c.draw.source_id!=next((i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==HOGDRIVER),None):return ()
        source=c.draw.source_id
        return (RequestChoice(c.player_id,(
            ChoiceOption('keep','Continue',()),
            ChoiceOption('bounce','Bounce original and create another',(ReturnToHand(source),AddToHand(c.player_id,HOGDRIVER,c.source_id))),
            ChoiceOption('transform','Transform original',(Transform(source,YETI),)),
            ChoiceOption('control','Change control',(ChangeControl(source,3-c.player_id),)),
            ChoiceOption('fail','Fail',(InvokeBehavior('k78.fail',c.source_id,c.player_id),))),c.source_id),)
    def nested(c):
        if c.draw is not None and c.draw.id==1 and c.draw.source_id!=c.source_id:return (Draw(c.player_id,source_id=c.source_id),)
        return ()
    for mode,body in(('wait_draw',wait_draw),('nested_draw',nested)):
        r.register_behavior('k78.'+mode,body)
        r.register_card(CardDefinition('k78.'+mode,mode,CardType.MINION,health=20,triggers=(TriggerSpec('card_drawn','k78.'+mode),),metadata=META))
    def gift(c,gift_id):
        target=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].kind==CardType.MINION)
        return (GrantDarkGift(CardReference.capture(target),gift_id,c.source_id),)
    scripts={
        'buff':lambda c:(Buff(c.target_id,2,source_id=c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'force':lambda c:(ForceAttack(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==STORM),c.target_id),),
        'summon_storm':lambda c:(Summon(c.player_id,STORM),),
        'copy_bird':lambda c:(CopyCard(CardReference.capture(next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==JAILBIRD)),c.player_id,Zone.HAND,mode='current',source_id=c.source_id),),
        'gift':lambda c:gift(c,'EDR_100t3'),
        'charge_gift':lambda c:gift(c,'EDR_100t6'),
        'ordinary_keyword':lambda c:(GrantKeyword(c.target_id,Keyword.CHARGE,c.source_id),),
    }
    for name,body in scripts.items():
        r.register_behavior('k78.'+name,body)
        r.register_card(CardDefinition('k78.'+name,name,CardType.SPELL,on_play='k78.'+name,
            targeting=TargetSpec()if name in('buff','silence','kill','force','ordinary_keyword')else None,metadata=META))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events']);saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')});return saved


def nodes(value,typename):
    if isinstance(value,dict):
        if str(value.get('type','')).endswith('.'+typename):yield value
        for v in value.values():yield from nodes(v,typename)
    elif isinstance(value,list):
        for v in value:yield from nodes(v,typename)


class FiveCostNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),deck=(YETI,)*10,enemy_deck=(YETI,)*10,mana=40):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=mana,max_mana=mana,mana_cap=40,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=enemy_deck,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=1078),self.r)
    def entities(self,g,cid,p=1,zone='board'):
        s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid]
    def first(self,g,cid,p=1,zone='board'):return self.entities(g,cid,p,zone)[0]
    def play(self,g,cid,target=None,p=1):
        eid=self.first(g,cid,p,'hand').id;g.apply(PlayCard(p,eid,target));return eid
    def choose(self,g,key):q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,registry()).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def prepare(self,g,cid=SAWBONES,p=1):g.apply(UseHandAction(p,self.first(g,cid,p,'hand').id,'prepare'))
    def price(self,g,cid=JAILBIRD):return g.quote_cost(self.first(g,cid,zone='hand').id).amount

    def test_complete_root_child_enchantment_pins_and_keywords(self):
        data=load_batch();self.assertEqual(canonical_digest(data),BATCH_HASH)
        self.assertEqual((len(data['cards']),len(data['dependencies']),len(data['evidence_only'])),(8,1,5))
        for row in data['cards']+data['dependencies']+data['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertIsNone(self.r.card(STORM).battlecry);self.assertFalse(self.r.card(JAILBIRD).hand_actions)
        self.assertEqual((self.r.card(BROODLING).attack,self.r.card(BROODLING).health,self.r.card(BROODLING).keywords),(4,4,(Keyword.TAUNT,)))
    def test_old1048_definitions_and_default_fingerprint_unchanged(self):
        prior=json.loads((ROOT/'outputs/card-integration-20261014/k78-before/definition-digests.json').read_bytes())
        self.assertEqual(len(prior),1048);self.assertEqual(prior,historical_definition_digests(self.r,prior))
        self.assertEqual(representative().fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)
    def test_rager_current_first_genuine_owner_turn_counts_once(self):
        g=self.game((RAGER,));source=self.play(g,RAGER);self.assertEqual(g.state.entities[source].max_health,2)
    def test_rager_uses_three_owner_starts_not_five_global_turns(self):
        g=self.game((RAGER,));self.cycle(g);self.cycle(g);source=self.play(g,RAGER)
        self.assertEqual((g.state.turn,g.state.entities[source].max_health),(5,4));self.portable(g)
    def test_rager_effect_summon_has_no_battlecry_health(self):
        # An original Scenario placement does not execute the card's Battlecry.
        g=self.game(board=(RAGER,));self.assertEqual(self.first(g,RAGER).max_health,1)
    def test_soldier_doubles_current_attack_and_has_real_rush(self):
        g=self.game((SOLDIER,),enemy=('k78.wall',));source=self.play(g,SOLDIER)
        self.assertEqual(g.state.entities[source].attack,6);g.apply(Attack(1,source,self.first(g,'k78.wall',2).id))
        self.assertEqual(self.first(g,'k78.wall',2).health,14)
    def test_soldier_silence_restores_printed_attack(self):
        g=self.game((SOLDIER,'k78.silence'));source=self.play(g,SOLDIER);self.play(g,'k78.silence',source)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].keywords),(3,set()))
    def test_matriarch_no_gift_does_not_summon(self):
        g=self.game((MATRIARCH,YETI));self.play(g,MATRIARCH);self.assertFalse(self.entities(g,BROODLING))
    def test_matriarch_actual_stored_dark_gift_summons_two_fixed_dragons(self):
        g=self.game((YETI,'k78.gift',MATRIARCH));self.play(g,'k78.gift');self.play(g,MATRIARCH)
        self.assertEqual(len(self.entities(g,BROODLING)),2);self.portable(g)
    def test_matriarch_zero_stat_gift_identity_is_sufficient(self):
        g=self.game((YETI,'k78.charge_gift',MATRIARCH));self.play(g,'k78.charge_gift');self.play(g,MATRIARCH)
        self.assertEqual(len(self.entities(g,BROODLING)),2)
    def test_matriarch_gift_on_board_does_not_satisfy_holding(self):
        g=self.game((YETI,'k78.gift',MATRIARCH));self.play(g,'k78.gift');self.play(g,YETI);self.play(g,MATRIARCH)
        self.assertFalse(self.entities(g,BROODLING))
    def test_matriarch_capacity_still_uses_original_summon_handler(self):
        g=self.game((YETI,'k78.gift',MATRIARCH),board=('k78.fodder',)*5);self.play(g,'k78.gift');self.play(g,MATRIARCH)
        self.assertEqual(len(self.entities(g,BROODLING)),1);self.assertEqual(len(g.state.players[1].board),7)
    def test_ancient_only_dormant_controller_ends_gain_armor_and_draw(self):
        g=self.game((ANCIENT,));source=self.play(g,ANCIENT);initial=len(g.state.players[1].deck)
        g.apply(EndTurn(1));self.assertEqual((g.state.entities[g.state.players[1].hero_id].armor,len(g.state.players[1].deck)),(3,initial-1))
        g.apply(EndTurn(2));self.assertEqual(g.state.entities[source].dormancy.remaining_turns,1)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,6)
        g.apply(EndTurn(2));self.assertIsNone(g.state.entities[source].dormancy)
        count=len(g.state.players[1].deck);g.apply(EndTurn(1));self.assertEqual(len(g.state.players[1].deck),count)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,6);self.portable(g)
    def test_ancient_empty_draw_uses_fatigue_after_armor(self):
        g=self.game((ANCIENT,),deck=());self.play(g,ANCIENT);g.apply(EndTurn(1));hero=g.state.entities[g.state.players[1].hero_id]
        self.assertEqual((hero.health,hero.armor,g.state.players[1].fatigue),(30,2,1))
    def test_jailbird_discounts_invested_mana_without_prepare_bonus(self):
        g=self.game((JAILBIRD,SAWBONES),mana=10);self.prepare(g)
        self.assertEqual((self.price(g),self.price(g,SAWBONES)),(1,0));self.assertEqual(g.state.players[1].mana,6);self.portable(g)
    def test_jailbird_two_actual_prepare_events_floor_cost_at_zero(self):
        g=self.game((JAILBIRD,SAWBONES,SAWBONES),mana=10);self.prepare(g)
        birds=self.entities(g,SAWBONES,zone='hand');g.apply(UseHandAction(1,birds[1].id,'prepare'));self.assertEqual(self.price(g),0)
    def test_jailbird_partial_mana_investment_reduces_only_actual_spend(self):
        g=self.game((JAILBIRD,SAWBONES),mana=2);self.prepare(g);self.assertEqual(self.price(g),3)
    def test_jailbird_only_held_and_friendly_prepare_counts(self):
        g=self.game((SAWBONES,),board=(JAILBIRD,),enemy_hand=(JAILBIRD,),deck=(JAILBIRD,));self.prepare(g)
        self.assertEqual(self.first(g,JAILBIRD).cost,5);self.assertEqual(self.price(g,JAILBIRD)if self.entities(g,JAILBIRD,zone='hand')else 5,5)
        self.assertEqual(g.state.entities[g.state.players[2].hand[0]].cost,5)
    def test_jailbird_current_copy_keeps_discount_and_independent_future_listener(self):
        g=self.game((JAILBIRD,SAWBONES,SAWBONES,'k78.copy_bird'));self.prepare(g);self.play(g,'k78.copy_bird')
        second=self.entities(g,SAWBONES,zone='hand')[1];g.apply(UseHandAction(1,second.id,'prepare'))
        self.assertEqual([g.quote_cost(e.id).amount for e in self.entities(g,JAILBIRD,zone='hand')],[0,0]);self.portable(g)
    def test_hogdriver_two_actual_minions_gain_charge_and_attack_hero(self):
        g=self.game((HOGDRIVER,),deck=(YETI,YETI));source=self.play(g,HOGDRIVER)
        self.assertIn(Keyword.CHARGE,g.state.entities[source].keywords);g.apply(Attack(1,source,g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25);self.portable(g)
    def test_hogdriver_mixed_original_types_do_not_gain_charge(self):
        for deck in((YETI,SPELL),(SPELL,YETI)):
            with self.subTest(deck=deck):
                g=self.game((HOGDRIVER,),deck=deck);source=self.play(g,HOGDRIVER);self.assertNotIn(Keyword.CHARGE,g.state.entities[source].keywords)
    def test_hogdriver_fatigue_is_not_a_second_minion(self):
        g=self.game((HOGDRIVER,),deck=(YETI,));source=self.play(g,HOGDRIVER)
        self.assertNotIn(Keyword.CHARGE,g.state.entities[source].keywords);self.assertEqual(g.state.players[1].fatigue,1)
    def test_hogdriver_burn_still_names_original_minion(self):
        g=self.game((HOGDRIVER,)+(SPELL,)*9,deck=(YETI,YETI));source=self.play(g,HOGDRIVER)
        self.assertEqual([d.outcome for d in g.state.draw_history],['hand','burned']);self.assertIn(Keyword.CHARGE,g.state.entities[source].keywords)
    def test_hogdriver_draw_cast_replacement_does_not_rewrite_original_type(self):
        g=self.game((HOGDRIVER,),deck=('k78.portal',YETI,YETI));source=self.play(g,HOGDRIVER)
        self.assertEqual(len(g.state.draw_history),3);self.assertNotIn(Keyword.CHARGE,g.state.entities[source].keywords);self.portable(g)
    def test_hogdriver_nested_spell_draw_does_not_join_original_group(self):
        g=self.game((HOGDRIVER,),board=('k78.nested_draw',),deck=(YETI,SPELL,YETI));source=self.play(g,HOGDRIVER)
        self.assertEqual(len(g.state.draw_history),3);self.assertIn(Keyword.CHARGE,g.state.entities[source].keywords)
    def test_hogdriver_waiting_restore_and_two_original_roots(self):
        g=self.game((HOGDRIVER,),board=('k78.wait_draw',),deck=(YETI,YETI));source=self.play(g,HOGDRIVER)
        self.assertIsNotNone(g.state.pending_choice);self.assertNotIn(Keyword.CHARGE,g.state.entities[source].keywords);self.portable(g)
        self.choose(g,'keep');self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g,'keep')
        self.assertIn(Keyword.CHARGE,g.state.entities[source].keywords);self.assertEqual(len(g.state.draw_history),2)
    def test_hogdriver_departure_cannot_reward_later_same_named_source(self):
        g=self.game((HOGDRIVER,),board=('k78.wait_draw',),deck=(YETI,YETI));source=self.play(g,HOGDRIVER);self.choose(g,'bounce')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.entities[source].zone,Zone.HAND)
        self.assertEqual(len(self.entities(g,HOGDRIVER,zone='hand')),2)
        self.assertTrue(all(Keyword.CHARGE not in e.keywords for e in self.entities(g,HOGDRIVER,zone='hand')));self.portable(g)
    def test_hogdriver_continuous_transformed_or_controlled_source_uses_same_residence(self):
        for option in('transform','control'):
            with self.subTest(option=option):
                g=self.game((HOGDRIVER,),board=('k78.wait_draw',),deck=(YETI,YETI));source=self.play(g,HOGDRIVER);self.choose(g,option)
                self.assertIsNone(g.state.pending_choice);self.assertIn(Keyword.CHARGE,g.state.entities[source].keywords)
    def test_hogdriver_failed_draw_choice_is_atomic(self):
        g=self.game((HOGDRIVER,),board=('k78.wait_draw',),deck=(YETI,YETI));self.play(g,HOGDRIVER);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)
    def test_hogdriver_rehashed_frame_cannot_borrow_future_presence(self):
        g=self.game((HOGDRIVER,),board=('k78.wait_draw',),deck=(YETI,YETI));self.play(g,HOGDRIVER);saved=g.snapshot()
        reward=next(nodes(saved,'DrawGroupReward'));reward['fields']['source']['fields']['presence_id']=g.state.next_order+100
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry())
    def test_draw_reward_contract_rejects_renamed_source_or_wrong_slot_plan(self):
        g=self.game(board=(HOGDRIVER,));source=self.first(g,HOGDRIVER);ref=BoardPresenceReference.capture(g.state,source.id)
        reward=DrawGroupReward('source_charge_if_both_minions',source=ref)
        with self.assertRaises(ValueError):DrawPhysicalGroup(1,source.id,(DrawGroupSlot(),),reward)
        with self.assertRaises(ValueError):DrawGroupReward('none',source=ref)
    def test_sawbones_destroys_other_allies_draws_and_refreshes_actual_count(self):
        g=self.game((SAWBONES,),board=('k78.fodder',YETI),enemy=('k78.wall',),deck=(YETI,)*4,mana=10);source=self.play(g,SAWBONES)
        self.assertEqual(g.state.players[1].board,[source]);self.assertEqual((len(g.state.draw_history),g.state.players[1].mana),(2,7))
        self.assertEqual(len(g.state.players[2].board),1);self.portable(g)
    def test_sawbones_no_other_minion_has_no_draw_or_refresh(self):
        g=self.game((SAWBONES,),mana=10);self.play(g,SAWBONES);self.assertEqual((len(g.state.draw_history),g.state.players[1].mana),(0,5))
    def test_sawbones_dormant_minions_are_not_destroyed_or_counted(self):
        g=self.game((SAWBONES,),board=(ANCIENT,'k78.fodder'),mana=10);self.play(g,SAWBONES)
        self.assertEqual((len(g.state.draw_history),g.state.players[1].mana),(1,6));self.assertTrue(self.entities(g,ANCIENT))
    def test_sawbones_nested_deaths_and_reborn_bodies_not_double_counted(self):
        g=self.game((SAWBONES,),board=('k78.dr_collateral','k78.reborn'),enemy=('k78.wall',),mana=10);self.play(g,SAWBONES)
        self.assertEqual(len(g.state.death_history),3);self.assertEqual((len(g.state.draw_history),g.state.players[1].mana),(2,7))
        self.assertEqual(len(self.entities(g,'k78.reborn')),1);self.assertEqual(self.first(g,'k78.reborn').health,1)
    def test_sawbones_deathrattle_spawn_not_an_original_victim(self):
        g=self.game((SAWBONES,),board=('k78.dr_spawn',),mana=10);self.play(g,SAWBONES)
        self.assertEqual((len(g.state.draw_history),g.state.players[1].mana),(1,6));self.assertEqual(len(self.entities(g,'k78.fodder')),1)
    def test_sawbones_source_death_does_not_remove_original_resource_reward(self):
        g=self.game((SAWBONES,),board=('k78.dr_kill_source','k78.fodder'),mana=10);source=self.play(g,SAWBONES)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual((len(g.state.draw_history),g.state.players[1].mana),(2,7))
    def test_sawbones_waiting_deathrattle_restore_choice_failure_and_original_receipt(self):
        g=self.game((SAWBONES,),board=('k78.dr_wait','k78.fodder'),mana=10);self.play(g,SAWBONES);self.portable(g)
        self.assertEqual(len(g.state.draw_history),0);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'keep');self.assertEqual((len(g.state.draw_history),g.state.players[1].mana),(2,7));self.portable(g)
    def test_sawbones_rehashed_pending_reward_cannot_omit_accepted_cause(self):
        g=self.game((SAWBONES,),board=('k78.dr_wait','k78.fodder'));self.play(g,SAWBONES);saved=g.snapshot()
        reward=next(nodes(saved,'CompleteDestroyedResources'));self.assertEqual(len(reward['fields']['accepted']['tuple']),2)
        reward['fields']['accepted']['tuple'].pop()
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry())
    def test_storm_first_damage_kills_target_without_retaliation(self):
        g=self.game(('k78.force',),board=(STORM,),enemy=('k78.fodder',));source=self.first(g,STORM).id;target=self.first(g,'k78.fodder',2).id
        self.play(g,'k78.force',target);self.assertEqual(g.state.entities[source].health,6)
        self.assertEqual(g.state.character_attack_history[-1].terminal.status,'cancelled');self.portable(g)
    def test_storm_surviving_target_receives_three_then_normal_combat(self):
        g=self.game(('k78.force',),board=(STORM,'k78.power'),enemy=('k78.wall',));self.play(g,'k78.force',self.first(g,'k78.wall',2).id)
        self.assertEqual((self.first(g,'k78.wall',2).health,self.first(g,STORM).health),(14,5))
        rows=[e for e in g.events if e.kind=='damage_dealt'and e.source_id==self.first(g,STORM).id]
        self.assertEqual([e.amount for e in rows],[3,3])
    def test_storm_other_attacker_does_not_trigger_and_silence_removes_ability(self):
        g=self.game(('k78.silence',),board=(STORM,YETI),enemy=('k78.wall',));target=self.first(g,'k78.wall',2).id
        g.apply(Attack(1,self.first(g,YETI).id,target));self.assertEqual(self.first(g,'k78.wall',2).health,16)
        self.play(g,'k78.silence',self.first(g,STORM).id);g.apply(Attack(1,self.first(g,STORM).id,target));self.assertEqual(self.first(g,'k78.wall',2).health,13)
    def test_storm_kindred_previous_owner_elemental_grants_rush_only_on_play(self):
        g=self.game((STORM,STORM),enemy=('k78.wall',));first=self.play(g,STORM)
        self.assertNotIn(Keyword.RUSH,g.state.entities[first].keywords);self.cycle(g);second=self.play(g,STORM)
        self.assertIn(Keyword.RUSH,g.state.entities[second].keywords);g.apply(Attack(1,second,self.first(g,'k78.wall',2).id));self.portable(g)
    def test_storm_effect_summon_does_not_gain_kindred_rush(self):
        g=self.game((STORM,'k78.summon_storm'));self.play(g,STORM);self.cycle(g);self.play(g,'k78.summon_storm')
        self.assertTrue(all(Keyword.RUSH not in e.keywords for e in self.entities(g,STORM)))
    def test_private_waiting_materials_not_in_player_projection(self):
        g=self.game((HOGDRIVER,),board=('k78.wait_draw',),deck=(YETI,YETI));self.play(g,HOGDRIVER)
        for p in(1,2):
            text=json.dumps(g.observe(p),ensure_ascii=False)
            for private in('DrawGroupReward','CompleteDestroyedResources','source_charge_if_both_minions','hand_cursor','presence_id'):
                self.assertNotIn(private,text)
        saved=g.snapshot();g.observe(1);g.observe(2);g.for_player(1).legal_actions();self.assertEqual(g.snapshot(),saved)
    def test_previous_schema296_snapshot_is_rejected(self):
        for name in('constructed-v86','default-v65'):
            with self.subTest(name=name),self.assertRaises(SnapshotError):Game.from_snapshot(json.loads((ROOT/f'outputs/card-integration-20261014/k78-before/{name}-core371-schema296.json').read_bytes()),self.r if name.startswith('constructed')else representative())


if __name__=='__main__':unittest.main()
