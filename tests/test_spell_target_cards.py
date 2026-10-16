"""Five real target sequences, original references and causal batch rewards."""
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.spell_target_cards import load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec)
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, Freeze,
    GainArmor, InvokeBehavior, RequestChoice, Transform)
from hs_sim.engine.errors import IllegalAction, ResolutionError, SnapshotError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import DamageKind, SpellSchool, Zone
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_target_sequences import (DamageEnemyAndRandomOthers,
    FreezeRandomEnemyMinions, FreezeSelectedEnemy, RandomMinionDamageDrawDeaths)
from hs_sim.targets import canonical_digest

LAVA='TLC_227'; STASIS='TIME_611'; BARRAGE='TIME_855'; PRECISION='TIME_600'; CONSUME='CORE_CATA_007'
YETI='CORE_CS2_182'; ROOTS=(LAVA,STASIS,BARRAGE,PRECISION,CONSUME)


def registry():
    r=build_registry(); meta=replace(r.card(YETI).metadata,collectible=False,tribes=(),deck_identity=None)
    for key,health,extra in (
        ('low',3,{}),('small',2,{}),('big',9,{}),('huge',50,{}),
        ('bonus',2,dict(spell_damage=1)),('reborn',3,dict(keywords=(Keyword.REBORN,))),
        ('shield',9,dict(keywords=(Keyword.DIVINE_SHIELD,))),
        ('immune',9,dict(keywords=(Keyword.IMMUNE,))),
        ('unfreezable',9,dict(keywords=(Keyword.CANT_BE_FROZEN,))),
        ('sleep',9,dict(dormant_turns=2)),('bomb',3,dict(deathrattle='h40.bomb')),
    ):
        r.register_card(CardDefinition('h40.'+key,key,CardType.MINION,attack=1,health=health,metadata=meta,**extra))
    r.register_behavior('h40.fail',lambda c:(AddToHand(1,'missing.h40'),))
    def bomb(c):
        ids=c.state.players[3-c.player_id].board
        return (Destroy(ids[0],c.source_id),) if ids else ()
    r.register_behavior('h40.bomb',bomb)
    def options(c,extra=()):
        return RequestChoice(1,(ChoiceOption('ok','Continue',()),*extra,
            ChoiceOption('bad','Rollback',(InvokeBehavior('h40.fail',c.source_id,1),))),c.source_id)
    def wait_damage(c):
        source=c.state.entities.get(c.event.source_id)
        return (options(c),) if source is not None and source.card_id==LAVA else ()
    def wait_freeze(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=STASIS:return ()
        remaining=[e for e in c.state.players[2].board if e!=c.event.target_id]
        return (Transform(remaining[0],YETI),options(c)) if remaining else ()
    def commit(c):
        source=c.state.entities.get(c.event.source_id)
        return (AddToHand(1,YETI,c.source_id),options(c)) if source is not None and source.card_id==PRECISION else ()
    for key,event,body in (('wait_damage','damage_dealt',wait_damage),('wait_freeze','frozen',wait_freeze),
                            ('commit','card_committed',commit)):
        r.register_behavior('h40.'+key,body)
        r.register_card(CardDefinition('h40.'+key,key,CardType.MINION,health=9,metadata=meta,
            triggers=(TriggerSpec(event,'h40.'+key),)))
    def mixed(c):
        request=DamageEnemyAndRandomOthers(c.player_id,c.cast.id,c.source_id,
            SourceAllocationFact.capture(c.state,c.state.entities[c.target_id]),3,2,2)
        return (options(c,(ChoiceOption('replace','Replace original',(Transform(c.target_id,YETI),)),)),request)
    def consume(c):
        return (options(c),RandomMinionDamageDrawDeaths(c.player_id,c.cast.id,c.source_id,3,2))
    def late(c):
        return (RandomMinionDamageDrawDeaths(c.player_id,c.cast.id,c.source_id,3,2),
            InvokeBehavior('h40.fail',c.source_id,c.player_id))
    scripts={
        'noop':lambda c:(), 'mixed':mixed, 'consume':consume, 'late':late,
        'wrong_cast':lambda c:(FreezeRandomEnemyMinions(c.player_id,c.cast.id+1,c.source_id,2),),
        'freeze':lambda c:(Freeze(c.target_id,c.source_id),),
        'auto_precision':lambda c:(CastSpell(1,PRECISION,c.source_id,c.target_id,targeting='explicit'),),
        'auto_lava':lambda c:(CastSpell(1,LAVA,c.source_id),),
    }
    for key,body in scripts.items():
        r.register_behavior('h40.'+key,body)
        r.register_card(CardDefinition('h40.'+key,key,CardType.SPELL,on_play='h40.'+key,
            requires_target=key in ('mixed','freeze','auto_precision'),metadata=meta))
    return r


class SpellTargetCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),enemy=(),deck=(YETI,)*6,seed=611):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*6,mana=30,max_mana=30,mana_cap=30)),seed=seed),self.registry)
    def play(self,g,cid,target=None):
        s=g.state;eid=next(i for i in s.players[1].hand if s.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target));return eid
    def choose(self,g,key='ok'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def results(self,g,cid):
        return [health_result(e) for e in g.events if e.kind=='health_resolved'
            and health_result(e).source_card_id==cid]
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        return other

    def test_complete_five_faces_schools_and_runes(self):
        rows=load_batch()['cards'];self.assertEqual({r['record']['id']for r in rows},set(ROOTS))
        for row in rows:
            raw=row['record'];card=self.registry.card(raw['id'])
            self.assertEqual(canonical_digest(raw),row['record_sha256'])
            self.assertEqual(card.cost,raw['cost']);self.assertEqual(card.kind,CardType.SPELL)
        self.assertEqual(self.registry.card(LAVA).spell_school,SpellSchool.FIRE)
        self.assertEqual(self.registry.card(STASIS).spell_school,SpellSchool.FROST)
        self.assertEqual(self.registry.card(BARRAGE).spell_school,SpellSchool.ARCANE)
        self.assertEqual(self.registry.card(STASIS).metadata.runes.frost,2)
        self.assertEqual(self.registry.card(CONSUME).metadata.runes.blood,2)

    def test_lava_rechecks_lowest_after_each_hit_and_owes_one_overload(self):
        g=self.game((LAVA,),enemy=('h40.low','h40.big'));s=g.state;low,big=s.players[2].board
        self.play(g,LAVA);s=g.state;rows=self.results(g,LAVA)
        self.assertEqual([r.target_id for r in rows],[low,low,big])
        self.assertEqual(s.entities[big].health,7);self.assertEqual(s.players[1].overload_owed,1)
        self.assertEqual(s.players[1].mana,27);self.assertEqual(len({r.batch_id for r in rows}),3)

    def test_lava_enemy_hero_eligible_and_spell_bonus_each_wave(self):
        g=self.game((LAVA,),board=('h40.bonus',));s=g.state;hero=s.players[2].hero_id
        self.play(g,LAVA);rows=self.results(g,LAVA)
        self.assertEqual([r.target_id for r in rows],[hero]*3)
        self.assertEqual([r.spell_bonus for r in rows],[1]*3)
        self.assertEqual(g.state.entities[hero].health,21)

    def test_lava_tie_random_eligible_all_and_overload_next_owner_turn(self):
        g=self.game((LAVA,),enemy=(YETI,YETI));before=g._rng.getstate();self.play(g,LAVA)
        self.assertNotEqual(g._rng.getstate(),before)
        self.assertEqual(sum(e.kind=='random_choice' for e in g.events),3)
        s=g.state;self.assertEqual(sorted(s.entities[i].health for i in s.players[2].board),[5])
        g.apply(EndTurn(1));g.apply(EndTurn(2));s=g.state
        self.assertEqual((s.players[1].overload_owed,s.players[1].overload_locked),(0,1))

    def test_lava_wait_each_wave_portable_rollback_and_pay_once(self):
        g=self.game((LAVA,),board=('h40.wait_damage',),enemy=('h40.huge',))
        self.play(g,LAVA);self.assertIsNotNone(g.state.pending_choice);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g)
        for n in range(3):
            for current in (g,other):
                self.assertIsNotNone(current.state.pending_choice)
                self.assertEqual(current.state.players[1].overload_owed,0)
                self.choose(current)
            self.assertEqual(g.snapshot(),other.snapshot())
        s=g.state;self.assertIsNone(s.pending_choice);self.assertEqual(s.players[1].mana,27)
        self.assertEqual(s.players[1].overload_owed,1)
        self.assertEqual(s.entities[s.players[2].hero_id].health,24)

    def test_stasis_small_pool_no_rng_and_dormant_not_selected(self):
        for enemy in ((),('h40.big',),('h40.big','h40.sleep')):
            with self.subTest(enemy=enemy):
                g=self.game((STASIS,),enemy=enemy);s=g.state;before=g._rng.getstate()
                self.play(g,STASIS,s.players[2].hero_id);s=g.state
                self.assertEqual(g._rng.getstate(),before);self.assertEqual(s.entities[s.players[2].hero_id].health,27)
                self.assertEqual(sum(s.entities[i].frozen for i in s.players[2].board),int(bool(enemy)))

    def test_stasis_requeries_after_reborn_and_does_not_freeze_dead_original(self):
        g=self.game((STASIS,),enemy=('h40.reborn','h40.big'));original=g.state.players[2].board[0]
        self.play(g,STASIS,original);s=g.state
        self.assertEqual(s.entities[original].zone,Zone.GRAVEYARD)
        self.assertEqual(len(s.players[2].board),2)
        self.assertTrue(all(s.entities[i].frozen for i in s.players[2].board))
        self.assertEqual([s.entities[i].health for i in s.players[2].board],[1,9])

    def test_stasis_samples_two_distinct_current_enemies(self):
        g=self.game((STASIS,),enemy=('h40.big',)*4);s=g.state;before=g._rng.getstate()
        self.play(g,STASIS,s.players[1].hero_id);s=g.state
        self.assertNotEqual(g._rng.getstate(),before)
        frozen=[i for i in s.players[2].board if s.entities[i].frozen]
        self.assertEqual(len(frozen),2)
        self.assertEqual(len({e.target_id for e in g.events if e.kind=='random_choice'}),2)

    def test_stasis_immune_freezes_and_cannot_be_frozen_remains_candidate(self):
        g=self.game((STASIS,),enemy=('h40.immune','h40.unfreezable'));s=g.state
        immune,blocked=s.players[2].board
        self.play(g,STASIS,s.players[1].hero_id);s=g.state
        self.assertTrue(s.entities[immune].frozen);self.assertFalse(s.entities[blocked].frozen)
        self.assertEqual({e.target_id for e in g.events if e.kind=='random_choice'},{immune,blocked})
        g=self.game(('h40.freeze',STASIS),enemy=('h40.big','h40.unfreezable'));s=g.state
        already=s.players[2].board[0];self.play(g,'h40.freeze',already)
        deadline=g.state.entities[already].frozen_until_owner_turn
        self.play(g,STASIS,s.players[1].hero_id)
        self.assertEqual(g.state.entities[already].frozen_until_owner_turn,deadline)

    def test_stasis_selected_reference_does_not_rebind_transformed_second_target(self):
        g=self.game((STASIS,),board=('h40.wait_freeze',),enemy=('h40.big','h40.big'));s=g.state
        self.play(g,STASIS,s.players[2].hero_id);self.assertIsNotNone(g.state.pending_choice)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g)
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());s=g.state
        self.assertEqual(sum(s.entities[i].frozen for i in s.players[2].board),1)
        self.assertEqual(sum(e.kind=='frozen' for e in g.events),1)
        self.assertEqual(sum(e.kind=='random_choice' for e in g.events),2)

    def test_stasis_thaws_at_enemy_owner_end_after_lost_opportunity(self):
        g=self.game((STASIS,),enemy=('h40.big',));s=g.state;target=s.players[2].board[0]
        self.play(g,STASIS,s.players[2].hero_id);g.apply(EndTurn(1))
        self.assertTrue(g.state.entities[target].frozen);g.apply(EndTurn(2))
        self.assertFalse(g.state.entities[target].frozen)

    def test_barrage_primary_and_others_share_one_damage_batch(self):
        g=self.game((BARRAGE,),enemy=('h40.big','h40.big'));s=g.state;hero=s.players[2].hero_id
        self.play(g,BARRAGE,hero);s=g.state;rows=self.results(g,BARRAGE)
        self.assertEqual([r.damage_dealt for r in rows],[3,2,2]);self.assertEqual(len({r.batch_id for r in rows}),1)
        self.assertEqual(s.entities[hero].health,27)
        self.assertEqual([s.entities[i].health for i in s.players[2].board],[7,7])

    def test_barrage_bonus_each_packet_and_original_primary_excluded(self):
        g=self.game((BARRAGE,),board=('h40.bonus',),enemy=('h40.big',)*4);s=g.state;target=s.players[2].board[0]
        self.play(g,BARRAGE,target);rows=self.results(g,BARRAGE)
        self.assertEqual([r.spell_bonus for r in rows],[1,1,1])
        self.assertEqual(len({r.target_id for r in rows}),3)
        self.assertEqual([r.damage_dealt for r in rows],[4,3,3])
        self.assertTrue(all(r.target_id not in s.players[1].board for r in rows))

    def test_barrage_primary_reborn_is_not_selected_again(self):
        g=self.game((BARRAGE,),enemy=('h40.reborn',));s=g.state;original=s.players[2].board[0]
        self.play(g,BARRAGE,original);s=g.state;rows=self.results(g,BARRAGE)
        self.assertEqual([r.target_id for r in rows],[original,s.players[2].hero_id])
        self.assertEqual(s.entities[s.players[2].board[0]].health,1)
        self.assertEqual(s.entities[s.players[2].hero_id].health,28)

    def test_barrage_shield_and_friendly_primary_rejected_atomically(self):
        g=self.game((BARRAGE,),enemy=('h40.shield',));s=g.state;before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,BARRAGE,s.players[1].hero_id)
        self.assertEqual(g.snapshot(),before)
        self.play(g,BARRAGE,s.players[2].board[0]);rows=self.results(g,BARRAGE)
        self.assertEqual([r.damage_dealt for r in rows],[0,2])

    def test_mixed_request_waiting_codec_original_primary_and_rollback(self):
        g=self.game(('h40.mixed',),enemy=('h40.big','h40.big'));s=g.state
        self.play(g,'h40.mixed',s.players[2].board[0]);before=g.snapshot()
        self.assertIn('DamageEnemyAndRandomOthers',json.dumps(before))
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g)
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual([r.damage_dealt for r in self.results(g,'h40.mixed')],[3,2,2])

    def test_mixed_request_expired_primary_skips_whole_request_without_resample(self):
        g=self.game(('h40.mixed',),enemy=('h40.big','h40.big'));s=g.state
        self.play(g,'h40.mixed',s.players[2].board[0]);before=g._rng.getstate();self.choose(g,'replace')
        self.assertEqual(g._rng.getstate(),before);self.assertFalse(self.results(g,'h40.mixed'))

    def test_precision_uses_odd_original_hand_middle_including_sole_card(self):
        cases=((0,1,5),(0,2,3),(1,2,3),(0,3,3),(1,3,5),(2,3,3),(2,5,5))
        for index,size,damage in cases:
            with self.subTest(index=index,size=size):
                hand=['h40.noop']*size;hand[index]=PRECISION;g=self.game(tuple(hand));s=g.state
                self.play(g,PRECISION,s.players[2].hero_id)
                self.assertEqual(g.state.entities[s.players[2].hero_id].health,30-damage)

    def test_precision_commit_wait_and_hand_change_keep_original_middle(self):
        g=self.game(('h40.noop',PRECISION,'h40.noop'),board=('h40.commit',));s=g.state
        self.play(g,PRECISION,s.players[2].hero_id);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(g.state.players[1].hand),3);other=self.portable(g)
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[s.players[2].hero_id].health,25)

    def test_automatic_precision_does_not_borrow_outer_sole_hand_record(self):
        g=self.game(('h40.auto_precision',));s=g.state;self.play(g,'h40.auto_precision',s.players[2].hero_id)
        self.assertEqual(g.state.entities[s.players[2].hero_id].health,27)
        self.assertEqual(len(g.state.cast_history),2)

    def test_automatic_lava_still_applies_all_waves_and_one_overload(self):
        g=self.game(('h40.auto_lava',));s=g.state;self.play(g,'h40.auto_lava')
        self.assertEqual(g.state.entities[s.players[2].hero_id].health,24)
        self.assertEqual(g.state.players[1].overload_owed,1)

    def test_consume_zero_one_two_direct_deaths_and_empty_pool_rng(self):
        for enemy,draws in (((),0),(('h40.big',),0),(('h40.small',),1),(('h40.small','h40.low'),2)):
            with self.subTest(enemy=enemy):
                g=self.game((CONSUME,),enemy=enemy);before=g._rng.getstate();self.play(g,CONSUME);s=g.state
                self.assertEqual(len(s.draw_history),draws);self.assertEqual(len(s.players[1].hand),draws)
                self.assertEqual(g._rng.getstate(),before)
                if enemy:self.assertEqual(len({r.batch_id for r in self.results(g,CONSUME)}),1)

    def test_consume_samples_without_replacement_bonus_and_dormant_excluded(self):
        g=self.game((CONSUME,),board=('h40.bonus',),enemy=('h40.low',)*3+('h40.sleep',));self.play(g,CONSUME)
        rows=self.results(g,CONSUME);s=g.state
        self.assertEqual(len({r.target_id for r in rows}),2);self.assertEqual([r.spell_bonus for r in rows],[1,1])
        self.assertEqual(len(s.draw_history),2)
        self.assertFalse(any(r.target_card_id=='h40.sleep' for r in rows))

    def test_consume_protection_and_reborn_count_only_original_corpses(self):
        g=self.game((CONSUME,),enemy=('h40.shield','h40.immune'));self.play(g,CONSUME)
        self.assertFalse(g.state.draw_history)
        g=self.game((CONSUME,),enemy=('h40.reborn','h40.small'));self.play(g,CONSUME);s=g.state
        self.assertEqual(len(s.draw_history),2);self.assertEqual(len(s.players[2].board),1)
        self.assertEqual(s.entities[s.players[2].board[0]].health,1)

    def test_consume_unrelated_deathrattle_destroy_not_rewarded(self):
        g=self.game((CONSUME,),board=('h40.big',),enemy=('h40.bomb','h40.small'));self.play(g,CONSUME);s=g.state
        self.assertEqual(len(s.death_history),3);self.assertEqual(len(s.draw_history),2)
        self.assertFalse(s.players[1].board)

    def test_consume_request_waiting_codec_restore_rollback_and_replay(self):
        g=self.game(('h40.consume',),enemy=('h40.low','h40.low','h40.big'));self.play(g,'h40.consume')
        before=g.snapshot();self.assertIn('RandomMinionDamageDrawDeaths',json.dumps(before))
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g)
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.results(g,'h40.consume')),2)

    def test_consume_late_error_rolls_back_health_draws_rng_and_knowledge(self):
        g=self.game(('h40.late',),enemy=('h40.small','h40.small','h40.small'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'h40.late')
        self.assertEqual(g.snapshot(),before)

    def test_wrong_cast_request_rejected_without_committing_action(self):
        g=self.game(('h40.wrong_cast',),enemy=('h40.big',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'h40.wrong_cast')
        self.assertEqual(g.snapshot(),before)

    def test_requests_reject_boolean_negative_and_wrong_original_target_shapes(self):
        for constructor,args in ((FreezeRandomEnemyMinions,(1,1,1,True)),
            (RandomMinionDamageDrawDeaths,(1,1,1,-1,2)),(RandomMinionDamageDrawDeaths,(1,1,1,3,0))):
            with self.subTest(constructor=constructor,args=args):
                with self.assertRaises(ValueError):constructor(*args)
        g=self.game(enemy=('h40.big',));s=g.state
        with self.assertRaises(ValueError):FreezeSelectedEnemy(1,1,1,MinionReference.capture(s.entities[s.players[1].hero_id]))
        with self.assertRaises(ValueError):DamageEnemyAndRandomOthers(1,1,1,
            SourceAllocationFact.capture(s,s.entities[s.players[1].hero_id]),3,2,2)

    def test_waiting_projection_keeps_private_requests_candidates_and_rng_hidden(self):
        g=self.game(('h40.mixed',),enemy=('h40.big',)*4);s=g.state
        self.play(g,'h40.mixed',s.players[2].board[0])
        for player in (1,2):
            visible=json.dumps(g.observe(player))+json.dumps(g.player_events(player))
            for token in ('DamageEnemyAndRandomOthers','SourceAllocationFact','rng_state','cast_history','candidates'):
                self.assertNotIn(token,visible)

    def test_previous_core_version_is_not_accepted_as_current(self):
        g=self.game();saved=g.snapshot();saved['mechanics_version']['version']='core-effects-v341'
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())


if __name__=='__main__':unittest.main()
