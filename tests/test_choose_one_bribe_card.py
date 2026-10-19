"""Noxious Bribe: one real choice, a combined friendly card and plain peer copy."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry as assembled_registry
from hs_sim.cards.choose_one_bribe_card import ROOT,BODY,load_batch,register_choose_one_bribe_card
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,
    Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand,ChoiceOption,InvokeBehavior,RandomDamage,RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CostSpec
from hs_sim.engine.pools import DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastStoredSpell
from hs_sim.engine.zones import CardReference,CopyCard,ModifyStoredCost

P='bribe.test.';TINY=P+'tiny';WRATH='CORE_EX1_154';WAR='EX1_178';NOURISH='EX1_164'
CHOICES=(WRATH,WAR,NOURISH);YETI='CS2_182';POOL='constructed.cards';TARGET=P+'target'


@lru_cache(maxsize=1)
def full_registry():return assembled_registry()


@lru_cache(maxsize=None)
def registry(role,mode=None,pool_mode=None):
    assert role in ('writer','reader')
    r=build_registry();full=full_registry();card=full.card(WRATH)
    prefixes=tuple(b.behavior_id for b in (*card.choose_one.branches,card.choose_one.combined))
    for name,body in full._behaviors.items():
        if any(name==prefix or name.startswith(prefix+'.')for prefix in prefixes):
            r.register_behavior(name,body)
    r.register_card(card);register_choose_one_bribe_card(r)
    meta=replace(r.card(YETI).metadata,deck_identity=None)
    r.register_card(CardDefinition(TINY,TINY,CardType.MINION,cost=0,attack=1,health=2,metadata=meta))
    def fail(c):raise ResolutionError('Bribe deliberate rollback')
    r.register_behavior(P+'fail',fail)
    for key,mode_value in (('copy','current'),('base-copy','base')):
        r.register_behavior(P+key,lambda c,m=mode_value:(CopyCard(
            CardReference.capture(c.state.entities[c.target_id]),c.player_id,mode=m,source_id=c.source_id),))
        r.register_card(CardDefinition(P+key,P+key,CardType.SPELL,on_play=P+key,
            targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,CardType.SPELL),relation='friendly'),metadata=meta))
    r.register_behavior(P+'cast',lambda c:(CastStoredSpell(CardReference.capture(c.state.entities[c.target_id]),
        c.player_id,c.source_id,target_id=c.state.players[2].board[0],targeting='explicit'),))
    r.register_card(CardDefinition(P+'cast',P+'cast',CardType.SPELL,on_play=P+'cast',
        targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.SPELL,),relation='friendly'),metadata=meta))
    if mode:
        def watch(c):
            if mode in ('counter','fill'):
                source=c.state.entities.get(c.event.source_id)
                if source is None or source.card_id!=ROOT:return ()
                return (CounterSpell(dict(c.event.data)['window_id']),)if mode=='counter'else(AddToHand(1,TINY,c.source_id),)
            target=c.state.entities.get(c.event.target_id);owner=1 if mode=='friendly'else 2
            if target is None or target.card_id not in CHOICES or target.controller!=owner:return ()
            return (RequestChoice(c.player_id,(
                ChoiceOption('ok','Continue',()),
                ChoiceOption('buff','Discount friendly',(ModifyStoredCost(CardReference.capture(target),CostSpec(set_to=0),source_id=c.source_id),)),
                ChoiceOption('fail','Fail',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),
                    InvokeBehavior(P+'fail',c.source_id,c.player_id)))),c.source_id),)
        r.register_behavior(P+'watch',watch)
        event='card_committed'if mode in ('counter','fill')else'card_created'
        r.register_card(CardDefinition(P+'watch',P+'watch',CardType.MINION,health=8,
            triggers=(TriggerSpec(event,P+'watch'),),metadata=meta))
    members=[]
    for cid in (()if pool_mode=='empty'else(*CHOICES,TINY)):
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
        members.append(PoolMember(cid))
    if pool_mode=='unknown':
        row=replace(r.card(WAR),id=P+'unknown',name=P+'unknown',metadata=replace(r.card(WAR).metadata,deck_identity=None))
        r.register_pool_card(PoolCard.from_definition(row));members.append(PoolMember(row.id))
    r.register_pool(PoolDefinition(POOL,P+'v1',TARGET,'experimental',tuple(members),complete=True))
    r.validate();r.freeze();return r


class ChooseOneBribeTests(unittest.TestCase):
    def game(self,hand=(ROOT,),*,enemy_hand=(),mode=None,pool_mode=None,board=()):
        self.mode=mode;self.pool_mode=pool_mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board+((P+'watch',)if mode else()),
                deck=(TINY,)*12,mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=enemy_hand,board=(YETI,),deck=(TINY,)*12,mana=10,max_mana=10)),
            seed=237861,generation_context=GenerationContext(TARGET,'experimental')),registry('writer',mode,pool_mode))
    def play(self,g,cid=ROOT,target=None,branch=None,eid=None):
        pid=g.state.active_player;eid=eid or next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        return g.apply(PlayCard(pid,eid,target,len(g.state.players[pid].board)
            if g.registry.card(cid).kind==CardType.MINION else None,branch_id=branch))
    def choose(self,g,key):
        q=g.state.pending_choice;return g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def pick(self,g,cid):
        option=next(x for x in g.state.pending_choice.options if x.card_id==cid)
        return self.choose(g,option.id)
    def copies(self,g,cid,pid=1):return [e for e in g.state.entities.values()if e.card_id==cid and e.owner==pid]
    def portable(self,g):
        r=registry('reader'if g.registry is registry('writer',self.mode,self.pool_mode)else'writer',self.mode,self.pool_mode)
        self.assertIsNot(r,g.registry);s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,r)
        for v in (other,g.clone(),replay(build_replay(g),r)):self.assertEqual(v.snapshot(),s)
        for pid in (1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for field in ('rng_state','resolution_frame','original_entities','DiscoveryPick','paired_choose_one'):
                self.assertNotIn(field,wire)
        return other
    def test_a00_complete_source_two_primary_faces_real_standard_wrath_and_root(self):
        from tools.card_batch import check_face
        d=load_batch();raw=d['cards'][0]['record'];self.assertEqual(len(d['official_observations']),2)
        for o in d['official_observations']:check_face(raw,o['face'],o['locale'])
        r=registry('writer');self.assertEqual(r.card(ROOT),full_registry().card(ROOT))
        self.assertEqual(r.card(WRATH),full_registry().card(WRATH))
        self.assertEqual((r.card(ROOT).cost,r.card(ROOT).kind),(2,CardType.SPELL))
        self.assertNotIn(ROOT+'e',r.cards)
    def test_b00_one_private_offer_exact_filter_and_only_root_payment(self):
        g=self.game();self.play(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},set(CHOICES))
        self.assertEqual(g.state.players[1].mana,8);self.assertFalse(g.state.players[2].hand)
        wire=json.dumps(g.for_player(2).observe(),ensure_ascii=False)
        self.assertNotIn(WRATH,wire);self.assertNotIn('战争古树',wire)
        self.portable(g)
    def test_b01_friendly_actual_wrath_forces_both_damage_and_draw_with_one_payment(self):
        g=self.game();self.play(g);self.pick(g,WRATH);friendly=self.copies(g,WRATH)[0]
        self.assertEqual(friendly.choose_branch.branch_id,'both');self.assertFalse(friendly.enchantments)
        target=g.state.players[2].board[0];result=self.play(g,WRATH,target,'both')
        self.assertEqual(sum(e.amount for e in result.events if e.kind=='damage_dealt'),4)
        self.assertEqual(g.state.entities[target].health,1);self.assertEqual(g.state.players[1].mana,6)
        self.assertEqual(sum(x.source_id==friendly.id for x in g.state.draw_history),1);self.portable(g)
    def test_b02_opponent_printed_wrath_keeps_ordinary_single_branch(self):
        g=self.game(board=(YETI,));self.play(g);self.pick(g,WRATH);peer=self.copies(g,WRATH,2)[0]
        self.assertIsNone(peer.choose_branch);self.assertFalse(peer.enchantments)
        g.apply(EndTurn(1));target=g.state.players[1].board[0]
        self.play(g,WRATH,target,'first');self.assertEqual(g.state.entities[target].health,2)
        self.assertEqual(sum(x.source_id==peer.id for x in g.state.draw_history),0);self.portable(g)
    def test_c00_minion_combined_and_peer_ordinary_branch_use_existing_bodies(self):
        g=self.game();self.play(g);self.pick(g,WAR);friendly=self.copies(g,WAR)[0]
        self.play(g,WAR,branch='both');current=g.state.entities[friendly.id]
        self.assertEqual((current.attack,current.health),(10,10));self.assertIn(Keyword.TAUNT,current.keywords)
        self.assertEqual(g.state.players[1].mana,1);g.apply(EndTurn(1))
        peer=self.copies(g,WAR,2)[0];self.play(g,WAR,branch='attack');current=g.state.entities[peer.id]
        self.assertEqual((current.attack,current.health),(10,5));self.assertNotIn(Keyword.TAUNT,current.keywords);self.portable(g)
    def test_c01_selection_allocates_two_independent_entities_without_rng_or_more_payment(self):
        g=self.game();self.play(g);before=g.snapshot()['rng_state'];self.pick(g,WRATH)
        own=self.copies(g,WRATH)[0];peer=self.copies(g,WRATH,2)[0]
        self.assertNotEqual(own.id,peer.id);self.assertEqual((own.controller,peer.controller),(1,2))
        self.assertEqual((own.base_cost,peer.base_cost),(2,2));self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertEqual(g.state.players[1].mana,8);self.portable(g)
    def test_c02_existing_same_name_cards_on_both_sides_are_untouched(self):
        g=self.game((ROOT,WRATH),enemy_hand=(WRATH,));old1=self.copies(g,WRATH)[0].id;old2=self.copies(g,WRATH,2)[0].id
        self.play(g);self.pick(g,WRATH)
        self.assertIsNone(g.state.entities[old1].choose_branch);self.assertIsNone(g.state.entities[old2].choose_branch)
        self.assertEqual(sum(e.choose_branch is not None for e in self.copies(g,WRATH)),1)
        self.assertTrue(all(e.choose_branch is None for e in self.copies(g,WRATH,2)));self.portable(g)
    def test_c03_current_copy_keeps_binding_and_base_copy_clears_it(self):
        g=self.game((ROOT,P+'copy',P+'base-copy'));self.play(g);self.pick(g,WRATH);target=self.copies(g,WRATH)[0].id
        self.play(g,P+'copy',target);self.play(g,P+'base-copy',target)
        copies=self.copies(g,WRATH);self.assertEqual(len(copies),3)
        self.assertEqual(copies[0].choose_branch,copies[1].choose_branch);self.assertIsNone(copies[2].choose_branch);self.portable(g)
    def test_d00_offer_restore_and_first_creation_binding_before_peer_delivery(self):
        g=self.game(mode='friendly');self.play(g);self.portable(g);self.pick(g,WRATH)
        own=self.copies(g,WRATH)[0];self.assertEqual(own.choose_branch.branch_id,'both')
        self.assertFalse(self.copies(g,WRATH,2));saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),saved);self.choose(g,'buff');self.choose(other,'buff')
        self.assertEqual(g.snapshot(),other.snapshot());own=self.copies(g,WRATH)[0];peer=self.copies(g,WRATH,2)[0]
        self.assertEqual(quote_cost(g.state,g.registry,own).amount,0)
        self.assertEqual(quote_cost(g.state,g.registry,peer).amount,2);self.assertIsNone(peer.choose_branch);self.portable(g)
    def test_d01_opponent_creation_wait_keeps_plain_copy_and_original_primary(self):
        g=self.game(mode='opponent');self.play(g);self.pick(g,WAR)
        self.assertEqual(self.copies(g,WAR)[0].choose_branch.branch_id,'both')
        self.assertIsNone(self.copies(g,WAR,2)[0].choose_branch);saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(other,'fail')
        self.assertEqual(other.snapshot(),saved);self.choose(g,'ok');self.choose(other,'ok')
        self.assertEqual(other.snapshot(),g.snapshot());self.assertEqual(len(self.copies(g,WAR,2)),1);self.portable(g)
    def test_e00_friendly_burn_still_gives_opponent_plain_original(self):
        g=self.game((ROOT,)+(TINY,)*9,mode='fill');self.play(g);self.pick(g,WRATH)
        own=self.copies(g,WRATH)[0];peer=self.copies(g,WRATH,2)[0]
        self.assertEqual(own.zone,Zone.GRAVEYARD);self.assertEqual(own.choose_branch.branch_id,'both')
        self.assertEqual(peer.zone,Zone.HAND);self.assertIsNone(peer.choose_branch);self.portable(g)
    def test_e01_opponent_full_hand_burns_only_plain_peer_card(self):
        g=self.game(enemy_hand=(TINY,)*10);self.play(g);self.pick(g,WRATH)
        own=self.copies(g,WRATH)[0];peer=self.copies(g,WRATH,2)[0]
        self.assertEqual(own.zone,Zone.HAND);self.assertEqual(own.choose_branch.branch_id,'both')
        self.assertEqual(peer.zone,Zone.GRAVEYARD);self.assertIsNone(peer.choose_branch);self.portable(g)
    def test_f00_unknown_eligible_choice_is_explicit_before_rng_and_transaction_commit(self):
        g=self.game(pool_mode='unknown');saved=g.snapshot()
        with self.assertRaises(ResolutionError)as caught:self.play(g)
        self.assertIn(P+'unknown',str(caught.exception));self.assertEqual(g.snapshot(),saved);self.portable(g)
    def test_f01_complete_empty_pool_has_no_pair_and_no_rng(self):
        g=self.game(pool_mode='empty');before=g.snapshot()['rng_state'];self.play(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertFalse(g.state.players[2].hand);self.assertEqual(g.state.players[1].mana,8);self.portable(g)
    def test_g00_countered_root_keeps_payment_without_discovery_or_pair(self):
        g=self.game(mode='counter');self.play(g);self.assertIsNone(g.state.pending_choice)
        self.assertFalse(g.state.players[2].hand);self.assertEqual(g.state.players[1].mana,8);self.portable(g)
    def test_g01_created_bound_spell_uses_both_on_existing_stored_automatic_cast(self):
        g=self.game((ROOT,P+'cast'));self.play(g);self.pick(g,WRATH);own=self.copies(g,WRATH)[0]
        self.play(g,P+'cast',own.id);self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,1)
        self.assertEqual(g.state.players[1].mana,8)
        cast=next(x for x in g.state.cast_history if x.card_id==WRATH)
        self.assertEqual(cast.branch_id,'both');self.assertEqual(sum(x.source_id==own.id for x in g.state.draw_history),1);self.portable(g)
    def test_h00_finite_request_rejects_mixed_recipes_and_non_choose_one_query(self):
        spec=DiscoverFromPool(1,POOL,PoolQuery(collectible=True,choose_one=True),source_id=1,paired_choose_one=True)
        for changes in ({'paired_choose_one':1},{'query':PoolQuery(collectible=True)},
                {'gift_copy_to_hand':True},{'discoveries':2},{'destination':'deck'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(spec,**changes)
    def test_h01_rehashed_bad_request_and_old_schema_are_rejected(self):
        g=self.game();self.play(g);saved=g.snapshot();bad=deepcopy(saved)
        def corrupt(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key=='paired_choose_one':value[key]='invalid'
                    else:corrupt(item)
            elif isinstance(value,list):
                for item in value:corrupt(item)
        corrupt(bad);bad['state_hash']=canonical_hash({k:v for k,v in bad.items()if k not in
            ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry('reader'))
        old=deepcopy(saved);old['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(old,registry('reader'))
        self.portable(g)


if __name__=='__main__':unittest.main()
