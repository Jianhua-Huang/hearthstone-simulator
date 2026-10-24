"""Real original Fan residence and Growfin summon/terminal derivative routes."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.past_source_bound_battlecries import (FAN,GROWFIN,TINYFIN,GIGANTIC,
    LIVE,load_batch,register_past_source_bound_battlecries)
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,
    EndTurn,Game,IllegalAction,Keyword,PlayerSetup,Registry,Scenario,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.attack_policies import current_policies
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,CopyMinion,
    Damage,Destroy,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.errors import ResolutionError,SnapshotError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import BattlecryRepeatSpec
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference
from tools import card_batch as batch

P='k490.'
HERO,POWER,A,B,WATCH,REPEAT=(P+x for x in ('hero','power','a','b','watch','repeat'))
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


def policies(e):return tuple(a for a in e.abilities if a.kind=='attack_policy')


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=Registry(P+mode);register_past_source_bound_battlecries(r)
    r.register_behavior(P+'empty',lambda c:())
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=100,initial_hero_power=POWER,metadata=META))
    r.register_card(CardDefinition(POWER,POWER,CardType.HERO_POWER,on_use=P+'empty',metadata=META))
    for cid,attack,health,extra in ((A,2,5,{}),(B,3,9,{}),
            (REPEAT,0,9,dict(battlecry_repeats=(BattlecryRepeatSpec(2),)))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=health,
            keywords=(Keyword.CHARGE,),metadata=META,**extra))
    def buff_hand(c):
        target=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==GROWFIN)
        return(BuffStoredCard(CardReference.capture(target),2,3,c.source_id),)
    bodies=dict(kill=lambda c:(Destroy(c.target_id,c.source_id),),
        silence=lambda c:(Silence(c.target_id),),bounce=lambda c:(ReturnToHand(c.target_id),),
        transform=lambda c:(Transform(c.target_id,A),),
        give=lambda c:(ChangeControl(c.target_id,3-c.state.entities[c.target_id].controller),),
        sleep=lambda c:(MakeDormant(c.target_id,2,c.source_id),),
        copy=lambda c:(CopyMinion(c.target_id,c.player_id),),
        base=lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        buff=lambda c:(Buff(c.target_id,2,3,c.source_id),),
        damage=lambda c:(Damage(c.target_id,2,c.source_id),),
        trigger=lambda c:(TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]),c.source_id),),
        self_trigger=lambda c:(TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]),
            c.source_id,target_id=c.target_id,targeting='explicit'),))
    for key,body in bodies.items():
        r.register_behavior(P+key,body);r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),metadata=META))
    for key,body in {'buff_hand':buff_hand,'summon_fan':lambda c:(Summon(c.player_id,FAN),),
            'summon_grow':lambda c:(Summon(c.player_id,GROWFIN),)}.items():
        r.register_behavior(P+key,body);r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,metadata=META))
    def fail(c):raise ResolutionError('K490 deliberate native delivery failure')
    r.register_behavior(P+'fail',fail)
    def watch(c):
        event=c.event;target=c.state.entities.get(event.target_id)
        if mode=='fill_hand' and event.kind=='minion_summoned' and target.card_id==GROWFIN:
            return(AddToHand(c.player_id,A,c.source_id),AddToHand(c.player_id,A,c.source_id))
        grant=event.kind=='ability_granted'and dict(event.data).get('ability_kind')=='attack_policy'
        tiny=event.kind=='minion_summoned'and target.card_id==TINYFIN
        child=event.kind=='card_added_to_hand'and target.card_id==GIGANTIC
        if mode=='grant_fail'and grant or mode=='tiny_fail'and tiny:
            return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if not(mode=='grant_wait'and grant or mode=='tiny_wait'and tiny or mode=='child_wait'and child):return ()
        options=(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',
            (InvokeBehavior(P+'fail',c.source_id,c.player_id),)))
        if grant:options=(*options,ChoiceOption('kill_source','Kill original source',(Destroy(event.source_id,c.source_id),)))
        return(RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
        triggers=tuple(TriggerSpec(e,WATCH)for e in ('ability_granted','minion_summoned','card_added_to_hand'))))
    r.validate();return r


class PastSourceBoundBattlecryTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)

    def game(self,hand=(),*,board=(),enemy=(),mode='normal',max_hand=40):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=tuple(hand),board=tuple(board),deck=(A,)*10,
            mana=40,max_mana=40,mana_cap=40),PlayerSetup(HERO,board=tuple(enemy),deck=(A,)*10,
            mana=40,max_mana=40,mana_cap=40)),seed=490),fixture(mode),Ruleset(max_hand=max_hand))

    def board(self,g,cid,player=1):return self.entity(g,cid,player,zone='board')
    def count(self,g,cid,player=1,zone='board'):
        return sum(g.state.entities[i].card_id==cid for i in getattr(g.state.players[player],zone))
    def blocked(self,g,eid):return any(p.mode=='cannot_attack'for p in current_policies(g.state,g.state.entities[eid],g.registry))
    def attacks(self,g,eid):return[a for a in g.legal_actions()if isinstance(a,Attack)and a.attacker_id==eid]

    def portable(self,g):
        other=super().portable(g)
        for player in (1,2):
            view=json.dumps(g.for_player(player).observe())+json.dumps(g.for_player(player).legal_actions())+json.dumps(g.player_events(player))
            for key in ('attack_source_binding','board_presence_id','captured_zone_epoch'):
                self.assertNotIn('"'+key+'"',view)
        return other

    def test_complete_four_raw_rows_eight_primary_faces_and_actual_child_links(self):
        d=load_batch();rows={x['record']['id']:x['record']for x in d['dependencies']}
        self.assertEqual(tuple(rows),(FAN,GROWFIN,TINYFIN,GIGANTIC));self.assertEqual(len(d['official_observations']),8)
        for o in d['official_observations']:
            self.assertEqual(batch.sha(o['response_file']),o['response_sha256'])
            batch.check_face(rows[o['card_id']],o['face'],o['locale'])
            if o['card_id']==GROWFIN:self.assertEqual(o['face']['childIds'],[rows[TINYFIN]['dbf_id'],rows[GIGANTIC]['dbf_id']])
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_actual_constructed_registration_adds_only_four_complete_faces(self):
        from hs_sim.cards import build_registry
        r=batch.registration_prefix(build_registry,
            'hs_sim.cards.past_source_bound_battlecries.register_past_source_bound_battlecries',
            register_past_source_bound_battlecries,after=True)
        self.assertEqual(len(r.cards),2688)
        for cid in(FAN,GROWFIN,TINYFIN,GIGANTIC):self.assertEqual(r.card(cid),fixture().card(cid))

    def test_paid_fan_targets_friendly_minion_and_blocks_actual_voluntary_attack(self):
        g=self.game((FAN,),board=(A,),enemy=(B,));target=self.board(g,A).id
        self.assertTrue(self.attacks(g,target));source=self.play(g,FAN,target)
        self.assertTrue(self.blocked(g,target));self.assertFalse(self.attacks(g,target))
        saved=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,target,self.board(g,B,2).id))
        self.assertEqual(g.snapshot(),saved);self.assertEqual(g.state.players[1].mana,39)
        binding=policies(g.state.entities[target])[0].attack_source_binding
        self.assertEqual(binding.reference.entity_id,source);self.assertEqual(binding.policy,LIVE);self.portable(g)

    def test_paid_fan_can_choose_enemy_and_enemy_turn_stays_blocked(self):
        g=self.game((FAN,),enemy=(B,));target=self.board(g,B,2).id
        self.play(g,FAN,target);g.apply(EndTurn(1));self.assertTrue(self.blocked(g,target))
        self.assertFalse(self.attacks(g,target));self.portable(g)

    def test_source_death_releases_target_immediately(self):
        g=self.game((FAN,P+'kill'),board=(A,),enemy=(B,));target=self.board(g,A).id
        source=self.play(g,FAN,target);self.play(g,P+'kill',source)
        self.assertFalse(self.blocked(g,target));self.assertTrue(self.attacks(g,target));self.portable(g)

    def test_source_silence_and_transform_keep_original_live_presence_policy(self):
        for key in ('silence','transform'):
            with self.subTest(key=key):
                g=self.game((FAN,P+key),board=(A,));target=self.board(g,A).id
                source=self.play(g,FAN,target);presence=g.state.entities[source].board_presence_id
                self.play(g,P+key,source);self.assertEqual(g.state.entities[source].board_presence_id,presence)
                self.assertTrue(self.blocked(g,target));self.portable(g)

    def test_original_source_control_and_dormancy_keep_live_binding(self):
        for key in ('give','sleep'):
            with self.subTest(key=key):
                g=self.game((FAN,P+key),board=(A,));target=self.board(g,A).id
                source=self.play(g,FAN,target);self.play(g,P+key,source)
                self.assertTrue(self.blocked(g,target));self.portable(g)

    def test_source_bounce_and_reentry_do_not_reactivate_old_target_link(self):
        g=self.game((FAN,P+'bounce'),board=(A,B));first=self.board(g,A).id;second=self.board(g,B).id
        source=self.play(g,FAN,first);old=g.state.entities[source].board_presence_id
        self.play(g,P+'bounce',source);self.assertFalse(self.blocked(g,first))
        self.assertEqual(self.play(g,FAN,second),source)
        self.assertNotEqual(g.state.entities[source].board_presence_id,old)
        self.assertFalse(self.blocked(g,first));self.assertTrue(self.blocked(g,second));self.portable(g)

    def test_target_silence_transform_and_bounce_remove_its_attachment(self):
        for key in ('silence','transform','bounce'):
            with self.subTest(key=key):
                g=self.game((FAN,P+key),board=(B,));target=self.board(g,B).id
                self.play(g,FAN,target);self.play(g,P+key,target)
                self.assertFalse(policies(g.state.entities[target]));self.portable(g)

    def test_current_target_copy_keeps_original_source_and_base_copy_drops_link(self):
        g=self.game((FAN,P+'copy',P+'base'),board=(A,));target=self.board(g,A).id;source=self.play(g,FAN,target)
        self.play(g,P+'copy',target);copied=g.state.entities[g.state.players[1].board[-1]]
        self.assertTrue(self.blocked(g,copied.id));self.assertEqual(policies(copied)[0].source_id,source)
        self.play(g,P+'base',target);self.assertFalse(policies(g.state.entities[g.state.players[1].board[-1]]));self.portable(g)

    def test_two_fans_have_independent_links_and_both_must_depart(self):
        g=self.game((FAN,FAN,P+'kill',P+'kill'),board=(A,));target=self.board(g,A).id
        first=self.play(g,FAN,target);second=self.play(g,FAN,target)
        self.assertEqual(len(policies(g.state.entities[target])),2)
        self.play(g,P+'kill',first);self.assertTrue(self.blocked(g,target))
        self.play(g,P+'kill',second);self.assertFalse(self.blocked(g,target));self.portable(g)

    def test_summoned_fan_has_no_battlecry_link(self):
        g=self.game((P+'summon_fan',),board=(A,));self.play(g,P+'summon_fan')
        self.assertFalse(self.blocked(g,self.board(g,A).id));self.assertFalse(g.state.battlecry_history);self.portable(g)

    def test_no_available_target_allows_plain_fan_entry(self):
        g=self.game((FAN,));source=self.play(g,FAN)
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.assertFalse(policies(g.state.entities[source]));self.portable(g)

    def test_missing_when_available_and_hero_targets_reject_before_payment(self):
        g=self.game((FAN,),board=(A,));saved=g.snapshot()
        for target in (None,g.state.players[2].hero_id):
            with self.subTest(target=target),self.assertRaises(IllegalAction):self.play(g,FAN,target)
            self.assertEqual(g.snapshot(),saved)

    def test_existing_indirect_fan_battlecry_can_choose_its_own_live_body(self):
        g=self.game((P+'self_trigger',),board=(FAN,));source=self.board(g,FAN).id
        self.play(g,P+'self_trigger',source);self.assertTrue(self.blocked(g,source))
        self.assertEqual(policies(g.state.entities[source])[0].source_id,source);self.portable(g)

    def test_grant_wait_restores_then_original_source_death_releases_link(self):
        g=self.game((FAN,),board=(A,WATCH),mode='grant_wait');target=self.board(g,A).id
        self.play(g,FAN,target);self.assertTrue(self.blocked(g,target));other=self.portable(g)
        self.choose(g,'kill_source');self.choose(other,'kill_source');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertFalse(self.blocked(g,target));self.portable(g)

    def test_grant_failure_rolls_back_entire_paid_fan(self):
        g=self.game((FAN,),board=(A,WATCH),mode='grant_fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,FAN,self.board(g,A).id)
        self.assertEqual(g.snapshot(),saved);self.portable(g)

    def test_paid_growfin_creates_native_rush_tinyfin_and_one_printed_gigantic(self):
        g=self.game((GROWFIN,),enemy=(B,));source=self.play(g,GROWFIN);tiny=self.board(g,TINYFIN)
        self.assertEqual((tiny.attack,tiny.max_health,tiny.damage),(1,1,0));self.assertIn(Keyword.RUSH,tiny.keywords)
        self.assertTrue(self.attacks(g,tiny.id));self.assertTrue(all(a.defender_id!=g.state.players[2].hero_id for a in self.attacks(g,tiny.id)))
        child=self.entity(g,GIGANTIC);self.assertEqual((child.base_cost,child.attack,child.max_health),(8,8,8))
        self.assertEqual(child.origin_entity_id,source);self.assertEqual(self.count(g,GIGANTIC,zone='hand'),1);self.portable(g)

    def test_hand_buffs_feed_tinyfin_but_do_not_inherit_into_gigantic(self):
        g=self.game((GROWFIN,P+'buff_hand'));self.play(g,P+'buff_hand');self.play(g,GROWFIN)
        tiny=self.board(g,TINYFIN);child=self.entity(g,GIGANTIC)
        self.assertEqual((tiny.attack,tiny.max_health),(3,4));self.assertEqual((child.attack,child.max_health),(8,8));self.portable(g)

    def test_actual_gigantic_play_summons_eight_eight_without_another_derivative(self):
        g=self.game((GIGANTIC,));self.play(g,GIGANTIC);tiny=self.board(g,TINYFIN)
        self.assertEqual((tiny.attack,tiny.max_health),(8,8));self.assertIn(Keyword.RUSH,tiny.keywords)
        self.assertEqual(self.count(g,GIGANTIC,zone='hand'),0);self.assertEqual(g.state.players[1].mana,32);self.portable(g)

    def test_indirect_wounded_current_stats_summon_does_not_generate_hand_derivative(self):
        g=self.game((P+'buff',P+'damage',P+'trigger'),board=(GROWFIN,));source=self.board(g,GROWFIN).id
        self.play(g,P+'buff',source);self.play(g,P+'damage',source);self.play(g,P+'trigger',source)
        tiny=self.board(g,TINYFIN);self.assertEqual((tiny.attack,tiny.max_health,tiny.damage),(3,2,0))
        self.assertEqual(g.state.entities[source].damage,2);self.assertEqual(self.count(g,GIGANTIC,zone='hand'),0);self.portable(g)

    def test_summoned_root_does_not_run_battlecry_or_generate_gigantic(self):
        g=self.game((P+'summon_grow',));self.play(g,P+'summon_grow')
        self.assertEqual(self.count(g,GROWFIN),1);self.assertEqual(self.count(g,TINYFIN),0)
        self.assertEqual(self.count(g,GIGANTIC,zone='hand'),0);self.portable(g)

    def test_last_board_slot_skips_tinyfin_but_still_delivers_one_gigantic(self):
        g=self.game((GROWFIN,),board=(A,)*6);self.play(g,GROWFIN)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(self.count(g,TINYFIN),0)
        self.assertEqual(self.count(g,GIGANTIC,zone='hand'),1);self.portable(g)

    def test_repeated_battlecry_summons_two_tinyfins_and_only_one_hand_derivative(self):
        g=self.game((GROWFIN,),board=(REPEAT,));self.play(g,GROWFIN)
        self.assertEqual(self.count(g,TINYFIN),2);self.assertEqual(self.count(g,GIGANTIC,zone='hand'),1)
        self.assertEqual(len(g.state.battlecry_history),2);self.portable(g)

    def test_full_hand_uses_original_created_overflow_for_gigantic(self):
        g=self.game((GROWFIN,),board=(WATCH,),mode='fill_hand',max_hand=2);self.play(g,GROWFIN)
        self.assertEqual(len(g.state.players[1].hand),2);self.assertEqual(self.count(g,GIGANTIC,zone='hand'),0)
        lost=[e for e in g.state.entities.values()if e.card_id==GIGANTIC]
        self.assertEqual(len(lost),1);self.assertEqual(lost[0].zone,Zone.GRAVEYARD);self.portable(g)

    def test_tinyfin_wait_precedes_exactly_once_gigantic_delivery(self):
        g=self.game((GROWFIN,),board=(WATCH,),mode='tiny_wait');self.play(g,GROWFIN)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.count(g,GIGANTIC,zone='hand'),0)
        other=self.portable(g);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(self.count(g,GIGANTIC,zone='hand'),1);self.portable(g)

    def test_gigantic_delivery_wait_late_failure_restores_once_only_child(self):
        g=self.game((GROWFIN,),board=(WATCH,),mode='child_wait');self.play(g,GROWFIN)
        self.assertEqual(self.count(g,GIGANTIC,zone='hand'),1);saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.count(g,GIGANTIC,zone='hand'),1);self.portable(g)

    def test_tinyfin_reaction_failure_rolls_back_root_summons_and_derivative(self):
        g=self.game((GROWFIN,),board=(WATCH,),mode='tiny_fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,GROWFIN)
        self.assertEqual(g.snapshot(),saved);self.portable(g)

    def test_rehashed_future_source_presence_is_rejected(self):
        g=self.game((FAN,),board=(A,));target=self.board(g,A).id;self.play(g,FAN,target);saved=g.snapshot()
        row=next(a for a in saved['state']['entities'][str(target)]['abilities']if a['kind']=='attack_policy')
        row['attack_source_binding']['reference']['presence_id']=saved['state']['next_order']+1
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as caught:Game.from_snapshot(saved,fixture('normal','forged-reader'))
        self.assertNotIn('digest mismatch',str(caught.exception));self.portable(g)
