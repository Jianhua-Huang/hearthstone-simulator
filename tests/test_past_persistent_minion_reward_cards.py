"""Physical printed growth, original copy recipes and a separate family program."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards.past_persistent_minion_reward_cards import (RAPTOR,FEEDER,DISPLAY,
    DEPENDENCIES,PREFIX,PROGRAM,load_batch,register_past_persistent_minion_reward_cards)
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,
    Game,Keyword,PlayerSetup,Rarity,Scenario,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,CopyMinion,
    Damage,Destroy,GrantDeathrattle,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.jade import CLASSIC,SummonJadeGolem,printed_definition
from hs_sim.engine.model import DamageKind,Enchantment,SummonStats
from hs_sim.engine.permanent_minion_stats import CreateGrowingMinion,LABEL,value,validate_carrier
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import ResurrectMinion,SummonFromZone
from hs_sim.engine.zones import CardReference,CopyCard,DiscardCard,MoveCard

P='k481.';FILLER=P+'filler';WATCH=P+'watch'
META=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


@lru_cache(None)
def classic_material():
    r=build_registry();family=r.jade_families[CLASSIC]
    return family,tuple((r.card(cid),r.pool_card(cid))for cid in family.forms)


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=defaults();register_past_persistent_minion_reward_cards(r);r._version='k481-'+mode
    family,templates=classic_material()
    for card,pool in templates:r.register_card(card);r.register_pool_card(pool)
    r.register_jade_family(family)
    r.register_card(CardDefinition(FILLER,FILLER,CardType.MINION,cost=8,attack=2,health=9,metadata=META))
    def fail(c):raise ResolutionError('K481 deliberate late creation failure')
    def take(c,cid):
        ids=[i for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id==cid]
        return (MoveCard(CardReference.capture(c.state.entities[ids[-1]]),c.player_id,Zone.HAND,source_id=c.source_id),)if ids else()
    def copy(c,mode='base',other=False):
        return (CopyCard(MinionReference.capture(c.state.entities[c.target_id]),3-c.player_id if other else c.player_id,
            mode=mode,source_id=c.source_id),)
    def played(c):
        row=next(x for x in reversed(c.state.play_history)if x.player_id==c.player_id and x.kind==CardType.MINION)
        return (CopyCard(row.minion_copy_material,c.player_id,mode='base',source_id=c.source_id),)
    def discarded(c):
        source=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].kind==CardType.MINION)
        return (DiscardCard(CardReference.capture(source),c.source_id),)
    def menu(c):
        source=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==FEEDER)
        request=CreateGrowingMinion(CapturedCardCopyMaterial.capture(c.state,source),c.player_id,2,2,'bottom')
        return (RequestChoice(c.player_id,(ChoiceOption('grow','Grow',(request,)),),c.source_id),)
    scripts={
        'ping':lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'buff':lambda c:(Buff(c.target_id,5,5,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'give':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'transform':lambda c:(Transform(c.target_id,FILLER),),
        'copy-base':lambda c:copy(c),
        'copy-current':lambda c:copy(c,'current'),
        'copy-opponent':lambda c:copy(c,other=True),
        'copy-board':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'take-r':lambda c:take(c,RAPTOR),'take-f':lambda c:take(c,FEEDER),
        'take-d':lambda c:take(c,DISPLAY),'played-copy':played,'discard':discarded,
        'discard-copy':lambda c:(CopyCard(c.state.discard_history[-1],c.player_id,mode='base',source_id=c.source_id),),
        'resurrect':lambda c:(ResurrectMinion(c.player_id,c.state.death_history[-1].id,
            source_id=c.source_id,cause=SummonCause.capture(c)),),
        'recruit':lambda c:(SummonFromZone(c.player_id,query=PoolQuery(kinds=(CardType.MINION,),attack_equals=3),
            source_id=c.source_id,cause=SummonCause.capture(c)),),
        'feeder-rattle':lambda c:(GrantDeathrattle(c.target_id,PREFIX+FEEDER,c.source_id),),
        'menu':menu,
        'jade-two':lambda c:(SummonJadeGolem(c.player_id,c.source_id,count=2),),
    }
    r.register_behavior(P+'fail',fail)
    for key,body in scripts.items():
        r.register_behavior(P+key,body)
        r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,metadata=META,
            targeting=TargetSpec()if key in('ping','kill','buff','silence','give','bounce','transform',
                'copy-base','copy-current','copy-opponent','copy-board','feeder-rattle')else None))
    def watch(c):
        e=c.event
        if e.kind=='card_added_to_deck'and c.state.entities[e.target_id].card_id in(RAPTOR,FEEDER):
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode=='wait':return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        if mode=='recruit-wait'and e.kind=='minion_summoned'and c.state.entities[e.target_id].card_id==FEEDER:
            return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),),c.source_id),)
        return ()
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=9,
        metadata=META,triggers=(TriggerSpec('card_added_to_deck',WATCH),TriggerSpec('minion_summoned',WATCH))))
    r.validate();return r


class PastPersistentMinionRewardTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)

    def game(self,hand=(),*,board=(),deck=(),enemy=(FILLER,),enemy_hand=(),mode='normal',seed=481):
        self.mode=mode
        if mode in('wait','fail','recruit-wait'):board=(WATCH,*board)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,
            mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,
            mana=50,max_mana=50,mana_cap=50)),seed=seed),fixture(mode))

    def assert_stats(self,g,eid,attack,health):
        e=g.state.entities[eid];self.assertEqual((e.attack,e.max_health),(attack,health))

    def grow_feeder(self,g):
        source=self.entity(g,FEEDER,zone='board').id;self.play(g,P+'kill',source)
        created=self.entity(g,FEEDER,zone='deck');self.assert_stats(g,created.id,3,5);return created.id

    def test_complete_five_rows_six_primary_faces_and_distinct_growth_semantics(self):
        d=load_batch();raw={x['record']['id']:x['record']for x in d['dependencies']}
        self.assertEqual((len(d['dependencies']),len(d['evidence_only']),len(d['official_observations'])),(3,2,6))
        for o in d['official_observations']:
            self.assertEqual(batch.sha(o['response_file']),o['response_sha256']);batch.check_face(raw[o['card_id']],o['face'],o['locale'])
        self.assertEqual(fixture().player_effect(PROGRAM).auras[0].scope,'controlled_minion_cards')
        self.assertEqual(fixture().card(RAPTOR).metadata.tribes,('beast',))
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_raptor_first_frenzy_grows_only_new_copy_and_only_once(self):
        g=self.game((RAPTOR,P+'ping',P+'ping'));source=self.play(g,RAPTOR)
        self.play(g,P+'ping',source);new=self.entity(g,RAPTOR,zone='deck').id
        self.assert_stats(g,new,3,4);self.assert_stats(g,source,1,3)
        self.play(g,P+'ping',source);self.assertEqual(len(g.state.players[1].deck),1)
        self.assertEqual(len(g.state.deck_shuffle_history),1);self.assertEqual(g.state.players[1].mana,49)
        self.portable(g)

    def test_raptor_lethal_damage_does_not_frenzy(self):
        g=self.game((P+'kill',),board=(RAPTOR,));self.play(g,P+'kill',g.state.players[1].board[0])
        self.assertFalse(g.state.players[1].deck)

    def test_raptor_second_generation_is_five_five_without_buffing_other_copy(self):
        g=self.game((RAPTOR,P+'ping',P+'take-r',P+'ping'),board=(RAPTOR,));original=g.state.players[1].board[0]
        source=self.play(g,RAPTOR);self.play(g,P+'ping',source);self.play(g,P+'take-r')
        source2=self.play(g,RAPTOR);self.play(g,P+'ping',source2)
        self.assert_stats(g,self.entity(g,RAPTOR,zone='deck').id,5,5);self.assert_stats(g,original,1,3)
        self.portable(g)

    def test_feeder_is_new_physical_bottom_card_without_shuffle_credit_or_rng(self):
        g=self.game((P+'kill',),board=(FEEDER,),deck=(FILLER,FILLER));before=g.snapshot()['rng_state']
        original=g.state.players[1].board[0];new=self.grow_feeder(g)
        self.assertNotEqual(new,original);self.assertEqual(g.state.players[1].deck[-1],new)
        self.assertEqual(g.state.entities[new].origin_entity_id,original)
        self.assertFalse(g.state.deck_shuffle_history);self.assertEqual(g.snapshot()['rng_state'],before)
        self.portable(g)

    def test_feeder_second_generation_keeps_only_native_growth(self):
        g=self.game((P+'kill',P+'take-f',P+'buff',P+'kill'),board=(FEEDER,))
        self.grow_feeder(g);self.play(g,P+'take-f');source=self.play(g,FEEDER)
        self.play(g,P+'buff',source);self.assert_stats(g,source,8,10);self.play(g,P+'kill',source)
        new=self.entity(g,FEEDER,zone='deck');self.assert_stats(g,new.id,5,7)
        self.assertEqual(len([e for e in new.enchantments if e.label==LABEL]),1);self.portable(g)

    def test_silence_keeps_permanent_stats_but_removes_next_deathrattle(self):
        g=self.game((P+'kill',P+'take-f',P+'buff',P+'silence',P+'kill'),board=(FEEDER,))
        self.grow_feeder(g);self.play(g,P+'take-f');source=self.play(g,FEEDER);self.play(g,P+'buff',source)
        self.play(g,P+'silence',source);self.assert_stats(g,source,3,5)
        self.play(g,P+'kill',source);self.assertFalse(g.state.players[1].deck);self.portable(g)

    def test_bounce_replay_keeps_permanent_base_and_restores_printed_body(self):
        g=self.game((P+'kill',P+'take-f',P+'silence',P+'bounce',P+'kill'),board=(FEEDER,))
        self.grow_feeder(g);self.play(g,P+'take-f');source=self.play(g,FEEDER)
        self.play(g,P+'silence',source);self.play(g,P+'bounce',source);self.assert_stats(g,source,3,5)
        self.play(g,FEEDER);self.play(g,P+'kill',source)
        self.assert_stats(g,self.entity(g,FEEDER,zone='deck').id,5,7);self.portable(g)

    def test_transform_discards_old_permanent_base(self):
        g=self.game((P+'kill',P+'take-f',P+'transform'),board=(FEEDER,));self.grow_feeder(g)
        self.play(g,P+'take-f');source=self.play(g,FEEDER);self.play(g,P+'transform',source)
        self.assert_stats(g,source,2,9);self.assertIsNone(value(g.state.entities[source]));self.portable(g)

    def test_base_and_current_hand_copies_keep_native_base_with_distinct_local_buffs(self):
        g=self.game((P+'kill',P+'take-f',P+'buff',P+'copy-base',P+'copy-current'),board=(FEEDER,))
        self.grow_feeder(g);self.play(g,P+'take-f');source=self.play(g,FEEDER);self.play(g,P+'buff',source)
        self.play(g,P+'copy-base',source);self.play(g,P+'copy-current',source)
        copies=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==FEEDER]
        self.assertEqual([(e.attack,e.max_health)for e in copies],[(3,5),(8,10)])
        self.assertEqual([value(e)for e in copies],[SummonStats(3,5)]*2);self.portable(g)

    def test_current_board_copy_keeps_native_base_and_independent_attachments(self):
        g=self.game((P+'kill',P+'take-f',P+'copy-board',P+'kill'),board=(FEEDER,))
        self.grow_feeder(g);self.play(g,P+'take-f');source=self.play(g,FEEDER);self.play(g,P+'copy-board',source)
        copy=g.state.players[1].board[-1];self.assertNotEqual(copy,source);self.assert_stats(g,copy,3,5)
        a={e.id for e in g.state.entities[source].enchantments};z={e.id for e in g.state.entities[copy].enchantments}
        self.assertFalse(a&z);self.play(g,P+'kill',copy);self.assert_stats(g,self.entity(g,FEEDER,zone='deck').id,5,7)
        self.portable(g)

    def test_resurrection_uses_original_native_base_and_not_local_buff(self):
        g=self.game((P+'kill',P+'take-f',P+'buff',P+'kill',P+'resurrect'),board=(FEEDER,))
        self.grow_feeder(g);self.play(g,P+'take-f');source=self.play(g,FEEDER);self.play(g,P+'buff',source)
        self.play(g,P+'kill',source);self.play(g,P+'resurrect')
        revived=self.entity(g,FEEDER,zone='board');self.assertNotEqual(revived.id,source)
        self.assert_stats(g,revived.id,3,5);self.portable(g)

    def test_discard_history_keeps_original_printed_growth_for_base_copy(self):
        g=self.game((P+'kill',P+'take-f',P+'discard',P+'discard-copy'),board=(FEEDER,))
        self.grow_feeder(g);self.play(g,P+'take-f');self.play(g,P+'discard')
        self.assertEqual(g.state.discard_history[-1].permanent_stats,SummonStats(3,5));self.portable(g)
        self.play(g,P+'discard-copy');self.assert_stats(g,self.entity(g,FEEDER).id,3,5);self.portable(g)

    def test_played_recipe_keeps_native_base_after_original_transforms(self):
        g=self.game((P+'kill',P+'take-f',P+'transform',P+'played-copy'),board=(FEEDER,))
        self.grow_feeder(g);self.play(g,P+'take-f');source=self.play(g,FEEDER)
        self.play(g,P+'transform',source);self.play(g,P+'played-copy')
        self.assert_stats(g,self.entity(g,FEEDER).id,3,5);self.portable(g)

    def test_recruit_printed_attack_filter_and_frozen_basis_keep_native_base(self):
        g=self.game((P+'kill',P+'recruit'),board=(FEEDER,),deck=(FILLER,),mode='recruit-wait')
        self.grow_feeder(g);self.play(g,P+'recruit');self.assertIsNotNone(g.state.pending_choice)
        self.assert_stats(g,self.entity(g,FEEDER,zone='board').id,3,5)
        self.portable(g);self.choose(g);self.portable(g)

    def test_granted_feeder_deathrattle_copies_original_carrier_face(self):
        g=self.game((P+'feeder-rattle',P+'kill'),board=(FILLER,));source=g.state.players[1].board[0]
        self.play(g,P+'feeder-rattle',source);self.play(g,P+'kill',source)
        copy=self.entity(g,FILLER,zone='deck');self.assert_stats(g,copy.id,4,11)
        self.assertFalse([a for a in copy.abilities if a.kind=='deathrattle']);self.portable(g)

    def test_feeder_repeated_deathrattle_creates_two_equal_copies(self):
        g=self.game((P+'kill',),board=(FEEDER,'FP1_031'));self.play(g,P+'kill',g.state.players[1].board[0])
        copies=[g.state.entities[i]for i in g.state.players[1].deck]
        self.assertEqual([(e.card_id,e.attack,e.max_health)for e in copies],[(FEEDER,3,5)]*2)
        self.assertNotEqual(copies[0].id,copies[1].id);self.assertFalse(g.state.deck_shuffle_history)

    def test_growing_original_carrier_keeps_intrinsic_jade_size_cost_and_origin(self):
        g=self.game((P+'jade-two',P+'feeder-rattle',P+'kill'))
        self.play(g,P+'jade-two');source=g.state.players[1].board[-1]
        self.assertEqual((g.state.entities[source].jade_size,g.state.entities[source].cost),(2,2))
        self.play(g,P+'feeder-rattle',source);self.play(g,P+'kill',source)
        copied=g.state.entities[g.state.players[1].deck[-1]];self.assert_stats(g,copied.id,4,4)
        self.assertEqual((copied.jade_size,copied.cost,copied.origin_entity_id),(2,2,source));self.portable(g)

    def test_transferred_feeder_gives_new_copy_to_actual_death_controller(self):
        g=self.game((P+'give',),board=(FEEDER,),enemy_hand=(P+'kill',));source=g.state.players[1].board[0]
        self.play(g,P+'give',source);g.apply(EndTurn(1));self.play(g,P+'kill',source,player=2)
        copy=self.entity(g,FEEDER,player=2,zone='deck');self.assertEqual((copy.owner,copy.controller),(2,2))
        self.assert_stats(g,copy.id,3,5);self.portable(g)

    def test_growth_request_can_wait_restore_before_original_material_is_used(self):
        g=self.game((P+'menu',),board=(FEEDER,));self.play(g,P+'menu');other=self.portable(g)
        self.choose(g,'grow');self.choose(other,'grow');self.assertEqual(g.snapshot(),other.snapshot())
        self.assert_stats(g,self.entity(g,FEEDER,zone='deck').id,3,5);self.portable(g)

    def test_creation_wait_restore_and_failed_selection_preserve_committed_growth(self):
        g=self.game((P+'kill',),board=(FEEDER,),mode='wait');self.play(g,P+'kill',g.state.players[1].board[-1])
        saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())

    def test_late_creation_failure_rolls_back_death_and_native_base(self):
        g=self.game((P+'kill',),board=(FEEDER,),mode='fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'kill',g.state.players[1].board[-1])
        self.assertEqual(g.snapshot(),before)

    def test_display_first_death_grows_hand_deck_board_and_new_named_copies(self):
        g=self.game((DISPLAY,P+'kill'),board=(DISPLAY,DISPLAY),deck=(DISPLAY,FILLER))
        self.play(g,P+'kill',g.state.players[1].board[0])
        all_owned=[e for e in g.state.entities.values()if e.card_id==DISPLAY and e.controller==1
            and e.zone in(Zone.HAND,Zone.DECK,Zone.BOARD)]
        self.assertEqual(len(all_owned),5);self.assertTrue(all((e.attack,e.max_health)==(2,2)for e in all_owned))
        self.assertTrue(all(value(e)is None for e in all_owned));self.assertEqual(len(g.state.deck_shuffle_history),1)
        self.portable(g)

    def test_display_repeat_deathrattle_grows_program_twice_and_shuffles_four(self):
        g=self.game((P+'kill',),board=(DISPLAY,'FP1_031'));self.play(g,P+'kill',g.state.players[1].board[0])
        self.assertEqual(len(g.state.players[1].deck),4)
        self.assertTrue(all((g.state.entities[i].attack,g.state.entities[i].max_health)==(3,3)for i in g.state.players[1].deck))
        self.assertEqual(len(g.state.deck_shuffle_history),2);self.portable(g)

    def test_display_global_aura_is_separate_from_silenced_body_and_current_controller(self):
        g=self.game((P+'kill',P+'silence',P+'give'),board=(DISPLAY,DISPLAY));source=g.state.players[1].board[0]
        self.play(g,P+'kill',source);other=g.state.players[1].board[0];self.assert_stats(g,other,2,2)
        self.play(g,P+'silence',other);self.assert_stats(g,other,2,2)
        self.play(g,P+'give',other);self.assert_stats(g,other,1,1);self.portable(g)

    def test_display_base_copy_to_opponent_does_not_copy_owner_global_aura(self):
        g=self.game((P+'kill',P+'copy-opponent'),board=(DISPLAY,DISPLAY));self.play(g,P+'kill',g.state.players[1].board[0])
        other=g.state.players[1].board[0];self.play(g,P+'copy-opponent',other)
        copied=self.entity(g,DISPLAY,player=2);self.assert_stats(g,copied.id,1,1);self.assertIsNone(value(copied));self.portable(g)

    def test_invalid_native_base_shape_and_duplicate_are_rejected(self):
        for kwargs in({'remove_on_silence':True},{'set_health':None},{'attack':1},{'expires_turn':2}):
            args={'id':1,'label':LABEL,'set_attack':3,'set_health':5,'remove_on_silence':False}|kwargs
            with self.assertRaises(ValueError):Enchantment(**args)
        g=self.game(board=(FEEDER,));entity=deepcopy(g.state.entities[g.state.players[1].board[0]])
        entity.enchantments=[Enchantment(i,label=LABEL,set_attack=3,set_health=5,remove_on_silence=False)for i in(1,2)]
        with self.assertRaises(ValueError):validate_carrier(entity)

    def test_snapshot_rejects_removable_permanent_growth(self):
        g=self.game((P+'kill',),board=(FEEDER,));new=self.grow_feeder(g);bad=deepcopy(g.snapshot())
        row=next(e for e in bad['state']['entities'][str(new)]['enchantments']if e['label']==LABEL)
        row['remove_on_silence']=True
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,fixture())

    def test_player_views_keep_private_recipe_and_growth_layers_internal(self):
        g=self.game((P+'kill',),board=(FEEDER,));self.grow_feeder(g)
        for player in(1,2):
            text=json.dumps(g.for_player(player).observe())
            for key in(LABEL,'permanent_stats','next_attachment_id','rng_state','source_sha256'):
                self.assertNotIn(key,text)

    def test_central_assembly_registers_three_sources_and_not_raw_enchantments(self):
        r=build_registry();self.assertTrue(set(DEPENDENCIES)<=set(r.cards))
        self.assertTrue(all(x['record']['id']not in r.cards for x in load_batch()['evidence_only']))


if __name__=='__main__':unittest.main()
