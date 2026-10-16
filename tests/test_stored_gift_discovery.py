"""Physical Dark Gift discovery, original material and real Xavius choices."""
from copy import deepcopy
from dataclasses import asdict, replace
from itertools import permutations
import json
from random import Random
from types import SimpleNamespace
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.stored_dark_gift_source import XAVIUS, load_batch
from hs_sim.engine import (CardDefinition, CardType, CostSpec, Game, Keyword, PlayCard, PlayerSetup,
    Ruleset, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.dark_gifts import DARK_GIFTS, GrantDarkGift, public_gifts
from hs_sim.engine.effects import AddToHand, ChangeControl, Destroy, Draw, GainArmor, InvokeBehavior
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.hand_capacity import SetHandCapacity
from hs_sim.engine.model import BattlecryRepeatSpec, CardPreview
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.stored_gift_discovery import (DiscoverDeckDarkGift, StoredGiftOffer,
    SelectGiftedDeckCard, eligible_face, gift_by_id, preview)
from hs_sim.engine.zones import CardReference, ModifyStoredCost, MoveCard
from hs_sim.targets import canonical_digest

YETI = 'CORE_CS2_182'; SEEDLING = 'TLC_234t'; FIREBALL = 'CORE_CS2_029'; SWEET = 'EDR_100t8'


def registry():
    r = build_registry()
    def first(c): return CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]])
    def stale(c):
        ref = first(c); face = CardPreview.capture(c.state.entities[ref.entity_id])
        offer = StoredGiftOffer(ref, face, False, 'EDR_100t3')
        return (MoveCard(ref, c.player_id, Zone.HAND), SelectGiftedDeckCard(DiscoverDeckDarkGift(c.player_id, c.source_id), (offer,), 0))
    scripts = dict(discover=lambda c: (DiscoverDeckDarkGift(c.player_id, c.source_id),),
        bad=lambda c: (DiscoverDeckDarkGift(c.player_id, c.source_id), InvokeBehavior('k84.fail', c.source_id, c.player_id)),
        unknown=lambda c: (DiscoverDeckDarkGift(c.player_id, 999999),),
        boost=lambda c: (BuffStoredCard(first(c), 2, 3, c.source_id), ModifyStoredCost(first(c), CostSpec(delta=-1), c.source_id)),
        keywords=lambda c: (GrantDarkGift(first(c), 'EDR_100t13', c.source_id),),
        rude=lambda c: (GrantDarkGift(CardReference.capture(next(c.state.entities[i] for i in c.state.players[c.player_id].hand
                                                                 if c.state.entities[i].card_id == XAVIUS)), 'EDR_100t7', c.source_id),),
        stale=stale, draw=lambda c: (Draw(c.player_id, source_id=c.source_id),))
    for key, body in scripts.items():
        r.register_behavior('k84.' + key, body)
        r.register_card(CardDefinition('k84.' + key, key, CardType.SPELL, on_play='k84.' + key))
    r.register_behavior('k84.fail', lambda c: (AddToHand(c.player_id, 'unknown.k84'),))
    def watch(c):
        target = c.state.entities.get(c.event.target_id)
        if target is None or target.card_id != YETI: return ()
        return (GainArmor(c.player_id, 1 if public_gifts(target) else 100),)
    def depart(c):
        target = c.state.entities.get(c.event.target_id)
        if target is None or target.zone != Zone.DECK: return ()
        return (MoveCard(CardReference.capture(target), c.player_id, Zone.HAND),)
    def kill(c): return (Destroy(c.event.source_id),)
    def steal(c): return (ChangeControl(c.event.source_id, 3-c.player_id),)
    def cap(c): return (SetHandCapacity(c.player_id, 1),)
    for key, event, body in (('watch', 'card_moved', watch), ('depart', 'dark_gift_granted', depart),
                             ('kill', 'choice_selected', kill), ('steal', 'choice_selected', steal),
                             ('cap', 'choice_selected', cap)):
        r.register_behavior('k84.' + key + '_body', body)
        r.register_card(CardDefinition('k84.' + key, key, CardType.MINION, health=8,
                                      triggers=(TriggerSpec(event, 'k84.' + key + '_body'),)))
    r.register_card(CardDefinition('k84.brann', 'repeat', CardType.MINION, health=8,
                                  battlecry_repeats=(BattlecryRepeatSpec(),)))
    return r


