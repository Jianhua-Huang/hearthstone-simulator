"""Real Leviathan choices, remaining-health transfer and original residences."""
from dataclasses import asdict
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_minion_health_theft_cards import CARD, BODY, load_batch, register_native_minion_health_theft_cards
from hs_sim.engine import (BattlecryRepeatSpec, CardDefinition, CardType, Game, Keyword,
    PlayCard, PlayerSetup, Registry, Scenario, SelectChoice, Zone)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, Destroy, GainArmor,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.health_theft import ChooseHealthForMinion, StealHealthToMinion
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import CardReference
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.targets import canonical_digest

P = 'k159.'
HERO, BIG, SMALL, GIANT, BENE, SHIELD, IMMUNE, STEALTH, ELUSIVE, SLEEP, LOCATION, REPEAT, WATCH, EGG = (
    P + n for n in ('hero', 'big', 'small', 'giant', 'beneficiary', 'shield', 'immune',
        'stealth', 'elusive', 'sleep', 'location', 'repeat', 'watch', 'egg'))
DIRECT, HIT, SILENCE, AUTO, ZERO, BAD_SOURCE = (P + n for n in ('direct', 'hit', 'silence', 'auto', 'zero', 'bad_source'))


@lru_cache(maxsize=40)
def registry(role, mode=None):
    assert role in ('writer', 'reader')
    r = Registry('k159-native-minion-theft-v1')
    register_native_minion_health_theft_cards(r)
    r.register_card(CardDefinition(HERO, 'Fixture hero', CardType.HERO, health=30))
    for cid, health, keywords, other in (
            (BIG, 10, (), {}), (SMALL, 2, (), {}), (GIANT, 30, (), {}), (BENE, 8, (), {}),
            (SHIELD, 3, (Keyword.DIVINE_SHIELD,), {}), (IMMUNE, 5, (Keyword.IMMUNE,), {}),
            (STEALTH, 5, (Keyword.STEALTH,), {}), (ELUSIVE, 5, (Keyword.ELUSIVE,), {}),
            (SLEEP, 5, (), dict(dormant_turns=3)),
            (REPEAT, 8, (), dict(battlecry_repeats=(BattlecryRepeatSpec(),))),
            (EGG, 3, (), dict(deathrattle=P + 'hatch'))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=health,
            keywords=keywords, **other))
    r.register_behavior(P + 'hatch', lambda c: (Summon(c.player_id, SMALL),))
    r.register_behavior(P + 'noop', lambda c: ())
    r.register_card(CardDefinition(LOCATION, 'Occupying location', CardType.LOCATION,
        durability=3, on_use=P + 'noop'))
    def recipient(c):
        return MinionReference.capture(c.state.entities[next(i for i in c.state.players[1].board
            if c.state.entities[i].card_id == BENE)])
    def direct(c):
        return (StealHealthToMinion(recipient(c), MinionReference.capture(c.state.entities[c.target_id]), 3, c.source_id),)
    bodies = {
        DIRECT: direct, HIT: lambda c: (Damage(c.target_id, 4, c.source_id),),
        SILENCE: lambda c: (Silence(c.target_id),),
        AUTO: lambda c: (TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]), c.source_id, choices='random'),),
        ZERO: lambda c: (ChooseHealthForMinion(recipient(c), 0, 3, c.source_id),),
        BAD_SOURCE: lambda c: (ChooseHealthForMinion(recipient(c), 0, 0, 999999),),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=1, on_play=cid,
            requires_target=cid in (DIRECT, HIT, SILENCE, AUTO)))
    if mode:
        def fail(c):
            raise ResolutionError('K159 deliberate failed reaction')
        def reenter(c):
            original = c.state.entities[c.target_id]
            return (SummonStoredCard(CardReference.capture(original), c.player_id),)
        r.register_behavior(P + 'fail', fail)
        r.register_behavior(P + 'reenter', reenter)
        choice_mode = mode.startswith('choice_')
        def eligible(c):
            if choice_mode:
                return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id == CARD
            return dict(c.event.data).get('health_delta', 0) < 0 and (
                c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in (CARD, DIRECT))
        def watch(c):
            source = c.event.source_id
            if choice_mode:
                donor = c.state.players[2].board[0]
                if mode == 'choice_donor_reentry':
                    return (ReturnToHand(donor), Summon(2, BIG))
                if mode == 'choice_receiver_reentry':
                    return (ReturnToHand(source), InvokeBehavior(P + 'reenter', c.source_id, 1, source))
                if mode == 'choice_donor_control': return (ChangeControl(donor, 1),)
                if mode == 'choice_receiver_control': return (ChangeControl(source, 2),)
                if mode == 'choice_receiver_death': return (Destroy(source),)
                raise AssertionError(mode)
            if mode == 'fatal': return (Damage(c.state.players[2].hero_id, 100, c.source_id),)
            if mode == 'failure': return (InvokeBehavior(P + 'fail', c.source_id, c.player_id),)
            if mode == 'atomic':
                receiver = next(e for e in c.state.entities.values() if e.card_id == BENE)
                donor = c.state.entities[c.event.target_id]
                assert (receiver.health, receiver.max_health, donor.health, donor.max_health) == (11, 11, 7, 7)
            return (RequestChoice(1, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('bad', 'Rollback', (InvokeBehavior(P + 'fail', c.source_id, 1),))), c.source_id),)
        r.register_trigger_condition(P + 'watch_condition', eligible)
        r.register_behavior(P + 'watch', watch)
        r.register_card(CardDefinition(WATCH, 'One actual reaction', CardType.MINION, health=5,
            limited_triggers=(LimitedTriggerSpec('choice_selected' if choice_mode else 'stats_changed',
                P + 'watch', condition_id=P + 'watch_condition'),)))
    r.validate(); r.freeze()
    return r


