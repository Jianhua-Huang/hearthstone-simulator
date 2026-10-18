"""Real future companion sources and one shared frozen family in all consumers."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards.fixed_companion_cards import (COMPANIONS,COMPANION_FAMILY,
    register_fixed_companion_cards)
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_companion_quantity_cards import TALYA,PROGRAM,register_native_companion_quantity_cards
from hs_sim.cards.native_companion_replacement_cards import (TAME,ELEKK,ROAM,ROOTS,load_batch,
    register_native_companion_replacement_cards)
from hs_sim.cards.simple_followup_p13_cards import SPEAKER,register_simple_followup_p13_cards
from hs_sim.cards.simple_followup_p14_cards import BROLL,register_simple_followup_p14_cards
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,
    Keyword,PlayCard,PlayerSetup,Rarity,Registry,RewindSpec,Scenario,SelectChoice,TargetSpec,Zone)
from hs_sim.engine.effects import (ChoiceOption,Destroy,InvokeBehavior,RandomDamage,RequestChoice,Silence)
from hs_sim.engine.errors import ResolutionError,SnapshotError
from hs_sim.engine.minion_families import (FamilyMember,FamilyReference,SummonFamilyMember,UpgradeMinionFamily,
    capture,members)
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import (GenerationContext,PoolCard,PoolDefinition,PoolMember,
    sample_candidates)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import canonical_digest

P='k192.';HERO=P+'hero';FILL=P+'filler';WATCH=P+'watch'
ANIMAL='CORE_NEW1_031';CALL='CORE_OG_211'
CTX=GenerationContext('k192-complete-fixture','experimental')
BEASTS=tuple(P+name for name in('four_a','four_b','five_a','five_b','six','ten','twelve'))
COSTS=(4,4,5,5,6,10,12)


@lru_cache(maxsize=None)
def registry(mode=None):
    r=Registry('k192-future-companions-'+str(mode))
    register_fixed_companion_cards(r);register_simple_followup_p13_cards(r)
    register_simple_followup_p14_cards(r);register_native_companion_quantity_cards(r)
    register_native_companion_replacement_cards(r)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=80))
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,attack=1,health=20))
    meta=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=('beast',))
    for i,(cid,cost)in enumerate(zip(BEASTS,COSTS)):
        definition=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=i+2,health=i+4,metadata=meta)
        if not(mode=='unknown_four'and cid==BEASTS[1]or mode=='unknown_five'and cid==BEASTS[3]):
            r.register_card(definition)
        r.register_pool_card(PoolCard.from_definition(definition))
    if mode!='missing_pool':
        pool_members=tuple(PoolMember(cid,2 if i==0 else 1)for i,cid in enumerate(BEASTS)
            if not(mode=='empty_four'and COSTS[i]==4))
        r.register_pool(PoolDefinition('constructed.cards','k192-fixture-pool-v1',CTX.target_id,
            CTX.mode,pool_members,complete=True))
    bodies={
        'noop':lambda c:(),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'summon_elekk':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(ELEKK),),SummonCause.capture(c)),),
        'rewind':lambda c:(UpgradeMinionFamily(COMPANION_FAMILY,SummonCause.capture(c),1),),
        'rewind_fail':lambda c:(UpgradeMinionFamily(COMPANION_FAMILY,SummonCause.capture(c),1),
            *((InvokeBehavior(P+'fail',c.source_id,c.player_id),)if c.rewind_attempt>0 else())),
        'fail':lambda c:(_ for _ in()).throw(ResolutionError('K192 deliberate failure')),
    }
    for name,body in bodies.items():
        r.register_behavior(P+name,body)
        if name!='fail':
            kwargs={'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))}if name in('kill','silence')else{}
            if name in('rewind','rewind_fail'):kwargs.update(cost=1,rewind=RewindSpec(1),keywords=(Keyword.REWIND,))
            r.register_card(CardDefinition(P+name,P+name,CardType.SPELL,on_play=P+name,**kwargs))
    if mode in('wait','random','upgrade_reaction','failure','draw_wait'):
        event='card_drawn'if mode=='draw_wait'else'minion_summoned'
        def eligible(c):
            if c.event.player_id!=c.player_id:return False
            if mode=='draw_wait':
                source=c.state.entities.get(c.event.source_id)
                return source is not None and source.card_id==TAME
            return(c.state.entities[c.event.target_id].card_id in BEASTS and
                sum(c.state.entities[i].card_id in BEASTS for i in c.state.players[c.player_id].board)==1)
        def watch(c):
            before=()
            if mode in('random','failure'):before=(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),)
            if mode=='failure':before=(*before,InvokeBehavior(P+'fail',c.source_id,c.player_id))
            if mode=='upgrade_reaction':
                from hs_sim.engine.minion_families import UpgradeMinionFamily
                before=(UpgradeMinionFamily(COMPANION_FAMILY,SummonCause.capture(c),1),)
            return(*before,RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('fail','Rollback',
                (RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(P+'fail',c.source_id,c.player_id)))),c.source_id))
        r.register_trigger_condition(P+'eligible',eligible);r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,
            limited_triggers=(LimitedTriggerSpec(event,P+'watch',condition_id=P+'eligible'),)))
    r.validate();return r


class NativeCompanionReplacementTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),other_hand=(),mode=None,context=CTX):
        self.mode=mode
        if mode in('wait','random','upgrade_reaction','failure','draw_wait'):board=(*board,WATCH)
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO,hand=hand,board=board,deck=(FILL,)*12,mana=100,max_mana=100,mana_cap=100),
            PlayerSetup(HERO,hand=other_hand,board=enemy,deck=(FILL,)*12,mana=100,max_mana=100,mana_cap=100)),
            seed=192,generation_context=context),registry(mode))

    def play(self,g,cid,target=None,p=None):
        p=g.state.active_player if p is None else p
        eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid,target));return eid

    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def family(self,g,p=1):return members(g.state,g.registry,capture(g.state,g.registry,COMPANION_FAMILY,p))

    def board(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].board]

    def random(self,g):
        state=g.snapshot()['rng_state'];rng=Random();rng.setstate((state[0],tuple(state[1]),state[2]));return rng

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));reader=registry.__wrapped__(self.mode)
        self.assertIsNot(reader,g.registry)
        self.assertEqual(Game.from_snapshot(deepcopy(saved),reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for key in('minion_family_history','old_members','rng_state','FamilyReference','SummonFamilyMember','resolution_frame'):
                self.assertNotIn('"'+key+'"',public)

    def rehash(self,saved):
        keys=('ruleset','registry_fingerprint','mechanics_version','state','rng_state','resolution_frame',
            'rewind_session','match_setup','generation_context','information')
        saved['events_hash']=canonical_hash(saved['events'])
        saved['state_hash']=canonical_hash({k:saved[k]for k in keys})
        return saved

    def test_three_complete_sources_six_faces_native_stats_and_printed_taunt(self):
        d=load_batch();self.assertEqual(len(d['official_observations']),6)
        self.assertEqual(len(d['existing_dependencies']),8);self.assertFalse(d['formal_pool_complete']or d['cn_calibrated'])
        for row in d['cards']:
            raw=row['record'];card=registry().card(raw['id'])
            self.assertEqual(canonical_digest(raw),row['record_sha256'])
            self.assertEqual(card.metadata,metadata_from_record(raw));self.assertEqual(card.cost,raw['cost'])
        self.assertEqual((registry().card(ELEKK).cost,registry().card(ELEKK).attack,registry().card(ELEKK).health),(2,2,3))

    def test_tame_replaces_all_three_with_complete_weighted_four_cost_beasts_then_draws(self):
        g=self.game((TAME,));rng=self.random(g);pool=(PoolMember(BEASTS[0],2),PoolMember(BEASTS[1],1))
        expected=[sample_candidates(rng,pool,1,replacement=True)[0]for _ in range(3)]
        source=self.play(g,TAME);self.assertEqual([x.card_id for x in self.family(g)],expected)
        self.assertEqual([x.cost for x in self.family(g)],[4]*3)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[FILL])
        self.assertEqual(g.state.players[1].mana,99);self.assertEqual(len(g.state.cast_history),1)
        root=g.state.minion_family_history[0]
        self.assertEqual(root.request.cause.source.entity_id,source);self.assertEqual(root.members,self.family(g));self.portable(g)

    def test_repeated_upgrade_uses_current_printed_cost_instead_of_original_three(self):
        g=self.game((TAME,TAME));self.play(g,TAME);old=self.family(g);self.play(g,TAME)
        self.assertEqual([x.cost for x in old],[4]*3);self.assertEqual([x.cost for x in self.family(g)],[5]*3)
        rows=g.state.minion_family_history;self.assertEqual(rows[1].old_members,rows[0].members)
        self.assertEqual(rows[1].previous.revision,1);self.portable(g)

    def test_elekk_battlecry_upgrades_without_drawing_and_ordinary_summon_does_not(self):
        g=self.game((ELEKK,P+'summon_elekk'));self.play(g,ELEKK)
        self.assertEqual([x.cost for x in self.family(g)],[4]*3)
        self.assertEqual(len(g.state.players[1].hand),1);self.play(g,P+'summon_elekk')
        self.assertEqual(len(g.state.minion_family_history),1);self.assertEqual(self.board(g),[ELEKK,ELEKK]);self.portable(g)

    def test_replacement_changes_future_materials_and_leaves_existing_companions_unchanged(self):
        g=self.game((TAME,ANIMAL),board=COMPANIONS);old_ids=list(g.state.players[1].board)
        self.play(g,TAME);before=[asdict(g.state.entities[i])for i in old_ids];self.play(g,ANIMAL)
        self.assertEqual(self.board(g)[:3],list(COMPANIONS));self.assertIn(self.board(g)[3],BEASTS[:2])
        self.assertEqual([asdict(g.state.entities[i])for i in old_ids],before);self.portable(g)

    def test_animal_samples_three_roles_without_deduplicating_repeated_faces(self):
        g=self.game((TAME,ANIMAL));self.play(g,TAME);roles=self.family(g);rng=self.random(g)
        expected=roles[rng.randrange(3)].card_id;self.play(g,ANIMAL)
        self.assertEqual(self.board(g),[expected])
        self.assertEqual(g.state.card_summon_history[-1].request.materials,(SummonEntryMaterial(expected),));self.portable(g)

    def test_call_summons_all_three_original_roles_in_order_even_when_faces_repeat(self):
        g=self.game((TAME,CALL));self.play(g,TAME);roles=self.family(g);rng=g.snapshot()['rng_state']
        self.play(g,CALL);self.assertEqual(self.board(g),[x.card_id for x in roles])
        self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

    def test_speaker_offers_exact_current_roles_and_keeps_distinct_role_ids(self):
        g=self.game((TAME,SPEAKER));self.play(g,TAME);roles=self.family(g);self.play(g,SPEAKER)
        q=g.state.pending_choice;self.assertEqual([x.id for x in q.options],list(COMPANIONS))
        self.assertEqual([x.card_id for x in q.options],[x.card_id for x in roles]);self.portable(g)
        self.choose(g,COMPANIONS[2]);self.assertEqual(self.board(g),[SPEAKER,roles[2].card_id]);self.portable(g)

    def test_broll_after_actual_upgrade_cast_uses_new_family(self):
        g=self.game((TAME,),board=(BROLL,));self.play(g,TAME)
        self.assertEqual(self.board(g)[0],BROLL);self.assertIn(self.board(g)[1],BEASTS[:2])
        self.assertEqual(g.state.card_summon_history[-1].request.cause.source.card_id,BROLL);self.portable(g)

    def test_free_roam_upgrades_two_then_has_one_menu_from_the_new_family(self):
        g=self.game((ROAM,));source=self.play(g,ROAM);roles=self.family(g)
        self.assertEqual([x.cost for x in roles],[5]*3)
        self.assertEqual([x.card_id for x in g.state.pending_choice.options],[x.card_id for x in roles])
        self.assertEqual(g.state.players[1].mana,93);self.assertEqual(len(g.state.cast_history),1);self.portable(g)
        self.choose(g,COMPANIONS[0]);self.assertEqual(self.board(g),[roles[0].card_id])
        root=g.state.card_summon_history[-1]
        self.assertEqual((root.request.cause.source.entity_id,root.request.cause.cast_id),(source,g.state.cast_history[0].id));self.portable(g)

    def test_talya_extra_units_share_current_family_and_one_actual_cast(self):
        g=self.game((TALYA,TAME,ANIMAL));self.play(g,TALYA);self.play(g,TAME)
        roles=self.family(g);rng=self.random(g);expected=[roles[rng.randrange(3)].card_id for _ in range(2)]
        self.play(g,ANIMAL);self.assertEqual(self.board(g),[TALYA,*expected])
        self.assertEqual(len(g.state.cast_history),2);self.assertEqual(len(g.state.card_summon_history),2);self.portable(g)

    def test_free_roam_talya_choice_then_independently_random_extra(self):
        g=self.game((TALYA,ROAM));self.play(g,TALYA);self.play(g,ROAM);roles=self.family(g)
        expected=roles[self.random(g).randrange(3)].card_id;self.choose(g,COMPANIONS[1])
        self.assertEqual(self.board(g),[TALYA,roles[1].card_id,expected]);self.portable(g)

    def test_source_death_and_silence_do_not_remove_future_family(self):
        g=self.game((ELEKK,P+'silence',P+'kill',ANIMAL));source=self.play(g,ELEKK)
        self.play(g,P+'silence',source);self.play(g,P+'kill',source);self.play(g,ANIMAL)
        self.assertEqual(len(g.state.minion_family_history),1);self.assertIn(self.board(g)[0],BEASTS[:2]);self.portable(g)

    def test_opponent_has_an_independent_original_family(self):
        g=self.game((TAME,),other_hand=(ANIMAL,TAME));self.play(g,TAME)
        self.assertEqual([x.card_id for x in self.family(g,2)],list(COMPANIONS));g.apply(EndTurn(1))
        self.play(g,ANIMAL);self.assertIn(self.board(g,2)[0],COMPANIONS);self.play(g,TAME)
        self.assertEqual(len(g.state.minion_family_history),2)
        self.assertEqual([x.cost for x in self.family(g,2)],[4]*3);self.portable(g)

    def test_missing_complete_host_pool_fails_atomically_before_rng_or_draw(self):
        g=self.game((TAME,),mode='missing_pool');before=g.snapshot()
        with self.assertRaises(ValueError):self.play(g,TAME)
        self.assertEqual(g.snapshot(),before);self.assertFalse(g.state.minion_family_history)

    def test_unknown_eligible_adapter_is_not_removed_from_pool_and_rolls_back(self):
        g=self.game((TAME,),mode='unknown_four');before=g.snapshot()
        with self.assertRaisesRegex(ValueError,'unsupported card definition'):self.play(g,TAME)
        self.assertEqual(g.snapshot(),before)

    def test_later_unknown_tier_does_not_rewrite_previous_family_or_payment(self):
        g=self.game((TAME,TAME),mode='unknown_five');self.play(g,TAME);before=g.snapshot()
        with self.assertRaisesRegex(ValueError,'unsupported card definition'):self.play(g,TAME)
        self.assertEqual(g.snapshot(),before);self.assertEqual(len(g.state.minion_family_history),1);self.portable(g)

    def test_empty_complete_tier_keeps_three_vacancies_without_upgrade_rng(self):
        g=self.game((TAME,ANIMAL),mode='empty_four');rng=g.snapshot()['rng_state'];self.play(g,TAME)
        self.assertEqual(self.family(g),(FamilyMember(None,4),)*3);self.assertEqual(g.snapshot()['rng_state'],rng)
        expected=self.random(g);expected.randrange(3);self.play(g,ANIMAL)
        self.assertFalse(self.board(g));self.assertFalse(g.state.card_summon_history)
        self.assertEqual(json.loads(json.dumps(expected.getstate())),g.snapshot()['rng_state']);self.portable(g)

    def test_later_upgrade_can_fill_previously_vacant_roles_from_next_tier(self):
        g=self.game((TAME,TAME,ANIMAL),mode='empty_four');self.play(g,TAME);self.play(g,TAME)
        self.assertTrue(all(x.card_id in BEASTS[2:4]and x.cost==5 for x in self.family(g)))
        self.play(g,ANIMAL);self.assertIn(self.board(g)[0],BEASTS[2:4]);self.portable(g)

    def test_full_board_does_not_prevent_future_replacement_but_blocks_summon_rng(self):
        g=self.game((TAME,ANIMAL),board=(FILL,)*7);self.play(g,TAME);rng=g.snapshot()['rng_state']
        self.play(g,ANIMAL);self.assertEqual(self.board(g),[FILL]*7);self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

    def test_draw_reaction_wait_keeps_committed_family_and_restores(self):
        g=self.game((TAME,),mode='draw_wait');self.play(g,TAME)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual([x.cost for x in self.family(g)],[4]*3)
        self.portable(g);self.choose(g);self.portable(g)

    def test_entry_wait_restores_frozen_family_and_unexecuted_talya_tail(self):
        g=self.game((TALYA,TAME,ANIMAL),mode='wait');self.play(g,TALYA);self.play(g,TAME);self.play(g,ANIMAL)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g)
        self.assertEqual(sum(x in BEASTS for x in self.board(g)),2);self.portable(g)

    def test_entry_reaction_rng_is_consumed_before_next_family_role_selection(self):
        g=self.game((TALYA,TAME,ANIMAL),mode='random');self.play(g,TALYA);self.play(g,TAME);self.play(g,ANIMAL)
        roles=self.family(g);expected=roles[self.random(g).randrange(3)].card_id;self.portable(g);self.choose(g)
        self.assertEqual(self.board(g)[-1],expected);self.portable(g)

    def test_accepted_tail_keeps_original_family_after_reaction_upgrades_current_bank(self):
        g=self.game((TALYA,TAME,ANIMAL),mode='upgrade_reaction');self.play(g,TALYA);self.play(g,TAME);old=self.family(g)
        self.play(g,ANIMAL);self.assertEqual([x.cost for x in self.family(g)],[5]*3);self.portable(g)
        self.choose(g);self.assertIn(self.board(g)[-1],{x.card_id for x in old});self.portable(g)

    def test_entry_failure_restores_whole_original_cast_and_family_rng(self):
        g=self.game((TAME,ANIMAL),mode='failure');self.play(g,TAME);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K192 deliberate'):self.play(g,ANIMAL)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_failed_wait_choice_keeps_original_family_and_owed_extra(self):
        g=self.game((TALYA,TAME,ANIMAL),mode='wait');self.play(g,TALYA);self.play(g,TAME);self.play(g,ANIMAL);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K192 deliberate'):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.portable(g);self.choose(g);self.portable(g)

    def test_rehashed_forged_selected_family_or_cropped_pool_is_rejected(self):
        g=self.game((TAME,));self.play(g,TAME);saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(self.rehash(deepcopy(saved)),registry()).snapshot(),saved)
        for field in('members','candidates'):
            bad=deepcopy(saved)
            if field=='members':bad['state']['minion_family_history'][0][field][0]['card_id']=BEASTS[4]
            else:bad['state']['minion_family_history'][0][field][0].pop()
            with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(bad),registry())

    def test_rehashed_cropped_history_and_borrowed_player_or_revision_are_rejected(self):
        g=self.game((TAME,TAME));self.play(g,TAME);self.play(g,TAME);saved=json.loads(json.dumps(g.snapshot()))
        for mutation in('crop','player','previous'):
            bad=deepcopy(saved)
            if mutation=='crop':bad['state']['minion_family_history'].pop()
            elif mutation=='player':bad['state']['minion_family_history'][1]['previous']['player_id']=2
            else:bad['state']['minion_family_history'][1]['previous']['revision']=0
            with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(bad),registry())

    def test_explicit_old_snapshot_schema_is_rejected(self):
        g=self.game((TAME,));saved=g.snapshot();saved['schema_version']=394
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())

    def test_actual_rewind_retry_replaces_attempt_history_without_accumulating_upgrade(self):
        g=self.game((TAME,P+'rewind'));self.play(g,TAME);self.play(g,P+'rewind')
        self.assertEqual([x.cost for x in self.family(g)],[5]*3);self.portable(g)
        self.choose(g,'retry')
        self.assertEqual([x.cost for x in self.family(g)],[5]*3)
        self.assertEqual(len(g.state.minion_family_history),2)
        self.assertEqual((len(g.state.cast_history),g.state.players[1].mana),(2,98));self.portable(g)

    def test_failed_actual_rewind_retry_restores_original_family_and_pending_offer(self):
        g=self.game((TAME,P+'rewind_fail'));self.play(g,TAME);self.play(g,P+'rewind_fail');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K192 deliberate'):self.choose(g,'retry')
        self.assertEqual(g.snapshot(),before);self.portable(g);self.choose(g,'keep')
        self.assertEqual([x.cost for x in self.family(g)],[5]*3);self.portable(g)


if __name__=='__main__':unittest.main()
