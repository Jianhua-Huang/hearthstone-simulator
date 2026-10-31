"""Actual Undead Dragon pieces through ordinary physical card life cycles."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.nefarian_crafted_faces import CARD,TEMPLATE,EXISTING,load_batch
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,IllegalAction,Keyword,PlayCard,
    PlayerSetup,ResolutionError,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.crafted_faces import (CraftedMinionBlueprint,CraftedMinionRecipe,PREFIX,recipe_from_id)
from hs_sim.engine.effects import (Buff,ChoiceOption,CopyMinion,Destroy,InvokeBehavior,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.zones import CardReference,CopyCard,DiscardCard
from hs_sim.engine.summon_sources import ResurrectMinion,Resurrect,DeathQuery
from hs_sim.engine.summon_quantities import SummonCause,SummonByCard,SummonEntryMaterial
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash

P='fixture.crafted.';UNIT=P+'unit';WATCH=P+'watch'
GHOUL=CraftedMinionRecipe(TEMPLATE,'TIME_045','CORE_OG_149').card_id
TWIN=CraftedMinionRecipe(TEMPLATE,'CORE_EX1_043','CORE_OG_149').card_id
BLOOD=CraftedMinionRecipe(TEMPLATE,'TIME_045','CORE_EX1_012').card_id


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r=build_registry();r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,attack=1,health=8))
    def fail(c):raise ResolutionError('Crafted native body fixture failure')
    r.register_behavior(P+'fail',fail)
    def resurrect(c):
        d=next(d for d in reversed(c.state.death_history)if d.card_id.startswith(PREFIX))
        return(ResurrectMinion(c.player_id,d.id,source_id=c.source_id,cause=SummonCause.capture(c)),)
    scripts={'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'buff':lambda c:(Buff(c.target_id,3,4,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),'bounce':lambda c:(ReturnToHand(c.target_id),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'base':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        'handcopy':lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,mode='base',source_id=c.source_id),),
        'discard':lambda c:(DiscardCard(CardReference.capture(c.state.entities[c.target_id]),c.source_id),),
        'named':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(GHOUL),),SummonCause.capture(c)),),
        'pool_resurrect':lambda c:(Resurrect(c.player_id,query=DeathQuery(cards=PoolQuery(tribes_any=('undead',))),
            source_id=c.source_id,cause=SummonCause.capture(c)),),
        'resurrect':resurrect}
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,))if name in('handcopy','discard')else None
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,
            requires_target=name not in('resurrect','pool_resurrect','named')and targeting is None,targeting=targeting,target_rule='any_entity'))
    def watch(c):
        target=c.state.entities.get(c.event.target_id)
        if target is None or target.card_id!=TWIN:return ()
        if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if mode!='wait':return ()
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',
            (InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(P+'watch',watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,
        triggers=(TriggerSpec('stats_changed',P+'watch'),)))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
    return s


class CraftedFacesTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),mode='normal',active=1):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand if active==1 else(),board=board,
            deck=(UNIT,)*10,max_mana=10,mana=10),PlayerSetup('HERO_08',hand=hand if active==2 else(),
            board=((WATCH,)if mode!='normal'else())+enemy,deck=(UNIT,)*10,max_mana=10,mana=10)),
            active_player=active,seed=91),fixture(mode))
    def play(self,g,card,target=None):
        p=g.state.active_player;cid=card if card.startswith(PREFIX)else P+card
        i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,i,target));return i
    def board(self,g,p=1):return[g.state.entities[i]for i in g.state.players[p].board]
    def check(self,g,mode='normal'):
        s=g.snapshot();self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),fixture(mode)).snapshot(),s)
        self.assertEqual(replay(build_replay(g),fixture(mode)).snapshot(),s)

    def test_complete_source_template_and_parts_preserve_separate_full_reference_pools(self):
        d=load_batch();self.assertEqual(len(d['official_observations']),12);self.assertEqual(len(d['existing_dependencies']),5)
        r=fixture();self.assertIsNotNone(r.card(CARD).battlecry)
        from hs_sim.cards.nefarian_crafting_card import DRAGONS,UNDEAD
        from hs_sim.cards.nefarian_community_pools import load_batch as references,SOURCE_TARGET
        source=references();pools=[p for p in r.pools.values()if p.id in(DRAGONS,UNDEAD)]
        self.assertEqual({p.id for p in pools},{DRAGONS,UNDEAD});self.assertEqual(len(pools),2)
        for role in source['roles']:
            pool=next(p for p in pools if p.id==role['pool_id'])
            self.assertEqual([(m.card_id,m.weight)for m in pool.members],
                [(m['card_id'],m['weight'])for m in role['members']])
            self.assertEqual(pool.excluded_card_ids,tuple(role['excluded_card_ids']))
            self.assertEqual((pool.version,pool.target_id,pool.mode),(source['policy_id'],SOURCE_TARGET,'experimental'))
            self.assertFalse(pool.complete)
        for row in d['cards']+d['existing_dependencies']:
            self.assertEqual(canonical_hash(row['record']),row['record_sha256'])
        self.assertEqual(r.card(TEMPLATE).attack,1);self.assertEqual(r.card(TEMPLATE).health,1)

    def test_pure_recipe_sums_printed_stats_and_keeps_both_native_origins_without_registration(self):
        r=fixture();fingerprint=r.fingerprint();ids=tuple(r.cards);n=len(r.cards)
        for _ in range(3):
            c=r.card(GHOUL);self.assertEqual((c.cost,c.attack,c.health),(6,4,7))
            self.assertEqual(c.metadata.tribes,('dragon','undead'));self.assertIn(GHOUL,r.cards)
            self.assertEqual(recipe_from_id(GHOUL).parts,('TIME_045','CORE_OG_149'))
        self.assertEqual((len(r.cards),tuple(r.cards),r.fingerprint()),(n,ids,fingerprint))

    def test_actual_poisonous_ghoul_battlecry_kills_other_minions_without_hitting_heroes(self):
        g=self.game(hand=(GHOUL,),board=(UNIT,),enemy=(UNIT,));i=self.play(g,GHOUL)
        self.assertEqual(g.state.players[1].mana,4);self.assertEqual(len(g.state.death_history),2)
        self.assertEqual([e.id for e in self.board(g)],[i]);self.assertFalse(self.board(g,2))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        self.assertEqual(g.state.entities[i].components,('TIME_045','CORE_OG_149'));self.check(g)

    def test_two_actual_battlecries_keep_order_donor_identity_one_payment_and_current_hand_value(self):
        g=self.game(hand=(TWIN,P+'kill',P+'buff'),enemy=(UNIT,));i=self.play(g,TWIN)
        e=g.state.entities[i];self.assertEqual((e.base_attack,e.base_health),(7,4));self.assertEqual(e.max_health,6)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,7);self.assertEqual(g.state.players[1].mana,3)
        captures=[d.payload.card_id for d in g.state.battlecry_history]
        self.assertEqual(captures,['CORE_EX1_043','CORE_OG_149']);self.check(g)

    def test_silence_removes_donated_text_but_preserves_printed_summed_body(self):
        g=self.game(hand=(GHOUL,P+'silence'));i=self.play(g,GHOUL);self.play(g,'silence',i)
        e=g.state.entities[i];self.assertEqual((e.attack,e.max_health),(4,7));self.assertFalse(e.abilities)
        self.assertEqual(e.components,('TIME_045','CORE_OG_149'));self.check(g)

    def test_current_and_base_copy_keep_recipe_with_distinct_physical_attachments(self):
        g=self.game(hand=(GHOUL,P+'buff',P+'copy',P+'base'));i=self.play(g,GHOUL)
        self.play(g,'buff',i);self.play(g,'copy',i);self.play(g,'base',i)
        bodies=self.board(g);self.assertEqual([(e.attack,e.max_health)for e in bodies],[(7,11),(7,11),(4,7)])
        self.assertTrue(all(e.card_id==GHOUL for e in bodies));self.assertEqual(len({a.id for e in bodies for a in e.abilities}),sum(len(e.abilities)for e in bodies));self.check(g)

    def test_bounce_and_replay_do_not_double_add_component_stats_or_change_base_cost(self):
        g=self.game(hand=(GHOUL,P+'buff',P+'bounce'));i=self.play(g,GHOUL);self.play(g,'buff',i);self.play(g,'bounce',i)
        e=g.state.entities[i];self.assertEqual((e.base_attack,e.base_health,e.base_cost),(4,7,6))
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,GHOUL)
        self.assertEqual((g.state.entities[i].attack,g.state.entities[i].max_health),(4,7));self.check(g)

    def test_reborn_uses_recipe_full_native_text_with_one_health_and_no_battlecry_replay(self):
        g=self.game(hand=(GHOUL,P+'kill'));old=self.play(g,GHOUL);self.play(g,'kill',old)
        e=self.board(g)[0];self.assertNotEqual(e.id,old);self.assertEqual(e.card_id,GHOUL)
        self.assertEqual((e.base_attack,e.base_health,e.health),(4,7,1));self.assertNotIn(Keyword.REBORN,e.keywords)
        self.assertIn(Keyword.POISONOUS,e.keywords);self.assertEqual(len(g.state.battlecry_history),1);self.check(g)

    def test_donated_spell_damage_deathrattle_and_reborn_reuse_shared_death_order(self):
        g=self.game(hand=(BLOOD,P+'kill'));i=self.play(g,BLOOD);before=len(g.state.players[1].deck)
        self.play(g,'kill',i);self.assertEqual(len(g.state.players[1].deck),before-1)
        e=self.board(g)[0];self.assertEqual((e.base_attack,e.base_health,e.health),(2,5,1))
        self.assertTrue(any(a.kind=='spell_damage'and a.spell_damage==1 for a in e.abilities));self.check(g)

    def test_typed_resurrection_preserves_printed_recipe_and_does_not_replay_battlecries(self):
        g=self.game(hand=(TWIN,P+'kill',P+'resurrect'));old=self.play(g,TWIN);self.play(g,'kill',old)
        self.play(g,'resurrect');e=self.board(g)[0]
        self.assertNotEqual(e.id,old);self.assertEqual((e.base_attack,e.base_health,e.max_health),(7,4,4))
        self.assertEqual(e.components,('CORE_EX1_043','CORE_OG_149'));self.assertEqual(len(g.state.battlecry_history),2);self.check(g)

    def test_actual_undead_death_query_keeps_crafted_candidate_and_typed_original_material(self):
        g=self.game(hand=(TWIN,P+'kill',P+'pool_resurrect'));i=self.play(g,TWIN);self.play(g,'kill',i)
        self.play(g,'pool_resurrect');e=self.board(g)[0]
        self.assertEqual(e.card_id,TWIN);self.assertEqual((e.base_attack,e.base_health),(7,4))
        self.assertEqual(e.components,('CORE_EX1_043','CORE_OG_149'));self.check(g)

    def test_typed_named_entry_infers_complete_recipe_and_never_replays_battlecry(self):
        g=self.game(hand=(P+'named',),enemy=(UNIT,));self.play(g,'named');e=self.board(g)[0]
        self.assertEqual(e.card_id,GHOUL);self.assertEqual((e.base_attack,e.base_health),(4,7))
        self.assertEqual(e.components,('TIME_045','CORE_OG_149'));self.assertEqual(self.board(g,2)[0].health,8)
        self.assertFalse(g.state.battlecry_history);self.check(g)

    def test_hand_base_copy_and_actual_discard_keep_exact_original_recipe(self):
        g=self.game(hand=(GHOUL,P+'handcopy',P+'discard'));old=g.state.players[1].hand[0]
        self.play(g,'handcopy',old)
        cards=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==GHOUL]
        self.assertEqual(len(cards),2);self.assertTrue(all(e.components==('TIME_045','CORE_OG_149')for e in cards))
        self.play(g,'discard',old);self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.discard_history[-1].components,('TIME_045','CORE_OG_149'));self.check(g)

    def test_native_first_battlecry_wait_restores_remaining_body_and_failed_resume(self):
        g=self.game(hand=(TWIN,P+'kill'),enemy=(UNIT,),mode='wait');i=self.play(g,TWIN)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.players[1].mana,3)
        self.check(g,'wait');q=g.state.pending_choice;s=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(q.player_id,q.id,('bad',)))
        self.assertEqual(g.snapshot(),s);g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(len(g.state.battlecry_history),2);self.check(g,'wait')

    def test_failed_native_reaction_rolls_back_payment_body_and_all_donated_state(self):
        g=self.game(hand=(TWIN,P+'kill'),mode='fail');s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,TWIN)
        self.assertEqual(g.snapshot(),s);self.check(g,'fail')

    def test_rehashed_component_reordering_or_base_stat_corruption_reject(self):
        g=self.game(hand=(GHOUL,));i=g.state.players[1].hand[0];s=g.snapshot()
        for key,value in [('components',['CORE_OG_149','TIME_045']),('base_attack',5)]:
            bad=deepcopy(s);bad['state']['entities'][str(i)][key]=value
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture())

    def test_private_hand_recipe_and_public_crafted_body_are_not_starships(self):
        g=self.game(hand=(GHOUL,));own=json.dumps(g.for_player(1).observe());enemy=json.dumps(g.for_player(2).observe())
        self.assertIn('crafted',own);self.assertNotIn(GHOUL,enemy);self.assertNotIn('CORE_OG_149',enemy)
        self.play(g,GHOUL)
        for p in(1,2):
            dto=g.for_player(p).observe()['observation'];encoded=json.dumps(dto)
            self.assertIn('CORE_OG_149',encoded)
            found=[]
            def visit(v):
                if isinstance(v,dict):
                    if v.get('card_id')==GHOUL:found.append(v)
                    for x in v.values():visit(x)
                elif isinstance(v,list):
                    for x in v:visit(x)
            visit(dto);self.assertTrue(found);self.assertTrue(all('starship'not in v for v in found))

    def test_canonical_recipe_rejects_changed_version_role_unknown_and_recursive_parts(self):
        r=fixture()
        for cid in(GHOUL+'=',PREFIX+'bad',CraftedMinionRecipe(TEMPLATE,'CORE_OG_149','TIME_045').card_id,
                CraftedMinionRecipe(TEMPLATE,'unimplemented','CORE_OG_149').card_id):
            with self.assertRaises(ValueError):r.card(cid)
        with self.assertRaises(ValueError):CraftedMinionRecipe(TEMPLATE,GHOUL,'CORE_OG_149').card_id
        with self.assertRaises(ValueError):CraftedMinionRecipe(TEMPLATE,TEMPLATE,'CORE_OG_149').card_id

    def test_unreviewed_ingredient_errors_without_mutating_registry_or_authorizing_a_pool(self):
        r=fixture.__wrapped__();meta=replace(r.card('TIME_045').metadata,deck_identity=P+'dormant')
        r.register_card(CardDefinition(P+'dormant','Dormant ingredient',CardType.MINION,health=4,metadata=meta,dormant_turns=1))
        before=(len(r.cards),r.fingerprint());cid=CraftedMinionRecipe(TEMPLATE,P+'dormant','CORE_OG_149').card_id
        with self.assertRaisesRegex(ValueError,'dormant_turns'):r.register_crafted_minion_part(P+'dormant')
        with self.assertRaisesRegex(ValueError,'reviewed native donation'):r.card(cid)
        self.assertEqual((len(r.cards),r.fingerprint()),before)

    def test_existing_executable_minion_is_not_automatically_a_reviewed_donation_adapter(self):
        r=fixture();self.assertIn('CORE_DRG_226',r.cards)
        cid=CraftedMinionRecipe(TEMPLATE,'CORE_DRG_226','CORE_OG_149').card_id
        with self.assertRaisesRegex(ValueError,'reviewed native donation'):r.card(cid)
        self.assertNotIn('CORE_DRG_226',r.crafted_minion_parts)

    def test_catalog_keeps_mapping_semantics_and_static_namespace_cannot_spoof_a_recipe(self):
        r=fixture.__wrapped__();self.assertNotIn(None,r.cards);self.assertIsNone(r.cards.get(None))
        with self.assertRaises(KeyError):r.cards[None]
        with self.assertRaises(TypeError):r.cards[[]]
        with self.assertRaises(ValueError):r.register_card(CardDefinition(GHOUL,'Spoof',CardType.MINION,health=1))


if __name__=='__main__':unittest.main()
