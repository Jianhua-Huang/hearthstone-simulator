"""Actual grant history across native armor, Hero replacement and Rewind."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.armor_gain_history_card import CARD, load_batch
from hs_sim.cards.constructed import build_registry
from hs_sim.engine import CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard, PlayerSetup, RewindSpec, Scenario, SelectChoice, SnapshotError, Zone
from hs_sim.engine.armor_gains import EVENT, gained_this_turn
from hs_sim.engine.effects import ChoiceOption, Damage, Draw, GainArmor, InvokeBehavior, LoseArmor, ReplaceHero, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.generated_heroes import InstallGeneratedHeroCard
from hs_sim.engine.model import CardClass, CardMetadata, DamageKind, TriggerSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from tools.card_batch import check_face

P = 'fixture.armor_history.'
PLAIN, SHIELD, SD, GAIN, ZERO, OTHER, LOSS, REPLACE, REPLACE_ZERO, HERO, WAIT, FAULT, RETRY, START, AFTER, GENERATED = (
    P+x for x in ('plain', 'shield', 'sd', 'gain', 'zero', 'other', 'loss', 'replace', 'replace_zero', 'hero',
        'wait', 'fault', 'retry', 'start', 'after', 'generated'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
COIN = 'GAME_005'


@lru_cache(maxsize=None)
def fixture(role='writer'):
    if role not in ('writer', 'reader'):
        raise ValueError('Independent registry role required')
    r = build_registry()
    def fail(c):
        raise ResolutionError('Explicit armor-history choice failure')
    r.register_behavior(P+'fail', fail)
    def wait(c):
        return (GainArmor(c.player_id, 3), RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id))
    scripts = {
        GAIN: lambda c: (GainArmor(c.player_id, 4),), ZERO: lambda c: (GainArmor(c.player_id, 0),),
        OTHER: lambda c: (GainArmor(3-c.player_id, 4),), LOSS: lambda c: (LoseArmor(c.player_id, None, c.source_id),),
        REPLACE: lambda c: (ReplaceHero(c.player_id, 'HERO_08', armor=5),),
        REPLACE_ZERO: lambda c: (ReplaceHero(c.player_id, 'HERO_08'),), WAIT: wait,
        GENERATED: lambda c: (InstallGeneratedHeroCard(c.player_id, HERO, c.source_id),),
        FAULT: lambda c: (GainArmor(c.player_id, 2), InvokeBehavior(P+'fail', c.source_id, c.player_id)),
        RETRY: lambda c: (GainArmor(c.player_id, 4),) if c.rewind_attempt == 0 else (),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        extra = dict(rewind=RewindSpec(), keywords=(Keyword.REWIND,)) if cid == RETRY else {}
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META, **extra))
    r.register_card(replace(r.card('HERO_08'), id=HERO, hero_card=True, hero_armor=5))
    r.register_card(CardDefinition(PLAIN, PLAIN, CardType.MINION, attack=1, health=10, metadata=META))
    r.register_card(CardDefinition(SHIELD, SHIELD, CardType.MINION, attack=1, health=10,
        keywords=(Keyword.DIVINE_SHIELD,), metadata=META))
    r.register_card(CardDefinition(SD, SD, CardType.MINION, attack=1, health=5, spell_damage=2, metadata=META))
    def start(c):
        e = c.event
        if e is None or e.source_id is None or c.state.entities[e.source_id].card_id != CARD:
            return ()
        return (GainArmor(c.player_id, 1),)
    r.register_behavior(P+'start', start)
    r.register_behavior(P+'after', lambda c: (GainArmor(c.player_id, 1),)
        if c.event is not None and c.event.source_id is not None and
        c.state.entities[c.event.source_id].controller == c.player_id else ())
    r.register_card(CardDefinition(START, START, CardType.MINION, health=5,
        triggers=(TriggerSpec('spell_cast_started', P+'start'),), metadata=META))
    r.register_card(CardDefinition(AFTER, AFTER, CardType.MINION, health=5,
        triggers=(TriggerSpec('damage_dealt', P+'after'),), metadata=META))
    return r


class ArmorGainHistoryTests(unittest.TestCase):
    def game(self, hand, board=(), armor=0, enemy=PLAIN):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01', hand=hand, board=board,
            deck=(COIN,)*8, mana=10, max_mana=10, armor=armor), PlayerSetup('HERO_08',
            board=(enemy,), deck=(COIN,)*8, mana=10, max_mana=10)), seed=0), fixture())

    def play(self, g, cid, target=None):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid, target_id=target)); return eid

    def target(self, g):
        return g.state.players[2].board[0]

    def hero(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id]

    def portable(self, g):
        saved = g.snapshot(); reader = fixture('reader')
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)), reader).snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for name in ('"armor_gain_history"', EVENT, '"resolution_frame"', '"rng_state"'):
                self.assertNotIn(name, public)

    def reject(self, saved):
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as caught:
            Game.from_snapshot(saved, fixture('reader'))
        self.assertNotIn('digest mismatch', str(caught.exception))

    def test_complete_source_and_bilingual_faces_keep_real_no_school_warrior_spell(self):
        data = load_batch(); raw = data['cards'][0]['record']
        self.assertEqual(len(data['official_observations']), 2)
        for item in data['official_observations']:
            check_face(raw, item['face'], item['locale'])
        card = fixture().card(CARD)
        self.assertEqual((card.kind, card.cost, card.spell_school), (CardType.SPELL, 2, None))

    def test_without_gain_damage_uses_spell_damage_and_initial_armor_does_not_qualify(self):
        g = self.game((CARD,), board=(SD,), armor=9); target = self.target(g)
        self.assertFalse(gained_this_turn(g.state, 1)); self.play(g, CARD, target)
        self.assertEqual(g.state.entities[target].health, 5)
        self.assertFalse(g.state.armor_gain_history); self.assertEqual(self.hero(g).armor, 9)
        self.assertEqual(g.state.players[1].mana, 8)

    def test_positive_grant_counts_even_after_all_armor_is_lost(self):
        g = self.game((GAIN, LOSS, CARD)); target = self.target(g)
        self.play(g, GAIN); self.play(g, LOSS)
        self.assertEqual(self.hero(g).armor, 0); self.assertTrue(gained_this_turn(g.state, 1))
        self.play(g, CARD, target); self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual([(x.before, x.amount, x.after) for x in g.state.armor_gain_history], [(0, 4, 4)])
        self.portable(g)

    def test_zero_and_other_player_grants_are_recorded_but_do_not_qualify(self):
        g = self.game((ZERO, OTHER, CARD)); target = self.target(g)
        self.play(g, ZERO); self.play(g, OTHER)
        self.assertFalse(gained_this_turn(g.state, 1)); self.assertTrue(gained_this_turn(g.state, 2))
        self.play(g, CARD, target); self.assertEqual(g.state.entities[target].health, 7)
        self.assertEqual([(x.player_id, x.amount) for x in g.state.armor_gain_history], [(1, 0), (2, 4)])

    def test_prior_turn_grant_does_not_qualify_despite_remaining_armor(self):
        g = self.game((GAIN, CARD)); self.play(g, GAIN)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); target = self.target(g)
        self.assertEqual(self.hero(g).armor, 4); self.assertFalse(gained_this_turn(g.state, 1))
        self.play(g, CARD, target); self.assertEqual(g.state.entities[target].health, 7)

    def test_destroy_branch_bypasses_shield_and_does_not_deal_spell_damage(self):
        g = self.game((GAIN, CARD), board=(SD,), enemy=SHIELD); target = self.target(g)
        self.play(g, GAIN); source = self.play(g, CARD, target)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertFalse([e for e in g.events if e.kind == 'damage_dealt' and e.source_id == source])

    def test_all_three_original_hero_install_paths_record_only_the_new_grant(self):
        for cid, origin in ((REPLACE, 'replacement'), (HERO, 'hero_card'), (GENERATED, 'generated_hero')):
            with self.subTest(cid=cid):
                g = self.game((cid, CARD), armor=7); old = self.hero(g).id; target = self.target(g)
                self.play(g, cid); row = g.state.armor_gain_history[-1]
                self.assertEqual((row.before, row.amount, row.after, row.origin), (7, 5, 12, origin))
                self.assertNotEqual(row.hero_id, old)
                self.play(g, CARD, target); self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.portable(g)

    def test_replacing_hero_with_no_grant_does_not_turn_carried_armor_into_a_gain(self):
        g = self.game((REPLACE_ZERO, CARD), armor=7); target = self.target(g)
        self.play(g, REPLACE_ZERO)
        self.assertEqual(g.state.armor_gain_history[-1].amount, 0)
        self.assertFalse(gained_this_turn(g.state, 1)); self.play(g, CARD, target)
        self.assertEqual(g.state.entities[target].health, 7)

    def test_spell_start_reaction_gain_is_seen_by_actual_body(self):
        g = self.game((CARD,), board=(START,)); target = self.target(g)
        self.play(g, CARD, target)
        self.assertEqual(self.hero(g).armor, 1)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)

    def test_damage_reaction_gain_does_not_rewrite_already_accepted_branch(self):
        g = self.game((CARD, CARD), board=(AFTER,)); target = self.target(g)
        self.play(g, CARD, target)
        self.assertEqual(g.state.entities[target].health, 7); self.assertTrue(gained_this_turn(g.state, 1))
        self.play(g, CARD, target); self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)

    def test_wait_restore_and_choice_failure_preserve_original_committed_gain(self):
        g = self.game((WAIT, CARD)); target = self.target(g); self.play(g, WAIT)
        self.assertIsNotNone(g.state.pending_choice); self.assertTrue(gained_this_turn(g.state, 1)); self.portable(g)
        saved = g.snapshot(); choice = g.state.pending_choice
        with self.assertRaisesRegex(ResolutionError, 'Explicit armor-history'):
            g.apply(SelectChoice(1, choice.id, ('fail',)))
        self.assertEqual(g.snapshot(), saved)
        g.apply(SelectChoice(1, choice.id, ('continue',))); self.play(g, CARD, target)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)

    def test_whole_action_failure_rolls_back_gain_facts_events_and_balance(self):
        g = self.game((FAULT,)); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Explicit armor-history'):
            self.play(g, FAULT)
        self.assertEqual(g.snapshot(), saved)

    def test_actual_rewind_retires_attempt_gain_and_does_not_poison_condition(self):
        g = self.game((RETRY, CARD)); target = self.target(g); self.play(g, RETRY)
        self.assertTrue(gained_this_turn(g.state, 1)); self.portable(g)
        choice = g.state.pending_choice; g.apply(SelectChoice(1, choice.id, ('retry',)))
        self.assertFalse(gained_this_turn(g.state, 1)); self.assertFalse(g.state.armor_gain_history)
        self.assertEqual(self.hero(g).armor, 0)
        self.play(g, CARD, target); self.assertEqual(g.state.entities[target].health, 7); self.portable(g)

    def test_rehashed_removed_modified_wrong_turn_and_wrong_hero_facts_are_rejected(self):
        g = self.game((GAIN,)); self.play(g, GAIN); saved = g.snapshot()
        for change in ('remove', 'amount', 'turn', 'hero', 'boolean'):
            with self.subTest(change=change):
                edited = json.loads(json.dumps(saved)); row = edited['state']['armor_gain_history'][0]
                if change == 'remove': edited['state']['armor_gain_history'] = []
                elif change == 'amount': row.update(amount=3, after=3)
                elif change == 'turn': row['turn'] = 0
                elif change == 'hero': row['hero_id'] = g.state.players[2].hero_id
                else: row['amount'] = True
                self.reject(edited)

    def test_current_query_is_pure_and_old_snapshot_schema_is_rejected(self):
        g = self.game((GAIN,)); self.play(g, GAIN); saved = g.snapshot()
        self.assertTrue(gained_this_turn(g.state, 1)); self.assertTrue(gained_this_turn(g.state, 1))
        self.assertEqual(g.snapshot(), saved)
        for bad in (True, 0, 3):
            with self.assertRaises(ValueError): gained_this_turn(g.state, bad)
        saved['schema_version'] -= 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, fixture('reader'))
