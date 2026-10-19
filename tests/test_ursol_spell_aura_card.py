"""Real Ursol entry, three owner-end casts and immutable spell material."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.ursol_spell_aura_card import CARD, AURA, PROGRAM, load_batch, register_ursol_spell_aura_card
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, Destroy, GainArmor,
    InvokeBehavior, RandomDamage, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec, DamageKind, PlayerEffectSpec
from hs_sim.engine.player_effects import AddPlayerEffect, RemovePlayerEffect
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.spell_auras import CastAuraSpell, CastHighestHandSpellAsAura, SpellAuraRecord
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.zones import CardReference, CopyCard

P = 'ursol.test.'
FILL = 'CS2_182'
COPY_WATCH = P+'copy_watch'
ARMOR, VALUE, TARGET, CHOICE, FAIL, LETHAL, SETUP, CLEAN, RECAST, COPY, BASE, WATCH, NESTED = (
    P+x for x in ('armor','value','target','choice','fail','lethal','setup','clean','recast','copy','base','watch','nested'))


@lru_cache(maxsize=None)
def registry(role, mode='normal'):
    assert role in ('writer','reader')
    r = build_registry()
    register_ursol_spell_aura_card(r)
    r.register_behavior(P+'failure', lambda c: (_ for _ in ()).throw(ResolutionError('Ursol deliberate failure')))
    r.register_behavior(ARMOR, lambda c: (GainArmor(c.player_id,2),))
    r.register_behavior(VALUE, lambda c: (Damage(c.state.players[3-c.player_id].hero_id,
        local_cost(c.source)[0],c.source_id,DamageKind.SPELL),))
    r.register_behavior(TARGET, lambda c: (Damage(c.target_id,2,c.source_id,DamageKind.SPELL),))
    r.register_behavior(CHOICE, lambda c: (RequestChoice(c.player_id,(
        ChoiceOption('one','One',(GainArmor(c.player_id,1),)),
        ChoiceOption('two','Two',(GainArmor(c.player_id,2),))),source_id=c.source_id),))
    r.register_behavior(FAIL, lambda c: (RandomDamage(tuple(p.hero_id for p in c.state.players.values()),1,c.source_id),
        InvokeBehavior(P+'failure',c.source_id,c.player_id)))
    r.register_behavior(LETHAL, lambda c: (Damage(c.state.players[3-c.player_id].hero_id,60,c.source_id,DamageKind.SPELL),))
    def setup(c):
        return tuple(BuffStoredCard(CardReference.capture(c.state.entities[eid]),source_id=c.source_id,
            cost=CostSpec(delta=3 if mode=='increase' else -4))
            for eid in c.state.players[c.player_id].hand if c.state.entities[eid].card_id==VALUE)
    r.register_behavior(SETUP,setup)
    def clean(c):
        if mode=='remove':
            item=next(x for x in c.state.players[c.player_id].player_effects if x.spec_id==PROGRAM)
            return (RemovePlayerEffect(c.player_id,item.id),)
        source=next(eid for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id==CARD)
        return {'destroy':(Destroy(source),),'silence':(Silence(source),),
            'bounce':(ReturnToHand(source),),'control':(ChangeControl(source,3-c.player_id),),
            'transform':(Transform(source,FILL),)}[mode]
    r.register_behavior(CLEAN,clean)
    r.register_behavior(RECAST,lambda c:(RecastSpell(c.player_id,
        next(x.id for x in c.state.cast_history if x.card_id==AURA),c.source_id),))
    def copied(c):
        e=next(c.state.entities[x.source_id]for x in c.state.cast_history if x.card_id==AURA)
        return (CopyCard(CapturedCardCopyMaterial.capture(c.state,e),c.player_id,
            mode='base' if c.source.card_id==BASE else 'current',source_id=c.source_id),)
    r.register_behavior(COPY,copied);r.register_behavior(BASE,copied)
    r.register_behavior(NESTED,lambda c:(AddPlayerEffect(c.player_id,P+'ordinary',c.source_id),))
    r.register_behavior(P+'ordinary',lambda c:(GainArmor(c.player_id,7),)
        if c.event.player_id==c.player_id else ())
    r.register_player_effect(PlayerEffectSpec(P+'ordinary',NESTED,kind='objective',duration=2,
        tick_event='turn_ended',triggers=(TriggerSpec('turn_ended',P+'ordinary'),)))
    r.register_behavior(P+'wait',lambda c:(RequestChoice(c.player_id,(
        ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),),source_id=c.source_id),)
        if c.event.player_id==c.player_id and dict(c.event.data).get('effect_key')==PROGRAM else ())
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,attack=0,health=5,
        triggers=(TriggerSpec('player_effect_ticked',P+'wait'),)))
    r.register_behavior(P+'copy_hand', lambda c:(CopyCard(CardReference.capture(
        c.state.entities[c.event.target_id]),c.player_id,mode='current',source_id=c.source_id),)
        if c.event.player_id==c.player_id and dict(c.event.data).get('card_id')==AURA else ())
    r.register_card(CardDefinition(COPY_WATCH,COPY_WATCH,CardType.MINION,attack=0,health=5,
        triggers=(TriggerSpec('stored_card_transformed',P+'copy_hand'),)))
    for cid,cost in ((ARMOR,4),(VALUE,5),(TARGET,6),(CHOICE,7),(FAIL,9),(LETHAL,9),
            (SETUP,0),(CLEAN,0),(RECAST,0),(COPY,0),(BASE,0),(NESTED,5)):
        extra={'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy')}if cid==TARGET else {}
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,**extra))
    r.validate();r.freeze();return r


class UrsolAuraTests(unittest.TestCase):
    def game(self,hand=(CARD,ARMOR),*,mode='normal',board=(),enemy=(),enemy_hand=(),capacity=5):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=(FILL,)*25,mana=10,max_mana=10,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(FILL,)*25,mana=10,max_mana=10,hero_power_card_id='HERO_08bp')),
            seed=255259),registry('writer',mode),Ruleset(max_ongoing_effects=capacity))
    def play(self,g,cid=CARD):
        pid=g.state.active_player
        eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid));return eid
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def owner(self,g,pid=1):
        self.end(g)
        while g.state.active_player!=pid:self.end(g)
    def programs(self,g,pid=1):return [e for e in g.state.players[pid].player_effects if e.spec_id==PROGRAM]
    def armor(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].armor
    def hp(self,g,pid=2):return g.state.entities[g.state.players[pid].hero_id].health
    def inner(self,g,cid=ARMOR):return [c for c in g.state.cast_history if c.card_id==cid]
    def portable(self,g,mode='normal'):
        s=json.loads(json.dumps(g.snapshot()));r=registry('reader',mode)
        other=Game.from_snapshot(s,r)
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        return other

    def test_a00_complete_original_body_wrapper_and_assembly(self):
        from hs_sim.cards import build_registry as full
        data=load_batch();self.assertEqual(data['dependencies'][0]['record']['type'],'SPELL')
        self.assertEqual(data['cards'][0]['record']['tags']['TAG_SCRIPT_DATA_NUM_1'],3)
        assembled=full()
        for cid in (CARD,AURA):self.assertEqual(asdict(assembled.card(cid)),asdict(registry('writer').card(cid)))
        self.assertEqual(registry('writer').card(CARD).metadata.tribes,('beast',))

    def test_a01_battlecry_casts_only_wrapper_and_retains_original_physical_selection(self):
        g=self.game();eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==ARMOR)
        original=g.state.entities[eid];epoch=original.zone_epoch
        self.play(g)
        self.assertEqual(self.armor(g),0);self.assertEqual(len(g.state.cast_history),1)
        cast=g.state.cast_history[0]
        self.assertEqual((cast.card_id,cast.source_id,cast.from_zone,cast.origin),(AURA,eid,Zone.HAND,'effect'))
        self.assertEqual((g.state.entities[eid].card_id,g.state.entities[eid].zone_epoch),(AURA,epoch+2))
        row=g.state.spell_aura_history[0]
        self.assertEqual((row.card.origin.entity_id,row.card.origin.card_id),(eid,ARMOR))
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(g.state.players[1].mana,2)
        self.assertEqual(self.programs(g)[0].remaining_turns,3)
        self.portable(g)

    def test_a02_three_owner_end_casts_then_expiry_no_fourth(self):
        g=self.game();self.play(g)
        for n in range(1,4):
            self.owner(g)
            self.assertEqual(self.armor(g),2*n);self.assertEqual(len(self.inner(g)),n)
            self.assertEqual([x.remaining_turns for x in self.programs(g)],[3-n]if n<3 else [])
        self.owner(g);self.assertEqual(self.armor(g),6)
        self.assertEqual(len({c.source_id for c in self.inner(g)}),3)
        self.assertTrue(all(c.from_zone is None and c.origin=='effect' for c in self.inner(g)))
        self.portable(g)

    def test_a03_highest_uses_current_cost_not_printed_cost_or_affordability(self):
        g=self.game((SETUP,CARD,ARMOR,VALUE),mode='decrease');self.play(g,SETUP);self.play(g)
        self.assertEqual(self.programs(g)[0].spell_aura_card_id,ARMOR)
        g=self.game((SETUP,CARD,ARMOR,VALUE),mode='increase');self.play(g,SETUP);self.play(g)
        self.assertEqual(self.programs(g)[0].spell_aura_card_id,VALUE)
        self.assertEqual(g.state.players[1].mana,2)
        self.end(g);self.assertEqual(self.hp(g),22)

    def test_a04_unique_highest_and_empty_spell_hand_do_not_draw_rng(self):
        for hand in ((CARD,FILL),(CARD,ARMOR)):
            with self.subTest(hand=hand):
                g=self.game(hand);before=g.snapshot()['rng_state'];self.play(g)
                self.assertEqual(g.snapshot()['rng_state'],before)
                self.assertEqual(len(g.state.spell_aura_history),int(ARMOR in hand))

    def test_a05_equal_current_costs_select_one_physical_copy_with_replayable_rng(self):
        g=self.game((CARD,ARMOR,ARMOR));before=g.snapshot()['rng_state'];self.play(g)
        row=g.state.spell_aura_history[0]
        self.assertEqual(len(row.candidates),2);self.assertNotEqual(g.snapshot()['rng_state'],before)
        self.assertEqual(len(g.state.players[1].hand),1);self.portable(g)

    def test_b00_missing_target_is_not_prefiltered_and_each_tick_consumes_its_attempt(self):
        g=self.game((CARD,TARGET));self.play(g)
        for _ in range(3):self.owner(g)
        self.assertEqual([c.failure for c in self.inner(g,TARGET)],['no_target']*3)
        self.assertEqual(self.programs(g),[]);self.portable(g)

    def test_b01_each_end_reselects_actual_current_targets(self):
        g=self.game((CARD,TARGET),enemy=(FILL,));self.play(g)
        target=g.state.players[2].board[0]
        self.owner(g);self.assertEqual(g.state.entities[target].health,3)
        self.owner(g);self.assertEqual(g.state.entities[target].health,1)
        self.owner(g);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual([c.target_id for c in self.inner(g,TARGET)],[target]*3)

    def test_b02_automatic_choices_do_not_request_human_input(self):
        g=self.game((CARD,CHOICE));self.play(g)
        for _ in range(3):self.owner(g)
        self.assertIsNone(g.state.pending_choice);self.assertTrue(3<=self.armor(g)<=6)
        self.assertEqual(len(self.inner(g,CHOICE)),3);self.portable(g)

    def test_b03_source_lifecycle_does_not_remove_installed_program(self):
        for mode in ('destroy','silence','bounce','control','transform'):
            with self.subTest(mode=mode):
                g=self.game((CARD,ARMOR,CLEAN),mode=mode);self.play(g);self.play(g,CLEAN)
                self.owner(g);self.assertEqual(self.armor(g),2);self.assertEqual(self.armor(g,2),0)
                self.assertEqual(self.programs(g)[0].remaining_turns,2)

    def test_b04_explicit_program_removal_stops_future_casts(self):
        g=self.game((CARD,ARMOR,CLEAN),mode='remove');self.play(g);self.play(g,CLEAN)
        self.owner(g);self.assertEqual(self.armor(g),0);self.assertEqual(self.programs(g),[])

    def test_b05_plain_summoned_ursol_does_not_run_battlecry(self):
        g=self.game((ARMOR,),board=(CARD,));self.owner(g)
        self.assertEqual(g.state.spell_aura_history,[]);self.assertEqual(g.state.cast_history,[])

    def test_c00_recast_wrapper_retains_original_spell_and_independent_clocks(self):
        g=self.game((CARD,ARMOR,RECAST));self.play(g);self.play(g,RECAST)
        self.assertEqual(len(self.programs(g)),2)
        self.assertEqual({p.spell_aura_id for p in self.programs(g)},{1})
        self.owner(g);self.assertEqual(self.armor(g),4)
        self.assertEqual([p.remaining_turns for p in self.programs(g)],[2,2]);self.portable(g)

    def test_c01_current_copy_wrapper_retains_material_through_actual_hand_play(self):
        g=self.game(board=(COPY_WATCH,));self.play(g);self.play(g,AURA)
        self.assertEqual(len(self.programs(g)),2);self.owner(g);self.assertEqual(self.armor(g),4)
        self.portable(g)

    def test_c02_wrapper_without_material_fails_explicitly_and_rolls_back(self):
        g=self.game((CARD,ARMOR,BASE));self.play(g);self.play(g,BASE)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,AURA)
        self.assertEqual(g.snapshot(),before)

    def test_c03_ordinary_aura_created_by_end_cast_waits_until_next_end(self):
        g=self.game((CARD,NESTED));self.play(g);self.owner(g)
        self.assertEqual(self.armor(g),0)
        self.owner(g);self.assertEqual(self.armor(g),7)
        self.assertEqual(len(self.inner(g,NESTED)),2)

    def test_c04_full_area_keeps_existing_program_and_consumes_new_wrapper_cast(self):
        g=self.game((CARD,CARD,ARMOR,VALUE),capacity=1);self.play(g);self.owner(g);self.play(g)
        self.assertEqual(len(self.programs(g)),1)
        self.assertEqual(len(g.state.spell_aura_history),2)
        self.assertEqual(sum(c.card_id==AURA for c in g.state.cast_history),2)
        self.assertTrue(any(e.kind=='player_effect_failed' for e in g.events));self.portable(g)

    def test_d00_actual_timer_choice_restores_clone_replays_and_resumes_once(self):
        g=self.game(board=(WATCH,));self.play(g);self.end(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((self.armor(g),len(self.inner(g))),(2,1))
        restored=self.portable(g)
        for game in (g,restored):
            q=game.state.pending_choice;game.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(restored.snapshot(),g.snapshot())
        self.assertEqual((self.armor(g),len(self.inner(g)),g.state.active_player),(3,1,2))

    def test_d01_failure_rolls_back_entire_end_rng_material_and_countdown(self):
        g=self.game((CARD,FAIL));self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.end(g)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_d02_lethal_cast_stops_remaining_timers_and_turn_switch(self):
        g=self.game((CARD,LETHAL));self.play(g);self.end(g)
        self.assertNotEqual(g.state.status,'playing');self.assertEqual(len(self.inner(g,LETHAL)),1)
        self.assertEqual(g.state.active_player,1)

    def test_d03_snapshot_candidate_material_and_event_inventory_tampering_rejected(self):
        from hs_sim.engine.serialization import canonical_hash
        g=self.game((CARD,ARMOR,VALUE));self.play(g)
        for mutate in ('cost','card','event','beneficiary'):
            with self.subTest(mutate=mutate):
                s=deepcopy(g.snapshot())
                if mutate=='cost':s['state']['spell_aura_history'][0]['costs'][0]+=1
                elif mutate=='card':s['state']['spell_aura_history'][0]['card']['local']['base_cost']+=1
                elif mutate=='event':s['events']=[e for e in s['events']if e['kind']!='hand_spell_aura_created']
                else:s['state']['players']['1']['player_effects'][0]['spell_aura_player_id']=2
                # Hash differences are independently rejected; the state/receipt
                # validators below also run directly on typed altered material.
                with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry('reader'))
        from hs_sim.engine.spell_auras import validate_state,validate_boundary
        bad=deepcopy(g.state);bad.spell_aura_history[0]=replace(bad.spell_aura_history[0],costs=(100,5))
        with self.assertRaises(ValueError):validate_state(bad,g.registry)
        original=g._state.spell_aura_history[0]
        g._state.spell_aura_history[0]=replace(original,card=replace(original.card,
            local=replace(original.card.local,base_cost=original.card.local.base_cost+1)))
        with self.assertRaises(ValueError):validate_boundary(g)

    def test_d04_strict_program_request_and_wrong_beneficiary_pending_body_rejected(self):
        for pid in (True,0,3):
            with self.subTest(pid=pid),self.assertRaises(ValueError):CastHighestHandSpellAsAura(pid,AURA,1)
        with self.assertRaises(ValueError):PlayerEffectSpec('bad',AURA,stored_spell=True)
        g=self.game();self.play(g);instance=self.programs(g)[0]
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        good=CastAuraSpell(1,instance);self.assertEqual(codec.decode(codec.encode(good)),good)
        with self.assertRaises(ValueError):codec.encode(CastAuraSpell(2,instance))

    def test_e00_player_view_reveals_cast_spell_but_no_candidates_ids_or_rng(self):
        g=self.game((CARD,ARMOR,VALUE));self.play(g)
        for pid in (1,2):
            view=g.for_player(pid).observe();wire=json.dumps(view)+json.dumps(g.player_events(pid))
            self.assertIn('"cast_card_id": "'+VALUE+'"',wire)
            for key in ('"spell_aura_history"','"spell_aura_id"','"source_allocation"','"rng_before"','"candidates"','"record_hash"'):
                self.assertNotIn(key,wire)

    def test_e01_second_player_uses_its_own_program_and_owner_ends(self):
        g=self.game((FILL,),enemy_hand=(CARD,ARMOR));self.end(g);self.play(g)
        self.owner(g,2);self.assertEqual((self.armor(g,1),self.armor(g,2)),(0,2))
        self.assertEqual(self.programs(g,2)[0].remaining_turns,2);self.portable(g)


if __name__=='__main__':unittest.main()