def seed_for(gift_id, *, battlecry=False, attack=4):
    face = SimpleNamespace(kind=CardType.MINION, attack=attack, keywords=(), battlecry='yes' if battlecry else None)
    possible = tuple(gs for gs in permutations(sorted(DARK_GIFTS, key=lambda g: g.id), 1) if gs[0].eligible(face))
    for seed in range(1, 1000):
        rng = Random(seed); rng.sample((0,), 1)
        if rng.choice(possible)[0].id == gift_id: return seed
    raise AssertionError('Expected a reachable fixed gift seed')


class StoredGiftDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.r = registry()
    def game(self, hand=(XAVIUS,), deck=(YETI,), *, board=(), cap=None, seed=184, rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, deck=deck, board=board, mana=40, max_mana=40,
                        mana_cap=40, hand_cap=cap, hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', hand=(FIREBALL,), deck=(YETI,)*4, hero_power_card_id='HERO_08bp'),
        ), seed=seed), self.r, ruleset=rules)
    def play(self, g, cid):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid, None, len(g.state.players[1].board) if self.r.card(cid).kind == CardType.MINION else None)); return eid
    def select(self, g, index=0):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (q.options[index].id,)))
    def branches(self, g): return [o.effects[0] for o in g._frame.options]
    def offers(self, g): return self.branches(g)[0].offered
    def portable(self, g):
        s = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(s, registry())
        self.assertEqual(other.snapshot(), s); self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), s)
        return other
    def rehash(self, s):
        s['events_hash'] = canonical_hash(s['events'])
        s['state_hash'] = canonical_hash({k:v for k,v in s.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        return s
    def selection_nodes(self, s):
        found = []
        def visit(x):
            if isinstance(x, dict):
                if str(x.get('type', '')).endswith('.SelectGiftedDeckCard'): found.append(x)
                for v in x.values(): visit(v)
            elif isinstance(x, list):
                for v in x: visit(v)
        visit(s); self.assertTrue(found); return found

    def test_complete_source_and_existing_ten_recipe_identity(self):
        data = load_batch(); self.assertEqual(len(data['cards']), 1); self.assertFalse(data['dependencies'])
        self.assertEqual({x['record']['id'] for x in data['existing_gift_sources']}, {g.id for g in DARK_GIFTS})
        self.assertEqual(canonical_digest([asdict(g) for g in DARK_GIFTS]), data['gift_recipes_sha256'])
        for row in data['cards'] + data['existing_gift_sources'] + data['evidence_only']:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        raw = data['cards'][0]['record']; card = self.r.card(XAVIUS)
        self.assertEqual((card.cost, card.attack, card.health), (4,4,4))
        self.assertEqual(card.metadata, replace(metadata_from_record(raw), deck_identity=XAVIUS))

    def test_paid_battlecry_offers_original_minions_and_pays_once(self):
        g = self.game(deck=(YETI, SEEDLING, XAVIUS, FIREBALL)); old = tuple(g.state.players[1].deck)
        source = self.play(g, XAVIUS); self.assertEqual(g.state.players[1].mana, 36)
        offers = self.offers(g); self.assertEqual(len(offers), 3)
        self.assertEqual({o.card.entity_id for o in offers}, {i for i in old if g.state.entities[i].kind == CardType.MINION})
        self.assertEqual(len({o.gift_id for o in offers}), 3)
        self.assertEqual(g.state.players[1].deck, list(old)); self.assertIn(source, g.state.players[1].board)
        self.portable(g)

    def test_empty_or_nonminion_deck_has_no_choice_or_rng(self):
        for deck in ((), (FIREBALL,)):
            g = self.game(deck=deck); rng = g.snapshot()['rng_state']; self.play(g, XAVIUS)
            self.assertIsNone(g.state.pending_choice); self.assertEqual(g.snapshot()['rng_state'], rng)

    def test_physical_duplicate_faces_remain_separate_take_candidates(self):
        g = self.game(deck=(YETI, YETI)); self.play(g, XAVIUS)
        offers = self.offers(g); self.assertEqual(len(offers), 2)
        self.assertEqual([o.card.card_id for o in offers], [YETI, YETI])
        self.assertEqual(len({o.card.entity_id for o in offers}), 2)

    def test_existing_stored_stats_cost_and_material_survive_real_delivery(self):
        g = self.game(('k84.boost', XAVIUS), seed=seed_for('EDR_100t3', attack=6))
        eid = g.state.players[1].deck[0]; self.play(g, 'k84.boost'); self.play(g, XAVIUS)
        offer, = self.offers(g); self.assertEqual((offer.face.cost, offer.face.attack, offer.face.health), (3,6,8))
        self.assertEqual(offer.gift_id, 'EDR_100t3'); shown = preview(offer)
        self.select(g); e = g.state.entities[eid]
        self.assertEqual((e.id, e.zone, e.cost, e.attack, e.health), (eid, Zone.HAND, shown.cost, shown.attack, shown.health))
        self.assertIn(Keyword.TAUNT, e.keywords); self.portable(g)

    def test_current_zero_attack_and_current_keywords_control_gift_eligibility(self):
        g = self.game(('k84.keywords', XAVIUS), deck=(YETI, SEEDLING))
        self.play(g, 'k84.keywords'); self.play(g, XAVIUS)
        for offer in self.offers(g):
            self.assertTrue(gift_by_id(offer.gift_id).eligible(eligible_face(offer.face, offer.battlecry)))
            if offer.card.card_id == YETI: self.assertNotEqual(offer.gift_id, 'EDR_100t13')
            else: self.assertNotIn(offer.gift_id, ('EDR_100t2','EDR_100t6','EDR_100t7'))

    def test_selected_original_moves_without_draw_or_new_entity(self):
        g = self.game(seed=seed_for('EDR_100t3')); old = g.state.players[1].deck[0]
        self.play(g, XAVIUS); count = len(g.state.entities); self.select(g)
        self.assertEqual(g.state.players[1].hand, [old]); self.assertEqual(len(g.state.entities), count)
        self.assertFalse(g.state.draw_history); self.assertTrue(public_gifts(g.state.entities[old]))

    def test_sweet_dreams_reorders_original_and_later_draw_keeps_gift(self):
        g = self.game((XAVIUS,'k84.draw'), deck=(YETI,FIREBALL), seed=seed_for(SWEET)); old = g.state.players[1].deck[0]
        self.play(g, XAVIUS); self.assertEqual(self.offers(g)[0].gift_id, SWEET); count = len(g.state.entities)
        self.select(g); self.assertEqual(g.state.players[1].deck[0], old)
        self.assertEqual(g.state.entities[old].zone, Zone.DECK); self.assertEqual(len(g.state.entities), count)
        self.play(g, 'k84.draw'); self.assertIn(old, g.state.players[1].hand)
        self.assertEqual((g.state.entities[old].attack,g.state.entities[old].health),(8,10)); self.portable(g)

    def test_full_hand_burns_original_after_grant_without_copy_or_draw(self):
        g = self.game((XAVIUS,YETI), cap=2, board=('k84.cap',), seed=seed_for('EDR_100t3'))
        old = g.state.players[1].deck[0]; self.play(g, XAVIUS); count = len(g.state.entities); self.select(g)
        self.assertEqual(g.state.entities[old].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.entities), count); self.assertFalse(g.state.players[1].deck)
        self.assertFalse(g.state.draw_history)

    def test_unselected_original_cards_and_order_are_untouched(self):
        g = self.game(deck=(YETI, SEEDLING, XAVIUS, FIREBALL)); old = list(g.state.players[1].deck)
        self.play(g, XAVIUS); index = next(i for i,o in enumerate(self.offers(g)) if o.gift_id != SWEET)
        selected = self.offers(g)[index].card.entity_id; self.select(g, index)
        self.assertEqual(g.state.players[1].deck, [i for i in old if i != selected])
        self.assertTrue(all(not public_gifts(g.state.entities[i]) for i in old if i != selected))

    def test_wait_restore_clone_replay_keep_original_pairing_and_rng(self):
        g = self.game(deck=(YETI, SEEDLING, XAVIUS)); self.play(g, XAVIUS)
        other = self.portable(g); rng = g.snapshot()['rng_state']; self.select(g); self.select(other)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertEqual(g.state.players[1].mana, 36); self.portable(g)

    def test_invalid_choice_keeps_original_offers_and_rng(self):
        g = self.game(); self.play(g, XAVIUS); saved = g.snapshot(); q = g.state.pending_choice
        with self.assertRaises(IllegalAction): g.apply(SelectChoice(1, q.id, ('not-an-offer',)))
        self.assertEqual(g.snapshot(), saved)

    def test_later_error_rolls_back_only_selection_grant_and_delivery(self):
        g = self.game(('k84.bad',), seed=seed_for('EDR_100t3')); self.play(g, 'k84.bad'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.select(g)
        self.assertEqual(g.snapshot(), saved); self.portable(g)

    def test_source_death_after_choice_acceptance_does_not_cancel_original_delivery(self):
        g = self.game(board=('k84.kill',), seed=seed_for('EDR_100t3')); old = g.state.players[1].deck[0]
        source = self.play(g, XAVIUS); self.select(g)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD); self.assertIn(old, g.state.players[1].hand)

    def test_source_control_change_does_not_rebind_accepted_recipient(self):
        g = self.game(board=('k84.steal',), seed=seed_for('EDR_100t3')); old = g.state.players[1].deck[0]
        source = self.play(g, XAVIUS); self.select(g)
        self.assertIn(source, g.state.players[2].board); self.assertIn(old, g.state.players[1].hand)
        self.assertNotIn(old, g.state.players[2].hand)

    def test_grant_reaction_moving_original_cannot_duplicate_hand_tail(self):
        g = self.game(board=('k84.depart',), seed=seed_for('EDR_100t3')); old = g.state.players[1].deck[0]
        self.play(g, XAVIUS); self.select(g)
        self.assertEqual(g.state.players[1].hand.count(old), 1); self.assertFalse(g.state.players[1].deck)
        self.assertTrue(any(e.kind == 'zone_target_skipped' for e in g.events)); self.portable(g)

    def test_stale_original_reference_is_not_rebound(self):
        g = self.game(('k84.stale',)); old = g.state.players[1].deck[0]; self.play(g, 'k84.stale')
        self.assertEqual(g.state.players[1].hand, [old]); self.assertFalse(public_gifts(g.state.entities[old]))

    def test_two_real_battlecries_requery_remaining_deck_and_pay_once(self):
        g = self.game(deck=(YETI, SEEDLING), board=('k84.brann',)); source = self.play(g, XAVIUS)
        first = self.offers(g); index = next(i for i,o in enumerate(first) if o.gift_id != SWEET)
        eid = first[index].card.entity_id; self.select(g,index)
        self.assertIsNotNone(g.state.pending_choice); self.assertNotIn(eid,{o.card.entity_id for o in self.offers(g)})
        self.select(g); self.assertEqual(g.state.players[1].mana,36)
        self.assertEqual(sum(e.kind == 'card_played' and e.source_id == source for e in g.events),1)
        self.portable(g)

    def test_rude_awakening_on_real_xavius_uses_existing_self_repeat(self):
        g = self.game(('k84.rude',XAVIUS), deck=(YETI,SEEDLING)); self.play(g,'k84.rude'); self.play(g,XAVIUS)
        index = next(i for i,o in enumerate(self.offers(g)) if o.gift_id != SWEET); self.select(g,index)
        self.assertIsNotNone(g.state.pending_choice); self.select(g); self.assertEqual(g.state.players[1].mana,36)

    def test_private_offers_expose_no_opponent_card_gift_or_physical_references(self):
        g = self.game(deck=(YETI, SEEDLING)); self.play(g, XAVIUS)
        enemy = json.dumps(g.for_player(2).legal_actions()) + json.dumps(g.player_events(2))
        for value in (YETI, SEEDLING, 'StoredGiftOffer', 'SelectGiftedDeckCard', 'zone_epoch', 'rng_state', 'EDR_100t'):
            self.assertNotIn(value, enemy)
        own = json.dumps(g.for_player(1).legal_actions())
        self.assertIn(YETI, own); self.assertNotIn('zone_epoch', own); self.assertNotIn('entity_id', own)
        self.portable(g)

    def test_choice_budget_failure_restores_payment_and_rng(self):
        g = self.game(deck=(YETI,SEEDLING,XAVIUS),rules=Ruleset(max_choice_options=2)); saved=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,XAVIUS)
        self.assertEqual(g.snapshot(),saved)

    def test_unknown_source_validates_even_for_empty_deck(self):
        g=self.game(('k84.unknown',),deck=());saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k84.unknown')
        self.assertEqual(g.snapshot(),saved)

    def test_typed_request_and_offers_roundtrip_the_shared_codec(self):
        g=self.game();self.play(g,XAVIUS);codec=FrameCodec(g.mechanics,self.r)
        for work in (DiscoverDeckDarkGift(1,g.state.players[1].board[0]),self.branches(g)[0]):
            self.assertEqual(codec.decode(codec.encode(work)),work)

    def test_invalid_constructor_shapes_and_duplicate_gifts_rejected(self):
        with self.assertRaises(ValueError):DiscoverDeckDarkGift(True,1)
        g=self.game(deck=(YETI,SEEDLING));self.play(g,XAVIUS);work=self.branches(g)[0]
        with self.assertRaises(ValueError):replace(work,index=2)
        with self.assertRaises(ValueError):replace(work,offered=(work.offered[0],work.offered[0]))
        with self.assertRaises(ValueError):replace(work.offered[0],gift_id='unknown')

    def test_changed_selection_index_rejected_on_snapshot_restore(self):
        g=self.game(deck=(YETI,SEEDLING));self.play(g,XAVIUS);saved=deepcopy(g.snapshot())
        self.selection_nodes(saved)[0]['fields']['index']=1
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry())

    def test_changed_current_face_rejected_on_snapshot_restore(self):
        g=self.game();self.play(g,XAVIUS);saved=deepcopy(g.snapshot());node=self.selection_nodes(saved)[0]
        node['fields']['offered']['tuple'][0]['fields']['face']['fields']['cost']+=1
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry())

    def test_trimmed_offer_list_rejected_on_snapshot_restore(self):
        g=self.game(deck=(YETI,SEEDLING));self.play(g,XAVIUS);saved=deepcopy(g.snapshot())
        for node in self.selection_nodes(saved):node['fields']['offered']['tuple'].pop()
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry())

    def test_previous_schema_is_explicitly_rejected(self):
        g=self.game(deck=());saved=g.snapshot();saved['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaisesRegex(SnapshotError,f'1 through {SNAPSHOT_SCHEMA_VERSION-1}'):Game.from_snapshot(saved,registry())


if __name__=='__main__':unittest.main()
