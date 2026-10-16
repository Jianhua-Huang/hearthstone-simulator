"""Actual Demon dependencies: forced ending combats and bound resurrection copy."""
import json
from random import Random
import unittest
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec,Zone
from hs_sim.engine.effects import (Buff,ChoiceOption,Damage,Destroy,Freeze,GainArmor,GrantDeathrattle,
    InvokeBehavior,RequestChoice,Silence,Summon,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.copy_materials import CopyEntryMaterial
from hs_sim.engine.model import DamageKind
from hs_sim.engine.replay import build_replay,replay
from test_death_followup_cards import registry as base_registry

TERROR='CORE_TTN_866';DINO='DINO_132';HOUND='EDR_891';BAT='EDR_892'
LOW='TLC_621';HIGH='EDR_572';YETI='CORE_CS2_182';FISH='CORE_EX1_506';SQUIRE='CORE_EX1_008'


def registry(mode=None):
    r=base_registry();r.register_behavior('d38.noop',lambda c:())
    scripts={'silence':lambda c:(Silence(c.target_id),),'grant':lambda c:(GrantDeathrattle(c.target_id,'d38.noop',c.source_id),),
        'wound':lambda c:(Damage(c.state.players[1].hero_id,10,c.source_id,DamageKind.EFFECT),),
        'freeze':lambda c:(Freeze(c.target_id),)}
    for name,body in scripts.items():
        r.register_behavior('d38.'+name,body);r.register_card(CardDefinition('d38.'+name,name,CardType.SPELL,
            on_play='d38.'+name,requires_target=name!='wound'))
    r.register_card(CardDefinition('d38.large','Large combat fixture',CardType.MINION,attack=12,health=12))
    if mode:
        def watch(c):
            if mode=='combat':
                if c.state.entities[c.event.target_id].card_id!=FISH:return ()
                target=next(e for e in c.state.players[1].board if c.state.entities[e].card_id==TERROR)
                options=(ChoiceOption('ok','Continue',(GainArmor(1,1),)),ChoiceOption('kill','Remove defender',(Destroy(target,c.source_id),)))
            else:
                row=next((x for x in c.state.resurrection_history if x.entity_id==c.event.target_id),None)
                if row is None or c.state.entities[c.event.target_id].card_id!=LOW:return ()
                target=row.entity_id
                options=(ChoiceOption('ok','Buff actual revived body and add unrelated minion',
                    (Buff(target,2,3,c.source_id),Summon(1,YETI))),
                    ChoiceOption('transform','Replace original body',(Transform(target,YETI),)))
            return(RequestChoice(1,(*options,ChoiceOption('bad','Rollback',(InvokeBehavior('k21.fail',c.source_id,1),))),c.source_id),)
        r.register_behavior('d38.watch',watch);r.register_card(CardDefinition('d38.watch','Observer fixture',CardType.MINION,health=8,
            triggers=(TriggerSpec('minion_died'if mode=='combat'else'minion_summoned','d38.watch'),)))
    return r


class DemonDependencyCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),enemy=(),mode=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40)),seed=386),registry(mode)if mode else self.registry)
    def body(self,g,cid,p=1):return next(g.state.entities[e]for e in g.state.players[p].board if g.state.entities[e].card_id==cid)
    def play(self,g,cid,target=None):
        eid=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid);g.apply(PlayCard(1,eid,target));return eid
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode=None):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(mode))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved);return other
    def end(self,g):g.apply(EndTurn(g.state.active_player))

    def test_full_faces_keywords_multitribes_and_explicit_core_identity(self):
        for cid,stats,keywords in((TERROR,(7,4,10),(Keyword.LIFESTEAL,)),(DINO,(8,6,12),(Keyword.TAUNT,)),
                                  (HOUND,(5,5,3),()),(BAT,(7,7,5),())):
            card=self.registry.card(cid);self.assertEqual((card.cost,card.attack,card.health),stats);self.assertEqual(card.keywords,keywords)
            self.assertIn('demon',card.metadata.tribes)
        self.assertEqual(self.registry.card(TERROR).metadata.deck_identity,'TTN_866')
        self.assertIn('beast',self.registry.card(TERROR).metadata.tribes);self.assertIn('beast',self.registry.card(DINO).metadata.tribes)

    def test_dino_owner_ending_one_complete_random_minion_hit_without_spell_bonus(self):
        g=self.game(board=(DINO,'CORE_EX1_012'),enemy=(YETI,YETI));targets=tuple(g.state.players[2].board)
        rng=Random();rng.setstate(g._rng.getstate());chosen=rng.choice(sorted(targets));self.end(g)
        self.assertEqual(g.state.entities[chosen].zone,Zone.GRAVEYARD);self.assertEqual(g._rng.getstate(),rng.getstate())
        rows=[x.health_result for x in g.state.damage_history if x.health_result.source_card_id==DINO]
        self.assertEqual([(x.modified_amount,x.spell_bonus)for x in rows],[(5,0)])
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        self.end(g);self.assertEqual(len(g.state.damage_history),1);self.portable(g)

    def test_dino_empty_pool_skips_rng_and_divine_shield_prevents_damage(self):
        g=self.game(board=(DINO,));before=g._rng.getstate();self.end(g);self.assertEqual(g._rng.getstate(),before)
        self.assertFalse(g.state.damage_history)
        g=self.game(board=(DINO,),enemy=(SQUIRE,));self.end(g);target=self.body(g,SQUIRE,2)
        self.assertEqual(target.health,1);self.assertNotIn(Keyword.DIVINE_SHIELD,target.keywords)

    def test_terror_forces_all_original_enemy_minions_and_retaliation_lifesteals(self):
        g=self.game(('d38.wound',),board=(TERROR,SQUIRE),enemy=(FISH,SQUIRE));self.play(g,'d38.wound')
        source=self.body(g,TERROR).id;original=tuple(g.state.players[2].board);self.end(g)
        events=[e for e in g.events if e.kind=='attack_declared']
        self.assertEqual([e.source_id for e in events],list(original));self.assertTrue(all(dict(e.data)['forced']for e in events))
        self.assertTrue(all(e.target_id==source for e in events));self.assertEqual(g.state.entities[source].health,7)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,24)
        self.assertEqual(len(g.state.players[2].board),1);self.portable(g)

    def test_terror_uses_forced_attack_for_frozen_enemy(self):
        g=self.game(('d38.freeze',),board=(TERROR,),enemy=(YETI,));target=self.body(g,YETI,2).id
        self.play(g,'d38.freeze',target);self.end(g)
        self.assertEqual(self.body(g,TERROR).health,6);self.assertEqual(g.state.entities[target].health,1)

    def test_terror_death_during_first_combat_cancels_remaining_original_defender(self):
        g=self.game(board=(TERROR,),enemy=('d38.large',FISH));second=self.body(g,FISH,2).id;self.end(g)
        self.assertFalse(g.state.players[1].board);self.assertEqual(g.state.entities[second].health,1)
        self.assertEqual(len([e for e in g.events if e.kind=='attack_declared']),1)

    def test_terror_waiting_combat_failure_restore_replay_and_defender_removed(self):
        g=self.game(board=(TERROR,'d38.watch'),enemy=(FISH,YETI),mode='combat');self.end(g)
        self.assertIsNotNone(g.state.pending_choice);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g,'combat')
        for current in(g,other):self.choose(current,'kill')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.body(g,YETI,2).health,5)
        self.assertEqual(len([e for e in g.events if e.kind=='attack_declared']),1)

    def test_felhunter_resurrects_one_low_original_face_then_copies_same_actual_body(self):
        g=self.game(('k21.buff','k21.kill','k21.kill'),board=(LOW,HOUND));old=self.body(g,LOW).id
        self.play(g,'k21.buff',old);self.play(g,'k21.kill',old);source=self.body(g,HOUND).id;self.play(g,'k21.kill',source)
        bodies=[g.state.entities[e]for e in g.state.players[1].board];self.assertEqual([e.card_id for e in bodies],[LOW,LOW])
        self.assertTrue(all((e.attack,e.max_health)==(4,7)and e.id!=old for e in bodies))
        self.assertEqual(len(g.state.resurrection_history),1)
        self.assertTrue(all(x.request.cause.source.entity_id==source for x in g.state.card_summon_history));self.portable(g)

    def test_felhunter_printed_predicate_includes_silenced_native_excludes_granted_plain(self):
        g=self.game(('d38.silence','d38.grant','k21.kill','k21.kill','k21.kill'),board=(LOW,YETI,HOUND))
        low,plain,source=g.state.players[1].board;self.play(g,'d38.silence',low);self.play(g,'d38.grant',plain)
        for target in(low,plain,source):self.play(g,'k21.kill',target)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].board],[LOW,LOW])

    def test_felbat_five_cost_boundary_and_different_card_exclusion(self):
        g=self.game(('k21.kill','k21.kill'),board=(HOUND,BAT));hound=self.body(g,HOUND).id
        self.play(g,'k21.kill',hound);self.play(g,'k21.kill',self.body(g,BAT).id)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].board],[HOUND,HOUND]);self.portable(g)
        g=self.game(('k21.kill','k21.kill'),board=(BAT,BAT));first,second=g.state.players[1].board
        self.play(g,'k21.kill',first);before=g._rng.getstate();self.play(g,'k21.kill',second)
        self.assertFalse(g.state.players[1].board);self.assertEqual(g._rng.getstate(),before)

    def test_resurrection_candidates_keep_each_death_occurrence_weight(self):
        g=self.game(('k21.kill',)*4,board=(LOW,LOW,'EDR_890',HOUND));ids=tuple(g.state.players[1].board)
        for target in ids:self.play(g,'k21.kill',target)
        root=g.state.resurrection_summon_history[-1]
        self.assertEqual(len(root.candidates),3)
        deaths={x.id:x for x in g.state.death_history}
        self.assertEqual([deaths[x].card_id for x in root.candidates].count(LOW),2)

    def test_felhunter_full_after_one_resurrection_skips_copy_without_replacing_body(self):
        # Fill the first released slot through a real minion play, then kill the source.
        g=self.game((YETI,'k21.kill','k21.kill'),board=(LOW,HOUND)+(YETI,)*5)
        self.play(g,'k21.kill',self.body(g,LOW).id);self.play(g,YETI)
        self.play(g,'k21.kill',self.body(g,HOUND).id)
        self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(sum(g.state.entities[e].card_id==LOW for e in g.state.players[1].board),1)

    def test_attributed_quantity_copies_original_resurrection_once_not_each_extra(self):
        g=self.game(('k21.kill','k21.kill'),board=(LOW,HOUND,'CORE_DAL_575'))
        self.play(g,'k21.kill',self.body(g,LOW).id);source=self.body(g,HOUND).id;self.play(g,'k21.kill',source)
        self.assertEqual(sum(g.state.entities[e].card_id==LOW for e in g.state.players[1].board),4)
        self.assertEqual(len(g.state.resurrection_history),2)
        self.assertEqual(len([x for x in g.state.card_summon_history if type(x.request.materials[0])is CopyEntryMaterial]),1)
        self.portable(g)

    def test_resurrection_waiting_binds_copy_after_buffs_not_unrelated_last_minion(self):
        g=self.game(('k21.kill','k21.kill'),board=(LOW,HOUND,'d38.watch'),mode='summon')
        self.play(g,'k21.kill',self.body(g,LOW).id);self.play(g,'k21.kill',self.body(g,HOUND).id)
        self.assertIsNotNone(g.state.pending_choice);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g,'summon')
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());bodies=[g.state.entities[e]for e in g.state.players[1].board if g.state.entities[e].card_id==LOW]
        self.assertEqual(len(bodies),2);self.assertTrue(all((e.attack,e.max_health)==(6,10)for e in bodies))
        self.assertEqual(sum(g.state.entities[e].card_id==YETI for e in g.state.players[1].board),1)
        self.assertNotIn('deathrattle_basis',json.dumps(g.observe(2)))

    def test_resurrection_subject_replaced_before_callback_does_not_copy_replacement(self):
        g=self.game(('k21.kill','k21.kill'),board=(LOW,HOUND,'d38.watch'),mode='summon')
        self.play(g,'k21.kill',self.body(g,LOW).id);self.play(g,'k21.kill',self.body(g,HOUND).id)
        self.choose(g,'transform');self.assertEqual(sum(g.state.entities[e].card_id==YETI for e in g.state.players[1].board),1)
        self.assertFalse(any(g.state.entities[e].card_id==LOW for e in g.state.players[1].board));self.portable(g,'summon')

    def test_silence_removes_both_ending_and_resurrection_bodies(self):
        for cid in(TERROR,DINO,HOUND,BAT):
            g=self.game(('d38.silence','k21.kill'),board=(cid,),enemy=(YETI,));source=self.body(g,cid).id
            self.play(g,'d38.silence',source)
            if cid in(TERROR,DINO):self.end(g);self.assertEqual(self.body(g,YETI,2).health,5)
            else:self.play(g,'k21.kill',source);self.assertFalse(g.state.resurrection_summon_history)
