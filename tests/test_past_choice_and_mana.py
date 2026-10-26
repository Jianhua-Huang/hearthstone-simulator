"""The actual five past roots, their choices, Mana accounts and taught CASTs."""
from dataclasses import replace
from functools import lru_cache
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_nefarian_native_dependencies import fixture as base_fixture, P, FILLER
from hs_sim.cards.past_choice_and_mana import ROOTS, DEPENDENCIES, CHOICES, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, ResolutionError, Scenario,
    SelectChoice, TriggerSpec)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import AddToHand, ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.pools import (GenerationContext, PoolDefinition, PoolMember,
    resolve_candidates, sample_candidates)
from hs_sim.engine.student_teaching import QUERY
from tools import card_batch as batch

WATCH, ADD = 'k550.watch', 'k550.add'
CTX = GenerationContext('k550-five-known-spell-test-inventory', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    fmt = base_fixture.__wrapped__('normal', role); r = fmt.registry
    for name in ('constructed.cards', 'constructed.minions'):
        r.register_pool(replace(r.pool(name, fmt.context), target_id=CTX.target_id, mode=CTX.mode))
    r.register_pool(PoolDefinition('constructed.past.spells', 'five-known-test-spells-v1',
        CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in ROOTS), complete=True))

    def fail(c): raise ResolutionError('k550 late summon failure')

    def observe(c):
        if mode=='wait' and c.event.kind=='card_drawn' and c.event.player_id==c.player_id:
            return (RequestChoice(c.player_id, (
                ChoiceOption('continue', 'Continue', ()),
                ChoiceOption('bad', 'Fail', (InvokeBehavior('k550.fail', c.source_id, c.player_id),))),
                c.source_id, prompt='Draw reaction'),)
        if (mode=='fail' and c.event.kind=='minion_summoned' and
                c.state.entities[c.event.target_id].card_id=='DEEP_028t'):
            return fail(c)
        return ()

    r.register_behavior('k550.fail', fail)
    r.register_behavior('k550.observe', observe)
    r.register_behavior(ADD, lambda c: (AddToHand(c.player_id, FILLER, c.source_id),))
    r.register_card(CardDefinition(ADD, 'Add a fresh Tiger', CardType.SPELL, on_play=ADD))
    r.register_card(CardDefinition(WATCH, 'Observer', CardType.MINION, attack=1, health=8,
        triggers=tuple(TriggerSpec(event, 'k550.observe') for event in ('card_drawn', 'minion_summoned'))))
    r.validate()
    return replace(fmt, context=CTX)


class PastChoiceManaTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(lambda mode, role: fixture(mode, role).registry)

    def game(self, hand, *, board=(), enemy=(), deck=(FILLER,)*8, mode='normal',
            maximum=10, cap=10, temporary=0, seed=1):
        self.mode = mode; fmt = fixture(mode)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06', hand=hand, board=board, deck=deck, max_mana=maximum,
                mana=maximum+temporary, mana_cap=cap, temporary_mana=temporary),
            PlayerSetup('HERO_08', hand=(FILLER,), board=enemy, deck=(FILLER,)*8,
                max_mana=10, mana=10)), seed=seed, generation_context=CTX), fmt.registry)

    def play_branch(self, game, cid, branch):
        game.apply(PlayCard(1, self.entity(game, cid).id, branch_id=branch))

    def pick(self, game, key):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (key,)))

    def test_full_original_rows_primary_faces_missing_option_evidence_and_printed_zero_are_distinct(self):
        data = load_batch(); r = fixture().registry
        rows = {x['record']['id']: x['record'] for key in ('cards', 'dependencies', 'evidence_only') for x in data[key]}
        source = {row['id']: row for row in batch.read(data['source'])}
        self.assertEqual(batch.sha(data['source']), data['source_sha256'])
        self.assertEqual(len(rows), 18)
        for cid, raw in rows.items(): self.assertEqual(raw, source[cid])
        for face in data['official_faces']:
            batch.check_face(rows[face['card_id']], face['face'], face['locale'],
                numeric_normalizations=data['numeric_normalizations'].get(face['card_id']))
        self.assertEqual(set(data['unconfirmed_choice_primary_ids']), {'ETC_373a','ETC_373b','OG_195a','OG_195b'})
        self.assertIsNone(rows['OG_195c']['cost']); self.assertEqual(r.card('OG_195c').cost, 0)
        self.assertEqual({cid for cid in (*ROOTS, *DEPENDENCIES) if r.card(cid).choice_only}, set(CHOICES))
        self.assertIsNone(r.card('VAC_907').choose_one)
        for root, tokens in (('DEEP_028', ('DEEP_028t',)), ('ETC_373', ('ETC_373t',)),
                ('OG_195', ('OG_195c',)), ('VAC_907', CHOICES[-3:])):
            for observation in (x for x in data['official_faces'] if x['card_id']==root):
                self.assertTrue({rows[cid]['dbf_id'] for cid in tokens} <= set(observation['face']['childIds']))
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_both_real_choose_one_branches_pay_once_and_keep_the_other_text_out(self):
        for root, token, count, health in (('ETC_373','ETC_373t',5,4), ('OG_195','OG_195c',7,2)):
            for branch in (root+'a', root+'b'):
                with self.subTest(root=root, branch=branch):
                    game = self.game((root,), board=(P+'unit',), enemy=('BOT_066t',))
                    original = game.state.players[1].board[0]
                    self.play_branch(game, root, branch)
                    self.assertEqual(game.state.players[1].mana, 3)
                    old = game.state.entities[original]
                    if branch.endswith('a'):
                        self.assertEqual(sum(game.state.entities[i].card_id==token for i in game.state.players[1].board), min(count,6))
                        self.assertEqual((old.attack,old.health), (1,1))
                    else:
                        self.assertEqual(len(game.state.players[1].board), 1)
                        self.assertEqual((old.attack,old.health), (3,1+health))
                        self.assertEqual(Keyword.TAUNT in old.keywords, root=='ETC_373')
                    enemy = game.state.entities[game.state.players[2].board[0]]
                    self.assertEqual((enemy.attack,enemy.health), (7,7))

    def test_existing_fandral_combined_payload_grants_after_new_minions_have_really_entered(self):
        for root, token, size, taunt in (('ETC_373','ETC_373t',(4,6),True), ('OG_195','OG_195c',(3,3),False)):
            with self.subTest(root=root):
                game = self.game((root,), board=('CORE_OG_044',))
                self.play_branch(game, root, root+':combined')
                children = [game.state.entities[i] for i in game.state.players[1].board if game.state.entities[i].card_id==token]
                self.assertEqual(len(children), 5 if root=='ETC_373' else 6)
                self.assertTrue(all((e.attack,e.health)==size and (Keyword.TAUNT in e.keywords)==taunt for e in children))
                self.assertEqual(game.state.players[1].mana, 3)

    def test_combined_branch_without_its_actual_source_is_illegal_before_payment(self):
        game = self.game(('ETC_373',)); saved = game.snapshot()
        with self.assertRaises(IllegalAction): self.play_branch(game, 'ETC_373', 'ETC_373:combined')
        self.assertEqual(game.snapshot(), saved)

    def test_cluster_uses_permanent_crystal_space_and_actual_cap_including_empty_growth(self):
        for maximum, cap, temporary, expected in ((7,10,0,0), (8,10,0,1), (9,10,0,2),
                (10,10,0,3), (12,13,0,2), (9,10,2,2)):
            with self.subTest(maximum=maximum, cap=cap, temporary=temporary):
                game = self.game(('DEEP_028',), maximum=maximum, cap=cap, temporary=temporary)
                self.play(game, 'DEEP_028')
                self.assertEqual(game.state.players[1].max_mana, min(maximum+3,cap))
                self.assertEqual(game.state.players[1].mana, maximum+temporary-7)
                children = [game.state.entities[i] for i in game.state.players[1].board]
                self.assertEqual(len(children), expected)
                self.assertTrue(all(e.card_id=='DEEP_028t' and (e.attack,e.health)==(3,7)
                    and Keyword.TAUNT in e.keywords for e in children))

    def test_full_board_does_not_convert_blocked_elementals_back_into_crystals(self):
        game = self.game(('DEEP_028',), board=(P+'unit',)*7)
        self.play(game, 'DEEP_028')
        self.assertEqual((game.state.players[1].max_mana,game.state.players[1].mana), (10,3))
        self.assertEqual(len(game.state.players[1].board), 7)

    def test_stars_allows_three_repeated_options_and_refresh_respects_actual_spent_mana(self):
        for option in CHOICES[-3:]:
            with self.subTest(option=option):
                game = self.game(('VAC_907',))
                self.play(game, 'VAC_907')
                self.assertEqual(game.state.players[1].mana, 2)
                for _ in range(3): self.pick(game, option)
                self.assertIsNone(game.state.pending_choice)
                self.assertEqual(len(game.state.players[1].hand), 6 if option=='VAC_907t1' else 0)
                self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 15 if option=='VAC_907t2' else 0)
                self.assertEqual(game.state.players[1].mana, 10 if option=='VAC_907t3' else 2)

    def test_stars_draw_reaction_wait_preserves_original_remaining_choices_and_bad_resume(self):
        game = self.game(('VAC_907',), board=(WATCH,), mode='wait')
        self.play(game, 'VAC_907'); self.pick(game, 'VAC_907t1')
        self.assertEqual(game.state.pending_choice.prompt, 'Draw reaction')
        saved = game.snapshot()
        with self.assertRaises(ResolutionError): self.pick(game, 'bad')
        self.assertEqual(game.snapshot(), saved)
        restored = self.portable(game)
        for current in (game, restored):
            self.pick(current, 'continue'); self.pick(current, 'continue')
            self.pick(current, 'VAC_907t2'); self.pick(current, 'VAC_907t3')
            self.assertIsNone(current.state.pending_choice)
            self.assertEqual(len(current.state.players[1].hand), 2)
            self.assertEqual(current.state.entities[current.state.players[1].hero_id].armor, 5)
            self.assertEqual(current.state.players[1].mana, 5)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.portable(game)

    def test_alignment_affects_only_current_own_hand_and_deck_not_future_generated_cards(self):
        game = self.game(('BAR_539', FILLER, ADD), deck=(FILLER, P+'noop'))
        self.play(game, 'BAR_539')
        owner = game.state.players[1]
        self.assertEqual((owner.max_mana,owner.mana), (0,0))
        for zone in (owner.hand, owner.deck):
            for eid in zone: self.assertEqual(quote_unselected_cost(game.state,game.registry,game.state.entities[eid]).amount,1)
        opponent = game.state.players[2]
        self.assertEqual((opponent.max_mana,opponent.mana), (10,10))
        self.assertEqual(quote_unselected_cost(game.state,game.registry,game.state.entities[opponent.hand[0]]).amount,5)
        game.apply(EndTurn(1)); game.apply(EndTurn(2))
        self.play(game, ADD)
        prices = [quote_unselected_cost(game.state,game.registry,game.state.entities[i]).amount
            for i in game.state.players[1].hand if game.state.entities[i].card_id==FILLER]
        self.assertIn(1,prices); self.assertIn(5,prices)

    def test_late_elemental_failure_rolls_back_payment_crystal_growth_and_all_summons(self):
        game = self.game(('DEEP_028',), board=(WATCH,), mode='fail', maximum=9)
        saved = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'k550 late summon failure'): self.play(game, 'DEEP_028')
        self.assertEqual(game.snapshot(), saved)

    def test_real_teacher_and_student_execute_all_five_roots_with_native_branch_and_choice_policy(self):
        r = fixture().registry
        rows = resolve_candidates(r, CTX, 'constructed.past.spells', QUERY,
            current_class=CardClass.DRUID, source_card_id='TIME_704', player_id=1)
        for cid in ROOTS:
            with self.subTest(card=cid):
                seed = next(n for n in range(100) if cid in sample_candidates(Random(n),rows,3,replacement=False))
                game = self.game(('TIME_704',), seed=seed)
                self.play(game, 'TIME_704'); choice = game.state.pending_choice
                selected = next(o for o in choice.options if o.card_id==cid)
                self.pick(game, selected.id); self.play(game, 'TIME_704t')
                self.assertIsNone(game.state.pending_choice)
                record = game.state.cast_history[-1]
                self.assertEqual((record.card_id,record.origin), (cid,'effect'))
                if cid in ('ETC_373','OG_195'):
                    self.assertIn(record.branch_id,(cid+'a',cid+'b'))
                if cid=='BAR_539': self.assertEqual(game.state.players[1].max_mana,0)
        self.portable(game)


if __name__ == '__main__':
    unittest.main()
