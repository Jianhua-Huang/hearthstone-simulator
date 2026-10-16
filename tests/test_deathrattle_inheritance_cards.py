"""Real Archdruid inheritance, including retained native growth/draw/discard material."""
from dataclasses import asdict,replace
import json,unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.deathrattle_inheritance_cards import THORNS,load_batch
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (CardClass,CardDefinition,CardType,EndTurn,Game,Keyword,
    PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Destroy,InvokeBehavior,
    RequestChoice,ReturnToHand,Silence,Summon,TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.deathrattle_inheritance import GainDeathrattlesFromDeathsThisTurn
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import canonical_digest

P='k105.test.';YETI='CORE_CS2_182';LOOT='CORE_EX1_096';EGG='CATA_210';WHELP='CATA_210t';PLAT='TLC_603';HOARDER='CATA_897';GRANT='CATA_134t2';TREANT='CATA_134t3'


def registry(mode=None):
    r=build_registry()
    bodies=dict(kill=lambda c:(Destroy(c.target_id,c.source_id),),silence=lambda c:(Silence(c.target_id),),
        bounce=lambda c:(ReturnToHand(c.target_id,to_owner=True),),steal=lambda c:(ChangeControl(c.target_id,3-c.state.entities[c.target_id].controller),),
        copy=lambda c:(CopyMinion(c.target_id,c.player_id),),base_copy=lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        held_copy=lambda c:(CopyCard(MinionReference.capture(c.state.entities[c.target_id]),c.player_id,mode='current',source_id=c.source_id),),
        trigger=lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),summon=lambda c:(Summon(c.player_id,THORNS),),
        gain_for_original=lambda c:(GainDeathrattlesFromDeathsThisTurn(c.player_id,MinionReference.capture(c.state.entities[c.target_id])),))
    for name,body in bodies.items():
        r.register_behavior(P+name,body);kwargs={}if name=='summon'else dict(targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)))
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,**kwargs))
    # A representative prohibition carrier, not a claim of another real card.
    r.register_card(CardDefinition(P+'suppressor','Deathrattle prohibition fixture',CardType.MINION,health=8,keywords=(Keyword.DEATHRATTLE_SUPPRESSOR,)))
    r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('K105 deliberate pending failure')))
    if mode:
        def eligible(c):
            e=c.state.entities.get(c.event.target_id)
            return e is not None and e.card_id==THORNS
        def watch(c):
            if mode=='kill_entry':return(Destroy(c.event.target_id,c.source_id),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(P+'watch',watch);r.register_trigger_condition(P+'recipient',eligible)
        r.register_card(CardDefinition(P+'watch','Actual grant/entry reaction',CardType.MINION,health=8,
            limited_triggers=(LimitedTriggerSpec('minion_summoned'if mode=='kill_entry'else'ability_granted',P+'watch',condition_id=P+'recipient'),)))
    r.validate();return r


class DeathrattleInheritanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),mode=None,deck=(YETI,)*8):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=100,max_mana=100,mana_cap=100),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=100,max_mana=100,mana_cap=100)),seed=105),registry(mode)if mode else self.r)
    def first(self,g,cid,p=1,zone='board'):
        return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None,p=1):
        entity=self.first(g,cid,p,'hand');g.apply(PlayCard(p,entity.id,target,len(g.state.players[p].board)if entity.kind==CardType.MINION else None));return entity.id
    def abilities(self,g,eid):return tuple(a for a in g.state.entities[eid].abilities if a.kind=='deathrattle')
    def board(self,g,p=1):return[g.state.entities[i]for i in g.state.players[p].board]
    def kill(self,g,eid):self.play(g,P+'kill',eid)
    def portable(self,g):
        snapshot=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(snapshot,registry(self.mode));self.assertEqual(other.snapshot(),snapshot);self.assertEqual(g.clone().snapshot(),snapshot);self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),snapshot)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('deathrattle_inherited_from','deathrattle_memory','deathrattle_history','rng_state','resolution_frame','behavior_id'):self.assertNotIn('"'+key+'"',public)
        return other
    def seeded(self,extra=(),board=(LOOT,),mode=None):
        g=self.game((P+'kill',THORNS,*extra),board,mode=mode);self.kill(g,self.first(g,LOOT).id);return g,self.play(g,THORNS)

    def test_complete_original_warlock_face_and_existing_dependencies(self):
        d=load_batch();row,=d['cards'];raw=row['record'];c=self.r.card(THORNS)
        self.assertEqual((c.cost,c.attack,c.health),(2,3,2));self.assertEqual(c.metadata,replace(metadata_from_record(raw),deck_identity=THORNS));self.assertEqual(c.metadata.classes,(CardClass.WARLOCK,));self.assertEqual(c.metadata.tribes,());self.assertIsNone(c.deathrattle);self.assertIsNotNone(c.battlecry);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])
        self.assertEqual(len(d['official_observations']['observations']),2)
        for x in d['cards']+d['existing_dependencies']:
            self.assertEqual(canonical_digest(x['record']),x['record_sha256'])
            if 'definition_sha256'in x:self.assertEqual(canonical_digest(asdict(self.r.card(x['record']['id']))),x['definition_sha256'])

    def test_only_one_complete_definition_added(self):
        with patch('hs_sim.cards.deathrattle_inheritance_cards.register_deathrattle_inheritance_cards',lambda r:None):old=build_registry()
        current=build_registry();self.assertEqual(set(current.cards)-set(old.cards),{THORNS});self.assertTrue(all(asdict(old.card(cid))==asdict(current.card(cid))for cid in old.cards))

    def test_no_deaths_gives_no_deathrattle_and_normal_cost(self):
        g=self.game((THORNS,));target=self.play(g,THORNS);self.assertFalse(self.abilities(g,target));self.assertEqual(g.state.players[1].mana,98);self.portable(g)

    def test_duplicate_physical_deaths_are_not_deduplicated(self):
        g=self.game((P+'kill',P+'kill',P+'kill',THORNS),(LOOT,LOOT));deaths=[e.id for e in self.board(g)]
        for eid in deaths:self.kill(g,eid)
        target=self.play(g,THORNS);abilities=self.abilities(g,target);self.assertEqual(len(abilities),2);self.assertEqual([a.deathrattle_inherited_from[0]for a in abilities],[1,2]);self.assertEqual(len({a.id for a in abilities}),2)
        count=len(g.state.draw_history);self.kill(g,target);self.assertEqual(len(g.state.draw_history),count+2);self.portable(g)

    def test_friendly_means_controller_at_death_not_original_owner(self):
        g=self.game((P+'steal',P+'kill',THORNS),enemy=(LOOT,));victim=self.first(g,LOOT,2).id;self.play(g,P+'steal',victim);self.kill(g,victim);target=self.play(g,THORNS);self.assertEqual(len(self.abilities(g,target)),1);self.assertEqual((g.state.death_history[0].owner,g.state.death_history[0].controller),(2,1));self.portable(g)
        g=self.game((P+'steal',P+'kill',THORNS),(LOOT,));victim=self.first(g,LOOT).id;self.play(g,P+'steal',victim);self.kill(g,victim);target=self.play(g,THORNS);self.assertFalse(self.abilities(g,target))

    def test_previous_global_turn_is_excluded(self):
        g=self.game((P+'kill',THORNS),(LOOT,));self.kill(g,self.first(g,LOOT).id);g.apply(EndTurn(1));g.apply(EndTurn(2));target=self.play(g,THORNS);self.assertFalse(self.abilities(g,target));self.portable(g)

    def test_inheritance_query_player_is_explicit_not_receiver_controller(self):
        g=self.game((P+'kill',P+'gain_for_original'),(LOOT,),enemy=(THORNS,));self.kill(g,self.first(g,LOOT).id);target=self.first(g,THORNS,2).id;self.play(g,P+'gain_for_original',target)
        self.assertEqual(g.state.entities[target].controller,2);self.assertEqual(len(self.abilities(g,target)),1);self.assertEqual(g.state.death_history[0].controller,1);self.portable(g)

    def test_silenced_death_and_non_death_removal_have_no_declaration(self):
        for op in('silence','bounce'):
            with self.subTest(op=op):
                g=self.game((P+op,P+'kill',THORNS),(LOOT,));victim=self.first(g,LOOT).id;self.play(g,P+op,victim)
                if op=='silence':self.kill(g,victim)
                target=self.play(g,THORNS);self.assertFalse(self.abilities(g,target))

    def test_real_granted_treant_deathrattle_survives_original_carrier_reset(self):
        g=self.game((GRANT,P+'kill',THORNS,P+'kill'),(YETI,));victim=self.first(g,YETI).id;grant=self.play(g,GRANT);self.kill(g,victim);target=self.play(g,THORNS);a,=self.abilities(g,target);original=g.state.death_history[0].abilities
        old=next(x for x in original if x.kind=='deathrattle');self.assertEqual(old.source_id,grant);self.assertEqual(old.deathrattle_grant_card_id,GRANT);self.assertEqual(a.deathrattle_inherited_from,(1,old.id));self.assertEqual((a.source_id,a.deathrattle_grant_card_id),(target,THORNS));self.assertNotEqual(a.id,old.id)
        before=len([e for e in self.board(g)if e.card_id==TREANT]);self.kill(g,target);self.assertEqual(len([e for e in self.board(g)if e.card_id==TREANT]),before+1);self.portable(g)

    def test_two_same_grants_on_one_dead_body_remain_two_payloads(self):
        g=self.game((GRANT,GRANT,P+'kill',THORNS),(YETI,));victim=self.first(g,YETI).id;self.play(g,GRANT);self.play(g,GRANT);self.kill(g,victim);target=self.play(g,THORNS);self.assertEqual(len(self.abilities(g,target)),2);self.assertEqual(len({a.deathrattle_inherited_from for a in self.abilities(g,target)}),2)

    def test_grown_egg_retains_frozen_stats_and_not_its_growth_trigger(self):
        g=self.game((P+'kill',THORNS,P+'kill'),(EGG,));g.apply(EndTurn(1));g.apply(EndTurn(2));egg=self.first(g,EGG);memory=next(a.deathrattle_memory for a in egg.abilities if a.deathrattle_memory is not None);self.assertGreater(memory.growth_steps,0);self.kill(g,egg.id);target=self.play(g,THORNS);a,=self.abilities(g,target);self.assertEqual(a.deathrattle_memory,memory);self.assertEqual(a.deathrattle_card_id,EGG);self.assertFalse(any(x.kind=='trigger'for x in g.state.entities[target].abilities));self.portable(g)
        before={e.id for e in self.board(g)};self.kill(g,target);fresh=[e for e in self.board(g)if e.id not in before];self.assertEqual([(e.card_id,e.attack,e.health)for e in fresh],[(WHELP,memory.spec.attack+memory.growth_steps,memory.spec.health+memory.growth_steps)]);self.portable(g)

    def test_prohibition_does_not_filter_retained_physical_draw_memory(self):
        g=self.game((PLAT,P+'kill',THORNS,P+'silence',P+'kill'),(P+'suppressor',));plat=self.play(g,PLAT);memory=self.abilities(g,plat)[0].deathrattle_memory;self.assertEqual(len(memory.draws),1);drawn=memory.draws[0].entity_id;self.kill(g,plat);self.assertTrue(g.state.death_history[0].deathrattles_blocked);self.assertIn(drawn,g.state.players[1].hand)
        target=self.play(g,THORNS);self.assertEqual(self.abilities(g,target)[0].deathrattle_memory,memory);self.portable(g);self.play(g,P+'silence',self.first(g,P+'suppressor').id);self.kill(g,target);self.assertNotIn(drawn,g.state.players[1].hand);self.assertEqual(g.state.discard_history[-1].card.entity_id,drawn);self.portable(g)

    def test_discard_memory_retains_original_card_and_cost_copy_material(self):
        g=self.game((HOARDER,YETI,P+'kill',THORNS,P+'kill'));victim=self.play(g,HOARDER,self.first(g,YETI,zone='hand').id);memory=self.abilities(g,victim)[0].deathrattle_memory;self.assertEqual(len(memory.discard_ids),1);self.kill(g,victim);target=self.play(g,THORNS);self.assertEqual(self.abilities(g,target)[0].deathrattle_memory,memory)
        before=set(g.state.players[1].hand);self.kill(g,target);fresh=[g.state.entities[i]for i in g.state.players[1].hand if i not in before];self.assertEqual(len(fresh),1);self.assertEqual(fresh[0].card_id,YETI)
        from hs_sim.engine.costs import quote_unselected_cost
        self.assertEqual(quote_unselected_cost(g.state,self.r,fresh[0]).amount,self.r.card(YETI).cost-1);self.portable(g)

    def test_current_and_base_copy_preserve_only_current_grants(self):
        for op in('copy','base_copy','held_copy'):
            with self.subTest(op=op):
                g,target=self.seeded((P+op,));a,=self.abilities(g,target);self.play(g,P+op,target)
                copy=next(e for e in(self.board(g)if op!='held_copy'else[g.state.entities[i]for i in g.state.players[1].hand])if e.card_id==THORNS and e.id!=target)
                grants=self.abilities(g,copy.id);self.assertEqual(len(grants),0 if op=='base_copy'else 1)
                if grants:self.assertNotEqual(grants[0].id,a.id);self.assertEqual(grants[0].deathrattle_inherited_from,a.deathrattle_inherited_from)
                self.portable(g)

    def test_inherited_memory_current_copy_round_trips_carrier_scope(self):
        g=self.game((P+'kill',THORNS,P+'copy',P+'held_copy'),(EGG,));self.kill(g,self.first(g,EGG).id);target=self.play(g,THORNS);memory=self.abilities(g,target)[0].deathrattle_memory;self.play(g,P+'copy',target);self.play(g,P+'held_copy',target)
        carriers=[e for e in self.board(g)+[g.state.entities[i]for i in g.state.players[1].hand]if e.card_id==THORNS];self.assertEqual(len(carriers),3);self.assertTrue(all(self.abilities(g,e.id)[0].deathrattle_memory==memory for e in carriers));self.portable(g)

    def test_control_change_uses_new_death_controller(self):
        g,target=self.seeded((P+'steal',P+'kill'));self.play(g,P+'steal',target);count=len([x for x in g.state.draw_history if x.player_id==2]);self.kill(g,target);self.assertEqual(len([x for x in g.state.draw_history if x.player_id==2]),count+1);self.portable(g)

    def test_silence_and_normal_return_remove_inheritance(self):
        for op in('silence','bounce'):
            with self.subTest(op=op):
                g,target=self.seeded((P+op,));self.play(g,P+op,target);self.assertFalse(self.abilities(g,target));self.portable(g)

    def test_nested_real_inheritance_retains_both_physical_deaths(self):
        g,first=self.seeded((P+'kill',THORNS));self.kill(g,first);second=self.play(g,THORNS);grants=self.abilities(g,second);self.assertEqual(len(grants),2);self.assertEqual([a.deathrattle_inherited_from[0]for a in grants],[1,2]);self.assertTrue(any(a.deathrattle_inherited_from is not None for a in g.state.death_history[1].abilities));self.portable(g)

    def test_real_extra_battlecry_grants_independent_complete_batches(self):
        g,target=self.seeded(board=('LOE_077',LOOT));self.assertEqual(len(self.abilities(g,target)),2);self.assertEqual(len({a.id for a in self.abilities(g,target)}),2);self.portable(g)

    def test_summon_without_battlecry_does_not_gain(self):
        g=self.game((P+'kill',P+'summon'),(LOOT,));self.kill(g,self.first(g,LOOT).id);self.play(g,P+'summon');self.assertFalse(self.abilities(g,self.first(g,THORNS).id));self.portable(g)

    def test_source_dead_before_actual_battlecry_does_not_attach_to_corpse(self):
        g=self.game((P+'kill',THORNS),(LOOT,P+'watch'),mode='kill_entry');self.kill(g,self.first(g,LOOT).id);target=self.play(g,THORNS);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertFalse(self.abilities(g,target));self.portable(g)

    def test_actual_grant_reaction_wait_restores_replays_and_rolls_back_failure(self):
        g,target=self.seeded(mode='wait',board=(LOOT,P+'watch'));self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(self.abilities(g,target)),1);other=self.portable(g);before=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(q.player_id,q.id,('bad',)))
        self.assertEqual(g.snapshot(),before)
        for game in(g,other):q=game.state.pending_choice;game.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)

    def test_forged_original_declaration_and_changed_memory_are_rejected(self):
        g=self.game((P+'kill',THORNS),(EGG,));self.kill(g,self.first(g,EGG).id);target=self.play(g,THORNS);before=g.snapshot()
        for mutate in('death','ability','memory','strip'):
            with self.subTest(mutate=mutate):
                snapshot=json.loads(json.dumps(before));ability=next(a for a in snapshot['state']['entities'][str(target)]['abilities']if a['kind']=='deathrattle')
                if mutate=='death':ability['deathrattle_inherited_from'][0]=9999
                elif mutate=='ability':ability['deathrattle_inherited_from'][1]=ability['id']
                elif mutate=='strip':ability['deathrattle_inherited_from']=None
                else:ability['deathrattle_memory']['growth_steps']+=1
                with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(snapshot,registry())


if __name__=='__main__':unittest.main()
