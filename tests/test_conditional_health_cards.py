"""Real conditional spells, complete quotation operands and original death results."""
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.conditional_health_cards import load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, Keyword,
    PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice, TriggerSpec, UseHandAction)
from hs_sim.engine.costs import capture_cost_input, capture_quote_fact, quote_cost, quote_generated_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, GainArmor, InvokeBehavior, RequestChoice,
    ReturnToHand, Silence)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.health_followups import InvokeHealthResult
from hs_sim.engine.intrinsic_costs import validate_intrinsic_origin
from hs_sim.engine.model import Zone
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.targets import canonical_digest


def registry(mode=None):
    r = build_registry()
    common = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())
    legend = replace(common, rarity=Rarity.LEGENDARY)
    for name, health, keywords, metadata, extra in (
        ('big', 8, (), common, {}), ('legend', 8, (), legend, {}),
        ('shield', 5, (Keyword.DIVINE_SHIELD,), common, {}),
        ('reborn', 5, (Keyword.REBORN,), common, {}),
        ('bonus', 8, (), common, dict(spell_damage=3)),
        ('sleep', 8, (), legend, dict(dormant_turns=3)),
        ('unknown', 8, (), replace(common, rarity=None), {}),
    ):
        r.register_card(CardDefinition('k16.'+name, name, CardType.MINION, attack=2, health=health,
            keywords=keywords, metadata=metadata, **extra))
    scripts = {
        'noop': lambda c: (),
        'hit': lambda c: (Damage(c.target_id, 1, c.source_id),),
        'wound': lambda c: (Damage(c.state.players[1].hero_id, 7, c.source_id),),
        'enemy_wound': lambda c: (Damage(c.state.players[2].hero_id, 7, c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'return': lambda c: (ReturnToHand(c.target_id),),
        'fail': lambda c: (AddToHand(c.player_id, 'missing.k16'),),
        'evil': lambda c: (Damage(c.target_id, 1, c.source_id, on_result='k16.evil_callback'),),
        'evil_callback': lambda c: (InvokeHealthResult('k16.noop', replace(c.event, sequence=c.event.sequence+1)),),
    }
    for name, body in scripts.items():
        r.register_behavior('k16.'+name, body)
        if name == 'evil_callback': continue
        r.register_card(CardDefinition('k16.'+name, name, CardType.SPELL, on_play='k16.'+name,
            metadata=common, requires_target=name in ('hit', 'silence', 'return', 'evil')))
    r.register_card(CardDefinition('k16.location', 'Legendary location', CardType.LOCATION,
        durability=3, on_use='k16.noop', metadata=legend))
    r.register_card(CardDefinition('k16.weapon', 'Legendary weapon', CardType.WEAPON,
        attack=1, durability=3, metadata=legend))
    if mode:
        def watch(c):
            if mode == 'split':
                if c.state.entities[c.event.source_id].card_id != 'CORE_BAR_311': return ()
                rows = [row for row in c.state.damage_history if row.health_result.source_card_id == 'CORE_BAR_311']
                if len(rows) != 1: return ()
            elif c.state.entities[c.event.target_id].card_id not in ('CORE_CS2_182', 'k16.reborn'):
                return ()
            return (RequestChoice(1, (
                ChoiceOption('ok', 'Continue original spell', (GainArmor(1, 1),)),
                ChoiceOption('bad', 'Rollback continuation', (InvokeBehavior('k16.fail', c.source_id, 1),)),
            ), c.source_id),)
        r.register_behavior('k16.watch', watch)
        r.register_card(CardDefinition('k16.watch', 'Observer', CardType.MINION, health=8, metadata=common,
            triggers=(TriggerSpec('damage_dealt' if mode == 'split' else 'minion_died', 'k16.watch'),)))
    return r


class ConditionalHealthCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.registry = registry()

    def game(self, hand=(), *, board=(), enemy=('k16.big',), weapon=None, mode=None, mana=30):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, weapon_card_id=weapon,
                deck=('CORE_CS2_182',)*5, mana=mana, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_08', board=enemy, deck=('CORE_CS2_182',)*5)), seed=241),
            registry(mode) if mode else self.registry)

    def eid(self, g, cid): return next(e for e in g.state.players[1].hand if g.state.entities[e].card_id == cid)
    def play(self, g, cid, target=None):
        eid = self.eid(g, cid); g.apply(PlayCard(1, eid, target)); return eid
    def hero(self, g, p=1): return g.state.entities[g.state.players[p].hero_id]
    def price(self, g, cid):
        state = g.state
        return quote_cost(state, g.registry, state.entities[self.eid(g, cid)]).amount
    def rows(self, g, cid): return [r.health_result for r in g.state.damage_history if r.health_result.source_card_id == cid]
    def choose(self, g, option='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (option,)))
    def portable(self, g, mode=None):
        saved = g.snapshot(); other = Game.from_snapshot(saved, registry(mode))
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(mode)).snapshot(), saved); return other

    def test_full_records_legacy_known_absence_and_unchanged_default_fingerprint(self):
        data = load_batch(); self.assertEqual(len(data['cards']), 6)
        for row in data['cards']:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
            self.assertEqual(self.registry.card(row['record']['id']).cost, row['recipe']['cost'])
            card = self.registry.card(row['record']['id'])
            self.assertEqual(Keyword.OUTCAST in card.keywords, row['record']['tags'].get('OUTCAST') == 1)
            self.assertEqual(Keyword.LIFESTEAL in card.keywords, row['record']['tags'].get('LIFESTEAL') == 1)
        self.assertEqual(len(data['known_unrarified_legacy']), 79)
        for row in data['known_unrarified_legacy']:
            self.assertFalse(row['record']['collectible']); self.assertNotIn('RARITY', row['record']['tags'])
            self.assertEqual(self.registry.card(row['record']['id']).metadata.rarity, Rarity.NONE)
        old = representative()
        self.assertEqual(old.fingerprint(), 'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')
        self.assertIsNone(old.card('GAME_005').metadata.rarity)

    def test_backstab_zero_cost_undamaged_domain_and_rejection_rolls_back(self):
        g = self.game(('k16.hit', 'CORE_CS2_072')); target = g.state.players[2].board[0]
        self.assertEqual(self.price(g, 'CORE_CS2_072'), 0)
        self.play(g, 'k16.hit', target); saved = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, 'CORE_CS2_072', target)
        self.assertEqual(g.snapshot(), saved)
        g = self.game(('CORE_CS2_072',)); target = g.state.players[2].board[0]
        self.play(g, 'CORE_CS2_072', target); self.assertEqual(g.state.entities[target].health, 6)
        self.assertEqual(g.state.players[1].mana, 30)

    def test_eye_beam_uses_original_hand_edges_and_single_slot(self):
        for hand, expected in ((('CORE_BT_801', 'k16.noop', 'k16.noop'), 1),
                               (('k16.noop', 'CORE_BT_801', 'k16.noop'), 3),
                               (('k16.noop', 'k16.noop', 'CORE_BT_801'), 1), (('CORE_BT_801',), 1)):
            g = self.game(hand); before = g.snapshot()
            self.assertEqual(self.price(g, 'CORE_BT_801'), expected); self.assertEqual(g.snapshot(), before)
            self.play(g, 'CORE_BT_801', g.state.players[2].board[0])
            self.assertEqual(g.state.players[1].mana, 30-expected)

    def test_eye_beam_requotes_after_neighbor_play_and_lifesteal_is_real(self):
        g = self.game(('k16.wound', 'CORE_BT_801', 'k16.noop'))
        self.assertEqual(self.price(g, 'CORE_BT_801'), 3)
        self.play(g, 'k16.wound'); self.assertEqual(self.price(g, 'CORE_BT_801'), 1)
        self.play(g, 'CORE_BT_801', g.state.players[2].board[0])
        self.assertEqual(self.hero(g).health, 26); self.portable(g)

    def test_eye_beam_fixed_intrinsic_one_precedes_external_preparation_discount(self):
        g = self.game(('CORE_BT_801', 'CORE_EX1_145')); self.play(g, 'CORE_EX1_145')
        self.assertEqual(self.price(g, 'CORE_BT_801'), 0)
        self.play(g, 'CORE_BT_801', g.state.players[2].board[0])
        self.assertEqual(g.state.players[1].mana, 30)

    def test_virtual_eye_beam_quote_cannot_borrow_an_actual_hand_position(self):
        g = self.game(('CORE_BT_801',)); before = g.snapshot()
        self.assertEqual(self.price(g, 'CORE_BT_801'), 1)
        self.assertEqual(quote_generated_cost(g.state, g.registry, 1, 'CORE_BT_801').amount, 3)
        self.assertEqual(g.snapshot(), before)

    def test_plague_enemy_minions_only_stops_empty_without_hitting_hero(self):
        g = self.game(('k16.wound', 'CORE_BAR_311'), enemy=('CORE_EX1_008',))
        self.play(g, 'k16.wound'); self.play(g, 'CORE_BAR_311')
        self.assertEqual([row.damage_dealt for row in self.rows(g, 'CORE_BAR_311')], [0, 1])
        self.assertEqual((self.hero(g).health, self.hero(g, 2).health), (24, 30))
        self.assertFalse(g.state.players[2].board)
        g = self.game(('CORE_BAR_311',), enemy=()); before = g.snapshot()['rng_state']
        self.play(g, 'CORE_BAR_311'); self.assertFalse(self.rows(g, 'CORE_BAR_311'))
        self.assertEqual(g.snapshot()['rng_state'], before)

    def test_plague_has_one_spell_bonus_budget_and_intrinsic_lifesteal_per_unit(self):
        g = self.game(('k16.wound', 'CORE_BAR_311'), board=('k16.bonus',))
        self.play(g, 'k16.wound'); self.play(g, 'CORE_BAR_311'); rows = self.rows(g, 'CORE_BAR_311')
        self.assertEqual(len(rows), 7); self.assertEqual(sum(row.damage_dealt for row in rows), 7)
        self.assertTrue(all(row.spell_bonus == 0 and row.damage_kind == 'spell' for row in rows))
        self.assertEqual((self.hero(g).health, self.hero(g, 2).health), (30, 30))

    def test_plague_real_split_wait_restores_rolls_back_and_continues_same_root(self):
        g = self.game(('CORE_BAR_311',), board=('k16.watch',), mode='split')
        self.play(g, 'CORE_BAR_311'); self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g, 'split'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g); self.choose(other); self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(self.rows(g, 'CORE_BAR_311')), 4); self.portable(g, 'split')

    def test_garona_requires_actual_printed_legendary_minion_and_trade_is_separate(self):
        g = self.game(('CATA_203',), enemy=('k16.big', 'k16.legend', 'CAP_107t'))
        for target in (g.state.players[2].board[0], g.state.players[2].board[2], self.hero(g, 2).id):
            saved = g.snapshot()
            with self.assertRaises(IllegalAction): self.play(g, 'CATA_203', target)
            self.assertEqual(g.snapshot(), saved)
        target = g.state.players[2].board[1]; self.play(g, 'CATA_203', target)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)

    def test_garona_can_trade_without_legendary_targets_and_does_not_cast(self):
        g = self.game(('CATA_203',), enemy=()); eid = self.eid(g, 'CATA_203')
        g.apply(UseHandAction(1, eid, 'trade'))
        self.assertEqual(g.state.players[1].mana, 29)
        self.assertFalse(any(e.kind == 'card_played' and e.source_id == eid for e in g.events))
        self.assertEqual(len(g.state.players[1].hand), 1)

    def test_controlled_legendary_includes_weapon_location_dormancy_and_quest(self):
        for kwargs in (dict(board=('k16.legend',)), dict(board=('k16.location',)),
                       dict(board=('k16.sleep',)), dict(weapon='k16.weapon')):
            g = self.game(('CATA_308',), **kwargs); self.assertEqual(self.price(g, 'CATA_308'), 1)
        g = self.game(('ULD_155', 'CATA_308')); self.assertEqual(self.price(g, 'CATA_308'), 5)
        self.play(g, 'ULD_155'); self.assertEqual(self.price(g, 'CATA_308'), 1)
        self.assertTrue(g.state.players[1].quests); self.portable(g)

    def test_controlled_legendary_excludes_hand_opponent_and_known_unrarified_token(self):
        for kwargs in (dict(enemy=('k16.legend',)), dict(board=('CAP_107t',)), dict()):
            g = self.game(('CORE_OG_044', 'CATA_308'), **kwargs)
            self.assertEqual(self.price(g, 'CATA_308'), 5)

    def test_controlled_legendary_silence_keeps_rarity_but_return_removes_presence(self):
        g = self.game(('CATA_308', 'k16.silence', 'k16.return'), board=('k16.legend',))
        target = g.state.players[1].board[0]
        self.play(g, 'k16.silence', target); self.assertEqual(self.price(g, 'CATA_308'), 1)
        self.play(g, 'k16.return', target); self.assertEqual(self.price(g, 'CATA_308'), 5)

    def test_medivh_keeps_original_one_payment_when_its_damage_kills_qualifier(self):
        g = self.game(('CATA_308', 'CATA_308'), board=('CORE_EX1_012',))
        self.play(g, 'CATA_308'); self.assertEqual(g.state.players[1].mana, 29)
        self.assertFalse(g.state.players[1].board); self.assertEqual(self.price(g, 'CATA_308'), 5)
        self.assertEqual(self.rows(g, 'CATA_308')[0].damage_dealt, 5); self.portable(g)

    def test_unknown_rarity_is_not_treated_as_a_known_nonlegendary(self):
        g = self.game(('CATA_308',), board=('k16.legend', 'k16.unknown'))
        with self.assertRaises(UnsupportedDefinitionError): self.price(g, 'CATA_308')
        g = self.game(('CATA_203',), enemy=('k16.unknown',))
        with self.assertRaisesRegex(ResolutionError, 'Printed rarity is unknown'):
            self.play(g, 'CATA_203', g.state.players[2].board[0])

    def test_purifying_breath_heals_enemy_hero_only_after_original_packet_death(self):
        for enemy, expected in (('CORE_CS2_182', 28), ('k16.big', 23), ('k16.shield', 23)):
            g = self.game(('k16.enemy_wound', 'CATA_303'), enemy=(enemy,))
            self.play(g, 'k16.enemy_wound'); self.play(g, 'CATA_303', g.state.players[2].board[0])
            self.assertEqual(self.hero(g, 2).health, expected)

    def test_purifying_breath_observes_original_death_even_when_reborn_body_survives(self):
        g = self.game(('k16.enemy_wound', 'CATA_303'), enemy=('k16.reborn',))
        original = g.state.players[2].board[0]; self.play(g, 'k16.enemy_wound'); self.play(g, 'CATA_303', original)
        self.assertEqual(self.hero(g, 2).health, 28)
        self.assertNotEqual(g.state.players[2].board[0], original)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health, 1)

    def test_purifying_breath_death_choice_retains_original_result_and_private_boundary(self):
        g = self.game(('k16.enemy_wound', 'CATA_303'), board=('k16.watch',), enemy=('CORE_CS2_182',), mode='death')
        self.play(g, 'k16.enemy_wound'); self.play(g, 'CATA_303', g.state.players[2].board[0])
        self.assertIsNotNone(g.state.pending_choice); other = self.portable(g, 'death'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g); self.choose(other); self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.hero(g, 2).health, 28); self.portable(g, 'death')
        public = json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        self.assertNotIn('"condition_facts"', public); self.assertNotIn('"pending_frames"', public)

    def test_health_result_continuation_rejects_forged_event_and_rolls_back(self):
        g = self.game(('k16.evil',)); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'k16.evil', g.state.players[2].board[0])
        self.assertEqual(g.snapshot(), saved)

    def test_hand_edge_quote_origin_rejects_truncated_original_order(self):
        g = self.game(('CORE_BT_801', 'k16.noop', 'k16.noop')); state = g.state
        fact = capture_quote_fact(state, g.registry, capture_cost_input(state.entities[self.eid(g, 'CORE_BT_801')]))
        match = fact.intrinsic.condition_facts[0]
        truncated = replace(match, hand=(match.hand[0], match.hand[-1]))
        changed = replace(fact.intrinsic, condition_facts=(truncated,))
        with self.assertRaises(ValueError): validate_intrinsic_origin(changed, state, g.registry)


if __name__ == '__main__': unittest.main()
