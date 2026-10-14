"""Physical cast facts feeding ordinary held progress; one real Diamond family."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CastWhenDrawnSpec, CostSpec,
    EndTurn, Game, HandProgressSpec, Keyword, PlayCard, PlayerSetup, Rarity, ResolutionError,
    Resource, RewindSpec, Scenario, SelectChoice, SnapshotError, SpellRepeatSpec, SpellSchool,
    TargetSpec, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, Draw, GainArmor,
    ModifyCost, RequestChoice, SpendResource)
from hs_sim.engine.hand_progress import AdvanceHandProgress, identity, progress_ability
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import Resolution
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell, CastStoredSpell, accepted_cast
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.summon_sources import Resurrect
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry

BASE, MID, MAXIMUM = 'LOOT_507', 'LOOT_507t', 'LOOT_507t2'
PIN = '75aade1b3732382c3157a9be841592a3c0a88e4defd1d4ba92779453775a16be'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/spell-cast-progress.json'


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN: raise ValueError('Complete Diamond evidence changed')
    for row in raw['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original Diamond record changed')
    return {row['id']: row['data'] for row in raw['records']}


def registry(scripts=(), *, bad_condition=False, choice_progress=False, origin_filter=None):
    r = opening_registry(); rows = evidence()
    def eligible(c):
        if bad_condition: return 'invalid'
        return c.cast.player_id == c.player_id and (origin_filter is None or c.cast.origin == origin_filter)
    r.register_trigger_condition('diamond.cast', eligible)
    for cid, number, following in ((MAXIMUM, 4, None), (MID, 3, MAXIMUM), (BASE, 2, MID)):
        r.register_behavior('diamond.' + cid, lambda c, n=number:
            (Resurrect(c.player_id, n, distinct='card', source_id=c.source_id),))
        spec = HandProgressSpec('event', 4, following, event='spell_cast_accepted',
            condition_id='diamond.cast', upgrade_cost_policy='clear_local') if following else None
        r.register_card(CardDefinition(cid, rows[cid]['name'], CardType.SPELL, cost=7,
            spell_school=SpellSchool.HOLY, hand_progress=spec, on_play='diamond.' + cid,
            metadata=metadata(CardClass.PRIEST, rarity=Rarity.RARE, collectible=cid == BASE)))
    r.register_behavior('probe.noop', lambda c: ())
    r.register_card(CardDefinition('probe.noop', 'Empty accepted spell probe', CardType.SPELL,
        on_play='probe.noop', metadata=metadata()))
    r.register_card(CardDefinition('probe.drawn', 'Drawn accepted spell probe', CardType.SPELL,
        on_play='probe.noop', cast_when_drawn=CastWhenDrawnSpec(replacement=False),
        keywords=(Keyword.CASTS_WHEN_DRAWN,), metadata=metadata()))
    r.register_card(CardDefinition('probe.targeted', 'Required target probe', CardType.SPELL,
        on_play='probe.noop', targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)), metadata=metadata()))
    r.register_card(CardDefinition('probe.repeat', 'Physical repeat probe', CardType.MINION, health=3,
        spell_repeats=(SpellRepeatSpec(3, class_mode='any'),), metadata=metadata()))
    r.register_card(CardDefinition('probe.retainer', 'Existing outcome retention probe', CardType.MINION,
        health=3, retain_rewind_outcomes=True, metadata=metadata()))
    r.register_behavior('probe.counter', lambda c: (CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id != c.player_id else ())
    r.register_card(CardDefinition('probe.counter', 'Pending hand spell counter probe', CardType.MINION,
        health=3, triggers=(TriggerSpec('card_committed', 'probe.counter'),), metadata=metadata()))
    if choice_progress:
        r.register_behavior('probe.progress.wait', lambda c: (RequestChoice(c.player_id,
            (ChoiceOption('ok', 'Continue', ()),), c.source_id),))
        r.register_card(CardDefinition('probe.progress', 'Ordinary progress wait probe', CardType.SPELL,
            on_play='probe.noop', hand_progress=HandProgressSpec('event', 20,
                on_progress='probe.progress.wait', on_complete='probe.noop',
                event='spell_cast_accepted', condition_id='diamond.cast'), metadata=metadata()))
    for name, callback, extra in scripts:
        r.register_behavior(name, callback)
        values = dict(extra); kind = values.pop('kind', CardType.SPELL)
        if kind == CardType.MINION:
            values.setdefault('health', 1); values.setdefault('battlecry', name)
        else: values.setdefault('on_play', name)
        r.register_card(CardDefinition(name, name, kind, metadata=metadata(), **values))
    return r


class SpellCastProgressTests(unittest.TestCase):
    def setUp(self): self.scripts = []; self.options = {}
    def script(self, name, callback, **extra): self.scripts.append((name, callback, extra))
    def driver(self, name, callback): self.script(name, callback, kind=CardType.MINION)
    def game(self, hand=(BASE,), deck=(), enemy_hand=(), board=(), enemy_board=(), power=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, deck=deck, board=board, max_mana=10, mana=10,
                hero_power_card_id=power),
            PlayerSetup('warrior.hero', hand=enemy_hand, deck=('card.1',)*12, board=enemy_board,
                max_mana=10, mana=10)), seed=51), registry(self.scripts, **self.options))
    def entity(self, g, card=None, player=1, zone=Zone.HAND):
        return next(g.state.entities[i] for i in getattr(g.state.players[player], zone.value)
            if g.state.entities[i].card_id == card or card is None and g.state.entities[i].card_id in (BASE, MID, MAXIMUM))
    def progress(self, g, card=None, player=1): return progress_ability(self.entity(g, card, player))
    def play(self, g, card, target=None):
        eid = self.entity(g, card, g.state.active_player).id
        g.apply(PlayCard(g.state.active_player, eid, target)); return eid
    def choose(self, g):
        p = g.state.pending_choice; g.apply(SelectChoice(p.player_id, p.id, ('ok',)))
    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(snap, registry(self.scripts, **self.options))
        self.assertEqual(restored.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, **self.options)).snapshot(), snap)
        return restored
    def facts(self, g): return tuple(e for e in g.events if e.kind == 'spell_cast_accepted')
    def ref(self, c, card=BASE, zone=Zone.HAND):
        return CardReference.capture(next(c.state.entities[i] for i in getattr(c.state.players[1], zone.value)
            if c.state.entities[i].card_id == card))
    def reject(self, g, mutate):
        snap = g.snapshot(); mutate(snap)
        snap['events_hash'] = canonical_hash(snap['events'])
        snap['state_hash'] = canonical_hash({k:v for k,v in snap.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as caught:
            Game.from_snapshot(snap, registry(self.scripts, **self.options))
        self.assertNotIn('digest mismatch', str(caught.exception))
    def marked(self):
        g = self.game(hand=(BASE, 'probe.noop')); self.play(g, 'probe.noop'); return g

    def test_complete_raw_and_reused_stage_declarations(self):
        rows = evidence(); r = registry()
        self.assertEqual(set(rows), {BASE, MID, MAXIMUM})
        for cid in rows: self.assertEqual((r.card(cid).name, r.card(cid).cost), (rows[cid]['name'], 7))
        self.assertEqual((r.card(BASE).hand_progress.goal, r.card(MID).hand_progress.goal), (4, 4))
        self.assertIsNone(r.card(MAXIMUM).hand_progress)

    def test_eight_hand_casts_advance_two_stages(self):
        g = self.game(hand=(BASE,)+('probe.noop',)*8)
        for _ in range(4): self.play(g, 'probe.noop')
        self.assertEqual((self.entity(g).card_id, self.progress(g).progress_value), (MID, 0))
        for _ in range(4): self.play(g, 'probe.noop')
        a = self.progress(g)
        self.assertEqual((self.entity(g).card_id, a.progress_value, a.progress_completions), (MAXIMUM, 4, 2))
        self.assertEqual(a.progress_keys, tuple(f'cast:{i}' for i in range(1, 9))); self.portable(g)

    def test_one_fact_per_physical_cast(self):
        g = self.marked(); event, = self.facts(g)
        self.assertEqual(accepted_cast(g.state, event), g.state.cast_history[0])
        self.assertEqual((event.player_id, event.amount, dict(event.data)), (1, 1, {'cast_id': 1})); self.portable(g)

    def test_existing_physical_repeat_counts_each_cast_once(self):
        g = self.game(hand=(BASE, 'probe.noop'), board=('probe.repeat',)); self.play(g, 'probe.noop')
        self.assertEqual(self.progress(g).progress_value, 3)
        self.assertEqual([c.origin for c in g.state.cast_history], ['hand', 'repeat', 'repeat'])
        self.assertEqual((len(g.state.play_history), len(self.facts(g))), (1, 3)); self.portable(g)

    def test_generated_effect_casts_use_same_counter(self):
        self.driver('probe.auto', lambda c: (CastSpell(1, 'probe.noop', c.source_id),)*4)
        g = self.game(hand=(BASE, 'probe.auto')); self.play(g, 'probe.auto')
        self.assertEqual((self.entity(g).card_id, self.progress(g).progress_value), (MID, 0))
        self.assertEqual([c.origin for c in g.state.cast_history], ['effect']*4); self.portable(g)

    def test_stored_cast_uses_its_real_physical_identity(self):
        self.driver('probe.stored', lambda c: (CastStoredSpell(self.ref(c, 'probe.noop'), 1, c.source_id),))
        g = self.game(hand=(BASE, 'probe.noop', 'probe.stored')); eid = self.entity(g, 'probe.noop').id
        self.play(g, 'probe.stored'); self.assertEqual(g.state.cast_history[0].source_id, eid)
        self.assertEqual(self.progress(g).progress_keys, ('cast:1',)); self.portable(g)

    def test_drawn_casts_use_same_counter(self):
        self.driver('probe.draw', lambda c: (Draw(1, 4, c.source_id),))
        g = self.game(hand=(BASE, 'probe.draw'), deck=('probe.drawn',)*4); self.play(g, 'probe.draw')
        self.assertEqual(self.entity(g).card_id, MID)
        self.assertEqual([c.origin for c in g.state.cast_history], ['draw']*4); self.portable(g)

    def test_historical_cast_has_a_new_witness(self):
        self.driver('probe.history', lambda c: (RecastSpell(1, 1, c.source_id),))
        g = self.game(hand=(BASE, 'probe.noop', 'probe.history')); self.play(g, 'probe.noop'); self.play(g, 'probe.history')
        self.assertEqual(self.progress(g).progress_keys, ('cast:1', 'cast:2'))
        self.assertEqual(g.state.cast_history[-1].origin, 'history'); self.portable(g)

    def test_opponent_cast_advances_only_opponents_hand(self):
        g = self.game(hand=(BASE,), enemy_hand=(BASE, 'probe.noop')); g.apply(EndTurn(1)); self.play(g, 'probe.noop')
        self.assertEqual((self.progress(g).progress_value, self.progress(g, player=2).progress_value), (0, 1)); self.portable(g)

    def test_nonspell_actions_do_not_count(self):
        g = self.game(hand=(BASE, 'card.1'), power='mage.power'); self.play(g, 'card.1')
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id)); g.apply(EndTurn(1))
        self.assertEqual(self.progress(g).progress_value, 0); self.assertEqual(self.facts(g), ()); self.portable(g)

    def test_countered_attempt_does_not_publish_acceptance(self):
        g = self.game(hand=(BASE, 'probe.noop'), enemy_board=('probe.counter',)); self.play(g, 'probe.noop')
        self.assertEqual(g.state.cast_history[0].failure, 'countered')
        self.assertEqual((self.progress(g).progress_value, self.facts(g)), (0, ())); self.portable(g)

    def test_failed_automatic_target_does_not_count(self):
        self.driver('probe.auto', lambda c: (CastSpell(1, 'probe.targeted', c.source_id, 99999, 'explicit'),))
        g = self.game(hand=(BASE, 'probe.auto')); self.play(g, 'probe.auto')
        self.assertEqual(g.state.cast_history[0].failure, 'invalid_target')
        self.assertEqual((self.progress(g).progress_value, self.facts(g)), (0, ())); self.portable(g)

    def test_new_hand_card_during_body_does_not_retroactively_count(self):
        self.script('probe.acquire', lambda c: (AddToHand(1, BASE),))
        g = self.game(hand=('probe.acquire',)); self.play(g, 'probe.acquire')
        self.assertEqual(self.progress(g).progress_value, 0); self.portable(g)

    def test_later_nested_cast_counts_for_new_hand_card(self):
        self.script('probe.acquire', lambda c: (AddToHand(1, BASE), CastSpell(1, 'probe.noop', c.source_id)))
        g = self.game(hand=('probe.acquire',)); self.play(g, 'probe.acquire')
        self.assertEqual(self.progress(g).progress_keys, ('cast:2',)); self.portable(g)

    def test_acceptance_and_upgrade_precede_spell_effect(self):
        self.script('probe.armor', lambda c: (GainArmor(1, 1),))
        g = self.game(hand=(BASE,)+('probe.noop',)*3+('probe.armor',))
        for _ in range(3): self.play(g, 'probe.noop')
        self.play(g, 'probe.armor'); kinds = [e.kind for e in g.events]
        self.assertLess(kinds.index('hand_card_upgraded'), kinds.index('armor_gained'))
        self.assertLess(self.facts(g)[-1].sequence, next(e.sequence for e in g.events if e.kind == 'hand_card_upgraded')); self.portable(g)

    def test_choice_before_automatic_acceptance_has_no_fact_yet(self):
        self.script('probe.watch', lambda c: (RequestChoice(1, (ChoiceOption('ok', 'Continue', ()),), c.source_id),),
            kind=CardType.MINION, triggers=(TriggerSpec('spell_cast_started', 'probe.watch'),))
        self.driver('probe.auto', lambda c: (CastSpell(1, 'probe.noop', c.source_id),))
        g = self.game(hand=(BASE, 'probe.auto'), board=('probe.watch',)); self.play(g, 'probe.auto')
        self.assertFalse(g.state.cast_history[0].payload_started); self.assertEqual(self.facts(g), ())
        self.assertEqual(self.progress(g).progress_value, 0); restored = self.portable(g)
        self.choose(g); self.choose(restored); self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(self.progress(g).progress_value, 1); self.portable(g)

    def test_progress_callback_wait_resumes_captured_real_fact_once(self):
        self.options['choice_progress'] = True
        g = self.game(hand=('probe.progress', BASE, 'probe.noop')); self.play(g, 'probe.noop')
        restored = self.portable(g); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(self.progress(g).progress_value, 1)
        self.assertEqual(len(self.facts(g)), 1); self.portable(g)

    def test_automatic_body_wait_does_not_double_count_after_restore(self):
        self.script('probe.wait', lambda c: (RequestChoice(1, (ChoiceOption('ok', 'Continue', ()),), c.source_id),))
        self.driver('probe.auto', lambda c: (CastSpell(1, 'probe.wait', c.source_id, choices='player'),))
        g = self.game(hand=(BASE, 'probe.auto')); self.play(g, 'probe.auto'); restored = self.portable(g)
        self.assertEqual(self.progress(g).progress_value, 1); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(self.progress(g).progress_value, 1); self.portable(g)

    def test_terminal_body_keeps_already_accepted_fact(self):
        self.script('probe.lethal', lambda c: (Damage(c.state.players[2].hero_id, 40, c.source_id),))
        g = self.game(hand=(BASE, 'probe.lethal')); self.play(g, 'probe.lethal')
        self.assertEqual((g.state.winner, self.progress(g).progress_value), (1, 1))
        self.assertTrue(g.state.cast_history[0].interrupted); self.portable(g)

    def test_late_error_rolls_back_cast_progress_payment_and_rng(self):
        self.script('probe.fail', lambda c: (AddToDeck(1, 'card.1'), SpendResource(1, Resource.CORPSES, 1, required=True)), cost=1)
        g = self.game(hand=(BASE, 'probe.fail')); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'probe.fail')
        self.assertEqual(g.snapshot(), before)

    def test_invalid_condition_rolls_back_physical_cast(self):
        self.options['bad_condition'] = True; g = self.game(hand=(BASE, 'probe.noop')); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'probe.noop')
        self.assertEqual(g.snapshot(), before)

    def test_actual_face_upgrade_clears_local_cost(self):
        self.driver('probe.discount', lambda c: (ModifyCost(self.ref(c).entity_id, CostSpec(delta=-3)),))
        g = self.game(hand=(BASE, 'probe.discount')+('probe.noop',)*4); self.play(g, 'probe.discount')
        for _ in range(3): self.play(g, 'probe.noop')
        self.assertEqual(self.entity(g).cost, 4); self.play(g, 'probe.noop')
        self.assertEqual((self.entity(g).card_id, self.entity(g).cost), (MID, 7)); self.portable(g)

    def test_current_copy_inherits_but_base_copy_starts_fresh(self):
        self.driver('probe.copy', lambda c: (CopyCard(self.ref(c), 1, Zone.HAND, mode='current'),
            CopyCard(self.ref(c), 1, Zone.HAND, mode='base')))
        g = self.game(hand=(BASE, 'probe.noop', 'probe.copy')); self.play(g, 'probe.noop'); self.play(g, 'probe.copy')
        cards = [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id == BASE]
        self.assertEqual([progress_ability(e).progress_value for e in cards], [1, 1, 0]); self.portable(g)

    def test_nonreset_deck_residence_pauses_existing_progress(self):
        self.driver('probe.out', lambda c: (MoveCard(self.ref(c), 1, Zone.DECK, reset=False),))
        self.driver('probe.back', lambda c: (MoveCard(self.ref(c, zone=Zone.DECK), 1, Zone.HAND, reset=False),))
        g = self.game(hand=(BASE, 'probe.noop', 'probe.out', 'probe.noop', 'probe.back'))
        self.play(g, 'probe.noop'); self.play(g, 'probe.out'); self.play(g, 'probe.noop'); self.play(g, 'probe.back')
        self.assertEqual(self.progress(g).progress_value, 1); self.portable(g)

    def test_two_physical_cards_advance_independently(self):
        g = self.game(hand=(BASE, BASE, 'probe.noop')); self.play(g, 'probe.noop')
        cards = [g.state.entities[i] for i in g.state.players[1].hand]
        self.assertEqual([progress_ability(e).progress_value for e in cards], [1, 1])
        self.assertNotEqual(progress_ability(cards[0]).id, progress_ability(cards[1]).id); self.portable(g)

    def test_internal_fact_and_witnesses_are_not_player_events(self):
        g = self.marked(); self.assertEqual(g.observe(1)['players'][0]['hand'][0]['hand_progress']['value'], 1)
        self.assertNotIn('hand_progress', g.observe(2)['players'][0]['hand'][0])
        for p in (1, 2):
            text = json.dumps(g.observe(p)) + json.dumps(g.player_events(p))
            for private in ('spell_cast_accepted', 'cast_id', 'progress_keys'): self.assertNotIn(private, text)

    def test_snapshot_cannot_drop_acceptance_fact(self):
        g = self.marked()
        self.reject(g, lambda s: s['events'].__setitem__(slice(None), [e for e in s['events'] if e['kind'] != 'spell_cast_accepted']))

    def test_snapshot_cannot_duplicate_acceptance_fact(self):
        g = self.marked()
        def mutate(s):
            event = deepcopy(next(e for e in s['events'] if e['kind'] == 'spell_cast_accepted'))
            event['sequence'] = len(s['events'])+1; s['events'].append(event)
        self.reject(g, mutate)

    def test_snapshot_cannot_change_cast_fact_fields(self):
        g = self.marked()
        for field, value in (('player_id', 2), ('source_id', None), ('target_id', 999), ('amount', 2)):
            with self.subTest(field=field):
                self.reject(g, lambda s, f=field, v=value: next(e for e in s['events'] if e['kind'] == 'spell_cast_accepted').update({f:v}))
        self.reject(g, lambda s: next(e for e in s['events'] if e['kind'] == 'spell_cast_accepted')['data'].update(cast_id=True))

    def test_snapshot_progress_requires_a_real_cast_witness(self):
        g = self.marked(); eid = str(self.entity(g).id)
        for key in ('event:1', 'cast:999'):
            with self.subTest(key=key):
                self.reject(g, lambda s, k=key: s['state']['entities'][eid]['abilities'][0].update(progress_keys=[k]))

    def test_waiting_queue_cannot_borrow_another_acceptance_event(self):
        self.options['choice_progress'] = True
        g = self.game(hand=('probe.progress', BASE, 'probe.noop')); self.play(g, 'probe.noop')
        def mutate(s):
            found = []
            def walk(v):
                if isinstance(v, dict):
                    if v.get('type', '').endswith('AdvanceHandProgress'): found.append(v)
                    for child in v.values(): walk(child)
                elif isinstance(v, list):
                    for child in v: walk(child)
            walk(s['resolution_frame'])
            self.assertTrue(found)
            def alter(v):
                if isinstance(v, dict):
                    if v.get('kind') == 'spell_cast_accepted': v['sequence'] = 1; return True
                    return any(alter(child) for child in v.values())
                if isinstance(v, list): return any(alter(child) for child in v)
                return False
            self.assertTrue(alter(found[0]))
        self.reject(g, mutate)

    def test_new_schema_rejects_old_future_and_bool(self):
        g = self.game(); self.assertEqual(g.snapshot()['schema_version'], 266)
        for version in (1, 160, 161, 162, 217, True):
            s = g.snapshot(); s['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(SnapshotError): Game.from_snapshot(s, registry())

    def test_real_three_bodies_resurrect_distinct_card_faces(self):
        self.script('probe.kill', lambda c: tuple(Destroy(i) for i in c.state.players[1].board))
        for cid, number in ((BASE, 2), (MID, 3), (MAXIMUM, 4)):
            with self.subTest(card=cid):
                g = self.game(hand=(cid, 'probe.kill'), board=('card.1', 'card.1', 'card.2', 'card.3', 'card.4'))
                self.play(g, 'probe.kill'); self.play(g, cid)
                faces = [g.state.entities[i].card_id for i in g.state.players[1].board]
                self.assertEqual((len(faces), len(set(faces))), (number, number)); self.portable(g)

    def test_condition_receives_actual_origin_and_can_filter(self):
        self.options['origin_filter'] = 'effect'
        self.driver('probe.auto', lambda c: (CastSpell(1, 'probe.noop', c.source_id),))
        g = self.game(hand=(BASE, 'probe.noop', 'probe.auto')); self.play(g, 'probe.noop'); self.play(g, 'probe.auto')
        self.assertEqual(self.progress(g).progress_keys, ('cast:2',)); self.portable(g)

    def test_reprocessing_same_fact_does_not_duplicate_progress(self):
        g = self.marked(); before = g.snapshot(); e = self.entity(g); a = progress_ability(e)
        Resolution(g).run((AdvanceHandProgress(identity(e, a), self.facts(g)[0]),))
        self.assertEqual(g.snapshot(), before)

    def test_existing_retained_outcomes_do_not_invent_extra_casts(self):
        self.script('probe.rewind', lambda c: (GainArmor(1, c.rewind_attempt+1),),
            rewind=RewindSpec(), keywords=(Keyword.REWIND,))
        g = self.game(hand=(BASE, 'probe.rewind'), board=('probe.retainer',)); self.play(g, 'probe.rewind')
        self.assertEqual((len(g.state.cast_history), len(self.facts(g)), self.progress(g).progress_value), (1, 1, 1))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 3); self.portable(g)

    def test_submission_reaction_acquisition_counts_at_later_acceptance(self):
        self.script('probe.acquire.watch', lambda c: (AddToHand(1, BASE),)
            if c.event.player_id == 1 else (), kind=CardType.MINION,
            triggers=(TriggerSpec('card_committed', 'probe.acquire.watch'),))
        g = self.game(hand=('probe.noop',), board=('probe.acquire.watch',)); self.play(g, 'probe.noop')
        self.assertEqual(self.progress(g).progress_keys, ('cast:1',)); self.portable(g)

    def test_extensions_cannot_emit_an_unbound_acceptance_fact(self):
        g = self.game(); before = g.snapshot()
        with self.assertRaises(ResolutionError): Resolution(g).emit('spell_cast_accepted', player_id=1, cast_id=1, amount=1)
        self.assertEqual(g.snapshot(), before)

    def test_fact_reader_rejects_boolean_units_and_extra_fields(self):
        g = self.marked(); fact, = self.facts(g)
        with self.assertRaises(ValueError): accepted_cast(g.state, replace(fact, amount=True))
        with self.assertRaises(ValueError): accepted_cast(g.state, replace(fact, data=(*fact.data, ('extra', 1))))

    def test_ordinary_retry_restores_progress_and_keeps_old_attempt_log(self):
        self.script('probe.retry', lambda c: (GainArmor(1, c.rewind_attempt+1),),
            rewind=RewindSpec(), keywords=(Keyword.REWIND,))
        g = self.game(hand=(BASE, 'probe.retry')); self.play(g, 'probe.retry'); restored = self.portable(g)
        for game in (g, restored):
            p = game.state.pending_choice; game.apply(SelectChoice(p.player_id, p.id, ('retry',)))
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual((len(g.state.cast_history), self.progress(g).progress_value), (1, 1))
        self.assertEqual(len(self.facts(g)), 2)
        self.assertEqual(accepted_cast(g.state, self.facts(g)[-1]), g.state.cast_history[0]); self.portable(g)
        self.reject(g, lambda s: next(e for e in s['events'] if e['kind'] == 'timeline_rewound').update(kind='probe.forged'))
