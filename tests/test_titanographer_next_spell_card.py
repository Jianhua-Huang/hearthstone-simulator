"""Actual Osk branch and one paired, persistent physical spell reservation."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.titanographer_next_spell_card import CARD,ROOT,SPEC,load_batch
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,IllegalAction,PlayCard,PlayerSetup,
    RandomSplitDamage,ResolutionError,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.effects import (ChoiceOption,Damage,Destroy,GainArmor,InvokeBehavior,RequestChoice)
from hs_sim.engine.model import BattlecryRepeatSpec,DamageKind,SpellRepeatSpec,TargetSpec
from hs_sim.engine.next_spell_bonuses import KIND,CLAIMED
from hs_sim.engine.player_effects import RemovePlayerEffect
from hs_sim.engine.health_rules import spell_bonus
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash

P='fixture.osk_bonus.';UNIT=P+'unit';WATCH=P+'watch';REPEAT=P+'repeat';SPELL_REPEAT=P+'spell_repeat'
FROST='CS2_024';PYRO='EX1_279';COUNTER='EX1_287'


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r=build_registry();meta=replace(r.card(CARD).metadata,collectible=False)
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,attack=1,health=20,metadata=meta))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=20,metadata=meta,battlecry_repeats=(BattlecryRepeatSpec(2),)))
    r.register_card(CardDefinition(SPELL_REPEAT,SPELL_REPEAT,CardType.MINION,health=20,metadata=meta,spell_repeats=(SpellRepeatSpec(2,class_mode='any'),)))
    r.register_behavior(P+'targeted',lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),))
    r.register_card(CardDefinition(P+'targeted',P+'targeted',CardType.SPELL,on_play=P+'targeted',metadata=meta,
        targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy')))
    def fail(c):raise ResolutionError('Native spell bonus fixture failure')
    r.register_behavior(P+'fail',fail)
    def hit(c):return(Damage(c.state.players[3-c.player_id].hero_id,1,c.source_id,DamageKind.SPELL),)
    def wait(c):return(RequestChoice(c.player_id,(ChoiceOption('hit','Hit',hit(c)),ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    def remove(c):
        e=next(e for e in c.state.players[c.player_id].player_effects if e.spec_id==SPEC)
        return(RemovePlayerEffect(c.player_id,e.id),)
    def kill(c):
        e=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD)
        return(Destroy(e,c.source_id),)
    scripts={'wait':wait,'hit':hit,'auto':lambda c:(CastSpell(c.player_id,FROST,c.source_id,
        c.state.players[3-c.player_id].hero_id,targeting='explicit'),),'remove':remove,'kill':kill,
        'auto_fail':lambda c:(CastSpell(c.player_id,P+'targeted',c.source_id),),'armor':lambda c:(GainArmor(c.player_id,4),),
        'split':lambda c:(RandomSplitDamage(c.player_id,c.cast.id,c.source_id,2),)}
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        r.register_card(CardDefinition(P+name,P+name,CardType.MINION if name in('auto','auto_fail','remove','kill')else CardType.SPELL,
            health=1,metadata=meta,**({'battlecry':P+name}if name in('auto','auto_fail','remove','kill')else{'on_play':P+name})))
    def watch(c):
        event=c.event
        if mode=='intervene' and event.kind=='card_committed' and event.player_id==c.player_id:
            rec=c.state.play_history[-1]
            if rec.kind==CardType.SPELL:return(CastSpell(c.player_id,P+'hit',c.source_id),)
        if mode=='after_install_fail' and event.kind=='player_effect_added' and dict(event.data).get('effect_key')==SPEC:
            return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=meta,
        triggers=(TriggerSpec('card_committed',P+'watch'),TriggerSpec('player_effect_added',P+'watch'))))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
    return s


class OskNextSpellTests(unittest.TestCase):
    def game(self,hand=None,mode='normal',active=1,repeat=False,spell_repeat=False):
        hand=(CARD,FROST,FROST)if hand is None else hand
        players=tuple(PlayerSetup('HERO_08',hand=hand if p==active else((COUNTER,)if mode=='counter'else()),deck=(UNIT,)*8,
            board=(((REPEAT,)if repeat else())+((SPELL_REPEAT,)if spell_repeat else())+((WATCH,)if mode in('intervene','after_install_fail')else()))if p==active else(),
            max_mana=10,mana=10)for p in(1,2))
        return Game.from_scenario(Scenario(players,active_player=3-active if mode=='counter'else active,seed=302),fixture(mode))
    def play(self,g,cid=CARD,target=None):
        p=g.state.active_player;i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,i,target));return i
    def health(self,g,p=2):return g.state.entities[g.state.players[p].hero_id].health
    def target(self,g):return g.state.players[3-g.state.active_player].hero_id
    def pending(self,g,p=1):return[e for e in g.state.players[p].player_effects if e.spec_id==SPEC]
    def portable(self,g,mode='normal',fresh=False):
        s=g.snapshot();r=fixture.__wrapped__(mode)if fresh else fixture(mode)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        return s

    def test_full_source_branch_and_persistent_paired_program_do_not_register_rolling_root(self):
        r=build_registry();d=load_batch();c=r.card(CARD);spec=r.player_effect(SPEC)
        self.assertEqual((c.cost,c.attack,c.health),(6,6,6));self.assertEqual((spec.kind,spec.next_spell_cost_reduction,spec.spell_damage),(KIND,3,3))
        self.assertEqual(len(d['official_observations']),4);self.assertNotIn(ROOT,r.cards)

    def test_actual_six_mana_battlecry_zero_cost_frostbolt_gets_six_damage_once(self):
        g=self.game();self.play(g);self.assertEqual(g.state.players[1].mana,4)
        e=self.pending(g)[0];self.assertEqual(spell_bonus(g.state,1,g.registry),0)
        card=next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==FROST)
        self.assertEqual(quote_cost(g.state,g.registry,card).amount,0)
        self.play(g,FROST,self.target(g));self.assertEqual((self.health(g),g.state.players[1].mana),(24,4))
        self.assertEqual(g.state.play_history[-1].next_spell_bonus_effects,(e,));self.assertEqual(g.state.cast_history[-1].next_spell_bonus_effects,(e,))
        self.assertFalse(self.pending(g));self.assertFalse(g.state.players[1].cost_modifiers)
        self.play(g,FROST,self.target(g));self.assertEqual((self.health(g),g.state.players[1].mana),(21,2));self.portable(g)

    def test_bonus_survives_source_death_and_turns_then_uses_original_price_and_damage(self):
        g=self.game((CARD,P+'kill',PYRO));self.play(g);self.play(g,P+'kill')
        self.assertTrue(self.pending(g));g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertTrue(self.pending(g))
        self.portable(g,fresh=True);self.play(g,PYRO,self.target(g))
        self.assertEqual((self.health(g),g.state.players[1].mana),(17,3));self.portable(g)

    def test_countered_paid_spell_consumes_both_parts_under_local_admission_policy(self):
        g=self.game(mode='counter');self.play(g,COUNTER);g.apply(EndTurn(2));self.play(g);self.play(g,FROST,self.target(g))
        self.assertEqual(self.health(g),30);self.assertFalse(self.pending(g));self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertEqual(g.state.cast_history[-1].failure,'countered');self.assertEqual(len(g.state.cast_history[-1].next_spell_bonus_effects),1)
        self.play(g,FROST,self.target(g));self.assertEqual(self.health(g),27);self.portable(g,'counter')

    def test_nonspell_automatic_cast_consumes_whole_bonus_without_manual_payment(self):
        g=self.game((CARD,P+'auto',FROST));self.play(g);self.play(g,P+'auto')
        self.assertEqual(self.health(g),24);self.assertFalse(self.pending(g));self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertEqual(g.state.cast_history[-1].origin,'effect');self.assertEqual(g.state.play_history[-1].next_spell_bonus_effects,())
        self.play(g,FROST,self.target(g));self.assertEqual(self.health(g),27-6);self.portable(g)

    def test_waiting_spell_keeps_reserved_bonus_through_independent_restore_and_failed_resume(self):
        g=self.game((CARD,P+'wait'));self.play(g);self.play(g,P+'wait');self.assertFalse(self.pending(g))
        before=self.portable(g,fresh=True);q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,q.id,('fail',)))
        self.assertEqual(g.snapshot(),before);g.apply(SelectChoice(1,q.id,('hit',)))
        self.assertEqual(self.health(g),26);self.portable(g)

    def test_actual_split_damage_quote_carries_reserved_player_program(self):
        g=self.game((CARD,P+'split'));self.play(g);self.play(g,P+'split');self.assertEqual(self.health(g),25)
        self.assertEqual(len(g.state.split_damage_history[-1].quote.cast.next_spell_bonus_effects),1);self.portable(g)

    def test_explicit_program_removal_retires_its_exact_linked_discount(self):
        g=self.game((CARD,P+'remove',FROST));self.play(g);self.play(g,P+'remove')
        self.assertFalse(self.pending(g));self.assertFalse(g.state.players[1].cost_modifiers)
        self.play(g,FROST,self.target(g));self.assertEqual((self.health(g),g.state.players[1].mana),(27,2));self.portable(g)

    def test_install_reaction_failure_restores_original_payment_and_all_allocations(self):
        g=self.game(mode='after_install_fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_second_actor_owns_both_price_and_damage_contributions(self):
        g=self.game(active=2);self.play(g);self.play(g,FROST,self.target(g))
        self.assertEqual((self.health(g,1),g.state.players[2].mana),(24,4));self.assertFalse(self.pending(g,1));self.portable(g)

    def test_nonspell_does_not_consume_program_or_receive_ambient_spell_damage(self):
        g=self.game((CARD,UNIT,FROST));self.play(g);self.play(g,UNIT)
        self.assertEqual(len(self.pending(g)),1);self.assertEqual(spell_bonus(g.state,1,g.registry),0)
        self.assertEqual(g.state.play_history[-1].next_spell_bonus_effects,())
        self.play(g,FROST,self.target(g));self.assertEqual(self.health(g),24)

    def test_illegal_unaffordable_spell_keeps_exact_original_program_and_quote(self):
        g=self.game((CARD,PYRO));self.play(g);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,PYRO,self.target(g))
        self.assertEqual(g.snapshot(),before);self.assertEqual(len(self.pending(g)),1)

    def test_two_actual_battlecries_reserve_both_original_instances_for_one_spell(self):
        g=self.game(repeat=True);self.play(g);self.assertEqual(len(self.pending(g)),2)
        self.play(g,FROST,self.target(g));self.assertEqual((self.health(g),g.state.players[1].mana),(21,4))
        self.assertEqual(len(g.state.cast_history[-1].next_spell_bonus_effects),2);self.assertFalse(self.pending(g));self.portable(g)

    def test_paid_reservation_cannot_be_stolen_by_intervening_automatic_spell(self):
        g=self.game(mode='intervene');self.play(g);self.play(g,FROST,self.target(g))
        self.assertEqual(self.health(g),23)
        self.assertEqual([c.origin for c in g.state.cast_history],['effect','hand'])
        self.assertEqual([len(c.next_spell_bonus_effects)for c in g.state.cast_history],[0,1]);self.portable(g,'intervene')

    def test_failed_automatic_target_selection_does_not_consume_pending_pair(self):
        g=self.game((CARD,P+'auto_fail',FROST));self.play(g);self.play(g,P+'auto_fail')
        self.assertIsNotNone(g.state.cast_history[-1].failure);self.assertEqual(g.state.cast_history[-1].next_spell_bonus_effects,())
        self.assertEqual(len(self.pending(g)),1);self.play(g,FROST,self.target(g));self.assertEqual(self.health(g),24);self.portable(g)

    def test_zero_cost_nondamage_spell_still_consumes_whole_program(self):
        g=self.game((CARD,P+'armor',FROST));self.play(g);self.play(g,P+'armor')
        self.assertFalse(self.pending(g));self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4)
        self.play(g,FROST,self.target(g));self.assertEqual(self.health(g),27)

    def test_local_first_physical_cast_policy_does_not_reapply_bonus_to_spell_repeat(self):
        g=self.game(spell_repeat=True);self.play(g);self.play(g,FROST,self.target(g))
        self.assertEqual((self.health(g),g.state.players[1].mana),(21,4))
        self.assertEqual([len(c.next_spell_bonus_effects)for c in g.state.cast_history],[1,0]);self.portable(g)

    def test_rehashed_snapshot_cannot_drop_entire_pending_program_and_bound_price(self):
        g=self.game();self.play(g);bad=deepcopy(g.snapshot())
        def drop(v):
            if isinstance(v,dict):
                if isinstance(v.get('player_effects'),list):v['player_effects'][:]=[e for e in v['player_effects']if e.get('spec_id')!=SPEC]
                if isinstance(v.get('cost_modifiers'),list):v['cost_modifiers'][:]=[m for m in v['cost_modifiers']if m.get('player_effect_id')is None]
                for x in v.values():drop(x)
            elif isinstance(v,list):
                for x in v:drop(x)
        drop(bad)
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture())

    def test_player_views_hide_original_material_price_link_and_private_claim_proofs(self):
        g=self.game();self.play(g)
        for p in(1,2):
            view=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('next_spell_bonus_effects','cost_modifier_id','effects_json','native_spell_bonus_installed','entered_order'):
                self.assertNotIn(key,view)


if __name__=='__main__':unittest.main()
