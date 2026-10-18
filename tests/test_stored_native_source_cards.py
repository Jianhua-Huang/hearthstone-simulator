"""Real absorption/eating, retained payloads and ordinary Deathrattle delivery."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.stored_native_source_cards import CLOUD, ANCIENT, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard,
    PlayerSetup, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, CopyMinion,
    Damage, Destroy, GainArmor, InvokeBehavior, RequestChoice, ReturnToHand,
    Silence, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import BattlecryRepeatSpec, CostSpec, DeathrattleRepeatSpec, EndTurnRepeatSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.stored_spell_damage import GrantStoredSpellDamage
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.targets import canonical_digest

P = 'k201.'
A, B, FIRE, FOUR, BIG, WATCH, BC2, DR2, END2 = (P + x for x in
    ('a', 'b', 'fire', 'four', 'big', 'watch', 'bc2', 'dr2', 'end2'))


@lru_cache(None)
def registry(mode=None):
    r = build_registry()
    for cid, attack, health in ((A, 2, 3), (B, 3, 4)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1,
                                       attack=attack, health=health))
    for cid, cost, armor in ((FOUR, 4, 5), (BIG, 6, 7)):
        r.register_behavior(cid, lambda c, amount=armor: (GainArmor(c.player_id, amount),))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=cost, on_play=cid))
    r.register_behavior(FIRE, lambda c: (Damage(c.state.players[3-c.player_id].hero_id,
                                               2, c.source_id),))
    r.register_card(CardDefinition(FIRE, FIRE, CardType.SPELL, cost=1, on_play=FIRE))
    r.register_card(CardDefinition(BC2, BC2, CardType.MINION, health=20,
                                   battlecry_repeats=(BattlecryRepeatSpec(2),)))
    r.register_card(CardDefinition(DR2, DR2, CardType.MINION, health=20,
                                   deathrattle_repeats=(DeathrattleRepeatSpec(2),)))
    r.register_card(CardDefinition(END2, END2, CardType.MINION, health=20,
                                   end_turn_repeats=(EndTurnRepeatSpec(2, scope='minion'),)))
    def grow(c):
        e = next(c.state.entities[i] for i in c.state.players[c.player_id].deck
                 if c.state.entities[i].card_id == A)
        return (BuffStoredCard(CardReference.capture(e), 4, 5, c.source_id),)
    bodies = dict(
        kill=lambda c: (Destroy(c.target_id, c.source_id),),
        silence=lambda c: (Silence(c.target_id),),
        bounce=lambda c: (ReturnToHand(c.target_id),),
        copy=lambda c: (CopyMinion(c.target_id, c.player_id),),
        base=lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        give=lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        trigger=lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        discount=lambda c: (ModifyStoredCost(CardReference.capture(c.state.entities[c.target_id]),
                                            CostSpec(delta=-3), source_id=c.source_id),),
        spell_bonus=lambda c: (GrantStoredSpellDamage(CardReference.capture(c.state.entities[c.target_id]),
                                                     5, c.source_id),),
        grow=grow,
        fail=lambda c: (AddToHand(c.player_id, P+'unknown', c.source_id),))
    for name, body in bodies.items():
        r.register_behavior(P+name, body)
        if name == 'fail':
            continue
        fields = {} if name == 'grow' else dict(targeting=TargetSpec(
            zones=(Zone.HAND,) if name in ('discount', 'spell_bonus') else (Zone.BOARD,),
            kinds=(CardType.SPELL,) if name in ('discount', 'spell_bonus') else (CardType.MINION,)))
        r.register_card(CardDefinition(P+name, name, CardType.SPELL, on_play=P+name, **fields))
    def react(c):
        e = c.state.entities.get(c.event.source_id)
        if e is None or e.card_id not in (CLOUD, ANCIENT):
            return ()
        if mode == 'return' and c.state.entities[c.event.target_id].card_id not in (A, B):
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', ()),
            ChoiceOption('bad', 'Rollback', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))),
            c.source_id),)
    r.register_behavior(P+'react', react)
    event = {'grant': 'ability_granted', 'return': 'card_created', 'cast': 'spell_cast_started'}.get(mode)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=50,
        triggers=() if event is None else (TriggerSpec(event, P+'react'),)))
    r.validate()
    return r


class StoredNativeSourceTests(unittest.TestCase):
    def game(self, hand=(), board=(), deck=(A,), enemy_hand=(), enemy=(), actor=1, mode=None):
        self.mode = mode
        own = PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
                          mana=80, max_mana=80, mana_cap=80)
        other = PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(B,)*8,
                            mana=80, max_mana=80, mana_cap=80)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own),
            active_player=actor, seed=201), registry(mode))

    def eid(self, g, cid, zone='hand', player=None):
        p = g.state.active_player if player is None else player
        return next(i for i in getattr(g.state.players[p], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None):
        eid = self.eid(g, cid)
        g.apply(PlayCard(g.state.active_player, eid, target))
        return eid

    def payloads(self, g, eid):
        return tuple(a for a in g.state.entities[eid].abilities if a.consumed_card_id is not None)

    def armor(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].armor

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        fresh = registry.__wrapped__(self.mode)
        self.assertEqual(Game.from_snapshot(deepcopy(snap), fresh).snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), fresh).snapshot(), snap)
        return snap

    def reject(self, g, snap):
        keys = ('ruleset', 'registry_fingerprint', 'mechanics_version', 'state', 'rng_state',
                'resolution_frame', 'rewind_session', 'match_setup', 'generation_context', 'information')
        snap['state_hash'] = canonical_hash({k:snap[k] for k in keys})
        with self.assertRaises(SnapshotError) as caught:
            Game.from_snapshot(snap, g.registry)
        self.assertNotIn('digest mismatch', str(caught.exception))

    def test_two_complete_native_sources_and_four_primary_faces(self):
        data = load_batch()
        self.assertEqual([x['record']['id'] for x in data['cards']], [CLOUD, ANCIENT])
        self.assertEqual(len(data['official_observations']), 4)
        for row in data['cards']:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        self.assertEqual([(registry().card(cid).cost, registry().card(cid).attack,
                           registry().card(cid).health) for cid in (CLOUD, ANCIENT)],
                         [(3,4,3), (8,6,7)])

    def test_cloud_absorbs_original_hand_spell_without_discard_or_death(self):
        g = self.game((CLOUD, FOUR))
        target = self.eid(g, FOUR)
        source = self.play(g, CLOUD, target)
        self.assertEqual(g.state.entities[target].zone, Zone.SETASIDE)
        self.assertEqual(g.state.players[1].mana, 77)
        self.assertFalse(g.state.discard_history or g.state.death_history or g.state.draw_history)
        row, = g.state.consumed_card_history
        self.assertEqual((row.card.origin.entity_id, row.source.entity_id), (target, source))
        self.assertEqual(row.after_epoch, row.card.origin.zone_epoch+1)
        self.assertEqual([a.consumed_card_id for a in self.payloads(g, source)], [row.id])
        self.portable(g)

    def test_cloud_accepts_current_discounted_cost(self):
        g = self.game((CLOUD, BIG, P+'discount'))
        target = self.eid(g, BIG)
        self.play(g, P+'discount', target)
        self.play(g, CLOUD, target)
        self.assertEqual(g.state.consumed_card_history[0].card.origin.card_id, BIG)

    def test_cloud_targets_only_own_eligible_hand_spells(self):
        g = self.game((CLOUD, FIRE, FOUR, BIG, A), enemy_hand=(FIRE,))
        source = self.eid(g, CLOUD)
        actions = [a for a in g.legal_actions() if isinstance(a, PlayCard) and a.entity_id == source]
        self.assertEqual({a.target_id for a in actions}, {self.eid(g, FIRE), self.eid(g, FOUR)})

    def test_cloud_with_no_eligible_spell_can_be_played_without_target(self):
        g = self.game((CLOUD, BIG, A))
        self.play(g, CLOUD)
        self.assertFalse(g.state.consumed_card_history)

    def test_cloud_natural_death_casts_absorbed_spell_without_paying_it(self):
        g = self.game((CLOUD, FOUR, P+'kill'))
        source = self.play(g, CLOUD, self.eid(g, FOUR))
        before = g.state.players[1].mana
        self.play(g, P+'kill', source)
        self.assertEqual((self.armor(g), g.state.players[1].mana), (5, before))
        self.assertEqual(sum(x.card_id == FOUR for x in g.state.cast_history), 1)
        self.portable(g)

    def test_repeated_battlecry_does_not_absorb_another_spell(self):
        g = self.game((CLOUD, FIRE, FOUR), board=(BC2,))
        other = self.eid(g, FOUR)
        source = self.play(g, CLOUD, self.eid(g, FIRE))
        self.assertEqual(len(g.state.consumed_card_history), 1)
        self.assertEqual(len(self.payloads(g, source)), 1)
        self.assertIn(other, g.state.players[1].hand)

    def test_repeated_deathrattle_casts_twice_without_consuming_again(self):
        g = self.game((CLOUD, FIRE, P+'kill'), board=(DR2,))
        source = self.play(g, CLOUD, self.eid(g, FIRE))
        self.play(g, P+'kill', source)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 26)
        self.assertEqual(len(g.state.consumed_card_history), 1)

    def test_silence_removes_absorbed_deathrattle(self):
        g = self.game((CLOUD, FOUR, P+'silence', P+'kill'))
        source = self.play(g, CLOUD, self.eid(g, FOUR))
        self.play(g, P+'silence', source)
        self.play(g, P+'kill', source)
        self.assertEqual(self.armor(g), 0)

    def test_return_to_hand_clears_old_payload(self):
        g = self.game((CLOUD, FOUR, P+'bounce'), enemy_hand=(P+'kill',))
        source = self.play(g, CLOUD, self.eid(g, FOUR))
        self.play(g, P+'bounce', source)
        self.assertFalse(self.payloads(g, source))
        self.play(g, CLOUD)
        g.apply(EndTurn(1))
        self.play(g, P+'kill', source)
        self.assertEqual(self.armor(g), 0)

    def test_current_copy_preserves_payload_and_base_copy_starts_empty(self):
        g = self.game((CLOUD, FOUR, P+'copy', P+'base', P+'kill', P+'kill'))
        source = self.play(g, CLOUD, self.eid(g, FOUR))
        self.play(g, P+'copy', source)
        self.play(g, P+'base', source)
        copies = [i for i in g.state.players[1].board if i != source]
        self.assertEqual([len(self.payloads(g, i)) for i in copies], [1,0])
        self.play(g, P+'kill', source)
        self.play(g, P+'kill', copies[0])
        self.assertEqual(self.armor(g), 10)
        self.portable(g)

    def test_transferred_cloud_casts_for_actual_death_controller(self):
        g = self.game((CLOUD, FIRE, P+'give', P+'kill'))
        source = self.play(g, CLOUD, self.eid(g, FIRE))
        self.play(g, P+'give', source)
        self.play(g, P+'kill', source)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 28)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)

    def test_actual_inheritance_retains_absorbed_payload(self):
        g = self.game((CLOUD, FOUR, P+'kill', 'EDR_491', P+'kill'))
        source = self.play(g, CLOUD, self.eid(g, FOUR))
        self.play(g, P+'kill', source)
        inheritor = self.play(g, 'EDR_491')
        self.assertEqual(len(self.payloads(g, inheritor)), 1)
        self.play(g, P+'kill', inheritor)
        self.assertEqual(self.armor(g), 10)
        self.portable(g)

    def test_historical_printed_cloud_does_not_replay_additional_grant(self):
        g = self.game((CLOUD, FOUR, P+'kill', 'JAIL_940'))
        source = self.play(g, CLOUD, self.eid(g, FOUR))
        self.play(g, P+'kill', source)
        self.play(g, 'JAIL_940')
        self.assertEqual(self.armor(g), 5)

    def test_current_spell_material_is_retained_but_native_output_uses_base_policy(self):
        g = self.game((CLOUD, FIRE, P+'spell_bonus', P+'kill'))
        spell = self.eid(g, FIRE)
        self.play(g, P+'spell_bonus', spell)
        source = self.play(g, CLOUD, spell)
        self.assertTrue(g.state.consumed_card_history[0].card.local.abilities or
                        g.state.consumed_card_history[0].card.local.enchantments)
        self.play(g, P+'kill', source)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28)

    def test_ancient_owner_end_eats_one_physical_minion_and_gains_stats(self):
        g = self.game((ANCIENT,), deck=(A,))
        source = self.play(g, ANCIENT)
        victim = self.eid(g, A, 'deck')
        g.apply(EndTurn(1))
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health), (8,10))
        self.assertEqual(g.state.entities[victim].zone, Zone.SETASIDE)
        self.assertFalse(g.state.discard_history or g.state.death_history)
        self.assertEqual(len(g.state.consumed_card_history), 1)
        self.portable(g)

    def test_opponent_end_does_not_eat(self):
        g = self.game((P+'give',), board=(ANCIENT,), deck=(A,B))
        source = self.eid(g, ANCIENT, 'board')
        self.play(g, P+'give', source)
        g.apply(EndTurn(1))
        self.assertFalse(g.state.consumed_card_history)

    def test_empty_or_spell_only_deck_does_not_consume_rng(self):
        for deck in ((), (FIRE,FOUR)):
            with self.subTest(deck=deck):
                g = self.game(board=(ANCIENT,), deck=deck)
                before = g.snapshot()['rng_state']
                g.apply(EndTurn(1))
                self.assertEqual(g.snapshot()['rng_state'], before)
                self.assertFalse(g.state.consumed_card_history)

    def test_random_eating_excludes_spells_and_preserves_complete_candidates(self):
        g = self.game(board=(ANCIENT,), deck=(FIRE,A,FOUR,B))
        g.apply(EndTurn(1))
        row, = g.state.consumed_card_history
        self.assertEqual([r.card_id for r in row.candidates], [A,B])
        self.assertIn(row.card.origin.card_id, (A,B))
        self.portable(g)

    def test_ancient_gains_current_deck_stats_but_returns_base_minion(self):
        g = self.game((P+'grow', P+'kill'), board=(ANCIENT,), deck=(A,))
        source = self.eid(g, ANCIENT, 'board')
        self.play(g, P+'grow')
        g.apply(EndTurn(1))
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health), (12,15))
        g.apply(EndTurn(2))
        self.play(g, P+'kill', source)
        returned = g.state.entities[self.eid(g, A)]
        self.assertEqual((returned.attack, returned.max_health), (2,3))

    def test_repeated_end_eats_distinct_cards_and_death_returns_both(self):
        g = self.game((P+'kill',), board=(ANCIENT,END2), deck=(A,B))
        source = self.eid(g, ANCIENT, 'board')
        g.apply(EndTurn(1))
        self.assertEqual(len(g.state.consumed_card_history), 2)
        self.assertEqual([len(x.candidates) for x in g.state.consumed_card_history], [2,1])
        self.assertEqual(len(self.payloads(g, source)), 2)
        g.apply(EndTurn(2))
        self.play(g, P+'kill', source)
        returned = [g.state.entities[i].card_id for i in g.state.players[1].hand]
        self.assertEqual(returned, [x.card.origin.card_id for x in g.state.consumed_card_history])
        self.portable(g)

    def test_ancient_without_food_still_has_structural_printed_deathrattle(self):
        g = self.game((P+'kill',), board=(ANCIENT,), deck=())
        source = self.eid(g, ANCIENT, 'board')
        self.assertTrue(any(a.kind == 'deathrattle' for a in g.state.entities[source].abilities))
        self.play(g, P+'kill', source)
        self.assertFalse(g.state.players[1].hand)

    def test_grant_waiting_is_atomic_and_portable(self):
        g = self.game((CLOUD, FOUR), board=(WATCH,), mode='grant')
        source = self.play(g, CLOUD, self.eid(g, FOUR))
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(self.payloads(g, source)), 1)
        self.assertEqual(len(g.state.consumed_card_history), 1)
        self.portable(g)
        self.choose(g)
        self.portable(g)

    def test_ancient_stats_and_payload_precede_grant_waiting(self):
        g = self.game(board=(ANCIENT,WATCH), deck=(A,), mode='grant')
        source = self.eid(g, ANCIENT, 'board')
        g.apply(EndTurn(1))
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health), (8,10))
        self.portable(g)
        self.choose(g)

    def test_failed_choice_restores_original_consumption_waiting(self):
        g = self.game((CLOUD, FOUR), board=(WATCH,), mode='grant')
        self.play(g, CLOUD, self.eid(g, FOUR))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g)

    def test_return_waiting_restores_remaining_deathrattles(self):
        g = self.game((P+'kill',), board=(ANCIENT,END2,WATCH), deck=(A,B), mode='return')
        source = self.eid(g, ANCIENT, 'board')
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.play(g, P+'kill', source)
        for _ in range(2):
            self.assertIsNotNone(g.state.pending_choice)
            self.portable(g)
            self.choose(g)
        self.assertIsNone(g.state.pending_choice)

    def test_player_projection_does_not_expose_private_consumption_material(self):
        g = self.game((CLOUD, FOUR))
        self.play(g, CLOUD, self.eid(g, FOUR))
        for player in (1,2):
            public = json.dumps(g.observe(player))+json.dumps(g.player_events(player))
            for key in ('consumed_card_history', 'consumed_card_id', 'rng_before', 'rng_after', 'after_epoch'):
                self.assertNotIn('"'+key+'"', public)

    def test_missing_consumption_record_or_changed_event_is_rejected(self):
        g = self.game((CLOUD, FOUR))
        self.play(g, CLOUD, self.eid(g, FOUR))
        snap = g.snapshot()
        snap['state']['consumed_card_history'] = []
        self.reject(g, snap)
        snap = g.snapshot()
        snap['state']['consumed_card_history'][0]['event_sequence'] += 1
        self.reject(g, snap)

    def test_old_snapshot_schema_is_rejected(self):
        g = self.game()
        snap = g.snapshot()
        snap['schema_version'] = 401
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(snap, g.registry)
