"""Real Raith entry, whole resurrection completion and original-residence attacks."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_actual_reborn_cards import CARD, BODY, load_batch, register_native_actual_reborn_cards
from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard, PlayerSetup, Registry,
    RewindSpec, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone, successful_reborns)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, Damage, Destroy, InvokeBehavior,
    RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_sources import Resurrect, ResurrectMinion
from hs_sim.engine.summon_quantities import GrantSummonQuantity, SummonCause
from hs_sim.engine.model import SummonQuantitySpec

P = 'k165b.'
HERO, A, B, PLAIN, ENEMY, WATCH = (P + x for x in ('hero', 'a', 'b', 'plain', 'enemy', 'watch'))
KILL, BOUNCE, SILENCE, COPY_RES, FILL, REWIND = (P + x for x in ('kill', 'bounce', 'silence', 'res', 'fill', 'rewind'))
QUANTITY = P + 'quantity'


@lru_cache(maxsize=None)
def registry(mode=None, role='writer'):
    r = Registry('raith-' + str(mode))
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=30))
    for cid, attack, health, keywords in ((A, 2, 3, (Keyword.REBORN,)), (B, 3, 4, (Keyword.REBORN,)),
            (PLAIN, 1, 4, ()), (ENEMY, 0, 50, ())):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1, attack=attack, health=health, keywords=keywords))
    register_native_actual_reborn_cards(r)
    bodies = {KILL: lambda c: (Destroy(c.target_id, c.source_id),), BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        SILENCE: lambda c: (Silence(c.target_id),), FILL: lambda c: tuple(Summon(c.player_id, PLAIN) for _ in range(5)),
        COPY_RES: lambda c: (ResurrectMinion(c.player_id, c.state.death_history[0].id, source_id=c.source_id),),
        QUANTITY: lambda c: (GrantSummonQuantity(c.target_id, SummonQuantitySpec(source_kinds=(CardType.MINION,)), c.source_id),),
        REWIND: lambda c: (Resurrect(c.player_id, len(successful_reborns(c.state, c.player_id)),
            source_id=c.source_id, cause=SummonCause.capture(c),
            death_ids=tuple(x.reborn_death_id for x in successful_reborns(c.state, c.player_id)), attack_after_all=True),)}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        target = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)) if cid in (KILL, BOUNCE, SILENCE, QUANTITY) else None
        extra = dict(keywords=(Keyword.REWIND,), rewind=RewindSpec()) if cid == REWIND else {}
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, targeting=target, **extra))
    def fail(c): raise ResolutionError('K165-B deliberate reaction failure')
    r.register_behavior(P + 'fail', fail)
    def reenter(c):
        from hs_sim.engine.summon_sources import SummonFromStoredCandidates
        from hs_sim.engine.zones import CardReference
        return (SummonFromStoredCandidates(1, (CardReference.capture(c.state.entities[c.target_id]),)),)
    r.register_behavior(P + 'reenter', reenter)
    def watch(c):
        roots = c.state.resurrection_summon_history
        if not roots or roots[-1].spec.attack_after_all is not True: return ()
        root = roots[-1]
        event = c.event
        if event.kind == 'minion_summoned':
            if root.status != 'active' or event.target_id not in {d.entity.entity_id for x in c.state.card_summon_history
                    if x.request.producer_link is not None for d in x.deliveries if d.entity is not None}: return ()
        elif event.kind == 'random_choice':
            if root.attacks is None or event.target_id not in {x.entity_id for x in root.attacks.members}: return ()
        elif event.kind in ('attack_declared', 'attack_finished'):
            if root.attacks is None or event.source_id not in {x.entity_id for x in root.attacks.members}: return ()
        else: return ()
        if mode == 'fatal': return (Damage(c.state.players[2].hero_id, 100, c.source_id),)
        if mode == 'fail': return (InvokeBehavior(P + 'fail', c.source_id, 1),)
        if mode == 'entry':
            target = event.target_id
            options = (ChoiceOption('ok', 'Continue'), ChoiceOption('kill', 'Kill original', (Destroy(target, c.source_id),)),
                ChoiceOption('take', 'Transfer original', (ChangeControl(target, 2),)),
                ChoiceOption('transform', 'Transform original', (Transform(target, PLAIN),)),
                ChoiceOption('reenter', 'Leave and reenter', (ReturnToHand(target), InvokeBehavior(P + 'reenter', c.source_id, 1, target_id=target))))
        elif mode == 'random':
            target = event.target_id
            options = (ChoiceOption('ok', 'Continue'), ChoiceOption('take', 'Transfer attacker', (ChangeControl(target, 2),)),
                ChoiceOption('kill_enemy', 'Remove selected defender', (Destroy(dict(event.data)['defender_id'], c.source_id),)))
        else: options = (ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Rollback', (InvokeBehavior(P + 'fail', c.source_id, 1),)))
        return (RequestChoice(1, options, c.source_id),)
    if mode:
        kinds = ('minion_summoned',) if mode in ('entry', 'fail') else ('random_choice',) if mode == 'random' else (
            'minion_summoned', 'random_choice', 'attack_declared', 'attack_finished') if mode == 'all' else ('attack_declared',)
        r.register_behavior(P + 'watch', watch)
        r.register_card(CardDefinition(WATCH, WATCH, CardType.WEAPON, durability=4,
            triggers=tuple(TriggerSpec(kind, P + 'watch') for kind in kinds)))
    r.validate(); r.freeze(); return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class RaithVanGeistTests(unittest.TestCase):
    def game(self, mode=None, hand=(KILL, KILL, CARD), board=(A, B), enemy=(ENEMY, ENEMY)):
        self.mode = mode
        extra = dict(weapon_card_id=WATCH) if mode else {}
        return Game.from_scenario(Scenario((PlayerSetup(HERO, hand=hand, board=board, deck=(PLAIN,) * 8,
            mana=30, max_mana=30, mana_cap=30, **extra), PlayerSetup(HERO, board=enemy, deck=(PLAIN,) * 8)), seed=1652), registry(mode))
    def first(self, g, cid, zone='board', pid=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[pid], zone) if g.state.entities[i].card_id == cid)
    def play(self, g, cid, target=None):
        e = self.first(g, cid, 'hand')
        g.apply(PlayCard(1, e.id, target_id=target, position=len(g.state.players[1].board) if e.kind == CardType.MINION else None))
        return e.id
    def history(self, g):
        for cid in (A, B): self.play(g, KILL, self.first(g, cid).id)
        self.assertEqual(len(successful_reborns(g.state, 1)), 2)
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def finish(self, g):
        for _ in range(35):
            if g.state.pending_choice is None: return
            self.choose(g)
        self.fail('Native group failed to finish')
    def portable(self, g):
        reader = registry(self.mode, 'reader'); self.assertIsNot(reader, g.registry)
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, reader)
        self.assertEqual(restored.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        replayed = replay(build_replay(g), reader)
        self.assertEqual(replayed.snapshot(), g.snapshot())
        return restored
    def corrupt(self, g, edit):
        saved = deepcopy(g.snapshot()); edit(saved)
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(saved), registry(self.mode, 'reader'))
    def attacks(self, g): return [e for e in g.events if e.kind == 'attack_declared']

    def test_a0_full_source_definition_and_typed_request_guards(self):
        raw = load_batch()['cards'][0]['record']; card = registry().card(CARD)
        self.assertEqual((card.name, card.cost, card.attack, card.health, card.battlecry), (raw['name'], 7, 5, 5, BODY))
        for kwargs in (dict(death_ids=(True,)), dict(death_ids=(1, 1)), dict(attack_after_all=1), dict(death_ids=()), dict(attack_after_all=True)):
            with self.assertRaises(ValueError): Resurrect(1, **kwargs)

    def test_a1_real_battlecry_resurrects_all_then_each_original_body_attacks(self):
        g = self.game(); self.history(g); source = self.play(g, CARD); root, = g.state.resurrection_summon_history
        self.assertEqual(root.spec.death_ids, tuple(x.reborn_death_id for x in successful_reborns(g.state, 1)))
        self.assertEqual((root.status, root.attacks.status, root.attacks.index), ('completed', 'completed', 2))
        self.assertEqual([e.source_id for e in self.attacks(g)], [x.entity_id for x in root.attacks.members])
        self.assertTrue(all(e.source_id != source for e in self.attacks(g)))
        deliveries = [e.sequence for e in g.events if e.kind == 'resurrection_delivery_bound']
        self.assertLess(max(deliveries), min(e.sequence for e in self.attacks(g)))
        self.assertEqual(g.state.players[1].mana, 23); self.portable(g)

    def test_a2_no_successful_reborn_is_empty_without_rng(self):
        g = self.game(hand=(CARD,), board=(A,)); before = g._rng.getstate(); self.play(g, CARD)
        root, = g.state.resurrection_summon_history
        self.assertEqual((root.spec.death_ids, root.attacks.members, root.attacks.status), ((), (), 'completed'))
        self.assertEqual(g._rng.getstate(), before); self.assertFalse(self.attacks(g)); self.portable(g)

    def test_a3_no_enemy_minions_consumes_no_attack_rng(self):
        g = self.game(enemy=()); self.history(g); self.play(g, CARD)
        root, = g.state.resurrection_summon_history
        self.assertFalse(self.attacks(g)); self.assertEqual(root.attacks.index, 2)
        self.assertFalse([e for e in g.events if e.kind == 'random_choice']); self.portable(g)

    def test_a4_current_reborn_keyword_is_not_actual_reborn_history(self):
        g = self.game(hand=(SILENCE, KILL, KILL, COPY_RES, CARD))
        self.play(g, SILENCE, self.first(g, A).id); self.play(g, KILL, self.first(g, A).id)
        self.play(g, COPY_RES); self.play(g, KILL, self.first(g, B).id); self.play(g, CARD)
        root, = g.state.resurrection_summon_history
        self.assertEqual(len(root.spec.death_ids), 1); self.assertEqual(len(root.attacks.members), 1)
        self.assertEqual(root.attacks.members[0].card_id, B); self.portable(g)

    def test_a5_capacity_is_checked_for_whole_return_group_before_any_attack(self):
        g2 = self.game(hand=(KILL, KILL, CARD), board=(A, B, PLAIN, PLAIN, PLAIN, PLAIN))
        self.history(g2); self.play(g2, CARD); root, = g2.state.resurrection_summon_history
        self.assertEqual((root.status, len(root.attacks.members)), ('board_full', 0)); self.portable(g2)
        g = self.game(board=(A, B, PLAIN, PLAIN, PLAIN)); self.history(g); self.play(g, CARD)
        root, = g.state.resurrection_summon_history
        self.assertEqual((root.status, len(root.attacks.members), len(self.attacks(g))), ('board_full', 1, 1)); self.portable(g)

    def test_a6_same_physical_minion_reborns_again_as_separate_death(self):
        g = self.game(hand=(KILL, BOUNCE, KILL, CARD), board=(A,))
        self.play(g, KILL, self.first(g, A).id); original = self.first(g, A).id
        self.play(g, BOUNCE, original); self.play(g, A); self.play(g, KILL, original); self.play(g, CARD)
        root, = g.state.resurrection_summon_history
        self.assertEqual(len(root.spec.death_ids), 2); self.assertEqual(len(root.attacks.members), 2); self.portable(g)

    def test_b0_every_waiting_window_resumes_with_independent_registry_and_replay(self):
        g = self.game(mode='all'); self.history(g); self.play(g, CARD); count = 0; seen = set()
        for _ in range(12):
            if g.state.pending_choice is None: break
            root, = g.state.resurrection_summon_history
            plan = root.attacks
            terminal = next((x.terminal is not None for x in g.state.character_attack_history if plan is not None and x.declaration.id == plan.window_id), None)
            phase = (root.status, None if plan is None else plan.stage, terminal)
            restored = None
            if phase not in seen:
                saved = json.loads(json.dumps(g.snapshot())); restored = Game.from_snapshot(saved, registry(self.mode, 'reader'))
                self.assertEqual(restored.snapshot(), saved); seen.add(phase)
                self.choose(restored)
            self.choose(g)
            if restored is not None: self.assertEqual(restored.snapshot(), g.snapshot())
            count += 1
        self.assertIsNone(g.state.pending_choice); self.assertEqual(count, 8)
        self.assertEqual(len(seen), 4); self.assertEqual(len(self.attacks(g)), 2); self.portable(g)

    def test_b1_dead_original_return_is_skipped_without_borrowing_its_reborn(self):
        g = self.game(mode='entry'); self.history(g); self.play(g, CARD)
        old = g.state.card_summon_history[0].deliveries[0].entity.entity_id
        self.choose(g, 'kill'); self.finish(g)
        self.assertNotIn(old, [e.source_id for e in self.attacks(g)])
        self.assertEqual(len(self.attacks(g)), 1); self.assertGreater(len(successful_reborns(g.state, 1)), 2); self.portable(g)

    def test_b2_control_changed_original_return_is_skipped(self):
        g = self.game(mode='entry'); self.history(g); self.play(g, CARD); self.choose(g, 'take'); self.finish(g)
        self.assertEqual(len(self.attacks(g)), 1); self.portable(g)

    def test_b3_same_entity_reentered_cannot_replace_original_board_presence(self):
        g = self.game(mode='entry'); self.history(g); self.play(g, CARD); self.choose(g, 'reenter'); self.finish(g)
        self.assertEqual(len(self.attacks(g)), 1); self.portable(g)

    def test_b4_continuous_transformed_return_keeps_original_attack_obligation(self):
        g = self.game(mode='entry'); self.history(g); self.play(g, CARD); self.choose(g, 'transform'); self.finish(g)
        self.assertEqual(len(self.attacks(g)), 2); self.portable(g)

    def test_b5_random_choice_reactions_can_remove_selected_enemy_without_retargeting(self):
        g = self.game(mode='random'); self.history(g); self.play(g, CARD); self.choose(g, 'kill_enemy'); self.finish(g)
        self.assertEqual(len(self.attacks(g)), 1); self.portable(g)

    def test_b6_random_choice_control_change_does_not_attack_for_other_player(self):
        g = self.game(mode='random'); self.history(g); self.play(g, CARD); self.choose(g, 'take'); self.finish(g)
        self.assertEqual(len(self.attacks(g)), 1); self.portable(g)

    def test_b7_failed_choice_rolls_back_group_progress_rng_and_snapshot(self):
        g = self.game(mode='all'); self.history(g); self.play(g, CARD); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate reaction failure'): self.choose(g, 'bad')
        self.assertEqual(saved, g.snapshot()); self.finish(g); self.portable(g)

    def test_b8_failure_during_entry_rolls_back_paid_real_card_and_whole_batch(self):
        g = self.game(mode='fail'); self.history(g); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate reaction failure'): self.play(g, CARD)
        self.assertEqual(g.snapshot(), saved); self.assertFalse(g.state.resurrection_summon_history)

    def test_b9_terminal_during_forced_combat_interrupts_remaining_original_group(self):
        g = self.game(mode='fatal'); self.history(g); self.play(g, CARD)
        self.assertEqual(g.state.status, 'finished'); root, = g.state.resurrection_summon_history
        self.assertEqual(root.attacks.status, 'interrupted'); self.assertEqual(len(self.attacks(g)), 1); self.portable(g)

    def test_c0_current_group_member_or_progress_tampering_rejected(self):
        g = self.game(); self.history(g); self.play(g, CARD)
        self.corrupt(g, lambda s: s['state']['resurrection_summon_history'][0]['attacks']['members'].reverse())
        self.corrupt(g, lambda s: s['state']['resurrection_summon_history'][0]['attacks'].update(index=1, status='active'))
        self.corrupt(g, lambda s: s['state']['resurrection_summon_history'][0]['spec'].update(death_ids=[]))

    def test_c1_waiting_owed_group_control_cannot_be_deleted_or_duplicated(self):
        g = self.game(mode='random'); self.history(g); self.play(g, CARD)
        def controls(saved):
            return saved['resolution_frame']['fields']['continuation']['tuple']
        def delete(saved):
            work = controls(saved); index = next(i for i, x in enumerate(work) if x.get('type', '').endswith('FinishResurrectionAttack')); work.pop(index)
        def duplicate(saved):
            work = controls(saved); work.extend(deepcopy([x for x in work if x.get('type', '').endswith('ApplyResurrectionAttack')]))
        self.corrupt(g, delete); self.corrupt(g, duplicate); self.finish(g); self.portable(g)

    def test_c2_internal_materials_progress_and_queue_do_not_enter_player_dto(self):
        g = self.game(mode='all'); self.history(g); self.play(g, CARD)
        for pid in (1, 2):
            text = json.dumps(g.for_player(pid).observe(), ensure_ascii=False) + json.dumps(g.player_events(pid))
            for hidden in ('resurrection_attacks_progress', 'resurrection_summon_history', 'resurrection_batch_accepted', 'ContinueResurrectionAttacks', 'rng_before'):
                self.assertNotIn(hidden, text)
        self.finish(g)

    def test_c3_rewind_retires_original_completed_group_and_builds_a_fresh_one(self):
        g = self.game(hand=(KILL, KILL, REWIND)); self.history(g); self.play(g, REWIND)
        self.assertIsNotNone(g.state.pending_choice); self.portable(g)
        old = g.state.resurrection_summon_history[0].id
        self.choose(g, 'retry'); self.assertIsNone(g.state.pending_choice)
        root, = g.state.resurrection_summon_history
        self.assertGreater(root.id, old); self.assertEqual(root.attacks.status, 'completed'); self.portable(g)

    def test_d0_quantity_extras_are_actual_group_members_and_attack_after_all_entries(self):
        g = self.game(hand=(KILL, QUANTITY, CARD), board=(A,))
        self.play(g, KILL, self.first(g, A).id); self.play(g, QUANTITY, self.first(g, A).id); self.play(g, CARD)
        root, = g.state.resurrection_summon_history
        self.assertEqual((len(root.picks), len(root.attacks.members), len(self.attacks(g))), (1, 2, 2))
        self.assertLess(max(e.sequence for e in g.events if e.kind == 'resurrection_delivery_bound'), self.attacks(g)[0].sequence)
        self.portable(g)

    def test_d1_second_player_uses_own_reborn_history_and_actual_enemy(self):
        self.mode = None
        g = Game.from_scenario(Scenario((PlayerSetup(HERO, board=(ENEMY,), deck=(PLAIN,) * 4),
            PlayerSetup(HERO, board=(A,), hand=(KILL, CARD), deck=(PLAIN,) * 4, mana=20, max_mana=20, mana_cap=20)), active_player=2), registry())
        killer = self.first(g, KILL, 'hand', 2); victim = self.first(g, A, pid=2)
        g.apply(PlayCard(2, killer.id, target_id=victim.id))
        card = self.first(g, CARD, 'hand', 2); g.apply(PlayCard(2, card.id, position=1))
        root, = g.state.resurrection_summon_history
        self.assertEqual((root.spec.player_id, len(root.attacks.members)), (2, 1))
        self.assertTrue(all(e.player_id == 2 for e in self.attacks(g))); self.portable(g)


if __name__ == '__main__': unittest.main()
