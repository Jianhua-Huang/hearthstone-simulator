"""Real five-root grant/transform entries and original hidden-hand lifecycles."""
from dataclasses import replace
from functools import lru_cache
import json,unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_native_grants_transforms as native
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayCard,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.effects import (Buff,ChangeControl,ChoiceOption,Destroy,Draw,GainArmor,GrantDeathrattle,
    GrantKeyword,InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,RevealHandCard,Silence,TriggerDeathrattles)
from hs_sim.engine.model import CardDefinition,CardType,Keyword,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import Registry
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format

SHANDO,HEAD,TALRITHA,ROTGILL,INVINCIBLE=native.ROOTS
P='k706.';A=P+'beast';B=P+'dragon';C=P+'plain';M=P+'mech';U=P+'undead';ALL=P+'all';DORMANT=P+'dormant';BOTH=P+'both';MDR=P+'death_mech'
KILL=P+'kill';BUFF=P+'buff';HUSH=P+'hush';RETURN=P+'return';STEAL=P+'steal';REVEAL=P+'reveal';DRAW=P+'draw';COPY=P+'copy';TRIGGER=P+'trigger'
QUEUE=P+'queued_hand';BAD=P+'bad_hand';BACK=P+'back';FAIL=P+'fault';GRANT=P+'grant_hand'
WAIT_HAND=P+'hand_wait';WAIT_GRANT=P+'grant_wait';WAIT_BOARD=P+'board_wait';WAIT_TOKEN=P+'token_wait';WAIT_TRANSFORM=P+'transform_wait'
HELPERS=(A,B,C,M,U,ALL,DORMANT,BOTH,MDR,KILL,BUFF,HUSH,RETURN,STEAL,REVEAL,DRAW,COPY,TRIGGER,QUEUE,BAD,GRANT,
    WAIT_HAND,WAIT_GRANT,WAIT_BOARD,WAIT_TOKEN,WAIT_TRANSFORM)


