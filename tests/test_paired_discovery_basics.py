"""Real Dark Gift discovery foundation in explicitly incomplete test inventories."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CreatedMinionGrant,
    DiscoverFromPool, DiscoveryGiftPool, DiscoveryMinionGift, Game, GenerationContext, Keyword,
    PlayCard, PlayerSetup, PoolCard, PoolDefinition, PoolMember, PoolQuery, Registry,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import AddToHand, ChoiceOption, Destroy, GainArmor, RequestChoice, ReturnToHand, Silence
from hs_sim.engine.model import ChoicePurpose, CostSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1]
PIN='2f57f0cff66ea9ab112f33ab5a961eb172807268c83d0ccbc8e86061a0fea9cc'
SOURCE='EDR_105';NATIVES=('CS2_118','CS2_125','CS2_127')
CONTEXT=GenerationContext('paired-discovery-foundation','experimental')
QUERY=PoolQuery(kinds=(CardType.MINION,),min_cost=3,max_cost=3,collectible=True,class_mode='current')


def evidence():
    value=json.loads((ROOT/'data/support/paired-discovery-basics.json').read_bytes())
    if canonical_digest(value)!=PIN:raise ValueError('Full paired discovery evidence changed')
    return value


def recipes(ids=('EDR_100t','EDR_100t2','EDR_100t3','EDR_100t9')):
    raw={x['id']:x for x in evidence()['records']}
    grants={
        'EDR_100t':CreatedMinionGrant(attack=3,keywords=(Keyword.LIFESTEAL,)),
        'EDR_100t2':CreatedMinionGrant(attack=-2),
        'EDR_100t3':CreatedMinionGrant(health=4,keywords=(Keyword.TAUNT,)),
        'EDR_100t9':CreatedMinionGrant(keywords=(Keyword.REBORN,),reborn_policy='full_health_enchantments'),
    }
    # Explicit experimental scope, never quietly remove an unsupported face.
    for cid in ids:
        if cid not in grants:raise ValueError('Unsupported real Dark Gift body: '+cid)
    return tuple(DiscoveryMinionGift(cid,raw[cid]['name'],grants[cid],
        cost_delta=-2 if cid=='EDR_100t2' else 0,min_attack=3 if cid=='EDR_100t2' else 0) for cid in ids)


def gift_pool(ids=None,**changes):
    return replace(DiscoveryGiftPool('dg.gifts','experimental-four-v1',CONTEXT.target_id,
        CONTEXT.mode,recipes() if ids is None else recipes(ids)),**changes)


def registry(ids=None,members=NATIVES,unknown=False,foreign=False):
    r=Registry('paired-discovery-independent-v1');raw={x['id']:x for x in evidence()['records']}
    r.register_card(CardDefinition('dg.hero','Diagnostic mage',CardType.HERO,health=30,
        metadata=CardMetadata(False,(CardClass.MAGE,),None)))
    for cid in (*NATIVES,'CS2_120','CS2_182'):
        x=raw[cid];d=CardDefinition(cid,x['name'],CardType.MINION,cost=x['cost'],attack=x['attack'],
            health=x['health'],keywords=(Keyword.TAUNT,) if x.get('tags',{}).get('TAUNT') else (),
            metadata=metadata_from_record(x))
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    extra=[]
    if unknown:
        d=CardDefinition('dg.unknown','Unimplemented eligible minion',CardType.MINION,cost=3,attack=4,health=4,
            metadata=CardMetadata(True,(CardClass.NEUTRAL,),None))
        r.register_pool_card(PoolCard.from_definition(d));extra.append(d.id)
    if foreign:
        d=CardDefinition('dg.foreign','Unimplemented other-class minion',CardType.MINION,cost=3,attack=4,health=4,
            metadata=CardMetadata(True,(CardClass.WARRIOR,),None))
        r.register_pool_card(PoolCard.from_definition(d));extra.append(d.id)
    r.register_pool(PoolDefinition('dg.minions','experimental-v1',CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(x) for x in (*members,*extra))))
    profile=gift_pool(ids)
    r.register_behavior('dg.native.discover',lambda c:(DiscoverFromPool(c.player_id,'dg.minions',QUERY,
        source_id=c.source_id,gift_pool=profile),))
    x=raw[SOURCE];r.register_card(CardDefinition(SOURCE,x['name'],CardType.MINION,cost=x['cost'],
        attack=x['attack'],health=x['health'],metadata=metadata_from_record(x),battlecry='dg.native.discover'))
    r.register_card(CardDefinition('dg.filler','Filler',CardType.MINION,health=1))
    def inspect(c):
        e=c.state.entities[c.event.target_id]
        if e.card_id not in NATIVES:return ()
        amount=e.cost+e.attack+e.max_health+10*len([a for a in e.enchantments if a.label.startswith('created_minion_grant:')])
        return (GainArmor(c.player_id,amount),)
    r.register_behavior('dg.probe.body',inspect)
    r.register_card(CardDefinition('dg.probe','Creation observer',CardType.MINION,health=3,
        triggers=(TriggerSpec('card_created','dg.probe.body'),)))
    def after(c):
        if c.state.entities[c.event.target_id].card_id not in NATIVES:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue',()),),c.source_id),)
    r.register_behavior('dg.after.body',after)
    r.register_card(CardDefinition('dg.after','Post-creation choice',CardType.MINION,health=3,
        triggers=(TriggerSpec('card_created','dg.after.body'),)))
    def fail(c):raise ResolutionError('Deliberate gift creation rollback')
    r.register_behavior('dg.fail.body',fail)
    r.register_card(CardDefinition('dg.fail','Failure observer',CardType.MINION,health=3,
        triggers=(TriggerSpec('card_created','dg.fail.body'),)))
    r.register_behavior('dg.fill.body',lambda c:(AddToHand(c.player_id,'dg.filler'),))
    r.register_card(CardDefinition('dg.fill','Fill freed hand slot',CardType.MINION,health=3,
        triggers=(TriggerSpec('choice_selected','dg.fill.body'),)))
    def ref(c):return CardReference.capture(next(c.state.entities[i] for i in c.state.players[c.player_id].hand
        if c.state.entities[i].card_id in NATIVES))
    bodies={'copy':lambda c:(CopyCard(ref(c),c.player_id,source_id=c.source_id),),
        'basecopy':lambda c:(CopyCard(ref(c),c.player_id,mode='base',source_id=c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),'bounce':lambda c:(ReturnToHand(c.target_id),),
        'kill':lambda c:(Destroy(c.target_id),)}
    for key,fn in bodies.items():
        r.register_behavior('dg.script.'+key,fn)
        r.register_card(CardDefinition('dg.'+key,key+' diagnostic',CardType.SPELL,on_play='dg.script.'+key,
            requires_target=key in ('silence','bounce','kill')))
    return r


class PairedDiscoveryTests(unittest.TestCase):
    def game(self,ids=None,members=NATIVES,hand=(SOURCE,),board=(),enemy_hand=(),seed=115,unknown=False,foreign=False,context=CONTEXT):
        r=registry(ids,members,unknown,foreign)
        g=Game.from_scenario(Scenario((PlayerSetup('dg.hero',hand=hand,board=board,mana=10,max_mana=10),
            PlayerSetup('dg.hero',hand=enemy_hand)),seed=seed,generation_context=context),r)
        return g
    def play(self,g,cid=SOURCE,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target));return eid
    def choose(self,g,gift=None,card=None):
        options=g._frame.options
        option=next(o for o in options if (gift is None or o.effects[0].selection.gift.id==gift) and
            (card is None or o.card_id==card))
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option.id,)))
        return option
    def created(self,g):
        return g.state.entities[next(e.target_id for e in reversed(g.events) if e.kind=='card_created')]
    def portable(self,g,ids=None,members=NATIVES):
        saved=json.loads(json.dumps(g.snapshot()))
        for other in (Game.from_snapshot(saved,registry(ids,members)),g.clone(),replay(build_replay(g),registry(ids,members))):
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

    def test_full_raw_scope_keeps_all_twelve_faces_and_real_three_cost_source(self):
        p=evidence();raw={x['id']:x for x in p['records']}
        self.assertEqual(len(p['all_local_gift_faces']),12)
        self.assertEqual(len(p['unsupported_recipe_faces']),8)
        self.assertEqual((raw[SOURCE]['cost'],raw[SOURCE]['attack'],raw[SOURCE]['health']),(2,1,1))
        self.assertIn('（3）',raw[SOURCE]['text'])
        self.assertFalse(p['current_formal_pool_verified']);self.assertFalse(p['whole_dark_gift_implemented'])
        self.assertFalse(p['CN_calibrated'])
        with self.assertRaisesRegex(ValueError,'Unsupported real'):recipes(p['all_local_gift_faces'])

    def test_native_battlecry_offers_three_distinct_real_minions_and_gifts(self):
        g=self.game(members=(*NATIVES,'CS2_120','CS2_182'),foreign=True);source=self.play(g)
        q=g.state.pending_choice
        self.assertEqual(q.purpose,ChoicePurpose.POOL_DISCOVERY)
        self.assertEqual((q.player_id,q.source_id),(1,source))
        self.assertEqual({o.card_id for o in q.options},set(NATIVES))
        gifts=[o.effects[0].selection.gift.id for o in g._frame.options]
        self.assertEqual(len(set(gifts)),3);self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual(len(g.state.battlecry_history),1)

    def test_short_claws_uses_attack_eligibility_and_ordinary_cost_reduction(self):
        ids=('EDR_100t','EDR_100t2','EDR_100t3');g=self.game(ids=ids);self.play(g)
        option=next(o for o in g._frame.options if o.effects[0].selection.gift.id=='EDR_100t2')
        self.assertIn(option.card_id,('CS2_118','CS2_125'))
        self.assertNotEqual(option.card_id,'CS2_127')
        self.choose(g,gift='EDR_100t2');e=self.created(g)
        self.assertGreaterEqual(e.attack,1);self.assertEqual(e.cost,1)
        self.assertEqual(CostSpec(delta=-2).minimum,0)

    def test_selected_preview_matches_atomic_created_entity_and_observer(self):
        g=self.game(board=('dg.probe',));source=self.play(g);option=self.choose(g)
        e=self.created(g);preview=option.preview
        self.assertEqual((e.cost,e.attack,e.max_health),(preview.cost,preview.attack,preview.max_health))
        self.assertEqual(set(e.keywords),set(preview.keywords))
        marker=[x for x in e.enchantments if x.label=='created_minion_grant:'+option.effects[0].selection.gift.id]
        self.assertEqual(len(marker),1);self.assertEqual(marker[0].source_id,source)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,e.cost+e.attack+e.max_health+10)

    def test_actual_choice_result_and_all_ordered_bindings_enter_private_receipt(self):
        g=self.game();source=self.play(g);choice=g.state.pending_choice;option=self.choose(g)
        event=next(e for e in g.events if e.kind=='pool_discovery_picked')
        from hs_sim.engine.continuations import FrameCodec
        effect=FrameCodec(g.mechanics,g.registry).decode(json.loads(dict(event.data)['receipt']))
        self.assertEqual(effect.choice_result.choice,choice)
        self.assertEqual(effect.choice_result.selected_ids,(option.id,))
        self.assertEqual(effect.selection.card_id,option.card_id)
        self.assertEqual(effect.offered_card_ids,tuple(o.card_id for o in choice.options))
        self.assertEqual(len(effect.offered_gifts),3);self.assertEqual(event.source_id,source)
        self.portable(g)

    def test_waiting_resume_preserves_binding_rng_and_payment_across_independent_hosts(self):
        g=self.game();self.play(g);self.portable(g)
        rng=g.snapshot()['rng_state'];mana=g.state.players[1].mana
        branch=g._frame.options[1];saved=g.snapshot();self.choose(g,card=branch.card_id)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(g.state.players[1].mana,mana)
        other=Game.from_snapshot(saved,registry());self.choose(other,card=branch.card_id)
        self.assertEqual(other.snapshot(),g.snapshot())

    def test_post_creation_waiting_restores_selected_gift_receipt_and_physical_card(self):
        g=self.game(board=('dg.after',));self.play(g);self.choose(g)
        self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.EFFECT)
        self.assertEqual(len([e for e in g.events if e.kind=='pool_discovery_picked']),1)
        self.portable(g);q=g.state.pending_choice
        g.apply(SelectChoice(q.player_id,q.id,('continue',)));self.portable(g)

    def test_full_hand_burn_still_receives_selected_grant_and_original_source(self):
        g=self.game(hand=(SOURCE,)+('dg.filler',)*9,board=('dg.fill',));source=self.play(g)
        option=self.choose(g);e=self.created(g)
        self.assertEqual(e.zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.players[1].hand),10)
        self.assertTrue(any(a.label=='created_minion_grant:'+option.effects[0].selection.gift.id and
            a.source_id==source for a in e.enchantments))
        self.assertTrue(any(x.kind=='card_burned' and x.target_id==e.id for x in g.events))
        self.assertFalse(any(x.entity_id==e.id for x in g.state.hand_entries))
        self.portable(g)

    def test_observer_failure_rolls_back_selection_creation_receipt_and_rng(self):
        g=self.game(board=('dg.fail',));self.play(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),saved)
        self.assertFalse(any(e.kind=='pool_discovery_picked' for e in g.events))

    def test_unknown_eligible_candidate_is_not_filtered_before_sampling(self):
        g=self.game(unknown=True);before=g.snapshot()
        with self.assertRaises((ValueError,ResolutionError)):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_empty_pool_skips_all_offer_rng_and_keeps_single_payment(self):
        g=self.game(members=());before=g.snapshot()['rng_state'];self.play(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertEqual(g.state.players[1].mana,8)
        self.assertFalse(any(e.kind=='pool_discovery_picked' for e in g.events))
        self.portable(g,members=())

    def test_invalid_gift_inventory_types_duplicates_and_unknown_bodies_are_rejected(self):
        pool=gift_pool()
        for members in (list(pool.members),pool.members[:2],(*pool.members,pool.members[0]),(*pool.members,None)):
            with self.assertRaises(ValueError):replace(pool,members=members)
        for args in (dict(grant=None),dict(min_attack=True),dict(cost_delta=True),dict(cost_delta=1),
                dict(grant=replace(pool.members[0].grant,identity='forged'))):
            with self.assertRaises(ValueError):replace(pool.members[0],**args)

    def test_context_binding_and_unsupported_delivery_forms_fail_explicitly(self):
        with self.assertRaises(ValueError):gift_pool(mode='standard')
        for args in (dict(destination='deck'),dict(discoveries=2),dict(count=2),dict(cost=CostSpec(set_to=1)),
                dict(delivery='after_all'),dict(replacement=False)):
            with self.assertRaises(ValueError):DiscoverFromPool(1,'dg.minions',gift_pool=gift_pool(),**args)
        g=self.game(context=GenerationContext('other-target','experimental'));before=g.snapshot()
        with self.assertRaises(ValueError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_selected_branch_cannot_swap_gift_from_another_offered_minion(self):
        g=self.game();self.play(g);saved=g.snapshot()
        branches=list(self.nodes(saved,'ResolvePoolDiscovery'))
        branches[0]['selection']['fields']['gift']=branches[1]['selection']['fields']['gift']
        self.reject(saved)

    def test_one_branch_cannot_change_complete_ordered_gift_bindings(self):
        g=self.game();self.play(g);saved=g.snapshot()
        branch=next(self.nodes(saved,'ResolvePoolDiscovery'))
        gifts=branch['offered_gifts']['tuple']
        gifts[0],gifts[1]=gifts[1],gifts[0]
        self.reject(saved)

    def test_saved_gift_recipe_or_preview_cannot_disagree_with_inventory(self):
        g=self.game();self.play(g)
        saved=g.snapshot();pick=next(self.nodes(saved,'DiscoveryPick'))
        pick['gift']['fields']['label']='Forged label';self.reject(saved)
        saved=g.snapshot();preview=next(self.nodes(saved,'CardPreview'))
        preview['attack']+=1;self.reject(saved)

    def test_current_copy_keeps_gift_identity_and_base_copy_clears_it(self):
        g=self.game(hand=(SOURCE,'dg.copy','dg.basecopy'));self.play(g);self.choose(g);original=self.created(g)
        self.play(g,'dg.copy');copy=self.created(g)
        self.assertEqual([a.label for a in copy.enchantments],[a.label for a in original.enchantments])
        self.assertTrue(set(a.id for a in copy.enchantments).isdisjoint(a.id for a in original.enchantments))
        self.play(g,'dg.basecopy');base=self.created(g)
        self.assertFalse(any(a.label.startswith('created_minion_grant:') for a in base.enchantments))
        self.portable(g)

    def test_keyword_only_marker_follows_ordinary_silence_and_bounce_lifecycle(self):
        ids=('EDR_100t','EDR_100t3','EDR_100t9');g=self.game(ids=ids,hand=(SOURCE,'dg.silence','dg.bounce'))
        self.play(g);self.choose(g,gift='EDR_100t9');e=self.created(g)
        self.assertTrue(any(a.label.endswith('EDR_100t9') for a in e.enchantments))
        self.play(g,e.card_id);self.play(g,'dg.silence',e.id)
        self.assertFalse(any(a.label.startswith('created_minion_grant:') for a in g.state.entities[e.id].enchantments))
        self.play(g,'dg.bounce',e.id)
        self.assertNotIn(Keyword.REBORN,g.state.entities[e.id].keywords)
        self.portable(g,ids=ids)

    def test_player_view_shows_owned_offer_preview_and_hides_private_bindings_and_enemy_hand(self):
        from hs_sim.engine.player_api import PlayerPort
        g=self.game(enemy_hand=('CS2_182',));self.play(g)
        own=PlayerPort(g,1).legal_actions();enemy=PlayerPort(g,2).legal_actions()
        owned=json.dumps(own,ensure_ascii=False);hidden=json.dumps(enemy,ensure_ascii=False)
        self.assertIn('preview',owned);self.assertNotIn('offered_gifts',owned)
        self.assertNotIn('DiscoveryGiftPool',owned);self.assertNotIn('source_card_id',owned)
        self.assertNotIn('CS2_182',owned)
        for cid in NATIVES:self.assertNotIn(cid,hidden)
        self.choose(g);public=json.dumps(PlayerPort(g,1).legal_actions(),ensure_ascii=False)
        self.assertNotIn('pool_discovery_picked',public);self.assertNotIn('receipt',public)
        for seat in (1,2):
            port=PlayerPort(g,seat)
            wire=json.dumps((port.observe(),port.legal_actions(),port.events()),ensure_ascii=False)
            for field in ('offered_gifts','DiscoveryGiftPool','pool_discovery_picked','"receipt"','resolution_frame'):
                self.assertNotIn(field,wire)

    def test_new_payloads_roundtrip_and_old_schema_is_rejected(self):
        g=self.game();self.play(g);saved=self.portable(g)
        self.assertEqual(saved['schema_version'],SNAPSHOT_SCHEMA_VERSION)
        saved['schema_version']=227
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())

