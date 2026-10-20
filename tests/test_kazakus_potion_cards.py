"""Actual Aya Potion dependencies; a recipe is one ordinary physical spell."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
from itertools import combinations
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.kazakus_potion_cards import TEMPLATE,DEMON,PARTS,load_batch
from hs_sim.cards.shadow_of_demise_card import CARD as SHADOW
from hs_sim.engine import (CardDefinition,CardType,Game,IllegalAction,PlayCard,PlayerSetup,Scenario,
    ResolutionError,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.composed_spells import (ComposedSpellRecipe,CreateRandomComposedSpell,
    ResolveComposedSpell,recipe_from_id,CREATED,STEP,END)
from hs_sim.engine.effects import ChoiceOption,Damage,Destroy,InvokeBehavior,RequestChoice,ReturnToHand
from hs_sim.engine.model import CardClass,CardMetadata,Rarity
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell,CastStoredSpell
from hs_sim.engine.zones import CardReference,CopyCard
from tools.card_batch import check_face

P='fixture.potion.';UNIT=P+'unit';WATCH=P+'watch';GEN=P+'generate';BODY=P+'demon'
CTX=GenerationContext('actual-aya-potion-dependency-experiment','experimental')


def potion(*indices):return ComposedSpellRecipe(TEMPLATE,*(PARTS[i]for i in sorted(indices))).card_id


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r=build_registry()
    for cid,health in((UNIT,8),(WATCH,20),(BODY,5)):
        meta=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=('demon',)if cid==BODY else())
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=health,metadata=meta,
            spell_damage=2 if mode=='spellpower'and cid==UNIT else 0))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    def fail(c):raise ResolutionError('Potion observer fixture failed')
    r.register_behavior(P+'fail',fail)
    def watch(c):
        if mode=='bounce'and c.event.kind=='stats_changed'and c.state.entities[c.event.target_id].card_id==UNIT:
            later=[i for i in c.state.players[c.player_id].board if i>c.event.target_id and c.state.entities[i].card_id==UNIT]
            return(ReturnToHand(later[-1]),)if later else()
        if c.event.kind!='minion_summoned'or c.state.entities[c.event.target_id].card_id!=DEMON:return ()
        if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if mode!='wait':return ()
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',
            (InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(P+'watch',watch)
    r.register_card(replace(r.card(WATCH),id=P+'observer',triggers=tuple(TriggerSpec(k,P+'watch')for k in('minion_summoned','stats_changed'))))
    scripts={'generate':lambda c:(CreateRandomComposedSpell(c.player_id,TEMPLATE,c.source_id),),
        'wound':lambda c:(Damage(c.state.players[3-c.player_id].hero_id,27,c.source_id),),
        'copy':lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,source_id=c.source_id),),
        'base':lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,mode='base',source_id=c.source_id),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'auto':lambda c:(CastSpell(c.player_id,potion(3,4),c.source_id),),
        'stored':lambda c:(CastStoredSpell(CardReference.capture(c.state.entities[c.target_id]),c.player_id,c.source_id),)}
    for key,body in scripts.items():
        r.register_behavior(P+key,body)
        targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.SPELL,),relation='friendly')if key in('copy','base','stored')else None
        r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,targeting=targeting,
            requires_target=key=='kill'))
    unknown=P+'unknown'
    if mode=='unknown':r.register_pool_card(PoolCard.from_definition(CardDefinition(unknown,unknown,
        CardType.MINION,health=2,metadata=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=('demon',)))))
    r.register_pool(PoolDefinition('constructed.minions','potion-fixture-v1',CTX.target_id,CTX.mode,
        ()if mode=='empty'else(PoolMember(unknown if mode=='unknown'else BODY),),complete=True))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
    return s


class KazakusPotionTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),deck=(),mode='normal',active=1,mana=10):
        return Game.from_scenario(Scenario(tuple(PlayerSetup('HERO_08',hand=hand if p==active else(),
            board=((P+'observer',)if mode in('wait','fail','bounce')else())+board if p==active else enemy,
            deck=deck if p==active else(),max_mana=mana,mana=mana)for p in(1,2)),active_player=active,
            generation_context=CTX,seed=308),fixture(mode))
    def eid(self,g,cid):return next(i for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.eid(g,cid);g.apply(PlayCard(g.state.active_player,eid,target));return eid
    def armor(self,g):return g.state.entities[g.state.players[g.state.active_player].hero_id].armor
    def portable(self,g,mode='normal'):
        s=json.loads(json.dumps(g.snapshot()));r=fixture.__wrapped__(mode)
        self.assertEqual(Game.from_snapshot(s,r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),fixture.__wrapped__(mode)).snapshot(),s)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def test_full_actual_source_and_choice_only_parts_keep_original_dependency_scope(self):
        d=load_batch();r=fixture()
        self.assertEqual(len(d['official_observations']),26)
        self.assertTrue(all(r.card(c).choice_only for c in PARTS))
        self.assertFalse(d['root_implemented']);self.assertNotIn('CFM_621',r.cards)
        self.assertEqual((r.card(DEMON).attack,r.card(DEMON).health),(2,2))

    def test_36_real_distinct_recipes_have_canonical_identity_and_only_fire_needs_target(self):
        r=fixture();before=(len(r.cards),r.fingerprint())
        for a,b in combinations(range(9),2):
            cid=potion(a,b);card=r.card(cid)
            self.assertEqual(recipe_from_id(cid).parts,(PARTS[a],PARTS[b]))
            self.assertEqual((card.cost,card.manual_playable,card.spell_school),(1,True,None))
            self.assertEqual(card.targeting is not None,3 in(a,b))
        self.assertEqual((len(r.cards),r.fingerprint()),before)

    def test_unknown_reversed_duplicate_recursive_and_noncanonical_recipes_reject(self):
        r=fixture()
        for cid in(ComposedSpellRecipe(TEMPLATE,PARTS[4],PARTS[0]).card_id,
                   ComposedSpellRecipe(TEMPLATE,PARTS[0],'missing.potion').card_id,potion(0,1)+'='):
            with self.subTest(cid=cid),self.assertRaises(ValueError):r.card(cid)
        with self.assertRaises(ValueError):ComposedSpellRecipe(TEMPLATE,PARTS[0],PARTS[0])
        with self.assertRaises(ValueError):ComposedSpellRecipe(TEMPLATE,PARTS[0],potion(1,2))

    def test_one_payment_and_one_cast_directed_damage_then_armor_both_players(self):
        cid=potion(3,4)
        for active in(1,2):
            g=self.game((cid,),active=active);target=g.state.players[3-active].hero_id
            self.play(g,cid,target)
            self.assertEqual(g.state.entities[target].health,27);self.assertEqual(self.armor(g),4)
            self.assertEqual(g.state.players[active].mana,9)
            self.assertEqual((len(g.state.play_history),len(g.state.cast_history)),(1,1))
            self.portable(g)

    def test_aoe_deaths_complete_before_resurrection_and_one_original_cast(self):
        cid=potion(0,2);g=self.game((cid,),board=(DEMON,),enemy=(DEMON,))
        old=tuple(i for p in(1,2)for i in g.state.players[p].board)
        self.play(g,cid)
        self.assertEqual(len(g.state.death_history),2)
        self.assertEqual(len(g.state.players[1].board),1);self.assertEqual(g.state.players[2].board,[])
        self.assertNotIn(g.state.players[1].board[0],old)
        self.assertEqual(len(g.state.cast_history),1);self.portable(g)

    def test_summoned_demon_exists_when_later_component_buffs_current_board(self):
        cid=potion(1,5);g=self.game((cid,),board=(UNIT,));self.play(g,cid)
        board=[g.state.entities[i]for i in g.state.players[1].board]
        self.assertEqual([e.health for e in board],[10,4])
        self.assertEqual([e.attack for e in board],[1,2])

    def test_freeze_random_enemy_and_draw_use_ordinary_actual_spell_context(self):
        cid=potion(6,7);g=self.game((cid,),enemy=(UNIT,UNIT),deck=(UNIT,))
        self.play(g,cid)
        self.assertEqual(sum(g.state.entities[i].frozen for i in g.state.players[2].board),1)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[UNIT])
        self.portable(g)

    def test_full_demon_host_query_then_empty_freeze_is_not_another_cast(self):
        cid=potion(6,8);g=self.game((cid,));self.play(g,cid)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[BODY])
        self.assertEqual(len(g.state.cast_history),1);self.portable(g)

    def test_empty_resurrection_and_empty_draw_keep_other_real_component(self):
        cid=potion(2,7);g=self.game((cid,));self.play(g,cid)
        self.assertEqual(g.state.players[1].board,[])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,29)

    def test_random_creation_proves_complete_roster_and_keeps_recipe_after_restore_replay(self):
        g=self.game((GEN,));self.play(g,GEN)
        cid=g.state.entities[g.state.players[1].hand[0]].card_id
        proof=json.loads(dict(next(e for e in g.events if e.kind==CREATED).data)['proof'])
        self.assertEqual(proof['candidates'],list(PARTS));self.assertEqual(len(set(proof['drawn'])),2)
        self.assertEqual(proof['recipe_id'],cid);self.portable(g)

    def test_full_hand_creation_burns_actual_recipe_without_omitting_random_draw(self):
        # An ordinary zero-cost automatic source can get a Potion with ten held cards.
        r=fixture.__wrapped__();r.register_behavior(P+'overflow',lambda c:(CreateRandomComposedSpell(c.player_id,TEMPLATE,c.source_id),))
        r.register_card(CardDefinition(P+'overflow','Overflow',CardType.MINION,health=2,
            triggers=(TriggerSpec('turn_started',P+'overflow'),)))
        from hs_sim.engine import EndTurn
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(potion(1,4),)*10,board=(P+'overflow',)),
            PlayerSetup('HERO_08',deck=(UNIT,))),active_player=2,generation_context=CTX,seed=308),r)
        g.apply(EndTurn(2))
        proof=next(e for e in g.events if e.kind==CREATED)
        self.assertEqual(g.state.entities[proof.target_id].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand),10)

    def test_actual_shadow_of_demise_copies_whole_potion_and_both_components(self):
        cid=potion(1,4);g=self.game((SHADOW,cid));shadow=self.eid(g,SHADOW)
        self.play(g,cid)
        self.assertEqual(g.state.entities[shadow].card_id,cid)
        g.apply(PlayCard(1,shadow))
        self.assertEqual(self.armor(g),8);self.assertEqual(len(g.state.players[1].board),2)
        self.assertEqual(len(g.state.cast_history),2);self.portable(g)

    def test_current_and_printed_hand_copy_keep_both_original_ingredients(self):
        cid=potion(1,4)
        for mode in('copy','base'):
            g=self.game((P+mode,cid));original=self.eid(g,cid);self.play(g,P+mode,original)
            self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[cid,cid])
            self.portable(g)

    def test_automatic_and_stored_cast_use_single_potion_body_without_extra_payment(self):
        g=self.game((P+'auto',));self.play(g,P+'auto');self.assertEqual(self.armor(g),4)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(len(g.state.cast_history),2);self.portable(g)
        cid=potion(1,4);g=self.game((P+'stored',cid));self.play(g,P+'stored',self.eid(g,cid))
        self.assertEqual(self.armor(g),4);self.assertEqual(g.state.players[1].mana,10);self.portable(g)

    def test_waiting_first_component_resumes_second_from_new_state_independent_registry(self):
        cid=potion(1,5);g=self.game((cid,),mode='wait');self.play(g,cid)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g,'wait')
        self.assertEqual(g.state.entities[g.state.players[1].board[-1]].health,2)
        self.choose(g)
        self.assertEqual(g.state.entities[g.state.players[1].board[-1]].health,4);self.portable(g,'wait')

    def test_failed_choice_and_observer_rollback_preserve_recipe_and_original_cursor(self):
        cid=potion(1,5);g=self.game((cid,),mode='wait');self.play(g,cid);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g)
        g=self.game((cid,),mode='fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,cid)
        self.assertEqual(g.snapshot(),before)

    def test_waiting_next_component_cannot_be_removed_advanced_or_duplicated(self):
        cid=potion(1,5);g=self.game((cid,),mode='wait');self.play(g,cid)
        saved=g.snapshot()
        def edit(value,mode):
            if isinstance(value,list):
                for i,item in enumerate(value):
                    if isinstance(item,dict)and item.get('type')=='hs_sim.engine.composed_spells.ResolveComposedSpell':
                        if mode=='remove':value.pop(i)
                        elif mode=='duplicate':value.insert(i,deepcopy(item))
                        else:item['fields']['index']=2
                        return True
                    if edit(item,mode):return True
            elif isinstance(value,dict):
                for item in value.values():
                    if edit(item,mode):return True
            return False
        for mode in('remove','advance','duplicate'):
            changed=deepcopy(saved);self.assertTrue(edit(changed,mode))
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(changed),fixture('wait'))

    def test_cropped_finished_component_or_random_draw_proof_rejects_after_rehash(self):
        cid=potion(1,4);g=self.game((cid,));self.play(g,cid);saved=g.snapshot()
        for kind in(STEP,END):
            changed=deepcopy(saved);changed['events']=[e for e in changed['events']if e['kind']!=kind]
            with self.subTest(kind=kind),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(changed),fixture())
        g=self.game((GEN,));self.play(g,GEN);s=g.snapshot()
        event=next(e for e in s['events']if e['kind']==CREATED)
        # Change the full accepted random pair, retaining the ordinary snapshot hashes.
        data=dict(event['data']);proof=json.loads(data['proof']);proof['drawn']=[PARTS[0],PARTS[0]]
        data['proof']=json.dumps(proof,sort_keys=True,separators=(',',':'));event['data']=data
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(s),fixture())

    def test_visible_recipe_and_hidden_opponent_hand_and_private_random_proof(self):
        cid=potion(1,4);g=self.game((cid,));own=g.observe(1);enemy=g.observe(2)
        mine=next(p for p in own['players']if p['id']==1)['hand'][0]
        hidden=next(p for p in enemy['players']if p['id']==1)['hand'][0]
        self.assertEqual(mine['spell_recipe'],{'template_card_id':TEMPLATE,'parts':[PARTS[1],PARTS[4]]})
        self.assertNotIn('spell_recipe',hidden);self.assertNotIn(cid,json.dumps(enemy))
        g=self.game((GEN,));self.play(g,GEN)
        public=json.dumps(g.observe(2));self.assertNotIn('rng_before',public);self.assertNotIn(CREATED,public)

    def test_uninitialized_template_is_never_silently_a_playable_blank(self):
        g=self.game((TEMPLATE,));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,TEMPLATE)
        self.assertEqual(g.snapshot(),before)

    def test_real_spell_damage_applies_to_each_damage_component_in_one_cast(self):
        cid=potion(0,3);g=self.game((cid,),board=(UNIT,),enemy=(UNIT,),mode='spellpower')
        self.play(g,cid,g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25)
        self.assertEqual([g.state.entities[g.state.players[p].board[0]].health for p in(1,2)],[4,4])
        self.assertEqual(len(g.state.cast_history),1)

    def test_lethal_first_component_interrupts_later_armor_and_remains_portable(self):
        cid=potion(3,4);g=self.game((P+'wound',cid));self.play(g,P+'wound')
        self.play(g,cid,g.state.players[2].hero_id)
        self.assertEqual(self.armor(g),0);self.assertEqual(g.state.winner,1)
        self.assertTrue(g.state.cast_history[-1].interrupted);self.portable(g)

    def test_full_board_summon_fails_normally_then_armor_still_executes(self):
        cid=potion(1,4);g=self.game((cid,),board=(UNIT,)*7);self.play(g,cid)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(self.armor(g),4)

    def test_health_component_does_not_modify_captured_minion_after_it_returns_to_hand(self):
        cid=potion(4,5);g=self.game((cid,),board=(UNIT,UNIT),mode='bounce');self.play(g,cid)
        self.assertEqual(self.armor(g),4)
        held=[g.state.entities[i]for i in g.state.players[1].hand]
        self.assertEqual([(e.card_id,e.health)for e in held],[(UNIT,8)])
        self.assertEqual(g.state.entities[g.state.players[1].board[-1]].health,10)
        self.portable(g,'bounce')

    def test_unknown_eligible_demon_is_not_pruned_and_empty_pool_retains_armor(self):
        cid=potion(4,8);g=self.game((cid,),mode='empty');self.play(g,cid)
        self.assertEqual(self.armor(g),4);self.assertEqual(g.state.players[1].hand,[])
        g=self.game((cid,),mode='unknown');s=g.snapshot()
        with self.assertRaises(ValueError):self.play(g,cid)
        self.assertEqual(g.snapshot(),s)

    def test_primary_empty_potion_template_requires_exact_two_native_placeholders(self):
        d=load_batch();row=d['dependencies'][0]['record'];decl={'{0}':'','{1}':''}
        for item in d['official_observations']:
            if item['card_id']!=TEMPLATE:continue
            check_face(row,item['face'],item['locale'],decl)
            for bad in({'{0}':''},{'{1}':''},{'{0}':'0','{1}':''}):
                with self.assertRaises(ValueError):check_face(row,item['face'],item['locale'],bad)
            raw=deepcopy(row);raw['text_en']+=' Deal 3 damage.';raw['text']+='造成3点伤害。'
            with self.assertRaises(ValueError):check_face(raw,item['face'],item['locale'],decl)


if __name__=='__main__':unittest.main()
