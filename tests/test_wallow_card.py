"""Wallow consumes genuine grants through the shared hand/deck listener."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.wallow_card import CARD, PROGRESS, load_batch, register_wallow_card
from hs_sim.cards.kindred_dark_gift_cards import RAPTOR, register_kindred_dark_gift_cards
from hs_sim.cards.stored_dark_gift_source import XAVIUS, register_stored_dark_gift_source
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    Attack, Keyword, PlayCard, PlayerSetup, Rarity, Registry, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.dark_gift_echo import CopyReceivedDarkGift
from hs_sim.engine.opponent_deck_gift_copy import DiscoverOpponentDeckCopy
from hs_sim.engine.dark_gifts import DARK_GIFTS, GrantDarkGift, public_gifts
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, Draw, GainArmor,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec, DamageKind, TargetSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, ModifyStoredCost, MoveCard
from hs_sim.targets import canonical_digest

P = 'wallow.test.'
BODIES = tuple(P + x for x in ('a', 'b', 'c'))
CTX = GenerationContext('wallow-real-native-test', 'experimental')
GIFTS = {g.id: g for g in DARK_GIFTS}
SWEET = 'EDR_100t8'
CLAWS = 'EDR_100t2'


def registry(mode=None):
    r = Registry('wallow-tests-v1.' + str(mode))
    register_wallow_card(r)
    register_kindred_dark_gift_cards(r)
    register_stored_dark_gift_source(r)
    r.register_card(CardDefinition(P + 'hero', 'Hero', CardType.HERO, health=100,
        metadata=CardMetadata(False, (CardClass.WARLOCK,), Rarity.NONE)))
    r.register_behavior(P + 'cry', lambda c: (GainArmor(c.player_id, 1),))
    for cid in BODIES:
        card = CardDefinition(cid, cid, CardType.MINION, cost=8, attack=8, health=8,
            battlecry=P + 'cry', metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=('beast',)))
        r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    r.register_pool(PoolDefinition('constructed.cards', 'wallow-explicit-three-v1', CTX.target_id, CTX.mode,
        tuple(PoolMember(cid) for cid in BODIES), complete=True))
    def held(c):
        return next(c.state.entities[i] for i in (*c.state.players[c.player_id].hand,
            *c.state.players[c.player_id].deck) if c.state.entities[i].card_id == CARD)
    def given(c, gift, to_deck=False, enemy=False, discount=0):
        player = 3-c.player_id if enemy else c.player_id
        recipe = replace(gift.grant, identity=gift.id)
        cost = CostSpec(delta=gift.cost_delta+discount) if gift.cost_delta+discount else None
        if to_deck or gift.destination == 'deck_top':
            return (AddToDeck(player, BODIES[0], 'top', c.source_id, cost=cost, minion_grant=recipe),)
        return (AddToHand(player, BODIES[0], c.source_id, cost=cost, minion_grant=recipe),)
    for gift in DARK_GIFTS:
        for category in ('new', 'deck', 'enemy', 'own', 'stored'):
            cid = P + category + '.' + gift.id
            def body(c, gift=gift, category=category):
                if category == 'own':
                    return (GrantDarkGift(CardReference.capture(held(c)), gift.id, c.source_id),)
                if category == 'stored':
                    target = c.state.entities[c.state.players[c.player_id].deck[-1]]
                    return (GrantDarkGift(CardReference.capture(target), gift.id, c.source_id),)
                return given(c, gift, category == 'deck', category == 'enemy')
            r.register_behavior(cid, body); r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    def fail(c): raise ResolutionError('Wallow deliberate echo failure')
    def change(c):
        ref = CardReference.capture(held(c))
        return (BuffStoredCard(ref, 20, 30, c.source_id), ModifyStoredCost(ref, CostSpec(delta=-1), c.source_id))
    def mixed(c):
        gift = GIFTS[CLAWS]
        return (AddToHand(c.player_id, CARD, c.source_id, cost=CostSpec(delta=-4),
            minion_grant=replace(gift.grant, identity=gift.id)),)
    bodies = {
        'draw': lambda c: (Draw(c.player_id, source_id=c.source_id),),
        'copy': lambda c: (CopyCard(CardReference.capture(held(c)), c.player_id, source_id=c.source_id),),
        'base': lambda c: (CopyCard(CardReference.capture(held(c)), c.player_id, mode='base', source_id=c.source_id),),
        'external': lambda c: (MoveCard(CardReference.capture(held(c)), c.player_id, Zone.DECK,
            position='top', reset=True, source_id=c.source_id),),
        'mixed': mixed, 'change': change, 'fail': fail,
        'fresh': lambda c: (AddToHand(c.player_id, CARD, c.source_id),),
        'opponent': lambda c: (DiscoverOpponentDeckCopy(c.player_id, c.source_id, True),),
        'silence': lambda c: (Silence(c.target_id),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'kill': lambda c: (Destroy(c.target_id),),
        'hit': lambda c: (Damage(c.target_id, 1, c.source_id, DamageKind.SPELL),),
    }
    for name, body in bodies.items():
        cid = P + name; r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, name, CardType.SPELL, on_play=cid,
            targeting=TargetSpec() if name in ('silence', 'bounce', 'kill', 'hit') else None))
    if mode:
        event = ('hand_progressed' if mode == 'progress_wait' else
            'dark_gift_copied' if mode in ('echo_wait', 'fail') else 'dark_gift_granted')
        def watch(c):
            if mode == 'fail': return (InvokeBehavior(P + 'fail', c.source_id, c.player_id),)
            if mode == 'depart':
                return (MoveCard(CardReference.capture(held(c)), c.player_id, Zone.HAND,
                    draw=True, source_id=c.source_id),) if held(c).zone == Zone.DECK else (
                    MoveCard(CardReference.capture(held(c)), c.player_id, Zone.DECK, source_id=c.source_id),)
            if mode == 'recipient_depart':
                target = c.state.entities[c.event.target_id]
                return (MoveCard(CardReference.capture(target), 3-target.controller, Zone.HAND, source_id=c.source_id),)
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
        r.register_behavior(P + 'watch', watch)
        r.register_card(CardDefinition(P + 'watch', 'Observer', CardType.MINION, health=50,
            triggers=(TriggerSpec(event, P + 'watch'),)))
    r.validate(); return r


class WallowTests(unittest.TestCase):
    def game(self, hand=(CARD,), deck=(), board=(), other_hand=(), other_deck=(), seat=1, mode=None, seed=277):
        own = PlayerSetup(P+'hero', hand=hand, deck=deck, board=(*board, *((P+'watch',) if mode else ())),
            mana=50, max_mana=50, mana_cap=50)
        other = PlayerSetup(P+'hero', hand=other_hand, deck=other_deck, mana=50, max_mana=50, mana_cap=50)
        return Game.from_scenario(Scenario((own, other) if seat == 1 else (other, own),
            active_player=seat, seed=seed, generation_context=CTX), registry(mode))

    def play(self, g, cid, target=None, seat=None):
        seat = g.state.active_player if seat is None else seat
        eid = next(i for i in g.state.players[seat].hand if g.state.entities[i].card_id == cid)
        pos = len(g.state.players[seat].board) if g.registry.card(cid).kind == CardType.MINION else None
        g.apply(PlayCard(seat, eid, target_id=target, position=pos)); return eid

    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def wallows(self, g, seat=1):
        return [e for e in g.state.entities.values() if e.card_id == CARD and e.controller == seat]

    def ids(self, entity): return [g['id'] for g in public_gifts(entity)]

    def portable(self, g, mode=None):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(mode))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(mode)).snapshot(), saved)
        return other

    def add(self, g, gift, category='new'):
        cid = P+category+'.'+gift
        self.play(g, cid)

    def test_a01_complete_source_real_face_and_all_ten_recipes(self):
        data = load_batch(); self.assertEqual(len(data['existing_dependencies']), 10)
        self.assertEqual(len(data['official_observations']), 2)
        for row in (*data['cards'], *data['existing_dependencies']):
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        r = build_registry(); card = r.card(CARD)
        self.assertEqual((card.cost, card.attack, card.health, card.metadata.classes), (7, 6, 6, (CardClass.WARLOCK,)))
        self.assertEqual(card.hand_progress, PROGRESS); self.assertIsNone(card.battlecry)

    def test_a02_each_real_gift_reaches_stored_wallow_without_selection_eligibility_filter(self):
        for gift in DARK_GIFTS:
            with self.subTest(gift=gift.id):
                g = self.game(hand=(CARD, P+'new.'+gift.id)); wid = self.wallows(g)[0].id
                self.add(g, gift.id); w = g.state.entities[wid]
                self.assertEqual(self.ids(w), [gift.id])
                self.assertEqual((w.attack, w.max_health), (6+gift.grant.attack, 6+gift.grant.health))
                self.assertTrue(set(gift.grant.keywords) <= w.keywords)
                self.assertEqual(len([e for e in g.events if e.kind == 'dark_gift_granted']), 1)
                self.assertEqual(len([e for e in g.events if e.kind == 'dark_gift_copied']), 1)

    def test_a03_deck_and_hand_receivers_both_copy_original_grant_once(self):
        gift = 'EDR_100t'; g = self.game(hand=(CARD, P+'new.'+gift), deck=(CARD, BODIES[0]))
        self.add(g, gift)
        self.assertEqual([self.ids(w) for w in self.wallows(g)], [[gift], [gift]])
        self.assertEqual(len([e for e in g.events if e.kind == 'dark_gift_copied']), 2)

    def test_a04_new_deck_recipient_also_notifies(self):
        gift = 'EDR_100t3'; g = self.game(hand=(CARD, P+'deck.'+gift))
        self.add(g, gift, 'deck'); self.assertEqual(self.ids(self.wallows(g)[0]), [gift])

    def test_a05_actual_stored_grant_and_departing_recipient_still_copy_frozen_gift(self):
        gift = 'EDR_100t3'; g = self.game(hand=(CARD, P+'stored.'+gift), deck=(BODIES[0],), mode='recipient_depart')
        self.add(g, gift, 'stored')
        self.assertEqual(self.ids(self.wallows(g)[0]), [gift])
        self.assertFalse(g.state.players[1].deck)

    def test_a06_opponent_gifts_do_not_advance_friendly_wallow(self):
        gift = 'EDR_100t'; g = self.game(hand=(CARD, P+'enemy.'+gift), other_deck=(CARD,))
        self.add(g, gift, 'enemy')
        self.assertEqual(self.ids(self.wallows(g)[0]), [])
        self.assertEqual(self.ids(self.wallows(g, 2)[0]), [gift])

    def test_a07_original_self_grant_is_copied_once_without_echo_loop(self):
        gift = 'EDR_100t'; g = self.game(hand=(CARD, P+'own.'+gift), deck=(CARD,))
        self.add(g, gift, 'own')
        self.assertEqual(self.ids(next(w for w in self.wallows(g) if w.zone == Zone.HAND)), [gift, gift])
        self.assertEqual(self.ids(next(w for w in self.wallows(g) if w.zone == Zone.DECK)), [gift])
        self.assertEqual(len([e for e in g.events if e.kind == 'dark_gift_granted']), 1)

    def test_a08_repeated_gift_stats_and_cost_stack_even_if_keyword_is_already_present(self):
        gift = 'EDR_100t'; g = self.game(hand=(CARD, P+'new.'+gift, P+'new.'+gift))
        self.add(g, gift); self.add(g, gift)
        self.assertEqual((self.wallows(g)[0].attack, self.ids(self.wallows(g)[0])), (12, [gift, gift]))

    def test_a09_wallow_on_board_does_not_listen(self):
        gift = 'EDR_100t'; g = self.game(hand=(CARD, P+'new.'+gift))
        wid = self.play(g, CARD); self.add(g, gift)
        self.assertEqual(self.ids(g.state.entities[wid]), [])
        self.assertEqual(g.state.players[1].mana, 43)

    def test_a10_late_created_wallow_does_not_catch_past_grants(self):
        gift = 'EDR_100t'; g = self.game(hand=(P+'new.'+gift, P+'fresh'))
        self.add(g, gift); self.assertEqual(self.wallows(g), [])
        self.play(g, P+'fresh'); self.assertEqual(self.ids(self.wallows(g)[0]), [])

    def test_a11_current_copy_keeps_gifts_and_native_listener_base_copy_starts_clean(self):
        gift = 'EDR_100t'; g = self.game(hand=(CARD, P+'new.'+gift, P+'copy', P+'base', P+'new.'+gift))
        self.add(g, gift); self.play(g, P+'copy'); self.play(g, P+'base')
        self.assertEqual([len(self.ids(w)) for w in self.wallows(g)], [1, 1, 0])
        self.add(g, gift)
        self.assertEqual([len(self.ids(w)) for w in self.wallows(g)], [2, 2, 1])

    def test_a12_sweet_dreams_keeps_only_real_gifts_and_moves_same_original_to_deck_top(self):
        gift = 'EDR_100t'; g = self.game(hand=(CARD, P+'new.'+gift, P+'change', P+'new.'+SWEET), deck=(BODIES[1],))
        wid = self.wallows(g)[0].id
        self.add(g, gift); self.play(g, P+'change'); self.add(g, SWEET)
        w = g.state.entities[wid]
        self.assertEqual(g.state.players[1].deck[:2], [wid, next(e.target_id for e in reversed(g.events) if e.kind=='card_created')])
        self.assertEqual((w.attack, w.max_health, w.zone), (13, 11, Zone.DECK))
        self.assertEqual(self.ids(w), [gift, SWEET]); self.assertIn(Keyword.LIFESTEAL, w.keywords)
        self.assertFalse(any(e.attack == 20 or e.health == 30 for e in w.enchantments))
        self.portable(g)

    def test_a13_sweet_dreams_preserves_gift_discount_and_drops_source_part_of_mixed_cost(self):
        g = self.game(hand=(P+'mixed', P+'new.'+SWEET))
        self.play(g, P+'mixed'); wid = self.wallows(g)[0].id
        self.assertEqual(self.ids(g.state.entities[wid]), [CLAWS, CLAWS])
        self.add(g, SWEET); w = g.state.entities[wid]
        self.assertEqual(w.cost, 3)  # two actual -2 gifts, not source's extra -2.
        self.assertEqual(self.ids(w), [CLAWS, CLAWS, SWEET])
        self.assertEqual((w.attack, w.max_health), (6, 11))

    def test_a14_sweet_dreams_on_already_deck_receiver_does_not_reorder_unrelated_cards(self):
        g = self.game(hand=(P+'new.'+SWEET,), deck=(BODIES[1], CARD, BODIES[2]))
        wid = self.wallows(g)[0].id
        self.add(g, SWEET)
        self.assertEqual(g.state.players[1].deck[2], wid)
        self.assertEqual((g.state.entities[wid].attack, g.state.entities[wid].max_health), (10, 11))

    def test_a15_external_backward_move_has_no_wallow_retention_exception(self):
        gift = 'EDR_100t'; g = self.game(hand=(CARD, P+'new.'+gift, P+'external'))
        self.add(g, gift); wid = self.wallows(g)[0].id; self.play(g, P+'external')
        self.assertEqual(self.ids(g.state.entities[wid]), [])
        self.assertEqual(g.state.entities[wid].attack, 6)

    def test_a16_grant_wait_restore_independent_registry_clone_replay_and_continuation(self):
        gift = 'EDR_100t'; g = self.game(hand=(CARD, P+'new.'+gift), mode='wait')
        self.add(g, gift); self.assertEqual(self.ids(self.wallows(g)[0]), [])
        other = self.portable(g, 'wait')
        for game in (g, other): self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(self.ids(self.wallows(g)[0]), [gift])

    def test_a17_copy_wait_bad_resume_rolls_back_only_resume_then_completes(self):
        gift = 'EDR_100t'; g = self.game(hand=(CARD, P+'new.'+gift), mode='echo_wait')
        self.add(g, gift); saved = g.snapshot(); self.assertEqual(self.ids(self.wallows(g)[0]), [gift])
        self.portable(g, 'echo_wait')
        with self.assertRaisesRegex(ResolutionError, 'Wallow deliberate'): self.choose(g, 'bad')
        self.assertEqual(saved, g.snapshot()); self.choose(g)

    def test_a18_source_departure_before_listener_resolution_invalidates_its_original_residence(self):
        gift = 'EDR_100t'; g = self.game(hand=(CARD, P+'new.'+gift), mode='depart')
        self.add(g, gift); self.assertEqual(self.ids(self.wallows(g)[0]), [])

    def test_a19_echo_failure_rolls_back_creation_attachments_rng_and_original_payment(self):
        gift = 'EDR_100t'; g = self.game(hand=(CARD, P+'new.'+gift), mode='fail'); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Wallow deliberate'): self.add(g, gift)
        self.assertEqual(g.snapshot(), saved)

    def test_a20_player_observations_and_events_do_not_leak_opponent_wallow_or_provenance(self):
        gift = 'EDR_100t'; g = self.game(hand=(CARD, P+'new.'+gift), other_hand=(CARD,))
        self.add(g, gift)
        own = json.dumps(g.for_player(1).observe(), ensure_ascii=False)
        other = json.dumps(g.for_player(2).observe(), ensure_ascii=False)+json.dumps(g.player_events(2), ensure_ascii=False)
        self.assertIn('dark_gifts', own); self.assertNotIn('dark_gifts', other)
        self.assertNotIn(chr(34)+'id'+chr(34)+': '+chr(34)+gift+chr(34), other)
        for value in (own, other):
            for field in ('dark_gift_id', 'grant_event', 'progress_keys', 'rng_state', 'resolution_frame'):
                self.assertNotIn('"'+field+'"', value)

    def test_a21_second_seat_and_hidden_deck_gain_are_supported(self):
        gift = 'EDR_100t'; g = self.game(hand=(P+'new.'+gift,), deck=(CARD,), seat=2)
        self.add(g, gift); self.assertEqual(self.ids(self.wallows(g, 2)[0]), [gift])
        self.portable(g)

    def test_a22_tampered_gift_provenance_rejects_rehashed_snapshot(self):
        gift = 'EDR_100t'; g = self.game(hand=(CARD, P+'new.'+gift)); self.add(g, gift)
        saved = deepcopy(g.snapshot()); wid = self.wallows(g)[0].id
        ability = next(a for a in saved['state']['entities'][str(wid)]['abilities'] if a.get('dark_gift_id') == gift)
        ability['dark_gift_id'] = 'EDR_100t3'
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry())

    def test_a23_real_xavius_selection_gives_original_deck_minion_and_wallow_same_actual_gift(self):
        g = self.game(hand=(CARD, XAVIUS), deck=BODIES)
        self.play(g, XAVIUS); other = self.portable(g)
        for game in (g, other):
            option = game._frame.options[0]; gift = option.effects[0].offered[0].gift_id
            self.choose(game, option.id)
            self.assertEqual(self.ids(self.wallows(game)[0]), [gift])
        self.assertEqual(g.snapshot(), other.snapshot())

    def test_a24_real_raptor_rewind_undoes_original_wallow_gift_and_discount(self):
        g = self.game(hand=(CARD, BODIES[0], RAPTOR), deck=(BODIES[0],), seed=5)
        self.play(g, BODIES[0]); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        wid = self.wallows(g)[0].id; self.play(g, RAPTOR)
        option = next(o for o in g._frame.options if o.effects[0].selection.gift.id == CLAWS)
        original_gift = option.effects[0].selection.gift.id
        self.choose(g, option.id)
        self.assertEqual(self.ids(g.state.entities[wid]), [original_gift])
        self.assertEqual(g.state.entities[wid].cost, 5)
        self.assertEqual(option.effects[0].batch.spec.cost.delta, -1)
        other = self.portable(g)
        for game in (g, other):
            self.choose(game, 'retry')
            self.assertEqual(self.ids(game.state.entities[wid]), [])
            self.assertEqual(game.state.entities[wid].cost, 7)
            self.assertIsNotNone(game.state.pending_choice)
            self.choose(game, game._frame.options[0].id)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(g.state.players[1].mana, 47)
        self.portable(g)

    def test_a25_real_paid_wallow_uses_copied_charge_windfury_and_living_nightmare_bodies(self):
        gifts = ('EDR_100t', 'EDR_100t6', 'EDR_100t13', 'EDR_100t5')
        g = self.game(hand=(CARD, *(P+'new.'+gid for gid in gifts)))
        for gid in gifts: self.add(g, gid)
        wid = self.play(g, CARD)
        copies = [g.state.entities[i] for i in g.state.players[1].board if i != wid]
        self.assertEqual(len(copies), 1); self.assertEqual((copies[0].attack, copies[0].max_health), (2, 2))
        self.assertEqual(self.ids(copies[0]), list(gifts))
        enemy = g.state.players[2].hero_id
        g.apply(Attack(1, wid, enemy)); g.apply(Attack(1, wid, enemy))
        self.assertEqual(g.state.entities[enemy].health, 82)
        self.assertEqual(len([e for e in g.events if e.kind == 'dark_gift_granted']), 4)
        self.portable(g)

    def test_a26_stored_horrific_claws_uses_numeric_cost_and_not_a_second_creation(self):
        g = self.game(hand=(CARD, P+'stored.'+CLAWS), deck=(BODIES[0],))
        target = g.state.players[1].deck[0]
        self.add(g, CLAWS, 'stored')
        self.assertEqual(g.state.entities[target].cost, 6)
        self.assertEqual(self.wallows(g)[0].cost, 5)
        self.assertFalse(any(e.kind == 'card_created' for e in g.events))

    def test_a27_opponent_deck_copy_with_fresh_gift_notifies_only_its_new_recipient(self):
        g = self.game(hand=(CARD, P+'opponent'), other_deck=BODIES)
        originals = tuple(g.state.players[2].deck)
        self.play(g, P+'opponent'); option = g._frame.options[0]
        gift = option.effects[0].offered[0].gift_id
        self.choose(g, option.id)
        self.assertEqual(tuple(g.state.players[2].deck), originals)
        self.assertTrue(all(not public_gifts(g.state.entities[i]) for i in originals))
        self.assertEqual(self.ids(self.wallows(g)[0]), [gift])
        self.portable(g)

    def test_a28_original_progress_wait_and_typed_copy_codec_reject_wrong_receiver(self):
        from hs_sim.engine.continuations import FrameCodec
        gift = 'EDR_100t'; g = self.game(hand=(CARD, P+'new.'+gift), mode='progress_wait')
        self.add(g, gift); self.assertEqual(self.ids(self.wallows(g)[0]), [])
        event = next(e for e in g.events if e.kind == 'dark_gift_granted')
        work = CopyReceivedDarkGift(CardReference.capture(self.wallows(g)[0]), event)
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state, origin_events=g.events)
        encoded = codec.encode(work)
        self.assertEqual(codec.decode(encoded), work)
        bad = deepcopy(encoded)
        bad['fields']['card']['fields']['card_id'] = BODIES[0]
        with self.assertRaises(ValueError): codec.decode(bad)
        with self.assertRaises(ValueError): CopyReceivedDarkGift(work.card, replace(event, kind='dark_gift_copied'))
        other = self.portable(g, 'progress_wait')
        for game in (g, other): self.choose(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.ids(self.wallows(g)[0]), [gift])


if __name__ == '__main__': unittest.main()
