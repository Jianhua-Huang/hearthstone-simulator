"""Real finite spell sequences over the existing health/zone/tribe interpreter."""
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.health_sequence_cards import PREFIX,load_batch
from hs_sim.engine import Game,PlayCard,EndTurn,SelectChoice,PlayerSetup,Scenario,CardDefinition,CardType,Keyword,TriggerSpec
from hs_sim.engine.effects import AddToHand,ChangeControl,ChoiceOption,Damage,Destroy,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import SpellSchool,SummonQuantitySpec,TribeChangeSpec,Zone
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.tribes import ChangeMinionTribes

BURST='FIR_909';SCORCH='FIR_954';CRYO='TLC_440';FUMES='TLC_901';ELECTRIC='TIME_216';INFEST='EDR_814'
YETI='CORE_CS2_182';LEECH='EDR_810t';ROOTS=(BURST,SCORCH,CRYO,FUMES,ELECTRIC,INFEST)


def registry():
    r=build_registry();base=r.card(YETI).metadata
    for key,tribes,health,keywords in(('big',(),20,()),('demon',('demon',),9,()),('beast',('beast',),9,()),
        ('dual',('demon','beast'),9,()),('all',('all',),9,()),('shield',('demon',),20,(Keyword.DIVINE_SHIELD,)),
        ('immune',('demon',),20,(Keyword.IMMUNE,)),('reborn',('demon',),5,(Keyword.REBORN,)),('small',(),2,())):
        r.register_card(CardDefinition('h39.'+key,key,CardType.MINION,attack=1,health=health,keywords=keywords,
            metadata=replace(base,collectible=False,tribes=tribes,deck_identity=None)))
    r.register_card(CardDefinition('h39.unknown','Unknown tribe fixture',CardType.MINION,health=9))
    r.register_card(CardDefinition('h39.sleep','Dormant demon',CardType.MINION,health=9,dormant_turns=2,
        metadata=replace(base,collectible=False,tribes=('demon',),deck_identity=None)))
    r.register_card(CardDefinition('h39.bonus','Spell damage fixture',CardType.MINION,health=2,spell_damage=1,
        metadata=replace(base,collectible=False,tribes=('undead',),deck_identity=None)))
    r.register_card(CardDefinition('h39.double','Quantity fixture',CardType.MINION,health=8,
        summon_quantities=(SummonQuantitySpec(),),metadata=replace(base,collectible=False,tribes=(),deck_identity=None)))
    r.register_behavior('h39.fail',lambda c:(AddToHand(1,'missing.h39'),))
    def change(c,spec):return(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),spec,c.source_id),)
    scripts={
        'steal':lambda c:(ChangeControl(c.target_id,1),),
        'set_demon':lambda c:change(c,TribeChangeSpec('set',('demon',))),
        'exclude_demon':lambda c:change(c,TribeChangeSpec('remove',('demon',))),
        'late':lambda c:(Damage(c.target_id,5,c.source_id,on_result=PREFIX+'scorch_result'),AddToHand(1,'missing.h39')),
        'cast_burst':lambda c:(CastSpell(1,BURST,c.source_id),),
        'cast_infest':lambda c:(CastSpell(1,INFEST,c.source_id,c.target_id,targeting='explicit'),),
    }
    for key,body in scripts.items():
        r.register_behavior('h39.'+key,body);r.register_card(CardDefinition('h39.'+key,key,CardType.SPELL,
            on_play='h39.'+key,requires_target=key!='cast_burst'))
    def wait(c,kill=False):
        e=c.state.entities.get(c.event.source_id)
        if e is None or e.card_id not in ROOTS:return ()
        options=(ChoiceOption('ok','Continue',(GainArmor(1,1),)),
            ChoiceOption('bad','Rollback choice',(InvokeBehavior('h39.fail',c.source_id,1),)))
        prefix=(Destroy(c.event.target_id,c.source_id),)if kill and e.card_id==ELECTRIC else()
        return(*prefix,RequestChoice(1,options,c.source_id))
    for key,kill in(('wait',False),('killwait',True)):
        r.register_behavior('h39.'+key,lambda c,kill=kill:wait(c,kill))
        r.register_card(CardDefinition('h39.'+key,key,CardType.MINION,health=9,
            triggers=(TriggerSpec('damage_dealt','h39.'+key),),metadata=replace(base,collectible=False,tribes=(),deck_identity=None)))
    return r


class HealthSequenceSpellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=(YETI,)*8,enemy_deck=(YETI,)*8,seed=517):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=enemy_deck,mana=40,max_mana=40,mana_cap=40)),seed=seed),self.registry)
    def play(self,g,cid,target=None):
        eid=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid);g.apply(PlayCard(1,eid,target));return eid
    def body(self,g,cid,p=2):return next(g.state.entities[e]for e in g.state.players[p].board if g.state.entities[e].card_id==cid)
    def hero(self,g,p=2):return g.state.entities[g.state.players[p].hero_id]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));h=Game.from_snapshot(saved,registry())
        self.assertEqual(h.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return h
    def health_rows(self,g,cid):return[x.health_result for x in g.state.damage_history if x.health_result.source_card_id==cid]
    def preceding_frost(self,g,card='CORE_CS2_024'):
        self.play(g,card,self.hero(g).id);g.apply(EndTurn(1));g.apply(EndTurn(2))

    def test_complete_six_faces_targets_school_runes_and_existing_leech(self):
        expected={BURST:(2,SpellSchool.FIRE),SCORCH:(1,SpellSchool.FIRE),CRYO:(4,SpellSchool.FROST),
            FUMES:(2,SpellSchool.FEL),ELECTRIC:(3,SpellSchool.NATURE),INFEST:(2,None)}
        for cid,(cost,school)in expected.items():
            c=self.registry.card(cid);self.assertEqual((c.cost,c.spell_school),(cost,school));self.assertTrue(c.on_play)
        self.assertEqual(self.registry.card(CRYO).metadata.runes.frost,2)
        data=load_batch();self.assertEqual(len(data['cards']),6);self.assertEqual(data['existing_dependencies'][0]['record']['id'],LEECH)
        self.assertEqual((self.registry.card(LEECH).attack,self.registry.card(LEECH).health),(0,2))

    def test_burst_three_distinct_enemies_one_batch_and_single_spell_bonus(self):
        g=self.game((BURST,),board=('h39.bonus',),enemy=('h39.big',)*5);pool={self.hero(g).id,*g.state.players[2].board}
        self.play(g,BURST);rows=self.health_rows(g,BURST)
        self.assertEqual(len(rows),3);self.assertEqual(len({x.target_id for x in rows}),3)
        self.assertTrue(all(x.target_id in pool and x.modified_amount==3 and x.spell_bonus==1 for x in rows))
        self.assertEqual(len({x.batch_id for x in rows}),1);self.portable(g)

    def test_burst_small_pool_hits_every_target_without_unnecessary_rng(self):
        g=self.game((BURST,),enemy=('h39.big','h39.big'));rng=g._rng.getstate();self.play(g,BURST)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(self.hero(g).health,28)
        self.assertTrue(all(g.state.entities[e].health==18 for e in g.state.players[2].board));self.portable(g)

    def test_burst_shield_immunity_and_dormancy_use_existing_health_rules(self):
        g=self.game((BURST,),enemy=('h39.shield','h39.immune','h39.sleep'));self.play(g,BURST)
        self.assertEqual(self.body(g,'h39.shield').health,20);self.assertNotIn(Keyword.DIVINE_SHIELD,self.body(g,'h39.shield').keywords)
        self.assertEqual(self.body(g,'h39.immune').health,20);self.assertEqual(self.body(g,'h39.sleep').health,9);self.assertEqual(self.hero(g).health,28)

    def test_scorch_friendly_and_enemy_current_controller_draws_original_physical_card(self):
        for p in(1,2):
            g=self.game((SCORCH,),board=('h39.big',)if p==1 else(),enemy=('h39.big',)if p==2 else())
            target=self.body(g,'h39.big',p);original=g.state.players[p].deck[0];self.play(g,SCORCH,target.id)
            self.assertEqual(g.state.entities[target.id].health,15);self.assertIn(original,g.state.players[p].hand)
            self.portable(g)

    def test_scorch_lethal_damage_still_draws_for_original_target_controller(self):
        g=self.game((SCORCH,),enemy=(YETI,));target=self.body(g,YETI);drawn=g.state.players[2].deck[0];self.play(g,SCORCH,target.id)
        self.assertEqual(g.state.entities[target.id].zone,Zone.GRAVEYARD);self.assertIn(drawn,g.state.players[2].hand)
        self.assertEqual(len(self.health_rows(g,SCORCH)),1);self.portable(g)

    def test_scorch_prevention_still_resolves_owner_draw(self):
        for target,p in(('h39.shield',2),('h39.immune',1)):
            g=self.game((SCORCH,),board=(target,)if p==1 else(),enemy=(target,)if p==2 else())
            e=self.body(g,target,p);self.play(g,SCORCH,e.id)
            self.assertEqual(g.state.entities[e.id].health,20);self.assertEqual(len(g.state.players[p].hand),1)

    def test_scorch_controlled_enemy_draws_for_current_controller_not_allocation_owner(self):
        g=self.game((SCORCH,'h39.steal'),enemy=('h39.big',));e=self.body(g,'h39.big');self.play(g,'h39.steal',e.id)
        self.assertEqual((g.state.entities[e.id].owner,g.state.entities[e.id].controller),(2,1))
        self.play(g,SCORCH,e.id);self.assertEqual(len(g.state.players[1].hand),1);self.assertFalse(g.state.players[2].hand);self.portable(g)

    def test_scorch_empty_deck_fatigue_and_full_hand_burn_are_normal_draws(self):
        g=self.game((SCORCH,),enemy=(YETI,),enemy_deck=());self.play(g,SCORCH,self.body(g,YETI).id);self.assertEqual(self.hero(g).health,29)
        g=self.game((SCORCH,),enemy=(YETI,),enemy_hand=(YETI,)*10,enemy_deck=(YETI,));burn=g.state.players[2].deck[0]
        self.play(g,SCORCH,self.body(g,YETI).id);self.assertEqual(g.state.entities[burn].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[2].hand),10);self.portable(g)

    def test_cryo_same_turn_frost_does_not_satisfy_previous_owner_turn(self):
        g=self.game((CRYO,'CORE_CS2_024'),board=('h39.big',));self.play(g,'CORE_CS2_024',self.body(g,'h39.big',1).id)
        self.play(g,CRYO,self.hero(g).id);self.assertEqual(len(g.state.players[1].hand),1)
        self.assertEqual(self.hero(g).health,26);self.assertFalse(self.hero(g).frozen);self.portable(g)

    def test_cryo_previous_frost_draws_two_and_other_school_draws_one(self):
        for previous,count in(('CORE_CS2_024',2),('CORE_CS2_029',1)):
            g=self.game((previous,CRYO));self.preceding_frost(g,previous);before=len(g.state.players[1].hand)
            self.play(g,CRYO,self.hero(g,1).id);self.assertEqual(len(g.state.players[1].hand),before-1+count)
            self.assertFalse(self.hero(g,1).frozen);self.portable(g)

    def test_cryo_accepted_bonus_wait_restoration_and_failed_choice_no_second_payment(self):
        g=self.game(('CORE_CS2_024',CRYO),board=('h39.wait',))
        # The observer reacts only to this batch's six source identities.
        self.preceding_frost(g);before_mana=g.state.players[1].mana;self.play(g,CRYO,self.hero(g).id)
        self.assertIsNotNone(g.state.pending_choice);h=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot())
        self.assertEqual(g.state.players[1].mana,before_mana-4);self.assertEqual(len(g.state.players[1].hand),3);self.portable(g)

    def test_electric_survival_draws_two_and_damage_uses_spell_bonus_once(self):
        g=self.game((ELECTRIC,),board=('h39.bonus',),enemy=('h39.big',));target=self.body(g,'h39.big');self.play(g,ELECTRIC,target.id)
        self.assertEqual(g.state.entities[target.id].health,14);self.assertEqual(len(g.state.players[1].hand),2)
        result=self.health_rows(g,ELECTRIC)[0];self.assertEqual((result.modified_amount,result.spell_bonus),(6,1));self.portable(g)

    def test_electric_lethal_and_reborn_do_not_rewrite_failed_original_survival(self):
        for cid in(YETI,'h39.reborn'):
            g=self.game((ELECTRIC,),enemy=(cid,));target=self.body(g,cid);self.play(g,ELECTRIC,target.id)
            self.assertFalse(g.state.players[1].hand);self.assertEqual(g.state.entities[target.id].zone,Zone.GRAVEYARD)
            if cid=='h39.reborn':self.assertTrue(g.state.players[2].board)
            self.portable(g)

    def test_electric_shield_or_friendly_immunity_still_survives(self):
        for cid,p in(('h39.shield',2),('h39.immune',1)):
            g=self.game((ELECTRIC,),board=(cid,)if p==1 else(),enemy=(cid,)if p==2 else())
            target=self.body(g,cid,p);self.play(g,ELECTRIC,target.id)
            self.assertEqual(g.state.entities[target.id].health,20);self.assertEqual(len(g.state.players[1].hand),2)

    def test_electric_original_health_window_keeps_accepted_reward_after_later_destroy(self):
        g=self.game((ELECTRIC,),board=('h39.killwait',),enemy=('h39.big',));target=self.body(g,'h39.big');self.play(g,ELECTRIC,target.id)
        self.assertIsNotNone(g.state.pending_choice);h=self.portable(g);self.choose(g);self.choose(h)
        self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(g.state.entities[target.id].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand),2);self.portable(g)

    def test_fumes_both_sides_multi_type_and_all_type_are_one_damage_batch(self):
        g=self.game((FUMES,),board=('h39.dual','h39.demon',YETI),enemy=('h39.beast','h39.all',YETI));target=self.body(g,'h39.dual',1)
        self.play(g,FUMES,target.id);rows=self.health_rows(g,FUMES)
        self.assertEqual(len(rows),4);self.assertEqual(len({x.batch_id for x in rows}),1)
        for p,cid in((1,'h39.dual'),(1,'h39.demon'),(2,'h39.beast'),(2,'h39.all')):self.assertEqual(self.body(g,cid,p).health,6)
        self.assertEqual(self.body(g,YETI,1).health,5);self.assertEqual(self.body(g,YETI).health,5);self.portable(g)

    def test_fumes_tribeless_target_only_and_unknown_others_irrelevant(self):
        g=self.game((FUMES,),board=(YETI,),enemy=(YETI,'h39.unknown'));target=self.body(g,YETI,1);self.play(g,FUMES,target.id)
        self.assertEqual(g.state.entities[target.id].health,2);self.assertEqual(self.body(g,YETI).health,5)
        self.assertEqual(self.body(g,'h39.unknown').health,9)

    def test_fumes_current_tribe_replacement_and_symbolic_all_exclusions(self):
        g=self.game((FUMES,'h39.set_demon'),board=('h39.beast',),enemy=('h39.beast','h39.demon'));target=self.body(g,'h39.beast',1)
        self.play(g,'h39.set_demon',target.id);self.play(g,FUMES,target.id)
        self.assertEqual(self.body(g,'h39.demon').health,6);self.assertEqual(self.body(g,'h39.beast').health,9);self.portable(g)
        g=self.game((FUMES,'h39.exclude_demon'),board=('h39.all',),enemy=('h39.beast','h39.demon','h39.all'));target=self.body(g,'h39.all',1)
        self.play(g,'h39.exclude_demon',target.id);self.play(g,FUMES,target.id)
        self.assertEqual(self.body(g,'h39.demon').health,9);self.assertEqual(self.body(g,'h39.beast').health,6)
        self.assertEqual(self.body(g,'h39.all').health,6);self.portable(g)

    def test_fumes_all_target_freezes_one_spell_bonus_before_provider_death(self):
        g=self.game((FUMES,),board=('h39.bonus',),enemy=('h39.all','h39.demon',YETI));target=self.body(g,'h39.all')
        self.play(g,FUMES,target.id);rows=self.health_rows(g,FUMES)
        self.assertEqual(len(rows),3);self.assertTrue(all((x.modified_amount,x.spell_bonus)==(4,1)for x in rows))
        self.assertFalse(g.state.players[1].board);self.assertEqual(self.body(g,YETI).health,5);self.portable(g)

    def test_fumes_unknown_required_tribes_fail_atomically_and_dormant_is_not_hit(self):
        for enemy,target_cid in((('h39.unknown',),'h39.unknown'),(('h39.demon','h39.unknown'),'h39.demon')):
            g=self.game((FUMES,),enemy=enemy);saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,FUMES,self.body(g,target_cid).id)
            self.assertEqual(g.snapshot(),saved)
        g=self.game((FUMES,),enemy=('h39.demon','h39.sleep'));self.play(g,FUMES,self.body(g,'h39.demon').id)
        self.assertEqual(self.body(g,'h39.sleep').health,9)

    def test_infest_damage_then_real_leech_with_actual_spell_summon_source(self):
        g=self.game((INFEST,),enemy=('h39.small',));target=self.body(g,'h39.small');source=self.play(g,INFEST,target.id)
        self.assertEqual(g.state.entities[target.id].zone,Zone.GRAVEYARD);leech=self.body(g,LEECH,1)
        self.assertEqual((leech.attack,leech.health),(0,2));self.assertEqual(g.state.card_summon_history[-1].request.cause.source.entity_id,source)
        self.portable(g)

    def test_infest_leech_end_body_does_not_inherit_parent_spell_bonus(self):
        g=self.game((INFEST,),board=('h39.bonus',));self.play(g,INFEST,self.hero(g).id);self.assertEqual(self.hero(g).health,27)
        g.apply(EndTurn(1));self.assertEqual(self.hero(g).health,26);self.assertEqual(self.hero(g,1).health,31);self.portable(g)

    def test_infest_uses_new_death_slot_but_full_board_keeps_damage(self):
        g=self.game((INFEST,),board=('h39.big',)*6+('h39.small',));self.play(g,INFEST,self.body(g,'h39.small',1).id)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(len([e for e in g.state.players[1].board if g.state.entities[e].card_id==LEECH]),1)
        g=self.game((INFEST,),board=('h39.big',)*7);self.play(g,INFEST,self.hero(g).id)
        self.assertEqual(self.hero(g).health,28);self.assertFalse(any(g.state.entities[e].card_id==LEECH for e in g.state.players[1].board));self.portable(g)

    def test_infest_existing_quantity_doubles_leech_but_not_damage(self):
        g=self.game((INFEST,),board=('h39.double',));self.play(g,INFEST,self.hero(g).id)
        self.assertEqual(self.hero(g).health,28);self.assertEqual(len([e for e in g.state.players[1].board if g.state.entities[e].card_id==LEECH]),2);self.portable(g)

    def test_scorch_reaction_wait_bad_selection_restoration_and_private_enemy_draw(self):
        g=self.game((SCORCH,),board=('h39.wait',),enemy=('h39.big',));self.play(g,SCORCH,self.body(g,'h39.big').id)
        self.assertIsNotNone(g.state.pending_choice);h=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot())
        self.assertEqual(len(g.state.players[2].hand),1)
        self.assertIsNone(g.observe(1)['players'][1]['hand'][0].get('card_id'));self.portable(g)

    def test_late_error_rolls_back_damage_draw_death_history_and_knowledge(self):
        g=self.game(('h39.late',),enemy=(YETI,));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'h39.late',self.body(g,YETI).id)
        self.assertEqual(g.snapshot(),saved)

    def test_real_minion_target_restrictions_and_untargeted_burst(self):
        for cid in(SCORCH,FUMES,ELECTRIC,BURST):
            g=self.game((cid,),enemy=(YETI,));saved=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,cid,self.hero(g).id)
            self.assertEqual(g.snapshot(),saved)

    def test_automatic_casts_keep_native_spell_source_and_leech_attribution(self):
        g=self.game(('h39.cast_burst',),enemy=('h39.big','h39.big'));self.play(g,'h39.cast_burst')
        self.assertEqual(len(self.health_rows(g,BURST)),3);self.assertTrue(all(x.source_card_id==BURST for x in self.health_rows(g,BURST)));self.portable(g)
        g=self.game(('h39.cast_infest',));self.play(g,'h39.cast_infest',self.hero(g).id)
        self.assertEqual(g.state.card_summon_history[-1].request.cause.source.card_id,INFEST);self.assertEqual(self.body(g,LEECH,1).health,2);self.portable(g)


if __name__=='__main__':unittest.main()
