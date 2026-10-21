"""Real Hatching Sigil entry, owner clock and guarded fixed summon group."""
from functools import lru_cache
import json
import unittest

from hs_sim.cards.constructed import build_registry
from hs_sim.cards.hatching_sigil_card import CARD, TOKEN, PROGRAM, EXPIRE, load_batch
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, PlayCard,
    PlayerSetup, Scenario, SelectChoice)
from hs_sim.engine.effects import ChoiceOption, GainArmor, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.model import (CardClass, CardMetadata, Keyword, LimitedTriggerSpec,
    SummonQuantitySpec, TriggerSpec)
from hs_sim.engine.player_effects import RemovePlayerEffect
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from tools.card_batch import check_face

P = 'fixture.hatching.'
BODY, MULT, START, EXPIRY, SUMMON, FAULT, AUTO_OTHER, REMOVE, BAD = (P+x for x in
    ('body', 'mult', 'start', 'expiry', 'summon', 'fault', 'auto_other', 'remove', 'bad'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
COIN = 'GAME_005'


@lru_cache(maxsize=None)
def fixture(role='writer'):
    if role not in ('writer', 'reader'): raise ValueError('Independent registry role required')
    r = build_registry()
    def fail(c): raise ResolutionError('Explicit Hatching choice failure')
    r.register_behavior(P+'fail', fail)
    r.register_card(CardDefinition(BODY, BODY, CardType.MINION, health=20, metadata=META))
    r.register_card(CardDefinition(MULT, MULT, CardType.MINION, health=20, metadata=META,
        summon_quantities=(SummonQuantitySpec(factor=2, source_kinds=(CardType.SPELL,)),)))
    def start(c):
        if c.event.player_id == c.player_id and sum(x.card_id == CARD for x in c.state.cast_history) == 1:
            return (CastSpell(c.player_id, CARD, c.source_id),)
        return ()
    r.register_behavior(P+'start', start)
    r.register_card(CardDefinition(START, START, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('turn_started', P+'start'),)))
    def eligible(c):
        if c.event.kind == 'player_effect_expired': return dict(c.event.data).get('effect_key') == PROGRAM
        e = c.state.entities.get(c.event.target_id)
        return e is not None and e.card_id == TOKEN
    r.register_trigger_condition(P+'eligible', eligible)
    def wait(c):
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
            ChoiceOption('new', 'Another Sigil', (CastSpell(c.player_id, CARD, c.source_id),)),
            ChoiceOption('fail', 'Fail', (GainArmor(c.player_id, 1),
                InvokeBehavior(P+'fail', c.source_id, c.player_id)))), c.source_id),)
    r.register_behavior(P+'wait', wait)
    r.register_behavior(P+'fault', lambda c: (InvokeBehavior(P+'fail', c.source_id, c.player_id),) if eligible(c) else ())
    for cid, event in [(EXPIRY, 'player_effect_expired'), (SUMMON, 'minion_summoned')]:
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=20, metadata=META,
            limited_triggers=(LimitedTriggerSpec(event, P+'wait', condition_id=P+'eligible'),)))
    r.register_card(CardDefinition(FAULT, FAULT, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('minion_summoned', P+'fault'),)))
    scripts = {
        AUTO_OTHER: lambda c: (CastSpell(3-c.player_id, CARD, c.source_id),),
        REMOVE: lambda c: tuple(RemovePlayerEffect(c.player_id, x.id)
            for x in c.state.players[c.player_id].player_effects if x.spec_id == PROGRAM),
        BAD: lambda c: (InvokeBehavior(EXPIRE, c.source_id, c.player_id),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META))
    return r