class NativeMinionHealthTheftTests(unittest.TestCase):
    def game(self, hand=(CARD,), board=(), enemy=(BIG,), mode=None, enemy_hand=()):
        self.mode = mode
        if mode: board = (WATCH, *board)
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO, hand=hand, board=board, deck=(BIG,) * 8, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup(HERO, hand=enemy_hand, board=enemy, deck=(BIG,) * 8)), seed=159), registry('writer', mode))

    def find(self, g, cid, zone='hand', pid=1):
        return next(i for i in getattr(g.state.players[pid], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid=CARD, target=None):
        eid = self.find(g, cid)
        g.apply(PlayCard(1, eid, target_id=target,
            position=len(g.state.players[1].board) if g.state.entities[eid].kind == CardType.MINION else None))
        return eid

    def choose(self, g, cid=None, eid=None, option=None):
        choice = g.state.pending_choice
        if option is None:
            option = next(o.id for o in choice.options if (cid is None or o.card_id == cid)
                and (eid is None or o.entity_id == eid))
        g.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def portable(self, g):
        reader = registry('reader', self.mode)
        self.assertIsNot(reader, g.registry)
        self.assertEqual(reader.fingerprint(), g.registry.fingerprint())
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for pid in (1, 2):
            public = json.dumps(g.for_player(pid).observe()) + json.dumps(g.for_player(pid).legal_actions()) + json.dumps(g.player_events(pid))
            for key in ('resolution_frame', 'rng_state', 'zone_epoch', 'entered_order', 'beneficiary', 'StealHealthToMinion'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def complete(self, g):
        while g.state.pending_choice is not None:
            self.choose(g)

    def test_complete_source_two_primary_faces_native_beast_and_central_registration(self):
        data = load_batch(); raw = data['cards'][0]['record']
        self.assertEqual((raw['cost'], raw['attack'], raw['health'], raw['tags']['CARDRACE']), (9, 8, 8, 20))
        self.assertEqual(canonical_digest(raw), data['cards'][0]['record_sha256'])
        self.assertEqual({o['locale'] for o in data['official_observations']}, {'zh_CN', 'en_US'})
        card = registry('writer').card(CARD)
        self.assertEqual((card.battlecry, card.metadata.tribes, card.keywords), (BODY, ('beast',), (Keyword.TAUNT,)))
        from hs_sim.cards import build_registry
        self.assertEqual(asdict(build_registry().card(CARD)), asdict(card))

    def test_real_three_choices_allow_new_targets_and_pay_only_once(self):
        g = self.game(enemy=(BIG, SMALL)); source = self.play(g)
        self.assertEqual(g.state.players[1].mana, 21)
        for cid in (BIG, SMALL, BIG):
            self.assertIsNotNone(g.state.pending_choice)
            self.choose(g, cid)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].health), (8, 16))
        self.assertEqual(g.state.entities[self.find(g, BIG, 'board', 2)].health, 4)
        self.assertEqual(sum(e.kind == 'choice_selected' for e in g.events), 3)
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual(len(g.state.battlecry_history), 1)
        self.portable(g)

    def test_wounded_donor_caps_at_remaining_health_and_dies_without_damage_packet(self):
        g = self.game((HIT, HIT, CARD)); donor = self.find(g, BIG, 'board', 2)
        self.play(g, HIT, donor); self.play(g, HIT, donor)
        source = self.play(g); start = len(g.events)
        self.choose(g, BIG)
        self.assertEqual(g.state.entities[source].health, 10)
        self.assertEqual(g.state.entities[donor].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[donor].max_health, 8)
        self.assertIsNone(g.state.pending_choice)
        self.assertFalse(any(e.kind in ('damage_dealt', 'healed', 'health_lost', 'shield_lost') for e in g.events[start:]))
        self.portable(g)

    def test_atomic_first_notification_sees_both_commits_and_wait_restores(self):
        g = self.game((DIRECT,), (BENE,), mode='atomic'); donor = self.find(g, BIG, 'board', 2)
        self.play(g, DIRECT, donor)
        self.assertIsNotNone(g.state.pending_choice)
        saved = g.snapshot(); other = self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, option='bad')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g, option='ok'); self.choose(other, option='ok')
        self.assertEqual(other.snapshot(), g.snapshot())
        self.portable(g)

    def test_direct_transfer_preserves_both_deficits_and_ordinary_silence_lifecycle(self):
        g = self.game((HIT, HIT, DIRECT, SILENCE, SILENCE), (BENE,))
        donor, receiver = self.find(g, BIG, 'board', 2), self.find(g, BENE, 'board')
        self.play(g, HIT, donor); self.play(g, HIT, receiver); self.play(g, DIRECT, donor)
        self.assertEqual((g.state.entities[donor].health, g.state.entities[donor].max_health), (3, 7))
        self.assertEqual((g.state.entities[receiver].health, g.state.entities[receiver].max_health), (7, 11))
        self.play(g, SILENCE, donor); self.play(g, SILENCE, receiver)
        self.assertEqual((g.state.entities[donor].health, g.state.entities[donor].max_health), (6, 10))
        self.assertEqual((g.state.entities[receiver].health, g.state.entities[receiver].max_health), (7, 8))
        self.portable(g)

    def test_manual_target_domain_uses_minion_ability_protections_and_shield_is_not_consumed(self):
        g = self.game(enemy=(SHIELD, IMMUNE, STEALTH, ELUSIVE, SLEEP, LOCATION)); source = self.play(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {SHIELD, ELUSIVE})
        donor = self.find(g, SHIELD, 'board', 2)
        self.choose(g, SHIELD)
        self.assertEqual(g.state.entities[source].health, 11)
        self.assertEqual(g.state.entities[donor].zone, Zone.GRAVEYARD)
        self.assertFalse(any(e.kind == 'shield_lost' for e in g.events))
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {ELUSIVE})
        self.complete(g); self.portable(g)

    def test_indirect_random_choices_use_automatic_targets_and_native_rng(self):
        g = self.game((AUTO,), (CARD,), enemy=(IMMUNE, STEALTH, SLEEP))
        source = self.find(g, CARD, 'board')
        self.play(g, AUTO, source)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(sum(e.kind == 'battlecry_choice_randomized' for e in g.events), 3)
        self.assertEqual(g.state.entities[source].health, 16)
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual(g.state.battlecry_history[-1].choices, 'random')
        self.portable(g)

    def test_no_eligible_donor_still_plays_without_choice_or_rng(self):
        g = self.game(enemy=(IMMUNE, SLEEP)); before = g.snapshot()['rng_state']
        source = self.play(g)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[source].health, 8)
        self.assertEqual(g.snapshot()['rng_state'], before)
        self.assertEqual(g.state.players[1].mana, 21)
        self.portable(g)

    def test_repeated_battlecries_have_independent_three_choice_bodies(self):
        g = self.game(board=(REPEAT,), enemy=(GIANT,)); source = self.play(g)
        self.complete(g)
        self.assertEqual(sum(e.kind == 'choice_selected' for e in g.events), 6)
        self.assertEqual(g.state.entities[source].health, 26)
        self.assertEqual(len(g.state.battlecry_history), 2)
        self.assertEqual(g.state.players[1].mana, 21)
        self.portable(g)

    def test_next_choice_observes_new_minion_from_original_donor_deathrattle(self):
        g = self.game(enemy=(EGG,)); source = self.play(g)
        self.choose(g, EGG)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {SMALL})
        self.choose(g, SMALL)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[source].health, 13)
        self.assertEqual(len(g.state.death_history), 2)
        self.portable(g)

    def test_selected_donor_reentry_does_not_receive_old_debit_but_later_choices_requery(self):
        g = self.game(mode='choice_donor_reentry'); donor = self.find(g, BIG, 'board', 2)
        source = self.play(g); self.choose(g, BIG)
        self.assertEqual(g.state.entities[donor].zone, Zone.HAND)
        self.assertEqual(g.state.entities[source].health, 8)
        current = self.find(g, BIG, 'board', 2)
        self.assertNotEqual(current, donor)
        self.assertEqual(g.state.pending_choice.options[0].entity_id, current)
        self.complete(g)
        self.assertEqual(g.state.entities[source].health, 14)
        self.assertEqual(g.state.entities[current].health, 4)
        self.portable(g)

    def test_original_receiver_reentry_cannot_adopt_remaining_choices_or_stolen_health(self):
        g = self.game(mode='choice_receiver_reentry'); source = self.play(g)
        self.choose(g, BIG)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[source].zone, Zone.BOARD)
        self.assertEqual(g.state.entities[source].health, 8)
        self.assertEqual(g.state.entities[self.find(g, BIG, 'board', 2)].health, 10)
        self.portable(g)

    def test_control_changes_or_original_receiver_death_skip_stale_transfer(self):
        for mode in ('choice_donor_control', 'choice_receiver_control', 'choice_receiver_death'):
            with self.subTest(mode=mode):
                g = self.game(mode=mode); donor = self.find(g, BIG, 'board', 2)
                source = self.play(g); self.choose(g, BIG)
                self.assertIsNone(g.state.pending_choice)
                self.assertEqual(g.state.entities[donor].health, 10)
                self.assertEqual(g.state.entities[source].health, 8)
                self.portable(g)

    def test_failed_selected_transfer_reaction_rolls_back_both_attachments_and_choice(self):
        g = self.game(mode='failure'); source = self.play(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, BIG)
        self.assertEqual(g.snapshot(), saved)
        self.assertEqual(g.state.entities[source].health, 8)
        self.assertEqual(g.state.players[1].mana, 21)
        self.portable(g)

    def test_terminal_during_first_transfer_closes_body_without_later_choices(self):
        g = self.game(mode='fatal'); source = self.play(g); self.choose(g, BIG)
        self.assertNotEqual(g.state.status, 'playing')
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[source].health, 11)
        self.assertEqual(sum(e.kind == 'choice_selected' for e in g.events), 1)
        self.assertTrue(g.state.battlecry_history[-1].interrupted)
        self.portable(g)

    def test_zero_does_not_allocate_but_unknown_source_is_checked_first(self):
        g = self.game((ZERO, BAD_SOURCE), (BENE,)); before = g.state.next_attachment_id
        self.play(g, ZERO)
        self.assertEqual(g.state.next_attachment_id, before)
        self.assertIsNone(g.state.pending_choice)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, BAD_SOURCE)
        self.assertEqual(g.snapshot(), saved)
        self.portable(g)

    def test_new_requests_codec_strict_values_and_waiting_typed_continuations(self):
        g = self.game(); source = self.play(g)
        receiver = MinionReference.capture(g.state.entities[source])
        donor = MinionReference.capture(g.state.entities[self.find(g, BIG, 'board', 2)])
        codec = FrameCodec(g.mechanics, g.registry)
        for request in (ChooseHealthForMinion(receiver, 3, 3, source), StealHealthToMinion(receiver, donor, 3, source)):
            self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(request)))), request)
        for count in (True, -1, 1.5):
            with self.assertRaises(ValueError): ChooseHealthForMinion(receiver, 3, count, source)
        with self.assertRaises(ValueError): StealHealthToMinion(receiver, receiver, 3, source)
        self.portable(g)
