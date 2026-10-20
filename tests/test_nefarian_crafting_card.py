"""Actual Victor source with explicit experimental curated inventories, not M0 pools."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.nefarian_crafting_card import CARD,TEMPLATE,DRAGONS,UNDEAD
from hs_sim.cards.nefarian_crafted_faces import load_batch
from hs_sim.engine import (CardDefinition,CardType,Game,IllegalAction,PlayCard,PlayerSetup,
    ResolutionError,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.crafted_faces import PREFIX,recipe_from_id
from hs_sim.engine.crafted_offers import CraftMinion,ResolveCraft,candidates,validate_offer
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import AddToHand,ChoiceOption,Destroy,InvokeBehavior,RequestChoice
from hs_sim.engine.model import BattlecryRepeatSpec,ChoicePurpose
from hs_sim.engine.model import TribeChangeSpec
from hs_sim.engine.pool_offers import ChooseFromPools,PoolOfferGroup
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,DiscardCard
from hs_sim.engine.tribes import ChangeMinionTribes

P='fixture.nefarian.';UNIT=P+'unit';WATCH=P+'watch';REPEAT=P+'repeat'
FIRST=('TIME_045','CORE_EX1_043');SECOND=('CORE_OG_149','CORE_EX1_012')
CONTEXT=GenerationContext('explicit-nefarian-fixture','experimental')


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r=build_registry();meta=replace(r.card('CORE_EX1_012').metadata,collectible=False,tribes=())
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,attack=1,health=30,metadata=meta))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=30,metadata=meta,
        battlecry_repeats=(BattlecryRepeatSpec(2,(CardType.MINION,)),)))
    for operation,tribes in(('all',('all',)),('remove',())):
        def change(c,tribes=tribes):
            i=next(i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==FIRST[0])
            return(ChangeMinionTribes(CardReference.capture(c.state.entities[i]),TribeChangeSpec('set',tribes),c.source_id),)
        r.register_behavior(P+operation,change)
        r.register_card(CardDefinition(P+operation,P+operation,CardType.SPELL,on_play=P+operation))
    first=FIRST;second=SECOND
    if mode=='high':
        # A high-cost real Dragon exercises the printed budget. This explicit
        # fixture capability/pool is not a claim about Victor's official pool.
        r.register_crafted_minion_part('CORE_UNG_848');first=(*FIRST,'CORE_UNG_848')
    if mode=='small':first=FIRST[:1];second=SECOND[1:]
    if mode=='empty':first=()
    if mode in('unknown','expensive_unknown'):
        raw=r.pool_card(SECOND[0]);r.register_pool_card(replace(raw,card_id=P+'unknown',cost=3 if mode=='unknown'else 99))
        second=(*second,P+'unknown')
    if mode=='unreviewed':first=(*first,'CORE_DRG_226')
    if mode=='wrong_role':first=(*first,SECOND[0])
    if mode!='missing':
        for pool,ids in((DRAGONS,first),(UNDEAD,second)):
            r.register_pool(PoolDefinition(pool,'explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,
                tuple(PoolMember(cid,2 if cid==FIRST[0]else 1)for cid in ids),complete=not(mode=='incomplete'and pool==DRAGONS)))
    def fail(c):raise ResolutionError('Actual creation delivery fixture failure')
    r.register_behavior(P+'fail',fail)
    def watch(c):
        event=c.event
        if event.kind=='card_added_to_hand' and mode=='fail':
            target=c.state.entities.get(event.target_id)
            if target is not None and target.card_id.startswith(PREFIX):return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if event.kind!='craft_offer_accepted' or dict(event.data).get('stage')!=1:return ()
        if mode in('add_dragon','overflow'):return(AddToHand(event.player_id,FIRST[0]if mode=='add_dragon'else UNIT,c.source_id),)
        if mode=='remove_dragon':
            i=next(i for i in c.state.players[event.player_id].hand if c.state.entities[i].card_id==FIRST[0])
            return(DiscardCard(CardReference.capture(c.state.entities[i]),c.source_id),)
        if mode=='kill_source':return(Destroy(event.source_id,c.source_id),)
        if mode=='intervene':return(ChooseFromPools(event.player_id,(PoolOfferGroup(DRAGONS),),c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=meta,
        triggers=(TriggerSpec('craft_offer_accepted',P+'watch'),TriggerSpec('card_added_to_hand',P+'watch'))))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
    return s


def typed_nodes(value,name):
    if isinstance(value,dict):
        if value.get('type','').endswith('.'+name):yield value['fields']
        for child in value.values():yield from typed_nodes(child,name)
    elif isinstance(value,list):
        for child in value:yield from typed_nodes(child,name)


class NefarianCraftingTests(unittest.TestCase):
    def game(self,hand=(CARD,),mode='normal',active=1,repeat=False):
        actors=[]
        for p in(1,2):
            actors.append(PlayerSetup('HERO_08',hand=hand if p==active else(),deck=(UNIT,)*10,
                board=((WATCH,)if p!=active and mode in('add_dragon','remove_dragon','kill_source','intervene','overflow','fail')else())+
                    ((REPEAT,)if p==active and repeat else()),max_mana=10,mana=10))
        return Game.from_scenario(Scenario(tuple(actors),active_player=active,seed=133,generation_context=CONTEXT),fixture(mode))
    def play(self,g):
        p=g.state.active_player;i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==CARD)
        g.apply(PlayCard(p,i));return i
    def offer(self,g):return g._frame.options[0].effects[0].offer
    def pick(self,g,cid=None):
        choice=g.state.pending_choice
        option=next((o for o in g._frame.options if any(type(e)is ResolveCraft and e.card_id==cid for e in o.effects)),None)if cid else None
        g.apply(SelectChoice(choice.player_id,choice.id,((option or choice.options[0]).id,)))
    def creations(self,g,p=1):return[g.state.entities[i]for i in g.state.players[p].hand if g.state.entities[i].card_id.startswith(PREFIX)]
    def portable(self,g,mode='normal',fresh=False):
        s=g.snapshot();r=fixture.__wrapped__(mode)if fresh else fixture(mode)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        return s

    def test_complete_pinned_source_and_root_definition_do_not_invent_formal_pools(self):
        raw=load_batch()['cards'][0]['record'];r=build_registry();c=r.card(CARD)
        self.assertEqual((c.cost,c.attack,c.health),(raw['cost'],raw['attack'],raw['health']));self.assertEqual(c.metadata.runes.unholy,1)
        self.assertFalse(any(key[0]in(DRAGONS,UNDEAD)for key in r.pools))
        for bad in({'source_id':None},{'max_total_cost':0},{'discount_amount':True}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):replace(CraftMinion(1,TEMPLATE,DRAGONS,UNDEAD,1),**bad)

    def test_actual_four_mana_source_two_choices_only_final_creation_is_allocated(self):
        g=self.game();n=len(g.state.entities);source=self.play(g)
        self.assertEqual(g.state.players[1].mana,6);self.assertEqual(len(g.state.entities),n)
        self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.CRAFT);self.assertEqual(self.offer(g).stage,1)
        self.pick(g,FIRST[0]);self.assertEqual(len(g.state.entities),n);self.assertEqual(self.offer(g).stage,2)
        self.pick(g,SECOND[0]);e=self.creations(g)[0]
        self.assertEqual((e.base_attack,e.base_health,e.base_cost),(4,7,6));self.assertEqual(e.components,(FIRST[0],SECOND[0]))
        self.assertEqual(quote_cost(g.state,g.registry,e).amount,6);self.assertEqual(g.state.players[1].board,[source]);self.portable(g)

    def test_actual_creation_can_be_played_with_original_poisonous_ghoul_body(self):
        g=self.game();self.play(g);self.pick(g,FIRST[0]);self.pick(g,SECOND[0]);e=self.creations(g)[0]
        g.apply(PlayCard(1,e.id));self.assertEqual(g.state.entities[next(i for i in g.state.players[1].board)].id,e.id)
        self.assertEqual(g.state.players[1].mana,0);self.assertEqual(g.state.battlecry_history[-1].payload.card_id,SECOND[0]);self.portable(g)

    def test_held_dragon_discount_changes_current_cost_not_recipe_printed_cost(self):
        g=self.game(hand=(CARD,FIRST[0]));self.play(g);self.assertEqual(self.offer(g).discount,3)
        self.pick(g,FIRST[0]);self.assertEqual({o.preview.cost for o in g.state.pending_choice.options},{2,3})
        self.pick(g,SECOND[0]);e=self.creations(g)[0]
        self.assertEqual((g.registry.card(e.card_id).cost,e.base_cost,quote_cost(g.state,g.registry,e).amount),(6,6,3));self.portable(g)

    def test_discount_is_frozen_before_two_choices_and_creation_cannot_discount_itself(self):
        for mode,held,wanted in(('add_dragon',False,0),('remove_dragon',True,3)):
            with self.subTest(mode=mode):
                g=self.game(hand=(CARD,FIRST[0])if held else(CARD,),mode=mode);self.play(g)
                self.assertEqual(self.offer(g).discount,wanted);self.pick(g,FIRST[0]);self.pick(g,SECOND[0]);e=self.creations(g)[0]
                self.assertEqual(quote_cost(g.state,g.registry,e).amount,6-wanted);self.portable(g,mode)

    def test_held_condition_uses_current_tribes_including_all_and_removed_dragon(self):
        for operation,wanted in(('all',3),('remove',0)):
            with self.subTest(operation=operation):
                g=self.game(hand=(CARD,FIRST[0],P+operation))
                i=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==P+operation)
                g.apply(PlayCard(1,i));self.play(g);self.assertEqual(self.offer(g).discount,wanted)
                self.pick(g,FIRST[0]);self.pick(g,SECOND[0]);self.portable(g)

    def test_printed_ten_mana_budget_restricts_second_pool_even_with_discount(self):
        g=self.game(hand=(CARD,FIRST[0]),mode='high');self.play(g);self.pick(g,'CORE_UNG_848')
        offer=self.offer(g);self.assertEqual(offer.candidates,(SECOND[1],));self.assertEqual(len(g.state.pending_choice.options),1)
        self.assertEqual(g.state.pending_choice.options[0].preview.cost,7);self.pick(g,SECOND[1]);e=self.creations(g)[0]
        self.assertEqual(g.registry.card(e.card_id).cost,10);self.assertEqual(quote_cost(g.state,g.registry,e).amount,7);self.portable(g,'high')

    def test_repeated_battlecry_has_independent_acceptance_and_second_sees_first_creation(self):
        g=self.game(repeat=True);self.play(g);self.assertEqual(self.offer(g).discount,0)
        self.pick(g,FIRST[0]);self.pick(g,SECOND[0]);self.assertEqual(self.offer(g).discount,3)
        self.pick(g,FIRST[0]);self.pick(g,SECOND[0]);cards=self.creations(g)
        self.assertEqual([quote_cost(g.state,g.registry,e).amount for e in cards],[6,3]);self.assertEqual(g.state.players[1].mana,6)
        self.assertEqual([dict(e.data)['stage']for e in g.events if e.kind=='craft_offer_accepted'],[1,2,1,2]);self.portable(g)

    def test_each_actual_wait_restores_with_independent_registry_and_replays_without_resampling(self):
        g=self.game();self.play(g);self.portable(g,fresh=True);self.pick(g,FIRST[1]);self.portable(g,fresh=True)
        before=g.snapshot()['rng_state'];self.pick(g,SECOND[1]);self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)

    def test_source_death_after_acceptance_keeps_original_player_and_source(self):
        g=self.game(mode='kill_source',active=2);source=self.play(g);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.pick(g,FIRST[0]);self.pick(g,SECOND[0]);self.assertEqual(len(self.creations(g,2)),1);self.assertFalse(self.creations(g,1));self.portable(g,'kill_source')

    def test_unrelated_choice_and_rng_between_stages_preserve_original_receipts(self):
        g=self.game(mode='intervene');self.play(g);self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.EFFECT)
        self.portable(g,'intervene');self.pick(g);first=self.offer(g);self.assertEqual(first.stage,1);self.assertEqual(first.discount,0)
        self.pick(g,FIRST[0]);second=self.offer(g);self.assertNotEqual(second.rng_before,first.rng_after)
        self.assertEqual(second.discount,0);self.portable(g,'intervene');self.pick(g,SECOND[0]);self.portable(g,'intervene')

    def test_rehashed_intervening_choice_cannot_lose_queued_craft_request(self):
        g=self.game(mode='intervene');self.play(g);saved=g.snapshot()
        self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.EFFECT)
        def remove(value):
            if isinstance(value,dict):
                if 'tuple'in value:
                    value['tuple'][:]=[x for x in value['tuple']if not(isinstance(x,dict)and x.get('type','').endswith('.RequestChoice')and
                        x.get('fields',{}).get('purpose',{}).get('value')=='craft')]
                for child in value.values():remove(child)
            elif isinstance(value,list):
                for child in value:remove(child)
        bad=deepcopy(saved);remove(bad)
        self.assertNotEqual(saved,bad)
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('intervene'))

    def test_complete_small_pool_offers_available_distinct_options_and_still_waits(self):
        g=self.game(mode='small');self.play(g);self.assertEqual(len(g.state.pending_choice.options),1)
        self.pick(g);self.assertEqual(len(g.state.pending_choice.options),1);self.pick(g);self.assertEqual(len(self.creations(g)),1);self.portable(g,'small')

    def test_missing_incomplete_empty_unknown_and_unreviewed_pools_fail_before_sampling(self):
        for mode in('missing','incomplete','empty','unknown','unreviewed','wrong_role'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);before=g.snapshot()
                with self.assertRaises((ResolutionError,ValueError)):self.play(g)
                self.assertEqual(g.snapshot(),before)

    def test_ineligible_expensive_unknown_is_not_misreported_as_an_executable_dependency(self):
        g=self.game(mode='expensive_unknown');self.play(g);self.pick(g,FIRST[0]);self.assertNotIn(P+'unknown',self.offer(g).candidates)
        self.pick(g,SECOND[0]);self.assertEqual(len(self.creations(g)),1)

    def test_hand_filled_during_choices_burns_final_creation_via_ordinary_overflow(self):
        g=self.game(hand=(CARD,)+(UNIT,)*9,mode='overflow');self.play(g);self.assertEqual(len(g.state.players[1].hand),10)
        self.pick(g,FIRST[0]);self.pick(g,SECOND[0]);self.assertFalse(self.creations(g))
        burns=[e for e in g.events if e.kind=='card_burned'];self.assertEqual(len(burns),1)
        self.assertTrue(g.state.entities[burns[0].target_id].card_id.startswith(PREFIX));self.portable(g,'overflow')

    def test_wrong_actor_unknown_option_and_delivery_failure_roll_back_exact_waiting_state(self):
        g=self.game(mode='fail');self.play(g);self.pick(g,FIRST[0]);before=g.snapshot();choice=g.state.pending_choice
        for action in(SelectChoice(2,choice.id,(choice.options[0].id,)),SelectChoice(1,choice.id,('unknown',))):
            with self.assertRaises(IllegalAction):g.apply(action)
            self.assertEqual(g.snapshot(),before)
        with self.assertRaises(ResolutionError):self.pick(g,SECOND[0])
        self.assertEqual(g.snapshot(),before);self.portable(g,'fail')

    def test_receipts_reject_rewritten_candidates_rng_discount_and_first_selection(self):
        g=self.game();self.play(g);first=self.offer(g)
        for change in({'candidates':first.candidates[:1]},{'offered':tuple(reversed(first.offered))},
                {'rng_after':first.rng_before},{'discount':3}):
            with self.subTest(change=change),self.assertRaises(ValueError):validate_offer(g.registry,CONTEXT,replace(first,**change),g.events)
        self.pick(g,FIRST[0]);second=self.offer(g)
        with self.assertRaises(ValueError):replace(second.first_result,selected_ids=('unknown',))
        other=next(o.id for o in second.first_result.choice.options if o.id not in second.first_result.selected_ids)
        for change in({'first_card_id':FIRST[1]},{'first_result':replace(second.first_result,selected_ids=(other,))}):
            with self.subTest(change=change),self.assertRaises(ValueError):validate_offer(g.registry,CONTEXT,replace(second,**change),g.events)

    def test_rehashed_snapshots_cannot_substitute_receipt_before_state_or_crop_branches(self):
        g=self.game();self.play(g);saved=g.snapshot()
        for stage in(1,2):
            if stage==2:self.pick(g,FIRST[0]);saved=g.snapshot()
            for kind in('discount','before','purpose','crop'):
                with self.subTest(stage=stage,kind=kind):
                    bad=deepcopy(saved)
                    if kind in('discount','before'):
                        nodes=list(typed_nodes(bad,'CraftOffer'));self.assertTrue(nodes)
                        for node in nodes:
                            if kind=='discount':node['discount']=3
                            else:node['before']['state']['players']['1']['mana']-=1
                    elif kind=='purpose':bad['state']['pending_choice']['purpose']='effect'
                    else:
                        for node in typed_nodes(bad,'ChoiceOption'):node['effects']={'tuple':[]}
                    with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture())

    def test_player_projection_exposes_only_offered_previews_and_own_final_recipe(self):
        g=self.game();self.play(g)
        for step in(1,2):
            for p in(1,2):
                view=json.dumps(g.for_player(p).observe())
                for hidden in('before_hash','rng_before','rng_after','craft_offer_accepted','candidates','first_result_hash'):
                    self.assertNotIn(hidden,view)
            if step==1:self.pick(g,FIRST[0])
        self.pick(g,SECOND[0]);self.assertIn('crafted',json.dumps(g.for_player(1).observe()))
        self.assertNotIn(self.creations(g)[0].card_id,json.dumps(g.for_player(2).observe()));self.portable(g)

    def test_player_commands_use_existing_choice_refs_for_both_stages(self):
        g=self.game();self.play(g)
        for _ in range(2):
            api=g.for_player(1);listing=api.legal_actions();action=next(a for a in listing['actions']if a['type']=='select_choice')
            self.assertTrue(api.submit({'revision':listing['revision'],'action':action})['accepted'])
        self.assertEqual(len(self.creations(g)),1);self.portable(g)


if __name__=='__main__':unittest.main()
