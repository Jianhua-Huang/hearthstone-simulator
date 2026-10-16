"""Real Dream spells share ordinary stats, start events and damage execution."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.complex_dream_cards import AWAKENS, NIGHTMARE, PREFIX, YSERA_IDS, load_batch
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (CardClass, CardDefinition, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import TargetSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import BuffCapturedMinionWithStartTrigger, MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.turn_scheduling import QueueTurns, SkipTurns
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P = 'k102b.'
YETI = 'CORE_CS2_182'
MINION = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))


def registry():
    r = build_registry()
    def grant(c):
        return BuffCapturedMinionWithStartTrigger(MinionReference.capture(c.state.entities[c.target_id]),
            5, 5, PREFIX + 'due.' + str(c.player_id), c.source_id, PREFIX+'actor.'+str(c.player_id))
    def wait(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Install complete grant', (grant(c),)),
            ChoiceOption('fail', 'Fail after installation', (grant(c), InvokeBehavior(P+'fail', c.source_id, c.player_id))),
            ChoiceOption('cycle', 'Retire original residence', (ReturnToHand(c.target_id),
                InvokeBehavior(P+'reenter', c.source_id, c.player_id, c.target_id), grant(c))),
            ChoiceOption('transform', 'Replace original face', (Transform(c.target_id, YETI), grant(c))),
            ChoiceOption('control', 'Change original controller', (ChangeControl(c.target_id, 3-c.player_id), grant(c))),
        ), c.source_id),)
    def stats(c, mode):
        if dict(c.event.data).get('attack_delta') != 5: return ()
        e = c.state.entities[c.event.target_id]
        if not any(a.kind == 'limited_trigger' and a.limited_trigger.behavior_id.startswith(PREFIX+'due.') for a in e.abilities):
            raise ResolutionError('Stat reaction observed half of the Nightmare grant')
        if mode == 'copy': return (CopyMinion(e.id, c.player_id),)
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue', ()),), c.source_id),)
    scripts = {
        'silence': lambda c: (Silence(c.target_id),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'transform': lambda c: (Transform(c.target_id, YETI),),
        'give': lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        'copy': lambda c: (CopyMinion(c.target_id, c.player_id),),
        'base': lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        'wait': wait,
        'late_fail': lambda c: (grant(c), InvokeBehavior(P+'fail', c.source_id, c.player_id)),
        'extra': lambda c: (QueueTurns((c.player_id,), c.source_id),),
        'skip': lambda c: (SkipTurns(c.player_id, 1, c.source_id),),
    }
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('Deliberate Dream rollback')))
    r.register_behavior(P+'reenter', lambda c: (
        SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id),))
    for name, body in scripts.items():
        r.register_behavior(P+name, body)
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name,
            targeting=None if name in ('extra', 'skip') else MINION))
    for name in ('copy', 'wait'):
        key = P+'watch_'+name
        r.register_behavior(key, lambda c, mode=name: stats(c, mode))
        r.register_card(CardDefinition(key, key, CardType.MINION, health=10,
            triggers=(TriggerSpec('stats_changed', key),)))
    r.register_behavior(P+'watch_used', lambda c: (
        RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue consumed original start', ()),), c.source_id),))
    r.register_card(CardDefinition(P+'watch_used', 'Consumed start witness', CardType.MINION, health=10,
        triggers=(TriggerSpec('limited_trigger_used', P+'watch_used'),)))
    r.register_card(CardDefinition(P+'power', 'Spell Damage fixture', CardType.MINION, health=12, spell_damage=2))
    r.register_card(CardDefinition(P+'shield', 'Shield fixture', CardType.MINION, health=12,
        keywords=(Keyword.DIVINE_SHIELD,)))
    r.register_card(CardDefinition(P+'named', '伊瑟拉', CardType.MINION, health=12))
    # Isolated identity fixtures test the compiled exclusion, without registering
    # incomplete real Ysera cards in the constructed content catalogue.
    for cid in sorted(YSERA_IDS):
        if cid not in r.cards: r.register_card(CardDefinition(cid, 'Ysera identity fixture', CardType.MINION, health=12))
    r.validate()
    return r


class ComplexDreamCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.r = registry()
    def game(self, hand=(NIGHTMARE,), board=(YETI,), enemy=(), enemy_hand=(), active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(YETI,)*8, mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(YETI,)*8, mana=40, max_mana=40, mana_cap=40),
        ), seed=102, active_player=active), self.r)
    def find(self, g, cid=YETI, p=1, zone='board'):
        return next(i for i in getattr(g.state.players[p], zone) if g.state.entities[i].card_id == cid)
    def play(self, g, cid=NIGHTMARE, target=None):
        p = g.state.active_player; i = self.find(g, cid, p, 'hand')
        g.apply(PlayCard(p, i, target)); return i
    def due(self, g, i):
        return [a for a in g.state.entities[i].abilities if a.kind == 'limited_trigger' and a.limited_trigger.behavior_id.startswith(PREFIX+'due.')]
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def next_caster(self, g):
        p = g.state.active_player; g.apply(EndTurn(p)); g.apply(EndTurn(3-p))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry())
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe()) + json.dumps(g.for_player(p).legal_actions())
            for private in ('MinionReference', 'resolution_frame', 'rng_state', 'zone_epoch'):
                self.assertNotIn(private, public)
        return other
    def nodes(self, value):
        if isinstance(value, dict):
            if value.get('type', '').endswith('.BuffCapturedMinionWithStartTrigger'): yield value['fields']
            for child in value.values(): yield from self.nodes(child)
        elif isinstance(value, list):
            for child in value: yield from self.nodes(child)
    def reject(self, saved):
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as error: Game.from_snapshot(saved, self.r)
        self.assertNotIn('digest mismatch', str(error.exception))

    def test_full_raw_metadata_and_cost_presence(self):
        data = load_batch()
        for row in data['dependencies']:
            raw = row['record']; card = self.r.card(raw['id'])
            self.assertEqual(canonical_digest(raw), row['record_sha256'])
            self.assertEqual(card.metadata, replace(metadata_from_record(raw), deck_identity=raw['id']))
            self.assertEqual(card.metadata.classes, (CardClass.DREAM,))
        raw = next(x['record'] for x in data['dependencies'] if x['record']['id'] == NIGHTMARE)
        self.assertIsNone(raw['cost']); self.assertNotIn('COST', raw['tags']); self.assertEqual(self.r.card(NIGHTMARE).cost, 0)
        self.assertEqual(self.r.card(AWAKENS).cost, 2)
        self.assertEqual(self.r.card(AWAKENS).spell_school, SpellSchool.NATURE)
        self.assertEqual(self.r.card(NIGHTMARE).spell_school, SpellSchool.SHADOW)

    def test_exclusion_uses_complete_pinned_identity_family(self):
        rows = load_batch()['ysera_exclusion_source']
        self.assertEqual({x['record']['id'] for x in rows}, YSERA_IDS)
        self.assertTrue(all(x['record']['tags'].get('4392') == 1 for x in rows))

    def test_nightmare_immediate_stats_and_original_source(self):
        g = self.game(); i = self.find(g); source = self.play(g, target=i)
        self.assertEqual((g.state.entities[i].attack, g.state.entities[i].max_health), (9, 10))
        self.assertEqual(len(self.due(g, i)), 1); self.assertEqual(self.due(g, i)[0].source_id, source)
        self.assertEqual(len(g.state.entities[i].enchantments), 1)

    def test_other_start_survives_original_caster_next_start_destroys(self):
        g = self.game(); i = self.find(g); source = self.play(g, target=i)
        g.apply(EndTurn(1)); self.assertEqual(g.state.entities[i].zone, Zone.BOARD)
        g.apply(EndTurn(2)); self.assertEqual(g.state.entities[i].zone, Zone.GRAVEYARD)
        self.assertEqual(next(d for d in g.state.death_history if d.entity_id == i).cause.source_id, source)

    def test_original_caster_two_targets_enemy(self):
        g = self.game(hand=(), enemy_hand=(NIGHTMARE,), active=2); i = self.find(g)
        self.play(g, target=i); self.assertEqual(self.due(g, i)[0].limited_trigger.behavior_id, PREFIX+'due.2')
        self.next_caster(g); self.assertEqual(g.state.entities[i].zone, Zone.GRAVEYARD)

    def test_control_change_preserves_original_caster_clock(self):
        g = self.game(hand=(NIGHTMARE, P+'give')); i = self.find(g)
        self.play(g, target=i); self.play(g, P+'give', i)
        self.assertEqual(g.state.entities[i].controller, 2)
        g.apply(EndTurn(1)); self.assertEqual(g.state.entities[i].zone, Zone.BOARD)
        g.apply(EndTurn(2)); self.assertEqual(g.state.entities[i].zone, Zone.GRAVEYARD)

    def test_extra_turn_is_actual_next_start(self):
        g = self.game(hand=(NIGHTMARE, P+'extra')); i = self.find(g)
        self.play(g, target=i); self.play(g, P+'extra'); g.apply(EndTurn(1))
        self.assertEqual(g.state.active_player, 1); self.assertEqual(g.state.entities[i].zone, Zone.GRAVEYARD)

    def test_skipped_slot_has_no_start_and_does_not_destroy(self):
        g = self.game(hand=(NIGHTMARE, P+'skip')); i = self.find(g)
        self.play(g, target=i); self.play(g, P+'skip'); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(g.state.active_player, 2); self.assertEqual(g.state.entities[i].zone, Zone.BOARD)
        g.apply(EndTurn(2)); self.assertEqual(g.state.entities[i].zone, Zone.GRAVEYARD)

    def test_silence_resets_both_ordinary_attachments(self):
        g = self.game(hand=(NIGHTMARE, P+'silence')); i = self.find(g)
        self.play(g, target=i); self.play(g, P+'silence', i)
        self.assertFalse(self.due(g, i)); self.assertEqual(g.state.entities[i].attack, 4)
        self.next_caster(g); self.assertEqual(g.state.entities[i].zone, Zone.BOARD)

    def test_return_and_reentry_do_not_keep_old_start_grant(self):
        g = self.game(hand=(NIGHTMARE, P+'bounce')); i = self.find(g)
        self.play(g, target=i); self.play(g, P+'bounce', i)
        g.apply(PlayCard(1, i, position=0)); self.assertFalse(self.due(g, i))
        self.next_caster(g); self.assertEqual(g.state.entities[i].zone, Zone.BOARD)

    def test_transform_resets_both_ordinary_attachments(self):
        g = self.game(hand=(NIGHTMARE, P+'transform')); i = self.find(g)
        self.play(g, target=i); self.play(g, P+'transform', i)
        self.assertFalse(self.due(g, i)); self.assertEqual(g.state.entities[i].attack, 4)
        self.next_caster(g); self.assertEqual(g.state.entities[i].zone, Zone.BOARD)

    def test_current_copy_keeps_complete_grant_base_copy_does_not(self):
        g = self.game(hand=(NIGHTMARE, P+'copy', P+'base')); i = self.find(g)
        self.play(g, target=i); self.play(g, P+'copy', i); current = g.state.players[1].board[-1]
        self.play(g, P+'base', i); base = g.state.players[1].board[-1]
        self.assertEqual(g.state.entities[current].attack, 9); self.assertEqual(len(self.due(g, current)), 1)
        self.assertEqual(g.state.entities[base].attack, 4); self.assertFalse(self.due(g, base))
        self.next_caster(g)
        self.assertEqual(g.state.entities[current].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[base].zone, Zone.BOARD)

    def test_stat_reaction_copies_already_complete_grant(self):
        g = self.game(board=(YETI, P+'watch_copy')); i = self.find(g)
        self.play(g, target=i); copy = g.state.players[1].board[-1]
        self.assertNotEqual(copy, i); self.assertEqual(g.state.entities[copy].attack, 9)
        self.assertEqual(len(self.due(g, copy)), 1)
        self.next_caster(g); self.assertEqual(g.state.entities[copy].zone, Zone.GRAVEYARD)

    def test_stat_reaction_wait_snapshot_clone_replay_and_finish(self):
        g = self.game(board=(YETI, P+'watch_wait')); i = self.find(g)
        self.play(g, target=i); self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g); self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot()); self.next_caster(g)
        self.assertEqual(g.state.entities[i].zone, Zone.GRAVEYARD); self.portable(g)

    def test_queued_atomic_request_wait_snapshot_replay(self):
        g = self.game(hand=(P+'wait',)); i = self.find(g); self.play(g, P+'wait', i)
        self.assertTrue(list(self.nodes(g.snapshot())))
        other = self.portable(g); self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(len(self.due(g, i)), 1)

    def test_late_failure_rolls_back_both_attachments(self):
        g = self.game(hand=(P+'late_fail',)); i = self.find(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, P+'late_fail', i)
        self.assertEqual(g.snapshot(), before)

    def test_choice_failure_preserves_wait_then_retry(self):
        g = self.game(hand=(P+'wait',)); i = self.find(g); self.play(g, P+'wait', i); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before); self.choose(g); self.assertEqual(len(self.due(g, i)), 1)

    def test_two_real_grants_create_one_actual_death(self):
        g = self.game(hand=(NIGHTMARE, NIGHTMARE)); i = self.find(g)
        self.play(g, target=i); self.play(g, target=i)
        self.assertEqual(g.state.entities[i].attack, 14); self.assertEqual(len(self.due(g, i)), 2)
        self.next_caster(g); self.assertEqual([d.entity_id for d in g.state.death_history], [i])

    def test_consumed_original_start_wait_restores_exact_source(self):
        g = self.game(board=(YETI, P+'watch_used')); i = self.find(g); source = self.play(g, target=i)
        self.next_caster(g); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[i].zone, Zone.BOARD)
        self.assertTrue(self.due(g, i)[0].consumed)
        other = self.portable(g); self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(next(d for d in g.state.death_history if d.entity_id == i).cause.source_id, source)

    def test_targeting_rejects_hero(self):
        g = self.game(); i = g.state.players[2].hero_id
        with self.assertRaises(IllegalAction): self.play(g, target=i)

    def test_original_recipient_stales_after_reentry_face_or_controller_change(self):
        for key in ('cycle', 'transform', 'control'):
            with self.subTest(key=key):
                g = self.game(hand=(P+'wait',)); i = self.find(g); self.play(g, P+'wait', i)
                self.choose(g, key); self.assertFalse(self.due(g, i))
                self.assertEqual(g.state.entities[i].attack, 4)

    def test_awakens_hits_both_heroes_and_minions_in_one_batch(self):
        g = self.game(hand=(AWAKENS,), enemy=(YETI,)); self.play(g, AWAKENS)
        self.assertEqual([g.state.entities[g.state.players[p].hero_id].health for p in (1, 2)], [25, 25])
        self.assertFalse(g.state.players[1].board); self.assertFalse(g.state.players[2].board)

    def test_awakens_uses_shared_spell_damage_and_divine_shield(self):
        g = self.game(hand=(AWAKENS,), board=(P+'power',), enemy=(P+'shield', P+'named'))
        shield = self.find(g, P+'shield', 2); named = self.find(g, P+'named', 2); self.play(g, AWAKENS)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 23)
        self.assertEqual(g.state.entities[shield].health, 12)
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[shield].keywords)
        self.assertEqual(g.state.entities[named].health, 5)

    def test_awakens_exempts_exact_current_ysera_identities(self):
        for cid in sorted(YSERA_IDS):
            with self.subTest(cid=cid):
                g = self.game(hand=(AWAKENS,), board=(cid,)); i = self.find(g, cid)
                before = g.state.entities[i].health; self.play(g, AWAKENS)
                self.assertEqual(g.state.entities[i].health, before)

    def test_awakens_after_identity_transform_uses_new_face(self):
        cid = sorted(YSERA_IDS)[0]
        g = self.game(hand=(P+'transform', AWAKENS), board=(cid,)); i = self.find(g, cid)
        self.play(g, P+'transform', i); self.play(g, AWAKENS)
        self.assertEqual(g.state.entities[i].zone, Zone.GRAVEYARD)

    def test_awakens_snapshot_and_independent_replay(self):
        g = self.game(hand=(AWAKENS,), board=(P+'named',)); self.play(g, AWAKENS); self.portable(g)

    def test_strict_atomic_request_types(self):
        g = self.game(); ref = MinionReference.capture(g.state.entities[self.find(g)])
        effect = BuffCapturedMinionWithStartTrigger(ref, 5, 5, PREFIX+'due.1', g.state.players[1].hero_id, PREFIX+'actor.1')
        for changes in ({'beneficiary': 1}, {'attack': True}, {'health': -1}, {'source_id': None}, {'behavior_id': ''}, {'condition_id': ''}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(effect, **changes)

    def test_frame_rejects_future_allocations_unknown_sources_and_behavior(self):
        g = self.game(); ref = MinionReference.capture(g.state.entities[self.find(g)])
        effect = BuffCapturedMinionWithStartTrigger(ref, 5, 5, PREFIX+'due.1', g.state.players[1].hero_id, PREFIX+'actor.1')
        codec = FrameCodec(g.mechanics, self.r, origin_state=g.state)
        for invalid in (replace(effect, beneficiary=replace(ref, zone_epoch=ref.zone_epoch+1)),
                replace(effect, beneficiary=replace(ref, entered_order=g.state.next_order)),
                replace(effect, source_id=999999), replace(effect, behavior_id='unknown.dream'),
                replace(effect, condition_id='unknown.dream')):
            with self.subTest(effect=invalid), self.assertRaises((ValueError, ResolutionError, KeyError)):
                codec.encode(invalid)

    def test_rehashed_wait_rejects_unknown_behavior(self):
        g = self.game(hand=(P+'wait',)); self.play(g, P+'wait', self.find(g)); saved = deepcopy(g.snapshot())
        for node in self.nodes(saved): node['behavior_id'] = 'unknown.dream'
        self.reject(saved)

    def test_rehashed_wait_rejects_unknown_source(self):
        g = self.game(hand=(P+'wait',)); self.play(g, P+'wait', self.find(g)); saved = deepcopy(g.snapshot())
        for node in self.nodes(saved): node['source_id'] = 999999
        self.reject(saved)


if __name__ == '__main__': unittest.main()
