"""One real self-discard summon expressed by the existing native body and Summon."""
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, CardClass, CardDefinition, CardType, EndTurn,
    Game, PlayCard, PlayerSetup, Rarity, Registry, ResolutionError, Scenario,
    SelectChoice, TriggerSpec, Zone, discarded_cards)
from hs_sim.engine.effects import (ChoiceOption, Destroy, Draw, GainArmor, InvokeBehavior,
    RequestChoice, ReturnToHand, Summon)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import (CardReference, ChooseFromZone, CopyCard, DiscardCard,
    DiscardMatching, DestroyDeckCard, MoveCard)
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

NATIVE='KAR_205'
PATH=Path(__file__).resolve().parents[1]/'data/support/discard-summon-basics.json'
PIN='81aee3434e1931ec1f1b6f28b2651fff697fbd664473fcdfd3123d69942d5f39'


def evidence():
    support=json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support)!=PIN:raise ValueError('Own-discard summon evidence changed')
    row=support['records'][0]
    if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Native full raw changed')
    return row['data']


def reference(c,player=None,zone=Zone.HAND):
    p=c.player_id if player is None else player
    return CardReference.capture(c.state.entities[getattr(c.state.players[p],zone.value)[0]])


def own_summon(c):
    # This is a printed new-body policy for this one representative, not a
    # universal interpretation of every card's "summon it" or "return it".
    if (c.discard is None or c.discard.card_id!=NATIVE or c.discard.entity_id!=c.source_id or
            c.discard.player_id!=c.player_id or c.source.zone!=Zone.GRAVEYARD):
        raise ResolutionError('Native summon needs its original successful discard')
    return (Summon(c.player_id,NATIVE),)


def registry():
    r=Registry('isolated-discard-summon-basics-v1');raw=evidence()
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata()))
    r.register_card(CardDefinition('a','Whiteboard',CardType.MINION,cost=1,attack=1,health=10,metadata=metadata()))
    r.register_card(CardDefinition('b','Blank spell',CardType.SPELL,metadata=metadata()))
    r.register_behavior('native.summon',own_summon)
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.MINION,cost=raw['cost'],
        attack=raw['attack'],health=raw['health'],on_discard='native.summon',
        metadata=metadata(CardClass.WARLOCK,rarity=Rarity.RARE)))
    def fault(c):raise RuntimeError('Deliberate late failure')
    r.register_behavior('fault',fault)
    def twice(c):
        ref=reference(c);return (DiscardCard(ref,c.source_id),DiscardCard(ref,c.source_id))
    scripts={
        'discard':lambda c:(DiscardCard(reference(c),c.source_id),),
        'enemy':lambda c:(DiscardCard(reference(c,3-c.player_id),c.source_id),),
        'many':lambda c:(DiscardMatching(c.player_id,count=2,selection='first',source_id=c.source_id),),
        'empty':lambda c:(DiscardMatching(c.player_id,PoolQuery(),selection='random',source_id=c.source_id),),
        'twice':twice,
        'chosen':lambda c:(ChooseFromZone(c.player_id,c.player_id,Zone.HAND,PoolQuery(),'discard',None,'entity',c.source_id),),
        'transfer':lambda c:(MoveCard(reference(c),2,Zone.HAND,source_id=c.source_id),),
        'move':lambda c:(MoveCard(reference(c),c.player_id,Zone.DECK,position='top',source_id=c.source_id),),
        'deckdestroy':lambda c:(DestroyDeckCard(reference(c,zone=Zone.DECK),c.source_id),),
        'draw2':lambda c:(Draw(c.player_id,2,c.source_id),),
        'buff':lambda c:(BuffStoredCard(reference(c),attack=2,health=3,source_id=c.source_id),),
        'buffdeck':lambda c:(BuffStoredCard(reference(c,zone=Zone.DECK),attack=2,health=3,source_id=c.source_id),),
        'copyhand':lambda c:(CopyCard(reference(c),c.player_id,source_id=c.source_id),),
        'latefault':lambda c:(DiscardCard(reference(c),c.source_id),InvokeBehavior('fault',c.source_id,c.player_id)),
    }
    targeted={
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
    }
    for cid,body in {**scripts,**targeted}.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            requires_target=cid in targeted,metadata=metadata()))
    def before_wait(c):
        if c.event.player_id!=c.player_id:return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue'),
            ChoiceOption('fault','Fail',(InvokeBehavior('fault',c.source_id,c.player_id),)),
        ),c.source_id),)
    def after_wait(c):
        if c.event.player_id!=c.player_id or c.state.entities[c.event.source_id].card_id!=NATIVE:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),GainArmor(c.player_id,1))
    for cid,event,body in (('before','card_discarded',before_wait),('after','minion_summoned',after_wait)):
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=10,
            triggers=(TriggerSpec(event,cid),),metadata=metadata()))
    return r


