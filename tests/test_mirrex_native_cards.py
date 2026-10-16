"""Mirrex retains an original HAND source over actual public played faces."""
from dataclasses import asdict,replace
import json,unittest
from types import SimpleNamespace
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import reviewed_definition_digest
from hs_sim.cards.mirrex_native_cards import load_batch
from hs_sim.engine import (AbilityInstance,CardClass,CardDefinition,CardMetadata,CardType,
    ChooseBranch,ChooseOneSpec,EndTurn,Game,HandMirrorSpec,Keyword,PlayCard,PlayerSetup,
    Scenario,SelectChoice,TriggerSpec,Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,Destroy,Draw,GainArmor,
    InvokeBehavior,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.errors import IllegalAction,ResolutionError,SnapshotError
from hs_sim.engine.hand_mirrors import latest,source,validate_entity,validate_game
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec,HandMirrorBinding
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard
from hs_sim.targets import canonical_digest

MIRROR='DINO_407';PLAIN='CORE_CS2_182';TARGET='k56.target';OTHER='k56.other'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=(),factions=(),subtypes=())


def carrier(c):
    return next(c.state.entities[i]for i in c.state.players[c.player_id].hand if source(c.state.entities[i])is not None)


def registry(mode=None):
    r=build_registry()
    scripts=dict(bc=lambda c:(GainArmor(c.player_id,2),),dr=lambda c:(GainArmor(c.player_id,3),),noop=lambda c:(),
        create=lambda c:(AddToHand(c.player_id,MIRROR,c.source_id),),draw=lambda c:(Draw(c.player_id,source_id=c.source_id),),
        current=lambda c:(CopyCard(CardReference.capture(carrier(c)),c.player_id,mode='current'),),
        base=lambda c:(CopyCard(CardReference.capture(carrier(c)),c.player_id,mode='base'),),
        cross_copy=lambda c:(CopyCard(CardReference.capture(carrier(c)),3-c.player_id,mode='current'),),
        copy_deck=lambda c:(CopyCard(CardReference.capture(carrier(c)),c.player_id,destination=Zone.DECK,mode='current',position='top'),),
        transfer=lambda c:(MoveCard(CardReference.capture(carrier(c)),3-c.player_id,Zone.HAND,source_id=c.source_id),),
        external=lambda c:(TransformStoredCard(CardReference.capture(carrier(c)),PLAIN,c.source_id),),
        into_mirror=lambda c:(TransformStoredCard(CardReference.capture(next(c.state.entities[i]for i in c.state.players[c.player_id].hand
            if c.state.entities[i].kind==CardType.MINION)),MIRROR,c.source_id),),
        shuffle=lambda c:(MoveCard(CardReference.capture(carrier(c)),c.player_id,Zone.DECK,position='top',source_id=c.source_id),),
        buff=lambda c:(BuffStoredCard(CardReference.capture(carrier(c)),2,2,c.source_id),),
        cost=lambda c:(BuffStoredCard(CardReference.capture(carrier(c)),source_id=c.source_id,cost=CostSpec(delta=-2)),),
        bounce=lambda c:(ReturnToHand(c.target_id),),silence=lambda c:(Silence(c.target_id),),
        change=lambda c:(Transform(c.target_id,OTHER),),kill=lambda c:(Destroy(c.target_id,c.source_id),),
        copy_board=lambda c:(CopyCard(MinionReference.capture(next(c.state.entities[i]for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id==MIRROR)),c.player_id,mode='current'),),
        summon=lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(TARGET),),SummonCause.capture(c)),),
        fail=lambda c:(AddToHand(c.player_id,'missing.k56',c.source_id),),
        return_self=lambda c:(ReturnToHand(c.source_id),),die=lambda c:(Destroy(c.source_id,c.source_id),))
    for key,body in scripts.items():
        r.register_behavior('k56.'+key,body)
        if key not in('bc','dr','fail','return_self','die'):
            r.register_card(CardDefinition('k56.'+key,key,CardType.SPELL,on_play='k56.'+key,metadata=META,
                requires_target=key in('bounce','silence','change','kill')))
    r.register_card(CardDefinition(TARGET,'Complete printed target',CardType.MINION,cost=7,attack=6,health=9,
        keywords=(Keyword.TAUNT,),battlecry='k56.bc',deathrattle='k56.dr',metadata=META))
    r.register_card(CardDefinition(OTHER,'Another printed target',CardType.MINION,cost=2,attack=1,health=2,metadata=META))
    r.register_card(CardDefinition('k56.return','Leaves during Battlecry',CardType.MINION,cost=4,attack=4,health=4,battlecry='k56.return_self',metadata=META))
    r.register_card(CardDefinition('k56.die','Dies during Battlecry',CardType.MINION,cost=2,attack=1,health=1,battlecry='k56.die',metadata=META))
    spec=ChooseOneSpec((ChooseBranch('a','Armor','k56.bc'),ChooseBranch('b','Nothing','k56.noop')),ChooseBranch('both','Both','k56.bc'))
    r.register_card(CardDefinition('k56.choice','Ordinary Choose One minion',CardType.MINION,cost=2,attack=2,health=5,choose_one=spec,metadata=META))
    if mode:
        def watch(c):
            event=c.event
            if event.kind=='stored_card_transformed':
                if source(c.state.entities[event.target_id])is None:return ()
                if mode=='batch':
                    target=c.state.entities[event.target_id].card_id
                    if any(source(c.state.entities[i])is not None and c.state.entities[i].card_id!=target for i in c.state.players[1].hand):
                        raise ResolutionError('Mirror notification captured an incompletely installed batch')
                    return ()
            elif event.player_id!=2 or c.state.entities[event.source_id].kind!=CardType.MINION:return ()
            if mode=='late_create':return(AddToHand(1,MIRROR,c.source_id),)
            if mode=='fault':return(AddToHand(c.player_id,'missing.k56',c.source_id),)
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,0),)),
                ChoiceOption('bad','Rollback',(InvokeBehavior('k56.fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior('k56.watch',watch)
        r.register_card(CardDefinition('k56.watch','Publication observer',CardType.MINION,health=8,metadata=META,
            triggers=(TriggerSpec('stored_card_transformed'if mode in('mirror_wait','batch')else'card_played'if mode=='fault'else'card_committed','k56.watch'),)))
    return r


class MirrexNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(MIRROR,),*,other=(TARGET,),board=(),enemy=(),deck=None,active=2,mode=None,mana=60,enemy_mana=60):
        return Game.from_scenario(Scenario((PlayerSetup('test.hero',hand=hand,board=board,deck=(PLAIN,)*8 if deck is None else deck,
            mana=mana,max_mana=60,mana_cap=60),PlayerSetup('test.hero',hand=other,board=enemy,deck=(PLAIN,)*8,
            mana=enemy_mana,max_mana=60,mana_cap=60)),active_player=active,seed=1056),registry(mode)if mode else self.r)
    def entity(self,g,cid,p=1,zone='hand'):
        s=g.state;return next(s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def mirrors(self,g,p=1):
        s=g.state;return[s.entities[i]for i in s.players[p].hand if source(s.entities[i])is not None]
    def mirror(self,g,p=1):return self.mirrors(g,p)[0]
    def play(self,g,cid,target=None,p=1,branch=None):
        i=self.entity(g,cid,p).id;g.apply(PlayCard(p,i,target,branch_id=branch));return i
    def opponent(self,g,cid=TARGET):return self.play(g,cid,p=2)
    def to_own(self,g):g.apply(EndTurn(2))
    def to_opponent(self,g):g.apply(EndTurn(1))
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode=None):
        saved=g.snapshot();other=Game.from_snapshot(saved,registry(mode));self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved);return other
    def test_complete_printed_face_and_two_distinct_enchantment_rows(self):
        data=load_batch();raw=data['cards'][0]['record'];self.assertEqual(canonical_digest(raw),data['cards'][0]['record_sha256'])
        self.assertEqual((self.r.card(MIRROR).cost,self.r.card(MIRROR).attack,self.r.card(MIRROR).health),(3,3,4))
        self.assertEqual([x['record']['id']for x in data['enchantment_evidence']],['DINO_407e','DINO_407e2']);self.assertEqual(self.r.hand_mirror_ids,frozenset((MIRROR,)))
    def test_no_opponent_minion_keeps_original_printed_face_without_rng(self):
        g=self.game(other=());e=self.mirror(g);self.assertEqual((e.card_id,e.attack,e.health,e.base_cost),(MIRROR,3,4,3));self.assertIsNone(source(e).hand_mirror.play_id);self.portable(g)
    def test_opponent_public_commit_immediately_installs_complete_three_four_face(self):
        g=self.game();original=self.mirror(g).id;before=g.snapshot()['rng_state'];self.opponent(g);e=self.mirror(g)
        self.assertEqual((e.id,e.card_id,e.attack,e.health,e.base_cost),(original,TARGET,3,4,7));self.assertIn(Keyword.TAUNT,e.keywords)
        self.assertEqual(source(e).hand_mirror.play_id,1);self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)
    def test_latest_source_returning_during_battlecry_does_not_lose_the_frozen_face(self):
        g=self.game(other=('k56.return',));original=self.opponent(g,'k56.return');self.assertEqual(g.state.entities[original].zone,Zone.HAND)
        self.assertEqual((self.mirror(g).card_id,self.mirror(g).attack,self.mirror(g).health),('k56.return',3,4));self.portable(g)
    def test_latest_source_dying_during_battlecry_is_still_the_played_minion(self):
        g=self.game(other=('k56.die',));original=self.opponent(g,'k56.die');self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD)
        self.assertEqual(self.mirror(g).card_id,'k56.die');self.portable(g)
    def test_later_board_transformation_does_not_rewrite_played_identity(self):
        g=self.game(other=(TARGET,'k56.change'));original=self.opponent(g);self.play(g,'k56.change',original,p=2)
        self.assertEqual(g.state.entities[original].card_id,OTHER);self.assertEqual(self.mirror(g).card_id,TARGET);self.assertIn(Keyword.TAUNT,self.mirror(g).keywords)
    def test_own_minion_and_opponent_spell_are_not_opponent_minion_plays(self):
        g=self.game((MIRROR,PLAIN),other=('k56.noop',),active=1);self.play(g,PLAIN);self.to_opponent(g);self.play(g,'k56.noop',p=2)
        self.assertEqual(self.mirror(g).card_id,MIRROR);self.assertIsNone(source(self.mirror(g)).hand_mirror.play_id)
    def test_direct_summon_does_not_count_as_a_paid_minion_play(self):
        g=self.game(other=('k56.summon',));self.play(g,'k56.summon',p=2);self.assertEqual(self.mirror(g).card_id,MIRROR)
    def test_unaffordable_opponent_play_cannot_change_mirror_or_private_history(self):
        g=self.game(enemy_mana=0);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.opponent(g)
        self.assertEqual(g.snapshot(),before)
    def test_query_requires_public_commit_even_if_a_detached_play_record_exists(self):
        g=self.game();self.opponent(g);domain=SimpleNamespace(_state=g.state,_events=[e for e in g.events if e.kind!='card_committed'])
        self.assertIsNone(latest(domain,1));self.assertEqual(latest(g,1).card_id,TARGET)
    def test_new_same_name_play_resets_hand_buffs_cost_and_epoch_once(self):
        g=self.game((MIRROR,'k56.buff','k56.cost'),other=(TARGET,TARGET));self.opponent(g);self.to_own(g);self.play(g,'k56.buff');self.play(g,'k56.cost')
        old=self.mirror(g);self.assertEqual((old.attack,old.health,quote_cost(g.state,g.registry,old).amount),(5,6,5));original_source=source(old).id
        self.to_opponent(g);self.opponent(g);e=self.mirror(g);self.assertEqual((e.attack,e.health,e.base_cost),(3,4,7));self.assertGreater(e.zone_epoch,old.zone_epoch)
        self.assertEqual(source(e).id,original_source);self.portable(g)
    def test_irrelevant_spell_publications_do_not_reset_later_hand_buffs(self):
        g=self.game((MIRROR,'k56.buff'),other=(TARGET,'k56.noop'));self.opponent(g);self.to_own(g);self.play(g,'k56.buff');self.to_opponent(g);self.play(g,'k56.noop',p=2)
        self.assertEqual((self.mirror(g).attack,self.mirror(g).health),(5,6));self.portable(g)
    def test_late_generation_synchronizes_to_already_completed_history(self):
        g=self.game(('k56.create',));self.opponent(g);self.to_own(g);self.play(g,'k56.create');self.assertEqual(self.mirror(g).card_id,TARGET);self.portable(g)
    def test_natural_draw_synchronizes_original_deck_entity_on_hand_entry(self):
        g=self.game((),deck=(MIRROR,PLAIN));original=g.state.players[1].deck[0];self.opponent(g);self.to_own(g)
        self.assertEqual((self.mirror(g).id,self.mirror(g).card_id),(original,TARGET));self.portable(g)
    def test_scripted_draw_uses_the_same_entry_without_a_fake_play(self):
        g=self.game(('k56.draw',),deck=(PLAIN,MIRROR));self.opponent(g);self.to_own(g);self.play(g,'k56.draw')
        self.assertEqual(self.mirror(g).card_id,TARGET);self.assertEqual(sum(p.kind==CardType.MINION for p in g.state.play_history),1);self.portable(g)
    def test_acquired_during_opponent_committed_window_uses_that_inflight_face(self):
        mode='late_create';g=self.game((),board=('k56.watch',),mode=mode);self.opponent(g)
        self.assertEqual(self.mirror(g).card_id,TARGET);self.assertEqual(source(self.mirror(g)).hand_mirror.play_id,1);self.portable(g,mode)
    def test_multiple_physical_mirrors_keep_independent_native_identities(self):
        g=self.game((MIRROR,MIRROR));self.opponent(g);rows=self.mirrors(g);self.assertEqual(len(rows),2)
        self.assertEqual(len({source(e).id for e in rows}),2);self.assertTrue(all(source(e).source_id==e.id and e.card_id==TARGET for e in rows));self.portable(g)
    def test_first_transformation_observer_captures_all_mirrors_fully_installed(self):
        mode='batch';g=self.game((MIRROR,MIRROR),board=('k56.watch',),mode=mode);self.opponent(g)
        self.assertEqual([e.card_id for e in self.mirrors(g)],[TARGET,TARGET]);self.portable(g,mode)
    def test_current_hand_copy_preserves_buff_and_rebinds_native_source(self):
        g=self.game((MIRROR,'k56.buff','k56.current'),other=(TARGET,OTHER));self.opponent(g);self.to_own(g);self.play(g,'k56.buff');self.play(g,'k56.current')
        rows=self.mirrors(g);self.assertEqual([(e.attack,e.health)for e in rows],[(5,6),(5,6)]);self.assertEqual(len({source(e).id for e in rows}),2)
        self.assertTrue(all(source(e).source_id==e.id for e in rows));self.to_opponent(g);self.opponent(g,OTHER)
        self.assertEqual([(e.card_id,e.attack,e.health)for e in self.mirrors(g)],[(OTHER,3,4)]*2);self.portable(g)
    def test_base_copy_uses_current_printed_face_without_origin_or_stat_overlay(self):
        g=self.game((MIRROR,'k56.base'),other=(TARGET,OTHER));self.opponent(g);self.to_own(g);self.play(g,'k56.base');s=g.state
        plain=next(s.entities[i]for i in s.players[1].hand if s.entities[i].card_id==TARGET and source(s.entities[i])is None)
        self.assertEqual((plain.attack,plain.health),(6,9));self.to_opponent(g);self.opponent(g,OTHER);self.assertEqual(g.state.entities[plain.id].card_id,TARGET);self.portable(g)
    def test_current_copy_to_other_hand_resynchronizes_for_new_controller(self):
        g=self.game((MIRROR,PLAIN,'k56.cross_copy'));self.opponent(g);self.to_own(g);self.play(g,PLAIN);self.play(g,'k56.cross_copy')
        e=self.mirror(g,2);self.assertEqual((e.controller,e.card_id,e.attack,e.health),(2,PLAIN,3,4));self.assertEqual(self.mirror(g).card_id,TARGET);self.portable(g)
    def test_hand_transfer_keeps_physical_owner_origin_and_uses_new_opponent_history(self):
        g=self.game((MIRROR,PLAIN,'k56.transfer'));original=self.mirror(g).id;self.opponent(g);self.to_own(g);self.play(g,PLAIN);self.play(g,'k56.transfer')
        e=g.state.entities[original];self.assertEqual((e.id,e.owner,e.controller,e.card_id),(original,1,2,PLAIN));self.assertEqual(source(e).hand_mirror.declaring_card_id,MIRROR);self.portable(g)
    def test_external_stored_replacement_removes_original_mirror_source(self):
        g=self.game((MIRROR,'k56.external'),other=(TARGET,OTHER));original=self.mirror(g).id;self.opponent(g);self.to_own(g);self.play(g,'k56.external')
        self.assertIsNone(source(g.state.entities[original]));self.to_opponent(g);self.opponent(g,OTHER);self.assertEqual(g.state.entities[original].card_id,PLAIN);self.portable(g)
    def test_external_replacement_into_printed_mirrex_installs_and_synchronizes(self):
        g=self.game((PLAIN,'k56.into_mirror'));original=self.entity(g,PLAIN).id;self.opponent(g);self.to_own(g);self.play(g,'k56.into_mirror')
        e=g.state.entities[original];self.assertEqual(e.card_id,TARGET);self.assertEqual(source(e).hand_mirror.declaring_card_id,MIRROR);self.portable(g)
    def test_played_copied_face_pays_its_cost_and_executes_its_battlecry_and_deathrattle(self):
        g=self.game((MIRROR,'k56.kill'));self.opponent(g);self.to_own(g);original=self.mirror(g).id;before=g.state.players[1].mana;self.play(g,TARGET)
        e=g.state.entities[original];self.assertEqual((e.zone,e.attack,e.health),(Zone.BOARD,3,4));self.assertIsNone(source(e));self.assertEqual(g.state.players[1].mana,before-7)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.play(g,'k56.kill',original);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,5);self.portable(g)
    def test_copied_ordinary_choose_one_face_retains_its_legal_branches(self):
        g=self.game(other=('k56.choice',));self.play(g,'k56.choice',p=2,branch='a');self.to_own(g);before=g.state.players[1].mana
        self.assertEqual({a.branch_id for a in g.legal_actions()if isinstance(a,PlayCard)and a.entity_id==self.mirror(g).id},{'a','b'})
        self.play(g,'k56.choice',branch='a');self.assertEqual(g.state.players[1].mana,before-2);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.portable(g)
    def test_bounced_played_copy_is_an_ordinary_printed_face_without_old_origin(self):
        g=self.game((MIRROR,'k56.bounce'),other=(TARGET,OTHER));self.opponent(g);self.to_own(g);original=self.mirror(g).id;self.play(g,TARGET);self.play(g,'k56.bounce',original)
        self.assertIsNone(source(g.state.entities[original]));self.assertEqual((g.state.entities[original].attack,g.state.entities[original].health),(6,9))
        self.to_opponent(g);self.opponent(g,OTHER);self.assertEqual(g.state.entities[original].card_id,TARGET);self.portable(g)
    def test_current_board_copy_of_actual_printed_mirrex_reactivates_on_new_hand_entry(self):
        g=self.game((MIRROR,'k56.copy_board'),other=(TARGET,),active=1);self.play(g,MIRROR);self.play(g,'k56.copy_board');self.assertEqual(len(self.mirrors(g)),1)
        self.to_opponent(g);self.opponent(g);self.assertEqual(self.mirror(g).card_id,TARGET);self.assertEqual(self.entity(g,MIRROR,zone='board').card_id,MIRROR);self.portable(g)
    def test_silenced_current_board_copy_does_not_recreate_removed_text(self):
        g=self.game((MIRROR,'k56.silence','k56.copy_board'),active=1);original=self.play(g,MIRROR);self.play(g,'k56.silence',original);self.play(g,'k56.copy_board')
        e=self.entity(g,MIRROR);self.assertTrue(e.silenced);self.assertIsNone(source(e));self.to_opponent(g);self.opponent(g);self.assertEqual(g.state.entities[e.id].card_id,MIRROR);self.portable(g)
    def test_shuffled_transformed_face_retires_origin_and_returns_as_static_current_copy(self):
        g=self.game((MIRROR,'k56.shuffle','k56.draw'),other=(TARGET,OTHER));original=self.mirror(g).id;self.opponent(g);self.to_own(g);self.play(g,'k56.shuffle');self.play(g,'k56.draw')
        self.assertIsNone(source(g.state.entities[original]));self.assertEqual((g.state.entities[original].card_id,g.state.entities[original].attack),(TARGET,3))
        self.to_opponent(g);self.opponent(g,OTHER);self.assertEqual(g.state.entities[original].card_id,TARGET);self.portable(g)
    def test_shuffled_original_printed_mirrex_reinstalls_conditional_source_on_draw(self):
        g=self.game((MIRROR,'k56.shuffle','k56.draw'),active=1);original=self.mirror(g).id;self.play(g,'k56.shuffle');self.play(g,'k56.draw')
        self.assertEqual(self.mirror(g).id,original);self.to_opponent(g);self.opponent(g);self.assertEqual(self.mirror(g).card_id,TARGET);self.portable(g)
    def test_current_deck_copy_does_not_keep_a_retired_transformed_hand_origin(self):
        g=self.game((MIRROR,'k56.copy_deck','k56.draw'),other=(TARGET,OTHER));self.opponent(g);self.to_own(g);self.play(g,'k56.copy_deck');copy=g.state.players[1].deck[0];self.play(g,'k56.draw')
        self.assertIsNone(source(g.state.entities[copy]));self.to_opponent(g);self.opponent(g,OTHER);self.assertEqual(g.state.entities[copy].card_id,TARGET);self.portable(g)
    def test_current_copy_of_native_full_health_reborn_face_rebinds_self_source(self):
        g=self.game((MIRROR,'k56.current'),other=('CAP_800',));self.opponent(g,'CAP_800');self.to_own(g);self.play(g,'k56.current')
        for e in self.mirrors(g):
            row=next(a for a in e.abilities if a.reborn_policy is not None);self.assertEqual(row.source_id,e.id)
        self.portable(g)
    def test_wait_at_original_commit_restores_complete_native_source(self):
        mode='commit_wait';g=self.game(board=('k56.watch',),mode=mode);self.opponent(g);self.assertEqual(self.mirror(g).card_id,TARGET)
        other=self.portable(g,mode);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.portable(g,mode)
    def test_private_mirror_reaction_wait_resumes_without_duplicate_transform(self):
        mode='mirror_wait';g=self.game(board=('k56.watch',),mode=mode);self.opponent(g);before=self.mirror(g);other=self.portable(g,mode);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.mirror(g).zone_epoch,before.zone_epoch);self.portable(g,mode)
    def test_bad_waiting_choice_preserves_original_mirrored_boundary(self):
        mode='mirror_wait';g=self.game(board=('k56.watch',),mode=mode);self.opponent(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.portable(g,mode)
    def test_failure_after_opponent_play_rolls_back_source_face_payment_and_knowledge(self):
        mode='fault';g=self.game(board=('k56.watch',),mode=mode);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.opponent(g)
        self.assertEqual(g.snapshot(),before)
    def test_quotes_observations_and_legal_queries_cannot_refresh_or_mutate_source(self):
        g=self.game();self.opponent(g);before=g.snapshot()
        for _ in range(3):quote_cost(g.state,g.registry,self.mirror(g));g.for_player(1).observe();g.legal_actions()
        self.assertEqual(g.snapshot(),before)
    def test_typed_source_rejects_borrowed_physical_id_and_origin(self):
        g=self.game();self.opponent(g);e=self.mirror(g);row=source(e)
        for bad in(replace(row,source_id=g.state.players[1].hero_id),replace(row,hand_mirror=replace(row.hand_mirror,declaring_card_id=PLAIN))):
            changed=replace(e,abilities=[bad if a.id==row.id else a for a in e.abilities])
            with self.assertRaises(ValueError):validate_entity(g.state,g.registry,changed)
    def test_latest_public_game_validation_rejects_older_same_card_stamp(self):
        g=self.game(other=(TARGET,TARGET));self.opponent(g);self.opponent(g);s=g.state;e=s.entities[self.mirror(g).id];row=source(e)
        e.abilities=[replace(a,hand_mirror=replace(a.hand_mirror,play_id=1))if a.id==row.id else a for a in e.abilities]
        validate_entity(s,g.registry,e)
        with self.assertRaisesRegex(ValueError,'latest actual public'):validate_game(SimpleNamespace(_state=s,_events=g.events,registry=g.registry))
    def test_malformed_and_dynamic_source_declarations_are_rejected(self):
        for kwargs in(dict(attack=True),dict(attack=-1),dict(health=0)):
            with self.assertRaises(ValueError):HandMirrorSpec(**kwargs)
        with self.assertRaises(ValueError):self.r._validate_card(CardDefinition('bad','bad',CardType.SPELL,hand_mirror=HandMirrorSpec()))
        with self.assertRaises(ValueError):AbilityInstance(1,'hand_mirror',source_id=1,hand_mirror=HandMirrorBinding(MIRROR,1))
    def test_snapshot_does_not_silently_repair_a_missing_original_binding(self):
        g=self.game(other=());saved=g.snapshot();row=saved['state']['entities'][str(self.mirror(g).id)]
        row['abilities']=[a for a in row['abilities']if a['kind']!='hand_mirror']
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())
    def test_nonempty_native_declaration_is_signed_and_null_legacy_pins_remain_exact(self):
        card=self.r.card(MIRROR);self.assertNotEqual(reviewed_definition_digest(card),reviewed_definition_digest(replace(card,hand_mirror=None)))
        plain=self.r.card(PLAIN);value=asdict(plain);value.pop('reborn_policy');value.pop('hand_mirror');value.pop('native_condition');value.pop('dormant_board_full');value.pop('native_deathrattle');self.assertEqual(reviewed_definition_digest(plain),canonical_digest(value))
    def test_opponent_observation_and_events_do_not_receive_hidden_source_or_origin(self):
        g=self.game();self.opponent(g);text=json.dumps(g.for_player(2).observe(),ensure_ascii=False)
        for key in(MIRROR,'hand_mirror','declaring_card_id'):self.assertNotIn(key,text)
        self.assertNotIn('stored_card_transformed',json.dumps(g.for_player(2).events()));self.portable(g)


if __name__=='__main__':unittest.main()
