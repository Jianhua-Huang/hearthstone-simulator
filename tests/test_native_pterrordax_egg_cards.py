"""Original Pterrordax delivery and one atomic batch across both minion boards."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_pterrordax_egg_cards import CARD, TOKEN, load_batch, register_native_pterrordax_egg_cards
from hs_sim.engine import (BoardPresenceReference, CardDefinition, CardType, Game,
    Keyword, PlayCard, PlayerSetup, Registry, RewindSpec, Ruleset, Scenario,
    SelectChoice, SummonQuantitySpec, TargetSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, Destroy,
    GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.health_theft import StealHealthFromOtherMinions, StealHealthToMinion
from hs_sim.engine.model import DamageKind, LimitedTriggerSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P = 'k163.'
HERO, BIG, SMALL, YETI, SHIELD, IMMUNE, STEALTH, SLEEP, LOCATION, DOUBLER, WATCH, DONOR_DEATH = (
    P + s for s in ('hero', 'big', 'small', 'yeti', 'shield', 'immune', 'stealth',
        'sleep', 'location', 'doubler', 'watch', 'donor_death'))
KILL, TRIGGER, TWICE, HIT, SILENCE, REWIND, ZERO, BAD = (
    P + s for s in ('kill', 'trigger', 'twice', 'hit', 'silence', 'rewind', 'zero', 'bad'))


@lru_cache(maxsize=32)
def registry(role, mode=None):
    assert role in ('writer', 'reader')
    r = Registry('k163-pterrordax-entry-v1')
    raw = load_batch()['existing_dependencies'][0]['record']
    r.register_card(CardDefinition(TOKEN, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], metadata=metadata_from_record(raw)))
    register_native_pterrordax_egg_cards(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=30))
    r.register_behavior(P + 'noop', lambda c: ())
    r.register_behavior(P + 'donor_death', lambda c: (GainArmor(c.player_id, 2),))
    for cid, attack, health, keywords, extra in ((BIG, 1, 10, (), {}), (SMALL, 1, 1, (), {}),
            (YETI, 4, 5, (), {}), (SHIELD, 1, 3, (Keyword.DIVINE_SHIELD,), {}),
            (IMMUNE, 1, 5, (Keyword.IMMUNE,), {}), (STEALTH, 1, 5, (Keyword.STEALTH,), {}),
            (SLEEP, 1, 5, (), dict(dormant_turns=5)),
            (DOUBLER, 1, 10, (), dict(summon_quantities=(SummonQuantitySpec(),))),
            (DONOR_DEATH, 1, 1, (), dict(deathrattle=P + 'donor_death'))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=attack, health=health, keywords=keywords, **extra))
    r.register_card(CardDefinition(LOCATION, LOCATION, CardType.LOCATION, durability=3, on_use=P + 'noop'))
    def fail(c): raise ResolutionError('K163 deliberate failure')
    def reenter(c):
        return (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]), 1, cause=SummonCause.capture(c)),)
    def thief(c):
        return next(i for i in c.state.players[1].board if c.state.entities[i].card_id == TOKEN)
    scripts = {KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        TRIGGER: lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        TWICE: lambda c: (TriggerDeathrattles(c.target_id, c.source_id, times=2),),
        HIT: lambda c: (Damage(c.target_id, 4, c.source_id, DamageKind.SPELL),),
        SILENCE: lambda c: (Silence(c.target_id),),
        REWIND: lambda c: (Destroy(c.target_id, c.source_id),),
        ZERO: lambda c: (StealHealthFromOtherMinions(1, BoardPresenceReference.capture(c.state, thief(c)), 0, thief(c)),),
        BAD: lambda c: (StealHealthFromOtherMinions(1, BoardPresenceReference(999999, 1), 0, 999999),)}
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        kwargs = dict(keywords=(Keyword.REWIND,), rewind=RewindSpec()) if cid == REWIND else {}
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=1, on_play=cid,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)) if cid not in (ZERO, BAD) else None, **kwargs))
    r.register_behavior(P + 'fail', fail); r.register_behavior(P + 'reenter', reenter)
    if mode:
        entry = mode.startswith('entry')
        def eligible(c):
            if entry: return c.state.entities[c.event.target_id].card_id == TOKEN
            return dict(c.event.data).get('health_delta', 0) < 0 and c.event.source_id is not None
        def watch(c):
            if mode.endswith('failure'): return (InvokeBehavior(P + 'fail', c.source_id, 1),)
            if mode == 'stats_fatal': return (Damage(c.state.players[2].hero_id, 100, c.source_id, DamageKind.EFFECT),)
            if mode == 'stats_atomic':
                token = c.state.entities[c.event.source_id]
                big = next(c.state.entities[i] for i in c.state.players[1].board if c.state.entities[i].card_id == BIG)
                small = next(e for e in c.state.entities.values() if e.card_id == SMALL)
                assert (token.health, token.max_health, big.health, small.health) == (5, 5, 9, 0)
            options = [ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Rollback', (InvokeBehavior(P + 'fail', c.source_id, 1),))]
            if entry:
                target = c.event.target_id
                options.extend((ChoiceOption('kill', 'Original receiver dies', (Destroy(target, c.source_id),)),
                    ChoiceOption('transfer', 'Original receiver changes controller', (ChangeControl(target, 2),)),
                    ChoiceOption('reenter', 'Original receiver leaves and reenters', (ReturnToHand(target),
                        InvokeBehavior(P + 'reenter', c.source_id, 1, target_id=target))),
                    ChoiceOption('transform', 'Continuous original receiver changes face', (Transform(target, YETI),))))
            return (RequestChoice(1, tuple(options), c.source_id),)
        r.register_behavior(P + 'watch', watch); r.register_trigger_condition(P + 'eligible', eligible)
        r.register_card(CardDefinition(WATCH, WATCH, CardType.WEAPON, durability=5,
            limited_triggers=(LimitedTriggerSpec('minion_summoned' if entry else 'stats_changed',
                P + 'watch', condition_id=P + 'eligible', uses=1),)))
    r.validate(); r.freeze(); return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class NativePterrordaxEggTests(unittest.TestCase):
    def game(self, hand=(KILL,), board=(CARD, BIG), enemy=(SMALL,), mode=None, active=1, enemy_hand=(), limit=7):
        self.mode = mode
        return Game.from_scenario(Scenario((PlayerSetup(HERO, hand=hand, board=board, deck=(BIG,) * 8,
            mana=30, max_mana=30, mana_cap=30, weapon_card_id=WATCH if mode else None),
            PlayerSetup(HERO, hand=enemy_hand, board=enemy, deck=(BIG,) * 8, mana=30, max_mana=30, mana_cap=30)),
            active_player=active, seed=163), registry('writer', mode), ruleset=Ruleset(max_board=limit))

    def first(self, g, cid, zone='board', pid=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[pid], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid=KILL, target=None, pid=1):
        source = self.first(g, cid, 'hand', pid)
        if target is None and cid in (KILL, TRIGGER, TWICE, REWIND): target = self.first(g, CARD).id
        g.apply(PlayCard(pid, source.id, target_id=target,
            position=len(g.state.players[pid].board) if source.kind == CardType.MINION else None))
        return source.id

    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); reader = registry('reader', self.mode)
        self.assertIsNot(reader, g.registry); self.assertEqual(reader.fingerprint(), g.registry.fingerprint())
        other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for pid in (1, 2):
            public = json.dumps(g.for_player(pid).observe()) + json.dumps(g.for_player(pid).legal_actions()) + json.dumps(g.player_events(pid))
            for key in ('resolution_frame', 'followup_started', 'on_summon', 'behavior_id', 'next_attachment_id'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_a0_complete_two_rows_four_faces_and_existing_blank_token_pin(self):
        from tools.card_batch import check_face
        data = load_batch(); raws = {x['record']['id']: x['record'] for x in data['cards'] + data['existing_dependencies']}
        for o in data['official_observations']:
            check_face(raws[o['card_id']], o['face'], o['locale'], numeric_normalizations=data['numeric_normalizations'].get(o['card_id']))
        self.assertEqual(len(data['official_observations']), 4)
        full = build_registry(); self.assertEqual((full.card(CARD).cost, full.card(CARD).attack, full.card(CARD).health), (3, 0, 3))
        self.assertEqual(canonical_digest(asdict(full.card(TOKEN))), data['existing_definition_pins'][TOKEN])
        self.assertIsNone(full.card(TOKEN).battlecry); self.assertIsNone(full.card(TOKEN).deathrattle)

    def test_a1_actual_parent_hand_play_pays_three_without_running_deathrattle(self):
        g = self.game(hand=(CARD,), board=(BIG,)); self.play(g, CARD)
        self.assertEqual(g.state.players[1].mana, 27); self.assertEqual(self.first(g, BIG).health, 10)
        self.assertEqual(self.first(g, SMALL, pid=2).health, 1); self.assertFalse(g.state.card_summon_history); self.portable(g)

    def test_a2_natural_death_steals_from_both_boards_and_one_health_donor_dies_without_damage(self):
        g = self.game(); self.play(g); token = self.first(g, TOKEN)
        self.assertEqual((token.attack, token.health, token.max_health), (3, 5, 5))
        self.assertEqual(self.first(g, BIG).health, 9)
        self.assertFalse(any(g.state.entities[i].card_id == SMALL for i in g.state.players[2].board))
        self.assertTrue(all(e.source_id == token.id for e in g.events if e.kind == 'stats_changed'))
        self.assertFalse(any(e.kind in ('damage_dealt', 'character_healed') for e in g.events)); self.portable(g)

    def test_a3_opponent_killing_player_does_not_take_the_original_named_beneficiary(self):
        g = self.game(hand=(), enemy_hand=(KILL,), active=2); self.play(g, KILL, pid=2)
        token = self.first(g, TOKEN); self.assertEqual((token.controller, token.health), (1, 5))
        self.assertEqual(g.state.players[1].mana, 30); self.assertEqual(g.state.players[2].mana, 29); self.portable(g)

    def test_b0_wounds_and_silence_preserve_ordinary_independent_health_attachments(self):
        g = self.game(hand=(HIT, KILL, SILENCE, SILENCE), enemy=())
        self.play(g, HIT, self.first(g, BIG).id); self.play(g)
        big, token = self.first(g, BIG), self.first(g, TOKEN)
        self.assertEqual((big.health, big.max_health, token.health), (5, 9, 4))
        self.play(g, SILENCE, big.id); self.assertEqual((self.first(g, BIG).health, self.first(g, BIG).max_health), (6, 10))
        self.play(g, SILENCE, token.id); self.assertEqual(self.first(g, TOKEN).health, 3); self.portable(g)

    def test_b1_untargeted_shield_immune_and_stealth_donors_are_not_pruned(self):
        g = self.game(board=(CARD,), enemy=(SHIELD, IMMUNE, STEALTH)); self.play(g)
        self.assertEqual(self.first(g, TOKEN).health, 6)
        self.assertEqual([self.first(g, cid, pid=2).health for cid in (SHIELD, IMMUNE, STEALTH)], [2, 4, 4])
        self.assertIn(Keyword.DIVINE_SHIELD, self.first(g, SHIELD, pid=2).keywords); self.portable(g)

    def test_b2_dormant_locations_and_no_other_minions_allocate_no_health_attachments(self):
        g = self.game(board=(CARD, LOCATION), enemy=(SLEEP,)); before = g.state.next_attachment_id; rng = g._rng.getstate()
        self.play(g); self.assertEqual(self.first(g, TOKEN).health, 3)
        self.assertEqual(self.first(g, SLEEP, pid=2).health, 5); self.assertEqual(g.state.next_attachment_id, before)
        self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_b3_playing_the_same_blank_token_does_not_permanently_grant_the_egg_followup(self):
        g = self.game(hand=(TOKEN,), board=(BIG,)); self.play(g, TOKEN)
        self.assertEqual((self.first(g, TOKEN).health, self.first(g, BIG).health, self.first(g, SMALL, pid=2).health), (3, 10, 1))
        self.portable(g)

    def test_c0_first_stats_wait_observes_all_debits_and_credit_and_failed_resume_rolls_back(self):
        g = self.game(mode='stats_atomic'); self.play(g); saved = g.snapshot(); other = self.portable(g)
        self.assertEqual(self.first(g, TOKEN).health, 5)
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g); self.choose(other); self.assertEqual(other.snapshot(), g.snapshot()); self.portable(g)

    def test_c1_original_entry_wait_restores_and_continuous_transform_receives_theft(self):
        g = self.game(mode='entry_wait'); self.play(g); self.portable(g); self.choose(g, 'transform')
        transformed = self.first(g, YETI); self.assertEqual((transformed.attack, transformed.health, transformed.max_health), (4, 7, 7))
        self.assertEqual(self.first(g, BIG).health, 9); self.portable(g)

    def test_c2_entry_death_control_or_same_id_reentry_cannot_redirect_theft(self):
        for action in ('kill', 'transfer', 'reenter'):
            with self.subTest(action=action):
                g = self.game(mode='entry_wait'); self.play(g); self.choose(g, action)
                self.assertEqual((self.first(g, BIG).health, self.first(g, SMALL, pid=2).health), (10, 1))
                for entity in g.state.entities.values():
                    if entity.card_id == TOKEN and entity.zone == Zone.BOARD: self.assertEqual(entity.health, 3)
                self.portable(g)

    def test_d0_quantity_extras_each_steal_after_their_original_delivery(self):
        g = self.game(board=(DOUBLER, CARD, BIG)); self.play(g)
        tokens = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == TOKEN]
        self.assertEqual([(e.attack, e.health) for e in tokens], [(3, 5), (3, 6)])
        self.assertEqual((self.first(g, DOUBLER).health, self.first(g, BIG).health), (8, 8))
        root, = g.state.card_summon_history; self.assertEqual(root.plan.total, 2)
        self.assertTrue(all(d.followup_started for d in root.deliveries)); self.portable(g)

    def test_d1_two_actual_deathrattles_have_independent_children_and_keep_live_egg_as_donor(self):
        g = self.game(hand=(TWICE,)); self.play(g, TWICE)
        self.assertEqual(self.first(g, CARD).health, 1); self.assertEqual(len(g.state.card_summon_history), 2)
        tokens = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == TOKEN]
        self.assertEqual([e.health for e in tokens], [5, 6]); self.portable(g)

    def test_e0_entry_or_stats_exception_rolls_back_original_payment_and_all_health_changes(self):
        for mode in ('entry_failure', 'stats_failure'):
            g = self.game(mode=mode); saved = g.snapshot()
            with self.assertRaises(ResolutionError): self.play(g)
            self.assertEqual(g.snapshot(), saved)

    def test_e1_terminal_first_theft_keeps_complete_atomic_batch_and_cancels_extra_body(self):
        g = self.game(board=(DOUBLER, CARD, BIG), mode='stats_fatal'); self.play(g)
        self.assertEqual(g.state.status, 'finished'); self.assertIsNone(g.state.pending_choice)
        self.assertEqual(self.first(g, TOKEN).health, 6)
        root, = g.state.card_summon_history; self.assertEqual((root.status, len(root.deliveries)), ('interrupted', 1)); self.portable(g)

    def test_e2_full_board_live_trigger_skips_without_callback_rng_or_health_changes(self):
        g = self.game(hand=(TRIGGER,), board=(CARD, *([BIG] * 6)), enemy=()); rng = g._rng.getstate(); before = g.state.next_attachment_id
        self.play(g, TRIGGER); root, = g.state.card_summon_history
        self.assertIsNone(root.selected); self.assertEqual(g.state.next_attachment_id, before)
        self.assertEqual(g._rng.getstate(), rng); self.assertEqual(self.first(g, CARD).health, 3); self.portable(g)

    def test_f0_real_rewind_retires_old_child_and_keeps_final_single_payment(self):
        g = self.game(hand=(REWIND,)); self.play(g, REWIND); old = self.first(g, TOKEN).id; self.portable(g)
        self.choose(g, 'retry'); self.assertIsNone(g.state.pending_choice)
        self.assertNotEqual(self.first(g, TOKEN).id, old); self.assertEqual(self.first(g, TOKEN).health, 5)
        self.assertEqual((g.state.players[1].mana, len(g.state.play_history), len(g.state.card_summon_history)), (29, 1, 1)); self.portable(g)

    def test_f1_new_typed_codec_zero_and_legacy_enemy_guard_remain_strict(self):
        g = self.game(hand=(KILL, ZERO, BAD)); self.play(g); token, big = self.first(g, TOKEN), self.first(g, BIG)
        effect = StealHealthFromOtherMinions(1, BoardPresenceReference.capture(g.state, token.id), 1, token.id)
        codec = FrameCodec(g.mechanics, g.registry); self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(effect)))), effect)
        for edit in (dict(player_id=True), dict(amount=True), dict(amount=-1), dict(source_id=big.id)):
            with self.assertRaises(ValueError): replace(effect, **edit)
        with self.assertRaises(ValueError): StealHealthToMinion(MinionReference.capture(token), MinionReference.capture(big), 1, token.id)
        before, rng = g.state.next_attachment_id, g._rng.getstate(); self.play(g, ZERO)
        self.assertEqual(g.state.next_attachment_id, before); self.assertEqual(g._rng.getstate(), rng)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, BAD)
        self.assertEqual(g.snapshot(), saved); self.portable(g)

    def test_f2_rehashed_original_named_followup_cannot_change_receiver(self):
        g = self.game(mode='entry_wait'); self.play(g); saved = g.snapshot()
        bad = deepcopy(saved); bad['state']['card_summon_history'][0]['deliveries'][0]['followup_started'] = True
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry('reader', self.mode))
        self.portable(g)
