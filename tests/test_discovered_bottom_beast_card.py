"""Original two Beast discoveries receive additive numbers before bottom-deck notices."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.discovered_bottom_beast_card import (
    CARD, GRANT, POOL_ID, QUERY, load_batch, register_discovered_bottom_beast_card)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, Keyword,
    PlayCard, PlayerSetup, Rarity, Registry, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.effects import ChoiceOption, Destroy, Draw, GainArmor, InvokeBehavior, RequestChoice, Silence, Summon
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.pools import DiscoverFromPool, GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay

P = 'k209.'
HERO, DRUID_HERO, A, B, ALL, DRUID, OTHER, NONBEAST, SPELL, HIDDEN, FILL, WATCH, UNKNOWN = (
    P+x for x in ('hero', 'druid_hero', 'a', 'b', 'all', 'druid', 'other', 'nonbeast',
                 'spell', 'hidden', 'fill', 'watch', 'unknown'))
MEMBERS = (A, B, ALL, DRUID, OTHER, NONBEAST, SPELL, HIDDEN)
CTX = GenerationContext('k209-explicit-current-beasts', 'experimental')


@lru_cache(None)
def registry(members=MEMBERS, mode=None, pool=True):
    r = Registry(P+'host'); register_discovered_bottom_beast_card(r)
    r.register_behavior(P+'empty', lambda c: ())
    r.register_behavior(P+'marker', lambda c: (GainArmor(c.player_id, 9),))
    for cid, cls in ((HERO, CardClass.MAGE), (DRUID_HERO, CardClass.DRUID)):
        r.register_card(CardDefinition(cid, cid, CardType.HERO, health=80,
            metadata=CardMetadata(False, (cls,), Rarity.NONE)))
    for cid, cls, tribes, collectible, attack, health in (
        (A, CardClass.MAGE, ('beast',), True, 1, 2),
        (B, CardClass.NEUTRAL, ('beast',), True, 3, 4),
        (ALL, CardClass.NEUTRAL, ('all',), True, 2, 1),
        (DRUID, CardClass.DRUID, ('beast',), True, 2, 3),
        (OTHER, CardClass.WARLOCK, ('beast',), True, 3, 3),
        (NONBEAST, CardClass.MAGE, ('elemental',), True, 4, 4),
        (HIDDEN, CardClass.MAGE, ('beast',), False, 5, 5),
    ):
        card = CardDefinition(cid, cid, CardType.MINION, cost=1, attack=attack, health=health,
            battlecry=P+'marker' if cid == A else None,
            keywords=(Keyword.TAUNT,) if cid == B else (),
            metadata=CardMetadata(collectible, (cls,), Rarity.COMMON, tribes=tribes))
        r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    for cid in (SPELL, FILL):
        card = CardDefinition(cid, cid, CardType.SPELL, on_play=P+'empty',
            metadata=CardMetadata(True, (CardClass.MAGE,), Rarity.COMMON))
        r.register_card(card)
        if cid == SPELL: r.register_pool_card(PoolCard.from_definition(card))
    if UNKNOWN in members:
        r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 1,
            CardMetadata(True, (CardClass.MAGE,), Rarity.COMMON, tribes=('beast',)),
            battlecry=False, deathrattle=False, choose_one=False))
    if pool: r.register_pool(PoolDefinition(POOL_ID, P+'complete-v1', CTX.target_id, CTX.mode,
        tuple(PoolMember(cid) for cid in members), complete=True))
    r.register_behavior(P+'draw', lambda c: (Draw(c.player_id, 3, c.source_id),))
    r.register_behavior(P+'silence', lambda c: (Silence(c.target_id),))
    r.register_behavior(P+'summon', lambda c: (Summon(c.player_id, CARD, c.source_id),))
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('K209 deliberate failure')))
    for name in ('draw', 'silence', 'summon'):
        fields = dict(targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))) if name == 'silence' else {}
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name, **fields))

    def watch(c):
        source = c.state.entities.get(c.event.source_id)
        target = c.state.entities.get(c.event.target_id)
        if (source is None or source.card_id != CARD or target is None
                or target.kind != CardType.MINION or target.zone != Zone.DECK
                or c.event.player_id != c.player_id): return ()
        if mode == 'inspect':
            definition = r.card(target.card_id)
            complete = (target.attack, target.max_health) == (definition.attack+5, definition.health+5)
            return (GainArmor(c.player_id, 10 if complete else 1),)
        if mode == 'destroy_source':
            return (Destroy(source.id, c.source_id),) if source.zone == Zone.BOARD else ()
        if mode == 'fail': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue'),
            ChoiceOption('bad', 'Rollback', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
        ), c.source_id),)
    r.register_behavior(P+'watch', watch)
    events = ('card_created', 'card_added_to_deck') if mode == 'inspect' else (
        'card_added_to_deck',) if mode in ('added', 'fail') else ('card_created',)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20,
        triggers=() if mode is None else tuple(TriggerSpec(e, P+'watch') for e in events)))
    r.validate(); return r


class DiscoveredBottomBeastTests(unittest.TestCase):
    def game(self, hand=(CARD,), board=(), actor=1, hero=HERO, members=MEMBERS, mode=None, pool=True):
        self.config = members, mode, pool
        own = PlayerSetup(hero, hand=hand, board=board, deck=(FILL, FILL), mana=80, max_mana=80, mana_cap=80)
        other = PlayerSetup(HERO, hand=(SPELL,), deck=(FILL, FILL), mana=80, max_mana=80, mana_cap=80)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own),
            active_player=actor, seed=209, generation_context=CTX), registry(*self.config))

    def play(self, g, cid=CARD, target=None):
        p = g.state.active_player
        eid = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(p, eid, target)); return eid
    def choose(self, g, cid=None, key='ok'):
        q = g.state.pending_choice
        if cid is not None: key = next(x.id for x in q.options if x.card_id == cid)
        g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def finish(self, g, picks=(A, B)):
        index = 0
        while g.state.pending_choice is not None:
            if g.state.pending_choice.purpose.value == 'pool_discovery':
                self.choose(g, picks[index]); index += 1
            else: self.choose(g)
        return index
    def outputs(self, g, player=None):
        p = g.state.active_player if player is None else player
        return [g.state.entities[i] for i in g.state.players[p].deck if g.state.entities[i].kind == CardType.MINION]
    def armor(self, g):
        p = g.state.active_player
        return g.state.entities[g.state.players[p].hero_id].armor
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); r = registry.__wrapped__(*self.config)
        self.assertEqual(Game.from_snapshot(deepcopy(saved), r).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        return Game.from_snapshot(deepcopy(saved), r)

    def test_complete_real_face_and_central_assembly(self):
        from hs_sim.cards import build_registry
        r = build_registry(); c = r.card(CARD)
        self.assertEqual((c.name, c.cost, c.attack, c.health), ('卡多雷培育师', 2, 2, 3))
        self.assertEqual(c.metadata.classes, (CardClass.DRUID,))
        self.assertEqual(len(load_batch()['official_observations']), 2)
        self.assertNotIn('TIME_730e', r.cards)

    def test_two_real_discoveries_deliver_in_selection_order_at_bottom_without_hand_or_shuffle(self):
        g = self.game(); prefix = tuple(g.state.players[1].deck); source = self.play(g)
        self.assertEqual(g.state.players[1].mana, 78)
        self.choose(g, A)
        self.assertEqual(tuple(g.state.players[1].deck[:2]), prefix)
        self.assertEqual([e.card_id for e in self.outputs(g)], [A])
        self.assertEqual(g.state.pending_choice.purpose.value, 'pool_discovery')
        before = g._rng.getstate(); self.choose(g, B)
        self.assertEqual(g._rng.getstate(), before)
        self.assertEqual([e.card_id for e in self.outputs(g)], [A, B])
        self.assertEqual([(e.attack, e.max_health) for e in self.outputs(g)], [(6, 7), (8, 9)])
        self.assertFalse(g.state.players[1].hand)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health), (2, 3))
        self.assertFalse(g.state.cast_history)
        self.assertFalse(any(e.kind == 'deck_shuffled' for e in g.events))
        self.assertEqual(sum(e.kind == 'card_discovered' for e in g.events), 2)

    def test_current_actor_class_not_printed_source_class_and_all_tribes_are_beasts(self):
        for hero, expected in ((HERO, {A, B, ALL}), (DRUID_HERO, {DRUID, B, ALL})):
            with self.subTest(hero=hero):
                g = self.game(hero=hero); self.play(g)
                self.assertEqual({x.card_id for x in g.state.pending_choice.options}, expected)
                self.choose(g, ALL); self.choose(g, B)
                self.assertEqual((self.outputs(g)[0].attack, self.outputs(g)[0].max_health), (7, 6))

    def test_same_selected_face_can_recur_with_two_fresh_independent_grants(self):
        g = self.game(members=(A,)); self.play(g); self.choose(g, A); self.choose(g, A)
        a, b = self.outputs(g)
        self.assertNotEqual(a.id, b.id)
        self.assertEqual((a.attack, a.max_health, b.attack, b.max_health), (6, 7, 6, 7))
        self.assertNotEqual(a.enchantments[-1].id, b.enchantments[-1].id)

    def test_full_creation_numbers_are_present_at_both_initial_notifications(self):
        g = self.game(board=(WATCH,), mode='inspect'); self.play(g); self.finish(g)
        self.assertEqual(self.armor(g), 40)

    def test_each_original_choice_and_creation_wait_restores_without_redraw(self):
        g = self.game(board=(WATCH,), mode='created'); self.play(g)
        for cid in (A, B):
            other = self.portable(g); self.choose(g, cid); self.choose(other, cid)
            self.assertEqual(g.snapshot(), other.snapshot())
            other = self.portable(g); self.choose(g); self.choose(other)
            self.assertEqual(g.snapshot(), other.snapshot())
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual([e.card_id for e in self.outputs(g)], [A, B])

    def test_added_notification_wait_and_failed_continuation_keep_original_output(self):
        g = self.game(board=(WATCH,), mode='added'); self.play(g); self.choose(g, A)
        other = self.portable(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, key='bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.choose(g, B); self.choose(g)
        self.assertEqual(len(self.outputs(g)), 2)

    def test_failed_creation_reaction_restores_original_selected_choice_and_rng(self):
        g = self.game(board=(WATCH,), mode='fail'); self.play(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, A)
        self.assertEqual(g.snapshot(), before)

    def test_invalid_selection_preserves_paid_original_discovery(self):
        g = self.game(); self.play(g); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.choose(g, key='not-an-option')
        self.assertEqual(g.snapshot(), before)

    def test_original_source_death_does_not_cancel_accepted_second_discovery(self):
        g = self.game(board=(WATCH,), mode='destroy_source'); source = self.play(g)
        self.choose(g, A)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.choose(g, B)
        self.assertEqual([e.card_id for e in self.outputs(g)], [A, B])

    def test_second_seat_keeps_outputs_in_its_own_deck(self):
        g = self.game(actor=2); first_deck = tuple(g.state.players[1].deck)
        self.play(g); self.finish(g)
        self.assertEqual(tuple(g.state.players[1].deck), first_deck)
        self.assertTrue(all(e.owner == e.controller == 2 for e in self.outputs(g, 2)))
        self.assertEqual(g.state.players[2].mana, 78)

    def test_high_hand_occupancy_does_not_receive_or_burn_discovered_deck_cards(self):
        g = self.game(hand=(CARD,)+(FILL,)*9); self.play(g); hand = tuple(g.state.players[1].hand)
        self.finish(g)
        self.assertEqual(tuple(g.state.players[1].hand), hand)
        self.assertEqual(len(self.outputs(g)), 2)
        self.assertFalse(any(e.kind == 'card_burned' for e in g.events))

    def test_draw_play_and_silence_use_the_original_common_lifecycle(self):
        g = self.game(hand=(CARD, P+'draw', P+'silence')); self.play(g); self.finish(g, (A, A))
        target = self.outputs(g)[0].id; self.play(g, P+'draw')
        self.assertEqual(g.state.entities[target].zone, Zone.HAND)
        g.apply(PlayCard(1, target))
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].max_health), (6, 7))
        self.assertEqual(self.armor(g), 9)
        self.play(g, P+'silence', target)
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].max_health), (1, 2))

    def test_empty_eligible_pool_has_no_fake_discovery_or_rng(self):
        g = self.game(members=(DRUID, OTHER, NONBEAST, SPELL, HIDDEN)); before = g._rng.getstate()
        prefix = tuple(g.state.players[1].deck); self.play(g)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g._rng.getstate(), before)
        self.assertEqual(tuple(g.state.players[1].deck), prefix)
        self.assertFalse(any(e.kind == 'card_discovered' for e in g.events))

    def test_missing_host_pool_and_unknown_eligible_definition_roll_back_entire_play(self):
        for config in (dict(pool=False), dict(members=MEMBERS+(UNKNOWN,))):
            with self.subTest(config=config):
                g = self.game(**config); before = g.snapshot()
                with self.assertRaises((ResolutionError, ValueError)): self.play(g)
                self.assertEqual(g.snapshot(), before)

    def test_plain_summon_does_not_run_the_battlecry_or_require_pool(self):
        g = self.game(hand=(P+'summon',), pool=False); self.play(g, P+'summon')
        self.assertIsNone(g.state.pending_choice)
        self.assertFalse(self.outputs(g))

    def test_finite_bottom_deck_grant_keeps_old_hand_prepare_and_stat_limits(self):
        request = DiscoverFromPool(1, POOL_ID, QUERY, source_id=1, discoveries=2,
            destination='deck', position='bottom', minion_grant=GRANT)
        for changes in (dict(position='random'), dict(discoveries=1), dict(discoveries=3),
                        dict(source_id=None), dict(delivery='after_all'),
                        dict(minion_grant=CreatedMinionGrant(special='prepare')),
                        dict(minion_grant=CreatedMinionGrant(keywords=(Keyword.TAUNT,)))):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(request, **changes)
        hand = replace(request, destination='hand', position='random', discoveries=1,
                       minion_grant=CreatedMinionGrant(special='prepare'))
        self.assertEqual(hand.destination, 'hand')

    def test_private_recipes_and_discovered_deck_faces_do_not_leak_to_opponent(self):
        g = self.game(); self.play(g); self.finish(g)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())
            for key in ('minion_grant', 'source_allocation', 'rng_state', 'RuleContext', 'resolution_frame'):
                self.assertNotIn(key, public)
        public = json.dumps(g.for_player(2).observe())
        for cid in (A, B, ALL): self.assertNotIn(cid, public)


if __name__ == '__main__':
    unittest.main()
