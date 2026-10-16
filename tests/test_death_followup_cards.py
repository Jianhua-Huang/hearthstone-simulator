"""Eight Deathrattle roots, exact reused/generated dependencies and zone lifetimes."""
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.death_followup_cards import load_batch
from hs_sim.engine import (CardDefinition,CardType,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,Destroy,Draw,GainArmor,
    InvokeBehavior,RequestChoice,TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import Zone
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest


def registry(mode=None):
    r=build_registry()
    scripts={
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'buff':lambda c:(Buff(c.target_id,3,4,c.source_id),),
        'weak':lambda c:(Buff(c.target_id,attack=-2,source_id=c.source_id),),
        'trigger':lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        'draw':lambda c:(Draw(c.player_id,source_id=c.source_id),),
        'control':lambda c:(ChangeControl(c.target_id,2),),
        'fail':lambda c:(AddToHand(c.player_id,'missing.k21'),),
    }
    for name,body in scripts.items():
        r.register_behavior('k21.'+name,body)
        if name=='fail':continue
        r.register_card(CardDefinition('k21.'+name,name,CardType.SPELL,on_play='k21.'+name,requires_target=name!='draw'))
    r.register_card(CardDefinition('k21.blade','Old blade',CardType.WEAPON,attack=1,durability=2))
    if mode:
        def watch(c):
            if mode=='split':
                if c.state.entities[c.event.source_id].card_id!='CORE_BT_201':return ()
                if c.state.entities[c.state.players[1].hero_id].armor:return ()
                good=(GainArmor(1,1),)
            else:
                expected='CORE_AT_123' if mode=='dragon' else 'EDR_890'
                if c.state.entities[c.event.target_id].card_id!=expected:return ()
                good=(Draw(1,source_id=c.source_id),)
            return (RequestChoice(1,(
                ChoiceOption('ok','Continue actual death body',good),
                ChoiceOption('bad','Rollback',(InvokeBehavior('k21.fail',c.source_id,1),))),c.source_id),)
        r.register_behavior('k21.watch',watch)
        r.register_card(CardDefinition('k21.watch','Observer',CardType.MINION,health=8,
            triggers=(TriggerSpec('random_choice' if mode=='split' else 'minion_died','k21.watch'),)))
    return r


class DeathFollowupCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=('CORE_CS2_182',)*6,
             mode=None,weapon=None,hero='HERO_08'):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=deck,weapon_card_id=weapon,
                mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=('CORE_CS2_182',)*6)),seed=293),
            registry(mode) if mode else self.registry)
    def play(self,g,cid,target=None):
        eid=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid)
        g.apply(PlayCard(1,eid,target));return eid
    def body(self,g,cid,p=1):return next(g.state.entities[e] for e in g.state.players[p].board if g.state.entities[e].card_id==cid)
    def price(self,g,eid):
        state=g.state;return quote_cost(state,g.registry,state.entities[eid]).amount
    def choose(self,g,option='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option,)))
    def portable(self,g,mode=None):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(mode))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved);return other
    def rows(self,g,cid):return [r.health_result for r in g.state.damage_history if r.health_result.source_card_id==cid]

    def test_full_nine_new_faces_one_reused_dependency_and_actual_dbf_references(self):
        data=load_batch();self.assertEqual(len(data['cards']),20);self.assertEqual(len(data['existing_dependencies']),2)
        self.assertEqual([link['dbf_id'] for link in data['dependency_links']],[564,1730])
        for row in (*data['cards'],*data['existing_dependencies']):
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(len([r for r in data['cards'] if r['recipe']['scope_role']=='standard_root_candidate']),18)
        tirion=self.registry.card('CORE_EX1_383');self.assertEqual((tirion.cost,tirion.attack,tirion.health),(8,8,8))
        sword=self.registry.card('EX1_383t');self.assertEqual((sword.attack,sword.durability),(5,3))

    def test_chillmaw_only_holding_dragon_all_minions_one_batch_no_spell_bonus(self):
        g=self.game(('k21.kill','EDR_890'),board=('CORE_AT_123','CORE_CS2_182','CORE_EX1_012'),enemy=('CORE_CS2_182',))
        self.play(g,'k21.kill',self.body(g,'CORE_AT_123').id)
        self.assertEqual((self.body(g,'CORE_CS2_182').health,self.body(g,'CORE_CS2_182',2).health),(2,2))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        rows=self.rows(g,'CORE_AT_123');self.assertEqual(len({r.batch_id for r in rows}),1)
        self.assertTrue(all(r.modified_amount==3 and r.spell_bonus==0 for r in rows))

    def test_chillmaw_no_dragon_source_itself_is_not_held(self):
        g=self.game(('k21.kill','CORE_CS2_182'),board=('CORE_AT_123',),enemy=('CORE_CS2_182',))
        self.play(g,'k21.kill',self.body(g,'CORE_AT_123').id)
        self.assertFalse(self.rows(g,'CORE_AT_123'));self.assertEqual(self.body(g,'CORE_CS2_182',2).health,5)

    def test_chillmaw_queries_after_real_death_reaction_draws_dragon(self):
        g=self.game(('k21.kill',),board=('CORE_AT_123','k21.watch'),enemy=('CORE_CS2_182',),
            deck=('EDR_890',),mode='dragon')
        self.play(g,'k21.kill',self.body(g,'CORE_AT_123').id);self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g,'dragon')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.body(g,'CORE_CS2_182',2).health,2)

    def test_living_chillmaw_trigger_damages_itself_without_fabricated_death(self):
        g=self.game(('k21.trigger','EDR_890'),board=('CORE_AT_123',),enemy=('CORE_CS2_182',))
        source=self.body(g,'CORE_AT_123').id;self.play(g,'k21.trigger',source)
        self.assertEqual(g.state.entities[source].health,3);self.assertFalse(g.state.death_history)

    def test_porcupine_freezes_actual_death_attack_whole_budget_and_ignores_spell_damage(self):
        g=self.game(('k21.buff','k21.kill'),board=('CORE_BT_201','CORE_EX1_012'))
        source=self.body(g,'CORE_BT_201').id;self.play(g,'k21.buff',source);self.play(g,'k21.kill',source)
        self.assertEqual(g.state.death_history[0].attack,5)
        self.assertEqual([r.damage_dealt for r in self.rows(g,'CORE_BT_201')],[1]*5)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25)

    def test_porcupine_living_trigger_uses_current_attack_and_zero_no_rng(self):
        g=self.game(('k21.trigger',),board=('CORE_BT_201',));source=self.body(g,'CORE_BT_201').id
        self.play(g,'k21.trigger',source);self.assertEqual(len(self.rows(g,'CORE_BT_201')),2)
        self.assertFalse(g.state.death_history);self.assertIn(source,g.state.players[1].board)
        g=self.game(('k21.weak','k21.kill'),board=('CORE_BT_201',));source=self.body(g,'CORE_BT_201').id
        self.play(g,'k21.weak',source);before=g.snapshot()['rng_state'];self.play(g,'k21.kill',source)
        self.assertFalse(self.rows(g,'CORE_BT_201'));self.assertEqual(g.snapshot()['rng_state'],before)

    def test_porcupine_split_waiting_bad_rollback_restore_clone_replay_and_projection(self):
        g=self.game(('k21.kill',),board=('CORE_BT_201','k21.watch'),mode='split')
        self.play(g,'k21.kill',self.body(g,'CORE_BT_201').id);self.assertIsNotNone(g.state.pending_choice)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g,'split')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.rows(g,'CORE_BT_201')),2)
        self.assertNotIn('rng_state',json.dumps(g.observe(2)))

    def test_spellwing_gets_exact_legacy_spell_and_reused_complete_spell_budget(self):
        g=self.game(('k21.kill',),board=('CORE_DRG_107','CORE_EX1_012'))
        self.play(g,'k21.kill',self.body(g,'CORE_DRG_107').id)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].hand],['EX1_277'])
        self.play(g,'EX1_277');self.assertEqual(len(self.rows(g,'EX1_277')),4)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,26);self.portable(g)

    def test_tirion_equips_exact_sword_replaces_old_weapon_and_uses_normal_attack(self):
        g=self.game(('k21.kill',),board=('CORE_EX1_383',),weapon='k21.blade')
        old=g.state.players[1].weapon_id;self.play(g,'k21.kill',self.body(g,'CORE_EX1_383').id)
        sword=g.state.entities[g.state.players[1].weapon_id]
        self.assertEqual((sword.card_id,sword.attack,sword.durability),('EX1_383t',5,3))
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack,5);self.portable(g)

    def test_rattler_enemy_minions_only_shield_and_no_spell_damage(self):
        g=self.game(('k21.kill',),board=('CORE_WC_701','CORE_EX1_012'),enemy=('CORE_CS2_182','CORE_EX1_008'))
        self.play(g,'k21.kill',self.body(g,'CORE_WC_701').id)
        self.assertEqual(self.body(g,'CORE_CS2_182',2).health,4)
        self.assertEqual(self.body(g,'CORE_EX1_008',2).health,1)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        self.assertEqual(self.body(g,'CORE_EX1_012').health,1)
        rows=self.rows(g,'CORE_WC_701');self.assertEqual(len({r.batch_id for r in rows}),1)

    def test_bear_death_imbues_actual_current_hunter_hero(self):
        g=self.game(('k21.kill',),board=('EDR_227',),hero='HERO_05')
        self.play(g,'k21.kill',self.body(g,'EDR_227').id)
        self.assertEqual(len(g.state.imbue_history),1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,'EDR_850p');self.portable(g)

    def test_whelp_actual_rightmost_card_discount_and_empty_hand(self):
        g=self.game(('k21.kill','CORE_CS2_182','EX1_277'),board=('EDR_890',))
        held=list(g.state.players[1].hand)[1:];self.play(g,'k21.kill',self.body(g,'EDR_890').id)
        self.assertEqual([self.price(g,e) for e in held],[4,0])
        g=self.game(('k21.kill',),board=('EDR_890',));self.play(g,'k21.kill',self.body(g,'EDR_890').id)
        self.assertFalse(g.state.players[1].hand)

    def test_whelp_current_rightmost_after_death_waiting_extra_draw(self):
        g=self.game(('k21.kill','CORE_CS2_029'),board=('EDR_890','k21.watch'),deck=('CORE_CS2_182',),mode='hand')
        original=g.state.players[1].hand[-1];self.play(g,'k21.kill',self.body(g,'EDR_890').id)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g,'hand')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());drawn=g.state.draw_history[-1].entity_id
        self.assertEqual((self.price(g,original),self.price(g,drawn)),(4,2))

    def test_stolen_whelp_uses_controller_hand_not_original_owner(self):
        g=self.game(('k21.control','k21.kill','CORE_CS2_182'),board=('EDR_890',),enemy_hand=('CORE_CS2_182',))
        source=self.body(g,'EDR_890').id;enemy_card=g.state.players[2].hand[0]
        own_card=g.state.players[1].hand[-1]
        self.play(g,'k21.control',source);self.play(g,'k21.kill',source)
        self.assertEqual((self.price(g,own_card),self.price(g,enemy_card)),(4,2))

    def test_meadow_fresh_printed_copy_bottom_cost_one_not_original_death_entity(self):
        g=self.game(('k21.buff','k21.kill'),board=('EDR_978',),deck=('CORE_CS2_182','CORE_CS2_182'))
        source=self.body(g,'EDR_978').id;self.play(g,'k21.buff',source)
        before=list(g.state.players[1].deck);self.play(g,'k21.kill',source)
        deck=g.state.players[1].deck;self.assertEqual(deck[:-1],before);copy=g.state.entities[deck[-1]]
        self.assertNotEqual(copy.id,source);self.assertEqual(copy.card_id,'EDR_978')
        self.assertEqual((copy.attack,copy.max_health),(6,11));self.assertEqual(self.price(g,copy.id),1)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.portable(g)

    def test_meadow_empty_deck_new_card_draw_retains_cost_one(self):
        g=self.game(('k21.kill','k21.draw'),board=('EDR_978',),deck=())
        self.play(g,'k21.kill',self.body(g,'EDR_978').id);self.play(g,'k21.draw')
        record=g.state.draw_history[0];self.assertEqual(record.card_id,'EDR_978')
        self.assertEqual(self.price(g,record.entity_id),1)
