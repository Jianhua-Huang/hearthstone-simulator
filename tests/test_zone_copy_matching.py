"""Automatic physical-card copy selection reuses prices, zones and transactions."""
import unittest

from hs_sim.engine import CardDefinition,CardType,Game,PlayCard,PlayerSetup,Registry,Scenario,SelectChoice,TriggerSpec
from hs_sim.engine.effects import ChoiceOption,InvokeBehavior,ModifyCost,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardClass,CardMetadata,CostSpec,Zone
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import CardReference,CopyMatching,MoveCard


def registry(wait=False):
    r=Registry('automatic-zone-copy-tests-v1')
    meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('beast',))
    r.register_card(CardDefinition('zc.hero','Hero',CardType.HERO,health=30))
    r.register_card(CardDefinition('zc.cheap','Cheap',CardType.MINION,cost=1,attack=1,health=2,metadata=meta))
    r.register_card(CardDefinition('zc.expensive','Expensive',CardType.MINION,cost=5,attack=2,health=4,metadata=meta))
    def first(c):return CardReference.capture(c.state.entities[c.state.players[2].hand[0]])
    def fail(c):raise ResolutionError('after random copy')
    r.register_behavior('zc.fail',fail)
    for name,body in {
        'deck':lambda c:(CopyMatching(1,2,Zone.DECK,source_id=c.source_id),),
        'hand':lambda c:(CopyMatching(1,2,Zone.HAND,source_id=c.source_id),),
        'twice':lambda c:(CopyMatching(1,2,Zone.HAND,count=2,source_id=c.source_id),),
        'lowest':lambda c:(CopyMatching(1,2,Zone.HAND,selection='lowest_cost',source_id=c.source_id),),
        'base':lambda c:(CopyMatching(1,2,Zone.HAND,mode='base',source_id=c.source_id),),
        'grow':lambda c:(BuffStoredCard(first(c),3,2,c.source_id),),
        'discount':lambda c:(ModifyCost(first(c).entity_id,CostSpec(set_to=0),c.source_id),),
        'bad':lambda c:(CopyMatching(1,2,Zone.DECK,source_id=c.source_id),InvokeBehavior('zc.fail',c.source_id,1)),
        'waiting':lambda c:(RequestChoice(1,(ChoiceOption('copy','Copy',(
            CopyMatching(1,2,Zone.DECK,source_id=c.source_id),)),),c.source_id),),
    }.items():
        r.register_behavior('zc.'+name,body)
        r.register_card(CardDefinition('zc.'+name,name,CardType.SPELL,on_play='zc.'+name))
    if wait:
        def watch(c):
            if c.event.player_id!=1 or c.state.entities[c.event.target_id].card_id not in ('zc.cheap','zc.expensive'):return ()
            card=first(c)
            return (RequestChoice(1,(ChoiceOption('move','Move original',(
                MoveCard(card,2,Zone.DECK,'bottom',source_id=c.source_id),)),),c.source_id),)
        r.register_behavior('zc.watch',watch)
        r.register_card(CardDefinition('zc.watch','Observer',CardType.MINION,health=4,
            triggers=(TriggerSpec('card_added_to_hand','zc.watch'),)))
    return r


