"""Real ending recipes keep natural scopes, current domains and shared continuations."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import past_legendary_end_recipes as native,past_legendary_named_bodies as earlier
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,GrantKeyword,
    InvokeBehavior,RandomDamage,RequestChoice,Silence,Transform)
from hs_sim.engine.hand_keywords import GrantStoredKeyword
from hs_sim.engine.model import (CardDefinition,CardType,EndTurnRepeatSpec,Keyword,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError,canonical_digest

DREAD,REPRINT,GEDDON,RAG,GRUUL,HOGGER,MOROES,SHUMA,ONYXIA,LIGHT,DARKHAN,ARM=native.ROOTS
GNOLL,STEWARD,TENTACLE=native.DEPENDENCIES;WHELP='ds1_whelptoken'
P='k685.';A=P+'plain';TAUNT=P+'taunt';DORMANT=P+'dormant';POWER=P+'power';SHIELD=P+'shield';LOCATION=P+'location'
KILL=P+'kill';HUSH=P+'hush';TAKE=P+'take';TURN=P+'turn';COPY=P+'copy';HURT=P+'hurt';BIG=P+'big';NEAR=P+'near'
GRANT=P+'grant';IMMUNE=P+'immune';WATCH=P+'watch';DMGWATCH=P+'dmgwatch';FAIL=P+'fail';NOOP=P+'noop';DOUBLE=P+'double'


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=opening_registry();d=native.load_batch();card=earlier.make_definition(d['existing_dependencies'][0]['record'])
    r.register_card(card);r.register_pool_card(PoolCard.from_definition(card));native.register_past_legendary_end_recipes(r)
    for cid,attack,keys,dormant,power in((A,1,(),0,0),(TAUNT,2,(Keyword.TAUNT,),0,0),
            (DORMANT,1,(),3,0),(POWER,1,(),0,9),(SHIELD,1,(Keyword.DIVINE_SHIELD,),0,0)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=40,keywords=keys,
            dormant_turns=dormant,spell_damage=power,metadata=metadata(collectible=False)))
    r.register_behavior(NOOP,lambda c:())
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,durability=2,on_use=NOOP,metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=40,
        end_turn_repeats=(EndTurnRepeatSpec(2),),metadata=metadata(collectible=False)))
    board=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),
        TAKE:lambda c:(ChangeControl(c.target_id,3-c.player_id),),TURN:lambda c:(Transform(c.target_id,A),),
        COPY:lambda c:(CopyMinion(c.target_id,c.player_id,cause=SummonCause.capture(c)),),
        HURT:lambda c:(Damage(c.target_id,3,c.source_id),),BIG:lambda c:(Damage(c.target_id,12,c.source_id),),
        NEAR:lambda c:(Damage(c.target_id,28,c.source_id),),GRANT:lambda c:(GrantStoredKeyword(CardReference.capture(c.state.entities[c.target_id]),Keyword.TAUNT,c.source_id),),
        IMMUNE:lambda c:(GrantKeyword(c.target_id,Keyword.IMMUNE,c.source_id),)}
    for cid,body in bodies.items():
        targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')if cid==GRANT else TargetSpec()if cid in(HURT,BIG,NEAR,IMMUNE)else board
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=targeting,metadata=metadata(collectible=False)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K685 deliberate end-body rollback')))
    def watch(c):
        event=c.event
        if event.kind=='minion_summoned':
            if c.state.entities[event.target_id].card_id not in(GNOLL,TENTACLE):return()
            tail=(ChoiceOption('kill','Destroy this token',(Destroy(event.target_id,c.source_id),)),)
        else:
            source=c.state.entities.get(event.source_id)
            if source is None or source.card_id!=RAG:return()
            tail=()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),*tail,ChoiceOption('fault','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    for cid,event in((WATCH,'minion_summoned'),(DMGWATCH,'damage_dealt')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=40,triggers=(TriggerSpec(event,WATCH),),metadata=metadata(collectible=False)))
    r.validate();return r


class PastLegendaryEndTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),player=1):
        self.mode='small'
        return Game.from_scenario(Scenario(tuple(PlayerSetup('mage.hero'if p==1 else'warrior.hero',
            hand=hand if p==player else enemy_hand,board=board if p==player else enemy,
            deck=('card.1',)*20,mana=40,max_mana=40,mana_cap=40)for p in(1,2)),active_player=player,seed=685),fixture('writer'))
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def board(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].board]
    def end(self,g):g.apply(EndTurn(g.state.active_player))

    def test_full_original_rows_roles_links_and_fifteen_complete_definition_pins(self):
        d=native.load_batch();r=fixture();self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['official_observations'])),(12,3,28))
        self.assertEqual(len(d['original_candidate_ids']),732);self.assertFalse(d['complete_past_legendary_source_bound'])
        for row in d['cards']+d['dependencies']:
            cid=row['record']['id'];self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(r.pool_card(cid))),row['pool_card_sha256'])
        with patch.object(native,'BATCH_HASH',''):
            with self.assertRaises(TargetValidationError):native.load_batch()

    def test_all_fifteen_faces_have_paid_entry_and_do_not_run_ending_body_early(self):
        for cid in(*native.ROOTS,*native.DEPENDENCIES):
            with self.subTest(card=cid):
                g=self.game((cid,));self.play(g,cid);e=self.unit(g,cid);c=g.registry.card(cid)
                self.assertEqual((e.attack,e.health),(c.attack,c.health));self.assertEqual(g.state.players[1].mana,40-c.cost)
                self.assertEqual(self.board(g),[cid]);self.assertEqual(self.hero(g,2).health,30)

    def test_dreadscale_both_real_identities_hit_all_enemies_and_ignore_spell_damage(self):
        for cid in(DREAD,REPRINT):
            g=self.game(board=(cid,A,POWER),enemy=(A,SHIELD,DORMANT,LOCATION));self.end(g)
            self.assertEqual((self.hero(g).health,self.hero(g,2).health,self.unit(g,A).health,self.unit(g,A,2).health),(30,29,40,39))
            self.assertEqual(self.unit(g,DORMANT,2).health,40);self.assertNotIn(Keyword.DIVINE_SHIELD,self.unit(g,SHIELD,2).keywords)
            self.assertEqual(self.unit(g,SHIELD,2).health,40)
        self.portable(g)

    def test_geddon_excludes_only_his_physical_source_and_preserves_ordinary_protection(self):
        g=self.game(board=(GEDDON,A,POWER),enemy=(A,SHIELD,DORMANT,LOCATION));self.end(g)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health,self.unit(g,GEDDON).health),(28,28,7))
        self.assertEqual((self.unit(g,A).health,self.unit(g,A,2).health,self.unit(g,SHIELD,2).health,self.unit(g,DORMANT,2).health),(38,38,40,40));self.portable(g)

    def test_geddon_simultaneous_hero_lethals_finish_both_health_packets(self):
        g=self.game((NEAR,NEAR),board=(GEDDON,));self.play(g,NEAR,self.hero(g).id);self.play(g,NEAR,self.hero(g,2).id);self.end(g)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(0,0));self.assertNotEqual(g.state.status,'playing');self.portable(g)

    def test_own_end_recipes_do_not_fire_at_opponent_end(self):
        g=self.game(board=(DARKHAN,),player=2);self.end(g);self.assertEqual(self.hero(g,1).health,24)
        self.end(g);self.assertEqual(self.hero(g,1).health,24);self.portable(g)

    def test_ragnaros_cannot_attack_until_silence_removes_original_policy(self):
        g=self.game((HUSH,),board=(RAG,));sid=self.unit(g,RAG).id;saved=deepcopy(g.snapshot())
        with self.assertRaises(IllegalAction):g.apply(Attack(1,sid,self.hero(g,2).id))
        self.assertEqual(g.snapshot(),saved);self.play(g,HUSH,sid);g.apply(Attack(1,sid,self.hero(g,2).id))
        self.assertEqual(self.hero(g,2).health,22);self.end(g);self.assertEqual(self.hero(g,2).health,22);self.portable(g)

    def test_ragnaros_random_eight_uses_only_enemy_characters_without_spell_bonus(self):
        g=self.game(board=(RAG,A,POWER),enemy=(A,DORMANT,LOCATION));before=self.hero(g,2).health+self.unit(g,A,2).health
        self.end(g);self.assertEqual(before-self.hero(g,2).health-self.unit(g,A,2).health,8)
        self.assertEqual((self.hero(g).health,self.unit(g,A).health,self.unit(g,DORMANT,2).health),(30,40,40));self.portable(g)

    def test_gruul_grows_once_at_each_players_actual_end(self):
        g=self.game(board=(GRUUL,));self.end(g);self.assertEqual((self.unit(g,GRUUL).attack,self.unit(g,GRUUL).health),(8,8))
        self.end(g);self.assertEqual((self.unit(g,GRUUL).attack,self.unit(g,GRUUL).health),(9,9));self.portable(g)

    def test_hogger_summons_actual_two_two_taunt_only_at_owner_end(self):
        g=self.game(board=(HOGGER,));self.end(g);e=self.unit(g,GNOLL);self.assertEqual((e.attack,e.health),(2,2));self.assertIn(Keyword.TAUNT,e.keywords)
        self.end(g);self.assertEqual(self.board(g).count(GNOLL),1);self.portable(g)

    def test_moroes_keeps_original_stealth_and_summons_real_one_one_steward(self):
        g=self.game(board=(MOROES,));self.assertIn(Keyword.STEALTH,self.unit(g,MOROES).keywords);self.end(g)
        e=self.unit(g,STEWARD);self.assertEqual((e.attack,e.health),(1,1));self.portable(g)

    def test_shuma_fills_actual_remaining_capacity_counting_dormant_and_location(self):
        g=self.game(board=(SHUMA,A,DORMANT,LOCATION));old=g.snapshot()['rng_state'];self.end(g)
        self.assertEqual(self.board(g).count(TENTACLE),3);self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(g.snapshot()['rng_state'],old);self.portable(g)

    def test_broodmother_fills_with_existing_onyxia_whelps_at_either_players_end(self):
        g=self.game(board=(ONYXIA,),enemy_hand=(KILL,));self.end(g);self.assertEqual(self.board(g).count(WHELP),6)
        self.play(g,KILL,self.unit(g,WHELP).id,2);self.assertEqual(self.board(g).count(WHELP),5);self.end(g)
        self.assertEqual(self.board(g).count(WHELP),6);self.assertNotIn('EX1_116t',self.board(g));self.portable(g)

    def test_full_board_named_end_summon_or_fill_allocates_nothing_and_uses_no_rng(self):
        for cid in(HOGGER,MOROES,SHUMA,ONYXIA):
            g=self.game(board=(cid,)+(A,)*6);before=tuple(g.state.players[1].board);entities=len(g.state.entities);rng=g.snapshot()['rng_state'];self.end(g)
            self.assertEqual(tuple(g.state.players[1].board),before);self.assertEqual(len(g.state.entities),entities);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_lightlord_restores_exact_eight_to_only_injured_friendly_hero(self):
        g=self.game((BIG,),board=(LIGHT,));self.play(g,BIG,self.hero(g).id);self.end(g)
        self.assertEqual(self.hero(g).health,26);self.assertEqual(self.hero(g,2).health,30);self.portable(g)

    def test_lightlord_selects_one_current_injured_friendly_character(self):
        g=self.game((BIG,BIG,BIG),board=(LIGHT,A,DORMANT),enemy=(A,));self.play(g,BIG,self.hero(g).id)
        self.play(g,BIG,self.unit(g,A).id);self.play(g,BIG,self.unit(g,A,2).id)
        before=(self.hero(g).health,self.unit(g,A).health);self.end(g);after=(self.hero(g).health,self.unit(g,A).health)
        self.assertCountEqual([z-a for a,z in zip(before,after)],[0,8]);self.assertEqual(self.unit(g,A,2).health,28)
        self.assertEqual(self.unit(g,DORMANT).health,40);self.portable(g)

    def test_lightlord_full_health_domain_uses_no_rng(self):
        g=self.game(board=(LIGHT,A));old=g.snapshot()['rng_state'];self.end(g)
        self.assertEqual(g.snapshot()['rng_state'],old);self.assertEqual(self.hero(g).health,30)

    def test_darkhan_lifesteal_heals_actual_ability_damage_and_not_spell_damage(self):
        g=self.game((BIG,),board=(DARKHAN,POWER));self.play(g,BIG,self.hero(g).id);self.end(g)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(24,24));self.portable(g)

    def test_darkhan_immune_enemy_takes_zero_and_lifesteal_heals_zero(self):
        g=self.game((BIG,IMMUNE),board=(DARKHAN,));self.play(g,BIG,self.hero(g).id);self.play(g,IMMUNE,self.hero(g,2).id);self.end(g)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(18,30));self.portable(g)

    def test_armagedillo_buffs_current_taunt_hand_minions_not_board_or_plain_hand(self):
        g=self.game((TAUNT,A,KILL),board=(ARM,TAUNT));self.end(g)
        self.assertEqual((self.entity(g,TAUNT).attack,self.entity(g,TAUNT).health),(4,42))
        self.assertEqual((self.entity(g,A).attack,self.entity(g,A).health),(1,40))
        self.assertEqual((self.unit(g,ARM).attack,self.unit(g,ARM).health),(4,8));self.assertEqual(self.unit(g,TAUNT).health,40)
        self.assertNotIn('"stored_card_buffed"',json.dumps(g.player_events(2)));self.portable(g)

    def test_armagedillo_uses_actual_granted_hand_taunt_and_buff_survives_paid_entry(self):
        g=self.game((A,GRANT),board=(ARM,));eid=self.entity(g,A).id;self.play(g,GRANT,eid);self.end(g);self.end(g)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(3,42));self.play(g,A)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(3,42));self.portable(g)

    def test_silence_and_transform_remove_original_end_source(self):
        for action in(HUSH,TURN):
            g=self.game((action,),board=(HOGGER,));self.play(g,action,self.unit(g,HOGGER).id);self.end(g)
            self.assertNotIn(GNOLL,self.board(g))

    def test_control_move_rebinds_owner_end_and_named_recipient(self):
        g=self.game((TAKE,),board=(HOGGER,));self.play(g,TAKE,self.unit(g,HOGGER).id);self.end(g)
        self.assertNotIn(GNOLL,self.board(g,2));self.end(g);self.assertEqual(self.board(g,2).count(GNOLL),1);self.assertNotIn(GNOLL,self.board(g));self.portable(g)

    def test_current_copy_retains_real_end_body_and_has_independent_source(self):
        g=self.game((COPY,),board=(HOGGER,));self.play(g,COPY,self.unit(g,HOGGER).id);self.end(g)
        self.assertEqual((self.board(g).count(HOGGER),self.board(g).count(GNOLL)),(2,2));self.portable(g)

    def test_original_end_repeat_decl_runs_two_real_random_bodies_in_one_natural_end(self):
        g=self.game(board=(RAG,DOUBLE));self.end(g);self.assertEqual(self.hero(g,2).health,14)
        self.assertEqual(sum(e.kind=='turn_ended'for e in g.events),1);self.portable(g)

    def test_named_summon_end_wait_restores_and_failed_rng_choice_rolls_back(self):
        g=self.game(board=(HOGGER,WATCH));self.end(g);self.assertIsNotNone(g.state.pending_choice);self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertEqual(g.state.active_player,2);self.assertEqual(self.board(g).count(GNOLL),1);self.portable(g)

    def test_fill_end_wait_keeps_original_capacity_when_first_token_dies(self):
        g=self.game(board=(SHUMA,WATCH));self.end(g);self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g,'kill')
        waits=1
        while g.state.pending_choice is not None:self.choose(g);waits+=1
        self.assertEqual((waits,self.board(g).count(TENTACLE),len(g.state.players[1].board)),(5,4,6));self.portable(g)

    def test_random_damage_end_wait_keeps_accepted_result_through_restore_and_fault(self):
        g=self.game(board=(RAG,DMGWATCH),enemy=(A,));self.end(g);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertEqual(g.state.active_player,2);self.portable(g)

    def test_real_standard_host_paid_ragnaros_runs_real_end_body_and_keeps_source_unbound(self):
        self.mode='host';h=host('writer');g=Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=(RAG,),deck=('CORE_CS2_182',)*20,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*20,mana=10,max_mana=10)),seed=685,generation_context=h.context),h.registry)
        self.play(g,RAG);self.assertEqual(g.state.players[1].mana,2);self.end(g)
        self.assertEqual(self.hero(g,2).health,22);self.assertNotIn('MIS_701',h.registry.cards);self.portable(g)
