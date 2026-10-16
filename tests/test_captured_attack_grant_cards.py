"""Actual attack grants keep the original target across public reaction windows."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.captured_attack_grant_cards import WINGMAN, load_batch
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction, Keyword,
    PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.attack_policies import GrantAttackPolicy, attack_policy_error
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, CopyMinion, Destroy,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import AttackPolicySpec, BoardPresenceReference
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference

YETI='CORE_CS2_182';MACHINE='TIME_043';PREFIX='k96.'


def registry():
    r=build_registry()
    r.register_card(CardDefinition(PREFIX+'tank','Nonretaliating target',CardType.MINION,health=40))
    r.register_behavior(PREFIX+'fail',lambda c:(AddToHand(c.player_id,'unknown.k96'),))
    r.register_behavior(PREFIX+'reenter',lambda c:(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id),))
    def wait(c):
        e=c.state.entities.get(c.event.target_id)
        if e is None or e.card_id!=YETI:return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),
            ChoiceOption('bad','Fail',(InvokeBehavior(PREFIX+'fail',c.source_id,c.player_id),)),
            ChoiceOption('cycle','Return and reenter',(ReturnToHand(e.id),InvokeBehavior(PREFIX+'reenter',c.source_id,c.player_id,e.id))),
            ChoiceOption('transform','Transform',(Transform(e.id,'CORE_CS2_179'),)),
            ChoiceOption('kill_source','Source departs',(Destroy(c.event.source_id,c.source_id),)),
        ),source_id=c.source_id),)
    for name,event in(('watch','ability_granted'),('stats_watch','stats_changed')):
        r.register_behavior(PREFIX+name,wait)
        r.register_card(CardDefinition(PREFIX+name,name,CardType.MINION,health=8,triggers=(TriggerSpec(event,PREFIX+name),)))
    r.register_behavior(PREFIX+'late_fail',lambda c:(AddToHand(c.player_id,'unknown.k96'),)
        if dict(c.event.data).get('ability_kind')=='attack_policy'else ())
    r.register_card(CardDefinition(PREFIX+'late_fail','Policy observer',CardType.MINION,health=8,
                                   triggers=(TriggerSpec('ability_granted',PREFIX+'late_fail'),)))
    def target(c):return next(c.state.entities[i]for i in c.state.players[1].board if c.state.entities[i].card_id==YETI)
    def defer(c):
        ref=MinionReference.capture(target(c))
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Grant',(
            GrantAttackPolicy(ref.entity_id,AttackPolicySpec('cannot_attack_heroes'),c.source_id,recipient=ref),)),),source_id=c.source_id),)
    def trigger(c):
        e=next(c.state.entities[i]for i in c.state.players[1].board if c.state.entities[i].card_id==WINGMAN)
        return (TriggerBattlecry(MinionReference.capture(e),c.source_id,e.id,targeting='explicit'),)
    scripts={
        'defer':defer,'trigger':trigger,
        'silence':lambda c:(Silence(target(c).id),),
        'bounce':lambda c:(ReturnToHand(target(c).id),),
        'control':lambda c:(ChangeControl(target(c).id,2),),
        'copy_current':lambda c:(CopyMinion(BoardPresenceReference.capture(c.state,target(c).id),1),),
        'copy_base':lambda c:(CopyMinion(BoardPresenceReference.capture(c.state,target(c).id),1,mode='base'),),
        'summon':lambda c:(Summon(c.player_id,WINGMAN),),
    }
    for name,body in scripts.items():
        r.register_behavior(PREFIX+name,body)
        r.register_card(CardDefinition(PREFIX+name,name,CardType.SPELL,on_play=PREFIX+name))
    return r


class CapturedAttackGrantCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(WINGMAN,),board=(YETI,),enemy=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
        ),seed=96),self.r)
    def target(self,g):return next(i for i in g.state.players[1].board if g.state.entities[i].card_id==YETI)
    def play(self,g,cid=WINGMAN,target=None):
        i=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,i,target,position=len(g.state.players[1].board)if self.r.card(cid).kind==CardType.MINION else None));return i
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def policies(self,g,i):return [a for a in g.state.entities[i].abilities if a.kind=='attack_policy']
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry())
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())
            for hidden in('MinionReference','resolution_frame','zone_epoch','entered_order','rng_state'):
                self.assertNotIn(hidden,public)
        return other
    def nodes(self,value):
        if isinstance(value,dict):
            if value.get('type','').endswith('.GrantAttackPolicy'):yield value['fields']
            for v in value.values():yield from self.nodes(v)
        elif isinstance(value,list):
            for v in value:yield from self.nodes(v)
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as error:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_full_face_and_unchanged_existing_consumer_definition(self):
        data=load_batch();card=self.r.card(WINGMAN)
        self.assertEqual((data['cards'][0]['record']['dbf_id'],card.cost,card.attack,card.health),(122952,5,5,5))
        self.assertEqual(len(data['official_observations']),2)
        self.assertEqual(data['existing_consumers'][0]['record']['id'],MACHINE)
        self.assertEqual(card.targeting.relation,'friendly');self.assertFalse(card.targeting.exclude_source)

    def test_actual_paid_battlecry_same_original_target_and_true_source(self):
        g=self.game();target=self.target(g);source=self.play(g,target=target)
        self.assertEqual(g.state.players[1].mana,35);self.assertEqual(len(g.state.battlecry_history),1)
        self.assertIn(Keyword.MEGA_WINDFURY,g.state.entities[target].keywords)
        policy,=self.policies(g,target);self.assertEqual((policy.source_id,policy.attack_policy.mode),(source,'cannot_attack_heroes'))
        self.assertEqual({a.source_id for a in g.state.entities[target].abilities if a.kind=='keyword'},{source})

    def test_four_minion_attacks_and_no_hero_attack_share_original_budget(self):
        g=self.game(enemy=(PREFIX+'tank',));target=self.target(g);self.play(g,target=target)
        hero=g.state.players[2].hero_id;before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,target,hero))
        self.assertEqual(g.snapshot(),before);enemy=g.state.players[2].board[0]
        for _ in range(4):g.apply(Attack(1,target,enemy))
        self.assertEqual(g.state.entities[enemy].health,24)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,target,enemy))
        self.portable(g)

    def test_no_eligible_target_plays_normally_and_bad_domains_preserve_payment(self):
        g=self.game(board=());self.play(g);self.assertEqual(g.state.players[1].mana,35)
        for target_kind in('hero','enemy','missing'):
            g=self.game(enemy=(YETI,));target=(g.state.players[1].hero_id if target_kind=='hero'else
                g.state.players[2].board[0]if target_kind=='enemy'else None);before=g.snapshot()
            with self.subTest(kind=target_kind),self.assertRaises(IllegalAction):self.play(g,target=target)
            self.assertEqual(g.snapshot(),before)

    def test_plain_summon_does_not_run_targeted_battlecry(self):
        g=self.game((PREFIX+'summon',));self.play(g,PREFIX+'summon')
        self.assertFalse(g.state.battlecry_history);self.assertFalse(self.policies(g,self.target(g)))

    def test_triggered_existing_battlecry_can_target_its_own_body(self):
        g=self.game((PREFIX+'trigger',),board=(WINGMAN,));source=g.state.players[1].board[0]
        self.play(g,PREFIX+'trigger')
        self.assertIn(Keyword.MEGA_WINDFURY,g.state.entities[source].keywords)
        self.assertEqual(len(self.policies(g,source)),1);self.assertEqual(len(g.state.battlecry_history),1)
        self.assertEqual(g.state.players[1].mana,40);self.portable(g)

    def test_actual_waiting_cycle_does_not_grant_restriction_to_reentered_id(self):
        g=self.game(board=(YETI,PREFIX+'watch'));target=self.target(g);original=MinionReference.capture(g.state.entities[target])
        self.play(g,target=target);other=self.portable(g)
        for current in(g,other):self.choose(current,'cycle');self.finish(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertNotEqual(MinionReference.capture(g.state.entities[target]),original)
        self.assertNotIn(Keyword.MEGA_WINDFURY,g.state.entities[target].keywords)
        self.assertFalse(self.policies(g,target));self.portable(g)

    def test_transform_between_actual_grants_does_not_receive_old_restriction(self):
        g=self.game(board=(YETI,PREFIX+'watch'));target=self.target(g);self.play(g,target=target)
        self.choose(g,'transform');self.finish(g)
        self.assertEqual(g.state.entities[target].card_id,'CORE_CS2_179');self.assertFalse(self.policies(g,target))

    def test_issuer_departure_does_not_cancel_original_recipient_grant(self):
        g=self.game(board=(YETI,PREFIX+'watch'));target=self.target(g);source=self.play(g,target=target)
        self.choose(g,'kill_source');self.finish(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(self.policies(g,target)[0].source_id,source)
        self.assertIn(Keyword.MEGA_WINDFURY,g.state.entities[target].keywords);self.portable(g)

    def test_choice_failure_restores_original_pending_policy_and_no_double_payment(self):
        g=self.game(board=(YETI,PREFIX+'watch'));target=self.target(g);self.play(g,target=target)
        before=g.snapshot();self.assertTrue(any(row['recipient']is not None for row in self.nodes(before)))
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.finish(g)
        self.assertEqual(g.state.players[1].mana,35);self.assertEqual(len(self.policies(g,target)),1)

    def test_late_policy_failure_rolls_back_both_grants_and_original_allocation(self):
        g=self.game(board=(YETI,PREFIX+'late_fail'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,target=self.target(g))
        self.assertEqual(g.snapshot(),before)

    def test_existing_infinitizer_reentry_also_skips_original_restriction(self):
        g=self.game((MACHINE,),board=(YETI,PREFIX+'stats_watch'));target=self.target(g);self.play(g,MACHINE,target)
        other=self.portable(g)
        for current in(g,other):self.choose(current,'cycle');self.finish(current)
        self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(4,5))
        self.assertFalse(self.policies(g,target));self.portable(g)

    def test_copy_material_and_silence_use_existing_attachment_lifecycle(self):
        g=self.game((WINGMAN,PREFIX+'copy_current',PREFIX+'copy_base',PREFIX+'silence'));target=self.target(g)
        self.play(g,target=target);self.play(g,PREFIX+'copy_current');self.play(g,PREFIX+'copy_base')
        bodies=[i for i in g.state.players[1].board if g.state.entities[i].card_id==YETI]
        self.assertEqual(len(bodies),3)
        self.assertEqual([Keyword.MEGA_WINDFURY in g.state.entities[i].keywords for i in bodies],[True,True,False])
        self.assertEqual([len(self.policies(g,i))for i in bodies],[1,1,0])
        self.play(g,PREFIX+'silence');self.assertFalse(self.policies(g,target));self.assertNotIn(Keyword.MEGA_WINDFURY,g.state.entities[target].keywords)
        self.portable(g)

    def test_completed_grants_survive_controller_transfer_and_next_turn(self):
        g=self.game((WINGMAN,PREFIX+'control'));target=self.target(g);self.play(g,target=target);self.play(g,PREFIX+'control')
        self.assertEqual(g.state.entities[target].controller,2);g.apply(EndTurn(1))
        self.assertIn(Keyword.MEGA_WINDFURY,g.state.entities[target].keywords)
        self.assertIsNotNone(attack_policy_error(g.state,g.state.entities[target],g.state.entities[g.state.players[1].hero_id],g.registry))

    def test_deferred_guarded_policy_restores_before_execution(self):
        g=self.game((PREFIX+'defer',));target=self.target(g);self.play(g,PREFIX+'defer');other=self.portable(g)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.policies(g,target)),1)

    def test_mismatched_wrong_type_unknown_and_future_recipient_reject(self):
        g=self.game();ref=MinionReference.capture(g.state.entities[self.target(g)]);spec=AttackPolicySpec('cannot_attack_heroes')
        for kwargs in(dict(target_id=ref.entity_id+1,recipient=ref),dict(target_id=ref.entity_id,recipient={'id':ref.entity_id})):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):GrantAttackPolicy(spec=spec,**kwargs)
        for original in(replace(ref,entity_id=999999),replace(ref,zone_epoch=ref.zone_epoch+1),replace(ref,entered_order=g.state.next_order)):
            effect=GrantAttackPolicy(original.entity_id,spec,recipient=original)
            with self.subTest(original=original),self.assertRaises(ValueError):effect.validate_in_state(g.state)

    def test_rehashed_frame_wrong_recipient_epoch_or_kind_is_rejected(self):
        g=self.game((PREFIX+'defer',));self.play(g,PREFIX+'defer')
        for field,value in(('zone_epoch',999999),('card_id','EX1_129')):
            s=deepcopy(g.snapshot());rows=list(self.nodes(s));self.assertTrue(rows)
            for row in rows:row['recipient']['fields'][field]=value
            with self.subTest(field=field):self.reject(s)

    def test_player_target_catalogue_is_supported_and_queries_are_pure(self):
        g=self.game();before=g.snapshot()
        for p in(1,2):
            self.assertNotIn('unsupported_rule',json.dumps(g.for_player(p).legal_actions()))
            g.for_player(p).observe()
        self.assertEqual(g.snapshot(),before)


if __name__=='__main__':unittest.main()
