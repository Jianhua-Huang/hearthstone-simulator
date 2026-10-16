"""Original physical recruit followups across reactions, quantities and saved work."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game,
    Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, GainArmor, GrantKeyword,
    RequestChoice, ReturnToHand, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import SpellSchool, SummonQuantitySpec
from hs_sim.engine.recruit_summons import ContinueRecruitedMinion, followup_record
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonCause, validate_queue
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.zones import CardReference
from hs_sim.engine.serialization import canonical_hash


def registry(mode=None):
    r = build_registry(); neutral = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
    for cid, tribe in (('body', 'beast'), ('demon', 'demon'), ('other', 'dragon')):
        r.register_card(CardDefinition('k08.'+cid, cid, CardType.MINION, cost=2, attack=2, health=4,
            metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(tribe,))))
    r.register_behavior('k08.cry', lambda c: (GainArmor(c.state.players[c.player_id].hero_id, 99),))
    r.register_card(CardDefinition('k08.cry', 'Cry', CardType.MINION, cost=2, attack=2, health=4,
        battlecry='k08.cry', metadata=neutral))
    r.register_card(CardDefinition('k08.double', 'Quantity diagnostic', CardType.MINION, health=6,
        summon_quantities=(SummonQuantitySpec(),), metadata=neutral))
    r.register_card(CardDefinition('k08.spellpower', 'Spell power', CardType.MINION, health=5,
        spell_damage=1, metadata=neutral))
    r.register_behavior('k08.grant', lambda c: (GrantKeyword(c.target_id, Keyword.RUSH, c.source_id),))
    r.register_behavior('k08.waitgrant', lambda c: (RequestChoice(c.player_id,
        (ChoiceOption('keep', 'Grant', (GrantKeyword(c.target_id, Keyword.RUSH, c.source_id),)),), c.source_id),))
    r.register_behavior('k08.failgrant', lambda c: (AddToHand(c.player_id, 'missing.k08.followup'),))
    scripts = {
        'recruit': lambda c: (SummonFromZone(c.player_id, 2, source_id=c.source_id,
            cause=SummonCause.capture(c), on_summon='k08.grant'),),
        'direct': lambda c: (SummonStoredCard(CardReference.capture(c.state.entities[c.state.players[1].deck[0]]),
            c.player_id, cause=SummonCause.capture(c), on_summon='k08.grant'),),
        'wait': lambda c: (SummonFromZone(c.player_id, source_id=c.source_id,
            cause=SummonCause.capture(c), on_summon='k08.waitgrant'),),
        'fault': lambda c: (SummonFromZone(c.player_id, source_id=c.source_id,
            cause=SummonCause.capture(c), on_summon='k08.failgrant'),),
        'unknown': lambda c: (SummonFromZone(c.player_id, source_id=c.source_id,
            cause=SummonCause.capture(c), on_summon='missing.k08.callback'),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'holy': lambda c: (),
        'wound': lambda c: (Damage(c.state.players[c.player_id].hero_id,4,c.source_id),),
    }
    for name, body in scripts.items():
        r.register_behavior('k08.'+name, body)
        r.register_card(CardDefinition('k08.'+name, name, CardType.MINION if name == 'kill' else CardType.SPELL,
            health=1 if name == 'kill' else 0, battlecry='k08.kill' if name == 'kill' else None,
            on_play=None if name == 'kill' else 'k08.'+name, requires_target=name == 'kill',
            spell_school=SpellSchool.HOLY if name == 'holy' else None, metadata=neutral))
    if mode is not None:
        def watch(c):
            e = c.state.entities[c.event.source_id]
            if e.card_id not in ('k08.body', 'k08.demon', 'k08.cry'):
                return ()
            if mode == 'destroy': return (Destroy(e.id, c.source_id),)
            if mode == 'transform': return (Transform(e.id, 'k08.other'),)
            if mode == 'bounce': return (ReturnToHand(e.id), Summon(c.player_id, 'k08.other'))
            if mode == 'fatal': return (Damage(c.state.players[2].hero_id,100,c.source_id),)
            return (RequestChoice(1, (ChoiceOption('keep', 'Continue'),
                ChoiceOption('bounce', 'Bounce', (ReturnToHand(e.id),))), c.source_id),)
        r.register_behavior('k08.watch', watch)
        r.register_card(CardDefinition('k08.watch', 'Entry diagnostic', CardType.MINION, health=6,
            triggers=(TriggerSpec('minion_summoned', 'k08.watch'),), metadata=neutral))
    return r


class RecruitFollowupTests(unittest.TestCase):
    def game(self, script='recruit', deck=('k08.body', 'k08.cry'), board=(), mode=None):
        self.mode = mode
        return Game.from_scenario(Scenario((PlayerSetup('test.hero', hand=('k08.'+script,),
            deck=deck, board=board, mana=10, max_mana=10), PlayerSetup('test.hero')), seed=83), registry(mode))
    def play(self, g):
        g.apply(PlayCard(1, g.state.players[1].hand[0]))
    def choose(self, g, option='keep'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (option,)))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(saved, registry(self.mode))
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(self.mode)).snapshot(), saved)
        return other
    def bodies(self, g):
        return [g.state.entities[d.entity.entity_id] for row in g.state.card_summon_history
                for d in row.deliveries if d.entity is not None]
    def reject(self, saved):
        saved['events_hash'] = canonical_hash(saved['events'])
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry(self.mode))

    def test_each_selected_physical_body_gets_one_followup_and_no_battlecry(self):
        g = self.game(); originals = set(g.state.players[1].deck); self.play(g)
        self.assertEqual({e.id for e in self.bodies(g)}, originals)
        self.assertTrue(all(Keyword.RUSH in e.keywords for e in self.bodies(g)))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)
        self.assertEqual(sum(e.kind == 'recruit_followup_started' for e in g.events), 2)
        self.assertTrue(all(d.followup_started for row in g.state.card_summon_history for d in row.deliveries))
        self.portable(g)

    def test_direct_stored_followup_has_original_delivery_provenance(self):
        g = self.game('direct'); original = g.state.players[1].deck[0]; self.play(g)
        self.assertEqual(self.bodies(g)[0].id, original); self.assertIn(Keyword.RUSH, self.bodies(g)[0].keywords)
        self.portable(g)

    def test_quantity_extras_have_separate_followups_before_next_query(self):
        g = self.game(board=('k08.double',)); original = list(g.state.players[1].deck); self.play(g)
        self.assertEqual(len(self.bodies(g)), 4); self.assertEqual(len(g.state.card_summon_history), 2)
        self.assertTrue(all(Keyword.RUSH in e.keywords for e in self.bodies(g)))
        self.assertTrue(all(row.deliveries[0].entity.entity_id in original for row in g.state.card_summon_history))
        self.assertEqual(sum(e.kind == 'recruit_followup_started' for e in g.events), 4); self.portable(g)

    def test_partial_quantity_capacity_does_not_grant_failed_extra(self):
        g = self.game('direct', board=('k08.double',)+('k08.other',)*5); self.play(g)
        row = g.state.card_summon_history[0]
        self.assertEqual([d.outcome for d in row.deliveries], ['delivered', 'board_full'])
        self.assertEqual([d.followup_started for d in row.deliveries], [True, False]); self.portable(g)

    def test_empty_and_full_board_do_not_draw_rng_or_accept_followups(self):
        for deck, board in (((), ()), (('k08.body',), ('k08.other',)*7)):
            g = self.game(deck=deck, board=board); before = g.snapshot()['rng_state']; self.play(g)
            self.assertEqual(g.snapshot()['rng_state'], before); self.assertEqual(g.state.card_summon_history, [])
            self.assertFalse(any(e.kind == 'recruit_followup_started' for e in g.events)); self.portable(g)

    def test_missing_callback_rejects_even_empty_pool_and_rolls_back(self):
        g = self.game('unknown', deck=()); saved = g.snapshot()
        with self.assertRaises((ResolutionError, ValueError)): self.play(g)
        self.assertEqual(g.snapshot(), saved)

    def test_entry_wait_saves_owed_callback_before_grant_and_resumes_once(self):
        g = self.game('direct', mode='wait', board=('k08.watch',)); self.play(g)
        self.assertNotIn(Keyword.RUSH, self.bodies(g)[0].keywords)
        self.assertFalse(g.state.card_summon_history[0].deliveries[0].followup_started)
        other = self.portable(g); self.choose(g); self.choose(other)
        self.assertEqual(other.snapshot(), g.snapshot()); self.assertIn(Keyword.RUSH, self.bodies(g)[0].keywords)
        self.assertEqual(sum(e.kind == 'recruit_followup_started' for e in g.events), 1); self.portable(g)

    def test_callback_wait_keeps_accepted_once_marker_and_remaining_finish(self):
        g = self.game('wait'); self.play(g)
        self.assertTrue(g.state.card_summon_history[0].deliveries[0].followup_started)
        self.assertNotIn(Keyword.RUSH, self.bodies(g)[0].keywords); other = self.portable(g)
        self.choose(g); self.choose(other); self.assertEqual(other.snapshot(), g.snapshot())
        self.assertIn(Keyword.RUSH, self.bodies(g)[0].keywords)
        self.assertEqual(sum(e.kind == 'recruit_followup_started' for e in g.events), 1)

    def test_dead_transformed_and_bounced_body_skip_without_granting_later_board_entity(self):
        for mode in ('destroy', 'transform', 'bounce'):
            with self.subTest(mode=mode):
                g = self.game('direct', mode=mode, board=('k08.watch',)); self.play(g)
                self.assertTrue(g.state.card_summon_history[0].deliveries[0].followup_started)
                self.assertTrue(all(Keyword.RUSH not in e.keywords for e in g.state.entities.values()))
                self.portable(g)

    def test_late_callback_error_rolls_back_selection_movement_rng_and_marker(self):
        g = self.game('fault'); saved = g.snapshot()
        with self.assertRaises((ResolutionError, ValueError)): self.play(g)
        self.assertEqual(g.snapshot(), saved)

    def test_players_cannot_read_callback_receipts_candidates_or_saved_work(self):
        g = self.game('direct', mode='wait', board=('k08.watch',)); self.play(g)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for word in ('recruit_followup_started', 'followup_started', 'ContinueRecruitedMinion',
                         'RecruitEntryMaterial', 'rng_before', 'on_summon'):
                self.assertNotIn('"'+word+'"', public)
        self.assertEqual(g.for_player(2).observe()['observation']['pending_choice'], {'player_id':1})

    def test_rehashed_missing_or_duplicate_owed_callback_is_rejected(self):
        g = self.game('direct', mode='wait', board=('k08.watch',)); self.play(g)
        for duplicate in (False, True):
            saved = g.snapshot(); hits = [0]
            def rewrite(node):
                if isinstance(node, list):
                    result = []
                    for child in node:
                        if isinstance(child, dict) and str(child.get('type', '')).endswith('.ContinueRecruitedMinion'):
                            hits[0] += 1
                            if duplicate: result.extend([deepcopy(child), deepcopy(child)])
                        else: result.append(rewrite(child))
                    return result
                if isinstance(node, dict): return {k:rewrite(v) for k,v in node.items()}
                return node
            saved['resolution_frame'] = rewrite(saved['resolution_frame']); self.assertGreater(hits[0], 0)
            self.reject(saved)

    def test_wrong_body_or_behavior_cannot_borrow_original_followup(self):
        g = self.game('direct', mode='wait', board=('k08.watch',)); self.play(g)
        row = g.state.card_summon_history[0]; fact = row.deliveries[0].entity
        from hs_sim.engine.sacrifice import MinionReference
        ref = MinionReference(fact.entity_id, fact.controller, fact.card_id, fact.zone_epoch, fact.entered_order)
        for effect in (ContinueRecruitedMinion(row.id, 0, replace(ref, entity_id=g.state.players[1].board[0]), 'k08.grant'),
                       ContinueRecruitedMinion(row.id, 0, ref, 'k08.waitgrant')):
            with self.assertRaises(ValueError): followup_record(g.state, g.registry, effect)

    def test_rehashed_changed_acceptance_marker_and_missing_receipt_are_rejected(self):
        g = self.game('direct'); self.play(g)
        saved = g.snapshot(); saved['state']['card_summon_history'][0]['deliveries'][0]['followup_started'] = False
        self.reject(saved)
        saved = g.snapshot(); saved['events'] = [e for e in saved['events'] if e['kind'] != 'recruit_followup_started']
        self.reject(saved)

    def test_followup_requires_attribution_and_old_schema_is_explicitly_rejected(self):
        with self.assertRaises(ValueError): SummonFromZone(1, on_summon='k08.grant')
        g = self.game('direct'); saved = g.snapshot(); saved['schema_version'] = 266
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry())
        self.assertEqual(g.snapshot()['schema_version'], SNAPSHOT_SCHEMA_VERSION)

    def test_each_quantity_reaction_wait_preserves_remaining_followups_and_queries(self):
        g = self.game(board=('k08.double','k08.watch'),mode='wait');self.play(g);waits=0
        while g.state.pending_choice is not None:
            other=self.portable(g);self.choose(g);self.choose(other)
            self.assertEqual(g.snapshot(),other.snapshot());waits+=1
        self.assertEqual(waits,4);self.assertEqual(len(self.bodies(g)),4)
        self.assertEqual(sum(e.kind=='recruit_followup_started' for e in g.events),4);self.portable(g)

    def test_terminal_entry_reaction_interrupts_owed_followup_and_later_recruit(self):
        g=self.game(mode='fatal',board=('k08.watch',));self.play(g)
        self.assertNotEqual(g.state.status,'playing')
        self.assertEqual(len(g.state.card_summon_history),1)
        self.assertEqual(g.state.card_summon_history[0].status,'interrupted')
        self.assertFalse(g.state.card_summon_history[0].deliveries[0].followup_started)
        self.assertFalse(any(e.kind=='recruit_followup_started' for e in g.events));self.portable(g)


if __name__ == '__main__': unittest.main()
