import json
import unittest
from functools import lru_cache

from hs_sim.cards import build_registry
from hs_sim.cards.ancient_word_cards import HAWK, LASH, PAST, PRESENT, PROGRAMS, load_batch
from hs_sim.engine import (AddSpellRepeatModifier, CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard, PlayerSetup,
    ResolutionError, Scenario, SelectChoice, SnapshotError, SpellSchool, TriggerSpec)
from hs_sim.engine.effects import ChoiceOption, Damage, Destroy, GainArmor, RequestChoice
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.model import CardClass, CardMetadata, DamageKind
from hs_sim.engine.next_spell_bodies import CLAIMED, STARTED, ContinueNextSpellBodies, FinishNextSpellBody
from hs_sim.engine.player_effects import AddPlayerEffect, RemovePlayerEffect
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from tools.card_batch import check_face

P = 'fixture.ancient_words.'
(SHADOW, FIRE, AUTO, ARM_ALL, ARM_TWO, COUNTER, CLEAR, WAIT, FAIL, HIT, FREE, BAD, TWICE, PLAIN, SD, WATCH) = tuple(
    P+x for x in ('shadow', 'fire', 'auto', 'arm_all', 'arm_two', 'counter', 'clear', 'wait',
        'fail', 'hit', 'free', 'bad', 'twice', 'plain', 'sd', 'watch'))
COIN = 'GAME_005'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(maxsize=None)
def fixture(mode='normal', role='writer'):
    if role not in ('writer', 'reader'): raise ValueError('Independent fixture registries required')
    r = build_registry()
    def fail(c): raise ResolutionError('Explicit claimed Shadow base failure')
    def free(c):
        board = c.state.players[c.player_id].board
        return (Destroy(board[0], c.source_id),) if board else ()
    bodies = {SHADOW:lambda c:(), FIRE:lambda c:(), AUTO:lambda c:(CastSpell(c.player_id, SHADOW, c.source_id),),
        ARM_ALL:lambda c:tuple(CastSpell(c.player_id, cid, c.source_id) for cid in (PAST, PRESENT, LASH)),
        ARM_TWO:lambda c:(CastSpell(c.player_id,LASH,c.source_id),CastSpell(c.player_id,LASH,c.source_id)),
        COUNTER:lambda c:(SetSecret(2,'CORE_EX1_287'),),
        TWICE:lambda c:(AddSpellRepeatModifier(c.player_id,uses=1,source_id=c.source_id),),
        CLEAR:lambda c:tuple(RemovePlayerEffect(c.player_id,e.id) for e in c.state.players[c.player_id].player_effects
            if e.spec_id in PROGRAMS.values()),
        WAIT:lambda c:(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),),c.source_id),),
        FAIL:fail, HIT:lambda c:(Damage(c.state.players[2].hero_id,1,c.source_id,DamageKind.SPELL),), FREE:free,
        BAD:lambda c:(AddPlayerEffect(c.player_id,PROGRAMS[PRESENT],c.source_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        school=SpellSchool.SHADOW if cid in (SHADOW,WAIT,FAIL,HIT,FREE) else SpellSchool.FIRE if cid==FIRE else None
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,spell_school=school,metadata=META))
    r.register_card(CardDefinition(PLAIN,PLAIN,CardType.MINION,cost=5,attack=1,health=10,metadata=META))
    r.register_card(CardDefinition(SD,SD,CardType.MINION,health=10,spell_damage=1,metadata=META))
    if mode in ('extra_wait','extra_fail','new_program'):
        def observe(c):
            if mode=='new_program':
                hero=c.state.entities[c.state.players[c.player_id].hero_id]
                if hero.armor:return()
                return(GainArmor(c.player_id,1),CastSpell(c.player_id,LASH,c.source_id))
            source=c.state.entities.get(c.event.source_id)
            if source is None or source.card_id!=SHADOW:return()
            if mode=='extra_fail':raise ResolutionError('Explicit original extra draw failure')
            return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),),c.source_id),)
        r.register_behavior(WATCH,observe)
        event='player_effect_removed' if mode=='new_program' else 'card_drawn'
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
            triggers=(TriggerSpec(event,WATCH),)))
    return r


