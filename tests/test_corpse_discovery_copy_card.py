"""Blood Clone binds the selected hand object, one payment and ordinary summon."""
from copy import deepcopy
from dataclasses import fields,is_dataclass,replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.corpse_discovery_copy_card import CARD,POOL_ID,QUERY,load_batch,register_corpse_discovery_copy_card
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,Game,PlayCard,
    PlayerSetup,Registry,Scenario,SelectChoice,SnapshotError,SpellSchool,TriggerSpec,Zone)
from hs_sim.engine.effects import (AddToHand,ChoiceOption,GainArmor,GainResource,InvokeBehavior,
    RequestChoice,SpendResource,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import Rarity,Resource,Runes,SummonQuantitySpec,SummonStats
from hs_sim.engine.pools import DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference,MoveCard
from hs_sim.targets import canonical_digest

P='k205.'
HERO,A,B,BC,OTHER,SPELL,FOREIGN,UNKNOWN,WATCH,DOUBLE=(P+x for x in
    ('hero','a','b','bc','other','spell','foreign','unknown','watch','double'))
CTX=GenerationContext('k205-complete-explicit-experiment','experimental')
MEMBERS=(A,B,BC,OTHER,SPELL,FOREIGN)


def metadata(collectible=False,cls=CardClass.NEUTRAL):
    return CardMetadata(collectible,(cls,),Rarity.COMMON if collectible else None,
                        tribes=(),factions=(),subtypes=(),runes=Runes() if cls==CardClass.DEATH_KNIGHT else None)


@lru_cache(None)
def registry(mode=None,members=MEMBERS,pool=True):
    r=Registry(P+str((mode,members,pool)));register_corpse_discovery_copy_card(r)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=60,metadata=metadata(cls=CardClass.DEATH_KNIGHT)))
    r.register_behavior(P+'bc',lambda c:(GainArmor(c.player_id,99),))
    for cid,cost,atk,hp,cls in ((A,5,3,4,CardClass.NEUTRAL),(B,5,4,5,CardClass.DEATH_KNIGHT),
                                (BC,5,1,6,CardClass.NEUTRAL),(OTHER,4,2,2,CardClass.NEUTRAL)):
        card=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=atk,health=hp,
            battlecry=P+'bc'if cid==BC else None,metadata=metadata(True,cls))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_behavior(P+'empty',lambda c:())
    r.register_behavior(P+'auto',lambda c:(CastSpell(c.player_id,CARD,c.source_id),))
    r.register_card(CardDefinition(P+'auto',P+'auto',CardType.SPELL,on_play=P+'auto'))
    card=CardDefinition(SPELL,SPELL,CardType.SPELL,cost=5,on_play=P+'empty',metadata=metadata(True))
    r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    for cid,cls in ((FOREIGN,CardClass.MAGE),(UNKNOWN,CardClass.NEUTRAL)):
        r.register_pool_card(PoolCard(cid,CardType.MINION,5,metadata(True,cls)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'k205-experiment-v1',CTX.target_id,CTX.mode,
                                         tuple(PoolMember(c)for c in members),complete=True))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=30,
        summon_quantities=(SummonQuantitySpec(2,(CardType.SPELL,)),)))
    r.register_behavior(P+'fail',lambda c:(_ for _ in ()).throw(ResolutionError('K205 deliberate failure')))
    def watch(c):
        if mode=='spent_wait' or mode=='spent_fill':
            if c.event.player_id!=c.player_id:return ()
        elif mode=='summon_wait':
            if c.event.player_id!=c.player_id:return ()
        else:
            source=c.state.entities.get(c.event.source_id)
            if source is None or source.card_id!=CARD:return ()
        if mode in('created_fill','spent_fill'):
            return tuple(Summon(c.player_id,A)for _ in range(7))
        if mode=='choice_fill':return (AddToHand(c.player_id,OTHER,c.source_id),)
        if mode=='created_buff':
            return (BuffStoredCard(CardReference.capture(c.state.entities[c.event.target_id]),4,4,c.source_id),)
        if mode=='created_move':
            return (MoveCard(CardReference.capture(c.state.entities[c.event.target_id]),c.player_id,Zone.DECK,source_id=c.source_id),)
        if mode=='created_gain':return (GainResource(c.player_id,Resource.CORPSES,5),)
        if mode=='created_drain':return (SpendResource(c.player_id,Resource.CORPSES,5),)
        if mode=='created_fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue'),
            ChoiceOption('bad','Rollback',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(P+'watch',watch)
    event='resource_spent'if mode in('spent_wait','spent_fill')else'minion_summoned'if mode=='summon_wait'else'choice_selected'if mode=='choice_fill'else'card_created'
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,
        triggers=(TriggerSpec(event,P+'watch'),)if mode else()))
    r.validate();return r


