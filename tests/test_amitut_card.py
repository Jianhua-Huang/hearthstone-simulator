"""Amitut's actual deck copies and finite original granted draw-cast declarations."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.amitut_card import CARD, load_batch, register_amitut_card
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.costs import local_cost
from hs_sim.engine.draw_cast_grants import GrantedDrawCastBasis, KEY
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, Draw, GainArmor,
    InvokeBehavior, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (BattlecryRepeatSpec, CardClass, CardMetadata, CastWhenDrawnSpec,
    CostSpec, Keyword, SpellSchool, TargetMode, TargetSpec)
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import (CardReference, CopyCard, DrawMatching, ModifyStoredCost, ReorderZone)
from tools.card_batch import canonical, check_face

P='fixture.amitut.'
PLAIN,H1,H2,SHADOW,NATIVE,TARGET,TOP,DRAW,CURR,BASE,COST,FILL,STEAL,REPEAT,WATCH=(P+x for x in
    ('plain','holy_one','holy_two','shadow','native_holy','target_holy','top','draw','current',
     'base','cost','fill','steal','repeat','watch'))
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
HAND=(CARD,TOP,DRAW,CURR,BASE,COST)


def grants(entity):return tuple(a for a in entity.abilities if a.draw_cast is not None and not a.consumed)


@lru_cache(maxsize=None)
def registry(mode=None,role='writer'):
    assert role in('writer','reader')
    r=build_registry();register_amitut_card(r)
    r.register_card(CardDefinition(PLAIN,PLAIN,CardType.MINION,health=10,metadata=META))
    for cid,amount,school in((H1,1,SpellSchool.HOLY),(H2,2,SpellSchool.HOLY),(SHADOW,3,SpellSchool.SHADOW)):
        r.register_behavior(cid,lambda c,n=amount:(GainArmor(c.player_id,n),))
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=2,on_play=cid,spell_school=school,metadata=META))
    r.register_behavior(NATIVE,lambda c:(GainArmor(c.player_id,1),))
    r.register_behavior(NATIVE+'.after',lambda c:(GainArmor(c.player_id,2),))
    r.register_card(CardDefinition(NATIVE,NATIVE,CardType.SPELL,cost=2,on_play=NATIVE,spell_school=SpellSchool.HOLY,
        keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec(after_draw=NATIVE+'.after'),metadata=META))
    r.register_behavior(TARGET,lambda c:(Damage(c.target_id,1,c.source_id),))
    r.register_card(CardDefinition(TARGET,TARGET,CardType.SPELL,cost=2,on_play=TARGET,spell_school=SpellSchool.HOLY,
        targeting=TargetSpec(TargetMode.REQUIRED,zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy'),metadata=META))
    def chosen(c):
        return max((c.state.entities[i]for i in c.state.players[c.player_id].deck if grants(c.state.entities[i])),
            key=lambda e:(len(grants(e)),-e.id))
    def top(c):
        deck=c.state.players[c.player_id].deck;target=chosen(c)
        rest=[i for i in deck if i!=target.id]
        ordinary=[i for i in rest if Keyword.CASTS_WHEN_DRAWN not in c.state.entities[i].keywords]
        return(ReorderZone(c.player_id,Zone.DECK,(target.id,*ordinary,*(i for i in rest if i not in ordinary))),)
    def copied(c,mode):
        return(CopyCard(CardReference.capture(chosen(c)),c.player_id,Zone.HAND,mode=mode,source_id=c.source_id),)
    def cheaper(c):
        target=next(c.state.entities[i]for i in c.state.players[c.player_id].deck
            if r.card(c.state.entities[i].card_id).spell_school==SpellSchool.HOLY)
        return(ModifyStoredCost(CardReference.capture(target),CostSpec(delta=-1),c.source_id),)
    bodies={TOP:top,DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),CURR:lambda c:copied(c,'current'),
        BASE:lambda c:copied(c,'base'),COST:cheaper,FILL:lambda c:tuple(AddToHand(c.player_id,PLAIN,c.source_id)for _ in range(3)),
        STEAL:lambda c:(DrawMatching(c.player_id,PoolQuery(),'fatigue',source_id=c.source_id,owner_id=3-c.player_id,selection='first'),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=10,metadata=META,
        battlecry_repeats=(BattlecryRepeatSpec(),)))
    def fail(c):raise ResolutionError('Amitut deliberate late failure')
    r.register_behavior(P+'fail',fail)
    if mode:
        event='card_drawn'if mode in('draw_wait','draw_fail')else'card_added_to_deck'
        def watch(c):
            target=c.state.entities.get(c.event.target_id)
            if target is None or not grants(target):return()
            if mode=='source_death':
                source=next((e for e in c.state.entities.values()if e.card_id==CARD and e.zone==Zone.BOARD),None)
                return()if source is None else(Destroy(source.id,c.source_id),)
            if mode in('copy_fail','draw_fail'):return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return(RequestChoice(3-c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,metadata=META,triggers=(TriggerSpec(event,WATCH),)))
    return r


class AmitutTests(unittest.TestCase):
    def game(self,mode=None,*,deck=(H1,PLAIN),hand=HAND,board=(),enemy_board=(PLAIN,),seat=1):
        self.mode=mode;self.seat=seat
        own=PlayerSetup('HERO_08',hand=hand,deck=deck,board=board+((WATCH,)if mode else()),mana=10,max_mana=10)
        other=PlayerSetup('HERO_01',hand=(STEAL,),deck=(PLAIN,PLAIN),board=enemy_board,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,seed=371),registry(mode))
    def play(self,g,cid=CARD,pid=None):
        pid=self.seat if pid is None else pid
        eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid));return eid
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def finish(self,g):
        while g.state.pending_choice:self.choose(g)
    def copies(self,g):return [e for e in g.state.entities.values()if grants(e)]
    def armor(self,g,pid=None):
        return g.state.entities[g.state.players[self.seat if pid is None else pid].hero_id].armor
    def prepare(self,g):
        self.play(g);self.finish(g);self.play(g,TOP)
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));r=registry(self.mode,'reader')
        self.assertIsNot(r,g.registry)
        for other in(g.clone(),Game.from_snapshot(saved,r),replay(build_replay(g),r)):
            self.assertTrue(other.snapshot()==saved,'Original granted draw material and shuffle/cast chains must restore')
        return Game.from_snapshot(saved,r)
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()
            if k not in('schema_version','events','events_hash','state_hash')});return s

    def test_complete_raw_and_two_primary_faces_keep_actual_paladin_legendary(self):
        d=load_batch();row=d['cards'][0];self.assertEqual(canonical(row['record']),row['record_sha256'])
        self.assertEqual(len(d['official_observations']),2)
        for o in d['official_observations']:check_face(row['record'],o['face'],o['locale'])
        card=registry().card(CARD);self.assertEqual((card.cost,card.attack,card.health),(7,5,8))
        self.assertEqual(card.keywords,(Keyword.TAUNT,))

    def test_actual_seven_mana_play_copies_each_original_holy_and_preserves_originals(self):
        g=self.game(deck=(H1,H1,H2,SHADOW,PLAIN));original=tuple(g.state.players[1].deck);source=self.play(g)
        copies=self.copies(g);self.assertEqual(len(copies),3);self.assertEqual(g.state.players[1].mana,3)
        self.assertEqual({e.origin_entity_id for e in copies},set(original[:3]))
        self.assertTrue(set(original)<=set(g.state.players[1].deck))
        self.assertTrue(all(Keyword.CASTS_WHEN_DRAWN not in g.state.entities[i].keywords for i in original))
        self.assertTrue(all(grants(e)[0].source_id==source for e in copies))
        row,=g.state.deck_shuffle_history;self.assertEqual((row.actor_id,row.player_id,row.declared_count),(1,1,3));self.portable(g)

    def test_no_holy_spell_is_empty_without_shuffle_or_rng(self):
        g=self.game(deck=(SHADOW,PLAIN));rng=g._rng.getstate();self.play(g)
        self.assertFalse(self.copies(g));self.assertFalse(g.state.deck_shuffle_history);self.assertEqual(g._rng.getstate(),rng)

    def test_current_cost_material_is_copied_and_both_original_and_copy_stay_distinct(self):
        g=self.game();self.play(g,COST);source=g.state.players[1].deck[0];self.play(g)
        copy,=self.copies(g);self.assertEqual(local_cost(copy)[0],1)
        self.assertEqual(local_cost(g.state.entities[source])[0],1);self.assertNotEqual(copy.id,source)

    def test_native_repeated_battlecry_reaccepts_new_holy_copies_without_double_casting(self):
        g=self.game(deck=(H1,),board=(REPEAT,));self.play(g);self.assertEqual(len(g.state.players[1].deck),4)
        self.assertEqual([r.declared_count for r in g.state.deck_shuffle_history],[1,2])
        self.assertEqual(len(self.copies(g)),3);self.assertTrue(any(len(grants(e))==2 for e in self.copies(g)))
        self.play(g,TOP);self.play(g,DRAW);self.assertEqual(self.armor(g),1)
        self.assertEqual(sum(d.outcome=='cast'for d in g.state.draw_history),1);self.portable(g)

    def test_granted_copy_draw_uses_original_entity_without_payment_then_replacement(self):
        g=self.game();self.prepare(g);copy=g.state.players[1].deck[0];mana=g.state.players[1].mana;self.play(g,DRAW)
        cast,normal=g.state.draw_history;self.assertEqual((cast.entity_id,cast.outcome,normal.outcome),(copy,'cast','hand'))
        self.assertIsInstance(cast.cast_grant,GrantedDrawCastBasis);self.assertEqual(cast.cast_grant.origin.zone,Zone.DECK)
        self.assertEqual(g.state.entities[copy].zone,Zone.GRAVEYARD);self.assertEqual(self.armor(g),1)
        self.assertEqual(g.state.players[1].mana,mana);self.assertEqual(len(g.state.play_history),3);self.portable(g)

    def test_current_hand_copy_inherits_grant_base_copy_does_not_and_manual_cast_never_replaces(self):
        g=self.game();self.play(g,COST);self.play(g);self.play(g,CURR);self.play(g,BASE)
        cards=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==H1]
        current,base=cards;self.assertTrue(grants(current));self.assertFalse(grants(base))
        self.assertEqual((local_cost(current)[0],local_cost(base)[0]),(1,2));self.assertFalse(g.state.draw_history)
        self.play(g,H1);self.assertEqual(self.armor(g),1);self.assertFalse(g.state.draw_history);self.portable(g)

    def test_printed_draw_cast_policy_and_after_draw_callback_are_preserved(self):
        g=self.game(deck=(NATIVE,PLAIN));self.prepare(g);self.play(g,DRAW)
        cast=g.state.draw_history[0];self.assertEqual(cast.spec.after_draw,NATIVE+'.after')
        self.assertIsNone(cast.cast_grant);self.assertEqual(self.armor(g),3);self.portable(g)

    def test_automatic_targeted_copy_and_no_target_fizzle_both_use_original_replacement(self):
        for enemy_board in((PLAIN,),()):
            g=self.game(deck=(TARGET,PLAIN),enemy_board=enemy_board);self.prepare(g);self.play(g,DRAW)
            self.assertEqual([d.outcome for d in g.state.draw_history],['cast','hand'])
            if enemy_board:self.assertEqual(g.state.entities[g.state.players[2].board[0]].damage,1)

    def test_full_hand_burns_granted_copy_without_cast_or_replacement(self):
        g=self.game(hand=(CARD,TOP,FILL)+(PLAIN,)*7);self.prepare(g);copy=g.state.players[1].deck[0];self.play(g,FILL)
        self.assertEqual(len(g.state.players[1].hand),10);g.apply(EndTurn(1));g.apply(EndTurn(2))
        row=g.state.draw_history[-1];self.assertEqual((row.entity_id,row.outcome),(copy,'burned'))
        self.assertIsNone(row.cast_grant);self.assertEqual(self.armor(g),0)

    def test_source_death_after_copy_publication_does_not_cancel_granted_draw(self):
        g=self.game('source_death');self.prepare(g);self.play(g,DRAW)
        self.assertTrue(all(e.zone!=Zone.BOARD for e in g.state.entities.values()if e.card_id==CARD))
        self.assertEqual(self.armor(g),1);self.portable(g)

    def test_all_copies_have_declarations_before_insertion_observer_choices(self):
        g=self.game('copy_wait',deck=(H1,H2,PLAIN));self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(self.copies(g)),2)
        self.assertTrue(all(Keyword.CASTS_WHEN_DRAWN in e.keywords for e in self.copies(g)))
        other=self.portable(g);self.finish(g);self.finish(other);self.assertTrue(g.snapshot()==other.snapshot())

    def test_copy_failure_restores_original_deck_attachments_payment_rng_and_shuffle(self):
        g=self.game('copy_fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertTrue(g.snapshot()==before)

    def test_draw_wait_keeps_exact_original_grant_and_resumes_without_recasting(self):
        g=self.game('draw_wait');self.prepare(g);self.play(g,DRAW)
        record=g.state.draw_history[-1];self.assertEqual(record.phase,'pending_cast')
        self.assertIsNotNone(record.cast_grant);other=self.portable(g)
        self.choose(g);self.choose(other);self.assertTrue(g.snapshot()==other.snapshot())
        self.assertEqual(self.armor(g),1);self.assertEqual(sum(d.outcome=='cast'for d in g.state.draw_history),1);self.portable(g)

    def test_draw_and_failed_choice_restore_original_draw_basis_and_rng(self):
        g=self.game('draw_fail');self.prepare(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,DRAW)
        self.assertTrue(g.snapshot()==before)
        g=self.game('draw_wait');self.prepare(g);self.play(g,DRAW);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertTrue(g.snapshot()==before)

    def test_partial_deck_capacity_only_publishes_successful_original_copy(self):
        g=self.game(deck=(H1,H2)+(PLAIN,)*96);self.play(g)
        self.assertEqual(len(g.state.players[1].deck),99);self.assertEqual(len(self.copies(g)),1)
        self.assertEqual(g.state.deck_shuffle_history[0].declared_count,2)

    def test_full_deck_does_not_allocate_copy_grants_consume_rng_or_publish_shuffle(self):
        g=self.game(deck=(H1,)+(PLAIN,)*98);rng=g._rng.getstate();self.play(g)
        self.assertFalse(self.copies(g));self.assertFalse(g.state.deck_shuffle_history)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(len(g.state.players[1].deck),99)

    def test_opponent_physical_draw_uses_actual_drawer_without_rebinding_original_owner(self):
        g=self.game(seat=2);self.prepare(g);copy=g.state.players[2].deck[0]
        g.apply(EndTurn(2));self.play(g,STEAL,pid=1)
        cast=next(d for d in g.state.draw_history if d.entity_id==copy)
        self.assertEqual((cast.player_id,cast.cast_grant.origin.owner,cast.cast_grant.origin.controller),(1,2,2))
        self.assertEqual(self.armor(g,pid=1),1);self.assertEqual(g.state.entities[copy].owner,2);self.portable(g)

    def test_copy_declaration_is_typed_finite_and_requires_original_own_deck_spell_material(self):
        g=self.game();source=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==CARD)
        entity=g.state.entities[g.state.players[1].deck[0]];material=CapturedCardCopyMaterial.capture(g.state,entity)
        effect=CopyCard(material,1,Zone.DECK,source_id=source,cast_when_drawn=True)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(effect)))),effect)
        for changes in(dict(cast_when_drawn=1),dict(mode='base'),dict(position='top'),dict(destination=Zone.HAND),
                dict(source_id=None),dict(player_id=2),dict(card=CardReference.capture(entity))):
            with self.assertRaises(ValueError):replace(effect,**changes)

    def test_granted_ability_rejects_fake_callback_policy_carrier_and_future_draw_basis(self):
        g=self.game('draw_wait');self.prepare(g);self.play(g,DRAW);basis=g.state.draw_history[-1].cast_grant
        for changes in(dict(draw_cast=CastWhenDrawnSpec(replacement=False)),dict(source_id=None),
                dict(origin='printed'),dict(keyword=Keyword.TAUNT),dict(expires_turn=1)):
            with self.assertRaises(ValueError):replace(basis.ability,**changes)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(basis)))),basis)
        with self.assertRaises(ValueError):codec.encode(replace(basis,next_attachment_id=g.state.next_attachment_id+1))

    def test_rehashed_draw_basis_and_original_private_witness_cannot_be_changed_or_dropped(self):
        g=self.game('draw_wait');self.prepare(g);self.play(g,DRAW);saved=g.snapshot()
        for mode in('remove_basis','future_basis','change_event','drop_event'):
            s=deepcopy(saved);row=s['state']['draw_history'][-1]
            if mode=='remove_basis':row['cast_grant']=None
            elif mode=='future_basis':row['cast_grant']['next_attachment_id']+=1000
            else:
                event=next(e for e in s['events']if KEY in dict(e['data']))
                if mode=='drop_event':s['events'].remove(event)
                else:
                    data=dict(event['data']);basis=json.loads(data[KEY]);basis['ability']['source_id']=row['entity_id']
                    data[KEY]=json.dumps(basis);event['data']=list(data.items())
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry(self.mode,'reader'))

    def test_second_seat_player_views_hide_private_grant_proof_and_complete_deck(self):
        g=self.game('draw_wait',seat=2);self.prepare(g);self.play(g,DRAW);saved=g.snapshot()
        for pid in(1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid));g.for_player(pid).legal_actions()
            for key in(KEY,'cast_grant','GrantedDrawCastBasis','next_attachment_id','draw_cast'):
                self.assertNotIn('"'+key+'"',public)
        self.assertTrue(g.snapshot()==saved);self.portable(g)
