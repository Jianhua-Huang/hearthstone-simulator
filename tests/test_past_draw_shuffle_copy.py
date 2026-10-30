"""Real frozen draw/shuffle copies, pre-entry grants and ordinary expiry."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_draw_shuffle_copy as native
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayCard,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial,CopyEntryMaterial,validate_scope
from hs_sim.engine.deck_shuffles import ShuffleDeckCards,shuffled
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,CopyMinion,Draw,GainArmor,
    InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,Keyword,RewindSpec,SummonQuantitySpec,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.registry import Registry,UnsupportedDefinitionError
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause
from hs_sim.engine.zones import AddToDeck,CardReference,CopyCard,ModifyStoredCost,MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format

BETRUG,TAK=native.ROOTS
P='k708.';A=P+'battlecry';B=P+'small';C=P+'plain';R=P+'reborn';Q=P+'quantity';SPELL=P+'spell'
DRAW=P+'draw';DRAW_OTHER=P+'draw_other';ADD=P+'add';BUFF=P+'buff';BUFF_DECK=P+'buff_deck';HUSH=P+'hush';RETURN=P+'return'
RETRY_DRAW=P+'retry_draw'
GIVE=P+'give';FORM=P+'form';COPY=P+'copy';SHUFFLE=P+'shuffle';MANY=P+'many';ENEMY=P+'enemy';TOP=P+'top';MOVE=P+'move';COPY_DECK=P+'copy_deck';UNKNOWN=P+'unknown';BAD=P+'bad';FAIL=P+'fail'
WAIT_ENTRY=P+'entry_wait';WAIT_DRAW=P+'draw_wait';WAIT_INSERT=P+'insert_wait';WAIT_COPY=P+'copy_wait'
HELPERS=(A,B,C,R,Q,SPELL,DRAW,RETRY_DRAW,DRAW_OTHER,ADD,BUFF,BUFF_DECK,HUSH,RETURN,GIVE,FORM,COPY,SHUFFLE,MANY,ENEMY,TOP,MOVE,COPY_DECK,UNKNOWN,BAD,WAIT_ENTRY,WAIT_DRAW,WAIT_INSERT,WAIT_COPY)


@lru_cache(None)
def host(role='writer'):
    h=build_cn37_local_pool_format();r=h.registry;meta=metadata(collectible=False)
    r.register_behavior(P+'bc',lambda c:(GainArmor(c.player_id,5),))
    for cid,attack,hp in((A,3,8),(B,1,1),(C,2,12),(R,2,5),(Q,1,12)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=2,attack=attack,health=hp,metadata=meta,
            battlecry=P+'bc'if cid==A else None,keywords=(Keyword.REBORN,)if cid==R else(),
            summon_quantities=(SummonQuantitySpec(),)if cid==Q else()))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K708 intentional original-copy continuation failure')))
    def failure(c):return ChoiceOption('fault','Fail after RNG',(
        RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))
    def waiting(c):
        entity=c.state.entities.get(c.event.target_id)
        if c.event.kind=='minion_summoned':
            if entity is None or entity.origin_entity_id is None or entity.card_id not in(A,R):return()
            if Keyword.RUSH not in entity.keywords or not any(a.behavior_id==native.PREFIX+'expire'for a in entity.abilities):
                raise ResolutionError('Betrug copy was notified before its complete temporary entry grant')
        if c.event.kind=='card_drawn'and(entity is None or entity.kind!=CardType.MINION):return()
        if c.event.kind=='card_created':
            source=c.state.entities.get(c.event.source_id)
            if source is None or source.card_id!=TAK:return()
        extra=()
        if c.event.kind=='card_drawn':
            extra=(ChoiceOption('move','Move drawn original',(MoveCard(CardReference.capture(entity),c.player_id,Zone.DECK,source_id=c.source_id),)),)
        if c.event.kind in('card_added_to_deck','card_moved_to_deck','card_shuffled'):
            extra=(ChoiceOption('move','Move inserted original',(MoveCard(CardReference.capture(entity),c.player_id,Zone.HAND,source_id=c.source_id),)),)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),failure(c),*extra),c.source_id),)
    r.register_behavior(P+'wait',waiting)
    for cid,events in((WAIT_ENTRY,('minion_summoned',)),(WAIT_DRAW,('card_drawn',)),
            (WAIT_INSERT,tuple(sorted(native.INSERT_EVENTS))),(WAIT_COPY,('card_created',))):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=20,metadata=meta,
            triggers=tuple(TriggerSpec(e,P+'wait')for e in events)))
    def buff(c):
        e=c.state.entities[c.target_id];ref=CardReference.capture(e)
        return(BuffStoredCard(ref,2,3,c.source_id),ModifyStoredCost(ref,CostSpec(set_to=1),c.source_id))
    def buff_deck(c):
        e=c.state.entities[c.state.players[c.player_id].deck[0]]
        return(BuffStoredCard(CardReference.capture(e),2,3,c.source_id),)
    def moved(c):
        return shuffled(c,(MoveCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,Zone.DECK,position='random',source_id=c.source_id),))
    def copied_deck(c):
        material=CapturedCardCopyMaterial.capture(c.state,c.state.entities[c.target_id])
        return shuffled(c,(CopyCard(material,c.player_id,Zone.DECK,mode='current',source_id=c.source_id),))
    def bad(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==A)
        material=CopyEntryMaterial.capture(c.state,e,'stored_copy','current',registry=r,player_id=c.player_id,
            minion_grant=replace(native.GRANT,identity='k708.missing_expiry'),grant_source_id=c.source_id)
        return(SummonByCard(c.player_id,(material,),SummonCause.capture(c)),)
    bodies={DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),RETRY_DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),DRAW_OTHER:lambda c:(Draw(3-c.player_id,1,c.source_id),),
        ADD:lambda c:(AddToHand(c.player_id,A,c.source_id),),BUFF:buff,BUFF_DECK:buff_deck,
        HUSH:lambda c:(Silence(c.target_id),),RETURN:lambda c:(ReturnToHand(c.target_id),),
        GIVE:lambda c:(ChangeControl(c.target_id,3-c.player_id),),FORM:lambda c:(Transform(c.target_id,C),),
        COPY:lambda c:(CopyMinion(c.target_id,c.player_id),),
        SHUFFLE:lambda c:shuffled(c,(AddToDeck(c.player_id,A,source_id=c.source_id),)),
        MANY:lambda c:shuffled(c,tuple(AddToDeck(c.player_id,A,source_id=c.source_id)for _ in range(2))),
        ENEMY:lambda c:(ShuffleDeckCards(3-c.player_id,c.player_id,(AddToDeck(3-c.player_id,A,source_id=c.source_id),),c.source_id),),
        TOP:lambda c:(AddToDeck(c.player_id,A,position='top',source_id=c.source_id),),
        MOVE:moved,COPY_DECK:copied_deck,UNKNOWN:lambda c:(AddToDeck(c.player_id,A,source_id=c.source_id),),BAD:bad,SPELL:lambda c:()}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=meta,
            keywords=(Keyword.REWIND,)if cid==RETRY_DRAW else(),rewind=RewindSpec(1)if cid==RETRY_DRAW else None,
            targeting=TargetSpec(zones=(Zone.HAND,Zone.BOARD),kinds=(CardType.MINION,CardType.SPELL))if cid in(BUFF,HUSH,RETURN,GIVE,FORM,COPY,MOVE,COPY_DECK)else None))
    r.validate();return h


@lru_cache(None)
def fixture(role='writer'):
    full=host(role).registry;r=Registry('k708-draw-shuffle-copy-v1')
    for bid,body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):r.register_behavior(bid,body)
    for cid in('HERO_08','HERO_08bp',*HELPERS):r.register_card(full.card(cid))
    native.register_past_draw_shuffle_copy(r);r.validate();return r


class PastDrawShuffleCopyTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=(),watch=None,real_host=False):
        self.mode='host'if real_host else'small'
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40,
            weapon_card_id=watch,hero_power_card_id='HERO_08bp'),PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(C,)*10,
            mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=708,generation_context=host().context if real_host else None),
            self.registry_factory(self.mode,'writer'))
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]
    def copies(self,g,cid=A,p=1):return[g.state.entities[i]for i in g.state.players[p].board if g.state.entities[i].card_id==cid]
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def fault(self,g):
        self.assertIsNotNone(g.state.pending_choice);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_complete_two_faces_original_full_source_and_finite_grant(self):
        d=native.load_batch();self.assertEqual(len(d['original_candidate_ids']),732);self.assertEqual(len(d['official_observations']),6)
        self.assertEqual(len(d['remaining_frontier_ids']),2)
        for row in d['cards']:self.assertEqual(fixture().card(row['record']['id']),native.make_definition(row['record']))
        self.assertEqual(native.GRANT.keywords,(Keyword.RUSH,));self.assertEqual(native.GRANT.special,'turn_end_destroy')

    def test_both_actual_paid_hand_entries(self):
        for cid in native.ROOTS:
            g=self.game((cid,));source=self.play(g,cid)
            self.assertEqual(g.state.entities[source].card_id,cid);self.assertEqual(g.state.players[1].mana,40-g.registry.card(cid).cost)

    def test_betrug_draw_keeps_original_and_current_copy_without_battlecry(self):
        g=self.game((BUFF_DECK,DRAW),board=(BETRUG,),deck=(A,));self.play(g,BUFF_DECK);self.play(g,DRAW)
        original=self.entity(g,A);copy=self.copies(g)[0]
        self.assertNotEqual(copy.id,original.id);self.assertEqual(copy.origin_entity_id,original.id)
        self.assertEqual((copy.attack,copy.max_health,original.attack,original.max_health),(5,11,5,11))
        self.assertIn(Keyword.RUSH,copy.keywords);self.assertNotIn(Keyword.RUSH,original.keywords)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.portable(g)

    def test_betrug_copy_can_rush_minion_but_not_hero_and_dies_at_end(self):
        g=self.game((DRAW,),board=(BETRUG,),deck=(A,),enemy=(B,));self.play(g,DRAW);copy=self.copies(g)[0].id;before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,copy,g.state.players[2].hero_id))
        self.assertEqual(g.snapshot(),before);g.apply(Attack(1,copy,self.unit(g,B,2).id));g.apply(EndTurn(1))
        self.assertEqual(self.copies(g),[]);self.assertEqual(self.hand(g),[A]);self.portable(g)

    def test_betrug_copy_during_opponent_turn_dies_at_that_turn_end(self):
        g=self.game(board=(BETRUG,),deck=(A,),enemy_hand=(DRAW_OTHER,));g.apply(EndTurn(1));self.play(g,DRAW_OTHER,player=2)
        self.assertEqual(len(self.copies(g)),1);g.apply(EndTurn(2));self.assertEqual(self.copies(g),[]);self.assertEqual(self.hand(g),[A])

    def test_betrug_spells_direct_creation_and_enemy_draw_do_not_copy(self):
        g=self.game((DRAW,ADD),board=(BETRUG,),deck=(SPELL,),enemy_hand=(DRAW,));self.play(g,DRAW);self.play(g,ADD)
        self.assertEqual(self.copies(g),[]);g.apply(EndTurn(1));self.play(g,DRAW,player=2);self.assertEqual(self.copies(g),[])

    def test_betrug_burned_draw_is_explicit_successful_hand_policy(self):
        g=self.game((DRAW,)+(C,)*9,board=(BETRUG,),deck=(A,A));self.play(g,DRAW)
        self.assertEqual(len(self.copies(g)),1);self.assertEqual(len(self.hand(g)),10)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(g.state.draw_history[-1].outcome,'burned');self.assertEqual(self.copies(g),[])

    def test_betrug_full_board_retains_draw_without_copy_or_rng(self):
        g=self.game((DRAW,),board=(BETRUG,)+(C,)*6,deck=(A,));rng=g._rng.getstate();self.play(g,DRAW)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(self.hand(g),[A]);self.assertEqual(g._rng.getstate(),rng)

    def test_betrug_quantity_extras_each_receive_complete_temporary_grant(self):
        g=self.game((DRAW,),board=(BETRUG,Q),deck=(A,));self.play(g,DRAW)
        self.assertEqual(len(self.copies(g)),2);self.assertTrue(all(Keyword.RUSH in e.keywords for e in self.copies(g)))
        g.apply(EndTurn(1));self.assertEqual(self.copies(g),[]);self.assertEqual(self.hand(g),[A]);self.portable(g)

    def test_betrug_silenced_source_never_accepts_later_draw(self):
        g=self.game((HUSH,DRAW),board=(BETRUG,),deck=(A,));self.play(g,HUSH,self.unit(g,BETRUG).id);self.play(g,DRAW)
        self.assertEqual(self.copies(g),[]);self.assertEqual(self.hand(g),[A])

    def test_betrug_copy_silence_and_transform_retire_end_trigger(self):
        for op in(HUSH,FORM):
            g=self.game((DRAW,op),board=(BETRUG,),deck=(A,));self.play(g,DRAW);eid=self.copies(g)[0].id;self.play(g,op,eid);g.apply(EndTurn(1))
            self.assertIn(eid,g.state.players[1].board);self.assertNotIn(Keyword.RUSH,g.state.entities[eid].keywords)

    def test_betrug_return_retires_grant_and_normal_replay_has_original_battlecry(self):
        g=self.game((DRAW,RETURN),board=(BETRUG,),deck=(A,));self.play(g,DRAW);copy=self.copies(g)[0].id;self.play(g,RETURN,copy)
        self.assertNotIn(Keyword.RUSH,g.state.entities[copy].keywords);self.assertFalse(any(a.behavior_id==native.PREFIX+'expire'for a in g.state.entities[copy].abilities))
        g.apply(PlayCard(1,copy));g.apply(EndTurn(1));self.assertEqual(len(self.copies(g)),1);self.assertEqual(self.copies(g)[0].id,copy)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,5)

    def test_betrug_control_change_keeps_any_turn_end_death_under_new_controller(self):
        g=self.game((DRAW,GIVE),board=(BETRUG,),deck=(A,));self.play(g,DRAW);copy=self.copies(g)[0].id;self.play(g,GIVE,copy);g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[copy].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[copy].controller,2);self.portable(g)

    def test_betrug_reborn_is_fresh_one_health_without_temporary_rush_or_expiry(self):
        g=self.game((DRAW,),board=(BETRUG,),deck=(R,));self.play(g,DRAW);old=self.copies(g,R)[0].id;g.apply(EndTurn(1))
        reborn=self.copies(g,R)[0];self.assertNotEqual(reborn.id,old);self.assertEqual(reborn.health,1)
        self.assertNotIn(Keyword.RUSH,reborn.keywords);self.assertFalse(any(a.behavior_id==native.PREFIX+'expire'for a in reborn.abilities));self.portable(g)

    def test_betrug_current_board_copy_retains_end_death_on_both_physical_carriers(self):
        g=self.game((DRAW,COPY),board=(BETRUG,),deck=(A,));self.play(g,DRAW);self.play(g,COPY,self.copies(g)[0].id)
        self.assertEqual(len(self.copies(g)),2);g.apply(EndTurn(1));self.assertEqual(self.copies(g),[])

    def test_betrug_first_entry_notification_has_grant_and_wait_restores_once(self):
        g=self.game((DRAW,),board=(BETRUG,),deck=(A,),watch=WAIT_ENTRY);self.play(g,DRAW)
        g=self.portable(g);self.fault(g);self.finish(g);self.assertEqual(len(self.copies(g)),1);g.apply(EndTurn(1));self.assertEqual(self.copies(g),[]);self.portable(g)

    def test_betrug_frozen_original_draw_copy_survives_original_moving_before_delivery(self):
        g=self.game((DRAW,),board=(BETRUG,),deck=(A,),watch=WAIT_DRAW);self.play(g,DRAW)
        g=self.portable(g);self.choose(g,'move');self.finish(g)
        self.assertEqual(self.entity(g,A,zone='deck').card_id,A);self.assertEqual(len(self.copies(g)),1);self.portable(g)

    def test_temporary_copy_grant_declaration_rejects_unrelated_mixed_shapes(self):
        for patch in(dict(keywords=()),dict(keywords=(Keyword.TAUNT,)),dict(attack=1),dict(health=1),dict(identity=None),dict(reborn_policy='full')):
            with self.subTest(patch=patch),self.assertRaises(ValueError):replace(native.GRANT,**patch)
        with self.assertRaises(ValueError):CreatedMinionGrant(keywords=(Keyword.RUSH,))

    def test_temporary_copy_requires_registered_body_before_actual_delivery(self):
        g=self.game((BAD,A));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,BAD)
        self.assertEqual(g.snapshot(),before)

    def test_original_draw_link_requires_both_typed_record_and_publication(self):
        g=self.game((A,),board=(BETRUG,));material=CopyEntryMaterial.capture(g.state,self.entity(g,A),'stored_copy','current',
            registry=g.registry,player_id=1,minion_grant=native.GRANT,grant_source_id=self.unit(g,BETRUG).id)
        for patch in(dict(draw_id=1),dict(draw_event=1),dict(draw_id=True,draw_event=1),dict(draw_id=1,draw_event=0)):
            with self.subTest(patch=patch),self.assertRaises(ValueError):replace(material,**patch)

    def test_original_draw_material_rejects_unknown_record_and_other_hand_residence(self):
        g=self.game((DRAW,),board=(BETRUG,),deck=(A,),watch=WAIT_ENTRY);self.play(g,DRAW)
        material=g.state.card_summon_history[-1].request.materials[0]
        self.assertEqual(material.draw_id,g.state.draw_history[-1].id);self.assertIsNotNone(material.draw_event)
        for forged in(replace(material,draw_id=999),replace(material,origin=replace(material.origin,zone_epoch=material.origin.zone_epoch+1))):
            with self.subTest(forged=forged),self.assertRaises(ValueError):validate_scope(g.state,g.registry,forged)

    def test_true_retry_retires_original_draw_copy_and_rebinds_exact_new_publication(self):
        g=self.game((RETRY_DRAW,),board=(BETRUG,),deck=(A,));self.play(g,RETRY_DRAW);self.portable(g)
        old=g.state.card_summon_history[-1];old_event=old.request.materials[0].draw_event
        self.choose(g,'retry');self.assertEqual(len(g.state.card_summon_history),1)
        current=g.state.card_summon_history[-1];self.assertGreater(current.id,old.id)
        self.assertNotEqual(current.request.materials[0].draw_event,old_event);self.assertEqual(len(self.copies(g)),1);self.portable(g)

    def test_tak_semantic_added_card_copies_actual_inserted_entity_not_a_draw(self):
        g=self.game((SHUFFLE,),board=(TAK,));self.play(g,SHUFFLE);original=self.entity(g,A,zone='deck');copy=self.entity(g,A)
        self.assertNotEqual(original.id,copy.id);self.assertEqual(copy.origin_entity_id,original.id);self.assertEqual(g.state.draw_history,[])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.portable(g)

    def test_tak_two_physical_entries_in_one_operation_each_copy_once(self):
        g=self.game((MANY,),board=(TAK,));self.play(g,MANY)
        self.assertEqual(self.hand(g),[A,A]);self.assertEqual(len(g.state.deck_shuffle_history),1)
        self.assertEqual(g.state.deck_shuffle_history[0].declared_count,2)
        self.assertEqual({g.state.entities[i].origin_entity_id for i in g.state.players[1].hand},set(g.state.players[1].deck));self.portable(g)

    def test_tak_physical_move_preserves_current_stats_cost_and_allocates_new_attachments(self):
        g=self.game((BUFF,MOVE,A),board=(TAK,));original=self.entity(g,A).id;self.play(g,BUFF,original);self.play(g,MOVE,original)
        copy=self.entity(g,A);self.assertEqual((copy.attack,copy.max_health,copy.cost),(5,11,1));self.assertEqual(copy.origin_entity_id,original)
        self.assertEqual(g.state.entities[original].zone,Zone.DECK)
        self.assertTrue({e.id for e in copy.enchantments}.isdisjoint({e.id for e in g.state.entities[original].enchantments}));self.portable(g)

    def test_tak_copy_to_deck_targets_new_inserted_copy_and_not_held_parent(self):
        g=self.game((BUFF,COPY_DECK,A),board=(TAK,));held=self.entity(g,A).id;self.play(g,BUFF,held);self.play(g,COPY_DECK,held)
        deck=self.entity(g,A,zone='deck');new=g.state.entities[g.state.players[1].hand[-1]]
        self.assertNotEqual(deck.id,held);self.assertEqual(new.origin_entity_id,deck.id);self.assertEqual((new.attack,new.max_health,new.cost),(5,11,1))

    def test_tak_copies_actual_spell_cards_as_well_as_minions(self):
        g=self.game((MOVE,SPELL),board=(TAK,));original=self.entity(g,SPELL).id;self.play(g,MOVE,original)
        self.assertEqual(self.hand(g),[SPELL]);self.assertEqual(self.entity(g,SPELL).origin_entity_id,original);self.assertEqual(len(g.state.cast_history),1)

    def test_tak_known_opponent_shuffle_and_positional_placement_do_not_copy(self):
        g=self.game((TOP,),board=(TAK,),enemy_hand=(ENEMY,));self.play(g,TOP);self.assertEqual(self.hand(g),[])
        g.apply(EndTurn(1));self.play(g,ENEMY,player=2);self.assertEqual(self.hand(g),[]);self.assertEqual(len(g.state.players[1].deck),2)

    def test_tak_unknown_issuer_is_explicit_atomic_error_and_not_guessed(self):
        g=self.game((UNKNOWN,),board=(TAK,));before=g.snapshot()
        with self.assertRaises(ResolutionError)as failure:self.play(g,UNKNOWN)
        self.assertIsInstance(failure.exception.__cause__,UnsupportedDefinitionError);self.assertEqual(g.snapshot(),before)

    def test_tak_full_hand_burns_only_extra_copy_and_keeps_both_deck_entries(self):
        g=self.game((MANY,)+(A,)*9,board=(TAK,));self.play(g,MANY)
        self.assertEqual(len(self.hand(g)),10);self.assertEqual(len(g.state.players[1].deck),2);self.assertEqual(g.state.draw_history,[])
        self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),1);self.portable(g)

    def test_tak_silence_removes_observer_without_affecting_actual_shuffle(self):
        g=self.game((HUSH,SHUFFLE),board=(TAK,));self.play(g,HUSH,self.unit(g,TAK).id);self.play(g,SHUFFLE)
        self.assertEqual(self.hand(g),[]);self.assertEqual(len(g.state.players[1].deck),1)

    def test_tak_original_insertion_can_move_before_accepted_frozen_copy_executes(self):
        g=self.game((SHUFFLE,),board=(TAK,),watch=WAIT_INSERT);self.play(g,SHUFFLE)
        g=self.portable(g);self.fault(g);self.choose(g,'move');self.finish(g)
        self.assertEqual(self.hand(g),[A,A]);self.assertEqual(g.state.players[1].deck,[])
        self.assertEqual(sum(g.state.entities[i].origin_entity_id is not None for i in g.state.players[1].hand),1);self.portable(g)

    def test_tak_copy_publication_wait_retains_original_material_and_hides_identity(self):
        g=self.game((SHUFFLE,),board=(TAK,),watch=WAIT_COPY);self.play(g,SHUFFLE);g=self.portable(g);self.fault(g);self.finish(g)
        own=[e for e in g.player_events(1)if e['kind']=='card_added_to_hand'];other=[e for e in g.player_events(2)if e['kind']=='card_added_to_hand']
        self.assertEqual(own[-1]['target']['card_id'],A);self.assertIsNone(other[-1]['target']['card_id']);self.portable(g)

    def test_standard_host_actual_draw_copy_and_semantic_shuffle_entries(self):
        g=self.game((DRAW,),board=(BETRUG,),deck=(A,),real_host=True);self.play(g,DRAW);self.assertEqual(len(self.copies(g)),1)
        g.apply(EndTurn(1));self.assertEqual(self.copies(g),[])
        g=self.game((MANY,),board=(TAK,),real_host=True);self.play(g,MANY);self.assertEqual(self.hand(g),[A,A])
