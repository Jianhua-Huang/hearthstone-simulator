"""Actual attack windows and real Noble Sacrifice/Ursoc native consumers."""
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction,
    PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec)
from hs_sim.engine.effects import (ChoiceOption, Destroy, ForceAttack, InvokeBehavior,
    RequestChoice, ReturnToHand)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.model import BoardPresenceReference
from hs_sim.engine.native_attack_targets import ACCEPTED, FINISHED
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from test_native_random_target_domains import (fixture as domain_fixture, CARD, UNIT,
    TAUNT, STEALTH, IMMUNE)

P = 'fixture.native.attack.'
WATCH = P+'watch'
NOBLE = 'EX1_130'
URSOC = 'EDR_819'


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r = domain_fixture.__wrapped__()
    def watch(c):
        if mode == 'fail':
            raise ResolutionError('Native attack observer failure')
        native = next((e.id for e in c.state.entities.values() if e.card_id == CARD and e.zone.value == 'board'), None)
        options = [ChoiceOption('ok','Continue')]
        if native is not None:
            options.append(ChoiceOption('native','Remove source',(Destroy(native),)))
        options.append(ChoiceOption('attacker','Remove attacker',(Destroy(c.event.source_id),)))
        if c.state.entities[c.event.target_id].kind == CardType.MINION:
            options.append(ChoiceOption('blink','Reenter selected defender',(
                ReturnToHand(c.event.target_id), InvokeBehavior(P+'resummon',
                    source_id=c.source_id,player_id=c.player_id,target_id=c.event.target_id))))
        return (RequestChoice(c.player_id,tuple(options),c.source_id),)
    def resummon(c):
        target = c.state.entities[c.target_id]
        return (SummonStoredCard(CardReference.capture(target),target.controller,cause=SummonCause.capture(c)),)
    r.register_behavior(P+'watch',watch);r.register_behavior(P+'resummon',resummon)
    event = 'attack_declared' if mode == 'before' else 'attack_finished' if mode == 'fail' else 'attack_redirected'
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,
        triggers=(TriggerSpec(event,P+'watch'),)))
    def force(c):
        a = next(i for i in c.state.players[1].board if c.state.entities[i].card_id == UNIT)
        d = next(i for i in c.state.players[1].board if c.state.entities[i].card_id == CARD)
        return (ForceAttack(*(BoardPresenceReference.capture(c.state,i)for i in(a,d)),combat_relation='friendly_minions'),)
    r.register_behavior(P+'force',force)
    r.register_card(CardDefinition(P+'force','Original forced friendly combat fixture',CardType.SPELL,on_play=P+'force'))
    r.validate();return r


def rehash(value):
    value['events_hash'] = canonical_hash(value['events'])
    value['state_hash'] = canonical_hash({k:v for k,v in value.items() if k not in('events','events_hash','state_hash')})
    return value


