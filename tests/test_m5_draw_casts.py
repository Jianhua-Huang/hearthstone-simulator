"""Draw attempts, Casts When Drawn and resumable replacement chains (R-089)."""
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, CastSpell, CastStoredSpell,
    CastWhenDrawnSpec, DrawRecord, EndTurn, Game, Keyword, PlayCard, PlayerSetup,
    ResolutionError, ResolutionLimitExceeded, Ruleset, Scenario, SelectChoice,
    SnapshotError, TriggerSpec, Zone, drawn_cards)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Draw, DrawToHandLimit,
    GainArmor, RequestChoice, Summon)
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, DrawMatching, MoveCard
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class DrawCastTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        self.r.register_card(CardDefinition('body','body',CardType.MINION,attack=1,health=3))
        self.spell('plain',lambda c:[])
        self.spell('draw',lambda c:[Draw(c.player_id,source_id=c.source_id)])
        self.spell('two',lambda c:[Draw(c.player_id,2,c.source_id)])
        self.spell('auto',lambda c:[GainArmor(c.player_id,2)],cast_when_drawn=CastWhenDrawnSpec(),cost=9)
    def spell(self,name,fn,**kw):
        if kw.get('cast_when_drawn') is not None:
            kw['keywords']=(*kw.get('keywords',()),Keyword.CASTS_WHEN_DRAWN)
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,**kw))
    def game(self,hand=('draw',),deck=('auto','plain'),enemy_deck=('plain',)*5,board=(),rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01',hand=hand,deck=deck,board=board,max_mana=10,mana=10),
            PlayerSetup('HERO_08',deck=enemy_deck,max_mana=10,mana=10)),seed=217),self.r,ruleset=rules)
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def cards(self,g,zone='hand',p=1):return [g.state.entities[i].card_id for i in getattr(g.state.players[p],zone)]
    def play(self,g,name='draw',target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        g.apply(PlayCard(1,eid,target));return eid
    def choose(self,g):
        choice=g.state.pending_choice;g.apply(SelectChoice(choice.player_id,choice.id,(choice.options[0].id,)))
    def check(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,self.r).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),snap)
    def reject(self,snap):
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as caught:Game.from_snapshot(snap,self.r)
        self.assertNotIn('digest mismatch',str(caught.exception))
    def choice(self,name='choice',*,after=None,replacement=True,policy='player'):
        self.spell(name,lambda c:[RequestChoice(c.player_id,(ChoiceOption('x','x',(GainArmor(c.player_id,3),)),),source_id=c.source_id)],
            cast_when_drawn=CastWhenDrawnSpec(replacement,after,policy))
    def blood(self):
        self.r.register_behavior('blood_after',lambda c:[AddToDeck(c.player_id,'blood',source_id=c.source_id) for _ in range(2)])
        self.spell('blood',lambda c:[Damage(c.state.players[c.player_id].hero_id,3,c.source_id)],
            cast_when_drawn=CastWhenDrawnSpec(after_draw='blood_after'))

    def test_drawn_spell_casts_original_entity_then_draws_replacement(self):
        g=self.game();eid=g.state.players[1].deck[0];self.play(g)
        self.assertEqual(self.hero(g).armor,2);self.assertEqual(self.cards(g),['plain'])
        self.assertEqual([d.outcome for d in g.state.draw_history],['cast','hand'])
        self.assertEqual(g.state.cast_history[-1].origin,'draw')
        self.assertEqual(g.state.cast_history[-1].source_id,eid)
        self.assertEqual(g.state.draw_history[0].cast_id,g.state.cast_history[-1].id);self.check(g)

    def test_cast_is_not_payment_or_hand_acquisition(self):
        g=self.game();eid=g.state.players[1].deck[0];self.play(g)
        self.assertEqual(g.state.players[1].mana,10);self.assertEqual(len(g.state.play_history),1)
        self.assertFalse(any(e.entity_id==eid for e in g.state.hand_entries));self.check(g)

    def test_contiguous_drawn_spells_chain_before_regular_card(self):
        g=self.game(deck=('auto','auto','plain','body'));self.play(g)
        self.assertEqual(self.hero(g).armor,4);self.assertEqual(self.cards(g),['plain'])
        self.assertEqual(self.cards(g,'deck'),['body'])
        self.assertEqual([d.parent_id for d in g.state.draw_history],[None,1,2]);self.check(g)

    def test_multi_draw_counts_requested_draws_plus_replacements(self):
        g=self.game(('two',),deck=('auto','plain','body'));self.play(g,'two')
        self.assertEqual(self.cards(g),['plain','body'])
        self.assertEqual([d.parent_id for d in g.state.draw_history],[None,1,None]);self.check(g)

    def test_empty_deck_records_fatigue_attempt(self):
        g=self.game(deck=());self.play(g)
        self.assertEqual(self.hero(g).health,29);row=g.state.draw_history[0]
        self.assertEqual(row.outcome,'fatigue');self.assertIsNone(row.entity_id);self.assertTrue(row.completed);self.check(g)

    def test_replacement_empty_deck_fatigues_once(self):
        g=self.game(deck=('auto',));self.play(g)
        self.assertEqual(g.state.players[1].fatigue,1)
        self.assertEqual([d.outcome for d in g.state.draw_history],['cast','fatigue']);self.check(g)

    def test_full_hand_burns_drawn_spell_without_cast_or_replacement(self):
        self.spell('fill',lambda c:[AddToHand(1,'plain'),Draw(1)])
        g=self.game(('fill',)+('plain',)*9);self.play(g,'fill')
        self.assertEqual(self.hero(g).armor,0);self.assertEqual(self.cards(g,'deck'),['plain'])
        self.assertEqual([d.outcome for d in g.state.draw_history],['burned'])
        self.assertEqual(len(g.state.cast_history),1);self.check(g)

    def test_draw_spell_can_fill_hand_and_burn_replacement(self):
        self.spell('filler',lambda c:[AddToHand(1,'plain')],cast_when_drawn=CastWhenDrawnSpec())
        g=self.game(('draw',)+('plain',)*9,deck=('filler','body'));self.play(g)
        self.assertEqual([d.outcome for d in g.state.draw_history],['cast','burned']);self.assertEqual(len(self.cards(g)),10);self.check(g)

    def test_full_hand_regular_draw_still_burns(self):
        self.spell('fill',lambda c:[AddToHand(1,'plain'),Draw(1)])
        g=self.game(('fill',)+('plain',)*9,deck=('body',));self.play(g,'fill')
        self.assertEqual(g.state.draw_history[0].outcome,'burned');self.check(g)

    def test_matching_draw_uses_unfiltered_topdeck_for_replacement(self):
        self.spell('matching',lambda c:[DrawMatching(1,query=PoolQuery(min_cost=9,max_cost=9),empty_deck='skip',selection='first')])
        g=self.game(('matching',),deck=('body','auto','plain'));self.play(g,'matching')
        self.assertEqual(self.cards(g),['body']);self.assertEqual(self.cards(g,'deck'),['plain']);self.check(g)

    def test_explicit_draw_move_uses_same_chain(self):
        self.spell('move',lambda c:[MoveCard(CardReference.capture(c.state.entities[c.state.players[1].deck[1]]),1,Zone.HAND,draw=True)])
        g=self.game(('move',),deck=('body','auto'));self.play(g,'move')
        self.assertEqual(self.cards(g),['body']);self.assertEqual(self.hero(g).armor,2);self.check(g)

    def test_regular_move_to_hand_does_not_cast(self):
        self.spell('move',lambda c:[MoveCard(CardReference.capture(c.state.entities[c.state.players[1].deck[0]]),1,Zone.HAND)])
        g=self.game(('move',));self.play(g,'move')
        self.assertEqual(self.cards(g),['auto']);self.assertFalse(g.state.draw_history);self.assertEqual(self.hero(g).armor,0);self.check(g)

    def test_copy_to_hand_does_not_cast(self):
        self.spell('copy',lambda c:[CopyCard(CardReference.capture(c.state.entities[c.state.players[1].deck[0]]),1)])
        g=self.game(('copy',));self.play(g,'copy')
        self.assertEqual(self.cards(g),['auto']);self.assertFalse(g.state.draw_history);self.check(g)

    def test_generated_to_hand_does_not_cast(self):
        self.spell('create',lambda c:[AddToHand(1,'auto')]);g=self.game(('create',));self.play(g,'create')
        self.assertEqual(self.cards(g),['auto']);self.assertEqual(self.hero(g).armor,0);self.assertFalse(g.state.draw_history)

    def test_manually_played_draw_marker_does_not_replace(self):
        g=self.game(('auto',),deck=('body',));self.play(g,'auto')
        self.assertEqual(g.state.players[1].mana,1);self.assertFalse(g.state.draw_history)
        self.assertEqual(self.cards(g,'deck'),['body']);self.check(g)

    def test_generic_automatic_cast_does_not_replace(self):
        self.spell('generic',lambda c:[CastSpell(1,'auto',c.source_id)])
        g=self.game(('generic',),deck=('body',));self.play(g,'generic')
        self.assertEqual(self.hero(g).armor,2);self.assertFalse(g.state.draw_history);self.check(g)

    def test_stored_automatic_cast_is_not_a_draw(self):
        self.spell('stored',lambda c:[CastStoredSpell(CardReference.capture(c.state.entities[c.state.players[1].deck[0]]),1,c.source_id)])
        g=self.game(('stored',));self.play(g,'stored');self.assertFalse(g.state.draw_history)
        self.assertEqual(self.cards(g,'deck'),['plain']);self.check(g)

    def test_blood_shuffles_after_replacement_not_before(self):
        self.blood();g=self.game(deck=('blood','body'));self.play(g)
        self.assertEqual(self.hero(g).health,27);self.assertEqual(self.cards(g),['body'])
        self.assertEqual(self.cards(g,'deck'),['blood','blood']);self.check(g)

    def test_only_blood_finishes_chain_with_fatigue_before_shuffling(self):
        self.blood();g=self.game(deck=('blood','blood'));self.play(g)
        self.assertEqual(self.hero(g).health,23);self.assertEqual(g.state.players[1].fatigue,1)
        self.assertEqual(self.cards(g,'deck'),['blood']*4);self.check(g)

    def test_after_draw_callbacks_unwind_inner_before_outer(self):
        self.r.register_behavior('append',lambda c:[AddToDeck(1,c.draw.card_id,position='bottom')]
            if c.cast.origin=='draw' and c.cast.completed else [])
        for name in ('first','second'):
            self.spell(name,lambda c:[],cast_when_drawn=CastWhenDrawnSpec(after_draw='append'))
        g=self.game(deck=('first','second','body'));self.play(g)
        self.assertEqual(self.cards(g,'deck'),['second','first']);self.check(g)

    def test_declaration_can_disable_replacement_explicitly(self):
        self.spell('single',lambda c:[GainArmor(1,2)],cast_when_drawn=CastWhenDrawnSpec(replacement=False))
        g=self.game(deck=('single','body'));self.play(g)
        self.assertEqual(self.cards(g,'deck'),['body']);self.assertEqual(len(g.state.draw_history),1);self.check(g)

    def test_fizzled_drawn_spell_still_replaces(self):
        from hs_sim.engine import TargetSpec
        self.spell('target',lambda c:[Damage(c.target_id,1,c.source_id)],cast_when_drawn=CastWhenDrawnSpec(),targeting=TargetSpec(kinds=(CardType.MINION,)))
        g=self.game(deck=('target','body'));self.play(g)
        self.assertEqual(g.state.cast_history[-1].failure,'no_target');self.assertEqual(self.cards(g),['body']);self.check(g)

    def test_choice_during_cast_restores_parent_draw_and_replacement(self):
        self.choice();g=self.game(deck=('choice','body'));self.play(g);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.cards(g),['body']);self.check(g)

    def test_random_choice_cast_does_not_suspend(self):
        self.choice(policy='random');g=self.game(deck=('choice','body'));self.play(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.hero(g).armor,3);self.check(g)

    def test_choice_in_after_draw_waits_until_replacement_finishes(self):
        self.r.register_behavior('after',lambda c:[RequestChoice(1,(ChoiceOption('x','x',(AddToDeck(1,'plain'),)),),source_id=c.source_id)])
        self.choice(after='after');g=self.game(deck=('choice','body'));self.play(g);self.choose(g)
        self.assertEqual(self.cards(g),['body']);self.assertEqual(g.state.draw_history[0].phase,'after_draw');self.check(g)
        self.choose(g);self.assertEqual(self.cards(g,'deck'),['plain']);self.check(g)

    def test_random_after_draw_choice_uses_same_policy(self):
        self.r.register_behavior('after',lambda c:[RequestChoice(1,(ChoiceOption('x','x',(GainArmor(1,4),)),),source_id=c.source_id)])
        self.choice(after='after',policy='random');g=self.game(deck=('choice','body'));self.play(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.hero(g).armor,7);self.check(g)

    def test_draw_trigger_can_suspend_before_cast(self):
        self.r.register_behavior('watch',lambda c:[RequestChoice(1,(ChoiceOption('x','x'),),source_id=c.source_id)] if c.draw.outcome=='cast' else [])
        self.r.register_card(CardDefinition('watch','watch',CardType.MINION,health=4,triggers=(TriggerSpec('card_drawn','watch'),)))
        g=self.game(board=('watch',));self.play(g);self.assertEqual(self.hero(g).armor,0);self.check(g)
        self.choose(g);self.assertEqual(self.hero(g).armor,2);self.check(g)

    def test_nested_regular_draw_inside_payload_has_independent_root(self):
        self.spell('nested',lambda c:[Draw(1)],cast_when_drawn=CastWhenDrawnSpec())
        g=self.game(deck=('nested','plain','body'));self.play(g)
        self.assertEqual(self.cards(g),['plain','body'])
        self.assertEqual([d.parent_id for d in g.state.draw_history],[None,None,1]);self.check(g)

    def test_lethal_drawn_spell_stops_replacement_and_after_draw(self):
        self.r.register_behavior('after',lambda c:[AddToDeck(1,'plain')])
        self.spell('lethal',lambda c:[Damage(c.state.players[1].hero_id,40,c.source_id)],cast_when_drawn=CastWhenDrawnSpec(after_draw='after'))
        g=self.game(deck=('lethal','body'));self.play(g)
        self.assertEqual(self.cards(g,'deck'),['body']);self.assertTrue(g.state.draw_history[0].interrupted);self.check(g)

    def test_error_in_after_draw_rolls_back_entire_chain(self):
        self.r.register_behavior('bad',lambda c:[AddToDeck(1,'missing')])
        self.spell('badcast',lambda c:[GainArmor(1,2)],cast_when_drawn=CastWhenDrawnSpec(after_draw='bad'))
        g=self.game(deck=('badcast','body'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_draw_history_query_filters(self):
        g=self.game();self.play(g)
        self.assertEqual(len(drawn_cards(g.state,1)),2);self.assertEqual(len(drawn_cards(g.state,1,outcome='cast',completed=True)),1)
        self.assertEqual(drawn_cards(g.state,2),());self.assertEqual(drawn_cards(g.state,1,turn=2),())

    def test_invalid_parent_link_rejected_after_digest_recomputed(self):
        g=self.game();self.play(g);snap=g.snapshot();snap['state']['draw_history'][1]['parent_id']=None;self.reject(snap)

    def test_missing_cast_link_rejected(self):
        g=self.game();self.play(g);snap=g.snapshot();snap['state']['draw_history'][0]['cast_id']=99999;self.reject(snap)

    def test_pending_draw_missing_finish_marker_rejected(self):
        self.choice();g=self.game(deck=('choice','body'));self.play(g);snap=g.snapshot()
        values=snap['resolution_frame']['fields']['continuation']['tuple']
        values[:]=[v for v in values if not v.get('type','').endswith('.FinishDraw')];self.reject(snap)

    def test_unknown_after_draw_behavior_rejected_at_registry_freeze(self):
        self.spell('bad',lambda c:[],cast_when_drawn=CastWhenDrawnSpec(after_draw='missing'))
        with self.assertRaises(ValueError):self.r.freeze()

    def test_draw_marker_requires_matching_typed_spell_declaration(self):
        for card in (CardDefinition('bad','bad',CardType.SPELL,keywords=(Keyword.CASTS_WHEN_DRAWN,)),
                     CardDefinition('bad','bad',CardType.MINION,health=1,keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())):
            with self.assertRaises(ValueError):self.r.register_card(card)

    def test_public_view_reveals_drawn_spell_but_not_next_hidden_card(self):
        self.choice();g=self.game(deck=('choice','body'));self.play(g)
        view=json.dumps(g.observe(2));self.assertIn('choice',view);self.assertNotIn('body',view)
        self.assertNotIn('draw_history',view);self.assertNotIn('parent_id',view);self.check(g)

    def test_draw_to_hand_limit_counts_replacements(self):
        self.spell('fill',lambda c:[DrawToHandLimit(1)])
        g=self.game(('fill',),deck=('auto','auto')+('plain',)*10);self.play(g,'fill')
        self.assertEqual(len(self.cards(g)),10);self.assertEqual(self.hero(g).armor,4)
        self.assertEqual(len(g.state.draw_history),12);self.check(g)

    def test_zero_draw_leaves_history_and_rng_unchanged(self):
        self.spell('zero',lambda c:[Draw(1,0)]);g=self.game(('zero',));rng=g.snapshot()['rng_state'];self.play(g,'zero')
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertFalse(g.state.draw_history)

    def test_topdeck_replacement_preserves_fixed_rng(self):
        g=self.game();rng=g.snapshot()['rng_state'];self.play(g)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.check(g)

    def test_stale_targeted_draw_does_not_create_attempt(self):
        def fn(c):
            ref=CardReference.capture(c.state.entities[c.state.players[1].deck[0]])
            return [MoveCard(ref,1,Zone.HAND),MoveCard(ref,1,Zone.HAND,draw=True)]
        self.spell('stale',fn);g=self.game(('stale',));self.play(g,'stale')
        self.assertEqual(self.cards(g),['auto']);self.assertFalse(g.state.draw_history);self.check(g)

    def test_lethal_replacement_fatigue_stops_after_draw_callbacks(self):
        self.r.register_behavior('after',lambda c:[AddToDeck(1,'plain')])
        self.spell('danger',lambda c:[Damage(c.state.players[1].hero_id,29,c.source_id)],cast_when_drawn=CastWhenDrawnSpec(after_draw='after'))
        g=self.game(deck=('danger',));self.play(g)
        self.assertFalse(self.cards(g,'deck'));self.assertTrue(all(d.interrupted for d in g.state.draw_history));self.check(g)

    def test_multiple_blood_requests_shuffle_between_requests(self):
        self.blood();g=self.game(('two',),deck=('blood',));self.play(g,'two')
        self.assertEqual(self.hero(g).health,18);self.assertEqual(g.state.players[1].fatigue,2)
        self.assertEqual(self.cards(g,'deck'),['blood']*4);self.check(g)

    def test_nested_draw_cast_choice_restores_both_chains(self):
        self.choice();self.spell('nested',lambda c:[Draw(1)],cast_when_drawn=CastWhenDrawnSpec())
        g=self.game(deck=('nested','choice','plain','body'));self.play(g);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.cards(g),['plain','body']);self.check(g)

    def test_independent_draw_trigger_choice_is_not_randomized(self):
        self.r.register_behavior('watch',lambda c:[RequestChoice(1,(ChoiceOption('x','x'),),source_id=c.source_id)])
        self.r.register_card(CardDefinition('watch','watch',CardType.MINION,health=3,triggers=(TriggerSpec('card_drawn','watch'),)))
        g=self.game(board=('watch',));self.play(g);self.assertIsNotNone(g.state.pending_choice);self.check(g)
        self.choose(g);self.assertIsNotNone(g.state.pending_choice);self.check(g)
        self.choose(g);self.assertIsNone(g.state.pending_choice);self.check(g)

    def test_effect_loop_hits_budget_and_rolls_back(self):
        self.spell('loop',lambda c:[AddToDeck(1,'loop',position='top')],cast_when_drawn=CastWhenDrawnSpec())
        g=self.game(deck=('loop',),rules=Ruleset(max_resolution_steps=80));before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_turn_start_draw_uses_same_contract(self):
        g=self.game(hand=(),enemy_deck=('auto','plain'));g.apply(EndTurn(1))
        self.assertEqual(self.hero(g,2).armor,2);self.assertEqual(self.cards(g,p=2),['plain'])
        self.assertEqual([d.player_id for d in g.state.draw_history],[2,2]);self.assertFalse(g.state.play_history);self.check(g)

    def test_drawing_for_opponent_keeps_draw_player_and_owner(self):
        self.spell('other',lambda c:[Draw(2,source_id=c.source_id)])
        g=self.game(('other',),enemy_deck=('auto','plain'));source=self.play(g,'other')
        d=g.state.draw_history[0];self.assertEqual((d.player_id,d.source_id),(2,source))
        self.assertEqual(self.hero(g,2).armor,2);self.assertEqual(g.state.entities[d.entity_id].owner,2);self.check(g)

    def test_player_port_choice_and_restore(self):
        self.choice();g=self.game(deck=('choice','body'));port=g.for_player(1);listing=port.legal_actions()
        action=next(a for a in listing['actions'] if a['type']=='play_card')
        port.submit({'revision':listing['revision'],'action':action});self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):
            port=match.for_player(1);listing=port.legal_actions();action=next(a for a in listing['actions'] if a['type']=='select_choice')
            port.submit({'revision':listing['revision'],'action':action})
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_echo_drawn_spell_does_not_create_echo_copy(self):
        from hs_sim.engine import HandRepeatSpec
        self.spell('echo',lambda c:[],keywords=(Keyword.ECHO,),hand_repeat=HandRepeatSpec(),cast_when_drawn=CastWhenDrawnSpec())
        g=self.game(deck=('echo','body'));self.play(g);self.assertEqual(self.cards(g),['body']);self.check(g)

    def test_twinspell_drawn_spell_creates_terminal_form_then_replaces(self):
        from hs_sim.engine import HandDerivativeSpec
        self.spell('child',lambda c:[])
        self.spell('twin',lambda c:[],keywords=(Keyword.TWINSPELL,),
            hand_derivatives=(HandDerivativeSpec(Keyword.TWINSPELL,'child'),),cast_when_drawn=CastWhenDrawnSpec())
        g=self.game(deck=('twin','body'));self.play(g);self.assertEqual(self.cards(g),['child','body']);self.check(g)

    def test_pending_draw_phase_cannot_skip_cast(self):
        self.choice();g=self.game(deck=('choice','body'));self.play(g);snap=g.snapshot()
        snap['state']['draw_history'][0]['phase']='after_draw';self.reject(snap)

    def test_cast_draw_backreference_cannot_be_removed(self):
        g=self.game();self.play(g);snap=g.snapshot();snap['state']['cast_history'][-1]['draw_id']=None;self.reject(snap)

    def test_replacement_marker_cannot_be_reordered(self):
        self.choice();g=self.game(deck=('choice','body'));self.play(g);snap=g.snapshot()
        values=snap['resolution_frame']['fields']['continuation']['tuple']
        values.reverse();self.reject(snap)

    def test_draw_spec_rejects_invalid_types(self):
        for kwargs in ({'replacement':1},{'after_draw':''},{'choices':'unknown'}):
            with self.assertRaises(ValueError):CastWhenDrawnSpec(**kwargs)

    def test_opening_deal_mulligan_and_first_turn_are_separate(self):
        from hs_sim.engine import CardClass, CardMetadata, Rarity
        from hs_sim.engine.construction import DeckPolicy, DeckSpec, MatchSetup
        self.spell('opening',lambda c:[GainArmor(c.player_id,1)],
            metadata=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON),cast_when_drawn=CastWhenDrawnSpec())
        policy=DeckPolicy('draw-test','local-2026-09-23','experimental',('opening',),deck_size=10,max_copies=10)
        decks=(DeckSpec('HERO_01',self.r.card('HERO_01').initial_hero_power,CardClass.WARRIOR,('opening',)*10),
               DeckSpec('HERO_08',self.r.card('HERO_08').initial_hero_power,CardClass.MAGE,('opening',)*10))
        g=Game.from_decks(MatchSetup(decks,policy,'GAME_005',seed=19,first_player=1),self.r)
        self.assertFalse(g.state.draw_history);self.assertFalse(g.state.cast_history);self.check(g)
        first=g.state.pending_choice;g.apply(SelectChoice(1,first.id,(first.options[0].id,)))
        self.assertFalse(g.state.draw_history);self.check(g)
        second=g.state.pending_choice;g.apply(SelectChoice(2,second.id,()))
        self.assertEqual(self.hero(g).armor,6);self.assertEqual(g.state.players[1].fatigue,1)
        self.assertEqual(len(g.state.draw_history),8);self.assertFalse(g.state.play_history);self.check(g)

    def test_drawn_secret_identity_remains_private(self):
        from dataclasses import replace
        base=self.r.card('EX1_287')
        self.r.register_card(replace(base,id='draw_secret',keywords=(*base.keywords,Keyword.CASTS_WHEN_DRAWN),
            cast_when_drawn=CastWhenDrawnSpec()))
        g=self.game(deck=('draw_secret','body'));self.play(g)
        self.assertEqual(len(g.state.players[1].secrets),1)
        self.assertNotIn('draw_secret',json.dumps(g.observe(2)))
        self.assertIn('draw_secret',json.dumps(g.observe(1)));self.check(g)

    def trade(self,on_use=None):
        from hs_sim.engine import HandActionSpec
        self.spell('trade',lambda c:[],hand_actions=(HandActionSpec('trade','trade',1,on_use=on_use),))

    def test_trade_completes_ordinary_draw_record(self):
        from hs_sim.engine import UseHandAction
        self.trade();g=self.game(('trade',),deck=('plain',));eid=g.state.players[1].hand[0]
        g.apply(UseHandAction(1,eid,'trade'))
        self.assertEqual(self.cards(g),['plain']);self.assertEqual(g.state.draw_history[0].source_id,eid)
        self.assertTrue(g.state.draw_history[0].completed);self.assertFalse(g.state.play_history);self.check(g)

    def test_trade_draw_chain_resumes_before_own_callback(self):
        from hs_sim.engine import UseHandAction
        self.r.register_behavior('traded',lambda c:[GainArmor(1,10)])
        self.trade('traded');self.choice();g=self.game(('trade',),deck=('choice',))
        eid=g.state.players[1].hand[0];g.apply(UseHandAction(1,eid,'trade'))
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.hero(g).armor,0);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.cards(g),['trade'])
        self.assertEqual(self.hero(g).armor,13);self.assertTrue(all(d.completed for d in g.state.draw_history));self.check(g)

    def test_lethal_traded_spell_stops_replacement_and_trade_callback(self):
        from hs_sim.engine import UseHandAction
        self.r.register_behavior('traded',lambda c:[GainArmor(1,10)])
        self.trade('traded');self.spell('lethal',lambda c:[Damage(c.state.players[1].hero_id,30,c.source_id)],cast_when_drawn=CastWhenDrawnSpec())
        g=self.game(('trade',),deck=('lethal',));g.apply(UseHandAction(1,g.state.players[1].hand[0],'trade'))
        self.assertEqual(self.cards(g,'deck'),['trade']);self.assertEqual(self.hero(g).armor,0)
        self.assertTrue(g.state.draw_history[0].interrupted);self.assertTrue(any(e.kind=='card_traded' for e in g.events));self.check(g)


if __name__=='__main__':unittest.main()
