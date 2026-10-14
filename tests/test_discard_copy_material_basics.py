"""Original successful-discard copies use one immutable recipe and shared delivery."""
from dataclasses import asdict,replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass,CardDefinition,CardType,CostSpec,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Rarity,Registry,ResolutionError,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone,discarded_cards)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.copy_materials import CopyEntryMaterial,from_dict,validate_scope
from hs_sim.engine.discard_history import validate_frame_materials
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Draw,InvokeBehavior,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import validate_material as validate_summon_material
from hs_sim.engine.temporary_cards import MakeHandCardTemporary
from hs_sim.engine.zones import CardReference,ChooseFromZone,CopyCard,DiscardCard,DiscardMatching,MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

NATIVE='TRL_252'
PATH=Path(__file__).resolve().parents[1]/'data/support/discard-copy-material-basics.json'
PIN='4d861c1eac86d5e6ca6539b7a540cd74e83f2fb58c2b9caa6c09e536807b9fbd'


def evidence():
    data=json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=PIN:raise ValueError('Discard copy raw evidence changed')
    row=data['records'][0]
    if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Discard copy raw row changed')
    return row['data']


def native_ref(c,player=None):
    p=c.player_id if player is None else player
    return CardReference.capture(next(c.state.entities[i]for i in c.state.players[p].hand if c.state.entities[i].card_id==NATIVE))


def registry():
    r=Registry('isolated-discard-copy-material-basics-v1');raw=evidence()
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata()))
    r.register_card(CardDefinition('a','Whiteboard',CardType.MINION,cost=1,attack=1,health=20,metadata=metadata()))
    r.register_card(CardDefinition('b','Blank spell',CardType.SPELL,metadata=metadata()))
    def own(c):
        material=CopyEntryMaterial.capture(c.state,c.state.entities[c.source_id],'discard_copy','current',
            registry=r,player_id=c.player_id,discard=c.discard)
        return (CopyCard(material,c.player_id,source_id=c.source_id),)*2
    r.register_behavior('native.copy',own)
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=(Keyword.TAUNT,Keyword.LIFESTEAL),on_discard='native.copy',
        metadata=metadata(CardClass.WARLOCK,rarity=Rarity.LEGENDARY)))
    def fault(c):raise RuntimeError('Deliberate copy fault')
    r.register_behavior('fault',fault)
    def stale(c):
        ref=native_ref(c);return (DiscardCard(ref,c.source_id),DiscardCard(ref,c.source_id))
    scripts={
        'discard':lambda c:(DiscardCard(native_ref(c),c.source_id),),
        'private':lambda c:(DiscardCard(native_ref(c),c.source_id,False),),
        'enemy':lambda c:(DiscardCard(native_ref(c,3-c.player_id),c.source_id),),
        'multi':lambda c:(DiscardMatching(c.player_id,count=2,selection='first',source_id=c.source_id),),
        'stale':stale,
        'chosen':lambda c:(ChooseFromZone(c.player_id,c.player_id,Zone.HAND,operation='discard',sample_size=None,distinct='entity',source_id=c.source_id),),
        'buff':lambda c:(BuffStoredCard(native_ref(c),3,4,source_id=c.source_id),),
        'cost':lambda c:(BuffStoredCard(native_ref(c),cost=CostSpec(set_to=1),source_id=c.source_id),),
        'temporary':lambda c:(MakeHandCardTemporary(native_ref(c),c.state.turn,source_id=c.source_id),),
        'copyhand':lambda c:(CopyCard(native_ref(c),c.player_id,source_id=c.source_id),),
        'transfer':lambda c:(MoveCard(native_ref(c),2,Zone.HAND,source_id=c.source_id),),
        'latefault':lambda c:(DiscardCard(native_ref(c),c.source_id),InvokeBehavior('fault',c.source_id,c.player_id)),
        'draw':lambda c:(Draw(c.player_id,source_id=c.source_id),),
    }
    targeted={'bounce':lambda c:(ReturnToHand(c.target_id),),'silence':lambda c:(Silence(c.target_id),)}
    for cid,body in {**scripts,**targeted}.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,requires_target=cid in targeted,metadata=metadata()))
    def options(c):
        return (ChoiceOption('ok','Continue'),ChoiceOption('fault','Fail',(InvokeBehavior('fault',c.source_id,c.player_id),)))
    def before(c):
        return (RequestChoice(c.player_id,options(c),c.source_id),)if c.event.player_id==c.player_id else ()
    def first(c):
        if c.event.player_id!=c.player_id or c.event.source_id is None:return False
        e=c.state.entities[c.event.target_id]
        return (e.card_id==NATIVE and
            sum(x.card_id==NATIVE and x.origin_entity_id==c.event.source_id for x in c.state.entities.values())==1)
    def wait(c):return (RequestChoice(c.player_id,options(c),c.source_id),)if first(c)else ()
    def copy_grow(c):
        if not first(c):return ()
        card=CardReference.capture(c.state.entities[c.event.target_id])
        return (BuffStoredCard(card,10,10,source_id=c.source_id),RequestChoice(c.player_id,options(c),c.source_id))
    def grow(c):
        if not first(c):return ()
        row=c.state.discard_history[-1]
        return (BuffStoredCard(row,10,10,source_id=row.entity_id),RequestChoice(c.player_id,options(c),c.source_id))
    def leave(c):
        if not first(c):return ()
        row=c.state.discard_history[-1]
        return (ReturnToHand(row.entity_id,discard=row),RequestChoice(c.player_id,options(c),c.source_id))
    def fill(c,n):
        return tuple(AddToHand(c.player_id,'b')for _ in range(n))if c.event.player_id==c.player_id else ()
    for cid,event,body in (('before','card_discarded',before),('firstwait','card_added_to_hand',wait),
        ('grow','card_added_to_hand',grow),('copygrow','card_added_to_hand',copy_grow),('leave','card_added_to_hand',leave),
        ('fill9','card_discarded',lambda c:fill(c,9)),('fill10','card_discarded',lambda c:fill(c,10))):
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=20,triggers=(TriggerSpec(event,cid),),metadata=metadata()))
    return r


