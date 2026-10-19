"""Gelbin's actual deck objects, independent Aura entry and Fabled opening."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.gelbin_deck_aura_card import CARD, COMPANIONS, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, DeckPolicy,
    DeckSpec, EndTurn, Game, GenerationContext, MatchSetup, PlayCard, PlayerSetup, Rarity, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, Zone, expand_fabled_cards)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.deck_auras import PutStoredAura
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, Destroy, GainArmor,
    InvokeBehavior, RequestChoice, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.pools import PoolDefinition, PoolMember
from hs_sim.engine.zones import CardReference, MoveCard

GNOME, MEKK = COMPANIONS
END, DRAGON, REPEAT, RESIST = 'END_011','TIME_700','CATA_480','TTN_851'
UNKNOWN, UNBOUND = 'BE_146','EDR_259e1'
P = 'gelbin.test.'
FILL, WATCH, CLEAN, SHUFFLE = (P+x for x in ('fill','watch','clean','shuffle'))


@lru_cache(maxsize=None)
def registry(role, mode='normal'):
    assert role in ('writer','reader')
    r=build_registry()
    meta=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,max_copies=30)
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,cost=1,attack=2,health=3,metadata=meta))
    def fail(c):raise ResolutionError('Gelbin deliberate failure')
    r.register_behavior(P+'fail',fail)
    def watch(c):
        if mode=='spy':return (GainArmor(c.player_id,9),)
        if c.event.player_id!=c.player_id or dict(c.event.data).get('card_id')!=GNOME:return ()
        if mode in ('wait','wait_grant'):
            return (RequestChoice(c.player_id,(
                ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),source_id=c.source_id),)
        if mode=='move':
            target=next(c.state.entities[i]for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id==MEKK)
            return (MoveCard(CardReference.capture(target),c.player_id,Zone.HAND,source_id=c.source_id),)
        if mode=='fail':return (GainArmor(c.player_id,1),InvokeBehavior(P+'fail',c.source_id,c.player_id))
        if mode=='lethal':return (Damage(c.state.players[3-c.player_id].hero_id,80,c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    event='spell_cast_accepted'if mode=='spy'else'player_effect_added'
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,attack=0,health=5,triggers=(TriggerSpec(event,P+'watch'),)))
    def clean(c):
        source=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD)
        return {'destroy':(Destroy(source),),'silence':(Silence(source),),
            'control':(ChangeControl(source,3-c.player_id),)}[mode]
    r.register_behavior(CLEAN,clean)
    r.register_card(CardDefinition(CLEAN,CLEAN,CardType.SPELL,on_play=CLEAN))
    def shuffle(c):
        entity=next(c.state.entities[i]for i in c.state.players[c.player_id].hand
            if any(a.kind=='aura_duration_bonus'for a in c.state.entities[i].abilities))
        return (MoveCard(CardReference.capture(entity),c.player_id,Zone.DECK,position='bottom',source_id=c.source_id),)
    r.register_behavior(SHUFFLE,shuffle)
    r.register_card(CardDefinition(SHUFFLE,SHUFFLE,CardType.SPELL,on_play=SHUFFLE))
    if mode=='missing':
        from hs_sim.cards.metadata import metadata_from_record
        raw=next(x['record']for x in load_batch()['evidence_only']if x['record']['id']==UNKNOWN)
        r.register_card(CardDefinition(UNKNOWN,raw['name'],CardType.SPELL,cost=raw['cost'],metadata=metadata_from_record(raw)))
    # A declared finite representative pool for the real Triumph producer;
    # this fixture does not certify the formal Standard generation catalog.
    r.register_pool(PoolDefinition('constructed.cards','gelbin-entry-fixture-v1',
        'gelbin-entry-fixture','experimental',(PoolMember(DRAGON),)))
    r.validate();r.freeze();return r


class GelbinAuraTests(unittest.TestCase):
    def game(self,deck=(GNOME,MEKK),*,hand=(CARD,),board=(),mode='normal',capacity=5,secret_capacity=5,enemy_hand=(),enemy_deck=None):
        if mode in ('spy','wait','wait_grant','move','fail','lethal'):board=(*board,WATCH)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_04',hand=hand,board=board,deck=deck,mana=10,max_mana=10,hero_power_card_id='HERO_04bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,deck=(FILL,)*25 if enemy_deck is None else enemy_deck,mana=10,max_mana=10,hero_power_card_id='HERO_08bp')),
            seed=256009,generation_context=GenerationContext('gelbin-entry-fixture','experimental')),
            registry('writer',mode),Ruleset(max_ongoing_effects=capacity,max_secret_zone=secret_capacity))
    def play(self,g,cid=CARD):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid));return eid
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def owner(self,g,pid=1):
        self.end(g)
        while g.state.active_player!=pid:self.end(g)
    def effects(self,g,pid=1):return g.state.players[pid].player_effects
    def portable(self,g,mode='normal'):
        s=json.loads(json.dumps(g.snapshot()));r=registry('reader',mode)
        other=Game.from_snapshot(s,r);self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),r).snapshot(),s);return other

    def test_a00_complete_root_child_identity_and_original_aura_tag_domain(self):
        data=load_batch();self.assertEqual(len(data['aura_ids']),16)
        self.assertEqual(len(data['existing_dependencies']),8)
        self.assertEqual(tuple(registry('writer').fabled[CARD].companion_card_ids),COMPANIONS)
        root=registry('writer').card(CARD)
        self.assertEqual((root.cost,root.attack,root.health),(8,6,6))
        for row in data['official_observations']:self.assertEqual(set(row['face']['childIds']),{119919,119920})

    def test_a01_actual_original_deck_cards_install_without_cast_draw_or_hand_play(self):
        g=self.game(mode='spy');refs=[CardReference.capture(g.state.entities[i])for i in g.state.players[1].deck]
        before_rng=g._rng.getstate();self.play(g)
        self.assertEqual(len(self.effects(g)),2);self.assertEqual(g.state.cast_history,[]);self.assertEqual(g.state.draw_history,[])
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(g.state.players[1].mana,2)
        self.assertEqual(g._rng.getstate(),before_rng)
        self.assertEqual({p.source_id for p in self.effects(g)},{x.entity_id for x in refs})
        for ref in refs:
            entity=g.state.entities[ref.entity_id]
            self.assertEqual((entity.card_id,entity.zone,entity.zone_epoch),(ref.card_id,Zone.GRAVEYARD,ref.zone_epoch+1))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.portable(g,'spy')

    def test_a02_one_of_each_identity_uses_first_physical_copy_and_preserves_rest(self):
        g=self.game((MEKK,GNOME,MEKK,GNOME,FILL));ids=tuple(g.state.players[1].deck)
        self.play(g)
        self.assertEqual([p.source_id for p in self.effects(g)],list(ids[:2]))
        self.assertEqual(g.state.players[1].deck,list(ids[2:]));self.portable(g)

    def test_a03_empty_and_non_aura_decks_are_rng_neutral(self):
        for deck in ((),(FILL,)*4):
            with self.subTest(deck=deck):
                g=self.game(deck);rng=g._rng.getstate();original=list(g.state.players[1].deck);self.play(g)
                self.assertEqual(g._rng.getstate(),rng);self.assertEqual(self.effects(g),[])
                self.assertEqual(g.state.players[1].deck,original)

    def test_a04_existing_aura_does_not_exclude_same_identity_from_deck(self):
        g=self.game((RESIST,GNOME),hand=(RESIST,CARD));self.play(g,RESIST);self.play(g)
        self.assertEqual([p.source_card_id for p in self.effects(g)].count(RESIST),2)
        self.assertEqual(len(self.effects(g)),3)
        self.assertEqual(len(g.state.cast_history),1);self.portable(g)

    def test_b00_full_area_does_not_consume_or_reveal_any_unused_deck_aura(self):
        g=self.game((REPEAT,DRAGON),hand=(RESIST,CARD),capacity=1)
        self.play(g,RESIST);original=list(g.state.players[1].deck);rng=g._rng.getstate();self.play(g)
        self.assertEqual(g.state.players[1].deck,original);self.assertEqual(len(self.effects(g)),1)
        self.assertEqual(g._rng.getstate(),rng)
        wire=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        self.assertNotIn('"card_id": "'+DRAGON+'"',wire)

    def test_b01_partial_capacity_and_shared_area_limit_leave_original_excess_in_deck(self):
        for capacity,secret_capacity in ((2,5),(5,2)):
            with self.subTest(limits=(capacity,secret_capacity)):
                g=self.game((GNOME,MEKK,DRAGON),capacity=capacity,secret_capacity=secret_capacity)
                original=list(g.state.players[1].deck);self.play(g)
                self.assertEqual(len(self.effects(g)),2);self.assertEqual(g.state.players[1].deck,[original[2]])
                self.assertEqual(g.state.entities[original[2]].zone_epoch,0)

    def test_b02_full_minion_board_does_not_use_aura_area_capacity(self):
        g=self.game((GNOME,MEKK,DRAGON,END,REPEAT),board=(FILL,)*6);self.play(g)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(len(self.effects(g)),5)
        self.assertEqual(g.state.players[1].deck,[])

    def test_b03_source_lifecycle_does_not_remove_original_aura_instances(self):
        for mode in ('destroy','silence','control'):
            with self.subTest(mode=mode):
                g=self.game((GNOME,),hand=(CARD,CLEAN),mode=mode);self.play(g);self.play(g,CLEAN)
                self.owner(g);self.assertEqual(len(self.effects(g)),1)
                self.assertEqual(self.effects(g)[0].remaining_turns,2)

    def test_b04_actual_owner_end_ticks_and_owner_start_clock_are_preserved(self):
        g=self.game((GNOME,END));self.play(g)
        self.owner(g);self.assertEqual([e.remaining_turns for e in self.effects(g)],[2,2])
        self.owner(g);self.assertEqual([e.remaining_turns for e in self.effects(g)],[1,1])
        self.owner(g);self.assertEqual(self.effects(g),[]);self.portable(g)

    def test_b05_real_repeat_source_rereads_next_battlecry_window_and_keeps_one_payment(self):
        g=self.game((GNOME,GNOME,MEKK,MEKK),board=('TIME_064',));self.play(g)
        self.assertEqual(len(self.effects(g)),4);self.assertEqual(g.state.players[1].deck,[])
        self.assertEqual(len({e.source_id for e in self.effects(g)}),4)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(g.state.players[1].mana,2)
        self.assertEqual(g.state.cast_history,[]);self.portable(g)

    def test_c00_actual_granted_extra_duration_survives_shuffle_and_direct_entry(self):
        g=self.game((),hand=('CATA_621',SHUFFLE,CARD));self.play(g,'CATA_621');self.play(g,SHUFFLE)
        eid=g.state.players[1].deck[0];cast_count=len(g.state.cast_history)
        self.play(g);effect=self.effects(g)[0];spec=g.registry.player_effect(effect.spec_id)
        self.assertEqual(effect.source_id,eid);self.assertEqual(effect.remaining_turns,spec.duration+1)
        self.assertIsNone(effect.aura_duration_cast_id);self.assertEqual(len(effect.aura_duration_grants),1)
        self.assertEqual(len(g.state.cast_history),cast_count)
        self.assertTrue(any(e.kind=='aura_duration_direct_bound'for e in g.events))
        self.portable(g);self.owner(g);self.assertEqual(self.effects(g)[0].remaining_turns,spec.duration)

    def test_c01_actual_pending_choice_between_installations_restores_and_finishes_once(self):
        g=self.game(mode='wait');self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(self.effects(g)),1)
        restored=self.portable(g,'wait')
        before=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(q.player_id,q.id,('fail',)))
        self.assertEqual(g.snapshot(),before)
        for game in (g,restored):
            q=game.state.pending_choice;game.apply(SelectChoice(q.player_id,q.id,('ok',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(len(self.effects(g)),2)
        self.assertEqual(g.state.cast_history,[])

    def test_c02_stale_selected_physical_card_does_not_rebind_to_duplicate(self):
        g=self.game((GNOME,MEKK,MEKK),mode='move');ids=list(g.state.players[1].deck);self.play(g)
        self.assertEqual([p.source_card_id for p in self.effects(g)],[GNOME])
        self.assertEqual(g.state.players[1].hand,[ids[1]]);self.assertEqual(g.state.players[1].deck,[ids[2]])
        self.portable(g,'move')

    def test_c03_installation_reaction_failure_rolls_back_whole_paid_root(self):
        g=self.game(mode='fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_c04_lethal_installation_reaction_stops_later_original_cards(self):
        g=self.game(mode='lethal');ids=list(g.state.players[1].deck);self.play(g)
        self.assertNotEqual(g.state.status,'playing');self.assertEqual(len(self.effects(g)),1)
        self.assertEqual(g.state.players[1].deck,[ids[1]])

    def test_c05_known_eligible_without_body_and_unbound_dynamic_aura_fail_explicitly(self):
        for cid,mode in ((UNKNOWN,'missing'),(UNBOUND,'normal')):
            with self.subTest(cid=cid):
                g=self.game((GNOME,cid),mode=mode);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g)
                self.assertEqual(g.snapshot(),before)

    def test_d00_second_actor_uses_its_own_original_deck_and_program(self):
        g=self.game((GNOME,),hand=(),enemy_hand=(CARD,),enemy_deck=(FILL,MEKK));self.end(g)
        self.play(g);self.assertEqual([e.source_card_id for e in self.effects(g,2)],[MEKK])
        self.assertEqual(len(g.state.players[1].deck),1);self.assertEqual(self.effects(g),[])
        self.owner(g,2);self.assertEqual(self.effects(g,2)[0].remaining_turns,2);self.portable(g)

    def test_d01_request_scope_future_residence_and_wrong_zone_rejected(self):
        g=self.game();eid=g.state.players[1].hand[0];ref=CardReference.capture(g.state.entities[eid])
        with self.assertRaises(ValueError):PutStoredAura(ref,1,eid)
        ref=CardReference.capture(g.state.entities[g.state.players[1].deck[0]])
        with self.assertRaises(ValueError):PutStoredAura(ref,2,eid)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        good=PutStoredAura(ref,1,eid);self.assertEqual(codec.decode(codec.encode(good)),good)
        with self.assertRaises(ValueError):codec.encode(replace(good,card=replace(ref,zone_epoch=999)))

    def test_d02_direct_duration_receipt_cannot_be_dropped_or_changed(self):
        from hs_sim.engine.aura_duration import validate_events
        g=self.game((),hand=('CATA_621',SHUFFLE,CARD));self.play(g,'CATA_621');self.play(g,SHUFFLE);self.play(g)
        snapshot=g.snapshot();bad=deepcopy(snapshot)
        bad['state']['players']['1']['player_effects'][0]['aura_duration_grants']=[]
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry('reader'))
        original=list(g._events);g._events=[e for e in original if e.kind!='aura_duration_direct_bound']
        with self.assertRaises(ValueError):validate_events(g)
        g._events=original;effect=g._state.players[1].player_effects[0]
        g._state.players[1].player_effects[0]=replace(effect,aura_duration_grants=())
        with self.assertRaises(ValueError):validate_events(g)

    def test_d03_real_fabled_bundle_uses_thirty_physical_slots_and_normal_opening(self):
        r=registry('writer');cards=expand_fabled_cards((CARD,)+(FILL,)*27,r)
        self.assertEqual(cards[:3],(CARD,*COMPANIONS));self.assertEqual(len(cards),30)
        own=DeckSpec('HERO_04','HERO_04bp',CardClass.PALADIN,cards)
        other=DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,(FILL,)*30)
        policy=DeckPolicy('K256-fixture','K256-fixed','experimental',tuple(r.cards))
        g=Game.from_decks(MatchSetup((own,other),policy,'GAME_005',256009,1),r)
        for cid in (CARD,*COMPANIONS):self.assertEqual(sum(e.card_id==cid and e.owner==1 for e in g.state.entities.values()),1)
        self.portable(g)


if __name__=='__main__':unittest.main()
