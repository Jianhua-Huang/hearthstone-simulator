"""Real Mask/Servant/Last Stand over existing health, choices and recruit paths."""
import json
from random import Random
import unittest
from hs_sim.engine import (CardDefinition, CardType, Game, PlayCard, PlayerSetup, Scenario,
                          SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, InvokeBehavior, RequestChoice)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference
from hs_sim.engine.hand_upgrades import BuffStoredCard
from test_granted_deathrattle_cards import registry as base_registry

MASK='DINO_429';SERVANT='CORE_YOD_026';LAST='CATA_610'
YETI='CORE_CS2_182';SQUIRE='CORE_EX1_008';FISH='CORE_EX1_506'


def registry(mode=None):
    result=base_registry('fail' if mode=='fail' else None)
    for name,body in [('hit',lambda c:(Damage(c.target_id,2,c.source_id),)),
                      ('buff',lambda c:(Buff(c.target_id,3,0,c.source_id),))]:
        result.register_behavior('k36.'+name,body)
        result.register_card(CardDefinition('k36.'+name,name,CardType.SPELL,on_play='k36.'+name,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    def hand_buff(c):
        target=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].kind==CardType.MINION)
        return(BuffStoredCard(CardReference.capture(target),3,2,c.source_id),)
    result.register_behavior('k36.handbuff',hand_buff)
    result.register_card(CardDefinition('k36.handbuff','Hand buff',CardType.SPELL,on_play='k36.handbuff'))
    if mode=='wait':
        result.register_behavior('k36.fail',lambda c:(AddToHand(c.player_id,'unknown.k36'),))
        def watch(c):
            if c.state.entities[c.event.target_id].card_id!=YETI:return()
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior('k36.fail',c.source_id,c.player_id),))),c.source_id),)
        result.register_behavior('k36.watch',watch)
        result.register_card(CardDefinition('k36.watch','Recruit watcher',CardType.MINION,health=8,
            triggers=(TriggerSpec('minion_summoned','k36.watch'),)))
    return result


class DeathrattleEffectCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,
            mana=40,max_mana=40,mana_cap=40),PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8)),seed=439),
            registry(mode)if mode else self.r)
    def play(self,g,cid,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def board(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].board]
    def portable(self,g,mode=None):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(mode))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for key in('resolution_frame','rng_state','deathrattle_history','recruit_history','zone_epoch','entered_order'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_all_three_real_faces_have_full_native_bodies_and_exact_current_stats(self):
        self.assertEqual((self.r.card(MASK).cost,self.r.card(LAST).cost),(4,5))
        servant=self.r.card(SERVANT)
        self.assertEqual((servant.cost,servant.attack,servant.health),(1,2,1))
        self.assertEqual(servant.metadata.tribes,('demon',))
        self.assertEqual(servant.metadata.deck_identity,'YOD_026')
        self.assertIsNotNone(servant.deathrattle)
        self.assertTrue(all(self.r.card(cid).on_play for cid in(MASK,LAST)))

    def test_mask_sets_wounded_minion_to_one_one_and_can_be_silenced(self):
        g=self.game(('k36.hit',MASK,'k35.silence'),(YETI,));target=g.state.players[1].board[0]
        self.play(g,'k36.hit',target);self.play(g,MASK,target)
        e=g.state.entities[target];self.assertEqual((e.attack,e.health,e.damage),(1,1,0))
        self.assertEqual(g.state.players[1].mana,36)
        self.play(g,'k35.silence',target)
        e=g.state.entities[target]
        self.assertEqual((e.attack,e.max_health),(4,5))
        self.assertFalse([a for a in e.abilities if a.kind=='deathrattle'])

    def test_mask_death_is_one_all_minion_batch_with_no_original_spell_damage_bonus(self):
        g=self.game((MASK,'k35.kill'),(YETI,'CORE_EX1_012'),(YETI,));target=g.state.players[2].board[0]
        self.play(g,MASK,target);self.play(g,'k35.kill',target)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].health,3)
        hits=[r.health_result for r in g.state.damage_history if r.health_result.source_id==target]
        self.assertEqual(len(hits),2);self.assertEqual(len({h.batch_id for h in hits}),1)
        self.assertTrue(all(h.modified_amount==2 and h.spell_bonus==0 for h in hits))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)
        self.portable(g)

    def test_active_mask_self_death_creates_one_further_natural_payload(self):
        g=self.game((MASK,'k35.trigger'),(YETI,YETI));target=g.state.players[1].board[0]
        self.play(g,MASK,target);self.play(g,'k35.trigger',target)
        self.assertEqual(self.board(g),[YETI]);self.assertEqual(g.state.entities[g.state.players[1].board[0]].health,1)
        self.assertEqual(len(g.state.death_history),1)

    def test_mask_rejects_hero_and_late_grant_failure_restores_original_stats_and_payment(self):
        g=self.game((MASK,),(YETI,'k35.watch'),mode='fail');target=g.state.players[1].board[0];before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,MASK,g.state.players[1].hero_id)
        self.assertEqual(g.snapshot(),before)
        with self.assertRaises(ResolutionError):self.play(g,MASK,target)
        self.assertEqual(g.snapshot(),before)

    def test_servant_uses_frozen_buffed_death_attack_and_single_recipient_without_rng(self):
        g=self.game(('k36.buff','k35.kill'),(SERVANT,YETI));source,target=g.state.players[1].board
        self.play(g,'k36.buff',source);rng=g.snapshot()['rng_state'];self.play(g,'k35.kill',source)
        self.assertEqual(g.state.entities[target].attack,9)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(g.state.death_history[-1].attack,5)
        self.portable(g)

    def test_servant_samples_complete_friendly_pool_once_without_player_choice(self):
        g=self.game(('k35.kill',),(SERVANT,YETI,SQUIRE),enemy=(YETI,))
        source,*pool=g.state.players[1].board;rng=Random();rng.setstate(g._rng.getstate());expected=rng.sample(pool,1)[0]
        before={eid:g.state.entities[eid].attack for eid in pool};self.play(g,'k35.kill',source)
        self.assertEqual(g._rng.getstate(),rng.getstate());self.assertIsNone(g.state.pending_choice)
        self.assertEqual([eid for eid in pool if g.state.entities[eid].attack!=before[eid]],[expected])
        self.assertEqual(g.state.entities[expected].attack,before[expected]+2)
        self.portable(g)

    def test_servant_empty_death_pool_leaves_rng_and_enemy_unchanged(self):
        g=self.game(('k35.kill',),(SERVANT,),(YETI,));source=g.state.players[1].board[0]
        rng=g.snapshot()['rng_state'];self.play(g,'k35.kill',source)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(g.state.entities[g.state.players[2].board[0]].attack,4)

    def test_active_servant_includes_live_self_and_keeps_current_attack_operand(self):
        g=self.game(('k36.buff','k35.trigger'),(SERVANT,YETI));source,*_=g.state.players[1].board
        self.play(g,'k36.buff',source);pool=list(g.state.players[1].board);before={eid:g.state.entities[eid].attack for eid in pool}
        rng=Random();rng.setstate(g._rng.getstate());expected=rng.sample(pool,1)[0]
        self.play(g,'k35.trigger',source)
        self.assertEqual(g.state.entities[expected].attack,before[expected]+5);self.assertFalse(g.state.death_history)

    def test_last_stand_moves_original_hand_minion_keeps_buff_and_does_not_run_battlecry(self):
        for cid in(YETI,FISH):
            with self.subTest(cid=cid):
                g=self.game((LAST,'k36.handbuff','k35.kill',cid),(SQUIRE,));carrier=g.state.players[1].board[0]
                held=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
                self.play(g,'k36.handbuff');stats=(g.state.entities[held].attack,g.state.entities[held].max_health)
                self.play(g,LAST,carrier);self.play(g,'k35.kill',carrier)
                self.assertEqual(g.state.players[1].board,[held]);self.assertNotIn(held,g.state.players[1].hand)
                self.assertEqual((g.state.entities[held].attack,g.state.entities[held].max_health),stats)
                self.assertEqual(len(g.state.draw_history),0)
                self.assertEqual(g.state.card_summon_history[-1].request.cause.source.entity_id,carrier)
        self.portable(g)

    def test_stolen_last_stand_uses_new_controller_hand_not_original_caster(self):
        g=self.game((LAST,'k35.steal','k35.kill',SQUIRE),(SQUIRE,),enemy_hand=(YETI,));carrier=g.state.players[1].board[0]
        held=g.state.players[2].hand[0];self.play(g,LAST,carrier);self.play(g,'k35.steal',carrier);self.play(g,'k35.kill',carrier)
        self.assertEqual(g.state.players[2].board,[held]);self.assertEqual(self.board(g),[])

    def test_last_stand_empty_or_full_hand_recruit_does_not_move_other_cards(self):
        for full in(False,True):
            with self.subTest(full=full):
                g=self.game((LAST,'k35.trigger',YETI)if full else(LAST,'k35.trigger'),(SQUIRE,)*(7 if full else 1))
                carrier=g.state.players[1].board[0];self.play(g,LAST,carrier);before=list(g.state.players[1].hand);rng=g.snapshot()['rng_state']
                self.play(g,'k35.trigger',carrier)
                self.assertEqual(g.state.players[1].hand,[i for i in before if g.state.entities[i].card_id!='k35.trigger'])
                self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_two_grants_requery_remaining_physical_hand_and_quantity_extras_keep_material(self):
        g=self.game((LAST,LAST,'k35.kill',YETI,FISH),('CORE_DAL_575',SQUIRE));carrier=g.state.players[1].board[1]
        held={i for i in g.state.players[1].hand if g.state.entities[i].kind==CardType.MINION}
        self.play(g,LAST,carrier);self.play(g,LAST,carrier);self.play(g,'k35.kill',carrier)
        self.assertTrue(held<=set(g.state.players[1].board));self.assertEqual(len(g.state.players[1].board),5)
        self.assertEqual(self.board(g).count(YETI),2);self.assertEqual(self.board(g).count(FISH),2)
        self.portable(g)

    def test_waiting_recruit_keeps_original_entity_and_restores_replays_bad_choice_rolls_back(self):
        g=self.game((LAST,'k35.kill',YETI),(SQUIRE,'k36.watch'),mode='wait');carrier=g.state.players[1].board[0]
        held=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==YETI)
        self.play(g,LAST,carrier);self.play(g,'k35.kill',carrier);self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g,'wait');before=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(q.player_id,q.id,('fail',)))
        self.assertEqual(g.snapshot(),before)
        for instance in(g,other):
            q=instance.state.pending_choice;instance.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(g.snapshot(),other.snapshot());self.assertIn(held,g.state.players[1].board)
        self.portable(g,'wait')
