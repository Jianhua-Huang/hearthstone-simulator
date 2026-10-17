"""Original defender windows, actual replacement targets and real native consumers."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_forced_attack_cards import HOUND,SABER,load_batch
from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,Game,IllegalAction,PlayCard,
    PlayerSetup,Scenario,SelectChoice,SnapshotError,TargetSpec,UseHandAction,Zone)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,ForceAttack,InvokeBehavior,
    RequestChoice,ReturnToHand,Summon,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import RedirectAttack,ResolveAttack,resolve_attack
from hs_sim.engine.model import CostSpec,LimitedTriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from hs_sim.targets import canonical_digest

P='k134.';YETI='CORE_CS2_182';SMALL=P+'small';BIG=P+'big'


def registry(mode=None):
    r=build_registry()
    for cid,attack,health in ((SMALL,1,1),(BIG,1,9)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=health))
    def reenter(c):
        e=c.state.entities[c.target_id]
        return (SummonStoredCard(CardReference.capture(e),e.controller),)
    def trigger(c):return (TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]),c.source_id),)
    def discount(c):
        return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(set_to=3),c.source_id)
            for i in c.state.players[c.player_id].hand)
    scripts={'reenter':reenter,'trigger':trigger,'discount':discount,
        'force':lambda c:(ForceAttack(capture_board_presence(c.state,c.state.players[1].board[0]),
            capture_board_presence(c.state,c.state.players[2].board[0])),),
        'hero':lambda c:(Buff(c.state.players[1].hero_id,1,source_id=c.source_id,expires_turn=c.state.turn),),
        'enemy_add':lambda c:(Summon(2,SMALL),Summon(2,SMALL)),
        'summon_hound':lambda c:(Summon(c.player_id,HOUND),),
        'summon_saber':lambda c:(Summon(c.player_id,SABER),),
        'fail':lambda c:(AddToHand(c.player_id,'unknown.k134'),)}
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        kwargs=dict(targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)))if name=='trigger'else {}
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,**kwargs))
    if mode:
        def bounce(c,target):
            return (ReturnToHand(target),InvokeBehavior(P+'reenter',c.source_id,c.player_id,target))
        def wait(c):
            return (RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',
                (InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        def watch(c):
            event=c.event;target=event.target_id
            if mode=='target_reentry':return bounce(c,target)
            if mode=='source_reentry':return bounce(c,event.source_id)
            if mode=='target_transform':return (Transform(target,BIG),)
            if mode=='target_control':return (ChangeControl(target,c.state.entities[event.source_id].controller),)
            if mode=='reentry_wait':return (*bounce(c,target),*wait(c))
            if mode in ('redirect','redirect_wait','redirect_reentry'):
                window=c.state.action_windows[-1];other=c.state.players[c.state.entities[target].controller].board[1]
                effects=(RedirectAttack(window.id,other),)
                return (*effects,*wait(c))if mode=='redirect_wait'else (*effects,*bounce(c,other))if mode=='redirect_reentry'else effects
            if mode=='explicit_retarget':
                window=c.state.action_windows[-1];hero=c.state.players[c.state.entities[target].controller].hero_id
                return (RedirectAttack(window.id,hero),*bounce(c,target),RedirectAttack(window.id,target))
            return wait(c)
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(P+'watch','Original window witness',CardType.MINION,health=30,
            limited_triggers=(LimitedTriggerSpec('attack_declared',P+'watch'),)))
    r.validate();return r


@lru_cache(maxsize=None)
def shared_registry(mode):return registry(mode)


class NativeForcedAttackCardTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),mode=None,mana=50,mechanics=None):
        self.mode=mode
        if mode:board=(*board,P+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,
            mana=mana,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,
            mana=50,max_mana=50,mana_cap=50)),seed=134),shared_registry(mode),mechanics=mechanics)
    def first(self,g,cid,zone='hand',p=1):
        return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        e=self.first(g,cid);g.apply(PlayCard(1,e.id,target,position=len(g.state.players[1].board)if e.kind==CardType.MINION else None));return e.id
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(self.mode),g.mechanics)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(self.mode),g.mechanics).snapshot(),saved)
        for p in (1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in ('attack_target_presence','target_presence_id','character_attack_history','resolution_frame','rng_state'):
                self.assertNotIn('"'+key+'"',public)
        return other
    def rehash(self,saved):
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in ('schema_version','events','events_hash','state_hash')})
        return saved

    def test_two_full_rows_four_primary_faces_exact_native_keywords_and_metadata(self):
        d=load_batch();r=shared_registry(None);self.assertEqual((len(d['cards']),len(d['official_observations'])),(2,4))
        for row in d['cards']:
            raw=row['record'];card=r.card(raw['id']);self.assertEqual(canonical_digest(raw),row['record_sha256'])
            self.assertEqual(card.metadata,metadata_from_record(raw));self.assertEqual((card.cost,card.attack,card.health),(raw['cost'],raw['attack'],raw['health']))
            self.assertEqual(card.keywords,())
        self.assertTrue(r.card(HOUND).hand_actions);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])

    def test_previous_complete_definitions_pools_and_default_identity_are_preserved(self):
        with patch('hs_sim.cards.native_forced_attack_cards.register_native_forced_attack_cards',lambda r:None):before=build_registry()
        after=build_registry();self.assertEqual(set(after.cards)-set(before.cards),{HOUND,SABER})
        for cid,c in before.cards.items():self.assertEqual(asdict(after.card(cid)),asdict(c))
        self.assertEqual(dict(after.pool_cards),dict(before.pool_cards));self.assertEqual(dict(after.pools),dict(before.pools))
        from hs_sim.engine.representative import build_registry as defaults
        self.assertEqual(defaults().fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_hound_all_original_enemies_use_normal_forced_combat_in_order(self):
        g=self.game((HOUND,),enemy=(YETI,YETI));source=self.play(g,HOUND)
        self.assertEqual(g.state.entities[source].health,4);self.assertEqual(len(g.state.character_attack_history),2)
        self.assertTrue(all(r.declaration.forced and r.terminal.status=='completed'for r in g.state.character_attack_history))
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[1,1])

    def test_native_prepare_keeps_same_turn_lock_then_real_next_turn_play(self):
        g=self.game((HOUND,),mana=7);source=self.first(g,HOUND).id;g.apply(UseHandAction(1,source,'prepare'))
        self.assertEqual(quote_unselected_cost(g.state,g.registry,g.state.entities[source]).amount,0);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,HOUND)
        self.assertEqual(g.snapshot(),saved);g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,HOUND)
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD)

    def test_hound_reentered_defending_source_keeps_twelve_health_and_stales_later_attacks(self):
        g=self.game((HOUND,),enemy=(YETI,YETI),mode='target_reentry');source=self.play(g,HOUND)
        self.assertEqual(g.state.entities[source].health,12);self.assertEqual(len(g.state.character_attack_history),1)
        self.assertEqual(g.state.character_attack_history[0].terminal.reason,'defender_left_original_board_residence')
        self.assertTrue(all(g.state.entities[i].health==5 for i in g.state.players[2].board))

    def test_saber_printed_five_cost_does_not_activate_conditional_attacks(self):
        g=self.game((SABER,),enemy=(YETI,YETI));self.play(g,SABER);self.assertFalse(g.state.character_attack_history)

    def test_saber_discounted_real_payment_samples_two_distinct_original_targets(self):
        g=self.game((P+'discount',SABER),enemy=(SMALL,SMALL,SMALL));self.play(g,P+'discount');source=self.play(g,SABER)
        rows=g.state.character_attack_history;self.assertEqual(len(rows),2);self.assertEqual(len({r.delivery.target_id for r in rows}),2)
        self.assertEqual(g.state.play_history[-1].cost,3);self.assertEqual(g.state.players[1].mana,47)
        self.assertEqual(g.state.entities[source].health,5)

    def test_saber_reentered_selected_target_is_not_damaged_by_the_original_window(self):
        g=self.game((P+'discount',SABER),enemy=(YETI,YETI),mode='target_reentry');self.play(g,P+'discount');self.play(g,SABER)
        returned=[r for r in g.state.hand_entries if r.from_zone==Zone.BOARD and r.reason=='return']
        self.assertEqual(len(returned),1);self.assertEqual(g.state.entities[returned[0].entity_id].health,5)
        self.assertEqual([r.terminal.status for r in g.state.character_attack_history],['cancelled','completed'])

    def test_saber_indirect_battlecry_uses_actual_current_cost_and_no_second_payment(self):
        g=self.game((P+'discount',SABER,P+'enemy_add',P+'trigger'),enemy=(SMALL,SMALL));self.play(g,P+'discount');source=self.play(g,SABER)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,P+'enemy_add')
        self.assertEqual(quote_unselected_cost(g.state,g.registry,g.state.entities[source]).amount,3)
        mana=g.state.players[1].mana;price=quote_unselected_cost(g.state,g.registry,self.first(g,P+'trigger')).amount
        self.play(g,P+'trigger',source)
        self.assertEqual(g.state.players[1].mana,mana-price);self.assertEqual(len(g.state.battlecry_history),2)
        self.assertEqual(len(g.state.character_attack_history),4)

    def test_ordinary_summons_do_not_execute_either_native_battlecry(self):
        for spell in ('summon_hound','summon_saber'):
            g=self.game((P+spell,),enemy=(YETI,));self.play(g,P+spell)
            self.assertFalse(g.state.battlecry_history);self.assertFalse(g.state.character_attack_history)

    def test_zero_enemy_saber_does_not_consume_randomness_or_request_a_choice(self):
        g=self.game((P+'discount',SABER));self.play(g,P+'discount');rng=g._rng.getstate();self.play(g,SABER)
        self.assertEqual(g._rng.getstate(),rng);self.assertIsNone(g.state.pending_choice)

    def test_native_hound_waiting_restore_replay_bad_resume_and_once_completion(self):
        g=self.game((HOUND,),enemy=(YETI,YETI),mode='wait');source=self.play(g,HOUND);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[source].health,4)

    def test_manual_minion_attack_also_cancels_for_same_id_defender_reentry(self):
        g=self.game(board=(YETI,),enemy=(YETI,),mode='target_reentry');source=g.state.players[1].board[0];target=g.state.players[2].board[0]
        g.apply(Attack(1,source,target));self.assertEqual(g.state.entities[target].health,5)
        self.assertEqual(g.state.entities[source].attacks_this_turn,1);self.assertEqual(g.state.character_attack_history[-1].terminal.status,'cancelled')

    def test_hero_attack_defender_reentry_does_not_damage_or_create_completed_credit(self):
        g=self.game((P+'hero',),enemy=(YETI,),mode='target_reentry');self.play(g,P+'hero');target=g.state.players[2].board[0]
        g.apply(Attack(1,g.state.players[1].hero_id,target));self.assertEqual(g.state.entities[target].health,5)
        self.assertEqual(g.state.hero_attack_history[-1].terminal.outcome,'cancelled');self.assertFalse(g.state.damage_history)

    def test_existing_source_residence_guard_still_cancels_reentered_attacker(self):
        g=self.game((P+'force',),board=(YETI,),enemy=(YETI,),mode='source_reentry');source=g.state.players[1].board[0]
        self.play(g,P+'force');self.assertEqual(g.state.entities[source].health,5)
        self.assertEqual(g.state.character_attack_history[-1].terminal.reason,'attacker_left_original_board_residence')

    def test_transform_within_the_same_defender_residence_keeps_normal_current_stats(self):
        g=self.game((P+'force',),board=(YETI,),enemy=(YETI,),mode='target_transform');target=g.state.entities[g.state.players[2].board[0]]
        self.play(g,P+'force');current=g.state.entities[target.id]
        self.assertEqual(current.board_presence_id,target.board_presence_id);self.assertEqual((current.card_id,current.health),(BIG,5))
        self.assertEqual(g.state.character_attack_history[-1].terminal.status,'completed')

    def test_control_change_retains_residence_but_normal_friendly_combat_is_cancelled(self):
        g=self.game((P+'force',),board=(YETI,),enemy=(YETI,),mode='target_control');self.play(g,P+'force')
        self.assertFalse(g.state.damage_history);self.assertEqual(g.state.character_attack_history[-1].terminal.reason,'combatants_became_friendly')

    def test_legal_redirect_captures_replacement_and_preserves_original_declaration(self):
        g=self.game((P+'force',),board=(YETI,),enemy=(YETI,YETI),mode='redirect');targets=g.state.players[2].board[:];self.play(g,P+'force')
        row=g.state.character_attack_history[-1];self.assertEqual((row.declaration.target_id,row.delivery.target_id),(targets[0],targets[1]))
        self.assertEqual((g.state.entities[targets[0]].health,g.state.entities[targets[1]].health),(5,1));self.portable(g)

    def test_redirected_target_reentry_cancels_instead_of_hitting_its_fresh_body(self):
        g=self.game((P+'force',),board=(YETI,),enemy=(YETI,YETI),mode='redirect_reentry');targets=g.state.players[2].board[:];self.play(g,P+'force')
        self.assertTrue(all(g.state.entities[i].health==5 for i in targets));self.assertEqual(g.state.character_attack_history[-1].terminal.status,'cancelled')

    def test_explicit_redirect_via_hero_can_legitimately_select_a_new_residence_of_the_old_id(self):
        g=self.game((P+'force',),board=(YETI,),enemy=(YETI,),mode='explicit_retarget');self.play(g,P+'force')
        row=g.state.character_attack_history[-1];self.assertEqual(row.declaration.target_id,row.delivery.target_id)
        self.assertNotEqual(row.declaration.attack_target_presence,row.delivery.attack_target_presence)
        self.assertEqual(row.terminal.status,'completed');self.assertEqual(g.state.entities[row.delivery.target_id].health,1);self.portable(g)

    def test_waiting_after_reentry_restores_old_target_guard_and_cancels_on_resume(self):
        g=self.game((P+'force',),board=(YETI,),enemy=(YETI,),mode='reentry_wait');self.play(g,P+'force');other=self.portable(g)
        target=g.state.players[2].board[0]
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[target].health,5)

    def test_already_delivered_combat_keeps_guard_across_an_independent_choice(self):
        def paused(r,effect):
            tail=resolve_attack(r,effect);target=r.state.character_attack_history[-1].delivery.target_id
            return (RequestChoice(1,(ChoiceOption('ok','Return and reenter',(
                ReturnToHand(target),InvokeBehavior(P+'reenter',r.state.players[1].hero_id,1,target))),),r.state.players[1].hero_id),*tail)
        mechanics=default_mechanics('k134-delivery').replace(ResolveAttack,paused)
        g=self.game((P+'force',),board=(YETI,),enemy=(YETI,),mechanics=mechanics);self.play(g,P+'force');self.assertFalse(g.state.action_windows)
        self.assertIsNotNone(g.state.character_attack_history[-1].delivery);other=self.portable(g)
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,5)
        self.assertEqual(g.state.character_attack_history[-1].terminal.status,'cancelled')

    def test_rehashed_missing_future_or_foreign_target_guard_is_rejected(self):
        g=self.game((P+'force',),board=(YETI,),enemy=(YETI,),mode='wait');self.play(g,P+'force');saved=g.snapshot()
        for value in (None,{'entity_id':g.state.players[1].board[0],'presence_id':1},
                {'entity_id':g.state.players[2].board[0],'presence_id':g.state.next_order}):
            bad=deepcopy(saved);bad['state']['action_windows'][0]['attack_target_presence']=value
            with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(bad),registry('wait'))

    def test_rehash_cannot_replace_original_target_guard_with_current_reentered_presence(self):
        g=self.game((P+'force',),board=(YETI,),enemy=(YETI,),mode='reentry_wait');self.play(g,P+'force');saved=g.snapshot()
        ref=asdict(capture_board_presence(g.state,g.state.players[2].board[0]))
        saved['state']['action_windows'][0]['attack_target_presence']=ref
        saved['state']['character_attack_history'][0]['declaration']['attack_target_presence']=ref
        with self.assertRaises(SnapshotError)as caught:Game.from_snapshot(self.rehash(saved),registry('reentry_wait'))
        self.assertNotIn('digest mismatch',str(caught.exception))

    def test_rehash_cannot_change_redirected_target_guard_without_its_original_redirect(self):
        g=self.game((P+'force',),board=(YETI,),enemy=(YETI,YETI),mode='redirect_wait');self.play(g,P+'force');saved=g.snapshot()
        window=saved['state']['action_windows'][0];window['attack_target_presence']['presence_id']=g.state.entities[g.state.players[2].board[0]].board_presence_id
        with self.assertRaises(SnapshotError)as caught:Game.from_snapshot(self.rehash(saved),registry('redirect_wait'))
        self.assertNotIn('digest mismatch',str(caught.exception))

    def test_previous_schema_is_rejected(self):
        g=self.game();saved=g.snapshot();saved['schema_version']-=1
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())


if __name__=='__main__':unittest.main()
