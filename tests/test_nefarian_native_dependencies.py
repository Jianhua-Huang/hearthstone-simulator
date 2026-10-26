"""Native generated dependencies and the real two-Mana continuous constraint."""
from dataclasses import asdict, replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.nefarian_native_dependencies import ROOTS, TOKEN, load_batch
from hs_sim.engine import (CardDefinition, CardMetadata, CardClass, CardType, EndTurn,
    Game, Keyword, PlayerSetup, Scenario)
from hs_sim.engine.costs import capture_generated_quote_fact, quote_cost
from hs_sim.engine.effects import AddCostModifier, Damage, DamageBatch, Destroy, Heal, Silence
from hs_sim.engine.intrinsic_costs import validate_generated_quote_fact
from hs_sim.engine.model import CostAuraSpec, CostSpec
from hs_sim.local_pool_format import build_cn37_local_pool_format
from tools import card_batch as batch

P = 'k545.'
FILLER = 'CORE_EX1_028'


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    fmt = build_cn37_local_pool_format(); r = fmt.registry
    bodies = {
        'hurt': lambda c: (Damage(c.target_id, 1, c.source_id),),
        'kill': lambda c: (Destroy(c.target_id),),
        'quiet': lambda c: (Silence(c.target_id),),
        'sweep': lambda c: (DamageBatch(tuple(Damage(i, 1, c.source_id)
            for player in c.state.players.values() for i in player.board)),),
        'hurt_hero': lambda c: (Damage(c.state.players[c.player_id].hero_id, 5, c.source_id),),
        'heal_hero': lambda c: (Heal(c.state.players[c.player_id].hero_id, 3, c.source_id),),
        'discount': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-10), source_id=c.source_id),),
        'increase': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=1), source_id=c.source_id),),
        'noop': lambda c: (),
    }
    for name, body in bodies.items():
        r.register_behavior(P+name, body)
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name,
            requires_target=name in ('hurt', 'kill', 'quiet'),
            metadata=CardMetadata(False, (CardClass.NEUTRAL,), None)))
    r.register_card(CardDefinition(P+'unit', 'unit', CardType.MINION, attack=1, health=1))
    r.validate()
    return fmt


class NefarianNativeDependencyTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(lambda mode, role: fixture(mode, role).registry)

    def game(self, hand, board=(), enemy=(), seed=1):
        fmt = fixture()
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_03', hand=tuple(hand), board=tuple(board),
                deck=(FILLER,)*6, max_mana=10, mana=10),
            PlayerSetup('HERO_08', board=tuple(enemy), deck=(FILLER,)*6)),
            seed=seed, generation_context=fmt.context), fmt.registry)

    def test_all_thirteen_faces_preserve_complete_original_records(self):
        data = load_batch(); rows = data['cards']+data['dependencies']
        self.assertEqual(tuple(x['record']['id'] for x in rows), (*ROOTS, TOKEN))
        self.assertEqual(batch.sha(data['source']), data['source_sha256'])
        original = {c['id']: c for c in batch.read(data['source'])}
        r = fixture().registry
        for row in rows:
            raw = row['record']; c = r.card(raw['id'])
            self.assertEqual(raw, original[c.id])
            self.assertEqual((c.name, c.cost, c.attack, c.health),
                tuple(raw[k] for k in ('name', 'cost', 'attack', 'health')))
            self.assertEqual(c.metadata.collectible, raw['collectible'])
        self.assertFalse(data['formal_pool_complete'])

    def test_native_shield_taunt_lifesteal_elusive_and_reborn_are_installed(self):
        cards = ('DEEP_006', 'ICC_913', 'ULD_275', 'ULD_185', 'JAM_007')
        game = self.game(cards)
        for cid in cards:
            if game.state.players[1].mana < game.registry.card(cid).cost:
                game.apply(EndTurn(1)); game.apply(EndTurn(2))
            ident = self.play(game, cid)
            self.assertTrue(set(game.registry.card(cid).keywords) <= game.state.entities[ident].keywords)
        self.portable(game)

    def test_soloist_requires_real_combo_and_first_play_has_no_poison(self):
        game = self.game(('JAM_021',))
        ident = self.play(game, 'JAM_021')
        self.assertIn(Keyword.RUSH, game.state.entities[ident].keywords)
        self.assertNotIn(Keyword.POISONOUS, game.state.entities[ident].keywords)
        game = self.game((P+'noop', 'JAM_021'))
        self.play(game, P+'noop'); ident = self.play(game, 'JAM_021')
        self.assertIn(Keyword.POISONOUS, game.state.entities[ident].keywords)
        self.portable(game)

    def test_squallhunter_spell_damage_and_real_next_turn_overload(self):
        game = self.game(('DRG_211', 'CORE_CS2_029'))
        self.play(game, 'DRG_211')
        self.assertEqual(game.state.players[1].overload_owed, 2)
        self.play(game, 'CORE_CS2_029', game.state.players[2].hero_id)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 22)
        game.apply(EndTurn(1)); game.apply(EndTurn(2))
        self.assertEqual(game.state.players[1].overload_locked, 2)
        self.portable(game)

    def test_mechanical_whelp_death_summons_its_real_seven_seven_token(self):
        game = self.game(('BOT_066', P+'kill'))
        ident = self.play(game, 'BOT_066'); self.play(game, P+'kill', ident)
        token = self.entity(game, TOKEN, zone='board')
        self.assertEqual((token.attack, token.health), (7, 7))
        self.assertEqual(game.state.players[1].board, [token.id])
        self.portable(game)

    def test_plagued_protodrake_death_uses_real_seven_cost_minion_domain(self):
        game = self.game(('SCH_711', P+'kill'), seed=4)
        ident = self.play(game, 'SCH_711'); self.play(game, P+'kill', ident)
        self.assertEqual(len(game.state.players[1].board), 1)
        token = game.state.entities[game.state.players[1].board[0]]
        self.assertEqual(game.registry.card(token.card_id).cost, 7)
        self.assertNotEqual(token.card_id, 'SCH_711')
        self.portable(game)

    def test_volcanic_drake_counts_both_sides_actual_deaths_and_resets(self):
        game = self.game((P+'sweep', 'BRM_025', 'BRM_025'),
            board=(P+'unit',), enemy=(P+'unit',))
        self.play(game, P+'sweep')
        self.assertEqual(quote_cost(game.state, game.registry, self.entity(game, 'BRM_025')).amount, 4)
        self.play(game, 'BRM_025')
        self.assertEqual(game.state.play_history[-1].cost, 4)
        game.apply(EndTurn(1)); game.apply(EndTurn(2))
        self.assertEqual(quote_cost(game.state, game.registry, self.entity(game, 'BRM_025')).amount, 6)
        self.portable(game)

    def test_happy_ghoul_requires_effective_own_hero_heal_and_resets(self):
        game = self.game((P+'heal_hero', P+'hurt_hero', P+'heal_hero', 'ICC_700', 'ICC_700'))
        self.play(game, P+'heal_hero')
        self.assertEqual(quote_cost(game.state, game.registry, self.entity(game, 'ICC_700')).amount, 3)
        self.play(game, P+'hurt_hero'); self.play(game, P+'heal_hero')
        self.assertEqual(quote_cost(game.state, game.registry, self.entity(game, 'ICC_700')).amount, 0)
        self.play(game, 'ICC_700'); self.assertEqual(game.state.play_history[-1].cost, 0)
        game.apply(EndTurn(1)); game.apply(EndTurn(2))
        self.assertEqual(quote_cost(game.state, game.registry, self.entity(game, 'ICC_700')).amount, 3)
        self.portable(game)

    def test_temple_berserker_loses_conditional_attack_on_healing(self):
        game = self.game(('ULD_185', P+'hurt', 'CORE_CS2_117'))
        ident = self.play(game, 'ULD_185'); self.play(game, P+'hurt', ident)
        self.assertEqual(game.state.entities[ident].attack, 3)
        self.play(game, 'CORE_CS2_117', ident)
        self.assertEqual(game.state.entities[ident].attack, 1)
        self.portable(game)

    def test_final_floor_overrides_later_discount_and_saved_payment(self):
        game = self.game((P+'discount', P+'noop', P+'quiet', P+'noop'), board=('TTN_924',))
        self.play(game, P+'discount')
        self.assertEqual(quote_cost(game.state, game.registry, self.entity(game, P+'noop')).amount, 2)
        self.play(game, P+'noop'); self.assertEqual(game.state.play_history[-1].cost, 2)
        self.portable(game)
        floor = self.entity(game, 'TTN_924', zone='board').id
        self.play(game, P+'quiet', floor)
        self.assertEqual(quote_cost(game.state, game.registry, self.entity(game, P+'noop')).amount, 0)
        self.portable(game)

    def test_final_floor_never_becomes_an_early_additive_increase(self):
        game = self.game((P+'increase', P+'noop'), board=('TTN_924',))
        self.play(game, P+'increase')
        self.assertEqual(quote_cost(game.state, game.registry, self.entity(game, P+'noop')).amount, 2)
        fact = capture_generated_quote_fact(game.state, game.registry, 1, P+'noop')
        self.assertEqual(fact.amount, 2)
        validate_generated_quote_fact(game.registry, fact)
        with self.assertRaises(ValueError):
            validate_generated_quote_fact(game.registry, replace(fact, amount=3))
        self.play(game, P+'noop'); self.portable(game)

    def test_floor_is_bilateral_stacks_as_a_constraint_and_rejects_other_recipes(self):
        game = self.game((P+'noop',), board=('TTN_924',), enemy=('TTN_924',))
        first = capture_generated_quote_fact(game.state, game.registry, 1, P+'noop')
        second = capture_generated_quote_fact(game.state, game.registry, 2, P+'noop')
        self.assertEqual((first.amount, second.amount), (2, 2))
        self.assertEqual(len(first.contributions), 2)
        validate_generated_quote_fact(game.registry, first)
        validate_generated_quote_fact(game.registry, second)
        self.play(game, P+'noop'); self.portable(game)
        with self.assertRaises(ValueError):
            CostAuraSpec(CostSpec(delta=-1, minimum=2), 'all_cards_minimum')


if __name__ == '__main__':
    unittest.main()
