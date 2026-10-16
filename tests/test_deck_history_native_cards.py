"""Cross-deck draws and real history consumers preserve original physical facts."""
from dataclasses import replace
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.deck_history_native_cards import load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,CastWhenDrawnSpec,
    EndTurn,Game,PlayCard,PlayerSetup,Rarity,Scenario,SelectChoice,TriggerSpec,Zone)
from hs_sim.engine.choose_one import GrantChooseBoth
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,Destroy,GainArmor,InvokeBehavior,
    RequestChoice,ReturnToHand,SetStats,Transform,ChangeControl)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import CostSpec,DamageKind,Keyword
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import Resolution,default_mechanics
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.model import TribeChangeSpec
from hs_sim.engine.zones import CardReference,DrawMatching,ModifyStoredCost
from hs_sim.targets import canonical_digest

TWILIGHT='END_010';CHRONOGOR='TIME_032';CHROMIE='TIME_103';EPOCH='TIME_714';ESHO='TLC_110'
ONE='k48.one';TWO='k48.two';THREE='k48.three';FOUR='k48.four';SIX='k48.six';DUAL='k48.dual';ALL='k48.all';UNKNOWN='k48.unknown';CWD='k48.cwd'


def registry():
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    for cid,cost,atk,hp,tribes in((ONE,1,2,3,('beast',)),(TWO,2,3,4,('dragon',)),(THREE,3,4,5,('undead',)),
        (FOUR,4,5,6,()),(SIX,6,7,8,('beast',)),(DUAL,2,3,4,('beast','dragon')),(ALL,3,4,5,('all',)),
        (UNKNOWN,2,3,4,None),('k48.dual_b',2,3,4,('dragon','undead')),('k48.dual_c',2,3,4,('beast','undead'))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=atk,health=hp,metadata=replace(meta,tribes=tribes)))
    def wait(c):
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('bad','Fail',(InvokeBehavior('k48.fail',c.source_id,c.player_id),))),c.source_id),)
    def price(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id==ONE)
        return(ModifyStoredCost(CardReference.capture(e),CostSpec(set_to=20),c.source_id),)
    bodies=dict(noop=lambda c:(),kill=lambda c:(Destroy(c.target_id,c.source_id),),
        ping=lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        both=lambda c:(GrantChooseBoth(c.target_id,c.source_id),),
        back=lambda c:(ReturnToHand(c.target_id),),transform=lambda c:(Transform(c.target_id,THREE),),
        steal=lambda c:(ChangeControl(c.target_id,c.player_id),),
        summon=lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(ONE),),SummonCause.capture(c)),),
        price=price,wait=wait,fail=lambda c:(AddToHand(c.player_id,'unknown.k48',c.source_id),),
        cast=lambda c:(Damage(c.state.players[c.player_id].hero_id,3,c.source_id,DamageKind.SPELL),),
        draw=lambda c:(DrawMatching(c.player_id,PoolQuery(),'skip',source_id=c.source_id,card_ids=(ONE,)),),
        foreign_fatigue=lambda c:(DrawMatching(2,PoolQuery(),'fatigue',2,source_id=c.source_id,owner_id=1),),
        invalid=lambda c:(DrawMatching(c.player_id,PoolQuery(),'skip',source_id=c.source_id,card_ids=('unknown.k48',)),))
    bodies['deck_tribe']=lambda c:(ChangeMinionTribes(CardReference.capture(next(c.state.entities[i]
        for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id==TWO)),TribeChangeSpec('set',('beast',)),c.source_id),)
    bodies['exclude_beast']=lambda c:(ChangeMinionTribes(CardReference.capture(next(c.state.entities[i]
        for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id==ALL)),TribeChangeSpec('remove',('beast',)),c.source_id),)
    for name,body in bodies.items():
        key='k48.'+name;r.register_behavior(key,body)
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=meta,
            requires_target=name in('kill','ping','both','back','transform','steal')))
    r.register_card(CardDefinition(CWD,CWD,CardType.SPELL,cost=0,on_play='k48.cast',
        keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec(replacement=True),metadata=meta))
    r.register_behavior('k48.cwd_wait',wait)
    r.register_card(CardDefinition('k48.cwd_wait','Wait drawn spell',CardType.SPELL,cost=0,on_play='k48.cwd_wait',
        keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec(replacement=True,choices='player'),metadata=meta))
    r.register_behavior('k48.watch',lambda c:wait(c)if c.event.player_id==c.player_id else())
    r.register_card(CardDefinition('k48.watch','Draw wait',CardType.MINION,health=10,metadata=meta,
        triggers=(TriggerSpec('card_drawn','k48.watch'),)))
    return r


class DeckHistoryNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,deck=(ONE,TWO,THREE,FOUR,SIX),board=(),enemy=(),enemy_hand=(),enemy_deck=(TWO,FOUR),active=1,cap=20):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,board=board,
            mana=80,max_mana=80,mana_cap=80,hand_cap=cap),PlayerSetup('HERO_08',hand=enemy_hand,deck=enemy_deck,
            board=enemy,mana=80,max_mana=80,mana_cap=80,hand_cap=cap)),active_player=active,seed=948),self.r)
    def eid(self,g,cid,zone='hand',p=1):
        s=g.state;return next(i for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def play(self,g,cid,target=None,*,p=1,branch=None):
        s=g.state;eid=self.eid(g,cid,p=p);g.apply(PlayCard(p,eid,target,
            position=len(s.players[p].board)if s.entities[eid].kind==CardType.MINION else None,branch_id=branch));return eid
    def cards(self,g,zone='hand',p=1):
        s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)]
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return other
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def finish_choices(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))

    def test_complete_five_roots_two_options_and_three_raw_enchantments(self):
        data=load_batch();self.assertEqual(len(data['cards']),7);self.assertEqual(len(data['enchantment_evidence']),3)
        self.assertEqual(sum(row['recipe']['root']for row in data['cards']),5)
        for row in data['cards']:
            raw=row['record'];card=self.r.card(raw['id']);self.assertEqual(canonical_digest(raw),row['record_sha256'])
            self.assertEqual(card.cost,0 if row['recipe']['choice_only']else raw['cost'])
        self.assertEqual(set(self.r.card(TWILIGHT).metadata.classes),{CardClass.DRUID,CardClass.PALADIN})
        self.assertEqual(data['deferred_real_dependency']['record']['id'],'TLC_520')

    def test_twilight_attack_branch_sets_both_boards_except_the_played_root(self):
        g=self.game((TWILIGHT,),board=(ONE,),enemy=(SIX,));source=self.play(g,TWILIGHT,branch='END_010a')
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(5,5))
        self.assertEqual(self.cards(g,'board')[0].attack,1);self.assertEqual(self.cards(g,'board',2)[0].attack,1)
        self.assertEqual(self.cards(g,'board',2)[0].health,8);self.portable(g)

    def test_twilight_health_branch_heals_damage_but_keeps_attack(self):
        g=self.game(('k48.ping',TWILIGHT),board=(SIX,),enemy=(TWO,));target=self.eid(g,SIX,'board')
        self.play(g,'k48.ping',target);source=self.play(g,TWILIGHT,branch='END_010b')
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(7,1))
        self.assertEqual(g.state.entities[source].health,5);self.assertEqual(self.cards(g,'board',2)[0].health,1)

    def test_twilight_choose_both_uses_one_normal_combined_body(self):
        g=self.game(('k48.both',TWILIGHT),board=(ONE,),enemy=(SIX,));self.play(g,'k48.both',self.eid(g,ONE,'board'))
        mana=g.state.players[1].mana;source=self.play(g,TWILIGHT,branch='END_010:combined')
        self.assertEqual(g.state.players[1].mana,mana-6)
        self.assertTrue(all((e.attack,e.health)==(1,1)for p in(1,2)for e in self.cards(g,'board',p)if e.id!=source));self.portable(g)

    def test_twilight_requires_legal_branch_and_options_are_not_physical_spells(self):
        g=self.game((TWILIGHT,));saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,TWILIGHT)
        self.assertEqual(g.snapshot(),saved)
        for cid in('END_010a','END_010b'):
            self.assertTrue(self.r.card(cid).choice_only);self.assertFalse(self.r.card(cid).hand_playable)

    def test_chronogor_draws_own_highest_then_gives_actual_own_lowest_cards(self):
        g=self.game((CHRONOGOR,));original={e.id:e.card_id for e in self.cards(g,'deck')};other=[e.id for e in self.cards(g,'deck',2)]
        source=self.play(g,CHRONOGOR);rows=[d for d in g.state.draw_history if d.source_id==source]
        self.assertEqual([(d.player_id,d.card_id)for d in rows],[(1,SIX),(1,FOUR),(2,ONE),(2,TWO)])
        self.assertTrue(all(d.entity_id in original for d in rows));self.assertEqual([e.id for e in self.cards(g,'deck',2)],other)
        self.assertEqual([e.card_id for e in self.cards(g,'deck')],[THREE]);self.portable(g)

    def test_chronogor_ranks_actual_deck_cost_not_printed_or_future_hand_cost(self):
        g=self.game(('k48.price',CHRONOGOR));one=self.eid(g,ONE,'deck');self.play(g,'k48.price');source=self.play(g,CHRONOGOR)
        rows=[d for d in g.state.draw_history if d.source_id==source];self.assertEqual(rows[0].entity_id,one)
        e=g.state.entities[one];self.assertEqual(quote_unselected_cost(g.state,g.registry,e).amount,20)

    def test_chronogor_rechecks_after_each_draw_and_stops_at_empty_source(self):
        g=self.game((CHRONOGOR,),deck=(ONE,TWO,THREE));source=self.play(g,CHRONOGOR)
        rows=[d for d in g.state.draw_history if d.source_id==source]
        self.assertEqual([(d.player_id,d.card_id)for d in rows],[(1,THREE),(1,TWO),(2,ONE)])
        self.assertTrue(all(d.outcome!='fatigue'for d in rows))

    def test_chronogor_empty_source_does_not_draw_from_opponents_deck(self):
        g=self.game((CHRONOGOR,),deck=());before=g._rng.getstate();self.play(g,CHRONOGOR)
        self.assertFalse(g.state.draw_history);self.assertEqual(g._rng.getstate(),before)
        self.assertEqual([e.card_id for e in self.cards(g,'deck',2)],[TWO,FOUR])

    def test_chronogor_overflow_burns_under_actual_recipient_without_switching_deck(self):
        g=self.game((CHRONOGOR,),enemy_hand=(FOUR,),cap=1);source=self.play(g,CHRONOGOR)
        rows=[d for d in g.state.draw_history if d.source_id==source and d.player_id==2]
        self.assertEqual([d.outcome for d in rows],['burned','burned'])
        self.assertTrue(all(g.state.entities[d.entity_id].controller==2 and g.state.entities[d.entity_id].zone==Zone.GRAVEYARD for d in rows))
        self.assertEqual([e.card_id for e in self.cards(g,'hand',2)],[FOUR]);self.portable(g)

    def test_foreign_drawn_spell_casts_for_recipient_and_replaces_from_recipient_deck(self):
        g=self.game((CHRONOGOR,),deck=(CWD,CWD,FOUR,SIX),enemy_deck=(TWO,THREE));source=self.play(g,CHRONOGOR);s=g.state
        roots=[d for d in s.draw_history if d.source_id==source and d.player_id==2]
        self.assertEqual([d.outcome for d in roots],['cast','cast']);self.assertEqual([e.card_id for e in self.cards(g,'hand',2)],[TWO,THREE])
        self.assertEqual(s.entities[s.players[2].hero_id].health,24);self.assertEqual(s.entities[s.players[1].hero_id].health,30)
        self.assertTrue(all(c.player_id==2 and c.origin=='draw'for c in s.cast_history))
        self.assertTrue(all(s.entities[d.entity_id].controller==2 for d in roots));self.portable(g)

    def test_foreign_drawn_spell_wait_restores_the_original_cast_and_following_lowest_draw(self):
        g=self.game((CHRONOGOR,),deck=('k48.cwd_wait',ONE,FOUR,SIX),enemy_deck=(TWO,));self.play(g,CHRONOGOR)
        self.assertEqual(g.state.pending_choice.player_id,2);g=self.portable(g);self.choose(g)
        self.assertEqual([e.card_id for e in self.cards(g,'hand',2)],[TWO,ONE]);self.portable(g)

    def test_foreign_draw_burned_cast_when_drawn_does_not_cast_or_replace(self):
        g=self.game((CHRONOGOR,),deck=(CWD,CWD,FOUR,SIX),enemy_hand=(ONE,),cap=1);source=self.play(g,CHRONOGOR)
        rows=[d for d in g.state.draw_history if d.source_id==source and d.player_id==2]
        self.assertEqual([d.outcome for d in rows],['burned','burned']);self.assertFalse(g.state.cast_history)

    def test_foreign_fatigue_profile_records_actual_recipient_without_drawing_its_deck(self):
        g=self.game(('k48.foreign_fatigue',),deck=());self.play(g,'k48.foreign_fatigue');s=g.state
        self.assertEqual([(d.player_id,d.outcome)for d in s.draw_history],[(2,'fatigue'),(2,'fatigue')])
        self.assertEqual(s.entities[s.players[2].hero_id].health,27);self.assertEqual([e.card_id for e in self.cards(g,'deck',2)],[TWO,FOUR]);self.portable(g)

    def test_foreign_draw_choice_failure_restores_whole_original_pending_boundary(self):
        g=self.game((CHRONOGOR,),deck=('k48.cwd_wait',ONE,FOUR,SIX));self.play(g,CHRONOGOR);saved=g.snapshot()
        with self.assertRaises((ResolutionError,ValueError)):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertIsNone(g.state.pending_choice)

    def test_foreign_draw_remains_private_to_recipient(self):
        g=self.game((CHRONOGOR,));self.play(g,CHRONOGOR)
        observer=g.for_player(1).observe()['observation'];opponent=next(p for p in observer['players']if p['id']==2)
        self.assertEqual(len(opponent['hand']),2);self.assertTrue(all(c['card_id']is None for c in opponent['hand']))
        recipient=g.for_player(2).observe()['observation'];own=next(p for p in recipient['players']if p['id']==2)
        self.assertEqual([c['card_id']for c in own['hand']],[ONE,TWO]);self.assertNotIn('draw_history',observer)

    def test_cross_controller_spell_movement_still_requires_an_original_draw_proof(self):
        g=self.game(deck=(CWD,));r=Resolution(g);e=r.state.entities[r.state.players[1].deck[0]];saved=g.snapshot()
        with self.assertRaises(ResolutionError):r.move(e,Zone.GRAVEYARD,controller_id=2)
        self.assertEqual(g.snapshot(),saved)

    def test_existing_draw_record_cannot_authorize_a_different_spell_or_card(self):
        g=self.game((CHRONOGOR,),deck=('k48.cwd_wait',ONE,FOUR,SIX));self.play(g,CHRONOGOR)
        r=Resolution(g);e=r.state.entities[r.state.players[1].deck[0]];saved=g.snapshot()
        with self.assertRaises(ResolutionError):r.move(e,Zone.GRAVEYARD,controller_id=2,draw_id=len(r.state.draw_history))
        self.assertEqual(g.snapshot(),saved)

    def test_new_draw_request_codec_preserves_owner_and_positive_identity_set(self):
        g=self.game();codec=FrameCodec(default_mechanics(),g.registry,origin_state=g.state)
        effect=DrawMatching(2,PoolQuery(),'skip',2,'lowest_cost',owner_id=1,card_ids=(ONE,TWO))
        self.assertEqual(codec.decode(codec.encode(effect)),effect)
        with self.assertRaises(ValueError):codec.encode(replace(effect,card_ids=('unknown.k48',)))
        with self.assertRaises(ValueError):DrawMatching(2,PoolQuery(),'skip',owner_id=3)

    def test_unknown_positive_draw_identity_is_an_error_and_rolls_back(self):
        g=self.game(('k48.invalid',));saved=g.snapshot()
        with self.assertRaises((ResolutionError,ValueError)):self.play(g,'k48.invalid')
        self.assertEqual(g.snapshot(),saved)

    def test_chromie_draws_existing_physical_copy_of_each_distinct_played_identity(self):
        g=self.game((ONE,'k48.noop','k48.kill'),board=(CHROMIE,),deck=(ONE,ONE,'k48.noop',TWO))
        original=self.eid(g,ONE,'deck');self.play(g,ONE);self.play(g,'k48.noop');source=self.eid(g,CHROMIE,'board');self.play(g,'k48.kill',source)
        rows=[d for d in g.state.draw_history if d.source_id==source]
        self.assertEqual([d.card_id for d in rows],[ONE,'k48.noop']);self.assertTrue(any(d.entity_id==original for d in rows)or original in g.state.players[1].deck)
        self.assertEqual(sum(e.card_id==ONE for e in self.cards(g,'deck')),1);self.portable(g)

    def test_chromie_repeated_plays_do_not_multiply_a_distinct_identity_budget(self):
        g=self.game((ONE,ONE,'k48.kill'),board=(CHROMIE,),deck=(ONE,ONE,ONE))
        self.play(g,ONE);self.play(g,ONE);source=self.eid(g,CHROMIE,'board');self.play(g,'k48.kill',source)
        self.assertEqual([d.card_id for d in g.state.draw_history if d.source_id==source],[ONE])
        self.assertEqual(len(self.cards(g,'deck')),2)

    def test_chromie_has_no_credit_for_initial_or_effect_summoned_minions(self):
        g=self.game(('k48.summon','k48.kill'),board=(CHROMIE,),deck=(ONE,ONE))
        self.play(g,'k48.summon');source=self.eid(g,CHROMIE,'board');self.play(g,'k48.kill',source)
        self.assertFalse([d for d in g.state.draw_history if d.source_id==source])

    def test_chromie_includes_its_own_actual_hand_play_but_not_created_copies(self):
        g=self.game((CHROMIE,'k48.kill'),deck=(CHROMIE,ONE));source=self.play(g,CHROMIE);self.play(g,'k48.kill',source)
        self.assertEqual([d.card_id for d in g.state.draw_history if d.source_id==source],[CHROMIE])

    def test_chromie_missing_matches_do_not_fatigue_or_create_cards(self):
        g=self.game((ONE,'k48.kill'),board=(CHROMIE,),deck=());self.play(g,ONE);source=self.eid(g,CHROMIE,'board')
        before=g._rng.getstate();self.play(g,'k48.kill',source)
        self.assertFalse(g.state.draw_history);self.assertEqual(g._rng.getstate(),before)

    def test_chromie_wait_preserves_frozen_identity_order_across_independent_restore(self):
        g=self.game((ONE,TWO,'k48.kill'),board=(CHROMIE,'k48.watch'),deck=(ONE,TWO,THREE))
        self.play(g,ONE);self.play(g,TWO);source=self.eid(g,CHROMIE,'board');self.play(g,'k48.kill',source)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g)
        self.assertEqual([d.card_id for d in g.state.draw_history if d.source_id==source],[ONE,TWO]);self.portable(g)

    def test_epoch_destroys_paid_minions_from_latest_closed_opponent_turn_only(self):
        g=self.game((EPOCH,),enemy=(FOUR,),enemy_hand=(ONE,TWO,'k48.summon'));g.apply(EndTurn(1))
        first=self.play(g,ONE,p=2);second=self.play(g,TWO,p=2);self.play(g,'k48.summon',p=2);g.apply(EndTurn(2))
        self.play(g,EPOCH);self.assertEqual(g.state.entities[first].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[second].zone,Zone.GRAVEYARD)
        self.assertCountEqual([e.card_id for e in self.cards(g,'board',2)],[FOUR,ONE]);self.portable(g)

    def test_epoch_keeps_minions_played_two_opponent_intervals_ago(self):
        g=self.game((EPOCH,),enemy_hand=(ONE,));g.apply(EndTurn(1));self.play(g,ONE,p=2);g.apply(EndTurn(2));self.cycle(g)
        self.play(g,EPOCH);self.assertEqual([e.card_id for e in self.cards(g,'board',2)],[ONE])

    def test_epoch_transformed_face_keeps_the_original_played_board_residence(self):
        g=self.game(('k48.transform',EPOCH),enemy_hand=(ONE,));g.apply(EndTurn(1));source=self.play(g,ONE,p=2);g.apply(EndTurn(2))
        self.play(g,'k48.transform',source);self.assertEqual(g.state.entities[source].card_id,THREE);self.play(g,EPOCH)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.portable(g)

    def test_epoch_can_destroy_a_now_friendly_original_opponents_play(self):
        g=self.game(('k48.steal',EPOCH),enemy_hand=(ONE,));g.apply(EndTurn(1));source=self.play(g,ONE,p=2);g.apply(EndTurn(2))
        self.play(g,'k48.steal',source);self.assertEqual(g.state.entities[source].controller,1);self.play(g,EPOCH)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)

    def test_epoch_does_not_target_a_hand_returned_original(self):
        g=self.game(('k48.back',EPOCH),enemy_hand=(ONE,));g.apply(EndTurn(1));source=self.play(g,ONE,p=2);g.apply(EndTurn(2))
        self.play(g,'k48.back',source);self.play(g,EPOCH);self.assertEqual(g.state.entities[source].zone,Zone.HAND)

    def test_epoch_no_opponent_history_has_no_effect_or_rng(self):
        g=self.game((EPOCH,),enemy=(ONE,));before=g._rng.getstate();self.play(g,EPOCH)
        self.assertEqual(g._rng.getstate(),before);self.assertEqual([e.card_id for e in self.cards(g,'board',2)],[ONE])

    def test_esho_common_current_deck_tribe_buffs_existing_hand_deck_and_board(self):
        g=self.game((ESHO,SIX),board=(ONE,),deck=(ONE,DUAL,ALL,'k48.noop'))
        hand=self.eid(g,SIX);source=self.play(g,ESHO);s=g.state
        self.assertEqual((s.entities[hand].attack,s.entities[hand].health),(9,10))
        self.assertEqual((s.entities[source].attack,s.entities[source].health),(5,7))
        self.assertEqual(self.cards(g,'board')[0].attack,4)
        self.assertEqual([e.attack for e in self.cards(g,'deck')if e.kind==CardType.MINION],[4,5,6]);self.portable(g)

    def test_esho_disjoint_deck_tribes_do_not_buff_any_zone(self):
        g=self.game((ESHO,SIX),board=(ONE,),deck=(ONE,TWO));self.play(g,ESHO)
        self.assertEqual(self.cards(g,'board')[0].attack,2);self.assertEqual(self.cards(g)[0].attack,7)

    def test_esho_empty_minion_deck_succeeds_without_inventing_a_tribe(self):
        for deck in((),('k48.noop',)):
            g=self.game((ESHO,SIX),deck=deck);self.play(g,ESHO);self.assertEqual(self.cards(g)[0].attack,9)

    def test_esho_tribeless_minion_makes_the_condition_false(self):
        g=self.game((ESHO,SIX),deck=(FOUR,));self.play(g,ESHO);self.assertEqual(self.cards(g)[0].attack,7)

    def test_esho_unknown_tribes_are_an_error_not_a_false_or_true_guess(self):
        g=self.game((ESHO,),deck=(UNKNOWN,));saved=g.snapshot()
        with self.assertRaises((ResolutionError,ValueError)):self.play(g,ESHO)
        self.assertEqual(g.snapshot(),saved)

    def test_esho_all_type_deck_succeeds_with_an_existing_common_type(self):
        g=self.game((ESHO,SIX),deck=(ALL,ALL));self.play(g,ESHO);self.assertEqual(self.cards(g)[0].attack,9)

    def test_esho_requires_a_common_type_not_only_pairwise_overlaps(self):
        g=self.game((ESHO,SIX),deck=(DUAL,'k48.dual_b','k48.dual_c'));self.play(g,ESHO)
        self.assertEqual(self.cards(g)[0].attack,7)

    def test_esho_uses_actual_current_tribes_after_a_real_deck_modification(self):
        g=self.game(('k48.deck_tribe',ESHO,SIX),deck=(ONE,TWO));self.play(g,'k48.deck_tribe');self.play(g,ESHO)
        self.assertEqual(self.cards(g)[0].attack,9);self.portable(g)

    def test_esho_respects_explicit_all_type_exclusions(self):
        g=self.game(('k48.exclude_beast',ESHO,SIX),deck=(ONE,ALL));self.play(g,'k48.exclude_beast');self.play(g,ESHO)
        self.assertEqual(self.cards(g)[0].attack,7)

    def test_esho_does_not_buff_later_generated_minions(self):
        g=self.game((ESHO,'k48.summon'),deck=(ONE,));self.play(g,ESHO);self.play(g,'k48.summon')
        self.assertEqual([(e.attack,e.health)for e in self.cards(g,'board')if e.card_id==ONE],[(2,3)])

    def test_esho_other_means_only_the_actual_source_is_excluded(self):
        g=self.game((ESHO,),board=(ESHO,),deck=(ONE,));old=self.eid(g,ESHO,'board');new=self.play(g,ESHO)
        self.assertEqual((g.state.entities[old].attack,g.state.entities[old].health),(7,9))
        self.assertEqual((g.state.entities[new].attack,g.state.entities[new].health),(5,7))

    def test_new_hand_deck_data_remains_out_of_opponent_projection(self):
        g=self.game((ESHO,SIX),deck=(ONE,));self.play(g,ESHO)
        obs=g.for_player(2).observe()['observation'];owner=next(p for p in obs['players']if p['id']==1)
        self.assertEqual(len(owner['hand']),1);self.assertEqual(owner['hand'][0]['card_id'],None)
        self.assertNotIn('play_history',obs);self.assertNotIn('successful_summon_history',obs);self.portable(g)
