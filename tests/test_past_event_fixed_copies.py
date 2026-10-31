"""Actual event/fixed consumers and official backward-copy rule corrections."""
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_event_fixed_copies as native
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,Damage,Destroy,DestroyBatch,Freeze,
    GainArmor,GrantKeyword,InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.cross_zone import BuffStoredCard
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,Keyword,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.local_pool_format import build_cn37_local_pool_format

SPLINTER,ZOLA,TALDARAM,MOORABI,SONYA,IXLID=native.ROOTS
P='k724.'
A,B,SLEEP,SHIFT,FROZEN_KILLER=(P+x for x in('a','b','sleep','shift','frozen_killer'))
BOOST,WOUND,HUSH,KILL,FREEZE,GRANT,SUMMON,AREA_KILL,HAND_BUFF,DECK3,DECK4,ZERO,THREE=(
    P+x for x in('boost','wound','hush','kill','freeze','grant','summon','area_kill','hand_buff','deck3','deck4','zero','three'))
WATCH,FILL,FAIL=(P+x for x in('watch','fill','fail'))
CTX=GenerationContext(P+'original-events-fixture','experimental')


@lru_cache(None)
def fixture(role='writer',host=False):
    h=build_cn37_local_pool_format()if host else None;r=h.registry if h else defaults()
    if not host:native.register_past_event_fixed_copies(r)
    meta=metadata(collectible=False,tribes=())
    r.register_behavior(A,lambda c:(Buff(c.source_id,1,2,c.source_id),GainArmor(c.player_id,3)))
    r.register_behavior(SHIFT,lambda c:(Transform(c.source_id,B),))
    r.register_behavior(FROZEN_KILLER,lambda c:(Destroy(c.event.target_id,c.source_id),))
    for cid,cost,atk,hp,fields in((A,4,2,6,dict(keywords=(Keyword.TAUNT,),battlecry=A)),(B,1,5,7,{}),
            (SLEEP,1,2,4,dict(dormant_turns=2)),(SHIFT,1,1,4,dict(battlecry=SHIFT)),
            (FROZEN_KILLER,1,0,20,dict(triggers=(TriggerSpec('frozen',FROZEN_KILLER),)))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=atk,health=hp,metadata=meta,**fields))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    def stored(c,zone,cost,stats=False):
        e=next(c.state.entities[i]for i in getattr(c.state.players[c.player_id],zone)if c.state.entities[i].kind==CardType.MINION)
        return(BuffStoredCard(CardReference.capture(e),6 if stats else 0,7 if stats else 0,c.source_id,cost=CostSpec(set_to=cost)),)
    bodies={BOOST:lambda c:(Buff(c.target_id,3,4,c.source_id),),WOUND:lambda c:(Damage(c.target_id,1,c.source_id),),
        HUSH:lambda c:(Silence(c.target_id),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        FREEZE:lambda c:(Freeze(c.target_id,c.source_id),),GRANT:lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),),
        SUMMON:lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(B),),SummonCause.capture(c)),),
        AREA_KILL:lambda c:(DestroyBatch(tuple(c.state.players[c.player_id].board),c.source_id),),
        HAND_BUFF:lambda c:stored(c,'hand',0,True),DECK3:lambda c:stored(c,'deck',3),DECK4:lambda c:stored(c,'deck',4),
        ZERO:lambda c:(GainArmor(c.player_id,1),),THREE:lambda c:(GainArmor(c.player_id,1),)}
    targets={BOOST,WOUND,HUSH,KILL,FREEZE,GRANT}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=3 if cid==THREE else 0,
            on_play=cid,metadata=meta,**({'targeting':TargetSpec()}if cid in targets else {})))
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ResolutionError('K724 deliberate rollback')))
    def wait(c):
        e=c.event;source=c.state.entities.get(e.source_id);target=c.state.entities.get(e.target_id)
        roots={SPLINTER,ZOLA,MOORABI,SONYA}
        copied=e.kind=='card_created'and source is not None and source.card_id in roots
        transformed=e.kind=='transformed'and dict(e.data).get('old_card_id')==TALDARAM
        summoned=(e.kind=='minion_summoned'and target is not None and target.origin_entity_id is not None and
            any(row.request.cause.source.card_id==IXLID and row.status=='active' for row in c.state.card_summon_history))
        if not(copied or transformed or summoned):return()
        options=(ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fault',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))))
        if copied:options+=(ChoiceOption('remove','Remove original source',(Destroy(source.id,c.source_id),)),)
        return(RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(WATCH,wait);r.register_card(CardDefinition(WATCH,WATCH,CardType.WEAPON,attack=0,durability=10,metadata=meta,
        triggers=tuple(TriggerSpec(e,WATCH)for e in('card_created','transformed','minion_summoned'))))
    r.register_behavior(FILL,lambda c:(AddToHand(c.player_id,ZERO,c.source_id),))
    r.register_card(CardDefinition(FILL,FILL,CardType.WEAPON,attack=0,durability=10,metadata=meta,triggers=(TriggerSpec('card_committed',FILL),)))
    r.validate();return r,h.context if h else CTX


class EventFixedCopyTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode=='host')[0])
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=None,host=False,watch=False,fill=False):
        self.mode='host'if host else'small';r,ctx=fixture('writer',host)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,
            deck=(B,)*12 if deck is None else deck,mana=40,max_mana=40,mana_cap=40,armor=500,
            weapon_card_id=WATCH if watch else FILL if fill else None),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(B,)*12,mana=40,max_mana=40,mana_cap=40,armor=500)),
            seed=724,generation_context=ctx),r)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def bodies(self,g,cid,p=1):return[g.state.entities[i]for i in g.state.players[p].board if g.state.entities[i].card_id==cid]
    def quote(self,g,e):return quote_unselected_cost(g.state,g.registry,e).amount
    def finish(self,g):
        n=0
        while g.state.pending_choice is not None:n+=1;self.assertLess(n,30);self.choose(g)
    def fault(self,g):
        old=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),old)

    def test_six_full_roots_twenty_six_primary_faces_and_six_existing_corrections(self):
        d=native.load_batch();self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(len(d['official_observations']),26);self.assertEqual(len(d['existing_effect_corrections']),6)
        self.assertFalse(d['complete_past_source_bound']);self.assertEqual(d['existing_dependencies'],[])
        self.assertTrue(d['superseded_local_policies']);self.assertNotIn('MIS_701',fixture()[0].cards)
        for cid in native.ROOTS:self.assertEqual(fixture()[0].card(cid),fixture('independent-reader')[0].card(cid))

    def test_all_six_actual_current_host_entries_execute(self):
        for cid in(SPLINTER,ZOLA,TALDARAM):
            g=self.game((cid,),board=(A,),deck=(B,),host=True);self.play(g,cid,self.unit(g,A).id)
            self.assertEqual(len(g.state.play_history),1)
            self.assertTrue(any(e.origin_entity_id is not None for e in g.state.entities.values())or cid==TALDARAM)
        g=self.game((FREEZE,),board=(MOORABI,A),host=True);self.play(g,FREEZE,self.unit(g,A).id);self.assertEqual(self.entity(g,A).card_id,A)
        g=self.game((KILL,),board=(SONYA,A),host=True);self.play(g,KILL,self.unit(g,A).id);self.assertEqual(self.entity(g,A).attack,1)
        g=self.game((A,),board=(IXLID,),host=True);self.play(g,A);self.assertEqual(len(self.bodies(g,A)),2)

    def test_Splintergraft_base_copy_sets_ten_ten_and_cost_before_publication(self):
        g=self.game((BOOST,WOUND,SPLINTER),board=(A,));sid=self.unit(g,A).id
        self.play(g,BOOST,sid);self.play(g,WOUND,sid);self.play(g,SPLINTER,sid);copy=self.entity(g,A)
        self.assertNotEqual(copy.id,sid);self.assertEqual((copy.attack,copy.health,self.quote(g,copy)),(10,10,10))
        self.assertEqual((g.state.entities[sid].attack,g.state.entities[sid].health),(5,9))
        self.assertEqual(len(g.state.play_history),3)

    def test_Splintergraft_copy_real_play_uses_one_payment_then_silence_restores_printed(self):
        g=self.game((SPLINTER,HUSH),board=(A,));self.play(g,SPLINTER,self.unit(g,A).id);sid=self.play(g,A)
        self.assertEqual(g.state.play_history[-1].cost,10);self.assertEqual((g.state.entities[sid].attack,g.state.entities[sid].health),(11,12))
        self.play(g,HUSH,sid);self.assertEqual((g.state.entities[sid].attack,g.state.entities[sid].health),(2,6))

    def test_Zola_printed_base_drops_source_buffs_grants_and_injury(self):
        g=self.game((BOOST,WOUND,GRANT,ZOLA),board=(A,));sid=self.unit(g,A).id
        for spell in(BOOST,WOUND,GRANT):self.play(g,spell,sid)
        self.play(g,ZOLA,sid);copy=self.entity(g,A)
        self.assertEqual((copy.attack,copy.health,self.quote(g,copy)),(2,6,4));self.assertNotIn(Keyword.DIVINE_SHIELD,copy.keywords)
        self.assertIn(Keyword.TAUNT,copy.keywords);self.assertEqual(g.state.entities[sid].health,9)

    def test_friendly_hand_copy_target_legality_and_full_hand_burn_are_atomic(self):
        g=self.game((ZOLA,),enemy=(A,));old=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,ZOLA,self.unit(g,A,2).id)
        self.assertEqual(g.snapshot(),old);self.play(g,ZOLA);self.assertEqual(g.state.players[1].hand,[])
        g=self.game((SPLINTER,)+(ZERO,)*9,board=(A,),fill=True);sid=self.unit(g,A).id;self.play(g,SPLINTER,sid)
        copies=[e for e in g.state.entities.values()if e.origin_entity_id==sid];self.assertEqual(len(copies),1)
        self.assertEqual((copies[0].zone,copies[0].attack,copies[0].health),(Zone.GRAVEYARD,10,10))
        self.assertIn(sid,g.state.players[1].board)

    def test_hand_copy_waits_independent_restore_replay_and_late_choice_rollback(self):
        for cid in(SPLINTER,ZOLA):
            g=self.game((cid,),board=(A,),watch=True);self.play(g,cid,self.unit(g,A).id)
            self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g)
            self.assertEqual(len(g.state.players[1].hand),1)

    def test_Taldaram_no_three_transforms_original_to_current_three_three_without_Battlecry(self):
        g=self.game((BOOST,TALDARAM),enemy=(A,),deck=(B,));sid=self.unit(g,A,2).id;self.play(g,BOOST,sid)
        source=self.play(g,TALDARAM,sid);body=g.state.entities[source]
        self.assertEqual((body.card_id,body.attack,body.health),(A,3,3));self.assertIn(Keyword.TAUNT,body.keywords)
        self.assertEqual(g.state.play_history[-1].cost,3);self.assertEqual(g.state.entities[sid].attack,5)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,500)

    def test_Taldaram_three_cost_spell_disables_arrow_and_blocked_body_is_known_empty(self):
        g=self.game((TALDARAM,),board=(A,),deck=(THREE,));old=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,TALDARAM,self.unit(g,A).id)
        self.assertEqual(g.snapshot(),old);sid=self.play(g,TALDARAM)
        self.assertEqual(g.state.entities[sid].card_id,TALDARAM)

    def test_Taldaram_uses_same_current_local_deck_cost_policy_as_Keleseth(self):
        g=self.game((DECK3,TALDARAM),board=(A,),deck=(B,));self.play(g,DECK3);sid=self.play(g,TALDARAM)
        self.assertEqual(g.state.entities[sid].card_id,TALDARAM)
        g=self.game((DECK4,TALDARAM),board=(A,),deck=(B,));self.play(g,DECK4)
        sid=self.play(g,TALDARAM,self.unit(g,A).id);self.assertEqual(g.state.entities[sid].card_id,A)

    def test_Taldaram_current_copy_wait_restores_then_silence_removes_three_three(self):
        g=self.game((TALDARAM,HUSH),board=(A,),deck=(B,),watch=True);sid=self.play(g,TALDARAM,self.unit(g,A).id)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.finish(g);self.play(g,HUSH,sid)
        self.assertEqual((g.state.entities[sid].attack,g.state.entities[sid].health),(2,6))

    def test_Moorabi_friendly_and_enemy_new_freeze_copy_printed_base_only(self):
        g=self.game((BOOST,FREEZE,FREEZE),board=(MOORABI,A),enemy=(B,));sid=self.unit(g,A).id
        self.play(g,BOOST,sid);self.play(g,FREEZE,sid);self.play(g,FREEZE,self.unit(g,B,2).id)
        self.assertEqual((self.entity(g,A).attack,self.entity(g,A).health),(2,6));self.assertFalse(self.entity(g,A).frozen)
        self.assertEqual((self.entity(g,B).attack,self.entity(g,B).health),(5,7))
        self.assertTrue(g.state.entities[sid].frozen)

    def test_Moorabi_repeated_freeze_heroes_and_self_do_not_create_extra_copies(self):
        g=self.game((FREEZE,FREEZE,FREEZE,FREEZE),board=(MOORABI,A));sid=self.unit(g,A).id
        self.play(g,FREEZE,sid);self.play(g,FREEZE,sid);self.play(g,FREEZE,self.unit(g,MOORABI).id)
        self.play(g,FREEZE,g.state.players[2].hero_id);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[A])

    def test_Moorabi_accepted_freeze_face_survives_earlier_reaction_removing_original(self):
        g=self.game((FREEZE,),board=(FROZEN_KILLER,MOORABI,A));sid=self.unit(g,A).id;self.play(g,FREEZE,sid)
        self.assertEqual(g.state.entities[sid].zone,Zone.GRAVEYARD);self.assertEqual(self.entity(g,A).card_id,A)

    def test_Moorabi_silence_removes_listener_and_copy_wait_is_portable(self):
        g=self.game((HUSH,FREEZE),board=(MOORABI,A));self.play(g,HUSH,self.unit(g,MOORABI).id);self.play(g,FREEZE,self.unit(g,A).id)
        self.assertEqual(g.state.players[1].hand,[])
        g=self.game((FREEZE,),board=(MOORABI,A),watch=True);self.play(g,FREEZE,self.unit(g,A).id)
        self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g);self.assertEqual(self.entity(g,A).attack,2)

    def test_Sonya_actual_friendly_death_uses_printed_one_one_one_cost(self):
        g=self.game((BOOST,GRANT,KILL),board=(SONYA,A));sid=self.unit(g,A).id
        self.play(g,BOOST,sid);self.play(g,GRANT,sid);self.play(g,KILL,sid);copy=self.entity(g,A)
        self.assertEqual((copy.attack,copy.health,self.quote(g,copy)),(1,1,1));self.assertNotIn(Keyword.DIVINE_SHIELD,copy.keywords)
        self.assertIn(Keyword.TAUNT,copy.keywords);self.assertEqual(copy.origin_entity_id,sid)

    def test_Sonya_enemy_death_and_same_wave_removed_source_do_not_reward(self):
        g=self.game((KILL,),board=(SONYA,),enemy=(B,));self.play(g,KILL,self.unit(g,B,2).id);self.assertEqual(g.state.players[1].hand,[])
        g=self.game((AREA_KILL,),board=(SONYA,A));self.play(g,AREA_KILL);self.assertEqual(g.state.players[1].hand,[])
        self.assertEqual(len(g.state.death_history),2)

    def test_Sonya_accepted_reward_wait_restores_and_keeps_original_death_private(self):
        g=self.game((KILL,),board=(SONYA,A),watch=True);self.play(g,KILL,self.unit(g,A).id)
        self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g)
        self.assertEqual(len(g.state.players[1].hand),1);self.assertEqual(self.entity(g,A).health,1)

    def test_Ixlid_current_post_Battlecry_material_copies_once_without_second_Battlecry(self):
        g=self.game((A,),board=(IXLID,));sid=self.play(g,A);bodies=self.bodies(g,A)
        self.assertEqual(len(bodies),2);self.assertTrue(all((e.attack,e.health)==(3,8)for e in bodies))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,503)
        self.assertEqual(len(g.state.play_history),1);self.assertTrue(any(e.origin_entity_id==sid for e in bodies))

    def test_Ixlid_own_arrival_effect_summons_and_opponent_plays_do_not_trigger(self):
        g=self.game((IXLID,SUMMON),enemy_hand=(B,));self.play(g,IXLID);self.assertEqual(len(self.bodies(g,IXLID)),1)
        self.play(g,SUMMON);self.assertEqual(len(self.bodies(g,B)),1);g.apply(EndTurn(1));self.play(g,B,player=2)
        self.assertEqual(len(self.bodies(g,B)),1)

    def test_Ixlid_original_continuous_presence_uses_current_self_transformed_face(self):
        g=self.game((SHIFT,),board=(IXLID,));sid=self.play(g,SHIFT)
        self.assertEqual(g.state.entities[sid].card_id,B);self.assertEqual(len(self.bodies(g,B)),2)

    def test_Ixlid_full_board_and_silence_obey_existing_summon_and_source_limits(self):
        g=self.game((B,),board=(IXLID,)+(A,)*5);self.play(g,B);self.assertEqual(len(self.bodies(g,B)),1)
        g=self.game((HUSH,B),board=(IXLID,));self.play(g,HUSH,self.unit(g,IXLID).id);self.play(g,B)
        self.assertEqual(len(self.bodies(g,B)),1)

    def test_Ixlid_actual_copy_wait_independent_restore_replay_and_RNG_rollback(self):
        g=self.game((A,),board=(IXLID,),watch=True);self.play(g,A)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.finish(g)
        self.assertEqual(len(self.bodies(g,A)),2)

    def test_corrected_actual_Echo_Potion_and_Spikeshell_do_not_retain_backward_enchantments(self):
        for cid in('GVG_005','SCH_352','BAR_549'):
            g=self.game((BOOST,GRANT,cid),board=(A,),host=True);sid=self.unit(g,A).id
            self.play(g,BOOST,sid);self.play(g,GRANT,sid);self.play(g,cid,sid if cid=='BAR_549'else None)
            copy=self.entity(g,A);self.assertEqual((copy.attack,copy.health),(1,1)if cid=='SCH_352'else(2,6))
            self.assertNotIn(Keyword.DIVINE_SHIELD,copy.keywords)

    def test_corrected_actual_Loud_attack_and_Dead_Mans_Hand_remove_backward_buffs(self):
        g=self.game((BOOST,),board=('LOOT_218',),host=True);sid=self.unit(g,'LOOT_218').id;self.play(g,BOOST,sid)
        g.apply(Attack(1,sid,g.state.players[2].hero_id));copy=self.entity(g,'LOOT_218')
        self.assertEqual((copy.attack,copy.health),(1,1));self.assertEqual(g.state.entities[sid].attack,4)
        g=self.game((HAND_BUFF,'ICC_091',B),host=True);sid=self.entity(g,B).id;self.play(g,HAND_BUFF);self.play(g,'ICC_091')
        copy=next(e for e in g.state.entities.values()if e.origin_entity_id==sid)
        self.assertEqual((copy.zone,copy.attack,copy.health,self.quote(g,copy)),(Zone.DECK,5,7,1))
        self.assertEqual((g.state.entities[sid].attack,g.state.entities[sid].health,self.quote(g,g.state.entities[sid])),(11,14,0))
        g=self.portable(g)

    def test_new_private_material_and_original_records_do_not_enter_either_player_DTO(self):
        g=self.game((FREEZE,),board=(MOORABI,A),watch=True);self.play(g,FREEZE,self.unit(g,A).id)
        for player in(1,2):
            view=json.dumps(g.for_player(player).observe())
            for key in('resolution_frame','next_attachment_id','native_hand_candidates','targeted_spells','source_allocation'):
                self.assertNotIn('"'+key+'"',view)
        g=self.portable(g);self.finish(g)


if __name__=='__main__':unittest.main()
