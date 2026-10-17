"""Actual Coin-family weapon quotes share original paid-hand acceptance proofs."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.native_coin_hand_cost_cards import CARD, BODY, load_batch
from hs_sim.engine import (Attack, CardDefinition, CardType, CoinHandCountCostSpec,
    CoinHandCountCostFact, CostSpec, EndTurn, Game, HandCountCostSpec, IllegalAction,
    PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import (capture_cost_input, capture_quote_fact, quote_cost,
    quote_generated_cost, capture_generated_quote_fact)
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Draw,
    GainTemporaryMana, InvokeBehavior, ModifyCost, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_count_costs import validate_definition, fact_from_dict
from hs_sim.engine.intrinsic_costs import validate_intrinsic_stage_fact
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, DiscardCard, MoveCard
from hs_sim.targets import canonical_digest

COIN, SPECIAL = 'GAME_005', 'JAIL_504t2'
P = 'k161.'
PLAIN, FAKE, WATCH, MINION, BASIC = (P + s for s in ('plain', 'fake_coin', 'watch', 'minion', 'basic_weapon'))
TO_PLAIN, TO_COIN, DISCARD, ACQUIRE, CYCLE, LAYERS = (P + s for s in ('to_plain', 'to_coin', 'discard', 'acquire', 'cycle', 'layers'))
FILL_ACQUIRE = P + 'fill_acquire'


@lru_cache(maxsize=8)
def registry(role, mode=None):
    assert role in ('writer', 'reader')
    r = build_registry()
    r.register_behavior(P + 'noop', lambda c: ())
    r.register_behavior(P + 'fake', lambda c: (GainTemporaryMana(c.player_id, 1),))
    r.register_card(CardDefinition(PLAIN, 'Ordinary non-Coin spell', CardType.SPELL, on_play=P + 'noop'))
    r.register_card(CardDefinition(FAKE, 'The Coin', CardType.SPELL, on_play=P + 'fake'))
    r.register_card(CardDefinition(MINION, 'Plain fixture minion', CardType.MINION, attack=1, health=4))
    r.register_card(CardDefinition(BASIC, 'Fixture weapon', CardType.WEAPON, attack=1, durability=2))
    def held(c, cid=COIN):
        return next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id == cid)
    def cycle(c):
        return (MoveCard(CardReference.capture(held(c)), 1, Zone.DECK, 'top', source_id=c.source_id),
            Draw(1, 1, c.source_id))
    bodies = {
        TO_PLAIN: lambda c: (TransformStoredCard(CardReference.capture(held(c)), PLAIN, c.source_id),),
        TO_COIN: lambda c: (TransformStoredCard(CardReference.capture(held(c, PLAIN)), SPECIAL, c.source_id),),
        DISCARD: lambda c: (DiscardCard(CardReference.capture(held(c))),),
        ACQUIRE: lambda c: (AddToHand(1, COIN, c.source_id),), CYCLE: cycle,
        FILL_ACQUIRE: lambda c: (AddToHand(1, PLAIN, c.source_id), AddToHand(1, COIN, c.source_id)),
        LAYERS: lambda c: (ModifyCost(held(c, CARD).id, CostSpec(set_to=5), c.source_id),
            AddCostModifier(1, CostSpec(delta=-2, card_ids=(CARD,)), uses_remaining=1)),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    if mode:
        def fail(c): raise ResolutionError('K161 deliberate failure')
        r.register_behavior(P + 'fail', fail)
        def eligible(c):
            return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id == CARD
        def watch(c):
            if not eligible(c): return ()
            if mode == 'failure': return (InvokeBehavior(P + 'fail', c.source_id, 1),)
            coin = next((c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id == COIN), None)
            options = [ChoiceOption('ok', 'Continue'),
                ChoiceOption('fail', 'Rollback', (InvokeBehavior(P + 'fail', c.source_id, 1),))]
            if coin is not None:
                ref = CardReference.capture(coin)
                options.extend((ChoiceOption('discard', 'Discard one original Coin', (DiscardCard(ref),)),
                    ChoiceOption('morph', 'Change one original Coin face', (TransformStoredCard(ref, PLAIN, c.source_id),)),
                    ChoiceOption('cycle', 'Leave and return original Coin', (
                        MoveCard(ref, 1, Zone.DECK, 'top', source_id=c.source_id), Draw(1, 1, c.source_id)))))
            return (RequestChoice(1, tuple(options), c.source_id),)
        r.register_behavior(P + 'watch', watch)
        r.register_card(CardDefinition(WATCH, 'Actual native checkpoint', CardType.MINION, health=10,
            triggers=(TriggerSpec('card_drawn' if mode == 'draw' else 'card_played', P + 'watch'),)))
    r.validate(); r.freeze()
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class NativeCoinHandCostTests(unittest.TestCase):
    def game(self, hand=(CARD, COIN, SPECIAL), enemy_hand=(), mode=None, mana=30,
            deck=(PLAIN,) * 12, hand_cap=None, weapon=None):
        self.mode = mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_03', hand=hand, board=(WATCH,) if mode else (), deck=deck,
                weapon_card_id=weapon, mana=mana, max_mana=30, mana_cap=30, hand_cap=hand_cap),
            PlayerSetup('HERO_03', hand=enemy_hand, deck=(PLAIN,) * 12)), seed=161), registry('writer', mode))

    def source(self, g, cid=CARD, pid=1):
        return next(g.state.entities[i] for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)

    def play(self, g, cid=CARD):
        eid = self.source(g, cid).id
        g.apply(PlayCard(1, eid))
        return eid

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def quote(self, g, cid=CARD):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, cid)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        reader = registry('reader', self.mode)
        self.assertIsNot(reader, g.registry)
        self.assertEqual(reader.fingerprint(), g.registry.fingerprint())
        other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for pid in (1, 2):
            public = json.dumps(g.for_player(pid).observe()) + json.dumps(g.for_player(pid).legal_actions()) + json.dumps(g.player_events(pid))
            for key in ('hand_cards', 'subject_id', 'next_entity_id', 'resolution_frame', 'coin_spell_ids', 'CoinHandCountCostFact'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_complete_source_six_faces_and_explicit_spell_family_classification(self):
        from tools.card_batch import check_face
        d = load_batch(); rows = {x['record']['id']: x for x in d['cards'] + d['existing_dependencies']}
        for o in d['official_observations']:
            check_face(rows[o['card_id']]['record'], o['face'], o['locale'],
                numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
        self.assertEqual(len(d['official_observations']), 6)
        self.assertEqual(len(d['coin_spell_ids']), 68)
        self.assertEqual([x['record']['id'] for x in d['coin_nonhand_evidence']], ['GAME_005e'])
        self.assertNotIn('GAME_005e', d['coin_spell_ids'])
        r = registry('writer'); card = r.card(CARD)
        self.assertEqual((card.cost, card.attack, card.durability, card.deathrattle), (3, 3, 2, BODY))
        for cid, pin in d['existing_definition_pins'].items():
            self.assertEqual(canonical_digest(asdict(r.card(cid))), pin)

    def test_pure_physical_and_generated_quotes_count_both_real_coins_but_not_names_or_mana_effects(self):
        g = self.game((CARD, COIN, SPECIAL, FAKE, PLAIN), enemy_hand=(COIN, SPECIAL))
        saved = g.snapshot(); fact = self.quote(g)
        self.assertEqual((fact.amount, fact.intrinsic.hand_cards.quantity), (1, 2))
        self.assertEqual(self.source(g).base_cost, 3); self.assertEqual(self.source(g).cost_modifier, 0)
        generated = capture_generated_quote_fact(g.state, g.registry, 1, CARD)
        self.assertEqual((generated.amount, generated.intrinsic.hand_cards.subject_id), (1, None))
        self.assertEqual(quote_generated_cost(g.state, g.registry, 1, CARD).amount, 1)
        self.assertEqual(g.snapshot(), saved)

    def test_real_weapon_payments_and_zero_floor_use_current_held_coin_quantity(self):
        for count, price in ((0, 3), (1, 2), (2, 1), (3, 0), (4, 0)):
            with self.subTest(count=count):
                coins = tuple(COIN if i % 2 == 0 else SPECIAL for i in range(count))
                g = self.game((CARD, *coins), mana=price)
                source = self.play(g); record = g.state.play_history[-1]
                self.assertEqual((record.cost, g.state.players[1].mana), (price, 0))
                self.assertEqual(g.state.players[1].weapon_id, source)
                self.assertEqual((g.state.entities[source].attack, g.state.entities[source].durability), (3, 2))
                self.assertEqual(record.submitted_cost.quote.intrinsic.hand_cards.quantity, count)
                self.portable(g)

    def test_actual_legal_player_price_and_insufficient_mana_roll_back(self):
        g = self.game(mana=1)
        port = g.for_player(1); dto = port.legal_actions()
        hand = g.observe(1)['players'][0]['hand']; row = next(x for x in hand if x['card_id'] == CARD)
        self.assertEqual(row['cost']['amount'], 1)
        action = next(a for a in dto['actions'] if a.get('card') == row['ref'])
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        self.portable(g)
        g = self.game(mana=0); saved = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g)
        self.assertEqual(g.snapshot(), saved)

    def test_current_hand_face_transform_changes_next_quote_without_new_identity(self):
        g = self.game((CARD, COIN, SPECIAL, PLAIN, TO_PLAIN, TO_COIN))
        original = self.source(g, COIN).id
        self.assertEqual(self.quote(g).amount, 1)
        self.play(g, TO_PLAIN)
        self.assertEqual(g.state.entities[original].card_id, PLAIN)
        self.assertEqual(self.quote(g).amount, 2)
        self.play(g, TO_COIN)
        self.assertEqual(self.quote(g).amount, 1)
        self.portable(g)

    def test_ordinary_local_and_external_layers_follow_filtered_intrinsic_stage(self):
        g = self.game((CARD, CARD, COIN, SPECIAL, LAYERS))
        self.play(g, LAYERS); fact = self.quote(g)
        self.assertEqual((fact.intrinsic.amount, fact.local_amount, fact.amount), (1, 5, 3))
        self.assertEqual(len(fact.consumable_ids), 1)
        self.assertEqual(g.state.players[1].cost_modifiers[0].uses_remaining, 1)
        self.play(g)
        self.assertEqual(g.state.play_history[-1].cost, 3)
        self.assertEqual(self.quote(g).amount, 1)
        self.portable(g)

    def test_discard_acquisition_and_full_hand_burn_requery_real_zones(self):
        g = self.game((CARD, COIN, SPECIAL, DISCARD, ACQUIRE))
        self.play(g, DISCARD); self.assertEqual(self.quote(g).amount, 2)
        self.play(g, ACQUIRE); self.assertEqual(self.quote(g).amount, 1); self.portable(g)
        g = self.game((CARD, FILL_ACQUIRE), hand_cap=2)
        self.play(g, FILL_ACQUIRE)
        self.assertEqual(self.quote(g).amount, 3)
        self.assertTrue(any(e.kind == 'card_burned' for e in g.events)); self.portable(g)

    def test_complete_paid_quote_keeps_original_hand_faces_after_later_discard(self):
        g = self.game((CARD, CARD, COIN, SPECIAL), mode='paid')
        source = self.play(g); receipt = g.state.play_history[-1].submitted_cost
        self.assertIn(source, receipt.quote.intrinsic.hand_cards.hands[0])
        saved = g.snapshot(); other = self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g, 'discard'); self.choose(other, 'discard')
        self.assertEqual(other.snapshot(), g.snapshot())
        self.assertEqual(g.state.play_history[0].submitted_cost, receipt)
        self.assertEqual(self.quote(g).amount, 2)
        self.portable(g)

    def test_frozen_price_survives_old_coin_face_change_and_same_id_hand_reentry(self):
        for option in ('morph', 'cycle'):
            with self.subTest(option=option):
                g = self.game((CARD, CARD, COIN, SPECIAL), mode='paid')
                self.play(g); original = g.state.play_history[-1].submitted_cost
                self.choose(g, option)
                self.assertEqual(g.state.play_history[0].submitted_cost, original)
                self.assertEqual(self.quote(g).amount, 2 if option == 'morph' else 1)
                self.portable(g)

    def test_rehashed_receipts_reject_same_count_alias_and_missing_subject_or_face_inventory(self):
        g = self.game(mode='paid'); self.play(g); saved = g.snapshot()
        for edit in ('same_count_alias', 'crop_subject', 'crop_faces', 'future_epoch', 'order', 'quantity', 'family'):
            bad = deepcopy(saved)
            hand = bad['state']['play_history'][0]['submitted_cost']['quote']['intrinsic']['hand_cards']
            if edit == 'same_count_alias': hand['faces'][0][1]['card_id'] = SPECIAL
            elif edit == 'crop_subject':
                hand['hands'][0] = hand['hands'][0][1:]; hand['faces'][0] = hand['faces'][0][1:]
            elif edit == 'crop_faces': hand['faces'][0] = hand['faces'][0][:-1]
            elif edit == 'future_epoch': hand['faces'][0][1]['zone_epoch'] = 100000
            elif edit == 'order':
                hand['hands'][0] = list(reversed(hand['hands'][0])); hand['faces'][0] = list(reversed(hand['faces'][0]))
            elif edit == 'quantity': hand['quantity'] += 1
            else: hand['spec']['card_ids'] = [COIN, SPECIAL]
            with self.subTest(edit=edit), self.assertRaises(SnapshotError):
                Game.from_snapshot(rehash(bad), registry('reader', 'paid'))

    def test_actual_second_weapon_attack_breaks_and_draws_once_from_original_deathrattle(self):
        g = self.game(); source = self.play(g)
        hero, enemy = g.state.players[1].hero_id, g.state.players[2].hero_id
        g.apply(Attack(1, hero, enemy)); self.assertEqual(g.state.entities[source].durability, 1)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); g.apply(Attack(1, hero, enemy))
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(sum(r.source_id == source for r in g.state.draw_history), 1)
        self.portable(g)

    def test_replacing_weapon_draw_wait_and_failed_resume_preserve_original_paid_quotes(self):
        g = self.game((CARD, CARD, COIN, SPECIAL), mode='draw')
        first = self.play(g); second = self.play(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].weapon_id, second)
        self.assertEqual(sum(r.source_id == first for r in g.state.draw_history), 1)
        saved = g.snapshot(); other = self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g); self.choose(other)
        self.assertEqual(other.snapshot(), g.snapshot()); self.portable(g)

    def test_late_failure_rolls_back_payment_weapon_replacement_and_original_price_material(self):
        g = self.game(mode='failure', weapon=BASIC); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g)
        self.assertEqual(g.snapshot(), saved)
        self.portable(g)

    def test_unknown_card_in_either_complete_hand_rejects_even_zero_price(self):
        g = self.game((CARD, COIN, COIN, SPECIAL), enemy_hand=(PLAIN,))
        self.assertEqual(self.quote(g).amount, 0)
        for pid in (1, 2):
            state = deepcopy(g.state)
            target = state.players[pid].hand[-1]
            state.entities[target].card_id = 'unknown.k161'
            with self.subTest(pid=pid), self.assertRaises(ValueError):
                capture_quote_fact(state, g.registry, capture_cost_input(self.source(g)))

    def test_player_price_does_not_expose_opponent_faces_or_private_family_facts(self):
        g = self.game(enemy_hand=(COIN, SPECIAL)); own = g.observe(1)
        twin = self.game(enemy_hand=(PLAIN, FAKE))
        self.assertEqual(own, twin.observe(1))
        self.assertTrue(all(row['card_id'] is None and row.get('cost') is None for row in own['players'][1]['hand']))
        self.assertEqual(own['players'][0]['hand'][0]['cost']['amount'], 1)
        self.portable(g)

    def test_strict_family_fact_codec_and_legacy_carrier_restrictions(self):
        g = self.game(); fact = self.quote(g); hand = fact.intrinsic.hand_cards
        self.assertIsInstance(hand, CoinHandCountCostFact)
        codec = FrameCodec(g.mechanics, g.registry)
        self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(fact)))), fact)
        self.assertEqual(fact_from_dict(json.loads(json.dumps(asdict(hand)))), hand)
        validate_intrinsic_stage_fact(g.registry, fact.intrinsic)
        for ids in ((), [COIN], (COIN, COIN), (SPECIAL, COIN), (True,)):
            with self.assertRaises(ValueError): CoinHandCountCostSpec(ids)
        with self.assertRaises(ValueError): replace(hand, quantity=True)
        with self.assertRaises(ValueError): replace(hand, faces=(hand.faces[0][:-1], hand.faces[1]))
        definition = g.registry.card(CARD)
        with self.assertRaises(ValueError): validate_definition(replace(definition, hand_count_cost=HandCountCostSpec()))
        with self.assertRaises(ValueError): validate_definition(replace(definition, kind=CardType.SPELL))
        self.portable(g)
