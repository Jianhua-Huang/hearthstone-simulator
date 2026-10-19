"""Acolyte's real cost link, source lifecycle and ordinary cost restoration."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.infinite_cost_card import CARD, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction, PlayCard,
    PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy, Draw,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.linked_hand_costs import (INFINITE_COST_VALUE, RestoreRememberedCost,
    SetRandomHandCostForDeathrattle)
from hs_sim.engine.model import BattlecryRepeatSpec, CostSpec, RememberedCost, TargetSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard, ModifyStoredCost, MoveCard
from hs_sim.targets import canonical_digest

P='acolyte.test.'
PLAIN='CORE_CS2_182'
NEW_FACE='CORE_CS2_189'


def memory(entity):
    return next(a.deathrattle_memory for a in entity.abilities
        if a.kind=='deathrattle' and a.deathrattle_memory is not None and a.deathrattle_memory.spec.kind=='cost_link')


@lru_cache(None)
def registry(mode=None):
    r=build_registry()
    def ref(c):return CardReference.capture(c.state.entities[c.target_id])
    def fail(c):raise ResolutionError('Acolyte deliberate failure')
    bodies={
        'discount':lambda c:(ModifyStoredCost(ref(c),CostSpec(delta=-2),c.source_id),),
        'after':lambda c:(ModifyStoredCost(ref(c),CostSpec(delta=-1),c.source_id),),
        'zero':lambda c:(ModifyStoredCost(ref(c),CostSpec(set_to=0),c.source_id),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'base':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        'steal':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'trigger':lambda c:(TriggerDeathrattles(c.target_id,c.source_id,times=2),),
        'face':lambda c:(TransformStoredCard(ref(c),NEW_FACE,c.source_id),),
        'deck':lambda c:(MoveCard(ref(c),c.player_id,Zone.DECK,position='top',source_id=c.source_id),),
        'draw':lambda c:(Draw(c.player_id,source_id=c.source_id),),
        'transfer':lambda c:(MoveCard(ref(c),3-c.player_id,Zone.HAND,source_id=c.source_id),),
        'hand_copy':lambda c:(CopyCard(ref(c),c.player_id,source_id=c.source_id),),
        'fail':fail,
    }
    stored={'discount','after','zero','face','deck','transfer','hand_copy'}
    for name,body in bodies.items():
        r.register_behavior(P+name,body)
        if name=='fail':continue
        targeting=None if name=='draw' else TargetSpec(zones=(Zone.HAND if name in stored else Zone.BOARD,),
            kinds=(CardType.MINION,) if name not in stored else (CardType.MINION,CardType.SPELL,CardType.WEAPON,CardType.LOCATION,CardType.HERO),
            relation='friendly' if name in stored else 'any')
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,cost=1,on_play=P+name,targeting=targeting))
    r.register_card(CardDefinition(P+'double','Two actual Battlecries',CardType.MINION,health=20,
        battlecry_repeats=(BattlecryRepeatSpec(),)))
    if mode:
        def watch(c):
            target=c.state.entities.get(c.event.target_id)
            if target is None or target.controller!=c.player_id:return ()
            if mode=='kill':return (Destroy(c.event.source_id,c.source_id),)
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(P+'watch','Cost observer',CardType.MINION,health=20,
            triggers=(TriggerSpec('cost_modified',P+'watch'),)))
    r.validate();return r


class InfiniteCostCardTests(unittest.TestCase):
    def game(self,hand=(CARD,PLAIN),*,other_hand=(),deck=(),board=(),mode=None,seat=1,seed=1):
        own=PlayerSetup('HERO_08',hand=hand,deck=deck,board=(*((P+'watch',) if mode else ()),*board),
            mana=50,max_mana=50,mana_cap=50)
        other=PlayerSetup('HERO_08',hand=other_hand,mana=50,max_mana=50,mana_cap=50)
        return Game.from_scenario(Scenario((own,other) if seat==1 else (other,own),
            active_player=seat,seed=seed),registry(mode))

    def eid(self,g,cid):
        return next(i for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id==cid)

    def play(self,g,cid=None,*,eid=None,target=None):
        eid=self.eid(g,cid) if eid is None else eid;seat=g.state.active_player
        definition=g.registry.card(g.state.entities[eid].card_id)
        g.apply(PlayCard(seat,eid,target_id=target,
            position=len(g.state.players[seat].board) if definition.kind==CardType.MINION else None))
        return eid

    def source(self,g):
        return next(e for e in g.state.entities.values() if e.card_id==CARD and e.zone==Zone.BOARD)

    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g,mode=None):
        saved=json.loads(json.dumps(g.snapshot()))
        other=Game.from_snapshot(saved,registry.__wrapped__(mode))
        self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry.__wrapped__(mode)).snapshot(),saved)
        return other

    def kill_from_enemy(self,g,source_id):
        g.apply(EndTurn(g.state.active_player));self.play(g,P+'kill',target=source_id)

    def reject(self,saved):
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry.__wrapped__())

    def test_a01_complete_original_sources_real_dragon_and_explicit_numeric_policy(self):
        data=load_batch()
        self.assertEqual([x['record']['id'] for x in data['evidence_only']],['END_018e','END_018e2'])
        for row in (*data['cards'],*data['evidence_only']):
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        card=registry().card(CARD)
        self.assertEqual((card.cost,card.attack,card.health),(3,5,5))
        self.assertEqual(card.metadata.tribes,('dragon',))
        self.assertEqual(data['policy']['infinite_cost_value'],INFINITE_COST_VALUE)
        self.assertFalse(data['policy']['cn_calibrated'])

    def test_a02_actual_paid_battlecry_binds_the_exact_physical_hand_and_cost_attachment(self):
        g=self.game();target=self.eid(g,PLAIN);source=self.play(g,CARD)
        links=memory(g.state.entities[source]).cost_links
        self.assertEqual(len(links),1)
        link=links[0];self.assertEqual((link.entity_id,link.hand_entry_id),(target,g.state.entities[target].hand_entry_id))
        self.assertEqual(g.state.entities[target].cost,INFINITE_COST_VALUE)
        self.assertEqual(g.state.players[1].mana,47)
        self.assertTrue(any(e.id==link.enchantment_id and e.source_id==source for e in g.state.entities[target].enchantments))
        with self.assertRaises(IllegalAction):self.play(g,eid=target)

    def test_a03_minion_spell_weapon_location_and_playable_hero_all_use_the_same_restoration(self):
        for cid in (PLAIN,'CORE_CS2_029','CATA_472','CORE_REV_990','SC_400'):
            g=self.game(hand=(CARD,cid),other_hand=(P+'kill',));target=self.eid(g,cid)
            cost=g.state.entities[target].cost;source=self.play(g,CARD)
            self.assertEqual(g.state.entities[target].cost,INFINITE_COST_VALUE)
            self.kill_from_enemy(g,source)
            self.assertEqual(g.state.entities[target].cost,cost)

    def test_a04_empty_hand_keeps_real_five_five_body_and_does_not_consume_rng(self):
        g=self.game(hand=(CARD,),other_hand=(P+'kill',));before=g._rng.getstate();source=self.play(g,CARD)
        self.assertEqual(g._rng.getstate(),before)
        self.assertEqual(memory(g.state.entities[source]).cost_links,())
        self.kill_from_enemy(g,source)
        self.assertEqual(len(g.state.death_history),1)

    def test_a05_full_hand_duplicates_are_distinct_physical_candidates_not_one_card_name(self):
        g=self.game(hand=(CARD,*([PLAIN]*9)));source=self.play(g,CARD)
        link=memory(g.state.entities[source]).cost_links[0]
        self.assertIn(link.entity_id,g.state.players[1].hand)
        self.assertEqual(sum(g.state.entities[i].cost==INFINITE_COST_VALUE for i in g.state.players[1].hand),1)
        self.assertEqual(len(g.state.players[1].hand),9)

    def test_a06_earlier_and_later_real_discounts_survive_removal_of_only_the_linked_layer(self):
        g=self.game(hand=(P+'discount',CARD,PLAIN,P+'after',P+'kill'));target=self.eid(g,PLAIN)
        self.play(g,P+'discount',target=target);source=self.play(g,CARD)
        self.assertEqual(memory(g.state.entities[source]).cost_links[0].entity_id,target)
        self.play(g,P+'after',target=target)
        self.assertEqual(g.state.entities[target].cost,INFINITE_COST_VALUE-1)
        self.play(g,P+'kill',target=source)
        self.assertEqual(g.state.entities[target].cost,1)

    def test_a07_later_explicit_zero_cost_is_not_overwritten_by_an_arbitrary_old_quote(self):
        g=self.game(hand=(CARD,PLAIN,P+'zero',P+'kill'));target=self.eid(g,PLAIN);source=self.play(g,CARD)
        self.play(g,P+'zero',target=target);self.play(g,P+'kill',target=source)
        self.assertEqual(g.state.entities[target].cost,0)
        self.play(g,eid=target);self.assertEqual(g.state.entities[target].zone,Zone.BOARD)

    def test_a08_two_actual_sources_remove_only_their_own_stacked_cost_layers(self):
        g=self.game(hand=(CARD,CARD,PLAIN,P+'kill',P+'kill'),seed=15);target=self.eid(g,PLAIN)
        first=self.play(g,CARD);second=self.play(g,CARD)
        self.assertEqual([memory(g.state.entities[i]).cost_links[0].entity_id for i in (first,second)],[target,target])
        self.play(g,P+'kill',target=first);self.assertEqual(g.state.entities[target].cost,INFINITE_COST_VALUE)
        self.play(g,P+'kill',target=second);self.assertEqual(g.state.entities[target].cost,4)

    def test_a09_repeated_native_battlecries_append_both_original_links_and_restore_both_once(self):
        g=self.game(board=(P+'double',),other_hand=(P+'kill',));target=self.eid(g,PLAIN);source=self.play(g,CARD)
        links=memory(g.state.entities[source]).cost_links
        self.assertEqual(len(links),2);self.assertEqual([x.entity_id for x in links],[target,target])
        self.assertEqual(len({x.battlecry_id for x in links}),2)
        self.kill_from_enemy(g,source);self.assertEqual(g.state.entities[target].cost,4)

    def test_a10_manual_repeated_deathrattles_and_later_natural_death_do_not_reset_twice(self):
        g=self.game(hand=(CARD,PLAIN,P+'trigger',P+'kill'));target=self.eid(g,PLAIN);source=self.play(g,CARD)
        self.play(g,P+'trigger',target=source)
        self.assertEqual(g.state.entities[target].cost,4)
        modified=sum(e.kind=='cost_modified' and e.target_id==target for e in g.events)
        self.play(g,P+'kill',target=source)
        self.assertEqual(sum(e.kind=='cost_modified' and e.target_id==target for e in g.events),modified)

    def test_a11_silence_removes_the_native_restoration_body(self):
        g=self.game(hand=(CARD,PLAIN,P+'silence',P+'kill'));target=self.eid(g,PLAIN);source=self.play(g,CARD)
        self.play(g,P+'silence',target=source);self.play(g,P+'kill',target=source)
        self.assertEqual(g.state.entities[target].cost,INFINITE_COST_VALUE)

    def test_a12_bounce_without_death_does_not_pretend_to_trigger_restoration(self):
        g=self.game(hand=(CARD,PLAIN,P+'bounce'));target=self.eid(g,PLAIN);source=self.play(g,CARD)
        self.play(g,P+'bounce',target=source)
        self.assertEqual(g.state.entities[source].zone,Zone.HAND)
        self.assertEqual(memory(g.state.entities[source]).cost_links,())
        self.assertEqual(g.state.entities[target].cost,INFINITE_COST_VALUE)

    def test_a13_source_control_change_still_restores_the_original_other_players_card(self):
        g=self.game(hand=(CARD,PLAIN,P+'steal',P+'kill'));target=self.eid(g,PLAIN);source=self.play(g,CARD)
        self.play(g,P+'steal',target=source);self.assertEqual(g.state.entities[source].controller,2)
        self.play(g,P+'kill',target=source);self.assertEqual(g.state.entities[target].cost,4)

    def test_a14_current_source_copy_keeps_its_frozen_link_to_the_original_hand_card(self):
        g=self.game(hand=(CARD,PLAIN,P+'copy',P+'kill'));target=self.eid(g,PLAIN);source=self.play(g,CARD)
        self.play(g,P+'copy',target=source)
        copied=next(i for i in g.state.players[1].board if i!=source and g.state.entities[i].card_id==CARD)
        self.assertEqual(memory(g.state.entities[copied]),memory(g.state.entities[source]))
        self.play(g,P+'kill',target=copied)
        self.assertEqual(g.state.entities[target].cost,4)
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD)

    def test_a15_base_source_copy_has_empty_native_memory_and_cannot_restore_another_source(self):
        g=self.game(hand=(CARD,PLAIN,P+'base',P+'kill'),other_hand=(P+'kill',))
        target=self.eid(g,PLAIN);source=self.play(g,CARD);self.play(g,P+'base',target=source)
        copied=next(i for i in g.state.players[1].board if i!=source and g.state.entities[i].card_id==CARD)
        self.assertEqual(memory(g.state.entities[copied]).cost_links,())
        self.play(g,P+'kill',target=copied);self.assertEqual(g.state.entities[target].cost,INFINITE_COST_VALUE)
        self.kill_from_enemy(g,source);self.assertEqual(g.state.entities[target].cost,4)

    def test_a16_target_reset_does_not_reapply_an_old_cost_to_its_new_face(self):
        g=self.game(hand=(CARD,PLAIN,P+'face',P+'kill'));target=self.eid(g,PLAIN);source=self.play(g,CARD)
        self.play(g,P+'face',target=target);self.assertEqual(g.state.entities[target].card_id,NEW_FACE)
        self.play(g,P+'kill',target=source)
        self.assertEqual((g.state.entities[target].card_id,g.state.entities[target].cost),(NEW_FACE,1))

    def test_a17_exact_attachment_survives_deck_move_and_new_hand_entry_without_rebinding(self):
        g=self.game(hand=(CARD,PLAIN,P+'deck',P+'draw'),other_hand=(P+'kill',));target=self.eid(g,PLAIN)
        old_entry=g.state.entities[target].hand_entry_id;source=self.play(g,CARD)
        self.play(g,P+'deck',target=target);self.assertEqual(g.state.entities[target].zone,Zone.DECK)
        self.portable(g);self.play(g,P+'draw')
        self.assertNotEqual(g.state.entities[target].hand_entry_id,old_entry)
        self.assertEqual(g.state.entities[target].cost,INFINITE_COST_VALUE)
        self.kill_from_enemy(g,source);self.assertEqual(g.state.entities[target].cost,4)

    def test_a18_transferred_original_hand_card_remains_the_exact_restoration_target(self):
        g=self.game(hand=(CARD,PLAIN,P+'transfer',P+'kill'));target=self.eid(g,PLAIN);source=self.play(g,CARD)
        self.play(g,P+'transfer',target=target)
        self.assertEqual(g.state.entities[target].controller,2)
        self.play(g,P+'kill',target=source)
        self.assertEqual(g.state.entities[target].cost,4)
        self.portable(g)

    def test_a19_new_current_target_copy_owns_a_different_cost_attachment(self):
        g=self.game(hand=(CARD,PLAIN,P+'hand_copy',P+'kill'));target=self.eid(g,PLAIN);source=self.play(g,CARD)
        self.play(g,P+'hand_copy',target=target)
        copied=next(e for e in g.state.entities.values() if e.origin_entity_id==target)
        self.play(g,P+'kill',target=source)
        self.assertEqual(g.state.entities[target].cost,4)
        self.assertEqual(g.state.entities[copied.id].cost,INFINITE_COST_VALUE)

    def test_a20_cost_notification_death_already_captures_the_installed_memory(self):
        g=self.game(mode='kill');target=self.eid(g,PLAIN);source=self.play(g,CARD)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[target].cost,4)
        self.assertEqual(len(g.state.death_history),1)

    def test_a21_cost_set_and_restoration_waits_roundtrip_through_independent_registries(self):
        g=self.game(hand=(CARD,PLAIN,P+'kill'),mode='wait');target=self.eid(g,PLAIN);source=self.play(g,CARD)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(memory(g.state.entities[source]).cost_links),1)
        other=self.portable(g,'wait')
        for value in (g,other):self.choose(value)
        self.assertEqual(other.snapshot(),g.snapshot())
        self.play(g,P+'kill',target=source);self.assertEqual(g.state.entities[target].cost,4)
        self.portable(g,'wait');self.choose(g);self.portable(g,'wait')

    def test_a22_failed_resume_preserves_the_exact_waiting_cost_memory_and_rng(self):
        g=self.game(mode='wait');self.play(g,CARD);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g)

    def test_a23_failed_cost_observer_rolls_back_payment_randomness_and_all_link_material(self):
        g=self.game(mode='fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CARD)
        self.assertEqual(g.snapshot(),saved)

    def test_a24_both_seats_keep_the_original_cost_target_and_memory_private(self):
        for seat in (1,2):
            g=self.game(hand=(CARD,PLAIN),seat=seat);self.play(g,CARD)
            hidden=json.dumps(g.for_player(3-seat).observe())+json.dumps(g.player_events(3-seat))
            self.assertNotIn(PLAIN,hidden)
            self.assertNotIn('cost_links',hidden)
            self.assertNotIn('hand_entry_id',hidden)

    def test_a25_rehashed_future_or_foreign_links_and_forged_cost_operations_are_rejected(self):
        g=self.game();source=self.play(g,CARD);snapshot=g.snapshot()
        def link(saved):
            ability=next(a for a in saved['state']['entities'][str(source)]['abilities'] if a['deathrattle_memory'] is not None)
            return ability['deathrattle_memory']['cost_links'][0]
        for key,value in (('battlecry_id',999),('entity_id',999),('hand_entry_id',999),('enchantment_id',99999)):
            bad=deepcopy(snapshot);link(bad)[key]=value;self.reject(bad)
        bad=deepcopy(snapshot);original=link(bad)
        target=bad['state']['entities'][str(original['entity_id'])]
        enchant=next(e for e in target['enchantments'] if e['id']==original['enchantment_id'])
        enchant['set_cost']=1;target['cost_modifier']=1-target['base_cost'];self.reject(bad)

    def test_a26_typed_requests_reject_invalid_values_and_completed_deathrattle_reuse(self):
        for args in ((True,1,None,()),(1,0,None,()),(1,1,None,(1,))):
            with self.assertRaises(ValueError):SetRandomHandCostForDeathrattle(*args)
        for args in ((0,1,1,1),(1,True,1,1),(1,1,1,0)):
            with self.assertRaises(ValueError):RememberedCost(*args)
        g=self.game(hand=(CARD,PLAIN,P+'kill'));source=self.play(g,CARD)
        link=memory(g.state.entities[source]).cost_links[0];self.play(g,P+'kill',target=source)
        request=RestoreRememberedCost(g.state.deathrattle_history[-1].id,link)
        codec=FrameCodec(g.mechanics,g.registry)
        self.assertEqual(codec.decode(codec.encode(request)),request)
        with self.assertRaises(ValueError):request.validate_in_state(g.state,g.registry)

    def test_a27_empty_shadow_returns_to_zero_cost_but_never_becomes_manually_playable(self):
        cid='CORE_RLK_567';g=self.game(hand=(CARD,cid),other_hand=(P+'kill',));target=self.eid(g,cid)
        source=self.play(g,CARD);self.kill_from_enemy(g,source)
        self.assertEqual(g.state.entities[target].cost,0)
        g.apply(EndTurn(2))
        self.assertFalse(any(isinstance(a,PlayCard) and a.entity_id==target for a in g.legal_actions()))

    def test_a28_summoned_source_without_battlecry_has_no_invented_link(self):
        g=self.game(hand=(PLAIN,P+'kill'),board=(CARD,));target=self.eid(g,PLAIN);source=self.source(g).id
        self.assertEqual(memory(g.state.entities[source]).cost_links,())
        self.play(g,P+'kill',target=source)
        self.assertEqual(g.state.entities[target].cost,4)


if __name__=='__main__':
    unittest.main()
