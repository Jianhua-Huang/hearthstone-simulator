"""Real turn entries, physical inventories and original-combat continuations."""
from dataclasses import replace
from functools import lru_cache
import json, unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_turn_lifecycle as native
from hs_sim.engine import Attack, EndTurn, Game, PlayerSetup, ResolutionError, Scenario
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, Destroy, ForceAttack,
    GainArmor, GrantKeyword, InvokeBehavior, RandomDamage, RequestChoice, ReturnToHand, Silence, SpendResource, Transform)
from hs_sim.engine.health_loss import LoseHealth
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType, EndTurnSpec,
    Keyword, Resource, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import GenerationContext, PoolCard
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.summon_sources import DeathQuery, Resurrect
from hs_sim.engine.turn_event_consumers import (GrowAfterOriginalForcedAttack, attacked_this_residence)
from hs_sim.local_pool_format import build_cn37_local_pool_format

KEL,HAMM,GILLY,AFK,MAW,LOTHAR=native.ROOTS
CROC=native.CROC
P='k725.'
A,B,TINY,HUGE,SLEEP,POISON,REBORN=(P+x for x in('a','b','tiny','huge','sleep','poison','reborn'))
KILL,BOOST,HUSH,RETURN,FORCE,SHIELD,POISON_GRANT,SHIFT,REZ,EARLY=(P+x for x in
    ('kill','boost','hush','return','force','shield','poison_grant','shift','rez','early'))
DRAIN,WOUND=P+'drain',P+'wound'
WATCH,FILL,FAIL,EARLIER_ATTACK,EARLIER_KILL=(P+x for x in('watch','fill','fail','earlier_attack','earlier_kill'))
CTX=GenerationContext(P+'turn-consumer-fixture','experimental')


