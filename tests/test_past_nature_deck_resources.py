"""Actual Nature plays and the two finite public requirements they exercise."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.cards import build_registry, past_nature_deck_resources as native
from hs_sim.cards.simple_followup_p89_cards import WO, PAST_POOL, QUERIES
from hs_sim.engine import EndTurn, Game, IllegalAction, PlayerSetup, ResolutionError, Ruleset, Scenario
from hs_sim.engine.effects import (AddToHand, Buff, ChangeManaCrystals, ChoiceOption,
    Damage, Destroy, GainTemporaryMana, InvokeBehavior, RandomDamage, RequestChoice)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import (CardClass, CardDefinition, CardType, CostSpec, EndTurnSpec,
    Keyword, PlayerEffectSpec, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery, resolve_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference, DrawMatching
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

P = 'k660.'
A, FIVE, SIX, EIGHT, NINE, TEN, BEAST, DRAGON, END, DEAD = (
    P + x for x in ('four', 'five', 'six', 'eight', 'nine', 'ten', 'beast', 'dragon', 'end_death', 'death_wait'))
SHIFT, REDUCE, HAND, KILL, OWN, OLD, AUTO, GROW, TEMP, BOOST, HURT = (
    P + x for x in ('shift_six', 'reduce_five', 'discount_hand', 'kill_all', 'kill_own',
        'printed_draw', 'other_gloop', 'grow', 'temporary', 'boost', 'hurt'))
FAIL = P + 'failure'
CTX = GenerationContext('k660-target', 'experimental')


def prompt(c, player):
    return RequestChoice(player, (ChoiceOption('continue', 'Continue'), ChoiceOption('fail', 'Fail', (
        RandomDamage((c.state.players[3-player].hero_id,), 1, c.source_id),
        InvokeBehavior(FAIL, c.source_id, player)))), c.source_id)


@lru_cache(maxsize=1)
def full():
    return build_registry()


@lru_cache(maxsize=None)
def fixture(role='writer'):
    r = opening_registry()
    r.register_card(full().card('REV_336t2'))
    r.register_pool_card(full().pool_card('REV_336t2'))
    native.register_past_nature_deck_resources(r)
    r.register_behavior(FAIL, lambda c: (_ for _ in ()).throw(ValueError('K660 deliberate rollback')))
    r.register_behavior(END, lambda c: (Destroy(c.source_id, c.source_id),))
    r.register_behavior(DEAD, lambda c: (prompt(c, c.player_id),))
    for cid, cost, fields in ((A, 4, {}), (FIVE, 5, {}), (SIX, 6, {}), (EIGHT, 8, {}),
            (NINE, 9, {}), (TEN, 10, {}), (BEAST, 4, {}), (DRAGON, 5, {}),
            (END, 3, dict(triggers=(TriggerSpec('turn_ended', END, EndTurnSpec()),))),
            (DEAD, 3, dict(deathrattle=DEAD))):
        meta = metadata(collectible=True, **({'tribes': ('beast',)} if cid == BEAST else
            {'tribes': ('dragon',)} if cid == DRAGON else {'tribes': ()}))
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=2, health=5,
            metadata=meta, **fields))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(native.POOL, 'k660-v1', CTX.target_id, CTX.mode,
        tuple(PoolMember(cid) for cid in (A, SIX, BEAST, DRAGON))))

    def stored(c, cid, delta):
        e = next(c.state.entities[i] for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id == cid)
        return (BuffStoredCard(CardReference.capture(e), cost=CostSpec(delta=delta), source_id=c.source_id),)

    def kills(c, own):
        players = (c.player_id,) if own else (1, 2)
        return tuple(Destroy(i, c.source_id) for pid in players for i in c.state.players[pid].board
            if not c.state.entities[i].card_id.startswith(P+'watch.'))

    helpers = {
        SHIFT: lambda c: stored(c, SIX, 1), REDUCE: lambda c: stored(c, FIVE, -1),
        HAND: lambda c: tuple(BuffStoredCard(CardReference.capture(c.state.entities[i]),
            cost=CostSpec(delta=-1), source_id=c.source_id) for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id == 'NX2_011'),
        KILL: lambda c: kills(c, False), OWN: lambda c: kills(c, True),
        OLD: lambda c: (DrawMatching(c.player_id, PoolQuery(kinds=(CardType.MINION,),
            min_cost=7, max_cost=7), 'skip', source_id=c.source_id),),
        AUTO: lambda c: (CastSpell(3-c.player_id, 'BOT_444', c.source_id),),
        GROW: lambda c: (ChangeManaCrystals(c.player_id, 6),),
        TEMP: lambda c: (GainTemporaryMana(c.player_id, 4),),
        BOOST: lambda c: (Buff(c.target_id, 2, 3, c.source_id),),
        HURT: lambda c: (Damage(c.target_id, 8, c.source_id),),
    }
    for cid, body in helpers.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            metadata=metadata(collectible=False), **({'targeting': TargetSpec()} if cid in (BOOST, HURT) else {})))
    for mode in ('draw', 'summon', 'fail_generated'):
        cid = P+'watch.'+mode

        def watch(c, mode=mode):
            event = c.event
            target = c.state.entities.get(event.target_id)
            if target is None:
                return ()
            if mode == 'draw' and event.kind == 'card_drawn':
                return (prompt(c, target.controller),)
            if mode == 'summon' and event.kind == 'minion_summoned' and target.card_id in ('GIL_553t', 'REV_336t2', 'REV_336t3', SIX, FIVE):
                return (prompt(c, target.controller),)
            if mode == 'fail_generated' and event.kind == 'card_added_to_hand' and target.controller == 2 and target.card_id in (A, SIX, BEAST, DRAGON):
                return (RandomDamage((c.state.players[1].hero_id,), 1, c.source_id),
                    InvokeBehavior(FAIL, c.source_id, 1))
            return ()

        r.register_behavior(cid, watch)
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=30,
            triggers=tuple(TriggerSpec(event, cid) for event in ('card_drawn', 'minion_summoned', 'card_added_to_hand'))))
    r.validate()
    return r


@lru_cache(maxsize=None)
def host(role='writer'):
    return build_cn37_local_pool_format()


class NatureDeckResourcesTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'mini'
    registry_factory = staticmethod(lambda mode, role: host(role).registry if mode == 'host' else fixture(role))

    def game(self, hand, *, board=(), enemy=(), deck=(A,)*7, enemy_deck=(A,)*7,
            mana=10, maximum=10, cap=10, watch=None, player=1, limit=7):
        self.mode = 'mini'
        own = PlayerSetup('mage.hero', hand=hand, board=board, deck=deck,
            mana=mana, max_mana=maximum, mana_cap=cap)
        other = PlayerSetup('mage.hero', board=enemy+((P+'watch.'+watch,) if watch else ()), deck=enemy_deck,
            mana=0, max_mana=10)
        return Game.from_scenario(Scenario((own, other) if player == 1 else (other, own),
            active_player=player, seed=660, generation_context=CTX), fixture(), ruleset=Ruleset(max_board=limit))

    def cards(self, g, zone, player=1):
        return [g.state.entities[i].card_id for i in getattr(g.state.players[player], zone)]

    def finish(self, g):
        while g.state.pending_choice:
            g = self.portable(g)
            self.choose(g)
        return g

    def test_twenty_actual_definitions_and_twenty_seven_full_rows_forty_primary_observations(self):
        d = native.load_batch(); r = fixture()
        self.assertEqual(len(d['official_observations']), 40)
        self.assertEqual(len(d['cards']+d['dependencies']+d['existing_dependencies']+d['evidence_only']), 27)
        for row in d['cards']+d['dependencies']:
            cid = row['record']['id']
            self.assertEqual(canonical_digest(asdict(r.card(cid))), row['definition_sha256'])
            self.assertEqual(asdict(r.pool_card(cid)), asdict(PoolCard.from_definition(r.card(cid))))
        self.assertEqual(len(d['complete_druid_Nature_inventory']), 85)
        self.assertFalse(d['source_scope_bound'])

    def test_existing_display_policy_preserves_real_infuse_thresholds_and_full_source_text(self):
        d = native.load_batch()
        rows = {v['record']['id']:v['record'] for v in d['cards']}
        self.assertEqual(d['display_normalizations'], {'NX2_011': {'@':''}, 'REV_336': {'@':''}})
        for cid, goal in d['infuse_thresholds'].items():
            self.assertEqual(rows[cid]['text_en'].count('@'), 1)
            self.assertEqual(fixture().card(cid).hand_progress.goal, goal)
        self.assertEqual(fixture().card('GIL_553t').cost, 0)

    def test_living_seed_all_three_real_ranks_draw_actual_beast_and_discount_it(self):
        for cid, maximum, reduction in zip(native.RANK.forms, (4, 5, 10), (1, 2, 3)):
            with self.subTest(card=cid):
                g = self.game((cid,), deck=(A, BEAST, DRAGON), mana=maximum, maximum=maximum)
                expected = self.entity(g, BEAST, zone='deck').id
                self.play(g, cid)
                self.assertEqual(g.state.players[1].hand, [expected])
                from hs_sim.engine.costs import local_cost
                self.assertEqual(local_cost(g.state.entities[expected])[0], 4-reduction)
        self.portable(g)

    def test_living_seed_actual_growth_upgrades_hand_and_deck_on_the_owner_maximum(self):
        g = self.game((GROW, 'BAR_536'), deck=('BAR_536', BEAST), mana=4, maximum=4)
        hand_id = self.entity(g, 'BAR_536').id; deck_id = self.entity(g, 'BAR_536', zone='deck').id
        self.play(g, GROW)
        self.assertEqual([g.state.entities[i].card_id for i in (hand_id, deck_id)], ['BAR_536t2']*2)
        self.portable(g)

    def test_living_seed_no_beast_skips_without_fatigue_or_random_draw(self):
        g = self.game(('BAR_536t2',), deck=())
        rng = g._rng.getstate(); self.play(g, 'BAR_536t2')
        self.assertEqual(g._rng.getstate(), rng)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 30)

    def test_living_seed_draw_reaction_wait_resumes_before_discounting_actual_arrival(self):
        g = self.game(('BAR_536t2',), deck=(BEAST,), watch='draw')
        self.play(g, 'BAR_536t2')
        self.assertIsNotNone(g.state.pending_choice)
        g = self.finish(g)
        from hs_sim.engine.costs import local_cost
        self.assertEqual(local_cost(self.entity(g, BEAST))[0], 1)

    def test_psychmelon_uses_adjusted_physical_cost_and_keeps_other_identical_copy_in_deck(self):
        g = self.game((SHIFT, 'BOT_404'), deck=(SIX, SIX, EIGHT, NINE, TEN))
        modified, original = g.state.players[1].deck[:2]
        self.play(g, SHIFT); self.play(g, 'BOT_404')
        self.assertEqual(g.state.players[1].hand[0], modified)
        self.assertEqual(self.cards(g, 'hand'), [SIX, EIGHT, NINE, TEN])
        self.assertEqual(g.state.players[1].deck, [original])
        self.portable(g)

    def test_old_matching_draw_retains_printed_cost_default_with_an_enchanted_seven(self):
        g = self.game((SHIFT, OLD), deck=(SIX,))
        self.play(g, SHIFT); self.play(g, OLD)
        self.assertEqual(self.cards(g, 'deck'), [SIX])
        self.assertEqual(self.cards(g, 'hand'), [])

    def test_psychmelon_each_waiting_draw_restores_and_keeps_original_cost_order(self):
        g = self.game((SHIFT, 'BOT_404'), deck=(TEN, SIX, NINE, EIGHT), watch='draw')
        self.play(g, SHIFT); self.play(g, 'BOT_404'); waits = 0
        while g.state.pending_choice:
            g = self.portable(g); self.choose(g); waits += 1
        self.assertEqual(waits, 4)
        self.assertEqual(self.cards(g, 'hand'), [SIX, EIGHT, NINE, TEN])

    def test_psychmelon_empty_matches_skip_and_full_hand_burns_each_actual_draw(self):
        g = self.game((SHIFT, 'BOT_404')+(A,)*8, deck=(SIX, EIGHT, NINE, TEN))
        self.play(g, SHIFT); self.play(g, 'BOT_404')
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertEqual(self.cards(g, 'deck'), [])
        empty = self.game(('BOT_404',), deck=()); self.play(empty, 'BOT_404')
        self.assertEqual(empty.state.entities[empty.state.players[1].hero_id].health, 30)

    def test_gloop_refreshes_for_both_sides_deaths_without_growing_any_crystals(self):
        g = self.game(('BOT_444', KILL), board=(A, A), enemy=(A,), mana=1)
        self.play(g, 'BOT_444'); self.play(g, KILL)
        p = g.state.players[1]
        self.assertEqual((p.mana, p.max_mana, p.temporary_mana), (3, 10, 0))
        self.portable(g)

    def test_gloop_instances_stack_and_remain_during_end_triggers_then_expire(self):
        g = self.game(('BOT_444', 'BOT_444'), board=(END,), mana=2)
        self.play(g, 'BOT_444'); self.play(g, 'BOT_444')
        self.assertEqual(len(g.state.players[1].player_effects), 2)
        g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].mana, 2)
        self.assertEqual(g.state.players[1].player_effects, [])
        self.portable(g)

    def test_gloop_automatic_opponent_turn_program_expires_on_actual_turn_end(self):
        g = self.game((AUTO, KILL), enemy=(A,))
        self.play(g, AUTO); self.play(g, KILL)
        self.assertEqual(g.state.players[2].mana, 1)
        self.assertEqual(len(g.state.players[2].player_effects), 1)
        g.apply(EndTurn(1))
        self.assertEqual(g.state.players[2].player_effects, [])
        self.portable(g)

    def test_ironbark_uses_permanent_crystals_and_applies_stats_and_taunt_to_real_target(self):
        g = self.game((TEMP, 'BT_132'), board=(A,), mana=2, maximum=6)
        target = self.entity(g, A, zone='board').id
        self.play(g, TEMP); self.play(g, 'BT_132', target)
        e = g.state.entities[target]
        self.assertEqual((e.attack, e.max_health), (3, 8)); self.assertIn(Keyword.TAUNT, e.keywords)
        self.assertEqual(g.state.players[1].mana, 4)
        free = self.game(('BT_132',), board=(A,), mana=0, maximum=7)
        self.play(free, 'BT_132', free.state.players[1].board[0]); self.assertEqual(free.state.players[1].mana, 0)
        self.portable(free)

    def test_real_twinspell_creates_one_original_copy_and_both_native_bodies_buff_current_team(self):
        g = self.game(('DAL_351',), board=(A, A))
        self.play(g, 'DAL_351'); self.assertEqual(self.cards(g, 'hand'), ['DAL_351ts'])
        self.play(g, 'DAL_351ts')
        self.assertEqual([(g.state.entities[i].attack, g.state.entities[i].max_health) for i in g.state.players[1].board], [(4, 7)]*2)
        self.assertEqual(self.cards(g, 'hand'), []); self.portable(g)

    def test_breath_checks_the_actual_drawn_dragon_and_at_cap_creates_no_excess_mana(self):
        g = self.game(('DRG_318',), deck=(DRAGON,), mana=2, maximum=3)
        self.play(g, 'DRG_318'); self.assertEqual(g.state.players[1].max_mana, 4)
        empty = self.game(('DRG_318',), deck=(A,), mana=2, maximum=3)
        self.play(empty, 'DRG_318'); self.assertEqual(empty.state.players[1].max_mana, 3)
        capped = self.game(('DRG_318',), deck=(DRAGON,))
        self.play(capped, 'DRG_318'); self.assertEqual(self.cards(capped, 'hand'), [DRAGON])
        self.assertEqual(capped.state.players[1].max_mana, 10); self.portable(capped)

    def test_wispering_woods_counts_remaining_hand_and_resumes_each_named_wisp_with_capacity(self):
        g = self.game(('GIL_553', A, A, A), board=(A,)*5, watch='summon')
        self.play(g, 'GIL_553'); g = self.finish(g)
        self.assertEqual(self.cards(g, 'board'), [A]*5+['GIL_553t']*2)
        self.assertEqual(self.cards(g, 'hand'), [A]*3)
        self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board[-2:]], [1, 1])

    def test_recycle_moves_actual_enemy_to_deck_without_death_and_clears_board_enchantments(self):
        g = self.game((BOOST, 'GVG_031'), enemy=(DEAD,), enemy_deck=())
        target = self.entity(g, DEAD, player=2, zone='board').id
        self.play(g, BOOST, target); self.play(g, 'GVG_031', target)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.players[2].deck, [target])
        self.assertEqual(g.state.entities[target].attack, 2)
        self.portable(g)

    def test_mulch_resolves_death_choice_before_opponent_random_minion_delivery(self):
        g = self.game(('AT_044',), enemy=(DEAD,))
        self.play(g, 'AT_044', self.entity(g, DEAD, player=2, zone='board').id)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(self.cards(g, 'hand', 2), [])
        g = self.finish(g)
        self.assertEqual(len(g.state.players[2].hand), 1)
        self.assertIn(self.cards(g, 'hand', 2)[0], (A, SIX, BEAST, DRAGON))

    def test_portal_heals_first_and_summons_from_full_declared_six_cost_scope(self):
        g = self.game((HURT, 'KAR_075'), enemy=(A,))
        target = g.state.players[2].hero_id
        self.play(g, HURT, target)
        self.play(g, 'KAR_075', target)
        self.assertEqual(g.state.entities[target].health, 28)
        self.assertEqual(self.cards(g, 'board'), [SIX]); self.portable(g)
        full_board = self.game(('KAR_075',), board=(A,)*7)
        self.play(full_board, 'KAR_075', full_board.state.players[2].hero_id)
        self.assertEqual(len(full_board.state.players[1].board), 7)

    def test_oaken_summons_uses_adjusted_deck_cost_and_physical_material_after_armor(self):
        g = self.game((REDUCE, 'LOOT_309'), deck=(FIVE,), watch='summon')
        original = self.entity(g, FIVE, zone='deck').id
        self.play(g, REDUCE); self.play(g, 'LOOT_309')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 6)
        g = self.finish(g)
        self.assertEqual(g.state.players[1].board, [original])
        self.assertEqual(self.cards(g, 'deck'), [])

    def test_oaken_full_board_retains_deck_but_still_gives_six_armor(self):
        g = self.game(('LOOT_309',), board=(A,)*7, deck=(A,))
        self.play(g, 'LOOT_309')
        self.assertEqual((g.state.entities[g.state.players[1].hero_id].armor, self.cards(g, 'deck')), (6, [A]))

    def test_infuse_five_and_six_only_own_deaths_in_hand_and_real_upgraded_bodies(self):
        g = self.game(('NX2_011', 'REV_336', KILL, OWN, A), board=(A,)*4, enemy=(A,),
            deck=('NX2_011', A, A, A), mana=20, maximum=20, cap=20)
        self.play(g, KILL)
        self.assertIn('REV_336', self.cards(g, 'hand'))
        self.play(g, A); self.play(g, OWN)
        self.assertIn('REV_336t4', self.cards(g, 'hand')); self.assertIn('NX2_011', self.cards(g, 'hand'))
        self.assertEqual(self.cards(g, 'deck')[0], 'NX2_011')
        self.play(g, 'REV_336t4'); self.assertEqual(self.cards(g, 'board'), ['REV_336t3']*2)
        self.portable(g)

    def test_life_from_death_retains_held_discount_and_draws_three_from_real_one_cost_form(self):
        g = self.game((HAND, 'NX2_011', OWN), board=(A,)*6, deck=(A, A, A))
        original = self.entity(g, 'NX2_011').id
        self.play(g, HAND); self.play(g, OWN)
        self.assertEqual(g.state.entities[original].card_id, 'NX2_011t')
        from hs_sim.engine.costs import local_cost
        self.assertEqual(local_cost(g.state.entities[original])[0], 0)
        mana = g.state.players[1].mana; self.play(g, 'NX2_011t')
        self.assertEqual((g.state.players[1].mana, self.cards(g, 'hand')), (mana, [A]*3))
        self.portable(g)

    def test_invalid_hero_target_and_generated_reaction_failure_preserve_paid_action_and_rng(self):
        bad = self.game(('BT_132',))
        before = bad.snapshot()
        with self.assertRaises(IllegalAction): self.play(bad, 'BT_132', bad.state.players[1].hero_id)
        self.assertEqual(bad.snapshot(), before)
        g = self.game(('AT_044',), enemy=(A,), watch='fail_generated')
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'AT_044', self.entity(g, A, player=2, zone='board').id)
        self.assertEqual(g.snapshot(), before)

    def test_current_cost_and_current_turn_program_declarations_reject_ambiguous_operands(self):
        query = PoolQuery(kinds=(CardType.MINION,), min_cost=7, max_cost=7)
        for fields in (dict(cost_basis='payment'), dict(cost_basis='local'),
                dict(cost_basis='local', source_id=1, owner_id=2)):
            with self.assertRaises(ValueError): DrawMatching(1, query, 'skip', **fields)
        with self.assertRaises(ValueError): DrawMatching(1, PoolQuery(), 'skip', source_id=1, cost_basis='local')
        with self.assertRaises(ValueError): PlayerEffectSpec('bad', 'BOT_444', kind='turn_trigger')
        with self.assertRaises(ValueError): replace(fixture().player_effect(native.PROGRAM), spell_damage=1)

    def test_second_player_physical_draw_and_private_infused_hand_keep_player_boundaries(self):
        g = self.game(('NX2_011', OWN), board=(A,)*6, player=2)
        text = json.dumps(g.for_player(1).observe())+json.dumps(g.player_events(1))
        self.assertNotIn('NX2_011', text)
        self.play(g, OWN, player=2)
        self.assertIn('NX2_011t', self.cards(g, 'hand', 2))
        text = json.dumps(g.for_player(1).observe())+json.dumps(g.player_events(1))
        for key in ('NX2_011t', 'rng_state', 'resolution_frame', 'hand_entry_id'):
            self.assertNotIn(key, text)
        self.portable(g)

    def test_real_standard_host_executes_all_new_effect_groups_and_keeps_complete_nature_scope_closed(self):
        self.mode = 'host'; f = host()
        g = Game.from_scenario(Scenario((PlayerSetup('HERO_06',
            hand=('BOT_444', 'BT_132', 'DAL_351', 'GIL_553', 'DRG_318', 'LOOT_309', 'BOT_404'),
            board=('CORE_CS2_182',), deck=('CORE_CS2_182',)*6, mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_08')), seed=660, generation_context=f.context), f.registry)
        self.play(g, 'BOT_444'); self.play(g, 'BT_132', g.state.players[1].board[0])
        for cid in ('DAL_351', 'GIL_553', 'DRG_318', 'LOOT_309', 'BOT_404'):
            self.play(g, cid)
        for query in (native.MINIONS, native.SIX):
            candidates = resolve_candidates(f.registry, f.context, native.POOL, query, current_class=CardClass.DRUID)
            self.assertTrue(candidates)
        with self.assertRaises(UnsupportedDefinitionError):
            resolve_candidates(f.registry, f.context, PAST_POOL, QUERIES[WO],
                current_class=CardClass.DRUID, source_card_id=WO, exclude_source_by_rule=True)
        self.portable(g)

    def test_real_standard_host_random_generation_recycle_and_real_upgrade_faces_execute(self):
        self.mode = 'host'; f = host()
        members = f.registry.pool(native.POOL, f.context).members
        beast = next(m.card_id for m in members if
            'beast' in (f.registry.card(m.card_id).metadata.tribes or ()) and
            f.registry.card(m.card_id).kind == CardType.MINION)
        g = Game.from_scenario(Scenario((PlayerSetup('HERO_06',
            hand=('AT_044', 'KAR_075', 'BAR_536t2', 'NX2_011t', 'REV_336t4', 'GVG_031'),
            deck=(beast, 'CORE_CS2_182', 'CORE_CS2_182', 'CORE_CS2_182'),
            mana=50, max_mana=50, mana_cap=50),
            PlayerSetup('HERO_08', board=('CORE_CS2_182', 'CORE_CS2_182'))),
            seed=661, generation_context=f.context), f.registry)
        enemies = list(g.state.players[2].board)
        self.play(g, 'AT_044', enemies[0])
        self.assertEqual(len(g.state.players[2].hand), 1)
        self.play(g, 'KAR_075', g.state.players[2].hero_id)
        self.assertTrue(g.state.players[1].board)
        for cid in ('BAR_536t2', 'NX2_011t', 'REV_336t4'):
            self.play(g, cid)
        self.assertIn(beast, self.cards(g, 'hand'))
        self.assertEqual(self.cards(g, 'board').count('REV_336t3'), 2)
        self.play(g, 'GVG_031', enemies[1])
        self.assertIn(enemies[1], g.state.players[2].deck)
        self.portable(g)