class CorpseDiscoveryCopyTests(unittest.TestCase):
    def game(self,corpses=5,hand=(CARD,),board=(),mode=None,actor=1,members=MEMBERS,pool=True):
        self.config=(mode,members,pool)
        if mode:board=(*board,WATCH)
        own=PlayerSetup(HERO,hand=hand,board=board,deck=(SPELL,)*10,corpses=corpses,
                        mana=80,max_mana=80,mana_cap=80)
        other=PlayerSetup(HERO,deck=(SPELL,)*10,mana=80,max_mana=80,mana_cap=80)
        return Game.from_scenario(Scenario((own,other)if actor==1 else(other,own),
            active_player=actor,seed=205,generation_context=CTX),registry(*self.config))

    def play(self,g):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==CARD)
        g.apply(PlayCard(p,eid));return eid

    def pick(self,g,cid=A):
        q=g.state.pending_choice;option=next(o for o in q.options if o.card_id==cid)
        g.apply(SelectChoice(q.player_id,q.id,(option.id,)))

    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def cards(self,g,zone,player=1):
        return [g.state.entities[i]for i in getattr(g.state.players[player],zone)
                if g.state.entities[i].card_id in(A,B,BC)]

    def bank(self,g,player=1):return g.state.players[player].resources[Resource.CORPSES]

    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=registry.__wrapped__(*self.config)
        self.assertEqual(Game.from_snapshot(deepcopy(s),r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)

    def test_original_shadow_spell_blood_runes_and_two_primary_faces(self):
        d=load_batch();r=registry();c=r.card(CARD);raw=d['cards'][0]['record']
        self.assertEqual(canonical_digest(raw),d['cards'][0]['record_sha256'])
        self.assertEqual((c.cost,c.spell_school,c.metadata.classes),(3,SpellSchool.SHADOW,(CardClass.DEATH_KNIGHT,)))
        self.assertEqual(raw['tags']['COST_BLOOD'],2);self.assertEqual(len(d['official_observations']),2)

    def test_discovery_selects_only_current_class_five_cost_minions(self):
        g=self.game();self.play(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{A,B,BC})
        self.assertEqual(self.bank(g),5);self.assertFalse(self.cards(g,'board'))
        self.portable(g)

    def test_real_pick_retains_selected_hand_card_and_summons_its_copy(self):
        g=self.game();source=self.play(g);self.pick(g)
        hand,=self.cards(g,'hand');body,=self.cards(g,'board')
        self.assertEqual((hand.card_id,body.card_id),(A,A));self.assertNotEqual(hand.id,body.id)
        self.assertEqual((body.attack,body.max_health),(3,4))
        self.assertEqual((g.state.players[1].mana,self.bank(g)),(77,0))
        self.assertEqual(len(g.state.corpse_spend_history),1)
        child,=g.state.card_summon_history
        self.assertEqual(child.request.cause.source.entity_id,source)
        self.assertEqual(child.request.materials[0].origin.entity_id,hand.id)
        self.portable(g)

    def test_insufficient_corpses_keeps_discovered_card_without_partial_payment(self):
        for amount in (0,4):
            g=self.game(corpses=amount);self.play(g);self.pick(g)
            self.assertEqual((len(self.cards(g,'hand')),len(self.cards(g,'board')),self.bank(g)),(1,0,amount))
            self.assertFalse(g.state.corpse_spend_history)

    def test_more_than_five_corpses_spends_exactly_five(self):
        g=self.game(corpses=9);self.play(g);self.pick(g,B)
        self.assertEqual(self.bank(g),4);self.assertEqual(self.cards(g,'board')[0].card_id,B)

    def test_full_board_keeps_discovery_and_does_not_spend_corpses(self):
        g=self.game(board=(A,)*7);self.play(g);self.pick(g,B)
        self.assertEqual(self.bank(g),5);self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(self.cards(g,'hand')[0].card_id,B)
        self.assertFalse(g.state.corpse_spend_history)

    def test_hand_overflow_burns_selected_card_but_summons_printed_copy(self):
        g=self.game(hand=(CARD,*([SPELL]*9)),mode='choice_fill')
        self.play(g);self.pick(g)
        self.assertEqual(len(self.cards(g,'hand')),0);self.assertEqual(len(self.cards(g,'board')),1)
        self.assertEqual(self.bank(g),0);self.assertTrue(any(e.kind=='card_burned'for e in g.events))
        self.assertFalse(g.state.discard_history or g.state.death_history)
        self.portable(g)

    def test_automatic_real_cast_selects_once_and_uses_one_corpse_payment(self):
        g=self.game(hand=(P+'auto',))
        eid=g.state.players[1].hand[0];g.apply(PlayCard(1,eid))
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len(self.cards(g,'hand')),1);self.assertEqual(len(self.cards(g,'board')),1)
        self.assertEqual(self.cards(g,'hand')[0].card_id,self.cards(g,'board')[0].card_id)
        self.assertEqual(self.bank(g),0);self.assertEqual(len(g.state.corpse_spend_history),1)
        self.assertEqual(g.state.players[1].mana,80);self.portable(g)

    def test_copy_does_not_trigger_selected_minions_battlecry(self):
        g=self.game();self.play(g);self.pick(g,BC)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)

    def test_summon_quantity_reuses_one_selected_material_and_one_payment(self):
        g=self.game(board=(DOUBLE,));self.play(g);self.pick(g)
        self.assertEqual([e.card_id for e in self.cards(g,'board')],[A,A])
        self.assertEqual(self.bank(g),0);self.assertEqual(len(g.state.corpse_spend_history),1)
        self.assertEqual(len(self.cards(g,'hand')),1)

    def test_creation_reaction_buff_does_not_rewrite_frozen_copy_material(self):
        g=self.game(mode='created_buff');self.play(g);self.pick(g)
        hand,=self.cards(g,'hand');body,=self.cards(g,'board')
        self.assertEqual((hand.attack,hand.max_health),(7,8))
        self.assertEqual((body.attack,body.max_health),(3,4))
        self.portable(g)

    def test_creation_reaction_moving_original_still_uses_accepted_copy_material(self):
        g=self.game(mode='created_move');self.play(g);self.pick(g)
        self.assertFalse(self.cards(g,'hand'));self.assertEqual(len(self.cards(g,'board')),1)
        self.assertTrue(self.cards(g,'deck'));self.portable(g)

    def test_creation_reaction_filling_board_prevents_corpse_payment(self):
        g=self.game(mode='created_fill');self.play(g);self.pick(g)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(self.bank(g),5)
        self.assertFalse(g.state.corpse_spend_history)

    def test_creation_reaction_resource_gain_or_spend_is_seen_by_payment(self):
        for mode,amount,expected in (('created_gain',0,1),('created_drain',5,0)):
            g=self.game(corpses=amount,mode=mode);self.play(g);self.pick(g)
            self.assertEqual(len(self.cards(g,'board')),expected);self.assertEqual(self.bank(g),0)

    def test_spend_reaction_filling_board_does_not_refund_completed_payment(self):
        g=self.game(mode='spent_fill');self.play(g);self.pick(g)
        self.assertEqual(self.bank(g),0);self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(len(g.state.corpse_spend_history),1)

    def test_second_seat_discovers_pays_and_summons_for_itself(self):
        g=self.game(actor=2);self.play(g);self.pick(g)
        self.assertEqual((self.bank(g,2),len(self.cards(g,'board',2)),len(self.cards(g,'hand',2))),(0,1,1))
        self.assertFalse(self.cards(g,'board',1))

    def test_empty_eligible_pool_does_not_spend_corpses_or_rng(self):
        g=self.game(members=(OTHER,SPELL,FOREIGN));before=g.snapshot()['rng_state']
        self.play(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.bank(g),5)
        self.assertEqual(g.snapshot()['rng_state'],before)

    def test_unknown_eligible_pool_member_rejects_before_sampling_without_cropping(self):
        g=self.game(members=(*MEMBERS,UNKNOWN));before=g.snapshot()
        with self.assertRaises(Exception)as caught:self.play(g)
        self.assertIn(UNKNOWN,str(caught.exception));self.assertEqual(g.snapshot(),before)

    def test_missing_host_pool_is_explicit_and_rolls_back_the_play(self):
        g=self.game(pool=False);before=g.snapshot()
        with self.assertRaises(Exception)as caught:self.play(g)
        self.assertIn(POOL_ID,str(caught.exception));self.assertEqual(g.snapshot(),before)

    def test_creation_waiting_restores_before_payment_with_frozen_original_material(self):
        g=self.game(mode='created_wait');self.play(g);self.pick(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.bank(g),5)
        self.assertFalse(self.cards(g,'board'));self.portable(g)
        self.choose(g);self.assertEqual(self.bank(g),0);self.assertEqual(len(self.cards(g,'board')),1)

    def test_spend_waiting_restores_after_one_payment_and_before_summon(self):
        g=self.game(mode='spent_wait');self.play(g);self.pick(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.bank(g),0)
        self.assertFalse(self.cards(g,'board'));self.portable(g)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g)
        self.assertEqual(len(self.cards(g,'board')),1);self.assertEqual(len(g.state.corpse_spend_history),1)

    def test_summon_waiting_restores_remaining_quantity_without_second_payment(self):
        g=self.game(board=(DOUBLE,),mode='summon_wait');self.play(g);self.pick(g)
        for _ in range(2):
            self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g)
        self.assertEqual(self.bank(g),0);self.assertEqual(len(g.state.corpse_spend_history),1)

    def test_creation_failure_rolls_back_to_original_discovery_choice(self):
        g=self.game(mode='created_fail');self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g)
        self.assertEqual(g.snapshot(),before)

    def test_corpse_copy_declaration_rejects_other_shapes_and_old_schema(self):
        g=self.game();self.play(g)
        branch=g._frame.options[0].effects[0];valid=branch.batch.spec
        for changed in (dict(summon_copy_corpse_cost=True),dict(summon_copy_corpse_cost=0),
                        dict(summon_copy_stats=SummonStats(2,3)),dict(destination='board'),
                        dict(cause=None),dict(discoveries=2),dict(keep_all_corpse_cost=5)):
            with self.assertRaises(ValueError):replace(valid,**changed)
        self.assertIsNone(DiscoverFromPool(1,POOL_ID).summon_copy_corpse_cost)
        snap=g.snapshot();snap['schema_version']=402
        with self.assertRaises(SnapshotError):Game.from_snapshot(snap,g.registry)

    def test_deferred_copy_capacity_gate_rejects_changed_player_cost_and_branch(self):
        g=self.game(mode='created_wait');self.play(g);self.pick(g)
        def walk(value):
            if isinstance(value,SpendResource):yield value
            if isinstance(value,(tuple,list)):
                for x in value:yield from walk(x)
            elif is_dataclass(value):
                for f in fields(value):yield from walk(getattr(value,f.name))
        payment=next(walk(g._frame))
        for changes in (dict(player_id=2),dict(amount=6),dict(required=True),
                        dict(on_failure=(AddToHand(1,A),)),dict(on_success=(Summon(1,A),))):
            with self.assertRaises(ValueError):replace(payment,**changes)

    def test_player_projections_hide_copy_payment_receipts_and_queries_are_pure(self):
        g=self.game();self.play(g);before=g.snapshot()
        for player in(1,2):
            public=json.dumps(g.observe(player))+json.dumps(g.player_events(player))
            for key in('summon_copy_corpse_cost','CopyEntryMaterial','corpse_spend_history','resolution_frame','rng_state'):
                self.assertNotIn('"'+key+'"',public)
            g.for_player(player).legal_actions()
        self.assertEqual(g.snapshot(),before)
