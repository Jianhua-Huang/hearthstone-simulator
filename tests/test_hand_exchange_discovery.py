"""Original physical discoveries, atomic slots and shared hand movement."""
from functools import lru_cache
from pathlib import Path
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import Game,PlayCard,PlayerSetup,Scenario,SelectChoice
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,Destroy,GainArmor,InvokeBehavior,RandomDamage,RequestChoice)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.hand_exchange_discovery import DiscoverHandExchange,SelectHandExchange
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,ChoicePurpose,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.zones import CardReference,ModifyStoredCost,MoveCard

ROOT=Path(__file__).resolve().parents[1]
B=ROOT/'outputs/card-integration-20261014/k729-past-physical-inventory-weapons'
P='exchange.';THEOTAR='REV_238'
A,BODY,C,D,FULL,MOVE,DISCOUNT,FAIL,CHECK,WAIT,REMOVE,STALE=(P+x for x in
    ('own','other','third','fourth','fill','move','discount','fail','check','wait','remove','stale'))
CTX=GenerationContext(P+'fixture','experimental')


@lru_cache(None)
def registry(role='writer'):
    r=defaults();m=json.loads((B/'manifest-02.json').read_text(encoding='utf8'))
    raw=next(x for x in json.loads((ROOT/m['source']).read_text(encoding='utf8'))if x['id']==THEOTAR)
    r.register_behavior(P+'start',lambda c:(DiscoverHandExchange(c.player_id,c.source_id),))
    card=CardDefinition(THEOTAR,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        battlecry=P+'start',metadata=metadata_from_record(raw))
    r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    for cid in(A,BODY,C,D):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=3,attack=2,health=4,metadata=metadata(collectible=False,tribes=())))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    def move(c):
        card=c.state.entities[c.state.players[c.player_id].hand[0]]
        return(MoveCard(CardReference.capture(card),3-c.player_id,Zone.HAND,source_id=c.source_id),)
    spells={FULL:lambda c:(AddToHand(c.player_id,A,c.source_id),DiscoverHandExchange(c.player_id,c.source_id)),
        MOVE:move,DISCOUNT:lambda c:(ModifyStoredCost(CardReference.capture(c.state.entities[c.target_id]),CostSpec(set_to=1),c.source_id),)}
    for cid,body in spells.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')if cid==DISCOUNT else None,
            metadata=metadata(collectible=False,tribes=())))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('Exchange rollback probe')))
    def check(c):
        if c.state.entities[c.event.source_id].card_id not in(THEOTAR,FULL):return()
        own=[c.state.entities[i].card_id for i in c.state.players[1].hand]
        enemy=[c.state.entities[i].card_id for i in c.state.players[2].hand]
        if BODY not in own or A not in enemy:raise ValueError('Hand observer saw half of a physical exchange')
        return()
    def wait(c):
        if c.event.target_id is not None:return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fault',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    def remove(c):return(Destroy(c.event.source_id,c.source_id),)if c.event.target_id is None else()
    def stale(c):
        if c.event.target_id is not None:return()
        selected=c.state.card_discovery_history[-1].result.selected[0]
        e=c.state.entities[selected.entity_id]
        return(MoveCard(CardReference.capture(e),c.player_id,Zone.DECK,position='top',source_id=c.source_id),)
    for cid,body,event in((CHECK,check,'card_moved_to_hand'),(WAIT,wait,'card_discovered'),(REMOVE,remove,'card_discovered'),(STALE,stale,'card_discovered')):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=20,
            triggers=(TriggerSpec(event,cid),),metadata=metadata(collectible=False,tribes=())))
    r.validate();return r


class HandExchangeDiscoveryTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(lambda mode,role:registry(role))
    mode='small'
    def game(self,hand=None,enemy=(BODY,),watch=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(THEOTAR,A)if hand is None else hand,
            deck=(C,)*8,mana=40,max_mana=40,mana_cap=40,armor=100,weapon_card_id=watch),
            PlayerSetup('HERO_08',hand=enemy,deck=(D,)*8,mana=40,max_mana=40,mana_cap=40,armor=100)),
            seed=729,generation_context=CTX),registry())
    def pick(self,g,index=0):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(c.options[index].id,)))
    def views(self,g):
        for player in(1,2):
            view=json.dumps(g.for_player(player).observe())
            for key in('resolution_frame','rng_state','original_discovery_offer','SelectHandExchange'):
                self.assertNotIn(key,view)

    def test_real_Theotar_has_two_actual_discoveries_and_swaps_original_entities(self):
        g=self.game();own=self.entity(g,A).id;other=self.entity(g,BODY,2).id;self.play(g,THEOTAR)
        self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.CARD_DISCOVERY);self.pick(g)
        self.assertEqual(len(g.state.card_discovery_history),1);self.pick(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.card_discovery_history),2)
        self.assertEqual(g.state.players[1].hand,[other]);self.assertEqual(g.state.players[2].hand,[own])
        self.assertEqual([e.target_id for e in g.events if e.kind=='card_discovered'],[None,other]);self.portable(g)

    def test_full_opponent_hand_does_not_burn_a_selected_card(self):
        g=self.game(hand=(THEOTAR,)+(A,)*9,enemy=(BODY,)*10,watch=CHECK);self.play(g,THEOTAR);self.pick(g);self.pick(g)
        self.assertEqual((len(g.state.players[1].hand),len(g.state.players[2].hand)),(9,10))
        self.assertFalse(any(e.kind=='card_burned'for e in g.events));self.portable(g)

    def test_both_full_hands_exchange_atomically_before_move_observers(self):
        g=self.game(hand=(FULL,)+(A,)*9,enemy=(BODY,)*10,watch=CHECK);self.play(g,FULL);self.pick(g);self.pick(g)
        self.assertEqual((len(g.state.players[1].hand),len(g.state.players[2].hand)),(10,10))
        self.assertFalse(any(e.kind=='card_burned'for e in g.events));self.portable(g)

    def test_duplicate_faces_remain_distinct_physical_options(self):
        g=self.game(hand=(THEOTAR,)+(A,)*5,enemy=(BODY,)*5);self.play(g,THEOTAR)
        c=g.state.pending_choice;self.assertEqual(len(c.options),3);self.assertEqual(len({o.entity_id for o in c.options}),3)
        self.pick(g);c=g.state.pending_choice;self.assertEqual(len({o.entity_id for o in c.options}),3)
        self.pick(g);self.portable(g)

    def test_both_real_selection_waits_restore_clone_and_replay(self):
        g=self.game(enemy=(BODY,C,D));self.play(g,THEOTAR);self.views(g);g=self.portable(g);self.pick(g)
        self.views(g);g=self.portable(g);self.pick(g);self.portable(g)

    def test_first_discovery_notification_wait_keeps_second_original_stage(self):
        g=self.game(watch=WAIT);self.play(g,THEOTAR);self.pick(g)
        self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.EFFECT);old=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),old);g=self.portable(g);self.choose(g);self.pick(g);self.portable(g)

    def test_source_death_after_first_discovery_does_not_cancel_accepted_exchange(self):
        g=self.game(watch=REMOVE);sid=self.play(g,THEOTAR);self.pick(g)
        self.assertEqual(g.state.entities[sid].zone,Zone.GRAVEYARD);self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);self.pick(g);self.assertEqual(len(g.state.card_discovery_history),2);self.portable(g)

    def test_departed_first_selected_card_does_not_rebind_to_a_new_zone(self):
        g=self.game(watch=STALE);own=self.entity(g,A).id;other=self.entity(g,BODY,2).id;self.play(g,THEOTAR);self.pick(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.entities[own].zone,Zone.DECK)
        self.assertIn(other,g.state.players[2].hand);self.assertEqual(len(g.state.card_discovery_history),1);self.portable(g)

    def test_hand_transfer_preserves_original_local_cost_and_physical_owner(self):
        g=self.game(hand=(DISCOUNT,THEOTAR,A));own=self.entity(g,A).id;self.play(g,DISCOUNT,own)
        old=tuple(g.state.entities[own].enchantments);self.play(g,THEOTAR);self.pick(g);self.pick(g)
        self.assertEqual(tuple(g.state.entities[own].enchantments),old);self.assertEqual(g.state.entities[own].owner,1)
        self.assertEqual(g.state.entities[own].controller,2);self.portable(g)

    def test_existing_single_hand_move_keeps_normal_capacity_and_identity(self):
        g=self.game(hand=(MOVE,A));own=self.entity(g,A).id;self.play(g,MOVE)
        self.assertEqual(g.state.entities[own].controller,2);self.assertIn(own,g.state.players[2].hand);self.portable(g)
        g=self.game(hand=(MOVE,A),enemy=(BODY,)*10);own=self.entity(g,A).id;self.play(g,MOVE)
        self.assertEqual(g.state.entities[own].zone,Zone.GRAVEYARD);self.assertTrue(any(e.kind=='card_burned'for e in g.events))

    def test_empty_hand_has_no_exchange_no_fake_discovery_and_no_extra_random_selection(self):
        for hand,enemy in(((THEOTAR,),()),((THEOTAR,A),()),((THEOTAR,),(BODY,))):
            g=self.game(hand=hand,enemy=enemy);self.play(g,THEOTAR)
            self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.card_discovery_history,[])

    def test_wrong_player_and_unknown_option_are_atomic_and_views_keep_private_material_hidden(self):
        g=self.game();self.play(g,THEOTAR);old=g.snapshot();c=g.state.pending_choice
        for player,key in((2,c.options[0].id),(1,'absent')):
            with self.assertRaises((IllegalAction,ResolutionError)):g.apply(SelectChoice(player,c.id,(key,)))
            self.assertEqual(g.snapshot(),old)
        self.views(g)


if __name__=='__main__':unittest.main()
