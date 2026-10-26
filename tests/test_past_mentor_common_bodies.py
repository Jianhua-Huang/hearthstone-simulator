"""Real past spells and their exact tokens, including taught automatic CASTs."""
from dataclasses import replace
from functools import lru_cache
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture as base_fixture, P, FILLER
from hs_sim.cards.past_mentor_common_bodies import ROOTS, DEPENDENCIES, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardType, EndTurn, Game,
    Keyword, PlayerSetup, ResolutionError, Scenario, SelectChoice, TriggerSpec)
from hs_sim.engine.effects import ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.pools import (GenerationContext, PoolDefinition, PoolMember,
    resolve_candidates, sample_candidates)
from hs_sim.engine.student_teaching import QUERY
from tools import card_batch as batch

WATCH = 'k549.watch'
CTX = GenerationContext('k549-six-known-spell-test-inventory', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    fmt = base_fixture.__wrapped__('normal', role); r = fmt.registry
    for name in ('constructed.cards', 'constructed.minions'):
        r.register_pool(replace(r.pool(name, fmt.context), target_id=CTX.target_id, mode=CTX.mode))
    # This tiny declared test inventory exercises the actual teacher. It is
    # deliberately separate from the production host's unresolved past domain.
    r.register_pool(PoolDefinition('constructed.past.spells', 'six-known-test-spells-v1',
        CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in ROOTS), complete=True))

    def fail(c): raise ResolutionError('late plant failure')

    def observe(c):
        if mode=='wait' and c.event.kind=='card_drawn' and c.event.player_id==c.player_id:
            options = (ChoiceOption('continue', 'Continue', ()),
                ChoiceOption('bad', 'Fail', (InvokeBehavior('k549.fail', c.source_id, c.player_id),)))
            return (RequestChoice(c.player_id, options, c.source_id),)
        if (mode=='fail' and c.event.kind=='minion_summoned' and
                c.state.entities[c.event.target_id].card_id=='TSC_656t'):
            return fail(c)
        return ()

    r.register_behavior('k549.fail', fail)
    r.register_behavior('k549.observe', observe)
    r.register_card(CardDefinition(WATCH, 'Observer', CardType.MINION, attack=1, health=8,
        metadata=r.card(P+'unit').metadata,
        triggers=tuple(TriggerSpec(event, 'k549.observe') for event in ('card_drawn', 'minion_summoned'))))
    r.validate()
    return replace(fmt, context=CTX)


class PastMentorCommonBodyTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(lambda mode, role: fixture(mode, role).registry)

    def game(self, hand, *, board=(), enemy=(), deck=(FILLER,)*8, mode='normal', seed=1):
        self.mode = mode; fmt = fixture(mode)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06', hand=hand, board=board, deck=deck, mana=10, max_mana=10),
            PlayerSetup('HERO_08', board=enemy, deck=(FILLER,)*8)), seed=seed,
            generation_context=fmt.context), fmt.registry)

    def test_ten_complete_faces_and_twenty_primary_observations_preserve_exact_native_tokens(self):
        data = load_batch(); r = fixture().registry
        rows = {x['record']['id']: x['record'] for x in data['cards']+data['dependencies']}
        original = {x['id']: x for x in batch.read(data['source'])}
        self.assertEqual(tuple(rows), (*ROOTS, *DEPENDENCIES))
        self.assertEqual(batch.sha(data['source']), data['source_sha256'])
        for cid, raw in rows.items():
            self.assertEqual(raw, original[cid]); card = r.card(cid)
            self.assertEqual((card.name, card.cost), (raw['name'], raw['cost']))
            if card.kind==CardType.MINION:
                self.assertEqual((card.attack, card.health), (raw['attack'], raw['health']))
        for observation in data['official_faces']:
            batch.check_face(rows[observation['card_id']], observation['face'], observation['locale'])
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_tree_of_life_really_heals_both_heroes_and_both_sides_minions(self):
        game = self.game(('GVG_033', *(P+'hurt',)*4), board=('BOT_066t',), enemy=('BOT_066t',))
        targets = tuple(game.state.players[p].hero_id for p in (1, 2)) + tuple(game.state.players[p].board[0] for p in (1, 2))
        for target in targets: self.play(game, P+'hurt', target)
        self.play(game, 'GVG_033')
        self.assertEqual(game.state.players[1].mana, 1)
        self.assertTrue(all(game.state.entities[i].health==game.state.entities[i].max_health for i in targets))

    def test_survival_buffs_physical_minions_in_three_zones_without_touching_enemy_or_spells(self):
        game = self.game(('SCH_609', FILLER, P+'noop'), board=('BOT_066t',),
            enemy=('BOT_066t',), deck=(FILLER, P+'noop', FILLER))
        own = game.state.players[1]
        ids = [i for zone in (own.hand, own.deck, own.board) for i in zone if game.state.entities[i].kind==CardType.MINION]
        old = {i:(game.state.entities[i].attack, game.state.entities[i].max_health) for i in ids}
        self.play(game, 'SCH_609')
        for i, (attack, health) in old.items():
            self.assertEqual((game.state.entities[i].attack, game.state.entities[i].max_health), (attack+4, health+4))
        enemy = game.state.entities[game.state.players[2].board[0]]
        self.assertEqual((enemy.attack, enemy.health), (7, 7))
        self.assertEqual(game.state.players[1].mana, 0)

    def test_scale_fills_only_actual_vacancies_with_exact_rush_whelps_and_accepts_full_board(self):
        for occupied in (3, 7):
            with self.subTest(occupied=occupied):
                game = self.game(('ONY_021',), board=(P+'unit',)*occupied)
                self.play(game, 'ONY_021')
                children = [game.state.entities[i] for i in game.state.players[1].board if game.state.entities[i].card_id=='ONY_001t']
                self.assertEqual(len(children), game.ruleset.max_board-occupied)
                self.assertTrue(all((e.attack,e.health)==(2,1) and Keyword.RUSH in e.keywords for e in children))
                self.assertEqual(len(game.state.players[1].board), game.ruleset.max_board)
                self.assertEqual(game.state.players[1].mana, 3)

    def test_growth_reads_actual_hand_after_burns_and_zero_card_fatigue_creates_a_zero_health_plant(self):
        game = self.game(('TSC_656', *(P+'noop',)*8))
        self.play(game, 'TSC_656')
        plant = self.entity(game, 'TSC_656t', zone='board')
        self.assertEqual((plant.attack, plant.health), (10,10))
        self.assertIn(Keyword.TAUNT, plant.keywords)
        self.assertEqual(len(game.state.players[1].deck), 5)
        game = self.game(('TSC_656',), deck=())
        self.play(game, 'TSC_656')
        self.assertFalse(game.state.players[1].board)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 24)
        self.assertEqual(game.state.death_history[-1].card_id, 'TSC_656t')

    def test_forests_aid_has_five_attempts_and_one_terminal_twinspell_copy(self):
        game = self.game(('DAL_256',), board=(P+'unit',)*4)
        self.play(game, 'DAL_256')
        self.assertEqual(sum(game.state.entities[i].card_id=='DAL_256t2' for i in game.state.players[1].board), 3)
        child = self.entity(game, 'DAL_256ts')
        self.assertNotIn(Keyword.TWINSPELL, child.keywords)
        game.apply(EndTurn(1)); game.apply(EndTurn(2))
        self.play(game, 'DAL_256ts')
        self.assertFalse(any(game.state.entities[i].card_id in ('DAL_256','DAL_256ts') for i in game.state.players[1].hand))
        self.assertEqual(len(game.state.players[1].board), 7)

    def test_cenarion_ward_grants_armor_then_summons_a_real_eight_cost_from_the_whole_local_pool(self):
        game = self.game(('DMF_732',))
        self.play(game, 'DMF_732')
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 8)
        self.assertEqual(game.state.players[1].mana, 2)
        self.assertTrue(game.state.players[1].board)
        roots = [row for row in game.state.card_summon_history
            if row.request.pool_basis is not None and row.request.cause.source.card_id=='DMF_732']
        self.assertEqual(len(roots), 1)
        chosen = roots[0].request.materials[roots[0].selected].card_id
        self.assertEqual(game.registry.card(chosen).cost, 8)
        # A Colossal left appendage can precede its actual eight-cost source.
        self.assertTrue(any(game.state.entities[i].card_id==chosen for i in game.state.players[1].board))

    def test_real_mentor_teaches_each_known_spell_and_student_automatically_executes_its_actual_cast(self):
        fmt = fixture(); r = fmt.registry
        rows = resolve_candidates(r, CTX, 'constructed.past.spells', QUERY,
            current_class=CardClass.DRUID, source_card_id='TIME_704', player_id=1)
        for cid in ROOTS:
            with self.subTest(card=cid):
                seed = next(n for n in range(100) if cid in sample_candidates(Random(n), rows, 3, replacement=False))
                game = self.game(('TIME_704',), seed=seed)
                self.play(game, 'TIME_704')
                choice = game.state.pending_choice
                option = next(o for o in choice.options if o.card_id==cid)
                game.apply(SelectChoice(1, choice.id, (option.id,)))
                self.play(game, 'TIME_704t')
                self.assertEqual(game.state.players[1].mana, 1)
                self.assertEqual(game.state.cast_history[-1].card_id, cid)
                self.assertEqual(game.state.cast_history[-1].origin, 'effect')
                if cid=='DAL_256': self.entity(game, 'DAL_256ts')
                if cid=='TSC_656':
                    plant = self.entity(game, 'TSC_656t', zone='board')
                    self.assertEqual((plant.attack,plant.health), (3,3))
        self.portable(game)

    def test_draw_wait_restores_before_dynamic_plant_and_bad_branch_does_not_advance(self):
        game = self.game(('TSC_656',), board=(WATCH,), mode='wait')
        self.play(game, 'TSC_656')
        self.assertTrue(game.state.pending_choice)
        self.assertFalse(any(game.state.entities[i].card_id=='TSC_656t' for i in game.state.players[1].board))
        saved = game.snapshot(); choice = game.state.pending_choice
        with self.assertRaises(ResolutionError): game.apply(SelectChoice(1, choice.id, ('bad',)))
        self.assertEqual(game.snapshot(), saved)
        restored = self.portable(game)
        for current in (game, restored):
            count = 0
            while current.state.pending_choice:
                self.choose(current); count += 1
            self.assertEqual(count, 3)
            plant = self.entity(current, 'TSC_656t', zone='board')
            self.assertEqual((plant.attack,plant.health), (3,3))
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.portable(game)

    def test_failure_after_plant_entry_rolls_back_the_original_payment_draws_and_summon(self):
        game = self.game(('TSC_656',), board=(WATCH,), mode='fail')
        saved = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'late plant failure'): self.play(game, 'TSC_656')
        self.assertEqual(game.snapshot(), saved)


if __name__ == '__main__':
    unittest.main()
