"""Real returned-card, original-controller and next-owner-turn boundaries."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT, historical_definition_digests
from copy import deepcopy
from dataclasses import replace
import json,unittest
from pathlib import Path
from hs_sim.cards import build_registry
from hs_sim.cards.temporal_effect_cards import load_batch,BATCH_HASH,PREFIX,DAZE,CHAINS,CEREMONY,SEAS,NAGA
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,
    PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Destroy,GainArmor,InvokeBehavior,
    RemoveEnchantment,RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import Enchantment,OwnerTurnExpiry,PlayerEffectSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

YETI='CORE_CS2_182';META=CardMetadata(False,(CardClass.NEUTRAL,),None)


def registry():
    r=build_registry()
    def fail(c):raise ResolutionError('K70 deliberate late failure')
    r.register_behavior('k70.fail',fail)
    scripts={
        'silence':lambda c:(Silence(c.target_id),),
        'destroy':lambda c:(Destroy(c.target_id,c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'face':lambda c:(Transform(c.target_id,'k70.form'),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'give':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'sleep':lambda c:(MakeDormant(c.target_id,None),),
        'remove':lambda c:tuple(RemoveEnchantment(c.target_id,e.id)for e in c.state.entities[c.target_id].enchantments if e.control_return_player_id is not None),
        'extra':lambda c:(QueueTurns((1,1,2),c.source_id),),
        'skip':lambda c:(SkipTurns(2,1,c.source_id),),
        'auto_ceremony':lambda c:(CastSpell(2,CEREMONY,c.source_id),),
        'auto_seas':lambda c:(CastSpell(2,SEAS,c.source_id),),
        'fault_return':lambda c:(ReturnToHand(c.target_id,to_owner=True,lock_next_owner_turn=True,source_id=c.source_id),InvokeBehavior('k70.fail',c.source_id,c.player_id)),
        'fault_control':lambda c:(ChangeControl(c.target_id,c.player_id,source_id=c.source_id,until_previous_controller_turn_end=True,cannot_attack_this_turn=True),InvokeBehavior('k70.fail',c.source_id,c.player_id)),
    }
    for key,body in scripts.items():
        cid='k70.'+key;r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,key,CardType.SPELL,on_play=cid,requires_target=key in('silence','destroy','bounce','face','copy','give','sleep','remove','fault_return','fault_control'),metadata=META))
    r.register_card(CardDefinition('k70.form','Different face',CardType.MINION,attack=1,health=4,metadata=META))
    r.register_card(CardDefinition('k70.dormant','Dormant',CardType.MINION,attack=2,health=4,dormant_turns=None,permanent_dormancy=True,metadata=META))
    r.register_card(CardDefinition('k70.charge','Charger',CardType.MINION,attack=3,health=5,keywords=(Keyword.CHARGE,),metadata=META))
    def returned(c):
        if not any(e.hand_play_lock for e in c.state.entities[c.event.target_id].enchantments):
            return()
        ref=CardReference.capture(c.state.entities[c.event.target_id])
        return(RequestChoice(1,(ChoiceOption('ok','Continue',(GainArmor(c.state.players[1].hero_id,1),)),
            ChoiceOption('summon','Summon the original',(SummonStoredCard(ref,ref.player_id),)),
            ChoiceOption('fault','Fail',(InvokeBehavior('k70.fail',c.source_id,1),))),c.source_id),)
    def controlled(c):
        e=c.state.entities[c.event.target_id]
        if not any(a.attack_policy is not None and a.attack_policy.mode=='cannot_attack_or_use_minion_abilities'for a in e.abilities):
            raise ResolutionError('Control observer did not see the installed attack prohibition')
        return(GainArmor(c.state.players[1].hero_id,1),)
    def ending(c):
        if c.event.player_id!=2:return()
        return(RequestChoice(1,(ChoiceOption('ok','Continue',()),
            ChoiceOption('fault','Fail',(InvokeBehavior('k70.fail',c.source_id,1),))),c.source_id),)
    def ceremony_at_end(c):
        return(CastSpell(1,CEREMONY,c.source_id),)if c.event.player_id==1 and c.state.turn==1 else()
    for key,event,body in(('returned','card_returned',returned),('controlled','control_changed',controlled),
            ('ending','turn_ended',ending),('late_ceremony','turn_ended',ceremony_at_end)):
        cid='k70.watch.'+key;r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,key,CardType.MINION,attack=1,health=9,triggers=(TriggerSpec(event,cid),),metadata=META))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
    return saved


class TemporalEffectCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),enemy_cap=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*12,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*12,mana=30,max_mana=30,mana_cap=30,hand_cap=enemy_cap)),seed=1070),self.r)
    def entities(self,g,cid,p=1,zone='board'):
        s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid]
    def play(self,g,cid,target=None,p=1):
        eid=self.entities(g,cid,p,'hand')[0].id;g.apply(PlayCard(p,eid,target));return eid
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def hero(self,g,p=1):return g.state.players[p].hero_id
    def portable(self,g):
        saved=g.snapshot();other=Game.from_snapshot(saved,registry());self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return other
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def marker(self,g,eid):return next(e for e in g.state.entities[eid].enchantments if e.control_return_player_id is not None)
    def waiting_return(self):
        g=self.game((DAZE,),board=('k70.watch.returned',),enemy=(YETI,),enemy_hand=('k70.bounce',));target=self.entities(g,YETI,2)[0].id
        self.play(g,DAZE,target);self.assertIsNotNone(g.state.pending_choice);return g,target
    def steal(self,g):
        target=g.state.players[2].board[0];self.play(g,CHAINS,target);return target
    def test_full_raw_faces_and_exact_naga_dependency(self):
        data=load_batch();self.assertEqual(canonical_digest(data),BATCH_HASH)
        self.assertEqual(len(data['cards']),4)
        for row in data['cards']+data['dependencies']+data['evidence_only']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        n=self.r.card(NAGA);self.assertEqual((n.cost,n.attack,n.health),(3,3,3));self.assertIn(Keyword.TAUNT,n.keywords)
        self.assertIn('naga',tuple(t.lower()for t in n.metadata.tribes));self.assertFalse(n.metadata.collectible)
        self.assertNotIn('DINO_405e',self.r.cards)
    def test_old_definitions_and_default_fingerprint_unchanged(self):
        before=json.loads((Path(__file__).resolve().parents[1]/'outputs/card-integration-20261014/k70-before/definition-digests.json').read_text(encoding='utf-8'))
        from dataclasses import asdict
        self.assertEqual(len(before),1003)
        self.assertEqual(before,historical_definition_digests(self.r,before))
        self.assertEqual(representative().fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)
    def test_daze_blocks_next_owner_turn_then_releases_on_following_start(self):
        g=self.game((DAZE,),enemy=(YETI,));target=g.state.players[2].board[0];self.play(g,DAZE,target)
        e=g.state.entities[target];self.assertEqual((e.zone,e.controller),(Zone.HAND,2))
        lock=next(e.hand_play_lock for e in e.enchantments if e.hand_play_lock)
        self.assertEqual((lock.deadline.player_id,lock.deadline.owner_turn_index),(2,2))
        self.end(g);saved=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(PlayCard(2,target))
        self.assertEqual(g.snapshot(),saved);self.end(g);self.end(g)
        g.apply(PlayCard(2,target));self.assertEqual(g.state.entities[target].zone,Zone.BOARD);self.portable(g)
    def test_daze_does_not_lock_other_same_name_hand_card(self):
        g=self.game((DAZE,),enemy=(YETI,),enemy_hand=(YETI,));old=self.entities(g,YETI,2,'hand')[0].id;target=self.entities(g,YETI,2)[0].id
        self.play(g,DAZE,target);self.end(g);g.apply(PlayCard(2,old));self.assertEqual(g.state.entities[old].zone,Zone.BOARD)
        with self.assertRaises(IllegalAction):g.apply(PlayCard(2,target))
    def test_daze_uses_original_owner_after_prior_permanent_control(self):
        g=self.game(('k70.give',DAZE),board=(YETI,));target=self.entities(g,YETI)[0].id
        self.play(g,'k70.give',target);self.play(g,DAZE,target);e=g.state.entities[target]
        self.assertEqual((e.owner,e.controller,e.zone),(1,1,Zone.HAND))
        self.assertEqual(next(x.hand_play_lock.deadline.player_id for x in e.enchantments if x.hand_play_lock),1)
        self.portable(g)
    def test_daze_full_hand_uses_original_death_without_false_lock(self):
        g=self.game((DAZE,),enemy=(YETI,),enemy_hand=(YETI,)*10);target=g.state.players[2].board[0]
        self.play(g,DAZE,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertFalse(any(e.hand_play_lock for e in g.state.entities[target].enchantments));self.assertEqual(len(g.state.death_history),1)
        self.portable(g)
    def test_daze_observer_sees_lock_and_waiting_restores_and_replays(self):
        g,target=self.waiting_return();other=self.portable(g);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[self.hero(g)].armor,1)
        self.assertTrue(any(e.hand_play_lock for e in g.state.entities[target].enchantments))
    def test_daze_manual_gate_does_not_block_effect_summon_and_reset_clears_lock(self):
        g,target=self.waiting_return();self.choose(g,'summon');self.assertEqual(g.state.entities[target].zone,Zone.BOARD)
        # The existing hand gate is inert outside hand. A fresh ordinary return
        # resets the old acquisition instead of rearming its previous clock.
        self.end(g);self.play(g,'k70.bounce',target,p=2)
        self.assertEqual(g.state.entities[target].zone,Zone.HAND)
        self.assertFalse(any(e.hand_play_lock for e in g.state.entities[target].enchantments))
        self.portable(g)
    def test_return_choice_exception_keeps_original_waiting_state(self):
        g,_=self.waiting_return();saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
    def test_daze_skipped_slot_does_not_advance_owner_lock(self):
        g=self.game((DAZE,'k70.skip'),enemy=(YETI,));target=g.state.players[2].board[0]
        self.play(g,DAZE,target);self.play(g,'k70.skip');self.end(g);self.assertEqual(g.state.active_player,1)
        self.end(g);self.assertEqual(g.state.active_player,2)
        with self.assertRaises(IllegalAction):g.apply(PlayCard(2,target))
        self.end(g);self.end(g);g.apply(PlayCard(2,target));self.portable(g)
    def test_daze_saved_clock_cannot_be_retimed_or_malformed(self):
        g,target=self.waiting_return();saved=g.snapshot()
        for mode in('index','origin','boundary','missing'):
            bad=deepcopy(saved);entity=bad['state']['entities'][str(target)]
            enchant=next(e for e in entity['enchantments']if e['hand_play_lock'])
            if mode=='missing':del enchant['hand_play_lock']
            else:
                clock=enchant['hand_play_lock']['deadline']
                if mode=='index':clock['owner_turn_index']+=1
                elif mode=='origin':clock['created_owner_turn_id']=999
                else:clock['boundary']='turn_ended'
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())
    def test_chains_installs_control_and_attack_gate_before_reactions(self):
        g=self.game((CHAINS,),board=('k70.watch.controlled',),enemy=('k70.charge',));target=self.steal(g)
        self.assertEqual(g.state.entities[self.hero(g)].armor,1)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,target,self.hero(g,2)))
        marker=self.marker(g,target);self.assertIsNone(marker.expires_turn)
        self.assertEqual((marker.control_return_player_id,marker.control_return_expiry.boundary),(2,'turn_ended'))
        self.portable(g)
    def test_chains_survives_own_end_and_returns_at_original_opponent_end(self):
        g=self.game((CHAINS,),enemy=(YETI,));target=self.steal(g);self.end(g)
        self.assertEqual(g.state.entities[target].controller,1)
        self.assertFalse(any(a.attack_policy for a in g.state.entities[target].abilities))
        self.portable(g);self.end(g);self.assertEqual(g.state.entities[target].controller,2);self.portable(g)
    def test_chains_extra_owner_turns_do_not_return_early_or_keep_attack_gate(self):
        g=self.game((CHAINS,'k70.extra'),enemy=('k70.charge',));target=self.steal(g);self.play(g,'k70.extra');self.end(g)
        self.assertEqual((g.state.active_player,g.state.entities[target].controller),(1,1))
        g.apply(Attack(1,target,self.hero(g,2)));self.end(g);self.assertEqual(g.state.active_player,1)
        self.end(g);self.assertEqual(g.state.active_player,2);self.assertEqual(g.state.entities[target].controller,1)
        self.end(g);self.assertEqual(g.state.entities[target].controller,2);self.portable(g)
    def test_chains_skipped_opponent_slot_is_not_an_end(self):
        g=self.game((CHAINS,'k70.skip'),enemy=(YETI,));target=self.steal(g);self.play(g,'k70.skip');self.end(g)
        self.assertEqual(g.state.active_player,1);self.assertEqual(g.state.entities[target].controller,1)
        self.end(g);self.assertEqual(g.state.entities[target].controller,1);self.end(g)
        self.assertEqual(g.state.entities[target].controller,2);self.portable(g)
    def test_chains_silence_returns_original_and_transform_discards_return(self):
        for operation in('silence','face'):
            with self.subTest(operation=operation):
                g=self.game((CHAINS,'k70.'+operation),enemy=(YETI,));target=self.steal(g);self.play(g,'k70.'+operation,target)
                self.assertEqual(g.state.entities[target].controller,2 if operation=='silence'else 1)
                self.assertFalse(any(e.control_return_player_id for e in g.state.entities[target].enchantments));self.portable(g)
    def test_chains_manual_marker_removal_uses_existing_return_path(self):
        g=self.game((CHAINS,'k70.remove'),enemy=(YETI,));target=self.steal(g);self.play(g,'k70.remove',target)
        self.assertEqual(g.state.entities[target].controller,2)
    def test_chains_current_copy_does_not_copy_physical_return_obligation(self):
        g=self.game((CHAINS,'k70.copy'),enemy=(YETI,));target=self.steal(g);self.play(g,'k70.copy',target)
        copied=next(e for e in self.entities(g,YETI)if e.id!=target);self.assertFalse(any(e.control_return_player_id for e in copied.enchantments))
        self.end(g);self.end(g);self.assertEqual(g.state.entities[target].controller,2);self.assertEqual(g.state.entities[copied.id].controller,1)
        self.portable(g)
    def test_chains_bounce_drops_return_without_reacquiring_later_residence(self):
        g=self.game((CHAINS,'k70.bounce'),enemy=(YETI,));target=self.steal(g);self.play(g,'k70.bounce',target)
        g.apply(PlayCard(1,target));self.end(g);self.end(g);self.assertEqual(g.state.entities[target].controller,1)
        self.portable(g)
    def test_chains_full_destination_rejected_before_payment(self):
        g=self.game((CHAINS,),board=(YETI,)*7,enemy=(YETI,));saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.steal(g)
        self.assertEqual(g.snapshot(),saved)
    def test_chains_full_return_board_uses_existing_death_and_controller(self):
        g=self.game((CHAINS,),enemy=(YETI,)*7,enemy_hand=(YETI,));target=self.steal(g);self.end(g);self.play(g,YETI,p=2);self.end(g)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.death_history[-1].controller,1);self.portable(g)
    def test_chains_end_choice_retains_original_clock_then_returns_once(self):
        g=self.game((CHAINS,),board=('k70.watch.ending',),enemy=(YETI,));target=self.steal(g);self.end(g);self.end(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.entities[target].controller,1)
        other=self.portable(g);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(g.state.entities[target].controller,2)
    def test_chains_end_choice_failure_rolls_back_to_same_waiting_boundary(self):
        g=self.game((CHAINS,),board=('k70.watch.ending',),enemy=(YETI,));self.steal(g);self.end(g);self.end(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
    def test_chains_dormant_resident_still_returns(self):
        g=self.game((CHAINS,'k70.sleep'),enemy=(YETI,));target=self.steal(g);self.play(g,'k70.sleep',target)
        self.end(g);self.end(g);self.assertEqual(g.state.entities[target].controller,2);self.portable(g)
    def test_chains_overlap_stays_explicitly_unsupported_and_rolls_back(self):
        g=self.game((CHAINS,),enemy=(YETI,),enemy_hand=(CHAINS,));target=self.steal(g);self.end(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Overlapping temporary control'):self.play(g,CHAINS,target,p=2)
        self.assertEqual(g.snapshot(),saved)
    def test_chains_saved_original_clock_rejects_future_wrong_player_or_mixed_deadline(self):
        g=self.game((CHAINS,),enemy=(YETI,));target=self.steal(g);saved=g.snapshot()
        for mode in('index','player','boundary','mixed','missing'):
            bad=deepcopy(saved);e=bad['state']['entities'][str(target)]
            marker=next(a for a in e['enchantments']if a['control_return_player_id'] is not None)
            if mode=='missing':del marker['control_return_expiry']
            elif mode=='mixed':marker['expires_turn']=1
            elif mode=='player':marker['control_return_expiry']['player_id']=1
            elif mode=='boundary':marker['control_return_expiry']['boundary']='turn_started'
            else:marker['control_return_expiry']['owner_turn_index']=9
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())
    def test_late_exception_rolls_back_return_lock_and_control_installation(self):
        for operation in('fault_return','fault_control'):
            g=self.game(('k70.'+operation,),enemy=(YETI,));saved=g.snapshot()
            with self.subTest(operation=operation),self.assertRaises(ResolutionError):self.play(g,'k70.'+operation,g.state.players[2].board[0])
            self.assertEqual(g.snapshot(),saved)
    def test_ceremony_counts_current_and_next_own_end_only(self):
        g=self.game((CEREMONY,),board=(YETI,));target=self.entities(g,YETI)[0].id;self.play(g,CEREMONY)
        self.assertEqual(g.state.players[1].player_effects[0].remaining_turns,2);self.end(g)
        self.assertEqual(g.state.entities[target].attack,4);self.assertEqual(g.state.players[1].player_effects[0].remaining_turns,1)
        self.end(g);self.assertEqual(g.state.entities[target].attack,4);self.end(g)
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(6,7));self.assertFalse(g.state.players[1].player_effects);self.portable(g)
    def test_ceremony_offturn_auto_install_uses_next_real_own_end(self):
        g=self.game(('k70.auto_ceremony',),enemy=(YETI,));target=g.state.players[2].board[0];self.play(g,'k70.auto_ceremony')
        self.assertEqual(g.state.players[2].player_effects[0].remaining_turns,1)
        self.end(g);self.assertEqual(g.state.entities[target].attack,4);self.end(g)
        self.assertEqual(g.state.entities[target].attack,6);self.portable(g)
    def test_ceremony_end_reaction_install_does_not_wait_an_extra_owner_end(self):
        g=self.game(board=(YETI,'k70.watch.late_ceremony'));target=self.entities(g,YETI)[0].id;self.end(g)
        self.assertEqual(g.state.players[1].player_effects[0].remaining_turns,1);self.assertEqual(g.state.entities[target].attack,4)
        self.end(g);self.end(g);self.assertEqual(g.state.entities[target].attack,6);self.portable(g)
    def test_ceremony_uses_then_current_recipients_and_skips_dormant(self):
        g=self.game((CEREMONY,YETI),board=('k70.dormant',),enemy=(YETI,));dormant=self.entities(g,'k70.dormant')[0].id
        self.play(g,CEREMONY);self.end(g);self.end(g);self.play(g,YETI);target=self.entities(g,YETI)[0].id;self.end(g)
        self.assertEqual(g.state.entities[target].attack,6);self.assertEqual(g.state.entities[dormant].attack,2)
        self.assertEqual(self.entities(g,YETI,2)[0].attack,4)
    def test_ceremony_duplicate_instances_and_silenceable_permanent_rewards(self):
        g=self.game((CEREMONY,CEREMONY),board=(YETI,),enemy_hand=('k70.silence',));target=self.entities(g,YETI)[0].id;self.play(g,CEREMONY);self.play(g,CEREMONY)
        self.assertEqual(len(g.state.players[1].player_effects),2);self.end(g);self.end(g);self.end(g)
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(8,9));self.play(g,'k70.silence',target,p=2)
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(4,5));self.portable(g)
    def test_ceremony_extra_owner_turn_is_the_next_turn(self):
        g=self.game((CEREMONY,'k70.extra'),board=(YETI,));target=self.entities(g,YETI)[0].id
        self.play(g,CEREMONY);self.play(g,'k70.extra');self.end(g);self.assertEqual(g.state.active_player,1)
        self.end(g);self.assertEqual(g.state.entities[target].attack,6);self.portable(g)
    def test_timed_objectives_and_sigils_share_capacity_before_payment(self):
        g=self.game((SEAS,)*6)
        for _ in range(5):self.play(g,SEAS)
        saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,SEAS)
        self.assertEqual(g.snapshot(),saved);self.portable(g)
    def test_seas_summons_exact_taunt_naga_at_next_owner_start_before_draw(self):
        g=self.game((SEAS,));source=self.play(g,SEAS);self.end(g);self.assertFalse(self.entities(g,NAGA));self.end(g)
        n=self.entities(g,NAGA)[0];self.assertEqual((n.attack,n.health),(3,3));self.assertIn(Keyword.TAUNT,n.keywords)
        events=[e for e in g.events if e.action==g.state.action_number and e.player_id==1]
        self.assertLess(next(e.sequence for e in events if e.kind=='minion_summoned'),next(e.sequence for e in events if e.kind=='card_drawn'))
        self.assertEqual(g.state.card_summon_history[-1].request.cause.source.entity_id,source);self.portable(g)
    def test_seas_duplicate_instances_are_independent(self):
        g=self.game((SEAS,SEAS));self.play(g,SEAS);self.play(g,SEAS);self.end(g);self.end(g)
        self.assertEqual(len(self.entities(g,NAGA)),2);self.assertFalse(g.state.players[1].player_effects);self.portable(g)
    def test_seas_shared_actual_summon_quantity_still_applies(self):
        g=self.game((SEAS,),board=('CORE_DAL_575',));self.play(g,SEAS);self.end(g);self.end(g)
        self.assertEqual(len(self.entities(g,NAGA)),2);self.portable(g)
    def test_seas_full_board_consumes_sigil_without_fake_naga(self):
        g=self.game((SEAS,),board=(YETI,)*7);self.play(g,SEAS);self.end(g);self.end(g)
        self.assertFalse(self.entities(g,NAGA));self.assertFalse(g.state.players[1].player_effects);self.portable(g)
    def test_seas_offturn_auto_install_still_fires_at_first_owner_start(self):
        g=self.game(('k70.auto_seas',));self.play(g,'k70.auto_seas');self.end(g)
        self.assertEqual(len(self.entities(g,NAGA,2)),1);self.portable(g)
    def test_private_clocks_and_original_references_do_not_leak_to_player(self):
        g,target=self.waiting_return();view=json.dumps(g.observe(1),ensure_ascii=False)
        for key in('hand_play_lock','control_return_expiry','created_owner_turn_id','resolution_frame','rng_state'):
            self.assertNotIn(key,view)
    def test_public_added_countdown_accepts_next_end_policy_without_weakening_ordinary_sigil(self):
        from hs_sim.engine.information import validate_player_effect_view
        for remaining in(1,2):
            validate_player_effect_view(dict(effect_key=PREFIX+'ceremony',card_id=CEREMONY,effect_kind='objective',remaining_turns=remaining),self.r,'player_effect_added')
        for key,cid,kind,remaining in(('ceremony',CEREMONY,'objective',0),('ceremony',CEREMONY,'objective',3),('seas',SEAS,'sigil',2)):
            with self.subTest(remaining=remaining),self.assertRaises(ValueError):
                validate_player_effect_view(dict(effect_key=PREFIX+key,card_id=cid,effect_kind=kind,remaining_turns=remaining),self.r,'player_effect_added')
    def test_new_public_flags_and_clock_declarations_reject_wrong_shapes(self):
        for constructor in(
            lambda:ReturnToHand(1,lock_next_owner_turn=1),lambda:ReturnToHand(1,lock_next_owner_turn=True),
            lambda:ChangeControl(1,2,True,3,True),lambda:ChangeControl(1,2,cannot_attack_this_turn=True),
            lambda:ChangeControl(1,2,source_id=3,until_previous_controller_turn_end=1),
            lambda:PlayerEffectSpec('bad',CEREMONY,next_turn_end=True),
            lambda:PlayerEffectSpec('bad',CEREMONY,kind='objective',duration=1,tick_event='turn_ended',next_turn_end=True),
            lambda:PlayerEffectSpec('bad',CEREMONY,next_turn_end=1),
            lambda:Enchantment(1,source_id=2,label='temporary_control',control_return_player_id=2,
                control_return_expiry=OwnerTurnExpiry(1,1,1,'turn_ended',1))):
            with self.subTest(constructor=constructor),self.assertRaises(ValueError):constructor()
    def test_previous_schema_is_rejected_and_current_default_restores(self):
        root=Path(__file__).resolve().parents[1]
        for label in('constructed-v78','default-v65'):
            old=json.loads((root/f'outputs/card-integration-20261014/k70-before/{label}-core364-schema289.json').read_text(encoding='utf-8'))
            with self.subTest(label=label),self.assertRaises(SnapshotError):Game.from_snapshot(old,build_registry()if label.startswith('constructed')else representative())
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08'),PlayerSetup('HERO_08'))),representative())
        self.assertGreater(SNAPSHOT_SCHEMA_VERSION,289);self.assertEqual(Game.from_snapshot(g.snapshot(),representative()).snapshot(),g.snapshot())


if __name__=='__main__':unittest.main()
