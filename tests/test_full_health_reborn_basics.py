"""A real Reborn gift recipe and focused lifecycle diagnostics, not its full pool."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine.actions import EndTurn, PlayCard, SelectChoice
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    DamageBatch, Destroy, GainArmor, GrantKeyword, InvokeBehavior, RequestChoice,
    ReturnToHand, SetStats, Silence, Summon, Transform)
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.game import Game, PlayerSetup, Scenario
from hs_sim.engine.hand_keywords import GrantStoredKeyword
from hs_sim.engine.lifecycle import restore_reborn_enchantments
from hs_sim.engine.model import (AbilityInstance, AuraSpec, CardDefinition, CardType,
    Keyword, TriggerSpec, Zone, validate_invariants)
from hs_sim.engine.registry import Registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

ROOT = Path(__file__).resolve().parents[1]
NATIVE = 'CS2_120'
POLICY = 'full_health_enchantments'
PIN = 'ab704400d1ebcc9b321067c4c2cdeaf63876a88d8b8856b1a93a44b8e226d56d'


def evidence():
    packet = json.loads((ROOT/'data/support/full-health-reborn-basics.json').read_bytes())
    if canonical_digest(packet) != PIN:
        raise ValueError('Full native Reborn gift evidence changed')
    return packet


def gift(card, source_id):
    # EDR_100t9 is a choice descriptor, not a playable spell. Its isolated
    # recipe is exercised here without inventing a partial native Discover pool.
    evidence()
    return GrantStoredKeyword(card, Keyword.REBORN, source_id, reborn_policy=POLICY)


def registry():
    r = Registry('full-health-reborn-independent-v1')
    r.register_card(CardDefinition('fr.hero', 'Diagnostic hero', CardType.HERO, health=30))
    row = next(x for x in evidence()['records'] if x['id'] == NATIVE)
    r.register_card(CardDefinition(NATIVE, row['name'], CardType.MINION, cost=row['cost'],
        attack=row['attack'], health=row['health'], metadata=metadata_from_record(row)))
    r.register_card(CardDefinition('fr.token', 'Capacity diagnostic', CardType.MINION, attack=1, health=1))
    r.register_card(CardDefinition('fr.reborn', 'Ordinary Reborn diagnostic', CardType.MINION,
        attack=2, health=3, keywords=(Keyword.REBORN,)))
    r.register_card(CardDefinition('fr.shield', 'Native Shield diagnostic', CardType.MINION,
        attack=2, health=3, keywords=(Keyword.DIVINE_SHIELD,)))
    r.register_card(CardDefinition('fr.aura', 'External health diagnostic', CardType.MINION,
        health=3, auras=(AuraSpec(0, health=2),)))
    r.register_card(CardDefinition('fr.weapon', 'Schema carrier diagnostic', CardType.WEAPON,
        attack=1, durability=1))
    r.register_behavior('fr.cb.battlecry', lambda c: (GainArmor(c.player_id, 3),))
    r.register_behavior('fr.cb.deathrattle', lambda c: (GainArmor(c.player_id, 2),))
    r.register_card(CardDefinition('fr.body', 'Native bodies diagnostic', CardType.MINION,
        cost=1, health=3, battlecry='fr.cb.battlecry', deathrattle='fr.cb.deathrattle'))

    def fail(c):
        raise ResolutionError('Deliberate full-health Reborn rollback')
    r.register_behavior('fr.cb.fail', fail)
    r.register_behavior('fr.cb.wait', lambda c: (RequestChoice(c.player_id, (
        ChoiceOption('done', 'Continue', (GainArmor(c.player_id, 1),)),
        ChoiceOption('fill', 'Fill board', tuple(Summon(c.player_id, 'fr.token') for _ in range(7))),
        ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 9), InvokeBehavior('fr.cb.fail', c.source_id, c.player_id))),
    ), c.source_id),))
    r.register_card(CardDefinition('fr.wait', 'Death continuation diagnostic', CardType.MINION,
        attack=2, health=3, deathrattle='fr.cb.wait'))
    r.register_card(CardDefinition('fr.failwatch', 'Rollback diagnostic', CardType.MINION, health=3,
        triggers=(TriggerSpec('minion_reborn', 'fr.cb.fail'),)))

    def hand_ref(c):
        return CardReference.capture(next(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].kind == CardType.MINION))
    def wait_grant(c, stored):
        effect = gift(hand_ref(c), c.source_id) if stored else GrantKeyword(
            c.target_id, Keyword.REBORN, c.source_id, reborn_policy=POLICY)
        return (RequestChoice(c.player_id, (
            ChoiceOption('gift', 'Persisting Horror', (effect,)),
            ChoiceOption('leave', 'Leave unchanged', ()),
        ), c.source_id),)
    bodies = {
        'gift': lambda c: (GrantKeyword(c.target_id, Keyword.REBORN, c.source_id, reborn_policy=POLICY),),
        'tempgift': lambda c: (GrantKeyword(c.target_id, Keyword.REBORN, c.source_id,
            expires_turn=c.state.turn, reborn_policy=POLICY),),
        'handgift': lambda c: (gift(hand_ref(c), c.source_id),),
        'handwait': lambda c: wait_grant(c, True),
        'boardwait': lambda c: wait_grant(c, False),
        'buff': lambda c: (Buff(c.target_id, 2, 4, c.source_id),),
        'tempbuff': lambda c: (Buff(c.target_id, 2, 4, c.source_id, c.state.turn),),
        'layers': lambda c: (Buff(c.target_id, 2, 4, c.source_id), SetStats(c.target_id, attack=7, health=9),
            Buff(c.target_id, 1, 2, c.source_id)),
        'kill': lambda c: (Destroy(c.target_id),),
        'killall': lambda c: (DamageBatch(tuple(Damage(i, 99) for p in c.state.players.values() for i in p.board)),),
        'ping': lambda c: (Damage(c.target_id, 1),),
        'shieldgrant': lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'transform': lambda c: (Transform(c.target_id, 'fr.token'),),
        'copy': lambda c: (CopyMinion(c.target_id, c.player_id),),
        'basecopy': lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        'steal': lambda c: (ChangeControl(c.target_id, 2),),
        'sleep': lambda c: (MakeDormant(c.state.players[c.player_id].board[0], 2),),
        'awake': lambda c: (AwakenMinion(c.state.players[c.player_id].board[0]),),
        'badhero': lambda c: (GrantKeyword(c.state.players[c.player_id].hero_id, Keyword.REBORN,
            c.source_id, reborn_policy=POLICY),),
    }
    untargeted = {'handgift', 'handwait', 'killall', 'sleep', 'awake', 'badhero'}
    for name, body in bodies.items():
        r.register_behavior('fr.cb.'+name, body)
        r.register_card(CardDefinition('fr.'+name, name+' diagnostic', CardType.SPELL, cost=1,
            on_play='fr.cb.'+name, requires_target=name not in untargeted))
    return r


class FullHealthRebornTests(unittest.TestCase):
    def game(self, hand=(), board=(NATIVE,), enemy_board=(), enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('fr.hero', hand=hand, board=board, deck=('fr.token',)*12, mana=10, max_mana=10),
            PlayerSetup('fr.hero', hand=enemy_hand, board=enemy_board, deck=('fr.token',)*12, mana=10, max_mana=10),
        ), seed=113), registry())
    def find(self, g, card, player=1, zone='hand'):
        return next(i for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == card)
    def body(self, g, player=1):
        return g.state.entities[g.state.players[player].board[0]]
    def play(self, g, card, target=None, player=1):
        return g.apply(PlayCard(player, self.find(g, card, player), target))
    def choose(self, g, key='done'):
        q = g.state.pending_choice
        return g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        variants = (Game.from_snapshot(saved, registry()), g.clone(), replay(build_replay(g), registry()))
        for other in variants:
            self.assertEqual(other.snapshot(), saved)
        return variants
    def armor(self, g):
        return g.state.entities[g.state.players[1].hero_id].armor
    def rehash(self, saved):
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        return saved
    def gift_and_buff(self, g, target=None):
        target = target or self.body(g).id
        self.play(g, 'fr.gift', target); self.play(g, 'fr.buff', target)
        return target

    def test_complete_native_raw_pin_and_descriptor_scope(self):
        p = evidence(); rows = {x['id']:x for x in p['records']}
        self.assertEqual(set(rows), {NATIVE, 'EDR_100t9', 'EDR_100t9e'})
        self.assertEqual((rows[NATIVE]['attack'], rows[NATIVE]['health']), (2, 3))
        self.assertIn('full Health and enchantments', rows['EDR_100t9']['text_en'])
        self.assertEqual(rows['EDR_100t9e']['tags']['4137'], 1)
        self.assertFalse(p['full_dark_gift_discover']); self.assertFalse(p['formal_pool'])
        self.assertNotIn('EDR_100t9', registry().cards)
        g = self.game()
        self.assertEqual((g.ruleset.id, g.mechanics.version, g.snapshot()['schema_version']),
                         ('prototype-v302', CORE_EFFECTS_VERSION, 265))

    def test_board_gift_returns_full_health_frozen_buff_and_new_identities(self):
        g = self.game(('fr.gift', 'fr.buff', 'fr.ping', 'fr.kill', 'fr.kill'))
        old = self.gift_and_buff(g); self.play(g, 'fr.ping', old)
        original = g.state.entities[old]; rng = g.snapshot()['rng_state']
        self.play(g, 'fr.kill', old); new = self.body(g)
        self.assertNotEqual(old, new.id); self.assertEqual(new.origin_entity_id, old)
        self.assertEqual((new.attack, new.max_health, new.health), (4, 7, 7))
        self.assertEqual(new.enchantments[0].source_id, original.enchantments[0].source_id)
        self.assertTrue({a.id for a in (*new.abilities, *new.enchantments)}.isdisjoint(
            {a.id for a in (*original.abilities, *original.enchantments)}))
        self.assertNotIn(Keyword.REBORN, new.keywords)
        self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertTrue(next(a for a in new.abilities if a.reborn_policy == POLICY).consumed)
        self.assertFalse(next(a for a in g.state.death_history[0].abilities if a.reborn_policy == POLICY).consumed)
        self.play(g, 'fr.kill', new.id); self.assertEqual(g.state.players[1].board, [])
        self.portable(g)

    def test_stored_real_recipe_follows_native_minion_and_pays_once(self):
        g = self.game(('fr.handgift', NATIVE, 'fr.buff', 'fr.kill'), board=())
        source = self.find(g, 'fr.handgift'); card = self.find(g, NATIVE)
        self.play(g, 'fr.handgift')
        self.assertEqual(g.state.entities[card].abilities[0].reborn_policy, POLICY)
        self.assertEqual(g.state.entities[card].abilities[0].source_id, source)
        self.play(g, NATIVE); self.play(g, 'fr.buff', card)
        before = g.state.players[1].mana; self.play(g, 'fr.kill', card)
        self.assertEqual(g.state.players[1].mana, before-1)
        self.assertEqual((self.body(g).health, self.body(g).max_health), (7, 7))
        self.portable(g)

    def test_ordinary_reborn_still_drops_buffs_and_returns_one_health(self):
        g = self.game(('fr.buff', 'fr.kill'), board=('fr.reborn',))
        old = self.body(g).id; self.play(g, 'fr.buff', old); self.play(g, 'fr.kill', old)
        new = self.body(g)
        self.assertEqual((new.attack, new.max_health, new.health), (2, 3, 1))
        self.assertEqual(new.enchantments, []); self.assertNotIn(Keyword.REBORN, new.keywords)

    def test_ordered_set_and_add_enchantments_retain_their_values(self):
        g = self.game(('fr.gift', 'fr.layers', 'fr.kill'))
        old = self.body(g).id; self.play(g, 'fr.gift', old); self.play(g, 'fr.layers', old)
        original = self.body(g); self.play(g, 'fr.kill', old); new = self.body(g)
        self.assertEqual((new.attack, new.max_health, new.health), (8, 11, 11))
        self.assertEqual([replace(e, id=1) for e in new.enchantments],
                         [replace(e, id=1) for e in original.enchantments])

    def test_fresh_printed_shield_and_frozen_consumed_granted_shield(self):
        for native in (False, True):
            with self.subTest(native=native):
                g = self.game(('fr.gift', 'fr.shieldgrant', 'fr.ping', 'fr.kill'), board=('fr.shield',) if native else (NATIVE,))
                old = self.body(g).id; self.play(g, 'fr.gift', old)
                if not native: self.play(g, 'fr.shieldgrant', old)
                self.play(g, 'fr.ping', old); self.assertNotIn(Keyword.DIVINE_SHIELD, self.body(g).keywords)
                self.play(g, 'fr.kill', old)
                self.assertEqual(Keyword.DIVINE_SHIELD in self.body(g).keywords, native)

    def test_reborn_is_not_another_play_or_battlecry_and_retains_native_deathrattle(self):
        g = self.game(('fr.handgift', 'fr.body', 'fr.kill', 'fr.kill'), board=())
        self.play(g, 'fr.handgift'); self.play(g, 'fr.body'); old = self.body(g).id
        self.assertEqual(self.armor(g), 3); self.play(g, 'fr.kill', old)
        self.assertEqual(self.armor(g), 5); self.play(g, 'fr.kill', self.body(g).id)
        self.assertEqual(self.armor(g), 7)
        self.assertEqual(len([e for e in g.events if e.kind == 'minion_reborn']), 1)
        self.portable(g)

    def test_waiting_death_continuation_restores_clones_and_replays_from_frozen_material(self):
        g = self.game(('fr.gift', 'fr.buff', 'fr.kill'), board=('fr.wait',))
        old = self.gift_and_buff(g); self.play(g, 'fr.kill', old)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(g.state.players[1].board, [])
        for other in (g, *self.portable(g)):
            self.choose(other); self.assertEqual(self.body(other).health, 7)
            self.portable(other)

    def test_waiting_stored_and_board_grants_keep_policy_in_effect_frames(self):
        for stored in (False, True):
            with self.subTest(stored=stored):
                g = self.game(('fr.handwait', NATIVE, 'fr.kill'), board=()) if stored else self.game(('fr.boardwait', 'fr.kill'))
                self.play(g, 'fr.handwait' if stored else 'fr.boardwait', None if stored else self.body(g).id)
                self.assertIsNotNone(g.state.pending_choice)
                for other in (g, *self.portable(g)):
                    self.choose(other, 'gift')
                    if stored: self.play(other, NATIVE)
                    old = self.body(other).id; self.play(other, 'fr.kill', old)
                    self.assertEqual(self.body(other).health, 3); self.portable(other)

    def test_frozen_copy_helper_does_not_read_mutated_graveyard_material(self):
        g = self.game(('fr.gift', 'fr.buff', 'fr.basecopy', 'fr.kill'), board=('fr.wait',))
        old = self.gift_and_buff(g); self.play(g, 'fr.basecopy', old); self.play(g, 'fr.kill', old)
        state = g.state; record = state.death_history[0]; destination = state.entities[state.players[1].board[0]]
        state.entities[old].abilities.clear(); state.entities[old].enchantments.clear()
        restore_reborn_enchantments(state, record, destination)
        self.assertEqual((destination.attack, destination.max_health), (4, 7))
        self.assertTrue(any(a.reborn_policy == POLICY for a in destination.abilities))

    def test_deathrattle_capacity_failure_does_not_resurrect_later(self):
        g = self.game(('fr.gift', 'fr.kill'), board=('fr.wait',))
        old = self.body(g).id; self.play(g, 'fr.gift', old); self.play(g, 'fr.kill', old)
        self.choose(g, 'fill')
        self.assertEqual(len(g.state.players[1].board), 7)
        failed = [e for e in g.events if e.kind == 'reborn_failed']
        self.assertEqual(len(failed), 1); self.assertEqual(dict(failed[0].data)['reason'], 'board_full')
        self.assertFalse(any(e.kind == 'minion_reborn' for e in g.events)); self.portable(g)

    def test_return_uses_death_controller_and_keeps_original_grant_source(self):
        g = self.game(('fr.gift', 'fr.buff', 'fr.steal', 'fr.kill'))
        old = self.gift_and_buff(g); source = self.body(g).abilities[0].source_id
        self.play(g, 'fr.steal', old); self.play(g, 'fr.kill', old)
        self.assertEqual(g.state.players[1].board, []); new = self.body(g, 2)
        self.assertEqual((new.owner, new.controller, new.health), (2, 2, 7))
        self.assertEqual(next(a for a in new.abilities if a.reborn_policy == POLICY).source_id, source)
        self.portable(g)

    def test_current_copy_carries_gift_with_new_attachment_ids(self):
        g = self.game(('fr.gift', 'fr.buff', 'fr.copy', 'fr.kill'))
        old = self.gift_and_buff(g); self.play(g, 'fr.copy', old)
        copy = g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual(copy.abilities[0].reborn_policy, POLICY)
        self.assertNotEqual(copy.abilities[0].id, self.body(g).abilities[0].id)
        self.play(g, 'fr.kill', copy.id)
        returned = g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual((returned.origin_entity_id, returned.health), (copy.id, 7)); self.portable(g)

    def test_base_copy_does_not_invent_a_gift(self):
        g = self.game(('fr.gift', 'fr.buff', 'fr.basecopy', 'fr.kill'))
        old = self.gift_and_buff(g); self.play(g, 'fr.basecopy', old)
        copy = g.state.entities[g.state.players[1].board[-1]]
        self.assertFalse(any(a.reborn_policy for a in copy.abilities))
        self.play(g, 'fr.kill', copy.id)
        self.assertEqual(g.state.players[1].board, [old]); self.assertFalse(any(e.kind == 'minion_reborn' for e in g.events))

    def test_silence_removes_gift_and_prevents_return(self):
        g = self.game(('fr.gift', 'fr.buff', 'fr.silence', 'fr.kill'))
        old = self.gift_and_buff(g); self.play(g, 'fr.silence', old); self.play(g, 'fr.kill', old)
        self.assertEqual(g.state.players[1].board, []); self.portable(g)

    def test_bounce_and_transform_reset_gift_as_an_attachment(self):
        for change in ('bounce', 'transform'):
            with self.subTest(change=change):
                g = self.game(('fr.gift', 'fr.'+change, 'fr.kill'))
                old = self.body(g).id; self.play(g, 'fr.gift', old); self.play(g, 'fr.'+change, old)
                self.assertFalse(any(a.reborn_policy for a in g.state.entities[old].abilities))
                if change == 'bounce': self.play(g, NATIVE)
                self.play(g, 'fr.kill', old); self.assertEqual(g.state.players[1].board, []); self.portable(g)

    def test_expiring_gift_does_not_override_remaining_ordinary_printed_reborn(self):
        g = self.game(('fr.tempgift', 'fr.buff', 'fr.kill'), board=('fr.reborn',))
        old = self.body(g).id; self.play(g, 'fr.tempgift', old); self.play(g, 'fr.buff', old)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g, 'fr.kill', old)
        self.assertEqual((self.body(g).max_health, self.body(g).health), (3, 1)); self.portable(g)

    def test_preserved_temporary_buff_keeps_original_expiry(self):
        g = self.game(('fr.gift', 'fr.tempbuff', 'fr.kill'))
        old = self.body(g).id; self.play(g, 'fr.gift', old); self.play(g, 'fr.tempbuff', old)
        expiry = self.body(g).enchantments[0].expires_turn; self.play(g, 'fr.kill', old)
        self.assertEqual(self.body(g).enchantments[0].expires_turn, expiry)
        g.apply(EndTurn(1)); self.assertEqual((self.body(g).attack, self.body(g).health), (2, 3))

    def test_external_health_aura_is_rederived_and_not_frozen_as_an_enchantment(self):
        g = self.game(('fr.gift', 'fr.buff', 'fr.kill', 'fr.kill'), board=(NATIVE, 'fr.aura'))
        old = self.gift_and_buff(g); self.play(g, 'fr.kill', old)
        new = self.body(g); self.assertEqual((new.max_health, new.health), (9, 9))
        self.play(g, 'fr.kill', self.find(g, 'fr.aura', zone='board'))
        self.assertEqual((self.body(g).max_health, self.body(g).health), (7, 7))

    def test_same_batch_aura_death_does_not_become_permanent_health(self):
        g = self.game(('fr.gift', 'fr.buff', 'fr.killall'), board=(NATIVE, 'fr.aura'))
        self.gift_and_buff(g); self.play(g, 'fr.killall')
        self.assertEqual((self.body(g).max_health, self.body(g).health), (7, 7)); self.portable(g)

    def test_awakening_is_not_death_and_does_not_trigger_reborn(self):
        g = self.game(('fr.gift', 'fr.sleep', 'fr.awake', 'fr.kill'))
        old = self.body(g).id; self.play(g, 'fr.gift', old); self.play(g, 'fr.sleep'); self.play(g, 'fr.awake')
        self.assertEqual(self.body(g).id, old); self.assertEqual(g.state.death_history, [])
        self.assertFalse(any(e.kind == 'minion_reborn' for e in g.events))
        self.play(g, 'fr.kill', old); self.assertEqual(self.body(g).health, 3); self.portable(g)

    def test_invalid_policy_keyword_kind_origin_and_nonremovable_declarations_rejected(self):
        for changes in ({'reborn_policy':'unknown'}, {'reborn_policy':True}, {'keyword':Keyword.TAUNT},
                        {'kind':'aura'}, {'origin':'printed'}, {'remove_on_silence':False}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                AbilityInstance(**dict(dict(id=1, kind='keyword', keyword=Keyword.REBORN, reborn_policy=POLICY), **changes))
        with self.assertRaises(ValueError): GrantKeyword(1, Keyword.TAUNT, reborn_policy=POLICY)
        ref = CardReference(1, 1, Zone.HAND, NATIVE, 0)
        with self.assertRaises(ValueError): GrantStoredKeyword(ref, Keyword.REBORN, reborn_policy=0)

    def test_hero_grant_is_rejected_with_complete_transaction_rollback(self):
        g = self.game(('fr.badhero',)); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'minion carrier'): self.play(g, 'fr.badhero')
        self.assertEqual(g.snapshot(), before)

    def test_rehashed_policy_field_corruption_and_previous_schema_rejected(self):
        g = self.game(('fr.gift',)); self.play(g, 'fr.gift', self.body(g).id)
        for value in (False, 'ordinary', 1):
            bad = deepcopy(g.snapshot()); row = bad['state']['entities'][str(self.body(g).id)]['abilities'][0]
            row['reborn_policy'] = value
            with self.assertRaises(SnapshotError) as caught: Game.from_snapshot(self.rehash(bad), registry())
            self.assertNotIn('digest mismatch', str(caught.exception))
        bad = deepcopy(g.snapshot()); del bad['state']['entities'][str(self.body(g).id)]['abilities'][0]['reborn_policy']
        with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(bad), registry())
        bad = g.snapshot(); bad['schema_version'] = 225
        with self.assertRaisesRegex(SnapshotError, '1 through 264'): Game.from_snapshot(bad, registry())

    def test_current_and_frozen_nonminion_carriers_rejected(self):
        g = self.game(('fr.gift', 'fr.kill')); old = self.body(g).id; self.play(g, 'fr.gift', old)
        bad = g.snapshot(); entity = bad['state']['entities'][str(g.state.players[1].hero_id)]
        ability = deepcopy(bad['state']['entities'][str(old)]['abilities'][0]); ability['id'] = bad['state']['next_attachment_id']
        bad['state']['next_attachment_id'] += 1; entity['abilities'].append(ability)
        with self.assertRaisesRegex(SnapshotError, 'minion carrier'): Game.from_snapshot(self.rehash(bad), registry())
        # Use an actual replaced weapon's death record so all unrelated cause,
        # physical-type and corpse checks remain valid before the policy guard.
        weapon_game = self.game(('fr.weapon', 'fr.weapon'), board=())
        self.play(weapon_game, 'fr.weapon'); self.play(weapon_game, 'fr.weapon')
        state = weapon_game.state; record = state.death_history[0]
        forbidden = AbilityInstance(state.next_attachment_id, 'keyword', keyword=Keyword.REBORN, reborn_policy=POLICY)
        state.next_attachment_id += 1
        state.death_history[0] = replace(record, abilities=(*record.abilities, forbidden))
        with self.assertRaisesRegex(ValueError, 'Frozen full-health Reborn'): validate_invariants(state, registry())

    def test_post_reborn_trigger_failure_rolls_back_new_entity_and_attachment_allocation(self):
        g = self.game(('fr.gift', 'fr.buff', 'fr.kill'), board=(NATIVE, 'fr.failwatch'))
        old = self.gift_and_buff(g); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Deliberate'): self.play(g, 'fr.kill', old)
        self.assertEqual(g.snapshot(), before); self.assertEqual(self.body(g).id, old)

    def test_failed_death_choice_preserves_waiting_then_valid_selection_finishes(self):
        g = self.game(('fr.gift', 'fr.kill'), board=('fr.wait',))
        old = self.body(g).id; self.play(g, 'fr.gift', old); self.play(g, 'fr.kill', old); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before); self.choose(g)
        self.assertEqual(self.body(g).health, 3); self.portable(g)

    def test_player_port_executes_recipe_and_hides_policy_death_material_and_enemy_hand(self):
        g = self.game(('fr.handgift', NATIVE, 'fr.kill'), board=(), enemy_hand=('fr.weapon',))
        port = g.for_player(1)
        for card in ('fr.handgift', NATIVE, 'fr.kill'):
            public = port.legal_actions(); own = public['observation']['players'][0]
            ref = next(x['ref'] for x in own['hand'] if x['card_id'] == card)
            action = next(a for a in public['actions'] if a['type'] == 'play_card' and a.get('card') == ref)
            if card == 'fr.kill':
                target = own['board'][0]['ref']
                action = next(a for a in public['actions'] if a['type'] == 'play_card' and a.get('card') == ref and a.get('target') == target)
            result = port.submit({'revision':public['revision'], 'action':action})
            self.assertTrue(result['accepted'], result['error'])
        self.assertEqual(self.body(g).health, 3)
        for seat in (1, 2):
            wire = json.dumps((g.for_player(seat).observe(), g.for_player(seat).legal_actions()), ensure_ascii=False)
            for field in ('reborn_policy', 'death_history', 'resolution_frame', 'source_sha256'):
                self.assertNotIn(field, wire)
            if seat == 1: self.assertNotIn('fr.weapon', wire)
        self.portable(g)


if __name__ == '__main__':
    unittest.main()
