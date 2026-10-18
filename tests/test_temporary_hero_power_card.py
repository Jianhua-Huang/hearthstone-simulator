"""Real two-use power, retained physical material and nested/replaced installations."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.temporary_hero_power_card import CARD, POWERS, load_batch, register_temporary_hero_power_card
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction, PlayCard, PlayerSetup,
    Registry, Scenario, SelectChoice, SnapshotError, TriggerSpec, UseHeroPower)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (ChoiceOption, GainArmor, InvokeBehavior, ReplaceHeroPower,
    RequestChoice, SetHeroPowerUses, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hero_powers import AddHeroPower, RemoveHeroPower, TriggerHeroPower
from hs_sim.engine.model import CostSpec, HeroPowerRepeatSpec, Zone
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.temporary_hero_powers import SwapTemporaryHeroPower

P, CMD = 'k214.', 'k214.cmd_'
HERO, ORIGINAL, FOREIGN, EXTRA, WATCH, SPELL, REPEAT, SPELLPOWER, LOW = (
    P+x for x in ('hero', 'original', 'foreign', 'extra', 'watch', 'spell', 'repeat', 'spellpower', 'low'))


@lru_cache(None)
def registry(mode=None):
    r = Registry(P+'host'); register_temporary_hero_power_card(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=80))
    r.register_behavior(P+'armor', lambda c: (GainArmor(c.player_id, 5),))
    r.register_behavior(P+'empty', lambda c: ())
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('Deliberate temporary power rollback')))
    for cid, cost in ((ORIGINAL, 3), (FOREIGN, 1), (EXTRA, 1)):
        r.register_card(CardDefinition(cid, cid, CardType.HERO_POWER, cost=cost, on_use=P+'armor'))
    r.register_card(CardDefinition(SPELL, SPELL, CardType.SPELL, on_play=P+'empty'))
    r.register_card(CardDefinition(REPEAT, REPEAT, CardType.MINION, health=20,
        hero_power_repeats=(HeroPowerRepeatSpec(2),)))
    r.register_card(CardDefinition(SPELLPOWER, SPELLPOWER, CardType.MINION, health=20, spell_damage=9))
    r.register_card(CardDefinition(LOW, LOW, CardType.MINION, health=4))
    commands = {
        'decorate': lambda c: (ReplaceHeroPower(c.player_id, ORIGINAL,
            cost=CostSpec(delta=-2, card_types=(CardType.HERO_POWER,)), source_id=c.source_id),
            SetHeroPowerUses(c.player_id, 3)),
        'limit': lambda c: (SetHeroPowerUses(c.player_id, 2),),
        'trigger': lambda c: (TriggerHeroPower(c.player_id, c.source_id),),
        'foreign': lambda c: (ReplaceHeroPower(c.player_id, FOREIGN, source_id=c.source_id),),
        'remove': lambda c: (RemoveHeroPower(c.player_id, source_id=c.source_id),),
        'extra': lambda c: (AddHeroPower(c.player_id, EXTRA, c.source_id),),
    }
    for name, body in commands.items():
        r.register_behavior(CMD+name, body)
        r.register_card(CardDefinition(CMD+name, name, CardType.SPELL, on_play=CMD+name))
    def watch(c):
        source = c.state.entities.get(c.event.target_id if c.event.kind == 'hero_power_replaced' else c.event.source_id)
        if source is None: return ()
        if mode == 'restore':
            if source.card_id != ORIGINAL: return ()
        elif source.card_id not in POWERS: return ()
        if mode == 'start': return (Summon(3-c.player_id, LOW, c.source_id),)
        if mode in ('nested', 'nested_second') and len(c.state.temporary_power_returns) == 1:
            wanted = POWERS[0] if mode == 'nested' else POWERS[1]
            if source.card_id == wanted: return (SwapTemporaryHeroPower(c.player_id, CARD, c.source_id),)
        if mode == 'foreign': return (ReplaceHeroPower(c.player_id, FOREIGN, source_id=c.source_id),)
        if mode == 'fail': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        if mode in ('damage', 'used', 'install', 'restore'):
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
        return ()
    r.register_behavior(P+'watch', watch)
    event = ('hero_power_used' if mode == 'used' else 'hero_power_replaced' if mode in ('install', 'restore') else
        'hero_power_started' if mode == 'start' else 'damage_dealt')
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20,
        triggers=(TriggerSpec(event, P+'watch'),)))
    r.validate(); return r


class TemporaryHeroPowerCardTests(unittest.TestCase):
    def game(self, hand=(CARD,), board=(), power=ORIGINAL, owner=1, mode=None, seed=214):
        self.owner, self.mode = owner, mode
        own = PlayerSetup(HERO, hand=hand, board=board, deck=(SPELL,)*5, mana=50, max_mana=50,
            mana_cap=50, hero_power_card_id=power)
        other = PlayerSetup(HERO, deck=(SPELL,)*5, mana=50, max_mana=50, mana_cap=50, hero_power_card_id=ORIGINAL)
        return Game.from_scenario(Scenario((own, other) if owner == 1 else (other, own),
            active_player=owner, seed=seed), registry(mode))
    def power(self, g):
        pid = g.state.players[self.owner].hero_power_id
        return g.state.entities[pid] if pid is not None else None
    def enemy(self, g): return g.state.entities[g.state.players[3-self.owner].hero_id]
    def play(self, g, cid=CARD):
        eid = next(i for i in g.state.players[self.owner].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(self.owner, eid)); return eid
    def use(self, g, power_id=None):
        g.apply(UseHeroPower(self.owner, self.power(g).id if power_id is None else power_id))
    def cycle(self, g): g.apply(EndTurn(self.owner)); g.apply(EndTurn(3-self.owner))
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def finish(self, g):
        while g.state.pending_choice is not None: self.choose(g)
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); r = registry.__wrapped__(self.mode)
        restored = Game.from_snapshot(deepcopy(saved), r)
        self.assertEqual(restored.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        return restored
    def rehash(self, data):
        data['events_hash'] = canonical_hash(data['events'])
        data['state_hash'] = canonical_hash({k: v for k, v in data.items()
            if k not in ('schema_version', 'state_hash', 'events', 'events_hash')})
        return data
    def test_three_complete_native_faces_six_primary_observations_and_profile(self):
        from hs_sim.cards import build_registry
        r = build_registry(); self.assertEqual(len(load_batch()['official_observations']), 6)
        self.assertEqual((r.card(CARD).cost, r.card(CARD).spell_school.value), (5, 'fire'))
        self.assertEqual([r.card(x).cost for x in POWERS], [2, 2])
        self.assertEqual(r.temporary_hero_power_profiles[CARD].stages, POWERS)
    def test_cast_pays_five_parks_exact_original_and_first_use_changes_face_without_refresh(self):
        g = self.game(); original = self.power(g).id; self.play(g); temporary = self.power(g).id
        self.assertEqual(g.state.players[1].mana, 45)
        self.assertEqual(g.state.entities[original].zone, Zone.SETASIDE)
        self.assertEqual(g.state.temporary_power_returns[temporary].original_id, original)
        self.use(g); self.assertEqual(self.enemy(g).health, 72)
        self.assertEqual((self.power(g).id, self.power(g).card_id, self.power(g).uses_this_turn), (temporary, POWERS[1], 1))
        before = g.snapshot()
        with self.assertRaises(IllegalAction): self.use(g)
        self.assertEqual(g.snapshot(), before); self.portable(g)
    def test_second_actual_use_returns_original_entity_cost_attachments_limit_and_ordinary_fresh_use(self):
        g = self.game((CMD+'decorate', CARD)); self.play(g, CMD+'decorate')
        original = self.power(g); self.use(g); material = (tuple(original.abilities), tuple(original.enchantments))
        self.play(g); self.use(g); self.cycle(g); self.use(g)
        restored = self.power(g)
        self.assertEqual((restored.id, restored.card_id, restored.use_limit, restored.uses_this_turn), (original.id, ORIGINAL, 3, 0))
        self.assertEqual((tuple(restored.abilities), tuple(restored.enchantments)), material)
        self.assertEqual(quote_cost(g.state, g.registry, restored).amount, 1)
        self.assertFalse(g.state.temporary_power_returns); self.assertFalse(g.state.players[1].setaside)
        self.use(g); self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 10); self.portable(g)
    def test_extra_use_limit_survives_first_face_change_and_two_uses_can_finish_same_turn(self):
        g = self.game((CARD, CMD+'limit')); original = self.power(g).id
        self.play(g); self.play(g, CMD+'limit'); self.use(g); self.use(g)
        self.assertEqual(self.enemy(g).health, 64); self.assertEqual(self.power(g).id, original)
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn, 2); self.portable(g)
    def test_payload_trigger_does_not_spend_temporary_uses_and_repeated_payload_counts_one_actual_use(self):
        g = self.game((CARD, CMD+'trigger')); self.play(g); before = g.state.players[1].mana
        self.play(g, CMD+'trigger'); self.assertEqual(self.enemy(g).health, 72)
        self.assertEqual((self.power(g).card_id, self.power(g).uses_this_turn, g.state.players[1].mana), (POWERS[0], 0, before))
        self.assertFalse(next(iter(g.state.temporary_power_returns.values())).use_ids)
        self.use(g); self.assertEqual(self.power(g).card_id, POWERS[1])
        g = self.game(board=(REPEAT, SPELLPOWER)); self.play(g); self.use(g)
        self.assertEqual(self.enemy(g).health, 64)
        self.assertEqual(len(next(iter(g.state.temporary_power_returns.values())).use_ids), 1); self.portable(g)
    def test_no_original_power_restores_empty_primary_without_inventing_a_base_skill(self):
        g = self.game(power=None); self.play(g); self.use(g); self.cycle(g); self.use(g)
        self.assertIsNone(self.power(g)); self.assertFalse(g.state.temporary_power_returns); self.portable(g)
    def test_random_pool_includes_enemy_created_by_original_power_start_reaction(self):
        g = self.game(board=(WATCH,), mode='start', seed=0); self.play(g); self.use(g)
        victim = next(e for e in g.state.entities.values() if e.card_id == LOW)
        self.assertEqual(victim.zone, Zone.GRAVEYARD)
        self.assertEqual(self.enemy(g).health, 80); self.portable(g)
    def test_additional_slot_and_its_uses_do_not_consume_or_replace_primary_return(self):
        g = self.game((CMD+'extra', CARD)); original = self.power(g).id
        self.play(g, CMD+'extra'); extra = g.state.players[1].additional_hero_power_ids[0]
        self.play(g); self.use(g, extra)
        self.assertEqual(self.power(g).card_id, POWERS[0]); self.use(g); self.cycle(g); self.use(g)
        self.assertEqual(self.power(g).id, original)
        self.assertEqual(g.state.players[1].additional_hero_power_ids, [extra]); self.portable(g)
    def test_foreign_replacement_or_removal_cancels_and_retires_original_chain(self):
        for command in ('foreign', 'remove'):
            g = self.game((CARD, CARD, CMD+command)); original = self.power(g).id
            self.play(g); self.play(g); self.play(g, CMD+command)
            self.assertFalse(g.state.temporary_power_returns); self.assertFalse(g.state.players[1].setaside)
            self.assertEqual(g.state.entities[original].zone, Zone.GRAVEYARD)
            self.assertEqual(self.power(g).card_id if self.power(g) else None, FOREIGN if command == 'foreign' else None)
            self.portable(g)
    def test_recasting_temporary_spell_returns_to_the_previous_remaining_power_before_original(self):
        g = self.game((CARD, CARD)); original = self.power(g).id
        self.play(g); first = self.power(g).id; self.use(g); self.play(g); self.use(g)
        self.cycle(g); self.use(g); self.assertEqual((self.power(g).id, self.power(g).card_id), (first, POWERS[1]))
        self.use(g); self.assertEqual(self.power(g).id, original); self.portable(g)
    def test_nested_exchange_during_first_damage_preserves_the_parked_power_progress(self):
        g = self.game(board=(WATCH,), mode='nested'); original = self.power(g).id
        self.play(g); first = self.power(g).id; self.use(g)
        self.assertNotEqual(self.power(g).id, first)
        self.assertEqual(g.state.entities[first].card_id, POWERS[1]); self.portable(g)
        self.use(g); self.cycle(g); self.use(g); self.assertEqual(self.power(g).id, first)
        self.assertEqual(g.state.temporary_power_returns[first].original_id, original)
    def test_exhausted_parked_power_splices_original_into_outer_return_instead_of_clobbering_slot(self):
        g = self.game(board=(WATCH,), mode='nested_second'); original = self.power(g).id
        self.play(g); first = self.power(g).id; self.use(g); self.cycle(g); self.use(g)
        self.assertNotEqual(self.power(g).id, first)
        self.assertEqual(g.state.entities[first].zone, Zone.GRAVEYARD)
        binding = g.state.temporary_power_returns[self.power(g).id]
        self.assertEqual(binding.original_id, original); self.assertEqual(len(g.state.temporary_power_returns), 1)
        self.portable(g)
    def test_foreign_replacement_during_damage_does_not_get_overwritten_by_completion(self):
        g = self.game(board=(WATCH,), mode='foreign'); self.play(g); self.use(g)
        self.assertEqual(self.power(g).card_id, FOREIGN); self.assertFalse(g.state.temporary_power_returns); self.portable(g)
    def test_install_damage_and_used_waits_restore_clone_replay_and_failed_choice(self):
        for mode in ('install', 'damage', 'used'):
            g = self.game(board=(WATCH,), mode=mode); self.play(g)
            if mode != 'install': self.use(g)
            self.assertIsNotNone(g.state.pending_choice); restored = self.portable(g); saved = g.snapshot()
            with self.assertRaises(ResolutionError): self.choose(g, 'fail')
            self.assertEqual(g.snapshot(), saved)
            self.finish(g); self.finish(restored); self.assertEqual(g.snapshot(), restored.snapshot())
            self.portable(g)
    def test_failed_damage_reaction_rolls_back_mana_use_phase_return_material_and_rng(self):
        g = self.game(board=(WATCH,), mode='fail'); self.play(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.use(g)
        self.assertEqual(g.snapshot(), before)
    def test_restoration_notification_wait_preserves_consumed_binding_and_original_entity(self):
        g = self.game(board=(WATCH,), mode='restore'); original = self.power(g).id
        self.play(g); self.use(g); self.cycle(g); self.use(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.power(g).id, original); self.assertFalse(g.state.temporary_power_returns)
        restored = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        self.finish(g); self.finish(restored); self.assertEqual(g.snapshot(), restored.snapshot())
    def test_both_seats_player_information_hides_parked_physical_material_and_private_bindings(self):
        for owner in (1, 2):
            g = self.game(owner=owner); self.play(g); self.use(g)
            for viewer in (1, 2):
                text = json.dumps(g.observe(viewer))
                for name in ('temporary_power_returns', 'original_epoch', 'original_order', 'use_ids', 'rng_state'):
                    self.assertNotIn(name, text)
            self.portable(g)
    def test_unbound_native_faces_and_rehashed_missing_binding_wrong_epoch_and_old_schema_reject(self):
        with self.assertRaises(ValueError): self.game(power=POWERS[0])
        g = self.game(); self.play(g); saved = g.snapshot()
        self.assertEqual(Game.from_snapshot(deepcopy(saved), registry()).snapshot(), saved)
        bad = deepcopy(saved); bad['state']['temporary_power_returns'] = {}
        with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(bad), registry())
        bad = deepcopy(saved); next(iter(bad['state']['temporary_power_returns'].values()))['original_epoch'] += 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(bad), registry())
        binding = next(iter(g.state.temporary_power_returns.values()))
        with self.assertRaises(ValueError): replace(binding, original_id=binding.power_id)
        bad = deepcopy(saved); bad['schema_version'] -= 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())


if __name__ == '__main__': unittest.main()