class AncientWordTests(unittest.TestCase):
    def game(self,hand=(),board=(),mode='normal',other_hand=(),deck=(PLAIN,)*10):
        if mode!='normal':board=(WATCH,)+board
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=other_hand,deck=(COIN,)*10,mana=10,max_mana=10)),seed=0),fixture(mode))

    def play(self,g,cid,player=1):
        eid=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(player,eid));return eid

    def pending(self,g,player=1):
        return [e for e in g.state.players[player].player_effects if e.spec_id in PROGRAMS.values()]

    def health(self,g):return g.state.entities[g.state.players[2].hero_id].health

    def hawks(self,g):return [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id==HAWK]

    def choose(self,g,option='continue'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(option,)))

    def portable(self,g,mode='normal'):
        saved=g.snapshot();r=fixture(mode,'reader')
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)),r).snapshot(),saved)
        self.assertEqual(replay(build_replay(g),r).snapshot(),saved)
        for p in(1,2):
            visible=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in ('"next_spell_body_effects"','"next_spell_body_cursor"','"material_json"','"rng_state"',STARTED,CLAIMED):
                self.assertNotIn(key,visible)

    def test_complete_three_roots_named_raw_token_and_source_only_enchantments(self):
        d=load_batch();rows={x['record']['id']:x['record'] for x in d['cards']}
        self.assertEqual(len(d['official_observations']),6)
        for o in d['official_observations']:check_face(rows[o['card_id']],o['face'],o['locale'])
        self.assertFalse(d['dependency_primary_verified'])
        self.assertEqual(tuple(x['record']['id'] for x in d['dependencies']),(HAWK,))
        card=fixture().card(HAWK);self.assertEqual((card.cost,card.attack,card.health),(5,5,5))
        self.assertIn(Keyword.LIFESTEAL,card.keywords)
        from hs_sim.engine.next_spell_bodies import NextSpellBodyProfile
        original = [fixture().next_spell_body_profiles[key] for key in PROGRAMS.values()]
        self.assertEqual(len(original),3)
        self.assertTrue(all(type(profile) is NextSpellBodyProfile for profile in original))

    def test_past_paid_body_and_next_shadow_each_draw_and_reduce_original_card(self):
        g=self.game((PAST,SHADOW));self.play(g,PAST)
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(len(self.pending(g)),1)
        self.play(g,SHADOW)
        self.assertFalse(self.pending(g));self.assertEqual(len(g.state.draw_history),2)
        cards=[g.state.entities[i] for i in g.state.players[1].hand]
        from hs_sim.engine.costs import local_cost
        self.assertEqual([local_cost(e)[0] for e in cards],[3,3]);self.portable(g)

    def test_present_initial_and_extra_summon_one_real_lifesteal_body_each(self):
        g=self.game((PRESENT,SHADOW));self.play(g,PRESENT);self.assertEqual(len(self.hawks(g)),1)
        self.play(g,SHADOW);self.assertEqual(len(self.hawks(g)),2)
        self.assertTrue(all((e.attack,e.health)==(5,5) and Keyword.LIFESTEAL in e.keywords for e in self.hawks(g)))
        self.assertEqual(g.state.players[1].mana,5);self.portable(g)

    def test_lash_extra_uses_current_spell_source_power_and_runs_after_base_body(self):
        g=self.game((LASH,HIT),(SD,));self.play(g,LASH);source=self.play(g,HIT)
        self.assertEqual(self.health(g),20)
        hits=[e.amount for e in g.events if e.kind=='damage_dealt' and e.source_id==source]
        self.assertEqual(hits,[2,4]);self.assertEqual(len(g.state.cast_history),2)
        self.assertEqual(g.state.cast_history[-1].next_spell_body_cursor,2);self.portable(g)

    def test_other_school_and_automatic_shadow_do_not_consume_the_next_played_shadow(self):
        g=self.game((LASH,FIRE,AUTO,SHADOW));self.play(g,LASH)
        self.play(g,FIRE);self.play(g,AUTO);self.assertEqual(len(self.pending(g)),1)
        self.assertEqual(self.health(g),27);self.play(g,SHADOW);self.assertEqual(self.health(g),24)

    def test_countered_shadow_keeps_pending_program_for_next_accepted_payload(self):
        g=self.game((LASH,COUNTER,SHADOW,SHADOW));self.play(g,LASH);self.play(g,COUNTER)
        self.play(g,SHADOW);self.assertEqual(len(self.pending(g)),1);self.assertEqual(self.health(g),27)
        self.play(g,SHADOW);self.assertFalse(self.pending(g));self.assertEqual(self.health(g),24);self.portable(g)

    def test_cross_turn_and_other_player_keep_original_owner_program(self):
        g=self.game((LASH,SHADOW),other_hand=(SHADOW,));self.play(g,LASH)
        g.apply(EndTurn(1));self.play(g,SHADOW,2);self.assertEqual(len(self.pending(g)),1)
        g.apply(EndTurn(2));self.play(g,SHADOW);self.assertEqual(self.health(g),24);self.portable(g)

    def test_next_ancient_word_installs_new_program_without_self_consumption_or_regrant(self):
        g=self.game((LASH,LASH,SHADOW));self.play(g,LASH);self.play(g,LASH)
        self.assertEqual(self.health(g),21);self.assertEqual(len(self.pending(g)),1)
        self.play(g,SHADOW);self.assertEqual(self.health(g),18);self.assertFalse(self.pending(g))

    def test_multiple_programs_preserve_original_order_and_each_runs_once(self):
        g=self.game((ARM_ALL,SHADOW));self.play(g,ARM_ALL)
        before=tuple(e.id for e in self.pending(g));self.assertEqual(len(before),3)
        self.play(g,SHADOW);record=g.state.cast_history[-1]
        self.assertEqual(tuple(e.id for e in record.next_spell_body_effects),before)
        self.assertEqual(record.next_spell_body_cursor,6);self.assertEqual(len(self.hawks(g)),2)
        starts=[dict(e.data)['instance_id'] for e in g.events if e.kind==STARTED]
        self.assertEqual(starts,list(before));self.assertEqual(self.health(g),24);self.portable(g)

    def test_duplicate_source_programs_are_two_instances_and_not_card_id_deduplicated(self):
        g=self.game((ARM_TWO,SHADOW));self.play(g,ARM_TWO);self.assertEqual(len(self.pending(g)),2)
        self.play(g,SHADOW);self.assertEqual(self.health(g),18)
        self.assertEqual(g.state.cast_history[-1].next_spell_body_cursor,4)

    def test_actual_repeated_word_installs_two_programs_without_claiming_on_repeat(self):
        g=self.game((TWICE,LASH,SHADOW));self.play(g,TWICE);self.play(g,LASH)
        self.assertEqual(len(self.pending(g)),2);self.assertEqual(self.health(g),24)
        self.play(g,SHADOW);self.assertEqual(self.health(g),18)
        self.assertEqual(g.state.cast_history[-1].next_spell_body_cursor,4);self.portable(g)

    def test_program_created_during_claim_reactions_is_not_added_to_old_plan(self):
        g=self.game((LASH,SHADOW,SHADOW),mode='new_program');self.play(g,LASH);self.play(g,SHADOW)
        record=next(c for c in g.state.cast_history if c.card_id==SHADOW)
        self.assertEqual(len(record.next_spell_body_effects),1)
        self.assertEqual(len(self.pending(g)),1);self.assertEqual(self.health(g),21)
        self.play(g,SHADOW);self.assertEqual(self.health(g),18);self.portable(g,'new_program')

    def test_base_wait_already_owns_original_program_and_resumes_it_once(self):
        g=self.game((LASH,WAIT));self.play(g,LASH);self.play(g,WAIT)
        self.assertFalse(self.pending(g));self.assertEqual(self.health(g),27)
        self.assertEqual(g.state.cast_history[-1].next_spell_body_cursor,0);self.portable(g)
        self.choose(g);self.assertEqual(self.health(g),24)

    def test_wait_inside_extra_draw_restores_running_cursor_and_remaining_finish(self):
        g=self.game((PAST,SHADOW),mode='extra_wait');self.play(g,PAST);self.play(g,SHADOW)
        self.assertEqual(g.state.cast_history[-1].next_spell_body_cursor,1);self.portable(g,'extra_wait')
        self.choose(g);self.assertEqual(g.state.cast_history[-1].next_spell_body_cursor,2)
        self.assertEqual(len(g.state.draw_history),2);self.assertFalse(self.pending(g))

    def test_base_failure_and_late_extra_failure_restore_original_program_and_rng(self):
        for mode,word,body in (('normal',LASH,FAIL),('extra_fail',PAST,SHADOW)):
            with self.subTest(mode=mode):
                g=self.game((word,body),mode=mode);self.play(g,word);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,body)
                self.assertEqual(g.snapshot(),saved)

    def test_full_initial_board_keeps_program_and_extra_sees_space_freed_by_base(self):
        g=self.game((PRESENT,FREE),(PLAIN,)*7);self.play(g,PRESENT)
        self.assertFalse(self.hawks(g));self.assertEqual(len(self.pending(g)),1)
        self.play(g,FREE);self.assertEqual(len(self.hawks(g)),1)
        self.assertEqual(len(g.state.players[1].board),7)

    def test_explicit_removal_and_wrong_spell_source_use_existing_transaction_boundary(self):
        g=self.game((LASH,CLEAR,SHADOW));self.play(g,LASH);self.play(g,CLEAR);self.play(g,SHADOW)
        self.assertEqual(self.health(g),27);self.portable(g)
        g=self.game((BAD,));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,BAD)
        self.assertEqual(g.snapshot(),saved)

    def test_rehashed_missing_claim_material_or_truncated_cursor_is_rejected(self):
        g=self.game((LASH,SHADOW));self.play(g,LASH);self.play(g,SHADOW)
        for mode in ('drop','cursor','missing_field'):
            with self.subTest(mode=mode):
                bad=json.loads(json.dumps(g.snapshot()));row=bad['state']['cast_history'][-1]
                if mode=='drop':row['next_spell_body_effects']=[];row['next_spell_body_cursor']=0
                elif mode=='cursor':row['next_spell_body_cursor']=0
                else:row.pop('next_spell_body_cursor')
                bad['state_hash']=canonical_hash({k:v for k,v in bad.items()
                    if k not in ('schema_version','events','events_hash','state_hash')})
                with self.assertRaises(SnapshotError) as error:Game.from_snapshot(bad,fixture())
                self.assertNotIn('digest mismatch',str(error.exception))

    def test_waiting_extra_queue_rejects_unknown_parent_or_repeated_slot(self):
        g=self.game((PAST,SHADOW),mode='extra_wait');self.play(g,PAST);self.play(g,SHADOW)
        record=g.state.cast_history[-1];codec=FrameCodec(default_mechanics(),g.registry,origin_state=g.state)
        for request in (FinishNextSpellBody(record.id,0),ContinueNextSpellBodies(record.id,1)):
            self.assertEqual(codec.decode(codec.encode(request)),request)
        for request in (ContinueNextSpellBodies(record.id,0),FinishNextSpellBody(record.id,1),
                ContinueNextSpellBodies(record.id+9,0)):
            with self.subTest(request=request),self.assertRaises(ValueError):codec.encode(request)

    def test_real_shadow_rewind_restores_old_pending_program_without_double_results(self):
        g=self.game((LASH,'TIME_610'));self.play(g,LASH);self.play(g,'TIME_610')
        self.assertEqual(self.health(g),24);self.portable(g)
        self.choose(g,'retry');self.assertEqual(self.health(g),24)
        self.assertFalse(self.pending(g));self.assertEqual(g.state.cast_history[-1].next_spell_body_cursor,2)
        self.portable(g)
