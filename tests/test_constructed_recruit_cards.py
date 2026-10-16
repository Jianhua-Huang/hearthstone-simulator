"""Real K07 consumers: physical zones, draw replacement and original cost facts."""
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.recruit_cards import load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CostSpec,
    DeckPolicy, DeckSpec, EndTurn, Game, Keyword, MatchSetup, OpeningHook, PlayCard,
    PlayerSetup, Rarity, Scenario, SelectChoice, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand, Buff, ChangeManaCrystals, ChoiceOption,
    Destroy, Draw, GainArmor, ModifyCost, RequestChoice, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import SpellSchool
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.targets import canonical_digest


def registry(wait=False, fault=False):
    r = build_registry()
    neutral = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
    r.register_behavior('k07.bc', lambda c: (GainArmor(c.state.players[c.player_id].hero_id, 99),))
    for cid, cost, tribes, bc in (('small', 2, (), None), ('demon', 4, ('demon',), 'k07.bc'),
                                ('large', 5, (), None)):
        r.register_card(CardDefinition('k07.'+cid, cid, CardType.MINION, cost=cost, attack=2, health=5,
            battlecry=bc, metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=tribes)))
    scripts = {
        'draw': lambda c: (Draw(c.player_id, source_id=c.source_id),),
        'full_draw': lambda c: (AddToHand(c.player_id, 'k07.small'), Draw(c.player_id, source_id=c.source_id)),
        'create_dragon': lambda c: (AddToHand(c.player_id, 'EDR_260t'),),
        'fel': lambda c: (),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'modify': lambda c: (ModifyCost(c.state.players[c.player_id].deck[0], CostSpec(delta=-4)),
            BuffStoredCard(CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[1]]), 3, 3, c.source_id)),
        'generate': lambda c: (AddToHand(c.player_id, next(c.state.entities[e].card_id
            for e in c.state.players[c.player_id].hand if e in c.state.opening.original_entities[c.player_id-1])),),
    }
    for name, body in scripts.items():
        r.register_behavior('k07.'+name, body)
        r.register_card(CardDefinition('k07.'+name, name, CardType.MINION if name == 'kill' else CardType.SPELL,
            health=1 if name == 'kill' else 0, battlecry='k07.kill' if name == 'kill' else None,
            on_play=None if name == 'kill' else 'k07.'+name, requires_target=name == 'kill',
            spell_school=SpellSchool.FEL if name == 'fel' else None, metadata=neutral))
    r.register_behavior('k07.wave', lambda c: (Summon(c.player_id, 'k07.wave_token'),))
    r.register_card(CardDefinition('k07.wave', 'Wave fixture', CardType.MINION, health=2,
        deathrattle='k07.wave', metadata=neutral))
    r.register_card(CardDefinition('k07.wave_token', 'Wave child', CardType.MINION, health=1, metadata=neutral))
    r.register_card(CardDefinition('k07.spellpower', 'Spell damage fixture', CardType.MINION, health=3,
        spell_damage=1, metadata=neutral))
    if wait or fault:
        def watch(c):
            if c.state.entities[c.event.source_id].card_id not in ('EDR_260t', 'CAP_400t2t'):
                return ()
            if fault:
                return (AddToHand(c.player_id, 'missing.k07.after_summon'),)
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),), c.source_id),)
        r.register_behavior('k07.watch', watch)
        r.register_card(CardDefinition('k07.watch', 'Watch', CardType.MINION, health=6,
            triggers=(TriggerSpec('minion_summoned', 'k07.watch'),), metadata=neutral))
    # A genuine constructed opening provides the physical starter identities.
    for i in range(29):
        r.register_card(CardDefinition(f'k07.origin.{i}', f'Origin {i}', CardType.MINION, health=2,
            metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())))
    r.register_behavior('k07.bootstrap', lambda c: (ChangeManaCrystals(c.player_id, 9, filled=True),
        *((AddToHand(1, 'DINO_409'), AddToHand(1, 'k07.generate')) if c.player_id == 1 else ())))
    r.register_card(CardDefinition('k07.boot', 'Bootstrap', CardType.MINION, health=2,
        opening_hooks=(OpeningHook('after_mulligan', 'k07.bootstrap'),),
        metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())))
    return r


class ConstructedRecruitCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = registry()
    def game(self, hand=(), deck=('k07.small',)*4, board=(), enemy=(), enemy_deck=(), enemy_hand=(), custom=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', hand=hand, deck=deck, board=board, mana=30, max_mana=30, mana_cap=40),
            PlayerSetup('HERO_03', hero_power_card_id='HERO_03bp', hand=enemy_hand, deck=enemy_deck, board=enemy, mana=30, max_mana=30, mana_cap=40)),
            seed=53), custom or self.r)
    def eid(self, g, cid, p=1):
        return next(e for e in g.state.players[p].hand if g.state.entities[e].card_id == cid)
    def play(self, g, cid, target=None, p=1, recipient=None):
        eid = self.eid(g, cid, p)
        g.apply(PlayCard(p, eid, target_id=target, board_player_id=recipient))
        return eid
    def names(self, g, zone='hand', p=1):
        return [g.state.entities[e].card_id for e in getattr(g.state.players[p], zone)]
    def price(self, g, cid, p=1):
        return quote_cost(g.state, g.registry, g.state.entities[self.eid(g, cid, p)]).amount
    def portable(self, g, wait=False):
        saved = g.snapshot()
        restored = Game.from_snapshot(saved, registry(wait))
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(wait)).snapshot(), saved)
        return restored
    def finish(self, g):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, ('continue',)))

    def test_24_full_pinned_records_and_definitions_match_printed_data(self):
        data = load_batch()
        self.assertEqual((len(data['cards']), sum(x['recipe']['root'] for x in data['cards'])), (24, 17))
        for row in data['cards']:
            raw = row['record']; definition = self.r.card(raw['id'])
            with self.subTest(card=raw['id']):
                self.assertEqual(canonical_digest(raw), row['record_sha256'])
                self.assertEqual((definition.cost, definition.attack, definition.health),
                    (raw['cost'], raw['attack'] or 0, raw['health'] or 0))
        self.assertEqual(self.r.card('END_030').metadata.tribes, ('dragon', 'beast'))
        self.assertTrue(self.r.card('JAIL_442').disguised)

    def test_sixteen_scenario_roots_pay_run_and_complete_their_trigger_or_death(self):
        for row in load_batch()['cards']:
            cid = row['record']['id']; recipe = row['recipe']
            if not recipe['root'] or cid == 'DINO_409':
                continue
            with self.subTest(card=cid):
                g = self.game((cid, 'k07.kill', 'k07.demon'), deck=('k07.demon', 'k07.small'))
                before = g.state.players[1].mana; price = self.price(g, cid)
                eid = self.play(g, cid)
                self.assertEqual(g.state.play_history[-1].mana_after, before-price)
                if 'deathrattle' in recipe['bodies']:
                    self.play(g, 'k07.kill', eid)
                if 'own_power_used' in recipe['bodies']:
                    g.apply(UseHeroPower(1, g.state.players[1].hero_power_id, target_id=g.state.players[2].hero_id))
                self.assertIsNone(g.state.pending_choice)

    def test_oak_recruits_original_with_printed_cost_preserving_buffs_without_battlecry(self):
        g = self.game(('k07.modify', 'CORE_LOOT_309'), deck=('k07.large', 'k07.demon'))
        large, small = g.state.players[1].deck
        self.play(g, 'k07.modify'); self.play(g, 'CORE_LOOT_309')
        self.assertEqual(g.state.players[1].deck, [large]); self.assertEqual(g.state.players[1].board, [small])
        self.assertEqual((g.state.entities[small].attack, g.state.entities[small].health), (5, 8))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 6)
        self.assertEqual(len(g.state.play_history), 2); self.portable(g)

    def test_oak_empty_or_full_board_keeps_armor_without_rng(self):
        for deck, board in ((('k07.large',), ()), (('k07.small',), ('k07.small',)*7)):
            g = self.game(('CORE_LOOT_309',), deck=deck, board=board); rng = g.snapshot()['rng_state']
            self.play(g, 'CORE_LOOT_309')
            self.assertEqual(g.snapshot()['rng_state'], rng)
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 6)
            self.assertEqual(self.names(g, 'deck'), list(deck))

    def test_willow_uses_one_actual_demon_from_each_zone_and_no_battlecry(self):
        g = self.game(('CORE_SCH_181', 'k07.demon', 'k07.small'), deck=('k07.demon', 'k07.large'))
        hand = self.eid(g, 'k07.demon'); deck = g.state.players[1].deck[0]
        willow = self.play(g, 'CORE_SCH_181')
        self.assertEqual(g.state.players[1].board, [willow, hand, deck])
        self.assertEqual(self.names(g, 'deck'), ['k07.large'])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)
        self.assertEqual(len(g.state.play_history), 1); self.portable(g)

    def test_willow_last_slot_goes_to_hand_then_deck_stays_physical(self):
        g = self.game(('CORE_SCH_181', 'k07.demon'), deck=('k07.demon',), board=('k07.small',)*5)
        original = g.state.players[1].deck[0]; hand = self.eid(g, 'k07.demon')
        self.play(g, 'CORE_SCH_181')
        self.assertIn(hand, g.state.players[1].board); self.assertEqual(g.state.players[1].deck, [original])
        self.assertEqual(len(g.state.players[1].board), 7)

    def test_real_deathrattles_shuffle_all_complete_dependencies_to_correct_deck(self):
        for cid, token, count, player in (('CORE_SW_439', 'SW_439t', 4, 1), ('CAP_400', 'CAP_400t2t', 2, 2),
                ('EDR_260', 'EDR_260t', 2, 1), ('JAIL_442', 'JAIL_443t', 4, 1)):
            with self.subTest(card=cid):
                g = self.game((cid, 'k07.kill'), deck=())
                eid = self.play(g, cid); self.play(g, 'k07.kill', eid)
                self.assertEqual(self.names(g, 'deck', player), [token]*count)
                self.assertEqual(self.names(g, 'deck', 3-player), [])
        g = self.game(('JAIL_442', 'k07.kill'), deck=())
        eid = self.play(g, 'JAIL_442', recipient=2); self.play(g, 'k07.kill', eid)
        self.assertEqual(self.names(g, 'deck', 2), ['JAIL_443t']*4)
        self.assertEqual(g.state.entities[eid].owner, 1)
        self.assertEqual(g.state.death_history[-1].controller, 2); self.portable(g)

    def test_drawn_dragon_moves_original_then_replaces_without_play_or_spell_cast(self):
        g = self.game(('k07.draw',), deck=('EDR_260t', 'k07.small'))
        original = g.state.players[1].deck[0]; self.play(g, 'k07.draw')
        self.assertEqual(g.state.players[1].board, [original]); self.assertEqual(self.names(g), ['k07.small'])
        self.assertEqual((len(g.state.play_history), len(g.state.cast_history)), (1, 1))
        self.assertEqual([d.source_id for d in g.state.draw_history], [g.state.play_history[0].source_id, original])
        self.portable(g)

    def test_drawn_imp_uses_opponent_board_but_original_owner_and_drawer_replacement(self):
        g = self.game(('k07.draw',), deck=('CAP_400t2t', 'k07.small'), board=('k07.small',)*7)
        original = g.state.players[1].deck[0]; self.play(g, 'k07.draw')
        self.assertEqual(g.state.players[2].board, [original]); e = g.state.entities[original]
        self.assertEqual((e.owner, e.controller, e.attack, e.health), (1, 2, 3, 3))
        self.assertIn(Keyword.LIFESTEAL, e.keywords); self.assertEqual(self.names(g), ['k07.small'])
        self.assertEqual(self.names(g, p=2), []); self.portable(g)

    def test_full_hand_burn_does_not_summon_or_replace(self):
        g = self.game(('k07.full_draw',)+('k07.small',)*9, deck=('EDR_260t', 'k07.large'))
        original = g.state.players[1].deck[0]; self.play(g, 'k07.full_draw')
        self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD)
        self.assertEqual(self.names(g, 'deck'), ['k07.large']); self.assertEqual(len(g.state.draw_history), 1)
        self.assertEqual(g.state.players[1].board, [])

    def test_full_recipient_board_keeps_revealed_original_and_still_replaces(self):
        for token, player in (('EDR_260t', 1), ('CAP_400t2t', 2)):
            with self.subTest(token=token):
                g = self.game(('k07.draw',), deck=(token, 'k07.small'),
                    board=('k07.small',)*7 if player == 1 else (), enemy=('k07.small',)*7 if player == 2 else ())
                original = g.state.players[1].deck[0]; self.play(g, 'k07.draw')
                self.assertIn(original, g.state.players[1].hand); self.assertEqual(len(g.state.draw_history), 2)
                visible = g.for_player(2).observe()['observation']['players'][0]['hand']
                self.assertEqual([row['card_id'] for row in visible], [token, None]); self.portable(g)

    def test_generation_and_other_physical_draw_do_not_activate_old_same_name(self):
        g = self.game(('k07.create_dragon', 'k07.draw', 'EDR_260t'), deck=('k07.small',))
        self.play(g, 'k07.create_dragon'); self.play(g, 'k07.draw')
        self.assertEqual(self.names(g).count('EDR_260t'), 2); self.assertEqual(g.state.players[1].board, [])
        self.assertEqual(len(g.state.draw_history), 1)

    def test_drawn_summon_wait_resumes_once_and_private_replacement_stays_hidden(self):
        g = self.game(('k07.draw',), deck=('EDR_260t', 'k07.small'), board=('k07.watch',), custom=registry(True))
        original = g.state.players[1].deck[0]; self.play(g, 'k07.draw')
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(self.names(g), [])
        self.assertEqual(self.names(g, 'deck'), ['k07.small']); other = self.portable(g, True)
        self.assertEqual(g.for_player(2).observe()['observation']['pending_choice'], {'player_id': 1})
        self.finish(g); self.finish(other); self.assertEqual(other.snapshot(), g.snapshot())
        self.assertEqual(g.state.players[1].board.count(original), 1); self.assertEqual(self.names(g), ['k07.small'])
        self.assertIsNone(g.for_player(2).observe()['observation']['players'][0]['hand'][0]['card_id'])
        self.portable(g, True)

    def test_late_unknown_summon_observer_rolls_back_draw_entity_rng_history_and_reveal(self):
        g = self.game(('k07.draw',), deck=('EDR_260t', 'k07.small'), board=('k07.watch',), custom=registry(fault=True))
        saved = g.snapshot()
        with self.assertRaises((ResolutionError, UnsupportedDefinitionError, ValueError)):
            self.play(g, 'k07.draw')
        self.assertEqual(g.snapshot(), saved)

    def test_acorn_armor_plague_and_tripwire_draw_cast_complete_and_replace(self):
        for token in ('SW_439t', 'JAIL_386t', 'JAIL_443t', 'JAIL_881t'):
            with self.subTest(token=token):
                g = self.game(('k07.draw',), deck=(token, 'k07.small'))
                original = g.state.players[1].deck[0]; self.play(g, 'k07.draw')
                self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD)
                self.assertEqual(self.names(g), ['k07.small']); self.assertEqual(len(g.state.play_history), 1)
                self.assertEqual([c.origin for c in g.state.cast_history], ['hand', 'draw'])
                if token == 'SW_439t': self.assertEqual(self.names(g, 'board'), ['SW_439t2'])
                if token == 'JAIL_386t': self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2)
                if token == 'JAIL_443t': self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 28)
                if token == 'JAIL_881t': self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 26)
                self.portable(g)

    def test_root_tripwire_shuffles_only_twice_and_spell_bonus_is_one_whole_budget(self):
        g = self.game(('JAIL_881',), deck=(), board=('k07.spellpower',))
        self.play(g, 'JAIL_881')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 25)
        self.assertEqual(self.names(g, 'deck'), ['JAIL_881t']*2)

    def test_two_damage_waves_requery_and_affect_resummoned_minion(self):
        g = self.game(('JAIL_307',), enemy=('k07.wave',), deck=('k07.small',)*25)
        self.assertEqual(self.price(g, 'JAIL_307'), 3); self.play(g, 'JAIL_307')
        self.assertEqual(self.names(g, 'board', 2), [])
        self.assertEqual(len(g.state.death_history), 2)
        self.assertEqual(g.state.play_history[-1].cost, 3); self.portable(g)

    def test_overload_discount_is_history_and_unlock_does_not_undo_it(self):
        g = self.game(('CATA_724', 'END_030', 'k07.kill'))
        self.assertEqual(self.price(g, 'END_030'), 6); wind = self.play(g, 'CATA_724')
        self.assertEqual(g.state.players[1].overload_owed, 3); self.assertEqual(self.price(g, 'END_030'), 3)
        self.play(g, 'k07.kill', wind)
        self.assertEqual(g.state.players[1].overload_owed, 0); self.assertEqual(self.price(g, 'END_030'), 3)
        saved = g.snapshot(); self.price(g, 'END_030'); self.assertEqual(g.snapshot(), saved)
        self.play(g, 'END_030'); self.assertEqual(g.state.play_history[-1].cost, 3); self.portable(g)

    def test_fel_spell_discount_and_actual_payment_share_count(self):
        g = self.game(('CATA_529', 'k07.fel', 'JAIL_386'))
        self.assertEqual(self.price(g, 'CATA_529'), 6); self.play(g, 'k07.fel'); self.play(g, 'JAIL_386')
        self.assertEqual(self.price(g, 'CATA_529'), 5); self.play(g, 'CATA_529')
        self.assertEqual(g.state.play_history[-1].cost, 5); self.portable(g)

    def test_hero_power_cost_and_own_refresh_ignore_opponent_use(self):
        g = self.game(('EDR_477', 'END_008')); self.play(g, 'END_008')
        self.assertEqual(self.price(g, 'EDR_477'), 6)
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id, target_id=g.state.players[2].hero_id))
        self.assertEqual(self.price(g, 'EDR_477'), 5); self.assertEqual(g.state.players[1].mana, 27)
        g.apply(EndTurn(1)); g.apply(UseHeroPower(2, g.state.players[2].hero_power_id))
        self.assertEqual(g.state.players[1].mana, 27); self.assertEqual(self.price(g, 'EDR_477'), 5)
        self.portable(g)

    def test_turn_death_discount_counts_both_sides_and_battlecry_draws_two(self):
        g = self.game(('END_004', 'k07.kill', 'k07.kill'), board=('k07.small',), enemy=('k07.small',))
        self.play(g, 'k07.kill', g.state.players[1].board[0]); self.play(g, 'k07.kill', g.state.players[2].board[0])
        self.assertEqual(self.price(g, 'END_004'), 5); self.play(g, 'END_004')
        self.assertEqual(g.state.play_history[-1].cost, 5); self.assertEqual(len(g.state.draw_history), 2)
        self.portable(g)

    def test_empty_crystals_are_for_both_players_without_refilling_spent_mana(self):
        g = self.game(('EDR_861', 'k07.kill')); eid = self.play(g, 'EDR_861')
        before = [g.state.players[p].mana for p in (1, 2)]
        self.play(g, 'k07.kill', eid)
        self.assertEqual([g.state.players[p].max_mana for p in (1, 2)], [31, 31])
        self.assertEqual([g.state.players[p].mana for p in (1, 2)], before)

    def test_nonstarter_cost_uses_genuine_opening_and_new_same_name_physical_card(self):
        r = registry(); base = tuple(f'k07.origin.{i}' for i in range(29))+('k07.boot',)
        decks = (DeckSpec('HERO_08', 'HERO_08bp', CardClass.MAGE, base),
                 DeckSpec('HERO_03', 'HERO_03bp', CardClass.ROGUE, base))
        policy = DeckPolicy('k07.test-pool', 'k07.experimental', 'experimental', tuple(r.cards))
        g = Game.from_decks(MatchSetup(decks, policy, 'GAME_005', 53, 1), r)
        while g.state.pending_choice:
            q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, ()))
        self.assertEqual(self.price(g, 'DINO_409'), 7)
        self.play(g, 'k07.generate'); self.assertEqual(self.price(g, 'DINO_409'), 6)
        generated = next(e for e in g.state.players[1].hand if e not in g.state.opening.original_entities[0]
            and g.state.entities[e].card_id.startswith('k07.origin.'))
        name = g.state.entities[generated].card_id
        original = next(e for e in g.state.players[1].hand if e in g.state.opening.original_entities[0]
            and g.state.entities[e].card_id == name)
        g.apply(PlayCard(1, original)); self.assertEqual(self.price(g, 'DINO_409'), 6)
        g.apply(PlayCard(1, generated)); self.assertEqual(self.price(g, 'DINO_409'), 5)
        self.play(g, 'DINO_409'); self.assertEqual(g.state.play_history[-1].cost, 5); self.portable(g)

    def test_nonstarter_price_refuses_scenario_without_original_deck_identity(self):
        with self.assertRaises(UnsupportedDefinitionError):
            g = self.game(('DINO_409',)); self.price(g, 'DINO_409')


if __name__ == '__main__':
    unittest.main()
