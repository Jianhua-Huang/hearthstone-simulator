"""Shard's original offers, attributed entry, ordered hand delivery and saved work."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import shard_original_remainders as native
from hs_sim.engine import (CardClass,CardDefinition,CardType,Game,PlayCard,PlayerSetup,ResolutionError,
    RewindSpec,Scenario,SnapshotError,TriggerSpec)
from hs_sim.engine.continuations import type_name
from hs_sim.engine.discovery_summons import DeliverUnselectedDiscoveryCard
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,Destroy,GainArmor,InvokeBehavior,ReplaceHero,RequestChoice)
from hs_sim.engine.model import CardMetadata,CostSpec,Keyword,Rarity,Zone
from hs_sim.engine.pools import DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION,canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P='k609.'
E1,E2,E3,E4,FOREIGN,PLAIN,NOOP,ENTRY,HAND,FAIL,AUTO,RETRY=(P+x for x in
    ('e1','e2','e3','e4','foreign','plain','noop','entry','hand','fail','auto','retry'))
ELEMENTALS=(E1,E2,E3,E4)
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=('elemental',),factions=(),subtypes=())


def context(mode='normal'):return GenerationContext(P+'explicit-complete-'+mode,'experimental')


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=build_registry();r.register_behavior(NOOP,lambda c:())
    r.register_behavior(P+'battlecry',lambda c:(GainArmor(c.player_id,9),))
    for i,cid in enumerate((*ELEMENTALS,FOREIGN,PLAIN)):
        meta=replace(META,classes=(CardClass.PALADIN,)if cid==FOREIGN else (CardClass.NEUTRAL,),
            tribes=()if cid==PLAIN else ('elemental',))
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=i+1,attack=2,health=10,
            battlecry=P+'battlecry',metadata=meta));r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_card(CardDefinition(NOOP,NOOP,CardType.SPELL,on_play=NOOP))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,native.CARD,c.source_id,choices='random'),))
    r.register_card(CardDefinition(AUTO,AUTO,CardType.SPELL,on_play=AUTO))
    r.register_card(CardDefinition(RETRY,RETRY,CardType.SPELL,cost=3,on_play=native.BODY,
        keywords=(Keyword.REWIND,),rewind=RewindSpec(1)))
    def fail(c):raise ResolutionError('K609 deliberate original remainder failure')
    r.register_behavior(P+'fault',fail)
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id);target=c.state.entities.get(e.target_id)
        if e.kind=='minion_summoned' and c.source.card_id==ENTRY and target is not None and target.card_id in ELEMENTALS:
            return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                ChoiceOption('kill','Destroy selected',(Destroy(target.id,c.source_id),)),
                ChoiceOption('class','Become Paladin',(ReplaceHero(c.player_id,'HERO_04'),)),
                ChoiceOption('fault','Fail',(InvokeBehavior(P+'fault',c.source_id,c.player_id),))),c.source_id),)
        if e.kind=='card_added_to_hand' and source is not None and source.card_id==native.CARD and target is not None and target.card_id in ELEMENTALS:
            root=next(x for x in reversed(c.state.discovery_summon_history)if x.spec.unselected_to_hand)
            if c.source.card_id==FAIL:return(InvokeBehavior(P+'fault',c.source_id,c.player_id),)
            acquired=sum(c.state.entities[i].card_id in ELEMENTALS for i in c.state.players[c.player_id].hand)
            if c.source.card_id==HAND and acquired==1:
                fills=tuple(AddToHand(c.player_id,NOOP,c.source_id)for _ in range(10-len(c.state.players[c.player_id].hand)))
                return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fill','Fill hand',fills),
                    ChoiceOption('terminal','End game',(Damage(c.state.players[3-c.player_id].hero_id,40,c.source_id),)),
                    ChoiceOption('fault','Fail',(InvokeBehavior(P+'fault',c.source_id,c.player_id),))),c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    for cid,event in((ENTRY,'minion_summoned'),(HAND,'card_added_to_hand'),(FAIL,'card_added_to_hand')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=20,
            triggers=(TriggerSpec(event,P+'watch'),)))
    members=list(ELEMENTALS if mode not in('empty','one','two')else ELEMENTALS[:{'empty':0,'one':1,'two':2}[mode]])
    if mode not in('empty','one','two'):members.extend((FOREIGN,PLAIN))
    if mode=='unknown':
        r.register_pool_card(PoolCard(P+'unknown',CardType.MINION,4,META));members.append(P+'unknown')
    r.register_pool(PoolDefinition(native.POOL,P+'whole-v1',context(mode).target_id,'experimental',
        tuple(PoolMember(cid)for cid in members),complete=True))
    r.validate();return r


class ShardOriginalRemainderTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'

    def game(self,hand=(native.CARD,),*,board=(),player=1,mode='normal'):
        self.mode=mode
        setups=tuple(PlayerSetup('HERO_08',hand=hand if p==player else (),board=board if p==player else (),
            deck=(NOOP,)*4,mana=20,max_mana=20,mana_cap=20)for p in(1,2))
        return Game.from_scenario(Scenario(setups,active_player=player,seed=609,generation_context=context(mode)),registry(mode))

    def start(self,g,player=1):
        mana=g.state.players[player].mana;source=self.play(g,native.CARD,player=player)
        self.assertEqual(g.state.players[player].mana,mana-3);self.assertEqual(g.state.cast_history[-1].card_id,native.CARD)
        return source

    def pick(self,g):
        choice=g.state.pending_choice;option=choice.options[0];self.choose(g,option.id);return option.card_id

    def root(self,g):return g.state.discovery_summon_history[-1]

    def reject(self,data):
        data['state_hash']=canonical_hash({k:v for k,v in data.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,registry(self.mode,'independent-reader'))

    def test_complete_original_face_primary_source_and_noncollectible_role(self):
        d=native.load_batch();row=d['cards'][0]
        for obs in d['official_observations']:batch.check_face(row['record'],obs['face'],obs['locale'])
        card=registry().card(native.CARD);self.assertEqual((card.cost,card.kind),(3,CardType.SPELL))
        self.assertFalse(card.metadata.collectible);self.assertEqual(native.COLLECTIBLE_ROOTS,())
        self.assertFalse(d['real_excavation_profile_bound']);self.assertNotIn('WW_009',registry().cards)

    def test_real_paid_original_elemental_offers_selected_summon_and_only_others_to_hand_both_seats(self):
        for p in(1,2):
            g=self.game(player=p);self.start(g,p);offered=tuple(o.card_id for o in g.state.pending_choice.options)
            self.assertEqual(len(offered),3);self.assertTrue(set(offered)<=set(ELEMENTALS))
            cid=self.pick(g);root=self.root(g);self.assertEqual(root.status,'completed')
            self.assertEqual([g.state.entities[i].card_id for i in g.state.players[p].board],[cid])
            self.assertEqual([g.state.entities[i].card_id for i in g.state.players[p].hand],[i for i in offered if i!=cid])
            self.assertEqual(tuple(f.card_id for f in root.remainder_created),tuple(i for i in offered if i!=cid))
            self.assertEqual(len([e for e in g.events if e.kind=='card_discovered']),1)
            self.assertEqual(g.state.entities[g.state.players[p].hero_id].armor,0)
            self.assertFalse(g.state.excavation_history)

    def test_unselected_cards_keep_printed_cost_and_can_run_real_battlecry_when_later_played(self):
        g=self.game();self.start(g);self.pick(g);cid=g.state.entities[g.state.players[1].hand[0]].card_id
        from hs_sim.engine.costs import quote_cost
        e=self.entity(g,cid);self.assertEqual(quote_cost(g.state,g.registry,e).amount,g.registry.card(cid).cost)
        self.play(g,cid);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,9);self.portable(g)

    def test_full_board_attempt_still_grants_original_others_and_live_full_hand_burns_second(self):
        g=self.game((native.CARD,)+(NOOP,)*9,board=(PLAIN,)*7);self.start(g);cid=self.pick(g);root=self.root(g)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual([f.zone for f in root.remainder_created],[Zone.HAND,Zone.GRAVEYARD])
        self.assertNotIn(cid,[f.card_id for f in root.remainder_created]);self.portable(g)

    def test_empty_domain_finishes_without_choice_or_rng(self):
        g=self.game(mode='empty');rng=g.snapshot()['rng_state'];self.start(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertEqual((self.root(g).status,self.root(g).remainder_created),('completed',()))

    def test_one_or_two_offered_cards_grant_only_actual_original_remainder(self):
        for mode,count in(('one',0),('two',1)):
            g=self.game(mode=mode);self.start(g);self.pick(g)
            self.assertEqual(len(self.root(g).remainder_created),count);self.assertEqual(len(g.state.players[1].hand),count)

    def test_unknown_eligible_elemental_rejects_before_offer_rng_payment_or_partial_history(self):
        g=self.game(mode='unknown');saved=g.snapshot()
        with self.assertRaisesRegex(ValueError,'unsupported card definition'):self.start(g)
        self.assertEqual(g.snapshot(),saved)

    def test_actual_original_offer_wait_restores_clone_replay_and_never_repays(self):
        g=self.game();self.start(g);other=self.portable(g);mana=g.state.players[1].mana
        option=g.state.pending_choice.options[0].id;self.choose(g,option);self.choose(other,option)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.players[1].mana,mana)

    def test_selected_entry_wait_precedes_any_unselected_creation_and_failed_branch_rolls_back(self):
        g=self.game(board=(ENTRY,));self.start(g);self.pick(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.root(g).remainder_created,())
        self.assertFalse(g.state.players[1].hand);other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K609 deliberate'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)

    def test_selected_body_death_during_entry_does_not_change_original_unselected_recipes(self):
        g=self.game(board=(ENTRY,));self.start(g);selected=self.pick(g)
        offered=self.root(g).offers[0].offered;self.choose(g,'kill')
        self.assertNotIn(selected,[g.state.entities[i].card_id for i in g.state.players[1].board])
        self.assertEqual(tuple(f.card_id for f in self.root(g).remainder_created),tuple(cid for cid in offered if cid!=selected))

    def test_class_change_after_selection_does_not_requery_or_replace_original_candidates(self):
        g=self.game(board=(ENTRY,));self.start(g);selected=self.pick(g);offered=self.root(g).offers[0].offered
        self.choose(g,'class');self.assertEqual(g.state.players[1].hero_class,CardClass.PALADIN)
        self.assertEqual(tuple(f.card_id for f in self.root(g).remainder_created),tuple(cid for cid in offered if cid!=selected))
        self.portable(g)

    def test_first_acquisition_wait_saves_next_original_card_and_current_capacity_can_change(self):
        g=self.game(board=(HAND,));self.start(g);self.pick(g);root=self.root(g)
        self.assertEqual(len(root.remainder_created),1);other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K609 deliberate'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'fill');self.choose(other,'fill')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.root(g).remainder_created[1].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand),10);self.portable(g)

    def test_acquisition_reaction_failure_restores_the_original_unselected_choice_and_rng(self):
        g=self.game(board=(FAIL,));self.start(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K609 deliberate'):self.pick(g)
        self.assertEqual(g.snapshot(),saved)

    def test_first_acquisition_terminal_keeps_actual_prefix_and_never_creates_second_card(self):
        g=self.game(board=(HAND,));self.start(g);self.pick(g)
        self.assertEqual(len(self.root(g).remainder_created),1);self.choose(g,'terminal')
        self.assertEqual(g.state.status,'finished');self.assertEqual(self.root(g).status,'interrupted')
        self.assertEqual(len(self.root(g).remainder_created),1);self.assertEqual(len(g.state.players[1].hand),1)
        self.portable(g)

    def test_real_retry_retires_original_creations_and_keeps_monotonic_new_producer_and_allocations(self):
        g=self.game((RETRY,));self.play(g,RETRY);self.pick(g);old=self.root(g)
        self.assertEqual(len(old.remainder_created),2);self.portable(g);self.choose(g,'retry')
        self.assertGreater(self.root(g).id,old.id);self.assertFalse(g.state.players[1].hand)
        self.pick(g);new=self.root(g);self.assertEqual(len(new.remainder_created),2)
        self.assertGreater(min(f.entity_id for f in new.remainder_created),max(f.entity_id for f in old.remainder_created))
        self.assertGreater(min(new.entry_root_ids),max(old.entry_root_ids));self.portable(g)

    def test_automatic_spell_keeps_true_cast_and_original_semantic_discovery(self):
        g=self.game((AUTO,));self.play(g,AUTO);self.assertIsNone(g.state.pending_choice)
        self.assertEqual((len(g.state.players[1].board),len(g.state.players[1].hand)),(1,2))
        self.assertEqual(self.root(g).spec.cause.origin,'spell_cast');self.portable(g)

    def test_unselected_policy_is_strict_finite_and_cannot_borrow_other_delivery_features(self):
        g=self.game();self.start(g);spec=self.root(g).spec
        invalid=({'unselected_to_hand':1},{'destination':'hand'},{'cause':None},{'source_id':None},
            {'count':2},{'discoveries':2},{'delivery':'after_all'},{'replacement':False},
            {'copy_selected_to_hand':True},{'summon_copies':2},{'freeze_summoned':True},
            {'cost':CostSpec(set_to=0)},{'query':replace(native.QUERY,class_mode='any')},
            {'query':replace(native.QUERY,tribes_any=('beast',))},{'shuffle_unselected_into_deck':True})
        for change in invalid:
            with self.subTest(change=change),self.assertRaises(ValueError):replace(spec,**change)
        self.assertFalse(replace(spec,unselected_to_hand=False).unselected_to_hand)

    def test_missing_reordered_duplicate_or_foreign_owed_remainder_control_cannot_restore(self):
        g=self.game(board=(HAND,));self.start(g);self.pick(g);saved=g.snapshot();kind=type_name(DeliverUnselectedDiscoveryCard)
        frame=saved['resolution_frame']['fields'];positions=[(key,i)for key in('prefix','continuation')for i,w in enumerate(frame[key]['tuple'])if isinstance(w,dict)and w.get('type')==kind]
        self.assertEqual(len(positions),1);key,index=positions[0]
        for mode in('remove','duplicate','wrong_index','foreign','bool'):
            d=deepcopy(saved);queue=d['resolution_frame']['fields'][key]['tuple'];work=queue[index]
            if mode=='remove':queue.pop(index)
            elif mode=='duplicate':queue.insert(index,deepcopy(work))
            else:work['fields']['index'if mode!='foreign'else'producer_id']=True if mode=='bool'else 0 if mode=='wrong_index'else 999
            self.reject(d)

    def test_rehashed_original_creation_prefix_and_allocation_edits_are_rejected(self):
        g=self.game(board=(HAND,));self.start(g);self.pick(g);saved=g.snapshot()
        for field,value in(('card_id',self.root(g).offers[0].result.selected[0].card_id),('owner',2),('next_entity_id',99999),('zone','board')):
            d=deepcopy(saved);d['state']['discovery_summon_history'][0]['remainder_created'][0][field]=value;self.reject(d)
        d=deepcopy(saved);d['state']['discovery_summon_history'][0]['remainder_created']=[];self.reject(d)

    def test_completed_producer_cannot_drop_creation_or_new_wire_fields(self):
        g=self.game();self.start(g);self.pick(g);saved=g.snapshot()
        for operation in('truncate','missing_allocations','missing_policy'):
            d=deepcopy(saved);root=d['state']['discovery_summon_history'][0]
            if operation=='truncate':root['remainder_created'].pop()
            elif operation=='missing_allocations':del root['remainder_created']
            else:del root['spec']['unselected_to_hand']
            self.reject(d)
        self.assertEqual(SNAPSHOT_SCHEMA_VERSION,610);old=deepcopy(saved);old['schema_version']=609;self.reject(old)

    def test_new_private_receipts_and_unselected_hidden_hand_never_escape_player_projection(self):
        g=self.game(board=(HAND,));self.start(g);self.pick(g)
        public=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))+json.dumps(g.for_player(2).legal_actions())
        for token in('remainder_created','DeliverUnselectedDiscoveryCard','discovery_summon_remainder_created','rng_before','original_offer','resolution_frame','state_hash'):
            self.assertNotIn('"'+token+'"',public)
        first=self.root(g).remainder_created[0].card_id;self.assertNotIn(first,public)

    def test_bad_original_face_rejected_before_partial_card_or_behavior_registration(self):
        d=deepcopy(native.load_batch());d['cards'][0]['record']['cost']=0
        r=batch.registration_prefix(build_registry,'hs_sim.cards.shard_original_remainders.register_shard_original_remainders',native.register_shard_original_remainders)
        before=(dict(r.cards),dict(r.pool_cards),dict(r._behaviors))
        with patch.object(native,'load_batch',return_value=d):
            with self.assertRaises(TargetValidationError):native.register_shard_original_remainders(r)
        self.assertEqual((r.cards,r.pool_cards,r._behaviors),before)


if __name__=='__main__':unittest.main()
