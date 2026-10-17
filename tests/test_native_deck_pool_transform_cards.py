"""Real Neutral deck capture, any Druid type, ordinary reset and private draws."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import random
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.native_deck_pool_transform_cards import ENVOY, DRUID, POOL_ID, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice, SnapshotError, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import local_cost
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CostSpec, Damage, Destroy,
    GainArmor, InvokeBehavior, RequestChoice, RevealHandCard)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.game_boards import BoardCardFamily, BoardCardForm
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import LimitedTriggerSpec, RewindSpec
from hs_sim.engine.pools import (GenerateFromPool, GenerationContext, PoolCard,
    PoolDefinition, PoolMember, PoolQuery, sample_candidates)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.stored_pool_transforms import (DRAW, TransformStoredFromPool, decode)
from hs_sim.engine.zones import AddToDeck, CardReference, MoveCard

P = 'k145.'
NM, NS, NW, NL, UNKNOWN_SOURCE = (P+n for n in ('neutral_minion', 'neutral_spell',
    'neutral_weapon', 'neutral_location', 'unknown_source'))
DM, DS, DW, DL, DH, OTHER, UNKNOWN, POWER, FORM = (P+n for n in (
    'druid_minion', 'druid_spell', 'druid_weapon', 'druid_location', 'druid_hero',
    'mage', 'unknown_destination', 'power', 'board_form'))
MEMBERS = (DM, DS, DW, DL, DH, OTHER, NM)
CONTEXT = GenerationContext('k145-complete-explicit-druid-pool', 'experimental')


def registry(mode=None, members=MEMBERS):
    r = build_registry()
    r.register_behavior(P+'marker', lambda c: (GainArmor(c.player_id, 99),))
    def add(cid, kind, cost, cls, **kwargs):
        card = CardDefinition(cid, cid, kind, cost=cost,
            metadata=CardMetadata(True, (cls,), Rarity.COMMON, tribes=()), **kwargs)
        r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    add(NM, CardType.MINION, 1, CardClass.NEUTRAL, attack=2, health=3)
    add(NS, CardType.SPELL, 6, CardClass.NEUTRAL, on_play=P+'marker')
    add(NW, CardType.WEAPON, 5, CardClass.NEUTRAL, attack=2, durability=2)
    add(NL, CardType.LOCATION, 3, CardClass.NEUTRAL, durability=2, on_use=P+'marker')
    add(DM, CardType.MINION, 9, CardClass.DRUID, attack=8, health=8,
        battlecry=None if mode == 'board' else P+'marker')
    add(DS, CardType.SPELL, 2, CardClass.DRUID, on_play=P+'marker')
    add(DW, CardType.WEAPON, 7, CardClass.DRUID, attack=4, durability=3)
    add(DL, CardType.LOCATION, 4, CardClass.DRUID, durability=2, on_use=P+'marker')
    add(POWER, CardType.HERO_POWER, 2, CardClass.DRUID, on_use=P+'marker')
    add(DH, CardType.HERO, 8, CardClass.DRUID, health=30, hero_card=True,
        initial_hero_power=POWER, hero_armor=5)
    add(OTHER, CardType.MINION, 3, CardClass.MAGE, attack=3, health=3)
    r.register_card(CardDefinition(UNKNOWN_SOURCE, UNKNOWN_SOURCE, CardType.MINION, health=1))
    r.register_pool_card(PoolCard(UNKNOWN, CardType.SPELL, 2,
        CardMetadata(True, (CardClass.DRUID,), Rarity.COMMON, tribes=()),
        battlecry=False, deathrattle=False, choose_one=False))
    if mode == 'board':
        r.register_card(CardDefinition(FORM, FORM, CardType.MINION, cost=9, attack=8, health=8,
            metadata=CardMetadata(False, (CardClass.DRUID,), Rarity.COMMON, tribes=())))
        r.register_board_card_family(BoardCardFamily(P+'board_family', 'v1', DM, (BoardCardForm(145, FORM),)))
    r.register_pool(PoolDefinition(POOL_ID, 'k145-explicit-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember(cid, 3 if cid == DM else 1) for cid in members), complete=True))

    def ref(c, zone=Zone.DECK):
        ids = getattr(c.state.players[c.player_id], zone.value)
        if zone == Zone.HAND:
            ids = tuple(i for i in ids if c.state.entities[i].card_id == NM)
        return CardReference.capture(c.state.entities[ids[0]])
    def first(c, *, zone=Zone.DECK, empty='skip'):
        return TransformStoredFromPool(ref(c, zone), POOL_ID, DRUID, c.source_id, empty=empty)
    def fail(c):
        raise ResolutionError('K145 deliberate continuation failure')
    def put_back(c):
        target = CardReference.capture(c.state.entities[c.target_id])
        return (MoveCard(target, c.player_id, Zone.DECK, 'bottom', source_id=c.source_id),)
    def stale(c):
        request = first(c)
        return (MoveCard(request.target, c.player_id, Zone.HAND, source_id=c.source_id),
            InvokeBehavior(P+'back', c.source_id, c.player_id, request.target.entity_id), request)
    bodies = {'fail': fail, 'back': put_back, 'hand': lambda c: (first(c, zone=Zone.HAND),),
        'buff': lambda c: (BuffStoredCard(ref(c, Zone.HAND), 4, 7, c.source_id, cost=CostSpec(set_to=0)),),
        'reveal': lambda c: (RevealHandCard(ref(c, Zone.HAND).entity_id),),
        'strict': lambda c: (first(c, empty='error'),), 'stale': stale,
        'rewind': lambda c: tuple(TransformStoredFromPool(CardReference.capture(c.state.entities[i]),
            POOL_ID, DRUID, c.source_id) for i in c.state.players[c.player_id].deck),
        'preface': lambda c: (TransformStoredCard(ref(c), OTHER, c.source_id),)}
    for key, body in bodies.items():
        r.register_behavior(P+key, body)
        if key not in ('fail', 'back'):
            kwargs = dict(keywords=(Keyword.REWIND,), rewind=RewindSpec()) if key == 'rewind' else {}
            r.register_card(CardDefinition(P+key, P+key, CardType.SPELL, on_play=P+key, **kwargs))
    if mode in ('wait', 'fail', 'lethal'):
        def eligible(c):
            source = c.state.entities.get(c.event.source_id)
            return source is not None and source.card_id == ENVOY and c.event.player_id == c.player_id
        def watch(c):
            if mode == 'fail':
                return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
            if mode == 'lethal':
                return (Damage(c.state.players[c.player_id].hero_id, 40, c.source_id),)
            target = next((CardReference.capture(c.state.entities[i])
                for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id == NM), None)
            options = [ChoiceOption('ok', 'Continue'),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
                ChoiceOption('new', 'Insert a new Neutral card', (AddToDeck(c.player_id, NM, 'bottom', c.source_id),)),
                ChoiceOption('retire', 'Retire the original source', (Destroy(c.event.source_id),)),
                ChoiceOption('transfer', 'Transfer the original source', (ChangeControl(c.event.source_id, 3-c.player_id),)),
                ChoiceOption('random', 'An independent ordinary random result', (GenerateFromPool(c.player_id,
                    POOL_ID, PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='specified',
                        classes=(CardClass.MAGE,), include_neutral=False), source_id=c.source_id),))]
            if target is not None:
                options.extend((ChoiceOption('move', 'Move original target',
                    (MoveCard(target, c.player_id, Zone.HAND, source_id=c.source_id),)),
                    ChoiceOption('back', 'Leave and reenter original deck',
                        (MoveCard(target, c.player_id, Zone.HAND, source_id=c.source_id),
                         InvokeBehavior(P+'back', c.source_id, c.player_id, target.entity_id)))))
            return (RequestChoice(c.player_id, tuple(options), c.source_id),)
        r.register_behavior(P+'watch', watch); r.register_trigger_condition(P+'eligible', eligible)
        r.register_card(CardDefinition(P+'watch', P+'watch', CardType.WEAPON, durability=5,
            limited_triggers=(LimitedTriggerSpec('stored_card_transformed', P+'watch', P+'eligible'),)))
    r.validate()
    return r


@lru_cache(maxsize=None)
def shared(mode, members):
    return registry(mode, members)


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


def wires(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from wires(child)
    elif isinstance(value, list):
        for child in value:
            yield from wires(child)


class NativeDeckPoolTransformTests(unittest.TestCase):
    def game(self, hand=(ENVOY,), deck=(NM, NS, NW, NL, OTHER, DM), *, mode=None,
            members=MEMBERS, board=(), board_id=None):
        self.config = mode, members
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, deck=deck, board=board, mana=10, max_mana=10,
                weapon_card_id=P+'watch' if mode in ('wait', 'fail', 'lethal') else None),
            PlayerSetup('HERO_09', hand=(ENVOY,), deck=(NS, NM, NW), mana=10, max_mana=10)),
            seed=1453, generation_context=CONTEXT, board_id=board_id), shared(*self.config))
    def play(self, g, cid, player=1):
        eid = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(player, eid, position=len(g.state.players[player].board)
            if g.state.entities[eid].kind == CardType.MINION else None))
        return eid
    def choose(self, g, option):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (option,)))
    def draws(self, g):
        return [decode(g, e) for e in g.events if e.kind == DRAW]
    def same_snapshot(self, g, saved):
        self.assertEqual(canonical_hash(g.snapshot()), canonical_hash(saved))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        self.same_snapshot(Game.from_snapshot(saved, registry(*self.config)), saved)
        self.same_snapshot(g.clone(), saved)
        self.same_snapshot(replay(build_replay(g), registry(*self.config)), saved)
        for actor in (1, 2):
            public = json.dumps(g.for_player(actor).observe()) + json.dumps(g.player_events(actor))
            for key in ('candidates', 'rng_before', 'rng_after', 'transformation_sequence', 'pool_id'):
                self.assertNotIn('"'+key+'"', public)
            self.assertNotIn('StoredPoolTransformDraw', public)

    def test_complete_original_source_and_two_primary_faces_are_not_formal_pool_claims(self):
        from tools.card_batch import check_face
        data = load_batch(); row, = data['cards']
        self.assertEqual(len(data['official_observations']), 2)
        for o in data['official_observations']:
            check_face(row['record'], o['face'], o['locale'])
        card = shared(None, MEMBERS).card(ENVOY)
        self.assertEqual((card.cost, card.attack, card.health, card.metadata.classes),
            (4, 3, 6, (CardClass.NEUTRAL,)))
        self.assertFalse(data['formal_pool_complete'] or data['cn_calibrated'])

    def test_real_paid_native_captures_only_original_own_neutral_deck_cards(self):
        g = self.game(hand=(ENVOY, NM), board=(NM,)); before = g.state
        ids = tuple(before.players[1].deck); source = self.play(g, ENVOY)
        draws = self.draws(g)
        self.assertEqual([d.request.target.entity_id for d in draws], list(ids[:4]))
        self.assertEqual(tuple(g.state.players[1].deck), ids)
        self.assertEqual((g.state.players[1].mana, len(g.state.players[1].board),
            g.state.entities[g.state.players[1].hero_id].armor), (6, 2, 0))
        self.assertEqual([g.state.entities[i].card_id for i in ids[4:]], [OTHER, DM])
        self.assertEqual(g.state.players[2].deck, before.players[2].deck)
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id, NM)
        for d in draws:
            self.assertEqual((d.request.source_id, d.source.card_id), (source, ENVOY))
            self.assertEqual(d.candidates, tuple(sorted(((DM, 3), (DS, 1), (DW, 1), (DL, 1), (DH, 1)))))
            self.assertEqual(g.registry.card(d.selected[0]).metadata.classes, (CardClass.DRUID,))
        self.assertFalse(any(e.kind == 'spell_cast_accepted' for e in g.events))
        self.portable(g)

    def test_all_five_physical_destination_types_ignore_original_type_and_cost(self):
        for destination in (DM, DS, DW, DL, DH):
            with self.subTest(destination=destination):
                g = self.game(deck=(NS,), members=(destination,)); original = g.state.entities[g.state.players[1].deck[0]]
                self.play(g, ENVOY); current = g.state.entities[original.id]
                self.assertEqual((current.card_id, current.owner, current.controller, current.zone),
                    (destination, original.owner, original.controller, Zone.DECK))
                self.assertGreater(current.zone_epoch, original.zone_epoch)
                self.assertEqual((len(g.state.players[1].board), len(g.state.players[1].hand)), (1, 0))
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)

    def test_duplicate_physical_cards_use_independent_weighted_draws_in_original_order(self):
        g = self.game(deck=(NM, NM, NM), members=(DM, DS)); old = tuple(g.state.players[1].deck)
        self.play(g, ENVOY); draws = self.draws(g)
        self.assertEqual([d.request.target.entity_id for d in draws], list(old))
        self.assertEqual(len(set(old)), 3)
        rng = random.Random(); rng.setstate(draws[0].rng_before)
        for d in draws:
            self.assertEqual(rng.getstate(), d.rng_before)
            self.assertEqual(sample_candidates(rng, (PoolMember(DM, 3), PoolMember(DS)), 1, replacement=True), d.selected)
            self.assertEqual(rng.getstate(), d.rng_after)

    def test_qualification_uses_current_printed_face_and_empty_or_non_neutral_deck_is_noop(self):
        g = self.game(hand=(P+'preface', ENVOY), deck=(NM,)); self.play(g, P+'preface')
        before = g.snapshot()['rng_state']; self.play(g, ENVOY)
        self.assertEqual((self.draws(g), g.snapshot()['rng_state']), ([], before))
        for deck in ((), (DM, OTHER)):
            with self.subTest(deck=deck):
                g = self.game(deck=deck); before = g.snapshot()['rng_state']; self.play(g, ENVOY)
                self.assertEqual((self.draws(g), g.snapshot()['rng_state']), ([], before))

    def test_generic_hand_draw_resets_old_material_and_hides_previously_revealed_identity(self):
        g = self.game((P+'buff', P+'reveal', P+'hand', NM), members=(DS,))
        target = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == NM)
        self.play(g, P+'buff'); self.assertEqual(local_cost(g.state.entities[target])[0], 0)
        self.play(g, P+'reveal'); self.play(g, P+'hand')
        current = g.state.entities[target]
        self.assertEqual((current.kind, current.card_id, local_cost(current)[0], current.enchantments),
            (CardType.SPELL, DS, 2, []))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)
        self.assertNotIn(DS, json.dumps(g.for_player(2).observe()))
        self.portable(g)

    def test_empty_draw_and_stale_original_residence_do_not_consume_rng(self):
        g = self.game(deck=(NM,), members=(OTHER,)); before = g.snapshot()['rng_state']; self.play(g, ENVOY)
        draw, = self.draws(g)
        self.assertEqual((draw.candidates, draw.selected, draw.transformation_sequence), ((), (), None))
        self.assertEqual(g.snapshot()['rng_state'], before)
        g = self.game((P+'strict',), deck=(NM,), members=(OTHER,)); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Empty stored'):
            self.play(g, P+'strict')
        self.same_snapshot(g, before)
        g = self.game((P+'stale',), deck=(NM,), members=(DM,)); target = g.state.players[1].deck[0]
        before = g.snapshot()['rng_state']; self.play(g, P+'stale')
        self.assertEqual((self.draws(g), g.snapshot()['rng_state']), ([], before))
        self.assertEqual((g.state.entities[target].card_id, g.state.entities[target].zone), (NM, Zone.DECK))

    def test_unknown_or_nonphysical_eligible_destination_and_unknown_original_class_fail_before_rng(self):
        for members, deck in (((DM, UNKNOWN), (NM,)), ((DM, POWER), (NM,)), ((DM,), (UNKNOWN_SOURCE,))):
            with self.subTest(members=members, deck=deck):
                g = self.game(deck=deck, members=members); before = g.snapshot(); calls = []
                def fail(*args, **kwargs):
                    calls.append(args); raise AssertionError('Unsupported content reached gameplay RNG')
                with patch.object(random.Random, 'randrange', fail), self.assertRaises(ResolutionError):
                    self.play(g, ENVOY)
                self.assertFalse(calls); self.same_snapshot(g, before)

    def test_mid_batch_wait_restores_original_requests_and_allows_later_independent_rng(self):
        g = self.game(deck=(NS, NM), mode='wait', members=(DS, OTHER)); self.play(g, ENVOY)
        self.assertEqual(len(self.draws(g)), 1); self.portable(g); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.choose(g, 'bad')
        self.same_snapshot(g, before); self.choose(g, 'random')
        self.assertEqual(len(self.draws(g)), 2)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck], [DS, DS])
        self.portable(g)

    def test_pending_original_target_departure_reentry_and_new_neutral_are_not_recaptured(self):
        for choice, expected in (('move', [DS]), ('back', [DS, NM]), ('new', [DS, DS, NM])):
            with self.subTest(choice=choice):
                g = self.game(deck=(NS, NM), mode='wait', members=(DS,)); self.play(g, ENVOY)
                self.choose(g, choice)
                self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck], expected)
                self.assertEqual(len(self.draws(g)), 2 if choice == 'new' else 1)

    def test_original_source_retirement_or_control_change_keeps_actual_deck_recipient(self):
        for choice in ('retire', 'transfer'):
            with self.subTest(choice=choice):
                g = self.game(deck=(NS, NM), mode='wait', members=(DS,)); source = self.play(g, ENVOY)
                self.choose(g, choice); draws = self.draws(g)
                self.assertEqual(len(draws), 2)
                self.assertTrue(all(d.request.source_id == source and d.request.target.player_id == 1 for d in draws))
                self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck], [DS, DS])

    def test_transformation_reaction_failure_rolls_back_payment_board_deck_receipts_and_rng(self):
        g = self.game(deck=(NS, NM), mode='fail'); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate'):
            self.play(g, ENVOY)
        self.same_snapshot(g, before)

    def test_actual_rewind_retains_original_diagnostic_draws_and_reexecutes_new_roots(self):
        g = self.game((P+'rewind',), deck=(NS, NM), members=(DS,)); original = tuple(g.state.players[1].deck)
        self.play(g, P+'rewind'); self.assertEqual(len(self.draws(g)), 2)
        self.choose(g, 'retry'); self.assertEqual(len(self.draws(g)), 4)
        self.assertEqual(tuple(g.state.players[1].deck), original)
        self.assertEqual([g.state.entities[i].card_id for i in original], [DS, DS])
        self.portable(g)

    def test_second_player_native_uses_own_physical_deck_and_fixed_druid_class(self):
        g = self.game(deck=(NM,)); other = tuple(g.state.players[1].deck)
        g.apply(EndTurn(1)); ids = tuple(g.state.players[2].deck); mana = g.state.players[2].mana
        source = self.play(g, ENVOY, 2); draws = self.draws(g)
        self.assertEqual([d.request.target.entity_id for d in draws], list(ids))
        self.assertTrue(all(d.request.target.player_id == 2 and d.request.source_id == source for d in draws))
        self.assertEqual((tuple(g.state.players[1].deck), g.state.players[2].mana), (other, mana-4))

    def test_real_terminal_reaction_abandons_remaining_requests_after_one_transform(self):
        g = self.game(deck=(NS, NM), mode='lethal', members=(DS,)); self.play(g, ENVOY)
        self.assertEqual((g.state.winner, len(self.draws(g))), (2, 1))
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck], [DS, NM])
        self.portable(g)

    def test_rehashed_receipts_reject_self_consistent_pool_crop_wrong_binding_and_header(self):
        g = self.game(deck=(NS,), members=(DM, DS)); self.play(g, ENVOY)
        original = g.snapshot(); draw, = self.draws(g); codec = FrameCodec(g.mechanics, g.registry)
        index = next(i for i, e in enumerate(g.events) if e.kind == DRAW)
        rng = random.Random(); rng.setstate(draw.rng_before)
        chosen = sample_candidates(rng, (PoolMember(DM, 3),), 1, replacement=True)
        cropped = replace(draw, candidates=((DM, 3),), selected=chosen, rng_after=rng.getstate())
        for case in ('crop', 'binding', 'header', 'float', 'version'):
            with self.subTest(case=case):
                saved = deepcopy(original); event = saved['events'][index]
                if case == 'crop': event['data']['draw'] = codec.encode(cropped)
                elif case == 'binding': event['data']['draw']['fields']['transformation_sequence'] += 1
                elif case == 'header': event['player_id'] = 2
                elif case == 'float': event['data']['draw']['fields']['transformation_sequence'] = float(draw.transformation_sequence)
                else: event['data']['draw']['fields']['pool_version'] += '.changed'
                with self.assertRaises((SnapshotError, ValueError, ResolutionError)):
                    Game.from_snapshot(rehash(saved), registry(*self.config))

    def test_pending_typed_request_and_old_schema_reject_missing_pool_future_reference_or_extra_field(self):
        g = self.game(deck=(NS, NM), mode='wait', members=(DS,)); self.play(g, ENVOY)
        original = g.snapshot()
        for case in ('pool', 'future', 'extra', 'schema'):
            with self.subTest(case=case):
                saved = deepcopy(original)
                if case == 'schema': saved['schema_version'] = 351
                else:
                    controls = [x for x in wires(saved['resolution_frame']) if x.get('type', '').endswith('.TransformStoredFromPool')]
                    self.assertTrue(controls)
                    for control in controls:
                        if case == 'pool': control['fields']['pool_id'] += '.missing'
                        elif case == 'extra': control['fields']['fabricated'] = True
                        else: control['fields']['target']['fields']['zone_epoch'] = 99999
                with self.assertRaises((SnapshotError, ValueError, ResolutionError)):
                    Game.from_snapshot(rehash(saved), registry(*self.config))

    def test_board_mapped_destination_uses_shared_face_and_all_mappings_validate_before_rng(self):
        g = self.game(deck=(NS,), mode='board', members=(DM,), board_id=145); self.play(g, ENVOY)
        self.assertEqual(self.draws(g)[0].selected, (DM,))
        self.assertEqual(g.state.entities[g.state.players[1].deck[0]].card_id, FORM)
        self.portable(g)
        g = self.game(deck=(NS,), mode='board', members=(DM,), board_id=999); before = g.snapshot(); calls = []
        def fail(*args, **kwargs):
            calls.append(args); raise AssertionError('Unknown board mapping reached RNG')
        with patch.object(random.Random, 'randrange', fail), self.assertRaises(ResolutionError):
            self.play(g, ENVOY)
        self.assertFalse(calls); self.same_snapshot(g, before)


if __name__ == '__main__':
    unittest.main()
