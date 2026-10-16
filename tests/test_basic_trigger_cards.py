"""Core play resources, actual cast/attack completions and physical recruit/aura use."""
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.basic_trigger_cards import load_batch
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,CastSpell,
    EndTurn,Game,Keyword,PlayCard,PlayerSetup,Rarity,Scenario,SelectChoice,SpellRepeatSpec,SpellSchool,TriggerSpec)
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Damage,DamageBatch,Destroy,Draw,
    GainArmor,Heal,InvokeBehavior,RequestChoice,Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,HealingKind,Zone
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import canonical_digest


def registry(mode=None):
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    r.register_card(CardDefinition('k20.big','Big',CardType.MINION,attack=2,health=12,metadata=meta))
    r.register_card(CardDefinition('k20.lethal','Lethal attacker',CardType.MINION,attack=20,health=12,metadata=meta))
    r.register_card(CardDefinition('k20.charger','Charge attacker',CardType.MINION,attack=2,health=8,
        keywords=(Keyword.CHARGE,),metadata=meta))
    r.register_card(CardDefinition('k20.repeat','Repeat provider',CardType.MINION,health=8,metadata=meta,
        spell_repeats=(SpellRepeatSpec(2,class_mode='any'),)))
    r.register_card(CardDefinition('k20.blade','Blade',CardType.WEAPON,attack=1,durability=3,metadata=meta))
    scripts={
        'holy':lambda c:(), 'noop':lambda c:(),
        'hit':lambda c:(Damage(c.target_id,3,c.source_id),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'heal':lambda c:(Heal(c.target_id,2,c.source_id,HealingKind.SPELL),),
        'wound':lambda c:(Damage(c.state.players[1].hero_id,3,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'control':lambda c:(ChangeControl(c.target_id,2),),
        'fail':lambda c:(AddToHand(c.player_id,'missing.k20'),),
        'driver':lambda c:(CastSpell(c.player_id,'k20.holy',c.source_id),),
        'recruit':lambda c:(SummonFromZone(c.player_id,zone=Zone.HAND,selection='first',
            source_id=c.source_id,cause=SummonCause.capture(c)),),
        'sweep':lambda c:(DamageBatch(tuple(Damage(eid,8,c.source_id,DamageKind.SPELL)
            for pid in (1,2) for eid in c.state.players[pid].board)),),
        'choice':lambda c:(RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue payload',(GainArmor(1,1),)),
            ChoiceOption('bad','Rollback',(InvokeBehavior('k20.fail',c.source_id,c.player_id),))),c.source_id),),
        'counter':lambda c:(SetSecret(2,'EX1_287'),),
    }
    for name,body in scripts.items():
        r.register_behavior('k20.'+name,body)
        if name=='fail':continue
        r.register_card(CardDefinition('k20.'+name,name,CardType.SPELL,on_play='k20.'+name,
            spell_school=SpellSchool.HOLY if name in ('holy','heal','sweep','choice') else None,
            requires_target=name in ('hit','kill','heal','silence','control'),metadata=meta))
    if mode:
        def watch(c):
            if c.event.player_id != (1 if mode=='medic' else 2):return ()
            entity=c.state.entities[c.event.source_id]
            if entity.card_id != ('BAR_878t' if mode=='medic' else 'CORE_DMF_067'):return ()
            return (RequestChoice(1,(
                ChoiceOption('ok','Finish original summon',(GainArmor(1,1),)),
                ChoiceOption('bad','Rollback',(InvokeBehavior('k20.fail',c.source_id,1),))),c.source_id),)
        r.register_behavior('k20.watch',watch)
        r.register_card(CardDefinition('k20.watch','Observer',CardType.MINION,health=10,metadata=meta,
            triggers=(TriggerSpec('minion_summoned','k20.watch'),)))
    return r


class BasicTriggerCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),weapon=None,enemy_weapon=None,mode=None,
             deck=('k20.noop',)*8,enemy_deck=('k20.noop',)*8):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,weapon_card_id=weapon,
                mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=enemy_deck,weapon_card_id=enemy_weapon,
                mana=30,max_mana=30,mana_cap=30)),seed=283),registry(mode) if mode else self.registry)
    def play(self,g,cid,target=None,position=None):
        eid=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid)
        g.apply(PlayCard(1,eid,target,position));return eid
    def choose(self,g,option='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option,)))
    def body(self,g,cid,p=1):return next(g.state.entities[e] for e in g.state.players[p].board if g.state.entities[e].card_id==cid)
    def count(self,g,cid,p=1):return sum(g.state.entities[e].card_id==cid for e in g.state.players[p].board)
    def portable(self,g,mode=None):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(mode))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved);return other

    def test_nine_complete_records_actual_entry_points_and_medic_dbf_link(self):
        data=load_batch();self.assertEqual(len(data['cards']),9)
        for row in data['cards']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            card=self.registry.card(row['record']['id'])
            self.assertEqual((card.cost,card.attack,card.health),(row['record']['cost'],row['record']['attack'],row['record']['health']))
        self.assertEqual(data['dependency_link']['dbf_id'],63321)
        self.assertIsNone(self.registry.card('CORE_AT_052').battlecry)
        self.assertIsNotNone(self.registry.card('CORE_AT_052').on_play)
        self.assertIn(Keyword.LIFESTEAL,self.registry.card('BAR_878t').keywords)

    def test_totem_manual_overload_once_no_battlecry_and_next_owner_lock(self):
        g=self.game(('CORE_AT_052',));self.play(g,'CORE_AT_052')
        self.assertEqual(g.state.players[1].overload_owed,1);self.assertFalse(g.state.battlecry_history)
        self.assertEqual(len(g.state.overload_history),1)
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual((g.state.players[1].overload_locked,g.state.players[1].overload_owed,g.state.players[1].mana),(1,0,29))
        self.portable(g)

    def test_totem_physical_recruit_does_not_execute_on_play_resource(self):
        g=self.game(('k20.recruit','CORE_AT_052'));self.play(g,'k20.recruit')
        self.assertEqual(self.count(g,'CORE_AT_052'),1)
        self.assertEqual(g.state.players[1].overload_owed,0);self.assertFalse(g.state.overload_history)

    def test_anshe_requires_actual_positive_restoration_not_full_health_attempt(self):
        g=self.game(('k20.heal','CORE_BAR_313'));self.play(g,'k20.heal',g.state.players[1].hero_id)
        self.play(g,'CORE_BAR_313');self.assertEqual(self.body(g,'CORE_BAR_313').attack,5)
        g=self.game(('k20.wound','k20.heal','CORE_BAR_313'))
        self.play(g,'k20.wound');self.play(g,'k20.heal',g.state.players[1].hero_id);self.play(g,'CORE_BAR_313')
        self.assertEqual((self.body(g,'CORE_BAR_313').attack,self.body(g,'CORE_BAR_313').health),(8,8))

    def test_anshe_restoring_enemy_minion_counts_for_source_and_previous_turn_expires(self):
        g=self.game(('k20.hit','k20.heal','CORE_BAR_313'),enemy=('k20.big',))
        target=self.body(g,'k20.big',2).id
        self.play(g,'k20.hit',target);self.play(g,'k20.heal',target);self.play(g,'CORE_BAR_313')
        self.assertEqual(self.body(g,'CORE_BAR_313').attack,8)
        g=self.game(('k20.wound','k20.heal','CORE_BAR_313'));self.play(g,'k20.wound')
        self.play(g,'k20.heal',g.state.players[1].hero_id);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.play(g,'CORE_BAR_313');self.assertEqual(self.body(g,'CORE_BAR_313').attack,5)

    def test_veteran_holy_manual_completion_not_other_spells_and_real_token(self):
        g=self.game(('k20.holy','k20.noop'),board=('CORE_BAR_878',))
        self.play(g,'k20.noop');self.assertEqual(self.count(g,'BAR_878t'),0)
        self.play(g,'k20.holy');token=self.body(g,'BAR_878t')
        self.assertEqual((token.attack,token.health),(2,2));self.assertIn(Keyword.LIFESTEAL,token.keywords)
        cause=g.state.card_summon_history[-1].request.cause
        self.assertEqual((cause.origin,cause.cast_id,cause.source.card_id),('card_effect',None,'CORE_BAR_878'))
        self.assertEqual(len([e for e in g.events if e.kind=='spell_cast_finished']),2);self.portable(g)

    def test_veteran_ignores_automatic_holy_and_counts_repeated_personal_play_once(self):
        g=self.game(('k20.driver',),board=('CORE_BAR_878',));self.play(g,'k20.driver')
        self.assertEqual(self.count(g,'BAR_878t'),0)
        self.assertEqual([r.origin for r in g.state.cast_history],['hand','effect'])
        g=self.game(('k20.holy',),board=('CORE_BAR_878','k20.repeat'));self.play(g,'k20.holy')
        self.assertEqual(self.count(g,'BAR_878t'),1)
        self.assertEqual([r.origin for r in g.state.cast_history],['hand','repeat'])
        self.assertEqual(len([e for e in g.events if e.kind=='spell_cast_finished']),2)
        self.assertEqual(len([e for e in g.events if e.kind=='card_played']),1);self.portable(g)

    def test_veteran_after_payload_not_before_sweep_and_full_board_skip(self):
        g=self.game(('k20.sweep',),board=('CORE_BAR_878',));self.play(g,'k20.sweep')
        self.assertFalse(g.state.players[1].board)
        g=self.game(('k20.holy',),board=('CORE_BAR_878',)+('k20.big',)*6)
        self.play(g,'k20.holy');self.assertEqual(self.count(g,'BAR_878t'),0)

    def test_veteran_countered_holy_has_no_payload_completion(self):
        g=self.game(('k20.counter','k20.holy'),board=('CORE_BAR_878',));self.play(g,'k20.counter')
        self.play(g,'k20.holy');self.assertEqual(self.count(g,'BAR_878t'),0)
        self.assertFalse(g.state.cast_history[-1].payload_started)
        self.assertEqual(len([e for e in g.events if e.kind=='spell_cast_finished']),1)

    def test_veteran_payload_waiting_then_after_cast_summon_waiting_is_portable(self):
        g=self.game(('k20.choice',),board=('CORE_BAR_878','k20.watch'),mode='medic')
        self.play(g,'k20.choice');self.assertEqual(self.count(g,'BAR_878t'),0)
        self.assertFalse(g.state.cast_history[0].completed)
        other=self.portable(g,'medic')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.count(g,'BAR_878t'),1)
        self.assertIsNotNone(g.state.pending_choice);self.assertTrue(g.state.cast_history[0].completed)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g,'medic')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertTrue(g.state.play_history[0].completed)

    def test_hero_attack_buffs_battlefiend_and_surviving_wrathspike_hits_all_enemies(self):
        g=self.game(board=('CORE_BT_351','k20.big'),enemy=('CORE_BT_510',),weapon='k20.blade')
        g.apply(Attack(1,g.state.players[1].hero_id,self.body(g,'CORE_BT_510',2).id))
        self.assertEqual((self.body(g,'CORE_BT_351').attack,self.body(g,'CORE_BT_351').health),(2,1))
        self.assertEqual(self.body(g,'k20.big').health,11)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,26)
        self.assertEqual(self.body(g,'CORE_BT_510',2).health,5);self.portable(g)

    def test_battlefiend_does_not_count_friendly_minion_or_opponent_hero_attacks(self):
        g=self.game(('k20.charger',),board=('CORE_BT_351',));eid=self.play(g,'k20.charger')
        g.apply(Attack(1,eid,g.state.players[2].hero_id));self.assertEqual(self.body(g,'CORE_BT_351').attack,1)
        g=self.game(board=('CORE_BT_351',),enemy_weapon='k20.blade');g.apply(EndTurn(1))
        g.apply(Attack(2,g.state.players[2].hero_id,g.state.players[1].hero_id))
        self.assertEqual(self.body(g,'CORE_BT_351').attack,1)

    def test_wrathspike_own_attack_not_ping_and_lethal_defense_still_pings(self):
        g=self.game(board=('CORE_BT_510',));g.apply(Attack(1,self.body(g,'CORE_BT_510').id,g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27)
        self.assertFalse([r for r in g.state.damage_history if r.health_result.damage_kind=='minion_ability'])
        g=self.game(board=('k20.lethal',),enemy=('CORE_BT_510',))
        g.apply(Attack(1,self.body(g,'k20.lethal').id,self.body(g,'CORE_BT_510',2).id))
        self.assertEqual(self.body(g,'k20.lethal').health,8)

    def test_dirty_rat_physical_enemy_hand_recruit_no_battlecry_then_real_deathrattle(self):
        g=self.game(('CORE_CFM_790','k20.kill'),enemy_hand=('CORE_DMF_067',))
        original=g.state.players[2].hand[0];self.play(g,'CORE_CFM_790')
        self.assertEqual(self.body(g,'CORE_DMF_067',2).id,original);self.assertFalse(g.state.draw_history)
        self.play(g,'k20.kill',original);self.assertEqual([r.player_id for r in g.state.draw_history],[2,1])
        self.portable(g)

    def test_dirty_rat_no_minion_and_full_enemy_board_leave_hand_untouched(self):
        for hand,board in ((('k20.noop',),()),(('CORE_DMF_067',),('k20.big',)*7)):
            g=self.game(('CORE_CFM_790',),enemy_hand=hand,enemy=board)
            ids=list(g.state.players[2].hand);self.play(g,'CORE_CFM_790')
            self.assertEqual(g.state.players[2].hand,ids)

    def test_dirty_rat_recruit_waiting_cause_recipient_restore_and_private_hand(self):
        g=self.game(('CORE_CFM_790',),enemy_hand=('CORE_DMF_067','k20.noop'),board=('k20.watch',),mode='rat')
        self.play(g,'CORE_CFM_790');self.assertIsNotNone(g.state.pending_choice)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g,'rat')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot())
        public=json.dumps(g.observe(1))+json.dumps(g.player_events(1))
        self.assertNotIn('RecruitEntryMaterial',public);self.assertNotIn('k20.noop',json.dumps(g.observe(1)['players'][1]['hand']))

    def test_vendor_distinct_battlecry_and_deathrattle_each_player_draw_order(self):
        g=self.game(('CORE_DMF_067','k20.kill'));eid=self.play(g,'CORE_DMF_067')
        self.assertEqual([r.player_id for r in g.state.draw_history],[1,2])
        self.play(g,'k20.kill',eid);self.assertEqual([r.player_id for r in g.state.draw_history],[1,2,1,2])

    def test_vendor_empty_decks_use_independent_fatigue(self):
        g=self.game(('CORE_DMF_067',),deck=(),enemy_deck=());self.play(g,'CORE_DMF_067')
        self.assertEqual([r.outcome for r in g.state.draw_history],['fatigue','fatigue'])
        self.assertEqual([g.state.entities[g.state.players[p].hero_id].health for p in (1,2)],[29,29])

    def test_wolf_adjacency_reflows_on_insertion_and_silence(self):
        g=self.game(('k20.charger','k20.silence'),board=('k20.big','CORE_EX1_162','CORE_CS2_182'))
        big=self.body(g,'k20.big').id;wolf=self.body(g,'CORE_EX1_162').id;yeti=self.body(g,'CORE_CS2_182').id
        self.assertEqual((g.state.entities[big].attack,g.state.entities[yeti].attack),(3,5))
        new=self.play(g,'k20.charger',position=1)
        self.assertEqual((g.state.entities[big].attack,g.state.entities[new].attack,g.state.entities[yeti].attack),(2,3,5))
        self.play(g,'k20.silence',wolf)
        self.assertEqual((g.state.entities[new].attack,g.state.entities[yeti].attack),(2,4));self.portable(g)

    def test_wolf_change_control_reassigns_aura_to_its_new_neighbors(self):
        g=self.game(('k20.control',),board=('k20.big','CORE_EX1_162'),enemy=('CORE_CS2_182',))
        self.play(g,'k20.control',self.body(g,'CORE_EX1_162').id)
        self.assertEqual(self.body(g,'k20.big').attack,2)
        self.assertEqual(self.body(g,'CORE_CS2_182',2).attack,5)