class ZoneCopyMatchingTests(unittest.TestCase):
    def game(self,hand=('zc.deck',),enemy_hand=(),enemy_deck=(),wait=False):
        return Game.from_scenario(Scenario((PlayerSetup('zc.hero',hand=hand,mana=10,max_mana=10,
            board=('zc.watch',) if wait else ()),PlayerSetup('zc.hero',hand=enemy_hand,deck=enemy_deck)),seed=71),registry(wait))
    def play(self,g,cid):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid))
    def names(self,g,player=1,zone='hand'):return [g.state.entities[i].card_id for i in getattr(g.state.players[player],zone)]
    def portable(self,g,wait=False):
        for other in (g.clone(),Game.from_snapshot(g.snapshot(),registry(wait)),replay(build_replay(g),registry(wait))):
            self.assertEqual(other.snapshot(),g.snapshot())

    def test_random_deck_copy_creates_new_owned_entity_and_preserves_original_order(self):
        g=self.game(enemy_deck=('zc.cheap','zc.expensive','zc.cheap'));before=list(g.state.players[2].deck)
        self.play(g,'zc.deck');copy=g.state.entities[g.state.players[1].hand[0]]
        self.assertNotIn(copy.id,before);self.assertIn(copy.origin_entity_id,before)
        self.assertEqual((copy.owner,copy.controller),(1,1));self.assertEqual(g.state.players[2].deck,before)
        self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_current_copy_keeps_stored_growth_but_base_copy_uses_printed_face(self):
        for mode,stats in [('hand',(4,4)),('base',(1,2))]:
            g=self.game(hand=('zc.grow','zc.'+mode),enemy_hand=('zc.cheap',))
            self.play(g,'zc.grow');self.play(g,'zc.'+mode);e=g.state.entities[g.state.players[1].hand[0]]
            self.assertEqual((e.attack,e.health),stats)

    def test_lowest_cost_is_current_enemy_owner_quote_and_unique_minimum_is_rng_free(self):
        g=self.game(hand=('zc.discount','zc.lowest'),enemy_hand=('zc.expensive','zc.cheap'))
        self.play(g,'zc.discount');rng=g.snapshot()['rng_state'];self.play(g,'zc.lowest')
        self.assertEqual(self.names(g),['zc.expensive']);self.assertEqual(g.quote_cost(g.state.players[1].hand[0]).amount,0)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

    def test_equal_current_cost_ties_are_random_and_replay_exactly(self):
        g=self.game(hand=('zc.lowest',),enemy_hand=('zc.cheap','zc.cheap'));rng=g.snapshot()['rng_state']
        self.play(g,'zc.lowest');self.assertNotEqual(g.snapshot()['rng_state'],rng);self.portable(g)

    def test_empty_pool_does_not_consume_rng_allocate_or_request_input(self):
        g=self.game();before=g.snapshot();self.play(g,'zc.deck')
        self.assertEqual(g.snapshot()['rng_state'],before['rng_state'])
        self.assertEqual(g.state.next_entity_id,before['state']['next_entity_id']);self.assertIsNone(g.state.pending_choice)

    def test_full_hand_burns_copy_without_touching_original(self):
        g=self.game(hand=('zc.twice',)+('zc.cheap',)*9,enemy_hand=('zc.expensive',));self.play(g,'zc.twice')
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(self.names(g,2),['zc.expensive'])
        self.assertEqual(len(g.state.death_history),0)
        self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),1)

    def test_hidden_hand_identities_and_candidate_list_are_not_published(self):
        g=self.game(hand=('zc.hand',),enemy_hand=('zc.cheap','zc.expensive'))
        before=g.for_player(1).observe();self.assertNotIn('zc.cheap',str(before));self.assertNotIn('zc.expensive',str(before))
        self.play(g,'zc.hand');self.assertTrue(all(x.get('card_id') is None for x in g.for_player(2).observe()['observation']['players'][0]['hand']))
        self.assertNotIn('CopyMatching',str(g.for_player(1).events()));self.assertIsNone(g.state.pending_choice)

    def test_stored_pending_instruction_restores_before_random_selection(self):
        g=self.game(hand=('zc.waiting',),enemy_deck=('zc.cheap','zc.expensive'));self.play(g,'zc.waiting');self.portable(g)
        others=(g.clone(),Game.from_snapshot(g.snapshot(),registry()),replay(build_replay(g),registry()))
        for current in (g,*others):p=current.state.pending_choice;current.apply(SelectChoice(1,p.id,('copy',)))
        for current in others:self.assertEqual(current.snapshot(),g.snapshot())

    def test_second_copy_requeries_after_first_acquisition_reaction(self):
        g=self.game(hand=('zc.twice',),enemy_hand=('zc.cheap',),wait=True);self.play(g,'zc.twice');self.portable(g,True)
        p=g.state.pending_choice;g.apply(SelectChoice(1,p.id,('move',)))
        self.assertEqual(self.names(g),['zc.cheap']);self.assertEqual(g.state.players[2].hand,[])
        self.assertEqual(self.names(g,2,'deck'),['zc.cheap']);self.portable(g,True)

    def test_late_failure_rolls_back_selection_materialization_and_rng(self):
        g=self.game(hand=('zc.bad',),enemy_deck=('zc.cheap','zc.expensive'));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'after random copy'):self.play(g,'zc.bad')
        self.assertEqual(g.snapshot(),before)

    def test_declaration_rejects_unknown_zone_policy_query_and_boolean_count(self):
        for kwargs in ({'zone':Zone.BOARD},{'selection':'highest_cost'},{'query':{}},{'count':True},{'mode':'unknown'}):
            args=dict(player_id=1,owner_id=2,zone=Zone.HAND);args.update(kwargs)
            with self.assertRaises(ValueError):CopyMatching(**args)
        with self.assertRaises(ValueError):CopyMatching(1,2,Zone.DECK,selection='lowest_cost')
