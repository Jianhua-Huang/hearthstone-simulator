"""Native ending scopes, fixed tokens and accepted/current source-stat summons."""
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.native_end_cards import load_batch
from hs_sim.engine import (CardDefinition,CardType,EndTurn,EndTurnSpec,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,TriggerSpec)
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,Damage,Destroy,GainArmor,InvokeBehavior,
    RequestChoice,Silence)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import DamageKind,SummonStats,Zone
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.source_stat_summons import SummonBySourceStats
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import canonical_digest


def registry(mode=None):
    r=build_registry()
    scripts={
        'hit':lambda c:(Damage(c.target_id,1,c.source_id),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'buff':lambda c:(Buff(c.target_id,2,4,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'wound':lambda c:tuple(Damage(c.state.players[p].hero_id,5,c.source_id) for p in (1,2)),
        'fail':lambda c:(AddToHand(c.player_id,'missing.k19'),),
    }
    for name,body in scripts.items():
        r.register_behavior('k19.'+name,body)
        if name=='fail':continue
        r.register_card(CardDefinition('k19.'+name,name,CardType.SPELL,on_play='k19.'+name,
                                      requires_target=name!='wound'))
    def earlier(c):
        target=next(eid for eid in c.state.players[1].board if c.state.entities[eid].card_id=='CATA_478')
        return (Damage(target,3,c.source_id,DamageKind.MINION_ABILITY),)
    r.register_behavior('k19.earlier',earlier)
    r.register_card(CardDefinition('k19.earlier','Earlier native damage',CardType.MINION,health=5,
        triggers=(TriggerSpec('turn_ended','k19.earlier',EndTurnSpec()),)))
    if mode=='source':
        def accepted(c):
            request=SummonBySourceStats(c.player_id,'CATA_478t',MinionReference.capture(c.source),
                SummonStats(c.source.attack,c.source.health),SummonCause.capture(c))
            return (RequestChoice(c.player_id,(
                ChoiceOption('grow','Change original source now',(Buff(c.source_id,2,3,c.source_id),)),
                ChoiceOption('kill','Remove original source',(Destroy(c.source_id,c.source_id),)),
                ChoiceOption('bad','Rollback',(InvokeBehavior('k19.fail',c.source_id,c.player_id),)),
            ),c.source_id),request)
        r.register_behavior('k19.accepted',accepted)
        r.register_card(CardDefinition('k19.accepted','Accepted source-stat producer',CardType.MINION,
            attack=3,health=5,triggers=(TriggerSpec('turn_ended','k19.accepted',EndTurnSpec()),)))
    if mode=='death':
        def watch(c):
            if c.state.entities[c.event.target_id].card_id!='CATA_478':return ()
            return (RequestChoice(1,(
                ChoiceOption('ok','Continue original ending',(GainArmor(1,1),)),
                ChoiceOption('bad','Rollback',(InvokeBehavior('k19.fail',c.source_id,1),)),
            ),c.source_id),)
        r.register_behavior('k19.watch',watch)
        r.register_card(CardDefinition('k19.watch','Death observer',CardType.MINION,health=8,
            triggers=(TriggerSpec('minion_died','k19.watch'),)))
    r.register_card(replace(r.card('CATA_999'),id='k19.sleep',dormant_turns=2))
    return r


class NativeEndCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),enemy=(),mode=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=('CORE_CS2_182',)*8,
                mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',board=enemy,deck=('CORE_CS2_182',)*8,
                mana=30,max_mana=30,mana_cap=30)),seed=271),registry(mode) if mode else self.registry)
    def play(self,g,cid,target=None):
        eid=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid)
        g.apply(PlayCard(1,eid,target));return eid
    def end(self,g,p=None):g.apply(EndTurn(g.state.active_player if p is None else p))
    def choose(self,g,option='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option,)))
    def portable(self,g,mode=None):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(mode))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved);return other
    def body(self,g,cid,p=1):return next(g.state.entities[e] for e in g.state.players[p].board if g.state.entities[e].card_id==cid)
    def hero(self,g,p):return g.state.entities[g.state.players[p].hero_id]

    def test_full_fourteen_records_existing_token_and_native_scope_keywords(self):
        data=load_batch();self.assertEqual(len(data['cards']),16);self.assertEqual(len(data['existing_dependencies']),1)
        for row in (*data['cards'],*data['existing_dependencies']):
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            card=self.registry.card(row['record']['id']);raw=row['record']
            self.assertEqual((card.cost,card.attack,card.health),(raw['cost'],raw['attack'],raw['health']))
            if 'recipe' in row and row['recipe']['script'] not in (None,'cannonmaster'):
                self.assertEqual(card.triggers[0].end_turn.turn_scope,row['recipe']['turn_scope'])
        self.assertEqual(self.registry.card('CATA_476t').metadata.tribes,('dragon','elemental'))
        self.assertIn(Keyword.ELUSIVE,self.registry.card('CATA_133').keywords)
        self.assertIn(Keyword.DIVINE_SHIELD,self.registry.card('CATA_476t').keywords)
        self.assertNotIn(Keyword.REBORN,self.registry.card('JAIL_883').keywords)

    def test_cannonmaster_actual_battlecry_gets_existing_cannon_then_native_shot(self):
        g=self.game(('CAP_107',));self.play(g,'CAP_107')
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].hand],['CAP_107t'])
        self.play(g,'CAP_107t');self.end(g)
        self.assertEqual(self.hero(g,2).health,29);self.portable(g)

    def test_flitterwing_and_mosquito_buff_other_current_friendly_bodies_in_order(self):
        g=self.game(board=('CATA_133','EDR_816','CORE_CS2_182'));self.end(g)
        self.assertEqual([(self.body(g,cid).attack,self.body(g,cid).health)
            for cid in ('CATA_133','EDR_816','CORE_CS2_182')],[(5,5),(2,3),(6,6)])
        before=[(g.state.entities[e].attack,g.state.entities[e].health) for e in g.state.players[1].board]
        self.end(g)
        self.assertEqual([(g.state.entities[e].attack,g.state.entities[e].health) for e in g.state.players[1].board],before)

    def test_matriarch_current_full_health_gate_and_wounded_no_growth(self):
        g=self.game(board=('CATA_305',));self.end(g);self.assertEqual(self.body(g,'CATA_305').health,6)
        g=self.game(('k19.hit',),board=('CATA_305',));self.play(g,'k19.hit',self.body(g,'CATA_305').id)
        self.end(g);self.assertEqual((self.body(g,'CATA_305').health,self.body(g,'CATA_305').max_health),(2,3))

    def test_matriarch_and_redeemer_observe_earlier_end_buff_current_remaining_health(self):
        g=self.game(('k19.hit',),board=('CATA_133','CATA_478','CATA_305'))
        self.play(g,'k19.hit',self.body(g,'CATA_478').id);self.end(g)
        token=self.body(g,'CATA_478t')
        self.assertEqual((token.attack,token.health,token.max_health),(4,3,3))
        self.assertEqual((self.body(g,'CATA_305').health,self.body(g,'CATA_305').max_health),(7,7))

    def test_bulwark_enemy_batch_no_extra_spell_damage_shield_and_enemy_hero(self):
        g=self.game(board=('CATA_475','CORE_EX1_012'),enemy=('CORE_CS2_182','CORE_EX1_008'))
        self.end(g);self.assertEqual(self.hero(g,2).health,28)
        self.assertEqual(self.body(g,'CORE_CS2_182',2).health,3)
        self.assertEqual(self.body(g,'CORE_EX1_008',2).health,1)
        rows=[r.health_result for r in g.state.damage_history if r.health_result.source_card_id=='CATA_475']
        self.assertEqual(len({r.batch_id for r in rows}),1);self.assertTrue(all(r.spell_bonus==0 for r in rows))

    def test_keeper_complete_fixed_elemental_dragon_shield_and_full_board(self):
        g=self.game(board=('CATA_476',));self.end(g)
        token=self.body(g,'CATA_476t');self.assertEqual((token.attack,token.health),(6,6))
        self.assertIn(Keyword.DIVINE_SHIELD,token.keywords);self.portable(g)
        g=self.game(board=('CATA_476',)+('CORE_CS2_182',)*6);self.end(g)
        self.assertEqual(len(g.state.players[1].board),7)
        self.assertFalse(any(g.state.entities[e].card_id=='CATA_476t' for e in g.state.players[1].board))

    def test_redeemer_copies_current_stats_not_other_abilities_and_full_board(self):
        g=self.game(('k19.buff','k19.hit'),board=('CATA_478',))
        source=self.body(g,'CATA_478').id;self.play(g,'k19.buff',source);self.play(g,'k19.hit',source)
        self.end(g);token=self.body(g,'CATA_478t')
        self.assertEqual((token.attack,token.health,token.max_health),(5,6,6));self.assertFalse(token.keywords)
        g=self.game(board=('CATA_478',)+('CORE_CS2_182',)*6);self.end(g)
        self.assertEqual(len(g.state.players[1].board),7)

    def test_drake_own_end_hero_damage_and_sleep_no_initial_body(self):
        g=self.game(board=('CATA_999',));self.end(g);self.assertEqual(self.hero(g,2).health,26)
        self.end(g);self.assertEqual(self.hero(g,2).health,26)
        g=self.game(board=('k19.sleep',));self.end(g);self.assertEqual(self.hero(g,2).health,30)

    def test_cumulus_gives_hero_shield_only_at_own_end(self):
        g=self.game(board=('EDR_942',));self.assertNotIn(Keyword.DIVINE_SHIELD,self.hero(g,1).keywords)
        self.end(g);self.assertIn(Keyword.DIVINE_SHIELD,self.hero(g,1).keywords)
        self.assertNotIn(Keyword.DIVINE_SHIELD,self.hero(g,2).keywords);self.portable(g)

    def test_caretaker_heals_both_heroes_in_one_minion_batch(self):
        g=self.game(('k19.wound',),board=('EDR_971',));self.play(g,'k19.wound');self.end(g)
        self.assertEqual((self.hero(g,1).health,self.hero(g,2).health),(28,28))
        rows=[r.health_result for r in g.state.healing_history if r.health_result.source_card_id=='EDR_971']
        self.assertEqual(len(rows),2);self.assertEqual(len({r.batch_id for r in rows}),1)

    def test_golem_each_player_end_reborn_consumed_then_gained_again(self):
        g=self.game(('k19.kill',),board=('JAIL_883',));old=self.body(g,'JAIL_883').id
        self.assertNotIn(Keyword.REBORN,self.body(g,'JAIL_883').keywords)
        self.end(g);self.assertIn(Keyword.REBORN,self.body(g,'JAIL_883').keywords)
        self.end(g);self.play(g,'k19.kill',old)
        new=self.body(g,'JAIL_883');self.assertNotEqual(new.id,old);self.assertEqual(new.health,1)
        self.assertNotIn(Keyword.REBORN,new.keywords)
        self.end(g);self.assertIn(Keyword.REBORN,self.body(g,'JAIL_883').keywords)

    def test_skipper_either_turn_coins_go_to_actual_ending_player(self):
        g=self.game(board=('TIME_054',));self.end(g)
        def coins(p):return sum(g.state.entities[e].card_id=='GAME_005' for e in g.state.players[p].hand)
        self.assertEqual((coins(1),coins(2)),(1,0));self.end(g)
        self.assertEqual((coins(1),coins(2)),(1,1));self.portable(g)

    def test_silence_removes_native_body_and_elusive_rejects_target(self):
        g=self.game(('k19.silence',),board=('CATA_999',));self.play(g,'k19.silence',self.body(g,'CATA_999').id)
        self.end(g);self.assertEqual(self.hero(g,2).health,30)
        g=self.game(('k19.hit',),board=('CATA_133',));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'k19.hit',self.body(g,'CATA_133').id)
        self.assertEqual(g.snapshot(),before)

    def test_accepted_redeemer_after_earlier_lethal_end_damage_uses_retained_basis(self):
        g=self.game(board=('k19.earlier','CATA_478'));self.end(g)
        self.assertEqual((self.body(g,'CATA_478t').attack,self.body(g,'CATA_478t').health),(3,3))
        self.assertEqual(g.state.death_history[0].card_id,'CATA_478');self.portable(g)

    def test_source_stat_waiting_exact_payload_fresh_growth_and_original_dead_fallback(self):
        for option,expected in (('grow',(5,8)),('kill',(3,5))):
            g=self.game(board=('k19.accepted',),mode='source');self.end(g)
            self.assertIsNotNone(g.state.pending_choice)
            self.assertIn('SummonBySourceStats',json.dumps(g.snapshot()))
            before=g.snapshot()
            with self.assertRaises(ResolutionError):self.choose(g,'bad')
            self.assertEqual(g.snapshot(),before);other=self.portable(g,'source')
            for current in (g,other):self.choose(current,option)
            self.assertEqual(g.snapshot(),other.snapshot())
            self.assertEqual((self.body(g,'CATA_478t').attack,self.body(g,'CATA_478t').health),expected)
            self.assertNotIn('accepted_stats',json.dumps(g.observe(2)))

    def test_actual_native_death_waiting_source_fallback_restore_clone_replay(self):
        g=self.game(board=('k19.earlier','CATA_478','k19.watch'),mode='death');self.end(g)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,'death')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.body(g,'CATA_478t').health,3)

    def test_source_stats_declared_complete_and_bound_to_original_cause(self):
        g=self.game(board=('CATA_478',));entity=self.body(g,'CATA_478')
        from hs_sim.engine.registry import RuleContext
        c=RuleContext(g.state,entity.id,1);cause=SummonCause.capture(c);ref=MinionReference.capture(entity)
        for factory in (lambda:SummonBySourceStats(1,'CATA_478t',ref,SummonStats(health=3),cause),
                        lambda:SummonBySourceStats(2,'CATA_478t',ref,SummonStats(3,3),cause)):
            with self.assertRaises(ValueError):factory()
