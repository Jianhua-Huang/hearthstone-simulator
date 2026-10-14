"""Repeated payloads, one paid play, live aura scope and resumable choices."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (AbilityInstance, CardDefinition, CardType, CardClass, CardMetadata,
    DamageKind, EndTurn, Game, GenerationContext, GrantSpellRepeatAura, Keyword,
    LimitedTriggerSpec, PlayCard, PlayerSetup, ResolutionError, ResolutionLimitExceeded,
    Ruleset, Scenario, SelectChoice, SnapshotError, SpellRepeatSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, Destroy, Draw, GainArmor, GrantSpellDamage, RequestChoice, ReturnToHand,
    Silence, Summon, Transform, ReplaceHero, RandomDamage)
from hs_sim.engine.dormancy import MakeDormant, AwakenMinion
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.representative import build_registry, HERALD_POOL_ID
from hs_sim.engine.pools import DiscoverFromPool, PoolQuery
from hs_sim.engine.replay import build_replay, replay


class SpellRepeatTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.minion('plain', attack=2, health=8)
        self.minion('repeat', health=5, spell_repeats=(SpellRepeatSpec(),))
        self.minion('any', health=5, spell_repeats=(SpellRepeatSpec(class_mode='any'),))
        self.spell('hit', lambda c: [Damage(c.target_id, 2, c.source_id, DamageKind.SPELL)], requires_target=True)
        self.spell('noop', lambda c: [])
        for name, fn in (
            ('silence', lambda c: [Silence(c.target_id)]),
            ('bounce', lambda c: [ReturnToHand(c.target_id)]),
            ('kill', lambda c: [Destroy(c.target_id)]),
            ('transform', lambda c: [Transform(c.target_id, 'plain')]),
            ('sleep', lambda c: [MakeDormant(c.target_id, None)]),
            ('wake', lambda c: [AwakenMinion(c.target_id)]),
            ('steal', lambda c: [ChangeControl(c.target_id, 2)]),
            ('copy', lambda c: [CopyMinion(c.target_id, c.player_id)]),
            ('base_copy', lambda c: [CopyMinion(c.target_id, c.player_id, mode='base')]),
        ):
            self.spell(name, fn, cls=CardClass.WARRIOR, requires_target=True)

    def minion(self, name, **kw):
        self.r.register_card(CardDefinition(name, name, CardType.MINION, **kw))

    def spell(self, name, fn, cls=CardClass.MAGE, **kw):
        self.r.register_behavior(name, fn)
        meta = None if cls is None else CardMetadata(False, cls if isinstance(cls, tuple) else (cls,), None)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=meta, **kw))

    def game(self, hand=(), board=('repeat',), enemy=(), enemy_hand=(), hero='HERO_01', rules=None, context=True):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, deck=('plain',)*16, max_mana=10, mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=('plain',)*16, max_mana=10, mana=10)),
            seed=173, generation_context=GenerationContext('local-2026-09-23', 'experimental') if context else None),
            self.r, ruleset=rules)

    def play(self, g, name, target=None, branch=None):
        p = g.state.active_player
        i = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == name)
        g.apply(PlayCard(p, i, target, branch_id=branch)); return i

    def hero(self, g, p=1): return g.state.entities[g.state.players[p].hero_id]
    def board(self, g, p=1): return [g.state.entities[i] for i in g.state.players[p].board]
    def events(self, g, kind): return [e for e in g.events if e.kind == kind]
    def choose(self, g, option):
        c = g.state.pending_choice; g.apply(SelectChoice(c.player_id, c.id, (option,)))
    def check(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot, self.r).snapshot(), snapshot)
        self.assertEqual(g.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), snapshot)

    def test_fireball_twice_one_payment_one_play(self):
        g = self.game(hand=('CS2_029',)); self.play(g, 'CS2_029', self.hero(g, 2).id)
        self.assertEqual(self.hero(g, 2).health, 18)
        self.assertEqual(g.state.players[1].mana, 6)
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual(len(self.events(g, 'card_committed')), 1)
        self.assertEqual(len(self.events(g, 'card_played')), 1)
        self.assertEqual((g.state.spell_repeats[0].completed, g.state.spell_repeats[0].finished), (2, True))
        self.check(g)

    def test_same_class_spell_once(self):
        g = self.game(hand=('hit',), hero='HERO_08'); self.play(g, 'hit', self.hero(g, 2).id)
        self.assertEqual(self.hero(g, 2).health, 28); self.assertFalse(g.state.spell_repeats)

    def test_neutral_spell_excluded(self):
        self.spell('neutral', lambda c: [GainArmor(1, 2)], cls=CardClass.NEUTRAL)
        g = self.game(hand=('neutral',)); self.play(g, 'neutral')
        self.assertEqual(self.hero(g).armor, 2); self.assertFalse(g.state.spell_repeats)

    def test_shared_current_multiclass_excluded(self):
        self.spell('dual', lambda c: [GainArmor(1, 2)], cls=(CardClass.WARRIOR, CardClass.MAGE))
        g = self.game(hand=('dual',)); self.play(g, 'dual'); self.assertEqual(self.hero(g).armor, 2)

    def test_other_multiclass_included(self):
        self.spell('dual', lambda c: [GainArmor(1, 2)], cls=(CardClass.ROGUE, CardClass.MAGE))
        g = self.game(hand=('dual',)); self.play(g, 'dual'); self.assertEqual(self.hero(g).armor, 4)

    def test_unknown_spell_metadata_rejected_atomically(self):
        self.spell('unknown', lambda c: [GainArmor(1, 2)], cls=None)
        g = self.game(hand=('unknown',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'unknown')
        self.assertEqual(g.snapshot(), before)

    def test_unknown_hero_class_rejected_atomically(self):
        g = self.game(hand=('noop',), hero='test.hero'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'noop')
        self.assertEqual(g.snapshot(), before)

    def test_any_scope_needs_no_class_metadata(self):
        self.spell('unknown', lambda c: [GainArmor(1, 2)], cls=None)
        g = self.game(hand=('unknown',), board=('any',), hero='test.hero')
        self.play(g, 'unknown'); self.assertEqual(self.hero(g).armor, 4); self.check(g)

    def test_multiple_cast_twice_auras_do_not_multiply(self):
        g = self.game(hand=('hit',), board=('repeat', 'repeat', 'any'))
        self.play(g, 'hit', self.hero(g, 2).id); self.assertEqual(self.hero(g, 2).health, 26)

    def test_larger_declared_count_uses_max(self):
        self.minion('triple', health=5, spell_repeats=(SpellRepeatSpec(3),))
        g = self.game(hand=('hit',), board=('repeat', 'triple'))
        self.play(g, 'hit', self.hero(g, 2).id); self.assertEqual(self.hero(g, 2).health, 24); self.check(g)

    def test_hostile_aura_does_not_repeat(self):
        g = self.game(hand=('hit',), board=(), enemy=('repeat',))
        self.play(g, 'hit', self.hero(g, 2).id); self.assertEqual(self.hero(g, 2).health, 28)

    def test_silence_source_stops_later_repeats(self):
        g = self.game(hand=('silence', 'hit')); self.play(g, 'silence', self.board(g)[0].id)
        self.play(g, 'hit', self.hero(g, 2).id); self.assertEqual(self.hero(g, 2).health, 28); self.check(g)

    def test_bounce_resets_aura_until_replayed(self):
        g = self.game(hand=('bounce', 'hit', 'hit')); self.play(g, 'bounce', self.board(g)[0].id)
        self.play(g, 'hit', self.hero(g, 2).id); self.play(g, 'repeat'); self.play(g, 'hit', self.hero(g, 2).id)
        self.assertEqual(self.hero(g, 2).health, 24); self.check(g)

    def test_transform_removes_repeat_source(self):
        g = self.game(hand=('transform', 'hit')); self.play(g, 'transform', self.board(g)[0].id)
        self.play(g, 'hit', self.hero(g, 2).id); self.assertEqual(self.hero(g, 2).health, 28)

    def test_dormancy_and_awaken_gate_aura(self):
        self.spell('awake', lambda c: [AwakenMinion(c.state.players[1].board[0])], cls=CardClass.WARRIOR)
        g = self.game(hand=('sleep', 'hit', 'awake', 'hit')); i = self.board(g)[0].id
        self.play(g, 'sleep', i); self.play(g, 'hit', self.hero(g, 2).id)
        self.assertEqual(self.hero(g, 2).health, 28)
        self.play(g, 'awake'); self.play(g, 'hit', self.hero(g, 2).id)
        self.assertEqual(self.hero(g, 2).health, 24); self.check(g)

    def test_control_changes_beneficiary(self):
        g = self.game(hand=('steal', 'hit'), enemy_hand=('CS2_009',), enemy=('plain',))
        self.play(g, 'steal', self.board(g)[0].id); self.play(g, 'hit', self.hero(g, 2).id)
        self.assertEqual(self.hero(g, 2).health, 28)
        g.apply(EndTurn(1)); self.play(g, 'CS2_009', self.board(g, 2)[0].id)
        self.assertEqual(self.board(g, 2)[0].attack, 6); self.check(g)

    def test_current_copy_of_silenced_source_stays_silenced(self):
        g = self.game(hand=('silence', 'copy', 'hit')); i = self.board(g)[0].id
        self.play(g, 'silence', i); self.play(g, 'copy', i); self.play(g, 'hit', self.hero(g, 2).id)
        self.assertEqual(self.hero(g, 2).health, 28); self.check(g)

    def test_base_copy_restores_printed_aura(self):
        g = self.game(hand=('silence', 'base_copy', 'hit')); i = self.board(g)[0].id
        self.play(g, 'silence', i); self.play(g, 'base_copy', i); self.play(g, 'hit', self.hero(g, 2).id)
        self.assertEqual(self.hero(g, 2).health, 26); self.check(g)

    def test_dynamic_grant_to_silenced_minion_and_expiry(self):
        self.spell('grant', lambda c: [GrantSpellRepeatAura(c.target_id, SpellRepeatSpec(), c.source_id, c.state.turn)],
                   cls=CardClass.WARRIOR, requires_target=True)
        g = self.game(board=('plain',), hand=('silence', 'grant', 'hit', 'hit')); i = self.board(g)[0].id
        self.play(g, 'silence', i); self.play(g, 'grant', i); self.play(g, 'hit', self.hero(g, 2).id)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g, 'hit', self.hero(g, 2).id)
        self.assertEqual(self.hero(g, 2).health, 24); self.check(g)

    def test_quota_survives_source_killed_by_first_iteration(self):
        self.spell('blast', lambda c: [Destroy(c.state.players[1].board[0]), GainArmor(1, 2)])
        g = self.game(hand=('blast',)); self.play(g, 'blast')
        self.assertEqual(self.hero(g).armor, 4); self.assertFalse(self.board(g)); self.check(g)

    def test_silencing_aura_during_first_iteration_does_not_cancel_second(self):
        self.spell('off', lambda c: [Silence(c.state.players[1].board[0]), GainArmor(1, 2)])
        g = self.game(hand=('off',)); self.play(g, 'off'); self.assertEqual(self.hero(g).armor, 4)

    def test_new_aura_summoned_by_single_cast_does_not_repeat_it(self):
        self.spell('make', lambda c: [Summon(1, 'repeat'), GainArmor(1, 2)])
        g = self.game(hand=('make',), board=()); self.play(g, 'make')
        self.assertEqual(self.hero(g).armor, 2); self.assertFalse(g.state.spell_repeats)

    def test_current_hero_class_is_read_before_each_play(self):
        self.spell('replace_hero', lambda c: [ReplaceHero(1, 'HERO_08')], cls=CardClass.WARRIOR)
        g = self.game(hand=('hit', 'replace_hero', 'hit'))
        self.play(g, 'hit', self.hero(g, 2).id); self.play(g, 'replace_hero'); self.play(g, 'hit', self.hero(g, 2).id)
        self.assertEqual(self.hero(g, 2).health, 24); self.check(g)

    def test_deathrattle_and_reborn_wait_until_both_iterations(self):
        self.spell('sweep', lambda c: [Damage(e.id, 2, c.source_id, DamageKind.SPELL)
                   for e in c.state.entities.values() if e.zone == Zone.BOARD and e.controller == 2])
        g = self.game(hand=('sweep',), enemy=('FP1_007', 'ULD_205')); self.play(g, 'sweep')
        self.assertEqual(sorted(e.card_id for e in self.board(g, 2)), ['FP1_007t', 'ULD_205'])
        self.assertEqual(next(e.health for e in self.board(g, 2) if e.card_id == 'ULD_205'), 1)
        damages = self.events(g, 'damage_dealt'); deaths = self.events(g, 'minion_died')
        self.assertLess(max(e.sequence for e in damages), min(e.sequence for e in deaths)); self.check(g)

    def test_same_dead_target_does_not_prevent_independent_draw(self):
        self.spell('naturalize', lambda c: [Destroy(c.target_id), Draw(2, 2)], requires_target=True)
        g = self.game(hand=('naturalize',), enemy=('plain',)); i = self.board(g, 2)[0].id
        self.play(g, 'naturalize', i)
        self.assertEqual(len(g.state.players[2].hand), 4); self.assertEqual(len(g.state.death_history), 1); self.check(g)

    def test_bounced_target_second_effect_is_stale_draw_still_runs(self):
        self.spell('return_draw', lambda c: [ReturnToHand(c.target_id), Draw(1)], requires_target=True)
        g = self.game(hand=('return_draw',), enemy=('plain',)); self.play(g, 'return_draw', self.board(g, 2)[0].id)
        self.assertEqual(len(g.state.players[1].hand), 2); self.assertEqual(len(g.state.players[2].hand), 1); self.check(g)

    def test_fresh_second_context_sees_new_spell_damage(self):
        self.spell('growing', lambda c: [Damage(c.target_id, len(c.state.players[1].hand)+1, c.source_id, DamageKind.SPELL),
                   GrantSpellDamage(c.state.players[1].board[0], 1), Draw(1)], requires_target=True)
        g = self.game(hand=('growing',)); self.play(g, 'growing', self.hero(g, 2).id)
        self.assertEqual(self.hero(g, 2).health, 26); self.check(g)  # 1 then (2 + 1).

    def test_counterspell_prevents_every_iteration(self):
        self.spell('arm', lambda c: [SetSecret(2, 'EX1_287')], cls=CardClass.WARRIOR)
        g = self.game(hand=('arm', 'CS2_029')); self.play(g, 'arm'); self.play(g, 'CS2_029', self.hero(g, 2).id)
        self.assertEqual(self.hero(g, 2).health, 30); self.assertFalse(g.state.spell_repeats)
        self.assertTrue(g.state.play_history[-1].countered); self.check(g)

    def test_spellbender_redirect_once_and_same_target_twice(self):
        self.spell('arm', lambda c: [SetSecret(2, 'tt_010')], cls=CardClass.WARRIOR)
        g = self.game(hand=('arm', 'hit'), enemy=('plain',)); self.play(g, 'arm'); target = self.board(g, 2)[0].id
        self.play(g, 'hit', target)
        self.assertEqual(self.board(g, 2)[0].health, 8)
        self.assertEqual(len(self.events(g, 'spell_redirected')), 1)
        self.assertEqual(len({e.target_id for e in self.events(g, 'damage_dealt')}), 1); self.check(g)

    def test_spellburst_once_after_both_iterations(self):
        self.r.register_behavior('burst', lambda c: [GainArmor(1, 30-c.state.entities[c.state.players[2].hero_id].health)])
        self.minion('burst', health=5, keywords=(Keyword.SPELLBURST,), limited_triggers=(LimitedTriggerSpec.spellburst('burst'),))
        g = self.game(hand=('hit',), board=('repeat', 'burst')); self.play(g, 'hit', self.hero(g, 2).id)
        self.assertEqual(self.hero(g).armor, 4); self.check(g)

    def test_mid_spell_summoned_spellburst_waits_for_future_spell(self):
        self.spell('make', lambda c: [Summon(1, 'SCH_231')])
        g = self.game(hand=('make',)); self.play(g, 'make')
        self.assertEqual([e.attack for e in self.board(g)[1:]], [1, 1]); self.check(g)

    def test_play_conditions_and_prior_count_frozen(self):
        self.spell('condition', lambda c: [GainArmor(1, c.play.prior_turn_plays+1)])
        g = self.game(hand=('noop', 'condition')); self.play(g, 'noop'); self.play(g, 'condition')
        self.assertEqual(self.hero(g).armor, 4); self.assertEqual(len(g.state.play_history), 2)

    def test_nourish_choose_once_draw_six_with_restore(self):
        g = self.game(hand=('EX1_164',)); self.check(g)
        restored = Game.from_snapshot(g.snapshot(), self.r)
        for match in (g, restored):
            self.play(match, 'EX1_164', branch='draw'); self.assertIsNone(match.state.pending_choice)
            self.assertEqual(len(match.state.players[1].hand), 6)
            self.assertEqual(len(self.events(match, 'choice_requested')), 0)
            self.assertEqual([c.branch_id for c in match.state.cast_history], ['draw','draw']); self.check(match)
        self.assertEqual(g.snapshot(), restored.snapshot())

    def test_discover_is_a_new_choice_each_iteration(self):
        self.spell('discover', lambda c: [DiscoverFromPool(1, HERALD_POOL_ID,
            PoolQuery(kinds=(CardType.SPELL,), class_mode='other', include_neutral=False), source_id=c.source_id)])
        g = self.game(hand=('discover',)); self.play(g, 'discover'); first = g.state.pending_choice.id
        self.choose(g, g.state.pending_choice.options[0].id); self.assertGreater(g.state.pending_choice.id, first)
        self.assertEqual(g.state.spell_repeats[0].completed, 1); self.check(g)
        restored = Game.from_snapshot(g.snapshot(), self.r)
        for match in (g, restored): self.choose(match, match.state.pending_choice.options[-1].id)
        self.assertEqual(len(g.state.players[1].hand), 2)
        self.assertEqual(len(self.events(g, 'choice_requested')), 2)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.check(g)

    def test_branch_reuses_id_but_recomputes_effects(self):
        self.spell('branch', lambda c: [RequestChoice(1, (ChoiceOption('armor', 'Armor',
            (GainArmor(1, c.state.entities[c.state.players[1].hero_id].armor+1),)),),
            source_id=c.source_id, repeat_key='scale')])
        g = self.game(hand=('branch',)); self.play(g, 'branch'); self.choose(g, 'armor')
        self.assertEqual(self.hero(g).armor, 3); self.check(g)

    def test_changed_branch_candidates_fail_and_roll_back_selection(self):
        self.spell('branch', lambda c: [RequestChoice(1, (ChoiceOption(
            'first' if c.state.entities[c.state.players[1].hero_id].armor == 0 else 'changed', 'Armor',
            (GainArmor(1, 1),)),), source_id=c.source_id, repeat_key='unstable')])
        g = self.game(hand=('branch',)); self.play(g, 'branch'); before = g.snapshot()
        with self.assertRaises((ValueError, ResolutionError)): self.choose(g, 'first')
        self.assertEqual(g.snapshot(), before)

    def test_terminal_interrupt_cancels_second_cast(self):
        self.spell('lethal', lambda c: [Damage(c.target_id, 30, c.source_id)], requires_target=True)
        g = self.game(hand=('lethal',)); self.play(g, 'lethal', self.hero(g, 2).id)
        self.assertEqual(len(self.events(g, 'damage_dealt')), 1)
        self.assertTrue(g.state.spell_repeats[0].interrupted)
        self.assertTrue(g.state.play_history[0].interrupted); self.check(g)

    def test_secret_repetition_does_not_duplicate_active_secret(self):
        g = self.game(hand=('EX1_287',)); self.play(g, 'EX1_287')
        self.assertEqual(len(g.state.players[1].secrets), 1)
        self.assertEqual(len(self.events(g, 'secret_set')), 1)
        self.assertEqual(len(self.events(g, 'secret_set_failed')), 1); self.check(g)

    def test_repeated_quest_cannot_duplicate_main_quest(self):
        g = self.game(hand=('ULD_155',)); self.play(g, 'ULD_155')
        self.assertEqual(len(g.state.players[1].quests), 1)
        self.assertEqual(len(self.events(g, 'quest_activation_failed')), 1); self.check(g)

    def test_repeated_ongoing_spell_creates_independent_player_effects(self):
        g = self.game(hand=('AV_344',)); self.play(g, 'AV_344')
        effects = g.state.players[1].player_effects
        self.assertEqual(len(effects), 2); self.assertNotEqual(effects[0].id, effects[1].id)
        self.assertEqual(effects[0].source_id, effects[1].source_id); self.check(g)

    def test_repeat_choice_can_pause_with_a_dying_source(self):
        self.spell('kill_ask', lambda c: [Destroy(c.state.players[1].board[0]), RequestChoice(1,
            (ChoiceOption('draw', 'Draw', (Draw(1),)),), source_id=c.source_id)])
        g = self.game(hand=('kill_ask',)); self.play(g, 'kill_ask')
        self.assertTrue(self.board(g)[0].doomed); self.assertFalse(g.state.death_history); self.check(g)
        self.choose(g, 'draw'); self.assertIsNotNone(g.state.pending_choice); self.check(g)
        self.choose(g, 'draw'); self.assertFalse(self.board(g)); self.assertEqual(len(g.state.players[1].hand), 2); self.check(g)

    def test_nested_starship_choice_restores_both_death_deferrals(self):
        from hs_sim.engine import LaunchStarshipEffect
        from hs_sim.engine.starships import construction
        self.r.register_behavior('launch_ask', lambda c: [RequestChoice(1,
            (ChoiceOption('armor', 'Armor', (GainArmor(1, 2),)),), source_id=c.source_id)])
        self.r.register_card(replace(self.r.card('SC_403a'), id='piece', on_launch='launch_ask'))
        self.spell('launch', lambda c: [LaunchStarshipEffect(1, construction(c.state, 1).id)]
                   if construction(c.state, 1) else [])
        g = self.game(board=('repeat', 'piece'), hand=('kill', 'launch'))
        self.play(g, 'kill', self.board(g)[1].id); self.play(g, 'launch')
        self.assertEqual(g.snapshot()['resolution_frame']['fields']['death_deferrals'], 2); self.check(g)
        restored = Game.from_snapshot(g.snapshot(), self.r)
        for match in (g, restored): self.choose(match, 'armor')
        self.assertEqual(self.hero(g).armor, 2); self.assertEqual(len(g.state.starship_history), 1)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.check(g)

    def test_on_commit_source_removal_is_before_quota_capture(self):
        self.r.register_behavior('remove_on_commit', lambda c: [Silence(c.source_id)] if
            c.event.player_id == c.player_id else [])
        self.minion('transient', health=5, spell_repeats=(SpellRepeatSpec(),),
                    triggers=(TriggerSpec('card_committed', 'remove_on_commit'),))
        g = self.game(board=('transient',), hand=('hit',)); self.play(g, 'hit', self.hero(g, 2).id)
        self.assertEqual(self.hero(g, 2).health, 28); self.assertFalse(g.state.spell_repeats); self.check(g)

    def test_corrupt_progress_is_one_paid_play(self):
        g = self.game(hand=('CS2_029', 'DMF_073'))
        self.play(g, 'CS2_029', self.hero(g, 2).id)
        card = g.state.entities[g.state.players[1].hand[0]]
        self.assertEqual(card.card_id, 'DMF_073t')
        self.assertEqual(len(self.events(g, 'card_committed')), 1); self.check(g)

    def test_repeated_random_effect_consumes_new_rng(self):
        self.spell('random', lambda c: [RandomDamage((c.state.players[2].hero_id,
            *c.state.players[2].board), 1, c.source_id)])
        g = self.game(hand=('random',), enemy=('plain', 'plain')); before = g.snapshot()['rng_state']
        self.play(g, 'random'); self.assertEqual(len(self.events(g, 'damage_dealt')), 2)
        self.assertNotEqual(before, g.snapshot()['rng_state']); self.check(g)

    def test_repeat_budget_is_transactional(self):
        self.minion('huge', health=5, spell_repeats=(SpellRepeatSpec(1001),))
        g = self.game(hand=('hit',), board=('huge',)); before = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded): self.play(g, 'hit', self.hero(g, 2).id)
        self.assertEqual(g.snapshot(), before)

    def test_second_iteration_failure_rolls_back_rng_damage_and_history(self):
        self.spell('fail', lambda c: [RandomDamage((c.state.players[2].hero_id,), 1),
            *([GrantSpellRepeatAura(c.state.players[1].board[0], SpellRepeatSpec(), 99999)]
              if c.state.entities[c.state.players[2].hero_id].health < 30 else [])])
        g = self.game(hand=('fail',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'fail')
        self.assertEqual(g.snapshot(), before)

    def test_real_sinestra_body_limbs_and_foreign_spell(self):
        g = self.game(board=(), hand=('CATA_154', 'CS2_029'))
        self.play(g, 'CATA_154'); self.assertEqual([e.card_id for e in self.board(g)], ['CATA_154t', 'CATA_154', 'CATA_154t1'])
        self.assertEqual(len(g.state.players[1].hand), 3)
        self.play(g, 'CS2_029', self.hero(g, 2).id); self.assertEqual(self.hero(g, 2).health, 18); self.check(g)

    def test_real_body_unknown_generation_context_rolls_back(self):
        g = self.game(board=(), hand=('CATA_154',), context=False); before = g.snapshot()
        with self.assertRaises((ValueError, ResolutionError)): self.play(g, 'CATA_154')
        self.assertEqual(g.snapshot(), before)

    def test_full_board_body_aura_survives_failed_limbs(self):
        g = self.game(board=('plain',)*6, hand=('CATA_154', 'CS2_029'))
        self.play(g, 'CATA_154'); self.play(g, 'CS2_029', self.hero(g, 2).id)
        self.assertEqual(len(self.board(g)), 7); self.assertEqual(self.hero(g, 2).health, 18); self.check(g)

    def test_player_observation_hides_repeat_records_and_branch_keys(self):
        g = self.game(hand=('EX1_164',)); self.play(g, 'EX1_164', branch='draw')
        for p in (1, 2):
            view = json.dumps(g.observe(p))
            for private in ('spell_repeats', 'repeat_key', 'behavior_ids', 'death_deferrals'):
                self.assertNotIn(private, view)
        self.check(g)

    def test_snapshot_rejects_corrupt_repeat_record(self):
        self.spell('pause', lambda c:[RequestChoice(1,(ChoiceOption('ok','OK',()),),source_id=c.source_id)])
        g = self.game(hand=('pause',)); self.play(g, 'pause')
        for field, value in (('casts', True), ('casts', 1), ('completed', 3), ('running', False),
                             ('play_id', 99), ('target_id', 9999), ('behavior_ids', ['unknown']), ('interrupted', True)):
            with self.subTest(field=field):
                s = g.snapshot(); s['state']['spell_repeats'][0][field] = value
                with self.assertRaises(SnapshotError): Game.from_snapshot(s, self.r)

    def test_snapshot_rejects_removed_or_reordered_repeat_marker(self):
        self.spell('pause', lambda c:[RequestChoice(1,(ChoiceOption('ok','OK',()),),source_id=c.source_id)])
        g = self.game(hand=('pause',)); self.play(g, 'pause')
        for mode in ('delete', 'reverse', 'depth'):
            s = g.snapshot(); frame = s['resolution_frame']['fields']
            if mode == 'depth': frame['death_deferrals'] = 0
            else:
                q = frame['continuation']['tuple']
                if mode == 'delete': q.pop(0)
                else: q[0], q[1] = q[1], q[0]
            with self.assertRaises(SnapshotError): Game.from_snapshot(s, self.r)

    def test_snapshot_rejects_old_schema(self):
        g = self.game(); s = g.snapshot(); s['schema_version'] = 40
        with self.assertRaises(SnapshotError): Game.from_snapshot(s, self.r)

    def test_invalid_specs_definitions_and_memo_declarations(self):
        for args in ((1,), (True,), (2, 'current'), (2, [])):
            with self.assertRaises(ValueError): SpellRepeatSpec(*args)
        with self.assertRaises(ValueError): AbilityInstance(1, 'spell_repeat')
        with self.assertRaises(ValueError): AbilityInstance(1, 'aura', spell_repeat=SpellRepeatSpec())
        with self.assertRaises(ValueError):
            self.r.register_card(CardDefinition('bad', 'bad', CardType.SPELL, spell_repeats=(SpellRepeatSpec(),)))
        with self.assertRaises(ValueError):
            RequestChoice(1, (ChoiceOption('a', 'A'),), repeat_key='branch')
        with self.assertRaises(ValueError):
            RequestChoice(1, (ChoiceOption('a', 'A'),), source_id=1, repeat_key='branch', sample_size=1)

    def test_real_example_through_player_actions(self):
        from examples.sinestra_spell_repeat import run
        g, snapshot = run()
        self.assertEqual(len(g.history), 5)
        self.assertEqual(snapshot['schema_version'], 265)
        self.assertIsNone(snapshot['state']['pending_choice'])


if __name__ == '__main__': unittest.main()
