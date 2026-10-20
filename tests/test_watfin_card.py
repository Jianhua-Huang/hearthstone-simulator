"""Actual Watfin, visible alterations and original shared discovery boundaries."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.watfin_card import CARD, TOKEN, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardPreview, CardType, Enchantment,
    Game, IllegalAction, PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError,
    TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.dredge import Dredge
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Destroy,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import preview_from_dict, preview_to_dict
from hs_sim.engine.suspicious_discoveries import (OFFERED, DELIVERED, FINISHED, KINDS,
    SuspiciousDiscoveryProfile, SuspiciousMutation, decode, draw, preview)
from hs_sim.engine.tribes import tribe_state
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.whole_card_replays import PlayDiscoveredOptions
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from test_current_deck_empty_basics import rehash

P = 'fixture.watfin.'
UNIT, WATCH = P + 'unit', P + 'watch'
MINIONS = ('CORE_CFM_790', 'CORE_EX1_012', 'CORE_EX1_096')
CTX = GenerationContext('watfin-complete-explicit-experiment', 'experimental')


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r = build_registry()
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=2, health=7, metadata=metadata()))
    def fail(c): raise ResolutionError('Explicit Watfin acquisition observer failed')
    r.register_behavior(P + 'fail', fail)
    def reenter(c):
        entity = next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id == CARD)
        return (SummonStoredCard(CardReference.capture(entity), 1),)
    r.register_behavior(P + 'reenter', reenter)
    def watch(c):
        e = c.event
        if e.kind == 'choice_selected' and e.source_id is not None and c.state.entities[e.source_id].card_id == CARD:
            if mode == 'kill': return (Destroy(e.source_id, c.source_id),)
            if mode == 'reenter': return (ReturnToHand(e.source_id), InvokeBehavior(P + 'reenter', c.source_id, c.player_id))
            if mode == 'control': return (ChangeControl(e.source_id, 2),)
            if mode == 'transform': return (Transform(e.source_id, UNIT),)
            if mode == 'fill': return tuple(AddToHand(1, UNIT, c.source_id) for _ in range(10 - len(c.state.players[1].hand)))
        if e.kind == 'card_added_to_hand' and c.state.entities[e.target_id].card_id in MINIONS:
            if mode == 'fail': raise ResolutionError('Explicit Watfin acquisition observer failed')
            if mode == 'wait':
                source = next(i for i in c.state.players[1].board if c.state.entities[i].card_id == CARD)
                return (RequestChoice(1, (ChoiceOption('ok', 'Continue'),
                    ChoiceOption('bad', 'Fail', (InvokeBehavior(P + 'fail', c.source_id, 1),)),
                    ChoiceOption('kill', 'Remove original source', (Destroy(source, c.source_id),))), c.source_id),)
        return ()
    r.register_behavior(P + 'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20,
        triggers=tuple(TriggerSpec(e, P + 'watch') for e in ('choice_selected', 'card_added_to_hand'))))
    tools = {
        'copy': lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, source_id=c.source_id),),
        'deck': lambda c: (MoveCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, Zone.DECK, source_id=c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'others': lambda c: (PlayDiscoveredOptions(c.player_id, c.source_id, c.state.card_discovery_history[-1].id),),
        'peek': lambda c: (Dredge(c.player_id, source_id=c.source_id),),
    }
    for name, body in tools.items():
        r.register_behavior(P + name, body)
        target = TargetSpec(zones=(Zone.HAND,), kinds=(CardType.MINION,), relation='friendly') if name in ('copy', 'deck') else (
            TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='friendly') if name in ('silence', 'bounce') else None)
        r.register_card(CardDefinition(P + name, name, CardType.SPELL, on_play=P + name, targeting=target))
    def trigger(c):
        source = next(c.state.entities[i] for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == CARD)
        return (TriggerBattlecry(MinionReference.capture(source), c.source_id),)
    r.register_behavior(P + 'trigger', trigger)
    r.register_card(CardDefinition(P + 'trigger', 'Explicit indirect Battlecry fixture', CardType.MINION,
        health=2, battlecry=P + 'trigger'))
    members = tuple(PoolMember(cid) for cid in (*MINIONS, CARD, 'TID_700'))
    if mode == 'empty': members = ()
    if mode == 'one': members = (PoolMember(MINIONS[0]),)
    if mode == 'unknown':
        unknown = CardDefinition(P + 'unknown', 'Known eligible unimplemented minion', CardType.MINION,
            health=2, metadata=metadata())
        r.register_pool_card(PoolCard.from_definition(unknown)); members += (PoolMember(unknown.id),)
    r.register_pool(PoolDefinition('constructed.minions', 'watfin-fixture-v1', CTX.target_id, CTX.mode, members, complete=True))
    r.validate()
    return r


def seed_for(kind, cid=None):
    profile = fixture()._suspicious_discovery_profiles[CARD]
    candidates = tuple(PoolMember(x) for x in MINIONS)
    for seed in range(10000):
        offered, index, mutation = draw(Random(seed), candidates, profile)
        if mutation.kind == kind and (cid is None or offered[index] == cid): return seed
    raise AssertionError('No deterministic native seed for requested coverage')


class WatfinTests(unittest.TestCase):
    def game(self, kind='attack', *, mode='normal', hand=(), cid=None, context=CTX, enemy_hand=()):
        board = (WATCH,) if mode in ('kill', 'reenter', 'control', 'transform', 'wait', 'fail', 'fill') else ()
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=(CARD,) + hand, board=board, deck=(UNIT,) * 12, mana=10, max_mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, deck=(UNIT,) * 12, mana=10, max_mana=10)),
            seed=seed_for(kind, cid), generation_context=context), fixture(mode))
    def entity(self, g, cid, *, player=1, zone='hand'):
        return next(i for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)
    def play(self, g, cid, target=None):
        eid = self.entity(g, cid); g.apply(PlayCard(1, eid, target)); return eid
    def proof(self, g):
        event = next(e for e in g.events if e.kind == OFFERED)
        return decode(g, dict(event.data)['proof'])
    def choose(self, g, key):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def discover(self, g, *, correct=True):
        source = self.play(g, CARD); proof = self.proof(g)
        index = proof.marked_index if correct else (proof.marked_index + 1) % len(proof.offered)
        self.choose(g, f'card{index + 1}')
        return source, proof, proof.offered[index]
    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot())); reader = fixture.__wrapped__(mode)
        self.assertEqual(Game.from_snapshot(saved, reader).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        return saved

    def test_complete_actual_source_name_catalog_and_uninitialized_token_are_pinned(self):
        data = load_batch(); r = fixture()
        self.assertEqual((len(data['cards']), len(data['dependencies']), len(data['evidence_only'])), (1, 1, 1))
        self.assertEqual(len(data['official_observations']), 2)
        self.assertEqual(len(data['name_catalog']), 4829)
        self.assertEqual(len(r._suspicious_discovery_profiles[CARD].tribes), 12)
        self.assertEqual((r.card(CARD).cost, r.card(CARD).attack, r.card(CARD).health), (2, 3, 2))
        self.assertEqual((r.card(TOKEN).cost, r.card(TOKEN).attack, r.card(TOKEN).health, r.card(TOKEN).metadata.tribes), (1, 1, 1, ('murloc',)))
        self.assertIsNone(r.card(TOKEN).battlecry); self.assertNotIn('JAIL_EVENT_100e', r.cards)
        self.assertTrue(r.card(CARD).manual_playable); self.assertFalse(r.card(TOKEN).manual_playable)
        self.assertFalse(data['cn_calibrated']); self.assertFalse(data['formal_pool_complete'])

    def test_uninitialized_token_cannot_be_silently_played_as_a_blank_minion(self):
        g = self.game(hand=(TOKEN,)); eid = self.entity(g, TOKEN); saved = g.snapshot()
        with self.assertRaisesRegex(IllegalAction, 'manually played'):
            g.apply(PlayCard(1, eid))
        self.assertEqual(g.snapshot(), saved)
        self.assertFalse(any(isinstance(a, PlayCard) and a.entity_id == eid for a in g.legal_actions()))

    def test_all_five_real_kinds_keep_original_card_identity_and_correct_source_reward(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                g = self.game(kind); source, proof, cid = self.discover(g)
                entity = g.state.entities[self.entity(g, cid)]; face = g.registry.card(cid)
                self.assertEqual(proof.mutation.kind, kind)
                self.assertEqual((g.state.players[1].mana, len(g.state.play_history), len(g.state.cast_history)), (8, 1, 0))
                self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (4, 3))
                self.assertEqual(entity.card_id, cid)
                self.assertEqual((entity.cost, entity.attack, entity.health),
                    (max(0, face.cost - (kind == 'cost')), face.attack + (kind == 'attack'), face.health + (kind == 'health')))
                if kind == 'name':
                    self.assertEqual(entity.display_name, dict(g.registry._suspicious_discovery_profiles[CARD].names)[proof.mutation.value])
                if kind == 'tribe': self.assertTrue(tribe_state(g.registry, entity).matches_any((proof.mutation.value,)))
                self.assertEqual(sum(e.kind == 'card_discovered' for e in g.events), 1)
                self.assertEqual(len(g.state.card_discovery_history), 1)
        self.portable(g)

    def test_wrong_selection_delivers_normal_card_without_source_or_recipient_bonus(self):
        g = self.game(); source, proof, cid = self.discover(g, correct=False)
        entity = g.state.entities[self.entity(g, cid)]; face = g.registry.card(cid)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (3, 2))
        self.assertEqual((entity.attack, entity.health, entity.cost), (face.attack, face.health, face.cost))
        self.assertFalse(entity.enchantments); self.assertEqual(len(g.state.card_discovery_history), 1)

    def test_original_weighted_domain_uses_normal_class_and_source_exclusions(self):
        g = self.game(); self.play(g, CARD); proof = self.proof(g)
        self.assertEqual(proof.candidates, tuple((cid, 1) for cid in MINIONS))
        self.assertEqual(set(proof.offered), set(MINIONS)); self.assertEqual(len(g.state.pending_choice.options), 3)
        self.assertNotIn(CARD, proof.offered); self.assertNotIn('TID_700', proof.offered)

    def test_menu_restore_clone_and_replay_keep_one_original_draw(self):
        g = self.game('tribe'); self.play(g, CARD); saved = self.portable(g)
        proof = self.proof(g); self.choose(g, f'card{proof.marked_index + 1}')
        restored = Game.from_snapshot(saved, fixture.__wrapped__())
        self.choose(restored, f'card{proof.marked_index + 1}')
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_name_donor_does_not_require_a_runtime_card_body_and_no_change_is_not_rerolled(self):
        r = fixture(); data = load_batch(); self.assertIn('CAP_405', dict(data['name_catalog']))
        self.assertNotIn('CAP_405', r.cards)
        shown = preview(r, MINIONS[0], CARD, SuspiciousMutation('name', 'CAP_405'))
        self.assertEqual(shown.display_name, dict(data['name_catalog'])['CAP_405'])
        profile = SuspiciousDiscoveryProfile(CARD, ((MINIONS[0], r.card(MINIONS[0]).name),), ('mech',))
        found = None
        for seed in range(200):
            candidate = draw(Random(seed), (PoolMember(MINIONS[0]),), profile)
            if candidate[2].kind == 'name': found = candidate; break
        self.assertIsNotNone(found); self.assertEqual(found[2].value, MINIONS[0])

    def test_renamed_minion_keeps_its_actual_battlecry(self):
        g = self.game('name', cid=MINIONS[0], enemy_hand=(UNIT,)); _, _, cid = self.discover(g)
        count = len(g.state.players[2].hand); entity = self.play(g, cid)
        self.assertEqual(len(g.state.players[2].hand), count - 1)
        self.assertEqual(g.state.entities[entity].card_id, MINIONS[0])
        self.assertIsNotNone(g.state.entities[entity].display_name); self.portable(g)

    def test_current_hand_copy_preserves_name_and_tribe_without_aliasing_original_body(self):
        for kind in ('name', 'tribe'):
            g = self.game(kind, hand=(P + 'copy',)); _, _, cid = self.discover(g)
            source = self.entity(g, cid); self.play(g, P + 'copy', source)
            copies = [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id == cid]
            self.assertEqual(len(copies), 2)
            self.assertEqual(copies[0].display_name, copies[1].display_name)
            self.assertEqual(tribe_state(g.registry, copies[0]), tribe_state(g.registry, copies[1]))
            self.assertTrue(set(e.id for e in copies[0].enchantments).isdisjoint(e.id for e in copies[1].enchantments))
        self.portable(g)

    def test_stored_original_dredge_preview_preserves_name_label_and_current_tribes(self):
        for kind in ('name', 'tribe'):
            g = self.game(kind, hand=(P + 'deck', P + 'peek')); _, proof, cid = self.discover(g)
            entity = self.entity(g, cid); self.play(g, P + 'deck', entity); self.play(g, P + 'peek')
            option = next(o for o in g.state.pending_choice.options if o.card_id == cid)
            if kind == 'name':
                self.assertEqual(option.preview.display_name, g.state.entities[entity].display_name)
                self.assertEqual(option.label, option.preview.display_name)
            else: self.assertIn(proof.mutation.value, option.preview.tribes)
            if kind == 'tribe': self.portable(g)
            self.choose(g, option.id)
            self.assertEqual(g.state.players[1].deck[0], entity)

    def test_indirect_battlecry_uses_genuine_automatic_discovery_without_extra_payment(self):
        g = self.game(hand=(P + 'trigger',)); self.discover(g); mana = g.state.players[1].mana
        self.play(g, P + 'trigger')
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].mana, mana)
        self.assertEqual(sum(e.kind == OFFERED for e in g.events), 2)
        self.assertEqual(len(g.state.card_discovery_history), 2)
        self.assertEqual(sum(e.kind == 'card_discovered' for e in g.events), 2)
        self.portable(g)

    def test_silence_and_normal_bounce_reset_actual_name_or_tribe_attachments(self):
        for kind in ('name', 'tribe'):
            g = self.game(kind, cid=MINIONS[2], hand=(P + 'silence', P + 'bounce'))
            _, _, cid = self.discover(g); entity = self.play(g, cid)
            self.play(g, P + 'silence', entity)
            self.assertIsNone(g.state.entities[entity].display_name)
            self.assertEqual(tribe_state(g.registry, g.state.entities[entity]).members, g.registry.card(cid).metadata.tribes)
            self.play(g, P + 'bounce', entity)
            self.assertFalse(g.state.entities[entity].enchantments)
        self.portable(g)

    def test_accepted_original_offer_survives_source_death_but_reward_does_not_rebind(self):
        g = self.game(mode='kill'); source, _, cid = self.discover(g)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertIsNotNone(self.entity(g, cid)); self.assertFalse(next(e for e in g.events if e.kind == FINISHED).target_id)
        self.portable(g, 'kill')
        g = self.game(mode='reenter'); source, _, _ = self.discover(g)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (3, 2))
        self.assertEqual(sum(e.kind == OFFERED for e in g.events), 1)
        self.portable(g, 'reenter')

    def test_original_residence_reward_follows_current_controller_and_current_body(self):
        g = self.game(mode='control'); source, _, _ = self.discover(g)
        self.assertEqual(g.state.entities[source].controller, 2)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (4, 3))
        g = self.game(mode='transform'); source, _, _ = self.discover(g)
        self.assertEqual(g.state.entities[source].card_id, UNIT)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (3, 8))
        self.portable(g, 'transform')

    def test_delivery_wait_keeps_original_modified_entity_and_next_reward(self):
        g = self.game('name', mode='wait'); source, _, cid = self.discover(g)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (3, 2))
        self.assertIsNotNone(g.state.entities[self.entity(g, cid)].display_name)
        before = self.portable(g, 'wait')
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before); self.choose(g, 'ok')
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (4, 3))
        self.portable(g, 'wait')

    def test_source_removed_during_delivery_reaction_does_not_receive_late_bonus(self):
        g = self.game(mode='wait'); source, _, _ = self.discover(g); self.choose(g, 'kill')
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertFalse(next(e for e in g.events if e.kind == FINISHED).target_id)

    def test_failed_acquisition_rolls_back_choice_modifications_reward_rng_and_delivery(self):
        g = self.game('tribe', mode='fail'); self.play(g, CARD); before = g.snapshot(); proof = self.proof(g)
        with self.assertRaises(ResolutionError): self.choose(g, f'card{proof.marked_index + 1}')
        self.assertEqual(g.snapshot(), before)

    def test_empty_pool_does_not_draw_rng_and_one_candidate_remains_genuine_discovery(self):
        g = self.game(mode='empty'); before = g._rng.getstate(); self.play(g, CARD)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g._rng.getstate(), before)
        self.assertFalse(g.state.card_discovery_history)
        g = self.game(mode='one'); source, proof, cid = self.discover(g)
        self.assertEqual((proof.offered, proof.marked_index), ((MINIONS[0],), 0))
        self.assertEqual(g.state.entities[source].attack, 4); self.assertIsNotNone(self.entity(g, cid))

    def test_unknown_eligible_minion_and_missing_generation_context_fail_explicitly(self):
        for mode, context in (('unknown', CTX), ('normal', None)):
            g = self.game(mode=mode, context=context); before = g.snapshot()
            with self.assertRaises(ValueError): self.play(g, CARD)
            self.assertEqual(g.snapshot(), before)

    def test_full_hand_burn_keeps_original_discovery_and_correct_source_bonus(self):
        g = self.game(mode='fill', hand=(UNIT,) * 9)
        source, _, cid = self.discover(g)
        self.assertEqual(g.state.entities[source].attack, 4)
        self.assertEqual(len(g.state.players[1].hand), 10)
        entity = self.entity(g, cid, zone='graveyard')
        self.assertTrue(any(e.kind == 'card_burned' and e.target_id == entity for e in g.events))

    def test_unselected_offered_execution_preserves_intrinsic_mutation_without_awarding_watfin_again(self):
        for kind in ('name', 'tribe'):
            g = self.game(kind, hand=(P + 'others',)); source, proof, _ = self.discover(g, correct=False)
            modified = proof.offered[proof.marked_index]
            self.play(g, P + 'others')
            body = g.state.entities[self.entity(g, modified, zone='board')]
            self.assertEqual(g.state.entities[source].attack, 3)
            if kind == 'name': self.assertEqual(body.display_name, dict(g.registry._suspicious_discovery_profiles[CARD].names)[proof.mutation.value])
            else: self.assertTrue(tribe_state(g.registry, body).matches_any((proof.mutation.value,)))
        self.portable(g)

    def test_player_views_only_expose_actual_faces_not_marked_slot_mutation_kind_or_rng(self):
        g = self.game('name'); self.play(g, CARD)
        for player in (1, 2):
            text = json.dumps(g.observe(player)) + json.dumps(g.player_events(player))
            for secret in ('marked_index', 'rng_before', 'suspicious_discovery_offered', 'profile_card_id'):
                self.assertNotIn(secret, text)
        proof = self.proof(g); self.choose(g, f'card{proof.marked_index + 1}')
        mine = next(p for p in g.observe(1)['players'] if p['id'] == 1)['hand']
        hidden = next(p for p in g.observe(2)['players'] if p['id'] == 1)['hand']
        self.assertTrue(any(e.get('display_name') for e in mine))
        self.assertFalse(any(e.get('display_name') for e in hidden))
        self.portable(g)

    def test_rehashed_cropped_candidate_changed_answer_and_changed_preview_reject(self):
        g = self.game('name'); self.play(g, CARD); saved = g.snapshot()
        from hs_sim.engine.continuations import FrameCodec
        for mode in ('pool', 'answer', 'preview'):
            bad = deepcopy(saved)
            if mode == 'preview':
                for row in bad['state']['pending_choice']['options']:
                    row['preview']['attack'] += 1
            else:
                event = next(e for e in bad['events'] if e['kind'] == OFFERED)
                proof = decode(g, event['data']['proof'])
                changed = replace(proof, candidates=proof.candidates[:-1]) if mode == 'pool' else replace(proof, marked_index=(proof.marked_index + 1) % 3)
                event['data']['proof'] = json.dumps(FrameCodec(g.mechanics, g.registry).encode(changed), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            with self.subTest(mode=mode), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), fixture())

    def test_waiting_reward_cannot_be_removed_duplicated_or_borrowed_after_rehash(self):
        g = self.game(mode='wait'); self.discover(g); saved = g.snapshot()
        def edit(value, mode):
            if isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict) and item.get('type') == 'hs_sim.engine.suspicious_discoveries.FinishSuspiciousDiscovery':
                        if mode == 'remove': value.pop(i)
                        elif mode == 'duplicate': value.insert(i, deepcopy(item))
                        else: item['fields']['offer_id'] += 1
                        return True
                    if edit(item, mode): return True
            elif isinstance(value, dict):
                for item in value.values():
                    if edit(item, mode): return True
            return False
        for mode in ('remove', 'duplicate', 'borrow'):
            bad = deepcopy(saved); self.assertTrue(edit(bad, mode))
            with self.subTest(mode=mode), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), fixture('wait'))

    def test_name_attachment_is_pure_and_preview_identity_roundtrips_without_changing_old_shape(self):
        ordinary = CardPreview(2, 3, 4, 4, 0)
        self.assertEqual(set(preview_to_dict(ordinary)), {'cost', 'attack', 'health', 'max_health', 'durability', 'keywords'})
        for value in (ordinary, replace(ordinary, display_name='Different actual visible name'),
                replace(ordinary, tribes=('beast', 'mech'))):
            self.assertEqual(preview_from_dict(preview_to_dict(value)), value)
        with self.assertRaises(ValueError): Enchantment(1, label='minion_name', display_name='Wrong mixed recipe', attack=1)
        with self.assertRaises(ValueError): Enchantment(1, label='minion_name')
        with self.assertRaises(ValueError): replace(ordinary, tribes=('mech', 'beast'))
        with self.assertRaises(ValueError): replace(ordinary, tribes_excluded=False)