@lru_cache(None)
def fixture(role='writer',host=False):
    h=build_cn37_local_pool_format()if host else None;r=h.registry if h else defaults()
    if not host:native.register_past_turn_lifecycle(r)
    meta=metadata(collectible=False,tribes=())
    def forced(c,attacker):
        enemies=c.state.players[3-c.player_id].board
        if not enemies:return()
        return(ForceAttack(BoardPresenceReference.capture(c.state,attacker),BoardPresenceReference.capture(c.state,enemies[0])),)
    def earlier(c,kill=False):
        units=[i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==A]
        if not units:return()
        return(Destroy(units[0],c.source_id),)if kill else forced(c,units[0])
    r.register_behavior(EARLIER_ATTACK,earlier);r.register_behavior(EARLIER_KILL,lambda c:earlier(c,True))
    units=((A,2,3,{}),(B,0,12,{}),(TINY,1,1,{}),(HUGE,10,10,{}),
        (SLEEP,2,4,dict(dormant_turns=2)),(POISON,1,1,dict(keywords=(Keyword.POISONOUS,))),
        (REBORN,1,1,dict(keywords=(Keyword.REBORN,))),
        (EARLIER_ATTACK,0,10,dict(triggers=(TriggerSpec('turn_ended',EARLIER_ATTACK,EndTurnSpec('controller')),))),
        (EARLIER_KILL,0,10,dict(triggers=(TriggerSpec('turn_ended',EARLIER_KILL,EndTurnSpec('controller')),))))
    for cid,attack,health,fields in units:
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=attack,health=health,metadata=meta,**fields))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    def early(c):
        from hs_sim.engine.effects import TriggerDeathrattles
        return(TriggerDeathrattles(c.target_id,c.source_id),)
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),BOOST:lambda c:(Buff(c.target_id,4,5,c.source_id),),
        HUSH:lambda c:(Silence(c.target_id),),RETURN:lambda c:(ReturnToHand(c.target_id),),
        FORCE:lambda c:forced(c,c.target_id),SHIELD:lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),),
        POISON_GRANT:lambda c:(GrantKeyword(c.target_id,Keyword.POISONOUS,c.source_id),),
        SHIFT:lambda c:(Transform(c.target_id,B),),EARLY:early,
        DRAIN:lambda c:(SpendResource(3-c.player_id,Resource.CORPSES,5),),
        WOUND:lambda c:(LoseHealth(c.state.players[c.player_id].hero_id,7,c.source_id),),
        REZ:lambda c:(Resurrect(c.player_id,1,query=DeathQuery(),selection='first',source_id=c.source_id,cause=SummonCause.capture(c)),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=0,on_play=cid,
            metadata=meta,**({}if cid in(REZ,DRAIN,WOUND)else dict(targeting=TargetSpec()))))
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ResolutionError('K725 deliberate rollback')))
    def wait(c):
        source=c.state.entities.get(c.event.source_id);target=c.state.entities.get(c.event.target_id)
        relevant=source is not None and source.card_id in native.ROOTS
        if c.event.kind=='minion_summoned':
            rows=[x for x in c.state.card_summon_history if x.request.cause.source.card_id==KEL and x.status=='active']
            relevant=bool(rows)
            if rows:source=c.state.entities[rows[-1].request.cause.source.entity_id]
        if c.event.kind=='resource_spent':relevant=any(c.state.entities[i].card_id==MAW for i in c.state.players[c.player_id].board)
        if not relevant:return()
        options=(ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fault',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))))
        removal=source if source is not None and source.zone==Zone.BOARD and source.kind==CardType.MINION else next(
            (c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==MAW),None)
        if removal is not None:options+=(ChoiceOption('remove','Remove original',(Destroy(removal.id,c.source_id),)),)
        if c.event.kind=='attack_declared'and target is not None and target.zone==Zone.BOARD:
            options+=(ChoiceOption('retreat','Return the original defender',(ReturnToHand(target.id),)),)
        return(RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(WATCH,wait);r.register_card(CardDefinition(WATCH,WATCH,CardType.WEAPON,durability=10,
        metadata=meta,triggers=tuple(TriggerSpec(e,WATCH)for e in('minion_summoned','card_created','card_destroyed_in_deck','stats_changed','attack_declared','resource_spent'))))
    r.register_behavior(FILL,lambda c:(AddToHand(c.player_id,BOOST,c.source_id),))
    r.register_card(CardDefinition(FILL,FILL,CardType.WEAPON,durability=10,metadata=meta,triggers=(TriggerSpec('turn_ended',FILL,EndTurnSpec('controller')),)))
    r.validate();return r,h.context if h else CTX


class TurnLifecycleTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode=='host')[0])
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=None,enemy_deck=None,corpses=0,host=False,watch=False,fill=False):
        self.mode='host'if host else'small';r,ctx=fixture('writer',host)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(B,)*12 if deck is None else deck,
            mana=40,max_mana=40,mana_cap=40,armor=500,corpses=corpses,weapon_card_id=WATCH if watch else FILL if fill else None),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(B,)*12 if enemy_deck is None else enemy_deck,
                mana=40,max_mana=40,mana_cap=40,armor=500)),seed=725,generation_context=ctx),r)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def bodies(self,g,cid,p=1):return[g.state.entities[i]for i in g.state.players[p].board if g.state.entities[i].card_id==cid]
    def finish(self,g):
        count=0
        while g.state.pending_choice is not None:count+=1;self.assertLess(count,40);self.choose(g)
    def fault(self,g):
        old=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),old)
    def health(self,g):
        e=g.state.entities[g.state.players[1].hero_id];return e.health,e.max_health

    def test_complete_source_roles_exact_child_and_omitted_zero_attack(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),16);self.assertEqual(len(d['original_candidate_ids']),732)
        row=next(x['record']for x in d['cards']if x['record']['id']==AFK)
        self.assertIsNone(row['attack']);self.assertNotIn('ATK',row['tags']);self.assertEqual(fixture()[0].card(AFK).attack,0)
        child=d['dependencies'][0]['record'];self.assertEqual((child['id'],child['dbf_id']),(CROC,113343))
        self.assertFalse(child['collectible']);self.assertNotIn('MIS_701',fixture()[0].cards)
        self.assertEqual(fixture()[0].card(CROC).metadata.tribes,('beast',))
        for cid in native.ROOTS+(CROC,):self.assertEqual(fixture()[0].card(cid),fixture('independent-reader')[0].card(cid))

    def test_all_six_current_host_entries_and_real_generated_child(self):
        for cid in native.ROOTS:
            g=self.game((cid,KILL),board=(A,),enemy=(TINY,),host=True);self.play(g,cid)
            if cid==KEL:self.play(g,KILL,self.unit(g,A).id)
            self.end(g);self.assertTrue(g.state.play_history[0].completed)
            if cid==KEL:self.assertEqual(len(self.bodies(g,A)),1)
            if cid==HAMM:self.assertEqual(self.unit(g,HAMM).attack,5)
            if cid==GILLY:
                self.assertEqual(self.entity(g,CROC).health,3);self.end(g);sid=self.play(g,CROC)
                self.assertEqual((g.state.entities[sid].attack,g.state.entities[sid].health),(2,3))
            if cid==AFK:self.assertEqual(self.unit(g,A).attack,4)
            if cid==MAW:self.assertEqual(g.state.players[1].resources[Resource.CORPSES],5)
            if cid==LOTHAR:self.assertEqual(self.unit(g,LOTHAR).attack,10)

    def test_Kel_resurrects_every_friendly_occurrence_only_this_global_turn(self):
        g=self.game((KILL,KILL),board=(KEL,A,A),enemy=(TINY,));ids=[e.id for e in self.bodies(g,A)]
        for sid in ids:self.play(g,KILL,sid)
        self.end(g);self.assertEqual(len(self.bodies(g,A)),2)
        self.assertTrue(all(e.id not in ids for e in self.bodies(g,A)));self.end(g)
        self.assertEqual(len(self.bodies(g,A)),2)

    def test_Kel_operates_on_opponent_turn_and_excludes_opponent_dead(self):
        g=self.game(board=(KEL,A),enemy=(TINY,),enemy_hand=(KILL,KILL));self.end(g)
        self.play(g,KILL,self.unit(g,A).id,2);self.play(g,KILL,self.unit(g,TINY,2).id,2);self.end(g)
        self.assertEqual(len(self.bodies(g,A)),1);self.assertEqual(self.bodies(g,TINY,2),[])

    def test_Kel_newly_played_source_reads_earlier_death_and_resets_ordinary_buffs(self):
        g=self.game((BOOST,KILL,KEL),board=(A,));sid=self.unit(g,A).id
        self.play(g,BOOST,sid);self.play(g,KILL,sid);self.play(g,KEL);self.end(g)
        e=self.unit(g,A);self.assertNotEqual(e.id,sid);self.assertEqual((e.attack,e.health),(2,3))

    def test_Kel_reads_deaths_from_an_earlier_end_body(self):
        g=self.game(board=(EARLIER_KILL,A,KEL));sid=self.unit(g,A).id;self.end(g)
        self.assertEqual(len(self.bodies(g,A)),1);self.assertNotEqual(self.unit(g,A).id,sid)

    def test_Kel_reborn_two_real_death_occurrences_are_not_deduplicated_by_card(self):
        g=self.game((KILL,KILL),board=(KEL,REBORN));self.play(g,KILL,self.unit(g,REBORN).id)
        self.play(g,KILL,self.unit(g,REBORN).id);self.end(g)
        self.assertEqual(len(self.bodies(g,REBORN)),2)

    def test_Kel_capacity_uses_shared_resurrection_and_empty_does_not_draw_rng(self):
        g=self.game((KILL,),board=(KEL,A,B,B,B,B,B));self.play(g,KILL,self.unit(g,A).id);self.end(g)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(len(self.bodies(g,A)),1)
        g=self.game(board=(KEL,));rng=g._rng.getstate();self.end(g);self.assertEqual(g._rng.getstate(),rng)

    def test_Kel_resurrection_wait_restore_continue_keeps_original_batch(self):
        g=self.game((KILL,KILL),board=(KEL,A,A),watch=True)
        for sid in[e.id for e in self.bodies(g,A)]:self.play(g,KILL,sid)
        self.end(g);self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g)
        self.assertEqual(len(self.bodies(g,A)),2);self.assertEqual(self.bodies(g,KEL),[]);self.portable(g)

    def test_Hamm_eats_only_physical_opponent_deck_minions_and_grows_once(self):
        g=self.game(board=(HAMM,),deck=(A,),enemy_deck=(BOOST,A,HUSH));original=list(g.state.players[2].deck)
        self.end(g);self.assertEqual(g.state.players[2].deck,original[2:])
        # Opponent's regular start draw also consumes the first spell, separately.
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].hand],[BOOST])
        self.assertEqual((self.unit(g,HAMM).attack,self.unit(g,HAMM).health),(5,5))
        self.assertEqual(g.state.entities[original[1]].zone,Zone.GRAVEYARD);self.assertEqual(g.state.death_history,[])
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0);self.assertEqual(g.state.players[2].resources[Resource.CORPSES],0)

    def test_Hamm_empty_or_spell_only_inventory_has_no_reward_or_rng(self):
        for deck in((),(BOOST,HUSH)):
            g=self.game(board=(HAMM,),enemy_deck=deck);rng=g._rng.getstate();self.end(g)
            self.assertEqual(g._rng.getstate(),rng);self.assertEqual(self.unit(g,HAMM).attack,3)

    def test_Hamm_uses_physical_duplicates_and_does_not_execute_their_deathrattles(self):
        g=self.game(board=(HAMM,),enemy_deck=(GILLY,GILLY,BOOST));ids=list(g.state.players[2].deck)
        self.end(g);eaten=[i for i in ids if g.state.entities[i].zone==Zone.GRAVEYARD]
        self.assertEqual(len(eaten),1);self.assertEqual(g.state.entities[eaten[0]].card_id,GILLY)
        self.assertFalse(any(e.card_id==CROC for e in g.state.entities.values()));self.assertEqual(g.state.death_history,[])

    def test_Hamm_wait_private_deck_restore_and_source_removal_prevents_reward(self):
        g=self.game(board=(HAMM,),enemy_deck=(A,B),watch=True);sid=self.unit(g,HAMM).id;self.end(g)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g)
        view=json.dumps(g.for_player(1).observe());self.assertNotIn('rng_state',view);self.assertNotIn('GrowAfter',view)
        self.choose(g,'remove');self.finish(g);self.assertEqual(g.state.entities[sid].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[sid].attack,3);self.portable(g)

    def test_Gilly_generates_exact_croc_only_at_own_end_and_croc_really_plays(self):
        g=self.game(board=(GILLY,));self.end(g);self.assertEqual(len(g.state.players[1].hand),1);self.end(g)
        self.assertEqual(sum(g.state.entities[i].card_id==CROC for i in g.state.players[1].hand),1)
        sid=self.play(g,CROC);self.assertEqual((g.state.entities[sid].attack,g.state.entities[sid].health),(2,3))

    def test_Gilly_death_buffs_actual_hand_minions_only_and_not_enemy(self):
        g=self.game((A,BOOST,KILL,CROC),board=(GILLY,),deck=(A,),enemy_hand=(A,));sid=self.unit(g,GILLY).id;self.play(g,KILL,sid)
        for cid in(A,CROC):self.assertEqual((self.entity(g,cid).attack,self.entity(g,cid).health),(4,6))
        self.assertEqual(self.entity(g,BOOST).attack,0);self.assertEqual(self.entity(g,A,2).health,3)
        self.assertEqual(g.state.entities[g.state.players[1].deck[0]].health,3)
        sid=self.play(g,CROC);self.assertEqual(g.state.entities[sid].health,6)

    def test_Gilly_early_deathrattle_and_silence_use_existing_lifecycle(self):
        g=self.game((EARLY,A,HUSH,KILL),board=(GILLY,));sid=self.unit(g,GILLY).id
        self.play(g,EARLY,sid);self.assertEqual(self.entity(g,A).health,6);self.assertEqual(g.state.death_history,[])
        self.play(g,HUSH,sid);self.play(g,KILL,sid);self.assertEqual(self.entity(g,A).health,6)

    def test_Gilly_full_hand_burn_and_created_wait_are_portable(self):
        g=self.game((BOOST,)*10,board=(GILLY,));self.end(g)
        copies=[e for e in g.state.entities.values()if e.card_id==CROC]
        self.assertEqual(len(copies),1);self.assertEqual(copies[0].zone,Zone.GRAVEYARD)
        g=self.game(board=(GILLY,),watch=True);self.end(g);self.assertIsNotNone(g.state.pending_choice)
        self.fault(g);g=self.portable(g);self.finish(g);self.assertEqual(self.entity(g,CROC).health,3);self.portable(g)

    def test_AFK_buffs_other_friendly_unattacked_minions_and_excludes_dormant(self):
        g=self.game(board=(AFK,A,B,SLEEP),enemy=(A,));self.end(g)
        self.assertEqual((self.unit(g,AFK).attack,self.unit(g,AFK).health),(0,5))
        self.assertEqual(self.unit(g,A).attack,4);self.assertEqual(self.unit(g,B).health,14)
        self.assertEqual(self.unit(g,SLEEP).health,4);self.assertEqual(self.unit(g,A,2).health,3)

    def test_AFK_manual_and_forced_completed_attacks_both_excluded(self):
        for force in(False,True):
            g=self.game((FORCE,),board=(AFK,A),enemy=(B,));sid=self.unit(g,A).id
            if force:self.play(g,FORCE,sid)
            else:g.apply(Attack(1,sid,self.unit(g,B,2).id))
            self.assertEqual(g.state.entities[sid].attacks_this_turn,0 if force else 1)
            self.assertTrue(attacked_this_residence(g.state,g.state.entities[sid]));self.end(g)
            self.assertEqual(g.state.entities[sid].attack,2)

    def test_AFK_fresh_query_sees_attack_from_earlier_end_body(self):
        g=self.game(board=(EARLIER_ATTACK,AFK,A),enemy=(B,));sid=self.unit(g,A).id;self.end(g)
        self.assertEqual(g.state.entities[sid].attack,2);self.assertEqual(self.unit(g,EARLIER_ATTACK).attack,2)

    def test_AFK_same_entity_reentered_after_attack_receives_new_residence_reward(self):
        g=self.game((RETURN,),board=(AFK,A),enemy=(B,));sid=self.unit(g,A).id;old=BoardPresenceReference.capture(g.state,sid)
        g.apply(Attack(1,sid,self.unit(g,B,2).id));self.play(g,RETURN,sid);self.assertEqual(self.play(g,A),sid)
        self.assertNotEqual(old,BoardPresenceReference.capture(g.state,sid));self.end(g);self.assertEqual(g.state.entities[sid].attack,4)

    def test_AFK_silence_and_stats_wait_restore(self):
        g=self.game((HUSH,),board=(AFK,A));self.play(g,HUSH,self.unit(g,AFK).id);self.end(g);self.assertEqual(self.unit(g,A).attack,2)
        g=self.game(board=(AFK,A,B),watch=True);self.end(g);self.assertIsNotNone(g.state.pending_choice)
        self.fault(g);g=self.portable(g);self.finish(g);self.assertEqual(self.unit(g,B).health,14);self.portable(g)

    def test_AFK_canceled_before_combat_remains_unattacked_under_local_policy(self):
        g=self.game(board=(LOTHAR,AFK),enemy=(TINY,),watch=True);self.end(g)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g,'retreat');self.finish(g)
        self.assertIsNone(g.state.character_attack_history[-1].combat)
        self.assertEqual(self.unit(g,LOTHAR).attack,9);self.assertEqual(self.unit(g,AFK).attack,0);self.portable(g)

    def test_Maw_own_end_gains_five_then_own_start_spends_five_and_gains_health(self):
        g=self.game(board=(MAW,));self.end(g);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],5)
        self.assertEqual(self.health(g),(30,30));self.end(g)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0);self.assertEqual(self.health(g),(35,35))

    def test_Maw_insufficient_balance_does_not_partially_spend_and_threshold_exact(self):
        # An ordinary test effect consumes the preceding real end's five Corpses.
        # The genuine turn-start body therefore sees exactly0 or4, without state edits.
        for balance in(0,4):
            g=self.game(board=(MAW,),corpses=balance,enemy_hand=(DRAIN,));self.end(g);self.play(g,DRAIN,player=2)
            self.assertEqual(g.state.players[1].resources[Resource.CORPSES],balance);self.end(g)
            self.assertEqual(g.state.players[1].resources[Resource.CORPSES],balance);self.assertEqual(self.health(g),(30,30))
        # Exact real start balances5 and9 follow one ordinary end gain.
        for balance in(0,4):
            g=self.game(board=(MAW,),corpses=balance);self.end(g);self.end(g)
            self.assertEqual(g.state.players[1].resources[Resource.CORPSES],balance);self.assertEqual(self.health(g),(35,35))

    def test_Maw_hero_health_gain_preserves_missing_health_not_heal(self):
        g=self.game((WOUND,),board=(MAW,));self.play(g,WOUND);self.assertEqual(self.health(g),(23,30));before=len(g.state.hero_health_change_history)
        self.end(g);self.end(g);self.assertEqual(self.health(g),(28,35));self.assertEqual(len(g.state.hero_health_change_history),before+1)

    def test_Maw_silenced_or_removed_before_start_has_no_spend(self):
        for remove in(HUSH,KILL):
            g=self.game(board=(MAW,),enemy_hand=(remove,));sid=self.unit(g,MAW).id;self.end(g)
            self.play(g,remove,sid,2);before=g.state.players[1].resources[Resource.CORPSES];self.end(g)
            self.assertEqual(g.state.players[1].resources[Resource.CORPSES],before);self.assertEqual(self.health(g),(30,30))

    def test_Maw_payment_wait_survives_original_source_death_and_restores(self):
        g=self.game(board=(MAW,),watch=True);self.end(g);self.end(g)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g)
        self.assertEqual(self.health(g),(35,35));self.assertEqual(self.bodies(g,MAW),[]);self.portable(g)

    def test_Lothar_forced_end_attack_kill_grows_and_records_actual_window(self):
        g=self.game(board=(LOTHAR,),enemy=(TINY,));sid=self.unit(g,LOTHAR).id;self.end(g)
        self.assertEqual((g.state.entities[sid].attack,g.state.entities[sid].health),(10,9))
        row=g.state.character_attack_history[-1];self.assertTrue(row.declaration.forced);self.assertEqual(row.terminal.status,'completed')
        self.assertEqual(g.state.entities[sid].attacks_this_turn,0);self.assertEqual(self.bodies(g,TINY,2),[])

    def test_Lothar_nonlethal_or_source_dies_or_empty_has_no_growth(self):
        g=self.game(board=(LOTHAR,),enemy=(B,));self.end(g);self.assertEqual(self.unit(g,LOTHAR).attack,7)
        g=self.game(board=(LOTHAR,),enemy=(HUGE,));sid=self.unit(g,LOTHAR).id;self.end(g)
        self.assertEqual(g.state.entities[sid].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[sid].attack,7)
        g=self.game(board=(LOTHAR,),enemy=(SLEEP,));rng=g._rng.getstate();self.end(g);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(g.state.character_attack_history,[])

    def test_Lothar_normal_or_unrelated_forced_kill_does_not_grow(self):
        for force in(False,True):
            g=self.game((FORCE,),board=(LOTHAR,),enemy=(TINY,));sid=self.unit(g,LOTHAR).id
            if force:self.play(g,FORCE,sid)
            else:g.apply(Attack(1,sid,self.unit(g,TINY,2).id))
            self.assertEqual(g.state.entities[sid].attack,7);self.end(g);self.assertEqual(g.state.entities[sid].attack,7)

    def test_Lothar_shield_prevents_kill_and_poison_fatal_combat_counts(self):
        g=self.game(board=(LOTHAR,),enemy=(B,),enemy_hand=(SHIELD,));self.end(g);self.play(g,SHIELD,self.unit(g,B,2).id,2)
        self.end(g);self.end(g);self.assertEqual(self.unit(g,LOTHAR).attack,7)
        g=self.game((POISON_GRANT,),board=(LOTHAR,),enemy=(B,));self.play(g,POISON_GRANT,self.unit(g,LOTHAR).id)
        self.end(g);self.assertEqual(self.unit(g,LOTHAR).attack,10);self.assertEqual(self.bodies(g,B,2),[])

    def test_Lothar_attack_declaration_wait_independent_restore_and_kill_reward(self):
        g=self.game(board=(LOTHAR,),enemy=(TINY,),watch=True);sid=self.unit(g,LOTHAR).id;self.end(g)
        self.assertIsNotNone(g.state.pending_choice);row=g.state.character_attack_history[-1]
        self.assertIsNone(row.terminal);ref=MinionReference.capture(g.state.entities[sid])
        GrowAfterOriginalForcedAttack(row.declaration.id,ref).validate_in_state(g.state,g.registry)
        with self.assertRaises(ValueError):GrowAfterOriginalForcedAttack(row.declaration.id,replace(ref,card_id=A)).validate_in_state(g.state,g.registry)
        self.fault(g);g=self.portable(g);self.finish(g);self.assertEqual(self.unit(g,LOTHAR).attack,10);self.portable(g)

    def test_Lothar_pending_attack_source_removed_cancels_without_reward(self):
        g=self.game(board=(LOTHAR,),enemy=(TINY,),watch=True);sid=self.unit(g,LOTHAR).id;self.end(g)
        g=self.portable(g);self.choose(g,'remove');self.finish(g)
        self.assertEqual(g.state.entities[sid].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[sid].attack,7)
        self.assertEqual(len(self.bodies(g,TINY,2)),1);self.portable(g)

    def test_Lothar_reward_rejects_a_manual_attack_window(self):
        g=self.game(board=(LOTHAR,),enemy=(B,));sid=self.unit(g,LOTHAR).id;g.apply(Attack(1,sid,self.unit(g,B,2).id))
        with self.assertRaises(ValueError):GrowAfterOriginalForcedAttack(g.state.character_attack_history[-1].declaration.id,
            MinionReference.capture(g.state.entities[sid])).validate_in_state(g.state,g.registry)


if __name__=='__main__':unittest.main()
