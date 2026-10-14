"""Real Summoned When Drawn bodies expressed with existing public operations."""
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, EndTurn, Game, HandProgressSpec,
    Keyword, PlayCard, PlayerSetup, Rarity, ResolutionError, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy, Draw, RequestChoice, RevealHandCard)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, DrawMatching, MoveCard
from hs_sim.engine.pools import PoolQuery
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry

HODIR,GIANT,KABAL,IMP,PLAIN='TTN_083','TTN_083t','CAP_400','CAP_400t2t','CS2_168'
FIXTURE=Path(__file__).resolve().parents[1]/'data/support/draw-summon-basics.json'
PIN='61fc35aefcdfd2d885c4bf3da0fb503b00a43ad1d42366f54d6ff07be9a69e42'


def evidence():
    raw=json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw)!=PIN:raise ValueError('Draw-summon complete raw changed')
    for row in raw['records']:
        if row['id']!=row['data']['id']or canonical_digest(row['data'])!=row['data_sha256']:
            raise ValueError('Draw-summon original row changed')
    return {row['id']:row['data']for row in raw['records']}


def own_physical_draw(c):
    if c.event is None or c.event.kind!='card_drawn':return False
    if (c.event.target_id,c.event.player_id)!=(c.source_id,c.player_id):return False
    draw_id=dict(c.event.data).get('draw_id')
    if type(draw_id)is not int or not 1<=draw_id<=len(c.state.draw_history):
        raise ResolutionError('Draw-summon needs an actual original draw fact')
    row=c.state.draw_history[draw_id-1]
    if (row.entity_id,row.player_id,row.outcome)!=(c.source_id,c.player_id,'hand'):
        raise ResolutionError('Draw-summon original successful hand draw disagrees')
    return True


def registry(scripts=(), *,observers=(),fault=False):
    r=opening_registry();rows=evidence()
    r.register_trigger_condition('own.physical.draw',own_physical_draw)
    for cid,other_side in ((GIANT,False),(IMP,True)):
        def summon(c,other_side=other_side):
            if not own_physical_draw(c):raise ResolutionError('Draw-summon callback lost original draw')
            source=c.state.entities[c.source_id]
            work=(RevealHandCard(source.id),SummonStoredCard(CardReference.capture(source),3-c.player_id if other_side else c.player_id),
                  Draw(c.player_id,source_id=source.id))
            if fault:work+=(AddToDeck(c.player_id,PLAIN),AddToHand(c.player_id,'missing.after.draw'))
            return work
        r.register_behavior(cid+'.draw',summon)
        row=rows[cid]
        r.register_card(CardDefinition(cid,row['name'],CardType.MINION,cost=row['cost'],attack=row['attack'],health=row['health'],
            keywords=(Keyword.LIFESTEAL,)if cid==IMP else (),
            hand_progress=HandProgressSpec('event',on_complete=cid+'.draw',event='card_drawn',condition_id='own.physical.draw',repeat=True),
            metadata=metadata(CardClass.WARLOCK if cid==IMP else CardClass.NEUTRAL,collectible=False,rarity=None,
                              tribes=('demon',)if cid==IMP else ())))
    r.register_behavior('hodir.shuffle',lambda c:tuple(AddToDeck(c.player_id,GIANT,source_id=c.source_id)for _ in range(4)))
    r.register_behavior('kabal.shuffle',lambda c:tuple(AddToDeck(3-c.player_id,IMP,source_id=c.source_id)for _ in range(2)))
    for cid,body,cls,rarity in ((HODIR,'hodir.shuffle',CardClass.NEUTRAL,Rarity.EPIC),
            (KABAL,'kabal.shuffle',CardClass.WARLOCK,Rarity.COMMON)):
        row=rows[cid];body_field={'battlecry':body}if cid==HODIR else {'deathrattle':body}
        r.register_card(CardDefinition(cid,row['name'],CardType.MINION,cost=row['cost'],attack=row['attack'],health=row['health'],
            metadata=metadata(cls,rarity=rarity),**body_field))
    row=rows[PLAIN]
    r.register_card(CardDefinition(PLAIN,row['name'],CardType.MINION,cost=row['cost'],attack=row['attack'],health=row['health'],
        metadata=metadata(rarity=Rarity.FREE,tribes=('murloc',))))
    for name,callback in (('draw',lambda c:(Draw(c.player_id,source_id=c.source_id),)),*scripts):
        r.register_behavior(name,callback)
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,metadata=metadata()))
    for name,event,callback in observers:
        r.register_behavior(name,callback)
        r.register_card(CardDefinition(name,name,CardType.MINION,health=4,triggers=(TriggerSpec(event,name),),metadata=metadata()))
    return r


