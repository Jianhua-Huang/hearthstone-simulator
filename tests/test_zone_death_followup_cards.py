"""Real filtered dragon draws, top-deck destruction and opponent hand discount."""
import json
from random import Random
import unittest
from hs_sim.engine import CardDefinition,CardType,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec,Zone
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import ChoiceOption,Draw,InvokeBehavior,RequestChoice,Silence
from hs_sim.engine.replay import build_replay,replay
from test_death_followup_cards import registry as base_registry

DREAD='EDR_572';WATCHER='TLC_621';EXPLORER='TLC_244';YETI='CORE_CS2_182';DRAGON='EDR_890';OTHER='CORE_AT_123'


def registry(wait=False):
    r=base_registry();r.register_behavior('k38.silence',lambda c:(Silence(c.target_id),))
    r.register_card(CardDefinition('k38.silence','Silence fixture',CardType.SPELL,on_play='k38.silence',requires_target=True))
    if wait:
        def watch(c):
            if c.state.entities[c.event.target_id].card_id!=WATCHER:return ()
            return(RequestChoice(1,(
                ChoiceOption('ok','Draw before Deathrattle',(Draw(1,source_id=c.source_id),)),
                ChoiceOption('bad','Rollback',(InvokeBehavior('k21.fail',c.source_id,1),))),c.source_id),)
        r.register_behavior('k38.watch',watch)
        r.register_card(CardDefinition('k38.watch','Death observer fixture',CardType.MINION,health=8,
            triggers=(TriggerSpec('minion_died','k38.watch'),)))
    return r


class ZoneDeathFollowupCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),deck=(),enemy_hand=(),enemy_deck=(),wait=False):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,
            mana=40,max_mana=40,mana_cap=40),PlayerSetup('HERO_08',hand=enemy_hand,deck=enemy_deck)),seed=381),registry(True)if wait else self.registry)
    def body(self,g,cid):return next(g.state.entities[e]for e in g.state.players[1].board if g.state.entities[e].card_id==cid)
    def play(self,g,cid,target=None):
        eid=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid)
        g.apply(PlayCard(1,eid,target));return eid
    def price(self,g,eid):return quote_cost(g.state,g.registry,g.state.entities[eid]).amount
    def choose(self,g):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
    def portable(self,g,wait=False):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(wait))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(wait)).snapshot(),saved);return other

    def test_full_faces_and_native_keywords(self):
        for cid,stats,keywords in((DREAD,(5,5,5),()),(WATCHER,(4,4,7),(Keyword.TAUNT,)),(EXPLORER,(2,3,5),())):
            card=self.registry.card(cid);self.assertEqual((card.cost,card.attack,card.health),stats)
            self.assertEqual(card.keywords,keywords);self.assertTrue(card.deathrattle)

    def test_dreadwing_draws_exact_physical_dragons_and_discounts_each_one(self):
        g=self.game(('k21.kill',),board=(DREAD,),deck=(YETI,DRAGON,'CORE_CS2_029',OTHER))
        original=tuple(g.state.players[1].deck);self.play(g,'k21.kill',self.body(g,DREAD).id)
        hand=g.state.players[1].hand
        self.assertEqual({g.state.entities[e].card_id for e in hand},{DRAGON,OTHER})
        for eid in hand:self.assertIn(eid,original);self.assertEqual(self.price(g,eid),self.registry.card(g.state.entities[eid].card_id).cost-1)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].deck],[YETI,'CORE_CS2_029']);self.portable(g)

    def test_dreadwing_active_controller_draws_other_deck_and_empty_skips(self):
        g=self.game(('k21.control','k21.trigger'),board=(DREAD,),deck=(YETI,),enemy_deck=(DRAGON,OTHER))
        source=self.body(g,DREAD).id;self.play(g,'k21.control',source);self.play(g,'k21.trigger',source)
        self.assertFalse(g.state.players[1].hand);self.assertEqual(len(g.state.players[2].hand),2)
        self.assertFalse(g.state.death_history)
        g=self.game(('k21.kill',),board=(DREAD,));before=g._rng.getstate();self.play(g,'k21.kill',self.body(g,DREAD).id)
        self.assertFalse(g.state.draw_history);self.assertEqual(g._rng.getstate(),before)

    def test_watcher_destroys_original_top_three_in_one_batch_without_board_deaths(self):
        g=self.game(('k21.kill',),board=(WATCHER,),deck=(YETI,DREAD,'END_002','CORE_CS2_029'))
        original=list(g.state.players[1].deck);before=g._rng.getstate();self.play(g,'k21.kill',self.body(g,WATCHER).id)
        self.assertEqual(g.state.players[1].deck,original[3:])
        self.assertTrue(all(g.state.entities[e].zone==Zone.GRAVEYARD for e in original[:3]))
        self.assertEqual([d.card_id for d in g.state.death_history],[WATCHER])
        self.assertFalse(g.state.draw_history);self.assertIsNone(g.state.players[1].weapon_id)
        events=[e.target_id for e in g.events if e.kind=='card_destroyed_in_deck'];self.assertEqual(events,original[:3])
        self.assertEqual(g._rng.getstate(),before);self.portable(g)

    def test_watcher_short_or_empty_deck_does_not_fatigue(self):
        for deck in((),(YETI,)):
            g=self.game(('k21.kill',),board=(WATCHER,),deck=deck);self.play(g,'k21.kill',self.body(g,WATCHER).id)
            self.assertFalse(g.state.players[1].deck);self.assertFalse(g.state.draw_history)
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)

    def test_watcher_queries_new_top_after_actual_death_reaction_wait(self):
        g=self.game(('k21.kill',),board=(WATCHER,'k38.watch'),deck=(YETI,DRAGON,DREAD,'END_002','CORE_CS2_029'),wait=True)
        original=list(g.state.players[1].deck);self.play(g,'k21.kill',self.body(g,WATCHER).id)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,True)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.players[1].hand,[original[0]])
        self.assertEqual(g.state.players[1].deck,[original[4]])

    def test_explorer_full_enemy_physical_pool_keeps_duplicates_and_ignores_spells(self):
        g=self.game(('k21.kill',YETI),board=(EXPLORER,),enemy_hand=(YETI,'CORE_CS2_029',YETI,'CORE_EX1_506'))
        ids=[e for e in g.state.players[2].hand if g.state.entities[e].kind==CardType.MINION]
        prices={e:self.price(g,e)for e in g.state.players[2].hand};stats={e:(g.state.entities[e].attack,g.state.entities[e].health)for e in ids}
        rng=Random();rng.setstate(g._rng.getstate());chosen=rng.choice(ids)
        self.play(g,'k21.kill',self.body(g,EXPLORER).id)
        self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(self.price(g,g.state.players[1].hand[0]),4)
        for eid,price in prices.items():self.assertEqual(self.price(g,eid),max(0,price-(2 if eid==chosen else 0)))
        for eid,stat in stats.items():self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),stat)
        self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_explorer_repeated_active_cost_floor_and_empty_no_rng(self):
        g=self.game(('k21.trigger','k21.trigger'),board=(EXPLORER,),enemy_hand=(YETI,));source=self.body(g,EXPLORER).id
        held=g.state.players[2].hand[0];self.play(g,'k21.trigger',source);self.play(g,'k21.trigger',source)
        self.assertEqual(self.price(g,held),0);self.assertFalse(g.state.death_history)
        g=self.game(('k21.kill',),board=(EXPLORER,),enemy_hand=('CORE_CS2_029',));before=g._rng.getstate()
        self.play(g,'k21.kill',self.body(g,EXPLORER).id);self.assertEqual(g._rng.getstate(),before)

    def test_explorer_control_changes_whose_opponent_receives_discount(self):
        g=self.game(('k21.control','k21.kill',YETI),board=(EXPLORER,),enemy_hand=(YETI,))
        source=self.body(g,EXPLORER).id;own=g.state.players[1].hand[-1];other=g.state.players[2].hand[0]
        self.play(g,'k21.control',source);self.play(g,'k21.kill',source)
        self.assertEqual((self.price(g,own),self.price(g,other)),(2,4))

    def test_silence_removes_all_three_native_bodies(self):
        for cid in(DREAD,WATCHER,EXPLORER):
            g=self.game(('k38.silence','k21.kill'),board=(cid,),deck=(DRAGON,OTHER),enemy_hand=(YETI,))
            source=self.body(g,cid).id;deck=list(g.state.players[1].deck);self.play(g,'k38.silence',source);self.play(g,'k21.kill',source)
            self.assertEqual(g.state.players[1].deck,deck);self.assertFalse(g.state.draw_history)
            self.assertEqual(self.price(g,g.state.players[2].hand[0]),4)
