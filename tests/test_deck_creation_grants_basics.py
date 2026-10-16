"""Atomic deck creation and the actual Sweet Dreams selected destination."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CreatedMinionGrant,
    DiscoverFromPool, DiscoveryGiftPool, DiscoveryMinionGift, Game, GenerationContext, Keyword,
    PlayCard, PlayerSetup, PoolCard, PoolDefinition, PoolMember, PoolQuery, Registry,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Draw, GainArmor, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard
from hs_sim.targets import canonical_digest
from test_dark_gift_keyword_recipes import recipes as ordinary_recipes

ROOT=Path(__file__).resolve().parents[1]
PIN='c86cce76f60b82b8c24591d0debb529d7166f6f3a99d63406fee8ad76c81426d'
SOURCE='EDR_105';MINIONS=('CS2_118','CS2_125','CS2_127');CROC='CS2_120';SWEET='EDR_100t8'
FORCED=('EDR_100t1','EDR_100t6',SWEET)
CONTEXT=GenerationContext('deck-creation-grants-foundation','experimental')
GRANT=CreatedMinionGrant(attack=4,health=5,identity=SWEET)


def evidence():
    p=json.loads((ROOT/'data/support/deck-creation-grants-basics.json').read_bytes())
    if canonical_digest(p)!=PIN:raise ValueError('Full deck creation evidence changed')
    return p


def recipes(ids=FORCED):
    p=evidence();raw={x['id']:x for x in p['records']};base={g.id:g for g in ordinary_recipes()}
    base[SWEET]=DiscoveryMinionGift(SWEET,raw[SWEET]['name'],CreatedMinionGrant(attack=4,health=5),destination='deck_top')
    ids=tuple(p['implemented_recipes']) if ids is None else ids
    for cid in ids:
        if cid not in base:raise ValueError('Unsupported real Dark Gift body: '+cid)
    return tuple(base[cid] for cid in ids)


def registry(ids=FORCED):
    r=Registry('deck-creation-grants-independent-v1');raw={x['id']:x for x in evidence()['records']}
    r.register_card(CardDefinition('dd.hero','Diagnostic mage',CardType.HERO,health=30,
        metadata=CardMetadata(False,(CardClass.MAGE,),None)))
    for cid in (*MINIONS,CROC):
        x=raw[cid];d=CardDefinition(cid,x['name'],CardType.MINION,cost=x['cost'],attack=x['attack'],health=x['health'],
            keywords=(Keyword.TAUNT,) if x['tags'].get('TAUNT') else (),metadata=metadata_from_record(x))
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    r.register_pool(PoolDefinition('dd.minions','experimental-v1',CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(x) for x in MINIONS)))
    gifts=DiscoveryGiftPool('dd.gifts','eight-ordinary-recipes-v1',CONTEXT.target_id,CONTEXT.mode,recipes(ids))
    query=PoolQuery(kinds=(CardType.MINION,),min_cost=3,max_cost=3,collectible=True,class_mode='current')
    r.register_behavior('dd.discover',lambda c:(DiscoverFromPool(c.player_id,'dd.minions',query,
        source_id=c.source_id,gift_pool=gifts),))
    x=raw[SOURCE];r.register_card(CardDefinition(SOURCE,x['name'],CardType.MINION,cost=x['cost'],attack=x['attack'],
        health=x['health'],metadata=metadata_from_record(x),battlecry='dd.discover'))
    r.register_card(CardDefinition('dd.filler','Filler',CardType.MINION,health=1))
    def ref(c):return CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]])
    def before(c):return (RequestChoice(c.player_id,(
        ChoiceOption('make','Deck creation',(AddToDeck(c.player_id,CROC,'top',c.source_id,minion_grant=GRANT),)),
        ChoiceOption('skip','Continue',())),c.source_id),)
    def bad_branch(c):return (RequestChoice(c.player_id,(
        ChoiceOption('valid','Valid',(AddToDeck(c.player_id,CROC,'top',c.source_id,minion_grant=GRANT),)),
        ChoiceOption('invalid','Wrong carrier',(AddToDeck(c.player_id,'dd.draw','top',c.source_id,minion_grant=GRANT),))),c.source_id),)
    bodies={
        'make':lambda c:(AddToDeck(c.player_id,CROC,'top',c.source_id,minion_grant=GRANT),),
        'plain':lambda c:(AddToDeck(c.player_id,CROC,'top',c.source_id),),
        'taunt':lambda c:(AddToDeck(c.player_id,CROC,'top',c.source_id,
            minion_grant=CreatedMinionGrant(health=4,keywords=(Keyword.TAUNT,),identity='EDR_100t3')),),
        'draw':lambda c:(Draw(c.player_id),),
        'copy':lambda c:(CopyCard(ref(c),c.player_id,source_id=c.source_id),),
        'basecopy':lambda c:(CopyCard(ref(c),c.player_id,mode='base',source_id=c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),'bounce':lambda c:(ReturnToHand(c.target_id),),
        'before':before,'badbranch':bad_branch,
        'wrong':lambda c:(AddToDeck(c.player_id,'dd.draw','top',c.source_id,minion_grant=GRANT),),
        'missing':lambda c:(AddToDeck(c.player_id,CROC,'top',999999,minion_grant=GRANT),),
    }
    for key,fn in bodies.items():
        r.register_behavior('dd.script.'+key,fn)
        r.register_card(CardDefinition('dd.'+key,key+' diagnostic',CardType.SPELL,
            on_play='dd.script.'+key,requires_target=key in ('silence','bounce')))
    for key,event in (('created','card_created'),('deck','card_added_to_deck')):
        def inspect(c):
            e=c.state.entities[c.event.target_id]
            if e.card_id not in (*MINIONS,CROC):return ()
            return (GainArmor(c.player_id,e.attack+e.max_health+10*(Keyword.TAUNT in e.keywords)+100*(e.zone==Zone.DECK)),)
        r.register_behavior('dd.probe.'+key,inspect)
        r.register_card(CardDefinition('dd.probe_'+key,key+' observer',CardType.MINION,health=3,
            triggers=(TriggerSpec(event,'dd.probe.'+key),)))
    def after(c):
        if c.state.entities[c.event.target_id].card_id not in (*MINIONS,CROC):return ()
        return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue',()),),c.source_id),)
    r.register_behavior('dd.after.body',after)
    r.register_card(CardDefinition('dd.after','Post-creation choice',CardType.MINION,health=3,
        triggers=(TriggerSpec('card_created','dd.after.body'),)))
    def fail(c):raise ResolutionError('Deliberate deck grant rollback')
    r.register_behavior('dd.fail.body',fail)
    r.register_card(CardDefinition('dd.fail','Failure observer',CardType.MINION,health=3,
        triggers=(TriggerSpec('card_created','dd.fail.body'),)))
    r.register_behavior('dd.fill.body',lambda c:(AddToHand(c.player_id,'dd.filler'),))
    r.register_card(CardDefinition('dd.fill','Fill freed slot',CardType.MINION,health=3,
        triggers=(TriggerSpec('choice_selected','dd.fill.body'),)))
    return r


class DeckCreationGrantTests(unittest.TestCase):
    def game(self,hand=(SOURCE,),board=(),ids=FORCED):
        return Game.from_scenario(Scenario((
            PlayerSetup('dd.hero',hand=hand,board=board,deck=(CROC,)*8,mana=10,max_mana=10),
            PlayerSetup('dd.hero',hand=(CROC,),deck=(CROC,)*8)),seed=117,generation_context=CONTEXT),registry(ids))
    def play(self,g,cid=SOURCE,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target));return eid
    def choose(self,g,gift=SWEET):
        option=next(o for o in g._frame.options if o.effects[0].selection.gift.id==gift)
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option.id,)));return option
    def created(self,g):return g.state.entities[next(e.target_id for e in reversed(g.events) if e.kind=='card_created')]
    def portable(self,g,ids=FORCED):
        saved=json.loads(json.dumps(g.snapshot()))
        for other in (Game.from_snapshot(saved,registry(ids)),g.clone(),replay(build_replay(g),registry(ids))):
            self.assertEqual(other.snapshot(),saved)
        return saved
    def nodes(self,value,suffix):
        if isinstance(value,dict):
            if value.get('type','').endswith('.'+suffix):yield value['fields']
            for x in value.values():yield from self.nodes(x,suffix)
        elif isinstance(value,list):
            for x in value:yield from self.nodes(x,suffix)
    def reject(self,saved):
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in
            ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())
    def marker(self,e,cid=SWEET):return [a for a in e.enchantments if a.label=='created_minion_grant:'+cid]

    def test_complete_raw_scope_keeps_all_twelve_faces_and_four_unknown_bodies(self):
        p=evidence();self.assertEqual((len(p['records']),len(p['all_local_gift_faces']),len(p['implemented_recipes'])),(33,12,8))
        self.assertEqual(set(p['unsupported_recipe_faces']),{'EDR_100t4','EDR_100t5','EDR_100t7','EDR_100t10'})
        self.assertFalse(p['current_formal_pool_verified']);self.assertFalse(p['whole_dark_gift_implemented'])
        self.assertFalse(p['CN_calibrated'])
        with self.assertRaisesRegex(ValueError,'Unsupported real'):recipes(tuple(p['all_local_gift_faces']))

    def test_direct_deck_creator_installs_grant_before_both_observers_without_hand_entry(self):
        g=self.game(hand=('dd.make',),board=('dd.probe_created','dd.probe_deck'))
        source=self.play(g,'dd.make');e=self.created(g)
        self.assertEqual((e.zone,e.attack,e.max_health),(Zone.DECK,6,8))
        self.assertEqual(g.state.players[1].deck[0],e.id);self.assertEqual(self.marker(e)[0].source_id,source)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,228)
        self.assertFalse(any(x.entity_id==e.id for x in g.state.hand_entries))
        self.assertFalse(any(x.kind in ('card_added_to_hand','card_burned') and x.target_id==e.id for x in g.events))
        self.portable(g)

    def test_deck_keyword_grant_uses_same_atomic_installer_and_survives_draw(self):
        g=self.game(hand=('dd.taunt','dd.draw'));self.play(g,'dd.taunt');e=self.created(g)
        self.assertEqual((e.attack,e.max_health),(2,7));self.assertIn(Keyword.TAUNT,e.keywords)
        self.play(g,'dd.draw');drawn=g.state.entities[e.id]
        self.assertEqual(drawn.zone,Zone.HAND);self.assertIn(Keyword.TAUNT,drawn.keywords)
        self.assertEqual(len(self.marker(drawn,'EDR_100t3')),1);self.portable(g)

    def test_plain_deck_creation_and_older_same_name_cards_remain_unchanged(self):
        g=self.game(hand=('dd.make','dd.plain',CROC));old=list(g.state.players[1].deck)+[g.state.players[1].hand[-1]]
        self.play(g,'dd.make');gift=self.created(g)
        for eid in old:self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].max_health),(2,3))
        self.play(g,'dd.plain');plain=self.created(g)
        self.assertEqual((plain.attack,plain.max_health),(2,3));self.assertEqual(self.marker(plain),[])
        self.assertNotEqual(plain.id,gift.id);self.portable(g)

    def test_sweet_dreams_choice_shows_deck_destination_and_delivers_matching_preview(self):
        g=self.game();source=self.play(g)
        option=next(o for o in g._frame.options if o.effects[0].selection.gift.id==SWEET)
        self.assertIn('置于牌库顶',option.label);self.portable(g)
        chosen=self.choose(g);e=self.created(g)
        self.assertEqual((e.zone,e.attack,e.max_health),(Zone.DECK,chosen.preview.attack,chosen.preview.max_health))
        self.assertEqual(g.state.players[1].deck[0],e.id);self.assertEqual(self.marker(e)[0].source_id,source)
        self.assertEqual(len(g.state.players[1].deck),9);self.assertEqual(len(g.state.players[1].hand),0)
        self.assertFalse(any(x.entity_id==e.id for x in g.state.hand_entries));self.portable(g)

    def test_full_hand_does_not_burn_or_transiently_acquire_deck_bound_result(self):
        g=self.game(hand=(SOURCE,)+('dd.filler',)*9,board=('dd.fill',));self.play(g);self.choose(g);e=self.created(g)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(e.zone,Zone.DECK)
        self.assertEqual(g.state.players[1].deck[0],e.id)
        self.assertFalse(any(x.kind in ('card_added_to_hand','card_burned') and x.target_id==e.id for x in g.events))
        self.assertFalse(any(x.entity_id==e.id for x in g.state.hand_entries));self.portable(g)

    def test_later_draw_preserves_selected_stats_identity_and_original_discovery_source(self):
        g=self.game(hand=(SOURCE,'dd.draw'));source=self.play(g);self.choose(g);e=self.created(g)
        self.play(g,'dd.draw');drawn=g.state.entities[e.id]
        self.assertEqual(drawn.zone,Zone.HAND);self.assertEqual(self.marker(drawn)[0].source_id,source)
        self.assertEqual((drawn.attack,drawn.max_health),(e.attack,e.max_health))
        self.assertEqual(len([x for x in g.state.hand_entries if x.entity_id==e.id]),1)
        self.portable(g)

    def test_current_deck_copy_preserves_grant_and_base_copy_uses_printed_material(self):
        g=self.game(hand=('dd.make','dd.copy','dd.basecopy'));self.play(g,'dd.make');original=self.created(g)
        self.play(g,'dd.copy');copy=self.created(g)
        self.assertEqual((copy.attack,copy.max_health),(6,8));self.assertEqual(len(self.marker(copy)),1)
        self.assertTrue({a.id for a in copy.enchantments}.isdisjoint(a.id for a in original.enchantments))
        self.play(g,'dd.basecopy');base=self.created(g)
        self.assertEqual((base.attack,base.max_health),(2,3));self.assertEqual(self.marker(base),[])
        self.assertEqual(g.state.players[1].deck[0],original.id);self.portable(g)

    def test_drawn_card_silence_and_bounce_follow_existing_reset_rules(self):
        g=self.game(hand=('dd.make','dd.draw','dd.silence','dd.bounce'));self.play(g,'dd.make');e=self.created(g)
        self.play(g,'dd.draw');self.play(g,CROC);self.play(g,'dd.silence',e.id)
        silenced=g.state.entities[e.id];self.assertEqual((silenced.attack,silenced.max_health),(2,3))
        self.assertEqual(self.marker(silenced),[]);self.play(g,'dd.bounce',e.id)
        returned=g.state.entities[e.id];self.assertEqual((returned.zone,returned.attack,returned.max_health),(Zone.HAND,2,3))
        self.assertEqual(self.marker(returned),[]);self.portable(g)

    def test_waiting_before_direct_creation_restores_typed_grant_and_creates_only_once(self):
        g=self.game(hand=('dd.before',));self.play(g,'dd.before');saved=self.portable(g)
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('make',)));self.assertEqual((self.created(g).attack,self.created(g).max_health),(6,8))
        other=Game.from_snapshot(saved,registry());q=other.state.pending_choice;other.apply(SelectChoice(q.player_id,q.id,('make',)))
        self.assertEqual(other.snapshot(),g.snapshot());self.assertEqual(len([x for x in g.events if x.kind=='card_created']),1)

    def test_waiting_after_deck_creation_keeps_selected_receipt_and_card_at_top(self):
        g=self.game(board=('dd.after',));self.play(g);self.choose(g);e=self.created(g);self.portable(g)
        self.assertEqual(e.zone,Zone.DECK);self.assertEqual(g.state.players[1].deck[0],e.id)
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('continue',)));self.portable(g)
        self.assertEqual(len([x for x in g.events if x.kind=='pool_discovery_picked']),1)

    def test_top_insertion_and_selected_delivery_do_not_use_more_rng_or_payment(self):
        g=self.game();self.play(g);rng=g.snapshot()['rng_state'];self.choose(g)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual(len(g.state.battlecry_history),1)
        plain=self.game(hand=('dd.make',));rng=plain.snapshot()['rng_state'];self.play(plain,'dd.make')
        self.assertEqual(plain.snapshot()['rng_state'],rng)

    def test_actual_choice_receipt_includes_selected_deck_top_policy(self):
        g=self.game();self.play(g);choice=g.state.pending_choice;option=self.choose(g)
        event=next(x for x in g.events if x.kind=='pool_discovery_picked')
        from hs_sim.engine.continuations import FrameCodec
        effect=FrameCodec(g.mechanics,g.registry).decode(json.loads(dict(event.data)['receipt']))
        self.assertEqual(effect.choice_result.choice,choice);self.assertEqual(effect.choice_result.selected_ids,(option.id,))
        self.assertEqual(effect.selection.gift.destination,'deck_top');self.assertEqual(effect.selection.gift.id,SWEET)
        self.portable(g)

    def test_creation_observer_failure_rolls_back_deck_selected_receipt_and_rng(self):
        g=self.game(board=('dd.fail',));self.play(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Deliberate deck grant'):self.choose(g)
        self.assertEqual(g.snapshot(),saved)
        direct=self.game(hand=('dd.make',),board=('dd.fail',));saved=direct.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Deliberate deck grant'):self.play(direct,'dd.make')
        self.assertEqual(direct.snapshot(),saved)

    def test_invalid_deck_carrier_source_and_unselected_branch_are_rejected(self):
        for cid in ('dd.wrong','dd.missing','dd.badbranch'):
            g=self.game(hand=(cid,));saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,cid)
            self.assertEqual(g.snapshot(),saved)
        with self.assertRaises(ValueError):AddToDeck(1,CROC,'top',minion_grant={'attack':4})

    def test_saved_selected_policy_cannot_disagree_with_declared_gift_inventory(self):
        g=self.game();self.play(g);saved=g.snapshot()
        pick=next(x for x in self.nodes(saved,'DiscoveryPick') if x['gift']['fields']['id']==SWEET)
        pick['gift']['fields']['destination']='hand';self.reject(saved)
        for value in (None,True,'deck','board','random'):
            with self.assertRaises(ValueError):replace(next(g for g in recipes() if g.id==SWEET),destination=value)

    def test_player_view_hides_created_deck_card_and_receipts_until_normal_draw(self):
        g=self.game(hand=(SOURCE,'dd.draw'));self.play(g);self.choose(g);e=self.created(g)
        for seat in (1,2):
            port=g.for_player(seat);wire=json.dumps((port.observe(),port.legal_actions(),port.events()),ensure_ascii=False)
            for field in ('offered_gifts','DiscoveryGiftPool','pool_discovery_picked','"receipt"','resolution_frame'):
                self.assertNotIn(field,wire)
            self.assertNotIn('entities',port.observe()['observation'])
        self.assertNotIn(e.card_id,json.dumps(g.for_player(2).observe(),ensure_ascii=False))
        self.play(g,'dd.draw');row=next(x for x in g.for_player(1).observe()['observation']['players'][0]['hand'] if x.get('card_id')==e.card_id)
        self.assertEqual((row['attack'],row['max_health']),(e.attack,e.max_health))
        self.assertNotIn(e.card_id,json.dumps(g.for_player(2).observe(),ensure_ascii=False));self.portable(g)

    def test_eight_recipe_inventory_shares_one_contract_and_old_schema_is_rejected(self):
        g=self.game(ids=None);self.play(g);self.portable(g,ids=None)
        self.assertEqual(len(g._frame.options[0].effects[0].batch.spec.gift_pool.members),8)
        saved=g.snapshot();self.assertEqual(saved['schema_version'],SNAPSHOT_SCHEMA_VERSION);saved['schema_version']=228
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(ids=None))

