import json
import unittest
from functools import lru_cache

from hs_sim.cards import build_registry
from hs_sim.cards.native_pool_hand_copy_cards import AGENT, CALLING, ELEMENTAL, PREFIX, load_batch
from hs_sim.cards.neptulon_entry_stat_card import NEPTULON
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction, PlayCard,
    PlayerSetup, ResolutionError, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Destroy,
    GainArmor, GrantDeathrattle, RequestChoice)
from hs_sim.engine.costs import local_cost
from hs_sim.engine.model import CardClass, CardMetadata, CostSpec, Rarity
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.registry import RuleContext, UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import CardReference, CopyCard, ModifyStoredCost
from tools.card_batch import check_face

P = 'fixture.native_pool_hand_copy.'
(ONE, TWO, THREE, FIVE, DEATH, PLAIN, ZERO, SPELL2, FOREIGN2, SPELL3, SPELL5,
 KILL, DISCOUNT, HAND_GRANT, CHEAP, WATCH) = tuple(P+x for x in (
    'one', 'two', 'three', 'five', 'death', 'plain', 'zero', 'spell2', 'foreign2', 'spell3', 'spell5',
    'kill', 'discount', 'hand_grant', 'cheap', 'watch'))
COIN = 'GAME_005'
CTX = GenerationContext('k336-explicit-known-domain', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(maxsize=None)
def fixture(mode='normal', role='writer'):
    if role not in ('writer', 'reader'):
        raise ValueError('Independent fixture registries required')
    r = build_registry()
    r.register_behavior(P+'reward', lambda c: (AddToHand(c.player_id, COIN, c.source_id),))
    for cid, cost in ((ONE, 1), (TWO, 2), (THREE, 3), (FIVE, 5), (DEATH, 2), (PLAIN, 2)):
        meta = CardMetadata(True, (CardClass.WARRIOR,), Rarity.COMMON, tribes=())
        card = CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=cost, health=cost+4,
            deathrattle=P+'reward' if cid == DEATH else None, metadata=meta)
        r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    for cid, cost, cls in ((ZERO, 0, CardClass.NEUTRAL), (SPELL2, 2, CardClass.PRIEST),
            (FOREIGN2, 2, CardClass.WARLOCK), (SPELL3, 3, CardClass.SHAMAN), (SPELL5, 5, CardClass.WARRIOR)):
        r.register_behavior(cid, lambda c: (GainArmor(c.player_id, 1),))
        card = CardDefinition(cid, cid, CardType.SPELL, cost=cost, on_play=cid,
            metadata=CardMetadata(True, (cls,), Rarity.COMMON, tribes=()))
        r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    target = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
    def discount(c):
        return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),
            CostSpec(set_to=3 if c.state.entities[i].card_id == FIVE else 1), c.source_id)
            for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id in (FIVE, DEATH))
    def grant(c):
        return tuple(effect for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id == PLAIN for effect in (
                GrantDeathrattle(i, P+'reward', c.source_id),
                CopyCard(MinionReference.capture(c.state.entities[i]), c.player_id, mode='current', source_id=c.source_id)))
    bodies = {KILL: lambda c: (Destroy(c.target_id, c.source_id),), DISCOUNT: discount, HAND_GRANT: grant,
        CHEAP: lambda c: (AddCostModifier(c.player_id, CostSpec(set_to=0, card_types=(CardType.MINION,)),
            uses_remaining=1, source_id=c.source_id),)}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=target if cid == KILL else None))
    members = () if mode == 'empty' else (ONE, TWO, THREE, FIVE, ZERO, SPELL2, FOREIGN2, SPELL3, SPELL5)
    entries = tuple(PoolMember(cid) for cid in members)
    if mode in ('unknown_minion', 'unknown_spell'):
        unknown = P+mode
        r.register_pool_card(PoolCard(unknown, CardType.MINION if mode == 'unknown_minion' else CardType.SPELL,
            2, CardMetadata(True, (CardClass.PALADIN,), Rarity.COMMON, tribes=()),
            battlecry=False, deathrattle=False, choose_one=False))
        entries += (PoolMember(unknown),)
    r.register_pool(PoolDefinition('constructed.cards', 'explicit-v1', CTX.target_id, CTX.mode, entries, complete=True))
    if mode in ('summon_wait', 'copy_wait', 'copy_fail', 'death_gift'):
        def observe(c):
            entity = c.state.entities.get(c.event.target_id)
            if entity is None:
                return ()
            if mode == 'death_gift':
                return (AddToHand(c.player_id, DEATH, c.source_id),) if entity.card_id == AGENT else ()
            if mode == 'summon_wait':
                if entity.card_id not in (ONE, TWO, THREE, FIVE): return ()
            elif entity.copy_origin is None:
                return ()
            if mode == 'copy_fail':
                raise ResolutionError('Explicit late physical copy observer failure')
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),), c.source_id),)
        event = 'minion_died' if mode == 'death_gift' else 'minion_summoned' if mode == 'summon_wait' else 'card_added_to_hand'
        r.register_behavior(WATCH, observe)
        r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
            triggers=(TriggerSpec(event, WATCH),)))
    return r


class NativePoolHandCopyTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), mode='normal', other_hand=(), seed=0):
        if mode in ('summon_wait', 'copy_wait', 'copy_fail', 'death_gift'): board = (WATCH,)+board
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(COIN,)*10, mana=10, max_mana=10),
            PlayerSetup('HERO_08', hand=other_hand, board=enemy, deck=(COIN,)*10, mana=10, max_mana=10)),
            seed=seed, generation_context=CTX), fixture(mode))

    def play(self, g, cid, target=None, player=1):
        eid = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(player, eid, target_id=target)); return eid

    def choose(self, g, cid=None):
        c = g.state.pending_choice
        option = next((o.id for o in c.options if o.card_id == cid), c.options[0].id)
        g.apply(SelectChoice(c.player_id, c.id, (option,)))

    def portable(self, g, mode='normal'):
        saved = g.snapshot(); r = fixture(mode, 'reader')
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)), r).snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        for player in (1, 2):
            visible = json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for key in ('"rng_state"', '"pool_basis"', '"cast_history"', '"resolution_frame"'):
                self.assertNotIn(key, visible)

    def copies(self, g):
        return [e for e in g.state.entities.values() if e.copy_origin is not None]

    def test_complete_three_source_rows_and_six_full_primary_faces(self):
        data = load_batch(); r = fixture()
        self.assertEqual(len(data['official_observations']), 6)
        rows = {x['record']['id']: x['record'] for x in data['cards']}
        for observation in data['official_observations']:
            check_face(rows[observation['card_id']], observation['face'], observation['locale'])
        self.assertEqual((r.card(CALLING).cost, r.card(ELEMENTAL).attack, r.card(AGENT).deathrattle),
            (2, 2, PREFIX+'agent'))
        self.assertEqual(r.card(ELEMENTAL).metadata.tribes, ('elemental',))

    def test_calling_paid_friendly_target_summons_any_class_same_cost_without_destroying_target(self):
        g = self.game((CALLING,), (TWO,)); target = g.state.players[1].board[0]
        self.play(g, CALLING, target)
        self.assertEqual(g.state.players[1].mana, 8)
        self.assertEqual(len(g.state.players[1].board), 2)
        self.assertEqual(g.state.entities[target].zone, Zone.BOARD)
        self.assertEqual(g.state.entities[g.state.players[1].board[-1]].card_id, TWO)
        self.portable(g)

    def test_calling_reads_retained_local_cost_after_actual_hand_play(self):
        g = self.game((DISCOUNT, FIVE, CALLING)); self.play(g, DISCOUNT)
        target = self.play(g, FIVE); self.assertEqual(g.state.players[1].mana, 7)
        self.play(g, CALLING, target)
        self.assertEqual(g.state.entities[g.state.players[1].board[-1]].card_id, THREE)

    def test_calling_does_not_use_previous_paid_price_or_live_hand_only_modifier(self):
        g = self.game((CHEAP, FIVE, CALLING)); self.play(g, CHEAP)
        target = self.play(g, FIVE); self.assertEqual(g.state.players[1].mana, 10)
        self.play(g, CALLING, target)
        self.assertEqual(g.state.entities[g.state.players[1].board[-1]].card_id, FIVE)

    def test_calling_rejects_enemy_target_and_has_no_summon_when_full(self):
        g = self.game((CALLING,), (TWO,), (TWO,)); saved = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, CALLING, g.state.players[2].board[0])
        self.assertEqual(g.snapshot(), saved)
        g = self.game((CALLING,), (TWO,)*7); self.play(g, CALLING, g.state.players[1].board[0])
        self.assertEqual(len(g.state.players[1].board), 7)

    def test_calling_summon_wait_is_portable_and_does_not_duplicate(self):
        g = self.game((CALLING,), (TWO,), mode='summon_wait')
        target = g.state.players[1].board[-1]; self.play(g, CALLING, target)
        self.assertIsNotNone(g.state.pending_choice); self.portable(g, 'summon_wait')
        self.choose(g); self.assertEqual(len(g.state.players[1].board), 3)

    def test_unknown_eligible_pool_entries_fail_without_pruning_and_roll_back(self):
        for mode, cid in (('unknown_minion', CALLING), ('unknown_spell', ELEMENTAL)):
            with self.subTest(mode=mode):
                g = self.game((cid,), (TWO,), mode=mode); saved = g.snapshot()
                with self.assertRaises((ResolutionError, UnsupportedDefinitionError)):
                    self.play(g, cid, g.state.players[1].board[0] if cid == CALLING else None)
                self.assertEqual(g.snapshot(), saved)

    def test_elemental_offers_any_class_at_current_attack_and_pays_zero_on_selection(self):
        g = self.game((ELEMENTAL,)); self.play(g, ELEMENTAL)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {SPELL2, FOREIGN2})
        self.portable(g); self.choose(g, FOREIGN2)
        self.play(g, FOREIGN2); self.assertEqual(g.state.players[1].mana, 7)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 1)
        self.portable(g)

    def test_elemental_zero_price_expires_at_actual_turn_end(self):
        g = self.game((ELEMENTAL,)); self.play(g, ELEMENTAL); self.choose(g, SPELL2)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); before = g.state.players[1].mana
        self.play(g, SPELL2); self.assertEqual(g.state.players[1].mana, before-2)

    def test_elemental_reads_real_neptulon_pre_battlecry_five_attack(self):
        g = self.game((NEPTULON, ELEMENTAL)); self.play(g, NEPTULON); eid = self.play(g, ELEMENTAL)
        self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].health), (5, 5))
        self.assertEqual(tuple(o.card_id for o in g.state.pending_choice.options), (SPELL5,))
        self.choose(g); self.assertEqual(g.state.players[1].mana, 0)
        self.play(g, SPELL5); self.assertEqual(g.state.players[1].mana, 0)

    def test_empty_complete_domain_has_no_choice_or_phantom_card(self):
        for cid in (CALLING, ELEMENTAL):
            with self.subTest(cid=cid):
                g = self.game((cid,), (TWO,), mode='empty')
                self.play(g, cid, g.state.players[1].board[0] if cid == CALLING else None)
                self.assertIsNone(g.state.pending_choice); self.assertFalse(g.state.players[1].hand)

    def test_agent_copies_current_physical_hand_card_and_keeps_original(self):
        g = self.game((DISCOUNT, KILL, DEATH), (AGENT,), other_hand=(PLAIN,))
        self.play(g, DISCOUNT)
        original = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == DEATH)
        self.play(g, KILL, g.state.players[1].board[0]); copies = self.copies(g)
        self.assertEqual(len(copies), 1); self.assertNotEqual(copies[0].id, original)
        self.assertEqual(copies[0].card_id, DEATH); self.assertEqual(copies[0].zone, Zone.HAND)
        self.assertEqual(local_cost(copies[0])[0], 1)
        self.assertEqual(g.state.entities[original].zone, Zone.HAND)
        self.assertEqual(len(g.state.players[2].hand), 1)
        self.assertNotIn(DEATH, json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2)))
        self.portable(g)

    def test_agent_excludes_same_card_and_non_deathrattle_minions(self):
        g = self.game((KILL, AGENT, PLAIN, COIN), (AGENT,))
        self.play(g, KILL, g.state.players[1].board[0]); self.assertEqual(self.copies(g), [])

    def test_agent_current_granted_deathrattle_is_eligible_and_copied(self):
        g = self.game((HAND_GRANT, KILL), (AGENT, PLAIN)); self.play(g, HAND_GRANT)
        self.assertEqual(len(self.copies(g)), 1)
        self.play(g, KILL, g.state.players[1].board[0]); copies = self.copies(g)
        self.assertEqual(len(copies), 2); self.assertEqual(copies[-1].card_id, PLAIN)
        self.assertTrue(any(a.kind == 'deathrattle' for a in copies[-1].abilities)); self.portable(g)

    def test_agent_duplicate_printed_cards_keep_independent_physical_weights(self):
        g = self.game((DEATH, DEATH, PLAIN), (AGENT,)); source = g.state.players[1].board[0]
        requests = fixture().behavior(PREFIX+'agent.now')(RuleContext(g.state, source, 1))
        self.assertEqual(len(requests), 1); request = requests[0]
        self.assertEqual(len(request.options), 2)
        self.assertEqual(len({o.id for o in request.options}), 2)
        self.assertEqual(tuple(o.card_id for o in request.options), (DEATH, DEATH))

    def test_agent_observes_hand_card_added_by_earlier_actual_death_reaction(self):
        g = self.game((KILL,), (AGENT,), mode='death_gift')
        self.play(g, KILL, g.state.players[1].board[-1])
        self.assertEqual(len(self.copies(g)), 1); self.assertEqual(self.copies(g)[0].card_id, DEATH)

    def test_agent_copy_wait_and_full_hand_overflow_use_ordinary_delivery(self):
        g = self.game((KILL, DEATH), (AGENT,), mode='copy_wait')
        self.play(g, KILL, g.state.players[1].board[-1]); self.portable(g, 'copy_wait')
        self.choose(g); self.assertEqual(len(self.copies(g)), 1)
        g = self.game((KILL,)+(COIN,)*9, (AGENT,), mode='death_gift')
        self.play(g, KILL, g.state.players[1].board[-1])
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertEqual(len(self.copies(g)), 1); self.assertEqual(self.copies(g)[0].zone, Zone.GRAVEYARD)

    def test_agent_late_copy_observer_failure_rolls_back_death_hand_and_rng(self):
        g = self.game((KILL, DEATH), (AGENT,), mode='copy_fail'); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Explicit late physical copy'):
            self.play(g, KILL, g.state.players[1].board[-1])
        self.assertEqual(g.snapshot(), saved)
