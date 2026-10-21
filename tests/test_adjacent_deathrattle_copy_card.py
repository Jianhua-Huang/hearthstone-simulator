"""Real Rockfang entry and complete live Deathrattle material lifecycle."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.adjacent_deathrattle_copy_card import CARD, load_batch
from hs_sim.cards.constructed import build_registry
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, SnapshotError, UseLocation, Zone)
from hs_sim.engine.deathrattle_copies import GainAdjacentDeathrattles
from hs_sim.engine.deathrattle_memory import GrowDeathrattleSummon
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, CopyMinion,
    Destroy, GainArmor, GrantDeathrattle, InvokeBehavior, RequestChoice, ReturnToHand,
    Silence, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass, CardMetadata, LimitedTriggerSpec, TargetSpec, TriggerSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from tools.card_batch import check_face

P = 'fixture.adjacent_dr.'
LEFT, RIGHT, FAR, DORMANT, LOCATION, DRAGON, WATCH, FAULT, BLOCK = (P+x for x in
    ('left', 'right', 'far', 'dormant', 'location', 'dragon', 'watch', 'fault', 'block'))
KILL, SILENCE, CURRENT, BASE, RETURN, CONTROL, CHANGE, EXTRA, GROW, QUEUE = (P+x for x in
    ('kill', 'silence', 'current', 'base', 'return', 'control', 'change', 'extra', 'grow', 'queue'))
COIN, DRAWER, HOARDER, EGG, ROOST, THORNS = 'GAME_005', 'TLC_603', 'CATA_897', 'CATA_210', 'EDR_454', 'EDR_491'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(maxsize=None)
def fixture(role='writer'):
    if role not in ('writer', 'reader'): raise ValueError('Independent registry role required')
    r = build_registry()
    r.register_behavior(P+'coin', lambda c: (AddToHand(c.player_id, COIN, c.source_id),))
    r.register_behavior(P+'armor', lambda c: (GainArmor(c.player_id, 3),))
    r.register_behavior(P+'noop', lambda c: ())
    for cid, body in [(LEFT, 'coin'), (RIGHT, 'armor'), (FAR, 'coin'), (DORMANT, 'coin')]:
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=8,
            deathrattle=P+body, dormant_turns=2 if cid == DORMANT else 0, metadata=META))
    r.register_card(CardDefinition(LOCATION, LOCATION, CardType.LOCATION, durability=2, on_use=P+'noop', metadata=META))
    r.register_card(CardDefinition(DRAGON, DRAGON, CardType.MINION, attack=5, health=6,
        metadata=replace(META, tribes=('dragon',))))
    r.register_card(CardDefinition(BLOCK, BLOCK, CardType.MINION, health=5,
        keywords=(Keyword.DEATHRATTLE_SUPPRESSOR,), metadata=META))
    def fail(c): raise ResolutionError('Explicit complete Deathrattle grant failure')
    r.register_behavior(P+'fail', fail)
    def recipient(c):
        e = c.state.entities.get(c.event.target_id)
        return e is not None and e.card_id == CARD and dict(c.event.data).get('ability_kind') == 'deathrattle'
    r.register_trigger_condition(P+'recipient', recipient)
    r.register_behavior(P+'wait', lambda c: (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
        ChoiceOption('fail', 'Fail', (GainArmor(c.player_id, 1), InvokeBehavior(P+'fail', c.source_id, c.player_id)))), c.source_id),))
    r.register_behavior(P+'fault', lambda c: (InvokeBehavior(P+'fail', c.source_id, c.player_id),) if recipient(c) else ())
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=5, metadata=META,
        limited_triggers=(LimitedTriggerSpec('ability_granted', P+'wait', condition_id=P+'recipient'),)))
    r.register_card(CardDefinition(FAULT, FAULT, CardType.MINION, health=5, metadata=META,
        triggers=(TriggerSpec('ability_granted', P+'fault'),)))
    def grow(c):
        e = c.state.entities[c.target_id]
        a = next(a for a in e.abilities if a.deathrattle_memory is not None)
        return (GrowDeathrattleSummon(MinionReference.capture(e), a.id),)
    def queue(c):
        ref = MinionReference.capture(c.state.entities[c.target_id])
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Gain'), ChoiceOption('leave', 'Return',
            (ReturnToHand(c.target_id, to_owner=True),))), c.source_id), GainAdjacentDeathrattles(ref))
    scripts = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),), SILENCE: lambda c: (Silence(c.target_id),),
        CURRENT: lambda c: (CopyMinion(c.target_id, c.player_id, mode='current'),),
        BASE: lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        RETURN: lambda c: (ReturnToHand(c.target_id, to_owner=True),),
        CONTROL: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        CHANGE: lambda c: (Transform(c.target_id, DRAGON),),
        EXTRA: lambda c: (GrantDeathrattle(c.target_id, P+'coin', c.source_id, expires_turn=c.state.turn),
            GrantDeathrattle(c.target_id, P+'coin', c.source_id, expires_turn=c.state.turn)),
        GROW: grow, QUEUE: queue,
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    return r


class AdjacentDeathrattleCopyTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), deck=(COIN,)*10):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_05', hand=hand, board=board, deck=deck,
            mana=30, max_mana=30, mana_cap=30), PlayerSetup('HERO_08', board=enemy, deck=(COIN,)*10,
            mana=30, max_mana=30, mana_cap=30)), seed=346), fixture())

    def first(self, g, cid, p=1, zone='board'):
        return next(i for i in getattr(g.state.players[p], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None, position=None):
        eid = self.first(g, cid, zone='hand')
        g.apply(PlayCard(1, eid, target, position)); return eid

    def abilities(self, g, eid):
        return tuple(a for a in g.state.entities[eid].abilities if a.kind == 'deathrattle')

    def choose(self, g, option):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (option,)))

    def count(self, g, cid, p=1, zone='hand'):
        return sum(g.state.entities[i].card_id == cid for i in getattr(g.state.players[p], zone))

    def portable(self, g):
        saved = g.snapshot(); other = Game.from_snapshot(json.loads(json.dumps(saved)), fixture('reader'))
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), fixture('reader')).snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in ('deathrattle_copied_from', 'deathrattle_memory', 'deathrattle_inherited_from',
                    'CopiedDeathrattleSource', 'rng_state', 'resolution_frame', 'behavior_id'):
                self.assertNotIn('"'+key+'"', public)
        return other

    def seeded(self, extra=(), board=(LEFT, RIGHT, FAR)):
        g = self.game((CARD, KILL, *extra), board)
        source = self.play(g, CARD, position=1)
        return g, source

    def test_complete_raw_and_bilingual_faces_and_beast_metadata(self):
        d = load_batch(); raw = d['cards'][0]['record']; card = fixture().card(CARD)
        self.assertEqual((card.cost, card.attack, card.health, card.metadata.classes, card.metadata.tribes),
            (3, 3, 2, ('hunter',), ('beast',)))
        self.assertEqual(len(d['official_observations']), 2)
        for f in d['official_observations']: check_face(raw, f['face'], f['locale'])

    def test_native_hand_entry_copies_only_immediate_left_and_right_complete_declarations(self):
        g, source = self.seeded(); rows = self.abilities(g, source)
        self.assertEqual([a.deathrattle_card_id for a in rows], [LEFT, RIGHT])
        self.assertEqual([a.deathrattle_copied_from.origin.entity_id for a in rows],
            [self.first(g, LEFT), self.first(g, RIGHT)])
        self.assertTrue(all(a.source_id == source and a.deathrattle_grant_card_id == CARD for a in rows))
        self.assertEqual(g.state.players[1].mana, 27)
        self.play(g, KILL, source)
        self.assertEqual(self.count(g, COIN), 1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 3)
        self.assertEqual(len(self.abilities(g, self.first(g, FAR))), 1)

    def test_edge_has_one_neighbor_and_no_neighbors_is_valid_empty_grant(self):
        g = self.game((CARD,), (LEFT, RIGHT)); source = self.play(g, CARD, position=0)
        self.assertEqual([a.deathrattle_card_id for a in self.abilities(g, source)], [LEFT])
        empty = self.game((CARD,)); eid = self.play(empty, CARD)
        self.assertFalse(self.abilities(empty, eid))

    def test_location_is_a_physical_separator_and_dormant_is_not_active_material(self):
        g = self.game((CARD,), (LEFT, LOCATION, RIGHT)); source = self.play(g, CARD, position=2)
        self.assertEqual([a.deathrattle_card_id for a in self.abilities(g, source)], [RIGHT])
        dormant = self.game((CARD,), (DORMANT,)); source = self.play(dormant, CARD)
        self.assertFalse(self.abilities(dormant, source))

    def test_silenced_donor_has_no_declaration_to_copy(self):
        g = self.game((CARD, SILENCE), (LEFT,)); self.play(g, SILENCE, self.first(g, LEFT))
        source = self.play(g, CARD); self.assertFalse(self.abilities(g, source))

    def test_duplicate_temporary_grants_are_independent_permanent_new_attachments(self):
        g = self.game((CARD, EXTRA, KILL), (LEFT,)); left = self.first(g, LEFT)
        self.play(g, EXTRA, left); source = self.play(g, CARD)
        rows = self.abilities(g, source); self.assertEqual(len(rows), 3)
        self.assertEqual(len({a.id for a in rows}), 3)
        self.assertTrue(all(a.origin == 'granted' and a.expires_turn is None and a.remove_on_silence for a in rows))
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(len(self.abilities(g, left)), 1); self.assertEqual(len(self.abilities(g, source)), 3)
        before = self.count(g, COIN); self.play(g, KILL, source)
        self.assertEqual(self.count(g, COIN)-before, 3)

    def test_prohibition_does_not_erase_structural_material(self):
        g = self.game((CARD, KILL, KILL), (LEFT, RIGHT, BLOCK)); source = self.play(g, CARD, position=1)
        self.assertEqual(len(self.abilities(g, source)), 2)
        self.play(g, KILL, self.first(g, BLOCK)); self.play(g, KILL, source)
        self.assertEqual(self.count(g, COIN), 1)

    def test_later_donor_transform_or_silence_does_not_rewrite_grants(self):
        g, source = self.seeded((CHANGE, SILENCE))
        old = deepcopy(self.abilities(g, source))
        self.play(g, CHANGE, self.first(g, LEFT)); self.play(g, SILENCE, self.first(g, RIGHT))
        self.assertEqual(self.abilities(g, source), old)
        self.play(g, KILL, source); self.assertEqual(self.count(g, COIN), 1)
        self.portable(g)

    def test_real_draw_link_keeps_original_physical_draw_after_donor_silence(self):
        g = self.game((DRAWER, CARD, SILENCE, KILL)); donor = self.play(g, DRAWER)
        memory = deepcopy(self.abilities(g, donor)[0].deathrattle_memory)
        source = self.play(g, CARD); row = self.abilities(g, source)[0]
        self.assertEqual(row.deathrattle_memory, memory)
        target = memory.draws[0].entity_id; self.assertIn(target, g.state.players[1].hand)
        self.play(g, SILENCE, donor); self.portable(g); self.play(g, KILL, source)
        self.assertNotIn(target, g.state.players[1].hand)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.portable(g)

    def test_real_discard_link_recovers_original_material_with_discount(self):
        g = self.game((HOARDER, CARD, COIN, KILL))
        target = self.first(g, COIN, zone='hand'); donor = self.play(g, HOARDER, target)
        memory = deepcopy(self.abilities(g, donor)[0].deathrattle_memory)
        source = self.play(g, CARD); self.assertEqual(self.abilities(g, source)[0].deathrattle_memory, memory)
        self.play(g, KILL, source); self.assertEqual(self.count(g, COIN), 1)
        self.portable(g)

    def test_native_growth_is_frozen_without_copying_donors_growth_trigger(self):
        g = self.game((CARD, GROW, KILL), (EGG,)); donor = self.first(g, EGG)
        source = self.play(g, CARD); original = deepcopy(self.abilities(g, source)[0].deathrattle_memory)
        self.play(g, GROW, donor)
        self.assertEqual(self.abilities(g, donor)[0].deathrattle_memory.growth_steps, original.growth_steps+1)
        self.assertEqual(self.abilities(g, source)[0].deathrattle_memory, original)
        self.portable(g); self.play(g, KILL, source)
        self.assertTrue(any(g.state.entities[i].card_id == original.spec.card_id for i in g.state.players[1].board))

    def test_real_roost_egg_preserves_complete_remembered_dragon_copy(self):
        g = self.game((ROOST, CARD, KILL), (DRAGON,)); dragon = self.first(g, DRAGON)
        location = self.play(g, ROOST); g.apply(UseLocation(1, location, target_id=dragon))
        source = self.play(g, CARD)
        rows = self.abilities(g, source)
        self.assertEqual(len(rows), 1); self.assertIsNotNone(rows[0].deathrattle_memory.summon_copy)
        self.portable(g); self.play(g, KILL, source)
        self.assertEqual(self.count(g, DRAGON, zone='board'), 2)
        self.portable(g)

    def test_current_copy_keeps_complete_grants_while_base_copy_does_not(self):
        g, source = self.seeded((CURRENT, BASE), board=(LEFT,))
        self.play(g, CURRENT, source); self.play(g, BASE, source)
        bodies = [i for i in g.state.players[1].board if g.state.entities[i].card_id == CARD]
        self.assertEqual([len(self.abilities(g, i)) for i in bodies], [1, 1, 0])
        self.portable(g)

    def test_return_resets_grants_and_silence_removes_existing_grants(self):
        g, source = self.seeded((RETURN, SILENCE), board=(LEFT,))
        self.play(g, RETURN, source); self.assertFalse(self.abilities(g, source))
        self.play(g, CARD); self.assertEqual(len(self.abilities(g, source)), 1)
        self.play(g, SILENCE, source); self.assertFalse(self.abilities(g, source))

    def test_control_change_executes_ordinary_deathrattle_for_new_controller(self):
        g, source = self.seeded((CONTROL,), board=(LEFT,))
        self.play(g, CONTROL, source); self.play(g, KILL, source)
        self.assertEqual((self.count(g, COIN, 1), self.count(g, COIN, 2)), (0, 1))
        self.portable(g)

    def test_dead_copied_grant_can_be_inherited_by_real_thorns(self):
        g, source = self.seeded((THORNS, KILL), board=(LEFT,))
        self.play(g, KILL, source); thorns = self.play(g, THORNS)
        rows = self.abilities(g, thorns); self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0].deathrattle_inherited_from)
        self.assertIsNone(rows[0].deathrattle_copied_from)
        self.portable(g); self.play(g, KILL, thorns)
        self.assertEqual(self.count(g, COIN), 2)

    def test_wait_after_grants_json_clone_replay_late_failure_and_once_only_continuation(self):
        g, source = self.seeded(board=(LEFT, RIGHT, WATCH)); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(self.abilities(g, source)), 2)
        other = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(other, 'fail')
        self.assertEqual(other.snapshot(), saved)
        for game in (g, other): self.choose(game, 'ok')
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(len(self.abilities(g, source)), 2)

    def test_failed_grant_reaction_rolls_back_whole_play_and_allocators(self):
        g = self.game((CARD,), (LEFT, RIGHT, FAULT)); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, CARD, position=1)
        self.assertEqual(g.snapshot(), saved)

    def test_queued_public_request_restores_and_stale_recipient_is_not_retargeted(self):
        g, source = self.seeded((QUEUE,), board=(LEFT,)); self.play(g, QUEUE, source)
        self.assertIn('GainAdjacentDeathrattles', json.dumps(g.snapshot()['resolution_frame']))
        other = self.portable(g)
        for game in (g, other): self.choose(game, 'leave')
        self.assertEqual(other.snapshot(), g.snapshot())
        self.assertEqual(g.state.entities[source].zone, Zone.HAND)
        self.assertFalse(self.abilities(g, source))

    def test_rehashed_payload_or_physical_provenance_forgery_is_rejected(self):
        g, source = self.seeded(board=(LEFT,)); saved = g.snapshot()
        changes = [lambda a: a.update(behavior_id=P+'armor'),
            lambda a: a['deathrattle_copied_from']['original'].update(id=a['id']),
            lambda a: a['deathrattle_copied_from']['origin'].update(owner=2),
            lambda a: a['deathrattle_copied_from'].update(next_attachment_id=a['id']+1)]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                bad = deepcopy(saved); row = next(a for a in bad['state']['entities'][str(source)]['abilities'] if a['kind'] == 'deathrattle')
                change(row); bad['state_hash'] = canonical_hash({k:v for k,v in bad.items()
                    if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
                with self.assertRaises(SnapshotError) as caught: Game.from_snapshot(bad, fixture('reader'))
                self.assertNotIn('digest mismatch', str(caught.exception))
