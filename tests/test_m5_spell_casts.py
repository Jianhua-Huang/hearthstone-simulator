"""Execution origins, automatic choices and recoverable spell provenance."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, CastSpell, CastStoredSpell,
    DamageKind, Game, HandDerivativeSpec, HandRepeatSpec, Keyword, PlayCard, PlayerSetup, Scenario,
    SelectChoice, SnapshotError, SpellRepeatSpec, TargetSpec, TargetMode, TriggerSpec,
    ResolutionError, ResolutionLimitExceeded, Ruleset, Zone, cast_spells)
from hs_sim.engine.effects import (ChoiceOption, Damage, Destroy, GainArmor,
    RequestChoice, Summon, InvokeBehavior)
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.serialization import canonical_hash


class SpellCastTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.r.register_card(CardDefinition('body', 'body', CardType.MINION, attack=2, health=5))
        self.spell('armor', lambda c: [GainArmor(c.player_id, 3)], cost=8)
        self.spell('hit', lambda c: [Damage(c.target_id, 2, c.source_id, DamageKind.SPELL)], requires_target=True)
        self.spell('minion_hit', lambda c: [Damage(c.target_id, 2, c.source_id, DamageKind.SPELL)],
                   targeting=TargetSpec(kinds=(CardType.MINION,)))
        self.spell('driver', lambda c: [CastSpell(c.player_id, 'armor', c.source_id)])
        self.spell('nothing', lambda c: [])

    def spell(self, name, behavior, **kw):
        self.r.register_behavior(name, behavior)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, **kw))

    def game(self, hand=('driver',), board=(), enemy=(), deck=('nothing',)*8, enemy_deck=('nothing',)*8, rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01', hand=hand, board=board, deck=deck, max_mana=10, mana=10),
            PlayerSetup('HERO_08', board=enemy, deck=enemy_deck, max_mana=10, mana=10)), seed=210), self.r, ruleset=rules)

    def hero(self, g, p=1): return g.state.entities[g.state.players[p].hero_id]
    def find(self, g, name, zone='hand', p=1):
        return next(i for i in getattr(g.state.players[p], zone) if g.state.entities[i].card_id == name)
    def play(self, g, name, target=None):
        eid = self.find(g, name); g.apply(PlayCard(1, eid, target)); return eid
    def check(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap, self.r).snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), snap)
    def reject(self, snap):
        # Exercise semantic validation, independently of the transport digest.
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as raised:
            Game.from_snapshot(snap,self.r)
        self.assertNotIn('digest mismatch',str(raised.exception))
    def auto(self, card, **kw):
        self.spell('auto', lambda c: [CastSpell(c.player_id, card, c.source_id, **kw)])
    def choice_spell(self, name='choice'):
        self.spell(name, lambda c: [RequestChoice(c.player_id, (
            ChoiceOption('one', 'one', (GainArmor(c.player_id, 1),)),
            ChoiceOption('four', 'four', (GainArmor(c.player_id, 4),))), source_id=c.source_id)])
    def stored(self, zone=Zone.DECK, owner=1, **kw):
        self.spell('stored', lambda c: [CastStoredSpell(CardReference.capture(
            c.state.entities[getattr(c.state.players[owner], zone.value)[0]]), c.player_id, c.source_id, **kw)])

    def test_automatic_cast_no_payment_or_extra_hand_play(self):
        g=self.game();source=self.play(g,'driver');records=g.state.cast_history
        self.assertEqual(self.hero(g).armor,3);self.assertEqual(g.state.players[1].mana,10)
        self.assertEqual(len(g.state.play_history),1)
        self.assertEqual([c.origin for c in records],['hand','effect'])
        self.assertEqual(records[1].caster_id,source);self.assertIsNone(records[1].play_id)
        self.assertTrue(all(c.completed for c in records));self.check(g)

    def test_effect_source_is_separate_physical_entity(self):
        g=self.game();source=self.play(g,'driver');cast=g.state.cast_history[-1]
        self.assertNotEqual(source,cast.source_id)
        self.assertEqual(g.state.entities[cast.source_id].origin_entity_id,source)

    def test_manual_spell_history(self):
        g=self.game(('hit',));target=self.hero(g,2).id;source=self.play(g,'hit',target)
        row=g.state.cast_history[0]
        self.assertEqual((row.origin,row.source_id,row.target_id,row.from_zone),('hand',source,target,Zone.HAND))
        self.assertEqual(row.play_id,1);self.assertTrue(row.completed);self.check(g)

    def test_countered_attempt_excluded_from_success_query(self):
        self.spell('setup',lambda c:[SetSecret(2,'EX1_287')])
        g=self.game(('setup','hit'));self.play(g,'setup');self.play(g,'hit',self.hero(g,2).id)
        row=g.state.cast_history[-1];self.assertEqual(row.failure,'countered')
        self.assertEqual([c.card_id for c in cast_spells(g.state,1,successful=True)],['setup']);self.check(g)

    def test_manual_repeat_records_each_execution_and_one_play(self):
        self.r.register_card(CardDefinition('repeat','repeat',CardType.MINION,health=5,
            spell_repeats=(SpellRepeatSpec(3,class_mode='any'),)))
        g=self.game(('hit',),board=('repeat',));self.play(g,'hit',self.hero(g,2).id)
        self.assertEqual([c.origin for c in g.state.cast_history],['hand','repeat','repeat'])
        self.assertEqual([c.iteration for c in g.state.cast_history],[1,2,3])
        self.assertEqual(len(g.state.play_history),1);self.check(g)

    def test_effect_cast_does_not_reenter_manual_repeat_aura(self):
        self.r.register_card(CardDefinition('repeat','repeat',CardType.MINION,health=5,
            spell_repeats=(SpellRepeatSpec(2,class_mode='any'),)))
        g=self.game(board=('repeat',));self.play(g,'driver')
        self.assertEqual(self.hero(g).armor,6)
        self.assertEqual([c.origin for c in g.state.cast_history],['hand','effect','repeat','effect']);self.check(g)

    def test_explicit_effect_target(self):
        self.spell('auto',lambda c:[CastSpell(1,'hit',c.source_id,c.state.players[2].hero_id,targeting='explicit')])
        g=self.game(('auto',));self.play(g,'auto');self.assertEqual(self.hero(g,2).health,28);self.check(g)

    def test_random_target_is_reproducible_and_kept_in_history(self):
        self.auto('hit');a=self.game(('auto',));b=self.game(('auto',))
        self.play(a,'auto');self.play(b,'auto')
        self.assertEqual(a.snapshot(),b.snapshot());self.assertIn(a.state.cast_history[-1].target_id,(self.hero(a).id,self.hero(a,2).id));self.check(a)

    def test_required_no_target_fizzles_without_random_or_payload(self):
        self.auto('minion_hit');g=self.game(('auto',));rng=g.snapshot()['rng_state'];self.play(g,'auto')
        self.assertEqual(g.state.cast_history[-1].failure,'no_target')
        self.assertEqual(g.snapshot()['rng_state'],rng);self.check(g)

    def test_invalid_explicit_target_fizzles(self):
        self.auto('hit',target_id=9999,targeting='explicit');g=self.game(('auto',));self.play(g,'auto')
        self.assertEqual(g.state.cast_history[-1].failure,'invalid_target')
        self.assertIsNone(g.state.cast_history[-1].target_id);self.check(g)

    def test_optional_no_target_still_executes(self):
        self.spell('optional',lambda c:[GainArmor(1,2)],targeting=TargetSpec(mode=TargetMode.OPTIONAL,kinds=(CardType.MINION,)))
        self.auto('optional');g=self.game(('auto',));self.play(g,'auto');self.assertEqual(self.hero(g).armor,2);self.check(g)

    def test_automatic_targets_ignore_manual_stealth_and_elusive(self):
        self.r.register_card(CardDefinition('hidden','hidden',CardType.MINION,health=5,keywords=(Keyword.STEALTH,Keyword.ELUSIVE)))
        self.auto('minion_hit');g=self.game(('auto',),enemy=('hidden',));self.play(g,'auto')
        self.assertEqual(g.state.entities[self.find(g,'hidden','board',2)].health,3);self.check(g)

    def test_structural_target_relation_is_preserved(self):
        self.spell('enemy',lambda c:[Damage(c.target_id,1,c.source_id)],targeting=TargetSpec(relation='enemy'))
        self.auto('enemy');g=self.game(('auto',));self.play(g,'auto')
        self.assertEqual(g.state.cast_history[-1].target_id,self.hero(g,2).id)

    def test_existing_player_target_predicate_works_off_board(self):
        self.auto('BT_490');g=self.game(('auto',),enemy=('body',));self.play(g,'auto')
        self.assertTrue(g.state.cast_history[-1].completed);self.check(g)

    def test_stored_deck_spell_moves_original_without_drawing(self):
        self.stored();g=self.game(('stored',),deck=('armor',));eid=self.find(g,'armor','deck');self.play(g,'stored')
        row=g.state.cast_history[-1];self.assertEqual((row.source_id,row.from_zone),(eid,Zone.DECK))
        self.assertFalse(g.state.players[1].deck);self.assertEqual(self.hero(g).armor,3)
        self.assertFalse(any(e.kind=='card_drawn' for e in g.events));self.check(g)

    def test_stored_hand_spell_does_not_pay_or_count_as_play(self):
        self.stored(Zone.HAND);g=self.game(('armor','stored'));eid=self.find(g,'armor');self.play(g,'stored')
        self.assertEqual(g.state.cast_history[-1].source_id,eid);self.assertEqual(len(g.state.play_history),1)
        self.assertFalse(g.state.players[1].hand);self.assertEqual(g.state.players[1].mana,10);self.check(g)

    def test_foreign_deck_cast_retains_owner_changes_controller(self):
        self.stored(owner=2);g=self.game(('stored',),enemy_deck=('armor',));eid=self.find(g,'armor','deck',2);self.play(g,'stored')
        entity=g.state.entities[eid];self.assertEqual((entity.owner,entity.controller),(2,1))
        self.assertIn(eid,g.state.players[1].graveyard);self.assertFalse(g.state.players[2].deck);self.check(g)

    def test_stale_stored_reference_skips_without_cast_history(self):
        def fn(c):
            ref=CardReference.capture(c.state.entities[c.state.players[1].deck[0]])
            return [MoveCard(ref,1,Zone.HAND),CastStoredSpell(ref,1,c.source_id)]
        self.spell('stale',fn);g=self.game(('stale',),deck=('armor',));self.play(g,'stale')
        self.assertEqual(len(g.state.cast_history),1);self.assertEqual(self.hero(g).armor,0);self.check(g)

    def test_random_choice_resolves_without_player_action(self):
        self.choice_spell();self.auto('choice');g=self.game(('auto',));self.play(g,'auto')
        self.assertIsNone(g.state.pending_choice);self.assertIn(self.hero(g).armor,(1,4))
        self.assertEqual(len(g.history),1);self.check(g)

    def test_player_choice_suspends_and_restores_automatic_cast(self):
        self.choice_spell();self.auto('choice',choices='player');g=self.game(('auto',));self.play(g,'auto');self.check(g)
        self.assertEqual(len([c for c in g.state.cast_history if not c.completed]),2)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):
            c=match.state.pending_choice;match.apply(SelectChoice(c.player_id,c.id,('four',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.hero(g).armor,4);self.check(g)

    def test_choice_callback_retains_cast_context(self):
        self.r.register_behavior('selected',lambda c:[GainArmor(1,7 if c.cast and c.play is None else 1)])
        self.spell('choose',lambda c:[RequestChoice(1,(ChoiceOption('x','x'),),source_id=c.source_id,on_select='selected')])
        self.auto('choose');g=self.game(('auto',));self.play(g,'auto');self.assertEqual(self.hero(g).armor,7);self.check(g)

    def test_nested_casts_finish_in_stack_order(self):
        self.spell('nested',lambda c:[CastSpell(1,'driver',c.source_id),CastSpell(1,'armor',c.source_id)])
        g=self.game(('nested',));self.play(g,'nested');self.assertEqual(self.hero(g).armor,6)
        self.assertEqual([c.card_id for c in g.state.cast_history],['nested','driver','armor','armor']);self.check(g)

    def test_spell_start_reaction_can_suspend_before_payload(self):
        self.r.register_behavior('watch',lambda c:[RequestChoice(1,(ChoiceOption('x','x'),),source_id=c.source_id)])
        self.r.register_card(CardDefinition('watch','watch',CardType.MINION,health=5,triggers=(TriggerSpec('spell_cast_started','watch'),)))
        g=self.game(board=('watch',));self.play(g,'driver');self.assertEqual(self.hero(g).armor,0);self.check(g)
        c=g.state.pending_choice;g.apply(SelectChoice(1,c.id,('x',)))
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.hero(g).armor,0);self.check(g)
        nested=g.state.pending_choice;self.assertNotEqual(nested.id,c.id)
        g.apply(SelectChoice(1,nested.id,('x',)));self.assertEqual(self.hero(g).armor,3);self.check(g)

    def test_hero_death_interrupts_unfinished_casts(self):
        self.spell('lethal',lambda c:[Damage(c.state.players[2].hero_id,40,c.source_id),GainArmor(1,10)])
        self.auto('lethal');g=self.game(('auto',));self.play(g,'auto')
        self.assertTrue(all(c.interrupted for c in g.state.cast_history));self.assertEqual(self.hero(g).armor,0);self.check(g)

    def test_error_after_random_cast_rolls_back_history_rng_entities(self):
        self.spell('bad',lambda c:[CastSpell(1,'hit',c.source_id),CastSpell(1,'missing',c.source_id)])
        g=self.game(('bad',));snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),snap)

    def test_unsupported_nonspell_rejected_atomically(self):
        self.auto('body');g=self.game(('auto',));snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'auto')
        self.assertEqual(g.snapshot(),snap)

    def test_no_echo_copy_from_automatic_cast(self):
        self.spell('echo',lambda c:[GainArmor(1,1)],keywords=(Keyword.ECHO,),hand_repeat=HandRepeatSpec())
        self.auto('echo');g=self.game(('auto',));self.play(g,'auto');self.assertFalse(g.state.players[1].hand);self.check(g)

    def test_twinspell_derivative_from_effect_payload(self):
        self.spell('child',lambda c:[])
        self.spell('twin',lambda c:[GainArmor(1,1)],keywords=(Keyword.TWINSPELL,),
            hand_derivatives=(HandDerivativeSpec(Keyword.TWINSPELL,'child'),))
        self.auto('twin');g=self.game(('auto',));self.play(g,'auto')
        child=g.state.entities[self.find(g,'child')];self.assertEqual(child.origin_entity_id,g.state.cast_history[-1].source_id);self.check(g)

    def test_manathirst_uses_current_mana_crystals(self):
        self.spell('thirst',lambda c:[GainArmor(1,5 if c.spell_conditions.manathirst else 1)],manathirst=6,keywords=(Keyword.MANATHIRST,))
        self.auto('thirst');g=self.game(('auto',));self.play(g,'auto');self.assertEqual(self.hero(g).armor,5);self.check(g)

    def test_hand_only_conditions_not_invented(self):
        self.spell('conditions',lambda c:[GainArmor(1,1 if c.cast and c.play is None and
            not any((c.cast.outcast,c.cast.quickdraw,c.cast.finale)) else 99)])
        self.auto('conditions');g=self.game(('auto',));self.play(g,'auto');self.assertEqual(self.hero(g).armor,1);self.check(g)

    def test_conditional_target_declaration_inactive(self):
        self.spell('conditional',lambda c:[GainArmor(1,2)],requires_target=True,target_condition='outcast',keywords=(Keyword.OUTCAST,))
        self.auto('conditional');g=self.game(('auto',));self.play(g,'auto')
        self.assertIsNone(g.state.cast_history[-1].target_id);self.assertEqual(self.hero(g).armor,2);self.check(g)

    def test_history_filters_and_detached_state(self):
        g=self.game();self.play(g,'driver')
        self.assertEqual(len(cast_spells(g.state,1,origin='effect',turn=1)),1)
        self.assertEqual(len(cast_spells(g.state,1,before_id=2)),1)
        self.assertEqual(cast_spells(g.state,2),())
        state=g.state;state.cast_history.clear();self.assertEqual(len(g.state.cast_history),2)

    def test_corrupted_history_missing_source_rejected(self):
        g=self.game();self.play(g,'driver');snap=g.snapshot();snap['state']['cast_history'][1]['source_id']=9999
        self.reject(snap)

    def test_corrupted_hand_cast_conditions_rejected(self):
        g=self.game();self.play(g,'driver');snap=g.snapshot();snap['state']['cast_history'][0]['combo']=True
        self.reject(snap)

    def test_missing_cast_completion_marker_rejected(self):
        self.choice_spell();self.auto('choice',choices='player');g=self.game(('auto',));self.play(g,'auto')
        snap=g.snapshot()
        def remove(value):
            if isinstance(value,dict):
                for k,v in value.items():
                    if isinstance(v,list):v[:]=[x for x in v if not(isinstance(x,dict) and x.get('type','').endswith('.FinishSpellCast'))]
                    remove(v)
            elif isinstance(value,list):
                for v in value:remove(v)
        remove(snap)
        self.reject(snap)

    def test_public_view_reveals_only_executed_spell_not_deck(self):
        self.stored();g=self.game(('stored',),deck=('armor','nothing'));self.play(g,'stored')
        view=g.observe(2);encoded=json.dumps(view)
        self.assertIn('armor',encoded);self.assertNotIn('cast_history',encoded)
        self.assertNotIn('caster_id',encoded);self.assertNotIn('nothing',encoded);self.check(g)

    def test_declaration_validation(self):
        for fn in (lambda:CastSpell(True,'hit'),lambda:CastSpell(1,'hit',targeting='other'),
                   lambda:CastSpell(1,'hit',target_id=2),lambda:CastSpell(1,'hit',choices='other')):
            with self.assertRaises(ValueError):fn()

    def test_existing_arcane_bolt_uses_cast_conditions(self):
        self.spell('auto',lambda c:[CastSpell(1,'RLK_843',c.source_id,c.state.players[2].hero_id,targeting='explicit')])
        g=self.game(('auto',));self.play(g,'auto');self.assertEqual(self.hero(g,2).health,27);self.check(g)

    def test_automatic_secret_activates_without_revealing_identity(self):
        self.auto('EX1_287');g=self.game(('auto',));self.play(g,'auto')
        self.assertEqual(len(g.state.players[1].secrets),1)
        self.assertNotIn('EX1_287',json.dumps(g.observe(2)));self.assertIn('EX1_287',json.dumps(g.observe(1)));self.check(g)

    def test_duplicate_secret_cast_does_not_duplicate_active_secret(self):
        self.spell('double',lambda c:[CastSpell(1,'EX1_287',c.source_id),CastSpell(1,'EX1_287',c.source_id)])
        g=self.game(('double',));self.play(g,'double');self.assertEqual(len(g.state.players[1].secrets),1)
        self.assertEqual(len(cast_spells(g.state,1,origin='effect',successful=True)),2);self.check(g)

    def test_counterspell_does_not_counter_minion_effect_cast(self):
        self.spell('setup',lambda c:[SetSecret(2,'EX1_287')])
        self.r.register_behavior('caster',lambda c:[CastSpell(1,'armor',c.source_id)])
        self.r.register_card(CardDefinition('caster','caster',CardType.MINION,health=3,on_play='caster'))
        g=self.game(('setup','caster'));self.play(g,'setup');self.play(g,'caster')
        self.assertEqual(self.hero(g).armor,3);self.assertEqual(len(g.state.players[2].secrets),1);self.check(g)

    def test_spellburst_not_consumed_by_minion_effect_cast(self):
        self.r.register_behavior('caster',lambda c:[CastSpell(1,'armor',c.source_id)])
        self.r.register_card(CardDefinition('caster','caster',CardType.MINION,health=3,on_play='caster'))
        g=self.game(('caster',),board=('SCH_242',));self.play(g,'caster')
        self.assertEqual(len(g.state.players[1].board),2);self.assertEqual(self.hero(g).armor,3);self.check(g)

    def test_spell_damage_applies_to_automatic_spell(self):
        self.spell('auto',lambda c:[CastSpell(1,'hit',c.source_id,c.state.players[2].hero_id,targeting='explicit')])
        g=self.game(('auto',),board=('EX1_012',));self.play(g,'auto');self.assertEqual(self.hero(g,2).health,27);self.check(g)

    def test_dormant_target_is_excluded(self):
        from hs_sim.engine.dormancy import MakeDormant
        self.spell('sleep',lambda c:[MakeDormant(c.target_id,None)],requires_target=True)
        self.auto('minion_hit');g=self.game(('sleep','auto'),enemy=('body',))
        self.play(g,'sleep',self.find(g,'body','board',2));self.play(g,'auto')
        self.assertEqual(g.state.cast_history[-1].failure,'no_target');self.check(g)

    def test_immune_target_can_be_selected_but_prevents_damage(self):
        self.r.register_card(CardDefinition('immune','immune',CardType.MINION,health=5,keywords=(Keyword.IMMUNE,)))
        self.auto('minion_hit');g=self.game(('auto',),enemy=('immune',));self.play(g,'auto')
        self.assertEqual(g.state.entities[self.find(g,'immune','board',2)].health,5)
        self.assertIsNone(g.state.cast_history[-1].failure);self.check(g)

    def test_multiple_random_choices_resolve_independently(self):
        self.spell('many',lambda c:[RequestChoice(1,(
            ChoiceOption('a','a',(GainArmor(1,1),)),ChoiceOption('b','b',(GainArmor(1,3),))),source_id=c.source_id) for _ in range(3)])
        self.auto('many');g=self.game(('auto',));self.play(g,'auto')
        self.assertEqual(len([e for e in g.events if e.kind=='spell_choice_automatic']),3)
        self.assertIsNone(g.state.pending_choice);self.check(g)

    def test_opponent_choice_does_not_inherit_caster_policy(self):
        self.spell('opponent',lambda c:[RequestChoice(2,(ChoiceOption('x','x',(GainArmor(2,5),)),),source_id=c.source_id)])
        self.auto('opponent');g=self.game(('auto',));self.play(g,'auto');self.check(g)
        choice=g.state.pending_choice;self.assertEqual(choice.player_id,2)
        g.apply(SelectChoice(2,choice.id,('x',)));self.assertEqual(self.hero(g,2).armor,5);self.check(g)

    def test_automatic_multi_select_respects_cardinality(self):
        self.spell('multi',lambda c:[RequestChoice(1,tuple(ChoiceOption(str(i),str(i),(GainArmor(1,1),)) for i in range(4)),
            source_id=c.source_id,min_count=2,max_count=2)])
        self.auto('multi');g=self.game(('auto',));self.play(g,'auto');self.assertEqual(self.hero(g).armor,2);self.check(g)

    def test_resolution_budget_aborts_recursive_casts_atomically(self):
        self.spell('loop',lambda c:[CastSpell(1,'loop',c.source_id)])
        g=self.game(('loop',),rules=Ruleset(max_resolution_steps=60));snap=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g,'loop')
        self.assertEqual(g.snapshot(),snap)

    def test_stored_nonspell_rejected_atomically(self):
        self.stored();g=self.game(('stored',),deck=('body',));snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'stored')
        self.assertEqual(g.snapshot(),snap)

    def test_terminal_history_cannot_be_made_pending_without_frame(self):
        g=self.game();self.play(g,'driver');snap=g.snapshot();snap['state']['cast_history'][1]['completed']=False
        self.reject(snap)

    def test_completed_manual_spell_requires_cast_history(self):
        g=self.game();self.play(g,'driver');snap=g.snapshot();snap['state']['cast_history']=[]
        self.reject(snap)

    def test_wrong_payload_phase_in_pending_cast_rejected(self):
        self.choice_spell();self.auto('choice',choices='player');g=self.game(('auto',));self.play(g,'auto')
        for index in (0,1):
            with self.subTest(origin=index):
                snap=g.snapshot();snap['state']['cast_history'][index]['payload_started']=False
                self.reject(snap)

    def test_automatic_choice_details_remain_private(self):
        self.spell('private',lambda c:[RequestChoice(1,(
            ChoiceOption('private_a','sensitive label',(GainArmor(1,1),)),
            ChoiceOption('private_b','another label',(GainArmor(1,2),))),source_id=c.source_id)])
        self.auto('private');g=self.game(('auto',));self.play(g,'auto')
        for player in (1,2):
            view=json.dumps(g.observe(player));self.assertNotIn('private_a',view)
            self.assertNotIn('sensitive label',view);self.assertNotIn('spell_choice_automatic',view)
        self.check(g)


if __name__ == '__main__': unittest.main()
