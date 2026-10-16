"""Real Duke of Below: two derived stats, original discard facts and lifetimes."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.discard_derived_stat_cards import DUKE, load_batch
from hs_sim.cards.native_discard_rewind_cards import DOOMSPEAKER
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, Destroy, InvokeBehavior, RequestChoice, ReturnToHand, SetStats, Silence, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (AuraSpec, BoardPresenceReference, StatReference,
    StatRelationLayer, StatRelationOperand, StatRelationSpec)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, DiscardCard

YETI='CORE_CS2_182';FIRE='CORE_CS2_029'


def registry():
    r=build_registry()
    def duke(c):
        return next(e for e in c.state.entities.values()if e.card_id==DUKE and e.zone==Zone.BOARD)
    def discard(c,cid=YETI):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==cid)
        return (DiscardCard(CardReference.capture(e),c.source_id),)
    scripts={
        'discard':discard,
        'discard_spell':lambda c:discard(c,FIRE),
        'hurt':lambda c:(Damage(duke(c).id,1,c.source_id),),
        'kill':lambda c:(Destroy(duke(c).id,c.source_id),),
        'silence':lambda c:(Silence(duke(c).id),),
        'control':lambda c:(ChangeControl(duke(c).id,3-duke(c).controller),),
        'copy':lambda c:(CopyMinion(BoardPresenceReference.capture(c.state,duke(c).id),c.player_id),),
        'copy_enemy':lambda c:(CopyMinion(BoardPresenceReference.capture(c.state,duke(c).id),3-c.player_id),),
        'bounce':lambda c:(ReturnToHand(duke(c).id,to_owner=True),),
        'transform':lambda c:(Transform(duke(c).id,YETI),),
        'health_set':lambda c:(SetStats(duke(c).id,health=5,source_id=c.source_id),),
        'negative':lambda c:(Buff(duke(c).id,health=-5,source_id=c.source_id),),
    }
    for name,body in scripts.items():
        r.register_behavior('k91.'+name,body)
        r.register_card(CardDefinition('k91.'+name,name,CardType.SPELL,on_play='k91.'+name))
    r.register_behavior('k91.fail',lambda c:(AddToHand(c.player_id,'unknown.k91'),))
    r.register_behavior('k91.wait',lambda c:(RequestChoice(c.player_id,(
        ChoiceOption('ok','Continue',()),
        ChoiceOption('bad','Fail',(InvokeBehavior('k91.fail',c.source_id,c.player_id),)),
    ),source_id=c.source_id),))
    r.register_card(CardDefinition('k91.watch','Discard observer',CardType.MINION,health=10,
                                   triggers=(TriggerSpec('card_discarded','k91.wait'),)))
    r.register_card(CardDefinition('k91.aura','Existing health aura',CardType.MINION,health=5,
                                   auras=(AuraSpec(health=2,include_self=False),)))
    return r


class DiscardDerivedStatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()

    def game(self,hand=(),board=(DUKE,),enemy=(),enemy_hand=(),deck=(YETI,)*8):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
        ),seed=91),self.r)

    def dukes(self,g,player=1,zone='board'):
        return [g.state.entities[i]for i in getattr(g.state.players[player],zone)if g.state.entities[i].card_id==DUKE]

    def only(self,g,player=1,zone='board'):
        value,=self.dukes(g,player,zone);return value

    def play(self,g,cid,player=None):
        p=g.state.active_player if player is None else player
        eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid,position=len(g.state.players[p].board)if cid==DUKE else None));return eid

    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def stats(self,e):return(e.attack,e.max_health,e.health)

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())
            for hidden in('conditional_health','conditional_attack','discard_history','resolution_frame','rng_state'):
                self.assertNotIn(hidden,public)
        return other

    def test_complete_real_source_and_two_finite_native_declarations(self):
        raw,=load_batch()['cards'];card=self.r.card(DUKE)
        self.assertEqual((raw['record']['dbf_id'],card.cost,card.attack,card.health),(122713,4,2,2))
        self.assertEqual(card.keywords,(Keyword.RUSH,))
        self.assertEqual({s.target for s in card.stat_relations},{StatReference.ATTACK,StatReference.HEALTH})
        self.assertIsNone(card.battlecry)

    def test_one_own_discard_adds_two_attack_and_two_health_without_enchantments(self):
        g=self.game(('k91.discard',YETI));source=self.only(g);before=len(source.enchantments)
        self.play(g,'k91.discard');source=self.only(g)
        self.assertEqual(self.stats(source),(4,4,4));self.assertEqual(source.conditional_health,2)
        self.assertEqual(len(source.enchantments),before);self.portable(g)

    def test_history_before_entry_updates_both_hand_and_deck_and_real_play(self):
        g=self.game(('k91.discard',YETI,DUKE),board=(),deck=(DUKE,))
        self.play(g,'k91.discard')
        self.assertEqual(self.stats(self.only(g,zone='hand')),(4,4,4))
        self.assertEqual(self.stats(self.only(g,zone='deck')),(4,4,4))
        eid=self.play(g,DUKE);self.assertEqual(self.stats(g.state.entities[eid]),(4,4,4))
        self.assertIn(Keyword.RUSH,g.state.entities[eid].keywords)

    def test_spell_discard_is_also_a_real_counter_occurrence(self):
        g=self.game(('k91.discard_spell',FIRE));self.play(g,'k91.discard_spell')
        self.assertEqual(self.stats(self.only(g)),(4,4,4))

    def test_each_occurrence_adds_once_and_health_growth_preserves_damage(self):
        g=self.game(('k91.discard',YETI,'k91.hurt','k91.discard',YETI))
        self.play(g,'k91.discard');self.play(g,'k91.hurt')
        self.assertEqual(self.stats(self.only(g)),(4,4,3))
        self.play(g,'k91.discard');self.assertEqual(self.stats(self.only(g)),(6,6,5))
        self.assertEqual(self.only(g).damage,1)

    def test_opponent_discard_does_not_feed_current_owner(self):
        g=self.game(enemy_hand=('k91.discard',YETI));g.apply(EndTurn(1));self.play(g,'k91.discard')
        self.assertEqual(self.stats(self.only(g)),(2,2,2))

    def test_silence_removes_both_relations_and_uses_existing_health_clamp(self):
        g=self.game(('k91.discard',YETI,'k91.hurt','k91.silence'))
        self.play(g,'k91.discard');self.play(g,'k91.hurt');self.play(g,'k91.silence')
        self.assertEqual(self.stats(self.only(g)),(2,2,2));self.assertEqual(self.only(g).conditional_health,0)
        self.assertNotIn(Keyword.RUSH,self.only(g).keywords);self.portable(g)

    def test_control_transfer_recomputes_new_controller_count_and_health(self):
        g=self.game(('k91.discard',YETI,'k91.hurt','k91.control'))
        self.play(g,'k91.discard');self.play(g,'k91.hurt');self.play(g,'k91.control')
        self.assertEqual(self.stats(self.only(g,2)),(2,2,2));self.assertEqual(self.only(g,2).owner,1)
        self.portable(g)

    def test_current_copy_does_not_turn_native_contribution_into_permanent_buff(self):
        g=self.game(('k91.discard',YETI,'k91.copy'));self.play(g,'k91.discard');self.play(g,'k91.copy')
        self.assertEqual([self.stats(e)for e in self.dukes(g)],[(4,4,4),(4,4,4)])
        self.assertTrue(all(not e.enchantments for e in self.dukes(g)));self.portable(g)

    def test_current_copy_to_other_player_uses_that_players_facts(self):
        g=self.game(('k91.discard',YETI,'k91.copy_enemy'));self.play(g,'k91.discard');self.play(g,'k91.copy_enemy')
        self.assertEqual(self.stats(self.only(g)),(4,4,4));self.assertEqual(self.stats(self.only(g,2)),(2,2,2))

    def test_return_and_replay_rederive_without_duplicating_bonus(self):
        g=self.game(('k91.discard',YETI,'k91.bounce'));self.play(g,'k91.discard');eid=self.only(g).id
        self.play(g,'k91.bounce');self.assertEqual(self.stats(self.only(g,zone='hand')),(4,4,4))
        self.play(g,DUKE);self.assertEqual(self.only(g).id,eid);self.assertEqual(self.stats(self.only(g)),(4,4,4))

    def test_transform_clears_conditional_health_cache(self):
        g=self.game(('k91.discard',YETI,'k91.transform'));self.play(g,'k91.discard');eid=self.only(g).id
        self.play(g,'k91.transform');e=g.state.entities[eid]
        self.assertEqual((e.card_id,e.attack,e.max_health,e.conditional_health),(YETI,4,5,0));self.portable(g)

    def test_health_set_remains_under_native_health_contribution(self):
        g=self.game(('k91.discard',YETI,'k91.health_set'));self.play(g,'k91.discard');self.play(g,'k91.health_set')
        self.assertEqual(self.stats(self.only(g)),(4,7,7))

    def test_existing_health_aura_and_native_health_are_not_double_counted(self):
        g=self.game(('k91.discard',YETI),board=(DUKE,'k91.aura'))
        self.assertEqual(self.stats(self.only(g)),(2,4,4))
        self.play(g,'k91.discard');self.assertEqual(self.stats(self.only(g)),(4,6,6))
        self.portable(g)

    def test_joint_aura_loss_and_native_health_growth_preserve_original_damage(self):
        g=self.game(('k91.hurt','k91.control'),board=(DUKE,'k91.aura'),
                    enemy_hand=('k91.discard',YETI,'k91.discard',YETI))
        self.play(g,'k91.hurt');self.assertEqual(self.stats(self.only(g)),(2,4,3))
        g.apply(EndTurn(1));self.play(g,'k91.discard');self.play(g,'k91.discard');g.apply(EndTurn(2))
        self.play(g,'k91.control')
        self.assertEqual(self.stats(self.only(g,2)),(6,6,5))
        self.assertEqual(self.only(g,2).damage,1)
        self.portable(g)

    def test_negative_local_health_still_uses_shared_death_pipeline(self):
        g=self.game(('k91.discard',YETI,'k91.negative'));self.play(g,'k91.discard');eid=self.only(g).id
        self.play(g,'k91.negative');self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        row=next(r for r in g.state.death_history if r.entity_id==eid)
        self.assertEqual(row.attack,4);self.portable(g)

    def test_death_record_keeps_original_stats_after_later_discard(self):
        g=self.game(('k91.discard',YETI,'k91.kill','k91.discard',YETI))
        self.play(g,'k91.discard');eid=self.only(g).id;self.play(g,'k91.kill')
        death=next(r for r in g.state.death_history if r.entity_id==eid)
        self.assertEqual((death.attack,death.max_health),(4,4));self.play(g,'k91.discard')
        self.assertEqual(next(r for r in g.state.death_history if r.entity_id==eid),death);self.portable(g)

    def test_native_rewind_restores_discard_facts_and_both_derived_stats(self):
        g=self.game((DOOMSPEAKER,YETI),enemy_hand=(YETI,));source=self.play(g,DOOMSPEAKER)
        self.assertEqual(self.stats(self.only(g)),(4,4,4));self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g);self.choose(g,'retry');self.choose(other,'retry')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.stats(self.only(g)),(4,4,4))
        self.assertEqual(len(g.state.discard_history),2)
        self.assertEqual(sum(e.kind=='card_discarded'for e in g.events),4)
        self.assertIn(source,g.state.players[1].board);self.portable(g)

    def test_real_discard_wait_restores_new_cache_and_transaction_failure(self):
        g=self.game(('k91.discard',YETI),board=(DUKE,'k91.watch'));self.play(g,'k91.discard')
        self.assertEqual(self.stats(self.only(g)),(4,4,4));before=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)

    def test_rehashed_wrong_conditional_cache_is_rejected(self):
        g=self.game(('k91.discard',YETI));self.play(g,'k91.discard');eid=self.only(g).id
        saved=deepcopy(g.snapshot());saved['state']['entities'][str(eid)]['conditional_health']=99
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as error:Game.from_snapshot(saved,registry())
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_finite_health_declaration_does_not_enable_arbitrary_relations(self):
        for kw in(dict(target=StatReference.HEALTH),dict(layer=StatRelationLayer.CONDITIONAL_HEALTH),
                   dict(target=StatReference.HEALTH,operand=StatRelationOperand.SELF_DAMAGED,
                        layer=StatRelationLayer.CONDITIONAL_HEALTH,amount=2)):
            with self.assertRaises(ValueError):StatRelationSpec(**kw)