class NativeAttackTargetTests(unittest.TestCase):
    def game(self,*,mode='normal',board=(CARD,UNIT),enemy=(UNIT,),hand=(),weapon=None,seed=313):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_03',board=board,hand=hand,weapon_card_id=weapon,mana=10,max_mana=10),
            PlayerSetup('HERO_03',board=enemy,mana=10,max_mana=10)),seed=seed),fixture(mode))
    def entity(self,g,cid,player=1,zone='board'):
        return next(i for i in getattr(g.state.players[player],zone) if g.state.entities[i].card_id == cid)
    def attack(self,g,target=None):
        g.apply(Attack(1,self.entity(g,UNIT),target or self.entity(g,UNIT,2)))
    def play(self,g,cid,player=1):
        g.apply(PlayCard(player,self.entity(g,cid,player,'hand')))
    def choose(self,g,option='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id,q.id,(option,)))
    def portable(self,g,mode='normal'):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved,fixture.__wrapped__(mode))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),fixture.__wrapped__(mode)).snapshot(),saved)
        return other
    def test_voluntary_attack_keeps_original_declaration_and_consumes_one_opportunity(self):
        g = self.game(enemy=(TAUNT,STEALTH,IMMUNE,UNIT));a=self.entity(g,UNIT);d=self.entity(g,TAUNT,2)
        rng=g.snapshot()['rng_state'];g.apply(Attack(1,a,d));row=g.state.character_attack_history[-1]
        self.assertEqual(row.declaration.target_id,d);self.assertIsNotNone(row.native_target)
        self.assertEqual(row.delivery.target_id,row.native_target.target_id)
        self.assertEqual(row.native_target.partition.submitted_target_id,d)
        self.assertEqual(set(row.native_target.partition.target_ids),set(g.state.players[2].board+[g.state.players[2].hero_id]))
        self.assertEqual(g.state.entities[a].attacks_this_turn,1)
        self.assertEqual(sum(e.kind==ACCEPTED for e in g.events),1);self.assertEqual(sum(e.kind==FINISHED for e in g.events),1)
        self.assertNotEqual(g.snapshot()['rng_state'],rng);self.portable(g)
    def test_taunt_and_frozen_illegal_original_attacks_do_not_gain_random_acceptance(self):
        g=self.game(enemy=(TAUNT,UNIT));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.attack(g)
        self.assertEqual(g.snapshot(),before)
        g._state.entities[self.entity(g,UNIT)].frozen_until_owner_turn=1;before=g.snapshot()
        with self.assertRaises(IllegalAction):self.attack(g,self.entity(g,TAUNT,2))
        self.assertEqual(g.snapshot(),before)
    def test_no_live_source_keeps_target_rng_and_ordinary_history(self):
        g=self.game(board=(UNIT,));before=g.snapshot()['rng_state'];d=self.entity(g,UNIT,2)
        self.attack(g);row=g.state.character_attack_history[-1]
        self.assertIsNone(row.native_target);self.assertEqual(row.delivery.target_id,d)
        self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)
    def test_real_hero_weapon_attack_keeps_original_hero_identity_and_spends_durability_once(self):
        g=self.game(weapon='CS2_106');a=g.state.players[1].hero_id;d=self.entity(g,UNIT,2)
        weapon=g.state.players[1].weapon_id;durability=g.state.entities[weapon].durability
        g.apply(Attack(1,a,d));row=g.state.character_attack_history[-1];hero=g.state.hero_attack_history[-1]
        self.assertEqual(hero.declaration.identity.declared_target_id,d)
        self.assertEqual(hero.delivery.target_id,row.native_target.target_id)
        self.assertEqual(g.state.entities[weapon].durability,durability-1);self.portable(g)
    def test_real_ursoc_forced_all_minions_can_deliver_to_enemy_hero(self):
        g=self.game(board=(CARD,),hand=(URSOC,),enemy=())
        self.play(g,URSOC);rows=g.state.character_attack_history
        self.assertEqual(len(rows),1);row=rows[0]
        self.assertEqual(row.declaration.combat_relation,'any_minions')
        self.assertEqual(g.state.entities[row.declaration.target_id].card_id,CARD)
        self.assertEqual(row.delivery.combat_relation,'opponent')
        self.assertEqual(row.delivery.target_id,g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[row.declaration.source_id].attacks_this_turn,0)
        self.assertEqual(row.native_target.rng_before!=row.native_target.rng_after,True);self.portable(g)
    def test_forced_friendly_relation_switch_uses_same_original_window(self):
        g=self.game(hand=(P+'force',),enemy=());self.play(g,P+'force');row=g.state.character_attack_history[-1]
        self.assertEqual(row.declaration.combat_relation,'friendly_minions')
        self.assertEqual(row.delivery.combat_relation,'opponent')
        self.assertEqual(row.delivery.target_id,g.state.players[2].hero_id);self.portable(g)
    def test_wait_before_native_policy_restores_original_order_and_samples_only_after_resume(self):
        g=self.game(mode='before',board=(WATCH,CARD,UNIT));before=g.snapshot()['rng_state'];self.attack(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertIsNone(g.state.character_attack_history[-1].native_target);other=self.portable(g,'before')
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(sum(e.kind==ACCEPTED for e in g.events),1)
    def test_removing_captured_source_before_policy_skips_without_rng(self):
        g=self.game(mode='before',board=(WATCH,CARD,UNIT));before=g.snapshot()['rng_state'];self.attack(g);self.choose(g,'native')
        self.assertIsNone(g.state.character_attack_history[-1].native_target)
        self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g,'before')
    def test_wait_after_selection_survives_source_death_and_does_not_repeat_draw(self):
        g=self.game(mode='after',board=(CARD,UNIT,WATCH));self.attack(g)
        self.assertIsNotNone(g.state.pending_choice);rng=g.snapshot()['rng_state'];row=g.state.character_attack_history[-1]
        other=self.portable(g,'after')
        for current in(g,other):self.choose(current,'native')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertEqual(g.state.character_attack_history[-1].delivery.target_id,row.native_target.target_id)
    def test_selected_defender_reentry_keeps_original_residence_and_cancels_combat(self):
        g=self.game(mode='after',board=(CARD,UNIT,WATCH),seed=0);self.attack(g)
        row=g.state.character_attack_history[-1];selected=row.native_target.target_id
        self.assertEqual(g.state.entities[selected].kind,CardType.MINION)
        before=g.state.entities[selected].zone_epoch;other=self.portable(g,'after')
        for current in(g,other):self.choose(current,'blink')
        self.assertEqual(g.snapshot(),other.snapshot())
        self.assertGreater(g.state.entities[selected].zone_epoch,before)
        self.assertEqual(g.state.character_attack_history[-1].terminal.status,'cancelled')
        self.assertEqual(g.state.entities[selected].damage,0)
        self.assertEqual(sum(e.kind==ACCEPTED for e in g.events),1)
    def test_attacker_removed_before_policy_cancels_without_native_draw(self):
        g=self.game(mode='before',board=(WATCH,CARD,UNIT));before=g.snapshot()['rng_state'];self.attack(g)
        self.choose(g,'attacker');row=g.state.character_attack_history[-1]
        self.assertIsNone(row.native_target);self.assertEqual(row.terminal.status,'cancelled')
        self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g,'before')
    def test_two_native_sources_keep_one_selection_for_this_original_window(self):
        g=self.game(enemy=(CARD,UNIT));self.attack(g);row=g.state.character_attack_history[-1]
        self.assertEqual(len(row.native_target.partition.carriers),2)
        self.assertEqual(sum(e.kind==ACCEPTED for e in g.events),1)
        rng=Random();rng.setstate(row.native_target.rng_before);rng.choice(row.native_target.partition.target_ids)
        self.assertEqual(rng.getstate(),row.native_target.rng_after);self.portable(g)
    def test_real_noble_sacrifice_after_native_policy_redirects_without_resampling(self):
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_03',board=(CARD,UNIT),mana=10,max_mana=10),
            PlayerSetup('HERO_04',hand=(NOBLE,),board=(UNIT,),mana=10,max_mana=10)),active_player=2,seed=313),fixture())
        self.play(g,NOBLE,2);g.apply(EndTurn(2));self.attack(g);row=g.state.character_attack_history[-1]
        self.assertEqual(row.native_target.partition.submitted_target_id,row.declaration.target_id)
        self.assertEqual(g.state.entities[row.delivery.target_id].card_id,'EX1_130a')
        self.assertEqual(sum(e.kind==ACCEPTED for e in g.events),1)
        self.assertEqual(len([e for e in g.events if e.kind=='attack_redirected']),2);self.portable(g)
    def test_real_noble_sacrifice_before_native_policy_supplies_its_current_target(self):
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_03',board=(UNIT,),mana=10,max_mana=10),
            PlayerSetup('HERO_04',hand=(NOBLE,CARD),board=(UNIT,),mana=10,max_mana=10)),active_player=2,seed=313),fixture())
        self.play(g,NOBLE,2);self.play(g,CARD,2);g.apply(EndTurn(2));self.attack(g);row=g.state.character_attack_history[-1]
        original=row.native_target.partition.submitted_target_id
        self.assertEqual(g.state.entities[original].card_id,'EX1_130a')
        self.assertNotEqual(original,row.declaration.target_id)
        self.assertEqual(sum(e.kind==ACCEPTED for e in g.events),1);self.portable(g)
    def test_late_failure_rolls_back_original_attack_counter_rng_and_native_receipts(self):
        g=self.game(mode='fail',board=(CARD,UNIT,WATCH));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.attack(g)
        self.assertEqual(g.snapshot(),before)
    def test_waiting_proof_rejects_cropped_candidates_missing_finish_and_changed_relation(self):
        g=self.game(mode='after',board=(CARD,UNIT,WATCH));self.attack(g)
        for mode in('crop','finish','relation'):
            s=json.loads(json.dumps(g.snapshot()))
            if mode=='crop':
                x=s['state']['character_attack_history'][-1]['native_target'];x['partition']['candidates']=x['partition']['candidates'][:-1]
            elif mode=='relation':s['state']['action_windows'][-1]['combat_relation']='any_minions'
            else:
                def prune(value):
                    if isinstance(value,dict):
                        for key,child in list(value.items()):
                            if isinstance(child,list):value[key]=[x for x in child if not(isinstance(x,dict)and str(x.get('type','')).endswith('.FinishNativeAttackTarget'))]
                            prune(value[key])
                    elif isinstance(value,list):
                        for child in value:prune(child)
                prune(s['resolution_frame'])
            with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(rehash(s),fixture.__wrapped__('after'))
    def test_internal_candidate_sources_proof_and_rng_are_not_player_visible(self):
        g=self.game();self.attack(g)
        for player in(1,2):
            shown=json.dumps(g.observe(player))
            for hidden in(ACCEPTED,FINISHED,'native_target','rng_before','before_state','native_random_target'):
                self.assertNotIn(hidden,shown)


if __name__=='__main__':unittest.main()
