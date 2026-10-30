"""Actual Conductivity entries, complete payloads and original adjacent body proofs."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json,unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import build_registry,past_conductivity as native
from hs_sim.engine import EndTurn,Game,PlayCard,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (ChoiceOption,Damage,DamageBatch,Destroy,GrantKeyword,InvokeBehavior,
    RandomDamage,RequestChoice,Summon)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,PlayerEffectSpec,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.next_spell_bodies import (AdjacentSpellBodyProfile,ContinueNextSpellBodies,
    FinishNextSpellBody,body_slots,validate_profile)
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION,canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

CARD=native.ROOTS[0];BOLT='CORE_EX1_238';JADE='CFM_707';HEX='EX1_246';CHORD='ETC_356'
P='k678.'
A,B,C,ELUSIVE,STEALTH,IMMUNE,DORMANT,SD,SMALL,LOCATION=(P+x for x in
    ('a','b','c','elusive','stealth','immune','dormant','sd','small','location'))
CHOICE,PLAIN,RESTRICTED,REMOVE_LEFT,PROTECT_RIGHT,AUTO,AUTO_BOTH,COUNTER,COUNTER_SOURCE,BAD,FAIL=(P+x for x in
    ('choice','plain','restricted','remove_left','protect_right','auto','auto_both','counter','counter_source','bad','fail'))
WOUND=P+'wound'


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=build_registry()
    for cid,hp,keywords,dormant,sd in ((A,20,(),0,0),(B,20,(),0,0),(C,20,(),0,0),
            (SMALL,1,(),0,0),(ELUSIVE,20,(Keyword.ELUSIVE,),0,0),(STEALTH,20,(Keyword.STEALTH,),0,0),
            (IMMUNE,20,(Keyword.IMMUNE,),0,0),(DORMANT,20,(),2,0),(SD,20,(),0,2)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=2,health=hp,
            keywords=keywords,dormant_turns=dormant,spell_damage=sd,metadata=metadata(collectible=False,tribes=())))
    r.register_behavior(P+'nothing',lambda c:())
    def wound(c):
        board=c.state.players[3-c.player_id].board
        return(DamageBatch(tuple(Damage(eid,1 if i==1 else 19,c.source_id,DamageKind.SPELL)
            for i,eid in enumerate(board))),)
    r.register_behavior(WOUND,wound)
    r.register_card(CardDefinition(WOUND,WOUND,CardType.SPELL,on_play=WOUND,metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,cost=1,durability=2,
        on_use=P+'nothing',metadata=metadata(collectible=False)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K678 deliberate body rollback')))
    def choose(c):
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue',
            (Damage(c.target_id,1,c.source_id,DamageKind.SPELL),)),ChoiceOption('fault','Fail',
            (RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
             InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    def remove_left(c):
        board=c.state.players[c.state.entities[c.target_id].controller].board
        extra=() if c.target_id!=c.cast.target_id or board.index(c.target_id)==0 else (Destroy(board[board.index(c.target_id)-1],c.source_id),)
        return(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),*extra)
    def protect_right(c):
        board=c.state.players[c.state.entities[c.target_id].controller].board;i=board.index(c.target_id)
        extra=() if c.target_id!=c.cast.target_id or i+1==len(board) else (GrantKeyword(board[i+1],Keyword.ELUSIVE,c.source_id),)
        return(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),*extra)
    r.register_target_rule(P+'only_b',lambda c:c.state.entities[c.target_id].card_id==B)
    for cid,body in ((CHOICE,choose),(PLAIN,lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),)),
            (RESTRICTED,lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),)),(REMOVE_LEFT,remove_left),(PROTECT_RIGHT,protect_right)):
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=cid,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),
            target_rule=P+'only_b' if cid==RESTRICTED else 'any_entity',metadata=metadata(collectible=False)))
    def auto(c,both=False):
        target=c.state.players[3-c.player_id].board[1]
        return(*((CastSpell(c.player_id,CARD,c.source_id),)if both else()),
            CastSpell(c.player_id,BOLT,c.source_id,targeting='explicit',target_id=target))
    for cid,both in ((AUTO,False),(AUTO_BOTH,True)):
        r.register_behavior(cid,lambda c,both=both:auto(c,both))
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,health=5,on_play=cid,metadata=metadata(collectible=False)))
    for cid,target_card in ((COUNTER,BOLT),(COUNTER_SOURCE,CARD)):
        r.register_behavior(cid,lambda c,target_card=target_card:(CounterSpell(dict(c.event.data)['window_id']),)
            if c.event.player_id!=c.player_id and c.state.entities[c.event.source_id].card_id==target_card else())
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=20,triggers=(TriggerSpec('card_committed',cid),),
            metadata=metadata(collectible=False,tribes=())))
    r.register_behavior(BAD,lambda c:(AddPlayerEffect(c.player_id,native.PROGRAM,c.source_id),))
    r.register_card(CardDefinition(BAD,BAD,CardType.SPELL,on_play=BAD,metadata=metadata(collectible=False)))
    r.validate();return r


class ConductivityTests(CardBatchTestMixin,unittest.TestCase):
    mode='fixture'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))
    def game(self,hand=(CARD,BOLT),*,board=(),enemy=(A,B,C),active=1,deck=None):
        self.mode='fixture';deck=(A,)*12 if deck is None else deck
        setups=[PlayerSetup('HERO_08',deck=deck,mana=10,max_mana=10),PlayerSetup('HERO_08',deck=deck,mana=10,max_mana=10)]
        setups[active-1]=replace(setups[active-1],hand=hand,board=board)
        setups[2-active]=replace(setups[2-active],board=enemy)
        return Game.from_scenario(Scenario(tuple(setups),active_player=active,seed=678),fixture('writer'))
    def ids(self,g,p=2):return tuple(g.state.players[p].board)
    def hp(self,g,ids):return tuple(g.state.entities[i].health for i in ids)
    def arm(self,g,p=1):self.play(g,CARD,player=p)
    def record(self,g):return g.state.cast_history[-1]
    def program(self,g,p=1):return tuple(e for e in g.state.players[p].player_effects if e.spec_id==native.PROGRAM)
    def drain(self,g):
        for _ in range(20):
            if g.state.pending_choice is None:return
            self.choose(g)
        self.fail('Choice chain did not terminate')

    def test_full_source_roles_and_independent_profile(self):
        d=native.load_batch();r=fixture('writer');card=r.card(CARD)
        self.assertEqual((card.cost,card.spell_school.value),(2,'nature'))
        self.assertEqual(canonical_digest(asdict(card)),d['cards'][0]['definition_sha256'])
        self.assertEqual([x['record']['id'] for x in d['evidence_only']],['YOG_522e'])
        self.assertEqual(len(d['original_shaman_member_ids']),71)
        self.assertFalse(d['complete_shaman_source_bound'])
        self.assertEqual(r.player_effect(native.PROGRAM),PlayerEffectSpec(native.PROGRAM,CARD,kind='next_spell_adjacent'))
        validate_profile(r,AdjacentSpellBodyProfile(native.PROGRAM,CARD))
        with self.assertRaises(ValueError):PlayerEffectSpec('bad',CARD,kind='next_spell_adjacent',spell_damage=1)

    def test_real_bolt_full_overload_three_bodies_one_cast_one_payment(self):
        g=self.game();ids=self.ids(g);self.arm(g);self.play(g,BOLT,ids[1])
        self.assertEqual(self.hp(g,ids),(17,17,17));self.assertEqual(g.state.players[1].overload_owed,3)
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(len(g.state.play_history),2)
        self.assertEqual(len(g.state.cast_history),2);self.assertEqual(self.record(g).target_id,ids[1])
        self.assertEqual(self.record(g).next_spell_body_cursor,4);self.assertFalse(self.program(g))
        self.assertEqual(sum(e.kind=='spell_cast_finished' and e.source_id==self.record(g).source_id for e in g.events),1)
        for player in (1,2):
            public=json.dumps(g.for_player(player).observe())
            for field in ('next_spell_body_board','next_spell_body_behaviors','next_spell_body_effects',
                    'adjacent_board_json','material_json','next_spell_body_cursor'):
                self.assertNotIn('"'+field+'"',public)
        self.portable(g)

    def test_real_jade_lightning_repeats_non_target_summons(self):
        g=self.game((CARD,JADE));ids=self.ids(g);self.arm(g);self.play(g,JADE,ids[1])
        self.assertEqual(self.hp(g,ids),(17,17,17))
        self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].health) for i in g.state.players[1].board],[(1,1),(2,2),(3,3)])
        self.assertEqual(len(g.state.cast_history),2);self.portable(g)

    def test_real_hex_uses_original_neighbors_after_primary_transform(self):
        g=self.game((CARD,HEX));ids=self.ids(g);self.arm(g);self.play(g,HEX,ids[1])
        self.assertEqual(len({g.state.entities[i].card_id for i in ids}),1)
        self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].health) for i in ids],[(0,1)]*3)
        self.portable(g)

    def test_official_legality_elusive_stealth_and_immune_skip_whole_extra_body(self):
        for side in (ELUSIVE,STEALTH,IMMUNE):
            with self.subTest(side=side):
                g=self.game(enemy=(side,B,C));ids=self.ids(g);self.arm(g);self.play(g,BOLT,ids[1])
                self.assertEqual(self.hp(g,ids),(20,17,17));self.assertEqual(g.state.players[1].overload_owed,2)

    def test_actual_chord_cannot_bypass_elusive(self):
        g=self.game((CARD,CHORD),enemy=(ELUSIVE,B,C));ids=self.ids(g);self.arm(g);self.play(g,CHORD,ids[1])
        self.assertEqual(self.hp(g,ids),(20,14,14));self.assertEqual(g.state.players[1].mana,3)
        self.portable(g)

    def test_printed_target_rule_is_rechecked_for_each_neighbor(self):
        g=self.game((CARD,RESTRICTED));ids=self.ids(g);self.arm(g);self.play(g,RESTRICTED,ids[1])
        self.assertEqual(self.hp(g,ids),(20,19,20));self.assertEqual(self.record(g).next_spell_body_cursor,4)

    def test_locations_block_bridging_and_dormant_neighbor_is_invalid(self):
        g=self.game(enemy=(A,LOCATION,B,DORMANT,C));ids=self.ids(g);self.arm(g);self.play(g,BOLT,ids[2])
        self.assertEqual(self.hp(g,(ids[0],ids[2],ids[4])),(20,17,20));self.assertEqual(g.state.players[1].overload_owed,1)
        self.assertEqual(len(self.record(g).next_spell_body_board),5);self.portable(g)

    def test_original_neighbors_are_not_replaced_after_primary_removal(self):
        g=self.game((CARD,REMOVE_LEFT),enemy=(A,A,B,C,C));ids=self.ids(g);self.arm(g);self.play(g,REMOVE_LEFT,ids[2])
        self.assertEqual(g.state.entities[ids[1]].zone,Zone.GRAVEYARD)
        self.assertEqual(self.hp(g,(ids[0],ids[2],ids[3],ids[4])),(20,19,19,20));self.portable(g)

    def test_legality_reads_new_state_before_each_body(self):
        g=self.game((CARD,PROTECT_RIGHT));ids=self.ids(g);self.arm(g);self.play(g,PROTECT_RIGHT,ids[1])
        self.assertEqual(self.hp(g,ids),(19,19,20));self.assertIn(Keyword.ELUSIVE,g.state.entities[ids[2]].keywords)

    def test_spell_damage_applies_to_every_complete_body(self):
        g=self.game(board=(SD,));ids=self.ids(g);self.arm(g);self.play(g,BOLT,ids[1])
        self.assertEqual(self.hp(g,ids),(15,15,15));self.assertEqual(g.state.players[1].overload_owed,3)

    def test_hero_arrow_consumes_without_adjacent_bodies(self):
        g=self.game();self.arm(g);self.play(g,BOLT,g.state.players[2].hero_id)
        self.assertFalse(self.program(g));self.assertEqual(self.record(g).next_spell_body_board,())
        self.assertEqual(self.record(g).next_spell_body_cursor,0);self.assertEqual(g.state.players[1].overload_owed,1)
        self.portable(g)

    def test_no_arrow_spell_consumes_and_does_not_leak_to_following_bolt(self):
        g=self.game((CARD,'GAME_005',BOLT));ids=self.ids(g);self.arm(g);self.play(g,'GAME_005')
        self.assertFalse(self.program(g));self.assertEqual(self.record(g).next_spell_body_board,())
        self.play(g,BOLT,ids[1]);self.assertEqual(self.hp(g,ids),(20,17,20));self.portable(g)

    def test_unconsumed_program_expires_at_actual_turn_end(self):
        g=self.game();self.arm(g);self.assertEqual(len(self.program(g)),1);self.portable(g)
        g.apply(EndTurn(1));self.assertFalse(self.program(g));self.portable(g)

    def test_second_player_owns_program_targets_overload_and_payment(self):
        g=self.game(active=2);ids=self.ids(g,1);self.arm(g,2);self.play(g,BOLT,ids[1],player=2)
        self.assertEqual(self.hp(g,ids),(17,17,17));self.assertEqual(g.state.players[2].overload_owed,3)
        self.assertEqual(g.state.players[1].overload_owed,0);self.assertEqual(g.state.players[2].mana,7);self.portable(g)

    def test_automatic_actual_next_cast_consumes_shared_program(self):
        g=self.game((CARD,AUTO));ids=self.ids(g);self.arm(g);self.play(g,AUTO)
        self.assertEqual(self.hp(g,ids),(17,17,17));self.assertEqual(self.record(g).origin,'effect')
        self.assertFalse(self.program(g));self.assertEqual(g.state.players[1].overload_owed,3);self.portable(g)

    def test_automatic_conductivity_installs_before_automatic_bolt(self):
        g=self.game((AUTO_BOTH,));ids=self.ids(g);self.play(g,AUTO_BOTH)
        self.assertEqual([c.card_id for c in g.state.cast_history],[CARD,BOLT]);self.assertEqual(self.hp(g,ids),(17,17,17))
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(g.state.players[1].mana,9);self.portable(g)

    def test_countered_recipient_retains_pending_program_for_next_payload(self):
        g=self.game((CARD,BOLT,JADE),enemy=(A,B,C,COUNTER));ids=self.ids(g);self.arm(g);self.play(g,BOLT,ids[1])
        self.assertEqual(self.record(g).failure,'countered');self.assertEqual(len(self.program(g)),1)
        self.play(g,JADE,ids[1]);self.assertEqual(self.hp(g,ids[:3]),(17,17,17));self.assertFalse(self.program(g));self.portable(g)

    def test_countered_source_installs_nothing_and_wrong_source_cannot_arm(self):
        g=self.game(enemy=(A,B,C,COUNTER_SOURCE));self.arm(g);self.assertFalse(self.program(g));self.portable(g)
        g=self.game((BAD,));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,BAD)
        self.assertEqual(g.snapshot(),saved)

    def test_primary_and_both_extra_choice_waits_restore_with_original_arrows(self):
        g=self.game((CARD,CHOICE));ids=self.ids(g);self.arm(g);self.play(g,CHOICE,ids[1])
        for cursor in (0,1,3):
            self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.record(g).next_spell_body_cursor,cursor)
            g=self.portable(g);self.choose(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.hp(g,ids),(19,19,19));self.portable(g)

    def test_failure_inside_extra_body_rolls_back_rng_and_running_cursor(self):
        g=self.game((CARD,CHOICE));ids=self.ids(g);self.arm(g);self.play(g,CHOICE,ids[1]);self.choose(g)
        self.assertEqual(self.record(g).next_spell_body_cursor,1);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);g=self.portable(g);self.drain(g);self.assertEqual(self.hp(g,ids),(19,19,19))

    def test_rehashed_board_body_vector_cursor_and_missing_fields_are_rejected(self):
        g=self.game();ids=self.ids(g);self.arm(g);self.play(g,BOLT,ids[1])
        for mode in ('board','body','cursor','missing'):
            with self.subTest(mode=mode):
                bad=deepcopy(g.snapshot());row=bad['state']['cast_history'][-1]
                if mode=='board':row['next_spell_body_board']=row['next_spell_body_board'][1:]
                elif mode=='body':row['next_spell_body_behaviors']=[]
                elif mode=='cursor':row['next_spell_body_cursor']=0
                else:row.pop('next_spell_body_board')
                bad['state_hash']=canonical_hash({k:v for k,v in bad.items() if k not in('schema_version','events','events_hash','state_hash')})
                with self.assertRaises(SnapshotError) as caught:Game.from_snapshot(bad,fixture('independent-reader'))
                self.assertNotIn('digest mismatch',str(caught.exception))

    def test_extra_finish_and_continue_reject_repeated_or_wrong_parent_slots(self):
        g=self.game((CARD,CHOICE));ids=self.ids(g);self.arm(g);self.play(g,CHOICE,ids[1]);self.choose(g)
        record=self.record(g);codec=FrameCodec(default_mechanics(),g.registry,origin_state=g.state)
        for request in (FinishNextSpellBody(record.id,0),ContinueNextSpellBodies(record.id,1)):
            self.assertEqual(codec.decode(codec.encode(request)),request)
        for request in (ContinueNextSpellBodies(record.id,0),FinishNextSpellBody(record.id,1),ContinueNextSpellBodies(record.id+4,0)):
            with self.assertRaises(ValueError):codec.encode(request)

    def test_actual_source_cost_spell_uses_body_arrow_and_one_original_cost(self):
        g=self.game((CARD,'BE_094',A),board=(A,B,C),enemy=());ids=self.ids(g,1)
        self.arm(g);self.play(g,'BE_094',ids[1]);self.assertEqual(self.hp(g,ids),(22,22,22))
        remaining=self.entity(g,A);self.assertEqual((remaining.attack,remaining.health),(8,26))
        self.assertEqual(g.state.players[1].mana,7);self.portable(g)

    def test_actual_numeric_optional_target_reads_each_body_arrow(self):
        g=self.game((CARD,'CATA_557'));ids=self.ids(g);self.arm(g);self.play(g,'CATA_557',ids[1])
        self.assertEqual(self.hp(g,ids),(17,17,17));self.portable(g)

    def test_actual_forbidden_flame_spends_remaining_mana_once_then_zero(self):
        g=self.game((CARD,'OG_086'));ids=self.ids(g);self.arm(g);self.play(g,'OG_086',ids[1])
        self.assertEqual(self.hp(g,ids),(20,12,20));self.assertEqual([x.actual for x in g.state.mana_consumption_history],[8,0,0])
        self.assertEqual(g.state.players[1].mana,0);self.portable(g)

    def test_actual_growing_spell_hits_original_neighbors_and_shuffles_three_successors(self):
        g=self.game((CARD,'SW_110'));ids=self.ids(g);self.arm(g);self.play(g,'SW_110',ids[1])
        self.assertEqual(self.hp(g,ids),(18,18,18))
        successors=[g.state.entities[i] for i in g.state.players[1].deck if g.state.entities[i].card_id=='SW_110']
        self.assertEqual(len(successors),3);self.portable(g)

    def test_actual_returning_damage_accepts_neighbor_remainder_receipt(self):
        g=self.game((WOUND,CARD,'CATA_585'));ids=self.ids(g);self.play(g,WOUND);self.arm(g);self.play(g,'CATA_585',ids[1])
        self.assertEqual(g.state.entities[ids[1]].health,11)
        self.assertEqual(g.state.entities[ids[0]].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[ids[2]].zone,Zone.GRAVEYARD)
        self.assertEqual(len([i for i in g.state.players[1].hand if g.state.entities[i].card_id=='CATA_585']),1)
        self.portable(g)

    def test_actual_composed_potion_executes_three_complete_bodies_without_extra_payment(self):
        from hs_sim.engine.composed_spells import ComposedSpellRecipe
        r=fixture('writer');profile=next(iter(r._composed_spell_profiles.values()))
        target=next(i for i,c in enumerate(profile.ingredients) if c.targeting is not None)
        other=next(i for i,c in enumerate(profile.ingredients) if c.targeting is None)
        parts=sorted((target,other));cid=ComposedSpellRecipe(profile.template_card_id,
            *(profile.ingredients[i].card_id for i in parts)).card_id
        g=self.game((CARD,cid));ids=self.ids(g);self.arm(g);self.play(g,cid,ids[1])
        self.assertEqual(self.hp(g,ids),(11,11,11));self.assertEqual(g.state.players[1].mana,7)
        self.assertEqual(len(g.state.cast_history),2);self.assertFalse(self.program(g));self.portable(g)

    def test_actual_flame_shock_two_arrow_cast_is_explicitly_rejected_without_effects(self):
        g=self.game((CARD,'BE_302'));ids=self.ids(g);self.arm(g);saved=g.snapshot()
        source=self.entity(g,'BE_302').id
        with self.assertRaisesRegex(ResolutionError,'multi-arrow'):
            g.apply(PlayCard(1,source,ids[1],target_ids=(ids[1],ids[2])))
        self.assertEqual(g.snapshot(),saved);self.assertEqual(len(self.program(g)),1)

    def test_old_snapshot_schema_is_explicitly_rejected(self):
        g=self.game();bad=g.snapshot();self.assertEqual(bad['schema_version'],SNAPSHOT_SCHEMA_VERSION)
        bad['schema_version']=643
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,fixture('writer'))

    def test_real_standard_host_executes_conductivity_and_actual_bolt(self):
        self.mode='host';h=host('writer');plain='CORE_CS2_120';h.registry.card(plain)
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_02',hand=(CARD,BOLT),mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=(plain,)*3,mana=10,max_mana=10)),seed=678,generation_context=h.context),h.registry)
        ids=self.ids(g);self.arm(g);self.play(g,BOLT,ids[1]);self.assertEqual(g.state.players[1].overload_owed,3)
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(len(g.state.cast_history),2)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in ids));self.portable(g)


if __name__=='__main__':unittest.main()
