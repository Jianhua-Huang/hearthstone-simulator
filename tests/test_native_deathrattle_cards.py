"""Real Disguised, Poisonous, hand-debuff and conditional weapon Deathrattles."""
import json
from random import Random
import unittest
from hs_sim.cards.death_followup_cards import load_batch
from hs_sim.engine import (Attack,CardDefinition,CardType,Game,IllegalAction,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,TriggerSpec,Zone)
from hs_sim.engine.effects import (ChoiceOption,Draw,EquipWeapon,GainArmor,InvokeBehavior,
    RequestChoice,Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay,replay
from test_death_followup_cards import registry as base_registry

OPERATOR='CAP_004';SPORE='EDR_110';TWISTED='EDR_495';BLIGHT='END_002'
YETI='CORE_CS2_182';SQUIRE='CORE_EX1_008';FISH='CORE_EX1_506'


def registry(mode=None):
    r=base_registry()
    r.register_behavior('k37.silence',lambda c:(Silence(c.target_id),))
    r.register_card(CardDefinition('k37.silence','Silence fixture',CardType.SPELL,
        on_play='k37.silence',requires_target=True))
    r.register_card(CardDefinition('k37.immune','Immune fixture',CardType.MINION,
        attack=4,health=5,keywords=(Keyword.IMMUNE,)))
    if mode:
        def watch(c):
            expected={'spore':SPORE,'weapon':BLIGHT,'hand':TWISTED}[mode]
            if c.state.entities[c.event.target_id].card_id!=expected:return ()
            continuation=(EquipWeapon(1,'CS2_082'),)if mode=='weapon'else(
                (Draw(1,source_id=c.source_id),)if mode=='hand'else(GainArmor(1,1),))
            return (RequestChoice(1,(
                ChoiceOption('ok','Continue original Deathrattle',continuation),
                ChoiceOption('bad','Fail transaction',(InvokeBehavior('k21.fail',c.source_id,1),))),c.source_id),)
        r.register_behavior('k37.watch',watch)
        r.register_card(CardDefinition('k37.watch','Death reaction fixture',CardType.MINION,health=8,
            triggers=(TriggerSpec('minion_died','k37.watch'),)))
    return r


class NativeDeathrattleCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=(YETI,)*5,
             enemy_deck=(YETI,)*5,weapon=None,mode=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,weapon_card_id=weapon,
                mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=enemy_deck)),seed=372),
            registry(mode)if mode else self.registry)
    def body(self,g,cid,p=1):return next(g.state.entities[e]for e in g.state.players[p].board if g.state.entities[e].card_id==cid)
    def play(self,g,cid,target=None,side=None):
        eid=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid)
        g.apply(PlayCard(1,eid,target,board_player_id=side));return eid
    def choose(self,g,option='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option,)))
    def portable(self,g,mode=None):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(mode))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved);return other
    def rows(self,g,cid):return[r.health_result for r in g.state.damage_history if r.health_result.source_card_id==cid]

    def test_full_current_faces_keywords_and_both_official_related_knives(self):
        data=load_batch();rows={x['record']['id']:x for x in data['cards']}
        for cid,stats,keywords in [(OPERATOR,(1,4,2),(Keyword.RUSH,)),(SPORE,(5,1,5),(Keyword.POISONOUS,)),
                                  (TWISTED,(2,2,2),()),(BLIGHT,(4,4,3),(Keyword.REBORN,))]:
            card=self.registry.card(cid);self.assertEqual((card.cost,card.attack,card.health),stats)
            self.assertEqual(card.keywords,keywords);self.assertTrue(card.deathrattle)
            self.assertEqual(card.disguised,cid==OPERATOR);self.assertEqual(card.name,rows[cid]['record']['name'])
        self.assertEqual(set(self.registry.card(BLIGHT).metadata.classes),{'death_knight','rogue'})
        self.assertEqual({x['dbf_id']for x in data['gallery_dependency_links']},{485,46054})
        for cid in ('CS2_082','CS2_082_H1'):
            card=self.registry.card(cid);self.assertEqual((card.cost,card.attack,card.durability),(1,1,2))
            self.assertFalse(card.metadata.collectible)

    def test_operator_friendly_rush_attack_and_opponent_two_real_draws(self):
        g=self.game((OPERATOR,),enemy=(YETI,));source=self.play(g,OPERATOR)
        self.assertEqual(g.state.players[1].mana,39)
        g.apply(Attack(1,source,self.body(g,YETI,2).id))
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[2].hand),2);self.assertFalse(g.state.players[1].hand)
        self.assertEqual(len(g.state.draw_history),2);self.portable(g)

    def test_operator_enemy_placement_preserves_actor_owner_and_changes_draw_receiver(self):
        g=self.game((OPERATOR,'k21.kill'));source=self.play(g,OPERATOR,side=2)
        self.assertEqual((g.state.entities[source].owner,g.state.entities[source].controller),(1,2))
        self.assertEqual(g.state.play_history[0].player_id,1)
        self.play(g,'k21.kill',source)
        self.assertEqual(len(g.state.players[1].hand),2);self.assertFalse(g.state.players[2].hand)
        self.assertEqual(g.state.death_history[0].controller,2);self.portable(g)

    def test_operator_later_control_not_original_owner_decides_receiver(self):
        g=self.game(('k21.control','k21.kill'),board=(OPERATOR,));source=self.body(g,OPERATOR).id
        self.play(g,'k21.control',source);self.play(g,'k21.kill',source)
        self.assertEqual(len(g.state.players[1].hand),2);self.assertFalse(g.state.players[2].hand)

    def test_operator_draw_respects_hand_capacity_and_fatigue(self):
        g=self.game(('k21.kill',),board=(OPERATOR,),enemy_hand=(YETI,)*9,enemy_deck=(YETI,)*2)
        self.play(g,'k21.kill',self.body(g,OPERATOR).id)
        self.assertEqual(len(g.state.players[2].hand),10);self.assertFalse(g.state.players[2].deck)
        g=self.game(('k21.kill',),board=(OPERATOR,),enemy_deck=())
        self.play(g,'k21.kill',self.body(g,OPERATOR).id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27)

    def test_enemy_full_or_plain_minion_side_rejected_atomically(self):
        for cid,enemy in ((OPERATOR,(YETI,)*7),(YETI,())):
            g=self.game((cid,),enemy=enemy);before=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,cid,side=2)
            self.assertEqual(g.snapshot(),before)

    def test_spore_dead_poisonous_source_kills_one_from_full_enemy_pool_no_spell_bonus(self):
        g=self.game(('k21.kill',),board=(SPORE,'CORE_EX1_012'),enemy=(YETI,YETI))
        targets=tuple(g.state.players[2].board);rng=Random();rng.setstate(g._rng.getstate());expected=rng.choice(sorted(targets))
        source=self.body(g,SPORE).id;self.play(g,'k21.kill',source)
        self.assertEqual(g.state.entities[expected].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[2].board),1);self.assertEqual(g._rng.getstate(),rng.getstate())
        row=self.rows(g,SPORE)[0];self.assertEqual((row.damage_dealt,row.modified_amount,row.spell_bonus),(1,1,0))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30);self.portable(g)

    def test_spore_divine_shield_and_immune_prevent_poison(self):
        for cid in (SQUIRE,'k37.immune'):
            g=self.game(('k21.kill',),board=(SPORE,),enemy=(cid,));target=self.body(g,cid,2).id
            original=g.state.entities[target].health;self.play(g,'k21.kill',self.body(g,SPORE).id)
            self.assertIn(target,g.state.players[2].board);self.assertEqual(g.state.entities[target].health,original)
            self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[target].keywords)

    def test_spore_empty_minion_pool_keeps_hero_and_rng(self):
        g=self.game(('k21.kill',),board=(SPORE,));before=g._rng.getstate()
        self.play(g,'k21.kill',self.body(g,SPORE).id)
        self.assertEqual(g._rng.getstate(),before);self.assertFalse(self.rows(g,SPORE))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)

    def test_spore_active_body_and_silence_use_existing_lifecycle(self):
        g=self.game(('k21.trigger',),board=(SPORE,),enemy=(YETI,));source=self.body(g,SPORE).id
        self.play(g,'k21.trigger',source);self.assertIn(source,g.state.players[1].board)
        self.assertFalse(g.state.players[2].board)
        self.assertEqual([d.card_id for d in g.state.death_history],[YETI])
        g=self.game(('k37.silence','k21.kill'),board=(SPORE,),enemy=(YETI,));source=self.body(g,SPORE).id
        self.play(g,'k37.silence',source);self.play(g,'k21.kill',source)
        self.assertEqual(self.body(g,YETI,2).health,5);self.assertFalse(self.rows(g,SPORE))

    def test_spore_death_waiting_failure_restore_replay_and_private_rng(self):
        g=self.game(('k21.kill',),board=(SPORE,'k37.watch'),enemy=(YETI,YETI),mode='spore')
        self.play(g,'k21.kill',self.body(g,SPORE).id);self.assertIsNotNone(g.state.pending_choice)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g,'spore')
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.players[2].board),1)
        self.assertNotIn('rng_state',json.dumps(g.observe(2)))

    def test_twisted_two_physical_hand_pools_including_duplicates_exclude_spells(self):
        g=self.game(('k21.kill',YETI,YETI,'CORE_CS2_029'),board=(TWISTED,),enemy_hand=(YETI,'CORE_CS2_029',FISH))
        ids={p:[e for e in g.state.players[p].hand if g.state.entities[e].kind==CardType.MINION]for p in(1,2)}
        attacks={e:g.state.entities[e].attack for pool in ids.values()for e in pool}
        rng=Random();rng.setstate(g._rng.getstate());selected=[rng.choice(ids[p])for p in(1,2)]
        self.play(g,'k21.kill',self.body(g,TWISTED).id)
        for eid,attack in attacks.items():self.assertEqual(g.state.entities[eid].attack,max(0,attack-(2 if eid in selected else 0)))
        self.assertEqual(g._rng.getstate(),rng.getstate());self.assertIsNone(g.state.pending_choice)
        self.portable(g)

    def test_twisted_empty_or_spell_only_hands_no_rng_or_created_cards(self):
        g=self.game(('k21.kill','CORE_CS2_029'),board=(TWISTED,),enemy_hand=('CORE_CS2_029',));before=g._rng.getstate()
        self.play(g,'k21.kill',self.body(g,TWISTED).id)
        self.assertEqual(g._rng.getstate(),before)
        self.assertEqual([len(g.state.players[p].hand)for p in(1,2)],[1,1])

    def test_twisted_repeated_active_debuff_preserves_hand_entity_into_play(self):
        g=self.game(('k21.trigger','k21.trigger',YETI),board=(TWISTED,),enemy_hand=(FISH,))
        held=g.state.players[1].hand[-1];source=self.body(g,TWISTED).id
        self.play(g,'k21.trigger',source);self.play(g,'k21.trigger',source)
        self.assertEqual(g.state.entities[held].attack,0);self.assertEqual(g.state.entities[held].max_health,5)
        self.assertEqual(self.play(g,YETI),held);self.assertEqual(g.state.entities[held].attack,0)

    def test_twisted_waits_then_queries_actual_hand_and_hides_opponent_material(self):
        g=self.game(('k21.kill',),board=(TWISTED,'k37.watch'),deck=(YETI,),enemy_hand=(FISH,),mode='hand')
        self.play(g,'k21.kill',self.body(g,TWISTED).id);self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g,'hand')
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());held=g.state.players[1].hand[0]
        self.assertEqual((g.state.entities[held].card_id,g.state.entities[held].attack),(YETI,2))
        for p in(1,2):
            view=json.dumps(g.observe(p));self.assertNotIn('zone_epoch',view);self.assertNotIn('rng_state',view)

    def test_blightspawn_equips_then_reborn_death_buffs_same_weapon(self):
        g=self.game(('k21.kill','k21.kill'),board=(BLIGHT,));source=self.body(g,BLIGHT).id
        self.play(g,'k21.kill',source);weapon=g.state.players[1].weapon_id
        self.assertEqual((g.state.entities[weapon].card_id,g.state.entities[weapon].attack,g.state.entities[weapon].durability),('CS2_082',1,2))
        reborn=self.body(g,BLIGHT);self.assertNotEqual(reborn.id,source)
        self.assertEqual(reborn.health,1);self.assertNotIn(Keyword.REBORN,reborn.keywords)
        self.play(g,'k21.kill',reborn.id)
        self.assertEqual(g.state.players[1].weapon_id,weapon)
        self.assertEqual((g.state.entities[weapon].attack,g.state.entities[weapon].durability),(3,2));self.portable(g)

    def test_blightspawn_existing_weapon_keeps_identity_durability_and_hero_attack(self):
        g=self.game(('k21.kill',),board=(BLIGHT,),weapon='k21.blade');weapon=g.state.players[1].weapon_id
        self.play(g,'k21.kill',self.body(g,BLIGHT).id)
        self.assertEqual(g.state.players[1].weapon_id,weapon)
        self.assertEqual((g.state.entities[weapon].attack,g.state.entities[weapon].durability),(3,2))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack,3)

    def test_blightspawn_active_controller_and_silence(self):
        g=self.game(('k21.control','k21.trigger'),board=(BLIGHT,));source=self.body(g,BLIGHT).id
        self.play(g,'k21.control',source);self.play(g,'k21.trigger',source)
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(g.state.entities[g.state.players[2].weapon_id].card_id,'CS2_082')
        self.assertFalse(g.state.death_history)
        g=self.game(('k37.silence','k21.kill'),board=(BLIGHT,));source=self.body(g,BLIGHT).id
        self.play(g,'k37.silence',source);self.play(g,'k21.kill',source)
        self.assertIsNone(g.state.players[1].weapon_id);self.assertFalse(g.state.players[1].board)

    def test_blightspawn_rechecks_weapon_after_death_reaction_wait_and_rollback(self):
        g=self.game(('k21.kill',),board=(BLIGHT,'k37.watch'),mode='weapon')
        self.play(g,'k21.kill',self.body(g,BLIGHT).id);self.assertIsNotNone(g.state.pending_choice)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g,'weapon')
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());weapon=g.state.entities[g.state.players[1].weapon_id]
        self.assertEqual((weapon.card_id,weapon.attack,weapon.durability),('CS2_082',3,2))
