"""Rewind checkpoints, information and retry control; provisional R-091."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, CastSpell, CostSpec, EndTurn, Game,
    Keyword, PlayCard, PlayerSetup, RewindSpec, ResolutionError, ResolutionLimitExceeded,
    Ruleset, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Damage, Destroy,
    Draw, GainArmor, GrantKeyword, RandomDamage, RequestChoice, ReturnToHand, RevealHandCard,
    Summon, Transform)
from hs_sim.engine.model import ChoicePurpose, PaymentType, Resource, SpellRepeatSpec, HandRepeatSpec, CastWhenDrawnSpec
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.secrets import SetSecret


class RewindTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.card('plain', lambda c: [])
        self.card('body', lambda c: [], kind=CardType.MINION)

    def card(self, name, behavior, *, kind=CardType.SPELL, retries=None, **kw):
        self.r.register_behavior(name, behavior)
        if retries is not None:
            kw['rewind'] = RewindSpec(retries)
            kw['keywords'] = (*kw.get('keywords', ()), Keyword.REWIND)
        if kind == CardType.MINION:
            kw.setdefault('attack', 2); kw.setdefault('health', 4)
        self.r.register_card(CardDefinition(name, name, kind, on_play=name, **kw))

    def game(self, hand=('rewind',), *, board=(), enemy=(), enemy_hand=(), deck=('plain',)*8,
             seed=319, rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01', hand=hand, board=board, deck=deck, max_mana=10, mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=('plain',)*8, max_mana=10, mana=10)),
            seed=seed), self.r, ruleset=rules)

    def hero(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id]

    def find(self, g, card='rewind', *, player=1, zone='hand'):
        return next(i for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == card)

    def play(self, g, card='rewind', target=None, position=None):
        source = self.find(g, card)
        g.apply(PlayCard(1, source, target, position))
        return source

    def choose(self, g, option='retry'):
        choice = g.state.pending_choice
        g.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def check(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot, self.r).snapshot(), snapshot)
        self.assertEqual(g.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), snapshot)

    def armor_card(self, **kw):
        self.card('rewind', lambda c: [GainArmor(1, c.rewind_attempt + 2)], retries=kw.pop('retries', 1), **kw)

    def reject(self, snapshot):
        snapshot['state_hash'] = canonical_hash({k:v for k,v in snapshot.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as raised:
            Game.from_snapshot(snapshot, self.r)
        self.assertNotIn('digest mismatch', str(raised.exception))

    def test_keep_commits_first_result(self):
        self.armor_card(cost=3); g=self.game(); self.play(g)
        self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.REWIND)
        self.assertEqual(self.hero(g).armor,2); self.check(g)
        self.choose(g,'keep'); self.assertEqual(self.hero(g).armor,2)
        self.assertIsNone(g.snapshot()['rewind_session']); self.check(g)

    def test_retry_restores_resources_and_only_one_play_and_cast(self):
        self.armor_card(cost=3); g=self.game(); self.play(g); self.choose(g)
        self.assertEqual((g.state.players[1].mana,self.hero(g).armor),(7,3))
        self.assertEqual((len(g.state.play_history),len(g.state.cast_history)),(1,1))
        self.assertEqual(len(g.history),2); self.assertIsNone(g.state.pending_choice); self.check(g)

    def test_multiple_retries_share_one_budget_and_end_automatically(self):
        self.armor_card(retries=3,cost=2); g=self.game(); self.play(g)
        for i in range(1,4):
            self.choose(g); self.assertEqual(self.hero(g).armor,i+2); self.check(g)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual(len(g.state.play_history),1)

    def test_keep_after_second_attempt_discards_unused_retries(self):
        self.armor_card(retries=3); g=self.game(); self.play(g); self.choose(g); self.choose(g,'keep')
        self.assertEqual(self.hero(g).armor,3); self.assertIsNone(g.snapshot()['rewind_session']); self.check(g)

    def test_random_stream_advances_and_replay_is_deterministic(self):
        self.card('rewind', lambda c:[RandomDamage(tuple(c.state.players[2].board),1,c.source_id)], retries=1)
        g=self.game(enemy=('body','body'),seed=4); before=g.snapshot()['rng_state']; self.play(g)
        after=g.snapshot()['rng_state']; self.assertNotEqual(before,after); self.choose(g)
        self.assertNotEqual(after,g.snapshot()['rng_state'])
        self.assertEqual(sum(g.state.entities[i].damage for i in g.state.players[2].board),1); self.check(g)

    def test_retry_can_produce_identical_random_result(self):
        self.card('rewind', lambda c:[RandomDamage((c.state.players[2].hero_id,),2,c.source_id)], retries=1)
        g=self.game(); self.play(g); self.choose(g); self.assertEqual(self.hero(g,2).health,28); self.check(g)

    def test_minion_retries_placement_and_battlecry_without_duplicate_body(self):
        self.armor_card(kind=CardType.MINION,cost=2); g=self.game(board=('body',)); source=self.play(g,position=0)
        self.choose(g); self.assertEqual(g.state.players[1].board[0],source)
        self.assertEqual(len(g.state.players[1].board),2); self.assertEqual(self.hero(g).armor,3); self.check(g)

    def test_retries_include_play_triggers(self):
        self.r.register_behavior('watch',lambda c:[GainArmor(1,5)])
        self.r.register_card(CardDefinition('watch','watch',CardType.MINION,health=3,
            triggers=(TriggerSpec('card_played','watch'),)))
        self.armor_card(); g=self.game(board=('watch',)); self.play(g); self.choose(g)
        self.assertEqual(self.hero(g).armor,8); self.check(g)

    def test_generated_entities_are_discarded_without_identity_reuse(self):
        self.card('rewind',lambda c:[AddToHand(1,'plain'),Summon(1,'body')],retries=1)
        g=self.game(); self.play(g); hand1=self.find(g,'plain'); board1=g.state.players[1].board[0]
        self.choose(g); self.assertNotIn(hand1,g.state.entities); self.assertNotIn(board1,g.state.entities)
        self.assertGreater(self.find(g,'plain'),board1); self.assertEqual(len(g.state.players[1].hand),1); self.check(g)

    def test_death_history_corpses_and_deathrattles_are_reverted(self):
        self.card('rewind',lambda c:[Destroy(c.state.players[1].board[0])],retries=1)
        self.r.register_behavior('hatch',lambda c:[Summon(1,'body'),Summon(1,'body')])
        self.r.register_card(CardDefinition('egg','egg',CardType.MINION,health=1,deathrattle='hatch'))
        g=self.game(board=('egg',)); self.play(g); self.assertEqual(len(g.state.death_history),1)
        old_id=g.state.death_history[0].id; self.choose(g)
        self.assertEqual(len(g.state.death_history),1); self.assertGreater(g.state.death_history[0].id,old_id)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],1)
        self.assertEqual(len(g.state.players[1].board),2); self.check(g)

    def test_draw_chain_rolls_back_deck_and_fatigue(self):
        self.card('rewind',lambda c:[Draw(1,2)],retries=1)
        g=self.game(deck=('plain',)); self.play(g); self.choose(g)
        self.assertEqual(len(g.state.players[1].hand),1); self.assertEqual(self.hero(g).health,29); self.check(g)

    def test_nested_choice_before_and_after_retry_saves(self):
        self.card('rewind',lambda c:[RequestChoice(1,(
            ChoiceOption('a','a',(GainArmor(1,2),)),ChoiceOption('b','b',(GainArmor(1,4),))),source_id=c.source_id)],retries=1)
        g=self.game(); self.play(g); self.check(g); self.choose(g,'a'); self.check(g)
        self.choose(g); self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.EFFECT); self.check(g)
        self.choose(g,'b'); self.assertEqual(self.hero(g).armor,4); self.check(g)

    def test_nested_enemy_choice_restores_with_correct_seat(self):
        self.card('rewind',lambda c:[RequestChoice(2,(ChoiceOption('a','a',(GainArmor(2,3),)),),source_id=c.source_id)],retries=1)
        g=self.game(); self.play(g); self.assertEqual(g.state.pending_choice.player_id,2); self.choose(g,'a')
        self.assertEqual(g.state.pending_choice.player_id,1); self.choose(g); self.check(g)
        self.choose(g,'a'); self.assertEqual(self.hero(g,2).armor,3); self.check(g)

    def test_player_port_exposes_choices_without_checkpoint_or_rng(self):
        self.armor_card(); g=self.game(); self.play(g)
        self.assertEqual(g.observe(2)['pending_choice'],{'player_id':1})
        view=json.dumps(g.observe(1)); self.assertNotIn('rewind_session',view); self.assertNotIn('rng_state',view)
        port=g.for_player(1); listing=port.legal_actions()
        action=[a for a in listing['actions'] if a['type']=='select_choice'][1]
        port.submit({'revision':listing['revision'],'action':action}); self.assertEqual(self.hero(g).armor,3); self.check(g)

    def test_logs_are_append_only_with_viewer_local_reset_boundaries(self):
        self.armor_card(); g=self.game(); cursors={p:len(g.player_events(p)) for p in (1,2)}; self.play(g)
        logs={p:g.player_events(p) for p in (1,2)}; self.choose(g)
        for p in (1,2):
            events=g.player_events(p); self.assertEqual(events[:len(logs[p])],logs[p])
            marker=next(e for e in events if e['kind']=='timeline_rewound')
            self.assertEqual(marker['rewind'],{'after':cursors[p],'attempt':1})
        self.check(g)

    def test_discarded_hand_handles_are_retired(self):
        self.card('rewind',lambda c:[AddToHand(1,'plain')],retries=1)
        g=self.game(); self.play(g); first=g.observe(1)['players'][0]['hand'][0]['ref']; self.choose(g)
        last=g.observe(1)['players'][0]['hand'][0]['ref']; self.assertNotEqual(first,last); self.check(g)

    def test_seen_opponent_identity_retained_without_disclosing_hidden_cards(self):
        self.card('rewind',lambda c:[RevealHandCard(c.state.players[2].hand[0])]
            if c.rewind_attempt==0 else [],retries=1)
        g=self.game(enemy_hand=('plain','body')); self.play(g); self.choose(g)
        hand=g.observe(1)['players'][1]['hand']; self.assertEqual(hand[0]['card_id'],'plain')
        self.assertIsNone(hand[1]['card_id']); self.check(g)

    def test_drawn_card_memory_does_not_reveal_restored_deck_position(self):
        self.card('rewind',lambda c:[Draw(1)] if c.rewind_attempt==0 else [],retries=1)
        g=self.game(deck=('body','plain')); self.play(g); self.choose(g)
        self.assertEqual(g.state.players[1].deck and len(g.state.players[1].deck),2)
        self.assertFalse(g.state.players[1].hand)
        for info in g.snapshot()['information']['players'].values():
            self.assertTrue(all(str(i) not in info['refs'] for i in g.state.players[1].deck))
        self.check(g)

    def test_retry_preserves_monotonic_choice_ids(self):
        self.armor_card(retries=3); g=self.game(); self.play(g); old=g.state.pending_choice.id; self.choose(g)
        self.assertGreater(g.state.pending_choice.id,old)
        with self.assertRaises(Exception):g.apply(SelectChoice(1,old,('retry',)))
        self.check(g)

    def test_clone_branches_do_not_share_checkpoint(self):
        self.armor_card(); g=self.game(); self.play(g); copy=g.clone(); self.choose(g,'keep'); self.choose(copy)
        self.assertEqual((self.hero(g).armor,self.hero(copy).armor),(2,3)); self.check(g); self.check(copy)

    def test_restore_mid_attempt_then_retry_matches_original(self):
        self.armor_card(retries=3); g=self.game(); self.play(g); self.choose(g)
        restored=Game.from_snapshot(g.snapshot(),self.r); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot()); self.check(restored)

    def test_countered_spell_has_no_result_choice(self):
        self.card('setup',lambda c:[SetSecret(2,'EX1_287')]); self.armor_card()
        g=self.game(('setup','rewind')); self.play(g,'setup'); self.play(g)
        self.assertIsNone(g.state.pending_choice); self.assertIsNone(g.snapshot()['rewind_session'])
        self.assertEqual(self.hero(g).armor,0); self.assertTrue(g.state.play_history[-1].countered); self.check(g)

    def test_automatic_spell_executes_once_without_rewind_choice(self):
        self.armor_card(); self.card('setup',lambda c:[CastSpell(1,'rewind',c.source_id)])
        g=self.game(('setup',)); self.play(g,'setup'); self.assertEqual(self.hero(g).armor,2)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(len(g.state.play_history),1); self.check(g)

    def test_summoned_minion_does_not_open_rewind(self):
        self.armor_card(kind=CardType.MINION); self.card('setup',lambda c:[Summon(1,'rewind')])
        g=self.game(('setup',)); self.play(g,'setup'); self.assertEqual(self.hero(g).armor,0)
        self.assertIsNone(g.state.pending_choice); self.check(g)

    def test_source_can_die_during_its_own_attempt(self):
        self.card('rewind',lambda c:[Destroy(c.source_id),GainArmor(1,c.rewind_attempt+1)],kind=CardType.MINION,retries=1)
        g=self.game(); source=self.play(g); self.choose(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD); self.assertEqual(self.hero(g).armor,2); self.check(g)

    def test_source_can_return_to_hand_during_attempt(self):
        self.card('rewind',lambda c:[ReturnToHand(c.source_id),GainArmor(1,2)],kind=CardType.MINION,retries=1)
        g=self.game(); source=self.play(g); self.choose(g)
        self.assertEqual(g.state.players[1].hand,[source]); self.assertEqual(self.hero(g).armor,2); self.check(g)

    def test_source_transform_does_not_change_captured_retry_entitlement(self):
        self.card('rewind',lambda c:[Transform(c.source_id,'body')],kind=CardType.MINION,retries=1)
        g=self.game(); source=self.play(g); self.choose(g)
        self.assertEqual(g.state.entities[source].card_id,'body'); self.assertEqual(len(g.state.players[1].board),1); self.check(g)

    def test_target_is_restored_before_reexecution(self):
        self.card('rewind',lambda c:[Damage(c.target_id,10,c.source_id)],retries=1,requires_target=True)
        g=self.game(enemy=('body',)); target=self.find(g,'body',player=2,zone='board')
        self.play(g,target=target); self.choose(g)
        self.assertEqual(len(g.state.death_history),1); self.assertEqual(g.state.death_history[0].entity_id,target); self.check(g)

    def test_terminal_attempt_discards_checkpoint_and_never_requests_retry(self):
        self.card('rewind',lambda c:[Damage(c.state.players[2].hero_id,99,c.source_id)],retries=1)
        g=self.game(); self.play(g); self.assertEqual(g.state.status,'finished')
        self.assertIsNone(g.state.pending_choice); self.assertIsNone(g.snapshot()['rewind_session']); self.check(g)

    def test_retry_can_end_match_without_dangling_work(self):
        self.card('rewind',lambda c:[Damage(c.state.players[2].hero_id,99 if c.rewind_attempt else 1,c.source_id)],retries=1)
        g=self.game(); self.play(g); self.choose(g); self.assertEqual(g.state.status,'finished'); self.check(g)

    def test_retry_error_rolls_back_to_result_choice(self):
        self.card('rewind',lambda c:[Summon(1,'missing')] if c.rewind_attempt else [GainArmor(1,2)],retries=1)
        g=self.game(); self.play(g); before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before); self.choose(g,'keep'); self.check(g)

    def test_budget_is_cumulative_across_retries(self):
        self.armor_card(retries=10); g=self.game(rules=Ruleset(max_resolution_steps=80)); self.play(g)
        count=0
        while g.state.pending_choice:
            before=g.snapshot()
            try:self.choose(g);count+=1
            except ResolutionLimitExceeded:
                self.assertEqual(g.snapshot(),before);break
        self.assertGreater(count,0); self.assertLess(count,10); self.check(g)

    def test_cost_modifier_is_consumed_once_net(self):
        self.armor_card(cost=4); self.card('setup',lambda c:[AddCostModifier(1,CostSpec(delta=-2),uses_remaining=1)])
        g=self.game(('setup','rewind')); self.play(g,'setup'); self.play(g); self.choose(g)
        self.assertEqual(g.state.players[1].mana,8); self.assertFalse(g.state.players[1].cost_modifiers); self.check(g)

    def test_alternate_payment_rolls_back_with_attempt(self):
        self.armor_card(cost=4); self.card('setup',lambda c:[AddCostModifier(1,CostSpec(payment=PaymentType.HEALTH))])
        g=self.game(('setup','rewind')); self.play(g,'setup'); self.play(g); self.choose(g)
        self.assertEqual(self.hero(g).health,26); self.assertEqual(g.state.players[1].mana,10); self.check(g)

    def test_invalid_retry_specs_and_markers_rejected(self):
        for count in (True,0,-1,1.5):
            with self.subTest(count=count),self.assertRaises(ValueError):RewindSpec(count)
        for definition in (
            CardDefinition('bad','bad',CardType.SPELL,keywords=(Keyword.REWIND,)),
            CardDefinition('bad','bad',CardType.SPELL,rewind=RewindSpec()),
            CardDefinition('bad','bad',CardType.WEAPON,keywords=(Keyword.REWIND,),rewind=RewindSpec())):
            with self.assertRaises(ValueError):self.r.register_card(definition)

    def test_bare_dynamic_keyword_is_explicitly_rejected(self):
        self.card('setup',lambda c:[GrantKeyword(c.state.players[1].board[0],Keyword.REWIND)])
        g=self.game(('setup',),board=('body',)); before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'setup')
        self.assertEqual(g.snapshot(),before)

    def test_checkpoint_missing_or_detached_is_rejected(self):
        self.armor_card(); g=self.game(); self.play(g)
        snapshot=g.snapshot(); snapshot['rewind_session']=None; self.reject(snapshot)
        snapshot=g.snapshot(); snapshot['rewind_session']['action']['entity_id']=99999; self.reject(snapshot)

    def test_checkpoint_attempt_bounds_are_validated(self):
        self.armor_card(); g=self.game(); self.play(g)
        for value in (-1,True,2):
            with self.subTest(value=value):
                snapshot=g.snapshot();snapshot['rewind_session']['attempt']=value;self.reject(snapshot)

    def test_checkpoint_fields_and_initial_choice_are_strict(self):
        self.armor_card(); g=self.game(); self.play(g)
        snapshot=g.snapshot();snapshot['rewind_session']['extra']=0;self.reject(snapshot)
        snapshot=g.snapshot();snapshot['rewind_session']['before']['pending_choice']=snapshot['state']['pending_choice'];self.reject(snapshot)

    def test_checkpoint_knowledge_and_event_cursors_are_validated(self):
        self.armor_card(); g=self.game(); self.play(g)
        snapshot=g.snapshot();snapshot['rewind_session']['event_start']=len(g.events);self.reject(snapshot)
        snapshot=g.snapshot();snapshot['rewind_session']['information']['players']['1']['next_ref']=9999;self.reject(snapshot)

    def test_nested_choice_requires_attempt_finisher(self):
        self.card('rewind',lambda c:[RequestChoice(1,(ChoiceOption('a','a'),),source_id=c.source_id)],retries=1)
        g=self.game();self.play(g);snapshot=g.snapshot()
        continuation=snapshot['resolution_frame']['fields']['continuation']['tuple']
        continuation[:]=[w for w in continuation if not w.get('type','').endswith('.OfferRewind')]
        self.reject(snapshot)

    def test_choice_requested_reaction_can_suspend_before_retry(self):
        def reaction(c):
            if dict(c.event.data).get('purpose')=='rewind':
                return [RequestChoice(2,(ChoiceOption('ack','ack',(GainArmor(2,5),)),),source_id=c.source_id)]
            return []
        self.r.register_behavior('reaction',reaction)
        self.r.register_card(CardDefinition('watch','watch',CardType.MINION,health=3,
            triggers=(TriggerSpec('choice_requested','reaction'),)))
        self.armor_card();g=self.game(board=('watch',));self.play(g);self.choose(g);self.check(g)
        self.assertEqual(g.state.pending_choice.player_id,2);self.choose(g,'ack')
        self.assertEqual(self.hero(g,2).armor,0);self.assertEqual(self.hero(g).armor,3);self.check(g)

    def test_choice_requested_reaction_can_suspend_before_keep(self):
        self.r.register_behavior('reaction',lambda c:[RequestChoice(2,(ChoiceOption('ack','ack',
            (GainArmor(2,5),)),),source_id=c.source_id)] if dict(c.event.data).get('purpose')=='rewind' else [])
        self.r.register_card(CardDefinition('watch','watch',CardType.MINION,health=3,
            triggers=(TriggerSpec('choice_requested','reaction'),)))
        self.armor_card();g=self.game(board=('watch',));self.play(g);self.choose(g,'keep');self.check(g)
        self.choose(g,'ack');self.assertEqual(self.hero(g,2).armor,5);self.check(g)

    def test_repeat_aura_is_one_rewind_attempt_with_all_iterations(self):
        self.r.register_card(CardDefinition('repeat','repeat',CardType.MINION,health=4,
            spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
        self.armor_card();g=self.game(board=('repeat',));self.play(g)
        self.assertEqual(self.hero(g).armor,4);self.choose(g)
        self.assertEqual(self.hero(g).armor,6);self.assertEqual(len(g.state.cast_history),2)
        self.assertEqual(len(g.state.spell_repeats),1);self.check(g)

    def test_echo_copy_from_discarded_attempt_does_not_accumulate(self):
        self.armor_card(keywords=(Keyword.ECHO,),hand_repeat=HandRepeatSpec())
        g=self.game();self.play(g);first=self.find(g);self.choose(g);last=self.find(g)
        self.assertNotEqual(first,last);self.assertEqual(len(g.state.players[1].hand),1)
        self.assertIsNotNone(g.state.entities[last].hand_lifetime);self.check(g)

    def test_drawn_spell_retry_does_not_leave_intermediate_casts(self):
        self.card('drawn',lambda c:[GainArmor(1,5)],keywords=(Keyword.CASTS_WHEN_DRAWN,),
            cast_when_drawn=CastWhenDrawnSpec())
        self.card('rewind',lambda c:[Draw(1)],retries=1)
        g=self.game(deck=('drawn','plain'));self.play(g);self.choose(g)
        self.assertEqual(self.hero(g).armor,5);self.assertEqual(len(g.state.cast_history),2)
        self.assertEqual(len(g.state.draw_history),2);self.check(g)

    def test_full_hand_burns_are_reverted(self):
        self.card('rewind',lambda c:[AddToHand(1,'body'),AddToHand(1,'body')],retries=1)
        g=self.game(('rewind',*('plain',)*9));self.play(g);self.choose(g)
        self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual(sum(e.card_id=='body' for e in g.state.entities.values()),2);self.check(g)

    def test_reborn_does_not_accumulate_retries(self):
        self.r.register_card(CardDefinition('reborn','reborn',CardType.MINION,health=3,keywords=(Keyword.REBORN,)))
        self.card('rewind',lambda c:[Destroy(c.state.players[1].board[0])],retries=1)
        g=self.game(board=('reborn',));self.play(g);self.choose(g)
        self.assertEqual(len(g.state.players[1].board),1)
        self.assertEqual(len(g.state.death_history),1);self.check(g)

    def test_next_manual_play_creates_independent_session(self):
        self.armor_card();g=self.game(('rewind','rewind'));self.play(g);self.choose(g)
        self.play(g);self.assertEqual(self.hero(g).armor,5);self.choose(g)
        self.assertEqual(self.hero(g).armor,6);self.assertEqual(len(g.state.play_history),2);self.check(g)

    def test_returned_source_starts_fresh_on_next_play(self):
        self.card('rewind',lambda c:[ReturnToHand(c.source_id),GainArmor(1,c.rewind_attempt+1)],
            kind=CardType.MINION,retries=1)
        g=self.game();self.play(g);self.choose(g);self.play(g);self.choose(g,'keep')
        self.assertEqual(self.hero(g).armor,3);self.check(g)

    def test_retry_restores_prior_play_conditions(self):
        self.card('rewind',lambda c:[GainArmor(1,7 if c.play.combo else 2)],retries=1)
        g=self.game();self.play(g);self.choose(g)
        self.assertEqual(self.hero(g).armor,2);self.assertEqual(g.state.play_history[0].prior_game_plays,0);self.check(g)

    def test_zero_cost_does_not_skip_retry(self):
        self.armor_card(cost=0);g=self.game();self.play(g);self.choose(g)
        self.assertEqual(g.state.players[1].mana,10);self.check(g)

    def test_first_attempt_error_is_transactional(self):
        self.card('rewind',lambda c:[AddToHand(1,'missing')],retries=1)
        g=self.game();before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_checkpoint_root_action_cannot_be_changed(self):
        self.armor_card();g=self.game();self.play(g);snapshot=g.snapshot()
        snapshot['rewind_session']['before']['action_number']=0;self.reject(snapshot)

    def test_forged_retry_count_within_spec_is_rejected(self):
        self.armor_card(retries=3);g=self.game();self.play(g);snapshot=g.snapshot()
        snapshot['rewind_session']['attempt']=1;self.reject(snapshot)

    def test_reset_marker_cannot_expose_host_event_cursor(self):
        self.armor_card();g=self.game();self.play(g);self.choose(g);snapshot=g.snapshot()
        marker=next(e for e in snapshot['information']['players']['1']['events'] if e['kind']=='timeline_rewound')
        marker['rewind']['host_event_start']=0;self.reject(snapshot)

    def test_action_during_result_choice_is_rejected_without_mutation(self):
        self.armor_card();g=self.game();self.play(g);before=g.snapshot()
        with self.assertRaises(ValueError):g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(),before)

    def test_previous_choice_commands_do_not_match_second_attempt(self):
        self.armor_card(retries=3);g=self.game();self.play(g);port=g.for_player(1);old=port.legal_actions()
        old_action=old['actions'][1];port.submit({'revision':old['revision'],'action':old_action})
        before=g.snapshot()
        result=port.submit({'revision':port.legal_actions()['revision'],'action':old_action})
        self.assertFalse(result['accepted']);self.assertEqual(result['error'],'invalid_action')
        self.assertEqual(g.snapshot(),before);self.check(g)


if __name__ == '__main__':
    unittest.main()
