"""Actual location use seeds a frozen copy before entry and native Deathrattle."""
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.corrupted_roost_card import CARD, EGG, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec, UseLocation, Zone)
from hs_sim.engine.copy_materials import CopyEntryMaterial
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage, Destroy,
    GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass, CardMetadata, NativeDeathrattleSpec, SummonQuantitySpec, TribeChangeSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.targets import canonical_digest

P = 'roost.test.'
DRAGON, OTHER, FILL, DOUBLE = (P + x for x in ('dragon', 'other', 'fill', 'double'))
BUFF, LATER_BUFF, TEMP, KILL_EGG, KILL_DRAGON, CHANGE_DRAGON, QUIET, CHANGE_EGG, BOUNCE, CURRENT, BASE, GIVE, TRIGGER, ADD_DRAGON = (
    P + x for x in ('buff', 'later_buff', 'temp', 'kill_egg', 'kill_dragon', 'change_dragon', 'quiet', 'change_egg', 'bounce', 'current', 'base', 'give', 'trigger', 'add_dragon'))
WATCH_EGG, WATCH_COPY, FAIL_EGG, POP_EGG = (P + x for x in ('watch_egg', 'watch_copy', 'fail_egg', 'pop_egg'))


@lru_cache(maxsize=None)
def registry(role):
    assert role in ('writer', 'reader')
    r = build_registry()
    r.register_behavior(P + 'bc', lambda c: (GainArmor(c.player_id, 9),))
    r.register_card(CardDefinition(DRAGON, DRAGON, CardType.MINION, cost=4, attack=3, health=6,
        battlecry=P + 'bc', metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('dragon',))))
    r.register_card(CardDefinition(OTHER, OTHER, CardType.MINION, attack=1, health=4,
        metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('beast',))))
    r.register_card(CardDefinition(DOUBLE, DOUBLE, CardType.MINION, health=5, summon_quantities=(SummonQuantitySpec(),)))
    def entity(c, card):
        return next(c.state.entities[i] for pid in (1, 2) for i in c.state.players[pid].board
            if c.state.entities[i].card_id == card)
    def buff(c):
        e = entity(c, DRAGON)
        return (Buff(e.id, 2, 3, c.source_id), Damage(e.id, 2, c.source_id))
    scripts = {
        FILL: lambda c: (), BUFF: buff, LATER_BUFF: lambda c: (Buff(entity(c, DRAGON).id, 4, 4, c.source_id),),
        TEMP: lambda c: (Buff(entity(c, DRAGON).id, 5, 0, c.source_id, expires_turn=c.state.turn),),
        KILL_EGG: lambda c: (Destroy(entity(c, EGG).id, c.source_id),),
        KILL_DRAGON: lambda c: (Destroy(entity(c, DRAGON).id, c.source_id),),
        CHANGE_DRAGON: lambda c: (Transform(entity(c, DRAGON).id, OTHER),),
        QUIET: lambda c: (Silence(entity(c, EGG).id),), CHANGE_EGG: lambda c: (Transform(entity(c, EGG).id, OTHER),),
        BOUNCE: lambda c: (ReturnToHand(entity(c, EGG).id),),
        CURRENT: lambda c: (CopyMinion(entity(c, EGG).id, c.player_id),),
        BASE: lambda c: (CopyMinion(entity(c, EGG).id, c.player_id, mode='base'),),
        GIVE: lambda c: (ChangeControl(entity(c, EGG).id, 2),),
        TRIGGER: lambda c: (TriggerDeathrattles(entity(c, EGG).id, c.source_id),),
        ADD_DRAGON: lambda c: (ChangeMinionTribes(MinionReference.capture(entity(c, OTHER)),
            TribeChangeSpec('add', ('dragon',)), c.source_id),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body); r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    def fail(c): raise ResolutionError('Deliberate Egg entry failure')
    r.register_behavior(P + 'fail', fail)
    def watch(c, mode):
        e = c.state.entities[c.event.target_id]
        if mode != 'copy' and e.card_id != EGG: return ()
        if mode == 'copy':
            roots = c.state.card_summon_history
            if not roots or not isinstance(roots[-1].request.materials[0], CopyEntryMaterial) or roots[-1].request.materials[0].profile != 'remembered_copy': return ()
        if mode == 'fail': return (InvokeBehavior(P + 'fail', c.source_id, c.player_id),)
        if mode == 'pop': return (Destroy(e.id, c.source_id),)
        if mode == 'egg' and not any(a.deathrattle_memory is not None and a.deathrattle_memory.summon_copy is not None for a in e.abilities):
            raise ResolutionError('Egg entry published before its native memory')
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
            ChoiceOption('hatch', 'Hatch original Egg', (Destroy(e.id, c.source_id),)),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P + 'fail', c.source_id, c.player_id),))), c.source_id),)
    for cid, mode in ((WATCH_EGG, 'egg'), (WATCH_COPY, 'copy'), (FAIL_EGG, 'fail'), (POP_EGG, 'pop')):
        r.register_behavior(cid, lambda c, mode=mode: watch(c, mode))
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=5, triggers=(TriggerSpec('minion_summoned', cid),)))
    r.validate(); r.freeze(); return r