class DiscardSummonTests(unittest.TestCase):
    def game(self,hand=('discard',NATIVE),board=(),enemy_hand=(),deck=('b',)*7):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,board=('a',),deck=('b',)*7,mana=10,max_mana=10),
        ),seed=51),registry())
    def play(self,g,cid,target=None,player=1):
        eid=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(player,eid,target));return eid
    def bodies(self,g,player=1):return tuple(g.state.entities[i]for i in g.state.players[player].board if g.state.entities[i].card_id==NATIVE)
    def choose(self,g,name='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(name,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));h=Game.from_snapshot(s,registry())
        self.assertEqual(h.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),s);return h

    def test_complete_raw_pin_and_native_current_printed_face(self):
        raw=evidence();original=next(x for x in json.loads((PATH.parents[1]/'extracted/cards.json').read_text(encoding='utf-8'))if x['id']==NATIVE)
        self.assertEqual(raw,original);card=registry().card(NATIVE)
        self.assertEqual((card.cost,card.attack,card.health,card.on_discard),(3,3,4,'native.summon'))
        self.assertEqual((card.metadata.classes,card.metadata.rarity),((CardClass.WARLOCK,),Rarity.RARE))
        self.assertIsNone(card.battlecry);self.assertIsNone(card.deathrattle)

    def test_discard_uses_original_summon_to_allocate_one_new_body(self):
        g=self.game();original=g.state.players[1].hand[-1];before=g.state;cause=self.play(g,'discard');body=self.bodies(g)[0]
        self.assertNotEqual(body.id,original);self.assertEqual((body.attack,body.health,body.controller,body.owner),(3,4,1,1))
        self.assertEqual(g.state.next_entity_id,before.next_entity_id+1)
        self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD)
        row=discarded_cards(g.state,1)[0];self.assertEqual((row.entity_id,row.source_id),(original,cause))
        self.assertEqual([e.source_id for e in g.events if e.kind=='minion_summoned'],[body.id]);self.portable(g)

    def test_hand_buff_does_not_become_the_new_summoned_body_recipe(self):
        g=self.game(('buff',NATIVE,'discard'));original=g.state.players[1].hand[1];self.play(g,'buff')
        self.assertEqual((g.state.entities[original].attack,g.state.entities[original].health),(5,7))
        self.play(g,'discard');body=self.bodies(g)[0]
        self.assertEqual((body.attack,body.health,body.damage,body.enchantments),(3,4,0,[]));self.assertNotEqual(body.id,original);self.portable(g)

    def test_deck_buff_and_hand_acquisition_do_not_redefine_printed_recipe(self):
        g=self.game(('buffdeck','draw2'),deck=(NATIVE,'discard'));self.play(g,'buffdeck');self.play(g,'draw2')
        original=g.state.players[1].hand[0];self.assertEqual(g.state.entities[original].attack,5)
        self.play(g,'discard');self.assertEqual((self.bodies(g)[0].attack,self.bodies(g)[0].health),(3,4));self.portable(g)

    def test_normal_manual_play_preserves_original_hand_buff_and_entity(self):
        g=self.game(('buff',NATIVE));original=g.state.players[1].hand[1];self.play(g,'buff');self.play(g,NATIVE)
        body=self.bodies(g)[0];self.assertEqual((body.id,body.attack,body.health),(original,5,7))
        self.assertEqual(discarded_cards(g.state,1),());self.assertEqual(g.state.death_history,[]);self.portable(g)

    def test_full_board_fails_without_new_allocation_or_losing_discard_fact(self):
        g=self.game(board=('a',)*7);before=g.state;self.play(g,'discard')
        self.assertEqual(self.bodies(g),());self.assertEqual(g.state.next_entity_id,before.next_entity_id)
        self.assertEqual(len(discarded_cards(g.state,1)),1)
        self.assertEqual([dict(e.data)['reason']for e in g.events if e.kind=='summon_failed'],['board_full']);self.portable(g)

    def test_last_slot_is_filled_once_and_later_physical_discard_fails_separately(self):
        g=self.game(('many',NATIVE,NATIVE),board=('a',)*6);self.play(g,'many')
        self.assertEqual((len(self.bodies(g)),len(g.state.players[1].board)),(1,7))
        self.assertEqual(len(discarded_cards(g.state,1)),2)
        self.assertEqual(len([e for e in g.events if e.kind=='summon_failed']),1);self.portable(g)

    def test_two_same_named_physical_discards_create_distinct_new_bodies(self):
        g=self.game(('many',NATIVE,NATIVE));originals=g.state.players[1].hand[1:];self.play(g,'many')
        self.assertEqual([r.entity_id for r in discarded_cards(g.state,1)],originals)
        ids=[e.id for e in self.bodies(g)];self.assertEqual(len(set(ids)),2);self.assertTrue(set(ids).isdisjoint(originals));self.portable(g)

    def test_stale_reference_and_empty_selection_do_not_duplicate_summons_or_rng(self):
        g=self.game(('twice',NATIVE));rng=g.snapshot()['rng_state'];self.play(g,'twice')
        self.assertEqual((len(self.bodies(g)),len(discarded_cards(g.state,1))),(1,1));self.assertEqual(g.snapshot()['rng_state'],rng)
        g=self.game(('empty',));rng=g.snapshot()['rng_state'];self.play(g,'empty')
        self.assertEqual(self.bodies(g),());self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

    def test_enemy_discard_creates_body_for_affected_player(self):
        g=self.game(('enemy',),enemy_hand=(NATIVE,));self.play(g,'enemy')
        self.assertEqual(self.bodies(g),());body=self.bodies(g,2)[0]
        self.assertEqual((body.controller,body.owner),(2,2));self.assertEqual(len(discarded_cards(g.state,2)),1);self.portable(g)

    def test_transferred_hand_owner_is_separate_from_new_summon_owner(self):
        g=self.game(('transfer',NATIVE),enemy_hand=('discard',));original=g.state.players[1].hand[-1]
        self.play(g,'transfer');g.apply(EndTurn(1));self.play(g,'discard',player=2)
        body=self.bodies(g,2)[0];row=discarded_cards(g.state,2)[0]
        self.assertEqual((row.entity_id,row.card.owner,row.player_id),(original,1,2))
        self.assertEqual((body.owner,body.controller),(2,2));self.portable(g)

    def test_burn_deck_destruction_and_normal_move_are_not_self_discard(self):
        g=self.game(('draw2',)+('b',)*9,deck=('b',NATIVE));self.play(g,'draw2')
        self.assertEqual(self.bodies(g),());self.assertEqual(discarded_cards(g.state,1),())
        self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),1);self.portable(g)
        g=self.game(('deckdestroy',),deck=(NATIVE,));self.play(g,'deckdestroy')
        self.assertEqual(self.bodies(g),());self.assertEqual(discarded_cards(g.state,1),());self.portable(g)
        g=self.game(('move',NATIVE));self.play(g,'move');self.assertEqual(self.bodies(g),());self.assertEqual(discarded_cards(g.state,1),());self.portable(g)

    def test_discard_not_death_and_only_new_board_body_later_enters_death_history(self):
        g=self.game(('discard',NATIVE,'kill'));original=g.state.players[1].hand[1];self.play(g,'discard')
        self.assertEqual(g.state.death_history,[]);new=self.bodies(g)[0].id;self.play(g,'kill',new)
        self.assertEqual([d.entity_id for d in g.state.death_history],[new])
        self.assertEqual([r.entity_id for r in discarded_cards(g.state,1)],[original]);self.portable(g)

    def test_new_body_obeys_original_summoning_sickness_and_ready_clock(self):
        g=self.game();self.play(g,'discard');eid=self.bodies(g)[0].id
        self.assertFalse(any(isinstance(a,Attack)and a.attacker_id==eid for a in g.legal_actions()))
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertTrue(any(isinstance(a,Attack)and a.attacker_id==eid for a in g.legal_actions()));self.portable(g)

    def test_bounce_and_reacquisition_can_discard_the_new_native_entity(self):
        g=self.game(('discard',NATIVE,'bounce','discard'));original=g.state.players[1].hand[1]
        self.play(g,'discard');new=self.bodies(g)[0].id;self.play(g,'bounce',new);self.play(g,'discard')
        latest=self.bodies(g)[0].id;self.assertEqual([r.entity_id for r in discarded_cards(g.state,1)],[original,new])
        self.assertEqual(len({original,new,latest}),3);self.portable(g)

    def test_current_hand_copy_is_a_distinct_discard_and_base_summon(self):
        g=self.game(('buff',NATIVE,'copyhand','many'));self.play(g,'buff');self.play(g,'copyhand')
        ids=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==NATIVE]
        self.assertEqual([g.state.entities[i].attack for i in ids],[5,5]);self.play(g,'many')
        self.assertEqual([r.entity_id for r in discarded_cards(g.state,1)],ids)
        self.assertEqual([(e.attack,e.health)for e in self.bodies(g)],[(3,4),(3,4)]);self.portable(g)

    def test_choice_before_discard_recovers_original_physical_selection(self):
        g=self.game(('chosen',NATIVE,'b'));self.play(g,'chosen');self.assertEqual(self.bodies(g),());h=self.portable(g)
        name=next(x.id for x in g.state.pending_choice.options if x.card_id==NATIVE)
        self.choose(g,name);self.choose(h,name);self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(len(self.bodies(g)),1);self.portable(g)

    def test_discard_listener_wait_and_summon_listener_wait_each_restore_once(self):
        g=self.game(board=('before','after'));self.play(g,'discard');self.assertEqual(self.bodies(g),());h=self.portable(g)
        self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(len(self.bodies(g)),1)
        self.assertIsNotNone(g.state.pending_choice);h=self.portable(g);self.choose(g);self.choose(h)
        self.assertEqual(g.snapshot(),h.snapshot());self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1);self.portable(g)

    def test_choice_failure_rolls_back_before_queued_summon_without_duplicate_body(self):
        g=self.game(board=('before',));self.play(g,'discard');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.bodies(g),());self.choose(g)
        self.assertEqual(len(self.bodies(g)),1);self.portable(g)

    def test_late_error_rolls_back_allocation_discard_and_summon_event(self):
        g=self.game(('latefault',NATIVE));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'latefault')
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.bodies(g),());self.assertEqual(discarded_cards(g.state,1),())

    def test_players_receive_public_body_and_never_private_original_facts(self):
        g=self.game(board=('before',));self.play(g,'discard');before=g.snapshot()
        for player in (1,2):
            view=json.dumps(g.for_player(player).observe());g.for_player(player).legal_actions()
            for field in ('discard_history','hand_entry_id','zone_epoch','RuleContext','resolution_frame','behavior_id'):
                self.assertNotIn(field,view)
        self.assertEqual(g.snapshot(),before);self.choose(g)
        self.assertIn('"card_id": "KAR_205"',json.dumps(g.observe(2)));self.portable(g)

    def test_independent_source_never_adds_an_extra_play_cast_or_death(self):
        g=self.game();cause=self.play(g,'discard')
        self.assertEqual([r.source_id for r in g.state.play_history],[cause])
        self.assertEqual([r.source_id for r in g.state.cast_history],[cause]);self.assertEqual(g.state.death_history,[])
        self.assertEqual(g.snapshot()['schema_version'],265);self.portable(g)
