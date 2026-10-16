"""Physical matching draws retain their own discounted arrival across reactions."""
import json
from random import Random
import unittest
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,PlayCard,
    PlayerSetup,Rarity,Registry,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import AddToHand,ChoiceOption,Draw,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.spell_sequences import DrawMatchingWithCostReduction
from hs_sim.engine.zones import CardReference,MoveCard

QUERY=PoolQuery(kinds=(CardType.MINION,),tribes_any=('dragon',))


def registry(mode=None):
    r=Registry('matching-discount-tests-v1')
    r.register_card(CardDefinition('hero','hero',CardType.HERO,health=30,
        metadata=CardMetadata(False,(CardClass.MAGE,),None)))
    for cid,cost,tribes in [('dragon',5,('dragon',)),('other_dragon',2,('dragon',)),
                            ('all_tribes',0,('all',)),('plain',7,())]:
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=2,health=4,
            metadata=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=tribes)))
    r.register_card(CardDefinition('spell','spell',CardType.SPELL,cost=8))
    r.register_behavior('take',lambda c:(DrawMatchingWithCostReduction(c.player_id,1,c.source_id,QUERY),))
    r.register_behavior('take2',lambda c:tuple(DrawMatchingWithCostReduction(c.player_id,1,c.source_id,QUERY)for _ in range(2)))
    r.register_behavior('invalid_source',lambda c:(DrawMatchingWithCostReduction(c.player_id,1,999999,QUERY),))
    r.register_behavior('burntake',lambda c:(AddToHand(1,'plain',c.source_id),DrawMatchingWithCostReduction(c.player_id,1,c.source_id,QUERY)))
    r.register_behavior('fail',lambda c:(AddToHand(c.player_id,'missing.m38'),))
    for cid in('take','take2','invalid_source','burntake'):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    if mode:
        def watch(c):
            source=c.state.entities.get(c.event.source_id)
            if source is None or source.card_id not in('take','take2'):return ()
            if c.state.entities[c.state.players[1].hero_id].armor:return ()
            if mode=='failure':return(InvokeBehavior('fail',c.source_id,1),)
            ref=CardReference.capture(c.state.entities[c.event.target_id])
            follow=(MoveCard(ref,1,Zone.DECK,position='top',source_id=c.source_id),Draw(1,source_id=c.source_id))if mode=='cycle'else(Draw(1,source_id=c.source_id),)
            return(RequestChoice(1,(
                ChoiceOption('ok','Continue',(GainArmor(1,1),*follow)),
                ChoiceOption('bad','Rollback',(InvokeBehavior('fail',c.source_id,1),))),c.source_id),)
        r.register_behavior('watch',watch)
        r.register_card(CardDefinition('watch','watch',CardType.MINION,health=8,
            triggers=(TriggerSpec('card_drawn','watch'),)))
    return r


