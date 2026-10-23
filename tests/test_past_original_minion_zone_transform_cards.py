"""Original physical self-shuffle and real post-damage transform boundaries."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards.past_original_minion_zone_transform_cards import (WEASEL,SPORE,AMALGAM,
    DEPENDENCIES,load_batch,register_past_original_minion_zone_transform_cards)
from hs_sim.engine import (Attack,AuraSpec,CardClass,CardDefinition,CardMetadata,CardType,
    EndTurn,Game,Keyword,PlayCard,PlayerSetup,Rarity,Scenario,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.deck_capacity import MAX_DECK_SIZE
from hs_sim.engine.effects import (Buff,ChangeControl,ChoiceOption,Damage,Destroy,GainArmor,
    GrantDeathrattle,GrantKeyword,InvokeBehavior,RequestChoice,ReturnToHand,SetStats,Silence,
    Transform,TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec,DamageKind
from hs_sim.engine.original_minion_shuffles import ShuffleOriginalMinion
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.zones import CardReference,MoveCard

P='k482.';FILLER=P+'filler';HARD=P+'hard';SMALL=P+'small';SHIELD=P+'shield';AURA=P+'aura';WATCH=P+'watch'
META=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=defaults();register_past_original_minion_zone_transform_cards(r);r._version='k482-'+mode
    for cid,attack,health,kwargs in((FILLER,0,8,{}),(HARD,3,8,{}),(SMALL,0,1,{}),
            (SHIELD,0,8,{'keywords':(Keyword.DIVINE_SHIELD,)}),(AURA,0,9,{'auras':(AuraSpec(attack=4,health=4),)})):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=8,attack=attack,health=health,metadata=META,**kwargs))
    def fail(c):raise ResolutionError('K482 deliberate late transfer failure')
    def take(c):
        ids=[i for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id in(WEASEL,AMALGAM)]
        return (MoveCard(CardReference.capture(c.state.entities[ids[-1]]),c.player_id,Zone.HAND,source_id=c.source_id),)if ids else()
    def hand_buff(c):
        source=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==AMALGAM)
        return (BuffStoredCard(CardReference.capture(source),attack=2,health=3,source_id=c.source_id,cost=CostSpec(delta=-1)),)
    def from_spore(c):
        source=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==SPORE)
        return (Damage(c.target_id,1,source.id,DamageKind.MINION_ABILITY),)
    def menu(c):
        source=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==WEASEL)
        req=ShuffleOriginalMinion(SourceAllocationFact.capture(c.state,source),3-c.player_id,c.source_id)
        return (RequestChoice(c.player_id,(ChoiceOption('go','Go',(req,)),
            ChoiceOption('stale','Return first',(ReturnToHand(source.id),req))),c.source_id),)
    scripts={
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'buff':lambda c:(Buff(c.target_id,2,3,c.source_id),),
        'debuff':lambda c:(Buff(c.target_id,-1,source_id=c.source_id),),
        'temporary':lambda c:(Buff(c.target_id,3,3,c.source_id,expires_turn=c.state.turn),),
        'taunt':lambda c:(GrantKeyword(c.target_id,Keyword.TAUNT,c.source_id),),
        'give':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'manual':lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        'ping':lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        'from-spore':from_spore,'hand-buff':hand_buff,'take':take,'menu':menu,
        'extra-rattle':lambda c:(GrantDeathrattle(c.target_id,P+'armor-rattle',c.source_id),),
    }
    r.register_behavior(P+'fail',fail);r.register_behavior(P+'armor-rattle',lambda c:(GainArmor(c.player_id,1),))
    for key,body in scripts.items():
        r.register_behavior(P+key,body)
        r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,metadata=META,
            targeting=None if key in('hand-buff','take','menu')else TargetSpec()))
    def watch(c):
        event=c.event
        if event.kind=='card_shuffled'and c.state.entities[event.target_id].card_id in(WEASEL,AMALGAM):
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode=='wait':return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        if mode=='preempt'and event.kind=='damage_dealt'and event.source_id is not None and c.state.entities[event.source_id].card_id==SPORE:
            return (Transform(event.target_id,SHIELD),)
        return ()
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=9,metadata=META,
        triggers=(TriggerSpec('card_shuffled',WATCH),TriggerSpec('damage_dealt',WATCH))))
    r.validate();return r


class PastOriginalMinionZoneTransformTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)

    def game(self,hand=(),*,board=(),deck=(),enemy=(FILLER,),enemy_hand=(),enemy_deck=(),mode='normal',seed=482):
        self.mode=mode
        if mode in('wait','fail','preempt'):board=(WATCH,*board)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,
            mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=enemy_deck,
            mana=50,max_mana=50,mana_cap=50)),seed=seed),fixture(mode))

    def stats(self,g,eid,attack,health):
        entity=g.state.entities[eid];self.assertEqual((entity.attack,entity.max_health,entity.health),(attack,health,health))

    def test_complete_three_rows_six_full_primary_faces_and_all_tribes(self):
        d=load_batch();self.assertEqual((len(d['dependencies']),len(d['official_observations'])),(3,6))
        raw={x['record']['id']:x['record']for x in d['dependencies']}
        for o in d['official_observations']:
            self.assertEqual(batch.sha(o['response_file']),o['response_sha256']);batch.check_face(raw[o['card_id']],o['face'],o['locale'])
        self.assertEqual(fixture().card(WEASEL).metadata.tribes,('beast',))
        self.assertEqual(fixture().card(AMALGAM).metadata.tribes,('all',))
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_weasel_dead_original_moves_to_enemy_without_keeping_normal_buffs(self):
        g=self.game((P+'buff',P+'kill'),board=(WEASEL,));source=g.state.players[1].board[0]
        self.play(g,P+'buff',source);self.play(g,P+'kill',source)
        self.assertEqual(g.state.players[2].deck,[source]);self.assertEqual((g.state.entities[source].owner,g.state.entities[source].controller),(1,2))
        self.stats(g,source,1,1);self.assertEqual(len(g.state.death_history),1)
        row,=g.state.deck_shuffle_history;self.assertEqual((row.actor_id,row.player_id,row.declared_count),(1,2,1));self.portable(g)

    def test_live_manual_weasel_shuffle_is_not_another_death_or_new_entity(self):
        g=self.game((P+'manual',),board=(WEASEL,));source=g.state.players[1].board[0];before=g.state.next_entity_id
        self.play(g,P+'manual',source);self.assertEqual(g.state.players[2].deck,[source])
        self.assertFalse(g.state.death_history);self.assertEqual(g.state.next_entity_id,before);self.portable(g)

    def test_transferred_weasel_uses_actual_death_controller_opponent(self):
        g=self.game((P+'give',),board=(WEASEL,),enemy_hand=(P+'kill',));source=g.state.players[1].board[0]
        self.play(g,P+'give',source);g.apply(EndTurn(1));self.play(g,P+'kill',source,player=2)
        self.assertEqual(g.state.players[1].deck,[source]);self.assertEqual(g.state.entities[source].controller,1)
        self.assertEqual(g.state.deck_shuffle_history[-1].actor_id,2);self.portable(g)

    def test_same_physical_body_only_shuffles_once_under_death_repeat(self):
        for cid in(WEASEL,AMALGAM):
            g=self.game((P+'kill',),board=(cid,'FP1_031'));source=g.state.players[1].board[0]
            self.play(g,P+'kill',source);recipient=2 if cid==WEASEL else 1
            self.assertEqual(g.state.players[recipient].deck,[source]);self.assertEqual(len(g.state.deck_shuffle_history),1)

    def test_foreign_receiver_capacity_does_not_read_original_controller_deck(self):
        g=self.game((P+'kill',),board=(WEASEL,),deck=(FILLER,)*MAX_DECK_SIZE)
        source=g.state.players[1].board[0];self.play(g,P+'kill',source)
        self.assertEqual(g.state.players[2].deck,[source]);self.assertEqual(len(g.state.players[1].deck),MAX_DECK_SIZE)

    def test_full_actual_receiver_keeps_dead_body_out_without_shuffle_credit(self):
        g=self.game((P+'kill',),board=(WEASEL,),enemy_deck=(FILLER,)*MAX_DECK_SIZE)
        source=g.state.players[1].board[0];self.play(g,P+'kill',source)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertFalse(g.state.deck_shuffle_history)
        self.assertEqual(len(g.state.players[2].deck),MAX_DECK_SIZE)

    def test_amalgam_keeps_hand_buff_discount_and_granted_keyword_but_heals_damage(self):
        g=self.game((AMALGAM,P+'hand-buff',P+'taunt',P+'ping',P+'kill'))
        self.play(g,P+'hand-buff');source=self.play(g,AMALGAM);self.play(g,P+'taunt',source)
        self.play(g,P+'ping',source);self.assertEqual(g.state.entities[source].damage,1)
        original_enchantments={e.id for e in g.state.entities[source].enchantments}
        original_abilities={a.id for a in g.state.entities[source].abilities}
        self.play(g,P+'kill',source);self.assertEqual(g.state.players[1].deck,[source])
        self.stats(g,source,3,5);self.assertEqual(g.state.entities[source].cost,0)
        self.assertEqual({e.id for e in g.state.entities[source].enchantments},original_enchantments)
        self.assertEqual({a.id for a in g.state.entities[source].abilities},original_abilities)
        self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords);self.portable(g)

    def test_live_manual_amalgam_keeps_same_body_material_without_death(self):
        g=self.game((P+'buff',P+'manual'),board=(AMALGAM,));source=g.state.players[1].board[0]
        self.play(g,P+'buff',source);self.play(g,P+'manual',source)
        self.assertEqual(g.state.players[1].deck,[source]);self.stats(g,source,3,5);self.assertFalse(g.state.death_history)

    def test_amalgam_does_not_store_external_board_aura_cache(self):
        g=self.game((P+'kill',),board=(AMALGAM,AURA));source=g.state.players[1].board[0]
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].max_health),(5,6))
        self.play(g,P+'kill',source);self.stats(g,source,1,2)

    def test_amalgam_keeps_negative_and_original_temporary_duration(self):
        g=self.game((P+'debuff',P+'temporary',P+'kill'),board=(AMALGAM,));source=g.state.players[1].board[0]
        self.play(g,P+'debuff',source);self.play(g,P+'temporary',source);self.play(g,P+'kill',source)
        self.stats(g,source,3,5);g.apply(EndTurn(1));self.stats(g,source,0,2);self.portable(g)

    def test_amalgam_retains_real_magnetic_material(self):
        g=self.game(('BOT_563',P+'kill'),board=(AMALGAM,));source=g.state.players[1].board[0]
        printed=g.registry.card('BOT_563');expected=(1+printed.attack,2+printed.health)
        gear=self.entity(g,'BOT_563').id;g.apply(PlayCard(1,gear,position=0));self.stats(g,source,*expected)
        self.play(g,P+'kill',source);self.stats(g,source,*expected);self.assertEqual(g.state.players[1].deck,[source]);self.portable(g)

    def test_amalgam_keeps_granted_deathrattle_for_next_actual_play(self):
        g=self.game((P+'extra-rattle',P+'kill',P+'take',P+'kill'),board=(AMALGAM,));source=g.state.players[1].board[0]
        self.play(g,P+'extra-rattle',source);self.play(g,P+'kill',source);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        self.play(g,P+'take');self.play(g,AMALGAM);self.play(g,P+'kill',source)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.assertEqual(g.state.players[1].deck,[source]);self.portable(g)

    def test_silence_removes_actual_self_shuffle_before_death(self):
        for cid in(WEASEL,AMALGAM):
            g=self.game((P+'silence',P+'kill'),board=(cid,));source=g.state.players[1].board[0]
            self.play(g,P+'silence',source);self.play(g,P+'kill',source)
            self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertFalse(g.state.deck_shuffle_history)

    def test_spore_real_combat_changes_original_surviving_enemy_body(self):
        g=self.game(board=(SPORE,));source=g.state.players[1].board[0];target=g.state.players[2].board[0]
        g.apply(Attack(1,source,target));self.assertEqual(g.state.entities[target].card_id,SPORE)
        self.assertEqual((g.state.entities[target].owner,g.state.entities[target].controller),(2,2));self.stats(g,target,1,2)
        self.assertFalse(g.state.death_history);self.portable(g)

    def test_spore_source_can_die_while_original_damage_still_transforms_target(self):
        g=self.game(board=(SPORE,),enemy=(HARD,));source=g.state.players[1].board[0];target=g.state.players[2].board[0]
        g.apply(Attack(1,source,target));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[target].card_id,SPORE);self.stats(g,target,1,2);self.portable(g)

    def test_spore_does_not_rescue_original_lethal_recipient(self):
        g=self.game(board=(SPORE,),enemy=(SMALL,));source=g.state.players[1].board[0];target=g.state.players[2].board[0]
        g.apply(Attack(1,source,target));self.assertEqual((g.state.entities[target].card_id,g.state.entities[target].zone),(SMALL,Zone.GRAVEYARD))
        self.assertEqual(g.state.death_history[-1].card_id,SMALL)

    def test_shielded_zero_damage_and_hero_damage_do_not_transform(self):
        g=self.game(board=(SPORE,),enemy=(SHIELD,));source=g.state.players[1].board[0];target=g.state.players[2].board[0]
        g.apply(Attack(1,source,target));self.assertEqual(g.state.entities[target].card_id,SHIELD)
        g=self.game(board=(SPORE,));source=g.state.players[1].board[0];hero=g.state.players[2].hero_id
        g.apply(Attack(1,source,hero));self.assertEqual((g.state.entities[hero].kind,g.state.entities[hero].health),(CardType.HERO,29))

    def test_spore_transforms_friendly_damage_recipient_but_not_unrelated_spell_damage(self):
        g=self.game((P+'ping',P+'from-spore'),board=(SPORE,FILLER));target=g.state.players[1].board[1]
        self.play(g,P+'ping',target);self.assertEqual(g.state.entities[target].card_id,FILLER)
        self.play(g,P+'from-spore',target);self.assertEqual(g.state.entities[target].card_id,SPORE);self.stats(g,target,1,2)

    def test_two_spores_transform_each_other_without_recursion_or_death(self):
        g=self.game(board=(SPORE,),enemy=(SPORE,));a=g.state.players[1].board[0];z=g.state.players[2].board[0]
        g.apply(Attack(1,a,z));self.stats(g,a,1,2);self.stats(g,z,1,2);self.assertFalse(g.state.death_history);self.portable(g)

    def test_silenced_spore_has_no_new_post_damage_body(self):
        g=self.game((P+'silence',),board=(SPORE,));source=g.state.players[1].board[0];target=g.state.players[2].board[0]
        self.play(g,P+'silence',source);g.apply(Attack(1,source,target));self.assertEqual(g.state.entities[target].card_id,FILLER)

    def test_prior_transform_invalidates_original_target_residence(self):
        g=self.game(board=(SPORE,),mode='preempt');source=g.state.players[1].board[-1];target=g.state.players[2].board[0]
        g.apply(Attack(1,source,target));self.assertEqual(g.state.entities[target].card_id,SHIELD);self.portable(g)

    def test_shuffle_request_waits_with_original_reference_and_stale_departure_skips(self):
        for key in('go','stale'):
            g=self.game((P+'menu',),board=(WEASEL,));source=g.state.players[1].board[0]
            self.play(g,P+'menu');other=self.portable(g);self.choose(g,key);self.choose(other,key)
            self.assertEqual(g.snapshot(),other.snapshot())
            if key=='go':self.assertEqual(g.state.players[2].deck,[source])
            else:self.assertEqual(g.state.entities[source].zone,Zone.HAND);self.assertFalse(g.state.deck_shuffle_history)

    def test_moved_keep_material_wait_restore_and_failed_selection_preserve_boundary(self):
        g=self.game((P+'buff',P+'kill'),board=(AMALGAM,),mode='wait');source=g.state.players[1].board[-1]
        self.play(g,P+'buff',source);self.play(g,P+'kill',source);saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.stats(g,source,3,5)

    def test_late_foreign_transfer_failure_rolls_back_death_controller_rng_and_history(self):
        g=self.game((P+'kill',),board=(WEASEL,),mode='fail');source=g.state.players[1].board[-1];before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'kill',source)
        self.assertEqual(g.snapshot(),before)

    def test_future_or_unsupported_retained_transfer_request_is_rejected(self):
        g=self.game(board=(AMALGAM,));source=g.state.entities[g.state.players[1].board[0]];fact=SourceAllocationFact.capture(g.state,source)
        with self.assertRaises(ValueError):ShuffleOriginalMinion(fact,2,keep_enchantments=True)
        req=ShuffleOriginalMinion(replace(fact,next_entity_id=g.state.next_entity_id+1),1)
        with self.assertRaises(ValueError):req.validate_in_state(g.state)

    def test_player_views_do_not_expose_original_fact_or_current_deck_handles(self):
        g=self.game((P+'kill',),board=(WEASEL,));self.play(g,P+'kill',g.state.players[1].board[0])
        for player in(1,2):
            text=json.dumps(g.for_player(player).observe())
            for key in('keep_enchantments','next_entity_id','zone_epoch','rng_state','death_cause'):
                self.assertNotIn(key,text)

    def test_central_registry_contains_all_three_complete_native_definitions(self):
        r=build_registry();self.assertTrue(set(DEPENDENCIES)<=set(r.cards))


if __name__=='__main__':unittest.main()