class CorruptedRoostTests(unittest.TestCase):
    def game(self, hand=(CARD, KILL_EGG), *, board=(DRAGON,), enemy_board=(), active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(FILL,) * 25, mana=10, max_mana=10,
                hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', board=enemy_board, deck=(FILL,) * 25, mana=10, max_mana=10,
                hero_power_card_id='HERO_08bp')), active_player=active, seed=262), registry('writer'))
    def play(self, g, cid=CARD):
        pid = g.state.active_player; eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid, eid)); return eid
    def use(self, g, location=None, target=None):
        pid = g.state.active_player
        location = location if location is not None else next(i for i in g.state.players[pid].board if g.state.entities[i].card_id == CARD)
        target = target if target is not None else next(i for i in g.state.players[pid].board if g.state.entities[i].card_id == DRAGON)
        g.apply(UseLocation(pid, location, target))
    def eggs(self, g, pid=1): return [i for i in g.state.players[pid].board if g.state.entities[i].card_id == EGG]
    def copies(self, g, pid=1):
        return [d.entity.entity_id for root in g.state.card_summon_history
            if isinstance(root.request.materials[0], CopyEntryMaterial) and root.request.materials[0].profile == 'remembered_copy'
            for d in root.deliveries if d.entity is not None and d.entity.controller == pid]
    def end(self, g): g.apply(EndTurn(g.state.active_player))
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(snap, registry('reader'))
        self.assertEqual(other.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry('reader')).snapshot(), snap); return other

    def test_a00_complete_location_egg_and_four_full_primary_faces(self):
        d = load_batch(); r = registry('writer'); self.assertEqual(len(d['official_observations']), 4)
        self.assertEqual((r.card(CARD).cost, r.card(CARD).durability), (2, 2))
        self.assertEqual((r.card(EGG).cost, r.card(EGG).attack, r.card(EGG).health), (1, 0, 2))
        self.assertEqual(d['dependencies'][0]['record']['text'], '<b>亡语：</b>召唤{0}。')
        self.assertFalse(r.card(EGG).metadata.collectible)

    def test_a01_paid_location_use_and_actual_egg_death_summon_original_dragon_copy(self):
        g = self.game(); source = g.state.players[1].board[0]; location = self.play(g); self.use(g)
        egg = self.eggs(g)[0]; self.assertEqual(g.state.players[1].mana, 8)
        self.assertEqual((g.state.entities[location].durability, g.state.entities[egg].attack, g.state.entities[egg].health), (1, 0, 2))
        self.play(g, KILL_EGG); copy = self.copies(g)[0]
        self.assertNotEqual(copy, source); self.assertIn(source, g.state.players[1].board)
        self.assertEqual(g.state.entities[copy].card_id, DRAGON)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)
        self.assertEqual(g.state.entities[egg].zone, Zone.GRAVEYARD)

    def test_a02_target_rule_uses_current_public_dragon_not_hero_enemy_or_printed_guess(self):
        g = self.game((CARD, ADD_DRAGON), board=(OTHER,), enemy_board=(DRAGON,)); loc = self.play(g)
        for target in (g.state.players[1].hero_id, g.state.players[2].board[0], g.state.players[1].board[0]):
            with self.subTest(target=target), self.assertRaises(IllegalAction): self.use(g, loc, target)
        self.play(g, ADD_DRAGON); self.use(g, loc, g.state.players[1].board[0]); self.assertEqual(len(self.eggs(g)), 1)

    def test_a03_full_board_consumes_location_use_without_fake_egg_or_rng(self):
        g = self.game(board=(DRAGON,) + (OTHER,) * 5); loc = self.play(g); rng = g._rng.getstate(); self.use(g)
        self.assertFalse(self.eggs(g)); self.assertEqual(g._rng.getstate(), rng)
        self.assertEqual(g.state.entities[loc].durability, 1)

    def test_a04_cooldown_and_last_use_follow_existing_location_lifecycle(self):
        g = self.game(); loc = self.play(g); self.use(g)
        with self.assertRaises(IllegalAction): self.use(g)
        for _ in range(4): self.end(g)
        self.use(g, loc); self.assertEqual(g.state.entities[loc].zone, Zone.GRAVEYARD)
        self.assertEqual(len(self.eggs(g)), 2)

    def test_b00_initial_current_buffs_and_damage_are_frozen_later_buffs_do_not_rebind(self):
        g = self.game((CARD, BUFF, LATER_BUFF, KILL_EGG)); self.play(g); self.play(g, BUFF); self.use(g)
        self.play(g, LATER_BUFF); self.play(g, KILL_EGG); e = g.state.entities[self.copies(g)[0]]
        self.assertEqual((e.attack, e.max_health, e.damage), (5, 9, 2))

    def test_b01_official_original_dragon_transform_or_death_does_not_replace_memory(self):
        for operation in (CHANGE_DRAGON, KILL_DRAGON):
            with self.subTest(operation=operation):
                g = self.game((CARD, operation, KILL_EGG)); self.play(g); self.use(g); self.play(g, operation); self.play(g, KILL_EGG)
                self.assertEqual(g.state.entities[self.copies(g)[0]].card_id, DRAGON)

    def test_b02_egg_silence_or_transform_removes_its_native_deathrattle_payload(self):
        for operation in (QUIET, CHANGE_EGG):
            with self.subTest(operation=operation):
                g = self.game((CARD, operation, KILL_EGG)); self.play(g); self.use(g); egg = self.eggs(g)[0]; self.play(g, operation)
                if operation == QUIET: self.play(g, KILL_EGG)
                else: self.assertEqual(g.state.entities[egg].card_id, OTHER)
                self.assertFalse(self.copies(g))

    def test_b03_current_egg_copy_keeps_frozen_payload_and_base_copy_has_empty_native_memory(self):
        for operation, count in ((CURRENT, 2), (BASE, 1)):
            with self.subTest(operation=operation):
                g = self.game((CARD, operation, KILL_EGG, KILL_EGG)); self.play(g); self.use(g); self.play(g, operation)
                self.play(g, KILL_EGG); self.play(g, KILL_EGG); self.assertEqual(len(self.copies(g)), count)

    def test_b04_egg_control_change_delivers_to_current_deathrattle_controller(self):
        g = self.game((CARD, GIVE, KILL_EGG)); self.play(g); self.use(g); self.play(g, GIVE); self.play(g, KILL_EGG)
        copy = self.copies(g, 2)[0]; self.assertEqual((g.state.entities[copy].controller, g.state.entities[copy].owner), (2, 2))

    def test_b05_non_death_invocation_uses_same_native_payload_and_leaves_egg_alive(self):
        g = self.game((CARD, TRIGGER, KILL_EGG)); self.play(g); self.use(g); egg = self.eggs(g)[0]; self.play(g, TRIGGER)
        self.assertIn(egg, g.state.players[1].board); self.assertEqual(len(self.copies(g)), 1)
        self.play(g, KILL_EGG); self.assertEqual(len(self.copies(g)), 2)

    def test_b06_return_replay_uses_existing_reset_empty_memory_policy(self):
        g = self.game((CARD, BOUNCE, KILL_EGG)); self.play(g); self.use(g); self.play(g, BOUNCE); self.play(g, EGG)
        self.play(g, KILL_EGG); self.assertFalse(self.copies(g))

    def test_c00_quantity_extras_seed_independent_eggs_and_reuse_original_copy_recipe(self):
        g = self.game(board=(DRAGON, DOUBLE)); self.play(g); self.use(g); eggs = self.eggs(g)
        self.assertEqual(len(eggs), 2)
        ids = [next(a.id for a in g.state.entities[i].abilities if a.deathrattle_memory is not None) for i in eggs]
        self.assertEqual(len(set(ids)), 2); self.play(g, KILL_EGG); self.assertEqual(len(self.copies(g)), 2)

    def test_c01_immediate_entry_death_already_has_complete_dragon_memory(self):
        g = self.game(board=(DRAGON, POP_EGG)); self.play(g); self.use(g)
        self.assertFalse(self.eggs(g)); self.assertEqual(len(self.copies(g)), 1)

    def test_c02_lapsed_turn_buff_in_remembered_material_is_not_restarted(self):
        g = self.game((CARD, TEMP, KILL_EGG)); self.play(g); self.play(g, TEMP); self.use(g)
        self.end(g); self.end(g); self.play(g, KILL_EGG)
        self.assertEqual(g.state.entities[self.copies(g)[0]].attack, 3)

    def test_c03_real_murozond_lapsed_start_deadline_cannot_be_restarted_by_later_hatch(self):
        g = self.game((CARD, 'TIME_024', KILL_EGG)); self.play(g); self.end(g); self.end(g)
        dragon = self.play(g, 'TIME_024'); self.use(g, target=dragon)
        for _ in range(4): self.end(g)
        self.play(g, KILL_EGG); e = g.state.entities[self.copies(g)[0]]
        self.assertEqual(e.card_id, 'TIME_024'); self.assertEqual(e.attack, 8)
        self.assertFalse(any(a.limited_trigger_deadline is not None for a in e.abilities))

    def test_d00_seeded_entry_wait_restores_clones_replays_and_failed_resume_keeps_original(self):
        g = self.game(board=(DRAGON, WATCH_EGG)); self.play(g); self.use(g); other = self.portable(g); snap = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Deliberate Egg entry failure'): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), snap); self.choose(g, 'hatch'); self.choose(other, 'hatch')
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(len(self.copies(g)), 1)

    def test_d01_hatched_copy_reaction_wait_restores_delayed_material_and_original_finish(self):
        g = self.game(board=(DRAGON, WATCH_COPY)); self.play(g); self.use(g); self.end(g); self.end(g); self.play(g, KILL_EGG)
        other = self.portable(g); self.choose(g); self.choose(other); self.assertEqual(g.snapshot(), other.snapshot())

    def test_d02_late_entry_failure_rolls_back_use_durability_cooldown_and_memory(self):
        g = self.game(board=(DRAGON, FAIL_EGG)); self.play(g); snap = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Deliberate Egg entry failure'): self.use(g)
        self.assertEqual(g.snapshot(), snap)

    def test_d03_memory_future_capture_tampering_rejects_after_rehash_and_views_hide_payload(self):
        g = self.game(); self.play(g); self.use(g); egg = self.eggs(g)[0]
        for pid in (1, 2):
            wire = json.dumps(g.for_player(pid).observe()) + json.dumps(g.player_events(pid))
            for key in ('"summon_copy"', '"deathrattle_memory"', '"next_attachment_id"', '"local"'):
                self.assertNotIn(key, wire)
        snap = g.snapshot(); a = next(a for a in snap['state']['entities'][str(egg)]['abilities'] if a['deathrattle_memory'] is not None)
        a['deathrattle_memory']['summon_copy']['captured_turn'] += 5
        keys = ('ruleset', 'registry_fingerprint', 'mechanics_version', 'state', 'rng_state',
            'resolution_frame', 'rewind_session', 'match_setup', 'generation_context', 'information')
        snap['state_hash'] = canonical_digest({k: snap[k] for k in keys})
        with self.assertRaises(ValueError): Game.from_snapshot(snap, registry('reader'))


if __name__ == '__main__': unittest.main()
