"""Actual Sidequest plays, Zombeast material limits and ordinary delivery."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.storm_gates_card import CARD,TEMPLATE,FIRST,SECOND,PARTS,load_batch
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,IllegalAction,Keyword,
    PlayCard,PlayerSetup,ResolutionError,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.crafted_faces import PREFIX,recipe_from_id
from hs_sim.engine.crafted_offers import CraftMinion,ResolveCraft
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import AddToHand,Destroy,InvokeBehavior,Summon
from hs_sim.engine.model import ChoicePurpose,TribeChangeSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference
from tools.card_batch import check_face

P='fixture.storm_gates.';UNIT=P+'unit';WATCH=P+'watch';ALL=P+'all'
BOAR='CS2_171';UNDEAD='CORE_EX1_012'
FIRST_PARTS=PARTS[:2];SECOND_PARTS=PARTS[2:]
CONTEXT=GenerationContext('explicit-zombeast-fixture','experimental')


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r=build_registry();meta=replace(r.card(UNDEAD).metadata,collectible=False,tribes=())
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,attack=1,health=30,metadata=meta))
    r.register_card(CardDefinition(ALL,ALL,CardType.MINION,attack=1,health=1,metadata=replace(meta,tribes=('all',))))
    def kill(c):
        i=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id.startswith(PREFIX))
        return(Destroy(i,c.source_id),)
    bodies={'summon':lambda c:(Summon(c.player_id,BOAR,c.source_id),),'kill':kill}
    for name,tribes in(('all_type',('all',)),('remove_type',())):
        def change(c,tribes=tribes):
            i=next(i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==BOAR)
            return(ChangeMinionTribes(CardReference.capture(c.state.entities[i]),TribeChangeSpec('set',tribes),c.source_id),)
        bodies[name]=change
    for name,body in bodies.items():
        r.register_behavior(P+name,body);r.register_card(CardDefinition(P+name,P+name,CardType.SPELL,on_play=P+name))
    first,second=FIRST_PARTS,SECOND_PARTS
    if mode=='same':first=second=(BOAR,)
    if mode in('unknown','high_unknown'):
        raw=r.pool_card(BOAR);r.register_pool_card(replace(raw,card_id=P+'unknown',cost=5 if mode=='unknown'else 6))
        first=(*first,P+'unknown');second=(*second,P+'unknown')
    if mode=='unreviewed':first=(*first,'CS2_169')
    if mode=='wrong_role':first=(*first,UNDEAD)
    if mode=='empty':second=()
    if mode!='missing':
        for pool,ids in((FIRST,first),(SECOND,second)):
            r.register_pool(PoolDefinition(pool,'explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,
                tuple(PoolMember(cid)for cid in ids),complete=not(mode=='incomplete'and pool==SECOND)))
    def fail(c):raise ResolutionError('Zombeast delivery fixture failure')
    r.register_behavior(P+'fail',fail)
    def watch(c):
        if c.event.kind=='craft_offer_accepted' and dict(c.event.data)['stage']==1 and mode=='overflow':
            return tuple(AddToHand(c.event.player_id,UNIT,c.source_id)for _ in range(10-len(c.state.players[c.event.player_id].hand)))
        if c.event.kind=='card_added_to_hand' and mode=='fail':
            target=c.state.entities.get(c.event.target_id)
            if target is not None and target.card_id.startswith(PREFIX):return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
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


class StormGatesTests(unittest.TestCase):
    def game(self,hand=None,mode='normal',active=1):
        hand=(CARD,BOAR,BOAR,BOAR)if hand is None else hand
        players=tuple(PlayerSetup('HERO_08',hand=hand if p==active else(BOAR,),deck=(UNIT,)*8,
            board=(WATCH,)if p==active and mode in('overflow','fail')else(),mana=10,max_mana=10)for p in(1,2))
        return Game.from_scenario(Scenario(players,active_player=active,seed=82,generation_context=CONTEXT),fixture(mode))
    def play(self,g,cid=CARD):
        p=g.state.active_player;i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,i));return i
    def progress(self,g,p=1):return g.state.entities[g.state.players[p].quests[0]].quest_progress.value
    def complete(self,g):
        self.play(g)
        for _ in range(3):self.play(g,BOAR)
    def offer(self,g):return g._frame.options[0].effects[0].offer
    def pick(self,g,cid=None):
        q=g.state.pending_choice
        option=next((o for o in g._frame.options if any(type(e)is ResolveCraft and e.card_id==cid for e in o.effects)),None)if cid else None
        g.apply(SelectChoice(q.player_id,q.id,((option or q.options[0]).id,)))
    def creations(self,g,p=1):return[g.state.entities[i]for i in g.state.players[p].hand if g.state.entities[i].card_id.startswith(PREFIX)]
    def portable(self,g,mode='normal',fresh=False):
        s=g.snapshot();r=fixture.__wrapped__(mode)if fresh else fixture(mode)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        return s

    def test_full_source_primary_faces_template_and_real_sidequest_metadata(self):
        data=load_batch();self.assertEqual(len(data['official_observations']),12)
        r=build_registry();c=r.card(CARD);t=r.card(TEMPLATE)
        self.assertEqual((c.cost,c.quest.kind,c.quest.stages[0].goal),(1,'sidequest',3))
        self.assertEqual(c.keywords,(Keyword.SIDEQUEST,));self.assertEqual(r.pool_card(CARD).keywords,(Keyword.SIDEQUEST,))
        self.assertEqual((t.cost,t.attack,t.health,t.metadata.tribes),(0,1,1,('beast','undead')))
        self.assertFalse(any(key[0]in(FIRST,SECOND)for key in r.pools))
        for bad in({'max_part_cost':True},{'max_part_cost':-1},{'discount_amount':True}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):replace(CraftMinion(1,TEMPLATE,FIRST,SECOND,1),**bad)

    def test_template_display_omission_requires_exact_full_row_both_slots_and_zero_face(self):
        data=load_batch();raw=data['dependencies'][0]['record'];decl={'{0}':'','{1}':''};numeric={'cost':0}
        for o in data['official_observations']:
            if o['card_id']!=TEMPLATE:continue
            check_face(raw,o['face'],o['locale'],decl,numeric_normalizations=numeric)
            for wrong in(None,{'{0}':''},{'{1}':''},{'{0}':'0','{1}':''}):
                with self.assertRaises(ValueError):check_face(raw,o['face'],o['locale'],wrong,numeric_normalizations=numeric)
            for key,value in(('id','other'),('text',raw['text']+' Extra rule.'),('health',2)):
                changed=deepcopy(raw);changed[key]=value
                with self.assertRaises(ValueError):check_face(changed,o['face'],o['locale'],decl,numeric_normalizations=numeric)
            for key,value in(('text','Draw a card.'),('manaCost',1),('health',2)):
                face=deepcopy(o['face']);face[key]=value
                with self.assertRaises(ValueError):check_face(raw,face,o['locale'],decl,numeric_normalizations=numeric)

    def test_undead_beast_and_dual_tribe_each_count_one_completed_play(self):
        g=self.game((CARD,BOAR,UNDEAD,'GIL_545'));self.play(g)
        for expected,cid in((1,BOAR),(2,UNDEAD)):
            self.play(g,cid);self.assertEqual(self.progress(g),expected)
        self.play(g,'GIL_545');self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.CRAFT)
        self.assertEqual(g.state.entities[g.state.players[1].quests[0]].quest_progress.value,3)

    def test_enemy_nontribal_and_summoned_beasts_do_not_advance_own_quest(self):
        g=self.game((CARD,UNIT,P+'summon',BOAR));self.play(g);self.play(g,UNIT);self.play(g,P+'summon')
        self.assertEqual(self.progress(g),0)
        g.apply(EndTurn(1));self.play(g,BOAR);g.apply(EndTurn(2));self.assertEqual(self.progress(g),0)
        self.play(g,BOAR);self.assertEqual(self.progress(g),1)

    def test_current_submitted_types_and_all_match_without_duplicate_race_credit(self):
        for change,want in(('remove_type',0),('all_type',1)):
            with self.subTest(change=change):
                g=self.game((CARD,P+change,BOAR));self.play(g);self.play(g,P+change);self.play(g,BOAR)
                self.assertEqual(self.progress(g),want)
        g=self.game((CARD,ALL));self.play(g);self.play(g,ALL);self.assertEqual(self.progress(g),1)

    def test_actual_reward_only_allocates_final_zombeast_and_native_battlecry_charge_work(self):
        g=self.game();n=len(g.state.entities);self.complete(g)
        self.assertEqual(len(g.state.entities),n);self.assertEqual(self.offer(g).discount,3)
        self.assertEqual(self.offer(g).spec.max_part_cost,5);self.assertIn('野兽',g.state.pending_choice.prompt)
        self.pick(g,'UNG_803');self.assertEqual(len(g.state.entities),n)
        self.assertEqual({o.preview.cost for o in g.state.pending_choice.options},{0,3})
        self.pick(g,BOAR);e=self.creations(g)[0]
        self.assertEqual((e.base_cost,e.base_attack,e.base_health),(2,3,2));self.assertEqual(e.components,('UNG_803',BOAR))
        self.assertEqual(quote_cost(g.state,g.registry,e).amount,0);self.assertFalse(g.state.players[1].quests)
        mana=g.state.players[1].mana;g.apply(PlayCard(1,e.id));self.assertEqual(g.state.players[1].mana,mana)
        self.assertEqual([g.state.entities[g.state.players[p].hero_id].health for p in(1,2)],[29,29])
        self.assertTrue(any(a.keyword==Keyword.CHARGE for a in g.state.entities[e.id].abilities));self.portable(g)

    def test_native_porcupine_deathrattle_uses_full_summed_attack_and_shared_damage(self):
        g=self.game((CARD,BOAR,BOAR,BOAR,P+'kill'));self.complete(g);self.pick(g,'BT_201');self.pick(g,'GIL_545')
        e=self.creations(g)[0];self.assertEqual((e.base_cost,e.base_attack,e.base_health),(8,5,8))
        self.assertEqual(quote_cost(g.state,g.registry,e).amount,5)
        g.apply(PlayCard(1,e.id));self.play(g,P+'kill')
        self.assertEqual(g.state.entities[e.id].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25)
        self.assertEqual(g.state.death_history[-1].entity_id,e.id)

    def test_each_part_cap_precedes_execution_lookup_and_discount_does_not_expand_budget(self):
        g=self.game(mode='high_unknown');self.complete(g)
        self.assertNotIn(P+'unknown',self.offer(g).candidates);self.pick(g,'BT_201')
        self.assertNotIn(P+'unknown',self.offer(g).candidates);self.pick(g,'GIL_545')
        e=self.creations(g)[0];self.assertEqual((e.base_cost,quote_cost(g.state,g.registry,e).amount),(8,5))

    def test_host_roles_can_overlap_without_duplicate_keyword_attachments(self):
        g=self.game(mode='same');self.complete(g);self.assertEqual(len(g.state.pending_choice.options),1)
        self.pick(g);self.assertEqual(len(g.state.pending_choice.options),1);self.pick(g)
        e=self.creations(g)[0];self.assertEqual(recipe_from_id(e.card_id).parts,(BOAR,BOAR))
        self.assertEqual((e.base_cost,e.base_attack,e.base_health),(2,2,2))
        self.assertEqual(sum(a.keyword==Keyword.CHARGE for a in e.abilities),1)

    def test_pool_failures_restore_third_physical_play_payment_progress_and_rng(self):
        for mode in('missing','incomplete','empty','unknown','unreviewed','wrong_role'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);self.play(g);self.play(g,BOAR);self.play(g,BOAR);before=g.snapshot()
                with self.assertRaises((ResolutionError,ValueError)):self.play(g,BOAR)
                self.assertEqual(g.snapshot(),before);self.assertEqual(self.progress(g),2)

    def test_both_reward_menus_restore_with_original_quest_finish_and_no_resampling(self):
        g=self.game();self.complete(g);self.assertTrue(g.state.entities[g.state.players[1].quests[0]].quest_progress.completing)
        self.portable(g,fresh=True);self.pick(g,'UNG_803');self.portable(g)
        self.pick(g,BOAR);self.assertFalse(g.state.players[1].quests);self.assertEqual(len(self.creations(g)),1);self.portable(g)

    def test_full_hand_during_reward_burns_only_final_creation_via_ordinary_delivery(self):
        g=self.game(mode='overflow');self.complete(g);self.assertEqual(len(g.state.players[1].hand),10)
        self.pick(g,'UNG_803');self.pick(g,BOAR);self.assertFalse(self.creations(g));self.assertFalse(g.state.players[1].quests)
        burns=[e for e in g.events if e.kind=='card_burned'];self.assertEqual(len(burns),1)
        self.assertTrue(g.state.entities[burns[0].target_id].card_id.startswith(PREFIX));self.portable(g,'overflow')

    def test_wrong_choice_and_native_delivery_failure_preserve_exact_second_menu(self):
        g=self.game(mode='fail');self.complete(g);self.pick(g,'UNG_803');before=g.snapshot();q=g.state.pending_choice
        for action in(SelectChoice(2,q.id,(q.options[0].id,)),SelectChoice(1,q.id,('unknown',))):
            with self.assertRaises(IllegalAction):g.apply(action)
            self.assertEqual(g.snapshot(),before)
        with self.assertRaises(ResolutionError):self.pick(g,BOAR)
        self.assertEqual(g.snapshot(),before);self.portable(g,'fail')

    def test_rehashed_new_part_cap_or_unconditional_discount_cannot_change_original_offer(self):
        g=self.game();self.complete(g);s=g.snapshot()
        for key,value in(('max_part_cost',6),('discount_amount',0)):
            bad=deepcopy(s);nodes=list(typed_nodes(bad['resolution_frame'],'CraftMinion'));self.assertTrue(nodes)
            for node in nodes:node[key]=value
            with self.subTest(key=key),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture())

    def test_second_actor_owns_quest_choices_cost_reduction_and_final_creation(self):
        g=self.game(active=2);self.complete(g);self.assertEqual(g.state.pending_choice.player_id,2)
        self.pick(g,'UNG_803');self.pick(g,BOAR);self.assertFalse(self.creations(g,1))
        e=self.creations(g,2)[0];self.assertEqual((e.owner,e.controller,quote_cost(g.state,g.registry,e).amount),(2,2,0))
        self.portable(g)

    def test_player_views_show_actual_choices_and_progress_without_private_crafting_material(self):
        g=self.game();self.complete(g)
        for p in(1,2):
            view=json.dumps(g.for_player(p).observe(),ensure_ascii=False)
            for private in('rng_before','rng_after','max_part_cost','before_hash','craft_offer_accepted'):
                self.assertNotIn(private,view)
        self.pick(g,'UNG_803');self.pick(g,BOAR);e=self.creations(g)[0]
        self.assertNotIn(e.card_id,json.dumps(g.for_player(2).observe(),ensure_ascii=False))


if __name__=='__main__':unittest.main()