class MatchingDrawDiscountTests(unittest.TestCase):
    def game(self,deck,*,mode=None,hand=('take',)):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,deck=deck,
            board=('watch',)if mode else(),mana=10,max_mana=10),PlayerSetup('hero')),seed=380),registry(mode))
    def play(self,g):g.apply(PlayCard(1,g.state.players[1].hand[0]))
    def price(self,g,eid):return quote_cost(g.state,g.registry,g.state.entities[eid]).amount
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode=None):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(mode))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved);return other

    def test_physical_duplicate_candidates_actual_draw_and_remaining_deck_order(self):
        g=self.game(('plain','dragon','spell','dragon','other_dragon'))
        before=tuple(g.state.players[1].deck);candidates=[e for e in before if g.state.entities[e].card_id in('dragon','other_dragon')]
        rng=Random();rng.setstate(g._rng.getstate());expected=rng.choice(candidates)
        self.play(g);self.assertEqual(g.state.players[1].hand,[expected])
        self.assertEqual(g.state.players[1].deck,[e for e in before if e!=expected])
        self.assertEqual(g._rng.getstate(),rng.getstate())
        self.assertEqual(self.price(g,expected),g.registry.card(g.state.entities[expected].card_id).cost-1);self.portable(g)

    def test_no_match_and_empty_deck_skip_without_rng_or_fatigue(self):
        for deck in((),('plain','spell')):
            g=self.game(deck);before=g._rng.getstate();self.play(g)
            self.assertFalse(g.state.draw_history);self.assertEqual(g._rng.getstate(),before)
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)

    def test_all_tribes_matches_and_reduction_has_zero_floor(self):
        g=self.game(('all_tribes',));self.play(g);held=g.state.players[1].hand[0]
        self.assertEqual(g.state.entities[held].card_id,'all_tribes');self.assertEqual(self.price(g,held),0)

    def test_two_requests_requery_and_skip_after_last_match(self):
        g=self.game(('plain','dragon','other_dragon','spell'),hand=('take2',));self.play(g)
        self.assertEqual(len(g.state.draw_history),2)
        self.assertEqual(sorted(self.price(g,e)for e in g.state.players[1].hand),[1,4])
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].deck],['plain','spell'])
        g=self.game(('dragon',),hand=('take2',));self.play(g)
        self.assertEqual(len(g.state.draw_history),1);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)

    def test_full_hand_burn_is_not_an_arrival_or_discount_target(self):
        g=self.game(('dragon',),hand=('burntake',)+('plain',)*9);self.play(g)
        self.assertEqual(g.state.draw_history[0].outcome,'burned');self.assertEqual(len(g.state.players[1].hand),10)
        burned=g.state.entities[g.state.draw_history[0].entity_id]
        self.assertEqual(burned.zone,Zone.GRAVEYARD);self.assertFalse(burned.enchantments)

    def test_waiting_extra_draw_does_not_redirect_discount_and_new_request_restores(self):
        g=self.game(('plain','dragon','other_dragon'),mode='draw',hand=('take2',));self.play(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertIn('DrawMatchingWithCostReduction',json.dumps(g.snapshot()))
        original=g.state.draw_history[0].entity_id;before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g,'draw')
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.draw_history),3)
        self.assertEqual(self.price(g,original),g.registry.card(g.state.entities[original].card_id).cost-1)
        unrelated=g.state.draw_history[1].entity_id;self.assertEqual(self.price(g,unrelated),g.registry.card(g.state.entities[unrelated].card_id).cost)
        self.assertNotIn('rng_state',json.dumps(g.observe(2)))

    def test_leave_and_redraw_same_entity_invalidates_original_arrival(self):
        g=self.game(('dragon',),mode='cycle');self.play(g);original=g.state.draw_history[0].entity_id
        other=self.portable(g,'cycle')
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.players[1].hand,[original])
        self.assertEqual(len(g.state.draw_history),2);self.assertEqual(self.price(g,original),5)

    def test_late_draw_failure_rolls_back_physical_move_rng_and_history(self):
        g=self.game(('dragon','other_dragon'),mode='failure');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_missing_source_rejected_before_random_selection(self):
        g=self.game(('dragon',),hand=('invalid_source',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_strict_request_and_allowlisted_codec_roundtrip(self):
        for args in((1,True,1,QUERY),(1,1,0,QUERY),(1,1,1,None),(1,1,1,{})):
            with self.assertRaises(ValueError):DrawMatchingWithCostReduction(*args)
        request=DrawMatchingWithCostReduction(1,1,1,QUERY);codec=FrameCodec(default_mechanics(),registry())
        self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(request)))),request)

    def test_prior_mechanics_signature_is_not_accepted_as_current(self):
        g=self.game(('dragon',));snapshot=g.snapshot();snapshot['mechanics_version']=default_mechanics(version='core-effects-v337').signature
        with self.assertRaises(SnapshotError):Game.from_snapshot(snapshot,registry())
