"""Original paid cost rewards and real next-owner-turn taxes through shared machinery."""
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.next_play_price_cards import load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,CostSpec,EndTurn,Game,
    Keyword,PlayCard,PlayerSetup,Rarity,Scenario,SelectChoice,SnapshotError,TriggerSpec,UseHeroPower,Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddCostModifier,AddToHand,ChangeControl,ChoiceOption,CopyMinion,
    Destroy,GainArmor,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import CounterMinion
from hs_sim.engine.model import TribeChangeSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

GLIDER='TLC_428';SLOW='TIME_716';TAR='TLC_439';PRIMER='DINO_404'
MURLOC='TLC_427';YETI='CORE_CS2_182';ROCK='WW_001t'


def registry():
    r=build_registry()
    def types(c,cid,tribe):
        entity=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==cid)
        return(ChangeMinionTribes(CardReference.capture(entity),TribeChangeSpec('set',(tribe,)),c.source_id),)
    bodies=dict(silence=lambda c:(Silence(c.target_id),),kill=lambda c:(Destroy(c.target_id,c.source_id),),
        bounce=lambda c:(ReturnToHand(c.target_id),),give=lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        copy=lambda c:(CopyMinion(c.target_id,c.player_id),),summon=lambda c:(Summon(c.player_id,MURLOC),),
        type_yeti=lambda c:types(c,YETI,'murloc'),type_murloc=lambda c:types(c,MURLOC,'beast'),
        type_sleep=lambda c:types(c,'MEND_040','murloc'),fill=lambda c:(Summon(c.player_id,YETI),)*4,
        extra=lambda c:(QueueTurns((c.player_id,),c.source_id),),skip=lambda c:(SkipTurns(3-c.player_id,source_id=c.source_id),),
        fail=lambda c:(AddToHand(c.player_id,'k65.missing',c.source_id),))
    for name,body in bodies.items():
        r.register_behavior('k65.'+name,body)
        if name!='fail':r.register_card(CardDefinition('k65.'+name,name,CardType.SPELL,on_play='k65.'+name,
            requires_target=name in ('silence','kill','bounce','give','copy')))
    r.register_card(CardDefinition('k65.zero','Zero Murloc',CardType.MINION,attack=1,health=2,
        metadata=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=('murloc',))))
    def wait(c,kind):
        entity=c.state.entities.get(c.event.source_id)
        if entity is None or entity.card_id!=MURLOC:return()
        if kind=='seen'and Keyword.DIVINE_SHIELD not in entity.keywords:
            raise AssertionError('First accepted summon notification omitted the original paid keyword')
        return(RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',(GainArmor(c.state.players[c.player_id].hero_id,1),)),
            ChoiceOption('bad','Fail',(InvokeBehavior('k65.fail',c.source_id,c.player_id),))),source_id=c.source_id),)
    for name,event in [('entry','minion_counter_check'),('seen','minion_summoned')]:
        r.register_behavior('k65.wait_'+name,lambda c,name=name:wait(c,name))
        r.register_card(CardDefinition('k65.wait_'+name,name,CardType.MINION,health=5,
            triggers=(TriggerSpec(event,'k65.wait_'+name),)))
    r.register_behavior('k65.counter',lambda c:(CounterMinion(dict(c.event.data)['window_id']),)
        if c.state.entities[c.event.source_id].card_id==MURLOC else())
    r.register_card(CardDefinition('k65.counter','Counter fixture',CardType.MINION,health=5,
        triggers=(TriggerSpec('minion_counter_check','k65.counter'),)))
    return r


class NextPlayPriceCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy_hand=(),enemy=(),deck=(YETI,)*12,power=False):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*12,mana=30,max_mana=30,mana_cap=30,
                hero_power_card_id='HERO_08bp'if power else None)),seed=1065),self.r)
    def entity(self,g,cid,p=1,zone='board'):
        s=g.state;return next(s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def play(self,g,cid,target=None,p=1):
        eid=self.entity(g,cid,p,'hand').id;g.apply(PlayCard(p,eid,target));return eid
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def prime(self,g):self.play(g,PRIMER);self.cycle(g)
    def price(self,g,cid,p=1):return quote_cost(g.state,g.registry,self.entity(g,cid,p,'hand')).amount
    def portable(self,g):
        s=g.snapshot();self.assertEqual(Game.from_snapshot(s,registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
    def qualified(self,extra=(),board=(),enemy=()):
        g=self.game((PRIMER,GLIDER,MURLOC,*extra),board,enemy=enemy);self.prime(g);self.play(g,GLIDER);return g
    def test_complete_three_faces_and_current_one_mana_reduction(self):
        d=load_batch();self.assertEqual([x['record']['id']for x in d['cards']],[GLIDER,SLOW,TAR])
        for row in d['cards']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertIn('(1)',d['cards'][0]['record']['text_en'])
        self.assertIsNone(self.r.card(TAR).spell_school);self.assertIsNone(self.r.card(SLOW).spell_school)
    def test_glider_unqualified_still_discounts_without_divine_shield(self):
        g=self.game((GLIDER,MURLOC));self.play(g,GLIDER);before=g.state.players[1].mana;eid=self.play(g,MURLOC)
        self.assertEqual(g.state.players[1].mana,before-1);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords)
    def test_qualified_glider_binds_discount_and_keyword_to_same_paid_minion(self):
        g=self.qualified();before=g.state.players[1].mana;eid=self.play(g,MURLOC)
        self.assertEqual(g.state.players[1].mana,before-1);self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords)
        self.assertFalse(g.state.players[1].cost_modifiers);self.portable(g)
    def test_discount_does_not_apply_to_non_murloc_or_opponent(self):
        g=self.game((GLIDER,YETI),enemy_hand=(MURLOC,));self.play(g,GLIDER)
        self.assertEqual(self.price(g,YETI),4);self.assertEqual(self.price(g,MURLOC,2),2)
        self.play(g,YETI);self.assertEqual(len(g.state.players[1].cost_modifiers),1)
    def test_zero_cost_matching_minion_consumes_and_receives_keyword(self):
        g=self.qualified(('k65.zero',));before=g.state.players[1].mana;eid=self.play(g,'k65.zero')
        self.assertEqual(g.state.players[1].mana,before);self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords)
        self.assertFalse(g.state.players[1].cost_modifiers);self.assertEqual(self.price(g,MURLOC),2);self.portable(g)
    def test_source_silence_does_not_revoke_pending_price_or_keyword(self):
        g=self.qualified(('k65.silence',));self.play(g,'k65.silence',self.entity(g,GLIDER).id)
        eid=self.play(g,MURLOC);self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords)
    def test_source_death_does_not_revoke_pending_price_or_keyword(self):
        g=self.qualified(('k65.kill',));self.play(g,'k65.kill',self.entity(g,GLIDER).id)
        eid=self.play(g,MURLOC);self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords);self.portable(g)
    def test_source_control_change_does_not_transfer_pending_price(self):
        g=self.qualified(('k65.give',));self.play(g,'k65.give',self.entity(g,GLIDER).id)
        eid=self.play(g,MURLOC);self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords)
    def test_pending_price_survives_ordinary_turn_boundary(self):
        g=self.qualified();self.cycle(g);eid=self.play(g,MURLOC)
        self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords);self.portable(g)
    def test_current_hand_tribe_qualifies_both_price_and_keyword(self):
        g=self.qualified((YETI,'k65.type_yeti'));self.play(g,'k65.type_yeti');self.assertEqual(self.price(g,YETI),3)
        eid=self.play(g,YETI);self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords);self.portable(g)
    def test_removed_murloc_tribe_does_not_consume_either_part(self):
        g=self.qualified(('k65.type_murloc',PRIMER));self.play(g,'k65.type_murloc');self.assertEqual(self.price(g,MURLOC),2)
        eid=self.play(g,MURLOC);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords)
        self.assertEqual(len(g.state.players[1].cost_modifiers),1);eid=self.play(g,PRIMER)
        self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords)
    def test_real_all_tribe_minion_qualifies_and_current_copy_inherits_keyword(self):
        g=self.qualified(('DINO_435',));self.assertEqual(self.price(g,'DINO_435'),4);self.play(g,'DINO_435')
        copies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id=='DINO_435']
        self.assertEqual(len(copies),2);self.assertTrue(all(Keyword.DIVINE_SHIELD in e.keywords for e in copies));self.portable(g)
    def test_effect_summon_does_not_consume_or_receive_pending_keyword(self):
        g=self.qualified(('k65.summon',));self.play(g,'k65.summon')
        self.assertNotIn(Keyword.DIVINE_SHIELD,self.entity(g,MURLOC).keywords)
        self.assertEqual(len(g.state.players[1].cost_modifiers),1)
    def test_dormant_paid_recipient_keeps_keyword_until_actual_awaken(self):
        g=self.qualified(('MEND_040','k65.type_sleep','k65.fill'));self.play(g,'k65.type_sleep');eid=self.play(g,'MEND_040')
        self.assertIsNotNone(g.state.entities[eid].dormancy)
        self.assertTrue(any(a.keyword==Keyword.DIVINE_SHIELD and not a.consumed for a in g.state.entities[eid].abilities))
        self.play(g,'k65.fill');self.assertIsNone(g.state.entities[eid].dormancy)
        self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords);self.portable(g)
    def test_source_replay_can_consume_previous_reward_and_create_new_one(self):
        g=self.qualified(('k65.bounce',));source=self.entity(g,GLIDER).id;self.play(g,'k65.bounce',source)
        self.play(g,GLIDER);self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords)
        self.assertEqual(len(g.state.players[1].cost_modifiers),1);self.assertEqual(self.price(g,MURLOC),1)
    def test_real_repeated_battlecry_stacks_prices_but_not_shield_charges(self):
        g=self.qualified(board=('TIME_064',));self.assertEqual(self.price(g,MURLOC),0);eid=self.play(g,MURLOC)
        self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords)
        self.play(g,ROCK,eid);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords)
        self.assertEqual(g.state.entities[eid].health,3);self.portable(g)
    def test_countered_paid_minion_consumes_price_without_installing_keyword(self):
        g=self.qualified(enemy=('k65.counter',));eid=self.play(g,MURLOC)
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertFalse(any(a.keyword==Keyword.DIVINE_SHIELD for a in g.state.entities[eid].abilities));self.portable(g)
    def test_pending_paid_entry_restores_original_keyword_and_does_not_repay(self):
        g=self.qualified(board=('k65.wait_entry',));eid=self.play(g,MURLOC);before=g.state.players[1].mana
        self.assertEqual(g.state.entities[eid].zone,Zone.PLAY);self.portable(g);saved=g.snapshot();choice=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,choice.id,('bad',)))
        self.assertEqual(g.snapshot(),saved);g.apply(SelectChoice(1,choice.id,('ok',)))
        self.assertEqual(g.state.players[1].mana,before);self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords);self.portable(g)
    def test_first_summon_notification_already_contains_paid_keyword(self):
        g=self.qualified(board=('k65.wait_seen',));eid=self.play(g,MURLOC)
        self.assertIsNotNone(g.state.pending_choice);self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords);self.portable(g)
        g.apply(SelectChoice(1,g.state.pending_choice.id,('ok',)));self.portable(g)
    def test_snapshot_cannot_change_consumed_keyword_to_another_keyword(self):
        g=self.qualified(board=('k65.wait_entry',));self.play(g,MURLOC);bad=g.snapshot()
        bad['state']['cost_use_history'][-1]['player_modifiers'][0]['minion_keyword']='taunt'
        bad['state_hash']=canonical_hash(bad['state'])
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
    def test_snapshot_requires_explicit_nullable_cost_reward_field(self):
        g=self.qualified();bad=g.snapshot();bad['state']['players']['1']['cost_modifiers'][0].pop('minion_keyword')
        bad['state_hash']=canonical_hash(bad['state'])
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
    def test_finite_cost_reward_rejects_unreviewed_shapes(self):
        base=dict(player_id=1,spec=CostSpec(delta=-1,card_types=(CardType.MINION,)),uses_remaining=1,
            source_id=1,tribes_any=('murloc',),minion_keyword=Keyword.DIVINE_SHIELD)
        for changes in [dict(uses_remaining=None),dict(source_id=None),dict(tribes_any=()),dict(minion_keyword=Keyword.TAUNT),
                dict(spec=CostSpec(delta=-1,card_types=(CardType.SPELL,)))]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):AddCostModifier(**dict(base,**changes))
    def test_slow_motion_arms_without_changing_current_cost(self):
        g=self.game((SLOW,),enemy_hand=(YETI,ROCK));self.play(g,SLOW)
        self.assertEqual((self.price(g,YETI,2),self.price(g,ROCK,2)),(4,1));self.assertEqual(len(g.state.players[2].player_effects),1)
        self.portable(g)
    def test_slow_motion_taxes_opponent_cards_for_only_next_actual_turn(self):
        g=self.game((SLOW,),enemy_hand=(YETI,ROCK));self.play(g,SLOW);g.apply(EndTurn(1))
        self.assertEqual((self.price(g,YETI,2),self.price(g,ROCK,2)),(5,2))
        before=g.state.players[2].mana;self.play(g,ROCK,g.state.players[1].hero_id,p=2)
        self.assertEqual(g.state.players[2].mana,before-2);g.apply(EndTurn(2));self.assertEqual(self.price(g,YETI,2),4);self.portable(g)
    def test_slow_motion_does_not_tax_hero_power(self):
        g=self.game((SLOW,),power=True);self.play(g,SLOW);g.apply(EndTurn(1));before=g.state.players[2].mana
        g.apply(UseHeroPower(2,g.state.players[2].hero_power_id,g.state.players[1].hero_id))
        self.assertEqual(g.state.players[2].mana,before-2)
    def test_two_slow_motion_sources_stack_and_expire_together(self):
        g=self.game((SLOW,SLOW),enemy_hand=(YETI,));self.play(g,SLOW);self.play(g,SLOW);g.apply(EndTurn(1))
        self.assertEqual(self.price(g,YETI,2),6);g.apply(EndTurn(2));self.assertEqual(self.price(g,YETI,2),4)
    def test_extra_turn_for_caster_does_not_activate_opponent_tax(self):
        g=self.game((SLOW,'k65.extra'),enemy_hand=(YETI,));self.play(g,SLOW);self.play(g,'k65.extra');g.apply(EndTurn(1))
        self.assertEqual(g.state.active_player,1);self.assertEqual(self.price(g,YETI,2),4)
        g.apply(EndTurn(1));self.assertEqual(g.state.active_player,2);self.assertEqual(self.price(g,YETI,2),5);self.portable(g)
    def test_skipped_opponent_slot_keeps_tax_for_next_real_start(self):
        g=self.game((SLOW,'k65.skip'),enemy_hand=(YETI,));self.play(g,SLOW);self.play(g,'k65.skip');g.apply(EndTurn(1))
        self.assertEqual(g.state.active_player,1);self.assertEqual(self.price(g,YETI,2),4)
        g.apply(EndTurn(1));self.assertEqual(g.state.active_player,2);self.assertEqual(self.price(g,YETI,2),5);self.portable(g)
    def test_wave_of_tar_damages_only_enemy_minions_then_arms_tax(self):
        g=self.game((TAR,),board=(YETI,),enemy=(YETI,),enemy_hand=(YETI,ROCK));self.play(g,TAR)
        self.assertEqual(self.entity(g,YETI).health,5);self.assertEqual(self.entity(g,YETI,2).health,3)
        self.assertEqual(self.price(g,YETI,2),4);g.apply(EndTurn(1))
        self.assertEqual((self.price(g,YETI,2),self.price(g,ROCK,2)),(6,1));self.portable(g)
    def test_tar_spell_damage_uses_shared_spell_layer(self):
        g=self.game((TAR,),board=('CORE_EX1_012',),enemy=(YETI,));self.play(g,TAR)
        self.assertEqual(self.entity(g,YETI,2).health,2)
    def test_tar_still_arms_when_enemy_board_is_empty(self):
        g=self.game((TAR,),enemy_hand=(YETI,));self.play(g,TAR);g.apply(EndTurn(1));self.assertEqual(self.price(g,YETI,2),6)
    def test_tar_and_slow_motion_keep_independent_type_filters(self):
        g=self.game((TAR,SLOW),enemy_hand=(YETI,ROCK));self.play(g,TAR);self.play(g,SLOW);g.apply(EndTurn(1))
        self.assertEqual((self.price(g,YETI,2),self.price(g,ROCK,2)),(7,2));g.apply(EndTurn(2))
        self.assertEqual((self.price(g,YETI,2),self.price(g,ROCK,2)),(4,1));self.portable(g)
    def test_pending_and_active_tax_snapshots_keep_original_scope(self):
        g=self.game((SLOW,TAR),enemy_hand=(YETI,));self.play(g,SLOW);self.play(g,TAR);self.portable(g)
        g.apply(EndTurn(1));self.portable(g);g.apply(EndTurn(2));self.portable(g)
    def test_queries_do_not_consume_pending_price_keyword_or_tax(self):
        g=self.qualified((SLOW,));self.play(g,SLOW);before=g.snapshot()
        for p in (1,2):g.for_player(p).observe();g.for_player(p).legal_actions()
        self.assertEqual(g.snapshot(),before)


if __name__=='__main__':unittest.main()