@lru_cache(None)
def host(role='writer'):
    h=build_cn37_local_pool_format();r=h.registry;meta=metadata(collectible=False)
    r.register_behavior(P+'bc',lambda c:(GainArmor(c.player_id,7),))
    r.register_behavior(P+'spawn',lambda c:tuple(SummonByCard(c.player_id,(SummonEntryMaterial(C),),SummonCause.capture(c))for _ in range(7)))
    for cid,tribes in((A,('beast',)),(B,('dragon',)),(C,()),(M,('mech',)),(U,('undead',)),(ALL,('all',)),
            (DORMANT,('mech',)),(BOTH,()),(MDR,('mech',))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=2,attack=4 if cid==A else 2,health=6,
            metadata=replace(meta,tribes=tribes),battlecry=P+'bc'if cid==A else None,
            dormant_turns=2 if cid==DORMANT else 0,choose_both=cid==BOTH,deathrattle=P+'spawn'if cid==MDR else None))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K706 intentional continuation failure')))
    r.register_behavior(BACK,lambda c:(MoveCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,Zone.HAND,source_id=c.source_id),))
    def hand_grant(c):
        e=c.state.entities[c.target_id]
        return(GrantDeathrattle(e.id,native.PREFIX+TALRITHA,c.source_id,stored_card=CardReference.capture(e)),)
    def copied(c):
        e=c.state.entities[c.target_id]
        return(CopyCard(CapturedCardCopyMaterial.capture(c.state,e),c.player_id,mode='current',source_id=c.source_id),)
    def failure(c):
        return ChoiceOption('fault','Fail after random draw',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))
    def queued(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==B)
        ref=CardReference.capture(e)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),failure(c),
            ChoiceOption('move','Move original',(MoveCard(ref,c.player_id,Zone.DECK,source_id=c.source_id),)),
            ChoiceOption('reenter','Leave and reenter',(
                MoveCard(ref,c.player_id,Zone.DECK,source_id=c.source_id),InvokeBehavior(BACK,c.source_id,c.player_id,e.id)))),c.source_id),
            GrantDeathrattle(e.id,native.PREFIX+TALRITHA,c.source_id,stored_card=ref))
    def bad(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==DRAW)
        return(GrantDeathrattle(e.id,native.PREFIX+TALRITHA,c.source_id,stored_card=CardReference.capture(e)),)
    def waiting(c):
        source=c.state.entities.get(c.event.source_id);target=c.state.entities.get(c.event.target_id)
        if c.event.kind=='stored_card_buffed'and(source is None or source.card_id!=TALRITHA):return()
        if c.event.kind=='stored_deathrattle_granted'and(target is None or target.card_id!=B):return()
        if c.event.kind=='ability_granted'and(source is None or source.card_id!=ROTGILL):return()
        if c.event.kind=='minion_summoned'and(source is None or source.card_id!=native.TOKEN):return()
        if c.event.kind=='transformed'and(target is None or target.card_id!=A):return()
        extra=()
        if c.event.kind=='stored_card_buffed':
            ref=CardReference.capture(target)
            extra=(ChoiceOption('move','Move original',(MoveCard(ref,c.player_id,Zone.DECK,source_id=c.source_id),)),)
        if c.event.kind=='ability_granted':
            later=next((i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==M),None)
            if later is not None:extra=(ChoiceOption('remove','Return later original',(ReturnToHand(later),)),)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),failure(c),*extra),c.source_id),)
    r.register_behavior(P+'wait',waiting)
    for cid,event in((WAIT_HAND,'stored_card_buffed'),(WAIT_GRANT,'stored_deathrattle_granted'),(WAIT_BOARD,'ability_granted'),
            (WAIT_TOKEN,'minion_summoned'),(WAIT_TRANSFORM,'transformed')):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=20,metadata=meta,triggers=(TriggerSpec(event,P+'wait'),)))
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),BUFF:lambda c:(Buff(c.target_id,2,3,c.source_id),GrantKeyword(c.target_id,Keyword.TAUNT,c.source_id)),
        HUSH:lambda c:(Silence(c.target_id),),RETURN:lambda c:(ReturnToHand(c.target_id),),
        STEAL:lambda c:(ChangeControl(c.target_id,c.player_id),),REVEAL:lambda c:(RevealHandCard(c.target_id),),
        DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),COPY:copied,TRIGGER:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        QUEUE:queued,BAD:bad,GRANT:hand_grant}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=0,on_play=cid,metadata=meta,
            targeting=None if cid in(DRAW,QUEUE,BAD)else TargetSpec(zones=(Zone.BOARD,Zone.HAND),kinds=(CardType.MINION,CardType.SPELL))))
    r.validate();return h


@lru_cache(None)
def fixture(role='writer'):
    full=host(role).registry;r=Registry('k706-past-native-grants-transforms-v1')
    for bid,body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):r.register_behavior(bid,body)
    r.register_target_predicate(full.target_predicate(native.BEAST_RULE))
    for cid in('HERO_08','HERO_08bp',*HELPERS):
        r.register_card(full.card(cid))
        if cid in full.pool_cards:r.register_pool_card(full.pool_card(cid))
    native.register_past_native_grants_transforms(r);r.validate();return r


class PastNativeGrantTransformTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),deck=(),enemy=(),enemy_hand=(),watch=None,real_host=False):
        self.mode='host'if real_host else'small';h=host('writer')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40,
            hero_power_card_id='HERO_08bp',weapon_card_id=watch),PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,mana=40,max_mana=40,mana_cap=40,
            hero_power_card_id='HERO_08bp')),seed=706,generation_context=h.context if real_host else None),h.registry if real_host else fixture('writer'))
    def board(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].board]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def dr(self,e):return[a for a in e.abilities if a.kind=='deathrattle']
    def shando(self,g,branch,target=None):
        eid=self.entity(g,SHANDO).id;g.apply(PlayCard(1,eid,target,branch_id=branch));return eid
    def own_start(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def fault(self,g):
        self.assertIsNotNone(g.state.pending_choice);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_full_original_faces_choice_roles_and_explicit_token_keywords(self):
        d=native.load_batch();r=fixture()
        self.assertEqual(len(d['official_observations']),14);self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(len(d['remaining_frontier_ids']),7)
        for row in d['cards']+d['dependencies']:self.assertEqual(r.card(row['record']['id']),native.make_definition(row['record']))
        for cid in native.CHOICES:self.assertTrue(r.card(cid).choice_only);self.assertNotIn(cid,r.pool_cards)
        self.assertEqual(r.card(native.TOKEN).keywords,(Keyword.CHARGE,Keyword.MEGA_WINDFURY))
        self.assertEqual([b.id for b in r.card(SHANDO).choose_one.branches],[native.BUFF_OPTION,native.COPY_OPTION])

    def test_all_five_actual_paid_hand_entries(self):
        for cid in native.ROOTS:
            with self.subTest(cid=cid):
                g=self.game((cid,));eid=self.shando(g,native.BUFF_OPTION)if cid==SHANDO else self.play(g,cid)
                self.assertEqual(g.state.entities[eid].card_id,cid);self.assertEqual(g.state.players[1].mana,40-g.registry.card(cid).cost)
                self.assertEqual(len(g.state.play_history),1)

    def test_shando_deck_branch_buffs_only_original_own_current_beasts_and_all(self):
        g=self.game((SHANDO,A),board=(A,),deck=(A,B,ALL,DRAW),enemy=(A,),enemy_hand=(A,))
        self.shando(g,native.BUFF_OPTION)
        self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].max_health)for i in g.state.players[1].deck[:3]],[(5,7),(2,6),(3,7)])
        self.assertEqual(self.entity(g,A).attack,4);self.assertEqual(self.unit(g,A).attack,4);self.assertEqual(self.unit(g,A,2).attack,4)

    def test_shando_copy_branch_uses_current_material_and_never_replays_battlecry(self):
        g=self.game((BUFF,SHANDO),board=(A,));target=self.unit(g,A).id;self.play(g,BUFF,target)
        source=self.shando(g,native.COPY_OPTION,target);e=g.state.entities[source]
        self.assertEqual((e.card_id,e.attack,e.max_health),(A,6,9));self.assertIn(Keyword.TAUNT,e.keywords)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.portable(g)

    def test_shando_invalid_enemy_nonbeast_and_unknown_branch_reject_before_payment(self):
        for branch,cid,p in((native.COPY_OPTION,A,2),(native.COPY_OPTION,C,1),('invented',A,1)):
            g=self.game((SHANDO,),board=(A,C),enemy=(A,));before=g.snapshot()
            with self.assertRaises(IllegalAction):self.shando(g,branch,self.unit(g,cid,p).id)
            self.assertEqual(g.snapshot(),before)

    def test_shando_no_available_beast_uses_original_optional_target_policy(self):
        g=self.game((SHANDO,),board=(C,));source=self.shando(g,native.COPY_OPTION)
        self.assertEqual(g.state.entities[source].card_id,SHANDO);self.assertEqual(self.board(g),[C,SHANDO])

    def test_shando_actual_choose_both_applies_deck_then_current_board_copy(self):
        g=self.game((SHANDO,),board=(BOTH,A),deck=(A,));source=self.shando(g,'both',self.unit(g,A).id)
        self.assertEqual((g.state.entities[source].card_id,g.state.entities[source].attack),(A,4))
        self.assertEqual(self.entity(g,A,zone='deck').attack,5);self.assertEqual(g.state.players[1].mana,37)

    def test_shando_transform_wait_restores_clone_replay_and_atomic_failure(self):
        g=self.game((SHANDO,),board=(A,),watch=WAIT_TRANSFORM);self.shando(g,native.COPY_OPTION,self.unit(g,A).id)
        g=self.portable(g);self.fault(g);self.finish(g);self.assertEqual(self.board(g),[A,A]);self.portable(g)

    def test_head_only_owner_start_destroys_all_mechs_and_keeps_original_position(self):
        g=self.game((HEAD,),board=(C,M,M,C),enemy=(M,));self.play(g,HEAD)
        rng=g._rng.getstate();g.apply(EndTurn(1));self.assertEqual(self.board(g).count(HEAD),1);self.assertEqual(g._rng.getstate(),rng)
        g.apply(EndTurn(2));self.assertEqual(self.board(g),[C,C,native.TOKEN]);self.assertEqual(self.board(g,2),[M])
        self.assertEqual(len([e for e in g.events if e.kind=='minion_died'and e.player_id==1]),3);self.portable(g)

    def test_head_uses_all_eligible_mechs_including_all_types_not_only_three(self):
        g=self.game(board=(HEAD,M,M,ALL));self.own_start(g)
        self.assertEqual(self.board(g),[native.TOKEN]);self.assertEqual(len([x for x in g.state.death_history if x.controller==1]),4)

    def test_head_less_than_three_or_dormant_mech_neither_destroys_nor_samples(self):
        for board in((HEAD,M),(HEAD,M,DORMANT)):
            g=self.game(board=board);rng=g._rng.getstate();self.own_start(g)
            self.assertEqual(self.board(g),list(board));self.assertEqual(g._rng.getstate(),rng)

    def test_head_silence_prevents_native_turn_start_body(self):
        g=self.game((HUSH,),board=(HEAD,M,M));self.play(g,HUSH,self.unit(g,HEAD).id);self.own_start(g)
        self.assertEqual(self.board(g),[HEAD,M,M])

    def test_head_death_reaction_capacity_is_respected_before_token_delivery(self):
        g=self.game(board=(C,HEAD,MDR,M));self.own_start(g)
        self.assertEqual(self.board(g),[C]*7);self.assertNotIn(native.TOKEN,self.board(g));self.portable(g)

    def test_real_token_has_immediate_four_attacks_and_fifth_is_atomic_rejection(self):
        g=self.game(board=(HEAD,M,M));self.own_start(g);source=self.unit(g,native.TOKEN).id;hero=g.state.players[2].hero_id
        initial_health=g.state.entities[hero].health
        for _ in range(4):g.apply(Attack(1,source,hero))
        self.assertEqual(g.state.entities[hero].health,initial_health-16);before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,source,hero))
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_head_token_delivery_wait_uses_original_death_group_and_resumes(self):
        g=self.game(board=(HEAD,M,M),watch=WAIT_TOKEN);self.own_start(g)
        g=self.portable(g);self.fault(g);self.finish(g);self.assertEqual(self.board(g),[native.TOKEN])

    def test_talritha_real_death_grants_hand_dragon_then_recurses_after_normal_play(self):
        g=self.game((KILL,KILL,B,ALL,C),board=(TALRITHA,));self.play(g,KILL,self.unit(g,TALRITHA).id)
        grown=[g.state.entities[i]for i in g.state.players[1].hand if self.dr(g.state.entities[i])]
        self.assertEqual(len(grown),1);first=grown[0];self.assertIn(first.card_id,(B,ALL));self.assertEqual((first.attack,first.max_health),(5,9))
        self.play(g,first.card_id);self.play(g,KILL,first.id)
        grown=[g.state.entities[i]for i in g.state.players[1].hand if self.dr(g.state.entities[i])]
        self.assertEqual(len(grown),1);self.assertEqual((grown[0].attack,grown[0].max_health),(5,9));self.assertEqual(self.entity(g,C).attack,2)
        self.portable(g)

    def test_talritha_no_current_dragon_neither_buffs_nor_samples(self):
        g=self.game((KILL,A,C,DRAW),board=(TALRITHA,));rng=g._rng.getstate();self.play(g,KILL,self.unit(g,TALRITHA).id)
        self.assertEqual(g._rng.getstate(),rng);self.assertFalse(any(self.dr(g.state.entities[i])for i in g.state.players[1].hand))

    def test_talritha_actual_death_actor_owns_selection_and_private_notification(self):
        g=self.game((KILL,B),enemy=(TALRITHA,),enemy_hand=(B,));self.play(g,KILL,self.unit(g,TALRITHA,2).id)
        self.assertEqual(self.entity(g,B).attack,2);self.assertEqual(self.entity(g,B,2).attack,5)
        self.assertNotIn('stored_deathrattle_granted',json.dumps(g.player_events(1)));self.assertIn('stored_deathrattle_granted',json.dumps(g.player_events(2)))

    def test_talritha_grant_is_private_even_after_original_identity_was_revealed(self):
        g=self.game((REVEAL,KILL,B),board=(TALRITHA,));self.play(g,REVEAL,self.entity(g,B).id);self.play(g,KILL,self.unit(g,TALRITHA).id)
        self.assertIn('stored_deathrattle_granted',json.dumps(g.player_events(1)))
        self.assertNotIn('stored_deathrattle_granted',json.dumps(g.player_events(2)));self.portable(g)

    def test_talritha_wait_between_buff_and_grant_restores_original_hand_reference(self):
        g=self.game((KILL,B),board=(TALRITHA,),watch=WAIT_HAND);self.play(g,KILL,self.unit(g,TALRITHA).id)
        self.assertEqual(self.entity(g,B).attack,5);self.assertEqual(self.dr(self.entity(g,B)),[])
        restored=self.portable(g);self.fault(g);self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(len(self.dr(self.entity(g,B))),1);self.portable(g)

    def test_talritha_buff_reaction_moving_original_skips_later_hand_grant(self):
        g=self.game((KILL,B),board=(TALRITHA,),watch=WAIT_HAND);self.play(g,KILL,self.unit(g,TALRITHA).id)
        g=self.portable(g);self.choose(g,'move');e=self.entity(g,B,zone='deck')
        self.assertEqual(e.attack,5);self.assertEqual(self.dr(e),[]);self.portable(g)

    def test_stored_grant_queued_before_wait_restores_and_rejects_reentered_original(self):
        for option,zone,count in(('continue','hand',1),('move','deck',0),('reenter','hand',0)):
            with self.subTest(option=option):
                g=self.game((QUEUE,B));self.play(g,QUEUE);restored=self.portable(g);self.fault(g)
                self.choose(g,option);self.choose(restored,option);self.assertEqual(g.snapshot(),restored.snapshot())
                self.assertEqual(len(self.dr(self.entity(g,B,zone=zone))),count)

    def test_stored_grant_wrong_original_printed_kind_is_atomic_failure(self):
        g=self.game((BAD,DRAW));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,BAD)
        self.assertEqual(g.snapshot(),before)

    def test_stored_grant_declaration_rejects_forged_identity_deck_expiry_and_memory(self):
        ref=CardReference(3,1,Zone.HAND,B,0);body=native.PREFIX+TALRITHA
        for create in(lambda:GrantDeathrattle(4,body,5,stored_card=ref),lambda:GrantDeathrattle(True,body,5,stored_card=ref),
                lambda:GrantDeathrattle(3,body,stored_card=ref),lambda:GrantDeathrattle(3,body,5,expires_turn=4,stored_card=ref),
                lambda:GrantDeathrattle(3,body,5,stored_card=replace(ref,zone=Zone.DECK)),
                lambda:GrantDeathrattle(3,body,5,stored_card='forged'),lambda:GrantDeathrattle(3,body,5,deathrattle_memory=object(),stored_card=ref)):
            with self.subTest(create=create),self.assertRaises(ValueError):create()

    def test_stored_hand_material_copies_fresh_attachments_and_retires_on_silence_or_return(self):
        g=self.game((KILL,COPY,B,HUSH,RETURN),board=(TALRITHA,));self.play(g,KILL,self.unit(g,TALRITHA).id)
        original=self.entity(g,B).id;self.play(g,COPY,original);cards=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==B]
        self.assertEqual(len(cards),2);self.assertEqual([e.attack for e in cards],[5,5]);self.assertNotEqual(self.dr(cards[0])[0].id,self.dr(cards[1])[0].id)
        self.play(g,B);self.play(g,HUSH,original);self.assertEqual(self.dr(g.state.entities[original]),[])
        self.play(g,RETURN,original);self.assertEqual(g.state.entities[original].attack,2);self.portable(g)

    def test_stored_grant_notification_wait_restores_installed_material_without_duplicate(self):
        g=self.game((GRANT,B),watch=WAIT_GRANT);self.play(g,GRANT,self.entity(g,B).id)
        self.assertEqual(len(self.dr(self.entity(g,B))),1);g=self.portable(g);self.fault(g);self.finish(g)
        self.assertEqual(len(self.dr(self.entity(g,B))),1);self.portable(g)

    def test_rotgill_grants_only_original_other_active_friends_then_buffs_current_team(self):
        g=self.game((ROTGILL,KILL,KILL,C),board=(A,M,DORMANT),enemy=(A,));source=self.play(g,ROTGILL)
        self.assertEqual(len(self.dr(self.unit(g,A))),1);self.assertEqual(len(self.dr(self.unit(g,M))),1)
        for e in(g.state.entities[source],self.unit(g,DORMANT),self.unit(g,A,2)):self.assertEqual(self.dr(e),[])
        later=self.play(g,C);self.assertEqual(self.dr(g.state.entities[later]),[]);self.play(g,KILL,self.unit(g,A).id)
        self.assertEqual((g.state.entities[source].attack,self.unit(g,M).attack,g.state.entities[later].attack),(4,3,3))
        self.play(g,KILL,self.unit(g,M).id);self.assertEqual(g.state.entities[source].attack,5);self.portable(g)

    def test_rotgill_grant_wait_skips_departed_later_original_without_rebinding(self):
        g=self.game((ROTGILL,),board=(A,M),watch=WAIT_BOARD);self.play(g,ROTGILL)
        g=self.portable(g);self.fault(g);self.choose(g,'remove');self.finish(g)
        self.assertEqual(self.dr(self.entity(g,M)),[]);self.assertEqual(len(self.dr(self.unit(g,A))),1);self.portable(g)

    def test_rotgill_granted_death_uses_current_controller_and_silence_retires_it(self):
        g=self.game((ROTGILL,HUSH,KILL),board=(A,M),enemy=(C,),enemy_hand=(STEAL,KILL));self.play(g,ROTGILL)
        self.play(g,HUSH,self.unit(g,M).id);self.assertEqual(self.dr(self.unit(g,M)),[])
        target=self.unit(g,A).id;g.apply(EndTurn(1));self.play(g,STEAL,target,player=2);self.play(g,KILL,target,player=2)
        self.assertEqual(self.unit(g,C,2).attack,3);self.assertEqual(self.unit(g,M).attack,2);self.portable(g)

    def test_invincible_real_battlecry_death_and_reborn_preserve_ordinary_semantics(self):
        g=self.game((INVINCIBLE,KILL),board=(U,),enemy=(U,));source=self.play(g,INVINCIBLE)
        self.assertEqual(self.unit(g,U).attack,7);self.assertIn(Keyword.TAUNT,self.unit(g,U).keywords)
        self.play(g,KILL,source);self.assertEqual(self.unit(g,U).attack,12);self.assertEqual(self.unit(g,U,2).attack,2)
        reborn=self.unit(g,INVINCIBLE);self.assertNotEqual(reborn.id,source);self.assertEqual((reborn.attack,reborn.health),(5,1))
        self.assertNotIn(Keyword.REBORN,reborn.keywords);self.portable(g)

    def test_invincible_current_all_types_qualify_but_self_and_empty_group_do_not(self):
        g=self.game((INVINCIBLE,),board=(ALL,C));self.play(g,INVINCIBLE)
        self.assertEqual(self.unit(g,ALL).attack,7);self.assertEqual(self.unit(g,C).attack,2)
        g=self.game((INVINCIBLE,KILL),board=(C,));rng=g._rng.getstate();source=self.play(g,INVINCIBLE);self.play(g,KILL,source)
        self.assertEqual(g._rng.getstate(),rng);self.assertEqual(self.unit(g,C).attack,2)

    def test_standard_host_actual_shando_talritha_and_token_entries(self):
        g=self.game((SHANDO,),board=(A,),real_host=True);self.shando(g,native.COPY_OPTION,self.unit(g,A).id);self.assertEqual(self.board(g),[A,A])
        g=self.game((KILL,B),board=(TALRITHA,),real_host=True);self.play(g,KILL,self.unit(g,TALRITHA).id)
        self.assertEqual(self.entity(g,B).attack,5);self.assertEqual(len(self.dr(self.entity(g,B))),1)
        g=self.game(board=(HEAD,M,M),real_host=True);self.own_start(g);self.assertEqual(self.board(g),[native.TOKEN])
