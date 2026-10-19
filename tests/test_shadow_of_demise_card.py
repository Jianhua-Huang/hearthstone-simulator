"""Native Shadow copies current cast material without replaying acquisitions."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.shadow_of_demise_card import CARD, IDENTITY, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction, PlayCard,
    PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (ChoiceOption, Draw, GainArmor, InvokeBehavior, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CostSpec, SpellMirrorBinding, TargetSpec
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_mirrors import source as mirror_source
from hs_sim.engine.stored_spell_damage import GrantStoredSpellDamage
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard, ModifyStoredCost, MoveCard
from hs_sim.targets import canonical_digest

P='shadow.test.'
FIRE='CORE_CS2_029'
FROST='CORE_CS2_024'
DRAW='CORE_CS2_023'
PLAIN='CORE_CS2_182'
MAP='TLC_515'


@lru_cache(None)
def registry(mode=None):
    r=build_registry()
    def first(c):
        return next(c.state.entities[i] for i in c.state.players[c.player_id].hand if mirror_source(c.state.entities[i]) is not None)
    def boost(c):
        ref=CardReference.capture(c.state.entities[c.target_id])
        return (ModifyStoredCost(ref,CostSpec(delta=-2),c.source_id),GrantStoredSpellDamage(ref,2,c.source_id))
    def fail(c):raise ResolutionError('Shadow deliberate failure')
    bodies={
        'boost':boost,
        'copy':lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,source_id=c.source_id),),
        'base':lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,mode='base',source_id=c.source_id),),
        'external':lambda c:(TransformStoredCard(CardReference.capture(c.state.entities[c.target_id]),FROST,c.source_id),),
        'deck':lambda c:(MoveCard(CardReference.capture(first(c)),c.player_id,Zone.DECK,position='top',source_id=c.source_id),),
        'transfer':lambda c:(MoveCard(CardReference.capture(first(c)),3-c.player_id,Zone.HAND,source_id=c.source_id),),
        'draw':lambda c:(Draw(c.player_id,source_id=c.source_id),),
        'fail':fail,
    }
    for name,body in bodies.items():
        cid=P+name;r.register_behavior(cid,body)
        target=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.SPELL,),relation='friendly') if name in ('boost','copy','base','external') else None
        r.register_card(CardDefinition(cid,name,CardType.SPELL,cost=1,on_play=cid,targeting=target))
    if mode:
        def watch(c):
            if mode=='auto':
                return (CastSpell(c.player_id,FIRE,c.source_id,target_id=c.state.players[3-c.player_id].hero_id,targeting='explicit'),) if c.event.player_id==c.player_id else ()
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            values=[e for e in c.state.entities.values() if e.zone==Zone.HAND and mirror_source(e) is not None]
            casts={mirror_source(e).spell_mirror.cast_id for e in values}
            if len(casts)>1:raise ResolutionError('Shadow batch was only partly transformed at first notice')
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(P+'watch','Observer',CardType.MINION,health=20,
            triggers=(TriggerSpec('turn_ended' if mode=='auto' else 'stored_card_transformed',P+'watch'),)))
    r.validate();return r


class ShadowOfDemiseTests(unittest.TestCase):
    def game(self,hand=(CARD,),deck=(),board=(),other_hand=(),other_deck=(),mode=None,seat=1):
        own=PlayerSetup('HERO_08',hand=hand,deck=deck,board=(*((P+'watch',)if mode else()),*board),
            mana=50,max_mana=50,mana_cap=50)
        other=PlayerSetup('HERO_08',hand=other_hand,deck=other_deck,mana=50,max_mana=50,mana_cap=50)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,seed=279),registry(mode))

    def mirrors(self,g,seat=1):
        return [g.state.entities[i]for i in g.state.players[seat].hand if mirror_source(g.state.entities[i]) is not None]

    def eid(self,g,cid):
        return next(i for i in reversed(g.state.players[g.state.active_player].hand) if g.state.entities[i].card_id==cid)

    def play(self,g,cid=None,*,eid=None,target=None):
        eid=self.eid(g,cid)if eid is None else eid
        card=g.registry.card(g.state.entities[eid].card_id);seat=g.state.active_player
        if target is None and g.state.entities[eid].card_id in (FIRE,FROST):target=g.state.players[3-seat].hero_id
        g.apply(PlayCard(seat,eid,target_id=target,position=len(g.state.players[seat].board)if card.kind==CardType.MINION else None))
        return eid

    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g,mode=None):
        saved=json.loads(json.dumps(g.snapshot()));r=registry.__wrapped__(mode);self.assertIsNot(r,g.registry)
        other=Game.from_snapshot(saved,r);self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry.__wrapped__(mode)).snapshot(),saved)
        return other

    def reject(self,saved,mode=None):
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry.__wrapped__(mode))

    def test_a01_complete_core_and_legacy_sources_strict_zero_cost_and_printed_identity(self):
        data=load_batch();self.assertEqual(len(data['evidence_only']),3)
        for row in (*data['cards'],*data['evidence_only']):self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(len(data['official_observations']),2)
        card=registry().card(CARD)
        self.assertEqual((card.cost,card.metadata.deck_identity,card.manual_playable),(0,IDENTITY,False))

    def test_a02_original_empty_shadow_has_native_hand_source_and_cannot_be_played(self):
        g=self.game();shadow=self.mirrors(g)[0];saved=g.snapshot()
        self.assertIsNone(mirror_source(shadow).spell_mirror.cast_id)
        self.assertFalse(any(isinstance(a,PlayCard)and a.entity_id==shadow.id for a in g.legal_actions()))
        with self.assertRaises(IllegalAction):self.play(g,eid=shadow.id)
        self.assertEqual(g.snapshot(),saved)

    def test_a03_non_spell_play_does_not_enable_empty_shadow(self):
        g=self.game(hand=(CARD,PLAIN));wid=self.mirrors(g)[0].id;self.play(g,PLAIN)
        self.assertEqual(g.state.entities[wid].card_id,CARD)
        with self.assertRaises(IllegalAction):self.play(g,eid=wid)

    def test_a04_real_cast_transforms_same_physical_hand_card_then_copy_pays_and_casts_normally(self):
        g=self.game(hand=(CARD,FIRE));wid=self.mirrors(g)[0].id
        self.play(g,FIRE);self.assertEqual(g.state.entities[wid].card_id,FIRE)
        self.assertEqual(g.state.entities[wid].cost,4)
        self.play(g,eid=wid)
        self.assertEqual(g.state.players[1].mana,42)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,18)
        self.assertIsNone(mirror_source(g.state.entities[wid]))
        self.assertEqual(len(g.state.cast_history),2)

    def test_a05_subsequent_cast_replaces_current_form_but_keeps_same_native_source(self):
        g=self.game(hand=(CARD,FIRE,FROST));wid=self.mirrors(g)[0].id;aid=mirror_source(self.mirrors(g)[0]).id
        self.play(g,FIRE);self.play(g,FROST)
        shadow=g.state.entities[wid]
        self.assertEqual(shadow.card_id,FROST);self.assertEqual(mirror_source(shadow).id,aid)
        self.assertEqual(mirror_source(shadow).spell_mirror.cast_id,2)

    def test_a06_exact_copy_keeps_source_discount_and_local_spell_damage(self):
        g=self.game(hand=(CARD,FIRE,P+'boost'));wid=self.mirrors(g)[0].id;fire=self.eid(g,FIRE)
        self.play(g,P+'boost',target=fire);self.play(g,eid=fire)
        self.assertEqual(g.state.entities[wid].cost,2)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,22)
        self.play(g,eid=wid)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,14)
        self.assertEqual(g.state.players[1].mana,45)

    def test_a07_multiple_shadows_are_fully_transformed_before_first_notice(self):
        g=self.game(hand=(CARD,CARD,FIRE),mode='wait');self.play(g,FIRE)
        self.assertEqual([e.card_id for e in self.mirrors(g)],[FIRE,FIRE])
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        self.choose(g);self.choose(g)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,24)

    def test_a08_other_players_spell_does_not_change_my_shadow(self):
        g=self.game(other_hand=(FIRE,));g.apply(EndTurn(1));self.play(g,FIRE)
        self.assertEqual(self.mirrors(g)[0].card_id,CARD)

    def test_a09_countered_spell_has_no_accepted_cast_to_copy(self):
        g=self.game(hand=(CARD,FIRE),other_hand=('CORE_EX1_287',))
        g.apply(EndTurn(1));self.play(g,'CORE_EX1_287');g.apply(EndTurn(2));self.play(g,FIRE)
        self.assertTrue(g.state.play_history[-1].countered)
        self.assertEqual(self.mirrors(g)[0].card_id,CARD)

    def test_a10_automatic_actual_spell_payload_updates_held_shadow_without_paid_play(self):
        g=self.game(mode='auto');self.play_count=len(g.state.play_history);g.apply(EndTurn(1))
        self.assertEqual(self.mirrors(g)[0].card_id,FIRE)
        self.assertEqual(len(g.state.play_history),self.play_count)
        self.assertEqual(g.state.cast_history[-1].origin,'effect')

    def test_a11_shadow_drawn_by_current_spell_does_not_backfill_that_spell(self):
        g=self.game(hand=(DRAW,),deck=(CARD,PLAIN));self.play(g,DRAW)
        shadow=self.mirrors(g)[0];self.assertEqual(shadow.card_id,CARD)
        self.assertIsNone(mirror_source(shadow).spell_mirror.cast_id)
        with self.assertRaises(IllegalAction):self.play(g,eid=shadow.id)

    def test_a12_existing_shadow_copies_draw_while_newly_drawn_shadow_stays_empty(self):
        g=self.game(hand=(CARD,DRAW),deck=(CARD,PLAIN));wid=self.mirrors(g)[0].id;self.play(g,DRAW)
        self.assertEqual(g.state.entities[wid].card_id,DRAW)
        self.assertEqual(sorted(e.card_id for e in self.mirrors(g)),sorted((DRAW,CARD)))

    def test_a13_real_cultist_map_delivers_original_unplayable_shadow_without_late_activation(self):
        g=self.game(hand=(MAP,),deck=(CARD,PLAIN));original=next(i for i in g.state.players[1].deck if g.state.entities[i].card_id==CARD)
        self.play(g,MAP);self.portable(g)
        option=next(o for o in g.state.pending_choice.options if o.card_id==CARD)
        self.choose(g,option.id)
        self.assertIn(original,g.state.players[1].hand)
        self.assertEqual(g.state.entities[original].card_id,CARD)
        with self.assertRaises(IllegalAction):self.play(g,eid=original)
        self.portable(g)

    def test_a14_current_hand_copy_keeps_binding_and_fresh_self_source(self):
        g=self.game(hand=(CARD,P+'copy',FROST));wid=self.mirrors(g)[0].id
        self.play(g,P+'copy',target=wid)
        mirrors=self.mirrors(g);self.assertEqual(len(mirrors),2)
        self.assertTrue(all(mirror_source(e).source_id==e.id for e in mirrors))
        self.play(g,FROST);self.assertTrue(all(e.card_id==FROST for e in self.mirrors(g)))
        self.portable(g)

    def test_a15_base_hand_copy_drops_original_mirror_and_remains_ordinary_spell(self):
        g=self.game(hand=(CARD,P+'base',FROST));wid=self.mirrors(g)[0].id
        self.play(g,P+'base',target=wid)
        ordinary=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==P+'base' and mirror_source(g.state.entities[i])is None]
        self.assertEqual(len(ordinary),1);oid=ordinary[0].id
        self.play(g,FROST);self.assertEqual(g.state.entities[oid].card_id,P+'base')

    def test_a16_ordinary_external_transform_retires_original_source(self):
        g=self.game(hand=(CARD,P+'external',FIRE));wid=self.mirrors(g)[0].id
        self.play(g,P+'external',target=wid)
        self.assertIsNone(mirror_source(g.state.entities[wid]));self.play(g,FIRE)
        self.assertEqual(g.state.entities[wid].card_id,FROST)

    def test_a17_departure_and_later_draw_does_not_reinstall_retired_source_on_copied_face(self):
        g=self.game(hand=(CARD,P+'deck',P+'draw',FIRE));wid=self.mirrors(g)[0].id
        self.play(g,P+'deck');self.assertIsNone(mirror_source(g.state.entities[wid]))
        self.play(g,P+'draw');self.play(g,FIRE)
        self.assertEqual(g.state.entities[wid].card_id,P+'deck');self.assertIsNone(mirror_source(g.state.entities[wid]))

    def test_a18_original_nonreset_hand_transfer_keeps_current_form_then_follows_new_holder(self):
        g=self.game(hand=(CARD,P+'transfer',FIRE),other_hand=(FROST,));wid=self.mirrors(g)[0].id
        self.play(g,P+'transfer');self.assertIn(wid,g.state.players[2].hand)
        self.play(g,FIRE);self.assertEqual(g.state.entities[wid].card_id,P+'transfer')
        g.apply(EndTurn(1));self.play(g,FROST);self.assertEqual(g.state.entities[wid].card_id,FROST)
        self.portable(g)

    def test_a19_private_transform_wait_restores_independent_registry_clone_replay_and_runs_cast_once(self):
        g=self.game(hand=(CARD,FIRE),mode='wait');self.play(g,FIRE)
        other=self.portable(g,'wait')
        for game in (g,other):self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,24)

    def test_a20_failed_resume_preserves_original_private_transform_and_payment(self):
        g=self.game(hand=(CARD,FIRE),mode='wait');self.play(g,FIRE);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Shadow deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g)

    def test_a21_failure_after_transform_rolls_back_material_binding_history_and_information(self):
        g=self.game(hand=(CARD,FIRE),mode='fail');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Shadow deliberate'):self.play(g,FIRE)
        self.assertEqual(g.snapshot(),saved)

    def test_a22_native_binding_and_hidden_current_face_stay_out_of_opponent_views(self):
        g=self.game(hand=(CARD,FIRE));self.play(g,FIRE)
        own=json.dumps(g.for_player(1).observe());other=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        self.assertIn(FIRE,own)
        for field in ('spell_mirror','declaring_card_id','cast_id','resolution_frame','rng_state'):
            self.assertNotIn(chr(34)+field+chr(34),own+other)
        observation=g.for_player(2).observe()['observation']
        self.assertTrue(all(x['card_id'] is None for x in observation['players'][0]['hand']))

    def test_a23_rehashed_missing_or_foreign_native_binding_is_rejected(self):
        g=self.game(hand=(CARD,FIRE));wid=self.mirrors(g)[0].id
        saved=deepcopy(g.snapshot());saved['state']['entities'][str(wid)]['abilities']=[a for a in saved['state']['entities'][str(wid)]['abilities'] if a['kind']!='spell_mirror']
        self.reject(saved)
        self.play(g,FIRE);saved=deepcopy(g.snapshot())
        binding=next(a for a in saved['state']['entities'][str(wid)]['abilities'] if a['kind']=='spell_mirror')['spell_mirror']
        binding['cast_id']=9999;self.reject(saved)

    def test_a24_binding_shape_profile_and_codec_are_strict(self):
        g=self.game();binding=SpellMirrorBinding(CARD)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state,origin_events=g.events)
        self.assertEqual(codec.decode(codec.encode(binding)),binding)
        with self.assertRaises(ValueError):SpellMirrorBinding(CARD,0)
        with self.assertRaises(ValueError):SpellMirrorBinding('',1)
        fresh=build_registry()
        with self.assertRaises(ValueError):fresh.register_spell_mirror(FIRE)
        with self.assertRaises(ValueError):fresh.register_spell_mirror(CARD)

    def test_a25_second_seat_follows_its_own_actual_cast(self):
        g=self.game(hand=(CARD,FROST),seat=2);self.play(g,FROST)
        self.assertEqual(self.mirrors(g,2)[0].card_id,FROST);self.portable(g)


if __name__=='__main__':unittest.main()
