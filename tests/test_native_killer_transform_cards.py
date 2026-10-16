"""Real fatal sources and guarded execution for Faceless Replicator."""
from dataclasses import asdict,replace
import json,unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_killer_transform_cards import REPLICATOR,load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardType,DamageKind,Game,Keyword,
    PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Damage,Destroy,ForceAttack,
    InvokeBehavior,RequestChoice,ReturnToHand,Silence,Transform,TriggerDeathrattles)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference,TransformCapturedMinion
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P='k106.test.';YETI='CORE_CS2_182'


def registry(mode=None):
    r=build_registry()
    def victim(c):return next(c.state.entities[i]for i in c.state.players[2].board if c.state.entities[i].card_id==REPLICATOR)
    def attacker(c):return c.state.entities[c.state.players[1].board[0]]
    def reenter(c):return(SummonStoredCard(CardReference.capture(c.source),c.player_id),)
    def choice(c,extra=()):
        return RequestChoice(1,(ChoiceOption('ok','Continue',extra),ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id)
    bodies=dict(combat=lambda c:(ForceAttack(attacker(c).id,victim(c).id),),
        spell=lambda c:(Damage(victim(c).id,3,c.source_id),),
        sourceless=lambda c:(Damage(victim(c).id,3),),
        hero=lambda c:(Damage(victim(c).id,3,c.state.players[1].hero_id),),
        activate=lambda c:(TriggerDeathrattles(victim(c).id,c.source_id),),
        destroy=lambda c:(Destroy(victim(c).id,c.source_id),),
        silence=lambda c:(Silence(victim(c).id),),
        pending=lambda c:(choice(c),TransformCapturedMinion(MinionReference.capture(attacker(c)),REPLICATOR,c.source_id)),
        reenter=reenter,fail=lambda c:(_ for _ in()).throw(ResolutionError('K106 deliberate pending failure')))
    for name,body in bodies.items():r.register_behavior(P+name,body)
    for name in('combat','spell','sourceless','hero','activate','destroy','silence','pending'):
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name))
    for name,body in dict(destroyer=lambda c:(Destroy(c.target_id,c.source_id),),
                          damager=lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.MINION_ABILITY),)).items():
        r.register_behavior(P+name,body);r.register_card(CardDefinition(P+name,name,CardType.MINION,health=9,battlecry=P+name,
            targeting=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy')))
    r.register_card(CardDefinition(P+'poison','Poison representative',CardType.MINION,attack=1,health=9,keywords=(Keyword.POISONOUS,)))
    r.register_card(CardDefinition(P+'mutual','Mutual death representative',CardType.MINION,attack=3,health=3))
    if mode:
        def eligible(c):return c.event.target_id is not None and dict(c.event.data).get('card_id')==REPLICATOR
        def watcher(c):
            death=c.state.death_history[dict(c.event.data)['death_id']-1];cause=death.cause;eid=cause.source_id
            if mode=='bounce':return(ReturnToHand(eid,to_owner=True),)
            if mode=='reenter':return(ReturnToHand(eid,to_owner=True),InvokeBehavior(P+'reenter',eid,cause.source_controller))
            if mode=='transform':return(Transform(eid,YETI),)
            if mode=='control':return(ChangeControl(eid,2),)
            return(choice(c),)
        r.register_behavior(P+'watch',watcher);r.register_trigger_condition(P+'replicator_death',eligible)
        r.register_card(CardDefinition(P+'watch','Original death reaction representative',CardType.MINION,health=9,
            limited_triggers=(LimitedTriggerSpec('minion_died',P+'watch',condition_id=P+'replicator_death'),)))
    r.validate();return r


class NativeKillerTransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(YETI,),enemy=(REPLICATOR,),mode=None):
        self.mode=mode
        if mode:enemy=(*enemy,P+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*6,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*6,mana=50,max_mana=50,mana_cap=50)),seed=106),registry(mode)if mode else self.r)
    def first(self,g,cid,p=1,zone='board'):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        e=self.first(g,cid,zone='hand');g.apply(PlayCard(1,e.id,target,len(g.state.players[1].board)if e.kind==CardType.MINION else None));return e.id
    def portable(self,g):
        snapshot=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(snapshot,registry(self.mode));self.assertEqual(other.snapshot(),snapshot);self.assertEqual(g.clone().snapshot(),snapshot);self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),snapshot)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('resolution_frame','death_history','deathrattle_history','source_zone_epoch','behavior_id','beneficiary'):self.assertNotIn('"'+key+'"',public)
        return other
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def test_complete_face_metadata_and_primary_source_pin(self):
        d=load_batch();row,=d['cards'];raw=row['record'];c=self.r.card(REPLICATOR);self.assertEqual(c.metadata,replace(metadata_from_record(raw),deck_identity=REPLICATOR));self.assertEqual(c.metadata.classes,(CardClass.NEUTRAL,));self.assertEqual(c.metadata.tribes,());self.assertEqual((c.cost,c.attack,c.health),(3,3,3));self.assertIn(Keyword.ELUSIVE,c.keywords);self.assertTrue(c.deathrattle);self.assertIsNone(c.battlecry);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(len(d['official_observations']['observations']),2);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])

    def test_only_one_definition_added_all_old_complete_definitions_unchanged(self):
        with patch('hs_sim.cards.native_killer_transform_cards.register_native_killer_transform_cards',lambda r:None):old=build_registry()
        current=build_registry();self.assertEqual(set(current.cards)-set(old.cards),{REPLICATOR});self.assertTrue(all(asdict(old.card(cid))==asdict(current.card(cid))for cid in old.cards))

    def test_paid_plain_play_is_three_three_elusive_without_battlecry(self):
        g=self.game((REPLICATOR,),board=(),enemy=());eid=self.play(g,REPLICATOR);e=g.state.entities[eid];self.assertEqual((e.attack,e.health),(3,3));self.assertIn(Keyword.ELUSIVE,e.keywords);self.assertEqual(g.state.players[1].mana,47);self.assertFalse(g.state.death_history);self.portable(g)

    def test_real_combat_killer_transforms_in_place_with_fresh_printed_body(self):
        g=self.game((P+'combat',));killer=self.first(g,YETI);victim=self.first(g,REPLICATOR,2);self.play(g,P+'combat');e=g.state.entities[killer.id];self.assertEqual((e.card_id,e.controller,e.owner,e.attack,e.health),(REPLICATOR,1,1,3,3));self.assertGreater(e.zone_epoch,killer.zone_epoch);self.assertEqual(g.state.players[1].board,[killer.id]);self.assertIn(Keyword.ELUSIVE,e.keywords);self.assertEqual(len([a for a in e.abilities if a.kind=='deathrattle']),1);self.assertEqual(len(g.state.death_history),1);self.assertEqual(g.state.death_history[0].entity_id,victim.id);self.assertEqual(g.state.death_history[0].cause.source_id,killer.id);self.assertEqual(len([e for e in g.events if e.kind=='transformed']),1);self.portable(g)

    def test_minion_ability_damage_and_direct_destruction_use_actual_minion_source(self):
        for cid,kind in((P+'damager','damage'),(P+'destroyer','destroy')):
            with self.subTest(cid=cid):
                g=self.game((cid,),board=());victim=self.first(g,REPLICATOR,2);killer=self.play(g,cid,victim.id);self.assertEqual(g.state.entities[killer].card_id,REPLICATOR);self.assertEqual(g.state.death_history[0].cause.kind,kind);self.portable(g)

    def test_poison_fatal_source_is_preserved(self):
        g=self.game((P+'combat',),(P+'poison',));killer=self.first(g,P+'poison').id;self.play(g,P+'combat');self.assertEqual(g.state.death_history[0].cause.kind,'poison');self.assertEqual(g.state.entities[killer].card_id,REPLICATOR);self.assertNotIn(Keyword.POISONOUS,g.state.entities[killer].keywords);self.portable(g)

    def test_spell_hero_and_sourceless_deaths_do_not_invent_minion_killer(self):
        for name in('spell','hero','sourceless','destroy'):
            with self.subTest(name=name):
                g=self.game((P+name,));killer=self.first(g,YETI).id;self.play(g,P+name);self.assertEqual(g.state.entities[killer].card_id,YETI);self.assertFalse(any(e.kind=='transformed'for e in g.events));self.assertEqual(len(g.state.death_history),1)

    def test_mutual_death_does_not_rescue_a_dead_killer(self):
        g=self.game((P+'combat',),(P+'mutual',));killer=self.first(g,P+'mutual').id;self.play(g,P+'combat');self.assertEqual(g.state.entities[killer].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.death_history),2);self.assertFalse(any(e.kind=='transformed'for e in g.events));self.portable(g)

    def test_live_effect_activation_has_no_fabricated_death_or_killer(self):
        g=self.game((P+'activate',));self.play(g,P+'activate');self.assertFalse(g.state.death_history);self.assertEqual(self.first(g,YETI).card_id,YETI);self.assertEqual(g.state.deathrattle_history[0].capture.origin,'effect');self.portable(g)

    def test_silenced_victim_does_not_transform_killer(self):
        g=self.game((P+'silence',P+'combat'));self.play(g,P+'silence');self.play(g,P+'combat');self.assertEqual(self.first(g,YETI).health,2);self.assertFalse(g.state.deathrattle_history)

    def test_original_killer_returned_before_execution_is_not_transformed(self):
        g=self.game((P+'combat',),mode='bounce');killer=self.first(g,YETI).id;self.play(g,P+'combat');self.assertEqual(g.state.entities[killer].zone,Zone.HAND);self.assertEqual(g.state.entities[killer].card_id,YETI);self.portable(g)

    def test_same_entity_reentry_is_not_the_original_killer_residence(self):
        g=self.game((P+'combat',),mode='reenter');old=self.first(g,YETI);self.play(g,P+'combat');e=g.state.entities[old.id];self.assertEqual((e.zone,e.card_id),(Zone.BOARD,YETI));self.assertGreater(e.zone_epoch,old.zone_epoch);self.assertNotEqual(e.entered_order,old.entered_order);self.portable(g)

    def test_same_card_transform_before_execution_retires_original_reference(self):
        g=self.game((P+'combat',),mode='transform');old=self.first(g,YETI);self.play(g,P+'combat');e=g.state.entities[old.id];self.assertEqual(e.card_id,YETI);self.assertGreater(e.zone_epoch,old.zone_epoch);self.portable(g)

    def test_control_change_before_execution_does_not_retarget_new_controller(self):
        g=self.game((P+'combat',),mode='control');killer=self.first(g,YETI).id;self.play(g,P+'combat');e=g.state.entities[killer];self.assertEqual((e.card_id,e.controller),(YETI,2));self.portable(g)

    def test_real_death_waiting_restores_replays_and_failure_rolls_back(self):
        g=self.game((P+'combat',),mode='wait');killer=self.first(g,YETI).id;self.play(g,P+'combat');self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[killer].card_id,REPLICATOR);self.portable(g)

    def test_extra_deathrattle_keeps_original_killer_and_transform_only_once(self):
        g=self.game((P+'combat',),enemy=(REPLICATOR,'FP1_031'));self.play(g,P+'combat');self.assertEqual(len(g.state.deathrattle_history),2);self.assertEqual(len([e for e in g.events if e.kind=='transformed']),1);self.portable(g)

    def test_pending_guarded_transform_effect_round_trip_and_atomic_failure(self):
        g=self.game((P+'pending',),enemy=());killer=self.first(g,YETI).id;self.play(g,P+'pending');other=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[killer].card_id,REPLICATOR)

    def test_future_reference_unknown_source_and_nonminion_result_rejected_on_restore(self):
        g=self.game((P+'pending',),enemy=());self.play(g,P+'pending');before=g.snapshot()
        def find(value):
            if isinstance(value,dict):
                if value.get('type','').endswith('.TransformCapturedMinion'):return value
                for x in value.values():
                    found=find(x)
                    if found is not None:return found
            if isinstance(value,list):
                for x in value:
                    found=find(x)
                    if found is not None:return found
            return None
        for change in('epoch','order','source','kind'):
            with self.subTest(change=change):
                bad=json.loads(json.dumps(before));node=find(bad);self.assertIsNotNone(node);fields=node['fields']
                if change=='epoch':fields['beneficiary']['fields']['zone_epoch']=99999
                elif change=='order':fields['beneficiary']['fields']['entered_order']=99999
                elif change=='source':fields['source_id']=99999
                else:fields['card_id']='HERO_08'
                bad['state_hash']=canonical_hash({k:v for k,v in bad.items()if k not in('schema_version','events','events_hash','state_hash')})
                with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())


if __name__=='__main__':unittest.main()