class DiscardCopyMaterialTests(unittest.TestCase):
    def game(self,hand=('discard',NATIVE),board=(),enemy_hand=(),deck=('b',)*6):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,deck=('b',)*6,mana=10,max_mana=10),
        ),seed=53),registry())
    def play(self,g,cid,target=None,player=1):
        eid=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(player,eid,target));return eid
    def original(self,g):
        return next(e for e in g.state.entities.values()if e.card_id==NATIVE and e.origin_entity_id is None)
    def copies(self,g,source=None):
        source=self.original(g).id if source is None else source
        return [e for e in g.state.entities.values()if e.origin_entity_id==source and e.card_id==NATIVE]
    def choose(self,g,name='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(name,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));h=Game.from_snapshot(s,registry())
        self.assertEqual(h.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),s);return h
    def first_wait(self,board='firstwait',hand=('discard',NATIVE)):
        g=self.game(hand,board=(board,));self.play(g,'discard');return g
    def queued(self,g):
        return next(w for w in(*g._frame.prefix,*g._frame.continuation)if type(w)is CopyCard and type(w.card)is CopyEntryMaterial)
    def replace_work(self,g,new):
        work=self.queued(g)
        return replace(g._frame,prefix=tuple(new if x==work else x for x in g._frame.prefix),
            continuation=tuple(new if x==work else x for x in g._frame.continuation))

    def test_complete_raw_pin_and_exact_native_copy_declaration(self):
        raw=evidence();original=next(x for x in json.loads((PATH.parents[1]/'extracted/cards.json').read_text(encoding='utf-8'))if x['id']==NATIVE)
        self.assertEqual(raw,original);card=registry().card(NATIVE)
        self.assertEqual((card.cost,card.attack,card.health,card.on_discard),(4,3,5,'native.copy'))
        self.assertEqual(card.keywords,(Keyword.TAUNT,Keyword.LIFESTEAL))
        self.assertEqual((card.metadata.classes,card.metadata.rarity),((CardClass.WARLOCK,),Rarity.LEGENDARY))
        self.assertNotIn('UNG_836',registry().cards)

    def test_two_new_independent_entities_leave_original_successfully_discarded(self):
        g=self.game();original=self.original(g);allocator=g.state.next_entity_id;self.play(g,'discard');copies=self.copies(g)
        self.assertEqual(len(copies),2);self.assertEqual(g.state.next_entity_id,allocator+2)
        self.assertEqual((self.original(g).id,self.original(g).zone,self.original(g).zone_epoch),(original.id,Zone.GRAVEYARD,original.zone_epoch+1))
        self.assertEqual([(e.zone,e.attack,e.health,e.owner,e.controller)for e in copies],[(Zone.HAND,3,5,1,1)]*2)
        self.assertEqual([r.entity_id for r in discarded_cards(g.state,1)],[original.id]);self.portable(g)

    def test_current_local_growth_is_frozen_and_copied_with_independent_attachments(self):
        g=self.game(('buff',NATIVE,'discard'));self.play(g,'buff');self.play(g,'discard');entities=[self.original(g),*self.copies(g)]
        self.assertEqual([(e.attack,e.health)for e in entities],[(6,9)]*3)
        ids=[{a.id for a in(*e.enchantments,*e.abilities)}for e in entities]
        self.assertTrue(all(not ids[i].intersection(ids[j])for i in range(3)for j in range(i)))
        self.assertTrue(all(a.source_id==e.id for e in entities[1:]for a in e.abilities if a.origin=='printed'));self.portable(g)

    def test_current_local_cost_recipe_is_copied(self):
        g=self.game(('cost',NATIVE,'discard'));self.play(g,'cost');self.play(g,'discard')
        copies=self.copies(g);self.assertEqual([g.quote_cost(e.id).amount for e in copies],[1,1]);self.portable(g)

    def test_first_copy_changes_cannot_mutate_the_other_copy(self):
        g=self.game(('buff',NATIVE,'discard'),board=('copygrow',));self.play(g,'buff');self.play(g,'discard')
        before=self.copies(g)[0];h=self.portable(g);self.choose(g);self.choose(h)
        self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual([(e.attack,e.health)for e in self.copies(g)],[(16,19),(6,9)])
        self.assertEqual(g.state.entities[before.id],before);self.portable(g)

    def test_original_live_growth_after_first_delivery_does_not_rewrite_frozen_recipe(self):
        g=self.first_wait('grow');self.assertEqual(self.original(g).attack,13);work=self.queued(g)
        self.assertEqual(work.card.local.base_attack,3);h=self.portable(g);self.choose(g);self.choose(h)
        self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual([(e.attack,e.health)for e in self.copies(g)],[(3,5)]*2);self.portable(g)

    def test_accepted_recipe_survives_original_leaving_the_discarded_epoch(self):
        g=self.first_wait('leave');self.assertEqual(self.original(g).zone,Zone.HAND);h=self.portable(g);self.choose(g);self.choose(h)
        self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual([e.zone for e in self.copies(g)],[Zone.HAND]*2)
        self.assertEqual(len(discarded_cards(g.state,1)),1);self.portable(g)

    def test_new_copies_form_independent_hand_acquisitions(self):
        g=self.game();before=self.original(g);self.play(g,'discard');copies=self.copies(g)
        entries=[g.state.hand_entries[e.hand_entry_id-1]for e in copies]
        self.assertEqual([(x.reason,x.from_zone,x.entity_id)for x in entries],[('created',None,e.id)for e in copies])
        self.assertEqual(len({before.hand_entry_id,*[x.id for x in entries]}),3);self.portable(g)

    def test_old_acquisition_temporary_lease_is_not_transferred_to_new_copies(self):
        g=self.game(('temporary',NATIVE,'discard'));self.play(g,'temporary');self.assertIsNotNone(self.original(g).hand_lifetime)
        self.play(g,'discard');self.assertIsNotNone(self.original(g).hand_lifetime)
        self.assertTrue(all(e.hand_lifetime is None for e in self.copies(g)));g.apply(EndTurn(1))
        self.assertEqual([e.zone for e in self.copies(g)],[Zone.HAND]*2);self.assertEqual(len(discarded_cards(g.state,1)),1);self.portable(g)

    def test_first_copy_fills_final_slot_and_second_copy_burns(self):
        g=self.game(board=('fill9',));self.play(g,'discard')
        self.assertEqual([e.zone for e in self.copies(g)],[Zone.HAND,Zone.GRAVEYARD])
        self.assertEqual([e.hand_entry_id is None for e in self.copies(g)],[False,True])
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(discarded_cards(g.state,1)),1);self.portable(g)

    def test_full_hand_burns_both_copies_without_accepting_their_discard_bodies(self):
        g=self.game(board=('fill10',));self.play(g,'discard')
        self.assertEqual([e.zone for e in self.copies(g)],[Zone.GRAVEYARD]*2)
        self.assertTrue(all(e.hand_entry_id is None for e in self.copies(g)))
        self.assertEqual(len(discarded_cards(g.state,1)),1);self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),2);self.portable(g)

    def test_two_genuine_physical_discards_capture_their_own_copy_recipes(self):
        g=self.game(('multi',NATIVE));self.play(g,'multi');rows=discarded_cards(g.state,1)
        self.assertEqual(len(rows),2);self.assertNotEqual(rows[0].entity_id,rows[1].entity_id)
        self.assertEqual(len([e for e in g.state.entities.values()if e.card_id==NATIVE]),5)
        self.assertEqual(len(g.state.players[1].hand),3);self.portable(g)

    def test_old_physical_discard_reference_does_not_discard_a_new_copy(self):
        g=self.game(('stale',NATIVE));self.play(g,'stale')
        self.assertEqual((len(self.copies(g)),len(discarded_cards(g.state,1))),(2,1));self.portable(g)

    def test_recipient_is_affected_controller_and_copies_have_new_owner(self):
        g=self.game(('transfer',NATIVE),enemy_hand=('discard',));eid=self.original(g).id;self.play(g,'transfer');g.apply(EndTurn(1));self.play(g,'discard',player=2)
        self.assertEqual((self.original(g).owner,self.original(g).controller),(1,2))
        self.assertEqual([(e.owner,e.controller,e.zone)for e in self.copies(g,eid)],[(2,2,Zone.HAND)]*2);self.portable(g)

    def test_enemy_cause_does_not_redirect_original_copy_recipient(self):
        g=self.game(('enemy',),enemy_hand=(NATIVE,));self.play(g,'enemy')
        self.assertEqual(g.state.players[1].hand,[]);self.assertEqual([(e.owner,e.controller)for e in self.copies(g)],[(2,2)]*2);self.portable(g)

    def test_ordinary_current_hand_copy_keeps_existing_original_native_behavior(self):
        g=self.game(('copyhand',NATIVE,'discard'));self.play(g,'copyhand')
        first=self.copies(g)[0];self.play(g,'discard');self.assertEqual(g.state.entities[first.id],first)
        self.assertEqual(len(self.copies(g)),3);self.assertEqual(len(discarded_cards(g.state,1)),1);self.portable(g)

    def test_manual_play_of_copy_preserves_local_growth_and_native_keywords(self):
        g=self.game(('buff',NATIVE,'discard'));self.play(g,'buff');self.play(g,'discard');e=self.copies(g)[0];self.play(g,NATIVE)
        self.assertEqual((g.state.entities[e.id].zone,g.state.entities[e.id].attack,g.state.entities[e.id].health),(Zone.BOARD,6,9))
        self.assertTrue(all(k in g.state.entities[e.id].keywords for k in(Keyword.TAUNT,Keyword.LIFESTEAL)));self.portable(g)

    def test_ordinary_board_bounce_keeps_existing_reset_recipe(self):
        g=self.game(('buff',NATIVE,'discard','bounce'));self.play(g,'buff');self.play(g,'discard');e=self.copies(g)[0]
        self.play(g,NATIVE);self.play(g,'bounce',e.id);after=g.state.entities[e.id]
        self.assertEqual((after.zone,after.attack,after.health),(Zone.HAND,3,5));self.portable(g)

    def test_draw_and_manual_play_do_not_create_discard_copies(self):
        g=self.game(('draw',),deck=(NATIVE,));self.play(g,'draw');self.play(g,NATIVE)
        self.assertEqual((len(self.copies(g)),len(discarded_cards(g.state,1))),(0,0));self.portable(g)

    def test_pre_discard_selection_resumes_to_two_original_copies(self):
        g=self.game(('chosen',NATIVE,'b'));self.play(g,'chosen');h=self.portable(g)
        name=next(x.id for x in g.state.pending_choice.options if x.card_id==NATIVE)
        self.choose(g,name);self.choose(h,name);self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(len(self.copies(g)),2);self.portable(g)

    def test_wait_before_native_body_uses_original_accepted_context_once(self):
        g=self.game(board=('before',));self.play(g,'discard');self.assertEqual(self.copies(g),[]);h=self.portable(g)
        self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(len(self.copies(g)),2);self.portable(g)

    def test_wait_between_deliveries_keeps_exact_original_material_and_remaining_work(self):
        g=self.first_wait();self.assertEqual(len(self.copies(g)),1);work=self.queued(g);row=discarded_cards(g.state,1)[0]
        self.assertEqual((work.card.profile,work.card.discard),('discard_copy',row));h=self.portable(g)
        self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(len(self.copies(g)),2);self.portable(g)

    def test_both_waits_restore_without_reaccepting_a_discard_or_copy(self):
        g=self.game(board=('before','firstwait'));self.play(g,'discard');h=self.portable(g);self.choose(g);self.choose(h)
        self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(len(self.copies(g)),1);h=self.portable(g)
        self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual((len(self.copies(g)),len(discarded_cards(g.state,1))),(2,1));self.portable(g)

    def test_choice_failure_restores_first_copy_and_original_pending_second_copy(self):
        g=self.first_wait();before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(len(self.copies(g)),2);self.portable(g)

    def test_late_failure_rolls_back_all_entities_attachments_history_and_acquisitions(self):
        g=self.game(('latefault',NATIVE));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'latefault')
        self.assertEqual(g.snapshot(),before);self.assertEqual((self.copies(g),discarded_cards(g.state,1)),([],()))

    def test_false_original_discard_and_future_attachment_material_are_rejected_by_frame(self):
        g=self.first_wait();work=self.queued(g)
        for material in(replace(work.card,discard=replace(work.card.discard,event_sequence=work.card.discard.event_sequence+1)),
                        replace(work.card,next_attachment_id=g.state.next_attachment_id+1)):
            bad=replace(work,card=material)
            with self.subTest(material=material),self.assertRaises(ValueError):validate_frame_materials(g.state,g.registry,self.replace_work(g,bad))

    def test_rehashed_snapshot_cannot_substitute_false_discard_occurrence(self):
        g=self.first_wait();work=self.queued(g)
        bad=replace(work,card=replace(work.card,discard=replace(work.card.discard,event_sequence=work.card.discard.event_sequence+1)))
        s=g.snapshot();s['resolution_frame']=FrameCodec(g.mechanics,g.registry).encode(self.replace_work(g,bad))
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_typed_and_plain_material_roundtrips_include_original_successful_fact(self):
        g=self.first_wait();work=self.queued(g);codec=FrameCodec(g.mechanics,g.registry)
        self.assertEqual(codec.decode(codec.encode(work)),work)
        data=json.loads(json.dumps(asdict(work.card)));self.assertEqual(from_dict(CopyEntryMaterial,data),work.card)
        data.pop('discard')
        with self.assertRaises(ValueError):from_dict(CopyEntryMaterial,data)
        self.portable(g)

    def test_closed_hand_delivery_rejects_unrelated_owner_destination_mode_or_reference(self):
        g=self.first_wait();work=self.queued(g)
        for fields in({'player_id':2},{'destination':Zone.DECK},{'mode':'base'},{'position':'bottom'},
                       {'source_id':g.state.players[1].hero_id},{'card':work.card.discard},{'card':{}}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):replace(work,**fields)
        with self.assertRaises(ValueError):validate_summon_material(g.registry,work.card)
        with self.assertRaises(ValueError):CardReference.capture(self.original(g))

    def test_material_rejects_late_capture_or_old_acquisition_lease(self):
        g=self.game(('temporary',NATIVE,'discard'),board=('firstwait',))
        self.play(g,'temporary');self.play(g,'discard');material=self.queued(g).card;state=g.state;source=state.entities[self.original(g).id]
        with self.assertRaises(ValueError):replace(material,local=replace(material.local,hand_lifetime=source.hand_lifetime))
        state.action_number+=1
        with self.assertRaises(ValueError):CopyEntryMaterial.capture(state,source,'discard_copy','current',registry=g.registry,player_id=1,discard=material.discard)
        self.assertIsNone(material.local.hand_lifetime);validate_scope(g.state,g.registry,material,hand_copy=True)

    def test_player_ports_do_not_expose_material_history_or_original_internal_identity(self):
        g=self.first_wait();before=g.snapshot()
        for player in(1,2):
            view=json.dumps(g.for_player(player).observe());g.for_player(player).legal_actions()
            for field in('discard_history','hand_entry_id','resolution_frame','zone_epoch','CopyEntryMaterial','behavior_id'):
                self.assertNotIn(field,view)
        self.assertEqual(g.snapshot(),before);self.choose(g);self.portable(g)

    def test_private_discard_and_private_copies_keep_unknown_card_face_hidden(self):
        g=self.game(('private',NATIVE));self.play(g,'private')
        self.assertFalse(discarded_cards(g.state,1)[0].reveal);view=json.dumps(g.observe(2))
        self.assertNotIn('"card_id": "TRL_252"',view);self.assertEqual(len(self.copies(g)),2);self.portable(g)

    def test_copies_do_not_count_as_extra_cast_play_draw_discard_or_death(self):
        g=self.game();cause=self.play(g,'discard')
        self.assertEqual([x.source_id for x in g.state.play_history],[cause]);self.assertEqual([x.source_id for x in g.state.cast_history],[cause])
        self.assertEqual(g.state.draw_history,[]);self.assertEqual(g.state.death_history,[]);self.assertEqual(len(discarded_cards(g.state,1)),1)
        self.assertEqual(len([x for x in g.events if x.kind=='card_created']),2);self.assertEqual(g.snapshot()['schema_version'],265);self.portable(g)
