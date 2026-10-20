import json
import unittest
from functools import lru_cache

from hs_sim.cards import build_registry
from hs_sim.cards.held_spell_school_cards import DREAD, SAGE, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, HandProgressSpec, Keyword,
    PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, SpellSchool, TargetSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, InvokeBehavior, RequestChoice, ReturnToHand)
from hs_sim.engine.held_spells import DIFFERENT_PLAYED_SCHOOLS, ability
from hs_sim.engine.model import CardClass, CardMetadata
from hs_sim.engine.played_battlecries import RepeatPlayedBattlecry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from tools.card_batch import check_face

P = 'fixture.held_schools.'
(FIRE, FIRE2, FROST, HOLY, NONE, AUTO, GIVE, ACQUIRE, COPY, BASE, CYCLE, BOUNCE,
 REPEAT, PAUSE, FAIL, PLAIN, SHIELD, SD) = tuple(P+x for x in (
    'fire', 'fire2', 'frost', 'holy', 'none', 'auto', 'give', 'acquire', 'copy', 'base', 'cycle', 'bounce',
    'repeat', 'pause', 'fail', 'plain', 'shield', 'sd'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
COIN = 'GAME_005'


@lru_cache(maxsize=None)
def fixture(role='writer'):
    if role not in ('writer', 'reader'): raise ValueError('Independent fixture registries required')
    r = build_registry()
    def held(c):
        return next(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id in (DREAD, SAGE))
    def cycle(c):
        return (MoveCard(CardReference.capture(held(c)), c.player_id, Zone.DECK),
            InvokeBehavior(P+'cycle.return', c.source_id, c.player_id))
    def back(c):
        entity = next(c.state.entities[i] for i in c.state.players[c.player_id].deck
            if c.state.entities[i].card_id in (DREAD, SAGE))
        return (MoveCard(CardReference.capture(entity), c.player_id, Zone.HAND),)
    def repeat(c):
        play = next(row for row in c.state.play_history if row.card_id == SAGE)
        return (RepeatPlayedBattlecry(c.player_id, c.source_id, play.id),)
    def fail(c): raise ResolutionError('Explicit late accepted Frost payload failure')
    bodies = {FIRE: lambda c: (), FIRE2: lambda c: (), FROST: lambda c: (), HOLY: lambda c: (), NONE: lambda c: (),
        AUTO: lambda c: (CastSpell(c.player_id, FROST, c.source_id),),
        GIVE: lambda c: (AddToHand(c.player_id, DREAD, c.source_id),),
        ACQUIRE: lambda c: (AddToHand(c.player_id, DREAD, c.source_id),),
        COPY: lambda c: (CopyCard(CardReference.capture(held(c)), c.player_id, mode='current', source_id=c.source_id),),
        BASE: lambda c: (CopyCard(CardReference.capture(held(c)), c.player_id, mode='base', source_id=c.source_id),),
        CYCLE: cycle, BOUNCE: lambda c: (ReturnToHand(c.target_id),), REPEAT: repeat,
        PAUSE: lambda c: (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),), c.source_id),), FAIL: fail}
    schools = {FIRE: SpellSchool.FIRE, FIRE2: SpellSchool.FIRE, FROST: SpellSchool.FROST,
        HOLY: SpellSchool.HOLY, ACQUIRE: SpellSchool.FIRE, PAUSE: SpellSchool.FIRE, FAIL: SpellSchool.FROST}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        if cid == REPEAT:
            r.register_card(CardDefinition(cid, cid, CardType.MINION, health=1, battlecry=cid, metadata=META))
        else:
            r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=1 if cid in schools or cid == NONE else 0,
                on_play=cid, spell_school=schools.get(cid), metadata=META,
                targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)) if cid == BOUNCE else None))
    r.register_behavior(P+'cycle.return', back)
    r.register_card(CardDefinition(PLAIN, PLAIN, CardType.MINION, attack=1, health=10, metadata=META))
    r.register_card(CardDefinition(SHIELD, SHIELD, CardType.MINION, attack=1, health=10, metadata=META,
        keywords=(Keyword.DIVINE_SHIELD,)))
    r.register_card(CardDefinition(SD, SD, CardType.MINION, health=10, spell_damage=1, metadata=META))
    return r


class HeldSpellSchoolTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(PLAIN,), other_hand=()):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board, deck=(COIN,)*10,
            mana=10, max_mana=10), PlayerSetup('HERO_08', hand=other_hand, board=enemy, deck=(COIN,)*10,
            mana=10, max_mana=10)), seed=0), fixture())

    def find(self, g, cid, player=1):
        return next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None, player=1):
        eid = self.find(g, cid, player); g.apply(PlayCard(player, eid, target_id=target)); return eid

    def mark(self, g): self.play(g, FIRE); self.play(g, FROST)

    def count(self, g, cid=DREAD):
        return sum(g.state.entities[i].card_id == cid for i in g.state.players[1].board)

    def progress(self, g, cid=DREAD): return ability(g.state.entities[self.find(g, cid)])

    def portable(self, g):
        saved = g.snapshot(); r = fixture('reader')
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)), r).snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        for p in (1, 2):
            visible = json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in ('"rng_state"', '"cast_ids"', '"progress_keys"', '"held_spells"'):
                self.assertNotIn(key, visible)

    def test_complete_two_rows_and_four_primary_faces_keep_taunt_and_elemental(self):
        data = load_batch(); rows = {x['record']['id']: x['record'] for x in data['cards']}
        self.assertEqual(len(data['official_observations']), 4)
        for o in data['official_observations']: check_face(rows[o['card_id']], o['face'], o['locale'])
        self.assertIn(Keyword.TAUNT, fixture().card(DREAD).keywords)
        self.assertEqual(fixture().card(SAGE).metadata.tribes, ('elemental',))
        self.assertEqual(fixture().card(DREAD).hand_progress.goal, 2)

    def test_two_distinct_played_schools_freeze_condition_and_summon_one_current_copy(self):
        g = self.game((DREAD, FIRE, FROST)); self.mark(g)
        self.assertTrue(self.progress(g).consumed); source = self.play(g, DREAD)
        self.assertEqual(self.count(g), 2); self.assertEqual(g.state.players[1].mana, 4)
        self.assertTrue(g.state.play_history[-1].held_spells.completed)
        self.assertTrue(all(Keyword.TAUNT in g.state.entities[i].keywords for i in g.state.players[1].board))
        self.assertEqual(g.state.entities[source].health, 5); self.portable(g)

    def test_repeated_school_different_spell_cards_do_not_reach_two(self):
        g = self.game((DREAD, FIRE, FIRE2)); self.play(g, FIRE); self.play(g, FIRE2)
        self.assertEqual(self.progress(g).progress_value, 1)
        self.play(g, DREAD); self.assertEqual(self.count(g), 1)

    def test_schoolless_and_automatic_other_school_do_not_count_as_played_school(self):
        for extra in (NONE, AUTO):
            with self.subTest(extra=extra):
                g = self.game((DREAD, FIRE, extra)); self.play(g, FIRE); self.play(g, extra)
                self.assertEqual(self.progress(g).progress_value, 1)
                self.play(g, DREAD); self.assertEqual(self.count(g), 1)

    def test_opponent_played_schools_do_not_mark_my_hand(self):
        g = self.game((DREAD,), other_hand=(FIRE, FROST)); g.apply(EndTurn(1))
        self.play(g, FIRE, player=2); self.play(g, FROST, player=2); g.apply(EndTurn(2))
        self.assertEqual(self.progress(g).progress_value, 0)
        self.play(g, DREAD); self.assertEqual(self.count(g), 1)

    def test_prior_spells_before_acquisition_and_spell_acquiring_card_do_not_count(self):
        g = self.game((FIRE, FROST, GIVE)); self.mark(g); self.play(g, GIVE)
        self.assertEqual(self.progress(g).progress_value, 0)
        g = self.game((ACQUIRE, FROST)); self.play(g, ACQUIRE); self.play(g, FROST)
        self.assertEqual(self.progress(g).progress_value, 1)
        self.play(g, DREAD); self.assertEqual(self.count(g), 1)

    def test_same_physical_card_leaving_and_reentering_hand_resets_school_witnesses(self):
        g = self.game((DREAD, FIRE, CYCLE, FROST)); original = self.find(g, DREAD)
        self.play(g, FIRE); old_entry = g.state.entities[original].hand_entry_id; self.play(g, CYCLE)
        self.assertEqual(self.find(g, DREAD), original)
        self.assertGreater(g.state.entities[original].hand_entry_id, old_entry)
        self.assertEqual(self.progress(g).progress_value, 0)
        self.play(g, FROST); self.play(g, DREAD); self.assertEqual(self.count(g), 1); self.portable(g)

    def test_current_hand_copy_inherits_earned_unique_schools_base_copy_does_not(self):
        g = self.game((DREAD, FIRE, FROST, COPY)); self.mark(g); original = self.find(g, DREAD); self.play(g, COPY)
        copied = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == DREAD and i != original)
        self.assertTrue(ability(g.state.entities[copied]).consumed)
        self.play(g, DREAD); self.play(g, DREAD); self.assertEqual(self.count(g), 4); self.portable(g)
        g = self.game((DREAD, FIRE, FROST, BASE)); self.mark(g); original = self.find(g, DREAD); self.play(g, BASE)
        copied = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == DREAD and i != original)
        self.assertEqual(ability(g.state.entities[copied]).progress_value, 0)
        g.apply(PlayCard(1, copied)); self.assertEqual(self.count(g), 1)

    def test_accepted_waiting_cast_marks_once_and_restores_before_second_school(self):
        g = self.game((DREAD, PAUSE, FROST)); self.play(g, PAUSE)
        self.assertEqual(self.progress(g).progress_value, 1); self.portable(g)
        self.assertNotIn(DREAD, json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2)))
        c = g.state.pending_choice; g.apply(SelectChoice(1, c.id, ('continue',)))
        self.assertEqual(self.progress(g).progress_value, 1)
        self.play(g, FROST); self.play(g, DREAD); self.assertEqual(self.count(g), 2)

    def test_late_frost_failure_rolls_back_new_progress_and_original_spell_play(self):
        g = self.game((DREAD, FIRE, FAIL)); self.play(g, FIRE); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Explicit late accepted Frost'): self.play(g, FAIL)
        self.assertEqual(g.snapshot(), saved); self.assertEqual(self.progress(g).progress_value, 1)

    def test_sage_hits_all_enemies_as_minion_ability_without_own_spell_power(self):
        g = self.game((SAGE, FIRE, FROST), (SD,), (PLAIN, SHIELD)); self.mark(g); self.play(g, SAGE)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 26)
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board], [6, 10])
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[g.state.players[2].board[1]].keywords)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].health, 10); self.portable(g)

    def test_unqualified_sage_and_full_board_dread_have_no_extra_effect(self):
        g = self.game((SAGE, FIRE)); self.play(g, FIRE); self.play(g, SAGE)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)
        g = self.game((DREAD, FIRE, FROST), (PLAIN,)*6); self.mark(g); self.play(g, DREAD)
        self.assertEqual(self.count(g), 1); self.assertEqual(len(g.state.players[1].board), 7)

    def test_qualified_played_history_keeps_original_verdict_after_bounce_resets_carrier(self):
        g = self.game((SAGE, FIRE, FROST, BOUNCE, REPEAT)); self.mark(g); source = self.play(g, SAGE)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 26)
        self.play(g, BOUNCE, source); self.assertEqual(self.progress(g, SAGE).progress_value, 0)
        self.play(g, REPEAT); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 22)
        self.portable(g)

    def test_unqualified_history_cannot_borrow_later_ready_carrier_schools(self):
        g = self.game((SAGE, BOUNCE, FIRE, FROST, REPEAT)); source = self.play(g, SAGE)
        self.play(g, BOUNCE, source); self.mark(g); self.assertTrue(self.progress(g, SAGE).consumed)
        self.play(g, REPEAT); self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)

    def test_progress_stops_at_two_unique_witnesses_and_reserved_spec_is_finite(self):
        g = self.game((DREAD, FIRE, FROST, HOLY)); self.mark(g); witnesses = self.progress(g).progress_keys
        self.play(g, HOLY); self.assertEqual(self.progress(g).progress_keys, witnesses)
        for spec in (HandProgressSpec('spell_cast', goal=3, condition_id=DIFFERENT_PLAYED_SCHOOLS),
                HandProgressSpec('event', event='turn_started', goal=2, on_complete=FIRE,
                    condition_id=DIFFERENT_PLAYED_SCHOOLS)):
            with self.subTest(spec=spec), self.assertRaises(ValueError): fixture().validate_hand_progress(spec)

    def test_rehashed_same_school_schoolless_and_automatic_witnesses_are_rejected(self):
        for cards in ((FIRE, FIRE2), (FIRE, NONE), (FIRE, AUTO)):
            with self.subTest(cards=cards):
                g = self.game((DREAD,)+cards); self.play(g, cards[0]); self.play(g, cards[1])
                if cards[1] == AUTO:
                    ids = [row.id for row in g.state.cast_history if row.card_id in (FIRE, FROST)]
                else: ids = [row.id for row in g.state.cast_history]
                bad = json.loads(json.dumps(g.snapshot())); eid = self.find(g, DREAD)
                entry = bad['state']['entities'][str(eid)]
                a = next(x for x in entry['abilities'] if x['kind'] == 'hand_progress')
                a.update(progress_keys=['cast:'+str(i) for i in ids], progress_units=[1, 1],
                    progress_value=2, progress_completions=1, consumed=True)
                bad['state_hash'] = canonical_hash({k:v for k,v in bad.items()
                    if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
                with self.assertRaises(SnapshotError) as error: Game.from_snapshot(bad, fixture())
                self.assertNotIn('digest mismatch', str(error.exception))
