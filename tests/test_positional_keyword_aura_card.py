"""Native Raviz, continuously selected minion edges and original attack scopes."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.constructed import build_registry
from hs_sim.cards.positional_keyword_aura_card import CARD, LEFT, RIGHT, load_batch
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError)
from hs_sim.engine.combat import is_immune
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Damage, Destroy,
    GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.keyword_auras import GrantKeywordAura, validate_carrier
from hs_sim.engine.model import CardClass, CardMetadata, KeywordAuraSpec, LimitedTriggerSpec, Zone
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from tools.card_batch import check_face

P = 'fixture.edges.'
BODY, TANK, SITE, SLEEP, WAIT = (P+x for x in ('body', 'tank', 'site', 'sleeping_body', 'wait'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None)


@lru_cache(maxsize=None)
def fixture(role='writer'):
    if role not in ('writer', 'reader'): raise ValueError('Independent registry role required')
    r = build_registry()
    r.register_behavior(P+'noop', lambda c: ())
    for cid, attack, health in ((BODY, 2, 6), (TANK, 6, 20)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=attack, health=health, metadata=META))
    r.register_card(CardDefinition(SLEEP, SLEEP, CardType.MINION, attack=2, health=6,
        dormant_turns=None, metadata=META))
    r.register_card(CardDefinition(SITE, SITE, CardType.LOCATION, durability=2, on_use=P+'noop', metadata=META))
    def failure(c): raise ResolutionError('Explicit positional aura failure')
    r.register_behavior(P+'failure', failure)
    def wait(c):
        source = next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == CARD)
        return (RequestChoice(c.player_id, (
            ChoiceOption('keep', 'Continue'),
            ChoiceOption('silence', 'Silence source', (Silence(source),)),
            ChoiceOption('append', 'New right edge', (Summon(c.player_id, BODY),)),
            ChoiceOption('fail', 'Fail', (GainArmor(c.player_id, 1), Silence(source),
                InvokeBehavior(P+'failure', c.source_id, c.player_id))),
        ), c.source_id),)
    r.register_behavior(P+'wait', wait)
    r.register_card(CardDefinition(WAIT, WAIT, CardType.MINION, health=20,
        limited_triggers=(LimitedTriggerSpec('attack_declared', P+'wait'),), metadata=META))
    operations = {
        'silence': lambda c: (Silence(c.target_id),),
        'destroy': lambda c: (Destroy(c.target_id, c.source_id),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'transform': lambda c: (Transform(c.target_id, BODY),),
        'control': lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        'copy': lambda c: (CopyMinion(c.target_id, c.player_id),),
        'basecopy': lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        'sleep': lambda c: (MakeDormant(c.target_id, None),),
        'wake': lambda c: (AwakenMinion(next(i for i in c.state.players[c.player_id].board
            if c.state.entities[i].dormancy is not None)),),
        'hurt': lambda c: (Damage(c.target_id, 1, c.source_id),),
        'fault': lambda c: (Silence(c.target_id), InvokeBehavior(P+'failure', c.source_id, c.player_id)),
    }
    for key, body in operations.items():
        cid = P+key; r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, requires_target=key != 'wake', metadata=META))
    return r


class PositionalKeywordAuraTests(unittest.TestCase):
    def game(self, hand=(), board=(BODY, CARD, BODY), enemy=(TANK,), actor=1):
        one = PlayerSetup('HERO_10', hand=hand, board=board, deck=('GAME_005',)*8,
            mana=30, max_mana=30, mana_cap=30)
        two = PlayerSetup('HERO_08', board=enemy, deck=('GAME_005',)*8,
            mana=30, max_mana=30, mana_cap=30)
        return Game.from_scenario(Scenario((one, two) if actor == 1 else (two, one),
            active_player=actor, seed=349), fixture())

    def board(self, g, pid=1):
        return [g.state.entities[i] for i in g.state.players[pid].board]

    def source(self, g, pid=1):
        return next(e.id for e in self.board(g, pid) if e.card_id == CARD)

    def play(self, g, name, target=None, position=None):
        pid = g.state.active_player; cid = name if name == CARD else P+name
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid, eid, target, position)); return eid

    def choose(self, g, key):
        choice = g.state.pending_choice; g.apply(SelectChoice(choice.player_id, choice.id, (key,)))

    def flags(self, g, pid=1):
        return [(Keyword.RUSH in e.keywords, Keyword.IMMUNE_WHILE_ATTACKING in e.keywords) for e in self.board(g, pid)]

    def portable(self, g):
        saved = g.snapshot(); other = Game.from_snapshot(json.loads(json.dumps(saved)), fixture('reader'))
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), fixture('reader')).snapshot(), saved)
        for pid in (1, 2):
            public = json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for private in ('"keyword_aura"', '"attachment_id"', '"resolution_frame"', '"rng_state"'):
                self.assertNotIn(private, public)
        return other

    def test_full_original_and_bilingual_faces_match_native_declarations(self):
        data = load_batch(); raw = data['cards'][0]['record']
        self.assertEqual(len(data['official_observations']), 2)
        for face in data['official_observations']: check_face(raw, face['face'], face['locale'])
        d = fixture().card(CARD)
        self.assertEqual((d.cost, d.attack, d.health, d.metadata.tribes), (4, 4, 4, ('beast',)))
        self.assertEqual(d.keyword_auras, (LEFT, RIGHT))

    def test_native_play_only_contributes_to_current_edges_and_pays_once(self):
        g = self.game(hand=(CARD,), board=(BODY, BODY)); source = self.play(g, CARD, position=1)
        self.assertEqual(g.state.players[1].mana, 26)
        self.assertEqual(self.flags(g), [(True, False), (False, False), (False, True)])
        self.assertEqual(self.board(g)[1].id, source); self.portable(g)

    def test_single_source_gets_both_scopes_and_rush_cannot_attack_hero_on_entry(self):
        g = self.game(hand=(CARD,), board=()); source = self.play(g, CARD)
        self.assertEqual(self.flags(g), [(True, True)])
        saved = g.snapshot()
        with self.assertRaises(IllegalAction): g.apply(Attack(1, source, g.state.players[2].hero_id))
        self.assertEqual(g.snapshot(), saved)
        g.apply(Attack(1, source, self.board(g, 2)[0].id))
        self.assertEqual(g.state.entities[source].health, 4)

    def test_location_slots_do_not_take_the_minion_edge(self):
        g = self.game(board=(SITE, BODY, CARD, BODY, SITE))
        self.assertEqual(self.flags(g), [(False, False), (True, False), (False, False), (False, True), (False, False)])
        self.portable(g)

    def test_dormant_edge_stays_selected_without_skipping_to_active_minion(self):
        g = self.game(hand=(P+'wake', P+'sleep'), board=(SLEEP, BODY, CARD, SLEEP))
        self.assertEqual(self.flags(g), [(False, False)]*4)
        left, right = self.board(g)[0].id, self.board(g)[-1].id
        self.play(g, 'wake'); self.assertIn(Keyword.RUSH, g.state.entities[left].keywords)
        self.play(g, 'sleep', self.source(g)); self.assertEqual(self.flags(g), [(False, False)]*4)
        self.assertNotIn(Keyword.IMMUNE_WHILE_ATTACKING, g.state.entities[right].keywords)

    def test_new_minion_placement_and_edge_removal_reassign_continuously(self):
        g = self.game(hand=(CARD, P+'destroy'), board=(BODY, BODY))
        old_left = self.board(g)[0].id; self.play(g, CARD, position=0)
        self.assertEqual(self.flags(g), [(True, False), (False, False), (False, True)])
        self.play(g, 'destroy', old_left)
        self.assertEqual(self.flags(g), [(True, False), (False, True)])

    def test_recipient_silence_keeps_aura_and_source_silence_removes_it(self):
        g = self.game(hand=(P+'silence', P+'silence'))
        self.play(g, 'silence', self.board(g)[0].id)
        self.assertEqual(self.flags(g), [(True, False), (False, False), (False, True)])
        self.play(g, 'silence', self.source(g)); self.assertEqual(self.flags(g), [(False, False)]*3)

    def test_death_and_transform_of_source_remove_contributions(self):
        for operation in ('destroy', 'transform'):
            with self.subTest(operation=operation):
                g = self.game(hand=(P+operation,)); self.play(g, operation, self.source(g))
                self.assertFalse(any(any(x) for x in self.flags(g))); self.portable(g)

    def test_multiple_sources_union_and_one_source_removal_keeps_other(self):
        g = self.game(hand=(P+'destroy',), board=(CARD, BODY, CARD))
        self.play(g, 'destroy', self.source(g))
        self.assertEqual(self.flags(g), [(True, False), (False, True)])

    def test_source_control_moves_both_scopes_to_actual_current_owner(self):
        g = self.game(hand=(P+'control',)); source = self.source(g); self.play(g, 'control', source)
        self.assertEqual(self.flags(g), [(False, False)]*2)
        self.assertEqual(self.flags(g, 2), [(True, False), (False, True)])
        self.assertEqual(g.state.entities[source].controller, 2); self.portable(g)

    def test_return_and_replay_source_rederive_edges_from_new_position(self):
        g = self.game(hand=(P+'bounce',)); source = self.source(g); self.play(g, 'bounce', source)
        self.assertEqual(self.flags(g), [(False, False)]*2)
        self.play(g, CARD)
        self.assertEqual(self.flags(g), [(True, False), (False, False), (False, True)])
        self.assertEqual(self.board(g)[-1].id, source); self.portable(g)

    def test_current_and_base_source_copies_keep_native_declarations_not_recipient_flags(self):
        for operation in ('copy', 'basecopy'):
            with self.subTest(operation=operation):
                g = self.game(hand=(P+operation,)); original = self.source(g)
                self.play(g, operation, original); copied = self.board(g)[-1]
                self.assertEqual(copied.card_id, CARD); self.assertNotEqual(copied.id, original)
                self.assertEqual(len([a for a in copied.abilities if a.kind == 'keyword_aura']), 2)
                self.assertEqual(self.flags(g), [(True, False), (False, False), (False, False), (False, True)])
                self.portable(g)
        g = self.game(hand=(P+'copy', P+'destroy')); self.play(g, 'copy', self.board(g)[0].id)
        copy = self.board(g)[-1].id; self.play(g, 'destroy', self.source(g))
        self.assertFalse(any(any(x) for x in self.flags(g)))
        self.assertNotIn(Keyword.RUSH, g.state.entities[copy].keywords)

    def test_rightmost_immunity_only_protects_its_actual_attack(self):
        g = self.game(hand=(P+'hurt',)); right = self.board(g)[-1].id; tank = self.board(g, 2)[0].id
        self.assertFalse(is_immune(g.state, g.state.entities[right]))
        self.play(g, 'hurt', right); self.assertEqual(g.state.entities[right].health, 5)
        g.apply(Attack(1, right, tank)); self.assertEqual(g.state.entities[right].health, 5)
        self.assertEqual(g.state.entities[tank].health, 18)
        self.assertFalse(is_immune(g.state, g.state.entities[right]))

    def test_waiting_attack_restores_then_source_silence_removes_protection_and_late_failure_rolls_back(self):
        g = self.game(board=(BODY, CARD, WAIT, BODY)); right = self.board(g)[-1].id
        g.apply(Attack(1, right, self.board(g, 2)[0].id)); self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g); saved = other.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Explicit positional aura failure'): self.choose(other, 'fail')
        self.assertEqual(other.snapshot(), saved)
        for game in (g, other): self.choose(game, 'silence')
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(g.state.entities[right].zone, Zone.GRAVEYARD)
        self.portable(g)

    def test_waiting_attack_rechecks_actual_right_edge_after_new_summon(self):
        g = self.game(board=(BODY, CARD, WAIT, BODY)); right = self.board(g)[-1].id
        g.apply(Attack(1, right, self.board(g, 2)[0].id)); self.assertIsNotNone(g.state.pending_choice)
        self.choose(g, 'append')
        self.assertEqual(g.state.entities[right].zone, Zone.GRAVEYARD)
        self.assertIn(Keyword.IMMUNE_WHILE_ATTACKING, self.board(g)[-1].keywords)
        self.portable(g)

    def test_outside_wait_failure_rolls_back_aura_and_original_payment(self):
        g = self.game(hand=(P+'fault',)); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Explicit positional aura failure'):
            self.play(g, 'fault', self.source(g))
        self.assertEqual(g.snapshot(), saved)

    def test_second_seat_uses_same_native_edges(self):
        g = self.game(actor=2); self.assertEqual(self.flags(g, 2), [(True, False), (False, False), (False, True)])
        self.assertEqual(self.flags(g, 1), [(False, False)])
        g.apply(EndTurn(2)); self.portable(g)

    def test_bounded_declarations_grants_and_native_carrier_changes_are_rejected(self):
        for changes in ({'keyword': Keyword.TAUNT}, {'include_self': False}, {'adjacent_only': True},
                {'condition': 'controller_turn'}, {'tribes_any': ('beast',)}, {'card_ids': (BODY,)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(LEFT, **changes)
        with self.assertRaises(ValueError): replace(RIGHT, keyword=Keyword.IMMUNE)
        for spec in (LEFT, RIGHT):
            with self.assertRaisesRegex(ValueError, 'native declaration'): GrantKeywordAura(1, spec, 2)
        g = self.game(); source = g.state.entities[self.source(g)]
        ability = next(a for a in source.abilities if a.keyword_aura == LEFT)
        for changes in ({'origin': 'granted'}, {'expires_turn': 1}, {'consumed': True},
                {'remove_on_silence': False}, {'magnetic_id': 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(ability, **changes)
        with self.assertRaises(ValueError): validate_carrier(g.registry, BODY, CardType.MINION, [ability])
        with self.assertRaises(ValueError): validate_carrier(g.registry, CARD, CardType.MINION, [ability, replace(ability, id=999)])

    def test_rehashed_snapshot_rejects_changed_selector_native_provenance_and_derived_cache(self):
        g = self.game(); source = self.source(g); left = self.board(g)[0].id
        for mutation in ('selector', 'origin', 'cache'):
            snap = g.snapshot()
            if mutation == 'cache': snap['state']['entities'][str(left)]['aura_keywords'] = []
            else:
                row = next(a for a in snap['state']['entities'][str(source)]['abilities'] if a['kind'] == 'keyword_aura')
                if mutation == 'origin': row['origin'] = 'granted'
                else: row['keyword_aura']['target'] = 'friendly_minions'
            snap['state_hash'] = canonical_hash({k: v for k, v in snap.items() if k not in
                ('schema_version', 'events', 'events_hash', 'state_hash')})
            with self.subTest(mutation=mutation), self.assertRaises(SnapshotError):
                Game.from_snapshot(snap, fixture('reader'))
