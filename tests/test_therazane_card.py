"""Real Therazane: independent school budgets, actual CASTs and durable one-use history."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.therazane_card import CARD,load_batch,register_therazane_card
from hs_sim.cards.amitut_card import CARD as AMITUT,register_amitut_card
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,
    SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.card_spell_repeats import GrantCardSpellRepeat,validate_automatic_proof
from hs_sim.engine.effects import (ChoiceOption,Destroy,Draw,GainArmor,InvokeBehavior,
    RequestChoice,Silence,ChangeControl)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardClass,CardMetadata,CastWhenDrawnSpec,Keyword,
    RecipientMetadataFilter,RepeatCostFilter,RepeatMatchSpec,RewindSpec,SpellRepeatSpec,SpellSchool,TargetSpec)
from hs_sim.engine.one_cost_casts import RepeatAutomaticSpell
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell,CastStoredSpell
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.spell_modifiers import (AddSpellRepeatModifier,RemoveSpellRepeatModifier,
    MATERIAL,AUTOMATIC_CAST)
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.zones import CardReference,ReorderZone
from tools.card_batch import canonical,check_face

P='fixture.therazane.'
REWIND=P+'rewind'
SCHOOLS={s:P+s.value for s in SpellSchool}
NATURE,HOLY=SCHOOLS[SpellSchool.NATURE],SCHOOLS[SpellSchool.HOLY]
FILL,PLAIN,AUTO,DRAW,DRAWN,HISTORY,FAILED,TARGETED,STORED,LEGACY,REMOVE,TOP,SOURCE,NATIVE,WATCH,COUNTER=(
    P+x for x in ('fill','plain','auto','draw','drawn','history','failed','targeted','stored',
        'legacy','remove','top','source','native','watch','counter'))
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


def school_spec(school):
    return SpellRepeatSpec(2,'any',RepeatMatchSpec(
        recipient_metadata=RecipientMetadataFilter(spell_schools=(school,))))


@lru_cache(maxsize=None)
def fixture(mode=None,role='writer'):
    assert role in ('writer','reader')
    r=build_registry();register_therazane_card(r);register_amitut_card(r)
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,health=12,metadata=META))
    def fail(c):raise ResolutionError('Therazane deliberate failure')
    r.register_behavior(P+'fail',fail)
    def body(c):
        work=(GainArmor(c.player_id,2),)
        if mode=='install' and r.card(c.cast.card_id).spell_school==SpellSchool.NATURE:
            return (*work,AddSpellRepeatModifier(c.player_id,school_spec(SpellSchool.NATURE),
                c.source_id,uses=1,automatic=True))
        if mode=='fail':return (*work,InvokeBehavior(P+'fail',c.source_id,c.player_id))
        if mode=='wait_body':return (*work,wait(c))
        return work
    def wait(c):
        return RequestChoice(3-c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',
            (InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id)
    for school,cid in SCHOOLS.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=cid,spell_school=school,metadata=META))
    r.register_behavior(REWIND,body)
    r.register_card(CardDefinition(REWIND,REWIND,CardType.SPELL,cost=1,on_play=REWIND,
        spell_school=SpellSchool.NATURE,metadata=META,keywords=(Keyword.REWIND,),rewind=RewindSpec(1)))
    for cid,school,native,target in ((DRAWN,SpellSchool.NATURE,True,None),
            (TARGETED,SpellSchool.NATURE,False,TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy'))):
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=cid,spell_school=school,
            metadata=META,targeting=target,keywords=(Keyword.CASTS_WHEN_DRAWN,) if native else (),
            cast_when_drawn=CastWhenDrawnSpec() if native else None))
    def stored(c):
        e=next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==NATURE)
        ref=CardReference.capture(e)
        return (GrantCardSpellRepeat(ref,source_id=c.source_id,automatic=True),
            CastStoredSpell(ref,c.player_id,c.source_id,choices='player'))
    def remove(c):
        m=next(m for m in c.state.players[c.player_id].spell_modifiers
            if m.spec.match.recipient_metadata.spell_schools==(SpellSchool.FIRE,))
        return (RemoveSpellRepeatModifier(c.player_id,m.id),)
    def top(c):
        deck=c.state.players[c.player_id].deck
        target=next(i for i in deck if any(a.draw_cast is not None for a in c.state.entities[i].abilities))
        return (ReorderZone(c.player_id,Zone.DECK,(target,*(i for i in deck if i!=target))),)
    def source(c):
        e=next(c.state.entities[i] for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD)
        if mode=='silence':return (Silence(e.id),)
        if mode=='control':return (ChangeControl(e.id,3-c.player_id),)
        return (Destroy(e.id,c.source_id),)
    bodies={PLAIN:lambda c:(GainArmor(c.player_id,1),),
        AUTO:lambda c:(CastSpell(c.player_id,NATURE,c.source_id,choices='player'),),
        DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),
        HISTORY:lambda c:(RecastSpell(c.player_id,next(x.id for x in c.state.cast_history if x.card_id==NATURE),c.source_id,choices='player'),),
        FAILED:lambda c:(CastSpell(c.player_id,TARGETED,c.source_id),),
        STORED:stored,LEGACY:lambda c:(AddSpellRepeatModifier(c.player_id,school_spec(SpellSchool.NATURE),c.source_id,uses=1),),
        REMOVE:remove,TOP:top,SOURCE:source,COUNTER:lambda c:(SetSecret(3-c.player_id,'EX1_287'),)}
    for cid,fn in bodies.items():
        r.register_behavior(cid,fn);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META))
    r.register_card(CardDefinition(NATIVE,NATIVE,CardType.MINION,health=12,metadata=META,
        spell_repeats=(SpellRepeatSpec(2,'any',RepeatMatchSpec(
            recipient_cost=RepeatCostFilter('cast_quote',minimum=1,maximum=1))),)))
    if mode in ('wait_use','wait_start'):
        def watch(c):
            if mode=='wait_use':
                if dict(c.event.data).get('play_id') is not None:return ()
            else:
                row=c.state.cast_history[dict(c.event.data)['cast_id']-1]
                if r.card(row.card_id).spell_school!=SpellSchool.NATURE:return ()
            return (wait(c),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=12,metadata=META,
            triggers=(TriggerSpec('spell_modifier_used' if mode=='wait_use' else 'spell_cast_started',WATCH),)))
    return r


class TherazaneTests(unittest.TestCase):
    def game(self,mode=None,*,hand=(CARD,NATURE),deck=(FILL,)*6,board=(),seat=1):
        self.mode,self.seat=mode,seat
        own=PlayerSetup('HERO_08',hand=hand,deck=deck,
            board=board+((WATCH,) if mode in ('wait_use','wait_start') else ()),mana=30,max_mana=30,mana_cap=30)
        other=PlayerSetup('HERO_01',hand=(NATURE,),deck=(FILL,)*6,mana=30,max_mana=30,mana_cap=30)
        return Game.from_scenario(Scenario((own,other) if seat==1 else (other,own),active_player=seat,seed=373),fixture(mode))
    def play(self,g,cid=CARD):
        pid=self.seat;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid));return eid
    def casts(self,g,cid=NATURE):return [x for x in g.state.cast_history if x.card_id==cid]
    def mods(self,g,pid=None):return g.state.players[self.seat if pid is None else pid].spell_modifiers
    def armor(self,g):return g.state.entities[g.state.players[self.seat].hero_id].armor
    def settle(self,g):
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
    def restore(self,g,*,replay_too=True):
        s=json.loads(json.dumps(g.snapshot()));r=fixture(self.mode,'reader')
        copies=(g.clone(),Game.from_snapshot(s,r))
        if replay_too:copies=(*copies,replay(build_replay(g),r))
        for other in copies:self.assertTrue(other.snapshot()==s,'Original school uses and actual CAST plans must restore')
        return Game.from_snapshot(s,r)
    def pending(self,g):return next(w for w in (*g._frame.prefix,*g._frame.continuation) if type(w) is RepeatAutomaticSpell)
    def reject(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error:Game.from_snapshot(s,fixture(self.mode,'reader'))
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_complete_root_and_two_primary_faces_keep_actual_elemental_battlecry(self):
        d=load_batch();raw=d['cards'][0]['record'];self.assertEqual(canonical(raw),d['cards'][0]['record_sha256'])
        self.assertEqual(len(d['official_observations']),2)
        for o in d['official_observations']:check_face(raw,o['face'],o['locale'])
        card=fixture().card(CARD);self.assertEqual((card.cost,card.attack,card.health),(6,5,5))
        self.assertEqual(card.metadata.tribes,('elemental',));self.assertFalse(d['behavior_verified']);self.assertFalse(d['cn_calibrated'])

    def test_actual_six_mana_battlecry_installs_seven_independent_source_bound_uses(self):
        g=self.game();eid=self.play(g);mods=self.mods(g)
        self.assertEqual(g.state.players[1].mana,24);self.assertEqual(len(mods),7)
        self.assertEqual({m.spec.match.recipient_metadata.spell_schools[0] for m in mods},set(SpellSchool))
        self.assertEqual(len({m.id for m in mods}),7)
        self.assertTrue(all((m.source_id,m.source_card_id,m.uses_remaining,m.automatic)==(eid,CARD,1,True) for m in mods))
        self.restore(g)

    def test_each_school_first_hand_spell_casts_twice_and_next_casts_once_with_single_payments(self):
        g=self.game(hand=(CARD,*SCHOOLS.values(),NATURE));self.play(g)
        for cid in SCHOOLS.values():
            self.play(g,cid);self.assertEqual(len(self.casts(g,cid)),2)
        self.assertFalse(self.mods(g));self.assertEqual(self.armor(g),28)
        self.play(g,NATURE);self.assertEqual(len(self.casts(g)),3);self.assertEqual(g.state.players[1].mana,16)
        self.assertEqual(len(g.state.spell_policy_receipts),7);self.restore(g)

    def test_schoolless_spell_and_enemy_hand_play_do_not_consume_the_players_school(self):
        g=self.game(hand=(CARD,PLAIN,NATURE));self.play(g);self.play(g,PLAIN)
        self.assertEqual((len(self.mods(g)),self.armor(g)),(7,1))
        g.apply(EndTurn(1));eid=next(i for i in g.state.players[2].hand if g.state.entities[i].card_id==NATURE)
        g.apply(PlayCard(2,eid));self.assertEqual(len(self.mods(g)),7)
        self.assertEqual(len(self.casts(g)),1);g.apply(EndTurn(2));self.play(g,NATURE)
        self.assertEqual(len(self.casts(g)),3);self.assertEqual(len(self.mods(g)),6)

    def test_two_independent_battlecries_overlap_at_two_and_consume_both_matching_uses(self):
        g=self.game(hand=(CARD,CARD,NATURE,NATURE));self.play(g);self.play(g)
        self.assertEqual(len(self.mods(g)),14);self.play(g,NATURE)
        self.assertEqual((len(self.casts(g)),len(self.mods(g)),self.armor(g)),(2,12,4))
        self.assertEqual(len(g.state.spell_policy_receipts[-1].modifiers),2)
        self.play(g,NATURE);self.assertEqual(len(self.casts(g)),3);self.restore(g)

    def test_source_death_silence_and_control_change_do_not_revoke_player_budgets(self):
        for mode in (None,'silence','control'):
            with self.subTest(mode=mode):
                g=self.game(mode,hand=(CARD,SOURCE,NATURE));self.play(g);self.play(g,SOURCE)
                self.assertEqual(len(self.mods(g)),7);self.play(g,NATURE)
                self.assertEqual((len(self.casts(g)),len(self.mods(g))),(2,6));self.restore(g,replay_too=False)

    def test_effect_cast_uses_original_school_once_and_has_two_real_casts_without_extra_payment(self):
        g=self.game(hand=(CARD,AUTO,NATURE));self.play(g);self.play(g,AUTO)
        rows=self.casts(g);self.assertEqual([x.origin for x in rows],['effect','native_repeat'])
        self.assertEqual(rows[1].recast_id,rows[0].id);self.assertTrue(all(x.completed for x in rows))
        self.assertEqual((self.armor(g),len(self.mods(g)),g.state.players[1].mana),(4,6,24))
        self.assertEqual(len(g.state.play_history),2);self.play(g,NATURE)
        self.assertEqual((len(self.casts(g)),self.armor(g)),(3,6));self.restore(g)

    def test_countered_hand_spell_keeps_original_commit_consumption_and_next_spell_casts_once(self):
        g=self.game(hand=(CARD,COUNTER,NATURE,NATURE));self.play(g);self.play(g,COUNTER);self.play(g,NATURE)
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual((len(self.mods(g)),self.armor(g)),(6,0))
        self.assertEqual(len(g.state.spell_policy_receipts),1);self.play(g,NATURE)
        self.assertEqual(self.armor(g),2);self.restore(g)

    def test_printed_cast_when_drawn_repeats_cast_not_physical_draw_or_replacement(self):
        g=self.game(hand=(CARD,DRAW),deck=(DRAWN,FILL,FILL));self.play(g);self.play(g,DRAW)
        self.assertEqual([x.origin for x in self.casts(g,DRAWN)],['draw','native_repeat'])
        self.assertEqual(len(g.state.draw_history),2);self.assertEqual(len(g.state.players[1].hand),1)
        self.assertEqual((len(self.mods(g)),self.armor(g)),(6,4));self.restore(g)

    def test_real_amitut_granted_copy_draw_uses_holy_school_and_replaces_only_once(self):
        g=self.game(hand=(CARD,AMITUT,TOP,DRAW),deck=(HOLY,FILL,FILL));self.play(g);self.play(g,AMITUT)
        self.play(g,TOP);self.play(g,DRAW)
        self.assertEqual([x.origin for x in self.casts(g,HOLY)],['draw','native_repeat'])
        self.assertIsNotNone(g.state.draw_history[0].cast_grant);self.assertEqual(len(g.state.draw_history),2)
        self.assertEqual((len(self.mods(g)),self.armor(g)),(6,4));self.restore(g)

    def test_history_recast_uses_current_unspent_school_with_one_new_parent_and_child(self):
        g=self.game(hand=(NATURE,CARD,HISTORY));self.play(g,NATURE);self.play(g);self.play(g,HISTORY)
        self.assertEqual([x.origin for x in self.casts(g)],['hand','history','native_repeat'])
        self.assertEqual((len(self.mods(g)),self.armor(g)),(6,6));self.restore(g)

    def test_failed_automatic_target_does_not_spend_unaccepted_school_local_policy(self):
        g=self.game(hand=(CARD,FAILED,NATURE));self.play(g);self.play(g,FAILED)
        self.assertIsNotNone(self.casts(g,TARGETED)[0].failure);self.assertEqual(len(self.mods(g)),7)
        self.assertFalse(any(x.origin=='native_repeat' for x in g.state.cast_history))
        self.play(g,NATURE);self.assertEqual(len(self.casts(g)),2);self.restore(g)

    def test_legacy_hand_only_policy_is_not_consumed_by_automatic_school_cast(self):
        g=self.game(hand=(CARD,LEGACY,AUTO,NATURE));self.play(g);self.play(g,LEGACY);self.play(g,AUTO)
        self.assertEqual(len(self.mods(g)),7);self.assertEqual(sum(not m.automatic for m in self.mods(g)),1)
        self.play(g,NATURE);self.assertEqual(len(self.casts(g)),4);self.assertTrue(all(m.automatic for m in self.mods(g)))
        self.restore(g)

    def test_card_property_native_provider_and_player_school_budget_share_one_actual_extra_cast(self):
        g=self.game(hand=(CARD,STORED,NATURE),board=(NATIVE,));self.play(g);self.play(g,STORED)
        self.assertEqual((len(self.casts(g)),self.armor(g),len(self.mods(g))),(2,4,6));self.restore(g)

    def test_new_school_budget_installed_in_body_is_not_consumed_by_original_repeat_child(self):
        g=self.game('install',hand=(CARD,AUTO));self.play(g);self.play(g,AUTO)
        self.assertEqual(len(self.casts(g)),2)
        nature=[m for m in self.mods(g) if m.spec.match.recipient_metadata.spell_schools==(SpellSchool.NATURE,)]
        self.assertEqual(len(nature),2);self.assertEqual(len(self.mods(g)),8);self.restore(g)

    def test_explicit_removal_retires_only_the_selected_unspent_school(self):
        fire=SCHOOLS[SpellSchool.FIRE];g=self.game(hand=(CARD,REMOVE,fire,NATURE))
        self.play(g);self.play(g,REMOVE);self.assertEqual(len(self.mods(g)),6)
        self.play(g,fire);self.assertEqual(len(self.casts(g,fire)),1)
        self.play(g,NATURE);self.assertEqual(len(self.casts(g)),2);self.restore(g)

    def test_waiting_during_auto_use_start_and_both_bodies_restores_and_replays_without_respends(self):
        for mode in ('wait_use','wait_start','wait_body'):
            with self.subTest(mode=mode):
                g=self.game(mode,hand=(CARD,AUTO));self.play(g);self.play(g,AUTO)
                waits=0
                while g.state.pending_choice:
                    waits+=1;self.assertEqual(len(self.mods(g)),6);g=self.restore(g)
                    q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
                self.assertGreaterEqual(waits,1);self.assertEqual((len(self.casts(g)),self.armor(g)),(2,4));self.restore(g)

    def test_waiting_manual_first_and_second_body_share_one_original_consumption(self):
        g=self.game('wait_body');self.play(g);self.play(g,NATURE);waits=0
        while g.state.pending_choice:
            waits+=1;self.assertEqual(len(self.mods(g)),6);g=self.restore(g)
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual((waits,len(g.state.spell_policy_receipts),self.armor(g)),(2,1,4))

    def test_failed_action_rolls_back_school_use_and_failed_choice_preserves_prior_consumption(self):
        g=self.game('fail',hand=(CARD,AUTO));self.play(g);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):self.play(g,AUTO)
        self.assertTrue(g.snapshot()==before);self.assertEqual(len(self.mods(g)),7)
        g=self.game('wait_body',hand=(CARD,AUTO));self.play(g);self.play(g,AUTO);before=g.snapshot();q=g.state.pending_choice
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):g.apply(SelectChoice(q.player_id,q.id,('fail',)))
        self.assertTrue(g.snapshot()==before);self.assertEqual(len(self.mods(g)),6);self.settle(g);self.restore(g)

    def test_original_rewind_retry_retires_old_use_witness_and_restores_one_school_consumption(self):
        g=self.game(hand=(CARD,REWIND));self.play(g);self.play(g,REWIND)
        self.assertIsNotNone(g.state.pending_choice);g=self.restore(g)
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('retry',)))
        choices=0
        while g.state.pending_choice:
            choices+=1;self.assertLess(choices,4);g=self.restore(g)
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('accept',)))
        self.assertEqual((len(self.mods(g)),len(g.state.spell_policy_receipts),self.armor(g)),(6,1,4))
        self.assertEqual(len(self.casts(g,REWIND)),2);self.restore(g)

    def test_second_seat_and_two_player_views_hide_original_inventory_and_consumption_proofs(self):
        g=self.game('wait_body',hand=(CARD,AUTO),seat=2);self.play(g);self.play(g,AUTO)
        self.assertEqual(self.casts(g)[0].player_id,2);self.assertEqual(len(self.mods(g,1)),0)
        for pid in (1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for private in (MATERIAL,AUTOMATIC_CAST,'player_modifiers','modifier_hero_class','card_proof','before_state'):
                self.assertNotIn(private,public)
        self.restore(g)

    def test_live_unused_school_cannot_be_dropped_or_rewritten_after_rehash(self):
        g=self.game();self.play(g);s=g.snapshot()
        for change in ('drop','flag','school'):
            with self.subTest(change=change):
                bad=deepcopy(s);mods=bad['state']['players']['1']['spell_modifiers']
                if change=='drop':mods.pop()
                elif change=='flag':mods[0]['automatic']=False
                else:mods[0]['spec']['match']['recipient_metadata']['spell_schools']=['nature']
                self.reject(bad)

    def test_private_addition_and_automatic_use_witnesses_cannot_be_removed_or_rebound(self):
        g=self.game(hand=(CARD,AUTO));self.play(g);self.play(g,AUTO);s=g.snapshot()
        for change in ('add','use','cast'):
            with self.subTest(change=change):
                bad=deepcopy(s)
                event=next(e for e in bad['events'] if (MATERIAL if change=='add' else AUTOMATIC_CAST) in dict(e['data']))
                data=dict(event['data'])
                if change=='add':del data[MATERIAL]
                elif change=='use':del data[AUTOMATIC_CAST]
                else:data[AUTOMATIC_CAST]+=1
                event['data']=list(data.items())
                self.reject(bad)

    def test_pending_plan_requires_complete_original_school_inventory_and_matching_source_window(self):
        g=self.game('wait_body',hand=(CARD,AUTO));self.play(g);self.play(g,AUTO);work=self.pending(g)
        proof=work.card_proof;self.assertEqual(len(proof.plan.player_modifiers),1)
        before=deepcopy(proof.before_state)
        before.players[1].spell_modifiers=[m for m in before.players[1].spell_modifiers if m.id!=proof.plan.player_modifiers[0].id]
        with self.assertRaisesRegex(ValueError,'original grants'):
            validate_automatic_proof(replace(proof,before_state=before),fixture(self.mode))
        with self.assertRaises(ValueError):replace(proof.plan,player_modifiers=())

    def test_automatic_policy_rejects_unbounded_unscoped_multi_school_or_missing_source_declarations(self):
        valid=dict(player_id=1,spec=school_spec(SpellSchool.NATURE),source_id=1,uses=1,automatic=True)
        AddSpellRepeatModifier(**valid)
        for delta in ({'uses':None},{'uses':2},{'uses':True},{'source_id':None},{'expires_turn':3},
                {'automatic':1},{'spec':SpellRepeatSpec(2,'any')},
                {'spec':SpellRepeatSpec(2,'any',RepeatMatchSpec(recipient_metadata=RecipientMetadataFilter(
                    spell_schools=(SpellSchool.NATURE,SpellSchool.FIRE))))}):
            with self.subTest(delta=delta):
                with self.assertRaises(ValueError):AddSpellRepeatModifier(**dict(valid,**delta))
