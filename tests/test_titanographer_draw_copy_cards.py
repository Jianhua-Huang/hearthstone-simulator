"""Actual Osk draw/copy branches through shared physical delivery boundaries."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.titanographer_draw_copy_cards import DRAW, COPY, ROOT, load_batch
from hs_sim.engine import (CardDefinition, CardType, CostSpec, Game, IllegalAction, Keyword,
    PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.crafted_faces import CraftedMinionRecipe
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, CopyMinion, Damage, Draw,
    GainArmor, InvokeBehavior, RequestChoice, Silence)
from hs_sim.engine.hand_upgrades import BuffStoredCard, SetStoredMinionStats
from hs_sim.engine.physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, MoveCard

P='fixture.osk.draw_copy.'; UNIT=P+'unit'; WATCH=P+'watch'; SPELL=P+'spell'
GHOUL=CraftedMinionRecipe('CATA_470t1','TIME_045','CORE_OG_149').card_id


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r=build_registry()
    r.register_behavior(P+'cry',lambda c:(GainArmor(c.player_id,7),))
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,cost=8,attack=4,health=7,battlecry=P+'cry'))
    r.register_card(CardDefinition(P+'elusive','Elusive body',CardType.MINION,attack=4,health=7,keywords=(Keyword.ELUSIVE,)))
    r.register_card(CardDefinition(P+'stealth','Stealth body',CardType.MINION,attack=4,health=7,keywords=(Keyword.STEALTH,)))
    r.register_behavior(P+'noop',lambda c:())
    r.register_card(CardDefinition(SPELL,SPELL,CardType.SPELL,on_play=P+'noop'))
    def fail(c): raise ResolutionError('Osk draw/copy reaction fixture failure')
    r.register_behavior(P+'fail',fail)
    def prep(c):
        refs=tuple(CardReference.capture(c.state.entities[i])for i in c.state.players[c.player_id].deck)
        return tuple(BuffStoredCard(ref,3,4,c.source_id,cost=CostSpec(delta=-5))for ref in refs)
    scripts={'prep':prep,'buff':lambda c:(Buff(c.target_id,3,4,c.source_id),Damage(c.target_id,3,c.source_id)),
        'silence':lambda c:(Silence(c.target_id),)}
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name!='prep'else None))
    def watch(c):
        event=c.event; target=c.state.entities.get(event.target_id)
        if event.kind=='card_drawn':
            source=c.state.entities.get(event.source_id)
            if source is None or source.card_id!=DRAW:return ()
            if mode=='draw_observe':return(GainArmor(c.player_id,target.attack*100+target.max_health),)
            if mode not in ('draw_wait','cycle')or c.state.entities[c.state.players[c.player_id].hero_id].armor:return ()
            ref=CardReference.capture(target)
            tail=(MoveCard(ref,c.player_id,Zone.DECK,'top',source_id=c.source_id),Draw(c.player_id,1,c.source_id))if mode=='cycle'else ()
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),*tail)),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        if event.kind=='stored_card_stats_set' and mode=='set_fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if event.kind=='minion_summoned'and target is not None and target.origin_entity_id is not None:
            if mode=='copy_observe':return(GainArmor(c.player_id,target.attack*100+target.max_health*10+target.damage),)
            if mode=='copy_fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode=='copy_wait':return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,triggers=tuple(
        TriggerSpec(k,P+'watch')for k in ('card_drawn','stored_card_stats_set','minion_summoned'))))
    r.validate();return r


class OskDrawCopyTests(unittest.TestCase):
    def game(self,hand=(),deck=(),board=(),enemy=(),mode='normal',active=1,cap=10):
        players=tuple(PlayerSetup('HERO_08',hand=hand if p==active else(),deck=deck if p==active else(),
            board=(((WATCH,)if mode!='normal'else())+board)if p==active else enemy,
            max_mana=10,mana=10,hand_cap=cap)for p in (1,2))
        return Game.from_scenario(Scenario(players,active_player=active,seed=303),fixture(mode))
    def play(self,g,card,target=None):
        p=g.state.active_player; eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==card)
        g.apply(PlayCard(p,eid,target));return eid
    def hand(self,g,p=None):return[g.state.entities[i]for i in g.state.players[p or g.state.active_player].hand]
    def body(self,g,cid=UNIT,p=None):
        return next(g.state.entities[i]for i in g.state.players[p or g.state.active_player].board if g.state.entities[i].card_id==cid)
    def copy(self,g):
        return next(g.state.entities[i]for i in reversed(g.state.players[g.state.active_player].board)
            if g.state.entities[i].origin_entity_id is not None)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode='normal'):
        s=g.snapshot();r=fixture.__wrapped__(mode)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        return Game.from_snapshot(s,r)
    def stats(self,g,e,attack,health,cost):
        e=g.state.entities[e.id]
        self.assertEqual((e.attack,e.max_health,quote_cost(g.state,g.registry,e).amount),(attack,health,cost))

    def test_full_original_forms_and_primary_faces_retain_source_pins_and_native_root(self):
        d=load_batch();r=fixture()
        self.assertEqual(len(d['official_observations']),6);self.assertIn(ROOT,r.cards)
        for cid in (DRAW,COPY):
            c=r.card(cid);self.assertEqual((c.cost,c.attack,c.health),(6,6,6))
            self.assertFalse(c.metadata.collectible);self.assertNotIn(Keyword.TITAN,c.keywords)
        self.assertEqual(r.card(COPY).targeting.relation,'any')

    def test_two_actual_original_minions_are_set_without_touching_preexisting_hand_or_spells(self):
        g=self.game((DRAW,UNIT),deck=(SPELL,UNIT,SPELL,UNIT));original=set(g.state.players[1].deck)
        prior=self.hand(g)[1];self.play(g,DRAW)
        results=[e for e in self.hand(g)if e.id in original]
        self.assertEqual(len(results),2);self.assertEqual(len({e.id for e in results}),2)
        for e in results:self.stats(g,e,2,2,2)
        self.stats(g,prior,4,7,8);self.assertEqual(g.state.players[1].mana,4)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[SPELL,SPELL])
        self.assertEqual(len(g.state.draw_history),2)

    def test_set_layers_override_existing_buffs_and_costs_without_rewriting_printed_body(self):
        g=self.game((P+'prep',DRAW),deck=(UNIT,UNIT));self.play(g,P+'prep');self.play(g,DRAW)
        for e in self.hand(g):
            self.stats(g,e,2,2,2);self.assertEqual((e.base_attack,e.base_health,e.base_cost),(4,7,8))
        eid=self.play(g,UNIT);e=g.state.entities[eid]
        self.assertEqual((e.attack,e.max_health),(2,2));self.assertEqual(g.state.players[1].mana,2)

    def test_empty_matching_slots_do_not_fatigue_and_burned_minions_get_no_hand_reward(self):
        g=self.game((DRAW,),deck=(SPELL,));self.play(g,DRAW)
        self.assertEqual(len(g.state.draw_history),0);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)
        g=self.game((DRAW,SPELL),deck=(UNIT,UNIT),cap=2);ids=set(g.state.players[1].deck);self.play(g,DRAW)
        kept=[g.state.entities[i]for i in ids if i in g.state.players[1].hand]
        burned=[g.state.entities[i]for i in ids if i not in g.state.players[1].hand]
        self.assertEqual((len(kept),len(burned)),(1,1));self.stats(g,kept[0],2,2,2)
        self.assertFalse(any(x.label=='stored_stats_set'for x in burned[0].enchantments))

    def test_draw_observers_see_original_values_before_the_existing_whole_group_reward(self):
        g=self.game((DRAW,),deck=(UNIT,UNIT),mode='draw_observe');self.play(g,DRAW)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,814)
        for e in self.hand(g):self.stats(g,e,2,2,2)

    def test_departed_and_redrawn_original_is_not_rebound_to_old_arrival(self):
        g=self.game((DRAW,),deck=(UNIT,UNIT),mode='cycle');self.play(g,DRAW)
        original=g.state.pending_choice;self.assertIsNotNone(original)
        first=g.state.draw_history[0].entity_id;self.choose(g)
        self.stats(g,g.state.entities[first],4,7,8)
        other=next(e for e in self.hand(g)if e.id!=first);self.stats(g,other,2,2,2)
        self.assertEqual(len(g.state.draw_history),3)

    def test_waiting_original_draw_restores_independently_and_failed_resume_preserves_boundary(self):
        g=self.game((DRAW,),deck=(UNIT,UNIT),mode='draw_wait');self.play(g,DRAW)
        saved=g.snapshot();restored=self.portable(g,'draw_wait')
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot())
        for e in self.hand(g):self.stats(g,e,2,2,2)

    def test_new_private_set_event_and_draw_material_are_owner_only(self):
        g=self.game((DRAW,),deck=(UNIT,UNIT));self.play(g,DRAW)
        owner=json.dumps(g.for_player(1).observe(),sort_keys=True);enemy=json.dumps(g.for_player(2).observe(),sort_keys=True)
        self.assertIn(UNIT,owner);self.assertNotIn(UNIT,enemy)
        self.assertNotIn('stored_card_stats_set',enemy);self.assertNotIn('set_stats_cost_all',enemy)
        self.assertEqual(len([e for e in g.events if e.kind=='stored_card_stats_set']),2)

    def test_actual_copy_accepts_either_side_and_never_replays_target_battlecry(self):
        for side in (1,2):
            with self.subTest(side=side):
                g=self.game((COPY,),board=(UNIT,)if side==1 else(),enemy=(UNIT,)if side==2 else())
                source=self.body(g,p=side);self.play(g,COPY,source.id);copied=self.copy(g)
                self.assertEqual((copied.attack,copied.max_health,copied.origin_entity_id),(6,9,source.id))
                self.assertEqual((copied.owner,copied.controller),(1,1));self.assertNotEqual(copied.id,source.id)
                source=g.state.entities[source.id]
                self.assertEqual((source.attack,source.max_health),(4,7));self.assertEqual(g.state.players[1].mana,4)
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)

    def test_current_local_copy_and_plus_two_are_visible_before_first_entry_observer(self):
        g=self.game((P+'buff',COPY),board=(UNIT,),mode='copy_observe');source=self.body(g)
        self.play(g,P+'buff',source.id);self.play(g,COPY,source.id);copied=self.copy(g)
        self.assertEqual((copied.attack,copied.max_health,copied.damage),(9,13,3))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1033)
        source=g.state.entities[source.id]
        self.assertEqual((source.attack,source.max_health,source.damage),(7,11,3))
        self.assertFalse({a.id for a in source.enchantments}&{a.id for a in copied.enchantments})

    def test_titan_hero_and_enemy_stealth_are_illegal_but_elusive_minion_is_legal(self):
        g=self.game((COPY,),enemy=('TTN_903',P+'stealth',P+'elusive'))
        for target in (self.body(g,'TTN_903',2).id,self.body(g,P+'stealth',2).id,g.state.players[2].hero_id):
            saved=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,COPY,target)
            self.assertEqual(g.snapshot(),saved)
        self.play(g,COPY,self.body(g,P+'elusive',2).id);self.assertIn(Keyword.ELUSIVE,self.copy(g).keywords)
        g=self.game((COPY,),enemy=('TTN_903',));self.play(g,COPY);self.assertEqual(len(g.state.players[1].board),1)

    def test_full_board_copy_has_no_allocation_or_reward_to_original(self):
        g=self.game((COPY,),board=(UNIT,)*6);target=self.body(g);next_id=g.state.next_entity_id
        self.play(g,COPY,target.id);self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(g.state.next_entity_id,next_id);self.assertEqual((target.attack,target.max_health),(4,7))
        self.assertFalse(g.state.card_summon_history[-1].deliveries)

    def test_actual_crafted_non_titan_copy_preserves_recipe_native_keywords_and_summed_base(self):
        g=self.game((COPY,),board=(GHOUL,));source=self.body(g,GHOUL);self.play(g,COPY,source.id);copied=self.copy(g)
        self.assertEqual(copied.components,source.components)
        self.assertEqual((copied.base_attack,copied.base_health),(source.base_attack,source.base_health))
        self.assertEqual((copied.attack,copied.max_health),(source.attack+2,source.max_health+2))
        self.assertIn(Keyword.POISONOUS,copied.keywords)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)
        self.portable(g)

    def test_waiting_copy_retains_pre_entry_grant_and_complete_material_after_restore(self):
        g=self.game((COPY,),board=(UNIT,),mode='copy_wait');self.play(g,COPY,self.body(g).id)
        copied=self.copy(g);self.assertEqual((copied.attack,copied.max_health),(6,9))
        restored=self.portable(g,'copy_wait');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_failed_stat_or_copy_reaction_rolls_back_payment_physical_material_and_rng(self):
        for card,mode in ((DRAW,'set_fail'),(COPY,'copy_fail')):
            with self.subTest(card=card):
                g=self.game((card,),deck=(UNIT,UNIT),board=(UNIT,),mode=mode);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,card,self.body(g).id if card==COPY else None)
                self.assertEqual(g.snapshot(),saved)

    def test_second_actor_owns_both_original_draw_reward_and_current_copy(self):
        g=self.game((DRAW,COPY),deck=(UNIT,UNIT),board=(UNIT,),active=2)
        self.play(g,DRAW)
        for e in self.hand(g):
            if e.card_id==UNIT:self.stats(g,e,2,2,2)
        # Six mana remains necessary for the second real Battlecry; use a separate actual game.
        g=self.game((COPY,),board=(UNIT,),active=2);self.play(g,COPY,self.body(g).id)
        self.assertEqual((self.copy(g).owner,self.copy(g).controller),(2,2))

    def test_typed_setter_codec_and_actual_minion_reward_reject_invalid_shapes(self):
        g=self.game((UNIT,));ref=CardReference.capture(self.hand(g)[0]);source=g.state.players[1].hero_id
        effect=SetStoredMinionStats(ref,2,2,source,CostSpec(set_to=2))
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);self.assertEqual(codec.decode(codec.encode(effect)),effect)
        for kwargs in ({'attack':True},{'health':0},{'card':replace(ref,zone=Zone.DECK)},{'cost':{}}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):replace(effect,**kwargs)
        with self.assertRaises(ValueError):DrawPhysicalGroup(1,source,(DrawGroupSlot(),),DrawGroupReward('set_stats_cost_all',2))
        with self.assertRaises(ValueError):DrawGroupReward('set_stats_cost_all',0)
        self.assertEqual(DrawPhysicalGroup(1,source,(DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,))),),
            DrawGroupReward('set_stats_cost_all',2)).reward.amount,2)
        with self.assertRaises(ValueError):CopyMinion(source,1,minion_grant=CreatedMinionGrant(2,2))


if __name__=='__main__':unittest.main()