class HatchingSigilTests(unittest.TestCase):
    def game(self, hand=(CARD,), board=(), enemy=(), actor=1):
        own = PlayerSetup('HERO_10', hand=hand, board=board, deck=(COIN,)*8,
            mana=30, max_mana=30, mana_cap=30)
        other = PlayerSetup('HERO_08', board=enemy, deck=(COIN,)*8,
            mana=30, max_mana=30, mana_cap=30)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own),
            active_player=actor, seed=347), fixture())

    def play(self, g, cid=CARD):
        pid = g.state.active_player
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid, eid)); return eid

    def end(self, g, count=1):
        for _ in range(count): g.apply(EndTurn(g.state.active_player))

    def tokens(self, g, pid=1):
        return [g.state.entities[i] for i in g.state.players[pid].board if g.state.entities[i].card_id == TOKEN]

    def effects(self, g, pid=1):
        return [e for e in g.state.players[pid].player_effects if e.spec_id == PROGRAM]

    def choose(self, g, option):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (option,)))

    def portable(self, g):
        saved = g.snapshot(); other = Game.from_snapshot(json.loads(json.dumps(saved)), fixture('reader'))
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), fixture('reader')).snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in ('"resolution_frame"', '"rng_state"', '"SummonCause"', '"source_allocation"', '"behavior_id"'):
                self.assertNotIn(key, public)
        return other

    def test_full_root_faces_and_explicit_local_token_evidence_status(self):
        d = load_batch(); raw = d['cards'][0]['record']; token = d['dependencies'][0]['record']
        self.assertFalse(d['dependency_primary_verified']); self.assertFalse(d['cn_calibrated'])
        self.assertEqual(len(d['official_observations']), 2)
        for f in d['official_observations']:
            check_face(raw, f['face'], f['locale'], {'~GAMEPLAY_ASPROXY_BE_873':''})
        card, unit = fixture().card(CARD), fixture().card(TOKEN)
        self.assertEqual((card.cost, card.ongoing_effect_id), (4, PROGRAM))
        self.assertEqual((unit.cost, unit.attack, unit.health, unit.metadata.tribes), (2, 3, 1, ('beast',)))
        self.assertEqual((token['id'], token['dbf_id']), (TOKEN, 130778))

    def test_native_payment_only_installs_then_first_actual_owner_start_summons_three(self):
        g = self.game(); self.play(g)
        self.assertEqual(g.state.players[1].mana, 26); self.assertFalse(self.tokens(g))
        self.assertEqual(len(self.effects(g)), 1); self.end(g)
        self.assertFalse(self.tokens(g)); self.end(g)
        self.assertEqual(len(self.tokens(g)), 3); self.assertFalse(self.effects(g))
        self.assertTrue(all((e.attack, e.max_health, e.health) == (3, 1, 1) for e in self.tokens(g)))
        self.assertEqual(sum(c.card_id == CARD for c in g.state.cast_history), 1)
        self.portable(g)

    def test_second_seat_and_out_of_turn_automatic_install_keep_actual_player_clock(self):
        g = self.game(actor=2); self.play(g); self.end(g, 2)
        self.assertEqual((len(self.tokens(g, 1)), len(self.tokens(g, 2))), (0, 3))
        auto = self.game((AUTO_OTHER,)); self.play(auto, AUTO_OTHER); self.end(auto)
        self.assertEqual((len(self.tokens(auto, 1)), len(self.tokens(auto, 2))), (0, 3))

    def test_multiple_original_sigils_expire_independently(self):
        g = self.game((CARD, CARD)); first = self.play(g); second = self.play(g)
        self.assertEqual({e.source_id for e in self.effects(g)}, {first, second})
        self.end(g, 2); self.assertEqual(len(self.tokens(g)), 6); self.assertFalse(self.effects(g))
        self.assertEqual({x.request.cause.source.entity_id for x in g.state.card_summon_history}, {first, second})

    def test_fixed_materials_use_existing_spell_source_quantity_rules(self):
        g = self.game(board=(MULT,)); self.play(g); self.end(g, 2)
        self.assertEqual(len(self.tokens(g)), 6)
        self.assertTrue(all(Keyword.RUSH in e.keywords and e.attack == 3 and e.health == 1 for e in self.tokens(g)))

    def test_partial_and_full_board_capacity_expire_without_future_retry(self):
        for occupied, expected in ((5, 2), (7, 0)):
            with self.subTest(occupied=occupied):
                g = self.game(board=(BODY,)*occupied); self.play(g); self.end(g, 2)
                self.assertEqual(len(self.tokens(g)), expected); self.assertFalse(self.effects(g))
                self.end(g, 2); self.assertEqual(len(self.tokens(g)), expected)

    def test_removing_original_sigil_cancels_its_future_expiry(self):
        g = self.game((CARD, REMOVE)); self.play(g); self.play(g, REMOVE)
        self.assertFalse(self.effects(g)); self.end(g, 2); self.assertFalse(self.tokens(g))

    def test_new_sigil_installed_by_start_reaction_waits_for_later_boundary(self):
        g = self.game(board=(START,)); self.play(g); self.end(g, 2)
        self.assertEqual((len(self.tokens(g)), len(self.effects(g))), (3, 1))
        self.end(g, 2); self.assertEqual((len(self.tokens(g)), len(self.effects(g))), (6, 0))

    def test_expiry_wait_restores_original_source_and_new_instance_has_later_clock(self):
        g = self.game(board=(EXPIRY,)); source = self.play(g); self.end(g, 2)
        self.assertIsNotNone(g.state.pending_choice); self.assertFalse(self.tokens(g)); self.assertFalse(self.effects(g))
        other = self.portable(g)
        for game in (g, other): self.choose(game, 'new')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual((len(self.tokens(g)), len(self.effects(g))), (3, 1))
        self.assertTrue(all(x.request.cause.source.entity_id == source for x in g.state.card_summon_history))
        self.end(g, 2); self.assertEqual(len(self.tokens(g)), 6)

    def test_partial_summon_wait_json_clone_replay_failure_and_tail_resume_once(self):
        g = self.game(board=(SUMMON,)); self.play(g); self.end(g, 2)
        self.assertEqual(len(self.tokens(g)), 1); self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Explicit Hatching choice failure'): self.choose(other, 'fail')
        self.assertEqual(other.snapshot(), saved)
        for game in (g, other): self.choose(game, 'ok')
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(len(self.tokens(g)), 3)
        self.portable(g)

    def test_expiry_summon_failure_rolls_back_the_whole_transition(self):
        g = self.game(board=(FAULT,)); self.play(g); self.end(g); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Explicit Hatching choice failure'): self.end(g)
        self.assertEqual(g.snapshot(), saved)

    def test_real_rush_token_attacks_minion_but_not_hero_on_entry_turn(self):
        g = self.game(enemy=(BODY,)); self.play(g); self.end(g, 2); unit = self.tokens(g)[0]
        saved = g.snapshot()
        with self.assertRaises(IllegalAction): g.apply(Attack(1, unit.id, g.state.players[2].hero_id))
        self.assertEqual(g.snapshot(), saved)
        target = g.state.players[2].board[0]; g.apply(Attack(1, unit.id, target))
        self.assertEqual(g.state.entities[target].health, 17)

    def test_direct_expiry_without_original_player_effect_is_rejected(self):
        g = self.game((BAD,)); saved = g.snapshot()
        with self.assertRaisesRegex(ValueError, 'actual original Sigil expiry'): self.play(g, BAD)
        self.assertEqual(g.snapshot(), saved)
