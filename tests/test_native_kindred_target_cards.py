"""Actual targeted Kindred legality shares its native previous-owner query."""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_kindred_target_cards import MATRIARCH, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice,
    SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.body_target_origin import capture_origin, origin_hash, reconstruct_origin
from hs_sim.engine.effects import Buff, ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.kindred_targets import KindredTargetProfile, matched, validate_profile
from hs_sim.engine.model import KindredProfile, TargetMode
from hs_sim.engine.player_target_inputs import capture as capture_view, decode as decode_view
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash, state_to_dict
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.targeting import target_choices
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_physical import PROFILE
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.cross_zone import BuffStoredCard
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P='k103.';BEAST='BAR_024';YETI='CORE_CS2_182';CHALLENGER='TLC_251'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


def registry():
    r=build_registry()
    r.register_card(CardDefinition(P+'tank','Original enemy',CardType.MINION,attack=0,health=30,metadata=META))
    r.register_card(CardDefinition(P+'dormant','Dormant enemy',CardType.MINION,health=30,dormant_turns=2,metadata=META))
    r.register_card(CardDefinition(P+'elusive','Elusive enemy',CardType.MINION,health=30,keywords=(Keyword.ELUSIVE,),metadata=META))
    r.register_card(CardDefinition(P+'power','Spell damage fixture',CardType.MINION,health=10,spell_damage=10,metadata=META))
    r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('Deliberate Kindred target failure')))
    def replay_body(c):
        return(ReplayWholeCards(c.player_id,c.source_id,WholeCardHistoryQuery(c.player_id,
            len(c.state.play_history)+1,kinds=(CardType.MINION,),exclude_card_ids=(BEAST,YETI,CHALLENGER)),
            choices='random',physical_profile=PROFILE),)
    scripts={
        'replay':replay_body,
        'summon':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(MATRIARCH),),SummonCause.capture(c)),),
        'boost':lambda c:(BuffStoredCard(CardReference.capture(c.state.entities[c.target_id]),3,0,c.source_id),),
    }
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,metadata=META,
            targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')if name=='boost'else None))
    def wait(c):
        e=c.state.entities.get(c.event.source_id)
        if e is None or e.card_id!=MATRIARCH:return()
        return(RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),
            ChoiceOption('boost','Change actual Attack before native body',(Buff(e.id,3,0,c.source_id),)),
            ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),)),
        ),c.source_id),)
    r.register_behavior(P+'wait',wait)
    r.register_card(CardDefinition(P+'watch','Entry witness',CardType.MINION,health=10,metadata=META,
        triggers=(TriggerSpec('minion_summoned',P+'wait'),)))
    r.validate();return r


class NativeKindredTargetCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(BEAST,MATRIARCH),board=(),enemy=(P+'tank',),active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand if active==1 else(),board=board if active==1 else enemy,
                deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=hand if active==2 else(),board=board if active==2 else enemy,
                deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
        ),active_player=active,seed=103),self.r)
    def find(self,g,cid=MATRIARCH,p=None,zone='hand'):
        p=p or g.state.active_player
        return next(i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid=MATRIARCH,target=None):
        p=g.state.active_player;i=self.find(g,cid);kind=self.r.card(cid).kind
        g.apply(PlayCard(p,i,target,position=len(g.state.players[p].board)if kind==CardType.MINION else None));return i
    def cycle(self,g):
        p=g.state.active_player;g.apply(EndTurn(p));g.apply(EndTurn(3-p))
    def qualified(self,**kwargs):
        g=self.game(**kwargs);self.play(g,BEAST);self.cycle(g);return g
    def enemy(self,g):return self.find(g,P+'tank',3-g.state.active_player,'board')
    def condition(self,g):
        i=self.find(g);return matched(g.state,self.r,g.state.entities[i],self.r.card(MATRIARCH))
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        return other
    def public_card(self,g,viewer=None):
        viewer=viewer or g.state.active_player;view=g.observe(viewer)
        return next(c for p in view['players']if p['id']==viewer for c in p['hand']if c['card_id']==MATRIARCH)

    def test_complete_raw_metadata_and_pure_kindred_profile(self):
        data=load_batch();row=data['cards'][0];card=self.r.card(MATRIARCH)
        self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(card.metadata,replace(metadata_from_record(row['record']),deck_identity=MATRIARCH))
        self.assertIsNone(card.battlecry);self.assertIsNotNone(card.on_play)
        self.assertEqual(self.r.kindred_target_profiles[MATRIARCH],KindredTargetProfile(MATRIARCH))
        self.assertEqual(len(data['official_observations']),2)

    def test_inactive_requires_no_target_even_with_enemy_present(self):
        g=self.game();i=self.find(g);self.assertFalse(self.condition(g))
        self.assertEqual(target_choices(g.state,self.r,g.state.entities[i],self.r.card(MATRIARCH)),(None,))
        target=self.enemy(g);self.play(g);self.assertEqual(g.state.entities[target].health,30)
        row=g.state.kindred_history[-1];self.assertFalse(row.condition.matched);self.assertEqual(row.plan,());self.portable(g)

    def test_inactive_rejects_a_supplied_target_without_payment(self):
        g=self.game();saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,target=self.enemy(g))
        self.assertEqual(g.snapshot(),saved)

    def test_current_turn_beast_does_not_count_as_previous_turn(self):
        g=self.game();self.play(g,BEAST);self.assertFalse(self.condition(g));self.play(g)
        self.assertFalse(g.state.kindred_history[-1].condition.matched)

    def test_previous_actual_owner_beast_enables_target_and_damage(self):
        g=self.qualified();target=self.enemy(g);before=g.state.players[1].mana
        self.assertTrue(self.condition(g));self.assertIn(target,g.legal_targets(self.find(g)))
        self.play(g,target=target);self.assertEqual(g.state.entities[target].health,25)
        self.assertEqual(g.state.players[1].mana,before-4);self.assertTrue(g.state.kindred_history[-1].completed);self.portable(g)

    def test_active_with_available_enemy_requires_target(self):
        g=self.qualified();before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_active_empty_enemy_domain_allows_play_without_effect(self):
        g=self.qualified(enemy=());self.play(g);self.assertTrue(g.state.kindred_history[-1].completed)
        self.assertTrue(g.state.kindred_history[-1].condition.matched)

    def test_nonmatching_previous_turn_and_empty_latest_turn_do_not_borrow_older(self):
        g=self.game(hand=(YETI,MATRIARCH));self.play(g,YETI);self.cycle(g);self.assertFalse(self.condition(g))
        g=self.qualified();self.cycle(g);self.assertFalse(self.condition(g))

    def test_player_two_uses_its_own_actual_previous_turn(self):
        g=self.qualified(active=2);target=self.enemy(g);self.play(g,target=target)
        self.assertEqual(g.state.entities[target].health,25);self.portable(g)

    def test_modified_actual_attack_not_printed_or_spell_damage(self):
        g=self.qualified(hand=(BEAST,P+'boost',MATRIARCH),board=(P+'power',));target=self.enemy(g)
        self.play(g,P+'boost',self.find(g));self.play(g,target=target)
        self.assertEqual(g.state.entities[target].health,22)

    def test_manual_target_domain_rejects_friendly_and_hero(self):
        g=self.qualified();before=g.snapshot()
        for target in(g.state.players[2].hero_id,self.find(g,BEAST,1,'board')):
            with self.subTest(target=target),self.assertRaises(IllegalAction):self.play(g,target=target)
            self.assertEqual(g.snapshot(),before)

    def test_elusive_enemy_remains_legal_for_minion_body(self):
        g=self.qualified(enemy=(P+'elusive',));target=self.find(g,P+'elusive',2,'board')
        self.play(g,target=target);self.assertEqual(g.state.entities[target].health,25)

    def test_native_next_kindred_repeats_only_active_damage_with_one_payment(self):
        g=self.qualified(hand=(BEAST,CHALLENGER,MATRIARCH));self.play(g,CHALLENGER);target=self.enemy(g)
        before=g.state.players[1].mana;self.play(g,target=target)
        self.assertEqual(g.state.entities[target].health,20);self.assertEqual(g.state.players[1].mana,before-4)
        row=g.state.kindred_history[-1];self.assertEqual(row.plan,('active','active'));self.assertEqual(len(row.sources),1)

    def test_inactive_still_consumes_real_next_kindred_without_target(self):
        g=self.game(hand=(CHALLENGER,MATRIARCH));self.play(g,CHALLENGER);self.play(g)
        row=g.state.kindred_history[-1];self.assertFalse(row.condition.matched);self.assertEqual(row.plan,())
        self.assertEqual(len(row.sources),1);self.assertFalse(g.state.players[1].player_effects)

    def test_plain_summon_does_not_run_native_play_body(self):
        g=self.qualified(hand=(BEAST,P+'summon',MATRIARCH));before=len(g.state.kindred_history);self.play(g,P+'summon')
        self.assertEqual(len(g.state.kindred_history),before);self.assertEqual(g.state.entities[self.enemy(g)].health,30)

    def test_automatic_physical_inactive_body_does_not_require_enemy_target(self):
        g=self.game(hand=(MATRIARCH,P+'replay'));self.play(g);self.play(g,P+'replay')
        self.assertEqual(g.state.entities[self.enemy(g)].health,30)
        self.assertEqual(len([i for i in g.state.players[1].board if g.state.entities[i].card_id==MATRIARCH]),2)
        self.portable(g)

    def test_automatic_physical_active_body_selects_real_enemy_target(self):
        g=self.qualified(hand=(BEAST,MATRIARCH,P+'replay'));target=self.enemy(g)
        self.play(g,target=target);self.play(g,P+'replay');self.assertEqual(g.state.entities[target].health,20);self.portable(g)

    def test_player_commands_agree_with_inactive_and_active_target_domains(self):
        for active in(False,True):
            with self.subTest(active=active):
                g=self.qualified()if active else self.game();card=self.public_card(g)
                self.assertIs(card['play_conditions']['kindred'],active)
                report=g.for_player(1).legal_actions();self.assertIsNone(report['error'])
                actions=[a for a in report['actions']if a['type']=='play_card'and a['card']==card['ref']]
                self.assertTrue(actions);self.assertTrue(all((a['target']is not None)==active for a in actions))
                reply=g.for_player(1).submit({'revision':report['revision'],'action':actions[0]})
                self.assertTrue(reply['accepted'],reply['error']);self.assertTrue(g.state.kindred_history[-1].completed)

    def test_public_fact_does_not_export_raw_histories_or_opposing_hand(self):
        g=self.qualified();own=self.public_card(g);self.assertIs(own['play_conditions']['kindred'],True)
        other=g.observe(2);hidden=next(p for p in other['players']if p['id']==1)['hand']
        self.assertTrue(all(set(c)=={'ref','card_id'}for c in hidden))
        text=json.dumps(g.observe(1))+json.dumps(other)
        for private in('owner_turn_history','play_history','PreviousOwnerTurnMatch','query_for_definition'):
            self.assertNotIn(private,text)

    def test_entry_wait_restores_original_targets_and_uses_actual_body_attack(self):
        g=self.qualified(board=(P+'watch',));target=self.enemy(g);self.play(g,target=target)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);self.choose(g,'boost');self.choose(other,'boost')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[target].health,22);self.portable(g)

    def test_failed_entry_choice_rolls_back_then_keeps_original_target(self):
        g=self.qualified(board=(P+'watch',));target=self.enemy(g);self.play(g,target=target);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(g.state.entities[target].health,25)

    def test_origin_reconstruction_uses_original_closed_prefix_after_later_turns(self):
        g=self.game(hand=(MATRIARCH,));source=self.find(g);before=deepcopy(g.state);before.action_number+=1
        original=capture_origin(before,before.entities[source],canonical_hash(state_to_dict(before)))
        self.play(g);play=g.state.play_history[-1];self.cycle(g)
        self.assertTrue(matched(g.state,self.r,g.state.entities[source],self.r.card(MATRIARCH)))
        receipt=SimpleNamespace(origin=original,origin_hash=origin_hash(original),action=PlayCard(1,source,position=0),retry_root=None)
        restored,e=reconstruct_origin(g.state,self.r,play,receipt)
        self.assertFalse(matched(restored,self.r,e,self.r.card(MATRIARCH)))
        self.assertEqual(restored.play_history,[]);self.assertFalse(restored.owner_turn_history[-1].closed)

    def test_profile_duplicate_missing_native_and_wrong_shapes_rejected(self):
        r=build_registry()
        with self.assertRaises(ValueError):r.register_kindred_target_profile(KindredTargetProfile(MATRIARCH))
        for bad in(KindredTargetProfile(YETI),object()):
            with self.subTest(profile=bad),self.assertRaises(ValueError):validate_profile(r,bad)
        with self.assertRaises(ValueError):KindredTargetProfile('')

    def test_player_observation_proof_rejects_nonboolean_kindred_fact(self):
        g=self.qualified();source=g._state.entities[self.find(g)];proof=capture_view(g,g._state,source)
        value=json.loads(proof.observation_json)
        card=next(c for p in value['players']if p['id']==1 for c in p['hand']if c['card_id']==MATRIARCH)
        card['play_conditions']['kindred']=1
        with self.assertRaises(ValueError):
            bad=replace(proof,observation_json=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')))
            decode_view(bad)


if __name__=='__main__':unittest.main()
