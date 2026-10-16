"""Upgrade foundations: physical references, hidden stats and printed forms."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from dataclasses import dataclass, replace
import json
import unittest

from hs_sim.engine import (AbilityInstance, BuffStoredCard, CardDefinition, CardType, CostSpec,
    EndTurn, Game, HandActionSpec, Keyword, PlayCard, PlayerSetup, ResolutionError, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, UpgradeHandCard, UseHandAction, Zone)
from hs_sim.engine.effects import (ChoiceOption, Effect, GainArmor, InvokeBehavior, ModifyCost,
    RequestChoice, RevealHandCard, ReturnToHand, ShuffleIntoDeck, Summon)
from hs_sim.engine.lifecycle import attachment_id, refresh_entity
from hs_sim.engine.model import Enchantment
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard, ReorderZone


@dataclass(frozen=True)
class StoredFixture(Effect):
    target_id: int
    kind: str = 'grant'


def install_fixture(r, effect):
    e=r.state.entities[effect.target_id]
    if effect.kind=='grant':
        e.abilities.append(AbilityInstance(attachment_id(r.state),'keyword',keyword=Keyword.LIFESTEAL))
    elif effect.kind=='bad_grant':
        e.abilities.append(AbilityInstance(attachment_id(r.state),'keyword',keyword=Keyword.TAUNT))
    elif effect.kind=='set':
        e.enchantments.append(Enchantment(attachment_id(r.state),set_attack=9,set_health=8))
    elif effect.kind=='damage':e.damage=1
    elif effect.kind=='consume':
        e.abilities=[replace(a,consumed=True) if a.kind=='keyword' else a for a in e.abilities]
    else:raise ValueError('Unknown fixture')
    refresh_entity(e)


class HandUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry();self.m=default_mechanics();self.m.register(StoredFixture,install_fixture)
        self.r.register_behavior('old',lambda c:[GainArmor(c.player_id,1)])
        self.r.register_behavior('new',lambda c:[GainArmor(c.player_id,7)])
        self.r.register_card(CardDefinition('base','Base',CardType.MINION,cost=2,attack=2,health=3,
            keywords=(Keyword.DIVINE_SHIELD,),on_play='old',hand_actions=(HandActionSpec('forge','forge',2,'up'),)))
        self.r.register_card(CardDefinition('up','Up',CardType.MINION,cost=3,attack=4,health=5,keywords=(Keyword.RUSH,),on_play='new'))
        self.r.register_card(CardDefinition('alt','Alt',CardType.MINION,cost=1,attack=1,health=1))
        self.r.register_card(CardDefinition('blade','Blade',CardType.WEAPON,cost=3,attack=4,durability=3))

    def script(self,callback):
        self.r.register_behavior('script',callback)
        self.r.register_card(CardDefinition('script','Script',CardType.SPELL,on_play='script'))

    def ref(self,c,zone='hand',index=0):
        return CardReference.capture(c.state.entities[getattr(c.state.players[1],zone)[index]])

    def game(self,hand=('script','base'),board=(),deck=('alt',)*12):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=hand,board=board,deck=deck,max_mana=10,mana=10),
            PlayerSetup('HERO_08',deck=('alt',)*12,max_mana=10,mana=10)),seed=109),self.r,mechanics=self.m)

    def play(self,g,card='script'):
        i=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==card)
        g.apply(PlayCard(1,i));return i

    def card(self,g,index=0):return g.state.entities[g.state.players[1].hand[index]]
    def check(self,g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r,self.m).snapshot(),g.snapshot())
        self.assertEqual(g.clone().snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r,self.m).snapshot(),g.snapshot())

    def test_upgrade_preserves_physical_id_owner_and_hand_position(self):
        self.script(lambda c:[UpgradeHandCard(self.ref(c,index=1),'up')])
        g=self.game(hand=('script','alt','base','alt'));before=g.state.players[1].hand[1:];self.play(g)
        self.assertEqual(g.state.players[1].hand,before);e=self.card(g,1)
        self.assertEqual((e.card_id,e.owner,e.zone_epoch),('up',1,1));self.check(g)

    def test_upgrade_replaces_printed_stats_keywords_and_behavior(self):
        self.script(lambda c:[UpgradeHandCard(self.ref(c),'up')]);g=self.game();self.play(g);e=self.card(g)
        self.assertEqual((e.attack,e.health,e.cost),(4,5,3));self.assertEqual(e.keywords,{Keyword.RUSH})
        self.play(g,'up');self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,7);self.check(g)

    def test_upgrade_keeps_stat_and_cost_attachments(self):
        self.script(lambda c:[BuffStoredCard(self.ref(c),2,3),ModifyCost(self.ref(c).entity_id,CostSpec(delta=-1)),UpgradeHandCard(self.ref(c),'up')])
        g=self.game();self.play(g);e=self.card(g);self.assertEqual((e.attack,e.health,e.cost),(6,8,2));self.assertEqual(len(e.enchantments),2);self.check(g)

    def test_upgrade_preserves_granted_ability_identity(self):
        self.script(lambda c:[StoredFixture(self.ref(c).entity_id),UpgradeHandCard(self.ref(c),'up')])
        g=self.game();self.play(g);e=self.card(g);self.assertIn(Keyword.LIFESTEAL,e.keywords)
        self.assertEqual(sum(a.origin=='granted' for a in e.abilities),1);self.check(g)

    def test_ordered_set_enchantments_still_override_new_base(self):
        self.script(lambda c:[StoredFixture(self.ref(c).entity_id,'set'),BuffStoredCard(self.ref(c),1,2),UpgradeHandCard(self.ref(c),'up')])
        g=self.game();self.play(g);self.assertEqual((self.card(g).attack,self.card(g).health),(10,10));self.check(g)

    def test_consumed_old_printed_ability_is_not_reused(self):
        self.r.register_card(CardDefinition('shield','Shield',CardType.MINION,health=3,keywords=(Keyword.DIVINE_SHIELD,)))
        self.script(lambda c:[StoredFixture(self.ref(c).entity_id,'consume'),UpgradeHandCard(self.ref(c),'shield')])
        g=self.game();self.play(g);self.assertIn(Keyword.DIVINE_SHIELD,self.card(g).keywords);self.check(g)

    def test_same_face_preserves_consumed_abilities_and_epoch(self):
        self.script(lambda c:[StoredFixture(self.ref(c).entity_id,'consume'),UpgradeHandCard(self.ref(c),'base')])
        g=self.game();self.play(g);self.assertNotIn(Keyword.DIVINE_SHIELD,self.card(g).keywords);self.assertEqual(self.card(g).zone_epoch,0);self.check(g)

    def test_upgrading_is_not_playing_drawing_or_summoning(self):
        self.script(lambda c:[UpgradeHandCard(self.ref(c),'up')]);g=self.game();self.play(g)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(len(g.state.players[1].deck),12)
        self.assertFalse(g.state.players[1].board);self.assertFalse(any(e.kind in ('minion_summoned','card_drawn') for e in g.events))

    def test_real_forge_uses_shared_preservation(self):
        self.script(lambda c:[BuffStoredCard(self.ref(c),1,2)])
        g=self.game(hand=('script','TTN_042'));self.play(g);i=self.card(g).id
        g.apply(UseHandAction(1,i,'forge'));e=g.state.entities[i]
        self.assertEqual(e.zone_epoch,1);self.assertEqual((e.attack,e.health),(7,7));self.check(g)

    def test_forge_uses_its_public_completion_event(self):
        g=self.game(hand=('base',));g.apply(UseHandAction(1,self.card(g).id,'forge'))
        self.assertTrue(any(e['kind']=='card_forged' for e in g.player_events(2)))
        self.assertFalse(any(e.kind=='hand_card_upgraded' for e in g.events));self.check(g)

    def test_conversion_in_hand_does_not_equip(self):
        self.script(lambda c:[UpgradeHandCard(self.ref(c),'blade',health_to_durability=True)])
        g=self.game();self.play(g);e=self.card(g)
        self.assertEqual((e.kind,e.attack,e.health,e.durability,e.corpse_value),(CardType.WEAPON,4,0,3,0))
        self.assertIsNone(g.state.players[1].weapon_id);self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack,0);self.check(g)

    def test_conversion_preserves_attack_cost_and_freezes_health_as_durability(self):
        self.script(lambda c:[BuffStoredCard(self.ref(c),2,4),ModifyCost(self.ref(c).entity_id,CostSpec(delta=-1)),
            UpgradeHandCard(self.ref(c),'blade',health_to_durability=True)])
        g=self.game();self.play(g);e=self.card(g);self.assertEqual((e.attack,e.health,e.durability,e.cost),(6,0,7,2))
        self.play(g,'blade');self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack,6);self.check(g)

    def test_conversion_respects_set_health_and_remaining_health(self):
        self.script(lambda c:[StoredFixture(self.ref(c).entity_id,'set'),StoredFixture(self.ref(c).entity_id,'damage'),
            UpgradeHandCard(self.ref(c),'blade',health_to_durability=True)])
        g=self.game();self.play(g);e=self.card(g);self.assertEqual((e.attack,e.health,e.durability),(9,0,7));self.check(g)

    def test_conversion_retains_weapon_compatible_granted_keyword(self):
        self.script(lambda c:[StoredFixture(self.ref(c).entity_id),UpgradeHandCard(self.ref(c),'blade',health_to_durability=True)])
        g=self.game();self.play(g);self.assertIn(Keyword.LIFESTEAL,self.card(g).keywords);self.check(g)

    def test_unsupported_granted_conversion_fails_transactionally(self):
        self.script(lambda c:[StoredFixture(self.ref(c).entity_id,'bad_grant'),UpgradeHandCard(self.ref(c),'blade',health_to_durability=True)])
        g=self.game();before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_cross_type_without_policy_fails_transactionally(self):
        self.script(lambda c:[UpgradeHandCard(self.ref(c),'blade')]);g=self.game();before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_wrong_conversion_pair_is_rejected(self):
        self.script(lambda c:[UpgradeHandCard(self.ref(c),'up',health_to_durability=True)]);g=self.game()
        with self.assertRaises(ResolutionError):self.play(g)

    def test_unknown_or_nonphysical_destination_is_rejected(self):
        for destination in ('missing','GDB_100a','HERO_01'):
            self.setUp();self.script(lambda c,d=destination:[UpgradeHandCard(self.ref(c),d)]);g=self.game();before=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g)
            self.assertEqual(g.snapshot(),before)

    def test_stored_buff_negative_attack_is_clamped_when_viewed(self):
        self.script(lambda c:[BuffStoredCard(self.ref(c),-8,1)]);g=self.game();self.play(g)
        self.assertEqual((self.card(g).attack,self.card(g).health),(0,4));self.check(g)

    def test_zero_buff_has_no_attachment_or_event(self):
        self.script(lambda c:[BuffStoredCard(self.ref(c))]);g=self.game();self.play(g)
        self.assertFalse(self.card(g).enchantments);self.assertFalse(any(e.kind=='stored_card_buffed' for e in g.events));self.check(g)

    def test_expiring_buff_remains_expiring_after_upgrade(self):
        self.script(lambda c:[BuffStoredCard(self.ref(c),2,3,expires_turn=c.state.turn),UpgradeHandCard(self.ref(c),'up')])
        g=self.game();self.play(g);g.apply(EndTurn(1));self.assertEqual((self.card(g).attack,self.card(g).health),(4,5));self.check(g)

    def test_buff_in_deck_is_hidden_and_survives_draw(self):
        self.r.register_behavior('draw_one',lambda c:[MoveCard(self.ref(c,zone='deck'),1,Zone.HAND,draw=True)])
        self.script(lambda c:[BuffStoredCard(self.ref(c,zone='deck'),2,3),InvokeBehavior('draw_one',c.source_id,1)])
        g=self.game(hand=('script',));self.play(g);self.assertEqual((self.card(g).attack,self.card(g).health),(3,4));self.check(g)

    def test_buff_nonminion_is_explicitly_unsupported(self):
        self.script(lambda c:[BuffStoredCard(self.ref(c),1,1)]);g=self.game(hand=('script','blade'))
        with self.assertRaises(ResolutionError):self.play(g)

    def test_departed_and_returned_card_rejects_old_reference(self):
        self.r.register_behavior('back',lambda c:[MoveCard(self.ref(c,zone='deck'),1,Zone.HAND,draw=True)])
        self.script(lambda c:[MoveCard(self.ref(c),1,Zone.DECK,position='top'),InvokeBehavior('back',c.source_id,1),
            BuffStoredCard(self.ref(c),8,8),UpgradeHandCard(self.ref(c),'up'),CopyCard(self.ref(c),1)])
        g=self.game();self.play(g);e=self.card(g)
        self.assertEqual((e.card_id,e.attack,e.health,e.zone_epoch),('base',2,3,2));self.assertEqual(len(g.state.players[1].hand),1);self.check(g)

    def test_controller_roundtrip_rejects_old_reference(self):
        self.r.register_behavior('back',lambda c:[MoveCard(CardReference.capture(c.state.entities[c.state.players[2].hand[0]]),1,Zone.HAND)])
        self.script(lambda c:[MoveCard(self.ref(c),2,Zone.HAND),InvokeBehavior('back',c.source_id,1),UpgradeHandCard(self.ref(c),'up')])
        g=self.game();self.play(g);self.assertEqual(self.card(g).card_id,'base');self.assertEqual(self.card(g).zone_epoch,2);self.check(g)

    def test_form_roundtrip_rejects_old_reference(self):
        self.r.register_behavior('back',lambda c:[UpgradeHandCard(self.ref(c),'base')])
        self.script(lambda c:[UpgradeHandCard(self.ref(c),'up'),InvokeBehavior('back',c.source_id,1),BuffStoredCard(self.ref(c),8,8)])
        g=self.game();self.play(g);self.assertEqual((self.card(g).attack,self.card(g).health,self.card(g).zone_epoch),(2,3,2));self.check(g)

    def test_reorder_does_not_invalidate_reference(self):
        self.script(lambda c:[ReorderZone(1,Zone.HAND,tuple(reversed(c.state.players[1].hand))),BuffStoredCard(self.ref(c),2,2)])
        g=self.game(hand=('script','base','alt'));self.play(g);self.assertEqual((self.card(g,1).attack,self.card(g,1).zone_epoch),(4,0));self.check(g)

    def test_current_and_base_copy_differ_after_upgrade(self):
        self.r.register_behavior('copy',lambda c:[CopyCard(self.ref(c),1),CopyCard(self.ref(c),1,mode='base')])
        self.script(lambda c:[BuffStoredCard(self.ref(c),2,2),UpgradeHandCard(self.ref(c),'up'),InvokeBehavior('copy',c.source_id,1)])
        g=self.game();self.play(g);self.assertEqual([self.card(g,n).attack for n in range(3)],[6,6,4])
        self.assertEqual([self.card(g,n).zone_epoch for n in range(3)],[1,0,0]);self.check(g)

    def test_play_return_uses_upgraded_base_and_resets_buffs(self):
        self.script(lambda c:[BuffStoredCard(self.ref(c),2,2),UpgradeHandCard(self.ref(c),'up')])
        self.r.register_behavior('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        self.r.register_card(CardDefinition('bounce','Bounce',CardType.SPELL,on_play='bounce'))
        g=self.game(hand=('script','base','bounce'));self.play(g);self.play(g,'up');self.play(g,'bounce')
        # Upgrade, hand -> pending -> board, then return are four revisions.
        self.assertEqual((self.card(g).card_id,self.card(g).attack,self.card(g).zone_epoch),('up',4,4));self.check(g)

    def test_old_ref_after_physical_shuffle_is_stale(self):
        self.r.register_behavior('back',lambda c:[MoveCard(CardReference.capture(next(e for e in c.state.entities.values() if e.card_id=='base')),1,Zone.HAND)])
        self.script(lambda c:[ShuffleIntoDeck(self.ref(c).entity_id),InvokeBehavior('back',c.source_id,1),UpgradeHandCard(self.ref(c),'up')])
        g=self.game();self.play(g);self.assertEqual(self.card(g).card_id,'base');self.assertEqual(self.card(g).zone_epoch,2);self.check(g)

    def test_choice_can_restore_stored_upgrade_reference(self):
        self.script(lambda c:[RequestChoice(1,(ChoiceOption('go','Go',(BuffStoredCard(self.ref(c),2,2),UpgradeHandCard(self.ref(c),'up'))),),c.source_id)])
        g=self.game();self.play(g);self.check(g);restored=Game.from_snapshot(g.snapshot(),self.r,self.m)
        for match in (g,restored):match.apply(SelectChoice(1,match.state.pending_choice.id,('go',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.card(g).attack,6);self.check(g)

    def test_failed_upgrade_reaction_rolls_back_epoch_and_visibility(self):
        def fail(c):raise RuntimeError('intentional')
        self.r.register_behavior('fail',fail)
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=3,triggers=(TriggerSpec('hand_card_upgraded','fail'),)))
        self.script(lambda c:[UpgradeHandCard(self.ref(c),'up')]);g=self.game(board=('watcher',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_upgraded_hidden_face_and_private_events_do_not_leak(self):
        self.script(lambda c:[UpgradeHandCard(self.ref(c),'up')]);g=self.game();self.play(g)
        kinds=[e['kind'] for e in g.player_events(2)];self.assertNotIn('hand_card_upgraded',kinds)
        self.assertIsNone(g.observe(2)['players'][0]['hand'][0]['card_id'])
        self.assertIn('hand_card_upgraded',[e['kind'] for e in g.player_events(1)]);self.check(g)

    def test_previously_revealed_face_is_forgotten_after_upgrade(self):
        self.script(lambda c:[RevealHandCard(self.ref(c).entity_id,(2,)),UpgradeHandCard(self.ref(c),'up')]);g=self.game();self.play(g)
        self.assertIsNone(g.observe(2)['players'][0]['hand'][0]['card_id'])
        self.assertFalse(any(e['kind']=='hand_card_upgraded' for e in g.player_events(2)));self.check(g)

    def test_known_enemy_face_does_not_reveal_hidden_buff(self):
        self.script(lambda c:[RevealHandCard(self.ref(c).entity_id,(2,)),BuffStoredCard(self.ref(c),2,2)]);g=self.game();self.play(g)
        self.assertEqual(set(g.observe(2)['players'][0]['hand'][0]),{'ref','card_id'})
        self.assertFalse(any(e['kind']=='stored_card_buffed' for e in g.player_events(2)));self.check(g)

    def test_internal_epoch_never_enters_player_view(self):
        self.script(lambda c:[UpgradeHandCard(self.ref(c),'up')]);g=self.game();self.play(g)
        self.assertNotIn('zone_epoch',json.dumps(g.observe(1)));self.assertNotIn('zone_epoch',json.dumps(g.player_events(1)))

    def test_corrupt_epoch_is_rejected_with_recomputed_hash(self):
        g=self.game(hand=('base',))
        for epoch in (-1,True,'1'):
            data=g.snapshot();data['state']['entities'][str(self.card(g).id)]['zone_epoch']=epoch
            data['state_hash']=canonical_hash({k:v for k,v in data.items() if k not in ('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r,self.m)

    def test_invalid_effect_payloads_reject(self):
        ref=CardReference(1,1,Zone.HAND,'base',0)
        for call in (lambda:CardReference(1,1,Zone.HAND,'base',True),lambda:BuffStoredCard(ref,True),
                lambda:BuffStoredCard(ref,health=-1),lambda:UpgradeHandCard(ref,'up',health_to_durability=1),
                lambda:UpgradeHandCard(replace(ref,zone=Zone.DECK),'up')):
            with self.assertRaises(ValueError):call()

    def test_old_schema_28_is_rejected(self):
        g=self.game(hand=('base',));data=g.snapshot();self.assertEqual(data['schema_version'],SNAPSHOT_SCHEMA_VERSION);data['schema_version']=28
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r,self.m)


if __name__=='__main__':unittest.main()