class DrawSummonTests(unittest.TestCase):
    def setUp(self):self.scripts=[];self.options={}
    def script(self,name,callback):self.scripts.append((name,callback))
    def watch(self,name,event,callback):self.options.setdefault('observers',[]).append((name,event,callback))
    def game(self,hand=('draw',), *,deck=(GIANT,PLAIN),board=(),enemy_board=(),enemy_deck=(PLAIN,)*4,enemy_hand=()):
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,deck=deck,board=board,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',hand=enemy_hand,deck=enemy_deck,board=enemy_board,mana=10,max_mana=10)),seed=67),
            registry(self.scripts,**self.options))
    def play(self,g,cid='draw',player=None):
        player=player or g.state.active_player
        source=next(eid for eid in g.state.players[player].hand if g.state.entities[eid].card_id==cid)
        g.apply(PlayCard(player,source));return source
    def cards(self,g,zone=Zone.HAND,player=1):
        return [g.state.entities[eid].card_id for eid in getattr(g.state.players[player],zone.value)]
    def portable(self,g):
        snapshot=json.loads(json.dumps(g.snapshot()));restored=Game.from_snapshot(snapshot,registry(self.scripts,**self.options))
        self.assertEqual(restored.snapshot(),snapshot);self.assertEqual(g.clone().snapshot(),snapshot)
        self.assertEqual(replay(build_replay(g),registry(self.scripts,**self.options)).snapshot(),snapshot);return restored
    def choose(self,g):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
    def wait(self,c):return (RequestChoice(1,(ChoiceOption('ok','Continue'),),c.source_id),)

    def test_real_giant_uses_same_drawn_entity_and_replaces_with_next_card(self):
        g=self.game();original=g.state.players[1].deck[0];self.play(g)
        self.assertEqual(g.state.players[1].board,[original]);self.assertEqual(self.cards(g),[PLAIN])
        self.assertEqual((g.state.entities[original].attack,g.state.entities[original].health),(8,8))
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(len(g.state.cast_history),1)
        self.assertEqual(g.state.players[1].mana,10)
        self.assertEqual([(d.entity_id,d.source_id,d.completed)for d in g.state.draw_history],
            [(original,g.state.play_history[0].source_id,True),(g.state.players[1].hand[0],original,True)])
        self.portable(g)

    def test_real_imp_summons_for_opponent_but_replacement_belongs_to_drawer(self):
        g=self.game(deck=(IMP,PLAIN));original=g.state.players[1].deck[0];self.play(g)
        self.assertEqual(g.state.players[2].board,[original]);self.assertEqual(g.state.players[1].board,[])
        self.assertEqual((g.state.entities[original].owner,g.state.entities[original].controller),(1,2))
        self.assertIn(Keyword.LIFESTEAL,g.state.entities[original].keywords)
        self.assertEqual(self.cards(g),[PLAIN]);self.assertEqual(self.cards(g,Zone.HAND,2),[])
        self.portable(g)

    def test_complete_raw_preserves_nonspell_type_and_original_marker_difference(self):
        rows=evidence();raw=json.loads((FIXTURE.parents[1]/'extracted/cards.json').read_text(encoding='utf-8'))
        originals={row['id']:row for row in raw}
        self.assertEqual(set(rows),{HODIR,GIANT,KABAL,IMP,PLAIN})
        for cid,row in rows.items():self.assertEqual(row,originals[cid])
        self.assertEqual((rows[GIANT]['type'],rows[IMP]['type']),('MINION','MINION'))
        self.assertEqual(rows[GIANT]['tags']['CASTS_WHEN_DRAWN'],1)
        self.assertIn({'tag':'SUMMONED_WHEN_DRAWN','value':1},rows[GIANT]['reference_tags'])
        self.assertEqual(rows[IMP]['tags']['SUMMONED_WHEN_DRAWN'],1)
        self.assertIn('for your opponent',rows[IMP]['text_en'])

    def test_real_hodir_battlecry_shuffles_four_declared_giants(self):
        g=self.game((HODIR,),deck=(PLAIN,PLAIN));source=self.play(g,HODIR)
        self.assertEqual(self.cards(g,Zone.DECK).count(GIANT),4)
        self.assertEqual(self.cards(g,Zone.BOARD),[HODIR]);self.assertEqual(g.state.players[1].mana,2)
        self.assertEqual(len(g.state.draw_history),0)
        added=[e for e in g.events if e.kind=='card_added_to_deck']
        self.assertEqual([e.source_id for e in added],[source]*4);self.portable(g)

    def test_real_kabal_death_places_imps_then_natural_enemy_draw_summons_for_creator(self):
        self.script('kill',lambda c:(Destroy(next(eid for eid in c.state.players[1].board
            if c.state.entities[eid].card_id==KABAL),c.source_id),))
        g=self.game((KABAL,'kill'),deck=(PLAIN,),enemy_deck=());self.play(g,KABAL);self.play(g,'kill')
        originals=list(g.state.players[2].deck);self.assertEqual(self.cards(g,Zone.DECK,2),[IMP,IMP])
        g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].board,originals)
        self.assertTrue(all(g.state.entities[eid].owner==2 and g.state.entities[eid].controller==1 for eid in originals))
        self.assertEqual([d.player_id for d in g.state.draw_history],[2,2,2])
        self.assertEqual(g.state.players[2].fatigue,1);self.portable(g)

    def test_contiguous_summoned_draws_preserve_physical_order_and_nested_sources(self):
        g=self.game(deck=(GIANT,GIANT,PLAIN));originals=list(g.state.players[1].deck);self.play(g)
        self.assertEqual(g.state.players[1].board,originals[:2]);self.assertEqual(self.cards(g),[PLAIN])
        self.assertEqual([d.entity_id for d in g.state.draw_history],originals)
        self.assertEqual([d.source_id for d in g.state.draw_history][1:],originals[:2])
        self.assertTrue(all(d.completed for d in g.state.draw_history));self.portable(g)

    def test_original_multi_draws_finish_each_summon_and_nested_draw_in_order(self):
        self.script('two',lambda c:(Draw(c.player_id,2,c.source_id),))
        g=self.game(('two',),deck=(GIANT,PLAIN,'card.1'));self.play(g,'two')
        self.assertEqual(self.cards(g),[PLAIN,'card.1']);self.assertEqual(self.cards(g,Zone.BOARD),[GIANT])
        self.assertEqual(len(g.state.draw_history),3);self.portable(g)

    def test_empty_nested_replacement_is_one_fatigue_after_summon(self):
        g=self.game(deck=(GIANT,));self.play(g)
        self.assertEqual(self.cards(g,Zone.BOARD),[GIANT]);self.assertEqual(g.state.players[1].fatigue,1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,29)
        self.assertEqual([d.outcome for d in g.state.draw_history],['hand','fatigue']);self.portable(g)

    def test_full_hand_burns_source_without_summon_or_nested_draw(self):
        self.script('fill',lambda c:(AddToHand(1,PLAIN),Draw(1,source_id=c.source_id)))
        g=self.game(('fill',)+(PLAIN,)*9);original=g.state.players[1].deck[0];self.play(g,'fill')
        self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.players[1].board,[]);self.assertEqual(self.cards(g,Zone.DECK),[PLAIN])
        self.assertEqual([d.outcome for d in g.state.draw_history],['burned']);self.portable(g)

    def test_full_board_keeps_drawn_minion_and_nested_draw_under_stored_policy(self):
        g=self.game(board=(PLAIN,)*7);original=g.state.players[1].deck[0];self.play(g)
        self.assertEqual(self.cards(g),[GIANT,PLAIN]);self.assertEqual(g.state.entities[original].zone,Zone.HAND)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(len(g.state.draw_history),2)
        self.assertEqual(g.observe(2)['players'][0]['hand'][0]['card_id'],GIANT);self.portable(g)

    def test_opponent_recipient_ignores_drawer_full_board(self):
        g=self.game(deck=(IMP,PLAIN),board=(PLAIN,)*7);original=g.state.players[1].deck[0];self.play(g)
        self.assertEqual(g.state.players[2].board,[original]);self.assertEqual(self.cards(g),[PLAIN])
        self.assertEqual(len(g.state.players[1].board),7)

    def test_full_opponent_board_does_not_redirect_minion_to_drawer(self):
        g=self.game(deck=(IMP,PLAIN),enemy_board=(PLAIN,)*7);self.play(g)
        self.assertEqual(self.cards(g),[IMP,PLAIN]);self.assertEqual(g.state.players[1].board,[])
        self.assertEqual(len(g.state.players[2].board),7);self.portable(g)

    def test_nonmatching_other_draw_does_not_activate_old_token_in_hand(self):
        g=self.game((GIANT,'draw'),deck=(PLAIN,PLAIN));self.play(g)
        self.assertEqual(self.cards(g),[GIANT,PLAIN]);self.assertEqual(g.state.players[1].board,[])
        self.assertEqual(len(g.state.draw_history),1)

    def test_manual_play_is_ordinary_minion_without_automatic_extra_draw(self):
        g=self.game((GIANT,),deck=(PLAIN,));self.play(g,GIANT)
        self.assertEqual(self.cards(g,Zone.BOARD),[GIANT]);self.assertEqual(self.cards(g,Zone.DECK),[PLAIN])
        self.assertEqual(g.state.draw_history,[]);self.assertEqual(g.state.players[1].mana,2)

    def test_moves_generation_and_copies_are_not_successful_draw_facts(self):
        def create(c):
            card=CardReference.capture(c.state.entities[c.state.players[1].deck[0]])
            return (AddToHand(1,GIANT),CopyCard(card,1),MoveCard(card,1,Zone.HAND))
        self.script('create',create);g=self.game(('create',),deck=(GIANT,PLAIN));self.play(g,'create')
        self.assertEqual(self.cards(g),[GIANT,GIANT,GIANT]);self.assertEqual(g.state.players[1].board,[])
        self.assertEqual(g.state.draw_history,[]);self.portable(g)

    def test_matching_draw_summons_original_match_and_nested_draw_is_unfiltered_top(self):
        self.script('match',lambda c:(DrawMatching(1,PoolQuery(min_cost=8,max_cost=8),empty_deck='skip',selection='first',source_id=c.source_id),))
        g=self.game(('match',),deck=(PLAIN,GIANT,'card.1'));original=g.state.players[1].deck[1];self.play(g,'match')
        self.assertEqual(g.state.players[1].board,[original]);self.assertEqual(self.cards(g),[PLAIN])
        self.assertEqual(self.cards(g,Zone.DECK),['card.1']);self.portable(g)

    def test_explicit_physical_draw_uses_same_entity_and_automatic_continuation(self):
        self.script('move.draw',lambda c:(MoveCard(CardReference.capture(c.state.entities[c.state.players[1].deck[1]]),1,Zone.HAND,draw=True,source_id=c.source_id),))
        g=self.game(('move.draw',),deck=(PLAIN,GIANT));original=g.state.players[1].deck[1];self.play(g,'move.draw')
        self.assertEqual(g.state.players[1].board,[original]);self.assertEqual(self.cards(g),[PLAIN]);self.portable(g)

    def test_natural_turn_draw_uses_actor_and_same_automatic_path(self):
        g=self.game((),deck=(PLAIN,),enemy_deck=(GIANT,PLAIN));original=g.state.players[2].deck[0]
        g.apply(EndTurn(1));self.assertEqual(g.state.players[2].board,[original])
        self.assertEqual(self.cards(g,Zone.HAND,2),[PLAIN]);self.assertEqual(g.state.draw_history[0].source_id,None)
        self.portable(g)

    def test_hand_progress_wait_restores_the_original_physical_summon_once(self):
        self.watch('wait','hand_progressed',self.wait)
        g=self.game(board=('wait',));original=g.state.players[1].deck[0];self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.entities[original].zone,Zone.HAND)
        restored=self.portable(g);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.cards(g),[PLAIN])
        self.assertEqual(g.state.players[1].board.count(original),1)

    def test_reveal_wait_restores_summon_then_nested_draw_without_new_capture(self):
        self.watch('wait','card_revealed',self.wait)
        g=self.game(board=('wait',));original=g.state.players[1].deck[0];self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.entities[original].zone,Zone.HAND)
        restored=self.portable(g);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.cards(g),[PLAIN])

    def test_summon_wait_precedes_nested_draw_and_resumes_once(self):
        self.watch('wait','minion_summoned',lambda c:self.wait(c)if c.state.entities[c.event.source_id].card_id==GIANT else ())
        g=self.game(board=('wait',));self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.cards(g),[])
        self.assertEqual(self.cards(g,Zone.DECK),[PLAIN]);restored=self.portable(g)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(self.cards(g),[PLAIN]);self.assertEqual(len(g.state.draw_history),2)

    def test_nested_draw_wait_preserves_both_unfinished_original_draws(self):
        self.watch('wait','card_drawn',lambda c:self.wait(c)if c.state.entities[c.event.target_id].card_id==PLAIN else ())
        g=self.game(board=('wait',));self.play(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual([d.completed for d in g.state.draw_history],[False,False])
        restored=self.portable(g);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertTrue(all(d.completed for d in g.state.draw_history))

    def test_late_fault_restores_physical_summon_draws_rng_and_visibility(self):
        self.options['fault']=True;g=self.game();before=g.snapshot();rng=g._rng.getstate();views=(g.observe(1),g.observe(2))
        with self.assertRaisesRegex(ResolutionError,'missing.after.draw'):self.play(g)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual((g.observe(1),g.observe(2)),views);self.portable(g)

    def test_player_views_reveal_summoned_body_but_not_replacement_or_remaining_deck(self):
        g=self.game(deck=(GIANT,PLAIN,'card.1'));self.play(g)
        self.assertEqual(g.observe(2)['players'][0]['board'][0]['card_id'],GIANT)
        self.assertIsNone(g.observe(2)['players'][0]['hand'][0]['card_id'])
        before=g.snapshot();rng=g._rng.getstate()
        for viewer in (1,2):
            public=json.dumps(g.observe(viewer))
            for private in ('draw_history','draw_id','source_id','progress_keys','zone_epoch','random_state'):
                self.assertNotIn('"'+private+'"',public)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g._rng.getstate(),rng)

    def test_new_draw_of_same_physical_failed_minion_can_activate_again(self):
        def recycle(c):
            original=next(c.state.entities[eid]for eid in c.state.players[1].hand if c.state.entities[eid].card_id==GIANT)
            return (Destroy(c.state.players[1].board[0],c.source_id),
                MoveCard(CardReference.capture(original),1,Zone.DECK,'top'),Draw(1,source_id=c.source_id))
        self.script('recycle',recycle)
        g=self.game(('draw','recycle'),deck=(GIANT,PLAIN,'card.1'),board=(PLAIN,)*7)
        original=g.state.players[1].deck[0];self.play(g)
        self.assertEqual(g.state.entities[original].zone,Zone.HAND)
        self.play(g,'recycle');self.assertEqual(g.state.entities[original].zone,Zone.BOARD)
        self.assertEqual(self.cards(g),[PLAIN,'card.1'])
        progress=next(a for a in g.state.entities[original].abilities if a.kind=='hand_progress')
        self.assertEqual(progress.progress_completions,2);self.assertFalse(progress.consumed)
        self.portable(g)

    def test_lethal_summon_reaction_stops_nested_draw_and_interrupts_original(self):
        self.watch('lethal','minion_summoned',lambda c:(Destroy(c.state.players[2].hero_id,c.source_id),)
            if c.state.entities[c.event.source_id].card_id==GIANT else ())
        g=self.game(board=('lethal',));self.play(g)
        self.assertEqual(g.state.status,'finished');self.assertEqual(self.cards(g,Zone.DECK),[PLAIN])
        self.assertEqual(len(g.state.draw_history),1);self.assertTrue(g.state.draw_history[0].interrupted)
        self.portable(g)
