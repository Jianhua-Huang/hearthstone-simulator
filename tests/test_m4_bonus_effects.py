"""Elusive, bonus-effect eligibility and complete Terran token generation."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, Game,
    GrantRandomBonusEffects, IllegalAction, Keyword, LaunchStarship, PlayCard, PlayerSetup,
    PoolCard, PoolDefinition, PoolMember, PoolQuery, Rarity, ResolutionError,
    ResolutionLimitExceeded, Ruleset, Scenario, SelectChoice, SnapshotError,
    SummonFromCandidates, TargetSpec, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.bonus_effects import BONUS_EFFECTS, bonus_candidates
from hs_sim.engine.effects import (ChoiceOption, CopyMinion, Damage, DamageBatch, Destroy,
    GrantKeyword, RandomDamage, RequestChoice, ReturnToHand, Silence, Summon)
from hs_sim.engine.pools import GenerationContext, resolve_candidates
from hs_sim.engine.representative import build_registry, TERRAN_LAUNCH_PIECES
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.starships import construction


class BonusEffectsTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.r.register_card(CardDefinition('plain', 'plain', CardType.MINION, attack=2, health=9,
            metadata=CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=('mech',), factions=())))
        self.r.register_card(replace(self.r.card('plain'), id='elusive', keywords=(Keyword.ELUSIVE,)))
        self.spell('scrap', lambda c: [Destroy(i) for i in c.state.players[1].board])

    def spell(self, name, callback, **kwargs):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, **kwargs))

    def game(self, hand=(), deck=(), board=(), enemy=(), seed=23, hero_power=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01', hand=hand, deck=deck, board=board,
            max_mana=10, mana=10, hero_power_card_id=hero_power),
            PlayerSetup('HERO_01', board=enemy, max_mana=10, mana=10)), seed=seed), self.r)

    def cast(self, g, card, target=None):
        entity = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == card)
        return g.apply(PlayCard(1, entity, target))

    def choose(self, g):
        c = g.state.pending_choice
        g.apply(SelectChoice(c.player_id, c.id, ('ok',)))

    def check_replay(self, g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())), self.r).snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), g.snapshot())

    def test_elusive_blocks_friendly_and_enemy_spell_targets_and_player_commands(self):
        g = self.game(hand=('CS2_029',), board=('elusive',), enemy=('elusive',))
        before = g.snapshot()
        for target in (*g.state.players[1].board, *g.state.players[2].board):
            with self.assertRaises(IllegalAction): self.cast(g, 'CS2_029', target)
            self.assertFalse(any(isinstance(a, PlayCard) and a.target_id == target for a in g.legal_actions()))
        self.assertEqual(g.snapshot(), before)
        # Only hero targets remain in both command surfaces.
        commands = g.for_player(1).legal_actions()['actions']
        self.assertEqual(sum(a['type'] == 'play_card' for a in commands), 2)

    def test_elusive_blocks_both_owners_hero_power_targets(self):
        g = self.game(board=('elusive',), enemy=('elusive',), hero_power='HERO_08bp')
        source = g.state.players[1].hero_power_id
        before = g.snapshot()
        for target in (*g.state.players[1].board, *g.state.players[2].board):
            with self.assertRaises(IllegalAction): g.apply(UseHeroPower(1, source, target))
            self.assertNotIn(target, g.legal_targets(source))
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(sum(isinstance(a, UseHeroPower) for a in g.legal_actions()), 2)
        target = g.state.players[2].hero_id
        health = g.state.entities[target].health
        g.apply(UseHeroPower(1, source, target))
        self.assertEqual(g.state.entities[target].health, health - 1)
        self.assertEqual(g.state.entities[source].uses_this_turn, 1)
        self.check_replay(g)

    def test_elusive_allows_battlecry_and_attack(self):
        g = self.game(hand=('EX1_019',), board=('elusive',), enemy=('elusive',))
        friendly, enemy = g.state.players[1].board[0], g.state.players[2].board[0]
        self.cast(g, 'EX1_019', friendly)
        self.assertEqual(g.state.entities[friendly].attack, 3)
        g.apply(Attack(1, friendly, enemy)); self.check_replay(g)

    def test_elusive_does_not_block_untargeted_aoe_or_random_damage(self):
        self.spell('sweep', lambda c: [DamageBatch(tuple(Damage(i, 1) for i in c.state.players[2].board)),
            RandomDamage(tuple(c.state.players[2].board), 2, c.source_id)])
        g = self.game(hand=('sweep',), enemy=('elusive',))
        target = g.state.players[2].board[0]; self.cast(g, 'sweep')
        self.assertEqual(g.state.entities[target].damage, 3); self.check_replay(g)

    def test_elusive_in_hand_is_not_target_protection(self):
        self.spell('inspect', lambda c: [], targeting=TargetSpec(zones=(Zone.HAND,), kinds=(CardType.MINION,)))
        g = self.game(hand=('inspect', 'elusive'))
        self.cast(g, 'inspect', g.state.players[1].hand[1])

    def test_silence_removes_elusive_and_reopens_shared_targeting(self):
        g = self.game(hand=('CS2_203', 'CS2_029'), enemy=('elusive',))
        target = g.state.players[2].board[0]
        self.cast(g, 'CS2_203', target); self.cast(g, 'CS2_029', target)
        self.assertEqual(g.state.entities[target].damage, 6); self.check_replay(g)

    def test_granted_elusive_copies_but_resets_on_return_to_hand(self):
        self.spell('grant', lambda c: [GrantKeyword(c.target_id, Keyword.ELUSIVE), CopyMinion(c.target_id, 1)], requires_target=True)
        self.spell('return', lambda c: [ReturnToHand(c.state.players[1].board[0])])
        g = self.game(hand=('grant', 'return'), board=('plain',))
        original = g.state.players[1].board[0]; self.cast(g, 'grant', original)
        copied = g.state.players[1].board[1]; self.cast(g, 'return')
        self.assertIn(Keyword.ELUSIVE, g.state.entities[copied].keywords)
        self.assertNotIn(Keyword.ELUSIVE, g.state.entities[original].keywords); self.check_replay(g)

    def test_all_eight_candidates_can_be_granted_without_stealth(self):
        self.assertEqual(len(BONUS_EFFECTS), 8); self.assertNotIn(Keyword.STEALTH, BONUS_EFFECTS)
        for wanted in BONUS_EFFECTS:
            with self.subTest(wanted=wanted):
                # A freshly summoned minion has exactly one missing candidate.
                r = build_registry()
                r.register_card(CardDefinition('almost', 'almost', CardType.MINION, attack=2, health=9,
                    keywords=tuple(k for k in BONUS_EFFECTS if k != wanted)))
                r.register_behavior('grant', lambda c: [GrantRandomBonusEffects(c.state.players[1].board[0])])
                r.register_card(CardDefinition('grant', 'grant', CardType.SPELL, on_play='grant'))
                g = Game.from_scenario(Scenario((PlayerSetup('HERO_01', hand=('almost','grant')), PlayerSetup('HERO_01'))), r)
                self.cast(g, 'almost'); self.cast(g, 'grant')
                self.assertEqual(g.state.entities[g.state.players[1].board[0]].keywords, set(BONUS_EFFECTS))

    def test_rush_readiness_filters_do_not_depend_on_enemy_targets(self):
        g = self.game(board=('plain',)); state = g.state; old = state.entities[state.players[1].board[0]]
        fresh = replace(old, summoned_turn=state.turn)
        self.assertIn(Keyword.RUSH, bonus_candidates(state, fresh))
        for blocked in (old, replace(fresh, controller=2), replace(fresh, attacks_this_turn=1),
                        replace(fresh, keywords={Keyword.CHARGE}),
                        replace(fresh, attacks_this_turn=1, keywords={Keyword.WINDFURY})):
            self.assertNotIn(Keyword.RUSH, bonus_candidates(state, blocked))

    def test_exhausted_bonus_pool_is_noop_without_rng(self):
        self.r.register_card(replace(self.r.card('plain'), id='complete', keywords=BONUS_EFFECTS))
        self.spell('grant', lambda c: [GrantRandomBonusEffects(c.state.players[1].board[0], 2)])
        g = self.game(hand=('grant',), board=('complete',))
        before = g.snapshot()['rng_state']; self.cast(g, 'grant')
        self.assertEqual(before, g.snapshot()['rng_state']); self.check_replay(g)

    def test_consumed_shield_can_be_granted_again(self):
        self.r.register_card(replace(self.r.card('plain'), id='complete', keywords=BONUS_EFFECTS))
        self.spell('renew', lambda c: [Damage(c.state.players[1].board[0], 1),
            GrantRandomBonusEffects(c.state.players[1].board[0])])
        g = self.game(hand=('renew',), board=('complete',)); self.cast(g, 'renew')
        self.assertIn(Keyword.DIVINE_SHIELD, g.state.entities[g.state.players[1].board[0]].keywords)
        self.check_replay(g)

    def test_multiple_ravens_grant_distinct_effects_on_combined_ship(self):
        g = self.game(hand=('scrap',), board=('SC_403c',)*3)
        self.cast(g, 'scrap'); ship = construction(g.state, 1)
        g.apply(LaunchStarship(1, ship.id)); entity = g.state.entities[ship.id]
        self.assertEqual(len(entity.keywords.intersection(BONUS_EFFECTS)), 6); self.check_replay(g)

    def test_raven_gain_is_on_launch_not_summon_or_death(self):
        g = self.game(hand=('SC_403c', 'scrap'))
        self.cast(g, 'SC_403c')
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].keywords, {Keyword.STARSHIP_PIECE})
        self.cast(g, 'scrap'); self.assertFalse(construction(g.state, 1).keywords.intersection(BONUS_EFFECTS))

    def test_bonus_choice_resume_preserves_remaining_random_work(self):
        self.r.register_behavior('ask', lambda c: [RequestChoice(1, (ChoiceOption('ok','ok',()),))])
        self.r.register_card(replace(self.r.card('plain'), id='watch', triggers=(TriggerSpec('ability_granted','ask'),)))
        self.spell('grant', lambda c: [GrantRandomBonusEffects(c.state.players[1].board[0], 2)])
        g = self.game(hand=('grant',), board=('watch',)); self.cast(g, 'grant')
        self.assertIsNotNone(g.state.pending_choice)
        restored = Game.from_snapshot(json.loads(json.dumps(g.snapshot())), self.r)
        while g.state.pending_choice: self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.check_replay(g)
        self.assertEqual(len(g.state.entities[g.state.players[1].board[0]].keywords), 2)

    def test_bonus_failure_rolls_back_rng_attachments_and_mana(self):
        self.spell('bad', lambda c: [GrantRandomBonusEffects(c.state.players[1].board[0], 2),
            GrantRandomBonusEffects(c.state.players[1].board[0], source_id=99999)])
        g = self.game(hand=('bad',), board=('plain',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.cast(g, 'bad')
        self.assertEqual(g.snapshot(), before)

    def test_departure_between_bonus_picks_stops_remaining_grants(self):
        self.r.register_behavior('bounce', lambda c: [ReturnToHand(c.event.target_id)])
        self.r.register_card(replace(self.r.card('plain'), id='watch', triggers=(TriggerSpec('ability_granted','bounce'),)))
        self.spell('grant', lambda c: [GrantRandomBonusEffects(c.state.players[1].board[0], 2)])
        g = self.game(hand=('grant',), board=('plain','watch')); target = g.state.players[1].board[0]
        result = self.cast(g,'grant')
        self.assertEqual(g.state.entities[target].zone, Zone.HAND)
        self.assertFalse(g.state.entities[target].keywords)
        self.assertEqual(sum(e.kind == 'ability_granted' for e in result.events), 1); self.check_replay(g)

    def test_bonus_count_budget_is_explicit_failure(self):
        self.spell('huge', lambda c: [GrantRandomBonusEffects(c.state.players[1].board[0], 1001)])
        g = self.game(hand=('huge',), board=('plain',)); before = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded): self.cast(g, 'huge')
        self.assertEqual(g.snapshot(), before)

    def test_faction_is_separate_from_minion_tribe(self):
        self.assertEqual(self.r.card('SC_403t').metadata.factions, ('terran',))
        self.assertEqual(self.r.card('SC_403t').metadata.tribes, ())
        self.assertEqual(self.r.card('plain').metadata.factions, ())
        self.assertEqual(self.r.card('SC_410').metadata.factions, ('terran',))

    def test_static_pool_filters_factions_independently(self):
        for i in ('SC_403t','SC_410','plain'): self.r.register_pool_card(PoolCard.from_definition(self.r.card(i)))
        self.r.register_pool(PoolDefinition('factions','v1','t','experimental',
            tuple(PoolMember(i) for i in ('SC_403t','SC_410','plain'))))
        found = resolve_candidates(self.r, GenerationContext('t','experimental'), 'factions', PoolQuery(factions_any=('terran',)))
        self.assertEqual({m.card_id for m in found}, {'SC_403t','SC_410'})

    def test_conflicting_faction_aliases_are_rejected(self):
        self.r.register_card(replace(self.r.card('plain'), id='alias', metadata=replace(self.r.card('plain').metadata, factions=('terran',))))
        for i in ('plain','alias'): self.r.register_pool_card(PoolCard.from_definition(self.r.card(i), identity='same'))
        self.r.register_pool(PoolDefinition('conflict','v1','t','experimental',(PoolMember('plain'),PoolMember('alias'))))
        with self.assertRaises(ValueError): self.r.validate()

    def test_unknown_faction_metadata_rolls_back_instead_of_excluding(self):
        self.r.register_card(replace(self.r.card('plain'), id='unknown', metadata=replace(self.r.card('plain').metadata, factions=None)))
        g = self.game(hand=('SC_410',), deck=('SC_403t','unknown')); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.cast(g, 'SC_410')
        self.assertEqual(g.snapshot(), before)

    def test_lift_off_draws_terran_minion_and_spell_but_not_unrelated_mech(self):
        g = self.game(hand=('SC_410',), deck=('plain','SC_403t','SC_407'))
        self.cast(g, 'SC_410')
        self.assertEqual({g.state.entities[i].card_id for i in g.state.players[1].hand}, {'SC_403t','SC_407'})
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck], ['plain'])
        self.assertIn(g.state.entities[g.state.players[1].board[0]].card_id, TERRAN_LAUNCH_PIECES)
        self.check_replay(g)

    def test_lift_off_draws_physical_duplicates(self):
        g = self.game(hand=('SC_410',), deck=('SC_403t',)*2); self.cast(g, 'SC_410')
        self.assertEqual(len(g.state.players[1].hand), 2); self.assertFalse(g.state.players[1].deck)

    def test_lift_off_empty_or_no_matching_deck_still_summons_without_fatigue(self):
        for deck in ((), ('plain',), ('SC_403t',)):
            with self.subTest(deck=deck):
                g = self.game(hand=('SC_410',), deck=deck); self.cast(g, 'SC_410')
                self.assertEqual(g.state.players[1].fatigue, 0)
                self.assertEqual(len(g.state.players[1].board), 1); self.check_replay(g)

    def test_lift_off_full_hand_burns_second_draw_before_summoning(self):
        g = self.game(hand=('SC_410',)+('plain',)*9, deck=('SC_403t',)*2)
        result = self.cast(g, 'SC_410')
        self.assertEqual(len(g.state.players[1].hand), 10); self.assertFalse(g.state.players[1].deck)
        self.assertEqual(len(g.state.players[1].board), 1)
        burned = [e for e in result.events if 'burn' in e.kind]
        self.assertEqual(len(burned), 1); self.check_replay(g)

    def test_lift_off_full_board_still_draws(self):
        g = self.game(hand=('SC_410',), deck=('SC_403t',)*2, board=('plain',)*7)
        self.cast(g, 'SC_410'); self.assertEqual(len(g.state.players[1].hand), 2)
        self.assertEqual(len(g.state.players[1].board), 7); self.check_replay(g)

    def test_full_five_piece_list_is_reachable_without_launching_on_summon(self):
        seen = set()
        for seed in range(40):
            g = self.game(hand=('SC_410',), seed=seed); self.cast(g, 'SC_410')
            entity = g.state.entities[g.state.players[1].board[0]]; seen.add(entity.card_id)
            self.assertEqual((entity.attack, entity.health, entity.keywords), (2,1,{Keyword.STARSHIP_PIECE}))
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)
        self.assertEqual(seen, set(TERRAN_LAUNCH_PIECES))

    def test_invalid_fixed_candidate_fails_even_on_full_board(self):
        for bad in ('missing','SC_410','GDB_100a'):
            with self.subTest(bad=bad):
                r = build_registry()
                r.register_behavior('bad', lambda c, bad=bad: [SummonFromCandidates(1, ('SC_403a',bad), c.source_id)])
                r.register_card(CardDefinition('bad','bad',CardType.SPELL,on_play='bad'))
                g = Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=('bad',),board=('SC_403a',)*7),PlayerSetup('HERO_01'))),r)
                before = g.snapshot()
                with self.assertRaises(ResolutionError): self.cast(g,'bad')
                self.assertEqual(before,g.snapshot())

    def test_fixed_candidate_list_rejects_duplicate_weighting(self):
        for values in ((), ('SC_403a','SC_403a'), ['SC_403a']):
            with self.assertRaises(ValueError): SummonFromCandidates(1, values)

    def test_lift_off_draw_choice_restores_query_and_full_fixed_list(self):
        self.r.register_behavior('ask', lambda c: [RequestChoice(1,(ChoiceOption('ok','ok',()),))])
        self.r.register_card(replace(self.r.card('plain'), id='watch', triggers=(TriggerSpec('card_drawn','ask'),)))
        g = self.game(hand=('SC_410',), deck=('SC_403t','SC_407'), board=('watch',)); self.cast(g,'SC_410')
        self.assertIsNotNone(g.state.pending_choice)
        restored = Game.from_snapshot(json.loads(json.dumps(g.snapshot())), self.r)
        while g.state.pending_choice: self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.check_replay(g)
        self.assertEqual(len(g.state.players[1].board), 2)

    def test_player_commands_and_snapshot_expose_elusive_on_public_minion(self):
        g = self.game(board=('elusive',))
        view = json.dumps(g.observe(1))
        self.assertIn('elusive', view); self.check_replay(g)

    def test_frame_codec_rejects_unimplemented_fixed_candidate_before_resuming(self):
        from hs_sim.engine.continuations import FrameCodec
        from hs_sim.engine.resolver import default_mechanics
        codec = FrameCodec(default_mechanics(), self.r)
        valid = codec.encode(SummonFromCandidates(1, TERRAN_LAUNCH_PIECES))
        self.assertEqual(codec.decode(valid), SummonFromCandidates(1, TERRAN_LAUNCH_PIECES))
        valid['fields']['card_ids']['tuple'][2] = 'missing-raven'
        with self.assertRaises(ValueError): codec.decode(valid)

    def test_real_card_example_restores_and_replays(self):
        from examples.raven_and_lift_off import run
        game, snapshot = run()
        self.assertEqual(snapshot['schema_version'], 265)
        self.assertEqual(len(game.history), 5)


if __name__ == '__main__': unittest.main()
